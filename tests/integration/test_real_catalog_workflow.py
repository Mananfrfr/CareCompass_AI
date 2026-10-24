import json
from dataclasses import replace

from app.research.hospital_catalog import CatalogHospitalSource
from app.research.insurer_sources import OfficialNetworkFileSource
from app.research.service import InProcessResearchClient
from app.workflow.orchestrator import CareCompassWorkflow


async def test_real_catalog_shortlist_approval_and_readback(repo, settings):
    workflow = CareCompassWorkflow(repo, replace(settings, data_mode="live"))
    research = InProcessResearchClient(CatalogHospitalSource(), OfficialNetworkFileSource())
    replies = await workflow.handle("catalog-user", "dialysis in Nagpur, no insurance", research)
    assert replies[0].card is not None
    case = repo.latest_case("catalog-user")
    result = json.loads(case.results_json)
    assert result[0]["hospital"]["hospital_id"] == "aiims-nagpur"
    assert result[0]["contextual_tier"] == "C"
    assert not result[0]["hospital"]["synthetic"]
    await workflow.handle("catalog-user", "approve", research)
    saved = repo.shortlists(case.case_id)
    assert len(saved) == 1
    assert json.loads(saved[0].payload_json)["data_mode"] == "live"
    await workflow.handle("catalog-user", "approve", research)
    assert len(repo.shortlists(case.case_id)) == 1
