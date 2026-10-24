"""Import public directory identities, never infer specialty from a hospital name."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

DELHI = "https://delhi.gov.in/page/hospitals-delhi"
DMER = "https://dmer.maharashtra.gov.in/english/medical-colleges-and-hospitals/"


def main():
    records = []
    with httpx.Client(timeout=35, follow_redirects=True) as client:
        for url in (DELHI, DMER):
            response = client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for tr in soup.select("table tr"):
                cells = tr.find_all("td", recursive=False)
                if not cells or not cells[0].get_text(strip=True).isdigit():
                    continue
                if url == DELHI and len(cells) == 3:
                    names = [cells[1].get_text(" ", strip=True)]
                    city, district, state = "Delhi", "Delhi", "Delhi"
                elif url == DMER and len(cells) == 5:
                    names = list(cells[4].stripped_strings)
                    city, district, state = cells[2].get_text(strip=True), cells[1].get_text(strip=True), "Maharashtra"
                else:
                    continue
                for name in names:
                    if "rural health" in name.lower():
                        continue  # different locality and care setting; needs separate verification
                    branch_city = name.rsplit(",", 1)[1].strip() if url == DMER and "," in name else city
                    hid = "gov-" + hashlib.sha256((name + branch_city).encode()).hexdigest()[:12]
                    records.append(dict(hospital_id=hid, name=name, city=branch_city, district=district,
                                        state=state, branch=name, address="", ownership_type="public" if url == DMER else "unknown",
                                        source_url=url, checked_at=datetime.now(timezone.utc).isoformat(),
                                        identity_status="directory_listing_only", capabilities=[], evidence=[]))
    records = list({r["hospital_id"]: r for r in records}.values())
    if len(records) < 50:
        raise RuntimeError("Directory layout changed; refusing incomplete replacement")
    path = Path("data/catalog/hospitals.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"records": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Imported {len(records)} government-directory facility identities; no clinical capabilities inferred.")


if __name__ == "__main__":
    main()
