# ChatBot（bot_unified_runtime）全量配置键目录

> 配套文档：总览与指令见 [ai-setup-knowledge-pack.md](ai-setup-knowledge-pack.md)（本文档是其 §6 的完整展开版）。
> 数据来源：`plugins/bot_unified_runtime/config.py`（296 个字段，全部覆盖，一个不漏）、`.env.example`、`plugins/bot_unified_runtime/config_readiness.py`、`plugins/bot_unified_runtime/runtime/settings.py`、`plugins/bot_unified_runtime/llm/providers.py`、`plugins/bot_unified_runtime/llm/model_router.py`；另以 grep 佐证 `character/documents.py` 与 `capabilities/music.py`、`capabilities/runtime_admin.py`。
> 安全声明：本目录从未读取真实 `.env`，只引用 `.env.example`；全文不含任何真实密钥、Cookie、Token、QQ 号，密钥一律以 `sk-xxxx` / `env:变量名` / `<占位符>` 表示。

---

## 0. 通用规则（先读）

1. **键名映射**：`.env` 中写 `BOT_XXX`，对应 `config.py` 字段 `bot_xxx`。`translate_env_keys()` 把所有键转小写并保持 `bot_` 前缀一一对应（幂等）；无 `BOT_` 前缀的键（如 `MCP_*`）不进 `Config`，留在 driver 配置里。
2. **列表/字典写法**（`field_validator(mode="before")` 解析）：
   - 文件列表键（`BOT_PERSONA_FILES`、`BOT_KNOWLEDGE_FILES`、`BOT_TREND_FILES`、`BOT_GLOSSARY_FILES`、`BOT_RUNTIME_PERSONA_NICKNAMES`、`BOT_PERSONA_NICKNAMES`）：接受 JSON 数组字符串 或 分号 `;` 分隔字符串；空/`[]` → 空列表。
   - ID 列表键（管理员/群策略等）：JSON 数组 或 `,` `;` 分隔（逗号先归一成分号）。
   - 平台列表键（`BOT_CONTENT_PARSE_PLATFORMS`、`BOT_MUSIC_PLATFORMS`、表情库群白/黑名单、`BOT_MEME_LIBRARY_PREFER`）：同上，且**全部转小写**。
   - 角色列表键（`BOT_RATE_LIMIT_BYPASS_ROLES` 等）：同 ID 列表写法。
   - 字典键（`BOT_MODEL_PRESETS/REGISTRY/SCHEDULE`、`BOT_MAIL_SENDER_ALIASES`、`BOT_VISION_MODEL_REGISTRY`、`BOT_PERSONA_ALT_PROFILES`、`BOT_CREDENTIAL_PROBE_URLS`）：JSON 对象字符串；解析失败静默回退 `{}`（`_parse_alt_profiles` 同）。
   - 布尔：`true/false/1/0/yes/no/on/off/开/关/是/否`（热更转换器口径；dotenv 由 pydantic 解析）。
3. **路径重定向**：模型校验器 `_resolve_runtime_data_paths` 把 `data`、`data/...` 前缀的路径统一解析到 `BOT_RUNTIME_DATA_DIR`（相对路径以项目根为基准拼接）。受影响的路径字段共 24 个 + 4 个文件列表字段（`bot_persona_files`、`bot_knowledge_files`、`bot_trend_files`、`bot_glossary_files`）。
4. **热更列**：✅ = 该键在 `SETTABLE_KEYS` 白名单中，可由管理员对话热改、立即生效；空白 = 修改 `.env` 后需重启进程。
5. **差异标注**：⚠️ = `.env.example` 样例值与 `config.py` 代码默认不一致（**以 config.py 为准**）；「.env 缺」= `.env.example` 未列出该键，实际生效代码默认。逐项汇总见第 E 节。

---

## A. 按功能域分组的配置键总表

### A1 运行时核心与日志（11 键）

| 键名（.env） | 类型 | 默认值 | 合法值/范围 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_RUNTIME_DATA_DIR` | str | `data` | 任意路径；相对路径基于项目根 | | 运行数据根目录，生产可放工作区外（样例 `../ChatBot_Runtime/data`） | 所有 `data/...` 路径键的重定向目标 |
| `BOT_RUNTIME_ENABLED` | bool | `True` | true/false | | 统一运行时总开关 | 关闭后 readiness 记录 `runtime_enabled=false` |
| `BOT_RUNTIME_DEFAULT_PERSONA` | str | `default` | 人格 profile id | | 默认人格 id（样例 shorekeeper ⚠️） | 与 `BOT_PERSONA_PROFILE_ID`、实例自举相关 |
| `BOT_RUNTIME_GROUP_COMMAND_PREFIX` | str | `/bot` | 任意前缀串 | | 群聊指令前缀 | |
| `BOT_RUNTIME_ADMIN_PREFIX` | str | `/bot` | 任意前缀串 | | 管理指令前缀 | 配合 `BOT_ADMIN_USER_IDS` |
| `BOT_RUNTIME_INSTANCE` | str | `default` | 实例名（建议字母数字） | | 多实例名；空则自举为人格 id | 决定热更设置文件名（见 C 节） |
| `BOT_RUNTIME_SETTINGS_FILE` | str | `data/runtime_settings.json` | 路径 | | 运行时设置文件（旧式单文件路径字段） | 实际覆盖文件按 settings_dir+实例名拼（见 C 节） |
| `BOT_RUNTIME_SETTINGS_DIR` | str | `data/settings` | 路径 | | 每实例设置目录 | `runtime_settings_<实例>.json` 存放处 |
| `BOT_RUNTIME_LOG_FILE` | str | `data/runtime_events.log` | 路径 | | 运行事件日志 | |
| `BOT_RUNTIME_LOG_MAX_BYTES` | int | `2097152` | 正整数（字节） | | 日志轮转上限（2 MiB） | |
| `BOT_RUNTIME_LOG_LEVEL` | str | `INFO` | 日志级别名（INFO 等） | | 运行日志级别 | |

### A2 多实例共享与数据导出（6 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SHARE_ENABLED` | bool | `False` | | | 多实例共享开关 | 依赖 `BOT_SHARE_GROUPS` |
| `BOT_SHARE_GROUPS` | list[str] | `[]` | `"A and B"` 格式或 JSON 数组 | | 共享组名列表 | |
| `BOT_SHARE_READ_ONLY` | bool | `False` | | | 共享只读 | |
| `BOT_SHARED_EXPORT_ENABLED` | bool | `False` | | | 共享导出开关 | |
| `BOT_SHARED_EXPORT_INCLUDE_PRIVATE` | bool | `False` | | | 导出是否含私聊内容 | |
| `BOT_SHARED_EXPORT_MAX_CHARS` | int | `200` | ≥0 | | 单条导出截断长度 | |

### A3 权限与用户分级（6 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_ADMIN_USER_IDS` | list[str] | `[]` | 平台用户 id 列表 | | 管理员（唯一可执行 `/bot runtime set` 等） | 限速/免打扰 bypass、热更指令均依赖 |
| `BOT_TELEGRAM_ADMIN_USER_IDS` | list[str] | `[]` | | | Telegram 侧管理员 | |
| `BOT_TELEGRAM_ADMIN_CHAT_IDS` | list[str] | `[]` | | | Telegram 侧管理会话 | 邮件通知发送目标相关 |
| `BOT_ENTERPRISE_USER_IDS` | list[str] | `[]` | | | 企业用户名单 | |
| `BOT_TRUSTED_USER_IDS` | list[str] | `[]` | | | 可信用户名单 | |
| `BOT_BLOCKED_USER_IDS` | list[str] | `[]` | | | 黑名单（拒绝服务） | |

### A4 GScore 对接（7 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GSCORE_ENABLED` | bool | `False` | | | GScore 第三方服务对接开关 | |
| `BOT_GSCORE_HOST` | str | `127.0.0.1` | 主机名/IP | | 服务地址 | |
| `BOT_GSCORE_PORT` | int | `8765` | 端口号 | | 服务端口 | |
| `BOT_GSCORE_WS_TOKEN` | str | `""` | 令牌；占位写入 `env:` 或本地 | | WebSocket 令牌（密钥类，输出占位） | |
| `BOT_GSCORE_MAX_RETRY` | int | `5` | ≥0 | | 连接重试次数 | |
| `BOT_GSCORE_BOT_ID` | str | `NoneBot2` | | | 上报的 bot 标识 | |
| `BOT_GSCORE_BOT_SELF_ID` | str | `""` | | | 账号 self_id | |

### A5 邮件桥与 Telegram 通知（6 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MAIL_BRIDGE_ENABLED` | bool | `False` | | | 邮件桥总开关 | |
| `BOT_MAIL_AUTO_REPLY_ENABLED` | bool | `False` | | | 邮件自动回复 | 依赖 bridge_enabled |
| `BOT_MAIL_NOTIFY_TELEGRAM_ENABLED` | bool | `True` | | | 新邮件通知 Telegram | 依赖 Telegram 管理配置 |
| `BOT_MAIL_BRIDGE_STATE_FILE` | str | `data/mail_bridge_state.json` | 路径 | | 桥接状态持久化 | data/ 重定向 |
| `BOT_MAIL_SENDER_ALIASES` | dict[str,str] | `{}` | JSON 对象：发件别名→真实地址 | | 发件人别名映射（示例文件中的 QQ/Foxmail 别名**不在此复述**） | |
| `BOT_MAIL_NOTIFY_PREVIEW_CHARS` | int | `280` | ≥0 | | 通知预览截断长度 | |

