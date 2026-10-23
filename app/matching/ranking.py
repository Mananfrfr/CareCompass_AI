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

SPECIALTY_SCORE = {"verified": 1.0, "directory": 0.6, "weak": 0.35, "none": 0.0}


def _network_score(states: list[InsuranceState]) -> float | None:
    if InsuranceState.NOT_CHECKED in states:
        return None  # user has no insurance: dimension dropped and weights renormalised
    if InsuranceState.NETWORK_VERIFIED in states:
        return 1.0 if InsuranceState.CASHLESS_LISTED in states else 0.85
    if InsuranceState.SOURCE_UNAVAILABLE in states:
        return 0.5  # unknown is not the same as out of network
    if InsuranceState.NETWORK_UNCERTAIN in states:
        return 0.4
    if InsuranceState.NETWORK_NOT_FOUND in states:
        return 0.0
    return 0.4


def _evidence_score(c: RankedCandidate, now: datetime) -> float:
    if not c.evidence:
        return 0.0
    authoritative = sum(1 for e in c.evidence if e.is_authoritative) / len(c.evidence)
    ages = [(now - e.retrieved_at).days for e in c.evidence]
    worst = max(ages)
    freshness = 1.0 if worst <= 90 else 0.7 if worst <= 365 else 0.4
    independent = len({e.source_type for e in c.evidence if e.claim_type != ClaimType.LOCATION} |
                      {e.source_name for e in c.evidence})
    breadth = 1.0 if independent >= 2 else 0.6
    return round(0.5 * authoritative + 0.3 * freshness + 0.2 * breadth, 3)


def _preference_score(c: RankedCandidate, req: CareRequest) -> float:
    score = 0.5
    if "cashless" in req.preferences:
        score = 1.0 if InsuranceState.CASHLESS_LISTED in c.insurance_states else 0.2
    return score


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
    now = now or datetime.now(timezone.utc)
    eligible = [c for c in candidates if c.eligibility != Eligibility.EXCLUDED]
    for c in eligible:
        components: dict[str, float | None] = {
            "specialty": SPECIALTY_SCORE.get(c.specialty_signal, 0.0),
            "network": _network_score(c.insurance_states),
            "location": 1.0 if c.location_verified else 0.4,
            "evidence": _evidence_score(c, now),
            "preferences": _preference_score(c, req),
        }
        active = {k: v for k, v in components.items() if v is not None}
        total_w = sum(getattr(weights, k) for k in active)
        c.score_breakdown = {k: round(v, 3) for k, v in active.items()}
        c.suitability_score = round(100 * sum(getattr(weights, k) * v for k, v in active.items()) / total_w, 1)
        c.evidence_confidence = evidence_confidence(c, req)
        c.explanation = explain(c, req)
    order = {Eligibility.PRIMARY: 0, Eligibility.SECONDARY: 1}
    eligible.sort(key=lambda c: (order[c.eligibility], -c.suitability_score, c.hospital.name))
    # Only show secondary options if they still have *some* specialty signal.
    shown = [c for c in eligible if c.eligibility == Eligibility.PRIMARY or c.specialty_signal != "none"]
    return shown if limit is None else shown[:limit]
