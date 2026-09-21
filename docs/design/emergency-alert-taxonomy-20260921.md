# 紧急信息预警种类全谱 · 定级 · 颜色 · 静默窗击穿 —— 权威规格（WP3，2026-09-21）

> **本件是唯一权威**：代码从这里派生，不反过来。改任何一格的正确顺序是
> ①改本件 → ②改 `domains/emergency_info/service/alert_taxonomy.py` → ③改/加
> `tests/test_emergency_info_taxonomy.py` 的锁。三者不一致时以「测试红」为准。
>
> 触发：用户对「只修地震门槛」的初版方案说「**不够，需要更加完善**」，并逐字给出
> 必须覆盖的全谱（14 类气象灾害预警信号 + 14 项其他相关预警 + 颜色口径）。
> 本件把她点名的每一种都落成注册表里的一行，并**明写哪些当前无源**——
> 仓内红线是绝不编数，所以"谱全"不等于"都有源"。
>
> 真身代码：`plugins/bot_unified_runtime/domains/emergency_info/service/alert_taxonomy.py`
> 回归锁：`tests/test_emergency_info_taxonomy.py`
> 施工记录：`.superpowers/sdd/2026-09-21-fix-wave/impl-WP3-log.md`

---

## 一、颜色与等级的唯一对应（D-3 一寸未动）

| 色词 | 等级 | rank | 是否紧急面（`URGENT_LEVELS`） |
|---|---|---|---|
| 红色 | `P0` | 4 | 是 |
| 橙色 | `P1` | 3 | 是 |
| 黄色 | `P2` | 2 | 否 |
| 蓝色 | `P3` | 1 | 否 |

- 唯一出处：`contracts.LEVEL_COLOR_LABEL`（与 `domains/weather/capabilities/weather.py:112`
  `_ALARM_COLOR_RANK` 同尺度，由 `tests/test_emergency_info_core.py` 的 AST 收编锁钉住）。
- **不新建第五色、不新建第二套 severity**。用户口径的两条陈列序（气象「蓝黄橙红」、
  地震「红橙黄蓝」）是**同一组四色的正反序**，注册表用 `color_tiers`（升序，判据用）
  与 `tier_order`（陈列序，文案用）分别记录，禁止混用。
- 「源没给色」与「色不认识」都不猜档：`build_emergency_item` 缺字段即丢（D-1），
  定级一条不中落 `FALLBACK_LEVEL=P3`（蓝）。

## 二、全谱注册表（31 类 · 9 族）

统计（`taxonomy.count_summary()`，与 `test_registry_scale_matches_the_documented_counts` 同值）：
**31 类 = 有源 21（其中真样例实测 16 + 类型体系收录但样例未见 5）+ 无源 10**。

可用性三态词汇（帮助文案与 catalog 只能抄这三个字面）：
`observed`＝真夹具实测出现过（可复跑）；`declared`＝源体系收录该类型、2026-09-20 样例未见实例；
`none`＝**无源**。