### A6 人格、昵称与别名（11 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_PERSONA_PROFILE_ID` | str | `default` | profile id | | 当前人格档案 id（样例 shorekeeper ⚠️） | 实例自举回退值 |
| `BOT_PERSONA_DISPLAY_NAME` | str | `报存` | 任意显示名 | | 人格显示名（样例「守岸人」⚠️） | 卡片页脚名称来源之一 |
| `BOT_PERSONA_VERSION` | str | `0` | 版本串 | | 人格版本号（样例 local ⚠️） | |
| `BOT_PERSONA_FILES` | list[str] | `[]` | `.md`/`.txt`/`.docx` 路径 | | 人格文档（readiness 强校验） | readiness：缺失/不支持/不可读/空 均 error |
| `BOT_PERSONA_NICKNAMES` | list[str] | `[]` | 昵称列表 | | 人格级昵称（随人格不随平台） | 触发词/别名解析 |
| `BOT_PERSONA_AVATAR_URL` | str | `""` | URL 或本地路径 | | 卡片页脚头像；空 = 名字首字圆点 | 卡片渲染消费 |
| `BOT_PERSONA_ALT_PROFILES` | dict[str,dict] | `{}` | JSON：`{"gentle":{"display_name","files","weight","emotions":[...]}}` | | 备用人格及权重/情绪触发 | 情绪系统联动 |
| `BOT_PERSONA_ACTION_BRACKETS` | str→bool | `True` | | ✅热更 | 动作括号（（…）描写）开关 | |
| `BOT_RUNTIME_PERSONA_NICKNAME` | str | `""` | | | 运行时层单昵称 | |
| `BOT_RUNTIME_PERSONA_NICKNAMES` | list[str] | `[]` | | | 运行时层多昵称 | |
| `BOT_RUNTIME_ALIAS_ENABLED` | bool | `True` | | | 昵称别名解析开关 | 与上两条配合 |

### A7 知识库与向量嵌入（16 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_KNOWLEDGE_FILES` | list[str] | `[]` | `.md`/`.txt`/`.docx` | | 知识文档 | readiness：缺失/不支持/不可读 = error；空/空文件 = warning |
| `BOT_KNOWLEDGE_MAX_CHUNKS` | int | `4` | ≥0 | | 顺序回退取块数（样例 2 ⚠️） | 嵌入失败时的回退路径 |
| `BOT_KNOWLEDGE_CHUNK_CHARS` | int | `900` | >0 | | 每块字符数（样例 600 ⚠️） | |
| `BOT_KNOWLEDGE_TOP_K` | int | `4` | ≥0 | | 向量检索条数（样例 5 ⚠️） | 依赖 `BOT_EMBEDDING_ENABLED` |
| `BOT_KNOWLEDGE_DB_PATH` | str | `data/knowledge_embeddings.sqlite3` | 路径 | | 向量库存放 | |
| `BOT_EMBEDDING_ENABLED` | bool | `False` | | | 远程向量嵌入开关 | 开启后按语义检索，失败回退顺序取块 |
| `BOT_EMBEDDING_MODEL` | str | `""` | 模型名 | | 远程嵌入模型 | |
| `BOT_EMBEDDING_BASE_URL` | str | `""` | OpenAI 兼容 URL | | 远程嵌入接口 | |
| `BOT_EMBEDDING_API_KEY` | str | `""` | 密钥或 `env:` 引用 | | 远程嵌入密钥（输出占位） | |
| `BOT_EMBEDDING_TIMEOUT_SECONDS` | float | `15.0` | 秒（样例 30 ⚠️） | | 远程嵌入超时 | |
| `BOT_EMBEDDING_DIMENSIONS` | int | `1024` | 模型维度 | | 向量维度 | |
| `BOT_EMBEDDING_LOCAL_ENABLED` | bool | `True` | | | 本地优先（Ollama 兼容端点） | 失败自动回退远程 |
| `BOT_EMBEDDING_LOCAL_BASE_URL` | str | `http://127.0.0.1:11434/v1` | URL | | 本地端点 | |
| `BOT_EMBEDDING_LOCAL_MODELS` | str | `bge-m3` | 模型名 | | 本地嵌入模型 | |
| `BOT_EMBEDDING_LOCAL_API_KEY` | str | `""` | 密钥（占位） | | 本地密钥（通常可空） | |
| `BOT_EMBEDDING_LOCAL_TIMEOUT_SECONDS` | float | `60.0` | 秒 | | 本地嵌入超时 | 快速模式另有 `BOT_CHAT_FAST_EMBEDDING_TIMEOUT_SECONDS` |

### A8 语气与回复控制（16 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_TONE_MODE` | str | `private_chat` | 模式名 | | 语气模式 | |
| `BOT_TONE_VOICE` | str | `soft` | 语气名 | | 语气风格 | |
| `BOT_TONE_WARMTH` | float | `0.7` | 数值（样例 0.8 ⚠️） | | 温暖度 | |
| `BOT_TONE_DIRECTNESS` | float | `0.5` | 数值（样例 0.4 ⚠️） | | 直接度 | |
| `BOT_TONE_MESSAGE_COUNT_LIMIT` | int | `0` | ≥0（0=不限） | | 语气消息数限制 | |
| `BOT_REPLY_PRIVATE_DEFAULT_MAX_MESSAGES` | int | `0` | ≥0（0=不限） | | 私聊默认回复条数上限 | |
| `BOT_REPLY_PRIVATE_SUPPORT_MAX_MESSAGES` | int | `0` | ≥0 | | 私聊安抚场景条数上限 | |
| `BOT_REPLY_PRIVATE_DEEP_HELP_MAX_MESSAGES` | int | `0` | ≥0 | | 私聊深度帮助条数上限 | |
| `BOT_REPLY_GROUP_MAX_MESSAGES` | int | `0` | ≥0 | | 群聊回复条数上限 | |
| `BOT_REPLY_RISK_MAX_MESSAGES` | int | `0` | ≥0 | | 风险场景条数上限 | |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | int | `0` | 0=不限；热更时必须 ≥200 | ✅热更 | 单条消息字数上限 | 热更转换器 `_reply_chars_converter` |
| `BOT_REPLY_DETAIL` | str | `auto` | `auto`/`detail`/`concise`（热更接受中文别名 详细/精简/默认） | ✅热更 | 回复详略：auto=知识类自动详尽，detail=2000~4000 字，concise=精炼（样例 detail ⚠️） | |
| `BOT_REPLY_DEFAULT_CONTEXT_BUDGET` | int | `2048` | ≥0（样例 8192 ⚠️） | | 默认场景上下文预算 | |
| `BOT_REPLY_SUPPORT_CONTEXT_BUDGET` | int | `2560` | ≥0（样例 8192 ⚠️） | | 安抚场景预算 | |
| `BOT_REPLY_DEEP_HELP_CONTEXT_BUDGET` | int | `3072` | ≥0（样例 12288 ⚠️） | | 深度帮助预算 | |
| `BOT_REPLY_GROUP_CONTEXT_BUDGET` | int | `2048` | ≥0（样例 8192 ⚠️） | | 群聊预算 | 快速模式另有 `BOT_CHAT_FAST_CONTEXT_BUDGET` |

### A9 记忆 / 历史 / 诊断 / 审计 / 回执 / 审计日志（21 键）

