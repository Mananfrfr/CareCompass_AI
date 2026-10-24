"""100-point evidence model. Hard capability gates precede the score.

No popularity, review-star or marketing-award inputs. Missing evidence scores zero.
Quality evidence is separately sourced; a hospital webpage is not accreditation.
"""
from datetime import datetime, timezone

from app.config import RankingWeights
from app.intelligence.clinical_requirements import key, requirements
from app.schemas.evidence import ClaimType, SourceType
from app.schemas.hospital import RankedCandidate
from app.schemas.input import CareRequest
from app.schemas.insurance import InsuranceState as S


def current(e, now, days=180):
    stamp = e.retrieved_at
    if stamp.tzinfo is None:
        return False
    if not 0 <= (now - stamp).total_seconds() <= days * 86400:
        return False
    return e.valid_until is None or (e.valid_until.tzinfo is not None and e.valid_until >= now)


def score_candidate(c: RankedCandidate, req: CareRequest, weights: RankingWeights,
                    now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    c.contextual_tier = None
    c.suitability_score = 0
    c.score_breakdown = {}
    if req.state and c.hospital.state and req.state.casefold() != c.hospital.state.casefold():
        c.rule_flags.append("State mismatch; a matching city name is insufficient")
        return False
    if c.hospital.city.casefold() == "bilaspur" and not req.state:
        c.rule_flags.append("Bilaspur is ambiguous: specify the state")
        return False
    # Branch-bound current evidence only. Fixture evidence cannot qualify a real hospital.
    ev = [e for e in c.evidence if e.subject_id == c.hospital.hospital_id and e.is_authoritative
          and current(e, now) and (c.hospital.synthetic or e.source_type != SourceType.SYNTHETIC_FIXTURE)]
    spec = any(e.claim_type == ClaimType.SPECIALTY and e.claim_value == req.care_specialty for e in ev)
    capabilities = {key(e.claim_value) for e in ev if e.claim_type == ClaimType.CAPABILITY
                    and e.scope == req.care_specialty}
    required = requirements(req)
    c.capability_checks = {r: r in capabilities for r in required}
    if not spec or not all(c.capability_checks.values()):
        missing = [r for r, ok in c.capability_checks.items() if not ok]
        flag = "Clinical gate failed: " + (", ".join(missing) or "current specialty evidence unavailable")
        if flag not in c.rule_flags:
            c.rule_flags.append(flag)
        return False
    # An unspecified service is consultation-level navigation only, not procedure clearance.
    capability = 1.0 if required else float("outpatient_consultation" in capabilities)
    quality = {e.claim_value for e in ev if e.claim_type == ClaimType.QUALITY
               and e.valid_until is not None and e.scope in {req.care_specialty, "hospital"}
               and e.claim_value in {"nabh_accreditation", "nqas_certification", "audited_safety_outcomes"}}
    network_ev = [e for e in c.evidence if e.claim_type == ClaimType.NETWORK_LISTING
                  and e.is_authoritative and current(e, now, 30)
                  and (e.insurer or "").casefold() == (req.insurance_provider or "").casefold()]
    network = 0.0
    if S.NETWORK_VERIFIED in c.insurance_states and network_ev and not ({S.SOURCES_CONFLICT, S.PROCEDURE_EXCLUDED} & set(c.insurance_states)):
        network = 2 / 3  # network membership alone is not treatment/plan coverage
        if req.insurance_plan and req.related_procedure and any(
            e.claim_type == ClaimType.TREATMENT_COVERAGE and e.is_authoritative and current(e, now, 30)
            and e.subject_id == c.hospital.hospital_id and e.plan == req.insurance_plan
            and e.insurer == req.insurance_provider and key(e.claim_value) == key(req.related_procedure)
            for e in c.evidence
        ):
            network = 1.0
    affordable = 0.0
    if req.budget_inr and req.budget_unit and req.related_procedure:
        costs = [e.amount_inr for e in ev if e.claim_type == ClaimType.COST and current(e, now, 30)
                 and key(e.claim_value) == key(req.related_procedure) and e.amount_inr
                 and e.cost_unit == req.budget_unit]
        # Conflicting higher quotes are not silently discarded.
        if costs:
            affordable = float(max(costs) <= req.budget_inr)
    components = dict(specialty=1.0, capability=capability, quality=min(len(quality) / 3, 1.0),
                      network=network, affordability=affordable,
                      location=float(c.location_verified and c.hospital.city.casefold() == (req.city or "").casefold()))
    c.score_breakdown = {k: round(100 * getattr(weights, k) * v, 2) for k, v in components.items()}
    c.suitability_score = round(sum(c.score_breakdown.values()), 1)
    score = c.suitability_score
    c.contextual_tier = "A" if score >= 85 and len(quality) >= 2 and not c.conflicts else "B" if score >= 70 else "C" if score >= 55 else None
    for label, value in components.items():
        if value == 0:
            message = f"{label}: no matching verified evidence or stated requirement; 0 points"
            if message not in c.missing_evidence:
                c.missing_evidence.append(message)
    return c.contextual_tier is not None
