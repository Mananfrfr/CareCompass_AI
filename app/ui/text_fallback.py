"""Plain-text (markdown) renderings. Always sent, so the workflow works even without cards."""

from __future__ import annotations

from app.schemas.actions import ActionResult, ShortlistPayload
from app.schemas.hospital import RankedCandidate
from app.schemas.input import CareRequest, FindingStatus, InputType
from app.schemas.insurance import STATE_TEXT, InsuranceState
from app.ui.card_builder import _key_evidence, specialty_label

DISCLAIMER = ("_CareCompass helps you navigate care. It does not diagnose, and a network listing does not "
              "guarantee a claim. Please confirm with the hospital and your insurer before treatment._")
SYNTHETIC_NOTICE = ("**Demo data notice:** these hospitals and insurer records are *synthetic (fictional)* and are "
                    "used to demonstrate the workflow. They are not real recommendations.")


def understanding_summary(req: CareRequest) -> str:
    parts = []
    if req.input_type == InputType.MEDICAL_REPORT:
        stated = [f for f in req.documented_findings if f.status == FindingStatus.STATED]
        suspected = [f for f in req.documented_findings if f.status == FindingStatus.SUSPECTED]
        negated = [f for f in req.documented_findings if f.status == FindingStatus.NEGATED]
        parts.append("From your report:")
        for f in stated[:2]:
            parts.append(f"- states: \"{f.text[:110]}\"")
        for f in suspected[:2]:
            parts.append(f"- *hedged / not confirmed*: \"{f.text[:110]}\"")
        for f in negated[:2]:
            parts.append(f"- rules out: \"{f.text[:110]}\"")
        for note in req.unreadable_notes[:2]:
            parts.append(f"- note: {note}")
    concern = req.reported_condition or ", ".join(req.reported_symptoms) or "your concern"
    if req.duration:
        concern += f" ({req.duration})"
    line = f"**Concern:** {concern}"
    if req.care_specialty:
        line += f" → looking for **{specialty_label(req.care_specialty)}** services"
    parts.append(line)
    if req.specialty_rationale:
        parts.append(f"_{req.specialty_rationale}_")
    if req.city:
        parts.append(f"**City:** {req.city}")
    if req.budget_inr:
        parts.append(f"**Budget:** INR {req.budget_inr:,.0f}; unit: {req.budget_unit or 'please specify per session/procedure/consultation'}")
    if req.insurance_provider:
        parts.append(f"**Insurer:** {req.insurance_provider}" + (f" ({req.insurance_plan})" if req.insurance_plan else ""))
    elif req.insurance_declined:
        parts.append("**Insurer:** none - hospital suitability only, no network check")
    return "\n".join(parts)


def _states(c: RankedCandidate) -> str:
    return "; ".join(STATE_TEXT[s] for s in c.insurance_states)


def shortlist_text(req: CareRequest, candidates: list[RankedCandidate], data_mode: str, narrative: str | None,
                   source_notes: list[str]) -> str:
    lines = []
    if data_mode == "fixture":
        lines += [SYNTHETIC_NOTICE, ""]
    if narrative:
        lines += [narrative, ""]
    lines.append(f"**Shortlist - {specialty_label(req.care_specialty)} in {req.city}**")
    for i, c in enumerate(candidates, start=1):
        lines.append(f"\n**{i}. {c.hospital.name}** ({c.hospital.city}) - suitability {c.suitability_score:.0f}/100, "
                     f"CareCompass tier **{c.contextual_tier or 'unrated'}**, evidence confidence *{c.evidence_confidence}*")
        lines.append(f"   - {c.explanation}")
        lines.append(f"   - Insurance: {_states(c)}")
        for conflict in c.conflicts:
            lines.append(f"   - ⚠️ Conflict: {conflict}")
        if c.missing_evidence:
            lines.append(f"   - Missing: {c.missing_evidence[0]}")
        urls = sorted({e.source_url for e in c.evidence})[:3]
        lines.append(f"   - Sources: {', '.join(urls)} (checked {c.last_verified})")
    lines.append("\nTiers are condition-specific CareCompass scores, not official hospital ratings. Unknown factors earn zero points. Fewer than five results means insufficient qualified evidence.")
    for note in source_notes:
        lines.append(f"\n_{note}_")
    lines.append("\nReply with a number (e.g. **1**) to see the evidence, **approve** to save this shortlist, "
                 "or tell me what to change.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def detail_text(c: RankedCandidate, req: CareRequest) -> str:
    lines = [f"**{c.hospital.name}**", f"- Address: {c.hospital.address or c.hospital.city}",
             f"- Why ranked: {c.explanation}",
             f"- Insurance: {_states(c)}",
             f"- Suitability {c.suitability_score:.0f}/100 ({', '.join(f'{k} {v:.2f}' for k, v in c.score_breakdown.items())}); "
             f"evidence confidence *{c.evidence_confidence}*"]
    for conflict in c.conflicts:
        lines.append(f"- ⚠️ Conflict: {conflict}")
    for m in c.missing_evidence:
        lines.append(f"- Missing: {m}")
    for flag in c.rule_flags:
        lines.append(f"- Rule: {flag}")
    lines.append("\n**Evidence**")
    for e in _key_evidence(c)[:6]:
        lines.append(f"- *{e.claim_type.value.replace('_', ' ')}* - {e.source_name} ({e.source_type.value}, "
                     f"{e.retrieved_at.date().isoformat()}): \"{e.excerpt[:140]}\" - {e.source_url}")
    if InsuranceState.NETWORK_VERIFIED in c.insurance_states:
        lines.append("\n_A network listing means the hospital appears in the insurer's directory. It does not confirm "
                     "your policy covers this treatment or that a cashless request would be accepted._")
    lines.append("\nSay **save** to save the shortlist with this choice, or **back** to return to the list.")
    return "\n".join(lines)


def review_text(payload: ShortlistPayload, selected_name: str | None) -> str:
    names = "; ".join(f"{i.rank}. {i.name}" for i in payload.items)
    return (f"**Please confirm:** save this shortlist ({names})"
            + (f" with **{selected_name}** as your choice" if selected_name else "")
            + " and its supporting evidence to your CareCompass record?\n"
              "No report text is stored, and nothing is sent to any hospital or insurer.\n\n"
              "Reply **approve** to save, or **cancel** to revise.")


def confirmation_text(result: ActionResult, payload: ShortlistPayload, selected_name: str | None) -> str:
    if result.duplicate:
        head = f"This shortlist was already saved - no duplicate was created. Reference: **{result.confirmation_id}**"
    else:
        head = f"✅ Saved and verified. Your reference is **{result.confirmation_id}**."
    lines = [head, "", "**Verification**"] + [f"- {d}" for d in result.verification_details]
    lines.append("\n**Saved shortlist**")
    for item in payload.items:
        mark = " ← your choice" if item.hospital_id == payload.selected_hospital_id else ""
        lines.append(f"- {item.rank}. {item.name} - {', '.join(item.insurance_states)}{mark}")
    lines.append("\n**Next steps**")
    lines.append("- Call the hospital to confirm the department, doctor availability and costs.")
    if payload.insurer:
        lines.append(f"- Call {payload.insurer} (or your TPA) with your policy number to confirm eligibility and "
                     "pre-authorisation before admission.")
    lines.append(f"- Ask me *show {result.confirmation_id}* any time in this chat, or *delete my data* to erase it.")
    if payload.data_mode == "fixture":
        lines.append("\n" + SYNTHETIC_NOTICE)
    return "\n".join(lines)
