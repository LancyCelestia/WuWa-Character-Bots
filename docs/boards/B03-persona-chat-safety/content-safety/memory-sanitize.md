# 内容安全与亲密模式 · 记忆侧净化同源

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 记忆侧净化同源

- 层级：一级 B03 → 二级 content-safety → 三级 `memory-sanitize`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/security`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

三级入口 `memory-sanitize`（记忆侧净化同源）挂在二级功能 B03.content-safety「内容安全与亲密模式」下——六硬线确定性闸、亲密档位判定、名单门与记忆净化。

真身模块自述：R-18 内容感知路由（bot.content_route）：会话亲密度分数 + 本地信号。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。

## 怎么调用

调用形态：本入口是机制件，不占路由席位、无独立能力 id，由所属二级功能的实现直接调用。

公开入口（签名以真身为准，本页不复制参数表）：`resolve_intimate_context()`、`build_router_cb()`。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。

## 开关与参数

配置键前缀：`bot_content_route_`、`bot_master_love_`。

逐键语义、缺省值与是否可热改以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准，一切可数事实（字段/主题/别名/入口/模板数）以机器册 `docs/auto-facts.md` 为准。

谁能改：管理员/超管专属开关由能力注册表与门禁判定，口径见 `docs/boards/_conventions.md` 第三节。

## 失败时看到什么

真身模块未以 docstring 写明失败契约，本席不臆测；统一口径是异常经主链路旁路走诊断卡并降级为纯文本兜底，见 B08 板块的错误报告功能页。

取不到外部数据时按项目教义诚实标注无源，绝不编数。

## 测试与验收

离线用例：`tests/test_memory_sanitize.py`。

上面按名强匹配点到的是与本入口同族的用例件、非穷举；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准，真机验收条目见 `docs/acceptance-manual.md`。
