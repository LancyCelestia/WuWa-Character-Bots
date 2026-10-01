# E07 · 无主库登记 + SQLite 并发统一（补丁提案，未落主树）

> 席位：E07。日期 2026-09-30。**状态＝未落地**，原因见 §A（工作区被清空，无文件可改）。
> 本文是可直接粘贴的成品：§B 登记行 + 扩门补丁、§C 并发补丁。所有事实＝从 `HEAD=8ad03e4606bcd332341e6efe0be643fcbad647b2`
> 抽出的 blob 逐行取证（只读命令见 §A.3），非记忆复述。

## A. 事故：工作区 tracked 文件全数缺席（先修这个，E07 才谈得上落地）

1. `C:\...\ChatBot\ChatBot` 现在**只剩空目录骨架**：`find . -type f` = **37 个文件**，其中
   源码树内**零个 `.py`**（`find plugins -name '*.py'` = 0）、`tests/` 零测试件、`AGENTS.md`/`bot.py`/
   `.env`/`docs/HANDBOOK.md`/`docs/db-owners.md`/`scripts/dev.ps1` 全部 MISSING；
   幸存件仅 `docs/config-catalog-full.md`、2 枚 `.superpowers/sdd/*.md`、`data/cards/*.png`、`webui/`。
2. `.git` **不在工作区**（`git status` → not a git repository），仓库元数据被搬到
   `ChatBot/../ChatBot_Runtime/git/`（HEAD/index/objects/refs/worktrees 齐全）。
   `git --git-dir=../ChatBot_Runtime/git ls-files --stage` 与 `ls-tree -r HEAD` **逐项相等**（各 2285 文件，
   blob 哈希零差异）⇒ 本席看不到任何"已暂存的 `__init__.py`/`config.py`"，简报的暂存前提已不成立。
3. 取证命令（全部只读，可复跑）：
   ```bash
   cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
   find . -type f | wc -l                                     # 37
   git --git-dir=../ChatBot_Runtime/git rev-parse HEAD          # 8ad03e4...
   git --git-dir=../ChatBot_Runtime/git diff --name-only HEAD   # 需用户/主会话授权后才跑恢复
   ```
4. 本席 15:2x 与 15:3x **两次复测**（间隔数分钟）`find plugins -name '*.py'` 恒为 0、`.git` 恒无
   ⇒ 不是一次陈旧视图，是常态。同期他席仍在写盘（`patches/W-E05-GATE-GAPS-20260930.md`、
   `data/cards/error_*.png` 四枚新增），说明进程/并发席活着而**源码树空**——它们也没法在真身上落地。
5. **恢复属主会话/用户裁定**，本席不动 git 写操作、不 `restore`/`checkout`：受保护面
   （规则 2/台账 #68★）与"补丁待审不自动部署"常令都压在这一步上。HEAD 完好 ⇒ tracked 件可全量捞回；
   **未提交的 WIP 捞不回**，线索＝`ChatBot_Runtime/git/worktrees/*` 的 30 个 worktree 指针
   （`%TEMP%/M2-01-wt/*`、`%TEMP%/headwt/head`、`WorkBuddy/Worktrees/ChatBot/*` 等，台账 #68 三源复原先例）。
6. 与简报不符的两处（不编造，如实登记）：
   - **`domains/chat_reply/character/person_profile.py` 不在 HEAD**（`ls-tree` 全仓无此件，只有 `persona_profile.py`，
     而后者不碰 sqlite、无 `person_*` 表）。`person_imagery_usage` 同样全仓零命中（仅 `AGENTS.md` 与
     `tests/test_persona_imagery_whitelist.py` 提 imagery）。⇒ 简报第 2 条的"寄生同一路径写 `person_*`"
     若属实，只存在于被清掉的未提交 WIP 里；恢复后须重新现算，本文 §C 改按 **HEAD 实证的寄生者** `MemoryStoreV21` 记账。
   - 行号漂移：`memory.py` 连接真身在 `:319`（非 357），`control_plane/audit.py` 默认库在 `:71`，
     `test_db_owners_coverage.py` 盲区自陈在 `:18-23`（非 42）。`history.py:667` 一字不差。

## B. 批次一 · 无主库登记 + 覆盖门扩面（一批就够，实测净新增红 0）

### B.1 扩门前先把账算清（复算脚本口径）

