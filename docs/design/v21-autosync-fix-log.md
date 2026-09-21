# V2.1 autosync 门禁冲突修复日志（A3 席，2026-09-17）

合同依据：`docs/design/backend-v2-implementation-guide.md` §13——`scripts/dev.ps1::Invoke-Test`
强制 `BOT_AUTOSYNC=1`，外层设 0 被覆盖，conftest 因此自动 `--write`（含
`tests/render_hashes.json`），把真实回归「洗绿」。裁定：显式关闭必须被尊重。

## 阶段 0：取证

- `git diff scripts/dev.ps1`：工作树已有未提交修复（HEAD `ccd38b9` 版为无条件
  `$env:BOT_AUTOSYNC = "1"`；工作树改为 `if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = "1" }`，
  带注释说明 V2.1 §13 裁定）。判定：修复半成品——无回归测试、无日志、判定逻辑未抽纯函数。
- `tests/conftest.py`（工作树与 HEAD 一致，无 diff）：`run_autosync` 内联
  `if os.environ.get("BOT_AUTOSYNC") != "1": return []`——行为上任何非 "1" 值
  （含 0/false/no/off 全部大小写变体）均跳过，与规格相容但判定不可测、
  与 dev.ps1 未对齐成语义契约。
- 生成器联动唯一自动调用点 = `conftest.run_autosync`（command_catalog/doc_sync/
  verify_hashes 三处 `--write`）；`dev.ps1 -Task sync` 为人工显式任务，不受此门约束。
- `tests/test_autosync_gate.py`、本日志文件此前不存在。

## 阶段 1：RED（失败测试先行）

新增 `tests/test_autosync_gate.py`（全离线，tmp_path 隔离，fake subprocess，禁真实写哈希）：

1. `test_is_autosync_enabled_matrix`（15 参数）：纯函数判定矩阵——"1"→True；
   未设置/0/false/FALSE/False/no/No/OFF/off/空串/true/yes/2/" 1"→False。
2. `test_run_autosync_disabled_never_invokes_generators`（7 参数）：禁用时零
   subprocess 调用，三处 `--write` 全跳过。
3. `test_run_autosync_enabled_invokes_all_write_steps`：启用时三步 `--write`
   齐发（现状回归锁）。
4. `test_run_autosync_enabled_reports_hash_baseline_change`：哈希基线重录留痕
   warning 路径（现状回归锁）。
5. `test_dev_ps1_source_contract`：dev.ps1 必须含守卫行、不得含无条件覆盖行。
6. `test_dev_ps1_guard_respects_explicit_env`（5 参数）：从 dev.ps1 正则钉出守卫行
   真身，powershell 子进程执行：未设置→1；0/false/OFF/1 原样透传。

调试修正（测试自身 bug）：fake subprocess 命名空间补 `SubprocessError`
（run_autosync 的 except 元组引用它）；fake 写清单前 mkdir 父目录。

RED 实跑（命令：`BOT_AUTOSYNC=0 ... venv python -m pytest tests/test_autosync_gate.py
-p no:cacheprovider --basetemp=$TEMP/v21-autosync -q`）：

```
15 failed, 21 passed in 1.22s
FAILED（15×）test_is_autosync_enabled_matrix[*] —
  AttributeError: module '_conftest_autosync_under_test' has no attribute 'is_autosync_enabled'
```

21 passed = 行为锁定项全绿：证明 dev.ps1 工作树修复与 conftest 现状行为
已与规格一致（实现只需补纯函数本身，字节级兼容有测试背书）。

## 阶段 2：实现（最小改动）

- `tests/conftest.py`：新增纯函数 `is_autosync_enabled(raw: str | None) -> bool`
  （仅 `"1"` → True，其余一律 False，与历史 `!= "1"` 字节级兼容，docstring 记录
  V2.1 §13 显式 0/false/no/off 禁用语义）；`run_autosync` 入口改用该函数。
  两次编辑各自保持文件可导入（并行 pytest 安全）。dev.ps1 工作树守卫已存在，
  本席未再改动（其行为由新测试钉死）。
- `scripts/dev.ps1`：无新增改动（工作树既有守卫 `if (-not (Test-Path env:BOT_AUTOSYNC))
  { $env:BOT_AUTOSYNC = "1" }` 即 V2.1 §13 语义，本席补源码契约测试 + 真实行行为测试锁定）。

## 阶段 3：GREEN + 回归验证（全部实跑）

命令口径：`BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
ChatBot_Runtime/venv/Scripts/python.exe -m pytest <targets> -p no:cacheprovider
--basetemp=$TEMP/v21-autosync -q`（全程 BOT_AUTOSYNC=0 = V2.1 验收模式实弹验证）。

1. 新测试 GREEN：`tests/test_autosync_gate.py` → **36 passed in 1.03s**。
2. 门禁回归：test_autosync_gate + test_doc_sync_gates + test_cross_validation_gates +
   test_verify_hashes_coverage → **45 passed, 1 failed**。唯一失败
   `test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync` 为**预存漂移，
   非本席回归**，定责证据：
   - 唯一漂移键 = 测试文件数（unified diff 只有一行：磁盘 355 → 代码推导 358）。
   - 归因：HEAD 跟踪 325 + 磁盘 34 个未跟踪 test_*.py（并行席位批量在途）= 358；
     auto-facts 停在 355 → 本席文件入库前磁盘已是 357 ≠ 355，门禁已红；
     本席仅贡献 +1。
   - 修复路径 = `python scripts/doc_sync.py --write`（门禁自述的既定流程），
     但 `docs/auto-facts.md` 不在本席文件域（其他文件只读），且并行席位仍在落
     测试文件、现在写立刻再漂并有写竞态——留给协调席/批量收尾时执行一次 --write。
3. `tests/verify_hashes.py --check` 只读 → **EXIT=0**（交付物基线未被本席改动，
   含 render_hashes.json）。
4. ruff：`ruff check tests/test_autosync_gate.py tests/conftest.py` →
   3 处 RUF100（多余 noqa）已 `--fix` 清零，**All checks passed**。
5. 树卫生：无 `__pycache__`/`.pytest_cache`/源码树 `data/` 残留；
   `plugins/bot_unified_runtime/sources/data/qx.json` 内置资产完好。

## 结论

- AC1（显式 0/false/no/off 尊重）：dev.ps1 守卫行真身子进程实测透传
  （0/false/OFF 原样、未设置才默认 1）；conftest `run_autosync` 禁用时零
  subprocess 调用（command_catalog/doc_sync/verify_hashes 三处 `--write` 全跳过）。
- AC2（未设置/1 行为字节级兼容）：判定矩阵含 None/"1"/" 1" 等边界；启用路径
  三步 `--write` 与哈希基线留痕 warning 均有现状回归锁，且实现未改任何取值
  组合下的启用/禁用结论。
- AC3（回归测试）：36 例全离线 tmp_path/fake-subprocess，纯函数判定 +
  conftest 行为 + dev.ps1 源码契约与真实行三层覆盖。
- AC4（实跑验证）：见上 1-4；doc_sync 门禁唯一红已定责为预存漂移（证据链
  完整），非本席回归。

