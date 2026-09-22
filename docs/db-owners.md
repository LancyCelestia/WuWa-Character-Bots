# SQLite 库文件 Owner 清单（db-owners）

> 本文是 2026-09-12 全库 grep 的登记产物：每个 SQLite 库文件 → owner 模块 →
> 建表/迁移位置 → 清理策略。**只登记，不改迁移代码。**
>
> 路径语义：配置中写作 `data/...` 的路径由 `Config._resolve_runtime_data_paths()`
> （`plugins/bot_unified_runtime/config.py`）按 `BOT_RUNTIME_DATA_DIR` 重映射到
> 外部运行数据目录（默认 `ChatBot_Runtime\data`），源码树内不落库。
> `db_path` 配置为空串的库 = 进程内内存实现，不产生文件。
> 全库统一约定：**手工清理前先停机器人进程**（WAL 模式下残留 `-wal/-shm`
> 未合并会导致丢数据），删文件 = 删同目录的 `-wal` / `-shm` 伴生文件。

> **路径时效声明（2026-09-20，LINK-AUDIT §E-2 / DOC-FIX-2 落 R19）**：本表「Owner 模块」列记的是
> 2026-09-12 取证时的目录布局。2026-09-19 的 v21r2 板块重组把绝大多数模块迁到了
> `plugins/bot_unified_runtime/domains/<域>/`，旧路径**多数仍存在但只是 PEP 562 垫片**
> （三—十八行的活转发，可 import、**不代表模块规模，行号更不可信**），少数旧路径已彻底不留。
> 因此本表读法是：**认库名与 owner 语义，路径按符号名现查真身**——
> 复跑 `grep -rl "Compat shim" plugins/bot_unified_runtime --include="*.py" | head` 看垫片全集，
> 或按文件名在 `domains/` 下检索（例：`find plugins/bot_unified_runtime/domains -name '<模块名>.py'`）。
> 本表**不许人工逐行改路径列**（改一次错一次）：现真身列由生成器回填，
> 排期见 `docs/design/link-unification-audit-20260920.md` §7 R19 与 §8 G-4。
> 漂移由常驻门 `tests/test_doc_link_integrity.py` 盯（旧路径与垫片条数走棘轮，只降不升）。

## 一、配置键指定的库（`plugins/bot_unified_runtime/config.py` 为唯一定义点）

