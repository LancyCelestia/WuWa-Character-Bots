# 席 Q1 工单：出站队列每次 `submit` 的全表扫（P5.9，2026-10-02）

席位：Q1 ｜ 需求书：`.superpowers/sdd/2026-10-02-fixwave/SEATS.md` §9 ｜ 基线 HEAD `5d581b2`
独占面：`plugins/bot_unified_runtime/domains/transport/sender/queue.py` ＋ 新建锁件 ＋ 本工单
零 git 写、零配置改（`config.py` 未动，**本席无 CONFIG 需求**）、零进程动作、零外发。
生产库只按 `mode=ro` 打开，实验一律在**仓外副本**上做（`sqlite3` 在线备份 API，非裸 copy——WAL 下裸拷会拿到撕裂副本）。
注入登记：本席**未**遇到伪装指令载荷。工具结果/他席文件正文一律当数据；本席关键读数全部先落
`%TEMP%\qoder-Q1\out\*.txt` 再 `Read` 回看，未采信任何回显（复跑命令见 §3 末）。

> **撤案判据未触发**：全表扫**是真的**，已用生产只读副本 `EXPLAIN QUERY PLAN` 证明（§1）。故不撤案。
> 但工单不把改后形态写成 `SEARCH`——SQLite 对无谓词的有序读一律叫 `SCAN`。真实的胜负手是
> `USE TEMP B-TREE FOR ORDER BY` 消失 ＋ 读的对象从**表 B 树**换成**覆盖索引**，见 §3 并排读数。

---

## ① 现状核实（file:line ＝本席开工时读数，行号会漂，认符号名）

描述给的 `queue.py:2464` **当轮就是准的**：`git show HEAD:…queue.py` 第 2464 行正是那条
`DELETE FROM send_requests`。全条语句＝ HEAD `2462-2479`。

| 面 | 真身 | 实况（改前） |
|---|---|---|
| 热路径 | `submit()` → `queue.py:646` `self._prune(connection)` | `_prune` **只此一个调用点**（全文件 grep `_prune` 除定义外仅 646 行命中）⇒ 每次**成功插入**的 submit 都跑一遍剪枝，非惰性清扫 |
| 全表扫本体 | HEAD `queue.py:2462-2479`（现 `queue.py:2504-2521`）留存腿 | `dedupe_key NOT IN (SELECT dedupe_key FROM send_requests ORDER BY created_at DESC, rowid DESC LIMIT ?)`。`created_at` 上**无索引**（`sqlite_master` 实测名册见下）⇒ 子查询＝整表读 ＋ 整表排序 |
| 生产 schema 真身 | 只读普查 `ChatBot_Runtime/data/wuwa_send_queue.sqlite3` | 索引六枚：`idx_send_requests_{session_state, request_id, state_due, processing_lease}`、`idx_send_request_parts_{request, identity}` ＋ 两枚 autoindex。**没有任何一列以 `created_at` 打头** |
| 生产 operating point | 同上，只读 | `send_requests = 1000` 行（`max_items=1000`＝`config.bot_send_queue_max_items` 缺省，`queue.py:2751` 读入）＝表被容量门**钉死在 cap**；state 分布 `sent 977 / failed_final 23`，非终态 0 行。⇒ 每次 submit 剪枝**一行都不必删**，纯付扫描＋排序的钱 |
| 库体积 | `page_count=1182 × page_size=4096` ＋ WAL 1.8M | 4.83 MB（描述说「5564K→已 4.7M 级」，量级一致） |
| 外层 DELETE | 同条语句 | 本来就 `SEARCH ... USING INDEX idx_send_requests_processing_lease (state=?)`——**全表扫不在外层，在 keeper 子查询里**。这点必须说清，否则会把「改前 SCAN→改后 SEARCH」误读成外层变了 |
| 第二枚 O(N) 腿 | `queue.py:2486-2488` `_warn_if_over_soft_ceiling` 的 `SELECT COUNT(*)` | 也是线性（`SCAN ... USING COVERING INDEX idx_send_requests_request_id`）。实测 **6.4 µs**（§3-E），比留存腿低三个数量级 ⇒ **判为不动**，只登记 |

### 三条受保护语义的现有执法点（改前先找齐，改后逐条复跑）

