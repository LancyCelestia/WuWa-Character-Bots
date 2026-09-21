# 席位 U13-DB 数据层/持久化统一 审计日志（2026-09-20）

> 只读审计席。范围：后端 Python + 数据层。禁改代码/配置/文档（本文件除外）；Runtime 侧一切查询只读；不读 .env 明文。
> 状态图例：`[ ]`未开始 `[~]`进行中 `[x]`完成

## 进度锚（重启即读）
- [x] D1 db-owners.md 与实况对账 — 11 黑户库、2 归属分裂、0 幻影、散落库逐个核完
- [x] D2 访问通路统一性 — 无中央 helper（20+ 自建 _connect）、热写库缺 WAL、on-loop IO 1 处、无 user_version、幂等表级到位
- [x] D3 生命周期与配额 — prune 面广；13GB 数据根、向量库 5.28GB 无配额、ANN 漂移 35341≠4611、4 僵尸空库
- [x] D4 数据安全与备份面 — 测试无「生产 Runtime」防线(P1·WIRE-SVC 实证)、活动库零备份、静息全明文（凭证打码部分缓解）

---

## D1 db-owners.md 与实况对账  `[x]`

> 方法：`grep sqlite3.connect(/create_engine(/CREATE TABLE` 全插件树聚类 + `find ChatBot_Runtime -name *.sqlite3/*.db` 只读列举 + 逐条对 db-owners.md。零 `create_engine`（无 SQLAlchemy，全 stdlib sqlite3）。plugins 连接点 75 处、建表模块 52 个。行号会漂，坐标带锚点。

### 实存 Runtime 生产库（ChatBot_Runtime/data/，只读 ls）
按状态分三类（`|bytes|mtime|`）：
- **活跃**：bot_mood(8192,09-19) channel_health(28672,09-19) control_plane_actions(36864) control_plane_config(28672) control_plane_features(20480) group_files(12288) **kb_wiki_embeddings(5,672,304,640=5.28GB!)** **knowledge_embeddings(949,612,544=905MB)** media_archive media_registry meme_library(1.4M,09-19) music_analytics notes parse_history persona_quirks **reactions(36864,09-19)** reflection reminders result_unknown session_identity subscriptions user_affinity(135168,09-19) **wuwa_audit(348160) wuwa_diagnostics(122880) wuwa_history(2.1M) wuwa_memory(106496) wuwa_receipts(352256) wuwa_send_queue(4,055,040)**
- **僵尸（0 字节，无任何代码 writer，mtime 停 09-08/08-24）**：`audit.sqlite3`(0) `diagnostics.sqlite3`(0) `receipts.sqlite3`(0) `_diag_debug.sqlite3`(20480,08-24)
- **迁移备份**：subscriptions_old(40960,08-22)
- **框架自带（非 bot 数据层）**：nonebot_orm(09-22 老) nonebot_plugin_orm/db.sqlite3(07-04)
- **陈旧低活跃（建后未再动）**：addressing_preferences(09-13) media_registry(09-11) session_identity(09-11)

### 三向差集
**① 幻影 owner（文档有码无）：0 条**——db-owners.md §1/§2 每条都在代码中找到建表方。
但 db-owners.md 的 Owner 模块路径**系统性陈旧**：写的是重组前旧顶层路径（`character/vector_knowledge.py`、`diagnostics.py`、`character/affinity.py`…），canonical 实际在 `domains/chat_reply/character/*`、`domains/ops/smoke/diagnostics.py`（旧顶层现为 PEP562 垫片）。垫片可解析，非错误，但读者据旧径找不到真身 → 建议修订表统一改指 canonical（P3 doc-hygiene）。

**② 黑户库（代码有 / db-owners.md 无）：共 11 处**（重点）
| # | 库文件 | 建表模块（锚点） | owner | 有配置键? | 严重度 |
|---|---|---|---|---|---|
| BH1 | control_plane_config | control_plane/config_store.py:167 `sqlite3.connect(self.path` | control_plane | 是 `bot_control_plane_config_db` | P2（盘上活跃 28KB，文档零登记） |
| BH2 | control_plane_features | control_plane/sqlite_features.py:136 `mode={mode}` | control_plane | 是 `_features_db` | P2 |
| BH3 | control_plane_actions | control_plane/actions.py:148 `timeout=2.0` | control_plane | 是 `_actions_db` | P2（盘上活跃） |
| BH4 | control_plane_platform | control_plane/platform.py:22 `check_same_thread=False` | control_plane | 是 `_platform_db` | P2（盘上无=特性关） |
| BH5 | control_plane_events | control_plane/events.py:267（表 `runtime_log_events`） | control_plane | 是 `_events_db` | P2 |
| BH6 | control_plane_events_v21 | ops/monitor/event_service.py:644 `runtime_path("data/control_plane_events_v21.sqlite3")` | ops/monitor | **否（硬编码）** | P1（与 BH5 概念重叠、双 events 库、无键） |
| BH7 | schedules_v21 | domains/schedule/service/schedule_store.py（4 表 schedule_plans/occurrences/send_log/quiet_exceptions） | schedule | 是 `bot_schedule_db_path` | P2（AGENTS 未提，盘上无=未触发） |
| BH8 | campus | domains/assistant/campus/campus_store.py:40 | assistant/campus | 是 `bot_campus_db_path` | P3（AGENTS#33 有、db-owners 无） |
| BH9 | divination `draws` | domains/divination/store/draw_store.py:229（表 draws） | divination | **否（`bot_control_plane_divination_db` 全树未定义）** | P1（见 D1-归属分裂-1） |
| BH10 | divination `tarot_draws`/`daily_fortune` | domains/divination/data/draw_store.py:399 | divination | 无（路径注入，未接生产） | P2 |
| BH11 | runtime_events_v1 + v21 | ops/monitor/event_store.py:504（表 runtime_events_v1 / _v21 + watermark） | ops/monitor | 无 | P2（与 BH6 同库不同表版本，双 schema 并存） |

