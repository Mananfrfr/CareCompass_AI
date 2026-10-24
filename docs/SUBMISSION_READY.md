# CareCompass AI ? final hackathon build

Verified on 24 October 2026. Core workflow is runnable; this remains a healthcare-navigation prototype with explicitly synthetic demo data.

## Description to submit

Patients and families in India often need help identifying the right hospital service and comparing uncertain insurer-network information. CareCompass AI uses ASI1-assisted intake and two specialist agents to build a sourced hospital shortlist inside ASI:One. Interactive Cards expose evidence and conflicts, then guide selection and approval. The action saves the shortlist, reads it back, and returns a reference. A free care brief turns saved evidence into preparation questions for the hospital and insurer. It does not diagnose, guarantee coverage, contact hospitals or book appointments.

Demo hospitals and insurers are fictional. Live OpenStreetMap retrieval is tested separately. No permitted real insurer dataset has been imported. The optional Payment Protocol integration is a disabled Stripe-test-only prototype, not a demonstrated paid service.

## Submission links

- Repository: https://github.com/Mananfrfr/CareCompass_AI
- Submitted coordinator profile: https://agentverse.ai/agents/details/agent1qf4xxsxv47fa6ghqvv7x8s6lhqw66vp52zgldq8w0xyueyd5cnkavhkl4dm/profile
- Direct agent: https://asi1.ai/ai/agent1qf4xxsxv47fa6ghqvv7x8s6lhqw66vp52zgldq8w0xyueyd5cnkavhkl4dm
- Shared conversation invite: https://asi1.ai/invite?channelInviteKey=vOe6V4S_Ep2Y0Q83V34GfIS0SbD5M4VI9jueaWYYwDo
- Captioned demo video: https://github.com/Mananfrfr/CareCompass_AI/blob/main/docs/demo/CareCompass-demo.mp4
- Direct MP4: https://raw.githubusercontent.com/Mananfrfr/CareCompass_AI/main/docs/demo/CareCompass-demo.mp4

The user confirmed that another session can see the conversation after sign-in. This is an invitation, not an anonymous transcript. Submit only the coordinator profile: the specialists are internal collaborators and their public profile URLs returned "Agent not found".

The 3:12 video is a silent, captioned sequence of actual screenshots and measured evidence, not a continuous screen recording. It demonstrates the core workflow. For a form requiring a streaming host, upload this MP4 to your preferred video host and use that link.

## Evidence

- 121 automated tests passed, including the real three-agent ACP journey and payment error/replay cases.
- One live OpenStreetMap test passed separately.
- Real ASI1 comparison: rules alone could not map user-stated lateral epicondylitis; ASI1 added orthopaedics in one successful call. See `data/test_results/asi1_live_comparison.json`.
- The corresponding ASI:One journey saved `CC-MWBAFGVE` with 16 evidence records; both specialist tasks succeeded and repeated approval left one record for that case. See `data/test_results/asi1_conversation_verification.json`.
- The restarted coordinator published AgentChatProtocol and AgentPaymentProtocol successfully.
- The final build saved a fresh ASI:One shortlist as `CC-WNKJ2E3N`; the free care brief rendered with its saved source links and preparation questions.
- `buy preparation report` returned the correct disabled-payment explanation inside ASI:One.
- Payments are disabled here. Automated Stripe tests use mocked HTTP responses; no actual checkout or settlement has occurred.

## Running and submission

Run `python scripts/run_agents.py` from the activated environment. Keep exactly one production runtime using these private seeds; two machines consuming the same mailbox can produce inconsistent replies. Keep the host awake and connected during judging. `.env`, databases, runtime logs and agent checkout storage stay out of Git.

Use `care brief` after saving, or `care brief CC-XXXXXXXX` for a reference owned by your current agent identity. References belonging to another identity are deliberately inaccessible even if you can read the shared conversation.

Review the video, paste the links and description into the submission form, and submit it yourself. Seller onboarding, supported checkout UI testing and real insurer-data permission remain external prerequisites, not completed features.
