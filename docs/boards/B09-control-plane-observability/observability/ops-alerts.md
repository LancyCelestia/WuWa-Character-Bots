# 日志·指标·Trace·审计 · 运维告警与抑制

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 运维告警与抑制

- 层级：一级 B09 → 二级 observability → 三级 `ops-alerts`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor`、`plugins/bot_unified_runtime/control_plane/metrics.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「线上出了不该没人知道的事」变成一条发给管理员的预警。每条预警固定讲清五要素：出了什么错（what_happened）、影响在哪（impact）、怎么解决（fix_suggestion）、发生时间（occurred_at，精确到秒）、位置（location，模块/阶段/会话）。同时压掉重复风暴，避免同一故障刷屏。

## 怎么调用

`domains/ops/monitor/alerts.py::notify_operational_issue(issue)` 消费 `OperationalIssue`，先用 `build_operational_alert_text` 组文案、`build_admin_alert_send_request` 造投递请求，交给统一出站链走 `SendRequest → DeliveryReceipt → AuditRecord`，不绕过审计；出站前对文本施加 `domains/render/plain_text.py::redact_local_secrets`（本机路径/密钥打码），LLM 链路细节由 `_compress_llm_chain_detail` 收成短摘要。收件人取 `BOT_ADMIN_USER_IDS`；控制台模式下不发 QQ、直接打印。相关采集与指标侧在 `domains/ops/collectors`、`domains/ops/audit`、`plugins/bot_unified_runtime/control_plane/metrics.py`。

## 开关与参数

抑制器 `alerts.py::AdminAlertSuppression`：按 `_issue_key`（同一 issue 的身份键）在滑动窗口内去重，窗口 `window_seconds` 缺省 300 秒；命中抑制时 `AdminAlertDispatchResult.suppressed=True` 并累计 `suppressed_count`，恢复放行时把「期间被压掉多少条」写进同一行告警（`build_operational_alert_text` 的 `suppressed_count=…`）。`last_report_kinds_for_issue` 供重连/对账场景判断上次报的是哪类。管理员名单是配置面键（`BOT_ADMIN_USER_IDS`），谁能收由它决定。

## 失败时看到什么

管理员收到的是守岸人语气可读的短预警，含上述五要素与打码后的位置/细节。设计取向是「宁可聚合也不静默」：抑制只压重复、不吞首条；同一 issue 恢复时带被抑制计数。落库/审计失败不改变预警本身是否发出。真机排查时注意：告警文案里的路径与凭据已被打码，看不到原始值属预期。

## 测试与验收

`tests/test_operational_failures.py`（五要素齐备、抑制窗口与 suppressed_count、走统一出站不绕审计、出站前打码、控制台分支）。真机（重启后）：制造一次可控能力失败，确认管理员私聊收到含五要素的一条预警、无盘符路径/密钥泄漏；短时间重复触发同一故障，确认第二条被抑制且后续恢复告警带被压计数。
