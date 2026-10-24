"""Local branch catalog plus live discovery, with conservative duplicate handling."""
import asyncio
import json
from pathlib import Path

from app.config import DATA_DIR
from app.intelligence.care_knowledge import normalize_city
from app.schemas.evidence import ClaimType, Evidence, SourceStatus, SourceType
from app.schemas.hospital import HospitalRecord, HospitalResearchResult


class CatalogHospitalSource:
    name = "official-branch-catalog"

    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "catalog" / "hospitals.json"

    async def search_hospitals(self, query):
        result = HospitalResearchResult(task_id=query.task_id, data_mode="live")
        paths = [self.path, self.path.with_name("clinical_hospitals.json")]
        for path in paths:
            if not path.exists():
                continue
            for raw in json.loads(path.read_text(encoding="utf-8"))["records"]:
                # Nearby is not permission to silently recommend anywhere in India.
                if (normalize_city(raw["city"]) or raw["city"]).casefold() != (normalize_city(query.city) or query.city).casefold():
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


class CombinedHospitalSource:
    name = "catalog-and-live-discovery"

    def __init__(self, live):
        self.catalog = CatalogHospitalSource()
        self.live = live

    async def search_hospitals(self, query):
        result = await self.catalog.search_hospitals(query)
        try:
            live = await asyncio.wait_for(self.live.search_hospitals(query), timeout=22)
            # Keep separate IDs where identity is ambiguous; verifier de-duplicates exact matches.
            result.hospitals.extend(live.hospitals)
            result.evidence.extend(live.evidence)
            result.source_status.extend(live.source_status)
        except Exception as exc:
            result.source_status.append(SourceStatus(source_name=self.live.name, ok=False,
                                                    error=f"Live discovery unavailable ({type(exc).__name__}); retained catalog results"))
        return result
