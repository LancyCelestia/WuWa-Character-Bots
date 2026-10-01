# S01 · 天气域多源互证 + 灾害感知 + 乡镇/全球精度 工单（未落地：主树空壳，本席零代码）

席位：S01（天气域）。**基线＝git 对象库 `HEAD = 8ad03e4`（2026-09-30 03:46:45 +0800）**，全部行号＝**HEAD 实测**（`git --git-dir=<Runtime>/git show HEAD:<路径>` 逐件读出并数行），blob 短哈希逐件附在册。
本席**未改任何文件、未跑任何门**（盘上无源码 ⇒ 跑出的红皆伪造）。落地前提＝主树按 `patches/INCIDENT-20260930-TREEWIPE-RECOVERY.md` 复原并逐笔 commit 之后。

> 需求（用户原话拆三件）：(a) 全球任意地点精确到乡镇/村庄；(b) 感知台风/地震/寒潮/高温/强对流/飓风/强降雨/火山等灾害；(c) **多来源互相校对**。
> 一句话结论：**三件里只有 (c) 是"没有"，另两件是"有但被用歪"。** 异源比对全树零命中（天气域）；预警腿被 `source=="nmc"` 一刀掐死；乡镇/全球**已经在走** Open-Meteo 点位，但码表无坐标、预警不附、精度上限不声明。

---

## §1 现状（HEAD 实测坐标）

### §1.1 天气域本体

| 件（相对 `plugins/bot_unified_runtime/`） | blob | 行 | 关键事实（HEAD 实测） |
|---|---|---|---|
| `domains/weather/capabilities/weather.py` | `1f7a533c` | 442 | 能力入口 + 串行兜底 + 预警腿 + 卡合成，四件事在一件里 |
| `domains/weather/data/nmc_weather.py` | `32d39d3d` | 213 | NMC 取数与格式化，**返回值是 `str`**（行 124-187），结构化读数在建报文前就被丢掉 |
| `domains/weather/data/open_meteo.py` | `d2c5f8cf` | 195 | 全球兜底：geocoding + forecast，**返回 dict 且带 latitude/longitude**（行 182-183） |
| `domains/weather/assets/qx.json` | `9909c20b` | 15,163 | 2,527 条 / 34 省 / 键**只有 `code/province/city/url`**（本席 json 现算）＝**无经纬度**；`code` 唯一；`city` 同名 6 组（朝阳/通州/河南/甘南/东乡/河口） |

坐标逐条（HEAD 实测，按符号名定位优先，行号会漂——台账 #50★）：

- 变体链上限 `_QUERY_VARIANTS_MAX = 3` 行 63，`_query_variants` 行 66-85：产出 `[原串, 去分隔串, 各段倒序]`，**不含首段**（`docs/boards/B05-external-data-services/weather/geo-locating.md` 行 18 写的「…／首段」与真身不符＝文档假账）。
- NMC 重试：`_NMC_RETRY_ATTEMPTS = 2`、`_NMC_RETRY_BACKOFF_SECONDS = 0.5` 行 93-94；`_nmc_query_with_retry` 行 97-120——**码表未命中直接 `return None`**（行 111-112），不重试。
- 预警端点常量 `_NMC_FIND_ALARM_URL = "...rest/findAlarm?pageNo=1&pageSize=300"` 行 127（**单页、无翻页**）；`_ALARM_COLOR_RANK` 行 128；`_ALARM_MAX_SHOWN = 5` 行 129。
- `parse_alert_title` 行 192-214（类型/颜色**从 title 正则式抠词**，无「发布」词即 `kind=""`）；`fetch_city_alerts` 行 217-262（token 全命中标题才算，行 247；异常一律 `[]`，行 235-236）；`format_city_alerts` 行 265-278（`其余 N 条略` 诚实，超限不谎报）。
- **串行兜底**＝行 367-385：`for variant in variants: report = _nmc_query_with_retry(...)` 全失败后才 `for variant in variants: global_result = open_meteo_query(...)`。**两条腿从不同时跑 ⇒ 结构上不可能比对。**
- **预警门**＝行 414 `if source == "nmc":`——Open-Meteo 支路（乡镇/街道/海外）**零预警**，注释行 411 自陈「Open-Meteo 海外/乡镇无预警语义」。
- 审计标签行 422-429：`weather_source:<nmc|open-meteo>`、`weather_query:<…>`、`weather_alerts:<N>`。卡面署名映射行 307（`{"nmc": "中国气象局 NMC", "open-meteo": "Open-Meteo"}`）。
- 装配：builder `build_weather_capability` 行 281-442；根闭包 `plugins/bot_unified_runtime/__init__.py` 行 4556（同函数内 `emergency_service` 于行 5629/5641 置 None、行 5663 建实例；天气 handler 行 9712 与两处内联调用行 7269/9585 均在消息期才跑 ⇒ 闭包按名后读到得到值）。注册颗 `domains/chat_reply/runtime/capability_registry.py` 行 367-392（`adapter="prepared"`、**外层安全网 `timeout_seconds=45.0`（行 388）**、`config_keys` 行 390）。
- 配置：`config.py` 行 495-499（`bot_weather_enabled/latitude/longitude/cache_seconds/timeout_seconds`＝**环境信息腿那一族**，缺省 enabled False）、行 1298 `bot_weather_query_enabled: bool = True`（命令腿）。命令腿各外呼超时唯一真身＝`bot_weather_timeout_seconds`（缺省 8.0，装配处行 290 读出后逐腿实传）。
- 板块声明：`domains/core/board_taxonomy.py` 行 465-477——`impl_paths=("plugins/bot_unified_runtime/domains/weather",)`（**目录级认领** ⇒ 本域新增 `.py` 自动被 G-P2 认领会红不了），`extra_l3` 现三枚（nmc-forecast / alert-branch / geo-locating），`config_prefixes=("bot_weather_",)`。

### §1.2 第二/第三条天气腿（**已存在，别再建第三条**）

- `domains/chat_reply/character/temporal.py` 行 212-320：`OpenMeteoWeatherProvider` **自带一套** open-meteo forecast 客户端（URL 行 277-282，字段与天气域那套不同：多 `apparent_temperature`、少 `wind/daily`），带缓存/后台刷新/响应限长。它与 `domains/weather/data/open_meteo.py` 是**同一上游的两份实现**（互证波不许再叠第三份；收编属 §7 风险 R6）。

### §1.3 可复用的「异源互证」既有形制（真身两处，不是一处）

