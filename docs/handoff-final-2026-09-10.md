# 守岸人 Bot 交接手册（活文档 · 2026-09-10 版）

> 整理日期：2026-09-10 · 分支 `v0.0.1-alpha.2` · HEAD `3819299` · 工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
> 本文件**取代** `docs/handoff-final-2026-09-07.md` 成为唯一活文档；旧文件按原样保留作历史存证，**不再更新**。
> ⚠️ **状态更新（2026-09-11）**：本文件已被 `handoff-2026-09-10-full.md`（更全）超越并进一步被 `handoff-MASTER-2026-09-11.md`（入口+跨文档总账）索引，不再是权威——接手请从 MASTER 读起。
> 写作规则：每完成一项交付，同步更新本文件对应小节；不再新开「增补章节」。
> 本版核心增量：2026-09-09 深夜 → 09-10 凌晨的**全库只读审计**与**三类别 90 项修复轮**（六域并行子代理执行 + 主会话门禁裁决），以及并行会话（视频理解 / 好感度数值化 / A 组解析专项）的同窗口协同记录。

---

## 1. 系统现状与门禁基线

NoneBot2 + OneBot V11（NapCat）QQ 聊天机器人，附带 Telegram / Mail / Console 适配器。已上线：统一消息管线、37+ 平台链接解析（Mica 卡图渲染）、多供应商音乐点歌（卡图+语音+候选选择卡）、四家搜索 API、45 条目模型路由与渠道健康巡检（EWMA 延迟择优 v2）、记忆/人格/知识库/好感度数值化、安全防线、订阅推送（V2 调度+outbox）、视频理解（vision direct + ASR 字幕 + 转写摘要）、运维告警。当前是功能完整、持续迭代的 alpha。

**当前验证基线（2026-09-10 实测，全部真实跑得）：**

| 门禁 | 结果 |
|---|---|
| `dev.ps1 -Task lint`（ruff） | All checks passed |
| `dev.ps1 -Task typecheck`（mypy） | Success: no issues found in 205 source files |
| `dev.ps1 -Task test`（pytest） | **865 passed**（32.8s，Python 3.12.10 / pytest 9.1.1，runtime venv） |

每轮交付后必须保持三门禁全绿。测试基线从交接旧版的 600 → 865，增量来源：并行会话视频理解/媒体注册/好感度数值化/text_at_mention 等新测试（约 80+ 用例）+ 本轮审计修复回归 96 用例（6 个 `test_auditfix_*.py` 文件）。

**工作树状态（写文档时点）**：约 99 个文件未提交，构成为 ① 本轮 90 项审计修复（六域，含 4 处文档修正）；② 并行会话在途的视频理解管线（`runtime/video_pipeline.py` 等）与好感度数值化收尾。**尚未 commit，任何一方提交前先与本文件 §14 的归属清单核对，禁用 `git add -A`。**

---

## 2. 硬约束（全部沿用，持续有效）

- 人格源文件、世界观源文件只读，AI 不得改写。
- Runtime 数据（SQLite/FAISS/向量库/记忆/Cookie/订阅/媒体缓存/日志/venv）不得删除；旧数据先归档验证再清理。
- 密钥不入库不入聊天：真实 key 存 `.env`（在 `.gitignore`），链路字段用 `env:变量名` 间接引用。
- 推送 origin 仅按用户明确指示执行；commit 禁用 `git add -A`（多会话并行，会裹挟他人半成品——实际踩过多次坑）。
- 源码树不产生缓存（`__pycache__`/.pytest_cache/.ruff_cache 等）：测试走 `dev.ps1`；绕开时必须 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp` 指到源码树外（各修复代理本轮已按此执行并自清缓存）。
- 工作区边界：`ChatBot_Runtime`、`ChatBot_Archive`、上层目录默认不扫描不修改；AI 唯一默认工作区是本仓库。
- **多会话并行纪律（本轮实战验证的规程）**：开工前 `git pull`；编辑共享文件一律用锚定式 Edit（先 Read 最新内容、按符号定位），**禁止整文件覆写**；每个文件域同一时刻只由一个会话负责（§14 归属表）；共享树不做回滚式 RED，回归用例允许「构造性 RED + 事后锁定」并如实披露。

---

## 3. 架构与消息主链路

```text
NapCat(OneBot V11 WS 服务端 127.0.0.1:3001, token ShoreKeeper)
  -> NoneBot OneBot Adapter（bot 是 forward-WS 客户端，.env.prod ONEBOT_WS_URLS；NapCat 起来后自动重连）
  -> _incoming_from_nonebot_event() -> IngressGateway -> IncomingMessage
     （QQ 引用回复 reply/quote 段已接入；小名软点名只记 name_mention_only，不再置 mentions_bot）
  -> 路由/权限(gate)/限流/安静时间/群策略/幂等表(可选,默认关)
  -> RuntimePipeline -> CapabilityResult
     （bot.eat 已加入 OFFLOADED_CAPABILITY_IDS；被动好感度感知整体 asyncio.to_thread 下放）
  -> Review/文本整理/媒体投影 -> RenderedOutput -> SendRequest
  -> SendQueue(SQLite, WAL, 60s 内联宽限期) -> UnifiedDeliveryGateway
     （或 handler 显式 _deliver_transport_send_request —— 搜图/复读已补齐该投递）
  -> sender.onebot（QQ 富消息, 分段副作用进度跟踪）/ sender.nonebot（TG 图文+语音+文件）
```

关键文件：`bot.py`（启动+崩溃守卫+异常处理器已改挂在 on_startup 的 running loop 上）；`plugins/bot_unified_runtime/__init__.py`（handler 装配、能力分发，约 5300 行）；`runtime/pipeline.py`、`runtime/ingress.py`；`sender/onebot.py`、`sender/nonebot.py`、`sender/gateway.py`、`sender/queue.py`、`sender/worker.py`。

TG 发送要点（`sender/nonebot.py`）：图片支持 http 直链和本地文件；语音走 `_prepare_telegram_voice`（sendVoice 仅认 OGG/OPUS，ffmpeg 转码先写 `.part` 再 `os.replace`，`.src` 发送后清理，`.ogg` 缓存保留最新 64 个，失败降级 sendAudio）；语音源下载改流式+45MB 上限+挂 `bot_download_proxy`；图文+语音按部件记录进度，重试不重发已送达图片；附件缺失/超限为 FAILED_FINAL 不再无谓重试。

**发送队列协议（本轮确立，后来者必读）**：`SendQueue` Protocol 只含 `submit/find_request/safe_summary`（`sent_requests` 属性已从协议移除，需要列表的消费方用 `getattr(queue, "sent_requests", [])`，SQLite 实现走 DB 查询）；submit 写入 `next_retry_at = now+60s` 宽限期——宽限期内 worker 不得认领、由 handler 内联投递负责，宽限期后仍在 QUEUED 的行（如进程重启遗留）由 worker 接管；`_prune` 只淘汰终态行（SENT/FAILED_FINAL/SKIPPED），非终态永不淘汰；租约过期重认领递增 retry_count，达上限置 FAILED_FINAL 并写 `send_failed_final` 审计。

---

## 4. 启动、验证与门禁

```powershell
# 门禁（每轮交付前全绿）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"        # 865 passed
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"       # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"  # mypy 205 files

