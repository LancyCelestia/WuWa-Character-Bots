# B02.capability-registry 能力注册表与调度壳

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.capability-registry 能力注册表与调度壳

> 每能力一行的 keystone 声明源，与中央调度信封的收编进度。

- 归属板块：[B02](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py`、`plugins/bot_unified_runtime/capabilities`
- 帮助主题：功能管理, 帮助

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [声明源与投影表一致性](keystone-declarations.md) | — | — | — | — |
| [调度信封与呈现契约分层](invocation-envelope.md) | — | — | — | — |
| [新增能力登记流程（先建模块与函数）](new-capability-checklist.md) | — | — | — | — |
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
