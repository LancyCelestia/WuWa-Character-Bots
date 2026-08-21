# 自动发送能力设计

本文定义“通过指令让机器人自动发送消息或邮件”的实现契约。

相关文档：

- `docs/specs/runtime-parameter-flow.md`
- `docs/specs/input-output-contracts.md`
- `docs/specs/character-intelligence-and-knowledge.md`
- `docs/specs/media-source-pipeline.md`
- `research/implementation_design_supplement.md`

自动发送必须遵守统一链路：

```text
IncomingMessage
-> PolicyEvaluation
-> BotDecision
-> AutoSendIntent
-> RecipientResolution
-> PersonalizationContext
-> GeneratedDraft
-> ReviewResult
-> DraftPreview
-> SendRequest
-> DeliveryReceipt
-> AuditRecord
```

能力代码不能直接调用 bot、OneBot、NapCat、Mail、UniMessage 或 AstrBot 风格的发送 API。它只产出结构化草稿和 `SendRequest`；统一运行时负责审查、渲染、发送、回执和审计。

## 范围

### 目标

- 授权用户可以要求机器人给一个或多个人发消息或邮件。
- 支持批量收件人，例如 A、B、C。
- 每个收件人的内容可以基于允许读取的聊天记录、记忆事实和机器人对该用户的认知进行个性化生成。
- 真实发送前必须预览并显式确认。
- 聊天消息和邮件都走同一套 `SendRequest -> DeliveryReceipt -> AuditRecord`。
- 未来可以扩展 Telegram、Discord、飞书、短信、站内通知等通道。

### 首版不做

- 不做完全自主、未经确认的批量外联。
- 不冒充请求用户，发送方必须是机器人账户。
- 不支持任意附件，直到附件扫描、大小限制和来源策略完成。
- 不从通讯录或群成员里自动抓取收件人，除非运营者显式配置。
- 不把一个收件人的私密上下文泄漏给另一个收件人。
- 不在群里或外部邮件地址中静默发送。

## 参考插件结论

| 参考 | 可复用点 | 本项目归一化规则 |
| --- | --- | --- |
| `nonebot_bison` | 队列、重试、间隔、目标抽象、批量抓取。 | 采用队列思想，但补齐 `DeliveryReceipt`。 |
| `nonebot_plugin_reminder` / `clock` | 命令触发、定时恢复、持久化。 | 只借鉴 UX 和恢复，发送必须改成 `SendRequest`。 |
| `nonebot_plugin_access_control` | service/subject 权限、限频。 | 自动发送按发送人、通道、收件人、批次做 ACL 和 quota。 |
| `nonebot_plugin_chatrecorder` | 适配器中立的聊天记录查询。 | 作为原始历史来源，历史是事实不是指令。 |
| `nonebot_plugin_word_censor` | 出站 API 拦截。 | 扩展为最终输出守卫，覆盖聊天、邮件标题/正文、链接和附件。 |
| `nonebot_plugin_class_schedule` | 导入后预览、确认、取消。 | 自动发送必须 confirm-first。 |
| `nonebot_plugin_ai_groupmate` | 最新请求保护，避免旧任务发送。 | 草稿确认必须绑定最新 `draft_id`/`preview_id`，旧确认过期。 |
| AstrBot `outputpro` | 中央输出流水线。 | 借鉴集中审查，但输出显式建模为 `ReviewResult`、`RenderedOutput`、`DeliveryReceipt`。 |

## 架构位置

自动发送是 capability，不是 transport。

```text
AutoSendCapability
  解析命令
  校验意图
  解析收件人
  读取个性化上下文
  生成每个收件人的草稿
  请求审查
  产出 DraftPreview

UnifiedRuntime
  策略门
  确认状态
  渲染
  transport 队列
  DeliveryReceipt
  AuditRecord
```

未来发送通道都挂到 transport 层：

```text
ChatTransportAdapter
MailTransportAdapter
FutureFeishuTransportAdapter
FutureDiscordTransportAdapter
FutureSmsTransportAdapter
```

