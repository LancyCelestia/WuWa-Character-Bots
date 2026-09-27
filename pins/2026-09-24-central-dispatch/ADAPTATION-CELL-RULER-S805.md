# S805「统筹适配」格真判化——一把逐库三腿尺（含零测自锁与验牙台）

Status: SUBMITTED ｜ 席位 S805 ｜ 批次 250926A-B2 ｜ 写面：`probes/s805-*.py` ＋ 本件
开窗时刻（UTC）：2026-09-26T08:1xZ ｜ 收窗时刻：2026-09-26T08:4xZ（终跑 08:38:25Z）
锚：HEAD `a5226ec`（跑前＝跑后）｜声明源 `board_taxonomy.py` sha256[:16] `a76235f025024d69`

**一句话总裁决**：审计板「统筹适配」格从今天起**有真判据**——一把逐库三腿尺（`probes/s805-adaptation-cell.py`，
11–12 秒跑完十库，两次实跑 11.05s／12.43s）现算今值＝**腿① 10/10 绿、腿② 0/10、腿③ 0/10 ⇒ 整格 YES 0/10 座 ⇒ `VERDICT: NOT-ADAPTED`**。
旧板那一格是手写 `PART`（只数 `api-surface.json` 存不存在，10/10 在场就永远 PART，永不追问"这份面账现在还对不对、
里面被跨库消费的符号有没有一个是声明过的、跨库引用有没有一条走依赖声明"）。**本席没有为了凑绿放宽任何判据**：
腿③今天结构性不可能绿（十库在册跨库依赖声明＝**0 枚**、主仓直连跨库语句边＝**261 条**），照实逐库判 NO。
与既有尺同源互证**三数全对上**（severance `stmt_edges=261` ＝ api-surface「跨库 import 边合计＝261」＝本尺所用；
severance `sym_edges=399` ＝ 本尺 Σ直连 399；api-surface「提供方符号条目合计＝298」＝ 本尺 Σ条目 298），
`XCHECK status=OK`，不平即退 3、读数作废。
**本席自曝一枚自造的假绿通道**：腿①首版把盘上 `api-surface.json` **预拷进 %TEMP% 骨架**再生成 ⇒
生成器哪怕哑掉（什么都不写）也会被逐库读出盘上旧账、腿①恒绿＝拿盘上文件和它自己比。
验牙台 T3 一发打穿，已根修（骨架改为**空目录**，现算面只能由生成器产出）——见 §伍-5 与 §柒。

成品三件（全在盘、全实跑绿）：

| 件 | 作用 | sha256[:16]（现算） |
|---|---|---|
| `probes/s805-adaptation-cell.py` | 主尺：逐库三腿 ⇒ `CELL/ADAPT/XCHECK/VERDICT` 机读行 | `f14f586d6ce16d36` |
| `probes/s805-teeth.py` | 验牙台：T1–T6 七发，全部打在 `%TEMP%` 副本／合成夹具 | `0d7753f184054d92` |
| `probes/s805-unverifiable-breakdown.py` | 明细尺：把腿②的两类红拆到六种**可行动**子形态并给样本 | `c4c4b91f2d4fe985` |

板件写面归主代理：**本席一个字没改 `probes/s0-main-goal-audit.py`**（只交可粘贴接线片段，§陆）。
仓外真库根 `ChatBot_Libs` 全程只读（本尺所有写盘只落 `%TEMP%`）；零 git 写、零配置改动、零重启、未跑全量套件。

---

## §〇 指纹与「我吃的输入是谁」（复合量具必须交底）

本尺是**复合量具**：三腿里有两条建在两把既有尺的产物上。审计板那套 C6 钉册钉得到本尺，**钉不到本尺的输入**，
故本尺把输入 sha 打成机读行 `GAUGES`，并给一条可选的输入 sha 腿 `--expect-surface-sha/--expect-severance-sha`。

08:3xZ 现算（板是移动靶：本席观察到的 `s0-main-goal-audit.py` sha256[:16]＝`2200e19b509219f0`，钉册 14 枚）：

