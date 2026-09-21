# v21r3 渲染垫片退役预研（SHIMRET 席，2026-09-19）

> **身份**：渲染域兼容垫片退役的**只读预研报告**。取证时点 2026-09-19，全部结论来自当前工作树 grep/读盘实取，非转述。
> **⛔ 本预研不执行退役**：执行裁决归 INTG 或用户。原因见 §五.0（在飞波占域 + 模板 D 态未提交 + 提交裁决权在用户）。
> 上游方法论：v21r2 垫片退役（EP1 机核清单 / RET1 已退役 / RWOC 在飞；存量台账 `docs/design/v21r2-shim-retirement-inventory.md`——注意其渲染域计数已过时，本文为准）。
> 范围：旧路径 `plugins/bot_unified_runtime/output/**` 全部垫片；真身 `plugins/bot_unified_runtime/domains/render/**`。

---

## 一、垫片全量清单（15 个 .py + 1 空目录）

### 1.1 `output/`（8 个 .py）

| # | 垫片文件 | 形态 | 转发面（逐符号实读） | 真身 |
|---|---|---|---|---|
| 1 | `output/__init__.py` | **中继**（非纯星转发）：`from .renderer import …` + `from .reviewer import …`，`__all__` 6 符号 | build_forward_output, render_reviewed_output, review_capability_result, should_forward_by_node_count, should_forward_long_text, split_text_chunks | 经 renderer/reviewer 垫片二跳达 `domains/render/{renderer,reviewer}` |
| 2 | `output/bot_avatar.py` | 星转发 | `*`（真身 `__all__` 面） | `domains/render/bot_avatar` |
| 3 | `output/plain_text.py` | 星转发 | `*` | `domains/render/plain_text` |
| 4 | `output/render_backends.py` | 星转发 + 3 具名私有 | `*` + `_MERMAID_CDN_URL, _RENDER_READY_SIGNALS, _wait_render_budget` | `domains/render/render_backends` |
| 5 | `output/renderer.py` | 星转发 | `*` | `domains/render/renderer` |
| 6 | `output/reviewer.py` | 星转发 + 1 具名私有 | `*` + `_unsafe_output_reasons` | `domains/render/reviewer` |
| 7 | `output/roleplay.py` | 星转发 | `*` | `domains/render/roleplay` |
| 8 | `output/templates.py` | 星转发 | `*` | `domains/render/templates` |

### 1.2 `output/card_render/`（6 个 .py + 1 空目录）

| # | 垫片文件 | 形态 | 转发面（逐符号实读） | 真身 |
|---|---|---|---|---|
| 9 | `card_render/__init__.py` | **中继**：`from .bridge import …` + `from .models import …`，`__all__` 6 符号 | PLATFORM_COLORS, PLATFORM_OFFICIAL_NAMES, ForwardPayload, RenderPayload, parse_to_render_payload, render_universal_card_html | 经 bridge/models 垫片二跳 |
| 10 | `card_render/bridge.py` | 星转发 + **~130 具名**（全仓最大转发面） | `*` + 全部公开渲染函数（render_universal/affinity/finance/market/mermaid/song_candidates/**error**_card_html、render_mermaid_png 等）+ 私有 `_darken/_hex_to_rgb/_rgb_to_hex/_derive_wash_tokens/payload_phase/digest_phase/stable_payload_digest/_MERMAID_READY_JS/_TEMPLATES_DIR/…` + 真身 import 进来的 Any/Path/annotations/json/re/… | `domains/render/card_render/bridge` |
| 11 | `card_render/mica_shell.py` | 星转发（**v21r3 新增**，2026-09-18 23:28，git 未跟踪 `??`） | `*`（docstring 明言：全仓确认零代码引用，补垫片纯为一一对应） | `domains/render/card_render/mica_shell` |
| 12 | `card_render/models.py` | 星转发 + 6 具名 | `*` + Any, ForwardPayload, RenderPayload, annotations, asdict, dataclass, field | `domains/render/card_render/models` |
| 13 | `card_render/theme_tokens.py` | 星转发 + ~60 具名 | `*` + BRAND_THEME/PLATFORM_THEMES/SHADOW_*/GAP_SCALE_PX/TYPE_SCALE_PX/CARD_SHELL_WIDTHS/derive_wash_tokens/theme_to_css_vars/get_platform_theme/… | `domains/render/card_render/theme_tokens` |
| 14 | `card_render/usage_cards.py` | **特殊：跨模块补转发**（非纯透传） | ①自 **theme_tokens 真身** 补转发 BRAND_THEME/FONT_FAMILY_STACK/SHADOW_PRIMARY/SHADOW_SECONDARY（真身 usage_cards 已不 import 这些）；②自 usage_cards 真身 `*` + 具名（render_usage_card_png/usage_card_accent/usage_report_mica_html/DIVIDER/GLOW_ACCENT/SURFACE_TINTS/_fmt_int/…） | `domains/render/card_render/{theme_tokens,usage_cards}` |
| 15 | `card_render/templates/` | **空目录**（7 张 .html 已删） | git 呈 **D 态**（affinity/error/finance/market/mermaid/song_candidates/universal_card.html） | `domains/render/card_render/templates/`（7 张真身在位，verify_hashes 已锚真身） |