| 件 | blob/行 | 可复用原语 |
|---|---|---|
| `domains/finance/data/market_crosscheck.py` | `791e17f4`，189 行 | ① `CrossCheckResult`（checked/matched/mismatches/source + `.ok` 属性）行 51-62；② 容差常量对（相对比 + 绝对百分点）行 43-44；③ 模块级 TTL 缓存 + `reset_crosscheck_cache()` 行 46-47/65-68，且**只缓存成功结果**行 139-141；④ **单点网络出口** `_fetch_tencent_snapshot`（测试 monkeypatch 它即全拦）行 71-109；⑤ `crosscheck_quotes` 主循环「主源缺数按差异记账、不判一致」行 154-157；⑥ `format_crosscheck_note` 三态文案（未核验→**空串不声明**／一致→`已与…交叉核验 ✓ m/n`／分歧→`⚠ … 差异：<两源读数值面并列>`）行 179-189。消费形制＝`domains/finance/capabilities/market.py` 行 802-819（`timeout_seconds=min(timeout, 4.0)` 的**互证腿预算封顶**＋`body = f"{body}\n{cross_note}"`） |
| `domains/emergency_info/sources/open_data_quakes.py` | `6d38a983`，591 行 | ⑦ **同域已有的第二枚互证原语**（比金融版更贴本任务）：`crosscheck_quakes(primary, secondary, window_minutes=30, radius_km=200)` 行 511-566——一对一贪心配对、**配不上出一条 `confirmed=False` 并写「未获第二源确认」，绝不静默择一、绝不改数**（行 546-547 与注释 521-522），核验源独有条目也不吞（行 560-565）；`QuakeMatch` 行 106；`haversine_km` 行 171 |
| `domains/emergency_info/sources/nmc_alarm.py` | `58fff60a`，459 行 | ⑧ **同一 NMC 接口的更强采集件**：`build_nmc_find_alarm_url(page_no, page_size)` 行 186-190（pageSize 上限 500）；`parse_nmc_alarm_page` 行 235-322——`total_hint` 取源端 `data.page.count`、条目 > 总量时打 `page_truncated:m/n` 注记（行 311-312），并**合并 `data.provinceAlarms` 按 alertid 去重 + 打省级标**（行 267-281）；`parse_nmc_station_alarm` 行 336-390——消费 `data.real.warn`（站点当前预警，含 `signaltype/signallevel/issuecontent`）；`fetch_nmc_alarms` 行 395-417、`fetch_nmc_station_alarm` 行 420-439 |
| `domains/emergency_info/sources/http_get.py` | `d946e2da`，312 行 | ⑨ `FetchState.OK/NO_DATA/FAILED` 三态行 83-88 与 `SourceOutcome`（`reason/total_hint/dropped/attempts/notes` + `.truncated` 行 123-126 + `.describe()` 行 128-141）；常量白名单主机行 148-155（`www.nmc.cn / mobile-new.chinaeew.cn / earthquake.usgs.gov / www.gdacs.org`）；`require_safe_id` 行 172-177；`resolve_document` 行 252-285（异常**收敛成状态而非空值**）；`NMC_ALARM_TIMEOUT_SECONDS = 15.0` 行 68 |
| `domains/emergency_info/service/snapshot_store.py` | `f9694641` | ⑩ 四态 `FRESH/STALE/NEVER_FETCHED/FETCH_FAILED` 行 49-55；`SnapshotView`（**调用方必须按 `state` 决定文案，不许只看 items 空不空**）行 117-133；`SnapshotStore.latest()` 行 215；根装配 `__init__.py` 行 10048-10050 建**跨轮持有**的实例（`max_age`＝三轮轮询） |
| `domains/emergency_info/service/alert_taxonomy.py` | `41579ed6`，687 行 | ⑪ **灾种权威注册表已存在**：可用性三态 `observed/declared/none` 行 141-143；族注册行 104-127（含 `volcano` 行 117、`quake` 行 111-116）；类别逐条带 `sources/availability/evidence`（见本文 §4 矩阵）。**下游禁止再造第二份表**（该件行 3-7 明令） |
| `domains/emergency_info/service/subscriptions.py` | — | ⑫ 地名→（省,市）的 `qx.json` 反查 `_area_index()` 行 163-188（其注释行 166-168 已实测并写明「码表**没有经纬度**」）、`haversine_km` 行 474、`matches_subscription` 的「文字命中 ∨ 半径命中，两样都拿不到**不放行**」行 495-543（尤其 527-542 的逐边判空） |
| `domains/emergency_info/sources/gdacs.py` | `f1b2b579`，248 行 | ⑬ 全球事件（带坐标）：URL 行 47，`EVENT_TYPE_LABEL` 只收 WF/EQ/FL/TC 行 58-63，**未知种类码原样透出行 169**，Green **故意不映射颜色**行 54 |

**结论**：本任务的互证腿**不需要新写算法骨架**，要写的只是"把两源读数摆在一起判"的那一格。⚠ 但 `market_crosscheck` 的名字与 `IndexQuote` 入参是金融专用（`crosscheck_quotes(quotes)` 直接吃 `.code/.name/.price/.change_pct`）——**照搬其形制、不照搬其签名**；把它"上提成公共件"属跨域搬迁（`domains/finance/**` 非本域写面，且 `test_emergency_weather_dup_drift_lock.py` 头注 行 10-14 已把"上提为单一事实源"登记为他人欠账）⇒ 本工单**不做上提**，只在本域新建一件、按注释指回真身，防漂移靠测试对账（§6）。

### §1.4 紧急信息侧的预警真身（天气腿该换的换代目标）

- 站点级预警字段 `data.real.warn` 在真响应里**一直存在**（本席读 `tests/fixtures/emergency_info/nmc_restWeather.sample.json`，`warn` 全字段为哨兵 `9999`、`issuetime=""`＝"确实无预警"）。`domains/weather/data/nmc_weather.py` 只读 `real.station/weather/wind/sunriseSunset`（行 148-186），**从未读 `real.warn`，也从未读 `data.predict`**（逐日/逐时预报在响应里躺着没消费）。`nmc_alarm.py` 行 7-10 已点名这枚"消费缺口"。
- 真夹具事实（本席 json 现算）：`tests/fixtures/emergency_info/nmc_findAlarm.sample.json`（83,370B）`code=0`、`page.count=328`、`list` 300 条、`provinceAlarms` 4 条（4 条 alertid 全在 list 内）；**300/300 条 `issuetime` 是斜杠形态 `2026/09/20 00:43`**（逐字符 ord 校验：`/`=0x2f）。省级条目标题形如「陕西省气象台发布暴雨蓝色预警」——**只含省名**。

### §1.5 门禁在册、施工必须跟随的（HEAD 实测）

| 门 | 判据要点（与本任务相交的部分） |
|---|---|
| `tests/test_weather_tls_verification.py`（`97b9649d`） | **AST 锁只扫 `domains/weather/**/*.py` 里的 `verify_ssl=False` 字面量**（行 60-86）＋**行为锁只验 weather 自己那两腿的 `http_get_json` kwargs**（行 94-136）。⚠ 判据面到此为止 ⇒ 见 §7 R1（这是本工单最重要的一格） |
| `tests/test_emergency_weather_dup_drift_lock.py`（`3cdeee7a`） | 钉死 `_ALARM_COLOR_RANK`（weather）与 `ALARM_COLOR_RANK`（nmc_alarm）**逐键等值且迭代序一致**；`parse_alert_title` 与 `split_alarm_title` 对 16 条语料**逐字同结果**；两份 `haversine_km` 同式（行 42-45/74-82/87+）。头注行 10-14：真正收口要落到本席写面之外，收口后本件「自然退役或改锁单源」 |
| `tests/test_weather_alerts_b10.py`（`30e97704`） | 行 140-168 `test_capability_appends_alerts_on_nmc_hit_only`＝**把今天这个缺口钉成了期望**（海外支路断言 `"气象预警" not in body` 且不得有 `weather_alerts` 标签）。⚠ 另：行 142-145 的替身 `lambda query, proxy=""` 不接 `timeout` 形参，而真身行 115 是按 `timeout=` 关键字调用的 ⇒ **静态判它必 TypeError**（本席禁跑门，不宣称实跑）；`HANDOFF-RESCUE-20260930.md` 行 201 记「全量首跑 20443 passed/156 failed，尾 13 枚红点名 weather_alerts」⇒ 按**存量待验**记账 |
| `tests/test_weather_data_boundary.py` | 行 68（NMC 报文行骨架不被远端文本撑爆）、行 81（数值闸）、行 119-131（open-meteo：`len(report.splitlines()) == 3`、代理透传、forecast 腿必发）、**行 151-159 `test_city_alerts_sanitized` 的假响应体没有 `code` 字段**（⇒ 见 §7 R2） |
| `tests/test_wx_t6_timeout_plumbing.py` | 三层锁：行为（配置值逐腿抵达）、**AST（调用点实传的必须是配置变量 Name 节点，不是字面量/漏传）**、注释诚实（registry 假账句式绝迹）⇒ 施工不得把 timeout 改回硬编码 |
| `tests/test_generic_executor_facets.py` | 行 188：**command 面 builder 除首位 `config` 外不得有必填参数**（`builder(config)` 必须可 call）；行 289/339：root 直呼的裸 builder 名 ⇔ 注册表 `#symbol` 必须同名 ⇒ `build_weather_capability` 不许改名、新参数必须带缺省关键字 |
| `tests/test_orchestration_callsite_wave3_b.py` | 活性 ledger 真树 AST 扫 `build_weather_capability` 调用点与归属模块（行 60/66）⇒ 新增调用点要同批改 ledger |
| `tests/test_copy_redline_gate.py` | 扫描面按族派生含 `domains/*/capabilities/**`（头注行 10-17）⇒ 新增**用户可见串**要过词表与降级句尾启发式；`audit_tags=` 关键字不在面上（行 25-27） |
| `tests/test_config_key_registration_ledger.py` | 新键两腿：①**读点**（五桶判据，行 10-46；只剩注释/文档串不算）②**热改面唯一表态**（`SETTABLE_KEYS` / `RESTART_REQUIRED_KEYS` / `w24.DELIBERATELY_UNLISTED` 三选一，行 48-55）。叠加台账 #68★「幽灵字段三面齐」＝`config.py` 字段 + `settings.py` 登记 + `.env.example` |
| `tests/test_physical_placement_gate.py` | G-P1 越界点数与 G-P2 未认领**只准降不准升、上限==现值零余量**（行 60-70）⇒ 本域新 `.py` 靠 `impl_paths` 目录级认领（§1.1 末）安全；**把文件放到别的域目录**当场红 |
| `tests/test_cross_validation_gates.py` + `scripts/doc_sync.py` | 机器册 `docs/auto-facts.md` 由 `--write` 整册重生成、`--check` 漂移即红（册首 行 1-4 自述）。⚠ 台账 #70 记「echo=T8 源件未入库挡 `--write`」——主树复原前生成物写不动 |
| 根 `AGENTS.md` | 体积**软上限 30,000B / 硬顶 32,768B**（机器门 `test_entry_docs_within_size_ceiling`，台账 #62）；第四部分载体列是 `tests/test_doc_link_integrity.py` 子门③ 读的尺（一字不删不改） |

