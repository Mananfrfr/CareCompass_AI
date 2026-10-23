"""Match hospital identities across sources (insurer lists abbreviate, websites use full names).

Conservative by design: a different branch, city or postcode is never merged, and a
borderline match is reported as AMBIGUOUS instead of being guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from app.intelligence.care_knowledge import normalize_city

_GENERIC = {
    "hospital", "hospitals", "pvt", "private", "ltd", "limited", "the", "and", "of", "centre", "center",
    "multispeciality", "multispecialty", "superspeciality", "superspecialty", "super", "speciality",
    "specialty", "multi", "medical", "healthcare", "health", "care", "institute", "research", "clinic",
    "nursing", "home", "memorial", "trust", "unit", "llp", "inc",
}
_ABBREV_EXPANSIONS = {"hosp": "hospital", "hsptl": "hospital", "inst": "institute", "ctr": "centre", "res": "research",
                      "med": "medical", "spl": "speciality", "multi-speciality": "multispeciality"}


class MatchDecision(str, Enum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class Identity:
    name: str
    city: str
    address: str = ""
    postcode: str | None = None
    branch: str | None = None
    website: str | None = None


@dataclass(frozen=True)
class MatchResult:
    decision: MatchDecision
    score: float
    reason: str


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    out = []
    for tok in text.replace("-", " ").split():
        out.append(_ABBREV_EXPANSIONS.get(tok, tok))
    return out


def split_branch(name: str) -> tuple[str, str | None]:
    """'Aravali Hospital (Malviya Nagar)' -> ('Aravali Hospital', 'malviya nagar')."""
    m = re.match(r"^(.*?)\s*[\(\[]\s*([^\)\]]+)\s*[\)\]]\s*$", name)
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    m = re.match(r"^(.*?)\s+[-–,]\s+(.+)$", name)
    if m and len(m.group(2).split()) <= 3:
        return m.group(1).strip(), m.group(2).strip().lower()
    return name.strip(), None


def core_tokens(name: str) -> list[str]:
    base, _ = split_branch(name)
    return [t for t in _tokens(base) if t not in _GENERIC]


def initials(name: str) -> str:
    base, _ = split_branch(name)
    return "".join(t[0] for t in _tokens(base) if t not in {"the", "and", "of", "pvt", "ltd", "private", "limited"})


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def _clean_postcode(pc: str | None) -> str | None:
    if not pc:
        return None
    digits = re.sub(r"\D", "", pc)
    return digits or None


def compare(a: Identity, b: Identity) -> MatchResult:
    city_a, city_b = normalize_city(a.city) or a.city.strip().lower(), normalize_city(b.city) or b.city.strip().lower()
    if city_a.lower() != city_b.lower():
        return MatchResult(MatchDecision.NO_MATCH, 0.0, "different city")

    pa, pb = _clean_postcode(a.postcode), _clean_postcode(b.postcode)
    if pa and pb and pa != pb:
        return MatchResult(MatchDecision.NO_MATCH, 0.0, "different postcode")

    _, branch_a = split_branch(a.name)
    _, branch_b = split_branch(b.name)
    branch_a = (a.branch or branch_a or "").lower() or None
    branch_b = (b.branch or branch_b or "").lower() or None
    if branch_a and branch_b and branch_a != branch_b:
        return MatchResult(MatchDecision.NO_MATCH, 0.0, "different branch")

    da, db = _domain(a.website), _domain(b.website)
    if da and db:
        if da == db and not (branch_a is None) ^ (branch_b is None):
            return MatchResult(MatchDecision.MATCH, 1.0, "same official domain")

    ta, tb = set(core_tokens(a.name)), set(core_tokens(b.name))
    if ta and tb:
        score = len(ta & tb) / len(ta | tb)
    else:
        score = 0.0

    # Abbreviation such as "ABJH" for "Aravali Bone Joint Hospital".
    abbrev_hit = False
    for short, full in ((a.name, b.name), (b.name, a.name)):
        short_base, _ = split_branch(short)
        compact = re.sub(r"[^a-z]", "", short_base.lower())
        if 2 < len(compact) <= 6 and len(short_base.split()) == 1 and compact == initials(full):
            abbrev_hit = True
    if abbrev_hit:
        score = max(score, 0.75)

    same_postcode = bool(pa and pb and pa == pb)
    one_branch_unknown = (branch_a is None) != (branch_b is None)

    if score >= 0.85 and not one_branch_unknown:
        return MatchResult(MatchDecision.MATCH, score, "name match")
    if score >= 0.6 and same_postcode:
        return MatchResult(MatchDecision.MATCH, score, "name + postcode match")
    if score >= 0.85 and one_branch_unknown and same_postcode:
        return MatchResult(MatchDecision.MATCH, score, "name + postcode match (branch unstated)")
    if score >= 0.5:
        reason = "branch not stated by one source" if one_branch_unknown else "partial name match"
        return MatchResult(MatchDecision.AMBIGUOUS, score, reason)
    return MatchResult(MatchDecision.NO_MATCH, score, "names differ")
