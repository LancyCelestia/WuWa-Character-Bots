# 调度器族与定时推送 · 发送队列驱动

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 发送队列驱动

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `send-queue-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

发送队列的驱动器（worker）：周期性地把排队中的消息取出来、交给传输层真正发出去，并记录送达回执。它是 B08 统一出站链的"腿"——队列与幂等归 B08，本调度器只负责"隔一段时间去抽一批、投递、防自旋"。

## 怎么调用

真身 `__init__.py:_register_send_queue_scheduler`。它 `scheduler.add_job` 一个 interval 任务（job id `bot_send_queue_worker`，`max_instances=1`、`coalesce=True`、`misfire_grace_time=30`），每轮调 `drain_send_queue_once`：按批次取条目，用 `transport` 依适配器分流（onebot 走 `send_onebot_v11`，其余走 `send_nonebot_message`），写回执仓与审计。B4b Tier2-b 的"未知件确认器"仅在 `bot_outbound_verify_enabled` 开时接入，关时传 `None` 与不传等价。

## 开关与参数

- `bot_send_queue_worker_enabled`（缺省 False）：关则整 worker 不注册。`bot_send_queue_worker_interval_seconds`（缺省 30）、`bot_send_queue_worker_batch_size`（缺省 20），都下限钳到 1。
- 队列本体（是否持久化、幂等、断点续发）归 B08.send-queue：`bot_send_queue_enabled` 关时是内存队列，重启丢在途消息（装配期会如实告警一次）。

## 失败时看到什么

选不到在线 bot 时返回 `bot_unavailable` 回执、条目留队；网络/协议异常由 B08 的 part 级幂等与 UNKNOWN 确认机制处理，不在此吞。APScheduler 插件不可用时，若 `bot_send_queue_worker_enabled` 开着，会落一条 `send_queue_scheduler_unavailable` 审计记录。

## 测试与验收

投递与回执、队列持久化的契约归 B08.send-queue 测试族；worker 侧直接相关的是 `tests/test_startup_queue_warning.py`（内存队列启动如实告警）与 `tests/test_queue_poison_row.py`（毒行不带走整轮 drain）。跨时区不影响本任务（interval 相对触发）。
