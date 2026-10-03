# SNP-STRUCT-NET-20261002 — 席 SNP 安全网扫（只读）工单

- 时刻：2026-10-02 09:55 UTC ｜ 席：SNP（安全网扫席，全程只读，本工单除外）｜ HEAD：`143098d`
- 轴：本窗生产件（content_route / tts / db_backup 挪家 / write_trace / prompt_template / capability_protocols / nonebot）相邻的结构契约锁，判零外溢与否。
- 解释器：`ChatBot_Runtime/venv/Scripts/python.exe`（pytest 9.1.1）。每件命令形：
  `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest tests/<件> -q -rf --tb=short -p no:cacheprovider --basetemp=<仓库外>/qoder-SNP/bt/bX`（无缓存、basetemp 全在 `%TEMP%\qoder-SNP\`）。

## ① 逐件读数表（末行原样）

| 件 | 末行 | exit |
|---|---|---|
| tests/test_rendering_contract.py | `157 passed in 10.60s` | 0 |
| tests/test_pipeline_hard_timeout.py | `11 passed in 2.63s` | 0 |
| tests/test_timeout_umbrella_remaining_legs.py | `20 passed in 2.51s` | 0 |
| tests/test_pipeline_offload_always.py | `10 passed in 5.09s` | 0 |
| tests/test_reply_policy_permanent.py | `91 passed in 15.59s` | 0 |
| tests/test_reply_policy_preset_command.py | `10 passed in 2.65s` | 0 |
| tests/test_datafix_runtime_paths.py | `20 passed in 16.99s` | 0 |
| tests/test_legacy_shim_import_ratchet.py | `12 passed in 69.13s (0:01:09)` | 0 |
| tests/test_capability_manifest_gate.py | `3 failed, 73 passed in 23.36s` | 1 |

## ② 红的分桶

红 3 枚，全在 `tests/test_capability_manifest_gate.py`（该件与 HEAD 零差异）：
- `::test_leg7_coverage_ratchet_never_rises`（未申报枚数 105 > 上限 101）
- `::test_leg8_direct_callsites_declared_match_census`（bot.chat x4/x2、bot.randpic x1、bot.tts x2 现算有而册未申报；bot.chat x3/x1、bot.moegirl x2 册申报而现算无）
- `::test_poison_callsite_new_site_not_followed_is_red`（注毒腿因真数据两向红无从自证）

分桶判据（规则 68 正道）：`git archive HEAD`（=143098d）抽到 `%TEMP%\qoder-SNP\head-baseline\` 同尺复跑 → **同 3 枚红、逐字同内容**（leg7 同 105>101 同清单；leg8/注毒同 5 缺 3 陈旧清单）。⇒ **三红全为既存（HEAD 同红），非工作树红**。

## ③ 外溢判定（本轴＝本窗生产改动是否引入）

**零外溢。** 8/9 件全绿；唯一红件三枚均为 HEAD 既存，不在本窗引入面。旁证：
- 本窗生产件（content_route +41 / tts +40 / nonebot +36 / capability_protocols +197 / reply_policy +231 / chat / echo WIP）相邻的出站腿、硬超时、V1 伞、offload、reply_policy 邻域、挪家棘轮、runtime_paths 全绿；其中 `tests/test_legacy_shim_import_ratchet.py`（+98 WIP）与 `tests/test_reply_policy_permanent.py` / `test_reply_policy_preset_command.py`（WIP）带在飞改动仍绿。
- `plugins/bot_unified_runtime/__init__.py` 本窗未改；注册册 `docs/boards/B02-routing-dispatch/capability-registry/README.md` 在飞 +6 行＝席 C-D-01 纯散文补记，不动任何声明行（故 HEAD/WT 失配集逐字一致）。三枚既存红的清偿责任在 manifest gate 册账侧（与 #72 盘面已知红背景同向），非本窗各席债务。

## ④ 锚差说明

简报三锚全中、无锚差：datafix_runtime_paths＝20P（锚 20P✓）、timeout_umbrella＝20P（锚 20P✓）、offload_always＝10P（锚 10P✓）。

## ⑤ 未尽事项

- 只扫简报指名 9 件，未跑全量回归（越权）。
- 三枚既存红未修（只读席）；建议主会话按②清单移交 manifest gate 册账责任席。
- HEAD 基线副本滞留 `%TEMP%\qoder-SNP\head-baseline\`，可删；全程无 git 写、无进程动作、无配置改、无源码/测试文件写入。
