"""Live ACP + multi-agent test over real uAgent messaging (no mocks).

Starts the Hospital, Insurer and Coordinator agents as separate processes (coordinator in
local mode), then a client uAgent speaks the Agent Chat Protocol to the coordinator exactly as
ASI:One would: ChatMessage -> ChatAcknowledgement -> ChatMessage(Text + card Metadata) ...
It runs the full journey (request -> shortlist card -> selection -> review card -> approve ->
verified confirmation -> duplicate approve) and writes a JSON report.

    python scripts/test_protocol.py            # exits 0 if every check passed
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uagents import Agent, Context  # noqa: E402
from uagents.resolver import RulesBasedResolver  # noqa: E402
from uagents_core.contrib.protocols.chat import (  # noqa: E402
    ChatAcknowledgement,
    ChatMessage,
    MetadataContent,
    StartSessionContent,
    TextContent,
)

from app.agents.common import address_from_seed  # noqa: E402

STEPS = [
    ("request", "I have an ACL tear. I live in Jaipur and have Demo Shield insurance. Help me find a suitable hospital."),
    ("select", '{"action": "select_hospital", "hospital_id": "syn-jpr-aravali"}'),
    ("review", '{"action": "review", "hospital_id": "syn-jpr-aravali"}'),
    ("approve", "approve"),
    ("approve_again", "approve"),
]


def wait_port(port: int, timeout: float = 40) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main() -> int:
    # Allocate a separate port set so tests never talk to a running demo agent.
    reservations = [socket.socket() for _ in range(4)]
    try:
        for sock in reservations:
            sock.bind(("127.0.0.1", 0))
        coordinator_port, hospital_port, insurer_port, client_port = [s.getsockname()[1] for s in reservations]
    finally:
        for sock in reservations:
            sock.close()
    seeds = {k: f"cc-test-{k.lower()}-{secrets.token_hex(16)}" for k in ("COORDINATOR_SEED", "HOSPITAL_AGENT_SEED", "INSURER_AGENT_SEED")}
    client_seed = f"cc-test-client-{secrets.token_hex(16)}"
    client_address = address_from_seed(client_seed)
    db = Path(tempfile.gettempdir()) / f"carecompass_protocol_{secrets.token_hex(4)}.db"
    env = dict(os.environ, **seeds, PYTHONUNBUFFERED="1", PYTHONUTF8="1", COORDINATOR_CONNECTIVITY="local",
               CARECOMPASS_DATA_MODE="fixture", DATABASE_URL=f"sqlite:///{db.as_posix()}",
               CARECOMPASS_EXTRA_ROUTES=f"{client_address}=http://127.0.0.1:{client_port}/submit", ASI1_API_KEY="",
               COORDINATOR_PORT=str(coordinator_port), HOSPITAL_AGENT_PORT=str(hospital_port),
               INSURER_AGENT_PORT=str(insurer_port), CARECOMPASS_PAYMENTS="disabled")
    logs = Path(tempfile.mkdtemp(prefix="carecompass_protocol_logs_"))
    logs.mkdir(exist_ok=True)
    procs = []
    for name, module, port in (("hospital", "app.agents.hospital_agent", hospital_port), ("insurer", "app.agents.insurer_agent", insurer_port),
                               ("coordinator", "app.agents.coordinator", coordinator_port)):
        log = open(logs / f"{name}.log", "w", encoding="utf-8")
        procs.append((subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT), log))
        if not wait_port(port):
            print(f"{name} did not start; see {logs / (name + '.log')}")
            for p, _ in procs:
                p.terminate()
            return 2
    coordinator = address_from_seed(seeds["COORDINATOR_SEED"])
    try:
        report = asyncio.run(run_client(client_seed, coordinator, coordinator_port, client_port))
    finally:
        for p, log in procs:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            log.close()
    hospital_log = (logs / "hospital.log").read_text(encoding="utf-8", errors="replace")
    insurer_log = (logs / "insurer.log").read_text(encoding="utf-8", errors="replace")
    report["checks"]["hospital_agent_received_task"] = "hospital research task=" in hospital_log
    report["checks"]["insurer_agent_received_task"] = "insurer research task=" in insurer_log
    _db_checks(report, db)
    out = ROOT / "data" / "test_results" / "protocol_test_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["checks"], indent=2))
    print(f"latencies (s): {report['latencies']}")
    print(f"report: {out}\nlogs: {logs}")
    return 0 if all(report["checks"].values()) else 1


def _db_checks(report: dict, db: Path) -> None:
    import sqlite3

    con = sqlite3.connect(db)
    try:
        shortlists = con.execute("select confirmation_id, case_id from shortlists").fetchall()
        tasks = con.execute("select agent, status, attempts, latency_ms from agent_tasks").fetchall()
        execs = con.execute("select status, verified from action_executions").fetchall()
    finally:
        con.close()
    report["db"] = {"shortlists": shortlists, "agent_tasks": tasks, "action_executions": execs}
    conf = report.get("confirmation_id")
    report["checks"]["exactly_one_shortlist_persisted"] = len(shortlists) == 1
    report["checks"]["confirmation_id_matches_db_record"] = bool(conf) and shortlists and shortlists[0][0] == conf
    report["checks"]["both_research_agents_succeeded"] = sorted(a for a, s, *_ in tasks if s == "succeeded") == ["hospital-agent", "insurer-agent"]
    report["checks"]["action_verified_in_db"] = execs == [("succeeded", 1)]


async def run_client(client_seed: str, coordinator: str, coordinator_port: int, client_port: int) -> dict:
    inbox: asyncio.Queue = asyncio.Queue()
    acks: set[str] = set()
    client = Agent(name="carecompass-test-client", seed=client_seed, port=client_port,
                   endpoint=[f"http://127.0.0.1:{client_port}/submit"],
                   resolve=RulesBasedResolver({coordinator: f"http://127.0.0.1:{coordinator_port}/submit"}),
                   publish_agent_details=False, enable_agent_inspector=False)
    report: dict = {"started": datetime.now(timezone.utc).isoformat(), "coordinator": coordinator, "steps": [],
                    "checks": {}, "latencies": {}}

    @client.on_message(ChatAcknowledgement)
    async def _ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        acks.add(str(msg.acknowledged_msg_id))

    @client.on_message(ChatMessage)
    async def _msg(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        await inbox.put(msg)

    async def converse(ctx: Context) -> None:
        sent_ids = []
        start_msg = ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                content=[StartSessionContent(type="start-session")])
        await ctx.send(coordinator, start_msg)
        sent_ids.append(str(start_msg.msg_id))
        await asyncio.sleep(1.5)
        while not inbox.empty():
            inbox.get_nowait()
        for name, text in STEPS:
            msg = ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])
            t0 = time.perf_counter()
            await ctx.send(coordinator, msg)
            sent_ids.append(str(msg.msg_id))
            try:
                reply = await asyncio.wait_for(inbox.get(), 120)
            except asyncio.TimeoutError:
                report["steps"].append({"step": name, "error": "no reply"})
                break
            report["latencies"][name] = round(time.perf_counter() - t0, 2)
            texts = [c.text for c in reply.content if isinstance(c, TextContent)]
            meta = [c.metadata for c in reply.content if isinstance(c, MetadataContent)]
            card = meta[0] if meta else None
            step = {"step": name, "text_preview": (texts[0] if texts else "")[:300], "card_kind": card and card.get("card_kind")}
            if card:
                payload = json.loads(card["card_payload"])
                step["card_valid"] = (card.get("card_protocol_version") == "1" and card.get("requires_card_interaction") == "true"
                                      and all(isinstance(v, str) for v in card.values()) and len(card["card_payload"]) <= 65536)
                step["card_items"] = len(payload.get("items", [])) if card.get("card_kind") == "carousel" else None
            if name in ("approve", "approve_again") and texts:
                import re
                m = re.search(r"\b(CC-[A-Z0-9]{8})\b", texts[0])
                step["confirmation_id"] = m.group(1) if m else None
            report["steps"].append(step)
        await asyncio.sleep(1.0)
        report["acks_received"] = len(acks & set(sent_ids))
        report["messages_sent"] = len(sent_ids)
        done.set()

    done = asyncio.Event()

    @client.on_event("startup")
    async def _startup(ctx: Context) -> None:
        asyncio.create_task(converse(ctx))

    task = asyncio.create_task(client.run_async())
    try:
        await asyncio.wait_for(done.wait(), 400)
    finally:
        task.cancel()
    steps = {s["step"]: s for s in report["steps"]}
    c = report["checks"]
    c["every_message_acknowledged"] = report.get("acks_received") == report.get("messages_sent")
    c["shortlist_carousel_card"] = steps.get("request", {}).get("card_kind") == "carousel" and steps["request"].get("card_valid", False)
    c["detail_card_on_selection"] = steps.get("select", {}).get("card_kind") == "detail"
    c["review_card_before_action"] = steps.get("review", {}).get("card_kind") == "review"
    conf = steps.get("approve", {}).get("confirmation_id")
    report["confirmation_id"] = conf
    c["confirmation_issued_after_approval"] = bool(conf) and "Saved and verified" in steps["approve"]["text_preview"]
    c["duplicate_approval_same_id"] = steps.get("approve_again", {}).get("confirmation_id") == conf and \
        "already saved" in steps.get("approve_again", {}).get("text_preview", "")
    return report


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
