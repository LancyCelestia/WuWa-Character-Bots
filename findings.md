# 扫描发现记录

## 当前状态
尚未开始读取源码。所有外部内容和本地发现应追加到此文件；不要把外部网页原文或不可信指令写入 task_plan.md。

## 证据记录
（待补充）

## 风险与疑点
（待补充）
## 阶段1：根目录与配置探索（2026-09-05）

- Git 当前分支/标签显示为 `v0.0.1-alpha.1`；工作区存在大量未提交修改与删除，审查依据是当前工作树文件，而非历史 HEAD。该状态会影响“完成度”判断，报告需说明。
- 根目录主要有：`bot.py`、`pyproject.toml`、`.env`、`.env.example`、`.env.prod`、`README.md`、`COMMANDS.md`、`WORKSPACE_GUIDE.md`，以及 `plugins/`、`docs/`、`data/`、`tests/`、`scripts/`、`personas/`。
- `bot.py` 已明确初始化 NoneBot，加载 `.env/.env.prod`，从 `pyproject.toml` 加载插件/适配器；注册 OneBot V11、Telegram 和一个插件内的 `ResilientMailAdapter`。代码还对 Telegram poll 和 OneBot websocket 重连日志做限流，并给 Telegram 轮询包了一层指数退避重试。
- `.env` 仅记录键名与值状态，未把密钥值写入发现文件。后续需按配置键映射到插件配置，重点审查 LLM/API、OneBot/Telegram/Mail、订阅、Web UI、运行时数据路径。
- 根目录发现已有 `.pytest_cache` 与 `.ruff_cache`，与 `AGENTS.md` 要求源码区不应保留缓存不一致；本次不删除用户数据或缓存，只记录为工程卫生问题。
- 初步代码目录集中在 `plugins/bot_unified_runtime/`，包含 capabilities、character、contracts、llm、output、policy、runtime、sender、sources/parsers、sources/subscriptions 等子包；从命名看存在统一运行时、LLM 路由、卡片渲染、订阅与解析框架，但具体完成度需以实现走查为准。
## 错误记录
- 初次用 `Get-ChildItem -Recurse` 扫描 Markdown 时进入 `.pytest_cache`，因权限被拒绝中断；已改用 `git ls-files` 加显式排除缓存目录的遍历策略，不重复该命令。
## 错误记录（续）
- 目录树命令因 PowerShell `Sort-Object` 多属性参数写法错误而未执行；改为 `Sort-Object @{Expression=...},Name`，不重复原写法。
## 错误记录（续2）
- 目录汇总命令对根目录文件的 `DirectoryName.Substring` 计算出现起始索引越界；改用安全相对路径函数区分根目录，不重复该表达式。
## 错误记录（续3）
- AST 索引首次输出 JSON 时，PowerShell 管道下 Python 使用系统 GBK stdout，遇到 Emoji 字符触发 `UnicodeEncodeError`，导致索引文件为空。改为显式设置 `PYTHONIOENCODING=utf-8` 后再运行。
## 阶段1/2补充发现

- `pyproject.toml`：依赖包含 `nonebot2[fastapi]`、OneBot、Console、Mail、Telegram、APS cheduler、localstore、filehost、ORM（但注释说明不自动加载且无项目模型）、FAISS、HTMLKit、Jinja2、MCP 等；NoneBot 本地插件目录为 `plugins`，自动加载 status/apscheduler/localstore/alconna/filehost/htmlkit，适配器配置包含 OneBot V11、Console、Telegram。未看到 FastAPI 自定义应用、Web 路由或前端构建依赖。
- `.env` 有 287 个配置键，`.env.example` 有 304 个，`.env.prod` 有 8 个；配置面覆盖 LLM、多供应商/模型、审计/诊断、订阅、音乐、天气、历史、邮件、Telegram、下载/媒体、向量知识、人格、运行策略等。当前 `.env.example` 比 `.env` 多出至少 `BOT_CARD_UI`、`BOT_CHAT_REASONING`、`BOT_CONTENT_VIDEO` 等示例键，存在示例与实际配置漂移风险。
- 未发现 YAML 配置文件；源码内唯一大型 JSON 是天气城市映射 `plugins/bot_unified_runtime/sources/data/qx.json`。NoneBot 主配置集中在 `pyproject.toml` + `.env`，第三方运行时配置按文档在外部 Runtime，不应扫描。
- 当前源码统计：222 个 Python 文件（含 50 个测试），约 163 个生产插件 Python 文件；非 Python Web 候选只有 `output/card_render/templates/universal_card.html`，另有无前端框架/静态资源/自定义 HTTP 服务迹象。
- 文档实际存在 26 个 Markdown 文件；Git 中仍跟踪但当前工作树已删除的历史/研究 Markdown 不属于本次“当前代码实现”证据，不能按现存功能计入。
## NoneBot 官方背景核对

