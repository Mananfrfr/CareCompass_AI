"""Condition-aware program signposting with explicit unknown eligibility."""
import json

from app.config import DATA_DIR
from app.schemas.input import CareRequest


def programs(req: CareRequest | None = None) -> list[dict]:
    rows = json.loads((DATA_DIR / "catalog/assistance_programs.json").read_text(encoding="utf-8"))["records"]
    if req is None:
        return rows
    result = []
    for row in rows:
        if row.get("age_min") is not None and (req.patient_age is None or req.patient_age < row["age_min"]):
            continue
        if row.get("age_max") is not None and (req.patient_age is None or req.patient_age > row["age_max"]):
            continue
        if row.get("state") and (req.state or "").casefold() != row["state"].casefold():
            continue
        if row["specialties"] and req.care_specialty not in row["specialties"]:
            continue
        result.append(row)
    return result


def render_assistance(req: CareRequest | None = None) -> str:
    lines = ["**Financial assistance avenues to check**",
             "These are official program references. Your eligibility, funding, hospital acceptance and treatment package have not been verified."]
    for row in programs(req):
        lines.append(f"- [{row['name']}]({row['source_url']}): {row['summary']}")
    return "\n\n".join(lines)
