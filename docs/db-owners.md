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
| `data/addressing_preferences.sqlite3` | `BOT_ADDRESSING_PREFERENCES_DB_PATH` | `domains/chat_reply/character/addressing.py`（`AddressingPreferenceStore`） | `CREATE TABLE addressing_preferences`（主键 `session_type+session_id+sender_id`；WAL；2026-10-03 §76 `ALTER`-if-missing 增两列 `intimate_pin_tier`／`intimate_explicit_at`＝"本人显式开过亲密档"的标记与墙钟时刻，**判据不住本库**（住 `runtime/content_route.py`），本库只当带时间戳的格子；群侧钉不入库） | 用户显式设置的称谓/性别偏好＋本人显式开档标记；清理=按行删（清行后回退推断与"没显式开过"），不整库删 |
| `data/reminders.sqlite3` | `BOT_REMINDER_DB_PATH` | `character/reminders.py` | `CREATE TABLE reminders` | 用户取消提醒即删对应行；不整库删 |
| `data/user_affinity.sqlite3` | `BOT_AFFINITY_DB_PATH` | `character/affinity.py` | `CREATE TABLE user_affinity / group_affinity`（含 `ALTER TABLE` 增列迁移；G-11 批新增 `impression_tag_times` JSON 列：标签→最近打标时间，印象标签淡出判据） | 管理员可按 config 注释直接改值；禁整库删 |
| `data/reply_policy.sqlite3` | `BOT_REPLY_POLICY_DB_PATH` | `domains/chat_reply/character/reply_policy.py` | `CREATE TABLE IF NOT EXISTS user_reply_policy`（`reply_policy.py:_SCHEMA_STATEMENTS`；per-sender 永久性回复策略：长度档 + 内容指令 + 来源/证据/时间戳。同库另有 `person_imagery_usage`＝按人意象族用量账，详见本清单 §二 同路径行） | 用户本人一句明示即覆盖旧值（含反悔回长文）；清空即回到全局档，**不做批量删除**（策略是用户的长期偏好，非缓存） |
| `data/media_registry.sqlite3` | `BOT_MEDIA_REGISTRY_PATH` | `domains/media/registry/media_registry.py` | `CREATE TABLE media_assets`；库内 `_prune_locked` 自动过期 | 自滚动，无需手工清 |
| `data/vision_caption_cache.sqlite3` | `BOT_VISION_CAPTION_CACHE_DB` | `domains/media/registry/vision_caption_cache.py` | `CREATE TABLE vision_caption`（主键 `sha256`＝图片**内容**摘要，走中央 `domains/media/digest.py`；列 `caption/model/created_at/hits`） | 纯缓存，可整库删（删了只是重新问一次模型）；`BOT_VISION_CAPTION_CACHE_TTL_SECONDS`（默认 24h）自滚动：读时过期即删、写侧每 32 次整体清理 |
| `data/meme_library.sqlite3` | `BOT_MEME_LIBRARY_DB_PATH` | `domains/meme/sources/meme_library.py` | `CREATE TABLE memes` | 表情库属活动数据；随 `bot_meme_library_dir` 图库配套 |
| `data/music_analytics.sqlite3` | `BOT_MUSIC_ANALYTICS_DB_PATH` | `domains/music/data/music_request_store.py` | `CREATE TABLE schema_meta / music_tracks / music_provider_tracks / music_track_aliases / music_request_events / music_chart_snapshots / music_chart_entries`；`schema_meta` 记 schema 版本 | `bot_music_analytics_retention_days`（默认 365）自动滚动 |
| `data/parse_history.sqlite3` | `BOT_PARSE_HISTORY_DB_PATH` | `domains/link_parse/support/parse_history.py` | `CREATE TABLE parse_history` | 解析历史可再生，可整库重建 |
| `data/subscriptions.sqlite3` | `BOT_SUBSCRIBE_DB_PATH` | `domains/subscribe/store/subscription_store.py`（V1：`subscriptions / cursors / push_log / digest_pending`）→ `domains/subscribe/store/subscription_store_v2.py`（V2：`schema_meta` + `subscription_targets / subscription_destinations / subscription_cursors / subscription_seen_items / subscription_outbox / subscription_poll_log / subscription_target_metadata`） | V1→V2 切换由 `domains/subscribe/store/subscription_migration.py::prepare_subscription_database` 完成（`schema_meta.version='2'` 判别） | 订阅状态属活动数据禁删；见下方备份行 |
| `data/subscriptions_old.sqlite3`（迁移备份） | — | `domains/subscribe/store/subscription_migration.py` | V1 库整体改名备份；已存在时拒绝二次迁移（refusing overwrite） | V2 运行验证无误后可归档/删除 |
| `data/campus.sqlite3` | `BOT_CAMPUS_DB_PATH` | `domains/assistant/campus/campus_store.py`（`CampusStore`；旧路径 `sources/campus_store.py` 已退役删除） | `CREATE TABLE IF NOT EXISTS campus_messages`（`message_id` 主键幂等 / `date_key` 索引） | 校园群消息转发去重台账；`date_key` 按保留窗自动 prune（天数以配置真身现算为准）；活动幂等去重数据，禁手工删整库（AGENTS #33） |
| `data/emergency_info.sqlite3` | `BOT_EMERGENCY_INFO_DB_PATH` | `domains/emergency_info/sources/store.py`（`EmergencyStore`/`build_emergency_store`） | `CREATE TABLE`（唯一 `_SCHEMA`，两表：`emergency_items` 含 `(source_id, external_id)` UNIQUE 与 `status` CHECK、`latitude/longitude` 列走 ALTER-if-missing 自动迁移；`emergency_subscriptions` 含 `target_scope` CHECK 与 `target_key` 主键=一群/一人一条）；prune `keep_days=BOT_EMERGENCY_INFO_KEEP_DAYS` **只裁条目、结构性不碰订阅** | 待审队列与订阅规则都是活动数据：`/bot` 审核面改条目状态、群内「紧急信息 订阅/退订」改规则，禁手工删库；清理先停进程（WAL 伴生 `-wal/-shm`）（WIRE-B1 登记，WIRE-SUB 补订阅表） |
| `data/outbound_gate.sqlite3` | `BOT_OUTBOUND_GATE_DB_PATH` | `domains/transport/sender/outbound_gate.py` | `CREATE TABLE IF NOT EXISTS outbound_gate_sends`（工作区动作发送幂等回执 / `request_digest`） | 出站动作幂等门，**运行中禁碰**；停机后可清（丢短窗去重回执，重放由上游 request_id 幂等兜底） |
| `data/schedules_v21.sqlite3` | `BOT_SCHEDULE_DB_PATH` | `domains/schedule/service/schedule_store.py`（消费方 `schedule_service.py`，经 `bot_schedule_db_path`+`runtime_path` 解析） | `CREATE TABLE IF NOT EXISTS schedule_plans / schedule_occurrences / schedule_send_log / schedule_quiet_exceptions`（`schedule_store.py`，ensure_schema 幂等） | 日程/定时任务台账；plan/occurrence 按业务生命周期更新、send_log 审计留痕；活动调度数据禁整库删 |
| `data/reply_policy.sqlite3`（生产已生成，2026-09-28 起在册） | `BOT_REPLY_POLICY_DB_PATH` | `domains/chat_reply/character/reply_policy.py`（`ReplyPolicyStore`；装配口 `shared_reply_policy_store(config)`，总开关 `BOT_REPLY_POLICY_ENABLED`） | `CREATE TABLE IF NOT EXISTS user_reply_policy` + `person_imagery_usage`（前者：主键 `person_key`＝「人」而非会话，键一律经 `domains/core/session_keys` 构造；`length_mode / content_directives / note / source / evidence / updated_at`，后三列走 ALTER-if-missing 迁移。后者＝意象族用量账，`PRIMARY KEY (person_key, family)`、只存最近一次用时，供「换意象」按人轮换避重；同库同连接同锁，**不新增库路径键**。均单连接 + 锁 + WAL） | 用户明示即覆盖同一行（反悔走同一条写腿），撤销＝按行删，且**同键的意象用量行一起清**（留旧账＝下次设上接着轮换，撤得不干净）；`evidence` 是不可信文本，入库前已过 `security/injection.py::neutralize_internal_markers` 与 `render/plain_text.py::redact_local_secrets` 两道咽喉（禁第二份消毒器）；永久性用户策略属活动数据，禁手工删整库，清理先停进程（WAL 伴生 `-wal/-shm`）；意象名册不住本库（住 `personas/<人格档>/imagery_families.txt`，跟人格走） |
| `data/control_plane_config.sqlite3`（X2 波补登：控制面配置态库，`_db` 族） | `BOT_CONTROL_PLANE_CONFIG_DB` | `control_plane/config_store.py`（`SQLiteConfigStateStore`） | `CREATE TABLE config_instances / config_overrides / config_audit`（config_store.py） | 控制面平台管理库（受 `bot_control_plane_enabled` 门，缺省关，与生产插件启停无关，见 AGENTS 控制面行）；盘上活跃即平台曾开；随平台生命周期治理 |
| `data/control_plane_features.sqlite3`（X2 波补登） | `BOT_CONTROL_PLANE_FEATURES_DB` | `control_plane/sqlite_features.py`（`SQLiteFeatureStateStore`） | `CREATE TABLE feature_meta / feature_states / feature_audit`（sqlite_features.py） | 同上；特性开关状态库。**enabled 值变化 ≠ 生产插件已停用**，勿据本库存在性反推生产态 |
| `data/control_plane_actions.sqlite3`（X2 波补登） | `BOT_CONTROL_PLANE_ACTIONS_DB` | `control_plane/actions.py`（`ControlActionService`；消费口 `control_plane/_app.py`） | `CREATE TABLE cp_action_runs / cp_action_confirmations / cp_action_audit`（actions.py） | 工作区动作执行审计链，归档优于删除；清理先停进程（伴生文件） |
| `data/control_plane_platform.sqlite3`（X2 波补登：特性关时盘上无文件） | `BOT_CONTROL_PLANE_PLATFORM_DB` | `control_plane/platform.py`（`PlatformStore`） | `CREATE TABLE resources / resource_versions / traces / usage / model_calls / jobs / logs`（platform.py） | 平台资源与用量台账；`check_same_thread=False` 长连接，未激活不落盘 |
| `data/control_plane_events.sqlite3`（X2 波补登：特性关时盘上无文件） | `BOT_CONTROL_PLANE_EVENTS_DB` | `control_plane/events.py`（`RuntimeEventService`，表 `runtime_log_events`） | `CREATE TABLE runtime_log_events / runtime_event_watermark`（events.py，WAL 先于 DDL） | 运行事件日志，与「事件」语义另两库并存属已知分裂（见 `docs/design/audit-20260920-unify-U13-db.md` D1-归属分裂-2），收口归控制面席 |


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
| `data/reactions.sqlite3`（待生成：生产未重启，B 线 2026-09-16） | `BOT_REACTIONS_DB_PATH` | `domains/meme/sources/reaction_store.py`（`ReactionStore`，`__init__.py` 装配单例；emoji_like notice 双写消费） | `CREATE TABLE IF NOT EXISTS reaction_events`（domains/meme/sources/reaction_store.py:_SCHEMA；event_id 幂等合并计数） | 贴纸回应长期记忆与统计；按 `bot_reactions_store_days`（缺省天数以该键真身现算为准）启动期裁剪；可再生可重建 |
| `data/memory_v21.sqlite3`（V2.1 S8，待生成：零生产接线，装配属后续席位；`character/memory_service.py` `build_memory_service_v21` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `character/memory_store_v21.py`（`MemoryStoreV21`；消费方 `MemoryServiceV21`） | `CREATE TABLE IF NOT EXISTS memory_entries_v21 / memory_tombstones_v21 / memory_identity_bindings_v21 / memory_index_v21` + partial UNIQUE `ux_memory_owner_source_event`（memory_store_v21.py `_SCHEMA_STATEMENTS`，ensure_schema 每连接幂等；WAL+busy_timeout 以建表真身现算为准） | 记忆行永不 DELETE（status=forgotten+墓碑双记录表遗忘，审计依赖行保留）；墓碑表是重建/恢复不复活的依据，禁清；memory_index_v21 为可再生投影（`rebuild_projection` 重建，可整表清）；绑定表只增不改 |
| `data/teaching_knowledge.sqlite3`（V2.1 S8，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/teaching_service.py` `build_teaching_service` 经 config `bot_teaching_db_path` + `runtime_path` 解析，path_fields 已登记） | `BOT_TEACHING_DB_PATH` | `domains/chat_reply/character/teaching_service.py`（`TeachingService`，本轮测试离线实证；生产消费方待装配席接线） | `CREATE TABLE IF NOT EXISTS teaching_entries`（scope/owner/category/title/content/status/version/supersedes/memory_ref/审计列）+ `teaching_versions`（(entry_id,version) 主键，append-only 版本史：propose/amend/rollback:vN）+ `idx_teaching_topic`（teaching_service.py `_SCHEMA_STATEMENTS`，ensure_schema 幂等；WAL+busy_timeout 以建表真身现算为准） | 教导条目属审核制用户数据禁整库删（revoke/reject 只改 status 留行留版本史=审计依据）；被拒内容从不入库（红线扫描拒绝于写入前）；注入面=active 且 (shared 或本人 personal)，撤改即时失效 |

| `data/persona_versions.sqlite3`（V2.1 S7 v21r2-V1 席，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/persona_service.py` `build_persona_service` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `domains/chat_reply/character/persona_service.py`（`PersonaService` + `VersionedResourceStore` prefix=persona） | `CREATE TABLE persona_versions`（(resource_id,version) 主键，append-only 不可变：`_no_update`/`_no_delete` 触发器 RAISE(ABORT) 结构性锁死）+ `persona_drafts`（可变工作稿）+ `persona_state`（active 指针+persona_revision）+ `persona_quarantine`（哈希损坏证据，只增不删）（persona_service.py `ensure_schema`，幂等；WAL+busy_timeout 以建表真身现算为准） | 正式版本与 quarantine 证据属审计依据**禁删**（版本不可变靠触发器，删证据=毁损坏取证）；drafts 可清（丢弃未发布草稿）；`data/` 默认路径经 runtime_paths 重映射 Runtime，不入源码树 |
| `data/worldbook_versions.sqlite3`（V2.1 S7 v21r2-V1 席，待生成：零生产接线，装配属后续席位；`domains/chat_reply/character/worldbook_service.py` `build_worldbook_service` 经 `runtime_path` 解析，暂无独立配置键） | （无；装配席位登记） | `domains/chat_reply/character/worldbook_service.py`（`WorldbookService`，复用 persona_service `PersonaService` 内核 prefix=worldbook；发布权限 admin+，发布前校验悬空/循环引用+Token 预算） | 同上四表（worldbook_versions/worldbook_drafts/worldbook_state/worldbook_quarantine，worldbook_service.py 经共享 `VersionedResourceStore.ensure_schema` 幂等建表；WAL+busy_timeout 以建表真身现算为准） | 同 persona_*：正式版本与 quarantine 证据禁删；drafts 可清 |
| `data/control_plane_workspaces.sqlite3`（V2.1 S9 席补登：控制面 Workspace 服务库，路径=config `bot_control_plane_workspaces_db` + `runtime_path` 重映射；表由 `control_plane/workspaces.py` `WorkspaceService.__init__` 幂等建） | `BOT_CONTROL_PLANE_WORKSPACES_DB` | `control_plane/workspaces.py`（`WorkspaceService`；消费方 `control_plane/api/workspaces.py` + `_app.py` lifespan prune） | `CREATE TABLE IF NOT EXISTS cp_workspaces`（id 主键/owner/version/expires_at/data JSON）+ `cp_workspace_audit`（自增 sequence，request_id+operation+version 审计链）+ `cp_workspace_sends`（(workspace_id,idem) 主键幂等回执+request_digest）（workspaces.py:111，executescript 幂等） | 短期隔离工作区（TTL 默认 24h）由 lifespan 每分钟自动 prune，过期即清（含 sends）；工作区内容为临时试验数据可随 TTL 丢弃；audit 链如需长期取证先归档再清 |