- 官方快速上手以 FastAPI driver + Console adapter 为示例，并通过 `nb run` 启动；NoneBot2 本身是异步、跨平台、可扩展框架，平台能力来自具体 adapter/插件，而不是框架自动提供。当前项目 `pyproject.toml`/`bot.py` 符合“driver/adapter/plugin 装配”模式，但用户要求的社交/音乐站点接入仍必须由项目自己的 parser/adapter/业务逻辑证明，不能把 NoneBot 的跨平台能力当作这些平台已经接入。
## 错误记录（续4）
- 订阅引用检索中再次直接对工作区递归调用 `Get-ChildItem`，命中 `.pytest_cache` 权限错误；后续所有全树匹配均使用已定义的缓存排除函数或 `git ls-files`，不再直接递归。
## 错误记录（续5）
- 功能源文件检索假定存在 `sources/weather.py`，但当前工作树不存在该路径；天气实现实际需从 `capabilities/weather.py` 的 import 目标和真实 `sources/` 清单追溯，不重复该假定路径。
## 阶段3/4：目录与核心代码发现

- 目录映射：`plugins/bot_unified_runtime/` 是单一生产插件，分为 `capabilities/`（19 个能力）、`runtime/`（16 个运行时模块）、`sources/parsers/`（27 个解析模块）、`sources/subscriptions/`（5 个订阅模块）、`llm/`、`character/`、`contracts/`、`sender/`、`audit/`、`output/card_render/`。未发现 `frontend/`、`web/`、`server/`、`api/`、Node/Vue/React/Svelte 工程。
- NoneBot 装配：`bot.py:126-148` 注册 OneBot V11、Telegram、插件内 Mail adapter；`plugins/bot_unified_runtime/__init__.py:109-117` 声明支持 `~onebot.v11/~console/~mail/~telegram`；消息 matcher 在 `__init__.py:2040-2436` 通过统一路由覆盖 chat、content、music、subscribe、today_history、wiki、epic、weather、file、mail、meme 等。
- 内容解析注册表 `sources/parsers/__init__.py:151-423` 实际覆盖 Bilibili/B站会员购、Biligame、微博、小红书、YouTube、Twitter/X、小黑盒、米游社、森空岛/深空岛、库街区、Pixiv、Lofter、无差别同人站、米画师、Telegram 及网易云/QQ/酷我/酷狗/Apple Music/Spotify；并有 Cookie、代理、Playwright 绑定逻辑 `:435-541`。这证明“链接解析”比“平台完整生态接入”更广，但不等同于各平台有发布订阅/搜索/推送 API。
- 点歌搜索提供方实际只有 6 个：网易云、Apple Music、酷狗、QQ音乐、酷我、Spotify（`sources/parsers/__init__.py:425-433`）；未出现汽水音乐，亦无独立的 iPad 免费游戏能力。
- 免费游戏：只有 Epic `sources/epicfree.py` + `capabilities/epic.py`，调用 Epic 免费促销接口并由 `base_router.py` 路由；代码/帮助中没有 iPad/App Store/Steam 本周免费游戏查询。
- 天气：`capabilities/weather.py` 调用 `sources/nmc_weather.py`，内置区县表与中国气象局 NMC 查询；支持 `天气`、`支持区县`，但实现为同步网络调用。
- 历史上的今天：`capabilities/today_history.py` + `sources/today_history.py`，配置缓存/推送文件，`__init__.py:855-975` 用 APScheduler 按目标注册每日 cron，并走统一发送流水线；具备核心查询和定时推送骨架。
- 搜索/聊天：`sources/web_search.py` 有可选的 DDG→Bing 链式同步/异步搜索、正文抽取和并发多查询；`capabilities/chat.py` 按意图决定知识库/联网回退，并把命中数写入审计，但 `BOT_WEB_SEARCH_ENABLED` 默认关闭（`config.py:177-190`）。
- LLM：`llm/model_router.py` 支持注册表、模型预设、优先级、时段优先级组、手动模型、候选 failover、API key 槽位和 reasoning effort；`llm/providers.py:298-470` 是同步 `urllib` OpenAI-compatible provider，支持 token usage、tool_calls、响应 schema/HTTP 错误分类。没有余额查询协议或供应商账户 API 封装。
- 用量/费用：`runtime/pricing.py` 按百万 token 价格计算；`sources/runtime_event_log.py:123-235` 从成功 transport 日志按日期/时间范围、模型聚合 token/cost；`runtime/usage_monitor.py:41-431` 实现阈值（输入/输出 token、当日费用）和 13/18/23 点定时管理员告警卡/文本。它是日志聚合与 QQ 预警，不是 Web 监测中心；未发现按会话/All 的完整多维查询 API或柱/线/雷达/饼/散点图生成。
- 音乐榜单：`sources/music_charts.py` 只有可注入 registry/protocol，`MusicRequestStore` 有表结构；当前代码没有实际注册的外部榜单 source，`BOT_MUSIC_CHART_ENABLED` 默认 false。
- 订阅 V2：`sources/subscriptions/social_v2.py` 注册 Bilibili、小红书、YouTube、Twitter/X、Telegram 公共频道、Pixiv、微博 7 个 adapter（`ADAPTERS` 在 1170-1178）；`music_v2.py` 只识别/提供网易云/QQ/酷我/酷狗/Apple/Spotify 的部分目标与网易云等分支，文档明确 QQ/酷我/酷狗/Spotify 动态与真实榜单未完成。
- 订阅调度：`subscription_runtime_v2.py` 注册 poll/outbox 两个 interval job；`subscription_scheduler.py` 有租约、并发节流、抖动/退避、baseline、outbox 投递；`subscription_store_v2.py` 有 SQLite schema。但 `capabilities/subscribe_v2.py:60-62` 在同步 capability 中调用 `asyncio.run(adapter.resolve_target(...))`，而它由 NoneBot async handler 直接传入普通 `pipeline.handle`（`__init__.py:2690-2720`），在事件循环中添加订阅可能触发 `asyncio.run() cannot be called from a running event loop`。
- 文件能力：`capabilities/file_exchange.py` 有管理员文件接收/代码调试入口与 docx/xlsx/pptx/pdf 导出函数；`__init__.py:2082-2160` 处理 QQ group upload/private offline_file。但输入解析/调试依赖当前实现和管理员白名单，未发现对 `.doc` 老格式或“自主生成任意 Python/源码文件”的完整通用工作流。
- 异步风险：`RuntimePipeline.handle_async` 只 await capability；同步 capability 会在事件循环线程执行。OFFLOADED_CAPABILITY_IDS 仅含 context/help/llm/dialogue（`__init__.py:140-147`），而 content/music/weather/epic/today_history/subscribe 的网络/文件/数据库操作没有统一 offload；`OpenAICompatibleLLMProvider.generate` 由 chat 包装成 `offload_capability`（`__init__.py:1949-2006`），所以聊天主链单独处理了这个风险。
## 验证错误记录
- 2026-09-05 运行规定入口 `scripts/dev.ps1 -Task test` 失败：脚本第 230 行尝试在源码工作区创建 `pytest_ci_43640` 临时目录，权限拒绝；尚未执行测试。下一步先读取脚本的临时目录配置，改用脚本支持的外部临时目录或在失败后采用 `PYTHONDONTWRITEBYTECODE=1` 的只读 AST/pytest 备选，不重复同一调用。
## 验证错误记录（续）
- 规避 `dev.ps1` 外部 Runtime 临时目录后，用工作区 Python 直接执行 `python -m pytest -p no:cacheprovider` 仍无法运行：当前 Python 3.12 环境未安装 `pytest`（`No module named pytest`）。未安装依赖，避免改动外部环境。
## 验证错误记录（续2）
- `scripts/dev.ps1 -Task lint` 找到外部 Runtime 的 Ruff，但 Ruff 试图写 `ChatBot_Runtime\cache\ruff\...` 时被沙箱拒绝，退出码 2；这不是 Ruff 代码诊断结果。后续用同一 Ruff 可执行文件把缓存目录重定向到系统临时目录，避免重复外部 Runtime 缓存写入。
## 验证错误记录（续3）
- 将 Ruff 缓存重定向至系统临时目录后，lint 真正执行并发现 6 个问题：`runtime/pricing.py:12` 未使用 `Any`；`runtime/pricing.py:63`、`runtime/usage_monitor.py:291` 多余 `int` 转换；`runtime/usage_monitor.py:302/370/405` 未使用 `BLE001` noqa。未修改业务源码，报告将列为当前工作树质量问题。
## 验证错误记录（续4）
- 外部 Runtime venv 的 pytest 成功收集 279 项，首轮输出 `240 passed, 39 errors`；39 个错误集中于 pytest 临时目录/`tmp_path` 在系统 Temp 的权限拒绝（未显示业务断言失败），因此该轮不能作为完整通过依据。下一步用允许写入的可视化工作区设置 `--basetemp` 与 TMP/TEMP 重跑，不重复原临时目录。
## 验证错误记录（续5）
- 第二轮 pytest 改用可写可视化目录后仍在 `tests/test_file_exchange.py` 的错误之后长时间无新输出，持续约 2 分钟未结束，已人工中断；没有获得完整通过/失败结论。最终报告只引用首轮明确的 `240 passed, 39 errors` 及错误均集中在临时目录权限的输出，并明确测试基线未能完整验证。
## 配置一致性补充

