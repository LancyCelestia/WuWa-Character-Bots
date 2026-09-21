# v21-R2 续跑席日志（进程生命周期+适配器韧性族）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 2026-09-17 深夜，R2 席二次续跑（前任 23:24 撞 1302 阵亡，未写日志；本席取证后续跑）。
> 文件域：bot.py、scripts/telegram_resilience.py、plugins/bot_unified_runtime/mail_adapter.py、
> plugins/bot_unified_runtime/sender/onebot.py、plugins/bot_unified_runtime/sender/worker.py、
> tests/test_v21r2_lifecycle_r2.py。未 commit（共享工作树，提交裁决权在用户）。

## 一、取证结论（前任 32 分钟实际完成度）

前任改动与历史 WIP 混合，逐文件甄别：

| 文件 | 前任状态 | 甄别 |
|---|---|---|
| scripts/telegram_resilience.py | **新建完成** | 从 bot.py 旧 monkey-patch poll 重构为 `build_resilient_telegram_adapter` 子类工厂；含 R2 降噪（前 3 次逐条告警→每 5 次一条→恢复单条）+ 401/403/409 permanent 分类停轮询 + startup catch_all 不逃逸 |
| bot.py | **P1/P4/P5/P6 全部完成** | ①`_reap_background_threads`（10s 宽限+超限 `os._exit` 强制收尾）+ `__main__` try/except KeyboardInterrupt/finally 接线；②日志过滤对 TG setup/poll 失败全栈**全量丢弃**（`_POLL_FAILURE_STATE` 计数）；③`configure(job_defaults={"misfire_grace_time": 30})` 在 load_from_toml 后、start 前窗口补设；④`_early_shutdown_scheduler_stop` 早于插件钩子关 apscheduler（治 kb_wiki_sync 停机 CancelledError 与排队 job 拖停机）；⑤注册 ResilientTelegramAdapter |
| sender/onebot.py | **P2 完成** | retcode=1200 三种失败形态（_ChunkRejectedError 属性形态/ActionFailed .info dict 形态/失败回执 dict 形态）全部改返 `_bot_unavailable_receipt`（FAILED_RETRYABLE + kind=bot_unavailable），不再终态丢消息；`_exception_platform_rejection` 鸭子探测（.info.retcode，nonebot 2.5.0 无 .retcode 属性实证入注释）；其余 retcode 语义零变化（-1 可重试/403 终态回归锁） |
| sender/worker.py | **P2 完成**（媒体文本降级为 09-15 历史批次 WIP，非前任） | `_notify_operational_issue_safely` 对 kind=bot_unavailable 静默跳过管理员告警（DEBUG 一行），抑制面不扩大 |
| mail_adapter.py | **P3 完成** | 新增 `search_unseen_with_backoff`（wait_for 15s 硬超时+同连接 2s 退避重试一次→耗尽抛回外层整链重连）；`_fetch_new_mail` 接线；a3e78a3 重连清早退缓存契约由 AST 测试钉死 |
| tests/test_v21r2_lifecycle_r2.py | **已产出，5 处测试自身缺陷致红** | 实跑 16 passed/5 failed，红因全在测试不在实现（见下） |

queue.py 的 B-4 bot_unavailable 挂起语义（不消耗重试预算/90s 慢速重探/年龄上限终态）为既有代码，前任未改也无需改。

## 二、本席修复（只补未完成部分）

5 处红全部是测试文件自身缺陷 + bot.py 一处 ruff S110，实现层零改动：

1. **test_p2 e2e checked=0**：submit 未传 `deliver_after`，撞上队列 60s 内联认领宽限期（`_INLINE_DELIVERY_GRACE_SECONDS`），drain 在 base+5s 认领不到行 → 补 `deliver_after=base`（声明无内联首投）。
2. **test_p2_alert_channel NameError**：`DeliveryReceipt` 用了没导入 → 补 contracts import。
3. **test_p2_onebot_sleep AttributeError**：asyncio 影子补丁只有 sleep，实现路径的 `wait_for`/`CancelledError` 落空 → 改完整 ModuleType 影子（复制真 asyncio 全部公开属性，仅换 sleep）。
4. **test_p5 anchor 偏移**：`source.find("if __name__ ==")` 命中前部 supervisor 分叉块（`... and _supervision_requested():`）→ 精确锚 `'if __name__ == "__main__":'`（该子串对分叉块不匹配）。
5. **test_p1 args 位错**：warning 调用参数序为（格式串, phase, failures, 类型名, delay），断言应读 `args[2]` → 已改并注释。
6. **bot.py S110（try-except-pass）**：misfire configure 块 except 补 `nonebot.logger.debug` 一行。
7. 测试文件 ruff 卫生：删未用 `worker_module` import、`_OkResponse.lines` 改 ClassVar、删失效 noqa 占位行。

## 三、实跑证据（直跑纪律：ChatBot_Runtime venv + PYTHONDONTWRITEBYTECODE=1 + basetemp，禁 dev.ps1）

```
# 修复前基线（前任遗留态）
tests/test_v21r2_lifecycle_r2.py            → 5 failed, 16 passed
# 修复后
tests/test_v21r2_lifecycle_r2.py            → 21 passed
域内回归 15 文件（sender×5/mail×2/telegram×2/supervisor×2/startup×2/queue 等）
                                            → 111 passed, 3 xfailed
核心域合跑（R2+mail+nonebot_sender+tg_resilience+bot_supervisor）
                                            → 66 passed
ruff 本域 6 文件                             → All checks passed
mypy（dev.ps1 同参：--explicit-package-bases --ignore-missing-imports plugins）
                                            → Found 2 errors（均 control_plane/api/platform.py 既有在飞批，
                                              AGENTS.md 已记录；mail_adapter/sender.* 零错）
py_compile bot.py + 全域 4 文件               → OK
```

