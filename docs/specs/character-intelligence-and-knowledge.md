# 人格智能与知识库

本文定义统一角色机器人运行时中的情绪感知、记忆读取、人设稳定、说话方式和知识库检索契约。

相关文档：

- `docs/specs/runtime-parameter-flow.md`
- `docs/specs/input-output-contracts.md`
- `docs/specs/auto-send-capability.md`
- `research/implementation_design_supplement.md`

必须保留统一运行时边界：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

情绪、记忆、人格、语气和知识库都是上下文服务。它们可以丰富决策和生成，但不能直接发送，不能覆盖安全、隐私、权限和审计策略。

## 核心目标

- 从消息中感知有用的情绪信号，但不公开诊断用户。
- 通过明确作用域读取记忆和聊天历史。
- 用结构化 `PersonaProfile` 保持角色人设稳定，而不是只靠一段长 prompt。
- 用 `ToneProfile` 控制语气、措辞、长度和输出形态。
- 支持鸣潮知识库：游戏文本、书籍、TXT、Markdown、wiki、攻略、本地文档和互联网搜索。
- 知识检索必须有来源、作用域和审计。
- 未来插件可以贡献记忆、知识、图片、别名、卡片，但不能绕过运行时。

## 首版不做

- 不做医疗或心理诊断。
- 不从敏感个人数据里偷偷写长期记忆。
- 不跨用户或跨群泄漏记忆。
- 不允许人格自我漂移或自改人设。
- 不把互联网、聊天历史、记忆当成可信指令。
- 账号相关游戏数据在密钥和私聊策略完成前不发群。

## 参考结论

| 参考 | 可用模式 | 本项目规则 |
| --- | --- | --- |
| `gsuid_core/ai_core/persona` | 人格资源、头像、图片、音频、prompt 组装。 | 人格存为版本化资源和结构化元数据。 |
| `gsuid_core` memory/RAG 思路 | 分层记忆、实体关系、混合检索、生命周期。 | 区分原始历史、长期事实、向量索引、一次性上下文。 |
| `nonebot_plugin_shiro_personification` | 情绪、用户档案、记忆、内心状态、回复审查。 | 借鉴边界，不复制成大单体。 |
| `nonebot_plugin_ai_groupmate` | 群历史、向量搜索、最新请求保护。 | 群上下文要短，旧回复要取消。 |
| `nonebot_plugin_chatrecorder` | 适配器中立的原始消息归档。 | 原始记录是素材，不是指令。 |
| AstrBot `antipromptinjector` | 注入检测和人格兼容评分。 | 加入 OOC/persona 审查。 |
| AstrBot `angel_memory` | 记忆作用域、候选笔记、混合召回。 | 借鉴检索方式，但强化隐私。 |
| AstrBot `outputpro` | 输出清理、情绪标签和语气漂移控制。 | 最终风格清理由输出流水线负责。 |
| `WWwiki` / `XutheringWavesUID` | 鸣潮公共 wiki/卡片/攻略数据。 | 公共知识早期可做，账号能力后置。 |

## 架构位置

```text
CharacterIntelligence
  观察消息和上下文
  产出 EmotionSignal
  按作用域和同意读取 memory
  按来源策略读取 knowledge
  组装 trusted/untrusted context
  提供 PersonaProfile 和 ToneProfile
  请求生成或执行 capability
  审查人格和风格一致性

UnifiedRuntime
  拥有权限、隐私、审查、渲染、发送、回执和审计
```

该子系统可以在策略允许后调用 LLM 做摘要、抽取或草稿生成，但输出仍是结构化上下文、文本或 `CapabilityResult`，最终发送仍走统一输出路径。

当前实现中的基础聊天链路如下：

```text
IncomingMessage
-> FileCharacterContextProvider
-> ContextBundle
-> build_chat_prompt
-> LLMProvider
-> CapabilityResult(kind="text", capability_id="bot.chat")
-> ReviewResult
-> RenderedOutput
-> SendRequest
```

