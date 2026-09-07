# ChatBot 全量交接报告

> 交接日期：2026-09-05  
> 当前工作区：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`  
> 当前 Git 标识：`v0.0.1-alpha.1`  
> 报告性质：源码审计、现状说明、用户决策、目标架构、接口合同、风险登记、执行路线和后续接手指南的合并文档。

---

## 0. 交接摘要

当前项目不是空项目，也不是已经完成的生产级多平台系统。它是一个以后端统一运行时为核心的 NoneBot2 alpha 项目，已经拥有较多可复用基础，但业务入口、数据存储、订阅实现、命令管理、监控数据和平台能力仍处于演进中。

当前项目已经具备的主要能力：

- NoneBot2 启动与插件加载；
- QQ/OneBot V11/NapCat 通信；
- Telegram 通信；
- Mail/IMAP/SMTP 桥接；
- 统一人格聊天；
- 本地人格知识、向量知识、记忆和对话历史；
- OpenAI-compatible LLM provider；
- 多模型注册表、排序、时段分组、reasoning effort、故障转移；
- Bilibili、小红书、抖音、X/Twitter、YouTube、微博、Pixiv 等部分链接解析；
- 部分社交订阅；
- 网易云等音乐搜索和点歌；
- 天气查询；
- Epic 免费游戏查询；
- 文件接收、Python 调试和 Markdown 到 DOCX/PPTX/XLSX/PDF 导出；
- 发送队列、回执、审计、运行日志和管理员告警；
- Token/费用的初步日志聚合和阈值提醒。

当前没有完成的主要能力：

- 稳定的后端 Control Plane API；
- 公网安全访问层；
- TailAdmin Vue Web UI；
- 多模型盲测；
- 供应商余额统一适配；
- 结构化 LLM 调用记录；
- 完整的 Token/费用/余额监控中心；
- 统一的 QQ/Telegram/Mail 文件分析流；
- 低资源强隔离代码执行沙箱；
- 森空岛和库街区订阅；
- 多数音乐平台动态订阅；
- iPad/App Store、Steam 免费游戏查询；
- 气象预警系统；
- QQ 空间日记发布；
- 表情包端到端验证和稳定自动发送；
- 戳一戳统一反应系统；
- 真正的中央决策层和统一出站网关。

本报告中所有状态必须按以下标签理解：

- **已实现**：当前代码中存在端到端实现，且有对应入口或测试证据。
- **部分实现**：存在代码，但能力不完整、依赖外部条件、只有解析没有订阅，或只有命令没有 API/UI。
- **设计已确定**：已经写入设计规格，但尚未修改业务源码。
- **完全缺失**：当前源码中未发现可执行实现。
- **待外部资料**：必须等用户提供站点脚本、字段、凭据规则或合法接口信息后才能安全实现。

---

## 1. 工作区边界和安全规则

### 1.1 允许扫描的目录

唯一允许默认扫描和修改的源码工作区：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
```

### 1.2 禁止默认扫描的外部目录

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot
```

这些目录可能包含：

- SQLite；
- FAISS；
- 聊天记忆；
- Cookie；
- API Key；
- Mail 状态；
- NoneBot data；
- 订阅状态；
- 媒体缓存；
- 日志；
- 卡片资源；
- 虚拟环境。

除非用户明确要求，不得删除、压缩、迁移或重建这些活动数据。

### 1.3 当前工作树状态

工作区存在大量未提交修改和删除。交接者必须先执行：

```powershell
git status --short --branch
```

不要使用以下破坏性命令：

```powershell
git reset --hard
git checkout -- <file>
```

除非用户明确要求恢复或丢弃指定变更。

---

## 2. 权威文档索引

### 2.1 本次审计报告

```text
docs/project-audit-and-modernization-roadmap-2026-09-05.md
```

包含：

- 平台差距；
- 核心功能差距；
- Web UI 差距；
- 架构问题；
- 设计目标；
- Phase 0-9 路线；
- TailAdmin Vue 后置策略；
- SakuraFrp 传输预算；
- 中央决策层设计。

### 2.2 控制面和 Provider 规格

```text
docs/control-plane-provider-and-usage-requirements-2026-09-05.md
```

包含：

- ProviderConfig；
- ModelConfig；
- URL resolver；
- 默认模型和模型列表；
- 显示名/实际模型 ID 分离；
- 计费模型；
- BalanceSnapshot；
- LLMCallRecord；
- Token 采集；
- extractor 沙箱；
- 三类联通检测；
- 余额和用量 API；
- 告警；
- NewAPI 适配；
- 中转站与官方 API 的计费身份分离。

### 2.3 其他关键文档

```text
README.md
COMMANDS.md
WORKSPACE_GUIDE.md
AGENTS.md
docs/acceptance-manual.md
docs/ai-kb-operations-manual.md
docs/ai-setup-knowledge-pack.md
docs/config-catalog-full.md
docs/route-matrix.md
docs/napcat-setup.md
docs/handover-2026-08-29.md
docs/handover-2026-08-31.md
docs/handover-2026-09-01.md
```

注意：交接文档和设计计划可能记录历史状态或未完成事项，不能代替当前源码验证。

---

## 3. 启动链路和当前运行流

### 3.1 启动流程

核心入口：

```text
bot.py
  ↓
nonebot.init(_env_file=(".env", ".env.prod"))
  ↓
读取 pyproject.toml
  ↓
注册 OneBot V11
  ↓
注册 Telegram
  ↓
加载 plugins/
  ↓
确认 bot_unified_runtime 已成功加载
  ↓
注册 ResilientMailAdapter
  ↓
nonebot.run()
```

关键代码：

```text
bot.py:53
bot.py:126-148
pyproject.toml:45-71
plugins/bot_unified_runtime/__init__.py:109-117
```

### 3.2 当前普通消息流

当前代码的大致逻辑：

```text
NoneBot Event
  ↓
适配器事件识别
  ↓
转换 IncomingMessage
  ↓
_route_decision / base_router
  ↓
选择 matcher/capability
  ↓
RuntimePipeline
  ↓
Policy / Role / RateLimit / QuietHours
  ↓
Capability
  ↓
CapabilityResult
  ↓
SendQueue
  ↓
OneBot/Telegram/Mail 传输
  ↓
