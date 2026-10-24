"""Real-insurer intelligence: IRDAI product register, official websites and policy-wording checks.

Network lists of Indian insurers sit behind search portals (CAPTCHA/OTP/terms), so CareCompass
does not scrape them. What it *can* do honestly for any real insurer:

1. Recognise the insurer and list its products from the IRDAI health-product register
   (data/catalog/insurance_products.json, official identities with UINs).
2. Match the user's plan name to a registered product (UIN + official policy wording PDF).
3. In live mode, read that official policy wording PDF and quote the clauses that mention the
   requested procedure (waiting periods / exclusions) - with the exact excerpt, never a verdict.
4. Point the user to the insurer's official website for the network-hospital search.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.research.policy_catalog import PolicyCatalog
from app.schemas.evidence import ClaimType, Evidence, Reliability, SourceType
from app.schemas.insurance import InsuranceState, PolicyFinding


@dataclass(frozen=True)
class InsurerProfile:
    name: str
    provider_pattern: str
    website: str


INSURERS: dict[str, InsurerProfile] = {p.name: p for p in [
    InsurerProfile("Star Health", r"star health", "https://www.starhealth.in"),
    InsurerProfile("HDFC ERGO", r"hdfc ergo", "https://www.hdfcergo.com"),
    InsurerProfile("ICICI Lombard", r"icici lombard", "https://www.icicilombard.com"),
    InsurerProfile("Niva Bupa", r"niva bupa|max bupa", "https://www.nivabupa.com"),
    InsurerProfile("Care Health", r"care health|religare", "https://www.careinsurance.com"),
    InsurerProfile("Bajaj Allianz", r"bajaj allianz", "https://www.bajajallianz.com"),
    InsurerProfile("Tata AIG", r"tata aig", "https://www.tataaig.com"),
    InsurerProfile("Aditya Birla Health", r"aditya birla", "https://www.adityabirlacapital.com/healthinsurance"),
    InsurerProfile("ManipalCigna", r"manipal ?cigna", "https://www.manipalcigna.com"),
    InsurerProfile("New India Assurance", r"new india", "https://www.newindia.co.in"),
    InsurerProfile("United India Insurance", r"united india", "https://uiic.co.in"),
    InsurerProfile("Oriental Insurance", r"oriental", "https://orientalinsurance.org.in"),
    InsurerProfile("National Insurance", r"national insurance", "https://nationalinsurance.nic.co.in"),
    InsurerProfile("SBI General", r"sbi general", "https://www.sbigeneral.in"),
    InsurerProfile("Reliance General", r"reliance general", "https://www.reliancegeneral.co.in"),
    InsurerProfile("Ayushman Bharat PM-JAY", r"^$", "https://pmjay.gov.in"),
    InsurerProfile("CGHS", r"^$", "https://cghs.mohfw.gov.in"),
    InsurerProfile("ECHS", r"^$", "https://echs.gov.in"),
]}

# Procedure -> words that policy wordings use for it (IRDAI standard specified-disease lists).
PROCEDURE_TERMS: dict[str, tuple[str, ...]] = {
    "acl": ("ligament", "arthroscop", "joint replacement", "knee"),
    "arthroscopy": ("arthroscop", "ligament", "menisc", "knee"),
    "knee replacement": ("joint replacement", "knee replacement", "arthroplasty", "osteoarthritis"),
    "cataract": ("cataract",),
    "lithotripsy": ("calculus", "calculi", "stone", "lithotripsy"),
    "ureteroscopy": ("calculus", "calculi", "stone"),
    "hernia": ("hernia",),
    "cholecystectomy": ("gall bladder", "gallbladder", "cholecyst", "calculus"),
    "appendectomy": ("appendic",),
    "dialysis": ("dialysis", "renal failure", "kidney"),
}
WAITING = re.compile(r"waiting period|specified (?:disease|illness)|excl0?2|24 months|two years|2 years|48 months", re.I)
EXCLUSION = re.compile(r"\bexcl\s?\d{2}\b|permanent(?:ly)? exclu", re.I)


def profile_for(insurer: str) -> InsurerProfile | None:
    return INSURERS.get(insurer)


def registered_products(insurer: str, limit: int = 6, catalog: PolicyCatalog | None = None) -> list[dict]:
    profile = profile_for(insurer)
    if not profile or profile.provider_pattern == r"^$":
        return []
    catalog = catalog or PolicyCatalog()
    rows = [r for r in catalog.records if re.search(profile.provider_pattern, r["provider"], re.I)]
    rows.sort(key=lambda r: (r.get("record_type", "").lower() in {"group", "group health"}, r.get("financial_year", "")),
              reverse=False)
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r.get("financial_year", ""), reverse=True):
        key = re.sub(r"\W+", "", r["name"].lower())
        uin = r.get("uin", "").upper()
        # Individual retail products only (UIN "...HLIP..."); group, add-on and pandemic covers are not useful here.
        if key in seen or (uin and "HLIP" not in uin) or re.search(r"group|covid|corona|add ?-?on", r["name"], re.I):
            continue
        seen.add(key)
        out.append(r)
    return out[:limit]


def count_products(insurer: str, catalog: PolicyCatalog | None = None) -> int:
    profile = profile_for(insurer)
    if not profile or profile.provider_pattern == r"^$":
        return 0
    catalog = catalog or PolicyCatalog()
    return len({r["uin"] for r in catalog.records if re.search(profile.provider_pattern, r["provider"], re.I)})


def match_plan(insurer: str, plan: str | None, catalog: PolicyCatalog | None = None) -> dict | None:
    """Best IRDAI register entry for the user's plan name, restricted to this insurer."""
    profile = profile_for(insurer)
    if not plan or not profile:
        return None
    catalog = catalog or PolicyCatalog()
    words = [w for w in re.findall(r"[a-z0-9]+", plan.lower())
             if w not in {"plan", "policy", "insurance", "health", "star", "the", "my", "and"}]
    if not words:
        return None
    best, best_score = None, 0.0
    for r in catalog.records:
        if not re.search(profile.provider_pattern, r["provider"], re.I):
            continue
        hay = set(re.findall(r"[a-z0-9]+", f"{r['name']} {r.get('uin', '')}".lower()))
        score = sum(1 for w in words if w in hay) / len(words)
        # Prefer the newest revision of the same product.
        if score > best_score or (score == best_score and best and r.get("financial_year", "") > best.get("financial_year", "")):
            best, best_score = r, score
    return best if best_score >= 0.6 else None