# 启动前体检
dev.ps1 -Task doctor / backend-base-smoke / backend-smoke / search-smoke / runtime-layout
```

- 启动：`ChatBot_Runtime\venv\Scripts\python.exe bot.py`（确认只有一个实例；**先查进程启动时间再查代码**——`Get-Process python | Select Id,StartTime`）。
- 日志：`dev.ps1` 启动重定向到 `ChatBot_Runtime/logs/nonebot.out.log`；手动控制台启动不落盘。
- NapCat 启动：`C:\Software\NapCat\login-bot.bat`（快速登录守岸人 3958874605，UAC 确认）；验证 `netstat -ano | findstr 3001` 出 LISTENING + bot 进程 ESTABLISHED。
- 轮询失败日志过滤（bot.py）：TG 轮询/OneBot 重连的已知可恢复错误按「首条放行 + 每 300s 最多一条」冷却限速，其余丢弃并计数——运维仍能看见错误在持续发生。

---

## 5. 数据、密钥与配置

- 运行数据根：`ChatBot_Runtime/`（data/cache/logs/venv/git 元数据）。`data/` 前缀路径自动重映射 Runtime 根——本轮已对齐 `./data/` 前缀与大小写变体，`scripts/runtime_paths.py` 与 `config.resolve` 两侧语义一致；手写 dotenv 解析现在能剥行内注释（引号感知）。
- Cookie：`ChatBot_Runtime/data/platform_cookies.txt`（Netscape 格式，17 平台域名映射 `sources/parsers/cookies.py`，支持 `#HttpOnly_` 前缀行）；管理员指令 `/bot cookie import <平台> <Cookie头>` 热写入（解析注册表按 cookies 文件 mtime 缓存，改动后自动重建）。
- 关键 `.env` 项：`BOT_CHAT_*`（provider/model/max_tokens 65538）、`BOT_SEARCH_TAVILY/YOU_API_KEY`、`TELEGRAM_BOTS`、`TELEGRAM_PROXY=http://127.0.0.1:7890`、`BOT_DOWNLOAD_PROXY`、`BOT_MUSIC_CANDIDATES_ENABLED=true`、`BOT_EVENT_IDEMPOTENCY_ENABLED`（默认 false）、`BOT_DISCONNECT_NOTICE_*`、`BOT_CHANNEL_HEALTH_ENABLED`（**现由 Config 统一读取生效**）、`BOT_CHANNEL_PROBE_THREADS / BOT_CHANNEL_PROBE_MANUAL_THREADS / BOT_CHANNEL_PROBE_JITTER_SECONDS`（探针线程/抖动参数化）、`BOT_DOWNLOAD_PROXY`（steam/epic/facebook 兜底代理现在读它，不再硬编码 7890）。
- **注意**：路由侧已不再读取 `BOT_CHANNEL_HEALTH_ENABLED` / `BOT_CHANNEL_HEALTH_DB` 环境变量（统一走 Config 字段与 `resolve_default_db_path()`）；健康库位置唯一由 runtime_paths 决定。
- 新增可选配置：`bot_subscription_outbox_sending_stale_seconds`（getattr 读取，默认 300s——outbox `sending` 僵尸行回收阈值）。
- 设置文件损坏处置：`runtime/settings.py` 原子写；损坏文件改名 `<原文件>.corrupt-<时间戳>` 保留——若管理员反馈「配置丢了」，先找 `.corrupt-*` 文件。
- Prompt 审计：`bot_prompt_audit_*` 组当前**仅** `runtime/prompt_preview.py`（CLI）使用，主链路不读取（已在 config.py 注释声明）；默认记录脱敏消息与上下文摘要；人格 Prompt 预算优先级 人设>知识库>短时对话>长时记忆。

---

## 6. 子系统速查

### 6.1 命令与路由
统一格式 `/bot <模块词> <功能词> [参数]`；命令别名表 `runtime/aliases.py`；命令前缀判定已加词边界（`/botxxx` 不再触发）。`/bot help` 出 Mica 手册卡；`/bot help <模块>` 说明书页；`_PUBLIC_HELP_TOPICS` 已含吃什么/偷表情。`/bot reply <未知参数>` 现在回用法提示（不再静默当 auto）；`/bot 群文件` 加管理员校验。

### 6.2 链接解析器
入口 `sources/parsers/__init__.py`（平台路由表+Cookie 绑定+代理绑定）；实现按平台拆 `platforms_*.py`，覆盖 37+ 条目。公共设施：`wbi.py`（B 站签名键 30 分钟缓存+single-flight，bilibili 模块已改为委托缓存的薄壳）、`http_util.py`（**默认 8MB 响应上限**、gzip 防炸弹、短链不读 body、POST 保留状态码/Retry-After）、`cookies.py`。已知边界与近期改动：小红书 playwright 兜底+撤回剥 `!` 后缀回归（f96d1a1）；xsec_token 剥除支持首/中/尾参数形态；油管/汽水音乐 JS unicode 转义只点转义 `\uXXXX`（中文不再乱码）；`youtu.be/<id>?list=` 走单视频；Apple Music cn→us 逐国容错；油管解析 60s/微博状态卡 45s 整体预算。

### 6.3 卡片渲染（Mica 规范）
管线：`capabilities/content_parser.py:render_card_png`（合成 ParsedContent → payload → HTML → playwright 截图，线程内常驻浏览器）→ `output/card_render/`（bridge 投影 + `templates/universal_card.html` + `song_candidates.html`（点歌候选选择卡）+ `affinity_card.html`（好感度卡））。规范：底色由 `PLATFORM_COLORS` 经 `--pc` 变量 color-mix 派生，禁写死品牌色；单柔光阴影；`body` 透明背景。本轮加固：bridge 侧对 `repost.text/compact_translation/compact_romanization` 预 html.escape；`platform_color` 做 `#hex` 白名单校验（非法回退中性灰 #607080）；banner/cover_url 进 CSS url() 前经 quote。Playwright 后端：`set_default_timeout(8000)`、页面级失败只关 page、浏览器级错误（Target closed 等）才重启、空闲 10 分钟回收（acquire 时判定）。

