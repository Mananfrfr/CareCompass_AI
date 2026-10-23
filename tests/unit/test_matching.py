"""Evidence engine, decision rules, ranking (Tests 1-5, 17)."""

from __future__ import annotations

from dataclasses import replace

from app.config import RankingWeights
from app.matching.decision_rules import (
    apply_candidate_rules,
    r7_routine_ranking_allowed,
    r8_requires_approval,
    r9_should_execute,
    r10_may_report_success,
)
from app.matching.evidence_engine import build_candidates
from app.matching.ranking import rank
from app.matching.result_verifier import verify
from app.schemas.evidence import ClaimType, Evidence, SourceType
from app.schemas.hospital import Eligibility, VerificationStatus
from app.schemas.input import Urgency
from app.schemas.insurance import InsuranceState as S
from app.schemas.insurance import PolicyFinding
from tests.helpers import NOW, hospital, hospital_result, insurer_result, observation, request


def pipeline(req, hres, ires):
    cands = [apply_candidate_rules(c, req) for c in build_candidates(req, hres, ires)]
    ranked = rank(cands, req, RankingWeights(), now=NOW)
    known = {e.evidence_id for e in hres.evidence}
    if ires:
        known |= {o.evidence.evidence_id for o in ires.observations} | {p.evidence.evidence_id for p in ires.policy_findings}
    return cands, ranked, verify(ranked, req, known)


def test_01_sources_agree_network_verified_but_qualified():
    hres = hospital_result(hospital("h1", "Aravali Bone & Joint Hospital"))
    ires = insurer_result(observation("Aravali Bone and Joint Hosp.", True))
    _, ranked, report = pipeline(request(), hres, ires)
    c = report.passed[0]
    assert S.NETWORK_VERIFIED in c.insurance_states and S.CASHLESS_LISTED in c.insurance_states
    assert c.eligibility == Eligibility.PRIMARY and c.evidence_confidence == "high"
    assert "does not confirm" in c.explanation  # listing is qualified, never "covered"
    assert {e.claim_type for e in c.evidence} >= {ClaimType.SPECIALTY, ClaimType.NETWORK_LISTING}


def test_02_procedure_excluded_never_claimed_covered():
    hres = hospital_result(hospital("h1", "Aravali Bone & Joint Hospital"))
    ires = insurer_result(observation("Aravali Bone and Joint Hosp.", True))
    excl = Evidence(claim_type=ClaimType.POLICY_EXCLUSION, claim_value="ACL reconstruction", subject="Demo Shield Basic",
                    source_name="policy", source_url="fixture://policy", source_type=SourceType.SYNTHETIC_FIXTURE,
                    excerpt="excludes ACL reconstruction", insurer="Demo Shield Insurance", plan="Demo Shield Basic")
    ires.policy_findings.append(PolicyFinding(plan="Demo Shield Basic", procedure="ACL reconstruction",
                                              state=S.PROCEDURE_EXCLUDED, evidence=excl))
    _, _, report = pipeline(request(insurance_plan="Demo Shield Basic"), hres, ires)
    c = report.passed[0]
    assert S.PROCEDURE_EXCLUDED in c.insurance_states
    assert any("excluded" in f for f in c.rule_flags)
    assert "covered" not in c.explanation.lower()


def test_03_other_city_excluded_unless_nearby_allowed():
    hres = hospital_result(hospital("h1", "Sanjeevani Ortho", city="Ajmer", postcode="305001"),
                           hospital("h2", "Jaipur Ortho"))
    cands, _, report = pipeline(request(insurance_provider=None), hres, None)
    ajmer = next(c for c in cands if c.hospital.hospital_id == "h1")
    assert ajmer.eligibility == Eligibility.EXCLUDED
    assert [c.hospital.hospital_id for c in report.passed] == ["h2"]
    cands, _, report = pipeline(request(insurance_provider=None, allow_nearby=True), hres, None)
    assert next(c for c in cands if c.hospital.hospital_id == "h1").eligibility == Eligibility.SECONDARY
    assert {c.hospital.hospital_id for c in report.passed} == {"h1", "h2"}


