# 守岸人 Bot（ChatBot）— Agent 工作区规则 + 项目全貌（2026-09-12 终稿）

> **本文件的双重身份**：①LLM 接手时自动加载的工作区规则；②项目完整说明（架构/功能/子模块/问题台账）。
> 用户裁定：不再另建 `agent.md`（Windows 大小写不敏感，与本文件同名冲突），一切以本文件为唯一入口。
> **更深细节按需查**：`docs/HANDBOOK.md`（单一活文档：族谱/现行事实/总账 §三/§1-§18 全史）、
> `docs/README.md`（文档索引）、`docs/design/`（B2/B3/B4/B5 四份架构规格，先成文后实现）、
> `COMMANDS.md`（59 模块 188 别名逐参数命令手册）。

## 〇、项目身份（30 秒版）

- **产品**：QQ 聊天机器人「守岸人」（鸣潮角色人格、泰缇斯系统第二实例、非 AI 设定），NoneBot2 + OneBot V11（NapCat，WS 127.0.0.1:3001；webhook 8080），附带 Telegram / Mail / Console 适配器。
- **主包**：`plugins/bot_unified_runtime/`；`config.py` ~450 字段全 pydantic；测试 ~1760 用例全离线 mock。
- **铁律**：改代码必须重启 bot 才生效；生产进程常驻且管理员权限启动（杀它需要提权）。
- **运行数据根**：`ChatBot_Runtime/`（venv/SQLite 群/cookie/日志/缓存）；`data/` 相对路径经 `scripts/runtime_paths.py` 全部重映射到这里。

---

## 第一部分：工作区规则（硬约束，违反即事故）

1. **唯一默认工作区**：本目录（`...\ChatBot\ChatBot`）。`ChatBot_Runtime`（运行数据/venv）、`ChatBot_Archive`（归档）、上层目录默认**不扫描、不索引、不读入上下文**。
2. **运行数据不可删**：Runtime 下的 SQLite、FAISS、向量嵌入、聊天记忆、Cookie、订阅状态、媒体缓存、日志、venv 一律保护（除非用户明确要求）。源码树若再现 `data/` 残留：先备份 `%TEMP%` 再清（写入根治已入库：全部相对路径统一走 runtime_paths 解析，见 `tests/test_datafix_runtime_paths.py`）。
3. **密钥不入库不入聊天**：真实 key 只在 `.env`，配置用 `env:变量名` 引用；出站前 `output/plain_text.py` 的 `redact_local_secrets` 会打码盘符路径/BOT_XXX=/sk- 形态，不要绕过。
4. **git 纪律**：禁 `git add -A`/`git add .`；逐文件显式 add；共享文件动前读最新态；提交后必 `git show --stat HEAD` 核对；push 用完整 refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` 且**仅按用户明确指示**。
5. **交接硬规矩**：写「已完成/已修复/测试通过」必须同时给出**提交哈希**或**可复跑命令+实跑输出**，否则一律按未完成记账。
6. **源码树零缓存**：绕开 dev.ps1 直跑 python/pytest 必须 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp=$TEMP/xxx -p no:cacheprovider`；源码树不应出现 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`data/`。
7. **多代理并发**：≤3 稳定（实测 5-6 并发触发上游 1302 限流整波暴毙）；文件域互斥切分；**代理阵亡先取证幸存成果（git diff+本地测试）再补缺，不盲目重做**；代理一律禁 git 写操作、禁再派代理。
8. **人格资产**：`personas/` 与 Runtime 人格副本是项目灵魂，话术改动必须维持守岸人语气（去 AI 味，参照 `.agents/skills/shuorenhua`）；好感度任何档位都**不攻击/不强硬/不 R-18**（红线已写死进 affinity.py 态度文本）。
9. **归档规程**：压缩 → 验证（testzip+副本）→ 移出，附 manifest（先例：`ChatBot_Archive/2026-09-12/code-hygiene-20260912.zip`）。不要把 Runtime/Archive 设为工作区，不要重建废弃的嵌套 `_Archive` 路径。