| 库文件（默认路径） | 配置键 | Owner 模块 | 建表 / 迁移位置 | 清理策略 |
| --- | --- | --- | --- | --- |
| `data/knowledge_embeddings.sqlite3` | `BOT_KNOWLEDGE_DB_PATH` | `character/vector_knowledge.py` | `CREATE TABLE knowledge_chunks / knowledge_meta / knowledge_docs`（含列迁移）；伴生 `knowledge_faiss.index` | 活动向量库，禁手工删；重建走人格知识库 sync_chunks 全量重灌 |
| `data/kb_wiki_embeddings.sqlite3` | `BOT_KB_WIKI_DB_PATH` | `domains/location/knowledge/kb_wiki.py`（复用 `vector_knowledge.SqliteVectorKnowledgeStore`） | 同上；伴生 `kb_wiki_faiss.index` / `kb_wiki_faiss.order.json` | 同上 |
| env 指定（例 `data/wuwa_memory.sqlite3`；空=内存） | `BOT_MEMORY_DB_PATH` | `domains/chat_reply/character/memory.py` | `CREATE TABLE memory_facts`；隔离区见 `security/memory_sanitize.py`（`memory_quarantine`） | 聊天记忆属活动数据禁删；只经 `/bot memory` 指令操作 |
| env 指定（例 `data/wuwa_history.sqlite3`；空=内存） | `BOT_HISTORY_DB_PATH` | `domains/chat_reply/character/history.py` | `CREATE TABLE conversation_turns`；库内 `_prune_scope` 自动滚动保留窗口 | `/bot history clear`；禁手工删整库 |
| env 指定（空=内存） | `BOT_DIAGNOSTICS_DB_PATH` | `diagnostics.py` | `CREATE TABLE runtime_diagnostics`；写入时 `_prune` | 诊断可再生；需合规时先归档再清 |
| env 指定（空=内存） | `BOT_AUDIT_DB_PATH` | `domains/ops/audit/logger.py` | `CREATE TABLE audit_records`；写入时 `_prune` | 审计留痕：归档优于删除 |
| env 指定（空=内存） | `BOT_RECEIPTS_DB_PATH` | `domains/transport/sender/receipts.py` | `CREATE TABLE delivery_receipts` | 发送回执可再生，可整库重建 |
| env 指定（空=内存） | `BOT_SEND_QUEUE_DB_PATH` | `sender/queue.py` | `CREATE TABLE send_requests` | 发送队列持久层，**运行中禁碰**；停机后可清（丢待发消息） |
| env 指定（空=内存） | `BOT_RATE_LIMIT_DB_PATH` | `domains/chat_reply/policy/rate_limit.py` | `CREATE TABLE rate_limit_events` | 限速计数可再生，可整库重建 |
| env 指定（空=内存） | `BOT_EVENT_IDEMPOTENCY_DB_PATH` | `domains/chat_reply/runtime/event_idempotency.py` | `CREATE TABLE event_idempotency` | 幂等去重可再生；清空后短窗内可能重复响应一次 |
| `data/bot_mood.sqlite3` | `BOT_MOOD_DB_PATH` | `character/mood.py` | `CREATE TABLE bot_mood` | 情绪状态可再生 |
| `data/persona_quirks.sqlite3` | `BOT_QUIRKS_DB_PATH` | `domains/chat_reply/character/quirks.py` | `CREATE TABLE persona_quirks` | 怪癖属学习数据，禁随意删 |
| `data/reflection.sqlite3` | `BOT_REFLECTION_DB_PATH` | `domains/chat_reply/character/reflection.py` | `CREATE TABLE reflection_facts / reflection_digests`（含列迁移） | 反思库属学习数据，禁随意删 |
| `data/session_identity.sqlite3` | `BOT_SESSION_IDENTITY_DB_PATH` | `domains/chat_reply/character/session_identity.py` | `CREATE TABLE session_identity`（含列迁移） | 会话身份可再生 |
| `data/addressing_preferences.sqlite3` | `BOT_ADDRESSING_PREFERENCES_DB_PATH` | `domains/chat_reply/character/addressing.py`（`AddressingPreferenceStore`） | `CREATE TABLE addressing_preferences`（主键 `session_type+session_id+sender_id`；WAL） | 用户显式设置的称谓/性别偏好；清理=按行删（清行后回退推断），不整库删 |
| `data/reminders.sqlite3` | `BOT_REMINDER_DB_PATH` | `character/reminders.py` | `CREATE TABLE reminders` | 用户取消提醒即删对应行；不整库删 |
| `data/user_affinity.sqlite3` | `BOT_AFFINITY_DB_PATH` | `character/affinity.py` | `CREATE TABLE user_affinity / group_affinity`（含 `ALTER TABLE` 增列迁移；G-11 批新增 `impression_tag_times` JSON 列：标签→最近打标时间，印象标签淡出判据） | 管理员可按 config 注释直接改值；禁整库删 |
| `data/media_registry.sqlite3` | `BOT_MEDIA_REGISTRY_PATH` | `domains/media/registry/media_registry.py` | `CREATE TABLE media_assets`；库内 `_prune_locked` 自动过期 | 自滚动，无需手工清 |
| `data/meme_library.sqlite3` | `BOT_MEME_LIBRARY_DB_PATH` | `domains/meme/sources/meme_library.py` | `CREATE TABLE memes` | 表情库属活动数据；随 `bot_meme_library_dir` 图库配套 |
| `data/music_analytics.sqlite3` | `BOT_MUSIC_ANALYTICS_DB_PATH` | `domains/music/data/music_request_store.py` | `CREATE TABLE schema_meta / music_tracks / music_provider_tracks / music_track_aliases / music_request_events / music_chart_snapshots / music_chart_entries`；`schema_meta` 记 schema 版本 | `bot_music_analytics_retention_days`（默认 365）自动滚动 |
| `data/parse_history.sqlite3` | `BOT_PARSE_HISTORY_DB_PATH` | `domains/link_parse/support/parse_history.py` | `CREATE TABLE parse_history` | 解析历史可再生，可整库重建 |
| `data/subscriptions.sqlite3` | `BOT_SUBSCRIBE_DB_PATH` | `domains/subscribe/store/subscription_store.py`（V1：`subscriptions / cursors / push_log / digest_pending`）→ `domains/subscribe/store/subscription_store_v2.py`（V2：`schema_meta` + `subscription_targets / subscription_destinations / subscription_cursors / subscription_seen_items / subscription_outbox / subscription_poll_log / subscription_target_metadata`） | V1→V2 切换由 `domains/subscribe/store/subscription_migration.py::prepare_subscription_database` 完成（`schema_meta.version='2'` 判别） | 订阅状态属活动数据禁删；见下方备份行 |
| `data/subscriptions_old.sqlite3`（迁移备份） | — | `domains/subscribe/store/subscription_migration.py` | V1 库整体改名备份；已存在时拒绝二次迁移（refusing overwrite） | V2 运行验证无误后可归档/删除 |
| `data/campus.sqlite3` | `BOT_CAMPUS_DB_PATH` | `domains/assistant/campus/campus_store.py`（`CampusStore`；旧路径 `sources/campus_store.py` 已退役删除） | `CREATE TABLE IF NOT EXISTS campus_messages`（`message_id` 主键幂等 / `date_key` 索引） | 校园群消息转发去重台账；`date_key` 跨 90 天自动 prune；活动幂等去重数据，禁手工删整库（AGENTS #33） |
| `data/emergency_info.sqlite3` | `BOT_EMERGENCY_INFO_DB_PATH` | `domains/emergency_info/sources/store.py`（`EmergencyStore`/`build_emergency_store`） | `CREATE TABLE`（唯一 `_SCHEMA`，两表：`emergency_items` 含 `(source_id, external_id)` UNIQUE 与 `status` CHECK、`latitude/longitude` 列走 ALTER-if-missing 自动迁移；`emergency_subscriptions` 含 `target_scope` CHECK 与 `target_key` 主键=一群/一人一条）；prune `keep_days=BOT_EMERGENCY_INFO_KEEP_DAYS` **只裁条目、结构性不碰订阅** | 待审队列与订阅规则都是活动数据：`/bot` 审核面改条目状态、群内「紧急信息 订阅/退订」改规则，禁手工删库；清理先停进程（WAL 伴生 `-wal/-shm`）（WIRE-B1 登记，WIRE-SUB 补订阅表） |
| `data/outbound_gate.sqlite3` | `BOT_OUTBOUND_GATE_DB_PATH` | `domains/transport/sender/outbound_gate.py` | `CREATE TABLE IF NOT EXISTS outbound_gate_sends`（工作区动作发送幂等回执 / `request_digest`） | 出站动作幂等门，**运行中禁碰**；停机后可清（丢短窗去重回执，重放由上游 request_id 幂等兜底） |
| `data/schedules_v21.sqlite3` | `BOT_SCHEDULE_DB_PATH` | `domains/schedule/service/schedule_store.py`（消费方 `schedule_service.py`，经 `bot_schedule_db_path`+`runtime_path` 解析） | `CREATE TABLE IF NOT EXISTS schedule_plans / schedule_occurrences / schedule_send_log / schedule_quiet_exceptions`（`schedule_store.py`，ensure_schema 幂等） | 日程/定时任务台账；plan/occurrence 按业务生命周期更新、send_log 审计留痕；活动调度数据禁整库删 |

