# WuWa-Character-Bots

这是一个面向鸣潮角色机器人、ACG/游戏助手、媒体解析和自动发送能力的统一 NoneBot 项目。

当前仓库已经进入 Milestone 0 实现阶段：研究和规格设计已经完成，`plugins/wuwa_unified_runtime` 提供了统一运行时插件骨架、契约模型、策略门、回复预算、内存/可选 SQLite 窗口限速、安静时间策略、审查/渲染、内存默认且可选 SQLite 持久化的发送回执和审计、可选 SQLite 发送队列、租约 claim 和一次性 drain worker、OneBot/NapCat text/image/json/mixed transport 及本地 transport smoke、人格/知识/provider 接口、parser registry 和 auto-send draft parser。

后续不要从单个插件文件直接开写，而是继续遵守统一命令入口、运行时契约、人格/记忆/知识约束和发送审计链路。

## 开发命令入口

本项目在 Windows 上统一使用 `scripts/dev.ps1`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dialogue-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 persona-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-setup
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 console
```

完整命令矩阵见 [COMMANDS.md](COMMANDS.md)。

## 最小可执行程序：控制台聊天

不需要 NapCat、不需要 QQ，就能真实体验整条机器人流水线：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 console
```

默认使用离线 `static` provider（不联网、不花钱）。接入真实模型有两种方式：

1. 复制 `.env.example` 为 `.env`，填 `WUWA_CHAT_PROVIDER=openai_compatible`、`WUWA_CHAT_MODEL`、`WUWA_CHAT_API_KEY`、`WUWA_CHAT_BASE_URL`；
2. 或用命令行参数临时覆盖（不写 `.env`）：

```powershell
.venv\Scripts\python.exe -m plugins.wuwa_unified_runtime.console_chat `
  --provider openai_compatible --model deepseek-chat `
  --base-url https://api.deepseek.com/v1 --api-key sk-xxx
```

单轮模式适合脚本和验证：`scripts/dev.ps1 console -Message "你好"`（回复成功退出码 0，否则非 0）。

控制台内命令：`/help`、`/status`、`/why`、`/quit`。配置 `WUWA_RUNTIME_PERSONA_NICKNAME=岸宝` 后，还能用角色昵称命令：`/岸宝帮助`、`/岸宝状态`、`/岸宝为什么`。REPL 会保留内存多轮对话历史（退出即清空），不连接 NapCat、不发送 QQ。

## 处理流程图（直白版）

```text
收到消息（QQ / 控制台 / 邮件）
      │
      ▼
① 归一化 IncomingMessage（会话类型 / 发送者角色 / 文本）
      │
      ▼
② 策略门 PolicyEvaluation
      ├─ 拉黑 / 风险过高 ──→ 阻断（不花钱）
      ├─ 群聊没@也没命令前缀 ──→ 静默观察（不调 LLM）
      └─ 通过 ──→ ③
③ 安静时间检查 QuietHours（夜间群聊）──命中→ 阻断
      │ 通过
      ▼
④ 回复预算 + 窗口限速（全局/会话/用户/目标间隔）──命中→ 阻断
      │ 通过
      ▼
⑤ 决策 BotDecision（回什么能力 / 最多几条 / 怎么发）
      │
      ▼
⑥ 能力执行 Capability（以 wuwa.chat 为例）
      ├─ 提示注入防护：高危请求 ──→ 直接拒绝
      ├─ 组装上下文：人格 + 语气 + 记忆 + 历史 + 知识
      │              + 时梗 + 环境信息（时间/天气/节气/节日）
      ├─ 参数预检（base_url/温度/token 非法 ──→ 不联网兜底）
      ├─ LLM 生成（默认 static 离线；配了模型才联网）
      └─ 输出收口（多段回复按预算裁剪）
      │
      ▼
⑦ 输出审查 Review（密钥泄漏检测 + 人格漂移检测）
      ├─ 泄漏 / 人格漂移 ──→ 白名单兜底提示，不发原文
      └─ 通过 ↓
⑧ 渲染 RenderedOutput（文本 / 卡片 / 图片 / 合并转发 + 文本兜底）
      │
      ▼
⑨ 发送 SendRequest（唯一出口；dedupe 去重键 + cooldown 冷却键）
      │
      ▼
⑩ 投递 Transport（NapCat 消息段 / SQLite 队列租约 + 重试 worker）
      │
      ▼
⑪ 回执 DeliveryReceipt（sent / queued / skipped / blocked / failed…）
      │
      ▼
⑫ 审计 + 运行诊断（每阶段留痕、脱敏）──→ 管理员 /wuwa why 可解释
```

**上网查询子流程**：`链接/搜索词 → URL 去跟踪参数 → FetchRequest（超时/重试/限频/robots/凭据引用）→ FetchResult → 归一化 → 审查 → 渲染 → 发送`；搜索结果一律标记"不可信、可能过时"。

**免 LLM 决策**：回不回消息完全由确定性规则决定（角色名单 → 群前缀/提及 → 软暂停 → 安静时间 → 限速 → 回复预算），LLM 只在最后"生成文本"时才花钱。

## 当前架构基线

高置信运行时链路如下，英文类型名是后续代码和测试要保留的锚点：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

人话解释：

1. `IncomingMessage` 把 NoneBot / OneBot / NapCat / Mail / Console 等适配器事件规整成统一输入。
2. `PolicyEvaluation` 先判断权限、群/私聊策略、冷却、隐私、风险和是否允许回复。
3. `BotDecision` 决定调用哪个能力、是否回复、最多发几条、走即时/队列/摘要/私聊回退/管理员确认。
4. 能力插件只返回 `CapabilityResult`，不能自己调用发送 API。
5. 人格、记忆、知识库、情绪感知和安全审查一起进入 `ReviewResult`。
6. `RenderedOutput` 把文本、卡片、图片、合并转发等输出准备好。
7. `SendRequest` 是唯一的发送入口。
8. `DeliveryReceipt` 记录是否排队、已发、跳过、失败、被拦截或转私聊。
9. `AuditRecord` 记录完整审计，方便以后修问题。

