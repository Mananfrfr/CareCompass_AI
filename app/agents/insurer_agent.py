"""Insurer Research Agent (uAgent).

Receives InsurerResearchRequest from the Coordinator and returns structured network-listing
observations and plan findings, each tied to its source. Never infers coverage.
Run: python -m app.agents.insurer_agent
"""

from __future__ import annotations

import asyncio

from uagents import Agent, Context

from app.agents.common import CompositeResolver, address_from_seed, configure_logging, local_routes, require_seed
from app.agents.protocols import InsurerResearchRequest, InsurerResearchResponse, insurer_research_protocol
from app.config import get_settings
from app.research.service import build_sources
from app.schemas.insurance import InsurerResearchQuery

settings = get_settings()
_, insurer_source = build_sources(settings)
protocol = insurer_research_protocol()
COORDINATOR = address_from_seed(settings.coordinator_seed) if settings.coordinator_seed else None
TIMEOUT_S = max(settings.research_timeout_s - 5, 10)


@protocol.on_message(InsurerResearchRequest, replies={InsurerResearchResponse})
async def on_request(ctx: Context, sender: str, req: InsurerResearchRequest) -> None:
    if COORDINATOR and sender != COORDINATOR:
        ctx.logger.warning("rejected request from unknown sender %s", sender[:20])
        await ctx.send(sender, InsurerResearchResponse(task_id=req.task_id, ok=False, error="unauthorized sender"))
        return
    ctx.logger.info("insurer research task=%s insurer=%s city=%s", req.task_id, req.insurer, req.city)
    query = InsurerResearchQuery(case_id=req.case_id, task_id=req.task_id, insurer=req.insurer, plan=req.plan,
                                 city=req.city, procedure=req.procedure, specialty=req.specialty)
    try:
        result = await asyncio.wait_for(insurer_source.research(query), TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        ctx.logger.error("insurer research failed task=%s: %s", req.task_id, type(exc).__name__)
        await ctx.send(sender, InsurerResearchResponse(task_id=req.task_id, ok=False, error=f"{type(exc).__name__}: {exc}"[:300]))
        return
    await ctx.send(sender, InsurerResearchResponse(
        task_id=req.task_id, ok=True, observation_count=len(result.observations), data_mode=result.data_mode,
        result_json=result.model_dump_json()))


def build_agent() -> Agent:
    seed = require_seed(settings.insurer_agent_seed, "INSURER_AGENT_SEED")
    agent = Agent(
        name="carecompass-insurer-research",
        seed=seed,
        port=settings.insurer_agent_port,
        endpoint=[f"http://127.0.0.1:{settings.insurer_agent_port}/submit"],
        resolve=CompositeResolver(local_routes(settings)),
        description="CareCompass insurer research agent: checks insurer hospital-network listings and plan "
                    "documents and returns source-linked evidence with explicit uncertainty states.",
        publish_agent_details=False,
    )
    agent.include(protocol, publish_manifest=True)

    @agent.on_event("startup")
    async def _startup(ctx: Context) -> None:
        ctx.logger.info("Insurer agent address: %s (data mode: %s)", agent.address, settings.data_mode)

    return agent


if __name__ == "__main__":
    configure_logging()
    build_agent().run()
