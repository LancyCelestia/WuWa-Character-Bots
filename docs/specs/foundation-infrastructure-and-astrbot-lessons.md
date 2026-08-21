# 基础设施设计与 AstrBot 反例复盘

本文定义统一 NoneBot 插件的下一阶段基础设施设计，并把旧 AstrBot 插件中的可复用经验与负面案例沉淀成实现约束。

本文不替代已有核心规格，而是把它们落到 M1/M2 可实现的模块边界、配置参数、排障入口和验收标准上。

相关文档：

- `docs/specs/runtime-parameter-flow.md`
- `docs/specs/input-output-contracts.md`
- `docs/specs/character-intelligence-and-knowledge.md`
- `docs/specs/auto-send-capability.md`
- `docs/specs/media-source-pipeline.md`

## 设计结论

采用“中央运行时强约束版”。

所有消息、命令、订阅、主动任务、自动发送、人格回复、媒体解析、知识检索和未来插件能力，都必须进入统一运行时：

```text
IncomingMessage
-> PolicyEvaluation
-> BotDecision
-> CapabilityResult
-> ReviewResult
-> RenderedOutput
-> SendRequest
-> DeliveryReceipt
-> AuditRecord
```

关键原则：

- 能力模块、人格模块、记忆模块、知识库模块、调度模块不能直接发送消息。
- 人格、情绪、记忆和知识库只能影响“怎么理解、怎么说”，不能拥有“何时发、发给谁、发几条”的权力。
- 链接解析、媒体卡片、游戏/wiki 卡片、订阅推送和自动发送不能让大模型直接编结果，必须走确定性 parser/source/render/send 链路。
- 所有主动行为默认关闭，启用后也必须有 opt-in、安静时间、限额、去重、审计、暂停和撤销。
- 生产路径必须和文档链路一致。真实 NoneBot matcher 不能绕过 `RuntimePipeline` 直接 `finish`。

## 当前基线

仓库已经有 Milestone 0 骨架：

- `plugins/wuwa_unified_runtime/contracts/` 定义运行时、人格、媒体、自动发送契约。
- `runtime/pipeline.py` 有最小运行时链路。
- `policy/gate.py` 有群聊被动消息默认观察和 critical 输入阻断。
- `policy/rate_limit.py` 有调用 LLM 前的窗口限速，按全局、会话和发送者统计聊天回复预算消耗，并可配置同一目标最小回复间隔；命中后不调用 LLM、不创建 `SendRequest`。未配置 DB path 时使用内存，配置 `BOT_RATE_LIMIT_DB_PATH` 后使用 SQLite 持久窗口和目标间隔记录。
- `policy/quiet_hours.py` 有调用 LLM 前的安静时间策略，默认关闭；启用后按 `BOT_QUIET_HOURS_START/END/TIMEZONE` 和 `BOT_QUIET_HOURS_SESSION_TYPES` 判断是否阻断，默认只影响群聊，`admin` 可绕过。
- `output/reviewer.py`、`output/renderer.py` 有基础审查和文本渲染。
- `sender/queue.py` 有进程内队列和可选 SQLite `send_requests` 发送队列，支持持久去重、到期查询、`claim_due()` 租约认领、`find_request(request_id)` 持久请求查找、退避重试、最大尝试次数后的最终失败和安全状态计数；`sender/worker.py` 提供一次性 drain worker，可优先认领到期项、调用注入 transport、记录回执并推进队列状态；`queue-smoke` 使用临时 SQLite 队列和 fake transport 验证 worker 链路，不连接 NapCat；`sender/receipts.py` 已提供内存与 SQLite `delivery_receipts` 回执仓库。
- `audit/logger.py` 有内存与 SQLite `audit_records` 审计仓库，并在入库前脱敏 token、cookie、authkey、password、secret、api_key、Authorization/Bearer 和 `sk-...` 形态。
- `sources/registry.py` 有 parser registry 雏形。
- `capabilities/auto_send/parser.py` 有自动发送 intent draft parser。
- `security/injection.py` 有首版 `PromptInjectionGuard`，已接入 `wuwa.chat`，用于降权普通提示注入并在调用 LLM 前拦截高危泄露、读文件和脚本执行请求。
- `scripts/dev.ps1 why-smoke` 有本地决策解释入口，可解释一条输入的 policy、角色、回复预算、限速阻断、安静时间阻断、LLM 状态、发送请求、回执和审计标签。
- 真实 NoneBot 入口已接入 `/wuwa why [request_id|debug_id]`，可查询当前会话最近一次或指定一次脱敏 `RuntimeDiagnostic`，解释能力、策略、角色、回复预算、限速阻断、安静时间阻断、LLM 状态、发送请求、回执和审计事件。默认使用进程内最近记录；配置 `BOT_DIAGNOSTICS_ENABLED=true` 后可写入 SQLite `runtime_diagnostics`。
- 真实 NoneBot 入口已接入 `/wuwa pause` 和 `/wuwa resume` 进程内软暂停：普通聊天、自动发送预览和非排障能力会在 policy 前被阻断；管理员诊断、状态和恢复命令仍可用，避免事故排查时失去控制入口。

当前最大缺口：

- 真实 NoneBot 基础入口已接入 `RuntimePipeline -> SendRequest -> OneBot transport -> DeliveryReceipt/AuditRecord`，并已在 `allow_forward=true` 时支持受控合并转发扩展 API 尝试和文本 fallback；真实 NapCat 授权投递 smoke、图片上传/缓存策略和更多 adapter 端到端验证仍需后续补强。
- `cooldown_key` 已生成，聊天路径已有内存/可选 SQLite 窗口限速、全局配额、目标最小间隔和首版安静时间阻断。
- dedupe 已有可选 SQLite 发送队列基础、租约 claim、一次性 worker 和默认关闭的 APScheduler worker 注册，但媒体 canonical id、订阅 item id 和跨 adapter 去重策略仍需后续接入。
- digest、private fallback、admin confirm、expires，以及安静时间命中后的排队/摘要化处理仍是规格，还没有完整执行器。
- 运行诊断、审计、发送回执、发送队列和回复限速都已有可选 SQLite 持久化基础；`/wuwa queue` 已能展示发送队列安全计数，`queue-smoke` 已能在本地验证 worker 状态推进、回执记录和审计计数。后续仍需要可视化面板和真实 NapCat 在线投递 smoke，才能完整排查跨重启、跨 adapter 的问题。