核心原则：能力适配器、来源适配器、解析器、知识库、人格服务和记忆服务都不能直接发送消息。它们只提供结构化结果，最终发送只能通过 `SendRequest -> DeliveryReceipt -> AuditRecord`。

权限角色首版已经参数化：`WUWA_ADMIN_USER_IDS`、`WUWA_ENTERPRISE_USER_IDS`、`WUWA_TRUSTED_USER_IDS` 和 `WUWA_BLOCKED_USER_IDS` 可在 `.env` 中用 JSON 数组、英文逗号或分号填写 QQ user_id。运行时会把它们解析成 `IncomingMessage.sender_roles`，再进入 `PolicyEvaluation.actor_roles` 和 `BotDecision.actor_roles`；拉黑用户会在 policy 阶段被阻断，其他角色会进入审计标签。`/wuwa status`、`/wuwa roles` 和 `nonebot-smoke` 只显示各类数量、角色顺序、绕过规则和配置格式，不显示具体 ID。

群命令前缀也已从配置进入策略门：`WUWA_RUNTIME_GROUP_COMMAND_PREFIX` 会影响群聊被动消息是否触发能力链路，避免代码里硬编码 `/wuwa`。普通群消息如果未命中命令前缀、也没有提及机器人，会在 `passive_group_message` 阶段静默阻断：不调用 LLM、不创建发送请求、不向群里回复“未启用主动回复”，但仍保留审计和 `/wuwa why` 可解释的诊断记录。

## 核心规格文档

- [运行时参数流](docs/specs/runtime-parameter-flow.md)
- [输入输出契约](docs/specs/input-output-contracts.md)
- [自动发送能力](docs/specs/auto-send-capability.md)
- [人格智能与知识库](docs/specs/character-intelligence-and-knowledge.md)
- [媒体来源流水线](docs/specs/media-source-pipeline.md)

这些文档定义消息、策略、人格上下文、记忆读取、知识检索、媒体解析、能力结果、审查结果、渲染输出、发送请求、回执和审计如何在统一运行时里传递。

## 人格优先与插件例外

普通自然语言回复必须依靠已配置的人格设定、角色性格、说话方式、情绪感知、记忆数据库、最近对话和知识库来生成。也就是说，机器人“怎么说话”和“记得什么”不是临场乱编，而是由 `PersonaProfile`、`ToneProfile`、`EmotionSignal`、`MemoryRetrievalResult`、`ConversationHistoryResult` 和 `RetrievalResult` 明确传入。

当前基础对话链路已经接入统一运行时：普通文本消息会构造 `ContextBundle`，组装带人格、记忆、知识和反注入边界的 prompt，经 `LLMProvider` 生成回复，再转换成 `CapabilityResult`，继续通过 `ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`。默认 provider 是 `static`，不会访问外部网络；接入真实模型时可配置 OpenAI-compatible `/chat/completions` 接口。

基础对话已加入 `ReplyBudgetSettings`。运行时会按消息意图、会话类型和风险等级决定 `max_messages` 与 `context_budget`：普通私聊默认 1 条，明显需要安慰/陪伴的私聊最多 2 条，深度请教/排查类私聊最多 3 条，群聊和中高风险输入会压回 1 条。所有阈值都可通过 `WUWA_REPLY_*` 配置调整，结果会写入 `BotDecision`、`SendRequest` 和 `reply_budget:*` 审计标签，避免 LLM 自己决定刷屏。

基础对话也已加入调用 LLM 前的窗口限速。默认使用 `InMemoryRateLimiter`，会按 `WUWA_RATE_LIMIT_WINDOW_SECONDS`、`WUWA_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS`、`WUWA_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS` 和 `WUWA_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS` 统计当前进程内的全局/会话/发送者回复预算消耗；配置 `WUWA_RATE_LIMIT_DB_PATH` 后会切换为 SQLite 持久限速，重启后仍保留窗口内记录。`WUWA_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` 可限制同一目标的最小回复间隔，避免同一群或同一用户被连续刷屏，默认 `0` 表示关闭。命中后在 policy 阶段阻断，不调用 LLM，不创建 `SendRequest`，并写入 `rate_limited` 审计事件。`WUWA_RATE_LIMIT_BYPASS_ROLES` 默认允许 `admin` 绕过。

基础对话和后续自动发送共用 `QuietHoursChecker`。默认 `WUWA_QUIET_HOURS_ENABLED=false`，不影响当前私聊对话；启用后按 `WUWA_QUIET_HOURS_START`、`WUWA_QUIET_HOURS_END` 和 `WUWA_QUIET_HOURS_TIMEZONE` 判断本地时间，默认只作用于 `WUWA_QUIET_HOURS_SESSION_TYPES=["group"]`，避免午夜群聊刷屏。命中后在 policy 阶段阻断，不调用 LLM，不创建 `SendRequest`，并写入 `quiet_hours_blocked` 审计事件；`WUWA_QUIET_HOURS_BYPASS_ROLES=["admin"]` 默认允许管理员绕过。`why-smoke` 和 `/wuwa why` 会把它解释成“安静时间，已在调用 LLM 前阻断”。

基础对话输出也会再次按回复预算收口。真实模型如果返回多个空行分隔的“拟似多条消息”，`wuwa.chat` 会在生成 `CapabilityResult` 前只保留 `BotDecision.max_messages` 允许的前几段，并追加避免刷屏的简短提示；审计标签会写入 `llm_output_trimmed`。`why-smoke` 和 `/wuwa why` 会把这个标签解释成“模型输出超过预算，已按回复预算收口”，方便排查为什么用户只看到前几段。这样即使模型无视 prompt 里的最多回复条数，最终也不会把多段输出完整推给 sender。

