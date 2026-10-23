"""Live data: real OpenStreetMap/Nominatim calls. Run explicitly with: pytest -m live"""

from __future__ import annotations

import pytest

from app.research.hospital_sources import OSMHospitalSource
from app.research.source_fetcher import SafeFetcher
from app.schemas.evidence import ClaimType
from app.schemas.hospital import HospitalResearchQuery

UA = "CareCompassAI/0.1 (hackathon test; https://github.com/)"


@pytest.mark.live
async def test_live_osm_hospitals_jaipur_orthopaedics():
    source = OSMHospitalSource(SafeFetcher(UA), verify_websites=True)
    result = await source.search_hospitals(HospitalResearchQuery(case_id="live", task_id="live-1", city="Jaipur",
                                                                 specialty="orthopaedics"))
    assert any(s.ok for s in result.source_status), result.source_status
    assert result.hospitals, "OSM returned no hospitals"
    ids = {h.hospital_id for h in result.hospitals}
    for e in result.evidence:
        assert e.subject_id in ids and e.source_url.startswith("https://") and not e.synthetic
    assert any(e.claim_type == ClaimType.HOSPITAL_EXISTS for e in result.evidence)
