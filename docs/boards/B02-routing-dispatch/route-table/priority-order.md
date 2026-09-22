# 路由表与判定序 · 优先级判定序与拆位

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.route-table · 优先级判定序与拆位

- 层级：一级 B02 → 二级 route-table → 三级 `priority-order`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定一条文本同时像多种命令时归谁。真实判定序不是清单的书写序，而是由各条 `RouteRule` 上的 `priority` 整数排出来的：数值越小越先判。当两条规则 priority 相同，按注册表的书写序稳定排序、先到先得。这一层只解决「谁先判」，不解决「判完谁执行」。

## 怎么调用

`base_router.py::classify_message_route` 对模块全局 `ROUTE_RULES` 调 `sorted(..., key=lambda c: c.priority)` 后遍历——Python 的 `sorted` 稳定，所以同 priority 天然保持 `build_route_rules` 里的书写序。每次调用都对全局重排，保留测试与决策引擎替换该注册表时的语义。

### 拆位口径（必须先读）

priority 是**唯一消歧手段**，冲突靠给它让位来解，不靠改判定逻辑。历史上金融族多条挤在同一数值，2026-09-21 全面修复波把它们拆开：汇率 `RouteKind.FX` 降到低于行情、商品 `COMMODITIES`、债 `BOND`、北向 `NORTHBOUND` 各占独立低值，使「美元兑人民币」「黄金」「国债收益率」「北向资金」不被泛股指词抢走；股指 `MARKET` 的触发词表同步收紧（兑 / 原油 / 国债 / 北向 等让路）。金融谓词内还共用 `base_router.py::_yields_to_leading_command`，命中更靠前的显式命令时主动不判。各 kind 的具体 priority 数值以 `build_route_rules()` 字面表与 `capability_registry.py::ROUTE_CAPABILITY_DECLARATIONS` 为准，不在本文手写。

## 开关与参数

路由拆位靠的是各能力的 `priority` 数值本身，没有额外开关：逐席位优先级以本页上方生成区（派生自能力 keystone `ROUTE_CAPABILITY_DECLARATIONS`）为准，本板块的路由席位清单以生成物为准，此处不复制。让路判据（谁在触发词上给谁让路）是代码事实，见真身 `domains/chat_reply/runtime/base_router.py` 的判定序与其回归锁。

## 失败时看到什么

priority 配错的表现是「抢答」或「答非所问」：一条命令被数值更小的规则提前截走。所有规则都不命中时落 `RouteKind.IGNORE` 兜底，命令形态的输入由 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` 回一句守岸人语气引导。

## 测试与验收

金融与命令族的拆位由 `tests/test_route_priority_disambiguation.py` 锁定；LLM 侧路由优先序回归见 `tests/test_llm_route_priority_v21r2.py`。声明表逐行逐字段与注册表一致由 `tests/test_capability_registry.py` 执法。
