"""CareCompass workflow orchestrator.

Transport-agnostic: the ACP coordinator agent, the CLI demo and the tests all call
`CareCompassWorkflow.handle(...)`. Research is reached through a ResearchClient, which in
production sends typed uAgent messages to the Hospital and Insurer agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass

from app.config import Settings
from app.database.models import CareCase
from app.database.repository import Repository
from app.intelligence import explainer
from app.intelligence.asi1_client import ASI1Client
from app.intelligence.care_knowledge import declines_insurance, find_insurer
from app.intelligence.intent_parser import IntentParser
from app.intelligence.question_engine import plan_questions
from app.intelligence.safety_router import assess
from app.matching.decision_rules import apply_candidate_rules, r7_routine_ranking_allowed, r8_requires_approval
from app.matching.evidence_engine import build_candidates
from app.matching.ranking import rank
from app.matching.result_verifier import verify
from app.research.service import ResearchClient, ResearchOutcome
from app.schemas.actions import ActionStatus
from app.schemas.hospital import Eligibility, HospitalResearchQuery, RankedCandidate
from app.schemas.input import CareRequest, Urgency
from app.schemas.insurance import InsuranceState, InsurerResearchQuery
from app.ui import text_fallback as tf
from app.ui.card_builder import Card, detail_card, review_card, shortlist_card
from app.ui.card_handlers import Selection, parse_selection
from app.workflow.action_executor import ACTION, ActionExecutor
from app.workflow.approval import build_payload, payload_hash
from app.workflow.state_machine import SHORTLIST_STATES, CaseState, can_transition, transition

log = logging.getLogger(__name__)
SHORTLIST_SIZE = 3

RESET = re.compile(r"^\s*(?:reset|start over|new search|restart)\s*[.!]?\s*$", re.I)
DELETE = re.compile(r"\bdelete (?:my|all)? ?(?:data|information|records?)\b", re.I)
HELP = re.compile(r"^\s*(?:help|\?|what can you do\??)\s*$", re.I)
RETRY = re.compile(r"^\s*(?:retry|try again)\s*[.!]?\s*$", re.I)
SHOW = re.compile(r"\bshow\s+(CC-[A-Z0-9]{8})\b", re.I)

WELCOME = ("Hi! I'm **CareCompass**. Tell me your health concern and city - for example *\"I have a kidney stone, "
           "I'm in Delhi and have Star Health insurance\"* - or paste the key lines of a medical report. "
           "I'll research suitable hospitals, check insurer network evidence, and save a verified shortlist when you approve.")
HELP_TEXT = (WELCOME + "\n\nCommands: **new search**, **retry**, **show CC-XXXXXXXX**, **delete my data**.")


@dataclass
class Reply:
    text: str
    card: Card | None = None
    end_session: bool = False


class CareCompassWorkflow:
    def __init__(self, repo: Repository, settings: Settings, asi1: ASI1Client | None = None):
        self.repo = repo
        self.settings = settings
        self.asi1 = asi1
        self.parser = IntentParser(asi1)
        self.executor = ActionExecutor(repo, max_attempts=settings.action_max_attempts)

    # ------------------------------------------------------------------ entry point
    async def handle(self, session_key: str, text: str, research: ResearchClient, msg_id: str | None = None,
                     report_text: str | None = None, notices: list[str] | None = None) -> list[Reply]:
        trace = uuid.uuid4().hex[:12]
        if msg_id and not self.repo.record_inbound(session_key, msg_id):
            log.info("duplicate inbound message ignored trace=%s", trace)
            return []
        text = (text or "").strip()
        notices = notices or []
        if not text and not report_text:
            return [Reply("\n\n".join(notices) or WELCOME)]

        # Safety takes precedence over commands, card actions and duplicate approvals.
        safety = assess(f"{text}\n{report_text or ''}")
        if safety.is_emergency:
            case = self.repo.active_case(session_key)
            if case is None:
                case = self.repo.create_case(session_key, "fixture" if self.settings.fixture_mode else "live")
            req = self._request(case).model_copy(update={
                "urgency": Urgency.EMERGENCY, "urgency_flags": safety.flags,
            })
            case.request_json = req.model_dump_json()
            self._move(case, CaseState.URGENT_GUIDANCE, trace, flags=safety.flags)
            return [Reply(safety.guidance or "")]

        if HELP.match(text):
            return [Reply(HELP_TEXT)]
        if DELETE.search(text):
            n = self.repo.delete_session_data(session_key)
            return [Reply(f"Deleted {n} case(s) and all associated records for this chat.")]
        if RESET.match(text):
            case = self.repo.active_case(session_key)
            if case and can_transition(CaseState(case.state), CaseState.CANCELLED):
                self._move(case, CaseState.CANCELLED, trace, reason="user reset")
            return [Reply("Okay, starting fresh. " + WELCOME)]
        if m := SHOW.search(text):
            return [self._show_saved(m.group(1).upper(), session_key)]

        case = self.repo.active_case(session_key)
        if case is None:
            last = self.repo.latest_case(session_key)
            if last and last.state == CaseState.COMPLETED.value:
                sel = parse_selection(text, self._ids(last))
                if sel.action == "approve":
                    return [await self._approve(last, sel, trace)]
            case = self.repo.create_case(session_key, "fixture" if self.settings.fixture_mode else "live")
            if last and last.state in (CaseState.CANCELLED.value, CaseState.COMPLETED.value):
                case.request_json = last.request_json  # continuity: keep city/condition/insurer from this chat
            self.repo.audit(case.case_id, trace, "case_created")

        state = CaseState(case.state)
        if state in SHORTLIST_STATES:
            sel = parse_selection(text, self._ids(case), self._names(case))
            if sel.action == "clarify_approval":
                return [Reply("Nothing was saved. To save the current shortlist, reply **approve** or use the "
                              "approval button. You can also say **cancel** or tell me what to change.")]
            if sel.action:
                return await self._on_selection(case, sel, research, trace)
            self._move(case, CaseState.COLLECTING_INPUT, trace)  # treat as a revision of the request
        elif state == CaseState.SOURCE_UNAVAILABLE:
            if RETRY.match(text):
                return await self._research(case, self._request(case), research, trace, [])
            self._move(case, CaseState.COLLECTING_INPUT, trace)
        elif state not in (CaseState.COLLECTING_INPUT,):
            # A message arrived mid-pipeline (e.g. duplicate delivery during research): don't start a second run.
            return [Reply("I'm still working on your previous request - one moment.")]
        return await self._intake(case, text, report_text, research, trace, notices)

    # ------------------------------------------------------------------ intake
    async def _intake(self, case: CareCase, text: str, report_text: str | None, research: ResearchClient,
                      trace: str, notices: list[str]) -> list[Reply]:
        previous = self._request(case)
        asked: dict[str, int] = json.loads(case.asked_json or "{}")
        self._move(case, CaseState.SAFETY_CHECKING, trace)

        safety = assess(f"{text}\n{report_text or ''}")
        if safety.is_emergency or not r7_routine_ranking_allowed(safety.urgency):
            req = previous.model_copy(update={"urgency": Urgency.EMERGENCY, "urgency_flags": safety.flags})
            case.request_json = req.model_dump_json()
            self._move(case, CaseState.URGENT_GUIDANCE, trace, flags=safety.flags)
            return [Reply(safety.guidance or "")]

        update = await self.parser.parse(text, report_text)
        # Short answers to a pending question ("none", "Demo Shield Basic").
        if asked.get("insurance") and not update.insurance_provider and declines_insurance(text):
            update.insurance_declined = True
        if asked.get("plan") and previous.insurance_provider and not update.insurance_plan and len(text) <= 60 \
                and not update.care_specialty and not update.city and not find_insurer(text):
            update.insurance_plan = text.strip().strip(".")
        req = previous.merged_with(update)
        if update.insurance_provider and update.insurance_provider != previous.insurance_provider:
            req.insurance_plan = update.insurance_plan  # plan belonged to the old insurer
            req.insurance_declined = False
        req.case_id = case.case_id
        req.urgency = safety.urgency
        req.urgency_flags = list(dict.fromkeys(req.urgency_flags + safety.flags))
        plan = plan_questions(req, asked)
        req.missing_required_fields = [f for f in plan.fields if f != "insurance"]
        case.request_json = req.model_dump_json()
        self.repo.audit(case.case_id, trace, "intake", method=req.extraction_method, specialty=req.care_specialty,
                        city=req.city, insurer=req.insurance_provider, missing=plan.fields, urgency=req.urgency.value)

        prefix = list(notices)
        if safety.guidance:
            prefix.append(safety.guidance)
        if not plan.ready:
            for f in plan.fields:
                asked[f] = asked.get(f, 0) + 1
            case.asked_json = json.dumps(asked)
            self._move(case, CaseState.COLLECTING_INPUT, trace)
            understood = tf.understanding_summary(req) if (req.care_specialty or req.city) else ""
            body = "\n\n".join(p for p in prefix + [understood, plan.message] if p)
            return [Reply(body)]
        return await self._research(case, req, research, trace, prefix)

    # ------------------------------------------------------------------ research → shortlist
    async def _research(self, case: CareCase, req: CareRequest, research: ResearchClient, trace: str,
                        prefix: list[str]) -> list[Reply]:
        self._move(case, CaseState.RESEARCHING, trace)
        h_query = HospitalResearchQuery(case_id=case.case_id, task_id="task_" + uuid.uuid4().hex[:12], city=req.city or "",
                                        specialty=req.care_specialty or "", procedure=req.related_procedure,
                                        allow_nearby=req.allow_nearby)
        jobs = [research.hospitals(h_query)]
        i_query = None
        if req.insurance_provider:
            i_query = InsurerResearchQuery(case_id=case.case_id, task_id="task_" + uuid.uuid4().hex[:12],
                                           insurer=req.insurance_provider, plan=req.insurance_plan, city=req.city or "",
                                           procedure=req.related_procedure, specialty=req.care_specialty)
            jobs.append(research.insurer(i_query))
        outcomes: list[ResearchOutcome] = list(await asyncio.gather(*jobs))
        h_out = outcomes[0]
        i_out = outcomes[1] if i_query else None
        for out, q in ((h_out, h_query), (i_out, i_query)):
            if out is not None and q is not None:
                self.repo.record_task(case.case_id, q.task_id, out.agent, "succeeded" if out.result else "failed",
                                      out.attempts, out.latency_ms, out.error)
        if h_out.result is None or not any(s.ok for s in h_out.result.source_status):
            error = h_out.error or "; ".join(s.error or "" for s in h_out.result.source_status)
            self._move(case, CaseState.SOURCE_UNAVAILABLE, trace, error=error)
            return [Reply("\n\n".join(prefix + [
                "I couldn't reach the hospital research source just now, so I have no verified hospitals to show "
                "(I won't guess). Say **retry** to try again, or **new search** to start over."]))]

        self._move(case, CaseState.MATCHING, trace)
        insurer_result = i_out.result if i_out else None
        if i_out and i_out.result is None:
            from app.schemas.evidence import SourceStatus
            from app.schemas.insurance import InsurerResearchResult
            insurer_result = InsurerResearchResult(task_id=i_query.task_id, insurer=req.insurance_provider or "",
                                                   source_status=[SourceStatus(source_name="insurer research agent",
                                                                               ok=False, error=i_out.error)])
        candidates = [apply_candidate_rules(c, req) for c in build_candidates(req, h_out.result, insurer_result)]
        ranked = rank(candidates, req, self.settings.weights)

        self._move(case, CaseState.VERIFYING, trace)
        known = {e.evidence_id for e in h_out.result.evidence}
        if insurer_result:
            known |= {o.evidence.evidence_id for o in insurer_result.observations}
            known |= {p.evidence.evidence_id for p in insurer_result.policy_findings}
        report = verify(ranked, req, known)
        order = {Eligibility.PRIMARY: 0, Eligibility.SECONDARY: 1}
        final = sorted(report.passed, key=lambda c: (order[c.eligibility], -c.suitability_score))[:SHORTLIST_SIZE]
        self.repo.audit(case.case_id, trace, "verification", passed=[c.hospital.hospital_id for c in report.passed],
                        rejected=report.rejected, notes=report.notes)

        source_notes = self._source_notes(h_out.result, insurer_result, req)
        if insurer_result is not None and insurer_result.plan_required:
            asked = json.loads(case.asked_json or "{}")
            asked["plan"] = asked.get("plan", 0) + 1
            case.asked_json = json.dumps(asked)
        partial = (not final or (insurer_result is not None and not insurer_result.any_source_ok)
                   or all(c.eligibility != Eligibility.PRIMARY for c in final))
        case.results_json = json.dumps([c.model_dump(mode="json") for c in final])
        case.research_meta_json = json.dumps({"rejected": report.rejected, "source_notes": source_notes,
                                              "data_mode": h_out.result.data_mode})
        case.shortlist_version = (case.shortlist_version or 0) + 1
        case.selected_hospital_id = None
        case.request_json = req.model_dump_json()
        self._move(case, CaseState.PARTIAL_RESULTS if partial else CaseState.AWAITING_APPROVAL, trace,
                   shown=len(final), version=case.shortlist_version)

        if not final:
            return [Reply("\n\n".join(prefix + [
                tf.understanding_summary(req),
                f"I couldn't find any hospital in {req.city} with reliable evidence for "
                f"{(req.care_specialty or '').replace('_', ' ')} services, so I won't invent options.",
                "You could try a nearby larger city (e.g. *\"also consider nearby cities\"*) or another city.",
            ] + [f"_{n}_" for n in source_notes]))]

        narrative, method = await explainer.summarize(self.asi1, req, final)
        self.repo.audit(case.case_id, trace, "summary", method=method)
        data_mode = h_out.result.data_mode
        text = "\n\n".join(prefix + [tf.understanding_summary(req),
                                     tf.shortlist_text(req, final, data_mode, narrative, source_notes)])
        return [Reply(text, shortlist_card(case.case_id, case.shortlist_version, req, final, data_mode))]

    def _source_notes(self, h_result, i_result, req: CareRequest) -> list[str]:
        notes = []
        failed = [s for s in h_result.source_status if not s.ok]
        if failed:
            notes.append(f"{len(failed)} hospital source(s) could not be reached; results may be incomplete.")
        if h_result.data_mode == "live":
            notes.append("Hospital data: OpenStreetMap contributors (ODbL) and hospitals' own websites where available.")
        if req.insurance_provider and i_result is not None:
            if not i_result.any_source_ok:
                reason = i_result.source_status[0].error if i_result.source_status else "unavailable"
                notes.append(f"{req.insurance_provider} network status was NOT checked: {reason} "
                             "This is not an out-of-network result.")
            elif i_result.plan_required:
                plans = ", ".join(i_result.known_plans)
                if req.insurance_plan:
                    notes.append(f"I don't recognise the plan '{req.insurance_plan}'. Known plans: {plans}.")
                else:
                    notes.append(f"Tell me your exact plan name ({plans}) and I'll check plan exclusions and waiting periods.")
        elif not req.insurance_provider and not req.insurance_declined:
            notes.append("Tell me your health insurer (or say *none*) and I'll check network listings too.")
        return notes

    # ------------------------------------------------------------------ selection / approval
    async def _on_selection(self, case: CareCase, sel: Selection, research: ResearchClient, trace: str) -> list[Reply]:
        if sel.case_id and sel.case_id != case.case_id:
            return [Reply("That card belongs to an earlier search. Here is your current shortlist.", self._shortlist_card(case))]
        req = self._request(case)
        results = self._results(case)
        if sel.action == "select_hospital":
            c = next((c for c in results if c.hospital.hospital_id == sel.hospital_id), None)
            if c is None:
                return [Reply("I couldn't find that option in the current shortlist.", self._shortlist_card(case))]
            case.selected_hospital_id = c.hospital.hospital_id
            self.repo.save_case(case)
            self.repo.audit(case.case_id, trace, "hospital_selected", hospital_id=c.hospital.hospital_id)
            return [Reply(tf.detail_text(c, req), detail_card(case.case_id, case.shortlist_version, c, req))]
        if sel.action == "back":
            return [Reply(tf.shortlist_text(req, results, case.data_mode, None, []), self._shortlist_card(case))]
        if sel.action == "review":
            if sel.hospital_id and any(c.hospital.hospital_id == sel.hospital_id for c in results):
                case.selected_hospital_id = sel.hospital_id
                self.repo.save_case(case)
            payload = build_payload(case.case_id, case.shortlist_version, req, case.data_mode, results, case.selected_hospital_id)
            name = self._names(case).get(case.selected_hospital_id or "")
            return [Reply(tf.review_text(payload, name), review_card(payload, name))]
        if sel.action == "approve":
            if sel.version is not None and sel.version != case.shortlist_version:
                payload = build_payload(case.case_id, case.shortlist_version, req, case.data_mode, results,
                                        case.selected_hospital_id)
                return [Reply("That approval was for an older version of the shortlist. Please review the current one.",
                              review_card(payload, self._names(case).get(case.selected_hospital_id or "")))]
            if sel.hospital_id and any(c.hospital.hospital_id == sel.hospital_id for c in results):
                case.selected_hospital_id = sel.hospital_id
            return [await self._approve(case, sel, trace)]
        if sel.action == "cancel":
            payload = build_payload(case.case_id, case.shortlist_version, req, case.data_mode, results, case.selected_hospital_id)
            self.repo.record_approval(case.case_id, case.shortlist_version, payload_hash(payload), "rejected", ACTION)
            self._move(case, CaseState.CANCELLED, trace)
            return [Reply("Okay - nothing was saved. Tell me what to change (for example a different city, insurer or "
                          "plan) and I'll search again, or say **new search**.")]
        return [Reply("Sorry, I didn't catch that.", self._shortlist_card(case))]

    async def _approve(self, case: CareCase, sel: Selection, trace: str) -> Reply:
        req = self._request(case)
        results = self._results(case)
        if not r8_requires_approval(ACTION):  # pragma: no cover - guard documents R8
            raise RuntimeError("save_shortlist must require approval")
        payload = build_payload(case.case_id, case.shortlist_version, req, case.data_mode, results, case.selected_hospital_id)
        name = self._names(case).get(case.selected_hospital_id or "")
        if case.state == CaseState.COMPLETED.value:
            result = await self.executor.save_shortlist(payload, [e for c in results for e in c.evidence])
            self.repo.audit(case.case_id, trace, "duplicate_approval", confirmation_id=result.confirmation_id)
            return Reply(tf.confirmation_text(result, payload, name))
        if not results:
            return Reply("There's nothing to save yet - the shortlist is empty.")
        self.repo.record_approval(case.case_id, case.shortlist_version, payload_hash(payload), "approved", ACTION)
        self._move(case, CaseState.APPROVED, trace, payload_hash=payload_hash(payload))
        self._move(case, CaseState.EXECUTING_ACTION, trace)
        result = await self.executor.save_shortlist(payload, [e for c in results for e in c.evidence])
        if result.status == ActionStatus.SUCCEEDED and result.verified:
            self._move(case, CaseState.CHECKING_SAVED_RESULT, trace)
            self._move(case, CaseState.COMPLETED, trace, confirmation_id=result.confirmation_id, attempts=result.attempts)
            return Reply(tf.confirmation_text(result, payload, name), end_session=False)
        self._move(case, CaseState.RETRY_OR_ESCALATE, trace, error=result.error, attempts=result.attempts)
        self._move(case, CaseState.FAILED, trace)
        return Reply(f"⚠️ I could not save your shortlist after {result.attempts} attempts, so **no confirmation was "
                     f"issued**. Nothing partial was kept. Please say **new search** to try again later.")

    def _show_saved(self, confirmation_id: str, session_key: str) -> Reply:
        row = self.repo.shortlist_for_session(confirmation_id, session_key)
        if row is None:
            return Reply(f"I couldn't find {confirmation_id} in this chat.")
        payload = json.loads(row.payload_json)
        items = "\n".join(f"- {i['rank']}. {i['name']} ({', '.join(i['insurance_states'])})" for i in payload["items"])
        return Reply(f"**{confirmation_id}** - saved {row.created_at:%Y-%m-%d %H:%M} UTC\n{items}")

    # ------------------------------------------------------------------ helpers
    def _move(self, case: CareCase, target: CaseState, trace: str, **detail) -> None:
        current = CaseState(case.state)
        if current != target:
            transition(current, target)
            case.state = target.value
        self.repo.save_case(case)
        self.repo.audit(case.case_id, trace, f"state:{target.value}", **detail)

    @staticmethod
    def _request(case: CareCase) -> CareRequest:
        data = json.loads(case.request_json or "{}")
        return CareRequest.model_validate(data) if data else CareRequest(case_id=case.case_id)

    @staticmethod
    def _results(case: CareCase) -> list[RankedCandidate]:
        return [RankedCandidate.model_validate(c) for c in json.loads(case.results_json or "[]")]

    def _ids(self, case: CareCase) -> list[str]:
        return [c.hospital.hospital_id for c in self._results(case)]

    def _names(self, case: CareCase) -> dict[str, str]:
        return {c.hospital.hospital_id: c.hospital.name for c in self._results(case)}

    def _shortlist_card(self, case: CareCase) -> Card | None:
        results = self._results(case)
        if not results:
            return None
        return shortlist_card(case.case_id, case.shortlist_version, self._request(case), results, case.data_mode)
