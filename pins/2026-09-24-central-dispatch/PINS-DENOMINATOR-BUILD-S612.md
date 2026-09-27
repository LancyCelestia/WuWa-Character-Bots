# PINS-DENOMINATOR-BUILD-S612 — pins 分母从 0 建起的最小可执法路径

席位：S612 ｜ 开窗：2026-09-25T13:04Z（主代理派单）｜ 本席交卷：2026-09-25T13:2x–13:3xZ（UTC，逐节落盘）
主件：本文件 ｜ 席目录：`.superpowers/sdd/2026-09-24-central-dispatch/`
完成度：**6/6 节已交**（§0–§6 全部填毕并实跑）｜ 零落码、未读 `.env`、未跑全量（自证见 §6.7）｜ 待她两句见 §6.9
产物：本件 ＋ `probes/s612-probe{1..6}.py`（六发探针，可复跑）

**一句话总结**：三件套十条锁**第一次真跑＝10/10 绿**；pins 分母今天能升断言的是 **2 条（DR-3 全量、DR-2b 限定 7/10 条边）**，其余 4 条卡在同一处结构性理由——**「合法 semver」与「有 annotated tag 作证」两集合的交集为空**（§4 F-4），且**卡点不是"没人填"，而是"填不进"**；另有 3 枚字段（`provides`/`counterparty`/`why`）**在册而零判据读**，本席给出可粘贴的反例锁 L-11 并实跑点名。

## §0 置顶：对简报前提的现算推翻/坐实

本席开工 UTC：2026-09-25T13:2x（`date -u` 见 §6 卫生段）。HEAD 现算 `5cc6832`。