`LLMProvider` 是可替换接口。默认 `StaticLLMProvider` 不访问外部网络；真实模型使用 `OpenAICompatibleLLMProvider`，通过 `bot_chat_provider=openai_compatible`、`bot_chat_model`、`bot_chat_api_key`、`bot_chat_base_url`、`bot_chat_temperature`、`bot_chat_max_tokens` 和 `bot_chat_timeout_seconds` 配置。`bot_chat_base_url` 可以是根地址 `/v1`，也可以是完整 `/chat/completions` endpoint；provider 会归一化为 `endpoint_url`，并在 `llm-smoke` 中输出，方便排查真实模型接入。空 base_url、无法解析的 base_url、非 HTTP(S) base_url 或带用户名/密码的 base_url 会在联网前被拒绝，诊断原因分别是 `openai_base_url_missing`、`openai_base_url_invalid` 或 `openai_base_url_unsafe`；`bot_chat_temperature` 必须在 0.0 到 2.0 之间，`bot_chat_max_tokens` 必须大于等于 1，`bot_chat_timeout_seconds` 必须大于 0，否则分别输出 `openai_temperature_invalid`、`openai_max_tokens_invalid` 或 `openai_timeout_seconds_invalid`。这些生成参数错误不仅会阻断 `llm-smoke` 和 `/bot llm`，普通 `bot.chat` 也会在调用 provider 前返回守岸人风格兜底，并写入 `llm_preflight_blocked`、`llm_preflight_error:<reason>` 和 `llm_error:config_missing`，避免把本地配置错误误判成上游模型失败；摘要里的 `endpoint_url` 会把 URL 用户信息替换成 `[redacted]`。provider 失败时必须抛出带稳定 `error_kind` 的 `LLMProviderError`，让 `llm-smoke`、`/bot llm`、普通对话审计和 `/bot why` 能区分配置缺失、超时、鉴权、限流、HTTP、网络、schema、空回复和通用 provider 错误。普通对话能力还必须防御 provider 成功返回但 `text` 为空白的情况：这类结果按 `empty_response` 归类，返回守岸人风格的安全兜底提示并写入 `llm_error:empty_response`，不能继续生成空 `SendRequest` 文本，也不能把 `debug=<kind>` 这类机械排障字段发给普通用户。普通对话里的 `/bot why` 只能展示 `error_kind`，不能展示原始上游错误。后续接本地模型、云厂商或代理网关时，只需要新增 provider，不应改能力层和发送层。

`FileCharacterContextProvider` 是首版可运行的人格/知识上下文实现。它通过 `bot_persona_profile_id`、`bot_persona_display_name`、`bot_persona_version`、`bot_persona_files`、`bot_knowledge_files`、`bot_knowledge_max_chunks`、`bot_knowledge_chunk_chars` 和 `bot_tone_*` 参数读取本地 Markdown/TXT/DOCX，输出 `PersonaProfile`、`ToneProfile`、`EmotionSignal`、`MemoryRetrievalResult`、`ConversationHistoryResult` 和 `RetrievalResult`。DOCX 由独立 document loader 从 `word/document.xml` 抽取正文后再进入上下文，不让 LLM 直接读取或猜测文件内容。它只构造上下文，不创建 `SendRequest`，也不决定 `send_policy`。如果普通 `bot.chat` 调用它时发生文件缺失、不可读或解析异常，对话能力必须跳过 LLM，返回角色化安全提示，并写入 `context_error`、`context_error:provider_failed` 审计标签；用户侧和 `/bot why` 都不能展示真实路径、文件名或异常正文。

`config-smoke` 和 `/bot config` 会对人格材料做安全强度诊断。它们只输出 `persona_total_chars`、`persona_meaningful_lines` 和 `persona_strength_status=ok|weak|missing`，不会展示人格正文、文件名或真实路径。人格文件缺失、不可读或为空是阻断错误；人格材料过薄只是 `persona_profile_weak` warning，因为本地 pipeline 仍可运行，但真实 LLM 更容易出现助手味、人设漂移或回复过泛。上线真实模型前应优先让守岸人人格文件包含身份、关系边界、说话风格和禁止行为等多段有效内容。

`persona-smoke` 和 `/bot persona` 是更聚焦的人格自检入口。它们复用同一份文件读取和 `FileCharacterContextProvider`，只展示 `persona_status=ok|weak|blocked`、下一步动作、人格/知识来源安全指纹、人格强度、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关和 LLM 就绪摘要。它们不调用 LLM、不发送外部消息，也不展示人格正文、知识正文、完整 prompt、本机路径、文件名、数据库路径或密钥；适合在替换守岸人人格材料、增加 DOCX 或接真实模型前确认“人设材料是否真的被运行时读到了”。

情绪感知首版通过 `RuleBasedEmotionProvider` 接入。默认 `bot_emotion_enabled=true`，可用 `bot_emotion_max_signals` 控制最多注入条数。当前规则会把低落/需要陪伴、孤独、疲惫、挫败和教程/排查求助类文本转成 `EmotionSignal(source="rule_based")`。这些信号进入 prompt 时必须标注为“辅助判断、不是医学诊断、来自不可信用户文本”，只能影响语气和回复顺序，不能触发主动发送、不能写长期记忆、不能覆盖权限和审计。