| 输入件 | 盘上 sha[:16] | 板钉 sha[:16] | 相符 |
|---|---|---|---|
| `s0-main-lib-api-surface.py` | `2ad887c56b3f1cda` | `d7ef7694a394ada1` | ❌ **不符** |
| `s0-main-lib-factory.py` | `e952b0914000ae0b` | `e952b0914000ae0b` | ✅ |
| `s759-severance.py` | `845373dcaf1438fde2751645` | `845373dcaf1438fde2751645` | ✅ |

⇒ **如实报备两件事**：① api-surface 盘上版与钉册不符（S785 消盲改件的未重录账，主代理 §〇-2 已点名），
板壳调它会拿 rc=99 ⇒ 板的 surface 格今天本就不可判；本尺绕过钉册直接调它，所以**本尺读数建立在
未重录的那版生成器上**，接线时 she 必须一并裁这条（要么 repin、要么给本尺传 `--expect-surface-sha`）。
② 主尺件不在钉册里——接线时 `PINNED_GAUGES` 必须加它，否则 `run("adapt")` 一上来就 rc=99、该格恒 NO。

面账新鲜度（本尺现算，非转述）：十份盘上 `api-surface.json` 生成时刻 `2026-09-26T07:00:55Z`、
内嵌 `repo_head=a5226ec`＝现 HEAD、声明源 sha＝现值 ⇒ 腿①的「与现算逐键相等」**今值 10/10 成立**。
（S744 当时值：面账冻结在 `ae096fc`、对现树 +4 条漂移；那条漂移账已被 07:00:55Z 这次重刷取代。）

---

## §一 判据口径（写死在尺里，读表前先读这节）

**逐库三腿，全绿该库才 YES；全库 YES 整格才 YES**（板格吃 `cells_yes`）。

| 腿 | 判什么（一句） | 机械判据 | 取不到数时 |
|---|---|---|---|
| ① | 接口面文件存在且能被 `--check` 通过 | `api-surface.json` 在盘＋可解析＋与权威生成器**现算产物**去掉 `generated_at_utc` 后**逐键相等** | 缺件／读不出／无 `symbols` 键 ⇒ 该库 leg1=NO（理由码随行）；**一座都测不到 ⇒ FATAL rc=2** |
| ② | 该库对外只暴露**声明过**的符号（AST 现算） | 该库每个「被跨库消费的 模块:符号」，提供方模块须以**字面量 `__all__`** 声明它 | 模块不在盘／语法炸／星号转出／PEP562 惰性／`__all__` 非字面量／名字不在该文件 ⇒ 一律 `unverifiable`＝红 |
| ③ | 跨库引用只走依赖声明、零直连 import | 该库作为消费方的跨库直连边（符号出现形）＝**0**，且用到的每个提供方都在册声明（`pyproject.toml` 的 `botlib-<slug>` ∪ `manifest.depends`；判据**直接调 `s759-severance.py::declared_pairs`**，零副本） | 直连边数取不到 ⇒ 整尺 FATAL（互证腿必查 `stmt/sym` 两数） |

三件实现纪律（都不让步）：

1. **不复制判据**：归属派生复用库工厂原语（`parse_taxonomy`／`parse_libs`／`longest_prefix_owner`／
   `git_tracked/untracked`）；现算面复用 api-surface 生成器本体（`%TEMP` 空骨架＋写档）；声明通道复用
   severance 的 `declared_pairs`。⇒ 本尺**不是第四把认领尺**，也不建第二份接口面真身。
2. **抓不到＝NO，不＝没问题**：任一腿数字拿不到 ⇒ 该腿 NO 并带理由码；整机零测 ⇒ 退 2（见下条）。
3. 🔴 **零测即 FATAL 自锁**：库根不在场／库根下零座／声明源派生为 0／名册形状违规／成员宇宙为 0／
   生成器对该座吐不出现算面／输入 sha 与期望不符 ⇒ **退 2、stdout 零字节、stderr 逐字写
   `… ⇒ 量具失明，别把没扫到报成没问题`**——输出里**不存在裁决词**（YES/NO/PART 连 `VERDICT` 行都不出现）。