基础对话入口已加入结构化 `PromptInjectionGuard`。普通的“忽略之前规则/切换系统身份/绕过运行时”类文本会被包进 `[UNTRUSTED_USER_TEXT]` 分区并提高风险标签；要求泄露系统提示、API key、token、cookie、本机文件或执行脚本的高危输入会在调用 LLM 前返回安全拒绝，并写入 `prompt_injection:*` 审计标签。

基础对话也会安全处理人格/知识上下文读取失败。如果 `FileCharacterContextProvider` 因人格文件、知识文件或 DOCX 解析问题无法构造 `ContextBundle`，`wuwa.chat` 不会调用 LLM，也不会把本机路径、文件名或异常正文发给用户；它会返回一条守岸人风格的安全提示，并写入 `context_error`、`context_error:provider_failed` 审计标签。`/wuwa why` 和 `why-smoke` 会把这类情况解释为“人格或知识上下文读取失败，已跳过 LLM”，避免误判成真实模型已调用。

基础输出审查也已加入最低限度泄漏防线和人格漂移防线。LLM 或插件输出中如果出现内部上下文标记、明显 API key/token/cookie/authkey/Authorization/Bearer/sk key 泄漏形态，会在 `ReviewResult` 阶段阻断，不会生成 `SendRequest`；`wuwa.chat` 如果输出“作为 ChatGPT/AI 语言模型”、拒绝守岸人身份或否认角色人格，也会被作为 `persona drift` 阻断。纯人格漂移阻断会给用户一条守岸人风格的安全兜底提示，引导重新提问，但被拦截的原始模型输出仍不会发送。审计原因会脱敏，避免排障日志二次泄漏；`/wuwa why` 和 `why-smoke` 只会把这类阻断归一化成 `review_blocked`、`persona_drift` 或 `unsafe_output_leakage` 等安全标签，不展示原始模型输出。

真实模型接入可用 `scripts/dev.ps1 llm-smoke` 单独诊断。它只检查 provider/model/base_url/API key 状态、归一化后的 endpoint、生成参数、HTTP 超时和一次短模型调用，不启动 NapCat、不发送 QQ 消息、不打印密钥；缺少真实 API key、model、base_url，或 `WUWA_CHAT_TEMPERATURE` 不在 0.0-2.0、`WUWA_CHAT_MAX_TOKENS < 1`、`WUWA_CHAT_TIMEOUT_SECONDS <= 0` 时不会发起 provider 调用，`.env.example` 中的 `your-api-key` 会被当成未配置，避免误触发网络请求。`llm-smoke` 会同时输出 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons` 和 `llm_fix_hints`，方便直接判断下一步是修配置、配置真实模型，还是继续跑短连接诊断。`WUWA_CHAT_BASE_URL` 可以填 OpenAI-compatible 根地址（如 `https://api.openai.com/v1`），也可以填完整的 `/chat/completions` endpoint；运行时会归一化为最终请求地址，避免重复拼接。空 base_url、非 HTTP(S) base_url、无法解析的 base_url 或带用户名/密码的 base_url 会在联网前被阻断，分别归因到 `openai_base_url_missing`、`openai_base_url_invalid` 或 `openai_base_url_unsafe`；生成参数错误会归因到 `openai_temperature_invalid`、`openai_max_tokens_invalid` 或 `openai_timeout_seconds_invalid`；如果地址里误放了凭据，摘要里的 `endpoint_url` 只显示 `[redacted]`。真实机器人运行时，管理员也可以用 `/wuwa llm` 从 NoneBot 入口执行同类在线诊断；它仍走统一 pipeline，只输出 `ok/ready_for_real_llm/llm_readiness_status/llm_next_action/llm_readiness_reasons/llm_fix_hints/provider/model/endpoint_url/api_key/diagnostic_temperature/diagnostic_max_tokens/timeout_seconds/error_kind/reply_preview_chars/usage_total_tokens/public_message` 等安全字段，不展示密钥、Authorization/Bearer、原始上游错误或完整模型回复。`llm_fix_hints` 只给安全、可执行的配置占位提示，例如 `WUWA_CHAT_PROVIDER=openai_compatible`、`WUWA_CHAT_API_KEY=<real_api_key>`、`WUWA_CHAT_TEMPERATURE=0.0..2.0` 或 `remove_credentials_from_WUWA_CHAT_BASE_URL`；它不会包含真实 API key、真实文件路径、prompt、用户原文或 provider 原始错误。`error_kind` 会区分 `provider_not_configured`、`config_missing`、`timeout`、`auth`、`rate_limited`、`server`、`http`、`network`、`schema`、`empty_response` 和 `provider_error`。普通聊天链路如果触发 `llm_error:<kind>`，或模型虽然成功返回但文本为空白，`chat-smoke`、`why-smoke` 和 `/wuwa why` 会额外输出安全字段 `llm_error_kind=<kind>`；用户侧会收到守岸人风格的兜底提示，空白回复会归类为 `empty_response`，避免发送空消息或机械 debug 文案。`why_summary` 中会说明 “LLM 调用失败，错误类型是 <kind>”；如果是生成参数预检触发的 `llm_preflight_blocked`，则会说明“LLM 生成参数或配置非法，已在调用 provider 前阻断”，并只列出 `openai_temperature_invalid`、`openai_max_tokens_invalid` 和 `openai_timeout_seconds_invalid` 这类稳定原因码。上述诊断都不会展示原始 provider 错误、用户原文、prompt、API key 或 Authorization/Bearer。

如果你还没开始填真实模型配置，可以先跑 `scripts/dev.ps1 llm-setup`。它把 `config-smoke` 的 LLM 就绪状态翻译成 `llm_setup_status=needs_env_edit|blocked|ready_for_probe`、必填 `WUWA_CHAT_*` 项、安全 `.env` 占位模板和下一步命令序列；它不会写 `.env`，不会调用真实 LLM provider，不连接 NapCat，不发送 QQ，也不会输出真实 API key、本机路径、prompt 或人格正文。真实机器人运行时，管理员也可以用 `/wuwa setup llm` 查看同一份只读接入清单；它仍走统一 pipeline，只输出安全字段，不写 `.env`、不调用 provider、不连接 NapCat、不发送外部消息，也不会覆盖最近一次业务诊断。

