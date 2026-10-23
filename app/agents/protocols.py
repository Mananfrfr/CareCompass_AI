"""Typed uAgent messages between the Coordinator and the research agents.

Envelope fields are typed uagents Models; the detailed result is a JSON document validated
against the Pydantic schemas in app.schemas on BOTH sides (sender serialises from the schema,
receiver re-validates), so a malformed reply is rejected rather than trusted.
"""

from __future__ import annotations

from typing import Optional

from uagents import Model, Protocol


class HospitalResearchRequest(Model):
    case_id: str
    task_id: str
    city: str
    specialty: str
    procedure: Optional[str] = None
    allow_nearby: bool = False
    max_results: int = 8


class HospitalResearchResponse(Model):
    task_id: str
    ok: bool
    error: Optional[str] = None
    hospital_count: int = 0
    data_mode: str = "fixture"
    result_json: str = ""


class InsurerResearchRequest(Model):
    case_id: str
    task_id: str
    insurer: str
    city: str
    plan: Optional[str] = None
    procedure: Optional[str] = None
    specialty: Optional[str] = None


class InsurerResearchResponse(Model):
    task_id: str
    ok: bool
    error: Optional[str] = None
    observation_count: int = 0
    data_mode: str = "fixture"
    result_json: str = ""


PROTOCOL_VERSION = "0.1.0"


def hospital_research_protocol() -> Protocol:
    return Protocol(name="CareCompassHospitalResearch", version=PROTOCOL_VERSION)


def insurer_research_protocol() -> Protocol:
    return Protocol(name="CareCompassInsurerResearch", version=PROTOCOL_VERSION)
