# ChatBot（bot_unified_runtime）全量配置键目录

> 配套文档：总览与指令见 [ai-setup-knowledge-pack.md](ai-setup-knowledge-pack.md)（本文档是其 §6 的完整展开版）。
> 数据来源：`plugins/bot_unified_runtime/config.py`（字段全集以 config.py 为权威；**计数不在此手写——`bot_*` 字段数以机器册 `docs/auto-facts.md` 为准**，2026-09-13 曾核为 485、当日后即过期一次，本目录按功能域收录、批次增量统一补录于 A26；2026-09-13 三期收尾：52 键清尾后键覆盖与 config.py 全量同步（门禁 KNOWN_MISSING 白名单清零））、`.env.example`、`plugins/bot_unified_runtime/config_readiness.py`、`plugins/bot_unified_runtime/runtime/settings.py`、`plugins/bot_unified_runtime/llm/providers.py`、`plugins/bot_unified_runtime/llm/model_router.py`；另以 grep 佐证 `character/documents.py` 与 `capabilities/music.py`、`capabilities/runtime_admin.py`。
> 安全声明：本目录从未读取真实 `.env`，只引用 `.env.example`；全文不含任何真实密钥、Cookie、Token、QQ 号，密钥一律以 `sk-xxxx` / `env:变量名` / `<占位符>` 表示。
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](snowluma-setup.md)。

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
3. **路径重定向**：模型校验器 `_resolve_runtime_data_paths` 把 `data`、`data/...` 前缀的路径统一解析到 `BOT_RUNTIME_DATA_DIR`（相对路径以项目根为基准拼接）。受影响的路径字段全集由 `config.py` 的 `path_fields` 列表定义，另有若干文件列表字段（**数量不在此手写**；此处曾核为 39 + 4，其后即过期）（`bot_persona_files`、`bot_knowledge_files`、`bot_trend_files`、`bot_glossary_files`）。
4. **热更列（2026-09-20 CATALOG-FIX 三档制；白名单成员一律以代码为准，本文不抄成员与计数）**：
   - **✅热更** = 该键在 `domains/chat_reply/runtime/settings.py::SETTABLE_KEYS` 内，`/bot runtime set` 可写且消费方现读 ⇒ 写了即生效；
   - **🟡需重启** = 该键已登记同文件的 `RESTART_REQUIRED_KEYS`：`/bot runtime set` 拒写并提示需重启，改 `.env` 后重启生效；
   - **❌无热改面** = 上述两表均未登记 ⇒ 白名单外 `set_override` 直接拒绝；未进根 `__init__.py` 的合并层 `_RUNTIME_HOT_OVERRIDE_FIELDS` 者更是零消费面。改了不生效，须改 `.env` 并重启；
   - 空白 = 历史写法，语义为「不在白名单」，正逐步并档到上两档。已知例外若干枚实测在 `SETTABLE_KEYS` 而列仍空白（**欠标，非假标**，清单见文末 F 节），本席按「只改被证伪的」边界未动。
   本列旧版有 35 处键级「可热更」断言被代码逐条证伪并已回标；判定方法与逐条账见文末 F 节。常驻门 `tests/test_doc_sync_gates.py` 只查「键有没有登记」、**不查本列真假** ⇒ 本文任何标记与代码冲突时以代码为准。
5. **差异标注**：⚠️ = `.env.example` 样例值与 `config.py` 代码默认不一致（**以 config.py 为准**）；「.env 缺」= `.env.example` 未列出该键，实际生效代码默认。逐项汇总见第 E 节。

---

## A. 按功能域分组的配置键总表

### A1 运行时核心与日志（键数以本节为准）

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

**入站事件幂等（P0.4）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_EVENT_IDEMPOTENCY_ENABLED` | bool | `False` | | | 入站事件幂等表：重连重放的同事件对同一能力只处理一次；默认关闭，建议真实 NapCat 验收期间保持关闭、验收通过后再启用 | |
| `BOT_EVENT_IDEMPOTENCY_TTL_SECONDS` | float | `3600.0` | >0 | | 幂等记录存活时长 | |
| `BOT_EVENT_IDEMPOTENCY_MAX_ENTRIES` | int | `4096` | ≥0 | | 幂等表容量上限 | |
| `BOT_EVENT_IDEMPOTENCY_DB_PATH` | str | `""` | 路径（空=进程内表） | | 非空时用 SQLite 持久化幂等表（跨重启拦截重放） | data/ 重映射 |

**聊天管线与生成文件**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_PIPELINE_MAX_WORKERS` | int | `8` | 钳位 1..64 | | 聊天管线专用线程池 worker 数（管线检视 #4）：与默认线程池隔离，避免长任务挤占语音转码/kb 拉取等 to_thread；在途上限为 2 倍（含排队），超限快败记 `pipeline_busy` 审计 | |
| `BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS` | float | `400.0` | (0, 3600] 秒 | 🟡需重启 | 管线能力单次执行硬超时（超时改造 C1-a / 在册 M-4）：`offload_capability` 到点抛 `CapabilityTimeout` ⇒ 走 `_internal_error` 出统一诊断卡，能力挂死不再「白等到永远」。须严格大于 `BOT_REQUEST_BUDGET_SECONDS`，不足时消费点按「请求预算 + 60s」抬底并留 WARNING | 读点 `runtime/pipeline.py::_resolve_capability_hard_timeout_seconds`（池创建期缓存，同 `BOT_PIPELINE_MAX_WORKERS` 口径）；异常身份复用 `runtime/capability_protocols.py::CapabilityTimeout` |
| `BOT_GENERATED_FILES_DIR` | str | `data/generated_files` | 路径 | | 聊天回复生成文件落盘目录（`sources/file_reader.build_generated_file` 消费） | data/ 重映射收口 |
| `BOT_FILE_READ_MAX_CHARS` | int | `120000` | ≥0 | | 文件读取字符上限旋钮；当前源码内暂无读取点（仅 config.py 定义，预留） | |

**掉线管理员通知**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DISCONNECT_NOTICE_ENABLED` | bool | `False` | | | 掉线时 QQ 通道不可用，改走仍在线的 Telegram/邮件适配器与外部 HTTP 推送通知管理员；默认关闭，收件人必须显式配置，避免误发外部消息 | 消费方 `domains/ops/monitor/disconnect_notice.py` |
| `BOT_DISCONNECT_NOTICE_COOLDOWN_SECONDS` | float | `600.0` | ≥0 | | 同类掉线通知的冷却间隔（防重复告警） | |
| `BOT_DISCONNECT_NOTICE_MAIL_ACCOUNT` | str | `""` | | | 掉线通知发件邮箱账号 | 依赖邮件适配器账号配置 |
| `BOT_DISCONNECT_NOTICE_MAIL_RECIPIENTS` | list[str] | `[]` | JSON 数组字符串或列表 | | 掉线通知邮件收件人列表 | 裸 JSON 串兜底解码 |
| `BOT_DISCONNECT_NOTICE_TELEGRAM_CHAT_IDS` | list[str] | `[]` | JSON 数组字符串或列表 | | 掉线通知 Telegram 会话列表 | 裸 JSON 串兜底解码 |
| `BOT_DISCONNECT_NOTICE_SERVERCHAN_SENDKEY` | str | `""` | 密钥（占位） | | Server酱 HTTP 推送 SendKey（掉线时 QQ 不可用，走外部推送兜底） | |
| `BOT_DISCONNECT_NOTICE_PUSHPLUS_TOKEN` | str | `""` | 密钥（占位） | | PushPlus HTTP 推送 token | |

### A2 多实例共享与数据导出（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SHARE_ENABLED` | bool | `False` | | | 多实例共享开关 | 依赖 `BOT_SHARE_GROUPS` |
| `BOT_SHARE_GROUPS` | list[str] | `[]` | `"A and B"` 格式或 JSON 数组 | | 共享组名列表 | |
| `BOT_SHARE_READ_ONLY` | bool | `False` | | | 共享只读 | |
| `BOT_SHARED_EXPORT_ENABLED` | bool | `False` | | | 共享导出开关 | |
| `BOT_SHARED_EXPORT_INCLUDE_PRIVATE` | bool | `False` | | | 导出是否含私聊内容 | |
| `BOT_SHARED_EXPORT_MAX_CHARS` | int | `200` | ≥0 | | 单条导出截断长度 | |

### A3 权限与用户分级（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_ADMIN_USER_IDS` | list[str] | `[]` | 平台用户 id 列表 | | 管理员（唯一可执行 `/bot runtime set` 等） | 限速/免打扰 bypass、热更指令均依赖 |
| `BOT_SUPER_ADMIN_USER_IDS` | list[str] | `[]` | 平台用户 id 列表 | | 超级管理员（R1 2026-09-12）：权威高于 admin，人格层有专属保护规则；超管自动具备全部 admin 权限 | 自动叠加 `BOT_ADMIN_USER_IDS` 全部权限 |
| `BOT_ADMIN_PROFILES` | list[dict] | `[]` | JSON 数组字符串（裸 JSON 串兜底解码）：`[{"qq","name","nicknames","role","note"}]`；qq=QQ号，name=显示名，nicknames=别名（分隔符任意的单字符串），role=super/admin，note=补充 | | 管理团队身份档案（人格层注入） | 配合 `BOT_SUPER_ADMIN_USER_IDS` |
| `BOT_TELEGRAM_ADMIN_USER_IDS` | list[str] | `[]` | | | Telegram 侧管理员 | |
| `BOT_TELEGRAM_ADMIN_CHAT_IDS` | list[str] | `[]` | | | Telegram 侧管理会话 | 邮件通知发送目标相关 |
| `BOT_ENTERPRISE_USER_IDS` | list[str] | `[]` | | | 企业用户名单 | |
| `BOT_TRUSTED_USER_IDS` | list[str] | `[]` | | | 可信用户名单 | |
| `BOT_BLOCKED_USER_IDS` | list[str] | `[]` | | | 黑名单（拒绝服务） | |

### A4 GScore 对接（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GSCORE_ENABLED` | bool | `False` | | | GScore 第三方服务对接开关 | |
| `BOT_GSCORE_HOST` | str | `127.0.0.1` | 主机名/IP | | 服务地址 | |
| `BOT_GSCORE_PORT` | int | `8765` | 端口号 | | 服务端口 | |
| `BOT_GSCORE_WS_TOKEN` | str | `""` | 令牌；占位写入 `env:` 或本地 | | WebSocket 令牌（密钥类，输出占位） | |
| `BOT_GSCORE_MAX_RETRY` | int | `5` | ≥0 | | 连接重试次数 | |
| `BOT_GSCORE_BOT_ID` | str | `NoneBot2` | | | 上报的 bot 标识 | |
| `BOT_GSCORE_BOT_SELF_ID` | str | `""` | | | 账号 self_id | |

### A5 邮件桥与 Telegram 通知（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MAIL_BRIDGE_ENABLED` | bool | `False` | | | 邮件桥总开关 | |
| `BOT_MAIL_AUTO_REPLY_ENABLED` | bool | `False` | | | 邮件自动回复 | 依赖 bridge_enabled |
| `BOT_MAIL_NOTIFY_TELEGRAM_ENABLED` | bool | `True` | | | 新邮件通知 Telegram | 依赖 Telegram 管理配置 |
| `BOT_MAIL_BRIDGE_STATE_FILE` | str | `data/mail_bridge_state.json` | 路径 | | 桥接状态持久化 | data/ 重定向 |
| `BOT_MAIL_SENDER_ALIASES` | dict[str,str] | `{}` | JSON 对象：发件别名→真实地址 | | 发件人别名映射（示例文件中的 QQ/Foxmail 别名**不在此复述**） | |
| `BOT_MAIL_NOTIFY_PREVIEW_CHARS` | int | `280` | ≥0 | | 通知预览截断长度 | |

### A6 人格、昵称、别名、怪癖与会话身份（键数以本节为准）

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
| `BOT_SESSION_IDENTITY_DB_PATH` | str | `data/session_identity.sqlite3` | 路径 | | 会话级身份记忆（管理员设置）：每群/每私聊独立的 bot 称呼与身份标签 | data/ 重映射收口 |

**人格怪癖 bot.quirks（L4 审核制演化区，domains/chat_reply/character/quirks.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_QUIRKS_ENABLED` | bool | `True` | | | 人格演化区开关：核心人格文件永不自动改，习惯沉淀在怪癖库，管理员审核（approve）后才生效 | 夜间反思可自动投喂待审池（A26 `_reflection_quirks_*`） |
| `BOT_QUIRKS_DB_PATH` | str | `data/persona_quirks.sqlite3` | 路径 | | 怪癖库 | data/ 重映射收口 |
| `BOT_QUIRKS_MAX_ACTIVE` | int | `6` | ≥0 | | 同时生效怪癖数上限 | |

### A7 知识库与向量嵌入（键数以本节为准）

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

**Crawl Wiki 外部知识库 bot.kb_wiki（domains/location/knowledge/kb_wiki.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_KB_WIKI_ENABLED` | bool | `False` | | | Crawl Wiki 外部知识库开关：只读语料 → 独立向量库，hash 幂等增量同步（协议见 Crawl Wiki 仓 docs/KB_HANDOFF.md） | |
| `BOT_KB_WIKI_ROOT` | str | `""` | 路径（空=不用） | | Crawl Wiki 语料根目录 | |
| `BOT_KB_WIKI_DB_PATH` | str | `data/kb_wiki_embeddings.sqlite3` | 路径 | | 独立向量库存放。独立 db_path 是刻意的：人格知识库 sync_chunks 以文件清单为全集删除，与 7.5 万文档级 wiki 库不能共用一张表 | data/ 重映射 |
| `BOT_KB_WIKI_TOPICS` | str | `""` | 逗号分隔 topic 名（如 `梗知识,鸣潮`）；空=全部 topic | | topic 白名单 | |
| `BOT_KB_WIKI_TOP_K` | int | `4` | ≥0 | | 检索注入条数 | |
| `BOT_KB_WIKI_CHUNK_CHARS` | int | `800` | >0 | | 每块字符数 | |
| `BOT_KB_WIKI_EMBED_BATCH` | int | `128` | ≥1 | | 每批嵌入行数：本地 Ollama 实测 128 最快（约为批 10 的 6 倍吞吐）。批大小与嵌入超时是配比：装不下时嵌入侧按批折半自调（下限 10，恰好也是远程单批上限），所以超时偏短或回落远程链只降吞吐，不再整轮中止 | |
| `BOT_KB_WIKI_SYNC_HOUR` | int | `23` | 0~23 | | 每日增量同步时刻（时）；Crawl Wiki 每日 23:00 导出之后 | 与 `BOT_KB_WIKI_SYNC_MINUTE` 组成同步时刻 |
| `BOT_KB_WIKI_SYNC_MINUTE` | int | `40` | 0~59 | | 每日增量同步时刻（分） | |
| `BOT_KB_WIKI_SYNC_ON_STARTUP` | bool | `True` | | | 进程启动时也触发一次增量同步 | |

### A8 语气与回复控制（键数以本节为准）

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
| `BOT_REPLY_DETAIL` | str | `auto` | `auto`/`detail`/`concise`（热更接受中文别名 详细/精简/默认） | ✅热更 | 回复详略全局档；各档字数下限/上限唯一真身＝`chat.py:REPLY_LENGTH_TIERS`（本行不抄数值，抄一次过期一次——旧注释「detail=2000~4000 字」从未在判据里存在）（样例 detail ⚠️） | 被 `BOT_REPLY_POLICY_*` 的 per-user 永久策略覆盖 |
| `BOT_REPLY_POLICY_ENABLED` | bool | `True` | true/false | ❌重启 | 永久性 per-user 回复策略总闸（2026-09-28 用户裁定：有人要长、有人说"字太多短一点"即长期生效）；关＝读与写整条不存在 | 唯一咽喉 `character/reply_policy.py:shared_reply_policy_store`；优先级＝当轮明示 > 永久策略 > `BOT_REPLY_DETAIL` > 缺省档 |
| `BOT_REPLY_POLICY_DB_PATH` | str | `data/reply_policy.sqlite3` | 任意路径；`data/` 相对值经 runtime_paths 重映射 | ❌重启 | 策略库路径（表 `user_reply_policy`） | owner 登记见 `docs/db-owners.md`；store 懒建后进程级缓存，故非热更 |
| `BOT_REPLY_POLICY_PERSON_ALIASES` | dict[str,str] | `{}` | JSON 对象串，形如 `{"<本人号>": "<并入的目标号>"}`（左＝号，右＝并入的目标号；样例已填真实号对 ⚠️，写法照本列单花括号抄，双花括号是模板转义残留、写进 `.env` 解析必失败） | ❌重启 | 同一人多号并键（2026-09-28 用户裁定）：让一个人的多个号共用**同一行**回复偏好。🔴 只并「偏好存到哪个键」，**不并权限**——提权/角色/同意判定一律不读本键 | 归并只在 `character/reply_policy.py:ReplyPolicyStore` 一处咽喉（`canonical_person_key`），旧号那行在首次读主号键时前移一次并删旧行、不留第二真身；渗锁 `tests/test_reply_policy_permanent.py::test_person_aliases_never_leak_into_privilege` |
| `BOT_REPLY_DEFAULT_DIRECTIVES` | str | `literary_prose,imagery_rich` | 受控码或人话（`文学化`/`说人话`/`讲具体`/`铺意象`/`换意象`，逗号分号顿号竖线都认）；`off`/`none`/`关`/`不表态`＝不开 | ❌重启 | 默认讲法（2026-09-28 夜用户裁定「对没表过态的人：只回一段话，但要用自己的人格、世界观与意象来表达，别寡淡」）：只把**这个人没表态过的那一维**顶进提示词，本人明说过的永远优先 | 🔴 三态要分开：写成开⇒出指令；写成关⇒整块不渲染（与今天之前逐字节同形）；写成认不出的乱码⇒**也当没配**，绝不静默给全服派一份未知讲法。判据真身 `character/reply_policy.py::normalize_default_directives` 与补空维表 `_DEFAULT_SUPPRESSED_BY`；人话词表与 `/bot reply set` 共用 `_HUMAN_DIRECTIVE_WORDS`；读点 `reply_policy_section_for_turn`（现读装配期 config 快照，故列 RESTART）；锁 `tests/test_reply_style_imagery_default.py` |
| `BOT_REACTIONS_SENTIMENT_ENABLED` | bool | `True` | true/false | ❌重启 | 贴纸语义匹配判定腿总闸（她点名「报喜却发委屈/大哭，不行」）：贴之前读 bot 本轮实际回复文本，由大模型判受控情感闭集再选贴 | 真身 `domains/meme/reactions/sentiment_selector.py`；判不了/超时＝整轮不贴 |
| `BOT_REACTIONS_SENTIMENT_TIMEOUT_SECONDS` | float | `8.0` | >0 秒 | ❌重启 | LLM 情感判定超时预算（8s 量级＝宁可不贴也不拖慢下发） | 超时→`sentiment_unavailable` 可 grep 状态行 |
| `BOT_REACTIONS_SENTIMENT_CACHE_TTL_SECONDS` | int | `120` | ≥0 秒 | ❌重启 | 同会话判定缓存 TTL，让表情腿与表情包腿共用一次判定（成本意识：只在要贴时才问） | 0＝每腿各问 |
| `BOT_REPLY_DEFAULT_CONTEXT_BUDGET` | int | `2048` | ≥0（样例 8192 ⚠️） | | 默认场景上下文预算 | |
| `BOT_REPLY_SUPPORT_CONTEXT_BUDGET` | int | `2560` | ≥0（样例 8192 ⚠️） | | 安抚场景预算 | |
| `BOT_REPLY_DEEP_HELP_CONTEXT_BUDGET` | int | `3072` | ≥0（样例 12288 ⚠️） | | 深度帮助预算 | |
| `BOT_REPLY_GROUP_CONTEXT_BUDGET` | int | `2048` | ≥0（样例 8192 ⚠️） | | 群聊预算 | 快速模式另有 `BOT_CHAT_FAST_CONTEXT_BUDGET` |

### A9 记忆 / 历史 / 反思 / 诊断 / 审计 / 回执 / 审计日志 / Prompt 审计（键数以本节为准）

> memory/history/diagnostics/audit/receipts 各组代码默认 db_path 均为空 = **内存态/禁用语义**；reflection 组自带 `data/reflection.sqlite3` 默认路径。`.env.example` 给出具体文件名（如 `data/wuwa_*.sqlite3`）仅为推荐样例。

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEMORY_ENABLED` | bool | `False` | | | 长期记忆开关 | |
| `BOT_MEMORY_DB_PATH` | str | `""` | 路径（空=内存） | | 记忆库 | |
| `BOT_MEMORY_MAX_ITEMS` | int | `5` | ≥0 | | 注入条数上限 | |
| `BOT_MEMORY_MAX_CHARS` | int | `1200` | ≥0 | | 注入字符上限 | |
| `BOT_MEMORY_EXTRACT_ENABLED` | bool | `True` | | | 回复后自动抽取记忆 | 依赖 `BOT_MEMORY_ENABLED` |
| `BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS` | float | `15.0` | 有限数且 (0, 3600]（校验器强制） | | 记忆抽取单次超时 | |
| `BOT_MEMORY_EXTRACT_MAX_TOKENS` | int | `200` | [1, 4096]（校验器强制） | | 记忆抽取输出 token 上限 | |
| `BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS` | float | `300.0` | 有限数且 (0, 3600]（校验器强制） | | 抽取出错后的冷却间隔 | |
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

**夜间反思（domains/chat_reply/character/reflection.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_REFLECTION_ENABLED` | bool | `True` | | | 夜间反思回路：把当天对话沉淀为高层事实+会话摘要，提供跨会话的「非线性记忆」召回 | LLM 归纳默认关（用确定性启发式） |
| `BOT_REFLECTION_DB_PATH` | str | `data/reflection.sqlite3` | 路径 | | 反思库 | data/ 重映射收口 |
| `BOT_REFLECTION_HOUR` | int | `4` | 0~23 | | 夜间反思触发时刻（时） | 与 `BOT_REFLECTION_MINUTE` 组成触发时刻 |
| `BOT_REFLECTION_MINUTE` | int | `30` | 0~59 | | 夜间反思触发时刻（分） | |
| `BOT_REFLECTION_MAX_SESSIONS` | int | `50` | ≥0 | | 单次反思纳入的会话数上限（source_limit_sessions） | |
| `BOT_REFLECTION_LLM_ENABLED` | bool | `False` | | | 反思 LLM 归纳开关；默认关，用确定性启发式 | 依赖 LLM 引擎 |

**Prompt 审计与执行模式（当前仅 domains/chat_reply/runtime/prompt_preview.py CLI 消费，主链路不读取，保留字段供 CLI 与未来扩展）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_PROMPT_AUDIT_DIR` | str | `data/prompt_audit` | 路径 | | prompt 审计落盘目录（prompt_preview CLI 实际读取） | data/ 重映射 |
| `BOT_PROMPT_AUDIT_MAX_CHARS` | int | `12000` | ≥0 | | 单条审计截断上限（prompt_preview CLI 实际读取） | |
| `BOT_PROMPT_AUDIT_ENABLED` | bool | `True` | | | prompt 审计组开关（保留字段） | |
| `BOT_PROMPT_AUDIT_INCLUDE_MESSAGES` | bool | `True` | | | 审计是否含消息正文（保留字段） | |
| `BOT_PROMPT_AUDIT_INCLUDE_UNTRUSTED_CONTEXT` | bool | `True` | | | 审计是否含不可信上下文（保留字段） | |
| `BOT_PROMPT_EXECUTION_MODE` | str | `execute` | 模式名 | | prompt 执行模式（保留字段） | |
| `BOT_PROMPT_APPROVAL_DIGEST` | str | `""` | 字符串 | | 审批摘要标识（保留字段） | |
| `BOT_PROMPT_AUDIT_RETENTION_DAYS` | int | `14` | ≥0 | | 审计保留天数（保留字段） | |

### A10 发送队列与超时/预算（键数以本节为准）

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
| `BOT_SEND_BOT_UNAVAILABLE_MAX_AGE_SECONDS` | float | `1800.0` | ≥0（秒） | | B-4：`bot_unavailable` 挂起回执的绝对年龄上限——入队超过该时长仍因 NapCat 断线不可投才置 `FAILED_FINAL`（防非终态行无限堆积） | 缺字段 = env 键被 pydantic 丢弃、旋钮恒默认 |
| `BOT_TRANSPORT_TIMEOUT_SECONDS` | float | `15.0` | **(0, 600]**，拒绝负数/NaN/Infinity | ✅热更 | 发送层单请求硬超时（OneBot/Telegram/Mail 共用）；超时不自动重发正文；0/非法值在 .env 加载与热改两道入口均直接报错拒绝（无静默兜底），仅发送层读取路径在 provider 异常/取到非法值时防御性回退 15 | 校验器+热更转换器双重把关 |
| `BOT_REQUEST_BUDGET_SECONDS` | float | `300.0` | **(0, 600]**（样例 90 ⚠️） | | 请求级总预算：单次聊天从 LLM/工具循环到发送共用单调 deadline；耗尽后不再发起新网络调用，群/频道静默，仅管理员收安全告警。2026-09-15 实弹由 150 抬到 300（五渠道链在 150s 内必然烧穿尾巴），旧值 150 已不是任何一侧的缺省 | 传入 ModelRouter 作为 failover deadline 上界；`BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS` 须严格大于本键 |

### A11 情绪 / 心情 / 好感度 / 趋势 / 时间感知（键数以本节为准）

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

**机器人自身心情 bot.mood（L1，domains/chat_reply/character/mood.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MOOD_ENABLED` | bool | `True` | | | 机器人自身心情：二维连续空间（valence 愉悦度 -1..1 / arousal 唤醒度 0..1），互动事件驱动、按半衰期指数回归基线；与好感度（天-周尺度）时间尺度分离 | 驱动开火概率/表情档/语气 |
| `BOT_MOOD_DB_PATH` | str | `data/bot_mood.sqlite3` | 路径 | | 心情持久化库（write-back：跨进程重启衰减结果一致） | data/ 重映射收口 |
| `BOT_MOOD_HALF_LIFE_MINUTES` | float | `120.0` | >0（消费点强制校验） | | 心情向基线收敛的半衰期（分钟） | |
| `BOT_MOOD_BASELINE_AROUSAL` | float | `0.3` | 0.0~1.0（读入钳位） | | 唤醒度基线：高=兴奋/烦躁，低=慵懒 | |
| `BOT_MOOD_RATE_CAP_PER_HOUR` | float | `0.5` | ≥0 | | 事件速率帽：任意 3600 秒窗口内已施加的 valence 增量绝对值之和上限，超帽部分截断而非整次拒绝（窗口记账存进程内存，重启清零） | |

