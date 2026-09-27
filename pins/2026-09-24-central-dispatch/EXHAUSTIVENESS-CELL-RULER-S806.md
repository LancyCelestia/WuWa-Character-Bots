# EXHAUSTIVENESS-CELL-RULER-S806 —— 「三前置·物理归类（穷尽性）」格真判尺（三腿派生＋零测 FATAL）

Status: 交卷

席号 S806｜批次 250926A-B2｜任务一句话：把审计板上今天**手写 NO** 的穷尽性格做成现算判据——
无主目标（被引用面）枚数＝0 ∧ 入边＝0 ∧ 双认领＝0 ∧ 每枚生产件被**唯一**一级库认领，三腿全过才 YES；
任一腿抓不到数＝尺 FATAL（rc=2、不落裁决词）⇒ 板侧派生必落 NO。同时交「从现在到 0 分几批」的序列表。
本席窗：2026-09-26 `08:17Z–08:3xZ`（`date -u` 起 08:17:01Z、收 08:32Z）；树身份 HEAD=`a5226ec`。
板件开工现值：`probes/s0-main-goal-audit.py` sha256[:16]=`2200e19b509219f0`（板是移动靶，此值供 sha 复核）。

写面自证：只写①`probes/s806-exhaustiveness-cell.py`②`probes/s806-poison.py`③本报告。
审计板、`board_taxonomy.py`、`board_placement.py`、门件、s746/ranker/factory 三把被消费尺——**一字未动**
（逐字节 cmp＋sha16 双查，见 §六）。未 commit／未 push／未动 `.env`／未拨闸／未重启杀进程／未跑全量套件。

## §〇 判据口径与真身（谁定义的，本尺不重造）

| 腿 | 今判据 | 数的真身 | 本尺的消费方式 |
|---|---|---|---|
| L1 无主目标（被引用面）＝0 ∧ 入边＝0 | 目标文件的「无唯一主 ∧ 有入边」账 | `probes/s0-main-unowned-edge-ranker.py`（唯一一张引用账） | 壳调＋解析头行与逐枚行，并**复验其自账**（行数==枚数、入边求和==合计、逐枚目标 ⊆ 本尺现算无唯一主集，任一不平⇒FATAL）——假尺/瞎尺/截断都过不了这三关 |
| L2 双认领＝0 | 目录前缀认领语义 A 下命中 ≥2 支一级板块 | `scripts/physical_placement_census.py` 取数口＋`probes/s746-exhaustiveness.py` 的 K2（终态＋洗账·增＋洗账·删） | **import s746 并直调其 `run()`**（非壳调读文案、非第二把扫描器）：宇宙地板 500／板块地板 8／K1 守恒／与门 G-P2 的 unclaimed 逐枚交叉腿全部复用；wash_added/wash_removed 两枚洗账腿并入硬零（判据只准变严——D-5 落地必同批跟随名册常量，S746 §四纪律的板侧化） |
| L3 每枚生产件被唯一一级库认领 | sole_missing＝宇宙−唯一认领＝双＋无主A·B＋候选C | 同一次 `run()` 的四本账（K1 守恒保证等式，本尺复验该等式，不平⇒FATAL） | L3 归零蕴含 K3 归零（候选桶空⇒未点名集必空），不单列 K3 腿 |