Receipt / Audit / Diagnostic
```

已有的统一基础包括：

- `IncomingMessage`；
- `BotDecision`；
- `CapabilityResult`；
- `RuntimePipeline`；
- `SendRequest`；
- `DeliveryReceipt`；
- `AuditRecord`；
- `RuntimeDiagnostic`。

但是当前仍存在平行入口：

- 一些 matcher 直接选择 capability；
- 文件事件直接调用 `bot.call_api`；
- 文件上传后直接发送；
- Mail 控制路径有独立处理；
- 旧订阅实现和新订阅实现并存；
- 某些能力仍可能在 matcher 中直接执行同步操作。

### 3.3 目标中央决策流

目标必须改成：

```text
任何 Event
  ↓
IngressNormalizer
  ↓
统一 RuntimeEvent
  ↓
CentralDecisionEngine
  ↓
ActionPlan
  ├── SILENT
  ├── CHAT_SMALL
  ├── CHAT_LARGE
  ├── SEARCH
  ├── PLUGIN
  ├── FILE_ANALYSIS
  ├── SUBSCRIPTION
  ├── WEATHER_WARNING
  ├── POKE_REACTION
  ├── REQUIRE_APPROVAL
  └── BLOCKED
  ↓
PolicyEngine
  ↓
QuotaEngine
  ↓
ApprovalEngine
  ↓
CapabilityExecutor
  ↓
Renderer
  ↓
UnifiedDeliveryGateway
  ↓
Receipt + Audit + Diagnostics
```

强制规则：

1. 所有事件必须经过中央决策层。
2. 新功能不得新建绕过决策层的直接回复入口。
3. capability 不得直接调用平台发送 API。
4. 只有统一发送网关可以向 QQ、Telegram、Mail、Console 发送。
5. 一个事件只能产生一个最终 ActionPlan。
6. 旁路日志、诊断、审计不能产生第二条业务消息。
7. 同一事件必须有 `event_id`、`dedupe_key`、截止时间、风险等级和优先级。
8. 传输重试只能由发送层负责，业务层不得重复发送。
9. 冲突由中央层通过优先级、互斥组、风险等级和幂等键裁决。
10. 所有决策必须能解释：为什么走聊天、插件、静默、阻断或审批。

---

## 4. 当前目录和模块地图

### 4.1 根目录

```text
bot.py                         NoneBot 初始化、adapter 注册
pyproject.toml                 依赖、插件目录、adapter 配置
.env                           实际本地配置，禁止输出密钥
.env.example                   配置模板
.env.prod                      生产覆盖配置
README.md                      项目说明
COMMANDS.md                    维护命令
WORKSPACE_GUIDE.md             工作区边界
AGENTS.md                      项目规则
scripts/                       启动、诊断、验证、维护
plugins/                       生产插件
personas/                      人格和知识
plugins/bot_unified_runtime/   主运行时
```

### 4.2 生产插件目录

```text
plugins/bot_unified_runtime/
├── __init__.py
├── audit/
├── capabilities/
│   ├── auto_send/
│   ├── chat.py
│   ├── content_parser.py
│   ├── debug.py
│   ├── download.py
│   ├── echo.py
│   ├── epic.py
│   ├── file_exchange.py
│   ├── meme.py
│   ├── meme_library.py
│   ├── memory.py
│   ├── music.py
│   ├── runtime_admin.py
│   ├── runtime_logs.py
│   ├── subscribe.py
│   ├── subscribe_v2.py
│   ├── today_history.py
│   ├── weather.py
│   └── wiki.py
├── character/
├── contracts/
├── llm/
├── output/
├── policy/
├── runtime/
├── security/
├── sender/
└── sources/
    ├── fetchers/
    ├── parsers/
    └── subscriptions/