**退出码语义**：`0`＝测到了（`VERDICT: ADAPTED|PARTIAL-ADAPTED|NOT-ADAPTED` 由逐库 cell 派生）；
`2`＝零测失明（不出裁决）；`3`＝与既有尺互证不平 ⇒ 读数作废（既不是绿也不是可信的红）。

**「测到零」≠「没测到」，但本尺对前者也不放行**：某库无任何跨库被消费面（腿②）或全无跨库引用（腿③）
⇒ 判 `NO` ＋ 理由码 `leg2:vacuous-zero-consumed`／`leg3:vacuous-no-cross-usage`。
这是**刻意的 fail-closed**，代价写进 §捌 待裁（真叶子库会被永久挡在 YES 之外），不偷偷放行。

---

## §二 真实十库今值（08:3xZ 现算，逐库点名；仓外真库根只读）

| 库 | ① 面账＝现算 | ② 只暴露声明符号 | ③ 零直连 | 整库 | 被跨库消费条目 | declared | 未声明 | 不可核 | 直连出边（符号形） | 用到提供方 | 在册声明 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| B01 ingress-protocol | ✅ YES | ❌ NO | ❌ NO | **NO** | 11 | 0 | 8 | 3 | 6 | 1 | 0 |
| B02 routing-dispatch | ✅ YES | ❌ NO | ❌ NO | **NO** | 27 | 17 | 10 | 0 | 52 | 7 | 0 |
| B03 persona-chat-safety | ✅ YES | ❌ NO | ❌ NO | **NO** | 30 | 5 | 25 | 0 | 82 | 8 | 0 |
| B04 memory-knowledge-notes | ✅ YES | ❌ NO | ❌ NO | **NO** | 30 | 9 | 21 | 0 | 16 | 4 | 0 |
| B05 external-data-services | ✅ YES | ❌ NO | ❌ NO | **NO** | 54 | 7 | 43 | 4 | 31 | 5 | 0 |
| B06 media-entertainment | ✅ YES | ❌ NO | ❌ NO | **NO** | 59 | 15 | 44 | 0 | 77 | 7 | 0 |
| B07 schedule-automation | ✅ YES | ❌ NO | ❌ NO | **NO** | 8 | 3 | 3 | 2 | 28 | 7 | 0 |
| B08 render-outbound | ✅ YES | ❌ NO | ❌ NO | **NO** | 49 | 12 | 22 | 15 | 14 | 4 | 0 |
| B09 control-plane-observability | ✅ YES | ❌ NO | ❌ NO | **NO** | 28 | 1 | 18 | 9 | 81 | 7 | 0 |
| B10 engineering-governance | ✅ YES | ❌ NO | ❌ NO | **NO** | 2 | 1 | 1 | 0 | 12 | 2 | 0 |
| **合计（当时值，现算非手抄）** | **10/10** | **0/10** | **0/10** | **0/10** | **298** | **70** | **195** | **33** | **399** | — | **0** |

尺的机读尾行（本次实跑原文）：

```
ADAPT libs_measured=10 disk_dirs=10 git_dirs=10 cells_yes=0 leg1_ok=10 leg2_ok=0 leg3_ok=0
ADAPT detail surface_symbols=298 declared=70 undeclared=195 unverifiable=33 direct_out_total=399 declared_pairs=0 stmt_edges=261
ADAPT leg1 agree=10 drift=0 absent=0 (tool 一致=10 漂移=0 缺失=0)
GAUGES api-surface=2ad887c5… severance=845373dc… factory=e952b091…
XCHECK status=OK surface_stmt=261 severance_stmt=261 severance_sym=399 s805_sym=399 severance_rc=0 notes=-
VERDICT: NOT-ADAPTED
```