| 类别 id | 中文名 | 族 | 别名（订阅/原文匹配用） | 来源 | 可用性 | NMC 图码 |
|---|---|---|---|---|---|---|
| `typhoon` | 台风 | meteo | 台风、热带气旋、飓风、typhoon | nmc+gdacs | declared | — |
| `rainstorm` | 暴雨 | meteo | 暴雨、特大暴雨、强降雨、短时强降水 | nmc | observed | 0002 |
| `snowstorm` | 暴雪 | meteo | 暴雪、大雪、强降雪 | nmc | declared | — |
| `cold_wave` | 寒潮 | meteo | 寒潮、强降温、剧烈降温 | nmc | observed | 0004 |
| `gale` | 大风 | meteo | 大风、陆地大风、强风 | nmc | observed | 0007 |
| `dust_storm` | 沙尘暴 | meteo | 沙尘暴、强沙尘暴、扬沙、浮尘 | nmc | declared | — |
| `heatwave` | 高温 | meteo | 高温、酷热 | nmc | observed | 0003 |
| `drought` | 干旱 | meteo | 干旱、气象干旱、秋伏旱 | nmc | declared | — |
| `lightning` | 雷电 | meteo | 雷电、雷暴、打雷、闪电 | nmc | observed | 0012 |
| `hail` | 冰雹 | meteo | 冰雹、雹灾 | nmc | observed | 0009 |
| `frost` | 霜冻 | meteo | 霜冻、霜害、早霜、晚霜 | nmc | observed | 0013 |
| `fog` | 大雾 | meteo | 大雾、浓雾、强浓雾、团雾、雾 | nmc | observed | 0005 |
| `haze` | 霾 | meteo | 霾、雾霾、灰霾、重霾 | nmc | declared | — |
| `road_ice` | 道路结冰 | meteo | 道路结冰、路面结冰、积雪结冰 | nmc | observed | 0011 |
| `severe_convection` | 强对流天气 | meteo | 强对流、强对流天气、雷雨大风、雷暴大风、飑线 | nmc | observed | 0015（另 0042） |
| `sea_thunder_gale` | 海上雷雨大风 | meteo | 海上雷雨大风、海上大风 | nmc | observed | 0000 |
| `geo_hazard_risk` | 地质灾害气象风险 | geo | 地质灾害、地质灾害气象风险、山体滑坡、滑坡、泥石流、崩塌 | nmc | observed | 0021 |
| `mountain_flood_risk` | 山洪灾害气象风险 | hydro | 山洪灾害、山洪、山洪灾害气象 | nmc | observed | 0024 |
| `river_flood` | 中小河流洪水 | hydro | 中小河流洪水、中小河流、河流洪水 | — | **none** | — |
| `waterlogging` | 渍涝 | hydro | 渍涝、内涝、城市内涝、农田渍涝 | — | **none** | — |
| `flood_event` | 洪水（国际事件） | global_disaster | 洪水、洪灾 | gdacs | observed | — |
| `forest_fire_risk` | 森林火险 | fire | 森林火险、森林火险等级、森林（草原）火险 | — | **none** | — |
| `grassland_fire_risk` | 草原火险 | fire | 草原火险、草原火灾风险 | — | **none** | — |
| `wildfire` | 森林草原火灾（国际事件） | global_disaster | 野火、林火、草原火灾 | gdacs | observed | — |
| `storm_surge` | 风暴潮 | marine | 风暴潮 | — | **none** | — |
| `ocean_wave` | 海浪 | marine | 海浪、大浪、灾害性海浪 | — | **none** | — |
| `tsunami` | 海啸 | marine | 海啸 | — | **none** | — |
| `sea_ice` | 海冰 | marine | 海冰、结冰 | — | **none** | — |
| `earthquake` | 地震 | quake | 地震、震情、地震速报 | icl+usgs+gdacs | observed | — |
| `volcanic_eruption` | 火山喷发 | volcano | 火山、火山喷发、火山灰 | — | **none** | — |
| `space_weather` | 空间天气 | space | 空间天气、地磁暴、太阳风暴、磁暴、太阳耀斑、极光 | — | **none** | — |

### 2.1 十类无源的逐条理由（不许用"暂时没接"糊过去）

| 类别 | 为什么无源 |
|---|---|
| `river_flood` 中小河流洪水 | 水利部＋中国气象局联合发布，本域四源端点无此通道；GDACS 的 `FL` 是**洪水事件**不是**中小河流洪水气象风险**，拒绝伪映射 |
| `waterlogging` 渍涝 | 四源无该类型；NMC 2026-09-20 样例的 14 种 kind 里没有 |
| `forest_fire_risk` 森林火险（等级预报） | 火险等级预报不在四源端点内；已发生的火灾另有 `wildfire`（GDACS WF 实测 84 条） |
| `grassland_fire_risk` 草原火险 | 同上 |
| `storm_surge` 风暴潮 | 国家海洋预报台通道未接入 |
| `ocean_wave` 海浪 | 同上 |
| `tsunami` 海啸 | GDACS 体系里有 `TS` 码，但真样例 101 条里没有一条——不据"体系里有"宣称可用 |
| `sea_ice` 海冰 | 海洋预报通道未接入 |
| `volcanic_eruption` 火山喷发 | GDACS 体系含 `VO` 码但样例未见；本域无火山通道 |
| `space_weather` 空间天气 | 国家空间天气监测预警中心通道不在四源内；NMC findAlarm 不发该类 |

