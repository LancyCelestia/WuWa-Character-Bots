# 守岸人 Bot 全量交接手册（2026-09-10 定稿版）

> 本文件是**独立的全新交接文档**，不基于旧文档增量修改；旧活文档 `docs/handoff-final-2026-09-07.md` 保留原样作并行参照，两者冲突时**以本文件为准**（本文件成文更晚、覆盖 09-10 全天多会话交付）。
> 成文时间：2026-09-10 05:30（+0800）· 分支 `v0.0.1-alpha.2` · 当时 HEAD `3819299` · 本地与 origin 同齐。
> **增补（2026-09-10 06:40，+0800）**：审计修复会话（09-10 深夜「全库审计 + 三类别 90 项修复轮」执行者）将其全部交付细节并入本文 **§13**——六域修复逐条表格、门禁 fallout、行为变化、残留清单与协同事件。增补时 HEAD `ce9119d`、工作树约 100 文件未提交（含 §13 修复主体，见 §13.0 落库状态）。
> **增补（2026-09-10 下午，+0800）**：A 组解析会话将其独立成文的深度手册全文并入本文 **§14 附篇**
> （解析器矩阵逐平台实测通道 / 卡片渲染管线细则 / 点歌候选决策树 / 排障手册 17 条等，事无巨细版）。
> 附篇曾独立短存于 docs/handover-full-2026-09-10.md，本次并入并移除该重复文件；增补时点 HEAD 在 `3819299` 之后。
> 源码工作区：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`（下称「仓库根」）。
> 运行数据根：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime`（下称「Runtime 根」，与仓库根是**兄弟目录**）。
> 事实核对方式：本文所有断言都可由 `git log`、`dev.ps1` 三门禁、`docs/capability-audit-2026-09-10.md`、`.superpowers/sdd/handoff-final-2026-09-07/`（SDD 台账与六份任务报告）复核。

---

## 0. 冷启动清单（新会话先做这五件事）

1. `git status` + `git log --oneline -15`：确认分支与工作树状态。**工作树常年有多个并行 AI 会话的未提交改动**（详见 §11 协作协议），不要惊讶、不要还原、不要提交它们。
2. `powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"`：跑测试门禁确认基线（09-10 收尾快照 **865 passed**；数字随各会话交付持续增长，红项先做文件归属判断，见 §11.3）。
3. `Get-Process python | Select Id,StartTime` + `netstat -ano | findstr "3001 8080"`：确认 bot 进程与端口归属（见 §4.3——**09-10 收尾时生产 bot 仍是 09-09 23:17 启动的旧进程，等待用户提权重启**）。
4. 读本文 §2 硬约束、§3 链路、§11 协作协议——这三节是踩过真实坑的沉淀。
5. 领任务前先看 §10 待办清单与 §9 凭据缺口，避免重复劳动。

---

## 1. 系统现状快照（2026-09-10 05:30）

- **产品形态**：NoneBot2 + OneBot V11（NapCat）QQ 聊天机器人，人格「守岸人」（泰提斯系统），附带 Telegram / Mail / Console 适配器。功能完整、持续迭代的 alpha，不是完成态生产版。
- **已上线能力**：统一消息管线、57 个平台注册条目的链接解析（37+ 平台，Mica 卡图渲染）、5 供应商音乐点歌（卡图+语音+候选选择卡）、四家搜索 API、45 条目模型路由（渠道化+健康巡检+延迟择优 v2+影子并发）、记忆/人格/好感度 v3/知识库、安全防线、订阅推送（含权限模型）、运维告警、视频理解（在途）、吃什么、天气、免费游戏、搜图。
- **测试基线**：865 passed / 0 failed（0910 05:00 快照，`dev.ps1 -Task test`，31s）。lint/typecheck 的残余红项全部位于并行会话在途文件（见 §11.3 归属表），**历史经验：这些红会随对应会话交付自愈**。
- **进程现状**：生产 bot = PID 44708（09-09 23:17 启动，管理员权限），持有 8080 LISTENING + 3001 ESTABLISHED。**它运行的是 09-09 的代码与 .env**——09-10 全天交付（含 Gemini 置顶、算法 v2、审计 17 项修复）**全部待重启生效**。重启被管理员权限阻塞（详见 §4.3）。
- **分支状态**：`v0.0.1-alpha.2` 与 tag 同名（push 必须写完整 `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`）。远端 origin=github.com/ElonaSerikas/WuWa-Character-Bots。

## 2. 硬约束（违反即事故，全部有真实前科）

1. **人格源文件、世界观源文件只读**——AI 不得改写。
2. **Runtime 数据不得删除**（SQLite/FAISS/向量库/记忆/Cookie/订阅/媒体缓存/日志/venv）。清理源码树残留须先备份验证（09-10 依 P3 规程清理过源码树 `data/`，497MB 备份在 `%TEMP%/bot_bgroup_backup/data_src_backup/`）。
3. **密钥不入库不入聊天**：真实 key 只存 `.env`（gitignored）；链路字段一律 `env:变量名` 间接引用；**运行时持久层（runtime settings store）也禁止落盘 resolved 明文 key**（09-10 审计修复 P1#1 落地的契约，别打破）。
4. **推送 origin 仅按用户明确指示**；**commit 禁用 `git add -A` / `git add .`**——多会话共享工作树，会裹挟他人半成品（本日真实事故两起，见 §11.2）。
5. **源码树零缓存**：`__pycache__`/`.pytest_cache` 不得出现；测试走 `dev.ps1`（已固定 basetemp），绕开时必须 `PYTHONDONTWRITEBYTECODE=1`。直跑 pytest 撞 `pytest-of-*` 共享目录锁会 PermissionError（09-10 实踩）。
6. **工作区边界**：`ChatBot_Runtime`、`ChatBot_Archive`、上层目录默认不扫描不修改；`ChatBot_Runtime/venv/Scripts/python.exe` 是跑脚本/测试的解释器。
7. **人格与世界观内容**（守岸人话术、泰提斯设定）是项目资产：改话术池必须维持人格语气（参照 `.agents/skills/shuorenhua/SKILL.md` 的去 AI 味标准 + chat.py 内注释的「系统性坦诚」原则）。
8. **用户路由裁定（09-10）**：**默认模型永远为 Gemini**（人格扮演效果最好）；「浅夜套壳」说法已被用户否决——浅夜 gemini 恢复 p1/p2 置顶，不得再以任何自动策略推翻。

## 3. 架构与消息主链路（六段）

```text
NapCat(OneBot V11 WS 服务端 127.0.0.1:3001, token ShoreKeeper)
  → [段6入口] NoneBot Adapter（forward-WS 客户端，.env.prod ONEBOT_WS_URLS；NapCat 起来后自动重连）
  → _incoming_from_nonebot_event() → IngressGateway → IncomingMessage
  → 路由/权限/限流/安静时间/群策略（幂等表可选，默认关）
  → RuntimePipeline（offload 到线程池；09-10 起为聊天专用有界池，见 §7.9）→ CapabilityResult
  → Review/文本整理/媒体投影 → RenderedOutput → SendRequest
  → SendQueue(SQLite) → UnifiedDeliveryGateway
  → sender.onebot（QQ 富消息）→ NapCat
```

LLM 子链路（段 1-5，09-10 检视后的现状）：

```text
[段1] 渠道选择：手动指定 > 时段分组 order > registry priority；同名模型聚合按 EWMA 动态排序
[段2] ModelRouter.generate：影子并发(hedge) → OpenAICompatibleLLMProvider（OpenAI 兼容 POST）
[段3] messages 组装：人格 Prompt（预算 人设>知识库>短时>长时）+ [UNTRUSTED_USER_TEXT] 包裹 + vision direct data URL
[段4] 回复接收：reasoning_effort 不支持自动去参重试 → failover（受 150s 总预算钳制）
[段5] 输出整理：plain_text 去噪 + 说人话层 + budget 切分 + 失败话术池（私聊）
[段6] sender.onebot CQ 组装 → NapCat（musicSignUrl 规避、媒体顺序、分片超时）
```

关键文件：`bot.py`（启动+崩溃守卫）；`plugins/bot_unified_runtime/__init__.py`（handler 装配与能力分发，约 4700 行，**多会话热区**）；`runtime/pipeline.py`、`runtime/ingress.py`；`llm/model_router.py`、`llm/channel_health.py`、`llm/providers.py`；`capabilities/chat.py`（约 2400 行，**多会话热区**）；`sender/onebot.py`、`sender/queue.py`、`sender/gateway.py`、`sender/receipts.py`。

## 4. 启动、验证与门禁

### 4.1 门禁（每轮交付前全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"        # 09-10 基线 865 passed
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"       # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"  # mypy
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"  # 源码树/运行时边界体检
# 其他：doctor / backend-base-smoke / backend-smoke / search-smoke / startup-smoke
```

门禁失败先做**归属判断**：失败文件属于你的允许清单 → 修；属于他人（§11.3 表）→ 报告不修（历史规律：会随对方交付自愈）。pytest 慢速标记：`pyproject` 已注册 `slow` marker（soak 长跑），`-m "not slow"` 可提速。

### 4.2 日志与启动

- `dev.ps1` 启动（run/run-watch）把输出重定向到 `ChatBot_Runtime/logs/nonebot.out.log`；手动控制台启动不落盘。分离式启动参考（09-10 实用）：
  `Start-Process -FilePath <venv>\python.exe -ArgumentList 'bot.py' -WorkingDirectory <仓库根> -WindowStyle Hidden -RedirectStandardOutput <Runtime>\logs\nonebot.out.log -RedirectStandardError ...\nonebot.err.log`
- NapCat：`C:\Software\NapCat\login-bot.bat`（快速登录守岸人 3958874605）。验证：`netstat -ano | findstr 3001` 出 LISTENING（NapCat）+ bot 进程 ESTABLISHED。

### 4.3 重启的权限陷阱（09-10 实踩）

生产 bot 由**管理员权限**启动 → 非提权 shell `taskkill /F` 报「拒绝访问」杀不掉。若需重启：
1. 让用户从管理员 shell 杀旧进程（或关闭其控制台）；
2. 确认 8080 无人监听后再启动；
3. **绝不要**在旧进程存活时启动新实例——新实例会因 8080 占用数秒内自灭（实测安全，但别赌）。
判断「改动是否已生效」永远先查进程启动时间 vs 提交时间（§7 排障表第一行）。

## 5. 数据、密钥与配置

### 5.1 目录与重映射

- Runtime 根：`ChatBot_Runtime/`（data/cache/logs/venv/git 元数据）。代码内 `data/` 前缀经 `scripts/runtime_paths.py` 自动重映射到 Runtime 根——**从仓库根直接跑脚本且未触发重映射时会在源码树生成 `data/` 残留**（runtime-layout 会 FAIL；清理规程=备份到 %TEMP% 再删，09-10 清过一次 497MB）。
- SQLite 资产：`channel_health`（渠道健康+EWMA）、好感度库（WAL）、`group_affinity` 镜像表、发送队列、幂等表、订阅 store v2（outbox/seen 已带清理）、媒体档案库（在途）。
- Cookie：`ChatBot_Runtime/data/platform_cookies.txt`（Netscape 格式）。**当前仅 weibo + xiaohongshu 域有效**；管理员热写指令 `/bot cookie import <平台> <Cookie头>`。缺失凭据的影响面见 §9。

### 5.2 `.env` 关键项（生产真值在 .env，不入库）

- 模型注册表：`BOT_MODEL_REGISTRY`（45 条目单行 JSON，结构 `{"<id>": {"model","base_url","api_key":"env:XXX","group","tags","priority","price_in","price_out"}}`）；`BOT_MODEL_PRIORITY_GROUPS`（两组时段分组 JSON，`days` ISO 周编号、`windows`、`order`）。
- 路由开关：`BOT_CHANNEL_HEALTH_ENABLED=true`、`BOT_CHANNEL_HEALTH_LATENCY_FIRST=1`（延迟择优，默认开）、`BOT_CHANNEL_PROBE_THREADS/MANUAL_THREADS/JITTER_SECONDS`（3/8/0.4，钳位 1..16 / 0..5s）、`BOT_CHANNEL_HEALTH_LATENCY_FIRST`、慢渠道阈值 `bot_channel_slow_ema_ms=15000`。
- 影子并发：`bot_chat_hedged_requests_enabled`（Config 默认 True=开）、`bot_chat_hedge_delay_seconds=6.0`、`bot_chat_hedge_max_candidates=2`；自适应超时 `bot_channel_adaptive_timeout=True`。
- 密钥槽位（全部 `env:` 引用，Config 需有同名小写字段——09-09 事故根因）：`BOT_API_KEY_QIANQIANYE`（**已失效 401**）、`_QIANQIANYE_NIGHT`、`_AIPRC`、`_AIPRC_GEMINI`、`_AIPRC_GROK`、`_UMI_GROUP1/2/3`（**GROUP3 三渠道余额 0**）、`_UMI_CLAUDE`、`_TOOLCODE_GPT/GEMINI/GROK`、`_DEEPSEEK_QIAN`、`_DEEPSEEK_OFFICIAL`（**no_api_key**）、`_ZHIPU`、`_HCN`、`_STARAPI`。
- 其他：`BOT_CHAT_*`（provider/model/max_tokens 65538）、`BOT_SEARCH_TAVILY/YOU_API_KEY`、`TELEGRAM_BOTS`、`TELEGRAM_PROXY=http://127.0.0.1:7890`、`BOT_DOWNLOAD_PROXY`、`BOT_MUSIC_CANDIDATES_ENABLED=true`、`BOT_MUSIC_CANDIDATES_LIMIT`（已全平台透传）、`BOT_PARSE_SUBTITLE_SUMMARY=true`、`BOT_EVENT_IDEMPOTENCY_ENABLED`（默认 false）、`BOT_DISCONNECT_NOTICE_*`、`BOT_VIDEO_*`（视频理解，在途）、`BOT_PIPELINE_MAX_WORKERS`（聊天专用池，默认 8，钳 1..64，改后需重启）。

### 5.3 模型路由现行布局（用户裁定 + 实测数据）

- **默认永远 Gemini**：registry p1=qian-night-gemini（gemini-3.8-flash-high，¥0.45/2.25）、p2=qian-night-c-gemini（c-gemini-3.8-flash-high）；两组时段 order 同样 Gemini 簇置顶（qian-night×2 → qian-gemini-38 → starapi → toolcode → aiprc）。
- aiprc-gemini 带 `manual` 标签**暂时移出自动轮换**（用户指令；实测探针其实 ok 3046ms，恢复=去掉 manual 标签）。
- 已知渠道故障面（09-10 探针）：`BOT_API_KEY_QIANQIANYE` 401×3（qian-terra/luna/astra）、`UMI_GROUP3` 三渠道 403 余额 0、umi claude×4+terra ReadTimeout、umi desk 组 503 上游无货、ds-official no_api_key×3、toolcode-gemini 404 下架、starapi-gemini 503 间歇。健康系统自动跳过+30 分钟重探，**这些是运维问题不是代码问题**。

## 6. 子系统详解（当前状态）

