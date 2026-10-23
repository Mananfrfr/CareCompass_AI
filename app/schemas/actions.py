"""Shortlists, approvals and action results."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ShortlistItem(BaseModel):
    rank: int
    hospital_id: str
    name: str
    city: str
    address: str = ""
    specialty_signal: str
    insurance_states: list[str]
    evidence_confidence: str
    suitability_score: float
    evidence_ids: list[str]
    source_urls: list[str]
    synthetic: bool = False


class ShortlistPayload(BaseModel):
    """The exact content the user is asked to approve. Its hash is stored with the approval."""

    case_id: str
    version: int
    specialty: str
    city: str
    insurer: str | None
    plan: str | None
    data_mode: str
    selected_hospital_id: str | None = None
    items: list[ShortlistItem]


class ActionStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ActionResult(BaseModel):
    status: ActionStatus
    confirmation_id: str | None = None
    idempotency_key: str
    verified: bool = False
    duplicate: bool = False
    attempts: int = 0
    error: str | None = None
    verification_details: list[str] = Field(default_factory=list)