| 语义 | 执法点（file:line，HEAD 读数） | 本席是否碰 |
|---|---|---|
| **part 级幂等** | `queue.py:174` `_part_key()`（稳定键＝请求身份＋part_index＋行身份摘要，重试不换键）；`:1497` `ON CONFLICT(part_key) DO NOTHING`；`:1544-1598` payload_digest 守卫 → `:124 PartLedgerConflictError`；`:2228` `dedupe_key TEXT PRIMARY KEY` ＋ `:621` `ON CONFLICT(dedupe_key) DO NOTHING`（submit 去重腿，`:602-604` 注释明写「去重与写入必须原子」） | **否**（submit 的 INSERT 语句一字未动，见 §2 末「未动清单」） |
| **UNKNOWN 确认态** | `queue.py:42` `PART_STATE_UNKNOWN`；`:1689` `mark_part_attempt` 落 unknown；`:1775` 续发臂把 PENDING/UNKNOWN 并列为可推进；`:262` `indexes_in_state(PART_STATE_UNKNOWN)`（确认器读侧）；`:2332/:2338` part 检索索引 | **否** |
| **PARTIAL 断点续发** | `queue.py:38` `PARTIAL_ROW_STATE`；`:65` `_PARTIAL_RESUME_BACKOFF_SECONDS=90`；`claim_due` 的 `:764-830` partial 续发臂；`:1932` `mark_partial`；**`_prune` 顶部 `:2433-2461` 休眠 PARTIAL→FAILED_FINAL 清扫腿（Q-G7 ③）** | 只动它**下面**那条留存 DELETE；清扫腿原样保留 |
| 台账 #46★（幂等键段禁 `:`） | `domains/emergency_info/service/dedupe.py:94` `is_legal_segment`；队列侧对应物＝ `queue.py:169-171` `_part_identity_token()`（sha256[:16] 摘要段，注释明写「冒号/井号皆有可能，故不裸拼原文」） | **否**——本席改动不构造任何键段 |

---

## ② 改法与理由（只有两把，全在「索引 / 查询形态」授权面内）

### 改动 1：`_ensure_schema` 建一枚 `created_at` 索引（`queue.py:2375-2380`）

```sql
CREATE INDEX IF NOT EXISTS idx_send_requests_created_at ON send_requests (created_at)
```

🔴 **键序必须是裸单列 ASC，不许「顺手」改成 DESC**——这是本席实测踩出来的，不是推理：
索引叶子键恒为 `(created_at, rowid ASC)`，**倒着走**恰好等于语句要的 `created_at DESC, rowid DESC`；
写成 `(created_at DESC)` 时叶子变成 `(created_at DESC, rowid ASC)`，正走倒走都对不上那枚 `rowid DESC`，
优化器退回 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`（四形对照读数在 `%TEMP%\qoder-Q1\out\index_forms.txt`：
A `(created_at DESC)`＝留尾巴 / B `(created_at)`＝零尾巴 / C `(created_at DESC, _rowid_ DESC)`＝
`OperationalError: no such column: _rowid_` / D `(created_at, rowid)`＝`no such column: rowid`，
**SQLite 拒绝把 rowid 写成索引列**，所以「显式双列」这条直觉路也走不通）。
锁件 `test_index_is_single_column_ascending` 钉住这条，注释也写在正身旁边。

`CREATE INDEX IF NOT EXISTS` 是 `_ensure_schema` 里既有的六枚索引的同一写法，不开新通路。

### 改动 2：`_prune` 留存腿的反连接键 `dedupe_key` → `rowid`（`queue.py:2504-2521`）

```sql
DELETE FROM send_requests
WHERE state IN (?, ?, ?)
  AND rowid NOT IN (
    SELECT rowid FROM send_requests
    ORDER BY created_at DESC, rowid DESC LIMIT ?
  )