接真实模型前也可以先跑 `scripts/dev.ps1 doctor`、`scripts/dev.ps1 readiness-smoke` 和 `scripts/dev.ps1 config-smoke`。`doctor` 诊断当前 PowerShell/Python 环境是否能导入 `nonebot`、OneBot V11 adapter、`nonebot_plugin_apscheduler`、统一运行时插件并找到 `nb` CLI；它会输出 `ready_for_local_llm_smoke` 与 `ready_for_nonebot_run`，缺依赖时给出 `scripts/dev.ps1 install` 建议。`readiness-smoke` 是统一就绪摘要：聚合环境、配置、上下文构造和本地基础聊天 pipeline，输出 `readiness_status=ready|local_only|blocked`、`next_action`、`recommended_commands`、`ready_for_local_dialogue`、`ready_for_real_llm`、`context_ok`、`chat_pipeline_ok`、LLM 就绪原因码和 `llm_fix_hints`；它只用 `local_static_probe` 验证聊天链路，固定输出 `real_llm_probe_performed=false`，不调用真实 LLM、不连接 NapCat、不发送 QQ，也不打印完整回复、prompt、路径或密钥。真实机器人运行时，管理员也可以用 `/wuwa readiness` 查看同源在线摘要；该命令仍走统一 pipeline，只展示环境/config/context/chat/NoneBot/transport 的安全白名单字段，并额外展示当前进程 `runtime_soft_paused`、安全 reason 和 `updated_by=set|missing`；它不调用真实 LLM、不连接 NapCat、不发送外部业务消息，也不会覆盖最近一次业务诊断。`config-smoke` 是只读配置体检，不调用 LLM、不启动 NapCat、不发送消息；会检查人格文件、知识文件、文件是否可解析且非空、人格材料是否过薄、聊天开关、provider/model/base_url/API key、endpoint、base_url 是否为空/非法/含凭据、生成参数范围、回复限速、安静时间和持久化开关，并输出 `ready_for_real_llm=true|false`、`llm_readiness_status=ready|local_only|blocked`、`llm_next_action=fix_config|configure_real_llm|llm_smoke`、`llm_readiness_reasons`、`llm_fix_hints`、`errors` 与 `warnings`。`ready` 表示真实 OpenAI-compatible provider 的关键配置和生成参数都具备且没有阻断错误，`local_only` 表示本地 pipeline 可验但还不是可联网真实模型，`blocked` 表示必须先修复错误；`llm_next_action` 会把状态翻译成下一步：先修配置、配置真实模型，或继续跑 `llm-smoke`；`llm_readiness_reasons` 是去重后的 errors + warnings，方便直接看到原因码；`llm_fix_hints` 会从阻断错误优先生成安全修复提示，没有错误时再根据 warning 提示如何接真实模型或补知识文件。`static` provider 会作为 warning 保留，表示本地 pipeline 可验但真实模型尚未就绪；人格文件损坏或为空会作为 error，人格材料过薄会作为 `persona_profile_weak` warning，配置了但损坏的知识文件也会作为 error，知识文件为空会作为 warning，生成参数错误会作为阻断 error。输出只显示 `chat_api_key=set|missing`、安全 `endpoint_url`、`chat_temperature`、`chat_max_tokens`、`timeout_seconds`、`persona_total_chars`、`persona_meaningful_lines`、`persona_strength_status=ok|weak|missing`、`rate_limit_store=memory|sqlite`、`rate_limit_db=set|missing`、限速参数、安静时间参数和可解析性计数，不会展示密钥原文、真实路径、人格正文或解析异常。真实机器人运行时，管理员也可以用 `/wuwa config` 查看同类安全摘要；该命令仍走统一 pipeline，但不会触发模型调用或外部投递，也不会覆盖最近一次业务诊断。

真实 NoneBot / NapCat 接入前可用 `scripts/dev.ps1 nonebot-smoke` 先做本地加载诊断。它检查 `nonebot`、OneBot V11 adapter、统一运行时插件 metadata、统一运行时启停状态、人格/知识文件、记忆/历史/诊断/审计/回执开关、回复限速、安静时间和 LLM 配置摘要，不启动 NoneBot，不连接 NapCat，也不会发送 QQ 消息；它只证明本地插件加载边界和配置摘要正常，不证明真实账号投递成功。输出里的 `runtime_enabled=true|false` 对应 `WUWA_RUNTIME_ENABLED`，只表示 `.env` 或运行环境里的硬开关；真实在线 `/wuwa status` 会额外显示当前进程 `运行时软暂停`，用于区分硬关闭、管理员临时 pause 和 LLM/provider 配置问题。`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons` 和 `llm_fix_hints` 复用 `config-smoke` 的只读配置体检逻辑，用于顺手确认真实模型是否接好和下一步该做什么。更接近真实启动顺序的本地检查是 `scripts/dev.ps1 startup-smoke`：它会在干净子进程里执行 `nonebot.init()`、注册 OneBot V11 adapter、加载统一运行时插件、统计 matcher 优先级并检查 APScheduler 可访问性，然后立即退出；它不会执行 `nb run`，不会启动长驻服务，不连接 NapCat，也不发送 QQ 消息。出站边界可以继续跑 `scripts/dev.ps1 transport-smoke`：它验证项目内 `sender.onebot`、text/image/json/mixed/fallback/forward 消息段和扩展 API 边界、`status/retcode/data.message_id` 解析，以及 fake bot 私聊/群聊/合并转发/失败分类 `send_onebot_v11` 回执映射；同样不会启动 NoneBot/NapCat，不连接 QQ，也不发送真实消息。启动真实 NoneBot / NapCat 后，可以再跑 `scripts/dev.ps1 online-transport-smoke` 做只读在线 bot 诊断：它只读取当前进程的在线 bot 数和 OneBot 风格发送方法可见性，不构造 `SendRequest`，不调用发送 API，不展示 bot id、目标 ID、正文或 provider message id，也不证明某条业务消息已经投递成功。