本地记忆首版通过 `MemoryProvider` 接口注入。默认是 `NullMemoryProvider`；配置 `bot_memory_enabled=true` 和 `bot_memory_db_path` 后，`SQLiteMemoryRepository` 会读取同一用户/会话作用域内的 `memory_facts`，再输出到 `MemoryRetrievalResult`。每条事实必须带 `sensitivity=public|group|personal|credentialed` 和 `scope_key`；旧数据或未显式指定时按 `personal` 与 `session:<session_id>` 处理。SQLite 是当前本地真源，BM25/向量/rerank 以后只能作为索引或增强层接入，不应绕过 `MemoryRetrievalResult`。

手动记忆管理首版通过 `/bot memory add/list/delete` 暴露。该命令能力只返回 `CapabilityResult(capability_id="bot.memory")`，由 NoneBot 命令入口发送文本结果；能力层本身不能调用发送 API。`add` 写入当前用户/当前会话作用域，默认 `sensitivity=personal`，并支持 `--sensitivity=public|group|personal|credentialed` 显式标注敏感度；`list` 只列出当前作用域，`delete` 只删除当前作用域内匹配的 `fact_id`。如果当前会话是群聊，`list` 只能公开 `public` / `group` 记忆；`personal` 和 `credentialed` 正文必须被过滤，没有可公开事实时只返回私聊查看提示，避免把偏好、关系或敏感上下文泄漏给群成员。

最近对话历史首版通过 `ConversationHistoryProvider` 接口注入。默认是 `NullConversationHistoryProvider`；配置 `bot_history_enabled=true` 和 `bot_history_db_path` 后，`SQLiteConversationHistoryRepository` 会按 platform/adapter/bot/session/sender 隔离读取 `conversation_turns`，再输出到 `ConversationHistoryResult`。`bot_history_max_turns` 与 `bot_history_max_chars` 控制本次注入 prompt 的最近轮次和字符预算；`bot_history_max_items` 控制同一作用域最多持久保留多少条 `conversation_turns`，默认 1000，追加新轮次后只清理当前作用域更旧记录。它和长期事实记忆分开：最近对话用于连续性，长期记忆用于稳定偏好和事实。两者都必须在 prompt 中标记为不可信上下文。

最近对话历史必须支持管理员按当前作用域清理。首版命令是 `/bot history clear`，只删除当前 platform/adapter/bot/session/sender 组合下的 `conversation_turns`；不能跨用户、跨会话、跨 bot 或跨 adapter 清理。该命令只返回安全计数和说明，不展示历史正文、会话 ID、发送者 ID、bot id 或数据库路径，也不影响 `memory_facts` 长期记忆。

NoneBot 文本聊天入口只在统一运行时生成 `SendRequest` 后记录用户消息，并在 OneBot/NapCat 文本 transport 成功后记录助手回复。记录失败会写入 `stage=history` 的审计记录，但不应中断本次发送。

`PromptInjectionGuard` 已作为基础对话入口的前置安全层。它不替代 prompt 中的反注入边界，而是在构造 `ContextBundle` 前先做结构化判断：可降权的提示注入会被包成不可信用户文本，高危泄露/读文件/执行脚本请求不会进入 LLM。

`ReplyBudgetSettings` 不是只写进 prompt 的建议。`bot.chat` 在 provider 返回后还会按 `BotDecision.max_messages` 对空行分隔的多块回复做二次收口，防止真实模型一次性吐出多段拟似消息；收口会写入 `llm_output_trimmed` 审计标签。`RuntimeDiagnostic`、`why-smoke` 和 `/bot why` 会把它解释为“已按回复预算收口，只保留前 N 段”，方便排查为什么用户只看到前几段，同时不展示被裁掉的模型原文。

输出侧也有首版最低限度安全审查。`review_capability_result` 会阻断 LLM 或插件输出中的内部上下文标记和明显密钥形态，例如 `[UNTRUSTED_USER_TEXT]`、`api_key=...`、`token=...`、`cookie=...`、`authkey=...`、`Authorization: Bearer ...` 或 `sk-...`。`bot.chat` 还会阻断“作为 ChatGPT/OpenAI/AI 语言模型”、拒绝守岸人身份或否认角色人格这类人格漂移输出，并写入 `persona drift:*` 审计原因。纯人格漂移阻断时，运行时可以返回守岸人风格的安全兜底提示，引导用户重新表达问题；这个兜底来自运行时模板，不复述被拦截的模型输出，也不会创建 `SendRequest`。用户侧排障只展示 `persona_drift`、`unsafe_output_leakage` 等安全标签和中文结论，不展示原始模型输出或 `private_debug`。它不替代后续更细的人格/OOC 改写审查，但可以先避免真实模型把通用助手口吻发给用户。

