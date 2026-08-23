# 开发命令

本项目统一使用 `scripts/dev.ps1` 作为 Windows 本地开发、验证和启动入口。

这些命令会诚实反映当前项目阶段：仓库已有研究资料、契约文档和 Milestone 0 统一运行时插件骨架。

## 常用命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dialogue-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 persona-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-setup
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dev
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

## 命令矩阵

| 任务 | 用途 | 当前行为 |
| --- | --- | --- |
| `help` | 显示帮助。 | 始终可用。 |
| `doctor` | 诊断当前 PowerShell/Python 环境是否能运行本项目。 | 输出当前 Python、`nonebot`、OneBot V11 adapter、`nonebot_plugin_apscheduler`、统一运行时插件、`nb` CLI、`ready_for_local_llm_smoke` 和 `ready_for_nonebot_run`；缺依赖时给出 `scripts/dev.ps1 install` 建议。不调用 LLM、不启动 NapCat、不发送消息、不显示 API key。 |
| `readiness-smoke` | 聚合基础 LLM 对话接入前的本地就绪状态。 | 优先读取 `.env`，没有则读取 `.env.example`；聚合 `doctor`、`config-smoke`、`context-smoke` 和本地静态聊天探针，输出 `readiness_status=ready|local_only|blocked`、`next_action`、`recommended_commands`、`ready_for_local_dialogue`、`ready_for_real_llm`、`context_ok`、`chat_pipeline_ok`、`chat_pipeline_mode=local_static_probe`、`real_llm_probe_performed=false`、LLM 就绪原因码和安全 `llm_fix_hints`；不调用真实 LLM、不启动 NapCat、不发送 QQ、不显示密钥、真实路径、prompt 或完整回复正文。 |
| `dialogue-smoke` | 本地验收一轮基础 LLM 对话。 | 优先读取 `.env`，没有则读取 `.env.example`；合并上下文摘要和聊天 pipeline 结果，输出 `dialogue_status=ready|local_only|blocked`、`next_action`、人格/知识来源安全指纹、情绪/记忆/历史/prompt 数字摘要、回复预算、`receipt_state`、`llm_status`、安全 `llm_error_kind`、LLM 就绪字段、安全 `llm_fix_hints`、`reply_preview_chars` 与 `reply_text_hidden=true`。默认 static provider 不联网；真实 provider 生成参数非法时显示 `fix_config/not_called` 且不调用 provider；真实 provider 调用出错时非零退出；不连接 NapCat、不发送 QQ、不显示完整回复、prompt、用户原文、知识原文、路径或密钥。 |
| `install` | 安装项目依赖。 | 如果存在 `uv` 就执行 `uv sync`，否则执行 `python -m pip install -e .`。 |
| `dev` | 启动本地开发机器人。 | 执行 `nb run`；如果没有 NoneBot CLI 会失败。 |
| `run` | 使用同一运行命令启动机器人。 | 目前等同于 `dev`，生产部署以后可以单独扩展。 |
| `docs-check` | 检查命令文档、契约文档、人格/知识库文档、媒体流水线文档、parser/render 锚点和关键配置指针。 | 文档和规格存在且包含必要锚点时通过。 |
| `plugin-check` | 检查 `plugins/` 是否已配置，并要求 `plugins/bot_unified_runtime` 存在。 | 缺少统一运行时插件会失败。 |
| `smoke` | 检查文档、插件配置、NoneBot import 和 `nb` CLI。 | 依赖未安装前会失败。 |
| `test` | 执行 `pytest`。 | 当前只收集项目自有 `tests/`，不会扫描 `research/` 下载源码。 |
| `lint` | 执行 `ruff check .`。 | 在 ruff 未安装时明确失败。 |
| `typecheck` | 执行 `mypy --explicit-package-bases --exclude research --ignore-missing-imports plugins tests`。 | 只检查项目自有插件和测试，不扫描 `research/` 下载源码；在 mypy 未安装时明确失败。 |
| `chat-smoke` | 本地跑一遍基础 LLM 对话链路。 | 优先读取 `.env`，没有则读取 `.env.example`；会经过人格/知识 provider、LLM provider、运行时 pipeline、内存发送队列和审计，并输出 `llm_status`、安全 `llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`reply_preview_chars` 与 `reply_text_hidden=true`。真实 provider 生成参数非法时会在调用 provider 前写入 `llm_preflight_blocked` 和 `llm_error:config_missing`；真实 provider 配置下出现其他 `llm_error` 会非零退出；该命令不连接 NapCat，不显示密钥、真实路径或完整回复正文。 |
| `config-smoke` | 本地检查基础对话和真实 LLM 接入配置是否就绪。 | 优先读取 `.env`，没有则读取 `.env.example`；只读检查人格/知识文件存在性、后缀、可解析性、空内容、人格材料强度、聊天开关、provider/model/base_url/API key、endpoint、base_url 是否为空/非法/含凭据、生成参数范围、回复限速、安静时间和持久化开关，并输出 `llm_readiness_status`、`llm_next_action`、原因码与安全 `llm_fix_hints`；不调用 LLM、不启动 NapCat、不显示密钥、人格正文或真实路径。 |
| `persona-smoke` | 本地检查守岸人人格材料和语气参数是否就绪。 | 优先读取 `.env`，没有则读取 `.env.example`；输出 `persona_status=ok|weak|blocked`、`persona_next_action`、人格/知识来源安全指纹、人格文件计数、可读性、字符数、有效行数、强度状态、风格规则/角色边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪三态和安全 `llm_fix_hints`；不调用 LLM、不启动 NapCat、不发送消息，不展示人格正文、知识正文、本机路径、prompt、用户原文或密钥。 |
| `context-smoke` | 本地构造人格、情绪、记忆、最近对话、知识和 chat prompt 诊断摘要。 | 优先读取 `.env`，没有则读取 `.env.example`；不会调用 LLM，不会启动 NapCat，也不会发送消息；用于确认守岸人人格、人格/知识来源安全指纹、情绪信号、知识 chunk、记忆事实、最近对话、回复预算、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections` 和分区预算/字符数是否正确进入上下文。 |
| `why-smoke` | 本地解释一条对话输入为什么会回复、为什么不回复、最多回复几条、有没有创建发送请求。 | 优先读取 `.env`，没有则读取 `.env.example`；会输出 policy、角色、回复预算、prompt 安全数字摘要、上下文计数、LLM 状态、安全 `llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、安全 `llm_usage_*`、`SendRequest` 创建状态、回执和审计标签；输出审查阻断、限速阻断、安静时间阻断、模型回复预算收口、人格/知识上下文读取失败、生成参数预检阻断和 `llm_error:<kind>` 会归一化为中文结论；预检阻断只展示稳定 `llm_preflight_error:<reason>` 原因码，并说明已在调用 provider 前阻断；上下文读取失败会说明已跳过 LLM；不启动 NapCat，不连接 QQ，不显示密钥或真实路径。 |
| `llm-setup` | 打印真实 LLM 接入清单。 | 优先读取 `.env`，没有则读取 `.env.example`；复用 `config-smoke` 的 LLM 就绪规则，输出 `llm_setup_status=needs_env_edit|blocked|ready_for_probe`、必填 `BOT_CHAT_*` 项、当前缺失或占位的安全键名、安全 `.env` 占位模板、下一步命令序列和人工步骤；不写 `.env`，不调用真实 LLM provider，不启动 NapCat，不发送 QQ，不显示 API key、真实路径、prompt、人格正文或知识正文。 |
| `llm-smoke` | 本地验证真实 LLM provider 配置和 OpenAI-compatible 连接。 | 优先读取 `.env`，没有则读取 `.env.example`；不会启动 NapCat，也不会向 QQ 发送消息；缺少真实 API key、model、base_url，base_url 非法/非 HTTP(S)/包含用户名密码，或 `temperature/max_tokens/timeout_seconds` 非法时不会发起网络调用；会打印 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、安全 `llm_fix_hints`、诊断调用参数、归一化且脱敏后的 `endpoint_url`，并用安全的 `error_kind` 区分配置、超时、鉴权、限流、HTTP、网络、schema 和空回复问题。 |
| `nonebot-smoke` | 本地验证 NoneBot / OneBot 依赖、统一运行时插件 metadata、统一运行时硬开关和当前人格/知识/记忆/历史/诊断/审计/回执/回复限速/安静时间/LLM 配置摘要。 | 优先读取 `.env`，没有则读取 `.env.example`；会输出 `runtime_enabled=true|false`、`rate_limit_enabled=true|false`、`quiet_hours_enabled=true|false`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、安全 `llm_fix_hints` 和安全的 store 摘要，不显示真实数据库路径；`runtime_enabled` 只表示 `BOT_RUNTIME_ENABLED` 硬开关，不代表当前进程是否被 `/bot pause` 软暂停；不会启动 NapCat，不会连接 QQ，也不会发送消息；依赖缺失、插件导入失败或缺少 OneBot V11 支持声明时非零退出。 |
| `startup-smoke` | 本地验证 NoneBot 初始化、OneBot adapter 注册、本地插件加载、handler 注册和 APScheduler 可访问性。 | 优先读取 `.env`，没有则读取 `.env.example`；在干净子进程里执行 `nonebot.init()`、注册 OneBot V11 adapter、加载 `plugins.bot_unified_runtime` 并统计 matcher / scheduler job，然后立即退出；不会执行 `nb run`，不会启动长驻服务，不连接 NapCat，不发送 QQ 消息，不显示 API key、数据库真实路径、目标 ID 或消息正文。 |
| `queue-smoke` | 本地验证发送队列 worker。 | 使用临时 SQLite 发送队列和 fake transport 跑一次 `drain_send_queue_once()`，输出 `checked/delivered/retryable_failed/final_failed`、队列状态计数、`processing` 租约计数、回执数和审计事件数；不会启动 NoneBot/NapCat，不连接 QQ，不展示目标 ID、正文、`dedupe_key`、数据库路径或 provider message id。 |
| `transport-smoke` | 本地验证 OneBot/NapCat 出站 transport 边界。 | 验证项目内 `sender.onebot` 可导入，构造 text/image/json/mixed/fallback/forward 样例，并用 fake bot 跑私聊、群聊和合并转发扩展 API 的 `send_onebot_v11` 回执映射；同时验证 `status/retcode/data.message_id` 解析和可重试/最终失败分类；不会启动 NoneBot/NapCat，不连接 QQ，不发送真实消息，不展示目标 ID、消息正文或 provider message id。 |
| `online-transport-smoke` | 只读检查当前运行态在线 bot 状态。 | 调用 NoneBot 的在线 bot 查询边界，统计 `online_bots_count`、`onebot_bots_count` 和 `send_capable`；不会构造 `SendRequest`，不会调用 `send_private_msg` / `send_group_msg`，不会发送 QQ 消息，也不会展示 bot id、目标 ID、正文或 provider message id。命令行环境未初始化 NoneBot 时会安全显示没有在线 bot 可检查。 |
| `console` | 控制台交互聊天（最小可执行程序）。 | 优先读取 `.env`，没有则读取 `.env.example`；走完整统一运行时流水线，默认 static provider 离线回复；配置 `openai_compatible` 后走真实模型。支持 `/help`、`/status`、`/why`、`/quit`，配置 `BOT_RUNTIME_PERSONA_NICKNAME` 后还支持 `/岸宝帮助` 等昵称别名；多轮历史默认保存在内存中（配置 SQLite 历史时自动持久化）。不连接 NapCat、不发送 QQ。带 `-Message "你好"` 时进入单轮非交互模式，回复成功退出码 0，否则非 0。 |
| `credential-smoke` | 本地检查 cookie/凭据健康。 | 优先读取 `.env`，没有则读取 `.env.example`；检查每个凭据引用的 `expires_at`（过期/临近过期/正常/未知），配置 `BOT_CREDENTIAL_PROBE_URLS` 后可用 `--probe` 在线探测（401/403 视为需要重新登录）；只输出 ref/kind/state/脱敏说明，绝不输出 cookie 值；存在需要重新登录的凭据时非零退出。 |
| `verify` | 当前阶段默认验证入口。 | 执行 `docs-check`、`plugin-check`、项目自有 `pytest`；ruff/mypy 可用时一起执行。 |

## 验证策略

`verify` 是当前仓库阶段的默认门禁。它不能假装缺失的检查已经通过。

- 缺少契约文档或配置指针会失败。
- 缺少统一运行时插件入口会失败。
- 当前已有 `tests/`，`verify` 会强制执行 `pytest`。
- 缺少 `ruff` 或 `mypy` 时，`verify` 只警告；但单独执行 `lint` 或 `typecheck` 必须失败。
- `smoke` 比 `verify` 更严格：它要求依赖和 NoneBot CLI 已安装。

推荐顺序：

1. 切换或激活 Python 环境后：先跑 `doctor`，确认当前 shell 看到的依赖。
2. 接真实 LLM 前：先跑 `llm-setup` 看安全 `.env` 清单，再跑 `readiness-smoke`，看 `next_action` 和 `recommended_commands`，再跑 `persona-smoke` 确认守岸人人格材料，再跑 `dialogue-smoke` 验收一轮本地对话；之后再决定是修环境、修配置、看上下文、跑本地聊天链路，还是继续 `llm-smoke`。
3. 实现前：先跑 `docs-check` 和 `verify`。
4. 依赖安装后：再跑 `smoke`。
5. 接真实 NapCat 前：先跑 `nonebot-smoke`，再跑 `startup-smoke`，再跑 `transport-smoke`，确认导入、初始化、handler 注册和出站消息段边界都能通过；启动真实 NoneBot/NapCat 后，再跑 `online-transport-smoke` 观察当前进程是否能看见在线 OneBot 风格 bot。
5. 创建测试后：`test` 应成为 `verify` 的强制部分。
6. 引入 lint/type 工具后：`lint` 和 `typecheck` 应进入 CI。

## 本地启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dev
```

