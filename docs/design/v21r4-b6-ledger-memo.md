# v21r4-B6 台账项调研与口径定义备忘（LEDGER-b 席，2026-09-18）

> **性质：纯调研+文档，零实装。** 本文所有方案均为**提案，未经用户裁定不实施**。
> 证据口径：file:line 为 2026-09-18 工作树快照（多席共享、未 commit，行号会漂移，符号名比行号可靠）。
> v21r2 板块重组后大量旧路径是垫片（PEP 562 re-export），本文一律引用**真身**坐标。
> 诚实声明：本文不声称任何改动「已生效」——生产 bot 未重启，一切代码面结论均为「已入库待重启」。

---

## ① 搜索时效：口径提案（供用户裁定，不实装）

### 1.1 现状盘点

**缓存 TTL 现状（五处，各管各的）：**

| 通道 | TTL | 容量 | 坐标（真身） |
|---|---|---|---|
| 通用 web 检索链（同步路径） | 600s | 256 条 | `domains/core/search/web_search.py:460-461`（`ChainedWebSearchProvider._CACHE_TTL_SECONDS`）；异步路径不缓存（`:457`、`:524-543`） |
| 控制面 SearchService | 普通 300s / 热点 60s | — | `domains/core/search/search_service.py:128-130` |
| meme 梗检索（DDG） | 600s（可配 `bot_meme_search_cache_seconds`） | 256 | `domains/meme/sources/meme_search.py:114`、`:340` |
| 萌娘百科 | 300s（注释：条目更新频率低） | 256 | `domains/location/data/moegirl.py:36-38` |
| ACG 竖源 Bangumi / B站 | 无缓存，每次实呼 | — | `sources/acg_search.py:105-160`、`:202+` |

**时效机制现状（v21r2 SEARCH 席已建的面）：**

- 意图时效档：`latest`（要最新动态）/ `background`（要背景知识），词表+正则纯本地判定，零 LLM——`sources/search_intent.py:33-34`（常量）、`:218-225`（判定：明确「最新」信号→latest；梗查询默认 latest；「出处/什么意思」归 background）。
- 时效加权融合：`fuse_into_web_hits`（`sources/acg_search.py:424-462`，纯函数）——latest 档按结果日期加权（≤7 天 1.6 / ≤30 天 1.3 / ≤180 天 1.1 / 更旧 0.8 / 日期未知 0.7 / 未来日期 1.6，`:364-410`）；background 档按源权威度（萌百 1.2 / Bangumi 1.1 / B站·web 1.0，`:372-377`）。
- 诚实标注（已有三件）：①条目摘要注「（来源·日期）」，latest 档无日期标「日期未知」（`acg_search.py:413-421`）；②【联网检索】区头「检索截至 YYYY-MM-DD HH:MM」（`acg_search.py:96-98`）；③守岸人语气时效免责句 `TIMELINESS_HONESTY_LINE`（`acg_search.py:79-82`）。三件均在 chat 链注入（`domains/chat_reply/capabilities/chat.py:1225-1226`）。
- Tavily 时间过滤钩子：`bot_web_search_tavily_time_range` 配置键**已存在**（`config.py:425`，缺省空串=未启用），作为一等 body 参数映射进 Tavily 请求（`domains/core/search/search_api.py:448-459`）。

**「时效」现状的四个真实缺口（只列不修）：**