订阅这些类别**不会被拒**（那是用户的判断），但回显必须明说「订了也不会有推送」，
`/bot 紧急信息 帮助` 与 `docs/command-catalog.md` 同样如实列（措辞见 §八）。

### 2.2 NMC 类型码（实测派生，非官方表抄录）

`pic` 文件名形态 `p{类型:04d}{等级:03d}.png` 由真样例
`tests/fixtures/emergency_info/nmc_findAlarm.sample.json`（300 条）逐条扫出，
共 14 枚类型码：

```
0000 海上雷雨大风   0002 暴雨   0003 高温   0004 寒潮   0005 大雾   0007 大风
0009 冰雹   0011 道路结冰   0012 雷电   0013 霜冻   0015 雷雨大风
0021 地质灾害   0024 山洪灾害   0042 雷暴大风
```
等级末三位实测到 `002 橙 / 003 黄 / 004 蓝`；`001`（红）**未在本次样例中出现**，
`NMC_LEVEL_SUFFIX_TO_COLOR` 仍按 NMC 色序收录，但定级**只走标题色词**，
不据图码猜红。类型码↔映射表严格相等由
`test_every_observed_nmc_kind_code_in_the_real_sample_is_mapped` 双向锁住。

## 三、族与色档

| 族 id | 名称 | 合法色档（升序） | 陈列序 | 可击穿静默窗 | 依据 |
|---|---|---|---|---|---|
| `meteo` | 气象灾害预警信号 | 蓝黄橙红 | 红橙黄蓝 | P0,P1 | 用户口径「气象类多为蓝、黄、橙、红」 |
| `hydro` | 洪涝与水文气象风险 | 蓝黄橙红 | 同上 | P0,P1 | 沿用四色；源不给色即不定色 |
| `geo` | 地质灾害气象风险 | 蓝黄橙红 | 同上 | P0,P1 | 同上 |
| `fire` | 森林草原火险 | 蓝黄橙红 | 同上 | P0,P1 | 同上（当前该类无源） |
| `marine` | 海洋类 | 蓝黄橙红 | 同上 | P0,P1 | 同上（当前该类无源） |
| `space` | 空间天气 | 蓝黄橙红 | 同上 | P0,P1 | 同上（当前该类无源） |
| `quake` | 地震 | 蓝黄橙红 | **红橙黄蓝** | P0,P1 | 用户口径「地震预警常用红、橙、黄、蓝」 |
| `volcano` | 火山 | 蓝黄橙红 | 红橙黄蓝 | P0,P1 | 同上（当前该类无源） |
| `global_disaster` | 国际灾害事件（GDACS） | **橙、红** | 红、橙 | **仅 P0** | **实证**：`sources/gdacs.py:54` 只映射 Red/Orange，Green 故意为空 |

**色档的用途只有两条**（刻意不作"官方逐类色档"声明）：
① 校验用户在订阅里能说的话——「蓝色以上」用在 `global_disaster` 族上当场报错并给候选；
② 族级穿窗地板——GDACS 的橙色（"中等相关"）不足以半夜叫醒一屋子人。

> 未取证之处不装懂：例如「高温无蓝色」「霾无红色」这类**逐类**官方色档数，
> 本表不作声明。实际出档由**源侧给出的颜色词**决定（NMC 标题色词是实测字段），
> 源不给色就走关键词/震级路径，都不中则蓝档。

## 四、定级判定序（`service/grading.py`）