```

---

## 5. 当前已实现能力详表

### 5.1 NoneBot 与通信

#### QQ

状态：**部分实现**。

已有：

- OneBot V11；
- NapCat WebSocket；
- 私聊和群聊；
- 发送队列；
- 回执；
- 群文件；
- 私聊 offline file 自定义事件；
- 管理员识别；
- 群策略；
- quiet hours；
- 群白名单/黑名单。

限制：

- 依赖外部 NapCat；
- 不是官方 QQ API；
- QQ 空间未实现；
- 戳一戳统一 reaction 未实现。

#### Telegram

状态：**部分实现**。

已有：

- NoneBot Telegram adapter；
- poll 重试；
- 代理；
- 消息归一化；
- 公开频道解析；
- 公开频道订阅；
- Telegram 管理员通知。

限制：

- 私有邀请链接解析不支持；
- 编辑/删除/媒体组等场景不完整；
- Telegram 文件尚未进入统一 Attachment pipeline。

#### Mail

状态：**部分实现**。

已有：

- IMAP 收信；
- `UNSEEN` 检索；
- Seen 标记；
- IMAP 重连；
- Mail event；
- SMTP/adapter 发件；
- MailBridge；
- 自动回复；
- 发件账户选择；
- Telegram 管理员提醒。

限制：

- 没有 Web 邮箱管理；
- 附件没有统一文件分析；
- 邮件正文/附件的提示注入边界仍需统一。

### 5.2 LLM 与聊天

状态：**基础能力已实现，质量和控制面不足**。

已有：

- `StaticLLMProvider`；
- OpenAI-compatible provider；
- `urllib` 请求；
- Proxy；
- timeout；
- HTTP 错误分类；
- schema 检查；
- tool calls；
- usage 读取；
- reasoning effort；
- 多模型 registry；
- priority；
- priority groups；
- schedule；
- 多 API Key；
- failover；
- 动态运行时设置；
- 人格文件；
- 向量知识；
- 对话历史；
- 记忆抽取；
- Vision 转文字；
- 联网意图判断。

核心文件：

```text
plugins/bot_unified_runtime/llm/providers.py
plugins/bot_unified_runtime/llm/model_router.py
plugins/bot_unified_runtime/capabilities/chat.py
plugins/bot_unified_runtime/character/providers.py
plugins/bot_unified_runtime/character/vector_knowledge.py
plugins/bot_unified_runtime/runtime/question_intent.py
```

#### 当前聊天决策逻辑

现有意图大致包括：

- 明确命令；
- 现实问题；
- 时效问题；
- 实体百科问题；
- 世界观/领域知识问题；
- 普通知识问题；
- 天气；
- 音乐；
- Epic；
- 历史上的今天；
- 链接解析；
- 订阅；
- 文件；
- 普通聊天。

目标逻辑必须改成中央决策层统一裁决，不能让多个 matcher 各自决定回复。

### 5.3 网络搜索

状态：**部分实现，当前质量不足**。

现有：

- DuckDuckGo HTML；
- Bing HTML fallback；
- 同步搜索；
- 异步搜索；
- 多查询并发；
- URL 去重；
- 正文抓取；
- 域名初步排序；
- 垃圾结果过滤；
- 搜索审计标签。

核心文件：

```text
plugins/bot_unified_runtime/sources/web_search.py
plugins/bot_unified_runtime/capabilities/chat.py
```

问题：

- HTML 搜索易被反爬和版式变动影响；
- SEO/聚合/低质量来源污染；
- 没有正式 provider adapter；
- 没有可信来源策略；
- 没有搜索结果证据数据库；
- 没有完整 provider 选择配置；
- 没有搜索质量评测集；
- 没有稳定引用策略；
- 页面正文可能含提示注入。

目标：

- provider 可插拔；
- 正式 API 优先；
- HTML 只作为显式 fallback；
- 官方、机构、文档、媒体、社区分层；
- 查询、命中、过滤、抓取、来源、摘要可追踪；
- 外来页面永远是不可信数据。

### 5.4 人格、知识和记忆

状态：**部分到较完整**。

已有：

- Shorekeeper 人格文件；
- 人格文本加载；
- 角色表达规范；
- 知识文档；
- SQLite 向量知识；
- FAISS 索引；
- 关键词回退；
- 对话历史；
- 长期记忆；
- 记忆抽取；
- 共享群上下文；
- 人格 profile；
- 运行时上下文注入。

限制：

- 没有完整知识质量评测系统；
- 没有学习单元、测验、评分、反馈闭环；
- 现实事实、世界观事实和搜索事实仍需要中央证据策略；
- 没有统一的知识版本/回滚 API。

### 5.5 平台链接解析

状态：**平台很多，但深度不一致**。

当前 parser 覆盖的主要平台：

- Bilibili；
- B站会员购；
- 小红书；
- 抖音；
- YouTube；
- Twitter/X；
- 微博；
- Pixiv；
- Lofter；
- 无差别同人站；
- 米画师；
- 米游社；
- 森空岛；
- 库街区；
- 萌娘百科；
- 小黑盒；
- Steam；
- Epic；
- Telegram；
- 网易云；
- QQ音乐；
- 酷我；
- 酷狗；
- Apple Music；
- Spotify。

必须区分：

```text
deep
shallow
blocked
fallback
oEmbed only
login required
Cookie required
Playwright required
```

### 5.6 订阅

状态：**V2 结构存在，但 V1/V2 双轨未清理**。

已有 V2 组件：

- `SubscriptionStoreV2`；
- `SubscriptionScheduler`；
- `subscription_runtime_v2.py`；
- target；
- destination；
- cursor；
- seen items；
- baseline；
- lease；
- outbox；
- jitter；
- retry/backoff；
- platform throttle；
- social adapters；
- music adapter。

当前社交订阅 adapter：

- Bilibili；
- 小红书；
- YouTube；
- Twitter/X；
- Telegram 公开频道；
- Pixiv；
- 微博。

当前音乐订阅：

- 网易云默认实际抓取；
- 其他音乐 provider 多数仅目标解析，默认返回 unsupported。

严重问题：

```python
asyncio.run(adapter.resolve_target(...))
```

位置：

```text
plugins/bot_unified_runtime/capabilities/subscribe_v2.py:60-62
```

该代码可能在运行事件循环中调用 `asyncio.run()`，必须在订阅合并阶段修复。

### 5.7 天气

状态：**当前天气查询已实现，气象预警未实现**。

已有：

- NMC 数据源；
- 区县编码；
- 城市搜索；
- 当前天气；
- 温度；
- 体感；
- 湿度；
- 风力；
- 降水；
- 日出日落；
- 区县列表。

未实现：

- 官方预警；
- 预警等级；
- 多机器人、多群、多地区映射；
- 预警升级/解除；
- baseline；
- 去重；
- 区域缓存；
- 预警审计。

### 5.8 免费游戏

已有：

- Epic 每周免费游戏；
- Epic 公开促销接口；
- 命令和自然语言路由。

缺失：

- Steam 周免；
- iPad/App Store 免费游戏；
- 游戏周免订阅；
- 多平台统一结果。

### 5.9 点歌

已有：

- 网易云；
- Apple Music；
- 酷狗；
- QQ音乐；
- 酷我；
- Spotify 信息卡；
- 卡片；
- 语音；
- 音频文件；
- 链接；
- 音乐请求统计；
- 缓存。

缺失/限制：

- 汽水音乐；
- Spotify 搜索当前返回 `None`；
- 真正播放队列；
- 暂停/继续/上下曲；
- 真实平台榜单；
- 多平台音乐动态订阅。

### 5.10 文件处理

已有：

- QQ 管理员文件接收；
- 群上传；
- 私聊 offline file；
- `.py` 语法检查；
- `.py` 受限子进程运行；
- `.md/.txt/.json/.yaml/.yml/.toml/.csv` 文本确认；
- Markdown 生成；
- DOCX 导出；
- PPTX 导出；
- XLSX 导出；
- PDF 导出。

缺失/限制：

- `.doc/.xls/.ppt`；
- PDF 输入解析；
- PPTX 输入分析；
- XLSX 输入分析；
- Telegram/Mail 附件统一处理；
- 非 Python 代码分析；
- 强资源隔离；
- 网络隔离；
- 系统调用隔离；
- 独立代码文件生成/下载工作流。

---

## 6. 当前平台优先级

用户已明确平台优先级：

1. 哔哩哔哩；
2. 小红书；
3. 抖音；
4. 推特/X；
5. YouTube；
6. 森空岛；
7. 库街区；
8. 网易云音乐。

每个平台不得只写“已接入”，必须逐项标记：

```text
link_parse
detail
creator_profile
search
incremental_subscription
push_projection
login_state
rate_limit
error_mapping
fixture_tests
capability_status
```

平台状态建议统一为：

```text
full
parse_only
subscription_ready
auth_required
rate_limited
blocked
unsupported
degraded
```

---

## 7. Web UI 现状和后置规划

### 7.1 当前 Web UI 现状

当前没有：

- `frontend/`；
- Vue 工程；
- React 工程；
- `package.json`；
- 自定义 FastAPI API；
- Provider 管理页面；
- Playground 页面；
- 多模型盲测页面；
- Web Terminal；
- 监控图表页面。

唯一 HTML：

```text
plugins/bot_unified_runtime/output/card_render/templates/universal_card.html
```

它只是消息卡片模板。

### 7.2 TailAdmin Vue 决策

TailAdmin Vue 作为后置 UI 模板：

- 当前不安装；
- 当前不复制模板；
- 当前不开发页面；
- 先完成 API、DTO、权限、数据表、审计、联通检测、限流；
- 后续使用 TailAdmin 的导航、布局、表格、表单、图表作为壳；
- 项目自己的云母视觉 token 不和模板视觉强绑定。

### 7.3 后端 API 先行

建议控制面 API：

```text
GET    /admin/api/v1/health
GET    /admin/api/v1/commands
GET    /admin/api/v1/capabilities

