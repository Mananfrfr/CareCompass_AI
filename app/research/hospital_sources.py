"""Hospital discovery and service verification providers.

FixtureHospitalSource  - synthetic dataset (clearly labelled) for reproducible demos/tests.
OSMHospitalSource      - live: OpenStreetMap via the public Nominatim API (ODbL data),
                         optionally verifying services on the hospital's own website.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup

from app.config import DATA_DIR
from app.intelligence.care_knowledge import SPECIALTIES, normalize_city
from app.research.source_fetcher import FetchError, RateLimiter, SafeFetcher
from app.schemas.evidence import ClaimType, Evidence, Reliability, SourceStatus, SourceType
from app.schemas.hospital import HospitalRecord, HospitalResearchQuery, HospitalResearchResult
from app.security.validation import UnsafeURLError

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Name fragments that hint at a service. Treated as a *weak* signal only.
NAME_HINTS: dict[str, tuple[str, ...]] = {
    "orthopaedics": ("ortho", "bone", "joint", "fracture", "trauma", "spine", "sports injur"),
    "urology": ("uro", "kidney", "stone"),
    "ophthalmology": ("eye", "netra", "vision", "drishti"),
    "cardiology": ("heart", "cardiac", "hriday"),
    "gynaecology": ("maternity", "women", "mother", "gynae", "ivf", "fertility"),
    "paediatrics": ("child", "children", "kids", "paediatric", "pediatric"),
    "oncology": ("cancer", "onco"),
    "ent": ("ent ", "ear nose"),
    "nephrology": ("nephro", "kidney", "dialysis", "renal"),
    "gastroenterology": ("gastro", "digestive", "liver", "endoscopy"),
    "pulmonology": ("chest", "pulmo", "respiratory", "lung"),
    "endocrinology": ("diabet", "endocrin", "thyroid"),
    "dermatology": ("skin", "derma"),
    "neurology": ("neuro", "brain"),
}


class HospitalSource(Protocol):
    name: str

    async def search_hospitals(self, query: HospitalResearchQuery) -> HospitalResearchResult: ...


class FixtureHospitalSource:
    name = "synthetic-hospital-fixtures"

    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "fixtures" / "hospitals.json"

    async def search_hospitals(self, query: HospitalResearchQuery) -> HospitalResearchResult:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        retrieved = datetime.fromisoformat(data["retrieved_at"])
        city = normalize_city(query.city) or query.city
        result = HospitalResearchResult(task_id=query.task_id, data_mode="fixture")
        for raw in data["hospitals"]:
            if city not in raw["listed_in"]:
                continue
            record = HospitalRecord(
                hospital_id=raw["hospital_id"], name=raw["name"], city=raw["city"], address=raw["address"],
                postcode=raw.get("postcode"), website=raw.get("website"), synthetic=True,
            )
            result.hospitals.append(record)
            common = dict(subject=record.name, subject_id=record.hospital_id, source_name="Synthetic hospital profile",
                          source_url=raw["website"], source_type=SourceType.SYNTHETIC_FIXTURE,
                          retrieved_at=retrieved, synthetic=True, reliability=Reliability.HIGH)
            result.evidence.append(Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=record.name,
                                            excerpt=f"{record.name}, {record.address}", **common))
            result.evidence.append(Evidence(claim_type=ClaimType.LOCATION, claim_value=record.city, city=record.city,
                                            excerpt=f"{record.address} {record.postcode or ''}".strip(), **common))
            for svc in raw.get("services", []):
                result.evidence.append(Evidence(claim_type=ClaimType.SPECIALTY, claim_value=svc["specialty"],
                                                excerpt=svc["excerpt"][:400], **common))
            for capability in raw.get("capabilities", []):
                for value in capability["values"]:
                    result.evidence.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value=value,
                                                    scope=capability["scope"], excerpt="Synthetic declared capability", **common))
        result.source_status.append(SourceStatus(source_name=self.name, url="fixture://hospitals", ok=True,
                                                 retrieved_at=retrieved))
        # Keep the most relevant first: hospitals with evidence for the requested specialty.
        relevant = {e.subject_id for e in result.evidence
                    if e.claim_type == ClaimType.SPECIALTY and e.claim_value == query.specialty}
        result.hospitals.sort(key=lambda h: h.hospital_id not in relevant)
        return result


def _specialty_from_text(text: str, specialty: str) -> str | None:
    """Return a short excerpt if the page text advertises the specialty."""
    spec = SPECIALTIES.get(specialty)
    if not spec:
        return None
    low = text.lower()
    for kw in spec.site_keywords:
        pattern = rf"\b{re.escape(kw)}\b"
        m = re.search(pattern, low)
        if m:
            start = max(0, m.start() - 80)
            return " ".join(text[start : m.end() + 120].split())
    return None


class OSMHospitalSource:
    """Live hospital discovery from OpenStreetMap (Nominatim usage policy: <=1 req/s, identify UA, cache)."""

    name = "openstreetmap-nominatim"
    _cache: dict[str, tuple[float, list[dict]]] = {}
    _limiter = RateLimiter(1.1)

    def __init__(self, fetcher: SafeFetcher, max_candidates: int = 40, verify_websites: bool = True,
                 cache_ttl_s: int = 6 * 3600):
        self.fetcher = fetcher  # robots.txt-respecting fetcher for hospital websites
        # Nominatim is an API governed by the OSMF usage policy (<=1 req/s, identifying User-Agent,
        # caching, attribution), not a crawl target; its robots.txt is aimed at crawlers. This fetcher
        # is pinned to that single host.
        self.api_fetcher = SafeFetcher(fetcher.user_agent, timeout_s=fetcher.timeout_s, resolver=fetcher.resolver,
                                       transport=fetcher.transport, respect_robots=False,
                                       allowed_hosts={"nominatim.openstreetmap.org"})
        self.max_candidates = max_candidates
        self.verify_websites = verify_websites
        self.cache_ttl_s = cache_ttl_s

    async def _nominatim(self, q: str) -> list[dict]:
        cached = self._cache.get(q)
        if cached and time.time() - cached[0] < self.cache_ttl_s:
            return cached[1]
        await self._limiter.wait()
        doc = await self.api_fetcher.fetch(NOMINATIM_URL, params={
            "q": q, "format": "jsonv2", "limit": str(self.max_candidates), "extratags": "1",
            "addressdetails": "1", "countrycodes": "in",
        })
        rows = json.loads(doc.text)
        if not isinstance(rows, list):
            raise FetchError("Unexpected Nominatim response")
        self._cache[q] = (time.time(), rows)
        return rows

    async def search_hospitals(self, query: HospitalResearchQuery) -> HospitalResearchResult:
        result = HospitalResearchResult(task_id=query.task_id, data_mode="live")
        spec = SPECIALTIES.get(query.specialty)
        queries = [f"hospital in {query.city}"]
        if spec and spec.key != "general_medicine":
            queries.insert(0, f"{spec.label.split(' (')[0].split(' /')[0]} hospital in {query.city}")
        rows: dict[str, dict] = {}
        for q in queries:
            try:
                for row in await self._nominatim(q):
                    rows.setdefault(f"{row.get('osm_type')}/{row.get('osm_id')}", row)
                result.source_status.append(SourceStatus(source_name=f"{self.name}: {q}", url=NOMINATIM_URL, ok=True))
            except (FetchError, UnsafeURLError, ValueError) as exc:
                result.source_status.append(SourceStatus(source_name=f"{self.name}: {q}", url=NOMINATIM_URL, ok=False,
                                                         error=str(exc)[:200]))
        requested_city = normalize_city(query.city) or query.city
        for key, row in rows.items():
            record, evidence = self._to_record(key, row, query.specialty)
            if record is None:
                continue
            if record.city != requested_city and not query.allow_nearby:
                # Still returned: decision rules will exclude it with an explicit reason.
                pass
            result.hospitals.append(record)
            result.evidence.extend(evidence)
        # Prefer hospitals with some specialty signal.
        signal = {e.subject_id for e in result.evidence if e.claim_type == ClaimType.SPECIALTY}
        result.hospitals.sort(key=lambda h: h.hospital_id not in signal)
        result.hospitals = result.hospitals[: max(query.max_results * 2, 10)]
        keep = {h.hospital_id for h in result.hospitals}
        result.evidence = [e for e in result.evidence if e.subject_id in keep]

        if self.verify_websites:
            for record in result.hospitals[: query.max_results]:
                if record.website:
                    result.evidence.extend(await self._verify_website(record, query.specialty, result))
        return result

    def _to_record(self, key: str, row: dict, specialty: str) -> tuple[HospitalRecord | None, list[Evidence]]:
        name = (row.get("name") or "").strip()
        tags = row.get("extratags") or {}
        if not name or row.get("type") not in {"hospital", "clinic", "doctors"} and row.get("category") not in {"amenity", "healthcare"}:
            return None, []
        address = row.get("address") or {}
        city_raw = address.get("city") or address.get("town") or address.get("state_district") or address.get("county") or ""
        city = normalize_city(city_raw) or city_raw.replace(" District", "").strip()
        osm_url = f"https://www.openstreetmap.org/{row.get('osm_type')}/{row.get('osm_id')}"
        website = tags.get("website") or tags.get("contact:website")
        record = HospitalRecord(
            hospital_id=f"osm-{key.replace('/', '-')}", name=name, city=city,
            address=row.get("display_name", "")[:300], postcode=address.get("postcode"), website=website,
            latitude=float(row["lat"]) if row.get("lat") else None,
            longitude=float(row["lon"]) if row.get("lon") else None,
        )
        common = dict(subject=name, subject_id=record.hospital_id, source_name="OpenStreetMap (community-maintained)",
                      source_url=osm_url, source_type=SourceType.COMMUNITY_DIRECTORY)
        evidence = [
            Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=name, excerpt=f"amenity={tags.get('amenity', row.get('type'))}",
                     reliability=Reliability.MEDIUM, **common),
            Evidence(claim_type=ClaimType.LOCATION, claim_value=city, city=city, excerpt=record.address[:200],
                     reliability=Reliability.MEDIUM, **common),
        ]
        spec = SPECIALTIES.get(specialty)
        osm_specialities = [s.strip() for s in (tags.get("healthcare:speciality") or "").split(";") if s.strip()]
        if spec and any(s in spec.osm_tags for s in osm_specialities):
            evidence.append(Evidence(claim_type=ClaimType.SPECIALTY, claim_value=specialty, reliability=Reliability.MEDIUM,
                                     excerpt=f"healthcare:speciality={tags.get('healthcare:speciality')}", **common))
        else:
            low = name.lower() + " "
            if any(h in low for h in NAME_HINTS.get(specialty, ())):
                evidence.append(Evidence(claim_type=ClaimType.SPECIALTY, claim_value=specialty, reliability=Reliability.LOW,
                                         excerpt=f"Hospital name suggests this service: '{name}'", **common))
        return record, evidence

    async def _verify_website(self, record: HospitalRecord, specialty: str,
                              result: HospitalResearchResult) -> list[Evidence]:
        url = record.website if "://" in (record.website or "") else f"https://{record.website}"
        try:
            doc = await self.fetcher.fetch(url)
        except (FetchError, UnsafeURLError) as exc:
            result.source_status.append(SourceStatus(source_name=f"official site: {record.name}", url=url, ok=False,
                                                     error=str(exc)[:200]))
            return []
        result.source_status.append(SourceStatus(source_name=f"official site: {record.name}", url=doc.final_url, ok=True))
        if "html" not in doc.content_type and "text" not in doc.content_type:
            return []
        text = BeautifulSoup(doc.text, "html.parser").get_text(" ", strip=True)
        excerpt = _specialty_from_text(text, specialty)
        if not excerpt:
            return []
        ev_list = [Evidence(claim_type=ClaimType.SPECIALTY, claim_value=specialty, subject=record.name,
                            subject_id=record.hospital_id, source_name="Hospital website", source_url=doc.final_url,
                            source_type=SourceType.OFFICIAL_HOSPITAL_SITE, excerpt=excerpt[:300],
                            retrieved_at=doc.retrieved_at, reliability=Reliability.HIGH)]
        low = text.lower()
        # General outpatient consultation capability when specialty is advertised
        if any(w in low for w in ("consult", "opd", "appointment", "outpatient", "doctor", "specialist")):
            ev_list.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value="outpatient_consultation",
                                    subject=record.name, subject_id=record.hospital_id, source_name="Hospital website",
                                    source_url=doc.final_url, source_type=SourceType.OFFICIAL_HOSPITAL_SITE,
                                    excerpt=excerpt[:250], retrieved_at=doc.retrieved_at, reliability=Reliability.HIGH,
                                    scope=specialty))
        # Condition/procedure specific capabilities
        if specialty == "nephrology":
            if any(w in low for w in ("dialysis", "haemodialysis", "hemodialysis", "dialysis unit")):
                ev_list.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value="dialysis",
                                        subject=record.name, subject_id=record.hospital_id, source_name="Hospital website",
                                        source_url=doc.final_url, source_type=SourceType.OFFICIAL_HOSPITAL_SITE,
                                        excerpt="Hospital website lists dialysis treatment capability.",
                                        retrieved_at=doc.retrieved_at, reliability=Reliability.HIGH, scope=specialty))
                ev_list.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value="nephrology_support",
                                        subject=record.name, subject_id=record.hospital_id, source_name="Hospital website",
                                        source_url=doc.final_url, source_type=SourceType.OFFICIAL_HOSPITAL_SITE,
                                        excerpt="Hospital website confirms nephrology department care.",
                                        retrieved_at=doc.retrieved_at, reliability=Reliability.HIGH, scope=specialty))
        return ev_list


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


class OverpassHospitalSource:
    """Live map discovery from OpenStreetMap via the Overpass API.

    Replaces the old free-text Nominatim search (max 40 fuzzy matches, often missing big
    hospitals) with a radius query around the city centre that returns *every* mapped hospital,
    plus clinics that declare a specialty, with their tags (speciality, phone, website, beds).
    """

    name = "openstreetmap-overpass"
    _cache: dict[str, tuple[float, list[dict]]] = {}
    _limiter = RateLimiter(1.1)

    def __init__(self, fetcher: SafeFetcher, radius_m: int = 15000, max_candidates: int = 25,
                 cache_ttl_s: int = 6 * 3600, centre_lookup=None):
        self.api_fetcher = SafeFetcher(fetcher.user_agent, timeout_s=8, resolver=fetcher.resolver,
                                       transport=fetcher.transport, respect_robots=False, max_attempts=1,
                                       allowed_hosts={"overpass-api.de", "nominatim.openstreetmap.org"})
        self.radius_m = radius_m
        self.max_candidates = max_candidates
        self.cache_ttl_s = cache_ttl_s
        self.centre_lookup = centre_lookup

    async def _centre(self, city: str) -> tuple[float, float] | None:
        if self.centre_lookup:
            centre = self.centre_lookup(city)
            if centre:
                return centre
        await self._limiter.wait()
        doc = await self.api_fetcher.fetch(NOMINATIM_URL, params={"q": f"{city}, India", "format": "jsonv2",
                                                                  "limit": "1", "countrycodes": "in"})
        rows = json.loads(doc.text)
        if isinstance(rows, list) and rows:
            return float(rows[0]["lat"]), float(rows[0]["lon"])
        return None

    async def _elements(self, lat: float, lon: float) -> list[dict]:
        key = f"{lat:.3f},{lon:.3f},{self.radius_m}"
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_ttl_s:
            return cached[1]
        around = f"(around:{self.radius_m},{lat:.5f},{lon:.5f})"
        query = (f'[out:json][timeout:8];(nwr["amenity"="hospital"]{around};nwr["healthcare"="hospital"]{around};'
                 f'nwr["amenity"="clinic"]["healthcare:speciality"]{around};);out center tags 400;')
        await self._limiter.wait()
        doc = await self.api_fetcher.fetch(OVERPASS_URL, params={"data": query})
        data = json.loads(doc.text)
        elements = data.get("elements", []) if isinstance(data, dict) else []
        self._cache[key] = (time.time(), elements)
        return elements

    async def search_hospitals(self, query: HospitalResearchQuery) -> HospitalResearchResult:
        result = HospitalResearchResult(task_id=query.task_id, data_mode="live")
        city = normalize_city(query.city) or query.city.strip().title()
        try:
            centre = await self._centre(city)
            if centre is None:
                raise FetchError(f"could not locate {city}")
            elements = await self._elements(*centre)
        except (FetchError, UnsafeURLError, ValueError, KeyError) as exc:
            result.source_status.append(SourceStatus(source_name=self.name, url=OVERPASS_URL, ok=False,
                                                     error=str(exc)[:200]))
            return result
        result.source_status.append(SourceStatus(source_name=self.name, url=OVERPASS_URL, ok=True))
        spec = SPECIALTIES.get(query.specialty)
        scored = []
        for el in elements:
            tags = el.get("tags") or {}
            name = (tags.get("name:en") or tags.get("name") or "").strip()
            if not name:
                continue
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            specialities = [s.strip().lower() for s in (tags.get("healthcare:speciality") or "").split(";") if s.strip()]
            if spec and any(s in spec.osm_tags for s in specialities):
                signal = "directory"
            elif any(h in f" {name.lower()} " for h in NAME_HINTS.get(query.specialty, ())):
                signal = "weak"
            elif tags.get("amenity") == "hospital" or tags.get("healthcare") == "hospital":
                signal = "general"
            else:
                continue
            dist = None
            if lat is not None and lon is not None:
                from app.research.india_directory import haversine_km
                dist = round(haversine_km(centre[0], centre[1], float(lat), float(lon)), 1)
            scored.append(({"directory": 0, "weak": 1, "general": 2}[signal], dist or 999, name, el, tags, signal,
                           lat, lon, dist))
        scored.sort(key=lambda x: x[:3])
        for _, _, name, el, tags, signal, lat, lon, dist in scored[: self.max_candidates]:
            osm_url = f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}"
            addr = ", ".join(tags[k] for k in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city",
                                               "addr:postcode") if tags.get(k))
            beds = re.search(r"\d+", tags.get("beds", "") or "")
            record = HospitalRecord(
                hospital_id=f"osm-{el.get('type')}-{el.get('id')}", name=name, city=city, address=addr or city,
                postcode=tags.get("addr:postcode"), website=tags.get("website") or tags.get("contact:website"),
                latitude=float(lat) if lat is not None else None, longitude=float(lon) if lon is not None else None,
                phone=tags.get("phone") or tags.get("contact:phone"), beds=int(beds[0]) if beds else None,
                facilities=["emergency_services"] if tags.get("emergency") == "yes" else [],
                distance_km=dist, discovery_source=self.name,
                ownership_type={"government": "public", "public": "public", "private": "private"}.get(
                    tags.get("operator:type", ""), "unknown"),
            )
            common = dict(subject=name, subject_id=record.hospital_id, source_name="OpenStreetMap (community-maintained)",
                          source_url=osm_url, source_type=SourceType.COMMUNITY_DIRECTORY)
            result.hospitals.append(record)
            result.evidence += [
                Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=name, reliability=Reliability.MEDIUM,
                         excerpt=f"amenity={tags.get('amenity') or tags.get('healthcare')}; {addr}"[:200], **common),
                Evidence(claim_type=ClaimType.LOCATION, claim_value=city, city=city, reliability=Reliability.MEDIUM,
                         excerpt=f"Mapped {dist} km from the {city} centre" if dist is not None else addr[:200], **common),
            ]
            if signal == "directory":
                result.evidence.append(Evidence(claim_type=ClaimType.SPECIALTY, claim_value=query.specialty,
                                                reliability=Reliability.MEDIUM, scope=query.specialty,
                                                excerpt=f"healthcare:speciality={tags.get('healthcare:speciality')}",
                                                **common))
            elif signal == "weak":
                result.evidence.append(Evidence(claim_type=ClaimType.SPECIALTY, claim_value=query.specialty,
                                                reliability=Reliability.LOW,
                                                excerpt=f"Hospital name suggests this service: '{name}'", **common))
            else:
                result.evidence.append(Evidence(claim_type=ClaimType.CAPABILITY, claim_value="multispeciality_hospital",
                                                scope="hospital", reliability=Reliability.LOW,
                                                excerpt="Mapped as a hospital; department not listed", **common))
        return result


def build_hospital_source(fixture_mode: bool, fetcher: SafeFetcher | None = None,
                          max_candidates: int = 40) -> HospitalSource:
    from app.research.hospital_catalog import CombinedHospitalSource, FixtureFirstHospitalSource
    from app.research.india_directory import DirectoryHospitalSource
    if fixture_mode:
        # Synthetic demo cities stay synthetic; every other Indian city uses the real directory.
        return FixtureFirstHospitalSource(FixtureHospitalSource(), DirectoryHospitalSource())
    assert fetcher is not None
    from app.research.india_directory import get_directory
    overpass = OverpassHospitalSource(fetcher, max_candidates=min(max_candidates, 25),
                                      centre_lookup=lambda city: get_directory().centroid(city))
    return CombinedHospitalSource([DirectoryHospitalSource()], live_map=overpass)
