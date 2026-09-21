# v21r2 R5 席工作日志（__init__.py 热区独占，第 4 次派遣）

> 本文件由 R5 席边做边追加；阵亡也不丢进度。时间线倒序无关，按完成顺序记录。

## [A] notice 族（戳一戳）摄取崩溃 —— 已核验 + 全链路回归锁死

- **根因**：生产栈 `Matcher(type='notice') _handle_poke_notice → _send_parts_through_unified_pipeline → _run_capability_through_pipeline → IngressGateway(_incoming_from_nonebot_event).from_event → get_plaintext()`；NoneBot 的 OB11 NoticeEvent 族无 `message` 字段，`get_plaintext` 抛 `ValueError("Event has no message!")`。
- **修复状态（诚实登记）**：`__init__.py` `_incoming_from_nonebot_event` 内的 `try/except ValueError → text=""` 守卫在本次派遣接手时**已在工作树 WIP 中**（未提交，与 09-16 实弹批的其他改动同文件共存；未跟踪测试 `tests/test_poke_notice_ingest.py` 亦已存在）。本席不做重复改动，做了三件事：
  1. **全链路审计**（结论：守卫完备）：notice 族全部 7 个 handler（poke / msg_emoji_like / admin_file_notice / group_increase / group_decrease / group_admin_change / group_upload）函数体零 `get_plaintext` 直调；出站路径全部经守卫后的摄取（`_send_text/parts_through_unified_pipeline` → `_run_capability_through_pipeline`）或纯 `bot.call_api`（入群欢迎）；`sender/`、`runtime/ingress.py` 全目录零 `get_plaintext`；`_extract_onebot_raw_segments`/`collect_reply_chain` 对无 message/reply 属性事件天然容错。其余裸 `get_plaintext` 调用点全在 `on_message` 规则/handler 内，notice 事件不可达（NoneBot on_message 类型规则拦截）。
  2. **全链路回归**：新增 `tests/test_v21r2_hotzone_notice_chain.py`（3 例）——假 PokeNoticeEvent（无 message、get_plaintext 必炸）过真实摄取不抛且空文本降级；同一假事件走真实 `RuntimePipeline` + `_run_capability_through_pipeline` 生产路径，断言链路产出带戳一戳话术的 SendRequest（`text_fallback="戳回去啦。"`、session/target 正确、receipt SENT）；AST 棘轮钉死 7 个 notice handler 永不再引 `get_plaintext`。
  3. **实跑**：7 例（含 B 文件）全绿，见 [实跑证据] 节。

## [B] 凌晨无接触自发「当前处于安静时间，已暂停非必要回复。」—— 根因已修（工作树），回归锁死

- **根因**：`runtime/pipeline.py` 旧版安静时间拦截回执 `public_message="当前处于安静时间，已暂停非必要回复。"` 且被投递（该文案现存于 HEAD 提交与 `docs/ai-kb-operations-manual.md` 旧口径；`git log -S` 证实）。生产进程未重启故仍在发作。
- **修复状态（诚实登记）**：工作树 WIP 已将该回执 `public_message` 置空（与限流拦截同款裁定），本席复核全链路确认完备：`_prepare` 命中安静时间 → BLOCKED 回执 → `handle`/`handle_async` 立即返回（`isinstance(prepared, DeliveryReceipt)` 短路），**不进能力、不进发送队列、零投递**；审计 `quiet_hours_blocked` 照常留痕。语义面（`policy/quiet_hours.py`）：非交互（未 @ 且 capability ∈ {bot.chat, bot.content}）→ BLOCKED；显式交互（@ / 非 chat 能力即指令族）→ `direct_request_bypass` 放行，既有门语义不变；admin role bypass 不受影响。
- **回归锁死**：新增 `tests/test_v21r2_hotzone_quiet_silence.py`（4 例，注入时钟，全离线）——安静窗口内无人 @ 的 bot.chat：`handle` 与 `handle_async` 双路 BLOCKED + `public_message==""` + 发送队列零入队（`find_request` 也为 None）；@ 直通与指令能力直通：能力照常执行、回复照常入队 SENT。
- **待生效前提**：生产进程重启（台账既有事项，非本席可做）。

## [C] 收编项