人格文件、知识文件或 DOCX 变更后，如果只想先确认“守岸人人格材料是否加载”，可用 `scripts/dev.ps1 persona-smoke`。它只输出 `persona_status=ok|weak|blocked`、`persona_next_action`、人格/知识来源安全指纹、人格字符数/有效行数/强度、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪三态和安全 `llm_fix_hints`；不调用 LLM，不启动 NapCat，不发送消息，也不展示人格正文、知识正文、本机路径、prompt、用户原文或密钥。真实机器人运行时，管理员也可以用 `/wuwa persona` 查看同类人格自检摘要；该命令仍走统一 pipeline，并且不会覆盖最近一次业务诊断。

需要进一步确认人格、记忆、知识和当前测试文本如何进入 prompt 时，可用 `scripts/dev.ps1 context-smoke` 看本地上下文诊断。它会构造 `ContextBundle` 和 chat prompt 摘要，输出风格规则、角色边界、禁止行为、人格/知识来源安全指纹、情绪信号、知识 chunk、记忆事实、最近对话轮数、上下文预算、prompt 长度、总字符数、剩余预算、是否整体裁剪、被裁剪的 prompt 分区，以及各分区预算/实际字符数；不会调用 LLM，不启动 NapCat，也不发送消息。`persona_source_refs` 和 `knowledge_source_refs` 只是稳定安全指纹，用来确认来源是否加载或变化，不展示本机路径、文件名、知识正文、prompt 原文或密钥。需要测试特定场景时可以加 `-Message "今天真的很难受，可以陪我慢慢说说吗？"`。真实机器人运行时，管理员也可以用 `/wuwa context [测试文本]` 查看同类安全摘要，用来确认当前会话的人格、知识、记忆、历史、情绪和回复预算是否会进入 LLM 上下文；该命令不调用 LLM，不展示原始用户文本、prompt 原文、知识原文、数据库路径或密钥。

基础对话验收可用 `scripts/dev.ps1 dialogue-smoke`。它会把 `context-smoke` 的人格/知识/记忆/历史/情绪/prompt 安全摘要、`chat-smoke` 的真实 pipeline 回执、LLM 状态和配置下一步动作合到一次输出里，字段包括 `dialogue_status=ready|local_only|blocked`、`next_action`、`context_ok`、`chat_pipeline_ok`、`receipt_state`、`max_messages`、`prompt_total_chars`、`llm_status`、`llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_fix_hints`、`reply_preview_chars` 和 `reply_text_hidden=true`。默认 `static` provider 不访问外部网络；真实 `openai_compatible` provider 如果生成参数非法，会直接显示 `next_action=fix_config`、`llm_status=not_called`，不调用 provider；真实 provider 调用失败时会非零退出，避免把“角色化兜底已生成”误判成“真实模型对话成功”。该命令不连接 NapCat、不发送 QQ、不展示完整回复、prompt、用户原文、知识原文、真实路径、数据库路径或密钥。真实机器人运行时，管理员也可以用 `/wuwa dialogue [测试文本]` 从 NoneBot 入口执行同类一轮对话验收；该命令只发送安全摘要，不展示模型回复正文，并且自身不会覆盖最近一次业务诊断。

基础对话烟测 `scripts/dev.ps1 chat-smoke` 会输出 `llm_status`、`llm_error_kind`、`llm_provider`、`llm_model`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`reply_preview_chars`、`reply_text_hidden=true` 和 `audit_tags`。默认 `static` provider 会标记为 `not_configured`，同时 `llm_readiness_status=local_only`，用于确认 pipeline 可跑但还不是可联网真实模型；真实 `openai_compatible` provider 下生成参数非法会在聊天能力内写入 `llm_preflight_blocked`、`llm_preflight_error:<reason>` 和 `llm_error:config_missing`，不调用 provider；真实 provider 调用错误会标记为 `error`，`llm_error_kind` 会显示 `timeout/auth/schema/provider_error` 等安全错误类型，并让命令非零退出，避免把“错误提示被发送”误当作“模型对话成功”。`chat-smoke` 的 LLM 就绪字段复用 `config-smoke` 的只读配置体检逻辑，只展示稳定原因码和下一步动作，不展示密钥、真实文件路径、原始解析异常或完整回复正文。接真实模型后，也可以加 `-Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 测试回复预算、人格和模型输出。

本地决策解释可用 `scripts/dev.ps1 why-smoke`。它会对一条测试输入输出 `policy_allowed`、`policy_reason`、`actor_roles`、`reply_budget_reason`、`max_messages`、`context_budget`、prompt 安全摘要、上下文计数、`llm_status`、`llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、安全 token usage、`send_request_created`、`receipt_state`、`audit_tags` 和一句 `why_summary`。这个命令不启动 NapCat、不发送 QQ 消息，主要用于排查“为什么回复、为什么不回复、为什么最多回复几条、上下文是否过大、token 用量是否异常、当前真实模型配置是否就绪、下一步该修配置还是跑模型连接诊断”，例如限速阻断、安静时间阻断、刷屏、模型多段回复被预算收口、生成参数预检在调用 provider 前阻断、真实模型 `timeout/auth/schema` 等调用失败、群聊误触发、拉黑用户、运行时暂停、LLM 未配置、人格漂移或输出泄漏被审查阻断。