当前命令包装的是 `nb run`。项目配置来自 `pyproject.toml`：

- `plugin_dirs = ["plugins"]`
- `builtin_plugins = ["echo"]`
- 适配器：OneBot V11、Console、Mail
- 支撑插件：status、apscheduler、localstore、alconna、filehost、orm、htmlkit

### LLM 对话配置

基础对话能力默认使用 `bot_chat_provider=static`，只返回未配置提示，不会访问外部网络。接入真实模型时，在 `.env` 或运行环境中配置 OpenAI-compatible 接口：

可以先复制 [.env.example](.env.example) 为 `.env`，再把 `BOT_CHAT_PROVIDER`、`BOT_CHAT_MODEL`、`BOT_CHAT_API_KEY` 和 `BOT_CHAT_BASE_URL` 改成你的模型服务配置。

```env
BOT_PERSONA_PROFILE_ID=shorekeeper
BOT_PERSONA_DISPLAY_NAME=守岸人
BOT_PERSONA_VERSION=2026-07-07
BOT_PERSONA_FILES=["C:/Users/LancyCelestia/Documents/AI智能体有关材料/鸣潮 AI智能体有关材料/守岸人人格设定.md","C:/Users/LancyCelestia/Documents/AI智能体有关材料/鸣潮 AI智能体有关材料/守岸人人格档案.md"]
BOT_KNOWLEDGE_FILES=["C:/Users/LancyCelestia/Documents/AI智能体有关材料/鸣潮 AI智能体有关材料/鸣潮库街区百科v2.md"]
BOT_KNOWLEDGE_MAX_CHUNKS=4
BOT_KNOWLEDGE_CHUNK_CHARS=900
BOT_TONE_MODE=private_chat
BOT_TONE_VOICE=soft
BOT_TONE_WARMTH=0.8
BOT_TONE_DIRECTNESS=0.4
BOT_TONE_MESSAGE_COUNT_LIMIT=1
BOT_REPLY_PRIVATE_DEFAULT_MAX_MESSAGES=1
BOT_REPLY_PRIVATE_SUPPORT_MAX_MESSAGES=2
BOT_REPLY_PRIVATE_DEEP_HELP_MAX_MESSAGES=3
BOT_REPLY_GROUP_MAX_MESSAGES=1
BOT_REPLY_RISK_MAX_MESSAGES=1
BOT_REPLY_DEFAULT_CONTEXT_BUDGET=2048
BOT_REPLY_SUPPORT_CONTEXT_BUDGET=2560
BOT_REPLY_DEEP_HELP_CONTEXT_BUDGET=3072
BOT_REPLY_GROUP_CONTEXT_BUDGET=2048
BOT_RATE_LIMIT_ENABLED=true
BOT_RATE_LIMIT_WINDOW_SECONDS=60
BOT_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS=60
BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS=6
BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS=4
BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS=0
BOT_RATE_LIMIT_BYPASS_ROLES=["admin"]
BOT_RATE_LIMIT_DB_PATH=
BOT_QUIET_HOURS_ENABLED=false
BOT_QUIET_HOURS_START=23:00
BOT_QUIET_HOURS_END=07:00
BOT_QUIET_HOURS_TIMEZONE=Asia/Hong_Kong
BOT_QUIET_HOURS_SESSION_TYPES=["group"]
BOT_QUIET_HOURS_BYPASS_ROLES=["admin"]
BOT_MEMORY_ENABLED=false
BOT_MEMORY_DB_PATH=data/bot_memory.sqlite3
BOT_MEMORY_MAX_ITEMS=5
BOT_MEMORY_MAX_CHARS=1200
BOT_HISTORY_ENABLED=false
BOT_HISTORY_DB_PATH=data/bot_history.sqlite3
BOT_HISTORY_MAX_TURNS=6
BOT_HISTORY_MAX_CHARS=1600
BOT_HISTORY_MAX_ITEMS=1000
BOT_DIAGNOSTICS_ENABLED=false
BOT_DIAGNOSTICS_DB_PATH=data/bot_diagnostics.sqlite3
BOT_DIAGNOSTICS_MAX_ITEMS=100
BOT_AUDIT_ENABLED=false
BOT_AUDIT_DB_PATH=data/bot_audit.sqlite3
BOT_AUDIT_MAX_ITEMS=1000
BOT_RECEIPTS_ENABLED=false
BOT_RECEIPTS_DB_PATH=data/bot_receipts.sqlite3
BOT_RECEIPTS_MAX_ITEMS=1000
BOT_SEND_QUEUE_ENABLED=false
BOT_SEND_QUEUE_DB_PATH=data/bot_send_queue.sqlite3
BOT_SEND_QUEUE_MAX_ITEMS=1000
BOT_SEND_QUEUE_MAX_ATTEMPTS=3
BOT_SEND_QUEUE_RETRY_BASE_SECONDS=30
BOT_SEND_QUEUE_RETRY_MAX_SECONDS=300
BOT_SEND_QUEUE_WORKER_ENABLED=false
BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS=30
BOT_SEND_QUEUE_WORKER_BATCH_SIZE=20
BOT_EMOTION_ENABLED=true
BOT_EMOTION_MAX_SIGNALS=4
BOT_CHAT_ENABLED=true
BOT_CHAT_PROVIDER=openai_compatible
BOT_CHAT_MODEL=your-model-name
BOT_CHAT_API_KEY=your-api-key
BOT_CHAT_BASE_URL=https://api.openai.com/v1
BOT_CHAT_TEMPERATURE=0.7
BOT_CHAT_MAX_TOKENS=512
BOT_CHAT_TIMEOUT_SECONDS=30
```

`BOT_CHAT_BASE_URL` 可以填写 OpenAI-compatible 根地址，例如 `https://api.openai.com/v1`，也可以填写完整接口地址，例如 `https://api.openai.com/v1/chat/completions`。运行时会归一化为最终请求用的 `endpoint_url`，避免把 `/chat/completions` 重复拼接。

