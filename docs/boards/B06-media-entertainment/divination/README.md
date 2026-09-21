# B06.divination 占卜

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.divination 占卜

> 八字、塔罗、金钱卦；牌算与抽卡存储单一真身。

- 归属板块：[B06](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/divination`
- 路由席位：`DIVINATION`
- 能力 id：`bot.divination`
- 帮助主题：占卜
- 配置键前缀：`bot_divination_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [占卜](divination.md) | DIVINATION | bot.divination | 占卜 | 41 |
| [牌算与节气算法真身](deck-math.md) | — | — | — | — |
| [抽卡记录单一存储](draw-store.md) | — | — | — | — |
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