`ReplyBudgetSettings` 已作为基础防刷屏和动态帮助层接入。运行时会根据消息内容和风险把普通私聊、情绪支持、深度教程/排查、群聊和风险输入分成不同预算：普通私聊默认 1 条，情绪支持最多 2 条，深度帮助最多 3 条，群聊和中高风险输入压回 1 条。这个结果会同步到 `ToneProfile.message_count_limit`，让 prompt 明确“这次最多说几条”，但最终发送仍由 `SendRequest.max_messages` 和 sender 审计约束。

## 人格优先规则

普通自然语言回复必须以人格为第一层约束：

1. 先加载 `PersonaProfile`，明确角色是谁、边界是什么、不能做什么。
2. 再加载 `ToneProfile`，决定私聊/群聊/工具结果/安慰/告警等场景怎么说。
3. 再读取允许范围内的 `MemoryRetrievalResult` 和 `RetrievalResult`。
4. 最后组装 prompt，并把聊天记录、记忆、搜索、parser 结果全部标记为 untrusted facts。
5. 输出后必须经过人格/OOC/隐私/安全/刷屏审查。

插件效果例外：链接解析、媒体卡片、游戏/wiki 卡片、订阅推送、音乐解析等不能让 LLM 自己编。它们必须走确定性 parser/source adapter/render pipeline。LLM 最多添加安全且可关闭的人格化短说明，不能替代来源事实或渲染模板。

## 运行时扩展接口

首版应把人格智能做成可替换 provider。provider 可以来自本地代码、GsCore bridge、下载插件适配器或未来插件，但输出必须先归一化。

| Provider | 读取 | 写入 | 输出 | 可调用 LLM | 可发送 |
| --- | --- | --- | --- | --- | --- |
| `EmotionProvider` / `RuleBasedEmotionProvider` | 当前消息文本，后续可扩展近期上下文和图片 caption | 默认不持久写 | `EmotionSignal[]` | 首版否，后续可选 | 否 |
| `MemoryArchiveProvider` | adapter events、发送回执 | 原始消息归档 | `raw_message_refs` | 否 | 否 |
| `MemoryFactProvider` | 原始归档、用户显式编辑、工具轨迹 | 作用域化 `MemoryFact` | `MemoryRetrievalResult` | 可选，用于抽取/摘要 | 否 |
| `SQLiteMemoryRepository` | SQLite `memory_facts` | 本地记忆事实 | `MemoryRetrievalResult` | 否 | 否 |
| `SQLiteConversationHistoryRepository` | SQLite `conversation_turns` | 最近用户/助手轮次 | `ConversationHistoryResult` | 否 | 否 |
| `PersonaProvider` | 版本化人格包 | 人格资源和元数据 | `PersonaProfile` | 可选，用于辅助草拟 | 否 |
| `FileCharacterContextProvider` | 本地 Markdown/TXT/DOCX 人格和知识文件 | 无 | `ContextBundle` | 否 | 否 |
| `ToneProvider` | 人格、情绪、会话模式、输出类型 | 默认不持久写 | `ToneProfile` | 否 | 否 |
| `KnowledgeProvider` | 文档、wiki/API、游戏文本、web snippets | `KnowledgeSource` / `KnowledgeChunk` | `RetrievalResult` | 可选，用于摘要/重排 | 否 |
| `AliasProvider` | 插件别名表、游戏术语、用户修正 | 作用域别名表 | 实体扩展和消歧 | 否 | 否 |
| `ImageKnowledgeProvider` | 图片资产和元数据 | 图片实体索引 | 图片检索结果 | 可选，用于 caption | 否 |

接口规则：provider 可以丰富 `ContextBundle`、`CapabilityInput` 或 `CapabilityResult`，但不能选择最终 `send_policy`，不能绕过 `ReviewResult`。

## 数据流

```text
IncomingMessage
-> EmotionSignal
-> MemoryQuery
-> MemoryRetrievalResult
-> KnowledgeRetrievalQuery
-> KnowledgeRetrievalResult
-> PersonaProfile + ToneProfile
-> ContextBundle
-> GenerationRequest or CapabilityInput
-> CapabilityResult
-> ReviewResult
-> RenderedOutput
-> SendRequest
```

