# PINS-CHANNEL-S764 —— 适配轴「库↔库版本区间声明」从无到有的唯一落点件

Status: SUBMITTED ｜ 席位 S764（批次 250926A-4，补位批 3）｜ 前题席位 S744（适配轴机检）
写面（纪律第 5 条，逐字守）：本件 ＋ `pins-channel/`（README／patch-01／patch-02／patch-03／rows-52）＋ `probes/s764-*.py`
红线自证：不落生产码、不动十库、不 commit、禁全量套件、注毒只 %TEMP%/内存夹具、卫生四件套＋`-B`、
禁仓树内 import plugins（全程 AST/JSON 尺）、`s744-adaptation-matrix.py` 与 `s0-main-lib-api-surface.py` 只读未动一字节。

**一句话总裁决**：mandate「统筹适配」缺的那半——「库 A 依赖库 B 的哪个版本区间」——**唯一落点已由
在册指名真身承载**（S594 设计、S612 实跑十条锁、S715 按 D-2甲 改形、S727 出可粘贴全文的
`workspace_manifest.py` 三件套之 `cross_library_edges`），本席交齐**可粘贴增量两处＋机器门判据原文
（含点名两把反制腿，杀伤力 16/16 实跑）**；52/52 零 pins 与守恒 **1343=261+494+588** 复算坐实。
**通道该落、码不该由本席落**：不挡在 D-5／环／761 脏树上——那三样改变的只是**数字与环账形态**，
守恒腿的设计本就是把漂移抓成「同批红」；可机检开工前置六条见 §四。

---

## §〇 开窗与锚（全部现算）

- 开窗 `date -u` ≈ **2026-09-26T07:0xZ**；收窗 **07:15:47Z**。
- 主仓 HEAD 跑前＝跑后＝`a5226ec`；声明源 `board_taxonomy.py` sha256[:16]＝`a76235f025024d69`（与 S744 同窗同值）。
- 工作树脏值现算 `git status --porcelain | wc -l` ＝ **993**（只报现值，不与他人窗比大小）。
- 三件套四件盘面现算：`workspace_manifest.py`／`workspace_manifest_sync.py`／
  `test_workspace_manifest_gate.py`／`docs/workspace-manifest.json` **四枚全 ABSENT**；
  候选全文在盘两处：席目录 `mirrors/s594-mirror/`（原件形）＋ `probes/s727-{wsm-decl,wsm-sync,gate,trio-run}.py`
  （**10 库改形后的可运行副本**——本席增量贴这一形）。
- 十库盘面：`ChatBot_Libs/<slug>/`×10 在场，`VERSION` 十枚全 `0.0.1`；① manifest 键面
  `@schema/authority_note/board_bid/members/planned_tag/slug/source/version/version_axis`——**无任何 depends 类键**。

## §一 52 对与守恒账复算（复跑 S744 尺，非转述）

复跑命令＝S744 报告 §陆 原样（JSON 落 `%TEMP%/s764-adaptation-matrix.json`）。**RC=0，attributable=true**。

| 账 | S744（06:41Z 窗） | 本席复算（06:52Z 窗） | 判定 |
|---|---|---|---|
| 守恒一 `总=跨+同+无主` | 1343＝261＋494＋588 | **1343＝261＋494＋588** | ✅ 逐值一致（前席转述的 1329=257+496+576 两窗皆已作废） |
| 非空格对数 | 52 | **52** | ✅ |
| 有边零 pins | 52/52（100%） | **52/52** | ✅ |
| 五通道 P1–P5 | 全零＋P4 不在场 | **P1=0，P2=0，P3=0，P4 present=false，P5 九词 9/9 各 0（总 0）** | ✅ `pins_verdict=NO_DECLARATION_CHANNEL_ON_DISK` 复现 |
| 面账↔现账守恒二 | 面 395＋4−0＝现 399（漂移 4 对） | **面 399＋0−0＝现 399（漂移 0 对）** | ⚠ 见下「面账已被重刷」 |
| 守恒三（面账带权） | 295 条×消费库＝331 | **298 条×消费库＝335** | ⚠ 同源 |

