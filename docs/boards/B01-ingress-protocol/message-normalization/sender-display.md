# 消息归一与身份中央件 · 发送者显示名归一

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.message-normalization · 发送者显示名归一

- 层级：一级 B01 → 二级 message-normalization → 三级 `sender-display`
- 实现落点：`plugins/bot_unified_runtime/domains/core/session_keys.py`、`plugins/bot_unified_runtime/domains/core/text_boundary.py`、`plugins/bot_unified_runtime/domains/core/board_placement.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

在摄取这一跳就把「这条消息是谁发的」一次填进契约，之后所有下游只读字段、不再各自去事件里刨。填的是：显示名、平台角色、群名片、昵称、头衔、群等级、群标题。它解决的是两类历史问题——同一群里同一个人被叫成两个名字，以及下游有人自己去读 `event.sender.role` 而另一处不读，导致权限判定与画像注入口径不一。

## 怎么调用

填充点在根 `__init__.py` 的摄取函数（内部件 `_incoming_from_nonebot_event`，装配私有、不对外）。口径：OneBot v11 群内 `card`（群名片）优先于 `nickname`，strip 后为空则保持 None，称谓链照旧回退。Telegram / Mail 事件没有 `sender.card/nickname` 形态，自然落 None，未在此处扩别的来源。

消费侧的登记件（不属本入口，列在这里是为了指明「不要再自己拼」）：

- `domains/chat_reply/character/addressing.py:build_addressing_context(...)`：把显示名连同用户显式偏好、会话类型合成称呼上下文；用户显式偏好永远最优先。
- `domains/chat_reply/character/providers.py`：把称呼与平台角色注入人格上下文分区。
- 权限判定不看这些展示字段：一律按 `sender_id` 走 `domains/chat_reply/policy/roles.py:build_role_settings(...)`。`sender_platform_role` 是**协议侧身份事实**（如群主），目前唯一的权限用途是紧急信息订阅的本群群主腿（`domains/emergency_info/capabilities/emergency_info.py:allows_emergency_subscription`，且仅 `scope=group` 生效）。

## 开关与参数

无配置键。字段定义在 `domains/core/contracts/runtime.py` 的 `IncomingMessage`（全可选，非 OneBot 事件保持 None ⇒ 对既有链路零破坏）。谁能改：只有摄取层可以新增来源；下游只读。

要特别记住的两条：

- `sender_level`（QQ 群等级）只作用户画像与上下文展示，**不影响权限**；等级 0 与空值统一落 None。
- 平台角色是协议事实，不是 bot 的角色体系。`blocked`/`admin` 这些只来自 `RoleSettings` 的名单，绝不能用 `sender.role=owner` 代替。

## 失败时看到什么

取不到就是 None，然后称谓链回退到既有默认（群友/你），不会崩也不会瞎猜性别或身份。事件实现差异导致的取值失败（`get_user_id()` 抛错这类）按空串处理并继续，不阻断入链。

## 测试与验收

`tests/test_b07_sender_level_ingest.py`（群等级摄取与「不影响权限」）、`tests/test_text_at_mention.py` 与 mentions 族（点名信号）、称谓与身份相关：`tests/test_addressing*.py`、`tests/test_admin_roster_and_roles.py`（管理档案名禁被学习）。
真机：在群里用改了群名片的账号 @ 守岸人，看回复称呼是否跟随；重启后生效，条目见 `docs/acceptance-manual.md` §6.6 系列。
