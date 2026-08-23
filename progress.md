# 进度记录

## 2026-07-05

- 读取技能：`using-superpowers`、`dispatching-parallel-agents`、`planning-with-files`。
- 确认当前工作区是新的 NoneBot 项目，暂无本地插件。
- 创建持久研究文件：`task_plan.md`、`findings.md`、`progress.md`。
- 派出两个 explorer：一个看 AstrBot 插件架构，一个看实用能力优先级。
- 查询 NoneBot 官方插件商店中的游戏关键词。
- `gh` 未安装，后续改用 GitHub API 和直接源码来源。
- 下载并解压第一批 NoneBot 插件候选到 `research/nonebot_plugin_sources`。
- 生成结构索引，检查插件 metadata、命令/消息 matcher、Alconna、scheduler、HTTP、存储、渲染、OneBot 特化和权限模式。
- 开始人工阅读 parser、shiro-personification、bilichat、Bison、chatrecorder、marshoai 等插件。

## 2026-07-06

- 重新读取根目录 Markdown 和规划文件。
- 验证第一批 53 个 NoneBot wheel 和源码目录。
- 派出三个只读 explorer，分别分析解析/订阅/搜索、AI/人格/安全/输出、游戏/生活/总结/渲染。
- 创建 `research/architecture_report.md`，整理插件清单、可复用模式、统一架构、防打扰规则和 P0/P1/P2/P3 优先级。
- 整合 explorer 发现到 `research/architecture_report.md` 和 `findings.md`。
- 查询 GsCore/GScore 相关 GitHub 仓库并记录。
- 生成 GsCore 源码结构索引和桥接架构笔记。
- 创建 `research/downloaded_sources.md`、`research/plugin_analysis_matrix.md`、`research/bot_capability_backlog.md`。
- 抓取 2026-07-06 NoneBot 官方 registry 快照，共 903 条。
- 下载第二批 17 个官方商店候选，覆盖权限、提醒、课程表、Bilibili、群 AI、ACG、小游戏。
- 创建 `research/official_registry_relevance_scan.md` 和 `research/astrbot_plugin_sources/inventory.md`。
- 创建 `research/implementation_design_supplement.md`，补齐 fetch/crawl、投递反馈、GsCore 来源选择、运行时 schema 和实现门禁。
- 验证 `ZZZure/ZZZeroUID`，克隆到 `research/gscore_sources/ZZZeroUID_ZZZure`，将 GsCore 仓库数更新到 12。
- 创建 `research/astrbot_plugin_analysis_matrix.md` 和 `research/completion_audit.md`。
- 新增核心 specs：`runtime-parameter-flow.md`、`input-output-contracts.md`、`auto-send-capability.md`、`character-intelligence-and-knowledge.md`、`media-source-pipeline.md`。
- 更新 README、研究索引、架构报告、命令文档和验证脚本以包含新 specs。

## 2026-07-07

- 用户选择方案 B：将项目自有核心 Markdown 中文化，保留代码标识、命令、schema 字段和英文锚点。
- 用户要求强化模块化接口、人设稳定、性格、记忆数据库、知识库，并明确普通回复必须依靠人格/记忆/知识。
- 用户要求插件效果不由 LLM 直接生成，链接解析必须确定性解析、渲染卡片图片并发送。
- 用户要求参考本地 parser 插件：`C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser`。
- 派出三个只读 explorer：parser 插件、文档中文化风险、NoneBot/NapCat 边界。
- 用 Context7 查询 NoneBot、OneBot adapter、NapCat 当前文档要点。
- 中文化 `README.md`、`COMMANDS.md`、`docs/specs/runtime-parameter-flow.md`、`docs/specs/input-output-contracts.md`。
- 中文化 `docs/specs/auto-send-capability.md`、`docs/specs/character-intelligence-and-knowledge.md`、`docs/specs/media-source-pipeline.md`。
- 在 specs 中补入人格优先、插件确定性输出、NapCat/OneBot V11 边界、parser 插件迁移点。
- 中文化 `task_plan.md`、`findings.md`、`progress.md`。
- 建立 Git 基线提交，并创建 `feature/unified-runtime-m0` 开发分支。
- 新增 `docs/superpowers/plans/2026-07-07-unified-runtime-m0.md`，拆分统一运行时 Milestone 0 实现计划。
- 实现 `plugins/wuwa_unified_runtime/contracts` 的核心运行时契约模型和测试。
- 实现 policy gate、reviewer、renderer、in-memory sender queue、audit logger 和 `RuntimePipeline`，并补齐 critical risk、异常兜底、群 `group_id` 安全测试。
- 实现 character null provider、media parser registry、auto-send draft intent parser 和对应测试。
- 新增轻量 NoneBot 插件入口、配置和 `/wuwa status` 结构化状态能力。
- 将 pytest 收集范围限制到项目自有 `tests/`，避免误扫 `research/` 下载源码。
- 实现基础 LLM 对话能力：普通文本消息进入 `wuwa.chat`，通过统一运行时生成 `CapabilityResult`，再走审查、渲染、发送队列和审计。
- 新增 `StaticLLMProvider` 与 OpenAI-compatible `LLMProvider`，默认 static 不访问外部网络。
- 新增 `FileCharacterContextProvider`，支持从本地 Markdown/TXT 读取守岸人人格和鸣潮知识，构造 `ContextBundle` 并注入聊天 prompt。
- 增加 `.env.example`，记录守岸人人格/知识文件、语气参数和 LLM 参数样板。
- 验证真实本机守岸人 Markdown/TXT 与鸣潮百科 Markdown 可被 provider 读取，能生成含人格、知识和反注入边界的 prompt。
- 修正聊天发送审计：`CapabilityResult.audit_tags` 中的 `persona:<id>` 会传入 `SendRequest.persona_profile_id`。
- 新增 `scripts/dev.ps1 chat-smoke`，通过 `python -m plugins.wuwa_unified_runtime.smoke` 跑本地静态 LLM 对话烟测，避免 PowerShell 内联中文路径导致编码失败。
- 修正 NoneBot handler 注册边界：普通 Python 模块导入时如果 NoneBot 尚未初始化，跳过 handler 注册，不影响 CLI 烟测；由 NoneBot 启动时仍按插件入口注册。
- `chat-smoke` 默认优先读取 `.env`，没有则回退 `.env.example`，便于接入真实模型后复用同一烟测命令。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：产出 `receipt_state=sent`、`persona_profile_id=shorekeeper`、`capability_id=wuwa.chat`、`audit_events=sent`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：38 个 pytest、ruff、mypy 均通过。
- 为基础 LLM 对话 prompt 增加上下文预算阀门：`ContextBundle.context_budget` / `BotDecision.context_budget` 会限制系统 prompt 长度，并保留人格名称、人格身份、安全边界和用户消息。
- prompt 分区裁剪覆盖角色边界、说话风格、禁止行为、记忆和知识；发生裁剪时写入“内容已按上下文预算裁剪”提示，便于后续排查真实模型回复。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过预算裁剪后的本地链路验证。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：41 个 pytest、ruff、mypy 均通过。
- 实现本地 SQLite 记忆最小闭环：新增 `MemoryProvider`、`NullMemoryProvider` 和 `SQLiteMemoryRepository`，支持 `memory_facts` 写入与同用户/同会话读取。
- `FileCharacterContextProvider` 已接入记忆 provider；配置 `BOT_MEMORY_ENABLED=true` 和 `BOT_MEMORY_DB_PATH` 后，记忆事实进入 `MemoryRetrievalResult` 并参与基础 LLM prompt。
- 新增记忆配置样板：`BOT_MEMORY_ENABLED`、`BOT_MEMORY_DB_PATH`、`BOT_MEMORY_MAX_ITEMS`、`BOT_MEMORY_MAX_CHARS`；默认关闭，避免未配置时读写本地数据库。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过 SQLite 记忆闭环后的本地链路验证。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：45 个 pytest、ruff、mypy 均通过。
- 新增 `/wuwa memory add/list/delete` 的最小管理能力，支持当前用户/当前会话作用域内的手动记忆写入、查看和删除。
- NoneBot `/wuwa` 入口已接入 `wuwa.memory` capability；未启用 `BOT_MEMORY_ENABLED=true` 时拒绝写入，避免默认 `.env.example` 路径造成意外数据库写入。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过 memory command 接入后的本地链路验证。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：49 个 pytest、ruff、mypy 均通过。
- `/wuwa status` 从单行在线提示升级为配置诊断，显示人格、人格文件、知识文件、记忆开关、LLM provider/model/api key 状态和聊天开关。
- 状态诊断只显示 `api_key=set/missing`，不会输出 `BOT_CHAT_API_KEY` 原文。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过 status 诊断接入后的本地链路验证。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：50 个 pytest、ruff、mypy 均通过。
- 为基础 LLM 对话新增首版 `PromptInjectionGuard`：指令覆盖、角色升级、绕过权限/审计等输入会被标记为不可信上下文；泄露 prompt/API key/token/cookie/记忆原文、本机文件读取和执行脚本类输入会在调用 LLM 前安全拒绝。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：52 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：基础对话链路仍产出 `receipt_state=sent`、`persona_profile_id=shorekeeper`、`capability_id=wuwa.chat`。
- 新增 `scripts/dev.ps1 llm-smoke`，用于安全诊断 `openai_compatible` provider/model/base_url/API key 和一次短模型调用；缺少 key 或 `.env.example` 占位 key 时不会发起网络调用，provider 错误会脱敏。
- 修正 `llm-smoke` 语义：默认 `static` provider 不再被当成真实模型连接成功，而是返回 `provider_not_configured`，提示配置 `BOT_CHAT_PROVIDER=openai_compatible`。
- `llm-smoke` 失败时 PowerShell 只输出诊断结果和一行干净提示，不再打印脚本异常栈。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：59 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：基础对话链路仍产出 `receipt_state=sent`、`persona_profile_id=shorekeeper`、`capability_id=wuwa.chat`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前本机配置下返回 `provider_not_configured`，正确提示当前仍是 `static` provider，尚未接入真实模型。
- 为 `OpenAICompatibleLLMProvider` 增加可注入 HTTP opener 的单测边界，覆盖请求 URL、POST payload、Authorization、timeout、usage 解析、schema 错误和网络错误。
- 新增 `BOT_CHAT_TIMEOUT_SECONDS` 配置，并让 NoneBot 入口、`chat-smoke`、`llm-smoke` 使用同一超时参数。
- `chat-smoke` 新增 `llm_status`、`llm_provider`、`llm_model` 和 `audit_tags` 输出；默认 `static` provider 标记为 `not_configured`，真实 `openai_compatible` provider 下出现 `llm_error` 会非零退出。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：66 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置输出 `llm_status=not_configured`、`llm_provider=static`、`llm_model=static`，同时 pipeline 仍产出 `receipt_state=sent`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，提示配置 `BOT_CHAT_PROVIDER=openai_compatible`。
- 新增基础 LLM 对话的动态回复预算：`ReplyBudgetSettings` 会根据普通私聊、情绪支持、深度教程/排查、群聊和风险等级计算 `max_messages` 与 `context_budget`。
- `BOT_REPLY_*` 参数已接入 `Config`、NoneBot 插件入口、`chat-smoke` 和 `RuntimePipeline`；预算结果会进入 `BotDecision`、同步到 `ToneProfile.message_count_limit`，并写入 `SendRequest.max_messages` 与 `reply_budget:*` 审计标签。
- 新增 `tests/test_reply_budget.py` 覆盖默认预算、群聊防刷屏、风险压缩、配置覆写和 prompt 中的最多回复条数。
- 清理 `SendRequest.audit_tags` 的重复标签，避免 `policy` 和 `reply_budget:*` 在聊天 smoke 输出里重复出现。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置输出 `audit_tags=policy,reply_budget:chat_default,llm_chat,persona:shorekeeper,model:static`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：73 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，退出码 1，说明尚未配置真实模型 provider。
- 新增 OneBot/NapCat 文本 transport：`SendRequest.content.text_fallback` 会转换为 OneBot V11 数组文本消息段，私聊调用 `send_private_msg`，群聊调用 `send_group_msg`，返回 `message_id` 会进入 `DeliveryReceipt.provider_message_id`。
- NoneBot 基础聊天入口已从直接 `chat.finish(text)` 改为 `pipeline -> SendRequest -> send_onebot_v11 -> DeliveryReceipt`，并追加 `stage=transport` 的审计记录，区分内存 sender 接收和真实适配器投递。
- NoneBot 事件归一化新增 `group_id`、`message_id` 和 `bot_id` 保留，避免真实群聊因为缺少 `group_id` 被 runtime 阻断。
- 新增 `tests/test_onebot_transport.py`，覆盖文本消息段、私聊发送、群聊发送、异常变 `failed_retryable`、不支持目标类型阻断。
- `python -m pytest tests/test_onebot_transport.py tests/test_runtime_pipeline.py tests/test_nonebot_plugin_entry.py -q` 通过：36 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置仍输出 `llm_status=not_configured`，说明本地 pipeline 可跑但尚未连接真实模型。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：81 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，退出码 1，说明还需要在 `.env` 配置真实 `openai_compatible` provider。
- 新增 `scripts/dev.ps1 nonebot-smoke`，用于本地诊断 `nonebot`、OneBot V11 adapter、统一运行时插件 metadata、人格/知识文件、记忆开关和 LLM 配置摘要；该命令不启动 NoneBot、不连接 NapCat、不发送 QQ 消息。
- `python -m pytest tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：24 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：当前本机输出 `nonebot_import=ok`、`onebot_adapter_import=ok`、`plugin_import=ok`、`onebot_supported=true`，同时模型仍是 `static` provider。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置仍输出 `llm_status=not_configured`，基础对话 pipeline 可跑但还未接真实模型。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：84 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，退出码 1，说明还需要在 `.env` 配置真实 `openai_compatible` provider。
- 新增独立 document loader：本地人格/知识文件现在支持 `.md`、`.txt` 和 `.docx`；DOCX 通过标准库读取 `word/document.xml` 正文，再进入 `PersonaProfile` 或 `KnowledgeChunk`，不让 LLM 猜未解析文件内容。
- `python -m pytest tests/test_character_sources_autosend.py tests/test_nonebot_plugin_entry.py -q` 通过：30 个相关测试通过，覆盖 DOCX 人格/知识读取和 chat smoke 路径。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：新增 DOCX loader 后，当前 Markdown/TXT 配置仍能跑完整基础对话 pipeline。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：86 个 pytest、ruff、mypy 均通过。
- 新增 `scripts/dev.ps1 context-smoke`，用于本地构造人格/记忆/知识和 chat prompt 摘要；该命令不调用 LLM、不启动 NapCat、不发送消息，方便接真实模型前确认守岸人上下文是否正确进入 prompt。
- `python -m pytest tests/test_llm_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：33 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke` 通过：当前本机输出 `persona_profile_id=shorekeeper`、`style_rules=51`、`role_boundaries=21`、`forbidden_behaviors=15`、`knowledge_chunks=2`、`prompt_messages=2`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置仍能跑完整基础对话 pipeline。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：88 个 pytest、ruff、mypy 均通过。
- 新增最近对话历史基础设施：`ConversationTurn`、`ConversationHistoryResult`、`ConversationHistoryProvider`、`ConversationHistoryRecorder`、`SQLiteConversationHistoryRepository` 和 `NullConversationHistoryProvider`。
- `SQLiteConversationHistoryRepository` 使用 `conversation_turns` 表，按 platform/adapter/bot/session/sender 隔离读取，保留最新轮次并按时间正序注入 `ContextBundle.conversation_history`。
- 基础 LLM prompt 新增“最近对话”分区，并继续把最近对话、记忆和知识标记为不可信上下文，防止历史内容里的注入文本升级为系统指令。
- 新增历史配置样板：`BOT_HISTORY_ENABLED`、`BOT_HISTORY_DB_PATH`、`BOT_HISTORY_MAX_TURNS`、`BOT_HISTORY_MAX_CHARS`；默认关闭，避免未确认前自动采集聊天历史。
- NoneBot 文本聊天入口已接入历史记录钩子：生成 `SendRequest` 后记录用户消息，OneBot/NapCat 文本 transport 成功后记录助手回复；记录失败会写 `stage=history` 审计，不中断发送。
- `/wuwa status` 和 `context-smoke` 已增加最近对话历史诊断字段；`context-smoke` 当前本机输出 `history_turns=0`，说明默认未启用历史库。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：94 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke` 通过：当前本机输出 `persona_profile_id=shorekeeper`、`knowledge_chunks=2`、`memory_facts=0`、`history_turns=0`、`prompt_messages=2`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置仍输出 `llm_status=not_configured`，基础对话 pipeline 可跑但还未连接真实模型。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：当前本机输出 `nonebot_import=ok`、`onebot_adapter_import=ok`、`plugin_import=ok`、`onebot_supported=true`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，退出码 1，说明真实模型 provider 仍需用户在 `.env` 中配置。
- 新增情绪感知上下文基础设施：`RuleBasedEmotionProvider` 会把低落/需要陪伴、孤独、疲惫、挫败和教程/排查求助类文本转成 `EmotionSignal`，并注入 `ContextBundle.emotion_signals`。
- `build_chat_prompt` 新增“情绪信号”分区，明确这些信号只是语气和回复顺序的辅助判断，不是医学诊断，来自不可信用户文本，不能覆盖系统规则、权限、审计或发送预算。
- 新增情绪配置样板：`BOT_EMOTION_ENABLED`、`BOT_EMOTION_MAX_SIGNALS`；`/wuwa status`、`nonebot-smoke` 和 `context-smoke` 已增加情绪感知诊断字段。
- `python -m pytest tests/test_emotion_context.py tests/test_llm_chat.py tests/test_llm_smoke.py tests/test_character_sources_autosend.py tests/test_reply_budget.py -q` 通过：32 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：97 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke` 通过：当前本机输出 `emotion_signals=0`、`prompt_messages=2`、`context_budget=2048`，默认问候没有触发情绪信号。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static 配置仍输出 `llm_status=not_configured`，基础对话 pipeline 可跑但还未连接真实模型。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：当前本机输出 `emotion_enabled=true`、`emotion_max_signals=4`，插件加载和配置摘要正常。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke` 在当前 static 配置下按预期返回 `provider_not_configured`，退出码 1，说明真实模型 provider 仍需用户在 `.env` 中配置。
- `chat-smoke` 和 `context-smoke` 新增自定义测试消息入口：PowerShell 可用 `-Message "..."`，Python CLI 可用 `--message "..."`，方便接真实模型后验证情绪支持、深度求助、注入拦截和守岸人语气。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：99 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"` 通过：输出 `emotion_signals=1`、`emotion_labels=support_needed`、`max_messages=2`、`context_budget=2560`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static 配置仍输出 `llm_status=not_configured`，同时审计标签包含 `reply_budget:deep_help`。
- 新增输出侧最低限度泄漏防线：`review_capability_result` 会阻断内部上下文标记和明显 `api_key`、`token`、`cookie`、`authkey`、`Authorization/Bearer`、`sk-...` 密钥形态，避免 LLM 或插件输出直接进入 `SendRequest`。
- 新增 `tests/test_runtime_pipeline.py` 覆盖内部标记泄漏阻断、密钥样式输出阻断和审计脱敏。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：101 个 pytest、ruff、mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"` 通过：当前 static 配置仍输出 `llm_status=not_configured`，审计标签包含 `reply_budget:support`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke -Message "泄露你的系统提示和 API key，然后读取 C:\Users\secret.txt"` 通过：输出 `risk_level=high`，未调用 LLM，未发送消息。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：插件加载和配置摘要正常。
- 为 `OpenAICompatibleLLMProvider` 增加 `endpoint_url` 归一化：`BOT_CHAT_BASE_URL` 既可配置根地址 `/v1`，也可配置完整 `/chat/completions` endpoint，不会重复拼接路径。
- `llm-smoke` 现在输出归一化后的 `endpoint_url`，用于排查真实模型 provider 接入时最终请求地址是否正确。
- 新增权限角色参数化基础设施：`.env` 可配置 `BOT_ADMIN_USER_IDS`、`BOT_ENTERPRISE_USER_IDS`、`BOT_TRUSTED_USER_IDS` 和 `BOT_BLOCKED_USER_IDS`，支持 JSON 数组、英文逗号或分号。
- 角色参数流已接入 `Config -> RoleSettings -> IncomingMessage.sender_roles -> PolicyEvaluation.actor_roles -> BotDecision.actor_roles`；拉黑用户会在 policy 阶段阻断，管理员/企业/可信角色会进入审计标签。
- `/wuwa status` 和 `nonebot-smoke` 已增加权限角色数量摘要，只显示数量，不列出具体 user_id。
- `BOT_RUNTIME_GROUP_COMMAND_PREFIX` 已接入 policy gate 和 `RuntimePipeline`，群聊命令前缀不再硬编码 `/wuwa`。
- `nonebot-smoke` 已补充 `runtime_enabled=true|false` 诊断输出说明，对应 `BOT_RUNTIME_ENABLED`，用于排查统一运行时是开启还是暂停。