> 代码默认 db_path 均为空 = **内存态/禁用语义**；`.env.example` 给出具体文件名（如 `data/wuwa_*.sqlite3`）仅为推荐样例。

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEMORY_ENABLED` | bool | `False` | | | 长期记忆开关 | |
| `BOT_MEMORY_DB_PATH` | str | `""` | 路径（空=内存） | | 记忆库 | |
| `BOT_MEMORY_MAX_ITEMS` | int | `5` | ≥0 | | 注入条数上限 | |
| `BOT_MEMORY_MAX_CHARS` | int | `1200` | ≥0 | | 注入字符上限 | |
| `BOT_MEMORY_EXTRACT_ENABLED` | bool | `True` | | | 回复后自动抽取记忆 | 依赖 `BOT_MEMORY_ENABLED` |
| `BOT_HISTORY_ENABLED` | bool | `False` | | | 对话历史开关 | |
| `BOT_HISTORY_DB_PATH` | str | `""` | 路径 | | 历史库 | |
| `BOT_HISTORY_MAX_TURNS` | int | `6` | ≥0 | | 注入轮数 | |
| `BOT_HISTORY_MAX_CHARS` | int | `1600` | ≥0 | | 注入字符上限 | |
| `BOT_HISTORY_MAX_ITEMS` | int | `1000` | ≥0 | | 存储条数上限 | |
| `BOT_DIAGNOSTICS_ENABLED` | bool | `False` | | | 诊断开关 | |
| `BOT_DIAGNOSTICS_DB_PATH` | str | `""` | 路径 | | 诊断库 | |
| `BOT_DIAGNOSTICS_MAX_ITEMS` | int | `100` | ≥0 | | 诊断条数上限 | |
| `BOT_AUDIT_ENABLED` | bool | `False` | | | 审计开关 | |
| `BOT_AUDIT_DB_PATH` | str | `""` | 路径 | | 审计库 | |
| `BOT_AUDIT_MAX_ITEMS` | int | `1000` | ≥0 | | 审计条数上限 | |
| `BOT_RECEIPTS_ENABLED` | bool | `False` | | | 回执开关 | |
| `BOT_RECEIPTS_DB_PATH` | str | `""` | 路径 | | 回执库 | |
| `BOT_RECEIPTS_MAX_ITEMS` | int | `1000` | ≥0 | | 回执条数上限 | |
| `BOT_AUDIT_LOG_FILE` | str | `""` | 路径（空=不写文件） | | 文件型审计日志 | |
| `BOT_AUDIT_LOG_MAX_BYTES` | int | `2097152` | 正整数 | | 审计日志轮转（2 MiB） | |

### A10 发送队列与超时/预算（11 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SEND_QUEUE_ENABLED` | bool | `False` | | | 发送队列开关 | |
| `BOT_SEND_QUEUE_DB_PATH` | str | `""` | 路径 | | 队列持久化；enabled 且非空 → sqlite，否则 memory | readiness 汇报 store 类型 |
| `BOT_SEND_QUEUE_MAX_ITEMS` | int | `1000` | ≥0 | | 队列容量 | |
| `BOT_SEND_QUEUE_MAX_ATTEMPTS` | int | `3` | ≥1 | | 最大重试次数 | 与重试间隔配合 |
| `BOT_SEND_QUEUE_RETRY_BASE_SECONDS` | int | `30` | ≥0 | | 重试基础间隔 | |
| `BOT_SEND_QUEUE_RETRY_MAX_SECONDS` | int | `300` | ≥base | | 重试间隔上限 | |
| `BOT_SEND_QUEUE_WORKER_ENABLED` | bool | `False` | | | 队列 worker 开关 | |
| `BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS` | int | `30` | ≥1 | | worker 轮询间隔 | |
| `BOT_SEND_QUEUE_WORKER_BATCH_SIZE` | int | `20` | ≥1 | | 每批处理条数 | |
| `BOT_TRANSPORT_TIMEOUT_SECONDS` | float | `15.0` | **(0, 600]**，拒绝负数/NaN/Infinity | ✅热更 | 发送层单请求硬超时（OneBot/Telegram/Mail 共用）；超时不自动重发正文；0 或非法值运行时回退 15 | 校验器+热更转换器双重把关 |
| `BOT_REQUEST_BUDGET_SECONDS` | float | `90.0` | **(0, 600]** | | 请求级总预算：单次聊天从 LLM/工具循环到发送共用单调 deadline；耗尽后不再发起新网络调用，群/频道静默，仅管理员收安全告警 | 传入 ModelRouter 作为 failover deadline 上界 |

### A11 情绪 / 趋势 / 时间感知（9 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_EMOTION_ENABLED` | bool | `True` | | | 情绪信号开关 | 与 `BOT_PERSONA_ALT_PROFILES.emotions` 联动 |
| `BOT_EMOTION_MAX_SIGNALS` | int | `4` | ≥0 | | 单次最大情绪信号数 | |
| `BOT_TREND_ENABLED` | bool | `False` | | | 动态/趋势注入开关 | |
| `BOT_TREND_FILES` | list[str] | `[]` | 文档路径 | | 趋势素材文件 | |
| `BOT_TREND_MAX_NOTES` | int | `5` | ≥0 | | 最多注入条数 | |
| `BOT_TREND_MAX_CHARS` | int | `500` | ≥0 | | 注入字符上限 | |
| `BOT_TREND_MAX_AGE_DAYS` | int | `14` | ≥0 | | 素材最大时效（天） | |
| `BOT_TEMPORAL_ENABLED` | bool | `True` | | | 时间感知开关 | |
| `BOT_TIMEZONE` | str | `Asia/Hong_Kong` | IANA 时区名 | | 主时区 | 免打扰时区独立配置 |

### A12 LLM 引擎与模型路由（28 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CHAT_ENABLED` | bool | `True` | | | 对话总开关；false → readiness error `chat_disabled` | |
| `BOT_CHAT_PROVIDER` | str | `static` | `static` / `openai_compatible`（readiness 仅认这两个） | | 引擎类型；static=占位回复 | 详见 B 节 |
| `BOT_CHAT_MODEL` | str | `static` | 非空、非占位模型名；热更时 ≤64 字符 | ✅热更 | 主模型名 | 详见 B 节 |
| `BOT_CHAT_API_KEY` | str | `""` | 真实密钥（输出一律 `sk-xxxx` 占位） | | 主密钥；readiness/诊断用 | 兼容镜像主 qian 密钥 |
| `BOT_API_KEY_QIANQIANYE` | str | `""` | 密钥（占位） | | 凭据槽：qian 组 | 注册表 `env:BOT_API_KEY_QIANQIANYE` 引用；NoneBot dotenv 会放进 driver.config，**必须保留在 Config**，否则运行态拿到空 key |
| `BOT_API_KEY_AIPRC` | str | `""` | 密钥（占位） | | 凭据槽：aiprc 组 | 同上 |
| `BOT_API_KEY_UMI_GROUP1` | str | `""` | 密钥（占位） | | 凭据槽：Umi 特惠组（desk） | 同上 |
| `BOT_API_KEY_UMI_GROUP2` | str | `""` | 密钥（占位） | | 凭据槽：Umi GPT 组 | 同上 |
| `BOT_API_KEY_HCN` | str | `""` | 密钥（占位） | | 凭据槽：HCN（兜底组） | 同上 |
| `BOT_CHAT_BASE_URL` | str | `https://api.openai.com/v1` | http(s) URL，不得内嵌账号密码；可带/不带 `/chat/completions`（自动补全） | | 主接口地址 | 详见 B 节 |
| `BOT_CHAT_TEMPERATURE` | float | `0.7` | **0.0 ≤ x ≤ 2.0**（有限数） | ✅热更 | 采样温度 | 详见 B 节 |
| `BOT_CHAT_REASONING_EFFORT` | str | `""` | `""`/`off`/`low`/`medium`/`high`/`xhigh`/`max` | ✅热更 | 思考强度：空=各模型家族默认最高档（deepseek/glm/kimi/minimax=max，gpt/grok=xhigh，gemini=high）；off=不发送；qwen/dashscope 系转成 `enable_thinking` 布尔；不支持时自动去参重试一次 | 复杂任务会把全局/默认档临时升到家族最高档；条目级 `effort` 字段优先于全局 |
| `BOT_CHAT_MAX_TOKENS` | int | `4096` | **≥0；0=不向 API 传 max_tokens（不设上限）**，负数非法 | ✅热更 | 正常聊天输出上限；命令能力用各自独立限制 | |
| `BOT_CHAT_TIMEOUT_SECONDS` | float | `30.0` | 有限数 **>0** | | 正常模式单模型超时 | 详见 B 节 |
| `BOT_CHAT_FAST_MODE` | bool | `True` | | | QQ/群聊快速响应模式：限制上下文/输出/联网前置，优先首字 | 启用时路由超时取 min(正常,快速) |
| `BOT_CHAT_FAST_MAX_TOKENS` | int | `4096` | ≥0 | | 快速模式输出上限 | |
| `BOT_CHAT_FAST_MAX_CANDIDATES` | int | `0` | ≥0；0=不限候选数 | | 快速模式候选模型截断数 | ModelRouter fast_mode 生效 |
| `BOT_CHAT_FAST_TIMEOUT_SECONDS` | float | `30.0` | >0 | | 快速模式超时 | router 取 min(正常,快速)；值为 0/缺省时回退 12.0 |
| `BOT_CHAT_FAST_CONTEXT_BUDGET` | int | `9600` | ≥0（样例 32768 ⚠️） | | 快速模式上下文预算 | |
| `BOT_CHAT_FAST_WEB_MAX_QUERIES` | int | `3` | ≥0（样例 5 ⚠️） | | 快速模式联网检索次数上限 | 依赖 `BOT_WEB_SEARCH_ENABLED` |
| `BOT_CHAT_FAILOVER_MAX_SECONDS` | float | `45.0` | ≥0；0=不限 | | 故障转移总时限：候选连败时的整体预算，防响应拖到分钟级 | 与请求级 deadline 取更早者 |
| `BOT_CHAT_FAST_EMBEDDING_TIMEOUT_SECONDS` | float | `3.0` | >0 | | 快速模式嵌入超时 | 压缩 `BOT_EMBEDDING_*_TIMEOUT` 的快路径 |
| `BOT_CHAT_FAST_SKIP_WEB_PAGES` | bool | `True` | | | 快速模式跳过网页抓取 | |
| `BOT_CHAT_FAST_DISABLE_VECTOR_KNOWLEDGE` | bool | `False` | | | 快速模式禁用向量知识检索 | 依赖 `BOT_EMBEDDING_ENABLED` |
| `BOT_MODEL_PRESETS` | dict[str,str] | `{}` | JSON：`{"预设名":"模型名"}` | | 模型预设：只接受**手动指定**（`/bot runtime model set <预设名>`），打 `manual` 标签、优先级 1000+，不参与自动选型；继承主配置 base_url/api_key | |
| `BOT_MODEL_REGISTRY` | dict[str,dict] | `{}` | JSON：id → `{model(必填，缺则忽略该条目), base_url, api_key(str 或 list，支持 env:VAR), group, tags(list 或逗号串=思考强度档位), effort(可选 off/low/medium/high/xhigh/max), priority(默认100，越小越先)}` | | 多模型注册表（自动路由+故障转移）；**绝不放真实 key，用 `env:BOT_API_KEY_*`**；api_key 支持列表做同模型多密钥转移。tags=档位体系（2026-09 改版）：deepseek/glm/kimi/minimax=low,high,max；gpt/grok=low,medium,high,xhigh；gemini=low,medium,high。样例中 `key_group`/`last_resort` 字段路由器**不解析**（仅注释性） | 注册表存在时主配置模型退居兜底（priority 2000, manual） |
| `BOT_MODEL_SCHEDULE` | str(dict) | `{}` | JSON：`{"HH:MM-HH:MM":"预设或注册表id"}`；支持跨零点 `"23:00-07:00"` | ✅热更 | 分时段自动切**单个模型**；窗口外回自动选型（与优先级分组互不影响） | 热更时存 JSON 字符串原样，调度器解析 |
| `BOT_MODEL_PRIORITY_GROUPS` | list[dict] | `[]` | JSON 数组：`[{"name","days"(ISO 周编号 1-7，缺省=每天),"windows"([["HH:MM","HH:MM"]]，缺省=全天),"order"(模型id 列表)]}`；days/windows 都缺省=兜底组 | ✅热更 | 时段优先级分组（峰谷顺序）：按列表顺序取**第一个命中**的组，命中组按 order 排序、组外模型按 priority 追加；每条消息实时判定（`BOT_TIMEZONE`）；只影响自动路由，手动 set 不受影响 | 前置校验 `_parse_model_priority_groups`；热更存规范化 JSON 字符串（`_model_priority_groups_converter`） |
| `BOT_MODEL_PRICES` | dict[str,dict] | `{}` | JSON：`{"模型名":{"input":元/1M,"output":元/1M}}` | ✅热更 | 每模型价格；成本按**调用时刻**价格记账（毫厘），调价不影响历史账单（峰谷差价天然正确）；未配置价格的模型不计费 | `/bot model price` 热维护；账单在 `/bot model usage` |
| `BOT_USAGE_MONITOR_ENABLED` | bool | `True` | | | 用量监控总开关（阈值提醒 + 定时报告，走管理员预警管线） | 无管理员 id 时自动禁用 |
| `BOT_USAGE_ALERT_OUTPUT_TOKENS` | int | `5000000` | ≥0 | | 单模型当日输出 token 提醒阈值 | 每 60 秒巡检当日聚合，每项每天只提醒一次 |
| `BOT_USAGE_ALERT_INPUT_TOKENS` | int | `50000000` | ≥0 | | 单模型当日输入 token 提醒阈值 | 同上 |
| `BOT_USAGE_ALERT_DAILY_COST_YUAN` | float | `10.0` | ≥0 | | 当日实际账单提醒阈值（元） | 超限立即发 Mica 报告卡+提醒（含各模型金额） |
| `BOT_USAGE_REPORT_HOURS` | str | `"13,18,23"` | 逗号分隔整点 0-23 | | 定时报告时间点（北京时间整点）；报告窗口=自上个报告点至今；**13 点报告额外附过去 24 小时总花费** | APScheduler CronTrigger；报告时间点持久化 |
| `BOT_USAGE_REPORT_STATE_FILE` | str | `"data/usage_report_state.json"` | 路径 | | 报告时间点状态文件（重启不丢） | 相对路径重定向到 Runtime data |
| `BOT_MODEL_AUTO_ROUTE` | bool | `True` | | | 自动选型开关：按时段分组/priority 顺序自动选型（runtime_admin 消费） | 复杂任务关键词现仅用于思考强度升档，不再分桶排序 |