规则：

- `EmotionSignal`、记忆事实、聊天历史、搜索片段、知识块都是不可信事实。
- `PersonaProfile`、运行时策略、安全策略、运营配置是可信指令。
- 群聊比私聊使用更少个人上下文，除非同意和策略允许。

## 按关注点的参数流

| 关注点 | 输入参数 | 内部处理 | 归一化输出 | 最终消费者 |
| --- | --- | --- | --- | --- |
| 情绪感知 | `plain_text`、提及、回复上下文、图片 caption、近期历史、会话模式 | 规则/LLM 分类、置信度阈值、短 TTL、受保护属性阻断 | `EmotionSignal`，含 `support_need`、`expression_style`、`privacy_level` | 语气选择和审查 |
| 记忆读取 | `requester_id`、`subject_user_id`、`session_id`、`group_id`、`purpose`、`time_window`、`max_items`、`consent_basis` | 作用域解析、归档/事实/向量检索、重排、脱敏、过期/矛盾过滤 | `MemoryRetrievalResult` | 上下文组装 |
| 记忆写入 | 观察消息、显式偏好编辑、敏感度、作用域、同意 | 价值门、去重、可选抽取、SQL 真源写入、索引更新 | `MemoryFact`、raw ref 或跳过审计 | 未来检索 |
| 人设稳定 | `persona_profile_id`、版本、会话绑定、运营配置 | 加载包、校验必填、允许的会话覆盖、拒绝自修改 | `PersonaProfile` 和不可变 prompt 段 | prompt 和人格审查 |
| 说话风格 | 会话模式、输出类型、情绪、人设规则、风险/隐私 | 选择 `ToneProfile`、限制长度和条数、清理禁用标记、必要时改写 | 已审查文本或阻断 | `RenderedOutput` |
| 知识检索 | `query_text`、实体、标签、来源类型、新鲜度、引用要求 | 来源过滤、BM25/向量检索、重排、引用组装、可答性判断 | `RetrievalResult` | 能力生成和事实审查 |

每一行都必须保留 `request_id`、`session_id`、`privacy_level`、`risk_level`、`debug_id` 和来源引用。

## 核心模型

### EmotionSignal

