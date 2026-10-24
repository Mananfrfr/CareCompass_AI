import json
from datetime import datetime, timedelta, timezone

import pytest

from app.research.insurer_sources import OfficialNetworkFileSource
from app.schemas.insurance import InsurerResearchQuery


async def test_completed_case_rejects_stale_or_changed_approval(workflow, research):
    await workflow.handle("owner", "ACL tear in Jaipur", research)
    await workflow.handle("owner", "approve", research)
    case = workflow.repo.latest_case("owner")
    original = workflow.repo.shortlists(case.case_id)[0].confirmation_id
    for data in [
        {"case_id": "case_other"}, {"version": case.shortlist_version + 1},
        {"hospital_id": "syn-jpr-aravali"},
    ]:
        replies = await workflow.handle("owner", json.dumps({"action": "approve", **data}), research)
        assert "Saved and verified" not in replies[0].text
        assert len(workflow.repo.shortlists(case.case_id)) == 1
    replies = await workflow.handle("owner", "approve", research)
    assert original in replies[0].text


async def test_care_brief_uses_saved_sources_and_is_private(workflow, research):
    await workflow.handle("owner", "ACL tear in Jaipur with Demo Shield insurance", research)
    await workflow.handle("owner", "approve", research)
    case = workflow.repo.latest_case("owner")
    reference = workflow.repo.shortlists(case.case_id)[0].confirmation_id
    reply = (await workflow.handle("owner", "care brief", research))[0].text
    assert reference in reply and "SYNTHETIC DEMO" in reply and "fixture://" in reply
    assert "Questions for the insurer" in reply
    other = (await workflow.handle("other", f"care brief {reference}", research))[0].text
    assert "couldn't find" in other
    assert len(workflow.repo.shortlists(case.case_id)) == 1


@pytest.mark.parametrize("date", ["", "invalid", "2000-01-01", "2099-01-01"])
async def test_import_rejects_unverified_dates(tmp_path, date):
    (tmp_path / "network.csv").write_text(
        f"# insurer: Example\n# source_url: https://example.com/network\n# retrieved_at: {date}\n"
        "# complete_for_cities: Jaipur\nname,city,address,postcode,cashless\nHospital,Jaipur,Road,302001,yes\n")
    result = await OfficialNetworkFileSource(tmp_path).research(
        InsurerResearchQuery(case_id="case", task_id="task", city="Jaipur", insurer="Example"))
    assert not result.any_source_ok and not result.observations


async def test_import_preserves_valid_retrieval_date(tmp_path):
    date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    (tmp_path / "network.csv").write_text(
        f"# insurer: Example\n# source_url: https://example.com/network\n# retrieved_at: {date}\n"
        "name,city,address,postcode,cashless\nHospital,Jaipur,Road,302001,yes\n")
    result = await OfficialNetworkFileSource(tmp_path).research(
        InsurerResearchQuery(case_id="case", task_id="task", city="Jaipur", insurer="Example"))
    assert result.any_source_ok and len(result.observations) == 1
    assert result.observations[0].evidence.retrieved_at == datetime.fromisoformat(date)