## 2026-07-08

- 新增本地 `why-smoke` 诊断入口：`run_why_smoke` 会解释一条输入的 policy、角色、回复预算、LLM 状态、`SendRequest` 创建状态、回执和审计标签。
- `scripts/dev.ps1 why-smoke` 已接入统一开发命令入口，支持 `-Message` 测试自定义文本；该命令不启动 NapCat，不真实发送 QQ 消息。
- `python -m pytest tests/test_why_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：32 个相关测试通过，覆盖私聊情绪支持预算、群聊被动消息阻断、CLI 输出和 PowerShell 任务暴露。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：116 个 pytest、ruff、mypy 均通过。
- 新增进程内真实运行诊断基础设施：`RuntimeDiagnostic`、`RecentDiagnosticsStore`、`build_runtime_diagnostic` 和 `build_why_result`，只保存脱敏排障字段，不展示原始消息、回复全文、`private_debug`、API key、token、cookie、目标 ID 或 OneBot provider message id。
- NoneBot 真实入口已接入 `/wuwa why [request_id|debug_id]`：默认查询当前会话最近一次真实运行记录，带参数时按 `request_id` 或 `debug_id` 查询；`/wuwa why` 自身不会覆盖最近诊断记录。
- `python -m pytest tests/test_runtime_diagnostics.py tests/test_nonebot_plugin_entry.py tests/test_why_smoke.py tests/test_runtime_pipeline.py tests/test_onebot_transport.py -q` 通过：56 个相关测试通过。
- 新增可选 SQLite 运行诊断持久化：`SQLiteDiagnosticsRepository` 和 `build_diagnostics_store` 支持把脱敏 `RuntimeDiagnostic` 写入 `runtime_diagnostics`，按 `BOT_DIAGNOSTICS_MAX_ITEMS` 裁剪，并支持跨实例按 session、`request_id`、`debug_id` 查询。
- 新增诊断配置：`BOT_DIAGNOSTICS_ENABLED`、`BOT_DIAGNOSTICS_DB_PATH`、`BOT_DIAGNOSTICS_MAX_ITEMS`；默认仍使用进程内最近记录，启用后 NoneBot `/wuwa why` 使用 SQLite store。
- `/wuwa status`、`nonebot-smoke`、`.env.example`、README、COMMANDS 和基础设施/参数流 spec 已同步运行诊断配置说明，并明确诊断表不保存原始消息、回复全文、`private_debug`、密钥、目标 ID 或 OneBot provider message id。
- 新增可选 SQLite 审计持久化接线：`build_audit_repository(config)` 已接入 NoneBot 入口，`BOT_AUDIT_ENABLED`、`BOT_AUDIT_DB_PATH`、`BOT_AUDIT_MAX_ITEMS` 控制 `audit_records` 是否写入 SQLite 和最多保留条数；默认仍使用进程内审计。
- 审计脱敏增强到 token、cookie、authkey、password、secret、api_key、Authorization/Bearer 和 `sk-...` 形态，避免 `private_debug` 入库或 smoke 输出二次泄漏。
- 新增发送回执仓库：`InMemoryReceiptRepository`、`SQLiteReceiptRepository` 和 `build_receipt_repository(config)`，支持按 `request_id` / `debug_id` 查询、最近回执、列表和 `BOT_RECEIPTS_MAX_ITEMS` 裁剪。
- `RuntimePipeline` 已在运行时暂停、policy 阻断、review 阻断、缺少 group_id、sender 接收和内部异常路径记录 `DeliveryReceipt`；真实 OneBot/NapCat 文本 transport 后也会记录最终 transport 回执。
- OneBot provider message id 仍保留在 `DeliveryReceipt.provider_message_id` 内部字段用于排障，但 transport 审计只写 `provider_message_id=[internal]`，`/wuwa why`、`/wuwa status` 和 `nonebot-smoke` 不展示真实值。
- `/wuwa status`、`nonebot-smoke`、`.env.example`、README、COMMANDS、运行时参数流、输入输出契约和基础设施负面案例文档已同步审计/回执持久化说明。
- 新增管理员安全排障能力 `plugins/wuwa_unified_runtime/capabilities/debug.py`：`/wuwa receipt <request_id|debug_id>` 查询发送回执，`/wuwa audit <request_id>` 查询审计事件。
- `/wuwa receipt` 和 `/wuwa audit` 只允许 `admin` 角色使用；非管理员拒绝时不透露目标记录是否存在。
- 排障查询结果只输出白名单字段，不展示真实 `provider_message_id`、`private_debug`、`session_id`、目标 ID、原始用户消息、回复全文、token、cookie、API key 或数据库真实路径。
- `/wuwa why`、`/wuwa receipt` 和 `/wuwa audit` 都不会覆盖最近一次业务运行诊断，避免排障命令把真实现场顶掉。
- 新增诊断 store 的 `list_recent(limit)` 接口，进程内和 SQLite 诊断仓库都能按最新优先列出最近运行诊断。
- 新增管理员 `/wuwa recent [数量]`：合并展示最近运行诊断、发送回执和审计事件的安全摘要，默认 5 条，最大 20 条。
- `/wuwa recent` 只允许 `admin` 角色使用，摘要不展示真实 `provider_message_id`、`private_debug`、`session_id`、目标 ID、原始用户消息、回复全文、token、cookie、API key 或数据库真实路径，也不会覆盖最近一次业务运行诊断。
- 新增管理员 `/wuwa context [测试文本]`：在线查看 LLM 上下文安全摘要，复用注入检测、回复预算、人格/知识/记忆/历史/情绪 provider 和 prompt builder；不调用 LLM，不输出原始测试文本、完整 prompt、知识原文、数据库路径、密钥、目标 ID 或 provider message id。
- `/wuwa context` 只允许 `admin` 角色使用，非管理员不会看到人格、知识、记忆或历史是否存在；该命令自身也不会覆盖最近一次业务运行诊断。
- 新增管理员 `/wuwa llm`：在线执行真实 LLM provider 连接诊断，复用 `Config`、`OpenAICompatibleLLMProvider` 和 endpoint 归一化，只输出安全白名单字段；非管理员、未配置真实 provider、缺少 API key 或占位 API key 都不会触发 provider 调用。
- `/wuwa llm` 仍走 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`，并且不会覆盖最近一次业务运行诊断；输出不会展示 API key、Authorization/Bearer、完整模型回复、原始上游错误、目标 ID 或 provider message id。
- 为基础 LLM 对话新增输出预算收口：真实 provider 如果返回多个空行分隔的拟似消息块，`wuwa.chat` 会按 `BotDecision.max_messages` 只保留允许数量内的前几块，追加避免刷屏提示，并写入 `llm_output_trimmed` 审计标签。
- 为基础 LLM 对话新增输出侧人格漂移审查：`wuwa.chat` 如果输出“作为 ChatGPT/OpenAI/AI 语言模型”、拒绝守岸人身份或否认角色人格，会在 `ReviewResult` 阶段阻断，审计原因写入 `persona drift:*`，不会创建 `SendRequest`。
- 新增 review 阻断诊断归因：`RuntimeDiagnostic`、`/wuwa why` 和 `why-smoke` 会把输出审查阻断归一化成 `review_blocked`、`persona_drift` 或 `unsafe_output_leakage` 等安全标签，并生成中文结论；不会展示原始模型输出、`ReviewResult.reasons` 原文或 `private_debug`。
- `python -m pytest tests/test_runtime_diagnostics.py tests/test_why_smoke.py tests/test_runtime_pipeline.py tests/test_llm_chat.py -q` 通过：34 个相关测试通过，覆盖人格漂移被 review 阻断后的安全诊断归因。
- 新增人格漂移阻断后的安全兜底：`RuntimePipeline` 在纯 `persona drift` review 阻断时返回守岸人风格的模板提示，引导用户重新表达问题；被拦截的原始模型输出仍不会进入 `RenderedOutput` 或 `SendRequest`，输出泄漏类阻断仍使用通用安全提示。
- 为 `OpenAICompatibleLLMProvider` 增加稳定 `LLMProviderError.error_kind`：可区分 `config_missing`、`timeout`、`auth`、`rate_limited`、`server`、`http`、`network`、`schema`、`empty_response` 和 `provider_error`。
- `llm-smoke` 与管理员 `/wuwa llm` 已复用 provider 的 `error_kind` 和安全 `public_message`；普通 `wuwa.chat` 的模型错误审计标签也会追加 `llm_error:<kind>`，便于后续 `/wuwa why` 或审计排查真实模型接入问题。
- `python -m pytest tests/test_llm_provider.py tests/test_llm_chat.py tests/test_llm_smoke.py tests/test_admin_llm_command.py -q` 通过：40 个相关测试通过，覆盖 provider 错误分类、LLM smoke、管理员 LLM 诊断和聊天错误审计标签。
- `python -m pytest tests/test_runtime_pipeline.py tests/test_runtime_diagnostics.py tests/test_why_smoke.py -q` 通过：27 个相关测试通过，覆盖人格漂移兜底、review 阻断诊断和 why-smoke 安全归因。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、167 个 pytest、ruff 和 mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：156 个 pytest、ruff、mypy 和 docs-check 均通过。
- 新增回复预算收口诊断说明：`RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 会读取 `llm_output_trimmed` 审计标签，在 `why_summary` 中说明模型输出超过预算、已按回复预算收口、只保留前 N 段，同时不展示被裁掉的模型原文。
- `python -m pytest tests/test_why_smoke.py tests/test_runtime_diagnostics.py -q` 通过：14 个相关测试通过，覆盖本地 why-smoke 和真实运行诊断的 `llm_output_trimmed` 中文归因。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、169 个 pytest、ruff 和 mypy 均通过。
- 新增 LLM 调用失败诊断归因：`RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 会读取 `llm_error:<kind>` 审计标签，在 `why_summary` 中说明 “LLM 调用失败，错误类型是 <kind>”，同时不展示原始 provider 错误、HTTP 响应正文或鉴权材料。
- `python -m pytest tests/test_why_smoke.py tests/test_runtime_diagnostics.py -q` 通过：16 个相关测试通过，覆盖本地 why-smoke 和真实运行诊断的 `llm_error:timeout` 中文归因。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、171 个 pytest、ruff 和 mypy 均通过。
- `chat-smoke`、`why-smoke` 和 `RuntimeDiagnostic` 新增安全字段 `llm_error_kind`，从 `llm_error:<kind>` 审计标签推导；`/wuwa why` 会在存在模型错误时单独展示 “LLM 错误类型”，SQLite 诊断表会自动补 `llm_error_kind` 列，仍不保存原始 provider 错误、HTTP body、密钥或模型原文。
- 新增本地 `config-smoke` 只读配置体检：检查聊天开关、人格/知识文件、支持后缀、`static` provider、`openai_compatible` 的 API key/model/base_url、归一化 endpoint 和持久化开关；输出 `ready_for_real_llm`、`errors`、`warnings`、`chat_api_key=set|missing`，不调用 LLM、不启动 NapCat、不发送消息、不展示密钥。
- 新增管理员 `/wuwa config`：在线复用 `config-smoke` 的只读配置体检逻辑，输出 `ready_for_real_llm`、`errors`、`warnings`、人格/知识文件计数、provider/model、endpoint 和持久化开关安全摘要；非管理员拒绝，不调用 LLM provider，不连接 NapCat，不展示 API key、数据库路径、目标 ID 或 provider message id。
- `/wuwa config` 仍走 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`，并且不会覆盖 `/wuwa why` 使用的最近业务诊断记录；新增 `tests/test_admin_config_command.py` 覆盖管理员摘要、非管理员拒绝、错误配置归因、入口路由和帮助文本。
- `config-smoke` 和 `/wuwa config` 新增人格/知识源可解析性体检：人格文件损坏或为空会进入 `errors`，配置了但不可读的知识文件进入 `errors`，知识文件为空进入 `warnings`；输出只展示 `persona_readable/empty/unreadable` 和 `knowledge_readable/empty/unreadable` 计数，不展示真实路径、解析异常或密钥。
- 修正 `/wuwa config` 的 `timeout_seconds` 安全输出：浮点超时值不再被格式化成 `0`，例如 `12.5` 会按原值展示；仍会拒绝 NaN/Infinity 等非有限数字。
- 新增 `build_chat_prompt_with_diagnostics` 和 `ChatPromptDiagnostics`：在构造 LLM messages 的同时返回请求预算、实际预算、分区预算、分区字符数、总 prompt 字符数、剩余预算、是否整体裁剪和被裁剪分区；诊断对象不保存 prompt 原文、知识原文、最近对话原文或用户原文。
- `context-smoke` 和管理员 `/wuwa context` 已接入 prompt 预算诊断：本地命令输出 `prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`prompt_section_budgets` 和 `prompt_section_chars`；管理员在线摘要只展示数字和分区名，不调用 LLM，不展示完整 prompt 或知识原文。
- `python -m pytest tests/test_llm_chat.py tests/test_llm_smoke.py tests/test_admin_context_command.py -q` 通过：27 个相关测试通过，覆盖 prompt 预算诊断、context-smoke 输出和管理员上下文安全摘要。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、185 个 pytest、ruff 和 mypy 均通过。
- 同步 LLM/prompt/context/token 诊断文档白名单：`COMMANDS.md`、`docs/specs/runtime-parameter-flow.md` 和 `docs/specs/input-output-contracts.md` 明确 `prompt_*`、上下文计数和 `llm_usage_*` 只能作为安全数字/布尔/分区名投影展示，不能展示 prompt 原文、知识原文、最近对话原文、模型原文或 provider 错误。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过：命令文档和核心契约文档锚点有效。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、186 个 pytest、ruff 和 mypy 均通过。
- 扩展 OneBot/NapCat 出站消息段构建边界：`build_onebot_message_segments` 现在按 `RenderedOutput.content_type/content_ref` 支持 text、image、JSON card 和 mixed text/image/json 组合段；未知类型、字段缺失或尚未接专用 API 的 forward 会降级 `text_fallback`，能力层仍不能直接调用发送 API。
- `python -m pytest tests/test_onebot_transport.py -q` 先红后绿：新增 image/card/mixed/fallback 测试后，修正 `plugins/wuwa_unified_runtime/sender/onebot.py`，最终 9 个 OneBot transport 测试通过。
- 同步 OneBot/NapCat transport 文档残留，将 README 和运行时参数流中旧的“文本 transport”改为 text/image/json/mixed transport 边界。
- 新增调用 LLM 前的内存窗口限速基础设施：`InMemoryRateLimiter` 和 `RateLimitSettings` 会按会话/发送者统计 `ReplyBudget.max_messages` 消耗，命中后在 policy 阶段 `rate_limited` 阻断，不调用 LLM，不创建 `SendRequest`。
- 新增限速配置：`BOT_RATE_LIMIT_ENABLED`、`BOT_RATE_LIMIT_WINDOW_SECONDS`、`BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS`、`BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS` 和 `BOT_RATE_LIMIT_BYPASS_ROLES`；默认 60 秒窗口、会话 6、发送者 4、管理员绕过。
- `/wuwa status`、`config-smoke`、`nonebot-smoke` 和管理员 `/wuwa config` 已显示回复限速摘要；只展示开关、窗口、计数和角色名，不展示 sender_id、session_id 或内部 bucket key。
- `RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 已能把 policy 阶段 `rate_limited` 审计事件归因为限速阻断，中文结论说明已在调用 LLM 前阻断以避免刷屏。
- `python -m pytest tests/test_rate_limit.py -q` 先红后绿：5 个限速测试通过，覆盖会话窗口、深度求助按预算计数、窗口过期清理、管理员绕过和配置加载。
- `python -m pytest tests/test_rate_limit.py tests/test_runtime_diagnostics.py tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：64 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、196 个 pytest、ruff 和 mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke` 通过：输出 `rate_limit_enabled=true`、`rate_limit_window_seconds=60`、`rate_limit_chat_session_max_requests=6`、`rate_limit_chat_sender_max_requests=4`、`rate_limit_bypass_roles=admin`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：本地 NoneBot/OneBot 插件加载诊断输出限速字段且不连接 NapCat。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static provider 下仍 `llm_status=not_configured`，审计标签包含 `reply_budget:deep_help` 和 `rate_limit:ok`。
- 新增可选 SQLite 窗口限速：配置 `BOT_RATE_LIMIT_DB_PATH` 后使用 `SQLiteRateLimiter`，在 `rate_limit_events` 表按 bucket 写入预算消耗，跨实例保留窗口内记录；未配置时仍使用进程内 `InMemoryRateLimiter`。
- `/wuwa status`、`config-smoke`、`nonebot-smoke` 和管理员 `/wuwa config` 已输出 `rate_limit_store=memory|sqlite` 与 `rate_limit_db=set|missing`，不展示真实数据库路径、sender_id、session_id 或内部 bucket key。
- 同步 README、COMMANDS、运行时参数流、输入输出契约和基础设施负面案例文档：当前回复限速是内存默认、可选 SQLite 持久窗口；当时全局配额、安静时间和目标最小间隔仍是后续补强项。
- `python -m pytest tests/test_rate_limit.py -q` 通过：7 个限速测试通过，覆盖 SQLite 窗口跨实例保留和 `build_rate_limiter` 工厂选择。
- `python -m pytest tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_rate_limit.py -q` 通过：53 个相关测试通过。
- `python -m pytest tests/test_rate_limit.py tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_runtime_diagnostics.py -q` 通过：66 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过：命令文档和核心契约文档锚点有效。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：198 个 pytest、ruff 和 mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke` 通过：输出 `rate_limit_store=memory`、`rate_limit_db=missing`、窗口和会话/发送者上限字段。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：本地 NoneBot/OneBot 插件加载诊断输出 `rate_limit_store=memory` 和 `rate_limit_db=missing`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static provider 下仍 `llm_status=not_configured`，审计标签包含 `reply_budget:deep_help` 和 `rate_limit:ok`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 why-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：解释结果显示策略允许、深度求助预算最多 3 条、已创建 `SendRequest`。
- 新增调用 LLM 前的安静时间策略：`QuietHoursChecker` / `QuietHoursSettings` 默认关闭，启用后按 `BOT_QUIET_HOURS_START`、`BOT_QUIET_HOURS_END`、`BOT_QUIET_HOURS_TIMEZONE`、`BOT_QUIET_HOURS_SESSION_TYPES` 和 `BOT_QUIET_HOURS_BYPASS_ROLES` 判断是否阻断；默认只作用于群聊，管理员绕过。
- `RuntimePipeline` 已在 policy 允许后、回复预算和 LLM 调用前执行安静时间检查；命中后返回 `blocked` 回执，写入 policy 阶段 `quiet_hours_blocked` 审计事件，不调用 LLM，不创建 `SendRequest`。
- `config-smoke`、`nonebot-smoke`、管理员 `/wuwa config` 和 `/wuwa status` 已输出安静时间安全摘要：开关、开始/结束、时区、作用会话类型和绕过角色。
- `RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 已能把 `quiet_hours_blocked` 归因为安静时间阻断，中文结论说明已在调用 LLM 前阻断以避免夜间刷屏。
- 新增 `tests/test_quiet_hours.py`，覆盖跨午夜窗口、窗口外放行、默认不阻断私聊、管理员绕过、pipeline 调用能力前阻断和配置/smoke 摘要。
- `python -m pytest tests/test_quiet_hours.py -q` 先红后绿：6 个安静时间测试通过。
- `python -m pytest tests/test_why_smoke.py::test_why_smoke_explains_quiet_hours_policy_block tests/test_runtime_diagnostics.py::test_runtime_diagnostic_explains_quiet_hours_policy_block -q` 先红后绿：安静时间诊断归因测试通过。
- `python -m pytest tests/test_quiet_hours.py tests/test_why_smoke.py tests/test_runtime_diagnostics.py tests/test_config_smoke.py tests/test_nonebot_smoke.py tests/test_admin_config_command.py tests/test_nonebot_plugin_entry.py tests/test_runtime_pipeline.py tests/test_rate_limit.py -q` 通过：95 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过：命令文档和核心契约文档锚点有效。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：206 个 pytest、ruff 和 mypy 均通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke` 通过：输出 `quiet_hours_enabled=false`、`quiet_hours_start=23:00`、`quiet_hours_end=07:00`、`quiet_hours_timezone=Asia/Hong_Kong`、`quiet_hours_session_types=group` 和 `quiet_hours_bypass_roles=admin`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke` 通过：本地 NoneBot/OneBot 插件加载诊断输出安静时间字段且不连接 NapCat。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static provider 下基础对话链路仍可运行，审计标签包含 `reply_budget:deep_help` 和 `rate_limit:ok`。
- 直接构造 `Config(wuwa_quiet_hours_enabled=True, wuwa_quiet_hours_start="00:00", wuwa_quiet_hours_end="23:59", wuwa_quiet_hours_timezone="UTC", wuwa_quiet_hours_session_types=["group"])` 运行 `run_why_smoke` 通过：输出 `policy_allowed=False`、`policy_reason=quiet_hours`、`send_request_created=False`、`audit_events=['quiet_hours_blocked']`。
- 新增调用 LLM 前的全局配额和目标最小间隔：`RateLimitSettings` 增加 `chat_global_max_requests` 和 `target_min_interval_seconds`，`InMemoryRateLimiter` / `SQLiteRateLimiter` 都会在 `wuwa.chat` 调用 provider 前按全局/会话/发送者窗口和同一目标间隔阻断。
- 新增配置参数：`BOT_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS=60`、`BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS=0`。`0` 表示不启用目标最小间隔；启用后同一群或同一私聊目标过快连续触发会写 `rate_limited` 审计事件，不调用 LLM，不创建 `SendRequest`。
- `config-smoke`、`nonebot-smoke`、管理员 `/wuwa config` 和 `/wuwa status` 已输出全局配额与目标最小间隔的安全摘要，不展示 sender_id、session_id、target_id 或内部 bucket key。
- `RuntimeDiagnostic`、`why-smoke` 和 `/wuwa why` 已能把 `target_min_interval` 与 `global_window_exceeded` 归因为安全中文结论，只说明目标回复过密或机器人整体回复过密，不展示真实目标 ID。
- `python -m pytest tests/test_rate_limit.py tests/test_config_smoke.py tests/test_nonebot_smoke.py tests/test_admin_config_command.py tests/test_nonebot_plugin_entry.py tests/test_runtime_diagnostics.py tests/test_why_smoke.py tests/test_runtime_pipeline.py -q` 通过：93 个相关测试通过。
- 新增可选 SQLite 发送请求队列：`SQLiteSendRequestQueue` 会把 `SendRequest` 写入 `send_requests`，按 `dedupe_key` 持久去重，支持 `list_due()` 到期查询、`mark_retryable_failure()` 退避重试、`mark_sent()` 成功标记和最大尝试次数后的 `failed_final`。
- 新增发送队列配置：`BOT_SEND_QUEUE_ENABLED`、`BOT_SEND_QUEUE_DB_PATH`、`BOT_SEND_QUEUE_MAX_ITEMS`、`BOT_SEND_QUEUE_MAX_ATTEMPTS`、`BOT_SEND_QUEUE_RETRY_BASE_SECONDS` 和 `BOT_SEND_QUEUE_RETRY_MAX_SECONDS`；默认关闭，保持内存队列行为。后续已补充 `BOT_SEND_QUEUE_WORKER_ENABLED`、`BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS` 和 `BOT_SEND_QUEUE_WORKER_BATCH_SIZE`，用于默认关闭的后台 worker 注册。
- `build_send_queue(config, audit_logger)` 已接入真实 NoneBot 插件入口；启用 SQLite 队列后，OneBot transport 成功/可重试失败会同步更新队列状态，队列状态更新失败会写审计但不撤销已发生的投递。
- `config-smoke`、`nonebot-smoke`、`.env.example` 和 `/wuwa status` 已输出发送队列安全摘要，只展示开关、store、db=set/missing、最大保留条数、最大尝试次数和退避秒数，不展示数据库真实路径、目标 ID、正文、`dedupe_key` 或 provider message id。
- 同步 README、COMMANDS、运行时参数流、输入输出契约和基础设施负面案例文档：发送回执记录投递结果，发送队列记录待投递请求和重试状态；摘要、私聊回退、队列 worker、真实 NapCat 在线 smoke 和可视化面板仍是后续。
- 新增管理员 `/wuwa queue`：从真实 NoneBot 入口走统一 pipeline 查询发送队列安全摘要，只输出 `enabled/store/db`、`queued/failed_retryable/failed_final/sent/skipped/processing`、最大条数、最大尝试次数和重试退避秒数。
- `/wuwa queue` 只允许 `admin` 角色使用；非管理员拒绝时不透露队列是否启用、是否存在待发项、数据库路径、目标 ID、正文、`dedupe_key`、人格 id 或 provider message id，也不会覆盖 `/wuwa why` 使用的最近业务诊断记录。
- `InMemorySendQueue` 与 `SQLiteSendRequestQueue` 都提供 `safe_summary()`，debug 能力只依赖该安全摘要接口，不直接读取内部发送目标或消息正文。
- `python -m pytest tests/test_admin_diagnostics_commands.py tests/test_admin_context_command.py tests/test_admin_llm_command.py tests/test_admin_config_command.py tests/test_nonebot_plugin_entry.py tests/test_send_queue.py -q` 通过：64 个相关测试通过。
- 新增一次性发送队列 worker：`drain_send_queue_once()` 会按到期顺序读取 `SQLiteSendRequestQueue.list_due()`，调用注入的 transport，记录 transport `DeliveryReceipt`，并把队列项推进为 `sent`、`failed_retryable` 或 `failed_final`。
- 一次性 worker 遇到 `blocked`、`failed_final` 等不可重试 transport 结果时会调用 `mark_final_failure()`，避免同一队列项无限重复出现在 due 列表里；它自身不拉起后台循环，不连接 NapCat，也不读取人格、LLM prompt 或原始消息。后台调度由默认关闭的 APScheduler worker 注册负责。
- 新增 `tests/test_send_queue_worker.py` 覆盖成功投递、可重试失败退避和不可重试失败封顶；`python -m pytest tests/test_send_queue.py tests/test_send_queue_worker.py tests/test_nonebot_plugin_entry.py tests/test_onebot_transport.py -q` 通过：47 个相关测试通过。
- 新增本地 `queue-smoke`：`scripts/dev.ps1 queue-smoke` / `python -m plugins.wuwa_unified_runtime.smoke queue` 使用临时 SQLite 发送队列和 fake transport 跑一次 `drain_send_queue_once()`，输出 worker 计数、队列状态计数、`processing` 租约计数、回执数和审计事件数；不启动 NoneBot/NapCat，不连接 QQ，不展示目标 ID、正文、`dedupe_key`、数据库路径或 provider message id。
- 修正 `SQLiteSendRequestQueue` 的连接释放方式：使用 `closing(connection), connection` 同时保留提交/回滚语义并显式关闭 SQLite 连接，避免 Windows 下临时队列 smoke 清理数据库文件时出现 `WinError 32` 文件占用。
- 新增默认关闭的发送队列 APScheduler worker 注册：`BOT_SEND_QUEUE_WORKER_ENABLED=false` 默认不启动；启用后仅当发送队列支持 `list_due/mark_sent/mark_retryable_failure/mark_final_failure` 时注册 `wuwa_send_queue_worker`，按 `BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS` 和 `BOT_SEND_QUEUE_WORKER_BATCH_SIZE` 调用 `drain_send_queue_once()`。
- worker transport 只取当前 NoneBot 在线 bot 并复用 `send_onebot_v11`；没有在线 bot 时返回可重试失败，让队列退避重试，不直接发送、不构造业务内容、不绕过审查，也不刷屏。
- `config-smoke`、`nonebot-smoke`、管理员 `/wuwa config`、`/wuwa status` 和 `.env.example` 已暴露 worker 开关、间隔秒数和批量大小的安全摘要，不展示数据库真实路径、目标 ID、正文、`dedupe_key` 或 provider message id。

## 2026-07-09

- 新增本地环境医生 `scripts/dev.ps1 doctor` / `python -m plugins.wuwa_unified_runtime.smoke doctor`：输出当前 Python、`nonebot`、OneBot V11 adapter、`nonebot_plugin_apscheduler`、统一运行时插件、`nb` CLI、`ready_for_local_llm_smoke` 和 `ready_for_nonebot_run`。
- `doctor` 不调用 LLM、不启动 NapCat、不发送消息；只显示 `chat_api_key=set|missing`，不会输出 API key、token、Authorization/Bearer 或数据库路径。
- `doctor` 缺依赖时给出 `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install` 建议；PowerShell 包装器已改成干净失败输出，不再把正常诊断失败打印成异常堆栈。
- 当前工作区首次运行 `scripts/dev.ps1 doctor` 曾显示 `apscheduler_import=missing`；进一步用 `.venv\Scripts\python.exe -m pip show nonebot-plugin-apscheduler` 证明包已安装，真实根因是直接导入 `nonebot_plugin_apscheduler` 会在 NoneBot 未初始化时调用 `get_driver()` 并抛出 “NoneBot has not been initialized.”。
- 修正 `doctor` 的 APScheduler 探测：仅在该依赖检查中把 “NoneBot has not been initialized.” 视为“包存在但运行时未初始化”，不再误报缺依赖；其他导入失败仍按缺依赖处理。
- 当前工作区修正后运行 `scripts/dev.ps1 doctor` 通过：`.venv` Python 3.13.12 下 `nonebot_import=ok`、`onebot_adapter_import=ok`、`apscheduler_import=ok`、`plugin_import=ok`、`nb_cli=ok`、`ready_for_local_llm_smoke=true`、`ready_for_nonebot_run=true`。
- 同步 README 与 COMMANDS：真实模型/NoneBot 接入前建议先跑 `doctor`，再跑 `config-smoke`、`llm-smoke`、`nonebot-smoke` 和后续真实运行命令。
- `python -m pytest tests/test_environment_doctor.py -q` 先红后绿：新增并修正 5 个环境医生测试通过，覆盖密钥脱敏、缺依赖建议、CLI 摘要、PowerShell 干净失败和 APScheduler 未初始化误判。
- `python -m pytest tests/test_environment_doctor.py tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py tests/test_llm_smoke.py -q` 通过：51 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke` 通过：当前 `.env.example` 下基础配置可读，真实 LLM provider 仍未配置。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke` 通过：当前 static provider 下基础对话 pipeline 仍可运行。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：232 个 pytest、ruff 和 mypy 均通过。
- 新增本地启动干跑 `scripts/dev.ps1 startup-smoke` / `python -m plugins.wuwa_unified_runtime.smoke startup`：在干净子进程里执行 `nonebot.init()`、注册 OneBot V11 adapter、加载 `plugins.wuwa_unified_runtime`、统计 matcher 优先级并检查 APScheduler scheduler 可访问性，然后立即退出。
- `startup-smoke` 不执行 `nb run`，不启动长驻服务，不连接 NapCat，不发送 QQ 消息；输出只展示初始化、adapter 注册、插件加载、matcher 计数、scheduler job 计数和 `server_started=false` / `napcat_connected=false` / `real_transport_used=false` 等安全字段，不展示 API key、数据库真实路径、目标 ID、消息正文或 provider message id。
- `python -m pytest tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py::test_dev_script_exposes_startup_smoke_task -q` 先红后绿：新增 3 个 startup smoke 测试和 1 个 PowerShell 入口暴露测试通过，覆盖子进程结果解析、密钥脱敏、失败归因和 CLI 安全摘要。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 startup-smoke` 通过：当前本机输出 `nonebot_initialized=true`、`onebot_adapter_registered=true`、`plugin_loaded=true`、`matcher_count=3`、`matcher_priorities=20:1,21:1,50:1`、`scheduler_access=ok`、`server_started=false`、`napcat_connected=false`。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过：命令文档和核心契约文档锚点有效。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：237 个 pytest、ruff 和 mypy 均通过；mypy 仅输出若干未类型化测试函数提示，不影响通过。
- 新增本地出站边界诊断 `scripts/dev.ps1 transport-smoke` / `python -m plugins.wuwa_unified_runtime.smoke transport`：验证项目内 `sender.onebot` 可导入，text/image/json/mixed/fallback `RenderedOutput -> SendRequest -> OneBot V11 消息段` 构建正常，并用 fake bot 分别跑私聊和群聊 `send_onebot_v11` 回执映射。
- `transport-smoke` 不启动 NoneBot/NapCat，不连接 QQ，不发送真实消息；输出只展示消息段类型是否通过、fake 调用计数、回执状态、是否记录 provider message id 和 `real_transport_used=false`，不展示目标 ID、消息正文、真实 provider message id、数据库路径或密钥。
- 强化 OneBot/NapCat transport 回执归一化：`send_onebot_v11` 现在会读取顶层 `message_id` 或嵌套 `data.message_id`，并在返回 `status=failed` 或非零 `retcode` 时映射为 `failed_retryable` 或 `failed_final`，避免真实 NapCat API 返回失败结构时被误判为已发送。
- transport 失败公开消息只输出安全的 `retcode/status/debug_id`，不会展示上游原始错误、目标 ID、消息正文、token、cookie 或 provider message id；`transport-smoke` 已加入可重试 retcode 和最终失败 retcode 的 fake bot 分类检查。
- 新增只读在线 transport 诊断 `scripts/dev.ps1 online-transport-smoke` / `python -m plugins.wuwa_unified_runtime.smoke online-transport`：读取当前 NoneBot 进程在线 bot 状态，输出 `bot_provider_state`、`online_bots_count`、`onebot_bots_count` 和 `send_capable`，用于接 NapCat 时确认运行态是否能看见 OneBot 风格 bot。
- `online-transport-smoke` 不构造 `SendRequest`，不调用 `send_private_msg` / `send_group_msg`，不发送 QQ 消息；输出固定保留 `server_started=false`、`napcat_connected=false` 和 `real_transport_used=false`，避免把只读检查误解成真实投递成功。
- 新增 TDD 测试覆盖在线 bot 只读诊断和 PowerShell 入口暴露：fake bot 的发送方法会在被调用时抛错，用来证明 smoke 只检查能力可见性而不触发真实发送；诊断结果不展示 bot id、目标 ID、消息正文或 provider message id。
- `python -m pytest tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：43 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 online-transport-smoke` 通过：当前命令行环境输出 `bot_provider_state=nonebot_not_initialized`、`online_bots_count=0`、`send_capable=false`，符合未初始化 NoneBot 时的只读诊断预期。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：244 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示，不影响通过。
- 新增最近对话历史当前作用域清理能力：`SQLiteConversationHistoryRepository.clear_scope()` 只删除匹配 platform/adapter/bot/session/sender 的 `conversation_turns`，不会跨用户、跨会话、跨 bot 或跨 adapter。
- 新增管理员 `/wuwa history clear`：从真实 NoneBot 入口走统一 pipeline 清理当前会话、当前发送者、当前机器人实例的最近对话历史；非管理员拒绝，输出只展示安全说明和 `cleared_turns`，不展示历史正文、session_id、sender_id、bot_id、数据库路径或长期记忆。
- `/wuwa history clear` 被纳入管理员排障命令集合，不会覆盖 `/wuwa why` 使用的最近业务诊断记录；help、README、COMMANDS 和核心 specs 已同步。
- `python -m pytest tests/test_conversation_history.py tests/test_admin_diagnostics_commands.py tests/test_nonebot_plugin_entry.py tests/test_admin_context_command.py tests/test_admin_config_command.py tests/test_admin_llm_command.py -q` 通过：72 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：247 个 pytest、ruff 和 mypy 均通过；mypy 仍只有未类型化测试函数提示。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static provider 下基础对话 pipeline 仍可运行，输出 `llm_status=not_configured`、`reply_budget:deep_help`、`rate_limit:ok` 和守岸人人格链路审计标签。
- 新增最近对话历史每作用域存储保留上限：`BOT_HISTORY_MAX_ITEMS=1000` 默认限制同一 platform/adapter/bot/session/sender 作用域最多保留 1000 条 `conversation_turns`，追加新轮次后只清理当前作用域更旧记录，不影响其他用户、会话、bot 或 adapter。
- 明确 `BOT_HISTORY_MAX_TURNS` / `BOT_HISTORY_MAX_CHARS` 是每次注入 prompt 的读取预算，`BOT_HISTORY_MAX_ITEMS` 是 SQLite 存储保留预算；`/wuwa status`、`/wuwa config`、`config-smoke` 和 `nonebot-smoke` 已输出安全 `history_max_items` 摘要。
- 同步 README、COMMANDS、运行时参数流、人格智能与知识库、输入输出契约文档，避免后续误把读取轮数当成存储保留上限。
- `python -m pytest tests/test_conversation_history.py tests/test_config_smoke.py tests/test_nonebot_plugin_entry.py tests/test_nonebot_smoke.py tests/test_admin_config_command.py -q` 通过：63 个相关测试通过。
- 新增普通 LLM 对话空白回复兜底：即使 provider 成功返回 `LLMReply`，只要 `reply.text` 去空白后为空，就按 `llm_error:empty_response` 归类，返回安全提示，不让空文本进入后续发送链路。
- `python -m pytest tests/test_llm_chat.py::test_chat_result_treats_blank_llm_reply_as_empty_response_error tests/test_llm_chat.py::test_chat_result_tags_llm_provider_error_kind -q` 先红后绿：2 个相关测试通过。
- `python -m pytest tests/test_llm_chat.py tests/test_llm_smoke.py tests/test_why_smoke.py tests/test_runtime_diagnostics.py -q` 通过：45 个 LLM 对话、smoke、why 和运行诊断相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过：命令文档和核心契约文档锚点有效。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：250 个 pytest、ruff 和 mypy 均通过；mypy 仍只有未类型化测试函数提示。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"` 通过：当前 static provider 下基础对话 pipeline 仍可运行，输出 `llm_status=not_configured`、`reply_budget:deep_help`、`rate_limit:ok`、prompt 安全诊断和守岸人人格审计标签。
- `config-smoke` 和管理员 `/wuwa config` 新增稳定 LLM 就绪三态：`llm_readiness_status=ready|local_only|blocked`。`ready` 表示真实 OpenAI-compatible provider 关键配置已具备且没有阻断错误，`local_only` 表示本地 pipeline 可验但尚未接真实模型，`blocked` 表示必须先处理 `errors`。
- `config-smoke` 和管理员 `/wuwa config` 新增 `llm_readiness_reasons`，按顺序输出去重后的 errors + warnings；无原因时显示 `-`。该字段只包含稳定原因码，例如 `provider_not_real`、`knowledge_files_empty`、`openai_api_key_missing`，不展示真实路径、API key、原始解析异常或 provider 错误。
- 同步 README、COMMANDS、运行时参数流和输入输出契约，把 `llm_readiness_status` 与 `llm_readiness_reasons` 纳入配置体检和管理员白名单字段。
- `nonebot-smoke` 和 `/wuwa status` 也复用配置体检逻辑输出 LLM 就绪三态与原因码，避免只看加载诊断或状态命令时误以为 provider/model 字段存在就等于真实模型已接通。
- `chat-smoke` 也复用 `config-smoke` 的只读配置体检逻辑，新增输出 `ready_for_real_llm`、`llm_readiness_status` 和 `llm_readiness_reasons`；它仍会跑基础对话 pipeline，但能同时提醒当前是 `local_only`、`ready` 还是 `blocked`，且不展示密钥、真实路径或原始解析异常。
- `why-smoke` 和真实 `/wuwa why` 使用的 `RuntimeDiagnostic` 也新增 LLM 就绪三态与原因码，并写入 SQLite `runtime_diagnostics`；旧诊断表会自动补 `ready_for_real_llm`、`llm_readiness_status` 和 `llm_readiness_reasons` 列。输出只展示稳定原因码，不展示密钥、真实路径、原始解析异常或 provider 错误。
- 管理员 `/wuwa recent [数量]` 的最近运行诊断摘要新增 `llm_readiness`、`ready_for_real_llm` 和 `llm_reasons`，可以在不知道具体 `request_id` 时先判断真实 LLM 是否就绪；原因码输出会过滤非稳定机器码，避免旧诊断或脏数据里的 API key、Authorization/Bearer、`session_id` 或原始错误被二次展示。
- 新增 `llm_next_action` 稳定动作码：`fix_config` 表示先修阻断配置，`configure_real_llm` 表示本地 pipeline 可跑但还没接真实模型，`llm_smoke` 表示真实模型关键配置已具备，下一步应跑 `scripts/dev.ps1 llm-smoke`。
- `config-smoke`、管理员 `/wuwa config`、`chat-smoke`、`why-smoke`、`nonebot-smoke` 和 `/wuwa status` 已展示 `llm_next_action`，字段来自同一套只读配置体检逻辑，不调用 LLM、不连接 NapCat、不展示密钥、真实路径或原始 provider 错误。
- `llm-smoke` 和管理员 `/wuwa llm` 已补齐同一套 LLM 就绪摘要：`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action` 和 `llm_readiness_reasons`。缺少真实 API key、model 或 base_url 时只返回 `config_missing` 与安全原因码，不调用 provider。
- 本轮按 TDD 新增并验证 `tests/test_llm_smoke.py` 与 `tests/test_admin_llm_command.py` 覆盖缺 model/base_url 不触发 provider、CLI 输出就绪摘要，以及在线管理员 LLM 诊断输出白名单字段。
- `context-smoke` 和管理员 `/wuwa context` 新增人格/知识来源安全指纹：输出 `persona_source_refs` 和 `knowledge_source_refs`，只用短 hash 表示来源是否加载或变化，不展示本机路径、文件名、知识正文、数据库路径、密钥、目标 ID 或 provider message id。
- 同步 COMMANDS、运行时参数流和输入输出契约：上下文诊断白名单包含来源安全指纹，但仍禁止输出原始测试文本、完整 prompt、知识原文、真实文件路径、文件名和任何密钥材料。
- 收紧本地 `context-smoke` 的 prompt 输出：默认不再打印 `system_prompt_preview`，只保留 `system_prompt_chars`、`user_prompt_chars`、分区预算和分区字符数，用于排查上下文预算而不泄露 prompt 原文。
- 新增人格材料强度诊断：`config-smoke` 和管理员 `/wuwa config` 现在输出 `persona_total_chars`、`persona_meaningful_lines` 和 `persona_strength_status=ok|weak|missing`，只展示安全计数和状态，不展示人格正文、真实路径或文件名。
- 人格文件缺失、不可读或为空仍是阻断错误；人格材料过薄会作为 `persona_profile_weak` warning 进入 `warnings` 和 `llm_readiness_reasons`，提醒真实 LLM 更容易出现人格漂移，但不阻断本地 pipeline 或真实 provider 连接诊断。
- 按 TDD 新增并验证 `tests/test_config_smoke.py` 与 `tests/test_admin_config_command.py` 覆盖弱人格 warning、安全字段输出、CLI 输出和管理员 `/wuwa config` 白名单。
- `python -m pytest tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_nonebot_smoke.py tests/test_nonebot_plugin_entry.py tests/test_llm_smoke.py tests/test_runtime_diagnostics.py tests/test_why_smoke.py -q` 通过：95 个相关测试通过。
- 收紧 `chat-smoke` CLI 输出安全边界：本地命令不再打印完整 `reply_text`，改为输出 `reply_preview_chars` 和 `reply_text_hidden=true`，避免接真实 LLM 后把完整模型回复、记忆或知识内容写进终端日志；内部 `run_chat_smoke()` 仍保留 `reply_text` 供测试和代码判断。
- 按 TDD 新增并验证 `tests/test_llm_smoke.py::test_chat_smoke_cli_prints_llm_readiness_summary`：先红后绿，确保 CLI 输出包含回复字符数和隐藏标记，且不出现 `reply_text=`。
- 新增本地聚合就绪入口 `scripts/dev.ps1 readiness-smoke` / `python -m plugins.wuwa_unified_runtime.smoke readiness`：聚合环境医生、配置体检、上下文诊断和本地静态聊天探针，输出 `readiness_status`、`next_action`、`recommended_commands`、`ready_for_local_dialogue`、`ready_for_real_llm`、`context_ok`、`chat_pipeline_ok`、`chat_pipeline_mode=local_static_probe` 和 LLM 就绪原因码。
- `readiness-smoke` 固定 `real_llm_probe_performed=false`，不调用真实 LLM provider，不连接或启动 NapCat，不发送 QQ，不展示 API key、真实路径、prompt 或完整回复正文；按 TDD 新增 `tests/test_readiness_smoke.py`，先红后绿覆盖函数、CLI 安全输出和 PowerShell 入口暴露。
- 新增管理员 `/wuwa readiness`：真实 NoneBot 入口复用 `readiness-smoke` 的聚合就绪逻辑，输出环境、配置、上下文、本地静态聊天探针、NoneBot 和 transport 的安全摘要；固定 `real_llm_probe_performed=false`，不调用真实 LLM、不连接 NapCat、不发送外部业务消息。
- `/wuwa readiness` 只允许 `admin` 角色使用；非管理员拒绝且不运行诊断导入，不透露人格、模型、文件、数据库或依赖状态。该命令仍走 `CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`，并且不会覆盖 `/wuwa why` 使用的最近业务诊断记录。
- 按 TDD 新增 `tests/test_admin_readiness_command.py`，先红后绿覆盖管理员安全摘要、非管理员拒绝、NoneBot 入口路由、自诊断排除集合和 help 文本；`python -m pytest tests/test_admin_readiness_command.py tests/test_admin_config_command.py tests/test_admin_llm_command.py tests/test_admin_context_command.py tests/test_readiness_smoke.py tests/test_nonebot_plugin_entry.py -q` 通过：60 个相关测试通过。
- 新增管理员 `/wuwa roles`：真实 NoneBot 入口可以查看权限角色规则矩阵，展示角色顺序、管理员/企业/可信/拉黑数量、拉黑阶段、限速/安静时间绕过角色、群命令前缀、ID 输入格式、角色来源配置项和管理员命令集合。
- `/wuwa roles` 只允许 `admin` 角色使用；非管理员拒绝且不泄露角色数量或具体 user_id。该命令不调用 LLM、不连接 NapCat、不发送外部业务消息，也不会展示 `session_id`、目标 ID、数据库路径、`provider_message_id` 或 `private_debug`，并且不会覆盖 `/wuwa why` 使用的最近业务诊断记录。
- 按 TDD 新增 `tests/test_admin_roles_command.py`，先红后绿覆盖管理员安全矩阵、非管理员拒绝、NoneBot 入口路由、自诊断排除集合和 help 文本；`python -m pytest tests/test_admin_roles_command.py tests/test_admin_readiness_command.py tests/test_admin_config_command.py tests/test_admin_llm_command.py tests/test_admin_context_command.py tests/test_admin_diagnostics_commands.py tests/test_permission_roles.py tests/test_nonebot_plugin_entry.py -q` 通过：80 个相关测试通过。
- 强化普通 LLM 对话失败兜底：provider 超时、错误或空白回复时，用户侧现在收到守岸人风格的模板提示，不再暴露 `debug=<kind>` 或机械错误类型；稳定错误类型仍保留在 `llm_error:<kind>` 审计标签、`chat-smoke`、`why-smoke` 和 `/wuwa why` 诊断字段中。
- 按 TDD 更新 `tests/test_llm_chat.py` 与 `tests/test_llm_smoke.py`，先红后绿覆盖超时和空白回复的角色化兜底、正文不含 `debug=`、错误类型仍写入审计；`python -m pytest tests/test_llm_chat.py tests/test_llm_smoke.py tests/test_why_smoke.py tests/test_runtime_diagnostics.py -q` 通过：50 个相关测试通过。
- 新增本地 `dialogue-smoke` 对话验收入口：聚合 `context-smoke` 的人格/知识/记忆/历史/情绪/prompt 安全摘要和 `chat-smoke` 的 pipeline 回执，输出 `dialogue_status`、`next_action`、回复预算、LLM 状态、就绪字段、`reply_preview_chars` 和 `reply_text_hidden=true`。
- `dialogue-smoke` 不连接 NapCat、不发送 QQ、不输出完整回复、prompt、用户原文、知识原文、真实路径、数据库路径或密钥；默认 static provider 不联网，真实 `openai_compatible` provider 发生 `llm_error` 时非零退出，避免把角色化兜底误判为真实模型成功。
- 按 TDD 新增 `tests/test_dialogue_smoke.py`，先红后绿覆盖 API 聚合、真实 provider 错误安全归因、CLI 安全输出和 `scripts/dev.ps1 dialogue-smoke` 暴露。
- 新增管理员 `/wuwa dialogue [测试文本]`：真实 NoneBot 入口复用 `dialogue-smoke` 的一轮对话验收逻辑，展示 `dialogue_status`、上下文安全计数、回复预算、LLM 状态、安全 `llm_error_kind`、LLM 就绪字段、`reply_preview_chars` 和 `reply_text_hidden=true`；非管理员拒绝且不触发模型调用，该命令不会覆盖 `/wuwa why` 最近业务诊断记录。
- 同步 README、COMMANDS、运行时参数流和输入输出契约，把 `/wuwa dialogue` 纳入管理员安全排障命令集合；输出禁止展示完整模型回复、原始测试文本、完整 prompt、知识原文、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id 或原始 provider 错误。
- 按 TDD 新增 `tests/test_admin_dialogue_command.py`，先红后绿覆盖管理员摘要、真实 provider 错误安全归因、非管理员不运行 probe、NoneBot 入口路由和 help 文本；`python -m pytest tests/test_admin_dialogue_command.py tests/test_admin_readiness_command.py tests/test_admin_config_command.py tests/test_admin_llm_command.py tests/test_admin_context_command.py tests/test_admin_roles_command.py tests/test_nonebot_plugin_entry.py -q` 通过：66 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：278 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示。
- OneBot/NapCat transport 已补合并转发扩展边界：`allow_forward=true` 时尝试 `send_group_forward_msg` / `send_private_forward_msg` 或对应 `call_api(...)`；不允许、节点缺失或 API 不可用时降级 `text_fallback`。`transport-smoke` 使用 fake bot 验证 `forward_api=true`、`forward_receipt_state=sent` 和 fake forward 调用计数，不启动 NoneBot/NapCat，不发送真实 QQ。
- LLM base_url 安全边界已补到文档：空地址、非法/非 HTTP(S) 地址和带用户名密码的地址会在联网前被拒绝，原因码分别是 `openai_base_url_missing`、`openai_base_url_invalid` 和 `openai_base_url_unsafe`；输出的 `endpoint_url` 会把 URL 用户信息显示为 `[redacted]`。
- `/wuwa recent` 文档已补安全 `diagnostic_tags`：仅显示固定机器标签，例如 `prompt_injection`、`prompt_injection:instruction_override`、`history_record_skipped` 和 `history_skip:prompt_injection`，不展示用户原话、密钥、Authorization/Bearer、`session_id`、目标 ID 或原始 provider 错误。
- SQLite 发送队列新增 `claim_due()` 租约认领：到期 `queued` / `failed_retryable` 请求会原子切到内部 `processing` 状态并写入 `lease_expires_at`，租约过期可重新认领，真实投递成功、可重试失败或最终失败后会清除租约字段。
- `drain_send_queue_once()` 已优先使用 `claim_due()`，避免多个 worker 并发时重复投递同一队列项；老式只支持 `list_due()` 的队列仍可 fallback。
- `/wuwa queue` 和 `queue-smoke` 已输出安全 `processing` 计数；该字段只表示队列表内部租约数量，不展示目标、正文、`dedupe_key`、数据库路径或 provider message id，也不加入公开 `DeliveryReceipt` 状态枚举。
- 按 TDD 验证队列租约行为：先让管理员队列摘要缺少 `processing` 的测试失败，再补 formatter；随后 `python -m pytest tests/test_send_queue.py tests/test_send_queue_worker.py tests/test_queue_smoke.py tests/test_admin_diagnostics_commands.py::test_admin_queue_query_returns_safe_summary_without_payload_or_targets -q` 通过：15 个相关测试通过。
- 新增发送队列内部只读 `find_request(request_id)`：进程内队列从内存镜像查找，SQLite 队列从持久化 `send_requests.request_json` 恢复 `SendRequest`，用于运行诊断和 `/wuwa why` 判断发送请求是否创建。
- `_record_runtime_diagnostic()` 已优先通过队列 `find_request()` 查找请求，再 fallback 到旧的 `sent_requests` 内存镜像，避免 SQLite 队列重开后把已创建的发送请求误判为 `send_request_created=false`。
- 按 TDD 验证持久化诊断恢复：先新增 `test_sqlite_send_queue_finds_request_after_reopen` 和 `test_plugin_entry_records_runtime_diagnostic_from_persistent_queue_after_reopen` 并观察红灯，再实现队列查找接口；`python -m pytest tests/test_send_queue.py::test_sqlite_send_queue_finds_request_after_reopen tests/test_nonebot_plugin_entry.py::test_plugin_entry_records_runtime_diagnostic_from_persistent_queue_after_reopen -q` 通过：2 个相关测试通过。
- `python -m pytest tests/test_send_queue.py tests/test_runtime_diagnostics.py tests/test_nonebot_plugin_entry.py -q` 通过：63 个队列、运行诊断和 NoneBot 入口相关测试通过。
- 新增进程内运行时软暂停：`RuntimeControlState` 支持 `/wuwa pause` 和 `/wuwa resume`，普通聊天、自动发送预览和非排障能力会在 policy 前被阻断，不调用 LLM、不创建 `SendRequest`；管理员诊断、状态和恢复命令仍可用。
- 新增管理员运行时控制输出：`build_runtime_control_result()` 只允许 admin 使用，只展示 `runtime_paused`、安全 reason 和 `updated_by=set|missing`，不展示具体 user_id、`session_id`、目标 ID、数据库路径或 `private_debug`；软暂停不写 `.env`，重启后按配置重新开始。
- 按 TDD 验证软暂停：先新增 runtime pipeline、管理员控制命令和 NoneBot 入口路由测试并观察红灯，再实现 `RuntimeControlState`、`build_runtime_control_result()` 和 `/wuwa pause|resume` 路由；`python -m pytest tests/test_runtime_pipeline.py tests/test_admin_diagnostics_commands.py tests/test_nonebot_plugin_entry.py -q` 通过：73 个相关测试通过。
- `/wuwa status` 已把 `BOT_RUNTIME_ENABLED` 硬开关和当前进程 `RuntimeControlState` 软暂停状态分开展示：`运行时硬开关：enabled|disabled`、`运行时软暂停：true|false，reason=...，updated_by=set|missing`。NoneBot 入口会把同一个 `runtime_control` 传给 status，避免真实排障时把 `.env` 硬关闭、管理员临时 pause 和 LLM/provider 配置问题混在一起；输出仍不展示具体管理员 ID。
- `/wuwa readiness` 已接入同一个当前进程 `RuntimeControlState`，在线统一就绪摘要会展示 `runtime_soft_paused=true|false`、安全 reason 和 `runtime_soft_pause_updated_by=set|missing`，用于排查“配置看起来就绪但机器人被软暂停”的场景；输出不展示具体管理员 ID。
- 按 TDD 验证 readiness 软暂停可观测性：先新增 `test_admin_readiness_query_reports_runtime_soft_pause_without_leaking_actor` 并观察红灯，再实现 `build_readiness_query_result(..., runtime_control=...)` 和 NoneBot 入口传参；`python -m pytest tests/test_admin_readiness_command.py tests/test_nonebot_plugin_entry.py tests/test_admin_diagnostics_commands.py tests/test_readiness_smoke.py -q` 通过：67 个相关测试通过。
- 新增真实 LLM 生成参数预检：`BOT_CHAT_TEMPERATURE` 必须在 0.0 到 2.0，`BOT_CHAT_MAX_TOKENS` 必须大于等于 1，`BOT_CHAT_TIMEOUT_SECONDS` 必须大于 0；否则 `config-smoke` / `/wuwa config` 输出 `openai_temperature_invalid`、`openai_max_tokens_invalid` 或 `openai_timeout_seconds_invalid`，`llm-smoke` / `/wuwa llm` 不会调用真实 provider。
- `config-smoke` 和 `/wuwa config` 已输出安全 `chat_temperature`、`chat_max_tokens` 和 `timeout_seconds`；`llm-smoke` 和 `/wuwa llm` 已输出诊断短调用实际使用的 `diagnostic_temperature`、`diagnostic_max_tokens` 和 `timeout_seconds`，其中短诊断 temperature 收口到不超过 0.3，max_tokens 收口到不超过 128。
- 按 TDD 验证 LLM 参数预检：先新增配置体检、管理员配置、LLM smoke 和管理员 LLM 诊断测试并观察红灯，再实现参数预检与安全输出；`python -m pytest tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_llm_smoke.py tests/test_admin_llm_command.py tests/test_llm_provider.py -q` 通过：71 个相关测试通过。
- `dialogue-smoke` 和管理员 `/wuwa dialogue` 已接入配置阻断短路：当只读配置体检显示 `llm_readiness_status=blocked` 时，直接返回 `next_action=fix_config`、`llm_status=not_called`、`receipt_state=not_created`，不会调用真实 provider。
- 普通 `wuwa.chat` 能力也已消费同一套生成参数预检：非法 `temperature/max_tokens/timeout_seconds` 会在调用 `LLMProvider.generate` 前写入 `llm_preflight_blocked`、`llm_preflight_error:<reason>` 和 `llm_error:config_missing`，返回守岸人风格兜底，避免把本地配置错误误判成上游模型失败。
- 按 TDD 验证生成参数预检下沉：先新增 `tests/test_dialogue_smoke.py`、`tests/test_admin_dialogue_command.py` 和 `tests/test_llm_chat.py` 红灯测试，确认 provider 仍被错误调用；再实现对话验收短路和聊天能力预检拦截；相关定向测试通过。
- `why-smoke` 和真实 `/wuwa why` 的 `RuntimeDiagnostic` 现在会把 `llm_preflight_blocked` 解释为“LLM 生成参数或配置非法，已在调用 provider 前阻断”，优先于普通 “LLM 调用失败” 文案。
- 预检阻断诊断只展示稳定原因码白名单：`openai_temperature_invalid`、`openai_max_tokens_invalid` 和 `openai_timeout_seconds_invalid`；不会展示 API key、Authorization/Bearer、用户原文、prompt 或原始 provider 错误。
- 按 TDD 新增 `tests/test_why_smoke.py` 和 `tests/test_runtime_diagnostics.py` 红灯测试，先确认旧 `why_summary` 仍笼统显示 `config_missing`，再实现安全原因码提取与中文结论；`python -m pytest tests/test_why_smoke.py tests/test_runtime_diagnostics.py -q` 通过：29 个相关测试通过。

