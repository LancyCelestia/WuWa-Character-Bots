# 全仓链接归一审计（2026-09-20，LINK-AUDIT 席）

> 任务定义（用户原话）：「把 chatbot 里所有的接口协议、模块功能、函数参数、变量、文本文档说明
> 是否**用链接达成了统一格式、统一内容**，全部都查一遍，没有的话立马改过来。」
> **唯一判定标准**：同一事实是否只写在一处、其余处用链接/生成物指过去。
> 手抄副本 = 缺陷；副本与真身不一致 = **高危**（会误导下一个读者）。
> 逐席工作日志与探针原件：`.superpowers/sdd/2026-09-19-emergency-info-unify/reports/LINKAUDIT-report.md`。

---

## 0. 一句话结论 + 抽样规模与方法

**结论**：**没有达成链接归一。** 五个维度全部有缺陷，共 **10 条高危 + 7 条中危**；
最严重的一类不是"链接指错"，而是**同一事实在真身内部/权威文档里被抄了两遍且已经抄歪**
（帮助注册表 77 主题中 50 主题参数说明双份互异、配置目录 54 处「✅热更」标记 32 处被代码逐条证伪、
模块归属表 44 条路径**零条**指向真身）。常驻门全绿（`test_doc_sync_gates.py` 5 passed、
`command_catalog.py --check` EXIT=0）恰恰证明**现有门查不到这一类**。

**规模与方法**（全部可复跑，探针在 `%TEMP%/link-audit/`，不落源码树）：

| 审计项 | 规模 | 方法 |
|---|---|---|
| `.py:行号` 坐标 | **3837 条全量普查** + 200 条分层随机抽样（seed=20260920）人工核 | `probe_d6.py`：全库 basename 索引 + "行容量优先"解析 + 垫片单列一档 |
| markdown 互链 | 578 条本地链接全量 | `probe_links.py` |
| 配置面 | config.py **633** 字段 / catalog 54 热更标记 / SETTABLE **41** / RESTART **54** / HOT **22** 四表交叉 | `probe_c5/c6.py` + `probe_c7.py` **实跑 `set_override` 取证** |
| 帮助/命令面 | 77 topics / 77 meta keys / 3 extra lines，AST 抽取零孤儿 | `probe_b.py` |
| NapCat 残留 | .md **224 行** / .py **140 行** 命中，44 份 .md | `grep -rn` 全量重数（旧台账"17 处"口径作废） |

**冷热判定实测**（判据 = `ls --time-style=+%H:%M:%S` + `git status --porcelain`，不用感觉）：
`AGENTS.md`/`docs/HANDBOOK.md` 03:45:26、`COMMANDS.md`+`route-matrix.md` 04:00:32、
`command-catalog.md` 04:00:45、`tts-contract-layer.md` 04:00:09、`auto-facts.md` 03:31、
`config-catalog-full.md` 03:23 —— 全部热面，**一律未改**，修复以 §7 diff 交付。
审计期间 `AGENTS.md` 至少被并发改写两次（本席两次读到内容不同），印证判定正确。

---

## 1. A 接口协议面

### A-1【高危】控制面 `/logs/sources` 手抄事件源枚举，缺 2 项
| 项 | 内容 |
|---|---|
| 缺陷位置 | `plugins/bot_unified_runtime/control_plane/api/v1.py:187` |
| 抄成了什么 | 字面量 10 项 `["bot","nonebot","napcat","control_plane","decision_engine","pipeline","sender","llm","database","scheduler"]` |
| 真身 | `domains/ops/monitor/event_store.py:54-67` `EVENT_SOURCES` **12** 项（多 `telegram`、`mail`）；合同口径 `docs/design/backend-v2-implementation-guide.md:211`（§8）亦 12 项 |
| 铁证 | **同一端点两条实现**：`control_plane/api/events.py:23,123` 走 `from .. import EVENT_SOURCES` + `list(EVENT_SOURCES)`（正确姿势）；`v1.py:187` 手抄（错误姿势） |
| 误导谁 | WebUI 按 items 渲染来源下拉 ⇒ 永远筛不到 telegram/mail 事件，并可被据以宣称"控制面不采 TG/Mail 日志" |
| 修法 | 删字面量，引用真身枚举（§7 R1） |
| 状态 | 已落码=否（当前树即如此）；`v1.py` 为 `??` 未入库件 ⇒ 只出 diff |

### A-2【高危】`EVENT_SOURCES` 两份活定义（12 vs 14），两份文档各抄一份且互不指链
- 真身之争：`domains/ops/monitor/event_store.py:54-67` = **12**（V2.1 合同 §8 有意收敛）；
  `control_plane/events.py:42-56` = **14**（存量，多 `capability`/`renderer`）。**两份都被消费**：
  `api/events.py:23` 引 14 项版，`api/v1.py:187` 手抄 10 项（两边都不等于）。
- 文档副本互斥：`docs/design/control-plane-events.md:59` 手抄 14 项、
  `docs/design/backend-v2-implementation-guide.md:211` 手抄 12 项，**互不指链、谁都不说自己是被抄方**。
- `event_store.py:12-19` 头注自我披露了这层关系（"存量多出 capability/renderer 两个 source"），
  但**没有一处声明"以谁为准"** ⇒ 读者只能靠读 20 行注释推断。
- 修法（§7 R2/R3）：定权威（建议 V2.1 的 12）+ 存量处加一行"派生自 X，多两枚存量码，退役指针=…"；
  `control-plane-events.md:59` 改指 backend-v2 §8 而非重列。

### A-3【高危】retcode 终态白名单：文档副本与代码真身已漂移（8 码 vs 10 码），三处失真
- 真身：`domains/transport/sender/onebot.py:176`
  `retcode in {403, 404, 100, 1003, 1200, 1201, 1400, 1401, 1403, 1404}` = **10 码**；
  `git show HEAD` 同值 + `git status` 该件干净 ⇒ **已落码且已入库**。函数自带 docstring 说明 100/1400 是 T46-N1 扩码。
- 三处手抄副本失真：
  1. `docs/design/tts-contract-layer.md:68`：称"现行 `_is_final_failure_retcode={403,404,1003,1200,1201,1401,1403,1404}`"
     （8 码）并断言 1400/100 **不在**白名单 ⇒ **对 HEAD 为假**；同句坐标 `onebot.py:119-122/:174` 亦失效
     （提取器实居 `:134-143`、判定 `:162-176`）。
  2. `docs/design/tts-handover-20260919.md:198`：称"T46-N1 retcode 白名单扩面（1400 先行）归 Wave H（**已授权未开工**）"
     ⇒ 扩面**已落地入库**，"未开工"为假。
  3. `AGENTS.md:189`（#44 ⑧）与 `docs/HANDBOOK.md:2389`（§35 ④）：均写"T46-N1 白名单实集 **8 码**" ⇒ 数字副本失真。
- 误导谁：Wave H / U-29 施工者会**重复施工**同一件事，或据"1400 不在白名单"推出
  "毒语音会白烧 3 轮"的错误设计前提并据此改方案。
- 修法（§7 R4/R5/R6）：三处删除码集字面量与计数，改指符号 `_is_final_failure_retcode`；
  建议把该集合提为具名常量使文档可指符号而非行号。

### A-4【中】协议端旧口径（NapCat）残留：重数结果与"17 处"旧口径差一个数量级
- 实测：`grep -rn "NapCat\|napcat" --include="*.md" docs/ AGENTS.md COMMANDS.md` = **224 行 / 44 份 .md**；
  `plugins/ tests/ scripts/` = **140 行**。
- **口径本身不统一**：`docs/design/emergency-info-unify-summary-20260919.md:54` 另给一套按文件计的数
  （AGENTS 8 / README 4 / HANDOFF-NEXT 6 / HANDBOOK 37 / napcat-setup 26 / acceptance 15 / bot.py 5），
  与 224 又不同 ⇒ **全仓无权威计数**。
- 正向（重要）：2026-09-20 已铺"术语说明"横幅，实测覆盖 `AGENTS.md:201`、`docs/HANDBOOK.md:2`、
  `docs/README.md:2`、`docs/acceptance-manual.md:2`、`docs/config-catalog-full.md:6`、
  `docs/design/backend-v2-implementation-guide.md:2`、`docs/design/control-plane-events.md:2`、
  `docs/design/backend-v2-acceptance-matrix.md:2`。统一句式 + 相对链接指 `snowluma-setup.md`
  = **本次审计里唯一成型的"单点声明 + 链接派发"范式**，其余四个维度都该照它收口。
- 仍缺横幅且含现行端口径表述的 .md（判据=命中但首 8 行无"术语说明"）仅 3 份，其中
  `docs/napcat-setup.md`、`docs/snowluma-setup.md` 属回滚件/对照表，**语义正确不计缺陷**；
  `AGENTS.md` 横幅在文末 `:201`，读者先撞上 `:129` 校园行的"以 NapCat 为现行端"表述 ⇒ 位置问题（§7 R7）。
