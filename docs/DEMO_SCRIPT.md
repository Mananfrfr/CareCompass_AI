# Demo script (4:30–5:00)

**Setup before recording:**
- `CARECOMPASS_DATA_MODE=fixture`, and `python scripts/run_agents.py` is running with the mailbox connected.
- Use a fresh ASI:One chat. Say `new search` first if you are reusing one.
- Keep a terminal visible: the `[hospital]` and `[insurer]` log lines show the agent-to-agent calls.

> Why "Demo Shield Insurance" and not Star Health: fixture mode uses **fictional** insurers, so that no network data about a real insurer is ever invented. Say this on camera; it is a strength. Real insurers work in live mode with official lists.

## 0:00–0:30 Problem

"Finding the right hospital for an ACL tear means guessing the specialty, searching hospitals, then digging through insurer PDFs to see if a hospital is in-network, and the sources often disagree. CareCompass turns one message into a verified, evidence-backed shortlist and a saved action, inside ASI:One."

## 0:30–1:00 Minimal input

Type in ASI:One:

> I have an ACL tear. I live in Jaipur and have Demo Shield insurance. Help me find a suitable hospital.

Point out what happened without any form:
- It understood **ACL tear → Orthopaedics**, with a navigation rationale and no diagnosis.
- It extracted **Jaipur** and **Demo Shield**.
- It asked no follow-up questions.

## 1:00–2:00 Autonomous coordination

Show the terminal:
- `[hospital] hospital research task=… city=Jaipur specialty=orthopaedics`
- `[insurer] insurer research task=… insurer=Demo Shield Insurance`

These are two separate uAgents, called in parallel with typed messages, timeouts and retries.

Then explain the evidence flow:
- The hospital agent returned profiles and specialty evidence.
- The insurer agent returned a network directory and a de-empanelment notice.
- Entity resolution matched "Aravali Bone and Joint Hosp." and the abbreviation "ABJH" to the same hospital. It did *not* attach an unbranched "Chandpole Ortho Hospital" listing to either of two branches.

## 2:00–3:00 Intelligent result

On the carousel:
1. **Aravali Bone & Joint**: "Network listed", evidence high, suitability 95.
2. **Pink City Multispeciality**: also network listed.
3. **Amber Sports Injury Centre**: **"Sources conflict"** badge. One insurer source lists it and the de-empanelment notice removes it, so CareCompass shows both instead of picking one.

Click **View evidence** on #1. The detail card shows:
- source URLs and retrieval dates,
- a score breakdown (specialty 1.00, network 1.00, …),
- "a listing alone does not confirm your claim",
- "Exact plan needed for plan-level checks".

Optional (+20 s): type `Demo Shield Basic`. The shortlist refreshes with **"Plan document lists this procedure as excluded"**. CareCompass does not say the procedure is covered.

## 3:00–3:45 Action

On the detail card, click **Save shortlist with this choice**. The **review card** shows exactly what will be saved, and states that no report text is stored and nothing is sent to anyone. Click **Approve & save**. The reply contains:
- ✅ **Saved and verified**, `CC-XXXXXXXX`,
- the verification lines: record read back, payload hash matches approval, N evidence records present.

Type `approve` again. The reply is "already saved – no duplicate was created", with the same ID (idempotency).

## 3:45–4:30 Reliability

`new search`, then:

> ACL tear in Jaipur, insured with Sample Care Health

The insurer source is down (a simulated 503). Results still arrive, marked **"Insurer source unavailable – not checked. This is not an out-of-network result."**

Optional: `new search` → `Sudden severe chest pain and difficulty breathing`. CareCompass gives immediate 112/108 guidance and does no hospital comparison.

## 4:30–5:00 Impact and future

"Real data mode already uses OpenStreetMap, hospitals' own websites, and official insurer network lists, with the same evidence rules. Next steps:
- user-approved appointment requests through real hospital APIs,
- Indian-language support,
- travel-time ranking,
- plan-document extraction.

Every new capability still has to pass the same verifier and approval gate."

## Text-only fallback

If cards don't render, the same flow works by typing `1`, then `save`, then `approve`. Every card is also sent as complete text.
