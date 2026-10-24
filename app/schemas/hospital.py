"""Hospital research request/result and ranked candidates."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.evidence import Evidence, SourceStatus
from app.schemas.insurance import InsuranceState


class HospitalRecord(BaseModel):
    hospital_id: str
    name: str
    city: str
    address: str = ""
    postcode: str | None = None
    branch: str | None = None
    website: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    aliases: list[str] = Field(default_factory=list)
    synthetic: bool = False
    state: str | None = None
    district: str | None = None
    ownership_type: str = "unknown"
    hfr_id: str | None = None
    pmjay_empanelment_id: str | None = None
    phone: str | None = None
    care_type: str | None = None
    beds: int | None = None
    facilities: list[str] = Field(default_factory=list)
    distance_km: float | None = None  # from the requested city's centre, when coordinates are known
    location_note: str | None = None
    discovery_source: str | None = None

    @property
    def map_url(self) -> str:
        """Google Maps link (no API key needed). Coordinates when known, otherwise a name+address search."""
        from urllib.parse import quote_plus
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps/search/?api=1&query={self.latitude:.6f}%2C{self.longitude:.6f}"
        return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{self.name}, {self.address or self.city}")

    @property
    def directions_url(self) -> str:
        from urllib.parse import quote_plus
        if self.latitude is not None and self.longitude is not None:
            dest = f"{self.latitude:.6f},{self.longitude:.6f}"
        else:
            dest = f"{self.name}, {self.address or self.city}"
        return "https://www.google.com/maps/dir/?api=1&destination=" + quote_plus(dest)


class HospitalResearchQuery(BaseModel):
    case_id: str
    task_id: str
    city: str
    specialty: str
    procedure: str | None = None
    allow_nearby: bool = False
    max_results: int = 8


class HospitalResearchResult(BaseModel):
    task_id: str
    hospitals: list[HospitalRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    source_status: list[SourceStatus] = Field(default_factory=list)
    data_mode: str = "fixture"


class Eligibility(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"  # shown with caveats (e.g. specialty not verified)
    EXCLUDED = "excluded"


class VerificationStatus(str, Enum):
    PASSED = "passed"
    DOWNGRADED = "downgraded"
    REJECTED = "rejected"
    PENDING = "pending"


class RankedCandidate(BaseModel):
    hospital: HospitalRecord
    evidence: list[Evidence] = Field(default_factory=list)
    specialty_verified: bool = False
    specialty_signal: str = "none"  # verified | weak | none
    location_verified: bool = False
    insurance_states: list[InsuranceState] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    rule_flags: list[str] = Field(default_factory=list)
    eligibility: Eligibility = Eligibility.SECONDARY
    suitability_score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_confidence: str = "low"  # high | medium | low — independent of score
    explanation: str = ""
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verification_notes: list[str] = Field(default_factory=list)
    last_verified: str | None = None
    contextual_tier: str | None = None
    capability_checks: dict[str, bool] = Field(default_factory=dict)
    scoring_version: str = "clinical-v2"
    # "verified": passed the clinical evidence gate. "lead": real, government/community-listed hospital
    # whose service still has to be confirmed by phone - shown separately, never as a verified match.
    match_kind: str = "verified"

    @property
    def network_label(self) -> str:
        from app.schemas.insurance import describe_states

        return describe_states(self.insurance_states)