def procedure_terms(procedure: str | None) -> tuple[str, ...]:
    low = (procedure or "").lower()
    for key, terms in PROCEDURE_TERMS.items():
        if key in low:
            return terms
    return ()


def scan_wording(text: str, procedure: str, terms: tuple[str, ...]) -> list[tuple[InsuranceState, str]]:
    """Find wording clauses that mention the procedure inside a waiting-period or exclusion context."""
    flat = " ".join(text.split())
    low = flat.lower()
    found: list[tuple[InsuranceState, str]] = []
    for term in terms:
        for m in re.finditer(re.escape(term), low):
            window = flat[max(0, m.start() - 500): m.end() + 200]
            sentence_start = flat.rfind(".", 0, m.start()) + 1
            excerpt = flat[max(sentence_start, m.start() - 160): m.end() + 160].strip()
            if WAITING.search(window):
                found.append((InsuranceState.WAITING_PERIOD_APPLIES, excerpt))
            elif EXCLUSION.search(window):
                found.append((InsuranceState.PROCEDURE_EXCLUDED, excerpt))
            if len(found) >= 2:
                return found
        if found:
            return found
    return found


class PolicyWordingReader:
    """Fetches an official IRDAI-hosted policy wording PDF and extracts its text."""

    def __init__(self, fetcher):
        from app.research.source_fetcher import SafeFetcher
        self.fetcher = SafeFetcher(fetcher.user_agent, timeout_s=10, max_bytes=12_000_000, resolver=fetcher.resolver,
                                   transport=fetcher.transport, respect_robots=False, max_attempts=1,
                                   allowed_hosts={"irdai.gov.in"})
        self._cache: dict[str, str] = {}

    async def text(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        doc = await self.fetcher.fetch(url)
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(doc.body))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:60])
        self._cache[url] = text
        return text


async def policy_findings(record: dict, procedure: str | None, insurer: str, reader: PolicyWordingReader | None
                          ) -> tuple[list[PolicyFinding], str | None]:
    """Returns (findings, error). No reader (offline) -> no findings, explained."""
    terms = procedure_terms(procedure)
    url = record.get("policy_wording_url") or ""
    if not terms or not url:
        return [], None
    if reader is None:
        return [], "policy wording not read in offline mode"
    try:
        text = await reader.text(url)
    except Exception as exc:  # noqa: BLE001 - wording is optional evidence
        return [], f"policy wording could not be read ({type(exc).__name__})"
    if len(text) < 500:
        return [], "policy wording PDF had no extractable text"
    findings = []
    for state, excerpt in scan_wording(text, procedure or "", terms):
        claim = ClaimType.POLICY_WAITING_PERIOD if state == InsuranceState.WAITING_PERIOD_APPLIES else ClaimType.POLICY_EXCLUSION
        findings.append(PolicyFinding(plan=record["name"], procedure=procedure or "", state=state, evidence=Evidence(
            claim_type=claim, claim_value=procedure or "", subject=record["name"],
            source_name=f"{record['name']} policy wording (IRDAI, UIN {record.get('uin')})", source_url=url,
            source_type=SourceType.OFFICIAL_POLICY_DOCUMENT, excerpt=excerpt[:400],
            retrieved_at=datetime.now(timezone.utc), reliability=Reliability.MEDIUM, insurer=insurer,
            plan=record["name"])))
    return findings, None