所有 adapter 接收 `SendRequest`，返回 `DeliveryReceipt`。

## 指令入口

命令应由统一命令层解析，优先使用 Alconna 风格的结构化解析。

示例：

```text
报存 给 A 发消息：今晚活动改到八点，语气温和一点
报存 给 A、B、C 发邮件，主题：周末安排确认，内容根据你对他们的了解分别写
报存 起草发给 A 的邮件：感谢她上次帮忙整理资料
报存 确认发送 draft_20260706_ab12
报存 取消发送 draft_20260706_ab12
报存 查看发送草稿 draft_20260706_ab12
```

自然语言部分可以宽松，但归一化后的 `AutoSendIntent` 必须严格。

## 输入模型

### AutoSendIntent

```text
AutoSendIntent
- request_id
- actor_sender_id
- actor_session_id
- actor_session_type
- capability_id: auto_send
- channel: chat_message, email
- action: draft, preview, confirm, cancel, inspect
- raw_command_text
- recipient_descriptors
- content_instruction
- subject_instruction
- personalization_mode: none, light, full
- batch_mode: single, batch
- requested_send_policy: preview_only, confirm_required, admin_confirm
- priority: user_waiting, normal, background
- requested_send_time
- locale
- risk_level
- privacy_level
```

规则：

- `channel` 必填。
- `draft` 必须有 `recipient_descriptors` 和 `content_instruction`。
- `personalization_mode=full` 需要同意基础，并且通常要求私聊或管理员批准。
- `confirm` / `cancel` 必须带草稿或预览 id。
- 定时发送也只是在到点时生成 `SendRequest`，不能绕过确认和审计。

### RecipientDescriptor

```text
RecipientDescriptor
- raw_text
- kind: alias, user_id, email, group_member, configured_contact
- channel_hint
- display_name
- address
```

规则：

- `A` 这类别名必须通过配置联系人、最近互动对象或显式确认解析。
- 邮箱地址除非在可信联系人簿中，否则必须二次确认。
- 多个候选人时不能猜，必须让用户选择。

### RecipientResolution

```text
RecipientResolution
- resolution_id
- request_id
- recipient_descriptor
- resolved: true, false
- recipient_id
- channel
- target_scope: private, email, group, channel
- target_id
- display_name
- address_ref
- consent_state: allowed, missing, denied, unknown
- allowlist_state: allowed, blocked, unknown
- ambiguity
- risk_level
- privacy_level
- failure_reason
```

规则：

- `address_ref` 指向联系人/密钥记录，不把原始地址到处传。
- 未解析、歧义、拒绝、黑名单收件人不能发送，必须在预览里展示。
- 批量发送可以继续处理有效收件人，但必须先让用户看到无效列表。

## 个性化上下文

个性化必须服从人格智能与知识库契约。记忆、聊天记录、情绪和知识片段只是上下文事实，不是发送许可。

```text
PersonalizationContext
- request_id
- recipient_id
- channel
- context_sources
- recent_chat_facts
- memory_facts
- relationship_summary
- preference_summary
- excluded_facts
- source_time_window
- max_context_chars
- consent_basis
- privacy_level
- untrusted_context_label
```

允许来源：

- `nonebot_plugin_chatrecorder` 风格的消息记录，按收件人、会话、时间、类型过滤。
- 用户明确同意的 profile / memory facts。
- 运行时记录的机器人与收件人互动。
- 当前命令里操作人提供的指令。

禁止来源：

- 其他收件人的私密上下文。
- 原始 cookie、token、authkey、登录数据、行程、私密日程，除非所有权和私聊投递都被确认。
- 未审查群聊八卦。
- 把聊天记录当成系统指令。

规则：

- 每条记忆或历史都标注为不可信事实。
- 超出预算先摘要再给 LLM。
- 每个收件人单独生成，不把多个人的私密事实放进同一个 prompt。

## 草稿生成