- 宇宙两口径**如实并存、不硬凑**（见 §三互证账）：s746＝磁盘尺 `py_universe`（plugins/**.py ∪ 仓根 *.py，跳编译/环境目录）；
  ranker＝git 尺（tracked∪untracked ∩ plugins/*.py）。差集两侧各有名目，XCHECK 行逐值列数。
- 简报硬要求「任一腿抓不到数即 NO」的实现＝FATAL 路径**只**打 `FATAL(S806):` 行、rc=2、
  整段输出不含 `VERDICT`/`BOARD S806`——板侧 `grab()` 抓不到 ⇒ `num()`=None ⇒ `cell()` 必落 NO（空值糊不成绿）。

## §一 能量具设计（`probes/s806-exhaustiveness-cell.py`）

1. **零测即 FATAL 自锁**（四条，逐条有码、§六有注毒实证）：
   ① 仓根/取数口缺失、s746 装载炸、宇宙=0/低于地板、板块低于地板 ⇒ FATAL（复用 s746 fail-closed 通道，读不到≠没有）；
   ② ranker rc≠0／头行解析不到／逐枚行数≠枚数／入边求和≠合计／出现入边≤0 的行／目标不在本尺无唯一主集 ⇒ FATAL；
   ③ L3 算术式 `宇宙−唯一认领 == 双+无主+候选` 不平 ⇒ FATAL；
   ④ `--emit-json` 落仓内即拒跑（与 s746 同规），仓内零写入。
2. **判定派生**：`yes ⟺ unowned==0 ∧ edges==0 ∧ double==0 ∧ wash==0 ∧ sole_missing==0`，全部数在手才谈 YES；
   机读行 `BOARD S806 unowned=… inbound=… double=… sole_missing=… wash=…` ＋ `VERDICT: EXHAUSTIVE|INCOMPLETE`
   ＋ `XCHECK …` 对账行；JSON 全量落仓外（accounts/targets/xcheck 逐枚可点名，可直接喂 S749 切笔图）。
3. **假量具防线**（S760「整件假量具」教训的尺侧化）：ranker 与本尺是两套独立取数
   （AST 引用账 vs 认领分桶账），三关复验（§〇 L1 行）使「ranker 被换成嘴」只能制造 FATAL，制造不了 YES。
4. 退出码：0=三腿全绿（今日不可达）／1=NO（真实欠账，数都在）／2=FATAL（不落裁决词）。

## §二 今值实跑（2026-09-26 08:2x–08:3xZ，HEAD=a5226ec，尺＝worktree；此类计数均为**当时值**）

```
L1（ranker 口径）：无主目标 79 枚／入边 420 条
L2：双认领 5 枚（wash 增 0／删 0）
L3：宇宙 603＝唯一认领 467＋未认领 136（双 5＋无主A·B 48＋候选C 83）
XCHECK universe=603 no_sole=136 root_py=2 ranker_universe=634 ghost=33
       no_sole_in_ranker_universe=134 referenced=79 unreferenced=55 gp2_unclaimed=131 等式核对=True
BOARD S806 unowned=79 inbound=420 double=5 sole_missing=136 wash=0
VERDICT: INCOMPLETE        （rc=1）
```
注毒台基线行同值（`基线 rc=1｜BOARD={'unowned': 79, 'inbound': 420, 'double': 5, 'sole_missing': 136, 'wash': 0}`），
两跑间隔约 10 分钟、并写窗内未漂移。

## §三 三源互证账（逐值相等；不等的点名是哪把尺口径不同，不硬凑）

| 数 | s806 | s746 真跑 | ranker 真跑 | 判定 |
|---|---|---|---|---|
| 宇宙（磁盘尺） | 603（XCHECK universe） | 603（`counts.universe`，§二基线） | 不适用（git 尺 634，见下行） | **逐值相等** |
| 双认领 | 5 | 5（`counts.double`） | 不判（其「无主」含双认领，见目标行） | **逐值相等** |
| 唯一认领／未认领 | 467／136 | 467／(5+48+83=136) | 不适用 | **逐值相等**（同一次 `run()`，结构性同源） |
| 无主目标枚数／入边 | 79／420 | 不适用（s746 不数引用） | 头行 79／420，本尺由 79 枚逐行**复算求和**=420 | **逐值相等＋自账复验** |
| 门 G-P2 unclaimed | 131（XCHECK gp2_unclaimed） | 131（交叉腿逐枚相等） | 不适用 | **逐值相等** |

**两把尺宇宙口径差（点名，不硬凑）**：`634（ranker git 尺） − 603（s746 磁盘尺）＝ +33 幻影枚 −2 仓根枚`：
- **+33**＝`plugins/bot_unified_runtime/capabilities/**.py` 里 33 枚「盘上已删、git 未落账删除」的旧垫片路径——
  `git status --porcelain` 对该目录今值 27 行 ` D`（部分含目录聚合），33 枚全部 `is_file()==False`；
  今日对两账**零实害**（0 条入边指向它们，ranker 源侧 `is_file()` 守卫已挡），但序列表批次 3/收敛面必须消化这笔；
- **−2**＝仓根 `bot.py`、`config_risk.py`（在 py_universe 与无唯一主集内、ranker 口径物理看不见）——
  这就是「L1=0 远不够、YES 必吃 L3」的活例：此二枚若只盯 ranker 会被永久漏认。
- 算术闭合自证：634−33=601＝py_universe 的 plugins 部分；601+2=603；136−79=57＝134−79+2（ranker 口径 55 枚未引用＋根 2）。**全部现算。**

**对账中点名的两枚在册外发现（如实报备，不代修）**：
1. `board_placement.py` 盘上现算 sha16=`02741a3bcfbbfd3d`，而 S746 §三 记账 `02741a3bcfbbfd3f`（末位 d3f↔d3d）；
   本席 `git status` 见该件对 HEAD **干净** ⇒ 二者之间文件未变，疑似 S746 誊册末位笔误——**不代归因、不改他席件**，留该席 owner 复核。
2. `s0-main-lib-factory.py` 盘上全 sha=`e952b0914000ae0b…`，审计板 `PINNED_GAUGES` 钉的是 `e0cb6055405a44e6…`
   ——**08:2xZ 现算即不符** ⇒ 板今日实跑「量具钉册」格本身就 NO（并发窗他波改过 factory 未 repin）。主代理接线本尺前**先裁 factory 这笔账再 --repin**，
   否则 repin 会把一笔未归因漂移静默洗成合法。

## §四 序列表：从现在到 0 分几批（今值派生，逐批消几枚／前置是谁）

总账：**5 个债批＋1 个接线批**消完三腿全零。消枚合计 5+74+32+25=136＝今值 L3；其中 L1 的 79＝5+74。
（数字全为本席窗**当时值**，并发窗在长，各批落地时以该尺复跑现算为准。）

| 批 | 消什么（腿·枚数） | 前置是谁（不先解则怎样） | 落码面 | 授权标 |
|---|---|---|---|---|
| **1** | L2 双认领 5→0；L1 −5（79→74）；L3 −5 | **无前置，它自己是全场前置**：D-5 未解则一切指向 `domains/chat_reply/character/`、`domains/ops/monitor/` 两吞区的补认领**必撞双认领**（wash_added 当场点名、本格永 NO）；且 B-0 切笔图/建库 pathspec 对这 5 枚无法点名 | `board_taxonomy.py` 两处目录声明缩为逐枚列举（S750 补丁端到端验通、S800 三十秒执行包在盘）＋**同批**跟随 s746 `K2_DOUBLE_CLAIM_ROSTER` 常量与 G-P2 违规账 | ⚑**须她**（D-5 裁定＋落码授权） |
| **2** | L1 74→0 ∧ 入边 420→0；L3 131→57：D-5 吞区**外**被引用簇 74 枚（A/B 16＋C 58；簇今值：domains/runtime 15、domains/contracts 11、domains/capabilities 7、domains/safety_exec 6、domains/supervisor 6、domains/self_calendar 5、顶层 runtime 6、顶层 character 4、domains/smoke 3、其余散枚 13） | 可与批 1 **并行**（簇逐枚核过不在两吞区下）；真前置是**归属本身**：safety_exec 族（8 枚）／self_calendar 族（5 枚）等 18 枚 K3 未点名者须先「定库或入不收名册」——S796 逐目标三选一方案是落地依据，其中无归属共识者**须她裁**；旧路径幻影（33 枚）不落账不影响本批（它们零入边、不在 74 内） | 声明面（`board_taxonomy.py` impl_paths 补认领），不改生产根 `__init__.py` | 部分⚑（未入册族定库） |
| **3** | L3 57→25：A/B 薄壳未引用 32 枚 | **前置＝15 枚垫片退役单在她手里执行＋旧路径件归位落账**——向「已删未落账」或「待退役」路径补认领＝白做且认领会漂（33 枚幻影就是本病的现行账）；退役每落一笔，本批枚数自动缩小，落地时复跑棘轮重算 | `board_placement.py` G-P2 棘轮与退役单跟随；存活薄壳走批 2 同面补认领 | ⚑**须她**（垫片删除是 git 写、执行权在她） |
| **4** | L3 25→0 ⇒ 三腿全绿：C 档未引用 25 枚（含仓根 `bot.py`、`config_risk.py`——ranker 口径看不见根级，全靠本腿兜住） | 前置＝批 2（K3 点名账口径先立，避免同一枚两种定法两本账）；根级两枚须在声明源可表达（census 语义 `rel==path` 逐字面可认领，本席现算未试改） | 声明面补认领／入名册逐枚带据 | — |
| **5** | （消 0 枚）板上格改判派生通道打开 | 前置＝批 1–4 中至少把「板要不要吃这格」定了；**接线前主代理先裁 §三-2 那笔 factory 钉册不符**，再 `--repin --reason` | 审计板（写面归主代理）——本席只交 §五片段 | ⚑**主代理**（板＋钉册） |
| 收敛面 | （不消债）两本账宇宙合流：33 枚幻影 git 删除落账 ⇒ ranker 尺 634→601，与磁盘尺只差收敛到根级 2 枚 | 与批 3 同前置（她的 git 执行）；批 1–4 期间两账由 XCHECK 行逐值对账，不强行并一 | git 账（她执行） | ⚑**须她** |

- 「零枚批不合法」防呆：批 5 若在无债批落地前接线，板格照样现算红（今值 79/420/5/136 全在场）——接线与清债互不阻塞、互不遮丑。
- 全程**没有任何一批**需要改生产根 `__init__.py`；⚑她的集中在批 1（裁）、批 3（垫片删）、收敛面（删除落账）三处。

## §五 可粘贴接线片段（**未落码**——板与钉册的写面归主代理；落码前先按 §三-2 裁 factory 账）

```python
# ① SOURCES 字典加一行（与 "outside" 条目并列）：
    "exhaust": "s806-exhaustiveness-cell.py",  # 三前置·物理归类（穷尽性）：三腿派生（S806）

# ② PINNED_GAUGES 加一行后跑 `--repin --reason "S806 穷尽性格尺入册"`（repin 按现盘重算全部——
#    故务必先裁 factory 那笔未归因漂移，勿把洗账搭车办掉）。本尺全 sha（08:3xZ 现算）：
#    ecaa184afcce495909f31becbbd5676e47fc07fff471d90fccc88a89d10f59dc
    "s806-exhaustiveness-cell.py": "ecaa184afcce495909f31becbbd5676e47fc07fff471d90fccc88a89d10f59dc",

# ③ run() 调用段（rc_ou 之后）：
    rc_x, out_x = run("exhaust", [])

# ④ 取数段（与其它 grab 并列；抓不到＝"?"＝None＝判 NO）：
    exh_ver = grab(out_x, r"VERDICT: (\w+)")
    ex_un, ex_ed = grab(out_x, r"unowned=(\d+)"), grab(out_x, r"inbound=(\d+)")
    ex_dbl, ex_sole = grab(out_x, r"double=(\d+)"), grab(out_x, r"sole_missing=(\d+)")
    ex_wash = grab(out_x, r"wash=(\d+)")
    exh_n = [num(ex_un), num(ex_ed), num(ex_dbl), num(ex_sole), num(ex_wash)]
    exh_j = cell(rc_x, exh_ver, "EXHAUSTIVE", *exh_n) if exh_n == [0, 0, 0, 0, 0] else "NO"

# ⑤ 替换手写 NO 的那一行（原行）：
#   f"| 三前置·物理归类（穷尽性） | 无主目标被引用面归零、双认领归零 | 无主目标 {unowned_files} 枚／入边 {unowned_target_edges} 条 | NO |",
#  改为：
    f"| 三前置·物理归类（穷尽性） | 无主目标(被引用面)＝0 ∧ 入边＝0 ∧ 双认领＝0 ∧ 洗账＝0 ∧ 无唯一一级库认领＝0；"
    f"任一腿抓不到数＝尺 FATAL(rc=2)＝不可判⇒NO（S806 三腿派生，判定不手写） | "
    f"无主 {ex_un} 枚/{ex_ed} 边、双认领 {ex_dbl}、未认领 {ex_sole}、wash {ex_wash}（`{exh_ver}`） | {exh_j} |",
```
附注：接线后 `run("census", ["--top", "1"])` 与 `unowned_files/unowned_target_edges` 两个 grab 仅供该行旧文案，
变成死调用——留删由主代理一并裁（本席不代动板件）。`built==0` 折叠段**不**含本格：本尺读仓根不读库根，
与库根空态正交，勿误挂。

## §六 注毒四发（`probes/s806-poison.py`，HARNESS_RC=0 实跑，副本全在 %TEMP%/s806-poison/）

| 发 | 注入（全在 %TEMP%，真身零写） | 预期 | 实跑 | 判定 |
|---|---|---|---|---|
| A 库根空／宇宙 0 | `--repo` 指假仓根（plugins/、scripts/ 皆空） | rc=2、无裁决词 | rc=2、FATAL(S806) 在场、`VERDICT`/`BOARD S806` 均不在场 | **抓到了**（扫不到绝不报成没问题） |
| B1 L1 尺失明 | `--ranker` 喂「什么都不印、rc=0」的假尺 | rc=2、无裁决词 | rc=2、FATAL 点名「头行解析不到」、无裁决词 | **抓到了**（假尺不供数⇒拒判，不折 0） |
| B2 L1 被喂全零假账 | 假尺印**自账自洽**的 0/0 头行 | rc=1、格仍红 | BOARD=`unowned=0, double=5, sole_missing=136`、VERDICT: INCOMPLETE | **抓到了**（单腿造假翻不动整格——三腿合取为真） |
| C 第 6 枚双认领 | 声明源副本把 `plugins/bot_unified_runtime/__init__.py` 追加进另一板块 fid `B01.mail-console`（同 S746 注毒② 手法；锚点唯一性＋compile 自检先行） | 数随声明源而动 | double 5→**6**、wash=**1** 且点名 victim、sole_missing 136→**137**、L1 不随动（79/420）、rc=1 | **抓到了**（派生是活的；手写 NO 的格做不出这种联动） |

- 基线不合法则注毒台拒开（要求 rc=1 ∧ INCOMPLETE ∧ double>0 ∧ unowned>0 ∧ sole_missing≥double——拿瞎尺验牙不算数）。
- 注毒 C 尝试史 `[]`＝零跑坏；交叉污染＝零（A/B1/B2/C 各打各腿，其余腿读数与基线逐一相同）。

**还原自证（逐字节 cmp＋sha16 双查）**：守护七件开工/收工同值——
`board_taxonomy=a76235f025024d69`、`board_placement=02741a3bcfbbfd3d`、`test_physical_placement_gate=02e28e3db1af7d3f`、
`s746-exhaustiveness=e82457859e02f4f5`、`s0-main-unowned-edge-ranker=04101548b2078e73`（与板钉册前 16 位相符）、
`s0-main-lib-factory=e952b0914000ae0b`（**与板钉册不符的那把，见 §三-2**——不符是他窗既成事实，本席未碰）、
`s806-exhaustiveness-cell=ecaa184afcce4959`。真身未动=True；sha 前后同值=True。

## §七 本包没做成什么／诚实缺口

1. **板没接线**（红线：写面归主代理）——§五只交文本；「手写 NO」今天仍在板上，本席交付的是**可换掉它的尺**。
2. L1 与 L3 的引用账复用 ranker 的 AST 通道，本尺不复解析（禁第二真身）；若 ranker 被**合法改版**改了输出格式，本尺以「解析不到⇒FATAL」自保，不会静默错判——改版席须同窗跟随本尺锚点（`RANKER_HEAD_RE`）。
3. 「唯一一级库」按 fid 首段聚合（同一板块内多 fid 认领一枚不算双）——这是归属门/门 G-P2 的既有语义（一级板块粒度），若 she 将来裁到 fid 粒度，本尺随语义 A 参数一处跟。
4. 序列表枚数为 08:2xZ **当时值**；并发窗每波落盘都会漂移，各批落地时以复跑现算为准；批次 2/4 的「散枚 13／25」按目录簇粗分，细到逐枚的三选一归 S796 账（其主件在本席窗仍 `done: no` 在飞）。
5. 未跑全量四门禁／真机（红线）；未 import plugins；注毒 A 的 fatal-JSON 在该分支不落盘（仓根都定位失败时不猜路径），已如实打印 False。
6. **卫生归因（收工现算 08:34Z）**：`find plugins scripts -name '*.pyc' -newermt "08:12"`＝**零枚**——源码树里 mtime
   被顶新的 11 个 `__pycache__` 目录是并发窗他波改写，本席窗口未向树内产出任何字节码（全程卫生四件套＋`-B`）；
   `probes/__pycache__/s802-rehearsal.cpython-312.pyc` 系 S802 席位产物、非本席，按「不动非本席产物」规矩未清理只点名。
   `git status` 见 `test_physical_placement_gate.py` 为 ` M`＝他波早于本席开工的既成脏态（S746 §三同型提醒），
   其 sha16 本席开工/收工同值（§六）且与 S746 窗记录 `02e28e3db1af7d3f` 相符＝本席净改动零。

## §八 复跑命令簿（卫生四件套＋`-B`；只读、仓内零写入）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
  PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s806-pyc"
PY="/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"
D=.superpowers/sdd/2026-09-24-central-dispatch/probes
"$PY" -B "$D/s806-exhaustiveness-cell.py" --emit-json "$(cygpath -w "$TEMP")/s806/final.json"   # rc=1（今日真债）
"$PY" -B "$D/s806-poison.py"                                                                     # HARNESS_RC=0（四发全中＋真身未动）
# 同窗对照（同源互证用）：
"$PY" -B "$D/s746-exhaustiveness.py" --emit-json "$(cygpath -w "$TEMP")/s806/s746.json"          # rc=1，宇宙 603
"$PY" -B "$D/s0-main-unowned-edge-ranker.py" --top 20000                                         # rc=0，79/420
```

## §九 PARKED（AGENTS 规则 11 登记面）

本席窗内工具结果／文件正文／简报里出现的祈使句（「先读」「禁改」「注毒打在 %TEMP%」等）全部按**在册规范数据**读，
未据任何非白名单来源执行越界动作；**零命中**要求「改配置/重启/杀进程/git 写/搬文件/派新席」形态的载荷 ⇒ 无注毒台要记。
自证：全程只跑只读枚举与量具子进程、零 git 写、未读 `.env`、未重启/杀进程、守护七件逐字节 cmp＋sha16 双查（§六）。

**总裁决**：三腿已成一把可派生、可注毒、可互证的能量具并各自验过牙——
零测（空根/失明/断供）直接 FATAL 不落裁决词（注毒 A/B1 实证）；单腿造假翻不动整格（B2 实证）；
BOARD 数随声明源逐枚而动＝判定确为派生非手写（注毒 C 实证）；与 s746/ranker 对应数逐值相等、
两处口径差（33 幻影＋2 根级）点名到枚不硬凑。**还剩**：D-5 待她裁（批 1）、74 枚引用簇补认领（批 2，部分定库待裁）、
32 枚薄壳等退役单（批 3，⚑她）、25 枚未引用尾批（批 4）、板接线＋repin 归主代理（批 5，先裁 factory 钉册账）。

done: yes