---

## §2 缺口（HEAD 实证的 9 格）

| # | 缺口 | 证据（HEAD 实测） | 命中需求 |
|---|---|---|---|
| G1 | **无异源互证**：两腿串行兜底，从不并存 | `weather.py` 行 367-385；全树 `crosscheck` 只在 finance/emergency 命中（`git grep`） | (c) |
| G2 | **走 Open-Meteo 的乡镇/街道/海外支路零预警** | `weather.py` 行 414 `if source == "nmc"`；测试行 152-168 把它钉成期望 | (b)(a) |
| G3 | **预警腿三态不分**：不可达／结构塌／确实无预警 一律 `[]` 静默 ⇒「取数失败」被说成「无预警」 | `weather.py` 行 235-236 与注释行 224；板块 README 现行缺陷 1（行 60）、`alert-branch.md` 行 30 已定性，**裁定＝不做超时化妆修复，改读快照**（`snapshot_store.py` 头注行 3-6）⇒ 接线至今未做 | (b) |
| G4 | **单页丢条目 + 省级/上级预警结构性挂不上** | `weather.py` 行 127 写死 `pageSize=300`、行 237 只读 `data.page.list`、从不读 `data.page.count/totalPage`（夹具实测 count=328 ⇒ 至少 28 条静默消失）；行 247 要求**全部 token 命中标题**，而省级标题只含省名（`provinceAlarms` 4 条标题实测形如「陕西省气象台发布暴雨蓝色预警」）⇒ 查「陕西-西安」类挂不到省级在报；`provinceAlarms` 整块未被天气腿消费 | (b) |
| G5 | **结构化读数不存在**：NMC 只回 `str`，Open-Meteo 只回 `report` 文本（且**不读 `current.time`**） | `nmc_weather.py` 行 124-187 返回值类型；`open_meteo.py` 行 179-185 出参键集（`report/location/latitude/longitude/source`）与请求字段行 137（无 `precipitation`、无 `apparent_temperature`） ⇒ 想做数值互证必须先把两源各留一份原始读数 | (c) |
| G6 | **地名→坐标只有兜底腿有**，NMC 腿永远没有（码表无经纬度） | `qx.json` 键集实测 `code/province/city/url`；`subscriptions.py` 行 166-168 注释同判 ⇒ 半径圈、跨源同点对齐、乡镇级"所属区县"回推都缺原料 | (a)(b) |
| G7 | **同名地名静默择一**：`search_city_code` 全称优先、其次前缀，**命中即返回首条** | `nmc_weather.py` 行 37-48；`qx.json` 实测 6 组同名跨省（朝阳/通州/河南/甘南/东乡/河口）⇒「天气 朝阳」永远是表序里靠前那个，用户无从知道选了哪个。点歌有「同名先问」先例（台账 #18） | (a) |
| G8 | **Open-Meteo 点位标签只到 `admin1`+国家**，村级命中丢中间层级 ⇒ 无法自证"真的是这个村" | `open_meteo.py` 行 156-161（只取 `admin1`、`country`；不取 `admin2/admin3`、不取 `population`/`type` 进正文），排序行 117-125 只在**同名候选**里挑人口最多者 | (a) |
| G9 | **精度上限与来源口径不声明**：卡面只署名"Open-Meteo"，正文没有"这是模式预报不是站点实况"「精度＝点位/格点，非本村实测」；预警无失效时间却易被读成"仍在生效" | `open_meteo.py` 行 162-178 报文行集；板块 README 缺陷 3（行 62）；`weather.py` 行 274 只写"发布 时刻" | (a)(b)(c) |

---

## §3 施工（六格，逐文件；每格独立可绿可回滚）

> 通用纪律：① 本域新文件一律落 `domains/weather/**`（G-P1/G-P2 安全，见 §1.5）；② 远端文本一律过 `sanitize_remote_text`（金融腿真身，**禁第二套尺**，先例 `nmc_weather.py` 行 16-18）；③ 数值一律过既有类型闸（`_fmt_num` 行 70-79 / `_format_value` 行 89-102）；④ 任何新增外呼腿必须实传 `bot_weather_timeout_seconds` 或按其封顶（AST 锁 `test_wx_t6_timeout_plumbing`）；⑤ 一律「取不到＝说取不到」，绝不填假值（D-1 口径 `contracts.py` 行 19-20）。

### S1 · 两源各留一份结构化读数（不改用户可见文本）

**文件**：`domains/weather/data/nmc_weather.py`、`domains/weather/data/open_meteo.py`

1. `nmc_weather.py`：把行 124-187 拆成两层——
   - 新增 `fetch_nmc_observation(stationid, *, proxy="", timeout=10.0) -> dict[str, Any] | None`：只做取数 + 结构守卫（沿用行 143-146 的 `isinstance` 逐层判，**这条守卫是台账 #47 的锁面，一字不动**），产出扁平 dict，键固定：`station_province/station_city/publish_time/info/temperature_c/feels_like_c/humidity_pct/wind_direct/wind_power/wind_speed_mps/rain_mm/icomfort`（值原样留 `str|float|None`，`9999` 哨兵折成 None 但**另留 `raw` 子字典**以便诚实显示），另加 `station_alarm`：把 `real.warn` 交 S3 用（本格只搬运，不消费）。
   - `fetch_nmc_weather(...)` 改为 `format_nmc_report(obs)` 的一行包装 ⇒ **报文字节零变化**（锁：`test_weather_data_boundary.py` 行 68/81、`test_weather_card.py`、`test_weather_nmc_malformed_json_degrade.py`——顶层非 dict 仍必须 `return None`，不许冲出异常烧掉兜底链）。
2. `open_meteo.py`：
   - 请求行 137 增 `precipitation`（单位 mm）、`apparent_temperature`，并在出参 dict 增 `observation`（`source/latitude/longitude/place_name/admin1/admin2/admin3/country/geocode_population/current_time/utc_offset_seconds/temperature_c/feels_like_c/humidity_pct/wind_kph/precipitation_mm/weather_code/daily[0..1]`）。**旧键 `report/location/latitude/longitude/source` 一个不动**（`test_weather_alerts_b10.py` 行 159 的假替身只给 `{"latitude": 35.0, "current": {}}` ⇒ 新代码对缺键必须"不声明"而不是抛错，见 §6 T2 注毒）。
   - 层级标签行 156-161 改为按 `admin1/admin2/admin3` 逐级拼接（拿不到的级跳过，不写"未知"）——这是 G8 的最小修法。⚠ **`admin2/admin3` 是否真在 geocoding 响应里＝待验**（本席只读到真码用 `admin1`，夹具内无该端点样例字节）；施工第一步必须先实测取证、把响应字节落成本域夹具，**禁先写死字段名**（夹具目录 README 行 5-7「禁止自造字段」是硬规矩）。
   - 同名候选：`open_meteo_query` 目前 `results[0]` 静默择一（行 116-125）。本格只加两件——出参带 `candidates`（前 5 枚 `name|admin|population|country` 的清洗后短串）与 `ambiguous: bool`（**同名候选 > 1 且人口/精确名判据不能唯一压过**时 True），择一逻辑本波**不改**（留给 S6）。

