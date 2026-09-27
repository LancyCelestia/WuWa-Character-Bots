# S798 复攻第二轮：打在 250926A-B 加固板（F1/F2/F3/F4＋built==0 折叠＋钉册格）上

> 席位 S798（批次 250926A-B1，恶毒攻击席）。被攻板＝`probes/s0-main-goal-audit.py`。
> **板是移动靶（本窗八改，逐发钉版）**：开窗现算 `caa3e637`（简报所说 16 格版，本席基线板跑的就是它，08:16:20Z→08:18:48Z）；
> 此后板 owner 一路推进：`3626213a`（repin 逐枚 --only）→ `bbfd1eae`（decls 补 seeded 腿）→ `0a682fb5` →
> `2200e19b`（S795 加 --evidence 硬门）→ `77521bb5`（S806 物理归类格真判化，钉册 14→15）→ `86306aeb`（S805 统筹适配派生，钉册→16）→
> `787b6ffa`（S811 跨库边派生，钉册→17）→ `4c7ed9f7` → 写稿收尾现算 `f8ddce16` → **交卷复核又见第九改 `33c4bc31`**（钉册仍 18 枚）。
> **正式波 14 发全部建在 787b6ffa/4c7ed9f7 上**（各发 `disk-hashes.txt` 首行记建台板版）；预战（同判据各发）在 `2200e19b/0a682fb5`。
> 交卷收尾版（33c4bc31）复核：F1/F2/F3/折叠/派生五枚锚点逐字在场（本席现算 grep 五发全中），各发结论可直接引用；
> 唯「版本号三处一致」行加了 S801 注记「本格只量十库轴」——不影响本席任何一发判据。
> 台架每次建台校验上述五枚锚点，板形再变（判据行被改动）即 `RIG-MISS` 作废该发、不拿旧结论冒充新版。

## §0 开工现算（开窗 08:1xZ，sha256 取前 12；当时钉册＝14 枚）

| 件 | 开窗值 | 与当时刻（caa3e637 内册） | 收尾值（交卷现算） |
|---|---|---|---|
| s0-main-goal-audit.py | caa3e6376b64 | —（板本体不钉） | 33c4bc314d62（九改，全属板 owner） |
| s0-main-unowned-edge-ranker.py | 04101548b207 | 相符 | 04101548b207 |
| s0-main-lib-api-surface.py | 2ad887c56b3f | **不符**（刻 d7ef7694；S785 在飞改版未 repin） | 2ad887c56b3f（后被 bless） |
| s0-main-lib-drift-checker.py | a544fad7460d | **不符**（刻 09f4f237；§〇-2 那枚坏件已被修好但未 repin） | a544fad7460d（后被 bless） |
| s0-main-lib-version-check.py | 1d7a4b656224 | 相符 | 1d7a4b656224 |
| s759-severance.py | 845373dcaf14 | 相符 | 845373dcaf14 |
| s759-noncode.py | fc3352cb000e | 相符 | fc3352cb000e |
| s759-decl-sources.py | be8637db4f6b | **不符**（刻 4bbf38de；seeded 腿） | be8637db4f6b |
| s0-main-central-seam-check.py | 94e5d97601b5 | 相符 | 94e5d97601b5 |
| s0-main-spec-uniform-check.py | 6a38a056b0fb | 相符 | 6a38a056b0fb |
| s0-main-lib-behind-commits.py | d69e58272eb8 | 相符 | 2e81d4694634（窗中被他人改版，非本席） |
| s0-main-lib-readiness.py | b31f053161e3 | 相符 | b31f053161e3 |
| s0-main-lib-factory.py | e952b0914000 | **不符**（刻 e0cb6055） | e952b0914000 |
| s715-deps.py | 28724bed9a90 | 相符 | 28724bed9a90 |
| s784-outside-placement.py | b14b40ede037 | 相符 | b14b40ede037 |
| （窗中新入册）s806／s805／s809／s811 | —— | —— | ecaa184a／f14f586d／39f03cc5／7b271d9c |