## 2026-07-10

- 新增 LLM 就绪安全修复提示 `llm_fix_hints`：`config-smoke`、`readiness-smoke`、`dialogue-smoke`、`llm-smoke`、`nonebot-smoke` 以及管理员 `/wuwa config`、`/wuwa readiness`、`/wuwa dialogue`、`/wuwa llm` 会在原因码之外输出可执行的配置提示。
- `llm_fix_hints` 由稳定原因码映射生成；有阻断错误时只根据 errors 生成，没有 errors 时再根据 warnings 给下一步建议。提示只包含配置项名、推荐范围和占位值，例如 `BOT_CHAT_PROVIDER=openai_compatible`、`BOT_CHAT_API_KEY=<real_api_key>`、`BOT_CHAT_TEMPERATURE=0.0..2.0`、`remove_credentials_from_BOT_CHAT_BASE_URL`。
- 明确安全边界：`llm_fix_hints` 不能包含真实 API key、Authorization/Bearer、真实文件路径、数据库路径、prompt、用户原文、人格正文、provider 原始错误或 HTTP 响应正文。
- 修复 `llm-smoke` CLI 曾未打印 `llm_fix_hints` 的问题；补充 TDD 用例 `tests/test_llm_smoke.py::test_llm_smoke_cli_prints_readiness_summary`，先红后绿验证本地 LLM 诊断也能看到安全修复提示。
- 修复 `nonebot-smoke` CLI 打印 `llm_fix_hints` 时 `run_nonebot_smoke()` 未透传字段导致的 `KeyError`；补充 `tests/test_nonebot_smoke.py` 覆盖结果字典和 CLI 输出。
- 同步 README、COMMANDS、运行时参数流和输入输出契约，说明 `llm_fix_hints` 的字段位置、生成规则和脱敏要求。
- `python -m pytest tests/test_config_smoke.py tests/test_admin_config_command.py tests/test_readiness_smoke.py tests/test_admin_readiness_command.py tests/test_admin_llm_command.py tests/test_llm_smoke.py tests/test_nonebot_smoke.py -q` 通过：63 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、342 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示。
- 新增本地 `persona-smoke` 人格自检入口：输出 `persona_status=ok|weak|blocked`、`persona_next_action`、人格/知识来源安全指纹、人格强度、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪三态和安全 `llm_fix_hints`；不调用 LLM、不启动 NapCat、不发送消息，不展示人格正文、知识正文、本机路径、prompt、用户原文或密钥。
- 新增管理员 `/wuwa persona`：真实 NoneBot 入口复用 `persona-smoke` 的只读人格自检逻辑，仍走统一 pipeline；非管理员拒绝，且该命令不会覆盖 `/wuwa why` 最近业务诊断记录。
- 按 TDD 新增 `tests/test_persona_smoke.py` 和 `tests/test_admin_persona_command.py`，先观察缺少 `run_persona_smoke`、CLI task、管理员命令和 help 文案的红灯，再实现人格自检、CLI、NoneBot 路由和安全 formatter；`python -m pytest tests/test_persona_smoke.py tests/test_admin_persona_command.py -q` 通过：7 个相关测试通过。
- 同步 README、COMMANDS、人格/知识规格、运行时参数流和输入输出契约，把 `persona-smoke` 与 `/wuwa persona` 纳入安全白名单和命令说明。
- 新增本地 `llm-setup` 接入清单入口：复用 `config-smoke` 的 LLM 就绪规则，输出 `llm_setup_status=needs_env_edit|blocked|ready_for_probe`、必填 `BOT_CHAT_*` 项、安全 `.env` 占位模板、缺失/占位键名、人工步骤和下一步命令；不写 `.env`，不调用真实 LLM，不启动 NapCat，不发送 QQ，也不展示 API key、真实路径、prompt、人格正文或知识正文。
- 按 TDD 新增 `tests/test_llm_setup.py`，先观察缺少 `run_llm_setup`、CLI task 和 PowerShell 入口的红灯，再实现 `run_llm_setup`、`python -m plugins.wuwa_unified_runtime.smoke llm-setup` 与 `scripts/dev.ps1 llm-setup`；`python -m pytest tests/test_llm_setup.py -q` 通过：5 个相关测试通过。
- 同步 README 与 COMMANDS，把 `llm-setup` 纳入常用命令、命令矩阵和接真实 LLM 前推荐顺序。
- 新增管理员 `/wuwa setup llm`：真实 NoneBot 入口复用本地 `llm-setup` 的只读接入清单，输出 `llm_setup_status`、LLM 就绪三态、安全 `llm_fix_hints`、必填/缺失环境变量、安全 `.env` 模板、人工步骤和下一步命令。
- `/wuwa setup llm` 只允许管理员使用；非管理员拒绝且不泄露配置状态。该命令不写 `.env`、不调用真实 LLM provider、不连接 NapCat、不发送 QQ，也不会展示 API key、Authorization/Bearer、本机路径、prompt、人格正文、知识正文、目标 ID、provider message id 或 `private_debug`，并且不会覆盖 `/wuwa why` 最近业务诊断。
- 按 TDD 新增 `tests/test_admin_llm_setup_command.py`，先观察缺少 `build_llm_setup_query_result`、NoneBot 路由和 help 文案的红灯，再实现管理员能力、`/wuwa setup llm` 路由、自诊断排除集合和安全 formatter；`python -m pytest tests/test_admin_llm_setup_command.py -q` 通过：4 个相关测试通过。
- `python -m pytest tests/test_admin_llm_setup_command.py tests/test_llm_setup.py tests/test_admin_llm_command.py tests/test_admin_roles_command.py tests/test_nonebot_plugin_entry.py -q` 通过：66 个相关测试通过。
- 同步 README 与 COMMANDS，把 `/wuwa setup llm` 纳入在线管理员命令、状态诊断、非覆盖业务诊断集合和下一阶段命令里程碑。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、358 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示。
- 加强手动记忆的群聊隐私边界：`/wuwa memory list` 在 `group:*` 会话中不再输出个人记忆正文，只提示用户到私聊查看，避免把当前用户/会话作用域内的偏好或敏感上下文公开到群里。
- 按 TDD 新增 `tests/test_memory_commands.py::test_memory_list_command_does_not_publish_personal_facts_in_group`，先观察旧实现会把 `fact_private` 和正文发到群里，再在 `route_memory_command()` 中加入群聊 `memory list` 拦截；`python -m pytest tests/test_memory_commands.py -q` 通过：5 个相关测试通过。
- 同步 README、COMMANDS 和人格/知识规格，明确群聊 `memory list` 的安全提示行为和不得公开个人记忆正文的 invariant。
- `python -m pytest tests/test_memory_commands.py tests/test_memory_context.py tests/test_llm_chat.py tests/test_nonebot_plugin_entry.py -q` 通过：75 个相关测试通过；`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、359 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示。
- 为 SQLite 长期记忆补充 `sensitivity` 与 `scope_key` 元数据：新写入事实默认 `sensitivity=personal`、`scope_key=session:<session_id>`，旧表会自动补列，检索结果和 LLM prompt 内部记忆行会携带这两个边界字段。
- `/wuwa memory add` 支持 `--sensitivity=public|group|personal|credentialed`；群聊 `/wuwa memory list` 现在只展示 `public` / `group` 事实，继续过滤 `personal` 和 `credentialed` 正文。
- 按 TDD 新增记忆元数据、群聊安全列表和 prompt 标注测试，先观察旧仓储缺少参数、旧命令把 `--sensitivity=group` 当正文、旧 prompt 不标注敏感度，再实现最小改动；`python -m pytest tests/test_memory_context.py tests/test_memory_commands.py -q` 通过：13 个相关测试通过。
- `python -m pytest tests/test_memory_context.py tests/test_memory_commands.py tests/test_llm_chat.py tests/test_nonebot_plugin_entry.py -q` 通过：79 个相关测试通过；`python -m pytest tests/test_llm_smoke.py tests/test_admin_context_command.py tests/test_emotion_context.py tests/test_conversation_history.py -q` 通过：37 个相关测试通过。
- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check` 通过；`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过：docs-check、plugin-check、363 个 pytest、ruff 和 mypy 均通过；mypy 仅输出未类型化测试函数提示。
- 加强基础对话上下文读取失败兜底：`wuwa.chat` 在 `FileCharacterContextProvider` 或其他上下文 provider 抛错时不再把异常冒泡成内部错误，也不会调用 LLM；用户侧收到守岸人风格安全提示，审计标签写入 `context_error` 和 `context_error:provider_failed`，且不展示真实路径、文件名或异常正文。
- `/wuwa why` / `why-smoke` 的运行诊断已能识别 `context_error`，把 `llm_status` 标记为 `not_run`，中文结论说明“人格或知识上下文读取失败，已跳过 LLM，返回安全提示”，避免误判成真实 provider 已调用。
- 按 TDD 新增 `tests/test_llm_chat.py::test_chat_capability_returns_safe_context_error_without_calling_llm` 和 `tests/test_runtime_diagnostics.py::test_runtime_diagnostic_explains_context_error_without_claiming_llm_called`，先观察红灯，再实现聊天兜底和诊断归因；`python -m pytest tests/test_llm_chat.py tests/test_runtime_diagnostics.py -q` 通过。
- 修复 NoneBot 聊天入口的被动群消息噪音：`passive_group_message` 阻断现在只记录审计和运行诊断，不再把“该场景下未启用主动回复。”发回群里；按 TDD 新增 `tests/test_nonebot_plugin_entry.py::test_chat_policy_passive_group_block_is_silent_for_nonebot_entry`，先观察红灯，再实现静默跳过。

## 2026-08-22：Lofter / allcpp / Pixiv 深度解析落地

- 三个并行子代理按 TDD 交付新解析模块（先红灯后绿灯，各自回归旧测试）：
  - `plugins/bot_unified_runtime/sources/parsers/platforms_lofter.py` + `http_util.http_post_form` + `tests/test_lofter_parser.py`（7 测）
  - `plugins/bot_unified_runtime/sources/parsers/platforms_allcpp.py` + `tests/test_allcpp_parser.py`（5 测）
  - `plugins/bot_unified_runtime/sources/parsers/platforms_pixiv.py`（多图分镜+作者作品/粉丝+proxy 透传）+ `tests/test_pixiv_parser.py`（4 测）
- 集成：`platforms_generic.py` 移除旧占位实现，`parsers/__init__.py` 改导入并把 `pixiv` 加入 `_PARSER_PROXY_PLATFORM`；
  旧测试 `test_parse_spa_link_cards` → `test_parse_spa_link_card_mihuashi`，`test_parse_pixiv_deep` 改为从新模块导入。
- 文档：README 新增「支持的链接解析平台」清单；.env.example 代理注释改为「油管/推特/Spotify/Pixiv 走代理」。
- 验证：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 通过（docs-check + plugin-check + 570 pytest）。
  ruff/mypy 当前环境未安装，verify 按设计跳过（上一会话环境有，需在配好工具链的机器上再跑 lint/typecheck）。
- 环境说明：系统 `%TEMP%\pytest-of-LancyCelestia` 是历史遗留且 ACL 损坏，沙箱内 `tmp_path` 夹具失败；
  本轮用工作区 basetemp + 提权跑测试绕过，属环境问题、与代码无关。
- 已知边界：Lofter 新版 permalink 帖子（`/post/{令牌}`）与米画师/画加仍为浅层降级；mihuashi/huajia 深解析留待下一轮。


## 2026-08-22：B站/小红书解析与订阅系统落地（M0-M2）

### M0（可测试程序 + 接入手册）
- cookie 已复制到 data/platform_cookies.txt（Netscape，1996 行，git 忽略）。
- persona-smoke / llm-smoke / chat-smoke 通过（deepseek-v4-flash，llm_status=ok，receipt_state=sent）。
- 新增 docs/acceptance-manual.md（对话/人格测试、NapCat、GsCore、插件接入、验收清单）。

### 基础订阅框架（子代理 Halley 交付）
- contracts/subscription.py、subscription_store.py(SQLite)、subscription_watcher.py、
  sources/subscriptions/__init__.py(pkgutil 自动发现 *_adapter.py)、capabilities/subscribe.py。
- __init__.py 调度：sub_watch(300s)/sub_live(60s)/sub_digest(20:00)，全部 jitter=60。
- 主控集成：/bot subscribe 命令分支接入 _handle_status；新增 BOT_FETCH_PLAYWRIGHT_ENABLED、
  BOT_SUBSCRIBE_PLAYWRIGHT_POLL_SECONDS；content 能力注入 PlaywrightFetchBackend。

### B站解析 100%（子代理 Euclid 交付 + 主控修复）
- wbi.py（盐表/签名）；PGC 番剧深解析(season+stat，ss/ep)；合集 seasons_series_list/
  seasons_archives_list + 旧版 x/series/archives；opus 改 opus/detail+WBI；直播/空间/分P增强。
- 主控修复真实结构 bug：opus/detail 的 modules 是 MODULE_TYPE_* 列表、正文在
  module_content.paragraphs 文本节点（node.word.words 嵌套键）——补回归测试后修复。
- 真实烟测：live/space/favlist/opus/bangumi(ss+ep)/watchlater 全通过。

### B站订阅（子代理 Dalton 交付）
- bilibili_adapter.py：creator(WBI arc/search + 动态 best-effort)/live_room(LIVE_POLL 状态差分)/
  bangumi(ep→ss→episodes)/favorite/collection；resolve_target 覆盖六类 URL。
- 真实烟测：creator 拉 7 条新视频+cursor、bangumi 14 集、直播间 live_started 候选均通过。

### 小红书（子代理 Arendt/Carver 交付 + 主控修复）
- fetchers/playwright_backend.py + xhs_sign.py(诚实占位)；parse_xiaohongshu 增加 /user/profile 深解析；
  xiaohongshu_adapter.py 用 capture_json(user_posted) + HTML 兜底。
- 主控修复：sync_playwright() 是 context manager，必须 .start() 才有 .chromium（真实烟测暴露并修复）。
- 真实烟测：无头 Chromium 注入 14 条 xhs cookie 抓取 explore 页成功（224KB HTML，含 __INITIAL_STATE__）。

### 验收状态
- 全量 pytest：640 passed（含各代理新增 ~62 项订阅/解析测试）。
- 剩余：最终 verify、清理临时评估环境、提交。


## 2026-08-22：SQLite ORM 底座 + NapCat token 接入（验收前）

- 补齐 `nonebot-plugin-orm[sqlite]`（安装 aiosqlite 0.22.1），pyproject 依赖同步改为 `nonebot-plugin-orm[sqlite]>=0.8.3`。
- `.env` 与 `.env.example` 增加 `SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:///data/nonebot_orm.sqlite3`，修复启动时「没有数据库」。
- `.env.prod` 的 OneBot 反向 WS 改为 `ws://127.0.0.1:3001/?access_token=<本地token>`，token 仅存本地、不写文档或日志。
- 新增 `tests/test_project_config_contract.py`：校验 ORM sqlite 依赖、数据库连接串与 `nb orm`/`nb run` 文档契约。
- 更新 `docs/napcat-setup.md`、`docs/acceptance-manual.md`、`GIT.md`、`README.md`：数据库初始化步骤、NapCat token 配置与中文提交信息规范。

