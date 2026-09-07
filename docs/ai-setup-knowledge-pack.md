# ChatBot 框架 · AI 搭建与配置知识包

> **这份文档是什么**：把整个框架的密码/凭据说明、插件结构、设置与配置说明、LLM 引擎接入（模型、密钥、路由）、可查询参数的范围/类型/关系、对话框指令与案例，整合成**一份可以整体喂给 AI 的知识包**。AI 读完整份即可帮你完成搭建与配置。
>
> **怎么喂**：机器人知识库的入库文档是说明书体 `docs/ai-kb-operations-manual.md`（已列入 BOT_KNOWLEDGE_FILES，待审阅+同步）；本文件与配套的 `docs/config-catalog-full.md`（296 键完整目录）是给人和 AI 编码助手看的速查表。配合 §14 的对话指令模板使用。
> **怎么用对话框指令**：机器人运行时，在 QQ 对话框按 §5 输入指令；标注「管理员」的指令只有管理员账号能触发（见 §3）。
>
> 安全约定：本文档遵守仓库规则——**真实密钥、Cookie、Token 一律不入文档**，密钥统一写占位符（`<real_api_key>`、`env:变量名`）。

---

## 1. 框架一页总览

| 项 | 内容 |
|---|---|
| 形态 | NoneBot2 QQ 机器人，OneBot V11 协议，NapCat 作为协议端 |
| 人格 | 守岸人（鸣潮），昵称 岸宝/守岸人，源码 `personas/shorekeeper/` |
| 统一运行时 | 单插件 `plugins/bot_unified_runtime/`，内部按层分包：capabilities（能力）/ runtime（流水线）/ policy（策略）/ character（人格记忆）/ llm（引擎路由）/ sources（数据源）/ sender（发送）/ audit（审计）/ output（卡片渲染） |
| 源码区 | `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`（AI 工作区，唯一可改区） |
| 运行数据 | `ChatBot_Runtime\data\`（向量库、记忆、日志、下载、NoneBot data）——**不在源码区** |
| 虚拟环境 | `ChatBot_Runtime\venv\`（由 `scripts/dev.ps1` 自动使用） |
| 统一入口 | 所有开发/验证命令走 `scripts\dev.ps1 -Task <task>` |
| 配置层 | `.env` + `.env.prod`（真实值，不提交）+ `.env.example`（样例与注释）；`config.py` 统一解析，`data/...` 相对路径自动重定向到 Runtime |
| 热更层 | `runtime/settings.py` 的 `SETTABLE_KEYS`（22 键）+ `data/runtime_settings.json` 覆盖文件，用 `/bot runtime set` 即时生效 |

能力分层一览（`capabilities/`）：chat（对话主链）、content_parser（21+ 平台链接解析）、download、weather、wiki、epic、music、meme、meme_library、subscribe_v2（订阅推送）、today_history、memory、file_exchange、auto_send、echo（帮助/状态）、debug（诊断）、runtime_admin（运行时管理）、runtime_logs。

---

## 2. 目录与数据地图

### 2.1 三个顶层目录

```text
ChatBot\
├─ ChatBot\          生产源码 = 当前 AI 工作区（bot.py、plugins/、personas/、docs/、scripts/、tests/）
├─ ChatBot_Runtime\  运行数据：data\、venv\、cache\、card_render_assets\、config\
└─ ChatBot_Archive\  历史归档压缩包（AI 不扫描）
```

### 2.2 运行数据落点（机器人如何引用）

机器人**不靠读 Markdown** 找数据，生效入口是：`.env`/`.env.prod` → `config.py` 的路径解析 → `bot.py` 初始化 → `scripts/dev.ps1` 固定工作目录。

| 数据 | 落点（Runtime\data 下） | 相关配置键 |
|---|---|---|
| 向量知识库 | `knowledge_embeddings.sqlite3` + `knowledge_faiss.index` | `BOT_KNOWLEDGE_DB_PATH` |
| 长期记忆 | `wuwa_memory.sqlite3` | `BOT_MEMORY_DB_PATH` |
| 对话历史 | `wuwa_history.sqlite3` | `BOT_HISTORY_DB_PATH` |
| 审计/诊断/回执/发送队列 | `wuwa_audit.sqlite3` / `wuwa_diagnostics.sqlite3` / `wuwa_receipts.sqlite3` / `wuwa_send_queue.sqlite3` | 对应 `BOT_*_DB_PATH` |
| 解析历史 | `parse_history.sqlite3` | `BOT_PARSE_HISTORY_DB_PATH` |
| 订阅 | `subscriptions.sqlite3`（旧库备份 `subscriptions_old.sqlite3`，禁止覆盖） | `BOT_SUBSCRIBE_DB_PATH` |
| 「历史上的今天」知识库 | `today_history_kb\`（events/days JSON + `md\th-*.md` 12 个月度知识文件，已入 `BOT_KNOWLEDGE_FILES`） | `BOT_TODAY_HISTORY_*` |
| 崩溃与主日志 | `crash.log`、`faulthandler.log`、`logs\nonebot.out.log / nonebot.err.log`（重启轮转 .old） | — |
| 热更覆盖 | `runtime_settings.json` | `BOT_RUNTIME_SETTINGS_FILE` |
| Cookie | `platform_cookies.txt` | `BOT_COOKIES_FILE` |
| 下载/卡片/表情库 | `downloads\` `cards\` `meme_library\` | `BOT_DOWNLOAD_DIR` 等 |
| NoneBot 第三方数据 | `data\nonebot\`、`config\`、`cache\nonebot\` | `LOCALSTORE_*_DIR`（必须 `LOCALSTORE_USE_CWD=false`） |

关键机制：配置里写 `data/xxx` 的路径会被 `Config._resolve_runtime_data_paths()` 自动重定向到 `BOT_RUNTIME_DATA_DIR`（= `../ChatBot_Runtime/data`），所以**不要**把数据改回源码目录。

---

## 3. 权限体系：为什么有些指令普通账户触发不了

角色模型（`policy/roles.py`）：每条来信按发送者 ID 解析出角色，优先级 user < trusted < enterprise < admin（blocked 直接拉黑）。

| 角色 | 来源配置键（JSON 数组） | 说明 |
|---|---|---|
| admin | `BOT_ADMIN_USER_IDS`（QQ 号）、`BOT_TELEGRAM_ADMIN_USER_IDS`（TG user id） | 管理员，可用全部指令、绕过免打扰/限流（`BOT_QUIET_HOURS_BYPASS_ROLES`、`BOT_RATE_LIMIT_BYPASS_ROLES` 默认 `["admin"]`） |
| trusted | `BOT_TRUSTED_USER_IDS` | 受信任用户 |
| enterprise | `BOT_ENTERPRISE_USER_IDS` | 企业/扩展角色 |
| blocked | `BOT_BLOCKED_USER_IDS` | 黑名单 |

**把自己设为管理员（两步）**：

1. 编辑源码根目录 `.env`：`BOT_ADMIN_USER_IDS=["你的QQ号"]`（多人可写 JSON 数组或分号/逗号分隔；Telegram 侧填 `BOT_TELEGRAM_ADMIN_USER_IDS=["你的TG_user_id"]`）。
2. 重启机器人生效。注意：`BOT_ADMIN_USER_IDS` **不在热更白名单**，不能 `/bot runtime set` 在线改；**本插件不读 NoneBot 的 `SUPERUSERS`**（写了也不生效）。

验证：发 `/bot roles` 或 `/bot recent`，能返回数据即 admin 已命中。

**权限判定细节**（`policy/roles.py` + 各能力层）：角色叠加式（user/trusted/enterprise/admin/blocked，名单互不互斥）；能力层再判 `"admin" in actor_roles`；文件收发调试只认 QQ 管理名单。

普通账户触发管理员指令时的回执（原话）：

| 指令组 | 回执 |
|---|---|
| `/bot receipt/audit/recent/queue/roles/persona/pause/resume/history clear/context/config/readiness/dialogue/llm/setup llm` | `只有管理员可以查看运行时排障记录。` |
| `/bot runtime …`、`/bot model …`、`/bot alert check` | `该命令只允许管理员使用。` |
| `/bot logs …` | `只有管理员才能查询运行时日志。` |
| `/bot search` | `只有管理员才能使用联网检索调试命令。` |
| `/bot reply`（含查询） | `只有管理员才能调整回复详略。` |
| `/bot group` | `只有管理员才能调整群聊回复策略。` |
| `点歌模式`（含查询） | `只有管理员才能修改点歌输出模式。` |
| 文件上传调试 / `文件 <格式> <主题>` | 非管理员**静默忽略**（规则不触发） |
| `/mail`（QQ 端 / TG 非管理员） | `邮件控制命令仅允许从 Telegram 管理端执行。` / `你没有邮件控制权限。` |

`/bot 帮助` 总览对普通账户隐藏管理员条目（`_PUBLIC_HELP_TOPICS` 只公开 10 个子功能主题，见 §5.3）——这就是之前说"这个功能只能对管理员开放，普通账户无法触发"的原因。

---

## 4. 引擎接入（LLM）：模型、密钥与路由

### 4.1 七必配键（对话主引擎，OpenAI 兼容）

| 键 | 说明 | 合法取值/范围 | 当前样例 |
|---|---|---|---|
| `BOT_CHAT_PROVIDER` | 供应商类型 | `openai_compatible`（真实模型）/ `static`（本地占位） | `openai_compatible` |
| `BOT_CHAT_MODEL` | 对话模型名 | 供应商提供的模型字符串，不能用占位符 | `gpt-5.6-terra` |
| `BOT_CHAT_API_KEY` | API 密钥（永不展示/回显） | 真实密钥或 `env:变量名` 引用 | `<real_api_key>` |
| `BOT_CHAT_BASE_URL` | OpenAI 兼容接口地址 | `http(s)://` 开头，一般以 `/v1` 结尾 | `https://newapi.qianqianye.com/v1` |
| `BOT_CHAT_TEMPERATURE` | 采样温度 | 0.0 – 2.0 | 0.7 |
| `BOT_CHAT_MAX_TOKENS` | 单次回复输出上限 | ≥0 整数（0=不设上限） | 4096 |
| `BOT_CHAT_TIMEOUT_SECONDS` | 请求超时 | 正数秒 | 30 |

