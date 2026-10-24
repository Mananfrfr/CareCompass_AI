"""Refresh a small reviewed set of branch-specific official clinical pages.

Mappings are human-reviewed service facts, not inferred from hospital reputation.
Missing service text fails closed. Page reachability does not establish availability
of appointments, equipment uptime, accreditation, treatment price or insurance.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

PROFILES = [
    ("cmc-ranipet", "CMC Vellore - Ranipet Campus", "Ranipet", "Tamil Nadu", "oncology",
     "https://www.cmch-vellore.edu/clinical-haematology/", ["paediatric", "leukaemia", "ranipet"],
     ["paediatric_care", "paediatric_oncology", "haematology", "outpatient_consultation"],
     "Clinical Haematology at Ranipet lists paediatric leukemia care, chemotherapy and outpatient clinics."),
    ("aiims-nagpur", "AIIMS Nagpur", "Nagpur", "Maharashtra", "nephrology",
     "https://aiimsnagpur.edu.in/nephrology-current-available-services", ["dialysis"],
     ["dialysis", "nephrology_support", "outpatient_consultation"], "Department lists dialysis services and a nephrology outpatient clinic."),
    ("aiims-nagpur", "AIIMS Nagpur", "Nagpur", "Maharashtra", "ophthalmology",
     "https://aiimsnagpur.edu.in/ophthalmologycurrentlyavailableservices", ["cataract", "phaco"],
     ["cataract_surgery", "outpatient_consultation"], "Department lists cataract surgery by phacoemulsification and SICS."),
    ("aiims-patna", "AIIMS Patna", "Patna", "Bihar", "nephrology",
     "https://aiimspatna.edu.in/nephrology", ["dialysis"],
     ["dialysis", "nephrology_support"], "Nephrology service includes hemodialysis and peritoneal dialysis patients."),
    ("aiims-patna", "AIIMS Patna", "Patna", "Bihar", "ophthalmology",
     "https://aiimspatna.edu.in/ophthalmology", ["cataract", "surgeries"],
     ["cataract_surgery", "outpatient_consultation", "paediatric_care"], "Ophthalmology lists cataract surgery and paediatric eye surgery."),
    ("aiims-bilaspur", "AIIMS Bilaspur", "Bilaspur", "Himachal Pradesh", "nephrology",
     "https://www.aiimsbilaspur.edu.in/node/1961", ["dialysis unit", "operational"],
     ["dialysis", "nephrology_support"], "Nephrology page reports an operational dialysis unit."),
]


def main():
    records = {}
    failures = []
    with httpx.Client(timeout=25, follow_redirects=True) as client:
        for hid, name, city, state, specialty, url, terms, caps, summary in PROFILES:
            try:
                response = client.get(url)
                response.raise_for_status()
                text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True).lower()
                if not all(t in text for t in terms):
                    raise ValueError("reviewed service text no longer present")
            except Exception as exc:
                failures.append({"url": url, "error": type(exc).__name__})
                continue
            stamp = datetime.now(timezone.utc).isoformat()
            record = records.setdefault(hid, dict(hospital_id=hid, name=name, city=city, state=state,
                                                 branch=name, ownership_type="public" if hid.startswith("aiims-") else "unknown", source_url=url,
                                                 checked_at=stamp, website=url, evidence=[]))
            common = dict(subject=name, subject_id=hid, source_name=f"{name} official department page",
                          source_url=url, source_type="official_hospital_site", excerpt=summary,
                          retrieved_at=stamp, reliability="high", scope=specialty)
            record["evidence"].append(dict(claim_type="specialty", claim_value=specialty, **common))
            record["evidence"].extend(dict(claim_type="capability", claim_value=cap, **common) for cap in caps)
            if hid == "cmc-ranipet":
                record["address"] = "CMC Vellore Ranipet Campus, Kilminnal Village, Ranipet, Tamil Nadu"
                record["postcode"] = "632517"
    path = Path("data/catalog/clinical_hospitals.json")
    if not records:
        raise RuntimeError(f"No pages verified; existing file preserved. {failures}")
    path.write_text(json.dumps({"records": list(records.values()), "failed_refreshes": failures}, indent=2), encoding="utf-8")
    print(f"Verified {len(records)} facilities, {sum(len(r['evidence']) for r in records.values())} service facts; failures: {failures}")


if __name__ == "__main__":
    main()