**转发面总转出名**：output/ 6+1+1+4+1+2+1+1（含中继）≈ 星面不可枚举；card_render/ 具名面 6+~130+0+7+~60+~20 ≈ **220+ 具名符号**（bridge 一家占 ~130）。

---

## 二、消费面普查（当前工作树 grep，全仓 plugins/tests/scripts/bot.py）

**总量**：60 文件 / ~78 处 import。动态导入（importlib/`__import__`）**0 处**；裸包 `import …output` **0 处**；config.py/.env.example 路径引用 **0 处**；bot.py **0 处**。

### 2.1 生产侧 plugins/（22 文件 33 处）——全部仍走旧路径

| 消费方（file:line） | 消费符号 | 真身等价 | 难度 |
|---|---|---|---|
| control_plane/actions.py:25 | plain_text.redact_local_secrets | domains/render/plain_text | 一行改路径 |
| control_plane/events.py:31 | 同上 | 同上 | 一行 |
| control_plane/workspaces.py:25（相对 `..output.plain_text`） | 同上 | 同上 | 一行（相对改绝对或 `..domains.render.plain_text`） |
| chat_reply/capabilities/chat.py:70 | plain_text.{naturalize_chat_text, redact_local_secrets} | 同上 | 一行 |
| chat_reply/capabilities/chat.py:74 | roleplay.{format_roleplay_paragraphs, normalize_paragraph_breaks, strip_action_brackets, strip_outer_speech_quotes} | domains/render/roleplay | 一行 |
| chat_reply/capabilities/chat.py:2301 | reviewer._unsafe_output_reasons（**私有符号**） | domains/render/reviewer | 一行（真身有同名定义，垫片显式转发已证可达） |
| chat_reply/capabilities/chat.py:2347 | plain_text.humanize_reply | domains/render/plain_text | 一行 |
| chat_reply/capabilities/echo.py:3217 | bridge.{_darken, _hex_to_rgb, _rgb_to_hex}（**私有**） | domains/render/card_render/bridge | 一行 |
| chat_reply/capabilities/echo.py:3281 | bridge.{_derive_wash_tokens, payload_phase}（**私有**） | 同上 | 一行 |
| chat_reply/character/knowledge_service.py:45 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |
| chat_reply/runtime/pipeline.py:57 | **经 output 包 __init__**：build_forward_output, render_reviewed_output, review_capability_result, should_forward_by_node_count, should_forward_long_text | domains/render/{renderer,reviewer}（拆两处 import） | 需拆包init面→两模块，5 行 |
| files/capabilities/download.py:23 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |
| finance/capabilities/fx.py:32 | bot_avatar.bot_avatar_uri | domains/render/bot_avatar | 一行 |
| finance/capabilities/fx.py:147 | bridge.render_finance_card_html | …/card_render/bridge | 一行 |
| finance/capabilities/market.py:33 | bot_avatar.bot_avatar_uri | domains/render/bot_avatar | 一行 |
| finance/capabilities/market.py:244 | bridge.render_finance_card_html | …/bridge | 一行 |
| finance/capabilities/market.py:669 | bridge.render_market_card_html | …/bridge | 一行 |
| finance/capabilities/stocks.py:51 | bot_avatar.bot_avatar_uri | domains/render/bot_avatar | 一行 |
| finance/capabilities/stocks.py:435 | bridge.render_finance_card_html | …/bridge | 一行 |
| finance/capabilities/stocks.py:478 | 同上 | 同上 | 一行 |
| link_parse/capabilities/content_parser.py:45 | bot_avatar.bot_avatar_uri | domains/render/bot_avatar | 一行 |
| link_parse/capabilities/content_parser.py:380 | templates.{card_payload_from_parse, render_media_card_html, render_universal_card_html} | domains/render/templates | 一行 |
| media/capabilities/media_archive.py:40 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |
| music/capabilities/music.py:33 | bot_avatar.bot_avatar_uri | domains/render/bot_avatar | 一行 |
| music/capabilities/music.py:627 | templates.render_song_candidates_html | domains/render/templates | 一行 |
| ops/admin/debug.py:707 | bridge.{_darken, _hex_to_rgb, _rgb_to_hex}（**私有**） | …/bridge | 一行 |
| ops/admin/debug.py:737 | bridge.{_derive_wash_tokens, payload_phase}（**私有**） | …/bridge | 一行 |
| ops/monitor/alerts.py:40 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |
| ops/monitor/error_report.py:70 | 同上 | 同上 | 一行 |
| ops/monitor/error_report.py:828 | render_backends.build_render_backend | domains/render/render_backends | 一行 |
| ops/monitor/error_report.py:851 | bridge.render_error_card_html | …/bridge | 一行 |
| ops/monitor/event_store.py:48 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |
| ops/monitor/usage_monitor.py:496 | usage_cards.{render_usage_card_png, usage_report_mica_html} | domains/render/card_render/usage_cards | 一行 |
| ops/smoke/console_chat.py:98 | render_backends.build_render_backend | domains/render/render_backends | 一行 |
| transport/sender/nonebot.py:33 | plain_text.redact_local_secrets | domains/render/plain_text | 一行 |