在对话框输入 **`/bot setup llm`**（管理员）可直接看到这七项的中文说明、取值范围与当前值（密钥不展示）；**`/bot llm`** 做一次真实连接诊断。

### 4.2 多供应商注册表与故障转移

- `BOT_MODEL_REGISTRY`：JSON 对象，每项含 `model` / `base_url` / `api_key`（**必须用 `env:BOT_API_KEY_*` 引用，绝不写明文**）/ `group` / `key_group` / `tags`（思考强度档位）/ `effort`（可选覆盖）/ `priority` / `last_resort`（`key_group`/`last_resort` 仅供人工标注，路由器实际只按 `priority` 排序）。
- `priority`：全局尝试顺序，整数 1-999，**越小越优先**；前一个失败自动切下一个；HCN 等保底项放最后（`last_resort: true`）。
- `tags`（2026-09 改版）= **思考强度档位**，按模型名家族划分：DeepSeek/GLM/Kimi/MiniMax = `low,high,max`；GPT/Grok = `low,medium,high,xhigh`；Gemini（含 c-gemini）= `low,medium,high`。默认思考强度 = 家族最高档（deepseek/glm/kimi=max，gpt/grok=xhigh，gemini=high）；`vision`/`multimodal`/`vlm` 仍允许 direct 图片直传。
- `effort`：条目级思考强度覆盖（`off`=该模型不发送；省略=家族默认最高档）；请求时按 **条目 effort > 全局 `BOT_CHAT_REASONING_EFFORT` > 家族默认最高档** 发送 `reasoning_effort`（接口不支持时自动去参重试）。复杂任务（≥300 字或教程/分析等关键词）会把来自全局/家族默认的档位临时升到家族最高档。
- 密钥槽位：`BOT_API_KEY_QIANQIANYE / _NIGHT / AIPRC / UMI_GROUP1 / UMI_GROUP2 / HCN / DEEPSEEK_OFFICIAL / DEEPSEEK_QIAN / ZHIPU`。
- `BOT_MODEL_AUTO_ROUTE=true`：自动选型（按时段分组/priority 顺序）。
- `BOT_MODEL_PRESETS`：短名映射（如 `terra`/`luna`）。
- `BOT_MODEL_SCHEDULE`：分时段自动切换**单个模型**，JSON 如 `{"23:00-07:00":"luna"}`，支持跨零点，窗口外回到自动选型（与下面的分组互不影响）。
- `BOT_MODEL_PRIORITY_GROUPS`：**时段优先级分组（峰谷顺序）**，JSON 数组：`[{"name":"工作日高峰","days":[1,2,3,4,5],"windows":[["09:00","12:00"],["14:00","18:00"]],"order":[模型id...]},{"name":"非高峰","order":[...]}]`。`days`=ISO 周编号（1=周一…7=周日，缺省=每天）；`windows` 缺省=全天；两者都缺省=兜底组；按列表顺序取**第一个命中**的组，命中组按 `order` 排序；每条消息实时判定（`BOT_TIMEZONE`），热更立即生效；只影响自动路由，手动 `set` 不受影响。
- `BOT_MODEL_PRICES`：每模型价格（元/每百万 token），如 `{"deepseek-v4-pro":{"input":4.0,"output":16.0}}`；成本按**调用时刻**的价格记账，调价不影响历史账单（峰谷差价天然正确）；未配置价格的模型不计费。
- `BOT_CHAT_FAST_*`：快速模式预算（上下文 32768、max_tokens 4096、超时 30s、候选上限 0=不限、`BOT_CHAT_FAILOVER_MAX_SECONDS=45` 故障转移总时限）。
- `BOT_CHAT_REASONING_EFFORT`：留空=各模型家族默认最高档；off=不发送；可选 low/medium/high/xhigh/max。
- 用量监控：`BOT_USAGE_MONITOR_ENABLED`（默认 true）、`BOT_USAGE_ALERT_OUTPUT_TOKENS=5000000`、`BOT_USAGE_ALERT_INPUT_TOKENS=50000000`、`BOT_USAGE_ALERT_DAILY_COST_YUAN=10.0`、`BOT_USAGE_REPORT_HOURS=13,18,23`、`BOT_USAGE_REPORT_STATE_FILE=data/usage_report_state.json`（详见 §4.5）。

### 4.3 引擎管理指令（管理员，改动即时生效、无需重启）

```text
/bot llm                          诊断当前 provider/model/key 并做一次短调用（不改配置）
/bot model list                   全部模型、思考强度档位、当前时段分组与故障转移顺序
/bot model set <id|auto>          切换当前模型；auto=按时段分组/priority 顺序自动选型
/bot model add <id> model=<模型名> base_url=<接口> key=<密钥|env:变量> [tags=档位] [effort=档位] [group=<分组>] [priority=<n>]
/bot model update <id> model=... base_url=... key=... tags=... effort=... group=... priority=...   （可只写要改的项，可覆盖 .env 同名条目）
/bot model priority <id> <n>      只改故障转移顺序
/bot model effort <id> <off|low|medium|high|xhigh|max|default>   单模型思考强度；default=清除覆盖
/bot model think <off|low|medium|high|xhigh|max|留空>   全局思考强度；留空=各模型家族默认最高档
/bot model price <模型名> input=<元/1M> output=<元/1M>   设置价格（热更）；不带价格参数=清除
/bot model usage [today|YYYY-MM-DD]   每日用量账单（输入/缓存命中/缓存创建/输出/费用，按模型分组）
/bot model search <on|off>        热切换联网搜索
/bot model remove <id>            删除自定义模型（.env 来源条目不可删，只能 update 覆盖）
/bot model vision list|add|update|priority|remove|mode <relay|direct>    图片识别模型管理
/bot model reset                  清除手动指定，回到自动选型
```

注意事项（来自内置帮助）：`key=` 不会被回显；等号两边不要加空格；`base_url` 必须以 `/v1` 结尾。
脱敏探测脚本：`scripts/probe_llm_providers.py`（每模型一次探测，`--max-tokens` 1-4096 默认 32，不改配置）。

### 4.4 故障转移队列：加入/移出/启用/禁用的准确语义（读自 `llm/model_router.py`）

**队列怎么排（自动选型）**：
- 候选 = `BOT_MODEL_REGISTRY` 全部条目 + 运行时新增条目，**排除 tags 含 `manual` 的条目**——预设名、以及注册表在场时的主配置模型（`BOT_CHAT_MODEL`）都被打上 `manual` 标签：只接受手动指定，不参与自动排队。
- 顺序：`BOT_MODEL_PRIORITY_GROUPS` 命中的组按组内 `order` 排（组外模型按原 `priority` 追加在后）；未命中任何组则按 `priority` 升序（同值按 id）。标签不再是 fast/strong 分桶——思考深度由 effort 档位体系负责。
- 快速模式额外把候选截断为前 `BOT_CHAT_FAST_MAX_CANDIDATES` 个（0=不限）；整体转移受 `BOT_CHAT_FAILOVER_MAX_SECONDS=45` 和请求级总预算双重限制。
- 每个候选依次尝试它的**每个密钥**（`api_key` 支持列表 = 模型内多密钥转移）；缺 key 的候选直接跳过（`config_missing`）。
- 管理员 `/bot model set <id>` 手动指定后：先试该模型，失败仍按上述顺序转移其余候选。

**操作对照表**：

| 想做什么 | 怎么做 |
|---|---|
| 接入新模型 | `/bot model add <id> model=<模型名> base_url=<接口> key=<密钥\|env:变量> [tags=档位] [priority=<n>]` |
| 加入故障转移队列 | 上面 add 完成**即自动入队**（tags 不含 manual 且配了 key）；改动即时生效，无需重启（条目存 `runtime_settings_<实例>.json`） |
| 调整队列顺序（临时） | `/bot model priority <id> <n>`（n 1-999，越小越先被调用） |
| 峰谷时段整体调序 | `/bot runtime set BOT_MODEL_PRIORITY_GROUPS '<JSON 数组>'`（热更，立即生效；见 §4.2） |
| 移出队列但保留手动可选 | `/bot model update <id> tags=manual` —— 退出自动队列，仍可 `/bot model set <id>` 手动使用 |
| 恢复参与自动队列 | `/bot model update <id> tags=low,high,max`（改回该模型家族的档位列表） |
| 彻底删除 | `/bot model remove <id>`（`.env` 来源条目不可删，只能 `update` 覆盖其参数） |
| 禁用 / 启用 | **没有独立开关**：禁用 = `tags=manual` 或 `remove`；启用 = 恢复 tags 或重新 add |
| 查看当前队列 | `/bot model list`（当前模型 + 当前时段分组 + 各模型 effort 档位 + 转移顺序） |

### 4.5 用量监控、账单与提醒（2026-09 新增）

- **记账链路**：每次成功调用把 输入/输出/缓存命中/缓存创建 token 与按调用时刻价格算出的费用（毫厘）写进运行事件日志（`transport_receipt` 行）；`/bot model usage` 与定时报告都从它聚合。
- **`/bot model usage [today|YYYY-MM-DD]`**：当日（或指定日）账单——按模型分组的 输入/缓存命中/缓存创建/输出 token、调用次数、费用与当日合计；未配置价格的调用单独标注。
- **实时阈值提醒**（每 60 秒巡检当日数据，每项每天只提醒一次，推送给全部管理员）：
  - 单模型当日输出 token > `BOT_USAGE_ALERT_OUTPUT_TOKENS`（默认 500 万）；
  - 单模型当日输入 token > `BOT_USAGE_ALERT_INPUT_TOKENS`（默认 5000 万）；
  - 当日实际账单 > `BOT_USAGE_ALERT_DAILY_COST_YUAN`（默认 10 元）→ 立即发送 Mica 云母质感账单报告卡 + 提醒（含各模型金额明细）。