```

为什么不能只建索引（跨腿实测 §3-C）：只建索引 ⇒ 子查询虽免了排序，仍要**逐行回表**取
`dedupe_key` 原文（plan 少一个 `COVERING`），3.021 ms；换成 `rowid` 后索引叶子自带 rowid ⇒
覆盖读，0.290 ms。两半各付一份钱，缺一半只拿到一半。

顺带堵掉的坑（**如实登记为行为差异，不是「语义一字不变」的一部分**）：SQLite 的
`TEXT PRIMARY KEY` **不隐含 NOT NULL**（本席实跑：`INSERT … VALUES (NULL,…)` 成功入库）。
旧形态一旦有 NULL 主键行落进 keeper 集，`NOT IN` 对**整个集合**判 NULL ⇒ 剪枝静默变成
「一行都不删」且不报错。对照实验：同样数据、cap=2，最新行 `dedupe_key=NULL` 时
**旧形态删除 0 行、无 NULL 时删 4 行；新形态两种情况都正常剪**。
现网 `SELECT COUNT(*) … WHERE dedupe_key IS NULL` **＝ 0**（只读实测），
所以这一腿在现网**无现值差异**，它买的是「以后也不许退回那个形状」，锁件
`test_prune_still_prunes_when_a_null_dedupe_key_row_is_the_newest`（该腿在 HEAD 代码上**必红**，见 §3-B）。

### 等价性（不靠「看起来一样」签字）
`(created_at, rowid)` 因 `rowid` 唯一而**全序**，故「按该序取前 N 行」的行集与取键方式无关；
`dedupe_key` 是主键 ⇒ `row ↔ dedupe_key` 双射，两个反连接判据圈出同一批行。
生产副本上 cap = 0/1/10/500/999/1000/1500/100000 **八档逐档比删除集，全等**（§3-D）。

### 未动清单（本席授权面自查）
`submit()` 的 INSERT 与 `ON CONFLICT(dedupe_key) DO NOTHING`／`claim_due` 全部认领臂／
`mark_sent`·`mark_retryable_failure`·`mark_final_failure`·`mark_partial`／`mark_part_attempt` 与
digest 守卫／`_part_key`·`_part_identity_token`（键段构造）／休眠 PARTIAL 清扫腿／
`_warn_if_over_soft_ceiling` 阈值判据——**一字未动**。`worker.py` 未打开（席 X5 独占）。
`git diff --stat` 只有 `queue.py | 39 insertions(+), 2 deletions(-)` 一枚 tracked 件。

---

## ③ 判据读数（全部原样贴，复跑命令在 §3-F）

### A. 改前 SCAN / 改后 SEARCH 并排（同一份生产只读副本，同一 cap=1000）

**改前**（HEAD schema ＋ HEAD 语句）：
```
SEARCH send_requests USING INDEX idx_send_requests_processing_lease (state=?)   <- 外层，本来就是 SEARCH
LIST SUBQUERY 1
SCAN send_requests                                                             <- 全表扫（本体）
USE TEMP B-TREE FOR ORDER BY                                                   <- 整表排序
```
**改后**（工作树 `_ensure_schema` ＋ 工作树 `_prune`）：
```
SEARCH send_requests USING COVERING INDEX idx_send_requests_processing_lease (state=?)
LIST SUBQUERY 1
SCAN send_requests USING COVERING INDEX idx_send_requests_created_at            <- 有序索引游标，被 LIMIT 截断
CREATE BLOOM FILTER
```
`USE TEMP B-TREE FOR ORDER BY` **消失**、表 B 树**不再被读**（`COVERING INDEX`）。
词面上 SQLite 仍叫它 `SCAN`——无谓词的有序读它只会叫 SCAN，本工单不把它写成 `SEARCH` 凑格式。
keeper 子查询单独看（改后）：`SCAN send_requests USING COVERING INDEX idx_send_requests_created_at`，一行尾巴都没有。

### B. 双向自测：注毒腿必须红（HEAD 树 `git archive` 到仓外，只把新锁件放进去）

`PYTHONDONTWRITEBYTECODE=1 … pytest tests/test_queue_prune_index_lock.py` 在未改代码的 HEAD 树上：
```
4 failed, 7 passed in 6.74s
FAILED ::test_prune_read_walks_the_created_at_index_without_sorting
FAILED ::test_poison_shape_reverts_to_table_key_probe
FAILED ::test_index_is_single_column_ascending
FAILED ::test_prune_still_prunes_when_a_null_dedupe_key_row_is_the_newest
    E  AssertionError: NULL 主键行使剪枝静默停摆（旧形态的坑）
    E  assert 9 < 9
