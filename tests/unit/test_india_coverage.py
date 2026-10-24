"""India-wide coverage: national hospital directory, live map discovery, real-insurer guidance."""
import json
from dataclasses import replace

import httpx
import pytest

from app.intelligence.care_knowledge import find_directory_city
from app.intelligence.intent_parser import rule_extract
from app.research import policy_intel
from app.research.hospital_catalog import FixtureFirstHospitalSource, merge_results
from app.research.hospital_sources import FixtureHospitalSource, OverpassHospitalSource
from app.research.india_directory import DirectoryHospitalSource, get_directory, specialties_from_text
from app.research.insurer_sources import FixtureInsurerSource, RealInsurerSource, RoutedInsurerSource
from app.research.service import InProcessResearchClient
from app.research.source_fetcher import SafeFetcher
from app.schemas.evidence import ClaimType, SourceType
from app.schemas.hospital import HospitalResearchQuery
from app.schemas.insurance import InsuranceState, InsurerResearchQuery
from app.workflow.orchestrator import CareCompassWorkflow


def q(city, specialty="orthopaedics", **kw):
    return HospitalResearchQuery(case_id="c", task_id="t", city=city, specialty=specialty, **kw)


def test_directory_covers_india_beyond_demo_cities():
    d = get_directory()
    assert len(d.records) > 25000
    for city in ("Mumbai", "Bengaluru", "Kolkata", "Hyderabad", "Pali", "Udaipur", "Gurugram"):
        assert d.known_city(city), city
    assert d.known_city("Bombay") == "Mumbai"


def test_declared_specialties_are_normalised():
    assert specialties_from_text("Orthopedics, ENT, Obstetrics and Gynaecology") == ["ent", "gynaecology", "orthopaedics"]
    assert specialties_from_text("0") == [] or specialties_from_text("") == []


async def test_mumbai_orthopaedics_returns_real_directory_leads():
    result = await DirectoryHospitalSource().search_hospitals(q("Mumbai"))
    assert len(result.hospitals) >= 8
    assert all(h.city == "Mumbai" for h in result.hospitals)
    spec = [e for e in result.evidence if e.claim_type == ClaimType.SPECIALTY]
    assert spec and all(e.source_type == SourceType.OFFICIAL_GOVERNMENT for e in spec)
    # A government directory listing is never treated as verification of a department.
    assert not any(e.is_authoritative for e in spec)
    ids = [h.hospital_id for h in result.hospitals]
    assert len(ids) == len(set(ids))


def test_small_towns_are_recognised_from_the_directory():
    assert find_directory_city("knee pain, I live in pali rajasthan") == "Pali"
    assert rule_extract("ACL tear in Bhilwara").city == "Bhilwara"


def test_explicit_plan_without_repeating_insurer():
    assert rule_extract("my plan is Star Comprehensive Insurance Policy").insurance_plan == "Star Comprehensive Insurance Policy"
    assert rule_extract("policy: Optima Secure, HDFC ERGO").insurance_plan == "Optima Secure"


async def test_fixture_mode_routes_non_demo_cities_to_real_directory():
    source = FixtureFirstHospitalSource(FixtureHospitalSource(), DirectoryHospitalSource())
    demo = await source.search_hospitals(q("Jaipur"))
    real = await source.search_hospitals(q("Mumbai"))
    assert demo.data_mode == "fixture" and all(h.synthetic for h in demo.hospitals)
    assert real.data_mode == "live" and real.hospitals and not any(h.synthetic for h in real.hospitals)


def overpass_transport():
    def handler(request: httpx.Request):
        assert request.url.host == "overpass-api.de"
        return httpx.Response(200, json={"elements": [
            {"type": "way", "id": 1, "center": {"lat": 19.10, "lon": 72.86},
             "tags": {"amenity": "hospital", "name": "Andheri Bone and Joint Hospital", "phone": "+91 22 0000 0000"}},
            {"type": "node", "id": 2, "lat": 19.11, "lon": 72.85,
             "tags": {"amenity": "clinic", "name": "City Clinic", "healthcare:speciality": "orthopaedics"}},
            {"type": "node", "id": 3, "lat": 19.12, "lon": 72.87, "tags": {"amenity": "hospital", "name": "General Care"}},
            {"type": "node", "id": 4, "lat": 19.12, "lon": 72.87, "tags": {"amenity": "hospital"}},
        ]})
    return httpx.MockTransport(handler)


async def test_overpass_map_discovery_parses_specialty_tags_and_coordinates():
    async def resolver(host):
        return ["93.184.216.34"]
    fetcher = SafeFetcher("test", transport=overpass_transport(), resolver=resolver)
    OverpassHospitalSource._cache.clear()
    OverpassHospitalSource._limiter.min_interval_s = 0
    source = OverpassHospitalSource(fetcher, centre_lookup=lambda city: (19.10, 72.86))
    result = await source.search_hospitals(q("Mumbai"))
    names = [h.name for h in result.hospitals]
    assert names[0] == "City Clinic"  # explicit specialty tag ranks first
    assert "Andheri Bone and Joint Hospital" in names and len(names) == 3  # unnamed element skipped
    first = result.hospitals[0]
    assert first.latitude and "google.com/maps" in first.map_url
    assert any(e.claim_type == ClaimType.SPECIALTY and e.source_type == SourceType.COMMUNITY_DIRECTORY
               for e in result.evidence)


