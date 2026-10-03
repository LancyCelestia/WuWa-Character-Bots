# NB4 工单 — 四红定性（2026-10-02 下午窗 · 定性席 · 只读）

- 使命：席 FLR 报的 4 枚邻域红（`test_config_read_points_declared.py` 2＋`test_single_entry_gates.py` 2）逐枚定性（HEAD 既存 / 晨窗新件带入 / 挪家带入 / 环境性），供终局净新增红判定。
- 环境：HEAD＝`143098d71a51f2890055383ae771f05ac749780b`（2026-10-02 11:27:37 +0800）；venv＝`ChatBot_Runtime/venv/Scripts/python.exe`；global＝`Python 3.12.10`（AppData site-packages）。两测试件 `git status` 零差异（tracked 未改）；`db_backup.py`＝untracked（晨窗 X1c 新件）。
- 手段：`git archive HEAD tests plugins scripts bot.py` → `%TEMP%/qoder-NB4/head`（python tarfile 解包），两侧同尺同 venv 复跑；pytest 全程带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/qoder-NB4/bt[-head]`。

## ① 工作树读数 + 4 枚点名

**global python**：`4 failed, 34 passed`：
1. `tests/test_config_read_points_declared.py::test_config_field_source_agrees_with_pydantic_truth` — 断言原文：`SystemError: The installed pydantic-core version (2.49.0) is incompatible with the current pydantic version, which requires 2.46.5.`（炸点＝`config.py:9` import pydantic，`pydantic/version.py:94`）
2. `tests/test_config_read_points_declared.py::test_ghost_read_points_exactly_match_registry` — `新增未登记幽灵读点`，Extra＝`('plugins/bot_unified_runtime/domains/ops/db_backup.py','bot_db_backup_enabled')`、`('…db_backup.py','bot_db_backup_dir')`
3. `tests/test_single_entry_gates.py::test_gate2_no_module_reads_host_metrics_beyond_the_ledger` — `又长了抄取数的文件：{'disk': ['plugins/bot_unified_runtime/domains/ops/db_backup.py']}`
4. `tests/test_single_entry_gates.py::test_gate2_multi_reader_facts_do_not_grow` — `重复取数的事实从 1 涨到 2：['disk', 'self_process']`（`assert 2 <= 1`）

**venv**：`3 failed, 35 passed`——枚 1 消失，余 2/3/4 原样。

## ② HEAD 侧对照读数

HEAD 抽取件（含 bot.py）同尺同 venv：**`38 passed, 0 failed`**。
⚠ 记录一次抽取伪影：首抽只带 tests/plugins/scripts（漏根目录 bot.py）时曾出 1 枚假红 `test_non_plugin_config_receivers_are_excluded_but_alive`（`('bot.py','_driver_config')` 排除项不命中真树）；补 bot.py 后全绿 ⇒ 该枚非 HEAD 真红，HEAD 基线＝0 红。

## ③ 逐枚定性表

| # | node ID | 定性 | 依据 |
|---|---|---|---|
| 1 | `…declared.py::test_config_field_source_agrees_with_pydantic_truth` | **环境性**（非代码红） | global py312 site-packages pydantic/pydantic-core 版本失配；venv 同测 **1 passed**；HEAD 抽取件＋global 同测 **1 failed**（与 db_backup、与本窗改动全无关，任何 import config 的测试在 global 下必炸） |
| 2 | `…declared.py::test_ghost_read_points_exactly_match_registry` | **晨窗新件带入** | 点名集仅含 db_backup.py 两键；HEAD 零红 |
| 3 | `…gates.py::test_gate2_no_module_reads_host_metrics_beyond_the_ledger` | **晨窗新件带入** | db_backup.py:506 `shutil.disk_usage(root).free`＝disk 账外读点（账＝`{host_metrics, host_status}`） |
| 4 | `…gates.py::test_gate2_multi_reader_fact_do_not_grow`（棘轮） | **晨窗新件带入** | 实测观测集：HEAD `disk=[host_metrics]`、`self_process=[resources,host_metrics]`；WT `disk=[db_backup,host_metrics]`、`self_process=[resources,host_metrics]`——self_process 两侧全同（非他件挪家），disk 仅因 db_backup 新增一读 ⇒ multi 1→2 全由 db_backup 贡献 |

**挪家带入＝0 枚**：两测试件与 HEAD 零差异；各红点名集均不含其他文件。

## ④ 键登记状态

`grep -n "bot_db_backup" plugins/bot_unified_runtime/config.py scripts/runtime_paths.py .env.example docs/config-catalog-full.md` ⇒ **四面全零命中**。
键真身＝db_backup.py:196-223 共 **7 枚**：`bot_db_backup_enabled / _dir / _keep_last / _size_ceiling_bytes / _max_footprint_bytes / _min_free_bytes / _stale_after_hours`（全走 `getattr(config, …)` / `_read_int(config, "…")`）。
- 按 #68★ 幽灵键三面判据（Config 字段＋settings.py 热改态＋.env.example）：**三面全缺**；文档面（config-catalog-full.md）也缺。
- 门可见性缺口：幽灵门只点名 2 枚（`getattr` 字面量属性访问形态，:201/:208）；其余 5 枚走 `_read_int(config, "字面量", …)` 形态，对该 AST 门不可见 ⇒ 真实未登记面 7 枚、门报 2 枚。
- `patches/B1-CONFIG-REQUEST.md` 无 `db_backup`/`bot_db_backup` 字样 ⇒ **不覆盖**。

## ⑤ 净新增红判定建议（本席轴）

- **venv（正解解释器）轴：净新增红＝3 枚**，全部归因晨窗 X1c 未跟踪新件 `db_backup.py`（2 枚直接点名＋1 枚棘轮经 disk 传导）；HEAD 轴＝0 红；环境性 SystemError 不计入（换 venv 即消，且 HEAD＋global 同样红）。
- 修向（供决策，不在本席执行面）：A. 给 Config 补 7 字段并四面登记（#68★ 三面齐＋catalog）＋db_backup 读点收进 `host_metrics`/`host_status` 真身；B. 不上该件则删件归零。两路均须过 `test_config_key_registration_ledger` / db-owners 联动门。

## 复跑命令

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest tests/test_config_read_points_declared.py tests/test_single_entry_gates.py -q -p no:cacheprovider --basetemp="$TEMP/qoder-NB4/bt"   # global：4F
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ChatBot_Runtime/venv/Scripts/python.exe -m pytest <同上>   # venv：3F
git archive HEAD tests plugins scripts bot.py | python -c "tarfile 解包到仓外" 后同尺 venv 复跑   # HEAD：38P/0F
```
