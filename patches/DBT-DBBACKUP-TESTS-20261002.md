# DBT — db_backup 测试件重写工单（2026-10-02 下午窗）

## 一、背景与范围

- 接手阵亡席 X1c 半成品 `.superpowers/sdd/2026-10-02-fixwave/half-done/test_db_backup.py.HALF-WRITTEN`（mtime Oct 2 01:56，早于 15:30 红线；**未移未删**）。死因＝`class TestHonestyAndFail Loud:` 断行语法错 + import 仍是旧家 `plugins.bot_unified_runtime.runtime`。
- 生产件 `plugins/bot_unified_runtime/domains/ops/db_backup.py` 本日已从 runtime/ 挪家（`parents[4]` 同步）。**本席未改生产件一行**；接线面 `domains/ops/admin/runtime_admin.py:244` 确认指向新家。
- 写前 mtime 自检：`tests/test_db_backup.py` 当时不存在的 ⇒ 新建。独占写面＝该测试件 + 本工单，零 git 写、零进程动作、零配置改。

## 二、抢救/重写判定（半成品逐腿）

| 半成品腿 | 判定 |
|---|---|
| `test_uncheckpointed_wal_rows_reach_the_copy` | **重写**（原稿缠死在 `_runtime_from`/`if False` 脚手架里；判据升级为「副本 ≥ 裸拷 且 ==3 / 裸拷 ==2」） |
| `test_backup_one_actually_calls_the_connection_backup_api` | **重写**。原稿全模块禁集含 `replace`/`copy2`——会误伤合法行为：运行日志轮转的 `Path.replace`（重命名非内容拷）与 restore_stage 的 `shutil.copy2`（口径 3：staging 合法）。收窄为**函数域** AST（backup_one 内禁裸拷形态 + 禁 `read_bytes`） |
| `test_poisoned_pattern_is_still_caught` | **抢救**（合成反例喂尺，改为喂共用尺 `_raw_copy_hits`） |
| `test_naive_now_is_rejected` / `test_unknown_timezone_still_records_an_offset` | **抢救重写**（naive 拒收＝②腿注毒；tz 降级不 naive＝②腿正向） |
| manifest 字段腿（`test_manifest_fields_and_offset_aware_timestamps`） | **重写并入腿②**（+08:00/480 硬断言，本机 tzdata 实测可用） |
| `test_verify_catches_bit_rot` | **抢救**＝②腿注毒自证（bit-flip ⇒ sha256 必红） |
| verify 其余（missing/truncated/row-drift）、`test_plan_restore_never_writes_anything` | **未抢救**（超出本席六腿范围；verify 已由 sha256 注毒腿守） |
| TestRetention 五腿 | **重写并入腿⑤**（keep_last 上界改用「sweep 期 64 → 现算期改 1」避免 backup_all 自动剪枝吃掉 victim；traversal 注毒腿近乎原样抢救） |
| `test_every_source_open_is_read_only`（connect spy） | **未抢救**（monkeypatch 面大；由「源文件字节/journal_mode/行数不变」+「ro 连接写拒」两腿等效覆盖） |
| `test_source_files_unchanged_after_sweep` / `test_write_attempt_on_ro_connection_fails` | **抢救重写**（URI 统一 `as_uri()`，原稿 f-string 拼盘符路径在 Windows 上脆） |
| TestWiring 命令面五腿（status/run/verify 回文、`_BACKUP_WRITE_ACTIONS` 门、usage 行） | **未抢救**（本席腿⑥只管 import 指向与防回潮；命令面行为腿留接线席） |
| `TestHonestyAndFailLoud`（空壳，语法错死点） | 无可抢 |

## 三、六腿实现与判据（`tests/test_db_backup.py`，28 枚）

