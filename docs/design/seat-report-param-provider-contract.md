# seat-report 参数来源契约：`role` / `status` / `wave`

> 席 **S211** 交付（2026-09-23，第卅一批）。**本件是契约，不是实现**：本席独占面内不写 provider 码、
> 不改 `scripts/doc_template_sync.py`、不改 `docs/templates/**`（均为公共只读面）。落码由主会话单点执行。
> 派工单原文见 `.superpowers/sdd/2026-09-22-taxonomy/BRIEFS.md` §S211。
> 全部数字为**本席现算当时值**（复跑口见 §6），依铁律 10 不视为长期事实。

## 0. 两处工单前提更正（依前言第五条「动手前先复现」）

| 工单写法 | 盘面真身 | 证据 |
|---|---|---|
| 三枚参数含 **`wave_id`** | seat-report 的键名是 **`wave`**；`wave_id` 是 `brief`/`handoff`/`sdd-ledger` 三枚模板的键 | `docs/templates/seat-report.md:5`、`brief.md:4`、`handoff.md:5`、`sdd-ledger.md:4` |
| `role` 候选源含 **模板 `@aliases`** | **结构上不适用**：`@aliases` 只解析进 `Schema.slot_aliases`，供**节名**匹配（`_match_slot`），params 侧无任何别名通路 | `scripts/doc_template_sync.py:59,88-90,154-167` |

⇒ 本契约按真身键名 `role`/`status`/`wave` 出规格；`wave_id` 三枚模板的同类缺陷一并在 §4 处理（同一份在册表可同服四桶）。
除这两条外工单前提成立，本席**不判 EXPIRED**。

## 1. 桶的现算规模（本席开工时刻）

| 量 | 现算值 |
|---|---|
| seat-report 桶总页数 | **523** |
| 已驱动（门侧 `parse_front_matter` 认 `template: seat-report`） | **27** |
| 未驱动 | **496** |

对账 N-2（简报写 508 桶 / 36 参齐 / 466 缺参）：桶自 S198 之后被后续席位新增的 `SEAT-*.md` 顶高 **15 枚**，属正当跟随，**非口径冲突**。
本席另核出一枚**假驱动页**（列 §5-D）。

## 2. 契约总表（每枚参数：唯一真身 + 取值域 + 缺失行为）

统一约束：缺失一律 **fail-closed 到「该页不可驱动」**。既有判据已具备此形状，无需新码：
`MISSING_PARAM` / `PROVIDER_MISSING` / `PROVIDER_FAIL` / `PROVIDER_EMPTY` / `DOMAIN_FAIL`
（`scripts/doc_template_sync.py:815-882`，G-T4 码集 `scripts/spec_gates_census.py:272-285`）。
**禁止**为凑驱动率造默认值（`role: report` 之类）——那等于把 G-T4 的缺参红换成 G-T4 的绿账。

| 参 | 声明 | 唯一真身（契约） | 取值域 | 缺失时行为 | 现成 provider |
|---|---|---|---|---|---|
| `role` | `enum \| literal \| req` | **新建**：波次在册席位表的 `role` 列（§4）。轴文本**不是**真身（§3-A） | `impl,readonly,conversion,gate,measurement,report` | 不在册 ⇒ `PROVIDER_FAIL` ⇒ 不可驱动 | 无（`seat_role` 待主会话落） |
| `status` | `enum \| literal \| req` | **既存真身**：页体 `Status:` 行（`_provider_body_status`） | 同 `_STATUS_LINE_RE` 四值 | 无合规行 ⇒ `PROVIDER_FAIL`；行内值越域 ⇒ `DOMAIN_FAIL` | **有**：`body_status`（已在 `PROVIDERS` + `PROVIDER_SOURCES` 申报 `page:页体 ^Status: 行`） |
| `wave` | `text \| literal \| req` | **新建**：波次在册表（§4）。目录名**不是**真身（§3-C，正面回应 S184「文件名回声」判定 `SEAT-S184.md:250`） | 在册 `wave_id` 集成员 | 该页所在目录不在册 ⇒ `PROVIDER_FAIL` | 有 `path_wave`，但**只可作候选生成器，不可作真身判据**（§3-C） |