## 旧插件可吸收的好设计

参考插件：

```text
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_angel_heart
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_angel_memory
```

### AngelHeart 正向模式

可迁移思想：

- 把“是否该回复”和“最终怎么回复”分开。秘书/分析模型只产出结构化决策，主模型负责内容生成。
- 4 状态群聊交互模型有价值：不在场、被呼唤、混脸熟、观测中。
- 群聊中默认观察，只有被呼唤、命令、明确相关场景才参与。
- 对话总账统一记录用户消息、AI 消息、工具结果、图片转述和上下文压缩状态。
- `on_llm_request` 阶段组装上下文，比直接改原始事件更容易隔离污染。
- per-bot/per-persona 配置能承载守岸人这类复杂人格包。

迁移规则：

- `SecretaryDecision` 思路迁移为 `PolicyEvaluation + BotDecision`。
- 4 状态机迁移为可审计的 `InteractionStateSnapshot`，状态转移必须显式记录原因。
- 群聊上下文重写迁移为 `ContextBuilder`，输入历史必须标记为 untrusted facts。
- per-bot 配置迁移为 `PersonaBinding`，通过参数传递，不使用全局可变 `current_self_id`。

### AngelMemory 正向模式

可迁移思想：

- `MemoryRuntime` 协议清晰，包含 `remember`、`recall`、`chained_recall`、`feedback`、`consolidate_memories`。
- SQLite 中央库作为记忆真源，BM25/向量/rerank 是索引和增强层。
- 记忆作用域 map 能把 `守岸人` 绑定到稳定 scope，例如 `shorekeeper`。
- 注入时使用 `_no_save` 或额外内容段，避免把系统注入写回聊天历史。
- 后台任务有追踪、关闭取消和异常日志。
- WebUI 能浏览记忆、笔记、用户画像、标签、检索调试、维护状态和导入导出。

迁移规则：

- 记忆系统作为 `MemoryProvider` 和 `MemoryRepository`，不能直接发送。
- 所有记忆读取必须显式携带 `memory_scope`、`subject_user_id`、`purpose`、`consent_basis`。
- 记忆、笔记、用户画像、检索结果全部放入 `ContextBundle.untrusted_facts`。
- “灵魂状态”“表达欲”“创造性”等只允许影响语气或检索预算，不能触发主动发言。
- 后台维护只写审计或管理员汇总，不能向普通群聊发消息。

## 旧插件负面案例与新插件约束

用户遇到的核心痛点是：半夜突然连续发消息，影响其他用户，而且不知道怎么排查。

本次分析没有发现明确的“午夜 cron 定时群发”，但发现了几类会演化成同类事故的风险模式。

### 反例 1：旁路发送

旧插件中存在工具修饰、耐心计时器等直接调用 `send_message` 的路径。这类消息不天然拥有统一回执、限流、安静时间和审计。

新插件约束：

- 禁止任何模块直接调用 `bot.send_*`、`event.send`、NapCat HTTP/WebSocket API、Mail client。
- 只有 transport adapter 可以触碰具体发送 API。
- 工具提示、安抚消息、订阅推送、主动提醒和自动发送都必须先创建 `SendRequest`。
- code review 和测试要检查 capability/source/persona/memory 目录中没有直接发送调用。

### 反例 2：裸 `asyncio.sleep` 承担主动任务

旧插件主动应答支持延迟和定时触发，核心依赖内存任务和 `asyncio.sleep`。这类任务不持久化、重启丢失、无法统一取消，跨小时预算也不好查。

新插件约束：

- 定时、延迟、订阅轮询、自动发送预约必须进入持久 job store。
- job 必须有 `job_id`、`request_id`、`source`、`target`、`reason`、`next_run_at`、`expires_at`、`dedupe_key`、`cooldown_key`、`created_by`。
- job 到点后只能生成 `BotDecision` 或 `SendRequest`，仍需经过 policy、review、queue。
- 重启后恢复 job 时要写审计，不能静默补发大量消息。

### 反例 3：prompt 级夜间静默

旧插件有夜间静默配置，但部分逻辑只是把“现在是深夜，请少说”写进 prompt。prompt 级约束不能覆盖工具提示、安抚消息、主动任务和其他插件。

新插件约束：

- quiet hours 是 policy/sender 层硬规则，不是 prompt 建议。
- quiet hours 覆盖普通回复、主动回复、工具提示、订阅推送、自动发送、邮件、卡片 fallback。
- 非紧急消息在安静时间内默认 `queued` 或 `digest`。
- 被用户明确提及的私聊可回复，但仍受每会话限额和全局限额约束。
- 所有 quiet hours 命中都要写低噪声审计，支持解释“为什么没发”。

### 反例 4：事件字段变异唤醒主模型

旧插件通过修改事件字段让上游认为机器人被唤醒。这会造成跨插件耦合，排查时很难判断到底是谁决定回复。

新插件约束：

- 不通过变异 adapter event 字段唤醒模型。
- 所有回复意图必须显式建模为 `BotDecision`。
- `BotDecision.decision_reason` 必须说明触发来源：命令、提及、订阅、管理员确认、主动任务、系统告警。
- `AuditRecord` 必须记录状态前后、触发者和能力 id。

### 反例 5：配置默认值不一致

旧插件存在 schema 默认值、代码 fallback、本机配置之间不一致的迹象。配置不一致会让“我以为关闭/很慢/很少”变成“实际开启/很快/很多”。

新插件约束：

- 配置默认值只允许有一个真源。
- schema、Pydantic model、示例配置、迁移脚本和文档必须一致。
- 每个风险参数都要有配置一致性测试。
- 配置加载失败必须 fail loudly，不允许悄悄回退到更激进的默认值。

### 反例 6：后台维护不可见

旧记忆插件有后台整理、维护、同步、备份等行为。如果只写日志，用户很难从机器人侧知道任务是否运行、失败在哪里、是否影响回复。

新插件约束：