**根 `__init__.py` 已改真身**（:2168 `from .domains.render.bot_avatar import refresh_from_qq`、:2189 bot_avatar_uri；:2181 仅 docstring 旧口径残留）。v21r2 库存文档所记「bot_avatar/render_backends 含根 __init__ 消费方」**已过时**。

### 2.2 scripts/（4 文件 5 处）

| 消费方 | 消费符号 | 真身等价 | 难度 |
|---|---|---|---|
| e2e_acceptance.py:126 | render_backends.build_render_backend | domains/render/render_backends | 一行 |
| fetch_mermaid_js.py:36 | render_backends.{mermaid_asset_dir, validate_mermaid_asset_bytes} | 同上 | 一行 |
| measure_latency_chains.py:98 | render_backends.PlaywrightRenderBackend | 同上 | 一行 |
| render_card_samples.py:81 | render_backends.build_render_backend | 同上 | 一行 |
| render_card_samples.py:830 | templates.render_media_card_html | domains/render/templates | 一行（注意：同文件 :78 的 usage_cards 已改真身——**混合态先例**） |

### 2.3 tests/（34 文件 ~40 处）

| 消费方 | 垫片（消费符号摘录） |
|---|---|
| test_affinity_query.py:372 | bridge.render_affinity_card_html |
| test_auditfix_sender_queue.py:29-30 | plain_text.naturalize_chat_text；renderer.split_text_chunks |
| test_batch_cdf_modules.py:11 | plain_text.humanize_reply |
| test_browser_ctx_leak.py:27 | render_backends.PlaywrightRenderBackend |
| test_chat_and_sources_regressions.py:9/302/350 | roleplay.strip_outer_speech_quotes；renderer.render_reviewed_output；plain_text.naturalize_chat_text |
| test_error_report.py:899 | render_backends.PlaywrightRenderBackend |
| test_forward_and_mood.py:18 | renderer.{build_forward_output, should_forward_by_node_count, split_text_chunks} |
| test_help_card_twocol.py:21 | theme_tokens.GAP_SCALE_PX |
| test_market_card.py:30 | bridge.render_market_card_html |
| test_mermaid_reply_render.py:219/307 | render_backends._MERMAID_CDN_URL（私有）；PlaywrightRenderBackend |
| test_metric_labels.py:11 | templates.card_payload_from_parse |
| **test_mica_builders_contract.py:41** | **templates.render_media_card_html（仍旧路径）；同文件 :31-38 的 mica_shell/theme_tokens/usage_cards 已改真身——混合态** |
| test_outdomain_fixes_20260911.py:41 | plain_text.humanize_reply |
| test_parse_presentation_v2.py:20 | bridge.render_universal_card_html |
| test_phase0_3_features.py:85/96/191 | reviewer.review_capability_result；renderer.render_reviewed_output ×2 |
| **test_phase_determinism.py:27/39/282** | **bridge（8 渲染器+3 相位函数）、templates.render_media_card_html、render_backends.build_render_backend（均仍旧）；:24 usage_cards 已改真身——混合态** |
| test_phase_determinism_2.py:27/32/176 | bridge ×3；usage_cards.usage_report_mica_html；render_backends.build_render_backend |
| test_poke_v2.py:25 | renderer.render_reviewed_output |
| test_render_backends.py:5 | render_backends 多符号 |
| test_render_card_samples.py:158/179 | bridge._MERMAID_READY_JS（私有）；theme_tokens.ERROR_ACCENT |
| test_render_image_cache.py:19 / test_render_launch_backoff.py:29 / test_render_phase2_env_keys.py:28 / test_render_wait_budget.py:25 | render_backends 族 |
| test_rendering_contract.py:61 | render_backends.{NullRenderBackend, PlaywrightRenderBackend} |
| test_roleplay_paragraphs.py:8 | roleplay.{format_roleplay_paragraphs, normalize_paragraph_breaks} |
| test_sdd9_n3re.py:40 / test_secret_redaction_hardening.py:17 | plain_text.redact_local_secrets |
| test_token_supply_chain.py:64 | templates.render_media_card_html（:10 已读真身模板路径——混合态） |
| test_tts_outbound_chain.py:27 | renderer.render_reviewed_output |
| test_universal_card_projection.py:24 | templates.{card_payload_from_parse, render_universal_card_html} |
| test_usage_card.py:22/25、test_usage_card_channels.py:37/40 | theme_tokens.derive_wash_tokens；usage_cards 渲染函数 |
| test_v21r3_visual_gates.py:57 | templates.render_media_card_html（:42-54 已大量走真身——混合态） |

