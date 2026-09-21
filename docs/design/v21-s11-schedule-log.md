# V2.1 S11 日程席（A11）实施日志 — 全场景日程链确定性核心

> 2026-09-17。合同：`docs/design/backend-v2-product-extensions.md` §4；验收矩阵 V21-TIME-001（时区部分）+ V21-SCHEDULE-002/003（核心算法）。
> 范围裁定：LLM 草稿解析 / 课表截图识别（recognize_timetable）/ 真实投递不在本席（需模型与运行时），本席交付全部**确定性核心**与生产装配位。未 commit（共享工作树，提交裁决权在用户）。

## 一、新增文件

| 文件 | 职责 |
|---|---|
| `plugins/bot_unified_runtime/runtime/schedule_dag.py` | 模型层 + DAG 校验 + 最早可行窗口 |
| `plugins/bot_unified_runtime/runtime/schedule_rrule.py` | 本地时→UTC 解析（DST/fold）+ RRULE 有限子集展开 |
| `plugins/bot_unified_runtime/runtime/schedule_store.py` | SQLite 持久层（WAL/租约/时间索引/限流计数/安静例外） |
| `plugins/bot_unified_runtime/runtime/schedule_service.py` | 服务门面（合同函数面）+ `build_schedule_service` 工厂 |
| `tests/test_schedule_service_v21.py` | 49 例全离线回归（固定时钟 + tmp_path） |

现存文件零改动（`git status` 实证：本席产物全部为 `??` 未跟踪新文件；`character/reminders.py`、`__init__.py`、`config.py` 未触碰）。

## 二、模型清单（pydantic StrictModel，extra=forbid，风格对齐 contracts/runtime.py）

- `SchedulePlan(plan_id, owner, timezone(IANA 合法性校验), revision, state=draft|active|paused|archived, tasks, edges, rules, reminder_policy, quiet_hours)`
- `TaskTemplate(task_id, title, kind=fixed_time|duration|relative_to_start|relative_to_finish, duration_minutes, anchor_task_id, offset_minutes, fixed_local_time, soft_window_minutes, tags)`；`is_hard`（soft_window==0）/`is_rush`（"rush" tag）派生属性
- `DependencyEdge(edge_id, predecessor, successor, relation=finish_to_start|start_to_start|finish_to_finish|start_to_finish, offset_seconds, failure_policy=block|warn)`
- `RecurrenceRule(rule_id, task_id, kind=once|daily|weekly|weekly_by_day|teaching_week, rule_revision, start_date, end_date, local_time, weekdays, week_parity, parity_anchor_date)`（学期起点缺省取 start_date）
- `ReminderPolicy(offsets_minutes=(-10,0) 默认前10分钟+准点, ≤4 条模型硬钳, urgent, quiet_hours_behavior=defer|send, missed_policy=skip|send_once|digest|ask, grace_minutes=15)`
- `QuietHours(start="23:00", end="07:00")`（跨午夜支持）
- `Occurrence(occurrence_id, plan_id, rule_id, rule_revision, task_id, title, scheduled_at_utc, duration_minutes, tags)`

## 三、函数清单与复杂度

