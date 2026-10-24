"""Structured understanding of what the user asked for."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class InputType(str, Enum):
    MEDICAL_REPORT = "medical_report"
    KNOWN_CONDITION = "known_condition"
    SYMPTOMS = "symptoms"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    EMERGENCY = "emergency"
    PROMPT = "prompt"  # see a doctor soon (same/next day), not an ambulance
    ROUTINE = "routine"
    UNKNOWN = "unknown"


class FindingStatus(str, Enum):
    STATED = "stated"  # the report states it plainly
    SUSPECTED = "suspected"  # hedged: "suggestive of", "likely", "?"
    NEGATED = "negated"  # "no evidence of", "negative for"


class SourceReference(BaseModel):
    origin: str = Field(description="user_message | report")
    text: str
    start: int | None = None
    end: int | None = None


class DocumentedFinding(BaseModel):
    text: str
    status: FindingStatus
    measurements: list[str] = Field(default_factory=list)
    mapped_condition: str | None = None
    source: SourceReference


class CareRequest(BaseModel):
    """Everything we know about the user's request. Never holds the raw report text."""

    case_id: str = ""
    input_type: InputType = InputType.UNKNOWN
    reported_condition: str | None = None
    reported_symptoms: list[str] = Field(default_factory=list)
    duration: str | None = None
    documented_findings: list[DocumentedFinding] = Field(default_factory=list)
    care_specialty: str | None = None
    specialty_rationale: str | None = None
    related_procedure: str | None = None
    patient_age: int | None = Field(default=None, ge=0, le=120)
    budget_inr: float | None = Field(default=None, gt=0)
    budget_unit: str | None = None  # session | procedure | consultation; never silently interchanged
    required_capabilities: list[str] = Field(default_factory=list)
    city: str | None = None
    state: str | None = None
    allow_nearby: bool = False
    insurance_provider: str | None = None
    insurance_declined: bool = False
    insurance_plan: str | None = None
    preferences: list[str] = Field(default_factory=list)
    urgency: Urgency = Urgency.UNKNOWN
    urgency_flags: list[str] = Field(default_factory=list)
    extraction_confidence: float = 0.0
    extraction_method: str = "rules"
    missing_required_fields: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    unreadable_notes: list[str] = Field(default_factory=list)

    def merged_with(self, update: "CareRequest") -> "CareRequest":
        """Fill gaps from a follow-up message without discarding earlier facts, resetting stale clinical state when concern changes."""
        data = self.model_dump()

        # Check if the update indicates a new or changed clinical topic / city
        new_specialty = update.care_specialty and update.care_specialty != self.care_specialty
        new_condition = update.reported_condition and update.reported_condition != self.reported_condition
        new_city = update.city and self.city and update.city.casefold() != self.city.casefold()

        if new_specialty or new_condition or new_city:
            # Clear previously specific procedures, capabilities, budget and ungrounded constraints
            for field in [
                "related_procedure", "budget_inr", "budget_unit",
                "patient_age", "state"
            ]:
                data[field] = getattr(update, field)
            data["required_capabilities"] = list(update.required_capabilities)
            data["preferences"] = list(update.preferences)
            data["allow_nearby"] = update.allow_nearby

        for key, value in update.model_dump().items():
            if key in {"case_id"}:
                continue
            if key in {"required_capabilities", "preferences"} and (new_specialty or new_condition or new_city):
                data[key] = list(value)
            elif isinstance(value, list):
                existing = data.get(key) or []
                data[key] = existing + [v for v in value if v not in existing]
            elif value not in (None, "", False, 0.0, InputType.UNKNOWN, Urgency.UNKNOWN):
                if key in {"input_type", "extraction_method"} and data.get(key) not in (None, InputType.UNKNOWN, "rules"):
                    continue
                data[key] = value
        return CareRequest.model_validate(data)