## 二、代码内默认路径的库（无独立配置键）

| 库文件 | Owner 模块 | 建表位置 | 清理策略 |
| --- | --- | --- | --- |
| `data/result_unknown.sqlite3`（`__init__.py` `_runtime_scripts_path`） | `domains/ops/monitor/result_unknown.py` | `CREATE TABLE result_unknown` | 未知结果兜底记录，可再生 |
| `runtime_data_dir()/decision_trace.sqlite3`（P-03，无独立配置键；`decision/trace.py` `_resolve_db_path` 惰性解析） | `decision/trace.py`（`SqliteDecisionTraceSink`） | `decision_trace` 表（WAL；批量 ≤64 写入；库内自动滚动保留 5 万条） | 决策引擎影子对照痕迹，诊断用途可再生；保留窗自动滚动，无需手工清 |
| `data/group_files.sqlite3`（`__init__.py` `_runtime_scripts_path`） | `capabilities/group_files.py` | `CREATE TABLE group_files` | 群文件索引可再生，可整库重建 |
| `data/channel_health.sqlite3`（`domains/chat_reply/llm_engine/channel_health.py` `runtime_path`） | `domains/chat_reply/llm_engine/channel_health.py` | `CREATE TABLE channel_health` | 渠道健康探针状态，停机后可清（重启后重新积累） |
| `data/food_images/library.sqlite`（`capabilities/eat.py` `_library_db_path`；落在 Runtime 图库目录 `ChatBot_Runtime\data\food_images\`，非源码树） | `capabilities/eat.py`（eat.py 预热/封面链路） | `CREATE TABLE food_images`（`name` 主键 → `path/source_url/fetched_at`） | 纯 name→path 索引可再生，可整库删（预热脚本重建索引）；图片文件 `<菜名>.<ext>`+`.source.txt` 是事实来源，删索引不删图 |
| `data/media_archive.sqlite3` | `BOT_MEDIA_ARCHIVE_DB_PATH` | `domains/media/archive/media_archive.py`（`MediaArchiveStore`，注册期单例；接线 `capabilities/media_archive.py`） | `CREATE TABLE IF NOT EXISTS media_archive`（domains/media/archive/media_archive.py:134） | 媒体归档索引；文件树 `data/media_archive/`+JSON 旁车为事实来源，索引可按文件树重建；禁整库删文件树 |
| `data/notes.sqlite3`（待生成：生产未重启） | `BOT_NOTES_DB_PATH` | `domains/notes/store/notes_store.py`（`build_notes_store`；消费方 `domains/notes/capabilities/notes.py` + `capabilities/reminder.py` 待办注入） | `CREATE TABLE IF NOT EXISTS notes`（notes_store.py:92，WAL 先于 DDL；单表） | 笔记/待办属用户数据禁整库删；待办随完成/过期按行清理 |
| `data/web_intent_telemetry.sqlite3`（待生成：功能默认关） | `BOT_WEB_INTENT_TELEMETRY_DB_PATH` | `domains/ops/monitor/intent_telemetry.py`（`build_intent_telemetry`，`__init__.py` 装配） | `CREATE TABLE IF NOT EXISTS intent_telemetry`（intent_telemetry.py:76） | 遥测可再生，可整库重建；上限 `bot_web_intent_telemetry_max_items`（默认 10000）自滚动 |
| `data/reactions.sqlite3`（待生成：生产未重启，B 线 2026-09-16） | `BOT_REACTIONS_DB_PATH` | `domains/meme/sources/reaction_store.py`（`ReactionStore`，`__init__.py` 装配单例；emoji_like notice 双写消费） | `CREATE TABLE IF NOT EXISTS reaction_events`（domains/meme/sources/reaction_store.py:_SCHEMA；event_id 幂等合并计数） | 贴纸回应长期记忆与统计；按 `bot_reactions_store_days`（默认 90 天）启动期裁剪；可再生可重建 |
| `data/memory_v21.sqlite3`（V2.1 S8，待生成：零生产接线，装配属后续席位；`character/memory_service.py` `build_memory_service_v21` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `character/memory_store_v21.py`（`MemoryStoreV21`；消费方 `MemoryServiceV21`） | `CREATE TABLE IF NOT EXISTS memory_entries_v21 / memory_tombstones_v21 / memory_identity_bindings_v21 / memory_index_v21` + partial UNIQUE `ux_memory_owner_source_event`（memory_store_v21.py `_SCHEMA_STATEMENTS`，ensure_schema 每连接幂等；WAL+busy_timeout=1000ms） | 记忆行永不 DELETE（status=forgotten+墓碑双记录表遗忘，审计依赖行保留）；墓碑表是重建/恢复不复活的依据，禁清；memory_index_v21 为可再生投影（`rebuild_projection` 重建，可整表清）；绑定表只增不改 |
| `data/teaching_knowledge.sqlite3`（V2.1 S8，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/teaching_service.py` `build_teaching_service` 经 config `bot_teaching_db_path` + `runtime_path` 解析，path_fields 已登记） | `BOT_TEACHING_DB_PATH` | `domains/chat_reply/character/teaching_service.py`（`TeachingService`，本轮测试离线实证；生产消费方待装配席接线） | `CREATE TABLE IF NOT EXISTS teaching_entries`（scope/owner/category/title/content/status/version/supersedes/memory_ref/审计列）+ `teaching_versions`（(entry_id,version) 主键，append-only 版本史：propose/amend/rollback:vN）+ `idx_teaching_topic`（teaching_service.py `_SCHEMA_STATEMENTS`，ensure_schema 幂等；WAL+busy_timeout=1000ms） | 教导条目属审核制用户数据禁整库删（revoke/reject 只改 status 留行留版本史=审计依据）；被拒内容从不入库（红线扫描拒绝于写入前）；注入面=active 且 (shared 或本人 personal)，撤改即时失效 |

