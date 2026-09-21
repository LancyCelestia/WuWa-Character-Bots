# B05.reference-wiki 百科与参考查询

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.reference-wiki 百科与参考查询

> 维基百科、萌娘百科与地点/作品参考。

- 归属板块：[B05](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/location`
- 路由席位：`WIKI`, `MOEGIRL`, `MOEGIRL_QUESTION`
- 能力 id：`bot.wiki`, `bot.moegirl`
- 帮助主题：维基, 萌娘百科
- 配置键前缀：`bot_wiki_`, `bot_moegirl_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [维基百科](wiki.md) | WIKI | bot.wiki | — | 41 |
| [萌娘百科](moegirl.md) | MOEGIRL | bot.moegirl | 萌娘百科 | 41 |
| [二次元问句](moegirl-question.md) | MOEGIRL_QUESTION | bot.moegirl | — | 46 |
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