**验收**：`test_weather_data_boundary.py`、`test_weather_nmc_malformed_json_degrade.py`、`test_weather_nmc_retry_nmcflix.py`、`test_weather_card.py`、`test_wx_t6_timeout_plumbing.py` 五件全绿，且两源的 `report` 串与基线逐字相同（新增 T1 文本等值锁，见 §6）。

### S2 · 新建异源互证件（本域）

**新文件**：`domains/weather/data/weather_crosscheck.py`（建议 150-190 行，形制照 §1.3 ①②③④⑥⑦ 组装）

```python
@dataclass(frozen=True)
class WeatherCrossCheck:      # 形制＝market_crosscheck.CrossCheckResult 行 51-62，字段换气象口径
    checked: int               # 可比对的量纲数（温度/湿度/风/降水 四项各一枚）
    matched: int
    diffs: tuple[str, ...]     # 人读差异行：两条读数值面并列，绝不"取其一"
    comparable: bool           # 两源是否同量纲同时间基（False⇒只报"不可比"，不判对错）
    primary_source: str
    secondary_source: str
    @property
    def ok(self) -> bool: ...  # checked>0 and matched==checked and comparable
```

- 判据函数 `crosscheck_weather(obs, om, *, tolerance=...) -> WeatherCrossCheck`：
  - **单位先归一**：风 NMC `m/s`（`nmc_weather.py` 行 180 出参语义）×3.6 ⇄ Open-Meteo `km/h`（`open_meteo.py` 行 137 请求字段）；温度同为 ℃、湿度同为 %；降水 NMC `rain` mm ⇄ Open-Meteo `precipitation` mm（本波新请求）。**换算只准在这一处**，禁两处各写一份。
  - 时间基：NMC `publish_time`（北京时、分钟精度）vs Open-Meteo `current.time` + `utc_offset_seconds`；**归一比较窗 ≤ 30 分钟**（对齐 `crosscheck_quakes` 的 `window_minutes=30` 形制，行 511-517）。任一源不给时间 ⇒ `comparable=False`。
  - 容差（**相对差 + 绝对地板**，双写以防 0℃ 除零；形制＝market 行 43-44/158-165）：温度 ≤2.0℃、体感 ≤3.0℃、湿度 ≤15 个百分点、风 ≤5 m/s 等效、降水 ≤1.0 mm（且任一侧缺数 ⇒ 记 `diffs` 不记 `matched`，同 market 行 154-157「主源缺价按差异处理」的判据）。⚠ **这五枚数是工程起点不是裁定**：落地同批必须补一枚"读数差分布"实跑（真机 20 城 × 2 日）并回填本文件注释；不许在文档里手写这些阈值当既成事实（规则 10）。
- 文案函数 `format_weather_crosscheck_note(result) -> str`（**三态，形制＝market 行 179-189**）：
  - `checked==0` ⇒ 返回 `""`（**不声明**，不阻塞，不伪造）。
  - `ok` ⇒ `已双源互证 ✓ {matched}/{checked}｜NMC 站点实况 × Open-Meteo 模式场`。
  - 分歧 ⇒ `⚠ 两源读数有差（口径不同，非谁错）：温度 NMC 21.5℃@00:15（站点实况）｜Open-Meteo 24.0℃@00:30（模式再分析）⇒ 差 2.5℃；主报告取 NMC 站点实况，另一读数如上。`
  - `comparable is False` ⇒ `ℹ 两源读数时间基/量纲不齐（NMC publish_time 缺 / Open-Meteo 未回 current.time）⇒ 不做互证结论，两读数并列只报数不判。`
  - **措辞红线**：绝不得写"已核实正确""另一源有误"——模式场 vs 站点实况的差是**口径差**；也绝不得静默择一（用户裁定「分歧要呈口径差异」）。词表要过 `test_copy_redline_gate.py`（禁用「给您带来不便」类、降级句尾启发式）。
- 出口与缓存：单点出口 `_fetch_secondary_observation(...)`（照 market 行 71-109 的"测试 monkeypatch 它即全拦外呼"），TTL 缓存 + `reset_weather_crosscheck_cache()`（照行 46-47/65-68，**只缓存成功**行 139-141）；互证腿预算 `min(timeout_seconds, 4.0)`（照 `market.py` 行 808）。
- **诚实边界（必须写进模块头注并在卡面体现）**：Open-Meteo 一个 API 背后是多家机构的模式场；若将来加 `&models=` 做"多模型"，那是**同源异模型**，不叫异源，文案要写「同源多模型」，不得冒充两源互证。本格只用 NMC（官方站点实况）× Open-Meteo（模式）这一对**真异源**。

**装配**：`weather.py` 行 372-410 之后（主报告成立才互证，查不到时不互证）：

```python
cross_note = ""
obs = _last_nmc_observation      # S1 产出，随 report 一起带出（新增局部，不改 builder 必填面）
if obs is not None and om_obs is not None:      # 两源都在才算，缺一律不声明
    cross_note = format_weather_crosscheck_note(crosscheck_weather(obs, om_obs, tolerance=...))
if cross_note:
    report = f"{report}\n{cross_note}"
audit_tags.append(f"weather_crosscheck:{'ok' if ... else 'diff'}")   # 只进审计面，不进正文
```

⚠ 参数注入必须走**带缺省的关键字参数**（`test_generic_executor_facets.py` 行 188）；builder 名与注册表 `#symbol` 不许动（同件行 289/339 双向锁）。

### S3 · 预警腿换代（三态 + 翻页 + 省级 + 站点预警），并扩到非 NMC 支路

**文件**：`domains/weather/capabilities/weather.py`（拆出 `domains/weather/data/nmc_alarm_bridge.py` 承接装配）

1. **新文件** `domains/weather/data/nmc_alarm_bridge.py`：把 `fetch_city_alerts` 换成消费 §1.3 ⑧⑨ 的三态件，**保留一个天气侧适配函数与旧名 `fetch_city_alerts`（旧签名 + 新增缺省关键字）**，因为 `test_weather_tls_verification.py` 行 30-32/113-136、`test_weather_data_boundary.py` 行 151-159 都按该名字与模块路径 import/patch（改名＝三件同批改，风险 R2）。产出 `AlarmRead`：`state ∈ {OK, NO_DATA, FAILED}`、`items`、`reason`、`truncated`、`total_hint`、`province_hits`。
2. **翻页**：`pageNo=1..totalPage` 上界 `_ALARM_PAGE_MAX = 3`（现算：夹具 `count=328/300` ⇒ 2 页即尽；上界防改版洪泛），逐页喂 `parse_nmc_alarm_page`，按 `alertid` 去重合并；**只要有一页 FAILED 就整腿判 degraded**，不得把半页当全量（G4）。
3. **省级/上级预警**：把 `parse_nmc_alarm_page` 的 `province_level=True` 条目单独成段展示——`⚠ 省级在报（陕西省气象台）：暴雨蓝色`，并在文案写明「乡镇/县级无独立预警单元，上级在报口径」。查询 token 匹配规则改为**分级命中**：完整 `省-市` 全命中（原行 247 语义保留）∨ 省级条目命中 `省`。⚠ 这是**放宽**，必须同批加负例锁（「大城」不得命中他省条目——原行 222-224 的防误挂意图一字不动）。
4. **站点预警白捡位**：NMC 命中站点的查询顺带读 `data.real.warn`（S1 已搬运到 `station_alarm`）与 `nmc_alarm.parse_nmc_station_alarm` 三态对齐 ⇒ **同一份响应的两个字段互为校验**（`real.warn` 单站 vs `findAlarm` 清单）：两说都有＝互证 ✓；清单有而站点无＝标注「站点侧未同步（NMC 无失效时间口径，README 缺陷 3）」；站点有而清单无＝标注「全国清单未收录/翻页截断」。**绝不静默择一。**
5. **三态文案**（治 G3，取代行 235-236 的一律 `[]`）：
   - `OK`＋有条目 ⇒ 现段照旧（`format_city_alerts` 行 265-278 骨架**一字不动**，`test_city_alerts_sanitized` 的 3 行骨架锁与 `test_format_city_alerts_renders_entry_lines` 的行序断言才保得住）。
   - `NO_DATA` ⇒ `（该地当前无在报气象预警）`——**只在结构成立且源自报零条目时**才允许出现这句。
   - `FAILED` ⇒ `（预警通道本轮取数失败：<机器 reason 消毒后短串>，先只显示天气）`。绝不写成"无预警"。
