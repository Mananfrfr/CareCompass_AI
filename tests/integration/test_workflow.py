"""Multi-turn workflow behaviour (Tests 10, 13, 19, 20 and recovery paths)."""

from __future__ import annotations

import json

from app.research.hospital_sources import FixtureHospitalSource
from app.research.insurer_sources import FixtureInsurerSource
from app.research.service import InProcessResearchClient
from app.workflow.state_machine import CaseState


def state(workflow, session):
    return workflow.repo.latest_case(session).state


async def test_20_complete_journey(workflow, research):
    s = "user-20"
    r = await workflow.handle(s, "I have an ACL tear. I live in Jaipur and have Demo Shield insurance. Help me find a suitable hospital.",
                              research, msg_id="m1")
    assert r[0].card.kind == "carousel" and state(workflow, s) == CaseState.AWAITING_APPROVAL
    items = json.loads(r[0].card.metadata()["card_payload"])["items"]
    assert 1 <= len(items) <= 8 and items[0]["primary_cta"]["selection"]["action"] == "select_hospital"
    hid = items[0]["id"]
    r = await workflow.handle(s, json.dumps(items[0]["primary_cta"]["selection"]), research, msg_id="m2")
    assert r[0].card.kind == "detail"
    review_sel = json.loads(r[0].card.metadata()["card_payload"])["ctas"][0]["selection"]
    r = await workflow.handle(s, json.dumps(review_sel), research, msg_id="m3")
    assert r[0].card.kind == "review" and state(workflow, s) == CaseState.AWAITING_APPROVAL
    assert workflow.repo.shortlists(workflow.repo.latest_case(s).case_id) == []  # nothing saved before approval
    approve_sel = json.loads(r[0].card.metadata()["card_payload"])["approve_cta"]["selection"]
    r = await workflow.handle(s, json.dumps(approve_sel), research, msg_id="m4")
    case = workflow.repo.latest_case(s)
    assert case.state == CaseState.COMPLETED
    saved = workflow.repo.shortlists(case.case_id)
    assert len(saved) == 1 and saved[0].confirmation_id in r[0].text and "verified" in r[0].text
    assert json.loads(saved[0].payload_json)["selected_hospital_id"] == hid
    approvals = workflow.repo.approvals(case.case_id)
    assert [a.decision for a in approvals] == ["approved"] and approvals[0].payload_hash == saved[0].payload_hash
    events = [e.event_type for e in workflow.repo.audit_events(case.case_id)]
    for st in ("RESEARCHING", "MATCHING", "VERIFYING", "AWAITING_APPROVAL", "APPROVED", "EXECUTING_ACTION",
               "CHECKING_SAVED_RESULT", "COMPLETED"):
        assert f"state:{st}" in events
    tasks = workflow.repo.tasks_for(case.case_id)
    assert sorted(t.agent for t in tasks) == ["hospital-agent", "insurer-agent"]
    # Test 11 at workflow level: approving again does not create a second record.
    r = await workflow.handle(s, "approve", research, msg_id="m5")
    assert "already saved" in r[0].text and len(workflow.repo.shortlists(case.case_id)) == 1
    # A redelivered message id is ignored.
    assert await workflow.handle(s, "approve", research, msg_id="m5") == []


async def test_10_rejection_executes_nothing(workflow, research):
    s = "user-10"
    await workflow.handle(s, "kidney stone in Delhi", research)
    r = await workflow.handle(s, '{"action": "cancel"}', research)
    case = workflow.repo.latest_case(s)
    assert case.state == CaseState.CANCELLED and "nothing was saved" in r[0].text
    assert workflow.repo.shortlists(case.case_id) == [] and workflow.repo.executions(case.case_id) == []
    assert [a.decision for a in workflow.repo.approvals(case.case_id)] == ["rejected"]


async def test_13_insurer_agent_unavailable_gives_partial_results(workflow):
    research = InProcessResearchClient(FixtureHospitalSource(), FixtureInsurerSource(), fail_insurer=True)
    r = await workflow.handle("user-13", "ACL tear in Jaipur with Demo Shield insurance", research)
    assert state(workflow, "user-13") == CaseState.PARTIAL_RESULTS
    assert "NOT checked" in r[0].text and r[0].card is not None
    tasks = {t.agent: t for t in workflow.repo.tasks_for(workflow.repo.latest_case("user-13").case_id)}
    assert tasks["insurer-agent"].status == "failed" and tasks["hospital-agent"].status == "succeeded"