接真实模型前建议先跑只读配置体检：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-setup
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 persona-smoke
```

`doctor` 先确认当前 PowerShell 的 Python 环境能否导入 NoneBot、OneBot V11、APScheduler、统一插件并找到 `nb` CLI；`llm-setup` 再把当前真实模型接入状态翻译成可执行清单，包含 `safe_env_template`、`required_env_keys`、`missing_or_placeholder_env_keys` 和 `next_commands`。`llm-setup` 只读，不写 `.env`、不调用真实 provider、不连接 NapCat、不发送 QQ，也不会显示密钥、路径、prompt 或人格正文。`readiness-smoke` 再把环境、配置、上下文构造和本地基础聊天链路合并成一个安全摘要。`readiness-smoke` 不调用真实 LLM provider，不启动 NoneBot/NapCat，不发送 QQ；它使用 `chat_pipeline_mode=local_static_probe` 验证 `IncomingMessage -> ... -> SendRequest -> DeliveryReceipt` 本地链路，并固定输出 `real_llm_probe_performed=false`。`config-smoke` 再检查项目配置。`config-smoke` 不调用 LLM、不启动 NoneBot/NapCat，也不会发送消息。它会检查聊天开关、人格文件是否存在且后缀受支持、人格文件是否可解析且非空、人格材料是否过薄、知识文件是否缺失/损坏/为空、`BOT_CHAT_PROVIDER` 是否仍是 `static`、`openai_compatible` 是否缺少真实 API key、模型名或 base_url、base_url 是否无法解析/非 HTTP(S)/误带用户名密码、回复限速是否启用及其窗口/全局/会话/发送者上限、同一目标最小回复间隔，以及安静时间是否启用、时间窗口、时区、作用会话类型和绕过角色，并输出 `ready_for_real_llm=true|false`、`llm_readiness_status=ready|local_only|blocked`、`llm_next_action=fix_config|configure_real_llm|llm_smoke`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、安全 `endpoint_url`、`chat_api_key=set|missing`、`persona_readable/empty/unreadable`、`persona_total_chars`、`persona_meaningful_lines`、`persona_strength_status=ok|weak|missing`、`knowledge_readable/empty/unreadable`、`rate_limit_store=memory|sqlite`、`rate_limit_db=set|missing`、`rate_limit_*` 和 `quiet_hours_*` 摘要。`persona-smoke` 进一步聚焦人格自检，确认 `PersonaProfile` 和 `ToneProfile` 能由当前配置构造出来，并展示安全来源指纹与规则计数。`openai_base_url_missing`、`openai_base_url_invalid` 和 `openai_base_url_unsafe` 都是阻断错误；其中 `unsafe` 表示 URL 内含用户名/密码，输出会把凭据替换为 `[redacted]`。`ready` 表示真实 OpenAI-compatible provider 关键配置已具备且没有阻断错误，`local_only` 表示当前只能验证本地 pipeline，`blocked` 表示必须先处理 `errors`；`llm_next_action` 分别表示先修配置、配置真实模型，或继续跑 `llm-smoke`；`llm_readiness_reasons` 是去重后的 errors + warnings；`llm_fix_hints` 是从这些原因码映射出的安全修复提示，优先根据阻断错误生成，没有错误时再根据 warning 给下一步配置建议。`static` provider 会作为 warning 保留，因为它仍可用于本地 pipeline 验证，但不代表真实 LLM 已接通；人格材料过薄会作为 `persona_profile_weak` warning，提示真实模型更容易人格漂移。`llm_fix_hints` 只输出参数名、推荐范围和占位值，例如 `BOT_CHAT_API_KEY=<real_api_key>`，不能输出真实 key、真实路径、prompt、用户原文或 provider 原始错误。

真实机器人运行时，管理员可以用 `/bot readiness` 查看同源统一就绪摘要。它复用本地 `readiness-smoke` 的安全字段，展示 `readiness_status`、`next_action`、`recommended_commands`、本地对话/真实 LLM/环境/config/context/chat/NoneBot/transport 状态、`chat_pipeline_mode=local_static_probe`、`real_llm_probe_performed=false`、当前进程 `runtime_soft_paused=true|false`、安全 reason、`updated_by=set|missing`、LLM 就绪原因码和安全 `llm_fix_hints`；它不调用真实 LLM、不连接 NapCat、不发送外部业务消息，也不会覆盖最近一次业务诊断。

真实机器人运行时，管理员可以用 `/bot config` 查看同类只读配置体检摘要。它不调用 LLM、不连接 NapCat、不发送外部业务消息，只展示安全白名单字段，例如 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格/知识文件计数、可解析性计数、人格字符数/有效行数/强度状态、provider/model、`endpoint_url` 和 `chat_api_key=set|missing`。

权限角色首版通过 `.env` 参数配置：

```env
BOT_ADMIN_USER_IDS=["10001"]
BOT_ENTERPRISE_USER_IDS=20001,20002
BOT_TRUSTED_USER_IDS=30001;30002
BOT_BLOCKED_USER_IDS=40001
```

这些值只填平台 user_id，不填昵称；支持 JSON 数组、英文逗号或分号。运行时会把角色注入 `IncomingMessage.sender_roles -> PolicyEvaluation.actor_roles -> BotDecision.actor_roles`。拉黑用户会在 policy 阶段被挡住；管理员、企业和可信用户先进入审计标签，后续高风险能力可以继续按这些角色做确认和放行规则。`/bot status`、`/bot roles` 与 `nonebot-smoke` 只显示数量、角色顺序、绕过规则和输入格式，不显示具体 ID。

群命令前缀使用 `BOT_RUNTIME_GROUP_COMMAND_PREFIX`。如果你把它改成 `!`，群里就应使用 `!status` 一类命令；旧的 `/bot status` 在未提及机器人时会按普通群消息观察，不进入能力链路。

`BOT_PERSONA_FILES` 和 `BOT_KNOWLEDGE_FILES` 支持 `.md`、`.txt` 和 `.docx` 文件，路径可以写成两种格式：

```env
BOT_PERSONA_FILES=["C:/path/a.md","C:/path/b.txt","C:/path/c.docx"]
BOT_PERSONA_FILES=C:/path/a.md;C:/path/b.txt;C:/path/c.docx
```

消息参数流是：`IncomingMessage -> FileCharacterContextProvider -> ContextBundle -> build_chat_prompt -> LLMProvider -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest`。其中 `ContextBundle` 会携带 `persona`、`tone`、`emotion_signals`、`memory_results`、`conversation_history` 和 `knowledge_results`。能力层不能直接调用 NoneBot 或 NapCat 发送 API。

基础对话已经接入 `ReplyBudgetSettings`。默认普通私聊最多 1 条；私聊里明显需要安慰、陪伴时最多 2 条；“一步一步/详细/教我/排查”这类深度帮助最多 3 条；群聊和中高风险输入会强制压回 1 条。对应上限和 prompt 上下文预算都可以通过 `BOT_REPLY_*` 参数调整，最终会写入 `BotDecision.max_messages`、`BotDecision.context_budget`、`SendRequest.max_messages` 和 `reply_budget:*` 审计标签。

基础对话已经接入调用 LLM 前的窗口限速。默认 `BOT_RATE_LIMIT_WINDOW_SECONDS=60`，全局在窗口内最多消耗 60 个聊天回复预算，同一会话最多消耗 6 个聊天回复预算，同一发送者最多消耗 4 个聊天回复预算；深度求助这类 `max_messages=3` 的请求会按 3 个预算计数。命中后会在 policy 阶段返回 `rate_limited`，不会调用 LLM，不会创建 `SendRequest`；`BOT_RATE_LIMIT_BYPASS_ROLES=["admin"]` 默认允许管理员绕过。未配置 `BOT_RATE_LIMIT_DB_PATH` 时使用进程内限速；配置该路径后使用 SQLite 持久限速，重启后仍保留窗口内记录。`BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` 用于限制同一目标的最小回复间隔，默认 `0` 为关闭；建议群聊实测稳定后设置为 `2` 到 `5` 秒，避免同一群被连续刷屏。

基础对话也已经接入调用 LLM 前的安静时间策略。默认 `BOT_QUIET_HOURS_ENABLED=false`，不会影响当前对话；启用后按 `BOT_QUIET_HOURS_START`、`BOT_QUIET_HOURS_END` 和 `BOT_QUIET_HOURS_TIMEZONE` 判断本地时间，默认只作用于 `BOT_QUIET_HOURS_SESSION_TYPES=["group"]`，避免午夜群聊刷屏。命中后会在 policy 阶段返回 `quiet_hours`，不会调用 LLM，不会创建 `SendRequest`；`BOT_QUIET_HOURS_BYPASS_ROLES=["admin"]` 默认允许管理员绕过。若你希望私聊夜间也静默，可以把 `BOT_QUIET_HOURS_SESSION_TYPES` 改成 `["group","private"]`。

真实模型输出还会在 `bot.chat` 能力层按回复预算做二次收口。模型如果返回多个空行分隔的回复块，系统只保留 `max_messages` 允许的前几块，并写入 `llm_output_trimmed` 审计标签；`why-smoke` 和 `/bot why` 会把它解释成“已按回复预算收口，只保留前 N 段”。这用于防止模型无视 prompt 后一次性输出多段刷屏内容，也让管理员能解释为什么最终输出比模型原始回复短。

基础输出审查会在发送前拦截内部上下文标记和明显密钥形态，例如 `[UNTRUSTED_USER_TEXT]`、`api_key=...`、`token=...`、`cookie=...`、`authkey=...`、`Authorization: Bearer ...` 或 `sk-...`。`bot.chat` 还会拦截自称 ChatGPT/OpenAI/AI 语言模型、拒绝守岸人身份或否认角色人格的输出，并在审计原因里记录 `persona drift`。这一步发生在 `ReviewResult`，通过后才会进入 `RenderedOutput -> SendRequest`；纯人格漂移阻断会返回守岸人风格的安全兜底提示，但不会把原始模型回复变成 `SendRequest`。被阻断后，`/bot why` 和 `why-smoke` 只展示 `review_blocked`、`persona_drift` 或 `unsafe_output_leakage` 等安全标签，不展示原始模型回复。

本地记忆首版通过 `SQLiteMemoryRepository` 读取 `memory_facts` 表，配置 `BOT_MEMORY_ENABLED=true` 和 `BOT_MEMORY_DB_PATH` 后，同一用户/会话作用域内的事实会进入 `MemoryRetrievalResult`，再被 prompt 作为不可信事实使用。每条事实会带 `sensitivity=public|group|personal|credentialed` 和 `scope_key`；默认是 `personal` 与当前 `session:<session_id>`。它不会直接发送消息，也不会替代权限、隐私和审计判断。

最近对话首版通过 `SQLiteConversationHistoryRepository` 读取 `conversation_turns` 表，配置 `BOT_HISTORY_ENABLED=true` 和 `BOT_HISTORY_DB_PATH` 后，同一 platform/adapter/bot/session/sender 作用域内的最近轮次会进入 `ConversationHistoryResult`，再被 prompt 作为不可信上下文使用。`BOT_HISTORY_MAX_TURNS` 和 `BOT_HISTORY_MAX_CHARS` 控制每次最多读取多少轮、多少字符进入 prompt；`BOT_HISTORY_MAX_ITEMS` 控制同一作用域在 SQLite 中最多保留多少条历史，默认 1000，追加新轮次后会自动清理该作用域更旧记录，不影响其他用户、会话、bot 或 adapter。NoneBot 文本聊天入口只在统一运行时生成 `SendRequest` 后记录用户消息，并在 OneBot/NapCat 文本 transport 成功后记录助手回复；默认关闭，避免未确认前自动采集聊天历史。管理员可用 `/bot history clear` 清理当前会话、当前发送者、当前机器人实例的最近对话历史，用来移除污染上下文或注入残留；它不影响 `/bot memory` 管理的长期记忆，也不展示历史正文、会话 ID、用户 ID 或数据库路径。

运行诊断首版默认使用进程内最近记录。配置 `BOT_DIAGNOSTICS_ENABLED=true` 和 `BOT_DIAGNOSTICS_DB_PATH` 后，`/bot why` 使用的脱敏 `RuntimeDiagnostic` 会写入 SQLite `runtime_diagnostics` 表；`BOT_DIAGNOSTICS_MAX_ITEMS` 控制最多保留多少条最近记录，避免数据库无限增长。诊断表只保存排障字段，不保存原始用户消息、回复全文、`private_debug`、目标 ID、API key、token、cookie 或 OneBot provider message id。

如果同时启用 SQLite 发送队列，运行诊断会优先通过队列的内部 `find_request(request_id)` 查找已持久化 `SendRequest`。这让 `/bot why <request_id>` 在进程重启或队列对象重开后，仍能安全判断本次业务是否创建过发送请求；输出仍只展示 `send_request_created`、回执状态和中文结论，不展示目标 ID、正文、`dedupe_key`、数据库路径或 provider message id。

审计、发送回执和发送队列默认也使用进程内 store。配置 `BOT_AUDIT_ENABLED=true` 和 `BOT_AUDIT_DB_PATH` 后，`AuditRecord` 会写入 SQLite `audit_records` 表；配置 `BOT_RECEIPTS_ENABLED=true` 和 `BOT_RECEIPTS_DB_PATH` 后，`DeliveryReceipt` 会写入 SQLite `delivery_receipts` 表；配置 `BOT_SEND_QUEUE_ENABLED=true` 和 `BOT_SEND_QUEUE_DB_PATH` 后，`SendRequest` 会写入 SQLite `send_requests` 表。发送队列负责请求去重、原子认领到期待发送项、失败后按退避时间重试，并在 `BOT_SEND_QUEUE_MAX_ATTEMPTS` 后封顶为最终失败；`SQLiteSendRequestQueue.claim_due()` 会把到期请求切到内部 `processing` 租约状态，租约过期后可再次认领，避免并发 worker 重复投递或请求永久卡住。`drain_send_queue_once()` 是当前代码层一次性 worker，优先使用 `claim_due()`，再调用注入的 transport、记录回执并更新队列状态。后台 APScheduler worker 默认关闭；只有 `BOT_SEND_QUEUE_WORKER_ENABLED=true` 且当前队列是可 drain 的 SQLite 队列时，NoneBot 入口才会注册 `bot_send_queue_worker`，按 `BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS` 间隔、每批最多 `BOT_SEND_QUEUE_WORKER_BATCH_SIZE` 条推进到期请求。没有在线 bot 时，worker 会返回可重试失败，不会崩溃或刷屏。`queue-smoke` 会用临时 SQLite 队列和 fake transport 验证这条 worker 链路，不连接 NapCat，也不会真实发送 QQ 消息。`/bot status`、`/bot queue`、`config-smoke`、`nonebot-smoke` 和 `queue-smoke` 只显示 `enabled/disabled`、`store=memory|sqlite`、`db=set|missing`、状态计数、`processing` 租约计数、`max_items`、`max_attempts`、退避秒数或 worker 计数，不显示数据库真实路径、目标 ID、原始消息、`dedupe_key` 或 OneBot provider message id。

SQLite 发送队列还提供只读 `find_request(request_id)`。它只供运行时内部恢复 `SendRequest` 诊断投影和测试使用，不是管理员列表接口；任何命令、smoke 或状态摘要都不能借此输出持久化正文、目标、去重键或 provider message id。

情绪感知首版通过 `RuleBasedEmotionProvider` 生成 `EmotionSignal`。配置 `BOT_EMOTION_ENABLED=true` 后，系统会识别低落/需要陪伴、孤独、疲惫、挫败和教程/排查求助等信号；`BOT_EMOTION_MAX_SIGNALS` 控制最多注入多少条。情绪信号只影响语气和回答顺序，不是医学诊断，不写长期数据库，不能创建 `SendRequest`，也不能绕过回复预算。

可以通过 `/bot memory` 管理当前用户/会话的手动记忆：

```text
/bot memory add 用户喜欢鸣潮和安静的陪伴式回复
/bot memory add --sensitivity=group 这个群喜欢简短的鸣潮活动提醒
/bot memory list
/bot memory delete fact_xxxxxxxxxxxx
/bot history clear
```

这些命令只写入、读取或删除当前用户/当前会话作用域内的 `memory_facts`；未启用 `BOT_MEMORY_ENABLED=true` 时会拒绝写入。`memory add` 默认写入 `sensitivity=personal`，可以用 `--sensitivity=public|group|personal|credentialed` 显式标注敏感度。群聊中的 `/bot memory list` 只展示 `public` / `group` 记忆；`personal` 和 `credentialed` 正文不会发到群里，没有可公开记忆时只返回“请在私聊中查看个人记忆”一类的安全提示。

`ContextBundle.context_budget` / `BotDecision.context_budget` 已经接入 `build_chat_prompt`。prompt 会保留人格名称、人格身份、安全边界和用户消息，对角色边界、说话风格、禁止行为、情绪信号、记忆、最近对话和知识分区裁剪；被裁剪时会写入“内容已按上下文预算裁剪”提示。内部 `build_chat_prompt_with_diagnostics` 会同时返回安全诊断字段，包括分区预算、分区字符数、总 prompt 字符数、剩余预算、是否整体裁剪和被裁剪分区；这些字段只包含数字和分区名，不包含 prompt 原文。

当前本地人格/知识文件支持 `.md`、`.txt` 和 `.docx`。`.docx` 会由独立 document loader 从 Word XML 中抽取正文，再转成 `PersonaProfile` 或 `KnowledgeChunk`；不要让 LLM 直接读取或猜测未解析文件。

配置好后可以先跑本地对话烟测：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dialogue-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dialogue-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 chat-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"
```

