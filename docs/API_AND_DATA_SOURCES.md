# APIs and data sources

| Source | Mode | What it can prove | Source type → reliability | Access rules followed |
|---|---|---|---|---|
| Synthetic hospital profiles (`data/fixtures/hospitals.json`) | fixture | Synthetic existence, location and services | `synthetic_fixture` → high (within the demo world) | Fictional. Labelled in every reply. `fixture://` URLs. |
| Synthetic insurer data (`data/fixtures/insurers.json`) | fixture | Synthetic network listings, de-listings, plan rules | `synthetic_fixture` | Fictional insurers only. Real insurer names return "not checked". |
| National Health Portal hospital directory (`data/catalog/india_hospitals.json.gz`, built by `scripts/import_nhp_hospitals.py` from data.gov.in `hospital_directory.csv`) | both | ~30,000 registered facilities: existence, district/state, pincode, phone, coordinates (~10,700), beds, facilities, self-declared specialties (~930) | `official_government`. Existence/location: high. Specialty: **directory signal only** (medium), never "verified". | Government Open Data License – India. Input SHA-256 recorded in the file. Snapshot can be out of date; every reply says to call before visiting. |
| OpenStreetMap via **Overpass API** (`overpass-api.de/api/interpreter`) | live | Mapped hospitals / specialty clinics within 15 km of the city centre, with `healthcare:speciality`, phone, website, beds, emergency tags | `community_directory` → medium | ≤1 request/s, identifying User-Agent, 6 h cache, single bounded query per city, fetcher pinned to the Overpass host. City centre from the directory (or one Nominatim lookup). |
| IRDAI health-product register (`data/catalog/insurance_products.json`) | both | A product with this name/UIN is registered by this insurer; link to its official policy wording | `official_government` identity | Registration ≠ on sale ≠ your cover. |
| Official policy wording PDF (irdai.gov.in, from the register) | live / real insurers | The wording mentions the procedure in a waiting-period or exclusion clause (excerpt quoted) | `official_policy_document` → medium (heuristic clause location) | Host-pinned to irdai.gov.in, 12 MB cap, first 60 pages. Always "confirm with insurer". |
| OpenStreetMap via Nominatim `/search` (legacy source, kept for compatibility) | live | A facility exists, location, community `healthcare:speciality` tags | `community_directory` → medium. Specialty from a tag is **not** treated as verified. | OSMF Nominatim usage policy: ≤1 request/s (`RateLimiter(1.1)`), identifying User-Agent (`HTTP_USER_AGENT`), 6 h cache, attribution shown ("OpenStreetMap contributors, ODbL"). Fetcher pinned to `nominatim.openstreetmap.org`. |
| Hospital official website (from the OSM `website` tag) | live | The hospital advertises the specialty (keyword in the page text, excerpt kept) | `official_hospital_site` → high | robots.txt respected, SSRF checks on every hop, 3 MB cap, 15 s timeout. Homepage only, no crawling. |
| Insurer official network list (CSV imported by the operator) | live | The hospital appears in the insurer's network list | `official_insurer_directory` → high | Downloaded manually from the insurer's official site. URL and date recorded in the file header. No portal scraping, CAPTCHA, OTP or login access. |
| ASI1 (`https://api.asi1.ai/v1`, model `asi1`) | both | Nothing. It only extracts and rephrases. | n/a | The key is read from env only. Identifiers are redacted before sending. Output is validated and grounded. |

## What each claim needs before CareCompass calls it "verified"

| Claim | Accepted source types |
|---|---|
| Specialty / service | `official_hospital_site`, or `synthetic_fixture` in demo mode |
| Network listing / absence, cashless | `official_insurer_directory` or `synthetic_fixture` |
| Exclusion / waiting period | `official_policy_document` or `synthetic_fixture` |

Weaker sources still count, but they are labelled. For example: "listed in public directory (unconfirmed)" or "name suggests service (unverified)".

## Why there is no live Star Health / HDFC ERGO / etc. lookup

These insurers' network locators are interactive web apps, often with CAPTCHA, and their terms do not grant automated access. Calling undocumented endpoints would break the hackathon rules ("no fake integrations") and the insurers' terms. The integration boundary is ready instead: drop an official list into `data/insurer_networks/`, or implement `InsurerSource.research()` against an authorised API or a partner agreement.
