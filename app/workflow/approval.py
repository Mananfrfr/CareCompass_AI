"""Approval payloads: the user approves an exact, hashed version of the shortlist."""

from __future__ import annotations

import hashlib
import json

from app.schemas.actions import ShortlistItem, ShortlistPayload
from app.schemas.hospital import RankedCandidate
from app.schemas.input import CareRequest


def build_payload(case_id: str, version: int, req: CareRequest, data_mode: str,
                  candidates: list[RankedCandidate], selected_hospital_id: str | None) -> ShortlistPayload:
    items = []
    for rank, c in enumerate(candidates, start=1):
        items.append(ShortlistItem(
            rank=rank, hospital_id=c.hospital.hospital_id, name=c.hospital.name, city=c.hospital.city,
            address=c.hospital.address, specialty_signal=c.specialty_signal,
            insurance_states=[s.value for s in c.insurance_states], evidence_confidence=c.evidence_confidence,
            suitability_score=c.suitability_score, evidence_ids=[e.evidence_id for e in c.evidence],
            source_urls=sorted({e.source_url for e in c.evidence}), synthetic=c.hospital.synthetic,
            match_kind=c.match_kind, phone=c.hospital.phone, map_url=c.hospital.map_url,
        ))
    return ShortlistPayload(case_id=case_id, version=version, specialty=req.care_specialty or "", city=req.city or "",
                            insurer=req.insurance_provider, plan=req.insurance_plan, data_mode=data_mode,
                            selected_hospital_id=selected_hospital_id, items=items)


def canonical_json(payload: ShortlistPayload) -> str:
    return json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def payload_hash(payload: ShortlistPayload) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def idempotency_key(case_id: str, action: str, p_hash: str) -> str:
    return hashlib.sha256(f"{case_id}|{action}|{p_hash}".encode()).hexdigest()
