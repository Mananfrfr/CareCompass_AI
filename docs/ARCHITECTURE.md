# Architecture

## Components and boundaries

| Layer | Module(s) | Deterministic? | Notes |
|---|---|---|---|
| Transport (ACP) | `app/agents/coordinator.py` | yes | Acks every `ChatMessage`. Reads `TextContent`, `ResourceContent` and `StartSessionContent`. Replies with `TextContent` plus optional card `MetadataContent`. Uses a per-session `asyncio.Lock`. |
| Agent-to-agent | `app/agents/protocols.py`, `hospital_agent.py`, `insurer_agent.py` | yes | Typed `Model` envelopes. Results are JSON validated against Pydantic schemas on both sides. Research agents accept requests only from the coordinator's address. |
| Workflow | `app/workflow/orchestrator.py`, `state_machine.py` | yes | One entry point, `handle()`, shared by the ACP agent, the CLI and the tests. Every state change goes through `transition()` and is audited. |
| Understanding | `app/intelligence/*` | rules: yes / ASI1: no | Safety runs first and is rule-based. Rules always run. ASI1 adds fields only when they are grounded in the user's own words and fit the controlled vocabulary. |
| Research | `app/research/*` | yes | Pluggable `HospitalSource` / `InsurerSource`. Every fetch goes through `SafeFetcher`. |
| Matching | `app/matching/*` | yes | Evidence engine → rules R1–R6 → ranking → verifier. No LLM involvement. |
| Action | `app/workflow/action_executor.py`, `approval.py` | yes | Idempotency key = hash(case, action, approved payload). Writes in one transaction, then reads back to verify. |
| UI | `app/ui/*` | yes | Cards follow the documented card protocol v1 schema. A full text fallback is always included. |
| Storage | `app/database/*` | yes | SQLite through SQLAlchemy 2. Any SQLAlchemy URL works (PostgreSQL/Supabase). |

## Request lifecycle (primary scenario)

1. **ASI:One → Coordinator.** A `ChatMessage` arrives. The Coordinator immediately sends a `ChatAcknowledgement` and records the message ID (duplicates are dropped).
2. **Safety.** `safety_router.assess()` checks emergency and prompt-care patterns, with simple negation handling ("no chest pain"). An emergency moves the case to `URGENT_GUIDANCE` and research stops.
3. **Understanding.**
   - `rule_extract()` pulls out the condition/symptoms, duration, city, insurer, plan and preferences.
   - For reports, it pulls findings with their status (stated / suspected / negated), measurements and character spans.
   - `IntentParser` optionally calls ASI1 (`structured()`, JSON validated, one repair attempt). `merge_llm()` accepts a field only if it appears in the user's text.
4. **Missing information.** `plan_questions()` blocks only on *concern* and *city*. It offers the insurer question once, as optional.
5. **Parallel research.** The `AgentResearchClient` runs `ctx.send_and_receive()` to both specialist agents at once with `asyncio.gather`. Each call has a timeout and bounded retries, and every outcome is recorded in `agent_tasks`.
6. **Matching** (`build_candidates`). Entity resolution links insurer rows to hospitals by city, postcode, branch, domain and normalised names/abbreviations. It also produces the combined insurance states, conflicts and missing evidence.
7. **Rules** (`apply_candidate_rules`):
   - R1 city
   - R2 specialty evidence
   - R3 conflicts
   - R4 exclusions and waiting periods
   - R5 existence
   - R6 source failure

   Workflow-level rules R7–R10 are enforced in the orchestrator and executor.
8. **Ranking.** Weighted, explainable suitability score. Evidence confidence is computed separately.
9. **Verification** (`verify`). Rejects unknown evidence IDs or invalid URLs, duplicates, excluded or other-city candidates. Downgrades unsupported specialty, network or cashless claims. Strips forbidden language.
10. **Presentation.** A text summary (ASI1 or template, both run through the same claim guard) plus a carousel card.
11. **Selection.** Detail card → review card. Selections arrive as JSON or as prose, and `parse_selection` handles both.
12. **Approval.** The `approvals` row stores the SHA-256 of the exact payload. Stale card versions are refused.
13. **Action.** `ActionExecutor.save_shortlist()` checks the idempotency key, writes the shortlist and its evidence in one transaction, then reads the record back and compares hashes and evidence rows. Only then does the case move to `COMPLETED` and the user receive `CC-XXXXXXXX`.

## Why three agents (and not more)

The hospital and insurer agents do independent research with different sources, failure modes and timeouts. That is real separation, and it lets one fail without the other. Understanding, ranking and verification stay as modules inside the coordinator. Splitting them into separate agents would add latency and failure points without adding independent evidence.

## Scaling path

- Swap SQLite for PostgreSQL with `DATABASE_URL`.
- Run the research agents on separate hosts with public endpoints. Replace `local_routes` with Almanac resolution, which is already the fallback in `CompositeResolver`.
- Add sources by implementing `HospitalSource.search_hospitals` / `InsurerSource.research`. Nothing downstream changes.
