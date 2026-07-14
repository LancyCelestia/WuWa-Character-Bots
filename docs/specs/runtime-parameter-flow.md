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
- `sender_roles`
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
- `actor_roles`
- `audit_tags`

规则：

- 权限角色必须来自配置名单，不由 LLM 或用户文本决定。首版角色包括 `user`、`trusted`、`enterprise`、`admin` 和 `blocked`。
- 配置名单通过 `WUWA_ADMIN_USER_IDS`、`WUWA_ENTERPRISE_USER_IDS`、`WUWA_TRUSTED_USER_IDS`、`WUWA_BLOCKED_USER_IDS` 输入，支持 JSON 数组、英文逗号和分号分隔。
- 角色参数流为 `Config -> RoleSettings -> IncomingMessage.sender_roles -> PolicyEvaluation.actor_roles -> BotDecision.actor_roles`。`blocked` 在 policy 阶段直接阻断；其他角色先写入审计标签，供后续高风险能力、企业能力和管理员确认复用。
- 群命令前缀必须使用 `WUWA_RUNTIME_GROUP_COMMAND_PREFIX`，不能在策略层硬编码 `/wuwa`。不匹配当前前缀且未提及机器人的群消息继续保持观察模式。
- `passive_group_message` 是静默阻断：NoneBot 聊天入口必须记录诊断和审计，但不能把 `DeliveryReceipt.public_message` 发送回群里，避免“未启用主动回复”本身变成群聊噪音。
- 状态诊断、`/wuwa roles` 和 smoke 只能显示各角色数量、角色顺序、绕过规则和输入格式，不能直接列出用户 ID。
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
- `actor_roles`

规则：

- 群聊通常 `max_messages=1`。
- 当前实现通过 `ReplyBudgetSettings` 计算 `BotDecision.max_messages` 和 `BotDecision.context_budget`。普通私聊默认 1 条；私聊情绪支持类输入最多 2 条；私聊深度帮助、教程、排查类输入最多 3 条；群聊和中高风险输入会强制压回配置的安全上限。
- 对应配置参数为 `WUWA_REPLY_PRIVATE_DEFAULT_MAX_MESSAGES`、`WUWA_REPLY_PRIVATE_SUPPORT_MAX_MESSAGES`、`WUWA_REPLY_PRIVATE_DEEP_HELP_MAX_MESSAGES`、`WUWA_REPLY_GROUP_MAX_MESSAGES`、`WUWA_REPLY_RISK_MAX_MESSAGES`、`WUWA_REPLY_DEFAULT_CONTEXT_BUDGET`、`WUWA_REPLY_SUPPORT_CONTEXT_BUDGET`、`WUWA_REPLY_DEEP_HELP_CONTEXT_BUDGET` 和 `WUWA_REPLY_GROUP_CONTEXT_BUDGET`。
- 预算结果必须写入 `reply_budget:*` 审计标签，并继续传递到 `SendRequest.max_messages`。
- 当前实现还通过 `InMemoryRateLimiter` / `SQLiteRateLimiter` 在调用 `wuwa.chat` 的 `LLMProvider` 前做窗口限速。它读取 `ReplyBudget.max_messages` 作为本次消耗量，按全局、会话和发送者三个桶统计回复预算；命中后在 policy 阶段返回 `rate_limited`，不调用 LLM，不创建 `SendRequest`。
- 对应配置参数为 `WUWA_RATE_LIMIT_ENABLED`、`WUWA_RATE_LIMIT_WINDOW_SECONDS`、`WUWA_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS`、`WUWA_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS`、`WUWA_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS`、`WUWA_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS`、`WUWA_RATE_LIMIT_BYPASS_ROLES` 和 `WUWA_RATE_LIMIT_DB_PATH`。默认窗口 60 秒、全局 60、会话 6、发送者 4，目标最小间隔默认 `0` 表示关闭，`admin` 角色可绕过。未配置 DB path 时使用同进程内存限速；配置 DB path 后使用 SQLite 持久限速，重启后仍保留窗口内记录和目标间隔记录。
- 限速允许时会把 `rate_limit:ok`、`rate_limit:disabled`、`rate_limit:non_chat` 或 `rate_limit:bypass_role` 写入审计标签；限速阻断时会写入 policy 阶段的 `rate_limited` 审计事件和安全 `rate_limited` 诊断标签。允许的安全细分标签包括 `rate_limit:global_window_exceeded`、`rate_limit:session_window_exceeded`、`rate_limit:sender_window_exceeded` 和 `rate_limit:target_min_interval`；不能在用户侧展示 sender_id、session_id、target_id 或内部 bucket key。
- 当前实现还通过 `QuietHoursChecker` 在 policy 允许后、回复预算/LLM 调用前做安静时间阻断。对应配置参数为 `WUWA_QUIET_HOURS_ENABLED`、`WUWA_QUIET_HOURS_START`、`WUWA_QUIET_HOURS_END`、`WUWA_QUIET_HOURS_TIMEZONE`、`WUWA_QUIET_HOURS_SESSION_TYPES` 和 `WUWA_QUIET_HOURS_BYPASS_ROLES`。默认关闭，默认窗口为 `23:00-07:00`、时区 `Asia/Hong_Kong`、作用会话类型为 `group`、`admin` 角色可绕过。
- 安静时间命中后会在 policy 阶段返回 `quiet_hours`，不调用 LLM，不创建 `SendRequest`，写入 `quiet_hours_blocked` 审计事件和安全 `quiet_hours_blocked` 诊断标签。`why-smoke` 和 `/wuwa why` 只能说明“安静时间，已在调用 LLM 前阻断”，不能展示目标 ID、原始用户消息或内部决策细节。
- `send_policy` 只能是 `immediate`、`queued`、`digest`、`private_fallback`、`admin_confirm`、`silent_audit`。
- 不回复的负向决策，在有排障价值时仍要写 `AuditRecord`。

### 3.1 基础 LLM 对话上下文

输入：通过策略门的 `IncomingMessage`、人格/知识配置、LLM 配置。