1. **「检索截至」标注与缓存数据矛盾**：区头写的是 `datetime.now()`（`chat.py:1225`），但同步检索命中 600s 缓存时，数据可能是最多 10 分钟前抓的——「截至现在」是假话。口径不一致（诚实性缺口，量级小但真实）。
2. **web 通用命中在 latest 档恒垫底**：融合时 web 结果传 `date_str=""`（`acg_search.py:440-443`），latest 档一律拿 0.7 权重——即使 Tavily 刚抓的新报道也压不过带旧日期的 ACG 竖源条目。竖源偏置是设计意图，但「新 web 内容被旧条目压」不符合 latest 档本意。
3. **缓存键不含时效档**：缓存键=(query, max_results)（`web_search.py:508`）——「芙莉莲 第二季」background 查询的缓存结果会被同名 latest 语义查询命中（或反之），时效敏感查询在 TTL 内拿到旧数据且无任何提示。
4. **Tavily time_range 钩子闲置**：配置键在、映射在，但缺省空且无人按 latest 档自动填；启用后 web 命中依旧没有日期字段回流给加权层（`WebSearchHit` 无 date 字段，`acg_search.py:454-459` 只能造无日期的 hit）。

### 1.2 「时效」口径定义提案

**建议口径（一句话版）**：「时效」分两层定义——**数据层**（结果本身的新旧：条目自带日期、缓存年龄）与**标注层**（bot 告诉用户的新旧：检索截至时间、条目日期标注、免责句）。治理目标是两层都诚实，而不是把缓存砍光。

**三个可选方案（互不排斥，可组合）：**

- **方案 A：缓存 TTL 分档治理。** latest 档查询命中缓存时：要么跳过缓存直接实呼，要么 TTL 压到 60s；缓存键纳入时效档（`(query, max_results, timeliness)`）。收益=时效敏感查询不拿旧数据；代价=latest 查询计费外呼变多（Tavily 计费链，检索链最坏 5 查询×3 源，`web_search.py:455-457` 注释自认）。影响面：`web_search.py` `ChainedWebSearchProvider.search` + `chat.py` 调用方需把意图档传进来（现签名不传，`chat.py:3200` `_search_queries_concurrently` 链路）。
- **方案 B：标注层修正（最便宜，纯诚实面）。** 缓存条目记录写入时的墙钟（`_cache_put` 现在只存 `time.monotonic()`，`web_search.py:491`，补一份墙钟即可）；「检索截至」在缓存命中时改为「检索截至 HH:MM（缓存于 N 分钟前）」或直接显示缓存写入时刻。收益=消除「截至现在」假话；代价≈0，不动检索行为、不动计费。影响面：`web_search.py` 缓存结构 + `acg_search.py::timeliness_section_note` + `chat.py:1225` 一行注入。
- **方案 C：时效加权补全。** ①按意图档自动启用 Tavily `time_range`（latest 档传 `week`/`month`）；②web 命中回流发布日期（Tavily 是否稳定返回 publishedDate **unknown，需查 Tavily API 契约并实呼验证**），有日期后 `fuse_into_web_hits` 把 `date_str=""` 换成真日期。收益=latest 档排序真正反映新旧；代价=动 provider 返回契约（`WebSearchHit` 加字段）+ 依赖 Tavily API 行为（无证据），且要用户确认 Tavily key 与计费意愿。影响面：`search_api.py` provider 契约、`web_search.py` hit 结构、`acg_search.py` 加权层、config/env 登记。

**推荐**：**B 立即可做（收益/成本比最高），A 轻量跟进（只做缓存键含档，TTL 分档可选），C 挂起等两个外部条件**（Tavily publishedDate 契约确认 + 用户对时效敏感查询计费增量的裁定）。三者都不改渲染、不改人格、不新增对用户可见的命令。

**裁决点交用户**：①是否接受 latest 查询缓存变短带来的计费增量；②「检索截至」缓存命中时的具体措辞；③Tavily time_range 只对 latest 档生效还是全局配置。

---

## ② 合并转发：已闭环，待重启生效 + live 观察

**结论：无余量缺口。** 2026-09-18 核心链路排查批已把「转发里再转发读不了」根治，代码入库待重启生效。

**现状核实（真身坐标）：**

