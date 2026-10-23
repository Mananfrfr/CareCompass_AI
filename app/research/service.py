"""Research services executed *inside* the Hospital and Insurer agents, plus the client
interface the coordinator uses to reach them.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from app.config import Settings
from app.research.hospital_sources import HospitalSource, build_hospital_source
from app.research.insurer_sources import InsurerSource, build_insurer_source
from app.research.source_fetcher import SafeFetcher
from app.schemas.hospital import HospitalResearchQuery, HospitalResearchResult
from app.schemas.insurance import InsurerResearchQuery, InsurerResearchResult

R = TypeVar("R")


@dataclass
class ResearchOutcome(Generic[R]):
    result: R | None
    attempts: int
    latency_ms: int
    error: str | None = None
    agent: str = ""


class ResearchClient(Protocol):
    async def hospitals(self, query: HospitalResearchQuery) -> ResearchOutcome[HospitalResearchResult]: ...

    async def insurer(self, query: InsurerResearchQuery) -> ResearchOutcome[InsurerResearchResult]: ...


def build_sources(settings: Settings) -> tuple[HospitalSource, InsurerSource]:
    fetcher = None if settings.fixture_mode else SafeFetcher(settings.http_user_agent)
    return (build_hospital_source(settings.fixture_mode, fetcher, settings.live_max_candidates),
            build_insurer_source(settings.fixture_mode))


class InProcessResearchClient:
    """Calls the research sources directly (unit tests / offline CLI demo). The deployed system
    uses AgentResearchClient in app.agents.coordinator, which talks to the real research uAgents."""

    def __init__(self, hospital_source: HospitalSource, insurer_source: InsurerSource,
                 fail_hospital: bool = False, fail_insurer: bool = False, timeout_s: float = 30):
        self.hospital_source = hospital_source
        self.insurer_source = insurer_source
        self.fail_hospital = fail_hospital
        self.fail_insurer = fail_insurer
        self.timeout_s = timeout_s

    async def _run(self, agent: str, coro, fail: bool) -> ResearchOutcome:
        start = time.perf_counter()
        if fail:
            coro.close()
            return ResearchOutcome(None, 1, 0, f"{agent} unavailable (simulated)", agent)
        try:
            result = await asyncio.wait_for(coro, self.timeout_s)
            return ResearchOutcome(result, 1, int((time.perf_counter() - start) * 1000), None, agent)
        except Exception as exc:  # noqa: BLE001 - surfaced as a controlled research failure
            return ResearchOutcome(None, 1, int((time.perf_counter() - start) * 1000), f"{type(exc).__name__}: {exc}", agent)

    async def hospitals(self, query: HospitalResearchQuery) -> ResearchOutcome[HospitalResearchResult]:
        return await self._run("hospital-agent", self.hospital_source.search_hospitals(query), self.fail_hospital)

    async def insurer(self, query: InsurerResearchQuery) -> ResearchOutcome[InsurerResearchResult]:
        return await self._run("insurer-agent", self.insurer_source.research(query), self.fail_insurer)
