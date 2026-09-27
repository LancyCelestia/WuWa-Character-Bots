# 发送队列与回执 · SQLite 队列与恢复

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.send-queue · SQLite 队列与恢复

- 层级：一级 B08 → 二级 send-queue → 三级 `queue-persistence`
- 实现落点：`plugins/bot_unified_runtime/domains/transport/sender/__init__.py`、`plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py`、`plugins/bot_unified_runtime/domains/transport/sender/gateway.py`、`plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`、`plugins/bot_unified_runtime/domains/transport/sender/queue.py`、`plugins/bot_unified_runtime/domains/transport/sender/receipts.py`、`plugins/bot_unified_runtime/domains/transport/sender/timeout.py`、`plugins/bot_unified_runtime/domains/transport/sender/worker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把待发消息持久化进队列、按 part 记录投递进度、崩溃或断连后按断点续发。输入是一条 `SendRequest`，产出是 `DeliveryReceipt`（排队即先给一条「已入队」回执）。它只在配置开启且给了库路径时才用 SQLite 落盘，否则退回内存队列——内存形态重启即清空。

## 怎么调用

契约是 `domains/transport/sender/queue.py::SendQueue`（Protocol：`submit` / `find_request` / `safe_summary`），统一由 `build_send_queue(config, audit_logger)` 构造，返回 `SQLiteSendRequestQueue` 或 `InMemorySendQueue`。SQLite 队列把每条请求封成 `QueuedSendRequest`（带 `state`、`retry_count`、`next_retry_at`、`lease_expires_at` 领取租约），并把长回复拆出的 part 以 `PartRecord` 逐条落 `send_request_parts` 行、聚合成只读快照 `PartProgress`（`delivered`/`pending_indexes`/`unknown_indexes`）。part 键由 `_part_key(request_id, part_index)` 生成，幂等靠 dedupe key + payload 摘要。主动消息不直调 `submit`，走 `submit_active_push`（见 outbound_gate）。

## 开关与参数

`bot_send_queue_enabled` 与 `bot_send_queue_db_path`（两键缺省态以 `config.py` 双字段为真身）共同决定是否落 SQLite，任一不满足即走 `InMemorySendQueue`（持久能力随之关闭，这是缺省形态不是降级）。开启后：`bot_send_queue_max_items`、`bot_send_queue_max_attempts`、`bot_send_queue_retry_base_seconds`/`bot_send_queue_retry_max_seconds`（五键缺省值以 `config.py` 五字段为真身）控制容量与退避重试，`bot_send_bot_unavailable_max_age_seconds`（缺省 1800）给「协议端不在线」挂起回执的年龄上限、超龄自动清理。键名以 `build_send_queue` 函数体与 `config.py` 为准，逐键详情见目录册；改配置属管理员动作，热改需重启。

## 失败时看到什么

网络类失败置 `FAILED_RETRYABLE` 并按退避安排 `next_retry_at` 重试；耗尽尝试次数落 `FAILED_FINAL`。SQLite 里读到损坏行抛 `_CorruptQueueRow` 由上层隔离处理，不带走整表。§9.3 UNKNOWN 确认协议：某 part 发出后拿不到明确结果时标 UNKNOWN，若未注入确认器（生产缺省 None）则绝不盲发重投，停在 PARTIAL 等人工或平台确认——重复投递比短暂延迟更不能接受。

## 测试与验收

队列容量/淘汰、退避重试、part 级断点续发与损坏行隔离的用例以仓库 `tests/` 相应件为准（清单见生成物 `docs/auto-facts.md`）；真机断连恢复属主链路 send_queue 段，重启后按 `docs/acceptance-manual.md` 验收。