---

## 第二部分：目录地图

```
ChatBot\                        ← 本工作区（唯一代码区）
├── bot.py                      ← NoneBot 启动+崩溃守卫（webhook 8080）
├── AGENTS.md                   ← 本文件（规则+全貌）
├── COMMANDS.md                 ← 命令手册人读版（与 /bot help 同口径）
├── docs\
│   ├── HANDBOOK.md             ← 单一活文档：Part 0 族谱/现行事实/总账 §三 + Part II 权威正文 §1-§18
│   ├── README.md               ← docs 索引
│   ├── design\                 ← 架构规格×4（B2 中央决策/B3 文件网关/B4 控制面/B5 计费账本）
│   ├── affinity-design.md      ← 好感度 v4 数值规范唯一权威
│   ├── db-owners.md            ← 26 个 SQLite 库的 owner/建表/清理清单
│   ├── THIRD_PARTY_NOTICES.md  ← MIT 出处唯一保留地（勿删）
│   └── napcat-setup / acceptance-manual / external-runtime-access / workspace-archive-policy / route-matrix / config-catalog-full …
├── plugins\bot_unified_runtime\← 主包（架构图见第三部分）
├── scripts\                    ← dev.ps1（统一任务入口）、runtime_paths.py、e2e_acceptance.py 等
├── tests\                      ← ~1760 用例（全离线 mock）
├── personas\shorekeeper\       ← 人格源（aliases.txt 等，改前读第 8 条）
└── .env                        ← 生产配置（gitignored；真实 key 只在这里）
ChatBot_Runtime\                ← venv / SQLite 群 / cookies / 日志 / 缓存（不扫描不修改）
ChatBot_Archive\                ← 归档（压缩包 + manifest）
```

## 第三部分：架构与消息主链路（流程图）

```
QQ/NapCat(WS 3001) ⇄ bot.py(forward-WS)
 → __init__.py 摄取：段归一 / 引用链递归反查(5层) / 语音预转码 / TG file_id→字节
 → IncomingMessage
 → 路由 base_router(35 matcher→RouteKind) ‖ decision/(shadow 影子对照，默认 legacy_only 不接管)
 → 门禁 policy/gate(黑白名单/安静时间/限流 InMemory+SQLite/主动搭话好感门≥亲近) → 幂等(可选)
 → RuntimePipeline(offload 线程池) → capabilities/*(27+ 能力) → CapabilityResult
 → Review → output/plain_text(说人话/数值打码/密钥与路径打码) → output/renderer(釉瑚云母卡片/合并转发/chunks)
 → SendQueue(SQLite：part 级幂等+UNKNOWN 确认+PARTIAL 断点续发) → sender/onebot|nonebot|mail → QQ/TG/邮件
```

**LLM 子链路**：`llm/model_router`（axonhub 统一网关 17 条 + 渠道注册表、时段分组、EWMA 延迟择优、影子并发 2s、baseline_effort 默认最低档、复杂任务自动升档）→ `providers.py` OpenAI 兼容 POST → 计费账本 `llm/ledger.py`（默认关）→ 故障转移受总预算钳制；私聊失败守岸人话术轮换、群聊静默。

**渲染管线**：`output/card_render/` 云母+液态玻璃+釉瑚渐变漂移（平台色 → `bridge._derive_wash_tokens` 派生 --wash-1/2/3/mist 个性化底；--pc 只做 accent）→ `render_backends.py` playwright 常驻浏览器 `.card` 元素截图。**UI 铁律**：无 `<meta viewport>`、body 透明、字重≤700、动画必须在 .card 内、光晕 alpha≥0.05、两枚阴影 token、失败→纯文本兜底契约零破坏。

## 第四部分：功能 × 子模块清单

