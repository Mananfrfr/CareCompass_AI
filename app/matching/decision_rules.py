"""Explicit, testable decision rules (R1-R10). Each rule is a small pure function."""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.care_knowledge import normalize_city
from app.schemas.evidence import ClaimType
from app.schemas.hospital import Eligibility, RankedCandidate
from app.schemas.input import CareRequest, Urgency
from app.schemas.insurance import InsuranceState


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    eligibility: Eligibility | None  # None = no change
    flag: str | None = None


def r1_city(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    want = normalize_city(req.city) or req.city
    have = normalize_city(c.hospital.city) or c.hospital.city
    if want and have != want:
        if req.allow_nearby:
            return RuleOutcome("R1", Eligibility.SECONDARY, f"Located in {c.hospital.city}, outside {want} (you allowed nearby options)")
        return RuleOutcome("R1", Eligibility.EXCLUDED, f"Located in {c.hospital.city}, not {want}")
    return RuleOutcome("R1", None)


def r2_specialty(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    if not c.specialty_verified:
        if c.specialty_signal == "none":
            return RuleOutcome("R2", Eligibility.SECONDARY, "No evidence this hospital offers the relevant service")
        if c.specialty_signal == "general":
            return RuleOutcome("R2", Eligibility.SECONDARY, "General hospital - relevant department not listed; confirm by phone")
        return RuleOutcome("R2", Eligibility.SECONDARY, "Relevant service suggested but not verified on an official source")
    return RuleOutcome("R2", None)


def r3_conflict(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    if InsuranceState.SOURCES_CONFLICT in c.insurance_states:
        if InsuranceState.NETWORK_UNCERTAIN not in c.insurance_states:
            c.insurance_states.append(InsuranceState.NETWORK_UNCERTAIN)
        if InsuranceState.NETWORK_VERIFIED in c.insurance_states:
            c.insurance_states.remove(InsuranceState.NETWORK_VERIFIED)
        return RuleOutcome("R3", None, "Insurer sources disagree - network status uncertain")
    return RuleOutcome("R3", None)


def r4_exclusion(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    if InsuranceState.PROCEDURE_EXCLUDED in c.insurance_states:
        return RuleOutcome("R4", None, "Your plan document lists this procedure as excluded - do not assume it is covered")
    if InsuranceState.WAITING_PERIOD_APPLIES in c.insurance_states:
        return RuleOutcome("R4", None, "Your plan document lists a waiting period for this procedure")
    return RuleOutcome("R4", None)


def r5_insufficient(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    exists = [e for e in c.evidence if e.claim_type == ClaimType.HOSPITAL_EXISTS and e.source_url]
    if not exists:
        return RuleOutcome("R5", Eligibility.EXCLUDED, "No source confirms this hospital exists")
    return RuleOutcome("R5", None)


def r6_source_failure(c: RankedCandidate, req: CareRequest) -> RuleOutcome:
    if InsuranceState.SOURCE_UNAVAILABLE in c.insurance_states:
        return RuleOutcome("R6", None, "Insurer source unavailable - this is NOT an out-of-network result")
    return RuleOutcome("R6", None)


CANDIDATE_RULES = (r5_insufficient, r1_city, r2_specialty, r3_conflict, r4_exclusion, r6_source_failure)


def apply_candidate_rules(c: RankedCandidate, req: CareRequest) -> RankedCandidate:
    eligibility = Eligibility.PRIMARY
    order = {Eligibility.PRIMARY: 0, Eligibility.SECONDARY: 1, Eligibility.EXCLUDED: 2}
    for rule in CANDIDATE_RULES:
        outcome = rule(c, req)
        if outcome.flag and outcome.flag not in c.rule_flags:
            c.rule_flags.append(f"{outcome.rule}: {outcome.flag}")
        if outcome.eligibility and order[outcome.eligibility] > order[eligibility]:
            eligibility = outcome.eligibility
    c.eligibility = eligibility
    return c


# --- Workflow-level rules -------------------------------------------------------------

def r7_routine_ranking_allowed(urgency: Urgency) -> bool:
    """R7: an emergency presentation stops routine hospital comparison."""
    return urgency != Urgency.EMERGENCY


EXTERNAL_ACTIONS = {"save_shortlist", "send_inquiry", "share_report"}


def r8_requires_approval(action: str) -> bool:
    """R8: every persistent or outward-facing action requires explicit user approval."""
    return action in EXTERNAL_ACTIONS


def r9_should_execute(existing_status: str | None) -> bool:
    """R9: never repeat a side effect that already succeeded."""
    return existing_status != "succeeded"


def r10_may_report_success(write_ok: bool, readback_ok: bool) -> bool:
    """R10: success is reported only after the stored record has been read back and matched."""
    return write_ok and readback_ok
