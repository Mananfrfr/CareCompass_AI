"""Missing-information engine: ask only what the next research step strictly needs."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.input import CareRequest

REQUIRED_FOR_RESEARCH = ("care_specialty", "city")


@dataclass
class QuestionPlan:
    ready: bool
    fields: list[str] = field(default_factory=list)
    message: str = ""


def plan_questions(req: CareRequest, asked_counts: dict[str, int] | None = None) -> QuestionPlan:
    asked_counts = asked_counts or {}
    missing = [f for f in REQUIRED_FOR_RESEARCH if not getattr(req, f)]
    if not missing:
        return QuestionPlan(ready=True)

    lines: list[str] = []
    fields = list(missing)
    if "care_specialty" in missing:
        if asked_counts.get("care_specialty", 0) == 0:
            lines.append("What would you like help with? You can name a condition (e.g. *kidney stone*), "
                         "describe symptoms (e.g. *knee pain for 2 weeks*), or paste the key lines of a medical report.")
        else:
            lines.append("I couldn't match that to a type of hospital service yet. Could you describe the main problem "
                         "in a few words, or paste the *Impression* / *Diagnosis* line from your report?")
    if "city" in missing:
        lines.append("Which **city** should I search in?")
    # Insurance is optional: offer it once, in the same message, never as a blocker.
    if (not req.insurance_provider and not req.insurance_declined and asked_counts.get("insurance", 0) == 0):
        lines.append("*(Optional)* Which **health insurer** do you have? Say *none* to skip.")
        fields.append("insurance")
    message = "\n".join(f"- {line}" for line in lines) if len(lines) > 1 else lines[0]
    return QuestionPlan(ready=False, fields=fields, message=message)
