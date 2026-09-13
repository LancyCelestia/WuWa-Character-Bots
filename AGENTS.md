# 守岸人 Bot（ChatBot）— Agent 工作区规则 + 项目全貌（2026-09-12 终稿）

> **本文件的双重身份**：①LLM 接手时自动加载的工作区规则；②项目完整说明（架构/功能/子模块/问题台账）。
> 用户裁定：不再另建 `agent.md`（Windows 大小写不敏感，与本文件同名冲突），一切以本文件为唯一入口。
> **更深细节按需查**：`docs/HANDBOOK.md`（单一活文档：族谱/现行事实/总账 §三/§1-§21 全史）、
> `docs/issue-ledger-p2-p3.md`（P2/P3 逐条详情台账：位置/根因/修法/验收）、`docs/perf-optimization-plan.md`（性能优化全量档案：Phase 1 终态+Phase 2 执行清单+五链路实测基线）、
> `docs/README.md`（文档索引）、`docs/design/`（B2/B3/B4/B5 四份架构规格，先成文后实现）、
> `docs/rendering-contract.md`（渲染契约——改任何卡片模板前必读，契约测试会拦违规）、
> `docs/command-catalog.md`（`scripts/command_catalog.py` 从 `_HELP_ENTRIES` 自动生成的逐参数教程目录）、
> `COMMANDS.md`（命令手册人读版，与 /bot help 同口径）。

## 〇、项目身份（30 秒版）

- **产品**：QQ 聊天机器人「守岸人」（鸣潮角色人格、泰缇斯系统第二实例、非 AI 设定），NoneBot2 + OneBot V11（NapCat，WS 127.0.0.1:3001；webhook 8080），附带 Telegram / Mail / Console 适配器。
- **主包**：`plugins/bot_unified_runtime/`；`config.py` ~470 字段全 pydantic；测试全离线 mock（用例数以最近一次 dev.ps1 -Task test 实跑输出为准，不在文档手写）。
- **铁律**：改代码必须重启 bot 才生效；生产进程常驻且管理员权限启动（杀它需要提权）。
- **运行数据根**：`ChatBot_Runtime/`（venv/SQLite 群/cookie/日志/缓存）；`data/` 相对路径经 `scripts/runtime_paths.py` 全部重映射到这里。

---

## 第一部分：工作区规则（硬约束，违反即事故）

1. **唯一默认工作区**：本目录（`...\ChatBot\ChatBot`）。`ChatBot_Runtime`（运行数据/venv）、`ChatBot_Archive`（归档）、上层目录默认**不扫描、不索引、不读入上下文**。
2. **运行数据不可删**：Runtime 下的 SQLite、FAISS、向量嵌入、聊天记忆、Cookie、订阅状态、媒体缓存、日志、venv 一律保护（除非用户明确要求）。源码树若再现 `data/` 残留：先备份 `%TEMP%` 再清（写入根治已入库：全部相对路径统一走 runtime_paths 解析，见 `tests/test_datafix_runtime_paths.py`）。
3. **密钥不入库不入聊天**：真实 key 只在 `.env`，配置用 `env:变量名` 引用；出站前 `output/plain_text.py` 的 `redact_local_secrets` 会打码盘符路径/BOT_XXX=/sk- 形态，不要绕过。
4. **git 纪律**：禁 `git add -A`/`git add .`；逐文件显式 add；共享文件动前读最新态；提交后必 `git show --stat HEAD` 核对；push 用完整 refspec `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` 且**仅按用户明确指示**。
5. **交接硬规矩**：写「已完成/已修复/测试通过」必须同时给出**提交哈希**或**可复跑命令+实跑输出**，否则一律按未完成记账。
6. **源码树零缓存**：绕开 dev.ps1 直跑 python/pytest 必须 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp=$TEMP/xxx -p no:cacheprovider`；源码树不应出现 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`data/`。**例外**：`plugins/bot_unified_runtime/sources/data/qx.json`（NMC 天气 2527 区县码表）是随包内置资产（.gitignore 已加否定规则），清理波不得误删——2026-09-13 曾被误清致 NMC 路径整体塌向 open-meteo（wx7 报告）。
7. **多代理并发**：并发受**当日累计用量**动态约束（非固定值）：2026-09-13 高消耗日实测 6-7 并发即触发 1302 限流（×4），低消耗日可更高；按文件域互斥切分，避免多人同时改同一文件；遇 1302 立即停止派遣、守住存量在飞、顺手取证阵亡者幸存成果（git diff+本地测试）再补缺，不盲目重做；单任务超 20 分钟的大任务在简报中要求分阶段落盘检查点；代理一律禁 git 写操作、禁再派代理。
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
├── tests\                      ← 回归树（全离线 mock；用例数以实跑为准）
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
 → 路由 base_router(matcher 族→RouteKind) ‖ decision/(shadow 影子对照，默认 legacy_only 不接管)
 → 门禁 policy/gate(黑白名单/安静时间/限流 InMemory+SQLite/主动搭话好感门≥亲近) → 幂等(可选)
 → RuntimePipeline(offload 线程池) → capabilities/*(29+ 能力) → CapabilityResult
 → Review → output/plain_text(说人话/数值打码/密钥与路径打码) → output/renderer(釉瑚云母卡片/合并转发/chunks)
 → SendQueue(SQLite：part 级幂等+UNKNOWN 确认+PARTIAL 断点续发) → sender/onebot|nonebot|mail → QQ/TG/邮件
```