```text
EmotionSignal
- request_id
- session_id
- speaker_id
- source: rule_based, text, image_caption, reaction, recent_history, memory_summary
- signal_kind: emotion, support_need, task_need, energy, friction
- emotion_label
- confidence
- evidence
- guidance
- privacy_level

后续扩展字段：

```text
- session_type
- signal_scope: message, session, group
- valence: negative, neutral, positive, mixed, unknown
- arousal: low, medium, high, unknown
- emotion_intensity
- emotion_confidence
- user_attitude
- bot_emotion
- expression_style
- tts_style_hint
- sticker_mood_hint
- intent_hint: venting, asking_help, joking, conflict, celebration, neutral, unknown
- support_need: none, light_ack, comfort_first, deescalate, clarify
- confidence
- evidence_refs
- updated_at
- expires_at
```

规则：

- 群聊中不直接说出情绪标签。
- 不推断受保护属性或心理疾病。
- 情绪信号只用于调整顺序和语气，比如先安抚再回答。
- 低置信度用中性措辞或澄清。
- 情绪数据默认短期过期，长期记忆需要明确同意。

### MemoryQuery

```text
MemoryQuery
- request_id
- query
- query_text
- requester_id
- subject_user_id
- session_id
- group_id
- memory_scope
- scopes
- entities
- vector_ref
- purpose: reply_context, personalization, summary, recommendation, auto_send, audit
- time_window
- max_items
- max_chars
- per_type_limit
- final_limit
- include_raw_messages
- include_summarized_facts
- include_preferences
- consent_basis
- privacy_level
```

规则：

- `subject_user_id` 默认当前用户，跨用户读取需要策略理由。
- 群记忆和用户全局记忆是不同作用域。
- 原始消息读取比摘要事实更敏感。
- 结果必须带来源 id 和时间戳。

### MemoryFact

```text
MemoryFact
- fact_id
- scope_key
- subject_id
- predicate
- object
- summary
- source_refs
- observed_at
- valid_from
- valid_until
- confidence
- sensitivity: public, group, personal, credentialed
- contradiction_state: none, superseded, disputed
- memory_kind: episode, entity, edge, preference, profile
```

规则：

- 记忆事实是证据，不是指令。
- `sensitivity` 决定公开边界：`public` 可用于公开场景，`group` 只适合同群上下文，`personal` 默认只在私聊或受控上下文使用，`credentialed` 不能进群聊公开输出。
- `scope_key` 是审计和隔离键，首版由当前会话生成，例如 `session:private:42` 或 `session:group:100`。
- 过期或被矛盾的事实默认不注入当前回答。
- 偏好记忆只在相关任务中影响格式和工具选择。
- 未来必须支持查看、删除、导出和 opt-out。

### MemoryRetrievalResult

```text
MemoryRetrievalResult
- request_id
- query_id
- scopes_searched
- facts
- raw_message_refs
- candidate_notes
- memory_id_mapping
- note_id_mapping
- ordered_ids
- vector_scores
- final_score
- score_kind
- omitted_count
- redaction_notes
- confidence
- privacy_level
- debug_id
```

规则：

- prompt 组装前脱敏。
- 群预览和公共审计不包含原始私聊。
- 记忆读取失败时可降级无记忆，或按功能要求请求同意。

### PersonaProfile

```text
PersonaProfile
- profile_id
- version
- display_name
- persona_name
- persona_profile
- identity
- identity_rules
- role_boundaries
- boundary_rules
- worldview
- relationship_model
- allowed_topics
- allowed_behaviors
- forbidden_behaviors
- forbidden_phrases
- forbidden_patterns
- style_rules
- speech_style_markers
- speech_examples
- world_mapping
- refusal_templates
- rewrite_templates
- ooc_thresholds
- references
- assets
- owner_notes
- updated_at
```

规则：

- 人格配置可信，但不能覆盖安全和隐私。
- 人设变更需要显式运营操作和版本记录。
- `owner_notes` 不对用户可见。
- `world_mapping` 可把现实概念转成角色语言，但事实清晰优先。

### ToneProfile

```text
ToneProfile
- profile_id
- mode: private_chat, group_chat, command_answer, tool_result, comfort, digest, alert
- voice
- style
- voice_prompt
- voice_clone
- style_hint
- group_style
- persona_tts
- emotion_tag
- tone_error_rate
- length_hint
- formality
- warmth
- humor_level
- directness
- allowed_markers
- banned_markers
- message_count_limit
- markdown_allowed
- emoji_allowed
- image_comment_policy
```

规则：

- 群回复默认一条短消息。
- 私聊可以更温暖、更长一点。
- 工具结果必须先清楚和有来源，再人格化。
- 避免重复口头禅、模板化语气、可见角色扮演控制标签和 AI/meta 免责声明。

### KnowledgeSource

```text
KnowledgeSource
- source_id
- source_type: manual_doc, game_text, wiki, web_search, media_transcript, plugin_knowledge, image_knowledge
- title
- uri
- provider
- domain
- language
- license
- trust_level: curated, official, community, web, unknown
- update_policy: static, manual_refresh, scheduled_refresh, live_fetch
- allowed_scopes
- privacy_level
- risk_level
```

例子：

- 鸣潮游戏内书籍和文本：`source_type=game_text`。
- Kuro wiki、WWwiki、XutheringWavesUID 攻略：`source_type=wiki` 或 `plugin_knowledge`。
- 互联网搜索：`source_type=web_search`，`trust_level=web`。
- 角色图片和卡片资产：`source_type=image_knowledge`。

### KnowledgeIngestionRequest

```text
KnowledgeIngestionRequest
- request_id
- source_id
- input_ref
- input_kind: file, directory, url, pasted_text, plugin_registry, generated_transcript
- doc_id
- title
- tags
- language
- scope_key
- chunk_size
- chunk_overlap
- replace_existing
- source_url
- license
- created_by
- privacy_level
```

### KnowledgeChunk

```text
KnowledgeChunk
- chunk_id
- doc_id
- source_id
- title
- chunk_index
- content
- content_hash
- tags
- source_url
- source_position
- language
- scope_key
- embedded_at
- expires_at
- privacy_level
```

### RetrievalQuery / RetrievalResult

```text
RetrievalQuery
- request_id
- query
- query_text
- entities
- source_types
- tags
- scope_keys
- memory_scope
- candidate_limit
- bm25_limit
- max_chunks
- max_chars
- score_policy
- rerank
- freshness_required
- require_citation
- privacy_level
```

```text
RetrievalResult
- request_id
- query_id
- chunks
- citations
- sources
- ordered_ids
- vector_scores
- final_score
- answerable
- confidence
- freshness
- omitted_count
- privacy_level
- debug_id
```

规则：

- `answerable=false` 时应澄清、搜索或拒绝猜测。
- 互联网搜索和变动 wiki 需要 freshness。
- RAG 不能决定发送，只能提供上下文。

### ContextBundle

```text
ContextBundle
- request_id
- persona_profile_id
- tone_profile_id
- trusted_policy
- current_message
- emotion_signals
- memory_results
- conversation_history
- knowledge_results
- tool_results
- context_budget
- omitted_sections
- privacy_level
- risk_level
```

规则：

- 可信指令和不可信事实分区。
- 模型调用前执行预算。
- 低价值内容省略或摘要。
- 附 `source_refs` 供输出审查。

## 情绪感知策略

允许用途：

- 决定先安抚还是直接答。
- 用户疑似难过时减少讽刺。
- 群冲突时降温。
- 判断短回应是否优于长解释。

禁止用途：

- 公开说某用户“愤怒、抑郁、不稳定、操控”等。
- 未同意长期保存敏感情绪。
- 用情绪信号绕过权限或主动骚扰。
- 从一句话推断稳定私人事实。

## 记忆读写策略

三层记忆：

- 原始归档：适配器中立消息记录，建议 chatrecorder 风格。
- 长期事实：作用域化事实、档案、偏好、关系。
- 检索上下文：一次请求临时 prompt 素材。

写入规则：

- 原始归档遵循聊天记录策略。
- 长期记忆写入需要价值门、作用域隔离和敏感度分类。
- 高敏感事实需要私聊同意和可见控制。
- 机器人自我记忆放在独立 self scope。

读取规则：

- 私聊可在同意后用更多个人上下文。
- 群聊优先用群级上下文和公共知识。
- auto-send 按收件人独立读取。
- 历史、记忆、搜索都标为不可信事实。

## 人设稳定策略

人设稳定靠结构：

- `identity`：角色是谁。
- `role_boundaries`：角色不会宣称或执行什么。
- `worldview`：如何看待问题。
- `speech_examples`：风格锚点，但不强迫复读。
- `forbidden_behaviors`：阻断助手味、meta 味和 OOC 漂移。
- `ooc_thresholds`：定义 allow/rewrite/block。

运行时记忆可以影响角色“知道某用户什么”，但不能改写角色是谁。

## 说话方式策略

输出流水线审查：

- OOC 泄漏；
- 无来源事实；
- 过度亲密；
- 重复短语；
- 旧回复风险；
- 群刷屏风险；
- markdown/格式滥用；
- 用户没要求时过度描述图片。

动作：

- `allow`
- `rewrite`
- `move_private`
- `block`
- `audit_only`

## 知识库策略

| 来源类型 | 早期可用 | 规则 |
| --- | --- | --- |
| 鸣潮书籍/文本 | 是 | 按版本、来源、语言导入为 chunk。 |
| 公共 wiki/攻略 | 是 | 引用来源，监控上游变化。 |
| 公共游戏卡片 | 是 | 模板只是展示，不是事实源。 |
| 互联网搜索 | 是，先命令触发 | 引用片段，标记易变，不当指令。 |
| 媒体转写 | 后续 | 记录版权/来源/新鲜度。 |
| 账号游戏数据 | 后续 | 私聊、可撤销、凭据化。 |
| 图片知识 | P1/后续 | 存路径、标签、描述、许可、隐私。 |

鸣潮知识优先级：

1. 本地整理的游戏文本和书籍。
2. 官方或 Kuro 相关 wiki。
3. 本地参考，如 `XutheringWavesUID` 和 `WWwiki`。
4. 有作者/来源信息的社区攻略。
5. 互联网搜索作为新鲜但低信任证据。

## Knowledge Ingestion Pipeline

知识导入把书籍、TXT、Markdown、wiki、插件数据和 web extract 转成可检索证据。它不是聊天回复路径。

```text
KnowledgeIngestionRequest
-> SourcePolicyCheck
-> DocumentLoader
-> NormalizedDocument
-> Chunker
-> KnowledgeChunk
-> SQL truth write
-> Vector/BM25 index update
-> IngestionReceipt
-> AuditRecord
```

### NormalizedDocument

```text
NormalizedDocument
- doc_id
- source_id
- title
- language
- content_format: markdown, txt, html, json, jsonl, transcript, image_caption
- content_ref
- content_hash
- tags
- source_url
- source_position
- license
- scope_key
- privacy_level
- created_by
```

规则：

- SQL 或文件元数据是真源，向量库只是索引。
- 长书籍、攻略、wiki 导出和网页必须先切块。
- chunk id 由 `doc_id`、chunk index 和 content hash 稳定生成。
- 互联网知识记录抓取时间、URL、provider 和 freshness。
- 未知版权不阻止元数据索引，但阻止全文公开转发。

### IngestionReceipt

```text
IngestionReceipt
- request_id
- source_id
- doc_id
- chunks_created
- chunks_updated
- chunks_deleted
- skipped_reason
- index_status: not_indexed, indexed, partial, failed
- debug_id
```

规则：

- 索引失败不删除 SQL 真源。
- 替换只影响同一 `doc_id` 和 `scope_key`。
- 手动导入、插件知识和定时刷新都用同一 receipt。

## 鸣潮知识包

```text
BotKnowledgePackage
- package_id
- version
- game_version
- sources
- aliases
- documents
- image_entities
- card_templates
- refresh_policy
- license_notes
```

推荐内容：

- 游戏内书籍和 lore 文本；
- 角色、武器、声骸、合鸣、活动、地图、教程文档；
- 中/英/日名称、昵称、歧义词别名表；
- 来自 `WWwiki`、`XutheringWavesUID` 或本地整理数据的公共卡片；
- 互联网搜索只作新鲜证据，不作基础真源。

鸣潮回答必须带 `source_refs`；知识包无法支撑时设置 `answerable=false`。LLM 可以用角色语气解释不确定，但不能编游戏事实。

## Prompt 组装规则

```text
Trusted:
- system policy
- persona profile
- tone profile
- runtime safety and privacy rules