**动态好感度 bot.affinity（domains/chat_reply/character/affinity.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_AFFINITY_ENABLED` | bool | `True` | | | 动态好感度与印象标签（批次 C）：按用户行为自动增减，差异化态度 | 数值规范唯一权威见 docs/affinity-design.md |
| `BOT_AFFINITY_DB_PATH` | str | `data/user_affinity.sqlite3` | 路径 | | 好感度库；管理员可直接改库调整个别用户 | data/ 重映射收口 |

### A12 LLM 引擎与模型路由（键数以本节为准）

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
| `BOT_API_KEY_QIANQIANYE_NIGHT` | str | `""` | 密钥（占位） | | 凭据槽：qianqianye 夜间组 | 同上 |
| `BOT_API_KEY_DEEPSEEK_QIAN` | str | `""` | 密钥（占位） | | 凭据槽：deepseek qian 组 | 同上 |
| `BOT_API_KEY_DEEPSEEK_OFFICIAL` | str | `""` | 密钥（占位） | | 凭据槽：DeepSeek 官方（registry 的 ds-official-flash/-flash-vision/-pro 条目引用 `env:BOT_API_KEY_DEEPSEEK_OFFICIAL`） | H3 修复：字段曾长期缺失，致 env 已填 key 也恒判 config_missing |
| `BOT_API_KEY_AXONHUB` | str | `""` | 密钥（占位） | | 凭据槽：axonhub 统一网关（本地 OpenAI 兼容端点，默认模型与故障转移都挂在它上面） | 同上 |
| `BOT_API_KEY_AIPRC_GEMINI` | str | `""` | 密钥（占位） | | 凭据槽：aiprc gemini 组 | 同上 |
| `BOT_POTCCV_API_KEY` | str | `""` | 密钥（占位） | | 凭据槽：POTCCV 中转（gpt-5.6-luna/-terra 两条渠道引用 `env:BOT_POTCCV_API_KEY`） | 命名偏离 `BOT_API_KEY_*` 惯例是**刻意的**：注册表 `env:` 解析走 `getattr(config, env_name.lower())`，字段名必须严格等于 `bot_potccv_api_key`，改名即恒判 config_missing（H3 家族第四次复发，见 config.py 同字段注释） |
| `BOT_API_KEY_AIPRC_GROK` | str | `""` | 密钥（占位） | | 凭据槽：aiprc grok 组 | 同上 |
| `BOT_API_KEY_UMI_GROUP3` | str | `""` | 密钥（占位） | | 凭据槽：Umi group3 | 同上 |
| `BOT_API_KEY_UMI_CLAUDE` | str | `""` | 密钥（占位） | | 凭据槽：Umi Claude | 同上 |
| `BOT_API_KEY_ZHIPU` | str | `""` | 密钥（占位） | | 凭据槽：zhipu | 同上 |
| `BOT_API_KEY_TOOLCODE_GPT` | str | `""` | 密钥（占位） | | 凭据槽：toolcode GPT | 同上 |
| `BOT_API_KEY_TOOLCODE_GEMINI` | str | `""` | 密钥（占位） | | 凭据槽：toolcode Gemini | 同上 |
| `BOT_API_KEY_TOOLCODE_GROK` | str | `""` | 密钥（占位） | | 凭据槽：toolcode Grok | 同上 |
| `BOT_API_KEY_STARAPI` | str | `""` | 密钥（占位） | | 凭据槽：starapi | 同上 |
| `BOT_CHAT_BASE_URL` | str | `https://api.openai.com/v1` | http(s) URL，不得内嵌账号密码；可带/不带 `/chat/completions`（自动补全） | | 主接口地址 | 详见 B 节 |
| `BOT_CHAT_TEMPERATURE` | float | `0.7` | **0.0 ≤ x ≤ 2.0**（有限数） | ✅热更 | 采样温度 | 详见 B 节 |
| `BOT_CHAT_REASONING_EFFORT` | str | `""` | `""`/`off`/`low`/`medium`/`high`/`xhigh`/`max` | ✅热更 | 思考强度：空=各模型家族默认最高档（deepseek/glm/kimi/minimax=max，gpt/grok=xhigh，gemini=high）；off=不发送；qwen/dashscope 系转成 `enable_thinking` 布尔；不支持时自动去参重试一次 | 复杂任务会把全局/默认档临时升到家族最高档；条目级 `effort` 字段优先于全局 |
| `BOT_CHAT_MAX_TOKENS` | int | `65538` | **0 ≤ x ≤ 65538（校验器强制）**；**0=不向 API 传 max_tokens（不设上限）**，负数/>65538 非法 | ✅热更 | 正常聊天输出上限；命令能力用各自独立限制 | |
| `BOT_CHAT_TIMEOUT_SECONDS` | float | `40.0` | 有限数 **>0** | | 正常模式单模型超时 | 详见 B 节 |
| `BOT_CHAT_FAST_MODE` | bool | `True` | | | QQ/群聊快速响应模式：限制上下文/输出/联网前置，优先首字 | 启用时路由超时取 min(正常,快速) |
| `BOT_CHAT_FAST_MAX_TOKENS` | int | `65538` | 0 ≤ x ≤ 65538（校验器强制，同上） | ✅热更 | 快速模式输出上限 | |
| `BOT_CHAT_FAST_MAX_CANDIDATES` | int | `0` | ≥0；0=不限候选数 | | 快速模式候选模型截断数 | ModelRouter fast_mode 生效 |
| `BOT_CHAT_FAST_TIMEOUT_SECONDS` | float | `40.0` | >0 | | 快速模式超时 | router 取 min(正常,快速)；值为 0/缺省时回退 12.0 |
| `BOT_CHAT_FAST_CONTEXT_BUDGET` | int | `9600` | ≥0（样例 32768 ⚠️） | | 快速模式上下文预算 | |
| `BOT_CHAT_FAST_WEB_MAX_QUERIES` | int | `3` | ≥0（样例 5 ⚠️） | | 快速模式联网检索次数上限 | 依赖 `BOT_WEB_SEARCH_ENABLED` |
| `BOT_CHAT_FAILOVER_MAX_SECONDS` | float | `120.0` | ≥0；0=不限 | | 故障转移总时限：候选连败时的整体预算，防响应拖到分钟级 | 与请求级 deadline 取更早者 |
| `BOT_CHAT_FAST_EMBEDDING_TIMEOUT_SECONDS` | float | `3.0` | >0 | | 快速模式嵌入超时 | 压缩 `BOT_EMBEDDING_*_TIMEOUT` 的快路径 |
| `BOT_CHAT_FAST_SKIP_WEB_PAGES` | bool | `True` | | | 快速模式跳过网页抓取 | |
| `BOT_CHAT_FAST_DISABLE_VECTOR_KNOWLEDGE` | bool | `False` | | | 快速模式禁用向量知识检索 | 依赖 `BOT_EMBEDDING_ENABLED` |
| `BOT_MODEL_PRESETS` | dict[str,str] | `{}` | JSON：`{"预设名":"模型名"}` | | 模型预设：只接受**手动指定**（`/bot runtime model set <预设名>`），打 `manual` 标签、优先级 1000+，不参与自动选型；继承主配置 base_url/api_key | |
| `BOT_MODEL_REGISTRY` | dict[str,dict] | `{}` | JSON：id → `{model(必填，缺则忽略该条目), base_url, api_key(str 或 list，支持 env:VAR), group, tags(list 或逗号串=思考强度档位), effort(可选 off/low/medium/high/xhigh/max), priority(默认100，越小越先)}` | | 多模型注册表（自动路由+故障转移）；**绝不放真实 key，用 `env:BOT_API_KEY_*`**；api_key 支持列表做同模型多密钥转移。tags=档位体系（2026-09 改版）：deepseek/glm/kimi/minimax=low,high,max；gpt/grok=low,medium,high,xhigh；gemini=low,medium,high。样例中 `key_group`/`last_resort` 字段路由器**不解析**（仅注释性） | 注册表存在时主配置模型退居兜底（priority 2000, manual） |
| `BOT_MODEL_SCHEDULE` | str(dict) | `{}` | JSON：`{"HH:MM-HH:MM":"预设或注册表id"}`；支持跨零点 `"23:00-07:00"` | 🟡需重启 | 分时段自动切**单个模型**；窗口外回自动选型（与优先级分组互不影响） | 值写 `.env`、重启后由调度器解析（旧「热更时存 JSON」为假——本键不在白名单） |
| `BOT_MODEL_PRIORITY_GROUPS` | list[dict] | `[]` | JSON 数组：`[{"name","days"(ISO 周编号 1-7，缺省=每天),"windows"([["HH:MM","HH:MM"]]，缺省=全天),"order"(模型id 列表)]}`；days/windows 都缺省=兜底组 | ✅热更 | 时段优先级分组（峰谷顺序）：按列表顺序取**第一个命中**的组，命中组按 order 排序、组外模型按 priority 追加；每条消息实时判定（`BOT_TIMEZONE`）；只影响自动路由，手动 set 不受影响 | 前置校验 `_parse_model_priority_groups`；热更存规范化 JSON 字符串（`_model_priority_groups_converter`） |
| `BOT_MODEL_PRICES` | dict[str,dict] | `{}` | JSON：`{"模型名":{"input":元/1M,"output":元/1M}}` | ✅热更 | 每模型价格；成本按**调用时刻**价格记账（毫厘），调价不影响历史账单（峰谷差价天然正确）；未配置价格的模型不计费 | `/bot model price` 热维护；账单在 `/bot model usage` |
| `BOT_USAGE_MONITOR_ENABLED` | bool | `True` | | | 用量监控总开关（阈值提醒 + 定时报告，走管理员预警管线） | 无管理员 id 时自动禁用 |
| `BOT_USAGE_ALERT_OUTPUT_TOKENS` | int | `5000000` | ≥0 | | 单模型当日输出 token 提醒阈值 | 每 60 秒巡检当日聚合，每项每天只提醒一次 |
| `BOT_USAGE_ALERT_INPUT_TOKENS` | int | `50000000` | ≥0 | | 单模型当日输入 token 提醒阈值 | 同上 |
| `BOT_USAGE_ALERT_DAILY_COST_YUAN` | float | `10.0` | ≥0 | | 当日实际账单提醒阈值（元） | 超限立即发 Mica 报告卡+提醒（含各模型金额） |
| `BOT_USAGE_REPORT_HOURS` | str | `"13,18,23"` | 逗号分隔整点 0-23 | | 定时报告时间点（北京时间整点）；报告窗口=自上个报告点至今；**13 点报告额外附过去 24 小时总花费** | APScheduler CronTrigger；报告时间点持久化 |
| `BOT_USAGE_REPORT_STATE_FILE` | str | `"data/usage_report_state.json"` | 路径 | | 报告时间点状态文件（重启不丢） | 相对路径重定向到 Runtime data |
| `BOT_MODEL_AUTO_ROUTE` | bool | `True` | | | 自动选型开关：按时段分组/priority 顺序自动选型（runtime_admin 消费） | 复杂任务关键词现仅用于思考强度升档，不再分桶排序 |

**模型路由补充语义**（model_router.py）：自动候选顺序 = `BOT_MODEL_PRIORITY_GROUPS` 命中组的 order（未命中则 priority 升序，manual 排除）；思考深度由档位体系负责——每次调用按 条目 effort > 全局 `BOT_CHAT_REASONING_EFFORT` > 家族默认最高档 发送 `reasoning_effort`，复杂任务（≥300 字或关键词）把全局/默认档升到家族最高档；手动指定 id 失败仍按优先级转移；未知覆盖 id 当作完整模型名走主配置接口；每次生成前合并**运行时注册表**（改动即生效）；仅 `timeout/network/server/rate_limited/provider_error/empty_response/model_not_found/unsupported_model` 触发转移，`auth/config_missing/schema/invalid_request` 立即抛出；`reasoning_effort` 遇 `unsupported_parameter` 自动去参重试一次；LLM 请求代理复用 `BOT_DOWNLOAD_PROXY`；推理模型 content 为空时回退 `reasoning_content` 尾部 600 字并打 `content_source=reasoning_fallback` 标记；usage 归一化缓存字段（`prompt_cache_hit_tokens`/`prompt_tokens_details.cached_tokens`/`cache_creation_input_tokens` 等）。

**渠道巡检与影子并发（B-2 / v2 无损切换）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CHANNEL_HEALTH_ENABLED` | bool | `True` | | | 模型渠道后台健康巡检总开关 | |
| `BOT_CHANNEL_HEALTH_INTERVAL_SECONDS` | float | `3600.0` | >0 | | 后台巡检间隔 | |
| `BOT_CHANNEL_PROBE_THREADS` | int | `3` | 钳位 1..16 | | 后台巡检并发线程数 | |
| `BOT_CHANNEL_PROBE_MANUAL_THREADS` | int | `8` | 钳位 1..16 | | 手动 `/bot model probe` 并发线程数 | |
| `BOT_CHANNEL_PROBE_JITTER_SECONDS` | float | `0.4` | 钳位 0..5.0 | | 后台巡检提交错峰间隔 | |
| `BOT_CHANNEL_SLOW_EMA_MS` | int | `15000` | ≥0（毫秒） | | 慢渠道识别（v2 动态检测）：平滑延迟（EWMA）超阈值时，巡检报告对该渠道的「快/正常」评级改标「偏慢」 | |
| `BOT_CHANNEL_ADAPTIVE_TIMEOUT` | bool | `True` | | | 自适应超时（v2 无损切换）：已知渠道 EWMA 时，单次尝试超时收紧为 min(原值, max(8s, ema×3))，挂死渠道快速失败转移，不再烧满超时窗口 | |
| `BOT_CHAT_HEDGED_REQUESTS_ENABLED` | bool | `True` | | | 影子并发（hedged request）：健康过滤后候选 ≥2 且非 fast_mode 时，首候选发出 hedge_delay 秒仍未回则并发发起次候选，先到先得；落选请求仍会飞完并正常计费 token（成本换尾延迟） | |
| `BOT_CHAT_HEDGE_DELAY_SECONDS` | float | `2.0` | >0 | | 影子并发触发延迟（秒） | |
| `BOT_CHAT_HEDGE_MAX_CANDIDATES` | int | `2` | ≥0 | | 影子并发最大候选数 | |

### A13 联网检索与分类遥测（键数以本节为准）

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

**检索供应商链与凭据**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEB_SEARCH_PROVIDER` | str | `tavily` | 供应商 id（转小写；本键须重启） | 🟡需重启 | 主检索供应商（Search API chain：Tavily 主，You/LangSearch 回退，TinyFish 可抓正文） | 端点/凭据见下两表 |
| `BOT_WEB_SEARCH_FALLBACK_PROVIDERS` | list[str] | `["you", "langsearch"]` | JSON 数组或逗号/分号分隔串（逐项小写化；空值回退默认） | 🟡需重启 | 主供应商失败后的回退顺序 | |
| `BOT_WEB_SEARCH_PROVIDER_OPTIONS` | dict[str,dict] | `{}` | JSON 对象字符串：供应商名 → 参数对象（键小写化，值非 dict 的条目丢弃；解析失败按空值降级） | | 按供应商覆盖请求参数（可覆盖 Tavily 一级参数同名键） | |
| `BOT_SEARCH_TAVILY_API_KEY` | str | `""` | 密钥（占位） | | 凭据槽别名：tavily。独立别名键保证 NoneBot dotenv 载入后 `env:BOT_SEARCH_*` 引用仍可解析 | 与 `BOT_WEB_SEARCH_TAVILY_API_KEY` 同源机制（A12 凭据槽同款） |
| `BOT_SEARCH_YOU_API_KEY` | str | `""` | 密钥（占位） | | 凭据槽别名：you | 同上 |
| `BOT_SEARCH_TINYFISH_API_KEY` | str | `""` | 密钥（占位） | | 凭据槽别名：tinyfish | 同上 |
| `BOT_SEARCH_LANGSEARCH_API_KEY` | str | `""` | 密钥（占位） | | 凭据槽别名：langsearch | 同上 |
| `BOT_WEB_SEARCH_TAVILY_API_KEY` | str | `""` | 密钥（占位） | | Tavily 密钥 | |
| `BOT_WEB_SEARCH_YOU_API_KEY` | str | `""` | 密钥（占位） | | You.com 密钥 | |
| `BOT_WEB_SEARCH_TINYFISH_API_KEY` | str | `""` | 密钥（占位） | | TinyFish 密钥 | |
| `BOT_WEB_SEARCH_LANGSEARCH_API_KEY` | str | `""` | 密钥（占位） | | LangSearch 密钥 | |

**供应商端点与一级参数**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEB_SEARCH_TAVILY_ENDPOINT` | str | `https://api.tavily.com/search` | URL | | Tavily 检索端点 | |
| `BOT_WEB_SEARCH_TAVILY_SEARCH_DEPTH` | str | `""` | 留空=不随请求发送 | | Tavily 一级参数 search_depth | 也可经 `BOT_WEB_SEARCH_PROVIDER_OPTIONS` 覆盖 |
| `BOT_WEB_SEARCH_TAVILY_TIME_RANGE` | str | `""` | 留空=不发送 | | Tavily 一级参数 time_range | 同上 |
| `BOT_WEB_SEARCH_TAVILY_EXTRACT_ENABLED` | bool | `False` | | | 正文抓取回退的 Tavily extract 兜底开关（默认关，避免额外额度消耗；TinyFish 抓取优先） | |
| `BOT_WEB_SEARCH_TAVILY_EXTRACT_ENDPOINT` | str | `https://api.tavily.com/extract` | URL | | Tavily extract 端点 | |
| `BOT_SEARCH_ACG_ENABLED` | bool | `False` | | | ACG 专项竖源检索总开关（v21r2）：命中二次元意图（番剧/漫画/B站梗/二次元游戏）且未触发安全红线时并发查竖源，按意图时效档加权并入【联网检索】；单源失败诚实降级 | 依赖意图识别（plugins/bot_unified_runtime/sources/search_intent.py）；不改变 bot_web_search_enabled 语义 |
| `BOT_SEARCH_ACG_BANGUMI_ENABLED` | bool | `True` | | | Bangumi (bgm.tv) 竖源（无 key，条目元数据+放送日期；v0 API 需自定义 UA，超限 429） | 依赖 `BOT_SEARCH_ACG_ENABLED` |
| `BOT_SEARCH_ACG_MOEGIRL_ENABLED` | bool | `True` | | | 萌娘百科竖源（复用 sources/moegirl 缓存+镜像回退；主站 WAF 拦截时降级为空） | 依赖 `BOT_SEARCH_ACG_ENABLED` |
| `BOT_SEARCH_ACG_BILIBILI_ENABLED` | bool | `True` | | | B站公开搜索竖源（视频 pubdate 时效信号；无 cookie 常见 -412 风控，诚实降级为空；wbi 收紧风险） | 依赖 `BOT_SEARCH_ACG_ENABLED` |
| `BOT_SEARCH_ACG_TIMEOUT_SECONDS` | float | `4.0` | >0 | | 单竖源请求超时 | |
| `BOT_SEARCH_ACG_MAX_PER_SOURCE` | int | `3` | ≥1 | | 单竖源结果条数上限 | |
| `BOT_WEB_SEARCH_YOU_ENDPOINT` | str | `https://api.you.com/v1/search` | URL | | You.com 检索端点 | |
| `BOT_WEB_SEARCH_TINYFISH_ENDPOINT` | str | `https://api.search.tinyfish.ai/search` | URL | | TinyFish 检索端点 | |
| `BOT_WEB_SEARCH_TINYFISH_FETCH_ENDPOINT` | str | `https://api.fetch.tinyfish.ai` | URL | | TinyFish 正文抓取端点 | |
| `BOT_WEB_SEARCH_LANGSEARCH_ENDPOINT` | str | `https://api.langsearch.com/v1/web-search` | URL | | LangSearch 检索端点 | |

**网页正文抓取**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEB_SEARCH_FETCH_TIMEOUT_SECONDS` | float | `15.0` | >0 | | 检索命中后网页正文抓取超时 | |
| `BOT_WEB_SEARCH_FETCH_MAX_CHARS` | int | `3000` | ≥0 | | 单页抓取字符上限 | | |

### A14 内容解析（链接/语音/视频）、抓取与解析历史（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CONTENT_PARSE_ENABLED` | bool | `True` | | | 平台链接识别→解析→信息卡总开关 | |
| `BOT_CONTENT_PARSE_PLATFORMS` | list[str] | `[]` | 空=全部；合法平台：bilibili, douyin, xiaohongshu, youtube, twitter, xiaoheihe, miyoushe, skland, kurobbs, netease_music, qqmusic, kuwo, kugou, apple_music, spotify（小写化） | | 平台白名单 | |
| `BOT_FETCH_TIMEOUT_SECONDS` | float | `10.0` | >0 | | 解析/点歌统一超时 | |
| `BOT_FORWARD_FETCH_TIMEOUT_SECONDS` | float | `5.0` | >0 | | 含合并转发的消息抓取转发正文超时；仅影响带 forward 段的消息 | |
| `BOT_COOKIES_FILE` | str | `""` | Netscape 格式 Cookie 文件路径（空=匿名解析；密钥类，路径可配、内容绝不外泄） | | 给 B站/小红书/抖音/QQ音乐/网易云/推特等解析与点歌加登录态（样例 data/platform_cookies.txt ⚠️） | data/ 重定向 |
| `BOT_PARSE_HISTORY_ENABLED` | bool | `True` | | | 解析历史落盘 | |
| `BOT_PARSE_HISTORY_DB_PATH` | str | `data/parse_history.sqlite3` | 路径 | | 历史库 | |
| `BOT_PARSE_HISTORY_MAX_ITEMS` | int | `2000` | ≥0 | | 条数上限 | |
| `BOT_MEDIA_ANALYZE_ENABLED` | bool | `True` | | | 解析视频时附加分辨率/时长/HDR/音频分析（yt-dlp） | 下载走 `/bot download` |
| `BOT_PARSE_SUBTITLE_SUMMARY` | bool | `False` | | | 解析卡 AI 字幕总结：解析到字幕文本且开启时，摘要后以「AI字幕总结」段附加在解析卡正文；默认关 | |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool | `True` | | 🟡需重启 | 解析器给出视频直链时自动下载并随卡发送；失败/超限静默降级为「下载：」提示 | 受下载上限约束 |
| `BOT_FETCH_PLAYWRIGHT_ENABLED` | bool | `True` | | | 抓取层允许 Playwright 渲染 | 与订阅 Playwright 轮询区分 |

**语音转写 bot.asr（record 段）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_ASR_MODEL_REGISTRY` | dict[str,Any] | `{}` | JSON 注册表：id → 条目或条目列表；格式与 `BOT_VISION_MODEL_REGISTRY` 相同，支持 `env:` 引用 key | | ASR 模型注册表（OpenAI 兼容 /audio/transcriptions 接口） | JSON 解析失败按空值降级并 ERROR 记键名（`_parse_model_dicts`） |
| `BOT_ASR_ENABLED` | bool | `False` | | ✅热更 | 语音转写开关 | |
| `BOT_ASR_TIMEOUT_SECONDS` | float | `20.0` | >0 | | 单次转写超时 | |
| `BOT_ASR_MAX_CHARS` | int | `300` | ≥0 | | 转写文本注入上限 | |

**视频理解与媒体档案 bot.video**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_VIDEO_UNDERSTANDING_ENABLED` | bool | `False` | | ✅热更 | 视频理解总开关（媒体档案库 + 抽帧/音轨/字幕 → 人格化追问）；关闭时完全走旧的 describe_video 抽帧摘要行为，零额外开销 | |
| `BOT_MEDIA_REGISTRY_PATH` | str | `data/media_registry.sqlite3` | 路径 | | 媒体档案库：message_id ↔ 视频文件 ↔ 字幕 ↔ 简报 的 SQLite 关联存储 | data/ 重映射收口 |
| `BOT_MEDIA_REGISTRY_TTL_DAYS` | int | `7` | ≥0 | | 档案（含感知简报）保留天数：过期自动剪枝，追问会重新分析；文本量级上限另受 5000 行 FIFO 约束；视频文件本身仍由下载缓存配额（`BOT_DOWNLOAD_CACHE_*`）单独清理 | |
| `BOT_VIDEO_MAX_FRAMES` | int | `6` | 下限钳位 1（本键须重启） | 🟡需重启 | 抽帧数（单次 VLM 调用内的图片预算） | |
| `BOT_VIDEO_BRIEF_DEADLINE_SECONDS` | float | `75.0` | >0 | | 简报硬预算：到点用已完成的信号合成 | |
| `BOT_VIDEO_BRIEF_MAX_CHARS` | int | `1200` | ≥0 | | 简报字符上限 | |
| `BOT_VIDEO_ASR_MAX_SECONDS` | int | `600` | ≥0 | | 音轨转写分析时长上限（默认前 600 秒）；ASR 超时随上限缩放（上限的 25%，封顶 150s） | |
| `BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE` | bool | `True` | | 🟡需重启 | 已有平台 CC 字幕时默认跳过 ASR（字幕已含语言信息，ASR 是纯增量成本） | |
| `BOT_VIDEO_NATIVE_INPUT` | bool | `False` | | 🟡需重启 | 原生视频直传（video_url content part，仅部分供应商支持）；失败自动回退抽帧 | |
| `BOT_VIDEO_NATIVE_MAX_MB` | int | `20` | ≥0 | | 直传视频体积上限（MB） | |
| `BOT_VIDEO_PROGRESS_ACK_ENABLED` | bool | `True` | | 🟡需重启 | 进度提示（「视频我看一下，稍等…」） | |
| `BOT_VIDEO_PROGRESS_ACK_COOLDOWN_SECONDS` | int | `60` | ≥0 | | 同会话进度提示节流 | |
| `BOT_VIDEO_FUZZY_FOLLOWUP` | bool | `True` | | 🟡需重启 | 模糊追问：无回复引用、文本提到「视频/刚才那个」等指代时用会话内最近档案——口语指代不再需要 @ 或回复 | |
| `BOT_VIDEO_DEEP_ENABLED` | bool | `True` | | 🟡需重启 | 自然语言深挖（「再仔细看看/没看懂」命中时重新分析）：更多帧 + 音频放宽 + 强制 ASR | |
| `BOT_VIDEO_DEEP_FRAMES` | int | `16` | ≥0 | | 深挖抽帧数 | |
| `BOT_VIDEO_DEEP_ASR_MAX_SECONDS` | int | `1800` | ≥0 | | 深挖音轨转写时长上限 | |
| `BOT_VIDEO_DEEP_DEADLINE_SECONDS` | float | `150.0` | >0 | | 深挖总预算 | |