- "以 NapCat 行为为准"断言专项核查：
  - `domains/core/decision/outbound_registry.py:232` 文本 "NapCat 实测验证（A1/风险5 清单未取证，如实标注待验证）"
    ⇒ **措辞自相矛盾**（既"实测验证"又"未取证"），且协议端已换 ⇒ §7 R8。
  - `domains/transport/sender/onebot.py:1181` "get_msg 返回 schema / not-found retcode 形态未经真机回读"
    ⇒ 这条**诚实**（自我标注未证实），与
    `docs/design/emergency-info-outbound-gate-spec-20260920.md:113`（"SnowLuma 侧同构性未证"）**一致** ✅ 不计缺陷。
- 修法（§7 R9）：不改写史实正文（铁律）；把"横幅铺设清单"本身变成**生成物**
  ——`doc_sync.py` 输出"含 NapCat 且无横幅"文件清单，否则永远无法回答"还差哪些"。

### A-5【未证实，如实标注】OneBot V11 段类型无中央真身，同名不同集
- 全仓**不存在** `SEGMENT_TYPES`/`SegmentType` 权威定义，各自私集且**同符号名两套成员**：
  `_MEDIA_SEGMENT_TYPES` 在 `domains/core/decision/engine.py:358` = `{image,record,video,forward}`，
  在 `domains/media/capabilities/media_archive.py:69` = `{image,photo,sticker,mface,animation}`；
  另有 `transcribe.py:38`、`vision_describe.py:59,67`、`notes.py:204`、`telegram_media.py:52`。
- **本席不开"必须合并"的处方**：归档面的"媒体"含 sticker/mface、决策面的含 forward，
  语义本就不同，是否存在唯一正确并集**未证实**。记为「结构性缺陷 + 待裁决」。
- 建议：新建 `domains/core/contracts/segments.py` 权威成员表，各消费面按语义取**不重名**子集
  （`ARCHIVE_MEDIA_SEGMENT_TYPES` 等）；样板已有先例=`domains/core/text_boundary.py`（T59 中央边界谓词件，六副本收编）。

---

## 2. B 函数参数面

### B-0 先给绿灯（防后文被误读）
- `scripts/command_catalog.py --check` → `command catalog is current (77 topics)` / **EXIT=0**
  ⇒ `docs/command-catalog.md` 确为 `_HELP_ENTRIES` 合法产物，无手改。
- `_HELP_ENTRIES` 77 / `_HELP_ENTRY_META` 77 / `_HELP_EXTRA_LINES` 3，AST 三向集合差集**全空**（零孤儿零缺失）。
- ⇒ **B 面问题不在生成链**，在"真相源自己抄了自己两遍"与"人读件无参数级门"。

### B-1【高危】`_HELP_ENTRIES` 同一 topic 内 `lines[]` 与 `detail`【指令与参数】**平行两份参数说明**，77 主题中 50 已漂移，且**两份都印给用户**
- 结构：`domains/chat_reply/capabilities/echo.py:451` 起，每 entry 同时带 `lines`（逐命令四要素）与
  `detail`（板块介绍/指令与参数/取值范围/权限与效果/示例）。
- 实测（`probe_b.py`）：两块的【指令与参数】**逐字相同**的主题 **3** 个；
  **前 16 字符同、正文不同**的 **53** 处 ⇒ 真实漂移面 ≥50 主题。
- **渲染面铁证**：`echo.py:3620-3630` 深页 body = `title_line` + 全部 `lines` + 追加 `detail_text`，
  去重门只有 `if detail_text and detail_text not in body`（:3628）——整块相等才抑制，
  而 detail 另含板块介绍 ⇒ **等价于永不去重** ⇒ `/bot help 状态` 一条消息把同一命令讲两遍且说法不同。
- 已证漂移实例（逐字，非推测）：
  - `功能管理`：`lines[2]`"意义=受控调整功能，**修改仅限超管**，已运行任务不强杀"
    vs `detail` 同句吞掉"修改仅限超管"（权限限定语丢失）。
  - `状态`：`lines[0]` 列明内容（软暂停/角色计数/缺失数/限速与安静时间/LLM…）
    vs `detail`"内容=多行状态清单（详见下方效果）"——一条具体、一条空指。
  - `回执`：只有 `detail` 带"可从 `/bot recent` 输出拿"这一取数路径。
- 误导谁：① QQ 侧管理员（同一条回复自相矛盾）；② 文档席——生成器只吃 `lines`，
  于是 **`docs/command-catalog.md` 与 `/bot help` 深页展示的同一命令参数不一致**。
- 修法（§7 R10，热面）：`detail` 的【指令与参数】块废除手写、由 `lines` 派生注入
  （`echo.py:3204-3205` 已有 `_HELP_EXTRA_LINES` 同写两处的现成姿势可照抄）。

### B-2【高危】`COMMANDS.md` 是纯手写副本；门只查"别写死总数"，**零参数级比对**
- 自证：`COMMANDS.md:5` 称与 `/bot help <模块>` 同口径、`:9` 点名"数据真相源=echo.py `_HELP_ENTRIES`"，
  但正文逐条手抄"关键参数"四列表。
- 权威链自认未收敛：`docs/design/COMPACT-CHECKPOINT.md:234`
  "「`command_catalog.py --write` 只生成 docs/command-catalog.md，**不会生成 COMMANDS.md**；
  本轮 COMMANDS.md 人工追加说明，**后续应收敛生成机制**」"。
- 门的面：`tests/test_documentation_consistency.py:414-420` 只断言
  ①含 `docs/command-catalog.md` 链接 ②无 `\d+个(模块|别名)` ③无"好感度 v4"，加 `:380-411` 十个 marker。
- 已证失真（实弹，非"可能漂"）：`COMMANDS.md:14` 用一整格详细登记 `/bot decision [N]` 为现役管理员命令；
  实测 `build_decision_query_result`（`echo.py:163`）在 `__init__.py` dispatch elif 链（:6562–:7076 逐支）**无 `decision` 分支**、
  全仓生产消费者为零 ⇒ 发出即坠 help 兜底。缺省值/上限（`_DECISION_QUERY_DEFAULT_LIMIT=20`/`_MAX=100`，`echo.py:103-104`）
  与文档**一致**——**漂的是"可达性"不是"取值"**。
  旁证已登记未修：`docs/design/audit-20260920-unify-U7-command.md:230`（U7-F7），
  根因由其点明："双向门判定'可达'的标准是词表解析层，不验执行层落点"。
- 修法（§7 R11）：COMMANDS.md 参数四列表纳入生成（人读段落保留），或参数列改"链接 + 一句话"
  并加门断言"COMMANDS.md 的必填/范围串必须能在 command-catalog.md 命中"。

### B-3【中】`echo.py:449` 代码注释手抄 topic 计数，已失效
`# 增删主题…必须同步声明源（73 topics 口径不变）` vs 权威 **77**（`--check` 实跑输出、
`docs/auto-facts.md` "帮助 topic 数：77"）。⇒ 照注释去"补齐"反而制造不一致。修法 §7 R10。

### B-4【中】帮助文案里的"热改"全称断言与代码互斥（详见 C-1，同一条证据链）
`echo.py:1260`（限流 topic `lines`）："**以上全部**支持 /bot runtime set 热改，立即生效
（接话总开关 ENABLED 装配期读取，改后需重启）"——实测该 topic 点名的
`BOT_GROUP_CHAT_AUTO_REPLY_ENABLED` **与** `..._PROBABILITY` **两键都在 `RESTART_REQUIRED_KEYS`**
（`settings.py:333`，理由文本自证"覆盖写入了也不被读取"），文案只点名前者、并对后者维持"全部" ⇒ 过强断言。
`COMMANDS.md:53` 末句"**全部热改即时生效**"同族。修法 §7 R10/R12。

### B-5【正向】称谓取值面副本当前与真身同值
`COMMANDS.md` 身份行 `set-gender 取值 male|female|nonbinary|custom|unknown`
≡ `domains/chat_reply/character/addressing.py:12` `_GENDER_VALUES`（成员一致）。
仍建议改指符号，但**不计缺陷**。

---

## 3. C 变量与配置面（四表交叉 + 实跑取证）

### C-1【高危】`config-catalog-full.md` 的「✅热更」54 行中 **32 行被代码逐条证伪**
- 三面真身：`domains/chat_reply/runtime/settings.py` `SETTABLE_KEYS`=**41**（:537）、
  `RESTART_REQUIRED_KEYS`=**54**（:333）；合并面 `__init__.py:733 _RUNTIME_HOT_OVERRIDE_FIELDS`=**22**。
- 程序化比对（`probe_c6.py`）：catalog 打「✅热更」共 **54 行**，其中 **32 个 (行,键) 被证伪**：
  - **25 处键其实躺在 `RESTART_REQUIRED_KEYS`**：`:348 model_schedule`、`:393/:394 web_search_provider(_fallback)`、
    `:446 content_video_auto_send`、`:465/:469/:470/:472/:474/:475` video 族、`:507-510` render_forward 四键、
    `:631/:632` 群自动回复两键、`:634/:635` 主动搭话两键、`:637`/`:803` shared_group_context_enabled、
    **`:795` poke 族 9 键整行**。
  - **4 处既不在 SETTABLE 也不在 RESTART**（写入被直接拒）：`:633 group_welcome_enabled`、
    `:662 daily_assist_enabled`、`:664 daily_assist_push_user_ids`、`:795 poke_admin_bypass`。