```
grade(item, now, rules=DEFAULT_GRADING_RULES):
  0) item.expires_at <= now           → P3（过期不得冒充紧急，D-2 兜底）
  1) category = taxonomy.category_of_item(item)      # 库里 id 优先，否则别名表现算
  2) 若 category 属 quake 族：
       magnitude 有值 → 震级/深度/境内境外分档（唯一档，直接返回）
       magnitude 无值 → 只允许源侧官方色（GDACS Red/Orange）出档；种类词与关键词一律不参与
  3) 其余族：候选 = 源侧 color_label（族内合法才计）
                    ∪ 标题/正文里的族内合法色词
                    ∪ 影响面硬事实关键词（缺省表 + 注入表）
     取最高 rank；空集 → P3
```

- **颜色优先于种类词**：「暴雨蓝色预警」＝蓝档。旧实现把种类词放进 P1 词表并与颜色取
  `max()`，等于凭空把蓝抬成橙，是穿窗误报的来源之一。
- **种类词整体退出关键词表**（`test_default_keyword_table_contains_no_category_words` 锁死），
  残留的关键词只描述"已经造成的后果/已经下达的强制动作"：

  | 档 | 关键词 |
  |---|---|
  | P0 | 特别重大、特大、紧急疏散、撤离、转移安置、停课、停运、溃坝、决堤、死亡、遇难、失联、洪峰、爆炸 |
  | P1 | 重大、山洪、泄漏、泄露、停水、停电、交通中断、封路 |
  | P2 | 积水、管制、延误、道路封闭 |

## 五、地震分档表（本域代理规则，**不是官方烈度色**）

ICL/USGS 只给震级、深度、坐标，不给烈度与影响色，所以「多少级算红」是**产品裁定**。
改数只改 `grading.py` 一处，规格与锁同步。

| 情形 | 红 P0 | 橙 P1 | 黄 P2 | 蓝 P3 |
|---|---|---|---|---|
| 境内（震中在 `CHINA_INLAND_RECT` 内） | M ≥ 6.5 | 5.0 ≤ M < 6.5 | 4.0 ≤ M < 5.0 | M < 4.0 |
| 境外 | —（结构上出不了红） | M ≥ 8.0 | 6.5 ≤ M < 8.0 | M < 6.5 |

- `M < 3.0` 一律蓝档，**且不被任何关键词抬档**（`EARTHQUAKE_INFO_MAX_MAGNITUDE`）。
- 深源 `depth > 100 km` 降一档（`EARTHQUAKE_DEEP_THRESHOLD_KM`），只降一档不降两档。
- 无坐标 ⇒ 判不出境内境外 ⇒ 按**境外**处理（保守不上抬）。
- 无震级数值 ⇒ 该路径不出候选（绝不用「地震」二字顶替一个数）。
- 采集侧同时收紧：USGS 腿回到 E11 §4 裁定的 `fetch_usgs_quakes(min_magnitude=4.0)`
  （fdsnws＋中国矩形＋滚动 24h），不再用无门槛的全球 `all_hour` feed（审计 E6-N1）。

## 六、静默窗击穿显式规则表（交付②）

击穿 00:00–06:00（生产窗由 `policy/quiet_hours` 决定，唯一事实源）需要**四条全真**：

1. `item.level is not None`（未定级不自称紧急，D-1）；
2. `contracts.is_urgent_level(level)`（D-2：只有 P0/P1 属紧急面）；
3. 族级地板允许：`level ∈ family.wake_levels`（§三表；`global_disaster` 只认红档）；
4. 用户配置层允许：`level ∈ bot_emergency_info_quiet_breach_levels`（缺省 `P0,P1`＝与今天一致）。

第 3、4 条不满足时，**投递触点本轮不提交**（`push.deliver_emergency` 返回
`skip_quiet_hours`）：条目仍在库里、等级已回写，出窗后的下一轮照常投递
（按日幂等键此前未被占用），**不是丢弃**。

两条"绝不变吵/绝不变哑"的方向锁：

