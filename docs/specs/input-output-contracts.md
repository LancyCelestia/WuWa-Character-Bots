# 输入输出契约

本文定义外部输入、能力输入、LLM 上下文、外部抓取请求、能力输出、发送请求和用户反馈如何校验。

## 输入类别

### 外部聊天输入

来源：

- 私聊消息；
- 群消息；
- 回复和提及；
- 命令文本；
- 链接和媒体消息段；
- NapCat/OneBot V11 数组消息段或 CQ 文本。

归一化目标：`IncomingMessage`。

校验规则：

- 保留 `raw_segments` 用于审计和适配器回退。
- 归一化文本、提及、回复目标、发送人、会话和时间戳。
- 空消息默认忽略，除非该 adapter event 本身有业务意义。
- 聊天文本绝不能被当成运行时策略指令。
- 聊天历史进入 LLM 前必须标记为不可信事实。

### 能力输入

来源：

- 命令参数；
- 路由器选中的链接；
- 订阅/调度任务；
- GsCore 或其他桥接命令；
- 管理员确认动作。

校验规则：

- 外部抓取或 LLM 调用前先校验必填参数。
- 必须携带 `capability_id`、`request_id`、`session_id`、`privacy_level`、`risk_level`。
- 涉及账号、cookie、token、二维码、authkey、位置、出行、个人日程的命令必须要求私聊或明确同意。
- 能力输入不能包含原始密钥；只能传 `headers_ref`、`credential_ref`、`address_ref` 这类引用。

### LLM 输入

来源：

- `PersonaProfile`；
- 当前消息；
- 短上下文窗口；
- 搜索结果；
- parser 结果；
- 记忆事实；
- 桥接输出。

校验规则：

- 可信系统/人格策略与不可信事实必须分区。
- 抓取内容、记忆、聊天记录和桥接输出都放在明确的 untrusted 区。
- 组装 prompt 前执行上下文预算。
- 没有私聊同意时，脱敏密钥和个人账号标识。
- LLM 工具默认关闭，只有被选中的能力明确允许时才能打开。

### 外部抓取输入

归一化目标：`FetchRequest`。

必填字段：

- `source_id`
- `url_or_endpoint`
- `method`
- `params`
- `body`
- `headers_ref`
- `auth_mode`
- `cache_key`
- `ttl_seconds`
- `timeout_seconds`
- `retry_policy`
- `min_interval_key`
- `priority`
- `privacy`
- `allowed_content_types`
- `robots_policy`

校验规则：

- 每个外部请求都必须有超时和重试策略。
- 每个来源都必须有 rate-limit key。
- 使用凭据引用，不能传原始 cookie/token/header。
- 敏感抓取必须遵守 `api_only` 或 `manual_review_required`。
- 凭据数据只有策略明确允许时才缓存。

## 输出类别

### CapabilityResult

每个能力返回结构化输出：

- `kind`
- `title`
- `summary`
- `body`
- `url`
- `source`
- `source_timestamp`
- `images`
- `actions`
- `confidence`
- `risk_level`
- `privacy_level`
- `private_recommended`
- `send_policy`
- `debug_id`

规则：

- 不直接发送。
- 不把原始异常当用户文本。
- 来源支撑的结论尽量附 `source` 或 `url`。
- 低置信度必须设置 `confidence`，让审查/发送路径决定降级、确认或跳过。

### ReviewResult

`ReviewResult` 把能力输出变成允许、改写、转私聊、管理员确认、阻断或仅审计。

动作：

- `allow`
- `rewrite`
- `move_private`
- `admin_confirm`
- `block`
- `audit_only`

规则：

- 隐私和安全优先于人格风格。
- 群输出比私聊输出有更严格的刷屏和隐私检查。
- 被阻断内容要写审计；如果用户正在等待，还要给简短可执行说明。

### RenderedOutput

渲染输出可以是：

- 文本；
- 卡片；
- 图片；
- 合并转发；
- 混合消息。

规则：

- 保留 `request_id`、`debug_id`、`privacy_level`、`risk_level`。
- 卡片/图片失败时尽量提供文本 fallback。
- 发送前执行大小限制和 `max_messages` 限制。
- 群里不把长输出拆成刷屏消息链。

### SendRequest

必填字段：

- `request_id`
- `session_id`
- `target_scope`
- `target_id`
- `origin_message_id`
- `capability_id`
- `content`
- `send_policy`
- `priority`
- `max_messages`
- `dedupe_key`
- `cooldown_key`
- `expires_at`
- `privacy_level`
- `allow_split`
- `allow_forward`
- `persona_profile_id`
- `audit_tags`