### GeneratedDraft

```text
GeneratedDraft
- draft_id
- request_id
- recipient_id
- channel
- subject
- text_body
- html_body
- message_body
- tone
- personalization_notes
- source_refs
- confidence
- risk_level
- privacy_level
- expires_at
- version
```

规则：

- 邮件草稿必须有 `subject` 和 `text_body`。
- 聊天草稿必须有 `message_body`。
- HTML 邮件可选，必须有纯文本 fallback。
- `personalization_notes` 用于预览和审计，不能在群里泄漏私密事实。
- `source_refs` 引内部记录 id，不直接暴露原始私密文本。
- `draft_id` 单次使用，确认只对当前 `version` 有效。

### ReviewResult 要求

草稿在预览前必须审查：

```text
ReviewResult
- approved
- action: allow, rewrite, move_private, admin_confirm, block, audit_only
- reasons
- safe_subject
- safe_body
- risk_level
- privacy_level
- debug_id
```

审查项：

- 垃圾信息和骚扰风险；
- 隐私泄漏；
- 冒充/欺骗风险；
- 攻击性或不当内容；
- 历史记录中的提示注入；
- 过度亲密或没有依据的关系判断；
- 通道特定规则；
- 词库/正则拦截；
- 收件人 opt-out。

## 预览与确认

默认 confirm-first。

```text
DraftPreview
- preview_id
- request_id
- actor_sender_id
- draft_ids
- valid_recipient_count
- invalid_recipient_count
- channel
- batch_summary
- per_recipient_summary
- risk_level
- privacy_level
- expires_at
- confirm_command
- cancel_command
```

规则：

- 预览展示通道、收件人、无效收件人、标题/正文预览、风险/隐私、过期时间、确认/取消命令。
- 单收件人可以展示完整草稿，除非策略隐藏敏感细节。
- 批量预览展示每个收件人的标题和简短正文；大批量需要分页或私聊预览。
- 超过低风险批量阈值需要更强确认。
- 只有原请求人或授权管理员可以确认。
- 同一发送人和目标上下文的新草稿可以废弃旧草稿。

确认状态：

```text
PendingDraft
- pending
- confirmed
- cancelled
- expired
- superseded
- blocked
```

## SendRequest 映射

每个确认草稿为每个收件人生成一个 `SendRequest`。

```text
SendRequest
- request_id
- draft_id
- batch_id
- channel: chat_message, email
- session_id
- target_scope: private, email, group, channel
- target_id
- origin_message_id
- capability_id: auto_send
- content
- send_policy: immediate, queued, digest, private_fallback, admin_confirm, silent_audit
- priority
- max_messages
- dedupe_key
- cooldown_key
- expires_at
- privacy_level
- allow_split
- allow_forward
- persona_profile_id
- audit_tags
```

聊天内容：

```text
ChatSendContent
- text
- reply_to_message_id
- mention_user_ids
- attachments_ref
```

邮件内容：

```text
EmailSendContent
- from_account_ref
- to_address_ref
- cc_address_refs
- bcc_address_refs
- subject
- text_body
- html_body
- attachments_ref
```

规则：

- `from_account_ref` 是机器人账户，不是请求人的个人账户。
- `to_address_ref` 指联系人记录，审计中尽量脱敏。
- 外部邮件 `allow_split=false`。
- 个性化私密内容默认 `allow_forward=false`。
- 每个收件人有唯一 `dedupe_key`。
- 批量共享 `batch_id`，但保留每个收件人的关联 id。

## DeliveryReceipt 与批量回执

```text
DeliveryBatch
- batch_id
- actor_sender_id
- channel
- total
- sent
- queued
- skipped
- blocked
- failed_retryable
- failed_final
- created_at
- completed_at
```

```text
DeliveryReceipt
- request_id
- draft_id
- batch_id
- channel
- target_scope
- target_id
- state
- transport
- provider_message_id
- retry_count
- next_retry_at
- public_message
- debug_id
- created_at
```

