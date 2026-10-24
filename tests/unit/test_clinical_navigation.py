from datetime import timedelta

import pytest

from app.config import RankingWeights
from app.intelligence.intent_parser import rule_extract
from app.matching.clinical_scoring import score_candidate
from app.research.policy_catalog import PolicyCatalog
from app.schemas.evidence import ClaimType, Evidence, SourceType
from app.schemas.hospital import RankedCandidate
from tests.helpers import NOW, hospital, request


def candidate(specialty="nephrology", caps=()):
    h, ev = hospital("branch", "Test branch", specialties=(specialty,))
    for cap in caps:
        ev.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value=cap, subject=h.name,
                           subject_id=h.hospital_id, source_name="test", source_url="fixture://clinical",
                           source_type=SourceType.SYNTHETIC_FIXTURE, retrieved_at=NOW, scope=specialty))
    return RankedCandidate(hospital=h, evidence=ev, specialty_verified=True,
                           specialty_signal="verified", location_verified=True)


def test_dialysis_needs_dialysis_and_support_not_kidney_name():
    req = rule_extract("I need dialysis in Jaipur, no insurance")
    c = candidate(caps=("nephrology_support",))
    assert not score_candidate(c, req, RankingWeights(), NOW)
    c = candidate(caps=("dialysis", "nephrology_support"))
    assert score_candidate(c, req, RankingWeights(), NOW)
    assert c.suitability_score == 60 and c.contextual_tier == "C"


def test_child_leukemia_needs_paediatric_haematology_not_general_oncology():
    req = rule_extract("My 8 year old child has leukemia in Jaipur")
    assert req.patient_age == 8 and req.care_specialty == "oncology"
    assert not score_candidate(candidate("oncology", ["outpatient_consultation"]), req, RankingWeights(), NOW)
    assert score_candidate(candidate("oncology", ["paediatric_care", "paediatric_oncology", "haematology"]), req, RankingWeights(), NOW)


def test_cataract_does_not_use_dialysis_capability():
    req = rule_extract("Cataract surgery in Jaipur")
    assert not score_candidate(candidate("ophthalmology", ["dialysis"]), req, RankingWeights(), NOW)
    assert score_candidate(candidate("ophthalmology", ["cataract_surgery"]), req, RankingWeights(), NOW)


@pytest.mark.parametrize("mutation", ["branch", "stale", "future", "community", "wrong_scope"])
def test_untrustworthy_capability_fails_closed(mutation):
    c = candidate("ophthalmology", ["cataract_surgery"])
    e = c.evidence[-1]
    if mutation == "branch": e.subject_id = "another-branch"
    if mutation == "stale": e.retrieved_at = NOW - timedelta(days=181)
    if mutation == "future": e.retrieved_at = NOW + timedelta(days=1)
    if mutation == "community": e.source_type = SourceType.COMMUNITY_DIRECTORY
    if mutation == "wrong_scope": e.scope = "nephrology"
    assert not score_candidate(c, request(care_specialty="ophthalmology", related_procedure="cataract surgery"), RankingWeights(), NOW)


def test_budget_units_and_conflicting_quotes():
    req = rule_extract("dialysis in Jaipur budget INR 3000 per session")
    assert req.budget_inr == 3000 and req.budget_unit == "session"
    c = candidate(caps=["dialysis", "nephrology_support"])
    e = c.evidence[-1].model_copy(update=dict(claim_type=ClaimType.COST, claim_value="dialysis",
                                             amount_inr=2500, cost_unit="procedure"))
    c.evidence.append(e)
    score_candidate(c, req, RankingWeights(), NOW)
    assert c.score_breakdown["affordability"] == 0
    e.cost_unit = "session"
    score_candidate(c, req, RankingWeights(), NOW)
    assert c.score_breakdown["affordability"] == 10
    c.evidence.append(e.model_copy(update={"amount_inr": 4000}))
    score_candidate(c, req, RankingWeights(), NOW)
    assert c.score_breakdown["affordability"] == 0


def test_no_popularity_quality_points_or_missing_insurance_bonus():
    c = candidate(caps=["dialysis", "nephrology_support"])
    req = rule_extract("dialysis in Jaipur")
    score_candidate(c, req, RankingWeights(), NOW)
    assert c.score_breakdown == dict(specialty=35, capability=20, quality=0, network=0, affordability=0, location=5)
    assert c.contextual_tier == "C"


def test_official_catalog_contains_200_plus_real_identity_records_not_seed():
    catalog = PolicyCatalog()
    assert len({r["uin"] for r in catalog.records}) >= 200
    assert all(r["verification_status"] == "official_registry_identity" for r in catalog.records)
    assert all(r["current_sale_status"] == "unknown" for r in catalog.records)
    assert catalog.search("Health Companion")
    assert not catalog.search("invented imaginary product")