**如实报备：两窗之间（06:41→06:52）十份 `api-surface.json` 被重刷过**——本席读到的面账戳
`generated_at=2026-09-26T06:48:02Z、repo_head=a5226ec、声明源 sha=a76235f0…`（S744 当时读的是
`2026-09-25T20:41Z、ae096fc、636804ba…` 老化态），故 symbol 条目 295→298、漂移 4→0。
这不是读数矛盾，是 S744 §肆「拆库当日必须重刷面账」的待办**已被别席先执行了一次**；
本席据此把「面账老化」从适配账里销掉，同时点名：**写面账那一步会脏十库工作树**（S757/S763 在册议题），
本席全程未跑任何写面账的件。

**52 对逐对「要声明什么」**（禁手抄，由尺派生）＝`pins-channel/rows-52.expected.md`，
由 `probes/s764-requires-rows.py` 现算：逐对给 `requires_min=提供方①现版(0.0.1)`、
`requires_max_exclusive=下一 major(1.0.0)`（same-major 缺省策略）＋语句边/被消费符号/符号出现三列；
**行数和＝52、Σ语句边＝261、Σ符号出现＝399 三腿自身守恒不平即 exit 2**（实跑 RC=0）。

## §二 唯一落点：三案代价与推荐

硬要求先复述：**复用既有声明面与既有取数口，禁新建第二真身/第二通道；没有读点的声明＝在册未执法。**

| 案 | 形 | 致命伤（全部现算/在册判定，非推测） | 代价 | 判定 |
|---|---|---|---|---|
| **甲** 仓外各库 `workspace-lib.manifest.json` 增 `depends` 段**当真身** | 手填① | ①是工厂**整文件重写**的生成物（factory 注释原文「字段全派生、零手填」），手填 depends 下一轮工厂静默蒸发＝**声明会失踪的假绿**；且①自己的 `authority_note` 写着「指回账②与对账门未落地前不得当已受治理的登记面」——它自认投影 | 最低（改 dict 一键）但性质是坑 | **真身位不合格；投影位合格** → 改造为甲′并入推荐 |
| **乙** 仓内声明源加依赖维 | 乙1＝写进 `board_taxonomy.py`；乙2＝落 S594/S715/S727 已指名的 `workspace_manifest.py` ②真身 | 乙1 被 S715 §1.1 表3 **在册判死**：一册一轴、板块轴=功能归类≠发行轴，docs/boards 重算会被版本 bump 牵动、非板块库（contracts＋四 adapter）进不了 BNN 文法——本席复核该判由今仍成立（board_taxonomy 的 `inbound/outbound` 字段是散文标签，全树无 AST 判据读它，本席现算 grep 零读点）。乙2 无此伤：三面（策略/例外/豁免）＋生成器＋门＋② 是**一条既有通道**，S612 十条锁已在镜像上实跑 10/10 绿 | 四件同批＋文法四处同批（S715 §1.2-④-①：旧 `LIBRARY_ID_RE` 不认连字符、S727 件1 已改 `SLUG_RE`）＋跟随账（机器册/verify_hashes/chatbot-tasks sync 列/runtime-layout） | **推荐＝乙2 当真身，甲′当①投影** |
| **丙** 主仓 `pyproject.toml` 依赖表 | pip 面 | 三闸今天全关：姊妹库**无可安装形**（D-6 包名碰撞未裁：S751 实测同名件静默先到取胜、regular 池翻转；十库 tag 全 lightweight＋版本尺 R-S709-1 待裁 ⇒ 无发布面；无 index/remote）；且主仓 pyproject 是 **bot 版本权威**（`error_report._plugin_version` 真身，S612 0-E），塞库间边＝一册两轴；唯一强点「运行期真读」要等库 pip 化兑现 | 改 pip 环境语义、影响现网安装链 | **今日不可作落点**；远期路线 S634 已裁（案甲 uv.lock 打底＋破环后案丙 uv workspace 合流）与本席不撞 |

**推荐（一句）**：真身＝②指回账（`workspace_manifest.py` 三面 + `cross_library_edges`），
① manifest 的 `depends` 为其投影（甲′），丙留作 pip 化后的下游消费形——**三面两影一真身，零新通道**。

