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

## 一、配置键指定的库（`plugins/bot_unified_runtime/config.py` 为唯一定义点）

| 库文件（默认路径） | 配置键 | Owner 模块 | 建表 / 迁移位置 | 清理策略 |
| --- | --- | --- | --- | --- |
| `data/knowledge_embeddings.sqlite3` | `BOT_KNOWLEDGE_DB_PATH` | `character/vector_knowledge.py` | `CREATE TABLE knowledge_chunks / knowledge_meta / knowledge_docs`（含列迁移）；伴生 `knowledge_faiss.index` | 活动向量库，禁手工删；重建走人格知识库 sync_chunks 全量重灌 |
| `data/kb_wiki_embeddings.sqlite3` | `BOT_KB_WIKI_DB_PATH` | `character/kb_wiki.py`（复用 `vector_knowledge.SqliteVectorKnowledgeStore`） | 同上；伴生 `kb_wiki_faiss.index` / `kb_wiki_faiss.order.json` | 同上 |
| env 指定（例 `data/wuwa_memory.sqlite3`；空=内存） | `BOT_MEMORY_DB_PATH` | `character/memory.py` | `CREATE TABLE memory_facts`；隔离区见 `security/memory_sanitize.py`（`memory_quarantine`） | 聊天记忆属活动数据禁删；只经 `/bot memory` 指令操作 |
| env 指定（例 `data/wuwa_history.sqlite3`；空=内存） | `BOT_HISTORY_DB_PATH` | `character/history.py` | `CREATE TABLE conversation_turns`；库内 `_prune_scope` 自动滚动保留窗口 | `/bot history clear`；禁手工删整库 |
| env 指定（空=内存） | `BOT_DIAGNOSTICS_DB_PATH` | `diagnostics.py` | `CREATE TABLE runtime_diagnostics`；写入时 `_prune` | 诊断可再生；需合规时先归档再清 |
| env 指定（空=内存） | `BOT_AUDIT_DB_PATH` | `audit/logger.py` | `CREATE TABLE audit_records`；写入时 `_prune` | 审计留痕：归档优于删除 |
| env 指定（空=内存） | `BOT_RECEIPTS_DB_PATH` | `sender/receipts.py` | `CREATE TABLE delivery_receipts` | 发送回执可再生，可整库重建 |
| env 指定（空=内存） | `BOT_SEND_QUEUE_DB_PATH` | `sender/queue.py` | `CREATE TABLE send_requests` | 发送队列持久层，**运行中禁碰**；停机后可清（丢待发消息） |
| env 指定（空=内存） | `BOT_RATE_LIMIT_DB_PATH` | `policy/rate_limit.py` | `CREATE TABLE rate_limit_events` | 限速计数可再生，可整库重建 |
| env 指定（空=内存） | `BOT_EVENT_IDEMPOTENCY_DB_PATH` | `runtime/event_idempotency.py` | `CREATE TABLE event_idempotency` | 幂等去重可再生；清空后短窗内可能重复响应一次 |
| `data/bot_mood.sqlite3` | `BOT_MOOD_DB_PATH` | `character/mood.py` | `CREATE TABLE bot_mood` | 情绪状态可再生 |
| `data/persona_quirks.sqlite3` | `BOT_QUIRKS_DB_PATH` | `character/quirks.py` | `CREATE TABLE persona_quirks` | 怪癖属学习数据，禁随意删 |
| `data/reflection.sqlite3` | `BOT_REFLECTION_DB_PATH` | `character/reflection.py` | `CREATE TABLE reflection_facts / reflection_digests`（含列迁移） | 反思库属学习数据，禁随意删 |
| `data/session_identity.sqlite3` | `BOT_SESSION_IDENTITY_DB_PATH` | `character/session_identity.py` | `CREATE TABLE session_identity`（含列迁移） | 会话身份可再生 |
| `data/addressing_preferences.sqlite3` | `BOT_ADDRESSING_PREFERENCES_DB_PATH` | `character/addressing.py`（`AddressingPreferenceStore`） | `CREATE TABLE addressing_preferences`（主键 `session_type+session_id+sender_id`；WAL） | 用户显式设置的称谓/性别偏好；清理=按行删（清行后回退推断），不整库删 |
| `data/reminders.sqlite3` | `BOT_REMINDER_DB_PATH` | `character/reminders.py` | `CREATE TABLE reminders` | 用户取消提醒即删对应行；不整库删 |
| `data/user_affinity.sqlite3` | `BOT_AFFINITY_DB_PATH` | `character/affinity.py` | `CREATE TABLE user_affinity / group_affinity`（含 `ALTER TABLE` 增列迁移） | 管理员可按 config 注释直接改值；禁整库删 |
| `data/media_registry.sqlite3` | `BOT_MEDIA_REGISTRY_PATH` | `character/media_registry.py` | `CREATE TABLE media_assets`；库内 `_prune_locked` 自动过期 | 自滚动，无需手工清 |
| `data/meme_library.sqlite3` | `BOT_MEME_LIBRARY_DB_PATH` | `sources/meme_library.py` | `CREATE TABLE memes` | 表情库属活动数据；随 `bot_meme_library_dir` 图库配套 |
| `data/music_analytics.sqlite3` | `BOT_MUSIC_ANALYTICS_DB_PATH` | `sources/music_request_store.py` | `CREATE TABLE schema_meta / music_tracks / music_provider_tracks / music_track_aliases / music_request_events / music_chart_snapshots / music_chart_entries`；`schema_meta` 记 schema 版本 | `bot_music_analytics_retention_days`（默认 365）自动滚动 |
| `data/parse_history.sqlite3` | `BOT_PARSE_HISTORY_DB_PATH` | `sources/parse_history.py` | `CREATE TABLE parse_history` | 解析历史可再生，可整库重建 |
| `data/subscriptions.sqlite3` | `BOT_SUBSCRIBE_DB_PATH` | `sources/subscription_store.py`（V1：`subscriptions / cursors / push_log / digest_pending`）→ `sources/subscription_store_v2.py`（V2：`schema_meta` + `subscription_targets / subscription_destinations / subscription_cursors / subscription_seen_items / subscription_outbox / subscription_poll_log / subscription_target_metadata`） | V1→V2 切换由 `sources/subscription_migration.py::prepare_subscription_database` 完成（`schema_meta.version='2'` 判别） | 订阅状态属活动数据禁删；见下方备份行 |
| `data/subscriptions_old.sqlite3`（迁移备份） | — | `sources/subscription_migration.py` | V1 库整体改名备份；已存在时拒绝二次迁移（refusing overwrite） | V2 运行验证无误后可归档/删除 |

