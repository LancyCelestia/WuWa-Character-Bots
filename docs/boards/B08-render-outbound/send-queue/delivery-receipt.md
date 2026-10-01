# 发送队列与回执 · 回执与对账

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.send-queue · 回执与对账

- 层级：一级 B08 → 二级 send-queue → 三级 `delivery-receipt`
- 实现落点：`plugins/bot_unified_runtime/domains/transport/sender/__init__.py`、`plugins/bot_unified_runtime/domains/transport/sender/failure_class.py`、`plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py`、`plugins/bot_unified_runtime/domains/transport/sender/gateway.py`、`plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`、`plugins/bot_unified_runtime/domains/transport/sender/queue.py`、`plugins/bot_unified_runtime/domains/transport/sender/receipts.py`、`plugins/bot_unified_runtime/domains/transport/sender/timeout.py`、`plugins/bot_unified_runtime/domains/transport/sender/worker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「这条消息到底发出去了没有」变成一个可对账、可追溯、且绝不靠猜来重发的事实。渲染完成的一条 `SendRequest` 进队列、经 worker 投递后，都会产出一条 `DeliveryReceipt`（投递回执）——它是发送侧唯一的结果凭据。本入口管两件相邻但不同的事：回执账本（`domains/transport/sender/receipts.py`）回答「我这边记了什么状态」，结果未知账本与重连对账（`domains/ops/monitor/result_unknown.py`）回答「拿不到确定结果时怎么留痕、怎么在重连时收口」。

回执分两层：请求级 `state`（`ReceiptState`，如 `SENT`/`FAILED_RETRYABLE`/`FAILED_FINAL`/`SKIPPED`/`BLOCKED`）与 part 级进度（长回复 `chunks`、语音混排 `mixed` 逐段记账）。核心不变量是「宁停在断点，也绝不重发可能已送达的一段」——重复投递比短暂延迟更不能接受。

## 怎么调用

构造与落账都发生在 sender 侧与根装配层，不由能力层显式调：

- 取数口 `build_receipt_repository(config)` 决定仓库实现：`bot_receipts_enabled` 且 `bot_receipts_db_path` 非空 ⇒ `SQLiteReceiptRepository`（表 `delivery_receipts`，按 `debug_id` 冲突覆盖写、`_prune` 裁到 `max_items`），否则 `InMemoryReceiptRepository`（有界 FIFO、`max_receipts`）。两实现同一契约 `record`/`latest`/`find`/`list_receipts`，工厂对调用方透明；带 `operational_issue` 的回执其 `public_message` 落库前置空（对外文案与运维细节分离）。
- 投递主循环 `drain_send_queue_once(send_queue, transport, ...)`：`claim_due`（带 `lease_seconds` 领取租约）取到期条目 → 交 `transport` → 依回执状态回写队列（`mark_sent`/`mark_retryable_failure`/`mark_final_failure`/`mark_partial`）→ `receipt_repository.record` → 逐事件写审计（`queue_worker_sent` 一类）。内存队列不实现 part 存储 API 时，整条 part 语义自动关闭、退回请求级整发。
- 结果未知记账在根装配：运维回执带 `kind=result_unknown` 时 `result_unknown_ledger.record(...)` 落一台线程安全、纯本地的 SQLite 账本（表 `result_unknown`，按 `request_id` 幂等）。

## 开关与参数

- 回执账本三键 `bot_receipts_enabled`/`bot_receipts_db_path`/`bot_receipts_max_items`：共同决定「落 SQLite 还是退回内存」，缺省为关（内存形态重启即清空、进程内常驻有界），逐键缺省以 `config.py` 三字段为真身；改属管理员动作、改码需重启。
- 「协议端不在线」挂起回执的年龄上限 `bot_send_bot_unavailable_max_age_seconds`（缺省值以该字段为真身），超龄自动清理；同族 `bot_send_queue_*`（条目上限、最大尝试次数、退避底/顶秒数）见 `config.py`。
- 结果未知账本不是配置面：TTL 参数 `expire_seconds` 与清理窗口 `purge_after_seconds` 是 `ResultUnknownLedger` 的构造参，`pending` 行永不清理、只标 `expired`；动这些属改码。
- 在途饱和告警（A-20 busy 可见）走 `AdminAlertSuppression` 的 `(stage, kind)` 抑制键，只进管理员通道、绝不向原会话补发（群聊刷屏红线），窗口与其余运维告警同源。

## 失败时看到什么

按「结果能否确定」分层，全部 fail-toward-safe：

- 网络/超时类失败 ⇒ 回执 `FAILED_RETRYABLE`，按退避安排 `next_retry_at` 续投；尝试烧尽落 `FAILED_FINAL`。
- 发出后拿不到明确结果 ⇒ 该 part 记 `UNKNOWN`、队列行置断点态 `PARTIAL`，并发出带 issue 的终态回执。§9.3 UNKNOWN 确认协议只在注入了确认器时才推进：确认器回「已送达」才标 `SENT`、回「确未送达」才回 `PENDING` 允许重发、回「无法确认」则保持 `UNKNOWN` 绝不盲发；生产缺省确认器为 `None`，故这类断点停在 `PARTIAL` 等人工或平台确认，靠慢速补偿扫描续发、零进展则休眠防空转。`get_msg` 在 SnowLuma 侧真机取证前，确认器只可能给「已送达 / 无法确认」两态、绝不判「未送达」。
- 重连对账：bot 连接时对 `result_unknown` 账本跑 `reconcile`，把超 TTL 的 pending 标 `expired`、顺带清理过期行；仍有 pending/expired 即落一条 `result_unknown_reconciled` 观测事件（人话摘要含按 bot 分布的计数）。它只留痕与提示、绝不自动重发——发送超时恰恰意味着拿不到 `message_id`，账本里没有可反查的把手，盲发=重复投递风险大于漏发。
- 媒体终败仅在平台明确拒绝（`retcode_failure`）时一次性回退纯文本降级（派生 `-textfb` 子请求、内容寻址幂等）；`result_unknown` 形态绝不降级。回执 `record` 失败只记审计、不影响已发生的发送。全链异常经主链路旁路走诊断卡并降级纯文本，见错误报告功能页。

## 测试与验收

行为锁（全离线）：`tests/test_result_unknown.py`（账本记录去重、过期标记、TTL 清理与重连对账摘要）、`tests/test_a03_timeout_retry_semantics.py`（退避重试与终态收敛）、`tests/test_part_idempotent_resume.py`（part 级断点续发、UNKNOWN 不盲重投）、`tests/test_media_rejection_retry_and_fallback.py`（明确拒绝才文本降级、result_unknown 不降级）、`tests/test_operational_failures.py`（issue 透传与告警面）、`tests/test_a22_inline_claim_race.py`（领取租约并发）、`tests/test_delivery_verification_tier1.py`（结果未知确认器）。全量门禁 `dev.ps1 -Task test`（用例数以最近一次实跑输出为准，本文不手写；文件清单见生成物 `docs/auto-facts.md`）。

真机（重启后）：在断连窗口里发一条会被切成多 part 的长回复，观察重连后 `result_unknown_reconciled` 是否出现在运行事件账、`PARTIAL` 断点未被盲目重投；按 `docs/acceptance-manual.md` 的发送/回执条目走。