**改标代价必须同读**：第廿九批判决段第 1 条已证「把有源必填参改标 `auto:` 会结构性新增 72 枚 G-T4」。
机制原因在 `resolve_params`：source 为 `auto:X` 时，页内字面量必须**逐字**等于 `auto:X`，否则 `AUTO_SOURCE_MISMATCH`（`:839-844`）。
⇒ 任何一枚参改 `auto:` 都**同时**要求全部目标页 front-matter 改写；这是主会话的批量动作，不是本契约能顺带做的。
本契约只定「改成什么、谁的页能跟上、跟不上的怎么记」。

## 3. 逐枚评估

### A. `role` —— 今天**没有**机器可读真身

三个候选各自评估（覆盖数＝未驱动 496 页口径，本席现算）：

1. **OWNERSHIP 问题轴列**（`OWNERSHIP.md` 表「问题轴」）：命中 **93/496**。
   缺陷不只是覆盖率——轴文本是自由散文（例「`GATE-*`/立门＝gate」这条映射**只写在 `docs/templates/seat-report.md:33-47` 的散文里**）。
   provider 若照抄这套关键词，就是**在同仓造第二真身**（判据住在只读模板正文、实现住在 py），本项目假绿册的既有形态。
2. **BRIEFS 小节标题后缀**（`## S196 FREEFORM-INSTANCE-CONSUMER-LOCK ——`）：命中 **160/496**，且 **OWNERSHIP 命中集是它的子集**（`own|brief` 任一 = 160 = `brief` 单独）。
   机读性好，但它是**派工散文**：每批重写、阵亡席换 id（S199→S206）、跨波次页（`T-*`、`S21R/S23R/S33R` 这类重试席）无从命中。
3. **模板 `@aliases`**：不适用（§0）。

**语义正确性的实弹证据**：本席按模板散文那 6 条规则写了一部启发式映射器，对 20 页样本做「预测值 vs 页内既存人工值」对账 ⇒
可比 17 例中**一致 11 / 不一致 6**（`S163` 预测 `report` 实为 `impl`；`S35` 预测 `gate` 实为 `readonly`；`S13/S202/S23/S25` 多规则同时命中）。
⇒ 结论不是"我的词表写得不好"，而是**轴语义到六值枚举的映射本身不可由现存文本机械决定**。
因此 §4 的在册表必须存**已定的 role 值**，而不是存轴文本再让 provider 猜。

**天花板（量化，交 P-57 用）**：以 `role` 有源论——
`role(OWNERSHIP) ∧ status` = **80 页**；`role(OWNERSHIP∨BRIEFS) ∧ status` = **143 页**；
`role` 两源皆无 = **336 页**（占未驱动 67.7%）。
⇒ 只建 `seat_role` provider（读 OWNERSHIP 现状）**最多解锁 80 页的参数维**，不是 466 页。
且此数**只算参数维**：`交付` 必选节的缺节墙（S184 记 401 页）另计，两者不可相加也不可用 143 宣称"可驱动 143 页"。

### B. `status` —— 真身已存在，改标即可，但有**两处现存越域**

`_provider_body_status` 已在册（`PROVIDERS:570`、`PROVIDER_SOURCES:596`），取值正则逐字为
`^Status:[ \t]*(STARTED|RUNNING|BLOCKED|DONE)\b`（MULTILINE，行首锚定，`scripts/doc_template_sync.py:398-400`）。
本席用真身 provider 与一把宽松正则在未驱动 496 页上对拍：**244 vs 245**，仅 1 枚差异 ⇒ provider 忠实、无系统性漏判。

改标前必须先裁的两处值域问题（数字为**复核席 2026-09-23 现算当时值**，口径见 §7）：

