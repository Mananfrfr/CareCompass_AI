"""India-wide hospital directory (National Health Portal, MoHFW, via data.gov.in).

~30,000 registered facilities across Indian states with district, pincode, phone and (for about
a third) GPS coordinates. Used as the backbone of hospital discovery so that *any* Indian city
returns real, government-listed hospitals - not just the handful of cities with hand-curated
profiles.

Evidence honesty:
- HOSPITAL_EXISTS / LOCATION come from a government directory (OFFICIAL_GOVERNMENT).
- A specialty column entry is a *self-declared directory listing*. It produces a "directory"
  specialty signal, never a "verified" one (only the hospital's own current site can verify).
- A specialty guessed from the hospital's name is a *weak* signal.
- Multi-speciality / general hospitals with no listing for the service are "general" leads:
  the user is told to call and confirm the department.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR
from app.intelligence.care_knowledge import SPECIALTIES, normalize_city
from app.schemas.evidence import ClaimType, Evidence, Reliability, SourceStatus, SourceType
from app.schemas.hospital import HospitalRecord, HospitalResearchQuery, HospitalResearchResult

DIRECTORY_PATH = DATA_DIR / "catalog" / "india_hospitals.json.gz"
SOURCE_URL = "https://data.gov.in/catalog/hospital-directory-national-health-portal"
SOURCE_NAME = "National Health Portal hospital directory (MoHFW, data.gov.in)"

# Declared-specialty vocabulary in the NHP directory -> CareCompass service keys.
DECLARED_PATTERNS: dict[str, tuple[str, ...]] = {
    "orthopaedics": (r"ortho", r"joint replacement", r"arthroscop", r"sports (?:medicine|injur)", r"spine", r"trauma",
                     r"fracture", r"bone"),
    "urology": (r"urolog", r"andrology", r"lithotripsy", r"kidney stone"),
    "ophthalmology": (r"ophthalm", r"\beye\b", r"cataract", r"retina", r"glaucoma", r"cornea", r"lasik", r"squint"),
    "cardiology": (r"cardio", r"cardiac", r"\bheart\b", r"cath ?lab"),
    "gynaecology": (r"gyna?ec", r"gynec", r"obstet", r"maternity", r"\bivf\b", r"infertility", r"\bob ?g ?y"),
    "gastroenterology": (r"gastro", r"hepatolog", r"endoscop", r"\bliver\b"),
    "general_surgery": (r"general surgery", r"laparoscop", r"\bsurgery\b", r"bariatric"),
    "neurology": (r"neuro", r"stroke"),
    "dermatology": (r"dermat", r"\bskin\b", r"cosmetolog", r"venereolog"),
    "ent": (r"\bent\b", r"otolaryng", r"otorhino", r"ear,? nose"),
    "pulmonology": (r"pulmo", r"chest", r"respirat", r"\btb\b", r"tuberculosis"),
    "nephrology": (r"nephro", r"dialysis", r"renal", r"kidney transplant"),
    "paediatrics": (r"paediat", r"pediat", r"neonat", r"\bnicu\b", r"child"),
    "oncology": (r"onco", r"cancer", r"haemat", r"hemat", r"radiotherap", r"chemotherap"),
    "endocrinology": (r"endocrin", r"diabet", r"thyroid"),
    "psychiatry": (r"psychiat", r"mental", r"de-?addiction", r"psycholog"),
    "general_medicine": (r"general medicine", r"internal medicine", r"\bmedicine\b", r"physician", r"family medicine"),
}

NAME_HINTS: dict[str, tuple[str, ...]] = {
    "orthopaedics": ("ortho", "bone", "joint", "fracture", "trauma", "spine", "sports injur", "accident"),
    "urology": ("uro", "kidney", "stone", "andro"),
    "ophthalmology": ("eye", "netra", "nethra", "vision", "drishti", "lasik", "retina", "nayan"),
    "cardiology": ("heart", "cardiac", "cardio", "hriday"),
    "gynaecology": ("maternity", "women", "mother", "gynae", "gyne", "ivf", "fertility", "nursing home"),
    "paediatrics": ("child", "children", "kids", "paediatric", "pediatric", "shishu", "bal "),
    "oncology": ("cancer", "onco", "tumour", "tumor"),
    "ent": ("ent ", "ear nose", " e.n.t"),
    "dermatology": ("skin", "derma"),
    "neurology": ("neuro", "brain", "stroke"),
    "nephrology": ("kidney", "nephro", "dialysis"),
    "gastroenterology": ("gastro", "liver", "digestive"),
    "psychiatry": ("mental", "psychiatr", "de-addiction", "manas"),
    "pulmonology": ("chest", "lung", "tb ", "tuberculosis"),
    "endocrinology": ("diabet", "thyroid", "endocrin"),
}

GENERAL_HINTS = re.compile(
    r"multi[- ]?special|super[- ]?special|multispecial|general hospital|civil hospital|district hospital|"
    r"medical college|institute of medical|\baiims\b|\besic\b|government hospital|govt\.? hospital|"
    r"municipal|sub[- ]district hospital|referral hospital|memorial hospital|medical cent(?:er|re)|\bhealthcare\b|"
    r"\binstitute\b|\bmedicity\b|\bglobal hospital", re.I)
FACILITY_PATTERNS: dict[str, str] = {
    "emergency_services": r"emergency|casualty|trauma|24 ?(?:x ?7|hours?)",
    "icu": r"\bicu\b|intensive care|critical care|\biccu\b|\bnicu\b",
    "blood_bank": r"blood bank",
    "dialysis": r"dialysis",
    "operation_theatre": r"operation theat|\bo\.?t\.?\b|surgical",
    "radiology": r"x-?ray|\bmri\b|\bct\b|radiolog|imaging|ultrasound|sonograph",
    "pharmacy": r"pharmacy|chemist",
    "ambulance": r"ambulance",
}
AYUSH_ONLY = re.compile(r"ayush|ayurved|homeopath|unani|siddha|naturopath", re.I)


def specialties_from_text(text: str) -> list[str]:
    low = (text or "").lower()
    if not low.strip():
        return []
    return sorted(k for k, pats in DECLARED_PATTERNS.items() if any(re.search(p, low) for p in pats))


def canonical_city(raw: str | None) -> str:
    """Canonical display name for a district/town/city string."""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", str(raw)).strip(" ,.")
    norm = normalize_city(text)
    if norm:
        return norm
    stripped = re.sub(r"\b(?:urban|rural|district|dist\.?|city|suburban|corporation|metropolitan)\b", "", text,
                      flags=re.I).strip(" ,.-")
    return normalize_city(stripped) or stripped.title()


def city_key(raw: str | None) -> str:
    return re.sub(r"[^a-z]", "", canonical_city(raw).lower())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class DirectoryHit:
    record: dict
    distance_km: float | None
    in_city: bool
    signal: str          # directory | weak | general | none
    location_suspect: bool = False


def _median(values: list[float]) -> float:
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


class IndiaDirectory:
    def __init__(self, path: Path | None = None):
        self.path = path or DIRECTORY_PATH
        self.meta: dict = {}
        self.records: list[dict] = []
        self.by_city: dict[str, list[dict]] = {}
        self.city_names: dict[str, str] = {}
        self.centroids: dict[str, tuple[float, float]] = {}
        self._load()

    @property
    def available(self) -> bool:
        return bool(self.records)

    def _load(self) -> None:
        if not self.path.exists():
            return
        with gzip.open(self.path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        self.meta = {k: v for k, v in data.items() if k != "records"}
        self.records = data.get("records", [])
        for rec in self.records:
            keys = {city_key(rec.get("d"))}
            if rec.get("t"):
                keys.add(city_key(rec["t"]))
            for k in keys - {""}:
                self.by_city.setdefault(k, []).append(rec)
        for k, recs in self.by_city.items():
            names = [canonical_city(r.get("d")) for r in recs if city_key(r.get("d")) == k] or \
                    [canonical_city(r.get("t")) for r in recs]
            self.city_names[k] = max(set(names), key=names.count) if names else k.title()
            pts = [(r["lat"], r["lon"]) for r in recs if r.get("lat") is not None]
            if len(pts) >= 3:
                self.centroids[k] = (_median([p[0] for p in pts]), _median([p[1] for p in pts]))

    @property
    def imported_at(self) -> datetime:
        try:
            stamp = datetime.fromisoformat(self.meta.get("imported_at", ""))
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)

    def known_city(self, raw: str) -> str | None:
        key = city_key(raw)
        return self.city_names.get(key) if key and len(self.by_city.get(key, [])) >= 2 else None

    def centroid(self, city: str) -> tuple[float, float] | None:
        return self.centroids.get(city_key(city))

    def search(self, city: str, specialty: str, allow_nearby: bool = False, radius_km: float = 40.0,
               limit: int = 40) -> list[DirectoryHit]:
        key = city_key(city)
        centre = self.centroids.get(key)
        hits: dict[str, DirectoryHit] = {}
        for rec in self.by_city.get(key, []):
            hit = self._hit(rec, specialty, centre, in_city=True)
            if hit:
                hits[rec["id"]] = hit
        if allow_nearby and centre:
            for rec in self.records:
                if rec["id"] in hits or rec.get("lat") is None:
                    continue
                dist = haversine_km(centre[0], centre[1], rec["lat"], rec["lon"])
                if dist <= radius_km:
                    hit = self._hit(rec, specialty, centre, in_city=False)
                    if hit:
                        hits[rec["id"]] = hit
        order = {"directory": 0, "weak": 1, "general": 2, "none": 3}
        ranked = sorted(hits.values(), key=lambda h: (h.location_suspect, order[h.signal], not h.in_city,
                                                      h.distance_km if h.distance_km is not None else 999,
                                                      -(h.record.get("b") or 0), -len(h.record), h.record["n"]))
        # The directory has duplicate rows for the same facility; keep the most informative one.
        from app.research.entity_resolution import core_tokens
        kept: dict[tuple, list[dict]] = {}
        unique = []
        for h in ranked:
            rec = h.record
            key = (tuple(sorted(core_tokens(rec["n"]))) or (rec["n"].lower(),), city_key(rec.get("d")))
            if any(_same_facility(rec, other) for other in kept.get(key, [])):
                continue  # same name, same district and same phone / pincode / location: one facility
            kept.setdefault(key, []).append(rec)
            unique.append(h)
        return unique[:limit]

    @staticmethod
    def _hit(rec: dict, specialty: str, centre, in_city: bool) -> DirectoryHit | None:
        discipline = rec.get("ds", "")
        if discipline and AYUSH_ONLY.search(discipline) and "allopath" not in discipline.lower():
            return None  # AYUSH-only facilities are not routed to for allopathic specialty navigation
        dist = None
        suspect = False
        if centre and rec.get("lat") is not None:
            dist = round(haversine_km(centre[0], centre[1], rec["lat"], rec["lon"]), 1)
            # Coordinates far from the listed district are a data error: keep, but never rank first.
            suspect = in_city and dist > 60
        signal = signal_for(rec, specialty)
        return DirectoryHit(rec, dist, in_city, signal, suspect)


def signal_for(rec: dict, specialty: str) -> str:
    if specialty and specialty in rec.get("sp", []):
        return "directory"
    low = f" {rec.get('n', '').lower()} "
    if any(h in low for h in NAME_HINTS.get(specialty, ())):
        return "weak"
    if GENERAL_HINTS.search(rec.get("n", "")) or (rec.get("b") or 0) >= 50 or len(rec.get("sp", [])) >= 4 \
            or "medical college" in rec.get("ct", "").lower():
        return "general"
    if specialty == "general_medicine" and re.search(r"hospital|clinic|health cent", rec.get("n", ""), re.I):
        return "general"
    return "none"


def _same_facility(a: dict, b: dict) -> bool:
    """Different branches of a chain share a name; only merge rows that also share a contact or place."""
    pa, pb = re.sub(r"\D", "", a.get("ph", ""))[-8:], re.sub(r"\D", "", b.get("ph", ""))[-8:]
    if pa and pb:
        return pa == pb
    if a.get("lat") is not None and b.get("lat") is not None:
        return haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) < 1.0
    return bool(a.get("p")) and a.get("p") == b.get("p") and a.get("a", "")[:20].lower() == b.get("a", "")[:20].lower()


def facilities_of(rec: dict) -> list[str]:
    text = f"{rec.get('f', '')} {rec.get('er', '')}".lower()
    return sorted(k for k, p in FACILITY_PATTERNS.items() if re.search(p, text))


@lru_cache(maxsize=1)
def get_directory() -> IndiaDirectory:
    return IndiaDirectory()


class DirectoryHospitalSource:
    """Hospital discovery over the India-wide government directory."""

    name = "nhp-india-hospital-directory"

    def __init__(self, directory: IndiaDirectory | None = None, max_candidates: int = 15):
        self.directory = directory
        self.max_candidates = max_candidates

    async def search_hospitals(self, query: HospitalResearchQuery) -> HospitalResearchResult:
        directory = self.directory or get_directory()
        result = HospitalResearchResult(task_id=query.task_id, data_mode="live")
        if not directory.available:
            result.source_status.append(SourceStatus(source_name=self.name, ok=False,
                                                     error="India hospital directory file is not installed"))
            return result
        retrieved = directory.imported_at
        city = directory.known_city(query.city) or canonical_city(query.city)
        hits = directory.search(city, query.specialty, allow_nearby=query.allow_nearby,
                                limit=self.max_candidates)
        hits = [h for h in hits if h.signal != "none" or query.specialty == "general_medicine"] or hits[:5]
        spec_label = SPECIALTIES[query.specialty].label if query.specialty in SPECIALTIES else query.specialty
        for hit in hits[: self.max_candidates]:
            rec = hit.record
            hospital_city = city if hit.in_city else canonical_city(rec.get("d"))
            address = ", ".join(x for x in [rec.get("a", ""), rec.get("t", ""), rec.get("d", ""), rec.get("s", ""),
                                            rec.get("p", "")] if x)[:300]
            record = HospitalRecord(
                hospital_id=rec["id"], name=rec["n"], city=hospital_city, address=address,
                postcode=rec.get("p"), website=_website(rec.get("w")), latitude=rec.get("lat"),
                longitude=rec.get("lon"), state=rec.get("s"), district=rec.get("d"),
                ownership_type=_ownership(rec.get("cat", "")), phone=rec.get("ph") or rec.get("em"),
                care_type=rec.get("ct"), beds=rec.get("b"), facilities=facilities_of(rec),
                distance_km=hit.distance_km, location_note=("Directory coordinates are far from the listed district; "
                                                            "confirm the address" if hit.location_suspect else None),
                discovery_source=self.name,
            )
            result.hospitals.append(record)
            common = dict(subject=record.name, subject_id=record.hospital_id, source_name=SOURCE_NAME,
                          source_url=SOURCE_URL, source_type=SourceType.OFFICIAL_GOVERNMENT, retrieved_at=retrieved)
            result.evidence.append(Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=record.name,
                                            excerpt=f"{record.name}; {address}"[:300], reliability=Reliability.HIGH,
                                            **common))
            if not hit.location_suspect:
                result.evidence.append(Evidence(claim_type=ClaimType.LOCATION, claim_value=hospital_city,
                                                city=hospital_city, excerpt=f"District: {rec.get('d')}, {rec.get('s')}",
                                                reliability=Reliability.HIGH, **common))
            if hit.signal == "directory":
                result.evidence.append(Evidence(
                    claim_type=ClaimType.SPECIALTY, claim_value=query.specialty, reliability=Reliability.MEDIUM,
                    excerpt=f"Directory lists specialties: {rec.get('spr', '')}"[:300], scope=query.specialty, **common))
            elif hit.signal == "weak":
                result.evidence.append(Evidence(
                    claim_type=ClaimType.SPECIALTY, claim_value=query.specialty, reliability=Reliability.LOW,
                    excerpt=f"Hospital name suggests {spec_label} services: '{record.name}' (unverified)", **common))
            elif hit.signal == "general":
                why = (f"{rec['b']} beds" if rec.get("b") else rec.get("ct") or "name indicates a general / "
                       "multi-speciality facility")
                result.evidence.append(Evidence(
                    claim_type=ClaimType.CAPABILITY, claim_value="multispeciality_hospital", scope="hospital",
                    reliability=Reliability.LOW, excerpt=f"General or multi-speciality facility ({why}); "
                                                         f"{spec_label} department not listed", **common))
            for facility in record.facilities:
                result.evidence.append(Evidence(
                    claim_type=ClaimType.CAPABILITY, claim_value=facility, scope="hospital",
                    reliability=Reliability.MEDIUM, excerpt=f"Directory lists facility: {facility.replace('_', ' ')}", **common))
        result.source_status.append(SourceStatus(source_name=SOURCE_NAME, url=SOURCE_URL, ok=True,
                                                 retrieved_at=retrieved))
        return result


def _website(raw: str | None) -> str | None:
    if not raw or "." not in raw or " " in raw.strip():
        return None
    raw = raw.strip().rstrip("/")
    return raw if raw.startswith(("http://", "https://")) else f"http://{raw}"


def _ownership(category: str) -> str:
    low = category.lower()
    if "public" in low or "gov" in low:
        return "public"
    if "private" in low:
        return "private"
    return "unknown"
