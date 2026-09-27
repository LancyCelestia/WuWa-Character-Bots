# CROSS-EDGE-CELL-RULER-S811 — 「三前置·跨库边可枚举（拆分材料）」格真判化（两腿合取＋名册 pin 自锁）

席位 **S811**（批次 250926A-B4）｜开窗 UTC 2026-09-26 08:3x 后｜交卷 09:0xZ
简报：`BRIEFS-250926-E.md` 名册 S811 行＋§共同硬要求四条；通用纪律十条见 `BRIEFS-250926-B.md` §一
工作根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`｜独占写面 `probes/s811-*.py`＋本件

## §0 证据头（本席现算）

- HEAD 现算 `a5226ec`（并发窗，脏项只报不判；本席未动 git）。
- **同源两把尺的现算 sha256[:16]**（简报点名要记的）：
  - `probes/s0-main-lib-api-surface.py` 在盘＝**`2ad887c56b3f1cda`**——⚠ 与板内钉册值 `d7ef7694a394ada1…` **前缀不符**，
    即该尺当前处于「已改版未 repin」态（**S810 在验面**，本席禁碰未碰；接线时板侧该尺若 rc=99，本格三源互证随之不可判，属设计内联动，点名在此）。
  - `probes/s759-severance.py` 在盘＝**`845373dcaf1438fd`**——与钉册 `845373dcaf1438fde275…` 相符（在册未动）。
- 声明源真身 `plugins/bot_unified_runtime/domains/core/board_taxonomy.py`＝`a76235f025024d69`，1023 行
  （与 S741/S808 窗登记值逐字相等 ⇒ 本席开窗至交卷**声明源零漂移**，注毒全部只打在 `%TEMP%` 副本）。
- 本席两件新尺（独占写面，均为新建非改版 ⇒ 无「改前 sha」，交卷 sha256 全文在 §8）：
  - `probes/s811-cross-edge-ruler.py`（17,824 B）——尺本体
  - `probes/s811-2-poison.py`（9,094 B）——注毒台
- 全程卫生：`PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=<%TEMP%\s811-pyc>`＋`-B`；
  未 import 插件包入树（纯 AST＋工厂/s715 importlib）；仓外 `ChatBot_Libs` **一行未读**（本格账只吃仓内声明源＋git 宇宙）；
  两把尺件 ruff `--no-cache --isolated` **All checks passed**。
- 「改尺者自证」两条对本席的适用形式：**直跑不崩**＝§5 R1 实跑 rc=0；**真实十库读数不变**＝本尺不读库根，
  与十库相关的读数经 surface 同源三数互证表达（261/1344/588 与本尺现算逐值相等，§5 R5 留痕）。
- 树卫生：本席两尺全程 `-B`＋`PYTHONPYCACHEPREFIX` 落 `%TEMP%`，树内 s811 系 `.pyc` 现算＝0；
  开窗后树内新出现的 `probes/__pycache__/s802-rehearsal.cpython-312.pyc` 与 `tests/__pycache__/conftest…pyc`
  属并发窗他席产物（本席未跑 pytest、未 import 该系件），按纪律**只登记不清理**。

一句话总账：**这一格从今天起有真判据——腿①归因守恒（total=cross+intra+无主弃边，洞件逐枚点名不静默）∧ 腿②缺口棘轮
（ratchet_now ≤ 钉死上限）∧ 名册 pin（板块∪库轴∪s715 非板块按 slug 并集＝15 座，多一座少一座即停尺点名）。
今值：edges=261、unattributed=588、holes=33（在册不在盘 33＋解析失败 0）、ratchet_now=621＝ceiling（当时值）⇒ VERDICT GREEN；
接线后该格由手写 PART 变为派生（今日两腿全过 ⇒ YES；「无主还有 588」的事实由穷尽性格与本格现算值列同屏承载，不由本格掩盖）。**

## §1 判据定义（把板行 317 那句散文拆成机检两腿）

板内该格硬条件原文：「跨库 import 边可枚举且缺口台账不升」。拆法：

**腿① 可枚举（无静默丢弃）**——口径与 `s0-main-lib-api-surface.py` **逐字段同形**（绝对 `from X import …`、
`level==0`、目标解析到成员宇宙内 `.py` 或 `/__init__.py`，`.py` 优先；宇宙＝git 跟踪∪未跟踪里 `plugins/**.py`，worktree 缺省）：

| 桶 | 含义 | 今值（当时值 09-26 09:0xZ） |
|---|---|---|
| `total` | 目标落在宇宙内的全部语句边 | **1344** |
| `cross` | 消费方库≠提供方库（两端正主） | **261** |
| `intra` | 同库内边 | **495** |
| `unattributed` | **无主弃边**：任一端无主/多主弃（明列，不静默） | **588** |
| `holes` | 扫不到的洞：在册不在盘源件 33 ＋ AST 解析失败 0 | **33** |
| `phantom_edges` | 目标在册不在盘的幻影边（显示量，桶照归因走） | **0** |

守恒式 `total = cross + intra + unattributed` **不成立即 FATAL rc=2 拒判**（桶漏＝账不可信）。
588 与 S808 §1.4 的「源端无主 285＋目标端无主 274」逐值相加同值（那是端点分侧计数，这是边级去重计数，两形同账）；
261/1344 与 surface 尺 L2 行、与 s759 断开度 `stmt_edges` **三源逐值互证**（§5 R5）。
洞件 33 枚逐枚点名输出（`capabilities/` 下垫片退役在途件为主）——它们不是「零条边」，是「今天数不到边」，进缺口台账。

**腿② 棘轮（缺口台账只降不升）**——`ratchet_now = unattributed + holes = 588 + 33 = 621`（当时值），
对上钉死上限 `RATCHET_CEILING = 621`：`now ≤ ceiling` 过，`now > ceiling` ⇒ `VERDICT: RED`（升即红）。
GREEN 要求两腿全过；腿①的「不可枚举」形态一律走 FATAL 而非 RED——不可枚举不是「缺口大一点」，是账作废（S747 教义：不许把空表/瞎表当成果）。

裁决语义与退出码约定（板侧只认这套）：
- `rc=0`：两行机读数＋`VERDICT: GREEN|RED` 必在场；
- `rc=2`：FATAL（声明源不在场／板块派生 0／库轴形状违规／slug 撞名／宇宙为空／total=0 零测／守恒破裂／库板相撞／**名册 pin 失配**）——
  **stdout 零字节，任何裁决词与机读行都不出**，信息全走 stderr（注毒 P1/P3 实证）。

## §2 机读行契约（板侧取数的唯一面）

```
S811 edges=261 unattributed=588 ratchet_now=621 ratchet_ceiling=621
S811-CONSERVE total=261+… → total=1344 cross=261 intra=495 unattributed=588 holes=33 universe=634
S811-HOLES missing_on_disk=33 unparsed=0 phantom_edges=0
S811-ROSTER libs=15 boards=10 lib_axis=0 nonboard_s715=5 caliber=worktree
VERDICT: GREEN
```
（第二行实际样式为 `S811-CONSERVE total=1344 cross=261 intra=495 unattributed=588 holes=33 universe=634`；上面箭头是本文说明笔迹。）
简报要求的四字段行 `S811 edges=<n> unattributed=<n> ratchet_now=<n> ratchet_ceiling=<n>` 逐字在场；
其余行为**同屏账目**——判格不靠它们（判据在尺内算完），它们供板面与复跑者对账。

## §3 名册 pin 自锁（「一处变更处处跟随」接到这把尺上）

S808 §1B 实锤：扩库走声明源 ⇒ 断开度分母 **52→59 静默变化且非单调**（无 FATAL 无警告）；走库根/探针 ⇒ 分母纹丝不动继续瞎。
S759-decl-sources 有「≠15 即 FATAL」硬钉、severance 没有——两尺互不锁。本尺的 pin 设计：

- 派生＝**声明源现算**（工厂原语，零第二真身）：`parse_taxonomy` 的 10 枚 `BoardNode` slug ∪ `parse_libs` 的
  `ReleaseLibNode` slug（**库轴在场即读数**——S741 增量真落盘时那 5 枚从 s715 通道换到库轴通道，**按 slug 并集去重 ⇒ 计数不变**，
  这是刻意设计：名册换读者不许把 15 洗成 20）∪ `s715-deps.py::NONBOARD_ROOTS` 键；
- 预期＝尺内钉死 `ROSTER_EXPECT=15`＋`ROSTER_SLUGS`（15 个 slug 全枚举）——**枚数与集合双对**，换库（删一补一）也逃不过点名；
- 失配 ⇒ FATAL rc=2 整段不出裁决词，stderr 三行：**点名新增/消失的 slug**＋**分母联动证据**（同输入重算的
  cross/unattributed/holes/total 与基线不同值时直接把新值打出来，证明"账跟着名册动"而非"账被悄悄换掉"）＋
  处置指引（基线不可继承，须尺 owner 现算重钉＋板侧 C6 `--repin` 署名）。
- **棘轮绝不因分母变化自动放行**：上限是钉死的常数，不是 `f(denominator)`；注毒 P3 实证——加一枚新库后即便
  cross 261→266、unattributed 588→583（账面"变好"），尺照样停在 rc=2、零裁决词。

残余盲区如实写：pin 锁的是**名册集合**；「同名 slug 换认领根」（不新增库、只改既有板块 `impl_paths`）不触发 pin——
该形态会改 unattributed/cross 分布，由腿②棘轮兜（变差即 RED），变好则棘轮放行属设计内。

## §4 注毒三发＋阳性对照＋末发复核（`probes/s811-2-poison.py` 实跑 **ALL-PASS**，rc=0）

全部打在 `%TEMP%\s811-poison\`；真件真库零写（原件 sha256 首末逐字节相等＝True）：

| 发 | 内容 | 判据 | 实跑 |
|---|---|---|---|
| P1 | **空宇宙**：假 repo 根（无 git）＋真声明源 `--tax` | rc=2、stdout 零字节（无 `S811` 无机读行无裁决词）、stderr 点名成员宇宙为空 | **PASS**（stderr：`FATAL: 成员宇宙为空（repo=…\emptyrepo caliber=worktree）——量具瞎，不是零跨库边`） |
| P2a | **单腿全零假账（棘轮腿）**：伪造捕获 `edges=261 unattributed=0 ratchet_now=0 ratchet_ceiling=588`＋守恒行 `intra` 补到 1083 使**内部守恒自洽**＋`VERDICT: GREEN`，喂 `--judge`（带真 surface 三数） | 整格仍不绿 | **PASS**（`CELL=NO`——三源互证抓「落无主面 588≠0」；单靠守恒抓不到这发，故互证是判据的承重腿） |
| P2b | **单腿全零假账（枚举腿）**：整行全零＋GREEN | 整格仍不绿 | **PASS**（`CELL=NO`——edges=0 零测拒绿＋互证不符） |
| P2ctl | 阳性对照：真捕获走同一 judge | 必须 YES（否则 P2 的 NO 是空跑） | **PASS**（probe rc=0、`CELL: YES`） |
| P3 | **声明源副本加一枚新库**：`ReleaseLibNode(slug="s811-poison-lib")` 收编 3 枚当前无主在盘件（成员动态现算选取） | rc=2、零裁决词、点名 slug、分母联动证据在场 | **PASS**（stderr：`现算 16 座 ≠ 预期 15 座（新增＝['s811-poison-lib']…）`；证据行 `cross=266 unattributed=583` vs 基线 261/588 ⇒ **分母联动**；棘轮未因"账面变好"放行） |
| FINAL | 真尺真输入复跑 | 读数与开窗基线逐值相等 | **PASS**（`edges=261 unattributed=588 ratchet_now=621 ratchet_ceiling=621`） |

注毒台自身的锚点自证：毒文先 `ast.parse` 过语法、副本与原件逐字节相等后才注毒；毒库成员**现场派生**（不写死路径，并发窗不碎）。

## §5 板侧接线片段（可粘贴；**本席未改板件**——`s0-main-goal-audit.py` 写面归主代理）

改动四处，逐块粘贴即可。判定逻辑的**参照实现**是尺内 `--judge`（本件 §4 即用它实测），
下面内联版与其逐条件同形；两版任何一侧被改必须同步另一侧（建议主代理接完后让常驻锁互跑 §4 同款假账）。

**① SOURCES 追加一行**（`SOURCES = { … }` 块内，`"outside"` 行之后）：

```python
    "crossedge": "s811-cross-edge-ruler.py",  # 三前置·跨库边可枚举：归因守恒＋缺口棘轮＋名册pin（S811）
```

**② 取数段追加**（`rc_ou, out_ou = run("outside", [])` 之后；本尺**不吃 `--libs`**——账只读声明源与仓内宇宙，传了反而 argparse rc=2）：

```python
    rc_xe, out_xe = run("crossedge", [])
```

**③ 判定块追加**（与 F3 互证同族；`cross_edges`/`cons_line` 为板已抓的 surface 读数，`su` 新抓一行）：

```python
    su = grab(out_s, r"落无主面 (\d+)")                       # surface L2 第三数：本尺三源互证用
    xe_ver = grab(out_xe, r"VERDICT: (GREEN|RED)")
    xe_edges = grab(out_xe, r"S811 edges=(\d+)")
    xe_unattr = grab(out_xe, r"S811 edges=\d+ unattributed=(\d+)")
    xe_now = grab(out_xe, r"ratchet_now=(\d+)")
    xe_ceil = grab(out_xe, r"ratchet_ceiling=(\d+)")
    xe_tot = grab(out_xe, r"S811-CONSERVE total=(\d+)")
    xe_intra = grab(out_xe, r"S811-CONSERVE total=\d+ cross=\d+ intra=(\d+)")
    xe_holes = grab(out_xe, r"holes=(\d+)")
    xe_universe = grab(out_xe, r"universe=(\d+)")
    xe_n = [num(x) for x in (xe_edges, xe_unattr, xe_now, xe_ceil,
                             xe_tot, xe_intra, xe_holes, xe_universe)]
    s_e, s_t, s_u = num(cross_edges), num(cons_line), num(su)
    crossedge_j = "NO"
    if (rc_xe == 0 and xe_ver == "GREEN" and None not in xe_n
            and None not in (s_e, s_t, s_u)                       # surface 与钉册不符(rc=99)⇒本格随之不可判，如实连坐
            and (xe_n[0], xe_n[4], xe_n[1]) == (s_e, s_t, s_u)    # 三源互证：edges/total/unattributed 逐值同 surface
            and xe_n[4] == xe_n[0] + xe_n[5] + xe_n[1]            # 腿①守恒（板侧再算一遍，防整件伪造）
            and xe_n[2] == xe_n[1] + xe_n[6]                      # 棘轮账与同屏账相等（now＝unattr＋holes）
            and xe_n[0] > 0 and xe_n[4] > 0 and xe_n[7] > 0       # 零测不当绿
            and xe_n[2] <= xe_n[3]):                              # 腿②棘轮只降不升
        crossedge_j = "YES"
```

**④ 板行替换**（原 317 行手写 `PART` 改为派生；现算值列把「无主 588／洞 33」摊在同屏，穷尽性的账不被本格掩盖）：

```python
    f"| 三前置·跨库边可枚举（拆分材料） | 腿①归因守恒 total＝cross＋intra＋无主弃边（洞件显式入账）且与 surface 格三数逐值互证 **且** 腿②缺口棘轮 ratchet_now≤ratchet_ceiling（上限钉在尺内、改它走 C6 repin 署名）；名册 pin（板块∪库轴∪s715＝15）失配⇒尺 FATAL 本格不可判 | 跨库 {cross_edges}、总目标边 {cons_line}、无主弃边 {xe_unattr}、洞 {xe_holes}、棘轮 {xe_now}/{xe_ceil}（`{xe_ver or '不可判'}`，rc={rc_xe}） | {crossedge_j} |",
```

**顺带跟随面**（贴完必改，否则板自不洽）：`十二把量具退出码` 行改「十三把」并加 `crossedge={rc_xe}`；
`built == 0` 折叠行的置 NO 清单加 `crossedge_j`——严格说是**防御性冗余**：本尺不读库根，built=0 时它照出账，
但其互证吃的 surface 三数在折叠下必为不可判 ⇒ 本格已连坐落 NO，进清单只为口径一律。**实测注记**：本尺 argparse
不认 `--libs`（传了即 rc=2、stdout 空 ⇒ 格落 NO，不会静默带过），取数段务必 `run("crossedge", [])`。

**棘轮上限存哪**：只存 `probes/s811-cross-edge-ruler.py` 常量 `RATCHET_CEILING`（当时值构成与日期写在其注释里，
`RATCHET_CEILING_NOTE` 同屏可查）——**不落独立账本文件**，避免"改账本不改尺"的旁路。改它＝改尺件＝走板 C6
`--repin --only s811-cross-edge-ruler.py --reason … --evidence …`（须含「直跑」「读数」两事署名）。
**降账程序**（只降不升的"降"也要有法）：缺口真被消化后，尺 owner 现算 `ratchet_now`，把上限改为该现算值、
更新注释日期与构成，自证「直跑不崩＋与 surface 三数互证仍逐值相等」，交主代理 repin。升账的唯一合法形态
= 名册 pin FATAL 后的**重钉**（S808 §1B 型扩展），须随新库声明同批、带分母联动证据，禁为转绿而升。

## §6 复跑命令簿（统一卫生前缀；cwd＝仓根；解释器 `../ChatBot_Runtime/venv/Scripts/python.exe`）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0
export PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s811-pyc"
D=.superpowers/sdd/2026-09-24-central-dispatch
# R1 尺本体（直跑不崩＋真实读数）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s811-cross-edge-ruler.py        # rc=0，VERDICT GREEN
# R2 注毒台（三发＋对照＋末发复核，全 %TEMP%）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s811-2-poison.py               # ALL-PASS rc=0
# R3 板侧参照实现（judge 吃捕获＋真 surface 三数）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s811-cross-edge-ruler.py > "$TEMP/s811-work/live.out"
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s811-cross-edge-ruler.py --judge "$TEMP/s811-work/live.out" \
    --rc 0 --surface-edges 261 --surface-total 1344 --surface-unowned 588               # CELL: YES
# R4 名册 pin 单独重放（P3 手工形）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s811-cross-edge-ruler.py \
    --tax "$(cygpath -w "$TEMP")/s811-poison/board_taxonomy.poison.py"                  # rc=2，stderr 三行，stdout 空
# R5 三源互证对照（同源两把尺，只读）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s0-main-lib-api-surface.py --check   # 261／1344／495／588
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s759-severance.py                    # stmt_edges=261
```

## §7 边界与挂账（诚实面）

1. **不造第二真身**：认领/派生全转调工厂原语；本尺**新增**的只有「守恒桶＋洞计数＋棘轮比较＋名册集合 pin」这一层判据，
   edges/total/unattributed 与 surface 逐值同源并由板侧互证执法（不同源即 NO）；断开度分子/分母仍归 s759，本尺一个都不重算。
2. **worktree 口径的并发窗易碎性**：宇宙含未跟踪件，并发窗内他席增删 `plugins/**.py` 会移动 ratchet_now ⇒
   本格可能因**他人落码**瞬时 RED——这是棘轮的设计语义（升即红、红必可归因），不是尺病；但**接板后首跑若 RED，
   先 diff 洞件清单与上窗读数再定性**（洞件逐枚点名输出即为此准备）。
3. **api-surface 现与钉册不符**（§0：在盘 `2ad887c5…` ≠ 册 `d7ef7694…`）：S810 在验、未 repin 前，板侧 `run("surface")`
   返 99 ⇒ 本格三源互证拿不到 surface 数 ⇒ 连坐落 NO。属**在册未执法→已执法**的正常联动，接线时点须向主代理点名。
4. 格判翻 YES 的口径裁定权在她：本尺两腿（可枚举∧棘轮）今日全过 ⇒ 派生 YES，取代手写 PART；若她裁定「无主 588 在场
   本格就该 NO」，改法是判据加第三腿 `unattributed==0`——那是**判据改道**不是本席可自加的条件，本件按简报口径实现。
5. 幻影目标边今值 0（S808 同数复证）；该量在本尺 `S811-HOLES` 行显式同屏，若他日非 0 会进现算值列，不并进棘轮（它是"看得见"的账）。
6. 未做／移交：常驻 pytest 门（把 §5 判定块与 `--judge` 同形性钉成回归锁）未写——本格属审计板面不属仓内测试面，
   且本席写面只有两把尺＋本件；建议主代理接线时顺手立一把 `tests/` 锁（喂 §4 同款假账断言不绿）。

**规则 11 账**：本席工具结果与所读件内未遇要求执行动作的祈使句载荷（命中 0）；读到的注入处置纪律文字一律当规范数据遵守。
红线自查：未 commit／未 push／未 git init 真仓真库／未搬生产文件／未动 `.env`／未拨闸／未重启杀进程／未跑全量套件。

## §8 交卷 sha256 全文（并发窗复算用）

```
probes/s811-cross-edge-ruler.py  17,824 B
7b271d9c13340c327603ee7640a07d3647b78619a89e94d2f6e426ccdba7c806
probes/s811-2-poison.py           9,094 B
2ea476128b8ccacbef73ed62285da223ad1264b31a23f26b199ec1053d48f9e9
```
（注：交卷前本件 §4 表与 §5 片段仍可能随复跑刷新——以上 sha 为「注毒 ALL-PASS 后、报告成文时」的重录基准。）

done: yes