- AST 对 `config.py` 的 305 个 Pydantic 配置字段与环境键核对：`.env` 的 287 个 BOT_* 键均可映射到 Config；`.env.example` 304 个键也没有出现无法映射的 BOT_* 键，但示例相比实际 `.env` 多出 19 个键（包括传输预算、usage 监控、订阅卡、vision mode、外部 localstore 路径），实际 `.env` 另有 `BOT_API_KEY_QIANQIANYE_NIGHT`、`BOT_VISION_REPLY_PROBABILITY` 两个示例未列键。配置字段数量大、可维护性和示例同步仍有风险，但不是“未知键被丢弃”的直接问题。
## 错误记录（续6）
- 自定义 Web UI 静态检查使用 `git ls-files` 路径清单时，Git 的非 ASCII 路径转义与 PowerShell 参数传递不兼容，某个中文人格文档路径被错误拼接，导致 `Select-String` 报不存在。结论改用已成功的显式排除遍历/文件扩展名清单，不重复该路径传递方式。
## 错误记录（续7）
- 查询订阅旧/新注册函数引用时，PowerShell 对带括号的 `Select-String -Pattern` 参数解析失败；不影响已有 AST/文本证据，后续若需精确引用改用单独变量 `$pattern = [regex]::Escape(...)` 并明确命名参数。
## 最终交叉比对结论（2026-09-05）

