# AstrBot Plugin Analysis Matrix

## Purpose

This matrix covers every non-cache, non-backup local AstrBot plugin found under `C:\Users\LancyCelestia\.astrbot\data\plugins`. It complements `research/astrbot_plugin_sources/inventory.md`, which records structural signals. This file adds migration value, reuse decision, and risk priority for each plugin.

Evidence levels:

- Deep: representative implementation files or prior focused audit were read.
- Sampled: entry/config/README and important code paths were sampled.
- Structural: structural scan only; useful for inventory and risk detection, not direct porting.

## Matrix

| Plugin | Evidence | Useful mechanisms | Reuse decision | Priority / risk |
| --- | --- | --- | --- | --- |
| `antipromptinjector` | Deep | Prompt-injection risk detection, prompt sanitization, persona compatibility scoring, revise/block actions | Adapt input risk and persona/OOC scoring into the central safety layer | P0/P1, false-positive tuning risk |
| `astrbot_plugin_angel_heart` | Structural | Heart/personality/life-simulation style concepts, persistent state, persona-adjacent behavior | Ideas only; do not port until safety, memory, and consent controls exist | P2/P3, OOC and privacy risk |
| `astrbot_plugin_angel_memory` | Structural | Large memory subsystem, long-term personality context, storage-heavy memory concepts | Mine carefully after core memory policy; not a first milestone dependency | P2/P3, privacy and hallucinated-memory risk |
| `astrbot_plugin_apis` | Structural | Small API command surface and external helper integration | Reference for simple adapter command wrapping only | P2, external API reliability risk |
| `astrbot_plugin_chat_archive` | Structural | Chat history/archive storage, retrieval ideas | Compare with `nonebot_plugin_chatrecorder`; prefer chatrecorder for first archive layer | P0/P1, privacy controls required |
| `astrbot_plugin_disaster_warning` | Structural | Disaster/weather alert subscription concepts, scheduled warning push | Compare with weather plugins for alert fatigue, severity, and admin opt-in design | P1, alert fatigue and location privacy risk |
| `astrbot_plugin_gscore_adapter` | Deep sampled | WebSocket bridge, outbound queue, reconnect, downstream dispatch, recall receipts | Primary AstrBot bridge robustness reference for GsCore adapter | P2, operational reliability and command allowlist risk |
| `astrbot_plugin_hapi_connector` | Structural | External connector/API integration, HTTP/WS signals | Reference only for connector boundaries after core policy exists | P2/P3, credential and API stability risk |
| `astrbot_plugin_heartflow` | Structural | Minimal heartflow/personality state concept | Ideas only; too small/unclear as a direct architecture source | P3, OOC/ambiguity risk |
| `astrbot_plugin_help` | Structural | Help command and user guidance surface | Useful for unified help/command registry UX | P0/P1, low risk |
| `astrbot_plugin_kuro_cos-main` | Structural | Kuro-related cosplay/fanwork fetching/sending concept | Optional fanwork source reference; private/default-command-only | P2/P3, copyright/content/privacy risk |
| `astrbot_plugin_outputpro` | Deep | Central output pipeline, step registry, rate limiter, cleanup/split/block/forward/TTS/T2I stages | Primary output choke-point reference; adapt architecture, not every transform | P0, medium transform/spam risk |
| `astrbot_plugin_parser` | Deep sampled | Parser registry, normalized result, downloader, QR/redirect support, rendering/sending split | Port interface ideas and selected platform logic behind NoneBot capability adapters | P1, platform adaptation work |
| `astrbot_plugin_pokepro` | Structural | Poke interaction handling and playful triggers | Keep optional and gated; do not enable proactive poke by default | P3, annoyance risk |
| `astrbot_plugin_proactive_chat` | Deep via prior audit | Per-session proactive config, idle gates, quiet hours, cancel-on-human-message, unanswered caps | Adapt proactive policy gates; private opt-in before group proactive behavior | P1/P2, spam/OOC risk |
| `astrbot_plugin_qq_group_daily_analysis` | Deep via prior audit | Structured LLM analysis, Pydantic validation, repair retries, group locks, circuit breaker, render templates | Adapt schema-first analytics and validation for summaries/reports | P2, privacy and LLM cost risk |
| `astrbot_plugin_qqadmin` | Structural | QQ group admin actions and permission-sensitive operations | Human-confirm/admin-only reference; never model-autonomous | P3, high-impact moderation risk |
| `astrbot_plugin_qzone_ultra` | Sampled | QZone posting/interaction bridge, cookie/token redaction, safe LLM-visible output filtering | Use redaction/error-sanitization patterns; QZone automation later | P3, critical account/reputation risk |
| `astrbot_plugin_reneban` | Structural | Ban/rename/admin-flavored moderation utilities | Reference only for permission checks; keep out of early persona runtime | P3, moderation/action risk |
| `astrbot_plugin_self_iterative_core` | Structural | Self-improvement/iteration concept and command surface | Do not port until audit, sandbox, and human approval exist | P3, self-modification risk |
| `astrbot_plugin_splitter` | Structural | Output splitting behavior | Superseded by OutputPro-style central output shaping | P1/P2, spam risk if direct |
| `astrbot_plugin_stealer` | Structural | Media/sticker acquisition/storage concept | Later media learning reference with consent, moderation, storage limits | P3, consent/copyright/storage risk |
| `astrbot_plugin_subagent_worktogether` | Structural | Multi-agent collaboration concept | Not a bot-user feature for first milestones; possible private/admin workflow later | P3, tool-execution and verbosity risk |
| `astrbot_plugin_ww_gacha_sim` | Sampled | WuWa gacha mechanics, pools/items, DB, renderer, web UI boundaries | Adapt as game simulation module layout after core runtime | P1/P2, low/medium balance/data risk |

## Cross-Plugin Lessons

- The AstrBot side strongly supports a central output choke point: `outputpro` is the clearest reference, and smaller output/split/send plugins should feed into one unified sender instead of each sending directly.
- Persona, memory, proactive behavior, and life-simulation plugins are useful but risky; they should come after explicit persona contracts, OOC review, privacy controls, and opt-in memory.
- Account/action plugins such as QZone, QQ admin, GScore account bridges, and moderation utilities must remain private/admin-confirmed or later-stage.
- Parser, GScore bridge, daily analysis, and WuWa gacha simulator are the most valuable AstrBot references for early migration because they map to concrete requested features.