- 递归展开三闸：深度上限 `_FORWARD_NESTED_MAX_DEPTH=3`、子节点总数 `_FORWARD_NESTED_MAX_TOTAL=12`（`__init__.py:874-875`）；主+子共享总超时预算 deadline=配置超时×(深度+1)（`__init__.py:1031-1033`）；环引用 seen 集合同 id 只取一次（`__init__.py:1034`、`:1054-1055`）；深度优先展开 `_expand`（`__init__.py:1045-1071`）。
- 失败可观测：子转发失败/主超时/空正文三路全有 warning（`__init__.py:1060-1067`、`:1075-1085`、`:1087-1092`）。
- 配置：`bot_forward_fetch_timeout_seconds` 缺省 5.0（`config.py:725`），消费点 `__init__.py:7245`、`:7786`。模块级回退常量 10.0（`__init__.py:864`）仅在 config 属性缺失时生效，非缺口（回退语义）。
- 大图 25MB/25s：远程 `_MAX_REMOTE_IMAGE_BYTES=25_000_000` + `_REMOTE_DOWNLOAD_TIMEOUT=25.0`（`domains/media/ingest/vision_describe.py:239-240`）；本地 `_MAX_LOCAL_IMAGE_INPUT_BYTES=25_000_000`（`:78`）。注释 `:241-244` 记录 8MB→20MB→25MB 放宽史（25MB=2026-09-18 用户裁定「图片大小放宽到25MB」，任务书 20MB 为旧口径）。进 VLM 前先 PIL 缩边 2048（`:79`、`:139-140`），data URL 实际 <5MB（`:71-72`）。
- 测试在位：`tests/test_forward_message_ingest.py`、`tests/test_perf_forward.py`（文件级证据，用例数未清点）。

**live 观察点（重启后）：**

1. 三层嵌套转发实聊一条，确认深层正文不再只剩 `[合并转发:id]` 占位符；
2. >20MB 手机原图发识别，确认不再「大图读不了」；
3. 5s 单跳预算 ×(3+1)=20s 总预算，遇到 SnowLuma 慢回执时观察 `forward message fetch timed out` warning 频率——若频繁超时可考虑把 `bot_forward_fetch_timeout_seconds` 调到 8-10（配置改动，非代码）。

---

## ③ 提醒系统：功能面残余盘点

**已落的面（本波确认在位，不动）：**

- 广告闸（粘贴体守卫）：超长/带广告痕迹/多句正文拒绝入库（`domains/schedule/capabilities/reminder.py:76-89`）+ 24h 同文去重（`:92-111`）——2026-09-18 实弹（群友粘贴 AI 缴费广告五条齐炸）已治。
- 勾选消歧 A-10/A-11：唯一候选相似度不足追问确认、歧义清单回序号，追问状态进程内 TTL 300s（`reminder.py:119-318`）；文案池收口 A-13（`:163-196`）。
- 清单满 20 条如实拒绝不挤旧（`reminder.py:672-680`，审查 A-07）。
- 过期治理：迟到 >30 分钟不原样补投（`domains/schedule/store/reminders.py:58-60` `LATE_DELIVERY_GRACE`）+ 治理回执（`:160-257` gov- 前缀）。
- 时区口径统一走配置时区+timesync 校正（`reminders.py:63-113`，V2.1 风险 7 修复）。

**残余（功能面缺口清单，不实装，供排期）：**

1. **「明早」不在日词表（实锤，会错记）**：`_ABS_TIME_RE` 日词交替只有 `今天|明天|后天|今晚|今早|明晚`，`_DAY_OFFSETS` 同（`reminders.py:46-51`）。「明早8点提醒我」解析为日词缺失+「早上」时段→按今天 8 点算：若现在已过 8 点会歪打正着顺延到明天，**若现在是早上 7 点则错记到今天 8 点**（顺延逻辑 `reminders.py:337-338` 只在已过时触发）。修法方向：日词表补「明早/明午/明晚变体」，一处正则+一处 offset 表。
2. **星期几不支持**：「周五提醒我」「下周三叫我」无正则命中→解析不出时间，走 usage 兜底文案（`reminder.py:640-647`）。行为=诚实拒绝，不是错记，优先级低于上条。
3. **具体日期不支持**：「3月5日提醒我」「下个月1号」同上，落 usage 兜底。
4. **模糊相对词不支持**：「一会儿/待会儿/等下提醒我」无正则（相对正则只有 半小时/N分钟/N小时后，`reminders.py:53-55`）。口语高频，可考虑给「一会儿」定默认 15 分钟，但涉及产品语义，**需用户裁定**。
5. 「X点一刻/三刻」不支持（「半」已有，`reminders.py:326-327` A-09 修过）。低频，登记即可。