### 6.1 命令与路由
统一格式 `/bot <模块> <功能> [参数]`；别名表 `runtime/aliases.py`。`/bot help` 出 Mica 手册卡（双列网格+药丸）；`/bot help <模块>` 出说明书页；分类名直查。命令真相源：`COMMANDS.md` + `_HELP_ENTRIES`（capabilities/echo.py，13 模块已补全参数取值与示例）。注意：C组 好感度 dispatch 在 `__init__.py` 的接线已随并行会话在工作树完成，**随该会话提交落地**；已提交树上 `好感度` 走 alias 兜底提示（不崩）。

### 6.2 链接解析器（57 注册条目 / 37+ 平台）
入口 `sources/parsers/__init__.py`（`build_content_parser_registry` → `{"registry", "parsers"}`；平台路由表+Cookie 绑定+代理绑定；全默认参数时进程级缓存）。实现按平台拆 `platforms_*.py`；公共设施 `wbi.py`（B站签名 30 分钟缓存）、`http_util.py`（代理/UA/重试）、`cookies.py`、`image_stitch.py`（竖切横图拼接）。

**09-10 全平台实测矩阵结果**（真实链接直驱解析器）：
- ✅ PASS（20 链路）：B站视频（字段健全：标题/作者全提取）/专栏、油管（代理链路）、推特 x.com/jack/status/20、小红书（cookie 发现式取样成功）、Pixiv、Spotify、Steam 商店页、Telegram、萌娘百科、酷我/网易云/QQ音乐歌曲解析、四家音乐搜索（修复后）、音乐候选（netease/qq/kugou 各 5 条）、天气全字段、steam-free 端点。
- 🔧 已修复真 bug：酷狗搜索/候选 URL `tagtype=全部` 裸中文 → httpx UnicodeEncodeError（95f2f63，两处同源，实测修复后「晴天」候选 5 条正常）。
- 🔑 需凭据（代码无恙）：B站直播（匿名 `-352` 风控，主通道已切 Room/get_info + get_status_info_by_uids 匿名可用，富集字段需 cookie）、linux.do 403、知乎 403（专栏 API 也拒匿名）、微博 403/432（**现有 weibo cookie 已失效需重灌**；A组已灌过一版登录 cookie 并验证 provider 链路，后续又失效）。
- 📐 设计范围外（URL 形态不属管辖，非缺陷）：豆瓣（只收 `group/topic/\d+`）、TapTap（只收 `moment|video/\d+`）、知乎纯问题页（只收 answer 页与 zhuanlan）。
- 📋 无固定样例待真实分享链接：douyin、快手、酷安、LOFTER、ALLCPP、米画师、画加、BUFF、米游社、森空岛、库街区、小黑盒、5E、完美、大道、汽水、豆包、Facebook、会员购、B站游戏中心、bilibili_goods。
- 解析层其他要点：B站直播主通道 Room/get_info（getInfoByRoom 匿名常态 -352）；专栏 -509/-352 瞬态风控短停重试一次；小红书笔记页 playwright 兜底（裸 http 间歇 403/461）；**剥 `!` 后缀已撤回**（2026 版 xhscdn 签名路径内含 `!nd_dft_*`，剥掉 200→403），高质量档走 info_list WB_DFT；naive 时间一律按北京时间解释（contracts 契约层根治）；ORB 拦 sinaimg 灰图由 render_backends route 兑子解决。

### 6.3 卡片渲染（Mica 规范）
管线：`capabilities/content_parser.py:render_card_png`（ParsedContent → payload → HTML → playwright 常驻浏览器截图）→ `output/card_render/`（bridge + `templates/`）。规范铁律：底色唯一来源 `PLATFORM_COLORS`（bridge.py）经 `--pc` 变量 `color-mix` 掺白派生（外壳 5-11%、面板 4-8%），**禁写死品牌色**；单柔光阴影；字重 ≤700；body 透明（omit_background 依赖）；`.card` 根元素承载截图。已接卡：链接解析（universal_card）、点歌成功卡、**点歌候选选择卡**（`song_candidates.html`+`bridge.render_song_candidates_html`，渲染失败逐字回退纯文本零回归）、帮助、天气、免费游戏、好感度（`affinity_card.html`）、会员购（嘉宾独立卡区）。
**渲染技术要点（09-10 淀淀）**：新模板**不要加 `<meta viewport>`**（触发 Chromium 移动模式缩放怪癖，整页被缩一半）；`.card` 用 `width: fit-content` 让元素截图收紧；viewport 要容住壳宽（候选卡 1028 壳 → viewport 1040）；验证手法=像素采样（柔光阴影 alpha<4% 合格，查看器把半透明红合成到黑底会误判成「实色环」）。改卡后必跑三门禁+样例截图核对（临时脚本放 %TEMP%）。死模板已清理（Compact 音乐版式七块+写死色违规源）。

### 6.4 音乐点歌
5 供应商（网易云/QQ/酷狗/酷我/Apple Music+Spotify 解析）；模式 `card+voice+link` 可组合（`点歌模式`）；多候选编号选歌（TTL 300s，按 session+sender 隔离）：歧义候选出 Mica 候选选择卡；QQ 端成功卡替代 CQ:music（NapCat 无 musicSignUrl 拒签会中断整条消息）。09-10 加固：裸歌名精确命中才跳过候选列表（旧 exact_hits 一票否决导致「后来 钢琴版」直接放同名翻唱）；编号无会话明确提示；`limit` 全平台透传（`BOT_MUSIC_CANDIDATES_LIMIT` 不再被硬编码 5 截断）；酷狗详情复用 parse_kugou 富化（封面/标题）；QQ 搜索迁移 musicu.fcg（旧端点恒 500）；酷我 r.s 搜索服务端劣化返回非 JSON（已知边界，候选链可用）。

### 6.5 搜索 API
Tavily 主、You.com 备、LangSearch 备、TinyFish 搜索+抓取；不接 Bing；链式回退+瞬时重试。验收 `dev.ps1 -Task search-smoke`。已知性能点（管线检视 #5）：非 fast 模式多 query 串行检索最坏 30-40s（fast_mode 默认开掩盖），待并发化。

### 6.6 模型路由（渠道化 + 延迟择优 v2）——本日重点改造区
- **选择链**：手动指定 > 时段分组 order（Gemini 簇置顶）> registry priority（1..N 唯一槽位）> 故障转移同序。`/bot model set <实际模型名>` 聚合同名全渠道：EWMA 升序（未实测垫底保价格序）→ 关健康层时价格升序。**auto-route 全局队列永不延迟重排**（默认永远 Gemini 的保障）。
- **健康巡检**：每小时全渠道最小调用（后台 3 线程+0.4s 错峰；手动 probe 8 并发带重入防护）；连续 2 失败 → ⛔移出队列，30 分钟半开重探，永不自动删除；全不可用放行全队列防瘫。参数 `bot_channel_probe_threads/manual_threads/jitter_seconds`。
- **v2 四件套**：① EWMA（α=0.3，`ema_ms/samples` 列，迁移自动）；② 慢渠道检测（`bot_channel_slow_ema_ms=15000`，降序不摘除）；③ 同名聚合按 ema 动态排序；④ 无损切换=自适应超时 `max(8s, ema*3)` + 影子并发（hedge_delay 6s 后向次优发影子请求，先到先得，落选也记账；落选计费 token，可关）。
- **注册表镜像防遮蔽**（审计 P1#1 修复）：`/bot model add/update/priority` 写运行时 store 时对 .env 来源条目打 source 标记，合并时**内容字段（model/base_url/api_key）以 .env 新鲜值为准**，仅 priority/新增/显式修改生效；store 里 key 只存 `env:` 引用原文。
- **错误面**：私聊 LLM 失败回 12 条守岸人话术 v4（会话内轮换不重复）；群聊静默。指令族 `/bot model list|set|add|update|priority|think|effort|price|remove|reset|usage|health|probe|routes|vision`。
- **运行时注册表镜像**：runtime store 条目与 .env 合并语义见上；`/bot model routes <模型名>` 按响应速度排序、未实测 ⏳ 标注。

### 6.7 记忆 / 人格 / 好感度（v3）
- 好感度 v3 数值改版（用户裁定）：初始 10 分（内部 0.1，旧库不迁移由惰性回归收敛）；步长幂律非线性（距极值 <10 分按 (d/0.1)^γ 缩小）；因人而异（sha1 派生 ±15% 个人系数）；每日上限本地自然日；辱骂半衰期 15d/其余 30d，全淡出回默认 10。行为识别正则实测修正（「我不喜欢你」不再判 positive、成语误捕排除、辱骂独立 `_INSULT_RE`）。
- bot.affinity 能力：私聊双向好感卡 + 群好感榜（`group_affinity` 镜像表）；`好感度 算法` 图文说明卡（个人精确步长+档位对照）。设计文档 `docs/affinity-design.md`。
- 记忆清洗 `security/memory_sanitize.py`（隔离表）；知识库向量检索含 FTS；「历史上的今天」365 天库（推送表读失败拒绝改写+写失败回错——修过空表覆写丢订阅）。

### 6.8 安全防线
`security/content_safety.py` 硬类别（NSFW/血腥/政治/骚扰）+ 软类别（强加称谓/宠物化/人格破坏/侮辱外号）；管理员放宽软类别不放宽硬类别；输出侧 plain_text 去噪+说人话层；文件读取视为不可信数据。

### 6.9 订阅（v2 + 权限模型）
`sources/subscriptions/`（social_v2/bilibili/xhs/music/telegram 适配器）+ `capabilities/subscribe_v2.py`（**09-10 起有权限校验**：pause/resume/remove 需创建者或管理员，移植 v1 `_can_operate`；list 按目的地过滤；re-add 不再重启管理员暂停的订阅）+ v1 `subscribe.py`（remove/pause 按目的地粒度，最后目的地移除才删 spec；check 加权限；digest 可关）。推送走视觉渲染管线；outbox sent 行按时间裁剪、retry 有上限进死信、seen 有 TTL。**09-10 实测**：YT 频道拉取 healthy（15 条）；@handle 订阅缺陷已修（resolve 先网络解析 handle→真实 UC id）；推特需 X cookie；QQ 实际推送待用户指定目标验证。

### 6.10 多适配器 / 6.11 告警 / 6.12 视觉字幕 / 6.13 吃什么
- 适配器：Telegram（轮询+韧性重连）、Mail（韧性适配器+bridge）、Console；掉线通知 `runtime/disconnect_notice.py`（默认关）。
- 告警：`runtime/alerts.py` 按 (stage,kind,adapter,bot,target) 300s 抑制；result-unknown 账本重连对账不盲发。
- 视觉：direct 直传默认（data URL 进主模型；`require_vision` 已与 `supports_vision` 统一为「仅 text-only 排除」——修掉了图片消息候选清空硬失败的根因）；relay 兜底；字幕总结开（B站 AI 字幕+油管 captionTracks →【AI字幕总结】）。
- 视频理解（**并行会话在途**）：`sources/video_understanding.py`/`transcribe.py`/`runtime/video_pipeline.py` 未跟踪+`chat.py` 接线未提交，深挖预算协调（管线检视 #1 High）在该批落地时一并处理。
- 吃什么：60 道本地库+LLM 约束推荐+Mica 卡；`_RECENT` 有界+锁（C组修）。

### 6.14 发送层（NapCat）
CQ 组装规避 musicSignUrl 拒签；分片发送超时按段钳下限；队列 SQLite 重试/裁剪；回执对账闭环（部分送达即停，无重复投递）；租约协议单 worker。已知残留（管线检视 #6/#13，热区待其会话）：NapCat 断线 >2 分钟排队回复被丢弃（bot_unavailable 计 attempts）；queue/receipts 每操作新开连接。

## 7. 排障手册（09-10 增补版）

| 症状 | 第一步诊断 | 处置 |
|---|---|---|
| 「改动没生效」 | 进程启动时间 vs 提交时间（`Get-Process python`） | 重启 bot；确认无第二实例 |
| 杀不掉旧 bot | 管理员权限进程（拒绝访问） | 用户提权杀；勿在其存活时启新实例 |
| NapCat 登录冲突/3001 不监听 | QQ 多代际并存 | 提权清场→`login-bot.bat`；bot 自动重连 |
| B站直播/专栏 -352/-509 | 匿名风控（cookie 缺失） | 灌 B站 cookie；专栏已有短停重试 |
| 知乎/微博/linux.do 403/432 | 凭据缺失或过期 | `/bot cookie import` 重灌 |
| 音乐搜索 UnicodeEncodeError | URL 裸中文（酷狗 tagtype 类） | percent-encode（酷狗已修，警惕同型） |
| 卡片渲染整页缩一半 | 模板带 `<meta viewport>` | 删 meta；`.card` 用 fit-content |
| 查看器里卡片有「实色描边」 | 半透明阴影被合成到黑底 | 像素采样定 alpha（<4% 即合规柔光） |
| pytest PermissionError | 共享 pytest-of-* 锁 | 走 dev.ps1 |
| push 报 refspec 歧义 | 分支与 tag 同名 | 完整 `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` |
| push 408/断 | 代理掐大包 | 分片推送逐提交重试 |
| fetch reference broken | gitdir 在 Runtime/git | `git ls-remote` 取哈希直写 |
| lint/mypy 突然多红 | 并行会话在途文件 | 按文件归属判断（§11.3），勿修他人域 |
| 源码树出现 data/ 或缓存 | 绕开 dev.ps1 直跑 | 备份后清理；`PYTHONDONTWRITEBYTECODE=1` |
| git commit 带上别人文件 | 共享 index 被并行 add | hash-object/update-index 部分暂存（§11.4）；事后 plumbing 拆分（§11.5） |

## 8. 交付史与提交索引（09-09 → 09-10，含重写后链）

09-09 及以前的修复史见旧活文档 §8（`docs/handoff-final-2026-09-07.md`）；09-10 全部提交（重写后链，HEAD 起点 18e5d35）：