- **实跑取证**（`probe_c7.py`，真调 `RuntimeSettingsStore.set_override`，tmp 目录不触生产库）：
  ```
  BOT_DAILY_ASSIST_ENABLED    REFUSED -> 不支持运行时修改的键：…
  BOT_POKE_ENABLED            REFUSED -> 不支持运行时热改的键：…（合并表未登记 bot_poke_*，覆盖不可达）
  BOT_GROUP_WELCOME_ENABLED   REFUSED -> 不支持运行时修改的键：…
  BOT_MUSIC_MODE              SET-OK  -> 'card'
  ```
- 误导谁：管理员照目录 `/bot runtime set BOT_POKE_ENABLED true` 调戳一戳被拒、无从判断是 bug 还是设计；
  后续施工席按目录 54 键规划热改面，真实可写面 41、真正落到 config 合并面只有 9。
- **门为什么没响**：`tests/test_doc_sync_gates.py` 5 passed 全绿，但它只查
  "键名是否出现在表格首格"（`_catalog_registered_keys` :306-319）+ 增量键 + TTS 专项，
  **完全不读第 5 列的热更记号、不比对 SETTABLE/RESTART**。⇒ 本条即任务书预警的"门绿文案假"，实锤。
- 修法（§7 R13，结构性）：热更列由 `doc_sync.py` 读三表派生**四态标**
  （可写且合并 / 可写走独立 reader / 拒写须重启 / 拒写且无消费者），或至少补
  `test_catalog_hot_marks_match_settings` 负样本门（§8 G-2）。

### C-2【高危·同文件自相矛盾】`BOT_MUSIC_MODE` 回退值在同册两行互斥
- `docs/config-catalog-full.md:689`：未设置时回退 `BOT_MUSIC_DEFAULT_MODE` = `card+voice+link`；
  `:1058`：同一键"未设置时运行时回退 **`card`**"。
- 真身三处一致支持 :689、否定 :1058：`config.py` `bot_music_default_mode: str = "card+voice+link"`（正则实读原文）、
  `__init__.py:6260` 与 `:8346` 的 `getattr(config,"bot_music_default_mode","card+voice+link")`、`__init__.py:7883`。
- 附证（正向）：`BOT_MUSIC_MODE` 确为**有意的"无 config 字段运行时专属键"**，`probe_c7.py` 实测 `SET-OK`
  且有 4 处活读点 ⇒ **不计死开关缺陷**（本席一度怀疑它是死键，取证后自我推翻）。
- 修法 §7 R14。

### C-3【中·缺面 + 台账叙述反了】决定热改能否生效的其实是**四表**，文档只讲一个
- 四表：`config.py` 字段（633）→ `SETTABLE_KEYS`（41，能不能写）→
  `_RUNTIME_HOT_OVERRIDE_FIELDS`（22，写了能否进合并 config）→ 消费点读法（现读 / 装配快照）。
  任务书列的"五面"里**没有第四表**，`config-catalog-full.md:917` 也只提 SETTABLE。
- `probe_c5.py` 实测：`SETTABLE ∩ HOT` = **9**（quiet_hours 六 + rate_limit 三）；
  `HOT − SETTABLE` = **13** ⇒ **合并表里 13 条永动臂**（`BOT_DAILY_ASSIST_*` 6、`BOT_GROUP_DIGEST_*` 5、
  `BOT_RENDER_FORWARD_MIN_NODES`、`BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY`）：
  `_config_with_runtime_overrides`（`__init__.py:762-793`）每轮判定去 store 读一次，而写入端永远拒绝 ⇒ 读侧空转。
- 与文档冲突（高价值）：`AGENTS.md` 台账 #32 明文"配置 6 键入 config.py+catalog+**SETTABLE**+.env.example"
  ⇒ 实测 6 个 `BOT_DAILY_ASSIST_*` **无一在 SETTABLE_KEYS**，且 `probe_c7.py` 实证写入被拒 ⇒ **台账叙述与代码相反**。
- `SETTABLE − HOT − RESTART` = **32**（可写、不合并、非冻结，靠各自 `store.get_or` 直读，如 `BOT_MUSIC_MODE`
  实证 `music.py:438`）。本席**只抽验 1 键**，余 31 键按「未证实」记账，不卖成缺陷；
  现存最接近真身的账 = `tests/test_settings_hot_audit.py:3`（2026-09-15 逐键消费点复核）。
- 修法 §7 R15 + §8 G-2。

### C-4【中·数字副本失真】字段总数三种口径
- 真身 **633**（我 grep 与 `scripts/doc_sync.py:61-62` 同式互证；机器册 `docs/auto-facts.md` 亦 633）。
- `AGENTS.md:32` 写"`config.py` **529 字段**"，**同句**又写"（bot_* 口径，机器册 `docs/auto-facts.md` 为准）"
  ⇒ 一句话里既钉死数字又承认别人是权威。`AGENTS.md:180` 留"509→529 字段/72→79 topics"史值
  （史值可豁免），topics 那半已由 AGFIX 更正为 77，**字段那半没跟上**。
- 同族：`echo.py:449` "73 topics"（=B-3）。
- 修法 §7 R16。

### C-5【已查·未命中】`KNOWN_MISSING` 假欠账 = **0 项**
`tests/test_doc_sync_gates.py:55` `KNOWN_MISSING: frozenset[str] = frozenset()`（**空集**），
且 `:335/:341` 反向断言 `stale = KNOWN_MISSING - fields - registered` 必须为空
⇒ "白名单里有其实已落库的键"这类假欠账**结构上不可能存在**。如实记 0（不是没查，是查了没有）。

### C-6【正向】五面里做对的部分（要保住）
- 633 键**全部有登记**（用门自带解析器复算，缺失 0；`probe_c.py` 首版报"132 未登记"是**我的假阳性**，
  因未复用 `_normalize_catalog_key` 的 `_xxx→bot_xxx` 归一 ⇒ 已在 §0 方法里作为教训记档）。
- `SETTABLE ∩ RESTART = ∅`（无一键两态）；`tests/test_settings_hot_audit.py:147` 锁"死开关不得留在热改白名单"、
  `:145` 钉 `len(MOVED_TO_RESTART_KEYS)==28`。
- `docs/config-catalog-full.md:849`（`_outbound_gate_max_per_target_per_*`）是**全仓最正确的一条热改文案样板**：
  明写"**勿按字面理解成'写了就生效'**"并点名"合并层 `_RUNTIME_HOT_OVERRIDE_FIELDS` 未登记本族键 ⇒ 写了不生效，
  七键一律入 RESTART_REQUIRED_KEYS"。⇒ C-1/C-3 的修法直接以该行为文字范式（不是发明，是把已有范式铺全册）。

---

## 4. D 文档内坐标与互链有效性

### D-1 全量体检结果（3837 条唯一 `.py:行号`）
| 判据 | 条数 | 占比 | 定性 |
|---|---|---|---|
| 目标文件全库不存在（真死坐标） | 32 | 0.8% | 真缺陷 |
| 行号超出解析到的真身行数 | 54 | 1.4% | 真缺陷 |
| 只能解析到**已退役 Compat 垫片**（3—18 行） | 56 | 1.5% | 真缺陷 |
| 写法为迁移前旧路径（非 `domains/`） | **898** | **23.4%** | 结构性缺陷：仍可 import，但**不是真身** |
| 符号屏幕：所引符号不在所指行 ±8 | 695 | 18.1% | **筛查上限值，不可当缺陷数报**（见 D-3） |
| 上项中能在同文件另定位到该符号 | 235 | — | 确证行号失效（带位移量） |

⇒ 可靠缺陷规模 = 前三行相加 **142 条（3.7%）**，另加 898 条旧路径写法这一结构性大类。

### D-2 确证的行号失效样本（位移 = 实测真身行 − 文档所引行）
| 文档坐标 | 所引 | 真身 | 位移 |
|---|---|---|---|
| `docs/design/file-transfer-gateway.md:186` | `onebot.py:341 _send_file_parts` | `domains/transport/sender/onebot.py:506`（`:341` 现为孤 `)`） | **+165** |
| `docs/design/v21-s0-inventory.md:113` | `__init__.py:1455 _register_send_queue_scheduler` | `:1619` | **+164** |
| `docs/design/v21-s0-inventory.md:118` | `__init__.py:2804 _register_reminder_scheduler` | `:3093` | **+289** |
| `docs/design/llm-billing-ledger.md:150` | `__init__.py:979 _log_runtime_event` | `:1175` | **+196** |
| `docs/design/audit-20260920-unify-U9-function.md:241` | `domains/ops/incident/service.py:739` | 该文件实长 **407 行** | 越界 |
| `docs/design/audit-20260920-unify-U10-gate.md:205` | `__init__.py:3032` | 同文件所引符号实居 `:241` | **−2791** |
| `docs/design/audit-20260920-unify-U11b-sec.md:175` | `runtime_admin.py:1864` | `:46` | **−1818** |

位移横跨 −2791 … +662、**无固定偏移** ⇒ 不能"统一加减常数"批量救，只能逐条按符号重定位。