| 函数 | 位置 | 语义 / 复杂度 |
|---|---|---|
| `validate_plan_dag(plan, max_tasks=100, max_edges=300)` | dag | Kahn 拓扑 **O(V+E)**；环→`schedule_cycle`；超限/未知端点→结构化 issues（不抛异常） |
| `compute_earliest(plan, anchors)` | dag | 拓扑序一遍传播 **O(V+E)**；fixed_time 无锚/锚缺失→`missing_calendar` |
| `resolve_local(tz, day, hhmm, fold=0, strict=False)` | rrule | PEP 495 语义；不存在时刻自动顺延 gap（`corrected_nonexistent`），歧义取 fold=0/1（`ambiguous_fold0/1`）；strict=True 抛 `ambiguous_local_time` |
| `iter_rule_dates(rule, ws, we)` | rrule | 真实日历遍历（跨年天然正确）；单双周按周一锚定周数 O(窗口天数) |
| `expand_occurrences(plan, now_utc, horizon_days=30, max_occurrences=1000)` | rrule/service | 物化未来 30 天、每 plan ≤1000 即停不超发；`occurrence_id=sha256(rule_id|rule_revision|scheduled_at_utc)[:20]` 幂等 |
| `parse_plan(payload)` | service | 确定性 dict→模型（LLM 半边不在本层） |
| `submit_plan / confirm_plan` | service | DAG 校验 + expected_revision 版本校验（不符→`version_conflict`） |
| `preview_reschedule(plan_id, changes, expected_revision)` | service | 软窗→diff+`new_revision`；硬预约→`schedule_conflict` 不静默顺延；硬碰撞（同日同刻两条硬规则）→conflict |
| `apply_reschedule` | service | 版本重校验→`supersede_rule` 旧版本未来实例退役→revision+1→重物化 |
| `claim_due(worker_id, limit=50)` | store/service | `BEGIN IMMEDIATE` 下 SELECT→UPDATE 线性化，租约 300s；`WHERE status='pending' AND due_epoch<=? AND (lease IS NULL OR 过期)` 走 `idx_occ_due(status, due_epoch)` 索引（EXPLAIN 实证），不扫全表；默认轮询 5s 语义（`poll_seconds` 暴露） |
| `cancel_occurrence` | store/service | 活跃租约内→`in_flight`（在途无法保证撤回）；否则 `cancelled`；claim 后取消必 in_flight、cancel 后 claim 必失败（竞态测试锁定） |
| `mark_task_done / snooze(minutes)` | store/service | done；顺延回 pending+清租约 |
| `reconcile_missed(grace_minutes=15)` | service | rush→`expired`（occurrence_expired 语义，绝不当"即将开售"）；send_once：grace 内保持 pending 迟发一次、超出→`digest`；skip/ask/digest 分流；重启=新 store 句柄再跑 |
| `split_quiet_hours(claimed)` | service | 非紧急→顺延至安静结束（租约释放）；urgent/显式批准例外→立即发；例外经 `approve/list_quiet_exceptions` 可查询 |
| `acquire_send_slot(owner, occ)` | service | 每分钟 ≤3、每小时 ≤20（`schedule_send_log` 确定性计数），超限→`digest` 决策 |
| `build_digest(owner)` | service | 确定性合并摘要（按 owner 过滤、逐条列出）；发送层只消费 decision/digest/claim 结果（**接口留位**） |
| `build_reminders(plan, occ)` | service | 默认 [-10,0] 分；每 offset 唯一 `reminder_id=sha256(occurrence_id|offset)[:20]` |
| `build_schedule_service(config)` | service | **生产装配位**：`bot_schedule_db_path`（默认 `data/schedules_v21.sqlite3`）经 `scripts/runtime_paths.runtime_path` 重映射 |

错误码：六个合同码全部取自 `contracts/errors.py` 已注册表（测试锁定）；`plan_limit_exceeded`/`unknown_edge_endpoint` 为本地确定性码，未入全局注册表（见遗留项④）。

## 四、存储（schedule_store.py）

- PRAGMA `journal_mode=WAL` + `busy_timeout=1000` + `synchronous=NORMAL`；单连接 + `threading.Lock`；写路径全部 `BEGIN IMMEDIATE`。
- 表：`schedule_plans` / `schedule_occurrences`（含 `lease_owner/lease_expires_epoch`，索引 `idx_occ_due(status, due_epoch)`、`idx_occ_plan`）/ `schedule_send_log`（`idx_sendlog_owner_time`）/ `schedule_quiet_exceptions`。
- 库路径经 runtime_paths 重映射；测试一律 tmp_path 显式路径（conftest data 守卫零触发）。

## 五、测试实跑（诚实底线：以下为真实命令与输出）