- **定时报告**（北京时间 `BOT_USAGE_REPORT_HOURS=13,18,23` 点整）：统计**自上个报告时间点至今**的总花费（金额 + token，含分模型明细）；**13:00 报告额外附过去 24 小时总花费**。报告时间点持久化在 `BOT_USAGE_REPORT_STATE_FILE`，重启不丢。渲染可用时报告附卡片图片，失败回退纯文本。
- 推送通道：`runtime/alerts.py` 管理员预警管线（QQ 私聊，走统一 SendRequest→审计，不绕过审计）。

---

## 5. 对话框指令总表

> 前缀：私聊/群里都用 `/bot`（`BOT_RUNTIME_ADMIN_PREFIX=/bot`，群内 `BOT_RUNTIME_GROUP_COMMAND_PREFIX=/bot`）；角色昵称也能触发（`守岸人/岸宝 <命令>`，斜杠可省略）；`/bot 帮助` 或 `/岸宝帮助` 查看内置帮助。
> 权限标注：🅰=仅管理员；⚪=所有人可用。

### 5.1 系统与诊断（`/bot …`）

| 指令 | 功能 | 权限 | 参数与范围 |
|---|---|---|---|
| `/bot status` | 运行状态摘要 | ⚪ | 无 |
| `/bot`（或未知子命令） | 帮助总览（管理员显示更多主题） | ⚪ | 无；输出图片卡 |
| `/bot help <主题>` / `/bot 帮助 <主题>` | 帮助详情 | ⚪ | 主题见 §5.3；管理员另见全部主题 |
| `/bot why [id]` | 解释最近一次回复的决策与错误 | ⚪* | id 可选（request_id/debug_id，省略=最近一次） |
| `/bot parse [数量]` | 最近解析历史 | ⚪* | 数量 1-100，默认 10 |
| `/bot memory add <内容> [--sensitivity=<级别>]` / `list` / `delete <fact_id>` | 长期记忆管理（按发送者+会话隔离） | ⚪* | 内容 ≤1200 字 |
| `/bot route <文本>` / `/bot routes` | 查看文本命中的路由 / 全部路由表 | ⚪ | 文本必填 |
| `/bot receipt <id>` | 查询发送回执 | 🅰 | id 必填 |
| `/bot audit <request_id>` | 查询审计事件 | 🅰 | request_id 必填 |
| `/bot recent [数量]` | 最近排障+回执+审计摘要 | 🅰 | 数量 1-20，默认 5 |
| `/bot queue` | 发送队列计数 | 🅰 | 无 |
| `/bot context [文本]` | 上下文/prompt 构成诊断 | 🅰 | 文本可选（默认"你好，守岸人。"） |
| `/bot dialogue [文本]` | 本地跑一轮对话诊断 | 🅰 | 不改线上状态 |
| `/bot setup llm` | LLM 接入检查卡（七必配键，含取值范围） | 🅰 | 无，不写 .env |
| `/bot config` | 配置体检（脱敏） | 🅰 | 无 |
| `/bot readiness` | 环境/配置/上下文/对话链路聚合就绪状态 | 🅰 | 无 |
| `/bot roles` | 角色数量摘要（不含具体 ID） | 🅰 | 无 |
| `/bot persona` | 人格材料自检（强度/语气/边界） | 🅰 | 无 |
| `/bot history clear` | 清空本会话最近对话 | 🅰 | 必须两个字 `history clear` |
| `/bot llm` | LLM 连接诊断（一次短调用，不改配置） | 🅰 | 无 |
| `/bot logs [级别] [数量]` | 运行时事件日志 | 🅰 | 级别 debug/info/warning/error（默认 info）；数量 1-200（默认 50）；先级别后数量 |
| `/bot search <问题>` | 联网检索链路验证 | 🅰 | 问题必填 |
| `/bot pause` / `/bot resume` | 软暂停/恢复回复 | 🅰 | 无 |

⚪=所有人；⚪*=代码未校验管理员、帮助页归入管理员分类；🅰=仅管理员（普通账户回执见 §3）。

### 5.2 运行时管理（全部仅管理员）

| 指令 | 功能 | 参数与示例 |
|---|---|---|
| `/bot runtime set <KEY> <VALUE>` | 写热更覆盖（持久化，白名单=§7 的 22 键） | `/bot runtime set BOT_VISION_ENABLED true`；可加 `--instance <名称>` |
| `/bot runtime get <KEY>` | 读参数（标注覆盖值或 .env 默认） | `/bot runtime get BOT_MUSIC_MODE` |
| `/bot runtime list` / `reset [KEY]` | 列出全部覆盖项 / 清除覆盖（省略=全部） | — |
| `/bot runtime instance list` | 列出已创建的实例设置文件 | — |
| `/bot runtime nickname add/remove/list <昵称>` | 动态昵称管理（立即生效，参与昵称命令） | `/bot runtime nickname add 小岸` |
| `/bot runtime persona list` / `switch <id\|default>` / `probability <id> <0-1>` | 人格切换与概率（`auto`/`概率`=回自动） | `/bot runtime persona switch default` |
| `/bot model list` / `set <id\|auto>` / `add …` / `update …` / `priority <id> <n>` / `remove <id>` / `reset` | 模型与供应商管理（详见 §4.3） | `.env` 来源条目不可删，只能 update 覆盖 |
| `/bot model think <off\|low\|medium\|high>` | 推理思考强度 | 别名 思考/推理 |
| `/bot model search <on\|off>` | 热切换联网搜索 | 别名 搜索/联网 |
| `/bot model usage [today\|YYYY-MM-DD]` | Token 用量按模型分组 | 别名 用量/token |
| `/bot model vision list/add/update/priority/remove/mode <relay\|direct>` | 图片识别模型管理与模式 | `/bot model vision mode direct` |
| `/bot reply <详细\|精简\|默认>`（无参=查当前档位） | 回复详略（持久化） | 别名：科普/详尽=详细，简洁=精简，自动=默认 |
| `/bot group list` / `add <档位> <群号…>` / `del\|set …` / `clear <档位>` | 群回复策略四档 | 档位 black1/black2/white1/white2（或 黑1/白2 等变体）；动作别名 加/删/设/清/查 等 |
| `/bot alert check [--probe]` | 凭据（Cookie）健康检查 | `--probe` 追加在线探测（401/403=需重登） |

### 5.3 功能操作（普通账户可用）

| 指令 | 功能 | 参数与说明 |
|---|---|---|
| `/订阅 add <链接\|platform:kind:id> [到本群\|私聊我] [--digest]`；`订阅 list/remove/pause/resume/check/status`（=`/bot subscribe`；动作别名 添加/删除/列表/暂停/恢复/检查/状态） | 平台新内容推送 | 支持 bilibili（UP主/直播间/番剧/收藏夹/合集）、小红书创作者；`--digest`=只进每日 20:00 日报；v2 后端所有人均可操作 |
| `点歌 <歌名>` / `music` / `song` | 多平台依次搜歌发歌 | 输出形态按 `点歌模式`（🅰，见 §5.2） |
| `表情 列表` / `表情 <key> <文字…>`（多段用 ｜）/ `表情帮助` | 本地 meme-generator 生成文字表情 | 模板词含 meme/memes 等英文与繁体变体 |
| `偷表情 [关键词\|私聊]` / `表情库统计` | 表情库随机发图（20 秒冷却）/ 库存统计 | 需 `BOT_MEME_LIBRARY_ENABLED=true`；写「私聊」转私聊 |
| `天气 <城市>` / `查天气 <城市>` / `支持区县 <省>` | 中国气象局 NMC 天气 | 同名城市用 `省-市`（如 河北-大城） |
| `维基 <词条>` / `wiki <词条>` | MediaWiki 百科 | — |
| `epic`（及 epic free / 免费游戏 等变体） | Epic 本周免费游戏 | 裸词结尾 |
| `历史上的今天 [设置 HH:MM\|状态\|取消]` | 当天历史 + 每日定时推送 | 24 小时制；短别名 `/历史`、`/今日历史` 必须带斜杠 |
| `/bot download <链接>` | yt-dlp 下载视频/音频 | B站/油管/推特/小红书/抖音；单文件 ≤1GB 超限自动降画质；**必须带 `/bot` 前缀**（裸写 `下载 <链接>` 会落入闲聊） |
| 直接发 http(s) 链接 | 平台内容解析信息卡 | B站/抖音/小红书/油管/推特/微博/Lofter/Pixiv/小黑盒/米游社/森空岛/库街区/allcpp/米画师/快手/acfun/steam/音乐平台；群内失败静默 |
| `报存 给 <收件人> 发消息\|邮件，主题…，内容…` | 自动发送草稿**预览**（不实发） | 必须以 `报存 ` 开头；收件人可用 、/， 分隔 |
| `守岸人/岸宝 <动词> [参数]` | 昵称别名命令（斜杠可省略） | 可直接执行：帮助/状态/查询/为什么/天气/点歌/点歌模式/wiki/epic/历史上的今天/订阅/偷表情/日志；其余动词会提示改用 `/bot` 形式 |

> 普通账户的帮助总览只显示 10 个公开主题：订阅、点歌、表情、天气、维基、历史上的今天、下载、昵称、链接、Epic。
> 管理员专属功能操作：直接上传 `.py` 文件=语法检查+受限运行（非管理员静默忽略）；`文件 <md|markdown|docx|pptx|xlsx|pdf> <主题>`=LLM 生成文档并转格式上传；`/mail status/accounts/use/send/pause/resume`=邮件桥控制（仅 Telegram 管理端）。