## 四、任务清单对账（6/6 全闭合）

1. ✅ TG setup 失败降噪：resilience 层一行告警（前3逐条→每5一条→恢复单条）+ bot.py 全栈全量丢弃。
2. ✅ QQ retcode=1200 挂起：onebot 三形态改 bot_unavailable 挂起 + worker 管理员告警静默 + queue B-4 既有语义（90s 重探/不烧预算/30min 年龄上限）。
3. ✅ mail UNSEEN 超时：15s 硬超时+2s 退避重试→耗尽抛回整链重连；a3e78a3 清缓存契约 AST 锁死。
4. ✅ Ctrl+C 60s+：`_reap_background_threads`（默认 10s 宽限，滞留非 daemon 线程强制收尾；异常路径让位真实退出码）+ asyncio.sleep 天然可取消（mail/onebot 两测试钉死）+ KeyboardInterrupt 归零退出码（supervisor 视为人工停止）。
5. ✅ apscheduler misfire：job_defaults misfire_grace_time=30（load 后 start 前窗口；job 显式 120/300/3600 不受影响）。
6. ✅ kb_wiki_sync 停机：bot.py 侧 `_early_shutdown_scheduler_stop`（FIFO 抢跑插件钩子，shutdown(wait=False) 取消排队/在跑 job），无需动 __init__.py。

## 五、遗留与移交

- **给 R5 的坐标（仅在 bot.py 侧缓解不彻底时备查）**：`plugins/bot_unified_runtime/__init__.py:1787` `_register_kb_wiki_sync_scheduler`；job 体 `_sync_job`（1795-1816，`except Exception` 不会捕获 CancelledError，停机报错大概率来自 apscheduler 执行器层）；`kb_wiki_sync_startup` 注册于 ~1841（date 触发器 run_date=start+45s、misfire_grace_time=300）。本席 bot.py 早停钩子已先于插件钩子 cancel 全部 job；若真机重启后仍有执行器层 CancelledError 刷屏，再考虑在 `_sync_job` 外层补 BaseException 兜底或改 run_kb_sync_task 内部停机检查点（均属 R5 域）。
- 旧 `_resilient_tg_poll` monkey-patch 已被前任删除（bot.py diff 中），`TelegramAdapter.poll` 不再被就地改写，改走子类注册——重启后行为变化点。
- bot.py `_POLL_FAILURE_STATE` 的 mypy 推断噪音（int|None）为前任之前既有模式且 bot.py 不在项目 mypy 门内（门=plugins/），未动。
- 未跑全量套件（共享工作树多席在飞，全量含他席在途红，跑之无判定力）；本域判定力由上述 5 组实跑承担。
- 真机验收（重启后）：TG 断网只出一行告警；NapCat 未连启动期队列静默挂起、连接恢复后补发（next_retry_at≈+90s）；Ctrl+C ≤ ~10-15s 退出；无 missed by 0:00:01 刷屏。

## 六、FIX 席收口记录（微修席，接 R1/R5 双席移交）

**收口对象**：存量孤儿红 `tests/test_operational_failures.py::test_queue_worker_notifies_typed_failure_without_blocking_state_update`（R1 续跑席与 R5 席双双实跑确认与本席改动零交集移交）。

**裁决**：新行为系本席（R2）设计意图，测试期望未同步，非代码缺陷——`sender/worker.py:347` `_notify_operational_issue_safely` 对 `kind == "bot_unavailable"` 精确短路（DEBUG 留痕 + 跳过管理员通知，防 NapCat 未连启动期成批挂起刷屏；队列审计 `send_deferred_bot_unavailable` 行承载可见性）；判定门按 kind 精确匹配，**未误伤其他类型**：`transport_exception`/`provider_failed` 等仍照常通知（后者覆盖见同文件 `test_pipeline_helper_notifies_issue_before_successful_transport_replacement`，kind=provider_failed）。**worker.py 零改动**。

**改动**（仅 tests/test_operational_failures.py）：
- 测试改名：`test_queue_worker_notifies_typed_failure_without_blocking_state_update` → `test_queue_worker_bot_unavailable_failure_skips_admin_notification_without_blocking_state_update`；
- 测试顶部补 R2 语义注释（挂起语义/静默边界/非 bot_unavailable 仍通知的交叉引用）；
- 断言 `notified == [transport_receipt]` → `notified == []`（bot_unavailable 挂起时 notifier 零调用），`retryable_failed == 1` 状态机断言保持不变——「静默但不阻塞状态机」的原始测试意图由新名+注释+断言组合自解释，非无脑翻转。

**实跑证据**（固定 venv 解释器，PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，--basetemp=%TEMP%/v21r2-fix -p no:cacheprovider）：
- 修前单测复现红：`AssertionError: assert [] == [DeliveryReceipt(...)]` @ tests/test_operational_failures.py:985（1 failed in 1.59s）——红点精确落在通知断言，`retryable_failed == 1` 断言通过，与静默化语义逐字吻合；
- 修后 tests/test_operational_failures.py 全量：**40 passed**（2.13s）；
- worker 域相邻回归 7 文件（a03_timeout_retry_semantics/a20_sender_session_order/a22_inline_claim_race/media_rejection_retry_and_fallback/nonebot_sender/part_idempotent_resume/v21r2_lifecycle_r2）：**71 passed**（1 warning=mail 适配器 pydantic 弃用既有提示，与本改无关）；
- ruff tests/test_operational_failures.py：All checks passed。

零 git 写操作、sender/*.py 只读未动、未 commit。