**谁读它（读点地图，缺一即不写）**：门禁期＝`tests/test_workspace_manifest_gate.py` 新增腿
（patch-03 全文，执法 `ADAPT-*` 五族＋L11 读点尺）；治理期＝库工厂（写①）、`s0-main-lib-sync-verify`
（①↔仓重算）、`s744-adaptation-matrix`（P2/P4 命中账）；**运行期＝零读者**（如实标：
它是治理元数据不是装配开关，mandate 的「适配」今天兑现到「门禁可检」，不等价于「线上执法」——
运行期约束力要等拆库后 pip/uv 面接管，S634 路线）。
⚠ 附带揭一笔（只报不改，该件写面非本席）：S744 的 pinned **逐对归因式半瞎**——P2 命中记为
`"{bid}->?:{k}"` 键，而逐对查找式只认 `"{c}->{p}"` 与 `"?:->{slug}"`（其 :401–403 原文），
① 落 `depends` 后其 verdict 会翻离全零、但 52 对仍逐对判不出「已钉」；**逐对权威位由 patch-03 门腿担**，S744 保持通道普查位。

## §三 可粘贴增量与机器门判据（全部在 `pins-channel/`）

- `patch-01-declaration-side.md`——**仓内声明源侧一处**：真身三面 `EDGE_RANGE_POLICY`
  （缺省 same-major）／`REQUIRE_OVERRIDES`（带 why，首拍空）／`ADAPT_WAIVERS`（带 why+expires、
  只降不升，首拍空）＋求值口 `expected_range` 唯一真身（门与生成器 import 同一份，禁三处各写算法）。
- `patch-02-manifest-side.md`——**manifest 侧一处**：工厂读②→① 写 `depends`（fail-closed：②缺席即
  FATAL，**缺键≠零依赖**）＋ `@schema /1→/2` ＋同批跟随五件（F1–F5，逐件点名今值证据）。
- `patch-03-gate-legs.py`——**判据原文**（可 exec 规格，落地并进 L-11 同门，禁另立第二件门）：
  - 反制腿②「删声明必同批守恒」＝`p_adapt_ledger_matches_ast` 双向差集：有边无行无豁免 ⇒
    `ADAPT-MISS`；有行无边 ⇒ `ADAPT-STALE`（悄悄删行必红在这）；行∩豁免 ⇒ `DUP`；豁免过期 ⇒
    `WAIVED-EXPIRED`；恒等式 `|覆盖|+|豁免|+|MISS|＝|computed|` 三分互斥；
  - 反制腿①「声明了无人读当场红」＝`p_adapt_no_silent_fields`（S612 L-11 **同族派生尺原样复用**，
    不另造机制：读点集从判据源码 AST 现算，禁手抄名册）＋逐对具体腿 `RANGE-DIVERGE`/`OVERRIDE-NOWHY`
    （S612 注毒 C「成对偷换全绿」那类病的 pair 级堵法）＋`DEPENDS-ABSENT`（缺键 fail-closed）；
  - 尺瞎自锁＝`p_adapt_empty_roster_selflock`（S664「分母为 0 不得恒真」＋S744 SL-4 同型：
    账有行而现算全零 ⇒ `GATE-BLIND-AST`；现算有边而行全零 ⇒ `PINS-DENOMINATOR-ZERO`；两全零 ⇒
    `EMPTY-EMPTY` 禁出漂亮空表）；
  - 环账 `report_adapt_cycles`＝**进度尺不作红门**（S715 §四在册判由）；本席实算今值＝
    **52 对构成单一巨型强连通（10/10 节点全入）、互为双向的库对 15 枚**，启发式删 22 边可达无环
    （⇒ 无环子集 ≥30；**精确最小破环集未暴力枚举**——52 边规模超 S612 的 10 边暴力位，如实标下界）。
- `rows-52.expected.md`——期望投影行 52 条（尺产物，重生成即覆盖）。

