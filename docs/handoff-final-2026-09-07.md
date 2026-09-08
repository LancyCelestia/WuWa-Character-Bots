# 守岸人 Bot 交接手册（活文档）

> 整理日期：2026-09-09 · 分支 `v0.0.1-alpha.2` · 工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
> 本文件取代此前 24 轮追加式交接记录；被压缩的原始流水账在 git 历史里（`git show 10a2272:docs/handoff-final-2026-09-07.md` 可回溯旧版全文）。
> 规则：每完成一项交付，同步更新本文件对应小节；不再新开「增补章节」。

## 1. 系统现状

NoneBot2 + OneBot V11（NapCat）QQ 聊天机器人，附带 Telegram / Mail / Console 适配器。已上线：统一消息管线、37+ 平台链接解析（Mica 卡图渲染）、多供应商音乐点歌（卡图+语音）、四家搜索 API、模型路由与故障转移、记忆/人格/知识库、安全防线、订阅推送、运维告警。当前是功能完整、持续迭代的 alpha；不是全部需求完成的生产版。

当前验证基线：**510 passed / Ruff 全过 / mypy 196 文件**（`dev.ps1` 三门禁），每轮交付后必须保持全绿。

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
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"        # 510 passed
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

### 6.6 模型路由
优先级：手动指定 > 时段组 order（`BOT_MODEL_SCHEDULE`/`BOT_MODEL_PRIORITY_GROUPS`）> 基础 priority（1..N 唯一槽位）> 故障转移同序。指令族 `/bot model list|set|add|update|priority|think|effort|price|remove|reset|usage`；密钥只收 `env:` 引用；故障转移总时限 45s。记忆抽取复用主路由（独立超时/冷却，不阻塞回复）。

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

## 9. 遗留事项与边界

**架构级（P0/P1 尾巴）**：FileTransferGateway（文件上传/下载统一网关，当前仍有 handler 直连 call_api）；订阅/文档导出出站未完全收敛；PersonaContract/WorldEntity/Claim/EvidenceLedger/AnswerPlan 结构化知识架构；claim-based RAG；记忆写入 propose→approve 流程；群聊公共状态；TrustLevel 反注入体系；ToolCatalog。

**验收级（P2）**：真实 NapCat poke/反戳；Telegram 评论树与文件出站；Mail 真机；LangSearch 验收；Wiki 多语言/复杂模板；视觉模型命令全对齐；LLMCallRecord 调用可观测；生成文件安全扫描；老 Office 格式转换链。

**数据级（P3）**：Runtime 迁移 manifest+SQLite 校验+可恢复归档；源码区 data/ 清理（须先备份验证）；alpha 备份包。

**平台边界（非缺陷，勿当 bug 修）**：YouTube 不提供频道总获赞；长/短视频数与 post 数需逐 Tab 抓取未做；小红书深层依赖登录态与风控；AI 总结仅部分视频存在；NapCat 二维码刷新受 QQ 版本漂移影响（等上游）。

**体验迭代**：视频解析/点歌卡按用户实卡反馈微调；help 各模块参数取值范围与示例持续充实。

## 10. 文档索引

- `COMMANDS.md`：命令与参数（用户手册层）。
- `docs/acceptance-manual.md`：验收手册；`docs/napcat-setup.md`：NapCat 配置；`docs/external-runtime-access.md`：Runtime 访问规则；`docs/workspace-archive-policy.md`：归档策略。
- `docs/plugin-benchmark-2026-09-07.md`：12 插件对比矩阵。
- `task_plan.md` / `findings.md` / `progress.md`：过程记录。
- 本文件旧版（24 轮增补全文）：`git show 10a2272^:docs/handoff-final-2026-09-07.md`。