### 6.4 音乐点歌
5 供应商（`platforms_music.py`）；模式 `card+voice+link+file` 可组合（`ALL_PARTS` 已含 file，「点歌模式 全部」不再丢音频）；多候选编号选歌（会话键含 sender_id，防代选/覆盖；候选 pop 原子取用防并发双发；TTL 300s/256 条上限）；QQ 端 Mica 歌曲卡图+候选图片选择卡（song_candidates.html）+语音+♪文本；TG 端封面/卡图+caption+语音。

### 6.5 搜索 API
Tavily 主、You.com 备、LangSearch 备、TinyFish 搜索+正文抓取；不接 Bing。链式回退+瞬时重试；正文反注入剥离补齐未闭合 `<script>`/`<!--` 残段；MCP web_search 工具（`search_async`）已装配 DuckDuckGo→Bing 兜底链（此前永远空结果）。Tavily/You/TinyFish 已真实 key 验收；LangSearch 未验。

### 6.6 模型路由（渠道化）
**45 个注册条目**（`.env BOT_MODEL_REGISTRY`），8 家供应商：浅夜（Gemini 置顶）/恒星纪元/ToolCode/umi（含 Claude 四渠道、GLM/Kimi/MiniMax 新组）/DeepSeek 官方/智谱/StarAPI/hcn 兜底。
- 选择：手动指定 > 时段组 order > 基础 priority（1..N 唯一槽位）> 故障转移同序；**`/bot model set <实际模型名>` 三级解析已修复可达**：精确 id 命中→单渠道路由；同名多渠道→按价格升序聚合（channels_for_model）；完全未知→fallback spec 合成。
- **渠道健康巡检（`llm/channel_health.py`）**：开关统一走 Config（`bot_channel_health_enabled`，两侧同源——此前路由侧读 os.environ 恒关、踢队/重探/延迟择优整体空转的缺陷已修）。每小时全渠道最小调用探测（后台线程+抖动可配 `bot_channel_probe_*`）；连续 2 次失败移出故障转移队列，30 分钟重探恢复回队，永不自动删除；全部不可用时放行原队列。**延迟择优 v2（EWMA）已落地（d5a9f43）**：动态测量+慢渠道检测+路由排序动态切换+自适应超时+影子并发无损切换。手动 `/bot model probe` 与后台巡检共享在飞互斥（重复触发直接回「正在进行中」）。`/bot model health` 运维报告、【需要你处理的】行动清单；`/bot model routes <模型名>` 单模型全渠道。
- 运行时注册表持久化（runtime_admin）：env 派生条目带 `source:"env"`+`override_fields` 标记；读取时 .env 实时内容为准、仅 priority/显式编辑字段取运行时副本；.env 删除条目即失效；remove 对 env 来源条目维持拒绝话术。**旧格式全量快照（无 source 标记的存量数据）仍整体遮蔽 .env 同名条目——对条目重新 `/bot model update` 一次即可迁移**。
- 失败话术：私聊 LLM 失败回 12 条守岸人话术，纯游标顺序轮换（已去随机，会话内连发不重复）；群聊静默。LLM 失败审计 tag 读 `exc.attempts`/`reply.attempts`（并发不串号）。工具循环中间轮 token 用量已累计入账。时段表清空会正确 reset BOT_CHAT_MODEL 覆盖。
- 请求总预算 150s（`bot_request_budget_seconds`）；预算耗尽不丢已生成回复（发送给足传输超时；`apply_request_deadline` 从不抛异常，发送层 `except DeadlineExceeded` 为死分支属既定语义）。记忆抽取复用主路由。

### 6.7 记忆/人格/知识库/好感度
- `character/` 已扩展至约 20 个模块（affinity/documents/emotion/glossary/history/kb_wiki/media_registry/memory/memory_extract/persona_set/providers/relationship/shared_export/shared_group/source_summary/temporal/trend/vector_knowledge 等）。
- **好感度数值化（C 组，并行会话进行中）**：设计文档 `docs/affinity-design.md`；实现含每日上限（`_DAILY_EFFECTIVE_CAPS`）、闲置 ≥7 天每日向基数 0.5 回归 0.01、行为因子表、档位→态度映射（tier_for_affinity/attitude_for_affinity）、画像自学（observe 回写 profile_notes、snapshot 返回画像）、好感度卡 `affinity_card.html`、`/bot 昵称 set` 管理员指令；回归 `tests/test_affinity_numerical.py` 等 28 用例全绿。注意：affinity.py 由并行会话持续重写，接手前先读最新版。
- 向量知识库（`vector_knowledge.py`）：查询向量已归一化（0.30 低置信阈值恢复有效）；retrieve 锁分段（嵌入网络调用在锁外，锁内仅索引一致读）；运行期人格知识库 `fts_auto_rebuild=False`（重建交给 knowledge-sync force 路径）；providers 检索故障时不再注入静态文件块（打降级日志，正常无命中仍兜底）。
- 人格 Prompt 注入预算见 §5；安全清洗（memory_sanitize）覆盖面与归一化见 §6.8。

### 6.8 安全防线
`security/content_safety.py`：硬类别（NSFW/血腥/政治/骚扰）+软类别（强加称谓/宠物化/人格破坏/侮辱外号）；管理员放宽软类别不放宽硬类别（不变量成立）。匹配入口统一 `normalize_for_matching`（NFKC+剥零宽+空白折叠）——全角/零宽变体不再绕过。输出侧 `output/plain_text.py`（去引号/Markdown/LaTeX 噪声；`$...$` 公式判定已收紧、行级 TeX 只转换命令 token）+ 说人话层。记忆清洗含同样归一化。文件读取视为不可信数据，不执行代码；`file_exchange.run_code_debug` docstring 已如实声明「非沙箱、bot 同等 OS 权限、仅限管理员」。

### 6.9 订阅（V2）
`sources/subscriptions/`（social_v2/music_v2/bilibili_adapter 等）+ `capabilities/subscribe_v2.py` + `sources/subscription_scheduler.py` + `subscription_store_v2.py`。本轮加固：per-target 异常收窄 Exception（单目标坏数据不再中止整轮）+租约兜底释放不回写过期退避；outbox `sending` 行 300s 自动回收+投递 try/finally（崩溃不再永久丢推送）；游标数值 `<=` 比较（删帖不再整页重发；数值 id 折衷：后加入的旧内容会被跳过，BV 号路径不受影响）；**remove/pause 权限：群聊=管理员∧本会话存在该订阅 destination，私聊=本会话存在 destination**；Twitter 凭据发现命中即 break；订阅推送换行符修复；add 多余参数显式报「暂不支持」。推送走视觉渲染管线。

