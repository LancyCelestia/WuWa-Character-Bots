# 模型路由与账本 · 优先级组与失败转移

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.model-control · 优先级组与失败转移

- 层级：一级 B09 → 二级 model-control → 三级 `model-router`
- 实现落点：`plugins/bot_unified_runtime/llm`、`plugins/bot_unified_runtime/domains/chat_reply/llm_engine`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

三级入口 `model-router`（优先级组与失败转移）挂在二级功能 B09.model-control「模型路由与账本」下——provider/channel/model 三级、failover、上下文钳制与计费账本。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。

## 怎么调用

调用形态：本入口是机制件，不占路由席位、无独立能力 id，由所属二级功能的实现直接调用。

具体公开函数以真身模块的顶层 `def`/`class` 为准，不在本页登记，避免与代码漂移。

本页上方的生成区从权威声明源投影，实现落点与归属以它为准，正文不复制。

## 开关与参数

配置键前缀：`bot_model_`、`bot_llm_`、`bot_chat_failover_`。

逐键语义、缺省值与是否可热改以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准，一切可数事实（字段/主题/别名/入口/模板数）以机器册 `docs/auto-facts.md` 为准。

谁能改：管理员/超管专属开关由能力注册表与门禁判定，口径见 `docs/boards/_conventions.md` 第三节。

## 失败时看到什么

真身模块未以 docstring 写明失败契约，本席不臆测；统一口径是异常经主链路旁路走诊断卡并降级为纯文本兜底，见 B08 板块的错误报告功能页。

取不到外部数据时按项目教义诚实标注无源，绝不编数。

## 测试与验收

离线用例：`tests/test_model_router_channel_failover.py`、`tests/test_model_router_failover.py`。

上面按名强匹配点到的是与本入口同族的用例件、非穷举；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准，真机验收条目见 `docs/acceptance-manual.md`。
