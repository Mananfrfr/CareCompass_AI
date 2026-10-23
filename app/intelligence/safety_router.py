"""Conservative safety routing. Runs on every user message *before* any research.

Deterministic on purpose: emergency detection must not depend on an LLM being available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.intelligence.care_knowledge import EMERGENCY_PATTERNS, PROMPT_PATTERNS
from app.schemas.input import Urgency

EMERGENCY_GUIDANCE = (
    "**This may be a medical emergency. Please do not wait for a hospital comparison.**\n\n"
    "- Call **112** (national emergency) or **108** (ambulance) in India right now, or go to the nearest emergency department.\n"
    "- If someone is with you, ask them to stay with you and help.\n"
    "- Do not drive yourself if you feel faint, have chest pain or trouble breathing.\n"
    "- Insurance can be sorted out later - emergency departments must not delay stabilising care for paperwork.\n\n"
    "I've paused the hospital search. Once you are safe, message me again and I can help with follow-up care."
)

SELF_HARM_GUIDANCE = (
    "**I'm really sorry you're going through this. You deserve support right now.**\n\n"
    "- If you are in immediate danger, call **112**.\n"
    "- Tele-MANAS (Govt. of India, 24x7, free): **14416** or **1-800-891-4416**.\n"
    "- Please reach out to someone you trust and let them know how you feel.\n\n"
    "I've paused the hospital search. I'm here if you'd like help finding mental-health services later."
)

PROMPT_NOTE = (
    "Some of what you described ({flags}) is worth getting checked **soon** - ideally today or tomorrow - "
    "rather than waiting for a planned appointment. If it gets worse, call 112."
)


@dataclass
class SafetyAssessment:
    urgency: Urgency
    flags: list[str] = field(default_factory=list)
    guidance: str | None = None

    @property
    def is_emergency(self) -> bool:
        return self.urgency == Urgency.EMERGENCY


_NEGATED = re.compile(r"\b(?:no|not|without|denies|never)\b[^.]{0,25}$")


def _match(text: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    flags: list[str] = []
    for pattern, label in patterns:
        for m in re.finditer(pattern, text):
            # Skip simple negations like "no chest pain".
            if _NEGATED.search(text[max(0, m.start() - 30) : m.start()]):
                continue
            if label not in flags:
                flags.append(label)
            break
    return flags


def assess(text: str) -> SafetyAssessment:
    low = " ".join(text.lower().split())
    flags = _match(low, EMERGENCY_PATTERNS)
    if flags:
        guidance = SELF_HARM_GUIDANCE if flags == ["risk of self-harm"] else EMERGENCY_GUIDANCE
        if "risk of self-harm" in flags and guidance is EMERGENCY_GUIDANCE:
            guidance = EMERGENCY_GUIDANCE + "\n\n" + SELF_HARM_GUIDANCE
        return SafetyAssessment(Urgency.EMERGENCY, flags, guidance)
    prompt = _match(low, PROMPT_PATTERNS)
    if prompt:
        return SafetyAssessment(Urgency.PROMPT, prompt, PROMPT_NOTE.format(flags=", ".join(prompt)))
    return SafetyAssessment(Urgency.ROUTINE)