### 烟测发现并修复的两处真问题
- 驱动组合必须为 `~fastapi+~httpx+~websockets`：仅有 `~fastapi+~httpx` 时 OneBot V11 会打印 `does not support websocket client connections` 并忽略 `ONEBOT_WS_URLS`，导致连不上 NapCat。
- `plugins/bot_unified_runtime/__init__.py` 在 `from __future__ import annotations` 下把 `Bot/Event/T_State` 只做了函数内局部导入，NoneBot 注册 handler 时按模块 globals 解析 ForwardRef 失败；已改为模块级导入，startup-smoke 的 matcher_count 从异常中断恢复到 10。

### QQ 实测后的第二轮修复
- `/bot status` 曾被安全审查误拦：状态正文里的 `api_key=set` 命中“明显密钥形态”正则；已让 reviewer 只拦截真实密钥形态（`set/missing/[redacted]` 占位值放行），并新增两条回归测试。
- 已把管理员 QQ 写入 `.env`：`BOT_ADMIN_USER_IDS=["3865067623","1722380002"]`（本地文件，不入库），重启后 `/bot logs` 等管理员命令可用。
- 全量 pytest 更新为 655 passed，机器人重启后已重新连接 NapCat（Bot 3958874605）。


## 2026-08-23：命令体验、点歌模式与向量知识库落地