| # | 简报／前席前提 | 本席现算 | 判定 |
|---|---|---|---|
| 0-A | 「pins 分母今值全 0：九词全 0 命中」 | 三树 `.py` 按 `\b词\b` 尺：`workspace_manifest`／`library_id`／`requires_min`／`requires_max_exclusive`／`pinned_version`／`breaking_events`／`bot_version`／`pins`／`_CONTRACT_VERSION` = **9/9 各 0 命中**（子串尺同值 0） | **坐实**（命令 §6.1） |
| 0-B | 三件套「已验证的一行修」尚可直接照抄落仓 | 生成器候选件在 `%TEMP%\s594-mirror\scripts\`：原样 `c0e6d790a23106b7`、修后 `6b590619bfb1d8fa`；`diff --strip-trailing-cr` 语义差**恰一行** `+    sys.modules[spec.name] = mod`（在 `mod = module_from_spec(spec)` 之后、`exec_module` 之前） | **坐实且精确到行**（§3） |
| 0-C | 镜件里那份 `workspace_manifest_sync_fixed.py` 的 diff 只改一行 | 朴素 `diff -u` 把**整文件 166 行全算成改动**——两文件都是全 CRLF，但行数 165→166、字节 7266→7465。⇒ 落码席拿这份去 `git apply` 会把整件重写；**必须按「插入一行」手工落**（§3） | **推翻一条形态**（不改结论，改施工方法） |
| 0-D | 「S594 已把三件套跑通一次」 | S594 报告 §3/§4 自述：跑通的是**生成器**；门件第一轮 `ImportError: cannot import name 'workspace_manifest_sync' from 'scripts'`，第二轮只重跑生成器 ⇒ **十条锁从落地到今天一次都没有被执行过**（S604 §3.4 亦记「门从未跑过」）。本席是**第一次真跑**（§1.3） | **坐实并补做**（本席最重要产出） |
| 0-E | 「`bot_version` 三处互斥、无真身」 | 仓内**已有唯一在码读取口**：`domains/ops/monitor/error_report.py:582 _plugin_version()`（先查发行元数据、再退 `pyproject.toml [project].version`、最终 `unknown`）。三处读值现算：`pyproject.toml:3 = "0.1.0"`／tag `v0.0.1-alpha.2`（`for-each-ref` 现算 objecttype=**tag** ⇒ 确是 annotated，2026-09-08）／分支 `v0.0.1-alpha.2` | **改口径**：不是「无人读的悬空数」，是「有指定真身（pyproject）但发布面（tag）与它分家」——这决定 §2 该往哪一格填（§1.2/§2.3） |
| 0-F | 「L-6 的 annotated-tag 腿形态无关」 | 门件 `_git_annotated_tags()` 实际跑 `git tag --list` ⇒ **lightweight 与 annotated 不分**；且 `t.lstrip("v")` 是**字符集剥离**不是前缀剥离（`version-1.0.0`→`ersion-1.0.0`、`vv1.0.0`→`1.0.0`）；且 tag 是**全仓单命名空间**，一枚 `v1.0.0` 会把 6 枚库全判「已发布」（§6.3 注毒 5e 实测） | **推翻**（三处独立缺陷，§4 给修法） |
| 0-G | 「字段填上就有人读」 | 从门件源码 AST 现算读点集，与 schema 叶子键集求差：**`provides`／`why`／`counterparty`／`events[].rule_id` 等键今天零判据读**（§5，实测数在 §1.3 coverage 段） | **推翻**（这正是本席 ⑤ 要锁的病） |

| 0-H | S604 §2 表：DR-3「③腿恒不触发 ⇒ `DR3-UNRECORDED` 分支今天永世不红」 | 真跑注毒：把一枚接口锚符号从 live 导出集摘掉、且零引用 ⇒ **`DR3-UNRECORDED` 当场红**（`breaking_events` 为空恰使 `not any(...)` 为真）。⇒ **DR-3 三腿今天全可执法**，不依赖任何版本格 | **推翻**（且推翻方向是"能做的比前席报的更多"）→ §1.3-B／§2.2 |
| 0-I | S604 §2.3 步骤 2「ownership 定稿 ⇒ 解锁 DR-2b 断言资格」（把卡点归给"哪段路径属哪库"） | 卡点不止 ownership。首批 6 库的 `path_roots` 已在册，本席按它现算：**现存跨库边 10 对，其中 9 对未声明；把 10 对全填成 `requires` ⇒ L-5 当场报 4 个环**；最小反馈弧集 **= 3**（暴力枚举 4 组解，1 刀/2 刀均不足）。⇒ 补声明的天花板是**代码环**，不是声明额度 | **补充且改判**：DR-2b 今天能升断言，但绿集最大 7 条边，其余 3 条要 S606 的刀先落 → §2.2 |
| 0-J | 「S549 §2.1 的 L-4 证据腿保证每枚接口必有可收集的接缝测试在位」 | 现算两半都塌：①`tests/test_feature_gate_layer2.py` 与 `tests/test_creation_image_protocol.py` **是 `??` 未跟踪件且不在 HEAD**（`git cat-file -e` 双 NO）⇒ 干净 checkout 当场红；②10 枚接口里 **5 枚**声明的测试文件正文**查无锚符号名**（逐枚 grep 独立复核，各 0 命中）⇒ "在位"只成立到"路径在盘"这一弱义 | **推翻（弱化为字面在盘）**→ §3.2 同批伙伴／§5 |

（详细读数与复跑命令一律在 §1/§4/§5/§6，本表只放结论。）

## §1 交付①：逐字段「要成为断言，盘上必须先有什么」＋真身声明源

### 1.1 三处「真身」的分层（先说清"声明源"这个词在本格指什么）

现算的层级只有三层，缺任何一层，字段就只是散文：

| 层 | 落点 | 今天状态（本席 `test -f` 现算） |
|---|---|---|
| 声明源（唯一可编处） | `plugins/bot_unified_runtime/domains/core/workspace_manifest.py` | **ABSENT**；候选全文在 `%TEMP%\s594-mirror\plugins\bot_unified_runtime\domains\core\workspace_manifest.py`（19,021 B） |
| 生成器（投影，不新增事实） | `scripts/workspace_manifest_sync.py` | **ABSENT**；候选 `…\scripts\workspace_manifest_sync.py`（7,266 B，sha `c0e6d790a23106b7`）与修后件（7,465 B，sha `6b590619bfb1d8fa`） |
| 常驻门（读它，否则=第二本账） | `tests/test_workspace_manifest_gate.py` | **ABSENT**；候选 22,197 B |
| 投影件（门的判据对象） | `docs/workspace-manifest.json` | **ABSENT**（本席现算 `projection_on_disk=false`） |

⇒ 七枚字段的**共同**前置是这四件同笔在场；下面逐字段只列**各自额外**要什么。

### 1.2 逐字段账（今值一律本席现算，尺在 §6.1/§6.2）

| 字段 | 候选真身位置 | 今值 | 被哪条判据读（本席 §5 现算） | 要成为断言，盘上**还**必须先有 |
|---|---|---|---|---|
| `library_id` | `workspace_manifest.py:29 LIBRARY_ID_RE` ＋ `:148 LIBRARY_ROWS`（6 枚） | 候选态 **6** | L-1 文法 / L-5 图 / L-6 钉装 / L-8b 划分 | **无额外前置**——四件同笔即成断言（唯一一条今天就能全速执法的格） |
| `pinned_version` | `PinRow.pinned_version`（`:100`） | **0 行** | L-6（`got["pinned_version"]`，真读点） | ①该库 `version` 非占位；②**存在与该版逐字相等的 annotated tag**（§4 实测：今值 tag∩semver **= ∅**）；③pin 行本身 ⇒ 三条今天全不成立 ⇒ **不是"没人去填"，是填不进**（与 S604 §1.5 补条一同结论，本席独立复现） |
| `requires_min` / `requires_max_exclusive` | `LibraryRow.requires` 的 dict（schema `:116-119`） | **1 条边**（`lib.emergency→core.transport [0.0.0,1.0.0)`） | L-6 区间腿（真读点，实测有牙：§1.3-D） | 前置**不是它自己**——区间腿只在被钉目标存在时开火。实测注毒 `5b`：新增一条 `[1.0.0,2.0.0)` 的边而目标无 pin ⇒ **L-5/L-6 双绿＝区间腿对无钉库完全失明**。⇒ 这两格升断言的充要前置是 **pins 非空**，因此排在 `pinned_version` 之后，不能并行 |
| `breaking_events` | `BREAKING_EVENTS`（`:388`，空 tuple） | **0 行** | L-4（bump↔event 成对＋票根在盘）／L-6／DR-1 第三条 | 两条不同面：**当"版本 bump 的因"** ⇒ 卡在同一发布面前置；**当 DR-3 的销账账**（§1.3-C）⇒ **零版本前置，今天即可执法**。S604 只看到前一个面（见 §0 追加推翻） |
| `pins` | `PIN_ROWS`（`:391`，空 tuple） | **0 行** | L-6（一库一钉／钉==版／bot 格一致／区间可满足） | 同 `pinned_version`。附加：`why` 今天**零判据读**（§5）⇒ 可以填一行"无理由的钉"而十条全绿 |
| `bot_version` | `BOT_VERSION: Final = "0.0.0"`（`:48`） | 顶层 `0.0.0`；pin 行 0 ⇒ 该格今天**无人可比** | L-6 的 bot 格一致腿（仅在有 pin 时开火） | 🔴 本席现算推翻其"唯一真身"地位：仓内已有指定事实源 `domains/ops/monitor/error_report.py:582 _plugin_version()`（先查发行元数据 → 退 `pyproject.toml [project].version` → `unknown`；实测现值 `pyproject.toml:3 = "0.1.0"`）。⇒ 声明源再写一枚 `BOT_VERSION` **＝造第二真身**。正解见 §2.4（生成器投影 pyproject，或门加等值腿） |
| （附）`interfaces[]`／`breaking_rules[]` | `INTERFACE_ROWS` 10 枚／`BREAKING_RULE_ROWS` 6 枚 | 10／6 | L-2/L-3/L-4/L-5/L-7/L-1 配对腿 | 无额外前置，随四件同笔即执法 ⇒ **pins 的"可钉面"其实是它的下游**：接口在、锚在、符号解析得了，缺的只有版本面 |

### 1.3 十条锁的**第一次真跑**（本席实跑，S594/S604 均未跑过门件）

方式：`%TEMP%` 镜像装载三件套（修后生成器），`REPO_ROOT` 指真仓，逐条调 `p_l1…p_l8c`（脚本 `probes/s612-probe1.py`）。

| 腿 | 吃什么 | 真跑结果 |
|---|---|---|
| L-1 未知键／文法 | 6 库＋10 接口＋6 规则 | **绿** |
| L-2 锚在盘 | 7 枚 `path_roots` ＋ 10 枚 `anchor.file` | **绿**（17 枚路径全在盘） |
| L-3 锚符号 AST 可解析（含"再导出壳"负判据） | 10 枚接口的 `kind∈{python-symbol,data-contract}` | **绿** ⇒ S594 那三处锚改指真身（`outbound_gate.py`/`onebot.py`/`CreationJob`）经真跑坐实 |
| L-4 bump↔事件成对＋票根 | 今值 events 0 ⇒ bump 腿空转；**接口测试在盘腿真跑** | **绿（弱绿）**——见下 C/D |
| L-5 无环＋方向 | 1 条边 | **绿**（1 条边判不出环，§2.2 补到 10 条即红） |
| L-6 钉装可满足＋占位禁钉 | 0 pin、6/6 `0.0.0` | **绿**（占位面天然空转） |
| L-7 接缝必含名册 | 10 必备 × 10 在册 | **绿** |
| L-8b 板块划分／诚实缺位 | 板块尺现算 10 枚（B01–B10）、认领 3、名册 7 | **绿**，且"既无人认领也不在名册"现算 **= ∅** ⇒ S594 的缺位名册恰好闭合（本席独立核对） |
| L-8c 人读名派生 | 6 库 `display_name` × 板块 label | **绿** |
| L-9/L-10 投影确定性＋三同体 | 读 `docs/workspace-manifest.json` | **无法跑**：现算 `projection_on_disk=false` ⇒ 这两条是"落码那一笔必带第四件"的硬证据（§3.2） |

**三发新注毒（本席补，逐发实跑）**：
- **A（区间腿有牙）** `core.transport` 抬 `2.0.0` 并给同名 tag，`lib.emergency` 的边仍 `[0.0.0,1.0.0)` ⇒ **L-6 红**「区间被钉版 2.0.0 不满足」＋L-4 红「MAJOR bump 无已登记破坏事件」。⇒ `requires_min/max` 与 `pinned_version` 两格**确有读点且有杀伤力**，只缺料。
- **B（DR-3 三腿今天全可执法）** 用 S604 §1.3 的三腿合判＋本席现算的 live 视图：把 `iface.render.theme-tokens` 的锚符号从导出集摘掉、且**无人引用** ⇒ **`DR3-UNRECORDED` 当场红**（事件账为 0 枚不影响开火，反而使任何"干净删除"都无账可查⇒必红）；再塞一个引用者 ⇒ 转为 `DR3-GONE`；不摘 ⇒ 全绿。⇒ **推翻 S604 §2 表「③腿恒不触发」**（它把 L-4 的"无版本可 bump"混进了 DR-3③ 的触发条件）。
- **C（全局 tag 摊派＝今天能造出假绿）** 6 枚库全填 `1.0.0`＋6 行 pin（**`why` 全空**）＋`tagged={"1.0.0"}` ⇒ **全部十条锁实跑绿（`probes/s612-probe6.py` 返回 `{}`）**，而现实中不存在任何"这六枚库各自发布过 1.0.0"的事实。
  **同一份册喂真 tag 集**（只有 `0.0.1-alpha.2`）⇒ **L-6 当场红 6 次**「占位版 1.0.0 被钉（无同名 annotated tag）」。⇒ 精确定性：**tag 腿自身有牙，缺的是命名空间**——一枚 `v1.0.0` 同时给六枚库发"已发布"资格（§4 F-3）；顺带实测 `why` 全空也绿＝N-H 的必要性（§5.5）。
- **D（票根相关性）** 把某接口的 `tests` 换成一枚**在盘但与之无关**的测试 ⇒ **十条全绿**（L-4 只查 `exists()`）。⇒ §5。

## §2 交付②：最小第一批字段 ⇒ DR-1/2a/2b/3/4 哪几条今天就能升断言

**"升断言"沿用 S604 §2 的三条定义**：(a) 读得到非空输入、(b) 今天给真绿（不是零遍历的绿）、(c) 注一条分叉当场红。

### 2.1 最小第一批 = **M0：四件同笔、零版本格**（不依赖她任何一项待裁）

要填的只有：`libraries[]`（6 枚，`version` 一律 `0.0.0`）、`interfaces[]`（10 枚）、`breaking_rules[]`（6 枚）、`UNCLAIMED_BOARDS_ROSTER`（7 枚）、`requires[]`（**只填无环子集，见 2.2**）。
**不填**：`pins[]`、`breaking_events[]`、任何非 `0.0.0` 的 `version`。
M0 的可执行性本席已实测：十条锁真跑全绿（§1.3），L-8b 板块闭合现算 ∅ 缺口。

### 2.2 逐条判定（点名条数与理由；数字全是本席现算）

| 判据 | M0 后能否升断言 | 理由（现算） |
|---|---|---|
| **DR-3**（删导出符号未销账，三腿） | ✅ **升，三腿全量** | ①腿＝L-3 今天已在册且实测可解析；②腿＝live `cross_edges` 在首批面内**只有 10 对／38 枚符号**（探针 `s612-probe1.py` 现算），零新声明成本；③腿注毒实测当场红（§1.3-B）。⇒ **这一条不欠任何版本格**，是四条里唯一"今天升断言且不承诺假绿"的 |
| **DR-2b**（未声明跨库边／方向偷换） | ⚠ **升，但今天只能是"限定面＋7 条边"** | 现存 10 对、已声明 1 对 ⇒ 直配即 **9 红**；把 10 对全填 ⇒ **L-5 报 4 环**（`core.creation↔core.dispatch`、`core.creation↔lib.controlplane`、`core.creation→lib.emergency→core.transport→core.creation`、`lib.emergency↔core.transport`）。暴力枚举：**删 1 或 2 条都不能无环，删 3 条可以（4 组解）** ⇒ 今天最大可落声明数 **= 7 条边**。余下 3 条**必须**等 S606 的刀（库粒度的最小破环集今值 = 3 对，本席读数，可与 S614 的 28 刀对账） |
| **DR-1**（producer 抬号、pin 未跟随） | ❌ **不升** | 三格全空且结构不可填：`pins` 0 行；tag 面实测 `semver_legal_subset = []`（唯一 annotated tag 是 `0.0.1-alpha.2`，不过 `SEM_RE`）；`breaking_events` 0 ⇒ 第①格（遍历非空）就不成立 ⇒ 配门＝配空转（S604 §2 同判，本席复现） |
| **DR-1b**（MAJOR 无事件） | ❌ **不升** | 6/6 库 `version=0.0.0` ⇒ `lv[0]>=2` 结构上永不成立 ⇒ 恒零遍历绿 |
| **DR-2a**（区间腿） | ❌ **不升**（且必须显式记它的失明面） | 实测注毒 `5b`：一条 `[1.0.0,2.0.0)` 的边、目标无 pin ⇒ L-5/L-6 双绿。⇒ 腿有牙（§1.3-A 实测红）但**吃不到料**。前置是 pins，不是它自己 ⇒ 排 DR-1 之后 |
| **DR-4**（契约形状动、代际未抬） | ❌ **不升** | `contracts_then` 侧结构上不存在（无锁文件、无 CI 工件、无发布快照）——S604 现算三格本席无一处可推翻；M0 不产生任何发布态 |

**点名结论（一句话）**：M0 之后今天能升断言的是 **2 条**——**DR-3（全量三腿）** 与 **DR-2b（限定面，声明额度 7/10）**；其余 **4 条（DR-1／DR-1b／DR-2a／DR-4）一条都不能升**，且卡点全在**发布面（tag×semver 交集空）**与**历史面（无上一发布态）**，不在"字段还没填"。

### 2.3 M0 的覆盖面必须同笔披露（防"首批绿"被读成"整仓绿"）

本席按首批 6 库 `path_roots` 现算（探针 `s612-probe3.py`，尺＝`plugins/bot_unified_runtime/**/*.py` 全量 AST）：

| 量 | 今值 |
|---|---|
| 生产面 `.py` 总数 | **573** |
| 落在 6 库 `path_roots` 内 | **134**（23.4%） |
| **未落入任何库** | **439**（76.6%） |
| 已认领→已认领跨库对 | **10**（含 38 枚符号名） |
| 「未认领消费方 → 已认领库」跨界对 | **6**（`→lib.render` 独占 179 枚符号／20 文件、`→core.creation` 51 枚／11 文件…） |
| 全仓边符号名总数 | **352** |

⇒ 断言只覆盖 10 对里的 7 对，S604 的全域口径（100 对／490 符号名）今天仍在门外。**M0 落地那一笔的正文必须写"覆盖 7/10，全仓 100 对仍在报告态"**——否则 DR-2b 这条门就是新的假绿源。

### 2.4 顺手可加的一条（零新数据面，今天即绿或即红，不留空转）

`bot_version` 的**等值腿**：manifest 顶层 `bot_version` ↔ 仓内在码指定源 `_plugin_version()`（`error_report.py:582`，实测读 `pyproject.toml [project].version = 0.1.0`）。
两格都在盘 ⇒ 这条判据今天**就有效果**：按候选件现值 `0.0.0` 直配即 **红**（0.0.0 ≠ 0.1.0）。
⇒ 因此 M0 必须先二选一：**(甲) 生成器不读 `BOT_VERSION`，改从 `pyproject.toml` 投影**（消除第二真身，代价＝生成器多一个输入面）；**(乙) 保留 `BOT_VERSION` 但门加等值腿**，她裁 G11 之前该腿必红 ⇒ 只能以 `missing_inputs` 形态在场。
**本席推荐甲**（理由：`_plugin_version()` 的 docstring 已把 pyproject 写成"唯一事实源"，乙等于给同一事实造第二个可编点——S591 `[DIM-VACUITY]` 的反面，且撞 AGENTS「禁第二真身」硬门）。

## §3 交付③：生成器一行修的落地位置与全文＋为何不能单独进提交

### 3.1 落地位置与全文（本席 `diff --strip-trailing-cr` 现算，非转述）

文件：`scripts/workspace_manifest_sync.py`（新落），函数 `load_declaration()`。
位置：**在 `mod = importlib.util.module_from_spec(spec)` 之后、`spec.loader.exec_module(mod)` 之前**插入一行，即修后候选件的第 **56** 行。

```python
    sys.modules[spec.name] = mod