## 二、代码内默认路径的库（无独立配置键）

| 库文件 | Owner 模块 | 建表位置 | 清理策略 |
| --- | --- | --- | --- |
| `data/result_unknown.sqlite3`（`__init__.py` `_runtime_scripts_path`） | `runtime/result_unknown.py` | `CREATE TABLE result_unknown` | 未知结果兜底记录，可再生 |
| `data/group_files.sqlite3`（`__init__.py` `_runtime_scripts_path`） | `capabilities/group_files.py` | `CREATE TABLE group_files` | 群文件索引可再生，可整库重建 |
| `data/channel_health.sqlite3`（`llm/channel_health.py` `runtime_path`） | `llm/channel_health.py` | `CREATE TABLE channel_health` | 渠道健康探针状态，停机后可清（重启后重新积累） |
| `data/food_images/library.sqlite`（`capabilities/eat.py` `_library_db_path`；落在 Runtime 图库目录 `ChatBot_Runtime\data\food_images\`，非源码树） | `capabilities/eat.py`（eat.py 预热/封面链路） | `CREATE TABLE food_images`（`name` 主键 → `path/source_url/fetched_at`） | 纯 name→path 索引可再生，可整库删（预热脚本重建索引）；图片文件 `<菜名>.<ext>`+`.source.txt` 是事实来源，删索引不删图 |
| `data/media_archive.sqlite3` | `BOT_MEDIA_ARCHIVE_DB_PATH` | `sources/media_archive.py`（`MediaArchiveStore`，注册期单例；接线 `capabilities/media_archive.py`） | `CREATE TABLE IF NOT EXISTS media_archive`（sources/media_archive.py:134） | 媒体归档索引；文件树 `data/media_archive/`+JSON 旁车为事实来源，索引可按文件树重建；禁整库删文件树 |
| `data/notes.sqlite3`（待生成：生产未重启） | `BOT_NOTES_DB_PATH` | `character/notes_store.py`（`build_notes_store`；消费方 `capabilities/notes.py` + `capabilities/reminder.py` 待办注入） | `CREATE TABLE IF NOT EXISTS notes`（notes_store.py:92，WAL 先于 DDL；单表） | 笔记/待办属用户数据禁整库删；待办随完成/过期按行清理 |
| `data/web_intent_telemetry.sqlite3`（待生成：功能默认关） | `BOT_WEB_INTENT_TELEMETRY_DB_PATH` | `runtime/intent_telemetry.py`（`build_intent_telemetry`，`__init__.py` 装配） | `CREATE TABLE IF NOT EXISTS intent_telemetry`（intent_telemetry.py:76） | 遥测可再生，可整库重建；上限 `bot_web_intent_telemetry_max_items`（默认 10000）自滚动 |

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
