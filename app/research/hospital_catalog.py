"""Hospital discovery pipeline: curated official catalog + India-wide directory + live map data.

Order of trust (first source wins on identity, later sources add evidence):
1. Curated official catalog (reviewed clinical profiles and state government directories).
2. National Health Portal directory (~30k registered facilities across India).
3. OpenStreetMap via Overpass (live map data: newer hospitals, coordinates, specialty tags).

Duplicates across sources are merged only when the names match AND nothing contradicts it
(different postcode, branch, or locations more than 1.5 km apart). Ambiguous pairs stay separate.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config import DATA_DIR
from app.intelligence.care_knowledge import normalize_city
from app.research.entity_resolution import Identity, MatchDecision, compare
from app.research.india_directory import canonical_city, haversine_km
from app.schemas.evidence import ClaimType, Evidence, SourceStatus, SourceType
from app.schemas.hospital import HospitalRecord, HospitalResearchQuery, HospitalResearchResult

SOURCE_TIMEOUT_S = 22


class CatalogHospitalSource:
    name = "official-branch-catalog"

    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "catalog" / "hospitals.json"

    async def search_hospitals(self, query):
        result = HospitalResearchResult(task_id=query.task_id, data_mode="live")
        paths = [self.path, self.path.with_name("clinical_hospitals.json")]
        want = (normalize_city(query.city) or canonical_city(query.city) or query.city).casefold()
        for path in paths:
            if not path.exists():
                continue
            for raw in json.loads(path.read_text(encoding="utf-8"))["records"]:
                # Nearby is not permission to silently recommend anywhere in India.
                if (normalize_city(raw["city"]) or canonical_city(raw["city"])).casefold() != want:
                    continue
                record = HospitalRecord.model_validate(raw)
                result.hospitals.append(record)
                common = dict(subject=record.name, subject_id=record.hospital_id,
                              source_name="Official facility directory", source_url=raw["source_url"],
                              source_type=SourceType.OFFICIAL_HOSPITAL_SITE if raw.get("evidence") else SourceType.OFFICIAL_GOVERNMENT,
                              retrieved_at=raw["checked_at"])
                result.evidence.extend([
                    Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=record.name, **common),
                    Evidence(claim_type=ClaimType.LOCATION, claim_value=record.city, city=record.city, **common),
                ])
                result.evidence.extend(Evidence.model_validate(e) for e in raw.get("evidence", []))
        result.source_status.append(SourceStatus(source_name=self.name, ok=True))
        return result


def _same_hospital(a: HospitalRecord, b: HospitalRecord) -> bool:
    if a.latitude is not None and b.latitude is not None and \
            haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) > 1.5:
        return False
    decision = compare(Identity(a.name, a.city, a.address, a.postcode, website=a.website),
                       Identity(b.name, b.city, b.address, b.postcode, website=b.website)).decision
    return decision == MatchDecision.MATCH


def merge_results(base: HospitalResearchResult, extra: HospitalResearchResult) -> None:
    """Fold `extra` into `base`, re-pointing evidence of duplicate hospitals to the kept record."""
    for record in extra.hospitals:
        own = [e for e in extra.evidence if e.subject_id == record.hospital_id]
        twin = next((h for h in base.hospitals if _same_hospital(h, record)), None)
        if twin is None:
            base.hospitals.append(record)
            base.evidence.extend(own)
            continue
        for field in ("latitude", "longitude", "phone", "website", "beds", "distance_km", "postcode"):
            if getattr(twin, field) in (None, "") and getattr(record, field) not in (None, ""):
                setattr(twin, field, getattr(record, field))
        twin.facilities = sorted(set(twin.facilities) | set(record.facilities))
        existing = {e.evidence_id for e in base.evidence}
        for e in own:
            moved = e.model_copy(update={"subject_id": twin.hospital_id})
            if moved.evidence_id not in existing:
                base.evidence.append(moved)
    base.source_status.extend(extra.source_status)


class CombinedHospitalSource:
    name = "catalog-directory-and-live-map"

    def __init__(self, sources):
        self.catalog = CatalogHospitalSource()
        self.sources = sources if isinstance(sources, (list, tuple)) else [sources]

    async def _safe(self, source, query):
        try:
            return await asyncio.wait_for(source.search_hospitals(query), timeout=SOURCE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - one source failing must not sink the others
            return HospitalResearchResult(task_id=query.task_id, data_mode="live", source_status=[SourceStatus(
                source_name=getattr(source, "name", type(source).__name__), ok=False,
                error=f"unavailable ({type(exc).__name__}); other sources retained")])

    async def search_hospitals(self, query: HospitalResearchQuery):
        result = await self.catalog.search_hospitals(query)
        extras = await asyncio.gather(*(self._safe(s, query) for s in self.sources))
        for extra in extras:
            merge_results(result, extra)
        return result


class FixtureFirstHospitalSource:
    """Demo mode: synthetic fixtures for the demo cities, the real India directory everywhere else.

    Results never mix: a city is served entirely by fixtures (data_mode "fixture") or entirely by
    real public data (data_mode "live"), so synthetic records are never presented as real.
    """

    name = "fixture-or-india-directory"

    def __init__(self, fixture, directory):
        self.fixture = fixture
        self.directory = directory

    async def search_hospitals(self, query: HospitalResearchQuery):
        result = await self.fixture.search_hospitals(query)
        if result.hospitals:
            return result
        live = await CombinedHospitalSource([self.directory]).search_hospitals(query)
        live.data_mode = "live"
        return live
