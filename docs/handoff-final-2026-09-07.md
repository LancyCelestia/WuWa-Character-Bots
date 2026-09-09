# 守岸人 Bot 交接手册（活文档）

> 整理日期：2026-09-09 · 分支 `v0.0.1-alpha.2` · 工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
> 本文件取代此前 24 轮追加式交接记录；被压缩的原始流水账在 git 历史里（`git show 10a2272:docs/handoff-final-2026-09-07.md` 可回溯旧版全文）。
> 规则：每完成一项交付，同步更新本文件对应小节；不再新开「增补章节」。

## 1. 系统现状

NoneBot2 + OneBot V11（NapCat）QQ 聊天机器人，附带 Telegram / Mail / Console 适配器。已上线：统一消息管线、37+ 平台链接解析（Mica 卡图渲染）、多供应商音乐点歌（卡图+语音）、四家搜索 API、模型路由与故障转移、记忆/人格/知识库、安全防线、订阅推送、运维告警。当前是功能完整、持续迭代的 alpha；不是全部需求完成的生产版。

当前验证基线：**600 passed / Ruff 全过 / mypy 200 文件**（`dev.ps1` 三门禁），每轮交付后必须保持全绿。

## 2. 硬约束

- 人格源文件、世界观源文件只读，AI 不得改写。
- Runtime 数据（SQLite/FAISS/向量库/记忆/Cookie/订阅/媒体缓存/日志/venv）不得删除；旧数据先归档验证再清理。
- 密钥不入库不入聊天：真实 key 存 `.env`（在 `.gitignore`），链路字段用 `env:变量名` 间接引用。
- 推送 origin 仅按用户明确指示执行；commit 禁用 `git add -A`（会裹挟并行会话的半成品——实际踩过坑）。
- 源码树不产生缓存（`__pycache__`/.pytest_cache 等）：测试走 `dev.ps1`，绕开时必须 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp` 指到源码树外。
- 工作区边界：`ChatBot_Runtime`、`ChatBot_Archive`、上层目录默认不扫描不修改；AI 唯一默认工作区是本仓库。

## 3. 架构与消息主链路

```text
NapCat(OneBot V11 WS 服务端 127.0.0.1:3001, token ShoreKeeper)
  -> NoneBot OneBot Adapter（bot 是 forward-WS 客户端，.env.prod ONEBOT_WS_URLS；NapCat 起来后自动重连）
  -> _incoming_from_nonebot_event() -> IngressGateway -> IncomingMessage
  -> 路由/权限/限流/安静时间/群策略（幂等表可选，默认关）
  -> RuntimePipeline -> CapabilityResult
  -> Review/文本整理/媒体投影 -> RenderedOutput -> SendRequest
  -> SendQueue(SQLite) -> UnifiedDeliveryGateway
  -> sender.onebot（QQ 富消息）/ sender.nonebot（TG 图文+语音+文件 / Mail / Console）
```

关键文件：`bot.py`（启动+崩溃守卫）；`plugins/bot_unified_runtime/__init__.py`（handler 装配、能力分发，约 4700 行）；`runtime/pipeline.py`、`runtime/ingress.py`；`sender/onebot.py`、`sender/nonebot.py`、`sender/gateway.py`、`sender/queue.py`。

TG 发送要点（`sender/nonebot.py`）：图片支持 http 直链**和本地文件**（适配器原生 multipart）；语音走 `_prepare_telegram_voice`（sendVoice 仅认 OGG/OPUS，ffmpeg 转码，失败降级 sendAudio，缓存 `%TEMP%/bot_tg_voice`）；空文本+有媒体部件不再 SKIPPED；媒体全部不可发时显式失败不静默。

## 4. 启动、验证与门禁

```powershell
# 门禁（每轮交付前全绿）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"        # 600 passed
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"       # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"  # mypy