GET    /admin/api/v1/providers
POST   /admin/api/v1/providers
PATCH  /admin/api/v1/providers/{provider_id}
DELETE /admin/api/v1/providers/{provider_id}
POST   /admin/api/v1/providers/{provider_id}/probe
GET    /admin/api/v1/providers/{provider_id}/balance

GET    /admin/api/v1/models
POST   /admin/api/v1/models
PATCH  /admin/api/v1/models/{model_id}
DELETE /admin/api/v1/models/{model_id}
POST   /admin/api/v1/models/order
POST   /admin/api/v1/models/{model_id}/probe

POST   /admin/api/v1/playground/sessions
POST   /admin/api/v1/playground/sessions/{session_id}/messages
POST   /admin/api/v1/experiments
POST   /admin/api/v1/experiments/{experiment_id}/runs
POST   /admin/api/v1/experiments/{experiment_id}/votes

GET    /admin/api/v1/usage/summary
GET    /admin/api/v1/usage/timeseries
GET    /admin/api/v1/usage/by-model
GET    /admin/api/v1/usage/by-provider
GET    /admin/api/v1/alerts
PATCH  /admin/api/v1/alerts/policy
```

---

## 8. Provider、模型和 Endpoint 设计

### 8.1 ProviderConfig

```text
provider_id
name
note
official_url
base_url
api_request_url
api_style
enabled
credential_ref
balance_adapter_id
balance_script_id
model_list_endpoint
website_probe_endpoint
model_probe_endpoint
chat_probe_policy
request_headers_template
request_query_template
request_body_template
url_join_policy
request_timeout_seconds
balance_poll_interval_seconds
model_poll_interval_seconds
created_at
updated_at
```

### 8.2 ModelConfig

```text
model_id
provider_id
menu_name
actual_model_id
model_aliases
enabled
is_default
context_window_tokens
request_context_budget_tokens
max_output_tokens
reasoning_level
custom_parameters
capabilities
input_price_per_million
cache_creation_price_per_million
cache_read_price_per_million
output_price_per_million
billing_multiplier
currency
pricing_source
priority
health_state
last_probe_at
created_at
updated_at
```

### 8.3 菜单显示名与真实模型 ID

必须始终分离：

```json
{
  "menu_name": "GPT-6 Astra",
  "actual_model_id": "gpt-6-astra"
}
```

规则：

- `menu_name` 可由用户改成中文、统一大小写、增加套餐标签；
- `actual_model_id` 原样保存；
- API 请求发送 `actual_model_id`；
- 排序、默认模型、盲测使用内部 `model_id`；
- 不能用 `menu_name` 作为唯一键；
- 不能自动 lower-case `actual_model_id`；
- 获取模型列表后，已存在模型不应因为菜单名被覆盖。

### 8.4 默认模型和模型列表

接口：

```text
GET  /admin/api/v1/providers/{provider_id}/models
POST /admin/api/v1/providers/{provider_id}/models/refresh
GET  /admin/api/v1/models
POST /admin/api/v1/providers/{provider_id}/default-model
```

列表来源：

1. 官方模型列表接口；
2. OpenAI-compatible `/models`；
3. 自定义 endpoint；
4. 手动登记；
5. 上次成功缓存。

失败时保留旧模型列表，不清空已知模型。

### 8.5 URL 规则

必须支持：

```text
https://example.com
https://example.com/v1
https://example.com/v1/chat/completions
/v1
v1
chat/completions
```

统一由 `EndpointResolver` 处理：

```text
resolve_base_url()
resolve_request_url(operation)
resolve_model_list_url()
resolve_probe_url()
```

不得在模块内散落字符串拼接。

---

## 9. API 协议和计费身份

### 9.1 协议类型

需要预留：

```text
OpenAI Chat Completions
OpenAI Responses
A 社 Cloud/厂商专用协议
Anthropic Messages 类协议
Custom JSON HTTP
```

“OpenAI-compatible”只说明请求协议兼容，不代表费用来自 OpenAI 官方。

### 9.2 Provider 身份

每次调用记录：

```text
provider_type: official / relay / self_hosted / aggregator
api_protocol: openai_chat / openai_responses / anthropic_messages / custom
upstream_vendor
billing_owner
endpoint_host
pricing_profile_id
balance_profile_id
usage_source
```

### 9.3 防止中转站和官方 API 混淆

规则：

- 中转站的 model ID 仅代表中转站路由；
- 中转站余额只代表中转账户；
- 中转站倍率、折扣、套餐优先于官方价格；
- 官方价格只能作为参考 baseline；
- 无明确价格来源时标记 `unpriced` 或 `estimated`；
- 官方和中转调用报表必须分开；
- 中转站返回的 Token 不一定等于上游账单 Token；
- 不能因为模型名字相同就合并价格。

### 9.4 汇率、折扣和套餐

必须分别建模：

```text
BalanceUnitProfile
- balance_currency
- display_currency
- balance_to_display_rate
- rate_source
- rate_effective_from
- rate_effective_to

RechargePromotion
- provider_id
- promotion_name
- paid_amount
- credited_amount
- effective_rate
- valid_from
- valid_to
- conditions

SubscriptionPlan
- provider_id
- plan_name
- plan_type: day/week/month/year/custom
- included_quota
- included_tokens
- overage_policy
- valid_from
- valid_to

