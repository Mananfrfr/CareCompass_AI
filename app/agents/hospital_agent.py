"""Hospital Verification Agent (uAgent).

Receives HospitalResearchRequest from the Coordinator, independently researches hospitals
(synthetic fixtures or live OpenStreetMap + official websites) and replies with structured,
source-linked evidence. Run: python -m app.agents.hospital_agent
"""

from __future__ import annotations

import asyncio

from uagents import Agent, Context

from app.agents.common import CompositeResolver, harden_outbound_sends, address_from_seed, configure_logging, local_routes, require_seed
from app.agents.protocols import HospitalResearchRequest, HospitalResearchResponse, hospital_research_protocol
from app.config import get_settings
from app.research.service import build_sources
from app.schemas.hospital import HospitalResearchQuery

settings = get_settings()
harden_outbound_sends()
hospital_source, _ = build_sources(settings)
protocol = hospital_research_protocol()
COORDINATOR = address_from_seed(settings.coordinator_seed) if settings.coordinator_seed else None
TIMEOUT_S = max(settings.research_timeout_s - 5, 10)


@protocol.on_message(HospitalResearchRequest, replies={HospitalResearchResponse})
async def on_request(ctx: Context, sender: str, req: HospitalResearchRequest) -> None:
    if COORDINATOR and sender != COORDINATOR:
        ctx.logger.warning("rejected request from unknown sender %s", sender[:20])
        await ctx.send(sender, HospitalResearchResponse(task_id=req.task_id, ok=False, error="unauthorized sender"))
        return
    ctx.logger.info("hospital research task=%s city=%s specialty=%s", req.task_id, req.city, req.specialty)
    query = HospitalResearchQuery(case_id=req.case_id, task_id=req.task_id, city=req.city, specialty=req.specialty,
                                  procedure=req.procedure, allow_nearby=req.allow_nearby, max_results=req.max_results)
    try:
        result = await asyncio.wait_for(hospital_source.search_hospitals(query), TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a structured error reply
        ctx.logger.error("research failed task=%s: %s", req.task_id, type(exc).__name__)
        await ctx.send(sender, HospitalResearchResponse(task_id=req.task_id, ok=False, error=f"{type(exc).__name__}: {exc}"[:300]))
        return
    await ctx.send(sender, HospitalResearchResponse(
        task_id=req.task_id, ok=True, hospital_count=len(result.hospitals), data_mode=result.data_mode,
        result_json=result.model_dump_json()))


def build_agent() -> Agent:
    seed = require_seed(settings.hospital_agent_seed, "HOSPITAL_AGENT_SEED")
    agent = Agent(
        name="carecompass-hospital-verifier",
        seed=seed,
        port=settings.hospital_agent_port,
        endpoint=[f"http://127.0.0.1:{settings.hospital_agent_port}/submit"],
        resolve=CompositeResolver(local_routes(settings)),
        description="CareCompass hospital verification agent: finds hospitals in a city and collects "
                    "source-linked evidence of location and advertised specialties.",
        publish_agent_details=False,
    )
    agent.include(protocol, publish_manifest=True)

    @agent.on_event("startup")
    async def _startup(ctx: Context) -> None:
        ctx.logger.info("Hospital agent address: %s (data mode: %s)", agent.address, settings.data_mode)

    return agent


if __name__ == "__main__":
    configure_logging()
    build_agent().run()
