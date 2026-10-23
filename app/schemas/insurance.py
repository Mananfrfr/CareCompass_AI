"""Insurance research types. Network listing, plan eligibility, exclusions and cashless
availability are tracked as separate states - never collapsed into a single "covered"."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.evidence import Evidence, SourceStatus


class InsuranceState(str, Enum):
    NETWORK_VERIFIED = "NETWORK_VERIFIED"
    NETWORK_NOT_FOUND = "NETWORK_NOT_FOUND"
    NETWORK_UNCERTAIN = "NETWORK_UNCERTAIN"
    SOURCES_CONFLICT = "SOURCES_CONFLICT"
    PLAN_DETAILS_REQUIRED = "PLAN_DETAILS_REQUIRED"
    PROCEDURE_EXCLUDED = "PROCEDURE_EXCLUDED"
    WAITING_PERIOD_APPLIES = "WAITING_PERIOD_APPLIES"
    CASHLESS_LISTED = "CASHLESS_LISTED"
    CASHLESS_NOT_CONFIRMED = "CASHLESS_NOT_CONFIRMED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NOT_CHECKED = "NOT_CHECKED"  # user has no / declined insurance


STATE_TEXT: dict[InsuranceState, str] = {
    InsuranceState.NETWORK_VERIFIED: "Listed in the insurer's network directory",
    InsuranceState.NETWORK_NOT_FOUND: "Not found in the insurer's network directory",
    InsuranceState.NETWORK_UNCERTAIN: "Network status uncertain",
    InsuranceState.SOURCES_CONFLICT: "Insurer sources disagree",
    InsuranceState.PLAN_DETAILS_REQUIRED: "Exact plan needed for plan-level checks",
    InsuranceState.PROCEDURE_EXCLUDED: "Plan document lists this procedure as excluded",
    InsuranceState.WAITING_PERIOD_APPLIES: "Plan document lists a waiting period for this procedure",
    InsuranceState.CASHLESS_LISTED: "Directory lists cashless facility (approval still needed per claim)",
    InsuranceState.CASHLESS_NOT_CONFIRMED: "Cashless facility not confirmed",
    InsuranceState.SOURCE_UNAVAILABLE: "Insurer source unavailable - not checked",
    InsuranceState.NOT_CHECKED: "No insurance check requested",
}


def describe_states(states: list[InsuranceState]) -> str:
    if not states:
        return STATE_TEXT[InsuranceState.NOT_CHECKED]
    return "; ".join(STATE_TEXT[s] for s in states)


class NetworkObservation(BaseModel):
    """One row from one insurer source about one hospital."""

    listed_name: str
    city: str
    address: str = ""
    postcode: str | None = None
    in_network: bool
    cashless: bool | None = None
    evidence: Evidence


class PolicyFinding(BaseModel):
    plan: str
    procedure: str
    state: InsuranceState
    evidence: Evidence


class InsurerResearchQuery(BaseModel):
    case_id: str
    task_id: str
    insurer: str
    plan: str | None = None
    city: str
    procedure: str | None = None
    specialty: str | None = None


class InsurerResearchResult(BaseModel):
    task_id: str
    insurer: str
    insurer_recognized: bool = False
    observations: list[NetworkObservation] = Field(default_factory=list)
    policy_findings: list[PolicyFinding] = Field(default_factory=list)
    plan_required: bool = False
    known_plans: list[str] = Field(default_factory=list)
    source_status: list[SourceStatus] = Field(default_factory=list)
    data_mode: str = "fixture"

    @property
    def any_source_ok(self) -> bool:
        return any(s.ok for s in self.source_status)