PricingProfile
- provider_id
- model_id
- input_price
- cache_creation_price
- cache_read_price
- output_price
- billing_multiplier
- currency
- formula_version
- effective_from
- effective_to
- source
```

报表必须区分：

1. provider reported cost；
2. local estimated cost；
3. effective paid cost。

---

## 10. NewAPI 专用适配

用户提供的 NewAPI 示例只能作为 NewAPI adapter 合同，不能直接推广到所有供应商。

### 10.1 NewAPI 请求

```text
GET {baseUrl}/api/user/self
Content-Type: application/json
Authorization: Bearer {accessToken}
User-Agent: cc-switch/1.0
New-Api-User: {userId}
```

规则：

- `baseUrl` 是 NewAPI API 根地址；
- `accessToken` 使用 credential ref；
- `userId` 为 NewAPI 必需数字 UID；
- `New-Api-User` 只由 NewAPI adapter 自动添加；
- `quota`/`used_quota` 除数 `500000` 只属于 NewAPI balance profile；
- `USD` 不能自动解释为官方美元；
- `data.group` 映射为套餐名称；
- `quota + used_quota` 映射 total；
- 余额请求失败不得显示为 0。

### 10.2 NewAPI 状态

```text
success=true + data -> valid
success=false        -> provider_error/invalid
401/403              -> auth_required
429                  -> rate_limited
5xx                  -> retryable provider_error
缺失字段             -> invalid_response
```

---

## 11. Token、日志和费用

### 11.1 LLMCallRecord

```text
request_id
session_id
provider_id
model_id
actual_model_id
prompt_tokens
cache_creation_tokens
cache_read_tokens
completion_tokens
total_tokens
input_cost
cache_creation_cost
cache_read_cost
output_cost
total_cost
billing_multiplier
currency
latency_ms
status
error_kind
started_at
first_token_at
completed_at
source
```

### 11.2 关键时间指标

```text
first_token_latency_ms = first_token_at - started_at
total_latency_ms = completed_at - started_at
```

没有流式响应或没有首 Token 时间时标记 `unknown`，不能用总耗时伪造首 Token 延迟。

### 11.3 采集优先级

1. provider response usage；
2. 本项目结构化日志；
3. provider usage API；
4. extractor；
5. unknown。

当前已有：

```text
runtime/usage_monitor.py
runtime/pricing.py
sources/runtime_event_log.py
```

但当前日志文本聚合只能作为兼容层，最终需要迁移到结构化调用表。

### 11.4 查询时间窗

必须支持：

```text
24h
7d
30d
365d
all
```

维度：

```text
all
provider
model
session
```

返回字段至少包括：

```text
prompt_tokens
cache_creation_tokens
cache_read_tokens
completion_tokens
total_tokens
input_cost
cache_creation_cost
cache_read_cost
output_cost
total_cost
priced_calls
unpriced_calls
unknown_usage_calls
```

---

## 12. 三类联通检测

### 12.1 网站联通

验证：DNS、TLS、HTTP 状态、代理、耗时、证书安全。

```text
POST /admin/api/v1/providers/{id}/probes/website
```

### 12.2 模型联通

优先使用模型列表或 metadata 接口；没有时使用最小请求。

```text
POST /admin/api/v1/models/{id}/probes/connectivity
```

### 12.3 模型对话联通

固定低成本 Prompt：

```text
请只回复 CONNECTED
```

记录：

- 实际 model ID；
- HTTP 状态；
- 响应 schema；
- Token；
- 费用；
- 耗时；
- 错误类型；
- retry/failover 行为。

检测默认不进入聊天历史，不触发记忆，不触发工具调用。

---

## 13. Extractor 和安全边界

用户提供的脚本格式是对象字面量：

```text
({ request: {...}, extractor: function(response) {...} })
```

它支持：

- `isValid`；
- `invalidMessage`；
- `remaining`；
- `unit`；
- `planName`；
- `total`；
- `used`；
- `extra`。

设计决策：

- 默认支持声明式 JSONPath/JMESPath/算术映射；
- 复杂站点才允许 ES2020 extractor；
- 不使用 Python `eval`；
- 不暴露 Node `process`；
- 不允许文件、网络、模块加载、子进程、动态 import；
- 输入 response 为只读 JSON 副本；
- credential 只通过不可读取原文的代理使用；
- 限制 CPU 时间、内存、输出大小、嵌套深度；
- 记录脚本版本、hash、耗时、字段、错误；
- 测试通过后才允许启用；
- 新版本失败时自动回滚旧版本。

提取器代码和脚本说明尚未收到，以下内容暂不能最终定稿：

- TokenPlan endpoint；
- Sub2API endpoint；
- 自建站响应字段；
- 各站点轮询限制；
- “消耗进”等自定义指标语义；
- 网站密码和 API Token 是否共享 credential ref；
- extractor 是否支持跨字段复杂计算。

---

## 14. SakuraFrp 穿透、低带宽和公网

用户实际条件：

```text
SakuraFrp
每日流量额度：3GB
隧道最高带宽：10Mbps
无公网 IPv4
无公网 IPv6
内网穿透可用
```

### 14.1 是否可实现公网访问

可实现，但反向代理不会凭空产生公网可达性，必须有：

- SakuraFrp 公网节点；
- 自有公网 VPS + frp；
- Cloudflare Tunnel 等出站连接中继；
- 或其他可访问的公网边缘节点。

公网入口不能直连本地 Bot 8080。只能暴露独立 Control Plane API。

### 14.2 硬预算

```text
daily_traffic_budget_bytes = 3 * 1024 * 1024 * 1024
user_declared_bandwidth_mbps = 10
control_plane_default_cap_mbps = 2
warning_thresholds = 50%, 75%, 90%, 100%
```

注意：SakuraFrp 的底层 `bandwidth_limit` 配置单位不能和用户看到的 Mbps 混用。实现时必须保存用户声明值、底层解析值和单位来源。

### 14.3 低带宽控制

默认：

- 单响应 1MiB；
- 日志尾部 200 行；
- 日志流关闭或每分钟 256KiB；
- playground 非流式；
- playground 并发 1；
- 文件上传不经过隧道；
- 文件任务默认不走公网；
- 余额和模型列表使用本地缓存；
- 图表使用服务端聚合、分页和时间桶；
- 接近 90% 关闭非必要自动刷新；
- 达到 100% 拒绝非必要传输。

### 14.4 本地计量

新增设计：

```text
TunnelTrafficMeter
- tunnel_id
- direction
- bytes
- request_id
- endpoint
- content_type
- started_at
- completed_at
- source
```

本地估算与 SakuraFrp 面板使用量必须分开显示，不能把本地估算伪装成账单精确值。

### 14.5 断路器

```text
NORMAL
  ↓ 50%
WATCH
  ↓ 75%
THROTTLED
  ↓ 90%
EMERGENCY
  ↓ 100%
