"""Measure engineering metrics on the fixture dataset (in-process research client).

    python scripts/benchmark.py --runs 20

Writes data/test_results/metrics.json. Agent-to-agent/ACP numbers come from
data/test_results/protocol_test_report.json (scripts/test_protocol.py) when present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.database.session import make_session_factory  # noqa: E402
from app.matching.result_verifier import check_text  # noqa: E402
from app.research.hospital_sources import FixtureHospitalSource  # noqa: E402
from app.research.insurer_sources import FixtureInsurerSource  # noqa: E402
from app.research.service import InProcessResearchClient  # noqa: E402
from app.workflow.orchestrator import CareCompassWorkflow  # noqa: E402

JOURNEYS = {
    "acl_demo_shield": ["I have an ACL tear. I live in Jaipur and have Demo Shield insurance.", "1", "save", "approve"],
    "kidney_no_insurer": ["kidney stone in Delhi, no insurance", "approve"],
    "symptoms_followup": ["I've had knee pain for two weeks.", "Jaipur", "approve"],
    "insurer_outage": ["ACL tear in Jaipur with Sample Care Health", "approve"],
    "report": ["MRI knee. Impression: Complete ACL tear. Medial meniscus intact. I'm in Jaipur, no insurance.", "approve"],
}


async def main(runs: int) -> dict:
    db = Path(tempfile.gettempdir()) / f"carecompass_bench_{int(time.time())}.db"
    settings = replace(get_settings(), data_mode="fixture", database_url=f"sqlite:///{db.as_posix()}", asi1_api_key="")
    repo = Repository(make_session_factory(settings.database_url))
    wf = CareCompassWorkflow(repo, settings)
    research = InProcessResearchClient(FixtureHospitalSource(), FixtureInsurerSource())
    turn_latencies, completed, started, questions, dup_ok, unsupported, total_claims = [], 0, 0, [], 0, 0, 0
    conflicts_detected = conflicts_expected = 0
    for i in range(runs):
        for name, turns in JOURNEYS.items():
            session = f"{name}-{i}"
            started += 1
            asked = 0
            conf = None
            for text in turns:
                t0 = time.perf_counter()
                replies = await wf.handle(session, text, research)
                turn_latencies.append((time.perf_counter() - t0) * 1000)
                for r in replies:
                    total_claims += 1
                    unsupported += bool(check_text(r.text.replace("does not guarantee", "")))
                    if "?" in r.text and r.card is None and "Please confirm" not in r.text:
                        asked += 1
                    m = re.search(r"(CC-[A-Z0-9]{8})", r.text)
                    conf = conf or (m.group(1) if m else None)
                    if name == "acl_demo_shield" and r.card is not None and r.card.kind == "carousel":
                        conflicts_expected += 1
                        conflicts_detected += "Conflict" in r.text
            questions.append(asked)
            replies = await wf.handle(session, "approve", research)  # duplicate approval
            dup_ok += bool(conf) and conf in replies[0].text and "already saved" in replies[0].text
            case = repo.latest_case(session)
            if case.state == "COMPLETED" and len(repo.shortlists(case.case_id)) == 1:
                completed += 1
    lat = sorted(turn_latencies)
    metrics = {
        "dataset": "synthetic fixtures (in-process research client)",
        "journeys_run": started,
        "workflow_completion_rate": round(completed / started, 3),
        "turn_latency_ms_avg": round(statistics.mean(lat), 1),
        "turn_latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 1),
        "follow_up_questions_per_journey": {n: questions[k] for k, n in enumerate(JOURNEYS)},
        "duplicate_approvals_without_new_side_effect": f"{dup_ok}/{started}",
        "unsupported_claim_rate": round(unsupported / max(total_claims, 1), 4),
        "source_conflict_detection": f"{conflicts_detected}/{conflicts_expected}",
    }
    proto = ROOT / "data" / "test_results" / "protocol_test_report.json"
    if proto.exists():
        report = json.loads(proto.read_text(encoding="utf-8"))
        metrics["acp_real_agents"] = {
            "ack_success": f"{report.get('acks_received')}/{report.get('messages_sent')}",
            "checks_passed": f"{sum(report['checks'].values())}/{len(report['checks'])}",
            "turn_latency_s": report.get("latencies"),
            "agent_tasks": report.get("db", {}).get("agent_tasks"),
        }
    out = ROOT / "data" / "test_results" / "metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    print(json.dumps(asyncio.run(main(ap.parse_args().runs)), indent=2))
