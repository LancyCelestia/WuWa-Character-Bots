# Plugin Analysis Matrix

## Purpose

This matrix complements `architecture_report.md`. The report explains the target architecture; this file tracks each downloaded source and records what it is useful for, what mechanism it demonstrates, how it should be reused, and what risks it carries.

Evidence levels:

- Deep: manually inspected representative implementation files or received focused explorer findings.
- Sampled: read README/entry files and searched key mechanisms.
- Structural: indexed source metadata and categorized by imports, matchers, scheduler/storage/rendering/API usage.

## NoneBot Plugin Matrix

| Category | Plugin / source dir | Evidence | Useful mechanisms | Reuse decision | Priority / risk |
| --- | --- | --- | --- | --- | --- |
| Subscription | `nonebot_bison-0.9.14-py3-none-any` | Deep | Platform abstraction, persistent subscription models, weighted scheduler, batch fetch, normalized posts, queued SAA sender | Adapt as subscription architecture reference | P1, medium auth risk |
| Life / traffic | `nonebot_plugin_12306_ticket-0.1.2-py3-none-any` | Sampled | Train ticket query, scheduler/polling shape, OneBot command UX | Adapt query parsing only; redesign persistent session/polling | P1/P2, medium privacy risk |
| AI chat | `nonebot_plugin_aitalk-3.13.38-py3-none-any` | Deep-ish via explorer | Active reply configs, cooldown helpers, LLM action surfaces | Adapt cooldown/active-reply ideas; do not copy autonomous actions directly | P0/P1 reference, high action risk |
| ACG search | `nonebot_plugin_anime-1.0.1-py3-none-any` | Structural | Anime query, aiohttp/http render, OneBot-heavy event handling | Adapter/reference only | P1, medium maintainability risk |
| Game sim | `nonebot_plugin_arkgacha-0.8.2-py3-none-any` | Sampled | Arknights gacha simulation, Alconna command, scheduler/static data | Direct/adapt simulator pattern | P1, low risk |
| Game interaction | `nonebot_plugin_arkguesser-1.0.3-py3-none-any` | Sampled | Guessing game state, rendering, HTTP resource fetch | Adapt state-machine/game loop pattern | P1/P2, low risk |
| Game account | `nonebot_plugin_arkrecord-1.7.1-py3-none-any` | Structural | Arknights record query commands | Later adapter after auth/privacy review | P2, account data risk |
| Game query | `nonebot_plugin_arktools-1.2.0-py3-none-any` | Sampled | Public DB/update/subscription modules, Arknights utilities | Adapt public query and update patterns | P1, low/medium risk |
| Security | `nonebot_plugin_authrespond-1.8-py3-none-any` | Deep via explorer | `run_preprocessor`, `IgnoredException`, auth response filters | Adapt as input/session ACL pattern | P0, low risk |
| Media query | `nonebot_plugin_bili_query-0.1.0-py3-none-any` | Structural | Bilibili query with scheduler/httpx | Reference only; Bilichat/Bison stronger | P1, medium API risk |
| Parser/subscription | `nonebot_plugin_bilichat-6.5.0-py3-none-any` | Deep | UniMsg/Hyper extraction, per-content cooldown, Bilibili API, UP subscription jobs | Adapt as Bilibili-specific parser/subscription source | P1, cookie/rate-limit risk |
| Live subscription | `nonebot_plugin_bililive-2.2.0-py3-none-any` | Sampled | Live-room subscriptions, risk-control cooldown, scheduler, ORM | Adapter/reference for live alerts | P1/P2, auth/rate-limit risk |
| Security | `nonebot_plugin_blacklist-1.4.3-py3-none-any` | Deep via explorer | Incoming event preprocessor blacklist | Direct/adapt for global denylist | P0, low risk |
| Rendering | `nonebot_plugin_cardimg-0.1.3-py3-none-any` | Deep | Template facade, startup resource loading, reusable card API | Direct dependency candidate or adapt API | P0/P1, low risk |
| AI chat | `nonebot_plugin_chatgpt_api-1.1.5-py3-none-any` | Structural | ChatGPT commands, localstore, scheduler, html render | Reference only; use modern LLM adapter abstraction | P0 reference, API key risk |
| Records | `nonebot_plugin_chatrecorder-0.7.0-py3-none-any` | Deep | ORM + uninfo raw message archive, query APIs, adapter-neutral identity | Direct dependency candidate | P0, privacy controls required |
| AI chat | `nonebot_plugin_deepseek-0.2.1-py3-none-any` | Structural | Alconna command/chat wrapper for DeepSeek | Reference provider adapter only | P0 reference, API key risk |
| Persona | `nonebot_plugin_dotcharacter-2.0.9-py3-none-any` | Structural | Character/persona commands and LLM calling | Reference only | P1, OOC risk if direct |
| Game query | `nonebot_plugin_endfield-0.2.5-py3-none-any` | Sampled | Endfield command modules, HTTP calls, html rendering | Public query reference; account flows later | P1/P2, token risk |
| Game account | `nonebot_plugin_gachalogs-0.2.13-py3-none-any` | Sampled | Gacha log import/query, authkey/cookie style flows | Later private-only adapter | P3, high account privacy risk |
| Fanwork | `nonebot_plugin_genshin_cos-0.3.5-py3-none-any` | Sampled | Genshin cosplay search/schedule/image sending | Adapt as fanwork recommendation source with private default | P2, copyright/content risk |
| Group analytics | `nonebot_plugin_group_heat-0.1.3-py3-none-any` | Sampled | Group activity/heat charts from message data | Adapt as derived analytics over chatrecorder | P2, privacy risk |
| Game public | `nonebot_plugin_gscode-0.2.2-py3-none-any` | Sampled | Redemption code query/push, HTTP calls | Direct/adapt low-risk public game utility | P1, low risk |
| Game account | `nonebot_plugin_gsmaterial-0.2.7-py3-none-any` | Sampled | Material planning, scheduler, some cookie-dependent calculator behavior | Split public material query from private calculator | P1/P3, cookie risk |
| Game account | `nonebot_plugin_gspanel-0.2.25-py3-none-any` | Deep-ish | UID panel, html rendering, game profile display | Later adapter with private controls | P2/P3, UID/privacy risk |
| Life/weather | `nonebot_plugin_heweather-0.11.0-py3-none-any` | Deep via explorer | Weather query/subscription, localstore targets, startup job reload | Direct/adapt simple weather subscription | P1, location privacy risk |
| Rendering | `nonebot_plugin_htmlrender-0.7.1-py3-none-any` | Deep | Browser HTML screenshot rendering API | Direct dependency candidate | P0/P1, runtime dependency risk |
| Social parser | `nonebot_plugin_instagram-0.3.1-py3-none-any` | Structural | Instagram/RapidAPI command/regex parser | Adapter/reference only | P2, API/auth/rate risk |
| Music | `nonebot_plugin_kuwo-0.2.6-cp310-abi3-win_amd64` | Sampled | Kuwo music search, Alconna, temp-file cache, locking | Optional adapter; check platform wheel constraints | P1/P2, binary/platform risk |
| AI chat | `nonebot_plugin_llmchat-0.5.4-py3-none-any` | Structural | LLM chat commands, scheduler, localstore | Reference only; avoid autonomous actions | P0 reference, tool risk |
| Rendering | `nonebot_plugin_markdown2img-0.0.6-py3-none-any` | Deep via explorer | Markdown-to-image rendering | Avoid direct sync fetch/verify=False pattern; adapt cautiously | P1, security risk |
| AI/tools | `nonebot_plugin_marshoai-1.2.1-py3-none-any` | Deep via explorer | Tool/function-call registry, caller permission/rule/pre-check, MCP knobs | Adapt host-side tool gate ideas only | P2/P3, high tool/MCP risk |
| Wiki | `nonebot_plugin_mediawiki-1.2.8-py3-none-any` | Sampled | MediaWiki query, regex commands, aiohttp, html rendering | Adapter for wiki search | P1, OneBot-heavy risk |
| Fun/media | `nonebot_plugin_memes-0.8.1-py3-none-any` | Sampled | Meme generation, allowlist/statistics, ORM | Optional feature after core; adapt allowlist | P2, spam/content risk |
| Life/weather | `nonebot_plugin_nmcweather-0.1.3-py3-none-any` | Sampled | Simple weather query via national weather source | Direct/simple weather source candidate | P1, low risk |
| Parser | `nonebot_plugin_parser-2.6.6-py3-none-any` | Deep | `BaseParser`, handler decorators, startup keyword map, `ParseResult`, renderer/sender/cache split | Primary parser architecture reference | P0/P1, medium platform/API risk |
| Permission | `nonebot_plugin_permission-0.3.0-py3-none-any` | Deep via explorer | ACL-style `checker.require_permission()` with Alconna | Adapt/direct permission model | P0, low risk |
| Fanwork/search | `nonebot_plugin_pixivbot-2.1.6-py3-none-any` | Deep via explorer | Handler/interceptor/repository/scheduler/watchman, Pixiv recommendation/search | Adapt control-plane ideas; do not adopt whole stack first | P2, token/content risk |
| AI chat | `nonebot_plugin_pxchat-1.0.3-py3-none-any` | Deep | Context capture even without reply, group probability decay, should-reply LLM judge, split replies | Adapt bounded context and group trigger throttling | P0/P1, spam/OOC risk if direct |
| Music | `nonebot_plugin_qqmusic_reco-0.1.15-py3-none-any` | Structural | QQ music recommendation/search, scheduler/httpx | Optional adapter with rate limits | P1/P2, API risk |
| Parser | `nonebot_plugin_resolver-1.2.32-py3-none-any` | Sampled | Many independent regex handlers for link resolving | Reference only; avoid as core architecture | P1, maintainability risk |
| Persona platform | `nonebot_plugin_shiro_personification-0.6.1-py3-none-any` | Deep | Memory/persona/context/jobs/web UI/MCP/QZone/response review runtime | Mine patterns; avoid direct monolith | P1/P2 reference, high complexity |
| Game public | `nonebot_plugin_starrail_calendar-1.0.8-py3-none-any` | Sampled | Star Rail calendar/schedule, scheduler, image rendering | Direct/adapt public calendar utility | P1, low risk |
| Media learning | `nonebot_plugin_sticker_saver-0.1.4-py3-none-any` | Sampled | Reply-media extraction and sticker saving | Adapt UX later; central media policy needed | P2/P3, consent/content risk |
| Summary | `nonebot_plugin_summary_group-1.0.1-py3-none-any` | Deep | Explicit Alconna summary command, count bounds, per-user cooldown, admin scheduled summary, queue config | Direct/adapt command UX; use chatrecorder as source | P0/P1, LLM cost/privacy risk |
| Search | `nonebot_plugin_tavily-0.1.0-py3-none-any` | Sampled | Tavily search/extract/crawl command surface | Manual search provider adapter | P1, API key/rate risk |
| Anti-spam | `nonebot_plugin_tea_silencer-1.0.2-py3-none-any` | Deep via explorer | Weighted category/decibel temporary blocking | Adapt as anti-noise heuristic | P1, false-positive risk |
| Weather analytics | `nonebot_plugin_weather_rank-0.1.9-py3-none-any` | Sampled | DB-backed city/group weather ranking, scheduler | Adapt as P1/P2 weather analytics | P1/P2, location privacy risk |
| Output safety | `nonebot_plugin_word_censor-0.3.1-py3-none-any` | Deep | Outgoing `Bot.on_calling_api` API hook, text/regex blacklist | Direct/adapt final transport censor | P0, low/medium false-positive risk |
| Group analytics | `nonebot_plugin_wordcloud-0.11.1-py3-none-any` | Deep via explorer | ORM-backed schedules, target JSON, chatrecorder-based analytics | Direct/adapt scheduled analytics | P1/P2, privacy risk |
| Game account | `nonebot_plugin_wwgachalogs-0.1.7-py3-none-any` | Sampled | WuWa gacha log storage/binding via ORM | Later private-only adapter | P2/P3, account history risk |
| Game wiki | `nonebot_plugin_wwwiki-0.4.1-py3-none-any` | Deep | WuWa public wiki/card commands, HTML/PIL templates | Direct/adapt public WuWa cards | P1, low risk |
| Game account | `nonebot_plugin_zzzpanel-0.1.6-py3-none-any` | Deep-ish | ZZZ account panel, QR/cookie-like flows, html rendering | Later private-only adapter | P3, critical account risk |

