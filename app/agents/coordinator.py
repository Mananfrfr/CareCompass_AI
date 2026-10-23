"""CareCompass Coordinator - the public ASI:One-facing agent.

Implements the Agent Chat Protocol (AgentChatProtocol 0.3.0 via uagents_core.contrib.protocols.chat):
acknowledges every ChatMessage, reads TextContent / ResourceContent / StartSessionContent, runs the
CareCompass workflow and replies with text plus an Interactive Card (MetadataContent) where useful.
Research is delegated over typed uAgent messages to the Hospital and Insurer agents.

Run: python -m app.agents.coordinator   (mailbox mode connects it to Agentverse / ASI:One)
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    ResourceContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from app.agents.common import CompositeResolver, address_from_seed, configure_logging, local_routes, require_seed
from app.agents.protocols import (
    HospitalResearchRequest,
    HospitalResearchResponse,
    InsurerResearchRequest,
    InsurerResearchResponse,
)
from app.config import ROOT_DIR, get_settings
from app.database.repository import Repository
from app.database.session import make_session_factory
from app.intelligence.asi1_client import ASI1Client
from app.intelligence.attachments import attachment_fetcher, read_attachment
from app.research.service import ResearchOutcome
from app.schemas.hospital import HospitalResearchQuery, HospitalResearchResult
from app.schemas.insurance import InsurerResearchQuery, InsurerResearchResult
from app.security.privacy import session_key, summarize_for_log
from app.workflow.orchestrator import WELCOME, CareCompassWorkflow, Reply

settings = get_settings()
repo = Repository(make_session_factory(settings.database_url))
workflow = CareCompassWorkflow(repo, settings, ASI1Client(settings))
fetcher = attachment_fetcher(settings.http_user_agent)
chat_proto = Protocol(spec=chat_protocol_spec)
_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

HOSPITAL_AGENT = address_from_seed(settings.hospital_agent_seed) if settings.hospital_agent_seed else ""
INSURER_AGENT = address_from_seed(settings.insurer_agent_seed) if settings.insurer_agent_seed else ""


class AgentResearchClient:
    """Delegates research to the specialist uAgents with bounded retries and timeouts."""

    def __init__(self, ctx: Context, hospital_address: str, insurer_address: str, timeout_s: int, max_attempts: int):
        self.ctx = ctx
        self.hospital_address = hospital_address
        self.insurer_address = insurer_address
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    async def _call(self, agent: str, address: str, request, response_type, result_type) -> ResearchOutcome:
        start = time.perf_counter()
        error = "not attempted"
        attempt = 0
        if not address:
            return ResearchOutcome(None, 0, 0, f"{agent} address not configured", agent)
        for attempt in range(1, self.max_attempts + 1):
            reply, status = await self.ctx.send_and_receive(address, request, response_type=response_type,
                                                            timeout=self.timeout_s)
            if isinstance(reply, response_type):
                if reply.ok and reply.task_id == request.task_id:
                    try:
                        result = result_type.model_validate_json(reply.result_json)
                        return ResearchOutcome(result, attempt, int((time.perf_counter() - start) * 1000), None, agent)
                    except ValueError as exc:
                        error = f"invalid reply payload: {str(exc)[:120]}"
                else:
                    error = reply.error or "task id mismatch"
            else:
                error = f"no reply within {self.timeout_s}s ({getattr(status, 'detail', status)})"
            self.ctx.logger.warning("%s attempt %s failed: %s", agent, attempt, error)
            if attempt < self.max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
        return ResearchOutcome(None, attempt, int((time.perf_counter() - start) * 1000), error, agent)

    async def hospitals(self, q: HospitalResearchQuery) -> ResearchOutcome[HospitalResearchResult]:
        req = HospitalResearchRequest(case_id=q.case_id, task_id=q.task_id, city=q.city, specialty=q.specialty,
                                      procedure=q.procedure, allow_nearby=q.allow_nearby, max_results=q.max_results)
        return await self._call("hospital-agent", self.hospital_address, req, HospitalResearchResponse,
                                HospitalResearchResult)

    async def insurer(self, q: InsurerResearchQuery) -> ResearchOutcome[InsurerResearchResult]:
        req = InsurerResearchRequest(case_id=q.case_id, task_id=q.task_id, insurer=q.insurer, city=q.city, plan=q.plan,
                                     procedure=q.procedure, specialty=q.specialty)
        return await self._call("insurer-agent", self.insurer_address, req, InsurerResearchResponse,
                                InsurerResearchResult)


def to_chat_message(reply: Reply) -> ChatMessage:
    content: list = [TextContent(type="text", text=reply.text)]
    if reply.card is not None:
        try:
            content.append(MetadataContent(type="metadata", metadata=reply.card.metadata()))
        except ValueError:
            pass  # oversized/invalid card: the text version is complete on its own
    if reply.end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def _resource_urls(item: ResourceContent) -> list[tuple[str, str]]:
    resources = item.resource if isinstance(item.resource, list) else [item.resource]
    out = []
    for res in resources:
        meta = getattr(res, "metadata", None) or {}
        url = getattr(res, "uri", None)
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
            url = next((meta.get(k) for k in ("url", "uri", "source") if str(meta.get(k, "")).startswith("http")), None)
        if url:
            out.append((url, meta.get("mime_type", "")))
    return out


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    texts: list[str] = []
    report_text: str | None = None
    notices: list[str] = []
    started = False
    for item in msg.content:
        if isinstance(item, StartSessionContent):
            started = True
            await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                               content=[MetadataContent(type="metadata", metadata={"attachments": "true"})]))
        elif isinstance(item, TextContent):
            texts.append(item.text)
        elif isinstance(item, ResourceContent):
            for url, mime in _resource_urls(item)[:2]:
                result = await read_attachment(url, mime, fetcher)
                if result.text:
                    report_text = (report_text + "\n" if report_text else "") + result.text
                elif result.message:
                    notices.append(result.message)
        elif isinstance(item, EndSessionContent):
            ctx.logger.info("session ended by %s", sender[:16])
    text = "\n".join(t for t in texts if t).strip()
    ctx.logger.info("chat from %s: %s report=%s", sender[:16], summarize_for_log(text), bool(report_text))
    if not text and not report_text and not notices:
        if started:
            await ctx.send(sender, to_chat_message(Reply(WELCOME)))
        return

    research = AgentResearchClient(ctx, HOSPITAL_AGENT, INSURER_AGENT, settings.research_timeout_s,
                                   settings.research_max_attempts)
    key = session_key(sender)
    async with _session_locks[key]:
        try:
            replies = await workflow.handle(key, text, research, msg_id=str(msg.msg_id), report_text=report_text,
                                            notices=notices)
        except Exception as exc:  # noqa: BLE001 - never leave the user without an answer
            ctx.logger.exception("workflow error: %s", type(exc).__name__)
            replies = [Reply("Sorry - something went wrong on my side and nothing was saved. Please try again, "
                             "or say **new search**.")]
    for reply in replies:
        await ctx.send(sender, to_chat_message(reply))


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.debug("ack from %s for %s", sender[:16], msg.acknowledged_msg_id)


def build_agent() -> Agent:
    seed = require_seed(settings.coordinator_seed, "COORDINATOR_SEED")
    kwargs: dict = {}
    if settings.coordinator_connectivity == "mailbox":
        kwargs["mailbox"] = True
    else:
        kwargs["endpoint"] = [f"http://127.0.0.1:{settings.coordinator_port}/submit"]
    agent = Agent(
        name="CareCompass AI",
        seed=seed,
        port=settings.coordinator_port,
        resolve=CompositeResolver(local_routes(settings)),
        readme_path=str(Path(ROOT_DIR / "docs" / "AGENT_PROFILE.md")),
        description=("Healthcare navigation for India: turns a health concern, known condition or medical report into "
                     "an evidence-backed hospital shortlist with insurer network checks, then saves it on your approval. "
                     "Does not diagnose or guarantee coverage."),
        publish_agent_details=True,
        **kwargs,
    )
    agent.include(chat_proto, publish_manifest=True)

    @agent.on_event("startup")
    async def _startup(ctx: Context) -> None:
        ctx.logger.info("CareCompass coordinator address: %s", agent.address)
        ctx.logger.info("hospital agent: %s | insurer agent: %s | data mode: %s | ASI1: %s",
                        HOSPITAL_AGENT[:20], INSURER_AGENT[:20], settings.data_mode,
                        "configured" if settings.asi1_api_key else "NOT configured (rules-only)")

    return agent


if __name__ == "__main__":
    configure_logging()
    build_agent().run()
