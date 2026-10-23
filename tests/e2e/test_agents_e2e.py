"""Tests 15 & 16: real uAgent processes, real ACP messages, real agent-to-agent research.

Runs scripts/test_protocol.py, which starts the three agents on ports 8000-8002 plus a client on 8010.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.coordinator import AgentResearchClient
from app.agents.protocols import HospitalResearchResponse
from app.schemas.hospital import HospitalResearchQuery

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.agents
def test_15_16_acp_and_multi_agent_over_real_uagents():
    proc = subprocess.run([sys.executable, "scripts/test_protocol.py"], cwd=ROOT, capture_output=True, text=True,
                          timeout=600, encoding="utf-8", errors="replace")
    report = json.loads((ROOT / "data" / "test_results" / "protocol_test_report.json").read_text(encoding="utf-8"))
    failed = [k for k, v in report["checks"].items() if not v]
    assert proc.returncode == 0 and not failed, f"failed checks: {failed}\n{proc.stdout[-2000:]}"


class FakeCtx:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.logger = SimpleNamespace(warning=lambda *a, **k: None)

    async def send_and_receive(self, address, request, response_type, timeout):
        self.calls += 1
        reply = self.replies.pop(0)
        return (reply(request) if callable(reply) else reply), SimpleNamespace(detail="timeout")


async def test_13_agent_timeout_bounded_retries(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    ctx = FakeCtx([None, None, None])
    client = AgentResearchClient(ctx, "agent1qhospital", "agent1qinsurer", timeout_s=1, max_attempts=2)
    out = await client.hospitals(HospitalResearchQuery(case_id="c", task_id="t1", city="Jaipur", specialty="orthopaedics"))
    assert out.result is None and out.attempts == 2 and ctx.calls == 2 and "no reply" in out.error


async def test_agent_reply_validated(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    bad = HospitalResearchResponse(task_id="t1", ok=True, result_json='{"not": "a result"}')
    good = lambda req: HospitalResearchResponse(task_id=req.task_id, ok=True, result_json=json.dumps({"task_id": req.task_id}))  # noqa: E731
    ctx = FakeCtx([bad, good])
    client = AgentResearchClient(ctx, "agent1qhospital", "agent1qinsurer", timeout_s=1, max_attempts=2)
    out = await client.hospitals(HospitalResearchQuery(case_id="c", task_id="t1", city="Jaipur", specialty="orthopaedics"))
    assert out.result is not None and out.attempts == 2


async def _no_sleep(_s):
    return None
