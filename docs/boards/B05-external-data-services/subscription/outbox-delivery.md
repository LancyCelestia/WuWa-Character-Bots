# 订阅与更新推送 · 更新出队与投递

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.subscription · 更新出队与投递

- 层级：一级 B05 → 二级 subscription → 三级 `outbox-delivery`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe`、`plugins/bot_unified_runtime/sources/subscriptions`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

"有新条目"到"真的送到每个目的地"之间的那段路：候选条目进 outbox，按目的地逐条投递、逐条记账，失败退避重试，超上限进死信。**一个事件多个目的地时，不能因为第一个投成功就把第二个当已投**。

## 怎么调用

- 队列与账本真身：`domains/subscribe/store/subscription_store_v2.py` —— 表 `subscription_outbox`（状态机）与 `subscription_outbox_deliveries`（逐目的地结果），读点 `record_outbox_deliveries(...)` / `outbox_undelivered_destinations(...)`（及各自的 `*_async` 门面，遵守"存储离环"约定：工作线程里不注入 async 回调）。
- 出队：`domains/subscribe/store/subscription_scheduler.py:SubscriptionScheduler.deliver_outbox_once(*, limit=20)`，由 B07 调度器按 `bot_subscribe_outbox_interval_seconds` 周期驱动；平台节流与退避状态在 `PlatformThrottle`。
- 渲染与发送：卡片走 `domains/link_parse/capabilities/content_parser.py:build_subscription_push_capability` / `render_subscription_push_card`（复用解析卡管线），投递经 B08 的发送队列（`review → renderer → send_queue → sender`），本层不自建 transport。
- 投递函数由装配注入：`build_subscription_runtime_v2(config, delivery_fn=..., context_factory=...)`。

## 开关与参数

- `bot_subscription_outbox_max_attempts`：单条最大尝试次数，超限进死信并告警（阶段名 `subscription_outbox_dead`）。
- `bot_subscription_outbox_sending_stale_seconds`：`sending` 状态超过此时长视为掉线，允许被重新领取（防进程崩溃把一条卡死在"正在发"）。
- `bot_subscription_outbox_sent_retention_days`：已发送行的保留期（只留近期供排障）。
- `bot_subscription_seen_retention_days`：已见条目去重记录的保留期，**故意大于 outbox 保留期**（否则同一事件在保留期外会被再次推送）。
- 逐键含义以 `docs/config-catalog-full.md` 为准。

## 失败时看到什么

- 单目的地失败：其余目的地继续，失败那条进退避重试；用户看不到"半成品"消息。
- 超过最大尝试：停止重试、进死信面并冒一条管理员告警；订阅本身不被删除（下轮新内容照常能推）。
- 渲染失败：降级为纯文本推送（内容与卡片文字版一致）。
- 全通道不可用：条目留在 outbox，不吞、不假装已投；重启后凭账本续投。

## 测试与验收

离线：`tests/test_subscription_outbox_reliability.py`（部分失败、重领取、退避上限、保留期不重复推）、`tests/test_subscription_delivery_v2.py`、`tests/test_subscription_runtime_delivery_v2.py`、`tests/test_subscription_scheduler_v2.py`、`tests/test_subscription_card_push.py`、`tests/test_h_dedupe_content_key.py`（内容级去重键）。
真机：同一事件两个目的地（一个群 + 一个私聊）时两条都到；制造一次失败（关掉目标会话可达性）后恢复，观察是否只补投未到的那一条；死信只在管理员告警面出现，不打扰用户。