1. **①命名消毒**：`_safe_stem` 去后缀/畸形字符全消毒且消毒后词干能拼回在册形态、空回落 `db`；`_copy_name` UTC 14 位戳 + `sha256(rel)[:8]` tag；`COPY_NAME_RE` 反向拒 12/13 位戳、非 hex tag、错后缀；+08:00 输入归一成 00:00Z 落名（台账 #6★）。
2. **②产物与 manifest**：tmp 库产出副本+成对 manifest；sha256/size/行数/integrity/`copy_is_single_file` 全对账；`created_at_utc`=+00:00、`created_at_local`=+08:00/480；UTC 策略=0 偏移；tz 不认识仍带偏移；naive 时刻抛；超上界 skip 零产物。
3. **③撕裂防护**：WAL 源未 checkpoint 行进副本（==3）而裸拷拿不全（==2），判据「副本 ≥ 裸拷」成立；静态尺（函数域）backup_one 必走 `Connection.backup`、零裸拷/`read_bytes` 形态；apply_retention 函数域零批量删。
4. **④落点人质**：`_reject_production_target` 对数据根本体/内部、仓库根本体/`data/`/任意子路径全抛；tmp 放行；`restore_stage` 公开面同尺且拒在写盘前；抢救腿：备份落点配进仓库内 `resolve_backup_root` 当场抛。
5. **⑤保留删**：先清单（零副作用）后点名；批准名单逐枚命中，删副本连带旁车；陌生文件/子目录/越界/绝对路径/未点名在册名全拒且零误伤；空名单零删；AST 尺：全模块零 rmtree/move 调用、unlink 只点名、删前 `COPY_NAME_RE.match(name)` 在场。
6. **⑥接线 AST**：`_handle_backup_command` 内 ImportFrom 必须指向 `plugins.bot_unified_runtime.domains.ops`；旧家形态（`runtime import db_backup` / `runtime.db_backup`）在**生产面**（plugins/scripts/bot.py）零命中——`.superpowers`/`docs` 是非代码档案（X1c 遗骸合法含旧 import）不在扫面，已注明。

## 四、注毒自证（实跑）

- **常驻注毒腿**：②bit-flip（sha256 必红）、②naive 时刻（必抛）、③假 `backup_one` 含 `shutil.copy2`（尺必咬）、⑤未点名/越界名单（全拒）、⑥合成旧 import（扫尺必咬）。
- **dev 临时改错判据跑红再还原**（两腿均按令执行）：
  - 腿② `offset_minutes == 480 → 481`：`2 failed in 4.97s`（含腿⑤同批毒）→ 还原。
  - 腿⑤ `deleted == 2 → 0`：同上批红 → 还原。
- 还原后复跑：`28 passed`。

## 五、验收实测（末行原文）

- 执行通道披露：系统 python 3.12.10 缺 nonebot（收集期即 ImportError），**装包被禁** ⇒ pytest/ruff 均经 `ChatBot_Runtime/venv/Scripts/` 只读执行（零写入：pytest 带全卫生前缀 + `--basetemp=$TEMP/qoder-DBT/bt`，ruff 带 `--no-cache`），与 dev.ps1 同源。
- `pytest tests/test_db_backup.py -q` → **`28 passed in 4.09s`**
- `pytest tests/test_db_backup.py --collect-only -q` → **`28 tests collected in 2.37s`**（0 errors）
- `ruff check tests/test_db_backup.py --no-cache` → **`All checks passed!`**（0.16.4）
- 源码树卫生：`tests/__pycache__` 零新增；`data/` 零出现。
- 观察到 tests/ 下他席在飞脏 WIP（render_hashes×2、config_key_registration_ledger、db_owners_coverage、doc_link_integrity 等）——**本席未触碰**，bot 未重启（台账 #10：生效待重启）。
- 生产件发现：无需改码项。唯一备注＝docstring 含 `rmtree` 字样（自述"不会有"），静态尺必须按 AST 调用面判、不能按全文 text-scan 判——X1c 的全模块文本尺正是会死在这里。