## GsCore / GScore Matrix

| Repository | Evidence | Useful mechanisms | Reuse decision | Priority / risk |
| --- | --- | --- | --- | --- |
| `gsuid_core` | Deep sampled | Adjacent runtime, `SV` registry, trigger model, permission chain, scheduler, DB, web console, AI core, history | Bridge as adjacent service; do not merge into plugin runtime | P2 bridge, broad blast radius |
| `nonebot-plugin-genshinuid` | Deep sampled | NoneBot message/notice intake, adapter-to-protocol map, WebSocket forwarding to gsuid-core | Primary NoneBot bridge reference | P2, bridge reliability risk |
| `GenshinUID` | Sampled | Full Genshin feature set, multi-platform game logic, wiki/panel/account features | Feature inventory and selected public logic reference | P1/P3 split, account risk |
| `StarRailUID` | Sampled | Star Rail UID/game query plugin, `SV` commands | Feature inventory before Star Rail integration | P1/P3 split |
| `ZZZeroUID` | Sampled | CM-Edelweiss ZZZ UID fork/reference, `SV` commands | Secondary/provisional comparison source; not authoritative after ZZZure verification | P1/P3 split, stale/low-signal risk |
| `ZZZeroUID_ZZZure` | Sampled | Active upstream ZZZure GsCore extension, ZZZ wiki/guide/code commands plus account/cookie/gacha/sign flows | Primary ZZZ feature reference; allow only public wiki/guide/code in first bridge | P1/P3 split, credential risk |
| `XutheringWavesUID` | Sampled | Active WuWa GsCore plugin, command modules, resources, login/account traces | Main WuWa GsCore reference | P1/P3 split |
| `WutheringWavesUID` | Sampled | WuWa plugin fork/reference | Secondary comparison source | P1/P3 split |
| `ScoreEcho` | Sampled | WuWa echo scoring algorithms/cards for GsCore | Adapt scoring logic/cards if license permits | P1/P2, data correctness risk |
| `EndUID` | Sampled | Endfield UID plugin for GsCore, scheduler/login traces | Later Endfield source | P2/P3, token risk |
| `BotShepherd` | Deep sampled | OneBot v11 proxy, connection management, global switches, blacklist, aliases, stats, web UI, backup | Governance inspiration; operational optional layer | P1 ops, security/config risk |
| `astrbot_plugin_gscore_adapter` | Deep sampled | AstrBot WebSocket bridge, outbound queue, reconnect, downstream dispatch, recall receipts | Bridge reliability reference | P2, bridge operational risk |

