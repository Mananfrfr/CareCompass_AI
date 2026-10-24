"""ASI1-written plain-language summary of a *verified* shortlist.

ASI1 only rephrases facts we hand it. The output is screened by the verifier's forbidden-claim
check (no coverage guarantees, no diagnoses, no bookings); on any problem we use the template.
"""

from __future__ import annotations

import json
import logging

from app.intelligence.asi1_client import ASI1Client, ASI1Unavailable
from app.matching.result_verifier import check_text
from app.schemas.hospital import RankedCandidate
from app.schemas.input import CareRequest
from app.schemas.insurance import STATE_TEXT

log = logging.getLogger(__name__)

SYSTEM = (
    "You write a 2-3 sentence, friendly, plain-English summary of a hospital shortlist for a person in India "
    "who is not medically trained. Use ONLY the facts provided. Never diagnose, never say anything is covered, "
    "guaranteed, approved or booked. If network status is uncertain or unavailable, say so plainly. No lists, no headings."
)


def template_summary(req: CareRequest, candidates: list[RankedCandidate]) -> str:
    if not candidates:
        return ""
    top = candidates[0]
    label = (req.care_specialty or "care").replace("_", " ")
    verified_n = sum(1 for c in candidates if c.match_kind != "lead")
    if verified_n:
        text = (f"I found {len(candidates)} option(s) for {label} in {req.city}; {verified_n} passed the verified "
                f"evidence checks. {top.hospital.name} matches best on the evidence available.")
    else:
        text = (f"I found {len(candidates)} real, publicly listed hospital(s) in or near {req.city} that are good first "
                f"calls for {label}. None has a current official page confirming the department yet, so please call "
                f"to confirm before visiting - {top.hospital.name} is the strongest lead.")
    if req.insurance_provider:
        states = [s.value for c in candidates for s in c.insurance_states]
        verified = sum(1 for c in candidates if "NETWORK_VERIFIED" in [s.value for s in c.insurance_states])
        if "SOURCE_UNAVAILABLE" in states:
            text += f" I could not check {req.insurance_provider}'s network for these hospitals, so their network status is unknown."
        else:
            text += (f" {verified} of them appear in {req.insurance_provider}'s network list; a listing still needs "
                     "confirming with your insurer.")
    return text


async def summarize(asi1: ASI1Client | None, req: CareRequest, candidates: list[RankedCandidate]) -> tuple[str, str]:
    """Returns (summary, method) where method is 'asi1' or 'template'."""
    fallback = template_summary(req, candidates)
    if not asi1 or not asi1.available or not candidates:
        return fallback, "template"
    facts = {
        "need": req.care_specialty, "city": req.city, "insurer": req.insurance_provider,
        "note": "Hospitals with match_kind 'lead' are real listed hospitals whose department is NOT verified; "
                "tell the user to call to confirm.",
        "hospitals": [{"name": c.hospital.name, "service_evidence": c.specialty_signal, "match_kind": c.match_kind,
                       "distance_km": c.hospital.distance_km,
                       "insurance": [STATE_TEXT[s] for s in c.insurance_states],
                       "evidence_confidence": c.evidence_confidence} for c in candidates],
    }
    try:
        text = (await asi1.chat(SYSTEM, f"<user_data>{json.dumps(facts)}</user_data>", max_tokens=220)).strip()
    except ASI1Unavailable as exc:
        log.info("ASI1 summary unavailable: %s", exc)
        return fallback, "template"
    if check_text(text) or len(text) > 900 or "<" in text:
        log.warning("ASI1 summary rejected by claim guard")
        return fallback, "template"
    return text, "asi1"