真实 NoneBot 入口已接入 `/wuwa why [request_id|debug_id]`。运行时会把最近的真实请求记录成脱敏 `RuntimeDiagnostic`，默认查询当前会话最近一次运行记录，也可以按 `request_id` 或 `debug_id` 精确查询；输出包含能力、策略原因、角色、回复预算、prompt 安全摘要、上下文计数、LLM 状态、LLM 安全错误类型、LLM 就绪三态与原因码、安全 token usage、发送请求、回执、审计事件、审计标签和结论。输出审查阻断会被归因为安全标签和中文结论，例如人格漂移会显示 `persona_drift`，LLM 调用失败会显示 `llm_error_kind`，生成参数预检阻断会显示 `llm_preflight_blocked` 与稳定 `llm_preflight_error:<reason>` 标签并说明已在调用 provider 前阻断，LLM 配置未接真实模型会显示 `llm_readiness_status=local_only` 或 `blocked`，限速阻断会显示 `rate_limited` 并说明已在调用 LLM 前阻断以避免刷屏，安静时间阻断会显示 `quiet_hours` 并说明已在调用 LLM 前阻断以避免夜间刷屏；但不会展示原始用户消息、回复全文、完整 prompt、知识原文、`private_debug`、API key、token、cookie、目标 ID、真实文件路径、原始模型输出、原始 provider 错误或 OneBot provider message id。默认诊断 store 是进程内最近记录；配置 `WUWA_DIAGNOSTICS_ENABLED=true` 和 `WUWA_DIAGNOSTICS_DB_PATH` 后会写入 SQLite `runtime_diagnostics`，并用 `WUWA_DIAGNOSTICS_MAX_ITEMS` 控制保留条数。

当启用 SQLite 发送队列时，`/wuwa why` 的诊断构造可以通过队列内部 `find_request(request_id)` 从持久化的 `send_requests.request_json` 找回对应 `SendRequest`，即使当前进程重启或队列对象重开，也能正确判断 `send_request_created`。这只是内部排障恢复能力；用户侧和管理员摘要仍只显示发送请求是否创建、回执状态和安全结论，不展示目标 ID、正文、`dedupe_key`、数据库路径或 provider message id。

真实 NoneBot 入口也已支持管理员 `/wuwa pause` 和 `/wuwa resume`。这是进程内软暂停：`pause` 后普通聊天、自动发送预览和非排障能力会在 policy 前被阻断，不调用 LLM、不创建 `SendRequest`；`status`、`why`、`receipt`、`audit`、`recent`、`queue`、`context`、`llm`、`config`、`readiness`、`dialogue`、`roles`、`history clear` 和 `resume` 仍可用，避免事故排查时把自己锁在门外。该状态不写入 `.env`，重启后恢复默认配置；长期硬关闭仍使用 `WUWA_RUNTIME_ENABLED=false`。`/wuwa status` 会分开展示 `运行时硬开关：enabled|disabled` 和 `运行时软暂停：true|false`，`/wuwa readiness` 也会展示 `runtime_soft_paused=true|false`；两者都只显示安全 reason 与 `updated_by=set|missing`，不展示具体管理员 ID。

审计、发送回执和发送队列也已有独立持久化开关。默认使用进程内 store；配置 `WUWA_AUDIT_ENABLED=true`、`WUWA_AUDIT_DB_PATH` 后会写入 SQLite `audit_records`，配置 `WUWA_RECEIPTS_ENABLED=true`、`WUWA_RECEIPTS_DB_PATH` 后会写入 SQLite `delivery_receipts`，配置 `WUWA_SEND_QUEUE_ENABLED=true`、`WUWA_SEND_QUEUE_DB_PATH` 后会写入 SQLite `send_requests`。回执记录最终投递状态，发送队列记录待投递请求、去重键、重试次数、下次重试时间和失败封顶状态；`WUWA_SEND_QUEUE_MAX_ATTEMPTS`、`WUWA_SEND_QUEUE_RETRY_BASE_SECONDS` 和 `WUWA_SEND_QUEUE_RETRY_MAX_SECONDS` 控制退避重试。`SQLiteSendRequestQueue.claim_due()` 会把到期的 `queued` / `failed_retryable` 请求原子认领为内部 `processing` 租约状态，并写入 `lease_expires_at`；worker 崩溃或进程退出后，租约过期的请求可再次被认领，避免多 worker 重复投递或永久卡死。`drain_send_queue_once()` 已提供一次性队列 worker：优先使用 `claim_due()`，再调用注入的 transport，记录 transport 回执，并把队列项标记为 `sent`、`failed_retryable` 或 `failed_final`。后台 APScheduler worker 默认关闭；只有配置 `WUWA_SEND_QUEUE_WORKER_ENABLED=true`，且启用了可 drain 的 SQLite 发送队列时，NoneBot 入口才会按 `WUWA_SEND_QUEUE_WORKER_INTERVAL_SECONDS` 和 `WUWA_SEND_QUEUE_WORKER_BATCH_SIZE` 注册 `wuwa_send_queue_worker`。没有在线 bot 时，worker 会把本次投递记为可重试失败而不是崩溃或刷屏。`scripts/dev.ps1 queue-smoke` 会用临时 SQLite 队列和 fake transport 验证 worker、回执、审计计数和 `processing` 安全计数，不启动 NapCat，也不发送 QQ 消息。所有用户侧状态、smoke 和管理员摘要只显示 `enabled/disabled`、`store=memory|sqlite`、`db=set|missing`、队列状态数量、重试参数或 worker 计数，不展示数据库真实路径、目标 ID、消息正文、`dedupe_key` 或 OneBot provider message id。