### D-3 抽样人核推翻的两类假阳性（必须一并交付，否则我的数会被当成"28% 坐标全废"卖）
- `AGENTS.md:188` 引 `__init__.py:5044`：屏幕报"所引 `explicit_allowed_for_session` 不在 ±8 行"。
  **人核推翻**——`sed -n '5040,5046p'` 实为 campus 被动 matcher 体，**坐标正确**；
  那个符号只是同一长行里另一处提及（真身 `domains/chat_reply/runtime/content_route.py:501`）。
  ⇒ 一行多坐标/多符号时，"行内任一反引号词"匹配必假阳。
- `docs/design/tts-audit-20260919.md:93` 引 `TTS.py:1132-1138`：屏幕报"文件不存在"。
  **人核推翻**——同表 `:92` 已给绝对根 `C:/Software/GPT-SoVITS-V2Pro/GPT_SoVITS/TTS_infer_pack/TTS.py`
  并附可复跑 grep，`:93` 只是就近缩写 ⇒ **外部仓坐标带就近全路径即有效，不计缺陷**；
  据此我**撤销了原计划给该文件加"外部仓根"横幅的改动**（避免无谓动刀）。
- 真死坐标里合法的外部类：`nonebot/plugin/load.py`、`nonebot/adapters/telegram/event.py`、
  `executors/asyncio.py`（第三方库内部路径，本就不在工作区）；
  真不可溯类：`.tmp-test\D9\full\test_auto_send_clean_sample_ze0\clean_auto.py`、`\u3_probe_registry.py`
  （TEMP 探针产物，目录已消失）⇒ 归 D-5 豁免规则③处置。

### D-4 跨文档互链（578 条本地 markdown 链接，死链 38 = 6.6%）
- 成因①（系统性，**23 条，未修**）：`docs/design/v21r2-handbook-sync-draft.md:99-121`（11 条）与
  `docs/design/v21r4-b-doc-sync-draft.md:103-112`（12 条）位于 `docs/design/` 却写**以 `docs/` 为基**的
  `design/xxx.md` ⇒ 解析成 `docs/design/design/…` 必死；两文件还各含**一条自指链**。
  同批 `v21r2-agents-ledger-draft.md` 同类写法。⇒ 两件均 `??` 未入库（他席草稿）⇒ §7 R17。
- 成因②（**7 条，本席已直接修好**）：`REVIEW-WORKFLOW.md:112-118` 索引 7 份 `REVIEW-<range>.md`，
  实测 `ls REVIEW-*.md` 仅命中本文件、`git log --all -- "REVIEW-f6f749b..6c57fd9.md"` **零命中**（从未入库）
  ⇒ 死链。修法=降为纯文本 + 写明取证依据 + 复现指引 + 归档规程补条（§6）。
- 成因③（**不计缺陷**）：`.superpowers/**` 会话产物里的正则串被解析器误当链接
  （`[^\\'\"]+`、`?:\/\d{1,3}`、`长度单位`）⇒ 我的探针噪声。
- 正向：`docs/README.md`、`docs/HANDBOOK.md`、`AGENTS.md`、`backend-v2-acceptance-matrix.md` 核心互链零死链；
  "术语说明"横幅一律用相对链接指 `snowluma-setup.md`，是全仓最好的一类互链。

### D-6 小结
真死/越界/垫片型 **142 条（3.7%）** · 旧路径写法 **898 条（23.4%，结构性）** ·
markdown 死链 **38 → 31**（余 23 待落、8 为探针噪声）· 门规格 1 份（§8）。

---

## 5. E 模块归属表

### E-1【高危】`AGENTS.md` 第四部分「功能 × 子模块」表：44 条载体路径，**命中真身 0 条**
- **20 条**只能解析到已退役 Compat 垫片（`capabilities/chat.py`、`character/affinity.py`、`llm/ledger.py`、
  `policy/roles.py`、`runtime/reactions.py`、`sources/campus_store.py` 等）；
  **23 条连垫片都不存在**（已彻底迁走、旧路径不留）：
  `sources/nmc_weather.py`→`domains/weather/data/`、
  `sources/{market_data,stock_data,fx_data,bond_data,commodities_data,market_crosscheck}.py`→`domains/finance/data/`、
  `sources/open_meteo.py`→`domains/weather/data/`、`sources/news_feeds.py`→`domains/subscribe/feeds/`、
  `sources/music_charts.py`→`domains/music/data/`、`sender/file_gateway.py`→`domains/transport/sender/`、
  `runtime/timesync.py`→`domains/schedule/timesync/`、`runtime/error_report.py`→`domains/ops/monitor/`、
  `card_render/templates/error_card.html`→`domains/render/card_render/templates/`；仅 `scripts/fetch_mermaid_js.py` 1 条字面正确。
- 误导谁：这是**每次自动加载进上下文**的表。新接手会话照它读 `sources/market_data.py` ⇒
  "文件不存在"，或读到 3—18 行垫片 ⇒ "这模块就这么点代码"。**任务书点名的"旧路径被当真身引用"，面积=100%。**
- 修法（§7 R18）：**不手改 44 格**——"载体文件"列由 `doc_sync.py` 从 `domains/**` 反查能力入口生成、
  落 `docs/auto-facts.md` 新节「能力→域→真身」，AGENTS 表只留人写的"作用/入口"两列 + 指链。

### E-2【高危】`docs/db-owners.md`（自称"唯一清单权威"）整表停在迁移前布局
- 实测 44 条路径引用 = **真身 2 / 垫片 33 / 旧路径已消失 9**（`audit/logger.py`→`domains/ops/audit/logger.py`、
  `character/persona_service.py`、`character/worldbook_service.py` 等旧路径已无）。
- 权威性（`AGENTS.md` 指它"唯一清单以此文件为准"）与失真度同时最高。
- 冷热：该件 ` M`（脏）⇒ 只出 §落地请求（§7 R19）：加一行时效声明 + **补"现真身"列由脚本回填**（44 行全可程序化，零人工）。

### E-3【中】域数三口径并存 + 新域未进任何归属表
- 实况（`ls plugins/bot_unified_runtime/domains/`）：21 个域目录 + `__init__.py` = 22 项
  （assistant chat_reply core creation divination **emergency_info** files finance food link_parse location
  media meme music notes ops render schedule subscribe transport weather）。
- 副本口径：`AGENTS.md` 顶部"20 域"、台账 #42-B4"14 领域 vs 20 域裁决点"、`v21r4-b-*` 系列沿用 20 ⇒ **20/21/22 三个数并存**。
- `emergency_info`（本波新建）**未进任何归属表**（E-1 表 44 条零命中）。
- 状态区分（不许含糊）：`emergency_info` 域**已落码存在于树**，但
  `docs/design/emergency-info-unify-wave-final-20260920.md:82` 证其 Help/命令面/联动面**零接线**
  ⇒ 归属表若补它必须同时标"未接线"，不得写成现役能力。
- 修法（§7 R20）：域清单亦归生成器（`doc_sync.py` 直接 `ls domains/` 落机器册），文档只指链。

### E-4【正向】垫片机制本身干净、且台账 #45 的运行态更正已被并发改对
- 抽查 `plugins/bot_unified_runtime/capabilities/echo.py`、`runtime/settings.py`：均为规范 PEP 562
  `__getattr__` 活转发（662—673 字节，`_CANONICAL` 指名真身）⇒ **旧路径 import 仍可得正确对象**，
  缺陷只在"文档把旧路径当真身写行号"，**无运行期语义分叉**。
- 现存垫片总数 `grep -rl "Compat shim" --include="*.py" plugins/` = **158**
  （EP1 盘点 2026-09-18 为 275 张 ⇒ 退役波已消化 117）⇒ 与 `v21r2-shim-retirement-inventory.md` 施工图可对接，未失控。
- **本席一次"结论被实时推翻"的如实记录**：04:0x 我读到 `AGENTS.md` #45 写"生产 bot 实例 PID 14920 /
  start=2026-09-20 01:08:14"，与我的独立测量冲突，拟列高危；04:2x 复查 `grep -rn "14920" --include="*.md"`
  已**零命中**（他席在审计期间自行更正）⇒ **该条撤回**，只保留一般性建议（§7 R21）：
  **运行态事实（PID / 启动时刻 / 在线与否）一律不得写进长期文档**，只准写"复跑命令"。
  理由：本席两次读 AGENTS.md 内容不同，同一分钟内 PID 已不存在（`Get-Process -Id 14920` 空返回）。