**模型路由补充语义**（model_router.py，2026-09 改版）：自动候选顺序 = `BOT_MODEL_PRIORITY_GROUPS` 命中组的 order（未命中则 priority 升序，manual 排除）；思考深度由档位体系负责——每次调用按 条目 effort > 全局 `BOT_CHAT_REASONING_EFFORT` > 家族默认最高档 发送 `reasoning_effort`，复杂任务（≥300 字或关键词）把全局/默认档升到家族最高档；手动指定 id 失败仍按优先级转移；未知覆盖 id 当作完整模型名走主配置接口；每次生成前合并**运行时注册表**（改动即生效）；仅 `timeout/network/server/rate_limited/provider_error/empty_response/model_not_found/unsupported_model` 触发转移，`auth/config_missing/schema/invalid_request` 立即抛出；`reasoning_effort` 遇 `unsupported_parameter` 自动去参重试一次；LLM 请求代理复用 `BOT_DOWNLOAD_PROXY`；推理模型 content 为空时回退 `reasoning_content` 尾部 600 字并打 `content_source=reasoning_fallback` 标记；usage 归一化缓存字段（`prompt_cache_hit_tokens`/`prompt_tokens_details.cached_tokens`/`cache_creation_input_tokens` 等）。

### A13 联网检索与分类遥测（8 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEB_SEARCH_ENABLED` | bool | `False` | | ✅热更 | 现实时效问题按需联网；开启后仅强信号（新闻/价格/汇率等）触发；世界观问题永远只走本地知识库 | |
| `BOT_WEB_SEARCH_TIMEOUT_SECONDS` | float | `3.0` | >0 | | 单次检索超时 | |
| `BOT_WEB_SEARCH_MAX_RESULTS` | int | `20` | ≥0；0=不限制（内部有安全上限） | | 检索条数上限 | |
| `BOT_WEB_SEARCH_ADMIN_NOTICE` | bool | `False` | | ✅热更 | 管理员私聊显示检索提示（仅有真实结果链接时追加） | 依赖管理员身份 |
| `BOT_WEB_INTENT_TELEMETRY_ENABLED` | bool | `False` | | | 联网分类遥测：只记录查询哈希/决策/置信度/命中统计，不记原文 | |
| `BOT_WEB_INTENT_TELEMETRY_DB_PATH` | str | `data/web_intent_telemetry.sqlite3` | 路径 | | 遥测库 | |
| `BOT_WEB_INTENT_TELEMETRY_MAX_ITEMS` | int | `10000` | ≥0 | | 遥测条数上限 | |
| `BOT_WEB_CLASSIFIER_SHADOW_ENABLED` | bool | `False` | | | 同时记录旧版分类标签做影子对比；不改变线上决策 | |

### A14 内容解析、抓取与解析历史（10 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CONTENT_PARSE_ENABLED` | bool | `True` | | | 平台链接识别→解析→信息卡总开关 | |
| `BOT_CONTENT_PARSE_PLATFORMS` | list[str] | `[]` | 空=全部；合法平台：bilibili, douyin, xiaohongshu, youtube, twitter, xiaoheihe, miyoushe, skland, kurobbs, netease_music, qqmusic, kuwo, kugou, apple_music, spotify（小写化） | | 平台白名单 | |
| `BOT_FETCH_TIMEOUT_SECONDS` | float | `10.0` | >0 | | 解析/点歌统一超时 | |
| `BOT_COOKIES_FILE` | str | `""` | Netscape 格式 Cookie 文件路径（空=匿名解析；密钥类，路径可配、内容绝不外泄） | | 给 B站/小红书/抖音/QQ音乐/网易云/推特等解析与点歌加登录态（样例 data/platform_cookies.txt ⚠️） | data/ 重定向 |
| `BOT_PARSE_HISTORY_ENABLED` | bool | `True` | | | 解析历史落盘 | |
| `BOT_PARSE_HISTORY_DB_PATH` | str | `data/parse_history.sqlite3` | 路径 | | 历史库 | |
| `BOT_PARSE_HISTORY_MAX_ITEMS` | int | `2000` | ≥0 | | 条数上限 | |
| `BOT_MEDIA_ANALYZE_ENABLED` | bool | `True` | | | 解析视频时附加分辨率/时长/HDR/音频分析（yt-dlp） | 下载走 `/bot download` |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool | `True` | | ✅热更 | 解析器给出视频直链时自动下载并随卡发送；失败/超限静默降级为「下载：」提示 | 受下载上限约束 |
| `BOT_FETCH_PLAYWRIGHT_ENABLED` | bool | `True` | | | 抓取层允许 Playwright 渲染 | 与订阅 Playwright 轮询区分 |

### A15 下载与缓存配额（10 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DOWNLOAD_DIR` | str | `data/downloads` | 路径 | | 下载目录 | |
| `BOT_DOWNLOAD_MAX_BYTES` | int | `1073741824` | ≥0（1 GiB） | | 单文件大小上限 | |
| `BOT_DOWNLOAD_MAX_HEIGHT` | int | `0` | ≥0；0=不限 | | 视频最大分辨率（高） | |
| `BOT_DOWNLOAD_TIMEOUT_SECONDS` | int | `600` | >0 | | 下载超时 | |
| `BOT_DOWNLOAD_CACHE_MAX_BYTES` | int | `2147483648` | ≥0（2 GiB） | | 下载目录配额，最旧优先清理 | |
| `BOT_DOWNLOAD_CACHE_MAX_AGE_DAYS` | int | `7` | ≥0 | | 下载保留天数 | |
| `BOT_MUSIC_CACHE_MAX_BYTES` | int | `536870912` | ≥0（512 MiB） | | 点歌缓存配额 | |
| `BOT_CARD_CACHE_MAX_BYTES` | int | `268435456` | ≥0（256 MiB） | | 卡片缓存配额 | |
| `BOT_MEME_CACHE_MAX_BYTES` | int | `268435456` | ≥0 | | 表情缓存配额 | |
| `BOT_DOWNLOAD_PROXY` | str | `""` | `http://127.0.0.1:7890` 形式；空=直连（样例 7890 ⚠️） | | 下载代理；**同时是 LLM 请求的代理来源**（model_router 复用） | |

