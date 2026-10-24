"""Searchable public identity catalog; intentionally not an eligibility engine."""
import json
import re
from pathlib import Path

from app.config import DATA_DIR


class PolicyCatalog:
    def __init__(self, path: Path | None = None):
        path = path or DATA_DIR / "catalog" / "insurance_products.json"
        self.records = json.loads(path.read_text(encoding="utf-8"))["records"] if path.exists() else []

    def search(self, query: str, limit: int = 8) -> list[dict]:
        terms = re.findall(r"[a-z0-9]+", query.casefold())
        if not terms:
            return []
        matched = [r for r in self.records if all(t in (r["name"] + " " + r["provider"] + " " + r.get("uin", "")).casefold() for t in terms)]
        # Variants and revisions remain inspectable but cannot inflate the default list.
        matched.sort(key=lambda r: (r.get("financial_year", ""), r.get("uin", "")), reverse=True)
        seen = set()
        result = []
        for r in matched:
            identity = (r["provider"].casefold(), re.sub(r"\W+", "", r["name"].casefold()))
            if identity not in seen:
                seen.add(identity)
                result.append(r)
        return result[:limit]

    def render(self, query: str) -> str:
        rows = self.search(query)
        lines = [f"**Policy identity search: {query[:100]}**",
                 "These official-register entries identify real products, including older versions and group/add-on products. Current sale, your eligibility, treatment coverage and hospital network have not been confirmed."]
        for r in rows:
            lines.append(f"- **{r['name']}** — {r['provider']}; UIN `{r.get('uin', 'not applicable')}`; {r['record_type']}; register year {r.get('financial_year', 'unknown')}. [Official record]({r['source_url']})")
        if not rows:
            lines.append("No matching official identity found. Try the insurer name or UIN from your policy schedule.")
        lines.append("Use your existing policy schedule and insurer confirmation for care decisions; buying a new policy does not establish cover for an existing treatment need.")
        return "\n\n".join(lines)