管理员排障命令已接入真实 NoneBot 入口：`/wuwa receipt <request_id|debug_id>` 查询某次发送回执，`/wuwa audit <request_id>` 查询某次审计事件，`/wuwa recent [数量]` 查看最近运行诊断、发送回执和审计事件的安全摘要，`/wuwa queue` 查看发送队列安全计数，`/wuwa context [测试文本]` 查看 LLM 上下文安全摘要，`/wuwa llm` 执行真实 LLM provider 在线连接诊断，`/wuwa setup llm` 查看真实 LLM 接入清单，`/wuwa config` 查看只读配置体检摘要，`/wuwa readiness` 查看统一就绪摘要，`/wuwa dialogue [测试文本]` 查看一轮对话验收摘要，`/wuwa roles` 查看权限角色规则矩阵，`/wuwa persona` 查看人格自检摘要，`/wuwa history clear` 清理当前会话/当前发送者/当前机器人实例的最近对话历史，`/wuwa pause` 和 `/wuwa resume` 控制当前进程的运行时软暂停。`/wuwa recent` 的运行诊断摘要会直接显示 `llm_readiness`、`ready_for_real_llm`、稳定 `llm_reasons` 和安全 `diagnostic_tags`，方便在不知道具体 `request_id` 时先判断真实模型是否接好、最近是否发生提示注入拦截或历史记录跳过。`diagnostic_tags` 只允许固定机器标签，例如 `prompt_injection`、`prompt_injection:instruction_override`、`history_record_skipped` 和 `history_skip:prompt_injection`，不会展示用户原话或密钥材料。它们只允许 `WUWA_ADMIN_USER_IDS` 中的管理员使用，并且仍走 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord` 链路；输出只展示白名单字段，不展示原始消息、完整 prompt、完整模型回复、最近对话原文、真实 `provider_message_id`、`private_debug`、`session_id`、目标 ID、数据库路径、密钥、token、Authorization/Bearer、`dedupe_key`、具体 user_id 或原始上游错误。`/wuwa receipt`、`/wuwa audit`、`/wuwa recent`、`/wuwa queue`、`/wuwa context`、`/wuwa llm`、`/wuwa setup llm`、`/wuwa config`、`/wuwa readiness`、`/wuwa dialogue`、`/wuwa roles`、`/wuwa persona`、`/wuwa history clear`、`/wuwa pause`、`/wuwa resume` 和 `/wuwa why` 都不会覆盖最近一次业务诊断记录。

人格和知识源首版通过 `FileCharacterContextProvider` 读取本地 Markdown/TXT/DOCX 文件。配置 `WUWA_PERSONA_FILES` 和 `WUWA_KNOWLEDGE_FILES` 后，文件内容会进入 `PersonaProfile`、`ToneProfile` 和 `RetrievalResult`，再被 `build_chat_prompt` 注入 LLM。DOCX 会先由独立 document loader 抽取正文，不让 LLM 直接读取或猜测未解析文件。配置 `WUWA_MEMORY_ENABLED=true` 和 `WUWA_MEMORY_DB_PATH` 后，本地 SQLite `memory_facts` 会作为 `MemoryRetrievalResult` 注入同一上下文，并可通过 `/wuwa memory add/list/delete` 管理当前用户/会话的手动记忆；记忆事实会带 `sensitivity=public|group|personal|credentialed` 和 `scope_key`，默认 `personal` 与当前 `session:<session_id>`。群聊里的 `/wuwa memory list` 只公开显示 `public` / `group` 记忆，不会输出 `personal` 或 `credentialed` 正文；没有可公开记忆时才提示用户到私聊查看。配置 `WUWA_HISTORY_ENABLED=true` 和 `WUWA_HISTORY_DB_PATH` 后，本地 SQLite `conversation_turns` 会按 platform/adapter/bot/session/sender 隔离读取最近对话，作为 `ConversationHistoryResult` 注入 prompt；`WUWA_HISTORY_MAX_TURNS` 和 `WUWA_HISTORY_MAX_CHARS` 只限制每次读取进 prompt 的轮数与字符数，`WUWA_HISTORY_MAX_ITEMS` 则限制同一作用域在 SQLite 中最多保留多少条历史，默认 1000，追加新轮次后自动清理更旧记录，避免长期运行后历史表无限增长。NoneBot 文本聊天入口会在生成 `SendRequest` 后记录用户消息，并在 OneBot/NapCat transport 成功后记录助手回复。管理员可用 `/wuwa history clear` 清理当前作用域最近对话历史，用于移除污染上下文或注入残留；该命令不影响长期记忆，也不展示历史正文、会话 ID、用户 ID 或数据库路径。配置 `WUWA_EMOTION_ENABLED=true` 后，首版 `RuleBasedEmotionProvider` 会把低落、孤独、疲惫、挫败和求助类文本转成 `EmotionSignal`，只作为语气和回复顺序的辅助信号，不写长期数据库，也不能触发主动发送。该 provider 只负责上下文，不发送消息、不决定权限、不绕过审计；后续更强的情绪识别、向量知识库和插件知识源都应接同一个 `ContextBundle` 边界。

但插件效果不能让大模型直接编。例如链接解析、媒体卡片、游戏/wiki 卡片、订阅推送、音乐平台解析等，必须走确定性流程：解析链接或命令，抓取来源数据，归一化为结构化模型，编译卡片，渲染图片或文本 fallback，然后发送。大模型最多生成安全的小标题或人格化短说明，不能替代解析器、渲染器和来源事实。

已参考的本地 parser 插件路径：

```text
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser
```

该插件的可复用思想是：`BaseParser` 自动注册、`@handle` 关键词/正则匹配、`ParseResult` 归一化、订阅去重、卡片渲染、发送计划和 fallback。新项目会吸收这些分层，但最终发送会收口到统一 sender/receipt/audit。

## NoneBot 与 NapCat 边界

项目通过 `pyproject.toml` 配置 NoneBot：

- 本地插件目录：`plugins`
- 内置插件：`echo`
- 适配器：OneBot V11、Console、Mail
- 支撑插件：status、apscheduler、localstore、alconna、filehost、orm、htmlkit

NapCat 按 OneBot V11 实现接入时，建议使用数组消息段格式。Incoming 事件中的 `message`、`raw_message`、`user_id`、`group_id`、`message_type` 等字段先归一化到 `IncomingMessage`；Outgoing 的文字、图片、合并转发等由 `SendRequest.content` 转换为 OneBot/NapCat 消息段。当前 `send_onebot_v11` 已支持把 `RenderedOutput.content_type=text` 转成 `text` 段，把 `image` 转成 `image` 段，把 `card` 中的 `onebot_json/json/data` 转成 `json` 段，把 `mixed.parts` 按顺序转成 text/image/json 组合段。`content_type=forward` 只有在 `SendRequest.allow_forward=true` 时才会尝试 OneBot/NapCat 扩展 API：群聊走 `send_group_forward_msg(group_id, messages)`，私聊走 `send_private_forward_msg(user_id, messages)`；如果 bot 没有这些方法，会退到 `call_api("send_group_forward_msg"...)` 或 `call_api("send_private_forward_msg"...)`；如果 `allow_forward=false`、缺少 forward 节点或扩展 API 不可用，会降级为 `text_fallback`，避免能力层直连发送。私聊/群聊普通消息分别调用 `send_private_msg` / `send_group_msg`。发送 API 的 `message_id` 或 `data.message_id`、异常、`status=failed` 和非零 `retcode` 必须映射到 `DeliveryReceipt`；真实 transport 回执可写入 `delivery_receipts`。非零 retcode 会先归一化成可重试失败或最终失败，公开消息只展示安全的 retcode/status/debug_id，不展示上游原文、目标 ID、正文或密钥；transport 审计只记录状态和内部标记，不公开 provider message id。后续接图片上传、真实 NapCat 合并转发授权投递验证和更完整 NapCat retcode 表时也必须落到同一回执模型，不能只看能力执行是否成功。

## 研究索引

研究证据、插件分析矩阵、架构报告和实现建议见 [research/README.md](research/README.md)。

## 近期新增能力

- **最小可执行程序**：`scripts/dev.ps1 console`（交互）与 `-Message`（单轮），走同一套运行时流水线，支持 CLI 参数临时接入任意 OpenAI 兼容模型。
- **角色昵称命令**：配置 `WUWA_RUNTIME_PERSONA_NICKNAME=岸宝` 后支持 `/岸宝帮助`、`/岸宝状态`、`/岸宝为什么` 等别名（`runtime/aliases.py`，动词映射可扩展）。
- **环境信息注入**：对话上下文自动带本地时间/日期/节气/节日；配置 `WUWA_WEATHER_ENABLED=true` 与经纬度后，天气经 Open-Meteo（免费、无 key）按 TTL 缓存注入，离线时安全降级为"未启用"（`character/temporal.py`）。
- **动作括号**：prompt 允许用中文括号表达动作/神态，例如（轻轻点头）；`WUWA_PERSONA_ACTION_BRACKETS=false` 可关闭。
- **时梗层**：`WUWA_TREND_FILES` 指向的 Markdown 备注作为"近期梗/热词/时事"注入，按 `WUWA_TREND_MAX_AGE_DAYS` 自动过滤过期条目，人设文件不用为追热点而改。
- **URL 去跟踪参数**：`sources/url_cleaner.py` 清洗 utm_*/spm/gclid/分享参数等，用于未来媒体流水线的去重键/缓存键/对外链接。
- **凭据存储**：`sources/credentials.py` 提供 `CredentialStore` 接口（文件 `data/credentials.json` 或 `WUWA_CREDENTIAL_*` 环境变量），cookie/api_key 以引用进入抓取链路，原始值不入日志与 prompt。
- **控制台多轮历史**：REPL 默认使用进程内多轮历史（`InMemoryConversationHistoryStore`），配置 SQLite 历史时自动切换持久存储。

## Git 本地工作流（不用 harness 也能更新回滚）

见 [GIT.md](GIT.md)。常用操作：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 save "feat: 说明"
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 history 20
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 tag v0.1-working
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 rollback 2
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 update
```