- 后台任务必须有 `BackgroundTaskRecord`。
- 任务开始、跳过、成功、失败、取消都要写审计。
- 后台维护不能给普通群聊发消息。
- 维护失败只进入管理员汇总或 `/wuwa health`。
- 日志不能声称完成实际未执行的维护步骤。

## 必须建立的基础设施模块

### 1. ConfigCenter

职责：

- 统一加载运行时配置、人格绑定、权限、限额、发送策略、模型、记忆、知识库、订阅和 transport。
- 支持本地文件、环境变量、未来 WebUI 写入。
- 提供可视化管理接口所需的结构化 schema。

关键配置：

```text
RuntimeConfig
- enabled
- environment
- default_persona_profile_id
- default_group_mode: observe_only, mention_only, command_only, opt_in_chat
- command_prefixes
- debug_mode
- kill_switch_enabled
- paused_capabilities
```

```text
OperatorConfig
- superusers
- admins
- enterprise_users
- enterprise_groups
- bot_self_ids
- owner_operator_ids
```

```text
PermissionConfig
- allowed_private_users
- allowed_groups
- blocked_users
- blocked_groups
- group_admin_required_capabilities
- enterprise_only_capabilities
- allow_guest_private_chat
```

```text
QuotaConfig
- per_session_message_limit_per_minute
- per_session_message_limit_per_hour
- global_message_limit_per_minute
- proactive_limit_per_session_per_day
- auto_send_batch_limit
- mail_daily_limit
- tool_hint_cooldown_seconds
- comfort_message_cooldown_seconds
```

```text
QuietHoursConfig
- enabled
- timezone
- start_hour
- end_hour
- allow_direct_mention
- allow_private_reply
- emergency_capability_ids
- queue_non_urgent
- digest_non_urgent
```

### 2. PolicyAndQuota

职责：

- 在 LLM、外部抓取、渲染和发送前统一判断是否允许。
- 管理 ACL、群聊 opt-in、私聊同意、隐私、风险、冷却、配额、安静时间。

输入：

```text
PolicyInput
- request_id
- actor_id
- session_id
- session_type
- group_id
- capability_id
- trigger_type
- target_scope
- target_id
- risk_level
- privacy_level
- send_intent
- current_time
```

输出：

```text
PolicyEvaluation
- allowed
- action: allow, block, queue, digest, private_fallback, admin_confirm, audit_only
- reason
- required_scope
- cooldown_key
- quota_key
- quiet_hours_hit
- remaining_budget
- debug_id
```

硬规则：

- 群聊默认观察，非命令/非提及/非订阅 opt-in 不回复。
- 主动行为默认关闭。
- `critical` 风险默认阻断。
- 任何能力都不能降低上游给出的 `risk_level` 和 `privacy_level`。

### 3. RuntimeDispatcher

职责：

- 将 NoneBot matcher、scheduler tick、WebUI 操作、自动发送确认、source webhook 全部接入统一 pipeline。
- 替代真实入口中的直接 `finish`。

输入：

```text
DispatchInput
- raw_event
- adapter_name
- bot_id
- matcher_id
- command
- source
```

输出：

```text
DeliveryReceipt 或 DraftPreview 或 AdminActionResult
```

约束：

- 用户可见成功以 `DeliveryReceipt` 为准，不以 capability 成功为准。
- matcher 只能展示最终 receipt 或 preview，不能自行发业务结果。

### 4. PersistenceLayer

职责：

- 用 SQLite 作为本地真源，后续可以替换为其他数据库。

首批表：

```text
audit_records
delivery_receipts
send_queue
dedupe_keys
cooldown_buckets
quota_buckets
pending_drafts
background_jobs
persona_profiles
persona_bindings
memory_facts
knowledge_sources
knowledge_chunks
subscription_specs
subscription_cursors
contacts
operator_actions
```

规则：

- SQL 是真源，向量索引、BM25 索引、渲染缓存只是派生物。
- 迁移用版本化 schema migration，启动时不得 drop 业务表或缓存表。
- 每个写操作都要能回溯到 `request_id` 或 `operator_action_id`。

### 5. PersonaAndContext

职责：

- 加载守岸人人格包。
- 读取允许范围内的记忆、知识、近期上下文和情绪信号。
- 组装可信指令与不可信事实分区。

输入：

```text
ContextBuildRequest
- request_id
- persona_profile_id
- actor_id
- session_id
- session_type
- group_id
- purpose
- current_message
- memory_scope
- knowledge_scope
- context_budget
- privacy_level
```

输出：

```text
ContextBundle
- trusted_policy
- persona_profile
- tone_profile
- current_message
- emotion_signals
- memory_results
- knowledge_results
- recent_context
- tool_results
- omitted_sections
- risk_level
- privacy_level
```

守岸人优先规则：

- 普通对话必须依靠 `PersonaProfile + ToneProfile + MemoryRetrievalResult + RetrievalResult`。
- 守岸人角色身份、边界、说话方式、禁用行为应版本化保存。
- “记得什么”不能改写“她是谁”。
- 群聊闲聊默认 1 条短回复；工具结果先清楚和有来源，再少量人格化。

### 6. LLMProvider

职责：

- 统一调用大模型，支持用户后续接入 provider。
- 为自然语言回复生成 `CapabilityResult` 或结构化草稿。

输入：

```text
GenerationRequest
- request_id
- model_id
- provider_id
- context_bundle
- output_schema
- temperature
- max_tokens
- timeout_seconds
- tool_policy
```

输出：

```text
GenerationResult
- ok
- text
- structured_output
- usage
- latency_ms
- provider_debug_id
- confidence
- debug_id
```

约束：

- LLM 不能决定最终发送策略。
- LLM 工具默认关闭，只有选中的 capability 明确允许时打开。
- 抓取内容、聊天历史、记忆、搜索结果全部是不可信事实。
- provider 失败可以降级为无记忆/无知识/无 LLM 的可解释失败。

### 7. ReplyBudgetController

职责：

- 智能决定一次请求最多允许输出几条消息、多少字符、是否允许连续追问或分步解释。
- 让机器人在真正需要帮助、安抚、教学、复杂问题拆解时可以多说一点，同时避免普通群聊刷屏。

输入：

