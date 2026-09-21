# 提醒督促 · 投递、顺延与作废

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.reminders · 投递、顺延与作废

- 层级：一级 B07 → 二级 reminders → 三级 `delivery-and-lateness`
- 实现落点：`plugins/bot_unified_runtime/domains/schedule`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

到点提醒的投递与"错过之后怎么办"这一层（机制件，不占路由席位）。它每分钟被调度器唤起一次：把到点的提醒取出来、生成守岸人语气的督促文案、投进统一发送队列并就地送达；对来不及投递的提醒做迟到治理——**迟到超过 30 分钟顺延、超过 24 小时作废**，并把顺延/作废各折成至多一句治理回执主动告诉用户，不静默。

## 怎么调用

存储侧真身 `domains/schedule/store/reminders.py:ReminderStore.due`（迟到三态 + `_build_governance_receipts`），到点文案 `...:build_reminder_text`（按 `classify_reminder_kind` 分 吃药/约会出行/购物/待办/自定义 五型切换模板）。调度与投递真身在根 `__init__.py:_deliver_due_reminders`（由 `_register_reminder_scheduler` 每分钟唤起）：`store.due()` → 构造 `SendRequest(capability_id=bot.reminder)` → `send_queue.submit` → **内联投递**，拿到 `SENT`/`REDIRECTED` 回执才 `mark_done` 销账；投递失败不销账、下一轮重投（重投前先查回执仓，SQLite worker 若已在宽限期后送出则直接销账，防双发）。

## 开关与参数

提醒总闸 `bot_reminder_enabled`（缺省 True）关时整条投递链不注册。迟到容忍窗是常量 `LATE_DELIVERY_GRACE=30 分钟`、作废阈值 `grace_hours=24`（`due()` 形参，非配置键）；单会话待办上限 20。回执节流：同一会话一轮治理扫描至多一条，群聊多条错过也不刷屏。

## 失败时看到什么

- 正常到点（迟到 ≤30 分）：收到督促文案；文案对 `gov-` 前缀的合成回执原样放行，不会被分型模板二次包装。
- 迟到 >30 分未超 24h：真提醒顺延到下一个同一时刻（宁可晚一天也不在错误时点打扰），另收一句「我把它挪到了明天同一个时刻」的顺延回执。
- 迟到超 24h：真提醒标 `expired` 作废，收一句「隔得太久了…先替你放下」的作废回执。
- 无在线 bot / 投递异常：只记一行 `kept for retry` 日志，绝不抛出影响主链路，下一轮再投。

## 测试与验收

`tests/test_reminder_delivery.py`（内联投递与回执销账/重投）、`tests/test_reminder_governance_receipt.py`（顺延/作废三态与回执）；调度器注册与 cron 口径见 `scheduled-jobs/README.md`。
