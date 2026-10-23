# Known limitations

1. **ASI:One behaviour has not been observed yet.** The mailbox connection is a manual step, so card rendering, attachment URLs and how `sender` maps to a conversation were not observed during the build.
2. **ASI1 was not exercised against the real API.** No key was available. The client, its validation and its fallback are tested with a mocked OpenAI-compatible client, and without a key the system runs on rules only.
3. **Live insurer data needs an operator import.** Real insurers' network locators aren't scraped, for terms and CAPTCHA reasons. Until an official list is imported, live insurance results are `SOURCE_UNAVAILABLE`.
4. **OpenStreetMap coverage is uneven.** Many large hospitals have no `healthcare:speciality` or `website` tag. Live results therefore often show "directory-listed" or "name suggests" signals rather than verified ones, and a well-known hospital may be missing from results.
5. **No OCR.** Image reports are acknowledged and the user is asked to paste the text. Scanned PDFs without a text layer are handled the same way.
6. **Care knowledge is curated, not comprehensive.** About 25 conditions and 11 symptom groups are mapped. Anything else depends on ASI1, if configured, or a clarifying question.
7. **Emergency detection is pattern-based and conservative.** It can over-trigger, which is acceptable. It cannot catch every emergency phrasing, so the disclaimer and 112 guidance stay visible.
8. **Ranking weights are product choices**, not validated clinical-quality measures. The score shows evidence fit, not hospital quality.
9. **No appointments, inquiries or payments.** The only action is saving the approved shortlist with its evidence. Booking would need a real provider API; Payment Protocol would need a genuine paid service.
10. **Single-host deployment.** The research agents talk to the coordinator over localhost routes. Multi-host deployment would use public endpoints and Almanac resolution, which is already the resolver fallback.
11. **SQLite.** This is fine for the MVP. Use PostgreSQL via `DATABASE_URL` for concurrency at scale.
