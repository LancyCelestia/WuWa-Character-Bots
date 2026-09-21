# 席位 U5-ARCH：统一架构审计（2026-09-20）

> **性质**：只读审计席位（架构/目录统一）。零代码/配置改动、零 git 写、零子代理、零真实发送/重启。唯一落盘物=本文件。
> **总问题**：用户 mandate「统一架构——一个能力只有一个真身位置、一套分层规则、一条 import 通路」。本席度量「20 域 + 12 旧顶层目录并存」的**真实收敛度**。
> **快照口径**：2026-09-20 工作树实盘（v21r5 时点，全部未 commit）。行号=取证时刻；每条发现附锚点字符串，行号漂移时以锚点重定位。
> **数字纪律**：以下全部计数为扫描器实跑输出（§1 给可复跑命令与脚本全文附录），不是文档旧口径的转抄；与 HANDOFF 宣称差异处**如实并列双方**。

---

## §0 结论一页版

**判定：统一架构三要素（单真身/单分层/单通路）当前均未成立；但「最恶性形态（双真身互抄漂移）」经实测为零，存量问题集中在"垫片通路未剪"而非"内容分叉"。**

| 严重度 | 数 | 条目 |
|---|---|---|
| P0 | 2 | F-01 qx.json 资产错位（新址未跟踪+旧址残留索引+第四删除风险窗重开）；F-02 `sources import web_search` 已删路径 import 仍在盘=活 ImportError 雷（audit-20260919 P0-2 同坐标复发） |
| P1 | 6 | F-03 domains→旧路径 413 边/117 文件（单通路未成立）；F-04 control_plane↔domains 双向成环+私有名穿仓；F-05 跨域直入实现 55 边（绕契约层）+公共件私藏；F-06 divination 域内双 `DrawStore`（能力链 vs V2.1 服务链各一份真身）；F-07 三套坐标系分歧实证（14/20/34/77）；F-08 根 `__init__.py` 8676 行/5125 行巨函数（一切耦合枢纽） |
| P2 | 5 | F-09 垫片层实测 158 张（死 14/仅测试 33/生产在消费 111）且两形态并存；F-10 模块级循环 5+组件级超级 SCC；F-11 20 域无统一内部骨架+重逻辑住包 `__init__`；F-12 生产不可达模块 119（测试独占 84/完全孤儿 ~20）+third_party 从未装载；F-13 依赖漂移（playwright/fastapi/pydantic 等未声明、curl_cffi 全树零 import 仍装） |
| P3 | 2 | F-14 数据路径卫生（主体安全；残余=4 处「except→相对路径」回落家族，其一 parents[3] 深度算错）；F-15 `.tmp-test/` 源码树残留+`.gitignore` 负规则指向已删路径 |

**与交接宣称的对照（交接口径完整性）**：HANDOFF-V21R5 §D 称「AST 旧路径 import 残余 **0**」（主代理 RET2b 席）与 §F 称「残留旧路径 import 22 点全为合法保留」（RWC5-b 席）。本席全树复扫：**残余非 0——按本席口径生产面（domains/旧目录/control_plane/bot.py/scripts）= 413+56+48 = 517 边，tests 另计 875 边**；根 `__init__.py` 单文件旧路径边 18 条（与"22 点合法"量级相符但目标状态含垫片，见 §2）。差异定性：前任「残余 0」的口径大概率只覆盖**其退役那 3 张垫片自身的直接消费边**，非全树全旧路径面；本项目缺一个统一定义的「旧路径残余」机器门，导致同一指标在不同日志中口径漂移（收敛路线 R-2 处置）。

---

## §1 方法与可复跑命令

### 1.1 环境纪律（本席全程执行）

```powershell
# 工作区
C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
# 解释器（唯一）
../ChatBot_Runtime/venv/Scripts/python.exe     # 3.12.10
# 所有直跑命令统一前缀
$env:PYTHONDONTWRITEBYTECODE=1; $env:PYTHONUTF8=1; $env:BOT_AUTOSYNC=0
```

