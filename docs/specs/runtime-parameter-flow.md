# 运行时参数流

本文是面向实现的契约，说明架构决策、算法参数和追踪字段如何在统一机器人运行时中传递。

系统级方向见 `research/architecture_report.md`，字段级规则应与 `research/implementation_design_supplement.md` 保持兼容。

## 标准链路

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

任何 capability adapter 都不能直接发送消息。所有能力只返回 `CapabilityResult`；统一运行时负责审查、渲染、发送和审计。

## 横切参数

| 参数 | 作用 | 最晚出现阶段 |
| --- | --- | --- |
| `request_id` | 串起一次用户事件或定时任务的全部阶段。 | intake |
| `debug_id` | 用户可见的失败查询编号，不能暴露堆栈和密钥。 | 第一个可能失败的阶段 |
| `session_id` | 跨适配器稳定表示一次会话。 | intake |
| `session_type` | `private`、`group` 或未来频道类型。 | intake |
| `sender_id` | 用于 ACL、冷却、配额和审计的行为人。 | intake |
| `group_id` | 群会话中的群号。 | intake |
| `capability_id` | 被路由选中的能力或适配器。 | decision |
| `risk_level` | 聚合风险：`low`、`medium`、`high`、`critical`。 | policy |
| `privacy_level` | 输出/数据敏感度：`public`、`group`、`personal`、`credentialed`。 | policy |
| `dedupe_key` | 防止同一内容重复渲染和重复发送。 | decision 或 capability |
| `cooldown_key` | 用于限频和防刷屏。 | policy |
| `audit_tags` | 机器可读的审计标签。 | policy |

这些字段应贯穿后续阶段。下游阶段可以提高 `risk_level` 和 `privacy_level`，但不能静默降低；确需降低时必须写入审计原因。

## 阶段契约

### 1. IncomingMessage

输入：NoneBot 适配器事件、OneBot/NapCat 消息段、Mail/Console 事件和 bot 元信息。

输出字段：

- `platform`
- `adapter`
- `bot_id`
- `session_id`
- `session_type`
- `sender_id`
- `sender_display_name`
- `group_id`
- `raw_segments`
- `plain_text`
- `mentions_bot`
- `reply_to_message_id`
- `timestamp`
- `message_id`

规则：

- 保存原始消息段，方便审计和适配器回退。
- 下游逻辑优先使用归一化字段，不直接依赖 NapCat/OneBot 原始结构。
- 用户文本、引用消息、抓取内容和历史记忆都视为不可信事实。
- 在 intake 阶段分配 `request_id`。

### 2. PolicyEvaluation

输入：`IncomingMessage`、会话配置、ACL、冷却状态、能力注册表元数据。

输出字段：

- `allowed`
- `reason`
- `risk_level`
- `required_scope`
- `cooldown_key`
- `quota_key`
- `privacy_level`
- `audit_tags`

规则：

- 会话、权限、隐私或冷却失败时，在 LLM/外部工具调用前拒绝。
- 群聊默认观察，只有命令、提及、管理员配置订阅或安全告警才主动回应。
- 私聊可以更温和、更个性化，但记忆、提醒和账号相关能力必须有同意基础。

### 3. BotDecision

输入：`IncomingMessage`、`PolicyEvaluation`、意图识别结果。

输出字段：

- `should_respond`
- `mode`
- `trigger`
- `capability_id`
- `target_scope`
- `max_messages`
- `send_policy`
- `persona_profile_id`
- `context_budget`
- `decision_reason`

规则：

- 群聊通常 `max_messages=1`。
- `send_policy` 只能是 `immediate`、`queued`、`digest`、`private_fallback`、`admin_confirm`、`silent_audit`。
- 不回复的负向决策，在有排障价值时仍要写 `AuditRecord`。

### 4. CapabilityResult

输入：`BotDecision`、能力专用的已校验输入，可选 `FetchResult`。