`test_db_owners_coverage.py` 现口径＝config 字段 `bot_*_db_path`（AST）⇄ 文档 ``BOT_*_DB_PATH``（正则）双向差集。
HEAD 实测：**`_DB_PATH` 族 30 枚，文档登记 30 枚，missing=0 / stale=0（门当前绿）**。
扩到 `_DB` 族后：config 侧 **37** 枚（30 + 7），文档侧仍 31 枚（`BOT_CONTROL_PLANE_WORKSPACES_DB` 已在册，§二 row 74）
⇒ **一次报红 6 枚**（正是四组无主库的控制面那批）：
`BOT_CONTROL_PLANE_ACTIONS_DB` / `..._CONFIG_DB` / `..._EVENTS_DB` / `..._FEATURES_DB` / `..._PLATFORM_DB` / `BOT_VISION_CAPTION_CACHE_DB`。
**不要**扩到 `_PATH` 族：32 枚里多数是目录/JSON（如 `BOT_SCHEDULE_EXCEPTIONS_PATH=data/schedule_exceptions.json`），
扩过去会把非库路径卷进库里；`BOT_MEDIA_REGISTRY_PATH` 已在 §二 登记，走专项注记即可（保持现盲区说法）。
⇒ 结论：**登记 6 行 + 扩门 = 同一批**（台账 #68★"账本行与真身同批"的同一族规），分两批反而必红。

### B.2 `docs/db-owners.md` §一 追加 6 行（`_DB` 命名族，逐字可贴）

| 库文件（默认路径） | 配置键 | Owner 模块 | 建表 / 迁移位置 | 清理策略 |
| --- | --- | --- | --- | --- |
| `data/control_plane_config.sqlite3` | `BOT_CONTROL_PLANE_CONFIG_DB` | `control_plane/config_store.py`（读侧另见 `domains/chat_reply/runtime/settings.py:1611` 取后端库） | `CREATE TABLE IF NOT EXISTS config_instances / config_overrides / config_audit`（config_store.py:153-160）；`connect(path, timeout=5, isolation_level=None)`（:170），**无 WAL** | 控制面配置与变更审计＝取证面，禁整库删；停机后按行清 audit |
| `data/control_plane_events.sqlite3` | `BOT_CONTROL_PLANE_EVENTS_DB` | `control_plane/events.py`（`EventStore`） | `CREATE TABLE IF NOT EXISTS runtime_log_events / runtime_event_watermark`（events.py:246,257）；**WAL**（:244）+ `timeout=1.0`（:267） | 事件流可再生；`max_events` 自滚动，容量告急时先归档再清 |
| `data/control_plane_features.sqlite3` | `BOT_CONTROL_PLANE_FEATURES_DB` | `control_plane/sqlite_features.py`（缺省另有 env 回落 `factory.py:62`） | `CREATE TABLE feature_meta / feature_states / feature_audit`（:119-123）；URI `mode=` 连接（:136），**无 WAL/无显式 timeout** | 特性开关态＋审计；**enabled 变化 ≠ 生产插件已停**（AGENTS 第四部分控制面行）；禁整库删（审计链） |
| `data/control_plane_platform.sqlite3` | `BOT_CONTROL_PLANE_PLATFORM_DB` | `control_plane/platform.py`（`_app.py:512` 空值回落 `:memory:`） | `CREATE TABLE IF NOT EXISTS resources/resource_versions/traces/usage/model_calls/jobs/logs`（:31-43）；`connect(path, check_same_thread=False)`（:22）**无 WAL/无 timeout** | 平台资源与调用台账；`model_calls/usage` 属统计可再生，`resources/versions` 禁删 |
| `data/control_plane_actions.sqlite3` | `BOT_CONTROL_PLANE_ACTIONS_DB` | `control_plane/actions.py` | `CREATE TABLE IF NOT EXISTS cp_action_runs / cp_action_confirmations / cp_action_audit`（:129-139）；`connect(path, timeout=2.0)`（:148）**无 WAL** | 动作执行/确认台账＝同意门留痕，**运行中禁碰**；归档优于删除 |
| `data/vision_caption_cache.sqlite3` | `BOT_VISION_CAPTION_CACHE_DB` | `domains/media/registry/vision_caption_cache.py`（空串＝整件关闭，:340） | `CREATE TABLE ... vision_caption`（:70）；`connect(check_same_thread=False)`（:206）**无 WAL/无 timeout**，`evict_every_writes`+TTL 自滚动 | 图注缓存可再生，停机后可整库重建（丢的只是重算成本） |

### B.3 `docs/db-owners.md` §二 追加 3 行（代码内默认路径，无配置键＝真无主）