扫描脚本与本席全部原始输出落 `%TEMP%\u5arch\`（源码树外）：
- `C:\Users\LancyCelestia\AppData\Local\Temp\u5arch\scan_u5.py`（主扫描器，全文见**附录 A**）
- `...\u5arch\out\u5-imports.md / u5-shims.md / u5-dual.md / u5-layers.md / u5-root.md / u5-orphans.md / u5-paths.md / u5-deps.md`

```powershell
# 复跑（全部分节，秒级～1 分钟，零写入源码树）
cd C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "$env:LOCALAPPDATA/Temp/u5arch/scan_u5.py" "$env:LOCALAPPDATA/Temp/u5arch/out"
```

> ⚠️ 临时目录会被清理；**脚本全文已随本文件附录 A 入库**，需要复跑时从附录 A 重建 `scan_u5.py` 即可（纯 stdlib、只读、零输出到源码树）。

### 1.2 扫描器算法摘要

1. **模块索引**：`plugins/ tests/ scripts/ third_party/` + 根级 `*.py` 全量 `ast.parse`（1300+ 文件），零解析失败（§2 末表）。
2. **边采集**：`Import/ImportFrom`（含**相对 import 归一为绝对**）→ 记录消费方/目标/行号/顶层-or-deferred；`from pkg import name` 双解析（属性名若为子模块则补边——即 RET2b 记录过的「包级 from-import 盲区」的克星）；字符串形态引用（`"plugins.bot_unified_runtime.…"` 点分串、`plugins/bot_unified_runtime/….py` 路径串、`importlib.import_module` 常量、`scripts/*.ps1` 内引用）一并计入「消费」。
3. **垫片分类**：旧顶层目录（12 个）+包根 4 个历史模块内：`_CANONICAL(_PKG)`+`__getattr__`=PEP562 活转发；`import * from domains`=star 薄转发；只 import domains 且无 def/class 的命名转发=thin-reexport；其余=real/aggregator/empty-init。
4. **表①分类**：A 垫片自身｜B 真身未迁合法保留（目标=real）｜C1 生产消费垫片｜C2 tests 消费垫片｜C3 脚本/bot.py 消费垫片｜**D domains 反向 import 旧顶层**｜**E 悬空/属性缺失**（`from pkg import X` 且 X 既非 pkg 定义名、亦无 `pkg/X.py`、pkg 无 star——运行期 ImportError 判定器）。
5. **表③双真身**：domains/ 与旧目录**同名 .py 且双方皆非转发件**（mirror 路径推断+basename 双联）→ sha256 全文比对 + `__all__` 比对 + **函数级归一化 AST 哈希**漂移检测。
6. **分层/循环**：domain→domain（按目标是否 `*.contracts*` 拆「经契约」vs「直入实现」）、domains→旧顶层、control_plane→domains、domains→control_plane；Tarjan SCC 三个粒度（模块级含包 `__init__` 边/排除之/组件级）。
7. **孤儿**：生产根={`bot.py`, 插件包根}+动态字符串边，可达性闭包；父包 `__init__` 随子模块导入自动可达（已修首轮假阳性）。分类：测试独占/脚本独占/完全孤儿。
8. **路径卫生**：`"data/…"` 字面量全树扫描+同行防护词标记+相对 open/makedirs/Path 复核表；依赖：pyproject vs 全树第三方 top-level import 差集+同功能桶。

### 1.3 本席未做（边界如实）

- 未跑全量 pytest（纪律）；未做任何写入源码树/`ChatBot_Runtime/` 的操作；在飞禁改面（domains/render、output/card_render、theme_tokens、render_hashes、capabilities/echo.py、domains/media/capabilities/tts.py）**只读引用**，本席全部建议不触碰其内部实现。

---

## §2 表①：旧路径 import 残余（三分类 + 三细类）

### 2.1 分类统计（全树实跑）

| 类别 | 边数 | 说明 |
|---|---|---|
| A-垫片自身转发 | **0** | 垫片全部只 import domains/，形态干净 |
| B-真身未迁合法保留 | **39** | 目标=real（详见 2.2，生产边仅 5 处/3 文件） |
| C1-生产（旧目录/control_plane）消费垫片 | **56** | 全部为「旧目录残存真身 + control_plane 服务层」经垫片取物 |
| C2-tests 消费垫片 | **875** | 287 个测试文件（按文件计数见 2.6） |
| C3-脚本/bot.py 消费垫片 | **48** | `bot.py:481`(mail_adapter，**设计内**，reorg 方案书明文钉死) + e2e/工具脚本 47 边 |
| D-domains 反向 import 旧顶层 | **413** | 117 个域文件（聚合见 2.5）——本表最大项 |
| E-悬空/属性缺失 | **1** | **F-02 地雷**（见 2.7） |
| 合计 | **1432** | |
| AST 解析失败文件 | 0 | 全树 1300+ py 文件 parse 干净 |

### 2.2 B 类（真身未迁合法保留）全量——按消费方聚合

| 消费方 | 边数 | 行:目标 |
|---|---|---|
| `plugins/bot_unified_runtime/__init__.py` | 2 | :3631→`runtime.loop_watchdog`；:4254→`runtime.service_wiring`（deferred） |
| `runtime/capability_protocols.py` | 2 | :1178→`sources.acg_search`、`sources.search_intent`（deferred，真身未迁实锤：`sources/acg_search.py` 有 187 行真身） |
| `runtime/service_wiring.py` | 1 | :126→`runtime.database_broker`（deferred） |
| `sources/acg_search.py` | 1 | :39→`sources.search_intent`（真身引用真身，合法） |
| `scripts/extract_trigger_words.py` | 1 | :376→`capabilities`（空 `__init__` 取目录名） |
| tests 25 文件 | 31 | `runtime.capability_protocols`/`runtime.database_broker`/`runtime.loop_watchdog`/`sources.acg_search`/`sources.search_intent`/`capabilities`(空 init) 等 |

**判定**：生产面合法保留边=5（与 RWC5-b 宣称的「loop_watchdog/runtime.service_wiring 等真身未迁」一致；其「22 点」口径含根文件内垫片消费 18 条中部分——该 18 条实际目标状态多为 shim，归入 D/C 口径，见 2.4）。`control_plane` 四旧路径边（settings/ledger/model_router/plain_text，表 2.3）在其「缓迁」登记内，但**目标已是垫片**，不属 B。

### 2.3 C1 生产消费垫片（56 边全量）

| 消费方 | 行 | 目标旧路径 | 形态 | 顶层? |
|---|---|---|---|---|
| `__init__.py` | 21 | `audit` | pep562 | T |
| `__init__.py` | 23,2882,3001,3161,3318,7451-7454,8521 | `contracts`（×9 处） | pep562 | 混 |
| `__init__.py` | 191 | `llm` | pep562 | T |
| `__init__.py` | 3610,3824,3837 | `policy`、`policy.gate`（×3） | pep562 | deferred |
| `__init__.py` | 7358 | `security.content_safety` | pep562 | deferred |
| `character/__init__.py` | 1,2,8,17,23 | `character.{addressing,emotion,history,memory,providers}`（聚合器转垫片） | pep562 | T |
| `control_plane/_app.py` | 324,376,783 | `runtime.settings`、`llm.ledger`、`llm.channel_health` | pep562 | deferred |
| `control_plane/actions.py` | 25 | `output.plain_text`（`redact_local_secrets`） | star | T |
| `control_plane/api/platform.py` | 358,393,410,422 | `sources.file_reader`、`sources.vision_describe`×2、`sources.transcribe` | star/pep562 | deferred |
| `control_plane/config_service.py` | 13 | `runtime.settings`（含 RESTART_REQUIRED_KEYS/SETTABLE_KEYS） | pep562 | T |
| `control_plane/config_store.py` | 44,251 | `runtime.settings` | pep562 | deferred |
| `control_plane/events.py` | 31 | `output.plain_text` | star | T |
| `control_plane/factory.py` | 78,79,80 | `character.documents`、`llm.model_router._resolve_api_key`（**私有名**）、`llm.providers` | pep562 | deferred |
| `control_plane/llm_admin.py` | 83,146,200,231,306,335,376,379 | `llm.model_router`×5（含 `_resolve_api_key/_preset_specs/_demote_cooling_candidates/_health_filter_candidates` **私有名×4**）、`llm.channel_health`×2 | pep562 | deferred |
| `control_plane/sandbox.py` | 15 | `llm.providers` | pep562 | T |
| `control_plane/workspaces.py` | 25 | `output.plain_text` | star | T |
| `output/__init__.py` | 1,8 | `output.renderer`、`output.reviewer`（聚合器转 star 垫片） | star | T |
| `output/card_render/__init__.py` | 3,9 | `output.card_render.bridge`、`.models` | star | T |
| `runtime/__init__.py` | 1 | `runtime.pipeline` | pep562 | T |
| `runtime/database_broker.py` | 458 | `llm.ledger.resolve_default_db_path` | pep562 | deferred |
| `runtime/loop_watchdog.py` | 55 | `runtime.pipeline._get_chat_pool`（**私有名**） | pep562 | deferred |
| `sources/__init__.py` | 3 | `sources.registry`（聚合器转 star 垫片） | star | T |
| `sources/acg_search.py` | 35,182 | `sources.parsers.http_util`、`sources.moegirl` | star/pep562 | 混 |

**要点**：control_plane 22 条 + 根 `__init__.py` 18 条 + 旧聚合器互转（character/output/runtime/sources 四个旧包 `__init__` 现在只是「垫片套垫片」二级跳）。`llm_admin.py` 经旧路径垫片连踩 4 个下划线私有名——垫片退役时（llm/* 属退役队列）**必炸 control_plane**，这是 F-04 的前置件。

### 2.4 D 类：domains 反向 import 旧顶层（413 边，域×旧顶层矩阵摘要 + 按文件 Top 全量）

**域×旧顶层（边数降序，全 84 对之 Top20）**：chat_reply→capabilities 32｜ops→llm 26｜ops→runtime 25｜chat_reply→contracts 20｜ops→capabilities 21｜subscribe→sources 15｜chat_reply→character 14｜chat_reply→runtime 14｜chat_reply→sources 14｜finance→capabilities 14｜ops→character 14｜subscribe→capabilities 14｜chat_reply→output 10｜core→sources 10｜ops→output 9｜finance→output 8｜subscribe→contracts 8｜transport→contracts 7｜finance→runtime 5｜media→llm 5；**其余 64 对合计 165 边**（每对 1-5 边）。
状态分布：D 类 413 边中目标=垫片 ~390、目标=真身未迁(acg_search/search_intent) 3、目标=旧包聚合器/空 `__init__` ~20。

**按文件聚合（117 文件全量，格式 `文件 ×边数`）**：

```
domains/ops/admin/runtime_admin.py x33      domains/chat_reply/capabilities/chat.py x30
domains/chat_reply/runtime/base_router.py x24
domains/ops/smoke/console_chat.py x21       domains/chat_reply/capabilities/echo.py x12
domains/ops/admin/debug.py x11              domains/ops/smoke/smoke.py x10
domains/ops/smoke/route_demo.py x10         domains/core/credentials/platform_credentials.py x10
domains/ops/monitor/usage_monitor.py x9     domains/chat_reply/pipeline/backend_unit.py x9
domains/music/capabilities/music.py x8      domains/food/capabilities/eat.py x8
domains/finance/capabilities/stocks.py x8   domains/finance/capabilities/market.py x8
domains/link_parse/capabilities/content_parser.py x6
domains/finance/capabilities/fx.py x6       domains/subscribe/capabilities/today_history.py x5
domains/subscribe/capabilities/epic.py x5   domains/ops/monitor/error_report.py x5
domains/location/capabilities/moegirl.py x5 domains/chat_reply/runtime/pipeline.py x5
domains/chat_reply/capabilities/affinity.py x5
domains/weather/capabilities/weather.py x4  domains/subscribe/capabilities/subscribe.py x4
domains/subscribe/adapters/social_v2.py x4  domains/schedule/capabilities/reminder.py x4
domains/chat_reply/runtime/prompt_preview.py x4
domains/chat_reply/policy/gate.py x4        domains/transport/sender/nonebot.py x3
domains/transport/sender/file_gateway.py x3 domains/subscribe/feeds/news_feeds.py x3
domains/subscribe/capabilities/subscribe_v2.py x3
domains/subscribe/capabilities/news.py x3   domains/subscribe/adapters/bilibili_adapter.py x3
domains/notes/capabilities/notes.py x3      domains/media/ingest/vision_describe.py x3
domains/media/ingest/transcribe.py x3       domains/media/capabilities/media_archive.py x3
domains/media/capabilities/image_search.py x3
domains/files/capabilities/download.py x3   domains/divination/capabilities/divination.py x3
domains/chat_reply/runtime/natural_language.py x3
domains/transport/sender/worker.py x2       domains/transport/sender/queue.py x2
domains/transport/sender/onebot.py x2       domains/schedule/service/schedule_service.py x2
domains/ops/admin/runtime_logs.py x2        domains/meme/capabilities/meme.py x2
domains/media/ingest/video_understanding.py x2
domains/link_parse/support/parse_history.py x2
domains/finance/data/stock_data.py x2       domains/finance/data/market_data.py x2
domains/finance/data/fx_data.py x2          domains/finance/data/commodities_data.py x2
domains/files/capabilities/file_exchange.py x2
domains/core/search/search_service.py x2    domains/core/config/config_readiness.py x2
domains/chat_reply/policy/rate_limit.py x2  domains/chat_reply/character/shared_export.py x2
domains/chat_reply/capabilities/memory.py x2
domains/chat_reply/capabilities/group_info.py x2
domains/assistant/daily/store/daily_assist.py x2
（余 47 文件各 ×1：weather/data/{open_meteo,nmc_weather}、transport/sender/{receipts,gateway}、
subscribe/store/{subscription_store_v2,subscription_runtime_v2}、subscribe/feeds/{today_history,steamfree,epicfree}、
subscribe/adapters/{xiaohongshu_adapter,music_v2}、schedule/store/reminders、schedule/llm_draft、
schedule/auto_send/parser、render/{reviewer,renderer,card_render/bridge}、ops/monitor/{intent_telemetry,
event_store,disconnect_notice,alerts}、ops/features/feature_catalog、notes/store/notes_store、
music/data/music_charts、meme/capabilities/randpic、meme/capabilities/meme_library、media/video/video_pipeline 等，
完整清单复跑 §1.1 命令即得）
```

**恶性样例（自环，一句话铁证）**：`domains/chat_reply/capabilities/affinity.py:19` → `plugins…character.affinity`（垫片）→ `domains/chat_reply/character/affinity.py`（真身）——**域真身经自己家的旧门牌号绕一圈回自己**；chat_reply→contracts 20 边同理绕 `contracts/__init__` 垫片再到 `domains/core/contracts`。这种自环使「RET 垫片」永无出头之日：消费者自己就住在真身隔壁。

### 2.5 C2 tests 消费垫片（875 边/287 文件）——按旧顶层目录分解

`capabilities 200｜contracts 133｜runtime 107｜character 86｜sources 81｜sender 52｜output 42｜llm 36｜audit 22｜message_context 6｜mail_bridge 2｜mail_adapter 2｜decision 2｜其余(截断重复) ~5`

边数 Top10 文件：test_trigger_english.py×22、test_phase0_3_features.py×16、test_operational_failures.py×16、test_traditional_triggers_2.py×14、test_detail_and_priority.py×14、test_affinity_query.py×14、test_chat_and_sources_regressions.py×13、test_reactions.py×10、test_deadline_budget.py×9、test_time_window_summary.py×8。
**含义**：875 边是垫片退役的第二座山——RET3 席「消费方改指 canonical→AST 零残余」的方法在 tests 面完全适用且低风险（测试无生产行为），但**必须先有统一口径的残余机器门**（R-2），否则「残余 0」与「残余 1432」会继续在日志里同时为真。

### 2.6 C3 脚本/bot.py 消费垫片（48 边全量清单见 `%TEMP%\u5arch\out\u5-imports.md`）

- `bot.py:481` → `mail_adapter`（star 垫片，**reorg 方案书 §装载约束明文保留位**——「插件根包与 mail_adapter 符号面不可破坏」，本席判定：合法设计钉，退役此垫片时 bot.py 同批改指 canonical 即可）；
- `bot.py:401` → `character.kb_wiki`（deferred，可改指 domains.location.knowledge.kb_wiki）；
- `scripts/e2e_acceptance.py`×28（最大脚本消费方）、`render_card_samples.py`×4、`extract_trigger_words.py`×3、`measure_latency_chains.py`×2、`probe_intimate_route.py`×3、`fetch_mermaid_js.py`/`import_model_prices.py`/`knowledge_bench.py`/`clean_food_gallery.py`/`probe_trigger_hijack.py` 各 1-2。
- **移交记录**：`scripts/dev.ps1:867-868` 两处 `security.memory_sanitize` 旧路径在 HANDOFF §五阻塞终表已登记，与本席实测一致（ps1 面引用未计入本表 48 边，属 path-ref 消费，表②已计）。

### 2.7 E 类（1 边）＝ F-02 地雷全文（见 §12 F-02）

`runtime/capability_protocols.py:1272-1275`（`_WebChainAsSearchProvider.search()` 内）：

```python
from plugins.bot_unified_runtime.sources import (
    web_search,  # RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径
)
```

实盘：`plugins/bot_unified_runtime/sources/web_search.py` **不存在**（RET2b 主代理席已退役该垫片），`sources/__init__.py`（aggregator）也不定义 `web_search` 名 → 该 deferred import 一旦被执行即 `ImportError: cannot import name 'web_search'`。注释「垫片挂起」与事实相反（挂起决议已被主代理席撤销）。**同文件 :1128 `_web_provider_or_none` 已是正确写法**（`from …domains.core.search import web_search`），证明修复只做了第一处、漏了第二处。

---

## §3 表②：垫片清单与状态（158 张全量分类账）

### 3.1 总账

**旧顶层目录（12 个）+ 包根历史模块内转发件 = 158：PEP562 活转发 83，star/thin 命名转发 75。`_CANONICAL(_PKG)` 指向存在性 = 158/158 全部可解析（零断链）。**

| 旧顶层 | 张数 | 生产在消费 | 仅 tests 消费 | 死垫片（零消费） |
|---|---|---|---|---|
| capabilities | 37 | 29 | 7 | 1 |
| sources | 31 | 18 | 8 | 5 |
| character | 26 | 18 | 8 | 0 |
| runtime | 21 | 15 | 5 | 1 |
| output | 12 | 10 | 1 | 1 |
| sender | 7 | 4 | 3 | 0 |
| policy | 6 | 2 | 0 | 4 |
| llm | 5 | 5 | 0 | 0 |
| security | 4 | 2 | 1 | 1 |
| decision / contracts / audit | 2/2/1 | 1/2/1 | 0 | 1/0/0 |
| 包根（config_readiness/message_context/mail_adapter/mail_bridge） | 4 | 4 | 0 | 0 |
| **合计** | **158** | **111** | **33** | **14** |

### 3.2 死垫片（14 张，零消费含 tests——可立即退役）

```
capabilities/memory.py          decision/__init__.py
output/card_render/mica_shell.py  runtime/video_pipeline.py
policy/quiet_hours.py  policy/rate_limit.py  policy/reply_budget.py  policy/roles.py
security/__init__.py    （注：policy/security 的 __init__ 垫片属 RWC6-b 新拨，聚合器语义见 F-09 注）
sources/fetchers/__init__.py  sources/media_archive.py
sources/meme_library_listener.py  sources/subscriptions/__init__.py  sources/telegram_media.py
```

验证命令（每张）：`grep -rn "bot_unified_runtime\.<dir>\.<name>\b" plugins/ tests/ scripts/ bot.py *.ps1 scripts/*.ps1 | grep -v "^plugins/bot_unified_runtime/<dir>/<name>.py"` 应零命中（本席扫描器等价逻辑已含 path-ref/importlib/ps1 三面）。

### 3.3 仅测试消费（33 张，tests 改指 canonical 后整批复用 RET3 方法退役）

清单（复跑命令同 3.2，把 grep 范围缩到 tests/ 判活）：capabilities/{campus,debug,file_exchange,group_files,image_search,poke,subscribe_v2}、character/{knowledge_service,memory_extract,memory_service,memory_store_v21,mood,reflection,shared_group,teaching_service}、output/card_render/theme_tokens、runtime/{event_idempotency,ingress,model_schedule,parrot,reactions}、security/injection、sender/{gateway,nonebot,worker}、sources/{campus_store,music_request_store,reaction_store,subscription_runtime_v2,subscription_store,subscriptions/music_v2,subscriptions/social_v2,today_history}。

**注意在飞面**：`output/card_render/theme_tokens.py`（前端波禁改面，其垫片消费仅 tests——退役动作留给前端合流波）；`capabilities/debug.py`＝账面「挂起 4」之一，实测其生产消费=0、仅 tests 8 边——挂起理由（前端 echo 漂移面）已弱化，可在前端收口批一并处理。

### 3.4 生产在消费 Top（111 张中的头部；退役排程输入）

```
contracts/__init__.py        prod=75  test=149   （头号：改指 domains.core.contracts 属纯机械重线）
capabilities/user_copy.py    prod=45  test=20
llm/model_router.py          prod=25  test=14    （含 control_plane 私有名 4 处，先补公开面）
sources/parsers/http_util.py prod=18  test=14    （公共件他域引用，配合 F-05 上收 shared）
runtime/pricing.py           prod=13  test=5
runtime/cache_policy.py      prod=13  test=0
output/plain_text.py         prod=12  test=6     （star 形态垫片，control_plane×3+domains 多处）
output/card_render/bridge.py prod=12  test=6     （前端独占面，随前端收口）
llm/__init__.py              prod=10  test=16
llm/channel_health.py        prod=9   test=0
character/providers.py       prod=9   test=14
capabilities/content_parser.py prod=9 test=7
sources/downloader.py        prod=8   test=6
sources/vision_describe.py   prod=8   test=?     （deferred 消费为主）
```

### 3.5 「93 退役/4 挂起」账面 vs 实盘 158 的口径差

HANDOFF-V21R5 §D 记「275 张→93 退役→4 挂起」是**波次台账口径**（挂起 4=contracts.media/config_readiness/decision.trace/capabilities.debug）。实盘 158 的含义：v21r2 重组后各波（RET1/RET2/RWOC 等）+v21r4-B 累计退役后**在库残余**就是 158。四张账面「挂起」的实况：`contracts/media.py` 活+生产消费 1（render/bridge.py:683，与登记相符）；`decision/trace.py` 活+生产消费 1（domains/chat_reply/capabilities/echo.py:188，前端漂移面属实）+tests 3+脚本 1；**`config_readiness.py` 账面挂起但实测生产消费 2（domains/chat_reply/capabilities/echo.py:16、domains/chat_reply/pipeline/backend_unit.py:21——都不是"前端 echo 漂移面"能豁免的，域真身自己住在旧路径上）**；`capabilities/debug.py` 仅 tests。→ 账面「挂起」清单已与实际消费漂移，退役排程必须以本表为准重做（R-1 第 0 步）。

---

## §4 表③：双真身检测（domains/ ↔ 旧目录）

**结论：同名对 164，其中「双方皆非转发垫片」= 0。旧目录与 domains/ 之间不存在内容级双写（含 sha 相同纯复制 0、sha 不同漂移 0）。**

方法学护栏（防假 0，吸取 RET2B-PREP「relative_to 吞前缀假 0」教训）：
1. 检测域为**全量 basename join**（不依赖 mirror 路径形态），mirror 与 basename-only 分列（mirror 214 对归并统计，basename-only 148 对）；
2. 「转发件」判定含 PEP562、star、thin-named 三形态；旧目录侧残余真身仅 4 件（`sources/acg_search.py`、`sources/search_intent.py`、`runtime/{loop_watchdog,service_wiring,database_broker,capability_protocols}.py` 等——domains/ 内均无同名者）；
3. domains/ 内部同域重复另行检测（表③扩展）——**发现 1 例域内双真身**：divination 双 `DrawStore`，见 **F-06**；另有 15 组域内同名不同内容文件（capability vs store 分层，语义正常，全清单见 §10 F-11 附录行）。

验证命令：§1.1 复跑 + `Read %TEMP%\u5arch\out\u5-dual.md`（表体空=0 候选即证据本体）。

---

## §5 分层违规与循环依赖

### 5.1 跨域 import：经契约 89 边 vs 直入实现 55 边（域对合计 144）

**合法面（经 `domains/core/contracts/`）**：link_parse→core 33、ops→core 16、chat_reply→core 15、subscribe→core 9、music→core 5、divination→core 4、finance→core 3 等。契约层是真实在用的（消费分布：tests 78/核心域全部）。

**违规面（直入他域实现，55 边）**：

| 从→到 | 边 | 样例（文件→目标） | 定性 |
|---|---|---|---|
| ops→chat_reply | 9 | console_chat/debug.py→`chat_reply.policy[.roles]` | 管理工具直捅门禁实现 |
| ops→core | 9 | console_chat.py→`core.config.config_readiness`、`core.search.web_search`、`core.credentials.credential_health` | 内部件当 API 用 |
| chat_reply→ops | 8 | backend_unit→`ops.smoke.console_chat`、chat.py→`ops.monitor.{intent_telemetry,runtime_event_log}` | 生产链路反向依赖运维面（互反=环） |
| finance→link_parse | 7 | stocks/bond_data/fx_data…→`link_parse.parsers.http_util` | **公共件私藏**：HTTP 重试工具住在 link_parse 被 finance 全家引用 |
| ops→render | 5 | debug.py→`render.card_render.{mica_shell,theme_tokens}`、runner.py→`render.plain_text` | 直入禁改独占域内部 |
| chat_reply→core | 3 | chat.py→`core.search.web_search`（这条是**合法 canonical**，与 §2 的旧路径边并存=双通路）等 | |
| core→ops | 2 | `credential_health.py:213`、`search_smoke.py:72`→`ops.smoke.smoke` | 内核依赖运维冒烟件 |
| 其余（chat_reply→render 1、divination→chat_reply 1、meme→core(decision.outbound) 1、notes→files 1、schedule→media 1、subscribe→divination 1、subscribe→ops 1、transport→ops 1、food→core 2、assistant→food 1、media→core 1、assistant→core 1） | 15 | 见 `%TEMP%\u5arch\out\u5-layers.md` | 「历史上的今天」用 divination 的 `multi_calendar`、notes 用 files.downloader 等跨域私件 |

### 5.2 domains→旧顶层 413 边（表①§2.4）——分层规则「domains 只 import canonical」未成立。

### 5.3 control_plane ↔ domains 双向

- **cp→domains 22 边**：divination.api 7（facet/dto/errors）、ops.audit.logger 7（actions/audit/config_store/events 各点）、chat_reply 5（llm_engine.pricing、character.glossary×2）、core 3（search.web_search、decision.outbound×2）。多为 deferred 合理装配，但 `ops.audit.logger.redact_private_debug` 属跨层私件复用。
- **domains→cp 11 边**（域反向依赖服务层）：`meme/reactions/engine.py:41`→cp.dispatcher、`chat_reply/runtime/settings.py:31,982`→cp.config_store、`core/decision/dispatcher.py:28`→cp.dispatcher、`ops/features/{feature_gate:9,feature_control:4,5,feature_catalog:6}`→cp.services/auth/features、`ops/admin/runtime_admin.py:133,134,1876`→cp.auth/config_store/services。
- 双向合流=**组件级单一大 SCC**（§5.5）。正解方向：出站/特性门/配置存储的**协议下沉 core.contracts**，cp 与域各自实现/消费协议（B2② 端口方案正是此形状，方案材料已有，等裁决）。

### 5.4 模块级循环（排除包 `__init__` 边后 5 个真环）

| SCC | 成员 | 根因 |
|---|---|---|
| 4 节点 | `capabilities.content_parser ↔ capabilities.music ↔ domains.link_parse.capabilities.content_parser ↔ domains.music.capabilities.music` | **唯一跨域模块环**：link_parse 解析器经旧垫片调 music 能力，music 能力直调 link_parse 解析器。垫片退役（前两条边改 canonical）自动变成 domains 2-环：content_parser↔music 仍互为对方域实现（§5.1 违规面的必然产物） |
| 2 | `link_parse.parsers.http_util ↔ link_parse.parsers.ssrf_guard` | 域内工具↔护栏互引（ssrf_guard 用 http_util 发探针、http_util 用其校验）|
| 2 | `chat_reply.llm_engine.channel_health ↔ model_router` | 域内互引（健康度反馈路由、路由记录回健康度）|
| 2 | `core.search.search_api ↔ web_search` | 域内互引 |
| 2 | `chat_reply.character.providers ↔ reflection` | 域内互引 |
| 2（含包边） | `control_plane ↔ control_plane._app` | 包 `__init__` 拉子模块、子模块回头 |

（含包 `__init__` 目标边的完整图另有 2 个由聚合器参与的环，细节在 u5-layers.md §5。）

### 5.5 组件级 SCC：1 个 24 成员大环

`{全部 20 域 ∪ control_plane ∪ old/{capabilities,character,runtime,sender,sources} ∪ pkgroot}` 互为可达。**含义**：当前包内没有任何一个组件可以被单独摘除/独立测试/独立退役——这正是「统一架构」未成立的图论表述。pkgroot（根 `__init__.py`）入环的原因=域文件 import 父包会执行根文件+根文件 import 177 条域直连边（§7）。

---

## §6 坐标系分歧实证（14 vs 19/20 vs 34 vs 77）

### 6.1 四套坐标系现状

| 坐标系 | 出处 | 数 | 状态 |
|---|---|---|---|
| 命令一级领域（14） | `docs/design/v21r2-command-spec.md` §4.1（聊天/表情/图片/链接/音乐/天气/菜谱/金融/资讯/生活/社交/模型/系统/帮助） | 14 | **纯提案**，未落码；B4 评审材料 §2.2 列为方案 A |
| 重组规划域（19） | `docs/design/v21r2-reorg-plan.md`（19 域=用户 8 域+11 扩展） | 19 | 规划口径 |
| 实盘域（20） | `domains/` 目录实测 | 20 | **规划 19 + `creation`（后增，TTS 波）** |
| 路由（RouteKind 34 成员 / catalog「33 条规则」） | `domains/chat_reply/runtime/base_router.py` `class RouteKind`（实测枚举成员 34）；`docs/command-catalog.md` 头部记 33 | 34≠33 | **口径分叉实锤**：33 是「路由规则数」（含一 kind 多规则/5 内部能力），34 是枚举数——两数并存于现行文档，无机器门对齐 |
| 帮助主题（77） | `scripts/command_catalog.py --check` 实跑输出 `command catalog is current (77 topics)` | 77 | 与 AGENTS 台账 09-19 修正一致 |

### 6.2 topic→域 逐条映射（77 行权威表 = `docs/design/v21r4-command-format-review.md` §3.1，其自身按代码实测）**+ 本席修正的文档内不自洽**

§3.1 明细 77 行实测分布：`chat_reply 21｜ops 11｜core 8｜finance 6｜subscribe 6｜media 4｜transport 3｜meme 3｜files 2｜schedule 2｜link_parse 2｜assistant 2｜creation 1｜divination 1｜location 0*｜music 1｜notes 1｜weather 1｜food 1｜render 1`（*location 两主题 wiki/萌娘百科在该表被记为 subscribe 资讯族挂靠，**物理能力在 domains/location/capabilities/{wiki,moegirl}.py**——表内「建议 L1」与物理家不同列所致）。
**发现（P3 文档漂移）**：§3.1 的「归属汇总」文字行写 `chat_reply 20｜…｜ops 10` 且总和=74≠明细 77（差 #14 帮助、#44 群信息、#57 队列三条两案择一未计入）——评审材料内部先自洽不了，落码前必须重生成该表（机器门可锁，见 R-6）。

### 6.3 无入口/无归属缺口清单（逐条带证据）

| 缺口 | 证据 | 判定 |
|---|---|---|
| **资讯族 5 条（快报/维基/萌百/历史上的今天/Epic）无「资讯」域** | §3.1 表内全挂 `subscribe（资讯面）`；物理实现散布 `subscribe/{capabilities,feeds}/` 与 `location/capabilities/`（wiki/moegirl） | 裁决点（B4 §五.3 原文已列），本席补充：物理已跨两域，「挂 subscribe」是命名层权宜 |
| **location 域有骨架无命令面归属** | `domains/location/poi/` 空壳（orphan §8）；`location/extensions/` 同 | 与 B4 裁决点 6（是否借 location 立 POI 项）绑定 |
| **creation 域三态并存（最尖锐）** | ①提案归属：语音→creation（§3.1 #33）；②**物理真身在 `domains/media/capabilities/tts.py`（TTS 在飞席）**；③`domains/creation/tts/contracts.py + image/contracts.py + _common/contracts.py` = 完全孤儿骨架（生产不可达 §8）；RouteKind 已有 `TTS` | 在飞面不判对错，但**坐标系必须一次裁决**：creation 要么接走 tts 真身，要么删契约骨架；三态并存=「一个能力一个真身」反面教材 |
| **files/notes/render/transport/core 无专属 RouteKind** | RouteKind 34 成员实测无 FILES/NOTES/QUEUE/MAIL 族（files 借 ADMIN `/bot download/文件`、notes 借 REMINDER 路由、render/transport/core=服务层无用户命令） | render/transport/core 属**设计内**（服务/技术域）；files/notes「借道」应显式登记为路由归属决定，防后被当缺口 |
| **RouteKind 34 中 8 个 kind 的帮助面在别家** | ALIAS/ADMIN/NATURAL_COMMAND/CONTENT/CHAT/IGNORE 等族 kind 数>有 topic 的域数，帮助注册表集中在 `chat_reply/capabilities/echo.py`（单源，健康） | 无缺口，登记「物理家 vs 归属家」双列即可 |

---

## §7 根 `__init__.py` 体量与职责审计

### 7.1 实测量（扫描器 §1 复跑即得）

- **行数 8676**；顶层语句 **235**（ImportFrom 96 + Import 6 = 102 顶层 import、函数 92 + 异步函数 10、类 3、Assign 24、AnnAssign 11、Try 1、Expr 2）。
- **matcher 工厂调用（全嵌套计数）：`on_message` ×42、`on_notice` ×7、`on_command` ×2 = 51 个被动 matcher 注册点**。
- **调度：`add_job` ×15**（9 个 `_register_*_scheduler` 函数：send_queue/credential_check/today_history/kb_wiki_sync/reflection/reminder/digest_push/daily_assist + nonebot_handlers 内联若干）。
- **直接平台 API：`bot.call_api` ×12**（S0 收编后残余直连面=已登记 BYPASS 四处门关旧路径 + get_msg 反查类只读调用，逐处坐标随 REG-REFRESH 台账漂移）。
- **import 边**：指向 domains canonical 177 条（健康直连）；指向旧顶层路径 18 条（=表① C1 前两行 + B 类 2 条，目标多为垫片→实际是「根文件消费自家垫片」）。
- 顶层裸调用（import 期副作用）2 处。

### 7.2 最大内联业务体（应下沉清单，含拆分风险标注——只建议不动手）

| 函数 | 行 | 体量 | 建议去处 | 风险 |
|---|---|---|---|---|
| `_register_nonebot_handlers` | :3544 | **5125 行**（全包 59%） | 按 matcher 家族拆到 `domains/<dom>/handlers.py`（chat/meme/campus/media_archive/reactions/poke/digest/…），根文件只留装配清单 | **高**：优先级/block 判定序按 priority 全局归一（0913 批成果），拆文件不得动注册顺序语义；且此文件多波独占写窗（RWC5-b/S0-ROOT-c 刚过，TTS 席占 echo/根文件编辑窗）——**拆分必须排队拿写权** |
| `_incoming_from_nonebot_event` | :1274 | 229 行摄取逻辑 | `domains/chat_reply/ingest/`（该子包已在位且近孤儿——正主没进去） | 中：U1 席位正在审摄取链，动前读其日志避免双改 |
| `_register_today_history_scheduler` | :1789 | 136 行 | `domains/subscribe/`（能力真身所在域） | 低-中：调度器装配期快照 config（台账#3） |
| `_deliver_due_reminders` / `_deliver_cookie_expiry_report_via_queue` | :2866/:2980 | 111/97 行投递循环 | `domains/schedule/`（提醒真身域）/ transport | 中：刚被 S0-ROOT-c 修过（缩进 UnboundLocalError 史），动前读其 GREEN 锁测试 |
| `_build_memory_writer` | :377 | 102 行 | `domains/chat_reply/character/`（memory 真身家） | 低：但 L41 记忆裁决未落，别抢先 |
| `_forward_message_text(_sync)` | :902/:1020 | 77+86 行 | `domains/link_parse/` 或 chat_reply 转发子件 | 低 |
| 其余 scheduler ×9 | — | 各 40-110 行 | 对应域 | 低-中 |

**结构性事实（比行数更重）**：任何进程 import 本包**任何**模块都会先执行这 8676 行（含 51 matcher 注册）——`v21-s2-contracts-log` 已自证该问题（"contracts 内任一现存模块被 import 都会先拉起根包"），并因此把根文件当**隐式装配总线**。根文件不拆，「域自包含」永远是纸面的。收敛路线 R-5 给分阶段方案。

---

## §8 孤儿与死码（生产可达性 119 = 84 测试独占 + 35 脚本/完全孤儿）

### 8.1 完全孤儿（生产+测试+脚本皆不可达，逐件列；**删除建议=否，先裁决归属**）

```
domains/chat_reply/character/shared_export.py      （群摘要导出件，#33 台账提过 shared_group 缺陷，疑似半成品）
domains/core/search/mcp_web_search_server.py       （MCP server，或为手工入口——文件含 __main__ 需人工判）
domains/link_parse/support/url_cleaner.py          （reorg 计划点名"URL 清洗"，迁后无人接）
domains/subscribe/store/subscription_watcher.py    （订阅 watcher 骨架）
domains/ops/smoke/route_demo.py                    （演示件，测试独占都不是）
domains/creation/{__init__,_common/contracts,image/contracts,tts/contracts} （creation 骨架，TTS 在飞——不动）
domains/schedule/{data,extensions}/__init__.py     、transport/extensions/__init__.py、location/{extensions,poi}/__init__.py、files/artifacts/__init__.py、assistant/*/__init__.py ×5、media 等（空壳包目录，14 个）
domains/chat_reply/pipeline/backend_unit.py        （测试独占——V2.1 backend unit 未接线，矩阵 not_wired 属实）
domains/chat_reply/llm_engine/{billing_entities,billing_pricing,billing_service,usage_service}.py （测试独占，计费账本 M1 默认关=设计内待接线）
domains/core/supervisor/*（acl_windows/appcontainer_windows/ipc 等）（测试独占，B4 沙箱等用户 key=台账#5 设计内）
control_plane/__main__.py                          （`python -m …control_plane` 手工入口，非死码——扫描器口径限制，人工改判）
control_plane/file_access.py                       （无任何引用含 tests——真孤儿，疑似工作区文件网关半成品）
domains/finance 旧 capabilities 垫片若干、runtime/video_pipeline 等 14 死垫片（已在 §3.2 记账，勿双计）
```

**替代者关系（防误删）**：完全孤儿中 `url_cleaner`/`subscription_watcher`/`shared_export` 的"替代者"= 各自 canonical 邻居文件已承担同职责（link_parse/support 层无人 import 但 parsers 内自带清洗；store 层由 subscription_store_v2 承担）；确认无人认领后归档 `%TEMP%`→删除，走台账 #9 归档规程。

### 8.2 third_party/（2 个 AstrBot 插件：meme_manager、portrayal）

`pyproject [tool.nonebot] plugin_dirs=["plugins"]`——**NoneBot 永不装载 `third_party/` 下任何插件**（AstrBot 生态不兼容）。定性：参考实现存档。建议：移入 `ChatBot_Archive/`（附 manifest），源码树只留真用件。

### 8.3 历史遗留物

- `.tmp-test/`：源码树内 154MB pytest basetemp 残留（HANDOFF §L 记录被并发测试进程锁定，备份已在 %TEMP%）——**不在本席权限内删（锁/占用属原波次）**；列入 R-7 树卫生门。
- `_ARCHIVE`：全树无嵌套 `_Archive` 残目录（已按规程清过）✓。
- `audit/`：包根旧 `audit/` 只剩 1 张活垫片（真身=domains/ops/audit，含 logger/file_logger，被 control_plane 直入实现 §5.3）。

---

## §9 域内结构一致性（20 域）

### 9.1 布局实测矩阵（一级子目录）

```
assistant   campus daily                          ← 无顶层 capabilities（藏在 daily/capabilities 双层）
chat_reply  capabilities character ingest llm_engine pipeline policy runtime security + 根文件 affinity_replay
core        config contracts credentials decision supervisor search     ← 无 capabilities（服务层，设计内）
creation    _common extensions image tts           ← 全骨架（孤儿，§8.1）
divination  api capabilities data projection service store
files       artifacts capabilities sources
finance     capabilities data
food        capabilities data
link_parse  capabilities fetchers parsers support
location    capabilities data extensions knowledge poi
media       archive capabilities ingest registry search video
meme        capabilities reactions sources
music       capabilities data
notes       capabilities store
ops         acceptance admin audit collectors features incident integrations monitor recovery repair smoke（10 子目录）
render      card_render + 7 个根模块               ← 无子目录分层
schedule    auto_send capabilities data extensions service store timesync + 3 根模块（delivery/llm_draft/timetable）
subscribe   adapters capabilities feeds store
transport   extensions mail sender
weather     assets capabilities data
```

**结论：不存在统一骨架。** 公共词汇只有 `capabilities/`（15 域有，5 域无：assistant/core/creation/render/transport 中前二后二为角色不同，assistant 为嵌套异常）。存储层四套方言：`data/`（6）vs `store/`（3）vs `sources/`（3）vs `feeds/adapters/registry`（subscribe/media）；服务层两套：`service/` vs 直挂模块；`extensions/` 三域有空壳。

### 9.2 包 `__init__.py` 藏逻辑（聚合面=隐式公共 API）

`link_parse/parsers/__init__.py` **861 行**、`creation/__init__.py` 264 行、`core/contracts/__init__.py` 163 行、`core/supervisor/__init__.py` 126 行、`subscribe/adapters/__init__.py` 99 行、`chat_reply/policy/__init__.py` 47 行（RWC6-b「旧聚合器逐字搬运」决议产物）等 23 处（清单在 §1.1 复跑 u5 探针）。其中 parsers/creation/contracts 三处的 `__init__` 实质是**注册表/契约总线**——可接受，但必须像 theme_tokens 那样立「单一事实来源」牌，否则新消费默认从 `__init__` 取物、目录结构进一步失配。

### 9.3 域内私自复制公共件

- **`http_util`（link_parse/parsers）被 finance 全家（7 处）+ music/subscribe/location/weather 引用（垫片 18 生产边）**——事实上的 shared 网络工具住私宅；
- `render.plain_text` 被 ops.runner 引用（render 域门面件，跨域=§5.1 违规表）；
- **divination 双 DrawStore（F-06）**=同域内复制公共件的恶性极限例。
- 全树同内容同名复制：0（sha 比对，§1.1 复跑探针 R6）——尚无「互抄漂移」，但 `data/store` 混用使漂移门槛很低。

---

## §10 配置/资产位置统一（runtime_paths 覆盖率）

### 10.1 `"data/..."` 字面量扫描（plugins+scripts+bot.py，198 处）

- **主体（~90%）= 安全**：config.py 529 字段的路径缺省值（`bot_*_path: str = "data/x"`）+ 消费侧 `getattr(config, …, "data/…")` 兜底——这些值在装载/装配期统一过 `scripts/runtime_paths.runtime_path()`（其 `data/` 前缀剥除重映射到 `ChatBot_Runtime`，与 config path_fields 同规则），且 getattr 兜底分支对 pydantic Config 恒不触发。抽查三处私宅常量实证 guarded：`persona_service.py:748`、`worldbook_service.py:426`、`stocks.py:112-114`（`runtime_path(_LOGO_CACHE_DIR_REL)`）。
- **残余风险面 = 「except 回落相对路径」家族 4 处**（台账 #1 根因变体：回落即写源码树）：
  - `control_plane/_app.py:806-808`、`control_plane/audit.py:71-73`——parents[3] 对 control_plane 深度**正确**；
  - `domains/chat_reply/llm_engine/ledger.py:92-102`、`domains/chat_reply/llm_engine/channel_health.py:415-423`——`project_root = Path(__file__).resolve().parents[3]`，文件实位于包内 5 层（domains/chat_reply/llm_engine/x.py），**parents[3]=bot_unified_runtime 而非工程根**：sys.path 插入的是错根；现网侥幸能跑（进程 cwd=工程根时 `scripts` 包本就在 path 上），但独立装配面（e2e/工具从别处启动、或 `import plugins` 前 sys.path 无工程根）会落入 `except → return "data/llm_billing.sqlite3"` 相对路径。
  - **改法**：两处 parents[3]→parents[6]（或统一 import 工程内 helper），并把 except 回落改为 `raise`/日志+`PROJECT_ROOT` 硬底；验证：见 §12 F-14。
- 写盘族相对路径复核（open/makedirs/Path("data…)）：命中皆经上述 guarded 模式或 tests tmp_path，无裸写。
- **tests 面**："data/..." 字面量另计（台账 #1 Wave-6 测试 tmp_path 化未完项，与本席发现一致，不重记账号）。

### 10.2 随包资产与 gitignore 错位（P0，F-01）

见 §12 F-01 七要素卡。

---

## §11 依赖治理

### 11.1 声明 vs 实跑 import（venv 实跑 `pip check` = "No broken requirements found"）

- pyproject `[project].dependencies` 22 条（`[dependency-groups].dev` 另含 pytest）。
- **实际 import 但未声明**（括号内=全树 import 点数/文件数）：**playwright（12/8，含渲染后端与 link_parse fetchers——换机静默降级重演 httpx 前科，0918 TTS 批注释里已承认"httpx 此前只在 venv 里存在、未声明，换环境会静默降级"，playwright 正踩同一坑）**、fastapi（32，靠 nonebot2[fastapi] 传递）、pydantic（61，传递）、uvicorn(2)/starlette(1)/websockets(5)（传递）、psutil(2)、pypinyin(1)、python-docx(2)/fpdf(1)/openpyxl(2)/python-pptx(2)/pypdf(1)（文件网关导出族）、aioimaplib(1，mail 适配器传递)、dotenv(2，传递)。本地 sys.path 兄弟导入（runtime_paths/verify_hashes/collect_v21r4_live_evidence/_autosync_fixture）非第三方，登记为口径噪音。
- **声明但树内零 import**：**curl-cffi 0.16.3 已装且 `Required-by` 为空**（台账 #27 pip-audit 升级操作的遗留；当前无任何代码引用）→ 卸载或声明为可选二选一，留着=白扩 CVE 面。
- 「同功能多库并存」实测：HTTP 客户端仅 httpx（+传递 starlette）✓ 已收敛；YAML/TOML/HTML 解析无多库；图像 PIL+numpy 单栈 ✓。旧台账"requests/httpx/curl_cffi 并存"现状=curl_cffi 无人用、requests 未 import，**账面三栈实际一栈半**，比登记更干净。
- 适配器钉死面复核：cryptography 48.0.1（qq 适配 <49 钉）、aiosmtplib 3.0.2（mail ~=3.0 钉）与台账 #27 回滚记录一致；pip check 零冲突。pip-audit 全量重跑属网络操作，本席未跑（禁改环境+诚实登记：验证命令给在 F-13）。

---

## §12 发现清单（七要素全量卡）

> 格式：严重度｜坐标｜锚点｜根因｜证据｜改法｜验证命令。坐标行号=2026-09-20 快照。

### F-01 ｜P0｜资产｜`plugins/bot_unified_runtime/domains/weather/assets/qx.json`（362774 字节）；`.gitignore:32-33`
- **锚点**：`.gitignore` 行 `!plugins/bot_unified_runtime/sources/data/qx.json`；`git ls-files` 索引 blob `100644 9909c20b… 0 plugins/bot_unified_runtime/sources/data/qx.json`。
- **根因**：v21r2 天气域重组把 qx.json 从 `sources/data/` 迁到 `domains/weather/assets/`，但**全部 git 层动作未发生**：新文件从未 `git add`（状态 `??`），旧路径 blob 仍挂在索引（工作树状态 ` D`），`.gitignore` 负规则仍指向已不存在的旧目录。铁律 6 的"入库根治"只完成了**文件系统层**。
- **证据**：实跑 `git ls-files --error-unmatch domains/weather/assets/qx.json`→UNTRACKED；`git status --porcelain`→`?? …assets/` + ` D …sources/data/qx.json`；`ls plugins/bot_unified_runtime/sources/data`→No such file or directory。台账 #27 记录此文件 09-12/09-13/09-13 三度被清——**第四度风险窗此刻全开**（任何 `git clean -fd`/按索引 checkout 都能丢）。
- **改法**（用户/主会话执行，本席只读）：逐文件 `git add plugins/bot_unified_runtime/domains/weather/assets/qx.json` + 同批处理旧路径 D 态登记（rename 或 delete 提交，随全树 commit 波）；`.gitignore:32-33` 负规则改指 `!plugins/bot_unified_runtime/domains/weather/assets/`（或直接删除——assets 不在 `data/` 规则射程内）；commit-checklist §1 要害件置顶行同步新路径。
- **验证**：`git ls-files --error-unmatch plugins/bot_unified_runtime/domains/weather/assets/qx.json` 零退出；`git show --stat HEAD | grep qx.json`；`python scripts/dev.ps1 -Task runtime-layout`（旧路径不应有实体）。

### F-02 ｜P0｜生产地雷｜`plugins/bot_unified_runtime/runtime/capability_protocols.py:1272-1275`（`_WebChainAsSearchProvider.search` 体内 deferred import）
- **锚点**：`from plugins.bot_unified_runtime.sources import (` + 注释 `RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径`。
- **根因**：RET2B-PREP 曾把 `sources.web_search` 列为挂起垫片（理由=control_plane/api 消费）；主代理席退役该垫片时改指了消费方 :1128 与字符串 `_SEARCH_REF`，**漏了函数体内的第二处 deferred import**（该席日志自述的"行级批量改写只动 import 行"方法对 deferred + 注释承诺场景失效）。注释语义（"垫片挂起"）已被后续决议反转，未同步。
- **证据**：本席表① E 类唯一命中；`ls sources/web_search.py`→不存在；`sources/__init__.py` 定义名集内无 web_search（属性缺失判定器输出）；调用可达性：`_handle_search_unified:1230` 在 `request.context` 未注入 providers 时构造该适配器，`UnifiedSearchService.search` 触发即 ImportError——W7 统一搜索链路（配置门内）一碰即炸。audit-20260919-unify-wave.md P0-2 点名过同坐标，属**旧伤复发**。
- **改法**（一行，补丁待审不自动部署）：`from plugins.bot_unified_runtime.domains.core.search import web_search`（与 :1128 同形态）；删除失真注释。
- **验证**：`grep -n "from plugins.bot_unified_runtime.sources import" plugins/bot_unified_runtime/runtime/capability_protocols.py` 零命中；`PYTHONDONTWRITEBYTECODE=1 … pytest tests/test_v21_s10_protocols.py tests/test_search_service_v21.py -p no:cacheprovider --basetemp="$TEMP/pt-u5f2" -q`；扫描器 E 类归零（§1.1 复跑）。

### F-03 ｜P1｜单通路未成立｜domains/ 全域 117 文件 413 边反向 import 旧顶层（明细 §2.4）
- **锚点**：`domains/chat_reply/capabilities/affinity.py:19` `from plugins.bot_unified_runtime.character.affinity import tier_name_for_affinity`（自环样例）；`domains/core/contracts/runtime.py:13`（契约层自己 import 包根 message_context 垫片）。
- **根因**：v21r2 重组的改线批次只覆盖了「旧目录/control_plane/tests」视角的消费边与「垫片自身 import 边」（RET2b 口径"残余 0"），**域真身内部对旧路径的引用从未纳入同一批次**；且 `contracts/__init__` 垫片 75 生产边里大半来自域内。
- **证据**：§2.4 全量文件×边数；§3.4 消费 Top（contracts 75、user_copy 45）。
- **改法**：R-1 重线波第 1 批（纯路径变化零行为差，RET2b 已示范行级批改+AST 复核法）：413 边按目标垫片分组改 canonical（contracts→domains.core.contracts 一组、character.*→chat_reply 一组、capabilities.user_copy→chat_reply 一组…）；与 §5.1 违规面合并施工可免二次动文件。
- **验证**：扫描器表① D 类=0（复跑命令 §1.1）；`tests/test_doc_sync_gates.py` + 各域 scoped 回归；全量套件由收口波跑。

### F-04 ｜P1｜分层｜control_plane ↔ domains 双向（22+11 边，§5.3）+ 私有名穿仓（llm_admin 4 处下划线名经垫片取用）
- **锚点**：`control_plane/llm_admin.py:379` `from plugins.bot_unified_runtime.llm.model_router import (_demote_cooling_candidates, _health_filter_candidates, …)`；`domains/ops/features/feature_gate.py:9` 反向 import `control_plane.services`。
- **根因**：control_plane 定位=「服务/协议层」，但历史上既未把被域需要的能力（FeatureControlService/Principal/dispatcher）沉进 core.contracts，也未禁止自己直取域私件；双向依赖并入组件大 SCC（§5.5）。
- **证据**：§5.3 全量边清单（Grep 复核命令见卡尾）。
- **改法**：短期（零行为差）：cp→domains 22 边改 canonical 直连 + 私有名先在域内出公开别名；中期：domains→cp 11 边的四族（dispatcher 出站/config_store/features 目录/auth principal）随 B2② 端口方案下沉契约（该方案材料已在盘，等 15 项勾选裁决——本席不催裁决，只登记其为 F-04 关账前置）。
- **验证**：`grep -rn "control_plane" plugins/bot_unified_runtime/domains/ --include=*.py -l`（应只剩契约/字符串/文档）；扫描器 components SCC 图中 control_plane 不再与域互环。

### F-05 ｜P1｜分层｜跨域直入实现 55 边（§5.1 全表）
- **锚点**：`domains/finance/capabilities/stocks.py:119` `from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import …`；`domains/chat_reply/capabilities/chat.py:56`→`domains.ops.monitor.intent_telemetry`；`domains/core/credentials/credential_health.py:213`→`domains.ops.smoke.smoke`。
- **根因**：无「域边界=只经 core.contracts/公开 service」执法门；重组搬运时把旧目录时代的横向 import 原样带进 domains/。
- **证据**：§5.1 表；扫描器经契约/直实现拆分统计（89/55）。
- **改法**：①公共件上收：`http_util`→core（或新建 `domains/core/net/`）+ 原址留薄转发（属新增垫片=违反终局，直接全树改线 21 边一步到位）；`multi_calendar`→core.data；`alerts`→core.ops 契约事件；②ops.smoke 被 core 反用=测试件混进生产，route_demo/smoke 移 tests 侧或标 dev-only；③chat_reply↔ops 互反 8+9 边：intent_telemetry/event 族属"运维读 chat 侧"→下沉 contracts 事件协议（B5 已有事件面先例）。
- **验证**：扫描器「直入实现」边数棘轮（基线 55，只降不升）——落为 `tests/test_arch_layers.py`（R-2）。

### F-06 ｜P1｜域内双真身｜`domains/divination/data/draw_store.py`(637 行，class DrawStore@:386) vs `domains/divination/store/draw_store.py`(419 行，class DrawStore@:212)
- **锚点**：两文件同 docstring 开头「V2.1 S12 抽签」；消费方分裂——能力链 `domains/divination/capabilities/divination.py:40` 引 **data** 版；V2.1 API/服务链 `domains/divination/api/facet.py:51`、`service/divination_service.py:60`、`control_plane/api/divination.py:47` 引 **store** 版。
- **根因**：V2.1 S12 服务合同实现（store/）与存量能力（data/ 内 DrawStore+算法+配额混合体）并行开发，无人合并；同域出现两套持久化/公平性语义（hmac 种子 PRNG、配额、作废公平性各一）。
- **证据**：上列 import 行；`grep -c "class DrawStore"` 两文件各 1；两 Store 表结构不同（data 版含 daily_fortune/tarot_draw 表；store 版 QuotaPolicy/DrawRecord）。风险：`/bot 占卜` 走 data 版落库、控制面 facet API 走 store 版查库——**同一用户数据两本账**（重启前后观感不一致的潜在源）。
- **改法**：裁决级（记入 wave-snapshot 式统一裁决清单）：以 store/（合同形态、tmp_path 可测、路径 runtime_paths 合规）为归宿，data/ 版的算法件（SeededPrng/HmacPrng/塔罗牌序/interpretation context builder）拆为 `service` 纯函数件，DrawStore 单一化并迁移数据；能力链改注入 service。分两步：先合 schema 映射文档再动码。**本席不代裁**。
- **验证**：合并后 `grep -rn "class DrawStore" domains/divination/` 命中=1；`tests/test_divination_service_v21.py tests/test_draw_fairness.py`（按实际测试名）+ 占卜域 scoped 回归。

### F-07 ｜P1｜坐标系｜14/20/34/77 四套并存且互相不自洽（全文 §6）
- **锚点**：`v21r2-command-spec.md §4.1`（14 领域提案）；`v21r2-reorg-plan.md :14`（"19 个域（8+11）"）vs 实盘 `domains/` 20 目录；`base_router.py class RouteKind` 34 成员 vs `docs/command-catalog.md` 头部"33 条"；`command_catalog.py --check` 实跑 `current (77 topics)`；`v21r4-command-format-review.md §3.1` 归属汇总 74≠明细 77。
- **根因**：三套坐标系各有权威文档互不引用锁；creation 域（20 号）在任一命令坐标系中都无行（其 topic #33 语音被建议挂 creation 但物理在 media）。
- **证据**：§6.1-6.3。
- **改法**：R-6——用户裁 B4 方案（A/B/折中）后，把「域注册表」做成机器件：`docs/auto-facts.md` 增「域清单×RouteKind×topic 三方映射表」由 doc_sync 校验（任何新域/新 kind/新 topic 未登记→门红）；location/资讯/creation 三个悬案并入 B4 裁决点清单，不新开文档。
- **验证**：`python scripts/doc_sync.py --check` + 新映射门测试（R-6 交付时）。

### F-08 ｜P1｜枢纽｜根 `__init__.py` 8676 行/5125 行巨函数/51 matcher/15 scheduler/18 条自家垫片边（§7）
- **锚点**：`_register_nonebot_handlers` @:3544（end 附近 :8669）；`from plugins.bot_unified_runtime.contracts import (` @:23。
- **根因**：NoneBot 插件「import 即注册」惯例+历史上所有装配都在根文件；v21 各波已做惰性导入/垫片清账（RWC5-b），但**体量与职责本身未动**；任何 import 本包任意模块都执行全量装配（§7.2 尾注，contracts 日志自证）。
- **证据**：§7.1 实测量；扫描器 root 段全表。
- **改法**：R-5 三段：①matcher 家族分组下沉 `domains/<dom>/handlers.py` + 根文件按声明序 import 触发注册（保 priority 全局序不变——用"注册清单+稳定排序"锁）；②9 个 scheduler 函数迁对应域 service 模块，根文件留 `register_all(config)` 一行调用；③摄取函数 `_incoming_from_nonebot_event` 迁 `chat_reply/ingest`。**每段单独 commit、单独冒烟 `import plugins.bot_unified_runtime`**；该文件为多波改写热点——执行波必须持写权排队（AGENTS 规则 7 文件域互斥）。
- **验证**：行数棘轮（基线 8676 只降）；`python -c "import plugins.bot_unified_runtime"` 冒烟；test_v21 全族+提醒族 scoped 回归（RWC5-b 先例清单）。

### F-09 ｜P2｜垫片终态｜在库 158（83 PEP562+75 star/thin 两形态并存）、死 14、仅测试 33、生产 111；账面"挂起 4"两处消费已漂移（§3）
- **锚点**：`plugins/bot_unified_runtime/policy/__init__.py`（docstring `Compat shim: policy 包已迁 domains/chat_reply/policy`）；`config_readiness.py` 生产消费=echo.py:16+backend_unit.py:21（账面豁免理由失效，§3.5）。
- **根因**：退役按"波"不按"账"：每波清自己批次视野内边，无人持全量消费账；两形态（PEP562 活转发 vs star 快照转发）语义有差（star 在 canonical 后定义的名字会漏），混用放大排查成本。
- **证据**：§3 全表 + u5-shims.md 158 行。
- **改法**：R-1 重线波按 §3.4 Top 顺序批处理（contracts 75 边批、user_copy 45 批、settings/model_router 批=与 F-04 合并）→ 死 14 张立即删（备份 %TEMP% + AST 零残余，RET3 法）→ 仅测试 33 张随 tests 改指批 → 生产 111 边清零后旧目录整体删除（`sources/acg_search/search_intent` 真身此时一并迁 core/search 或留旧名转正，随 R-4）。
- **验证**：扫描器表①C1+C3(除 bot.py 设计钉)+D 全零、表②行数=0。

### F-10 ｜P2｜循环｜模块级 5 环 + 组件级 24 成员大环（§5.4/5.5）
- **锚点**：`domains/link_parse/capabilities/content_parser.py` 顶部 `from …capabilities.music import …`（垫片边）+ `domains/music/capabilities/music.py:13`→`domains.link_parse.capabilities.content_parser`。
- **根因**：F-03/F-05 的直接产物；跨域互引在垫片层被掩盖。
- **证据**：扫描器 SCC 输出（含节点名单）。
- **改法**：跨域环 content_parser↔music：解析结果喂点歌的语义改为 music 消费 content 的**契约 DTO**（core.contracts 已有 media/parse 族），拆掉反向 import；域内 4 环（http_util↔ssrf_guard 等）用延迟绑定（函数内 import 已在位者登记即可，非函数内者拆开）；组件大环在 R-1/R-5 完成后自然散架，**不要单独立项去"解环"**。
- **验证**：扫描器 SCC 输出（新门 `tests/test_arch_layers.py` 负锁无环）。

### F-11 ｜P2｜结构｜20 域无统一内部骨架；23 个域包 `__init__` 含真逻辑（`link_parse/parsers/__init__.py` 861 行为最）（§9）
- **锚点**：§9.1 矩阵；`domains/creation/tts/contracts.py`（生产零可达）。
- **根因**：reorg 按"旧目录映射"而非"统一模板"搬运（方案书本就允许域内自定义子结构）；聚合器 `__init__` 是旧顶层包惯性。
- **证据**：§9 全节。
- **改法**：**不强行统一目录**（成本高收益低）；改为发布「域骨架规范 v1」软文档 + 机器最小集：每域必须存在 `__init__.py`+恰好一个对外 `api`（现有三种：api/、facet、capabilities 门面）→ 登记进 R-6 域注册表；新域按规范生；旧域自然演化。重逻辑 `__init__` 逐个改名为 `registry.py`/`catalog.py` 之类（纯改名，随重线波做）。
- **验证**：R-6 注册表校验域门面存在性。

### F-12 ｜P2｜死码｜生产不可达 119（84 测试独占+完全孤儿 ~35，明细 §8）
- **锚点**：`control_plane/file_access.py`（全树零引用）；`third_party/astrbot_plugin_*`（plugin_dirs 永不扫此）。
- **根因**：混合体——①"待接线"半成品（billing 四件套=L41/B5 前置、supervisor=沙箱等 key、backend_unit=矩阵 not_wired 实身）；②真孤儿（file_access/shared_export/url_cleaner/subscription_watcher/mcp_web_search_server）；③口径孤儿（`control_plane/__main__.py`=手工入口，扫描器无 root 边）。
- **证据**：§8 全清单+分类列。
- **改法**：三票分立：待接线者**保留**并入验收矩阵行注（L 编号）；真孤儿按台账 #9 规程备份→删除（7 件）；`__main__`/demo 件登记入口性质免死。third_party 两插件移 Archive 附 manifest。
- **验证**：复跑 orphans 段，完全孤儿=仅白名单入口件。

### F-13 ｜P2｜依赖｜playwright 等 11 包未声明；curl-cffi 零 import 常驻 venv（§11）
- **锚点**：`plugins/bot_unified_runtime/domains/link_parse/fetchers/playwright_backend.py`；`pyproject.toml:23-26`（httpx 声明处的注释自证"此前只在 venv 里存在、未声明"）。
- **根因**：依赖=环境驱动而非清单驱动；venv 是钦定唯一运行体（ChatBot_Runtime 不重建则问题不可见），一次换机/重装即爆（前科=httpx、TTS 批注释承认）。
- **证据**：§11.1 实跑（pip check 输出、逐包文件计数、`pip show curl-cffi` Required-by 空）。
- **改法**：pyproject 补 11 条显式声明（playwright/fastapi/pydantic/uvicorn/starlette/websockets/psutil/pypinyin/python-docx/fpdf2/openpyxl/python-pptx/pypdf 按实际 import 形态择要；传递件也显式化——"直接 import 就必须直接声明"立为规矩）；curl-cffi 卸载或登记可选；新增 `scripts/dep_sync.py --check`（实际 top-level import ⊆ 声明集）入常驻门禁。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pip check`；dep_sync --check；（网络操作留用户窗口）`pip-audit` 复跑对照台账 #27。

### F-14 ｜P3｜路径｜4 处 `except → "data/…"` 回落 + domains 两文件 parents[3] 深度错（§10.1）
- **锚点**：`ledger.py:102` `return "data/llm_billing.sqlite3"` + `:94` `parents[3]`。
- **根因**：runtime_paths 收编时各件自写局部兜底，拷贝代码未随目录深度重算。
- **证据**：§10.1（现网侥幸点：工程根恰在 sys.path 时 import 成功，兜底不触发——所以它是潜伏面不是现行事故）。
- **改法**：兜底改 `PROJECT_ROOT` 常量导入失败即 raise（fail-fast）或 `runtime_data_dir()` 绝对化；深度改正 parents[6] 或统一走 `plugins.bot_unified_runtime` 内 helper（推荐后者，一处算一次）。
- **验证**：`cd $TMPDIR && ../ChatBot_Runtime/venv/Scripts/python.exe -c "from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import ledger; print(ledger.resolve_default_db_path())"` 输出必须绝对路径且不含源码树目录。

### F-15 ｜P3｜卫生｜`.tmp-test/` 占树+未 ignore；`.gitignore` 负规则指旧路径（§8.3/F-01 附带）
- **证据**：`git check-ignore .tmp-test`→未忽略；`ls -d .tmp-test` 存在（HANDOFF §L 记录其被在飞测试进程锁定、备份已在 %TEMP%）。
- **改法**：占用释放后由收口波删除；`.gitignore` 加 `.tmp-test/`；runtime-layout 门（`dev.ps1 -Task runtime-layout`）扩检 `.tmp-test`/未跟踪 data 面。
- **验证**：`dev.ps1 -Task runtime-layout` + `ls .tmp-test` 不存在。

## §13 架构收敛路线（垫片清零 + 分层规则可执法化）

> 编号 R-x；每条给「做什么/前置/关账判据」。**依赖链**：R-0 →（并行 R-3/R-4）；R-1 → R-5；R-2 可与 R-1 并行先行（先立棘轮再消化）。所有波次遵守 AGENTS 规则 7（文件域互斥、写权排队）与「补丁待审不自动部署」。

**R-0 立即两针（各一行改动，先于一切）**
1. F-02：`capability_protocols.py:1272-1275` deferred import 改 canonical（同文件 :1128 现成形态）+ 删失真注释。关账：表① E=0。
2. F-01：qx.json 新址 `git add` + 旧址 D 态登记 + `.gitignore:32-33` 负规则改写——**用户 git 动作**（本席只出命令）。关账：`git ls-files --error-unmatch` 通过。

**R-1 垫片清零波（机械重线，5 批，RET2b/RET3 已验证方法论）**
- 批 0：以本审计 §3 为唯一账本重算退役排程（作废账面「挂起 4」口径——config_readiness/debug 实况已漂移，§3.5）。
- 批 1：死 14 张删除（备份 %TEMP%、AST 零残余复跑、域回归）。
- 批 2：域内 413 边 + C1 56 边改 canonical，按目标垫片分组（contracts 75 边批、user_copy 45 批、settings/model_router 批与 F-04 合并施工、cache_policy/pricing 批…）；**与 §5.1 的 55 直入实现边同批处置**（改线时顺手把 http_util/multi_calendar/alerts 上收 shared）。
- 批 3：tests 875 边 retarget（纯机械、可并行切文件；`test_datafix_runtime_paths.py` 的动态 import 前缀先例照抄）。
- 批 4：scripts 47 边 + `bot.py` 两处（:481 设计钉同批转正或保留旧名迁移，随 R-4 裁决；:401 改线）。
- 关账判据：扫描器表① C1+C3+D=0、表② 158→0（旧目录整删）；此后「一条 import 通路」= domains canonical 单义。
- 每批必做：导入冒烟 + 受影响域 scoped 回归；全量与四门禁由收口波统一跑。

**R-2 分层规则机器门（新增 `tests/test_arch_layers.py`，把本席扫描器降维成常驻门）**
①旧路径 import 残余计数棘轮（统一口径=表①定义，含 ps1/path-ref；白名单=垫片自身+bot.py 设计钉）；②跨域直入实现边棘轮（基线 55，只降）；③模块级无新环（现存 5 环登记豁免+摘除计划）；④「下划线私有名跨层 import」零新增（AST 门）；⑤**垫片新创禁令**（旧目录内出现新的 `_CANONICAL`/star 转发件=红）。关账=接入 `dev.ps1 -Task test` 收集面（离线、秒级）。

**R-3 依赖与资产治理（与 R-1 并行）**：pyproject 补声明（playwright/pypinyin/psutil/docx 族等，§11.1 清单）；`scripts/dep_sync.py --check` 入门禁；curl-cffi 卸载/登记可选（用户窗）；third_party 两 AstrBot 插件移 Archive 附 manifest；`.gitignore` 补 `.tmp-test/`。

**R-4 坐标系终裁（并入 B4 评审包，勿另开文档）**：14/20 方案裁决 + 三个悬案（资讯族归属、location/poi 立项与否、creation 三态收编——TTS 真身归 creation 或骨架删除）+ acg_search/search_intent 两件未迁真身终名。裁决结果落成 R-6 机器账。

**R-5 根 `__init__.py` 三段拆分（严格排在 R-1 批 2 之后）**：①51 matcher 按域家族下沉 `domains/<dom>/handlers.py`（根文件留声明序装配清单，「注册清单+稳定排序」锁保 priority 语义）；②9 scheduler 迁对应域；③`_incoming_from_nonebot_event` 迁 chat_reply/ingest。关账判据：根文件行数棘轮 8676→<1500；每段独立 commit+冒烟+锚测试；全程持该文件写权（多波热点，排队机制先例=RWC5-b→S0-ROOT-c）。

**R-6 域注册机器账（doc_sync 扩展）**：`docs/auto-facts.md` 增「域 × 门面 × RouteKind × topic」四元表（生成物，禁手写数）；顺带消解 33 vs 34 口径（catalog 头部改由代码生成）与 §3.1 汇总表不自洽问题。

**R-7 树卫生执法**：runtime-layout 门扩检 `.tmp-test`/根级缓存目录/未跟踪 data 面；存量清理（三个 09-19 遗留 cache 目录与 .tmp-test）由收口波在确认无占用后按「备份→删→复跑门」规程处置。

**终局态（全部关账后）**：旧顶层 12 目录仅剩 control_plane + config(+config_readiness 转正) + 真身未迁裁决件；domains/ 20 域自包含、互经契约；根 `__init__` 只做装配；`import plugins.bot_unified_runtime` 冒烟与全部门禁绿——此时才可在文档写「统一架构达成」。

---

## §14 本席结束前树卫生自查（实跑记录）

| 检查 | 命令 | 结果 |
|---|---|---|
| 源码树零 .pyc/__pycache__ | `find plugins tests scripts -name __pycache__ -o -name "*.pyc"` | **0**（本机 DONTWRITEBYTECODE 不可靠，已按计数实测） |
| 今日新增缓存 | `find … -newermt "2026-09-20 00:00" -name "*.pyc" | wc -l` | **0** |
| 根级 `.mypy_cache/.pytest_cache/.ruff_cache` | `stat -c %y` | mtime=09-19 12:3x，**先于本席开工，属前波遗留**（列 R-7 存量处置，本席未动） |
| 源码树 `data/` | `ls -d data` | 不存在 ✓ |
| `.tmp-test/` | `ls -d .tmp-test` | 存在（前波锁件，未动，已记 F-15） |
| 本席全部工件 | `%TEMP%\u5arch\{scan_u5.py,out/u5-*.md,probe1.txt,c2rows.txt,d_compact.txt,c2_list.txt}` | 全在源码树外 ✓ |
| git/写边界 | 零 add/commit/push/checkout；零配置/代码修改；唯一源码树写入=本文件 | ✓ |

---

## 附录 A：扫描器全文（可持久重建）

落盘位置=本文件文末；重建命令：从下方代码块复制到 `%TEMP%/u5arch/scan_u5.py` 后按 §1.1 运行。纯 stdlib、只读目标工程、不写源码树。


```python
"""U5-ARCH 架构统一扫描器（只读，stdlib only）。
用法: python scan_u5.py [OUTDIR] [section...]
sections: imports | shims | dual | layers | root | orphans | paths | deps | all
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot")
PKG = "plugins.bot_unified_runtime"

OLD_DIRS = ["audit", "capabilities", "character", "contracts", "decision",
            "llm", "llm_engine", "output", "policy", "runtime", "security",
            "sender", "sources"]

def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()

files: list[Path] = []
for base in ["plugins", "tests", "scripts", "third_party"]:
    d = ROOT / base
    if d.is_dir():
        for p in d.rglob("*.py"):
            if "__pycache__" not in p.parts and ".tmp-test" not in p.parts:
                files.append(p)
for p in ROOT.glob("*.py"):
    files.append(p)

def mod_of(p: Path) -> str:
    r = rel(p)
    if r.endswith("__init__.py"):
        return r[: -len("__init__.py")].rstrip("/").replace("/", ".")
    return r[: -len(".py")].replace("/", ".")

MODULE_INDEX: dict[str, Path] = {}
for p in sorted(files, key=rel):
    MODULE_INDEX.setdefault(mod_of(p), p)

def region_of(r: str) -> str:
    pre = "plugins/bot_unified_runtime/"
    if r.startswith(pre + "domains/"):
        return "domains"
    if r.startswith(pre + "control_plane/"):
        return "control_plane"
    if r.startswith(pre):
        seg = r[len(pre):].split("/")[0]
        return seg if (seg in OLD_DIRS or seg.endswith(".py")) else "other:" + seg
    if r.startswith("plugins/"):
        return "plugins-other"
    return r.split("/")[0] if "/" in r else "root"

ROOT_OLD = {"config_readiness", "message_context", "mail_adapter", "mail_bridge"}

def old_top_of(mod: str) -> str | None:
    if not mod.startswith(PKG + "."):
        return None
    rest = mod[len(PKG) + 1:]
    seg = rest.split(".")[0]
    if seg in OLD_DIRS:
        return seg
    if seg in ROOT_OLD and "." not in rest:
        return seg
    return None

def domain_of(mod: str) -> str | None:
    m = re.match(r"^plugins\.bot_unified_runtime\.domains\.([a-z_0-9]+)(\.|$)", mod)
    return m.group(1) if m else None

class FileInfo:
    __slots__ = ("path", "rel", "mod", "region", "tree", "error", "src",
                 "is_shim", "shim_kind", "canonical", "topnames", "is_init", "has_star")
    def __init__(self, p: Path):
        self.path = p
        self.rel = rel(p)
        self.mod = mod_of(p)
        self.region = region_of(self.rel)
        self.is_init = p.name == "__init__.py"
        self.src = p.read_text(encoding="utf-8", errors="replace")
        self.tree: ast.AST | None = None
        self.error: str | None = None
        self.is_shim = False
        self.shim_kind = "real"
        self.canonical = ""
        self.topnames: set[str] = set()
        self.has_star = False

INFO: dict[str, FileInfo] = {}
for p in sorted(files, key=rel):
    fi = FileInfo(p)
    INFO.setdefault(fi.mod, fi)

def collect_block_names(tree: ast.Module) -> set[str]:
    """module-level defined names, 含 If/Try/For/While/With 包裹（import 期执行）。"""
    names: set[str] = set()
    def visit(body):
        for st in body:
            if isinstance(st, ast.Import):
                for a in st.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(st, ast.ImportFrom):
                for a in st.names:
                    if a.name == "*":
                        continue
                    names.add(a.asname or a.name)
            elif isinstance(st, ast.Assign):
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
                    elif isinstance(t, (ast.Tuple, ast.List)):
                        for e in t.elts:
                            if isinstance(e, ast.Name):
                                names.add(e.id)
            elif isinstance(st, (ast.AnnAssign, ast.AugAssign)):
                if isinstance(st.target, ast.Name):
                    names.add(st.target.id)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(st.name)
            elif isinstance(st, ast.If):
                visit(st.body); visit(st.orelse)
            elif isinstance(st, ast.Try):
                visit(st.body); visit(st.orelse); visit(st.finalbody)
                for h in st.handlers:
                    visit(h.body)
            elif isinstance(st, (ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
                visit(st.body)
                visit(getattr(st, "orelse", []) or [])
    visit(tree.body)
    return names

def imp_targets(fi: FileInfo, body) -> list[str]:
    out = []
    for st in body:
        if isinstance(st, ast.Import):
            out.extend(n.name for n in st.names)
        elif isinstance(st, ast.ImportFrom):
            base = st.module or ""
            if st.level:
                pkgparts = (fi.mod if fi.is_init else ".".join(fi.mod.split(".")[:-1])).split(".")
                pkgparts = pkgparts[: len(pkgparts) - (st.level - 1)]
                base = ".".join(pkgparts + ([base] if base else []))
            out.append(base)
    return out

def classify(fi: FileInfo) -> None:
    if fi.tree is None or fi.region == "domains":
        return
    body = fi.tree.body
    has_getattr = False
    canon = ""
    canon_pkg = ""
    star_from_domains = False
    import_nodes = [st for st in body if isinstance(st, (ast.Import, ast.ImportFrom))]
    defclass = [st for st in body if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for st in body:
        if isinstance(st, ast.FunctionDef) and st.name == "__getattr__":
            has_getattr = True
        elif isinstance(st, ast.Assign):
            for t in st.targets:
                if isinstance(t, ast.Name) and t.id == "_CANONICAL" and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                    canon = st.value.value
                if isinstance(t, ast.Name) and t.id == "_CANONICAL_PKG" and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                    canon_pkg = st.value.value
        elif isinstance(st, ast.ImportFrom):
            if any(a.name == "*" for a in st.names):
                fi.has_star = True
                if "domains" in (st.module or ""):
                    star_from_domains = True
                    if not fi.canonical:
                        fi.canonical = st.module or ""
    fi.topnames = collect_block_names(fi.tree)
    if has_getattr and (canon or canon_pkg):
        fi.is_shim, fi.shim_kind = True, "pep562-shim"
        fi.canonical = canon or canon_pkg
        return
    tgt_lists = imp_targets(fi, import_nodes)
    only_domains = bool(tgt_lists) and all(t.startswith(PKG + ".domains.") for t in tgt_lists)
    if fi.is_init and star_from_domains and not defclass:
        fi.is_shim, fi.shim_kind = True, "pkg-star-reexport"
        return
    if (not fi.is_init) and fi.has_star and star_from_domains and not defclass:
        fi.is_shim, fi.shim_kind = True, "module-star-reexport"
        return
    if (not fi.is_init) and only_domains and not [d for d in defclass if d.name != "__getattr__"] and len(fi.src) < 3000:
        fi.is_shim, fi.shim_kind = True, "thin-reexport-named"
        fi.canonical = canon or (tgt_lists[0] if tgt_lists else "")
        return
    if fi.is_init:
        nonimp = [st for st in body if not isinstance(st, (ast.Import, ast.ImportFrom))]
        nonimp = [st for st in nonimp if not (isinstance(st, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in st.targets))]
        nonimp = [st for st in nonimp if not (isinstance(st, ast.FunctionDef) and st.name == "__getattr__")]
        if not nonimp and import_nodes:
            fi.shim_kind = "aggregator"
        elif not body or (len(body) == 1 and isinstance(body[0], ast.Expr)):
            fi.shim_kind = "empty-init"
        else:
            fi.shim_kind = "real-init"
    else:
        fi.shim_kind = "real"

for fi in INFO.values():
    try:
        fi.tree = ast.parse(fi.src)
    except SyntaxError as e:
        fi.error = f"{e.msg}@{e.lineno}"

for fi in INFO.values():
    classify(fi)

Edge = dict

def collect_edges(fi: FileInfo) -> list[Edge]:
    edges: list[Edge] = []
    pkg = fi.mod if fi.is_init else ".".join(fi.mod.split(".")[:-1])
    def add(target, names, line, toplevel):
        edges.append(Edge(importer_mod=fi.mod, importer_rel=fi.rel, target=target,
                          names=names, line=line, toplevel=toplevel))
    def walk(body, in_func):
        for st in body:
            if isinstance(st, ast.Import):
                for a in st.names:
                    add(a.name, [], st.lineno, not in_func)
            elif isinstance(st, ast.ImportFrom):
                base = st.module or ""
                if st.level:
                    parts = pkg.split(".") if pkg else []
                    parts = parts[: len(parts) - (st.level - 1)]
                    base = ".".join(parts + ([base] if base else []))
                add(base, [a.name for a in st.names], st.lineno, not in_func)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(st.body, True)
            elif isinstance(st, ast.ClassDef):
                walk(st.body, in_func)
            elif isinstance(st, ast.If):
                walk(st.body, in_func); walk(st.orelse, in_func)
            elif isinstance(st, ast.Try):
                walk(st.body, in_func); walk(st.orelse, in_func); walk(st.finalbody, in_func)
                for h in st.handlers:
                    walk(h.body, in_func)
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                walk(st.body, in_func)
                walk(getattr(st, "orelse", None) or [], in_func)
    walk(fi.tree.body, False)
    return edges

ALL_EDGES: list[Edge] = []
string_refs: list[tuple[str, str, int]] = []
string_path_refs: list[tuple[str, str, int]] = []
dyn_imports: list[tuple[str, str, int]] = []

RE_MODSTR = re.compile(r'"(plugins\.bot_unified_runtime[\w.]*?)"')
RE_PATHSTR = re.compile(r'(plugins/bot_unified_runtime/[\w/.\-]+?\.py)')

for fi in INFO.values():
    if fi.tree is None:
        continue
    ALL_EDGES.extend(collect_edges(fi))
    for lineno, line in enumerate(fi.src.splitlines(), 1):
        for m in RE_MODSTR.finditer(line):
            string_refs.append((fi.rel, m.group(1), lineno))
        for m in RE_PATHSTR.finditer(line):
            string_path_refs.append((fi.rel, m.group(1), lineno))
    for node in ast.walk(fi.tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in ("import_module", "__import__") and node.args and \
               isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                s = node.args[0].value
                if s.startswith("plugins") or s.startswith("domains"):
                    dyn_imports.append((fi.rel, s, node.lineno))

for e in list(ALL_EDGES):
    if not e["names"]:
        continue
    for n in e["names"]:
        sub = (e["target"] + "." + n) if e["target"] else n
        if sub in MODULE_INDEX and sub != e["target"]:
            ALL_EDGES.append(Edge(importer_mod=e["importer_mod"], importer_rel=e["importer_rel"],
                                  target=sub, names=[], line=e["line"], toplevel=e["toplevel"],
                                  via_pkg=True))

def target_status(mod: str) -> str:
    fi = INFO.get(mod)
    if fi is None:
        return "missing"
    return ("shim:" + fi.shim_kind) if fi.is_shim else fi.shim_kind

# ============================================================ 表① imports
def sec_imports() -> str:
    out = ["## 表① 旧顶层路径 import 残余（plugins/tests/scripts/bot.py/third_party）", ""]
    rows = []
    for e in ALL_EDGES:
        tgt = e["target"]
        ot = old_top_of(tgt)
        if not ot:
            continue
        tfi = INFO.get(tgt)
        status = target_status(tgt)
        attr_missing: list[str] = []
        if tfi is not None and not tfi.is_shim and e["names"] and not tfi.has_star:
            for n in e["names"]:
                if n == "*" or (tgt + "." + n) in MODULE_INDEX or n in tfi.topnames:
                    continue
                attr_missing.append(n)
        imp = INFO[e["importer_mod"]]
        reg = imp.region
        imp_is_shim_here = imp.is_shim and old_top_of(imp.mod) is not None
        if attr_missing and tfi is not None:
            cls = "E-属性缺失(运行期ImportError雷)"
        elif status == "missing":
            cls = "E-悬空import"
        elif imp_is_shim_here:
            cls = "A-垫片自身转发"
        elif reg == "domains":
            cls = "D-domains反向import旧顶层"
        elif status.startswith("shim") or status in ("aggregator",):
            if reg == "tests":
                cls = "C2-tests消费垫片"
            elif reg in ("scripts", "root", "plugins-other"):
                cls = "C3-脚本/bot.py消费垫片"
            else:
                cls = "C1-生产(旧目录/control_plane)消费垫片"
        elif status in ("real", "real-init", "empty-init"):
            cls = "B-真身未迁合法保留"
        else:
            cls = "X-" + status
        rows.append((cls, imp.rel, e["line"], tgt, status, ",".join(e["names"])[:50], ";".join(attr_missing), e["toplevel"]))
    cnt = Counter(x[0] for x in rows)
    out.append("### 分类统计")
    out.append("")
    out.append("| 类别 | 数量 |\n|---|---|")
    for k, v in sorted(cnt.items()):
        out.append(f"| {k} | {v} |")
    out.append("")
    for cls in sorted(cnt):
        sub = sorted([x for x in rows if x[0] == cls], key=lambda t: (t[1], t[2]))
        if cls.startswith(("A", "B")) or cls == "C2-tests消费垫片":
            out.append(f"### {cls}（按消费方文件聚合，共 {len(sub)} 边）")
            out.append("")
            out.append("| 消费方 | 边数 | 行:目标 | 含deferred |")
            out.append("|---|---|---|---|")
            byfile: dict[str, list] = defaultdict(list)
            for x in sub:
                byfile[x[1]].append(x)
            for f, xs in sorted(byfile.items()):
                det = "; ".join(f":{x[2]}→{x[3]}" for x in xs[:6]) + ("…" if len(xs) > 6 else "")
                defer = any(not x[7] for x in xs)
                out.append(f"| {f} | {len(xs)} | {det} | {'Y' if defer else ''} |")
            out.append("")
            continue
        out.append(f"### {cls}（共 {len(sub)} 边）")
        out.append("")
        out.append("| 消费方 | 行 | 目标旧路径 | 目标状态 | names | 缺失属性 | 顶层? |")
        out.append("|---|---|---|---|---|---|---|")
        for x in sub:
            out.append(f"| {x[1]} | {x[2]} | {x[3]} | {x[4]} | {x[5]} | {x[6]} | {'T' if x[7] else 'deferred'} |")
        out.append("")
    errs = [(fi.rel, fi.error) for fi in INFO.values() if fi.error]
    out.append("### AST 解析失败文件")
    out.extend([f"- {r}: {e}" for r, e in errs] or ["- 无"])
    return "\n".join(out)

# ============================================================ 表② shims
def consumers_of_shims() -> dict[str, list[tuple[str, str]]]:
    cons: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in ALL_EDGES:
        tgt = e["target"]
        if tgt in MODULE_INDEX and old_top_of(tgt) and INFO[tgt].is_shim:
            cons[tgt].append((e["importer_rel"], "import"))
        for n in e["names"]:
            sub = (tgt + "." + n) if tgt else n
            if sub in MODULE_INDEX and sub != tgt and old_top_of(sub) and INFO[sub].is_shim:
                cons[sub].append((e["importer_rel"], "from-pkg"))
    for r, s, _ in string_refs + dyn_imports:
        base = s
        while base:
            if base in MODULE_INDEX:
                if INFO[base].is_shim and old_top_of(base):
                    cons[base].append((r, "str/importlib"))
                break
            base = base.rpartition(".")[0]
    for r, p, _ in string_path_refs:
        m = re.match(r"plugins/bot_unified_runtime/([\w/.\-]+)\.py", p)
        if m:
            mod = PKG + "." + m.group(1).replace("/", ".")
            if mod in MODULE_INDEX and INFO[mod].is_shim and old_top_of(mod):
                cons[mod].append((r, "path-ref"))
    for ps1 in (ROOT / "scripts").glob("*.ps1"):
        txt = ps1.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        for m in RE_PATHSTR.finditer(txt):
            mm = re.match(r"plugins/bot_unified_runtime/([\w/.\-]+)\.py", m.group(0))
            if mm:
                mod = PKG + "." + mm.group(1).replace("/", ".")
                if mod in MODULE_INDEX and INFO[mod].is_shim and old_top_of(mod):
                    cons[mod].append(("scripts/" + ps1.name, "ps1"))
        for m in RE_MODSTR.finditer(txt):
            base = m.group(1)
            while base:
                if base in MODULE_INDEX:
                    if INFO[base].is_shim and old_top_of(base):
                        cons[base].append(("scripts/" + ps1.name, "ps1"))
                    break
                base = base.rpartition(".")[0]
    return cons

def sec_shims() -> str:
    out = ["## 表② 垫片清单与状态", ""]
    cons = consumers_of_shims()
    shims = sorted([fi for fi in INFO.values() if (fi.region in OLD_DIRS or old_top_of(fi.mod)) and fi.is_shim],
                   key=lambda f: f.rel)
    n_pep = sum(1 for s in shims if s.shim_kind == "pep562-shim")
    n_other = len(shims) - n_pep
    out.append(f"旧顶层目录内转发件总数 = {len(shims)}（PEP562={n_pep}，其他转发形态={n_other}）")
    out.append("")
    out.append("| 垫片 | 型 | canonical 指向 | 指向存在 | 生产/test/脚本消费数 | 状态 |")
    out.append("|---|---|---|---|---|---|")
    dead, testonly = [], []
    for s in shims:
        cs = [c for c in cons.get(s.mod, []) if c[0] != s.rel]
        prod = [c for c in cs if c[0].startswith("plugins/") and not c[0].startswith("tests/")]
        tst = [c for c in cs if c[0].startswith("tests/")]
        other = [c for c in cs if c[0].startswith("scripts/") or c[0] == "bot.py" or c[0].startswith("third_party/")]
        canon_ok = ("有" if s.canonical in MODULE_INDEX else "**缺**") if s.canonical else "-"
        status = "活+生产消费" if prod or other else ("仅tests消费" if tst else "**死垫片(零消费)**")
        if not (prod or other or tst):
            dead.append(s.rel)
        elif not (prod or other):
            testonly.append(s.rel)
        out.append(f"| {s.rel} | {s.shim_kind} | {s.canonical} | {canon_ok} | {len(prod)}/{len(tst)}/{len(other)} | {status} |")
    out.append("")
    out.append(f"### 死垫片（零消费）: {len(dead)}")
    out.extend([f"- {d}" for d in dead] or ["- 无"])
    out.append(f"### 仅测试消费: {len(testonly)}")
    out.extend([f"- {d}" for d in testonly] or ["- 无"])
    return "\n".join(out)

# ============================================================ 表③ dual
def fingerprint(fi: FileInfo) -> dict:
    tops, funcs, allv = [], {}, None
    if fi.tree:
        for st in fi.tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tops.append("def:" + st.name)
                funcs[st.name] = hashlib.sha1(ast.dump(st, annotate_fields=False, include_attributes=False).encode()).hexdigest()[:10]
            elif isinstance(st, ast.ClassDef):
                tops.append("class:" + st.name)
                for sub in st.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        funcs[st.name + "." + sub.name] = hashlib.sha1(ast.dump(sub, annotate_fields=False, include_attributes=False).encode()).hexdigest()[:10]
            elif isinstance(st, ast.Assign):
                for t in st.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__":
                        try:
                            allv = ast.literal_eval(st.value)
                        except Exception:
                            allv = "UNPARSE"
    return {"tops": tops, "funcs": funcs, "all": allv,
            "sha": hashlib.sha256(fi.path.read_bytes()).hexdigest()[:16]}

def sec_dual() -> str:
    out = ["## 表③ 双真身检测（同名 .py 在 domains/ 与旧目录都存在且都非转发垫片）", ""]
    domain_mods = [fi for fi in INFO.values() if fi.region == "domains" and fi.path.name != "__init__.py"]
    old_mods = [fi for fi in INFO.values() if fi.region in OLD_DIRS or old_top_of(fi.mod)]
    old_by_name: dict[str, list[FileInfo]] = defaultdict(list)
    for o in old_mods:
        old_by_name[o.path.name].append(o)
    pairs = []
    for d in domain_mods:
        dm = domain_of(d.mod)
        segs = d.mod[len(PKG) + 1 + len("domains." + (dm or "")) + 1:].split(".")
        for o in old_by_name.get(d.path.name, []):
            orest = o.mod[len(PKG) + 1:].split(".")
            kind = "mirror" if (segs and segs[0] == orest[0] and segs[1:] == orest[1:]) else "basename"
            pairs.append((d, o, kind))
    both_real = [(d, o, k) for d, o, k in pairs if (not d.is_shim) and (not o.is_shim)]
    out.append(f"同名对 {len(pairs)}；双非垫片候选 {len(both_real)}"
               f"（mirror={sum(1 for x in both_real if x[2]=='mirror')}/basename-only={sum(1 for x in both_real if x[2]=='basename')}）")
    out.append("")
    out.append("| domains 侧 | 旧路径侧 | 关联 | 旧侧类型 | sha 同 | __all__ 同 | 漂移函数数 | 漂移样例 |")
    out.append("|---|---|---|---|---|---|---|---|")
    detail = []
    for d, o, k in sorted(both_real, key=lambda x: x[1].rel):
        fd, fo = fingerprint(d), fingerprint(o)
        same = fd["sha"] == fo["sha"]
        same_all = fd["all"] == fo["all"]
        drift = [n for n in set(fd["funcs"]) | set(fo["funcs"]) if fd["funcs"].get(n) != fo["funcs"].get(n)]
        if not same:
            detail.append((d, o, drift, fd, fo))
        out.append(f"| {d.rel} | {o.rel} | {k} | {o.shim_kind} | {'同' if same else '异'} | {'同' if same_all else '异'} | {len(drift)} | {','.join(sorted(drift)[:5])} |")
    out.append("")
    out.append("### 漂移/差异细节（双真身且内容不同 = 最高危）")
    for d, o, drift, fd, fo in detail:
        out.append(f"- **{o.rel}（旧，{o.shim_kind}） vs {d.rel}（domains）**")
        only_old = [t for t in fo["tops"] if t not in fd["tops"]]
        only_dom = [t for t in fd["tops"] if t not in fo["tops"]]
        out.append(f"  - 顶层符号 旧独有: {only_old[:8]}｜域独有: {only_dom[:8]}")
        out.append(f"  - 函数体不同: {sorted(drift)[:10]}{'…' if len(drift) > 10 else ''}")
    return "\n".join(out)

# ============================================================ layers
def scc_all(graph: dict[str, set[str]]) -> list[list[str]]:
    index, low, onstack, stack, out = {}, {}, set(), [], []
    sys.setrecursionlimit(200000)
    counter = [0]
    def rec(v):
        index[v] = low[v] = counter[0]; counter[0] += 1
        stack.append(v); onstack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                rec(w); low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); onstack.discard(w); comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(comp)
    for v in list(graph):
        if v not in index:
            rec(v)
    return sorted(out, key=len, reverse=True)

def sec_layers() -> str:
    out = ["## 分层违规与循环依赖", ""]
    dd = defaultdict(list); do_rev = defaultdict(list); cp_dom = defaultdict(list)
    for e in ALL_EDGES:
        imp = INFO[e["importer_mod"]]
        src_dom = domain_of(imp.mod) if imp.region == "domains" else None
        tgt_dom = domain_of(e["target"])
        if src_dom and tgt_dom and src_dom != tgt_dom:
            dd[(src_dom, tgt_dom)].append((imp.rel, e["line"], e["target"], e["toplevel"]))
        if src_dom and old_top_of(e["target"]):
            do_rev[(src_dom, old_top_of(e["target"]))].append((imp.rel, e["line"], e["target"], target_status(e["target"])))
        if imp.region == "control_plane" and tgt_dom:
            cp_dom[tgt_dom].append((imp.rel, e["line"], e["target"]))
    out.append("### 1) domain→domain 直接 import")
    out.append("")
    out.append("| 从域 | 到域 | 边数 | 样例(文件:行→目标) |")
    out.append("|---|---|---|---|")
    for (a, b), rows in sorted(dd.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {a} | {b} | {len(rows)} | " + "; ".join(f"{Path(r[0]).name}:{r[1]}→{r[2][len(PKG)+1:]}" for r in rows[:2]) + " |")
    out.append(f"\n合计跨域边 {sum(len(v) for v in dd.values())}，域对 {len(dd)}")
    out.append("")
    out.append("### 2) domains/ 反向 import 旧顶层路径（按域×旧顶层）")
    out.append("")
    out.append("| 域 | 旧顶层 | 边数 | 状态分布 | 样例 |")
    out.append("|---|---|---|---|---|")
    for (a, b), rows in sorted(do_rev.items(), key=lambda kv: -len(kv[1])):
        sc = Counter(r[3] for r in rows)
        out.append(f"| {a} | {b} | {len(rows)} | {dict(sc)} | " + "; ".join(f"{Path(r[0]).name}:{r[1]}→{r[2][len(PKG)+1:]}" for r in rows[:2]) + " |")
    out.append("")
    out.append("### 3) control_plane → domains 直入域内实现")
    out.append("")
    out.append("| 目标域 | 边数 | 样例 |")
    out.append("|---|---|---|")
    for b, rows in sorted(cp_dom.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {b} | {len(rows)} | " + "; ".join(f"{Path(r[0]).name}:{r[1]}→{r[2][len(PKG)+1:]}" for r in rows[:3]) + " |")
    ctr = Counter()
    for e in ALL_EDGES:
        if e["target"].startswith(PKG + ".domains.core.contracts"):
            imp = INFO[e["importer_mod"]]
            ctr[domain_of(imp.mod) or imp.region] += 1
    out.append("")
    out.append("### 4) 中央契约层 domains/core/contracts/ 消费分布: " + json.dumps(dict(ctr), ensure_ascii=False))
    graph = defaultdict(set); graph_ni = defaultdict(set)
    pnodes = {m for m in INFO if m.startswith(PKG)}
    for e in ALL_EDGES:
        a, b = e["importer_mod"], e["target"]
        if a in pnodes and b in pnodes and a != b:
            graph[a].add(b)
            if not INFO[b].is_init:
                graph_ni[a].add(b)
    comps = scc_all(graph); comps_ni = scc_all(graph_ni)
    out.append("")
    out.append(f"### 5) 模块级 import 图 SCC（含指向包 __init__ 边）：{len(comps)} 个环")
    for c in comps[:10]:
        out.append(f"- SCC({len(c)}): " + ", ".join(sorted(x[len(PKG)+1:] for x in c)[:15]) + ("…" if len(c) > 15 else ""))
    out.append(f"### 5b) 排除包 __init__ 目标后 SCC：{len(comps_ni)} 个")
    for c in comps_ni[:10]:
        out.append(f"- SCC({len(c)}): " + ", ".join(sorted(x[len(PKG)+1:] for x in c)[:15]) + ("…" if len(c) > 15 else ""))
    def comp_of(mod):
        if mod.startswith(PKG + ".domains."):
            return "domains/" + (domain_of(mod) or "?")
        ot = old_top_of(mod)
        if ot:
            return "old/" + ot
        if mod.startswith(PKG + ".control_plane"):
            return "control_plane"
        return "pkgroot"
    cgraph = defaultdict(set)
    for e in ALL_EDGES:
        if e["importer_mod"].startswith(PKG) and e["target"].startswith(PKG):
            a, b = comp_of(e["importer_mod"]), comp_of(e["target"])
            if a != b:
                cgraph[a].add(b)
    cc = scc_all(cgraph)
    out.append("")
    out.append(f"### 5c) 组件级 SCC（域/旧顶层粒度）：{len(cc)} 个环")
    for c in cc:
        out.append(f"- 环: {sorted(c)}")
        members = set(c)
        seen = set()
        for a in sorted(members):
            for b in sorted(members):
                if b in cgraph.get(a, set()) and (a, b) not in seen:
                    seen.add((a, b))
                    for e in ALL_EDGES:
                        if e["importer_mod"].startswith(PKG) and comp_of(e["importer_mod"]) == a and comp_of(e["target"]) == b:
                            out.append(f"  - {a} → {b} 例: {e['importer_rel']}:{e['line']}")
                            break
    return "\n".join(out)

# ============================================================ root init
def sec_root() -> str:
    fi = INFO[PKG]
    tree = fi.tree
    lines = fi.src.count("\n") + 1
    out = [f"## 根 __init__.py 审计（{fi.rel}）", ""]
    topk = Counter(type(st).__name__ for st in tree.body)
    out.append(f"- 行数 {lines}；顶层语句 {len(tree.body)}")
    out.append("- 顶层语句分布: " + json.dumps(dict(topk), ensure_ascii=False))
    imports_n = sum(1 for st in tree.body if isinstance(st, (ast.Import, ast.ImportFrom)))
    funcs = [st for st in tree.body if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))]
    out.append(f"- 顶层 import 语句 {imports_n}；顶层函数 {len(funcs)}；顶层类 {sum(1 for st in tree.body if isinstance(st, ast.ClassDef))}")
    matcher = Counter(); sched = Counter(); api = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fn = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fn and re.match(r"^on_[a-z_]+$", fn):
                matcher[fn] += 1
            if fn in ("create_task", "add_job", "ensure_future", "Thread", "run_in_executor"):
                sched[fn] += 1
            if isinstance(f, ast.Attribute) and f.attr in (
                    "call_api", "send_private_msg", "send_group_msg", "upload_group_file",
                    "upload_private_file", "set_msg_emoji_like", "delete_msg", "get_msg",
                    "get_group_msg_history", "get_forward_msg"):
                api[f.attr] += 1
    out.append("\n### on_* matcher 工厂调用: " + json.dumps(dict(matcher.most_common(20)), ensure_ascii=False))
    out.append("### 任务/调度原语: " + json.dumps(dict(sched), ensure_ascii=False))
    out.append("### 直接平台 API 调用点: " + json.dumps(dict(api.most_common(20)), ensure_ascii=False))
    sized = sorted(((st.end_lineno - st.lineno, st.name, st.lineno) for st in funcs), reverse=True)
    out.append("\n### 最大 20 个顶层函数（行数）")
    for size, name, ln in sized[:20]:
        out.append(f"- :{ln:>5} {name} ({size} 行)")
    lvl = Counter("relative" if isinstance(st, ast.ImportFrom) and st.level else "absolute"
                  for st in tree.body if isinstance(st, (ast.Import, ast.ImportFrom)))
    out.append("- 顶层 import 形态: " + json.dumps(dict(lvl), ensure_ascii=False))
    oldimp = sum(1 for e in ALL_EDGES if e["importer_mod"] == PKG and old_top_of(e["target"]))
    domimp = sum(1 for e in ALL_EDGES if e["importer_mod"] == PKG and e["target"].startswith(PKG + ".domains."))
    out.append(f"- 根文件 import 边：旧顶层路径 {oldimp} 条｜domains 直连 {domimp} 条")
    bare_calls = [st for st in tree.body if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)]
    out.append(f"- 顶层裸调用语句（import 期副作用）: {len(bare_calls)}")
    regf = [st.name for st in funcs if st.name.startswith("_register") or "scheduler" in st.name.lower() or st.name.startswith("_schedule")]
    out.append(f"- _register_*/调度装配函数 {len(regf)} 个: {regf[:30]}")
    return "\n".join(out)

