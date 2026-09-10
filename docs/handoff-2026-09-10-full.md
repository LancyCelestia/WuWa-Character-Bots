# 守岸人 Bot 全量交接手册（2026-09-10 定稿版）

> 本文件是**独立的全新交接文档**，不基于旧文档增量修改；旧活文档 `docs/handoff-final-2026-09-07.md` 保留原样作并行参照，两者冲突时**以本文件为准**（本文件成文更晚、覆盖 09-10 全天多会话交付）。
> 成文时间：2026-09-10 05:30（+0800）· 分支 `v0.0.1-alpha.2` · 当时 HEAD `3819299` · 本地与 origin 同齐。
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

---

*本文档由 09-10 B组会话（渠道运维/UI/点歌/审计修复/算法 v2/历史修复/平台实测/管线检视）主笔，整合 A组（解析专项）、C组（好感度与质量）、视频会话、基建会话同日交付。旧活文档继续按其自身规则维护，两者不一致时以本文+git 历史为准。*