**读法三句**：① 腿①今天真是全绿（面账 07:00:55Z 重刷过、对现树零漂移）⇒ 旧板那句「10/10 座落 json」
在**这一条**上没说错，但它把「在场」当「可校验」，本尺把后者做成了判据；② 腿②**十座全红**，
且红得不一样：最好的 B02 也只剩 10 条未声明（17/27 命中），最差的 B01 是 **0/11 全裸**；
③ 腿③十座全红且**同因**：在册声明 0 枚、直连 261 条语句边（符号形 399）——见 §肆。

---

## §三 腿②那 228 枚红长什么样（明细尺现算；每类一句修法）

`probes/s805-unverifiable-breakdown.py` 08:3xZ 实跑（121 枚提供方模块全扫）：

| 子形态 | 枚数 | 是什么 | 要它变绿得做什么 |
|---|---:|---|---|
| `declared` | 70 | 在字面量 `__all__` 里 | —— 已合格 |
| `undeclared:bound` | 192 | 模块确有这个顶层绑定，但没进 `__all__` | 把它写进该模块 `__all__`（逐库可批量，B06 44／B05 43／B03 25 为头三户） |
| `undeclared:submodule` | 3 | 从包 `__init__` 直接进子模块（包没声明） | 包 `__init__` 补 `__all__` 或改指真身模块 |
| `unverifiable:star-reexport` | 14 | 垫片 `from 真身 import *`（成员集合静态不可核） | 垫片把转出名单写成字面量 |
| `unverifiable:lazy-getattr` | 9 | PEP 562 `__getattr__` 惰性转出（真身＝`llm/__init__.py` 一族） | 静态补一份 `__all__`（惰性解析照旧） |
| `unverifiable:absent-or-alias` | 10 | 名字**不在该文件任何作用域** | 先分家：一半是上游符号键取 asname（§捌-Q3），其余要人工点名 |

提供方模块形态分布（同一把尺现算）：`__all__` 字面量在场 **32/121**、非字面量 **12**、完全没写 **77**。
⇒ 「补声明」这条路是**有界活**（121 个文件里补 89 个），不是黑洞；本席**没做**（禁改生产）。

---

## §肆 腿③为什么今天不可能绿（不放宽判据的那一条）

现算三条硬数（本尺＋severance 双尺同形）：

- 在册跨库依赖声明 **0 枚**（`declared_pairs=0`；十库 `pyproject.toml` 与 `workspace-lib.manifest.json`
  两通道各扫一遍，S744 的五通道复算亦 9/9 词 0 命中）；
- 主仓仍在直连的跨库边 **语句形 261 条／符号形 399 条**；
- 于是「用到的每个提供方都在册声明」这条**对十座库都成立不了**——`undeclared-providers` 逐库＝
  1／7／8／4／5／7／7／4／7／2（＝该库实际直连进去的提供方数）。

⇒ **格判 NO 是事实，不是判据太严**。要翻绿必须先有 pins 声明面（S612 M0 是前置）＋把边真断掉，
两件事都在她手里；本席既没建 pins（禁建）、也没改判据（禁放宽）。

---

## §伍 验牙账（七发全 PASS ＋ 两发注毒；全部 `%TEMP%`，真件真库零写）

```
$ <venv-py> -B probes/s805-teeth.py
[PASS] T1 库根指空⇒FATAL :: 零测通道形状全部正确
[PASS] T1b 库根不在场⇒FATAL :: 零测通道形状全部正确
[PASS] T2 派生为 0⇒FATAL :: 零测通道形状全部正确
[PASS] T3 生成器吐不出面⇒FATAL :: 零测通道形状全部正确
[PASS] T4 面账缺失⇒该库判 NO（禁读成没事） :: rc=0；受害库 control-plane-observability 行＝CELL B09 … leg1=NO … reasons=leg1:file-missing
[PASS] T5 腿②判据正/负控（含绿通道可达） :: 八类形态全部按名命中，且 declared 分支可达（腿②非写死红）
[PASS] T6 全绿夹具⇒能报 YES 且互证有牙 :: rc=3：cells_yes=10/VERDICT=ADAPTED，同时 XCHECK 抓住哑具供数与 severance 399 不平
TEETH ran=7 pass=7 fail=0
```