### 平台层
- 通信：QQ=OneBot V11/NapCat 已接入；Telegram=官方 NoneBot adapter + public channel parser/subscription；Mail=插件内 ResilientMailAdapter + MailBridge 收信/发信/Telegram 管理员提醒。
- 社交：Bilibili、XHS、微博、X/Twitter、YouTube、Pixiv 均有链接解析与 V2 订阅；萌娘百科、米画师、无差别同人站、Lofter、库街区、森空岛/深空岛、米游社只有解析，没有订阅 adapter。`social_v2.py` 的 ADAPTERS 明确只有 7 个社交源。
- 音乐：网易云/QQ/酷我/酷狗/Apple Music/Spotify 有解析/搜索（Spotify 搜索函数当前返回 None），汽水音乐无代码；音乐订阅 adapter 可解析多个 provider 目标，但默认 fetch 只有网易云实现，其余返回 unsupported。
- 游戏/其他：Epic 每周免费游戏已实现；Steam 只有链接解析；B站会员购只有商品链接解析；小黑盒只有社区链接解析；NGA 未发现独立 parser/adapter/service；iPad/App Store 免费游戏无实现。

### 核心功能状态
1. 历史上的今天【部分实现】：外部百度接口+JSON 日缓存+标题/年份输出+定时推送；没有以数据库为主的事件查询，也没有稳定的事件梗概字段。
2. 免费游戏【部分实现】：Epic 已有；iPad/Steam 本周免费查询完全缺失。
3. 点歌【部分实现】：6 个音乐搜索提供方和卡片/链接/语音/音频文件路径；汽水缺失、Spotify 搜索为空、播放更像下载/发送而非播放器。
4. 订阅推送【部分实现】：V2 store/scheduler/outbox/增量游标/退避/7 社交 adapter + 网易云分支；长尾社交和 5 个音乐 provider 的真实抓取缺失；add 路径存在 `asyncio.run` 事件循环风险。
5. 天气查询【已完成】：NMC 区县索引+当前天气查询+错误降级；天气命令由 `BOT_WEATHER_QUERY_ENABLED` 控制，实际 `.env` 中通用 `BOT_WEATHER_ENABLED=false` 与命令开关语义分离，需文档化避免误解。
6. 基础聊天【已完成】：真实 OpenAI-compatible provider、人格/知识/记忆、路由、可选 DDG→Bing 搜索、视觉转文字、失败转移；联网默认配置值和运行态需注意，依赖外部凭据/代理。
7. 文件处理【部分实现】：QQ 管理员收文件，`.py` 受限调试，`.md/.txt/.json/.yaml/.yml/.toml/.csv` 仅读取确认，LLM 生成 Markdown 并导出 `md/docx/pptx/xlsx/pdf`；无 `.doc`/旧 `.ppt`/旧 `.xls` 输入解析、无通用 PDF/PPT/Excel 内容读取和自主代码文件生成。