### A15 下载与缓存配额（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DOWNLOAD_DIR` | str | `data/downloads` | 路径 | | 下载目录 | |
| `BOT_DOWNLOAD_MAX_BYTES` | int | `1073741824` | ≥0（1 GiB） | | 单文件大小上限 | |
| `BOT_DOWNLOAD_MAX_HEIGHT` | int | `0` | ≥0；0=不限 | | 视频最大分辨率（高） | |
| `BOT_DOWNLOAD_TIMEOUT_SECONDS` | int | `600` | >0 | | 下载超时 | |
| `BOT_DOWNLOAD_CONCURRENCY` | int | `8` | ≥1 | | 下载并发数 | |
| `BOT_DOWNLOAD_ARIA2_ENABLED` | bool | `True` | | | 装有 aria2c 时自动委托多连接下载（-x16 免预分配）；False 强制 yt-dlp 原生并发 | |
| `BOT_DOWNLOAD_CACHE_MAX_BYTES` | int | `2147483648` | ≥0（2 GiB） | | 下载目录配额，最旧优先清理 | |
| `BOT_DOWNLOAD_CACHE_MAX_AGE_DAYS` | int | `7` | ≥0 | | 下载保留天数 | |
| `BOT_MUSIC_CACHE_MAX_BYTES` | int | `536870912` | ≥0（512 MiB） | | 点歌缓存配额 | |
| `BOT_CARD_CACHE_MAX_BYTES` | int | `268435456` | ≥0（256 MiB） | | 卡片缓存配额 | |
| `BOT_MEME_CACHE_MAX_BYTES` | int | `268435456` | ≥0 | | 表情缓存配额 | |
| `BOT_DOWNLOAD_PROXY` | str | `""` | `http://127.0.0.1:7890` 形式；空=直连（样例 7890 ⚠️） | | 下载代理；**同时是 LLM 请求的代理来源**（model_router 复用） | |

### A16 卡片渲染与转发渲染（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CARD_RENDER_ENABLED` | bool | `True` | | | 解析结果渲染 PNG 卡片 | |
| `BOT_CARD_RENDER_BACKEND` | str | `playwright` | `playwright` / `null` | | 渲染后端 | |
| `BOT_CARD_RENDER_DIR` | str | `data/cards` | 路径 | | 卡片输出目录 | |
| `BOT_CARD_ASSET_DIR` | str | `""` | 路径 | | 外置卡片 SVG 资源目录；空=bridge 自动发现同级 ChatBot_Runtime | |
| `BOT_CARD_UI_SCALE` | float | `1.25` | >0（1.0=100%） | | 信息卡整体 UI 缩放，viewport 等比放大 | |
| `BOT_HELP_CARD_COLOR` | str | `""` | 十六进制色；空=中性灰（**模板禁止写死品牌色**，tint 一律由主色派生） | | 帮助页卡片主色 | 遵循 Mica 规范（AGENTS.md） |
| `BOT_RENDER_FORWARD_MIN_CHARS` | int | `1500` | ≥0（样例 0 ⚠️） | 🟡需重启 | 长文本转合并转发的最小字符数 | |
| `BOT_RENDER_FORWARD_MIN_NODES` | int | `4` | ≥0；0=关闭该规则，只看 min_chars | 🟡需重启（合并表 `__init__.py:748` 有读点而写拒⇒空转） | 按**条数**触发合并转发：切分后条数达到该值即合并（用户口径「超过 3 条就合并」→ 4） | |
| `BOT_RENDER_FORWARD_MAX_NODES` | int | `0` | ≥0；0=不限 | 🟡需重启 | 转发节点数上限 | |
| `BOT_RENDER_FORWARD_NODE_CHARS` | int | `900` | ≥0；下限钳位 200（本键须重启） | 🟡需重启 | 单节点字符数 | |

### A17 天气 / Wiki / 萌娘百科 / Epic / 历史上的今天 / 占卜 / 吃什么 / 今日快报 / 节假日（键数以本节为准）

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
| `BOT_WIKI_ENTRY_PAGES` | list[str] | `["鳴潮角色列表"]` | 词条页名列表（裸 JSON 串兜底解码） | | 维基候选索引页；候选页仅圈定范围，正文抽取仍需精确词条命中 | 消费点 domains/location/capabilities/wiki.py |
| `BOT_EPIC_ENABLED` | bool | `True` | | | 「epic」每周免费游戏（Epic 公开接口，免 key） | |
| `BOT_TODAY_HISTORY_ENABLED` | bool | `True` | | | 「历史上的今天」查询+每日推送（百度百科公开接口） | |
| `BOT_TODAY_HISTORY_PUSH_FILE` | str | `data/today_history_push.json` | 路径 | | 推送状态文件 | |
| `BOT_TODAY_HISTORY_CACHE_FILE` | str | `data/today_history_cache.json` | 路径 | | 每日缓存文件 | |
| `BOT_HOLIDAYS_FILE` | str | `""` | 路径（空=不用） | | 节假日数据文件 | 时间感知消费 |

**萌娘百科 bot.moegirl（公开 MediaWiki API 免 key，镜像仅作回退，总耗时受 timeout 预算硬约束）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MOEGIRL_ENABLED` | bool | `True` | | | 「萌娘百科 <词条>」显式指令 + 二次元问句（「初音未来是谁？」）自动查询；问句未命中/网络失败时无感降级 AI 聊天 | |
| `BOT_MOEGIRL_QUESTION_ENABLED` | bool | `True` | | | 问句自动触发独立开关；关闭后仅保留显式指令（群聊不 @ 本就不触发） | |
| `BOT_MOEGIRL_API_BASE` | str | `https://zh.moegirl.org.cn/api.php` | URL | | 主站 API | |
| `BOT_MOEGIRL_MIRROR_API_BASE` | str | `https://mzh.moegirl.org.cn/api.php` | URL | | 镜像 API（仅回退） | |
| `BOT_MOEGIRL_TIMEOUT_SECONDS` | float | `5.0` | >0 | | 单请求超时；问句路径整体预算 ≈ 2×该值（主站+镜像各一份份额） | |
| `BOT_MOEGIRL_MAX_CANDIDATES` | int | `5` | ≥0 | | 候选词条数上限 | |
| `BOT_MOEGIRL_SUMMARY_MAX_CHARS` | int | `300` | ≥0 | | 摘要字符上限 | |

**今日快报 bot.news（domains/subscribe/capabilities/news.py；国内可达 RSS 聚合，进程内 TTL 缓存按类目分桶）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_NEWS_ENABLED` | bool | `True` | | | 今日快报开关；仅显式触发词（快报/早报/科技新闻…），裸「新闻」让给联网搜索意图 | base_router news_match 检查 |
| `BOT_NEWS_TIMEOUT_SECONDS` | float | `6.0` | >0 | | 抓取超时 | |
| `BOT_NEWS_CACHE_SECONDS` | float | `600.0` | ≥0 | | 缓存 TTL | |
| `BOT_NEWS_MAX_ITEMS` | int | `20` | ≥0 | | 单次返回条数上限 | |

**占卜与吃什么（base_router 路由门）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DIVINATION_ENABLED` | bool | `True` | | | 占卜娱乐三件套（八字/塔罗/金钱卦）：纯本地计算、零网络；显式触发词 | base_router divination_match |
| `BOT_EAT_ENABLED` | bool | `True` | | | 「吃什么」/菜谱推荐路由开关（is_recipe_command 或 is_eat_command 命中走 bot.eat） | base_router eat_match |

### A18 表情包与图片识别（键数以本节为准）

**表情包搜索（3）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_SEARCH_ENABLED` | bool | `False` | | ✅热更 | 表情搜索开关 | |
| `BOT_MEME_SEARCH_TIMEOUT_SECONDS` | float | `8.0` | >0 | | 搜索超时 | |
| `BOT_MEME_SEARCH_CACHE_SECONDS` | int | `600` | ≥0 | | 搜索缓存 | |

**表情命令与本地 meme API（6）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_COMMAND_ENABLED` | bool | `True` | | | `/表情 列表`、`/表情 <key> <文字>`、`/meme help` 命令开关 | 依赖 meme API |
| `BOT_MEME_API_ENABLED` | bool | `False` | | | 对接本地 meme-generator-rs HTTP API | |
| `BOT_MEME_API_BASE_URL` | str | `http://127.0.0.1:2233` | URL | | API 地址 | |
| `BOT_MEME_API_TIMEOUT_SECONDS` | float | `15.0` | >0 | | API 超时 | |
| `BOT_MEME_API_OUTPUT_DIR` | str | `data/memes` | 路径 | | 生成图输出 | 受 `BOT_MEME_CACHE_MAX_BYTES` 配额 |
| `BOT_MEMES_PLUGIN_ENABLED` | bool | `False` | | | 外挂表情包生成插件 nonebot-plugin-memes（能力空白补齐）；默认关闭：加载后其 matcher 独立于统一管线直接响应 | |

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

**图片/表情识别 bot.vision（8）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_VISION_MODEL_REGISTRY` | dict[str,Any] | `{}` | JSON 注册表（模型/接口/密钥等条目） | | 识图模型注册表（预设名+注册表机制） | 与运行时 vision_registry 叠加（见 C 节） |
| `BOT_VISION_ENABLED` | bool | `False` | | ✅热更 | 聊天图片/表情识别开关；启用**且**注册表有可用模型才调 VLM | |
| `BOT_VISION_MODE` | str | `direct` | `direct`（图片直传 tags 含 vision/multimodal/vlm 的主模型，失败只回退一次 relay）/ `relay`（视觉模型先转文字）（样例 relay ⚠️） | ✅热更 | 识别模式；代码缺省 direct（主模型均 multimodal，direct 省一层调用） | direct 依赖主模型带视觉 tags |
| `BOT_VISION_TIMEOUT_SECONDS` | float | `20.0` | >0 | | 识别超时 | |
| `BOT_VISION_MAX_IMAGES` | int | `2` | ≥0 | | 单次识别图片数上限 | |
| `BOT_VISION_MAX_CHARS` | int | `500` | ≥0 | | 识别描述字数上限 | |
| `BOT_VISION_VIDEO_FRAMES` | int | `4` | ≥0（0 视同 1） | | 视频识别抽帧数：ffmpeg 均匀抽帧后单次 VLM 摘要 | |
| `BOT_VISION_CAPTION_CACHE_DB` | str | `data/vision_caption_cache.sqlite3` | SQLite 路径；空串＝关闭整件 | | 图片描述缓存库（按**图片内容 sha256** 命中，同图二次追问不再向 VLM 付费）。真身 `domains/media/registry/vision_caption_cache.py`；表 `vision_caption(sha256, caption, model, created_at, hits)` | 需重启才换库（实例按路径 memo 连接，见 `RESTART_REQUIRED_KEYS`）；落点经 `PATH_REMAPPED_FIELDS` 重映射到运行数据根（铁律 6）；库归属登记见 `docs/db-owners.md` |
| `BOT_VISION_CAPTION_CACHE_TTL_SECONDS` | int | `86400` | 秒；≤0＝关闭缓存 | | 描述保留时长；`lookup` 命中即刷新 `hits`，过期行读时即删、写侧每 32 次顺带整体清理 | 需重启才改 TTL（同上烘进实例） |
| `BOT_VISION_REPLY_PROBABILITY` | float | `0.004` | 0.0~1.0（`.env.example` 未列＝实际生效代码默认） | | 🔴 **本键已退役为判定输入**（2026-09-24 用户裁定：图片/表情包/视频类与文字接话用同一个概率）：缺省取自 `config.py::GROUP_PROACTIVE_REPLY_PROBABILITY`（与文字同源，禁两处各写一份数字），抽签实际只经 `domains/chat_reply/policy/gate.py::group_proactive_probability` 唯一读点取值 ⇒ 写本键**不改变任何行为**。想调视觉接话频率请改 `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY`。旧文案把默认写成 1.0（＝发图即回应）既不等于代码缺省也无现役读点，属假旋钮口径 | 装配层与 pipeline 仍逐字节透传本值（字段删掉会炸构造函数），故在册但 inert；生产 `.env` 若残留 1.0 该行已失效、可删 |

**以图搜图 SauceNAO（domains/media/capabilities/image_search.py + domains/media/search/sauce_search.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SAUCENAO_API_KEY` | str | `env:SAUCENAO_API_KEY` | 密钥或 `env:` 引用（输出占位） | | SauceNAO 反搜图（对标 YetAnotherPicSearch）的 API key | |

### A19 群聊策略、主动发言、复读检测、提醒与逆天发言防御（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GROUP_BLACK1` | list[str] | `[]` | 数字群号列表 | ✅热更 | black1=完全静默只接收不发送 | 四档互斥：按 black1>black2>white1>white2 语义判定 |
| `BOT_GROUP_BLACK2` | list[str] | `[]` | 数字群号 | ✅热更 | black2=只回「@它且带指令」 | |
| `BOT_GROUP_WHITE1` | list[str] | `[]` | 数字群号 | ✅热更 | white1=正常回复+可按主动接话开关抽签 | 与 auto_reply_probability 联动 |
| `BOT_GROUP_WHITE2` | list[str] | `[]` | 数字群号 | ✅热更 | white2=只回「@它」或显式命令 | |
| `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED` | bool | `False` | | 🟡需重启 | 群聊自动接话总开关（点名/命令不受影响）。装配期烘进策略快照、合并层 `_RUNTIME_HOT_OVERRIDE_FIELDS` 未登记本键 ⇒ 覆盖不被读取 | |
| `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY` | float | `0.004` | 0.0~1.0 | 🟡需重启（合并表 `__init__.py:746` 有读点而写拒⇒空转） | 未点名群消息抽签概率（**确定性哈希**，非随机数；2026-09-12 实弹反馈调低：5%/条 会频繁主动接话并自我触发限流）；⚠️与 `_ENABLED` 同族但只有本键进了合并表（`__init__.py:746`）——两键都不在白名单 ⇒ 写拒 | |
| `BOT_GROUP_WELCOME_ENABLED` | bool | `True` | | ❌无热改面（SETTABLE/RESTART 两表均未登记） | 入群欢迎语开关（审查 B-05；守岸人语气一行，昵称富集失败退通用称呼） | 退群/管理变更只记 runtime 事件不发言（公开点名离开者是打扰） |
| `BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR` | int | `6` | ≥0 | 🟡需重启 | 每小时主动回复上限 | |
| `BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS` | int | `90` | ≥0 | 🟡需重启 | 主动回复冷却 | |
| `BOT_NATURAL_COMMAND_ENABLED` | bool | `True` | | | 自然语言命令层（基层路由优先级 45）：「帮我查天气」等归一化执行 | |
| `BOT_SHARED_GROUP_CONTEXT_ENABLED` | bool | `False` | | 🟡需重启 | 跨实例共享群上下文（群摘要真总开关；原 `BOT_GROUP_DIGEST_ENABLED` 为死字段已删除，勿再配置） | |
| `BOT_GROUP_DIGEST_MAX_TURNS` | int | `150` | ≥0（样例 20 ⚠️） | | 摘要覆盖轮数 | |
| `BOT_GROUP_DIGEST_MAX_CHARS` | int | `800` | ≥0 | | 摘要字符上限 | |
| `BOT_GROUP_DIGEST_LLM_ENABLED` | bool | `False` | | | 摘要用 LLM 精炼 | 依赖 LLM 引擎 |
| `BOT_GROUP_DIGEST_LLM_TTL_SECONDS` | int | `3600` | ≥0 | | LLM 摘要缓存 TTL | |

**群聊复读检测 bot.parrot**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_PARROT_THRESHOLD` | int | `3` | | | 群聊复读检测触发人数：窗口内 ≥N 个不同用户发同一文本则吐槽一次（「怎么一个个都当复读机」） | |
| `BOT_PARROT_WINDOW_SECONDS` | float | `60.0` | | | 复读检测窗口时长（秒） | |
| `BOT_PARROT_COOLDOWN_SECONDS` | float | `300.0` | | | 吐槽后的冷却间隔（秒） | |

**时间点提醒 bot.reminder（domains/schedule/store/reminders.py；进阶轨 `_reminder_llm_extract_enabled` 见 A26）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_REMINDER_ENABLED` | bool | `True` | | | 时间点提醒：记住「几点要做什么」，到点主动督促 | |
| `BOT_REMINDER_DB_PATH` | str | `data/reminders.sqlite3` | 路径 | | 提醒库 | data/ 重映射收口 |

**日常助理 bot.daily_assist（domains/assistant/daily/store/daily_assist.py + domains/assistant/daily/capabilities/daily_assist.py）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DAILY_ASSIST_ENABLED` | bool | `True` | | ❌无热改面（合并表 `__init__.py:757` 在列而白名单未登记⇒写拒；改 .env 须重启） | 日常助理总开关（收件箱命令面 + 定时推送） | 推送另受名单门约束 |
| `BOT_DAILY_ASSIST_DIR` | str | `data/daily_assist` | 路径 | | 收件箱/菜单/任务清单纯文本目录（inbox.md/food.md/tasks.md + daily/ 归档与 meal_history.jsonl） | data/ 重映射收口；可指向工作区外共享目录 |
| `BOT_DAILY_ASSIST_PUSH_USER_IDS` | ID 列表 | `[]` | JSON 数组或 ,; 分隔 | ❌无热改面（合并表 `__init__.py:759` 在列而白名单未登记⇒写拒；改 .env 须重启） | 早晚简报与吃什么推荐的私聊推送名单 | 名单为空=只记不推（绝不猜人） |
| `BOT_DAILY_ASSIST_MEAL_TIMES` | 字符串列表 | `["11:15", "17:15"]` | HH:MM 列表 | | 到点吃什么推荐时刻表 | 非法时刻跳过；cron 装配期快照，改后需重启 |
| `BOT_DAILY_ASSIST_MORNING_TIME` | str | `"09:00"` | HH:MM | | 早报时刻（读收件箱+任务清单，读后归档） | 非法回退 09:00；装配期快照 |
| `BOT_DAILY_ASSIST_EVENING_TIME` | str | `"21:00"` | HH:MM | | 晚报时刻（当日对账+主动琐事建议） | 非法回退 21:00；装配期快照 |

**逆天发言自动撤回 dirty_guard（防御强化，默认关）**

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_DIRTY_GUARD_ENABLED` | bool | `False` | | | 逆天发言检测开关（on_message matcher 优先级 3、block=False，只评估不阻塞其他处理器） | |
| `BOT_DIRTY_GUARD_DELETE` | bool | `False` | | | 判定为 severe 时自动撤回消息；仅机器人有群管理员权限时才可能生效 | |

### A20 点歌与音乐（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MUSIC_ENABLED` | bool | `True` | | | 「点歌 <关键词>」开关 | |
| `BOT_MUSIC_PLATFORMS` | list[str] | `[]` | 空=默认顺序：网易云→Apple→酷狗→QQ→酷我→Spotify | | 搜索顺序白名单 | |
| `BOT_MUSIC_DEFAULT_MODE` | str | `card+voice+link` | `card`/`voice`/`link` 以 `+` 组合 | | 点歌默认输出模式（卡片/封面 + 语音试听 + 链接） | 运行时 `BOT_MUSIC_MODE` 覆盖 |
| `BOT_MUSIC_CANDIDATES_ENABLED` | bool | `True` | | | F20：候选选择窗默认开启——同名歌必须先问再播，不经询问直接播首选曾被用户实弹否决 | |
| `BOT_MUSIC_CANDIDATES_TTL_SECONDS` | float | `300.0` | >0 | | 候选列表缓存有效期 | |
| `BOT_MUSIC_CANDIDATES_LIMIT` | int | `5` | ≥0 | | 候选列表条数上限 | |
| `BOT_MUSIC_ANALYTICS_ENABLED` | bool | `True` | （.env 缺） | | 点歌行为分析：只记成功结果，不记原始查询词 | |
| `BOT_MUSIC_ANALYTICS_DB_PATH` | str | `data/music_analytics.sqlite3` | 路径（.env 缺） | | 分析库 | |
| `BOT_MUSIC_ANALYTICS_RETENTION_DAYS` | int | `365` | ≥0（.env 缺） | | 分析数据保留天数 | |
| `BOT_MUSIC_MODE` * | str | （无默认；回退 `BOT_MUSIC_DEFAULT_MODE`=`card+voice+link`） | `audio`/`voice`/`link`/`card`（中文别名：音频/语音/链接/卡片；default→card） | ✅热更 | **config.py 无此字段**，纯运行时覆盖键：点歌返回形态；未设置时回退 `BOT_MUSIC_DEFAULT_MODE` | 仅存于 settings 覆盖层（`__init__.py` 点歌出口消费） |

### A21 订阅系统 bot.subscribe（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SUBSCRIBE_ENABLED` | bool | `True` | | | 定时拉取平台新内容并推送 | |
| `BOT_SUBSCRIBE_DB_PATH` | str | `data/subscriptions.sqlite3` | 路径 | | 订阅库 | |
| `BOT_SUBSCRIBE_POLL_INTERVAL_SECONDS` | int | `300` | ≥0 | | 常规轮询间隔 | |
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
| `BOT_SUBSCRIBE_PLATFORM_BILIBILI` | bool | `True` | | | 审查 J-02：B站订阅平台开关（审查 J-02，用户「所有子模块可开关」硬要求）。关=该平台 add 显式拒绝（「该平台订阅暂未开放」）、轮询跳过，既有订阅行保留（重开自动恢复）；与 `BOT_SUBSCRIBE_ENABLED` 总开关叠加（总开关关=整个订阅系统路由层拦截）；键名与 V2 注册表 target.platform 标识逐字对齐；config 实例启动期固定，改后需重启（非热更） | 与订阅 add/轮询共用 `subscription_platform_enabled` 判定 |
| `BOT_SUBSCRIBE_PLATFORM_XIAOHONGSHU` | bool | `True` | | | 小红书（xhs）订阅平台开关，语义同上 | 同上 |
| `BOT_SUBSCRIBE_PLATFORM_YOUTUBE` | bool | `True` | | | YouTube 订阅平台开关，语义同上 | 同上 |
| `BOT_SUBSCRIBE_PLATFORM_TELEGRAM` | bool | `True` | | | Telegram 订阅平台开关，语义同上 | 同上 |
| `BOT_SUBSCRIBE_PLATFORM_PIXIV` | bool | `True` | | | Pixiv 订阅平台开关，语义同上 | 同上 |
| `BOT_SUBSCRIBE_PLATFORM_WEIBO` | bool | `True` | | | 微博订阅平台开关，语义同上 | 同上 |
| `BOT_SUBSCRIBE_PLATFORM_NETEASE` | bool | `True` | | | 网易云音乐订阅平台开关，语义同上。注意：music adapter 以 provider 名 `netease` 落 target.platform，故键名为 NETEASE 而非 MUSIC | 同上 |

### A22 凭据检查（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CREDENTIALS_FILE` | str | `""` | 路径（Cookie 文件；密钥类，内容绝不外泄） | | 平台凭据文件 | |
| `BOT_CREDENTIAL_WARN_DAYS` | int | `7` | ≥0 | | 到期预警天数 | |
| `BOT_CREDENTIAL_PROBE_URLS` | dict[str,str] | `{}` | JSON：名称→探测 URL | | 凭据可用性探测地址 | |
| `BOT_CREDENTIAL_PROBE_TIMEOUT_SECONDS` | float | `8.0` | >0 | | 探测超时 | |
| `BOT_CREDENTIAL_CHECK_ENABLED` | bool | `False` | | | 周期凭据检查开关 | |
| `BOT_CREDENTIAL_CHECK_INTERVAL_HOURS` | int | `6` | ≥1 | | 检查间隔（小时） | |

### A23 术语表与用户档案（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_GLOSSARY_FILES` | list[str] | `[]` | 文档路径 | | 术语表文件 | |
| `BOT_GLOSSARY_MAX_ENTRIES` | int | `30` | ≥0 | | 注入词条数上限 | |
| `BOT_GLOSSARY_MAX_CHARS` | int | `1500` | ≥0 | | 注入字符上限 | |
| `BOT_USER_PROFILES_FILE` | str | `""` | 路径（空=不用） | | 用户画像文件 | |

### A24 速率限制与免打扰（键数以本节为准）

| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系/依赖 |
|---|---|---|---|---|---|---|
| `BOT_RATE_LIMIT_ENABLED` | bool | `True` | | | 限速总开关 | |
| `BOT_RATE_LIMIT_WINDOW_SECONDS` | int | `60` | ≥1 | | 滑动窗口长度 | |
| `BOT_RATE_LIMIT_CHAT_GLOBAL_MAX_REQUESTS` | int | `60` | ≥0 | | 全局窗口内聊天请求上限 | |
| `BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS` | int | `6` | ≥0（样例 12 ⚠️） | | 单会话上限 | |
| `BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS` | int | `4` | ≥0（样例 8 ⚠️） | | 单用户上限 | |
| `BOT_RATE_LIMIT_CHAT_SENDER_MIN_INTERVAL_SECONDS` | int | `45` | ≥0；0=关闭 | | R3 防刷屏：同一发送者两次 bot.chat 回复的最小间隔（秒），仅同人点名（mentions_bot）生效 | InMemory 与 SQLite 限流器同语义，且均先于 role bypass 判定 |
| `BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` | int | `0` | ≥0 | | 同目标最小间隔 | |
| `BOT_RATE_LIMIT_BYPASS_ROLES` | list[str] | `["admin"]` | 角色名列表 | | 限速豁免角色 | |
| `BOT_RATE_LIMIT_DB_PATH` | str | `""` | 路径；非空=sqlite，空=内存 | | 限速持久化 | readiness 汇报 store |
| `BOT_QUIET_HOURS_ENABLED` | bool | `True` | | ✅热更 | 免打扰总开关 | |
| `BOT_QUIET_HOURS_START` | str | `00:00` | `HH:MM` | ✅热更 | 开始时刻 | |
| `BOT_QUIET_HOURS_END` | str | `06:00` | `HH:MM` | ✅热更 | 结束时刻 | 支持跨零点 |
| `BOT_QUIET_HOURS_TIMEZONE` | str | `Asia/Hong_Kong` | IANA 时区 | ✅热更 | 免打扰时区（独立于 `BOT_TIMEZONE`） | |
| `BOT_QUIET_HOURS_SESSION_TYPES` | list[str] | `["group"]` | 会话类型列表 | ✅热更 | 适用的会话类型 | |
| `BOT_QUIET_HOURS_BYPASS_ROLES` | list[str] | `["admin"]` | 角色名列表 | ✅热更 | 豁免角色 | |
| `BOT_QUIET_HOURS_DIRECT_BYPASS_MENTIONS` | bool | `True` | 0/1 | 🟡需重启 | 安静时段直连豁免的 mentions 腿：True＝@bot 点名夜间仍必应，False＝收紧这一腿 | 判据真身 `policy/quiet_hours.py::_direct_bypass_leg`；同族六枚在合并层已登记、本枚新出未登记 |
| `BOT_QUIET_HOURS_DIRECT_BYPASS_COMMANDS` | bool | `True` | 0/1 | 🟡需重启 | 安静时段直连豁免的 commands 腿：True＝命令类能力夜间直通（既有语义），False＝命令关进这道门 | 与 mentions 腿分立、互不顶替（2026-10-01 用户裁定） |
| `BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP` | bool | `True` | 0/1 | 🟡需重启 | 命令态群须在册：群不属四册（black1/black2/white1/white2，含动态名单）时群内 `/bot` 与别名命令一律否决；只收紧命令腿 | 判据真身 `policy/gate.py` 的 `command_group_unlisted`；读点＝gate 现读 driver config→os.environ，装配层未透传 |
| `BOT_RATE_LIMIT_COMMAND_ENABLED` | bool | `True` | 0/1 | 🟡需重启 | 命令腿帽总开关 | 读点 `policy/rate_limit.py::build_rate_limit_settings`，合并层未登记该键 |
| `BOT_RATE_LIMIT_COMMAND_WINDOW_SECONDS` | int | `60` | ≥1 | 🟡需重启 | 命令腿滑动窗长度（秒） | 同上族 |
| `BOT_RATE_LIMIT_COMMAND_SENDER_MAX_REQUESTS` | int | `12` | ≥0；0=该腿不生效 | 🟡需重启 | 同人命令腿窗内上限 | 同上族；与 chat 句数帽分册记账（scope `command_*`） |
| `BOT_RATE_LIMIT_COMMAND_GROUP_MAX_REQUESTS` | int | `20` | ≥0；0=该腿不生效 | 🟡需重启 | 同群命令腿窗内上限（私聊不记群账） | 同上族 |
| `BOT_RATE_LIMIT_COMMAND_BYPASS_ROLES` | list[str] | `["admin"]` | 角色名列表 | 🟡需重启 | 命令腿自己的旁路脸 | 与 `BOT_RATE_LIMIT_BYPASS_ROLES`（聊天侧）分册，改这枚不动聊天语义 |

### A25 非 Config 键（`.env.example` 存在、但由其他组件消费，不属于本 Config）

| 键名 | 消费方 | 说明 |
|---|---|---|
| `MAIL_BOTS` / `TELEGRAM_BOTS` | 邮件/Telegram 插件 | JSON 数组；含账号令牌，占位配置、绝不粘贴真实值到对话 |
| `TELEGRAM_PROXY` / `TELEGRAM_WEBHOOK_URL` | Telegram 插件 | 代理与 webhook |
| `MCP_CACHE_TTL` / `MCP_SERVERS` / `MCP_TOOL_TIMEOUT` | nonebot-plugin-mcpclient | 可选 MCP 工具；TTL 0=不过期 |
| `SQLALCHEMY_DATABASE_URL` | 可选 ORM | 样例含 `CHANGE_ME` 占位口令 |
| `LOCALSTORE_USE_CWD` / `LOCALSTORE_CACHE_DIR` / `LOCALSTORE_CONFIG_DIR` / `LOCALSTORE_DATA_DIR` | nonebot-plugin-localstore | 第三方本地存储，指向工作区外 Runtime 目录 |

---

### A26 增量补录（2026-09-12 批次起新增，逐键对 config.py 核实）

| 键（BOT_ 前缀省略） | 默认值 | 作用/效果 |
|---|---|---|
| `_decision_engine_mode` | `legacy_only` | 中央决策引擎模式：legacy_only（默认，不接管）/ shadow（影子对照记录分歧，P95≈0.04ms，绝不发送）。阶段 2 前保持默认 |
| `_group_digest_push_enabled` | `true` | 夜间"每日通讯总结"主动推送总开关；仅推群摘要白名单群（list_mode 非 whitelist 时零推送） |
| `_group_digest_push_time` | `21:30` | 推送时刻，HH:MM 校验 |
| `_group_digest_list_mode` / `_group_digest_whitelist` / `_group_digest_blacklist` | 空 | 群摘要名单：whitelist=仅名单内群注入/被推送；blacklist=排除；空=不过滤。🟡需重启（三键均在 `RESTART_REQUIRED_KEYS`、不在 `SETTABLE_KEYS`；旧「运行时 store 可热改」为假。同族 `_group_digest_push_enabled`/`_push_time` 两表均未登记＝❌无热改面） |
| `_proactive_affinity_gate_enabled` | `true` | 群聊主动接话好感门：仅对好感档 ≥ 亲近（close）用户抽签接话（冷却/频控沿用 rate_limit） |
| `_reflection_quirks_propose_enabled` | `true` | 夜间反思高置信事实 → persona_quirks 待审池（仍需管理员 approve，不直接生效） |
| `_reflection_quirks_min_confidence` | `0.5` | 投喂置信度门槛 |
| `_reminder_llm_extract_enabled` | **`false`** | 提醒进阶轨：LLM 轮末抽取无"提醒"词的时间陈述（"中午12点要写作业"）；默认关 |
| `_media_archive_enabled` / `_media_archive_dir` / `_media_archive_db_path` | `true` / `data/media_archive` / `data/media_archive.sqlite3` | 媒体归档（bot.media_archive）：发媒体+收藏/归档/archive → VLM 判 类别×IP（cosplay/二次元插图等）双层目录落盘；dir/db_path 走 runtime 重映射 |
| `_media_archive_min_role` | `super_admin` | 触发角色门槛（user<trusted<enterprise<admin<super_admin）；放开全员改 user，限额/冷却照常 |
| `_media_archive_max_file_mb` / `_media_archive_daily_limit` / `_media_archive_per_message_limit` | `100` / `50` / `4` | 单文件上限（MB）/每日件数额度/单条消息件数上限 |
| `_media_archive_summary_enabled` / `_media_archive_video_frames` | `true` / `5` | 聊天记录归档一句话 VLM 摘要开关 / 视频轻量抽帧数（ffmpeg） |
| `_notes_enabled` / `_notes_db_path` / `_notes_max_per_chat` | `true` / `data/notes.sqlite3` / `200` | 笔记/备忘录（bot.notes）：Markdown 笔记+待办勾选+图片收纳；「做完了/完成了」自然语言勾选；db_path 走 runtime 重映射 |
| `_time_sync_enabled` / `_time_sync_servers` / `_time_sync_max_drift_ms` | `true` / `ntp.aliyun.com,cn.ntp.org.cn,pool.ntp.org` / `1500` | 联网授时（bot.timesync）：NTP 校准提醒/调度时间基准（不改系统钟，全服务器超时回退系统钟+告警）。⚠ 1500 是**单源**可信上限：一家之言超此即拒收；TS-CONSENSUS（2026-09-29）另开一条互证出口——≥2 家**独立供应商**（`_vendor_key` 折到 host 末两节，不是数端点；同家两个子域不算两家）、簇**直径** ≤1.0s（HTTPS `Date` 的一个量化步长）、每枚往返 ≤0.5s（不被建连耗时污染）、中位数 ≤60s 时按中位数采纳，并用 warning 提示"去把系统时间同步打开"；因为旧形态把"本机钟本来就偏 1.6s"钉成永远修不好（离线现算：偏 1.4s 可校、偏 1.6s 起永久失败）。TS-SOCKET 同日修：默认套接字工厂必须显式 `SOCK_DGRAM`——`socket.socket()` 缺省是 TCP，UDP/123 的 SNTP 腿因此静默超时，注入替身的单测全绿而生产从未校成过一次 NTP |
| `_error_card_enabled` / `_error_card_cooldown_seconds` / `_error_card_stack_frames` | `true` / `60` / `8` | 统一错误报告卡（bot.error_card）：能力异常回云母诊断卡（方法/栈摘录/脱敏配置/版本/协议/IDs/运行时长+求助指引）；同会话冷却防刷屏 |
| `_render_max_concurrency` / `_render_wait_budget_ms` | `1` / `0` | 渲染 Phase 2：后端并发信号量上限 / 单卡等待预算（超预算纯文本兜底）；0=预算不生效；解锁建议 2 / 1500（性能席实测 warm P50 −64%） |
| `_reactions_enabled` / `_reactions_probability` / `_reactions_cooldown_seconds` / `_reactions_max_per_hour` | `true` / `0.2` / `30` / `20` | 表情回应（bot.reactions）：识别 QQ(SnowLuma)/TG 贴纸回应注入上下文+主动贴表情；概率/冷却/时限三重防刷屏门。**主动贴表情只支持群消息，私聊一律不派发**——QQ 侧本就没有私聊表情回应通道（**非迁移退化**），SnowLuma 对非群消息直接拒（详见 snowluma-setup.md §1 能力边界） |
| `_reactions_db_path` / `_reactions_store_days` | `data/reactions.sqlite3` / `90` | 贴纸回应持久化（B 线 2026-09-16「把所有表情贴纸存下来」）：识别事件双写（缓冲+SQLite 幂等合并）、按 emoji/按用户聚合统计、保留期裁剪（启动期 prune）；db_path 走 runtime 重映射。owner：`sources/reaction_store.py ReactionStore` |
| `_reactions_meme_enabled` / `_reactions_meme_probability` / `_reactions_meme_cooldown_seconds` / `_reactions_meme_daily_max` | `true` / `0.15` / `120` / `6` | 双层表情·第二层（B 线 2026-09-16）：情绪信号命中且第一层未贴 → 意图匹配表情库 VLM 情绪标签加权抽图小概率发送；独立冷却/每日上限/每小时帽（沿用 `_reactions_max_per_hour`）/C1 悲伤门；互斥=同消息先贴后包 |
| `_market_enabled` / `_market_timeout_seconds` / `_market_cache_seconds` | `true` / `6.0` / `60.0` | 全球股指能力（东财 17+MOEX ISS，18 指数） |
| `_stocks_enabled` / `_fx_enabled` | `true` / `true` | 个股行情/汇率路由开关（已落 config.py `bot_stocks_enabled`/`bot_fx_enabled`，.env `BOT_STOCKS_ENABLED`/`BOT_FX_ENABLED` 可关；base_router getattr 读取） |
| `_commodities_enabled` / `_bond_enabled` / `_northbound_enabled` | `true` / `true` / `true` | 商品（COMEX 金银铜+WTI）/国债收益率/北向资金路由开关。2026-09-21 补键：`base_router.py:364/378/388` 一直 getattr 读这三个名而 Config 无字段 ⇒ 补键前三路 `.env` **完全关不掉**；缺省 True 与补键前逐字节同行为。owner：`base_router` 谓词 + `domains/finance/capabilities/market.py` |
| `_market_retry_on_empty` | `true` | 东财空响应受控重试（限流返回空 JSON 时单次重试+0.6s 退避；真异常不重试；仍空→诚实降级不缓存） |
| `_randpic_enabled` / `_randpic_dirs` / `_randpic_trigger_words` / `_randpic_max_file_mb` | `true` / `[]` / `[]` / `20` | 随机图：只读用户自定义文件夹（**必须配 `_randpic_dirs`**，JSON 字符串数组），绝不自建目录 |
| `_poke_enabled` / `_poke_private_cooldown_seconds` / `_poke_group_cooldown_seconds` / `_poke_probability` / `_poke_admin_bypass` / `_poke_reply_enabled` / `_poke_poke_back` / `_poke_group_text` / `_poke_private_text` | 见 config.py | 戳一戳统一分发：回戳（NapCat 扩展 API，失败静默）/话术/冷却/概率。**热改面 2026-09-20 CATALOG-FIX 改口**：本行 9 键无一在 `SETTABLE_KEYS` ⇒ 旧文「除 `_poke_admin_bypass` 外 8 键均可热更 ✅」为假。🟡需重启（`RESTART_REQUIRED_KEYS` 在列）8 键＝`_poke_enabled`/`_poke_private_cooldown_seconds`/`_poke_group_cooldown_seconds`/`_poke_probability`/`_poke_reply_enabled`/`_poke_poke_back`/`_poke_group_text`/`_poke_private_text`；`_poke_admin_bypass` ❌无热改面（两表均未登记）。**2026-09-16 用户裁定：`_poke_poke_back` 缺省 false→true（回戳进五件套）** |
| `_poke_reply_mode` / `_poke_affinity_enabled` / `_poke_affinity_delta` / `_poke_affinity_daily_max` | `mix` / `true` / `0.5` / `5.0` | 戳一戳 v2（2026-09-16 批）：回复形态 mix=固定话术/LLM 话术/表情包三选一确定性轮换（llm 失败→固定、库空→固定；群聊回复自动 @戳者）；好感度=门控放行后 observe 小额正向（delta_override），每会话每日上限防刷（0=不记） |
| `_content_route_enabled` / `_content_route_model` / `_content_route_order` / `_content_route_words` / `_content_route_intimate_threshold` / `_content_route_normal_threshold` / `_content_route_context_turns` / `_content_route_max_ttl_minutes` / `_content_route_intimate_ttl_minutes`（v21r5：两开关同一 TTL） / `_content_route_idle_reset_minutes` / `_content_route_group_per_user_enabled`（v21r5） / `_content_route_group_whitelist` / `_content_route_group_blacklist`（生产已填 1108838060/631785829/662948429） / `_content_route_private_whitelist` / `_content_route_private_blacklist`（v21r5 私聊两面：白名单**空=放开**、非空=仅名单内；黑名单最高优先） / `_master_love_enabled` / `_master_love_admins`（条目 "qq"=全域 / "群号:qq"=仅该群；生产=[3865067623, 1722380002]） | `true` / `grok-4.6` / `grok-4.6,gemini-3.8-flash` / 空 / `60` / `25` / `4` / `120` / `60`（v21r5） / `10` / `true`（v21r5） | R-18 内容感知路由（runtime/content_route.py，2026-09-16 批；**2026-09-17 v2 修订**）：模型自评标签层与升级重试已删（gemini/grok 把标签元指令当注入攻击整轮拒答——生产拒答原文点名 routing tags）；检测改纯本地信号 L1 强词表（+70/次）+ L2 上下文强词累积（+35/次；擦边词不记分——普通模式可以擦边，留在默认链）+ L4「亲密模式 开/关」（含倒装句式）；滞回（≥60 切、≤25 回、中间保持前态）；INTIMATE 时自动候选序=order 配置（**用户裁定 gemini 第二位**）并跳过影子并发；会话准入门=私聊/控制台常开、群聊黑白名单制（`_group_whitelist` 命中且不在 `_group_blacklist`；白名单空=群聊亲密面关闭；群内手动开关仅管理员或 Master Love 名单可拨）；Master Love=名单内 master 会话自动亲密档+恋人语气指令注入（显式「亲密模式 关」的 normal 钉不被覆盖）；拒绝模板句只记日志不重试；fail-open；管理员 override 分支不受影响。**v21r5 双开关+四名单（2026-09-19）**：群聊两级状态——管理员拨群键=全群（开关二，既有语义保留）、成员拨成员派生键=仅本人（开关一，键=群键`||u:`用户号；`_group_per_user_enabled` 总闸，False=成员指令不受理；群级 OFF 不压制个人档）；亲密档 TTL=`_intimate_ttl_minutes`（默认 60 分钟）按激活时刻惰性过期（活跃不续期、重新开启即重置；MAX_TTL=120 仍为全状态硬上限）；私聊两面名单入 explicit_allowed_for_session（黑名单永远赢——Master Love 压不过黑名单；console 不参与私聊名单门）；注入与路由双门同源（resolve_intimate_context 按发送者逐消息合成，L1/L2 群内按成员键隔离不互相污染） |
| `_chat_max_input_tokens` / `_chat_max_output_tokens` | `131072` / `65536` | 上下文钳制全局缺省（2026-09-17 用户裁定：输入 128K/输出 64K）：输出=请求 max_tokens 封顶；输入=粗估（CJK≈1 token/字）超限从最旧非 system 消息丢起。router 层强制，不可绕过 |
| `_music_dir` | `data/music` | 点歌音频缓存目录（经 runtime_paths 重映射；DATAFIX 收口） |
| `_addressing_preferences_db_path` | `data/addressing_preferences.sqlite3` | 用户称谓/性别偏好持久化（用户显式设置或纠正；优先于一切推断；经 runtime_paths 重映射，DATAFIX 收口。owner：`domains/chat_reply/character/addressing.py AddressingPreferenceStore`） |
| `_rate_limit_group_max_per_hour` / `_rate_limit_group_max_per_minute` | `0` / `0` | 群聊专属句数帽（用户口径：每小时 60 句、每分钟 3 句；**代码默认 0=该帽不生效**）；InMemory 与 SQLite 限流器双实现均生效；两键均已入 SETTABLE_KEYS 可热更 |
| `_rate_limit_emotion_exempt` | `true` | 情绪低落豁免群句数帽；✅热更（SETTABLE_KEYS） |
| `_shared_group_context_enabled` | **`false`** | 群摘要**真总开关**（原 `BOT_GROUP_DIGEST_ENABLED` 为死字段已删，勿再配置）；🟡需重启（`RESTART_REQUIRED_KEYS` 在列、`SETTABLE_KEYS` 未登记；旧「✅热更（SETTABLE_KEYS）」为假）。⚠️本表此前误写默认 `true`，以 config.py `False` 为准 |
| `_rate_limit_group_hourly...` 之外的新限流键 | — | 见 A24 与 domains/chat_reply/policy/rate_limit.py `RateLimitSettings`（SQLite 版群帽/豁免已对齐 InMemory，热改不支持=架构取舍） |
| `_campus_enabled` / `_campus_self_ids` / `_campus_group_whitelist` / `_campus_notify_qq` / `_campus_push_bot_id` / `_campus_db_path` | **`false`** / `[]` / `[]` / 空 / 空 / `data/campus.sqlite3` | 校园自动转发（campus v1，2026-09-15 批）：监听学校号（NapCat-school 第二实例 WS 3002）所在群文本消息→私聊实时转发主人号；三重来源门（enabled ∧ self_ids ∧ whitelist 任一空=关闭，绝不猜账号/猜群；whitelist 支持 `*` 显式放行全部群）；纯监听绝不向学校群发消息；db_path 走 runtime 重映射；设计权威=`MyWorkspace\CampusInfoButler\docs\specs\2026-09-15-campus-info-butler-design.md` |
| `_tts_enabled` | **`false`** | 语音合成（bot.tts，2026-09-17 批）总开关：对接本机 GPT-SoVITS v2ProPlus HTTP API（`api_v2.py` 的 `/tts`）；关=路由不占位、对话不配音 |
| `_tts_api_url` | `http://127.0.0.1:9880` | GPT-SoVITS API 服务地址；需与 `api_v2.py` 启动参数一致（只连 loopback，不上传文本到外部） |
| `_tts_gptsovits_dir` | 空 | GPT-SoVITS 安装目录（如 `C:\Software\GPT-SoVITS-V2Pro`）；仅用于把相对参考音频路径解析成绝对路径 |
| `_tts_ref_audios` | `[]` | 参考音频清单，元素格式 `"路径\|参考文本\|语种"`（如 `"ref/shorekeeper_01.wav\|……\|zh"`）；**必须配**，空=能力返回"缺参考音频"降级文案。约束：3~10 秒干声、单人单情绪、参考文本与音频逐字一致。走 `_parse_file_list` 校验器（不可走 id_list，含 `\|` 与中文逗号） |
| `_tts_trigger_words` | `[]` | 追加触发词（与内置 `说/语音/念/朗读/tts/say`+拼音词合并）；触发词后须跟正文才命中，裸触发词交回人格对话 |
| `_tts_output_dir` | `data/tts_output` | 合成 wav 落盘目录（走 runtime 重映射，DATAFIX 收口）；同参数命中 sha256 缓存则复用 |
| `_time_sync_http_enabled` / `_time_sync_http_url` | `true` / 空（内置 `https://www.baidu.com,https://www.qq.com`） | HTTPS 授时兜底（R3 停摆批 2026-09-17 立）：当时把它讲成"UDP 123 被墙"，**2026-09-29 实测该端口通**（`ntp.aliyun.com`/`cn.ntp.org.cn`/`pool.ntp.org` 互差 <0.01s）、真凶是 NTP 腿用了 TCP 套接字 ⇒ 本腿定位是"NTP 真的被拦时才用"，不是现役主源；HEAD 取 RFC 7231 `Date` 头估偏移（1s 粒度 +0.5s 量化居中，θ=server−(t0+t3)/2；⚠ 建连整段落在采样窗内 ⇒ 慢链路会把偏移虚报，2026-09-29 实测 3s 建连就能把分毫不差的钟报成超限并拒收）；失败链 NTP→HTTPS→多源互证→系统钟每级一行日志，回退告警带上本轮各源读数；复用 `_time_sync_max_drift_ms` 钳制与 RTT 上限；仅收 `https://` 端点，url 逗号分隔可换。内置表 2026-09-29 移出 taobao（其 `Date` 实测自错 −62.5s，像边缘缓存值不是钟），只留两家**不同供应商**——互证那一级怕的正是同家两台一起错伪造共识 |
| `_tts_preset` | `shorekeeper` | 语音预设选择（G-2 契约层 2026-09-20，**合成参数唯一缺省源**=`domains/media/tts_presets.py` 中央预设表：带每参数 rationale/引擎域值/seed_policy/读法词典占位/八硬编码收编，其中 `split_bucket=False`=M-76 死意图显式化）；枚举成员=TTS_PRESET_IDS（装载期即拒未知值，与注册表键集一致性由 `tests/test_tts_presets.py` 锁）；下方 `BOT_TTS_*` 数值键降级为管理员覆盖（env 显式值 > preset；v1 预设值=本表缺省值，零行为变更；U-13 周期后收敛） |
| `_tts_max_chars` | `200` | 单次合成文本上限（超出按句末截断，静默无用户面提示——audit_tags `truncated=true` 留痕）；**`0`=不限（不按字数截断，M-35 语义反转修死，全仓 `*_MAX_CHARS=0 表不限` 惯例自此在 TTS 域成立）**；「不限≠无界」——必过 `_tts_hard_max_chars` 中央硬顶 |
| `_tts_hard_max_chars` | `2000` | 文本中央硬顶（G2-R3）：超顶=拒绝合成+OperationalIssue 留痕（`tts_service_rejected`+audit `over_hard_cap`）+引导文案，**不静默不拆条**（拆条归 H 波 M-63 修后）；`0`=禁配无界（取内置常量 2000）；自动配音路超顶=静默放弃增益 |
| `_tts_max_audio_bytes` | `8388608`（8 MiB） | 产物字节硬顶（G2-R3）：v2ProPlus=32000Hz/16bit/单声道 ⇒ 64,000 B/s 恒定，8 MiB≈131s（覆盖现行 200 字档 ≈82s≈5.3MB 留 50% 余量）；超顶=体检闸拒（`tts_bad_audio` 族）不入缓存不落盘不出站；`0`=禁配无界（取内置 8 MiB）；**换 media_type/采样率须重裁**（字节顶≈时长顶的换算前提） |
| `_chat_strict_priority` / `_chat_channel_cooldown_seconds` / `_chat_failover_min_hop_seconds` | `true` / `90` / `3` | v21r2 R1 故障转移链完善（2026-09-17 用户裁定「永远按注册表优先级处理」）：同名模型渠道聚合排序严格按注册表 priority（价格/EWMA 只作同级 tiebreak，false=旧行为）；真实调用失败的渠道 90s 冷却降级到候选队尾（不剔除、全冷却原序放行，落 SQLite 重启不丢）；链预算止损=除首跳外剩余预算 <3s 不再发起新跳（0=关）。owner：`llm/model_router.py` + `llm/channel_health.py` |
| `_tts_timeout_seconds` | `60.0` | 单次 `/tts` 请求超时（≥1.0，装载期即拒越界值）；超时返回守岸人口吻降级文案，绝不阻断出站 |
| `_tts_speed_factor` | `0.85` | 语速倍率；**域=[0.6,1.65]**（引擎 WebUI 滑杆，report-T53.md；越界装载期即拒，M-35）；中文建议 0.8~0.9，过快会有电音感；≠1 时引擎自动关 split_bucket 并走逐段串行（性能语义，T53 §4.6） |
| `_tts_temperature` | `0.9` | 采样温度（语气起伏，越高越活但越不稳）；**域=[0,1]**（T53，越界装载期即拒） |
| `_tts_top_k` / `_tts_top_p` | `15` / `1.0` | 采样参数；**域=top_k [1,100]、top_p [0,1]**（T53 WebUI 滑杆，越界装载期即拒） |
| `_tts_text_lang` | `zh` | 合成文本语种；合法域 11 值 `auto/auto_yue/en/zh/ja/yue/ko/all_zh/all_ja/all_yue/all_ko`（装载期枚举校验+出门一律 casefold——POST 入口引擎用原值断言，"ZH" 必 400） |
| `_tts_text_split_method` | `cut5` | 切句方式 `cut0..cut5` 六值枚举（装载期校验；长文本按句切分后逐段合成再拼接） |
| `_tts_cache_enabled` | `true` | sha256 结果缓存开关（键=canonical_json(identity_version+引擎地址+参考指纹+预设身份+生效参数+清洗后文本)；LRU 上限 512）；seed 由键派生（同句恒同音色，G2-R3 报备项） |
| `_tts_cache_max_bytes` / `_tts_cache_max_age_days` | `0` / `0` | 产物目录磁盘配额（U-04：`data/tts_output` 定性=**缓存**，接中央 `cache_policy.enforce_quota` 最旧先删+保鲜期；**缺省 0/0=不限制，字节级行为不变**）；换缓存键空间（identity_version 换代）产生的旧 wav 孤儿靠它回收。owner：`domains/media/capabilities/tts.py synthesize` |
| `_tts_auto_reply_enabled` | **`false`** | 对话自动配音：LLM 回复生成后追加语音条（在能力包装层附加 `CapabilityResult.audio`，不侵入 domains/chat_reply/runtime/pipeline.py） |
| `_tts_auto_reply_scope` | `private` | 自动配音适用会话：`private`=仅私聊 / `group`=仅群聊 / `all`=双向（**三值枚举装载期校验**；M-51 漏登 `group` 已补）；群聊默认不配音以免刷屏；**scope=礼仪维度**，群面另受内容群白名单安全门约束（`bot_content_route_group_whitelist`，黑名单永远赢；白名单空=群面不配音绝不猜群，M-17） |
| `_tts_auto_reply_max_chars` | `120` | 自动配音文本上限（比命令式合成更短；**`0`=不限**，超硬顶=放弃增益纯文本发出） |
| `_tts_auto_reply_probability` | `0.05` | 自动配音概率门（2026-09-19 批）：符合条件的回复按此概率配音，**确定性哈希实现**（`should_voice_reply`，seed=`session_id:message_id`，与 `policy/gate.py` 的 `deterministic_group_reply_lottery` 同款）——同一条消息结果恒定，可复现可审计，不用 `random` 以免测试 flaky。`0`=永不配音、`1.0`=全量配音 |
| `_tts_auto_reply_always` | **`false`** | 跳过概率门的调试/验收旁路：置真则凡过前五道门的回复一律配音（逐条听音用）。日常勿开——等于把概率当 100% |
| `_tts_voice_hook_enabled` | **`false`** | G-3 配音出站路径开关（M-10/M-13 根修，2026-09-20）：`true`=自动配音改走 pipeline post-review hook（`domains/media/voice_enricher.py` 经 `RuntimePipeline.outbound_voice_enricher` 在 review 批准后、render 前恰调一次；取文口径翻正=只合成 review 批准后的正文，被拦正文零落盘；合成失败挂 `tts_*` OperationalIssue 码族走 300s 抑制告警；群内正文照发、降级仍归中央 A-19）；`false`=旧能力包装路径（根 `_attach_voice_reply`，逐字节现状）。**双态互斥**（键开不装配旧包装）；装配期冻结（重启生效）；退役第二步（摘旧包装）等真机浸泡窗 |
| `_teaching_enabled` / `_teaching_db_path` | `true` / `data/teaching_knowledge.sqlite3` | V2.1 S8 教导知识库（V21-TEACH-001，`domains/chat_reply/character/teaching_service.py`；装配已落盘 `plugins/bot_unified_runtime/runtime/service_wiring.py`（B2①），受 `_v21_service_wiring_enabled` 主门（缺省关）约束，待重启生效）：用户提议→管理员审核→生效为「背景知识」注入（仅供理解、禁止复述；封闭三值类目 preference/fact/correction+内容红线扫描+注入面结构隔离=不可达人格/权限/路由）；撤销+版本回滚（回滚=新增一版）；db_path 走 runtime 重映射。owner：`domains/chat_reply/character/teaching_service.py TeachingService` |
| `_database_broker_enabled` | `true` | V2.1 S8 数据库安全查询代理（V21-DB-001，`plugins/bot_unified_runtime/runtime/database_broker.py`；装配已落盘 `plugins/bot_unified_runtime/runtime/service_wiring.py`（B2①），受 `_v21_service_wiring_enabled` 主门（缺省关）约束，待重启生效）：仅注册 query_id 的参数化只读查询——白名单 registry（SQL 模板静态校验+参数 schema+排序列注册枚举）+ 只读 URI 连接 + 2s 语句超时 + 200 行限额（截断如实置 truncated）；预注册 5 查询指向 db-owners 在册库（发送队列/好感度/账本/审计/订阅）。owner：`plugins/bot_unified_runtime/runtime/database_broker.py DatabaseBroker` |
| `_v21_service_wiring_enabled` | **`false`** | V2.1 B2① 服务装配组主门（WIRE-SVC 席；`plugins/bot_unified_runtime/runtime/service_wiring.py` 装配+进程内注册表）：缺省关=零装配零副作用（不改现网行为）；开启后按分门装配 WORLD/KB/DB/TEACH 四服务（worldbook/knowledge/teaching/database_broker）供消费方 `get_v21_service(id)` 取用；单服务装配失败 fail-open 记 warning 跳过。L41 memory 待用户裁决（独立新库 vs 同源同库）不接。owner：`plugins/bot_unified_runtime/runtime/service_wiring.py` |
| `_worldbook_enabled` | **`false`** | 世界书服务分门（V21-WORLD-001，`domains/chat_reply/character/worldbook_service.py`）：主门 ∧ 本门=装配 `build_worldbook_service`（悬空/循环引用+Token 预算+草稿隔离；库 `data/worldbook_versions.sqlite3` 走 runtime 重映射） |
| `_knowledge_service_enabled` | **`false`** | 知识检索服务分门（V21-KB-001，`domains/chat_reply/character/knowledge_service.py`）：主门 ∧ 本门=装配 `build_knowledge_service`（FTS/向量/RRF 三通道+原子重建；persona/kb_wiki 两源，kb_wiki 另受 `_kb_wiki_enabled` 约束） |
| `_schedule_enabled` | **`false`** | 全场景日程服务面总开关（V2.1 §4，`domains/schedule/{llm_draft,timetable,delivery}.py`；**未接线，装配属后续席位**）：LLM 草稿解析（自然语言→结构草稿，缺信息只澄清禁猜）+课表截图识别（缺学期/节次表不发布）+到点投递（occurrence→SendQueue 提交面；真实出站端口未授权前不注入出站构造器）。与既有 schedule 引擎（`schedule_service` 族）共库 |
| `_schedule_db_path` | `data/schedules_v21.sqlite3` | 日程引擎 SQLite 库（`build_schedule_service` 消费；getattr 兜底值与之一致）；走 runtime 重映射 |
| `_schedule_llm_draft_enabled` / `_schedule_timetable_enabled` / `_schedule_delivery_enabled` | `false` / `false` / `false` | 三子服务开关：LLM 草稿解析（走主路由，费 token 默认关）/课表识别（走识图 registry，还受 `_vision_enabled` 与 registry 非空双门）/到点投递 tick |
| `_schedule_delivery_max_retries` | `3` | 投递失败退避重试上限（指数退避 1/2/… 分钟起；超限置 `delivery_failed` 终态；计数进程内存记账，重启归零随 reconcile 重分流） |
| `_schedule_exceptions_path` | `data/schedule_exceptions.json` | 调休/节假日例外表 overlay（JSON；随包模板 `domains/schedule/data/calendar_exceptions.json` 先载、本文件同键覆盖）。**年份不在表=unknown 不猜**：只有显式登记的 holiday/workday 才改变 `follow_calendar` 标签实例的投递，unknown 照常投递但回执如实标注 |
| `_persona_versioned_injection` | **`false`** | 人格核心注入走版本库（V21-PERSONA-001 装配接线，`domains/chat_reply/character/persona_service.py`）：True=chat 链人格核心从 `data/persona_versions.sqlite3` 取（幂等 baseline 灌入→`build_core_injection` 唯一出口，带 version+sha256 溯源；托管 active 指针在场不抢）；False（默认保守灰度）=文件直读路径逐字节不变；任何故障（灌入失败/库空/损坏隔离/全损）fail-open 回退文件路径+一行告警，绝不阻塞消息链。owner：`domains/chat_reply/character/persona_injection.py` |
| 🔴 `_file_export_via_queue`（**已退役，不是 Config 字段**） | 无（`config.py` 零命中） | 2026-09-19 S0-ROOT-c 曾把它做成「门开才走管线」的开关（v21r4-b2-direct-collect-plan §3.4 直连收编④），**2026-09-24 裁定 R-4 已连开关带关态直发分支一并从生产根删净** ⇒ 文档旧写法「默认值 `false`／缺省 False＝旧直连逐字节等价／重启生效」是假旋钮：`Config` 无 `bot_file_export_via_queue` 字段，加上 `extra='ignore'` 后 `.env` 写它等于没写，拨它不改变任何行为。现役唯一路径＝`_send_files_through_unified_pipeline`（`CapabilityResult.files` 件→`FileTransferGateway`，群 upload_group_file/私聊 upload_private_file，成功/失败文案由回执态驱动）。退役判据登记＝`domains/core/decision/outbound_registry.py` 的 DirectSendEntry（该点判 ABSORBED，note 明写「四枚 `*_via_queue` 键在 config.py 零命中」）；本节标题「逐键对 config.py 核实」对本行**不适用**，保留本行只为可溯 |
| 🔴 `_group_welcome_via_queue`（**已退役，不是 Config 字段**） | 无（`config.py` 零命中） | 同上退役（R-4，收编②）：本键已无字段、无读点，写它不生效；现役唯一路径＝`_send_text_through_unified_pipeline`（capability=bot.group_welcome，SENT/REDIRECTED 才记 group_welcome_sent）。**仍在册的真旋钮是 `_group_welcome_enabled`**（`config.py` 有字段），要关入群欢迎语改那枚、不是本枚。判据登记同 `outbound_registry.py` DirectSendEntry |
| 🔴 `_cookie_qr_via_queue`（**已退役，不是 Config 字段**） | 无（`config.py` 零命中） | 同上退役（R-4，收编③）：写它不生效；现役唯一路径＝`_send_parts_through_unified_pipeline`（mixed 件 text=""+image，`file:///` 引用由 onebot `_resolve_local_file_ref` 显式解析，失败静默、文本兜底先行不变）。判据登记同 `outbound_registry.py` DirectSendEntry |
| 🔴 `_cookie_expiry_reminder_via_queue`（**已退役，不是 Config 字段**） | 无（`config.py` 零命中） | 同上退役（R-4，收编①）：写它不生效；现役唯一路径＝`_deliver_cookie_expiry_report_via_queue`（SendRequest→SendQueue→内联投递，SENT 才算送达，dedupe_key/request_id 带本地日期＝当日幂等）。**每日提醒的真开关是 `_cookie_expiry_reminder_enabled`**（`config.py` 有字段，2026-09-21 幽灵读点补键批落地，此前 job 永远注册关不掉）。判据登记同 `outbound_registry.py` DirectSendEntry |
| `_cookie_expiry_reminder_enabled` / `_divination_fortune_secret` / `_video_deep_cooldown_seconds` / `_subscription_outbox_sent_retention_days` / `_subscription_seen_retention_days` / `_subscription_outbox_max_attempts` / `_subscription_outbox_sending_stale_seconds` | `true` / `''` / `300` / `0` / `0` / `0` / `0` | **幽灵读点补键批（2026-09-21，`tests/test_config_read_points_declared.py` 执法）**：代码一直 `getattr(config, "bot_…", 缺省)` 读这七枚名而 `Config` 无字段 ⇒ 读出来永远是缺省、`.env` 写了也不生效（`extra='ignore'` 连报错都没有）。逐枚缺省**等于原 getattr 缺省** ⇒ 补键当笔现网零行为变更，只是把"假旋钮"变成真旋钮。典型咬痕：cookie 到期提醒 job 此前**永远注册关不掉**；运势 HTTP 面 `fortune_secret` 恒空 ⇒ 永久不启用；订阅 outbox 四枚保留期/重试参数（读点是 `or` 链，0 恒回退模块常量）。owner：`__init__.py` 提醒 job / `domains/divination/{api/facet,store/draw_store}.py` / `domains/chat_reply/capabilities/chat.py` / `domains/subscribe/sources/subscription_store_v2.py` |
| `_outbound_gate_enabled` | **`false`** | 中央出站防风暴闸总开关（B4-spec §1，真身 `domains/transport/sender/outbound_gate.py::submit_active_push`）：False=直通 `send_queue.submit`，零判定、零 store 读写=现状字节级不动；聚合域（紧急信息等）主动投递**只允许**经此闸触达队列。2026-09-22 统一波（WAVE42 裁定件 `.superpowers/sdd/2026-09-21-unify-wave/decisions/WAVE42-active-push-central-exit.md`）：每日群摘要 / 日常助理两族主动投递已改道本闸（关态＝与裸 `submit` 同形 passthrough，线上零变更）。仍直调 `send_queue.submit` 的族清单以结构锁 `tests/test_outbound_gate.py::test_existing_families_still_submit_directly` 与 `tests/test_outbound_bypass_prohibition_gate.py` 的豁免表为准（本处不手写族数）；旧口径为「存量族只登记不迁移」（当时值，见 `docs/design/emergency-info-unify-summary-20260919.md` §十） |
| `_outbound_gate_quiet_defer_enabled` 与 `_outbound_gate_urgent_severities` | `true` 与 `["P0","P1"]` | 仅 enabled=True 时生效：非紧急等级在安静时间窗内顺延到窗结束，P0/P1 穿静默（D-2 裁定映射）。窗判定唯一事实源=`domains/chat_reply/policy/quiet_hours.py` 的 `QuietHoursSettings`，**闸内不自造 HH:MM 解析**（T13 锁）；顺延执行用队列原生 `deliver_after` 原语（`queue.py:418-438`），不建第二张 delay 表 |
| `_outbound_gate_max_per_target_per_minute` 与 `_outbound_gate_max_per_target_per_hour` | `2` 与 `6` | 每主体（键=`target_scope:target_id`）60s 与 3600s 双滑窗上限，超限=defer(now+60s)。**热改语义（B8-MERGE 实证后收紧，勿按字面理解成"写了就生效"）**：闸本体支持 callable 设置源（`outbound_gate.py:137/:324` 每次判定实时求值、求值失败回退缺省关闭），但装配 builder 现在走 `getattr(裸 config)` 快照（`:725-730`）且合并层 `_RUNTIME_HOT_OVERRIDE_FIELDS` 未登记本族键 ⇒ `/bot runtime set` 写了不生效，**七键一律入 `domains/chat_reply/runtime/settings.py:333 RESTART_REQUIRED_KEYS`**（改后需重启）；接线时补登记两行后方可把这两键回白名单（不复刻台账#3「SQLite 限流不支持热改」旧坑的**终态**目标不变）。**与入站 chat 限流是两个对象**：入站真值见 `_rate_limit_chat_*`（代码缺省 60/6/4 + 45s 最小间隔，生产实值取 `.env`），旧口径「每主体 3/分钟·20/小时」只属于**未接线**的日程 v2 引擎（`schedule_service.py:152-153`），不得描述现役生产 |
| `_outbound_gate_db_path` | `data/outbound_gate.sqlite3` | 闸自身计数 store（单表 `outbound_gate_sends(subject_key, sent_at_utc)`，确定性样板抄 `schedule_send_log`）；**已进 `path_fields` 重映射**（`config.py:1188`，runtime_paths 铁律 6）。store 故障=fail-open 放行 + error 日志 + `outbound_gate_degraded` 告警，**绝不因闸病丢消息**（T4 方向锁） |
| `_outbound_verify_enabled` | **`false`** | 送达核验 Tier1/Tier2 开关（治「谎报送达」，B4-spec §3.2 与其 §8 Amendment）：开启后 ①发送前摘段丢弃会在 SENT 回执挂 `segment_dropped_local` 审计注记（观测日志本身无条件出，只记类型名零正文）；②装配期给 `drain_send_queue_once` 传 UNKNOWN 段确认器。**一律不改 `ReceiptState`**（枚举冻结锁用例在 `tests/test_delivery_verification_tier1.py`，改判=重投风暴）；Tier2 的「明确不存在→False」被 `_ONEBOT_GET_MSG_NOT_FOUND_PROVEN=False` 取证锁钉成生产不可达，SnowLuma `get_msg` 语义真机取证前不参与重投判定。缺省 False=现状逐字节 |

