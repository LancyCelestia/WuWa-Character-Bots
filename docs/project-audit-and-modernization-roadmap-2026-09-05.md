# ChatBot 项目审计与现代化路线图

> 审计日期：2026-09-05  
> 审计范围：当前源码工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`。  
> 本报告反映当前工作树，不等同于 Git 历史标签 `v0.0.1-alpha.1`；工作树有大量未提交变更和删除。  
> 密钥、Cookie、Token、邮件状态、外部 Runtime 数据均未读取或写入本报告。

## 1. 执行结论

当前项目是一个以后端为中心的 NoneBot2 统一运行时：已具备 QQ/Telegram/Mail 接入、人格聊天、向量知识、部分网络搜索、多平台链接解析、部分订阅推送、天气、Epic 周免、文件导出、审计与用量阈值通知。

它不是完整的多平台生态，也不是 Web 管理系统：没有独立前端、没有自定义 FastAPI API 路由、没有供应商余额采集、没有浏览器游乐场、没有多模型盲测、没有 Web 终端、没有监控图表中心。当前唯一 HTML 是消息卡片模板，不是管理页面。

后续工作的正确顺序是：

1. 稳定机器人主链与测试基线。
2. 统一并补齐后端领域模型和 API 契约。
3. 优化聊天与可信搜索。
4. 清理订阅双轨并优先补齐常用平台。
5. 建立可审计的模型、用量、费用与通知后端。
6. 扩展跨平台文件处理并建立真正受限的执行工作器。
7. 最后再建设外部 Web UI。

这符合“先保证 Bot 正常交互、人格、知识库和插件可用，再把控制面通过 API 暴露给 UI”的优先级。

## 2. 审计方法与验证状态

### 2.1 已检查内容

- 根配置：`pyproject.toml`、`.env`、`.env.example`、`.env.prod`、`bot.py`。
- 现存 README、命令、接入、配置、交接、设计、人格 Markdown 文档，共 26 个。
- 生产插件 `plugins/bot_unified_runtime/`：capabilities、runtime、sources/parsers、sources/subscriptions、llm、character、contracts、sender、audit、output。
- 测试目录和维护脚本。
- Python AST 静态解析：222 个 Python 文件，0 个语法错误。

### 2.2 验证结果

| 检查 | 结果 | 说明 |
|---|---|---|
| Python AST | 通过 | 222 个 Python 文件可解析，未发现语法错误。 |
| `docs-check` | 通过 | 文档和运行入口最小约束有效。 |
| `plugin-check` | 通过 | 本地插件发现合同有效，识别 `bot_unified_runtime`。 |
| `runtime-layout` | 通过 | Runtime/源码边界正确，源码无 bytecode。 |
| pytest | 未形成全绿结论 | 一轮收集 279 项，240 passed、39 errors；错误集中在临时目录权限。改 basetemp 的重跑无进展后中断。 |
| Ruff | 不通过 | 当前有 6 个 lint 问题，见第 8 节。 |

### 2.3 当前技术边界

运行数据、数据库、日志、Cookie、媒体缓存和虚拟环境按工作区规则位于外部 `ChatBot_Runtime`。本次没有递归扫描、迁移、删除或压缩这些数据。

## 3. 当前架构概览

```text
bot.py
└── NoneBot 初始化
    ├── OneBot V11 / QQ / NapCat
    ├── Telegram
    ├── Mail
    └── plugins/bot_unified_runtime
        ├── capabilities/            聊天、解析、点歌、订阅、天气、文件等入口
        ├── runtime/                 路由、策略、设置、用量、告警
        ├── sources/parsers/         多平台链接解析
        ├── sources/subscriptions/   订阅增量抓取 adapter
        ├── llm/                     OpenAI-compatible provider 与模型路由
        ├── character/               人格、历史、记忆、向量知识
        ├── sender/                  队列、回执、传输
        ├── audit/                   审计
        └── output/card_render/      HTML 到 PNG 消息卡片