**建议**：#1 是唯一会**错记**的缺口（其余都是诚实拒绝），若排期只做一件事就做 #1；#4 需用户定默认值；#2/#3/#5 按需。测试面：`tests/test_reminder.py` 等 5 文件在位（`ls tests/ | grep reminder`）。

---

## ④ LLM 故障转移：重启后需采集的 live 证据清单

**前提**：R1 席修复全部代码入库但未重启未 commit（权威记录 `docs/design/v21r2-r1-llmroute-log.md`，其符号本席已在真身逐一验证在位，见 §附录）。真身=`domains/chat_reply/llm_engine/model_router.py`（2340 行）、`channel_health.py`（750 行）、`domains/ops/monitor/alerts.py`（567 行）。**本席未跑任何真实 LLM 调用**，以下全部是重启后的观察项。

| # | 证据项 | 看什么 | 采集方式（日志关键字/坐标） |
|---|---|---|---|
| 1 | served_by 轨迹 | 每轮 content_route 实际服务渠道与 attempts 数 | chat.py:2001-2005 `content_route: has_session= mode= tag= served_by= ... attempts=` |
| 2 | 逐跳失败日志 | 每跳失败模型/家族/类型/耗时/是否 intimate | model_router 逐跳 warning `llm route hop failed model= family= kind= elapsed_ms= timeout= intimate=`（R1 日志 §二前任成果；真身 `:2097` 附近 min_hop 止损消费） |
| 3 | chain 长度分布 | 正常应 1 跳命中；告警 detail 压缩形态 `chain=N跳全败 last=x` | alerts.py:312-343（`_compress`「chain=N跳全败」）；若 N 持续 >3 说明冷却降级未起效 |
| 4 | 90s 冷却观察点 | 首跳失败渠道是否进冷却、下轮不再首发 | channel_health.py:457 `resolve_channel_cooldown_seconds`（缺省 90s）+ `:98-100` `cooldown_until` 列迁移（SQLite 落库重启不丢）+ demote 日志 model_router.py:1978-1985 `demoted=` |
| 5 | INTIMATE grok 钉一 | grok 被冷却挤下时有无回落日志 | model_router.py:1972-1999 `llm intimate grok fallback: grok 熔断冷却/不可用中，临时回落` |
| 6 | 严格优先级生效 | 同名模型渠道按注册表 priority 序，不再价格序反超 | `bot_chat_strict_priority` 缺省开（model_router.py:611、:1119-1120）；对照组=观察是否还有低优先级渠道抢先命中 |
| 7 | 分组配置真生效（R7 修复） | BOT_MODEL_PRIORITY_GROUPS 从「恒 no-op」变真生效 | 生产现配置与注册表序同序→重启零行为差属**预期**；改分组序后重排才见真效果（R1 日志 §五） |
| 8 | axonhub 控制台对照 | bot 20s 读超时掐断 vs axonhub 侧「已取消」记录对得上 | 对照 AGENTS.md #36 四段取证形态（20:45 取消链）；bot 侧 20s 超时**保持不改**（用户令，axon-grok 健康 ema≈11.5s） |
| 9 | 告警折叠防刷屏 | 故障期 llm 族跨 kind 折一条、kinds 清单随行 | alerts.py:161-168 `fold_kind_stages={"llm"}` + `llm_kinds=[a|b|c]` 随行 |