| `_reply_policy_enabled` / `_reply_policy_db_path` | `true` / `data/reply_policy.sqlite3` | **2026-09-28 §51 波（per-user 永久回复策略）**：总闸关＝读写整条不存在（唯一咽喉 `character/reply_policy.py::shared_reply_policy_store`，装配层 `chat.py` 用 `content_route_config` 快照懒建、进程级按路径缓存 ⇒ 非每请求现读）；db_path 走 runtime 重映射。**热改位＝两枚均 RESTART**（合并表 `_RUNTIME_HOT_OVERRIDE_FIELDS` 未登记）。全行权威见回复域表（`BOT_REPLY_POLICY_*`）。owner 登记见 `docs/db-owners.md` |
| `_reactions_sentiment_enabled` / `_reactions_sentiment_timeout_seconds` / `_reactions_sentiment_cache_ttl_seconds` | `true` / `8.0` / `120` | **2026-09-28 §51 波（贴纸语义匹配判定腿）**：贴前读 bot 本轮实际回复由大模型判受控情感再选脸；判定腿真身 `domains/meme/reactions/sentiment_selector.py`，engine/capability 调用点直读 Config 快照，合并表未登记本族键 ⇒ `/bot runtime set` 写进去也到不了判据。**热改位＝三枚均 RESTART**。全行权威见回复域表（`BOT_REACTIONS_SENTIMENT_*`） |
| `_chat_rate_limit_redrive_max_wait_seconds` / `_chat_rate_limit_redrive_max_attempts` | `270.0` / `3` | **2026-09-28 限流补回窗（chat 入站）**：`build_redrive_settings` 从 Config 烘进 `RuntimePipeline` 构造（`policy/rate_limit.py`），装配期一次定值、非合并层实时读 ⇒ **热改位＝两枚均 RESTART**。全行权威见限流域表（`BOT_CHAT_RATE_LIMIT_REDRIVE_*`）；`_redrive_enabled` 早于本波在册 |
| `_control_plane_files_roots` | `""`（空） | **2026-09-28 F-1 根修（控制面文件读取根白名单）**：`/api/v1/files/read` 据装配期快照构造 `FileReadGateway`（`control_plane/api/platform.py::read_file` 的 `getattr` 字面直读），空⇒503 诚实拒绝绝不回落 cwd；敏感子树/后缀常驻拒读。**热改位＝RESTART**（合并层未登记）。全行权威见控制面文件域表（`BOT_CONTROL_PLANE_FILES_ROOTS`）；锁 `tests/test_control_plane_files_read_scope.py` |
| `_emergency_info_quiet_breach_levels` | `P0,P1` | **2026-09-28 静默窗源级穿窗表（紧急信息域）**：能力构建期 `getattr` 现读 Config 快照（`capabilities/emergency_info.py`，烘进 frozen 快照 `quiet_breach_levels`），与族级地板取交、只收窄不放宽；紧急十键族整体两表皆不登记，本枚由别席按现算补进 RESTART（同域装配期快照口径）。全行权威见紧急信息表 |
| `_chat_native_tools_enabled` | **`false`** | **2026-09-29 复原波补登（原生工具调用总门，第 19 项 T1「A-6」）**：唯一读取口 `domains/core/search/native_tools.py::native_tools_enabled`，判据 `getattr(config, KEY, None) is True`——**只认严格 True**，配成字符串 `"true"` 也判关（fail-closed：读不到＝没开）。开＝把中央在册表 `runtime.capability_protocols.CAPABILITY_DESCRIPTOR` 的只读子集投影成 OpenAI `tools` 数组（同件 `build_native_tool_schemas`）交 chat 既有工具循环消费；写侧/权限/出站/自指回路面恒在 `WRITE_OR_PRIVILEGED_DENYLIST` 拒绝清单，往白名单塞写类能力即装配锁红。**⚠ 今天装配腿未接**：`domains/chat_reply/capabilities/chat.py` 不 import 本件（施工图 `.superpowers/sdd/2026-09-27-fullload/patches/G19R-T1-chat-wiring.patch.md`）⇒ 拨它不改任何现网行为，别当成「开了模型就能自己查天气」。🟡需重启（`RESTART_REQUIRED_KEYS` 在列、`SETTABLE_KEYS` 未登记；读点是调用方交来的装配期快照）。锁 `tests/test_native_tools.py` |
| `_person_profile_enabled` | **`false`** | **2026-09-29 复原波补登（会话画像整链总门，需求 11 线）**：两处读取口同一判据 `getattr(config, …, False)`——`domains/chat_reply/character/person_profile.py::build_person_profile_store`（建库）与同件 `compose_person_profile_context`（渲染）。关＝返回 `None` 且**连库文件都不碰**（写侧 `domains/chat_reply/character/memory_extract.py::_settle_person_profile` 见 `profile is None` 连画像件都不 import ⇒ 缺省关态逐字节不变）。开＝还要 `bot_memory_db_path` 非空、建出的 store `available` 才真生效，抽取到的事实按 `person_profile_key(sender_id, platform_domain)` 现算键落进**记忆库同库**（不另起 db 文件）的画像表族（facet / 言行事件 / 审计 / 墓碑）。**⚠ 现网只写不读**：渲染出口 `compose_person_profile_context` 生产侧零调用方（只在本件 `__all__` 与 `tests/test_person_profile_memory.py` 出现）⇒ 开本门只把画像写进库，不会进提示词。🟡需重启（`RESTART_REQUIRED_KEYS` 在列；热 set 改不动已按 db_path 懒建的进程级 store 缓存） |
| `_person_profile_max_items` | `6` | **2026-09-29 复原波补登（画像取数条数上限）**：唯一读点在 `domains/chat_reply/character/person_profile.py::compose_person_profile_context`，往下交给同件 `render_profile` ⇒ 一次夹住渲染的两段：`facets(key)[: max(1, n)]`（「关于你」条目）与 `search_events(…, limit=n)`（「你交代过、我留着的话」言行）。缺省 `6` 逐字等于模块常量 `_DEFAULT_MAX_ITEMS`，读式 `int(入参 or 本键 or 该常量)` ⇒ **⚠ 配 `0` 回落 6，不是「一条都不给」**；要收窄最低写 `1`（渲染侧 `max(1, …)` 夹形，永不为 0）。与 `_person_profile_enabled` 同病：只作用在渲染腿，该腿今天无生产调用方。🟡需重启（每次渲染现读快照，合并层未登记） |
| `_person_profile_max_chars` | `520` | **2026-09-29 复原波补登（画像注入文本字符预算）**：与 `_person_profile_max_items` 同口读入（缺省 `520` 逐字等于模块常量 `_DEFAULT_MAX_CHARS`），交给 `domains/chat_reply/character/person_profile.py` 内的预算裁剪 `_budget`：预算取 `max(40, int(n))`——总长在预算内＝整段原样拼接；超限＝**从尾部逐行丢**（先丢结尾免责行，再丢言行段，最后才轮到画像条目），并如实追加「（另有 N 条没列出）」，**绝不静默截断**（静默截断＝谎报）。**⚠ 两个边界**：配 `0` 经 `or` 链回落 520（不是「无限制」）；配 1~39 一律被夹成 40（最小可读段）。🟡需重启（同上） |
| `_affinity_v8_enabled` / `_affinity_v8_impulse_cap_z` / `_affinity_v8_ambient_centering` / `_affinity_v8_ambient_halflife_days` / `_affinity_goodwill_band_min` / `_affinity_goodwill_band_max` / `_affinity_goodwill_band_saturate_days` / `_affinity_v8_tier_blend_band` / `_affinity_v8_impulse_weights` | `false` / `0.02` / `true` / `28.0` / `2.60` / `0.55` / `365.0` / `0.25` / 空串（末键 .env 缺） | **好感度 v8 九键（2026-10-02 全量修复批登记；此前 `resolve_v8_settings` 纯 getattr+env 现读、九键零登记＝线上死键风险）**：优先序 v8>v7>v5/v6。总开关 / κ 单轮冲量位移上限（展示最坏 2.0 分/轮，affinity-design §C.2）/ ambient 质量基线去心开关 / ambient EMA 半衰（天）/ 善意底保护带三键（§C.4：新人端近全谱、老关系最多回落峰值减带、带饱和天数）/ 档内 λ 混合边缘（§C.5.1：λ∈[edge,1−edge] 单档原句）/ 六子冲量权重 JSON 文本（空串=按代码缺省；Σ\|w\|≠1 点名告警并整体归一）。日额度共享键 `_affinity_daily_move_cap_z` 的 v8 时代值 0.04 走 .env（§C.7）。九键均不在 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` ⇒ ❌无热改面（改 .env + 重启）。数值规范唯一权威＝`docs/affinity-design.md` |
| `_message_mutation_enabled` / `_message_mutation_window_seconds` | `false` / `120` | **消息编辑/撤回开面（S34b，2026-10-03 用户点头）**：总开关与「不许翻旧账」窗口秒数（平台侧时限更短、以平台为准）。缺省 False＝门关＝能力整体不生效（`authorize_mutation` 首条即 feature_disabled、零平台调用）⇒ 今日现网行为零变化；开面必须改 .env + 重启。两键均不在 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` ⇒ ❌无热改面（C-09「死开关不许骗人」口径） |
| `_files_incoming_ttl_days` | `7.0`（.env 缺） | **文件网关落盘点寿命清扫（incoming/ 与生成目录）TTL 天数**；≤0＝清扫关闭（席6 全量修复批 2026-10-02）。重启形键不进热改面（C-09 形态）；消费点唯一＝`restricted_runner.sweep_ttl_days_from_config` |

### 控制面 v1 已登记 Config 字段（后端第一切片）