**LLM 子链路**：`llm/model_router`（axonhub 统一网关 17 条 + 渠道注册表、时段分组、EWMA 延迟择优、影子并发 2s、baseline_effort 默认最低档、复杂任务自动升档）→ `providers.py` OpenAI 兼容 POST → 计费账本 `llm/ledger.py`（默认关）→ 故障转移受总预算钳制；私聊失败守岸人话术轮换、群聊静默。

**渲染管线**：`output/card_render/` 云母+液态玻璃+釉瑚渐变漂移。**token 单一事实来源 `theme_tokens.py`**（BRAND 本命色/PLATFORM_THEMES 17 平台显式注册表+别名/两枚阴影 token/半径 30-18-14/宽度登记表/间距刻度；`docs/rendering-contract.md` 为软文档）；平台色只做 accent（--pc 不作底色，wash-mist 打底+色斑≤35%）；`bridge.py` 消费注册表并保持历史导出面兼容。契约机器可执行形态=`tests/test_rendering_contract.py`（6 模板逐条断言）+`test_mica_builders_contract.py`（4 处 f-string 直拼卡）。→ `render_backends.py` playwright 常驻浏览器 `.card` 元素截图。**UI 铁律**：无 `<meta viewport>`、body 透明、字重≤700、动画必须在 .card 内、光晕 alpha≥0.05、恰好两枚阴影 token、失败→纯文本兜底契约零破坏。

## 第四部分：功能 × 子模块清单