# 启动前体检
dev.ps1 -Task doctor / backend-base-smoke / backend-smoke / search-smoke / runtime-layout
```

- 启动：`ChatBot_Runtime\venv\Scripts\python.exe bot.py`（确认只有一个实例；**先查进程启动时间再查代码**）。
- 日志：`dev.ps1` 启动重定向到 `ChatBot_Runtime/logs/nonebot.out.log`；手动控制台启动不落盘。
- NapCat 启动：`C:\Software\NapCat\login-bot.bat`（快速登录守岸人 3958874605，UAC 确认）；验证 `netstat -ano | findstr 3001` 出 LISTENING + bot 进程 ESTABLISHED。

## 5. 数据、密钥与配置

- 运行数据根：`ChatBot_Runtime/`（data/cache/logs/venv/git 元数据）。`data/` 前缀路径自动重映射 Runtime 根。
- Cookie：`ChatBot_Runtime/data/platform_cookies.txt`（Netscape 格式，17 平台域名映射 `sources/parsers/cookies.py`）；管理员指令 `/bot cookie import <平台> <Cookie头>` 热写入。
- 关键 `.env` 项：`BOT_CHAT_*`（provider/model/max_tokens 65538）、`BOT_SEARCH_TAVILY/YOU_API_KEY`、`TELEGRAM_BOTS`、`TELEGRAM_PROXY=http://127.0.0.1:7890`、`BOT_DOWNLOAD_PROXY`、`BOT_MUSIC_CANDIDATES_ENABLED=true`、`BOT_EVENT_IDEMPOTENCY_ENABLED`（默认 false）、`BOT_DISCONNECT_NOTICE_*`。
- Prompt 审计：默认记录脱敏消息与上下文摘要；人格 Prompt 预算优先级 人设>知识库>短时对话>长时记忆。

## 6. 子系统速查

### 6.1 命令与路由
统一格式 `/bot <模块词> <功能词> [参数]`；命令别名表 `runtime/aliases.py`。`/bot help` 出 Mica 手册卡（双列分类网格+命令药丸，参考小维帮助风格）；`/bot help <模块>` 出该模块说明书页；分类名可直查（如 `/bot help 大模型`）。命令详情以 `COMMANDS.md` 与 `_HELP_ENTRIES`（`capabilities/echo.py`）为准。

### 6.2 链接解析器
入口 `sources/parsers/__init__.py`（`build_content_parser_registry`：平台路由表+Cookie 绑定+代理绑定）；实现按平台拆 `platforms_*.py`。覆盖 bilibili/YouTube/Twitter-X/小红书/知乎/豆瓣/TapTap/贴吧社区/虎扑/全民K歌/抖音站系等 37+ 条目。公共设施：`wbi.py`（B站签名键 30 分钟缓存）、`http_util.py`（代理/UA/重试）、`cookies.py`。
已知边界：小红书 2026 版 INITIAL_STATE 无标题（用 desc 兜底）；X 纯媒体推文走 fxtwitter 深分支（`code==200` 门槛）；YouTube 字段=watch 页正则+innertube 端点+about 页三层合并。

### 6.3 卡片渲染（Mica 规范）
管线：`capabilities/content_parser.py:render_card_png`（合成 ParsedContent → payload → HTML → playwright 截图，线程内常驻浏览器）→ `output/card_render/`（bridge 投影 + `templates/universal_card.html`）。规范：底色由 `PLATFORM_COLORS`（bridge.py）经 `--pc` 变量 `color-mix` 派生，禁写死品牌色；单柔光阴影；125% 缩放语义；`body` 透明背景。已接卡：链接解析、点歌、帮助、天气、免费游戏。改卡后必跑三门禁+样例截图核对（临时脚本放 `%TEMP%` 子目录）。

### 6.4 音乐点歌
5 供应商（网易云/QQ/酷狗/酷我等，`platforms_music.py`）；模式 `card+voice+link` 可组合（`/bot music mode`）；多候选编号选歌（`BOT_MUSIC_CANDIDATES_ENABLED=true`，会话 TTL 300s）；QQ 端出 Mica 歌曲卡图（**替代 CQ:music**——NapCat 无 musicSignUrl 会拒签并中断整条消息）+语音+♪文本；TG 端封面/卡图+caption+语音。

### 6.5 搜索 API
Tavily 主、You.com 备、LangSearch 备、TinyFish 搜索+正文抓取；不接 Bing。链式回退+瞬时重试；Tavily 一级参数 `search_depth/time_range`；抓取回退链 TinyFish fetch → Tavily extract → 通用 `fetch_page_text`（含反注入去噪）。验收工具 `dev.ps1 -Task search-smoke`。Tavily/You/TinyFish 已真实 key 验收；LangSearch 未验。

