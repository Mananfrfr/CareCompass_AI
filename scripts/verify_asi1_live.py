"""Compare deterministic extraction with a real ASI1 call using synthetic input.

Run: python scripts/verify_asi1_live.py
No credentials or patient data are printed. Exit 0 requires model-added understanding.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.intelligence.asi1_client import ASI1Client
from app.intelligence.intent_parser import IntentParser, rule_extract

SAMPLE = "I have lateral epicondylitis. I live in Jaipur and have Demo Shield insurance."


async def main() -> int:
    client = ASI1Client(get_settings())
    if not client.available:
        print("ASI1_API_KEY is missing. Add it privately to .env; no live verification was performed.")
        return 2
    baseline = rule_extract(SAMPLE)
    result = await IntentParser(client).parse(SAMPLE)
    passed = (
        client.calls > 0
        and result.extraction_method == "rules+asi1"
        and baseline.care_specialty is None
        and result.care_specialty == "orthopaedics"
        and result.city == baseline.city
        and result.insurance_provider == baseline.insurance_provider
    )
    print(json.dumps({
        "synthetic_input": SAMPLE,
        "rules_specialty": baseline.care_specialty,
        "asi1_specialty": result.care_specialty,
        "extraction_method": result.extraction_method,
        "api_calls": client.calls,
        "api_failures": client.failures,
        "meaningful_contribution_verified": passed,
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
