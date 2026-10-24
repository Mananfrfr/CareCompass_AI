"""Explainable suitability ranking.

The score says how well the *available evidence* matches the user's stated needs. It is not
a measure of clinical quality, and it is kept separate from evidence confidence.
Weights are product choices (see app.config.RankingWeights), not validated clinical weights.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import RankingWeights
from app.schemas.evidence import ClaimType
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


def rank(candidates: list[RankedCandidate], req: CareRequest, weights: RankingWeights,
         limit: int | None = None, now: datetime | None = None) -> list[RankedCandidate]:
    from app.matching.clinical_scoring import score_candidate
    now = now or datetime.now(timezone.utc)
    qualified = []
    for c in candidates:
        if c.eligibility == Eligibility.EXCLUDED:
            continue
        if not score_candidate(c, req, weights, now):
            continue
        c.evidence_confidence = evidence_confidence(c, req)
        if c.conflicts:
            c.evidence_confidence = "low"
        c.explanation = explain(c, req) + " " + (
            "Required treatment capabilities passed the evidence checks. "
            "Missing or unverified factors earn no points; this is not an official hospital rating."
        )
        qualified.append(c)
    qualified.sort(key=lambda c: (-c.suitability_score, c.hospital.hospital_id))
    return qualified if limit is None else qualified[:limit]