| 提交 | 会话 | 内容 |
|---|---|---|
| de006a1 | C组 | 好感度数值化+capabilities 审计报告 36 项+浸泡+帮助文本 13 模块 |
| 5d34884 | B组 | 渠道延迟择优 v1+巡检参数化+routes/health 展示 |
| c4e0996 | B组 | Config 补 probe 三字段 |
| 02f3b46 | B组 | 点歌候选 Mica 选择卡（plumbing 拆分后纯化版） |
| e1374b1 | 视频(拆出) | `_inline_local_image` 本地图片内联（自候选卡提交拆出） |
| ad2bcde | B组 | 订阅油管 @handle 解析修复 |
| c7e3eeb | C组 | bot.affinity 好感查询能力+双卡 |
| 04e096f | B组 | 失败话术 v4+轮换回归 |
| 63de2f6 | B组 | 候选卡渲染稳健化（去 meta viewport/fit-content/viewport 1040） |
| 2309561 | C组(拆出) | 好感度 base_router 接线+回归（自稳健化提交拆出） |
| e119a1d | C组 | handoff 存证 amend 混入事件 |
| 19baf96 / 7e63f91 | A组 | 解析数据层+封面原图+B站/微博专项+文档 |
| 95f2f63 | B组 | 酷狗搜索 URL 裸中文编码缺陷修复（实测验证） |
| c817170 | B组 | 交接文档二轮更正（撤浅夜降级/默认 Gemini/aiprc manual） |
| bd35b4c | C组 | 好感度 v3 数值改版（用户裁定） |
| ed0fedb / 8b08439 | A组 | 会员购嘉宾卡区+点歌实测修复批（含 music.py 审计 5 项） |
| ee8dbc5 | C组 | 优化批 9 项（行为正则/半衰期/前缀配额/WAL/httpx 单例等） |
| 2c42282 | B组 | 审计修复批 P1×4+P2×7+P3×6（19 回归） |
| db84aae / 34ef721 | A组 | B站直播风控规避重构+死模板清理 |
| 22d561e / d076d25 | A组 | naive 时间契约根治+点歌二轮加固 |
| d5a9f43 | B组 | **延迟择优 v2**（EWMA/慢渠道/动态排序/自适应超时/影子并发；24 回归） |
| 9589232 | B组 | 管线检视 #3/#4：vision 双门槛统一+聊天专用有界线程池（15 回归） |
| f96d1a1 / 3819299 | A组 | xhs playwright 兜底+撤剥！回归+时长秒数化（⚠️ 该提交因共享 index 裹挟了并行会话已暂存的 runtime policy 改动集——pipeline 瘦身+test 改名，内容连贯 865 passed，已存证） |

## 9. 凭据与外部依赖缺口（需用户）

| 缺口 | 影响 | 恢复动作 |
|---|---|---|
| B站 cookie | 直播富集字段/专栏部分风控 | `/bot cookie import bilibili <头>` |
| X/Twitter cookie | 推特订阅无法真实拉取（auth_required） | `/bot cookie import x <头>` |
| 微博 cookie 失效 | 微博解析/订阅（403/432） | 重灌 `/bot cookie import weibo <头>` |
| 知乎 cookie | 知乎解析 403（含专栏 API） | `/bot cookie import zhihu <头>` |
| linux.do cookie | 帖子解析 403 | `/bot cookie import linuxdo <头>` |
| umi 账户余额 | 三渠道 403「余额 ✦0」（key 有效） | 充值或换有余额账户 key 到 `BOT_API_KEY_UMI_GROUP3` |
| `BOT_API_KEY_QIANQIANYE` | 浅夜主 key 401×3 | 后台换新 key |
| ds-official key | no_api_key×3 | 配 `BOT_API_KEY_DEEPSEEK_OFFICIAL` |
| toolcode-gemini | 404 已下架 | `/bot model remove` 或换模型 |
| NapCat 提权重启 | 全部新代码/.env 未生效 | 管理员 shell 杀 44708/11936 后重启 |
| 21 平台真实分享链接 | 无固定样例未实测 | 提供链接后逐个补测 |

## 10. 待办清单（下一波认领参考）

**用户动作**（上表）之外，代码侧已知待办：
1. **管线检视余 11 条**（`pipeline-review-report.md`，全带 file:line 与修法）：#1 媒体预算与 150s 请求预算协调（视频会话落地时一并）；#2 providers.py HTTP 400 分类（可转移/去参重试）；#7 urllib→httpx.Client 单例+read 限长；#5 多 query 并发检索；#6 NapCat 断线 bot_unavailable 不计 attempts；#8 MCP 负缓存 TTL；#9 知识文件 mtime 缓存；#10 分片超时下限；#11 工具循环空文本收尾轮；#12 失效审计标签；#13 queue/receipts 长连接。
2. **chat.py 三项延后**（C组登记）：MCP 缓存中毒、输出预算装箱、记忆抽取线程池——同因待视频会话落地。
3. **`__init__.py` 好感度 dispatch 接线**已在工作树，随视频会话提交落地。
4. **测试树清理**：`tests/test_perf_*.py`（5 个）等历史性能脚本与正式回归并存，可评估归档；untracked 的 `-b` 垃圾文件已清（如再生是某会话命令 typo）。
5. 架构级长线（旧文档 §9）：FileTransferGateway、claim-based RAG、TrustLevel、ToolCatalog 等不受本日工作影响。

## 11. 多会话协作协议（本日三次真实事故的沉淀）

### 11.1 基本约定
- 多个 AI 会话共享**同一工作树**与同一分支；按文件域切分任务（09-10 分 A/B/C 组+视频会话+基建会话）。
- 开工先 `git pull`（无 upstream 时 `git fetch` + 对比 ls-remote）；只改本任务文件域；逐文件显式 `git add`；**禁止 `git add -A`**。
- 共享文件（`__init__.py`/`bridge.py`/`echo.py`/`chat.py`）动前在 handoff「共享文件编辑登记」行登记，提交后销记。

### 11.2 本日事故实录（为什么会 §11.3/11.4/11.5）
1. **index 裹挟（正向）**：Task2 提交 bridge.py 时把视频会话在同文件在途的 `_inline_local_image` hunk 一起带入（2c42282 前身 6b16a90）。
2. **amend 撞车（反向）**：B组提交 a1bf17d 后被 C组 `git commit --amend` 混入其 base_router.py/test_affinity_query.py（成 df27c56）。
3. **共享 index 裹挟（三度）**：A组 f96d1a1 把并行会话已暂存的 runtime policy 改动集一起提交（对方已自行存证）。
**处置先例**：内容正确的不回退、存证+勘误；用户要求真修时用 §11.5 的 plumbing 重链拆分。

### 11.3 门禁红项归属判断（当前快照）
lint/typecheck 残余红在：`bot.py`、`plain_text.py`、`settings.py`、`worker.py`、`disconnect_notice.py`、`chat.py`、`__init__.py`、`test_auditfix_runtime_policy.py`、`image_stitch.py` 等——**全部是视频/基建会话在途文件**。规则：失败文件在自己允许清单内才修；否则报告。历史规律：对方交付后自愈（09-10 内 video/affinity/mention 红三次自愈）。

### 11.4 部分暂存手法（只提交自己 hunk）
同文件混有他人在途改动时：
```bash
export GIT_INDEX_FILE="$TEMP/tmp_index"
git read-tree <base_commit>          # 或当前 HEAD 树
# 在工作树/内存构造只含自己改动的文件内容，写入 blob：
git hash-object -w <file>            # → sha
git update-index --cacheinfo "100644,<sha>,<path>"
git write-tree && git commit-tree <tree> -p <parent> -m "msg"
```
已三次实战（config.py probe 字段、chat.py 话术元组、content_parser 守卫 hunk）——工作树他人在途改动分毫未失。

### 11.5 历史重写手法（拆分混交提交）
用户命令修复历史时：`git read-tree`+`git apply --cached`（过滤 hunk）+ 树对象复用 + `git commit-tree` 逐 commit 重链（保留原作者/日期：GIT_AUTHOR_* 从 `git log --format` 读）；终局 `git diff old_HEAD new_HEAD` 必须为空才 `git update-ref`；`push --force-with-lease=refs/heads/<branch>:<旧远端sha>`。09-10 实战：6b16a90→02f3b46+e1374b1、df27c56→63de2f6+2309561，链尾 7e63f91。注意：重写期间其他会话可能提交——完成后 `git fetch` 核对，必要时让后续提交 rebase。
**并发写入同文件的裁量为**：对方改动语义互补时，在合并态继续+提交前 diff 稳定性检查（间隔 ≥10s 两次一致）+提交信息注明吸收+报告专节存证（09-10「健康开关来源统一」重构先例）。

### 11.6 限流
子代理上游会 1302 限流（一次跑 32 分钟后被打死）。纪律：实现者读文件一次读全、少反复小请求；死掉的实现者的成 gone 工作按「controller 接管验证」或重派处理（均有先例）。

## 12. 证据与文档索引

| 资料 | 路径 |
|---|---|
| 旧活文档（保留不改，历史参照） | `docs/handoff-final-2026-09-07.md` |
| SDD 台账（本会话全程决策/裁决/事故） | `.superpowers/sdd/handoff-final-2026-09-07/progress.md` |
| 任务需求书/报告 ×6 | 同目录 `task-{1,1p5,2,3,4,5,6}-brief.md` / `task-*-report.md` |
| 最终全分支审查 | 同目录 `final-review-package.txt` / `final-review-report.md`（APPROVED） |
| 管线检视报告（13 条，file:line+修法） | 同目录 `pipeline-review-report.md` |
| C组审计报告（36 项） | `docs/capability-audit-2026-09-10.md` |
| 好感度设计文档（v3） | `docs/affinity-design.md` |
| 用户手册层命令 | `COMMANDS.md`；验收手册 `docs/acceptance-manual.md`；NapCat `docs/napcat-setup.md` |
| .env 备份（09-10 两次） | `%TEMP%/bot_bgroup_backup/env.bak-20260910`、`env.bak2-20260910` |
| 源码树 data/ 清理备份 | `%TEMP%/bot_bgroup_backup/data_src_backup/`（497MB） |
| 实测脚本（可复跑） | `%TEMP%/bot_bgroup/`：`platform_matrix.py`、`probe_umi.py`、`test_subscribe_fetch.py`、`render_candidates_sample.py` |
| 09-10 审计+修复轮全记录 | 本文 **§13**（六域修复逐条表格 / 门禁 fallout / 行为变化 / 残留 / 协同事件） |
| 审计回滚基线快照 | `%TEMP%/auditfix-baseline-20260910-023342/`（`tracked.patch` / `status.txt` / `untracked.txt`） |
| 审计回归测试（96 用例 ×6 文件） | `tests/test_auditfix_{sender_queue,runtime_policy,llm_route,main_character,parsers,subscriptions_capabilities}.py`——`runtime_policy` 已随 f96d1a1 共享 index 裹挟入库，其余 5 个为 untracked 待提交 |
| 解析/卡片/点歌 深度手册（事无巨细版） | 本文 **§14 附篇**（A 组会话主笔；解析器逐平台实测通道、ORB 兜子、点歌候选决策树、排障手册 17 条） |

---

## 13. 09-10 深夜「全库审计 + 三类别 90 项修复轮」全记录（审计修复会话主笔）

### 13.0 落库状态与门禁终态（先读）

- **门禁终态（审计修复会话收尾实测）**：lint `All checks passed`；typecheck `Success: no issues found in 205 source files`；pytest **865 passed**（32.8s）——与 §1 的 865 基线为同一快照谱系。
- **落库状态（增补时点）**：修复主体**仍在工作树未提交**（`sender/queue.py`、`plain_text.py`、`gate.py`、`rate_limit.py`、`reply_budget.py`、`disconnect_notice.py`、`settings.py`、`vector_knowledge.py`、`console_chat.py`、bot.py、config.py、`__init__.py` 等约 100 文件dirty）；6 个回归测试文件中 `test_auditfix_runtime_policy.py` 已随 f96d1a1 的共享 index 裹挟入库（内容正确已存证），其余 5 个 untracked。**提交时按 §11.4 部分暂存规程逐文件显式 add，禁 `git add -A`**。
- **回滚基线**：`%TEMP%/auditfix-baseline-20260910-023342/`（修复开始前的工作树 patch + 状态清单；修复全程锚定式 Edit，未整文件覆写）。
- **方法**：先只读全库审计（7 个并行只读子代理分域通读 + 主会话对最高严重度声明逐条实码复核，剔除 2 条 stale）；再 6 个实施子代理按互不相交文件域并行修复；主会话统一跑三门禁并修全部 fallout（§13.8）。

### 13.1 A 组修复（发送/队列/输出渲染域，16/16）

| # | 位置 | 修复 |
|---|---|---|
| A1 | sender/queue.py `submit` | next_retry_at 写 now+60s 宽限期（`_INLINE_DELIVERY_GRACE_SECONDS`），消除 worker 与内联投递竞态双发 |
| A2 | queue.py + receipts.py | `_schema_ready` 一次性建表 + 首连 `PRAGMA journal_mode=WAL`（失败降级）+ `connect(timeout=5.0)` |
| A3 | queue.py `submit` | 去重改 `INSERT ... ON CONFLICT(dedupe_key) DO NOTHING`，并发冲突→skipped 回执，不再抛 IntegrityError |
| A4 | queue.py `_prune` | 只淘汰终态（SENT/FAILED_FINAL/SKIPPED），非终态永不淘汰（防静默删未发消息） |
| A5 | queue.py `claim_due` | 租约过期重认领递增 retry_count，达上限 `_finalize_expired_lease` 置 FAILED_FINAL + `send_failed_final` 审计 |
| A6 | queue.py | 删除 SQLite 队列无上界 `sent_requests` 内存列表（连带 SendQueue Protocol 变更，见 §13.8） |
| A7 | onebot.py | `_SendSideEffects` 副作用计数：chunk/文件/图成功即 +1；仅零副作用才重试，否则 result_unknown/FAILED_FINAL（修部分送达后从头重发） |
| A8 | onebot.py | `_TimeoutBudget` 按段/文件数切分超时，每段独立 wait_for，总受原 deadline 约束（修多段 15s 一刀切误判 result_unknown） |
| A9 | nonebot.py | 语音源 client.stream 流式+45MB 上限；`_resolve_download_proxy` 挂下载代理（残留：Config 与 env 不同步时可能取不到，见 §13.10） |
| A10 | nonebot.py | ffmpeg 输出 `.part`+`os.replace` 原子落位；`.src` 发送后删；`.ogg` 缓存 mtime 清扫保留 64 个；顺带修缓存目录未建导致本地语音转码必败 |
| A11 | nonebot.py | `delivered_parts` 部件进度：重试不重发已送达图片；附件缺失/超限 `_FinalSendError`→FAILED_FINAL（不再无谓重试） |
| A12 | worker.py | `_background_tasks` 集合+done callback，create_task 不再被 GC（告警偶发静默丢失根因） |
| A13 | render_backends.py | `set_default_timeout(8000)`；页面级失败只关 page，浏览器级错误（Target closed 等 6 特征串）才重启；线程本地浏览器空闲 10 分钟回收（修一张坏卡销毁整只浏览器+阻塞渲染约 40s） |
| A14 | renderer.py | forward 溢出合并后按 node_chars 二次切分（硬边界优先于节点数上限） |
| A15 | plain_text.py | `$...$` 两侧禁邻字母/数字（"价格 $5 和 $10"不再被改写）；行级 TeX 只转换命令 token（`_convert_line_tex_tokens`） |
| A16 | bridge.py | repost.text/compact_translation/compact_romanization 预 html.escape；platform_color `#hex` 白名单（非法回退 #607080）+banner/cover_url 进 CSS url() 前 quote（模板零改动方案，样式未动） |

### 13.2 B 组修复（运行时/配置/策略域，14/14）