**杀伤力实跑**（`probes/s764-teeth.py`，内存夹具＝真矩阵 JSON＋真 VERSION；RC=0）：
**TEETH-OK shots=16 passed=16**——T0 基线全绿＋T0c 环账读数逐值命中；T1 删行⇒MISS、T2 幻影行⇒STALE、
T3a 换有效豁免⇒转绿（守恒放行显式豁免）、T3b 豁免过期⇒红、T4 加没人读的结构格⇒L11 点名、
T5a/T5b ①投影少条/整键失踪⇒PROJ-MISS/DEPENDS-ABSENT、T6 AST 尺瞎⇒BLIND-AST（STALE 洪水为
设计性伴红，走 companion 白名单）、T7 声明空转⇒DENOMINATOR-ZERO（MISS 洪水同理）、
T8 区间偷改⇒RANGE-DIVERGE、T9a/b 例外无 why/指向无此边⇒NOWHY/ORPHAN、T10 表外策略⇒UNSAT×52、
T11 解 D-5 新增边未随批⇒MISS 点名该对。逐发**单族命中、名单外串扰 0**。

## §四 今日该不该落

**裁决：通道判「该落」，本席按红线只交件不落码；开工不被 D-5／环／761 枚脏卡住**——
这三样各动什么、为何不拦：D-5 双认领只改 computed 集的**数字**（T11 预演证明新增边会被 MISS 腿
当场点名、随批补行＝设计意图）；环只决定无环腿的**形态**（进度尺，S715 判由在本席实算下仍成立）；
脏树只决定**落码窗**（安静窗纪律，与通道设计无关）。R-S709-1 亦不拦：②不存 raw 版本串、
逐对区间按现三段尺可比（十库 VERSION 今值全 `0.0.1` 全过尺）。

**可机检开工前置（逐条能被尺判真假）**：

| # | 前置 | 判据（可复跑） | 今值 |
|---|---|---|---|
| P1 | 四件同批在场 | `for f in plugins/bot_unified_runtime/domains/core/workspace_manifest.py scripts/workspace_manifest_sync.py tests/test_workspace_manifest_gate.py docs/workspace-manifest.json; do test -f "$f" && echo Y || echo N; done` ⇒ 四 Y 或四 N；**一半 Y＝禁止入库**（收集期红，S594/S612 §3.2 在册） | 今 4×N（未落，合法态） |
| P2 | 文法四处同批 | 落地真身 `SLUG_RE` 对 `BOARD_TAXONOMY[*].slug` 现算 **10/10 通过**（S727 件1 形已改；若有人回退成旧 `LIBRARY_ID_RE` ⇒ 0/10 当场可测） | 增量内已含 |
| P3 | 跑序两 pass 钉死 | `sync` 后跑工厂 depends pass；工厂缺② ⇒ RC=2 且**不产①**（patch-02 fail-closed 块可测：②缺席实跑注毒） | 待落 |
| P4 | 门腿并进 L-11 同门 | `pytest tests/test_workspace_manifest_gate.py` 收得到 `p_adapt_*` 四判据＋teeth 十六发在门件夹具上复跑全按预期 | 待落 |
| P5 | 跟随账 | `doc_sync --write`／`verify_hashes --write`／`chatbot-tasks.json` sync 列含新件／`runtime-layout` PASS——四尺各 rc=0 | 待落 |
| P6 | 安静窗 | `git status --porcelain \| wc -l` 收敛到版本化窗后落码；本席开窗现值 **993** 只作窗况不作判据 | 窗未关 |

## §五 在册未执法边界（写给下一个 AI，防把本件读成「适配已上线」）

1. 本席交付＝**声明通道的构造图纸＋杀伤力实测**，盘上通道仍不存在（P1 今值 4×N）。
2. 落地后执法位＝**门禁期**；运行期零读者是设计语义（治理元数据），禁叙述成「线上已在管版本适配」。
3. S744 探针的逐对归因半瞎（§二 ⚠）在门腿落地前保持——**「52/52 零 pins」这个标题数仍全真**，
   翻的只是它落地后的下一版读数怎么读。
4. contracts＋四 adapter 不在 52 对内（板块尺下其边落无主桶 588）——「非板块库怎么进依赖账」是
   S727 `NONBOARD_SLUGS`/名册线的账，与本通道正交，勿混。

## §六 自错账／安全账／复跑簿／PARKED