## 三、代码硬编码路径 / 外部框架 / 孤儿库（X2-DB-OWNERS-COVERAGE 波普查补登）

> 本节库**无 config `_db`/`_db_path` 字段**（尺①②的"声明点"看不见），靠本波盘上只读普查逐个认主。
> 覆盖门对"新增硬编码库"不设自动腿的原因见 `tests/test_db_owners_coverage.py` 模块 docstring 残余盲区段。

| 库文件 | 路径来源 | Owner 模块 | 建表位置 | 清理策略 / 判定 |
| --- | --- | --- | --- | --- |
| `data/llm_billing.sqlite3`（盘上活跃；总开关 `BOT_LLM_BILLING_ENABLED` 为 bool，**非路径键**） | `runtime_path("data/llm_billing.sqlite3")`（ledger.py:121 / audit.py:71 各硬解析） | **双 co-owner（共库不同表）**：`domains/chat_reply/llm_engine/ledger.py`（`LedgerService`）+ `control_plane/audit.py`（`ControlPlaneAuditStore`） | ledger：`llm_call_records / llm_usage_daily / balance_snapshots`；audit：`control_plane_audit`。WAL 先行、进程内单连接+锁（台账 #54：成本走微元、取整只在聚合） | 计费/审计属留痕数据，归档优于删除；两模块同库不同表，收口单一 owner 见设计审计 §6 建议（加 config 键＝越界，进 patch 提案） |
| `data/meme_send_history.sqlite3`（无独立键：随表情库目录派生 `<BOT_MEME_LIBRARY_DB_PATH 目录>/meme_send_history.sqlite3`） | `meme_library.py:267/916`、`meme_library_listener.py:361` 用 `db_path.parent / "meme_send_history.sqlite3"` | `domains/meme/sources/send_history.py`（`MemeSendHistoryStore` + `MemeQuarantineLedger`；由 `meme_library.py` 惰性构造） | `CREATE TABLE meme_sends / meme_quarantine`（send_history.py:74/83） | 表情发送史与隔离台账；随表情库目录一并治理（AGENTS #72：册基与贴纸池两键两片目录，勿混用）；盘上活跃 |
| `data/control_plane_events_v21.sqlite3`（无键：`ops/monitor/event_service.py:644` 硬编码 `runtime_path`；本轮不接线，盘上无文件） | `runtime_path("data/control_plane_events_v21.sqlite3")`（event_service.py:644） | `domains/ops/monitor/event_store.py`（表 `runtime_events_v21` + 旧 `runtime_events_v1`），消费方 `EventService` | `CREATE TABLE runtime_events_v21`（+ 多索引，event_store.py:415）；WAL+busy_timeout 由装配口 | 运行事件 v21；与 `control_plane_events`（BH5）概念重叠属已知分裂（设计审计 D1-归属分裂-2）；加 config 键＝越界，进 patch 提案 |
| `data/modality_preprocess.sqlite3`（无键：源件注释明写"不碰 config.py"，自建自管；盘上暂无文件） | `domains/vision/capabilities/modality_preprocessing.py:555` `sqlite3.connect(db_path)`（`db_path` 由调用方注入，缺省落 Runtime data 根） | `domains/vision/capabilities/modality_preprocessing.py`（`ModalityPreprocessJobStore`） | `CREATE TABLE IF NOT EXISTS modality_preprocess_jobs`（+ `idx ... (session_key, updated_at)`） | 多模态预处理作业队列表；可再生作业台账；本波普查认主，未自动门覆盖 |