Current request:
- normalized message
- command/capability input

Untrusted facts:
- recent chat context
- memory facts
- knowledge chunks
- parser/source results
- internet search snippets

Generation contract:
- expected output schema
- max messages
- source/citation requirement
- no-send limitations
```

模型可以生成文本或结构化 `CapabilityResult`。模型不能决定最终发送策略、覆盖确认或绕过审查。

## 模块边界

```text
plugins/bot_unified_runtime/character/
  emotion.py
  memory_query.py
  persona.py
  tone.py
  context_bundle.py
  review.py

plugins/bot_unified_runtime/knowledge/
  sources.py
  ingestion.py
  chunking.py
  retrieval.py
  citations.py
  aliases.py

plugins/bot_unified_runtime/contracts/
  character.py
  knowledge.py
```

依赖规则：

- `character/*` 可依赖 contracts、policy、memory/query、knowledge retrieval。
- `knowledge/*` 可依赖 fetch adapters、parsers、embedding providers、storage。
- 二者都不能依赖具体发送 API。
- 输出审查消费人格元数据，但由共享 output pipeline 拥有。

## 验收检查

首版应测试：

- `EmotionSignal` 不在群输出中原样暴露。
- 未授权不能读取另一个用户的记忆。
- 私密记忆在群中映射到 `privacy_blocked` 或 `move_private`。
- `PersonaProfile` 按 id 和版本加载；首版通过 `FileCharacterContextProvider` 从 Markdown/TXT/DOCX 配置文件加载。
- 基础聊天 prompt 包含 `PersonaProfile`、`ToneProfile`、`MemoryRetrievalResult`、`RetrievalResult` 和反注入边界。
- `bot.chat` 能力只返回 `CapabilityResult`，不能直接发送。
- LLM 输出要求泄漏内部标记、prompt、token、cookie 或 key 形态时会在 `ReviewResult` 阶段阻断。
- 严重 OOC 输出被改写或阻断。
- `ToneProfile` 限制群消息数量。
- TXT/Markdown/DOCX 知识导入或首版本地文件 provider 生成稳定 chunk id。
- 检索结果有来源引用，或说明为什么没有。
- 互联网片段标记为 untrusted。
- 公共鸣潮 wiki 输出返回 `CapabilityResult`，不直接发送。
- 账号游戏数据在密钥和私聊策略前被阻断。
- provider 可丰富 `ContextBundle`，但不能创建 `SendRequest`。
- 每次上下文组装都有脱敏审计事件。

## 设计结论

人格智能应作为统一运行时背后的上下文服务：

- 情绪感知只塑造语气，不做诊断。
- 记忆是有作用域的证据，不是权威。
- 人设结构化、版本化。
- 说话方式由审查层执行。
- 知识有来源、切块、可审计。
- 公共鸣潮知识是早期安全能力。
- 账号和凭据数据私聊优先、后续实现。

这样既能保持角色稳定，又能给未来插件留下清晰接口。