6. **TLS 对齐（硬前置，见 §7 R1）**：`nmc_alarm.fetch_nmc_alarms` / `fetch_nmc_station_alarm` 现在带 `verify_ssl=False`（`nmc_alarm.py` 行 412/435），而 `nmc_weather.py` 行 128-132 已实测证伪"证书链不完整"并撤销该传参（`test_weather_tls_verification` 上锁）。**天气腿复用该采集件前，必须先把这两处改回缺省验证**（同批改 `http_get.py` 头注行 31-33 那句"`verify_ssl=False` 的用法同 `nmc_weather.py:119`"——它引用的是已撤销的旧做法，属假账）。改前读 `tests/test_emergency_info_sources.py` 是否钉了 `verify_ssl=False`（本席 grep 只确认该文件出现 `verify_ssl` 字样，**未逐条读断言方向＝待验**）。
7. **快照优先**（板块 README 行 60 已裁的正解，本波接线）：builder 加带缺省关键字 `alarm_snapshot_provider: Callable[[], Any] | None = None`，根装配 `__init__.py` 行 4556 的闭包传 `lambda: emergency_snapshot_ref`（后读，避开装配顺序）。优先级＝**快照（四态）> 现拉**；快照 `NEVER_FETCHED`（=紧急域未开 `bot_emergency_info_enabled`，缺省 False 见 `config.py` 行 706）时回退现拉并在审计标签记 `weather_alert_path:snapshot|live`。⚠ **不得宣称"接线即免除超时病"**：紧急域总闸关着时快照永不存在，天气腿仍走现拉；这条要写在 §1.1 与卡面之外的运维册里。

**非 NMC 支路的预警腿（G2 正解）**——`weather.py` 行 414 的 `if source == "nmc"` 改为按"能不能定位到行政层级/坐标"分三条路：

- **路 A（中国境内、码表未命中的乡镇/街道）**：拿 Open-Meteo geocoding 的 `admin1`（省）+ `admin2`（市/地区）回填成 `省-市` 串再喂 S3 的预警腿；命中即显示并明说「该地为 <乡镇>，预警按其所辖 <市/区> 口径给出（乡镇级无独立预警单元）」。拿不到 `admin1/admin2`（待验字段）⇒ 落路 C。
- **路 B（境外）**：NMC 无覆盖 ⇒ 用**本域已有的全球事件源**做"事件级灾害感知"：GDACS（`GdacsEvent` 带 `latitude/longitude/event_type`）与 USGS/ICL 震情（`QuakeEvent`）按**坐标半径**匹配——直接复用 `subscriptions.haversine_km`（行 474）与 `matches_subscription` 的"文字 ∨ 半径，两边都拿不到**不放行**"判据（行 495-543，含 527-542 的逐边判空），半径起点 `DEFAULT_RADIUS_KM`（在册常量，别手抄数字）。来源署名 `GDACS/USGS`，并带其固有口径注记（GDACS 时间按 UTC 读取的显式标记 `gdacs_time_tz_assumed_utc`，`gdacs.py` 行 18-21；Green **不映射颜色**行 54 ⇒ 等级为空，按"无等级"显示，不猜档）。
- **路 C（哪儿都定不了）**：**显式缺席句**——`（该地未能定位到行政层级，气象预警给不到口径；已按点位显示天气）`。绝不静默省过（今天的写法就是静默省过）。
- 境外**气象类**预警（暴雪/寒潮/台风以外的官方预警）：**唯一取证在册的候选是 NWS**——`api.weather.gov/alerts?limit=2` 已在 `tests/fixtures/emergency_info/README.md` 行 36 登记为 #12 端点，实测 200 且**裁定「不接：国内用户无投递价值」**，夹具留档、无解析用例消费。⇒ 本工单**不擅自接**：作为 §8 裁定项 C-2 交用户重裁（接＝新增采集件 + 新域外主机 `api.weather.gov` 进 `ALLOWED_HOSTS` + 新夹具消费用例；不接＝路 B 只到"事件级"，气象预警对海外一律走路 C 诚实缺席）。**飓风/台风类海外事件**因此只能报「GDACS 有热带气旋事件（`eventtype=TC`，真样例实测 2 条）」，**报不到路径、中心风力、登陆时刻**——这句要在卡面/帮助里写明白，不许用"已关注台风动态"糊过去。

### S4 · 灾种覆盖与"给不到怎么说"（注册表反向消费，禁第二份表）

**新文件**：`domains/weather/data/disaster_coverage.py`（≤120 行，纯读 `alert_taxonomy` 派生，不另立灾种枚举）

- 唯一真身＝`domains/emergency_info/service/alert_taxonomy.py`（§1.3 ⑪，其行 3-7 明令下游禁造第二份表）。天气腿只调用它的 `families()/categories()/category_of_item()` 与 `availability` 三态；`_ALARM_COLOR_RANK` 与紧急侧 `ALARM_COLOR_RANK` 的序位等值**已由 dup-drift 锁钉**，本波若把拆色上提为单件，**必须同批改该锁为"锁单源"**（其头注行 12-114 允许两条路，不许把锁删掉——台账 #68★「只动一边必红另一边」）。
- 展示规则：`observed` 正常出；`declared` 出但注「该灾种 NMC 类型体系在册、本轮清单未见实例」；`none` **不出条目、只出口径**——把 `AlertCategory.evidence` 的"无源"理由原样消毒后透出（该件行 11-16 的纪律：订了也不会命中，帮助文案同样如实说）。
- 覆盖矩阵见 §4（**本工单的交付判据**，也是验收锁 T4 的语料来源）。

### S5 · 乡镇/村庄精度：上限声明 + 同名先问 + 降级路径

**文件**：`domains/weather/capabilities/weather.py`、`domains/weather/data/nmc_weather.py`、`domains/weather/data/open_meteo.py`

1. **精度上限（写实，不吹）**：
   - NMC 腿精度上限＝**区县级站点**（`qx.json` 实测 2,527 条、34 省，键无经纬度）＝"该区县气象台发布的实况"，不是"你村的天"。
   - Open-Meteo 腿＝**geocoding 点位（可到村庄/社区）→ 模式格点**，读数代表该坐标所在格点，**不是当地实测**。
   - 两句话进 `format_*` 之外的**卡面署名副行**与帮助页（S6），正文不加装饰性免责声明。
2. **同名先问（G7）**：新增 `_maybe_ask_ambiguous(variants_obs, candidates) -> CapabilityResult | None`，条件＝码表同名跨省命中（实测 6 组）或 geocoding `ambiguous=True` 且人口判据不能唯一压过；产出＝**一次性澄清问句**（守岸人语气、去 AI 味；规则 8），带候选列表（≤5 枚，清洗后短串）。先例与判据同 `docs` 里点歌「同名先问」（台账 #18）：问一次、不重复拦。⚠ 不得引入新触发词（`test_trigger_word_copy_ratchet.py` 在册棘轮）。
3. **降级路径（逐级显式，禁静默跳级）**：
   `码表精确(区县) → 码表前缀(区县，注"前缀匹配") → 变体链降维(末段乡镇) → geocoding 点位(admin1/admin2 回填) → 行政层级回退(所属市口径预警) → 只给点位天气 + 预警缺席句 → 全失败：现有"没有查到…"文案（行 401-408 一字不动，群聊静默腿行 386-400 保留）`。
   每一级只降**一件事**（先降地名粒度、再降预警口径），且降完必须在正文/审计标签留痕（`weather_geo_level:district|township|point|admin_backfill|none`）。
4. **变体链预算**（G1 的副作用控制）：行 63 的 3 枚上限**不动**（S-FIX-WXSSL L2 注释行 59-62 的理由仍成立）；但互证腿与预警腿新增外呼**一律不进变体循环**（只在主报告命中后跑一次），见 §5 的现算账。