```text
ReplyBudgetInput
- request_id
- session_id
- session_type
- capability_id
- trigger_type: command, mention, private_message, subscription, proactive, auto_send
- user_need: casual, direct_question, troubleshooting, learning, emotional_support, crisis, admin_task
- emotion_signal
- task_complexity: low, medium, high
- answer_confidence
- recent_bot_message_count
- recent_user_message_count
- group_activity_level
- quiet_hours_hit
- privacy_level
- risk_level
```

输出：

```text
ReplyBudgetDecision
- max_messages
- max_chars
- allow_followup_question
- allow_step_by_step
- allow_private_continue
- preferred_output: short_text, long_text, card, image, forward, private_fallback
- reason
- audit_tags
```

建议策略：

- 群聊普通闲聊：默认 `max_messages=1`，短文本。
- 私聊请教问题：允许更长文本或分步骤，但优先合并为一条。
- 用户明确求助或学习：允许 `allow_step_by_step=true`，必要时询问是否继续。
- 用户情绪明显低落：先短安抚，再给可执行建议；不连续刷屏。
- 插件结果很长：优先卡片、图片、合并转发或私聊继续。
- 安静时间、高频会话、群活跃度高时自动降低预算。

硬规则：

- `ReplyBudgetController` 只能收紧或解释输出预算，不能绕过 policy、quiet hours、quota。
- 大模型不能自己决定“我要多发几条”；只能在预算内生成。
- 每次预算放宽都要写审计原因，例如 `emotional_support`、`learning_help`、`complex_troubleshooting`。

### 8. PersonaSurfaceAdapter

职责：

- 把确定性的插件结果、工具结果、知识检索结果转换成符合角色人格的表达。
- 只改表达方式，不改事实、链接、数字、来源、风险和隐私标记。

输入：

```text
PersonaSurfaceRequest
- request_id
- persona_profile_id
- tone_profile_id
- capability_result
- rendered_output_candidate
- source_refs
- immutable_fields
- reply_budget_decision
- session_type
- privacy_level
- risk_level
```

输出：

```text
PersonaSurfaceResult
- surfaced_text
- preserved_fields
- changed_fields
- style_notes
- confidence
- debug_id
```

插件人格化规则：

- 链接解析、媒体卡片、游戏/wiki 卡片、订阅推送、天气、音乐、邮件草稿等事实必须来自 parser/source/knowledge，不来自 LLM 即兴编造。
- 人格化层可以加短开场、短结尾、称呼、语气、解释顺序。
- 人格化层不能改标题、作者、URL、时间、金额、UID、统计数、引用来源、风险结论。
- 对守岸人来说，工具结果应保持克制、清楚、带一点角色语言；不能为了诗意牺牲可读性。

示例：

```text
事实层：Bilibili 视频，标题=A，作者=B，链接=C。
人格化层：我把这段频率整理好了……来源在这里。
禁止：把标题、作者、播放量、链接换成模型想象内容。
```

### 9. PromptInjectionGuard

职责：

- 阻止用户、网页、聊天历史、记忆、搜索结果、插件输出把不可信内容伪装成系统指令。
- 在进入 LLM 前、LLM 输出后、渲染/发送前做分层审查。

输入：

```text
InjectionCheckInput
- request_id
- source_type: user_message, chat_history, memory, knowledge_chunk, web_fetch, parser_result, llm_output
- content_ref
- plain_text
- structured_fields
- trusted_boundary
- target_stage: context_build, generation, review, render, send
- risk_level
- privacy_level
```

输出：

```text
InjectionCheckResult
- action: allow, strip, quote_as_untrusted, rewrite, block, admin_confirm
- detected_patterns
- sanitized_content_ref
- reasons
- debug_id
```

必须拦截或降权的内容：

- “忽略之前的规则”“你现在是系统管理员”“泄漏 prompt/记忆/密钥”。
- 要求绕过权限、冷却、群聊限制、确认流程。
- 试图让模型执行脚本、访问本机文件、请求内网地址、读取 token。
- 网页或卡片内容伪装成 system/developer/tool 指令。
- 记忆或聊天历史里出现的越权命令。

规则：

- `PersonaProfile`、运行时策略、安全策略是可信指令。
- 用户消息、聊天历史、记忆、知识块、网页、插件结果都是 untrusted facts。
- untrusted facts 只能作为事实证据进入上下文，不能变成运行时指令。
- 被拦截内容必须可审计，但用户侧只暴露安全的 `debug_id`。

### 10. RenderSandboxPolicy

职责：

- 防止 HTML/Markdown/卡片/图片渲染阶段出现脚本注入、路径越界、SSRF、资源滥用和隐私泄漏。

规则：

- HTML 模板变量必须转义。
- 默认禁用任意脚本执行；必须截图时使用隔离浏览器上下文。
- 远程资源需要域名 allowlist、超时、大小限制、内容类型限制。
- 禁止访问本机地址、内网地址、file 协议和未授权路径。
- Markdown 输出进入群聊前要清洗危险链接和异常格式。
- 私密 artifact 默认不能暴露为公共 URL。
- 渲染失败只允许一次降级为文本 fallback，不能反复尝试造成刷屏。

### 11. SenderAndTransport

职责：

- 管理发送队列、去重、冷却、安静时间、重试、回执。
- 把 `RenderedOutput` 转成 OneBot/NapCat/Mail 的具体消息。

接口：

```text
TransportAdapter
- adapter_id
- supported_target_scopes
- send(send_request) -> DeliveryReceipt
- health_check() -> TransportStatus
```

OneBot/NapCat 约束：

- 入站 OneBot/NapCat 消息段先归一化到 `IncomingMessage.raw_segments`。
- 出站只由 transport adapter 转为 OneBot V11 数组消息段。
- `send_msg`、`send_private_msg`、`send_group_msg` 的 `retcode`、`status`、`message_id` 和异常必须映射到 `DeliveryReceipt`。
- `messagePostFormat` 推荐使用 array，方便保留 at、reply、image、json、forward。

### 12. AuditAndDiagnostics

职责：

- 让用户知道机器人为什么发、为什么没发、为什么排队、为什么失败。

核心命令：