当前实现参数流：

```text
IncomingMessage.request_id
IncomingMessage.sender_id
IncomingMessage.session_id
IncomingMessage.plain_text
-> FileCharacterContextProvider.build_context(...)
-> ContextBundle(persona, tone, emotion_signals, memory_results, conversation_history, knowledge_results, current_message)
-> build_chat_prompt_with_diagnostics(ContextBundle)
-> LLMProvider.generate(messages, temperature, max_tokens)
-> CapabilityResult(capability_id="wuwa.chat")
```

规则：

- `wuwa_persona_files` 和 `wuwa_knowledge_files` 读取 `.md` / `.txt` / `.docx`。
- 人格文件进入 `PersonaProfile.identity`、`style_rules`、`role_boundaries` 和 `forbidden_behaviors`。
- 知识文件按 `wuwa_knowledge_chunk_chars` 切成 `KnowledgeChunk`，最多注入 `wuwa_knowledge_max_chunks` 条。
- `MemoryRetrievalResult` 默认由空实现提供；配置 `wuwa_memory_enabled=true` 和 `wuwa_memory_db_path` 后，首版 `SQLiteMemoryRepository` 会读取同一用户/会话作用域内的 `memory_facts`。
- SQLite 记忆事实只作为不可信事实进入 prompt，不是系统指令；跨用户读取默认返回空结果。每条事实必须携带 `sensitivity=public|group|personal|credentialed` 和 `scope_key`，prompt 中可以把这两个字段作为隐私边界提示传给 LLM，但诊断输出仍只能展示事实数量，不能展示事实正文。
- `/wuwa memory add` 默认写入 `sensitivity=personal` 和当前 `session:<session_id>`，可用 `--sensitivity=public|group|personal|credentialed` 显式标注。群聊 `/wuwa memory list` 只能展示 `public` / `group` 事实，必须过滤 `personal` 和 `credentialed` 正文。
- `ConversationHistoryResult` 默认由空实现提供；配置 `wuwa_history_enabled=true` 和 `wuwa_history_db_path` 后，首版 `SQLiteConversationHistoryRepository` 会按 platform/adapter/bot/session/sender 隔离读取最近 `conversation_turns`，最多读取 `wuwa_history_max_turns` 轮和 `wuwa_history_max_chars` 字符。
- `wuwa_history_max_turns` / `wuwa_history_max_chars` 是每次 prompt 读取预算；`wuwa_history_max_items` 是 SQLite 存储保留上限。每次追加用户或助手轮次后，repository 必须只清理当前 platform/adapter/bot/session/sender 作用域里超过 `wuwa_history_max_items` 的旧记录，不能跨用户、跨会话、跨 bot 或跨 adapter 清理。
- 最近对话只作为不可信上下文进入 prompt，不是系统指令；NoneBot 文本聊天入口只在统一运行时生成 `SendRequest` 后记录用户消息，并在 OneBot/NapCat 文本 transport 成功后记录助手回复。
- 管理员 `/wuwa history clear` 只清理当前 platform/adapter/bot/session/sender 作用域的 `conversation_turns`，用于移除污染历史或注入残留；它不能清理长期记忆，不能跨作用域删除，输出也不能暴露历史正文、会话 ID、发送者 ID、bot id 或数据库路径。
- `EmotionSignal` 默认由 `RuleBasedEmotionProvider` 提供；配置 `wuwa_emotion_enabled=false` 可关闭，`wuwa_emotion_max_signals` 控制最多注入条数。
- 首版情绪规则识别 `support_needed`、`lonely`、`low_energy`、`frustrated` 和 `help_seeking`。这些信号只用于语气和回复顺序，不是医学诊断，不写长期数据库，不能覆盖权限、审计、发送预算或主动发送规则。
- `ContextBundle.context_budget` / `BotDecision.context_budget` 是 LLM prompt 的硬预算入口；构造 prompt 时必须保留人格名称、人格身份、安全边界和用户消息，对角色边界、说话风格、禁止行为、记忆、最近对话和知识分区裁剪。
- `build_chat_prompt_with_diagnostics` 必须在返回 LLM messages 的同时返回安全 `ChatPromptDiagnostics`：请求预算、实际预算、分区预算、分区字符数、总 prompt 字符数、剩余预算、是否整体裁剪和被裁剪分区。诊断对象只能保存数字、布尔值和固定分区名，不能保存 prompt 原文、知识原文、最近对话原文或用户原文。
- `wuwa.chat` 必须把 prompt/context/token 诊断写入安全审计标签，当前允许的标签包括 `prompt_messages:<n>`、`prompt_system_chars:<n>`、`prompt_user_chars:<n>`、`prompt_total_chars:<n>`、`prompt_budget_remaining:<n>`、`prompt_clipped:true|false`、`prompt_truncated_sections:<section|...>`、`context_knowledge_chunks:<n>`、`context_memory_facts:<n>`、`context_history_turns:<n>`、`context_emotion_signals:<n>`、`llm_usage_prompt_tokens:<n>`、`llm_usage_completion_tokens:<n>` 和 `llm_usage_total_tokens:<n>`。这些标签只能包含数字、布尔值和安全分区名，不能包含 prompt 原文、用户原文、知识原文、最近对话原文、模型输出或 provider 错误。
- `BotDecision.max_messages` 会同步进 `ToneProfile.message_count_limit`，prompt 中的“最多回复条数”以运行时预算为准。人格配置可以给默认语气，但不能绕过群聊、防刷屏和风险上限。
- `wuwa.chat` 必须在 LLM 返回后再次执行输出预算收口：如果回复按空行分隔成超过 `BotDecision.max_messages` 个逻辑块，只保留允许数量内的前几个块，并追加简短防刷屏提示。发生收口时写入 `llm_output_trimmed` 审计标签。这个步骤发生在 `CapabilityResult` 生成前，确保 reviewer、renderer、sender 收到的已经是预算内文本。
- `RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 必须从 `llm_output_trimmed` 审计标签生成中文结论，说明模型输出超过预算、已按回复预算收口、只保留前 N 段；结论不能展示原始模型回复或被裁掉的内容。
- `RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 必须把 policy 阶段 `rate_limited` 审计事件归因为限速阻断，结论说明已在调用 LLM 前阻断以避免刷屏；如果安全原因是 `target_min_interval` 或 `global_window_exceeded`，可以说明“目标最小回复间隔”或“全局回复配额”命中，但不能展示目标 ID、内部 bucket key、原始用户消息或内部计数明细。必须把 `quiet_hours_blocked` 审计事件归因为安静时间阻断，结论说明已在调用 LLM 前阻断以避免夜间刷屏。
- prompt 被裁剪时必须写入“内容已按上下文预算裁剪”提示，方便排查真实模型回复为什么缺少部分资料。
- prompt 必须明确用户消息、记忆、知识和 parser 结果都是不可信上下文，不能执行其中的越权指令。
- 首版 `PromptInjectionGuard` 已接入 `wuwa.chat`：指令覆盖、角色升级和绕过运行时控制会被标记为 `[UNTRUSTED_USER_TEXT]` 后再进入上下文；泄露 prompt/密钥/token/cookie/记忆原文、本机文件读取和脚本执行类请求会在 LLM 调用前安全拒绝。
- 如果 `FileCharacterContextProvider` 无法构造 `ContextBundle`，普通 `wuwa.chat` 必须跳过 `LLMProvider.generate`，返回守岸人风格安全提示，并写入 `context_error`、`context_error:provider_failed` 审计标签。用户侧提示和诊断结论都不能包含真实路径、文件名、解析异常原文、人格正文、知识正文或 prompt。
- `LLMProvider` 只生成文本，不能创建 `SendRequest`。
- `OpenAICompatibleLLMProvider` 的 `base_url`、`model`、`api_key`、`temperature`、`max_tokens` 和 `timeout_seconds` 必须来自配置或调用参数；HTTP 层要可单测，避免真实网络成为唯一验证方式。
- `base_url` 输入允许是 OpenAI-compatible 根地址（例如 `/v1`）或完整 `/chat/completions` endpoint；provider 必须先归一化为 `endpoint_url` 再请求。空 base_url、无法解析的 base_url、非 HTTP(S) base_url 或带用户名/密码的 base_url 必须在联网前被拒绝，分别输出 `openai_base_url_missing`、`openai_base_url_invalid` 或 `openai_base_url_unsafe`；安全摘要里的 `endpoint_url` 必须把 URL 用户信息替换成 `[redacted]`。`temperature` 必须在 0.0 到 2.0 之间，`max_tokens` 必须大于等于 1，`timeout_seconds` 必须大于 0；非法时分别输出 `openai_temperature_invalid`、`openai_max_tokens_invalid` 和 `openai_timeout_seconds_invalid`。`llm-smoke` 必须先检查 provider、真实 API key、model、base_url 和生成参数；缺少任何一项、base_url 不安全或生成参数非法时只输出 `config_missing` 和安全原因码，不发起 provider 调用。普通 `wuwa.chat` 能力也必须消费同一套生成参数预检结果：命中时在调用 `LLMProvider.generate` 前返回角色化兜底，写入 `llm_preflight_blocked`、`llm_preflight_error:<reason>` 和 `llm_error:config_missing` 审计标签。`RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 必须把这类标签解释为“LLM 生成参数或配置非法，已在调用 provider 前阻断”，并且只展示稳定原因码白名单：`openai_temperature_invalid`、`openai_max_tokens_invalid`、`openai_timeout_seconds_invalid`；不能展示 API key、Authorization/Bearer、用户原文、prompt、原始 provider 错误或任意非白名单原因。预检通过后才打印同一个安全 `endpoint_url`、诊断调用参数并执行短调用，避免真实模型接入时重复拼接路径、误用空地址或把凭据放进 URL。
- `chat-smoke` 必须同时报告 pipeline 发送状态、LLM 状态、安全 `llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status=ready|local_only|blocked`、`llm_next_action=fix_config|configure_real_llm|llm_smoke`、`llm_readiness_reasons`、`reply_preview_chars` 和 `reply_text_hidden=true`。`receipt_state=sent` 只能说明内存 sender 接受输出，不代表真实模型成功，也不代表真实 NapCat 投递成功；真实 provider 下 `llm_error` 必须通过 `llm_status=error` 与 `llm_error_kind=<kind>` 暴露。LLM 就绪字段必须复用 `config-smoke` 的只读配置体检逻辑，只输出稳定原因码和下一步动作，不能展示 API key、真实文件路径、原始解析异常、provider 错误或完整模型回复。
- `dialogue-smoke` 是一轮基础对话验收入口。它必须复用 `context-smoke` 的安全上下文摘要和 `chat-smoke` 的 pipeline 结果，输出 `dialogue_status=ready|local_only|blocked`、`next_action`、`context_ok`、`chat_pipeline_ok`、`receipt_state`、人格/知识来源安全指纹、情绪/记忆/历史/prompt 数字摘要、回复预算、LLM 状态、安全 `llm_error_kind`、LLM 就绪字段、`llm_fix_hints`、`reply_preview_chars` 和 `reply_text_hidden=true`。默认 `static` provider 不访问外部网络；真实 `openai_compatible` provider 如果配置体检已是 `blocked`，必须直接返回 `next_action=fix_config`、`llm_status=not_called` 和 `receipt_state=not_created`，不能调用 provider；真实 provider 下出现其他 `llm_error` 必须非零退出，避免把角色化兜底误判为真实模型成功。它不能连接或启动 NapCat，不能发送 QQ，不能输出完整回复、prompt、用户原文、知识原文、最近对话原文、真实文件路径、数据库路径、API key、Authorization/Bearer 或 provider 错误原文。
- `persona-smoke` 是守岸人人格自检入口。它必须复用 `config-smoke` 的只读配置体检和 `FileCharacterContextProvider` 的上下文构造边界，只输出 `persona_status=ok|weak|blocked`、`persona_next_action`、人格 id/显示名/版本、人格/知识来源安全指纹、人格文件计数、可读性、字符数、有效行数、强度状态、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪字段和安全 `llm_fix_hints`。它不能调用 `LLMProvider.generate`，不能启动或连接 NapCat，不能创建真实业务发送，也不能输出人格正文、知识正文、完整 prompt、用户原文、真实文件路径、文件名、数据库路径、API key、Authorization/Bearer 或 provider 错误原文。
- 管理员可用 `/wuwa dialogue [测试文本]` 在线查看同类一轮对话验收摘要。该命令必须复用 `dialogue-smoke` 的聚合逻辑，并继续经过 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`；它可以在真实 provider 配置完整时短调用 `LLMProvider.generate` 做验收，但只能输出安全白名单字段、稳定下一步动作、稳定错误类型和 `reply_text_hidden=true`，不能展示完整模型回复、prompt、用户原文、知识原文、最近对话原文、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id 或 provider 错误原文。该命令自身不能覆盖最近业务诊断。
- `readiness-smoke` 是接真实 LLM 前的聚合就绪入口。它必须复用 `doctor`、`config-smoke`、`context-smoke` 和本地聊天 pipeline 的安全结果，输出 `readiness_status=ready|local_only|blocked`、`next_action`、`recommended_commands`、`ready_for_local_dialogue`、`ready_for_real_llm`、`context_ok`、`chat_pipeline_ok`、`chat_pipeline_mode=local_static_probe`、`chat_receipt_state`、`real_llm_probe_performed=false`、LLM 就绪三态和稳定原因码。它只能用静态本地探针验证基础对话链路，不能调用真实 LLM provider、不能连接或启动 NapCat、不能发送 QQ、不能输出完整回复、prompt、真实文件路径、数据库路径、API key、Authorization/Bearer 或 provider 错误原文。
- 管理员可用 `/wuwa readiness` 在线查看同类统一就绪摘要。该命令必须复用 `readiness-smoke` 的聚合逻辑，并继续经过 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`；它只能输出安全白名单字段、稳定下一步动作和安全 `llm_fix_hints`，必须固定 `real_llm_probe_performed=false`。在线入口还必须注入同进程 `RuntimeControlState`，展示 `runtime_soft_paused=true|false`、安全 reason 和 `updated_by=set|missing`，用于区分“配置就绪但当前被管理员软暂停”；不能调用真实 LLM provider、不能启动或连接 NapCat、不能发送外部业务消息、不能输出完整回复、prompt、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id、具体管理员 ID 或 provider 错误原文。该命令自身不能覆盖最近业务诊断。
- 管理员可用 `/wuwa roles` 在线查看权限角色规则矩阵。该命令必须从 `Config -> RoleSettings` 读取角色配置，只输出 `role_order`、各角色数量、`blocked_policy`、限速/安静时间绕过角色、群命令前缀、ID 输入格式、角色来源配置项、管理员命令集合和 `ids_hidden=true`；它必须继续经过 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`，不能调用 LLM、不能启动或连接 NapCat、不能发送外部业务消息，也不能输出具体 user_id、`session_id`、目标 ID、数据库路径、`provider_message_id`、`private_debug` 或原始配置文本。该命令自身不能覆盖最近业务诊断。
- 管理员可用 `/wuwa persona` 在线查看人格自检摘要。该命令必须复用 `persona-smoke` 的只读逻辑，并继续经过 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`；它只能输出人格状态、下一步动作、人格/知识来源安全指纹、人格强度、规则计数、语气参数、记忆/历史/情绪开关和 LLM 就绪摘要，不能调用 LLM、不能启动或连接 NapCat、不能发送外部业务消息，也不能输出人格正文、知识正文、完整 prompt、真实文件路径、文件名、数据库路径、目标 ID、provider message id、API key、Authorization/Bearer 或 `private_debug`。该命令自身不能覆盖最近业务诊断。
- 管理员可用 `/wuwa pause` 和 `/wuwa resume` 控制当前进程的运行时软暂停。软暂停必须发生在 policy 之前：普通聊天、自动发送预览和非排障能力被阻断，不调用 LLM，不创建 `SendRequest`；`status`、`why`、`receipt`、`audit`、`recent`、`queue`、`context`、`llm`、`config`、`readiness`、`dialogue`、`roles`、`history clear` 和 `resume` 必须绕过软暂停，避免事故排障时失去控制入口。该状态只保存在当前进程内，不能伪装成已修改 `.env`；长期硬开关仍由 `WUWA_RUNTIME_ENABLED` 决定。输出只能展示 `runtime_paused`、安全 reason 和 `updated_by=set|missing`，不能展示具体 user_id、`session_id`、目标 ID、数据库路径或 `private_debug`。
- `/wuwa status` 和在线 `/wuwa readiness` 必须把长期硬开关和当前进程软暂停分开展示：`运行时硬开关：enabled|disabled` 来自 `WUWA_RUNTIME_ENABLED`，`运行时软暂停：true|false` 或 `runtime_soft_paused=true|false` 来自同进程 `RuntimeControlState`，并只展示安全 reason 与 `updated_by=set|missing`。这些字段不能混写，避免把 `.env` 硬关闭、管理员临时 pause 和 LLM/provider 配置问题混在一起。
- 管理员可用 `/wuwa context [测试文本]` 在线查看 LLM 上下文安全摘要。该命令会复用 `PromptInjectionGuard`、`ReplyBudgetSettings`、`FileCharacterContextProvider` 和 `build_chat_prompt_with_diagnostics`，但不调用 `LLMProvider.generate`；输出只展示人格/知识来源安全指纹、人格/知识/记忆/历史/情绪/预算/prompt 长度、总字符数、剩余预算、是否整体裁剪、被裁剪分区和分区字符统计等摘要。`persona_source_refs` 和 `knowledge_source_refs` 必须由文件后缀、可读状态、长度或 chunk 形状等安全材料生成短 hash，不能包含原始路径、文件名、正文、解析异常、数据库路径、目标 ID、密钥或 provider message id。
- 管理员可用 `/wuwa llm` 在线查看真实 LLM provider 连接诊断。该命令会先复用只读配置体检结果输出 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons` 和 `llm_fix_hints`；只有 provider、真实 API key、model、安全 base_url 和合法生成参数都具备时才短调用 `LLMProvider.generate`。短调用只使用固定诊断 prompt，不读取人格、记忆、历史或知识，不发送外部聊天消息；输出只展示 `ok`、LLM 就绪字段、`provider`、`model`、`endpoint_url`、`api_key=set|missing`、`diagnostic_temperature`、`diagnostic_max_tokens`、`timeout_seconds`、`error_kind`、`reply_preview_chars`、`usage_total_tokens` 和 `public_message`。非管理员、未配置真实 provider、缺少真实 API key/model/base_url、使用占位 key 或生成参数非法时都不能发起真实 provider 调用。
- `LLMProviderError.error_kind` 必须是稳定枚举式字符串，用于本地 `llm-smoke`、管理员 `/wuwa llm`、普通对话审计标签和 `/wuwa why` 诊断。当前允许值包括 `provider_not_configured`、`config_missing`、`timeout`、`auth`、`rate_limited`、`server`、`http`、`network`、`schema`、`empty_response` 和 `provider_error`；普通聊天用户侧只展示角色化安全兜底，管理员诊断侧只展示安全 `public_message` 或 “LLM 调用失败，错误类型是 <kind>”，不能展示原始上游错误。
- `config-smoke` 是真实 LLM 接入前的只读配置体检入口。它只能读取本地配置和文件状态，不能调用 `LLMProvider.generate`、不能启动 NoneBot/NapCat、不能创建 `SendRequest`。它输出 `ready_for_real_llm`、`llm_readiness_status=ready|local_only|blocked`、`llm_next_action=fix_config|configure_real_llm|llm_smoke`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格/知识文件计数、可解析性计数、人格安全强度摘要、`chat_provider`、`chat_model`、`endpoint_url`、`chat_api_key=set|missing`、`chat_temperature`、`chat_max_tokens` 和 `timeout_seconds`，用于在 `llm-smoke` 之前先排除本地配置错误。`ready` 表示真实 provider 关键配置和生成参数已具备且没有阻断错误，`local_only` 表示本地 pipeline 可验但真实 provider 尚未就绪，`blocked` 表示必须先修复阻断错误；`llm_next_action` 必须只输出稳定机器码，分别表示修配置、配置真实模型或继续跑 `llm-smoke`；`llm_readiness_reasons` 必须是去重后的 errors + warnings；`llm_fix_hints` 必须由稳定原因码映射，只能包含配置项名、推荐范围和占位值。人格文件不可读或为空必须是 error；人格材料过薄可以是 `persona_profile_weak` warning；配置了但不可读的知识文件必须是 error；知识文件为空可以是 warning；生成参数非法必须是 error。人格强度摘要只能包含 `persona_total_chars`、`persona_meaningful_lines` 和 `persona_strength_status=ok|weak|missing`，不能包含正文、路径或文件名。
- 管理员可用 `/wuwa config` 在线查看同类配置体检摘要。该命令必须复用 `config-smoke` 的只读检查逻辑，并继续经过 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`；它可以展示 `llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`history_max_items`、人格字符数/有效行数/强度状态等安全摘要，但不能调用 `LLMProvider.generate`，不能启动或连接 NapCat，不能展示 API key、数据库真实路径、目标 ID、provider message id、真实文件路径、人格正文或原始解析错误。
- NoneBot 基础聊天入口在取得 `SendRequest` 后，必须再调用 sender/transport adapter。当前 OneBot/NapCat transport 是 `send_onebot_v11`：它只接收 `SendRequest` 和 OneBot bot 对象，把 `RenderedOutput.content_type` 转成 OneBot 消息段，不读取人格/LLM 内部状态。

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
- 当前最低限度输出泄漏防线会阻断内部上下文标记和明显密钥形态，例如 `[UNTRUSTED_USER_TEXT]`、`api_key=...`、`token=...`、`cookie=...`、`authkey=...`、`Authorization: Bearer ...` 或 `sk-...`。
- 当前 `wuwa.chat` 输出人格漂移防线会阻断通用 AI 身份输出，例如“作为 ChatGPT/OpenAI/AI 语言模型”、拒绝成为守岸人或否认角色人格。被阻断时 `ReviewResult.reasons` 必须包含 `persona drift:*`，方便 `/wuwa why` 和审计查询定位。
- 纯人格漂移阻断可以返回角色化安全兜底提示，说明可以重新提问，但该提示只能来自白名单模板；被阻断的原始模型输出不能进入 `RenderedOutput` 或 `SendRequest`。
- 输出审查原因进入 `AuditRecord(stage="review")` 前必须脱敏，不能让审计日志二次泄漏密钥。
- 用户侧诊断不能展示 `ReviewResult.reasons` 或 `AuditRecord.private_debug` 原文。`RuntimeDiagnostic` 只能把 review 阻断归一化为安全标签，例如 `review_blocked`、`persona_drift`、`unsafe_output_leakage`，并生成中文结论。

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
- 当前实现默认使用进程内 `InMemorySendQueue` 做即时接收和去重；配置 `WUWA_SEND_QUEUE_ENABLED=true` 且 `WUWA_SEND_QUEUE_DB_PATH` 后，`SQLiteSendRequestQueue` 会把 `SendRequest` 写入 SQLite `send_requests` 表。
- SQLite 发送队列必须按 `dedupe_key` 去重，支持按 `next_retry_at` 查找到期请求，失败后写入 `failed_retryable`、`retry_count` 和下一次重试时间，并在 `WUWA_SEND_QUEUE_MAX_ATTEMPTS` 后封顶为 `failed_final`。
- SQLite 发送队列必须提供 `claim_due()` 原子认领：把到期的 `queued` / `failed_retryable` 请求切换为内部 `processing` 租约状态，写入原始状态和 `lease_expires_at`；租约过期后必须允许重新认领，真实投递成功、可重试失败或最终失败后必须清除租约字段。`processing` 是队列表内部状态，不加入公开 `DeliveryReceipt` 状态枚举。
- 发送队列还应提供只读 `find_request(request_id)`。进程内队列可以从本地镜像查找，SQLite 队列必须从 `send_requests.request_json` 恢复 `SendRequest`，用于 `/wuwa why` 和运行诊断在重启或队列对象重开后仍能判断 `send_request_created`。该接口不能成为公开列表接口，不能向用户侧输出目标 ID、正文、`dedupe_key`、数据库路径或 provider message id。
- 当前代码层已有 `drain_send_queue_once()` 一次性 worker：它优先通过 `claim_due()` 认领到期项，再调用注入的 transport，记录 transport `DeliveryReceipt`，并把队列项标记为 `sent`、`failed_retryable` 或 `failed_final`。它不能读取人格、LLM prompt、原始消息或绕过审查。`queue-smoke` 只用临时 SQLite 队列和 fake transport 验证这条状态推进链路；它不连接 NapCat，不代表真实账号投递成功。
- NoneBot 入口可选注册后台 APScheduler worker，但默认关闭。只有 `WUWA_SEND_QUEUE_WORKER_ENABLED=true` 且当前发送队列实现支持 `claim_due/list_due/mark_sent/mark_retryable_failure/mark_final_failure` 时，才注册 `wuwa_send_queue_worker`。worker 按 `WUWA_SEND_QUEUE_WORKER_INTERVAL_SECONDS` 间隔、每批最多 `WUWA_SEND_QUEUE_WORKER_BATCH_SIZE` 条调用同一个 `drain_send_queue_once()`；如果当前没有在线 bot，transport 返回 `failed_retryable`，让队列退避重试而不是崩溃或刷屏。
- `WUWA_SEND_QUEUE_MAX_ITEMS` 控制队列表裁剪；`WUWA_SEND_QUEUE_RETRY_BASE_SECONDS` 和 `WUWA_SEND_QUEUE_RETRY_MAX_SECONDS` 控制指数退避上限。
- 用户侧状态、`config-smoke`、`nonebot-smoke` 和管理员摘要只能展示发送队列开关、store、db=set/missing、状态计数、`processing` 租约计数、最大条数、最大尝试次数、退避秒数、worker 开关、worker 间隔和 worker 批量大小，不能展示 `target_id`、消息正文、`dedupe_key`、数据库真实路径或 provider message id。

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
- 当前 OneBot V11 transport 参数映射：
  - `SendRequest.target_scope=private` -> `bot.send_private_msg(user_id=target_id, message=segments)`
  - `SendRequest.target_scope=group` -> `bot.send_group_msg(group_id=target_id, message=segments)`
  - `RenderedOutput.content_type=text` -> `[{"type":"text","data":{"text": text}}]`
  - `RenderedOutput.content_type=image` 且 `content_ref.file/url/path` 存在 -> `[{"type":"image","data":{"file": file_ref}}]`
  - `RenderedOutput.content_type=card` 且 `content_ref.onebot_json/json/data` 存在 -> `[{"type":"json","data":{"data": json_string}}]`
  - `RenderedOutput.content_type=mixed` 且 `content_ref.parts` 存在 -> 按顺序组合 text/image/json 段，跳过无效 part
  - `forward` 只有在 `SendRequest.allow_forward=true` 且存在有效 `messages` 或 `nodes` 时，才能尝试 `send_group_forward_msg` / `send_private_forward_msg` 或对应 `call_api(...)`；不允许、节点缺失或 API 不可用时必须安全降级到 `RenderedOutput.text_fallback`
  - 返回 `message_id` -> `DeliveryReceipt.provider_message_id`
  - 发送异常 -> `ReceiptState.FAILED_RETRYABLE`，用户只看到 `debug_id`，不暴露 token/cookie/堆栈。