| 功能 | 载体文件 | 子模块/作用 | 入口 |
|---|---|---|---|
| 人格对话 | capabilities/chat.py + character/providers.py | 人设全文+运行时上下文【标签】13 分区（空分区不渲染）；反注入包裹+指令剥离；好感/心情/怪癖/身份四层注入；**【当前称谓与主角边界】分区**（AddressingContext：私聊可漂泊者/群聊群友/超管 master 例外/性别 unknown 不推断/用户显式偏好最优先） | @bot、白名单抽签、昵称点名 |
| 好感度 v5 | character/affinity.py + capabilities/affinity.py | -100~+100、基准10=档0友善、8 档温和态度连续过渡（无门槛跳变）；**v5 多因素线性步长**：基准因子 × 说话温度 × 相处时长 × 第一印象(建档±30%,随相处衰减) × 当日心情 × 个人节奏，**算法说明一律定性、不展示固定加减数值**（2026-09-12 实弹反馈④ 用户裁定）；惰性回归+印象淡出；SQLite 列 first_signals/first_impression/created_at 自动迁移 | `好感度`/`好感度 算法`/`好感`/`亲密度`/`affinity`（v5 起 RouteKind.AFFINITY 已接 NoneBot matcher，/bot 链也有显式分支） |
| 角色/权限 v2 | policy/roles.py + capabilities/chat.py | user/trusted/enterprise/**admin/super_admin**/blocked 六级；超管自动叠加 admin 权限；【管理团队】分区注入人格（档案+权威规则：超管不可侵犯/被调侃时温和制止、管理员宽容）；`.env` BOT_SUPER_ADMIN_USER_IDS + BOT_ADMIN_PROFILES 普适化配置 | 内部（生产：澜汐/霞月） |
| bot 心情 | character/mood.py | valence/arousal 双轴半衰回归；驱动开火概率/表情档/语气 | 内部 |
| 人格怪癖 | character/quirks.py | 审核制演化：propose→管理员 approve→渲染；反思回路自动投喂 | `/bot quirk` |
| 会话身份+称谓偏好 | character/session_identity.py + character/addressing.py | 管理员设会话昵称/标签（防 OOC 护栏内建）；**用户自助称谓/性别偏好**（AddressingPreferenceStore SQLite，`/bot identity set-name/set-gender/unset-*` 仅本人、绕管理员门；群聊"漂泊者"为保留字自动回退） | `/bot identity` |
| 记忆体系 | character/history+memory_extract+reflection | 线性对话+长期事实+夜间反思（per-sender 归属）；提醒 LLM 抽取（默认关） | 内部 |
| 提醒督促 | character/reminders.py + capabilities/reminder.py | 自然语言时间点→会话待办(≤20)→每分钟投递守岸人督促 | `12点提醒我…`/`提醒列表` |
| 每日通讯总结 | __init__._register_digest_push_scheduler | 21:30 向群摘要白名单群推送（dedupe 按日期；非 whitelist 零推送） | 自动 |
| 链接解析 | sources/parsers/（34 文件） | 37+ 平台；引用/语音/转发/TG 媒体全通；cookie 18 平台已灌 | 发链接即解析 |
| 卡片渲染 | output/card_render/ | 釉瑚云母卡片（见第三部分渲染管线；6 Jinja 模板 + 4 处 f-string 直拼卡全部走 theme_tokens 契约） | 随各能力 |
| 点歌 | capabilities/music.py + sources/music_charts.py | 5 供应商+候选卡；真实榜单 ×5（netease×2/QQ/酷狗×2） | `点歌`/`来首` |
| 全球股指 | capabilities/market.py + sources/market_data.py + sources/market_crosscheck.py | 18 指数（东财 17+MOEX ISS）；市场词过滤；30 日走势（MOEX 走 ISS history 真折线）；腾讯源 6 指数交叉核验脚注；东财 kline 必须带 `end` 参数（接口 2026-09-13 起变更，已修+回归锁死） | `行情`/`B股行情`/`莫斯科股指` |
| 个股行情 | capabilities/stocks.py + sources/stock_data.py | 9 家科技巨头 OHLCV/市值/KDJ/多日收益分布箱形图；OpenAI/Anthropic/字节非上市红线（结构性无价格字段，估值唯一口径=官方公告/注明口径的公开报道） | `英伟达股价`/`股价`/`市值`/`stocks` |
| 汇率 | capabilities/fx.py + sources/fx_data.py | 主要货币面板+定向换算（USD/EUR/GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED；TWD/MOP/AED 东财无源→诚实标注）；基准货币/中间价/延迟显式 | `汇率`/`美元兑人民币`/`100日元换多少人民币` |
| 今日快报 | sources/news_feeds.py | V2EX 真 Atom + IT之家/少数派/华尔街见闻/BBC中文（营销条目过滤+默认 20 条已做，见台账 #12） | `快报` |
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

