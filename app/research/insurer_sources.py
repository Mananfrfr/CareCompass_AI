"""Insurer network and policy research providers.

FixtureInsurerSource         - synthetic, fictional insurers only (never real insurer names).
OfficialNetworkFileSource    - live: network lists that the operator downloaded from an insurer's
                               official website and imported into data/insurer_networks/*.csv,
                               with the source URL and retrieval date recorded in the file header.

CareCompass deliberately does NOT scrape insurer portals: most sit behind CAPTCHA/OTP or terms
that prohibit automated access. When no permitted source exists the result says so
(SOURCE_UNAVAILABLE) instead of guessing.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.config import DATA_DIR
from app.intelligence.care_knowledge import normalize_city
from app.schemas.evidence import ClaimType, Evidence, Reliability, SourceStatus, SourceType
from app.schemas.insurance import (
    InsuranceState,
    InsurerResearchQuery,
    InsurerResearchResult,
    NetworkObservation,
    PolicyFinding,
)


class InsurerSource(Protocol):
    async def research(self, query: InsurerResearchQuery) -> InsurerResearchResult: ...


def _procedure_matches(procedure: str | None, keywords: list[str]) -> bool:
    if not procedure:
        return False
    low = procedure.lower()
    return any(k in low for k in keywords)


class FixtureInsurerSource:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "fixtures" / "insurers.json"

    async def research(self, query: InsurerResearchQuery) -> InsurerResearchResult:
        data = json.loads(self.path.read_text(encoding="utf-8"))["insurers"]
        result = InsurerResearchResult(task_id=query.task_id, insurer=query.insurer, data_mode="fixture")
        insurer = data.get(query.insurer)
        if insurer is None:
            result.source_status.append(SourceStatus(
                source_name=f"{query.insurer} network directory", ok=False,
                error="Fixture mode only contains fictional insurers; no data for this insurer was checked.",
            ))
            return result
        result.insurer_recognized = True
        city = normalize_city(query.city) or query.city
        for src in insurer["sources"]:
            if src.get("simulate_unavailable"):
                result.source_status.append(SourceStatus(source_name=src["name"], url=src["url"], ok=False,
                                                         error=src.get("error", "unavailable")))
                continue
            retrieved = datetime.fromisoformat(src["retrieved_at"])
            complete = city in src.get("complete_for_cities", [])
            result.source_status.append(SourceStatus(source_name=src["name"], url=src["url"], ok=True,
                                                     retrieved_at=retrieved, complete_for_city=complete))
            for row in src["rows"]:
                if (normalize_city(row["city"]) or row["city"]) != city:
                    continue
                claim = ClaimType.NETWORK_LISTING if row["in_network"] else ClaimType.NETWORK_ABSENCE
                excerpt = row.get("excerpt") or f"{row['listed_name']}, {row['city']} {row.get('postcode', '')}".strip()
                ev = Evidence(claim_type=claim, claim_value="in_network" if row["in_network"] else "not_in_network",
                              subject=row["listed_name"], source_name=src["name"], source_url=src["url"],
                              source_type=SourceType.SYNTHETIC_FIXTURE, excerpt=excerpt, retrieved_at=retrieved,
                              reliability=Reliability.HIGH, synthetic=True, insurer=query.insurer, city=row["city"])
                result.observations.append(NetworkObservation(
                    listed_name=row["listed_name"], city=row["city"], postcode=row.get("postcode"),
                    in_network=row["in_network"], cashless=row.get("cashless"), evidence=ev,
                ))
        plans = insurer.get("plans", {})
        result.known_plans = sorted(plans)
        plan_rules_for_procedure = {
            name: [r for r in p["rules"] if _procedure_matches(query.procedure, r["keywords"])]
            for name, p in plans.items()
        }
        if query.plan:
            plan_name = next((p for p in plans if p.lower() == query.plan.lower()), None)
            if plan_name:
                p = plans[plan_name]
                for rule in plan_rules_for_procedure[plan_name]:
                    state = InsuranceState(rule["state"])
                    claim = ClaimType.POLICY_EXCLUSION if state == InsuranceState.PROCEDURE_EXCLUDED else ClaimType.POLICY_WAITING_PERIOD
                    result.policy_findings.append(PolicyFinding(plan=plan_name, procedure=query.procedure or "", state=state,
                        evidence=Evidence(claim_type=claim, claim_value=query.procedure or "", subject=plan_name,
                                          source_name=f"{plan_name} policy wording (synthetic)", source_url=p["document_url"],
                                          source_type=SourceType.SYNTHETIC_FIXTURE, excerpt=rule["excerpt"],
                                          retrieved_at=datetime.fromisoformat(p["retrieved_at"]), synthetic=True,
                                          insurer=query.insurer, plan=plan_name)))
            else:
                result.plan_required = True  # unknown plan name: ask again rather than guess
        elif any(plan_rules_for_procedure.values()):
            result.plan_required = True
        return result


class OfficialNetworkFileSource:
    """Reads operator-imported official network lists.

    File format (data/insurer_networks/<anything>.csv):
        # insurer: Star Health
        # source_url: https://<official insurer page the list was downloaded from>
        # retrieved_at: 2026-10-20
        # complete_for_cities: Jaipur
        name,city,address,postcode,cashless
    """

    def __init__(self, directory: Path | None = None):
        self.directory = directory or DATA_DIR / "insurer_networks"

    def _load(self) -> list[tuple[dict[str, str], list[dict[str, str]], Path]]:
        out = []
        for path in sorted(self.directory.glob("*.csv")):
            header: dict[str, str] = {}
            lines = path.read_text(encoding="utf-8").splitlines()
            body = []
            for line in lines:
                if line.startswith("#"):
                    key, _, value = line[1:].partition(":")
                    header[key.strip().lower()] = value.strip()
                else:
                    body.append(line)
            rows = list(csv.DictReader(io.StringIO("\n".join(body))))
            if header.get("insurer") and header.get("source_url", "").startswith("https://"):
                out.append((header, rows, path))
        return out

    async def research(self, query: InsurerResearchQuery) -> InsurerResearchResult:
        result = InsurerResearchResult(task_id=query.task_id, insurer=query.insurer, data_mode="live")
        city = normalize_city(query.city) or query.city
        matched = [(h, r, p) for h, r, p in self._load() if h["insurer"].lower() == query.insurer.lower()]
        if not matched:
            result.source_status.append(SourceStatus(
                source_name=f"{query.insurer} official network list", ok=False,
                error=("No official network list has been imported for this insurer. Automated access to insurer "
                       "portals is not used (CAPTCHA/terms), so network status was not checked."),
            ))
            return result
        result.insurer_recognized = True
        for header, rows, path in matched:
            try:
                retrieved = datetime.fromisoformat(header.get("retrieved_at", "")).replace(tzinfo=timezone.utc)
            except ValueError:
                retrieved = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            complete = city in [c.strip() for c in header.get("complete_for_cities", "").split(",")]
            name = f"{query.insurer} official network list ({path.name})"
            result.source_status.append(SourceStatus(source_name=name, url=header["source_url"], ok=True,
                                                     retrieved_at=retrieved, complete_for_city=complete))
            for row in rows:
                row_city = normalize_city(row.get("city", "")) or row.get("city", "")
                if row_city != city:
                    continue
                cashless = (row.get("cashless") or "").strip().lower()
                ev = Evidence(claim_type=ClaimType.NETWORK_LISTING, claim_value="in_network", subject=row["name"],
                              source_name=f"{query.insurer} official network list", source_url=header["source_url"],
                              source_type=SourceType.OFFICIAL_INSURER_DIRECTORY,
                              excerpt=f"{row['name']}, {row.get('address', '')} {row.get('postcode', '')}".strip()[:300],
                              retrieved_at=retrieved, reliability=Reliability.HIGH, insurer=query.insurer, city=row_city)
                result.observations.append(NetworkObservation(
                    listed_name=row["name"], city=row_city, address=row.get("address", ""), postcode=row.get("postcode"),
                    in_network=True, cashless=True if cashless in {"yes", "true", "y"} else None, evidence=ev,
                ))
        return result


def build_insurer_source(fixture_mode: bool) -> InsurerSource:
    return FixtureInsurerSource() if fixture_mode else OfficialNetworkFileSource()