- **枚举外的状态词**：本波 SEAT 页正文行首 `Status:` 实际值域超出模板枚举的有 `SUBMITTED`(3) / `COMPLETE`(2) / `IN`(2) / `DELIVERED`(1) / `DONE_WITH_DISCLOSURE`(1) / `EXPIRED`(1) = **10 处 / 8 页**（全类 occurrence 口径，行首锚定）。
  其中 **`EXPIRED` 是第廿九批前言第五条明文要求的写法**（「立刻在报告首段写 `Status: EXPIRED`」），而 `seat-report` 的 `status` 枚举里没有它 ⇒
  **派工口径与模板值域互相矛盾**。这不是席位写错，是规格缺口；**必须用户/主会话裁**（扩枚举 or 改前言措辞），本席两边都不碰。
  ⚠ 首版本件把这一项写成 `EXPIRED 5 / … = 12 页`，那是**散文提及与行首值混计**（`Status: EXPIRED` 在别席正文里作为规则引用出现多次）；`EXPIRED` 作行首状态值只有 1 页。勘误见 §7。
- ~~大小写：`status: DONE` 小写形态 28 处会被真身正则拒~~ —— **首版此条判据错，已撤**。复核现算：那 28 处里 **27 处是驱动页 front-matter 的参键行**（`status:` 本来就是 params 的小写键名，不是状态标记），另 **1 处是 `SEAT-S188.md:33` 正文里的说明性残句**。真身 provider 只读 `body_no_fm`（front-matter 被剥掉），所以这 28 处**一律不进 `body_status` 的判定面**；且改标后 front-matter 该行须逐字写成 `auto:body_status`（§2 的 `AUTO_SOURCE_MISMATCH` 机制），根本不存在"被大小写拒"的分支。⇒ 本条原先给出的"改标阻断"是虚的，真阻断如下三条（首版漏计）。

**改标 `auto:body_status` 的真实前置清单**（复核席现算，27 枚已驱动页全量、非抽样）：

| # | 页 | 现状 | 改标后行为 | 必须先做什么 |
|---|---|---|---|---|
| 1 | `SEAT-S171.md` | front-matter `status: DONE`，正文**无**行首合规 `Status:` 行 | `PROVIDER_FAIL` ⇒ 由"已驱动"跌回不可驱动 | 补页体状态行，或该页保持 `literal` 例外并登记 |
| 2 | `SEAT-T-TRANS1R.md` | 同上（`status: DONE` 而正文无状态行） | `PROVIDER_FAIL` | 同上 |
| 3 | `SEAT-T-SHAPE.md` | front-matter `status: DONE` 与正文 `Status: STARTED` **互相矛盾** | 渲染值从 `DONE` 翻成 `STARTED` | 先裁哪一侧是真（正文行是活性事实，字面量疑为抢先手写）；不许两边同时留 |

⇒ `status` 改标**不是**"零成本、28 处待清洗"，而是"3 枚既存页需先各自裁一个事实"。前两条同时是 §4 过渡期口径的输入：改标一旦发生会**净新增**未驱动页，驱动率不升反降，主会话落码时必须按这三枚点名处置。

契约取法：`status | enum | auto:body_status | req | enum:STARTED,RUNNING,BLOCKED,DONE`；越域值 `DOMAIN_FAIL` 如实红，无状态行 `PROVIDER_FAIL` 如实红，都不许静默降级。

### C. `wave` —— 正面回应「文件名回声」

S184 判：「`wave_id` 若要语义正确，需要一份**波次在册表**（当前只有目录名与 `SEAT-MAIN.md` 散文）；没有它，任何派生都只是文件名回声」（`SEAT-S184.md:250`；另 `:167` 主张 provider 内对在册席位表校验成员资格）。

本席实测支持该判定，并给出可核验的量化形式：`_provider_path_wave` 在未驱动 496 页上 **成功率 496/496 = 100%**，
且 27 枚已驱动页的 `wave` 实值**全部**等于所在目录名 `2026-09-22-taxonomy`。
一个**永不失败、且必然等于被测对象自身属性**的派生，其信息量为零：它无法抓住任何一枚放错目录的页，
也无法否认一枚伪造的 `wave:` 字面量。⇒ `path_wave` 可保留作**候选生成器**（S184:167 的形状：先派生、再对在册集校验成员资格，不在册即抛），
但**不得充当 `@schema` 的 source 真身**。

