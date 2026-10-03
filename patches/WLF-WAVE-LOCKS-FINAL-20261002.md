# WLF — 修复波六锁终戳工单（2026-10-02 下午窗）

席 WLF，只读终戳席。本窗六枚新锁/改锁在当前终态树上合并复跑，产出终戳读数。全程零写（本工单除外）。

## ① 命令

```
# 首跑误用系统 Python 3.12（缺 nonebot，5 collection errors），改用 Runtime venv 解释器后成立：
mkdir -p "$TEMP/qoder-WLF/bt"
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_intimate_group_switch_delivery.py \
  tests/test_migration_status_assignment_gate.py \
  tests/test_db_backup.py \
  tests/test_ab_red_bucket.py \
  tests/test_prompt_template_layer_w1.py \
  tests/test_store_write_trace_d2.py \
  -q -p no:cacheprovider --basetemp="$TEMP/qoder-WLF/bt"
```

两件单跑各用独立 basetemp（`$TEMP/qoder-WLF/bt-s1`、`bt-s2`），命令同构。

## ② 合并末行（原样）

```
115 passed in 13.42s
```

（六文件 = 18+15+28+9+28+17 = 115，与预期一致。）

## ③ 单跑两件末行（原样）

```
tests/test_command_admin_gate_registration.py   →  9 passed in 59.78s
tests/test_timeout_umbrella_remaining_legs.py   →  20 passed in 2.59s
```

（锚全绿 / 锚 20P，均达。）

## ④ 与预期差说明

终态零差。备注：首跑一次环境误判（系统 python 无 nonebot，5 errors in 2.17s，收集期 ImportError，非代码红），换 venv 解释器后不复现，不计入红账。

## ⑤ 未尽事项

- 本席零 git 写、零进程动作；读数基于当前工作树（未提交 WIP 若在飞，以本读数时刻为准，2026-10-02 下午窗）。
- 合并跑 13.42s、admin 门单跑 59.78s 偏慢但绿，无动作项。
- 六锁生效仍以 bot 重启为前提（铁律：改码必须重启；台账 #10 同源约束）。