BLOCK_NONESSENTIAL
```

断路器只影响穿透控制面，不影响本地 Bot。

---

## 15. 公网认证和极高自由度权限

支持组合：

- Bearer Token；
- 用户名密码；
- TOTP/Aegis；
- QR 设备配对；
- 反向代理认证头；
- 未来 OIDC。

公网强制：

- TLS；
- 登录限速；
- CSRF；
- Secure/HttpOnly/SameSite Cookie；
- Token 轮换；
- 设备撤销；
- 审计；
- 危险操作二次确认；
- 凭据不出现在响应、日志和 URL。

权限流：

```text
功能总开关
→ Bot 实例
→ adapter
→ 群/私聊
→ 用户角色
→ 时间段
→ 内容风险等级
→ 配额
→ 审批
```

默认：

- 代码执行关闭；
- 网络访问关闭；
- 系统调用关闭；
- QQ 空间只草稿；
- 日记只脱敏摘要；
- 表情包自动发送关闭；
- 气象预警按群/地区开启；
- 戳一戳使用轻量规则，不调用 LLM。

---

## 16. 数据库、迁移和订阅合并

### 16.1 当前存储

当前存在多个 SQLite 仓库：

- audit；
- conversation history；
- memory；
- vector knowledge；
- rate limit；
- sender queue；
- receipts；
- subscriptions；
- music analytics；
- parse history；
- intent telemetry；
- diagnostics。

问题：

- 迁移分散；
- schema owner 不统一；
- 用量和账单没有统一事实表；
- API 未来需要跨库读取；
- 旧订阅 V1/V2 双轨。

### 16.2 订阅合并

必须执行：

1. 冻结旧入口；
2. 修复 `asyncio.run`；
3. 只读校验旧库；
4. 备份且禁止覆盖旧备份；
5. 当前实现重命名为正式 subscription 模块；
6. 删除旧 store/watcher/scheduler/注册入口；
7. 保留有期限 migration shim；
8. 配置键 `BOT_SUBSCRIBE_*` 保持兼容；
9. 校验 target、destination、cursor、seen、outbox；
10. 用户不可见 V1/V2 字样。

---

## 17. 命令、运维和配置

### 17.1 维护命令

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task docs-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task plugin-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task verify"
```

### 17.2 当前命令透明化缺口

当前命令存在于：

- `plugins/bot_unified_runtime/__init__.py`；
- `capabilities/echo.py`；
- `capabilities/runtime_admin.py`；
- `runtime/aliases.py`；
- `COMMANDS.md`；
- `docs/route-matrix.md`。

缺少：

- 统一 catalog；
- 参数 schema；
- 权限矩阵；
- 当前启用状态；
- 依赖状态；
- 失败原因；
- 自动生成文档。

目标命令：

```text
/bot commands
/bot command <name>
/bot capability <name>
/bot status
```

### 17.3 配置策略

当前 `Config` 大约 305 个字段，主要覆盖：

- runtime；
- persona；
- roles；
- group policy；
- LLM；
- models；
- pricing；
- usage；
- weather；
- today history；
- content parser；
- music；
- subscription；
- mail；
- vision；
- meme；
- download；
- audit；
- diagnostics；
- sender。

新增控制面配置不能全部继续塞进 `.env`。建议：

```text
.env              启动级、机密引用和部署环境
control_plane DB 供应商、模型、排序、告警、权限、实验
settings store    可热更运行参数
runtime data      日志、缓存、任务、快照
```

---

## 18. 风险登记

### P0

1. 订阅新增路径使用 `asyncio.run`，可能在事件循环中失败。
2. 多入口直接处理和直接发送，可能产生重复回复、冲突和 debug 困难。
3. 公网 API 若先于认证/审计上线，会暴露模型配置、凭据或命令执行面。
4. 文件代码执行没有强隔离，不能直接开放给公网。

### P1

1. Token/费用依赖日志文本，无法作为长期账单事实源。
2. 余额单位和中转站计费与官方计费容易混淆。
3. 测试临时目录权限未稳定解决。
4. V1/V2 订阅双轨增加迁移和重复入口风险。
5. 搜索 HTML 质量不足。
6. Telegram/Mail 文件没有统一 Attachment pipeline。

### P2

1. 长尾平台只有 parser，没有订阅。
2. 音乐订阅和真实榜单不完整。
3. 命令帮助和运行状态不透明。
4. 没有学习内容和评测闭环。
5. 没有 Web UI。
6. 6 个 Ruff 问题。

---

## 19. 事实与设计边界

以下是源码事实：

- 当前有 NoneBot、OneBot、Telegram、Mail、LLM、parser、部分 subscription、文件导出、usage monitor。
- 当前没有独立 Web UI、正式 Control Plane API、统一余额 adapter、盲测、强沙箱。
- 当前测试不是全绿；Ruff 有 6 项问题。
- 当前工作树有大量未提交修改和删除。

以下是已经确定但尚未编码的设计：

- TailAdmin Vue 后置；
- 公网反向代理/穿透；
- 10Mbps/3GB SakuraFrp 硬预算；
- 中央决策层；
- 统一发送网关；
- Provider/Model/Balance/Usage API；
- NewAPI 专用 adapter；
- extractor 沙箱；
- QQ/Telegram/Mail 预警；
- 文件 worker；
- 气象预警；
- 日记草稿和人工审批；
- 戳一戳 reaction；
- 表情包端到端验证。

以下必须等待用户资料：

- TokenPlan、Sub2API、自建站余额接口；
- 各站点 request headers/body；
- extractor 脚本真实规则；
- 轮询限制；
- 自定义指标语义；
- “思考等级”各供应商映射之外的特殊字段；
- 具体中继站计费和优惠规则。

---

## 20. 执行计划

### 第一个工作批次

1. 修复 Ruff 6 项问题。
2. 修复测试临时目录。
3. 写 `CommandCatalog` 失败测试。
4. 写 CentralDecisionEngine 失败测试。
5. 写 UnifiedDeliveryGateway 失败测试。
6. 修复订阅 `asyncio.run`。
7. 建立数据库 owner 清单。
8. 不启动 Web UI。

### 第二个工作批次

1. `SearchProvider` 正式 API adapter。
2. 搜索来源策略。
3. 搜索审计。
4. 搜索 fixture。
5. Chat 引用和事实边界。

### 第三个工作批次

1. ProviderConfig/ModelConfig repository。
2. URL resolver。
3. Model list。
4. default model。
5. probe。
6. 命令/API 统一。

