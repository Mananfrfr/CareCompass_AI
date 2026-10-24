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


def states_text(values: list[str]) -> str:
    out = []
    for v in values:
        try:
            out.append(STATE_TEXT[InsuranceState(v)])
        except ValueError:
            out.append(v)
    return "; ".join(out)


def _states(c: RankedCandidate) -> str:
    return "; ".join(STATE_TEXT[s] for s in c.insurance_states)


def insurer_notes(req: CareRequest, i_result) -> list[str]:
    """Actionable insurer guidance for real insurers (official site, plan documents, register)."""
    notes = []
    plan = getattr(i_result, "matched_plan", None)
    if plan:
        line = (f"Your plan matched the IRDAI register entry **{plan['name']}** (UIN `{plan['uin']}`, register year "
                f"{plan.get('year') or 'n/a'}).")
        if plan.get("wording_url"):
            line += f" [Official policy wording (PDF)]({plan['wording_url']})"
        notes.append(line)
    for finding in getattr(i_result, "policy_findings", []):
        if finding.evidence.source_type.value == "official_policy_document":
            kind = "waiting-period" if finding.state == InsuranceState.WAITING_PERIOD_APPLIES else "exclusion"
            notes.append(f"Policy wording {kind} clause mentioning this procedure: \"{finding.evidence.excerpt[:220]}\" "
                         "- confirm how it applies to you with the insurer.")
    for g in getattr(i_result, "guidance", []):
        notes.append(g)
    products = getattr(i_result, "registered_products", [])
    if products and not plan:
        names = "; ".join(f"{p['name']} (UIN {p['uin']})" for p in products[:4])
        notes.append(f"Registered {req.insurance_provider} products include: {names}. Tell me which one is yours.")
    for link in getattr(i_result, "official_links", []):
        notes.append(f"Check network hospitals: [{link['label']}]({link['url']})")
    return notes


def _contact_line(c: RankedCandidate) -> str:
    h = c.hospital
    bits = []
    if h.phone:
        bits.append(f"📞 {h.phone}")
    bits.append(f"[📍 Map]({h.map_url})")
    bits.append(f"[Directions]({h.directions_url})")
    if h.distance_km is not None:
        bits.append(f"~{h.distance_km:.0f} km from centre")
    if h.website:
        bits.append(f"[Website]({h.website})")
    return " · ".join(bits)


def _candidate_lines(i: int, c: RankedCandidate) -> list[str]:
    lines = []
    if c.match_kind == "lead":
        lines.append(f"\n**{i}. {c.hospital.name}** ({c.hospital.city}) - lead score {c.suitability_score:.0f}/100 "
                     f"(evidence match, not a quality rating), evidence confidence *{c.evidence_confidence}*")
    else:
        lines.append(f"\n**{i}. {c.hospital.name}** ({c.hospital.city}) - suitability {c.suitability_score:.0f}/100, "
                     f"CareCompass tier **{c.contextual_tier or 'unrated'}**, evidence confidence *{c.evidence_confidence}*")
    lines.append(f"   - {c.explanation}")
    lines.append(f"   - {_contact_line(c)}")
    lines.append(f"   - Insurance: {_states(c)}")
    for conflict in c.conflicts:
        lines.append(f"   - ⚠️ Conflict: {conflict}")
    if c.hospital.location_note:
        lines.append(f"   - ⚠️ {c.hospital.location_note}")
    urls = sorted({e.source_url for e in c.evidence})[:3]
    lines.append(f"   - Sources: {', '.join(urls)} (checked {c.last_verified})")
    return lines


def shortlist_text(req: CareRequest, candidates: list[RankedCandidate], data_mode: str, narrative: str | None,
                   source_notes: list[str]) -> str:
    lines = []
    if data_mode == "fixture":
        lines += [SYNTHETIC_NOTICE, ""]
    if narrative:
        lines += [narrative, ""]
    verified = [c for c in candidates if c.match_kind != "lead"]
    leads = [c for c in candidates if c.match_kind == "lead"]
    i = 0
    if verified:
        lines.append(f"**Verified matches - {specialty_label(req.care_specialty)} in {req.city}**")
        for c in verified:
            i += 1
            lines += _candidate_lines(i, c)
    if leads:
        lines.append(f"\n**{'More options' if verified else 'Hospitals to call'} - {specialty_label(req.care_specialty)} "
                     f"in {req.city}** _(real, publicly listed hospitals; the department is not yet verified - "
                     "call to confirm before visiting)_")
        for c in leads:
            i += 1
            lines += _candidate_lines(i, c)
    if verified:
        lines.append("\nTiers are condition-specific CareCompass scores, not official hospital ratings. "
                     "Unknown factors earn zero points.")
    for note in source_notes:
        lines.append(f"\n_{note}_" if not note.startswith(("Check network", "Your plan", "Policy wording")) else f"\n{note}")
    lines.append("\nReply with a number (e.g. **1**) to see the evidence, **approve** to save this shortlist, "
                 "or tell me what to change.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def detail_text(c: RankedCandidate, req: CareRequest) -> str:
    score_label = "Lead score" if c.match_kind == "lead" else "Suitability"
    lines = [f"**{c.hospital.name}**", f"- Address: {c.hospital.address or c.hospital.city}",
             f"- Contact & map: {_contact_line(c)}",
             f"- Why listed: {c.explanation}",
             f"- Insurance: {_states(c)}",
             f"- {score_label} {c.suitability_score:.0f}/100 ({', '.join(f'{k} {v:.2f}' for k, v in c.score_breakdown.items())}); "
             f"evidence confidence *{c.evidence_confidence}*"]
    if c.hospital.beds or c.hospital.facilities:
        lines.append(f"- Listed facilities: {', '.join(f.replace('_', ' ') for f in c.hospital.facilities) or 'n/a'}"
                     + (f"; {c.hospital.beds} beds" if c.hospital.beds else ""))
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
    if c.match_kind == "lead":
        lines.append("\n**Before you go:** call and ask whether this branch has a "
                     f"{specialty_label(req.care_specialty)} specialist, the next available OPD slot and the consultation fee.")
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
        lead = " (call to confirm the department)" if item.match_kind == "lead" else ""
        phone = f" · 📞 {item.phone}" if item.phone else ""
        lines.append(f"- {item.rank}. {item.name}{lead}{phone} - {states_text(item.insurance_states)}{mark}")
    lines.append("\n**Next steps**")
    lines.append("- Call the hospital to confirm the department, doctor availability and costs.")
    lines.append(f"- Say **care brief** for a free preparation checklist (questions to ask, documents to carry).")
    if payload.insurer:
        lines.append(f"- Call {payload.insurer} (or your TPA) with your policy number to confirm eligibility and "
                     "pre-authorisation before admission.")
    lines.append(f"- Ask me *show {result.confirmation_id}* any time in this chat, or *delete my data* to erase it.")
    if payload.data_mode == "fixture":
        lines.append("\n" + SYNTHETIC_NOTICE)
    return "\n".join(lines)
