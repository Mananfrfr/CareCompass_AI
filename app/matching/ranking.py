"""Explainable suitability ranking.

The score says how well the *available evidence* matches the user's stated needs. It is not
a measure of clinical quality, and it is kept separate from evidence confidence.
Weights are product choices (see app.config.RankingWeights), not validated clinical weights.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import RankingWeights
from app.schemas.evidence import ClaimType, SourceType
from app.schemas.hospital import Eligibility, RankedCandidate
from app.schemas.input import CareRequest
from app.schemas.insurance import InsuranceState

def evidence_confidence(c: RankedCandidate, req: CareRequest) -> str:
    specialty_ok = c.specialty_verified
    network_ok = (InsuranceState.NOT_CHECKED in c.insurance_states
                  or InsuranceState.NETWORK_VERIFIED in c.insurance_states)
    if c.conflicts:
        return "low"
    if specialty_ok and network_ok and c.location_verified:
        return "high"
    if specialty_ok or network_ok:
        return "medium"
    return "low"


def explain(c: RankedCandidate, req: CareRequest) -> str:
    parts = []
    label = (req.care_specialty or "").replace("_", " ")
    if c.specialty_signal == "verified":
        parts.append(f"{label} services are advertised on its own profile")
    elif c.specialty_signal == "directory":
        parts.append(f"a public directory lists {label} services (not yet confirmed by the hospital)")
    elif c.specialty_signal == "weak":
        parts.append(f"its name suggests {label} services (unverified)")
    elif c.specialty_signal == "general":
        parts.append(f"it is a general hospital ({label} department not listed)")
    else:
        parts.append(f"no source confirms {label} services")
    if c.location_verified:
        parts.append(f"it is in {c.hospital.city}")
    if InsuranceState.NETWORK_VERIFIED in c.insurance_states:
        parts.append(f"it appears in {req.insurance_provider}'s network list (a listing alone does not confirm your claim)")
    elif InsuranceState.SOURCES_CONFLICT in c.insurance_states:
        parts.append("insurer sources disagree about its network status")
    elif InsuranceState.SOURCE_UNAVAILABLE in c.insurance_states:
        parts.append("insurer network status could not be checked")
    elif InsuranceState.NETWORK_NOT_FOUND in c.insurance_states:
        parts.append(f"it was not found in {req.insurance_provider}'s network list")
    elif InsuranceState.NETWORK_UNCERTAIN in c.insurance_states:
        parts.append("its network status is uncertain")
    return "Ranked here because " + "; ".join(parts) + "."


LEAD_SIGNALS = {"directory", "weak", "general"}


def lead_score(c: RankedCandidate, req: CareRequest) -> dict[str, float]:
    """Transparent evidence-match score for hospitals whose service is NOT yet verified.

    Measures how much *public evidence* points to this hospital being a sensible first call for the
    requested service. It is not a quality rating and never makes a lead look "verified".
    """
    spec_ev = [e for e in c.evidence if e.claim_type == ClaimType.SPECIALTY and e.claim_value == req.care_specialty]
    if c.specialty_signal == "directory":
        service = 40.0 if any(e.source_type == SourceType.OFFICIAL_GOVERNMENT for e in spec_ev) else 32.0
    else:
        service = {"weak": 22.0, "general": 12.0}.get(c.specialty_signal, 0.0)
    h = c.hospital
    facility = 0.0
    care = (h.care_type or "").lower()
    if "medical college" in care or "hospital" in care:
        facility += 6
    if (h.beds or 0) >= 100:
        facility += 6
    elif (h.beds or 0) >= 30:
        facility += 3
    for flag, pts in (("emergency_services", 4), ("icu", 4), ("operation_theatre", 2), ("radiology", 2)):
        if flag in h.facilities:
            facility += pts
    network = 15.0 if InsuranceState.NETWORK_VERIFIED in c.insurance_states else 0.0
    location = 0.0
    if c.location_verified:
        location = 10.0
        if h.distance_km is not None:
            location += 5.0 if h.distance_km <= 5 else 3.0 if h.distance_km <= 10 else 0.0
    elif h.distance_km is not None and h.distance_km <= 40:
        location = 4.0
    contact = (6.0 if h.phone else 0.0) + (4.0 if h.website else 0.0)
    return {"service_evidence": service, "facilities": min(facility, 20.0), "insurer_network": network,
            "location": location, "contactable": contact}


def explain_lead(c: RankedCandidate, req: CareRequest) -> str:
    label = (req.care_specialty or "").replace("_", " ")
    why = {
        "directory": f"a public directory lists {label} services here",
        "weak": f"its name suggests {label} services",
        "general": f"it is a general / multi-speciality hospital (no {label} department is listed)",
    }[c.specialty_signal]
    bits = [why]
    if c.hospital.distance_km is not None:
        bits.append(f"about {c.hospital.distance_km:.0f} km from the {req.city} centre")
    if c.hospital.beds:
        bits.append(f"{c.hospital.beds} beds listed")
    if InsuranceState.NETWORK_VERIFIED in c.insurance_states:
        bits.append(f"it appears in {req.insurance_provider}'s network list")
    return ("Lead to confirm: " + "; ".join(bits) + ". The service has NOT been verified on the hospital's own "
            "current source - call before visiting.")


def rank(candidates: list[RankedCandidate], req: CareRequest, weights: RankingWeights,
         limit: int | None = None, now: datetime | None = None) -> list[RankedCandidate]:
    """Verified matches (clinical evidence gate passed) first, then clearly labelled leads."""
    from app.matching.clinical_scoring import score_candidate
    now = now or datetime.now(timezone.utc)
    qualified, leads = [], []
    for c in candidates:
        if c.eligibility == Eligibility.EXCLUDED:
            continue
        if score_candidate(c, req, weights, now):
            c.match_kind = "verified"
            c.evidence_confidence = evidence_confidence(c, req)
            if c.conflicts:
                c.evidence_confidence = "low"
            c.explanation = explain(c, req) + " " + (
                "Required treatment capabilities passed the evidence checks. "
                "Missing or unverified factors earn no points; this is not an official hospital rating."
            )
            qualified.append(c)
        elif c.specialty_signal in LEAD_SIGNALS and not c.hospital.synthetic:
            make_lead(c, req)
            leads.append(c)
    qualified.sort(key=lambda c: (-c.suitability_score, c.hospital.hospital_id))
    leads.sort(key=lambda c: (-c.suitability_score, c.hospital.distance_km or 999, c.hospital.hospital_id))
    out = qualified + leads
    return out if limit is None else out[:limit]


def make_lead(c: RankedCandidate, req: CareRequest) -> None:
    c.match_kind = "lead"
    c.contextual_tier = None
    c.score_breakdown = lead_score(c, req)
    c.suitability_score = round(sum(c.score_breakdown.values()), 1)
    c.scoring_version = "lead-v1"
    c.evidence_confidence = "medium" if c.specialty_signal == "directory" and c.location_verified else "low"
    if c.conflicts:
        c.evidence_confidence = "low"
    c.explanation = explain_lead(c, req)