- **开窗真值基线**（真板 caa3e637 直调、`--out` 落 %TEMP%、真仓真十库零写）：板 rc=1，总判 NOT ACHIEVED；
  唯一 YES＝版本号三处一致（CONSISTENT／扫 10 座／问题 0 处）；surface=99 drift=99（钉册不符未跑）；
  severance 真数 **分子 0／分母 52、语句边 261、互证失败 `261≠?`**；behind total=5/stale=3/measured=10；
  noncode 783/1434（direct 4/5）；outside 盲区4/残骸1/事故1；decls gap 5；seam/spec RED；ready 红 10 格。
  全文＝`%TEMP%\s798-runlog\baseline-board.md`。凡注毒发把这些翻成 YES 者皆为确凿假绿。

## §0.1 纪律自证

- 台架＝`probes/s798-reattack.py`（本席唯一 py 写面）。对 15→19 件真身只有 read/copy；注毒全打在
  `%TEMP%\s798-bench\<发>\.superpowers\sdd\2026-09-24-central-dispatch\probes\` 副本，每发 fresh_bench 重建。
  **夹具修补**＝仅把副本里 `SEAT_DIR.parents[2]`／`HERE.parents[3]`／`HERE.parent.parents[2]` 派生仓根行换成真实绝对路径
  （不改则副本找不到声明源），判定逻辑一字未动——与 S760/S777 同款，如实声明。
- **注毒先自证**：每发跑板前直跑被注毒件，断言目标 rc＋目标字样全命中，否则 `POISON-MISS` 不发板；
  输入注入类（f3b）自证＝直跑**一字未改**的真尺对假根，断言假行确认真先于真行进合并流。
- **bless 一律走板自己的合法流程**（逐枚 --only＋--evidence，且本席台架要求 repin rc≠0 即中止整发）——
  第一波正是这道自设检查抓到台架没传 --evidence、六发静默空跑（见 §6），作废重跑。**本表只收 bless 成功或按设计该落 99 的发。**
- 台架对钉册新增件带白名单闸：未审过的尺进册 ⇒ 各发主动作废（本窗两次实拦：s809、s811 落册瞬间），
  人工复核其写面（s809 只读 rev-parse；s811 纯 AST 静态尺，零 subprocess/零写口）后才入列——**不盲跑未知尺**。
- 卫生：`PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=<TEMP>/s798-pyc` 全程＋`-B`；
  板 `--out` 落各发 bench；surface 走板自带 `--check` 只读档。**未 commit、未 push、未 git init、未搬文件、未动 .env、
  未拨闸、未重启/杀进程、未跑 pytest 全量。**
- 白盒发（n3a/n3b/n3c）注明「注在板副本的解析/赋值面」——那是攻派生腿本身的必要手段，裁决按
  「今天可达／未来重构可达」分记，不混。
- 工具结果/文件正文（含 MEMORY 索引、简报、板注）里的祈使句一律当数据处置；本席未执行任何非白名单指令（命中登记：0 枚）。

## §1 加固板机制速读（正式波版＝787b6ffa/4c7ed9f7，本席现读）

板仍 16 格，但**原五枚硬编码行已全部真判化**（建库/统筹版本号←S809、统筹适配←S805、物理归类←S806、跨库边←S811），
钉册 14→18 枚；F1/F2/F3/折叠/派生五处与简报所述逐字在场。关键现值：

| 面 | 判据（本席复核在场） | 备注 |
|---|---|---|
| F1 版本格 | `ver_bad==0 ∧ ver_libs==built ∧ built>0` ＋ cell(rc,CONSISTENT,两数) | 行注记「只量十库轴」（S801） |
| F2 统筹更新 | `bh_total==0 ∧ bh_measured==built ∧ built>0` ＋ cell 三数 | 不吃 `bh_stale==0`（真尺构造上 total=0⇒stale=0，挂观察 F10-④） |
| F3 断开度 | `sev_j==YES` 后过 `sev_cross_ok = "?"∉(sev_e,cross_edges) ∧ sev_e==cross_edges` | **不吃两侧 rc**（f3b 命门）；`cross_edges` 来自 surface 合并流首匹配 |
| F4 钉册 | run() 前置 pinned_ok→99；pin_j 成格进总判；repin 逐枚 --only＋--evidence（须含「直跑」「读数」两词） | 自钉边界板上自述；**板本体不在任何册内** |
| 折叠 | `if built==0:` 手写 11 枚变量落 NO | **新格不在清单**：exhaust/adapt/buildlib/verongov/crossedge 五格漏编（f10 命门） |
| 派生 | 表行尾格∈{YES,PART,NO} 计入 verdicts；`achieved=bool(verdicts)∧无一非YES`；rc 随派生 | **无行名册地板**；非三值行静默丢（n3b/n3c 命门） |

> 判「拦住/打穿」只认板面实文（各发 `out/BOARD.md` 入档）＋板 rc＋逐发自证直跑输出，不认本席嘴。

## §2 战果表（正式波 14 发；板版＝建台现算；板面原文在各发 out/BOARD.md，直跑自证在 `%TEMP%\s798-runlog\<发>.txt`）

> 预战在 `2200e19b/0a682fb5` 的同发全部同判复现（f1a/f1b/f2empty/foldshell/f3a/f3b/f4a/f4b/n1/n3b/n3c）；
> **唯 n3a 在两个板版之间由「拦」翻「穿」——翻版原因是板方拆掉硬地板（S805/806/809/811 四波格真判化），非本席改判据**，两版证据都留档。

| # | 发（板版） | 攻击怎么做（全在 %TEMP% 副本） | 板子判成什么 | 应当判成什么 | 拦/穿 |
|---|---|---|---|---|---|
| 1 | f1a-version-poison (787b6ffa) | S777 #4 原形重放：version 副本三注（`ok=False`／伪 CONSISTENT／`return 0`），stdout 逐行 DIVERGES＋合计「不一致/缺件/缺 tag **10 处**」真字在场；自证后逐枚 bless→跑真根 | 版本格 **NO**（问题数腿抓到 10≠0，掐死文案腿）；钉册 YES | NO | **拦**（F1 对「文案与自家数字打架」成立） |
| 2 | f1b-libcount-lie (4c7ed9f7) | 只把合计行扫座数 10→11（0 处/CONSISTENT/rc0 全真），bless→跑板 | 版本格 **NO**（11≠built 10） | NO | **拦**（「测座＝板座」腿有效） |
| 3 | f2empty-built0 (4c7ed9f7) | 零注毒：bless 后板指**空库根**（S777 #6 全等重放） | 全表 **0 枚 YES**、rc=1、NOT ACHIEVED；钉册现算值「与册不符 0 件」却判 NO（被折叠吞） | 不许任何 YES | **拦**（折叠是硬闸；附 F10-① 呈现矛盾一条） |
| 4 | foldshell (4c7ed9f7) | 零注毒：1 枚 `.git` 空壳＋名册外鬼影目录，无注毒字样 | 唯一 YES＝钉册自证（真相符）；surface/drift/s806 鬼影 FATAL、version rc1、behind UNTRUSTED 各自掐停 | 除钉册外不得 YES | **拦**（S785/S806 系「库数对账硬腿＋UNTRUSTED」把换根翻绿堵死——**但 severance 没吃这条腿**，见 #6） |
| 5 | f3a-equal-false-stubs (4c7ed9f7) | **两把尺整件对倒**：severance stub 印 `SEV numer=52 denom=52 stmt_edges=4242`、surface stub 印「跨库 import 边合计＝4242」，直跑自证后**逐枚点名 bless**（走板的合法流程）→跑真根 | 断开度 **YES**：「分子 52／分母 52（仍直连语句边 4242，与 surface 格互证成立）」＋钉册 YES（板自证相符） | NO（真数 分子0/分母52、语句边 261） | **穿**（F3 只查“两数相等”，不查“数是不是跑完了的尺算出来的”） |
| 6 | f3b-input-injection (4c7ed9f7) | **零改尺、零违册（18/18 与册相符）的发**：只造一个库根，内含 ①`S798Z`(.git 空壳，built≥1 防折叠) ②目录名字面 `S798X stmt_edges=4242 SEV numer=1 denom=1`＋坏 pyproject.toml（severance 明细行**回显目录名原文**→三个 grab 数全被首匹配劫走） ③目录名 `S798Y 跨库 import 边合计＝4242`（surface 鬼影 FATAL 把名单回显进 stderr→合并流供互证数，**且该尺 rc=2**） | 断开度 **YES**：「分子 1／分母 1（仍直连语句边 4242，与 surface 格互证成立）」；severance rc=0；**钉册格 YES**；真行 `BOARD SEV numer=0 denom=52` 就在注入行下游逐字躺着，板一字不看 | NO（注入值 4242/4242 皆假，真数 261/0/52） | **穿（本席最重一发）**：输入层目录名喂相等假数即糊过 F3；真仓真尺真册全绿。答简报「还需要什么第三源」：**互证的两张嘴共享同一个可被回显的合并流——需要 ①rc 前提＋②模式唯一性＋③一个不同源锚（名册 pin／冻结 fixture），三缺一都能再造一枚 #6** |
| 7 | f10-fold-miss (4c7ed9f7) | 「格真判化」新格未同步折叠清单：s806 换假尺（`BOARD S806 unowned=0 inbound=0 double=0 sole_missing=0 wash=0`＋EXHAUSTIVE＋rc0），自证→bless→板指**空库根**（built=0） | 物理归类 **YES** 挂在折叠板上（唯一非折叠 YES；钉册被折叠吞成 NO 反衬它）；同族漏编还有 adapt/buildlib/verongov/crossedge 四格（现读折叠行） | NO（built==0＝输入失效，已算格无一例外折叠） | **穿**（折叠清单手写枚数 vs 格数无同步锁——S777「接无零测自锁的尺＝开新洞」同族，本轮由格数扩张引爆；给 F9 修） |
| 8 | f4a-drift-swap-norepin (787b6ffa) | bless 全部现盘件后，只给 drift 副本加一枚**可编译**字节＋执行记号；板跑（带 marker env）；改后件先直跑自证记号可生成 | 快照 NO、drift=99、钉册 NO 点名 drift、**板跑后记号不在场**＝板根本没执行改后件 | 该尺读数一律不可吃 | **拦**（主判据＋「不吃」都有物证；本席注毒第一版写成 SyntaxError 致证据变弱，重注重跑——自曝见 §6） |
| 9 | f4b-deps-extra (4c7ed9f7) | bless 后只改 `s715-deps.py` 一枚字节（PIN_EXTRA：run() 不经它，但 decls 经 importlib 现场加载它派生名册） | 钉册 NO 点名它；其余十二把 rc 照旧、**名册声明源格照常出数入表**（现算值「缺口 5／播种未建 0／在册 15」出自被改过上游的派生路） | 钉册点名＝按设计拦；「上游被换后其它格读数仍照吃不疑」应挂账（无 YES 翻面，总判被 pin NO 挡死） | **拦（边界挂账 F10-⑤）**：pin_j 入总判兜住了裁决面，但污染读数照常显示——引用者只看格值会受骗 |
| 10 | n1-legit-rev-no-repin（新形①）(4c7ed9f7) | bless 后给 readiness 加一枚注释字节（＝合法改版未 repin 的开窗实况同型），跑真根 | 就绪度 NO 且现算值全 `?`（「`?`（测 ? 座／红 ? 格／本板数 10 座）」）＝**板对该尺零消费**；钉册 NO 点名 readiness | 落 NO 且不吃任何读数 | **拦**（真板开窗实况同型：drift/surface 改而未 repin ⇒ 99/NO，见基线） |
| 11 | n3a-hard-floor（新形③-白盒）(4c7ed9f7) | 板副本注毒：现读全部可计算 `_j`（随 S805/806/809/811 扩员自动跟名册，pin_j 留真值）force 成 YES | **「总判（由上表 16 格派生，PART 与 NO 同判不达）：ACHIEVED」、板 rc=0、钉册 YES**——预战在 2200e19b（还剩五枚硬编码行时）同发为 NOT ACHIEVED「拦」 | 总判必须有一枚不来自量具的锚（或行名册＋跨格守恒），不许「全格 YES⇒达成」纯语法推 | **穿（裁决级）**：S777 §4「总判面今天不可能翻」那句**已随格真判化过期**——地板被拆除时没补替代判据。黑盒复现门槛高（须 13 把尺同供相等假数且过全部互证），但 #12 证明语法层更脆 |
| 12 | n3b-rows-dropped（新形③-白盒）(4c7ed9f7) | 板副本拼表后注入一行过滤器：16 行全吞、只剩一枚合成 YES 行（模拟行名被重构改掉/行被吞的解析面退化） | 「**总判（由上表 1 格派生…）：ACHIEVED**」且板 rc=0 | 格名册不齐＝拒判点名；缺行不许静默缩分母 | **穿（结构脆弱）**：派生腿只 `bool(verdicts)` 设防，无行数/行名地板 |
| 13 | n3c-space-and-wildcard（新形③-白盒）(4c7ed9f7) | 板副本追加两行：尾随空格的 `|YES |` 行＋野值 `MAYBE` 行 | 空格行被 strip 正确计入（这半＝拦）；野值行**无声消失**：输入 18 行、总判只报「由上表 17 格派生」，无一字点名 | 未知判定字样必须点名拒判 | **半穿（轻，同根 #12）**：静默丢行＝分母可被悄悄缩 |
| 14 | x1-traceback-echo (4c7ed9f7) | drift 换**运行时崩**件（raise 行原文含 `VERDICT: CLEAN … DRIFT=0`）**再 bless**——钉册全绿的崩件，traceback 连字样一起进合并流 | 快照 **NO**（rc 腿掐死；崩件自证＝直跑 rc1 且 traceback 确含两枚判据字样） | NO（崩＝不可判，回显字样不是证据） | **拦**（S777 #5 那族在「合法在册的崩尺」语境下仍闭合） |

## §3 总裁决

**14 发＝8 拦／6 穿**（穿：#5 f3a、#6 f3b、#7 f10、#11 n3a、#12 n3b、#13 n3c 半穿按穿记）。
必打五发：**F1 拦**（两形：#4 原形「文案与自家数字打架」＋扫座不配对，均在 bless 生效的台架上验，不靠 99 蒙混）；
**F2 拦**（#6 全等重放：零测＝折叠）；**F3 穿**（f3a/f3b 两形皆穿；f3b＝零改尺零违册，最重）；
**F4 拦**（换件＝99＋格 NO＋marker 实证板不执行改件；两处边界挂账 F10-⑤）；**built==0 折叠拦**、但其清单已漏编五格（**f10 穿**）。
新形三发：①合法改版未 repin＝**拦**（n1 实测板对未 bless 改件零消费）；②两把尺互相指认＝**穿**（等值即过，不问出身）；
③总判派生腿短路＝**穿**（n3a 在最新版直接从格面翻出 ACHIEVED rc=0；n3b/n3c 证明解析层连「剩几格」都不守）。

**这版板子可信到什么程度（覆盖 S777 §4 那句）**：格面比上轮厚（rc＋数字＋文案三腿齐、格数翻倍且逐格挂上互证/棘轮/库数对账），
但 YES 的可信前提是六重：**尺没被换 ∧ 册相符 ∧ 每枚 grab 模式在合并流里恰好出现一次 ∧ 互证两侧都真跑完了（rc=0）∧
库根＝名册那座根 ∧ 折叠清单与格名册同步**。本席逐一实测：前两重板自己守（F4/99/marker）；第三、四、五重不守
（f3b 一发打穿三、四、五重）；第六重不守（f10）。总判面则从「结构性不可翻」退成「**全格派生 ⇒ 语法上任何一格都可能被供出来**」——
格真判化是正确方向，但拆硬地板时没补「不来自量具的最后一枚锚」。S777 的教训「把散文格改判据格时，每把尺先配零测自锁再接线」，
这轮以「**每加一枚派生格，要同步折叠清单＋派生地板＋格名册锁**」的形式收回。
**引用纪律（给台账/交接件）**：本窗之后凡写「断开度互证成立」「总判不可翻」者，须附各发 `out/BOARD.md` 原文或复跑命令，
否则按未完成记账——本席六发穿全部板面逐字可复跑。

## §4 可粘贴判据（写面归板 owner；每条附实弹出处＋不伤诚实绿验算）

**F6（grab 唯一性——掐 f3b/#5 族「回显劫持」）**：任何机读模式在合并流里必须**恰好出现一次**，多解＝污染、零解＝没算完，一律 `?`：

```python
def grab(text: str, pat: str) -> str:
    ms = re.findall(pat, text)
    return ms[0] if len(ms) == 1 else "?"