- 对话输出：新增 roleplay 分行格式化，成功 LLM 回复中括号动作与说话拆段。
- 命令路由：wiki/epic/weather/today/music 支持 `/`、`!`、`！` 前缀与 ASCII 大小写；中文订阅命令与 `/岸宝<功能>` 昵称命令接入统一 pipeline。
- 点歌：新增 `/点歌模式`（管理员、RuntimeSettingsStore 持久化），支持音频文件/语音/链接/卡片四种输出。
- 媒体发送：本地 image/record/video/file 相对路径自动转绝对路径，修复卡片解析成功但 OneBot 发送失败问题。
- 向量知识库：新增 OpenAI-compatible embedding provider、SQLite 向量库、关键词跨文件检索回退；`BOT_KNOWLEDGE_FILES` 接入四份用户材料。
- 全量 pytest：705 passed。

## 2026-08-23：PostgreSQL 落地与多实例共享底座
- 按用户选择，PostgreSQL 17.11 已安装到 C:\Software\PostgreSQL\17（端口 5432，服务 postgresql-x64-17 自动启动），安装器在 C:\Software\_installers（哈希已校验）。
- 创建 chatbot 数据库与 bot_a/bot_b/shared schema；连接串密码中的 @ 编码为 %40 后写入本地 .env（不入库）。
- ORM 驱动改用 asyncpg：psycopg 异步与 Windows 默认 ProactorEventLoop 不兼容，实测 nb run 会启动失败；asyncpg 下 nb orm upgrade/check 与真实 nb run 全部通过，OneBot V11 已连接 NapCat。
- 修复 bot_share_groups 缺少列表校验器导致 smoke 配置加载失败的问题（新增字符串/JSON 输入回归测试）。
- scripts/dev.ps1 verify 内 pytest 统一把 TMP/TEMP 指向 .pytest_tmp_ci，规避 Windows 沙箱 WinError 5。
- 验收：全量 pytest 711 passed，scripts/dev.ps1 verify 通过。