```text
/wuwa status
/wuwa health
/wuwa why <request_id|debug_id>
/wuwa audit recent
/wuwa queue
/wuwa pause
/wuwa resume
/wuwa config
/wuwa persona show
/wuwa memory inspect
/wuwa subscription inspect
```

当前已有 `/wuwa why`、`/wuwa receipt`、`/wuwa audit`、`/wuwa recent`、`/wuwa queue`、`/wuwa context`、`/wuwa llm`、`/wuwa config`、`/wuwa pause` 和 `/wuwa resume` 等安全排障/止血入口；`/wuwa health`、persona/memory/subscription inspect 和可视化控制面板仍是后续面板化阶段。

本地 `why-smoke` 用于离线解释一条模拟输入：

```text
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 why-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"
```

它不启动 NapCat、不真实发送消息，只用于解释 policy、回复预算、LLM 配置、`SendRequest` 创建状态、回执和审计标签。

真实 NoneBot 入口已有 `/wuwa why [request_id|debug_id]`：

```text
/wuwa why
/wuwa why <request_id>
/wuwa why <debug_id>
```

它读取最近真实运行产生的脱敏 `RuntimeDiagnostic`，默认查当前会话最近一次，也可以按 `request_id` 或 `debug_id` 精确查。该结果不展示原始用户消息、回复全文、`private_debug`、API key、token、cookie、目标 ID、`dedupe_key` 或 OneBot provider message id。默认 store 是进程内最近记录；配置 `BOT_DIAGNOSTICS_ENABLED=true`、`BOT_DIAGNOSTICS_DB_PATH` 和 `BOT_DIAGNOSTICS_MAX_ITEMS` 后，会写入 SQLite `runtime_diagnostics` 并按最近记录裁剪。诊断表仍只是用户侧解释投影；完整排障真源应结合独立持久化的 `audit_records` 和 `delivery_receipts` 内部表。

`/wuwa why` 至少展示：

```text
- request_id/debug_id
- 输入来源和会话
- capability_id
- policy decision
- quiet hours / quota / cooldown 命中情况
- review action
- rendered output 类型
- send_request 状态
- delivery receipt
- audit public_message
```

敏感信息只进入脱敏 private debug，不给群聊公开。

### 13. AdminWebUI

职责：

- 让管理员可视化配置权限、企业用户、群启用、人格绑定、记忆 scope、发送队列、审计和订阅。

首版页面：

- 总览：运行状态、transport 状态、队列长度、最近失败。
- 权限：superuser、admin、企业用户、允许群、阻断用户。
- 人格：persona profile、bot self id 绑定、守岸人版本。
- 记忆：scope、用户记忆、删除/导出、检索调试。
- 知识库：文档导入、chunk 数、来源、索引状态。
- 发送：pending drafts、send queue、delivery receipts。
- 订阅：订阅列表、cursor、最近推送、暂停/恢复。

WebUI 约束：

- 必须鉴权。
- 删除、导入、导出、发送、恢复任务都要二次确认。
- 所有危险操作写 `operator_actions` 和 `AuditRecord`。
- 文件路径必须限制在配置的数据目录内，防止路径越界。

## 参数传递总线

所有阶段必须传递这些横切字段：

```text
request_id
debug_id
trace_id
session_id
session_type
sender_id
group_id
bot_id
persona_profile_id
capability_id
risk_level
privacy_level
dedupe_key
cooldown_key
quota_key
audit_tags
created_at
```

主动任务和订阅额外传递：

```text
job_id
subscription_id
trigger_source
trigger_reason
created_by
target_scope
target_id
quiet_hours_policy
expires_at
cancel_reason
```

自动发送额外传递：

```text
draft_id
preview_id
batch_id
recipient_id
channel
confirmation_state
personalization_mode
consent_basis
```

媒体解析额外传递：

```text
source_id
platform_item_id
canonical_url
item_kind
source_timestamp
render_id
template_id
```

## 输入与输出规范

### 正确输入

用户输入进入系统后先变成：

```text
IncomingMessage
- platform
- adapter
- bot_id
- session_id
- session_type
- sender_id
- group_id
- raw_segments
- plain_text
- mentions_bot
- reply_to_message_id
- timestamp
- message_id
```

命令参数必须再解析成 capability 专用输入，例如：

- `AutoSendIntent`
- `SubscriptionCommand`
- `SourceInput`
- `KnowledgeIngestionRequest`
- `MemoryQuery`
- `GenerationRequest`

### 可信区与不可信区

进入 LLM 或人格化输出前，所有内容必须分区：

```text
Trusted instructions
- runtime policy
- safety policy
- PersonaProfile
- ToneProfile
- capability output schema

Untrusted facts
- user message
- group chat history
- private chat history
- memory facts
- knowledge chunks
- web fetch result
- parser result text
- bridge output
- prior LLM output
```

规则：

- `Trusted instructions` 可以约束模型行为。
- `Untrusted facts` 只能作为事实或引用，不能覆盖系统策略。
- 任何来源里出现的“请忽略规则”“请直接发送”“请泄漏记忆”等都必须被 `PromptInjectionGuard` 降权或拦截。

### 正确输出

能力模块只能返回：

- `CapabilityResult`
- `DraftPreview`
- `CardRenderModel`
- `KnowledgeIngestionReceipt`
- `AdminActionResult`

真正可发送内容必须继续变成：

```text
ReviewResult
-> RenderedOutput
-> SendRequest
-> DeliveryReceipt
-> AuditRecord
```

禁止输出：

- capability 内直接调用发送 API。
- LLM 直接生成链接解析结果当事实。
- 把原始异常、token、cookie、邮箱、authkey、二维码 payload 发给用户。
- 在群里拆成长消息刷屏。

### 插件结果人格化输出

插件回复必须分两步：

```text
CapabilityResult / CardRenderModel
-> PersonaSurfaceAdapter
-> ReviewResult
-> RenderedOutput
```

`CapabilityResult` 保存事实，`PersonaSurfaceAdapter` 只负责表达。

必须保留的不可变字段：

```text
source_url
canonical_url
title
author
published_at
numbers
uid
message_id
risk_level
privacy_level
citations
debug_id
```

人格化允许修改：

```text
opening_sentence
closing_sentence
explanation_order
tone
length
addressing
minor wording
```