| # | 位置 | 修复 |
|---|---|---|
| B1 | runtime/disconnect_notice.py | Server酱/PushPlus 推送 to_thread（原同步 httpx 在掉线时刻冻结事件循环最长 16s） |
| B2 | bot.py | asyncio 异常处理器移至 `@driver.on_startup` 的 `get_running_loop()`（原 import 期 `get_event_loop` 装在死循环上从未生效；3.12+ 弃用、3.14 直接崩） |
| B3 | bot.py | 轮询失败日志按注释实现冷却放行（首条+每 300s 一条），激活死代码计数器 |
| B4 | policy/rate_limit.py SQLiteRateLimiter | `_schema_ready_paths` 一次性建表 + threading.Lock + `connect(timeout=5.0)` + 每 300s 全表过期清理（原每条消息 2 条 DDL+新连接，锁竞争变用户可见失败） |
| B5 | policy/rate_limit.py InMemory | 每 600s 清扫空/过期桶（键集合不再无界线性增长） |
| B6 | policy/gate.py | 新增 `is_command_text`：`/bot` 前缀须后随空白/结尾（`/botxxx` 不再触发命令态绕过观察期） |
| B7 | policy/reply_budget.py | `_cap_max_messages`：cap≤0=该帽不生效（修 `min(4,0)=0` 使风险/群聊帽反向变不限的语义冲突） |
| B8 | runtime/settings.py | 原子写（temp+`os.replace`）；损坏文件改名 `.corrupt-<时间戳>` 保留+warning（不再被空态覆盖清零）；实例缓存键统一清洗后名；interactions 外部重载按键 max 合并 |
| B9 | config.py | `_parse_alt_profiles/_parse_model_dicts/_parse_model_priority_groups/_parse_probe_urls` JSON 解析失败 log ERROR（键名+异常摘要，不打内容防密钥泄漏）；transport_timeout 注释对齐实际校验行为；`bot_prompt_audit_*` 注释声明仅 CLI 使用 |
| B10 | audit/logger.py、event_idempotency.py、result_unknown.py、intent_telemetry.py | sqlite 连接统一 `with closing(...)`（原 with 只 commit 不 close） |
| B11 | audit/file_logger.py | append+rotate 加 threading.Lock；rename 失败降级续写不丢审计行 |
| B12 | sources/runtime_event_log.py | 轮转 rename 失败重开后 `getsize` 回填 `_handle_bytes`（日志不再无界增长） |
| B13 | runtime/model_schedule.py | 抽出 `run_model_schedule_job`：时段表清空时若 last_applied 非空仍 reset BOT_CHAT_MODEL 覆盖（原直接 return 致覆盖永久卡死） |
| B14 | scripts/runtime_paths.py + config.py | dotenv 行内注释引号感知截断；`./data/` 前缀与大小写不敏感重映射，两侧对齐 |

### 13.3 C 组修复（__init__.py 主装配 + 人格/知识/安全域，23/23）

| # | 位置 | 修复 |
|---|---|---|
| C1[P0] | `__init__.py` | **搜图与群复读投递缺口**：`_handle_image_search` 与 parrot 分支补 `_find_sent_request`+`_deliver_transport_send_request`+诊断+通知（此前 pipeline 只入队、InMemory 队列回假 sent 回执，默认配置下这两类消息永不发出） |
| C2 | `__init__.py` | weather/eat handler 工厂互换纠正（`@weather.handle` 调 eat 工厂的复制粘贴错位） |
| C3 | `__init__.py` | `bot.eat` 加入 OFFLOADED_CAPABILITY_IDS（自然语言路径不再同步跑 Playwright+LLM 冻结事件循环数秒~数十秒） |
| C4 | `__init__.py` | 凭据健康巡检 `check_credentials_and_report`（同步 urllib 串行）to_thread 下放 |
| C5 | `__init__.py` | `run_code_debug`（同步 subprocess 15s）与大文件 write_bytes to_thread 下放 |
| C6 | `__init__.py` | 每消息被动好感度感知块（observe/classify/learn/小名自学，多次同步 SQLite）包 `_passive_affinity_perception()` 后 to_thread 下放 |
| C7 | `__init__.py` | `get_record` 预转码加 `asyncio.wait_for(20s)`，超时保留原段（NapCat 挂起不再永久卡住该用户） |
| C8 | `__init__.py` | 订阅推送两处 f-string 字面 `\n` 改真实换行 |
| C9 | `__init__.py` | 三处 `sub_ctx["store"]` 改 `.get` 判空→「订阅运行时未启动」文本结果（不再 KeyError 静默吞命令） |
| C10 | `__init__.py` | (a) 小名学习正则加 `(?<!别)(?<!不要)(?<!不许)(?<!不准)` 否定排除；(b) 小名软点名只记 `name_mention_only` 不再置 `mentions_bot`——white1/未名单群不再因常用词小名全群触发 LLM（white2 判定不变；@硬点名/私聊不变） |
| C11 | `__init__.py` | 历史上的今天推送改 `_select_credential_bot(_all_online_bots())` 只取 onebot 账号（原 `_first_online_bot` 可能拿 TG/Mail bot 发 OneBot 请求） |
| C12 | `__init__.py` | transport 分支处理完显式 return，管道回执诊断/通知仅在无 sent_request 时执行（消双诊断与重复通知） |
| C13 | `__init__.py` | 管理员文件通知 `Path(file_name).name`+空值回退（防路径逃逸落盘） |
| C14 | `__init__.py` | bot 头像 URL 缓存（按 self_id，TTL 600s）；内容解析注册表按 cookies 文件 mtime 单槽缓存（保留热更新语义；原每条链接消息同步重建） |
| C15 | `__init__.py` | `/bot reply` 未知参数回用法提示（不再静默当 auto）；`/bot 群文件` 加 `_is_admin_origin` |
| C16 | `__init__.py` | `_refresh_affinity_nicknames` 连接 finally 关闭 |
| C17 | vector_knowledge.py | (a) 暴力检索查询向量归一化（原得分=cos×‖q‖ 致 0.30 阈值失效）；(b) retrieve 锁分段——嵌入网络调用（同步 httpx 最长 60s）移到锁外，锁内仅索引一致读；(c) 运行期人格库 `fts_auto_rebuild=False` 对齐 kb_wiki（热更新不再在请求路径持锁全量重建 FTS） |
| C18 | providers.py | `_shared_affinity_store()` 共享工厂单例，消除与 `__init__` 的双实例双锁互争（异常回退本地保可用） |
| C19 | providers.py | 检索故障→空块+降级日志，不再把整文件前几块按 confidence 0.8 注入（正常无命中仍兜底） |
| C20 | content_safety.py + memory_sanitize.py | 匹配入口统一 `normalize_for_matching`（NFKC+剥 U+200B/200C/200D/FEFF+空白折叠）——全角/零宽变体不再绕过硬/软类别；归一化文本不写回存储 |
| C21 | history.py | `_ensure_schema_once` 加 threading.Lock 双检（冷启动并发双跑 ALTER） |
| C22 | shared_group.py | LLM 摘要缓存 OrderedDict LRU-32（原按全文为键永不淘汰） |
| C23 | temporal.py | 天气缓存过期返回旧值+后台守护线程刷新；无旧值才同步拉（首条消息不再被 8s 同步拉取阻塞） |

### 13.4 D 组修复（LLM 路由/渠道健康域）

| # | 位置 | 修复 |
|---|---|---|
| D1 | channel_health.py + model_router.py | 健康开关唯一解析源 `channel_health_enabled(config)`（Config→env→默认关），路由侧四处 `os.environ.get("BOT_CHANNEL_HEALTH_ENABLED","0")` 直读删除、config 显式传入——**此前 .env-only 部署下踢队/30 分钟重探/延迟择优整体空转、巡检每小时白烧 45 次真实调用、health 显示假状态的系统性脱节已修**（与 B组「健康开关来源统一」重构系同一方向，合并态吸收，见 §11.5 末条） |
| D2 | model_router.py `route_ids` | 三级解析：override 精确 id 命中→单渠道；同名聚合（价格升序/延迟择优）→`channels_for_model`；完全未知→fallback spec 合成。`/bot model set <模型名>` 聚合分支真实可达（原 `_spec_for` 对未知 id 恒合成 spec 使聚合永不可达） |
| D3 | runtime_admin.py | 并行会话已先行落地 `_env_derived_persist_entry`/`override_fields` 防遮蔽方案（见 §6.6）；本组补防回归测试（合并语义 + 旧格式向后兼容读取） |
| D4 | channel_health.py | 健康库路径统一 `resolve_default_db_path()`；单例对不一致 db_path 打 warning；model_router 删 env 相对路径默认（`BOT_CHANNEL_HEALTH_DB` 不再被读取） |
| D5 | channel_health.py + runtime_admin.py | 模块级 `_PROBE_ALL_LOCK`+`probe_in_flight()`：手动 probe 与后台巡检共享在飞互斥，重复触发回 busy（原可叠加多路全量真实调用打爆共享 key） |
| D6 | providers.py + model_router.py + chat.py | `LLMReply.attempts` 字段+`LLMProviderError.attempts`；generate 用局部 attempts 出口整体发布；失败审计 tag 读 `exc.attempts`/`reply.attempts`（并发不串号；`last_attempts` 保留为诊断快照，约 15 处既有测试依赖） |
| D7 | runtime_admin.py | `_probe_specs`：手动 probe 集合=.env ∪ 运行时注册表合并视图。**残留**：后台每小时巡检取数点在 `__init__.py` 仍只覆盖 base 注册表 |
| D8 | channel_health.py | probe_entry 删 `_config_ref` 死表达式与 frozen dataclass 属性注入，改 `api_key_override` 显式参数；预解析 `except: pass` 改 debug 日志 |
| D9 | chat.py | 失败话术去 random，纯 `(offset) % n` 顺序轮换（「同会话连发不重复」成立；无会话才随机） |
| D10 | chat.py | 工具循环逐轮累计 raw_usage 随最终 reply 产出（中间轮计费不再被覆盖丢弃） |
| D11 | runtime_admin.py | ISC003 冗余 `+` 拼接修掉（原审计报 ：246 ISC004 已不存在，实际位于 ：1031） |

### 13.5 E1 组修复（解析器与 sources 域，18/18）

| # | 位置 | 修复 |
|---|---|---|
| E1-1 | parsers/cookies.py | `min(..., default=0)`（平台全为会话 cookie 时不再 ValueError 崩掉单条消息解析）；`#HttpOnly_` 前缀行剥前缀解析（SESSDATA 类关键登录态不再静默缺失） |
| E1-2 | platforms_generic.py | xhs 剥 xsec_token 改 `(^|&)xsec_token=[^&]*&?`+strip("&")，基于路径归一化后 URL 重新 urlsplit（首/中/尾参数形态全覆盖；旧 `[?&]` 写法对 query 首参永不匹配，机制静默失效） |
| E1-3 | platforms_generic.py + media_share.py | `_unescape_js_unicode` 只点转义 `\uXXXX`（含代理对合并），字面中文不再被 unicode_escape 碎成乱码；qsmusic title/artist、`_youtube_channel_about` 同模式一并修 |
| E1-4 | platforms_bilibili.py | `build_wbi_signed_url` 改薄壳委托 `wbi._cached_mixin_key`（保留 monkeypatch 缝；每视频不再多打 2-3 次 nav 接口） |
| E1-5 | parsers/http_util.py | `DEFAULT_MAX_BYTES=8MB` **默认生效**（0/负=不限、参数可覆盖；gzip 解压同样限幅防炸弹）；`resolve_short_link` 改自定义 RedirectHandler 记录落点即中止（不再全量下载 body）；POST 单独 except HTTPError 提取状态码/Retry-After（POST 4xx 不再被误判可重试） |
| E1-6 | platforms_music.py | Apple Music cn→us 回退每国 try/except continue（对齐 `_itunes_lookup`） |
| E1-7 | platforms_taptap.py | 删 URL 拼 `&cookie=`，改 `http_get_json(cookie=...)` 请求头（凭证不再进 URL） |
| E1-8 | platforms_kurobbs.py | 移除 `ssl._create_unverified_context()`，恢复证书校验（实测该站证书 schannel 校验通过，无功能损失） |
| E1-9 | platforms_steam/epic/facebook.py | 删三处硬编码 `http://127.0.0.1:7890` 兜底代理，改读 `BOT_DOWNLOAD_PROXY`，未配置不追加跳 |
| E1-10 | platforms_generic.py | xhs `undefined` 改 `\b` 词界替换（残留风险注释声明）；`new Map(...)` 改平衡括号扫描（嵌套数组不再产生非法 JSON 致深解析静默退化） |
| E1-11 | sources/web_search.py | config=None 时装配 DuckDuckGo→Bing 兜底链（MCP web_search 工具不再永远空结果）；未闭合 `<script>`/`<!--` 残段剥离（反注入补漏） |
| E1-12 | sources/transcribe.py | 语音下载 client.stream 逐块累计 20MB 上限即弃（原整读进内存后才检查） |
| E1-13 | sources/vision_describe.py | 本地图 >8MB 跳过 data URL 走既有降级+debug 日志 |
| E1-14 | parsers/wbi.py | `_cached_mixin_key` Future single-flight（并发 miss 只一个线程打 nav；leader 失败等待方接手重试） |
| E1-15 | platforms_generic.py | `youtu.be/<id>?list=` 加 `not video_id` 前置判断（不再误走歌单分支丢单视频） |
| E1-16 | platforms_bilibili.py | 字幕空格连接+压空白（英文跨行不再粘连） |
| E1-17 | platforms_bilibili_goods.py | `float(price)` 包 try/except，脏数据置 None 降级（对齐「绝不抛」契约） |
| E1-18 | platforms_generic.py + platforms_weibo.py | YouTube 60s/微博状态卡 45s 整体预算，步骤间 monotonic 检查，超预算用已有数据出卡（单链路最坏 1-2 分钟串行占用消除） |

### 13.6 E2 组修复（订阅系统 + 能力层域）