### A16 卡片渲染与转发渲染（9 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CARD_RENDER_ENABLED` | bool | `True` | | | 解析结果渲染 PNG 卡片 | |
| `BOT_CARD_RENDER_BACKEND` | str | `playwright` | `playwright` / `null` | | 渲染后端 | |
| `BOT_CARD_RENDER_DIR` | str | `data/cards` | 路径 | | 卡片输出目录 | |
| `BOT_CARD_ASSET_DIR` | str | `""` | 路径 | | 外置卡片 SVG 资源目录；空=bridge 自动发现同级 ChatBot_Runtime | |
| `BOT_CARD_UI_SCALE` | float | `1.25` | >0（1.0=100%） | | 信息卡整体 UI 缩放，viewport 等比放大 | |
| `BOT_HELP_CARD_COLOR` | str | `""` | 十六进制色；空=中性灰（**模板禁止写死品牌色**，tint 一律由主色派生） | | 帮助页卡片主色 | 遵循 Mica 规范（AGENTS.md） |
| `BOT_RENDER_FORWARD_MIN_CHARS` | int | `1500` | ≥0（样例 0 ⚠️） | | 长文本转合并转发的最小字符数 | |
| `BOT_RENDER_FORWARD_MAX_NODES` | int | `0` | ≥0；0=不限 | | 转发节点数上限 | |
| `BOT_RENDER_FORWARD_NODE_CHARS` | int | `900` | ≥0 | | 单节点字符数 | |

### A17 天气 / Wiki / Epic / 历史上的今天 / 节假日（13 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEATHER_ENABLED` | bool | `False` | | | 天气上下文注入开关（给人格用） | 与 `BOT_WEATHER_QUERY_ENABLED`（指令查询）是两个独立开关 |
| `BOT_WEATHER_LATITUDE` | float | `0.0` | 纬度（样例 22.3193） | | 上下文天气坐标 | |
| `BOT_WEATHER_LONGITUDE` | float | `0.0` | 经度（样例 114.1694） | | 同上 | |
| `BOT_WEATHER_CACHE_SECONDS` | int | `1800` | ≥0 | | 上下文天气缓存 | |
| `BOT_WEATHER_TIMEOUT_SECONDS` | float | `8.0` | >0 | | 上下文天气超时 | |
| `BOT_WEATHER_QUERY_ENABLED` | bool | `True` | | | 「天气 <城市>」指令（中国气象局 NMC，免 key） | |
| `BOT_WIKI_ENABLED` | bool | `True` | | | 「维基 <词条>」（MediaWiki 公开 API，免 key） | |
| `BOT_WIKI_LANG` | str | `zh` | 语言代码 | | 维基语言 | |
| `BOT_EPIC_ENABLED` | bool | `True` | | | 「epic」每周免费游戏（Epic 公开接口，免 key） | |
| `BOT_TODAY_HISTORY_ENABLED` | bool | `True` | | | 「历史上的今天」查询+每日推送（百度百科公开接口） | |
| `BOT_TODAY_HISTORY_PUSH_FILE` | str | `data/today_history_push.json` | 路径 | | 推送状态文件 | |
| `BOT_TODAY_HISTORY_CACHE_FILE` | str | `data/today_history_cache.json` | 路径 | | 每日缓存文件 | |
| `BOT_HOLIDAYS_FILE` | str | `""` | 路径（空=不用） | | 节假日数据文件 | 时间感知消费 |

### A18 表情包与图片识别（34 键）

**表情包搜索（3）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_SEARCH_ENABLED` | bool | `False` | | ✅热更 | 表情搜索开关 | |
| `BOT_MEME_SEARCH_TIMEOUT_SECONDS` | float | `8.0` | >0 | | 搜索超时 | |
| `BOT_MEME_SEARCH_CACHE_SECONDS` | int | `600` | ≥0 | | 搜索缓存 | |

**表情命令与本地 meme API（5）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_COMMAND_ENABLED` | bool | `True` | | | `/表情 列表`、`/表情 <key> <文字>`、`/meme help` 命令开关 | 依赖 meme API |
| `BOT_MEME_API_ENABLED` | bool | `False` | | | 对接本地 meme-generator-rs HTTP API | |
| `BOT_MEME_API_BASE_URL` | str | `http://127.0.0.1:2233` | URL | | API 地址 | |
| `BOT_MEME_API_TIMEOUT_SECONDS` | float | `15.0` | >0 | | API 超时 | |
| `BOT_MEME_API_OUTPUT_DIR` | str | `data/memes` | 路径 | | 生成图输出 | 受 `BOT_MEME_CACHE_MAX_BYTES` 配额 |

**群聊表情库 bot.meme_library（19）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_LIBRARY_ENABLED` | bool | `False` | | | 监听群图片→异步下载→MD5 去重入库；`/偷表情` 按权重随机发送 | |
| `BOT_MEME_LIBRARY_DIR` | str | `data/meme_library` | 路径 | | 图片库目录 | |
| `BOT_MEME_LIBRARY_DB_PATH` | str | `data/meme_library.sqlite3` | 路径 | | 库索引 | |
| `BOT_MEME_LIBRARY_MAX_FILE_BYTES` | int | `5242880` | ≥0（5 MiB） | | 单文件上限 | |
| `BOT_MEME_LIBRARY_MAX_FILES` | int | `20000` | ≥0 | | 文件总数上限 | |
| `BOT_MEME_LIBRARY_MAX_AGE_DAYS` | int | `30` | ≥0 | | 保留天数 | |
| `BOT_MEME_LIBRARY_COOLDOWN_SECONDS` | int | `20` | ≥0 | | 发送冷却 | |
| `BOT_MEME_LIBRARY_GROUP_ALLOWLIST` | list[str] | `[]` | 数字群号列表 | | 生效群白名单 | |
| `BOT_MEME_LIBRARY_GROUP_DENYLIST` | list[str] | `[]` | 数字群号列表 | | 禁用群黑名单 | |
| `BOT_MEME_LIBRARY_NSFW_MAX` | float | `0.2` | 0.0~1.0 | | 普通发送的 NSFW 分数上限 | |
| `BOT_MEME_LIBRARY_PREFER` | list[str] | `["守岸人","岸宝","鸣潮","战双帕弥什","库洛"]` | 标签列表（小写化） | | 优先标签 | |
| `BOT_MEME_LIBRARY_VLM_ENABLED` | bool | `False` | | | VLM 打标（标签+NSFW 评分）开关 | 需先配好 vlm 三件套 |
| `BOT_MEME_LIBRARY_VLM_MODEL` | str | `""` | 模型名 | | 视觉模型名 | |
| `BOT_MEME_LIBRARY_VLM_BASE_URL` | str | `""` | URL | | 视觉接口 | |
| `BOT_MEME_LIBRARY_VLM_API_KEY` | str | `""` | 密钥（占位） | | 视觉密钥 | |
| `BOT_MEME_LIBRARY_VLM_TIMEOUT_SECONDS` | float | `20.0` | >0 | | 视觉超时 | |
| `BOT_MEME_LIBRARY_VLM_PRESET` | str | `deepseek-vision` | 预设名（样例为空 ⚠️） | | 识图模型预制接口预设 | 配合 `BOT_VISION_MODEL_REGISTRY` |
| `BOT_MEME_LIBRARY_NSFW_DELETE` | float | `0.8` | 0.0~1.0 | | NSFW 直接删除阈值（淫秽色情不存储，删文件+记录） | |
| `BOT_MEME_LIBRARY_PROXY` | str | `""` | 代理 URL；空=直连 QQ 多媒体源（外网源可走 7890） | | 群图下载代理 | 独立于 `BOT_DOWNLOAD_PROXY` |

**图片/表情识别 bot.vision（7）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_VISION_MODEL_REGISTRY` | dict[str,Any] | `{}` | JSON 注册表（模型/接口/密钥等条目） | | 识图模型注册表（预设名+注册表机制） | 与运行时 vision_registry 叠加（见 C 节） |
| `BOT_VISION_ENABLED` | bool | `False` | | ✅热更 | 聊天图片/表情识别开关；启用**且**注册表有可用模型才调 VLM | |
| `BOT_VISION_MODE` | str | `relay` | `relay`（视觉模型先转文字）/ `direct`（图片直传 tags 含 vision/multimodal/vlm 的主模型，失败只回退一次 relay） | ✅热更 | 识别模式 | direct 依赖主模型带视觉 tags |
| `BOT_VISION_TIMEOUT_SECONDS` | float | `20.0` | >0 | | 识别超时 | |
| `BOT_VISION_MAX_IMAGES` | int | `2` | ≥0 | | 单次识别图片数上限 | |
| `BOT_VISION_MAX_CHARS` | int | `500` | ≥0 | | 识别描述字数上限 | |
| `BOT_VISION_REPLY_PROBABILITY` | float | `1.0` | 0.0~1.0（.env 缺） | | 白名单1 群图片回复概率：1.0=发图即识别回应；0=仅 @ 时看图 | 配合群白1 策略 |