```
$ cd ChatBot && PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_schedule_service_v21.py \
  --basetemp="$TEMP/v21-schedule" -p no:cacheprovider -q
................................................                         [100%]
49 passed in 2.39s     ← 连续三次：49 passed in 2.39s / 2.30s / 2.32s（并发用例无抖动）

$ python -m ruff check <5 个新文件>
All checks passed!

$ python -m mypy --cache-dir=%TEMP%/v21-schedule/mypy --explicit-package-bases \
  --ignore-missing-imports plugins/.../schedule_{dag,rrule,store,service}.py
Success: no issues found in 4 source files
```

覆盖映射（任务书 10 项 → 测试）：环检测 `TestDag.test_cycle_rejected*`；单双周 `test_teaching_week_parity_and_cross_year`；跨年 `test_cross_year_dates_via_service`；夏令时 `test_dst_nonexistent_time_corrected` / `test_dst_expansion_notes`；时钟倒拨 fold `test_dst_fold_two_instants` / `test_fold_expansion_note`；不同日期同名任务 `test_same_title_different_dates_distinct_ids`；重复导入幂等 `test_double_import_is_noop` / `test_rule_revision_bump*`；取消与发送竞态 `test_cancel_then_claim_fails` / `test_cancel_after_claim_is_in_flight`；离线一周 reconcile `TestReconcileMissed`（含 `test_restart_reconcile_with_fresh_handle`）；claim 并发唯一 `test_claim_concurrent_unique`（4 线程 4 连接 barrier）；风暴限流合并 `TestStormGate`；DST fold 展开 `test_fold_expansion_note`。另覆盖：任务/边上限、相对链最早窗口、version_conflict、软窗 diff+new_revision、硬冲突/硬碰撞、时间索引导 EXPLAIN、安静时间边界、>4 offset 模型拒绝、错误码注册表锁定。

## 六、与既有 reminders/daily_assist 的复用关系（rg 只读取证，未改其文件）

- `character/reminders.py`（会话待办 ≤20，` ReminderStore` WAL+单连接+Lock 惯例）→ 本席**沿用其存储惯例**（WAL 先于 DDL、`due()` 查询、`mark_done/cancel` 命名），但语义不平行：S11 是 plan/rule/occurrence 三层模型 + 租约线性化 + 版本化，reminders 是单层自然语言待办；两者库文件分离（`reminders.sqlite3` vs `schedules_v21.sqlite3`），互不影响。
- `capabilities/daily_assist.py`（收件箱/早晚报）→ 无共享状态；S11 的 digest 合并语义与其 21:00 晚报互不替代（digest 是限流/错过产物，发送层可后续择机投递）。
- `contracts/errors.py`（S2 席）→ 六个日程错误码直接消费并测试锁定，未新增注册表条目。

## 七、遗留项（移交后续席位/用户裁决）

1. **LLM 草稿解析**：`parse_plan` 只做 dict→模型半边；自然语言→SchedulePlan 草稿需模型（合同 §4.1），走 `/schedules/drafts` 时接入。
2. **课表截图识别**（`recognize_timetable`）：行列/合并区域/周次/置信度，缺学期起点与节次表不得发布——需视觉模型，未实现。
3. **真实投递接线**：`build_schedule_service(config)` 装配位已留好（config 只读 getattr，不依赖 WIP 中的 config.py）；SendQueue submit、轮询循环（5s）、`acquire_send_slot`→SendRequest 的映射属运行时接线席。
4. **本地错误码注册**：`plan_limit_exceeded`/`unknown_edge_endpoint` 未入 `contracts/errors.py` 全局表（避免与并行席位改同一文件冲突）；上 API 面前需补登记或映射。
5. **调休/校历例外**：单双周已支持，节假日调休例外表（校历 exceptions）未建模——合同模板行"校历例外必须明确"，待校历数据源席位。
6. **通勤 ETA**：按合同不做 LLM 猜 ETA，用户 buffer 字段（`offset_minutes`）已可承载，产品面提示未接。