| 字段 | 默认值 | 说明 |
|---|---|---|
| `bot_control_plane_enabled` | `false` | 控制面监听总开关，默认不启用；随 Bot startup/shutdown 装配独立 uvicorn，不共用 webhook。 |
| `bot_control_plane_host` / `bot_control_plane_port` | `127.0.0.1` / `8742` | 嵌入入口只允许 loopback；端口1..65535，拒绝webhook默认端口。监听参数当前需重启。 |
| `bot_control_plane_token_sha256` | 空 | 只读 Bearer 摘要；不可与超管摘要相同。 |
| `bot_control_plane_host_allowlist` | 空 | 可附加 Host 白名单（字符串或列表），不改变监听边界。 |
| `bot_control_plane_features_db` | `data/control_plane_features.sqlite3` | 功能状态、单调图修订和长期变更审计；SQLite CAS事务，已接主Pipeline执行前门禁。 |
| `bot_control_plane_config_db` | `data/control_plane_config.sqlite3` | 按实例隔离配置覆盖/版本/审计；API与RuntimeSettingsStore消费同源；旧JSON昵称/人格/模型等非参数数据仍保留原路径。 |
| `bot_control_plane_events_db` | `data/control_plane_events.sqlite3` | 结构化诊断事件与SSE；不等于已接通NapCat/NoneBot原始控制台。 |
| `bot_control_plane_workspaces_db` | `data/control_plane_workspaces.sqlite3` | 独立短期工作区；24小时原文保留、每分钟清理；不写生产记忆或发送队列。存储路径变更需重启。 |
| `bot_control_plane_platform_db` | `data/control_plane_platform.sqlite3` | 控制面平台注册/连接态存储（并行控制面批次工作树键，按收敛流程补录；经 runtime_paths 重映射）。 |
| `bot_control_plane_actions_db` | `data/control_plane_actions.sqlite3` | 控制面动作审计/待执行存储（并行控制面批次工作树键，按收敛流程补录；经 runtime_paths 重映射）。 |
| `bot_control_plane_features_file` | `data/control_plane_features.json` | 旧功能状态 JSON 的单次导入源；SQLite 已有状态时不覆盖，原 JSON 保留。显式旧工具配置仍可使用 JSON 兼容存储。 |
| `bot_control_plane_super_admin_token_sha256` | 空 | 独立超管 Bearer 的 SHA-256 摘要；空值禁用写操作；与只读摘要相同也禁用写操作。不通过配置 API 返回或修改。 |

**非 Config 键（getattr 防御式读取，未入本表字段域）**：本条已清空。`BOT_LLM_BILLING_ENABLED` 此前属本形态（读点幽灵），2026-09-26 批已在 `config.py` 补上真字段 `bot_llm_billing_enabled`，登记见文末「欠账批次补录」X6 节。控制面监听键已进入上表 Config 字段域。

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

### 6. `BOT_CHAT_MAX_TOKENS`（默认 `65538`）
- **说明**：正常聊天输出上限；命令能力用各自独立限制。
- **合法值**：整数 **0 ≤ x ≤ 65538**（校验器强制）；**0 = 不向 API 传 max_tokens（由模型自行决定）**；负数或 >65538 非法 → error `openai_max_tokens_invalid`。热更同规则（`_max_tokens_converter`）。
- **常见错误**：填负数；误以为 0 是"零输出"（实际是"不设上限"）。

### 7. `BOT_CHAT_TIMEOUT_SECONDS`（默认 `40.0`）
- **说明**：正常模式单模型请求超时（**每一跳**，不是整条回复的预算）；快速模式实际用 min(正常, `BOT_CHAT_FAST_TIMEOUT_SECONDS`)。
- **合法值**：有限数 **>0**（NaN/Infinity/≤0 → error `openai_timeout_seconds_invalid`）。
- **地板 30s**：低于它时思考型模型连首字都等不到，而链上每一跳共用同一钳制值——换渠道不会更快，只会把同一发超时重放 N 遍，结局恒为 `error_kind=timeout` + 失败话术模板（2026-09-27 实弹：两跳全 timeout、`duration_ms=69436.9`）。地板由 `tests/test_chat_timeout_floor.py` 执法，两枚键要一起抬（只抬一枚＝没抬，快速模式取 min）。
- **常见错误**：填 0；超过 `BOT_CHAT_FAILOVER_MAX_SECONDS` 时单次超时会被故障转移窗口压到剩余预算内。整条回复另有 `BOT_REQUEST_BUDGET_SECONDS`（缺省 300s）封顶。

**七键之外的关键配套**：`BOT_API_KEY_*` 五个凭据槽（供注册表 `env:` 引用，NoneBot dotenv 会放进 driver.config，**必须保留在 Config 字段里**，否则真实运行态拿到空 key）；`BOT_MODEL_REGISTRY` 条目内 api_key 支持列表做同模型多密钥转移；`reasoning_effort`（空/off=不发送；qwen/dashscope 转 `enable_thinking`；遇 `unsupported_parameter` 自动去参重试一次）；推理模型空 content 回退 `reasoning_content` 尾部 600 字。

---

## C. 热更机制说明

1. **白名单与转换器**：只有 `SETTABLE_KEYS` 中的键可热更（防止任意配置注入）。**成员数不在本文维护**（真身＝`domains/chat_reply/runtime/settings.py:537 SETTABLE_KEYS`）。旧记「67 键」与本席 2026-09-20 AST 实测（41 枚，含 `BOT_MUSIC_MODE` 这类无 config 字段的运行时专属键）不等，差异成因未取证 ⇒ 以代码为准）。非白名单键 `set_override` 直接拒绝并提示可用键。
2. **可热更键全表**（→ 转换规则，按功能域分组；**本表若与 `SETTABLE_KEYS` 不符，以代码为准并提请 `doc_sync.py` 派生重录**）：

| 键 | 转换规则 |
|---|---|
| **LLM 引擎与模型路由（10）** | |
| `BOT_CHAT_TEMPERATURE` | float，0.0~2.0 |
| `BOT_CHAT_MAX_TOKENS` | int，0..65538（0=不设上限） |
| `BOT_CHAT_FAST_MODE` | bool |
| `BOT_CHAT_FAST_MAX_TOKENS` | int，0..65538（0=不设上限） |
| `BOT_CHAT_MODEL` | 非空且 ≤64 字符 |
| `BOT_CHAT_REASONING_EFFORT` | ``""``/off/low/medium/high/xhigh/max |
| `BOT_TRANSPORT_TIMEOUT_SECONDS` | float，(0,600]，拒绝 NaN/Infinity/空 |
| `BOT_MODEL_SCHEDULE` | JSON 对象字符串（如 `{"23:00-07:00":"luna"}`） |
| `BOT_MODEL_PRIORITY_GROUPS` | JSON 数组字符串（时段优先级分组，存规范化 JSON） |
| `BOT_MODEL_PRICES` | JSON 对象字符串（每模型价格表，单位元/每百万 token，存规范化 JSON） |
| **记忆抽取（4）** | |
| `BOT_MEMORY_EXTRACT_ENABLED` | bool |
| `BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS` | 有限数，(0,3600] 秒 |
| `BOT_MEMORY_EXTRACT_MAX_TOKENS` | int，1..4096 |
| `BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS` | 有限数，(0,3600] 秒 |
| **回复形态（3）** | |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | int，≥200 |
| `BOT_REPLY_DETAIL` | 详细/精简/默认（detail/concise/auto） |
| `BOT_PERSONA_ACTION_BRACKETS` | bool |
| **联网检索（4）** | |
| `BOT_WEB_SEARCH_ENABLED` | bool |
| `BOT_WEB_SEARCH_ADMIN_NOTICE` | bool |
| `BOT_WEB_SEARCH_PROVIDER` | 供应商 id（转小写） |
| `BOT_WEB_SEARCH_FALLBACK_PROVIDERS` | 逗号/分号分隔列表（逐项小写化；空段忽略） |
| **识图 / 语音 / 视频（11）** | |
| `BOT_VISION_ENABLED` | bool |
| `BOT_VISION_MODE` | relay/direct |
| `BOT_ASR_ENABLED` | bool |
| `BOT_VIDEO_UNDERSTANDING_ENABLED` | bool |
| `BOT_VIDEO_MAX_FRAMES` | int，下限钳位 1 |
| `BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE` | bool |
| `BOT_VIDEO_PROGRESS_ACK_ENABLED` | bool |
| `BOT_VIDEO_FUZZY_FOLLOWUP` | bool |
| `BOT_VIDEO_DEEP_ENABLED` | bool |
| `BOT_VIDEO_NATIVE_INPUT` | bool |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool |
| **表情搜索 / 点歌（2）** | |
| `BOT_MEME_SEARCH_ENABLED` | bool（true/1/yes/on/开/是 ↔ false/0/no/off/关/否） |
| `BOT_MUSIC_MODE` | 音频/语音/链接/卡片（audio/voice/link/card；default→card；运行时专属键） |
| **戳一戳（8）** | |
| `BOT_POKE_ENABLED` | bool |
| `BOT_POKE_PRIVATE_COOLDOWN_SECONDS` | 有限数，(0,3600] 秒 |
| `BOT_POKE_GROUP_COOLDOWN_SECONDS` | 有限数，(0,3600] 秒 |
| `BOT_POKE_PROBABILITY` | float，0.0~1.0 |
| `BOT_POKE_REPLY_ENABLED` | bool |
| `BOT_POKE_POKE_BACK` | bool |
| `BOT_POKE_GROUP_TEXT` | 字符串原样 |
| `BOT_POKE_PRIVATE_TEXT` | 字符串原样 |
| **群策略与群摘要（12）** | |
| `BOT_GROUP_BLACK1` / `BOT_GROUP_BLACK2` / `BOT_GROUP_WHITE1` / `BOT_GROUP_WHITE2` | 数字群号列表（逗号/分号/顿号/空白分隔或 JSON 数组；仅数字群号） |
| `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED` | bool |
| `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY` | float，0.0~1.0 |
| `BOT_SHARED_GROUP_CONTEXT_ENABLED` | bool |
| `BOT_GROUP_DIGEST_LIST_MODE` | whitelist/blacklist/off/all |
| `BOT_GROUP_DIGEST_WHITELIST` / `BOT_GROUP_DIGEST_BLACKLIST` | 数字群号列表 |
| `BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS` | 有限数，(0,3600] 秒 |
| `BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR` | int，≥0 |
| **免打扰（6）** | |
| `BOT_QUIET_HOURS_ENABLED` | bool |
| `BOT_QUIET_HOURS_START` / `BOT_QUIET_HOURS_END` | HH:MM（时 0-23、分 0-59） |
| `BOT_QUIET_HOURS_TIMEZONE` | IANA 时区名（非空且校验有效） |
| `BOT_QUIET_HOURS_SESSION_TYPES` | group/private/email（逗号/空白分隔，小写化） |
| `BOT_QUIET_HOURS_BYPASS_ROLES` | 角色名列表（逗号/分号/空白分隔，小写化） |
| **合并转发渲染（4）** | |
| `BOT_RENDER_FORWARD_MIN_NODES` | int，≥0（0=关闭按条数合并规则） |
| `BOT_RENDER_FORWARD_MIN_CHARS` | int，≥0 |
| `BOT_RENDER_FORWARD_MAX_NODES` | int，≥0（0=不限） |
| `BOT_RENDER_FORWARD_NODE_CHARS` | int，下限钳位 200 |
| **群帽与限流豁免（3）** | |
| `BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR` / `BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE` | int，≥0（0=该帽不生效） |
| `BOT_RATE_LIMIT_EMOTION_EXEMPT` | bool |

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

**E1 样例值 ≠ 代码默认**（样例文件给的是本机推荐值，代码默认仍是权威缺省）：`BOT_RUNTIME_DEFAULT_PERSONA`(shorekeeper/default)、`BOT_RUNTIME_DATA_DIR`(../ChatBot_Runtime/data/data)、`BOT_RUNTIME_INSTANCE`(空/default)、`BOT_PERSONA_PROFILE_ID`(shorekeeper/default)、`BOT_PERSONA_DISPLAY_NAME`(守岸人/报存)、`BOT_PERSONA_VERSION`(local/0)、`BOT_TONE_WARMTH`(0.8/0.7)、`BOT_TONE_DIRECTNESS`(0.4/0.5)、`BOT_GROUP_DIGEST_MAX_TURNS`(20/150)、`BOT_RATE_LIMIT_CHAT_SESSION_MAX_REQUESTS`(12/6)、`BOT_RATE_LIMIT_CHAT_SENDER_MAX_REQUESTS`(8/4)、`BOT_RENDER_FORWARD_MIN_CHARS`(0/1500)、`BOT_REPLY_DETAIL`(detail/auto)、四个 `BOT_REPLY_*_CONTEXT_BUDGET`(8192/8192/12288/8192 vs 2048/2560/3072/2048)、`BOT_KNOWLEDGE_CHUNK_CHARS`(600/900)、`BOT_KNOWLEDGE_MAX_CHUNKS`(2/4)、`BOT_KNOWLEDGE_TOP_K`(5/4)、`BOT_EMBEDDING_TIMEOUT_SECONDS`(30/15.0)、`BOT_CHAT_PROVIDER`(openai_compatible/static)、`BOT_CHAT_MODEL`(gpt-5.6-terra/static)、`BOT_CHAT_BASE_URL`(中转站/api.openai.com)、`BOT_CHAT_FAST_CONTEXT_BUDGET`(32768/9600)、`BOT_CHAT_FAST_WEB_MAX_QUERIES`(5/3)、`BOT_DOWNLOAD_PROXY`(7890/直连)、`BOT_COOKIES_FILE`(data/platform_cookies.txt/空)、`BOT_MEME_LIBRARY_VLM_PRESET`(空/deepseek-vision)；另 memory/history/diagnostics/audit/receipts/send_queue/rate_limit 的 db_path 代码默认空（内存/禁用），样例填了 `data/wuwa_*.sqlite3` 等具体文件。

**E2 `.env.example` 未列出（实际生效代码默认）**：`BOT_MUSIC_ANALYTICS_ENABLED/DB_PATH/RETENTION_DAYS`、`BOT_VISION_REPLY_PROBABILITY`、`BOT_SUBSCRIBE_JITTER_RATIO/GLOBAL_CONCURRENCY/PLATFORM_CONCURRENCY/MIN_INTERVAL_SECONDS/LEASE_SECONDS/RETRY_BASE_SECONDS/RETRY_CAP_SECONDS/OUTBOX_INTERVAL_SECONDS`（键名以上列为准）。

**E3 `.env.example` 有而 Config 无**：`MAIL_BOTS`、`TELEGRAM_BOTS`、`TELEGRAM_PROXY`、`TELEGRAM_WEBHOOK_URL`、`MCP_CACHE_TTL/SERVERS/TOOL_TIMEOUT`、`SQLALCHEMY_DATABASE_URL`、`LOCALSTORE_*`——由邮件/Telegram 插件、MCP 插件、可选 ORM、nonebot-plugin-localstore 消费。

**E4 热更层特有**：`BOT_MUSIC_MODE` 只存在于 `SETTABLE_KEYS`（config.py 无字段），未设置时运行时回退 `card`；`.env.example` 的 `BOT_MODEL_REGISTRY` 样例中的 `key_group`/`last_resort` 字段模型路由器**不解析**，仅作人工注释。

---

## F. 热更列复核记账（2026-09-20，CATALOG-FIX 席）

**做了什么**：把本册「热更」列与同句内的可热改叙述按代码**逐键自验**，只改被证伪的，统一成三档标记
（三档定义见本文「0. 通用规则」第 4 条：✅热更／🟡需重启／❌无热改面。**本册没有「使用说明」也没有「档位记号」段**——旧指针指向的是不存在的锚点，已改指实际定义处）。**没有**为省事把证伪项一律降级为「需重启」——
🟡 与 ❌ 按「是否已登记 `RESTART_REQUIRED_KEYS`」分开记账，真 ✅ 与真可热更键条目保持原样（枚数以节内现算为准）。
**本节及图例不写行号**：行号随增删漂移（本席插入图例已使后文整体 +5），检索请用键名或节名。

**判据（每键三问，静态解析、零 import 插件包）**

1. 键名 ∈ `plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py::SETTABLE_KEYS`？ → ✅
2. 否则 ∈ 同文件的 `RESTART_REQUIRED_KEYS`？ → 🟡
3. 两表皆无 → ❌（`set_override` 白名单外直接抛 `ValueError`；再看是否落在合并层
   根 `plugins/bot_unified_runtime/__init__.py::_RUNTIME_HOT_OVERRIDE_FIELDS`（实测条数见当席报告），
   落在其中的即「读侧空转臂」）。

**复跑口径**：AST 抽取上列三个符号 + 逐行比对第 5 列，探针在 `%TEMP%/catalog-fix/probe_c6b.py`（一次性件，不入库）；
`SETTABLE=41 / RESTART=54 / 两表交集=∅ / config.py 字段=633` 为本席实测值。

**改口清单（处数与各节分账以本节下列行现算为准）**
（另有 **6 处同句叙述**一并改口：`BOT_MODEL_SCHEDULE` 的「热更时存 JSON」、`BOT_WEB_SEARCH_PROVIDER` 的「热更时转小写」、`BOT_VIDEO_MAX_FRAMES` 与 `BOT_RENDER_FORWARD_NODE_CHARS` 的「热更时钳位」、`BOT_GROUP_CHAT_AUTO_REPLY_ENABLED/_PROBABILITY` 两行的装配快照与同族两态说明。）

| 位置 | 键 | 改前 | 改后（依据） |
|---|---|---|---|
| 主表（行数以本节为准） | `BOT_MODEL_SCHEDULE`、`BOT_WEB_SEARCH_PROVIDER`、`BOT_WEB_SEARCH_FALLBACK_PROVIDERS`、`BOT_CONTENT_VIDEO_AUTO_SEND`、`BOT_VIDEO_MAX_FRAMES`、`BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE`、`BOT_VIDEO_NATIVE_INPUT`、`BOT_VIDEO_PROGRESS_ACK_ENABLED`、`BOT_VIDEO_FUZZY_FOLLOWUP`、`BOT_VIDEO_DEEP_ENABLED`、`BOT_RENDER_FORWARD_MIN_CHARS`、`BOT_RENDER_FORWARD_MIN_NODES`、`BOT_RENDER_FORWARD_MAX_NODES`、`BOT_RENDER_FORWARD_NODE_CHARS`、`BOT_GROUP_CHAT_AUTO_REPLY_ENABLED`、`BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY`、`BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR`、`BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS`、`BOT_SHARED_GROUP_CONTEXT_ENABLED` | ✅热更 | 🟡需重启（`RESTART_REQUIRED_KEYS` 在列、`SETTABLE_KEYS` 未登记） |
| 主表 | `BOT_GROUP_WELCOME_ENABLED` | ✅热更 | ❌无热改面（两表均未登记） |
| 主表 | `BOT_DAILY_ASSIST_ENABLED`、`BOT_DAILY_ASSIST_PUSH_USER_IDS` | ✅热更 | ❌无热改面（合并表 根 `__init__.py::_RUNTIME_HOT_OVERRIDE_FIELDS` 在列而写拒＝读侧空转） |
| C 节 `_poke_*` 行 | poke 族键组 / `_poke_admin_bypass` | 「除 admin_bypass 外均可热更 ✅」 | 🟡需重启 / ❌无热改面 |
| C 节 `_shared_group_context_enabled` 行 | 同键 | ✅热更（SETTABLE_KEYS） | 🟡需重启 |
| C 节 群摘要名单行 | `_group_digest_list_mode`/`_whitelist`/`_blacklist` | 「运行时 store 可热改」 | 🟡需重启（同族 `_push_enabled`/`_push_time` 为 ❌） |

**未改与已知残余（本席不猜，留给门与生成器）**

- 反向缺口：`BOT_MEMORY_EXTRACT_ENABLED`/`_TIMEOUT_SECONDS`/`_MAX_TOKENS`/`_ERROR_COOLDOWN_SECONDS` 四键
  与 `BOT_CHAT_FAST_MODE`/`_MAX_CANDIDATES`/`_CONTEXT_BUDGET`/`_WEB_MAX_QUERIES`/`_SKIP_WEB_PAGES` 五键**确在 `SETTABLE_KEYS`**，
  但热更列仍空白（欠标，非假标）——按任务边界「只改被证伪的」未动，提请 `doc_sync.py` 派生时一并补齐。
- `BOT_MUSIC_MODE` 同册两行互斥（「音乐能力」节回退 `card+voice+link` vs E4 节回退 `card`）：属**值抄本失真**、不属热更标记面 ⇒ 本席未改，随审计件 §7 R14 落地。
- C 节 `_outbound_gate_max_per_target_per_*` 行已是全册正确的热改文案样板（明写「勿按字面理解成'写了就生效'」并点名装配期 `getattr(裸 config)` 快照）**未动**，作为其余行的写法范式。
- C 节 `_rate_limit_group_max_per_hour`/`_rate_limit_group_max_per_minute`/`_rate_limit_emotion_exempt` 三键实测确在 `SETTABLE_KEYS`，标记为真、**未动**。
- C 节「`_rate_limit_group_hourly…` 之外的新限流键 ⇒ 热改不支持＝架构取舍」与上一行「两键均已入 SETTABLE_KEYS 可热更」并列同表、语义相抵：
  孰真需读 `domains/chat_reply/policy/rate_limit.py` 消费面才能判 ⇒ **保留原文，进未决**（本席不为凑数改口）。

**防再漂（建议，不在本席实现）**：见 `docs/design/link-unification-audit-20260920.md` §8 G-2
（建议件真身已另名落地 = `tests/test_config_hotchange_consistency_gate.py`（2026-09-27 核：在册门 `test_catalog_hot_claims_are_backed_by_settable_list`/`test_catalog_restart_claims_are_not_already_hot`/`test_hot_change_lists_are_disjoint`），原文拟名 `test_config_hot_reclaim_consistency.py` 从未存在；判据=打 ✅ 的键必须 ∈ `SETTABLE_KEYS`，双向负样本自检；
`SETTABLE ∩ RESTART == ∅`；`_RUNTIME_HOT_OVERRIDE_FIELDS − SETTABLE_KEYS` 必须 ⊆ 显式豁免清单）。


## 外部紧急信息聚合（bot.emergency_info，WIRE-B1 波登记 2026-09-21）

| 键 | 类型 | 缺省 | 值域 | | 说明 | 影响 |
|---|---|---|---|---|---|---|
| `BOT_EMERGENCY_INFO_ENABLED` | bool | `False` | true/false | ❌无热改面（`SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` 两表 grep 零 `EMERGENCY` 条目、合并层 `_RUNTIME_HOT_OVERRIDE_FIELDS`（`__init__.py:733-763`）亦未登记 ⇒ `set_override` 拒写） | 紧急信息聚合总闸（装配门腿1） | 关=整链不装配（`__init__.py:5179`）、路由谓词不触发。⚠️旧「装配期快照」只说中一半：路由侧是**每次判定现读 config**（`domains/chat_reply/runtime/base_router.py` 的 `build_emergency_info_source(config)`），冻结的是投递侧。改 `.env` 重启生效 |
| `BOT_EMERGENCY_INFO_SOURCES` | list[str] | `[]` | 源 id 列表，合法值=四个真身 `SOURCE_ID`：`nmc`/`gdacs`/`icl`/`usgs` | ❌无热改面（两表均未登记、合并层未登记） | 允许采集的外部来源名单（装配门腿2） | 空=整链不装配（不猜源）。写 `nmc_alarm` 之类**模块名**不报错但零命中⇒该源永不采集（根装配 2.A 已把未注册 id 点名进日志）。真·装配期快照：`plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py` 烘进 frozen `EmergencyInfoSource`，调度每轮按该快照过滤源 |
| `BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES` | list[str] | `[]` | 源 id 子集（同上四真身） | ❌无热改面（两表均未登记；消费方是装配期烘进快照的 `auto_approve_sources` 字段） | 权威源入库自动过审（用户裁定 D-8(a)） | 名单命中的源入库即 `approved`（`reviewed_by=auto:authoritative_source`），其余仍 `pending` 走人工；空名单=整机制关闭＝逐字节旧行为。✅曾经是真死键（快照不搬、`ReviewGate(store)` 裸构造），WIRE-L2 起经 `build_review_gate` 唯一构造口接线并有端到端证据；合法值同样只认 `SOURCE_ID` 真身，写成模块名会静默不命中 |
| `BOT_EMERGENCY_INFO_POLL_INTERVAL_SECONDS` | int | `300` | >0 秒 | ❌无热改面（⚠️**「建议热改」为假**：值先烘进 frozen 快照（`domains/emergency_info/capabilities/emergency_info.py:124-126`），再在装配期一次性钉进 APScheduler interval job（`__init__.py:9014-9023` `scheduler.add_job(..., "interval", seconds=source.poll_interval_seconds, misfire_grace_time=...)`）；全树无 reschedule/remove 该 job 的面 ⇒ 即便登记白名单写了也不改轮询节奏） | 采集轮询间隔 | 非法值按缺省 300（`_positive_int`）。另被装配期快照复用为新鲜度窗 `max_age=3×间隔`（`__init__.py:8931-8933`）；改 `.env` 重启生效 |
| `BOT_EMERGENCY_INFO_MIN_LEVEL` | str | `P2` | P0..P3（EmergencyLevel 字面） | ❌无热改面（⚠️**「建议热改」为假**：装配期解算成局部闭包变量一次即定（`__init__.py:8934-8938` `min_rank = EmergencyLevel(source.min_level).rank`，`ValueError` → `None`），此后每轮投递只读该闭包旧值（`__init__.py:8995`）；键本身两表均未登记） | 投递最低等级门槛 | 非法值按缺省处理＝不拦档（D-3：不建第二套枚举，快照「只搬运不校验」`domains/emergency_info/capabilities/emergency_info.py:121-123`）。改 `.env` 重启生效 |
| `BOT_EMERGENCY_INFO_QUIET_BREACH_LEVELS` | str | `P0,P1` | P0..P3 逗号分隔（非法 token 由 `_level_tokens` 弃置；全空⇒兜回代码缺省 {P0,P1}） | ❌无热改面（装配期烘进 frozen 快照 `quiet_breach_levels`，`domains/emergency_info/capabilities/emergency_info.py:201-204` 读点；root 传参→`grading.may_breach_quiet_window_intersects_floor` 取交判据） | 静默窗源级穿窗表 | **与族级地板取交、只收窄不放宽**（源表配成 `P0,P1,P2,P3` 也架空不了地板）；缺省覆盖全族地板⇒落键当天行为逐字节不变。改 `.env` 重启生效 |
| `BOT_EMERGENCY_INFO_PUSH_GROUP_WHITELIST` | list[str] | `[]` | 群 id，`*`=显式全群 | ❌无热改面（两表均未登记、合并层未登记） | 群**硬推**腿（可选，不再是装配门） | 2026-09-20 裁定 3.B：装配门缩为 总闸∧有源，本键不再参与判定。名单里的群每轮收全部过 `min_level` 地板的条目、**不受订阅条件约束**；日常按群按条件推送请用群内「紧急信息 订阅 …」（落 `emergency_subscriptions`、每轮现读、当轮生效）。缺省空=这条腿不存在。`*` 只在投递侧按显式全群处理，读侧通配不等于知道有哪些群 |
| `BOT_EMERGENCY_INFO_PUSH_USER_IDS` | list[str] | `[]` | QQ id 列表 | ❌无热改面（两表均未登记、合并层未登记） | 私聊**硬推**腿（可选，不再是装配门） | 同上一条：降级为可选硬推目标，不受订阅过滤。个人级订阅请在私聊里说「紧急信息 订阅 …」（超管/管理员可设，形态与群内一致） |
| `BOT_EMERGENCY_INFO_REVIEWER_IDS` | list[str] | `[]` | QQ id 列表 | ❌无热改面（两表均未登记、合并层未登记 ⇒ 写不进去）。**本键消费形态最特殊**：查询读侧每次调用现场重建快照现读 config（`domains/emergency_info/capabilities/emergency_info.py:364` → `:110`），装配侧的 `review_surface_enabled` 则一次定（`:120`） | 审核人名单（不参与装配门） | 空=审核面关闭：料可入库但永远投不出去（安全缺省态）。⚠️旧「装配期快照」对读侧不成立；若日后登记进 `SETTABLE_KEYS`＋合并层，读侧可近瞬时生效而装配侧仍需重启——不要按整族一刀切标热更 |
| `BOT_EMERGENCY_INFO_KEEP_DAYS` | int | `90` | >0 天 | ❌无热改面（两表均未登记、合并层未登记） | 库保留天数（prune） | 非法值按缺省 90。装配期烘进快照（`domains/emergency_info/capabilities/emergency_info.py:127`），每轮 prune 读的是那个 frozen 字段（`__init__.py:9004` `service.store.prune(keep_days=source.keep_days, ...)`）⇒ 现读形态≠热改面 |
| `BOT_EMERGENCY_INFO_DB_PATH` | str | `data/emergency_info.sqlite3` | 路径（path_fields 重映射进 Runtime，铁律 6；`config.py:1317`） | ❌无热改面（两表均未登记、合并层未登记） | 紧急条目 SQLite 库 | 装配期建库一次即持有连接（`__init__.py:5190`；`domains/emergency_info/sources/store.py:100-107`）。详见 docs/db-owners.md |