如果你只是想确认 `.env` 还差哪些 LLM 项，可以单独跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-setup
```

`llm-setup` 的 `llm_setup_status` 有三种：`needs_env_edit` 表示本地 pipeline 可跑但还需要填写真实模型配置；`blocked` 表示现有配置存在阻断错误，先看 `llm_fix_hints`；`ready_for_probe` 表示关键配置已具备，下一步先跑 `llm-smoke`，再跑 `dialogue-smoke`。它只输出占位模板和命令序列，不写文件、不联网、不发送消息。

`dialogue-smoke` 更适合做“我发一句话后基础聊天能不能跑”的验收。它会同时展示人格/知识来源安全指纹、情绪/记忆/历史/prompt 数字摘要、回复预算、LLM 状态、回执、下一步动作、安全 `llm_fix_hints` 和 `reply_text_hidden=true`；默认 `static` provider 不联网，真实 `openai_compatible` provider 调用失败时会非零退出。它不会启动 NapCat，也不会真实向 QQ 发送消息；不打印完整回复、prompt、用户原文、知识原文、真实路径、数据库路径或密钥。

`chat-smoke` 只在本机验证“读取人格/知识文件 -> 构造 LLM 对话能力 -> 进入统一运行时 -> 生成 `SendRequest` -> 内存 sender 记录 `DeliveryReceipt/AuditRecord`”这条链路。输出中的 `llm_status` 会区分 `ok`、`not_configured` 和 `error`：默认 `static` provider 是 `not_configured` 但仍允许 pipeline smoke 通过；配置 `openai_compatible` 后如果模型调用失败，或模型成功返回但文本为空白，会显示 `llm_status=error` 与 `llm_error_kind=<kind>` 并非零退出；用户侧回复会使用守岸人风格兜底，空白回复会归类为 `empty_response`，不会继续发送空文本或机械 debug 文案。`chat-smoke` 只输出 `reply_preview_chars` 和 `reply_text_hidden=true`，不打印完整回复正文，避免把真实模型回复、记忆或知识内容写进终端日志。若这个命令因为文件缺失或模型配置问题失败，先跑 `config-smoke` 会更快定位是配置问题还是运行时问题。

如果只想确认人格文件、语气参数和安全来源指纹是否正确加载，不想调用模型，可以先跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 persona-smoke
```

