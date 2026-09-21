# v21r4-B REM-DAWN 席位日志（提醒「明早」词表修复）

## 席位信息
- 席位：REM-DAWN（v21r4-B 波次）
- 任务：修复提醒自然语言解析错记型缺口——「明早」不在日词表，「明早8点」上午场景被错记到今天。
- 文件域（已写入 coordination 表认领）：`plugins/bot_unified_runtime/domains/schedule/store/reminders.py` + `tests/test_reminder.py`
- 冲突核查（步骤①）：已读 `docs/design/v21r4-b-coordination.md`——WIRE-DIRECT 对 `domains/schedule/**` 为**只读取证面（不写）**，无任何席位认领 `store/reminders.py` 或 `tests/test_reminder.py` 的写入面；无冲突，开工。

## 定位（verified）
- 真身：`plugins/bot_unified_runtime/domains/schedule/store/reminders.py`
  - L46 `_DAY_OFFSETS`（原值 `{"今天":0,"今晚":0,"今早":0,"明天":1,"明晚":1,"后天":2}`）——无「明早」。
  - L48-51 `_ABS_TIME_RE`、L52 `_PERIOD_ONLY_RE` 日词备选串均无「明早」。
- 错记机理：「明早8点」以裸「8点」命中正则（day_word=None，匹配串从「早8点」的 8 点段起）→ day_offset=0 → 候选=今天 08:00；now < 08:00 不触发顺延 → 错记今天。now 已过 08:00（夜间）时侥幸顺延，故缺陷呈「上午场景」选择性。
- `character/reminders.py` 为纯 re-export 垫片（v21r2 重组），零改动；测试经垫片导入同一符号。

## TDD 两态实跑证据（步骤②）
- 解释器：`ChatBot_Runtime/venv/Scripts/python.exe`（模板：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1，--basetemp=$TEMP/remdawn_*，-p no:cacheprovider）
- **RED**（修复前，新增 2 测试）：
  ```
  tests/test_reminder.py::test_parse_mingzao_day_word_tomorrow_morning FAILED
  AssertionError: assert datetime.datetime(2026, 9, 11, 8, 0, ...) == datetime.datetime(2026, 9, 12, 8, 0, ...)
  + where ... = ReminderIntent(remind_at=datetime.datetime(2026, 9, 11, 8, 0, ...), label='今天 08:00').remind_at
  1 failed, 1 passed in 1.81s
  ```
  实锤复现错记：06:30 说「明早8点」→ label=**今天 08:00**（应为明天）。
- **GREEN**（修复后，同测试 + 全部提醒存量）：
  ```
  pytest tests/test_reminder.py tests/test_reminder_delivery.py tests/test_reminder_governance_receipt.py tests/test_reminder_tone.py tests/test_v21r2_reminder_guards.py
  64 passed in 3.56s
  ```

## 修复内容（最小改动面）
文件唯一改动：`plugins/bot_unified_runtime/domains/schedule/store/reminders.py`
1. `_DAY_OFFSETS` 增 `"明早": 1`；
2. `_ABS_TIME_RE` 日词备选串增 `|明早`；
3. `_PERIOD_ONLY_RE` 日词备选串增 `|明早`（「明早早上8点」类冗余句式也确定性落次日）。
不新增 config 键、不改帮助 topics、不触其他解析分支。

## 步骤④「明晚/明早+具体时刻」组合语义一致性核查（只核不改）
- 新增对照测试 `test_parse_mingwan_stays_consistent_with_hour`（RED 阶段即通过=既有语义锁定）：
  - 「明晚8点」→ 次日 08:00（与「明早8点」同构：day_offset=+1，时段词缺省不加 12）；
  - 「明晚晚上8点」→ 次日 20:00（带时段词时 +12 分支照常生效）。
- 明早修复后与明晚完全同构：日词只管日期偏移、上下午判定权归时段词；两词行为一致性由测试锁死。
- 已知既有边界（核实后不改，超本席范围）：「明晚8点」口语期待 20:00、现解析 08:00——属「明晚」历史行为，任务明令不改其他解析行为，仅在此登记。

## 验收门（全部实跑）
| 门 | 结果 |
|---|---|
| RED→GREEN 两态 | ✅ 1 failed（今天 08:00 错记实锤）→ 64 passed |
| 存量测试（5 个提醒测试文件） | ✅ 64 passed in 3.56s |
| `python -m ruff check .`（全树） | ✅ All checks passed! |
| `scripts/command_catalog.py --check` | ✅ current (77 topics)（未改帮助面） |
| `scripts/doc_sync.py --check` | ✅ exit=0 零漂移（未新增 config 键/测试文件，无需 --write；工作树中 auto-facts.md 的未提交变更为并行席位收敛产物，本席未触碰） |

## 诚实边界
- 以上全部为**离线 mock 测试证据**。生产 bot 未重启，修复**重启后才在生产生效**；在重启验证前不得宣称生产已修复。
- 零 git 写操作、零子代理派遣、未触碰禁改文件（theme_tokens/render 链/验收矩阵）。

## 完成状态
- [x] 步骤① 冲突核查
- [x] 步骤② RED→GREEN
- [x] 步骤③ 存量测试全绿 + ruff
- [x] 步骤④ 明晚/明早组合语义一致性核查（对照测试锁定）
- [x] 验收门：catalog 77 topics、doc_sync 零漂移