### 6.10 多适配器
Telegram（轮询+韧性重连+堆栈降噪冷却放行）、Mail（`mail_adapter.py`+`mail_bridge.py`）、Console。掉线通知 `runtime/disconnect_notice.py`（TG/邮件/Server酱/PushPlus，推送已 to_thread 化不再阻塞事件循环，默认关）。掉线时 async 上下文内不再有同步 HTTP。

### 6.11 运维告警
`runtime/alerts.py`：按 (stage,kind,adapter,bot,target) 300s 窗口抑制；`llm deadline_exceeded` 不通知；result-unknown 记账 `runtime/result_unknown.py`（重连对账不盲发；对账钩子注册已独立于运行时事件日志初始化）。审计文件轮转加锁；事件日志轮转 rename 失败后回填真实大小（不再无界增长）。后台任务统一 `_spawn_background_task` 持引用（防 GC 丢告警）。

### 6.12 视觉/字幕/视频理解
**图片直传（vision direct，默认）**：聊天图片以 data URL 进主模型（本地图 >8MB 跳过转码走降级）；`supports_vision` 默认全渠道支持（text-only 标签排除）；relay 兜底可切。**字幕总结**：B 站 AI 字幕（ai-zh 优先，去重后空格连接）+油管 captionTracks（ASR 滚动重叠去重）→【AI字幕总结】。**视频理解（并行会话新子系统）**：`sources/video_understanding.py` + `runtime/video_pipeline.py` + `sources/transcribe.py`（流式 20MB 上限）+ `character/media_registry.py`（媒体档案注册/简报回写，chat.py 侧 `MediaAssetRecord.model_validate` 构造）；设计文档 `docs/superpowers/specs/2026-09-09-video-understanding-design.md`；回归 test_video_* / test_media_registry / test_asr_transcribe 全绿。

### 6.13 吃什么（bot.eat）
随机推荐/三选一/忌口约束（Mica 卡图+文本）；`菜谱/怎么做` 查做法（本地 60 道库，未收录走 LLM）；触发收窄：`is_eat_command` 的 extra 必须命中修饰/约束词表（“吃了吗”等日常寒聊落回闲聊）；`bot.eat` 已 offload 到线程池；菜品图 `Runtime data/food_images/<菜名>.jpg`。**已知 flaky**：`tests/test_eat_capability.py::test_spicy_filter` 约 2.3% 概率随机失败（非辣菜「鱼香肉丝」简介含“酸辣”被 random.choice 命中；预存问题与本轮无关，重跑即过，待修：断言前固定 seed 或剔除歧义菜）。

### 6.14 天气
NMC+Open-Meteo 双源；触发收窄：查询词 ≤20 字+口语感叹词过滤（“太/那/哈”开头的真实城市不受影响，测试锁定），群聊查不到城市时 `SILENT_AUDIT` 静默、私聊明确报错；缓存过期返回旧值+后台线程刷新（首条消息不再被同步 8s 拉取阻塞）。

---

## 7. 2026-09-10 全库审计与修复轮（本轮核心交付，事无巨细）

### 7.1 方法
先做**只读全库审计**：7 个并行只读子代理分域通读（运行时核心、`__init__.py` 全文、发送/渲染、解析器、LLM 路由、人格/安全、能力层+测试+文档），主会话对最高严重度声明逐条实码复核（其中 2 条子代理声明被复核为已在工作树修复而剔除）。随后**修复轮**：6 个实施子代理按互不相交文件域并行落地，主会话统一跑三门禁并修 fallout。回滚基线：`%TEMP%/auditfix-baseline-20260910-023342/`（tracked.patch + status.txt + untracked.txt）。

### 7.2 A 组修复（发送/队列/输出渲染域，16/16）
| # | 位置 | 修复 |
|---|---|---|
| A1 | sender/queue.py `submit` | next_retry_at 写 now+60s 宽限期（`_INLINE_DELIVERY_GRACE_SECONDS`），消除 worker 与内联投递竞态双发 |
| A2 | queue.py + receipts.py | `_schema_ready` 一次性建表 + 首连 `PRAGMA journal_mode=WAL`（失败降级）+ `connect(timeout=5.0)` |
| A3 | queue.py `submit` | 去重改 `INSERT ... ON CONFLICT(dedupe_key) DO NOTHING`，并发冲突→skipped 回执，不再抛 IntegrityError |
| A4 | queue.py `_prune` | 只淘汰终态（SENT/FAILED_FINAL/SKIPPED），非终态永不淘汰（防静默删未发消息） |
| A5 | queue.py `claim_due` | 租约过期重认领递增 retry_count，达上限 `_finalize_expired_lease` 置 FAILED_FINAL+审计 |
| A6 | queue.py | 删除 SQLite 队列无上界 `sent_requests` 内存列表（连带 SendQueue Protocol 变更，见 §9） |
| A7 | onebot.py | `_SendSideEffects` 副作用计数：chunk/文件/图成功即 +1；仅零副作用才重试，否则 result_unknown/FAILED_FINAL |
| A8 | onebot.py | `_TimeoutBudget` 按段/文件数切分超时，每段独立 wait_for，总受原 deadline 约束 |
| A9 | nonebot.py | 语音源 client.stream 流式+45MB 上限；`_resolve_download_proxy` 挂下载代理 |
| A10 | nonebot.py | ffmpeg 输出 `.part`+`os.replace`；`.src` 发送后删；`.ogg` 缓存 mtime 清扫保留 64 个；顺带修缓存目录未建导致本地转码必败 |
| A11 | nonebot.py | `delivered_parts` 部件进度：重试不重发已送达图片；附件缺失/超限 `_FinalSendError`→FAILED_FINAL |
| A12 | worker.py | `_background_tasks` 集合+done callback，create_task 不再被 GC |
| A13 | render_backends.py | `set_default_timeout(8000)`；页面级失败只关 page，浏览器级错误（6 特征串）才重启；空闲 10 分钟回收浏览器 |
| A14 | renderer.py | forward 溢出合并后按 node_chars 二次切分（硬边界优先于节点数） |
| A15 | plain_text.py | `$...$` 两侧禁邻字母/数字；行级 TeX 只转换命令 token（`_convert_line_tex_tokens`） |
| A16 | bridge.py | repost.text/compact_translation/compact_romanization 预转义；platform_color `#hex` 白名单+URL quote（模板零改动方案） |