### Web UI 状态
- 9 项没有独立前端/后端 Web API。唯一 HTML 是 `output/card_render/templates/universal_card.html`，它是聊天信息卡模板，不是控制台 UI。
- 后端已有可复用能力：runtime model registry/priority/schedule/effort、`/bot llm` 诊断、console_chat、usage aggregation/threshold alerts；这些都通过 NoneBot 命令/定时任务/QQ 推送，不是 Web UI。
- 因而供应商管理【完全缺失 Web UI】；LLM 登记管理/排序【部分实现（命令后端，无 Web）】；余额【完全缺失】；游乐场【部分实现（本地 Console，无 Web）】；多 LLM 对比【完全缺失】；控制台【部分实现（本地 PowerShell/Console，无 Web terminal）】；监测中心【部分实现（日志聚合，无 UI/图表/完整时间维度）】；费用预警【部分实现（后端 QQ 预警，无 Web 配置/面板）】。

### 质量与验证状态
- 当前工作树包含大量未提交修改/删除；报告基于工作树，不能等同于 tag `v0.0.1-alpha.1` 的历史状态。
- Python AST 解析 222 文件无语法错误；docs-check/plugin-check/runtime-layout 通过。
- 规定 test 入口受 Runtime 临时目录权限阻断；直接外部 venv pytest 收集 279 项，首轮为 240 passed/39 errors，错误为 tmp_path/Temp 权限；第二轮改 basetemp 后长时间无进展而中断，不能称全绿。
- Ruff 缓存改到 Temp 后可运行，但当前工作树有 6 个 lint 问题，集中在 `runtime/pricing.py` 与 `runtime/usage_monitor.py`。
## 最终验证补充（2026-09-05）