| `data/persona_versions.sqlite3`（V2.1 S7 v21r2-V1 席，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/persona_service.py` `build_persona_service` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `domains/chat_reply/character/persona_service.py`（`PersonaService` + `VersionedResourceStore` prefix=persona） | `CREATE TABLE persona_versions`（(resource_id,version) 主键，append-only 不可变：`_no_update`/`_no_delete` 触发器 RAISE(ABORT) 结构性锁死）+ `persona_drafts`（可变工作稿）+ `persona_state`（active 指针+persona_revision）+ `persona_quarantine`（哈希损坏证据，只增不删）（persona_service.py `ensure_schema`，幂等；WAL+busy_timeout=1000ms） | 正式版本与 quarantine 证据属审计依据**禁删**（版本不可变靠触发器，删证据=毁损坏取证）；drafts 可清（丢弃未发布草稿）；`data/` 默认路径经 runtime_paths 重映射 Runtime，不入源码树 |
| `data/worldbook_versions.sqlite3`（V2.1 S7 v21r2-V1 席，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/worldbook_service.py` `build_worldbook_service` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `domains/chat_reply/character/worldbook_service.py`（`WorldbookService`，复用 persona_service `PersonaService` 内核 prefix=worldbook；发布权限 admin+，发布前校验悬空/循环引用+Token 预算） | 同上四表（worldbook_versions/worldbook_drafts/worldbook_state/worldbook_quarantine，worldbook_service.py 经共享 `VersionedResourceStore.ensure_schema` 幂等建表；WAL+busy_timeout=1000ms） | 同 persona_*：正式版本与 quarantine 证据禁删；drafts 可清 |
| `data/control_plane_workspaces.sqlite3`（V2.1 S9 席补登：控制面 Workspace 服务库，路径=config `bot_control_plane_workspaces_db` + `runtime_path` 重映射；表由 `control_plane/workspaces.py` `WorkspaceService.__init__` 幂等建） | `BOT_CONTROL_PLANE_WORKSPACES_DB` | `control_plane/workspaces.py`（`WorkspaceService`；消费方 `control_plane/api/workspaces.py` + `_app.py` lifespan prune） | `CREATE TABLE IF NOT EXISTS cp_workspaces`（id 主键/owner/version/expires_at/data JSON）+ `cp_workspace_audit`（自增 sequence，request_id+operation+version 审计链）+ `cp_workspace_sends`（(workspace_id,idem) 主键幂等回执+request_digest）（workspaces.py:111，executescript 幂等） | 短期隔离工作区（TTL 默认 24h）由 lifespan 每分钟自动 prune，过期即清（含 sends）；工作区内容为临时试验数据可随 TTL 丢弃；audit 链如需长期取证先归档再清 |

## 三、统一清理纪律

1. **默认不动**：SQLite、FAISS/向量索引、聊天记忆、NoneBot data、Cookie、
   订阅状态、媒体缓存、日志、卡片 SVG、Runtime 虚拟环境均为活动数据
   （见工作区 `AGENTS.md`），除非用户明确要求，不删除、不压缩。
2. **可再生白名单**（停机后可删，重启自动重建）：`receipts`、`rate_limit`、
   `event_idempotency`、`diagnostics`、`result_unknown`、`group_files`、
   `channel_health`、`parse_history`、`session_identity`；`audit` 例外——
   先归档到 `ChatBot_Archive` 再清。
3. **迁移备份**：`subscriptions_old.sqlite3` 仅在 V2 订阅链路实测正常后
   归档删除；删除前不得再次触发迁移（会被 refusing overwrite 保护拦下，
   需先移走备份）。
4. **空 db_path = 内存实现**（memory/history/diagnostics/audit/receipts/
   send_queue/rate_limit/event_idempotency）：无文件，无清理语义。
5. 迁移代码本身（`subscription_migration.py`、各模块 `_migrate`/`ALTER TABLE`）
   的修改不在本清单职责内；发现缺陷请登记 issue，勿顺手改。
