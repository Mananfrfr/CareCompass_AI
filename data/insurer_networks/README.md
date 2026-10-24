# Official insurer network lists (live mode)

CareCompass does **not** scrape insurer portals: most use CAPTCHA/OTP or terms that forbid automation.
Instead, an operator downloads a network-hospital list **from the insurer's official website** and
saves it here as CSV. The header records where it came from, so every network claim stays traceable.

```csv
# insurer: Star Health
# source_url: https://<the official page you downloaded the list from>
# retrieved_at: 2026-10-20
# complete_for_cities: Jaipur
name,city,address,postcode,cashless
Example Hospital Name,Jaipur,"Street, Area",302017,yes
```

Rules enforced by the loader (`app/research/insurer_sources.py`):
- Files without `insurer` and an `https://` `source_url` are ignored.
- `retrieved_at` must be a valid date no more than 30 days old and not in the future. File modification time is never substituted for source verification. This is an operational freshness limit, not an insurer guarantee.
- Empty lists and rows missing hospital name or city are rejected; they cannot establish network absence.
- `complete_for_cities` lists the cities for which the file is the insurer's full list. Absence from
  a complete list becomes `NETWORK_NOT_FOUND`; otherwise absence is only `NETWORK_UNCERTAIN`.
- A listing proves network membership only, never plan eligibility or claim approval.

Only `*.csv` files are loaded; `*.csv.example` files are ignored.