| # | 位置 | 修复 |
|---|---|---|
| E2-1 | capabilities/subscribe_v2.py | remove/pause 权限：群聊=管理员∧本会话存在 destination，私聊=本会话存在 destination（**注：B组/C组已按审计自行落地 `_can_operate`/`_own_destinations`，本组核实语义一致后未重复改动**） |
| E2-2 | subscription_scheduler.py | per-target `except Exception`+warning 堆栈（KeyError/sqlite3.Error/ET.ParseError 不再中止整轮）；记账再抛由 finally 兜底新增 `store.release_target_lease` 只清租约**不回写过期 next_poll_at**（退避失效修复）；`deliver_outbox_once` 内层 except 收窄+try/finally |
| E2-3 | subscription_store_v2.py | claim_outbox 回收 `sending` 超 300s 陈旧行（`_OUTBOX_SENDING_STALE_SECONDS` / 构造参数 / getattr config 键 `bot_subscription_outbox_sending_stale_seconds`）；claim 时刷新 next_attempt_at 防误回收；回收行仍受 5 次死信上限（崩溃不再永久丢推送） |
| E2-4 | social_v2.py + music_v2.py + bilibili_adapter.py | 新增 `_reached_cursor`（`int(item) <= int(previous)` 截止，任一侧非数值回退相等语义）——上游删帖后整页旧内容不再每轮重发（数值 id 折衷：后加入的旧内容会跳过；BV 号路径不受影响） |
| E2-5 | social_v2.py | Twitter 凭据发现命中拿齐即 break（不再串行下载至多 12 个 x.com JS bundle） |
| E2-6 | capabilities/music.py | `ALL_PARTS` 补 `"file"`（「点歌模式 全部」不再丢音频部件）；候选二次选择改 `dict.pop` 原子取用（消同发送者 get/pop 并发双发；会话键含 sender_id 防代选已由并行会话落地） |
| E2-7 | capabilities/weather.py | `_plausible_weather_query`（≤20 字+口语感叹词首表+语气助词收尾过滤；「太/那/哈」开头真实城市不受影响，测试锁定）；群聊未命中城市 `SILENT_AUDIT` 静默、私聊明确报错；NMC/Open-Meteo 双源链路未动 |
| E2-8 | capabilities/eat.py | `_EAT_MODIFIER_RE`：extra 非空须命中修饰/约束词表（寒聊落回闲聊）；语气助词组扩展保住「吃什么啊」 |
| E2-9 | capabilities/echo.py | （并行会话已落地：帮助卡 digest 去 request_id + `prune_prefixed(keep=200)` 磁盘配额，核实一致） |
| E2-10 | capabilities/echo.py | （并行会话已落地：`_PUBLIC_HELP_TOPICS` 补吃什么/偷表情，核实一致） |
| E2-11 | capabilities/file_exchange.py | docstring 如实声明「非沙箱、以 bot 进程同等 OS 权限运行、仅限管理员」（行为未改） |
| E2-12 | capabilities/subscribe_v2.py | add 多余参数显式回「暂不支持 <参数>」（不再静默丢弃） |
| E2-13 | tests 两文件 I001 | （并行会话已修好，核实 ruff 通过） |

### 13.7 回归测试（96 用例 ×6 文件）

`tests/test_auditfix_sender_queue.py`(7) / `test_auditfix_runtime_policy.py`(16) / `test_auditfix_main_character.py`(11) / `test_auditfix_llm_route.py`(15) / `test_auditfix_parsers.py`(33) / `test_auditfix_subscriptions_capabilities.py`(14)。全部离线（tmp_path SQLite / monkeypatch 网络/时钟）。运行方式（仓库根）：
```bash
PYTHONDONTWRITEBYTECODE=1 "ChatBot_Runtime\venv\Scripts\python.exe" -m pytest tests/test_auditfix_<name>.py -q --basetemp="$TEMP/auditfix_<域>"
```

### 13.8 主会话门禁 fallout（统一裁决记录）

1. **lint 10 条**：bot.py import 排序（time 提前）+ test_auditfix_runtime_policy.py 9 条（F401/I001/RUF100×5 ruff --fix；C408 dict 字面量、F841 手改）。
2. **mypy 12+2 条**：plain_text.py `re.match` None 守卫；settings.py `_quarantine_corrupt_file` 的 `self.path is None` 守卫；disconnect_notice.py 两处 `and await to_thread(...)` 拆显式 bool 局部变量；worker.py `task: asyncio.Task` 注解；**`SendQueue` Protocol 移除 `sent_requests` 属性**（A6 连带：协议消费方只用 submit/find_request/safe_summary，列表消费方一律 `getattr(queue, "sent_requests", [])`，console_chat.py 两处同步改）；chat.py `MediaAssetRecord(**dict[str,str])` 改 `model_validate({...})`（视频会话在途代码的静态错误，行为等价）。
3. **文档 6 处**：COMMANDS.md 测试口径三处（"4 个测试"→仓库内完整套件）；route-matrix.md §2 锚点（指向不存在的 test_route_matrix.py）、§7 陈旧参数（1080P/200MB→默认不限/1GB）、§8 搜索默认 12→20。
4. 终态：lint `All checks passed`；typecheck `Success`（205 文件）；**865 passed**。

### 13.9 行为变化须知（管理员可感知）

1. 渠道健康开始真实生效：弱渠道被实际踢出故障转移、30 分钟重探回队；观察期误踢频繁可临时 `bot_channel_health_enabled=false` 两侧同关回退。
2. SQLite 发送队列新行 60s 内由内联投递负责；`run_queue_smoke` 在 submit+2s 时 delivered=0 属预期。
3. 群聊「天气冷了」「吃了吗」类寒聊不再回复/报错（静默记账）；私聊仍明确报错。
4. 小名独占触发的消息在未名单/white1 群不再必然回复；`@小名` 与私聊语义不变。
5. 设置文件损坏会多出 `.corrupt-<时间戳>` 文件（排查「配置丢失」先看它）。
6. `/bot reply <未知参数>` 回用法提示而不是悄悄设成 auto。

### 13.10 已知残留（按优先级）

| 项 | 说明 | 建议 |
|---|---|---|
| D7 后台巡检集合 | 手动 probe 已含运行时渠道；后台每小时巡检取数点在 `__init__.py` 仍只覆盖 .env 注册表 | 改为 `_probe_specs` 同款合并视图 |
| 旧注册表快照迁移 | 无 source 标记的存量运行时条目仍整体遮蔽 .env 同名条目 | 对相关条目重新 `/bot model update` 一次即迁移 |
| A9 代理解析 | sender 层拿不到运行时 Config，走 `bot.config→env` 探测 | 后续注入 provider 或统一读 env |
| 小名否定排除宽度 | 只挡紧邻前缀，「千万别叫我X」仍会学 | 正则扩 `(?:别|不要|千万别|谁)\s*叫` 前置分支 |
| spicy_filter flaky | `test_eat_capability::test_spicy_filter` 约 2.3% 随机失败（鱼香肉丝简介含"酸辣"；预存问题） | 固定 seed 或剔除歧义菜 |
| C12 边缘语义 | transport 失败且回执无 public_message 时不再用管道回执 finish 兜底重发（去重方向的取舍） | 观察 result_unknown 台账量 |
| 模板品牌色残留 | universal_card.html 仍有 `#fb7299`/`#1d9bf0` 等写死语义色（VIP/认证徽章、Top3 序号） | 卡 UI 迭代时收敛进 PLATFORM_COLORS 派生（改后必跑样例截图+三门禁） |
| 本轮修复未提交 | §13.0：修复主体约 90+ 文件仍在工作树 | 按 §11.4 部分暂存规程分域提交 |

### 13.11 与各会话协同事件（存证）

- A4 修复 `_prune` 后，并行会话追加的「总量硬顶 DELETE」会删 QUEUED 在途行，按 A4 契约移除；对方随后把 `test_soak_growth.py` 改写为兼容 A4 的弱不变量，冲突消解。
- D 组编辑期间 model_router.py/channel_health.py 被并行会话多轮重写（EWMA v2、hedged request）；D1/D2/D6 契约均被保留整合（其 worker 注释「绝不触碰 self.last_attempts——D6」）。
- E2 的 5 项（订阅鉴权、模式词冲突、help digest、help topics、测试 I001）并行会话已按审计报告自行修复，核实语义一致后跳过。
- `tests/test_render_backends.py` 浏览器重置测试已被改写为 A13 新语义（页面级失败保留浏览器），无需处理。
- `test_auditfix_runtime_policy.py` 与 B 组 runtime policy 修复集经 f96d1a1 共享 index 裹挟入库（对方已在 §8 存证）；其余 5 个测试文件与修复主体待显式提交。

---

*本文档由 09-10 B组会话（渠道运维/UI/点歌/审计修复/算法 v2/历史修复/平台实测/管线检视）主笔；§13 由 09-10 深夜审计修复会话（全库审计 + 三类别 90 项修复轮 + 96 回归测试）增补并自署；§14 由 09-10 A组解析会话（解析专项/卡片渲染/点歌实测）增补并自署。整合 A组（解析专项）、C组（好感度与质量）、视频会话、基建会话同日交付。旧活文档继续按其自身规则维护，两者不一致时以本文+git 历史为准。*

---

## 14. 附篇：解析 / 卡片 / 点歌 深度手册（A 组解析会话主笔，事无巨细版）

> 本附篇是 A 组解析会话独立成文的深度手册全文并入，内部小节编号 **§14.0~§14.22 为附篇自有编号**，
> 与上文 §0~§13 相互独立、不互指；两套编号以所在章节语境区分。
> 覆盖面：目录地图 / 消息主链路逐跳 / dev.ps1 全任务 / 配置密钥链 / 解析器矩阵（B站双通道、
> 微博三通道+访客兑子、xhs 签名 URL 铁律、油管推特、会员购全字段、竖切横图拼接）/ 卡片渲染
> （Mica 细则、ORB 兜子、data URL 内联、转义规则）/ 点歌候选决策树全版 / 模型路由 / 记忆好感度 /
> 安全 / 订阅 / 适配器 / 告警 / 测试约定 / 排障手册 17 条 / 硬约束 / 并行会话规范 / 已知边界 /
> 修复史全索引 / 完成判定 / 下一步建议。全部结论标注实测依据。

> 本文件是**从零重写的全新交接文档**，不基于旧文档增补；旧文档
> `docs/handoff-final-2026-09-07.md`（及其 git 历史）保留作过程档案。
> 定位：任何新会话/AI/人只读这一份，即可完整接手系统的**所有**子系统、
> 运维操作、已知坑与设计取舍理由。
> 编写时点：2026-09-10，分支 `v0.0.1-alpha.2`，HEAD 见 `git log -1`。

---

### 14.0. 三分钟速览

- **是什么**：QQ（NapCat/OneBot V11）为主的多人设聊天机器人，附带 Telegram / Mail / Console 适配器。核心能力：37+ 平台链接解析（Mica 卡图渲染）、多供应商点歌（候选选歌卡+歌曲卡+语音）、模型路由与渠道健康巡检、记忆/人格/好感度/向量知识库、订阅推送、搜索 API、内容安全防线。
- **代码规模**：插件主包 `plugins/bot_unified_runtime/`；`__init__.py` 约 5280 行（handler 装配/能力分发）；`config.py` 973 行 **426 个配置字段**；解析器 34 个文件；测试 111 个文件 **865+ 用例**。
- **验证基线**（2026-09-10 本轮交付时点）：`dev.ps1` 三门禁 = **865 passed / ruff 全过 / mypy 本组分文件零错**（树内常有并行会话在途文件的少量 mypy 残留，见 §14.19）。
- **一句话架构**：NapCat(WS 服务端 127.0.0.1:3001) ← bot(forward-WS 客户端) → IngressGateway → 路由/风控 → RuntimePipeline → CapabilityResult → 渲染(HTML→PNG 卡图) → SendQueue(SQLite) → 各适配器 sender。
- **最重要的三条纪律**（踩过实坑）：
  1. **密钥永不入库不入聊天**：真实 key 只在 `.env`（gitignored），配置里用 `env:变量名` 间接引用，且对应的 `bot_api_key_*` Config 字段**必须存在**（缺字段=env: 解析失败=整渠道失效，09-09 事故根因）。
  2. **commit 禁用 `git add -A`**：本仓库常有 2~3 个 AI 会话并行工作，`-A` 会裹挟别人未提交的半成品；只 `git add <明确路径>`。同理**共享 index 陷阱**：别的会话可能已把文件 `git add` 进暂存区，`git commit`（不带路径参数）会连他们的暂存一起提交——提交前 `git diff --cached --stat` 检查，或事后在 handoff 存证（f96d1a1 即实例）。
  3. **改动"没生效"先查进程启动时间再查代码**：`Get-Process python | Select Id,StartTime` 对比最后一次提交时间；bot 常驻进程不会热加载。

---

### 14.1. 运行环境与目录地图

```
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├── ChatBot\                     ← 唯一默认工作区（AI 只扫这里）
│   ├── bot.py                   ← 入口：NoneBot 启动 + 崩溃守卫 + TG 过滤器
│   ├── .env / .env.prod         ← 全部配置（.env 在 .gitignore；.env.prod 进库不含密钥）
│   ├── pyproject.toml           ← ruff/mypy/pytest 配置（basetemp 固定在源码树外）
│   ├── scripts/
│   │   ├── dev.ps1              ← 所有开发任务的统一入口（见 §14.3）
│   │   └── runtime_paths.py     ← BOT_RUNTIME_DATA_DIR 解析规则（data/ → Runtime 根）
│   ├── plugins/bot_unified_runtime/
│   │   ├── __init__.py          ← ~5280 行：plugin 装配、路由分发、各能力构建与接线
│   │   ├── config.py            ← 426 字段 Config + translate_env_keys
│   │   ├── runtime/             ← pipeline / ingress / base_router / aliases / settings /
│   │   │                          alerts / disconnect_notice / result_unknown / runtime_event_log
│   │   ├── capabilities/        ← 27 个能力模块（§14.8~§14.12 逐个说明）
│   │   ├── sources/
│   │   │   ├── parsers/         ← 34 个文件：34 文件矩阵见 §14.7
│   │   │   ├── fetchers/        ← PlaywrightFetchBackend（xhs 等真浏览器抓取）
│   │   │   ├── subscriptions/   ← social_v2 / xiaohongshu_adapter / youtube 适配器
│   │   │   ├── video_understanding.py / transcribe.py / vision_describe.py
│   │   │   ├── steamfree.py / web_search.py / meme_library_listener.py
│   │   │   └── credentials.py / platform_credentials.py
│   │   ├── character/           ← affinity / providers / memory / history / vector_knowledge /
│   │   │                          media_registry / shared_group / temporal
│   │   ├── security/            ← content_safety / memory_sanitize
│   │   ├── output/              ← renderer / plain_text / templates / render_backends /
│   │   │                          card_render/(bridge.py models.py templates/universal_card.html
│   │   │                          templates/song_candidates.html templates/affinity_card.html)
│   │   ├── llm/                 ← model_router / providers / channel_health
│   │   ├── sender/              ← onebot / nonebot / gateway / queue / receipts / worker
│   │   ├── policy/gate.py       ← 群门禁（URL 支持判定走注册表缓存）
│   │   ├── audit/logger.py      ← 脱敏审计
│   │   └── contracts/           ← media.py(ParsedContent 全家桶) / runtime.py / character.py
│   ├── tests/                   ← 111 个测试文件（865+ 用例）
│   └── docs/                    ← 本文档、handoff-final-2026-09-07.md（旧过程档案）、
│                                  affinity-design.md、capability-audit-2026-09-10.md 等
├── ChatBot_Runtime\             ← 运行数据根（默认不扫描不修改！）
│   ├── venv\                    ← 唯一运行虚拟环境（865 测试/playwright/PIL 都在这里）
│   ├── data\                    ← platform_cookies.txt / SQLite 库 / FAISS / cards / music /
│   │                              media_stitch / food_images / 订阅状态 / 记忆库
│   ├── logs\nonebot.out.log     ← dev.ps1 启动重定向日志
│   └── git\                     ← git 元数据外置目录（见 §14.18 git 陷阱）
├── ChatBot_Archive\             ← 归档区（历史/旧工作树，压缩后移入）
└── C:\Software\NapCat\          ← NapCat 本体 + login-bot.bat（快速登录脚本）
```