```
⇒ 四把尺**量得到东西**（起点值 ≠ 本轮值）。剩下 7 把在 HEAD 树就绿＝它们锁的是既有语义，
不是为本改动定制的橡皮章。工作树上同文件 **`11 passed in 4.47s`**。
注毒腿另有两枚在文件内自证：`test_poison_plan_regresses_when_the_index_is_dropped`
（拔索引⇒必现 `TEMP B-TREE`，补回⇒必转绿）、`test_poison_shape_reverts_to_table_key_probe`
（换回 `dedupe_key`⇒必丢 `COVERING`）。

### C. 语句级耗时（生产只读副本，1000 行＝cap，best/mean of 300，BEGIN…ROLLBACK 包裹）

| 腿 | plan | best | mean |
|---|---|---|---|
| HEAD 语句 ＋ HEAD schema（**改前**） | SCAN 表 ＋ TEMP B-TREE | 6.437 ms | **8.308 ms** |
| HEAD 语句 ＋ 新索引（只建索引） | SCAN USING INDEX（回表） | — | 3.021 ms |
| 新语句 ＋ **无**索引（只改形态） | SCAN 表 ＋ TEMP B-TREE | — | 4.559 ms |
| 新语句 ＋ 新索引（**改后**） | SCAN USING **COVERING** INDEX，无排序 | 0.263 ms | **0.290 ms** |

**语句级 8.308 → 0.290 ms＝28.7×**（且那一轮 `deleted=0`：钱全花在「确认无需删除」上）。
两轮独立复跑给 22.8×（4.849→0.212）与 28.7×，绝对值随机器负载浮动，倍率一致。

### D. 端到端真 `submit()`（生产形状副本，pinned at cap，40 次/轮）
```
BEFORE: HEAD stmt, no index      -> 11.320 ms/submit
PARTIAL: HEAD stmt, index present->  8.460 ms/submit
AFTER : new stmt, index present  ->  4.164 ms/submit
net submit() cost change: 11.320 -> 4.164 ms/submit (2.7x)
```
端到端倍率（2.7×）远低于语句级（28.7×）是**真的**：`submit()` 其余成本（`request_json` 序列化、
WAL fsync、审计腿）不归本席管。写侧新增代价＝每枚新行多写一条索引记录，已被这组端到端数字吃进。

### E. 新索引会不会打坏别的语句？（13 枚语句形状全量对拍）
把真队列跑一轮完整工作流（submit×18 / list_due / claim_due / mark_part_attempt / mark_sent /
mark_retryable_failure / mark_final_failure / mark_partial / safe_summary / find_request），
用 trace 捞出 **13 个去遮蔽后的语句形状**，同一份数据、两枚库（有/无新索引）逐形状比 plan：
```
index presence check -- with-db=1 without-db=0
changed = 2 / 13 shapes ; untouched = 11
```
变的两枚：① 留存腿本体（目标改动）；② `SELECT COUNT(*) FROM send_requests` 从
`COVERING INDEX idx_send_requests_request_id` 换成 `COVERING INDEX idx_send_requests_created_at`。
②是**平调不是退化**：实测 6.431 µs → 7.424 µs（＋1.0 µs，均值）。换来留存腿省 8.0 ms，
本席判为值得，如实登记。**`claim_due` 的三臂认领、part 检索、session 互斥共 11 形状 plan 未变。**

### F. 三条受保护语义的既有锁：改后复跑（同前缀，实跑末行原样）
```
tests/test_queue_prune_index_lock.py tests/test_part_idempotent_resume.py
tests/test_queue_dormant_partial_final.py tests/test_queue_sendq_f3f4.py
tests/test_queue_poison_row.py tests/test_queue_shared_key_fanout_fix.py
tests/test_auditfix_sender_queue.py tests/test_result_unknown.py
tests/test_policy_queue_not_drop.py tests/test_a20_sender_session_order.py
tests/test_soak_growth.py tests/test_startup_queue_warning.py
tests/test_receipt_sibling_enum_rg1.py tests/test_progress_ack_no_double_send.py
-> 121 passed in 18.51s
```
关键三枚点名：`test_part_idempotent_resume.py::test_unknown_without_confirmer_never_blind_resent`、
`::test_restart_resume_never_resends_delivered_parts`、
`test_queue_dormant_partial_final.py::test_legacy_dormant_rows_swept_to_terminal_by_prune`
（这枚直接打在 `_prune` 里那条我没动的清扫腿上）。
**起点读数（改动前、同一把尺先跑的 11 文件子集，不含新锁件与后两枚点名文件）**＝`100 passed in 15.40s`。两组集合不同（上表 14 文件＝那 11 枚 ＋ `test_receipt_sibling_enum_rg1.py` ＋ `test_progress_ack_no_double_send.py` ＋ 新锁件），所以 121 − 100 ＝ 21 ＝ 新锁件 11 ＋ 后两文件 10，**不是**「同一集合从 100 涨到 121」；起点值 ≠ 本轮值这条成立，但按上表那组 14 文件的改前读数本席未单独跑过，如实标注。

复跑命令（席位卫生前缀一字不改；`<py>`＝`ChatBot_Runtime/venv/Scripts/python.exe`）：
```
mkdir -p "$TEMP/qoder-Q1/bt"
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <py> -m pytest -p no:cacheprovider \
  --basetemp="$TEMP/qoder-Q1/bt" -q tests/test_queue_prune_index_lock.py \
  tests/test_part_idempotent_resume.py tests/test_queue_dormant_partial_final.py \
  tests/test_queue_sendq_f3f4.py tests/test_result_unknown.py tests/test_soak_growth.py