- 能力层仍不能构造 OneBot 原始调用或直接发送；它只能填充 `RenderedOutput.content_type/content_ref/text_fallback`，由 transport adapter 负责消息段转换和失败回执。
- NoneBot 入口层必须在真实 transport 后追加 `AuditRecord(stage="transport")`，用 `transport_sent`、`transport_failed_retryable`、`transport_blocked` 等事件区分内存 sender 接收和真实适配器投递。
- 当前实现默认把回执存在进程内 `InMemoryReceiptRepository`。配置 `WUWA_RECEIPTS_ENABLED=true` 和 `WUWA_RECEIPTS_DB_PATH` 后，回执会写入 SQLite `delivery_receipts` 表；`WUWA_RECEIPTS_MAX_ITEMS` 控制最多保留条数。
- 回执和发送队列的职责不同：`send_requests` 是待投递/重试真源，`delivery_receipts` 是投递结果记录。真实 transport 成功或失败后应同时产生 `DeliveryReceipt`，并在启用 SQLite 队列时更新对应请求的终态或重试状态。队列 worker 记录的是 transport 回执；队列状态更新产生的内部回执只用于审计和队列状态推进。
- `delivery_receipts.provider_message_id` 可保存 OneBot/NapCat 内部 message id 用于排障，但用户侧 `/wuwa why`、`/wuwa status`、`nonebot-smoke` 和普通审计摘要不能展示真实值。
- 管理员可用 `/wuwa receipt <request_id|debug_id>` 查询回执。该命令本身仍返回 `CapabilityResult`，并继续经过审查、渲染、发送、回执和审计；输出只允许展示 `request_id`、`debug_id`、`state`、`transport`、`retry_count`、`next_retry_at` 和脱敏后的 `public_message`。
- 非管理员查询回执必须拒绝，且拒绝信息不能透露目标记录是否存在。

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
- 私有调试信息可以记录堆栈和上游细节，但必须脱敏。当前脱敏覆盖 token、cookie、authkey、password、secret、api_key、Authorization/Bearer 和 `sk-...` 形态。
- 被拦截或失败的动作必须可观察、可定位、可修复。
- 当前实现默认使用进程内 `InMemoryAuditLogger`。配置 `WUWA_AUDIT_ENABLED=true` 和 `WUWA_AUDIT_DB_PATH` 后，审计会写入 SQLite `audit_records` 表；`WUWA_AUDIT_MAX_ITEMS` 控制最多保留条数。
- transport 审计可以说明 `provider_message_id=[internal]`，但不能把真实 provider message id 写入 `private_debug`。
- 管理员可用 `/wuwa audit <request_id>` 查询审计事件。用户侧输出只允许展示 `request_id`、`stage`、`event`、`severity` 和脱敏后的 `public_message`；不能展示 `session_id`、`private_debug`、原始消息、回复全文、目标 ID、provider message id、token、cookie、API key 或数据库真实路径。
- 非管理员查询审计必须拒绝，且拒绝信息不能透露目标记录是否存在。