## AstrBot Reference Matrix

| Plugin | Evidence | Useful mechanisms | Reuse decision | Priority / risk |
| --- | --- | --- | --- | --- |
| `astrbot_plugin_parser` | Deep sampled | Parser registry, normalized result, downloader, QR attach, redirect support, render/sender split | Port domain logic and interface ideas | P1, platform adaptation work |
| `astrbot_plugin_qzone_ultra` | Sampled | Cookie/token redaction, safe LLM-visible output filtering, public error sanitization, QZone bridge | Use security/redaction patterns; QZone later | P3, critical account risk |
| `astrbot_plugin_proactive_chat` | Deep via explorer | Session config, scheduler, idle gates, quiet hours, cancel-on-human-message, unanswered counters | Adapt proactive policy gates | P1/P2, spam risk |
| `antipromptinjector` | Deep | Prompt threat detector, persona matcher, risk levels, defense modes | Adapt input risk and persona scoring | P0/P1, false-positive risk |
| `astrbot_plugin_outputpro` | Deep | Central output pipeline, step registry, rate limiter, cleanup/split/block/forward/TTS/T2I steps | Primary output choke-point reference | P0, low/medium risk |
| `astrbot_plugin_qq_group_daily_analysis` | Deep via explorer | Structured LLM output, Pydantic validation, repair retries, group locks, circuit breaker, render templates | Adapt analytics and schema validation | P2, privacy/cost risk |
| `astrbot_plugin_ww_gacha_sim` | Sampled | DB, item manager, pool manager, gacha mechanics, renderer, web UI boundaries | Adapt game simulation module layout | P1/P2, low risk |
| `astrbot_plugin_disaster_warning` | Structural | Disaster/weather warning subscriptions | Compare with weather plugins for warning policy | P1, alert fatigue risk |
| `astrbot_plugin_gscore_adapter` | Deep sampled | GsCore WebSocket bridge and queue/reconnect logic | Bridge reference | P2, operational risk |
| `astrbot_plugin_chat_archive` | Structural | Chat archive/history storage | Compare with chatrecorder before final archive choice | P0/P1, privacy risk |
| `astrbot_plugin_angel_memory` / `angel_heart` | Structural | Memory/personality/life-simulation style concepts | Ideas only after safety core | P2/P3, OOC/privacy risk |