### S6 · 文档 / 生成物 / 台账跟随（漏一件即红）

- `domains/core/board_taxonomy.py` 天气节点（行 465-477）：`summary` 与 `extra_l3` 若新增「异源互证」「灾害与预警口径」两枚三级入口 ⇒ 同批 `python scripts/board_doc_sync.py --write` 重生成 `docs/boards/B05-external-data-services/weather/**`，并过 `tests/test_board_taxonomy_gate.py`。
- 帮助文案真身：`domains/chat_reply/capabilities/echo.py`「天气」条目（HEAD 行 1539-1558，含 `index/title_line/details`）；改后同批 `scripts/command_catalog.py --write` → `docs/command-catalog.md`、根 `COMMANDS.md`，并过 `tests/test_commands_md_generated_index.py`、`test_command_catalog_ast_eval.py`、`test_generated_artifact_teeth.py`。⚠ 台账 #70 记 echo 源件当前未入库会挡 `--write` ⇒ 主树复原顺序有关。
- 机器册：`python scripts/doc_sync.py --write` 重生成 `docs/auto-facts.md`（新增配置键/板块计数一律现算，规则 10）。
- 根 `AGENTS.md`：第四部分「天气+预警」行的载体列补新落点（**只改不叠加**，且体积软上限 30,000B 顶线必压——台账 #62 硬顶 32,768）；第六部分新增一行台账（**编号由主会话/用户定**：HEAD 现至 #70，盘上另有未入库的 #71）。
- `docs/boards/B05-external-data-services/weather/README.md` 的「现行缺陷」4 条：G2/G3/G4 修完后**逐条销账并留指针**（缺陷 2「qx.json 禁删」不动——`.gitignore` 否定规则与 2026-09-13 误清先例继续有效）；`geo-locating.md` 行 18 那句「…／首段」假账按真身改正。
- `docs/db-owners.md` / `config-catalog-full.md`：本波若无新库、无新键则**明确写"零新增"**；若加互证开关（建议**不加键**，用模块常量 + 现有 `bot_weather_timeout_seconds`）则补齐 §1.5 的三面齐。

---

## §4 灾种覆盖矩阵（(b) 的交付；逐条：现有源能不能给 → 给不到怎么说）

> 载体＝`alert_taxonomy.py` 的 `availability`（`observed`＝真夹具实测出现／`declared`＝源体系在册但样例未见／`none`＝四源都供不了），行号均 HEAD 实测。**"给不到"一律要求显式缺席句，禁止用相邻灾种顶替。**

| 灾种 | 现在能不能给 | 真身证据（HEAD 实测） | 拿不到时的口径（必须出现在回复里） |
|---|---|---|---|
| 台风 | **半给**：国内官方预警类型在册但清单未见实例；境外只有"事件存在" | `alert_taxonomy.py` 行 203-209：`sources=("nmc","gdacs")`、`availability=declared`、evidence 明写「2026-09-20 真样例 300 条内未见实例；GDACS eventtype=TC 实测 2 条（境外口径）」；夹具实测本席：`gdacs_eventlist.sample.json` 含 TC 2 条 | 「台风预警类型 NMC 体系在册、本轮全国清单未见实例」；境外**只报事件存在**，并写「路径/中心风力/登陆时刻本域无源，不编」 |
| 飓风 | **不给独立口径**：与台风同族同 id，别名"飓风"已在册 | `alert_taxonomy.py` 行 204-206（`category_id="typhoon"`，aliases 含「飓风」）；`weather.py` 无独立飓风分支 | 明说「飓风＝同一热带气旋类，境外口径同上；本项目无飓风路径源」；**禁**把国内台风条目当飓风 |
| 地震 | **能给**（三源齐、带坐标/震级/深度），但**天气腿今天不显示** | `alert_taxonomy.py` 行 392-398 `observed`（icl/usgs/gdacs 真样例三源）；`open_data_quakes.py` 端点行 59-60、`QuakeEvent` 行 72、`crosscheck_quakes` 行 511-566（**已有互证 + 不静默择一**）；`contracts.py` 行 202-212（`latitude/longitude/magnitude/depth_km` 字段）；ICL 是降级代理源、**不得冒充 CENC**（夹具 README 行 33） | 天气腿按 S3 路 B 半径接入后给；两源未配对 ⇒ 「未获第二源确认」（照 `crosscheck_quakes` 语义）；拿不到震级/深度 ⇒ 落最低档、**不判红**（审计 E6-N1 教训，`collector.py` 行 84-90） |
| 寒潮 | **能给**（真样例 8 条全蓝） | `alert_taxonomy.py` 行 224-229 `observed`，`nmc_signal_type="0004"` | 只有省级在报时走 S3 省级段并写"上级口径"；站点侧 `real.warn` 与清单不一致 ⇒ 按 S3-4 标注，不择一 |
| 高温 | **能给**（真样例 37 条：黄 36/橙 1） | `alert_taxonomy.py` 行 244-249 `observed`，`nmc_signal_type="0003"` | 同上；**逐类官方色档数本表不声明**（该件行 17-21），故不得写"高温可达四档" |
| 强对流 | **能给**（雷雨大风 10/雷暴大风 6 实测；「强对流」作总称在标题可匹配） | `alert_taxonomy.py` 行 299-306 `observed`，`nmc_signal_type="0015"` | 冰雹/雷电各自单列（行 263-269/257-262），**不得**用"强对流"顶替未出现的单类 |
| 强降雨（暴雨） | **能给**（真样例 kind=暴雨 37 条：蓝 27/黄 7/橙 3） | `alert_taxonomy.py` 行 210-215 `observed`，`nmc_signal_type="0002"`；夹具本席现算 300 条里 kind 分布含暴雨 | 「中小河流洪水」「渍涝/城市内涝」「山洪灾害」是**不同口径**：前两者 `none`（行 328-341 **无源**），后者 `observed`（行 321-326）；被问"会不会淹"时只能答暴雨预警本身 + 无源声明 |
| 火山 | **明确无源＝不给** | `alert_taxonomy.py` 行 399-404 `sources=()`、`availability=none`、evidence「GDACS 体系含 VO 码但真样例未见；本域无火山通道（不接就不说）」；`gdacs.py` 行 58-63 `EVENT_TYPE_LABEL` 无 VO、行 169 未知码原样透出 | 固定句：「火山喷发本域无采集源，不报有无」；**禁止**从"某地是火山旅游城市"推断。升 `observed` 的唯一通道＝GDACS 真响应里出现 VO 并落成本域夹具（夹具 README 行 5-7 的"禁自造字段"规矩），同批改注册表 `sources/availability/evidence` |
| （附）空间天气/风暴潮/海浪/海冰/海啸/森林草原火险等级 | 全部 `none` | `alert_taxonomy.py` 行 367-391、行 405-411；`marine` 族收窄 | 逐条给"无源"，不得互相顶替（海啸 ≠ GDACS 的 FL/TS 缺口，行 380-385 已自证） |
| （附）地质灾害气象风险/山洪灾害 | `observed`（真样例各 5 条/1 条） | `alert_taxonomy.py` 行 314-327 | 可给；与「地震」分列（成因不同） |

---

## §5 预算与超时（落笔前自己现算——台账 #52★）

现状最坏（HEAD 实测，`bot_weather_timeout_seconds=8.0`、`_QUERY_VARIANTS_MAX=3`、`_NMC_RETRY_ATTEMPTS=2`）：

- NMC 腿：每变体最多 2×8s + 1×0.5s 退避 = **16.5s**，三变体 **49.5s**（且只有码表命中才重试，行 111-112）
- Open-Meteo 腿：每变体 geocode 8s + forecast 8s = **16s**，三变体 **48s**
- 预警腿：**8s**（现码行 416 传 `timeout_seconds`）
- 合计最坏 ≈ **105.5s**，而注册表外层安全网 `timeout_seconds=45.0`（`capability_registry.py` 行 388）⇒ **今天就已经存在"中央硬超时先落"的路径**（超时逃逸→`_internal_error`→错误卡；见 AGENTS 第四部分「统一错误报告卡」行与台账 #49★ 销账句）。这是**存量缺陷**，本波不假装它不存在。