`persona-smoke` 会输出人格 id、显示名、版本、`persona_status=ok|weak|blocked`、`persona_next_action`、`persona_source_refs`、`knowledge_source_refs`、人格文件计数、可读性、字符数、有效行数、`persona_strength_status`、风格规则数量、角色边界数量、禁止行为数量、语气参数、记忆/历史/情绪开关、LLM 就绪状态和安全 `llm_fix_hints`。它不构造完整 prompt，不调用 LLM，不启动 NoneBot/NapCat，也不会发送消息；不会展示本机路径、文件名、人格正文、知识正文、prompt、用户原文、数据库路径或密钥。

如果还要确认人格、记忆、知识和 prompt 是否正确进入上下文，不想调用模型，可以继续跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke -Message "请你一步一步教我怎么配置 NoneBot 和 NapCat"
```

`context-smoke` 会输出人格 id、人格/知识来源安全指纹 `persona_source_refs` 和 `knowledge_source_refs`、风格规则数量、角色边界数量、禁止行为数量、知识 chunk 数、记忆事实数、最近对话轮数、情绪信号数量和标签、prompt 消息数、上下文预算、最多回复条数、`system_prompt_chars`、`user_prompt_chars`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`prompt_section_budgets` 和 `prompt_section_chars`。来源指纹只用于确认文件或知识来源是否加载、是否发生变化；不会展示本机路径、文件名、知识正文、数据库路径、prompt 原文或密钥。它不会调用 LLM，不会启动 NoneBot/NapCat，也不会发送消息。这个命令适合在替换人格文件、加入 DOCX 或接真实模型前排查“上下文摘要是否正确”和“预算花在哪些分区”。

真实机器人运行时，管理员可以用 `/bot context [测试文本]` 查看当前会话的 LLM 上下文安全摘要。它会展示人格 id、人格名、版本、`persona_source_refs`、`knowledge_source_refs`、风格/边界/禁止行为计数、知识 chunk 数和来源数、记忆事实数、最近对话轮数、情绪信号标签、回复预算、prompt 消息数、prompt 长度、总字符数、剩余预算、是否整体裁剪、被裁剪分区和各分区预算/字符数；不会调用 LLM，不展示原始测试文本、完整 prompt、知识原文、数据库路径、API key、token、cookie、目标 ID、真实文件路径、文件名或 OneBot provider message id。

如果想解释“为什么会回复、为什么不回复、为什么最多回复几条”，可以跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 why-smoke
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 why-smoke -Message "今天真的很难受，可以陪我慢慢说说吗？"
```

`why-smoke` 会输出 `policy_allowed`、`policy_reason`、`actor_roles`、`reply_budget_reason`、`max_messages`、`context_budget`、`prompt_messages`、`system_prompt_chars`、`user_prompt_chars`、`prompt_total_chars`、`prompt_budget_remaining`、`prompt_clipped`、`prompt_truncated_sections`、`knowledge_chunks`、`memory_facts`、`history_turns`、`emotion_signals`、`llm_status`、`llm_error_kind`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_usage_prompt_tokens`、`llm_usage_completion_tokens`、`llm_usage_total_tokens`、`send_request_created`、`receipt_state`、`audit_tags` 和 `why_summary`。它会走本地统一运行时和内存发送队列，但不会启动 NoneBot/NapCat，也不会真实发 QQ 消息。这个命令适合排查限速阻断、安静时间阻断、刷屏、上下文过大、prompt 分区裁剪、人格/知识上下文读取失败且跳过 LLM、模型 token 用量异常、模型多段回复被 `llm_output_trimmed` 收口、生成参数非法导致的 `llm_preflight_blocked`、真实 provider 出现 `llm_error:timeout` / `llm_error:auth` / `llm_error:schema` / `llm_error:empty_response` 等调用失败或空回复、群聊误触发、拉黑用户、运行时暂停、真实 LLM 配置未就绪、LLM 未配置、人格漂移和输出泄漏审查阻断等问题。

真实机器人运行时可用：

```text
/bot why
/bot why <request_id>
/bot why <debug_id>
```

`/bot why` 默认查询当前会话最近一次真实运行记录；带 `request_id` 或 `debug_id` 时查询指定记录。它读取脱敏 `RuntimeDiagnostic`，展示能力、策略原因、角色、回复预算、prompt 安全数字摘要、上下文计数、LLM 状态、`llm_error_kind`、LLM 就绪三态、就绪原因码、安全 `llm_usage_*`、发送请求、回执、审计事件、审计标签和一句结论；人格漂移或输出泄漏类 review 阻断会显示安全标签和中文原因，`llm_output_trimmed` 会显示模型输出已按回复预算收口，`llm_error:<kind>` 会显示 “LLM 调用失败，错误类型是 <kind>”，`llm_preflight_blocked` 会显示“LLM 生成参数或配置非法，已在调用 provider 前阻断”并只列出稳定 `openai_*_invalid` 原因码，`llm_readiness_status=local_only|blocked` 会说明真实模型配置仍未完全就绪，`rate_limited` 会显示已在调用 LLM 前阻断以避免刷屏，`quiet_hours` 会显示已在调用 LLM 前阻断以避免夜间刷屏。它不会展示原始用户消息、回复全文、完整 prompt、知识原文、最近对话原文、`private_debug`、API key、token、cookie、目标 ID、真实文件路径、原始模型输出、原始 provider 错误或 OneBot provider message id。默认该记录只保存在当前进程内；配置 `BOT_DIAGNOSTICS_ENABLED=true` 和 `BOT_DIAGNOSTICS_DB_PATH` 后会写入 SQLite，`BOT_DIAGNOSTICS_MAX_ITEMS` 控制最多保留多少条最近记录。

需要绕过 PowerShell 包装时，也可以直接运行：

```powershell
python -m plugins.bot_unified_runtime.smoke context --message "今天真的很难受，可以陪我慢慢说说吗？"
python -m plugins.bot_unified_runtime.smoke chat --message "请你一步一步教我怎么配置 NoneBot 和 NapCat"
python -m plugins.bot_unified_runtime.smoke why --message "今天真的很难受，可以陪我慢慢说说吗？"
```

配置真实模型后，可以单独跑模型连接诊断：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke
```

`llm-smoke` 只在 `openai_compatible` provider 的 API key、model、安全 base_url 和生成参数都具备时发送一条短诊断 prompt；否则只输出安全预检结果，不触发 provider。它会打印 provider、model、base_url 状态、脱敏 `endpoint_url`、api_key=set/missing、`diagnostic_temperature`、`diagnostic_max_tokens`、`timeout_seconds`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、错误类型和短回复预览。空 base_url、非 HTTP(S) base_url、无法解析的 base_url 或带用户名/密码的 base_url 都会在联网前被拒绝；例如 `https://user:raw-password@llm.example/v1` 只会显示为 `https://[redacted]@llm.example/v1/chat/completions`，并给出 `remove_credentials_from_BOT_CHAT_BASE_URL`。`BOT_CHAT_TEMPERATURE` 必须在 0.0 到 2.0 之间，`BOT_CHAT_MAX_TOKENS` 必须大于等于 1，`BOT_CHAT_TIMEOUT_SECONDS` 必须大于 0；非法时原因码分别是 `openai_temperature_invalid`、`openai_max_tokens_invalid` 和 `openai_timeout_seconds_invalid`，修复提示分别是 `BOT_CHAT_TEMPERATURE=0.0..2.0`、`BOT_CHAT_MAX_TOKENS>=1` 和 `BOT_CHAT_TIMEOUT_SECONDS>0`。诊断短调用会把 temperature 收口到不超过 0.3、max_tokens 收口到不超过 128。它不会打印 API key，也会脱敏 provider 错误里的 `api_key=`、`token=` 等字段。当前 `error_kind` 包括 `provider_not_configured`、`config_missing`、`timeout`、`auth`、`rate_limited`、`server`、`http`、`network`、`schema`、`empty_response` 和 `provider_error`。这个命令只证明模型接口可用，不证明 NoneBot/NapCat 投递成功。

真实机器人运行时，管理员可以用：

```text
/bot llm
```

`/bot llm` 会从 NoneBot 入口走统一运行时 pipeline，执行一次短 LLM provider 连接诊断，并返回 `ok`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`provider`、`model`、`endpoint_url`、`api_key=set|missing`、`diagnostic_temperature`、`diagnostic_max_tokens`、`timeout_seconds`、`error_kind`、`reply_preview_chars`、`usage_total_tokens` 和 `public_message`。它只允许管理员使用；非管理员不会触发 provider。缺少真实 API key、model、base_url、仍使用 `your-api-key` 占位符或生成参数非法时不会发起网络调用。输出不会包含 API key、Authorization/Bearer、完整模型回复、原始上游错误、目标 ID 或 provider message id。`llm_fix_hints` 只包含参数名、推荐范围和占位值，不含真实密钥、路径或上游错误正文。`error_kind` 与 `llm-smoke` 保持一致，用于在线区分配置缺失、超时、鉴权、限流、HTTP、网络、schema 和空回复等问题。该命令用于在线确认真实机器人当前看到的 LLM 配置，不证明 NapCat 投递成功。

```text
/bot setup llm
```

`/bot setup llm` 会从 NoneBot 入口走统一运行时 pipeline，复用本地 `llm-setup` 的真实模型接入清单，返回 `llm_setup_status`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`required_env_keys`、`missing_or_placeholder_env_keys`、`safe_env_template`、`next_commands`、`manual_steps` 和安全布尔字段。它只允许管理员使用；非管理员不会看到配置状态。该命令只读，不写 `.env`，不调用真实 LLM provider，不连接 NapCat，不发送 QQ，也不会展示 API key、Authorization/Bearer、本机路径、prompt、人格正文、知识正文、目标 ID、provider message id 或 `private_debug`。它用于在线告诉你“下一步应该填哪些 `BOT_CHAT_*` 参数、再跑哪些验证命令”，不证明模型接口或 NapCat 投递已经成功。