**路径重映射规则**（`scripts/runtime_paths.py` + `config.py` + `cookies.py` 各有一份等价实现）：
`data/...` 相对路径 → `BOT_RUNTIME_DATA_DIR`（.env=`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/data`）。env 未设置时解析器一律**禁用写文件行为**（如 `image_stitch.py` 直接不拼接），绝不往源码树写。

---

### 14.2. 消息主链路（逐跳）

```text
QQ 客户端 ⇄ NapCat（OneBot V11 正向 WS 服务端，127.0.0.1:3001，token=ShoreKeeper）
   ↑↓ forward-WS（.env.prod ONEBOT_WS_URLS；NapCat 重启后 bot 自动重连）
bot.py（NoneBot 初始化 + 崩溃守卫：主循环异常自动重启；TG 轮询过滤器在此）
   → plugins/bot_unified_runtime/__init__.py
      ① _incoming_from_nonebot_event() → IngressGateway → IncomingMessage（严格 pydantic 模型）
      ② 路由（runtime/base_router.py）：RouteDecision{capability_id, rest_text, priority}
         - 命令：/bot <模块> <功能> [参数]（runtime/aliases.py 别名表归一）
         - 自然语言触发：chat / poke / 音乐 / 吃什么 / 天气 / wiki …（各 is_xxx_command）
         - URL → 解析管线（_has_supported_url 走注册表缓存单例）
      ③ 门禁/风控（policy/gate.py + __init__ 内联）：
         群黑白名单 → 安静时间（BOT_QUIET_HOURS_*）→ 限流（BOT_RATE_LIMIT_*，SQLite 窗口）
         → 幂等表（BOT_EVENT_IDEMPOTENCY_ENABLED 默认 false，进程内+SQLite 双层）
         → 内容安全（security/content_safety.py 硬/软类别）
      ④ RuntimePipeline.run() → CapabilityResult{kind, title, body, images[], audio[], files[], audit_tags[]}
      ⑤ Review（risk/privacy 评定）→ output/renderer.py → RenderedOutput
         （text / chunks / forward / mixed 四种 content_type；媒体部件透传规则见 renderer.py）
      ⑥ SendQueue（SQLite 持久化）→ UnifiedDeliveryGateway → sender.onebot / sender.nonebot
      ⑦ 发送回执 receipts / result_unknown 账本（重连对账，不盲发）
```

关键设计取舍：
- **发送层丢消息是 P0 事故**（09-09 实锤：LLM 慢烧完 90s 预算后发送层静默丢）。现在请求总预算 150s（`bot_request_budget_seconds`），**预算耗尽不丢已生成回复**，给足传输超时。
- 群聊 LLM 失败**静默**；私聊失败回 `_PERSONA_FAILURE_MESSAGES` 12 条守岸人话术轮换（`capabilities/chat.py`）。
- `bot.content` / `bot.music` 等长任务在 `to_thread` 里跑；playwright 渲染全大锁串行+线程本地常驻浏览器（`output/render_backends.py`）。

---

### 14.3. 启动、停止、验证（dev.ps1 全量任务）

```powershell
# 统一入口（PowerShell；Git Bash 下写 .ps1 临时脚本执行，防 $_ 被吞）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task <task>"

# —— 三门禁（每轮交付前必须全绿）——
-Task test        # pytest 全量（当前 865 passed）；basetemp 已固定在源码树外
-Task lint        # ruff check
-Task typecheck   # mypy（205 文件）

# —— 启动前体检 ——
-Task doctor              # 环境体检
-Task backend-base-smoke  # 基础后端冒烟
-Task backend-smoke       # 完整后端冒烟
-Task chat-smoke          # 聊天链路冒烟
-Task search-smoke        # 搜索 API 验收（Tavily/You/TinyFish 真实 key）
-Task runtime-layout      # Runtime 目录布局检查（勿在手动删除缓存后立即跑）
-Task kb-sync             # 知识库同步（--kb-full 全量 / --kb-no-embed）
-Task smoke               # 综合冒烟
-Task run                 # 启动 bot（日志重定向 ChatBot_Runtime/logs/nonebot.out.log）
```

**启动顺序**：
1. NapCat：`C:\Software\NapCat\login-bot.bat`（UAC 确认，快速登录守岸人 3958874605）。
   验证：`netstat -ano | findstr 3001` 出 LISTENING。
2. bot：`ChatBot_Runtime\venv\Scripts\python.exe bot.py`（或 dev.ps1 -Task run）。
   确认**只有一个实例**（先查进程启动时间再查代码！）。bot 起来后自动连 NapCat。

**绕开 dev.ps1 直接跑 python/pytest 的铁律**：必须 `PYTHONDONTWRITEBYTECODE=1` + pytest 加 `--basetemp=<源码树外目录>`，否则源码树会出现 `__pycache__`/.pytest_cache（runtime-layout 会报，且违反工作区规范）。

---

### 14.4. 配置体系与密钥

#### 14.4.1 Config 加载链

```
.env / .env.prod（NoneBot dotenv）→ driver.config
→ translate_env_keys()（BOT_X → bot_x，幂等小写化，config.py:11）
→ Config.model_validate(...)（pydantic，426 字段，config.py:28 起）
```
字段分域（前缀即域）：`BOT_RUNTIME_*`（实例/管理前缀/别名）、`BOT_PERSONA_*`+`BOT_TONE_*`（人格语气）、`BOT_ADMIN/BLOCKED/TRUSTED_USER_IDS`、`BOT_GROUP_*`（黑白名单/摘要/主动回复）、`BOT_QUIET_HOURS_*`、`BOT_RATE_LIMIT_*`、`BOT_MUSIC_*`、`BOT_PARSE_*`、`BOT_CHANNEL_HEALTH_*`、`BOT_CARD_*`、`BOT_SEARCH_*`、`BOT_MODEL_REGISTRY`（整段 JSON）、`BOT_API_KEY_*`（密钥区，env: 引用的解析目标）等。

#### 14.4.2 密钥规则（不可违反）

- 真实 key 只存在于 `.env`（gitignored）。配置值写 `env:BOT_XXX_KEY` 形式。
- `env:` 解析链 = `os.environ → Config 同名字段回退`。**对应 `bot_api_key_*` 字段不存在 → 解析结果 config_missing → 该模型全渠道失败**（09-09 五连发失败事故根因，当时补了 9 个字段）。
- Cookie 与密钥值永不进日志/审计/消息（`audit/logger.py` 脱敏 + `cookies.py` 只暴露 cookie 名）。

#### 14.4.3 Cookie 文件

- 路径：`ChatBot_Runtime/data/platform_cookies.txt`（Netscape 格式）。
- 管理：管理员指令 `/bot cookie import <平台> <Cookie头>` 热写入；或直接编辑文件追加 Netscape 行。
- 平台域名白名单与关键 cookie 名：`sources/parsers/cookies.py:PLATFORM_COOKIE_DOMAINS`（bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe）。
- **当前实装状态**（2026-09-10）：小红书 ✓（web_session 有效）、微博 ✓（09-10 灌入登录态 SUB/ALF/SUBP）；**B站无登录态**（建议 `/bot cookie import bilibili`，可解锁 AI 字幕+降低 -352 面积）；X 无凭证（订阅推特前必须先 import）。
- 微博解析有无登录态都能用：无登录态自动走 genvisitor 访客兑子（`platforms_weibo.py:_weibo_visitor_cookie`，进程内缓存 6h；genvisitor→incarnate 换 SUB/SUBP/tid）。

---

### 14.5. 解析器矩阵（sources/parsers/，34 文件全量）

#### 14.5.1 架构

- 注册中心 `parsers/__init__.py`：`_PLATFORM_RULES`（平台→URL 正则→解析函数→优先级），`build_content_parser_registry(enabled_platforms, cookie_provider, proxy, playwright_backend)` 返回 `{registry, parsers}`。
  - **全默认参数调用有进程级单例缓存**（`_DEFAULT_REGISTRY_BUNDLE`）：群门禁每条消息全默认调一次，缓存后零重复构建。
  - 代理绑定 `_PARSER_PROXY_PLATFORM`：youtube/twitter/spotify/pixiv×5/facebook 走 `BOT_DOWNLOAD_PROXY`（127.0.0.1:7890）。
  - playwright 绑定：xiaohongshu、kurobbs。
- 公共设施：`http_util.py`（http_get/text/json/post_json，代理/UA/重试/gzip）、`wbi.py`（B站 WBI 签名，键 30 分钟缓存）、`cookies.py`（§14.4.3）、`image_stitch.py`（竖切横图拼接，§14.5.9）。
- 契约：`contracts/media.py` `ParsedContent`（纯嵌套：identity/content/creator/engagement/media/music/provenance）+ `build_parsed_content()` 归一化构造器。解析器产出平台形状字段（stats/detail），构造器负责映射；`detail` 键消费白名单 `_DETAIL_CONSUMED_KEYS`、作者键 `_AUTHOR_CONSUMED_KEYS`。
- **时间契约（重要）**：`_optional_datetime` 对 naive 时间一律按**北京时间**解释（`_CN_TZ=+08:00`）。解析器不得产出 naive 字符串当 UTC；带时区 ISO 或 epoch 最稳。字符串发布时间经此归一，展示层 `astimezone()` 得到正确本地时间。（历史：误标 UTC 曾致微博/推特/专栏时间整体漂 8 小时，09-10 契约层根治。）

#### 14.5.2 B站（platforms_bilibili.py，~2100 行，A组主战场）

分发入口 `parse_bilibili()` 按 URL 形态分流（b23.tv/bili2233.cn 短链先 `resolve_short_link`）：

| 形态 | 函数 | 数据通道（按可靠性排序） |
|---|---|---|
| 视频 BV/av | `_lookup_video_by_id` | `x/web-interface/view` 主数据 + `_author_enrichment`（card 签名/relation 粉丝关注/navnum 视频专栏数/upstat 获赞+总播放，**WBI 签名**）+ AI 总结（view/conclusion/get，WBI）+ 字幕（player/wbi/v2，ai-zh 优先，需登录 cookie）+ 热评（v2/reply ps=3 sort=1） |
| 直播间 | `_parse_live` | **主通道 `room/v1/Room/get_info`**（匿名稳，失败 1s 重试一次）+ `get_status_info_by_uids` 补主播昵称/头像/粉丝（POST，匿名可用）+ getInfoByRoom **降为尽力富集**（人气/在线/大航海 TOP3；对无登录态常态 **-352**，buvid3/4+浏览器 UA 实测无效——这就是主通道切换的原因） |
| 专栏 cv | `_parse_article` | `x/article/view` + `_author_enrichment` 全量注入；**-509/-352/-412/429 短停 1.5s 重试一次**（瞬态 IP 风控，实测隔秒自愈） |
| 直播富集 | guardTopList | 大航海 TOP3，尽力而为 |
| 空间 | `_parse_space`/`_parse_favlist` | card + navnum + relation |
| 动态 opus | `_parse_opus` | polymer web-dynamic/v1/opus/detail |
| 番剧 | `_parse_bangumi` | season view + stat；失败回退 og |
| 课程 | `_parse_cheese` | pugv/view/web/season |
| 漫画 | `_parse_manga_card` | twirp TLS 指纹风控 code=99 **不可破**，诚实降级浅卡 |
| 会员购 show | `parse_bilibili_show` | `show.bilibili.com/api/ticket/project/getV2`，全字段见 §14.5.8 |
| 合集/搜索/公益/游戏/电竞 | 各 `_parse_*` | 见文件内 docstring |

**实测经验（2026-09-10）**：`web-interface/view`、`popular`、`Room/get_info`、`get_status_info_by_uids`、`finger/spi` 匿名可用；`article/view`、`xlive/getInfoByRoom`、`player/wbi/v2` 受波动 IP 风控（-509/-352），有登录 cookie 面积大幅缩小。`x/space/upstat` 需 WBI 且常需登录（拿不到就静默跳过）。
**时长口径**：`stats["时长"]` 存**整型秒**（字符串会让桥接 duration pill 退化成 0:00）；人类可读"X分Y秒"只在摘要行拼装。

#### 14.5.3 微博（platforms_weibo.py）

- 单条微博三通道：①`m.weibo.cn/statuses/show?id={bid}`（JSON）→ ②`weibo.com/ajax/statuses/show`（PC ajax）→ ③`m.weibo.cn/status/{bid}` 页面 `$render_data`。通道前置 **`_weibo_merge_cookies`**：调用方 cookie 优先，缺失并入 genvisitor 访客兑子（缓存 6h）。
- m.weibo.cn 必须**移动端 UA + XHR 头**（PC UA 一律 302 访客验证 retcode=6102）。
- 头像 `_weibo_avatar`：avatar_hd 优先，`/50/`→`/180/` 升级，http→https。
- 视频帖：`page_info.media_info` 取直链，`page_pic` 作封面（无图集时）。
- 发布时间：`created_at`（英文格式带 +0800）strptime %z → **aware ISO 秒级**。
- 标题剥「xx的微博视频」尾缀。
- 长微博 `/statuses/extend` 补全文；图集 `pic_infos.largest`。
- **图片灰块事故结论**：xhs/sina 图床在 Chromium `<img>` no-cors 下被 **ORB** 拦（ERR_BLOCKED_BY_ORB）——修法见 §14.6.4 render_backends。sinaimg WAF：**直连+curl 形极简头 200；浏览器 UA 缺完整头 403；python TLS 指纹 403**。

#### 14.5.4 小红书（platforms_generic.py 内 parse_xiaohongshu，~370 行起）

- 流程：xhslink 短链解析 → /discovery/item/ 归一 /explore/ → 用户主页（playwright capture_json user_posted → INITIAL_STATE → og）→ 搜索页关键词卡 → **笔记页深解析** → og 兜底。
- **笔记深解析 `_xhs_note_deep_parse`（09-10 修复）**：先 http_get_text（带 cookie）；失败或缺 `INITIAL_STATE` → **playwright fetch_html 兜底**（此前 backend 参数只用于用户主页，笔记页被 xhs 间歇 403/461 拦后就直接落 og 空卡——真实缺陷已修）。
- `xsec_token` 失效（整页 404）：自动剥 token 重试一次；仍失败给明确汇报文案（让用户重新分享）。
- **图片 URL 铁律（实测血泪）**：2026 版 xhscdn 的 `!nd_dft_*` 后缀**在签名路径内，剥掉即 403**（200→403 对照实测）。质量提升唯一合法姿势：优先 `imageList[].info_list` 里 `image_scene=="WB_DFT"` 的变体，否则 urlDefault/url **原样使用**。`_xhs_original_url` 剥！函数已删除（ed0fedb 引入、f96d1a1 撤回）。
- `_strip_js_new_map`：INITIAL_STATE 里 `new Map([...])` 平衡扫描替换为 null（嵌套数组防 JSON 截断）。
- URL 时效：图片地址带时间戳签名（约 10 分钟级），解析→渲染/发送要快；过期 403 属正常。

#### 14.5.5 YouTube（platforms_generic.py parse_youtube，需代理）