| 功能 | 载体文件 | 子模块/作用 | 入口 |
|---|---|---|---|
| 人格对话 | capabilities/chat.py + character/providers.py | 人设全文+运行时上下文【标签】13 分区（空分区不渲染）；反注入包裹+指令剥离；好感/心情/怪癖/身份四层注入 | @bot、白名单抽签、昵称点名 |
| 好感度 v5 | character/affinity.py + capabilities/affinity.py | -100~+100、基准10=档0友善、8 档温和态度连续过渡（无门槛跳变）；**v5 多因素线性步长**：基准因子 × 说话温度 × 相处时长 × 第一印象(建档±30%,随相处衰减) × 当日心情 × 个人节奏，**算法说明一律定性、不展示固定加减数值**（2026-09-12 实弹反馈④ 用户裁定）；惰性回归+印象淡出；SQLite 列 first_signals/first_impression/created_at 自动迁移 | `好感度`/`好感度 算法`/`好感`/`亲密度`/`affinity`（v5 起 RouteKind.AFFINITY 已接 NoneBot matcher，/bot 链也有显式分支） |
| 角色/权限 v2 | policy/roles.py + capabilities/chat.py | user/trusted/enterprise/**admin/super_admin**/blocked 六级；超管自动叠加 admin 权限；【管理团队】分区注入人格（档案+权威规则：超管不可侵犯/被调侃时温和制止、管理员宽容）；`.env` BOT_SUPER_ADMIN_USER_IDS + BOT_ADMIN_PROFILES 普适化配置 | 内部（生产：澜汐/霞月） |
| bot 心情 | character/mood.py | valence/arousal 双轴半衰回归；驱动开火概率/表情档/语气 | 内部 |
| 人格怪癖 | character/quirks.py | 审核制演化：propose→管理员 approve→渲染；反思回路自动投喂 | `/bot quirk` |
| 会话身份 | character/session_identity.py | 每群/私聊独立昵称+标签，防 OOC 护栏内建 | `/bot identity` |
| 记忆体系 | character/history+memory_extract+reflection | 线性对话+长期事实+夜间反思（per-sender 归属）；提醒 LLM 抽取（默认关） | 内部 |
| 提醒督促 | character/reminders.py + capabilities/reminder.py | 自然语言时间点→会话待办(≤20)→每分钟投递守岸人督促 | `12点提醒我…`/`提醒列表` |
| 每日通讯总结 | __init__._register_digest_push_scheduler | 21:30 向群摘要白名单群推送（dedupe 按日期；非 whitelist 零推送） | 自动 |
| 链接解析 | sources/parsers/（34 文件） | 37+ 平台；引用/语音/转发/TG 媒体全通；cookie 18 平台已灌 | 发链接即解析 |
| 卡片渲染 | output/card_render/ | 釉瑚云母卡片（见第三部分） | 随各能力 |
| 点歌 | capabilities/music.py + sources/music_charts.py | 5 供应商+候选卡；真实榜单 ×5（netease×2/QQ/酷狗×2） | `点歌`/`来首` |
| 全球股指 | capabilities/market.py + sources/market_data.py | 18 指数（东财 17+MOEX ISS）；市场词过滤；`fetch_index_trend` 30 日收盘 API 已入库 | `行情`/`B股行情`/`莫斯科股指`（**釉瑚折线卡半成品见台账 #11**） |
| 今日快报 | sources/news_feeds.py | V2EX 真 Atom + IT之家/少数派/华尔街见闻/BBC中文（**营销条目过滤/20条/AI新闻未做，见台账 #12**） | `快报` |
| 天气+预警 | capabilities/weather.py + sources/nmc_weather.py + sources/open_meteo.py | NMC 主通道 2 次重试+Open-Meteo 兜底+预警支路（≤5 条）；F18：geocoding count=10 按人口/精确名排序（治「东京→江苏小镇」）、60+ 中英城市别名（治「华沙」查不到）、查询变体链（『湘潭-雨湖』→逐级拆到行政区/乡镇） | `天气 城市`/`天气 湘潭 雨湖` |
| 占卜 | capabilities/divination.py 等 | 八字（Meeus 节气+藏干权重）/塔罗 78/金钱卦 | `八字`/`塔罗`/`占卜` |
| 随机图 | capabilities/randpic.py | 只读 BOT_RANDPIC_DIRS 自定义文件夹 | `随机图` |
| 订阅 | sources/subscriptions/ + capabilities/subscribe_v2.py | B站/YT(含 live)/xhs(creator/column/live-degraded)/推特/微博；outbox+metadata 落库 | `/订阅` |
| 表情包 | sources/meme_library_listener.py + capabilities/meme_library.py | 群图收库 NSFW 降权；心情低时吵闹梗软重抽 | 自动+`表情` |
| 文件出站 | sender/file_gateway.py（Phase-1）+ downloader | FileSource→Ticket→通道 deliver；download 有 SSRF 护栏 | `/bot download` |
| 控制面 | control_plane/（M1 默认关） | uvicorn 8742+Bearer+/health+/status 只读 | `python -m …control_plane` |
| 计费账本 | llm/ledger.py（M1 默认关） | 三表+generate 出口 sink（失败不阻塞） | `BOT_LLM_BILLING_ENABLED` |
| 决策引擎 | decision/（Phase-1 shadow） | 影子对照记录分歧（P95 0.039ms）；接管待阶段 2 | `BOT_DECISION_ENGINE_MODE` |
| 运维告警 | runtime/alerts + result_unknown | 300s 抑制；台账 TTL；重连对账 | 内部 |

