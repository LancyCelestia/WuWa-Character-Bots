# B09.observability 日志·指标·Trace·审计

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability 日志·指标·Trace·审计

> 统一事件总线、来源枚举、指标结构化与轨迹阶段表。

- 归属板块：[B09](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`
- 路由席位：`HOST_STATE`
- 能力 id：`bot.host_state`
- 帮助主题：日志, 状态, 审计, 用量, 宿主机状态
- 配置键前缀：`bot_alerts_`, `bot_metrics_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [宿主机状态](host-state.md) | HOST_STATE | bot.host_state | 宿主机状态 | 41 |
| [统一事件与 SSE](event-bus.md) | — | — | — | — |
| [指标结构化来源](metrics-sources.md) | — | — | — | — |
| [轨迹阶段与脱敏](trace-stages.md) | — | — | — | — |
| [运维告警与抑制](ops-alerts.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

二级功能 B09.observability「日志·指标·Trace·审计」——统一事件与 SSE（`control_plane/events.py`
及 V2.1 事件层）、指标结构化来源（账本/资源/宿主机/用量四类只读源）、轨迹阶段与脱敏
（`domains/chat_reply/runtime/deadline.py` 相位账 + 审计脱敏真身）、运维告警与抑制
（`domains/ops/monitor/alerts.py`）。四条腿共用的纪律：先持久化后投递、未知不是 0、
脱敏零例外、存在性锁不算修好。

## 处理流程

```mermaid
flowchart LR
  in[入口] --> core[处理] --> out[产出]
```

## 边界与降级

开关面：配置键前缀 `bot_alerts_`、`bot_metrics_`，逐键缺省与热更性以 `docs/config-catalog-full.md` 为准。

失败与降级的逐条契约写在真身模块 docstring 里，页内不抄；项目级口径：外部依赖失败不编数、诚实标注无源，异常走统一诊断卡。

## 测试与验收

离线用例：以与真身同域的 `tests/` 目录为准，此处不臆写文件名。

上面按名强匹配点到的是与本功能同族的用例件、非穷举；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准，真机验收条目见 `docs/acceptance-manual.md`。

## 现行缺陷

已知未修项的唯一台账是 `docs/issue-ledger-p2-p3.md` 与 `docs/boards/_meta/code-quality-findings-20260921.md`，逐条归属看那两份，此处不抄。