命令全集：`/bot help`（Mica 卡）· `/bot help <模块>`（深度页，逐参数四要素）· `/bot commands`（机器可读目录）· `/bot model|runtime|cookie|identity|quirk|reply|download|parse|logs|status|routes|search…`（**无顶层 health 子命令**，健康信息在 status 内）。逐参数真相源：echo.py `_HELP_ENTRIES`（67 topics）。

## 第五部分：验证与门禁

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"           # 全量（以本次实跑输出为准；不在文档中手写固定用例数）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"           # ruff All checks passed
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"      # mypy Success 238 文件
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout" # 源码树/边界体检
```
真机验收（bot 重启并在线后）：`python scripts/e2e_acceptance.py --target-group <white1群ID> --execute`（默认 DRY-RUN）。

## 第六部分：已知问题台账（残留，动手前先查）

| # | 问题 | 状态 |
|---|---|---|
| 1 | 部分测试以默认路径写源码树 `data/`（reflection/user_affinity/**addressing_preferences** sqlite；主路径已 DATAFIX 治本，此为测试卫生残余；2026-09-12 下午与 2026-09-13 凌晨两度再现，均已备份 %TEMP% 后清理；全量套件直跑会触发） | Wave-6：测试 tmp_path 化 |
| 2 | TG 正文嵌套块级元素早停；social_v2 同函数 channel_title/bio 未改（纯文本无实据） | 罕见残余，登记 |
| 3 | SQLite 限流路径不支持热改；G-DIGEST 等调度器族装配期 config 快照（热改当夜不生效） | 架构取舍，待统一改造 |
| 4 | B2/B3/B4/B5 规格开放问题（8+7+6+7 个）待用户裁决后才进阶段 2/M2+ | 规格在 docs/design/ |
| 5 | B5 Extractor 沙箱等用户脚本；B14 LangSearch 等用户 key；B11 用户明令暂缓 | 等外部 |
| 6 | cron/调度用系统本地时区（异时区机器与安静时间口径偏移） | 登记 |
| 7 | YT live 次信号受 consent 页影响可能漏判；xhs:live 常驻 degraded（无匿名探测通道） | 已知边界 |
| 8 | G-MERMAID 渲染在 loop 线程限时等待（典型 1-2s/张；无网 10-14s 预算截断） | 已知取舍 |
| 9 | NMC findAlarm 只有发布时间无失效时间；rest/weather 必须带码表有效 stationid（无重试已修） | 已知边界 |
| 10 | 生产 bot 未重启——a9d1222 批次（好感度黑洞修复/v5 算法/釉瑚本命底/天气定位）+ 2026-09-13 全域审计批次（称谓体系/stocks/fx 上车/渲染契约/identity 自助/卡片化接线，见台账 #26）全部待生效 | **等用户提权重启** |
| 11 | ~~F19 股指折线卡~~ **已接线**（153fd78）；~~MOEX 折线源~~ **已接**（2026-09-13：`fetch_index_trend("100.IMOEX")` 走 MOEX ISS history 尾部窗口取 30 真实收盘，卡上真折线；另加腾讯源 6 指数交叉核验脚注） | 完成 |
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
| 22 | **R 系列角色体系**（2026-09-12 晚，73d8c6a+测试批）：R1 超管/管理员六级角色（超管自动叠加 admin）+BOT_ADMIN_PROFILES 档案注入；R3 同人点名最小间隔 45s（仅 mentions_bot 生效，InMemory+SQLite 同语义且都先于 role bypass——SQLite 顺序不一致已修）；R4 长文软点名观察门；21 例专属回归（test_policy_sender_interval/test_policy_soft_mention_gate/test_admin_roster_and_roles） | 代码+测试完成，重启生效 |
| 23 | **CC 字幕必存**（77d8b28）：下载自动抓 CC（zh 优先 srt）落盘+纯文本进 meta.subtitle_text；压制不做（ROI 为负）；追问链路零改动可引用 | 完成，重启生效 |
| 24 | **Ghost Downloader 集成**：有 aria2 兼容 RPC（无 CLI）；需用户开 RPC+确认端口/token；当前 yt-dlp 原生 8 并发+16MB Range 分块已可用，装 aria2（winget install aria2.aria2）自动委托 | 可选优化 |
| 25 | **账单计价已接**（483f852）：ledger 写入时按渠道价计价（含缓存命中/创建价+按次计费）；38 条价目已写入生产 store（scripts/import_model_prices.py 幂等导入）；价有出入用 /bot model price 改 | 完成，重启生效 |
| 26 | **2026-09-13 全域审计批次**（多会话协同：本会话 SDD + 并行 Codex 会话，独立评审代理终裁 Critical 0/Important 6 已全修）：①称谓体系——AddressingContext 私聊漂泊者/群聊群友/超管 master 例外/性别不推断 + AddressingPreferenceStore 持久化 + `/bot identity set-name/set-gender/unset-*` 自助（群聊"漂泊者"保留字回退）+ 群摘要隔离（确定性头+LLM 提示词双处）+ 摄取层 sender_display_name 填充；②渲染契约——theme_tokens 单一来源+PLATFORM_THEMES 17 平台+6 Jinja 模板与 4 处 f-string 卡全部收编，契约测试 98+44 条；③金融——stocks（9 巨头 OHLCV/市值/KDJ/箱形）/fx（11 币种）/market 交叉核验/MOEX 真折线上车，OpenAI 非上市红线三层结构性成立，东财 kline `end` 参数变更已修；④帮助注册表 65→67 topics（新增 帮助/聊天/戳一戳/表情收库/自然语言/忽略/个股行情/汇率），11 个结构化元数据字段+20 条一致性门禁；⑤占卜/历史上的今天卡片化+渲染后端接线（推送调度器保持纯文字）；⑥菜谱图片质检（分辨率/宽高比/来源落盘）+图库预热 60/61 道。证据：`docs/handover-c-20260913.md`（C 方向）+ `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/`（SDD 台账+B 方向交接+评审报告）。已知 parked：占卜卡每抽一子目录暂不受 enforce_quota 约束（评审 Minor C5）；route-matrix 覆盖门子串匹配偏弱（B park M-2）；mermaid 真机出图待重启观察。**0913 文档实况增补**：⑦mermaid 渲染线程 asyncio 中毒已根修（render_backends `_close_thread_browser` 改 `ctx.__exit__`）；C 终批评审（`review-c-final-report.md`：1 Critical/3 Important/8 Minor，总裁决「需修」）新发现漏毒路径 C-1——`_get_browser` launch 重试失败分支已 start 的 ctx 不退出且 thread-local 未写入→该线程永久中毒至进程重启，**C-FIX 修复中**；多会话终审报告（`final-review-report.md`）总裁决全分支「可合入」（Critical 0/Important 0）。⑧identity.md 称谓边界补全（§2.3 漂泊者情感限私聊语境+§一称呼段群聊称谓场景边界/master 例外，世界观设定零触碰）。⑨占卜/历史上的今天卡片配额 prune 关账（divination.py、today_history.py 各补 `_prune_card_dirs`，keep=120）。⑩fx 卡语义两处收口（面板副标题显式标注面板/换算语义；出图文件名 digest 纳入查询语义 panel/pair:方向，不再同名互覆）。⑪config-catalog A26 补齐（stocks/fx 开关落地+addressing_preferences_db_path 路径字段）。⑫新增文档：`docs/design/fstring-card-dom-spec.md`（f-string 卡 DOM 统一规格，Python 侧共享 mica 壳方案，未实施待裁决）、`docs/acceptance-manual.md` §6.6（本批重启验收清单）。0913 收尾波：G1 data 写入拦截守卫根治台账#1、东财空响应重试上线（bot_market_retry_on_empty）、C-1 渲染线程中毒漏毒路径修复、smoke 配置 JSON 解码修复、fx 卡语义两处、config-catalog/env-example 补录、config-catalog 全量同步收官（三期 157 键归零白名单+8 处漂移修正，doc_sync_gates 门禁常驻）、route-matrix 触发词列全量对齐、T-Spec 触发规范化：英文触发 32 词全覆盖+拼音三批 136 词（全拼 76+缩写 60，冲突审慎弃用）+繁體补齐（快報族/隨機圖/親密度/點唱/天氣預報修活）+昵称动词缺口（守岸人点唱/天气预报）+劫持清零（divination 8/stocks 4/market 3/weather 1，探针 37 样例+8 真命令对照）+路由判定序按 priority 归一 + 分享瓦片标签/清晰度角标/音乐署名/话题 chip 视觉四件；0914 二次收尾：订阅存储离环（17 个 *_async 门面+调度器 await 化，线程 id 断言离环实证）、触发体检棘轮 24→0 清零（extract_trigger_words 提取器+探针 37 样例全清+三守卫负样本入 E2E 矩阵 34 项）、路由判定序按 priority 归一（stocks 不再抢占 41 组）、P1 热点卫生 4 处模块级提级、E01 漂移相位钉帧 7/7+f-string 三卡二批+reduced-motion 死 CSS 修复（截图字节确定性达成）、UX 文案 12 条落地（logger 兑现）、验收清单 §6.6.1 触发形态、死配置键裁定=休眠预留不加废弃标注 | 代码+测试完成，重启生效 |
| 27 | **2026-09-13 实战审计批**（单线程）：①qx.json 第三次消失→%TEMP% 备份恢复+随包入库根治；②静态门残留 ruff 1（typing.Callable）/mypy 1（_HELP_ENTRY_META object→Any）清零，全量 4523 passed；③乱触发三件套收口：route-matrix 覆盖门改 \b 词边界（M-2）、求籤/求签另立入双正则+echo 注册+帮助别名闭合 30 词（含 pp/mp/yg/lssg 等漏登拼音，command-catalog 再生成联动）、zb/bz/sz/sm 真冲突缩写「永不启用」设计裁定+测试锁；④安全专项：绑定面核查（进程内仅 control_plane 127.0.0.1+显式拒 0.0.0.0；8080 属 NapCat 侧非代码）、全树危险 sink 零命中、wiki 标题全 urlencode、downloader SSRF 护栏实证、pip-audit（临时 venv 法不污染生产）——curl-cffi 0.14→0.16.3 清零，cryptography ×3/aiosmtplib ×2 被适配器钉死阻塞（qq 1.7.2 钉 <49、mail 1.0.0a7 钉 ~=3.0）→回滚 48.0.1 保 pip check 零冲突，入 P2 台账等上游；⑤P2/P3 全量入档 docs/issue-ledger-p2-p3.md（死配置键=R65 已裁定保留）；⑥性能全量档案 docs/perf-optimization-plan.md+测量脚本 scripts/measure_latency_chains.py 首轮实测：路由 P50 0.014ms/P95 0.054ms、渲染 warm P50 2222ms（固定 sleep 地板实锤）、NapCat 离线 unreachable；⑦23:00 定时批按 §三执行 Phase 2（BOT_RENDER_MAX_CONCURRENCY/BOT_RENDER_WAIT_BUDGET_MS 接线，缺省=字节级现状） | 代码+测试+文档完成；Phase 2 待 23:00 批；重启生效 |

## 第七部分：交接史与权威链

- 单一活文档 `docs/HANDBOOK.md`：Part 0（族谱终裁/现行事实/总账 §三）+ Part II（权威正文 §1-§17）+ §18（2026-09-12 五波并发收尾全账）+ §19-§20（并行批次补录）+ §21（2026-09-13 全域审计批次总账）。
- **维护规矩**：不再新建带日期交接文档；一切增量直接更新 HANDBOOK；「已完成」必须带哈希或可复跑证据。例外记录：2026-09-13 批次的多会话交接件 `docs/handover-c-20260913.md`（C 方向）与 `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/progress-agent-b.md`（B 方向）为外部会话产物，保留原样并在 HANDBOOK §19 引用。
- 历史文档 26 份+5 份折算件在 `ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（含 manifest），git 历史全量可溯。
