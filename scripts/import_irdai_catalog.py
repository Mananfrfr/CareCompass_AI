"""Import factual product identities from IRDAI, never infer sale/coverage status.

Run manually: python scripts/import_irdai_catalog.py --pages 8
Only public table metadata is stored, not policy text. Requests are sequential.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

URL = "https://irdai.gov.in/health-insurance-products"
PREFIX = "_com_irdai_document_media_IRDAIDocumentMediaPortlet_"


def parse_products(html: str, source_url: str, checked_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for table in soup.select("table"):
        headers = [c.get_text(" ", strip=True) for c in table.select("th")]
        if "UIN" not in headers or "Product Name" not in headers:
            continue
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) != len(headers):
                continue
            row = dict(zip(headers, [c.get_text(" ", strip=True) for c in cells]))
            uin = row.get("UIN", "").strip()
            name = row.get("Product Name", "").strip()
            # Keep only identifiable health products; travel/PA and malformed rows are not padding.
            if not re.fullmatch(r"[A-Z0-9/-]{10,45}", uin) or "HL" not in uin or not name:
                continue
            links = [urljoin(URL, a["href"]) for a in tr.select("a[href]") if "/document" in a["href"]]
            result.append(dict(
                catalog_id="irdai-" + uin, name=name, provider=row["Name of the Insurer"],
                uin=uin, record_type=row.get("Type Of Product", "unknown"),
                financial_year=row.get("Financial Year"), approval_date=row.get("Date of Approval"),
                registry_status=row.get("Archive / Non Archive"),
                verification_status="official_registry_identity", source_url=source_url,
                source_sha256=hashlib.sha256(html.encode()).hexdigest(), checked_at=checked_at,
                policy_wording_url=links[0] if links else None,
                current_sale_status="unknown", patient_eligibility="not_assessed",
                treatment_coverage="not_assessed", network_status="not_assessed",
            ))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("data/catalog/insurance_products.json"))
    args = parser.parse_args()
    records = {}
    with httpx.Client(timeout=40, follow_redirects=True, headers={"User-Agent": "CareCompass/0.2 public product catalog research"}) as client:
        for page in range(1, args.pages + 1):
            response = client.get(URL, params={"p_p_id": "com_irdai_document_media_IRDAIDocumentMediaPortlet",
                                              "p_p_lifecycle": "0", PREFIX + "delta": "100", PREFIX + "cur": str(page)})
            response.raise_for_status()
            rows = parse_products(response.text, str(response.url), datetime.now(timezone.utc).isoformat())
            before = len(records)
            records.update({r["uin"]: r for r in rows})
            print(f"page {page}: {len(rows)} health identities, {len(records)} unique UINs", flush=True)
            if len(records) == before:
                break
            time.sleep(1.1)
    if not records:
        raise RuntimeError("No validated rows; existing catalog preserved")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"description": "IRDAI registered health product identities. Registration is not current sale or coverage confirmation.",
               "records": list(records.values())}
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
