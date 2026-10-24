# Narrow live-data review: Jaipur / Niva Bupa

Reviewed 24 October 2026 through the public insurer directory and hospital website. This review is separate from the synthetic ASI:One demonstration; it is not an imported production dataset.

## One concrete candidate

- Insurer source: https://rules.nivabupa.com/hospital-network/ — select Jaipur. The browser returned 219 matches. The Manipal entry links to https://rules.nivabupa.com/hospital-network/detail/61952 . This is an insurer-published listing, not a broker's copied list.
- Listed entity: Manipal Health Enterprises Pvt. Ltd., Sector 5, Vidhyadhar Nagar, Jaipur. The directory labels it a preferred hospital.
- Specialty source: https://www.manipalhospitals.com/jaipur/specialities/orthopaedics/ — the hospital advertises orthopaedics and discusses sports injuries and ligament care. This supports an advertised service, not clinical quality or patient-specific suitability.
- Branch cross-check: the hospital footer identifies Sector 5, Main Sikar Road, Vidhyadhar Nagar, Jaipur.
- Unresolved source discrepancy: the insurer lists PIN 302013; the hospital footer lists 302039. Preserve both and confirm directly before treating exact branch matching as verified.

## Evidence limits

The insurer listing and hospital service are visible on primary-source websites. They do not establish policy eligibility, appointment availability, cashless authorization for a particular claim, or treatment coverage.

Niva Bupa's website terms (https://www.nivabupa.com/help-centre/help-terms-and-condition.html) reserve copyright and database rights. This review records a narrow factual observation with links. No bulk directory was downloaded or republished, and no dataset-reuse licence has been obtained. The public browser interface was used without bypassing authentication, CAPTCHA or access controls.

## Implementation boundary

Live OpenStreetMap discovery passed its live test. The app supports operator-imported official insurer CSV files, but no permission-confirmed insurer dataset is imported. Network status remains not checked when no source exists. Never mark a partial sample complete for Jaipur.

For production use, obtain permitted insurer data, resolve branch identifiers, and add an expiry/revalidation policy. The demonstrated workflow remains explicitly synthetic.