### A19 群聊策略与主动发言（15 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GROUP_BLACK1` | list[str] | `[]` | 数字群号列表 | ✅热更 | black1=完全静默只接收不发送 | 四档互斥：按 black1>black2>white1>white2 语义判定 |
| `BOT_GROUP_BLACK2` | list[str] | `[]` | 数字群号 | ✅热更 | black2=只回「@它且带指令」 | |
| `BOT_GROUP_WHITE1` | list[str] | `[]` | 数字群号 | ✅热更 | white1=正常回复+可按主动接话开关抽签 | 与 auto_reply_probability 联动 |
| `BOT_GROUP_WHITE2` | list[str] | `[]` | 数字群号 | ✅热更 | white2=只回「@它」或显式命令 | |
| `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED` | bool | `False` | | | 群聊自动接话总开关（点名/命令不受影响） | |
| `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY` | float | `0.05` | 0.0~1.0 | | 未点名群消息抽签概率（**确定性哈希**，非随机数） | |
| `BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR` | int | `6` | ≥0 | | 每小时主动回复上限 | |
| `BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS` | int | `90` | ≥0 | | 主动回复冷却 | |
| `BOT_NATURAL_COMMAND_ENABLED` | bool | `True` | | | 自然语言命令层（基层路由优先级 45）：「帮我查天气」等归一化执行 | |
| `BOT_SHARED_GROUP_CONTEXT_ENABLED` | bool | `False` | | | 跨实例共享群上下文 | |
| `BOT_GROUP_DIGEST_ENABLED` | bool | `False` | | | 群摘要开关 | |
| `BOT_GROUP_DIGEST_MAX_TURNS` | int | `150` | ≥0（样例 20 ⚠️） | | 摘要覆盖轮数 | |
| `BOT_GROUP_DIGEST_MAX_CHARS` | int | `800` | ≥0 | | 摘要字符上限 | |
| `BOT_GROUP_DIGEST_LLM_ENABLED` | bool | `False` | | | 摘要用 LLM 精炼 | 依赖 LLM 引擎 |
| `BOT_GROUP_DIGEST_LLM_TTL_SECONDS` | int | `3600` | ≥0 | | LLM 摘要缓存 TTL | |

### A20 点歌与音乐（8 键 + 1 个运行时专属键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MUSIC_ENABLED` | bool | `True` | | | 「点歌 <关键词>」开关 | |
| `BOT_MUSIC_PLATFORMS` | list[str] | `[]` | 空=默认顺序：网易云→Apple→酷狗→QQ→酷我→Spotify | | 搜索顺序白名单 | |
| `BOT_MUSIC_ANALYTICS_ENABLED` | bool | `True` | （.env 缺） | | 点歌行为分析：只记成功结果，不记原始查询词 | |
| `BOT_MUSIC_ANALYTICS_DB_PATH` | str | `data/music_analytics.sqlite3` | 路径（.env 缺） | | 分析库 | |
| `BOT_MUSIC_ANALYTICS_RETENTION_DAYS` | int | `365` | ≥0（.env 缺） | | 分析数据保留天数 | |
| `BOT_MUSIC_CHART_ENABLED` | bool | `False` | （.env 缺） | | 音乐榜单开关 | |
| `BOT_MUSIC_CHART_SOURCES` | dict[str,Any] | `{}` | JSON（.env 缺） | | 榜单数据源配置 | |
| `BOT_MUSIC_CHART_POLL_INTERVAL_SECONDS` | int | `3600` | ≥0（.env 缺） | | 榜单轮询间隔 | |
| `BOT_MUSIC_MODE` * | str | 运行时缺省 `card` | `audio`/`voice`/`link`/`card`（中文别名：音频/语音/链接/卡片；default→card） | ✅热更 | **config.py 无此字段**，纯运行时覆盖键：点歌返回形态；未设置时代码回退 `card` | 仅存于 settings 覆盖层 |

### A21 订阅系统 bot.subscribe（17 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SUBSCRIBE_ENABLED` | bool | `True` | | | 定时拉取平台新内容并推送 | |
| `BOT_SUBSCRIBE_DB_PATH` | str | `data/subscriptions.sqlite3` | 路径 | | 订阅库 | |
| `BOT_SUBSCRIBE_POLL_INTERVAL_SECONDS` | int | `300` | ≥0 | | 常规轮询间隔 | |
| `BOT_SUBSCRIBE_LIVE_POLL_SECONDS` | int | `60` | ≥0 | | 直播类快速轮询 | |
| `BOT_SUBSCRIBE_DIGEST_HOUR` | int | `20` | 0~23 | | 日报小时 | 与分钟组成推送时刻 |
| `BOT_SUBSCRIBE_DIGEST_MINUTE` | int | `0` | 0~59 | | 日报分钟 | |
| `BOT_SUBSCRIBE_MAX_ITEMS_PER_TICK` | int | `20` | ≥0 | | 单轮最大处理条数 | |
| `BOT_SUBSCRIBE_JITTER_RATIO` | float | `0.20` | 0.0~1.0（.env 缺） | | 轮询抖动比例 | |
| `BOT_SUBSCRIBE_GLOBAL_CONCURRENCY` | int | `3` | ≥1（.env 缺） | | 全局并发 | |
| `BOT_SUBSCRIBE_PLATFORM_CONCURRENCY` | int | `1` | ≥1（.env 缺） | | 单平台并发 | |
| `BOT_SUBSCRIBE_MIN_INTERVAL_SECONDS` | float | `1.0` | ≥0（.env 缺） | | 平台请求最小间隔 | |
| `BOT_SUBSCRIBE_LEASE_SECONDS` | int | `120` | ≥0（.env 缺） | | 任务租约时长 | |
| `BOT_SUBSCRIBE_RETRY_BASE_SECONDS` | int | `60` | ≥0（.env 缺） | | 重试基础间隔 | |
| `BOT_SUBSCRIBE_RETRY_CAP_SECONDS` | int | `1800` | ≥base（.env 缺） | | 重试间隔上限 | |
| `BOT_SUBSCRIBE_OUTBOX_INTERVAL_SECONDS` | int | `15` | ≥0（.env 缺） | | 发件箱扫描间隔 | |
| `BOT_SUBSCRIBE_CARD_ENABLED` | bool | `True` | | | 即时推送附带解析卡片图（kind=mixed）；渲染失败自动回退纯文本 | 依赖卡片渲染 |
| `BOT_SUBSCRIBE_PLAYWRIGHT_POLL_SECONDS` | int | `1800` | ≥0 | | Playwright 类源轮询间隔 | 依赖 `BOT_FETCH_PLAYWRIGHT_ENABLED` |

### A22 凭据检查（6 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CREDENTIALS_FILE` | str | `""` | 路径（Cookie 文件；密钥类，内容绝不外泄） | | 平台凭据文件 | |
| `BOT_CREDENTIAL_WARN_DAYS` | int | `7` | ≥0 | | 到期预警天数 | |
| `BOT_CREDENTIAL_PROBE_URLS` | dict[str,str] | `{}` | JSON：名称→探测 URL | | 凭据可用性探测地址 | |
| `BOT_CREDENTIAL_PROBE_TIMEOUT_SECONDS` | float | `8.0` | >0 | | 探测超时 | |
| `BOT_CREDENTIAL_CHECK_ENABLED` | bool | `False` | | | 周期凭据检查开关 | |
| `BOT_CREDENTIAL_CHECK_INTERVAL_HOURS` | int | `6` | ≥1 | | 检查间隔（小时） | |

### A23 术语表与用户档案（4 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GLOSSARY_FILES` | list[str] | `[]` | 文档路径 | | 术语表文件 | |
| `BOT_GLOSSARY_MAX_ENTRIES` | int | `30` | ≥0 | | 注入词条数上限 | |
| `BOT_GLOSSARY_MAX_CHARS` | int | `1500` | ≥0 | | 注入字符上限 | |
| `BOT_USER_PROFILES_FILE` | str | `""` | 路径（空=不用） | | 用户画像文件 | |

