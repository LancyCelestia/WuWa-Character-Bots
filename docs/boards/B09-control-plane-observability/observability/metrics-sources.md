# 日志·指标·Trace·审计 · 指标结构化来源

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 指标结构化来源

- 层级：一级 B09 → 二级 observability → 三级 `metrics-sources`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「bot 现在跑得怎么样」变成一组**结构化、只读、有界**的数字来源：账本统计、进程与
宿主机资源、模型用量与成本、外部协议端日志。每个来源各自回答一类问题，共同纪律是
「未知不是 0」——取不到就标 `unknown`/`source_unavailable`，绝不伪造零值。

## 怎么调用

各来源真身与消费口：

- **账本统计**：`control_plane/metrics.py::LedgerMetricsService`（`overview`/`models`/
  `providers`/`sessions`/`trends`/`token_families`）——只读适配 `llm_call_records`，
  不初始化 ledger、不解析 attempts、不触碰运行配置；模型按 `actual_model` 分组，不用
  渠道 `model_id` 冒充真实模型；每块 token 带 `known_rows/unknown_rows/quality`
  （complete/partial/unknown）；会话标识用进程内随机密钥 HMAC，不输出原文；旧
  provider 字段整体标 `provider_identity_quality=legacy_unverified`。
- **进程资源**：`control_plane/resources.py::ResourceMetricsService.snapshot()`——按需
  采样、CPU 按累计 user+system 时间除以 monotonic 窗（单核口径、多核可超，缩放真身
  以该服务为准），首发/故障后
  先预热再出数；无后台线程、无目录扫描、无数据库写入；HTTP 与 CLI 共用同一服务。
- **宿主机读数**：`domains/ops/host_metrics.py` 是**唯一取数真身**（CPU/GPU 标签读
  winreg、psutil 采样、disk_usage），呈现件 `domains/ops/monitor/host_status.py`、
  `host_card.py` 反过来 import 它——双真身已于 2026-09-26 收敛，回潮由
  `tests/test_host_metrics_single_source.py` 拦。
- **用量与成本监控**：`domains/ops/monitor/usage_monitor.py`——数据源是运行事件日志中
  成功调用的 `transport_receipt` 行（输入/输出/缓存命中/缓存创建 token 与当时价格的
  `cost_milli`）；实时阈值巡检与定时账单报告，阈值与报告时点走 `BOT_USAGE_*` 键
  （缺省值以该件 docstring 与 `docs/config-catalog-full.md` 为准），报告状态落
  `BOT_USAGE_REPORT_STATE_FILE` 重启不丢。
- **外部协议端日志**：`domains/ops/collectors/snowluma_tail.py`——SnowLuma 是独立进程，
  只能 tail 其日志文件；pull 式 `poll_once()` 由接线席周期驱动，含轮转识别、行级脱敏、
  级别归一、背压丢弃诚实计数；不自带线程、无装配副作用。
- **联网意图遥测**：`domains/ops/monitor/intent_telemetry.py`——只保存哈希、决策与结果
  统计，不保存完整用户原文（开关 `bot_web_intent_telemetry_enabled`）。

HTTP 消费口在 `control_plane/api/v1.py` 的 `/api/v1/metrics/*`（`metrics_service` 未注入
时该面直接不可用，不返回假数据）。

## 开关与参数

- 配置键前缀登记为 `bot_alerts_`、`bot_metrics_`；用量报告另有 `BOT_USAGE_*` 一族。
  逐键语义与热更性以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准。
- 分页/排名参数一律有界（如 `limit` 的允许区间写在端点签名与适配器判据里），越界即
  422/`invalid_request`，不静默截断总计。
- 谁能改：这些是只读面，没有「改指标」的开关；能改的只有采集开关与阈值键，属管理员配置面。

## 失败时看到什么

每个来源的失败都是**显式三态**而非零值：账本适配器失败只回
`{status: source_unavailable|invalid_request, reason: 固定代码, data: None}`；有 token
无已知记录时 value 为 `None` 并标 `quality=unknown`；attempt 数恒标未知（一行账本只代表
一次已记账 generate，不代表网络 attempt）；无效时间戳记 `unknown_timestamp_calls` 并保留
`bucket_start=None` 的未知桶。tail 采集器总线拥塞时快速丢弃并计数。资源采样预热期不返回
伪造零。用户可见侧（如 `/bot status`）读不到某项时按诚实标注呈现，绝不补一个好看的数。

## 测试与验收

`tests/test_control_plane_metrics.py`（账本适配器三态与分组口径）、
`tests/test_host_metrics.py` / `test_host_metrics_coverage.py` /
`test_host_metrics_single_source.py`（取数真身与防回潮）。用例数以最近一次
`scripts/dev.ps1 -Task test` 实跑为准。真机（重启后）：控制面开着时拉
`/api/v1/metrics/overview` 与 `/api/v1/metrics/resources`，确认账本关闭时返回
`source_unavailable` 而不是全零；制造一轮模型调用后确认当日聚合与账单卡口径一致。