### 7.3 B 组修复（运行时/配置/策略域，14/14）
| # | 位置 | 修复 |
|---|---|---|
| B1 | runtime/disconnect_notice.py | Server酱/PushPlus 推送 asyncio.to_thread（原同步 httpx 冻结循环最长16s） |
| B2 | bot.py | 异常处理器移至 `@driver.on_startup` 的 `get_running_loop()`（原 import 期装在死循环上，3.14 会崩） |
| B3 | bot.py | 轮询失败日志按注释实现冷却放行（首条+每300s一条），激活死代码计数器 |
| B4 | policy/rate_limit.py SQLite | `_schema_ready_paths` 一次性建表+threading.Lock+timeout=5.0+每300s全表过期清理 |
| B5 | policy/rate_limit.py InMemory | 每600s清扫空/过期桶（键集合不再无界） |
| B6 | policy/gate.py | 新增 `is_command_text`：`/bot` 前缀须后随空白/结尾（`/botxxx` 不再触发命令态） |
| B7 | policy/reply_budget.py | `_cap_max_messages`：cap≤0=该帽不生效（修 min(4,0)=0 变不限的反向放大） |
| B8 | runtime/settings.py | 原子写（temp+os.replace）；损坏文件 `.corrupt-<ts>` 保留+warning；实例缓存键统一清洗后名；interactions 重载按键 max 合并 |
| B9 | config.py | 四个 JSON 解析器失败 log ERROR（键名+摘要，不打内容）；transport_timeout 注释对齐实际行为；bot_prompt_audit_* 注释声明仅 CLI 使用 |
| B10 | audit/logger.py 等 4 文件 | sqlite 连接统一 `with closing(...)`（audit/logger、event_idempotency、result_unknown、intent_telemetry） |
| B11 | audit/file_logger.py | append+rotate 加 threading.Lock；rename 失败降级续写不丢行 |
| B12 | sources/runtime_event_log.py | 轮转 rename 失败重开后 `getsize` 回填计数（不再无界增长） |
| B13 | runtime/model_schedule.py | 抽出 `run_model_schedule_job`：空表时若 last_applied 非空仍 reset BOT_CHAT_MODEL 覆盖 |
| B14 | scripts/runtime_paths.py + config.py | dotenv 行内注释引号感知截断；`./data/` 前缀与大小写不敏感重映射，两侧对齐 |

### 7.4 C 组修复（__init__.py 主装配 + 人格/知识/安全域，23/23）
| # | 位置 | 修复 |
|---|---|---|
| C1[P0] | `__init__.py` | **搜图与群复读投递缺口**：`_handle_image_search` 与 parrot 分支补 `_find_sent_request`+`_deliver_transport_send_request`+诊断+通知（此前只入队假 sent 回执、默认配置下消息永不发出） |
| C2 | `__init__.py` | weather/eat handler 工厂互换纠正（问天气得菜谱的复制粘贴错位） |
| C3 | `__init__.py` | `bot.eat` 加入 OFFLOADED_CAPABILITY_IDS（自然语言路径不再同步跑 Playwright+LLM 冻结循环） |
| C4 | `__init__.py` | 凭据巡检 `check_credentials_and_report` to_thread 下放 |
| C5 | `__init__.py` | `run_code_debug` 与大文件 write_bytes to_thread 下放 |
| C6 | `__init__.py` | 被动好感度感知块（observe/learn/小名自学）包 `_passive_affinity_perception()` 后 to_thread |
| C7 | `__init__.py` | `get_record` 预转码加 `asyncio.wait_for(20s)`，超时保留原段 |
| C8 | `__init__.py` | 订阅推送两处 f-string 字面 `\n` 改真实换行 |
| C9 | `__init__.py` | 三处 `sub_ctx["store"]` 改 `.get` 判空→「订阅运行时未启动」文本结果（不再 KeyError 静默） |
| C10 | `__init__.py` | (a) 小名学习正则加 `(?<!别)(?<!不要)(?<!不许)(?<!不准)` 否定排除；(b) 小名命中只记 `name_mention_only`，不再置 `mentions_bot`（white1/未名单群不再因常用词小名触发完整 LLM；white2 判定不变，@硬点名/私聊不变） |
| C11 | `__init__.py` | 历史上的今天推送改 `_select_credential_bot(_all_online_bots())` 只取 onebot 账号 |
| C12 | `__init__.py` | transport 分支处理完显式 return；管道回执诊断/通知仅在无 sent_request 时执行（消双诊断） |
| C13 | `__init__.py` | 管理员文件通知 `Path(file_name).name`+空值回退（防路径逃逸） |
| C14 | `__init__.py` | 头像 URL 缓存（按 self_id，TTL 600s）；解析注册表按 cookies mtime 单槽缓存（保留热更新） |
| C15 | `__init__.py` | `/bot reply` 未知参数回用法提示；`/bot 群文件` 加 `_is_admin_origin` |
| C16 | `__init__.py` | `_refresh_affinity_nicknames` 连接 finally 关闭 |
| C17 | vector_knowledge.py | (a) 查询向量归一化（阈值恢复有效）；(b) retrieve 锁分段（嵌入在锁外）；(c) 人格库 `fts_auto_rebuild=False` 对齐 kb_wiki |
| C18 | providers.py | `_shared_affinity_store()` 共享工厂单例，消除双实例双锁（异常回退本地保可用） |
| C19 | providers.py | 检索故障→空块+降级日志，不再注入无关静态文件块（confidence 0.0）；正常无命中保留兜底 |
| C20 | content_safety.py + memory_sanitize.py | `normalize_for_matching`（NFKC+剥 U+200B/C/D/FEFF+空白折叠）统一入口；归一化文本不写回存储 |
| C21 | history.py | `_ensure_schema_once` 加 threading.Lock 双检 |
| C22 | shared_group.py | LLM 摘要缓存 OrderedDict LRU-32 |
| C23 | temporal.py | 天气过期返回旧值+后台守护线程刷新（`_refresh_lock` 去重）；无旧值才同步拉 |