逐发交代（哪些是「有牙」、哪些是「不是摆设」）：

1. **T1／T1b／T2／T3＝零测自锁的四条不同入口**（空库根／库根不在场／声明源掏空致派生为 0／
   生成器换哑具）。每发断言四件事：`rc==2` ∧ **stdout 零字节** ∧ stderr 含原句
   「别把没扫到报成没问题」∧ stdout+stderr 里 `YES|NO|PART` **零命中**（连 `VERDICT` 字样都不许出现）。
   实跑原文（手敲一发，非转述）：
   `FATAL: 库根下零座（C:\Users\…\Temp\s805-empty） ⇒ 量具失明，别把没扫到报成没问题`｜stdout 0 字节｜RC=2。
2. **T4＝「抓不到＝NO」有牙**：`%TEMP%` 副本里抽掉一座库的 `api-surface.json` ⇒ 该库 `leg1=NO`＋
   理由码 `leg1:file-missing`、`leg1_ok=9`、`cells_yes=0`，而尺**不崩也不放行**（rc=0，红得可归因）。
3. **T5＝腿②不是写死的红**：`%TEMP%` 合成七种模块形态（含包子模块、PEP562、星号、非字面量 `__all__`、
   嵌套私有件、语法炸、缺件），断言每一类各归其名，且 `declared` 分支可达 ⇒ 判据会绿、只是现在没东西可绿。
4. **T6＝本尺既能报 YES、又不会因换生成器被凭空放行**（一发双牙）：合成夹具做到三腿全绿 ⇒
   `cells_yes=10`＋`VERDICT: ADAPTED`（证明尺不是永久 NO 的摆设）；**同时**互证腿必须炸——
   实际 `rc=3`、`XCHECK notes=sym:399!=0`（哑具供的符号形 0 与 severance 的 399 不平）。
5. **T3 打穿的正是本席自己造的假绿通道**（记在 §柒，不抹）。
6. 加发注毒（输入 sha 腿）：`--expect-surface-sha deadbeef` ⇒ `RC=2`、stdout 0 字节、无裁决词。

---

## §陆 可粘贴接线片段（板件写面归主代理——本席未动板）

改四处。**第 4 处必须与前三处同批**，否则 `run("adapt")` 因不在钉册而 rc=99、该格恒 NO。

1）`SOURCES` 里加一行（放在 `"surface"` 之后即可）：

```python
    "adapt": "s805-adaptation-cell.py",   # 统筹适配（真判）：逐库三腿——面账＝现算 ∧ 只暴露声明过的符号 ∧ 零直连
```

2）取数区（`rc_ou, out_ou = run("outside", [])` 之后）：

```python
    rc_ad, out_ad = run("adapt", LIBARG)
    ad_measured = num(grab(out_ad, r"ADAPT libs_measured=(\d+)"))
    ad_gitdirs = num(grab(out_ad, r"git_dirs=(\d+)"))
    ad_yes = num(grab(out_ad, r"cells_yes=(\d+)"))
    ad_l1, ad_l2, ad_l3 = (num(grab(out_ad, r"leg1_ok=(\d+)")), num(grab(out_ad, r"leg2_ok=(\d+)")),
                           num(grab(out_ad, r"leg3_ok=(\d+)")))
    ad_ver = grab(out_ad, r"VERDICT: ([\w-]+)")
    ad_stmt = grab(out_ad, r"stmt_edges=(\d+)")
    ad_xc = "FAILED" in grab(out_ad, r"XCHECK status=(\w+)")
    # 判 YES 的五把尺同时成立：rc=0 ∧ 文案 ADAPTED ∧ 四个数抓到 ∧ 测座＝板数出的座数>0
    # ∧ 三腿各自都全座绿且 YES＝座数 ∧ 互证未 FAILED ∧ surface 格与本尺的语句边数逐值相等
    adapt_j = cell(rc_ad, ad_ver, "ADAPTED", ad_measured, ad_yes, ad_l1, ad_l2, ad_l3) \
        if (built > 0 and ad_measured == built and ad_gitdirs == built
            and (ad_l1, ad_l2, ad_l3, ad_yes) == (built, built, built, built)
            and not ad_xc and ad_stmt == cross_edges) else "NO"
```