| 库文件 | Owner 模块 | 建表位置 | 清理策略 |
| --- | --- | --- | --- |
| `data/llm_billing.sqlite3`（`runtime_path` 派生，**四写方同库不同表，无 `BOT_*_DB` 键**） | 写方 1 `domains/chat_reply/llm_engine/ledger.py:101`（缺省路径）；写方 2 `control_plane/audit.py:71`＋`_app.py:250`；写方 3 `llm_engine/usage_service.py:1064`（预算腿）；写方 4 `llm_engine/billing_service.py:176`（**零接线**，装配席未接） | ledger `llm_call_records / llm_usage_daily / balance_snapshots`（:828,879,895，WAL :670 + timeout 5.0 + 单连接锁）；audit `control_plane_audit`（DDL :195，WAL :185）；usage `budget_accounts / budget_reservations`（:1023,1034，WAL + `busy_timeout=15000` :1065-1066）；billing `billing_attempts / billing_usage_events / billing_settlements / billing_adjustments / billing_prices / budget_envelopes / budget_reservations`（:1093-1181，**无 WAL**） | 计费与授权预算＝活动账务，**禁整库删**（台账 #54 成本口径依赖行）；WAL 不齐（4 家 3 家设、billing 家不设）⇒ 谁先建库谁定 journal 形态，见 §C.3；清理只按 `bot_llm_ledger_retention_*` 类策略按行裁 |
| `data/<表情库目录>/meme_send_history.sqlite3`（**双 owner，路径由 `db_path.parent` 派生，无键**） | `domains/meme/sources/meme_library.py:144`（`MemeSendHistoryStore`）、`:396` 与 `sources/meme_library_listener.py:358`、`sources/shorekeeper_absorb.py:157`（各构造 `MemeQuarantineLedger`）；真身 DDL/类在 `sources/send_history.py:145,422` | `CREATE TABLE meme_sends`（send_history.py:74）、`meme_quarantine`（:83）；三处 `connect(timeout=15)`（meme_library.py:111 / send_history.py:181,434），**全无 WAL**，各持自己的 `threading.Lock` | 反重复账本：`retention_days`/window 自滚动；**墓碑（quarantine）是"降权后不复活"的依据，禁清**；缺它＝同贴库并发双发（S-RANDPIC-LEDGER2 实测过，tests/test_randpic_no_repeat_ledger.py E 组） |
| `data/control_plane_events_v21.sqlite3`（`ops/monitor/event_service.py:644` 缺省，**无键、本轮不接线**） | `domains/ops/monitor/event_service.py::build_event_service` → `domains/ops/monitor/event_store.py::EventStore`（:473） | `event_store.py:504-508`：`connect(timeout=1.0)` + `PRAGMA journal_mode=WAL` + `busy_timeout=1000` + foreign_keys（§7 契约，单写执行器） | 运行事件 v21 流，诊断用途可再生；保留窗自滚动。**建议**：补 `bot_control_plane_events_v21_db` 键升为 §一 一族（源码 `event_service.py:639` 自己就这么写的），但键属 `config.py`＝本席禁写面，见 §C.4 补丁提案 |

> 登记面口径补一句（同批写进文档头，免得下位席误读）：本门覆盖 `BOT_*_DB_PATH` + `BOT_*_DB` 两族；
> `_PATH` 族与代码内默认路径库不在差集内，仍靠本文件 §二 人工登记＋评审。

### B.4 `tests/test_db_owners_coverage.py` 扩门补丁（四处，逐字替换）

1. 常量区（现 `:40` 附近）：
   ```python
   # pydantic 字段名（小写）；以 `_db_path` 或 `_db` 结尾者即声明了一个库文件
   # （2026-09-30 E07：控制面六枚 `bot_control_plane_*_db` 与 `bot_vision_caption_cache_db`
   #  原落在门外＝本门自陈盲区，现已收编）。
   _DB_FIELD_SUFFIXES = ("_db_path", "_db")
   _DOC_DB_KEY_RE = re.compile(r"\bBOT_[A-Z0-9_]+_(?:DB_PATH|DB)\b")
   ```
2. `_config_db_field_names()` 末行改为：
   `return {n.upper() for n in fields if n.endswith(_DB_FIELD_SUFFIXES)}`
3. 主断言 docstring 的"新增一个 `bot_*_db_path` 字段"改述为"新增一个 `bot_*_db`(_path) 字段"，
   并删掉模块 docstring `:18-23` 里"`*_db` 结尾的键不在本差集内"那句——**盲区已闭，留着就是假话**；
   替换为 §B.3 末句的两族口径 + "仍盲区：`_PATH` 族与无键库"。
4. 地板值：`test_db_owners_truth_sources_nonempty` 的 `>=25` 改 `>=35`（实测 37/37；
   地板按现算复录、容差一字不动＝台账 #68★）。