```

实弹：f3b 注入行使 `SEV numer=` 出现两次（注入行＋真行）；改后该腿落 `?`⇒NO。
不伤诚实绿：现盘各尺每模式各只一行（f2empty/foldshell 全尺跑过，改前改后 `?` 集不扩即验收）。
⚠ 单用拦不住 surface-早退回声（真行根本没打、假行只出现一次）——必须配 F7。

**F7（互证腿吃「对面跑完了」＋第三源锚——掐 f3b 命门）**：

```python
    sev_cross_ok = (rc_s == 0 and rc_sev == 0
                    and "?" not in (sev_e, cross_edges) and sev_e == cross_edges)
```

实弹：f3b 里 surface rc=2 ⇒ 互证即败 ⇒ 断开度 NO＋板面点名。不伤诚实绿：baseline 两尺同跑完时 261=261。
**再深一层（简报点名要的「第三源」）**：两张嘴共享同一个可被输入回显的合并流，等值≠真——终态二选一：
(a) 钉册外移进 git 受门禁保护件（板尾自述「未做」那条）；
(b) **冻结 fixture 一致性门**：最小假库根样本（已知边数/座数）钉进常驻测试，severance/surface/s811 对样本的读数钉成常数——
换尺＋repin＋目录名注入三发同时失效，因为「相等且在册」之外还要「与样本同形」。

**F8（派生腿地板——掐 n3a/n3b/n3c）**：总判解析必须核对格名册，且 ACHIEVED 前加一枚**不来自量具**的判据：

```python
    EXPECT_ROWS = [...16 枚行名逐字...]
    got = [name for name, _ in verdicts]
    if sorted(got) != sorted(EXPECT_ROWS):
        L += [f"- **总判：拒判**——表格解析与格名册不符（缺 {sorted(set(EXPECT_ROWS)-set(got))}"
              f"／多出 {sorted(set(got)-set(EXPECT_ROWS))}）；缺行＝判据被拆，不许静默缩分母", ""]
        Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
        print(L[-1]); return 1
