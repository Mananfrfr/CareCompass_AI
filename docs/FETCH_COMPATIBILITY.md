# Fetch.ai compatibility notes

Verified against the Innovation Lab docs (docs version 1.0.5), read on 2026-10-23, and against the installed packages.

| Item | Documentation | This project | Verified how |
|---|---|---|---|
| Python | 3.10+ | 3.12.3 (Windows 11) | local runs |
| uAgents | `uagents==0.25.5` | `uagents==0.25.5` | `pip freeze` |
| uagents-core | "compatible" (card docs: `>=0.4.9`) | `0.4.12`, pulled in by uagents | `pip freeze` |
| Chat protocol | `AgentChatProtocol 0.3.0` | `chat_protocol_spec.name/version` = `AgentChatProtocol 0.3.0` | printed at runtime |
| Imports | `uagents_core.contrib.protocols.chat` | same: `ChatMessage, ChatAcknowledgement, TextContent, MetadataContent, ResourceContent, StartSessionContent, EndSessionContent, chat_protocol_spec` | code |
| Protocol include | `Protocol(spec=chat_protocol_spec)`, `agent.include(p, publish_manifest=True)` | same | log: `Manifest published successfully: AgentChatProtocol` |
| Acknowledgement | send `ChatAcknowledgement(acknowledged_msg_id=msg.msg_id)` on receipt | sent before any processing | `test_protocol.py`: 6/6 acks |
| Agent constructor | `name, seed, port, mailbox=True, publish_agent_details=True` | same, plus `readme_path`, `description`, custom `resolve` | runtime |
| Agent-to-agent | `Model` messages, `ctx.send`, `ctx.send_and_receive(dest, msg, response_type=..., timeout=...)` (uagents ≥0.21.1) | same; two `send_and_receive` in parallel | real 3-process test |
| ASI1 LLM | OpenAI client, `base_url=https://api.asi1.ai/v1`, `model="asi1"`, `ASI1_API_KEY` | same (`AsyncOpenAI`) | **mocked only**: no key was available during the build |
| Interactive cards | `MetadataContent.metadata` keys `card_protocol_version="1"`, `requires_card_interaction="true"`, `card_kind`, `card_payload` (JSON string, ≤64 KB) | same; kinds used: `carousel`, `detail`, `review` | unit tests + real ACP round-trip; **ASI:One rendering not yet observed** |
| Card interaction | Follow-up `ChatMessage` with `TextContent`: either selection JSON or prose containing the identifiers | `parse_selection()` tries JSON first, then a prose fallback | unit tests |
| Attachments | `StartSessionContent` → reply `MetadataContent({"attachments": "true"})`. `ResourceContent.resource.uri` (or `metadata.url`/`uri`/`source`) is an http(s) URL | same; PDF text extracted after an SSRF-guarded download | unit tests; **ASI:One URL format not yet observed** |
| Session end | `EndSessionContent` ends the turn | never sent mid-workflow (multi-turn state is kept) | code |

## Notes from source inspection (uagents 0.25.5)

- Replies to `send_and_receive` are matched in `Dispatcher.dispatch_msg` *before* they are queued. A coordinator handler that is awaiting research replies therefore cannot deadlock, even with sequential message handling.
- With `mailbox=True` and no REST handlers, the local server is dropped. The agent inspector (enabled by default) registers REST handlers, so port 8000 stays up for the local research agents' replies.
- The research agents and the coordinator resolve each other through a `RulesBasedResolver` (localhost). Everyone else, such as ASI:One users, goes through `GlobalResolver`.
- Almanac **contract** registration warns about missing funds. Almanac **API** registration succeeds, which is the path the hackathon examples rely on.

## Known unknowns (verify on event day)

1. How ASI:One assigns `sender` addresses per user and conversation. Continuity is keyed by a hash of `sender`.
2. Whether ASI:One renders our carousel without `image` fields. The schema example includes `image`, but the docs don't say it's required. If a card is rejected, ASI:One shows the complete text version.
3. How ASI:One exposes uploaded PDFs, i.e. whether the URL is publicly fetchable.