### 5.4 自然语言路由与问法

- **确定性路由链**：入站文本 → `base_router`（优先级：alias 10 → admin 11 → subscribe 12 → auto_send 13 → meme 20 → music_mode 40 → music/today_history/wiki/epic/weather 41 → natural_command 45 → content 46 → chat 50 → ignore 999）→ capability → `RuntimePipeline` 统一审查/渲染 → SendQueue → NapCat（子能力不直接发消息）。`/bot routes` 看全表。
- **日常说法归一化**（优先级 45，规则保守、闲聊不误触；含链接时让位解析）：`杭州天气怎么样`→`天气 杭州`；`帮我查一下杭州天气`→同；`来首晴天`/`放首歌`→`点歌 …`；`以后点歌只发卡片和语音`→`点歌模式 …`；`查一下维基 鸣潮`→`wiki 鸣潮`；`这周有什么免费游戏`→`epic`；`今天历史上发生了什么`→`历史上的今天`；`偷个表情`→`偷表情`（需表情库开启）；`weather in beijing`→中文城市（内置 36 城英文映射）。
- **点名**：只写昵称（`岸宝`）也算在叫机器人（与 @ 互补，`呼叫/召唤/在吗` 同样生效）；群聊门禁四档：black1 完全静默 / black2 仅@+指令 / white1 指令、点名、自然提问 / white2 仅@（`/bot group` 调整）。
- **chat 内联网决策**：明确联网（时效词/搜索词/URL/现实实体）、世界观词知识库优先+置信度 <0.35 回退联网、寒暄/情绪/角色扮演永不联网、技术 how-to 可调一次搜索工具；管理员私聊联网时附加 `🔎 已联网检索 N 条` 标记。
- **暂停期间仍可用**：status/help/why/receipt/audit/recent/queue/context/llm/setup.llm/config/readiness/dialogue/roles/history/control；限流/安静时间/群门禁的统一回执见 `runtime/pipeline.py`。

---

## 6. 全量配置键目录（按域）

> 完整清单以 `.env.example`（361 行，全部字段显式声明）+ `config.py`（296 个字段）为准；真实值在 `.env`/`.env.prod`，**永不入文档**。下表"默认"列 = `.env.example` 的显式值（当前生产基线）；它与代码默认在约 30 处不同（差异汇总见 §6.16，代码默认是权威缺省）。`热更` = 可用 `/bot runtime set` 即时生效（见 §7）。
> **本节为精简版**；逐键完整表（296 键 × 类型/默认/范围/热更/关系）见配套文档 [config-catalog-full.md](config-catalog-full.md)，喂 AI 时两份一起发效果最好。

### 6.0 通用写法规则（所有键适用）

1. **键名映射**：`.env` 写 `BOT_XXX` ↔ `config.py` 字段 `bot_xxx`（`translate_env_keys()` 小写化一一对应）；无 `BOT_` 前缀的键（`MCP_*`、`TELEGRAM_*`、`MAIL_BOTS`、`SQLALCHEMY_DATABASE_URL`、`LOCALSTORE_*`）不进 `Config`，由对应插件消费。
2. **列表写法**：文件/昵称列表接受 JSON 数组或分号分隔；ID 列表（管理员/群策略）接受 JSON 数组或 `,` `;` 分隔；平台列表（`BOT_CONTENT_PARSE_PLATFORMS`、`BOT_MUSIC_PLATFORMS`、表情库群名单等）同上且**全部转小写**。
3. **字典写法**：`BOT_MODEL_PRESETS/REGISTRY/SCHEDULE`、`BOT_MAIL_SENDER_ALIASES`、`BOT_VISION_MODEL_REGISTRY`、`BOT_PERSONA_ALT_PROFILES`、`BOT_CREDENTIAL_PROBE_URLS` 等为 JSON 对象字符串，解析失败**静默回退 `{}`**。
4. **布尔写法**：`true/false/1/0/yes/no/on/off/开/关/是/否`。
5. **路径重定向**：24 个路径字段 + 4 个文件列表字段（persona/knowledge/trend/glossary）中的 `data`、`data/...` 前缀统一重定向到 `BOT_RUNTIME_DATA_DIR`。

### 6.1 NoneBot 运行时

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_RUNTIME_ENABLED` | bool | true | 统一运行时总开关 |
| `BOT_RUNTIME_ADMIN_PREFIX` | str | `/bot` | 管理指令前缀 |
| `BOT_RUNTIME_GROUP_COMMAND_PREFIX` | str | `/bot` | 群内指令前缀 |
| `BOT_RUNTIME_ALIAS_ENABLED` | bool | true | 昵称别名触发 |
| `BOT_RUNTIME_DEFAULT_PERSONA` | str | `shorekeeper` | 默认人格档案 |
| `BOT_RUNTIME_PERSONA_NICKNAME` | str | `岸宝` | 主昵称 |
| `BOT_RUNTIME_PERSONA_NICKNAMES` | JSON | `[]` | 附加昵称（与 BOT_PERSONA_NICKNAMES 相关） |
| `BOT_RUNTIME_INSTANCE` | str | 空 | 多实例名（`--instance` 切换） |
| `BOT_RUNTIME_DATA_DIR` | 路径 | `../ChatBot_Runtime/data` | 运行数据根；`data/...` 一律重定向至此 |
| `BOT_RUNTIME_SETTINGS_DIR/FILE` | 路径 | `data/settings` / `data/runtime_settings.json` | 热更覆盖存储 |
| `BOT_RUNTIME_LOG_FILE/LEVEL/MAX_BYTES` | 路径/str/int | `data/runtime_events.log` / INFO / 2097152 | 运行事件日志（`/bot logs` 数据源） |

### 6.2 人格与权限

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_ADMIN_USER_IDS` | JSON | `[]` | QQ 管理员（§3）；Telegram 管理员另有 `BOT_TELEGRAM_ADMIN_USER_IDS` |
| `BOT_TRUSTED_USER_IDS` / `BOT_ENTERPRISE_USER_IDS` / `BOT_BLOCKED_USER_IDS` | JSON | `[]` | 信任/企业/黑名单 |
| `BOT_PERSONA_PROFILE_ID` | str | `shorekeeper` | 当前人格档案 |
| `BOT_PERSONA_FILES` | JSON(路径) | Runtime\data\persona\守岸人_核心人格.md | 人格原文注入（§8） |
| `BOT_PERSONA_NICKNAMES` | JSON | 8 个昵称 | 触发词（岸宝/守岸人/漂泊的终点…） |
| `BOT_PERSONA_DISPLAY_NAME` | str | `守岸人` | 显示名 |
| `BOT_PERSONA_ALT_PROFILES` | JSON | `{}` | 备选人格档案 |
| `BOT_PERSONA_VERSION` | str | `local` | 人格版本标记 |
| `BOT_PERSONA_ACTION_BRACKETS` | bool | true | 动作括号排版（热更） |
| `BOT_PERSONA_AVATAR_URL` | str | 空 | 头像 |
| `BOT_EMOTION_ENABLED` / `BOT_EMOTION_MAX_SIGNALS` | bool/int | true / 4 | 情绪信号 |
| `BOT_TONE_MODE` | enum | `private_chat` | 语气模式 |
| `BOT_TONE_VOICE` | enum | `soft` | 语气 |
| `BOT_TONE_WARMTH` / `BOT_TONE_DIRECTNESS` | float | 0.8 / 0.4 | 语气维度 0-1 |
| `BOT_TONE_MESSAGE_COUNT_LIMIT` | int | 0 | 语气上下文条数（0=不限） |

