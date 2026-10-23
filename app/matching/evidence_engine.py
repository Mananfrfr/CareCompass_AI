"""Evidence Matching Engine: unify hospital research and insurer research into candidates.

Deterministic. Each candidate's facts are derived only from Evidence objects returned by
the research agents; the LLM never contributes facts here.
"""

from __future__ import annotations

from app.intelligence.care_knowledge import normalize_city
from app.research.entity_resolution import Identity, MatchDecision, compare
from app.schemas.evidence import ClaimType, Evidence, Reliability
from app.schemas.hospital import HospitalRecord, HospitalResearchResult, RankedCandidate
from app.schemas.input import CareRequest
from app.schemas.insurance import InsuranceState, InsurerResearchResult, NetworkObservation


def _specialty_signal(evidence: list[Evidence], specialty: str) -> tuple[str, bool]:
    relevant = [e for e in evidence if e.claim_type == ClaimType.SPECIALTY and e.claim_value == specialty]
    if any(e.is_authoritative for e in relevant):
        return "verified", True
    if any(e.reliability in (Reliability.MEDIUM, Reliability.HIGH) for e in relevant):
        return "directory", False  # community directory tag: useful, not authoritative
    if relevant:
        return "weak", False
    return "none", False


def _insurance_for(hospital: HospitalRecord, request: CareRequest, insurer: InsurerResearchResult | None,
                   all_hospitals: list[HospitalRecord]) -> tuple[list[InsuranceState], list[Evidence], list[str], list[str]]:
    """Returns (states, evidence, conflicts, missing)."""
    if not request.insurance_provider:
        return [InsuranceState.NOT_CHECKED], [], [], []
    if insurer is None or not insurer.any_source_ok:
        reason = "Insurer network source unavailable - network status not checked"
        if insurer and insurer.source_status:
            reason += f" ({insurer.source_status[0].error})"
        return [InsuranceState.SOURCE_UNAVAILABLE], [], [], [reason]

    me = Identity(hospital.name, hospital.city, hospital.address, hospital.postcode, website=hospital.website)
    matched: list[NetworkObservation] = []
    ambiguous: list[str] = []
    for obs in insurer.observations:
        them = Identity(obs.listed_name, obs.city, obs.address, obs.postcode)
        result = compare(me, them)
        if result.decision == MatchDecision.MATCH:
            matched.append(obs)
        elif result.decision == MatchDecision.AMBIGUOUS:
            # Also ambiguous if the same listing matches more than one of our hospitals.
            ambiguous.append(f"'{obs.listed_name}' may refer to this hospital ({result.reason})")

    states: list[InsuranceState] = []
    evidence = [o.evidence for o in matched]
    conflicts: list[str] = []
    missing: list[str] = []
    failed_sources = [s for s in insurer.source_status if not s.ok]

    verdicts = {o.in_network for o in matched}
    if verdicts == {True}:
        states.append(InsuranceState.NETWORK_VERIFIED)
    elif verdicts == {False}:
        states.append(InsuranceState.NETWORK_NOT_FOUND)
    elif verdicts == {True, False}:
        states += [InsuranceState.SOURCES_CONFLICT, InsuranceState.NETWORK_UNCERTAIN]
        listed = [o.evidence.source_name for o in matched if o.in_network]
        delisted = [o.evidence.source_name for o in matched if not o.in_network]
        conflicts.append(f"Listed as in-network by: {', '.join(listed)}; listed as NOT in network by: {', '.join(delisted)}")
    else:
        if ambiguous:
            states.append(InsuranceState.NETWORK_UNCERTAIN)
            missing.append("Network listing could not be matched to this exact branch: " + "; ".join(ambiguous[:2]))
        elif any(s.ok and s.complete_for_city for s in insurer.source_status) and not failed_sources:
            states.append(InsuranceState.NETWORK_NOT_FOUND)
        else:
            states.append(InsuranceState.NETWORK_UNCERTAIN)
            missing.append("Hospital not found in the insurer sources we could check (sources may be incomplete)")
    if failed_sources and InsuranceState.NETWORK_VERIFIED not in states:
        missing.append(f"{len(failed_sources)} insurer source(s) unavailable")

    if InsuranceState.NETWORK_VERIFIED in states:
        cashless = [o for o in matched if o.cashless]
        states.append(InsuranceState.CASHLESS_LISTED if cashless else InsuranceState.CASHLESS_NOT_CONFIRMED)

    for finding in insurer.policy_findings:
        if finding.state not in states:
            states.append(finding.state)
        evidence.append(finding.evidence)
    if insurer.plan_required and not request.insurance_plan:
        states.append(InsuranceState.PLAN_DETAILS_REQUIRED)
    elif insurer.plan_required:
        states.append(InsuranceState.PLAN_DETAILS_REQUIRED)
        missing.append(f"Plan '{request.insurance_plan}' not recognised; known plans: {', '.join(insurer.known_plans)}")
    return states, evidence, conflicts, missing


def build_candidates(request: CareRequest, hospitals: HospitalResearchResult,
                     insurer: InsurerResearchResult | None) -> list[RankedCandidate]:
    candidates: list[RankedCandidate] = []
    specialty = request.care_specialty or ""
    requested_city = normalize_city(request.city) or request.city or ""

    # One network listing must not silently attach to two different branches.
    listing_hits: dict[str, list[str]] = {}
    if insurer:
        for h in hospitals.hospitals:
            me = Identity(h.name, h.city, h.address, h.postcode)
            for obs in insurer.observations:
                if compare(me, Identity(obs.listed_name, obs.city, obs.address, obs.postcode)).decision != MatchDecision.NO_MATCH:
                    listing_hits.setdefault(obs.evidence.evidence_id, []).append(h.hospital_id)

    for hospital in hospitals.hospitals:
        own = [e for e in hospitals.evidence if e.subject_id == hospital.hospital_id]
        signal, verified = _specialty_signal(own, specialty)
        location_ok = (normalize_city(hospital.city) or hospital.city) == requested_city and any(
            e.claim_type == ClaimType.LOCATION for e in own)
        states, ins_evidence, conflicts, missing = _insurance_for(hospital, request, insurer, hospitals.hospitals)

        shared = [eid for eid in (e.evidence_id for e in ins_evidence) if len(listing_hits.get(eid, [])) > 1]
        if shared and InsuranceState.NETWORK_VERIFIED in states:
            states = [s for s in states if s not in (InsuranceState.NETWORK_VERIFIED, InsuranceState.CASHLESS_LISTED,
                                                     InsuranceState.CASHLESS_NOT_CONFIRMED)]
            states.insert(0, InsuranceState.NETWORK_UNCERTAIN)
            missing.append("The insurer listing names this hospital without a branch, and more than one branch exists")
            ins_evidence = [e for e in ins_evidence if e.evidence_id not in shared]

        if signal == "none":
            missing.append(f"No source found advertising {specialty.replace('_', ' ')} services")
        elif not verified:
            missing.append("Specialty not confirmed by the hospital's own website")
        retrieved = [e.retrieved_at for e in own + ins_evidence]
        candidates.append(RankedCandidate(
            hospital=hospital,
            evidence=own + ins_evidence,
            specialty_verified=verified,
            specialty_signal=signal,
            location_verified=location_ok,
            insurance_states=states,
            conflicts=conflicts,
            missing_evidence=missing,
            last_verified=min(retrieved).date().isoformat() if retrieved else None,
        ))
    return candidates