### 第四个工作批次

1. LLMCallRecord。
2. Token 细分。
3. 费用公式。
4. 汇率/折扣/套餐。
5. BalanceAdapter。
6. QQ/Telegram/Mail alert。

### 第五个工作批次

1. 订阅合并。
2. 优先平台补全。
3. 文件 Attachment。
4. 静态分析。
5. worker 沙箱。
6. 气象预警。
7. 表情包验证。

### 最后工作批次

1. TailAdmin Vue 壳层。
2. 认证与权限页面。
3. Provider/Model 页面。
4. Playground/盲测页面。
5. Usage/Balance/Alert 页面。
6. Subscription 页面。
7. File/Worker 页面。
8. 低带宽模式和 SakuraFrp 流量看板。

---

## 21. 接手者第一天检查表

```powershell
git status --short --branch
Get-Content README.md
Get-Content COMMANDS.md
Get-Content docs/control-plane-provider-and-usage-requirements-2026-09-05.md
Get-Content docs/project-audit-and-modernization-roadmap-2026-09-05.md
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task docs-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task plugin-check"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
```

然后阅读：

```text
plugins/bot_unified_runtime/__init__.py
plugins/bot_unified_runtime/runtime/pipeline.py
plugins/bot_unified_runtime/runtime/base_router.py
plugins/bot_unified_runtime/capabilities/chat.py
plugins/bot_unified_runtime/llm/model_router.py
plugins/bot_unified_runtime/llm/providers.py
plugins/bot_unified_runtime/sources/web_search.py
plugins/bot_unified_runtime/sources/subscription_runtime_v2.py
plugins/bot_unified_runtime/sources/subscription_scheduler.py
plugins/bot_unified_runtime/sources/subscription_store_v2.py
plugins/bot_unified_runtime/capabilities/file_exchange.py
plugins/bot_unified_runtime/runtime/usage_monitor.py
```

---

## 22. 最终交接判断

不要推倒重写现有项目。现有 Runtime、contracts、pipeline、sender、audit、LLM router、parser 和 subscription store 都可以成为后续基础。

但是从现在开始不能继续采用：

```text
在 __init__.py 增加 matcher
+ 在 .env 增加配置
+ 在 capability 内直接调用 bot.send()
+ 在日志里临时拼统计
```

后续所有重要功能必须遵循：

```text
领域模型
→ repository
→ service
→ 中央决策层
→ 能力执行器
→ 统一出站网关
→ API
→ 测试
→ 文档
→ 最后 UI
```

最重要的三条原则：

1. **所有事件一个中央决策入口。**
2. **所有出站一个统一发送出口。**
3. **所有控制能力先有后端 API，再有 TailAdmin Vue UI。**

---
---
## 23. Config 字段完整清单

plugins/bot_unified_runtime/config.py 当前由字段扫描发现 305 个配置字段。以下是字段名清单，具体默认值、解析器和校验逻辑以源码为准：

