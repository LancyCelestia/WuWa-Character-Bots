# FLR 工单 — test_config_key_registration_ledger.py 全件复验（2026-10-02 下午窗，只读席）

## ① 命令
- 前置：`mkdir -p "$TEMP/qoder-FLR/bt"`（实际落在 `/tmp/qoder-FLR/bt`，Git Bash，仓库外）；`python --version` → Python 3.12.10（全局解释器，非 ChatBot_Runtime venv）。
- 全件：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest tests/test_config_key_registration_ledger.py -q -p no:cacheprovider --basetemp="$TEMP/qoder-FLR/bt"`
- 邻域：同前缀 `python -m pytest tests/test_config_read_points_declared.py tests/test_single_entry_gates.py -q`（其后为取断言首行补跑 `tests/test_config_read_points_declared.py -q --tb=short -rf`，读数一致 2 failed）。

## ② 全件末行（原样）
```
39 passed in 616.13s (0:10:16)
```
零红，含四枚 poison 腿。

## ③ 邻域读数
`tests/test_config_read_points_declared.py + tests/test_single_entry_gates.py` → 末行原样：`4 failed, 34 passed in 50.13s`

四枚红 node ID + 断言首行原样（未修）：
1. `tests/test_config_read_points_declared.py::test_config_field_source_agrees_with_pydantic_truth`
   `SystemError: The installed pydantic-core version (2.49.0) is incompatible with the current pydantic version, which requires 2.46.5.`（import `config.py` 即炸＝环境性红，见 ⑤）
2. `tests/test_config_read_points_declared.py::test_ghost_read_points_exactly_match_registry`
   `AssertionError: 新增未登记幽灵读点（补 Config 字段或改读点，二选一后销账）`；extra＝`('plugins/bot_unified_runtime/domains/ops/db_backup.py', 'bot_db_backup_enabled')` 与 `('plugins/bot_unified_runtime/domains/ops/db_backup.py', 'bot_db_backup_dir')`
3. `tests/test_single_entry_gates.py::test_gate2_no_module_reads_host_metrics_beyond_the_ledger`
   `AssertionError: 又长了抄取数的文件：{'disk': ['plugins/bot_unified_runtime/domains/ops/db_backup.py']}。修法：调已登记真身（`host_metrics` 或 `host_status.cached_host_snapshot`），不要自己再读一次 psutil/注册表/nvidia-smi`
4. `tests/test_single_entry_gates.py::test_gate2_multi_reader_facts_do_not_grow`
   `AssertionError: 重复取数的事实从 1 涨到 2：['disk', 'self_process']。`

## ④ 与复录前对照
- 全件：CHK 席复录前读数 `4 failed, 35 passed` → 本次 `39 passed` 全绿。CORPUS_FLOOR_BASELINE→(784,1612,3,688) 复录后全件无回归，净减 4 红、0 新红。
- 邻域：与在册 WT-only 红邻域记录相容；其中 2/3/4 三枚同源 `domains/ops/db_backup.py`（disk 抄取 + 两枚幽灵读点），疑似在飞席面，本席未修未裁。

## ⑤ 未尽事项
- 全件在全局 Python（pydantic-core 2.49.0）下跑；ledger 件不敏感（39 绿），但邻域第 1 枚在同一环境是 import 期 SystemError，非断言红——与 CHK 在册记的那枚是否同因未核（unknown），需在 Runtime venv 或原席环境复跑 `tests/test_config_read_points_declared.py` 定性。
- 邻域 4 红均未修（本席只读）；归属（WT-only 在飞面 vs 复原残留）留给主会话。
- 未复跑 poison 腿单独计数（全件已含且绿）。
