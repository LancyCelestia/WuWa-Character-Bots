# B09.observability 日志·指标·Trace·审计

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability 日志·指标·Trace·审计

> 统一事件总线、来源枚举、指标结构化与轨迹阶段表。

- 归属板块：[B09](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor`、`plugins/bot_unified_runtime/control_plane/metrics.py`
- 帮助主题：日志, 状态, 审计, 用量
- 配置键前缀：`bot_alerts_`, `bot_metrics_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [统一事件与 SSE](event-bus.md) | — | — | — | — |
| [指标结构化来源](metrics-sources.md) | — | — | — | — |
| [轨迹阶段与脱敏](trace-stages.md) | — | — | — | — |
| [运维告警与抑制](ops-alerts.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

（待写：一到三段大白话，说清它替谁解决什么问题。）

## 处理流程

```mermaid
flowchart LR
  in[入口] --> core[处理] --> out[产出]
```

## 边界与降级

（待写：外部依赖挂了怎么办、无源时如何诚实、权限门与限额。）

## 测试与验收

（待写：离线用例件与真机验收条目指针。）

## 现行缺陷

（待写：已知未修的 P0/P1/P2 与本功能相关项，指真身台账。）