def test_04_sources_disagree_marked_uncertain_with_conflict():
    hres = hospital_result(hospital("h1", "Amber Sports Injury Centre", postcode="302021"))
    ires = insurer_result(observation("Amber Sports Injury Centre", True, "Directory A", postcode="302021"),
                          observation("Amber Sports Injury Centre", False, "De-empanelment notice", postcode="302021"))
    _, _, report = pipeline(request(), hres, ires)
    c = report.passed[0]
    assert S.SOURCES_CONFLICT in c.insurance_states and S.NETWORK_UNCERTAIN in c.insurance_states
    assert S.NETWORK_VERIFIED not in c.insurance_states
    assert c.conflicts and "De-empanelment notice" in c.conflicts[0]
    assert c.evidence_confidence == "low"


def test_05_insurer_unavailable_is_not_out_of_network():
    hres = hospital_result(hospital("h1", "Aravali Bone & Joint Hospital"))
    ires = insurer_result(ok=False)
    _, _, report = pipeline(request(), hres, ires)
    c = report.passed[0]
    assert c.insurance_states == [S.SOURCE_UNAVAILABLE]
    assert S.NETWORK_NOT_FOUND not in c.insurance_states
    assert any("NOT an out-of-network" in f for f in c.rule_flags)
    assert c.score_breakdown["network"] == 0.5  # unknown is neutral, not penalised like "not found"


def test_not_found_only_when_list_is_complete():
    hres = hospital_result(hospital("h1", "Moti Dungri Hospital", postcode="302004"))
    _, _, complete = pipeline(request(), hres, insurer_result(observation("Other Hospital", True), complete=True))
    assert S.NETWORK_NOT_FOUND in complete.passed[0].insurance_states
    hres = hospital_result(hospital("h1", "Moti Dungri Hospital", postcode="302004"))
    _, _, partial = pipeline(request(), hres, insurer_result(observation("Other Hospital", True), complete=False))
    assert S.NETWORK_UNCERTAIN in partial.passed[0].insurance_states


def test_unbranched_listing_does_not_verify_two_branches():
    hres = hospital_result(hospital("mn", "Chandpole Ortho Hospital (Malviya Nagar)"),
                           hospital("vn", "Chandpole Ortho Hospital (Vaishali Nagar)", postcode="302021"))
    ires = insurer_result(observation("Chandpole Ortho Hospital", True, postcode=None))
    _, _, report = pipeline(request(), hres, ires)
    for c in report.passed:
        assert S.NETWORK_VERIFIED not in c.insurance_states
        assert S.NETWORK_UNCERTAIN in c.insurance_states


def test_missing_specialty_is_never_primary():
    hres = hospital_result(hospital("h1", "General Care", specialties=("general_medicine",)),
                           hospital("h2", "Bone Clinic"))
    cands, _, report = pipeline(request(insurance_provider=None), hres, None)
    gen = next(c for c in cands if c.hospital.hospital_id == "h1")
    assert gen.eligibility == Eligibility.SECONDARY and gen.specialty_signal == "none"
    assert [c.hospital.hospital_id for c in report.passed] == ["h2"]  # no-signal secondaries are not shown


def test_community_directory_specialty_is_not_verified():
    hres = hospital_result(hospital("h1", "OSM Ortho", source_type=SourceType.COMMUNITY_DIRECTORY))
    _, _, report = pipeline(request(insurance_provider=None), hres, None)
    c = report.passed[0]
    assert c.specialty_verified is False and c.eligibility == Eligibility.SECONDARY


def test_no_insurance_drops_network_dimension():
    hres = hospital_result(hospital("h1", "Bone Clinic"))
    _, ranked, _ = pipeline(request(insurance_provider=None, insurance_declined=True), hres, None)
    assert "network" not in ranked[0].score_breakdown
    assert ranked[0].insurance_states == [S.NOT_CHECKED]