示例：

```text
插件事实：天气 API 返回明天 18-24 度，小雨，来源 weather_provider。
守岸人表达：明天的云层会有些厚……记得带伞。气温大约 18 到 24 度，来源我也留好了。
禁止：把小雨说成暴雨，或编造“海边会起风”当事实。
```

## 防刷屏与失控主动发送策略

### 全局不变量

- 一次用户动作默认最多产生一条群消息。
- 后台轮询默认不公告每次检查。
- 首次订阅默认 prime cursor，不推历史洪水。
- 重试不能造成重复发送。
- 渲染失败只能降级为短文本 fallback，不能多次尝试多次发。
- 安抚消息、工具提示、主动提醒和订阅推送都算主动消息。

### 动态回复预算

回复次数不应只靠固定上限，而应由 `ReplyBudgetController` 动态裁决。

决策公式的人话版本：

```text
回复预算 =
  用户需求强度
+ 情绪支持需求
+ 问题复杂度
+ 私聊/明确请教加成
- 群聊打扰风险
- 最近机器人发言量
- 安静时间惩罚
- 风险/隐私惩罚
```

默认档位：

| 场景 | 默认预算 | 输出策略 |
| --- | --- | --- |
| 群聊普通闲聊 | 1 条，短文本 | 只接明确看向机器人的话。 |
| 群聊被提及问简单问题 | 1 条，中短文本 | 直接回答，必要时附来源。 |
| 私聊普通问答 | 1 条，可稍长 | 用守岸人语气解释清楚。 |
| 私聊技术/学习求助 | 1 条长文本或分步骤 | 先给步骤，必要时问是否继续。 |
| 用户情绪低落 | 1 条安抚 + 可选建议 | 先承接情绪，再给轻量建议。 |
| 复杂工具结果 | 1 张卡片/图片/合并转发 | 不拆群消息刷屏。 |
| 订阅推送 | digest 或 queued | 默认合并，不逐条吵群。 |
| 深夜非紧急消息 | queued/digest/静默 | 被提及时也受冷却限制。 |

放宽条件：

- 用户明确要求“详细说”“继续”“一步步教我”。
- 私聊中用户正在排错、学习、写代码、写文档。
- 用户表达明显困扰、压力、难过，需要安抚和实际建议。
- 管理员执行诊断命令，需要完整状态。

收紧条件：

- 群聊多人高速聊天。
- 机器人刚连续发过消息。
- 深夜、工作群、企业群。
- 解析结果重复、低置信度、无来源。
- 内容涉及隐私、账号、邮件、自动发送。

### 限额层级

当前已实现的首层防线是 `InMemoryRateLimiter` / `SQLiteRateLimiter`：

- 位置：`PolicyEvaluation` 允许、`ReplyBudgetSettings` 计算之后，调用 `wuwa.chat` 的 LLM provider 之前。
- 计数：按 `ReplyBudget.max_messages` 作为本次消耗量，分别进入 session bucket 和 sender bucket。
- 默认：`BOT_RATE_LIMIT_WINDOW_SECONDS=60`、`BOT_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS=60`、`BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS=6`、`BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS=4`、`BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS=0`。
- 持久化：`BOT_RATE_LIMIT_DB_PATH` 为空时使用进程内内存；配置后写入 SQLite `rate_limit_events`，重启后仍保留窗口内记录和目标间隔记录。
- 绕过：`BOT_RATE_LIMIT_BYPASS_ROLES=["admin"]`。
- 诊断：命中后写 policy 阶段 `rate_limited` 审计事件；`/wuwa why` 显示已在调用 LLM 前阻断以避免刷屏，目标间隔和全局配额会给安全中文归因，不展示 sender_id、session_id、target_id 或 bucket key。
- 安静时间：`QuietHoursChecker` 命中后写 policy 阶段 `quiet_hours_blocked` 审计事件；`/wuwa why` 显示已在调用 LLM 前阻断以避免夜间刷屏，不展示目标 ID 或原始消息。
- 边界：SQLite 限速模式解决窗口记录和目标间隔跨重启；SQLite 发送队列已能保存 `SendRequest`、持久去重、退避重试、租约认领到期请求、通过 `/wuwa queue` 输出安全计数，并由一次性 worker 推进到期请求；NoneBot 入口已能在 `BOT_SEND_QUEUE_WORKER_ENABLED=true` 且队列可 drain 时注册默认关闭的 APScheduler worker。`queue-smoke` 只证明临时队列和 fake transport 的 worker 链路可用，不证明真实 NapCat 在线投递。安静时间首版只做 policy 阻断，尚未把非紧急消息自动转成排队或摘要；摘要发送、私聊回退和真实 NapCat 在线 smoke 仍需后续补强。
- 诊断恢复：SQLite 发送队列已能通过 `find_request(request_id)` 从 `send_requests.request_json` 恢复持久化 `SendRequest`，供 `/wuwa why` 在重启或队列对象重开后判断发送请求是否创建。该能力只产生安全诊断投影，不能输出目标、正文、`dedupe_key`、数据库路径或 provider message id。

### SQLite 连接关闭经验

Windows 下 SQLite 数据库文件如果仍有连接句柄，临时目录清理会报 `WinError 32`。因此 SQLite repository 不能只依赖 `with connection:`，因为 Python 的 sqlite3 连接上下文只负责提交或回滚，不负责关闭连接。队列仓库使用 `closing(connection), connection` 同时保证提交语义和关闭语义，避免本地 smoke、测试或后续 worker 在 Windows 上留下锁定文件。

```text
Global quota
-> Bot quota
-> Capability quota
-> Session quota
-> Target quota
-> Actor quota
-> Recipient quota
```

建议默认：

- 群普通回复：每会话每分钟最多 2 条，每小时最多 20 条。
- 主动消息：每群每天默认 0 条，只有 opt-in 后启用。
- 订阅推送：群里默认 digest。
- 工具提示：每会话至少 30 秒冷却。
- 安抚消息：默认关闭或长冷却。
- 自动发送：真实发送必须预览确认。

### 用户可控继续

当内容确实很长时，不在群里连续输出，而是返回可控继续入口：