# ============================================================ orphans
def sec_orphans() -> str:
    out = ["## 孤儿与死码（生产可达性）", ""]
    graph = defaultdict(set)
    for e in ALL_EDGES:
        graph[e["importer_mod"]].add(e["target"])
        for n in e["names"]:
            sub = e["target"] + "." + n if e["target"] else n
            if sub in MODULE_INDEX:
                graph[e["importer_mod"]].add(sub)
    rel2mod = {}
    for m, fi in INFO.items():
        rel2mod.setdefault(fi.rel, m)
    for r, s, _ in string_refs + dyn_imports:
        src = rel2mod.get(r)
        base = s
        while base:
            if base in MODULE_INDEX:
                if src:
                    graph[src].add(base)
                break
            base = base.rpartition(".")[0]
    for r, p, _ in string_path_refs:
        mm = re.match(r"plugins/bot_unified_runtime/([\w/.\-]+)\.py", p)
        if mm:
            mod = PKG + "." + mm.group(1).replace("/", ".")
            src = rel2mod.get(r)
            if mod in MODULE_INDEX and src:
                graph[src].add(mod)
    ps1names = []
    for ps1 in (ROOT / "scripts").glob("*.ps1"):
        name = "ps1:" + ps1.name
        ps1names.append(name)
        txt = ps1.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        for m in RE_PATHSTR.finditer(txt):
            mm = re.match(r"plugins/bot_unified_runtime/([\w/.\-]+)\.py", m.group(0))
            if mm:
                mod = PKG + "." + mm.group(1).replace("/", ".")
                if mod in MODULE_INDEX:
                    graph[name].add(mod)
        for m in RE_MODSTR.finditer(txt):
            base = m.group(1)
            while base:
                if base in MODULE_INDEX:
                    graph[name].add(base)
                    break
                base = base.rpartition(".")[0]
    def ancestors(m: str) -> list[str]:
        parts = m.split(".")
        return [".".join(parts[:i]) + "" for i in range(1, len(parts)) if ".".join(parts[:i]) in MODULE_INDEX and INFO[".".join(parts[:i])].is_init]
    def reach(rs):
        seen, stack = set(rs), list(rs)
        while stack:
            v = stack.pop()
            ws = set(graph.get(v, ())) | set(ancestors(v))
            for w in ws:
                if w not in seen:
                    seen.add(w); stack.append(w)
        return seen
    prod_roots = {PKG, "bot"}
    test_roots = {m for m in INFO if m.startswith("tests.")}
    script_roots = {m for m in INFO if m.startswith("scripts.")} | set(ps1names)
    prod_reach = reach(prod_roots)
    test_reach = reach(test_roots | prod_roots)
    all_reach = reach(prod_roots | test_roots | script_roots)
    plugin_mods = {m for m in INFO if m.startswith(PKG) and m != PKG}
    orphans = sorted(plugin_mods - prod_reach)
    out.append(f"包内模块 {len(plugin_mods)}；生产不可达 {len(orphans)}")
    out.append("")
    out.append("| 模块 | 分类 | 证据 |")
    out.append("|---|---|---|")
    for m in orphans:
        fi = INFO[m]
        tag = "测试独占" if m in test_reach else ("脚本/构建独占" if m in all_reach else "完全孤儿")
        ev = "tests 图可达" if m in test_reach else ("scripts/ps1 可达" if m in all_reach else "无任何引用")
        out.append(f"| {fi.rel} | {tag} | {ev} |")
    out.append("")
    out.append("### 历史遗留物（按名）")
    for pat in ["_ARCHIVE", "backend_unit"]:
        hits = sorted({rel(p) for p in ROOT.rglob("*") if pat.lower() in p.name.lower() and "ChatBot_Runtime" not in str(p) and "ChatBot_Archive" not in str(p) and "node_modules" not in str(p)})[:20]
        out.append(f"- '{pat}': {hits or '无'}")
    audit_hits = sorted({rel(p) for p in (ROOT / "plugins").rglob("*") if p.parent.name == "audit" or p.name == "audit.py"})[:20]
    out.append(f"- audit 相关: {audit_hits}")
    return "\n".join(out)