`.env`、`data/`、`.venv/` 与下载的研究源码都在 `.gitignore` 中，密钥和运行数据不会被提交。

当前 M0 已完成一个很窄的统一运行时插件骨架、SQLite 记忆闭环、最近对话历史闭环、当前作用域历史清理入口、每作用域历史存储保留上限、调用 LLM 前的内存/可选 SQLite 窗口限速、全局配额、目标最小间隔、安静时间策略、人格/知识上下文读取失败安全兜底、可选 SQLite 运行诊断、可选 SQLite 审计/回执/发送队列持久化、发送请求去重、持久请求查找、退避重试、失败封顶、SQLite 队列租约 claim、一次性队列 worker、默认关闭的 APScheduler 队列 worker 注册、本地 `doctor` 环境诊断、本地 `llm-setup` 接入清单、本地 `readiness-smoke` 统一就绪摘要、本地 `dialogue-smoke` 对话验收摘要、本地 `persona-smoke` 人格自检、本地 `queue-smoke` worker 诊断、本地 `startup-smoke` 启动干跑、本地 `transport-smoke` 出站边界诊断、只读 `online-transport-smoke` 在线 bot 可见性诊断、OneBot/NapCat text/image/json/mixed/forward transport 边界、OneBot `status/retcode/data.message_id` 回执归一化、本地 NoneBot 插件加载 smoke、`/wuwa why` 最近诊断，以及管理员 `/wuwa receipt`、`/wuwa audit`、`/wuwa recent`、`/wuwa queue`、`/wuwa context`、`/wuwa llm`、`/wuwa setup llm`、`/wuwa config`、`/wuwa readiness`、`/wuwa dialogue`、`/wuwa roles`、`/wuwa persona`、`/wuwa history clear`、`/wuwa pause`、`/wuwa resume` 安全排障和运行时控制入口。下一步建议补一个低风险媒体 source adapter、公共游戏/wiki 能力、排障可视化面板、摘要/私聊回退、图片上传/缓存策略和真实 NapCat 授权投递验证。