- AST：222 个 Python 文件全部解析成功，`ast_errors=0`。
- `scripts/dev.ps1`：`docs-check=0`、`plugin-check=0`、`runtime-layout=0`；运行时边界检查通过，源码生成目录为空，Python bytecode absent。
- Ruff：使用外部 Runtime venv 且缓存重定向后退出码 1，稳定复现 6 个 lint 问题；不修改代码。
- pytest：由于前述 `tmp_path` 权限错误与第二轮无进展中断，没有全套新结论；报告明确标记为“未完成验证”，不宣称通过。

## 2026-09-05 后端核心切片发现

- `backend-smoke` 已通过现有 `RuntimePipeline` 执行一轮聊天，实际返回 `receipt_state=sent`、`capability_id=bot.chat`、`knowledge_chunks=8`，默认不启用联网搜索。
- `startup-smoke` 初始因订阅 V2 数据库 lock 文件 PermissionError 导致插件导入失败；加入可选订阅 fail-open 后，插件加载成功，当前 dry-run 注册 20 个 matcher。
- `console --message` 已存在单轮逻辑，但作为统一后端合同缺少结构化 JSON、稳定退出码和安全字段过滤；新增 `backend_unit.py` 补足该边界。
- 当前 Git 工作树含大量既有未提交变更；本轮必须只暂存新增执行单元、相关测试、脚本和文档，不能使用 `git add -A`。

## 2026-09-06 PowerShell 与搜索 API

- 用户粘贴的所有 smoke 错误共因是 Windows PowerShell 5.1 无法解析 `scripts/dev.ps1` 的帮助 here-string；改为字符串数组并用 UTF-8 BOM 保存后，`powershell.exe -File` 与 `powershell.exe -Command` 均可执行。
- 本轮 API 链为 Tavily -> You.com -> LangSearch；TinyFish 为可选正文抓取，Bing 未进入新 API 链。未配置 key 时 provider 链为空并安全返回空结果。
- 官方文档浏览器 CDP 核验因本机调试代理超时未完成，因此 TinyFish endpoint 不写死；所有 endpoint 以 `.env` 可覆盖配置为准。

## 2026-09-06 搜索 API 与 PowerShell 兼容结论

- Windows PowerShell 5.1 不能正确解析原 `Show-Help` 的双引号 here-string；替换为字符串数组并以 UTF-8 BOM 保存后，`-File` 与 `-Command` 两种入口都可执行。
- 真实搜索 key 未配置时，`build_web_search_provider(Config(bot_web_search_enabled=True))` 生成空 provider 链并返回空结果，不请求网络。
- 当前 API 链提供 Tavily、You.com、LangSearch 搜索适配；TinyFish 同时有搜索适配和可选正文抓取适配，但正文 endpoint 必须由本地配置明确提供。
- `BOT_WEB_SEARCH_PROVIDER_OPTIONS` 按 provider 接受 headers/params/body 和任意供应商原生字段；密钥通过 `env:` 引用解析，不能写入 options。
- `runtime-layout` 仍会报告源码目录已有 ignored `data/` SQLite/settings 文件；未删除，因为活动数据的所有权和迁移目标尚未确认。

## 2026-09-06 上下文编译器与五层合同设计判断

### Runtime 迁移分类

- `data/knowledge_embeddings.sqlite3`、`data/meme_library.sqlite3`、`data/settings/runtime_settings_default.json` 属于疑似运行态残留；不能直接移动，需停机、快照、SQLite integrity_check、复制到 Runtime 临时目录、切换绝对路径、跑 runtime-layout/config/context/startup/backend smoke 后再保留回滚窗口。
- `.env`、`.env.prod`、Cookie、浏览器会话、Mail 状态、订阅状态和任何密钥不自动迁移；它们需要独立的权限控制和凭据轮换策略。
- `personas/` 与可版本化的世界观/知识 Markdown 继续留在源码或受控内容目录；迁移到 Runtime 的应是向量索引、倒排索引、实体图、缓存和审计数据，而不是失去版本来源的原始知识副本。