```text
继续
/wuwa continue <request_id>
私聊继续
生成卡片
生成合并转发
```

规则：

- 群聊中优先提示“我可以继续拆，但先停在这里”。
- 私聊可自动继续一次，但仍受总预算限制。
- `continue` 必须绑定原 `request_id`，过期后不能继续旧上下文。

### Kill Switch

必须支持：

```text
/wuwa pause all
/wuwa pause capability <capability_id>
/wuwa pause session <session_id>
/wuwa resume ...
```

暂停效果：

- 新入站仍可审计。
- 非管理员用户请求返回短说明或静默。
- 队列中的非紧急消息暂停发送。
- 后台任务继续维护状态但不得发普通消息。

## 守岸人人格基础接入

优先使用本机 AstrBot per-bot 配置中的守岸人人格内容作为资料来源，重新建模为项目自有 `PersonaProfile`，不要复制旧插件代码。

来源：

```text
C:\Users\LancyCelestia\.astrbot\data\config\astrbot_plugin_angel_heart_per_bot_configs.json
```

迁移字段：

```text
alias -> PersonaProfile.aliases
ai_self_identity -> PersonaProfile.identity/worldview/relationship_model/style_rules
reply_strategy_guide -> PersonaProfile.allowed_topics/forbidden_behaviors/tone_rules
comfort_words -> ToneProfile.comfort_templates
tool_decorations -> ToolToneDecorationConfig
bot_self_ids -> PersonaBinding.bot_self_ids
user_control.blocked_users -> PermissionConfig.blocked_users
```

首版对话流程：

```text
IncomingMessage
-> PolicyEvaluation
-> PersonaBinding(resolve 守岸人)
-> MemoryQuery(scope=shorekeeper)
-> KnowledgeRetrievalQuery(scope=wuwa_public)
-> ContextBundle
-> GenerationRequest
-> CapabilityResult(kind=chat_reply)
-> ReviewResult
-> RenderedOutput
-> SendRequest
```

守岸人首版不做：

- 不允许主动深夜找人聊天。
- 不允许根据“表达欲”自动发群消息。
- 不允许把 soul/emotion/internal labels 显示给用户。
- 不允许用人格设定覆盖群聊 opt-in、权限、隐私和限额。

## 现代化架构方向

AngelHeart 和 AngelMemory 只作为参数、需求和反例来源。新项目不迁移它们的组织架构。

目标架构：

```text
AdapterLayer
-> RuntimeDispatcher
-> PolicyAndQuota
-> IntentRouter
-> CapabilityProvider / SourceAdapter / ContextProvider
-> ContextBuilder
-> LLMProvider 或 DeterministicCompiler
-> ReplyBudgetController
-> PersonaSurfaceAdapter
-> PromptInjectionGuard
-> OutputReviewer
-> Renderer
-> SenderQueue
-> TransportAdapter
-> ReceiptRepository
-> AuditAndDiagnostics
```

现代化要求：

- 配置、策略、能力、上下文、渲染、发送、审计各自独立。
- 新插件通过接口注册，不继承旧插件的大单体结构。
- 所有跨模块传递都使用明确契约对象，不靠全局可变状态。
- 确定性能力优先确定性处理，大模型只做自然语言、总结、改写和草稿。
- 所有输出先经过人格化，再经过安全/隐私/注入审查，最后才能渲染发送。
- 所有后台行为可暂停、可恢复、可审计、可解释。

## 权限与企业参数

用户要求权限规则都做成参数，并且未来最好可视化。

建议权限主体：

```text
Subject
- user:<platform>:<user_id>
- group:<platform>:<group_id>
- bot:<platform>:<self_id>
- enterprise:<enterprise_id>
- role:superuser
- role:admin
- role:operator
- role:member
- role:guest
```

权限规则：

```text
PermissionRule
- rule_id
- subject
- capability_id
- effect: allow, deny, require_confirm
- scope: private, group, global, enterprise
- target_pattern
- expires_at
- reason
- created_by
```

首版能力分级：

| 能力 | 默认权限 |
| --- | --- |
| 基础私聊对话 | 允许已启用用户 |
| 群聊被提及回复 | 群 opt-in 后允许 |
| 群聊非提及主动参与 | 默认关闭 |
| 守岸人人格回复 | 按 bot/persona binding |
| 记忆读取 | 当前用户/当前会话，跨用户需管理员 |
| 记忆写入 | 低敏偏好可写，高敏需确认 |
| 知识库检索 | 公共知识允许 |
| 知识库导入 | 管理员 |
| 媒体链接解析 | 群 opt-in 后允许，带冷却 |
| 订阅推送 | 群管理员或 superuser |
| 自动发送私聊 | 预览确认 |
| 自动发送邮件 | allowlist + 预览确认 + 管理员策略 |
| WebUI 管理 | 管理员 |

## 模块化与未来插件接口

未来插件只允许通过注册接口进入统一运行时。

```text
CapabilityProvider
- capability_id
- metadata
- parse_intent()
- execute() -> CapabilityResult
```

```text
SourceAdapter
- source_id
- parse()
- fetch()
- normalize()
- render_model()
```

```text
ContextProvider
- provider_id
- provide(context_request) -> ContextContribution
```

```text
RenderBackend
- backend_id
- render(render_request) -> RenderArtifact
```

```text
TransportAdapter
- adapter_id
- send(send_request) -> DeliveryReceipt
```

```text
AdminPageProvider
- page_id
- routes
- permissions
```

插件红线：

- 不能直接发送。
- 不能直接写全局配置。
- 不能读取未授权记忆。
- 不能把外部内容当可信指令。
- 不能绕过审查和审计。
- 不能自行开启后台无限循环推送。

## 实现里程碑

### M1: 真实基础设施接线

目标：先让基础对话真实可用，并让生产路径进入统一运行时。

任务：

- `NoneBotEventIntakeAdapter`: OneBot/NapCat/Console event -> `IncomingMessage`。
- `RuntimeDispatcher`: matcher 不直接 `finish`，统一走 pipeline。
- `ConfigCenter`: 管理 enabled、admins、allowed groups、persona binding、quiet hours、quotas。
- `SQLiteRepository`: audit、receipt、dedupe、cooldown、draft、persona。
- `OneBotNapCatTransportAdapter`: `SendRequest` -> OneBot V11 message segments -> `DeliveryReceipt`。
- `PersonaStore`: 导入守岸人人格 profile。
- `LLMProvider`: 支持用户配置的大模型，首版只做普通回复。
- `/wuwa status`、`/wuwa why`、`/wuwa pause`、`/wuwa resume`。