```text
bot_admin_user_ids
bot_api_key_aiprc
bot_api_key_hcn
bot_api_key_qianqianye
bot_api_key_umi_group1
bot_api_key_umi_group2
bot_audit_db_path
bot_audit_enabled
bot_audit_log_file
bot_audit_log_max_bytes
bot_audit_max_items
bot_blocked_user_ids
bot_card_asset_dir
bot_card_cache_max_bytes
bot_card_render_backend
bot_card_render_dir
bot_card_render_enabled
bot_card_ui_scale
bot_chat_api_key
bot_chat_base_url
bot_chat_enabled
bot_chat_failover_max_seconds
bot_chat_fast_context_budget
bot_chat_fast_disable_vector_knowledge
bot_chat_fast_embedding_timeout_seconds
bot_chat_fast_max_candidates
bot_chat_fast_max_tokens
bot_chat_fast_mode
bot_chat_fast_skip_web_pages
bot_chat_fast_timeout_seconds
bot_chat_fast_web_max_queries
bot_chat_max_tokens
bot_chat_model
bot_chat_provider
bot_chat_reasoning_effort
bot_chat_temperature
bot_chat_timeout_seconds
bot_content_parse_enabled
bot_content_parse_platforms
bot_content_video_auto_send
bot_cookies_file
bot_credential_check_enabled
bot_credential_check_interval_hours
bot_credential_probe_timeout_seconds
bot_credential_probe_urls
bot_credential_warn_days
bot_credentials_file
bot_diagnostics_db_path
bot_diagnostics_enabled
bot_diagnostics_max_items
bot_download_cache_max_age_days
bot_download_cache_max_bytes
bot_download_dir
bot_download_max_bytes
bot_download_max_height
bot_download_proxy
bot_download_timeout_seconds
bot_embedding_api_key
bot_embedding_base_url
bot_embedding_dimensions
bot_embedding_enabled
bot_embedding_local_api_key
bot_embedding_local_base_url
bot_embedding_local_enabled
bot_embedding_local_models
bot_embedding_local_timeout_seconds
bot_embedding_model
bot_embedding_timeout_seconds
bot_emotion_enabled
bot_emotion_max_signals
bot_enterprise_user_ids
bot_epic_enabled
bot_fetch_playwright_enabled
bot_fetch_timeout_seconds
bot_glossary_files
bot_glossary_max_chars
bot_glossary_max_entries
bot_group_black1
bot_group_black2
bot_group_chat_auto_reply_enabled
bot_group_chat_auto_reply_probability
bot_group_digest_enabled
bot_group_digest_llm_enabled
bot_group_digest_llm_ttl_seconds
bot_group_digest_max_chars
bot_group_digest_max_turns
bot_group_proactive_cooldown_seconds
bot_group_proactive_max_replies_per_hour
bot_group_white1
bot_group_white2
bot_gscore_bot_id
bot_gscore_bot_self_id
bot_gscore_enabled
bot_gscore_host
bot_gscore_max_retry
bot_gscore_port
bot_gscore_ws_token
bot_help_card_color
bot_history_db_path
bot_history_enabled
bot_history_max_chars
bot_history_max_items
bot_history_max_turns
bot_holidays_file
bot_knowledge_chunk_chars
bot_knowledge_db_path
bot_knowledge_files
bot_knowledge_max_chunks
bot_knowledge_top_k
bot_mail_auto_reply_enabled
bot_mail_bridge_enabled
bot_mail_bridge_state_file
bot_mail_notify_preview_chars
bot_mail_notify_telegram_enabled
bot_mail_sender_aliases
bot_media_analyze_enabled
bot_meme_api_base_url
bot_meme_api_enabled
bot_meme_api_output_dir
bot_meme_api_timeout_seconds
bot_meme_cache_max_bytes
bot_meme_command_enabled
bot_meme_library_cooldown_seconds
bot_meme_library_db_path
bot_meme_library_dir
bot_meme_library_enabled
bot_meme_library_group_allowlist
bot_meme_library_group_denylist
bot_meme_library_max_age_days
bot_meme_library_max_file_bytes
bot_meme_library_max_files
bot_meme_library_nsfw_delete
bot_meme_library_nsfw_max
bot_meme_library_prefer
bot_meme_library_proxy
bot_meme_library_vlm_api_key
bot_meme_library_vlm_base_url
bot_meme_library_vlm_enabled
bot_meme_library_vlm_model
bot_meme_library_vlm_preset
bot_meme_library_vlm_timeout_seconds
bot_meme_search_cache_seconds
bot_meme_search_enabled
bot_meme_search_timeout_seconds
bot_memory_db_path
bot_memory_enabled
bot_memory_extract_enabled
bot_memory_max_chars
bot_memory_max_items
bot_model_auto_route
bot_model_presets
bot_model_prices
bot_model_priority_groups
bot_model_registry
bot_model_schedule
bot_music_analytics_db_path
bot_music_analytics_enabled
bot_music_analytics_retention_days
bot_music_cache_max_bytes
bot_music_chart_enabled
bot_music_chart_poll_interval_seconds
bot_music_chart_sources
bot_music_enabled
bot_music_platforms
bot_natural_command_enabled
bot_parse_history_db_path
bot_parse_history_enabled
bot_parse_history_max_items
bot_persona_action_brackets
bot_persona_alt_profiles
bot_persona_avatar_url
bot_persona_display_name
bot_persona_files
bot_persona_nicknames
bot_persona_profile_id
bot_persona_version
bot_quiet_hours_bypass_roles
bot_quiet_hours_enabled
bot_quiet_hours_end
bot_quiet_hours_session_types
bot_quiet_hours_start
bot_quiet_hours_timezone
bot_rate_limit_bypass_roles
bot_rate_limit_chat_global_max_requests
bot_rate_limit_chat_sender_max_requests
bot_rate_limit_chat_session_max_requests
bot_rate_limit_db_path
bot_rate_limit_enabled
bot_rate_limit_target_min_interval_seconds
bot_rate_limit_window_seconds
bot_receipts_db_path
bot_receipts_enabled
bot_receipts_max_items
bot_render_forward_max_nodes
bot_render_forward_min_chars
bot_render_forward_node_chars
bot_reply_deep_help_context_budget
bot_reply_default_context_budget
bot_reply_detail
bot_reply_group_context_budget
bot_reply_group_max_messages
bot_reply_max_chars_per_message
bot_reply_private_deep_help_max_messages
bot_reply_private_default_max_messages
bot_reply_private_support_max_messages
bot_reply_risk_max_messages
bot_reply_support_context_budget
bot_request_budget_seconds
bot_runtime_admin_prefix
bot_runtime_alias_enabled
bot_runtime_data_dir
bot_runtime_default_persona
bot_runtime_enabled
bot_runtime_group_command_prefix
bot_runtime_instance
bot_runtime_log_file
bot_runtime_log_level
bot_runtime_log_max_bytes
bot_runtime_persona_nickname
bot_runtime_persona_nicknames
bot_runtime_settings_dir
bot_runtime_settings_file
bot_send_queue_db_path
bot_send_queue_enabled
bot_send_queue_max_attempts
bot_send_queue_max_items
bot_send_queue_retry_base_seconds
bot_send_queue_retry_max_seconds
bot_send_queue_worker_batch_size
bot_send_queue_worker_enabled
bot_send_queue_worker_interval_seconds
bot_share_enabled
bot_share_groups
bot_share_read_only
bot_shared_export_enabled
bot_shared_export_include_private
bot_shared_export_max_chars
bot_shared_group_context_enabled
bot_subscribe_card_enabled
bot_subscribe_db_path
bot_subscribe_digest_hour
bot_subscribe_digest_minute
bot_subscribe_enabled
bot_subscribe_global_concurrency
bot_subscribe_jitter_ratio
bot_subscribe_lease_seconds
bot_subscribe_live_poll_seconds
bot_subscribe_max_items_per_tick
bot_subscribe_min_interval_seconds
bot_subscribe_outbox_interval_seconds
bot_subscribe_platform_concurrency
bot_subscribe_playwright_poll_seconds
bot_subscribe_poll_interval_seconds
bot_subscribe_retry_base_seconds
bot_subscribe_retry_cap_seconds
bot_telegram_admin_chat_ids
bot_telegram_admin_user_ids
bot_temporal_enabled
bot_timezone
bot_today_history_cache_file
bot_today_history_enabled
bot_today_history_push_file
bot_tone_directness
bot_tone_message_count_limit
bot_tone_mode
bot_tone_voice
bot_tone_warmth
bot_transport_timeout_seconds
bot_trend_enabled
bot_trend_files
bot_trend_max_age_days
bot_trend_max_chars
bot_trend_max_notes
bot_trusted_user_ids
bot_usage_alert_daily_cost_yuan
bot_usage_alert_input_tokens
bot_usage_alert_output_tokens
bot_usage_monitor_enabled
bot_usage_report_hours
bot_usage_report_state_file
bot_user_profiles_file
bot_vision_enabled
bot_vision_max_chars
bot_vision_max_images
bot_vision_mode
bot_vision_model_registry
bot_vision_reply_probability
bot_vision_timeout_seconds
bot_weather_cache_seconds
bot_weather_enabled
bot_weather_latitude
bot_weather_longitude
bot_weather_query_enabled
bot_weather_timeout_seconds
bot_web_classifier_shadow_enabled
bot_web_intent_telemetry_db_path
bot_web_intent_telemetry_enabled
bot_web_intent_telemetry_max_items
bot_web_search_admin_notice
bot_web_search_enabled
bot_web_search_max_results
bot_web_search_timeout_seconds
bot_wiki_enabled
bot_wiki_lang
translated
```

注意：这不是 `.env` 的密钥值清单，不包含任何实际 Key、Cookie、Token 或密码。
.env/.env.example/.env.prod 的键名可以通过脱敏方式对照，真实值不得写入交接报告。
