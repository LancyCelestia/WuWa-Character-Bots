# v21r4-B REM-EVE 席日志（明晚时段语义修复）

席位：REM-EVE｜包：B-提醒解析｜状态：**已完成（离线全绿；重启后才生产生效）**
认领：`v21r4-b-coordination.md` 已追加「REM-EVE | 明晚时段语义修复 | domains/schedule/store/reminders.py + tests/test_reminder.py」（开工首动作，时点确认 REM-DAWN 已交付释放、无在飞冲突）。

## ① 取证结论

- 时段-小时调整**已存在**（`domains/schedule/store/reminders.py` 原L330-333）：`下午/傍晚/晚上` 且 hour<12 → +12；`凌晨` 12→0。「今天/明天晚上8点」原本就正确 20:00 → 按任务①判定走「日词与时段词组合路径漏了同一调整」分支，不新发明规则。
- 缺口实锤：日词「今晚/明晚」自带晚间语义，但带显式小时时正则 period 组为空 → 「明晚8点」= 次日 08:00；「今晚8点」= 今天 08:00（且 now>08:00 时因 `target<=current` **静默返回 None**，提醒根本建不成）。
- 「中午12点」语义（period 不调整=12:00）、「凌晨 0-5 语义」（含 12→0）均已存在，零补齐需求。

## ② TDD 实跑证据（解释器 ChatBot_Runtime venv，命令模板按简报）

- **RED**：`pytest tests/test_reminder.py` → `3 failed, 31 passed`。失败输出两态：`明晚8点 → label='明天 08:00'`（错）vs `明天晚上8点 → '明天 20:00'`（对）。新增/改写 4 测试：`test_parse_mingwan_evening_semantics`、`test_parse_evening_day_word_consistency`、`test_parse_evening_boundary_explicit_ge12_unchanged`（RED 阶段即绿，属保守边界现状锁）、`test_parse_full_period_hour_matrix`（上午8/中午12/下午3点半/傍晚6/晚上8/凌晨1/凌晨12/明晚8 全组合）。
- **GREEN**：最小修复后同文件 `34 passed`。
- **提醒族全量 7 文件**（5 个提醒测试文件 + `test_v21r2_reminder_guards.py` + `test_schedule_service_v21.py` 波及面）：`125 passed`。REM-DAWN「明早」上午/夜间两例原样保持通过。
- **ruff**：本席两文件 `All checks passed!`。全树 `Found 5 errors` 均为他席在飞件（`domains/render/card_render/mica_shell.py`×2（本席禁改域）、`tests/test_webui_http.py`×2、`tests/test_webui_stats.py`×1），非本席引入、不越界代修。
- **command_catalog**：`--check` → `command catalog is current (77 topics)`。
- **doc_sync**：`--check` 报漂移 → 按简报授权跑 `--write`。漂移**非本席引入**（RouteKind 33→34 含 TTS、topics 75→77、测试文件 326→415、bot_* 字段 529→610、哈希清单路径迁 domains/render——全是本波在飞存量欠账）；写后 topics=77 与协调口径一致。

## ③ 修复内容（最小面）

`plugins/bot_unified_runtime/domains/schedule/store/reminders.py`：
1. `import logging` + 模块 `logger`。
2. 原有时段调整两分支**零触碰**，其后新增：`not period and day_word in {"今晚","明晚"}` 时——`1<=hour<=11` → 记 info 日志并 +12；`hour>=12` → 保持字面并记 info 日志（任务④保守边界：「明晚20点」「明晚12点」不改，不发明半夜语义）。

`tests/test_reminder.py`：改写 1 例 + 新增 3 例（见 RED 段）。

## ④ 冲突裁决记录（须向协调者回呈）

REM-DAWN 交付中 `test_parse_mingwan_stays_consistent_with_hour` 把「明晚8点=次日 08:00」作既有语义**锁死**，与本席任务简报「明晚8点口语期待次日 20:00」直接冲突、不可兼得。按用户指令优先裁决：**修成 20:00**，该测试已改写为 `test_parse_mingwan_evening_semantics`（docstring 注明取代关系）；简报点名要保的 REM-DAWN 两例=「明早上午/夜间」（`test_parse_mingzao_day_word_tomorrow_morning`）**未动、实跑通过**。若协调者裁定应保留 REM-DAWN 的 08:00 口径，回滚点=本日志③的两处改动。

## ⑤ 本席工作树足迹（禁 git 写操作，未 commit）

1. `docs/design/v21r4-b-coordination.md`（认领行）
2. `plugins/bot_unified_runtime/domains/schedule/store/reminders.py`（解析修复；整 `domains/schedule/` 目录在 git 中未跟踪，v21r2 域重组未提交件，无 diff 属预期）
3. `tests/test_reminder.py`（+142/-9）
4. `docs/auto-facts.md`（doc_sync --write 对账）
5. 本日志

## 诚实红线

以上全部为**离线测试通过**；生产 bot 未重启，明晚语义修复**重启后才生效**。未做真实 LLM 调用/真实发送/重启/git 写操作/再派代理；禁改文件（theme_tokens/render_hashes/domains/render/output/card_render/验收矩阵）零触碰。