## 一致性漂移巡检（sync_drift，S12 救活波登记 2026-09-21）

> 本族七键此前**只存在于消费方**（`domains/ops/sync_drift/service.py` 直接读七个 `Config`
> 上根本不存在的字段）⇒ `extra="ignore"` 下 `.env` 填了也没用，`alert_enabled` 恒 `False`
> ⇒ 巡检器**永不注册**（这是它「代码全绿却零告警」的根因）。S12 波由主会话在 `config.py`
> 落字段、`.env.example` 与本节同步，接线点由 WP10 落根装配。

| 键 | 类型 | 缺省 | 值域 | | 说明 | 影响 |
|---|---|---|---|---|---|---|
| `BOT_SYNC_DRIFT_ALERT_ENABLED` | bool | `False` | true/false | ❌无热改面（两表均未登记；`install()` 装配期读一次即定） | 漂移巡检总闸 | 关=**连 APScheduler job 都不注册**（零开销、零告警）。真值还需 `bot_super_admin_user_ids` 非空与 scheduler 在场，任一缺 → `install()` 返回 skipped 原因不注册。改 `.env` 重启生效 |
| `BOT_SYNC_DRIFT_SURFACES` | list[str] | `[]` | registry 登记表里的 `surface` 真名；空表=扫全部已登记面 | ✅每轮现读（`run_patrol_async` 每轮 `checks_for(...)`） | 本轮要扫的漂移面 | 面名写错**不报错**——它静默不在扫描集里（列现有面：`sync_drift.registered_surfaces()`，2026-09-21 实况 6 面：`persona_source_vs_runtime_copy` / `env_example_vs_config_fields` / `commands_md_vs_help_entries` / `db_owners_vs_config_dbs` / `trigger_words_vs_route_matrix` / `tts_spec_numbers_vs_code`） |
| `BOT_SYNC_DRIFT_INTERVAL_MINUTES` | int | `60` | ≥1（`max(1, ...)` 兜底） | ❌装配期一次钉进 job（`scheduler.add_job` 的 `IntervalTrigger`） | 巡检周期 | 改 `.env` 重启生效；`coalesce=True`+`max_instances=1` ⇒ 上一轮未完不叠跑 |
| `BOT_SYNC_DRIFT_STARTUP_DELAY_SECONDS` | int | `65` | ≥0 | ❌装配期一次 | 首跑延迟 | 让路于启动期装配与 NTP 授时（重启后 ~65s 起算），与提醒/摘要调度器族同口径 |
| `BOT_SYNC_DRIFT_SUPPRESSION_SECONDS` | int | `21600` | >0 秒 | ✅每轮现读（服务壳构造期读，装配期即定 ⇒ 实质重启生效；抑制窗本身进程内滑窗） | 同（面,严重度）告警抑制窗 | 默认 6 小时；抑制计数如实写进巡检结果（`status=suppressed`），不静默吞。抑制器异常时**照常投递**（宁可重复不可漏报） |
| `BOT_SYNC_DRIFT_QQ_BOT_ID` | str | `""` | QQ 号；空串=用 sink 缺省 `"queued-onebot"` | ❌装配期一次 | QQ 侧投递走哪台协议端的发送队列 | 投递复用 `domains/monitor/alerts` 中央件 `build_alert_content_sink`，**不直调 send_queue**（T6 门口径） |
| `BOT_SYNC_DRIFT_MAX_EVIDENCE_LINES` | int | `12` | ≥1 | ✅每轮现读 | 告警正文最多带几行证据 | 只裁展示行数，不裁证据本身；证据全文落 `scan_surface()` 可复算 |


## 记忆/反思 v2 总线与好感度 v7（WP6/WP7 灰度键，S12 波登记 2026-09-21）

> 两族键（数以本节为准），**缺省一律=关闭/旧行为**（灰度用）。热改面本轮**故意不登记** `SETTABLE_KEYS`：
> 只登记白名单而不接 `runtime/settings.py` 的 `_RUNTIME_HOT_OVERRIDE_FIELDS` 合并层 ⇒ 「可热改」是假的
> （本仓已定罪的形态，见本文 F 节热更列复核记账）。实现席证明读路径为「逐调用现读」后，收尾再逐键裁定。

| 键 | 类型 | 缺省 | 值域 | | 说明 | 影响 |
|---|---|---|---|---|---|---|
| `BOT_MEMORY_BUS_ENABLED` | bool | `False` | true/false | 🟡需重启 | 记忆总线总闸 | 关=读写全走旧路径（`reflection_facts` + `memory_entries_v21` 并行现状），逐字节旧行为；开=召回改走统一打分器 |
| `BOT_MEMORY_REFLECTED_WRITE_TARGET` | str | `legacy` | `bus`/`legacy` | ❌本轮未登记热改面 | 反思归纳结果的落点 | 灰度期回退位；非法值按 `legacy`（fail-safe 到旧路径，绝不双写重复记账） |
| `BOT_MEMORY_STRENGTH_K` | float | `3.0` | >0 | ❌同上 | 证据累积→强度的形状参数 | 只影响新总线打分序，不改任何已存行 |
| `BOT_MEMORY_TAU_STABLE_DAYS` | int | `180` | >0 天 | ❌同上 | 稳定类事实半衰 | 分类学由 `decay_class` 列承载，不再靠字符串猜 |
| `BOT_MEMORY_TAU_SEASONAL_DAYS` | int | `45` | >0 天 | ❌同上 | 季节类事实半衰 | 同上 |
| `BOT_MEMORY_TAU_EPISODIC_DAYS` | int | `14` | >0 天 | ❌同上 | 事件类事实半衰 | 同上 |
| `BOT_MEMORY_RELEVANCE_WEIGHTS` | str | `""` | JSON（`w_rel`/`w_str`/`w_rec`/`w_red`） | ❌同上 | 召回打分四权重 | 空或非法 JSON=按代码缺省并**首次点名一次告警**，不静默猜权重 |
| `BOT_MEMORY_PER_CATEGORY_MAX` | int | `1` | ≥0（0=不裁） | ❌同上 | 同类谓词槽位上限（MMR-lite） | 治「三条近重复吃掉三个名额」 |
| `BOT_MEMORY_SEMANTIC_RECALL_ENABLED` | bool | `True` | true/false | ❌本轮未登记热改面 | 语义通道开关 | 关=只走 FTS/词面，向量库缺失时本就自动降级（诚实不装） |
| `BOT_AFFINITY_V7_ENABLED` | bool | `False` | true/false | 🟡需重启 | 好感度 v7 总闸 | 关=v5/v6 逐字节现状；开=分数由潜变量 `z` 经 `tanh` 映射。**存量分数惰性映射不重置**（`z=atanh(score/100)`） |
| `BOT_AFFINITY_BASE_STEP` | float | `0.10` | >0（z 单位） | ❌同上 | 单次互动的基准位移 | ⚠ 这是 z 尺度参数，不是「加几分」；对外文案一律定性、不展示数值（她的裁定） |
| `BOT_AFFINITY_NOVELTY_RATIO` | float | `0.90` | (0,1) | ❌同上 | 跨日新鲜度 EMA 比率 | 治「连发敷衍短句也照涨」 |
| `BOT_AFFINITY_NOVELTY_HALO_DAYS` | int | `21` | >0 天 | ❌同上 | 新鲜度半衰光晕 | 同上 |
| `BOT_AFFINITY_RHYTHM_REFERENCE_TURNS` | int | `8` | >0 轮/日 | ❌同上 | 按人活跃归一的参考轮次 | 治「话痨增速碾压轻度用户」 |
| `BOT_AFFINITY_NEGATIVE_EVENT_CAP_Z` | float | `0.10` | >0 | ❌同上 | 单次负向事件 \|Δz\| 上限 | 护栏：不可被设定/名单架空 |
| `BOT_AFFINITY_DAILY_MOVE_CAP_Z` | float | `0.12` | >0 | ❌同上 | 单日总位移上限 | 同上（修道歉通道不吃此配额，但仍在硬护栏内） |
| `BOT_AFFINITY_FUSE_DAILY_EVENTS` | int | `25` | >0 次 | ❌同上 | 单日事件数熔断 | 超限当日只记不涨，防刷分 |
| `BOT_AFFINITY_REPAIR_GAIN` | float | `1.4` | ≥1 | ❌同上 | 修复（道歉/和解）通道加成 | 与「说好话」不同权重 |
| `BOT_AFFINITY_Z_HARD_BOUND` | float | `0.985` | (0,1) | ❌同上 | tanh 饱和域硬边界 | 越界即钳制 ⇒ score 永不触 ±100，八档边界不再跳变 |
| `BOT_AFFINITY_QUALITY_WEIGHTS` | str | `""` | JSON（w1..w5） | ❌同上 | 质量分五子信号权重 | 空/非法=按代码缺省并点名一次，不静默猜 |
| `BOT_AFFINITY_DECAY_TAU_DAYS` | str | `""` | JSON（stable/seasonal/episodic） | ❌同上 | 衰减时间常数 | 同上 |

## 欠账批次补录（2026-09-23~26 各波落键、本日入册，S-FIX-CATALOG 席 2026-09-27）

> 本节逐枚补录 2026-09-27 清点时欠账的 69 枚 `bot_*` 字段：全部已在 `config.py` 落地、`.env.example` 已列激活键，唯独本目录漏登（覆盖门 `tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields` 红转绿的清偿面）。
> 逐枚「类型/缺省」取自 `config.py` 字段声明现值，「作用」摘自字段注释与生产消费点实证（不凭键名猜语义）；「热更」列按 `domains/chat_reply/runtime/settings.py` 的 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` 两表现读判定（判定方法见 §0 第 4 条）。
> 安全声明沿用头部铁律 3：`BOT_AXONHUB_DB_PASSWORD` 等密钥类键只写占位，本目录从未读取真实 `.env`。

### X1 慢回复先行回执（bot.chat_progress_ack 族，选项 C 波登记）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CHAT_PROGRESS_ACK_ENABLED` | bool | `False` | true/false | 🟡需重启 | 慢回复先行回执总闸（2026-09-23 用户裁定）：真回复仍在跑，先补一句守岸人口吻的等待短句；开启与否按会话走四名单（下方四枚）。装配期读一次，热改当轮不生效——与调度器族同口径（台账 #3 P3） | `domains/chat_reply/runtime/progress_ack.py` |
| `BOT_CHAT_PROGRESS_ACK_DELAY_SECONDS` | float | `15.0` | >0 秒 | 🟡需重启 | 判定"慢"的固定阈值：能力在此时间内出结果就什么都不发，不发第二条、也不撤回（2026-09-23「15 秒内出结果时不发」）。自适应开启时被下方三枚接管 | 同上 |
| `BOT_CHAT_PROGRESS_ACK_COOLDOWN_SECONDS` | float | `60.0` | ≥0 秒 | 🟡需重启 | 同一会话两次回执的最小间隔，防刷屏；**只在回执真发成功时占用额度** | 同上 |
| `BOT_CHAT_PROGRESS_ACK_GROUP_WHITELIST` | list[str] | `[]` | 群 id 列表（id-list 写法） | 🟡需重启 | 群聊白名单：**空 = 群聊整面关闭（绝不猜群）** | 同上 |
| `BOT_CHAT_PROGRESS_ACK_GROUP_BLACKLIST` | list[str] | `[]` | 群 id 列表 | 🟡需重启 | 群聊黑名单：**永远赢**过白名单 | 同上 |
| `BOT_CHAT_PROGRESS_ACK_PRIVATE_WHITELIST` | list[str] | `[]` | QQ id 列表 | 🟡需重启 | 私聊白名单：**空 = 私聊放开**（刻意不对称，同 `BOT_CONTENT_ROUTE_*` 族口径） | 同上 |
| `BOT_CHAT_PROGRESS_ACK_PRIVATE_BLACKLIST` | list[str] | `[]` | QQ id 列表 | 🟡需重启 | 私聊黑名单（最高优先） | 同上 |
| `BOT_CHAT_PROGRESS_ACK_ADAPTIVE_ENABLED` | bool | `True` | true/false | 🟡需重启 | 回执阈值随网关当下快慢浮动（2026-09-25 裁定：中转站一慢就必触发、误报太多）。开=按「链上各跳 EWMA 延迟 × 倍率」抬高质量阈值并夹在 floor~cap 之间；**关=逐字节回到固定 `..._DELAY_SECONDS`** | 同上 |
| `BOT_CHAT_PROGRESS_ACK_DELAY_FLOOR_SECONDS` | float | `50.0` | >0 秒（样例 30 ⚠️） | 🟡需重启 | 自适应下限：网关很快时也不早于此值发回执。沿革 15→30（2026-09-26）→**50**（2026-09-29 需求项 6 落进用户口径区间 45~60：现网实测 p50=35.7s、p75=68.9s，地板 30 时过半正常轮会白说一句）。缺省常量唯一真身=同文件 `DEFAULT_ACK_DELAY_FLOOR_SECONDS`，本键与它由 `tests/test_progress_ack_thresholds.py` AST parity 锁现场比对 | 同上 |
| `BOT_CHAT_PROGRESS_ACK_DELAY_CAP_SECONDS` | float | `60.0` | >0 秒（样例 90 ⚠️） | 🟡需重启 | 自适应上限：网关再慢也不能让用户无限期等不到一句提示。2026-09-29 由 90 收到 **60**（同一裁定要求「结果落在 45~60 区间」，上限 90 会把慢网关的阈值推出区间） | 同上 |
| `BOT_CHAT_PROGRESS_ACK_LATENCY_MULTIPLIER` | float | `3.0` | >1 倍率（样例 2.0 ⚠️） | 🟡需重启 | 阈值 = 链上**最慢一跳**的 EWMA × 此倍率（取最慢一跳而非当值一跳：回执压的是整轮，检索+联网+LLM 任何一路慢都可能是本轮走的那条）。2026-09-29 由 2.0 抬到 **3.0**：2.0 档下现网慢跳 13.7s 派生 27.4s 恒被地板压住、自适应腿形同虚设 | 同上 |

### X2 折句窗口（bot.chat_message_coalescing 族，登记 2026-09-25 裁定波）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CHAT_MESSAGE_COALESCING_ENABLED` | bool | `True` | true/false | 🟡需重启 | 折句窗口（2026-09-25 用户裁定）：一句话按逗号拆成两三条发时合成一轮、只回一次。只有「本身像半句话」的消息才会等下一条，**完整句子零额外延迟** | `domains/chat_reply/runtime/message_coalescing.py` |
| `BOT_CHAT_MESSAGE_COALESCING_MAX_HOLD_SECONDS` | float | `8.0` | >0 秒 | 🟡需重启 | 封顶等待：有人逐字蹦也必须在这时开口，绝不允许一直不回。⚠ 同族曾有「停口窗口」`_quiet_seconds` 一枚**已于 2026-09-27 乙案退役删除**（唯一真身=`message_merge.MERGE_WINDOW_SECONDS` 3s、装配层每轮无条件覆盖，该键系「在册永不算数」的死口）——勿再找那枚键 | 同上 |
| `BOT_CHAT_MESSAGE_COALESCING_MAX_MESSAGES` | int | `6` | ≥1 条 | 🟡需重启 | 一轮合成最多收编几条消息（越限即封口输出） | 同上（`getattr` 缺省回 `defaults.max_messages`） |
| `BOT_CHAT_MESSAGE_COALESCING_MAX_CHARS` | int | `1500` | ≥1 字 | 🟡需重启 | 一轮合成文本的字符上限（越限即封口输出） | 同上 |

### X3 限流补回（chat_rate_limit_redrive 族，2026-09-25 裁定第 2 项）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CHAT_RATE_LIMIT_REDRIVE_ENABLED` | bool | `True` | true/false | 🟡需重启 | 被限流挡下的「明确找我说话」消息改为期后补回，不再静默吞掉（裁定第 2 项：冷却与条数帽把消息吃掉了；「可以延后，不可以丢弃」） | `domains/chat_reply/policy/rate_limit.py` + `policy/redrive_ledger.py`（同人多条被拦消息排开回位） |
| `BOT_CHAT_RATE_LIMIT_REDRIVE_MAX_WAIT_SECONDS` | float | `270.0` | >0 秒（样例 180 ⚠️） | 🟡需重启 | 最多延后多久补回；还要等更久的**不弃**，改排到最近可用槽（2026-09-28）。270 = 6×点名间隔缺省 45s：连发 6 条 @bot 排得下（上一档 180 只容 5 条，第 6 条起仍被静默吞）；180 = 4×间隔那档的历史理由仍在（连发 5 条装得下） | 同上 |
| `BOT_CHAT_RATE_LIMIT_REDRIVE_MAX_ATTEMPTS` | int | `3` | ≥1 次（样例 1 ⚠️） | 🟡需重启 | 一条消息最多补回几次，防重放循环。2026-09-28 由 1 抬到 **3**：单次补回仍被限流挡住的形态（同人多条挤同一间隔）此前直接丢弃；上限 3 足够覆盖 6 条连发且不放大刷屏 | 同上 |

### X4 群聊节奏层（rate_limit_group_pacing 族，2026-09-24 T7 波）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_RATE_LIMIT_GROUP_PACING_TOKENS_PER_HOUR` | int | `60` | ≥0；0=整层关 | 🟡需重启 | 令牌桶每小时补充 x 句（治「开局瞬间打光后整段静默」：旧滑动小时窗 2 分钟打光 30 句、随后静默 58 分钟；节奏层把最坏静默压到 3600/x 秒）。0 = 整个节奏层不生效（含分钟帽与最小间隔） | `domains/chat_reply/policy/rate_limit.py`；经装配期 settings_provider 每轮现读**本 Config 值**，但键未进热改合并层（根 `__init__` 冻结、禁插行）⇒ 改 `.env` + 重启 |
| `BOT_RATE_LIMIT_GROUP_PACING_BURST_CAPACITY` | int | `5` | ≥1 | 🟡需重启 | 桶容量 B = 开局可连发句数（"绝不瞬间打光"的红线；T6 建议值 5 起步） | 同上 |
| `BOT_RATE_LIMIT_GROUP_PACING_MAX_PER_MINUTE` | int | `3` | ≥0；0=不设 | 🟡需重启 | 节奏层分钟外骨架（她自己的口径"每分钟 3 句"） | 同上 |
| `BOT_RATE_LIMIT_GROUP_PACING_MIN_INTERVAL_SECONDS` | int | `20` | ≥0 秒；0=不设 | 🟡需重启 | 群非点名两句之间的最小间隔。情绪/好感豁免**只免这类间隔**，不免桶与帽 | 同上 |
| `BOT_RATE_LIMIT_GROUP_VISION_MIN_INTERVAL_SECONDS` | int | `120` | ≥0 秒；0=不设 | 🟡需重启 | 图片/表情包/视频类**自己的**独立最小间隔：与文字并入同一个桶，另加这道更宽的间隔（2026-09-24 裁定采纳） | 同上（资源归属登记见 `domains/core/capability_resource_ownership.py`） |

### X5 亲密档 L1 自动腿（content_route 族，2026-09-24 裁定 R1 A）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CONTENT_ROUTE_L1_AUTO_ENABLED` | bool | `True` | true/false | 🟡需重启 | 亲密档浅档（L1）自动腿总闸：好感度达标的用户自动进浅档——**只给关系语气，绝不换模型**（换模型只由显式开/管理员钉/内容信号触发，判据唯一住 `content_route._MODEL_SWITCH_SOURCES`） | `domains/chat_reply/runtime/content_route.py` 的 `_knobs()`（每次判定现读传入的 config）；键未进合并层 ⇒ 需重启 |
| `BOT_CONTENT_ROUTE_L1_AUTO_MIN_TIER` | int | `1` | 好感档号 | 🟡需重启 | 自动腿门槛：好感度**档号**达到该档及以上才自动进浅档。档号真身住 `character/affinity.py` 的 `_ATTITUDE_TIERS`（取数口 `attitude_tiers()`），本目录不抄档位表；缺省对应「亲近」（id=+1），调高=更严、调到最低档号=对全体建档用户开放、负得离谱等于关（另有上一行总闸） | 同上 |

### X6 LLM 计费账本与网关归因（B5 M1 / B1，2026-09-25 批）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_LLM_BILLING_ENABLED` | bool | `False` | true/false | 🟡需重启 | 计费账本总开关。此前只以 `_ENABLED_CONFIG_KEY` 常量名住在 ledger.py、Config 无字段 ⇒ `extra="ignore"` 把 `.env` 值静默丢掉（「写在 .env 却永远关不上/打不开」，读点幽灵登记项已销账）。关 = 与历史行为逐字节一致（不建库、不写行） | `domains/chat_reply/llm_engine/ledger.py`（`ledger_enabled`）+ `llm_engine/model_router.py` |
| `BOT_AXONHUB_ATTRIBUTION_ENABLED` | bool | `False` | true/false | 🟡需重启 | 网关归因（B1）：bot 侧注册表只指向 AxonHub、看不见网关内部实际选了哪条上游渠道，也拿不到缓存创建 token 与四项分项价。开=由**账本写线程**按响应体 id（== requests.external_id，实测关联键）去网关库只读反查并回填；刻意不放回复路径（要等网络，挂回复前=拿延迟换报表） | `domains/chat_reply/llm_engine/axonhub_attribution.py` |
| `BOT_AXONHUB_DB_HOST` | str | `""` | 主机名/IP | 🟡需重启 | 只读账号连接面。host/user 任一空 ⇒ `from_config` 直接返回 None（fail-closed，不存在"看着开了其实没连"） | 同上 |
| `BOT_AXONHUB_DB_PORT` | int | `5432` | 端口 | 🟡需重启 | 网关库端口 | 同上 |
| `BOT_AXONHUB_DB_DATABASE` | str | `axonhub` | 库名 | 🟡需重启 | 网关库库名 | 同上 |
| `BOT_AXONHUB_DB_USER` | str | `""` | 只读角色名 | 🟡需重启 | 必须用只读角色（本机已建 `axonhub_ro`，仅五张表 SELECT）：账本侧对网关库零写需求，给写权限=把故障半径扩到她的生产网关 | 同上 |
| `BOT_AXONHUB_DB_PASSWORD` | str | `""` | 密钥（占位 `env:`） | 🟡需重启 | 只读账号口令。**真实口令只在 `.env`（铁律 3），代码零硬编码**；本目录只写占位 | 同上 |
| `BOT_AXONHUB_ATTRIBUTION_TIMEOUT_SECONDS` | float | `3.0` | >0 秒 | 🟡需重启 | 单批反查超时：到点就放弃这一批、标 unavailable，绝不拖慢落库 | 同上 |