### 7.5 D 组修复（LLM 路由/渠道健康域）
| # | 位置 | 修复 |
|---|---|---|
| D1 | channel_health.py + model_router.py | 健康开关唯一解析源 `channel_health_enabled(config)`（Config→env→默认），路由侧四处 os.environ 直读删除，config 显式传入；**此前 .env-only 下踢队/重探/延迟择优整体空转、巡检白烧钱、health 显示假状态的系统性脱节已修** |
| D2 | model_router.py `route_ids` | 三级解析：精确 id 命中→单渠道；同名聚合（价格升序/延迟择优）→channels_for_model；完全未知→fallback spec。`/bot model set <模型名>` 聚合分支真实可达（此前 `_spec_for` 恒合成 spec 使其不可达） |
| D3 | runtime_admin.py | （并行会话先前已落地 `_env_derived_persist_entry`/`override_fields` 方案）本轮补防回归测试：D3 合并语义×2 + 旧格式向后兼容读取 |
| D4 | channel_health.py | 健康库路径统一 `resolve_default_db_path()`；单例对不一致 db_path 打 warning；model_router 删 env 相对路径默认 |
| D5 | channel_health.py + runtime_admin.py | 模块级 `_PROBE_ALL_LOCK`+`probe_in_flight()`：手动/后台共享互斥，在飞回 busy 摘要 |
| D6 | providers.py + model_router.py + chat.py | `LLMReply.attempts` 字段+`LLMProviderError.attempts`；generate 局部 attempts 整体发布；消费点改读新载体（并发不串号；`last_attempts` 保留为诊断快照，约 15 处既有测试依赖） |
| D7 | runtime_admin.py | `_probe_specs`：手动 probe 集合=.env ∪ 运行时注册表合并视图。**残留**：后台每小时巡检取数点在 `__init__.py`（当时禁改）仍只覆盖 base 注册表 → 列入 §14 待办 |
| D8 | channel_health.py | probe_entry 删 `_config_ref` 死表达式与 frozen 属性注入，改 `api_key_override` 显式参数；`except: pass` 改 debug 日志（顺手修 lint S110） |
| D9 | chat.py | 失败话术去 random，纯 `(offset) % n` 顺序轮换（无会话才随机） |
| D10 | chat.py | 工具循环逐轮累计 raw_usage 随最终 reply 产出（中间轮计费不再丢） |
| D11 | runtime_admin.py | ISC003 冗余 `+` 拼接修掉（审计原报 ISC004@246 已不存在，实际在 ：1031） |

### 7.6 E1 组修复（解析器与 sources 域，18/18）
| # | 位置 | 修复 |
|---|---|---|
| E1-1 | parsers/cookies.py | `min(..., default=0)`（全 session cookie 不再崩）；`#HttpOnly_` 前缀剥除解析 |
| E1-2 | platforms_generic.py | xhs 剥 xsec_token：`(^|&)xsec_token=[^&]*&?`+strip("&")，基于归一化后 URL 重新 urlsplit（首/中/尾形态全覆盖，旧 `_replace` 复活旧路径问题一并修） |
| E1-3 | platforms_generic.py + media_share.py | `_unescape_js_unicode` 点转义 `\uXXXX`（含代理对），中文不再乱码；qsmusic title/artist、`_youtube_channel_about` 同修 |
| E1-4 | platforms_bilibili.py | `build_wbi_signed_url` 改薄壳委托 `wbi._cached_mixin_key`（保留 monkeypatch 缝，nav 不再每视频多打 2-3 次） |
| E1-5 | parsers/http_util.py | `DEFAULT_MAX_BYTES=8MB` 默认生效（0/负=不限，参数可覆盖；gzip 限幅防炸弹）；`resolve_short_link` 改 RedirectHandler 记录落点不读 body；POST 单独 except HTTPError 提取状态码/Retry-After |
| E1-6 | platforms_music.py | Apple Music cn→us 每国 try/except continue |
| E1-7 | platforms_taptap.py | 删 URL 拼 cookie，改 `http_get_json(cookie=...)` 请求头 |
| E1-8 | platforms_kurobbs.py | 移除 ssl unverified，恢复证书校验（实测该站证书正常） |
| E1-9 | steam/epic/facebook | 删硬编码 `127.0.0.1:7890` 兜底代理，改读 `BOT_DOWNLOAD_PROXY` |
| E1-10 | platforms_generic.py | xhs undefined 改 `\b` 词界替换（注释声明残留风险）；`new Map(...)` 平衡括号扫描（嵌套不再产生非法 JSON 整页降级） |
| E1-11 | sources/web_search.py | config=None 装配 DDG→Bing 兜底链（MCP web_search 不再永远空结果）；未闭合 script/注释残段剥离 |
| E1-12 | sources/transcribe.py | 语音下载流式+20MB 上限即弃 |
| E1-13 | sources/vision_describe.py | 本地图 >8MB 跳过 data URL 走降级+debug 日志 |
| E1-14 | parsers/wbi.py | `_cached_mixin_key` Future single-flight（并发 miss 只一个线程打 nav；leader 失败等待方接手） |
| E1-15 | platforms_generic.py | `youtu.be/<id>?list=` 加 `not video_id` 前置判断走单视频 |
| E1-16 | platforms_bilibili.py | 字幕空格连接+压空白（英文不再粘连） |
| E1-17 | platforms_bilibili_goods.py | float(price) 包 try/except 脏数据置 None 降级 |
| E1-18 | platforms_generic.py + platforms_weibo.py | YouTube 60s/微博 45s 整体预算，步骤间 monotonic 检查，超预算返回已有数据 |

### 7.7 E2 组修复（订阅系统 + 能力层域）
| # | 位置 | 修复 |
|---|---|---|
| E2-1 | capabilities/subscribe_v2.py | remove/pause 权限：群聊=管理员∧本会话存在 destination；私聊=本会话存在 destination；不满足回「没有权限操作该订阅」（**注：并行会话已按审计自行落地 `_can_operate`/`_own_destinations`，本组核实语义一致后未重复改动**） |
| E2-2 | subscription_scheduler.py | per-target `except Exception`+warning 堆栈；记账再抛由 finally 兜底 `release_target_lease` 只清租约不回写过期退避；`deliver_outbox_once` 内层 except 收窄+try/finally |
| E2-3 | subscription_store_v2.py | claim_outbox 回收 `sending` 超 300s 陈旧行（`_OUTBOX_SENDING_STALE_SECONDS`/构造参数/getattr config 键 `bot_subscription_outbox_sending_stale_seconds`）；claim 时刷新 next_attempt_at 防误回收；回收行仍受 5 次死信上限 |
| E2-4 | social_v2.py + music_v2.py + bilibili_adapter.py | 新增 `_reached_cursor`（`int(a) <= int(b)`，非数值回退相等语义）；Twitter 凭据发现命中即 break（E2-5） |
| E2-6 | capabilities/music.py | `ALL_PARTS` 补 `"file"`；候选二次选择改 `dict.pop` 原子取用（防同发送者并发双发；会话键含 sender_id 已由并行会话落地） |
| E2-7 | capabilities/weather.py | `_plausible_weather_query`（≤20 字+口语词首/尾过滤）；群聊未命中城市 `SILENT_AUDIT` 静默，私聊明确报错；双源链路未动 |
| E2-8 | capabilities/eat.py | `_EAT_MODIFIER_RE`：extra 非空须命中修饰/约束词表（寒聊落回闲聊）；语气助词组扩展保住「吃什么啊」 |
| E2-9 | capabilities/echo.py | （并行会话已落地：digest 去 request_id + `prune_prefixed(keep=200)`，核实一致） |
| E2-10 | capabilities/echo.py | （并行会话已落地：`_PUBLIC_HELP_TOPICS` 补吃什么/偷表情，核实一致） |
| E2-11 | capabilities/file_exchange.py | docstring 如实声明「非沙箱、bot 同等 OS 权限、仅限管理员」 |
| E2-12 | capabilities/subscribe_v2.py | add 多余参数显式回「暂不支持 <参数>」 |
| E2-13 | tests 两个文件 I001 | （并行会话已修好，核实 ruff 通过） |