async def test_overpass_failure_is_reported_not_fatal():
    async def resolver(host):
        return ["93.184.216.34"]
    fetcher = SafeFetcher("test", transport=httpx.MockTransport(lambda r: httpx.Response(504)), resolver=resolver,
                          max_attempts=1)
    OverpassHospitalSource._cache.clear()
    source = OverpassHospitalSource(fetcher, centre_lookup=lambda city: (19.0, 72.8))
    result = await source.search_hospitals(q("Mumbai"))
    assert not result.hospitals and not result.source_status[0].ok


async def test_duplicate_hospitals_across_sources_are_merged_conservatively():
    a = await DirectoryHospitalSource().search_hospitals(q("Mumbai"))
    first = a.hospitals[0]
    b = a.model_copy(deep=True)
    for h in b.hospitals:
        h.hospital_id = "osm-" + h.hospital_id
    for e in b.evidence:
        e.subject_id = "osm-" + (e.subject_id or "")
    before = len(a.hospitals)
    merge_results(a, b)
    assert len(a.hospitals) == before
    assert first.hospital_id in {h.hospital_id for h in a.hospitals}


def test_real_insurer_plan_matching_uses_irdai_register():
    record = policy_intel.match_plan("Star Health", "Star Comprehensive")
    assert record and record["uin"].startswith("SHAHLIP") and record["policy_wording_url"].startswith("https://irdai.gov.in")
    assert policy_intel.match_plan("Star Health", "imaginary platinum ultra") is None
    products = policy_intel.registered_products("Star Health")
    assert products and all("HLIP" in p["uin"] for p in products)


def test_policy_wording_scan_quotes_waiting_period_clause():
    text = ("Section 4. Exclusions. Code-Excl02 Specified disease/procedure waiting period: expenses related to the "
            "treatment of the listed conditions, surgeries/treatments shall be excluded until the expiry of 24 months "
            "of continuous coverage. List: Cataract; Joint replacement surgery; Ligament tear repair; Hernia.")
    found = policy_intel.scan_wording(text, "ACL reconstruction", policy_intel.procedure_terms("ACL reconstruction"))
    assert found and found[0][0] == InsuranceState.WAITING_PERIOD_APPLIES
    assert "Ligament" in found[0][1] or "Joint replacement" in found[0][1]
    assert not policy_intel.scan_wording("Room rent is covered.", "cataract surgery", ("cataract",))


async def test_real_insurer_gets_official_guidance_never_a_network_verdict():
    source = RoutedInsurerSource(FixtureInsurerSource(), RealInsurerSource())
    real = await source.research(InsurerResearchQuery(case_id="c", task_id="t", insurer="Star Health", city="Mumbai",
                                                      plan="Star Comprehensive", procedure="ACL reconstruction"))
    assert real.insurer_recognized and not real.any_source_ok and not real.observations
    assert real.official_links[0]["url"] == "https://www.starhealth.in"
    assert real.matched_plan and real.matched_plan["uin"].startswith("SHAHLIP")
    demo = await source.research(InsurerResearchQuery(case_id="c", task_id="t", insurer="Demo Shield Insurance",
                                                      city="Jaipur"))
    assert demo.data_mode == "fixture" and demo.observations


@pytest.fixture
def india_research():
    return InProcessResearchClient(FixtureFirstHospitalSource(FixtureHospitalSource(), DirectoryHospitalSource()),
                                   RoutedInsurerSource(FixtureInsurerSource(), RealInsurerSource()))


async def test_mumbai_acl_star_health_is_no_longer_empty(workflow, india_research):
    replies = await workflow.handle("s1", "I have an ACL tear, I'm in Mumbai and have Star Health insurance",
                                    india_research)
    text = replies[-1].text
    assert "couldn't find" not in text
    assert "Hospitals to call" in text and "starhealth.in" in text
    assert "synthetic (fictional)" not in text  # real hospitals are never labelled as demo data
    case = workflow.repo.latest_case("s1")
    results = workflow._results(case)
    assert results and all(c.match_kind == "lead" and c.contextual_tier is None for c in results)
    assert all(c.evidence_confidence != "high" for c in results)
    assert case.data_mode == "live"
    saved = await workflow.handle("s1", "approve", india_research)
    assert "Saved and verified" in saved[-1].text and "call to confirm" in saved[-1].text


async def test_empty_shortlist_does_not_swallow_next_message(workflow, india_research):
    await workflow.handle("s2", "ACL tear in Atlantisville", india_research)
    replies = await workflow.handle("s2", "yes, search in Mumbai instead", india_research)
    assert "Nothing was saved" not in replies[-1].text
    assert "Mumbai" in replies[-1].text


async def test_demo_city_still_uses_verified_synthetic_flow(workflow, india_research):
    replies = await workflow.handle("s3", "ACL tear in Jaipur, Demo Shield Insurance", india_research)
    assert "synthetic" in replies[-1].text.lower()
    assert any(c.match_kind == "verified" for c in workflow._results(workflow.repo.latest_case("s3")))