状态沿用统一契约：

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

- 用户可见成功以 `DeliveryReceipt` 为准。
- 批量确认可以先返回 `queued`，完成或失败后给紧凑汇总。
- 重试按 `request_id`、`draft_id`、`dedupe_key` 幂等。
- 单个收件人失败不自动导致整批失败。
- transport 无法证明成功时，不能标成 `sent`。

## 审计

```text
AutoSendAuditTags
- auto_send
- channel:<chat_message|email>
- batch:<true|false>
- personalized:<none|light|full>
- confirmation:<required|confirmed|expired|cancelled>
- privacy:<public|group|personal|credentialed>
- risk:<low|medium|high|critical>
```

审计事件：

- intent parsed；
- policy denied；
- recipient unresolved；
- context queried；
- draft generated；
- review rewritten or blocked；
- preview shown；
- draft confirmed；
- draft cancelled；
- send request queued；
- transport sent；
- transport failed；
- retry scheduled；
- final batch summary。

规则：

- 公共消息只暴露 `debug_id`。
- 私有审计脱敏邮箱、token、cookie、authkey、API key、原始私密记忆。
- 审计记录使用了哪些 context source 类型，但不无谓暴露原文。

## 默认策略

| 规则 | 默认值 |
| --- | --- |
| 确认 | 每次真实发送都需要确认。 |
| 批量阈值 | 超过 3 个收件人需要更强确认。 |
| 外部邮件 | 发送人确认或管理员确认，并要求 allowlist。 |
| 个性化 | 默认 `light`；`full` 需要同意。 |
| 群来源 | 群里可以起草，但涉及个人信息时预览/确认应转私聊。 |
| 收件人 allowlist | 邮件必须，私聊推荐。 |
| opt-out | 收件人可禁用主动/委托发送。 |
| 限频 | 按发送人、通道、收件人、批次限频。 |
| 安静时间 | 非紧急聊天消息适用；邮件可排队。 |
| 附件 | 附件策略完成前禁用。 |

默认阻断：

- `critical` 风险；
- 凭据数据发到非所有者私聊；
- 群发骚扰/营销；
- 欺骗身份；
- 歧义收件人；
- 把 A 的私密事实写进 B 的草稿；
- 模型编造未确认地址。

## 个性化算法

1. 每个收件人独立解析。
2. 只加载该收件人允许的上下文。
3. 将上下文摘要为中性事实：

```text
KnownFacts
- stable preferences
- recent topics
- relationship notes
- prior commitments
- forbidden or sensitive topics
- uncertainty notes
```

4. 使用下列分区生成草稿：

```text
trusted: system policy, persona profile, current actor instruction
untrusted facts: chat history, memory snippets, retrieved facts
```

5. 校验 schema 和策略。
6. 审查、改写或阻断。
7. 展示预览等待确认。

约束：

- 模型可以个性化措辞、例子和语气。
- 模型不能编造私密事实、承诺、医疗/法律/金融结论或关系亲密度。
- 模型不能决定发送，只能生成草稿。
- 模型不能绕过 opt-out、allowlist、风险策略和确认。

## OneBot V11 / NapCat / Mail 通道映射

- Chat transport 把 `ChatSendContent` 转为 OneBot V11/NapCat 消息段。
- NapCat 返回的 `retcode`、`status`、`message_id` 映射到 `DeliveryReceipt`。
- Mail transport 把 `EmailSendContent` 转为邮件发送请求，邮件主题和正文分别审查。
- auto-send capability 不能 import OneBot `Bot` 或 Mail client；只能产出 `SendRequest`。
- 发送失败必须进入统一错误分类，不能只在日志里吞掉。

## 失败处理

