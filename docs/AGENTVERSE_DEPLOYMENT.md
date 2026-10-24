# Agentverse & ASI:One deployment runbook

Steps marked 👤 need your authenticated account and can't be automated from this repo.

## 1. Prepare (once)

```bash
pip install -r requirements.txt
python scripts/run_agents.py --init-env        # creates .env with three seeds (never commit it)
python scripts/run_agents.py --addresses       # copy these into README "Agents" table
```

Optionally set `ASI1_API_KEY` in `.env` (👤 create it at https://asi1.ai/dashboard/api-keys).

Use `CARECOMPASS_DATA_MODE=live` (default) for real data in every Indian city: the National Health Portal directory, government catalogs, OpenStreetMap (Overpass) and the IRDAI register. Set `HTTP_USER_AGENT` to include a real contact, as the OSM usage policies require. `fixture` keeps the synthetic Jaipur/Delhi demo and uses the real directory for all other cities.

## 2. Pre-flight

```bash
python -m pytest                    # 89 tests incl. the real 3-agent ACP journey
python scripts/test_protocol.py     # writes data/test_results/protocol_test_report.json
```

## 3. Start the agents

```bash
python scripts/run_agents.py
```

Expected coordinator log lines:

```
Starting agent with address: agent1q...
Agent inspector available at https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8000&address=agent1q...
Starting mailbox client for https://agentverse.ai
Manifest published successfully: AgentChatProtocol
Registration on Almanac API successful
```

On first start you will also see `Agent mailbox not found: create one using the agent inspector`. That warning is resolved in step 4.

## 4. 👤 Connect the mailbox

1. Sign in at https://agentverse.ai.
2. Open the **Agent inspector** URL from the log, in the same browser.
3. Click **Connect** and choose **Mailbox**. Confirm.
4. Check that the coordinator log no longer warns about the mailbox, and that the agent appears under *Agentverse → Agents → Local agents*.

## 5. 👤 Polish the profile (discoverability)

- **Name:** `CareCompass AI`.
- **README:** published from `docs/AGENT_PROFILE.md`. It includes the required `innovationlab` and `hackathon` badges. Edit it in the Agentverse UI if it doesn't appear.
- **Keywords / short description:** hospital finder, health insurance hospital search, in-network hospitals, healthcare navigation, medical report hospital search, orthopaedic hospitals, insurance-compatible hospitals, hospital comparison.
- Check that the protocol list shows **AgentChatProtocol**.
- The research agents run with `publish_agent_details=False`, because they are internal services. If you also want them listed as separate profiles, for example for "Best Multi-Agent Workflow", connect them through their own inspector links too.

## 6. 👤 Test in ASI:One

1. Go to https://asi1.ai, use agent mode/search, and query "CareCompass hospital finder", or open the agent from its Agentverse page via **Chat with agent**.
2. Run the demo from `docs/DEMO_SCRIPT.md`.
3. Use **Share** to create the public chat URL, and add it to `docs/HACKATHON_SUBMISSION.md`.

## 7. Keep it running

The mailbox delivers messages to the local process, so the process must stay up. Choose one of:

- Keep the laptop running during judging.
- `docker build -t carecompass . && docker run --env-file .env -v carecompass-data:/app/data carecompass` on any always-on VM. Use the same seeds so the address doesn't change.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `COORDINATOR_SEED is missing` | Run `python scripts/run_agents.py --init-env`. |
| Port 8000-8002 in use | Change `*_PORT` in `.env`. The local routes follow automatically. |
| Replies say research timed out | Make sure the hospital and insurer processes are running (same `.env`). Raise `RESEARCH_TIMEOUT_S` for live mode. |
| Card not shown in ASI:One | The text version is complete. Note it and continue: the text flow supports `1`, `save`, `approve` and `cancel`. |