### 10. RuntimeDiagnostic

输入：`IncomingMessage`、`PolicyEvaluation`、`BotDecision`、`SendRequest`、`DeliveryReceipt` 和脱敏审计摘要。

用途：

- 支撑 `/wuwa why [request_id|debug_id]`、`/wuwa recent [数量]`、`/wuwa queue`、`/wuwa context [测试文本]`、`/wuwa llm`、`/wuwa config`、`/wuwa readiness`、`/wuwa dialogue [测试文本]`、`/wuwa roles`、`/wuwa persona`、`/wuwa history clear`、`/wuwa pause`、`/wuwa resume` 和本地排障。
- 解释为什么回复、为什么不回复、为什么最多回复几条、是否创建发送请求、transport 是否成功。
- 默认使用进程内最近记录；配置 `WUWA_DIAGNOSTICS_ENABLED=true` 和 `WUWA_DIAGNOSTICS_DB_PATH` 后写入 SQLite `runtime_diagnostics`。
- `WUWA_DIAGNOSTICS_MAX_ITEMS` 控制最多保留多少条最近记录，避免 SQLite 无限增长。

规则：

- 只保存脱敏排障字段：`request_id`、`debug_id`、`session_id`、`capability_id`、策略原因、角色、风险、隐私、回复预算、prompt 安全数字摘要、上下文计数、安全 token usage、LLM 状态、安全 `llm_error_kind`、回执状态、审计事件、审计标签和结论。
- prompt 安全数字摘要只允许保存 `prompt_messages`、`system_prompt_chars`、`user_prompt_chars`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped` 和 `prompt_truncated_sections`；上下文计数只允许保存 `knowledge_chunks`、`memory_facts`、`history_turns` 和 `emotion_signals`；token usage 只允许保存 `llm_usage_prompt_tokens`、`llm_usage_completion_tokens` 和 `llm_usage_total_tokens`。这些字段用于排查上下文预算、分区裁剪和 token 异常，不能反推出或展示 prompt 原文。
- 不保存原始用户消息、回复全文、`private_debug`、目标 ID、API key、token、cookie、`dedupe_key` 或 OneBot provider message id。
- 构造诊断时可以通过发送队列内部 `find_request(request_id)` 恢复 `SendRequest`，尤其是 SQLite 队列重开后从持久化 `request_json` 判断发送请求是否创建。恢复后的对象只用于生成脱敏投影，例如 `send_request_created`、capability、预算和安全标签；不能把恢复出的 target、正文、`dedupe_key`、数据库路径或 provider message id 写入 `RuntimeDiagnostic` 或 `/wuwa why` 输出。
- review 阻断的诊断结论必须来自白名单归因，不允许把原始模型输出、审查私有原因或密钥样本拼进 `/wuwa why`、`why-smoke` 或 `runtime_diagnostics`。
- 输出预算收口的诊断结论必须来自 `llm_output_trimmed` 审计标签，只能说明收口事实和保留段数，不能保存或展示被裁掉的文本。
- LLM 调用失败的诊断结论必须来自 `llm_error:<kind>` 审计标签，只能说明稳定错误类型；其中 `llm_error:config_missing` 如果同时带有 `llm_preflight_blocked`，必须优先解释为生成参数或配置预检阻断，而不是普通 provider 调用失败。`RuntimeDiagnostic`、`why-smoke` 和 `chat-smoke` 可以输出安全字段 `llm_error_kind=<kind>`，但不能保存或展示原始 provider 错误、HTTP 响应正文、Authorization/Bearer、API key 或模型回复原文。`chat-smoke` 如需证明有回复，只能输出 `reply_preview_chars` 和 `reply_text_hidden=true`，不能打印 `reply_text` 全文。`RuntimeDiagnostic` 和 `why-smoke` 还必须保存/展示 `ready_for_real_llm`、`llm_readiness_status` 和 `llm_readiness_reasons`，`why-smoke` 和 `chat-smoke` 可以展示只读配置体检给出的 `llm_next_action`；这些字段必须来自 `config-smoke` 同一套只读体检逻辑，只能包含稳定原因码或稳定动作码，不能包含真实文件路径、原始解析异常或 provider 错误。`llm_fix_hints` 只允许在配置体检、人格自检、统一就绪、对话验收、LLM 连接诊断和 NoneBot 加载诊断这类安全摘要中出现，且只能包含配置项名、推荐范围和占位值，不能包含真实路径、密钥、prompt、用户原文或 provider 原始错误。
- 人格/知识上下文读取失败的诊断结论必须来自 `context_error` / `context_error:provider_failed` 审计标签。`RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 应把 `llm_status` 标记为 `not_run`，结论说明“人格或知识上下文读取失败，已跳过 LLM，返回安全提示”；不能把这类情况伪装成 provider 已调用，也不能展示路径、文件名、解析异常原文或上下文正文。
- `/wuwa recent [数量]` 可以合并展示最近运行诊断、发送回执和审计事件摘要；默认 5 条，最大 20 条。运行诊断摘要可以包含 `llm_readiness`、`ready_for_real_llm`、稳定 `llm_reasons` 和安全 `diagnostic_tags`，用于第一眼判断真实模型配置是否就绪，以及最近是否发生提示注入、审查阻断或历史记录跳过。`diagnostic_tags` 只能包含固定 ASCII 机器标签，不能包含自然语言用户文本、密钥、Authorization/Bearer、真实路径、`session_id`、目标 ID 或原始 provider 错误。该摘要只能展示安全白名单字段，不能暴露 `session_id`、目标 ID、原始消息、回复全文、`private_debug`、provider message id、Authorization/Bearer、API key 或密钥。
- `/wuwa queue` 可以展示发送队列安全摘要；它只能输出 `enabled`、`store`、`db=set|missing`、`queued`、`failed_retryable`、`failed_final`、`sent`、`skipped`、`processing`、`max_items`、`max_attempts` 和重试退避秒数，不能展示 `target_id`、正文、`dedupe_key`、数据库真实路径、人格 id 或 provider message id。
- `/wuwa history clear` 可以清理当前作用域最近对话历史；它只能输出安全说明和 `cleared_turns`，不能展示历史正文、`session_id`、`sender_id`、`bot_id`、数据库真实路径或长期记忆内容。
- `queue-smoke` 可以展示本地 worker 安全摘要；它只能输出 `checked`、`delivered`、`retryable_failed`、`final_failed`、`skipped`、`receipt_record_failed`、队列状态计数、`processing` 租约计数、回执数、审计事件数、fake transport 名称和 `real_transport_used=false`，不能展示 `target_id`、正文、`dedupe_key`、数据库真实路径、`private_debug` 或 provider message id。
- `/wuwa context [测试文本]` 展示当前会话将进入 LLM 的上下文投影摘要，必须由管理员触发，且自身不能调用 LLM、不能主动发送外部业务消息、不能暴露原始用户文本、完整 prompt、知识原文、真实文件路径、文件名或数据库路径；来源只能以 `persona_source_refs`、`knowledge_source_refs` 这类安全短指纹出现。
- `/wuwa llm` 展示真实 LLM provider 在线连接摘要，必须由管理员触发；它必须先做只读配置预检，缺少真实 API key、model 或 base_url 时不能短调用 provider。它可以展示 LLM 就绪三态、稳定原因码和下一步动作，但不能展示 API key、Authorization/Bearer、完整模型回复、原始 provider 错误、目标 ID、provider message id 或数据库路径。
- `/wuwa config` 展示当前进程看到的只读配置体检摘要，必须由管理员触发；它可以展示 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格材料强度等安全原因码、动作码或修复提示，但不能调用 provider、不能连接 NapCat、不能展示 API key、数据库真实路径、真实文件路径、人格正文、目标 ID、provider message id 或原始解析错误。
- `/wuwa readiness` 展示当前进程看到的统一就绪摘要，必须由管理员触发；它可以展示 `readiness_status`、`next_action`、`recommended_commands`、本地对话/真实 LLM/环境/config/context/chat/NoneBot/transport 安全状态、LLM 就绪原因码和安全 `llm_fix_hints`，但不能把本地静态探针解释成真实 provider 或真实 NapCat 投递。
- `/wuwa dialogue [测试文本]` 展示当前进程看到的一轮基础对话验收摘要，必须由管理员触发；它可以展示 `dialogue_status`、`next_action`、上下文安全计数、回复预算、LLM 状态、安全 `llm_error_kind`、LLM 就绪字段和 `reply_preview_chars`，但不能展示完整模型回复、原始测试文本、完整 prompt、知识原文、最近对话原文、真实路径、数据库路径、目标 ID、provider message id、API key 或 provider 错误原文。
- `/wuwa roles` 展示当前进程看到的权限角色规则矩阵，必须由管理员触发；它可以展示角色顺序、角色数量、拉黑策略、绕过规则、群命令前缀、输入格式和管理员命令集合，但不能展示具体 user_id、`session_id`、目标 ID、数据库路径、provider message id 或 `private_debug`。
- `/wuwa persona` 展示当前进程看到的人格自检摘要，必须由管理员触发；它可以展示人格状态、下一步动作、人格/知识来源安全指纹、人格强度、规则计数、语气参数、记忆/历史/情绪开关和 LLM 就绪字段，但不能展示人格正文、知识正文、完整 prompt、真实路径、文件名、数据库路径、目标 ID、provider message id、API key、Authorization/Bearer 或 `private_debug`。
- `/wuwa status` 展示当前进程配置摘要时，可以公开硬开关状态和软暂停状态，但只能使用 `enabled|disabled`、`true|false`、安全 reason 和 `updated_by=set|missing`；不能展示具体管理员 ID、`session_id`、目标 ID、数据库路径或 `private_debug`。
- `/wuwa pause` 和 `/wuwa resume` 展示当前进程软暂停状态，必须由管理员触发；它们可以展示 `runtime_paused`、安全 reason 和 `updated_by=set|missing`，但不能展示具体 user_id、`session_id`、目标 ID、数据库路径或 `private_debug`。非管理员查询或执行必须拒绝，且不能透露当前是否暂停。
- `/wuwa why`、`/wuwa receipt`、`/wuwa audit`、`/wuwa recent`、`/wuwa queue`、`/wuwa context`、`/wuwa llm`、`/wuwa config`、`/wuwa readiness`、`/wuwa dialogue`、`/wuwa roles`、`/wuwa persona`、`/wuwa history clear`、`/wuwa pause` 和 `/wuwa resume` 自身不能覆盖最近诊断记录。
- SQLite 持久化只改变记录保存位置，不改变能力、审查、渲染和发送链路。
- `RuntimeDiagnostic` 是用户侧解释投影，不是完整审计真源；完整排障应结合独立的 `audit_records` 和 `delivery_receipts` 内部表。

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