### X7 表情包子系统（goal-12 波，2026-09-25）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_MEME_LIBRARY_VLM_FALLBACK_FIRST_PRESET` | bool | `True` | true/false | 🟡需重启 | 打标 VLM 预设名落空时退到注册表里真实存在的第一组。现网实况：`.env` 把 `BOT_MEME_LIBRARY_VLM_PRESET` 写成空串、注册表只有 myvlm 一组，旧实现两侧都取不到 ⇒ 打标静默不跑 ⇒ 库里的图全没标签（表现是「选图像随机」）。**关=逐字节回旧行为**；注册表真为空时两档都不打标（不猜端点） | `domains/meme/sources/meme_library_listener.py` |
| `BOT_MEME_SHOREKEEPER_ABSORB_ENABLED` | bool | `True` | true/false | 🟡需重启 | 自动吸收「主体是守岸人」的贴纸：VLM 主体判定命中中央别名（`personas/shorekeeper/aliases.txt`）⇒ 标本命、吃本命加权、默认豁免按龄裁剪。**不放宽任何收库门**（群黑白名单与总闸照旧在调用方） | `sources/meme_library_listener.py` + `sources/shorekeeper_absorb.py` |
| `BOT_MEME_SHOREKEEPER_PROTECT_FROM_PRUNE` | bool | `True` | true/false | 🟡需重启 | 本命贴纸豁免「按天」裁剪（`BOT_MEME_LIBRARY_MAX_AGE_DAYS` 那一刀）；**按量上限（max_files）仍然生效**，否则全标本命就能让库无界增长 | `sources/meme_library_listener.py` |
| `BOT_MEME_RELEVANCE_MIN` | float | `0.35` | 0~1 | 🟡需重启 | 选图相关性地板：比的是**合格分**（库权重 × 主题相关度），不是排序分——被拦的只有库自判「不算表情/高危」（权重 0.25/0.0）与离题且不熟（0.0）两类；心情降权、口味与本命加成只影响先后顺序，**不参与地板**（否则「低落×中性档」=0.175 会被吃掉，软偏置成硬开关）。0.35 落在中性档 0.5 之下、非表情 0.25 之下 | `domains/meme/capabilities/meme_library.py` |
| `BOT_MEME_STICKER_SCOPE_MODE` | str | `global` | `global`/`session` | 🟡需重启 | 反重复作用域口径：`global`=本机发过即不再发（缺省，钉「同一张绝不发两次」）；`session`=同时再按会话/群各记一本账（并集判定，比 global 更严，不会更松） | 同上 |
| `BOT_MEME_LIBRARY_MIN_FILE_KB` | int | `100` | ≥0；0=关 | 🟡需重启 | B1 收库守卫：字节下限（KB），「把所有表情贴纸存下来」收窄为真贴纸——1KB 图标/缩略图拒收（进 `skipped` 的 `guard_*` 代号账） | `sources/meme_library_listener.py` |
| `BOT_MEME_LIBRARY_MIN_SIDE` | int | `400` | ≥0；0=关（样例 300 ⚠️） | 🟡需重启 | B1 收库守卫：像素短边下限（与 `BOT_RANDPIC_MIN_SIDE` 语义一致、两把闸各自独立——表情包段与本地原图分布本不同）；PIL 解不开按坏件拒（`guard_undecodable`）；文件头魔数验真不待本键即在 `_download_once` 常开 | 同上 + `domains/media/image_guard.py` |

### X8 戳一戳扩臂与主动戳人（P14 波，2026-09-25 裁定「被戳→任意一臂」）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_POKE_EXTRA_ARMS_ENABLED` | bool | `False` | true/false | 🟡需重启 | 臂矩阵扩臂闸：False=mix 轮换池停在旧三臂（fixed/llm/meme）⇒ 与 P14 之前逐字节同形；True=池扩到六臂（+voice/randpic/poke）。`BOT_POKE_REPLY_MODE` 显式指名任一臂**不受本档影响** | `domains/chat_reply/capabilities/poke.py` |
| `BOT_POKE_FOLLOW_ENABLED` | bool | `False` | true/false | 🟡需重启 | 跟戳总闸：用户 A 在群里戳用户 B 时 bot 有概率跟着戳 B。缺省关 | 根 `__init__.py`（P14 派发腿，`getattr(merged_config, ...)` 现读） |
| `BOT_POKE_FOLLOW_PROBABILITY` | float | `0.2` | 0~1 | 🟡需重启 | 跟戳概率（getattr 兜底同值） | 同上 |
| `BOT_POKE_FOLLOW_COOLDOWN_SECONDS` | float | `120.0` | ≥0 秒 | 🟡需重启 | 跟戳独立冷却（QQ 戳很便宜但极刷屏，与回戳**分账不共用门**） | 同上 |
| `BOT_POKE_FOLLOW_MAX_PER_HOUR` | int | `4` | ≥0 | 🟡需重启 | 跟戳每小时上限 | 同上 |
| `BOT_POKE_AFTER_REPLY_ENABLED` | bool | `False` | true/false | 🟡需重启 | 回复后/主动发言后戳人总闸：bot 把话说完（含群内主动接话、入群欢迎这类「bot 先开口」）后按概率戳一下对方。两触发共用本族旋钮、各自独立掷骰。安静时间与 blocked 名单是硬门，拨开开关也越不过 | 同上 |
| `BOT_POKE_AFTER_REPLY_PROBABILITY` | float | `0.15` | 0~1 | 🟡需重启 | 回后戳概率（getattr 兜底同值） | 同上 |
| `BOT_POKE_AFTER_REPLY_COOLDOWN_SECONDS` | float | `300.0` | ≥0 秒 | 🟡需重启 | 回后戳独立冷却 | 同上 |
| `BOT_POKE_AFTER_REPLY_MAX_PER_HOUR` | int | `3` | ≥0 | 🟡需重启 | 回后戳每小时上限 | 同上 |

### X9 随机发图派发（P14 波）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_RANDPIC_DISPATCH_ENABLED` | bool | `False` | true/false | 🟡需重启 | 随机发图主动派发总闸（2026-09-25 三触发「回复完用户消息/用户戳 bot/特定指令」中本批加的「回复完主动发图」腿；戳 bot 腿走 `BOT_POKE_REPLY_MODE=randpic` 臂，同一取图口同一本窗账）。缺省全关=只在用户开口要图时发；**开态也过安静时间/blocked 两道硬门** | 根 `__init__.py`（P14 派发腿） |
| `BOT_RANDPIC_DISPATCH_PROBABILITY` | float | `0.1` | 0~1 | 🟡需重启 | 派发概率门（getattr 兜底同值） | 同上 |
| `BOT_RANDPIC_DISPATCH_COOLDOWN_SECONDS` | float | `600.0` | ≥0 秒 | 🟡需重启 | 派发独立冷却 | 同上 |
| `BOT_RANDPIC_DISPATCH_MAX_PER_HOUR` | int | `2` | ≥0 | 🟡需重启 | 派发每小时上限 | 同上 |
| `BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS` | float | `0.0` | ≥0 秒；0=关 | 🟡需重启 | 窗内不重发同一张（按会话记账）。0 = 关 = 旧行为逐字节同形（纯随机、可重样） | `domains/meme/capabilities/randpic.py` |
| `BOT_RANDPIC_MIN_FILE_KB` | int | `100` | ≥0；0=关 | 🟡需重启 | B1 池子守卫：单张字节下限（KB），低于不进候选；任一守卫键 > 0 时同时启用文件头魔数验真（假 .png/HTML 改名件计入 `images_bad_magic`） | 同上（`_min_bytes_for`）+ `domains/media/image_guard.py` |
| `BOT_RANDPIC_MIN_SIDE` | int | `400` | ≥0；0=关（样例 300 ⚠️） | 🟡需重启 | B1 池子守卫：像素短边下限（与 `BOT_MEME_LIBRARY_MIN_SIDE` 语义一致、两把闸各自独立）；代码注释点名该缺省出自现网图库普查（拒的是 QQ 预览/缩略图＝用户所称「糊」那一段），PIL 只解图头；解不开按坏件记 | 同上（`_min_side_for`）+ `domains/media/image_guard.py` |

### X10 creation 对接点 provider 选择器（中央调度收编波 P5/S09 §7）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CREATION_IMAGE_PROVIDER` | str | `""` | provider id；空=未配 | 🟡需重启 | creation 绘画对接点的 provider 选择器：空 ⇒ 域内 `reserved_provider.provider_configured` 判 False ⇒ 诚实 UNAVAILABLE。⚠ **登记两键只是把"根本没这个键"改成"有键、待填、待接工厂"，不等于绘画可用**——适配器工厂尚未存在（填了值仍诚实 UNAVAILABLE，探测面转为 DEGRADED）。装配期快照（描述符/探针建表时读） | `domains/creation/reserved_provider.py` + `domains/creation/image/engine_provider.py`/`provider_factory.py` + `domains/core/capability_manifest.py` |
| `BOT_CREATION_TTS_PROVIDER` | str | `""` | provider id；空=未配 | 🟡需重启 | 同上，creation 语音腿 | `domains/creation/reserved_provider.py` + `domains/creation/tts/engine_provider.py` + `runtime/capability_protocols.py` |

### X11 日程记录与智能代答（裁定第 20 项，2026-09-26 S-SCHEDULE-20 波）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SCHEDULE_STATUS_REPLY_ENABLED` | bool | `False` | true/false | 🟡需重启 | 代答腿总闸：关着时「她在干嘛」一类问句完全不进日程路由，零行为变更；开着也只按分级表投影公开条目（**隐私判定在出站前，不靠模型自觉**） | `domains/schedule/capabilities/schedule_board.py`（能力/路由侧 `getattr` 现读装配期快照 config，未进合并层 ⇒ 热 set 不可达，C-09 口径） |
| `BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED` | bool | `False` | true/false | 🟡需重启 | 宽口径自然捕捉闸：关着只认「日程/课表」显式命令与导入；开着才把「明天8点有课」这类带时间+活动词的短句顺手记进她的日程板（缺省隐私） | 同上 |

### X12 联网检索行为阈值（web_search 族）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD` | float | `0.6` | 0.0~1.0（越界装载期拒） | ✅热更（`SETTABLE_KEYS`，`_web_ratio_converter`） | 行为阈值（区别于只记录不决策的遥测）：本地知识可答的门槛，**低于它才补搜**。总闸仍是 `BOT_WEB_SEARCH_ENABLED`；本键只在联网已开时决定 FALLBACK（本地世界观优先）一类问题是否补搜；置信度=查询主题词被知识库覆盖的比例（S13 真身）。缺省 0.60 偏高，须用遥测影子期数据校准 | `domains/chat_reply/capabilities/chat.py` |
| `BOT_WEB_SEARCH_CONFIDENCE_FLOOR` | float | `0.2` | 0.0~1.0（越界装载期拒） | ✅热更（同上） | 硬底线安全阀：本地知识近乎空白时**无条件补搜一次**，独立于可被调高的 knowledge_threshold，防止误判成「不用搜」 | 同上 |
| `BOT_WEB_SEARCH_KEYFREE_FALLBACK_ENABLED` | bool | `False` | true/false | 🟡需重启 | 链尾免 key 兜底（DuckDuckGo → Bing）：有 key 的供应商全部失败/未配置时才接管，永不抢在前面。开启会让检索面依赖公开搜索引擎 HTML，结果质量与配额不可控。**只在装配期读一次**（链构造即固化），改动需重启 | `domains/core/search/web_search.py` |

### X13 TTS 长回复拆条（语音 H 波后续）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_TTS_AUTO_REPLY_SPLIT_MAX_CHARS` | int | `0` | ≥0（`Field(ge=0)`）；0=不拆条 | ❌无热改面（`SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` 两表均未登记） | 长回复拆条的每段音频文本上限：0=不拆条=缺省逐字节现状；超过此值的可朗读文本按句末标点切成多块、逐块合成、多段音频随同一条回复发出。参考量级：60 秒 ≈ 150~180 字（守岸人语速偏慢 speed 0.85，2026-09-23 按听感校准） | `domains/media/tts/result_transform.py`（manifest/ownership 登记见 `domains/core/capability_manifest.py`/`capability_resource_ownership.py`） |

### X14 文件写盘口（需求 16(2)，2026-09-26 S-FILES-LAND 收编波）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_FILES_WRITE_ENABLED` | bool | `True` | true/false | 🟡需重启 | 写盘口总闸（今日在岗）。六枚缺省值**逐字节等于** restricted_runner 内建缺省（8MiB/60/120、白名单回落 export、总闸今日在岗）⇒ 现网零变更；「保守」体现在口本身：白名单外什么都不许写（fail-closed）、可执行扩展名永远拦。缺省常量与运行器同名常量的等值由 `tests/test_files_write_side_assembly.py` 现场对账（改其一必看到另一处红） | `domains/files/capabilities/file_exchange.py::write_policy_from_config`（根 matcher 交装配期快照 config，六枚未进合并层 ⇒ 不做「看着能热改」，C-09 形态） |
| `BOT_FILES_WRITE_ALLOWED_DIRS` | list[str] | `[]` | 目录列表 | 🟡需重启 | 可写目录白名单；**空=回落 `BOT_DOWNLOAD_DIR/export`**（=今日导出腿唯一落点，现网零变更） | 同上 |
| `BOT_FILES_WRITE_MAX_BYTES` | int | `8388608`（8 MiB） | >0 字节 | 🟡需重启 | 单文件写入字节上限 | 同上（`WriteLimits.max_file_bytes`） |
| `BOT_FILES_WRITE_DAILY_CREATE` | int | `60` | ≥0 | 🟡需重启 | 每日新建文件件数额度 | 同上（`WriteLimits.daily_create_limit`） |
| `BOT_FILES_WRITE_DAILY_REPLACE` | int | `120` | ≥0 | 🟡需重启 | 每日覆盖（替换）件数额度 | 同上（`WriteLimits.daily_replace_limit`） |
| `BOT_FILES_READ_CONFINED_MAX_BYTES` | int | `8388608`（8 MiB） | >0 字节 | 🟡需重启 | 回读侧单文件限额：与写侧同根策略，只把 max_file_bytes 换成这一枚（`_read_policy_from_config`） | 同上 |

### X15 出站闸自动到期（开闸 A 案第二腿，2026-09-25 裁定「开，A+B」）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_OUTBOUND_GATE_ENABLED_UNTIL` | str | `""` | ISO-8601 字面量 | 🟡需重启（本族键不在 `_RUNTIME_HOT_OVERRIDE_FIELDS`，登记见 settings.py RESTART 表） | 中央出站防风暴闸的**自动到期时刻**：到期即等同 `BOT_OUTBOUND_GATE_ENABLED=false` 并响亮留痕，不需要谁记得回来手工关掉（「临时停用要自动到期、不留人工回滚债」）。缺省空=无到期 ⇒ 有效开启逐字节等于 `BOT_OUTBOUND_GATE_ENABLED` 本身，新键落地零现网读数变更 | 判据唯一真身 `domains/transport/sender/outbound_gate.py::effective_gate_enabled`（读不到/解不出=宁关不猜）；解析真身 `domains/core/moment_parsing.py::parse_moment` |

### X16 SAFE-EXEC 书面同意执法门（裁定第 18 项，2026-09-26）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_SAFETYEXEC_ENABLED` | bool | `True` | true/false | 🟡需重启（护栏**不可被一条命令热关**） | 危险参数设置书面同意执法门总闸。缺省 True＝执法开——「危险的参数设置需要经过超级管理员的书面同意」；关它必须改 `.env` + 重启 | `domains/core/safety_exec/consent.py::ConsentPolicy.from_config`（装配期快照）+ `safety_exec/settings_gate.py`（关 ⇒ 该件整体旁路、行为与接线前逐字节一致）；装载链 `runtime/settings.py::configure_safety_gate` |

### X17 协议端版本目录（诊断卡要素⑤）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_PROTOCOL_CLIENT_DIR` | str | `""` | 路径 | 🟡需重启 | 协议端（SnowLuma）安装目录：诊断卡要素⑤「协议端版本」读它自己的 `package.json` 的 version 字段（OneBot V11 的 `get_version` 本仓从未调用过，而卡片在渲染线程里同步组装，不能为一个版本号往主循环发异步 RPC）。空=走内置探测路径（`error_report._protocol_client_version_label`）；读不到就在卡上写「未取到」，**绝不拿 nonebot-adapter-onebot 的版本顶替** | `domains/ops/monitor/error_report.py` |

### X18 控制面文件读取根白名单（F-1 根修，2026-09-28 SEAT-FIX-ATK-CP）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_CONTROL_PLANE_FILES_ROOTS` | list[str]/str | `""` | 逗号分隔目录列表（绝对或相对 cwd） | 🟡需重启（装配期快照字段，合并表未登记该键，登记见 settings.py RESTART 表） | `/api/v1/files/read` 的读取根白名单（F-1：旧实现以进程 cwd 为根 ⇒ 只读令牌可枚举整棵工作树）。缺省空 ⇒ 端点 503 `files_config_unavailable` 诚实拒绝，**绝不回落 cwd**；只应登记真正的产物/素材目录。`data/`、`logs/`、`webui/node_modules/` 子树与 `.log`/`.env*` 形态为常驻敏感禁区，即便误落登记根内也一律拒读（403 `file_read_denied`，可归因）；路径成员两侧 `resolve()` 后按段判成员，短名/`..` 穿越不逃逸 | `control_plane/api/platform.py::read_file`（getattr 字面直读）→ `control_plane/file_access.py::FileReadGateway`（F-3 收编：守卫唯一执法体）；锁在 `tests/test_control_plane_files_read_scope.py` |

### X19 bot 自有表情私库（STICKER-POOL 波，2026-09-29）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_STICKER_DIR` | str | `data/bot_stickers/shorekeeper` | 目录路径（`data/` 前缀自动折进运行数据根） | 🟡需重启（每次现读调用方交来的装配期快照；换目录里的**图**不用重启，扫池 30s TTL） | bot **自己**的贴纸登记根。与 `BOT_MEME_LIBRARY_DIR`（别人发到群里的图被收进库）分家：本目录只读、不落 SQLite、不打标、不进权重账。目录不存在 ⇒ 诚实不发并记 `dirs_missing`，**绝不自建目录**（先例 randpic） | `domains/meme/sources/sticker_packs.py::configured_sticker_dir`（**唯一**读路径，消费方不得自己 walk）；重映射名册 `config.PATH_REMAPPED_FIELDS` |
| `BOT_STICKER_ENABLED` | bool | `True` | true/false | 🟡需重启 | 发送侧总闸：P3 情绪时刻 / 戳一戳 / 偷表情 三条腿共用一枚。关掉⇒`pick_sticker` 直接回 `None`（读路径照旧可查库存）。与 feature gate `bot.plugin.sticker_packs` **两道门各管一侧**（那枚是控制面「这条能力在不在产品里」，本枚是业务「今天要不要发」），任一关就不发 | 同上 `sticker_send_enabled`；闸口在 `pick_sticker` 首行 |
| `BOT_STICKER_RECURSIVE` | bool | `True` | true/false | 🟡需重启 | `os.walk` 递归整棵树 vs 只扫登记根那一层（重解析点两侧都不进树：Windows junction 的 `islink` 为假，判据真身 `path_gate.reparse_point`）。值与目录一同进扫池缓存键 | 同上 `sticker_is_recursive`；剪枝名单懒引 `randpic._should_prune_dir`（禁第二份名单） |
| `BOT_STICKER_NO_REPEAT_WINDOW_SECONDS` | float | `1800.0` | ≥0 秒；0=关（纯随机、可重样） | 🟡需重启 | 窗内不重发同一张贴纸（按会话记账，群账键由窗账自己收敛成 `group_{G}`）。同图判据=内容 SHA-256，摘要唯一真身 `domains/media/digest.py::media_digest_file`（经 `randpic.image_identity`，本件不抄第二份）。整库都在窗内：指令路退「最久没发」并**明确记成复发**，主动路不发（宁可不发也不刷屏） | 同上 `sticker_window_seconds`；窗口实现复用 `randpic.RecentImageWindow`（`try_claim` 原子占坑，禁第二本窗账） |
| `BOT_STICKER_PRIVATE_SUBDIR` | str | `私藏` | 子目录**名**（非路径，`BOT_STICKER_DIR` 之下那一层；空串＝整件关闭） | 🟡需重启（每次选图现读的是调用方交来的装配期快照；合并表 `_RUNTIME_HOT_OVERRIDE_FIELDS` 未登记本键；`settings.py::RESTART_REQUIRED_KEYS` 在册） | S4 好感档联动的锁定目标名：命中该名的子目录在「探查」与「最久没发复发」两条路上**整条剔除**——档位不够就当没有这批图，绝不猜档。改这里＝换锁哪一格 | `domains/meme/capabilities/meme_library.py::_locked_sticker_subdirs`（**唯一**判据口，消费方不得自己拼）→ `sticker_packs.py::pick_sticker` 的 `locked_subdirs` 形参（`relative_to(登记根)` 逐段比名）；**不是**落点字段，故不进 `config.PATH_REMAPPED_FIELDS` |
| `BOT_STICKER_PRIVATE_MIN_TIER` | int | `7` | 好感**档号**下限（现读快照的 `tier`，值大＝更亲近）；档位表真身 `domains/chat_reply/character/affinity.py`，本行不抄；读不出/非数⇒按 `7` 处理 | 🟡需重启（同上一行判据：装配期快照＋合并表未登记＋`RESTART_REQUIRED_KEYS` 在册） | 解锁私藏格所需的最低好感档。快照缺席（没建过档）或取不出 `tier` ⇒ **fail-closed** 按未解锁算，与「档位低」同处置；调高＝更严（关这件另有上一行的空串口） | 同上 `_locked_sticker_subdirs`（档位取 `__init__.py::_poke_affinity_snapshot` 交来的快照 `tier`）；执法面在 `sticker_packs.pick_sticker`；回归锁 `tests/test_sticker_persona_album.py` |

### X20 网络巡检（代理链根修波，2026-09-30）

| 键 | 类型 | 缺省 | 值域 | 热更 | 作用 | 消费点/依赖 |
|---|---|---|---|---|---|---|
| `BOT_NETWORK_PATROL_ENABLED` | bool | `True` | true/false | 🟡需重启（巡检任务在装配期登记，热改当轮不生效） | 巡检总闸：关掉⇒整条巡检不排班，Clash 探活与上游双腿都不跑（差分带外告警随之静默）。与出站同意门无关，不经 `safety_exec` | `domains/ops/network_patrol.py`（执行体）；装配点 `__init__.py::_register_network_patrol_scheduler`（**唯一**排班处，禁第二处起巡） |
| `BOT_NETWORK_PATROL_INTERVAL_MINUTES` | int | `15` | >0 分钟 | 🟡需重启 | 巡检周期。首轮只建基线**不告警**；此后只在「变坏边界」走带外告警（TG/邮件），恢复只记账不刷屏 | 同上；落盘 `<runtime>/data/network_patrol.jsonl`，体积上限见该件 `_PATROL_JSONL_MAX_BYTES`（超限滚 `.1`，防无界增长） |
| `BOT_NETWORK_PATROL_DOMAINS` | str | `""` | 逗号分隔域名；空⇒用内置名册（真身 `network_patrol.PATROL_TARGETS_DEFAULT`，枚数以该件现值为准） | 🟡需重启 | 覆盖巡检目标集，用于临时增删观测域名而不改代码 | 同上 |
| `BOT_NETWORK_PATROL_DOWN_THRESHOLD` | int | `5` | >0 | 🟡需重启 | 连续失败去抖阈值（2026-10-02 裁定「连续五次炸了才提醒」）：目标（域名×腿）连续失败达此数才报 down 进告警差分，中途任何一次成功清零；恢复翻转不延迟，且只对报过 down 的目标发恢复行 | 真身 `domains/ops/network_patrol.py::DownDebounce`；差分仍走 `state_delta`（喂去抖稳态）；推送文案 10-02 起自带失败分型（`classify_leg_failure`：refused 族＝本机 Clash 不在家、EOF/SSL 族＝节点抖动、直连腿＝上游不可达） |


## DB 备份腿（db_backup，四面落键 2026-10-02，#68★）

真身 `domains/ops/db_backup.py::load_policy`（消费点 :201-224，每轮现读装配期快照 config）；七枚全进 `RESTART_REQUIRED_KEYS`（热 set 不改判据）。缺省＝现网哑面不变（`ENABLED=false`）。开启后把 Runtime 数据根每枚 `*.sqlite3` 用 sqlite3 在线备份 API 打一致快照、落仓库外备份区（缺省＝运行数据根同级 `backups/sqlite/`），覆盖绝不自动、删旧必须点名（工单 `patches/DBK-DBBACKUP-ENVKEYS-20261002.md`）。批注：字段落定后 db_backup.py:203 的 env 直读腿恒短路＝预期语义收窄，非缺陷。

| 键 | 类型 | 缺省 | 形态 | 热更列 | 语义 | 备注 |
|---|---|---|---|---|---|---|
| `BOT_DB_BACKUP_ENABLED` | bool | `False` | 0/1 | 🟡需重启 | 备份总闸：关＝哑面（现网态） | 每库 `*.sqlite3` 一致快照＋旁车 manifest |
| `BOT_DB_BACKUP_DIR` | str | `""` | 绝对路径；空⇒缺省 `backups/sqlite/` | 🟡需重启 | 备份区根；**必须在仓库外**，仓库内落点当场抛 | 登记根经 PATH_REMAPPED_FIELDS 折进运行数据根 |
| `BOT_DB_BACKUP_KEEP_LAST` | int | `7` | 1-64 | 🟡需重启 | 每库保留副本数 | 删旧必须按保留清单逐枚点名，禁递归 |
| `BOT_DB_BACKUP_SIZE_CEILING_BYTES` | int | `67108864` | 1 KiB-2 GiB | 🟡需重启 | 单库尺寸上界：超界库整片排除（防把巨型向量库拷爆） | 缺省 64 MiB 落在真空档（实测 5.7 MB 与 908 MB 之间） |
| `BOT_DB_BACKUP_MAX_FOOTPRINT_BYTES` | int | `4294967296` | 1 MiB-512 GiB | 🟡需重启 | 备份区总量上界 | 超界按保留序淘汰 |
| `BOT_DB_BACKUP_MIN_FREE_BYTES` | int | `21474836480` | 0-1 TiB | 🟡需重启 | 开跑前同卷剩余空间下限：不足不开火 | 缺省 20 GiB（基线普查同卷剩 111 GB） |
| `BOT_DB_BACKUP_STALE_AFTER_HOURS` | int | `24` | 1-720 | 🟡需重启 | 副本过期时限（小时） | 超龄在体检报告点名，不自动删 |
