# 路由表与判定序 · matcher 族与谓词

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.route-table · matcher 族与谓词

- 层级：一级 B02 → 二级 route-table → 三级 `matcher-family`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

路由表由一组 `RouteRule` 构成，每条规则自带一个**判定谓词**（matcher）。输入是去空白后的消息文本，外加 `config` 与可选的 `alias_resolver`；谓词命中就返回一个 `RouteDecision`（含 `RouteKind`、`capability_id`、priority、reason、tags），不命中返回 `None` 交给下一条规则。它只判断「这条消息归谁」，不执行能力、不发消息。生效条件是文本非空——空文本在 `classify_message_route` 入口直接判 `RouteKind.IGNORE`，不进谓词循环。

## 怎么调用

判定入口是 `plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py::classify_message_route`，它遍历模块级 `ROUTE_RULES`（由 `build_route_rules()` 构造），按 priority 升序逐个调用规则的 `matcher` 列，第一个非 `None` 即最终决定。谓词本身是 `build_route_rules` 内定义的闭包（如 `weather_match`、`market_match`、`fx_match`、`admin_match`、`chat_match`），统一签名 `(text, config, alias_resolver)`。谓词内可再调已登记的公共判定件，例如金融族共用 `base_router.py::_yields_to_leading_command` 做「让路给更靠前的命令」判定。规则的数据列（kind / capability_id / priority / label / reason / tags / matcher 名）以 `capability_registry.py::ROUTE_CAPABILITY_DECLARATIONS` 为权威声明源。

## 开关与参数

谓词是否放行常受配置开关控制：例如 `subscribe_match` 先读 `bot_subscribe_enabled`（缺省 True），关闭即返回 `None`。这类键在对应谓词内以 `getattr(config, ...)` 引用，装配期取值。`alias_resolver=None` 时昵称命令谓词不命中，文本落到后续规则。

## 失败时看到什么

所有谓词都不命中时，`classify_message_route` 返回兜底 `RouteDecision(RouteKind.IGNORE, "bot.ignore", ...)`。审查 C-07 记录：该兜底曾是无消费的静默点，现消费侧收敛在 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py`（`is_command_form_text` 为真的输入才回守岸人语气的引导，普通闲聊 / 空消息仍静默）。谓词内部不应抛异常——它们写成返回 `None` 而非冒泡，判定异常会拖垮整条分类。

## 测试与验收

路由判定序与拆位见 `tests/test_route_priority_disambiguation.py`；规则数据列与 keystone 声明表的一致性由 `tests/test_capability_registry.py` 锁定。真机验收随路由面在 `docs/acceptance-manual.md` 覆盖。