### 6.3 群策略与回复限制

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_GROUP_WHITE1` | JSON | `[]` | 正常回复+主动抽奖群 |
| `BOT_GROUP_WHITE2` | JSON | `[]` | 仅 @或显式命令群 |
| `BOT_GROUP_BLACK1` / `BOT_GROUP_BLACK2` | JSON | `[]` | 黑名单档位（热更） |
| `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED` / `_PROBABILITY` | bool/float | false / 0.05 | 群聊自动搭话 |
| `BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS` / `_MAX_REPLIES_PER_HOUR` | int | 90 / 6 | 主动发言节流 |
| `BOT_GROUP_DIGEST_*` | 混合 | false / … | 群摘要（LLM 可选，TTL 3600s，≤800 字，≤20 轮） |
| `BOT_QUIET_HOURS_*` | 混合 | true，00:00-06:00，Asia/Hong_Kong，group | 免打扰；`_BYPASS_ROLES=["admin"]` |
| `BOT_RATE_LIMIT_ENABLED` / `_WINDOW_SECONDS` / `_CHAT_GLOBAL_MAX_REQUESTS` / `_CHAT_SENDER_MAX_REQUESTS` / `_CHAT_SESSION_MAX_REQUESTS` | bool/int | true / 60 / 60 / 8 / 12 | 限流三维度（全局/发送者/会话，60s 窗口）；admin 绕过 |
| `BOT_RATE_LIMIT_TARGET_MIN_INTERVAL_SECONDS` / `_DB_PATH` | int/路径 | 0 / 空 | 目标最小间隔；空=内存实现 |
| `BOT_REPLY_DETAIL` | enum | `detail` | 详略档位（热更） |
| `BOT_REPLY_DEFAULT_CONTEXT_BUDGET` / `_SUPPORT_` / `_GROUP_` / `_DEEP_HELP_` | int | 8192/8192/8192/12288 | 上下文 token 预算 |
| `BOT_REPLY_*_MAX_MESSAGES`（6 键） | int | 0 | 各场景消息条数（0=不限） |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | int | 0 | 单条字数上限（0=不限，热更） |
| `BOT_RENDER_FORWARD_*` | int | 0/0/900 | 合并转发节点（0=不分节点） |

### 6.4 持久化与诊断（每域= 开关+路径+容量）

| 域 | 键 | 默认 |
|---|---|---|
| 审计 | `BOT_AUDIT_ENABLED`（false）+ `_DB_PATH`（wuwa_audit.sqlite3）+ `_MAX_ITEMS`（1000）+ `_LOG_FILE/_LOG_MAX_BYTES` | 审计记录（/bot audit） |
| 诊断 | `BOT_DIAGNOSTICS_ENABLED`（false）+ `_DB_PATH` + `_MAX_ITEMS`（100） | /bot recent、why 数据源 |
| 历史 | `BOT_HISTORY_ENABLED`（false）+ `_DB_PATH` + `_MAX_TURNS`（6）+ `_MAX_CHARS`（1600）+ `_MAX_ITEMS`（1000） | 对话历史 |
| 记忆 | `BOT_MEMORY_ENABLED`（false）+ `_DB_PATH` + `_MAX_ITEMS`（5）+ `_MAX_CHARS`（1200）+ `BOT_MEMORY_EXTRACT_ENABLED`（true） | 长期记忆 |
| 回执 | `BOT_RECEIPTS_ENABLED`（false）+ `_DB_PATH` + `_MAX_ITEMS`（1000） | /bot receipt |
| 发送队列 | `BOT_SEND_QUEUE_ENABLED`（false）+ `_DB_PATH` + `_MAX_ITEMS`（1000）+ `_MAX_ATTEMPTS`（3）+ `_RETRY_BASE_SECONDS`（30）+ `_RETRY_MAX_SECONDS`（300）+ `_WORKER_ENABLED`（false）+ `_WORKER_INTERVAL_SECONDS`（30）+ `_WORKER_BATCH_SIZE`（20） | 重试队列 |
| 超时 | `BOT_TRANSPORT_TIMEOUT_SECONDS`（15，(0,600]，热更）+ `BOT_REQUEST_BUDGET_SECONDS`（90，(0,600]） | 发送硬超时 / 请求总预算 |

### 6.5 LLM 引擎与路由（详见 §4）

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_CHAT_ENABLED` | bool | true | 对话 LLM 总开关 |
| `BOT_CHAT_PROVIDER` | enum | `openai_compatible` | openai_compatible / static |
| `BOT_CHAT_MODEL` | str | `gpt-5.6-terra` | 主模型（热更） |
| `BOT_CHAT_API_KEY` | 密钥 | 占位 | 七必配之一，永不展示 |
| `BOT_CHAT_BASE_URL` | url | `https://newapi.qianqianye.com/v1` | OpenAI 兼容接口 |
| `BOT_CHAT_TEMPERATURE` | float | 0.7 | 0-2（热更） |
| `BOT_CHAT_MAX_TOKENS` | int | 4096 | ≥0（热更） |
| `BOT_CHAT_TIMEOUT_SECONDS` | float | 30 | 秒 |
| `BOT_CHAT_REASONING_EFFORT` | enum | 空 | 空/off/low/medium/high（热更） |
| `BOT_API_KEY_QIANQIANYE/AIPRC/HCN/UMI_GROUP1/UMI_GROUP2` | 密钥 | 占位/空 | 供应商密钥池，注册表 env: 引用 |
| `BOT_MODEL_REGISTRY` | JSON | 11 条目 | 多供应商注册表（model/base_url/api_key/group/key_group/tags/priority/last_resort） |
| `BOT_MODEL_AUTO_ROUTE` | bool | true | 自动选型 fast/strong |
| `BOT_MODEL_PRESETS` | JSON | terra/luna | 短名映射 |
| `BOT_MODEL_SCHEDULE` | JSON | `{}` | 分时段切换单个模型（热更） |
| `BOT_MODEL_PRIORITY_GROUPS` | JSON 数组 | 见 §4.2 | 时段优先级分组：峰谷顺序 + 工作日高峰窗口（热更） |
| `BOT_MODEL_PRICES` | JSON 对象 | `{}` | 每模型价格（元/1M token），按调用时刻记账（热更） |
| `BOT_USAGE_*` | 混合 | 见 §4.5 | 用量监控开关、阈值、报告时间点与状态文件 |
| `BOT_CHAT_FAST_MODE` | bool | true | 快速模式 |
| `BOT_CHAT_FAST_CONTEXT_BUDGET` / `_MAX_TOKENS` / `_TIMEOUT_SECONDS` | int | 32768 / 4096 / 30 | 快速模式预算 |
| `BOT_CHAT_FAST_MAX_CANDIDATES` | int | 0 | 候选上限（0=不限，1-100） |
| `BOT_CHAT_FAST_DISABLE_VECTOR_KNOWLEDGE` | bool | false | 快速模式跳过向量知识 |
| `BOT_CHAT_FAST_SKIP_WEB_PAGES` | bool | true | 快速模式跳过网页抓取 |
| `BOT_CHAT_FAST_WEB_MAX_QUERIES` / `_EMBEDDING_TIMEOUT_SECONDS` | int | 5 / 3 | 快速模式联网/嵌入预算 |
| `BOT_CHAT_FAILOVER_MAX_SECONDS` | float | 45 | 故障转移总时限（0=不限） |

### 6.6 知识与嵌入

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_KNOWLEDGE_FILES` | JSON(路径) | 4 个文件 | 知识源（分块向量化，§8） |
| `BOT_KNOWLEDGE_DB_PATH` | 路径 | data/knowledge_embeddings.sqlite3 | 向量库（+FAISS 索引） |
| `BOT_KNOWLEDGE_CHUNK_CHARS` | int | 600 | 分块字数 |
| `BOT_KNOWLEDGE_TOP_K` / `_MAX_CHUNKS` | int | 5 / 2 | 检索候选/注入块数 |
| `BOT_GLOSSARY_FILES` / `_MAX_ENTRIES` / `_MAX_CHARS` | JSON/int | 空 / 30 / 1500 | 词表 |
| `BOT_TREND_ENABLED` / `_FILES` / `_MAX_AGE_DAYS` / `_MAX_NOTES` / `_MAX_CHARS` | 混合 | false / 空 / 14 / 5 / 500 | 时效知识 |
| `BOT_EMBEDDING_ENABLED` | bool | false | 远程嵌入 |
| `BOT_EMBEDDING_BASE_URL` / `_MODEL` / `_API_KEY` / `_TIMEOUT_SECONDS` / `_DIMENSIONS` | 混合 | 空 / 空 / 空 / 30 / 1024 | 远程嵌入参数 |
| `BOT_EMBEDDING_LOCAL_ENABLED` | bool | true | 本地 Ollama 兜底 |
| `BOT_EMBEDDING_LOCAL_BASE_URL` / `_MODELS` / `_API_KEY` / `_TIMEOUT_SECONDS` | 混合 | http://127.0.0.1:11434/v1 / bge-m3 / 空 / 60 | 本地嵌入（1024 维） |
| `BOT_USER_PROFILES_FILE` | 路径 | 空 | 用户画像 |

### 6.7 网络、内容与媒体

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_CONTENT_PARSE_ENABLED` | bool | true | 链接解析总开关 |
| `BOT_CONTENT_PARSE_PLATFORMS` | JSON | `[]` | 平台白名单（空=全部 21+ 平台） |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool | true | 视频直发（热更；大小上限复用 BOT_DOWNLOAD_MAX_BYTES） |
| `BOT_DOWNLOAD_DIR` / `_MAX_BYTES` / `_MAX_HEIGHT` / `_TIMEOUT_SECONDS` | 混合 | data/downloads / 1GB / 0（不限）/ 600 | 下载 |
| `BOT_DOWNLOAD_CACHE_MAX_AGE_DAYS` / `_MAX_BYTES` | int | 7 / 2GB | 下载缓存 |
| `BOT_DOWNLOAD_PROXY` | url | `http://127.0.0.1:7890` | 下载代理 |
| `BOT_FETCH_PLAYWRIGHT_ENABLED` / `_TIMEOUT_SECONDS` | bool/int | true / 10 | 动态页面抓取 |
| `BOT_COOKIES_FILE` | 路径 | data/platform_cookies.txt | Cookie 存储（§9） |
| `BOT_CARD_RENDER_ENABLED` / `_BACKEND` / `_DIR` / `_UI_SCALE` / `_CACHE_MAX_BYTES` / `_ASSET_DIR` | 混合 | true / playwright / data/cards / 1.25 / 256MB / 空 | 卡片渲染（Mica 规范） |
| `BOT_HELP_CARD_COLOR` | hex | 空 | 帮助页主色（空=中性灰） |
| `BOT_MEDIA_ANALYZE_ENABLED` | bool | true | 媒体分析 |
| `BOT_MUSIC_ENABLED` / `_PLATFORMS` / `_CACHE_MAX_BYTES` | 混合 | true / 空(全部) / 512MB | 点歌 |
| `BOT_NATURAL_COMMAND_ENABLED` | bool | true | 自然语言指令路由 |
| `BOT_PARSE_HISTORY_ENABLED` / `_DB_PATH` / `_MAX_ITEMS` | 混合 | true / data/parse_history.sqlite3 / 2000 | 解析历史 |
| `BOT_WEB_SEARCH_ENABLED` / `_MAX_RESULTS` / `_TIMEOUT_SECONDS` / `_ADMIN_NOTICE` | 混合 | false / 20 / 3 / false | 联网搜索（热更前两项） |
| `BOT_WEB_INTENT_TELEMETRY_*` / `BOT_WEB_CLASSIFIER_SHADOW_ENABLED` | 混合 | false | 意图遥测（默认关） |