### A24 速率限制与免打扰（14 键）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_RATE_LIMIT_ENABLED` | bool | `True` | | | 限速总开关 | |
| `BOT_RATE_LIMIT_WINDOW_SECONDS` | int | `60` | ≥1 | | 滑动窗口长度 | |
| `BOT_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS` | int | `60` | ≥0 | | 全局窗口内聊天请求上限 | |
| `BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS` | int | `6` | ≥0（样例 12 ⚠️） | | 单会话上限 | |
| `BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS` | int | `4` | ≥0（样例 8 ⚠️） | | 单用户上限 | |
| `BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` | int | `0` | ≥0 | | 同目标最小间隔 | |
| `BOT_RATE_LIMIT_BYPASS_ROLES` | list[str] | `["admin"]` | 角色名列表 | | 限速豁免角色 | |
| `BOT_RATE_LIMIT_DB_PATH` | str | `""` | 路径；非空=sqlite，空=内存 | | 限速持久化 | readiness 汇报 store |
| `BOT_QUIET_HOURS_ENABLED` | bool | `True` | | | 免打扰总开关 | |
| `BOT_QUIET_HOURS_START` | str | `00:00` | `HH:MM` | | 开始时刻 | |
| `BOT_QUIET_HOURS_END` | str | `06:00` | `HH:MM` | | 结束时刻 | 支持跨零点 |
| `BOT_QUIET_HOURS_TIMEZONE` | str | `Asia/Hong_Kong` | IANA 时区 | | 免打扰时区（独立于 `BOT_TIMEZONE`） | |
| `BOT_QUIET_HOURS_SESSION_TYPES` | list[str] | `["group"]` | 会话类型列表 | | 适用的会话类型 | |
| `BOT_QUIET_HOURS_BYPASS_ROLES` | list[str] | `["admin"]` | 角色名列表 | | 豁免角色 | |

### A25 非 Config 键（`.env.example` 存在、但由其他组件消费，不属于本 Config）

| 键名 | 消费方 | 说明 |
|---|---|---|
| `MAIL_BOTS` / `TELEGRAM_BOTS` | 邮件/Telegram 插件 | JSON 数组；含账号令牌，占位配置、绝不粘贴真实值到对话 |
| `TELEGRAM_PROXY` / `TELEGRAM_WEBHOOK_URL` | Telegram 插件 | 代理与 webhook |
| `MCP_CACHE_TTL` / `MCP_SERVERS` / `MCP_TOOL_TIMEOUT` | nonebot-plugin-mcpclient | 可选 MCP 工具；TTL 0=不过期 |
| `SQLALCHEMY_DATABASE_URL` | 可选 ORM | 样例含 `CHANGE_ME` 占位口令 |
| `LOCALSTORE_USE_CWD` / `LOCALSTORE_CACHE_DIR` / `LOCALSTORE_CONFIG_DIR` / `LOCALSTORE_DATA_DIR` | nonebot-plugin-localstore | 第三方本地存储，指向工作区外 Runtime 目录 |

---

## B. 「LLM 引擎七必配键」专节

readiness 预检（`openai_compatible_preflight_errors` + provider 校验）对应的七个核心键；`BOT_CHAT_ENABLED=true` 是进入体检与对话的**总闸**（第八个隐含前提）。

### 1. `BOT_CHAT_PROVIDER`（默认 `static`）
- **说明**：引擎类型。`static` = 内置占位回复（readiness 出 warning `provider_not_real`，能本地跑但不接真模型）；`openai_compatible` = 真实 OpenAI 兼容引擎，触发全部七键预检。
- **合法值**：`static`、`openai_compatible`（仅此两个；其他值 → error `chat_provider_unsupported`）。
- **常见错误**：忘记从 `static` 改成 `openai_compatible`（机器人只会说"还没接上外面的模型"）；拼错 provider 名。

### 2. `BOT_CHAT_API_KEY`（默认空）
- **说明**：主密钥；同时是兼容性诊断的镜像 key。空或占位 → error `openai_api_key_missing`。
- **合法值**：非空，且不等于占位符黑名单（大小写不敏感）：`<api_key>`、`<real_api_key>`、`your-api-key`、`your_api_key`、`replace-me`、`replace_me`、`sk-your-api-key`、`test-key`。文档中一律写 `sk-xxxx` 占位。
- **常见错误**：直接抄 `.env.example` 占位符；服务端报 `auth`（HTTP 401/403 = key 无效/无权限/欠费，**不触发故障转移**，立即报错）。

### 3. `BOT_CHAT_BASE_URL`（默认 `https://api.openai.com/v1`）
- **说明**：OpenAI 兼容接口地址；可带或不带 `/chat/completions`（`normalize_openai_chat_endpoint` 自动补全）。
- **合法值**：`http(s)://` + 有效主机；**不得内嵌账号密码**（否则 `openai_base_url_unsafe`）；错误分三档：`openai_base_url_missing`（空）/ `openai_base_url_invalid`（协议或主机非法）/ `openai_base_url_unsafe`。
- **常见错误**：漏 `/v1`；`network`/`timeout`（连不上，查代理——LLM 请求走 `BOT_DOWNLOAD_PROXY`）；日志只显示脱敏端点（账号密码被替换为 `[redacted]`）。

### 4. `BOT_CHAT_MODEL`（默认 `static`）
- **说明**：主模型名。注册表为空时它是唯一模型；注册表在场时它退居兜底（manual、priority 2000）。
- **合法值**：非空且不在占位名单：`<model_name>`、`your-model-name`、`your_model_name`、`replace-me`、`replace_me`、`model-name`；热更时**长度 ≤64 字符**（`_model_converter`）。
- **常见错误**：`model_not_found`/`unsupported_model`（中转站没注册该模型，会自动转移下一候选）；手动指定未知 id 会被当作完整模型名走主配置接口。

### 5. `BOT_CHAT_TEMPERATURE`（默认 `0.7`）
- **说明**：采样温度。
- **合法值**：有限数且 **0.0 ≤ x ≤ 2.0**；NaN/Infinity/越界 → error `openai_temperature_invalid`。热更同范围（`_temperature_converter`）。
- **常见错误**：填负数或 >2；诊断调用自动钳到 min(温度, 0.3)。

### 6. `BOT_CHAT_MAX_TOKENS`（默认 `4096`）
- **说明**：正常聊天输出上限；命令能力用各自独立限制。
- **合法值**：整数 **≥0**；**0 = 不向 API 传 max_tokens（由模型自行决定）**；负数非法 → error `openai_max_tokens_invalid`。热更同规则（`_max_tokens_converter`）。
- **常见错误**：填负数；误以为 0 是"零输出"（实际是"不设上限"）。

### 7. `BOT_CHAT_TIMEOUT_SECONDS`（默认 `30.0`）
- **说明**：正常模式单模型请求超时；快速模式实际用 min(正常, `BOT_CHAT_FAST_TIMEOUT_SECONDS`)。
- **合法值**：有限数 **>0**（NaN/Infinity/≤0 → error `openai_timeout_seconds_invalid`）。
- **常见错误**：填 0；超过 `BOT_CHAT_FAILOVER_MAX_SECONDS` 时单次超时会被故障转移窗口压到剩余预算内。

**七键之外的关键配套**：`BOT_API_KEY_*` 五个凭据槽（供注册表 `env:` 引用，NoneBot dotenv 会放进 driver.config，**必须保留在 Config 字段里**，否则真实运行态拿到空 key）；`BOT_MODEL_REGISTRY` 条目内 api_key 支持列表做同模型多密钥转移；`reasoning_effort`（空/off=不发送；qwen/dashscope 转 `enable_thinking`；遇 `unsupported_parameter` 自动去参重试一次）；推理模型空 content 回退 `reasoning_content` 尾部 600 字。

---

## C. 热更机制说明

1. **白名单与转换器**：只有 `SETTABLE_KEYS` 中的键可热更（防止任意配置注入）。共 **23 键**（22 个对应 config.py 字段 + `BOT_MUSIC_MODE` 运行时专属键；2026-09 新增 `BOT_MODEL_PRIORITY_GROUPS`、`BOT_MODEL_PRICES`）。非白名单键 `set_override` 直接拒绝并提示可用键。
2. **可热更键全表**（键 → 转换规则）：

| 键 | 转换规则 |
|---|---|
| `BOT_CHAT_TEMPERATURE` | float，0.0~2.0 |
| `BOT_CHAT_MAX_TOKENS` | int，≥0（0=不设上限） |
| `BOT_CHAT_MODEL` | 非空且 ≤64 字符 |
| `BOT_CHAT_REASONING_EFFORT` | ``""``/off/low/medium/high/xhigh/max |
| `BOT_TRANSPORT_TIMEOUT_SECONDS` | float，(0,600]，拒绝 NaN/Infinity/空 |
| `BOT_MODEL_SCHEDULE` | JSON 对象字符串（如 `{"23:00-07:00":"luna"}`） |
| `BOT_MODEL_PRIORITY_GROUPS` | JSON 数组字符串（时段优先级分组，存规范化 JSON） |
| `BOT_MODEL_PRICES` | JSON 对象字符串（每模型价格表，存规范化 JSON） |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | int，≥200 |
| `BOT_MEME_SEARCH_ENABLED` | bool（true/1/yes/on/开/是 ↔ false/0/no/off/关/否） |
| `BOT_WEB_SEARCH_ENABLED` | bool |
| `BOT_WEB_SEARCH_ADMIN_NOTICE` | bool |
| `BOT_PERSONA_ACTION_BRACKETS` | bool |
| `BOT_MUSIC_MODE` | 音频/语音/链接/卡片（audio/voice/link/card） |
| `BOT_REPLY_DETAIL` | 详细/精简/默认（detail/concise/auto） |
| `BOT_VISION_ENABLED` | bool |
| `BOT_VISION_MODE` | relay/direct |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool |
| `BOT_GROUP_BLACK1/2、WHITE1/2` | 数字群号列表（逗号/分号/顿号/空白分隔或 JSON 数组） |

   群策略四档支持别名：`black1/黑1/黑名单一`、`white2/白2/白名單二` 等简繁变体（`GROUP_POLICY_MODE_ALIASES`）。
