# v21r2 S11 席日志（全场景日程提醒·余量交付，2026-09-18）

> 合同：backend-v2-implementation-guide.md §13 S11 行 + backend-v2-product-extensions.md §4 +
> 验收矩阵 V21-SCHEDULE-001/002/003。域现状：W10（RW10 席）已迁 `domains/schedule/**` 并保持
> 653 passed 存量面；旧 v21 S11 席（2026-09-17，`v21-s11-schedule-log.md`）已交付确定性引擎四件
> （dag/rrule/store/service，现位于 `domains/schedule/service/`，其遗留项①②③⑤即本席范围）。
> 引擎族**只读复用禁改**——全程零改动实达（git diff 面=本席新文件+config 三处同生）。

## 一、交付物（全部落地）

| 文件 | 职责 | 只读消费面（实测） |
|---|---|---|
| `plugins/bot_unified_runtime/domains/schedule/llm_draft.py` | 自然语言→ScheduleDraft（动作/时间/依赖/重复规则+七模板链种子）；失败/低置信→澄清问题清单禁猜 | `llm.model_router.build_model_router`（PEP 562 垫片，DI 注入 `.generate`，模块 import 零硬依赖） |
| `plugins/bot_unified_runtime/domains/schedule/timetable.py` | 课表截图→结构草稿（行列/合并/周次/置信度保留；节次→时间映射；缺学期起点或节次表=needs_clarification 拒发布；指纹去重） | `domains.media.ingest.vision_describe.build_vision_provider`（惰性 import 只读） |
| `plugins/bot_unified_runtime/domains/schedule/delivery.py` | occurrence 到点→claim_due→split_quiet_hours（安静门）→acquire_send_slot（风暴门）→SendRequest→`queue.submit(deliver_after=now)`→receipt 诚实落账；退避重试；例外表 | `domains.schedule.service.ScheduleService`（W10 引擎；`_store` 公有方法面经服务句柄只读消费——服务层无 set_status 透传，禁改故不加） |
| `plugins/bot_unified_runtime/domains/schedule/data/calendar_exceptions.json` | 调休/节假日例外表数据文件+schema 模板（**entries 为空：无官方核实数据不预填任何日期**） | `CalendarExceptions.load_default`（随包模板+config overlay 同键覆盖） |
| `tests/test_v21_s11_llm_draft.py`（21 例）/ `tests/test_v21_s11_timetable.py`（16 例）/ `tests/test_v21_s11_delivery.py`（17 例） | 全离线回归（DI 桩/FakeQueue/固定可拨时钟/tmp_path），零网络零 NoneBot | — |

- **禁猜边界**（均有测试锁定）：缺日期→needs_clarification 且 `draft_to_plan_payload` 拒发布；
  有时刻没日期→`missing date fact` 拒发布；规则永不落默认时刻（早期稿的 "08:00" 兜底已按
  诚实底线移除）；课表低置信(<0.3)条目丢弃不收；例外表年份不在表=unknown 绝不当 regular/holiday 宣称。
- **不擅自购买**（结构性）：购物链「下单记录」只是用户自己下单后的记录提醒步；抢票链只提醒
  （rush 标签→引擎过期即 occurrence_expired 语义）；测试断言全链无 pay/purchase/auto_buy 语义。
- **真实出站端口未授权**：queue/builder 未注入→`not_authorized` 干跑（租约释放保持 pending，
  detail 如实写 unauthorized），绝不伪装成功；注入后也只到 `queue.submit` 为止（发送由队列
  worker 授权边界执行）；receipt 状态按返回值原样落 outcome，FAILED_RETRYABLE→退避重试
  （snooze 复用引擎续投），failed_final/blocked→`delivery_failed` 终态，超限重试→同终态。
- **提示词卫生**：出站 system 文本守岸人口径（llm_draft/timetable 各一），`_LEAK_MARKERS`
  （route/registry/model_router/system prompt/注入/工具调用/function call）测试逐词扫描零命中。

## 二、config 三处同生（新键 7）

`bot_schedule_enabled=False` / `bot_schedule_db_path=data/schedules_v21.sqlite3`（path_fields 重
映射；与 `build_schedule_service` getattr 兜底值一致）/ `bot_schedule_llm_draft_enabled=False` /
`bot_schedule_timetable_enabled=False` / `bot_schedule_delivery_enabled=False` /
`bot_schedule_delivery_max_retries=3` / `bot_schedule_exceptions_path=data/schedule_exceptions.json`
（path_fields 重映射）。三处=config.py 键块（campus 块后新增 bot_schedule_* 键块）+
`docs/config-catalog-full.md` A26 五行 + `.env.example` 尾块。doc_sync 门禁实跑 19 passed。

## 三、实跑证据（诚实底线：以下为真实命令与输出摘要）

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_v21_s11_llm_draft.py tests/test_v21_s11_timetable.py tests/test_v21_s11_delivery.py \
  --basetemp="$TEMP/v21r2-s11" -p no:cacheprovider -q
......................................................                   [100%]
54 passed in 2.02s        ← 21+16+17 例，修复期复跑两次同绿