## 2026-08-23：通用 HTML 卡片渲染 + B站 PGC/直播/动态字段 + 商品解析

- 参考 MIT 万能解析器（astrbot_plugin_parser，Copyright (c) 2024 Les Freire）落地通用信息卡渲染：
  新增 `output/card_render/`（RenderPayload 模型 + 桥接 + 1440×960 通用模板），B站/小红书等深解析自动渲染卡片 PNG，失败降级文本；已写入 THIRD_PARTY_NOTICES.md 保留 MIT 出处。
- B站解析补强：PGC 按 season_type 细分番剧/电影/纪录片/国创/电视剧/综艺（page_type/badge/detail.episodes），直播补分区/标签/封面/截图，动态补图片/作者，视频补作者。
- 新增 B站商品解析（`platforms_bilibili_goods.py`）：魔力赏市集列表接口按 itemsId 匹配（需 cookies.txt 登录态），会员购走 og 兜底，全部失败时浅层降级、不打断消息链路。
- 验收：全量 pytest 737 passed；scripts/dev.ps1 verify、startup-smoke、nonebot-smoke 通过；nb orm check 无新升级、nb run 链路正常。
- 真实只读烟测：B站市集列表接口当前返回空列表（需设备指纹），商品解析会按设计回退 og/浅层降级；其余 B站 PGC/直播/动态字段与通用卡片渲染由固定响应测试覆盖。

