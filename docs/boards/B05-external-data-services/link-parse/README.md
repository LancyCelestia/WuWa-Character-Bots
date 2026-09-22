# B05.link-parse 链接解析与内容理解

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.link-parse 链接解析与内容理解

> 多平台链接解析、正文抽取与 Cookie 归因。

- 归属板块：[B05](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/link_parse`
- 路由席位：`CONTENT`
- 能力 id：`bot.content`
- 帮助主题：解析, 链接
- 配置键前缀：`bot_link_parse_`, `bot_parse_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [链接解析](content.md) | CONTENT | bot.content | — | 46 |
| [解析器规则族与归因](parser-rules.md) | — | — | — | — |
| [凭证域名绑定与剥离](credential-scoping.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

二级功能 B05.link-parse「链接解析与内容理解」——多平台链接解析、正文抽取与 Cookie 归因。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。 一切可数事实（字段/主题/别名/入口/模板数）以机器册 `docs/auto-facts.md` 为准。

## 处理流程

```mermaid
flowchart LR
  in[入口] --> core[处理] --> out[产出]
```

## 边界与降级

开关面：配置键前缀 `bot_link_parse_`、`bot_parse_`，逐键缺省与热更性以 `docs/config-catalog-full.md` 为准。

失败与降级的逐条契约写在真身模块 docstring 里，页内不抄；项目级口径：外部依赖失败不编数、诚实标注无源，异常走统一诊断卡。

## 测试与验收

离线用例：`tests/test_content_parser_quota_throttle.py`、`tests/test_content_route.py`、`tests/test_content_route_threading.py`。

上面按名强匹配点到的是与本功能同族的用例件、非穷举；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准，真机验收条目见 `docs/acceptance-manual.md`。

## 现行缺陷

已知未修项的唯一台账是 `docs/issue-ledger-p2-p3.md` 与 `docs/boards/_meta/code-quality-findings-20260921.md`，逐条归属看那两份，此处不抄。