- `test_deliver_emergency_still_allows_a_wake_worthy_red_at_night`：真闸 + 窗内，
  红色台风预警照旧 `allow`，且 `priority=="P0"` 载体不变（锁 C 同源）。
- `test_quiet_predicate_agrees_with_the_gate_itself`：域内"此刻是否在窗内"的谓词
  与闸自身在非紧急载体上的 defer 行为**逐点等值**（判据取自 `QuietHoursChecker`，
  窗事实取自 `gate.quiet`，禁止第二套窗定义）；读不到窗事实一律**不压人**（fail-open），
  因为把观测面故障变成漏报是错的方向。

## 七、定级回写与三方同值（交付③，审计 E6-N3）

- 回写点＝`EmergencyInfoService.approved_items(limit, now)`：根装配 job 每轮经此取条目，
  是"读侧"与"投递侧"唯一同处一时的位置。
- 定级唯一出口仍是 `ReviewGate.publishable_level`（本函数不自建第二套判定），
  因此回写值与 job 随后重算值必然相等（纯函数 + 同一 `now`）。
- 落库口＝`EmergencyStore.set_level(item_id, level=…, category_id=…)`，
  SQL 守卫 `WHERE status='approved'` 原样保留 ⇒ pending 行永远 NULL（D-8 不松）。
- 幂等：库里已是该值就不再 UPDATE（每轮 50 条 × 数分钟一次，不做无谓刷盘）。
- 存储迁移＝**只加列不改语义**（`ALTER-if-missing` 家规，先例 affinity 三列 /
  WIRE-SUB 的 `latitude/longitude`）：新库建表即带，老库开库补
  `category_id TEXT NOT NULL DEFAULT ''`、`magnitude REAL`、`depth_km REAL`，
  订阅表补 `categories TEXT NOT NULL DEFAULT ''`；老行读出为 `""`/`None`，不硬凑。

三方同值锁：`test_query_side_and_delivery_side_report_the_same_value`
（库里 == 读侧 == 投递侧）。

## 八、订阅面口径（交付⑤）

- 类型维度＝**注册表类别 id ∨ 开放词表原文**（旧策略一寸不收）：
  认得出的词进 `SubscriptionRule.categories`（精确/别名命中），
  **同时**保留在 `kinds`（原文子串老路仍通），命中判定走「∨」。
  ⇒ 订阅「雷暴大风」能收到标题写"强对流天气"的条目；老库里的旧规则不会突然变哑。
- 色档按族校验：`validate_levels_against_categories` 在解析末尾执行，
  对每个已登记类别检查其族合法色档，越档 ⇒ `RuleError` + 该族合法档作候选回显。
- 无源类别：规则照设、回显明说（`unsourced_terms()`），绝不静默收下。
- 语法不变（裁定 1.C）：`area=<地名> kinds=<词> levels=<P0,P1 或 橙色以上> radius=<km> coord=<纬,经>`
  与自然语序 `湘潭 暴雨 橙色以上` 同等可用。

帮助文本需要新增的措辞（**由主会话落 `echo.py`**，本席禁改该文件）：
「本域按注册表 31 类预警种类定级与订阅；其中 10 类当前无源（中小河流洪水、渍涝、
森林火险、草原火险、风暴潮、海浪、海啸、海冰、火山喷发、空间天气），订阅会照记但
不会有推送；订阅时可用的色档按族校验，国际灾害事件族只有橙、红两档。」

## 九、本件明确**不做**的事

- 不做逐类官方色档的断言（未取证）。
- 不给无源类别造映射（风暴潮 ≠ 台风、海啸 ≠ 地震、森林火险 ≠ 野火事件）。
- 不让定级读墙钟、读 config、发网络请求（AST 锁在位；本次只把**同域纯数据件**
  `alert_taxonomy` 加进 `grading.py` 的允许 import 前缀，两条判据不变）。
- 不碰 `qx.json`（只读；地名索引仍由 `subscriptions._area_index()` 自己读）。
- 不引入第二个静默窗定义、第二个等级枚举、第二条投递路径。