| 失败 | 用户侧行为 | 审计细节 |
| --- | --- | --- |
| 命令非法 | 说明格式。 | 原始命令和解析错误。 |
| 收件人歧义 | 要求选择或配置联系人。 | 候选 id，必要时脱敏。 |
| 权限拒绝 | 说明功能/目标未启用。 | ACL 主体和规则。 |
| 限频 | 说明冷却或已排队。 | 限制规则和重试时间。 |
| 上下文不可用 | 降级为无个性化或请求同意。 | 缺失来源或同意状态。 |
| 草稿被拦截 | 说明无法按当前内容发送。 | 审查类别和 debug id。 |
| 确认过期 | 要求重新生成草稿。 | 草稿 id、过期时间、发送人。 |
| 临时发送失败 | 展示排队/重试状态。 | transport 异常和重试次数。 |
| 最终失败 | 展示每个收件人的失败汇总。 | provider 响应，脱敏。 |

## 模块边界

建议未来代码结构：

```text
plugins/bot_unified_runtime/contracts/
  runtime.py
  auto_send.py

plugins/bot_unified_runtime/policy/
  permissions.py
  quotas.py
  privacy.py

plugins/bot_unified_runtime/capabilities/auto_send/
  parser.py
  recipients.py
  personalization.py
  drafts.py
  confirmation.py

plugins/bot_unified_runtime/output/
  reviewer.py
  renderer.py
  censor.py

plugins/bot_unified_runtime/sender/
  queue.py
  chat_transport.py
  mail_transport.py
  receipts.py

plugins/bot_unified_runtime/audit/
  logger.py
```

依赖规则：

- `capabilities/auto_send` 依赖 contracts、policy、memory query 和 draft storage。
- `capabilities/auto_send` 不依赖具体 OneBot/NapCat/Mail API。
- `sender/*` 依赖 transport adapter 并返回 receipts。
- `audit/*` 接收能力层和发送层的阶段事件。

## 验收检查

首版实现应测试：

- 命令解析为 `AutoSendIntent`。
- 无效收件人生成 `RecipientResolution.resolved=false`。
- 歧义收件人不能发送。
- 生成草稿后必须预览才能生成 `SendRequest`。
- 旧草稿被新草稿 supersede 后确认失败。
- 批量发送为每个收件人创建一个 `SendRequest`。
- 每个收件人的个性化上下文相互隔离。
- `personalization_mode=full` 没有同意时失败。
- 邮件必须有 subject 和 text body。
- 最终输出审查能阻断标题或正文。
- transport 失败创建 `DeliveryReceipt.failed_retryable` 或 `failed_final`。
- 阻断、取消、过期、已发送、失败都创建 `AuditRecord`。
- 自动发送任何路径都不能在 `SendRequest` 前直接调用 transport API。

## 实现里程碑

### Milestone A: Draft-Only

- 定义 `AutoSendIntent`、`RecipientResolution`、`PersonalizationContext`、`GeneratedDraft`、`DraftPreview`。
- 解析命令为严格 intent。
- 只解析已配置联系人。
- 生成占位草稿或经审查的 LLM 草稿。
- 支持预览、确认、取消状态，但不真实发送。

### Milestone B: Chat Message Transport

- 确认后的聊天草稿转为 `SendRequest`。
- 加入队列、去重、冷却和回执。
- 首先只支持 allowlisted 私聊。
- 全状态审计。

### Milestone C: Mail Transport

- 增加 `MailTransportAdapter`。
- 要求机器人邮件账户和 allowlisted 联系人地址。
- 单独审查标题和正文。
- 返回每个收件人回执和批量汇总。

### Milestone D: Batch And Scheduling

- 批量预览分页。
- 延迟发送调度。
- 重试策略和完成汇总。
- 收件人 opt-out 控制。

## 设计结论

采用保守路线：

- 自动发送是统一运行时里的普通 capability。
- 个性化和草稿生成与 transport 分离。
- 每次真实发送都先预览、再确认。
- 参考 Bison 队列、class-schedule 预览确认、access-control 权限、chatrecorder 查询、ai-groupmate 最新请求保护、word-censor 最终钩子、OutputPro 中央流水线。

这样首版足够小，也为未来通道和插件保留清晰接口。