```text
/bot config
```

`/bot config` 会从 NoneBot 入口走统一运行时 pipeline，复用 `config-smoke` 的配置体检逻辑，返回 `ok`、`ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons`、`llm_fix_hints`、`errors`、`warnings`、人格/知识文件计数、可解析性计数、人格字符数、有效行数、强度状态、记忆/历史/情绪/回复限速/安静时间/诊断/审计/回执/发送队列开关、`history_max_items`、`rate_limit_store=memory|sqlite`、`rate_limit_db=set|missing`、`rate_limit_chat_global_max_requests`、`rate_limit_chat_session_max_requests`、`rate_limit_chat_sender_max_requests`、`rate_limit_target_min_interval_seconds`、`quiet_hours_*`、`send_queue_store=memory|sqlite`、`send_queue_db=set|missing`、`send_queue_max_items`、`send_queue_max_attempts`、`send_queue_retry_*`、`send_queue_worker_enabled`、`send_queue_worker_interval_seconds`、`send_queue_worker_batch_size`、`chat_provider`、`chat_model`、`chat_api_key=set|missing`、`endpoint_url`、`chat_temperature`、`chat_max_tokens` 和 `timeout_seconds`。它只允许管理员使用；不会调用 LLM provider，不会启动或连接 NapCat，不会发送外部业务消息，也不会展示 API key、数据库真实路径、人格正文、目标 ID、provider message id 或原始错误。

```text
/bot readiness
```

`/bot readiness` 会从 NoneBot 入口走统一运行时 pipeline，复用 `readiness-smoke` 的聚合就绪逻辑，返回 `ok`、`readiness_status=ready|local_only|blocked`、`next_action`、`recommended_commands`、`runtime_soft_paused=true|false`、`runtime_soft_pause_reason=<safe>`、`runtime_soft_pause_updated_by=set|missing`、`ready_for_local_dialogue`、`ready_for_real_llm`、`real_llm_probe_performed=false`、`doctor_ok`、`ready_for_local_llm_smoke`、`ready_for_nonebot_run`、`nonebot_ok`、`transport_ok`、`config_ok`、`context_ok`、`chat_pipeline_ok`、`chat_pipeline_mode=local_static_probe`、`chat_receipt_state`、`chat_reply_preview_chars`、LLM 就绪三态、`llm_fix_hints`、人格强度和知识可读计数等安全摘要。它只允许管理员使用；不会调用真实 LLM provider，不会启动或连接 NapCat，不会发送外部业务消息，不展示完整回复、prompt、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id 或原始上游错误。

```text
/bot dialogue [测试文本]
```

`/bot dialogue [测试文本]` 会从 NoneBot 入口走统一运行时 pipeline，复用 `dialogue-smoke` 的一轮对话验收逻辑，返回 `dialogue_status=ready|local_only|blocked`、`next_action`、`context_ok`、`chat_pipeline_ok`、`receipt_state`、人格/知识来源安全指纹、情绪/记忆/历史/prompt 数字摘要、回复预算、LLM 状态、安全 `llm_error_kind`、LLM 就绪字段、`llm_fix_hints`、`reply_preview_chars` 和 `reply_text_hidden=true`。它只允许管理员使用；真实 `openai_compatible` provider 配置完整时可能短调用模型做验收，但不会展示模型回复正文、原始测试文本、完整 prompt、知识原文、真实路径、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id 或原始 provider 错误；该命令自身不会覆盖 `/bot why` 使用的最近业务诊断记录。

```text
/bot roles
```

`/bot roles` 会从 NoneBot 入口走统一运行时 pipeline，展示当前权限角色规则矩阵：`role_order=user,trusted,enterprise,admin,blocked`、`admin_users`、`enterprise_users`、`trusted_users`、`blocked_users`、`blocked_policy=policy_stage_block_before_llm`、限速/安静时间绕过角色、群命令前缀、`id_input_formats=json_array,comma,semicolon`、角色来源配置项和管理员命令集合。它只允许管理员使用；不会调用 LLM、不连接 NapCat、不发送外部业务消息，也不会展示任何具体 user_id、`session_id`、目标 ID、数据库路径、`provider_message_id` 或 `private_debug`。

```text
/bot persona
```

`/bot persona` 会从 NoneBot 入口走统一运行时 pipeline，复用 `persona-smoke` 的人格自检逻辑，展示 `persona_status`、`persona_next_action`、人格 id/显示名/版本、`persona_source_refs`、`knowledge_source_refs`、人格文件计数、可读性、字符数、有效行数、强度状态、风格/边界/禁止行为计数、语气参数、记忆/历史/情绪开关、LLM 就绪字段和安全 `llm_fix_hints`。它只允许管理员使用；不会调用 LLM、不连接 NapCat、不发送外部业务消息，不展示人格正文、知识正文、完整 prompt、真实路径、文件名、数据库路径、API key、Authorization/Bearer、目标 ID、provider message id 或 `private_debug`；该命令自身不会覆盖 `/bot why` 使用的最近业务诊断记录。

```text
/bot pause
/bot resume
```

`/bot pause` 和 `/bot resume` 会从 NoneBot 入口走统一运行时 pipeline，控制当前进程的运行时软暂停。`pause` 后普通聊天、自动发送预览和非排障能力会在 policy 前被阻断，返回“统一运行时已暂停”，不调用 LLM、不创建 `SendRequest`；`status`、`why`、`receipt`、`audit`、`recent`、`queue`、`context`、`llm`、`config`、`readiness`、`dialogue`、`roles`、`history clear` 和 `resume` 仍可用。它只允许管理员使用；非管理员拒绝且不泄露当前暂停状态。输出只展示 `runtime_paused`、安全 reason 和 `updated_by=set|missing`，不展示具体 user_id、`session_id`、目标 ID、数据库路径或 `private_debug`。该状态不写入 `.env`，重启后按 `BOT_RUNTIME_ENABLED` 和默认软状态重新开始。

配置真实模型或真实 NapCat 前，可以先跑本地 NoneBot 插件加载诊断：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke
```

`nonebot-smoke` 会检查 `nonebot`、`nonebot.adapters.onebot.v11`、`plugins.bot_unified_runtime` 是否可导入，插件 metadata 是否声明支持 `~onebot.v11`，并输出 `runtime_enabled=true|false`、人格文件、知识文件、记忆开关、历史开关、诊断开关、审计 store、回执 store、回复限速 store/db、全局/会话/发送者上限、目标最小间隔、安静时间开关/窗口/时区/作用会话类型、LLM provider/model/API key 状态，以及 `ready_for_real_llm`、`llm_readiness_status`、`llm_next_action`、`llm_readiness_reasons` 和 `llm_fix_hints`。`runtime_enabled` 来自 `BOT_RUNTIME_ENABLED`，只用于确认 `.env` 或运行环境里的硬开关；当前进程是否被管理员软暂停，要看真实在线 `/bot status` 的 `运行时软暂停` 或 `/bot readiness` 的 `runtime_soft_paused`。LLM 就绪字段复用 `config-smoke` 的只读配置体检逻辑，用于判断真实模型是 `ready`、`local_only` 还是 `blocked`，并给出下一步动作。它不会启动 NoneBot，不会连接 NapCat，也不会向 QQ 发送消息。它只证明“本地插件加载边界是通的”，不证明真实账号投递成功。

如果要进一步确认真实启动顺序不会因为 handler 或 scheduler 注册崩溃，可以跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 startup-smoke
```

`startup-smoke` 会在干净子进程里执行 `nonebot.init()`，注册 OneBot V11 adapter，加载统一运行时插件并统计 matcher 优先级；它还会检查 `nonebot_plugin_apscheduler` 的 scheduler 是否可访问，以及是否注册了默认关闭的 `bot_send_queue_worker`。该命令不会执行 `nb run`，不会启动长驻服务，不连接 NapCat，也不会发送 QQ 消息。输出只展示 `nonebot_initialized`、`onebot_adapter_registered`、`plugin_loaded`、`matcher_count`、`matcher_priorities`、`scheduler_jobs`、`server_started=false`、`napcat_connected=false` 和 `real_transport_used=false` 等安全字段。

如果要单独确认 OneBot/NapCat 出站消息段和 transport 回执边界，可以跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 transport-smoke
```

`transport-smoke` 会构造 text、image、JSON card、mixed、fallback 和 forward 六类 `RenderedOutput -> SendRequest` 样例，验证它们能被转换成 OneBot V11 数组消息段或受控扩展 API 调用，并用 fake bot 跑私聊、群聊、合并转发、可重试失败 retcode 和最终失败 retcode 的 `send_onebot_v11` 回执映射。合并转发只在 `allow_forward=true` 时尝试 `send_group_forward_msg` / `send_private_forward_msg` 或对应 `call_api(...)`，否则降级为 `text_fallback`；smoke 会输出 `forward_api=true`、`forward_receipt_state=sent` 和 fake forward 调用计数。它只证明项目内 sender/transport adapter 的本地边界正确；不会启动 NoneBot/NapCat，不连接 QQ，不发送真实消息，也不会展示目标 ID、消息正文、真实 provider message id、数据库路径或密钥。

如果已经启动真实 NoneBot / NapCat，想只读确认当前进程是否看得见在线 bot，可以跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 online-transport-smoke
```