- 但同一族里**仍有一条活的失真**（本席独立测量、非引用他席）：
  `AGENTS.md:156` 台账 #10 至今写"生产 bot 未重启…**等用户提权重启**"，
  而只读测量 `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 显示
  **PID 52272（`ChatBot_Runtime\venv\Scripts\python.exe bot.py`）创建于 2026-09-19 23:38:29、仍在岗**，
  其子 58780 `ParentProcessId=52272`（Windows venv trampoline 父子对 ⇒ **单实例，不是"双 bot 并存"**，
  本席一度误判后自纠）。⇒ #10 所称"未重启"对 2026-09-19 23:38 之后的进程为假，
  该横幅下大量"重启生效"记账需**逐批重判**（哪些已被 23:38 那次重启吃进、哪些仍待下一次重启）。
  修法 §7 R22。**注意：这不属于本席的施工范围，是否重启由用户裁定。**

---

## 6. 已直接修好的（冷面，逐处自证）

判据：`git status --porcelain <file>` 空 **且** mtime > 30 分钟。改前后各跑一次 `git diff --numstat`。

| 文件 | 改前 numstat | 改后 numstat | 改动 |
|---|---|---|---|
| `REVIEW-WORKFLOW.md` | （空=未触碰） | `16 11` | §8 报告索引 7 条死链降为纯文本 + 写明"从未入库"取证依据（`git log --all` 零命中）+ 复现指引 + 归档规程补条"归档必须落可解析路径，否则不留死链" |
| `docs/design/control-plane-api.md` | （空） | `14 0` | 头注加"坐标时效声明"：旧路径行号失效实证举例（`sender/queue.py:…`→3 行垫片）+ 4 条现行指针 + "按符号检索"姿势 + 明确哪些节仍有效 |
| `docs/design/llm-billing-ledger.md` | （空） | `12 0` | 同款声明，带实测位移（`__init__.py:979`→`:1175`）与现行真身路径（`domains/chat_reply/llm_engine/ledger.py`，`ls` 实证存在） |

复跑验证：`%TEMP%/link-audit/probe_links.py` → 本地链接 577→578、**死链 38→31**，`REVIEW-WORKFLOW.md` 从死链榜消失。
`git status --porcelain | wc -l` 改前 970 / 改后 971（**净增 1 = 本席两份交付物**，其余文件零触碰）。
树卫生自查：`ls -d data .pytest_cache .ruff_cache .mypy_cache` 全部不存在、
`git status --porcelain | grep '^?? data/'` = 0、无新建 `__pycache__`；全部实跑带
`PYTHONDONTWRITEBYTECODE=1`、pytest 带 `-p no:cacheprovider --basetemp="$TEMP/link-audit"`。

**本席主动放弃的一处改动**（记录理由，避免下游以为漏做）：
原拟给 `docs/design/tts-audit-20260919.md` 加"外部仓根"横幅，人核 `:92` 后判**不需要**
（就近行已给绝对根 + 可复跑命令）⇒ 不改。见 D-3。

---

## 7. §落地请求（热面 / 生成物，diff 级原文）

> 责任面标注：**[C]** = 代码改动（需该域 owner 施工 + 跑门禁）；**[D]** = 文档正文；
> **[G]** = 生成物重录请求（**不许手改**，只能跑 `--write`）。

### R1 [C] `plugins/bot_unified_runtime/control_plane/api/v1.py:187` — 消灭手抄枚举
```diff
-            return _ok({"items": ["bot", "nonebot", "napcat", "control_plane", "decision_engine", "pipeline", "sender", "llm", "database", "scheduler"]})
+            # 事件源枚举单一真身：domains/ops/monitor/event_store.py::EVENT_SOURCES
+            # （合同 §8 的 12 项）。此处禁止再写字面量清单——历史上漏过 telegram/mail 两项。
+            from plugins.bot_unified_runtime.domains.ops.monitor.event_store import EVENT_SOURCES
+
+            return _ok({"items": list(EVENT_SOURCES)})
```
验收：`GET /api/v1/logs/sources` 的 items 从 10 → 12；
`tests/` 内该端点断言若钉死 10 项须一并更新（**归属控制面席**）。
注：`v1.py` 当前为 `??` 未入库件，本席不碰无基线文件。

### R2 [D] `docs/design/control-plane-events.md:59` — 14 项手抄改指链
```diff
-来源：bot、nonebot、napcat、telegram、mail、control_plane、decision_engine、pipeline、sender、llm、database、scheduler、capability、renderer。
+来源枚举的唯一真身＝`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py` 的 `EVENT_SOURCES`
+（V2.1 合同 §8 收敛为 **12 项**，合同文字面见 [backend-v2-implementation-guide.md](backend-v2-implementation-guide.md) §8）。
+**本文不重列成员**——重列必过期。存量实现 `control_plane/events.py` 另多两枚历史码
+（`capability`、`renderer`），其收敛排期归接线席，差异取证见 `docs/design/v21-s5-events-log.md`。
```

### R3 [C] `plugins/bot_unified_runtime/control_plane/events.py:42-56` — 存量 14 项加"谁是权威"指针
```diff
 # 存量控制面诊断层的事件源。
