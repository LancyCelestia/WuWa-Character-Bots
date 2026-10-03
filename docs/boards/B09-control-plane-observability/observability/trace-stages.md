# 日志·指标·Trace·审计 · 轨迹阶段与脱敏

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 轨迹阶段与脱敏

- 层级：一级 B09 → 二级 observability → 三级 `trace-stages`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`、`plugins/bot_unified_runtime/domains/ops/host_snapshot.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

一条请求走过哪些阶段、各花多久、留下了什么可审计的痕迹——这一面负责把主链路的执行
轨迹变成**固定阶段名 + 耗时 + 脱敏记录**，供诊断卡、审计查询与事后复盘消费。立场有两条：
同一请求共用一个单调时钟预算（各阶段只能消费剩余、不能各自重新计时）；轨迹只记结构，
不记用户正文。

## 怎么调用

- **预算与相位**：`domains/chat_reply/runtime/deadline.py::DeadlineBudget`——由 chat 能力
  按请求装配（预算秒数取 `config.py::Config.bot_request_budget_seconds`，缺省值以该字段
  为准；`<=0` 表示未启用，全部门控退化为无操作保持旧行为）。`record_phase(stage, started_at)`
  归账、`mark_in_flight(stage)` 标注「预算到期那一刻哪一段在跑」；阶段名只接受
  `_safe_phase_name` 通过的固定字面量（小写字母开头的短标识），未通过或不标注则诚实降级
  为「未记账」。现记相位名以 `domains/chat_reply/capabilities/chat.py` 各 `record_phase(`
  调用点现算为准（检索/视觉/ASR/上下文/LLM/工具循环等段各有归账点），本页不抄清单。
- **轨迹出口**：`deadline.py::phase_tags(budget)` 把 `phases_ms` 刷成审计标签
  `phase_<stage>_ms` 与 `phase_total_ms`，随能力结果标签进诊断卡与审计行（2026-09-23
  停摆波补上「算了却从不落盘」的这段）。预算耗尽抛 `DeadlineExceeded`，稳定错误
  kind=`deadline_exceeded`，**不可自动重试**。
- **审计落痕**：`domains/ops/audit/logger.py` 定义 `AuditRecord` 的仓库协议与脱敏真身
  `redact_private_debug`；`domains/ops/audit/file_logger.py::TeeAuditRepository` 把每条
  脱敏审计记录追加到 JSONL（超限轮转保留最近两代，不开数据库也能 tail 排查）。
- **结果未知对账**：`domains/ops/monitor/result_unknown.py` 把 OneBot 发送超时的
  result-unknown 持久化，重连时写 `result_unknown_reconciled` 事件、超 TTL 标 `expired`，
  保留人工排查入口（UNKNOWN 分片确认器在 `domains/transport/sender/onebot.py`）。
- 决策侧影子轨迹（B02 的 decision shadow）另有持久化，见 `tests/test_decision_trace_persistence.py`
  所钉的口径，归属 B02，本页不重画。

## 开关与参数

- `bot_request_budget_seconds`（Config 字段，装配期读取，改后重启生效）；整链 LLM 预算
  `bot_chat_failover_max_seconds` 在 model_router 侧另账（见 B09.model-control）。
- 审计文件：`BOT_AUDIT_LOG_FILE`、`BOT_AUDIT_LOG_MAX_BYTES`（缺省值以 `file_logger.py`
  与 `docs/config-catalog-full.md` 为准）。
- 无「关掉轨迹」的用户开关：相位记账随预算启用与否自然退化；审计脱敏零例外、不可关。

## 失败时看到什么

- 相位名不过安全判据 ⇒ 该段不进 `phases_ms`（宁缺毋假），`in_flight_stage` 留空串；
  用户内容进不了标签名（判据只收固定字面量）。
- 脱敏防线：`audit/logger.py` 的键值密钥正则按「含标识符字符的整词」匹配（历史教训 H7：
  旧 `\b(token|…)` 对 `access_token=` 失配致明文入审计），覆盖 sk- 形态、盘符路径、
  `BOT_XXX=`、Bearer/JWT；用户派生文本必须走专门参数、只保留「已隐去 N 字」痕迹。
  脱敏器自身抛错 ⇒ 丢弃该值（fail-closed），绝不因脱敏失败而泄漏。
- 发送结果未知 ≠ 失败：账本 pending 期间不重发不谎报，等对账或 TTL 过期。

## 测试与验收

`tests/test_deadline_budget.py`、`tests/test_deadline_phases.py`、
`tests/test_deadline_phase_accounting.py`（预算/相位归账/`phase_tags` 落盘，含 LLM 相位
迟于归账的活性锁）、`tests/test_audit_fixes_b.py`（审计脱敏形态）、
`tests/test_result_unknown.py` 与 `tests/test_decision_trace_persistence.py`（对账与
影子轨迹）。用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准。真机（重启后）：
发一条会走检索的长消息，触发一次能力失败，确认诊断卡/审计行里 `phase_*_ms` 标签齐且
不含用户正文与本机路径。