本波约束（写死在 `nmc_alarm_bridge.py`/`weather_crosscheck.py` 头注，作为可审的账）：

1. 互证腿**只在主报告命中后**跑，预算 `min(timeout_seconds, 4.0)`（照 `market.py` 行 808），不进变体循环 ⇒ 新增最坏 **+4s**。
2. 预警腿优先读快照（0 外呼）；现拉腿翻页上界 3 页、单页超时 `max(timeout_seconds, 15.0)`（`NMC_ALARM_TIMEOUT_SECONDS=15.0` 的既有裁定，`http_get.py` 行 64-68：冷页实测 24.9s ⇒ 8s 必掐），**总腿封顶 18s**。
3. 变体链最坏预算必须显式收紧到与外层 45s 相容（建议：主报告腿合计预算 ≤ 28s，超出即停止后续变体并在审计标签记 `weather_budget_exceeded`）——**这是新增判据，属代码改动走评审**，本工单只出数不出码。

---

## §6 验收判据（含注毒自证；全部离线 mock，零真实外呼）

> 现有五件（§1.5）不许改判据方向；新增锁命名建议如下。**每条都给"注毒必红"的一手**。

| # | 判据 | 复跑 | 注毒自证（必红） |
|---|---|---|---|
| T1 | 报文等值：S1 重构后 `fetch_nmc_weather`/`format_open_meteo` 输出与基线**逐字相同**（文本零变化是 S1 的唯一合法性证明） | `pytest tests/test_weather_data_boundary.py tests/test_weather_card.py` | 把 `format_nmc_report` 里任一行模板改一个字 ⇒ 等值锁当场红（证明锁在量字节而非量"非空"） |
| T2 | 互证三态：一致→✓ m/n；分歧→两条读数值面并列且**含两源原值**；`checked==0`→**空串不声明**；缺时间基→`comparable=False` 只并数不判 | 新增 `tests/test_weather_crosscheck.py` | ①把 NMC 替身温度改成 OM 的 3 倍 ⇒ 断言"分歧 + 两值都在正文"必红否则判假锁；②替身删 `current.time` ⇒ 断言不得出现"已核实"；③照 `test_weather_alerts_b10.py` 行 159 给残缺替身 ⇒ 全链**不得抛异常**（缺键＝不声明，不是崩溃） |
| T3 | 预警腿三态：`OK/NO_DATA/FAILED` 三形各出各的文案；`FAILED` 不得出现"无预警"字样；`NO_DATA` 不得出现"取数失败" | 新增 `tests/test_weather_alert_states.py` | ①出口返回 FAILED 而文案写成"该地当前无在报气象预警" ⇒ 红；②夹具去掉 `code` 字段 ⇒ 该腿必须判 FAILED（**不许**沿用今天"没 code 也当清单读"的形状）——这条同时抓 `test_city_alerts_sanitized` 的假象，见 R2 |
| T4 | 灾种矩阵不撒谎：对 §4 每一行，源不给 ⇒ 缺席句在场；`none` 类**永不产出条目**；`declared` 类必带"清单未见实例"注 | 新增 `tests/test_weather_disaster_coverage_honesty.py`（语料＝`alert_taxonomy.categories()` 派生，不手抄枚数，规则 10） | 把某 `availability="none"` 的类别临时改成 `observed` 的内存合成表 ⇒ 缺席句消失必红（照 dup-drift 锁的合成数据手法，`test_copy_redline_gate` 头注行 17「注毒只在 tmp_path 造样本」同纪律） |
| T5 | 非 NMC 支路有预警口径：乡镇/海外查询 ⇒ 断言 `weather_alert_path` 标签 ∈ {admin_backfill, global_event, absent}，且 `absent` 时正文含缺席句；**不许再出现"今天这段根本没出现"** | 改 `tests/test_weather_alerts_b10.py` 行 152-168（该断言即缺口本身，见下 ⚠） | 把行 414 的门改回 `if source == "nmc"` ⇒ T5 必红（这是"证明改动真的执法"的唯一手段） |
| T6 | 单页不再谎报全量：`page.count > 实收` ⇒ `truncated=True` 且正文/审计留痕；`provinceAlarms` 被消费（省级段独立） | 用 `tests/fixtures/emergency_info/nmc_findAlarm.sample.json` 真字节（count=328/300）跑 T6 | 把 `_ALARM_PAGE_MAX` 设 1 且不标注 ⇒ 断言"truncated 必须 True"红；把 `provinceAlarms` 读取删掉 ⇒ 省级段断言红 |
| T7 | TLS 验证在场（**扩面**）：天气腿经由的每一次 `http_get_json` 都不得带 `verify_ssl=False`，**包括穿过 `domains/emergency_info` 的那一腿** | 改 `tests/test_weather_tls_verification.py`：AST 扫描面从 `domains/weather/**` 扩到「天气腿实际经由的模块集合」（由真身声明派生，不手抄路径），行为锁补一枚经 bridge 的调用捕获 | 把 `nmc_alarm.py` 行 412 的 `verify_ssl=False` 留着不修 ⇒ 扩面 AST 锁必红（**当前判据面抓不到它，见 R1——T7 这条是本工单的止血点**） |
| T8 | 同名先问：码表同名跨省（实测 6 组）与 geocoding `ambiguous` 各出一条澄清、第二次带 `省-市` 后不再问 | 新增 `tests/test_weather_ambiguous_place_ask.py` | 把择一改回静默首条 ⇒ 问句断言红 |
| T9 | 文档/生成物一致：板块页 + catalog + `docs/auto-facts.md` + AGENTS 载体列同批跟随；`qx.json` 在位 | `pytest tests/test_doc_link_integrity.py tests/test_cross_validation_gates.py tests/test_documentation_consistency.py tests/test_board_taxonomy_gate.py` ＋ `test -f plugins/bot_unified_runtime/domains/weather/assets/qx.json` | 删载体列里新落点那一格 ⇒ 子门③「字面是否真身」红；手抄计数进叙述文档 ⇒ `test_narrative_docs_defer_volatile_counts_to_machine_ledger` 红 |
| T10 | 中央缝与配置面不破 | `pytest tests/test_generic_executor_facets.py tests/test_orchestration_callsite_wave3_b.py tests/test_prepared_adapter_canary.py tests/test_config_key_registration_ledger.py tests/test_wx_t6_timeout_plumbing.py` | 给 builder 加必填参 ⇒ 结构判据红；把 timeout 改回字面量 ⇒ AST 锁红 |
| — | 存量红对账 | 主树复原后**先全量复跑并把输出完整落盘**（`--junitxml`，勿用管道 tail——`HANDOFF-RESCUE-20260930.md` 行 201 的教训），按**节点 ID** 分桶，再与本波新增红比 | ⚠ `test_capability_appends_alerts_on_nmc_hit_only`（HEAD 行 140-168）**当前静态即 TypeError**（替身不接 `timeout=`），且它把 G2 钉成期望 ⇒ 本波**同批**改它（改成 T5 的形态），并先在报告里写明"该枚红非本波新造"（判据：`git archive HEAD` 抽到仓库外同尺复跑，台账 #68★ 正道） |

**门命令**（一律经 `scripts/dev.ps1 -Task test|lint|typecheck|runtime-layout`；绕开必带规则 6 卫生前缀）。真机：`python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute`，并把 `scripts/e2e_acceptance.py` 天气三枚 MatrixItem 的 `note`（行 983、1134、1144-1145）按新行为改写。

---

## §7 风险与回滚

**R1（最高）· TLS 验证会被"复用"静默降级。** 天气腿若直接调 `nmc_alarm.fetch_nmc_alarms/fetch_nmc_station_alarm`，就把 `verify_ssl=False`（`nmc_alarm.py` 行 412/435，http_util 真身 `domains/link_parse/parsers/http_util.py` 行 157/305/385 认该关键字）带进了"预警标题直接进群聊正文"的通道，而 `test_weather_tls_verification.py` 的 AST 锁**只扫 `domains/weather/**`**（行 60-66）、行为锁**只捕 weather 模块命名空间的 `http_get_json`**（行 121/133）⇒ **两把锁全绿，降级照跑**。这正是台账 #48★「AGENTS 叙述≠真身」与"证明缺席且代次>0"型缺牙的同族病。**处置**：S3 第 6 步先修上游，再上 T7 扩面锁；顺序颠倒＝假绿上线。

