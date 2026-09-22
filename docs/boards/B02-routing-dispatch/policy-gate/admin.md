# 门禁与限流 · 管理员命令

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate · 管理员命令

- 层级：一级 B02 → 二级 policy-gate → 三级 `admin`
- 路由席位：`ADMIN`（matcher `admin`，command=True）
- 判定优先级：11
- 能力 id：`bot.status`
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

识别以 `/bot` 为前缀的管理/命令族消息，判成一个显式命令席位。输入是消息文本，产出是 `RouteDecision(RouteKind.ADMIN, "bot.status", ...)`。它把「这是不是一条 `/bot` 命令」这一步判定收敛成一处，供路由表与群门禁共用，不在别处重抄前缀规则。

## 怎么调用

路由侧谓词是 `plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py` 内 `build_route_rules` 的 `admin_match`，底层判定 `base_router.py::_admin_command_match`：文本等于 `/bot`、或以 `/bot `、`bot ` 开头即命中。该席位登记在 `capability_registry.py::ROUTE_CAPABILITY_DECLARATIONS`，`command=True`（属命令席位，群门禁按确定性命令处理）、`has_rule=True`。群门禁侧另有一个命令态判定 `domains/chat_reply/policy/gate.py::is_command_text`，语义是「以前缀 `/bot` 开头且带词边界」——`/botxxx` 这种无边界的不算命令，避免普通聊天误入命令态。

## 开关与参数

`RouteKind.ADMIN` 的 priority 以 `capability_registry.py` 声明行为准（`base_router` 字面表同值，由一致性锁钉住），不在本文手写。命中 ADMIN 后按 `capability_id=bot.status` 交由对应能力入口处理；管理员专属子命令的可见性由帮助注册表 `admin_only` 元数据控制，属能力实现面不属本判定。

## 失败时看到什么

误判风险是「把普通文本当命令」或「命令没被认出来」：`_admin_command_match` 靠空格边界区分 `bot ` 与 `botxxx`，改这个边界要同步核对 `gate.py::is_command_text` 的词边界语义，两处必须一致否则门禁与路由口径分叉。未命中任何规则时落 `RouteKind.IGNORE` 兜底。

## 测试与验收

`tests/test_admin_roster_and_roles.py`（管理员名单与角色）、`tests/test_group_policy.py`（群门禁命令态）。路由席位数据列一致性由 `tests/test_capability_registry.py` 锁定。