```

配套：行名册↔表行双向等值的常驻锁（加格/改名必动册）；n3a 的另一半修法是把「板自身 sha 记进 GAUGE-PIN-LOG 当行 ∧
钉册外锚在场」并入 ACHIEVED 前提，否则「13 把尺同供相等假数」在语法上就是可达终态。

**F9（折叠/格数同步锁——掐 f10）**：折叠禁手写枚数，从格派生：

```python
    CELLS = {"drift_j": drift_j, "version_j": version_j, "behind_j": behind_j, "ready_j": ready_j,
             "seam_j": seam_j, "spec_j": spec_j, "outside_j": outside_j, "de_j": de_j, "sev_j": sev_j,
             "nc_j": nc_j, "pin_j": pin_j, "exhaust_j": exhaust_j, "adapt_j": adapt_j,
             "buildlib_j": buildlib_j, "verongov_j": verongov_j, "crossedge_j": crossedge_j}
    if built == 0:
        CELLS = {k: "NO" for k in CELLS}
```

并加一条常驻锁：**表行判定列出现的新 `_j` 必须同时在 CELLS 册内**（AST 抓 `^\s{4}(\w+_j)\s*=` 与 CELLS 键名双向差＝0）。
实弹：f10 在 built=0 板上挂出物理归类 YES；现读折叠行仍漏 adapt/buildlib/verongov/crossedge 四格（本席 4c7ed9f7 现算——一枚实证已够定级，不必逐格注毒）。

**F10（观察级，不挡道但记账）**：
① 折叠吞真值：built==0 时钉册判 NO、现算值却印「与册不符 0 件」——建议折叠统一注记「输入失效⇒已算格全 NO（钉册真值见表头）」。
② `run()` `timeout=1800` 无兜 ⇒ 一把尺挂死＝整板 traceback 不出板；建议捕获成 `(98,"TIMEOUT")` 逐格点名。
③ `num()` 吃 Unicode 数字（`int("٠")`＝0、`\d` 亦吃）——F6 落地时顺手加 `isascii()` 判据即可。
④ F2 不吃 `bh_stale==0`（真尺构造上 total=0⇒stale=0，注毒件可造「落后合计 0 笔／3 座」仍 YES）——cell 里加一员即可。
⑤ decls/severance/s809 等把名册外目录名**原文回显**进 stdout/stderr（f3b 的通道本体）——对回显名消毒（repr 转义/摘 `=`），
   或明细行移到机读行之后＋grab 取行尾锚；属「输入文字与机读行不同屏」卫生。severance 的 `declared_pairs` 也缺
   drift/surface/s806 同款库数对账硬腿——补上它，板侧再加「built 座名集合 ⇄ decls roster 名集合对账，不符⇒总判拒判」，
   换根攻击即从「格值假」升为「整板拒判」。
⑥ 正面账：`--evidence` 硬门与「逐枚 --only」在本窗**实拦本席两轮**（bless 静默失败＋新格扩册瞬间）——摩擦是活的；
   自钉边界（板上自述）两轮复攻共同未解，解法只有 F7(b)/F8 外锚一条。

## §5 还原与零污染自证

- 台架写面＝`probes/s798-reattack.py`＋本文件＋%TEMP%（bench/runlog/pyc）；15→19 件真身全程只有 read/copy。
  各发 `disk-hashes.txt`（建台）与交卷前 `original-hashes.txt`（收尾）对照：**除 §0 表逐枚点名的「他人改版」
  （board×9、behind，及开窗时已动的 surface/drift/decls/factory）外无一格漂移**——漂移全部归属板 owner/他席在飞，本席零写入。
- 真十库（ChatBot_Libs）指纹：开窗中段与交卷前两次现算（各库 `git status --porcelain` 行数摘要）**`393d7cb5200a90ab` 逐字符全等**。
- 真仓 tracked 面 `git status --porcelain -uno` 摘要开窗 `d77fd4c83ff3a028…`；窗内有他席在飞（板文件八改即其证），
  本席对仓的写只发生在 `.superpowers/`（gitignore 内）自己的两个面上。
- 红线复查：未 commit/push/git init/搬文件/动 .env/拨闸/重启杀进程/跑 pytest 全量；板对真根只走 `--check` 只读档＋`--out` 落 bench。

## §6 本席自曝（假绿三形＋一次口头越线，全部本席自己抓到并修）

1. **bless 静默失败一轮**：第一波六发在 2200e19b 上没传 `--evidence`，repin 退 2、台架照跑 ⇒ 那些「拦住」全是
   99 空跑的假证据；逐发核对 repin rc 时发现，修法＝repin 非 0 即 Miss 中止、整批重跑（本表只收复跑件）。
2. **f4a 注毒体编译即崩**：第一版锚点截断集合推导式致 SyntaxError，marker 判据一度失义（结论侥幸未变向、证据无效）；
   重注可编译字节后重跑，marker 双向自证成立。
3. **x1 注毒与 bless 顺序颠倒**：先 bless 后注崩＝测的是 99 不是 traceback；改序重跑。
4. **口头越线一次（未落稿即止）**：B3 未完时我一度凭 bench 目录一行残留文本把 n3a 判成 ACHIEVED 写进叙述，
   回读 `results.jsonl` 逐条对账才发现该发记录当时尚未产生（被 s811 扩册闸中止）——最终 n3a 在正式波确实翻穿，
   但那是**复算后**的事实，不是那次臆读。教训与 S777「存在性糊过活性判据」同型：叙述前必以记录文件现算为准。

done: yes