**结构性判定（工单④要求明写）**：`wave` 与 `wave_id` 这两枚参数**今天结构性不可驱动**，必须先建在册波次表；
在此之前把它们改标 `auto:path_wave` 只是把"人手不碰数"的口号套在一枚回声上，属本批红线禁止的"发明数据源"。

## 4. 波次在册表的最小形状（本契约的核心新建件）

一枚表同时服 `role` 与 `wave` 两参，避免造两份真身。

| 维度 | 规定 |
|---|---|
| **放哪** | ① 跨波清单：`.superpowers/sdd/_WAVES.md`（一波一行）。② 波内席位名册：`.superpowers/sdd/<wave>/SEAT-ROSTER.md`（一席一行）。二者都是**声明式 Markdown 表**，与 `OWNERSHIP.md`/`CENSUS.md` 同族，不新增 py 真身 |
| **谁写** | 主会话。派工时刻写（它本来就在写 `BRIEFS.md` 小节与 `OWNERSHIP.md` 认领行 ⇒ 同一次动作追加一行，零新增仪式）。席位**只读不得自填**——否则 role 又变成页侧手写事实，与 §2 的 fail-closed 契约相悖 |
| **谁读** | 唯一取数口 = 新增两枚 provider：`registered_role`、`registered_wave`（`scripts/doc_template_sync.py::PROVIDERS` 各加一行）。形状比照既有"枚举校验类"五枚（`_candidate()` 派生候选 → 真身集校验 → 不在册即 `ValueError`，见 `:426-434,485-561`）。`PROVIDER_SOURCES` 必须同步申报两个文件路径，否则装载守卫 `_provider_source_guard`(`:744-760`) 点名 `PROVIDER_NOT_REGISTERED`——这条守卫已存在，**零新判据** |
| **形状（席位名册）** | `seat_id \| role \| wave_id \| brief_ref`。`role` 取 §2 六值枚举**之一**（表内即终值，不是轴散文）；`seat_id` 与 `_SEAT_ID_RE` 同源；`wave_id` 必须是 `_WAVES.md` 的在册行（双表互查，防孤儿名册）；`brief_ref` 指工单坐标，供人复核映射出处 |
| **哪道门执法** | ① **G-T4 现有腿**即执法缺参：页挂了 front-matter 而名册无该席 ⇒ `PROVIDER_FAIL`（`resolve_params:852-856`）。② 另加一枚**在册覆盖率地板**锁（只准升，防"名册被清空而门仍绿"的空集恒真——本批第五条同型事故）；该锁基线须写成**只准减的欠账账**并在门 docstring 双向点名（第卅批红线④，S196 先例）。**不建议**新增第八道门，覆盖面 G-T1..T5 + G-P1..P2 + G-C1 已含此判据位 |
| **禁** | 不得另写第二份名册解析器（provider 是唯一取数口）；不得用目录名/文件名反推 role；不得为提升驱动率把 `role` 改 `opt` 或塞默认值 |

**过渡期口径**（名册建成之前）：三枚参数保持 `literal`，缺 role 的 336 页与 status 越域的 8 页／3 枚改标阻断页（§3-B 前置清单），**照实计入 G-T1 存量**，
不得用降必选槽、改判据或写"本页豁免"的方式出账（第廿九批判决段 + 第六条红线）。

## 5. 本席顺带查实、须交回主会话的四件（均**不在**本席独占面内，未动）

- **A. `P-57` 未落 PARKED**：`BRIEFS.md:2939,2987,2993`、`ledger:203,224`、`SEAT-MAIN.md:784-785`、`SEAT-S198.md:7,28`、`findings.md:97` 共 9 处引用 `P-57`，
  但 `PARKED.md` 现有条目最大号是 **`P-56`**，全文件无 `P-57`。⇒ 一条被四处当"在册待裁"引用的裁定，实际**不在册**。请主会话补登或指明它改挂何号。
