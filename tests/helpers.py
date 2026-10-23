"""Builders for hand-made research results used across tests."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.evidence import ClaimType, Evidence, Reliability, SourceStatus, SourceType
from app.schemas.hospital import HospitalRecord, HospitalResearchResult
from app.schemas.input import CareRequest
from app.schemas.insurance import InsurerResearchResult, NetworkObservation

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def hospital(hid: str, name: str, city: str = "Jaipur", postcode: str | None = "302017",
             specialties: tuple[str, ...] = ("orthopaedics",), source_type: SourceType = SourceType.SYNTHETIC_FIXTURE):
    rec = HospitalRecord(hospital_id=hid, name=name, city=city, postcode=postcode, address=f"1 Road, {city}",
                         synthetic=True)
    common = dict(subject=name, subject_id=hid, source_name="test profile", source_url=f"fixture://h/{hid}",
                  source_type=source_type, retrieved_at=NOW, reliability=Reliability.HIGH)
    ev = [Evidence(claim_type=ClaimType.HOSPITAL_EXISTS, claim_value=name, **common),
          Evidence(claim_type=ClaimType.LOCATION, claim_value=city, **common)]
    ev += [Evidence(claim_type=ClaimType.SPECIALTY, claim_value=s, excerpt=f"{s} dept", **common) for s in specialties]
    return rec, ev


def hospital_result(*items) -> HospitalResearchResult:
    res = HospitalResearchResult(task_id="t1", source_status=[SourceStatus(source_name="test", ok=True)])
    for rec, ev in items:
        res.hospitals.append(rec)
        res.evidence.extend(ev)
    return res


def observation(name: str, in_network: bool, source: str = "Directory A", city: str = "Jaipur",
                postcode: str | None = "302017", cashless: bool | None = True, insurer: str = "Demo Shield Insurance"):
    ev = Evidence(claim_type=ClaimType.NETWORK_LISTING if in_network else ClaimType.NETWORK_ABSENCE,
                  claim_value="in_network" if in_network else "not_in_network", subject=name, source_name=source,
                  source_url=f"fixture://ins/{source.replace(' ', '-')}", source_type=SourceType.SYNTHETIC_FIXTURE,
                  retrieved_at=NOW, insurer=insurer, city=city)
    return NetworkObservation(listed_name=name, city=city, postcode=postcode, in_network=in_network, cashless=cashless, evidence=ev)


def insurer_result(*obs, ok: bool = True, complete: bool = True, insurer: str = "Demo Shield Insurance") -> InsurerResearchResult:
    status = [SourceStatus(source_name="Directory A", ok=ok, complete_for_city=complete, error=None if ok else "HTTP 503")]
    return InsurerResearchResult(task_id="t2", insurer=insurer, insurer_recognized=True, observations=list(obs),
                                 source_status=status)


def request(**kw) -> CareRequest:
    base = dict(case_id="case_test", care_specialty="orthopaedics", city="Jaipur", insurance_provider="Demo Shield Insurance",
                reported_condition="ACL tear", related_procedure="ACL reconstruction")
    base.update(kw)
    return CareRequest(**base)