### 2.4 零消费面（实核）

- `output/card_render/__init__.py`（包中继）：外部消费 **0**；
- `output/card_render/models.py`：外部消费 **0**（仅被包 __init__ 内部中继）；
- `output/card_render/mica_shell.py`：全仓消费 **0**（垫片自身 docstring 亦承认）；
- `output/card_render/usage_cards.py` 的 **theme_tokens 补转发段**（BRAND_THEME/FONT_FAMILY_STACK/SHADOW_PRIMARY/SHADOW_SECONDARY）：当前消费 **0**（test_mica_builders_contract.py:31-35 已改从真身 theme_tokens 取）；
- `output/__init__.py` 包面：生产消费仅 pipeline.py:57 一处。

### 2.5 任务点名消费点现状核实结论

| 点名对象 | 现状（以当前树为准） |
|---|---|
| test_mica_builders_contract.py:41 | **仍走旧** output.templates（render_media_card_html 一行）；其余导入已真身化 |
| test_phase_determinism.py | **仍走旧**（bridge:27/templates:39/render_backends:282）；usage_cards:24 已真身化 |
| echo.py | 真身在 domains/chat_reply/capabilities/，**仍 import 旧 bridge**（:3217/:3281 私有符号） |
| debug.py | 真身在 domains/ops/admin/，**仍 import 旧 bridge**（:707/:737 私有符号） |
| error_report.py | 真身在 domains/ops/monitor/，**仍走旧** plain_text:70/render_backends:828/bridge:851 |
| content_parser.py | 真身在 domains/link_parse/capabilities/，**仍走旧** bot_avatar:45/templates:380 |
| 根 __init__.py | **已真身化**（bot_avatar 两处），仅 :2181 docstring 旧口径文字残留 |

---

## 三、三档分类

### A 档：改写/直删即可退役（消费方全在 tests/ 或零消费）——4 张

| 垫片 | 依据 | 动作 |
|---|---|---|
| card_render/mica_shell.py | 零消费 + git 未跟踪 | 直接删（零回归面） |
| card_render/models.py | 零外部消费 | 删（与包 __init__ 同批） |
| card_render/theme_tokens.py | 消费方全 tests/（4 文件 5 处） | 改 4 测试文件 import 路径→删 |
| card_render/__init__.py | 零外部消费（包锚） | 删（目录收尾时） |