**采集纪律**：不主动制造故障；等自然故障窗口采样即可。任何一项与预期不符→按 systematic-debugging 另立排查，不在 B6 波次内修。

---

## ⑤ 亲密话术：边界说明（本波不动）

**口径**：亲密话术属人格域资产（personas/ 知识文件 + chat.py 提示词注入），按波次分工需与人格域协同推进，**本波只留指针、不动代码、不动 persona**。

**指针**：`docs/design/v21r2-rp-style-log.md`（v21r2 RP 席，2026-09-18 已实施完毕：复读三连根因定位→文风池化游标轮换→INTIMATE/normal 动作描写条件开关互斥注入→persona 源四处改写；7 例新测试+回归 190 passed；persona sync `--adopt` 锚定 sha=d13a7ada…）。

**该域遗留三项（摘自 RP 日志 §七，均待人格域+用户裁决，非 B6 范围）**：

1. 输出侧硬保证（normal 态 `strip_action_brackets`）未做——改全局出站行为，涉 `bot_persona_action_brackets` 默认语义；
2. 核心知识.md 战斗语音原声保留（知识事实）——若实测仍被复读，在 intimate 指令加负向示例；
3. INTIMATE 判定代理的是「会话态」非逐句内容分类（群级整群生效/120min TTL 兜底，既有裁定语义）。

---

## 附录：本席验证过的关键符号（真身坐标，供后续席位免检索）

- 合并转发：`__init__.py` `_forward_message_text`(:1007)、三闸常量(:874-875)、`_expand`(:1045)。
- 大图：`domains/media/ingest/vision_describe.py` `_MAX_REMOTE_IMAGE_BYTES`(:239)、`_REMOTE_DOWNLOAD_TIMEOUT`(:240)、`_MAX_LOCAL_IMAGE_INPUT_BYTES`(:78)。
- 搜索：`domains/core/search/web_search.py` `ChainedWebSearchProvider`(:452)、TTL(:460)；`sources/acg_search.py` `fuse_into_web_hits`(:424)、`TIMELINESS_HONESTY_LINE`(:79)、`timeliness_section_note`(:96)；`sources/search_intent.py` `detect_acg_intent`(:166)；接线 `domains/chat_reply/capabilities/chat.py:3141/:3259/:3289/:1225`；Tavily 钩子 `config.py:425`+`search_api.py:448-459`。
- 提醒：`domains/schedule/capabilities/reminder.py`（730 行，广告闸 :76-89）；`domains/schedule/store/reminders.py` `parse_reminder_intent`(:295)、日词表(:46-52)、顺延(:337-338)。
- LLM：`domains/chat_reply/llm_engine/model_router.py` `_strict_priority_enabled`(:611)、`_failover_min_hop_seconds`(:636)、`_demote_cooling_candidates`(:655)、grok 回落日志(:1972-1999)、attempts 注入在 chat.py:2001-2005；`channel_health.py` `resolve_channel_cooldown_seconds`(:457)、`cooldown_until` 迁移(:98-100)；`domains/ops/monitor/alerts.py` `fold_kind_stages`(:161)、chain 压缩(:312-343)。
- 垫片注意：`llm/model_router.py`、`llm/channel_health.py`、`runtime/alerts.py`、`sources/web_search.py`、`sources/moegirl.py`、`capabilities/reminder.py`、`character/memory_extract.py` 均为垫片，全库 grep 时须到 domains/ 真身搜。

## 交付状态

- memo：本文（docs/design/v21r4-b6-ledger-memo.md），2026-09-18 LEDGER-b 席落盘。
- 续跑日志：docs/design/v21r4-b-LEDGER-log.md（含逐项取证过程）。
- 全部五项为调研结论，**无一实装**；①的三方案与③的 #4 待用户裁定。