3. **生效方式**：
   - 覆盖值存 `<BOT_RUNTIME_SETTINGS_DIR>/runtime_settings_<实例>.json`（实例名 = `BOT_RUNTIME_INSTANCE`，空则自举为人格 profile id）；读取时经 **mtime 检测自动重载**，线程安全（锁），文件损坏安全降级为空存储。管理员改完**立即生效**（每次使用时经 `RuntimeSettingsStore.get` 读取覆盖值，未覆盖回退 config 字段），**无需重启**。
   - 多实例：管理员可用 `--instance <名称>` 修改其他实例的设置文件；目标实例进程下次读取时自动刷新。
   - `.env` 中的键若**不在**上述白名单：改完必须**重启进程**才生效（Config 在启动时一次性 model_validate）。
4. **设置入口**：`/bot runtime set <键> <值>`（仅 `BOT_ADMIN_USER_IDS` 管理员）；`reset` 可清空单个或全部覆盖。
5. **白名单之外、同样热生效的运行时数据**（走专用指令，不占 SETTABLE_KEYS）：多昵称增删、人格切换（persona_override）、人格权重（0.0~1.0 钳制）、**运行时模型注册表**（新增/修改/删除供应商条目，每次生成前合并、条目变更即丢弃 provider 缓存）、**运行时视觉模型注册表**。
6. **典型示例**（来自 .env.example 注释）：`/bot runtime set BOT_TRANSPORT_TIMEOUT_SECONDS <秒>` 热改发送硬超时，超时不自动重发正文。

---

## D. config_readiness 校验规则清单

### D1 密钥/模型占位符黑名单
- `has_real_api_key`（大小写不敏感、去空白）：空 = 无 key；黑名单：`<api_key>`、`<real_api_key>`、`your-api-key`、`your_api_key`、`replace-me`、`replace_me`、`sk-your-api-key`、`test-key`。
- `is_placeholder_model`：空 = 无模型；黑名单：`<model_name>`、`your-model-name`、`your_model_name`、`replace-me`、`replace_me`、`model-name`。

### D2 base_url 规则
- 空 → `openai_base_url_missing`；scheme 非 http/https 或无 netloc → `openai_base_url_invalid`；URL 内嵌 username/password → `openai_base_url_unsafe`（安全展示时会脱敏为 `[redacted]@host`）。

### D3 生成参数规则（`llm_generation_parameter_errors`）
- temperature：有限数且 0.0 ≤ x ≤ 2.0，否则 `openai_temperature_invalid`。
- max_tokens：非 bool 且 ≥0（0=不设上限），否则 `openai_max_tokens_invalid`。
- timeout：有限数且 >0，否则 `openai_timeout_seconds_invalid`。

### D4 `run_config_smoke` 完整错误（errors，任一存在 → ok=false）
| 错误码 | 触发条件 |
|---|---|
| `chat_disabled` | `BOT_CHAT_ENABLED=false` |
| `persona_files_empty` | `BOT_PERSONA_FILES` 为空 |
| `persona_file_missing` | 任一人格文件不存在 |
| `persona_file_unsupported` | 扩展名不在 `{.md, .txt, .docx}` |
| `persona_file_unreadable` | 文档解析抛异常（只给计数不给原始错误） |
| `persona_file_empty` | 解析后文本为空 |
| `knowledge_file_missing` / `knowledge_file_unsupported` / `knowledge_file_unreadable` | 知识文件同上三种问题 |
| `chat_provider_unsupported` | provider 既非 static 也非 openai_compatible |
| `openai_api_key_missing` / `openai_model_missing` / `openai_base_url_*` / `openai_temperature_invalid` / `openai_max_tokens_invalid` / `openai_timeout_seconds_invalid` | provider=openai_compatible 时的七键预检 |

### D5 警告（warnings，不阻断）
| 警告码 | 触发条件 |
|---|---|
| `provider_not_real` | provider=static |
| `persona_profile_weak` | 人格总量字符 <10 或有效行 <2（`PERSONA_PROFILE_MIN_CHARS=10`、`MIN_MEANINGFUL_LINES=2`）；完全不可读时状态为 missing |
| `knowledge_files_empty` | 知识文件列表为空 |
| `knowledge_file_empty` | 知识文件解析后为空 |

### D6 就绪判定与产出
- `ready_for_real_llm` = 无 error 且 provider=openai_compatible 且 key 已设 且 model 非空 且 base_url 合法。
- `llm_readiness_status`：`ready`（可接真实 LLM）→ 下一步 `llm_smoke`；`blocked`（有 error）→ 下一步 `fix_config`；`local_only`（无 error 但未接真实 provider）→ 下一步 `configure_real_llm`。
- `llm_fix_hints`：按错误码给出修复提示（如 `chat_disabled → BOT_CHAT_ENABLED=true`、`openai_base_url_unsafe → remove_credentials_from_BOT_CHAT_BASE_URL`、`openai_max_tokens_invalid → BOT_CHAT_MAX_TOKENS>=0（0=不设上限）`）。
- 诊断辅助钳制：诊断 LLM 温度 = 有效时 min(温度, 0.3)，无效时 0.0；诊断 max_tokens = ≤0 时取 128，否则 min(配置, 128)。
- 附带汇报：runtime/chat/memory/history/emotion/限速（含 store=sqlite|memory）/免打扰/诊断/审计/回执/发送队列（含 store）各开关与关键数值；发送队列 store = enabled 且 db_path 非空 → sqlite，否则 memory。

---

## E. config.py 与 .env.example 差异汇总（以 config.py 为准）

**E1 样例值 ≠ 代码默认**（.env.example 给的是本机推荐值，代码默认仍是权威缺省）：`BOT_RUNTIME_DEFAULT_PERSONA`(shorekeeper/default)、`BOT_RUNTIME_DATA_DIR`(../ChatBot_Runtime/data/data)、`BOT_RUNTIME_INSTANCE`(空/default)、`BOT_PERSONA_PROFILE_ID`(shorekeeper/default)、`BOT_PERSONA_DISPLAY_NAME`(守岸人/报存)、`BOT_PERSONA_VERSION`(local/0)、`BOT_TONE_WARMTH`(0.8/0.7)、`BOT_TONE_DIRECTNESS`(0.4/0.5)、`BOT_GROUP_DIGEST_MAX_TURNS`(20/150)、`BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS`(12/6)、`BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS`(8/4)、`BOT_RENDER_FORWARD_MIN_CHARS`(0/1500)、`BOT_REPLY_DETAIL`(detail/auto)、四个 `BOT_REPLY_*_CONTEXT_BUDGET`(8192/8192/12288/8192 vs 2048/2560/3072/2048)、`BOT_KNOWLEDGE_CHUNK_CHARS`(600/900)、`BOT_KNOWLEDGE_MAX_CHUNKS`(2/4)、`BOT_KNOWLEDGE_TOP_K`(5/4)、`BOT_EMBEDDING_TIMEOUT_SECONDS`(30/15.0)、`BOT_CHAT_PROVIDER`(openai_compatible/static)、`BOT_CHAT_MODEL`(gpt-5.6-terra/static)、`BOT_CHAT_BASE_URL`(中转站/api.openai.com)、`BOT_CHAT_FAST_CONTEXT_BUDGET`(32768/9600)、`BOT_CHAT_FAST_WEB_MAX_QUERIES`(5/3)、`BOT_DOWNLOAD_PROXY`(7890/直连)、`BOT_COOKIES_FILE`(data/platform_cookies.txt/空)、`BOT_MEME_LIBRARY_VLM_PRESET`(空/deepseek-vision)；另 memory/history/diagnostics/audit/receipts/send_queue/rate_limit 的 db_path 代码默认空（内存/禁用），样例填了 `data/wuwa_*.sqlite3` 等具体文件。

**E2 `.env.example` 未列出（实际生效代码默认）**：`BOT_MUSIC_ANALYTICS_ENABLED/DB_PATH/RETENTION_DAYS`、`BOT_MUSIC_CHART_ENABLED/SOURCES/POLL_INTERVAL_SECONDS`、`BOT_VISION_REPLY_PROBABILITY`、`BOT_SUBSCRIBE_JITTER_RATIO/GLOBAL_CONCURRENCY/PLATFORM_CONCURRENCY/MIN_INTERVAL_SECONDS/LEASE_SECONDS/RETRY_BASE_SECONDS/RETRY_CAP_SECONDS/OUTBOX_INTERVAL_SECONDS`（共 15 键）。

**E3 `.env.example` 有而 Config 无**：`MAIL_BOTS`、`TELEGRAM_BOTS`、`TELEGRAM_PROXY`、`TELEGRAM_WEBHOOK_URL`、`MCP_CACHE_TTL/SERVERS/TOOL_TIMEOUT`、`SQLALCHEMY_DATABASE_URL`、`LOCALSTORE_*`（4 键）——由邮件/Telegram 插件、MCP 插件、可选 ORM、nonebot-plugin-localstore 消费。

**E4 热更层特有**：`BOT_MUSIC_MODE` 只存在于 `SETTABLE_KEYS`（config.py 无字段），未设置时运行时回退 `card`；`.env.example` 的 `BOT_MODEL_REGISTRY` 样例中的 `key_group`/`last_resort` 字段模型路由器**不解析**，仅作人工注释。