规则：

- `send_policy` 决定即时、队列、摘要、私聊回退、管理员确认或仅审计。
- 群发送必须有 `max_messages`、去重和冷却。
- 凭据或个人输出默认私聊。
- 管理员确认必须包含来源、风险、目标、过期时间和确认/取消命令。

### DeliveryReceipt

状态：

- `accepted`
- `rendered`
- `queued`
- `sent`
- `skipped`
- `redirected`
- `blocked`
- `failed_retryable`
- `failed_final`

规则：

- 用户可见成功以 receipt 状态为准，不以 capability 成功为准。
- 可重试失败必须保留请求关联。
- 最终失败必须包含用户安全文本和审计私有细节。
- 去重、冷却或过期导致的跳过，在群里通常保持静默。

### AuditRecord

必填字段：

- `audit_id`
- `request_id`
- `session_id`
- `capability_id`
- `stage`
- `event`
- `severity`
- `public_message`
- `private_debug`
- `created_at`

规则：

- 脱敏 token、cookie、authkey、二维码 payload、账号密钥、邮件地址等。
- 私有审计需要足够排障信息。
- 公共消息短而可执行。
- 阻断、转私聊、可重试失败和最终失败都必须记录审计。

## 错误分类

| 错误类型 | 用户侧行为 | 审计要求 |
| --- | --- | --- |
| `user_input_invalid` | 说明期望格式。 | 原始输入和校验错误。 |
| `auth_required` | 引导私聊绑定/登录。 | 缺失凭据类型和来源 id。 |
| `permission_denied` | 告知该功能未在此处启用。 | ACL 规则和主体。 |
| `rate_limited` | 说明来源或功能正在冷却。 | 来源、目标、retry-after。 |
| `upstream_changed` | 说明来源格式可能变化。 | parser 异常和样本 id。 |
| `content_blocked` | 说明内容不能在此处发送。 | 安全类别和审查阶段。 |
| `privacy_blocked` | 转私聊或要求同意。 | 隐私等级和目标范围。 |
| `timeout` | 说明来源响应超时。 | 耗时、超时配置、重试次数。 |
| `internal_error` | 给短失败说明和 debug id。 | 堆栈和运行时状态。 |

## 用户反馈规则

- 两秒内完成的即时命令：只回复结果。
- 超过两秒的即时命令：最多发一次等待提示。
- 后台订阅：发送新内容、摘要或管理员失败汇总，不公告每次轮询。
- 群自动解析：重复和冷却命中静默跳过。
- 私聊回退：只告诉用户一次敏感输出已移到私聊。
- 管理员确认：展示紧凑审批信息和过期时间。
- 失败：说明下一步能做什么；必要时附 `debug_id`。

## 隐私与群聊约束

- 群聊保守且 opt-in。
- 私聊可使用更多个人上下文，但必须有同意基础。
- 同人、账号游戏数据、日程、出行、位置默认私聊。
- 公共游戏/wiki/兑换码/日历命令可以早期开放。
- cookie、token、二维码登录、authkey、UID 绑定、抽卡记录、账号面板在密钥存储、脱敏、审计和撤销能力完成前默认阻断。

## NoneBot / NapCat 输入输出规范

- NoneBot 的 `plugin_dirs = ["plugins"]` 是本地插件加载入口。
- OneBot V11 / NapCat 输入事件应先转成 `IncomingMessage`，不让业务能力依赖原始 adapter 类型。
- NapCat 推荐 `messagePostFormat: 'array'`，方便保留文字、图片、at、json、合并转发等消息段结构。
- 出站消息只能由 sender/transport adapter 把 `RenderedOutput` 转换成 OneBot/NapCat 消息段。
- `send_msg`、`send_private_msg`、`send_group_msg` 的返回值必须映射成 `DeliveryReceipt`。
- capability adapter 不应直接调用 `event.send`、`bot.send_*` 或 NapCat HTTP/WebSocket API。

## 验收检查

实现时应添加测试：

- 非法命令输入映射到 `user_input_invalid`。
- 群聊中的私密数据映射到 `privacy_blocked` 或 `redirected`。
- 没有来源置信度的 `CapabilityResult` 会先被审查。
- 重复 `dedupe_key` 会跳过重复群输出。
- 发送失败创建 `DeliveryReceipt.failed_retryable` 或 `failed_final`。
- 所有被阻断输出创建脱敏 `AuditRecord`。