**③ 归属分裂（≥2 模块直接建表/写同库/同概念）：逐条**

**D1-归属分裂-1（P1｜divination 双 DrawStore）**
- 坐标：`domains/divination/store/draw_store.py`（class `DrawStore`→表 `draws`，`_resolve_db_path` 走 runtime_paths）与 `domains/divination/data/draw_store.py`（**同名 class `DrawStore`**→表 `tarot_draws`+`daily_fortune`，:390 `self.db_path = Path(db_path)` **不走 runtime_paths 重映射**）。
- 锚点：`class DrawStore` （两文件同名）；`db_path = getattr(config, "bot_control_plane_divination_db", None)`（facet.py:331）。
- 根因：同域两个同名 `DrawStore`，一个用 `runtime_path` 一个用裸 `Path`；`store/` 版依赖的 config 键 `bot_control_plane_divination_db` **在 config.py 全树未定义**→facet.py:331 `getattr(...,None)`→`:332 if not db_path: return None`→**`draws` 表生产永不建**（死建表码 + 潜在裸 `Path` 写源码树风险，若哪天手滑补上相对路径键）。
- 证据：`grep -n "divination_db\|control_plane_divination" config.py` = NOT DEFINED；`find ChatBot_Runtime/data` 无任何 divination/`.sqlite3` 落盘（两 store 生产均未激活）；capabilities/divination.py:433 `draw_store: Any | None = None`（不注入即零持久）。
- 改法：删死 store 或收编为单一 owner；若留 `data/` 版，`self.db_path=Path(db_path)` → `self.db_path=_resolve_db_path(db_path)`（与 `store/` 版同规则），并补 config 键或删键引用。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=1=0 ..venv/python -c "import ast,sys;[print(p) for p in __import__('pathlib').Path('plugins/bot_unified_runtime/domains/divination').rglob('*.py')]"` 人工核 DrawStore 唯一性 + scoped pytest `-k divination`。

**D1-归属分裂-2（P1｜events 三库并存、同「事件」语义）**
- 「事件日志」在数据层有**三种落点且无单一 owner**：①`data/runtime_events.log`（**纯文本**，config `bot_runtime_log_file`，runtime_event_log.py，`/bot runtime` 聚合源=AGENTS K2）；②`control_plane_events.sqlite3` 表 `runtime_log_events`（control_plane/events.py，config `_events_db`）；③`control_plane_events_v21.sqlite3` 表 `runtime_events_v1`+`runtime_events_v21`（event_store.py，event_service.py 硬编码路径、**无 config 键**）。
- 锚点：`runtime_path("data/control_plane_events_v21.sqlite3")`（event_service.py:644）；`CREATE INDEX IF NOT EXISTS runtime_events_source_cursor ON runtime_log_events`（events.py:255）。
- 根因：v21r2/v21r4 迭代新增 event_store v21（含 `_v1`/`_v21` 双 schema 版本表同名并存），既没并入 config 也没并入 db-owners，与既有控制面 events 库平行。同一「运行时事件」语义三处安放、消费方各自读。
- 证据：db-owners.md 三处全无；`grep runtime_event_log` 指向 .log 文本、`grep events_v21` 指向 event_store；盘上三库皆无（特性关）。
- 改法：单一 events owner 裁定（建议 SQLite 版为真、.log 作可再生镜像）；`event_service` 硬编码路径 → 新 config 键；`runtime_events_v1` 旧 schema 若弃用则登记清理。
- 验证：`grep -rn "control_plane_events" plugins/ | grep -v test`（收口后应只剩一处 owner）。

### 台账散落库逐个核验（真身 owner + 路径键）
| 台账提及库 | 真身 owner（canonical 文件） | 路径键 | 盘上 | 判定 |
|---|---|---|---|---|
| user_affinity | domains/chat_reply/character/affinity.py:748（含 `affinity_delta_log`:712、`group_affinity`） | `bot_affinity_db_path` | 活跃 135KB | ✓单 owner，delta_log 同库（非分裂） |
| addressing_preferences | domains/chat_reply/character/addressing.py:109 `check_same_thread=False` | `bot_addressing_preferences_db_path` | 陈旧 09-13 | ✓ |
| reflection/memory | reflection.py:268 / memory.py:238（表 memory_facts）；隔离表 memory_quarantine 在 security/memory_sanitize.py:90（**同 memory 库？需核 D2**） | `bot_reflection_db_path`/`bot_memory_db_path`(env) | 活跃 | ⚠ memory_quarantine 建在哪个库见 D2 归属核验 |
| campus | domains/assistant/campus/campus_store.py:40 | `bot_campus_db_path` | 无（未启用） | 黑户 BH8 |
| media_archive | domains/media/archive/media_archive.py:166 | `bot_media_archive_db_path` | 陈旧 09-13 | ✓ |
| notes | domains/notes/store/notes_store.py:168 | `bot_notes_db_path` | 活跃 | ✓（db-owners 标「待生成」已过期，实际 09-18 已在写） |
| web_intent_telemetry | domains/ops/monitor/intent_telemetry.py:67 | `bot_web_intent_telemetry_db_path` | 无（默认关） | ✓（db-owners 标待生成） |
| send_queue | domains/transport/sender/queue.py:297,1610 | `bot_send_queue_db_path`(env=wuwa_send_queue) | 活跃 4MB | ✓ |
| idempotency | domains/chat_reply/runtime/event_idempotency.py:127 | `bot_event_idempotency_db_path`(env) | env 未设=内存 | ✓ |
| llm 相关（存储层，计价逻辑归 U12） | ledger.py:451,730（llm_call_records/daily/balance_snapshots）· usage_service.py:1064（budget_accounts/reservations）· billing_service.py:176,920（billing_* 7 表 + budget_accounts + budget_reservations） | 各自 env 键（llm_billing 盘上不存在） | 表结构见 D2「budget_accounts/budget_reservations 三处共名」 | ⚠ 见 D2 归属核验 |
| runtime_event_log | 见 D1-归属分裂-2（.log 文本非 SQLite） | `bot_runtime_log_file` | 活跃文本 | ⚠ 三库分裂 |
| diagnostics | domains/ops/smoke/diagnostics.py:381（表 runtime_diagnostics）；另有 `wuwa_diagnostics`(env) | `bot_diagnostics_db_path`(env) | 活跃 wuwa_ + 僵尸空 audit/diag/receipts | 僵尸库见 D3 |
| reactions | domains/meme/sources/reaction_store.py:45（表 reaction_events，event_id 幂等） | `bot_reactions_db_path` | **活跃 09-19** | ✓（db-owners 标「待生成：生产未重启」= 已过期，实际在写） |
| subscriptions outbox | domains/subscribe/store/subscription_store_v2.py:147（subscription_outbox + _deliveries 双表） | `bot_subscribe_db_path` | 活跃 | ⚠ outbox 与 outbox_deliveries 双表，见 D2 |

---

## D2 访问通路统一性

### 连接/生命周期 helper 份数  `[x]`
- **无中央连接 helper。** plugins 内 `sqlite3.connect(` 共 75 处、`_connect()/_connection()` 各模块自建 20+ 份（每个 store 一个）。全树零 `create_engine`（无 SQLAlchemy，纯 stdlib）。
- `runtime/database_broker.py` 是 **L42 特性服务**（受门控的受控 SQL 执行器），**不是** 50 个 store 复用的通用连接器——它不统一任何既有 store 的连接生命周期。
- 两种连接形态并存且无统一约定：
  - **A 形态（长连接+锁，新派）**：持久 `self._conn = connect(check_same_thread=False)` + `threading.RLock` 串行。成员（21 个）：addressing/affinity/mood/quirks/reflection/session_identity/notes/reminders/schedule_store/schedule(reminders)/subscription_store_v2/vector_knowledge/ledger/queue/receipts/media_registry/music_request_store/memory_store_v21/persona_service/teaching_service/cp(platform/audit)。交叉核验：**凡 `check_same_thread=False` 者均在 lock 名单内**（无「共享连接无锁」裸奔）→ 此面一致性良好（正面）。
  - **B 形态（每次调用新建连接，旧派）**：`def _connect(): return sqlite3.connect(...)` 每操作开闭。成员：history/memory/audit-logger/diagnostics/result_unknown/intent_telemetry/meme_library/campus/parse_history/group_files/channel_health/eat/divination×2/event_idempotency/…（多数）。

### PRAGMA 差异（busy_timeout/WAL/fk/synchronous）  `[x]`
- **WAL 采纳率 ~半**：`PRAGMA journal_mode=WAL` 命中 25 模块；其余写库仍默认 rollback journal（DELETE）。
- **busy_timeout**：显式 `PRAGMA busy_timeout` 仅 10 文件；其余靠 `connect(timeout=…)` 参数或**吃 Python 默认 5s**。`foreign_keys=ON` 仅 5 处（teaching/music/event_store/subscription_v2 + cp）——外键大多未开。
- **D2-PRAGMA-1（P2｜热写库未 WAL+无 busy_timeout=与 mark_done 死锁同族）**
  - 坐标/锚点：`domains/chat_reply/character/history.py:667` `connection = sqlite3.connect(self.db_path)`（**无 journal_mode、无 timeout、无 PRAGMA busy_timeout**，全文件除 `PRAGMA table_info` 外零 PRAGMA）；`domains/ops/audit/logger.py:205` 同形（grep `journal_mode|busy_timeout|timeout=` = 0 命中）；`domains/chat_reply/character/memory.py:238` 同形；`domains/ops/monitor/result_unknown.py:94` `timeout=5.0` 但无 WAL。
  - 根因：character-v5 新派 store 已批量迁 WAL+timeout+lock，但**最热的三条写路径**（history 每轮对话都写、audit 每审计事件写、memory 记忆写）停留在「无 WAL + 每调新建连接 + 默认 5s」。journal_mode=DELETE 下写者独占、读阻塞，突发并发/读写交叠即 `database is locked`。
  - 证据：`find` 显示 wuwa_history 2.1MB、wuwa_audit 348KB **活跃在写**；上表 grep 实证 PRAGMA 缺失。
  - 改法：`history._connect` 首行后加 `connection.execute("PRAGMA journal_mode=WAL")` + `connect(self.db_path, timeout=10.0)`（memory/audit/result_unknown 同）；或并入统一 `_connect` helper。
  - 验证：`grep -n "journal_mode=WAL" plugins/.../history.py` 命中 + scoped `pytest -k "history or audit"`。

### 事件循环线程内同步 DB IO  `[x]`
- 中央 `offload_capability`（`domains/chat_reply/runtime/pipeline.py:225`）经 `loop.run_in_executor(pool, …)` 把能力体甩到专用线程池（注释 :78-81：避免挤占默认 to_thread 池）；`__init__.py` 内 18 处 `to_thread`，且 `:321` 有注释「调度器路径已 to_thread，命令路径同款必须 offload（审计重发现 P1）」→ 项目**已意识到并修过多处**，并有 `loop-watchdog`（`__init__.py:3634`）探测冻结。
- **残余在飞（P2）**：`__init__.py:3906 async def _notify_operational_receipt` 于 :3916 **直调** `result_unknown_ledger.record(...)`（无 to_thread）→ 非 WAL SQLite 写发生在事件循环线程；触发条件=发送队列产出 `result_unknown` 运行回执时。同 helper 若上层再叠 WAL 缺失即「循环线程被 DB 锁阻塞」双重放大。`runtime_event_log.emit`（:1198，写文本 .log）为同步 append，调用点若在 async 摄取路径则同属在飞面（次要，量小）。
- 改法：:3916 包 `await asyncio.to_thread(result_unknown_ledger.record, …)`；或把 result_unknown 升 WAL+timeout。验证：`grep -n "asyncio.to_thread" plugins/.../__init__.py` 覆盖 3916 上下文。

### 迁移/建表策略与 schema_version  `[x]`
- **D2-VER-1（P2｜schema 版本追踪缺位）**：`PRAGMA user_version` 全树 **0 处**；仅 `schema_meta` 表有版本号的库 **3 个**（music_request_store、subscription_store、subscription_migration）。其余 ~47 库无版本表。迁移靠 `CREATE TABLE IF NOT EXISTS` + **列级 `ALTER TABLE ADD COLUMN`（9 模块 12 处，见下）+ `PRAGMA table_info` 探测列是否存在（16 模块）**——每模块各写一套列迁移，无统一版本号/迁移框架，失败面为「列探测→缺则 ADD」的 try/except 静默。
  - ADD COLUMN 迁移实现者：affinity/history/memory/quirks/vector_knowledge/channel_health/diagnostics/queue/receipts（各自 `PRAGMA table_info`+`ALTER`）。
  - 改法：低风险起步=对活跃库补 `PRAGMA user_version` 记录当前 schema 代次，迁移集中到一处 helper；不建议大改（既有 ADD-COLUMN 幂等可用）。验证：`grep -rn "user_version" plugins/` 从 0 起步。

### 事务与幂等唯一约束  `[x]`
- **表级去重普遍到位（正面）**：`send_requests.dedupe_key TEXT PRIMARY KEY`（queue.py:1483）·`event_idempotency PRIMARY KEY(event_key,capability_id)`（event_idempotency.py:115）·`reaction_events.event_id PRIMARY KEY`·`subscription_outbox PRIMARY KEY(event_id,destination_key)`·`diagnostics.request_id PRIMARY KEY`·`result_unknown PRIMARY KEY(request_id,created_at)`·`events.event_id UNIQUE`·`draws(idempotency_key) UNIQUE`（该 store 未激活）。幂等判定在**表上**而非纯应用层。
- **D2-IDEM-1（P2｜`budget_reservations` 同名异表结构，双模块 DDL）**：`usage_service.py:1034`（列 `scope,currency`）与 `billing_service.py:1181`（列 `budget_id,attempt_id,updated_at`）**同表名不同列集**，均 `CREATE TABLE IF NOT EXISTS`→若被指向同一 db 文件，先建者胜、后者静默 no-op，运行时读缺失列 `no such column`。现状：两模块**均未在 `__init__.py` 装配**（无生产调用点，重启亦不激活）→ 潜在 P2（计价逻辑归 U12，本条仅报存储层表结构归属冲突）。`budget_accounts` 仅 usage_service 建，不冲突。改法：单一 owner 定 budget_* schema 或拆表名/拆库。验证：`grep -rn "CREATE TABLE IF NOT EXISTS budget_reservations" plugins/` 应只剩一处。
- **重放补偿数据缺口（P2）**：好感度误扣重放补偿（L60 立项）——`affinity.py:712` 建 `affinity_delta_log`（+`idx_affinity_delta_log_event_id` UNIQUE:741）作逐事件账，`affinity_replay.py:181` 以 `mode=ro` 只读消费；**事故窗口（≤2026-09-17）的库缺该表**（affinity_replay.py:175 明确 `_require_tables` 抛 `ReplayDataMissing`，:637 注「delta_log 之前物理缺失，仅聚合计数」）→ 数据层缺口=历史行无法逐事件重放，非连接问题。诚实记录，不裁决。

### 正面结论（勿重复怀疑）
- 长连接 store 一律 `RLock`+`check_same_thread=False` 串行，无共享连接无锁裸奔。
- 幂等键绝大多数落表级 PK/UNIQUE，非应用层判重。

---

## D3 生命周期与配额  `[x]`

### 每库/每表 prune 策略矩阵
`grep def _prune|prune|DELETE FROM|retention|keep_days|max_items|vacuum` 全树。**覆盖面广**（30+ 模块含清理）。分类：
- **写内/滚动自清（✓）**：send_queue `_prune`（queue.py:1630，终态行淘汰、非终态永不删 :703）、receipts `_prune`(max 1000)、audit_records/logger `_prune`、diagnostics `_prune`(写内)、result_unknown、intent_telemetry(≤10000)、decision_trace(保留 5 万滚动)、music(365d `bot_music_analytics_retention_days`)、media_registry `_prune_locked`、event_idempotency(按 claimed_at DELETE)、rate_limit(窗口)、**meme_library `cleanup(max_files=20000,max_age_days=30)` 且监听器触发（meme_library_listener.py:313，含图片文件 `unlink` + 行 `DELETE` 双清）**、reactions(启动期 90d)、reminders(完成/过期按行)、vector_knowledge(sync_chunks 按清单差集删)。
- **按设计只增不删（P3，需知悉）**：memory_v21（status=forgotten+墓碑，行永不 DELETE，db-owners 已注明=审计依赖）、teaching_*（append-only 版本史）、persona/worldbook_versions（触发器锁死不可变）、memory_quarantine（取证证据）。→ 生命周期无压缩，单调增长。
- **按基数天然有界无 prune（P3）**：user_affinity/addressing_preferences/session_identity/quirks/persona_quirks/bot_mood——一行/用户或一行/会话，随**独立用户/会话数**增长，无 TTL；量小可接受，但 session_identity 随历史会话累积无回收登记。
- **无任何清理**（本席猎杀）：**除上述外无「零清理」的活跃遥测/事件/日志表**——事件类（runtime_events_v1/v21、events_v21 watermark）随 event_store 落库，该 store 未接生产（盘上无文件），故暂无增长；一旦接线需确认 prune（event_store __init__ 有 max_events 形参，未见启动期触发方）。

### 磁盘占用与限额覆盖
- **数据根实测 13GB**（`du -sh ChatBot_Runtime/data`）。大头（只读 du）：meme_library/ **3.2G**（5297 文件，有 cap 见上）、music/ 486M、meme_generator/ 402M、cards/ 262M（渲染域目录，prune keep=120 见 AGENTS#26⑨，**本席按范围裁定不深入**）、downloads/ 244M、card_samples/ 18M、today_history_kb/ 16M。
- **D3-SIZE-1（P1｜向量库体量无 DB 级配额、BLOB+FAISS 双份）**
  - 坐标：`ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3` = **5,672,304,640B(5.28GB)**（只读 COUNT：`knowledge_chunks`=238,614、`knowledge_docs`=75,708）；`knowledge_faiss.index`=1.04GB、`knowledge_embeddings.sqlite3`=905MB + `knowledge_faiss.index`=154MB。
  - 根因：同一语料的向量**既存 SQLite BLOB 又落 FAISS 文件**（双份，约 (5.28+1.04)GB for wiki）；无文件级/DB 级容量上限（现有配额只到「单能力」粒度：media 100MB、meme 20000 文件、intent 10000——**向量库无对应配额键**）。`_build_vector_cache`（vector_knowledge.py:646）检索期建 numpy 全量矩阵 → 体量增长同时是**内存**风险不止磁盘。
  - 证据：`du`/`find -printf %s` 只读实测；`grep quota` 无向量库配额键。
  - 改法：为两向量库加「软容量水位」告警键（超阈不静默涨）；评估 embedding 单存 FAISS、SQLite 去 BLOB 留元数据；消费侧向量缓存分片加载。
  - 验证：`du -sh ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3`（收口后应显著下降或有水位告警）。
- **文件级限额实现分散**：media_archive(100MB/50d/4-msg AGENTS#28)、meme(20000/30d)、intent(10000)各自实现，无统一「磁盘配额器」；downloads/、card_samples/、FAISS、向量库覆盖缺口。

### 孤儿与废弃 / 双写双读
- **D3-ZOMBIE-1（P3｜4 个僵尸空库无 reader/writer/cleanup）**：`data/audit.sqlite3`(0B)、`diagnostics.sqlite3`(0B)、`receipts.sqlite3`(0B)、`_diag_debug.sqlite3`(20480B,停 08-24)。证据：`grep "data/audit\|data/diagnostics\|data/receipts\|_diag_debug" plugins/ scripts/ bot.py` = **0 命中**（无任何代码路径引用），mtime 停 09-08/08-24 = 历史 .env 旧命名残留；现行数据落 `wuwa_audit/wuwa_diagnostics/wuwa_receipts`（活跃）。非双写（空库零写入），纯孤儿噪声。改法：确认无引用后随停机清理（删 .sqlite3 连带 -wal/-shm）。
- **无「同一数据两处副本双写」**：迁移备份 `subscriptions_old.sqlite3`(40960,08-22) 属 db-owners §3.3 归档待删，非双写；V1→V2 由 `prepare_subscription_database` 改名备份、二次迁移被 refusing-overwrite 拦。
- **零读写方的废弃表**：`subscription_store.py`(V1) 的 subscriptions/cursors/push_log/digest_pending 四表在 V2 激活后仍**存在于 subscriptions.sqlite3**（V1/V2 **同库不同表名空间**：V1 `subscriptions` vs V2 `subscription_targets`…）。V1 表是否仍有读方需核（`grep` V1 类使用）——若仅迁移期用则属可清理遗留。
- **db-owners.md 状态字段过期（P3）**：`notes/reactions/web_intent_telemetry` 三条仍标「待生成：生产未重启」，实际 reactions(09-19) / notes(09-18) 盘上活跃在写 → 文档「待生成」判定失真，须改「活跃」。

### 知识/向量面漂移取证（数据一致性，不裁决）
- **D3-DRIFT-1（P1｜persona 知识库 ANN/FTS 严重滞后于 chunks）**
  - 只读实测：`knowledge_embeddings.sqlite3` → `knowledge_chunks`=**4,611**（真相源）；`knowledge_faiss.index` ntotal=**35,341**；`knowledge_chunks_fts`=**35,341**。→ ANN+FTS 携带 **~30,730 条** 指向已不存在 chunk 的向量/索引行（7.6x）。对照 `kb_wiki_embeddings`：chunks 238,614 == FAISS ntotal 238,614 == FTS 238,614 → **内部一致（无漂移，仅体量）**。故 AGENTS/HANDOFF 的「kb_drift 35341 vs 4611」实锤定位在 **persona 知识库**。
  - 真相源=`knowledge_chunks` 表；校验/重建通路=sync_chunks（差集删 `source_id NOT IN`→已改按 ledger-manifest 差集，vector_knowledge.py:758）+ 签名门 `fts_signature`(:39)/`_fts_valid`/`vector_meta`(:654)/`_ann_order`(order.json :440)。
  - 消费方读到不一致时的行为：检索 `for chunk_id in vector_ids`(RNN/RRF :366) 合并 ANN∪FTS∪bonus 的 chunk_id 打分，dangling chunk_id 在正文懒加载时查无行→被过滤（**不崩**），但**陈旧向量参与排序=召回被稀释、近邻错配**；大库路径 `fts_auto_rebuild=False`（:471-473 注释「大库重建分钟级，不做内联重建」）→ 签名不一致时不自愈，漂移粘滞。
  - 现状：`pre_restart_check.py:339` 以 `mode=ro` 只读探测该漂移并 FAIL 上报（AGENTS 六：kb_drift 存量待裁决=忽略或重建）。**本席只报事实与影响，重建与否归用户**。
  - 验证（只读）：`python -c "import faiss;print(faiss.read_index('.../knowledge_faiss.index').ntotal)"` 对比 `SELECT COUNT(*) FROM knowledge_chunks`。

### 正面结论
- 绝大多数可再生/遥测/事件/队列/媒体表都有 prune；meme 树文件+行双清且监听器自动触发。
- kb_wiki 向量库内部一致；漂移是**特定单库**（persona KB）问题，可定位、可复跑取证。

---

## D4 数据安全与备份面  `[x]`

### Runtime 数据覆写风险
- **正面（保障在位）**：①`BOT_AUTOSYNC=1` 钩子（conftest.py:88 `run_autosync`）仅重跑 `command_catalog/doc_sync/verify_hashes --write`，**全部落源码树生成物、绝不写 Runtime**；②人格副本覆写走 `scripts/sync_persona_source.py --adopt`（:72 `resolve_copy_path`，覆写 Runtime 人格副本 + 重录锚），且被 `pre_restart_check.py:261` 显式「人工审阅后 --adopt」门控 → 与 HANDOFF「垫片覆写数据事故」**同族但已有审阅闸**；③改 Runtime settings JSON 的脚本（apply_config_batch.py:135 / configure_axonhub_registry.py:166 / consolidate_model_registry.py:144）一律 `shutil.copy2(SETTINGS, backups/…bak-{stamp})` **先备份后 `write_text`**。
- **D4-OVERWRITE-1（P1｜无「测试写生产 Runtime」防线）**：`runtime_paths.runtime_data_dir()` 读 `_dotenv_value("BOT_RUNTIME_DATA_DIR") or "data"`（:53）→ 生产经 .env 解析到 `ChatBot_Runtime/data`；conftest 的 G1 写拦截守卫 `_REPO_DATA = REPO_ROOT/"data"`（:214）**只快照源码树 data/，不覆盖 ChatBot_Runtime/data**。任何测试以默认路径构造 store、或拨开「急切建库」服务门（Teaching `bot_teaching_enabled`/broker `bot_database_broker_enabled` **缺省 True**，config.py:165/169），即写进**生产 Runtime 库**且不被任何守卫拦下。
  - 证据：HANDOFF-V21R5 §三.B 实锤「WIRE-SVC 首轮测试 stub → Runtime data 一过性教导库文件，备份 %TEMP%\wiresvc_runtime_backup 后删除」= 该缺口已发生一次；conftest 全篇无 `setenv("BOT_RUNTIME_DATA_DIR", tmp)` 会话级钉。
  - 改法：conftest 加 session autouse `monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_runtime))` 使测试期 `runtime_path()` 恒指临时根；G1 快照根改读**解析后的 runtime_data_dir()** 而非仅 REPO/data。
  - 验证：造一个「以默认 path 建 store」的测试 → 改前落在 ChatBot_Runtime/data（守卫不红）、改后落 tmp 且越界即 AssertionError。

### 备份 / 恢复通路 + 测试污染生产库
- **备份通路：仅两处**——①`memory_service.backup_to/restore_from`（:581/:591，用 sqlite `.backup` API + 恢复后重放墓碑「恢复不复活」）——**唯一有程序化快照/恢复的库，且 memory_v21 未接生产**；②`ChatBot_Runtime/backups/` 仅存 09-11 手工 `.bak`（env×2、runtime_settings×4、wuwa_history×1）。**其余 ~50 个 SQLite 库无任何备份/导出/只读快照通路**，误删=不可恢复（仅靠铁律2 人工不删）。
- **D4-BACKUP-1（P2｜生产活动库零备份）**：活跃库（user_affinity/reflection/wuwa_history/wuwa_memory/subscriptions/knowledge_embeddings 905MB/kb_wiki 5.28GB）无自动快照；`restore_from` 只覆盖未接线的 memory_v21。改法：对「禁删」学习/记忆库补周期性 `sqlite3.Connection.backup` 快照到 backups/（带轮转），复用 memory_service 已有实现口径。验证：`find ChatBot_Runtime/backups -name '*.sqlite3.bak' -newermt '-7d'` 应见活动库快照。
- **测试污染生产库**：源码树 `data/` 实测**零残留**（G1 守卫根治台账#1）；但 `ChatBot_Runtime/cache/pytest_{agentA,ci_78640,ci_manual,me}/basetemp/**.sqlite3` 存**大量未清理的测试基座库**（09-10～09-16，数十个 send_queue/affinity/subscriptions/cp 等）——tmp_path 基座选了 `--basetemp` 落 `ChatBot_Runtime/cache` 却**无会话后清理** → 属测试卫生残余（在 cache/ 非生产 data/，不污染真数据但累积占空间）。仍写真实 `runtime_path` 的具体用例：随 D4-OVERWRITE-1 一并钉 tmp 后归零。

### 敏感数据落盘面（只报形态与路径键，不抄值）
- **D4-SEC-1（P2｜静息全明文库）**：`grep Fernet|AESGCM|Cipher|encrypt`（stores 内）= **0 命中** → 所有 SQLite 与 cookie/媒体/prompt 落盘**明文**（仅 TLS 传输加密 + OS 文件权限保护）。明文敏感面：`wuwa_memory`(memory_facts)、`wuwa_history`(conversation_turns)、`user_affinity`、`notes`、`media_archive`+JSON 旁车、cookie 文件、`data/prompt_audit`（config `bot_prompt_audit_dir`、`include_messages=True`:819、enabled=True:817、retention_days=14:824，仅 prompt_preview CLI 写、主链路不读）。
- **缓解（部分，在位）**：①入库前凭证打码 `redact_history_text`（history.py:39，正则洗 bearer/sk-/cookie=k 形态为 `[redacted]`）→ **密钥/cookie 值不落 history**（但聊天正文/记忆语义仍明文）；②出站 `output/plain_text.redact_local_secrets` 打码盘符/sk-/BOT_XXX_（不改静息）；③离线 `scripts/scrub_history_credentials.py`（:127 只读扫 + :163 写清）可二次洗；④memory 隔离 `memory_quarantine` 表（memory_sanitize.py，与被洗行同行库）。
- **缺口**：无统一「静息加密/脱敏位」——加密与否取决于各 store 自觉；`prompt_audit` 含消息正文明文虽 14d TTL 但明文可回读；cookie 文件明文（形态，路径经 runtime 根）。改法：对「禁删学习/记忆库」至少提供 keyring/Fernet 列级加密开关（默认关、opt-in，避免破坏既有可读工具链），并把 `redact_history_text` 同款洗扩展至 memory_facts/notes 落库前。验证：`grep -rn "encrypt\|Fernet" plugins/.../character plugins/.../notes` 从 0 起步（若采纳）。

---

## 收口清单（数据层单一 owner + 单一访问通路，按解锁顺序）

> 排序原则：先堵「会丢数据/会写脏生产」（P1 数据完整），再并「归属/通路分裂」，后清「卫生/文档」。

**T0 立即（P1，防数据事故）**
1. **D4-OVERWRITE-1**：conftest 加 session autouse `setenv("BOT_RUNTIME_DATA_DIR", tmp)`，G1 快照根改读解析后的 `runtime_data_dir()` → 测试期 `runtime_path()` 永指生产。这是 WIRE-SVC 一过性误写的根治，先于任何服务门接线。
2. **D3-DRIFT-1**：persona 知识库 ANN/FTS(35341) vs chunks(4611) 漂移——提供一条 `mode=ro` 只读校验+显式重建通路（sync 时按 ledger 全量重灌 FAISS+FTS 至与 chunks 同计数），并把 `pre_restart_check` 的 FAIL 升级为「可一键重建」指引（重建动作归用户，AI 不代跑）。
3. **D3-SIZE-1**：kb_wiki 5.28GB+FAISS、knowledge 905MB+FAISS、BLOB 双存、无 DB 级配额 → 加「软水位告警键」，检索期全量 numpy 矩阵改分片，评估去 SQLite BLOB。

**T1 归属统一（P1/P2）**
4. **events 三库分裂（D1-归属分裂-2）**：`.log` 文本 / control_plane_events / control_plane_events_v21(+v1) → 单一 events owner 裁定 + event_service 硬编码路径改 config 键 + 旧 `runtime_events_v1` schema 登记清理。
5. **divination 双 DrawStore（D1-归属分裂-1）**：删死 `store/draw_store.py`（依赖未定义 config 键）或收编 `data/draw_store.py` 单一 owner；统一走 `_resolve_db_path`（禁裸 `Path`）。
6. **llm 三 store（存储层）**：`budget_reservations` 同名异 schema（usage vs billing）择一 owner/拆库；`llm_billing.sqlite3` 作为 control_plane_audit + llm ledger 共库不同表——**登记进 db-owners 并声明双 co-owner**（当前零登记）。
7. **黑户库 11 处**（BH1-11）全部并入 db-owners.md（见修订表）。

**T2 访问通路统一（P2）**
8. **热写库补 WAL+busy_timeout（D2-PRAGMA-1）**：history/memory/audit/result_unknown（盘上无 -wal 实证非 WAL）→ `PRAGMA journal_mode=WAL`+`timeout=10`。
9. **on-loop DB IO（D2 事件循环）**：`__init__.py:3916 result_unknown_ledger.record` 包 `to_thread`。
10. **统一连接 helper**：抽 `runtime/_sqlite.py`（open+PRAGMA+schema 版本迁移一站式），逐步替掉 20+ 份自建 `_connect`。
11. **schema 版本（D2-VER-1）**：活跃库补 `PRAGMA user_version`，迁移集中化。

**T3 生命周期/安全/卫生（P2/P3）**
12. **D4-BACKUP-1**：禁删学习/记忆库补周期 `Connection.backup` 快照+轮转（复用 memory_service 口径）。
13. **D4-SEC-1**：静息明文——opt-in 列级加密开关 + `redact_history_text` 同款扩至 memory_facts/notes。
14. **D3-ZOMBIE-1**：4 个 0 字节僵尸库（audit/diagnostics/receipts/_diag_debug）确认零引用后随停机清；`ChatBot_Runtime/cache/pytest_*` 基座库纳入清理。
15. db-owners.md 状态字段过期（reactions/notes「待生成」实为活跃）+ 旧顶层路径改指 canonical（P3）。

---

## 建议 db-owners.md 修订表

> 仅列**需新增/需更正**的行（既有正确行不重抄）。「现状判定」：OK=文档属实 / 补登=黑户 / 更正=文档失真。

| 库名（默认路径） | owner 模块（canonical） | 路径键 | 建表处 | prune 策略 | 现状判定 |
|---|---|---|---|---|---|
| control_plane_config | control_plane/config_store.py | `bot_control_plane_config_db` | config_store.py:167 | 未见 | 补登 BH1 |
| control_plane_features | control_plane/sqlite_features.py | `_features_db` | sqlite_features.py:136 | 未见 | 补登 BH2 |
| control_plane_actions | control_plane/actions.py | `_actions_db` | actions.py:148 | actions TTL（有 prune） | 补登 BH3 |
| control_plane_platform | control_plane/platform.py | `_platform_db` | platform.py:22 | 未见 | 补登 BH4 |
| control_plane_events | control_plane/events.py（表 runtime_log_events） | `_events_db` | events.py:267 | events prune | 补登 BH5 |
| control_plane_events_v21 | ops/monitor/event_service.py→event_store.py | **无（硬编码）** | event_store.py:504 | max_events | 补登 BH6+建议加键 |
| runtime_events_v1（同库旧版） | ops/monitor/event_store.py | 同上 | event_store.py:504 | — | 补登 BH11，登记待清 |
| llm_billing（**共库不同表**：control_plane_audit + llm_call_records/llm_usage_daily/balance_snapshots） | control_plane/audit.py + llm_engine/ledger.py | `bot_llm_billing_enabled`（ledger）；audit 无独立键 | audit.py:195 / ledger.py | 未见（账本关，盘上无文件） | 补登，声明双 co-owner |
| schedules_v21 | domains/schedule/service/schedule_store.py（4 表） | `bot_schedule_db_path` | schedule_store.py | 未见 | 补登 BH7 |
| campus | domains/assistant/campus/campus_store.py | `bot_campus_db_path` | campus_store.py:40 | 90d（AGENTS#33） | 补登 BH8（AGENTS 有、db-owners 无） |
| divination（draws / tarot_draws / daily_fortune） | **双同名 DrawStore**：divination/store + divination/data | store 版键未定义 / data 版无键 | store:229 / data:399 | 未见 | 补登 BH9/10 + 归属分裂修正 |
| reactions / notes | meme/sources/reaction_store.py / notes/store/notes_store.py | `bot_reactions_db_path`/`bot_notes_db_path` | reaction_store:45 / notes_store:168 | 90d / 按行 | **更正**：「待生成·未重启」→ 活跃在写（盘上 mtime 09-18/19） |
| user_affinity（+ affinity_delta_log / group_affinity） | domains/chat_reply/character/affinity.py | `bot_affinity_db_path` | affinity.py:748 / delta_log:712 | 无（按用户基数） | 更正：路径改指 canonical + 注明 delta_log 同库、重放缺史窗数据 |
| knowledge_embeddings / kb_wiki_embeddings | domains/chat_reply/character/vector_knowledge.py | `bot_knowledge_db_path`/`bot_kb_wiki_db_path` | vector_knowledge:504 | sync_chunks 差集 | **更正+风险标注**：5.28GB/905MB 无 DB 级配额；persona 库 ANN/FTS 漂移 35341≠4611 |
| 僵尸库 audit/diagnostics/receipts/_diag_debug | （无 writer） | 无 | — | — | **新增「孤儿」节**：0 引用，随停机清理 |

---

## 自查与临时物披露
- **只读纪律**：全程未写/删/移动 ChatBot_Runtime 任何文件；所有 Runtime SQL 以 `sqlite3.connect(f"file:{p}?mode=ro", uri=True)` 打开（见 D3/D4 脚本）；未读 .env 明文值（仅按代码 `getattr`/键名取证）。
- **临时物**：本席所有 `python -` 查询走 **inline heredoc**，未在源码树或 %TEMP% 落任何 `.py`/缓存。直跑带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；未跑 pytest（无 basetemp 需求）。结束自查 `find -newermt '-2h' __pycache__/*.pyc/data/*.sqlite3`（排除 ChatBot_Runtime）= 空；源码树零新增缓存。%TEMP% 中 `u15_probe*/u3_probe*` 为他席产物，非本席。
- **唯一写文件**：`docs/design/audit-20260920-unify-U13-db.md`（本文件）。
- **未跑全量门**：无 `dev.ps1 -Task test`（禁）；结论全为静态 grep + 只读 SQL + 只读 du/find。行号会漂，坐标均带锚点串。
- **诚实边界**：未 commit（禁 git 写）；「离线/grep 实锤」≠「生产生效」；kb_drift/备份/加密均只报事实与改法，不代裁不代改；llm 计价逻辑归 U12，本席仅报其表结构与 owner 归属冲突。
- **范围遵守**：未碰 webui/、domains/render/**、output/card_render/**、theme_tokens.py、TTS/语音；cards/ 262M 目录仅记体量、prune 细节归渲染席。
