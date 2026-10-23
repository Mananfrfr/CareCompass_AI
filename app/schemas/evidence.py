"""Evidence records: every factual claim CareCompass shows must point to one of these."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, Enum):
    OFFICIAL_HOSPITAL_SITE = "official_hospital_site"
    OFFICIAL_INSURER_DIRECTORY = "official_insurer_directory"
    OFFICIAL_POLICY_DOCUMENT = "official_policy_document"
    COMMUNITY_DIRECTORY = "community_directory"  # e.g. OpenStreetMap
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class Reliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClaimType(str, Enum):
    HOSPITAL_EXISTS = "hospital_exists"
    LOCATION = "location"
    SPECIALTY = "specialty"
    NETWORK_LISTING = "network_listing"
    NETWORK_ABSENCE = "network_absence"
    POLICY_EXCLUSION = "policy_exclusion"
    POLICY_WAITING_PERIOD = "policy_waiting_period"
    CASHLESS = "cashless"
    PREAUTHORIZATION = "preauthorization"


# Source types that are allowed to back each claim when we call it "verified".
AUTHORITATIVE_SOURCES: dict[ClaimType, set[SourceType]] = {
    ClaimType.SPECIALTY: {SourceType.OFFICIAL_HOSPITAL_SITE, SourceType.SYNTHETIC_FIXTURE},
    ClaimType.NETWORK_LISTING: {SourceType.OFFICIAL_INSURER_DIRECTORY, SourceType.SYNTHETIC_FIXTURE},
    ClaimType.NETWORK_ABSENCE: {SourceType.OFFICIAL_INSURER_DIRECTORY, SourceType.SYNTHETIC_FIXTURE},
    ClaimType.POLICY_EXCLUSION: {SourceType.OFFICIAL_POLICY_DOCUMENT, SourceType.SYNTHETIC_FIXTURE},
    ClaimType.POLICY_WAITING_PERIOD: {SourceType.OFFICIAL_POLICY_DOCUMENT, SourceType.SYNTHETIC_FIXTURE},
    ClaimType.CASHLESS: {SourceType.OFFICIAL_INSURER_DIRECTORY, SourceType.SYNTHETIC_FIXTURE},
}


class Evidence(BaseModel):
    evidence_id: str = ""
    claim_type: ClaimType
    claim_value: str
    subject: str = Field(description="Entity the claim is about, as named by the source")
    subject_id: str | None = Field(default=None, description="hospital_id when the source is our own hospital record")
    source_name: str
    source_url: str
    source_type: SourceType
    excerpt: str = ""
    retrieved_at: datetime = Field(default_factory=utcnow)
    reliability: Reliability = Reliability.MEDIUM
    synthetic: bool = False
    insurer: str | None = None
    plan: str | None = None
    city: str | None = None

    def model_post_init(self, __context) -> None:  # noqa: D401
        if not self.evidence_id:
            raw = "|".join(
                [self.claim_type.value, self.claim_value, self.subject, self.source_url, self.insurer or "", self.plan or ""]
            )
            self.evidence_id = "ev_" + hashlib.sha1(raw.encode()).hexdigest()[:12]

    @property
    def is_authoritative(self) -> bool:
        allowed = AUTHORITATIVE_SOURCES.get(self.claim_type)
        return allowed is None or self.source_type in allowed


class SourceStatus(BaseModel):
    source_name: str
    url: str = ""
    ok: bool
    error: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    attempts: int = 1
    complete_for_city: bool = False  # absence from this list is meaningful