### 新模型

采用“上下文编译器（Context Compiler）”而不是全文 RAG 注入：问题先由意图/任务规划器拆成子问题，再做混合召回；召回结果被压缩成带来源、时间、权威等级、置信度和冲突状态的原子事实；只把与回答计划相关的事实账本、短时记忆摘要和工具结果交给 LLM；输出后做事实覆盖、冲突和引用校验。

五层合同是：PersonaPolicy、WorldModel、EvidenceLedger、Memory、ToolAction。五层不是五段固定 prompt，而是五种可版本化数据/策略合同，运行时通过 DecisionContext 编译成最小上下文。

群聊采用 Public Scene State：滚动窗口、话题聚类、重复短语检测、参与者/目标识别和社会行为特征；机器人读取的是公共场景摘要，不把全群原文塞给模型。个人长记忆与群公共状态严格分离。

## 2026-09-06 防御型上下文编译器设计

- 用户确认采用复制验证迁移，并将旧数据整合为一次可恢复归档；当前判断为“可迁移但不可直接移动”。迁移对象只包括可证明的派生索引/非敏感运行设置；`.env`、Cookie、Mail 状态、浏览器会话、订阅状态和未知来源记忆不自动迁移。
- 新算法采用信任分层、污点追踪、结构化事实卡片、证据账本、回答计划、工具授权票据和输出后校验；任何用户/网页/工具返回内容都不能升级为系统规则、人格规则、世界观真相或工具权限。
- 世界观采用版本化 claim graph；网络证据只进入 EvidenceLedger，不自动写入 WorldModel；长时记忆采用候选→策略审核→事务写入，不允许模型直接覆盖或删除记忆。
- 群聊采用 PublicSceneState，不把群聊全文注入；用时间窗、话题线程、重复短语、参与者数量和当前消息相关度决定是否生成轻度社交反应。
- 工具采用 ToolCatalog + schema 校验 + 权限/副作用/超时/预算/幂等键/审计；搜索和网页正文是只读工具，发送、写记忆、改配置和文件操作是受控副作用工具。
- 2026-09-06：用户确认图片已经能够回复，图片实机接收与回复闭环验证通过。

## 2026-09-06 详细回答与模型路由问题

- 当前 `.env` 显示 `BOT_CHAT_FAST_MODE=true`、`BOT_CHAT_FAST_MAX_TOKENS` 与 `BOT_CHAT_MAX_TOKENS` 受限，且运行时回答规则仍写着“知识问答一两句定性、只挑最关键的一两点”，这是游戏人物/关系回答偏短的直接原因之一。
- 当前 `ModelSpec.priority` 仅用于 `(priority, model_id)` 排序；注册表和运行时命令都允许重复 priority，没有移动槽位或唯一约束。
- `_build_memory_writer()` 单独构造 `_build_chat_llm_provider(config)`，没有复用主聊天 `ModelRouter`；主聊天成功而 memory extraction 401 的根因是配置/凭据路径分叉。

## 2026-09-06 修复后确认
旧的 fast mode/独立 memory provider 描述属于修复前诊断，不代表当前状态。现已复用 ModelRouter，保留 alternate keys，并修复 Config 凭据引用；独立调用状态不等同于固定复用上一条回复的实际模型。详细配置已传入生产构造器，搜索上下文不再依赖正文抓取开关。启动关闭抽取时仍需要本地启用并重启。完整限制和 TODO 见 docs/chat-memory-routing-fixes-2026-09-06.md。

## 2026-09-06 群聊与来源质量确认
群聊出站代码本身只发送 OneBot text segment，未发现主动添加 reply 段；问题按“模型整包外引号”处理：只剥离整条匹配外引号，内部引用不动。维基 opensearch 不是身份查询，现改为精确标题优先并拒绝低相似候选。无效 Netscape Cookie 现在不会进入 yt-dlp，避免重复堆栈和敏感行泄露。