### 外部框架库（第三方插件自建，bot 代码零 writer）

| 库文件 | Owner | 判定 |
| --- | --- | --- |
| `data/nonebot_orm.sqlite3`、`data/nonebot_plugin_orm/db.sqlite3` | 第三方依赖 `nonebot-plugin-orm`（见 `pyproject.toml` 依赖声明，**非 bot 数据层**） | `.env` 的 `SQLALCHEMY_DATABASE_URL` 指向 Postgres，但插件 bootstrap 仍落本地 sqlite 兜底文件。登记为止血"盘上无主没人认"；清理按 NoneBot 插件规程，bot 侧无 owner 可指 |

### 孤儿 / 僵尸空库（无任何代码 writer）

| 库文件 | 判定 |
| --- | --- |
| `data/_diag_debug.sqlite3`（20480B，mtime 停 2026-08-24） | 全树零引用（AST 字符串常量扫描亦无命中），无 writer、无 config 键、无 owner；历史调试落盘残留 |
| `data/audit.sqlite3`、`data/diagnostics.sqlite3`、`data/receipts.sqlite3`（均 0 字节，mtime 停 09-08/08-24） | 对应 config 键（`BOT_AUDIT_DB_PATH` 等）**在册**，但现行生产数据已落 `wuwa_audit` / `wuwa_diagnostics` / `wuwa_receipts`（活跃）；这三个 default-named 空库系历史 `.env` 旧命名残留，非双写、零写入 |

> **孤儿处置**：以上"无 writer"库按 §五.3 可再生/停机清理，删 `.sqlite3` 必连带同目录 `-wal`/`-shm`；**是否清理归用户**，本清单只认主与记账，不代删（AGENTS 铁律 2）。



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
