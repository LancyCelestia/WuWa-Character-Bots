# OUT-OUTBOUND-NEIGHBOR 工单（2026-10-02 下午窗 · 席 OUT · 只读）

使命：MIG 席收窄量具 `tests/test_migration_status_assignment_gate.py`（未跟踪新件；生产件 outbound_registry.py 未动）后，跑 outbound 生产邻域锁收尾。全程只读（本工单除外），零 git 写 / 零进程动作 / 零配置改。
跑法：venv python + `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/qoder-OUT/bt*`，逐件 `-q`。

## ① 读数（末行原样）

| 件 | 末行 |
|---|---|
| tests/test_outbound_v21.py（含 TakeoverRegistryIntegrity 在册锁） | `59 passed in 8.45s` |
| tests/test_capability_registry.py | `2 failed, 16 passed in 2.28s` |
| tests/test_central_dispatch_closure_gate.py（25P 锚） | `25 passed in 16.44s` |

## ② 红分桶（预期外两红 → A/B）

两红均在 test_capability_registry.py（该件对 HEAD 干净，非脏面）：
- `test_help_topics_equal_registry_book_order`：钉 82、现算 83（`tests/test_capability_registry.py:414`，help topic 计数钉子过期）
- `test_help_public_visibility_derived_from_declaration`：同根（声明面 vs 注册表 83 项不齐）

A/B：`git archive HEAD` 全树抽 `$TEMP/qoder-OUT/ab` 同尺复跑 → 同两红（`2 failed, 16 passed in 5.67s`）⇒ **HEAD 既存红**。echo.py 在飞脏面 diff 无 topic 行，第 83 个 topic 在 HEAD 已入库。

## ③ 净新增判定

**零净新增。** 两红 HEAD 即红，与本波无关；MIG 席量具件未跟踪、outbound_registry.py 对 HEAD 未动；本席零源码/测试写入。

## ④ 锚差

- 25P 锚 `test_central_dispatch_closure_gate.py`（未跟踪在飞件）实跑 25 passed，与锚一致，**无差**。
- test_outbound_v21.py 59 枚全绿，TakeoverRegistryIntegrity 在册锁在内。

## ⑤ 未尽

- 2 枚既存红未修（工单禁修）：help topic 钉子 82→83 待认领席推进或裁定口径（真身 `echo.py` `_HELP_ENTRIES`）。
- A/B 树留存 `$TEMP/qoder-OUT/ab` 供复核。