## 2026-09-06 22:40 续修交接
- 按句引号、Wiki 列表条目、小红书 discovery 路由、Cookie 内存规范化与降噪、doctor 解释器路径、mypy 类型问题已处理。
- 四个用户 Wiki 查询已通过公开 API 真实入口复验；QQ 和用户 Cookie 平台实机验收未代做。
- 以 docs/live-chat-followup-2026-09-06.md 为本轮准确说明；此前整份 Cookie 跳过和仅整条引号清理描述已过时。

## 聊天最终自然语言输出收尾
- [complete] bot.chat 正文和最终渲染文本/分段/图片说明接入确定性纯文本整理；不改人格 Prompt、不增加模型调用。
- [complete] 用户宝宝样例、Markdown/LaTeX、模拟 OneBot 最终 payload 定向回归通过。
- [pending] 用户重启实际运行进程后 QQ 实测；审计标识 chat_plain_text:v1。详见 docs/chat-plain-text-output.md。

## 2026-09-07 Phase 0-3 完成记录
- [complete] 64K 输出预算/科普详细策略、统一 quote/forward/mixed message、文件读取/生成文件、安全边界基线已接入。
- [complete] 完整 verify：343 passed、Ruff 通过、mypy 173 源码文件通过。
- [pending] Telegram 评论树 API 补拉、老格式文件依赖、生成文件扫描/清理和更强语义安全分类器。
- 详见 docs/phase0-3-implementation-2026-09-07.md。

## 2026-09-07 Phase 4-5 续修
- 文件生成改为原始回复抽取并调用真实 OneBot 上传 API；安全拒绝改为人格化模型回应/兜底。
- Phase 4 文本戳一戳冷却已注册；Phase 5 Wiki 游戏摘要已接入。Telegram 评论树、真实 NapCat poke、复杂 Wiki 仍待实机验收。

## 2026-09-07 最终收尾发现

- 之前 Phase 0-3 文档中的 343 passed 已过时；最后一次完整 verify 为 352 passed、Ruff 通过、mypy 174 源码文件通过。
- `backend-smoke` 明确使用 static provider；`backend-base-smoke` 明确使用 fake OneBot；两者都不能替代真实 NapCat/真实 LLM 验收。
- `doctor` 当前通过，`nb_cli=ok`、`ready_for_nonebot_run=true`。
- `runtime-layout` 当前仍失败，检测到源码 data 运行产物和 156 个 Python 缓存路径；清理前必须完成 Runtime 归档和数据库完整性校验。
- `.env.example` 原有重复 `BOT_CHAT_MAX_TOKENS/BOT_CHAT_FAST_MAX_TOKENS` 已统一为单一 65538 配置。
- 最终状态、用户要求和未完成清单见 `docs/handoff-final-2026-09-07.md`。

## 2026-09-07 alpha.2 发现

- `%TEMP%\pytest-of-LancyCelestia\pytest-current` 是指向父目录的循环符号链接且 DACL 拒绝访问（未提权无法删除），曾导致 pytest 会话收尾崩溃；已通过 dev.ps1 固定 basetemp 根治，测试从崩溃变为 7 秒级稳定。
- mail bridge 测试此前把状态文件写进源码树工作目录，与运行中的机器人实例和 Windows 文件扫描器竞争造成 `os.replace` WinError 5 偶发失败；已迁到 pytest 临时目录并加重试。
- 12 个社区插件对比结论：无整插件可安全替换（架构边界/许可/维护状态三重原因），采纳点均为局部思路；详见 `docs/plugin-benchmark-2026-09-07.md`。
- `provider_options` 自定义键透传请求体是既有能力，Tavily `search_depth`/`time_range` 无需改码即可用。
- 源码树 `.ruff_cache` 残留已删除；`data/` 等活动运行数据仍未触碰，runtime-layout 依旧失败属预期。