`online-transport-smoke` 只读取 NoneBot 当前在线 bot 状态，输出 `bot_provider_state`、`online_bots_count`、`onebot_bots_count`、`send_capable`、`runtime_enabled`、`server_started=false`、`napcat_connected=false` 和 `real_transport_used=false`。它不会构造 `SendRequest`，不会调用 `send_private_msg` / `send_group_msg`，不会连接新的 NapCat 实例，也不会发送 QQ 消息；命令输出不展示 bot id、目标 ID、消息正文、数据库真实路径、密钥或 provider message id。这个命令只能证明“当前运行态能否看到具备 OneBot 风格发送方法的 bot”，不证明某条业务消息已经真实投递成功。

### 状态诊断

`/bot status` 会返回当前运行时配置摘要，方便接入真实模型时排查：

- 人格 id、显示名和版本。
- 运行时硬开关 `BOT_RUNTIME_ENABLED`，显示为 `运行时硬开关：enabled|disabled`。
- 当前进程软暂停状态，显示为 `运行时软暂停：true|false`、安全 reason 和 `updated_by=set|missing`。
- 人格文件数量与缺失数量。
- 知识文件数量与缺失数量。
- 记忆是否启用、数据库路径是否已配置。
- 最近对话历史是否启用、数据库路径是否已配置、最大读取轮数和每作用域最大保留条数。
- 运行诊断是否启用、数据库路径是否已配置、最大保留条数。
- 审计是否启用、使用内存还是 SQLite、数据库路径是否已配置、最大保留条数。
- 发送回执是否启用、使用内存还是 SQLite、数据库路径是否已配置、最大保留条数。
- 发送队列是否启用、使用内存还是 SQLite、数据库路径是否已配置、最大保留条数、最大尝试次数和重试退避秒数。
- 情绪感知是否启用、最多注入多少条情绪信号。
- 回复限速是否启用、store、db 是否配置、窗口秒数、全局上限、会话上限、发送者上限、目标最小间隔和绕过角色。
- 安静时间是否启用、开始/结束时间、时区、作用会话类型和绕过角色。
- 权限角色数量：管理员、企业、可信和拉黑名单数量。
- LLM provider、model、api key 是否已设置、聊天是否启用。
- LLM 就绪三态：`ready/local_only/blocked`、`ready_for_real_llm`、下一步动作 `fix_config/configure_real_llm/llm_smoke` 和安全原因码。

状态诊断不会输出 `BOT_CHAT_API_KEY` 原文，只显示 `api_key=set` 或 `api_key=missing`。

`/bot why [request_id|debug_id]` 会返回最近一次或指定一次运行时诊断，适合在线排查“为什么回复、为什么没回复、为什么最多回复几条、是否创建发送请求、transport 是否成功”。启用 SQLite 发送队列后，它可以从持久化队列里按 `request_id` 恢复发送请求创建状态，避免重启后误判为 `send_request_created=false`。`/bot why` 自身不会覆盖最近诊断记录。

`/bot receipt <request_id|debug_id>` 只允许管理员查询发送回执。它会展示 `request_id`、`debug_id`、`state`、`transport`、`retry_count`、`next_retry_at` 和安全的 `public_message`，不会展示 OneBot/NapCat 真实 `provider_message_id`、目标 ID、数据库路径或密钥。

`/bot audit <request_id>` 只允许管理员查询审计事件。它会展示每条记录的 `request_id`、`stage`、`event`、`severity` 和安全的 `public_message`，不会展示 `private_debug`、`session_id`、原始用户消息、回复全文、目标 ID、token、cookie、API key 或 provider message id。

`/bot recent [数量]` 只允许管理员查看最近排障摘要。它会把最近运行诊断、发送回执和审计事件合并成紧凑列表，默认显示 5 条，最大 20 条；运行诊断行会展示 `llm_readiness`、`ready_for_real_llm`、安全 `llm_reasons` 原因码和安全 `diagnostic_tags`，方便先判断真实 LLM 配置是 `ready`、`local_only` 还是 `blocked`，以及刚才是否发生提示注入、审查阻断或历史记录跳过。`diagnostic_tags` 只允许固定机器标签，不展示原始用户文本、自然语言异常、密钥、Authorization/Bearer、session_id 或目标 ID。输出只展示安全字段，方便在不知道 `request_id` 时先定位刚刚发生了什么。

`/bot queue` 只允许管理员查看发送队列安全摘要。它会展示 `enabled`、`store`、`db=set|missing`、`queued`、`failed_retryable`、`failed_final`、`sent`、`skipped`、`processing`、`max_items`、`max_attempts` 和退避秒数；不会展示数据库真实路径、目标 ID、消息正文、`dedupe_key`、人格 id 或 provider message id。

`/bot history clear` 只允许管理员清理当前会话、当前发送者、当前机器人实例的最近对话历史。它会展示安全的 `cleared_turns` 计数，方便确认是否真的清掉污染上下文；不会展示历史正文、`session_id`、`sender_id`、`bot_id`、数据库真实路径或长期记忆内容。非管理员会被拒绝，且不会透露历史库是否启用或是否存在记录。

`/bot context [测试文本]` 只允许管理员查看 LLM 上下文安全摘要。它用于在线确认人格、知识、记忆、最近对话、情绪信号、回复预算、prompt 长度、来源安全指纹和分区裁剪状态是否进入上下文；输出不包含原始用户文本、完整 prompt、知识原文、数据库真实路径、密钥、目标 ID、真实文件路径、文件名或 provider message id。

`/bot llm` 只允许管理员查看 LLM 在线连接诊断。它会先做只读配置预检，缺少真实 API key、model 或 base_url 时不调用 provider；预检通过后才短调用真实 provider。输出白名单摘要包含 LLM 就绪三态、下一步动作和安全 `llm_fix_hints`，不展示密钥、Authorization/Bearer、完整模型回复或原始 provider 错误。

`/bot setup llm` 只允许管理员查看真实 LLM 接入清单。它复用本地 `llm-setup`，只展示缺失/占位环境变量、安全 `.env` 模板、人工步骤和下一步命令；它不写 `.env`、不调用 provider、不连接 NapCat、不发送 QQ，也不会覆盖最近业务诊断。

`/bot config` 只允许管理员查看只读配置体检摘要。它用于在线确认当前机器人进程看到的人格文件、知识文件、文件可解析性、人格材料强度、provider/model/API key 状态、持久化开关和安全 `llm_fix_hints`；它不调用模型、不发送外部消息。

`/bot dialogue [测试文本]` 只允许管理员查看一轮基础对话验收摘要。它用于在线确认当前进程里人格、知识、情绪、记忆、历史、回复预算、LLM provider、输出审查、本地发送链路和安全 `llm_fix_hints` 是否能合成一次对话结果；它不展示完整模型回复、原始测试文本、完整 prompt、知识原文或密钥。

`/bot roles` 只允许管理员查看权限角色规则矩阵。它用于确认角色数量、角色顺序、拉黑策略、限速/安静时间绕过角色、群命令前缀和 ID 输入格式；它不调用模型、不连接 NapCat、不发送外部消息，也不会展示具体 user_id。

`/bot receipt`、`/bot audit`、`/bot recent`、`/bot queue`、`/bot context`、`/bot llm`、`/bot setup llm`、`/bot config`、`/bot readiness`、`/bot dialogue`、`/bot roles`、`/bot persona`、`/bot history clear`、`/bot pause` 和 `/bot resume` 本身不会覆盖 `/bot why` 使用的最近业务诊断记录；这避免管理员排障时把真正要查的业务现场顶掉。

## NoneBot / NapCat 运行边界

NoneBot 只负责插件加载、事件分发和适配器抽象。NapCat 作为 OneBot V11 实现时，进入项目的事件必须先归一化为 `IncomingMessage`，离开项目的消息必须由统一 sender 将 `SendRequest.content` 转成 OneBot/NapCat 消息段。

能力模块不能直接调用 `bot.send_private_msg`、`bot.send_group_msg`、`event.send` 或 NapCat HTTP/WebSocket API。只有 sender/transport adapter 可以触碰具体发送 API，并且必须返回 `DeliveryReceipt`。

当前 NoneBot 基础聊天入口已经接入 OneBot V11 transport：`RenderedOutput.content_type=text` 会被转换成数组 `text` 段，`image` 会被转换成 `image` 段，`card` 中的 `onebot_json/json/data` 会被转换成 `json` 段，`mixed.parts` 会按顺序转换成 text/image/json 组合段。`forward` 只有在 `SendRequest.allow_forward=true` 时才会尝试 OneBot/NapCat 扩展 API：群聊调用 `send_group_forward_msg(group_id, messages)`，私聊调用 `send_private_forward_msg(user_id, messages)`；如果 bot 没有这些方法，会回退到 `call_api("send_group_forward_msg", ...)` 或 `call_api("send_private_forward_msg", ...)`；如果不允许 forward、节点缺失或扩展 API 不可用，则降级为 `text_fallback`。普通私聊调用 `send_private_msg`，普通群聊调用 `send_group_msg`，返回的 `message_id` 或 `data.message_id` 会写入 `DeliveryReceipt.provider_message_id`，并可写入内部 `delivery_receipts` 表。返回 `status=failed` 或非零 `retcode` 时会归一化为 `failed_retryable` 或 `failed_final`；公开消息只展示安全 retcode/status/debug_id，不展示上游原文、目标 ID、正文或密钥。同时追加 `stage=transport` 的审计记录，但审计私有字段只保留 `provider_message_id=[internal]`，不写真实 provider id。图片上传/缓存策略、真实 NapCat 合并转发授权投递验证和更多 NapCat retcode 细分仍是后续阶段。

## 下一阶段命令里程碑

统一运行时插件实现后，需要收紧这些检查：