def test_17_verifier_rejects_fabricated_citations_and_unsupported_claims():
    hres = hospital_result(hospital("h1", "Real One"), hospital("h2", "Fabricated One", postcode="302099"))
    req = request(insurance_provider=None)
    cands = [apply_candidate_rules(c, req) for c in build_candidates(req, hres, None)]
    ranked = rank(cands, req, RankingWeights(), now=NOW)
    fake = Evidence(claim_type=ClaimType.NETWORK_LISTING, claim_value="in_network", subject="Fabricated One",
                    source_name="made up", source_url="https://insurer.example/fake", source_type=SourceType.OFFICIAL_INSURER_DIRECTORY,
                    insurer="Demo Shield Insurance")
    target = next(c for c in ranked if c.hospital.hospital_id == "h2")
    target.evidence.append(fake)
    target.insurance_states = [S.NETWORK_VERIFIED]
    real = next(c for c in ranked if c.hospital.hospital_id == "h1")
    real.explanation = "This hospital is fully covered and your claim will be approved."
    report = verify(ranked, req, {e.evidence_id for e in hres.evidence})
    assert ("Fabricated One" in [name for name, _ in report.rejected])
    kept = report.passed[0]
    assert kept.verification_status == VerificationStatus.DOWNGRADED
    assert "withheld" in kept.explanation


def test_verifier_downgrades_network_claim_without_listing():
    hres = hospital_result(hospital("h1", "Bone Clinic"))
    req = request()
    cands = [apply_candidate_rules(c, req) for c in build_candidates(req, hres, insurer_result())]
    ranked = rank(cands, req, RankingWeights(), now=NOW)
    ranked[0].insurance_states = [S.NETWORK_VERIFIED, S.CASHLESS_LISTED]  # tampered, no evidence
    report = verify(ranked, req, {e.evidence_id for e in hres.evidence})
    c = report.passed[0]
    assert S.NETWORK_VERIFIED not in c.insurance_states and S.CASHLESS_LISTED not in c.insurance_states
    assert c.verification_status == VerificationStatus.DOWNGRADED


def test_verifier_removes_duplicates():
    a = hospital("h1", "Pink City Hospital")
    b = hospital("h1b", "Pink City Hospital")
    hres = hospital_result(a, b)
    _, _, report = pipeline(request(insurance_provider=None), hres, None)
    assert len(report.passed) == 1 and report.rejected[0][1] == "duplicate hospital"


def test_workflow_level_rules():
    assert r7_routine_ranking_allowed(Urgency.ROUTINE) and not r7_routine_ranking_allowed(Urgency.EMERGENCY)
    assert r8_requires_approval("save_shortlist") and r8_requires_approval("send_inquiry")
    assert r9_should_execute(None) and r9_should_execute("failed") and not r9_should_execute("succeeded")
    assert r10_may_report_success(True, True)
    assert not r10_may_report_success(True, False) and not r10_may_report_success(False, True)


def test_ranking_weights_are_configurable():
    hres = hospital_result(hospital("h1", "Bone Clinic"), hospital("h2", "Other Ortho", postcode="302021"))
    ires = insurer_result(observation("Bone Clinic", True, cashless=None))
    req = request()
    _, ranked, _ = pipeline(req, hres, ires)
    assert ranked[0].hospital.hospital_id == "h1"
    no_network = replace(RankingWeights(), network=0.0)
    cands = [apply_candidate_rules(c, req) for c in build_candidates(req, hres, ires)]
    ranked2 = rank(cands, req, no_network, now=NOW)
    assert ranked2[0].score_breakdown["network"] in (0.85, 0.0)
    assert abs(ranked2[0].suitability_score - ranked2[1].suitability_score) < abs(ranked[0].suitability_score - ranked[1].suitability_score)