```

全文（落仓后该函数应为，修行为第 56 行）：

```python
def load_declaration() -> Any:
    """按文件路径装载声明源（它只 import 标准库 ⇒ 不触发插件包初始化）。"""
    spec = importlib.util.spec_from_file_location("_wsm_decl", DECL_PY)
    assert spec and spec.loader, f"声明源装载失败：{DECL_PY}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod
```

- 机制（S594 §4A 已定，本席复核崩点行号一致）：`exec_module` 前不登记 `sys.modules[spec.name]` ⇒ 声明源带 `from __future__ import annotations` ＋ `@dataclass` 时，`dataclasses._is_type` 走 `sys.modules.get(cls.__module__).__dict__` 取到 `None` ⇒ `AttributeError`。**崩在生成器自己的函数里，不是 harness**。
- 语义：**只加一行，零行为变更**（`sys` 已在第 16 行 import ⇒ 不新增依赖）。
- 🔴 **施工告诫（本席现算，简报未写）**：镜像里那两份候选件**全文都是 CRLF**，朴素 `diff -u` 会把 166 行**全部**报成改动（`orig 165 行 / fixed 166 行`、字节 7266→7465）。⇒ **不许拿镜像去 `git apply`**；按"插入一行"手工落，落完用 `git diff --numstat` 自证应为 **`1  0`**（相对修前）。
- 本席指纹（供落码席核对拿对了件）：修前 sha256[:16] `c0e6d790a23106b7`（与 S594 §0 登记的自名指纹**逐字相等**，本席独立算得）；修后 `6b590619bfb1d8fa`。
- ⚠ 一行修**不等价于可单飞**：见 3.2。

### 3.2 为什么它今天不能单独进提交（同批伙伴逐枚点名，全为现算）

| # | 同批伙伴 | 不带它会怎样 | 本席证据 |
|---|---|---|---|
| P1 | `plugins/bot_unified_runtime/domains/core/workspace_manifest.py`（声明源） | 生成器 `load_declaration()` 直接 `assert spec and spec.loader` 失败 ⇒ 门收集期崩 | §1.1 现算 ABSENT |
| P2 | `tests/test_workspace_manifest_gate.py`（门） | 生成物无人读 ⇒ 正是本席 ⑤ 定罪的"只填不读"；且投影件漂了没人报 | S549 §5.2 首行"三件不同笔＝收集 ImportError 挡全树"；本席复核其 import 边：门 import 声明源与生成器 |
| P3 | `docs/workspace-manifest.json`（投影件） | **L-9/L-10 当场红**（两函数直接 `(REPO_ROOT/"docs"/"workspace-manifest.json").read_text()`） | 本席现算 `projection_on_disk=false` ⇒ 这不是"建议"，是必然失败 |
| P4 | `scripts/chatbot-tasks.json` 的 `sync` 列 | 新投影件天生复刻既有不对称 ⇒ `--check` 永不进门禁 | **本席现算**（行级证据）：`sync` 块内 `--write` 四枚＝`:431 command_catalog` / `:433 doc_sync` / `:435 verify_hashes` / `:437 board_doc_sync`；`--check` 三枚＝`:439 doc_sync` / `:440 verify_hashes` / `:441 board_doc_sync` ⇒ **独缺 `command_catalog.py --check`**，与 S604 §4.3.2 的独立实现同值（两条实现相等） |
| P5 | `doc_sync --write` 重录机器册 | 新 `.py` 入树 ⇒ `tests_files`/`python_files` 计数漂 ⇒ `test_doc_sync_gates` 红 | S549 §5.2 第 2 行"会撞（预期内跟随）" |
| P6 | 🔴 **两枚未跟踪的接缝测试件**：`tests/test_feature_gate_layer2.py`、`tests/test_creation_image_protocol.py` | 门件 L-4 的"接缝测试在盘"腿在**干净 checkout** 里对这两枚必红（它们今天只在脏工作树上存在） | 本席现算：`git cat-file -e HEAD:<f>` 两枚均 **NO**、`git status --porcelain` 两枚均 `??`、`git ls-tree -r HEAD \| grep -c` = **0** |
| — | P6 的归属澄清 | 这两枚**不在** S602 §3.3 的 B-0 七枚同笔集里（该集 7 枚全是生产侧 `plugins/**`）⇒ 它是**独立的一笔**，不能指望 B-0 顺带带走 | 本席读 S602 §3.3 清单逐枚比对 |

⇒ **最小可提交面 = M0 ＝ P1+P2+P3+P4+P5 五处同笔（外加 P6 作为"要么同笔、要么把 L-4 那半腿改成显式 `missing_inputs`"的前置）。** 只带一行修进去＝往树里放一枚谁都不读的脚本，且第一次 `-Task sync` 就炸。

## §4 交付④：NEVER_PIN 占位版禁令的形态无关写法

### 4.1 候选件的现状是"两条腿一真一假"，且真那条有三处实测缺陷

现状（`test_workspace_manifest_gate.py:31` ＋ `:205`）：
`is_placeholder = version in PLACEHOLDER_VERSIONS or version not in tagged`，其中 `PLACEHOLDER_VERSIONS = {"0.0.0","0.1.0"}`、`tagged = _git_annotated_tags()`。
第一条腿**天然形态相关**（枚举字面量，改个 `0.2.0` 就漏）；第二条腿方向正确但实现有洞：

| # | 缺陷 | 本席实跑证据 |
|---|---|---|
| F-1 | `_git_annotated_tags()` 跑的是 `git tag --list` ⇒ **lightweight 与 annotated 不分**。一枚随手 `git tag v1.0.0`（无 tag 对象、无日期）即被当"发布动作发生过" | 读其函数体（`:273-276`，无 `objecttype` 过滤） |
| F-2 | `t.lstrip("v")` 是**字符集剥离**不是前缀剥离 | 实测：`version-1.0.0 → "ersion-1.0.0"`、`vv1.0.0 → "1.0.0"`（`s612-probe1.py` 的 `5d_lstrip_trap`） |
| F-3 🔴 | **tag 是全仓单命名空间**，却用来给 N 枚库各自"作证" | 实跑（`probes/s612-probe6.py`）：6 库全填 `1.0.0`＋6 行 pin＋`tagged={"1.0.0"}` ⇒ **十条锁全绿 `{}`**；同册喂真 tag 集 ⇒ L-6 红 6 次 ⇒ **腿有牙、缺命名空间** |
| F-4 | 现值使两腿**交集为空**：唯一 annotated tag 现算 `tags/v0.0.1-alpha.2`（objecttype=`tag`），门把它洗成 `0.0.1-alpha.2`，而 L-1 的 `SEM_RE` 不认预发布 ⇒ `semver_legal_subset = []` | 本席现算（`s612-probe3.py` 的 `tag_leg`）：`gate_computed_tagged=["0.0.1-alpha.2"]`、`semver_legal_subset=[]` |

⇒ **F-4 是本席对"可钉面 0"的机制解释**（S604/S586 只给了读数，没给"为什么必然 0"）：**要合法必须过 `SEM_RE`；要算已发布必须等于某枚 tag 去 `v` 后的串；而今天唯一那枚 tag 去了 `v` 不合法 ⇒ 两集无交。** 所以不是"还没人填"，是**填不进**，且不补 tag 面就永远填不进。

### 4.2 形态无关的主判据（可粘贴文本；本席只在探针里实现并验证，不落仓）

**教义**：占位 ⟺ **该库该版的"发布动作"没有发生过**。发布动作的唯一机器证据 = 指向**本库本版**的 annotated tag 对象；字面量名册降级为**防手滑的次级判据**，禁当主判据。

```python
#: 库→tag 的命名空间约定（单仓多库必须带库名前缀，否则一枚 tag 给全员作证＝F-3）
#: 形状：refs/tags/<library_id>/v<semver>   例 refs/tags/core.dispatch/v1.2.3
def release_tags_by_library(repo_root: Path) -> dict[str, set[str]]:
    """现算「每枚库各自发布过哪些版」——只认 annotated tag，且必须带库名命名空间。"""
    proc = subprocess.run(
        ["git", "for-each-ref", "refs/tags",
         "--format=%(refname:short)\t%(objecttype)"],
        cwd=repo_root, capture_output=True, text=True,
        encoding="utf-8", check=False)
    out: dict[str, set[str]] = {}
    for line in proc.stdout.splitlines():
        ref, _, otype = line.partition("\t")
        if otype != "tag":                      # F-1：lightweight 不算发布动作
            continue
        name = ref[len("refs/tags/"):] if ref.startswith("refs/tags/") else ref
        lib, sep, ver = name.rpartition("/v")   # 按 '/' 切，**不用 lstrip**（F-2）
        if not sep or not lib:                  # 无库命名空间 ⇒ 谁都不许受益
            continue
        out.setdefault(lib, set()).add(ver)
    return out


def never_pin_reason(version: str, released: set[str],
                     forbidden: frozenset[str]) -> str | None:
    """None = 可钉。三态显式：非文法／命中名册／无发布动作。"""
    if not _SEM.match(version):
        return f"非 semver，不得进 pins：{version!r}"
    if version not in released:
        return f"无该库该版的 annotated tag ⇒ 发布动作未发生：{version!r}"
    if version in forbidden:
        return f"命中禁用字面量（次级防手滑腿）：{version!r}"
    return None
```

配套三条硬约束（各挡一种本仓已定过罪的病）：
- **主判据先行**：`forbidden` 只允许是**第三**道闸（上表顺序即判序）。禁写成"命中名册才红"的短路——否则名册一删，判据立刻退化成形状尺。
- **名册单点供给**（K1）：`NEVER_PIN` 只在声明源出现一次，门与生成器都从它取；禁两处各写一份。
- **反向锁**（防 F-3 回潮）：`release_tags_by_library()` 里若存在某命名空间**不属于任何在册库** ⇒ 红（"tag 造了没人认领的库的假"）。这条腿让"随手打 tag"也要付账。

### 4.3 次级名册（保留，但口径改成"防手滑"，逐枚给在仓证据）

```python
#: 真身＝domains/core/workspace_manifest.py，唯一供给点；它是兜底不是主判据（§4.2）。
NEVER_PIN: frozenset[str] = frozenset({
    "0.0.0",           # 本册「无货可发」缺省：6/6 库现值即它（声明源 LIBRARY_ROWS）
    "0.1.0",           # 脚手架缺省：pyproject.toml:3 现值恰为它（本席读盘复核）
    "0.0.1-alpha.2",   # 唯一 annotated tag 去 v 后的串：禁它绕文法腿进 pins（F-4）
})
```

S604 §1.5 那份长名册里的 `"unknown"/"dev"/"latest"/"snapshot"/"0.0.x"…` 在新主判据下**结构上不需要**：它们一律不过 `SEM_RE` ⇒ 第一道就红。保留长名册反而制造"加了名字就算防住"的错觉，且违反 K1 的词表最小化。**这条是对 S604 §1.5 的改判**（它写的是"主判据＝发布动作发生过没有"＋一份长兜底名册；本席只把名册缩到三枚各有在仓证据的、并把顺序钉死）。

### 4.4 预发布文法：两案与代价（今天不定，§4 的 F-4 无解）

- **丙（改文法）**：`SEM_RE` 扩预发布段 `…(?:-[0-9A-Za-z.-]+)?$` ⇒ 与 `@schema` 升代同笔（L-10 三同体），代价＝`requires_max_exclusive` 的"下一个 MAJOR"约定要补预发布排序语义。本席不推荐今天动。
- **丁（改发布习惯）**：新 tag 一律 `refs/tags/<library_id>/v<纯 semver>`；旧 `v0.0.1-alpha.2` 原样留史、**显式永不参与判定**（无库命名空间 ⇒ 主判据天然不收）。⇒ **本席推荐丁**：零 schema 升代、零文法放宽，且把 G11（bot 真身号）完整留在她手里——本席只负责把"今天为什么钉不进"的机制说死。

## §5 交付⑤：反例锁——「填了字段但没人读」怎么防

### 5.1 本席先对自己的尺注毒（两版尺，第一版不可信）

- **尺 v1（名级，不可信）**：把门件源码里出现过的所有字符串常量＋属性名当"读点集"，与 `WORKSPACE_MANIFEST_JSON_SCHEMA` 叶子键集求差 ⇒ unread = `counterparty/generated_by/notes/provides/statement`（**5 枚，`why` 被误判为"有人读"**，因为它只作为注毒夹具里的 dict 键出现过）。落盘在 `s612-probe1.py`。
- **尺 v2（读点级，本席采用）**：只认 `p_*` 判据函数体里的 `ast.Subscript` 字符串下标 与 `ast.Attribute.attr` ⇒ unread = **`counterparty` / `generated_by` / `notes` / `provides` / `statement` / `why`（6 枚）**。
- **两版尺的不对称性必须写进判据说明**：这族尺**只会假"有人读"，不会假"没人读"**——一个键名在门件里从没作为读点出现，任何判据都不可能在算它。⇒ 本席只对"unread 集"下结论，对"read 集"不下结论（`append/get/match/exists` 这类方法名混在 read 集里即为证据：尺的上界是松的）。

### 5.2 四发空转注毒（真跑，全部"该红却绿"，`s612-probe3.py` → `vacuity_poisons`）

| 发 | 注法 | 十条锁 | 结论 |
|---|---|---|---|
| A | `core.dispatch.provides = ["iface.render.theme-tokens"]`（把别人的接口写成自己提供的） | **全绿** | `provides` 零执法；L-5 只查 `requires.via_interface` 的方向，不查 `provides` 的方向 ⇒ **谎报能力面免费** |
| B | 唯一 `kind=="external-protocol"` 那枚的 `counterparty` 清空 | **全绿** | S549 §2.4 给 external-protocol 的特殊语义（须带实测票根）**无腿** |
| C | `iface.render.theme-tokens` 的 `kind` 从 `token-registry` 改 `python-symbol`、`breaking_rule` 同步换成合法名 | **全绿** | 配对腿（L-1 改动 4②）只查"搭配合法"，不查"这格本来的语义"⇒ **整枚接口的裁判可以被偷换** |
| D | 把某接口的 `tests` 换成一枚**在盘但与之无关**的测试 | **全绿** | L-4 只 `exists()` ⇒ 票根与接口的相关性零执法（= §0-J） |

⇒ 这四枚都是"**填了、门不看**"的具体形态；且它们**都发生在候选件已经"十条全绿"的那本册上**，不是设想。

### 5.3 建议的反例锁全文（派生式、零手写清单，合 K1；本席只给文本不落仓）

```python
#: 散文/溯源格豁免名册：**只准降不准升**，每枚必须带一句"为什么不需要腿"。
#: 新增豁免＝造新空转面，所以由棘轮钉死（先例＝capability_manifest.IMPL_REF_UNDECLARED_ROSTER）。
PROSE_KEYS: frozenset[str] = frozenset({
    "notes",          # 人读注：任何判据读它都会把散文变成硬约束
    "statement",      # 规则的自然语言陈述；其可机检面由 detector 词表承担（L-1 已执法）
    "generated_by",   # 溯源戳：由 L-9 的"投影==现算"整体承担，不逐字段判
})


def _read_keys_in(predicates: list[Callable]) -> set[str]:
    """读点集＝判据函数体里的字符串下标与属性名（AST 现算，禁手抄）。"""
    out: set[str] = set()
    for fn in predicates:
        for node in ast.walk(ast.parse(inspect.getsource(fn))):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                out.add(node.slice.value)
            elif isinstance(node, ast.Attribute):
                out.add(node.attr)
    return out


def p_l11_no_silent_fields(doc_schema: dict, predicates: list[Callable]) -> list[str]:
    """L-11：schema 里每一枚**结构格**都必须至少被一条判据读；读不到 ⇒ 红（"只填不读"）。"""
    leaves: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                leaves.add(k)
                walk(v)
        elif isinstance(node, list) and node:
            walk(node[0])

    walk(doc_schema)
    return [f"L11-SILENT {k}: 在册但没有任何判据读它（填了=假分母）"
            for k in sorted(leaves - _read_keys_in(predicates) - {"@schema"} - PROSE_KEYS)]
```

**注毒自证（三发，本席已实跑＝`probes/s612-probe5.py`，非预测）**：
① 把 `p_l6_pins` 里 `pinned_version` 的全部读点换成 `None` ⇒ L-11 点名集从 `{counterparty, provides, why}` 变为 **含 `pinned_version`**（实测 `names_pinned_version: true`）⇒ 证明它测的是"读点消失"，不是"名字没写"；
② 真册跑 L-11 ⇒ **实测红 3 枚：`counterparty` / `provides` / `why`**（这条在写探针前本席预测为 3，实跑得 3，预测与实测同时留在盘上）；
③ 把 `provides`/`statement`/`generated_by` 之外的名字塞进 `PROSE_KEYS` ⇒ 由"只准降"棘轮腿红（本席未实现该棘轮，只登记需求——它是 S598 那族 `approvals` 通道的同型件）。
⇒ **交给落码席的欠账清单就这三枚**，且第 5.2 表的注毒 A/B 恰好各杀其中一枚。

### 5.4 L-11 挡不住的（如实写，别把它吹成万能）

L-11 只保证"有人读"，不保证"读得对"。§5.2 的 C/D 两发**在 L-11 下仍然绿**——因为 `breaking_rule`/`tests` 都有人读，只是读得浅。⇒ 必须与 §5.5 的四条具体腿同时落，二者是一浅一深两把尺，缺一就把另一把的空当留给下一次假绿。

### 5.5 四条具体腿（本席已在探针里实现并实跑，战果如下）

| 腿 | 判据 | 实测战果 |
|---|---|---|
| **N-E** `provides` 方向 | 每枚 `provides[i]` 必须在册且 `producer == 本库` | 杀掉注毒 A ✅；真册 6/6 库全过 ✅ |
| **N-F** kind↔counterparty | `kind=="external-protocol"` **当且仅当** `counterparty` 非空 | 杀掉注毒 B ✅；真册 10/10 全过 ✅ |
| **N-G** 票根相关性 | `interfaces[].tests[i]` 文件正文必须**出现**该接口的 `anchor.symbol` | 杀掉注毒 D ✅；🔴 **真册现算 5/10 不过**（见 5.6） |
| **N-H** `why` 非空 | 每枚 pin 的 `why` 去空白后非空 | 真册 0 pin ⇒ 今天无靶；🔴 但 §1.3-C 的注毒已实测"**6 行 pin 的 `why` 全空、十条锁仍全绿**" ⇒ 一旦 pins 开面，无理由的钉免费。与 pins 首批同笔才有效（诚实标注，别当已执法） |

### 5.6 N-G 在真册上的现算战果（逐枚 grep 独立复核，各 0 命中）

声明的接缝测试里**查无锚符号名**的 5 枚：
`iface.core.dispatch.orchestrated-command`（`orchestrated_command` ∉ `test_capability_result_unique.py`）、
`iface.core.dispatch.run-capability-through-pipeline`（`_run_capability_through_pipeline` ∉ `test_feature_gate_layer2.py`）、
`iface.controlplane.openapi`（`build_v1_router` ∉ `test_v21_s9_llm_api.py`）、
`iface.emergency.dedupe.key-segment`（`is_legal_segment` ∉ `test_emergency_info_subscriptions.py`）、
`iface.transport.onebot-v11-adapter`（`send_onebot_v11` ∉ `test_outbound_gate.py`）。

**这把尺的强度边界（不吹）**：字面查无 ⇒ 只证明"锁声称的证据与接口之间查不到字面关联"，**不等于"这枚接口没被测"**（测试可以经公共入口间接打它）。⇒ 推荐落法＝ N-G 先以 **`missing_inputs` 报告**形态落（点名 5 枚、不承诺红），改判"接口→锚符号所在模块的 import 边被该测试收集到"作硬断言，是下一步的事。
**但同一段读数里有一枚是真红**：`test_feature_gate_layer2.py` 与 `test_creation_image_protocol.py` **是未跟踪件**（§3.2 P6）⇒ 这两枚接口在干净 checkout 里连"路径在盘"都不成立。

## §6 复跑命令簿＋注毒＋卫生＋PARKED

### 6.1 词元分母（§0-A 的尺，一条命令可复跑）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
for w in workspace_manifest library_id requires_min requires_max_exclusive pinned_version \
         breaking_events bot_version pins _CONTRACT_VERSION; do
  printf "%-26s %s\n" "$w" "$(grep -rnE --include=*.py "\b${w}\b" plugins scripts tests | wc -l)"; done
# ⇒ 本席 2026-09-25T13:0xZ 实跑：九词各 0 命中
```
⚠ 尺边界：`\b` 把 `_` 当词字符 ⇒ snake_case 内部的 `pins` 不算边界命中（S604 §6.2 已记此分歧，本席沿用同一把尺并点名）。

### 6.2 三件套在位性 ＋ 发布面 ＋ P6 未跟踪件

```bash
for f in plugins/bot_unified_runtime/domains/core/workspace_manifest.py \
         scripts/workspace_manifest_sync.py tests/test_workspace_manifest_gate.py \
         docs/workspace-manifest.json; do
  test -f "$f" && echo "EXISTS $f" || echo "ABSENT $f"; done          # ⇒ 四件全 ABSENT
git for-each-ref refs/tags --format='%(refname:short) %(objecttype)'  # ⇒ tags/v0.0.1-alpha.2 tag
git branch --show-current                                             # ⇒ v0.0.1-alpha.2
grep -nE '^\s*version\s*=' pyproject.toml | head -1                   # ⇒ 3:version = "0.1.0"
git ls-tree -r HEAD --name-only | grep -cE 'test_feature_gate_layer2\.py|test_creation_image_protocol\.py'
# ⇒ 0（两枚接缝测试不在 HEAD，工作树里是 ??）
```

### 6.3 本席六发探针（一次跑完＝§1.3/§2.2/§5 的全部读数）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
export PYTHONPYCACHEPREFIX="C:\\Users\\LancyCelestia\\AppData\\Local\\Temp\\s612-pyc"   # 必 Windows 形态
PY=../ChatBot_Runtime/venv/Scripts/python.exe
S=.superpowers/sdd/2026-09-24-central-dispatch
$PY -B $S/probes/s612-probe1.py   # 十条锁首跑（10/10 绿）＋ 首批 DR-2b ＋ 注毒 5a-5f
$PY -B $S/probes/s612-probe2.py   # 覆盖率尺 v1/v2 ＋ tag∩semver ＋ DR-3 三腿 ＋ 5f
$PY -B $S/probes/s612-probe3.py   # DR-2b 全仓口径（修正版）＋ 四发空转注毒 ＋ 区间腿有牙
$PY -B $S/probes/s612-probe4.py   # 补 10 条边⇒4 环；N-E/N-F/N-G/N-H 四条新腿战果
$PY -B $S/probes/s612-probe5.py   # L-11「只填不读」锁：真册红 3 枚＋删读点必点名
$PY -B $S/probes/s612-probe6.py   # 补证 F-3：全局 tag 摊派下**全部十条**锁的判决（绿），真 tag 集下 L-6 红 6 次
```
最小反馈弧集＝3 那一发是纯 itertools 枚举，命令原文在 §2.2 引用处；它不读盘、只吃 10 对边名，因此**不随树漂**。
**前置**：`%TEMP%\s594-mirror\` 必须还在（它是三件套唯一落盘处，gitignore 区外、**无 git 回滚位**）。本席实测在场；**若被清，本件全部"门真跑"读数即刻不可复现**——已登记 §6.6 P-S612-1。

### 6.4 注毒总账（本席实跑 12 发，逐发记归属）

| 发 | 注法 | 结果 | 判读 |
|---|---|---|---|
| 5a | 钉一枚 `0.0.0` 的库 | L-6 红「0.0.0 被钉」 | 锁有牙 ✅ |
| 5b | 加一条 `[1.0.0,2.0.0)` 的边、目标无 pin | **全绿** | 区间腿失明＝真缺陷 → §2.2 |
| 5c | 版本填 `0.0.1-alpha.2` 并同名 tag | L-6 **实跑绿**（`probe1.py` 的 `5c_prerelease_tag`） | 两腿互斥 → §4 F-4。（"L-1 会红"是**推定**：`SEM_RE` 不认预发布；本席未对该形态实跑 L-1，标注为未实测） |
| 5d | `lstrip("v")` 陷阱 | `version-1.0.0→ersion-1.0.0` | §4 F-2 |
| 5f/§1.3-C | 全局一枚 tag 摊给 6 库（且 6 行 pin 的 `why` 全空） | **十条全绿**；喂真 tag 集则 L-6 红 6 次 | §4 F-3＝最危险的一发（假分母今天就能造出来）＋ N-H 必要性；证据 `probe6.py` |
| B(DR-3) | 摘符号＋零引用＋事件账空 | **DR3-UNRECORDED 红** | 推翻 S604「③腿恒不触发」 |
| B'(DR-3) | 摘符号＋有引用 | DR3-GONE 红 | ②腿有牙 |
| A | `provides` 谎报别人接口 | 十条绿／N-E 红／L-11 点名 | §5.2/§5.5 |
| B | `counterparty` 清空 | 十条绿／N-F 红／L-11 点名 | 同上 |
| C | `kind`＋`breaking_rule` 成对偷换 | **十条绿**（L-11 也不管，因两格都有读点） | §5.4 的边界实例 |
| D | `tests` 换成在盘无关测试 | 十条绿／N-G 红 | §5.5/§5.6 |
| ⑤ | 删 `pinned_version` 读点 | L-11 当场点名它 | L-11 不是名册尺 |

### 6.5 本席自造并自纠的问题（照实记，不抹）

1. **probe-2 的路径解析自伤**：`mod.replace("plugins.bot_unified_runtime", "plugins/bot_unified_runtime")` 只换前缀、尾巴仍是点号 ⇒ 绝对 import 全部匹配失败，算出"已认领→已认领 = 1 对"（真值 10）。**发现方式**＝与 probe-1 的 10 对交叉对不上，而不是它自己报红。修法＝probe-3 用整串 `.`→`/` 归一后重算，得 10 对（与 probe-1 独立实现同值）。⇒ 又是"两把尺的读数分家才抓到尺瞎"这一型。
2. **覆盖率尺 v1 是名级尺**（§5.1）：它把 `why` 判成"有人读"。若我停在 v1 就会少报一枚空转格。已升级并**把两版结果都留在盘上**。
3. **probe-4 里我自己的"最大无环子集"贪心是错的**：它给出的 7 条边仍含 2 个环。真数由 itertools 暴力枚举得出（删 3 条、4 组解）。⇒ 报告里的"7"取自暴力枚举后的 `10-3`，不取自那个错误贪心。

### 6.6 PARKED（本席未做/做不了/等她）

| # | 事项 | 为什么停在这里 |
|---|---|---|
| P-S612-1 | 🔴 **三件套唯一落盘处 `%TEMP%\s594-mirror\` 无 git 回滚位**（gitignore 区外、Temp 可被清理） | 本席只读、未搬动（搬进仓＝落码，越红线）。**建议她或主代理立刻把它备份进 `.superpowers/sdd/2026-09-24-central-dispatch/probes/` 或仓内受管目录**，否则 §1.3 的"门第一次真跑"不可复现，本件一半读数随之作废 |
| P-S612-2 | L-11 / N-E / N-F / N-G / N-H 五判据**只给文本、未实装** | 红线：不改 `tests/`。§5.3/§5.5 已给全文＋注毒预期，落码席照抄即可 |
| P-S612-3 | 未跑 `workspace_manifest_sync.py --write`（不生成投影件） | 红线：不写 `docs/`。⇒ L-9/L-10 两条本席**只证到"它们会红"**，未证到绿态 |
| P-S612-4 | `bot_version` 甲/乙两案（§2.4）需她一句 | 乙案涉及 G11（真身版本号），甲案涉及"生成器多一个输入面"的口径变更 |
| P-S612-5 | 预发布文法两案（§4.4）需她一句 | 丙＝schema 升代；丁＝发布习惯。本席推荐丁，但不替她定 tag 策略（git 写面） |
| P-S612-6 | 库粒度未复核 | 本席照候选件 6 库 7 roots 原样用，**未独立核粒度**（那是 S546/S547 的活）。⚠ 数字口径提醒：memory 索引行里的"未认领 109 枚"＝**他源转述、本席未复算**，且与本席"未认领 439 枚"是**不同宇宙**（那把尺吃 `impl_paths` 93 枚声明根、本席只吃首批 6 库 7 条 `path_roots`）⇒ 两数不可比，本席不判谁对 |

### 6.7 卫生账与红线自证

**卫生自查（含一次本席自造假零的更正）**
1. 本席第一次自查用 `find . -name '*.pyc' -newermt "2026-09-25 21:04"` ⇒ 输出 **0**。🔴 **那是假零**：改用 python `os.walk` 现算同一判据 ⇒ **330 枚 `.pyc` mtime 晚于开窗**（`plugins/**` 326 ＋ `scripts/__pycache__` 4），时间簇为 21:07:05（一次性 326 枚，含 `doc_sync`/`board_doc_sync`/`physical_placement_census`/`doc_template_sync`）／21:14:10／21:15:19–20／21:21:51–52。⇒ 又一例"**一条命令的输出不等于事实**"（本机 `find` 与 `grep`/`rm` 同窗报 `command not found`，PATH 已局部失效，见 §6.8）。
2. **归属现算（不靠推测）**：本席做了一次控制实验——按与探针完全相同的环境（`-B` ＋ `PYTHONDONTWRITEBYTECODE=1` ＋ `PYTHONPYCACHEPREFIX=%TEMP%\s612-pyc`）二次加载 `domains/core/board_taxonomy.py`，该 `.pyc` 的 mtime **21:14:10 → 21:14:10 未变**，且 `sys.dont_write_bytecode is True` ⇒ **本席的六发探针零树污染**（`tests/**__pycache__` 计数亦为 0，本席一次 pytest 都没跑）。
3. 归属结论：330 枚属**并发写入窗**（本席窗口内另有进程在全量 import 插件包，形态＝`dev.ps1`/pytest/census 一类未带 `PYTHONPYCACHEPREFIX` 或带 POSIX 形态 prefix 的跑法，与台账 #50「`dev.ps1:73` 设 prefix、绕开它直跑会落树」同型）。**本席不清理、不代账**（备份搬运会撞并发写者，且非本席产物）；只登记，交由安静窗按铁律 6 处置。
4. 其余快照：`data/` 不在树内（`isdir=False`）✅；`.mypy_cache` mtime 16:16、`.ruff_cache` 18:35（**均早于开窗 21:04**）⇒ 他波残余，未触碰；`.pytest_cache` 不在树内 ✅；`domains/core/__pycache__/` 在场，mtime 21:14:10（第 2 条已排除本席）。

**本席写面与红线自证**

- 写面：`PINS-DENOMINATOR-BUILD-S612.md` ＋ `probes/s612-probe{1..6}.py`（六件，全在席目录，`.superpowers/` 已 gitignore）。探针入库副本与 `%TEMP%` 原件**逐字节等值**（本席用 sha256[:16] 双算核对，指纹见下）：
  `probe1 12,751 B 46c2fdfc2255c422`｜`probe2 9,376 B 853a4a02da349688`｜`probe3 8,494 B 771b8ce687eb30a4`｜`probe4 7,760 B c308073604154b14`｜`probe5 5,218 B 853d822048fc4344`｜`probe6 3,481 B cc044e44129284e9`。
  其余临时件全在 `%TEMP%`（`s612-probe*.json/txt/err`、`s612-pyc`、`s612-clean`）。
- ⚠ 本窗工具环境异常（如实记，非注入）：若干条命令里 `rm`/`grep`/`find`/`bash.exe` 报 `command not found`（PATH 局部失效）。⇒ 后果之一＝§6.7 第 1 条那次假零；后果之二＝**`%TEMP%\s612-clean` 这个本席建的空目录未删掉**（TEMP 内的临时件，不犯"禁写仓外"）。后续读数改用 Grep 工具 / python `os.walk` 重取，本文所有数字都出自**重取后**的读数。
- 红线逐条自证：**未改** `plugins/`、`scripts/`、`tests/`、`docs/`、`config.py`、根 `__init__.py` 任一字节（全程只用 Read/Grep 与只读 python）；**未读** `.env`；**未** 拨闸／`git` 写／删垫片／重启杀进程／装包／外部上传；**未跑** 全量 `dev.ps1 -Task test`（本席一次 pytest 都没跑，全部判据经"纯函数直调"求值，不依赖收集期）。

### 6.8 安全登记（规则 11）

本席在工具结果、在册件正文（S604/S594/S549 报告）、镜像源文件、`MEMORY.md` 索引行里**未遇到**任何要求执行动作的祈使句载荷；读到的是**关于**注入的报告文字（台账 #53 席 C 那条 OPEN 记录、AGENTS 规则 11 本体），一律当数据处置，未执行、未换工具、未停手。**命中数 0**，故无需消毒载荷入册。
本窗唯一环境侧异常是 PATH 局部失效（非注入），其后果与处置已如实记在 §6.7——**它同时制造了本席一次假零读数**，本席不把它记成"环境无害、读数无碍"。

### 6.9 交下去的三句（按可执行度排）

1. **落码席**：M0＝四件同笔（P1/P2/P3 ＋ P4/P5 跟随），一行修按 §3.1 手工插、`git diff --numstat` 自证 `1 0`；**别拿镜像去 `git apply`**；先把 §3.2-P6 那两枚未跟踪接缝测试处理掉，否则干净 checkout 当场红。
2. **主代理**：`%TEMP%\s594-mirror` 马上备份（P-S612-1）——本席所有"门真跑"的读数都挂在它身上，Temp 一清这半件就退化成转述。
3. **她**：两句——`bot_version` 走甲还是乙（§2.4）、tag 策略走丁还是丙（§4.4）。这两句不裁，`pins` 面**永远 0**，且 0 的理由是结构性的（§4 F-4），不是"没人有空填"。