- `smoke` 后续可以收口到更完整的集成检查。
- `readiness-smoke` 已聚合环境、配置、上下文和本地静态聊天探针，用于接真实 LLM 前第一眼判断下一步；它不调用真实 provider，也不代表 NapCat 投递完成。
- `llm-setup` 已提供接真实模型前的只读清单：输出安全 `.env` 占位模板、必填键名、缺失/占位键名和下一步命令；它不写 `.env`，不调用真实 provider，不连接 NapCat，不代表模型或 QQ 投递完成。
- `/bot setup llm` 已接入在线管理员入口，复用 `llm-setup` 的只读清单，并继续经过统一 pipeline、审查、渲染、发送请求、回执和审计；它不写 `.env`，不调用 provider，不连接 NapCat，不覆盖最近业务诊断。
- `dialogue-smoke` 已聚合上下文安全摘要和一轮本地聊天 pipeline，用于验收人格、情绪、记忆/历史、知识、回复预算、LLM 状态、回执和下一步动作；它不连接 NapCat，不代表真实账号投递完成。
- `persona-smoke` 已验证人格材料、语气参数、安全来源指纹和人格规则计数；它不调用 LLM，不代表真实模型回复质量。
- `config-smoke` 已验证基础对话、回复限速、安静时间和真实 LLM 接入的关键配置是否就绪；它不调用 LLM，不代表模型服务可用。
- `nonebot-smoke` 已验证本地 NoneBot / OneBot 依赖导入、插件 metadata、回复限速、安静时间和配置摘要；它不启动 NapCat，不代表真实账号投递完成。
- `startup-smoke` 已验证干净子进程里的 NoneBot 初始化、OneBot adapter 注册、本地插件加载、handler 注册和 APScheduler 可访问性；它不执行 `nb run`，不连接 NapCat，不代表真实账号投递完成。
- `context-smoke` 已验证人格/记忆/知识/provider 和 chat prompt 构造摘要；它不调用 LLM，不代表真实模型回复质量。
- `why-smoke` 已验证本地 policy、角色、回复预算、限速阻断、安静时间阻断、人格/知识上下文读取失败归因、LLM 状态、LLM 就绪三态、发送请求、回执、审计摘要和 review 阻断安全归因；它不启动 NapCat，不代表真实账号投递完成。
- `queue-smoke` 已验证临时 SQLite 发送队列、租约 claim、一次性 worker、transport 回执记录和队列状态推进；它使用 fake transport，不启动 NapCat，不代表真实账号投递完成。
- `transport-smoke` 已验证项目内 OneBot/NapCat text/image/json/mixed/fallback/forward 边界、`status/retcode/data.message_id` 归一化，以及 fake bot 私聊/群聊/合并转发/失败分类 transport 回执映射；它不启动 NoneBot/NapCat，不代表真实账号投递完成。
- `online-transport-smoke` 已提供只读在线 bot 诊断；它读取当前 NoneBot 进程的在线 bot 状态和 OneBot 风格发送方法可见性，但不调用发送 API，不代表真实业务消息投递完成。
- `/bot why` 已接入真实 NoneBot 入口的最近诊断；默认进程内保存，配置 `BOT_DIAGNOSTICS_ENABLED=true` 后可持久化到 SQLite；启用 SQLite 发送队列时还能按 `request_id` 从 `send_requests` 恢复安全发送请求创建状态。
- `/bot receipt <request_id|debug_id>`、`/bot audit <request_id>`、`/bot recent [数量]`、`/bot queue`、`/bot context [测试文本]`、`/bot llm`、`/bot setup llm`、`/bot config`、`/bot readiness`、`/bot dialogue [测试文本]`、`/bot roles`、`/bot persona`、`/bot history clear`、`/bot pause` 和 `/bot resume` 已接入管理员安全查询与运行时控制；后续仍需要可视化面板。
- `drain_send_queue_once()` 已提供一次性发送队列 worker，`queue-smoke` 已提供本地 fake transport 验证入口；NoneBot 入口已能在 `BOT_SEND_QUEUE_WORKER_ENABLED=true` 且 SQLite 队列可用时注册默认关闭的 APScheduler worker。SQLite 队列已支持 `claim_due()` 租约认领、过期恢复和 `find_request(request_id)` 持久请求查找；真实 NapCat 在线重试 smoke 仍是后续工作。
- `chat-smoke` 已验证基础对话链路，并复用 `config-smoke` 的只读 LLM 就绪三态，能同时看出本地 pipeline、真实 provider 配置和模型调用状态；但它仍使用内存队列，不代表真实 NapCat 投递完成。
- NoneBot 基础聊天入口已接入 OneBot/NapCat text/image/json/mixed/forward transport 边界；`transport-smoke` 已覆盖本地消息段、合并转发扩展 API 门控、retcode 归一化和 fake bot 回执映射；`online-transport-smoke` 已覆盖只读在线 bot 可见性检查；仍需要后续增加真实 NapCat 授权投递验证，验证实际账号和网络投递。
- `llm-smoke` 已验证真实模型配置诊断入口，但不会触碰真实聊天 transport。
- `verify` 已要求运行时契约、策略决策、发送回执、审计记录、上下文接口、parser registry 和 auto-send draft parser 测试通过。
- 数据库或迁移命令只在 ORM schema 存在后再加入。


## 2026-08-23 命令与知识库更新

### QQ 功能命令
- 通用：`/bot status`、`/bot help`、直接聊天。
- 点歌：`/点歌 <歌名>`；模式设置：`/点歌模式 音频|语音|链接|卡片`（管理员，持久化）。
- 大小写均可：`/wiki`、`/WIKI`、`/Wikipedia`、`/维基`、`/维基百科`；`/epic`、`/EPICFREE`、`/Epic Free`、`/Epic 免费`。
- 斜杠均可：`/天气 城市`、`/查天气 城市`、`/历史上的今天`、`/点歌 歌名`。
- 中文订阅：`/订阅 添加 <链接> [到本群|私聊我] [--digest]`、`/订阅 列表|删除|暂停|恢复|检查|状态`；旧 `/bot subscribe ...` 继续可用。
- 角色昵称：`/岸宝帮助`、`/岸宝状态`、`/岸宝天气 城市`、`/岸宝点歌 歌名`、`/岸宝wiki 词条`、`/岸宝epic`、`/岸宝订阅 ...`、`/岸宝日志`。
- 管理员：`/bot logs [info|warning|error] [数量]`。

### 知识库
- 人格文件：`BOT_PERSONA_FILES`（守岸人 identity）。
- 知识文件：`BOT_KNOWLEDGE_FILES` 已配置四份用户材料（三份人格档案 + 鸣潮库街区百科v2.md）。
- 向量检索：`BOT_EMBEDDING_ENABLED=true` 且填好 `BOT_EMBEDDING_MODEL/BASE_URL/API_KEY` 后启用 `/embeddings` 语义检索；未启用自动跨文件关键词检索并回退顺序取块。


### 多实例共享与实例名命令（追加）

- 命令前缀：`/守岸人`、`守岸人`、`/岸宝`、`岸宝` 均可；斜杠可省略。
- 示例：`守岸人帮助`、`守岸人查询`、`守岸人查询天气 杭州`、`/岸宝点歌 晴天`、`守岸人订阅 添加 <链接>`。
- 多实例共享组配置：
  - `BOT_SHARE_ENABLED=false`
  - `BOT_SHARE_GROUPS=[]`（组名写成 `A and B`、`A and B and C` 形式）
  - `BOT_SHARE_READ_ONLY=false`
- 语义：实例可见性 = 自己 private 记录 + `记录.share_groups` 与 `实例.BOT_SHARE_GROUPS` 有交集的记录；凭据级敏感记忆永不共享。
- 调试命令（待 PostgreSQL 落地后接入，统一 `/bot` 开头）：`/bot share status`、`/bot share groups`、`/bot share group create <组名>`、`/bot share group add <组名> <实例名>`、`/bot share group remove <组名> <实例名>`、`/bot share send history <id> --group <组名>`、`/bot share send memory <fact_id> --group <组名>`、`/bot share list`、`/bot share revoke ...`。


## 2026-08-23 基层路由、点名接话与表情包更新

### 优先级调整（昵称/管理员命令最前）
- 昵称命令 `/岸宝…`、`守岸人…`（斜杠可省略）优先级 10；
  管理员命令 `/bot …` 优先级 11，两者先于订阅/点歌/天气等判定。
- 全部生效路由可用管理员命令 `/bot routes` 查看；`/bot route <文本>` 看单条判定。

### 自然语言命令（不带斜杠也会执行对应插件）
- 天气：`帮我查一下杭州天气`、`杭州天气怎么样`、`帮我查天气 杭州`
- 点歌：`来首晴天`、`点一首晴天`、`放首歌 晴天`、`帮我放一首周杰伦的歌`
- 维基：`帮我查维基 鸣潮`
- Epic：`今天有什么免费游戏`
- 历史：`今天历史上发生了什么`
- 保守规则：`今天天气不错`、`播放量好高` 这类闲聊仍走人格大模型，不会被误判。

### 点名与群聊接话
- 群聊里 @ 机器人、写“岸宝/守岸人”点名（含“呼叫守岸人”“大家好，守岸人，在吗”）都会触发回复。
- 群聊默认只有点名/命令才回复；开启自动接话：
  - `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED=true`
  - `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY=0.1`（0~1，确定性哈希抽签）
- 私聊无门禁，直接进入人格对话。

### 表情包生成（bot.meme）
- 依赖：本地运行 [meme-generator-rs](https://github.com/MemeCrafters/meme-generator-rs)（MIT，默认 `http://127.0.0.1:2233`）。
- 配置：`BOT_MEME_API_ENABLED=true`，可选 `BOT_MEME_API_BASE_URL`、`BOT_MEME_API_TIMEOUT_SECONDS`。
- 命令（大小写均可、斜杠可省略）：`/表情 列表`、`/表情 <key> <文字>`（多段文字用 ｜ 分隔）、`/表情帮助`。
- 三件套结论：`meme-generator-rs`（后端，必装）与
  `nonebot-plugin-memes`、`nonebot-plugin-memes-api`（两个插件功能重复）。
  本项目未安装任何一个 NoneBot 插件，而是自研 `bot.meme` 客户端对接同一
  HTTP API，保证表情包输出也走基层统一流水线（安全审查/日志/发送队列）。