```

主要装配位置：

- `bot.py:126-148`：注册 OneBot V11、Telegram、插件内 Mail adapter。
- `pyproject.toml:45-71`：本地插件目录、NoneBot adapter/plugin 配置。
- `plugins/bot_unified_runtime/__init__.py:109-117`：声明支持 OneBot、Console、Mail、Telegram。
- `plugins/bot_unified_runtime/__init__.py:2040-2436`：消息 matcher 和能力路由。

## 4. 平台生态接入审计

完成度必须区分五类能力：通信适配、链接解析、搜索、增量订阅抓取、消息推送。存在链接解析不等于完成了一个平台的完整接入。

### 4.1 通信平台

| 平台 | 状态 | 现有能力 | 欠缺 |
|---|---|---|---|
| QQ | 部分实现 | OneBot V11/NapCat 消息、文件、发送队列 | 强依赖外部 NapCat；未形成 QQ 空间、戳一戳等完整扩展能力。 |
| Telegram | 部分实现 | adapter、消息收发、公开频道解析/订阅 | 私有邀请链接不支持；编辑、删除、媒体分组等仍有缺口。 |
| Mail | 部分实现 | IMAP 收信、Seen 标记、重连、SMTP 发件、自动回复、Telegram 管理员提醒 | 没有 Web 邮件管理和统一附件分析链路。 |

关键文件：`bot.py`、`plugins/bot_unified_runtime/mail_adapter.py`、`plugins/bot_unified_runtime/mail_bridge.py`。

### 4.2 社交平台

链接解析注册表：`sources/parsers/__init__.py:151-423`。  
社交订阅注册：`sources/subscriptions/social_v2.py:491-1178`。

| 平台 | 链接解析 | 订阅增量/推送 | 当前判定 |
|---|---:|---:|---|
| 哔哩哔哩 | 有 | 有 | 部分实现 |
| 小红书 | 有 | 有 | 部分实现 |
| 抖音 | 有 | 无 | 部分实现 |
| 推特/X | 有 | 有，依赖 Cookie/GraphQL | 部分实现 |
| YouTube | 有 | 有，主要 Atom Feed | 部分实现 |
| Pixiv | 有 | 有 | 部分实现 |
| 微博 | 有 | 有 | 部分实现 |
| 萌娘百科 | 有 | 无 | 部分实现 |
| 米画师 | 有 | 无 | 部分实现 |
| 无差别同人站 | 有 | 无 | 部分实现 |
| Lofter | 有 | 无 | 部分实现 |
| 森空岛 | 有 | 无 | 部分实现 |
| 库街区 | 有 | 无 | 部分实现 |
| 米游社 | 有 | 无 | 部分实现 |

用户已更正平台名称，后续统一使用：

- **森空岛**：当前代码 ID 为 `skland`。
- **库街区**：当前代码 ID 为 `kurobbs`。
- 不再使用此前语音转写形成的“深空岛”“酷街区”。

当前真正注册了社交订阅 adapter 的只有：Bilibili、小红书、YouTube、Twitter/X、Telegram 公开频道、Pixiv、微博。森空岛和库街区当前只有解析，不能声明为可订阅平台。

### 4.3 音乐平台

点歌搜索提供方在 `sources/parsers/__init__.py:425-433`：网易云、Apple Music、酷狗、QQ音乐、酷我、Spotify。

| 平台 | 解析 | 点歌搜索 | 默认动态订阅抓取 | 当前判定 |
|---|---:|---:|---:|---|
| 网易云音乐 | 有 | 有 | 有 | 部分实现 |
| QQ音乐 | 有 | 有 | 无，默认 unsupported | 部分实现 |
| 酷我音乐 | 有 | 有 | 无，默认 unsupported | 部分实现 |
| 酷狗音乐 | 有 | 有 | 无，默认 unsupported | 部分实现 |
| Apple Music | 有 | 有 | 无，默认 unsupported | 部分实现 |
| Spotify | 有，主要 oEmbed 信息卡 | 当前搜索返回 `None` | 无，默认 unsupported | 部分实现 |
| 汽水音乐 | 无 | 无 | 无 | 完全缺失 |

`music_v2.py:67-140` 显示：未注入专用 client 时，实际默认抓取只实现了网易云；其他音乐 provider 返回 `unsupported`。

### 4.4 游戏与其他平台

| 需求 | 状态 | 说明 |
|---|---|---|
| B站会员购 | 部分实现 | 有商品链接解析，不是完整会员购业务。 |
| 小黑盒 | 部分实现 | 有社区链接解析，部分场景浅层。 |
| NGA | 完全缺失 | 没有独立 parser、API client、搜索或订阅。 |
| Steam | 部分实现 | 商店、社区、市场、个人资料链接解析；没有周免查询。 |
| Epic Games | 部分实现 | 有 Epic 每周免费游戏查询。 |
| iPad/App Store 免费游戏 | 完全缺失 | 没有数据源、命令、路由或订阅。 |
## 5. 核心业务能力审计

### 5.1 历史上的今天：部分实现

已有：百度百科公开接口、JSON 缓存、`历史上的今天` 查询、每日推送、APScheduler。

文件：

- `sources/today_history.py`
- `capabilities/today_history.py`
- `__init__.py:855-975`

欠缺：不是以结构化事件数据库为主；事件仅稳定保存 year/title，缺乏可靠梗概、人物、地点、来源与原文链接字段；缓存文件不适合复杂查询和审计。

### 5.2 免费游戏：部分实现

Epic 已实现：`sources/epicfree.py`、`capabilities/epic.py`。  
Steam 周免和 iPad/App Store 免费游戏完全缺失。

### 5.3 点歌：部分实现

已有：六平台搜索顺序、卡片、链接、语音、音频文件、下载、请求统计。  
欠缺：汽水音乐；Spotify 搜索；播放队列；播放状态；真正的跨平台播放体验；实际平台榜单源。

相关文件：

- `capabilities/music.py`
- `sources/parsers/platforms_music.py`
- `sources/music_request_store.py`

### 5.4 订阅推送：部分实现

已有：SQLite store、游标、baseline、outbox、租约、并发节流、重试、抖动、社交 adapter、QQ/Telegram 等传输投递。

关键风险：`capabilities/subscribe_v2.py:60-62` 在同步 capability 内调用 `asyncio.run(adapter.resolve_target(...))`，但该路径从 NoneBot 异步 handler 进入。运行中的事件循环会触发 `asyncio.run() cannot be called from a running event loop`，可能使新增订阅失效。

### 5.5 天气：已完成，但还不是气象预警系统

`capabilities/weather.py` 与 `sources/nmc_weather.py` 已支持 NMC 区县查询、天气、区县列表和失败降级。

限制：主要是中国当前天气，不是完整预报/预警系统；当前 NMC 请求关闭 TLS 校验，应在后续气象预警改造中统一处理。

### 5.6 基础聊天：已完成但网络搜索质量不足

已有：人格、知识库、记忆、历史、多模型故障转移、视觉转文本、按意图联网、DDG→Bing HTML 抓取、正文抽取。

关键文件：

- `capabilities/chat.py`
- `sources/web_search.py`
- `llm/model_router.py`
- `llm/providers.py`

当前搜索问题：HTML 搜索结果易被反爬、版式变动、SEO 污染、聚合站和无关词条影响；项目没有来源质量策略、可信域名策略、结果证据结构化、搜索 API 可观测性或检索评估集。

### 5.7 文件处理：部分实现

已有：QQ 管理员收文件；`.py` 语法/受限执行；文本型文件确认；LLM 生成 Markdown 后导出 `md/docx/pptx/xlsx/pdf`。

文件：`capabilities/file_exchange.py`、`__init__.py:2082-2209`。

欠缺：`.doc/.xls/.ppt`；通用 PDF/PPTX/XLSX 内容读取与总结；非 Python 代码分析；Telegram/Mail 附件统一流；真正隔离的执行工作器；生成独立代码文件的产品化入口。

## 6. Web UI 与控制面审计

没有前端工程、Web 路由或自定义 FastAPI API。唯一 HTML：

`plugins/bot_unified_runtime/output/card_render/templates/universal_card.html`

它仅用于消息卡片渲染。

| 用户目标 | 状态 | 现有可复用基础 |
|---|---|---|
| API 供应商管理 | 完全缺失 | `.env`/运行时模型注册表可作为迁移来源。 |
| LLM 登记管理 | 部分实现 | `/bot runtime model`、注册表、URL、模型名、effort、priority。 |
| LLM 排序 | 部分实现 | `priority`、时段 priority group、failover 顺序；没有 UI。 |
| 供应商余额 | 完全缺失 | 没有余额 API adapter、数据模型或页面。 |
| Web 游乐场 | 部分实现 | 有 Console 入口；没有浏览器聊天。 |
| 多 LLM 盲测 | 完全缺失 | 现有 failover 不是并行比较。 |
| Web CMD 控制台 | 完全缺失 | 有 PowerShell 和 Console，不可安全地直接暴露给 Web。 |
| 监测中心 | 部分实现 | 有日志用量聚合和 QQ 报告，无查询 API/图表。 |
| 费用预警 | 部分实现 | 有 QQ 管理员告警；未覆盖 Telegram/Mail，且无 Web 配置面板。 |

### 6.1 LLM 后端可复用能力

`llm/model_router.py` 已支持：

- 模型注册表；
- 模型预设；
- 手动选择；
- priority；
- 时段 priority groups；
- reasoning effort；
- 多 API Key；
- failover；
- 动态运行时注册表。

`capabilities/runtime_admin.py` 和 `runtime/settings.py` 已提供命令侧管理，但它们不是稳定的 HTTP API，不能直接让前端读写内部对象。

### 6.2 用量、费用和余额现状

已有后端用量统计：

- 输入 Token；
- 输出 Token；
- 总 Token；
- Cache Read/Write Token；
- 按模型聚合；
- 调用费用；
- 未定价调用；
- 当日阈值；
- 定时报告；
- 管理员告警；
- Mica 用量卡片。

相关文件：

- `runtime/usage_monitor.py`
- `runtime/pricing.py`
- `sources/runtime_event_log.py`

但缺少：正式供应商维度、按会话/All 的统一查询 API、24h/7d/30d/365d/all 的完整时间窗 API、图表数据接口、余额采集和 Telegram/Mail 预警。

### 6.3 多模型盲测缺失

当前 `ModelRouter` 的故障转移是“前一个失败后尝试下一个”，不是：

- 同一 Prompt 并发调用多个模型；
- 隐藏模型名称；
- 用户投票；
- 解盲；
- 比较延迟、Token、费用和回答质量。

因此多 LLM 对比测试应判定为【完全缺失】。
## 6.4 命令透明化与“学习内容”缺口

当前项目有 `docs/ai-setup-knowledge-pack.md`、`docs/ai-kb-operations-manual.md`、`docs/config-catalog-full.md` 和 `docs/route-matrix.md`，这些是人工/AI 阅读的配置与运维资料，不是完整的学习系统。

没有发现独立的以下能力：

- 命令自动发现、参数 schema、权限矩阵和实时状态 API；
- 机器人向用户逐步教学命令的课程/任务模型；
- 用户操作示例、练习题、结果评估和错误反馈闭环；
- 人格、世界观、知识库回答质量的评测集；
- 搜索结果质量、引用正确率、事实一致性的自动评测；
- 多模型盲测结果回流到模型选择、提示词或知识库优化；
- 学习内容版本、进度、复习和管理员审阅状态。

因此，您提到的“4.5 学习内容”应按【完全缺失】处理，不能把现有 Markdown 知识包误认为已经实现。建议在后端先建设：

1. `CommandCatalog`：命令、参数、权限、示例、依赖、限制。
2. `LearningUnit`：一个可学习的命令、平台能力、配置项或排障主题。
3. `LearningAttempt`：用户输入、上下文、结果、错误类型、完成状态。
4. `EvaluationCase`：人格、世界观、知识、搜索、平台解析和安全测试样例。
5. `FeedbackRecord`：管理员评分、用户选择、盲测投票和修订建议。
6. `GET /admin/api/v1/learning/*`：为未来 Web UI 提供学习目录、进度、测验和评测结果。

第一版可以只做管理员命令 `/bot commands`、`/bot learn <topic>`、`/bot evaluate <case>`，但它们必须调用同一个 service 和 API 层，不能继续把命令逻辑散落在 `__init__.py`。

## 7. 架构与质量问题

### 7.1 异步边界不统一

聊天、内容解析、点歌、历史上的今天已使用 `asyncio.to_thread`/`offload_capability`。但文件上传后的代码调试、文件导出时的 LLM 请求与文档转换仍直接在 matcher 中执行，可能阻塞事件循环。

- `__init__.py:2147`：同步 `run_code_debug`。
- `__init__.py:2165-2184`：同步 LLM 生成和导出。

### 7.2 文件执行隔离不足

当前 `.py` 执行使用 `python -I`、临时目录、超时、受限环境变量，但不构成强安全沙箱：没有 Windows Job Object 资源限制、网络隔离、低权限 token/AppContainer、系统调用边界或子进程树限制。

### 7.3 异常信息可能泄露内部细节

`runtime_admin.py` 多处将 `str(exc)` 返回给管理员，可能暴露文件路径、上游报错、URL 或库细节。应改为安全错误码 + debug ID，对完整异常只写审计日志。

### 7.4 SQLite 存储分散

审计、历史、记忆、向量、限流、队列、回执、订阅、音乐统计、解析历史、遥测、诊断分别维护 SQLite schema。没有统一迁移框架，后续 API/监控需要跨库拼接，维护成本高。

### 7.5 订阅旧实现与新实现双轨

新订阅 runtime 已在启动链路使用；旧 store/watcher/scheduler 和 `_register_subscription_scheduler` 仍在源码。必须以迁移方式清理，不能直接删除外部 Runtime 中的活动订阅数据。

### 7.6 配置规模与示例漂移

`Config` 有约 305 个字段。`.env` 与 `.env.example` 均可映射到 Config，但示例独有 19 个键，实际独有 2 个键。应生成配置文档和 schema，而非手工维护多份目录。

### 7.7 用量统计不适合长期监控

`RuntimeEventLog.aggregate_llm_usage_range()` 从日志文本解析 token/cost。适合作为短期兼容层，不适合作为供应商、会话、图表、账单和历史查询的长期事实源。

### 7.8 平台解析深度不一致

平台 parser 中同时存在 `deep`、`shallow`、`blocked`、oEmbed、OG 元数据兜底、Cookie 登录态解析和 Playwright 浏览器解析。产品层应显式展示平台、解析深度、是否需要登录、是否能获取正文、媒体和订阅。

### 7.9 当前 lint 问题

Ruff 当前有 6 项：

- `runtime/pricing.py:12` 未使用 `Any`。
- `runtime/pricing.py:63` 冗余 `int()`。
- `runtime/usage_monitor.py:291` 冗余 `int()`。
- `runtime/usage_monitor.py:302/370/405` 无效 `noqa: BLE001`。

## 8. 目标架构

### 8.1 核心原则

1. Bot Runtime 和控制面分离：聊天、解析、订阅、发送不能依赖 Web UI 才能工作。
2. API 优先：UI 只调用稳定的 `/admin/api/v1` 契约，不能直接读写 `.env`、SQLite 或 Python 全局对象。
3. 数据事实优先：LLM 调用、费用、告警、订阅、模型配置均进入结构化存储。
4. 安全默认关闭：命令执行、外部发帖、自动互动、文件执行、凭据读写都需显式启用、角色授权、审计与限流。
5. 不直接照搬 AstrBot 插件：只借鉴能力边界、状态机、API 使用方法和失败策略；重写为 NoneBot2 adapter/capability/runtime 结构，并先核对许可证和上游 API 条款。

### 8.2 推荐控制面模块

```text
plugins/bot_unified_runtime/control_plane/
├── domain/                 Provider、Model、Usage、Alert、Experiment、Command models
├── repositories/           SQLite repository 与迁移
├── services/               业务服务，不依赖 NoneBot Event
├── api/                    FastAPI routers 与 Pydantic 请求/响应 DTO
├── auth.py                 本地管理员鉴权、CSRF、session/token
├── audit.py                控制面审计
└── command_catalog.py      命令注册表和帮助文档生成
```

初始 API 只监听 loopback，要求管理员鉴权；不在第一阶段对公网开放。NoneBot FastAPI driver 仅承担挂载，不让前端直接持有 LLM provider key。

### 8.3 首批 API 契约

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

任何返回 provider 配置的 endpoint 都只返回 `credential_state`、`key_fingerprint` 或“已设置/缺失”，绝不返回 API Key/Cookie 原文。
## 9. 分阶段完善方案

### 阶段 0：稳定基线和命令透明化

目标：先让当前机器人可验证、可理解、可维护。

1. 修复 6 个 Ruff 问题。
2. 修复 `scripts/dev.ps1` 的 pytest 临时目录策略，让 `$TMP/$TEMP` 和 pytest `--basetemp` 可配置到允许写入目录。
3. 复跑完整 pytest，先解决环境权限，再区分真实功能失败。
4. 新建 `CommandCatalog`，把 matcher、能力 ID、权限、语法、参数、示例、输出类型统一注册。
5. 让 `/bot help`、`/bot commands`、`/bot command <name>` 和后续 `GET /commands` 都由同一 catalog 生成。
6. 建立 `docs/command-reference.md` 自动生成机制，消除命令黑箱。
7. 为每个 capability 生成机器可读状态：enabled、permission、dependencies、known_limitations。

验收：管理员能通过单一入口得到完整命令、权限、参数、示例、能力依赖和限制；测试、lint、runtime-layout 有可重复结果。

### 阶段 1：优先优化基础聊天和稳定搜索 API

目标：聊天正常、人格和知识库优先，联网搜索使用稳定 API 而不是 HTML 搜索页抓取。

1. 抽象 `SearchProvider` 协议，保留当前 DDG/Bing HTML provider 作为降级实现。
2. 增加正式搜索 API provider adapter，第一候选可使用 Brave Search API；同时预留 Tavily 等 provider adapter，不把某个供应商硬编码进 chat。
3. 增加 `SearchResult` 统一字段：标题、摘要、URL、域名、发布时间、来源类型、可信度、查询 ID、原始 provider、抓取时间。
4. 建立来源策略：官方站点、开发者文档、政府/机构、媒体原创、社区内容分别赋权；低质量聚合站、词典/笔顺/SEO 站默认降权或过滤。
5. 先返回搜索证据，再选择性抓取少量高质量页面正文；页面正文必须做长度、域名、重复和提示注入清洗。
6. 记录搜索审计：查询哈希、provider、耗时、命中数、被过滤原因；不记录用户敏感原文。
7. 新增离线 fixture 测试：时效问题、世界观问题、官方优先、污染源过滤、无结果、provider 限流、fallback。
8. 聊天回答加事实边界：联网事实必须附来源名或明确“未检索到可靠来源”；世界观事实优先知识库，知识库置信度不足才联网。

验收：当前信息问题不再依赖 HTML 搜索页；搜索失败可安全降级；人格和知识库回答不被搜索噪声覆盖；能够审计搜索质量。

### 阶段 2：后端控制 API 和供应商/模型管理

目标：先提供稳定后台 API，不急于做外部 UI。

1. 新建 Provider、Model、CredentialRef、ModelOrder、ProbeResult 领域模型。
2. 将 `.env` 中的 `BOT_MODEL_REGISTRY` 迁移为只读启动种子；运行时编辑写入独立控制面数据库或受控 settings 文件。
3. Provider 记录 URL、认证类型、可选余额 adapter、启用状态、限制、标签；凭据只保存引用名或安全存储引用。
4. Model 记录 provider_id、model_name、reasoning effort、上下文上限、输出上限、priority、分组、成本表和健康状态。
5. 实现 provider/model CRUD、连通性 probe、优先级重排、时段排序和操作审计 API。
6. 保留 `/bot runtime model`，但改为调用同一 service，而不是自己操作 settings。
7. 为删除操作实现引用检查：被活动会话、订阅、实验或计划引用时禁止删除，先禁用或迁移。

验收：机器人命令和 API 修改同一份模型/供应商状态；修改立即生效、可审计、可回滚，不泄露凭据。

### 阶段 3：Web 游乐场后端和多模型盲测

目标：先建实验 API，UI 仍可后置。

1. `PlaygroundSession` 保存固定人格 profile、系统提示版本、知识/搜索策略、消息历史、模型选择和预算。
2. `Experiment` 保存同一 Prompt、候选模型、随机展示标签、上下文快照、搜索证据快照。
3. 并发执行候选模型，设置全局 deadline、每模型 timeout、并发上限、费用上限和取消机制。
4. 结果以 A/B/C 标签返回，前端不能先获得真实 model_id；投票后才可解盲。
5. 记录延迟、Token、缓存 Token、费用、finish reason、错误类型；回答正文与可审计证据分开存储。
6. 支持用户偏好投票、备注、重新运行和导出比较结果。
7. 对实验默认禁用真实外部工具或使工具调用使用相同快照，避免模型因不同联网结果而失去可比性。

验收：可从 API 创建同 Prompt 的多模型盲测，完成选择后能查看解盲、成本、延迟和输出差异。

### 阶段 4：用量、费用、余额和多通道预警

目标：满足余额和 Token 消耗需求，为 UI 和告警提供唯一事实源。

1. 新建 `llm_call_records`，每次模型调用写结构化记录：provider、model、session、prompt/cache-create/cache-read/completion/total tokens、费用、延迟、状态、错误、时间。
2. 保留 `runtime_event_log` 作为运行日志，不再让它承担账单数据库职责。
3. 实现固定时间窗：24h、7d、30d、365d、all；支持 session、provider、model、all 维度。
4. 实现 summary/timeseries/breakdown API，分别返回输入、缓存创建、缓存读取、输出 Token 和费用。
5. Provider adapter 可选实现余额查询；不能查询余额的 provider 标记 `balance_capability=unsupported`，不能伪造为 0。
6. 建立 `AlertPolicy`：日/周/月费用阈值、输入/输出 Token 阈值、余额阈值、provider 失联阈值。
7. 将告警统一发送到 QQ、Telegram、Mail；每种 destination 单独记录投递成功、失败、重试、抑制窗口。
8. 费用预警至少支持全局、供应商、模型、会话四个范围。

验收：可查询任意指定时间窗的 Token/费用细分；余额有明确支持状态；阈值跨 QQ/Telegram/Mail 投递并可追踪。

### 阶段 5：清除订阅旧实现并将当前实现变为唯一正式订阅系统

目标：不再区分 V1/V2，当前 V2 成为唯一的 `subscription` 实现。

1. 先冻结旧订阅写入入口，确认所有当前 matcher、命令、scheduler、测试和文档引用。
2. 修复新增订阅的异步 `asyncio.run` 问题，先保证 canonical implementation 可用。
3. 写一次性、可重复、带备份保护的迁移：旧数据库先只读检查，保留现有 `subscriptions_old.sqlite3` 规则，不允许覆盖备份。
4. 把新实现重命名为正式名称：`subscription_store.py`、`subscription_scheduler.py`、`subscription_runtime.py`、`subscription.py`；模块、类、文档、测试中去掉 V2 字样。
5. 删除旧 `SubscriptionStore`、`subscription_watcher`、旧 `_register_subscription_scheduler` 和旧命令入口，只保留有期限的 migration compatibility shim。
6. 保持用户配置键 `BOT_SUBSCRIBE_*` 不变，避免配置破坏。
7. 迁移后校验：目标数、destination 数、游标、已见 item、outbox 状态和禁用目标均一致。
8. 更新命令帮助和 API，用户只看到“订阅”，永远不看到 V1/V2。

验收：源码只存在一个正式订阅运行时；旧数据不丢失；新建/暂停/恢复/删除/投递均通过真实异步测试。

### 阶段 6：优先平台能力补全

优先级严格按用户指定顺序：

1. 哔哩哔哩。
2. 小红书。
3. 抖音。
4. 推特/X。
5. YouTube。
6. 森空岛。
7. 库街区。
8. 网易云音乐。

每个平台按照同一能力矩阵实施：

```text
resolve_target / link_parse / detail_fetch / creator_profile /
incremental_subscription / push_projection / login_state /
rate_limit / error_mapping / fixture_tests / capability_status
```

具体交付顺序：

1. 哔哩哔哩：视频、动态、直播、空间、会员购字段和订阅游标稳定化；处理 WBI、Cookie 失效、直播状态、去重。
2. 小红书：补笔记正文、时间、互动、主页增量、Cookie/Playwright 降级和真实 fixture。
3. 抖音：先实现稳定链接解析和公开视频元数据；再评估可维护的公开增量来源，未满足前不得声称支持订阅。
4. 推特/X：把 GraphQL 凭据、Cookie、代理、错误码、rate limit、cursor 持久化做成独立 client；无授权时明确 `auth_required`。
5. YouTube：增强 Atom Feed、频道/播放列表/Shorts、视频类型、发布时间和取消订阅处理。
6. 森空岛：统一 `skland` 的名称、链接解析和账户/帖子能力；后续才做订阅 adapter。
7. 库街区：统一 `kurobbs` 名称和 API/Playwright fallback；后续再做 creator/post 订阅。
8. 网易云音乐：完成 playlist/artist/album/public user 订阅、变更游标、音频可用性和卡片投影。

后置平台：萌娘百科、米画师、无差别同人站、Lofter、米游社、QQ音乐、酷我、酷狗、Apple Music、Spotify、汽水音乐、NGA、Steam 周免、iPad/App Store 周免。
## 10. 跨平台文件处理和低资源安全工作器

目标：支持 Word、PPT、Excel、PDF、代码的输入分析和多格式生成，同时避免任意代码执行损害宿主机。

1. 建立统一 `Attachment` 合同：来源 adapter、下载 URL/本地路径、MIME、大小、哈希、保留期限、owner、风险等级。
2. QQ、Telegram、Mail 的附件都转换为同一 attachment pipeline；不能直接在 matcher 内分析。
3. 增加只读解析器：DOCX、PPTX、XLSX、PDF、TXT/MD/CSV/JSON/YAML/TOML、Python；`.doc/.xls/.ppt` 仅在可用安全转换器存在时处理，否则明确提示不支持。
4. 解析输出为结构化 `DocumentAnalysis`：文本摘要、页/工作表/幻灯片数量、表格、代码语言、依赖、错误、风险标记。
5. 文件生成改为 `DocumentRequest`：先由 LLM 生成受约束的结构化内容，再渲染 Markdown/DOCX/PPTX/XLSX/PDF；对“生成代码文件”增加明确的语言、文件名、目的和安全提示。
6. 默认不执行上传代码。执行入口必须分为“静态分析”和“受限运行”；普通用户无执行权限。
7. 低资源执行工作器采用分层方案：
   - 第一层：Python AST、依赖清单、危险 API 静态扫描，不运行代码。
   - 第二层：独立 worker 子进程，Windows Job Object 限制单进程、CPU 比例、内存、运行时间、输出大小和子进程数量。
   - 第三层：清洁目录、最小环境变量、只读输入副本、受控输出目录。
   - 第四层：默认禁止网络。真正可靠的网络隔离需 Windows 防火墙规则、AppContainer/受限 token 或独立隔离宿主；不能仅凭 Python `subprocess` 宣称已隔离。
   - 第五层：对于需要系统调用隔离的高风险代码，默认拒绝本机运行，改为人工审核或独立、可销毁的隔离环境。
8. 将资源预算做成配置：CPU 低配默认、内存硬上限、单次时限、队列并发 1、GPU 不透传。没有 GPU 任务不启动 GPU 相关组件。
9. 对文档和代码内容统一做提示注入检测：外来文本只作为不可信数据，禁止其改变系统指令、调用工具、读取凭据或触发发送/执行。

验收：三种通信平台的附件可统一分析和回传；多格式生成可复用；危险代码不能借机器人获得无限 CPU、内存、网络或系统权限。

## 11. 气象预警、表情包、日记与戳一戳扩展

### 11.1 气象预警

参考公开 AstrBot 气象预警项目的能力思路，但按 NoneBot2 重写为：

1. `AlertRegion`：机器人实例、群、城市/区县、预警类型、最低等级、时段、目标 adapter。
2. `WeatherWarningProvider`：官方气象局数据源 adapter；数据格式、缓存、去重、失效和错误映射独立。
3. `WarningEvent`：事件 ID、地区、类型、等级、发布时间、有效期、正文、来源、哈希。
4. `WarningScheduler`：按地区聚合请求，避免每群重复拉取；按群规则投递。
5. 支持“机器人 A 在 A 地群播 A 地；机器人 B 在 B 地群播 B/C 地”的多实例映射。
6. 首次上线只建 baseline，不推送历史预警；预警升级、取消、更新需要明确消息策略。
7. 全链路走发送队列、quiet hours、角色/群策略和告警审计。

### 11.2 表情包生成与理解

先验证，后扩展自动发送：

1. 对现有 meme service 做 readiness probe：服务存活、模板列表、单模板生成、文件大小、发送回执。
2. 新增端到端测试：机器人命令 → 服务 → 图片 → QQ/Telegram/Mail 发送结果。
3. VLM/图像理解结果仅作为标签，不作为绝对事实；记录 `is_meme`、情绪、主题、NSFW、人物和置信度。
4. 自动发送必须为 opt-in，按群、冷却、上下文相关性、角色设定、NSFW、失败率做 gate；默认不因“能生成”而自动发送。

### 11.3 日记与 QQ 空间互动

这是高风险外部发布能力，采用“先草稿、后人工批准、再发布”：

1. 每日仅使用已授权、已脱敏、可见范围允许的当天群/私聊摘要和公开事件摘要。
2. 先生成 `DiaryDraft`，包含人格版本、事实来源、引用会话数量、敏感性分数和发布时间建议。
3. 草稿只能由管理员审核/编辑/批准；未批准不得发布。
4. QQ 空间发布 adapter 必须独立、显式启用、低频、Cookie 安全存储、发布审计、失败回滚和账号风控开关。
5. 互动先做“收集评论 → 生成候选回复 → 管理员审核”，不做无人值守自动社交。

### 11.4 戳一戳

1. 接收 OneBot poke/notify event。
2. 按群/私聊、频率、用户角色、时间段和人格状态选择反应。
3. 反应可为文本、表情、图片或轻量动作，不触发昂贵 LLM。
4. 每个群独立启用和冷却，支持管理员预览和禁用。

## 12. 外部 Web UI

UI 明确后置。只有阶段 1-4 的 API 和数据模型稳定后才开始。

第一版 UI 只做：

1. 健康状态、命令目录、能力状态。
2. Provider/Model 管理和 probe。
3. 盲测游乐场。
4. Token/费用/余额/告警。
5. 订阅目标和平台健康。
6. 文件任务、代码静态分析和受限运行状态。

CMD 控制台不直接提供任意 PowerShell。若确有需求，仅提供：

- 固定维护任务白名单；
- 参数 schema；
- 运行前预览；
- 单实例锁；
- 流式输出；
- 取消；
- 全量审计；
- 管理员二次确认。

## 13. 外部参考项目的使用原则

用户提供的 AstrBot 项目应作为“能力调研对象”，不是可直接装入 NoneBot 的依赖：

- 气象预警：借鉴多地区订阅、预警去重、等级升级、群目的地映射和 API 容错；重写为 NoneBot capability/scheduler/store。
- QQ 空间：借鉴草稿、发布、互动、状态持久化和频率控制；任何发布必须先审计、先人工批准。
- 戳一戳：借鉴按场景的 reaction router；映射到 OneBot notify event 和现有 policy gate。

实现前必须逐个审查：许可证、上游 API 合法性、账号风控、Cookie 处理方式、依赖体积、资源占用和可测试性。不得复制未确认许可证的代码，也不得把 AstrBot 的同步/生命周期假设直接带入 NoneBot2。

## 14. 建议的第一批实现任务

在开始任何大功能前，建议按以下顺序落地：

1. 修复测试临时目录、Ruff 和订阅 `asyncio.run` 风险。
2. 完成 `CommandCatalog`、自动化命令参考和 capability 状态接口。
3. 实现正式搜索 API adapter、来源策略、搜索审计和聊天回归测试。
4. 建立 Provider/Model/Usage/Alert 的控制面数据模型与 loopback API。
5. 将 LLM 调用从日志文本统计迁移到结构化 `llm_call_records`。
6. 清理订阅旧实现，当前实现重命名为唯一正式订阅系统。
7. 逐个补齐优先八个平台的能力矩阵，先 Bilibili、小红书、抖音、X、YouTube。
8. 建立跨 QQ/Telegram/Mail 的附件合同和静态分析管道。
9. 加入低资源受限运行 worker。
10. 实现天气预警和表情包端到端验证。
11. 在上述 API 稳定后建设游乐场和 Web UI。

## 15. 实施前需要确认的产品决策

以下不应由代码自行猜测，实施阶段需要管理员明确选择：

1. 搜索 API 供应商、预算、地区、每日请求上限和 API Key 存储方式。
2. Web API 是否只监听本机，还是未来需要反向代理/公网访问。
3. UI 管理员认证方式：本机单用户、密码、OIDC、反向代理认证或设备令牌。
4. 哪些供应商可查询余额，以及每个供应商是否允许自动轮询余额。
5. 文件执行是否允许；若允许，哪些管理员、哪些语言、资源上限、是否接受 Windows 防火墙/AppContainer 等隔离配置。
6. QQ 空间发布是否仅草稿/人工批准，还是未来允许自动发布；默认建议仅人工批准。
7. 哪些群可启用表情包自动发送、气象预警、日记素材收集和戳一戳反应。

## 16. 最终判断

当前项目不需要推倒重写。已有统一 Runtime、消息适配、模型路由、发送队列、卡片、审计、解析器、订阅实现和人格/知识能力，足以作为后续演进基础。

但必须停止继续以“在 `__init__.py` 增加一个 matcher + 在 `.env` 增加一个键”的方式扩张。后续新增能力应先落到领域模型、service、repository、API 契约和测试，再接入 NoneBot matcher；Web UI 只消费这些 API。这样才能同时满足稳定聊天、多模型盲测、供应商管理、余额监控、平台订阅和低风险自动化的长期需求。
## 17. 用户确认的架构决策

本节记录 2026-09-05 用户补充要求，后续实施以此为准。

### 17.1 UI 模板决策

- 外部管理 UI 暂不立即实现。
- 后置 UI 采用 **TailAdmin Vue** 作为壳层和交互参考：Vue + Tailwind，保留其导航、表格、表单、图表和响应式后台结构。
- 当前阶段不安装、不复制、不改造 TailAdmin 模板；先把后端 API、数据模型、权限、审计和迁移稳定下来。
- 后续 UI 不直接绑定 Element Plus/Ant Design；云母风格由项目自己的 CSS token 和组件层实现。
- TailAdmin 只作为 UI 实现载体，不能反向决定后端数据结构。

### 17.2 网络和认证决策

用户选择后端 API 未来支持反向代理和公网访问，而不是只监听本机。因此必须采用分层部署：

```text
公网 HTTPS / 反向代理
        ↓
认证与限流层
        ↓
Control Plane API
        ↓
Bot Runtime / Repositories / Workers
```

必须支持可插拔认证方式，并允许组合启用：

- Bearer Token；
- 用户名 + 密码；
- TOTP/Aegis 兼容的一次性验证码；
- 二维码密钥/设备配对；
- 反向代理认证头；
- 未来 OIDC/OAuth2；
- 管理员、审计员、只读观察员、运维执行员等角色。

公网模式的强制条件：TLS、反向代理、登录失败限速、CSRF 防护、Secure/HttpOnly/SameSite Cookie、设备撤销、密钥轮换、审计、危险操作二次确认。不能把任意 PowerShell、API Key、Cookie 或文件执行接口直接暴露到公网。

### 17.3 搜索 API 决策

当前代码已有 DDG→Bing HTML provider，但用户明确认为质量不足。后续改为“正式搜索 API provider + HTML provider 降级”，且 provider 必须可配置：

```text
BOT_SEARCH_PROVIDER=brave|tavily|custom|html_fallback
BOT_SEARCH_API_URL=<provider endpoint>
BOT_SEARCH_API_KEY=env:<secret variable>
BOT_SEARCH_TIMEOUT_SECONDS=<number>
BOT_SEARCH_MAX_RESULTS=<number>
BOT_SEARCH_REGION=<region>
BOT_SEARCH_SAFE_MODE=<value>
BOT_SEARCH_ALLOWED_DOMAINS=<list>
BOT_SEARCH_BLOCKED_DOMAINS=<list>
BOT_SEARCH_CONTENT_FETCH_ENABLED=<bool>
BOT_SEARCH_DAILY_REQUEST_LIMIT=<number>
```

以上是建议配置合同，不代表当前 `.env` 已经存在这些键。正式实现前应从本地凭据和配置中选择实际 provider；没有 API Key 时不伪造可用状态。

### 17.4 供应商余额决策

用户要求所有供应商都可尝试余额查询，但不同供应商的余额协议并不统一。因此后端采用以下兼容层：

1. 官方余额 API adapter；
2. OpenAI-compatible usage/billing adapter；
3. NewAPI 模板 adapter；
4. TokenPlan adapter；
5. Sub2API 模板 adapter；
6. 自定义 HTTP adapter；
7. 自定义 JSONPath/JMESPath 字段映射；
8. 无余额 API 时的 `unsupported` 状态。

每个 provider 可以配置：余额 URL、HTTP method、请求头模板、query/body 模板、认证引用、响应字段映射、单位、币种、轮询周期、重试和限流。余额查询失败不能返回 0，必须返回 `unsupported`、`auth_required`、`rate_limited` 或 `provider_error`。

### 17.5 文件执行和自动化权限决策

文件执行、QQ 空间发布、表情包自动发送、气象预警、日记素材收集、戳一戳反应均改为细粒度策略：

```text
功能总开关
→ 机器人实例
→ adapter
→ 群/私聊目标
→ 用户角色
→ 时间段
→ 内容风险等级
→ 单次/每日额度
→ 是否需要管理员批准
```

默认策略：

- 代码执行：关闭；静态分析默认开启；
- 网络访问：关闭；逐任务白名单；
- 系统调用：关闭；高风险任务拒绝本机执行；
- QQ 空间：只生成草稿，人工批准后发布；
- 日记素材：只收集脱敏摘要，不收集原始私聊全文；
- 表情包自动发送：关闭，按群开启；
- 气象预警：按机器人、群、地区开启；
- 戳一戳：轻量本地 reaction，默认不调用 LLM。

所有默认值都应在 API/UI 中可查看、可修改、可回滚、可审计。

## 18. 当前配置与待新增配置对照

### 18.1 当前已有，可复用

- LLM：`BOT_CHAT_*`、`BOT_MODEL_REGISTRY`、`BOT_MODEL_PRESETS`、`BOT_MODEL_SCHEDULE`、`BOT_MODEL_PRIORITY_GROUPS`、`BOT_MODEL_PRICES`。
- 搜索：`BOT_WEB_SEARCH_ENABLED`、`BOT_WEB_SEARCH_TIMEOUT_SECONDS`、`BOT_WEB_SEARCH_MAX_RESULTS`、`BOT_WEB_SEARCH_ADMIN_NOTICE`、`BOT_DOWNLOAD_PROXY`。
- 订阅：`BOT_SUBSCRIBE_*`，包括轮询、并发、租约、重试、outbox、卡片。
- 用量：`BOT_USAGE_MONITOR_ENABLED`、`BOT_USAGE_ALERT_*`、`BOT_USAGE_REPORT_*`。
- 文件和媒体：`BOT_DOWNLOAD_*`、`BOT_CONTENT_*`、`BOT_CARD_RENDER_*`。
- 权限：`BOT_ADMIN_USER_IDS`、`BOT_TRUSTED_USER_IDS`、群白名单/黑名单、quiet hours。
- 通信：OneBot、Telegram、Mail 配置及账号列表。

### 18.2 需要新增领域配置

- Control Plane 监听地址、反向代理模式、可信代理头；
- 用户、角色、会话、设备、Token、TOTP、二维码配对；
- Search Provider、来源质量、配额、缓存和引用策略；
- Provider balance adapter、响应映射、单位、币种和轮询策略；
- LLM 调用结构化记录保留期和脱敏策略；
- 文件分析器、最大文件大小、解压炸弹检测、任务队列；
- worker CPU、内存、网络、进程数、输出大小、超时时间；
- QQ 空间草稿/审批/发布/互动策略；
- 表情包识别、NSFW、自动发送和群级策略；
- 气象地区、预警类型、等级和机器人/群映射；
- 戳一戳 reaction 规则；
- 学习单元、评测集、评分和反馈回流。

## 19. 后端优先的正式实施计划

### Phase 0：基线、命令目录和数据库盘点

**目标：** 先保证现有 Bot 能运行，并消除命令和数据库黑箱。

1. 修复当前 6 个 Ruff 问题。
2. 修复 `scripts/dev.ps1` 的测试临时目录配置。
3. 重新跑完整 pytest，区分环境权限错误和真实业务失败。
4. 建立数据库清单：数据库路径、表、拥有模块、读写入口、保留期、迁移责任。
5. 给每个旧数据库指定 canonical owner，不立即删除任何外部 Runtime 数据。
6. 建立 `CommandCatalog`，统一记录命令、参数、权限、能力 ID、依赖、示例、限制和状态。
7. 让 `/bot help`、`/bot commands`、文档和未来 API 使用同一 catalog。

**验收：** 能通过一个命令查看所有命令和可操作范围；数据库参数和所有权有清单；测试入口可重复执行。

### Phase 1：统一搜索 API 与聊天事实链

**目标：** 先解决用户最关心的基础聊天和网络搜索质量。

1. 定义 `SearchProvider`、`SearchQuery`、`SearchResult`、`SearchPolicy`、`SearchAuditRecord`。
2. 实现正式 API provider 抽象，第一 provider 按本地配置选择；保留 HTML provider 作为显式 fallback。
3. 实现 provider 配置校验、凭据引用、超时、重试、每日限额和缓存。
4. 实现来源评分：官方、政府/机构、开发者文档、媒体原创、社区、聚合/SEO。
5. 实现域名白名单、黑名单、结果去重、标题/正文污染过滤。
6. 页面正文只抓取少量高分来源；清除页面中的指令性文本、脚本、隐藏文本和提示注入。
7. 将搜索证据和回答文本分开存储；回答必须能追溯到搜索结果 ID。
8. 增加时效问题、世界观问题、官方优先、无结果、限流、API 故障和 fallback 测试。
9. 增加 `/bot search` 的清晰输出：provider、结果数、过滤数、耗时和安全状态，但不输出 Key/Cookie。

**验收：** 现实问题优先使用稳定搜索 API；污染源明显减少；无法检索时明确说明；人格和知识库上下文不被搜索结果覆盖。

### Phase 2：Provider/Model 后端控制 API

**目标：** 先完成可被 UI 消费的后端 API，不建设 UI。

1. 定义 Provider、Model、CredentialRef、BalanceAdapterConfig、ProbeResult、ModelOrder。
2. 把 `.env` 注册表作为启动种子，不允许 API 直接修改 `.env`。
3. 运行时修改写入独立控制面数据库或正式 settings repository。
4. 实现供应商和模型 CRUD、启用/禁用、连接测试、排序、回滚和审计。
5. 保持现有 `/bot runtime model`，改为调用同一 service。
6. 删除操作执行引用检查，避免删除仍被聊天、订阅、实验引用的模型。
7. 所有凭据只使用引用名、哈希指纹或存在状态。
8. 设计公开/内网部署配置，默认带反向代理信任边界校验。

**验收：** 命令和 API 看到同一份模型状态；增删改、排序、probe、回滚可审计；密钥不会出现在响应或日志中。

### Phase 3：余额、Token、费用和多通道预警后端

**目标：** 形成所有监控和 UI 的唯一事实源。

1. 建立 `llm_call_records` 结构化调用表。
2. 每次调用记录输入、缓存创建、缓存读取、输出、总 Token、延迟、provider、model、session、费用、状态和错误。
3. 实现官方、NewAPI、TokenPlan、Sub2API、OpenAI-compatible 和 custom balance adapter 接口。
4. 实现自定义请求模板和响应字段映射，但模板必须经过管理员审计。
5. 实现 24h、7d、30d、365d、all 时间窗口。
6. 支持 all、provider、model、session 维度。
7. 实现余额快照表和余额变化历史，不支持的供应商明确标记。
8. 实现 QQ、Telegram、Mail 三种告警 channel，统一记录发送状态和重试。
9. 支持全局、供应商、模型、会话四种阈值范围。

**验收：** 能准确查看四类 Token；能按五种时间范围统计 Token 和费用；余额不可用时不会被误报为 0；超阈值告警可在三种通信渠道追踪。

### Phase 4：订阅系统合并

**目标：** 当前实现成为唯一正式订阅系统，代码和用户界面不再出现 V1/V2。

1. 冻结旧订阅写入口并完成引用清单。
2. 修复 `subscribe.py`/`subscribe_v2.py` 的异步边界，禁止在运行事件循环中使用 `asyncio.run()`。
3. 对旧数据库做只读快照、校验、备份和迁移演练。
4. 将当前 canonical implementation 重命名为正式 `subscription_*` 模块。
5. 清理旧 `SubscriptionStore`、旧 watcher、旧 scheduler、旧注册入口。
6. 只保留带删除期限的迁移 shim，不保留重复业务入口。
7. 保持 `BOT_SUBSCRIBE_*` 配置兼容。
8. 校验目标、destination、cursor、seen items、outbox 和状态迁移前后一致。
9. 更新命令、文档、测试、审计标签，移除用户可见的 V1/V2。

**验收：** 源码只有一个订阅实现；旧数据不丢失；新增、暂停、恢复、删除、轮询、推送均是真实异步路径。

### Phase 5：优先平台补全

**目标：** 按用户使用频率优先完成以下八个平台：

1. 哔哩哔哩；
2. 小红书；
3. 抖音；
4. 推特/X；
5. YouTube；
6. 森空岛；
7. 库街区；
8. 网易云音乐。

每个平台必须逐项验收：

```text
link_parse / detail / creator_profile / search /
incremental_subscription / push / login_state /
rate_limit / error_mapping / fixture / capability_status
```

现阶段不把“有链接 parser”写成“平台完成”。无稳定、合法、可维护的增量来源时，平台只能标记为 `parse_only` 或 `auth_required`。

### Phase 6：文件分析、生成与低资源安全 worker

**目标：** 统一 QQ、Telegram、Mail 文件处理，并保证资源边界可选、可审计。

1. 定义 `Attachment`、`DocumentAnalysis`、`CodeAnalysis`、`DocumentRequest`。
2. 统一三种通信平台的附件接收和安全落盘。
3. 增加 DOCX/PPTX/XLSX/PDF/TXT/MD/CSV/JSON/YAML/TOML/Python 的只读分析器。
4. `.doc/.xls/.ppt` 只有在明确安装、验证和隔离转换器后才启用。
5. 输出文本摘要、页数、工作表、幻灯片、表格、代码语言、依赖和风险。
6. 生成 Markdown、Word、PPT、Excel、PDF 和独立代码文件。
7. 代码默认先 AST/静态分析，不执行。
8. 受限运行 worker 使用独立进程、Windows Job Object、内存/CPU/时限/输出/子进程限制。
9. 默认无网络、无 GPU、队列并发 1；高风险系统调用拒绝本机执行。
10. 所有外来文档和代码都视为不可信内容，先做提示注入和危险操作检测。

### Phase 7：气象预警和群/机器人区域映射

**目标：** 支持不同机器人、不同群、不同地区的官方气象预警。

1. 定义 `AlertRegion`、`WarningEvent`、`WeatherWarningProvider`、`WarningScheduler`。
2. 官方气象 API 统一为 provider，支持缓存、增量、去重、等级升级、取消和失效。
3. 规则支持 bot_id、群号、地区、预警类型、等级、时间段和发送策略。
4. 按地区合并请求，避免一个地区被多个群重复拉取。
5. 首次订阅只建立 baseline，不刷历史消息。
6. 预警升级、解除和内容变更有单独策略。
7. 走现有发送队列、quiet hours、群策略、告警和回执。

### Phase 8：表情包、QQ 空间、日记和戳一戳

1. 表情包先做服务探活、模板列表、生成、识别、发送回执和失败率测试。
2. VLM 只生成不可信标签：是否表情包、情绪、主题、NSFW、人物、置信度。
3. 自动发送按群 opt-in、冷却、场景匹配、NSFW 和每日额度控制。
4. 日记只使用脱敏摘要和已授权来源；先生成草稿，再人工批准。
5. QQ 空间发布独立为 adapter，具有草稿、审批、发布、撤回、审计和 Cookie 轮换。
6. 评论互动先生成候选回复，默认人工批准。
7. 戳一戳采用轻量规则 reaction，不调用 LLM；支持群级冷却和权限。

### Phase 9：TailAdmin Vue 外部 UI

只有后端 API 稳定后开始：

1. 引入 TailAdmin Vue 的导航、布局、表格、表单和图表结构作为壳层。
2. 使用项目自己的云母设计 token，不直接照搬模板主题。
3. 首屏展示健康状态、Bot 实例、插件能力、命令目录和待处理告警。
4. Provider/Model 页面支持增删改、probe、排序、启停和审计。
5. Playground 页面支持单模型聊天、多模型盲测、解盲、评分和成本对比。
6. Usage 页面支持 24h、7d、30d、365d、all，输入/缓存创建/缓存读取/输出 Token 和费用图表。
7. Balance 页面区分余额数值、更新时间、币种、来源和 unsupported。
8. Subscription 页面支持目标、目的地、游标健康、重试和暂停。
9. File 页面展示附件分析、静态分析、worker 任务和资源限制。
10. Terminal 页面只调用白名单维护任务，不开放任意 PowerShell。

## 20. 设计上的关键取舍

### 20.1 “极高自由度”不等于“任意执行”

自由度应体现在配置和策略组合上，而不是允许任意代码、任意 HTTP、任意系统调用。所有高风险能力需要：schema、白名单、限额、审批、审计和撤销。

### 20.2 “所有供应商余额”必须允许不支持

系统可以为所有供应商建立 adapter 插槽，但无法从没有余额协议的供应商凭空得到余额。正确状态是：已支持、未配置、鉴权失败、限流、接口错误、不支持，而不是伪造 0 元。

### 20.3 公网访问必须后置于认证和审计

公网 API 不是简单把监听地址改成 `0.0.0.0`。必须先完成认证、TLS、反向代理信任、CSRF、限流、审计、设备撤销和危险操作确认，再允许外部访问。

### 20.4 UI 后置可以降低返工

TailAdmin Vue 只应在 API、DTO、权限和状态稳定后接入。否则 UI 会把当前分散的 SQLite、日志文本和运行时全局变量固化成新的技术债。

## 21. SakuraFrp 传输预算与低带宽控制

用户实际使用 SakuraFrp：每日流量额度 3GB，隧道带宽最高 10Mbps。该限制是本项目控制面的硬约束，不把 10Mbps 当作可以持续跑满的目标。

SakuraFrp 官方文档说明：穿透流量按 frpc 与节点之间的上行/下行计算，协议额外开销不计入账户扣费；实际速度还受本机上行带宽和节点共享负载影响；`bandwidth_limit` 的配置单位实际是 MiB/KiB 兼容单位，而不是普通十进制 Mbps。citeturn1search0turn1search1

### 21.1 硬预算

```text
sakurafrp.daily_traffic_budget_bytes = 3 * 1024 * 1024 * 1024
sakurafrp.tunnel_bandwidth_cap_mibps = 10
sakurafrp.control_plane_default_cap_mibps = 2
sakurafrp.warning_thresholds = 50%, 75%, 90%, 100%
```

`10Mbps` 在用户语义中表示 SakuraFrp 隧道最高带宽；实现时必须明确单位并统一为内部 bytes/sec，不能直接把 `10` 传入一个单位未知的底层配置。

建议实际运行配置：

- SakuraFrp 隧道配置带宽上限不高于 `10M`，并在 UI/API 显示实际单位为 `MiB/KiB` 兼容单位；
- Control Plane API 默认限速远低于隧道上限，建议初始 `2Mbps` 左右；
- 单个请求响应上限默认 1MiB；
- SSE/WebSocket 日志默认关闭或严格限速；
- 文件上传、文件下载、图片原图、视频、音频和批量导出默认不经过控制面隧道；
- 余额、用量、模型列表使用本地缓存快照，浏览器只读取增量变化；
- playground 默认非流式，流式输出采用合并分片并设每分钟预算；
- 接近 90% 日流量时自动关闭非必要刷新、图表高频轮询和日志流；
- 达到 100% 时只保留低流量健康检查、配置读取和本地 Bot 运行，禁止主动大数据传输。

### 21.2 流量计量

新增本地 `TunnelTrafficMeter`，不依赖 SakuraFrp 面板才能做保护：

```text
TunnelTrafficSample
- tunnel_id
- direction: ingress/egress
- bytes
- request_id
- endpoint
- content_type
- started_at
- completed_at
- source: proxy/access_log/app_counter
```

计量优先级：

1. 反向代理 access log 的请求/响应字节；
2. Control Plane middleware 的请求/响应字节；
3. SSE/WebSocket 分片累计字节；
4. 文件任务和 API 请求分开计量。

SakuraFrp 账户流量与本地 HTTP 字节数可能因封装、重试和协议差异不同，因此 UI 同时显示：

- 本地估算传输量；
- SakuraFrp 面板已使用量（管理员手工/接口同步）；
- 估算差异；
- 最后同步时间。

不能把本地估算值伪装成 SakuraFrp 账单精确值。

### 21.3 断路策略

传输预算状态机：

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

各状态行为：

- `NORMAL`：允许正常控制面读取和低频 playground。
- `WATCH`：提高审计频率，禁止自动刷新间隔低于 30 秒。
- `THROTTLED`：禁止日志流和大响应，模型列表/余额刷新改为手动。
- `EMERGENCY`：只保留健康检查、配置摘要、告警和管理员操作。
- `BLOCK_NONESSENTIAL`：拒绝文件传输、图表大查询、连续日志、原图和流式回答。

断路器必须只影响穿透控制面，不影响本地 Bot 在内网中的正常运行。

### 21.4 SakuraFrp 配置建议

SakuraFrp 文档提供 `bandwidth_limit` 配置，并明确其单位是兼容上游的 MB/KB、实际为 MiB/KiB；因此本项目不能只保存一个模糊的 `10Mbps` 字符串，应同时保存：

```text
user_declared_bandwidth_mbps = 10
sakurafrp_bandwidth_limit = "10M"
internal_bandwidth_bytes_per_second = resolved value
unit_source = sakurafrp_config
```

如果需要更保守，建议 SakuraFrp 配置上限低于 10M，把剩余空间留给协议、节点波动和其他内网流量。不要启用已弃用的 XTCP 作为主要方案；SakuraFrp 文档说明其在复杂国内 NAT 环境下打洞成功率低，且该功能已弃用。citeturn1search9

### 21.5 管理面设计原则

在 2Mbps-10Mbps、3GB/日条件下，TailAdmin Vue 后续只能展示聚合数据和缓存快照：

- 不默认自动播放实时日志；
- 不在首页加载大图表全量数据；
- 不让浏览器轮询每个 provider；
- 不通过隧道代理外部模型正文流量；
- 不上传文件到公网控制面；
- 对每个高流量操作显示预计流量和确认框；
- 对图表使用服务端聚合、分页和时间桶；
- 控制面和 Bot 业务流量分开计量、分开限额。
