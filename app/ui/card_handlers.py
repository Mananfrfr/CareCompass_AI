"""Parse card interactions and text replies into a typed Selection.

Per the ASI:One card docs, a card interaction arrives as a follow-up ChatMessage whose
TextContent is either the selection JSON (direct @mention) or prose written by the planner
that contains every identifier. JSON is tried first, then a conservative prose parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

ACTIONS = {"select_hospital", "review", "approve", "cancel", "back", "revise"}
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}


@dataclass
class Selection:
    action: str | None = None
    hospital_id: str | None = None
    case_id: str | None = None
    version: int | None = None
    from_card: bool = False


def _from_json(text: str) -> Selection | None:
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("action") not in ACTIONS:
        return None
    version = data.get("version")
    return Selection(action=data["action"], hospital_id=data.get("hospital_id"), case_id=data.get("case_id"),
                     version=int(version) if str(version).isdigit() else None, from_card=True)


def parse_selection(text: str, ranked_ids: list[str], names: dict[str, str] | None = None) -> Selection:
    sel = _from_json(text)
    if sel:
        return sel
    low = " ".join(text.lower().split())
    names = names or {}
    hospital_id = next((hid for hid in ranked_ids if hid.lower() in low), None)
    if not hospital_id:
        for hid, name in names.items():
            if name.lower() in low:
                hospital_id = hid
                break
    if not hospital_id:
        m = re.search(r"(?:option|number|no\.?|#|hospital|choose|pick|select|details?(?: for| of)?)\s*(\d)\b", low) \
            or re.fullmatch(r"\s*(\d)\s*[.!]?\s*", low)
        idx = int(m.group(1)) if m else next((v for k, v in ORDINALS.items() if re.search(rf"\b{k}\b", low)), None)
        if idx and 1 <= idx <= len(ranked_ids):
            hospital_id = ranked_ids[idx - 1]

    negated = re.search(r"\b(?:don'?t|do not|not|never)\s+(?:approve|save|confirm)", low)
    # Only explicit approval words execute; "save ..." first shows the review/approval step.
    if re.search(r"\b(?:approve[ds]?|confirm(?:ed)?|yes|go ahead|proceed)\b", low) and not negated:
        return Selection(action="approve", hospital_id=hospital_id)
    if negated or re.search(r"\b(?:cancel(?:led)?|reject(?:ed)?|no thanks|stop|revise)\b", low) or low in {"no", "nope"}:
        return Selection(action="cancel")
    if re.search(r"\b(?:back to (?:the )?(?:list|shortlist)|show (?:the )?(?:list|shortlist)|go back)\b", low) or low == "back":
        return Selection(action="back")
    if re.search(r"\bsave\b", low):
        return Selection(action="review", hospital_id=hospital_id)
    if hospital_id:
        return Selection(action="select_hospital", hospital_id=hospital_id)
    return Selection()