$ …python -m pytest <W10 显式域清单 17 文件 + 本席 3 文件> … -q
574 passed, 1 failed      ← 唯一失败=copy_redline_gate::test_current_tree_no_critical_redline
                            （criticals 全部位于 domains/chat_reply/runtime/content_route.py
                            R-18 词表——RWC 批迁移使其进入门禁扫描面，归该批收口；
                            domains/schedule/** 零命中）

$ …python -m ruff check <三模块+config.py+三测试文件>
All checks passed!        （--fix 收 7 处 I001/SIM 纯格式；余 6 处按建议改写：SIM102 条件合并/
                           S112 补 debug 日志/F822 __all__ 修正/PYI046 删未用协议/TRY004 TypeError）

$ …python -m mypy --explicit-package-bases --ignore-missing-imports <三新模块>
Found 2 errors in 1 file  ← 全部为 control_plane/api/platform.py:79/:254 既有基线（台账 #36）；
                             本席三模块 0 错

$ …python -m pytest tests/test_doc_sync_gates.py tests/test_datafix_runtime_paths.py \
  tests/test_no_source_tree_data_writes.py … -q
19 passed                 ← 含 config-catalog 键覆盖门（新 7 键已登记）

$ …python -B tests/verify_hashes.py --check ; echo exit=$?
exit=0

$ …python -B -c "插件导入+三新模块导入+垫片同一性+例外表装载+config 键"
plugin import OK / new modules OK
shim identity OK (ScheduleService, ReminderStore 旧路径 is 新路径同对象)
calendar asset exists: True years_known: [2026]   ← 随包模板空表
config keys OK（7 键齐；解析口径与 campus/notes 家族逐字节同型）
```

- **外部在飞面如实登记（非本席引入，零交集）**：①`tests/test_pinyin_triggers_3.py` 收集期
  StopIteration——`scripts/extract_trigger_words.py:104` 对旧路径 `runtime/base_router.py`
  read_text+AST 探测 `build_route_rules`，W15d 已将其迁为垫片（脚本与 chat_reply 域均本席禁触）；
  ②user_copy/copy_redline 门三红读 chat.py 垫片文本锚/content_route 扫描面（RWC 批在飞）；
  ③capability_registry 两红在合跑出现、隔离复跑 18 passed 自愈（并行席改 echo/config 竞态）。

## 四、已知边界与移交（接线席注意）

1. **production_wiring=not_wired**（三行同）：`__init__.py`/bot.py 本席禁触，无 matcher、无 tick
   调度循环；生产装配=`build_schedule_llm(config)`+`build_timetable_provider(config)`+
   `build_schedule_delivery_service(config, queue, request_builder=…)` 三助手就位，由接线席注入
   SendQueue 实例与出站构造器（真实发送端口未授权前传 None=诚实干跑）。
2. **投递重试计数进程内存记账**（`_attempts` dict）：进程重启归零，随 reconcile 重新分流；
   store schema 禁改故不落列（如需跨重启严格计数，接线席可扩 store 或复用 due_epoch 退避）。
3. **ScheduleStore 不建父目录**：离线 smoke 用缺省相对路径时父目录不存在→OperationalError；
   生产经 BOT_RUNTIME_DATA_DIR 解析到既有 Runtime/data 不受影响（campus/notes 同口径实证）。
4. **例外表数据为空**：schema 模板+加载器+unknown 语义就绪；真实调休/节假日日期需管理员按
   官方公告补录到 BOT_SCHEDULE_EXCEPTIONS_PATH（本席不臆造日期）。
5. **本地错误码**：`plan_limit_exceeded`/`unknown_edge_endpoint` 仍未入 contracts/errors.py
   全局注册表（旧 S11 遗留④，避免多席改同文件；上 API 面前需补登记）。
6. 单双周 parity 锚=学期起点（`semester_start`/`parity_anchor_date`），校历例外仅对显式
   `follow_calendar` 标签实例生效（workday 调休上班≠学校停课，合同 §4.1 口径）。

## 五、验收矩阵四列（本席终记）

| 行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-SCHEDULE-001 | **done(high)**：timetable.py（OCR→结构草稿/单双周/节次映射/行列合并置信度保留/指纹去重/缺学期缺节次表拒发布）+llm_draft.py 草稿面 | **not_wired**（无 matcher/装配；vision provider 接线席注入） | **done(high)**：test_v21_s11_timetable.py 16 例全离线全绿 | unknown（需真机截图+识图 registry+真实出站授权） |
| V21-SCHEDULE-002 | **done(high)**：W10 引擎（DAG O(V+E)/硬冲突/diff+new_revision）+本席七模板链种子→draft_to_plan_payload（过 validate_plan_dag；无购买执行步） | **not_wired**（同上） | **done(high)**：W10 653 面保持+本席 llm_draft 21 例 | unknown |
| V21-SCHEDULE-003 | **done(high)**：W10 引擎（claim 精确一次/quiet/storm/reconcile）+本席 delivery（submit 面+退避重试+receipt 诚实落账+例外表 unknown 语义） | **not_wired**（tick 无调度装配；SendQueue 协议就绪，真实出站端口未授权） | **done(high)**：test_v21_s11_delivery.py 17 例（安静不出站/风暴 digest/退避恢复/超限终态/not_authorized 干跑/例外表跨年 unknown） | unknown |