三层合并：watch 页正则（标题/描述/时长）+ innertube 端点（作者数据）+ about 页（频道粉丝）。封面 `i.ytimg.com/vi/{id}/maxresdefault.jpg`；模板 onerror 自动回退 hqdefault（universal_card.html 封面 img）。字幕 captionTracks（ASR 滚动重叠去重）→ 摘录+`BOT_PARSE_SUBTITLE_SUMMARY=true` 时主路由出【AI字幕总结】。
边界：频道总获赞官方不提供；长/短视频数与 post 数需逐 Tab 抓取（未做）。

#### 14.5.6 推特/X（platforms_generic.py parse_twitter_x，需代理）

fxtwitter 聚合接口（`api.fxtwitter.com/{user}/status/{id}`，`code==200` 门槛，纯媒体推文也走深分支）→ og 兜底。图片 `_twitter_large_url` 补 `name=large`；**photos 全量进 images**；`created_timestamp` epoch → `_format_epoch` 带时区 ISO。媒体多为 4 图竖切横图 → `try_stitch_strip` 拼接（§14.5.9）。

#### 14.5.7 其他平台速览

| 文件 | 平台 | 要点 |
|---|---|---|
| platforms_music.py | 网易/QQ/酷狗/酷我/Apple/Spotify | 见 §14.9 点歌 |
| platforms_zhihu.py 系 | 知乎/豆瓣/TapTap/虎扑/贴吧等 | parser-lite 批次，og+API 混合 |
| platforms_discourse.py/community.py | Discourse 论坛/社区 | JSON API |
| platforms_acfun/kuaishou/lofter/... | 各社媒 | 注意各自 stats["发布时间"] 均产出 naive 本地串 → 契约层已按 +08 解释 |
| platforms_epic.py / steam.py | Epic/Steam 喜加一 | 免费游戏卡（capabilities/epic + steamfree.py） |
| platforms_moegirl.py | 萌娘百科 | moegirlSSOToken cookie |
| platforms_generic.py 其余 | 抖音（_ROUTER_DATA）、汽水/豆包/米画师/画加/BUFF | 抖音反爬拦截时给降级卡 |

#### 14.5.8 会员购全字段（parse_bilibili_show，09-10 重写）

getV2 一发拿全，可见面=summary 行+stats，结构化全量存 `detail["show"]`：
- 档期 `project_label`、起止 `start/end_time`
- 场馆 `venue_info.name`+`place_info.name`（展厅）+城市+`address_detail`
- 票价 `price_low/high`（**分→元**）
- 场次 `screen_list[]`：名称/时间/售票状态 + `ticket_list[]` 票档明细（desc/价格/开售窗/状态）
- 票种 `has_eticket/has_paper_ticket` + 票档 desc 关键词（电子/实体/兑换）
- 退票 `refund_desc`（"支持/不支持7天无理由退票"）
- 嘉宾 `guests[]`：name/description/guest_img/book_num → **独立卡区**（bridge `show_guests` 投影 + universal_card 嘉宾网格）
- 主办 `merchant.company`；博主位 `follow_info.up_name/up_face`（无则主办方撑布局）
- 图文详情 `performance_desc.list[]`：**details 可能是 HTML 串或 [{title,content}] 列表**（`_show_module_text` 双形态适配）+ gallery 图片提取
- 实测样例：88451（苏州OCG，12嘉宾）、96799（惠州镜漫，4嘉宾）全字段上卡。

#### 14.5.9 竖切横图拼接（image_stitch.py）

识别"横图竖切 N 块"发布形式：同尺寸竖图组（±2px 容差、单张 h/w≥1.12、n∈2..10、拼接总宽高比 1.0~4.0）→ PIL 横向拼回 → 落盘 `data/media_stitch/strip_{sha1}.jpg`（q90）。推特/小红书/微博三平台接入；任一图下载失败或条件不满足**原样返回不丢图**。BOT_RUNTIME_DATA_DIR 未设置时整功能自动禁用（防源码树写文件）。

---

### 14.6. 卡片渲染管线（Mica 规范）

#### 14.6.1 管线

```
CapabilityResult → content_parser.render_card_png(backend, item, config, card_dir, bot_avatar_url)
  → bridge.parse_to_render_payload（ParsedContent→RenderPayload 字段全量投影）
  → bridge.render_universal_card_html（Jinja2，autoescape=True）
  → render_backends（PlaywrightRenderBackend：线程本地常驻 Chromium，
     page.set_content(networkidle) + img.complete 等待 + .card 元素截图 omit_background）
  → PNG 落盘 data/cards/ → CapabilityResult.images=[{"file": path}]
```

- **分支选择**：`use_universal`（有 page_type/badge/detail 或平台在 universal 集合）→ Mica 分支；否则 legacy 分支。点歌成功卡走 **legacy 分支**（实测显示效果好，已验证）。
- **UI 缩放**：`bot_card_ui_scale`（1.25 基准语义），card_width 1440px。

#### 14.6.2 Mica 规范（AGENTS.md 硬规则）

- 底色渐变唯一来源：`PLATFORM_COLORS`（bridge.py:40，bilibili #fb7299 / xhs #ff2442 / weibo #e6162d / youtube #f00 / twitter #1d9bf0 / netease #c20c0c / qqmusic #00c853 / kugou / kuwo / apple_music / spotify / douyin / pixiv / lofter / allcpp / facebook / instagram），经模板 `--pc` 变量 `color-mix(in srgb, var(--pc) N%, #fff)` 掺白派生。**禁止写死品牌色**（含岸宝粉）——历史上大会员徽章写死 #fb7299 曾把全平台染成B站粉（已修为 --pc 派生）。语义状态色（认证金/错误红）不算品牌色。
- 阴影只允许 `--mica-shadow` + `--mica-shadow-soft` 两枚 token；圆角 `--r-shell/--r-panel/--r-tile`；字重≤700；`body` 透明背景+antialiased。
- `song_candidates.html`/`affinity_card.html` 为独立模板（B组/C组产），同样遵守派生规范。

#### 14.6.3 RenderPayload 关键字段（models.py）

身份/内容（name/avatar/title/summary/text/image_urls/cover_url/qrcode）、Header 五行（signature/handle/follower_count/timestamp/official_*）、统计（stats/author_stats/video_stats/stats_bar_items/author_stat_items）、视频（video_duration/video_desc/video_pages）、评论（pinned/hot/comments）、**show_guests**（会员购嘉宾网格）、直播（live_*）、平台主题（platform_color 系列）、bot（bot_name/bot_avatar_url）、card_width/font_scale。

#### 14.6.4 本地图片与 ORB（两个曾致灰块的坑）

1. **本地文件**：playwright 以 about:blank 起页，`file://` 子资源被拒载 → `bridge._inline_local_image` 把本地图转 **data URL** 内联（12MB 上限；吃什么卡菜品图因此修复）。
2. **ORB 拦截**：Chromium 对部分图床（**wx*.sinaimg.cn** 实测）的 `<img>` no-cors 请求直接 `ERR_BLOCKED_BY_ORB`（卡上封面/头像全灰）→ `render_backends` 对 `_ORB_PRONE_HOST_SUFFIXES`（sinaimg.cn/weibocdn.com）安装 `page.route`：**直连+curl 形极简头**（`_ORB_FETCH_HEADERS`）python 侧取回字节 `route.fulfill`。取回头形态实测矩阵：sinaimg WAF 对「浏览器 UA 缺完整头」和「代理出口 IP」都 403，**直连+curl 极简头才 200**。名单外不拦截（避免每图双下载）。
3. 渲染失败语义（并行会话改版）：页面级错误只关页面复用浏览器；浏览器级错误（Target closed 等 `_BROWSER_CRASH_MARKERS`）才重置常驻浏览器。

#### 14.6.5 转义规则（易踩）

bridge 对 `payload.text/summary/forward.text/repost.text` **预 html.escape**；legacy 分支模板用 `| safe`（净一次转义）；**Mica 简介分支**是 `{{ video_desc or summary | safe or text | safe }}`（video_desc 未预转义靠 autoescape，summary/text 已预转义用 safe——新增渲染点务必分清）。CSS 注入由 `_safe_css_color/_css_url_token` 阻断。

---

### 14.7. 点歌子系统（capabilities/music.py，~795 行）

#### 14.7.1 搜索与候选决策树（完整版）

```
「点歌 X」→ base_router is_music_command（模式词/别名由 B组 P3#23 修复：不再吞消息）
  → capability():
    X 以 # 开头 → 剥 #，强制按歌名搜索
    X 是模式别名（link/卡片/语音…）→ 冲突提示 + 「点歌 #X」转义用法（不搜）
    X.isdecimal()（十进制才安全，"²" 不再崩）:
        会话命中（session+sender 隔离、TTL 内、编号在界）→ detail_fn(候选) → _render_hit
        否则 → 「编号不在候选里，重新点歌」提示（绝不拿数字当歌名搜）[music_candidates_miss]
    候选启用（BOT_MUSIC_CANDIDATES_ENABLED && candidate_providers 非空）且 X 非纯数字:
        list_fn(X, limit=candidates_limit)   ← limit 全平台透传（原先硬编码5截断）
        len(cands)>=2 且非「裸歌名+首条精确同名」→ 存会话 → _render_candidates_card
            （song_candidates.html → PNG；失败逐字回退纯文本编号列表 [music_candidates_card]）
        裸歌名（无空格）且精确命中 → 跳过候选直接播放（点歌 晴天 → 周杰伦）
        带限定词（「晴天 钢琴版」）即使存在字面同名命中也出候选窗
            （网易云模糊搜索几乎总能搜出字面同名翻唱——旧 exact_hits 一票否决
             曾让候选卡几乎不可达，09-10 根治）
    未命中候选 → 逐平台 search_fn 单结果 → _render_hit
```

- 会话存储：`_CANDIDATE_SESSIONS[session_type:session_id:sender_id] = (expires, parser_id, cands)`；`_CANDIDATE_MAX_SESSIONS` 容量上限+最旧逐出。
- 二次选择详情：`candidate_providers[platform][1]`（`.get()` 判空降级）；QQ/酷狗/酷我/网易各有关键 ID 直取详情；酷狗复用 `parse_kugou`（getSongInfo：封面+标题+试听）。

#### 14.7.2 成功卡与发送（_render_hit）

优先级：**Mica 歌曲卡 PNG**（`_render_music_card_png` → render_card_png，失败 warning 日志）> **封面直链** > CQ:music 签名卡（最后——NapCat 缺 musicSignUrl 会拒签并中断整条消息）。语音：`mode` 含 voice 时音频下载（ffmpeg 转 OGG/OPUS，失败降级）。实测真实数据：网易云《晴天》搜索→候选卡→编号选择→成功卡（封面/歌手/专辑/平台色全对）+语音。

#### 14.7.3 供应商现状（实测 2026-09-10）

| 平台 | 搜索 | 候选 | 备注 |
|---|---|---|---|
| 网易云 | ✅ 匿名 | ✅ limit 透传 | 主力；pic_str 是资源 ID 不是 URL（已剔）；网易云模糊搜索几乎必出字面同名翻唱 |
| QQ | ✅ **musicu.fcg DoSearchForQQMusicDesktop**（POST） | ✅ | **旧 client_search_cp 服务端下线（任意参数恒 500，实测）**；封面 `album.mid` 拼 `y.gtimg.cn/music/photo_new/T002R500x500M000{mid}.jpg`；音频 vkey 需登录 |
| 酷狗 | ✅ msearchcdn（**明文 http**，证书主机名不匹配——已知取舍） | ✅ | 编号详情复用 parse_kugou |
| 酷我 | ⚠️ 单结果走第三方 suyanw 聚合 | ❌ r.s 接口服务端劣化返回非 JSON（实测） | 候选路径静默跳过；登记已知边界 |
| Apple/Spotify | Apple ✅ itunes API；Spotify search 恒 None（占位） | — | Spotify 链接解析可用 |

---

### 14.8. 模型路由与渠道健康（llm/）

- **注册表**：`.env BOT_MODEL_REGISTRY` 一段 JSON，45 条目，8 供应商（浅夜/恒星纪元/ToolCode/umi（含 Claude 四渠道）/DeepSeek 官方/智谱/StarAPI/hcn 兜底）。条目含 price_in/price_out/priority/think/effort/`env:`key。
- **选择顺序**：手动指定 > 时段组 order（BOT_MODEL_SCHEDULE/PRIORITY_GROUPS）> 基础 priority > 故障转移同序。`/bot model set <模型名>` 聚合同名全渠道。
- **渠道健康巡检**（channel_health.py，SQLite）：连续 2 次失败标 ⛔ 暂不可用移出故障转移队列，30 分钟重探，**永不自动删除**；全挂时放行原队列防全瘫。探针双模式：手动 `/bot model probe` 8 并发 / 后台 3 线程+0.4s 抖动（**已参数化** bot_channel_probe_threads/manual_threads/jitter_seconds）。
- **延迟择优 v2**（B组 d5a9f43）：EWMA 动态测量+慢渠道动态检测+路由排序动态切换+自适应超时与影子并发（无损切换）。双开关 `BOT_CHANNEL_HEALTH_ENABLED`+`BOT_CHANNEL_HEALTH_LATENCY_FIRST`。auto-route 全局队列保持人工策展 priority 不被延迟重排（设计裁决：否则原生 gemini 会被套壳渠道的速度反复顶掉）。
- **已知渠道事实**：浅夜渠道 gemini-3.8 自报 DeepSeek 身份（套壳实锤，介意用 aiprc-gemini/starapi-gemini，已在 .env 提前）；umi 三渠道余额 ✦0 需充值；浅夜主 key 曾 401；ds-official 曾 no_api_key；toolcode-gemini 404 下架。
- **指令族**：`/bot model list|set|add|update|priority|think|effort|price|remove|reset|usage|health|probe|routes`。health 报告含【需要你处理的】行动清单。
- **vision direct**（默认）：图片以 data URL 直传主模型；`supports_vision` 默认全渠道（text-only 标签排除）；relay（VLM 转译）兜底；`/bot model vision mode relay|direct`。
- **请求总预算 150s**；预算耗尽不丢已生成回复。记忆抽取复用主路由（独立超时/冷却）。

---

### 14.9. 记忆 / 人格 / 好感度 / 知识库（character/）

- **好感度 v3**（affinity.py + docs/affinity-design.md，用户已裁定）：初始 10（内部 0.1）；五行为影响因子+每日有效次数上限；步长幂律非线性（距极值 <10 分按 (d/0.1)^γ 缩小）；因人而异（sha1 派生 ±15% 个人系数）；惰性回归向基数收敛；四档位→语气映射；`好感度 算法` 图文说明卡。库里 WAL 模式；每日上限按本地自然日。
- **查询卡**：`好感度`（私聊双向：守岸人对你/你对他）/`群好感榜`（镜像表，正分绿低分红）；affinity_card.html 独立 Mica 模板。
- **记忆**：chat.py 后台线程抽取（`_schedule_memory_extraction`，独立超时不阻塞回复）；`memory_sanitize.py` 清洗→隔离表。
- **知识库**：`vector_knowledge.py` 向量检索+FTS；`dev.ps1 -Task kb-sync` 同步。
- **人格注入预算**：人设>知识库>短时对话>长时记忆（§14.5 Prompt 审计脱敏）。