```
实验脚本（仓外，未入库）：`%TEMP%\qoder-Q1\{probe_eqp,probe_ddl,probe_ab,probe_real,probe_plan_diff2,probe_forms}.py`，
读数 `%TEMP%\qoder-Q1\out\*.txt`。注毒腿的 HEAD 对照树＝`git archive HEAD` 抽到
`%TEMP%\qoder-Q1\head_tree`，只把新锁件复制进去。

---

## ④ 净新增红 A/B（只签本席域，不签全绿）

同一条尺（24 个既有出站/队列/收件/告警面文件），HEAD 树 vs 工作树，按 node ID 分桶；工作树那一跑额外带上本席新锁件，所以枚数是 24 文件 / 25 文件之比：

| 树 | 收集 | 结果 |
|---|---|---|
| HEAD（`git archive` 到仓外，**不含**新锁件） | 564 | `1 failed, 562 passed, 1 xfailed in 109.51s` |
| 工作树（含新锁件 11 枚） | 575 | `574 passed, 1 xfailed in 137.70s` |

575 − 564 ＝ 11 ＝ 新锁件枚数（逐档核过 `--collect-only` 读数 564，不是猜的）。
HEAD 那枚红 `tests/test_outbound_v21.py::TestImportProbe::test_module_importable_in_subprocess`
＝ `FileNotFoundError: c:\program files\python312\python.exe`（本机没有该硬编码解释器路径），
属**既存环境红、与本席域无关**，工作树本轮恰好没撞上。
⇒ **本波域净新增红 0**（不是「全绿」；#72★ 口径）。

三门读数（一律走 `scripts/dev.ps1`）：

| 门 | 结果 | 归属 |
|---|---|---|
| lint | FAIL，53 红，**点名 16 个文件里 0 个是本席面**；`ruff check --no-cache tests/test_queue_prune_index_lock.py plugins/…/queue.py` → `All checks passed!` | 他席在飞件（`quirks.py`/`db_backup.py`/`fx_data.py`/`write_trace.py`/`test_error_copy_pool_gate.py` …）。本席新件初版带 4 枚 `UP031`，已改掉并复跑 |
| typecheck | FAIL 于 `chat_reply/character/quirks.py:474: error: Expected 'except' or 'finally' block [syntax]`（他席 WIP，mypy 遇语法错**整轮中止**，压根没轮到本席文件） | 本席单独验：`git archive HEAD` 抽仓外树、只覆盖本席 `queue.py`、跑与 dev.ps1 同参的 mypy → **`Success: no issues found in 606 source files`**，exit 0 |
| runtime-layout | FAIL：`source workspace contains 2 Python cache path(s)` | 两枚皆 `plugins/bot_unified_runtime/runtime/__pycache__{,/*.pyc}`，属**席 X1b（§3 db_backup）**件，mtime 01:20:21＋源件 01:29:44 仍在被写；本席全程带 `PYTHONDONTWRITEBYTECODE=1`，`find` 复核本席面零缓存件。**非本席红，按规则不代删**（只列清单交主会话） |

---

## ⑤ 未尽事项与原因

1. **改动未生效，等重启**（台账 #10★）。索引由 `_ensure_schema` 在首次 submit/list_due 时
   `CREATE INDEX IF NOT EXISTS` 自动补，**无需手工 DDL**；生产库 4.8 MB，建索引毫秒级，
   但会在启动了 bot 之后第一次队列操作里持写锁——由用户执行或明示授权，本席未动进程。
   验证入口（bot 在线后，只读）：`SELECT sql FROM sqlite_master WHERE name='idx_send_requests_created_at'`
   应非空；`EXPLAIN QUERY PLAN` 打留存腿应无 `USE TEMP B-TREE`。
2. **`SELECT COUNT(*)` 那枚线性腿没动**。实测 6.4 µs，比留存腿低三个数量级，改动它要牺牲告警里的
   真实行数（`_warn_if_over_soft_ceiling` 把 `total` 打进日志）。判为「测过、不值当」，不是漏了。
   若主会话要收，形态是 `SELECT 1 … LIMIT 1 OFFSET (8*max_items)`（实测 0.008 ms），
   代价是告警改口成「≥8×cap」而不是报准数——那是**语义变更**，得单独裁。
3. **`ANALYZE` / `PRAGMA optimize` 的 plan 稳定性没测**。生产库当前**无** `sqlite_stat1`
   （只读普查的 `sqlite_master` 名册里没有），本席所有 plan 读数都是无统计信息下的默认判据。
   将来谁上 `ANALYZE`，§3-A/E 的读数要重录一次（本席不动库的统计面，也不在只读副本以外跑 `ANALYZE`）。
4. **`rowid` 依赖**：新形态假定 `send_requests` 是 rowid 表（它现在是，`SELECT rowid` 实测可用）。
   若将来改成 `WITHOUT ROWID`（例如嫌 6 枚索引太胖），`rowid` 会直接 `no such column` 报错——
   属**响亮失败**不是静默错删，本席判为可接受；锁件
   `test_prune_keeps_exactly_the_newest_window_with_created_at_ties` 也会同批红。
5. **写放大没做长期观察**：每枚新行多写一条索引项。§3-D 的端到端数字已含此代价（净减 7.2 ms/submit）。
   队列在 cap=1000 稳态，索引不随历史增长，无无界面。
6. **无 CONFIG 需求**：`bot_send_queue_max_items`（`queue.py:2751` 读入，缺省 1000）已够用，
   本席不需要新键，故未写 `Q1-CONFIG-REQUEST.md`。cap=1000 这个数是否合理属**阈值判断**，
   本席不造数：现网 cap 恰好等于行数（表被钉死），说明剪枝**在正常工作**、非「超限 8×」告警态。
7. **跨席卫生上报（非本席红、本席未处置）**：`plugins/bot_unified_runtime/runtime/__pycache__`
   正把 `runtime-layout` 门打成 FAIL（席 X1b 的 `db_backup.py` 字节码件）。请主会话或该席自清。
   另建议转给席 R1（§15 扩扫面那席）：`runtime_layout_smoke.py:118` 只报
   `contains {len(bytecode)} Python cache path(s)`——**只报数不报路径**，本席是靠自写 `find` 探针
   才认出归属他人的，否则只能盲猜或越界乱删。这条属于 R1 的独占面，本席不动那个文件。
   同批给 R1 补一枚现算证据：本席扫出仓库内 basetemp 残迹 `cb-w9chk/`（46 枚
   `test_*0/` 目录、内含 `*.sqlite3`，mtime 2026-09-30 17:54，**早于本席开工数日、非本席产物**；
   已被 `.gitignore:73` 那条「pytest sandbox basetemp」罩住 ⇒ `git status` 永远看不见，
   `runtime-layout` 现值也没把它算进那 2 枚里）。这正是 §15 需求书点名要扩的那一类。
   本席只登记、不删（规则：不删不移非本席产物）。

### 交付物
| 件 | 状态 |
|---|---|
| `plugins/bot_unified_runtime/domains/transport/sender/queue.py` | 改：`+39 / −2`（`_ensure_schema` 建索引、`_prune` 留存腿换 rowid，两处都带判据注释） |
| `tests/test_queue_prune_index_lock.py` | 新建：11 枚＝1 现状核实 ＋ 1 读侧形态 ＋ 2 注毒自证 ＋ 1 索引键序 ＋ 5 语义等价与保护 ＋ 1 总量（枚数＝实跑 `11 passed`）。语句文本从**执行轨迹**捞（`set_trace_callback`），不在测试里抄第二份字面量 |
| `patches/Q1-QUEUE-SUBMIT-SCAN-20261002.md` | 本件 |
| `worker.py` / `sender/*` / `config.py` | **未碰** |