- **C① kb_wiki_sync 停机 CancelledError 兜底（R2b 备用坐标）**：`_register_kb_wiki_sync_scheduler._sync_job`（原 :1795-1816）在 `except Exception` 前补 `except asyncio.CancelledError: return`（优雅静默退出）。R2b 的 bot.py `_early_shutdown_scheduler_stop` 已是主修；本席兜底防取消落在线程体内逃逸刷执行器日志（CancelledError 是 BaseException，原 `except Exception` 接不住）。真机验收点：重启后停机日志无 CancelledError 栈。
- **C② 两餐开场 6 变体确定性轮换（R6 草案落地）**：`_build_meal_push_text`（原 :3026-3032）由单句 f-string 改为 `_MEAL_OPENERS` 6 变体池 + `character/daily_assist.pick_variant("meal_open", ...)` 游标轮换（同池连发不重复）；6 变体文案逐字取自 `docs/design/v21r2-r6-copy-log.md` §六草案。推送调度/dedupe 行为面零改动。R6 登记的两处 LLM instruction 坐标（早报/晚报 summarize 指令）为面向模型的提示词，非用户可见文案，R6 已有输出守卫，本席不动。

## 实跑证据

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
    tests/test_v21r2_hotzone_notice_chain.py tests/test_v21r2_hotzone_quiet_silence.py \
    -q --basetemp=$TEMP/v21r2-r5c -p no:cacheprovider
7 passed in 2.28s
```

（后续回归与静态门结果继续追加于下。）

## 实跑证据（终版）

```
$ python -m ruff check plugins/bot_unified_runtime/__init__.py \
    tests/test_v21r2_hotzone_notice_chain.py tests/test_v21r2_hotzone_quiet_silence.py \
    tests/test_v21r2_hotzone_meal_variants.py
All checks passed!

$ python -m mypy --explicit-package-bases plugins/bot_unified_runtime/__init__.py
17 errors in 11 files —— 零条落在 __init__.py 与本席新测试；全部为既有面
（库 stub 缺失 openpyxl/yt_dlp/qrcode/psutil/apscheduler、control_plane 2 既有、
timesync/kb_wiki 其他席 WIP 面），与本批改动零交集。

$ python -m pytest tests/test_v21r2_hotzone_{notice_chain,quiet_silence,meal_variants}.py \
    tests/test_poke_v2.py tests/test_daily_assist.py tests/test_poke_notice_ingest.py \
    tests/test_policy_quiet_hours.py tests/test_pipeline_review_fixes.py \
    tests/test_a18_gate_idempotency_rollback.py tests/test_a19_group_failure_notice.py \
    tests/test_rate_limit_silent_and_chat_forward.py tests/test_unified_delivery_routes.py \
    tests/test_production_wiring.py -q --basetemp=$TEMP/v21r2-r5c -p no:cacheprovider
166 passed in 6.07s
```

（另：`tests/test_operational_failures.py` 单跑 103 例中 1 失败
`test_queue_worker_notifies_typed_failure_without_blocking_state_update`——
系 R2 席 09-17 WIP 在 `sender/worker.py::_notify_operational_issue_safely`
静默 `kind=bot_unavailable` 通知但未同步该存量测试所致，与本席改动零交集、
文件域不在本席，**未修**，提请 R2/属主席收口。）

## 交付清单（全部未 commit，共享工作树）

- `plugins/bot_unified_runtime/__init__.py`：
  - `_register_kb_wiki_sync_scheduler._sync_job` 补 `except asyncio.CancelledError: return`（C①）；
  - 新增 `_MEAL_OPENERS` 6 变体池 + `_build_meal_push_text` 改走 `pick_variant("meal_open", ...)`（C②）。
- 新增 `tests/test_v21r2_hotzone_notice_chain.py`（3 例，A：摄取不抛+全链路产出 poke 回复+AST 棘轮）。
- 新增 `tests/test_v21r2_hotzone_quiet_silence.py`（4 例，B：非交互双路零投递+@/指令直通）。
- 新增 `tests/test_v21r2_hotzone_meal_variants.py`（4 例，C②：6 变体零重复+确定性循环+名注记完整+池逐条含名槽）。
- A/B 的代码级修复（摄取守卫、安静时间静默）在接手时已在工作树 WIP，本席审计确认完备并补齐回归锁（诚实登记，不认领）。

## 遗留

1. 生产重启前 B 症状仍会在旧进程复现（代码已修，等用户提权重启）。
2. `sender/worker.py` bot_unavailable 静默 × 存量测试 1 例红——属主席收口（见上）。
3. R2b 备用坐标 C① 已落地，真机验收点=重启后停机日志无 CancelledError 栈。
4. R6 登记的两处早/晚报 LLM instruction 坐标核对无误、无需改动（面向模型的提示词，R6 已有输出守卫），如实不认领为改动。
