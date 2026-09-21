# B02.policy-gate 门禁与限流

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate 门禁与限流

> 角色/黑白名单/安静时间/限流/幂等，全能力共用的准入面。

- 归属板块：[B02](../README.md)
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
- 路由席位：`ADMIN`
- 能力 id：`bot.status`
- 帮助主题：角色, 群策略, 限流, 暂停, 为什么
- 配置键前缀：`bot_rate_limit_`, `bot_quiet_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [管理员命令](admin.md) | ADMIN | bot.status | — | 11 |
| [六级角色与权限叠加](role-model.md) | — | — | — | — |
| [安静时间与主动搭话门](quiet-hours.md) | — | — | — | — |
| [双实现限流与回滚](rate-limiter.md) | — | — | — | — |
| [入站幂等](idempotency.md) | — | — | — | — |
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