### 6.8 表情包

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_MEME_COMMAND_ENABLED` | bool | true | 文字表情命令 |
| `BOT_MEME_API_ENABLED` / `_BASE_URL` / `_TIMEOUT_SECONDS` / `_OUTPUT_DIR` | 混合 | false / http://127.0.0.1:2233 / 15 / data/memes | meme-api 服务 |
| `BOT_MEME_SEARCH_ENABLED` / `_TIMEOUT_SECONDS` / `_CACHE_SECONDS` | 混合 | false / 8 / 600 | 表情搜索（热更开关） |
| `BOT_MEME_CACHE_MAX_BYTES` | int | 256MB | 缓存 |
| `BOT_MEME_LIBRARY_ENABLED` / `_DIR` / `_DB_PATH` / `_MAX_FILES` / `_MAX_FILE_BYTES` / `_MAX_AGE_DAYS` | 混合 | false / data/meme_library / meme_library.sqlite3 / 20000 / 5MB / 30 | 表情库 |
| `BOT_MEME_LIBRARY_COOLDOWN_SECONDS` | int | 20 | 抽取冷却 |
| `BOT_MEME_LIBRARY_GROUP_ALLOWLIST` / `_DENYLIST` | JSON | `[]` | 群白/黑名单 |
| `BOT_MEME_LIBRARY_PREFER` | JSON | 守岸人/岸宝/鸣潮… | 抽取偏好标签 |
| `BOT_MEME_LIBRARY_NSFW_MAX` / `_NSFW_DELETE` | float | 0.2 / 0.8 | NSFW 阈值 |
| `BOT_MEME_LIBRARY_PROXY` | url | 空 | 代理 |
| `BOT_MEME_LIBRARY_VLM_*`（ENABLED/BASE_URL/MODEL/API_KEY/PRESET/TIMEOUT） | 混合 | false… | VLM 自动打标（需视觉模型） |

### 6.9 时间、天气与公开查询

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_TIMEZONE` | str | Asia/Hong_Kong | 全局时区 |
| `BOT_TEMPORAL_ENABLED` / `BOT_HOLIDAYS_FILE` | bool/路径 | true / 空 | 时间理解/节假日 |
| `BOT_EPIC_ENABLED` | bool | true | Epic 免费游戏 |
| `BOT_TODAY_HISTORY_ENABLED` / `_PUSH_FILE` / `_CACHE_FILE` | 混合 | true / data/today_history_push.json / cache.json | 历史上的今天 |
| `BOT_WEATHER_ENABLED` / `_QUERY_ENABLED` | bool | false / true | 主动/查询天气 |
| `BOT_WEATHER_LATITUDE` / `_LONGITUDE` | float | 22.3193 / 114.1694 | 默认坐标（香港） |
| `BOT_WEATHER_CACHE_SECONDS` / `_TIMEOUT_SECONDS` | int | 1800 / 8 | 缓存/超时 |
| `BOT_WIKI_ENABLED` / `_LANG` | bool/str | true / zh | 维基 |

### 6.10 订阅与集成

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_SUBSCRIBE_ENABLED` | bool | true | 订阅系统 |
| `BOT_SUBSCRIBE_DB_PATH` | 路径 | data/subscriptions.sqlite3 | 存储 |
| `BOT_SUBSCRIBE_POLL_INTERVAL_SECONDS` / `_LIVE_POLL_SECONDS` / `_PLAYWRIGHT_POLL_SECONDS` | int | 300 / 60 / 1800 | 轮询周期 |
| `BOT_SUBSCRIBE_MAX_ITEMS_PER_TICK` | int | 20 | 单轮推送上限 |
| `BOT_SUBSCRIBE_CARD_ENABLED` | bool | true | 推送用卡片 |
| `BOT_SUBSCRIBE_DIGEST_HOUR` / `_MINUTE` | int | 20 / 0 | 日报时间 |
| `BOT_GSCORE_ENABLED` / `_HOST` / `_PORT` / `_BOT_ID` / `_BOT_SELF_ID` / `_WS_TOKEN` / `_MAX_RETRY` | 混合 | false / 127.0.0.1 / 8765 / NoneBot2 / 空 / 空 / 5 | GsCore 桥接 |
| `BOT_SHARE_ENABLED` / `_GROUPS` / `_READ_ONLY` | 混合 | false / 空 / false | 共享群 |
| `BOT_SHARED_EXPORT_ENABLED` / `_INCLUDE_PRIVATE` / `_MAX_CHARS` / `BOT_SHARED_GROUP_CONTEXT_ENABLED` | 混合 | false / false / 200 / false | 共享导出与上下文 |

### 6.11 外部凭据

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `BOT_CREDENTIALS_FILE` | 路径 | 空 | 额外凭据文件 |
| `BOT_CREDENTIAL_CHECK_ENABLED` / `_INTERVAL_HOURS` | bool/int | false / 6 | 定时健康检查 |
| `BOT_CREDENTIAL_PROBE_URLS` | JSON | `{}` | 平台→探测地址 |
| `BOT_CREDENTIAL_PROBE_TIMEOUT_SECONDS` / `_WARN_DAYS` | int | 8 / 7 | 探测超时/提前告警天数 |

### 6.12 Telegram 与邮件

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `TELEGRAM_BOTS` | JSON | `[]` | BotFather Token 列表（≥1 个才连接） |
| `BOT_TELEGRAM_ADMIN_USER_IDS` / `_ADMIN_CHAT_IDS` | JSON | `[]` | TG 管理员 / 邮件提醒会话 |
| `TELEGRAM_PROXY` / `TELEGRAM_WEBHOOK_URL` | url | 空 | 代理/Webhook |
| `MAIL_BOTS` | JSON | `[]` | 邮箱账户（IMAP/SMTP；授权码只进此处） |
| `BOT_MAIL_BRIDGE_ENABLED` / `_STATE_FILE` / `BOT_MAIL_AUTO_REPLY_ENABLED` | 混合 | false / data/mail_bridge_state.json / false | 邮件桥接/自动回复 |
| `BOT_MAIL_NOTIFY_TELEGRAM_ENABLED` / `_PREVIEW_CHARS` | bool/int | true / 280 | 新邮件 TG 提醒 |
| `BOT_MAIL_SENDER_ALIASES` | JSON | foxmail→QQ 映射 | 发件别名 |

### 6.13 MCP / 数据库 / 视觉 / 其他

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `MCP_SERVERS` / `MCP_CACHE_TTL` / `MCP_TOOL_TIMEOUT` | JSON/int | `{}` / 3600 / 30 | nonebot-plugin-mcpclient |
| `SQLALCHEMY_DATABASE_URL` | url | postgresql+asyncpg://…CHANGE_ME@127.0.0.1:5432/chatbot | ORM 底座（nb orm upgrade） |
| `BOT_VISION_ENABLED` / `_MODE` / `_TIMEOUT_SECONDS` / `_MAX_IMAGES` / `_MAX_CHARS` / `BOT_VISION_MODEL_REGISTRY` | 混合 | false / relay / 20 / 2 / 500 / `{}` | 图片识别（relay=先转文字，direct=直传多模态） |
| `LOCALSTORE_USE_CWD` | bool | **false（必须保持）** | false 时数据写 Runtime，防回流源码区 |
| `LOCALSTORE_CACHE_DIR` / `_CONFIG_DIR` / `_DATA_DIR` | 路径 | ../ChatBot_Runtime/cache/nonebot、config、data/nonebot | 第三方插件落盘 |

### 6.14 `.env.example` 未列出但实际生效的键（15 个，代码默认）

`BOT_MUSIC_ANALYTICS_ENABLED/_DB_PATH/_RETENTION_DAYS`、`BOT_MUSIC_CHART_ENABLED/_SOURCES/_POLL_INTERVAL_SECONDS`、`BOT_VISION_REPLY_PROBABILITY`、`BOT_SUBSCRIBE_JITTER_RATIO/_GLOBAL_CONCURRENCY/_PLATFORM_CONCURRENCY/_MIN_INTERVAL_SECONDS/_LEASE_SECONDS/_RETRY_BASE_SECONDS/_RETRY_CAP_SECONDS/_OUTBOX_INTERVAL_SECONDS`。

### 6.15 配置校验规则（config_readiness，`/bot config` 与 `config-smoke` 的判据）

- **占位符黑名单**：key 视为缺失 = 空 或 `<api_key>`/`<real_api_key>`/`your-api-key`/`replace-me`/`sk-your-api-key`/`test-key` 等；model 视为缺失 = 空 或 `<model_name>`/`your-model-name`/`replace-me` 等。
- **base_url**：空=`openai_base_url_missing`；scheme 非 http(s) 或无 host=`invalid`；**内嵌账号密码=`openai_base_url_unsafe`**（展示时脱敏 `[redacted]@host`）。
- **生成参数**：temperature 有限且 0.0-2.0；max_tokens ≥0（0=不设上限）；timeout >0。
- **文件校验**：人格/知识文件缺失、后缀不在 `{.md,.txt,.docx}`、不可读、解析后为空都会报对应错误码；人格总量 <10 字符或有效行 <2 只警告（`persona_profile_weak`）。
- **就绪判定**：`ready_for_real_llm` = 无 error 且 provider=openai_compatible 且 key/model/base_url 合法；状态三档 `ready / blocked / local_only`；`llm_fix_hints` 按错误码给修复提示。
- **附带汇报**：runtime/chat/memory/history/限速（store=sqlite|memory）/免打扰/审计/回执/发送队列各开关与关键数值。

### 6.16 `.env.example` 样例值 ≠ 代码默认（约 30 处，代码默认为权威缺省）

重点差异：`BOT_RUNTIME_DEFAULT_PERSONA`(样例 shorekeeper/默认 default)、`BOT_RUNTIME_INSTANCE`(空/`default`，空则自举为人格 id)、`BOT_TONE_WARMTH`(0.8/0.7)、`BOT_TONE_DIRECTNESS`(0.4/0.5)、`BOT_GROUP_DIGEST_MAX_TURNS`(20/150)、`BOT_RATE_LIMIT_CHAT_SESSION/SENDER_MAX_REQUESTS`(12/6、8/4)、`BOT_RENDER_FORWARD_MIN_CHARS`(0/1500)、`BOT_REPLY_DETAIL`(detail/auto)、四个 `BOT_REPLY_*_CONTEXT_BUDGET`(8192 系/2048 系)、`BOT_KNOWLEDGE_CHUNK_CHARS`(600/900)、`BOT_KNOWLEDGE_MAX_CHUNKS`(2/4)、`BOT_KNOWLEDGE_TOP_K`(5/4)、`BOT_CHAT_PROVIDER/MODEL/BASE_URL`(中转配置/static 占位)、`BOT_CHAT_FAST_CONTEXT_BUDGET`(32768/9600)、`BOT_CHAT_FAST_WEB_MAX_QUERIES`(5/3)、`BOT_DOWNLOAD_PROXY`(7890/直连)、`BOT_COOKIES_FILE`(data/platform_cookies.txt/空)。memory/history/diagnostics/audit/receipts/send_queue/rate_limit 的 db_path 代码默认空（内存或禁用），样例填了 `data/wuwa_*.sqlite3` 具体文件。

另：`BOT_MUSIC_MODE` 只存在于热更白名单（`config.py` 无字段），未设置时运行时回退 `card`；`BOT_MODEL_REGISTRY` 样例里的 `key_group`/`last_resort` 字段模型路由器**不解析**，仅作人工标注。

---

## 7. 可热更参数（SETTABLE_KEYS，`/bot runtime set` 即时生效，无需重启）

共 **22 键**（`runtime/settings.py`，逐一核对）：

| 键 | 类型/转换 | 取值 |
|---|---|---|
| `BOT_CHAT_TEMPERATURE` | float | 0.0–2.0 |
| `BOT_CHAT_MAX_TOKENS` | int | ≥0 |
| `BOT_CHAT_MODEL` | str | 已注册模型 id / 预设名 |
| `BOT_CHAT_REASONING_EFFORT` | enum | 空/off/low/medium/high/xhigh/max（空=各模型家族默认最高档） |
| `BOT_TRANSPORT_TIMEOUT_SECONDS` | float | (0,600]，默认 15 |
| `BOT_MODEL_SCHEDULE` | JSON | {"HH:MM-HH:MM": "模型id或预设"} |
| `BOT_MODEL_PRIORITY_GROUPS` | JSON 数组 | 时段优先级分组（峰谷顺序，见 §4.2/§4.4） |
| `BOT_MODEL_PRICES` | JSON 对象 | 每模型价格 {"模型名":{"input":元/1M,"output":元/1M}}（热改计价） |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | int | ≥0（0=不限） |
| `BOT_REPLY_DETAIL` | enum | 详细/精简/默认 |
| `BOT_MUSIC_MODE` | enum | 卡片/语音/音频/链接（可组合） |
| `BOT_MEME_SEARCH_ENABLED` | bool | true/false |
| `BOT_WEB_SEARCH_ENABLED` | bool | true/false |
| `BOT_WEB_SEARCH_ADMIN_NOTICE` | bool | true/false |
| `BOT_PERSONA_ACTION_BRACKETS` | bool | true/false |
| `BOT_VISION_ENABLED` | bool | true/false |
| `BOT_VISION_MODE` | enum | relay/direct |
| `BOT_CONTENT_VIDEO_AUTO_SEND` | bool | true/false |
| `BOT_GROUP_BLACK1/BLACK2/WHITE1/WHITE2` | 群号列表 | JSON 数组 |

管理：`/bot runtime get <key>` 读；`/bot runtime list` 列覆盖项；`/bot runtime reset [key]` 恢复默认。覆盖值存 `runtime_settings.json`。

---

## 8. 人格与知识：怎么"喂"给机器人

### 8.1 目录结构与配置入口

```text
personas\shorekeeper\
├─ identity.md                 源码内人格文本（身份/理念/爱好/习惯）
├─ aliases.txt                 昵称别名表（守岸人｜岸宝｜小岸同学｜蓝蝴蝶｜花房的守护者）
└─ knowledge\
   ├─ 守岸人_核心知识.md        角色核心设定知识
   └─ 守岸人_人格与表达规范.md  人格档案与表达规范