### 14.10. 安全防线（security/）

- `content_safety.py`：硬类别（NSFW/血腥/政治/骚扰）不可放宽；软类别（强加称谓/宠物化/人格破坏/侮辱外号/excessive_intimacy/insult_nickname）管理员可放宽。
- 输出侧：`output/plain_text.py`（去引号/Markdown/LaTeX 噪声+TeX 命令转中文）+ 说人话层。
- 文件读取视为不可信数据，不执行代码。

### 14.11. 订阅（sources/subscriptions/ + capabilities/subscribe_v2.py）

- 适配器：Bilibili/Xiaohongshu/YouTube/Twitter/Telegram/Pixiv/Weibo（social_v2.py ADAPTERS）。
- **YT 订阅实测通过**（@handle 解析已修：先解析 handle→真实 UC 频道 id，失败回退不阻塞）；**推特订阅需先 `/bot cookie import x`**（当前无 X 凭证）；QQ 端实际推送外发需指定真实目标再验。
- v2 权限模型：pause/resume/remove 校验创建者/目的地归属；库有界化（outbox 14d 裁剪）。

### 14.12. 其他能力速查

| 能力 | 文件 | 要点 |
|---|---|---|
| 帮助 | echo.py | `/bot help` 双列网格手册卡；`/bot help <模块>`；分类名直查 |
| 天气 | weather.py | Open-Meteo+全球兜底；天气误捕静默 |
| 吃什么 | eat.py + sources/food_data.py | 随机/三选一/忌口；本地 60 道菜谱库；菜品图 Runtime data/food_images（本地图经 bridge 内联 data URL 后卡片可见） |
| 免费游戏 | epic.py + steamfree.py | Epic+Steam 双源 |
| 搜图 | image_search.py | SauceNAO |
| 萌娘 | moegirl.py + sources/moegirl.py | KB 优先 |
| 历史/回忆 | today_history.py | 本地 365 天库 |
| 戳一戳 | poke.py | NapCat poke/反戳（真实事件验收仍待） |
| 运维 | runtime_admin.py / debug.py / runtime_logs.py | `/bot model` 族、注册表 source=env 语义（.env 实时为准，明文永不落盘） |
| 文件 | file_exchange.py / group_files.py / download.py | 群文件/下载 |
| 表情包 | meme.py / meme_library.py | httpx Client 单例（修过连接池泄漏） |

### 14.13. 多适配器

- **Telegram**（sender/nonebot.py）：图文（本地 PNG 可作 photo）、语音 ffmpeg→OGG/OPUS（失败降级 sendAudio，缓存 %TEMP%/bot_tg_voice）、空文本+有媒体不再 SKIPPED、TELEGRAM_PROXY=http://127.0.0.1:7890。
- **Mail**：mail_adapter.py 韧性适配器+mail_bridge.py。
- **Console**：本地调试。
- **掉线通知**：runtime/disconnect_notice.py（TG/邮件/Server酱/PushPlus，默认关）。

### 14.14. 运维告警与可观测

- alerts.py：按 (stage,kind,adapter,bot,target) 300s 窗口抑制；`llm deadline_exceeded` 豁免（常态降级）。
- result_unknown 账本：发送结果未知时记账，重连对账不盲发。
- 审计：audit/logger.py 脱敏消息与上下文摘要；人格 Prompt 审计文件。
- 渲染失败日志：歌曲卡/候选卡 warning；`build_render_backend` 未知名字/不可用 warning（曾经静默降级导致卡片功能整体消失且无诊断线索——P0-1 收尾）。

### 14.15. 测试

- 入口只走 `dev.ps1 -Task test`（basetemp 源码树外）。111 文件 865+ 用例。
- 约定：测试桩的 `list_fn` 等签名要跟实现 kwarg 演进（如 limit）；共享缓存类（`_KB_PROVIDER_CACHE`）测试间要 `.clear()`；`_CANDIDATE_SESSIONS` 有 `clear_music_candidate_sessions()`。
- 各组测试文件独立命名（test_music_candidates_v2 / test_auditfix_runtime_policy / test_affinity_* …），互不碰。

### 14.16. 排障手册（症状→诊断→处置，全实战沉淀）

| 症状 | 第一步诊断 | 处置 |
|---|---|---|
| 改动"没生效" | 进程启动时间 vs 最后提交时间（Get-Process python） | 重启 bot；确认无第二实例 |
| NapCat 3001 不监听/重复登录 | `Get-Process QQ \| Select Id,StartTime` 查多代际并存 | 提权清场（先杀看门狗父进程再杀 QQ/QQEX/NapCatWinBootMain）→ login-bot.bat；bot 自动重连 |
| NapCat 二维码不刷新 | 日志「未找到对应版本的偏移数据」 | QQ 构建号超出 NapCat 支持表——上游问题；启动后 2 分钟内扫首码 |
| 点歌没有候选卡 | 1) 配置开关 2) 裸歌名精确命中（设计如此）3) 渲染失败日志 | 带限定词查询必出；查 `music candidates card render failed` 日志 |
| 点歌候选/歌曲卡全灰 | 图床 WAF/ORB | 见 §14.6.4；sinaimg 已兜，新图床照方抓药（直连+curl 极简头） |
| 发布时间差 8 小时 | 该解析器是否产 naive 串 | 契约层已按 +08 解释（media.py _CN_TZ）；新解析器直接给 epoch 或带时区 ISO 最稳 |
| xhs 图片 403 | 签名过期（分钟级）属正常 | 解析→渲染要快；**永远不要剥 URL 的 !后缀/参数** |
| B站 -352/-509 | 波动 IP 风控 | 专栏自动重试；直播已切匿名稳通道；根治=灌 bilibili 登录 cookie |
| QQ 音乐全平台搜不到 | client_search_cp 已死 | 已迁移 musicu.fcg；若再挂先 probe 接口 |
| 卡图无机器人头像 | config.bot_persona_avatar_url | render_card_png 有 config 兜底 |
| pytest 会话收尾崩溃 | 共享 %TEMP% pytest-of-* 循环 symlink | 走 dev.ps1（basetemp 已固定） |
| git push 408/断 | 代理掐大包 | 分片推送；**分支标签同名必须完整 refspec** `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` |
| fetch 报 reference broken | gitdir 外置于 ChatBot_Runtime/git，remote ref 文件损坏 | `git ls-remote` 取正确哈希直写该文件 |
| bash 里 PowerShell `$_` 报错 | Git Bash 吞 $ | 写 .ps1 文件执行；Windows 路径 cygpath -w |
| 源码树出现缓存 | 绕开了 dev.ps1 | PYTHONDONTWRITEBYTECODE=1 + basetemp 外置 |
| mypy/lint 树级残留报错 | 并行会话在途文件 | 先确认归属（git status + 文件域），别人的 WIP 不动、只保证自己文件零错 |

### 14.17. 硬约束（不可违反）

1. 人格源文件、世界观源文件只读。
2. Runtime 数据（SQLite/FAISS/记忆/Cookie/订阅/媒体缓存/日志/venv）不得删除；清理先归档验证。
3. 密钥永不入库不入聊天（§14.4.2）。
4. 推送 origin 按用户明确指示执行（本轮 A/B/C 组交接文档约定包含交付后推送）。
5. commit 禁 `git add -A`；共享 index 陷阱自查 `git diff --cached --stat`。
6. 源码树零缓存（§14.3）。
7. 工作区边界：ChatBot_Runtime / ChatBot_Archive / 上层目录默认不扫描不修改。
8. 人格：说话语气=理性、天然呆、活泼感不过量；失败话术 12 条轮换、无表演腔、不做虚假承诺。

### 14.18. 并行会话协作规范（本仓库常态）

- 常态 2~3 个 AI 会话并行（当前活跃域：解析+卡片=A、模型渠道+点歌=B、好感度+审计=C、另有视频理解会话）。
- 文件域切分（9.9 版约定）：A=sources/parsers/** + universal_card.html + 卡片管线；B=llm/* + music.py + song_candidates.html + subscribe*；C=character/* + tests。实际已多次互相"顺手"共享文件（bridge.py 被 A/C 先后提交、music.py A/B 先后提交）——**内容一致即无害，提交信息如实描述**。
- 动共享文件前 `git pull`；Edit 工具的 file-modified 检查是最后防线。
- 别人在途的 WIP（未提交的语法错误/mypy 报错）不修、不裹挟、等其自愈（chat.py 曾语法半成品约 20 分钟后自愈）。
- 树级 lint 门禁被别人 WIP 卡住时：机械性可 auto-fix 的顺手修并注明；语义性的留给归属会话。

### 14.19. 当前已知边界与非缺陷清单

- **mypy 树级残留**：视频理解会话（chat.py:248 MediaAssetRecord、__init__ queue 联合类型）与 B组在途（worker/disconnect_notice/settings）共 7~12 个报错流动中——归属会话收尾，A 组文件零错。
- **平台边界（非缺陷）**：YouTube 无频道总获赞/Tab 数未抓；小红书依赖登录态+风控（图片签名分钟级过期属正常）；B站 AI 总结仅部分视频有；AI 字幕需登录 cookie；NapCat 二维码刷新受 QQ 版本漂移影响（等上游）；浅夜渠道 gemini 套壳嫌疑（实锤，.env 已降权）；酷我搜索接口劣化（候选不可用，单结果走第三方 suyanw）；Spotify 搜索恒 None 占位；B站漫画 twirp TLS 风控不可破；Spotify/Apple 边界见 platforms_music docstring。
- **架构级尾巴（P0/P1）**：FileTransferGateway 统一（仍有 handler 直连 call_api）；订阅/文档导出出站收敛；PersonaContract/WorldEntity/Claim/EvidenceLedger/AnswerPlan 结构化知识架构；claim-based RAG；记忆写入 propose→approve；群聊公共状态；TrustLevel 反注入；ToolCatalog。
- **验收级（P2）**：真实 NapCat poke/反戳；TG 评论树与文件出站；Mail 真机；LangSearch 验收；视觉模型命令全对齐；LLMCallRecord 可观测；生成文件安全扫描；老 Office 转换链。
- **低优先改进点（audit 存量）**：kugou 明文 http 搜索端点；kuwo suyanw 第三方依赖；`点歌模式` 词与路由的边界 UX；universal_card 内少量语义状态色写死（认证金/错误红——语义色不属品牌色违规）。

### 14.20. 修复史全索引（2026-09-07 → 09-10）

| 日期 | 主题 | 要点 |
|---|---|---|
| 09-07 | alpha.1 收尾 | 统一管线/文件读写/输出整理/安全基线/Wiki 修复/poke；352 tests |
| 09-08 | 测试基建 | basetemp 修复、mail_bridge 竞态 |
| 09-08 | 12 插件硬对比 | 吸收 htmlrender 常驻浏览器/memes 守门；其余 10 项原生胜出 |
| 09-08 | 搜索验收 | Tavily/You 真实 key smoke；TinyFish 端点修正；search-smoke |
| 09-08 | 幂等/恢复 | 事件幂等表、result_unknown 账本 |
| 09-08 | 音乐多候选 | 网易云编号选歌、TTL 会话 |
| 09-08 | parser-lite A | 知乎/豆瓣/TapTap/社区/虎扑 + B站 AI 总结 + UP 获赞 + /bot cookie |
| 09-08 | 防御强化 | 软硬类别/记忆清洗/命令统一 |
| 09-08 | 并行大交付 | 全平台覆盖/搜图/小名/复读检测/说人话/天气兜底/启动闪退修 |
| 09-08 | 实卡修复一 | 点歌三件套/B站作者栏/发布时间到秒/Help 图/TG 图文 |
| 09-08 | 类型修复 | B站 fans/likes int 化 |
| 09-09 | TG 媒体链路 | 本地卡作 photo/语音 OGG/OPUS/help 空文本 |
| 09-09 | 呈现层四断点 | 时间到秒+时区/热评块/专栏标签/候选选歌启用 |
| 09-09 | 三平台解析 | 推特媒体推文/油管 innertube 三层合并/xhs 空 title 兜底 |
| 09-09 | Help 重设计 | 双列网格/分类直查/免费游戏卡/天气卡 |
| 09-09 | key 批次+渠道扩容 | 45 条目 registry/探针 key 修复/health 行动清单/model list 价格列 |
| 09-09 | 渠道+卡 UI+话术 | StarAPI 渠道/视频卡 UI/话术 v2/探针双模式 |
| 09-09 | 路由救急+视觉直传 | 9 个 bot_api_key 字段/vision direct/internal_error 可观测/预算 150s |
| 09-09 | 字幕+LLM 总结 | B站 AI 字幕/油管 captionTracks |
| 09-09 | 私聊无回复+预算 | 发送层丢消息根因/预算耗尽不丢 |
| 09-09 | 渠道化 | 健康巡检/价格选渠道 |
| 09-09 | 实卡反馈二轮 | 作者数据行归位/alpha 裁剪/Help 视口 |
| 09-10 | B组交付 | 延迟择优+巡检参数化+qian-night 重排+候选 Mica 卡+话术 v4+YT @handle 修复 |
| 09-10 | C组交付 | 好感度数值化+审计报告 36 项+浸泡测试+帮助文本 |
| 09-10 | 好感度查询卡 | bot.affinity 能力+affinity_card.html |
| 09-10 | A组解析专项(8dc7ed4) | 封面原图/时区根治/微博修复+访客兑子/专栏直播会员购补齐/竖切横图拼接 image_stitch/ORB 兜子/data URL 内联 |
| 09-10 | 嘉宾卡区+点歌批(ed0fedb) | 嘉宾独立卡区/候选卡不可达根治/QQ musicu.fcg 迁移/pic_str/{size}/渲染告警/VIP 色/双转义 |
| 09-10 | 直播风控规避+死模板清理(db84aae) | 直播主通道切换/专栏重试/Compact 死块删除 |
| 09-10 | naive 契约+点歌二轮(22d561e) | _CN_TZ/limit 透传/酷狗详情富化/render_backend 告警 |
| 09-10 | xhs playwright 兜底+撤剥!回归+时长秒数化(f96d1a1) | 见 §14.5.4/§14.5.2；共享 index 裹挟存证 |
| 09-10 | B组 EWMA v2(d5a9f43) | 渠道延迟择优算法 v2 |

### 14.21. 完成判定（说"完成"前逐条核对）

AC 达成 ∧ 实测通过（真跑，禁编造输出）∧ 无回归（全量 pytest）∧ 影响已控制（只动本域文件）∧ 交付记录同步（handoff/提交信息）。

### 14.22. 建议下一步（按价值排序）

1. `/bot cookie import bilibili` + `x`（登录态解锁 AI 字幕/订阅推特，缩小 -352 面积）。
2. mypy 树级残留清零（等视频会话收尾后统一清）。
3. xhs/微博图床 ORB 名单按需扩展（新图床灰图→照 §14.6.4 方针加后缀+实测取回头形态）。
4. FileTransferGateway 统一出站（架构尾巴里价值最高的一个）。
5. 酷我搜索找新的匿名通道（当前候选不可用，静默跳过不影响主链路）。