### 7.8 主会话门禁 fallout（修复代理完成后统一裁决）
1. **lint 10 条**：bot.py import 排序（time 提前）1 条 + test_auditfix_runtime_policy.py 9 条（F401/I001/RUF100×5 经 ruff --fix；C408 改 dict 字面量、F841 删 `as holder` 手改）。
2. **mypy 12+2 条**：plain_text.py `re.match` None 守卫；settings.py `_quarantine_corrupt_file` 的 `self.path is None` 守卫；disconnect_notice.py 两处 `and await to_thread(...)` 拆为显式 bool 局部变量；worker.py `task: asyncio.Task` 注解；**`SendQueue` Protocol 移除 `sent_requests` 属性**（A6 的连带——协议消费方只用 submit/find_request/safe_summary）；chat.py `MediaAssetRecord(**dict[str,str])` 改 `model_validate({...})`（并行会话在途代码的静态错误，行为等价）；console_chat.py 两处 `.sent_requests` 改 getattr 兜底。
3. **文档 4 处**：COMMANDS.md 测试口径三处（“4 个测试”→仓库内完整套件约 100 文件）；route-matrix.md 三处（不存在的 test_route_matrix.py 锚点、1080P/200MB 陈旧参数→默认不限/1GB、搜索默认 12→20）。
4. 验证：最终 lint `All checks passed`；typecheck `Success`（205 文件）；**865 passed**。

### 7.9 与并行会话的协同事件（存证）
- A4 修复 `_prune` 后，并行会话追加的「总量硬顶 DELETE」会删 QUEUED 在途行，按 A4 契约移除该语句；对方随后把 `test_soak_growth.py` 改写为兼容 A4 的弱不变量，冲突消解。
- D 组编辑期间 model_router.py/channel_health.py 被并行会话多轮重写（EWMA v2、hedged request）；D1/D2/D6 契约均被其保留整合（其 worker 注释明确「绝不触碰 self.last_attempts——D6」）。
- E2 的 5 项（订阅鉴权、模式词冲突、help digest、help topics、测试 I001）并行会话已按审计报告自行修复，本组核实语义一致后跳过。
- `tests/test_render_backends.py` 的浏览器重置测试已被并行会话改写为 A13 新语义（页面级失败保留浏览器），无需处理。

---

## 8. 行为变化须知（管理员可感知）

1. **渠道健康开始真实生效**：弱渠道会被实际踢出故障转移队列、30 分钟重探回队；`/bot model health` 的 ⛔ 状态从显示变为真实。观察期内若误踢频繁，可临时 `bot_channel_health_enabled=false` 一键回退（两侧同关）。
2. SQLite 发送队列新行 60s 内由内联投递负责；`smoke run_queue_smoke` 在 submit+2s 时 delivered=0 属预期（诊断打印，无断言消费）。
3. 群聊「天气冷了」「吃了吗」类寒聊不再回复/报错（静默记账）；私聊仍明确报错。
4. 小名独占触发的消息在未名单/white1 群不再必然回复；`@小名` 与私聊语义不变。
5. 设置文件损坏时会多出 `.corrupt-<时间戳>` 文件（排查「配置丢失」先看它）。
6. 运维告警任务不再可能被 GC 静默丢失；审计文件轮转并发安全。
7. `/bot reply 随便什么` 现在回用法提示而不是悄悄设成 auto。

---

## 9. 已知残留与低风险项（按优先级）

| 项 | 说明 | 建议 |
|---|---|---|
| 后台巡检集合 | 手动 probe 已含运行时渠道；后台每小时巡检取数点在 `__init__.py`，仍只覆盖 .env 注册表 | 下一轮把该取数点改为 `_probe_specs` 同款合并视图 |
| 旧注册表快照迁移 | 无 source 标记的存量运行时条目仍整体遮蔽 .env 同名条目 | 对相关条目重新 `/bot model update` 一次即迁移 |
| A9 代理解析 | sender 层拿不到运行时 Config，走 `bot.config→env` 探测；Config 与 env 不同步时可能取不到 | 后续把 provider 注入 sender 或统一读 env |
| 小名否定排除宽度 | `(?<!别)…` 只挡紧邻前缀，「千万别叫我X」仍会学 | 正则扩为 `(?:别|不要|千万别|谁)\s*叫` 前置分支 |
| spicy_filter flaky | 约 2.3% 随机失败（鱼香肉丝简介含“酸辣”） | 测试固定 seed 或剔除歧义菜 |
| C12 边缘语义 | transport 失败且 transport 回执无 public_message 时不再用管道回执 finish 兜底重发（去重方向的正确取舍） | 观察 result_unknown 台账量确认无副作用 |
| 模板品牌色残留 | universal_card.html 仍有 `#fb7299`/`#1d9bf0` 等写死语义色（VIP/认证徽章、Top3 序号），未走 PLATFORM_COLORS 派生 | 涉及卡 UI 视觉迭代时一并收敛（改后必跑样例截图+三门禁） |
| 订阅真实账号实测 | 油管/推特拉取链路 adapter 已在，仍未真实账号验证 | 运维实测后记录到本文件 |
| LangSearch | 仍未真实 key 验收 | 验收后更新 §6.5 |

---

## 10. 排障手册（实战沉淀，含本轮新增）