### 6.6 模型路由（渠道化）
**45 个注册条目**（`.env BOT_MODEL_REGISTRY`），8 家供应商：浅夜（Gemini 置顶）/恒星纪元/ToolCode/umi（含 Claude 四渠道、GLM/Kimi/MiniMax 新组）/DeepSeek 官方/智谱/StarAPI/hcn 兜底。
- 选择：手动指定 > 时段组 order > 基础 priority（1..N 唯一槽位）> 故障转移同序；**`/bot model set <实际模型名>`（如 gemini-3.8-flash-high）自动聚合该模型全部渠道，按价格升序转移**（条目带 `price_in/price_out`）。
- **渠道健康巡检**（`llm/channel_health.py`）：每小时全渠道最小调用探测（后台 3 线程+0.4s 错峰防限流；手动 `/bot model probe` 8 并发）；连续 2 次失败标「⛔暂时不可用」移出故障转移队列，30 分钟重探恢复即回队，**永不自动删除**；全部不可用时放行原队列防全瘫。`/bot model health` 出运维报告（含【需要你处理的】行动清单）、`/bot model routes <模型名>` 列单模型全渠道。
- 失败话术：私聊 LLM 失败回 12 条守岸人人格话术（`_PERSONA_FAILURE_MESSAGES`，会话内轮换）；群聊静默。
- 指令族 `/bot model list|set|add|update|priority|think|effort|price|remove|reset|usage|health|probe|routes`；密钥 `env:` 引用，**对应 `bot_api_key_*` Config 字段必须存在**（env: 解析链=os.environ→Config 字段回退，缺字段=config_missing 全渠道失败——09-09 事故根因）。
- 请求总预算 150s（`bot_request_budget_seconds`）；**预算耗尽不再丢弃已生成回复**（发送给足传输超时）。记忆抽取复用主路由。

### 6.7 记忆/人格/知识库
`character/affinity.py`（动态好感度/印象标签/昵称自学）；`security/memory_sanitize.py`（记忆清洗→隔离表）；知识库为向量检索（`character/vector_knowledge.py`，含 FTS）；「历史上的今天」本地 365 天库。人格 Prompt 注入预算见 §5。

### 6.8 安全防线
`security/content_safety.py`：硬类别（NSFW/血腥/政治/骚扰）+软类别（强加称谓/宠物化/人格破坏/侮辱外号）；管理员放宽软类别不放宽硬类别。输出侧 `output/plain_text.py`（去引号/Markdown/LaTeX 噪声）+ 说人话层。文件读取视为不可信数据，不执行代码。

### 6.9 订阅
`sources/subscriptions/`（social_v2 等）+ `capabilities/subscribe_v2.py`；推送走视觉渲染管线；详见交接历史与 `docs/` 订阅文档。

### 6.10 多适配器
Telegram（轮询+韧性重连+堆栈降噪，`bot.py` 过滤器）；Mail（`mail_adapter.py` 韧性适配器+`mail_bridge.py`）；Console。掉线通知 `runtime/disconnect_notice.py`（TG/邮件/Server酱/PushPlus，默认关）。

### 6.11 运维告警
`runtime/alerts.py`：按 (stage,kind,adapter,bot,target) 300s 窗口抑制；`llm deadline_exceeded` 不通知（常态降级）；result-unknown 记账 `runtime/result_unknown.py`（重连对账不盲发）。

### 6.12 视觉与字幕
**图片直传（vision direct，默认）**：聊天图片不再经 VLM 转译中间层，直接以 data URL 进主模型消息（`build_direct_vision_messages`）；`supports_vision` 默认全部渠道支持（`text-only` 标签排除）；relay（VLM 转译）保留为 direct 失败兜底；`/bot model vision mode relay|direct` 可切。
**字幕总结**（`BOT_PARSE_SUBTITLE_SUMMARY=true` 已开）：B站 AI 字幕（player/wbi/v2，ai-zh 优先，连续重复去重）+ 油管 captionTracks（ASR 滚动重叠去重）→ 摘录进文本/卡，主路由出【AI字幕总结】。