# ============================================================ paths
def sec_paths() -> str:
    out = ["## 数据路径卫生（裸相对 data/ 与 runtime_paths 覆盖）", ""]
    scope = [fi for fi in INFO.values() if fi.rel.startswith(("plugins/", "scripts/")) or fi.rel == "bot.py"]
    RE_LIT = re.compile(r'''["']data[/\\]''')
    hits = []
    for fi in scope:
        for lineno, line in enumerate(fi.src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if RE_LIT.search(line):
                guarded = ("runtime_path" in line) or ("RUNTIME" in line) or ("_ROOT" in line)
                hits.append((fi.rel, lineno, s[:150], "G" if guarded else "RAW"))
    out.append(f'"data/…" 字面量命中 {len(hits)}（G=同行含 runtime_path/RUNTIME/_ROOT；RAW=需复核）：')
    out.append("")
    out.append("| 文件 | 行 | 标记 | 内容 |")
    out.append("|---|---|---|---|")
    for r, ln, s, tag in hits:
        out.append(f"| {r} | {ln} | {tag} | {s} |")
    ntests = sum(1 for fi in INFO.values() if fi.rel.startswith("tests/")
                 for l in fi.src.splitlines() if RE_LIT.search(l))
    out.append(f"\ntests/ 内字面量行数另计: {ntests}")
    RE_OPEN = re.compile(r'''(?:^|[^\w.])(open|os\.makedirs|os\.mkdir|Path)\(\s*f?["']([A-Za-z_.][\w./\\ \-]*)["']''')
    rels = []
    for fi in scope:
        for lineno, line in enumerate(fi.src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            m = RE_OPEN.search(line)
            if m and "/" in m.group(2) and not m.group(2).startswith(("C:", "/", "\\\\", "..")):
                rels.append((fi.rel, lineno, s[:140]))
    out.append(f"\n### 相对路径字面量 open/makedirs/Path（复核候选 {len(rels)}）")
    out.append("")
    out.append("| 文件 | 行 | 内容 |")
    out.append("|---|---|---|")
    for r, ln, s in rels:
        out.append(f"| {r} | {ln} | {s} |")
    rpf = INFO.get("scripts.runtime_paths")
    out.append(f"\nruntime_paths: {'在盘 ' + str(len(rpf.src.splitlines())) + ' 行' if rpf else '缺失'}")
    if rpf:
        funcs = [n.name for n in ast.walk(rpf.tree) if isinstance(n, ast.FunctionDef)]
        out.append("- 函数: " + ", ".join(f for f in funcs if not f.startswith("_")))
    return "\n".join(out)

# ============================================================ deps
def sec_deps() -> str:
    out = ["## 依赖治理", ""]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"dependencies\s*=\s*\[(.*?)\]", pyproject, re.S)
    deps = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    out.append(f"pyproject [project].dependencies = {len(deps)} 条: {deps}")
    stdlib = set(sys.stdlib_module_names)
    local = {"plugins", "scripts", "tests", "third_party", "personas", "webui", "bot", "conftest"}
    top: Counter[str] = Counter()
    for fi in INFO.values():
        if fi.rel.startswith("third_party/") or fi.tree is None:
            continue
        for node in ast.walk(fi.tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m0 in mods:
                t = m0.split(".")[0]
                if t and t not in stdlib and t not in local:
                    top[t] += 1
    def pkgname(d):
        return re.split(r"[<>=!~;\[ ]", d)[0].lower().replace("_", "-")
    declared = {pkgname(d) for d in deps}
    alias = {"pil": "pillow", "yaml": "pyyaml", "dotenv": "python-dotenv", "dateutil": "python-dateutil",
             "bs4": "beautifulsoup4", "curl_cffi": "curl-cffi"}
    norm = lambda x: x.lower().replace("_", "-")
    imported_not = sorted(t for t in top if norm(alias.get(t, t)) not in declared)
    out.append("\n### 实际 import 但未声明（第三方）")
    for t in imported_not:
        out.append(f"- {t}: {top[t]} 处")
    out.append("\n### 声明但全树未见 import")
    dn = sorted(d for d in declared if not any(norm(alias.get(t, t)) == d for t in top))
    out.append(", ".join(dn) or "无")
    out.append("\n### 同功能多库并存")
    buckets = {
        "http-client": ["requests", "httpx", "aiohttp", "curl_cffi", "urllib3", "starlette"],
        "yaml": ["yaml", "ruamel"],
        "toml": ["tomllib", "tomli", "toml"],
        "image-numeric": ["PIL", "cv2", "numpy"],
        "html-parse": ["bs4", "lxml", "selectolax"],
        "scheduler": ["apscheduler", "asyncio"],
        "db": ["sqlite3", "peewee", "sqlalchemy"],
        "ws": ["websockets", "aiohttp"],
    }
    for k, ns in buckets.items():
        usage = {n: top.get(n, 0) for n in ns if top.get(n, 0)}
        out.append(f"- {k}: {usage}")
    out.append("\n### requirements*.txt: " + (", ".join(rel(f) for f in ROOT.glob("requirements*.txt")) or "无（依赖全在 pyproject）"))
    return "\n".join(out)

SECS = {"imports": sec_imports, "shims": sec_shims, "dual": sec_dual,
        "layers": sec_layers, "root": sec_root, "orphans": sec_orphans,
        "paths": sec_paths, "deps": sec_deps}

ap = argparse.ArgumentParser()
ap.add_argument("outdir", nargs="?", default="C:/Users/LancyCelestia/AppData/Local/Temp/u5arch/out")
ap.add_argument("sections", nargs="*", default=[])
args = ap.parse_args()
outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
which = args.sections or list(SECS)
for name in which:
    text = SECS[name]()
    (outdir / f"u5-{name}.md").write_text(text, encoding="utf-8")
    print(f"@@@@@ {name} @@@@@")
    print(text)
```

---

*（U5-ARCH 席位报告完。姊妹席：U1-INVEST 入站统一性=`docs/design/audit-20260920-unify-U1-invest.md`；上轮=`docs/design/audit-20260919-unify-wave.md`。本席结论以工作树 2026-09-20 快照为准，重启/commit 后数字需复核。）*