| 症状 | 第一步诊断 | 处置 |
|---|---|---|
| 「改动没生效」 | 查进程启动时间 vs 提交时间（`Get-Process python`），再 grep 代码确认 | 重启 bot；确认没有第二个旧实例 |
| NapCat「已登录，无法重复登录」/3001 不监听 | `Get-Process QQ | Select Id,StartTime` 查多代际并存 | 提权清场（先杀看门狗父进程再杀 QQ/QQEX/NapCatWinBootMain）→ `login-bot.bat` 快速登录；bot 自动重连 |
| 二维码不刷新 | QQ 构建号超出 NapCat 支持表（日志「未找到对应版本的偏移数据」） | 上游问题等 NapCat 新版；启动后 2 分钟内扫首码 |
| 「配置丢了/昵称没了」 | 找 `*.corrupt-*` 文件（settings 原子写损坏隔离） | 从 .corrupt 文件人工恢复字段；本轮起损坏不会再被空态覆盖 |
| 渠道被大面积 ⛔ | `/bot model health`；确认是否真实探针失败（健康门现在真生效） | 网络抖动等 30 分钟自动回队；持续失败按行动清单换 key |
| 同一消息发两次 | 先确认队列 worker 是否开启 + 是否 60s 宽限期内人为重启 | 新协议下不应复现；复现则查 `send_failed_final` 审计与租约日志 |
| pytest 单测偶发红 | `test_spicy_filter` 约 2.3% 随机（§6.13） | 重跑；其余偶发红先查并行会话在途文件 |
| 控制台异常刷屏变化 | B2 修复后异常处理器真正生效，原「Task exception was never retrieved」刷屏变为单行摘要 | 属预期；ConnectionError/TimeoutError/OSError 仍降噪 |
| pytest 会话收尾崩溃 | 共享 %TEMP% 的 pytest-of-* 循环符号链接 | 走 dev.ps1（已固定 basetemp）；绕开必带 PYTHONDONTWRITEBYTECODE=1+外置 basetemp |
| git push 408/断 | 代理掐大包 | 分片推送（逐提交+重试）；分支标签同名必须完整 refspec `refs/heads/...` |
| fetch 报 reference broken | gitdir 在 `ChatBot_Runtime/git`，remote ref 文件可能损坏 | 用 `git ls-remote` 取正确哈希直写该文件 |
| bash 里 PowerShell `$_` 报错 | Git Bash 吞 `$` | 写 .ps1 脚本文件执行；Windows 路径用 cygpath -w |
| 源码树出现缓存 | 绕开了 dev.ps1 | `PYTHONDONTWRITEBYTECODE=1` + basetemp 外置；勿跑 runtime-layout 前手动删 |

---

## 11. 修复史索引（2026-09-07 → 09-10，详情见 git 提交与本文件 §7）

| 日期 | 主题 | 要点 |
|---|---|---|
| 09-07→09-09 | （见旧版 handoff §8，34 行完整表保留于 `git show` 历史） | 统一管线/解析扩展/TG 媒体链路/字幕/key 批次/渠道化/视觉直传/预算等 |
| 09-09→09-10 | A组解析专项（8dc7de4） | 封面原图高清化、时区根治、微博修复+访客兑子、专栏/直播/会员购补齐、竖切横图拼接、ORB 兑子、xsec_token 剥除 |
| 09-10 | db84aae | B站直播风控规避重构+专栏重试+死模板清理 |
| 09-10 | 22d561e / d076d25 | naive 时间契约层根治+点歌链路二轮加固 |
| 09-10 | d5a9f43 | 渠道延迟择优 v2：EWMA 动态测量+慢渠道检测+动态排序+自适应超时+影子并发 |
| 09-10 | 9589232 | 管线检视#3/#4：vision 双门槛统一+聊天专用有界线程池 |
| 09-10 | f96d1a1 / 3819299 | 小红书 playwright 兜底+撤回剥！回归+B站时长秒数化；handoff 存证 |
| **09-10** | **全库审计+修复轮（本文件 §7，未提交）** | **三类别 90 项：P0 搜图/复读投递缺口、weather/eat 互换、队列协议化（WAL/宽限期/终态 prune/租约递增）、事件循环阻塞六连、健康门同源、model set 聚合可达、xhs 正则/乱码/WBI 缓存、订阅 outbox/调度/游标/鉴权、好感度存储/向量归一化、安全归一化+小名网关收窄、配置原子写/解析告警；+96 回归测试；三门禁 865 全绿** |

---

## 12. 任务分组现状（原 9.9 A/B/C 组进度盘点）

- **A组（解析数据层+封面原图+B站/微博专项）**：✅ 已完成（8dc7de4 + f96d1a1 + db84aae 等系列提交）。
- **B组（模型渠道运维+UI 排版+点歌候选窗口）**：延迟择优 ✅（d5a9f43 EWMA v2）；探针参数化 ✅（`bot_channel_probe_*`）；点歌候选选择卡 ✅（`song_candidates.html`）；model list/health 展示 ✅；失败话术本轮修轮换机制，文案继续按实卡反馈调；**待办**：qian-night 渠道重排（starapi/aiprc 原生 gemini 提前——运维操作）、umi 401/额度渠道换 key 重探（运维操作）、订阅油管/推特真实账号实测。
- **C组（好感度数值化+全面质量审查）**：好感度数值化主体已落地并在继续迭代（设计文档+numerical 测试+好感度卡，**并行会话进行中，勿抢**）；全面插件逻辑审查 ✅（即本轮 §7 全库审计，capabilities 级算法/边界已过一遍）；865 全绿 ✅；**待办**：长跑内存/队列/线程数观察（`test_soak_growth` 已有基线，仍需 24h+ 实机观察）、帮助文本各模块参数取值范围与示例继续充实。

## 13. 并行会话协同记录（当前活跃域，接手前必读）

1. **视频理解子系统**（进行中）：`sources/video_understanding.py`、`runtime/video_pipeline.py`、`character/media_registry.py`、chat.py 媒体档案接线、`capabilities/download.py`、test_video_* / test_media_registry 等约 30 用例全绿。设计文档：`docs/superpowers/specs/2026-09-09-video-understanding-design.md`。
2. **好感度数值化收尾**（进行中）：`character/affinity.py` 持续重写中，`docs/affinity-design.md`、`tests/test_affinity_numerical.py`、`affinity_card.html`。其他会话**只读** affinity.py，改调用侧需先读最新版。
3. 协同纪律见 §2 末条（锚定式 Edit、文件域归属、共享树不做回滚式 RED）。

## 14. 文档索引

- `COMMANDS.md`：命令与参数（用户手册层；测试口径本轮已校正）。
- `docs/route-matrix.md`：问法/媒体参数矩阵（本轮已校正 §2 锚点、§7 参数、§8 默认值）。
- `docs/acceptance-manual.md`：验收手册；`docs/napcat-setup.md`：NapCat 配置；`docs/external-runtime-access.md`：Runtime 访问规则；`docs/workspace-archive-policy.md`：归档策略。
- `docs/affinity-design.md`：好感度数值化设计（C组活文档）。
- `docs/superpowers/specs/2026-09-09-video-understanding-design.md`：视频理解设计。
- `docs/plugin-benchmark-2026-09-07.md`：12 插件对比矩阵。
- 旧版交接（2026-09-07，24 轮增补全文）：`docs/handoff-final-2026-09-07.md`（已冻结，不再更新；更早历史 `git show 10a2272^:docs/handoff-final-2026-09-07.md`）。
- 本轮回滚基线：`%TEMP%/auditfix-baseline-20260910-023342/`（tracked.patch / status.txt / untracked.txt）。