+# ⚠ 权威枚举 = domains/ops/monitor/event_store.py::EVENT_SOURCES（V2.1 合同 §8，12 项）。
+#   本表多出的 capability/renderer 是历史遗留，新代码不得再依赖；
+#   二者关系与收敛计划见 docs/design/v21-s5-events-log.md 与
+#   docs/design/control-plane-events.md（该文档 2026-09-20 起改为指链，不再重列成员）。
 EVENT_SOURCES = (
```

### R4 [D] `docs/design/tts-contract-layer.md:68`（P2 行）— 8 码断言已对 HEAD 为假
```diff
-| P2 | SnowLuma | `1400`（消息校验失败：record 缺 file/url、未知段类型、字段非标量）与 `100`（动作失败）**不在**现行 `_is_final_failure_retcode={403,404,1003,1200,1201,1401,1403,1404}` 白名单 | 毒语音会白烧 3 轮 | **T46-N1 施工在 H 波**；修法=按平台版本声明 retcode 集（读本表），`domains/transport/sender/onebot.py:119-122/:174` 的 `_ONEBOT_API_UNAVAILABLE_RETCODE=1200` 语义漂移同批改判 |
+| P2 | SnowLuma | `1400`（消息校验失败）与 `100`（动作失败）**曾不在**白名单；**2026-09-20 已由 T46-N1 扩码入列** ⇒ 本行原判据作废 | 原判"毒语音白烧 3 轮"已闭合，勿重复施工 | 白名单**成员集与行号一律不在本文维护**：真身＝`domains/transport/sender/onebot.py` 的 `_is_final_failure_retcode`（建议提为具名常量以便指符号）；`_ONEBOT_API_UNAVAILABLE_RETCODE=1200` 的语义漂移改判仍归 H 波 |
```

### R5 [D] `docs/design/tts-handover-20260919.md:198` — "未开工"为假
```diff
-A 案最小改造面+T46-N1 retcode 白名单扩面（1400 先行）归 **Wave H**（已授权未开工，T65 先遣件备料中）
+A 案最小改造面归 **Wave H**（在飞）；T46-N1 retcode 白名单扩面 **已落地入库**
+（`domains/transport/sender/onebot.py` `_is_final_failure_retcode`，含 100 与 1400；
+ `git show HEAD` 同值、该文件工作树干净＝已入库，非仅落码）。本句 2026-09-20 由 LINK-AUDIT 席更正。
```

### R6 [D] `AGENTS.md:189`（#44 ⑧）与 `docs/HANDBOOK.md:2389`（§35 ④）— 删数字副本
```diff
-T55 传输层取证（喂 H 波）：M-63 根因链钉死、「9」=断连形态限定（纯超时=3）、T46-N1 白名单实集 8 码、
+T55 传输层取证（喂 H 波）：M-63 根因链钉死、「9」=断连形态限定（纯超时=3）、
+T46-N1 retcode 白名单（**成员数不在文档维护**：真身＝`domains/transport/sender/onebot.py::_is_final_failure_retcode`；
+2026-09-20 复核＝该扩面已入库，本文旧记「8 码」作废），
```

### R7 [D] `AGENTS.md:129` 校园行 — 协议端口径与横幅位置
```diff
-| 校园自动转发 | … | 学校号（2300230562，NapCat-school 第二实例 WS 3002）…
+| 校园自动转发 | …（载体文件列的现真身待 R18 生成化，本列暂不改）… | 学校号（2300230562，
+第二实例 WS 3002；采集侧曾名 NapCat-school，现归档件内名见下）…
```
并把 `AGENTS.md:201` 的"术语说明"横幅**同时复制到第一部分顶部**（现仅文末，读者先撞上正文旧口径）。

### R8 [D] `plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py:232` — 自相矛盾措辞
```diff
-        "NapCat 实测验证（A1/风险5 清单未取证，如实标注待验证）",
+        "登记为待验证：A1/风险5 清单未取证；旧协议端时代的实测不外推到 SnowLuma（见 docs/snowluma-setup.md）",
```
理由：原文既称"实测验证"又称"未取证"，读者无法判断该不该信。语义不变、只把结论摆正。

### R9 [G] 生成物重录请求 —— `docs/auto-facts.md` 增设两节，替掉手写计数与清单
```
请 doc_sync 席在 scripts/doc_sync.py 增两段落 --write 输出：
  ①「能力 → 域 → 真身」：遍历 domains/**，输出每个 capability 入口文件的现路径（替 R18/R19 的手写列）
  ②「协议端口径残留清单」：输出 grep NapCat|napcat 命中且首 8 行无「术语说明」横幅的 .md 列表
    （回答“还差哪些”，现在全仓无权威计数：.md 224 行 / .py 140 行 / 另一席按文件计 101）
现值参考（本席 2026-09-20 04:0x 实跑）：帮助 topic 77 / config.py bot_* 字段 633 /
SETTABLE 41 / RESTART 54 / HOT 22 / 现存 Compat 垫片 158。
```

### R10 [C] `domains/chat_reply/capabilities/echo.py` — 参数说明单份化 + 注释计数
```diff
-# 增删主题 / 翻转可见性 / 改能力入口，必须同步声明源（73 topics 口径不变）。
+# 增删主题 / 翻转可见性 / 改能力入口，必须同步声明源。
+# topic 总数**不在本注释维护**：权威＝docs/auto-facts.md（由 scripts/doc_sync.py 生成），
+# 或本地复跑 python scripts/command_catalog.py --check 的输出行。
```
```diff
-                '修改方式：以上全部支持 /bot runtime set 热改，立即生效（接话总开关 ENABLED 装配期读取，改后需重启）。',
+                '修改方式：逐键以 /bot runtime set 的实际裁决为准——可写面＝settings.SETTABLE_KEYS，'
+                '被拒并提示需重启的键列在 settings.RESTART_REQUIRED_KEYS（含 BOT_GROUP_CHAT_AUTO_REPLY_ENABLED '
+                '与 _PROBABILITY 两键，两者装配期烘进策略快照，覆盖不被读取）。本文不重列白名单成员。',
```
**参数双份的根治**（B-1，需 echo 域 owner 施工）：`detail` 的【指令与参数】段由 `lines` 派生而非手写，
照 `echo.py:3204-3205` 已有的 `_HELP_EXTRA_LINES` 双写姿势改成"单写 + 派生"。
⚠ 该件在 `tests/verify_hashes.py` 哈希清单内（`docs/auto-facts.md` 第 37 行列出），
改完必须 `--write` 重录哈希，否则哈希门先红。

### R11 [D] `COMMANDS.md:14` — 幻影命令必须显式标注
```diff
-| 决策影子 | `/bot decision [N]`（别名 `决策`/`决策引擎`/`decision`，昵称形式等价） | 查看影子决策引擎的路由分歧痕迹 | N：条数可选，1-100 默认 20；… |
+| 决策影子 | `/bot decision [N]` —— **⚠ 未接线：发出去坠 /bot help 兜底页，不是执行** |
+  实现体 `build_decision_query_result` 与参数（1-100 默认 20）齐备、`_parse_decision_limit` 已钳制，
+  但 `__init__.py` dispatch elif 链无 `decision` 分支（取证见
+  `docs/design/audit-20260920-unify-U7-command.md:230` U7-F7）；接线一行分支前，本命令**不可用** |
+  接线后恢复登记；缺省与上限一律指 `_DECISION_QUERY_DEFAULT_LIMIT`/`_MAX`，不在此抄数值 |
```
配套：给 `tests/test_documentation_consistency.py` 增一条"COMMANDS.md 登记的每条 `/bot x` 必须能在
dispatch elif 链或 alias-elif 链找到消费者"的门（规格 §8 G-3）。

### R12 [D] `COMMANDS.md:53` 末句 — 删未证实的全称断言
```diff
-；全部热改即时生效 |
+；可写面与拒写面以 `/bot runtime get`（列白名单）与 settings 两表为准，本文不重列键 |
```

### R13 [D] `docs/config-catalog-full.md:917-918` — 67 → 真身 41，并停止手抄计数
```diff
-1. **白名单与转换器**：只有 `SETTABLE_KEYS` 中的键可热更（防止任意配置注入）。共 **67 键**（66 个对应 config.py 字段 + `BOT_MUSIC_MODE` 运行时专属键；2026-09-13 按 `runtime/settings.py` SETTABLE_KEYS 实况全量校准，此前「23 键」为严重过期计数）。非白名单键 `set_override` 直接拒绝并提示可用键。
-2. **可热更键全表**（67 键 → 转换规则，按功能域分组）：
+1. **白名单与转换器**：只有 `SETTABLE_KEYS` 中的键可热更（防止任意配置注入）。
+   **成员数不在本文维护**：真身＝`domains/chat_reply/runtime/settings.py` 的 `SETTABLE_KEYS`；
+   LINK-AUDIT 席 2026-09-20 AST 复核实测 **41 键**（旧记「67 键」系 C-09 治理把 28 键移入
+   `RESTART_REQUIRED_KEYS` 之前的数，未随之回标）。非白名单键 `set_override` 直接拒绝并提示可用键。
+2. **可热更键全表**（→ 转换规则，按功能域分组；**本表若与 `SETTABLE_KEYS` 不符，以代码为准并提请重录**）：
```
**并**：C-1 列出的 **32 处「✅热更」勾**需逐行回标（清单见本报告 §C-1，全量重跑件
`%TEMP%/link-audit/probe_c6.py` 可打印行号）。建议不手点——由 `doc_sync.py` 派生四态标一次到位（§8 G-2）。

### R14 [D] `docs/config-catalog-full.md:1058` — 同册两行互斥，删假的那半
```diff
-**E4 热更层特有**：`BOT_MUSIC_MODE` 只存在于 `SETTABLE_KEYS`（config.py 无字段），未设置时运行时回退 `card`；
+**E4 热更层特有**：`BOT_MUSIC_MODE` 只存在于 `SETTABLE_KEYS`（config.py 无字段），
+未设置时运行时回退 `BOT_MUSIC_DEFAULT_MODE`＝`card+voice+link`（真身＝`config.py`
+`bot_music_default_mode`，消费点 `__init__.py:6260`/`:8346`；本行旧写「回退 card」为假，与同册 :689 互斥，
+2026-09-20 LINK-AUDIT 更正）；
```

### R15 [C] `__init__.py:733 _RUNTIME_HOT_OVERRIDE_FIELDS` — 13 条永动臂要么接线要么摘除
```
现状：HOT(22) − SETTABLE(41) = 13 键被 _config_with_runtime_overrides 每轮判定读取，
      而写入端一律拒绝 ⇒ 读侧空转（行为无损，语义死码）。
处置二选一（不得两不沾）：
  a) 把 13 键并入 SETTABLE_KEYS 并逐键验证消费点现读（则须同步摘出 RESTART_REQUIRED_KEYS 的相关条目）；
  b) 从 _RUNTIME_HOT_OVERRIDE_FIELDS 摘掉这 13 条，并加断言
     set(HOT) - set(SETTABLE) == 0（否则红），防再长。
禁止：只在 catalog 里把勾改了之——那正是 C-1 的成因。
```

### R16 [D] `AGENTS.md:32` — 删硬编码字段数（同句已承认别人是权威）
```diff
-- **主包**：`plugins/bot_unified_runtime/`；`config.py` 529 字段（bot_* 口径，机器册 `docs/auto-facts.md` 为准）全 pydantic；
+- **主包**：`plugins/bot_unified_runtime/`；`config.py` 全 pydantic，
+  **bot_* 字段数一律不在此手写**——真身见机器册 [docs/auto-facts.md](docs/auto-facts.md)
+  （由 `python scripts/doc_sync.py --write` 生成，`--check` 漂移即红）；
```
（同理 `AGENTS.md` 顶部与正文中一切"N 字段 / N topics / N 域 / N 码 / N 处残留"型数字，见 R9/R20。）

### R17 [D] 两份草稿的相对链基目录错（23 条死链，一次 sed 级可修）
```
docs/design/v21r2-handbook-sync-draft.md:99-121 与 docs/design/v21r4-b-doc-sync-draft.md:103-112：
  这两份文件**位于 docs/design/**，链接却写成以 docs/ 为基的 `design/xxx.md`
  ⇒ 解析为 docs/design/design/xxx.md，23 条全死。
改法：去掉 `design/` 前缀改同级（`design/v21r2-command-spec.md` → `v21r2-command-spec.md`）；
      两条**自指链**（…/v21r2-handbook-sync-draft.md、…/v21r4-b-doc-sync-draft.md 指向自己）改纯文本；
      `docs/design/v21r2-handbook-sync-draft.md:99` 的 `../V21-UPDATE-LOG.md` 目标不存在，改指
      `../../HANDOFF-V21R4-20260918.md` 或删除。
注：两件均为 `??` 未入库（他席草稿，无还原基线）⇒ 请草稿 owner 自己改，本席不动无基线文件。
```

### R18 [G]+[D] `AGENTS.md` 第四部分「载体文件」列 → 生成化（E-1，44/44 不指真身）
```
不手改表格。做法：
  ① scripts/doc_sync.py 增「能力 → 域 → 真身」节（R9①），输出每个能力入口的 domains/ 现路径；
  ② AGENTS.md 第四部分「载体文件」列整列替换为一句指链：
     「本表『载体文件』列已于 2026-09-20 移除——路径随 v21r2 域重组漂移且旧路径多为垫片，
       现行真身见 docs/auto-facts.md『能力→域→真身』节（勿手抄）。」
     人写的「子模块/作用」「入口」两列保留。
  ③ 过渡期允许的最小改动：仅把 :129 等行的旧路径加 `(已迁: domains/<域>/…)` 括注，
     但**优先做 ①②**，否则 44 格改动本身就是一次新的大面积手抄。
```

### R19 [D]+[G] `docs/db-owners.md` — 时效声明 + 「现真身」列脚本回填
```
表头（:1-9 之后）加一行：
> **路径时效（2026-09-20）**：本表「Owner 模块」列为 2026-09-12 取证时布局（实测 44 条引用中
> 真身 2 / 垫片 33 / 旧路径已消失 9）。现行真身以 docs/auto-facts.md「能力→域→真身」节为准；
> 本表补「现真身」列由脚本回填，**不许人工逐行改**（改一次错一次）。
```

### R20 [D] 域数口径统一（E-3）
```
AGENTS.md 顶部横幅「板块重组 20 域」、正文各处、docs/design/v21r4-b-* 系列：
  统一改为「域数不在文档维护，真身见 docs/auto-facts.md（domains/ 目录实测）」。
补登 emergency_info 域时必须同时标注：**已落码存在于树、Help/命令/联动面零接线**
  （取证 docs/design/emergency-info-unify-wave-final-20260920.md:82），不得写成现役能力。
```

### R21 [D] 一般性规矩：运行态事实禁止写进长期文档
```
禁止在 AGENTS.md / HANDBOOK.md / docs/** 写 PID、进程启动时刻、"当前在线"之类会过期的运行态断言。
允许的形态只有：可复跑命令（如
  powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\""）
＋ 该命令的取证时间戳。
依据：本席 04:0x 读到 AGENTS.md #45 的 PID 14920/01:08:14，04:2x 复查全 md 零命中且该 PID 已不存在；
     同分钟内我测到的在岗进程是 PID 52272（2026-09-19 23:38:29 起）。写死即失真。
```

### R22 [D] `AGENTS.md:156` 台账 #10 —— 被本席独立测量证伪的现行断言
```diff
-| 10 | 生产 bot 未重启——a9d1222 批次（…）+ 2026-09-13 全域审计批次（…）全部待生效 | **等用户提权重启** |
+| 10 | 生产 bot **已于 2026-09-19 23:38:29 重启过一次**（LINK-AUDIT 只读测量：PID 52272，
+  `ChatBot_Runtime\venv\Scripts\python.exe bot.py`，子 58780 父=52272 系 Windows venv trampoline
+  父子对 ⇒ **单实例**）⇒ 本行旧记"未重启"作废。但 09-19 23:38 之后的各批（含 v21r5 三任务批、
+  Wave G/H 后段席位）**仍未生效**。逐批重判生效面＝各批自己的责任，重启窗口由用户裁定。 | **部分已生效；余待下一次重启** |
```
⚠ 本席**不建议**据此改动任何生产行为，只更正记账。

---

## 8. 常驻检查门规格（防再犯，含豁免设计）

> 只给规格不实现。四道门，全部纯静态（零 import 插件包，照 `scripts/command_catalog.py:3` 纪律）。

### G-1 `tests/test_doc_coordinate_links.py` —— 坐标与互链有效性
- 检四件事（解析器**必须**用 `probe_d6.py` 那套规则：全库 basename 索引 + 行容量优先 + 垫片单列；
  本席踩过两次假阳性，见 D-3）：
  1. 文件可解析（不可解析即红）；
  2. 行容量（`所引行 ≤ 目标文件行数`，越界即红）；
  3. 旧路径**棘轮**（只许降不许升，基线 `tests/data/doc-oldpath-ratchet.json`；现存 898 条，
     一刀切硬零必红到无法合流）；
  4. 符号就近 ⇒ **warn-only 不红**（一行多坐标必假阳，见 D-3 的 AGENTS.md:188 反例）。
- markdown 相对链接：非 http/mailto/# 的目标必须存在 ⇒ 硬红（无豁免必要，本席实测死链全是可修类）。
- **豁免设计** `tests/data/doc-coordinate-exempt.txt`，逐条 `文件 + 理由 + 出处`，四类：
  ① 史实件（`AGENTS.md` 第六部分台账行、`HANDBOOK.md` 总账节、`*-log.md`、`audit-*.md`、
     `nightly-ops-report-*`、`handover-c-*`）——判定辅助锚＝该行含日期戳/提交哈希/「已入库」字样；
  ② 外部仓坐标（`C:/Software/…`，或同表块 5 行内已给绝对根的裸文件名缩写 ⇒ 即 D-3 的 `TTS.py:1132`）；
  ③ 一次性 TEMP 产物（`.tmp-test/…`、`%TEMP%/…`）⇒ 要求就近写"已失效，仅存取证记录"，有字样豁免、无则红；
  ④ 非源码坐标（表名、`data/` 运行时路径、`.md` 引用）先过滤。
  反向锁：豁免条目若不再命中任何坐标 ⇒ 红（"过期豁免须摘除"，照 `test_doc_sync_gates.py:341` 姿势）。
- 失败消息必须打 `文档:行 -> 解析到:目标:行 (所引符号真身:行)`，让人不必重跑探针就能修。

### G-2 `tests/test_config_hot_reclaim_consistency.py` —— 配置四表与目录文案对齐（治 C-1/C-3）
- 断言 A：catalog 第 5 列打「✅热更」的每个键 ⇒ 必须 ∈ `SETTABLE_KEYS`；否则红并打行号。
  （本席实测当前应有 **32 条红**。双向自测：内嵌一个"在 SETTABLE 却没打勾"与一个"打勾但不在 SETTABLE"
  的伪键，确认两个方向都抓得住——照 `test_doc_sync_gates.py:368-369` 的负样本自检姿势。）
- 断言 B：`set(RESTART_REQUIRED_KEYS) ∩ set(SETTABLE_KEYS) == ∅`（现成立，钉住防退化）。
- 断言 C：`set(_RUNTIME_HOT_OVERRIDE_FIELDS) - set(SETTABLE_KEYS)` 必须 ⊆ 一份显式豁免清单
  （现状 13 条 ⇒ 要么接线要么摘除，见 R15；不许长期挂账）。
- 断言 D：**数字去手抄门**——`AGENTS.md`/`COMMANDS.md`/`docs/config-catalog-full.md` 正文里
  出现 `共 N 键`/`N 字段`/`N topics`/`N 码`/`N 处残留` 形态且与 `docs/auto-facts.md` 生成值不等 ⇒ 红
  （现值：633 字段 / 77 topics / SETTABLE 41 / HOT 22 / 垫片 158；本席已证 529、67、73、"8 码" 四处失真）。
- 断言 E（实跑型，可选，慢）：对断言 A 的每个红键真调一次 `RuntimeSettingsStore.set_override` 到 tmp_path，
  用**异常/成功**作为文案对错的裁判（本席已用该方法把"文档 vs 代码"从口证升级为实跑证）。

### G-3 `tests/test_command_surface_reachability.py` —— 命令可达性门（治 B-2）
- 从 `_HELP_ENTRIES` 与 `COMMANDS.md` 各抽 `/bot <verb>` 形态词，
  断言每个 verb ∈ (dispatch elif 链 verb 集) ∪ (alias-elif 链 capability 集)，否则红并列缺口。
  （U7 席验算的当前缺口集：`{bot.decision, bot.memory, bot.config, bot.readiness, bot.persona,
  bot.roles, bot.history, bot.control}`，其中仅 `bot.decision` 两头全死 ⇒ 首版按**棘轮**上，
  基线钉死现存缺口，只拦新增。）
- 补 `COMMANDS.md` 参数一致性：参数列里出现的 `<必填>` 标记与 `1-N`/`默认 M` 范围串，
  必须能在 `docs/command-catalog.md` 命中 ⇒ 否则红（治"人读件无参数门"）。

### G-4 生成物侧（配合 R9/R18/R19/R20，一次做完四个"数字与清单"的收口）
`scripts/doc_sync.py` 新增段落并 `--write`：能力→域→真身、协议端口径残留清单、域数、
SETTABLE/RESTART/HOT 三表成员数。**新增节须同步进 `verify_hashes` 的产物一致性判据**，
避免"机器册长两行 → 哈希门红"的循环阻塞（本波已发生过一次 hash 被 autosync 抢录）。

---

## 9. 我没查的（诚实缺口）

1. **`domains/render/**`、`domains/chat_reply/**` 的代码级重复实现**（六份"挑变体"API、
   触发词六副本一类）**未查**——本席判其为另一条正交审计线（OUTBOUND-COPY / T59 已做过触发词那一份），
   且这两块此刻是热面，读码结论落地即过期。
2. **32 条 `SETTABLE − HOT − RESTART` 键是否都有活读点**：只抽验 `BOT_MUSIC_MODE` 一条。
   余 31 条按「未证实」记账，不当缺陷卖。最接近真身的现存账 = `tests/test_settings_hot_audit.py`（2026-09-15 逐键复核）。
3. **695 条符号屏幕命中项未逐条人核**：只核了抽样里的 6 条（结论：≥2 条为假阳性 ⇒ 该类计数不可外推）。
   可靠缺陷数只取 D-1 前三行的 142。
4. **`.superpowers/**`、`docs/design/audit-*.md`、`*-log.md` 等会话产物**：仅纳入坐标普查（结果已按史实件
   分类处置），未要求其文案与今日真身一致——那是故意豁免，见 G-1 豁免①。
5. **`.env` 与 `.env.prod` 的生产实值**：未读值、未比对（纪律：值不外泄；只写键名与存在性）。
   ⇒ catalog「默认值」列 vs **生产实值** 的对齐面**未查**。
6. **OpenAPI 面**（控制面 `/api/v1/openapi.json` 的 opId/路径 与 `docs/design/control-plane-api.md` 的端点表）：
   未做双向 diff；只查了 `api/v1.py` 的枚举手抄这一条。RK5 席记过 OpID 清零，我没复核。
7. **OneBot V11 事件侧字段**（`message_sent`/`group_increase` 等 notice 族的字段面）未审——
   本席 A 面只覆盖**段类型/retcode/事件源枚举**三点。
8. **前端 WebUI（若有独立目录）与 docs/design/F2-\* 契约件的参数对齐**：未查，属前端域。
9. **卡片模板 DOM 与渲染契约的"内容级"归一**：未查（渲染域此刻为热面），
   仅确认 `docs/rendering-contract.md` 与 `DESIGN-SPEC.md` 在 `verify_hashes` 清单内（有门）。
10. **本席自己的 200 抽样与 3837 全量口径差异**：抽样用于人工核性质、全量用于计数；
    两者不可混用。下游若引用，请引 D-1 表 + D-3 修正，不要引 `probe_d.py`/`d4`/`d5` 的中间数。

---

## 10. DOC-FIX-2 落地回执 + 热面待落档（2026-09-20 追加，不重排上文）

追加席：DOC-FIX-2（执行尾段）。冷热判据一律实测：`ls -l --time-style=+%H:%M:%S` +
`git status --porcelain <f>`，测量时刻 = 本机 05:06–05:20 之间。

### 10.1 已吃掉（冷面，逐处自证）

| 请求 | 文件 | 冷热实测 | 改动 | 自证 |
|---|---|---|---|---|
| R19 [D] | `docs/db-owners.md` | mtime 03:27:21（>90 分钟无人在写），状态 ` M`（7/0，系 v21r5 波未提交存量）| 表头后加「路径时效声明」块：认库名与 owner 语义、路径按符号名现查真身、**不许人工逐行改路径列**、指常驻门 `tests/test_doc_link_integrity.py`。**故意不写条数**（数字副本正是本审计的病），计数由门实测 | `git diff --numstat` 由 `7 0` → `18 0`（净增 11 行，全部在我那段） |
| R11 [D] | `COMMANDS.md:23` | clean、mtime 04:00:32（>60 分钟）| 「决策影子」行改写：显式标 **当前不可用（未接线）**、给复跑取证命令、参数缺省改指符号 `_DECISION_QUERY_DEFAULT_LIMIT`/`_DECISION_QUERY_MAX_LIMIT` 不再抄数值 | 本席复核证据链：`grep -rn '"decision"' plugins/bot_unified_runtime/__init__.py` 零分发分支（同族 `"receipt"` 分支在 `__init__.py:6645` 对照）；`grep -rn build_decision_query_result plugins/` 除定义外零消费者（仅 `tests/test_decision_trace_persistence.py` 引用）；`runtime/aliases.py:188` 只登记别名 ⇒ 解析层可达、执行层无落点，与 §B-2 一致 |
| R12 [D] | `COMMANDS.md:53` | 同上 | 删「全部热改即时生效」全称断言，改指 `settings.SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` + `/bot runtime get` | 同上 numstat：`2 2` |

### 10.2 热面 / 无基线 / 归属他席：不改，登记「何时可改」判据

| 请求 | 面 | 实测状态 | 何时可改（判据） |
|---|---|---|---|
| R4 R5 | `docs/design/tts-contract-layer.md`（04:58 ` M`）、`tts-handover-20260919.md`（05:06 ` M`）| **已被 CATALOG-FIX 席就地做掉**（现文已删成员清单、改指 `_is_final_failure_retcode`，并落四态口径）⇒ 本席不再动，避免同面撞车 | 已闭环；防再漂＝新门 `test_protocol_enum_*` 接管 |
| R6 | `AGENTS.md:189`、`docs/HANDBOOK.md:2390`（均 04:50/04:51 ` M`）| 「白名单 8 码」数字副本仍在 | 两席写完、mtime 静默 >30 分钟且 `git status` 无新增时，按 §7 R6 原文改；改后 `tests/test_doc_link_integrity.py` 的 `retcode 计数副本` 判据自动盯住（史实行含哈希者走豁免，勿指望门去喊这两行） |
| R7 R16 R20 R22 | `AGENTS.md`（04:50 ` M`，每次会话自动载入）| 未动 | 同上：**冷判据** = mtime >30 分钟 + 状态无变化；R20 的域数、R22 的运行态断言建议与 R9/R18 生成化同一批落，避免二次手抄 |
| R2 R3 | `docs/design/control-plane-events.md`（`??` 未跟踪，无基线）、`control_plane/events.py` | 未动（本仓纪律：untracked 件还原不可自证）| 该文档入库（`git add`）后即成棘轮面；届时把 :59 改指链，门侧 `collect_enum_copies(skip_inflight=True)` 会立刻验出副本归零 |
| R1 R8 R10 R13 R14 R15 | 生产代码面（`control_plane/api/v1.py`、`domains/core/decision/outbound_registry.py`、`echo.py`、`config-catalog-full.md`、根 `__init__.py`）| 全部**未动**——简报禁「改生产代码配文档」，且 HELP-1/CATALOG-FIX/LOCK-FIX-2 已占面 | 各 owner 席施工；`v1.py:187` 手抄枚举现由新门的 `test_inflight_wave_docs_do_not_explode` 间接可见（该件 untracked） |
| R9 R18 R19[G] R21 | 生成物 `docs/auto-facts.md` / `scripts/doc_sync.py` | 未动（生成物禁手改、禁 `--write`）| doc_sync 席执行；G-4 落地后 AGENTS 载体列与 db-owners 真身列改指生成节，本席棘轮基线随之下调（只降不升，属预期） |
| R17 | `docs/design/v21r2-handbook-sync-draft.md`、`v21r4-b-doc-sync-draft.md`（`??`）| 未动（他席草稿、无基线）| 草稿 owner 自行去 `design/` 前缀；入库瞬间这些死链从「在飞上限档」落进 `_BASELINE_MD_DEAD_LINKS = 2` 的硬棘轮 ⇒ 届时必须一并修 |

### 10.3 本席新增的常驻门（§8 规格的落地态）

`tests/test_doc_link_integrity.py`，17 例全绿、ruff/mypy 净、纯静态（零 import 插件包）。

- **G-1 落地**：坐标四类（死坐标硬零限 `AGENTS.md`/`COMMANDS.md` + 其余棘轮 123 / 越界 3 /
  垫片 3 / 旧路径 837）+ markdown 死链棘轮 2。豁免**双机制**：文件级史实件类 + 行级日期锚
  （含日期戳/提交哈希/「已入库·旧口径·勘误·作废」字样），外加**显式条目清单**（现 1 条，
  带理由），并由 `test_exemptions_are_all_still_needed` 反向锁死过期豁免。
  未跟踪件（他席在飞草稿）单列上限档 `167`，**入库即自动落进棘轮/硬零** ⇒ 在飞脏账带不进史实。
- **G-2 部分落地（协议面）**：真身从源码解析（`_is_final_failure_retcode` 10 码、
  `event_store.EVENT_SOURCES` 12 项）；**非等值副本硬零**、等值副本棘轮（已跟踪件现为 0）、
  数字副本「N 码」比对亦红。**段类型族（§A-5）判为不可立门**——全仓无中央真身、
  同名两套成员（审计本身亦「不开必须合并的处方」），故不硬凑一条会误伤的断言。
- **G-3/E-1 落地为归属表子门**：`AGENTS.md` 第四部分载体列四档判定
  （字面真身 5 / 垫片 35 / 旧路径 15 / 彻底失效 0），dead 走硬零、误导面 50 走棘轮、
  字面真身设**地板**（不得低于开工实测 5 条）⇒ 该列只会越改越真，不会整体失真回潮。
- **防假锁**：三条负样本（假坐标 / 假 retcode 副本 / 假载体行）内嵌自检；
  另做**真文件变异自证**（`docs/db-owners.md` 追加三行做坏 ⇒ 5 条断言同时红，
  报错逐条给 `文档:行 -> 所引 / 漂移成员 / 修法`；还原 `cp` 二进制通道 + `cmp` 字节等值 +
  sha256 前后一致 `2775228…6cceb0`，还原后 17 例复绿）。

### 10.4 与 §8 规格的偏差（如实）

1. 审计 G-1 要求「符号就近」判据 warn-only ⇒ 本席**未实现符号档**（假阳性率已被 §D-3 证伪两次），
   改为「行容量 + 文件可解析 + 垫片/旧路径分类」三档，符号级校验留给未来带 AST 索引的门。
2. 审计 G-2 的断言 A/C/E（catalog 第 5 列热更勾 vs `SETTABLE_KEYS`、实跑 `set_override` 裁判）
   **未落地**：`docs/config-catalog-full.md` 归 CATALOG-FIX 席、`SETTABLE_KEYS` 消费面归 R15 施工席，
   本席无面可改，且实跑型断言需 import 插件包（与本门「纯静态」纪律冲突）⇒ 归该席自建。
3. 审计 G-3（命令可达性门）未落地：需解析 `__init__.py` dispatch elif 链与 `_HELP_ENTRIES`
   （`echo.py` 为 HELP-1 在飞面），且 §B-2 里 `/bot decision` 一例本席已以文档标注止血。
   建议下一席专做，规格沿用 §8 G-3。