### 6.13 吃什么（bot.eat）
`吃什么` 随机推荐（Mica 卡图+文本）/`吃什么 三选一`/`吃什么 不辣`；`菜谱 <菜名>`/`怎么做 <菜名>` 查做法（本地 60 道库，未收录走 LLM 生成）；带忌口/食材约束自动 LLM。菜品图：`Runtime data/food_images/<菜名>.jpg`。库在 `sources/food_data.py`，能力 `capabilities/eat.py`。

## 7. 排障手册（实战沉淀）

| 症状 | 第一步诊断 | 处置 |
|---|---|---|
| 「改动没生效」 | 查进程启动时间 vs 提交时间（`Get-Process python`），再 grep 代码确认 | 重启 bot；确认没有第二个旧实例 |
| NapCat「已登录，无法重复登录」/3001 不监听 | `Get-Process QQ | Select Id,StartTime` 查多代际并存 | 提权清场（先杀看门狗父进程再杀 QQ/QQEX/NapCatWinBootMain）→ `login-bot.bat` 快速登录；bot 自动重连 |
| 二维码不刷新 | QQ 构建号超出 NapCat 支持表（日志「未找到对应版本的偏移数据」） | 上游问题等 NapCat 新版；启动后 2 分钟内扫首码 |
| pytest 会话收尾崩溃 | 共享 %TEMP% 的 pytest-of-* 循环符号链接 | 走 dev.ps1（已固定 basetemp） |
| git push 408/断 | 代理掐大包 | 分片推送（逐提交+重试）；分支标签同名必须完整 refspec `refs/heads/...` |
| fetch 报 reference broken | gitdir 在 `ChatBot_Runtime/git`，remote ref 文件可能损坏 | 用 `git ls-remote` 取正确哈希直写该文件 |
| bash 里 PowerShell `$_` 报错 | Git Bash 吞 `$` | 写 .ps1 脚本文件执行；Windows 路径用 cygpath -w |
| 源码树出现缓存 | 绕开了 dev.ps1 | `PYTHONDONTWRITEBYTECODE=1` + basetemp 外置；勿跑 runtime-layout 前手动删 |

## 8. 修复史索引（2026-09-07 → 09-09，详情见 git 提交与旧版文档历史）

