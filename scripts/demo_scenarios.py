"""Run CareCompass conversations locally without Agentverse (in-process research client).

    python scripts/demo_scenarios.py                 # all scripted scenarios (fixture data)
    python scripts/demo_scenarios.py --scenario acl  # one scenario
    python scripts/demo_scenarios.py --interactive   # chat in the terminal
    CARECOMPASS_DATA_MODE=live python scripts/demo_scenarios.py --scenario live

The deployed system routes research through the Hospital/Insurer uAgents instead
(see scripts/run_agents.py and scripts/test_protocol.py).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import replace  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.database.session import make_session_factory  # noqa: E402
from app.intelligence.asi1_client import ASI1Client  # noqa: E402
from app.research.service import InProcessResearchClient, build_sources  # noqa: E402
from app.workflow.orchestrator import CareCompassWorkflow  # noqa: E402

SCENARIOS: dict[str, list[str]] = {
    "acl": ["I have an ACL tear. I live in Jaipur and have Demo Shield insurance. Help me find a suitable hospital.",
            '{"action": "select_hospital", "hospital_id": "syn-jpr-aravali"}',
            "save this one",
            "approve",
            "approve"],
    "plan_exclusion": ["ACL tear, Jaipur, Demo Shield insurance", "Demo Shield Basic"],
    "kidney": ["I have kidney stones and live in Jaipur."],
    "symptoms": ["I've had knee pain for two weeks.", "Jaipur", "none"],
    "emergency": ["Sudden severe chest pain and difficulty breathing."],
    "outage": ["I have an ACL tear, I'm in Jaipur, insured with Sample Care Health"],
    "report": ["MRI LEFT KNEE. Findings: Complete tear of the anterior cruciate ligament with bone bruise 9 mm. "
               "Medial meniscus intact. Impression: Complete ACL tear. Possible low-grade MCL sprain. "
               "Advised orthopaedic consultation. I'm in Jaipur, no insurance."],
    "reject": ["kidney stone in Delhi, Demo Shield insurance", "cancel", "try Jaipur instead"],
    "live": ["I have an ACL tear and live in Jaipur. No insurance."],
}


async def run(names: list[str], interactive: bool) -> None:
    settings = get_settings()
    if settings.database_url.startswith("sqlite") and "PYTEST" not in settings.database_url:
        db = Path(tempfile.gettempdir()) / "carecompass_demo.db"
        settings = replace(settings, database_url=f"sqlite:///{db.as_posix()}")
    repo = Repository(make_session_factory(settings.database_url))
    workflow = CareCompassWorkflow(repo, settings, ASI1Client(settings))
    research = InProcessResearchClient(*build_sources(settings))
    print(f"[data mode: {settings.data_mode}] [ASI1: {'configured' if settings.asi1_api_key else 'not configured - rules only'}]")

    async def say(session: str, text: str) -> None:
        print(f"\n\033[1;36mUSER>\033[0m {text}")
        for reply in await workflow.handle(session, text, research):
            print(f"\033[1;32mCARECOMPASS>\033[0m {reply.text}")
            if reply.card:
                print(f"   [card: {reply.card.kind} - {len(reply.card.metadata()['card_payload'])} bytes]")

    if interactive:
        session = "terminal-user"
        while True:
            try:
                text = input("\nyou> ")
            except EOFError:
                break
            await say(session, text)
        return
    for name in names:
        print(f"\n{'=' * 30} scenario: {name} {'=' * 30}")
        for text in SCENARIOS[name]:
            await say(f"demo-{name}", text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), action="append")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    default = [n for n in SCENARIOS if n != "live"]
    asyncio.run(run(args.scenario or default, args.interactive))