- **B. `Status: EXPIRED` 词表冲突**（§3-B）：前言第五条明文要求 vs `seat-report` `status` 枚举无此值。**待裁**。
- **C. `seat_id`/`wave`/`status` 三枚均声明 `literal`，而对应 provider 早已注册**（`seat_id_from_name`/`path_wave`/`body_status`，`:567-570`）——
  机制在、`@schema` 不用。这三枚的"literal vs auto"分歧应由主会话按 §2/§3 一次性裁，不留"机制存在但装配落空"的旧形态（紧急域 D-8(a) 前例）。
- **D. 假驱动页 `SEAT-S188.md`**：页内含 `template: seat-report` 字面行（`grep -l` 命中，故任何用 grep 数驱动页的席报都会多算 1 枚），
  但门侧 `parse_front_matter` **不认**它 ⇒ 真身现算它是**未驱动**。恰为前言②「静态 grep 全绿而运行期不认」同型。
  与 S188「刻意自留未驱动页」的声明一致，但**页体那行 front-matter 残留**会持续误导任何 grep 口径，建议归 S198/S209 面处置。

## 5-附 · 第卅二批独立复核记录（续跑席 S211-R，2026-09-23）

首版 S211 交卷后本席被同 id 复派。按铁律 5（"已完成"必须带可复跑命令 + 实跑输出）与前言第五条（动手前先复现），
本席**不重写契约**，只做逐枚独立复核：全部取数走真身口（`dts.walk_content_pages`/`classify`/`parse_front_matter`/`PageCtx`/`PROVIDERS`），
临时件 `%TEMP%/s211_verify.py`、`%TEMP%/s211_verify2.py`，源码树零写入。复跑命令见 §6。

| 首版断言 | 本席现算 | 判定 |
|---|---|---|
| 桶 523 / 驱动 27 / 未驱动 496 | **523 / 27 / 496** | ✅ 逐位复现 |
| `path_wave` 未驱动 496/496＝100%，且派生值必在自身路径内 | **496/496 ok、0 fail、496 枚值原样出现在本页 rel 中** | ✅「回声」判定成立且更强（永不失败 ∧ 必等于被测对象自身属性） |
| 27 枚驱动页 `wave` 实值全等目录名 | **27/27 相等**；全树字面量 `wave` 只有 `2026-09-22-taxonomy` 一个值 | ✅ |
| `body_status` 命中 244（宽松对拍 245，差 1） | **245 / fail 251（和＝496）** | ✅ 判定不变，+1 属语料在飞跟随（首版之后本席报告页自身落盘） |
| OWNERSHIP 命中 93 / BRIEFS 命中 160 / own ⊆ brief / 两源皆无 336 | **98 / 165 / 子集关系 True / 两源皆无 104（SEAT 命名页口径）** | ✅ 判定不变（分母随语料长）；⚠ 首版 336 是"未驱动全集"、本席 104 是"其中文件名可解出 seat_id 者"，两口径**不可互换**，引用时须点名 |
| 首版新证据（本席补）：命中集是否被跨波次同名席位号灌水 | **越波碰撞 0 枚**（own/brief 命中全部落在本波目录内） | ✅ 覆盖率不是撞名撞出来的 |
| role 启发式：一致 11 / 不一致 6（S163、S35、S13/S202/S23/S25） | 本席另写一部词表不同的映射器：**一致 14 / 不一致 2（S20、S23）/ 不可比 11** | ✅ 结论复现且**加固**——两台独立启发式给出**不同的不一致集合** ⇒ "轴文本 → 六值枚举"不可机械决定，不是词表没写好 |
| `status` 小写 28 处会被真身正则拒 ⇒ 改标阻断 | **27 处是 front-matter 参键行、1 处是 S188 正文残句**；provider 只读剥头后的正文 | ❌ **判据错，已在 §3-B 撤条并换真阻断**（3 枚页：2 无正文状态行、1 正文与字面量互斥） |
| 越域 `EXPIRED 5 …=12 页` | **10 处 / 8 页**，`EXPIRED` 行首值只 1 页 | ❌ 数量夸大，口径混淆（见下 §6-附），已在 §3-B/§4 更正 |
| P-57 不在册（PARKED 最大 P-56） | **仍不在册**，而 PARKED 最大号已涨到 **P-59**；15 处引用分布在 9 个件（含 `SEAT-S210.md`/`SEAT-S211.md` 各 1/2 处） | ✅ 且**性质变了**：不再是"号还没排到"，而是**跳号空洞** ⇒ 交回主会话补登或指明改挂 |
| S188 假驱动页 | `parse_front_matter` → **None**、`grep` 字面行 **存在**、真身口径落**未驱动**集 | ✅ 逐点复现 |
| `@aliases` 无 params 通路 | `slot_aliases` 全树仅 4 个读点（`:90` 声明、`:217/:227` 装载、`:972` 节匹配），无一处触 params | ✅ |