## 2026-08-23：阿里云百炼 qwen3.7-text-embedding 接入与 NapCat 登录指引

- 向量嵌入层：新增 `BOT_EMBEDDING_DIMENSIONS`，OpenAI 兼容 provider 支持 `dimensions` 请求参数；嵌入批大小 32→10，兼容百炼 qwen3.7（20 条上限）与 text-embedding-v4（10 条上限）。
- 知识库：`SqliteVectorKnowledgeStore` 新增 `embed_pending()`（预建库、断点续跑）与 `stats()`。
- 新命令：`scripts/dev.ps1 embedding-smoke`（连通性验证，不落库）与 `scripts/dev.ps1 knowledge-sync`（把四份材料切片向量化写入 data/knowledge_embeddings.sqlite3）。
- 本地 .env 已预填 model/base_url/dimensions（qwen3.7 + dashscope 兼容端点），待用户填入 API Key 并把 ENABLED 改 true 即可一键烟测。
- dev.ps1 pytest 临时目录改为 `.pytest_tmp_ci_<PID>` 避免 Windows ACL 锁死后无法复跑；.gitignore 同步覆盖 `.pytest_tmp*/`。
- 验收：全量 pytest 746 passed，scripts/dev.ps1 verify 通过。

## 2026-08-23：百炼 Key 落地与模型回退

