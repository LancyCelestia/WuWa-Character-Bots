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
- 归一化发送者角色：从配置名单解析 `admin`、`enterprise`、`trusted` 和 `blocked`，写入 `IncomingMessage.sender_roles`，后续只通过 `PolicyEvaluation.actor_roles` 和 `BotDecision.actor_roles` 使用。
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
- 调用 LLM 前必须执行运行时回复预算、限速和安静时间检查；当前 `wuwa.chat` 在 policy 允许后先由 `QuietHoursChecker` 判断当前会话类型是否命中 `BOT_QUIET_HOURS_*`，再计算回复预算并由窗口限速判断全局/当前会话/发送者是否已经超出 `BOT_RATE_LIMIT_*` 上限，最后按 `BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` 判断同一目标是否过于频繁。安静时间或限速命中时都不能调用 provider。未配置 `BOT_RATE_LIMIT_DB_PATH` 时使用内存窗口，配置后使用 SQLite 持久窗口和目标间隔记录。
- 没有私聊同意时，脱敏密钥和个人账号标识。
- LLM 工具默认关闭，只有被选中的能力明确允许时才能打开。
- LLM 输出不能只相信 prompt 中的“最多回复条数”。自然语言对话能力必须在 provider 返回后按运行时 `max_messages` 做输出收口，并把收口事实写入 `llm_output_trimmed` 审计标签；`why-smoke` 和 `/wuwa why` 只能解释收口事实与保留段数，不能展示被裁掉的模型文本。
- `wuwa.chat` 产生的 prompt/context/token 诊断只能以安全投影进入审计和诊断：`prompt_messages`、`system_prompt_chars`、`user_prompt_chars`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`knowledge_chunks`、`memory_facts`、`history_turns`、`emotion_signals`、`llm_usage_prompt_tokens`、`llm_usage_completion_tokens` 和 `llm_usage_total_tokens`。这些字段只能是数字、布尔值和固定分区名，不能携带 prompt 原文、用户原文、知识原文、最近对话原文、模型输出或 provider 错误。
- `MemoryRetrievalResult.facts` 可以在内部 prompt 中携带 `sensitivity` 和 `scope_key`，用于提醒 LLM 这些记忆的隐私边界；但任何 smoke、管理员诊断、审计公开消息和群聊列表都不能展示 `personal` / `credentialed` 记忆正文。群聊 `/wuwa memory list` 只能展示 `public` / `group` 事实。
- 管理员 `/wuwa context [测试文本]` 只能构造并展示 LLM 上下文安全摘要：人格、人格/知识来源安全指纹、知识、记忆、最近对话、情绪、回复预算、prompt 长度、总字符数、剩余预算、是否整体裁剪、被裁剪分区和分区字符统计。`persona_source_refs` 和 `knowledge_source_refs` 只能是稳定短指纹，用来确认来源是否加载或变化；它不能调用 LLM，不能输出原始测试文本、完整 prompt、知识原文、数据库路径、真实文件路径、文件名、密钥、目标 ID 或 provider message id。
- 管理员 `/wuwa llm` 只能执行固定短 prompt 的 LLM provider 连接诊断。它不读取人格、记忆、历史或知识，不展示完整模型回复；非管理员、未配置真实 provider、缺少真实 API key、model、base_url、base_url 非法、base_url 非 HTTP(S)、base_url 带用户名/密码、占位 API key、`temperature` 非法、`max_tokens` 非法或 `timeout_seconds` 非法都不能触发真实 provider 调用。普通 `wuwa.chat` 能力也必须复用生成参数预检，命中时不调用 provider，只写入 `llm_preflight_blocked`、`llm_preflight_error:<reason>` 和 `llm_error:config_missing` 这类稳定审计标签。`why-smoke` 和 `/wuwa why` 解释这类标签时只能展示稳定原因码白名单：`openai_temperature_invalid`、`openai_max_tokens_invalid`、`openai_timeout_seconds_invalid`，并说明已在调用 provider 前阻断；不能展示 API key、Authorization/Bearer、用户原文、prompt 或原始 provider 错误。它可以展示 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons` 和 `llm_fix_hints`，但这些字段必须来自同一套只读配置体检逻辑。
- 本地 `config-smoke` 只能做只读配置体检。它可以报告人格/知识文件缺失、文件类型不支持、人格材料过薄、聊天关闭、provider 仍为 `static`、真实 provider 缺 key/model/base_url、base_url 非法、base_url 非 HTTP(S)、base_url 带用户名/密码、`temperature/max_tokens/timeout_seconds` 范围错误、`llm_readiness_status=ready|local_only|blocked`、稳定下一步动作 `llm_next_action=fix_config|configure_real_llm|llm_smoke`、去重原因码 `llm_readiness_reasons`、安全修复提示 `llm_fix_hints`、回复限速参数、全局/会话/发送者上限、目标最小间隔、`rate_limit_store/db`、安静时间参数等错误、警告或安全摘要。人格强度只能以 `persona_total_chars`、`persona_meaningful_lines` 和 `persona_strength_status=ok|weak|missing` 这类计数/状态输出；`endpoint_url` 必须脱敏 URL 用户信息；`llm_fix_hints` 只能包含配置项名、推荐范围和占位值；不能调用模型、不能连接 NapCat、不能发送消息，也不能输出 API key 原文、人格正文、真实文件路径、prompt、用户原文、provider 原始错误或 SQLite 路径。
- 本地 `persona-smoke` 只能做只读人格自检。它可以报告 `persona_status=ok|weak|blocked`、`persona_next_action`、人格 id/显示名/版本、`persona_source_refs`、`knowledge_source_refs`、人格文件计数、可读性、字符数、有效行数、`persona_strength_status`、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪字段、安全 `llm_fix_hints` 和安全 `public_message`。来源指纹只能是短 hash 或 `-`；不能调用模型、不能连接 NapCat、不能发送消息，也不能输出人格正文、知识正文、完整 prompt、用户原文、真实文件路径、文件名、数据库路径、API key、Authorization/Bearer、provider message id 或 provider 原始错误。
- 本地 `readiness-smoke` 只能输出聚合就绪白名单字段：`ok`、`readiness_status`、`next_action`、`recommended_commands`、`ready_for_local_dialogue`、`ready_for_real_llm`、`real_llm_probe_performed=false`、`doctor_ok`、`ready_for_local_llm_smoke`、`ready_for_nonebot_run`、`nonebot_ok`、`transport_ok`、`config_ok`、`context_ok`、`chat_pipeline_ok`、`chat_pipeline_mode=local_static_probe`、`chat_receipt_state`、`chat_reply_preview_chars`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`persona_strength_status`、`knowledge_readable`、`provider`、`model`、`chat_api_key=set|missing` 和安全 `public_message`。它不能调用真实 LLM provider，不能启动或连接 NapCat，不能发送 QQ，不能输出完整回复正文、prompt、用户原文、知识原文、真实路径、数据库路径、API key、Authorization/Bearer、provider message id 或原始 provider 错误。
- 本地 `dialogue-smoke` 只能输出一轮对话验收白名单字段：`ok`、`dialogue_status=ready|local_only|blocked`、`next_action`、`context_ok`、`context_error_kind`、`persona_profile_id`、`persona_display_name`、`persona_source_refs`、`knowledge_source_refs`、`knowledge_chunks`、`memory_facts`、`history_turns`、`emotion_signals`、`emotion_labels`、`prompt_messages`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`context_budget`、`max_messages`、`risk_level`、`chat_pipeline_ok`、`receipt_state`、`capability_id`、`reply_preview_chars`、`reply_text_hidden=true`、`llm_status`、`llm_error_kind`、`llm_provider`、`llm_model`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`audit_tags`、`audit_events`、`real_transport_used=false`、`napcat_connected=false` 和安全 `public_message`。如果配置体检为 `blocked`，它必须输出 `next_action=fix_config`、`llm_status=not_called`、`receipt_state=not_created`，并且不能调用 provider。它不能启动或连接 NapCat，不能发送 QQ，不能输出 `reply_text` 全文、完整 prompt、原始用户文本、知识原文、最近对话原文、真实路径、数据库路径、目标 ID、API key、Authorization/Bearer、provider message id 或原始 provider 错误。真实 provider 下出现其他 `llm_error` 时必须非零退出。
- 管理员 `/wuwa readiness` 只能展示同源聚合就绪摘要。它可以报告 `readiness_status`、`next_action`、`recommended_commands`、`runtime_soft_paused=true|false`、安全 `runtime_soft_pause_reason`、`runtime_soft_pause_updated_by=set|missing`、`ready_for_local_dialogue`、`ready_for_real_llm`、`real_llm_probe_performed=false`、环境/config/context/chat/NoneBot/transport 安全状态、`chat_pipeline_mode=local_static_probe`、`chat_reply_preview_chars`、LLM 就绪字段、人格强度状态、知识可读计数、provider/model 和 `chat_api_key=set|missing`；不能调用真实 LLM provider，不能连接 NapCat，不能发送外部业务消息，也不能输出完整回复正文、prompt、用户原文、知识原文、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id、具体管理员 ID 或原始 provider 错误。
- 管理员 `/wuwa dialogue [测试文本]` 只能展示同源一轮对话验收摘要。它可以报告 `dialogue_status`、`next_action`、`context_ok`、`chat_pipeline_ok`、`receipt_state`、人格/知识来源安全指纹、情绪/记忆/历史/prompt 数字摘要、回复预算、LLM 状态、安全 `llm_error_kind`、LLM 就绪字段、`reply_preview_chars` 和 `reply_text_hidden=true`；真实 provider 配置完整时可以短调用模型做验收，但不能输出完整模型回复、原始测试文本、完整 prompt、知识原文、最近对话原文、真实路径、数据库路径、目标 ID、API key、Authorization/Bearer、provider message id 或原始 provider 错误。该命令自身不能覆盖最近业务诊断。
- 管理员 `/wuwa roles` 只能展示权限角色规则矩阵。它可以报告 `role_order`、`admin_users`、`enterprise_users`、`trusted_users`、`blocked_users`、`blocked_policy`、`rate_limit_bypass_roles`、`quiet_hours_bypass_roles`、`group_command_prefix`、`id_input_formats`、`role_source`、`admin_commands` 和 `ids_hidden=true`；不能调用 LLM provider，不能连接 NapCat，不能发送外部业务消息，也不能输出具体 user_id、`session_id`、目标 ID、数据库路径、`provider_message_id`、`private_debug` 或原始配置文本。
- 管理员 `/wuwa persona` 只能展示人格自检白名单字段。它可以报告 `persona_status`、`persona_next_action`、人格 id/显示名/版本、`persona_source_refs`、`knowledge_source_refs`、人格文件计数、可读性、字符数、有效行数、强度状态、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪字段、安全 `llm_fix_hints` 和安全 `public_message`；不能调用 LLM provider，不能连接 NapCat，不能发送外部业务消息，也不能输出人格正文、知识正文、完整 prompt、真实路径、文件名、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id、`private_debug` 或原始配置文本。非管理员查询必须拒绝，且不能透露人格、知识、模型、文件或数据库是否存在。
- `/wuwa status` 可以展示当前进程的配置摘要、`运行时硬开关：enabled|disabled` 和 `运行时软暂停：true|false`。硬开关只能来自 `BOT_RUNTIME_ENABLED`，软暂停只能来自同进程 `RuntimeControlState`；软暂停摘要只能展示安全 reason 和 `updated_by=set|missing`，不能展示具体管理员 ID、`session_id`、目标 ID、数据库路径、`provider_message_id`、`private_debug` 或原始配置文本。
- 管理员 `/wuwa pause` 和 `/wuwa resume` 只能控制当前进程的运行时软暂停。它们可以报告 `runtime_paused`、安全 reason 和 `updated_by=set|missing`，不能调用 LLM provider，不能连接 NapCat，不能展示具体 user_id、`session_id`、目标 ID、数据库路径、`provider_message_id`、`private_debug` 或原始配置文本。非管理员必须拒绝，且不能透露当前是否暂停。
- 管理员 `/wuwa config` 只能展示同类只读配置体检摘要。它可以报告 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格/知识文件计数、可解析性计数、人格字符数、有效行数、强度状态、provider/model、`endpoint_url`、`chat_api_key=set|missing`、最近对话读取和保留参数、回复限速参数、全局/会话/发送者上限、目标最小间隔、`rate_limit_store/db`、`quiet_hours_*` 和持久化开关；不能调用模型、不能连接 NapCat、不能输出 API key、数据库真实路径、真实文件路径、人格正文、原始解析错误、目标 ID 或 provider message id。

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
- `wuwa.chat` 的自然语言输出必须保持配置角色身份；如果输出自称 ChatGPT/OpenAI/AI 语言模型、拒绝守岸人身份或否认角色人格，必须在发送前阻断并写入 `persona drift` 审计原因。
- 纯人格漂移阻断允许返回角色化安全兜底提示，例如请用户重新说一遍；该提示必须由运行时模板生成，不能复述被拦截的模型输出，也不能创建 `SendRequest`。
- `/wuwa why` 和 `why-smoke` 只能展示审查阻断的安全归因标签，例如 `review_blocked`、`persona_drift`、`unsafe_output_leakage`，不能展示原始模型输出、`ReviewResult.reasons` 原文或 `private_debug`。
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
- 默认进程内队列只做即时接收和去重；启用 `BOT_SEND_QUEUE_ENABLED=true` 且配置 `BOT_SEND_QUEUE_DB_PATH` 后，`SendRequest` 必须落入 SQLite `send_requests`，并支持 `dedupe_key` 持久去重、`next_retry_at` 到期查询、`claim_due()` 原子认领、`retry_count` 递增、退避重试和最大尝试次数后的最终失败。
- `claim_due()` 必须把到期 `queued` / `failed_retryable` 请求切到内部 `processing` 租约状态，并写入原始状态与 `lease_expires_at`；租约过期后可再次认领，成功、可重试失败或最终失败后必须释放租约字段。`processing` 只属于队列表内部和安全摘要，不属于公开 `DeliveryReceipt` 状态。
- `find_request(request_id)` 是发送队列的内部只读查找接口。SQLite 实现必须从持久化的 `send_requests.request_json` 恢复 `SendRequest`，用于运行诊断判断发送请求是否创建；它不能被用作公开队列浏览接口，也不能让用户侧输出目标 ID、消息正文、`dedupe_key`、数据库真实路径、人格 id 或 provider message id。
- `drain_send_queue_once()` 是当前发送队列的一次性 worker 契约。它优先认领到期 `SendRequest`、调用注入的 transport、记录 transport `DeliveryReceipt`、再更新队列状态；不能直接构造业务内容、不能读取人格/LLM 私有上下文、不能绕过 `ReviewResult`。`queue-smoke` 只允许用临时 SQLite 队列和 fake transport 做本地验证，不能连接 NapCat 或真实 QQ 账号。
- 后台 APScheduler worker 默认关闭。只有 `BOT_SEND_QUEUE_WORKER_ENABLED=true` 且当前发送队列支持到期认领和状态更新时，NoneBot 入口才注册 `wuwa_send_queue_worker`；它只复用 `drain_send_queue_once()`，按配置间隔和批量大小推进队列。没有在线 bot 时，本次投递必须进入可重试失败和退避，而不是直接丢弃、崩溃或连续刷屏。
- 发送队列可持久保存内部发送目标和正文用于真实投递，但任何用户可见摘要、smoke、状态输出或管理员列表都不能展示 `target_id`、正文、`dedupe_key`、人格 id、provider message id 或数据库真实路径。

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
- 限速或安静时间导致的阻断必须发生在调用 LLM 或 transport 前，回执状态为 `blocked`，用户侧只给短说明或通过 `/wuwa why` 查询；不能展示内部 bucket key、目标 ID 或原始消息。
- 回执默认进程内保存；启用 `BOT_RECEIPTS_ENABLED=true` 和 `BOT_RECEIPTS_DB_PATH` 后可写入 SQLite `delivery_receipts`。
- `delivery_receipts` 记录投递结果；`send_requests` 记录待投递请求和重试状态。真实 transport 返回 `sent` 时应把队列项标记为 `sent`，返回 `failed_retryable` 时应按配置退避并在超出 `BOT_SEND_QUEUE_MAX_ATTEMPTS` 后标记为 `failed_final`；返回 `blocked`、`failed_final` 或其他不可重试状态时，worker 必须把队列项标记为最终失败，避免同一请求无限重试。
- OneBot/NapCat provider message id 只作为内部排障字段保存，不能进入用户可见诊断、状态输出或公共消息。
- 管理员查询 `/wuwa receipt <request_id|debug_id>` 时，只输出回执白名单字段：`request_id`、`debug_id`、`state`、`transport`、`retry_count`、`next_retry_at` 和安全 `public_message`。非管理员查询必须拒绝，且不能提示目标记录是否存在。

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

- 脱敏 token、cookie、authkey、二维码 payload、账号密钥、api_key、Authorization/Bearer、`sk-...`、邮件地址等。
- 私有审计需要足够排障信息。
- 公共消息短而可执行。
- 阻断、转私聊、可重试失败和最终失败都必须记录审计。
- 审计默认进程内保存；启用 `BOT_AUDIT_ENABLED=true` 和 `BOT_AUDIT_DB_PATH` 后可写入 SQLite `audit_records`，并按 `BOT_AUDIT_MAX_ITEMS` 裁剪。
- 管理员查询 `/wuwa audit <request_id>` 时，只输出审计白名单字段：`request_id`、`stage`、`event`、`severity` 和安全 `public_message`。不能输出 `session_id`、`private_debug`、原始消息、回复全文、目标 ID、provider message id、token、cookie、API key 或数据库真实路径。
- 管理员查询 `/wuwa recent [数量]` 时，可以合并展示最近运行诊断、发送回执和审计事件摘要；数量参数必须限制在 1 到 20 之间，非法值使用默认 5。运行诊断摘要可以展示 `request_id`、`debug_id`、`capability`、`policy`、`budget`、`llm`、`llm_readiness`、`ready_for_real_llm`、稳定原因码 `llm_reasons`、安全 `diagnostic_tags` 和 `receipt`。`llm_reasons` 只能包含简单稳定原因码，不能包含密钥、Authorization/Bearer、真实路径、`session_id`、原始 provider 错误或自然语言异常。`diagnostic_tags` 只能包含固定 ASCII 机器标签，不能包含用户原话、密钥、Authorization/Bearer、真实路径、`session_id`、目标 ID、原始 provider 错误或自然语言异常。该命令只能输出白名单字段，不能因为是管理员摘要就展示内部私有字段。
- 管理员查询 `/wuwa queue` 时，只能输出发送队列白名单字段：`enabled`、`store=memory|sqlite`、`db=set|missing`、`queued`、`failed_retryable`、`failed_final`、`sent`、`skipped`、`processing`、`max_items`、`max_attempts`、`retry_base_seconds` 和 `retry_max_seconds`。非管理员查询必须拒绝，且不能透露队列是否启用、是否存在待发项、数据库路径、目标 ID、正文、`dedupe_key`、人格 id 或 provider message id。
- 管理员执行 `/wuwa history clear` 时，只能清理当前 platform/adapter/bot/session/sender 作用域内的最近对话历史。输出只能包含安全说明和 `cleared_turns` 计数；不能展示历史正文、`session_id`、`sender_id`、`bot_id`、数据库真实路径或长期记忆内容。非管理员必须拒绝，且不能透露历史库是否启用或是否存在记录。
- 本地 `queue-smoke` 只能输出 worker 白名单字段：`ok`、`checked`、`delivered`、`retryable_failed`、`final_failed`、`skipped`、`receipt_record_failed`、`queued`、`sent`、`failed_retryable`、`failed_final`、`skipped_in_queue`、`processing`、`receipts_recorded`、`audit_events`、`transport=fake_transport`、`real_transport_used=false` 和安全 `public_message`。它不能展示目标 ID、消息正文、`dedupe_key`、数据库真实路径、`private_debug` 或 provider message id。
- 管理员查询 `/wuwa why [request_id|debug_id]` 或本地运行 `why-smoke` 时，只能输出运行诊断白名单字段：`request_id`、`debug_id`、`capability_id`、会话类型、角色、策略原因、回复预算、`prompt_messages`、`system_prompt_chars`、`user_prompt_chars`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`knowledge_chunks`、`memory_facts`、`history_turns`、`emotion_signals`、`llm_status`、`llm_error_kind`、`llm_provider`、`llm_model`、`llm_usage_prompt_tokens`、`llm_usage_completion_tokens`、`llm_usage_total_tokens`、发送请求状态、回执状态、审计事件、审计标签和中文结论。限速阻断只能显示 `rate_limited`、安全细分标签和中文归因；目标间隔命中可以说明同一目标回复过密，全局配额命中可以说明机器人整体回复过密。安静时间阻断只能显示 `quiet_hours` / `quiet_hours_blocked` 和中文归因。人格/知识上下文读取失败只能显示 `context_error`、`context_error:provider_failed` 和中文归因，并把 `llm_status` 显示为 `not_run`，不能把它伪装成已调用 provider。生成参数预检阻断只能显示 `llm_preflight_blocked`、白名单 `llm_preflight_error:<reason>` 和中文归因，不能把它伪装成已调用 provider。不能输出原始用户消息、回复全文、完整 prompt、知识原文、最近对话原文、`private_debug`、目标 ID、provider message id、限速 bucket key、原始模型输出、原始 provider 错误、HTTP 响应正文、API key、token、cookie、Authorization/Bearer、真实路径、文件名或解析异常原文。
- `/wuwa why` 可以通过队列内部 `find_request(request_id)` 恢复持久化 `SendRequest` 来判断 `send_request_created`，但这个恢复结果仍必须先降成白名单诊断字段。即使管理员按 `request_id` 精确查询，也不能展示恢复出的正文、目标 ID、`dedupe_key`、数据库路径或 provider message id。
- 管理员查询 `/wuwa context [测试文本]` 时，只能输出上下文白名单字段：人格 id/名称/版本、`persona_source_refs`、`knowledge_source_refs`、风格/边界/禁止行为计数、知识 chunk 数和来源数、记忆事实数、最近对话轮数、情绪信号数量和标签、回复预算、风险等级、prompt 消息数、prompt 字符数、总字符数、剩余预算、是否整体裁剪、被裁剪分区、分区预算和分区字符数。来源指纹只能是短 hash 形式，不能包含路径、文件名、正文片段、密钥或解析异常。非管理员查询必须拒绝，且不能透露人格、知识、记忆或历史是否存在。
- 管理员查询 `/wuwa llm` 时，只能输出 LLM 连接诊断白名单字段：`ok`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`provider`、`model`、`endpoint_url`、`api_key=set|missing`、`diagnostic_temperature`、`diagnostic_max_tokens`、`timeout_seconds`、`error_kind`、`reply_preview_chars`、`usage_total_tokens` 和安全 `public_message`。`llm_readiness_reasons` 只能由稳定原因码组成，`llm_next_action` 只能由稳定动作码组成，`llm_fix_hints` 只能由稳定原因码映射成配置项名、推荐范围或占位值。不能输出 API key、Authorization/Bearer、完整模型回复、原始 provider 错误、目标 ID、provider message id、数据库路径或任何上游鉴权材料。
- 管理员查询 `/wuwa config` 时，只能输出配置体检白名单字段：`ok`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格/知识文件计数、`persona_readable/empty/unreadable`、`persona_total_chars`、`persona_meaningful_lines`、`persona_strength_status`、`knowledge_readable/empty/unreadable`、`knowledge_total_chars`、`knowledge_meaningful_lines`、记忆/历史/情绪/回复限速/安静时间/诊断/审计/回执/发送队列开关、`history_max_items`、`rate_limit_store=memory|sqlite`、`rate_limit_db=set|missing`、`rate_limit_chat_global_max_requests`、`rate_limit_chat_session_max_requests`、`rate_limit_chat_sender_max_requests`、`rate_limit_target_min_interval_seconds`、`quiet_hours_enabled`、`quiet_hours_start/end/timezone/session_types/bypass_roles`、`send_queue_store=memory|sqlite`、`send_queue_db=set|missing`、`send_queue_max_items`、`send_queue_max_attempts`、`send_queue_retry_base_seconds`、`send_queue_retry_max_seconds`、`send_queue_worker_enabled`、`send_queue_worker_interval_seconds`、`send_queue_worker_batch_size`、`chat_provider`、`chat_model`、`chat_api_key=set|missing`、`endpoint_url`、`chat_temperature`、`chat_max_tokens`、`timeout_seconds` 和安全 `public_message`。`llm_readiness_reasons` 只能由稳定原因码组成，`llm_next_action` 只能由稳定动作码组成，`llm_fix_hints` 只能包含安全修复提示，不能包含路径、密钥、人格正文、原始解析异常、prompt、用户原文或 provider 错误。非管理员查询必须拒绝，且不能透露当前人格、模型、文件或数据库是否存在。
- 管理员查询 `/wuwa readiness` 时，只能输出统一就绪白名单字段：`ok`、`readiness_status`、`next_action`、`recommended_commands`、`runtime_soft_paused`、`runtime_soft_pause_reason`、`runtime_soft_pause_updated_by=set|missing`、`ready_for_local_dialogue`、`ready_for_real_llm`、`real_llm_probe_performed=false`、`doctor_ok`、`ready_for_local_llm_smoke`、`ready_for_nonebot_run`、`nonebot_ok`、`transport_ok`、`config_ok`、`config_errors`、`config_warnings`、`context_ok`、`context_error_kind`、安全上下文字符数、上下文裁剪布尔值、`chat_pipeline_ok`、`chat_pipeline_mode`、`chat_receipt_state`、`chat_reply_preview_chars`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`persona_strength_status`、`knowledge_readable`、`provider`、`model`、`chat_api_key=set|missing` 和安全 `public_message`。非管理员查询必须拒绝，且不能透露当前人格、模型、文件、数据库、依赖状态、软暂停状态或管理员 ID 是否存在。
- 管理员查询 `/wuwa roles` 时，只能输出权限角色白名单字段：`role_order`、`admin_users`、`enterprise_users`、`trusted_users`、`blocked_users`、`blocked_policy`、`user_role`、`admin_role`、`enterprise_role`、`trusted_role`、`rate_limit_bypass_roles`、`quiet_hours_bypass_roles`、`group_command_prefix`、`id_input_formats`、`role_source`、`admin_commands`、`ids_hidden=true` 和安全 `public_message`。非管理员查询必须拒绝，且不能透露角色数量、具体 user_id、`session_id`、目标 ID、数据库路径、provider message id、`private_debug` 或角色配置原文。
- 管理员执行 `/wuwa pause` 或 `/wuwa resume` 时，只能输出运行时控制白名单字段：`runtime_paused`、`reason`、`updated_by=set|missing` 和安全 `public_message`。非管理员必须拒绝，且不能透露当前暂停状态、管理员 ID、`session_id`、目标 ID、数据库路径或 `private_debug`。软暂停状态不应写入 `.env`，也不能声称跨重启持久生效。
- `/wuwa why`、`why-smoke` 和 `chat-smoke` 解释普通对话里的 LLM 调用失败或空白回复时，只能从 `llm_error:<kind>` 审计标签读取稳定错误类型，并输出安全 `llm_error_kind` 或中文归因；如果存在 `llm_preflight_blocked`，则必须优先解释为生成参数或配置非法、调用 provider 前已阻断，并只列出 `openai_temperature_invalid`、`openai_max_tokens_invalid`、`openai_timeout_seconds_invalid` 这类稳定原因码。provider 成功返回但文本为空白必须归类为 `empty_response`，不能向用户发送空文本。普通用户侧的失败兜底必须使用运行时模板生成的角色化提示，不能包含 `debug=<kind>`、原始 provider 错误、HTTP 响应正文或任何鉴权材料。`chat-smoke`、`why-smoke` 和 `/wuwa why` 还必须输出 `ready_for_real_llm`、`llm_readiness_status` 和 `llm_readiness_reasons`，`chat-smoke` 和 `why-smoke` 可以输出 `llm_next_action`，这些字段必须来自 `config-smoke` 的只读配置体检结果。`llm_fix_hints` 不能进入普通用户回复或 `/wuwa why` 的业务现场解释，除非该入口已经明确列入配置/人格/就绪/LLM 诊断白名单。`chat-smoke` 可以输出 `reply_preview_chars` 来证明回复存在，但必须同时输出 `reply_text_hidden=true`，不能输出 `reply_text` 全文。诊断不能展示原始 provider 错误、HTTP 响应正文、完整模型回复、API key、Authorization/Bearer、真实文件路径或任何上游鉴权材料。
- `/wuwa why`、`why-smoke` 和 `chat-smoke` 解释普通对话里的上下文读取失败时，只能从 `context_error` / `context_error:provider_failed` 审计标签读取稳定归因，输出 `llm_status=not_run` 和中文结论“人格或知识上下文读取失败，已跳过 LLM”。普通用户侧必须收到角色化安全提示，不能包含 `debug=<kind>`、真实路径、文件名、解析异常、人格正文、知识正文或 prompt。

## 错误分类

| 错误类型 | 用户侧行为 | 审计要求 |
| --- | --- | --- |
| `user_input_invalid` | 说明期望格式。 | 原始输入和校验错误。 |
| `auth_required` | 引导私聊绑定/登录。 | 缺失凭据类型和来源 id。 |
| `permission_denied` | 告知该功能未在此处启用。 | ACL 规则和主体。 |
| `rate_limited` | 说明来源、功能或当前会话正在冷却。 | 安全 scope、retry-after；不能写原始目标 ID 或 bucket key。 |
| `auth` | 说明模型或来源鉴权失败。 | HTTP 状态、provider、endpoint 摘要，不能写原始密钥。 |
| `upstream_changed` | 说明来源格式可能变化。 | parser 异常和样本 id。 |
| `content_blocked` | 说明内容不能在此处发送。 | 安全类别和审查阶段。 |
| `privacy_blocked` | 转私聊或要求同意。 | 隐私等级和目标范围。 |
| `timeout` | 说明来源响应超时。 | 耗时、超时配置、重试次数。 |
| `network` | 说明网络或代理无法连接。 | endpoint 摘要、异常类别、重试次数。 |
| `http` | 说明上游 HTTP 错误。 | HTTP 状态和脱敏响应摘要。 |
| `server` | 说明上游服务端错误。 | HTTP 状态、provider 和退避建议。 |
| `schema` | 说明上游响应格式不符合契约。 | 响应结构摘要，不能写完整原文。 |
| `empty_response` | 说明模型返回空内容。 | provider、model 和 request_id。 |
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
- 未命中命令前缀且未提及机器人的普通群消息必须作为 `passive_group_message` 静默阻断：不调用 LLM、不创建 `SendRequest`、不发送用户可见提示，但要写审计和运行诊断，供管理员用 `/wuwa why` 排查。
- 私聊可使用更多个人上下文，但必须有同意基础。
- 同人、账号游戏数据、日程、出行、位置默认私聊。
- 公共游戏/wiki/兑换码/日历命令可以早期开放。
- cookie、token、二维码登录、authkey、UID 绑定、抽卡记录、账号面板在密钥存储、脱敏、审计和撤销能力完成前默认阻断。

## NoneBot / NapCat 输入输出规范

- NoneBot 的 `plugin_dirs = ["plugins"]` 是本地插件加载入口。
- OneBot V11 / NapCat 输入事件应先转成 `IncomingMessage`，不让业务能力依赖原始 adapter 类型。
- OneBot/NapCat 的用户 ID 只在配置和审计私有上下文里作为主体 ID 使用；状态诊断只显示管理员、企业、可信和拉黑名单数量，不公开具体 ID。
- NapCat 推荐 `messagePostFormat: 'array'`，方便保留文字、图片、at、json、合并转发等消息段结构。
- 出站消息只能由 sender/transport adapter 把 `RenderedOutput` 转换成 OneBot/NapCat 消息段。
- `send_msg`、`send_private_msg`、`send_group_msg`、`send_group_forward_msg`、`send_private_forward_msg` 和对应 `call_api(...)` 扩展调用的返回值必须映射成 `DeliveryReceipt`。
- capability adapter 不应直接调用 `event.send`、`bot.send_*` 或 NapCat HTTP/WebSocket API。

## 验收检查

实现时应添加测试：

- 非法命令输入映射到 `user_input_invalid`。
- 群聊中的私密数据映射到 `privacy_blocked` 或 `redirected`。
- 没有来源置信度的 `CapabilityResult` 会先被审查。
- 重复 `dedupe_key` 会跳过重复群输出。
- 发送失败创建 `DeliveryReceipt.failed_retryable` 或 `failed_final`。
- 所有被阻断输出创建脱敏 `AuditRecord`。