| 日期 | 主题 | 要点 |
|---|---|---|
| 09-07 | alpha.1 收尾交接 | 统一管线/文件读写/输出整理/安全基线/Wiki 定向修复/poke；352 passed |
| 09-08 | 测试基建 | pytest basetemp 修复、mail_bridge 测试竞态修复 |
| 09-08 | 12 插件硬对比 | 吸收 htmlrender 常驻浏览器、memes 守门加载；其余 10 项原生胜出（矩阵见旧版 §19.9） |
| 09-08 | 搜索验收 | Tavily/You 真实 key smoke+故障转移演练；TinyFish 端点修正（GET 根路径）；search-smoke 任务 |
| 09-08 | 幂等与恢复 | 事件幂等表（进程内+SQLite）、result-unknown 账本 |
| 09-08 | 音乐多候选 | 网易云编号选歌（multincm 思路）、TTL 会话 |
| 09-08 | parser-lite 批次A | 知乎/豆瓣/TapTap/社区/虎扑等新平台 + B站 AI 总结（WBI）+ UP 获赞 + `/bot cookie` 凭证管理 |
| 09-08 | 防御强化 | excessive_intimacy/insult_nickname 类别、管理员软类别放宽、记忆清洗、命令格式统一 |
| 09-08 | 并行大交付 | 全平台覆盖、搜图（SauceNAO）、小名体系、群复读检测、说人话输出层、全球天气兜底、Open-Meteo、启动闪退修复（NameError） |
| 09-08 | 实卡修复批 | 点歌三件套、B站作者栏归位、发布时间到秒、Help 图、TG 图文 |
| 09-08 | 类型修复 | B站 fans/likes 强制 int、键名对齐；YT/Twitter 深度数据确认 |
| 09-09 | TG 媒体链路 | 本地渲染卡可作 photo、点歌语音（ffmpeg→OGG/OPUS+降级）、help 空文本不吞；NapCat 登录冲突处置 |
| 09-09 | 呈现层四断点 | 发布时间到秒+时区、AI总结/热评空行、卡片热评块（紧凑分支+白名单）、专栏标签；点歌 Mica 卡图替代 CQ:music；候选选歌启用；help 二级引导 |
| 09-09 | 三平台解析 | 推特媒体推文、油管 innertube+新标记三层合并、小红书空 title 兜底；代码块反馈移除；llm 告警豁免 |
| 09-09 | Help 重设计+新卡 | 双列网格手册卡、分类名直查；免费游戏卡（Epic+Steam 双源 `sources/steamfree.py`）、天气卡 |
| 09-09 | key批次+渠道扩容+token汇报 | umi 扩容(GLM-flash/Kimi/MiniMax 新组key+Claude四渠道新key+DeepSeek换key)+StarAPI加GPT三件套+浅夜/DeepSeek key轮换(45条目)；探针key解析bug修复(Config回退)；health报告加【需要你处理的】行动清单；model list族聚合修双Gemini组+价格列；xhs剥xsec_token重试+token失效汇报文案；封面竖图双层(blur填充+contain全露)；失败话术第三版(自然断句) |
| 09-09 | 渠道+卡UI+话术 | StarAPI 渠道接入(gemini-3.8-flash,priority18)；视频卡UI(二维码112/博主id26px/数据icon30数字22/页脚缩小)；失败话术 shuorenhua 重写(12条去表演腔)；探针双模式(手动8并发/后台3线程错峰抖动)；实锤浅夜渠道 gemini 疑似 DeepSeek 套壳(自称深度求索开发) |
| 09-09 | 路由救急+视觉直传 | Config补9个bot_api_key字段(env:解析config_missing根因)；vision默认direct直传多模态主模型(supports_vision放宽,file://转data URL,relay保留为兜底)；internal_error可观测(logger.exception+摘要入审计)；finish空文本兜底(NapCat该消息类型文案)；health报告运维化排版；天气误捕静默；eat约束白名单 |
| 09-09 | 字幕+LLM总结 | B站 AI 字幕（player/wbi/v2, ai-zh 优先，连续重复去重）+油管 captionTracks（ASR 滚动重叠去重）→摘录进文本/卡；`BOT_PARSE_SUBTITLE_SUMMARY=true` 时主路由出【AI字幕总结】；bot.content 加入 offload 名单 |
| 09-09 | 私聊无回复+预算 | LLM 慢烧完 90s 预算→发送层丢消息（根因）；预算 150s+预算耗尽不丢消息；img complete 等待修封面糊 |
| 09-09 | 模型路由渠道化 | registry 45 条目（StarAPI/umi 扩容/Claude 四渠道/key 轮换）；渠道健康巡检+价格选渠道；探针 key 解析 bug 修复（no_api_key 误判）；health 行动清单 |
| 09-09 | 实卡反馈二轮 | 文本作者数据行归位（YT/B站/推特博主级数据+注册日期，订阅同值去重）、小红书字符串计数、卡图 alpha 裁剪（修小卡+透明边）、Help 视口 1040 防切断、「免费游戏」触发词 |
| 09-10 | C组交付 | 好感度数值化（affinity-design.md 成文+每日上限/惰性回归/档位 id/画像清空 bug 修复）；capabilities 全面审查报告 36 项（docs/capability-audit-2026-09-10.md）；浸泡快速回归+长跑（RSS/线程/队列全有界）；帮助文本 13 模块补全取值与示例 |
| 09-10 | 好感度查询卡 | bot.affinity 能力（好感度/好感查看/查询好感）：私聊双向好感卡+群好感榜（group_affinity 镜像表）；affinity_card.html 独立 Mica 模板+bridge 渲染；帮助页公开条目；test_affinity_query 9 项回归；__init__ 接线随并行会话落地（见 §9.9 C组⚠️） |

## 9. 遗留事项与边界

**架构级（P0/P1 尾巴）**：FileTransferGateway（文件上传/下载统一网关，当前仍有 handler 直连 call_api）；订阅/文档导出出站未完全收敛；PersonaContract/WorldEntity/Claim/EvidenceLedger/AnswerPlan 结构化知识架构；claim-based RAG；记忆写入 propose→approve 流程；群聊公共状态；TrustLevel 反注入体系；ToolCatalog。

**验收级（P2）**：真实 NapCat poke/反戳；Telegram 评论树与文件出站；Mail 真机；LangSearch 验收；Wiki 多语言/复杂模板；视觉模型命令全对齐；LLMCallRecord 调用可观测；生成文件安全扫描；老 Office 格式转换链。

**数据级（P3）**：Runtime 迁移 manifest+SQLite 校验+可恢复归档；源码区 data/ 清理（须先备份验证）；alpha 备份包。

**平台边界（非缺陷，勿当 bug 修）**：浅夜渠道 gemini-3.8 自报 DeepSeek 身份（套壳嫌疑，实测实锤，介意纯度用 aiprc-gemini/starapi-gemini）；vision relay 的 myvlm 首选曾 auth 失败（vision registry 已刷新 gemini-3.8 置顶）；YouTube 不提供频道总获赞；长/短视频数与 post 数需逐 Tab 抓取未做；小红书深层依赖登录态与风控（xsec_token 失效自动剥 token 重试，仍失败会明确汇报）；AI 总结仅部分视频存在；NapCat 二维码刷新受 QQ 版本漂移影响（等上游）。

**旧边界行（已被上行取代，保留作历史对照）**：YouTube 不提供频道总获赞；长/短视频数与 post 数需逐 Tab 抓取未做；小红书深层依赖登录态与风控；AI 总结仅部分视频存在；NapCat 二维码刷新受 QQ 版本漂移影响（等上游）。

**体验迭代**：视频解析/点歌卡按用户实卡反馈微调；help 各模块参数取值范围与示例持续充实。

## 9.9 待办任务分组（A/B/C 三组互不相交，可并行认领）

> 划分日期 2026-09-09。三组按文件域切分，无共同文件，可三个 AI 会话并行执行。
> **A组已由本会话认领。** 认领约定：开工前先 `git pull`；只改本组列出的文件域；
> 完成后跑 `dev.ps1` 三门禁（test/lint/typecheck）再提交推送。

### A组（解析数据层 + 封面原图 + B站/微博专项）——已认领，执行中

文件域：`sources/parsers/**`、`sources/moegirl.py`、`sources/food_data.py`

1. 封面原图高清化（全平台）：油管 maxresdefault 原图+404 回退 hqdefault（已落地）；推特图片 name=large（已落地）；小红书脱 webp 压缩后缀取原图；统一审查全平台不再出低清压缩封面
2. 油管/推特爬取修复：油管封面原图链路收尾；推特原图抓取正常化
3. B站直播解析：直播间数据+解析模板更新到最新 Mica 规范
4. B站专栏数据补齐：UP主头像/签名/粉丝数/关注数/总播放/总点赞/投稿时间
5. B站会员购演出全字段：场次、价格、票种（电子/实体/兑换）、是否支持 7 天无理由退票、参展嘉宾、主办单位、场馆名称/地址、举办时间；头像与博主信息替换为真实内容撑开布局
6. 微博解析全面修复：头像/图片/简介/发布时间；微博模板重制到新规范
7. 竖切横图拼接还原：识别"横图切多竖块"发布形式（推特/小红书常见），自动拼接还原完整横图（可保留缝隙）
8. 小红书新 cookie 已灌入并验证（2026-09-09，deep 解析+图集正常）；xsec_token 失效帖自动剥 token 重试+明确汇报文案（已落地）

### B组（模型渠道运维 + UI 排版 + 点歌候选窗口）——待认领

文件域：`llm/channel_health.py`、`llm/model_router.py`（route/health 展示）、`capabilities/runtime_admin.py`、`capabilities/music.py`（候选窗口）、新模板 `song_candidates.html`、`capabilities/subscribe_v2.py`

1. 渠道延迟择优：健康库已有各渠道延迟数据，实现"响应最快的健康渠道优先"动态策略
2. 巡检错峰参数化：探针抖动/线程数从硬编码（0.4s/3 线程）改为可配置
3. qian-night 渠道重排：浅夜渠道 gemini 疑似 DeepSeek 套壳（实测实锤），把 starapi/aiprc 的原生 gemini 提到前面
4. umi 渠道排查：401/额度不足渠道换 key（新 key 已在 .env）后 /bot model probe 重探验证回队
5. 失败话术迭代：第三版（12 条自然断句）按实卡反馈继续调
6. model list/health 文本展示继续细化（价格列/族聚合已做）
7. 订阅油管/推特拉取链路实测：adapter 已在（social_v2），需真实账号验证拉取与推送
8. 点歌候选窗口：图片式候选选择卡（复用 Mica 规范建独立模板，不碰 universal_card.html——A组在同文件有改动）

### C组（好感度系统数值化 + 全面质量审查）——已由本会话完成（2026-09-10）

1. **好感度数值化**：规范成文 `docs/affinity-design.md`（基数 0.5、五行为影响因子表+每日有效次数上限、惰性回归向基数收敛、四档位→语气映射、providers 注入规则）；`character/affinity.py` 实现落地：修「observe 的 INSERT OR REPLACE 清空 profile_notes」数据丢失 bug、时钟统一走注入 clock、新增 `counter_day_index/day_counters` 只加列迁移、`tier_for_affinity()` 档位 id、`snapshot()` 增返 `tier/profile_notes`。回归 `tests/test_affinity_numerical.py`（独立命名，既有 test_affinity.py 不改一字全过）。
2. **全面审查**：`docs/capability-audit-2026-09-10.md`——36 项发现（P1×5 / P2×16 / P3×15），逐项标归属：B组（runtime_admin 注册表烘焙遮蔽 .env、subscribe_v2 无权限校验、music 数字编号崩等）、A组（wbi 缓存无界、卡片非原子写）、无主待修（MCP 工具缓存永久中毒、httpx Client 泄漏、today_history 读失败覆写丢数据等）。
3. **浸泡**：套件内快速回归 `tests/test_soak_growth.py`（多线程异常浸泡行数/线程/队列/幂等全有界）+ 分钟级长跑（3 线程轰击，RSS 105.6→108.5MB 增速收敛非泄漏、线程完全回收、队列封顶 max_items、幂等封顶 4096、零异常）。
4. **帮助文本**：`_HELP_ENTRIES` 13 个模块补参数取值范围与示例（天气/维基/历史上的今天/点歌/表情/偷表情/订阅/草稿/搜索/下载/群策略/日志/路由）。
5. **好感度查询能力（bot.affinity，2026-09-10 二段交付）**：`好感度`/`好感查看`/`查询好感`——私聊出双向好感卡（守岸人对你=印象好感度 0-100；你对守岸人=表达倾向加权占比，诚实标注为估算），群聊出本群好感榜卡（`group_affinity` 镜像表，有印象成员网格、正分绿/低分红/自己高亮，参考样本 UI）；`好感度 我`、`好感度 算法`（三档规则文本）。独立模板 `templates/affinity_card.html` + `bridge.render_affinity_card_html`（主色取 `bot_help_card_color`，Mica 规范，卡片文件名按内容摘要防无界增长）；帮助页新增公开条目「好感度」。设计口径见 `docs/affinity-design.md` §9；回归 `tests/test_affinity_query.py`（9 项）+ 样例双卡截图核对通过。
   ⚠️ 接线注意：`__init__.py` 的 dispatch/OFFLOADED/observe 传 group 已在工作树完成，但因同文件混有并行会话未提交的视频理解接线（引用未跟踪的 transcribe.py/media_registry.py），该文件**随并行会话提交落地**；已提交树上 `好感度` 会走 alias 兜底提示（不崩）。

C 组验证快照：C 组文件域 ruff/mypy/pytest 全绿（新增 13 测试全过，mypy 202 文件全过）；树内同时刻 4 失败+9 lint 均位于并行会话进行中文件（test_video_reply_flow.py 等），不属本组域。

**跨组约定**：`universal_card.html` 归 A组；`__init__.py` 谁动谁先 `git pull`；C组测试文件独立命名不碰他组测试。

## 10. 文档索引

- `COMMANDS.md`：命令与参数（用户手册层）。
- `docs/acceptance-manual.md`：验收手册；`docs/napcat-setup.md`：NapCat 配置；`docs/external-runtime-access.md`：Runtime 访问规则；`docs/workspace-archive-policy.md`：归档策略。
- `docs/plugin-benchmark-2026-09-07.md`：12 插件对比矩阵。
- `task_plan.md` / `findings.md` / `progress.md`：过程记录。
- 本文件旧版（24 轮增补全文）：`git show 10a2272^:docs/handoff-final-2026-09-07.md`。