**复核引入的一处新风险（须主会话知悉）**：首版 §6 的 `Status:` 值域复跑口是 `grep -hoiE "^[^A-Za-z<\`]*Status:…"`
——`-i` 放宽大小写、前缀 `[^A-Za-z<`]*` 允许行中提到 `Status:`、且不区分 front-matter 与正文。
这条命令的口径**不等于** provider 的口径，首版"越域 12 页 / 小写 28 处"正是从这类宽松 grep 与"参键行"混读而来。
⇒ 复跑口本身必须换成 §6-附 的严格形，否则第三席照抄会复现同一个错数。

## 6. 复跑口（本契约所有数字的来源）

三段一次性脚本，临时件按纪律落 `%TEMP%`（会话后即失，故本件把**口径**写全而不只贴路径）：

```
# 桶规模 / provider 覆盖 / 20 页对账 / role 两源命中
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
  ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/s211_probe.py"
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
  ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/s211_ceiling.py"   # 假驱动页 + 解锁天花板
```

脚本内**只 import 真身取数口**（`doc_template_sync` 的 `walk_content_pages`/`classify`/`load_schemas`/
`parse_front_matter`/`PROVIDERS`），不自解析 `@schema`、不自写 front-matter 解析器；
唯一自造件是 §3-A 那部**启发式** role 映射器，其用途就是被证明不可靠（一致 11/不一致 6），**不进契约**。
**6-附 · 严格复跑口（复核席补）**：值域统计必须与 provider **逐字同构**——剥 front-matter、行首锚定、大小写敏感，
否则会把「散文里的 `Status:` 提及」和「front-matter 的小写参键行」计成状态值（首版 12 页 / 28 处两个数就是这么来的）。

```python
import re, sys
from collections import Counter
sys.path.insert(0, ".")                      # 仓库根
from scripts import doc_template_sync as dts  # 唯一取数口，不自解析 @schema

vals, pages = Counter(), {}
for p in dts.walk_content_pages():
    if dts.classify(p.rel) != "seat-report":
        continue
    fm = dts.parse_front_matter(p.text)
    lines = p.text.splitlines()
    close = -1 if fm is None else next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), -1)
    for i, ln in enumerate(lines):
        if 0 < i < close:                    # front-matter 内不计
            continue
        m = re.match(r"^[ \t]*Status[ \t]*:[ \t]*([A-Za-z_]+)", ln)
        if m:
            vals[m.group(1)] += 1
            pages.setdefault(m.group(1), set()).add(p.rel)
print(vals)                                  # occurrence 口径
print({k: len(v) for k, v in pages.items()}) # page 口径（两数不等，引用须点名）
```

本席两次实跑件：`%TEMP%/s211_verify.py`（桶规模 / provider 覆盖 / 驱动页对账 / 两源命中 / 越波碰撞 / role 启发式 / P-57 / S188 / @aliases 读点）
与 `%TEMP%/s211_verify2.py`（小写 28 处的归属拆分 / 值域 occurrence vs page 双口径 / 3 枚改标阻断页 / 全树 `wave` 字面量枚举）。

`Status:` 值域分布复跑（**首版宽松口径，仅存目：`-i` 放宽大小写、允许行中匹配、不辨 front-matter，对账请改用 §6-附**）：

```
grep -hoiE "^[^A-Za-z<\`]*Status:[ \t]*[A-Za-z_]+" SEAT-*.md \
  | grep -oiE "Status:[ \t]*[A-Za-z_]+" | sed 's/Status:[ \t]*//' | sort | uniq -c | sort -rn
```