5. 变异测试三腿不动（`_diff` 语义未变即仍有效）。

**预期门禁**：`pytest tests/test_db_owners_coverage.py tests/test_doc_link_integrity.py -q` 全绿；
文档里新增的 `.sqlite3` 反引号名不触发链接门（`test_doc_link_integrity.py:171` `_DB_NAME_RE` 放行 sqlite3/json 等产物名）。

## C. 批次二 · SQLite 并发并形制（参照 affinity，形制＝单写者 + WAL + timeout）

`affinity.py` 基准形制（HEAD 实证，简报给的 1953/2086 属算法段，真身在）：
`self._lock = threading.Lock()`（:1482）＋进程内单连接 `sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)`（:1610-1612）
＋ `PRAGMA journal_mode=WAL`（:1542）＋ 三表一锁、写入方唯一。**注意**：affinity 没有后台写线程，
它的"单一写线程"就是调用线程在 `self._lock` 下串行——本席按这一形制统一，不新造线程模型（避免第二条时间线）。

### C.1 `character/memory.py`（本席独占，可直改）

真问题（HEAD 实证）：同一 `data/*.sqlite3`（`bot_memory_db_path`）上坐着**两把互不相识的锁**——
- 旧腿 `SQLiteMemoryRepository._connect()`（:319）＝每次新建连接、**无 WAL、无显式 timeout、无锁**，写 `memory_facts`（INSERT :112 / DELETE :234 / ALTER-if-missing :301-302）；
- 新腿 `memory_bus_v2.build_memory_bus`（:1881）→ `shared_bus_store(db_path)`（:786，`_BUS_STORE_LOCK` :701）→ `MemoryStoreV21`
  （`memory_store_v21.py:188-191`：`RLock` + 单连接 `check_same_thread=False` + **WAL + `busy_timeout=1000`**），表集 `memory_entries_v21` 等。
⇒ 两腿共用一把文件锁的语义**没有**：一边 WAL+1s busy、一边裸连默认 5s busy + 各自 ALTER，
`_ensure_schema` 并发跑时 `PRAGMA table_info`→`ALTER` 是经典 TOCTOU（第二个连接报 duplicate column / database is locked）。
补丁（三处，最小面，不新建模块）：
```python
# _connect(): 与 MemoryStoreV21 对齐（同库两腿同一 journal 形态 + 同一 busy 窗）
connection = sqlite3.connect(self.db_path, timeout=1.0)   # 与 busy_timeout=1000ms 同值
connection.row_factory = sqlite3.Row
# _ensure_schema(): WAL 先行、失败降级不致命（ledger.py:670 / affinity.py:1542 先例）
with self._connect() as connection:
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=1000")
    except sqlite3.Error:
        pass          # 网络盘等不支持 WAL 时降级默认 journal，不致命
    connection.execute("""CREATE TABLE IF NOT EXISTS memory_facts ...""")
```
再加**进程内 per-path 建库锁**（一把模块级 `_MEMORY_SCHEMA_LOCK = threading.Lock()`，只包住 `_ensure_schema`）
⇒ 与 V21 腿的 `RLock` 仍不相识，但"同进程内 ALTER 竞态"这一维被关掉；跨进程的写串行只能靠 WAL + busy_timeout（这是 SQLite 的正解，不是 Python 锁）。
**不做**：不引入后台写线程、不改调用面、不迁数据文件（规则 2）。

### C.2 `character/history.py`（**非本席文件 ⇒ 提案，等授权转派或主会话落**）

`history.py:667` 与 memory.py 同形（裸 `sqlite3.connect(self.db_path)`、无 WAL、无 timeout），
而它同时被三个只读客打开：`character/shared_group.py:403`、`character/shared_export.py:193`、
`runtime/participant_memory.py:392`（另 `character/reflection.py:1261`、`control_plane/webui_memory_graph.py:532`）。
写方无 WAL ⇒ 读侧在写事务期间必取 `SQLITE_BUSY`，而读客各持自己的 timeout 甚至不设 URI `mode=ro`。
同一补丁片段（WAL + timeout）套 `history.py::_connect/_ensure_schema` 即可；三个只读客**不改**（读侧无写风险，
database_broker 的 `mode=ro` 形制已在 `ledger.aggregate_channel_usage` 先例里，别拉进来）。

### C.3 同库异 journal 的通则（写进 `db-owners.md` §三）