**R2 · 预警腿的 monkeypatch 出口会失效 / 夹具形状不匹配。** 现有两件测试按 `domains.weather.capabilities.weather.http_get_json` 打补丁（`test_weather_alerts_b10.py` 行 63-67、`test_weather_data_boundary.py` 行 151-152）。腿一走 `emergency_info.sources.http_get.resolve_document`，补丁点失效 ⇒ **测试会打真网络**（离线纪律破，且 CI 上表现为慢/随机红）；同时 `test_city_alerts_sanitized` 的假响应**没有 `code` 字段**，而 `parse_nmc_alarm_page` 要求 `str(code).strip()=="0"`（`nmc_alarm.py` 行 244-246）⇒ 该枚从"解析成功"变 `FAILED`。**处置**：同批改补丁点（改注入 `fetch=` 替身，签名见 `fetch_nmc_alarms(..., fetch: FetchJson|None)` 行 399）与补 `code:0`，或天气侧保留自己的取数出口但**消费同一个纯解析件**（`parse_nmc_alarm_page` 是纯函数、零 IO，属最安全的复用面）。

**R3 · 中央硬超时先落（存量）。** §5 现算：最坏 105.5s > 外层 45s。互证与翻页若塞进变体循环会把这条更容易踩到。**处置**：S3/S5 的"不进变体循环 + 腿封顶"是硬约束；本波只出账不"化妆修复"（板块 README 行 60 的裁定继续有效），把预算收紧列为独立评审项。

**R4 · dup-drift 锁与"上提单源"的批次耦合。** 若本波把拆色/色序上提成公共件，`tests/test_emergency_weather_dup_drift_lock.py` 必须同批改锁单源（其头注行 10-14 允许）；只动一边必红另一边（台账 #68★）。跨域搬迁还牵 `domains/core/board_taxonomy.py` 的归属与 G-P1 零余量上限（§1.5）⇒ **本工单不做上提**，只加"新件必须 import 真身、不许复制表字面量"的 AST 锁。

**R5 · 生成物写口可能被挡。** `docs/auto-facts.md`/`command-catalog.md` 的重生成依赖 `echo.py` 等源件在库（台账 #70 记「echo=T8 源件未入库挡 `--write`」）⇒ 主树复原顺序在前，S6 在后；顺序错则 S6 的红不是本波缺陷。

**R6 · 第三套 open-meteo 客户端风险。** `temporal.py` 行 212-320 已存在第二套（同一上游、不同字段、httpx 复用 LLM 单例客户端）。本波若"顺手"把互证腿也接到 temporal 那条腿，会把**可选上下文腿**与**命令热路径**混成一团（两套缓存/后台刷新语义不同）。**处置**：互证只用 `domains/weather/data/open_meteo.py`；把"收编 temporal 那条腿"列为**独立格**（另席），不在本工单夹带。

**R7 · 海外源误当国内口径。** GDACS `alertlevel` 全 Green 时 `color_label=""`（行 54 故意不映射）⇒ 定级为空、按"无等级"显示，**不得**渲染成黄色或"未知等级"糊弄（`contracts.py` D-1 行 19-20）；USGS `all_hour` 全球通道**零震级门槛**（`collector.py` 行 84-90 审计 E6-N1 的教训）⇒ 天气腿只走 `fetch_usgs_quakes(min_magnitude=...)` 那条有门槛的路，且门槛常量真身不许在天气域重写第二枚。

**R8 · 用户可见文案。** 新增串全部过 `test_copy_redline_gate.py`（Critical 词表 + 降级句尾 Important）；好感度/人格语气面不涉及（纯查询、`risk_level=LOW`、`privacy_level=PUBLIC` 保持不变，行 437-438）；缺席句不得写成攻击/强硬口吻（规则 8）。

**回滚（逐格独立，一格一 commit）**

1. S2（互证）＝纯增量：把 `weather.py` 装配处的 `cross_note` 一行短路（或 `crosscheck_weather` 首行 `return WeatherCrossCheck(0,0,(),...)`）⇒ 恢复今天行为，其余格不受影响。**禁**"整片 revert `weather.py`"——该文件被并发席改过的先例见 AGENTS 第四部分「统一错误报告卡」那格（`pipeline.py` 现盘已被并发席改过，禁盲 cp 的同族教训）。
2. S3（预警腿）＝最大风险格：`nmc_alarm_bridge.py` 里留一枚模块常量开关（**不是配置键**，避免 §1.5 三面齐成本）`USE_LEGACY_FETCH = False`，置 True 即回到旧 `fetch_city_alerts` 路径；回滚＝翻常量 + 一个 commit。
3. S4（灾种矩阵）＝只读派生，回滚＝撤展示段调用行，注册表一字不动。
4. S5（同名先问）＝有打扰面风险，回滚＝关 `_maybe_ask_ambiguous` 的调用点；S6（文档）＝与代码同批回滚，不许留"文档说已互证、码没互证"的第二例（台账 #48★）。
5. 主树侧：任何回滚前按规则 9 拍保险；`ChatBot_Runtime/**` 与 `assets/qx.json` **绝不动**（.gitignore 否定规则在册，2026-09-13 误清致 NMC 整体塌向 Open-Meteo 就是今天 G2/G6 的放大版）。

---

## §8 待验 / 待裁（不许静默结案）

**待验（本席无源码、禁跑门，全部只读取证到边界为止）**

- V1 `open_meteo` geocoding 是否真回 `admin2/admin3`、`population` 之外还有哪些层级字段——**必须先实测取字节、落本域夹具**（夹具目录 README 行 5-7「禁止自造字段」），再写解析；拿不到 ⇒ 路 A 直接落路 C。
- V2 `tests/test_emergency_info_sources.py` 是否钉了 `verify_ssl=False` 的方向（本席只确认该文件出现字样，未逐条读断言）。
- V3 `test_capability_appends_alerts_on_nmc_hit_only` 在净身 HEAD 是否实红（静态推定 TypeError；`HANDOFF-RESCUE-20260930.md` 行 201 的尾 13 枚点名 weather_alerts，**未给节点 ID**）。
- V4 NMC `findAlarm` 的 `totalPage`/`next` 字段在生产响应里的形态（夹具含 `totalPage/next/prev/pageNo/pageSize` 键，本席实测键集；翻页上界是否够用＝待实跑）。
- V5 `data.predict`（逐日/逐时预报）在 `rest/weather` 里的字段稳定性——真样例存在（本席读到 `predict.detail` 逐日数组），**本工单未消费它**；若要给"未来三天灾害趋势"须另开一格 + 新锁。
- V6 `http_get.py` 头注行 31-33 引用的「`nmc_weather.py:119` 同口径关校验」是**已被撤销的旧做法**（现盘该处行 128-132 明文撤销）⇒ 注释假账，S3-6 同批改；改前确认没有别的门依赖那句注释文字。

**待裁（用户/主会话点，本席不代拍）**

- C-1 互证阈值五枚数（§S2）：先按真机 20 城 × 2 日跑**读数差分布**给他手筛，还是直接采用工程起点值上线？（推荐：先跑分布——数字一上线就变成门。）
- C-2 海外气象预警接不接 NWS（`api.weather.gov`，夹具在册而**曾被裁定「不接」**，见 README 行 36）：接＝扩 `ALLOWED_HOSTS` + 新采集件；不接＝海外气象预警永远走路 C 诚实缺席。（推荐：**不接**，先把国内乡镇级与全球事件级做扎实。）
- C-3 「同名先问」是否接受多一轮往返（点歌已有先例，天气是查询面，问了就不出数）。（推荐：只在**跨省同名 + 人口判据压不住**时问，其余择一并在正文写实际选中的全层级地名。）
- C-4 预算收紧（§5 建议「主报告腿 ≤28s」）算代码改动，走评审还是先只登记不修？（推荐：先登记 + T5/T3 上线，避免同批动两件在飞面。）
- C-5 台账行编号与新 AGENTS 载体列文案（HEAD 现至 #70，盘上另有未入库 #71；体积软上限 30,000B）——**编号不许删不许重排**（42 处代码注释按号引用）。
