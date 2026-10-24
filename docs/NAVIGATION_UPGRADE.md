# India navigation upgrade

Implemented in October 2026. This document distinguishes imported identities from
patient-specific verification; counts are not claims of insurance coverage.

## Catalogs

- `data/catalog/insurance_products.json`: 606 unique health-product UINs from the
  public IRDAI register; 577 distinct normalized provider/name combinations.
  Includes historical versions, group products and add-ons. Active sale, eligibility,
  exclusions, waiting periods and hospital networks remain unknown unless separately verified.
- `data/staging/policy_seed_200.json`: original user-supplied research candidates.
  Not loaded into patient-facing recommendations. Variants and programs are not
  automatically treated as separate verified insurance policies.
- `data/catalog/hospitals.json`: 112 public-directory facility identities from Delhi
  government and Maharashtra DMER. These records do not prove treatment capability.
- `data/catalog/clinical_hospitals.json`: successfully retrieved, reviewed official
  department facts. Currently AIIMS Nagpur and AIIMS Bilaspur; Patna refresh failed
  and those facts were not imported. No accreditation, prices or networks invented.

Refresh commands (network required):

```powershell
python scripts/import_irdai_catalog.py --pages 8
python scripts/import_government_hospitals.py
python scripts/refresh_clinical_profiles.py
```

## Recommendation behavior

The production workflow now uses a fixed 100-point evidence model: specialty 35,
procedure/facility capability 20, quality 15, insurance 15, affordability 10,
same-city practicality 5. Missing dimensions score zero, without renormalization.
This is a product scoring model, not clinically validated or an official rating.

Current authoritative specialty evidence and every requested capability must pass
before ranking. Capability facts are bound to the physical facility ID and the
requested specialty. Dialysis needs dialysis and nephrology support; childhood
leukemia needs paediatric care, paediatric oncology and haematology. These are
navigation checks, not a comprehensive clinical safety certification.

Clinical evidence expires after 180 days; network/price evidence after 30 days.
Future dates fail closed. Accreditation requires an explicit unexpired validity
date and suitable scope. Hospital marketing alone earns no quality points.
Budget comparison requires a stated budget and matching per-session/procedure/
consultation units; conflicting higher quotes cannot be discarded. A network
listing earns at most 10 of 15 points, never establishes treatment approval.

Tiers: A >=85 with at least two valid quality indicators and no conflicts; B >=70;
C >=55. Below 55 or a failed capability gate is not shown as a qualified option.
At most eight qualified options are returned. Never pad a short list to reach five.
The independent result verifier repeats the capability checks after downgrades.

In ASI:One, `policy search Health Companion` searches official product identities.
The existing conversational shortlist, cards, approval and verified save remain.
Real catalogs are used in `CARECOMPASS_DATA_MODE=live`. Fixture mode remains an
explicitly fictional, reproducible test/demo path.

## Remaining data work

This release does not establish nationwide clinical coverage, automatic government
eligibility, 200 current sale/coverage-verified products, guaranteed cashless care,
or real-time bed/appointment availability. Most directory facilities lack the
clinical detail required to qualify. Expand reviewed branch evidence and obtain
permitted current insurer/package data before claiming those capabilities.

Offline regression checkpoint: 120 passed, 2 live/agent tests deselected.