```

| 通道 | 配置键 | 说明 |
|---|---|---|
| 人格文件 | `BOT_PERSONA_FILES` | JSON 数组，支持绝对路径；**生产生效源**当前指向 `Runtime\data\persona\守岸人_核心人格.md`（用户维护的唯一提示词源），以 `.env` 实际清单为准 |
| 人格档案 | `BOT_PERSONA_PROFILE_ID=shorekeeper`、`BOT_PERSONA_ALT_PROFILES`、`BOT_PERSONA_VERSION` | 多档案切换（/bot runtime persona） |
| 知识文件 | `BOT_KNOWLEDGE_FILES` | JSON 数组；含鸣潮/战双库街区百科（外部绝对路径）+ 守岸人两件 + 历史上的今天 `th-*.md` 等，以 `.env` 实际清单为准 |
| 词表 | `BOT_GLOSSARY_FILES`（≤30 条 / 1500 字） | 专有名词矫正 |
| 趋势 | `BOT_TREND_FILES`（近 14 天） | 时效性知识 |
| 向量化 | `BOT_KNOWLEDGE_CHUNK_CHARS=600`（代码默认 900）、`BOT_KNOWLEDGE_TOP_K=5`、`BOT_KNOWLEDGE_MAX_CHUNKS=2` | 分块与检索数量 |
| 嵌入服务 | `BOT_EMBEDDING_*`（远程）/ `BOT_EMBEDDING_LOCAL_*`（本地 Ollama bge-m3，1024 维） | 本地优先，远程兜底 |

### 8.2 两种注入机制（重要区别）

- **人格 = 原文注入**：`BOT_PERSONA_FILES` 全文写入 `PersonaProfile.raw_text`，聊天时作为系统提示词主体（不走向量）。预算优先级：人设原文 > 实时分区（分区内 知识库 0.42 > 短时对话 0.14 > 长时记忆 0.08）。人格文件**内容**改动热生效（mtime 缓存）；改 `.env` 清单本身需重启。
- **知识 = 分块向量化**：`BOT_KNOWLEDGE_FILES`/`BOT_GLOSSARY_FILES`/`BOT_TREND_FILES` 段落式分块（超长单段硬切；按小标题/空行分段的 md 最友好），写入 `knowledge_embeddings.sqlite3`（FTS5 trigram 关键词索引）+ `knowledge_faiss.index`（缺 FAISS 时回退 numpy）。检索 = 向量余弦 + BM25 双通道 RRF(k=60) 融合；无关键词命中且最高余弦 < 0.30 判定未命中（可回退联网）。
- **支持格式**：`.md`、`.txt`（UTF-8）与 `.docx`（抽取正文段落）。`source_id`=文件名；内容变化会重置该块向量等待重嵌。
- **嵌入链注意**：本地 Ollama bge-m3 优先，远程兜底；批大小 10、断点续跑（已有向量的块不重嵌）；`base_url|models` 指纹变化会触发**全库重嵌**——勿随意改 `BOT_EMBEDDING_LOCAL_MODELS`。

### 8.3 喂文档操作步骤

① 文件放 `personas/shorekeeper/knowledge/` 或任意外部位置 → ② 把绝对路径追加进 `.env` 的 `BOT_KNOWLEDGE_FILES`（改 .env 需重启）→ ③ `scripts\dev.ps1 -Task knowledge-sync`（分块并写入向量库）→ ④ 验证。
**删块语义（务必注意）**：同步以当次传入的**全量文件清单**为准，清单外 `source_id` 的旧块会被全部删除；**机器人运行中进程的清单在重启前是旧的**——入库后请尽快重启机器人，否则旧进程的下一次知识检索会按旧清单删掉新块（handover-08-31 实证）。
**验证**：`embedding-smoke`（看 active_base_url 是否命中本地）→ `context-smoke`（确认知识库命中而非顺序取块）→ `persona-smoke`（人格与知识来源加载）→ 端到端 `chat-smoke -Message "…"` 或 QQ 私聊问一个设定问题。

**已列入知识库清单（2026-09-01，待同步）**：说明书体新文档 `docs/ai-kb-operations-manual.md`（专为向量检索撰写：成段自包含、每段 ≤600 字、命令与含义同段）已加入 `BOT_KNOWLEDGE_FILES`（现共 17 个文件）；两份速查表（本文件与 config-catalog-full.md）为表格体，保留作人工/AI 编码助手参考，不入机器人知识库。待用户审阅手册并自行运行 `knowledge-sync` 后、再重启机器人，向机器人提问即可命中手册内容。

### 8.4 人格切换与记忆（区别于知识库）

- **切换顺序（纯规则）**：管理员覆盖 `/bot persona switch <id|default>` → 情绪信号命中备档 `emotions` → 按 `weight` 随机抽取（`/bot persona probability` 调整，0=不参与）→ 默认主人格。
- **记忆 ≠ 知识库**：聊天收尾由轻量 LLM 自动抽取事实（`BOT_MEMORY_EXTRACT_ENABLED=true`）写入 `wuwa_memory.sqlite3`；检索按 `updated_at` 取最近 5 条（非向量），以"已读取记忆："分区注入。

---

## 9. 密码、Cookie 与凭据

| 对象 | 位置/方式 | 要点 |
|---|---|---|
| NapCat WebUI 密码 | NapCat 本地面板（默认 http://127.0.0.1:6099） | 首次扫码登录成功后**修改一次 WebUI 密码**；WebUI token 在启动日志或 `webui.json` |
| QQ 登录 | NapCat 扫码（用小号，勿用主号） | 凭证失效只能重扫；配置按 QQ 号存 `onebot11_<QQ号>.json` |
| OneBot WS Token | NapCat 网络配置（3001 WS 服务器）+ `.env.prod` 的 `ONEBOT_WS_URLS` | 两边必须完全一致；真实 token 只存本地 `.env.prod` |
| 平台 Cookie | `BOT_COOKIES_FILE`（Runtime\data\platform_cookies.txt） | 浏览器导出的 **Netscape 格式**，换 Cookie 直接覆盖该文件并重启；日志/审计/消息都不打印 Cookie 值 |
| 凭据引用机制 | `sources/credentials.py` | 外部抓取只拿 `CredentialRef`（掩码预览=前 6 字符+长度），原始值仅在传输边界解析；两种后端：`EnvCredentialStore`（变量 `BOT_CREDENTIAL_<REF_ID>`，可附 `_KIND/_DOMAIN/_EXPIRES_AT`）与 `FileCredentialStore`（`BOT_CREDENTIALS_FILE` 指定 JSON：`{"refs":{"<ref_id>":{"kind","value","domain","expires_at"}}}`，配置了文件则文件优先）；可扩展 keyring 等 |
| 凭据健康 | `BOT_CREDENTIAL_CHECK_ENABLED` / `BOT_CREDENTIAL_PROBE_URLS` / `BOT_CREDENTIAL_WARN_DAYS=7` | `/bot alert check [--probe]` 检查过期（401/403=需重登） |
| LLM 密钥 | `.env` 的 `BOT_API_KEY_*` / `BOT_CHAT_API_KEY` | 注册表一律 `env:变量名` 引用；密钥不回显、不入日志/文档 |
| 邮箱 | `MAIL_BOTS` / `BOT_MAIL_SENDER_ALIASES` | Gmail 用 OAuth2 或 16 位应用专用密码（勿用主密码）；授权码只进 .env |
| PostgreSQL | `SQLALCHEMY_DATABASE_URL`（本机 5432） | 密码用 CHANGE_ME 占位替换，不入文档 |

---

## 10. 现有文档地图

| 文档 | 主题 | 内容概括 |
|---|---|---|
| `README.md` | 项目总览 | NoneBot AI 聊天机器人（守岸人人格、向量知识、聊天记忆、QQ/Telegram/Mail 适配器、媒体解析、订阅、表情包、统一运行时）；三区磁盘布局与 AI 扫描边界；快速启动四命令（console / readiness-smoke / run / verify） |
| `WORKSPACE_GUIDE.md` | 工作区引导 | 三目录职责表、启动与验证入口、归档入口、最小回归测试、禁止事项 |
| `AGENTS.md` | AI 工作区规则 | 扫描边界、dev.ps1 测试入口、源码树禁止缓存文件、卡片 Mica UI 规范、归档流程 |
| `COMMANDS.md` | 开发命令 | dev.ps1 任务表、测试策略（完整测试树在归档包）、路径与安全规则 |
| `docs/napcat-setup.md` | NapCat 连接 QQ | 下载与扫码（小号）、被踢重登、WebUI 密码修改、3001 反向 WS + token、`.env.prod` 三项、ORM 初始化、驱动器/适配器选型结论 |
| `docs/external-runtime-access.md` | 外部运行时访问 | 机器人经 .env/config.py/dev.ps 访问外部数据（非读 Markdown）；数据流图；`data/` 重定向；工作区打开方式、验收命令、快速故障判断表 |
| `docs/route-matrix.md` | 问法路由矩阵 | base_router → capability → RuntimePipeline → SendQueue 链路；问法→kind→优先级权威矩阵；群聊门控、知识库优先+联网回退、点歌组合、下载配额 |
| `docs/acceptance-manual.md` | 验收与接入手册 | 顺序化验收：依赖 → 人格对话验收（console→真实模型→smoke 链）→ NapCat → GsCore；运行时日志、Cookie 接入、向量知识库配置与最终检查表 |
| `docs/standard-parse-card-acceptance.md` | 标准解析卡验收 | 解析信息卡的验收基准 |
| `docs/workspace-archive-policy.md` | 工作区与归档规范 | 归档标准流程（停进程→压缩→验证→移出）、活动数据不删、敏感信息红线 |
| `docs/handover-2026-08-29.md` | 交接报告（明细底稿） | 人设原文注入、记忆补全、模型路由/分时切换/vision、网络韧性、LLM 接入卡片化；未完成明细 |
| `docs/handover-2026-08-31.md` | 交接快照（全量状态） | 后端韧性/X GraphQL/vision/文件收发完成清单；「历史上的今天」知识库全链路与 **knowledge-sync 按清单删块的坑**；配置键速查 |
| `docs/handover-2026-09-01.md` | 交接快照（增量） | ParsedContent 纯嵌套化、六平台字段深化、视频直发、venv 修复；剩余待办与人工验收 |

另有 `docs/superpowers/specs|plans/` 存设计与计划历史；`handover-2026-08-29.md` 引用的 `backend-resilience-requirements.md` 已归档不在 docs/。

---

## 11. 从零搭建清单（第一次跑通）

1. **环境**：`powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task doctor"`（检查 Python/NoneBot/适配器）。
2. **配置**：复制 `.env.example` → `.env`；至少填 §4.1 七必配键 + `BOT_ADMIN_USER_IDS`；`.env.prod` 保持 NapCat token 一致。
3. **NapCat**：按 `docs/napcat-setup.md` 启动并扫码；WebUI 改密；3001 WS 服务器带 token 运行。
4. **ORM**：`nb orm upgrade` + `nb orm check`（PostgreSQL 本机服务）。
5. **启动**：`dev.ps1 -Task run`；日志出现 OneBot V11 连接 3001 成功。
6. **验证**：QQ 里发 `/bot status`（管理员）→ `/bot setup llm` → `/bot llm`；普通账户视角发 `天气 香港`、`点歌 测试`。
7. **知识**：确认 `BOT_KNOWLEDGE_FILES` 路径存在 → `knowledge-sync` → `/bot persona` 自检。
8. **体检**：`dev.ps1 -Task verify`（docs/plugin/pytest/ruff/mypy）。