`data/llm_billing.sqlite3` 四写方中三家设 WAL、`billing_service.py` 不设 ⇒ journal 形态由**先建库者**决定，
`mode=ro`/裸连都跟着文件头走。§三 加第 6 条：「同库多写方必须同批设 `journal_mode=WAL` + 同值 `busy_timeout`；
缺一家即按最弱那家计时——登记时逐家点名（谁没设）」。

### C.4 配置键提案（`config.py`＝本席禁写面 ⇒ 只提案）

- 建议新增 `bot_llm_billing_db_path: str = "data/llm_billing.sqlite3"`，把 `ledger.resolve_default_db_path()`
  与 `audit.resolve_default_ledger_db_path()` 两处硬缺省收成一个键（现在两处各写一遍字面量＝两份真身，
  改路径要同时改两件文件，正是本次无主库的成因）。落地须**三面齐**（config 字段 + `settings.py` 热改登记 +
  `.env.example`，台账 #68★），并把 §B.3 首行的"无键"改为该键名——**同一批**。
- 建议新增 `bot_control_plane_events_v21_db`（源码 `event_service.py:639` 自己提请的）。
- 键一旦加，§一 行数与 `_DB_PATH` 族计数同步进 `db-owners.md`（门自动盯，不手写计数＝规则 10）。

### C.5 TDD 计划（先红后绿；恢复工作树后跑）

新文件 `tests/test_sqlite_concurrency_dbowners.py`（离线 tmp_path，无外网）：
1. 登记腿（**红**在扩门前，随 §B 同批转绿）：断言 `_config_db_field_names()` 覆盖 `_DB` 族、且六枚键逐一在文档出现；
   注毒自证各一枚（文档删一行 ⇒ 必红；config 假字段 ⇒ 必红）。
2. `test_memory_repo_uses_wal_and_busy_timeout`：tmp_path 建库后 `PRAGMA journal_mode` 读回 `'wal'`、
   `PRAGMA busy_timeout` 读回 `1000` ⇒ **当前必红**（memory.py 不设）。
3. `test_memory_two_legs_share_one_journal_form`：`SQLiteMemoryRepository` 与 `shared_bus_store(同一路径)`
   先后建库，断言两侧 `journal_mode` 读数一致（现形制下先建者赢、后建者被裸连拖回 delete journal 的窗口要能被抓到）。
4. `test_memory_alter_race_is_serialized`：两线程并发 `_ensure_schema()`（第二线程先删列名缓存），
   断言无 `duplicate column`/`database is locked` ⇒ 现形制红。
5. 红线锁：断言 `database_broker._FORBIDDEN_SQL_RE` 仍含 `attach|detach`（防后人"顺手"放开）。

## D. 红线遵守

- `domains/chat_reply/runtime/database_broker.py:11`（文档）、`:63`（黑名单正则含 `attach|detach|pragma|vacuum|reindex`）、
  `:147`（拒绝消息）**一字未动、不放开**；本提案也不在它上面动刀。
- 零数据文件触碰：全程只读 git 对象与源码 blob；未打开/未写 `ChatBot_Runtime/` 下任何 sqlite/faiss/venv；
  迁移类脚本一律不产（未 DRY-RUN 的必要——本席没做任何迁移）。
- 未做 git 写操作、未改 `.env`/`.env.example`/`config.py`/`__init__.py`、未重启进程、未派子代理、未删移既有文件。
- 唯一新增件＝本文（`patches/` 新文件，简报授权通道）。

## E. 顺带登记不修 → 交 E09

1. **全仓零 VACUUM / auto_vacuum**：`grep -rn -i vacuum plugins/ scripts/ tests/` 只命中
   `database_broker.py:64` 的**黑名单词**与 `tests/test_prepared_adapter_canary.py:783` 的门 ⇒ 没有任何回收路径。
   后果：各库按行 prune 后文件体积只增不减（WAL 合并只回滚日志、不缩主文件）。
2. `character/reflection.py`：`reflection_facts`（:281）/`reflection_digests`（:302）**零 DELETE**（文件内无 `DELETE FROM`）＝无界增长；
   有 WAL（:278），无 prune。
3. `character/affinity.py`：`user_affinity` / `group_affinity` 无行数上限、无过期行清理（`affinity_delta_log` 另有滚动口径，见 §54）。
4. `person_imagery_usage`＝**HEAD 全仓零命中**（见 §A.6），E09 若要给它加上限，需先确认它在哪个未提交 WIP/席位里。
5. `meme_send_history.sqlite3` 的 `meme_quarantine` 按设计"只增不删"（墓碑），体积增长与图库规模同阶——不是 bug，是取证面；E09 别当无界垃圾清。