### B 档：需生产/脚本代码改写——11 张

| 垫片 | 生产/脚本消费面 | 测试消费面 |
|---|---|---|
| plain_text.py | 12 处/11 文件（redact 族为主） | 6 文件 |
| bot_avatar.py | 6 处/6 文件（统一 bot_avatar_uri） | 0 |
| bridge.py | 11 处/7 文件（含 5 种私有符号） | 6 文件 |
| render_backends.py | 2 处生产 + 4 处脚本 | 12 文件 |
| templates.py | 2 处生产 + 1 处脚本 | 6 文件 |
| usage_cards.py | 1 处（usage_monitor.py:496） | 3 文件；theme 补转发段零消费可随删 |
| renderer.py | 经 output/__init__ ← pipeline.py:57 | 7 文件 |
| reviewer.py | chat.py:2301（私有 _unsafe_output_reasons）+ 经包 __init__ | 1 文件 |
| roleplay.py | chat.py:74（4 符号） | 2 文件 |
| output/__init__.py | pipeline.py:57（唯一） | 0（测试均直连子模块垫片） |
| usage_cards.py 补转发段 | —（并入上行） | — |

### C 档：必须保留或特殊处理——2 类

1. **无一张代码垫片必须永久保留**——所有具名转发（含私有符号）在真身均有同名定义（垫片显式转发本身即可达性证明），无逻辑唯一存在于垫片者。`usage_cards.py` 的跨模块补转发段是唯一「垫片含转发逻辑」件，但其消费面已归零，属可退役。
2. **特殊处理面**：
   - **verify_hashes TRACKED_FILES（tests/verify_hashes.py:33-59，19 项）**：**零旧路径登记**（全部锚 domains 真身 + docs/DESIGN-SPEC）→ 退役**无哈希清单联动**，`--check` 应零漂移（已实核清单原文）。
   - **文档引用旧路径（12+ 处，退役时需同步改口径，不阻塞代码）**：docs/rendering-contract.md:3、docs/HANDBOOK.md:257/:1136、docs/acceptance-manual.md:127、docs/THIRD_PARTY_NOTICES.md:6（MIT 出处地，改标题路径须保留正文）、docs/design/fstring-card-dom-spec.md（多处）、docs/design/visual-effects-catalog.md:5、docs/design/frontend-render-expansion-plan.md:19/:279、docs/design/backend-protocol-plan.md:258、docs/design/control-plane-api.md:26、docs/design/v21r3-render-unification-plan.md:49、docs/design/codebase-slim-plan.md、docs/HANDOVER-2026-09-15.md:49、docs/issue-ledger-p2-p3.md:142。
   - **git D 态 7 张模板**：属未提交删除，退役提交需与整个 output/ 目录移除同一批次语义（提交裁决权在用户）。
   - **相邻域提醒（非本席范围）**：`capabilities/echo.py`、`capabilities/debug.py` 也是 PEP562 垫片（RWC3/RWOC 波），test_v21r3_visual_gates.py:42-43 / test_mica_builders_contract.py:25-26 仍从其取 `_help_mica_html/_llm_setup_mica_html`——渲染域退役不依赖它们，但同属「渲染出卡 builder 链」的旧路径残留，建议另立工单。

---

## 四、退役工单（供 INTG/用户裁决；本预研不执行）

### 4.0 执行前置（裁决门）

