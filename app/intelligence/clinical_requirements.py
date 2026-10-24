"""Conservative navigation requirements, not treatment prescriptions.

Explicit treatment requests need evidence for that treatment. A general specialty
consultation is not automatically a recommendation to undergo surgery.
"""
import re

from app.schemas.input import CareRequest


def key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def requirements(req: CareRequest) -> list[str]:
    needed = list(req.required_capabilities)
    if req.related_procedure:
        needed.append(key(req.related_procedure))
    if req.patient_age is not None and req.patient_age < 18:
        needed.append("paediatric_care")
        if req.care_specialty == "oncology":
            needed.extend(["paediatric_oncology", "haematology"])
    return sorted(set(needed))


def extract_requirements(req: CareRequest, text: str) -> None:
    for state in ("Himachal Pradesh", "Chhattisgarh", "Maharashtra", "Bihar", "Rajasthan", "Delhi"):
        if re.search(rf"\b{re.escape(state)}\b", text, re.I):
            req.state = state
    age = re.search(r"\b(\d{1,3})\s*(?:year[s]?[- ]old|yr[s]?[- ]old|years of age)\b", text, re.I)
    if age and int(age[1]) <= 120:
        req.patient_age = int(age[1])
    budget = re.search(r"\b(?:budget|up to|under|maximum|max)\s*(?:is|of|:)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)\s*(lakh|lac|k)?\b", text, re.I)
    if budget:
        value = int(budget[1].replace(",", ""))
        multiplier = {"lakh": 100000, "lac": 100000, "k": 1000}.get((budget[2] or "").lower(), 1)
        if value > 0:
            req.budget_inr = value * multiplier
            unit = re.search(r"\b(?:per|each|a)\s+(session|procedure|consultation)\b", text, re.I)
            req.budget_unit = unit[1].lower() if unit else None
    # Do not infer dialysis merely from chronic kidney disease.
    if re.search(r"\b(?:ha?emodialysis|dialysis)\b", text, re.I) and not re.search(r"\b(?:no|not|without|don't need|do not need)\s+(?:\w+\s+){0,2}dialysis\b", text, re.I):
        req.related_procedure = "dialysis"
        req.required_capabilities = ["dialysis", "nephrology_support"]
    if re.search(r"\bleuk[ae]mia\b", text, re.I):
        req.reported_condition = "Leukemia (reported)"
        req.care_specialty = "oncology"
        req.required_capabilities = ["haematology"]
    if req.patient_age is None and re.search(r"\b(?:my child|my son|my daughter|paediatric|pediatric)\b", text, re.I):
        req.required_capabilities.append("paediatric_care")
        if req.care_specialty == "oncology":
            req.required_capabilities.extend(["paediatric_oncology", "haematology"])