- 按用户提供 Key 写入本地 .env（不入库），BOT_EMBEDDING_ENABLED=true。
- 支持多模型回退：`BOT_EMBEDDING_MODEL=qwen3.7-text-embedding,text-embedding-v4`，前者失败自动换后者；批大小 10 兼容两者上限。
- 真实烟测：embedding-smoke ok=true（1024 维）；knowledge-sync 完成 2777/2777 行向量化（SQLite 61MB）；端到端语义检索命中鸣潮库街区百科v2 相关段落。
- NapCat 重启方式已确认并写入 docs/napcat-setup.md：C:\Software\NapCat 下 launcher-win10-user.bat，先停 QQ/NapCatWinBootMain 再启动 launcher 重新扫码。
- 全量 pytest 748 passed（新增 2 条回退测试）。

## 2026-08-23：本地 Ollama bge-m3 优先 + 百炼兜底

- 嵌入链改为：本地 Ollama `http://127.0.0.1:11434/v1` + `bge-m3` 优先；失败自动切百炼 `qwen3.7-text-embedding,text-embedding-v4`；成功后 sticky 当前链。
- 修复两个真实问题：空 Authorization 头导致 httpx 报错；bge-m3 首次加载超 5s 被误判不可用（本地超时改为 60s）。
- 新增模型指纹：换端点/模型自动清空旧向量重建，避免向量空间混用；`knowledge_meta.embedding_signature` 已记录当前指纹。
- 真实烟测：embedding-smoke 命中本地 bge-m3（1024 维）；knowledge-sync 用 bge-m3 重建 2777/2777 行；语义检索命中人格档案。
- 全量 pytest 752 passed。

## 2026-08-23：本地向量未运行时的静默回退保证

- 新增 3 条回归测试（本地 404 / 返回体异常 / 全链不可用），锁定「本地挂了不报错、静默切百炼」的行为。
- 真实死端口验证：本地不可达 → 自动切百炼 qwen3.7，1024 维，exit=0 零报错。
- 全量 pytest 755 passed。

## 2026-08-23：对话体验四项修复
- 颜文字不再被拆行：动作格式器只拆“括号内有汉字/嵌套括号”的动作，纯符号颜文字保持原位；合并转发改为标点安全断行。
- 取消回复长度限制：0=不限制语义落到 回复条数/单条长度/合并转发 三处，完整回复一次性发出，不再出现“（平台单条消息长度限制…）”提示。
- 参考 angel_heart/angel_memory（AGPL）的思路调研完成，只借鉴设计、不抄代码；新增世界观“先事实后感受”提示词规则。
- 知识检索增强：BOT_KNOWLEDGE_TOP_K=6，上下文预算 4096/6144。
- 全量 pytest 763 passed（新增 8 条回归）。

## 2026-08-23：基层统一路由与人格档案收口
- 新建 `runtime/base_router.py`（基层路由器）+ `tests/test_base_router.py`（11 条分类测试）+ `docs/specs/base-routing.md`。
- 12 个 NoneBot matcher rule 全部委托给基层路由器；新增 `/bot route <文本>` 调试命令，帮助文案已更新。
- BOT_PERSONA_FILES 切换为用户三份权威人格档案（守岸人档案/人格档案/人格设定），persona-smoke 校验 3 文件可读、47,994 字符。
- persona-smoke、startup-smoke 通过（matcher_count=12 不变）；全量 pytest 预计 774 passed。

## 2026-08-23：基层路由全接口预配置 + 点名接话 + 自然语言命令 + 表情包

- base_router 重写为声明式 RouteRule 注册表 + INTERFACE_MANIFEST（16 条接口，含 GsCore/早柚桥、NapCat 传输、解析、人格、天气、游戏直播（预留）、订阅、表情吸收（预留）等）；新增 /bot routes 审计命令。
- 优先级调整：昵称命令 10、管理员命令 11 排最前；新增 meme=20、natural_command=45；NoneBot matcher 顺序与注册表一致（startup-smoke matcher_count=14，priority 10/11/12/13/20/40/41x5/45/46/50）。
- 新增 runtime/natural_language.py：把“帮我查杭州天气/来首晴天/查维基/今天有什么免费游戏/今天历史上发生了什么”归一化成标准命令执行，保守规则不劫持闲聊。
- 新增 runtime/mentions.py：只写昵称/名字也算点名（岸宝，…、守岸人 天气、呼叫守岸人），并入 mentions_bot。
- 群聊自动接话：BOT_GROUP_CHAT_AUTO_REPLY_ENABLED（默认关）+ BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY，确定性 SHA-256 抽签，可复现可审计。
- 新增 capabilities/meme.py：自研 MIT 协议客户端对接本地 meme-generator-rs（/表情 列表、/表情 <key> <文字>、/表情帮助），服务不可达优雅降级；三件套结论：两个 NoneBot 插件功能重复且会绕过基层流水线，故不安装、自研接入。
- 全量 pytest 808 passed（+34）；dev.ps1 verify / startup-smoke / persona-smoke / chat-smoke（真实 deepseek-v4-flash，receipt_state=sent）全部通过。
