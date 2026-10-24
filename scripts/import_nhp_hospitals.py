"""Build data/catalog/india_hospitals.json.gz from the National Health Portal hospital directory.

Source: "Hospital Directory (National Health Portal)", Ministry of Health & Family Welfare,
published on the Open Government Data Platform India (https://data.gov.in, Government Open
Data License - India). Download `hospital_directory.csv` from
https://data.gov.in/catalog/hospital-directory-national-health-portal and run:

    python scripts/import_nhp_hospitals.py path/to/hospital_directory.csv

The output keeps only fields CareCompass uses, normalises specialties to CareCompass service
keys, and records the SHA-256 of the input so the snapshot can be audited. The directory is a
government listing: it proves that a facility was registered, and its specialty column is a
*self-declared directory listing*, not confirmation that a department is currently running.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.research.india_directory import DIRECTORY_PATH, SOURCE_URL, specialties_from_text  # noqa: E402

EMPTY = {"", "0", "na", "n/a", "nil", "none", "-", "null"}


def clean(value: str | None) -> str:
    value = (value or "").replace("\\n", " ").replace("\n", " ")
    value = " ".join(value.split()).strip(" ,;")
    return "" if value.lower() in EMPTY else value


def coords(raw: str) -> tuple[float, float] | tuple[None, None]:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", raw or "")
    if not m:
        return None, None
    lat, lon = float(m[1]), float(m[2])
    # India bounding box; anything else is a data-entry error.
    if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
        return None, None
    return round(lat, 6), round(lon, 6)


def to_int(raw: str) -> int | None:
    m = re.search(r"\d+", raw or "")
    return int(m[0]) if m and clean(raw) else None


def build(csv_path: Path) -> dict:
    raw = csv_path.read_bytes()
    rows = list(csv.DictReader(raw.decode("utf-8", errors="replace").splitlines()))
    records = []
    for row in rows:
        name = clean(row.get("Hospital_Name"))
        state = clean(row.get("State"))
        district = clean(row.get("District"))
        if not name or not district:
            continue
        lat, lon = coords(row.get("Location_Coordinates", ""))
        discipline = clean(row.get("Discipline_Systems_of_Medicine"))
        declared = clean(row.get("Specialties"))
        facilities = clean(row.get("Facilities"))
        rec = {
            "id": f"nhp-{clean(row.get('Sr_No')) or hashlib.sha1(name.encode()).hexdigest()[:8]}",
            "n": name,
            "s": state,
            "d": district,
            "t": clean(row.get("Town")) or clean(row.get("Subdistrict")),
            "a": clean(row.get("Address_Original_First_Line")) or clean(row.get("Location")),
            "p": clean(row.get("Pincode")),
            "lat": lat, "lon": lon,
            "ph": clean(row.get("Telephone")) or clean(row.get("Mobile_Number")),
            "em": clean(row.get("Emergency_Num")),
            "w": clean(row.get("Website")),
            "ct": clean(row.get("Hospital_Care_Type")),
            "cat": clean(row.get("Hospital_Category")),
            "ds": discipline,
            "sp": specialties_from_text(declared),
            "spr": declared[:400],
            "f": facilities[:300],
            "acc": clean(row.get("Accreditation"))[:120],
            "b": to_int(row.get("Total_Num_Beds", "")),
            "er": clean(row.get("Emergency_Services"))[:60],
        }
        records.append({k: v for k, v in rec.items() if v not in ("", None, [])})
    return {
        "source": "Hospital Directory (National Health Portal), MoHFW - Open Government Data Platform India",
        "source_url": SOURCE_URL,
        "license": "Government Open Data License - India (GODL)",
        "input_file": csv_path.name,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "notice": ("Government directory snapshot. Listing proves registration in the directory, not current "
                   "department availability. Specialties are self-declared directory entries."),
        "records": records,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, default=DIRECTORY_PATH)
    args = ap.parse_args()
    data = build(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    with_sp = sum(1 for r in data["records"] if r.get("sp"))
    geo = sum(1 for r in data["records"] if r.get("lat"))
    print(f"wrote {len(data['records'])} hospitals ({with_sp} with declared specialties, {geo} geocoded) -> {args.out}")


if __name__ == "__main__":
    main()
