"""Turn a free-text message (and optional report text) into a validated CareRequest.

Two layers:
1. Deterministic extraction (always runs, works offline).
2. ASI1 extraction (when configured) to catch phrasing the rules miss. Every ASI1 field is
   grounded against the user's own words before it is accepted - the model cannot invent a
   city, insurer or condition the user never mentioned.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.intelligence import care_knowledge as kb
from app.intelligence.asi1_client import ASI1Client, ASI1Unavailable
from app.intelligence.report_parser import looks_like_report, parse_report
from app.schemas.input import CareRequest, FindingStatus, InputType, SourceReference
from app.security.privacy import redact_identifiers

log = logging.getLogger(__name__)

DURATION = re.compile(
    r"\b(?:for|since|past|last)\s+(?:the\s+)?(?:last\s+|past\s+)?((?:\d+|a|an|one|two|three|four|five|six|several|few)\s+"
    r"(?:day|week|month|year)s?)\b", re.I)
PLAN = re.compile(
    r"\b((?:[A-Z][\w+&-]*\s){0,4}(?:Basic|Plus|Gold|Silver|Platinum|Premier|Comprehensive|Optima|Assure|Secure|Supreme|"
    r"Elite|Classic|Floater|Advantage|Medicare|Health Guard|Family Health Optima))\b")
FREEFORM_CITY = re.compile(r"\b(?:in|near|at|around|from)\s+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)\b")
NOT_CITIES = {"The", "My", "Our", "This", "That", "January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December", "Hospital", "India", "Pain"}
NEARBY = re.compile(r"\b(?:nearby cit|other cit|anywhere|outside the city|near ?by areas?|willing to travel)", re.I)

SPECIALTY_KEYS = tuple(kb.SPECIALTIES)


class LLMExtraction(BaseModel):
    input_type: Literal["medical_report", "known_condition", "symptoms", "unknown"] = "unknown"
    condition: str | None = Field(default=None, description="Condition the user or report explicitly names")
    symptoms: list[str] = Field(default_factory=list)
    duration: str | None = None
    city: str | None = None
    insurer: str | None = None
    plan: str | None = None
    allow_nearby: bool = False
    preferences: list[str] = Field(default_factory=list)
    suggested_specialty: str | None = Field(default=None, description=f"One of {SPECIALTY_KEYS} or null")


SYSTEM_PROMPT = (
    "You extract facts for a healthcare NAVIGATION assistant in India. You never diagnose. "
    "Extract only what the user explicitly wrote: the condition they name, symptoms, duration, city, health "
    "insurer, insurance plan name and preferences. Use null when something is not stated. Do not guess a city "
    "or insurer. suggested_specialty is the type of hospital service that usually handles the stated concern."
)


def _grounded(value: str | None, text: str) -> bool:
    if not value:
        return False
    low = text.lower()
    words = [w for w in re.findall(r"[a-z]{4,}", value.lower())]
    return value.lower() in low or (bool(words) and any(w in low for w in words))


def rule_extract(text: str, report_text: str | None = None) -> CareRequest:
    req = CareRequest(extraction_method="rules")
    req.duration = (m.group(1) if (m := DURATION.search(text)) else None)
    req.city = kb.find_city(text)
    if not req.city:
        for m in FREEFORM_CITY.finditer(text):
            cand = m.group(1)
            if cand.split()[0] not in NOT_CITIES and not kb.find_insurer(cand):
                req.city = cand
                req.source_references.append(SourceReference(origin="user_message", text=m.group(0), start=m.start(), end=m.end()))
                break
    req.insurance_provider = kb.find_insurer(text)
    req.insurance_declined = req.insurance_provider is None and kb.declines_insurance(text)
    if (m := PLAN.search(text)) and req.insurance_provider:
        req.insurance_plan = m.group(1).strip()
    req.allow_nearby = bool(NEARBY.search(text))
    low = text.lower()
    req.preferences = [p for p, pat in (("cashless", r"cashless"), ("government hospital", r"government|govt"),
                                         ("private hospital", r"\bprivate\b"), ("low cost", r"cheap|low cost|budget|afford"))
                       if re.search(pat, low)]

    condition = kb.find_condition(text)
    symptoms = kb.find_symptoms(text)
    report_body = report_text if report_text is not None else (text if looks_like_report(text) else None)

    if report_body:
        req.input_type = InputType.MEDICAL_REPORT
        extraction = parse_report(report_body)
        req.documented_findings = extraction.findings
        req.unreadable_notes = extraction.unreadable
        rule, finding = extraction.primary
        if rule and finding:
            qualifier = "" if finding.status == FindingStatus.STATED else "possible "
            req.reported_condition = f"{qualifier}{rule.canonical}"
            req.care_specialty, req.related_procedure = rule.specialty, rule.procedure
            req.specialty_rationale = (f"Your {extraction.document_type.lower()} mentions: \"{finding.text[:120]}\". "
                                       f"{rule.rationale}")
            req.extraction_confidence = 0.9 if finding.status == FindingStatus.STATED else 0.6
            req.source_references.append(finding.source)
        if condition and not rule:
            negated = [f for f in extraction.findings if f.mapped_condition == condition.canonical
                       and f.status == FindingStatus.NEGATED]
            if negated:
                req.unreadable_notes.append(
                    f"You mentioned {condition.canonical}, but the report text says: \"{negated[0].text[:120]}\". "
                    "Please confirm with your doctor which finding applies.")
    if not req.care_specialty and condition:
        req.input_type = InputType.KNOWN_CONDITION if req.input_type == InputType.UNKNOWN else req.input_type
        req.reported_condition = condition.canonical
        req.care_specialty, req.related_procedure = condition.specialty, condition.procedure
        req.specialty_rationale = condition.rationale
        req.extraction_confidence = 0.85
        m = next((re.search(p, low) for p in condition.patterns if re.search(p, low)), None)
        if m:
            req.source_references.append(SourceReference(origin="user_message", text=text[m.start():m.end()],
                                                         start=m.start(), end=m.end()))
    if symptoms:
        req.reported_symptoms = [s.name for s in symptoms]
        if not req.care_specialty:
            req.input_type = InputType.SYMPTOMS
            req.care_specialty = symptoms[0].specialty
            req.specialty_rationale = symptoms[0].note + " This is a starting point for evaluation, not a diagnosis."
            req.extraction_confidence = 0.7
    return req


class IntentParser:
    def __init__(self, asi1: ASI1Client | None = None):
        self.asi1 = asi1

    async def parse(self, text: str, report_text: str | None = None) -> CareRequest:
        req = rule_extract(text, report_text)
        if not self.asi1 or not self.asi1.available:
            return req
        safe_text = redact_identifiers(text if report_text is None else f"{text}\n\n[report]\n{report_text}")[:6000]
        try:
            llm = await self.asi1.structured(SYSTEM_PROMPT, f"<user_data>\n{safe_text}\n</user_data>", LLMExtraction)
        except ASI1Unavailable as exc:
            log.info("ASI1 extraction unavailable, using rules only: %s", exc)
            return req
        return merge_llm(req, llm, safe_text)


def merge_llm(req: CareRequest, llm: LLMExtraction, text: str) -> CareRequest:
    """Accept ASI1 fields only when grounded in the user's text and inside our controlled vocabulary."""
    req = req.model_copy(deep=True)
    used = False
    if not req.city and llm.city and _grounded(llm.city, text):
        req.city = kb.normalize_city(llm.city) or llm.city.strip().title()
        used = True
    if not req.insurance_provider and llm.insurer and _grounded(llm.insurer, text):
        req.insurance_provider = kb.find_insurer(llm.insurer) or llm.insurer.strip()
        used = True
    if not req.insurance_plan and llm.plan and req.insurance_provider and _grounded(llm.plan, text):
        req.insurance_plan = llm.plan.strip()
        used = True
    if not req.duration and llm.duration and _grounded(llm.duration, text):
        req.duration = llm.duration
        used = True
    if not req.care_specialty:
        rule = kb.find_condition(llm.condition or "") if _grounded(llm.condition, text) else None
        if rule:
            req.reported_condition, req.care_specialty = rule.canonical, rule.specialty
            req.related_procedure, req.specialty_rationale = rule.procedure, rule.rationale
            req.input_type = InputType.KNOWN_CONDITION
            req.extraction_confidence = 0.75
            used = True
        elif llm.suggested_specialty in kb.SPECIALTIES and (llm.condition or llm.symptoms):
            grounded_symptoms = [s for s in llm.symptoms if _grounded(s, text)]
            if grounded_symptoms or _grounded(llm.condition, text):
                req.care_specialty = llm.suggested_specialty
                req.reported_symptoms = req.reported_symptoms or grounded_symptoms
                req.reported_condition = req.reported_condition or (llm.condition if _grounded(llm.condition, text) else None)
                req.input_type = InputType.SYMPTOMS if grounded_symptoms else InputType.KNOWN_CONDITION
                req.specialty_rationale = (f"ASI1 suggested {kb.SPECIALTIES[llm.suggested_specialty].label} as a starting "
                                           "point for this concern. This is navigation guidance, not a diagnosis.")
                req.extraction_confidence = 0.5
                used = True
    if llm.allow_nearby and NEARBY.search(text):
        req.allow_nearby = True
    if used:
        req.extraction_method = "rules+asi1"
    return req