命令全集：`/bot help`（Mica 卡）· `/bot help <模块>`（深度页，逐参数四要素）· `/bot commands`（机器可读目录）· `/bot model|runtime|cookie|identity|quirk|reply|download|parse|logs|status|routes|search|health…`。逐参数真相源：echo.py `_HELP_ENTRIES`。

## 第五部分：验证与门禁

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"           # 全量（终稿基线 1758+ passed）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"           # ruff All checks passed
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"      # mypy Success 238 文件
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout" # 源码树/边界体检
```
真机验收（bot 重启并在线后）：`python scripts/e2e_acceptance.py --target-group <white1群ID> --execute`（默认 DRY-RUN）。

## 第六部分：已知问题台账（残留，动手前先查）

| # | 问题 | 状态 |
|---|---|---|
| 1 | 部分测试以默认路径写源码树 `data/`（reflection/user_affinity sqlite；主路径已由 DATAFIX 治本，此为测试卫生残余；2026-09-12 下午再现一轮，已备份 %TEMP% 后清理） | Wave-6：测试 tmp_path 化 |
| 2 | TG 正文嵌套块级元素早停；social_v2 同函数 channel_title/bio 未改（纯文本无实据） | 罕见残余，登记 |
| 3 | SQLite 限流路径不支持热改；G-DIGEST 等调度器族装配期 config 快照（热改当夜不生效） | 架构取舍，待统一改造 |
| 4 | B2/B3/B4/B5 规格开放问题（8+7+6+7 个）待用户裁决后才进阶段 2/M2+ | 规格在 docs/design/ |
| 5 | B5 Extractor 沙箱等用户脚本；B14 LangSearch 等用户 key；B11 用户明令暂缓 | 等外部 |
| 6 | cron/调度用系统本地时区（异时区机器与安静时间口径偏移） | 登记 |
| 7 | YT live 次信号受 consent 页影响可能漏判；xhs:live 常驻 degraded（无匿名探测通道） | 已知边界 |
| 8 | G-MERMAID 渲染在 loop 线程限时等待（典型 1-2s/张；无网 10-14s 预算截断） | 已知取舍 |
| 9 | NMC findAlarm 只有发布时间无失效时间；rest/weather 必须带码表有效 stationid（无重试已修） | 已知边界 |
| 10 | 生产 bot 未重启——a9d1222 批次（好感度黑洞修复/v5 算法/釉瑚本命底/天气定位）全部待生效 | **等用户提权重启** |
| 11 | ~~F19 股指折线卡~~ **已接线**（153fd78）：`render_market_card_html`+market.py 出图+并行走势；MOEX 无东财 kline（卡上无折线），补图需 MOEX ISS history 源 | 残余：MOEX 折线源 |
| 12 | ~~F9 快报~~ **已做**（153fd78）：营销过滤+RSS 摘要行（治标题党）+默认 20 条+三链触发补齐（AI新闻昵称命令此前坠 help 即根因） | 完成 |
| 13 | F8/F15 help：admin_only 隔离**已存在**（复核确认）；四要素连排拆行**已做**（`_split_facets`）；繁体触发词已补 11 条 | 残余：Mica 卡两栏排版、触发词全量三语普查 |
| 14 | ~~F12 维基~~ **已做**（153fd78）：机械标签废除+状态空省略+概述不再洗成残句 | 完成 |
| 15 | ~~F16 记忆质量~~ **已做**（153fd78）：提示词硬化+琐事黑名单 | 完成 |
| 16 | ~~F5 randpic~~ **已做**（153fd78）：title 置空防兜底链上文案；原图=file:// 原字节直发无重编码 | 完成 |
| 17 | **F6 meme 主动调用**：生成器已配好（2233 端口 enabled）+触发词已丰富；「心情驱动主动发」需完整防骚扰门（概率×心情×冷却×NSFW×白名单），**有意不上线半吊子版** | 待设计评审 |
| 18 | ~~F20 点歌同名先问~~ **已做**（153fd78）：候选默认开启+bare_exact 捷径废除+新指引文案 | 完成 |
| 19 | **F7 随机 cos 照片未做**：等用户提供 gs_kuro_cos 插件+油猴脚本；思路=借鉴其接口做 xhs/推特 cos 图检索随机发（两份参考油猴脚本已读：xhs CI 原图 token 接口 + X name=orig 直链） | 等外部 |
| 20 | F13 queue 告警 `source_bot=unknown`：**已定性**（153fd78 记录）——历史批次终态+300s 抑制聚合（bot_unavailable=worker 阶段无在线 OneBot 的挂起回执，1800s 年龄上限自动清理），非现行缺陷 | 重启后观察 |
| 21 | help 页脚 bot 头像：`.env` 的 BOT_PERSONA_AVATAR_URL 为空 → 页脚用「守」字圆点；用户可提供头像图路径后配置 | 等用户（可选） |
| 22 | **R 系列角色体系**（2026-09-12 晚已落码）：R1 超管/管理员六级角色（超管自动叠加 admin）+BOT_ADMIN_PROFILES 档案注入；R3 同人点名最小间隔 45s（仅 mentions_bot 生效，双限流器同语义）；R4 长文软点名观察门（≥50 字含昵称、非@/非开头称呼/非问句 → 不抢答） | 待全量测试确认+重启生效 |
| 23 | **CC 字幕必存**（77d8b28）：下载自动抓 CC（zh 优先 srt）落盘+纯文本进 meta.subtitle_text；压制不做（ROI 为负）；追问链路零改动可引用 | 完成，重启生效 |
| 24 | **Ghost Downloader 集成**：有 aria2 兼容 RPC（无 CLI）；需用户开 RPC+确认端口/token；当前 yt-dlp 原生 8 并发+16MB Range 分块已可用，装 aria2（winget install aria2.aria2）自动委托 | 可选优化 |
| 25 | **账单计价已接**（483f852）：ledger 写入时按渠道价计价（含缓存命中/创建价+按次计费）；38 条价目已写入生产 store（scripts/import_model_prices.py 幂等导入）；价有出入用 /bot model price 改 | 完成，重启生效 |

## 第七部分：交接史与权威链

- 单一活文档 `docs/HANDBOOK.md`：Part 0（族谱终裁/现行事实/总账 §三）+ Part II（权威正文 §1-§17）+ §18（2026-09-12 五波并发收尾全账：五波 28+ 提交哈希、勘误核验表、问题台账）。
- **维护规矩**：不再新建带日期交接文档；一切增量直接更新 HANDBOOK；「已完成」必须带哈希或可复跑证据。
- 历史文档 26 份+5 份折算件在 `ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（含 manifest），git 历史全量可溯。