3）表里把这一行整行替换（原第 284 行那格的手写 `{'PART' if have_surface else 'NO'}` 作废）：

```python
         f"| 统筹适配 | 逐库三腿全绿（①`api-surface.json` 在盘**且＝生成器现算**（忽略生成时刻逐键等）"
         f"②被跨库消费的符号全在提供方字面量 `__all__` 里 ③该库零直连跨库 import **且**用到的提供方都在册声明）"
         f"＋测座＝本板数出的座数>0＋与 surface 格语句边互证 | "
         f"三腿各绿 {ad_l1}/{ad_l2}/{ad_l3} 座（共测 {ad_measured} 座）／YES {ad_yes} 座／语句边 {ad_stmt}（`{ad_ver}`）"
         f"；盘上落 `api-surface.json` {have_surface}/{built} 座 | {adapt_j} |",
```

4）`PINNED_GAUGES` 加本尺（走 `--repin --reason`，别手改块）：

```
python -B probes/s0-main-goal-audit.py --repin --reason "S805 统筹适配格真判尺接入（新增 adapt 量具；api-surface 盘上版仍与册不符，一并裁）"
```

**接线时必带的两句提醒**（本席现算，别当散文）：
① 本尺十几次秒里**跑了两遍生成器＋一遍 severance**（板已跑过 surface/severance 各一遍 ⇒ 全板耗时约 +25 秒），
板的 `run()` 有 `timeout=1800`，够；② `built` 数 `.git` 目录、本尺 `libs_measured` 数**目录**，
两者今天同为 10；一旦有人建了未 `git init` 的新座，该格会因 `ad_gitdirs != built` 落 NO——**这是刻意的**。

---

## §柒 本席自曝账（就地更正，不抹）

1. **腿①首版自造假绿通道**（最重的一条）：骨架里**预拷**盘上 `api-surface.json` 再让生成器写档 ⇒
   生成器什么都不写时，`fresh` 仍读到盘上旧账 ⇒ 逐库「一致」＝拿文件跟自己和，
   连「换掉整把生成器」都能被糊过去。首发 T3 直接 FAIL 才暴露 ⇒ 改为**空骨架**（现算面只能由生成器产出），
   改后腿①仍 10/10（说明今天的绿是真的，不是这条通道造出来的）。教训与本窗 drift-checker 那条同源：
   **写完必须当场注毒验"它会红"**，不然锁只是注释。
2. **`REPO` 层数写错一次**：验牙台把主仓算成 `.superpowers`（`HERE.parents[2]`，应 `parents[3]`），
   首发即被自家"声明源不在场"自锁挡下（rc=2、stderr 带原句）——锁顺手救了自己一次，记功也记过。
3. **T5 首版夹具期望值写错**：拿 `__all__ = [n for n in ("a",)]` ＋ `a = 1` 期望 `unverifiable:dynamic-all`，
   而尺判 `undeclared:bound`——**尺对、夹具错**（模块级确有绑定时更具体的修法提示优先）。
   改夹具并把这条**优先级写成断言**（新增 `dyn2.py`），不放宽尺。
4. **静态门首笔不干净**：三件 ruff 8 错（`subprocess.run` 无 `check=`、`__slots__` 未排序、f-string 无占位、
   未用变量）＋mypy 3 错（AST `expr` 收窄）。全修完：`ruff check --no-cache` → `All checks passed!`、
   `mypy` → `Success: no issues found in 3 source files`。
5. **中途一次 Edit 把两行 f-string 打坏**（`invalid character '（'`）——按本窗纪律**改尺件必自证直跑不崩**：
   当场 `ast.parse` 复算定位到行、修好后重跑主尺＋验牙台全绿，未留下半死件。

---

## §捌 诚实边界与待裁（本席不替她裁）

