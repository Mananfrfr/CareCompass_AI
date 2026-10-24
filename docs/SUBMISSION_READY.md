# CareCompass AI submission pack

Status: draft reconstructed from the shared handoff. The demo video and migrated deployment are pending.

## Description

Patients and families in India often need help choosing a hospital and understanding contradictory insurer information. CareCompass AI turns a stated concern or text report into an evidence-backed hospital shortlist within ASI:One. A coordinator dispatches two specialist research agents, checks their evidence, presents interactive choices, and saves a shortlist only after approval. It reads the saved record back and returns a reference. It does not diagnose, confirm coverage, or book appointments.

The demonstrated hospital and insurer data are fictional fixtures. Live OpenStreetMap discovery is implemented; no official insurer network dataset has been imported.

## Submission links

- Repository: https://github.com/Mananfrfr/CareCompass_AI
- Submitted coordinator: https://agentverse.ai/agents/details/agent1qf4xxsxv47fa6ghqvv7x8s6lhqw66vp52zgldq8w0xyueyd5cnkavhkl4dm/profile
- Direct agent chat: https://asi1.ai/ai/agent1qf4xxsxv47fa6ghqvv7x8s6lhqw66vp52zgldq8w0xyueyd5cnkavhkl4dm
- Workflow invite: https://asi1.ai/invite?channelInviteKey=vOe6V4S_Ep2Y0Q83V34GfIS0SbD5M4VI9jueaWYYwDo
- Video: pending; no verified public video URL exists in the handoff.

The user reported the invite works for another signed-in account. This is not an anonymous transcript. The two research agents are internal collaborators; their public profile URLs were reported unavailable.

## Suggested video sequence (3:12)

| Time | Show |
|---|---|
| 0:00–0:25 | Problem, intended users, navigation limits and synthetic-data label |
| 0:25–0:55 | Synthetic lateral-epicondylitis prompt; measured rules versus real ASI1 extraction |
| 0:55–1:25 | Actual coordinator and both specialist task results, without secrets |
| 1:25–2:05 | ASI:One shortlist, evidence, conflict handling and hospital selection |
| 2:05–2:45 | Review, explicit approval, saved reference and repeated approval |
| 2:45–3:12 | Tests, limitations, repository and coordinator profile |

Use genuine screenshots or a fresh screen recording. Label an edited walkthrough clearly. Do not depict historical references as records in the new laptop's empty database. Do not expose API keys, seeds, patient information or private logs.

## Completion gate

- [ ] Original identity restored and migrated runtime verified.
- [x] Current automated tests pass: 89 passed, 1 live test deselected; includes real three-agent ACP workflow.
- [x] Real ASI1 comparison passes on this laptop (one call, zero failures; rules: no specialty; ASI1: orthopaedics).
- [ ] Video rendered, watched and publicly accessible.
- [ ] Updated documentation and artifacts published.
- [ ] All submitted links checked and submission sent by the owner.

Historical checks and exact reconciliation: [HANDOFF.md](HANDOFF.md).