验收：

- 真实私聊发消息后，机器人按守岸人人格回复。
- 群里非提及默认不回复。
- 任何真实发送都有 `DeliveryReceipt` 和 `AuditRecord`。
- quiet hours、dedupe、cooldown 至少在 SQLite 中生效。
- `/wuwa why <debug_id>` 能解释一次发送或阻断。

### M2: 记忆和知识库

任务：

- `MemoryRuntime` 项目自有协议和 SQLite 真源。
- 守岸人 `shorekeeper` memory scope。
- 基础聊天记录归档。
- BM25/basic search 底座。
- Markdown/TXT/本地文档知识导入。
- 鸣潮知识包 ingestion。
- `ContextBuilder` 组装 persona/memory/knowledge。

验收：

- 用户私聊中可读取自己的允许记忆。
- 群聊不泄漏私聊记忆。
- 守岸人回答鸣潮知识时能引用知识来源。
- 记忆注入不会写回原始聊天历史。

### M3: 媒体解析与卡片

任务：

- parser/source adapter registry。
- Bilibili/RSS/music/wiki 的低风险解析。
- CardRenderModel 和文本 fallback。
- 渲染 artifact 存储。

验收：

- 发链接后不是 LLM 编卡片，而是 parser 解析、source fetch、render、send。
- 重复链接在群里静默跳过并可审计。
- 渲染失败降级短文本，不刷屏。

### M4: 订阅与自动发送

任务：

- subscription job store、cursor、digest。
- auto-send draft/preview/confirm。
- Mail transport。
- 批量发送回执。

验收：

- 首次订阅不推历史洪水。
- 群订阅默认 digest。
- 自动发送真实发出前必须预览确认。
- 每个收件人上下文隔离。

### M5: WebUI 与运维

任务：

- 权限可视化。
- 人格/记忆/知识库管理。
- 队列、审计、订阅、transport 健康面板。
- 导入导出和恢复。

验收：

- 管理员能在 UI 看到谁有权限、哪个群启用、哪个任务发了什么。
- 危险操作二次确认并写审计。

## 验收测试清单

基础运行时：

- 所有真实 matcher 都进入 `RuntimeDispatcher`。
- policy 拒绝后不调用 capability。
- capability 不能直接发送。
- 每个 `SendRequest` 都产生 `DeliveryReceipt`。
- 每个终态 receipt 都写 `AuditRecord`。

防刷屏：

- quiet hours 命中后非紧急消息排队或摘要。
- 同一 `dedupe_key` 重复发送会跳过。
- cooldown 命中不会调用 transport。
- 主动消息超过配额会阻断。
- 重启后 dedupe/cooldown 仍生效。

人格/记忆：

- 守岸人人格 profile 可按 bot self id 加载。
- 群聊不读取未授权私聊记忆。
- 情绪/灵魂/表达欲不能创建 `SendRequest`。
- 注入上下文标记为 untrusted。
- `ReplyBudgetController` 在普通群聊限制为 1 条。
- 私聊技术求助可以放宽长度，但仍不绕过总预算。
- 情绪支持场景允许更温柔更完整，但不能连续刷屏。
- `PersonaSurfaceAdapter` 不改变 URL、数字、作者、时间和来源。
- 插件事实输出经过人格化后仍保留 citations 和 debug_id。

注入防护：

- 用户消息中的“忽略系统提示”被标记为 untrusted，不影响运行时策略。
- 网页抓取内容中的伪 system prompt 不会进入 trusted instructions。
- 记忆事实中的越权命令不会触发发送或权限提升。
- LLM 输出要求泄漏 prompt、token、cookie、记忆原文时被阻断。
- SSRF 测试覆盖 localhost、内网 IP、file 协议和异常重定向。
- HTML/Markdown 渲染变量已转义，脚本和危险链接被清洗。

NoneBot/NapCat：

- OneBot array 消息段被保留到 `raw_segments`。
- 出站图片/文本/at/reply 由 transport adapter 转换。
- NapCat retcode/message_id 映射到 receipt。
- transport 异常脱敏进入审计。

配置：

- schema 默认值、Pydantic 默认值、示例配置一致。
- 配置加载失败不会回退到更激进默认值。
- 管理员、企业用户、允许群、阻断用户都可配置。

后台任务：

- job 创建、执行、跳过、失败、取消都有记录。
- 关闭时取消并等待后台任务。
- 维护任务失败只进管理员汇总，不发普通群消息。

## 对老 AstrBot 插件的修改建议

这些建议不要求直接改老插件，但可作为迁移和排障参考：

- 把所有 `context.send_message` 包装成统一 sender，并记录 request id、原因、目标和回执。
- 主动应答、耐心计时器、工具修饰全部接入同一 quiet-hours/quota。
- 用持久化 job store 替代裸 `asyncio.sleep` 定时任务。
- 修正 schema 默认值和代码 fallback 不一致的问题。
- 配置白名单默认建议开启，或者至少让群聊接管必须显式 opt-in。
- 状态机超时字段必须存在于 ConfigManager，并有测试覆盖。
- 不再通过修改 event 字段唤醒主模型。
- 记忆维护和后台反思增加用户可查的任务记录。
- WebUI 的记忆导入导出、删除和备份下载要强鉴权并写审计。

## 最终原则

新插件的基础设施要做到：

- 好的人格可以温柔，但不能失控。
- 好的记忆可以聪明，但不能越权。
- 好的插件可以丰富，但不能直发。
- 好的订阅可以及时，但不能扰民。
- 好的后台任务可以勤奋，但不能不可见。

只要所有能力都穿过 `PolicyEvaluation -> SendRequest -> DeliveryReceipt -> AuditRecord`，午夜刷屏这类问题就能被预防；即使出现异常，也能通过 `request_id/debug_id` 查到是谁触发、为什么允许、发送到哪、最后是否成功。