async def test_13_hospital_agent_unavailable_then_retry(workflow):
    down = InProcessResearchClient(FixtureHospitalSource(), FixtureInsurerSource(), fail_hospital=True)
    r = await workflow.handle("user-13b", "ACL tear in Jaipur", down)
    assert state(workflow, "user-13b") == CaseState.SOURCE_UNAVAILABLE and "won't guess" in r[0].text
    up = InProcessResearchClient(FixtureHospitalSource(), FixtureInsurerSource())
    r = await workflow.handle("user-13b", "retry", up)
    assert state(workflow, "user-13b") in (CaseState.AWAITING_APPROVAL, CaseState.PARTIAL_RESULTS)
    assert r[0].card is not None


async def test_19_conversation_continuity(workflow, research):
    s = "user-19"
    r = await workflow.handle(s, "I've had knee pain for two weeks.", research)
    assert "city" in r[0].text.lower() and state(workflow, s) == CaseState.COLLECTING_INPUT
    r = await workflow.handle(s, "Jaipur. I have Demo Shield", research)
    assert r[0].card is not None
    req = json.loads(workflow.repo.latest_case(s).request_json)
    assert req["city"] == "Jaipur" and req["insurance_provider"] == "Demo Shield Insurance"
    assert req["reported_symptoms"] == ["knee pain"] and req["duration"] == "two weeks"
    # Plan answer is understood in context and triggers plan-level checks.
    r = await workflow.handle(s, "Demo Shield Plus", research)
    req = json.loads(workflow.repo.latest_case(s).request_json)
    assert req["insurance_plan"] == "Demo Shield Plus" and req["city"] == "Jaipur"
    # After cancelling, a revision keeps the earlier facts.
    await workflow.handle(s, "cancel", research)
    await workflow.handle(s, "try Delhi instead", research)
    req = json.loads(workflow.repo.latest_case(s).request_json)
    assert req["city"] == "Delhi" and req["care_specialty"] == "orthopaedics" and req["insurance_provider"] == "Demo Shield Insurance"


async def test_08_emergency_in_workflow_stops_research(workflow, research):
    r = await workflow.handle("user-8", "Sudden severe chest pain and difficulty breathing. I'm in Jaipur.", research)
    case = workflow.repo.latest_case("user-8")
    assert case.state == CaseState.URGENT_GUIDANCE and "112" in r[0].text and r[0].card is None
    assert workflow.repo.tasks_for(case.case_id) == []  # no research started


async def test_plan_exclusion_reaches_user(workflow, research):
    r = await workflow.handle("user-2", "ACL tear, Jaipur, Demo Shield Basic plan with Demo Shield insurance", research)
    assert "Plan document lists this procedure as excluded" in r[0].text
    assert "covered" not in r[0].text.lower().replace("not confirm", "")


async def test_stale_card_and_access_control(workflow, research):
    await workflow.handle("owner", "kidney stone in Jaipur", research)
    case = workflow.repo.latest_case("owner")
    r = await workflow.handle("owner", json.dumps({"action": "approve", "case_id": case.case_id, "version": 99}), research)
    assert "older version" in r[0].text and workflow.repo.shortlists(case.case_id) == []
    r = await workflow.handle("owner", "approve", research)
    conf = workflow.repo.shortlists(case.case_id)[0].confirmation_id
    assert "saved" in (await workflow.handle("owner", f"show {conf}", research))[0].text.lower()
    assert "couldn't find" in (await workflow.handle("intruder", f"show {conf}", research))[0].text
    r = await workflow.handle("owner", "delete my data", research)
    assert workflow.repo.latest_case("owner") is None and workflow.repo.read_shortlist(conf) is None


async def test_no_reliable_results_does_not_invent(workflow, research):
    r = await workflow.handle("user-none", "I have a cataract, I'm in Jaipur", research)
    assert "won't invent" in r[0].text and r[0].card is None


async def test_report_path_end_to_end(workflow, research):
    report = ("MRI LEFT KNEE. Findings: Complete tear of the anterior cruciate ligament. Medial meniscus intact. "
              "Impression: Complete ACL tear. Advised orthopaedic consultation.")
    r = await workflow.handle("user-9", "Here is my report. I'm in Jaipur, no insurance.", research, report_text=report)
    assert "From your report" in r[0].text and "rules out" in r[0].text and r[0].card.kind == "carousel"
    case = workflow.repo.latest_case("user-9")
    assert "anterior cruciate" not in case.request_json.lower() or "documented_findings" in case.request_json