输出字段：

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

- capability adapter 不允许调用 bot/event/NapCat/mail 发送 API。
- 低置信度结果必须请求审查、降级、确认或不发送。
- 个人、账号、凭据相关数据必须设置更高 `privacy_level`。

### 5. ReviewResult

输入：`CapabilityResult`、`PersonaProfile`、`ToneProfile`、安全策略、隐私策略、防刷屏策略。

输出字段：

- `approved`
- `action`: `allow`, `rewrite`, `move_private`, `admin_confirm`, `block`, `audit_only`
- `risk_level`
- `privacy_level`
- `reasons`
- `safe_text`
- `debug_id`

规则：

- LLM 输出和非 LLM 插件输出都必须审查。
- 人格和语气不能覆盖安全、隐私和权限。
- 改写必须保留事实、来源链接和风险/隐私标记。

### 6. RenderedOutput

输入：通过审查的 `CapabilityResult` 或 `safe_text`。

输出字段：

- `content_type`: `text`, `card`, `image`, `forward`, `mixed`
- `content_ref`
- `text_fallback`
- `size_estimate`
- `render_debug_id`

规则：

- 长输出应转为卡片、图片、合并转发或私聊继续，不在群里刷屏。
- 渲染失败时尽量降级为简短文本。
- 渲染不能移除风险、隐私、来源和审计元数据。

### 7. SendRequest

输入：`RenderedOutput`、`BotDecision`、审查后的策略元数据。

输出字段：

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

- 每次发送都必须有 `dedupe_key` 和 `cooldown_key`。
- 后台事件默认走 `digest` 或 `queued`，除非明确是紧急告警。
- 群聊敏感内容转私聊时，只给用户一次简短说明。

### 8. DeliveryReceipt

输入：transport adapter 的发送结果或队列决策。

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

- `sent`、`skipped`、`redirected`、`blocked`、`failed_final` 是终态。
- `failed_retryable` 可以转为 `queued`、`sent` 或 `failed_final`。
- 重试必须通过 `request_id` 和 `dedupe_key` 保持幂等。
- NapCat/OneBot 的 `retcode`、`message_id` 和异常必须映射到这里。

### 9. AuditRecord

输入：策略、能力、审查、渲染、发送和失败阶段的所有事件。

输出字段：

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

- 用户只看到 `debug_id`，不能看到原始异常、cookie、token、authkey、邮件地址等敏感信息。
- 私有调试信息可以记录堆栈和上游细节，但必须脱敏。
- 被拦截或失败的动作必须可观察、可定位、可修复。

## 算法不变量

### 调度

- 每个目标有最小轮询间隔。
- 429、403、验证码、登录要求、超时、解析器变更都进入退避。
- 低优先级目标不能永远饿死，调度器需要 aging 或公平规则。
- cursor 和 last-successful-item 只在成功归一化后更新。

### 风险策略

- 风险由输入、输出、隐私、账号和刷屏风险共同决定。
- `critical` 默认阻断，除非存在明确的人类管理员确认路径。
- 群聊允许的风险低于私聊。
- 凭据和账号数据默认不发群。
- 下游只能让 `risk_level` 和 `privacy_level` 更严格。

### 发送反馈

- 一次用户动作通常最多产生一条群消息。
- 重复内容在渲染前和发送前都要去重。
- 两秒内完成的即时命令只返回结果。
- 长任务最多发一次等待提示。
- 后台轮询不能每轮都公告。

## 验收检查

Milestone 0/1 实现时应添加测试：

- intake 会分配 `request_id` 并归一化会话字段。
- policy 拒绝后不会执行 capability。
- capability adapter 不能直接发送。
- 每个 `SendRequest` 都产生 `DeliveryReceipt`。
- 重试保留 `request_id` 和 `dedupe_key`。
- 被阻断动作会创建带用户安全 `debug_id` 的 `AuditRecord`。
