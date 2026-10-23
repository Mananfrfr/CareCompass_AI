# Fetch-A-Thon 3.0 submission: CareCompass AI

**Event:** Fetch-A-Thon 3.0, 24 October 2026. Final submission is due at 16:30 IST.
**Challenge:** ASI:One Agent Challenge — From Intent to Action.

## Short description (for Devpost)

**CareCompass AI** turns one message about a health concern into an evidence-backed hospital shortlist inside ASI:One. The message can name a known condition, describe symptoms, or include the key lines of a medical report.

- **Coordinator agent:** checks for emergencies first, then works out which hospital service is relevant. This is navigation, not diagnosis.
- **Specialist agents:** the Coordinator sends a Hospital Verification Agent and an Insurer Research Agent to research in parallel.
- **Evidence handling:** the evidence is matched, contradictions are detected (for example, one insurer source lists a hospital and another de-lists it), and options are ranked explainably. An independent verifier removes any unsupported claim.
- **Approval and action:** the user picks from Interactive Cards and approves. CareCompass then saves the shortlist and its evidence, reads the record back to verify it, and returns a real reference ID.

It never says a treatment is "covered". Network listing, plan exclusions and cashless status stay separate and sourced.

**Target users:** patients and families in India who are choosing a hospital under health insurance, especially those unfamiliar with medical terminology.

## Mandatory requirements

| Requirement | How it is met | Status |
|---|---|---|
| ≥1 agent registered on Agentverse | Coordinator: `mailbox=True`, `publish_agent_details=True`. Almanac API registration succeeds. | ✅ registration verified in logs · 👤 mailbox Connect pending |
| Agent Chat Protocol | `Protocol(spec=chat_protocol_spec)`, `publish_manifest=True`, acknowledgements, multi-turn | ✅ manifest published (log) · ✅ local ACP test 12/12 |
| Discoverable/usable in ASI:One | Agentverse profile README + keywords (`docs/AGENT_PROFILE.md`) | 👤 verify after mailbox Connect |
| Meaningful tool execution / multi-agent | 3 uAgents with typed protocols. Live OSM data. DB action with read-back verification. | ✅ |
| Workflow completes inside ASI:One | Cards + text fallback, no external frontend | 👤 record it in a shared chat |
| Public GitHub repo with instructions | This repository (README, docs, tests) | 👤 push and make public |

## Bonus criteria addressed

- **Multi-agent collaboration:** parallel, typed, timed-out and retried requests to two specialist agents, with partial-result handling.
- **Interactive Cards:** carousel → detail → review, with JSON or prose selections and version-checked approvals.
- **Reliability:** bounded retries, idempotent actions, a read-after-write check, SOURCE_UNAVAILABLE semantics and an explicit state machine.
- **Real-time data:** live mode queries OpenStreetMap and hospitals' own websites, with provenance.
- **Continued operation:** Dockerfile, a SQLAlchemy URL for PostgreSQL, and a pluggable official insurer data import.
- **Payment Protocol:** deliberately *not* used, because there is no genuine paid transaction yet (see LIMITATIONS).

## Submission checklist (fill on event day — do not invent values)

- [ ] Public GitHub repository URL: `______________________`
- [ ] Agentverse profile URL, coordinator (CareCompass AI): `______________________`
- [ ] Agentverse profile URL(s), research agents (optional): `______________________`
- [ ] Public ASI:One shared chat URL showing the full workflow: `______________________`
- [ ] Demo video (3–5 min, follows `docs/DEMO_SCRIPT.md`): `______________________`
- [ ] README agent names and addresses match `python scripts/run_agents.py --addresses`
- [ ] README contains both badges (`innovationlab`, `hackathon`) ✅ already present
- [ ] `.env` is NOT committed (`git status` shows it ignored)
- [ ] `python -m pytest` is green on the final commit

## Manual steps that need you (👤)

1. **ASI1 key (optional but recommended):** create a key at https://asi1.ai/dashboard/api-keys and add it to `.env` as `ASI1_API_KEY=`. Then run the demo once and confirm that the log line reads `ASI1: configured`.
2. **Agentverse mailbox:** follow `docs/AGENTVERSE_DEPLOYMENT.md` step 4.
3. **ASI:One test and share link:** follow `docs/AGENTVERSE_DEPLOYMENT.md` step 6.
4. **GitHub:** create a public repo and push. Then check that `.env` and `data/*.db` are absent from the repo.
5. **Video:** record it following `docs/DEMO_SCRIPT.md`.

## 60-second pitch

"Choosing a hospital under insurance in India means guessing the specialty, searching hospitals, and reading insurer lists that often disagree. CareCompass does that work inside ASI:One. You send one message. Two specialist agents research hospitals and insurer networks in parallel. CareCompass matches their evidence, flags contradictions instead of hiding them, and ranks options with a score you can inspect. A deterministic verifier removes anything we can't source, so it never says 'covered' and never invents a hospital. When you approve, it saves the shortlist and evidence, reads the record back to prove it's there, and gives you a real reference. If something breaks — an insurer site is down, or a database write fails — it tells you exactly what wasn't checked. That's what we mean by trustworthy intent-to-action."