- **Q1（待裁）** 真叶子库会被 §一的 vacuous fail-closed **永久挡在 YES 外**（无跨库被消费面＝腿②红）。
  今天不咬人（十库都有跨库账），但拆库后会出现。放行需要她一句话；本席选的是不偷偷放宽。
- **Q2（口径陷阱，两把尺同病）** 「零直连」是在**当前主仓成员宇宙**上量的：B-0 落码、文件物理出库后，
  那些 import 连目标都解析不到 ⇒ 本尺与 severance 的分子/分母都会**因为看不见而变绿**。
  届时必须与「成员宇宙枚数」「库内文件数」同屏读，单看「0」宣布断开完成＝假绿。
- **Q3（上游件的事，本席不改）** `absent-or-alias` 那 10 枚里含**消费方别名**形态：实证一枚
  `plugins/bot_unified_runtime/__init__.py:9926` 处 `build_alert_content_sink as _build_kb_sync_alert_sink`，
  而 api-surface 的符号键取 `asname or name` ⇒ 提供方被记成 `_build_kb_sync_alert_sink`（该文件里根本没这名字）。
  腿②的红方向成立（「从别的库进来了却静态无面」），但**归因名字不对**。修法在 `s0-main-lib-api-surface.py`
  （改用提供方原名），该件写面归 S785/主代理 ⇒ 本席只点名、不硬凑、不改它的数。
- **覆盖面是下界**：本尺的跨库边沿承生成器口径——只数「可解析成仓内件的绝对 `ImportFrom(level==0)`」；
  裸 `import x.y`、相对 import、反射/f-string 模块名、协议边（`submit_active_push`／`CapabilityRequest`）
  一概不进账 ⇒ 腿③的直连数是**下界**（与 S744/S717 同申）。腿②另有 AST 静态不可核那一层，已分家点名。
- **未做**：全量四门禁与真机验收（红线：并发写入窗未关、重启裁决权在她）；15 座名册库口径下本尺只测到
  **盘上真存在的 10 座**（`decls gap` 那五座在库根无目录 ⇒ api-surface 会先 FATAL，本尺随之零测——
  属「缺件」不是「没问题」，与本尺自锁同判）。**没为绿改判据、没代他波修账。**

---

**树卫生（自查）**：本席三件全带 `-B` ＋ `PYTHONPYCACHEPREFIX="$TEMP/s805-pyc"`（bash 侧＝`/tmp/s805-pyc`）跑，源码树与本席写面**零缓存**；开窗期间 `probes/__pycache__/s802-rehearsal.cpython-312.pyc`（16:24 落盘）系并行席位 S802 的产物，非本席所造、本席**未删**（红线：不动他席产物）——留给该门 owner 在安静窗按「先备份 `%TEMP%` 再清」的既有规程处置。
真库根的 `api-surface.json` mtime 全部停在 `2026-09-26T07:00:55Z`（＝本席开窗之前）⇒ 坐实本尺全程只读十库、零写盘。

## §玖 复跑命令（卫生前缀按铁律；全程只读真库根）

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$TEMP/s805-pyc"
PY=/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
D=.superpowers/sdd/2026-09-24-central-dispatch/probes

"$PY" -B $D/s805-adaptation-cell.py                      # 今值：11.05s，rc=0，VERDICT: NOT-ADAPTED
"$PY" -B $D/s805-teeth.py                                # 验牙七发：TEETH ran=7 pass=7 fail=0（rc=0）
"$PY" -B $D/s805-unverifiable-breakdown.py               # 腿②缺口子形态（§三）
"$PY" -m ruff check --no-cache --output-format=concise $D/s805-*.py       # All checks passed!
"$PY" -m mypy --ignore-missing-imports $D/s805-adaptation-cell.py         # Success

# 零测自锁一发（安全、只读）：
mkdir -p "$TEMP/s805-empty" && "$PY" -B $D/s805-adaptation-cell.py --libs "$TEMP/s805-empty"
#   ⇒ RC=2、stdout 0 字节、stderr 末句「别把没扫到报成没问题」、输出无 YES/NO/PART
```

done: yes