## Cross-Cutting Decisions

- Direct dependencies should be library-like, adapter-neutral, and low-risk: `chatrecorder`, `htmlrender`, maybe `cardimg`, weather/public query plugins after testing.
- Architecture patterns should be copied from mature systems: parser registry, Bison scheduler, OutputPro pipeline, AntiPromptInjector risk scoring, ProactiveChat gates, GsCore bridge queue.
- Avoid direct monolith adoption: Shiro personification, full GsCore game plugins, QZone automation, MCP/tool-heavy LLM plugins.
- Public data first, private/account data later. Game panels, logs, QR login, cookies, authkeys, travel/location subscriptions, and fanwork scraping require explicit privacy controls.
- Group chat features should be opt-in and digest-oriented. Private chat can be more helpful but still needs consent and pause/snooze/delete/export controls.
## Second-Batch Official Store Candidates

These 17 plugins were added after a 2026-07-06 official registry snapshot (`903` entries) to cover newer or more life-oriented candidates not included in the first 53-source batch.

| Category | Plugin / source dir | Evidence | Useful mechanisms | Reuse decision | Priority / risk |
| --- | --- | --- | --- | --- | --- |
| Security / governance | `nonebot_plugin_access_control-1.2.4-py3-none-any` | Sampled | Session-aware permission control, call limits, ORM persistence, APScheduler integration, Alconna admin surface | Strong P0 governance reference; evaluate as direct dependency or adapt service model | P0, low/medium correctness risk |
| Life / reminder | `nonebot_plugin_reminder-0.4.3-py3-none-any` | Sampled | Regex reminder commands, APScheduler jobs, localstore persistence, SAA-style cross-platform intent | Adapt reminder UX/persistence under private-first policy | P1, privacy/alert fatigue risk |
| Life / reminder | `nonebot_plugin_clock-1.1.9.1-py3-none-any` | Structural | Alarm/clock commands, scheduler/localstore, OneBot send path | Reference for reminder command grammar only | P1, OneBot/noise risk |
| Life / schedule | `nonebot_plugin_class_schedule-1.0.6-py3-none-any` | Sampled | Course schedule import/query, holiday awareness, reminder toggles, text/image fallback | Strong personal schedule assistant reference | P1/P2, personal data risk |
| Life / schedule | `nonebot_plugin_ai_timetable-0.4.1-py3-none-any` | Structural | Timetable import/query style, regex and Alconna command surfaces, scheduler/httpx | Optional timetable import reference | P2, personal data risk |
| Parser / Bilibili | `nonebot_plugin_analysis_bilibili-2.8.1-py3-none-any` | Sampled | Video/bangumi/live/article/dynamic parsing, regex/message hooks, aiohttp, SAA send | Compare with Bilichat/BiliHelper for parsing coverage; do not keep direct send path | P1, API/rate risk |
| Parser / Bilibili | `nonebot_plugin_bili_helper-0.9.3-py3-none-any` | Sampled | Bilibili share extraction, comments, cookie config, localstore, htmlrender templates | Adapt parser/render ideas; centralize output and cookie policy | P1/P2, cookie/OneBot risk |
| Subscription / Bilibili | `nonebot_plugin_bili_fav_watcher-0.1.12-py3-none-any` | Structural | Favorites watcher, scheduler, localstore, OneBot commands | Adapter reference; Bison remains stronger scheduler foundation | P1/P2, auth/rate risk |
| Subscription / push | `nonebot_plugin_autopush-0.1.1-py3-none-any` | Structural | Simple scheduled push mechanism | Reference only; replace with central queue/digest | P2, spam risk |
| AI / group persona | `nonebot_plugin_ai_groupmate-2.0.6-py3-none-any` | Sampled | ORM/uninfo/localstore message memory, media storage, wordcloud, LLM reply judge, latest-only group reply worker | Strong anti-backlog/group participation reference; route through persona/OOC gate | P1/P2, privacy/spam/OOC risk |
| AI / LLM | `nonebot_plugin_aiochatllm-0.1.7-py3-none-any` | Structural | LLM command/message wrapper, localstore, permission signals | Provider/trigger reference only | P0/P1 reference, API key risk |
| AI / LLM | `nonebot_plugin_anywhere_llm-1.1.6-py3-none-any` | Structural | General chat trigger surface, localstore, OneBot output | Reference only; unified LLM adapter preferred | P1, group over-participation risk |
| ACG / resource search | `nonebot_plugin_animeres-1.0.5-py3-none-any` | Structural | Anime resource search, HTTP calls, OneBot send | Optional private-command source after content policy review | P2/P3, copyright/content risk |
| ACG / image recognition | `nonebot_plugin_anime_trace-0.2.3-py3-none-any` | Sampled | Image character recognition, PIL output, OneBot forward messages | Optional image-search tool reference | P2, platform/output risk |
| ACG / events | `nonebot_plugin_acgnshow-0.3-py3-none-any` | Structural | ACG expo/exhibition query, HTTP/rendering/storage signals | Useful life+ACG event query reference | P1/P2, external data reliability |
| Game / simulator | `nonebot_plugin_badrawcard-0.2.3-py3-none-any` | Structural | Blue Archive draw simulation and command/state handling | Optional gacha simulator reference after WuWa/Arknights | P2, fun/spam risk |
| Game / interaction | `nonebot_plugin_boardgame-0.4.1-py3-none-any` | Structural | Board game command/state pattern, Alconna/ORM | Optional state-machine reference | P2, not core first milestone |

## Full AstrBot Matrix

See esearch/astrbot_plugin_analysis_matrix.md for per-plugin coverage of all 24 local AstrBot plugin directories. The AstrBot section above keeps only the strongest reference plugins for direct comparison with the NoneBot architecture.

