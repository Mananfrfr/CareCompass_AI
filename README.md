# CareCompass AI

**From Medical Concern to Coordinated Care.** One request gets you a smarter hospital choice, checked insurance information and a real action.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)

![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

CareCompass is a multi-agent healthcare-navigation system built on Fetch.ai uAgents and the Agent Chat Protocol, and it runs entirely inside **ASI:One**. A user describes a health concern, a known condition or a medical report in one message. CareCompass checks it for emergencies, works out which hospital service is relevant, and sends **two specialist agents** to research hospitals and insurer networks. It then matches their evidence, detects contradictions, ranks options explainably and verifies every claim. Finally it shows an Interactive Card shortlist and, **only after the user approves**, saves the shortlist and its evidence. It reads the saved record back to verify it and returns a real reference ID.

> CareCompass is a navigation assistant. It does not diagnose, and it never says a treatment is "covered". Network listing, plan exclusions and cashless availability are tracked as separate, evidence-backed states.

---

## Why it matters

In India, a patient with an ACL tear, a kidney stone or just "knee pain for two weeks" has to work out several things alone:

- which specialty to approach,
- which hospitals in their city offer it,
- whether those hospitals appear in their insurer's network,
- whether their plan excludes the procedure.

This information is scattered across hospital sites, insurer PDFs and directories, and it often contradicts itself. CareCompass turns one message into an evidence-backed, explainable shortlist. When the evidence is missing or conflicting, it says so plainly.

## What makes it different

| | |
|---|---|
| **Minimal input** | One message usually starts the search. CareCompass asks only for what the next step strictly needs (typically just the city). Insurance is optional. |
| **Medical-context aware, not diagnostic** | It extracts facts from a report and keeps their status: *stated*, *hedged* ("possible…") or *ruled out* ("meniscus intact"). Each finding links to the exact sentence it came from. |
| **Real multi-agent research** | The Coordinator sends typed requests to a **Hospital Verification Agent** and an **Insurer Research Agent** in parallel, using real uAgent messaging with timeouts and bounded retries. |
| **Evidence-aware matching** | Every claim is an `Evidence` record with source URL, source type, excerpt and retrieval time. Entity resolution matches "ABJH" or "Aravali Bone and Joint Hosp." to the right hospital, but never merges different branches. |
| **Conflict detection** | If one insurer source lists a hospital and another de-lists it, the result is `SOURCES_CONFLICT` plus `NETWORK_UNCERTAIN`, and the user sees both sources. |
| **Explainable ranking** | The suitability score shows its per-dimension breakdown and is kept separate from evidence confidence. The weights are configurable product choices, not clinical quality. |
| **Independent verifier** | A deterministic verifier re-derives each claim. It rejects citations the research agents never returned, downgrades unsupported network claims, and removes "covered", "guaranteed" or "booked" language. |
| **Human-approved, verified action** | Review card → approval (hash of the exact payload) → a single-transaction save → read-back verification → confirmation ID. The save is idempotent, so a repeated approval never writes twice. |
| **Graceful failure** | An insurer outage gives "not checked", never "out of network". If the hospital agent is down, the user gets `retry`. If a DB write fails, the user gets a bounded retry and no false confirmation. |

## Architecture

```mermaid
flowchart TD
    U[User in ASI:One] -->|Agent Chat Protocol| C[CareCompass Coordinator uAgent<br/>mailbox · Agentverse]
    C --> S[Safety router<br/>deterministic red flags]
    S -->|emergency| E[112 / 108 guidance - stop]
    S --> I[Intent + report understanding<br/>rules + ASI1, grounded]
    I --> Q[Missing-info engine]
    Q -->|ask only what is needed| U
    Q --> P{{parallel typed uAgent messages}}
    P --> H[Hospital Verification Agent<br/>fixtures or OpenStreetMap + official sites]
    P --> N[Insurer Research Agent<br/>fixtures or official network lists]
    H --> M[Evidence matching + entity resolution]
    N --> M
    M --> R[Decision rules R1-R10]
    R --> K[Explainable ranking]
    K --> V[Independent verifier]
    V --> CARD[Carousel → Detail → Review cards<br/>+ full text fallback]
    CARD -->|approve| X[Action executor<br/>idempotent save]
    X --> DB[(SQLite: cases, evidence,<br/>approvals, executions, audit)]
    DB -->|read-back + hash check| OK[Confirmation CC-XXXXXXXX]
    OK --> U
```

The full design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the state machine is in [docs/STATE_MACHINE.md](docs/STATE_MACHINE.md).

## Agents

| Agent | Role | Protocols | Address |
|---|---|---|---|
| **CareCompass AI** (Coordinator) | Public ASI:One agent. Handles conversation, safety, orchestration, cards, approval and action. | `AgentChatProtocol` 0.3.0 (manifest published), CareCompass research protocols (client) | `agent1qg0ls5xx5xff8zs8d2xpjr4ye92tymamcyllvw2u2kvtq7k7t8uv5jh0ppg` * |
| **Hospital Verification Agent** | Independent hospital discovery and specialty/location evidence. | `CareCompassHospitalResearch` 0.1.0 | `agent1qv60axczyzymf4zwqyjfzm64g3ycftwzsgulm3v34waurnrjdfa7c5w004j` * |
| **Insurer Research Agent** | Network listings, de-listings, plan exclusions and waiting periods, with sources. | `CareCompassInsurerResearch` 0.1.0 | `agent1qtw9t4wyq9nxalc88ncdn7067qwgku08r06phala7m2d3j5ngatqsfyuskl` * |

\* These addresses come from the seeds in the maintainer's local `.env`. A new `--init-env` produces different addresses. Print yours with `python scripts/run_agents.py --addresses`. **Agentverse profile URL:** _to be added after the mailbox is connected (manual step, see below)._

## Quick start

Requires Python 3.10+ (tested on 3.12).

```bash
git clone <your-repo-url> carecompass-ai && cd carecompass-ai
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_agents.py --init-env      # writes .env with fresh agent seeds (git-ignored)
# optional: add ASI1_API_KEY=... to .env (https://asi1.ai/dashboard/api-keys)
```

| Goal | Command |
|---|---|
| Run all tests (incl. the real 3-agent ACP test on ports 8000-8002, 8010) | `python -m pytest` |
| Live-data test (real OpenStreetMap) | `python -m pytest -m live` |
| Real ACP + multi-agent journey with JSON report | `python scripts/test_protocol.py` |
| Scripted conversations in the terminal | `python scripts/demo_scenarios.py` |
| Chat in the terminal | `python scripts/demo_scenarios.py --interactive` |
| Measure metrics | `python scripts/benchmark.py --runs 20` |
| **Start the agents for ASI:One** | `python scripts/run_agents.py` |
| Live data instead of synthetic | set `CARECOMPASS_DATA_MODE=live` in `.env` |

### Connect to Agentverse and ASI:One (manual, needs your account)

1. Run `python scripts/run_agents.py`. The coordinator log prints an **Agent inspector** link and `Manifest published successfully: AgentChatProtocol`.
2. Open the inspector link while signed in to [agentverse.ai](https://agentverse.ai), then click **Connect → Mailbox**. The log then stops showing `Agent mailbox not found`.
3. On the agent's Agentverse page, check the name, description, README (from [docs/AGENT_PROFILE.md](docs/AGENT_PROFILE.md)) and the *AgentChatProtocol* badge.
4. In [asi1.ai](https://asi1.ai), search for "CareCompass" or message the agent address directly, then run the demo in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
5. Share the chat to get a public ASI:One URL for the submission.

The detailed runbook is in [docs/AGENTVERSE_DEPLOYMENT.md](docs/AGENTVERSE_DEPLOYMENT.md). Keep the process running, because the local agents serve the mailbox. The Dockerfile runs the same three agents on any always-on host.

## Environment variables

See [.env.example](.env.example). The key ones:

- `ASI1_API_KEY`: optional. Without it, CareCompass falls back to its deterministic parser.
- `CARECOMPASS_DATA_MODE`: `fixture` or `live`.
- `*_SEED`: the agent identities. Keep them secret.
- `COORDINATOR_CONNECTIVITY`: `mailbox` or `local`.
- `DATABASE_URL`, `RESEARCH_TIMEOUT_S`, `RESEARCH_MAX_ATTEMPTS`, `ACTION_MAX_ATTEMPTS`, `HTTP_USER_AGENT`.

## Data modes

| Mode | Hospitals | Insurance | Use |
|---|---|---|---|
| `fixture` (default) | 12 **fictional** hospitals (Jaipur, Delhi, Ajmer) | fictional insurers *Demo Shield Insurance* and *Sample Care Health* (the latter has a simulated outage) | Reproducible demo of every path: agreement, conflict, de-listing, branch ambiguity, exclusion, outage, other city, prompt injection |
| `live` | Real OpenStreetMap data via Nominatim (ODbL, at most 1 request per second, cached). Hospital websites are fetched only where robots.txt allows. | Official network lists imported by the operator from insurer websites ([format](data/insurer_networks/README.md)). Otherwise the result is reported as `SOURCE_UNAVAILABLE`. | Real-world use |

Synthetic data is labelled in every reply, card badge and saved record. Fixture mode **never** returns network data for a real insurer: asking about Star Health in fixture mode gives "not checked".

## Implementation status

Each status means only what it says.

| Capability | Implemented | Tested locally | Tested with live API | Tested inside ASI:One |
|---|---|---|---|---|
| ACP handler (ack, text, start-session, resources, metadata) | ✅ | ✅ real uAgents (`test_protocol.py`) | n/a | ❌ needs mailbox connection |
| Manifest publication to Agentverse | ✅ | ✅ log: `Manifest published successfully` | ✅ | ❌ |
| Almanac registration | ✅ | ✅ log: `Registration on Almanac API successful` | ✅ | n/a |
| Agentverse mailbox | ✅ (`mailbox=True`) | ❌ | ❌ **manual inspector Connect required** | ❌ |
| Coordinator ↔ Hospital/Insurer agents (typed messages) | ✅ | ✅ 3 processes, 12/12 checks | n/a | ❌ |
| Interactive Cards (carousel/detail/review) + selection parsing | ✅ per documented schema | ✅ schema + round-trip | n/a | ❌ rendering not yet observed |
| Text fallback for every step | ✅ | ✅ | n/a | ❌ |
| ASI1 intent extraction + shortlist summary | ✅ with grounding + validation + fallback | ✅ with mocked client | ❌ **no API key available in build env** | ❌ |
| Safety routing, report parsing, question engine | ✅ | ✅ | n/a | ❌ |
| Live hospital discovery (OpenStreetMap) | ✅ | ✅ | ✅ `pytest -m live` | ❌ |
| Hospital website specialty verification | ✅ | ✅ (mock transport) | ⚠️ code path ran, but no top Jaipur candidate had a website tag | ❌ |
| Official insurer network list import | ✅ | ✅ | ❌ no official list imported yet (manual) | ❌ |
| PDF report via ResourceContent URL | ✅ (SSRF-guarded download + pypdf) | ✅ extraction | ❌ ASI:One attachment URL format not yet observed | ❌ |
| Image report OCR | ❌ not implemented (asks user to paste text) | — | — | — |
| Approval → idempotent save → read-back verify → ID | ✅ | ✅ incl. DB failure + duplicates | n/a | ❌ |
| External inquiry / booking / payments | ❌ not implemented (see [LIMITATIONS](docs/LIMITATIONS.md)) | — | — | — |

## Measured results

Measured on 2026-10-23 with `scripts/benchmark.py` (fixture data, in-process) and `scripts/test_protocol.py` (real uAgents):

| Metric | Result |
|---|---|
| Automated tests | 66 passed (`pytest`), plus 1 live-data test passed (`pytest -m live`) |
| Workflow completion (100 journeys, 5 types) | 100% |
| Duplicate approvals creating a new side effect | 0 / 100 |
| Unsupported coverage/diagnosis claims in replies | 0 |
| Source-conflict detection (seeded conflict) | 20 / 20 |
| Follow-up questions | 0 for condition, report and outage paths; 1 (city) for symptoms-only |
| Turn latency, in-process | avg 19 ms, p95 29 ms |
| Real ACP: acknowledgements | 6 / 6 |
| Real ACP: end-to-end checks | 12 / 12. The first turn, including both agent round-trips, took 0.16 s. |

The full matrix of expected vs observed results for every test is in [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md).

## Repository layout

```
app/agents/        coordinator (ACP), hospital_agent, insurer_agent, typed protocols
app/intelligence/  ASI1 client, intent + report parsing, safety router, question engine, explainer, attachments
app/research/      hospital & insurer sources (fixture/live), safe fetcher, entity resolution, research service
app/matching/      evidence engine, decision rules R1-R10, ranking, independent verifier
app/workflow/      state machine, orchestrator, approval hashing, action executor
app/ui/            card builders, card/selection parsing, text fallback
app/database/      SQLAlchemy models, repository (session-scoped access)
app/security/      SSRF validation, redaction/privacy
data/              fixtures (synthetic), synthetic reports, insurer network import folder
scripts/           run_agents, test_protocol, demo_scenarios, benchmark
docs/              architecture, state machine, compatibility, deployment, sources, security, tests, demo, submission
```

## Safety and privacy

- Emergency red flags are checked deterministically **before** any research. If one is found, CareCompass gives 112/108 guidance (or Tele-MANAS 14416) and stops comparing hospitals.
- Raw report text is never stored or logged. Logs record only message length and a hash. Identifiers are redacted before any ASI1 call.
- Records are scoped to a hash of the user's chat. `delete my data` erases them all.
- Outbound fetches are SSRF-guarded on every redirect hop, with scheme/port/IP checks, size caps and timeouts.
- Retrieved text is untrusted data. It never reaches a code path that makes decisions (see the prompt-injection test).

Details are in [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md).

## Limitations and future scope

The honest list is in [docs/LIMITATIONS.md](docs/LIMITATIONS.md). Planned next steps:
- live appointment availability and user-approved booking with real partner APIs,
- authorised insurer inquiries,
- Indian-language support,
- travel-time ranking,
- verified cost estimates,
- plan-document extraction,
- Payment Protocol, if a real paid service, such as a concierge callback, is added.

## License

MIT. Synthetic data is fictional. OpenStreetMap data is © OpenStreetMap contributors under ODbL.
