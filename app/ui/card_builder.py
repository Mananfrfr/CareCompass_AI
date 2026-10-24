"""ASI:One Interactive Card payloads (card protocol version "1").

Schemas follow https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards :
metadata values are strings, card_payload is JSON-stringified at the top level, <= 64 KB.
If ASI:One rejects a card it falls back to the TextContent, so every card is always sent
alongside a complete text version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.intelligence.care_knowledge import SPECIALTIES
from app.schemas.actions import ShortlistPayload
from app.schemas.evidence import ClaimType
from app.schemas.hospital import RankedCandidate
from app.schemas.input import CareRequest
from app.schemas.insurance import STATE_TEXT, InsuranceState

MAX_PAYLOAD_BYTES = 64 * 1024
CARD_KINDS = {"carousel", "detail", "form", "review", "custom"}


@dataclass
class Card:
    kind: str
    payload: dict

    def metadata(self) -> dict[str, str]:
        if self.kind not in CARD_KINDS:
            raise ValueError(f"unknown card kind {self.kind}")
        body = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))
        if len(body.encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("card payload exceeds 64 KB")
        return {
            "card_protocol_version": "1",
            "requires_card_interaction": "true",
            "card_kind": self.kind,
            "card_payload": body,
            "preferred_drawer_width_px": "560",
        }


def specialty_label(key: str | None) -> str:
    return SPECIALTIES[key].label if key in SPECIALTIES else (key or "relevant care").replace("_", " ")


def network_badge(states: list[InsuranceState]) -> dict:
    if InsuranceState.NOT_CHECKED in states:
        return {"label": "Insurance not checked", "variant": "info"}
    if InsuranceState.SOURCES_CONFLICT in states:
        return {"label": "Sources conflict", "variant": "warning"}
    if InsuranceState.NETWORK_VERIFIED in states:
        return {"label": "Network listed", "variant": "success"}
    if InsuranceState.SOURCE_UNAVAILABLE in states:
        return {"label": "Insurer source unavailable", "variant": "warning"}
    if InsuranceState.NETWORK_NOT_FOUND in states:
        return {"label": "Not in network list", "variant": "warning"}
    return {"label": "Network uncertain", "variant": "warning"}


def _specialty_text(c: RankedCandidate, req: CareRequest) -> str:
    label = specialty_label(req.care_specialty)
    return {"verified": f"{label}: advertised by hospital",
            "directory": f"{label}: listed in public directory (unconfirmed)",
            "weak": f"{label}: suggested by name only (unverified)",
            "none": f"{label}: no evidence found"}[c.specialty_signal]


def shortlist_card(case_id: str, version: int, req: CareRequest, candidates: list[RankedCandidate],
                   data_mode: str) -> Card:
    items = []
    for i, c in enumerate(candidates, start=1):
        badges = [network_badge(c.insurance_states),
                  {"label": f"Evidence: {c.evidence_confidence}", "variant": "success" if c.evidence_confidence == "high" else "info"}]
        if c.hospital.synthetic:
            badges.append({"label": "Synthetic demo data", "variant": "warning"})
        if InsuranceState.PROCEDURE_EXCLUDED in c.insurance_states:
            badges.append({"label": "Procedure excluded by plan", "variant": "warning"})
        items.append({
            "id": c.hospital.hospital_id,
            "title": f"{i}. {c.hospital.name}",
            "subtitle": f"{c.hospital.city} · {_specialty_text(c, req)}",
            "badges": badges,
            "secondary_text": f"CareCompass tier {c.contextual_tier or 'unrated'} · Suitability {c.suitability_score:.0f}/100 · verified {c.last_verified or 'n/a'}",
            "primary_cta": {"label": "View evidence",
                            "selection": {"action": "select_hospital", "hospital_id": c.hospital.hospital_id,
                                          "case_id": case_id, "version": version}},
        })
    insurer = req.insurance_provider or "no insurer"
    subtitle = f"{req.city} · {insurer}" + (" · SYNTHETIC DEMO DATA" if data_mode == "fixture" else " · live public data")
    return Card("carousel", {"title": f"{specialty_label(req.care_specialty)} options", "subtitle": subtitle, "items": items})


def detail_card(case_id: str, version: int, c: RankedCandidate, req: CareRequest) -> Card:
    rows = [
        {"label": "Location", "value": f"{c.hospital.address or c.hospital.city}"},
        {"label": "Service", "value": _specialty_text(c, req)},
        {"label": "Insurance", "value": "; ".join(STATE_TEXT[s] for s in c.insurance_states) or "Not checked"},
        {"label": "Evidence confidence", "value": c.evidence_confidence},
        {"label": "Suitability", "value": f"{c.suitability_score:.0f}/100 ({', '.join(f'{k} {v:.2f}' for k, v in c.score_breakdown.items())})"},
        {"label": "Why ranked", "value": c.explanation},
    ]
    for conflict in c.conflicts:
        rows.append({"label": "Conflict", "value": conflict})
    for missing in c.missing_evidence[:3]:
        rows.append({"label": "Missing evidence", "value": missing})
    for e in _key_evidence(c)[:5]:
        rows.append({"label": f"Source ({e.claim_type.value.replace('_', ' ')})",
                     "value": f"{e.source_name}: {e.source_url} (retrieved {e.retrieved_at.date().isoformat()})"})
    if c.hospital.synthetic:
        rows.append({"label": "Data notice", "value": "Synthetic demo record - not a real hospital"})
    return Card("detail", {
        "title": c.hospital.name,
        "summary_rows": rows,
        "ctas": [
            {"label": "Save shortlist with this choice", "primary": True,
             "selection": {"action": "review", "hospital_id": c.hospital.hospital_id, "case_id": case_id, "version": version}},
            {"label": "Back to shortlist", "selection": {"action": "back", "case_id": case_id}},
        ],
    })


def _key_evidence(c: RankedCandidate):
    priority = {ClaimType.SPECIALTY: 0, ClaimType.NETWORK_LISTING: 1, ClaimType.NETWORK_ABSENCE: 1,
                ClaimType.POLICY_EXCLUSION: 2, ClaimType.POLICY_WAITING_PERIOD: 2, ClaimType.HOSPITAL_EXISTS: 3}
    return sorted(c.evidence, key=lambda e: priority.get(e.claim_type, 9))


def review_card(payload: ShortlistPayload, selected_name: str | None) -> Card:
    rows = [
        {"label": "Action", "value": "Save this shortlist and its evidence to your CareCompass record"},
        {"label": "Hospitals", "value": "; ".join(f"{i.rank}. {i.name}" for i in payload.items)},
        {"label": "Your choice", "value": selected_name or "No single choice (whole shortlist)"},
        {"label": "Search", "value": f"{specialty_label(payload.specialty)} in {payload.city}"},
        {"label": "Insurance", "value": f"{payload.insurer or 'not provided'}{' / ' + payload.plan if payload.plan else ''}"},
        {"label": "Data", "value": "Synthetic demo data" if payload.data_mode == "fixture" else "Live public sources"},
        {"label": "Not included", "value": "No medical report text is stored or shared with anyone"},
    ]
    return Card("review", {
        "title": "Approve saving this shortlist?",
        "summary_rows": rows,
        "approve_cta": {"label": "Approve & save", "primary": True,
                        "selection": {"action": "approve", "case_id": payload.case_id, "version": payload.version}},
        "reject_cta": {"label": "Revise or cancel", "selection": {"action": "cancel", "case_id": payload.case_id}},
    })