---

## 12. dev.ps1 任务速查

| 任务 | 用途 | 联网/副作用 |
|---|---|---|
| help / doctor / install | 帮助 / 依赖检查 / 安装依赖（uv sync 或 pip） | install 修改外部 venv |
| run / run-watch | 启动 NoneBot（可自动重启） | 连接平台 |
| console | 控制台对话 | 默认离线 |
| nonebot-smoke / startup-smoke | 插件导入 / 子进程加载后退出 | 不连 NapCat |
| readiness-smoke / config-smoke / persona-smoke / context-smoke / why-smoke | 就绪/配置/人格/上下文/决策本地检查 | 不调 LLM |
| llm-setup / llm-smoke | LLM 配置清单 / 真实连接检查 | 只读网络 |
| dialogue-smoke / chat-smoke | 对话链路验证 | 依配置调 LLM |
| knowledge-sync | 分块写入向量知识库 | 改外部 data；调嵌入服务（本地优先） |
| route-demo / route-smoke | 路由矩阵 / 真实能力验证 | 后者可能联网 |
| queue-smoke / transport-smoke / online-transport-smoke | 队列/消息段/在线状态 | 不发 QQ |
| credential-smoke / embedding-smoke / gscore-smoke | 凭据/嵌入/GsCore 检查 | 只读 |
| test / lint / typecheck / verify | 4 个关键回归 / ruff / mypy / 总检查 | 本地 |
| smoke / docs-check / plugin-check / runtime-layout | 聚合冒烟 / 文档锚点 / 插件契约 / 外部布局 | 只读 |

---

## 13. 典型案例

**案例 A：接入一个新的模型供应商（管理员，对话框直接做）**
```text
/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1
/bot model list      ← 确认顺序
/bot model set myapi
```
密钥更安全的写法：先在 `.env` 加 `BOT_API_KEY_MYAPI=sk-xxx`，再 `key=env:BOT_API_KEY_MYAPI`。

**案例 B：让某指令普通账户也能用**
不可按指令单独放权；可见性由角色+帮助主题表决定。可把用户加进 `BOT_TRUSTED_USER_IDS` 提升信任级，管理员条目仍仅 admin。

**案例 C：分时段换模型（如夜间换 luna）**
```text
/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}
```

**案例 D：订阅 B 站 UP 主** → 群里直接 `/订阅 add <UP主主页链接>`；只要日报加 `--digest`。

**案例 E：LLM 不回复排查链** → `/bot status` → `/bot setup llm`（看红项）→ `/bot llm`（真实诊断）→ `/bot why`（决策解释）→ `/bot recent`（最近排障摘要）。

---

## 14. 喂给 AI 的对话指令（可直接粘贴）

把本文件发给 AI 后，可再粘贴下面任一段落下达任务：

**① 让 AI 帮你搭建：**
> 请基于我刚发给你的《ChatBot 框架 AI 搭建与配置知识包》，带我完成首次搭建：逐项告诉我 .env 需要填哪些键（按 §4.1 七必配键 + BOT_ADMIN_USER_IDS + NapCat token），每一步给出可直接复制的 PowerShell 命令；遇到需要我填密钥的地方用占位符提醒我，不要索要真实密钥明文。

**② 让 AI 汇总/更新全量配置目录：**
> 这是我仓库的《全量配置键目录》（config-catalog-full.md）。当 .env 或 config.py 发生变化后，请按同样的格式（键名、类型、默认值、取值范围、是否热更、作用与关联键）核对新差异并更新该文档；密钥一律脱敏为占位符。

**③ 在 QQ 对话框查配置（发给机器人小号的管理员账号）：**
```text
/bot setup llm        ← 引擎七键接入清单（含取值范围）
/bot config           ← 配置就绪检查（脱敏）
/bot model list       ← 已接入模型与故障转移顺序
/bot runtime list     ← 已被热更覆盖的参数
/bot readiness        ← 全链路就绪状态
```