1. **在飞占域确认**：v21r4-b QA 探针（docs/design/v21r4-b-qa-probe-report.md §七）曾将「domains/render/**、output/card_render/**、视觉门禁族」列为在飞未定性的唯一破坏面；2026-09-19 SWITCH 席已收口，但执行前必须由 INTG 确认无新席占用 output/ 垫片面。
2. **提交裁决**：工作树多会话共享，7 张模板 D 态 + 本轮全部改动未 commit；退役是删除性大动作，提交与批次划分归用户。

### 4.1 安全顺序与文件数估算

| 步 | 动作 | 涉及文件数 | 验证 |
|---|---|---|---|
| 1 | **改写生产侧**（B 档 plugins 33 处）：机械路径替换 `bot_unified_runtime.output` → `bot_unified_runtime.domains.render`（pipeline.py:57 需拆包 init 面为 renderer+reviewer 两处） | 22 文件 | ruff + mypy + 受影响域测试（chat_reply/finance/ops/link_parse/music/media/transport/control_plane） |
| 2 | **改写脚本侧**（5 处） | 4 文件 | 语法级 + render_card_samples DRY 路径 |
| 3 | **改写测试侧**（~40 处；A 档 theme_tokens 4 文件一并） | 34 文件 | 全量 dev.ps1 -Task test |
| 4 | **单删垫片**：先 card_render/{mica_shell,models,theme_tokens,__init__} → bridge/usage_cards → output/ 其余 7 .py → `output/__init__.py` 最后 → 连带 git rm 7 张 D 态模板与空目录（output/ 整目录消亡） | 15 .py + 目录 | import 冒烟（python -c 逐模块）+ runtime-layout |
| 5 | **文档口径同步**：§三 C 档 12+ 处旧路径改真身口径；:2181 根 __init__ docstring 顺带 | ~13 文档 | doc_sync 类门禁（如有）+ verify_hashes --check（应零漂移） |
| 6 | **全量回归四门禁**：dev.ps1 test / lint / typecheck / runtime-layout | — | 全绿为完成判定 |

**顺序不可倒置的原因**：output/__init__.py 是包结构锚，先删会让一切 `…output.*` import 在收集期即断；而任何一步「先删后改」都会把可灰度的改写变成硬断言。步 1-3 全部完成前，垫片面保持只读。

### 4.2 verify_hashes 联动

**无**。TRACKED_FILES 19 项全部锚真身（7 张 domains 模板 + domains bridge/usage_cards/renderer/templates/theme_tokens + ops/debug + chat_reply/echo + docs 三规格）——2026-09-14 K-06 扩面时即按真身登记。退役全程不应触发任何 `--write`。

---

## 五、风险点

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | 在飞波冲突（历史 RWOC/QA 探针显示渲染域曾是唯一破坏面） | 高 | 执行前 INTG 占域确认 + 单批次原子完成，不留半改状态过夜 |
| 2 | bridge 具名面 ~130 符号中混有真身 import 进来的非本模块符号（Any/Path/annotations/os/re/…）——若有人消费这些病态名，改写后断 | 低 | 全仓 grep 实核：现役消费全部为渲染函数/私有函数，无病态消费；改写时按 §二表逐符号对照即可 |
| 3 | 私有符号跨模块导入（echo/debug/chat 的 `_darken` 等 5 种 + `_MERMAID_CDN_URL`/`_unsafe_output_reasons`/`_MERMAID_READY_JS`）在真身均有定义（垫片显式转发即证明），但属脆弱耦合 | 中 | 改写只换路径不改符号；后续可立「私有符号公开化」小工单（bridge G8 缺 render_error_card_html 于 `__all__` 一事见 closing-spec 0.3-G8，改走真身后靠显式 import 不受 `__all__` 影响） |
| 4 | 改写 ~60 文件 import 行触发 ruff I001/isort 重排噪音 | 低 | 顺带 `ruff --check` 单批次格式化，禁夹带逻辑改动 |
| 5 | 文档口径漂移（12+ 处）违反 doc_sync 类门禁/交接真实性 | 中 | 步 5 显式列清单收口；THIRD_PARTY_NOTICES 只改路径标题、正文出处不动 |
| 6 | 多会话共享工作树：退役删除与其他席新增 import 旧路径竞态 | 中 | 执行窗口内声明 output/ 冻结；删后 grep 复核零残留 |
| 7 | 未部署生产进程仍在跑旧代码（重启前无影响；退役只动源码树不动 Runtime） | 信息 | 与既有「重启生效」纪律一致，无额外动作 |

---

## 六、结论一句话

渲染域旧路径 15 .py 垫片 + 1 空目录**全部具备退役条件**：零哈希清单联动、零动态导入、零配置引用；A 档 4 张可直接退役，B 档 11 张需先机械改写 60 文件 ~78 处（一行换路径为主，唯 pipeline.py:57 需拆包 init 面）；唯一「垫片含逻辑」的 usage_cards 补转发段消费面已归零。执行窗口与提交裁决归 INTG/用户。