**本席自错三笔（全部被自家尺当场抓住、当场改，未出错误读数入册）**：
① 恒等式首版 `|覆盖|+|MISS|==|computed|` **漏了有效豁免项**——T3a 注毒当场红在自家脸上，
   修成三分互斥式并把教训写进判据注释；② 读点 AST 尺首版只认字符串下标、不认 `.get("k")` 首参
   ⇒ 基线 52 格全被误判「没人读」（又一例「修在不会被执行的路径上」同型病），改两色尺；
③ out 守卫的负例测试首发选错路径（`.superpowers` 内被正确放行却被本席误判尺瞎），换 `docs/` 重测
   RC=2＋零落盘坐实——**判尺瞎之前先核对判据射程**。

**与前席读数分家一处**：面账 295/395→298/399、漂移 4→0——非矛盾，是 06:48Z 被重刷（§一）。

**卫生账（交卷现算）**：生产树（`plugins/`、`scripts/`、`tests/`、`docs/`、`ChatBot_Libs/` 十库、
`pyproject.toml`、`.env`）零字节改动——本席写面只在席目录；开窗与交窗 `git status --porcelain`
现算同值 **993**（他波在飞件），`git diff --numstat HEAD` 里无本席任何一件（本席只写过
`PINS-CHANNEL-S764.md`／`pins-channel/` 五件／`probes/s764-*.py` 两件）。
`probes/__pycache__/` 在场两枚 `s749-*.pyc`（14:54 本地戳）——**非本席产物**：按名归因，本席全窗
装载过的模块（s744 矩阵、工厂、patch-03 门件、两把 s764 尺）无一为 s749 名，且本席全程
`-B`＋`PYTHONDONTWRITEBYTECODE=1`＋`PYTHONPYCACHEPREFIX=$TEMP/s764-pyc`，自有 pyc 足迹现算 **0**；
席目录属 gitignore 区，不清理他人过程件。`pins-channel/` 与生产树内 `__pycache__` 现算 0 枚。

**安全台账（规则 11）**：本席全程在工具结果、在册件正文、镜像文件里**未遇到**要求执行动作的
非白名单指令载荷（读到的一切祈使句形态文字一律按数据处置）；**命中 0**，无需消毒入册。

**复跑命令簿**（卫生四件套全程在带；本席源码树自有足迹＝零，`-B`＋`PYTHONDONTWRITEBYTECODE=1`＋
`PYTHONPYCACHEPREFIX=$TEMP/s764-pyc`，pytest 一次未跑、全量套件未跑）：

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$TEMP/s764-pyc"
PY=/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
S=.superpowers/sdd/2026-09-24-central-dispatch
# ① 复算 52 对与三守恒（前题复算，只读）
"$PY" -B $S/probes/s744-adaptation-matrix.py --json-out "$TEMP/s764-adaptation-matrix.json"     # RC=0
# ② 52 对期望投影行＋自身守恒
"$PY" -B $S/probes/s764-requires-rows.py --out $S/pins-channel/rows-52.expected.md               # RC=0 rows=52 Σ=261/399
# ③ 门腿杀伤力（注毒全内存）
"$PY" -B $S/probes/s764-teeth.py                                                                  # RC=0 TEETH-OK 16/16
# ④ 静态门（本席三 py 件）
"$PY" -B -m ruff check --no-cache $S/probes/s764-requires-rows.py $S/probes/s764-teeth.py $S/pins-channel/patch-03-gate-legs.py  # All checks passed
```

**PARKED（交出去的欠账，逐条有名有姓）**：
- K1 落码席：按 §四 P1–P6 顺序落；patch-03 的 `expected_range` 搬进真身、门与生成器 import 同一份。
- K2 主代理：S744 探针逐对归因腿跟进（其 :399–403 三行改法在 §二 ⚠ 已给定位；本席红线不动其件）。
- K3 她（不催，登记）：R-S709-1 版本尺收形——不拦本通道落地，拦「预发布段进区间比较」那一天；
  丙案（uv workspace）在 S634 路线上与本通道自然合流。
- K4 环账精确最小破环集未暴力枚举（52 边超位，本席只给启发式上界 22／无环子集 ≥30）——归拆库次序席。

done: yes
