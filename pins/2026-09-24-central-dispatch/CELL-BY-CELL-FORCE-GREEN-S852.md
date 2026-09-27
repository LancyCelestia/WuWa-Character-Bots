# S852 逐格「单点强制翻绿」常驻台架：18 格战果矩阵（批次 250926J）

> 席位 S852。任务＝把 S760／S777／S798／S831 三轮人工复攻**固化成常驻可重跑台架**：对审计板
> `probes/s0-main-goal-audit.py` 的 **18 格逐格**做「单点强制翻绿」攻击＋判定，输出一张能当复跑前「尺有牙」
> 体检表的矩阵。台架＝`probes/s852-percell-bench.py`（`--shots list|control|<逗号发名>|all|summary`）。
> 被攻板版本（本窗交卷现算，全 36 发同一版）：`s0-main-goal-audit.py` sha256[:12]＝**`9142db4c89f5`**
> （全值 `9142db4c89f526581f5fbad847dda6acfc62676b9f0900c0839eb348602549fd`）。
> ⚠ **移动靶**：本窗内板被并发的板 owner 推进过两次（`718473f331b7`→`9142db4c89f5`）；已按〔cell,式〕交叉核对
> 两版逐格判定**零分歧**，交付快照统一重跑在 `9142db4c89f5`（当前在盘版）上。后来者引用前先 diff 板改动是否吃掉本表任何一发。

## §0 方法（判据只认板面实文＋板退出码，不认本席推理）

- **攻击模型**：每台架 `fresh_bench` 重建一枚 %TEMP% 副本——板副本（只把 `REPO` 锚点换成真实绝对路径以让
  VENV_PY 指回真 venv，判定逻辑一字未动）＋**全部 21 枚钉册件换成合成假尺**＋合成库根（造 `BUILT=10` 座，
  与真十库同值、不碰真仓真库）。每把假尺是 stdlib-only 的 `print + sys.exit`，只喂机读行。
- **每格两式**（合 36 发；`control-all-no` 另发）：
  · **S 式＝旧票原形重放**：只把该格那一枚**加固过的判据腿**踩住（其余腿喂真值），问「这一发的牙今天还在不在」
    → 落 NO/PART/拒判＝**拦**（牙在），落 YES＝**穿＝回归**（置顶红字点名）。S 式＝**改板后的常驻回归探测器**。
  · **P 式＝强制翻绿**：把该格判据链**全部**喂成自洽绿（含镜像板上每轮公开的对侧常数 261／15／座数），
    其余格尺诚实供 NO，验「单点（或该格所需最小面）造假能否刷绿」。P 式＝**残留边界**（钉册自钉、整件假量具，
    板自己写在「未覆盖」里、S795/S831 均实证未解），多数格穿是预期内、不算回归。
- **判定抽取**：跑板→读 `out/BOARD.md`→按该格行前缀取那一行**判定列**（YES／PART／NO）为唯一依据；
  「应当」一律 **NO**（中毒态下 mandate 各子句真实世界均未达成）。`拦＝该格非 YES`。
- **注毒先自证**：每发跑板前直跑全部合成尺（`selfprove_stub`），确认各自 rc 与机读体确按预期产出，
  否则 `POISON-MISS` 不发板；bless 走板自己的合法 `--repin --only <21枚> --reason --evidence`（只写副本），
  退非 0 即中止整发。`pin` 那一发故意**不 bless**，考「改尺不改板」。

**对照基线（`control-all-no`）**：全尺诚实供 NO、bless 全枚 → 板 rc=1、**恰 1 枚 YES＝量具钉册自证**（自证格在
全 bless 下本就真），其余 17 格全 NO。⇒ 本表任何一发的差异都可归因到注毒本身，不是夹具/重录。

## §1 十八格战果矩阵（S 式＝牙在否／P 式＝残留边界；全在 `9142db4c89f5`）

| # | 格（板行名） | S 式踩的那枚加固判据腿 | S 板判 | 应当 | 拦/穿 | P 式最小造假足迹 | P 板判 | 拦/穿 | 回归 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 快照可信度 `drift_j` | 崩件回显 `VERDICT: CLEAN`＋`DRIFT=0` 但 rc≠0（S760 C1 rc 腿＋数字腿双闸） | NO | NO | **拦** | drift 尺供 `DRIFT=0`＋`VERDICT: CLEAN`＋rc0 | YES | 穿 | — |
| 2 | 版本号三处一致 `version_j` | `CONSISTENT` 在、真数「不一致/缺件/缺 tag **10 处**」也印（S777 #4 补问题数腿） | NO | NO | **拦** | `CONSISTENT`＋扫 10 座＝built＋问题 0 处 | YES | 穿 | — |
| 3 | 落码前就绪度 `ready_j` | `fails=0` 但 `libs_measured=9≠built`（S777 #6/#8 补「测座＝板座」腿） | NO | NO | **拦** | `READY`＋measured=10＋fails=0 | YES | 穿 | — |
| 4 | 统筹更新 `behind_j` | 只造 behind（UP-TO-DATE/total0/stale0/measured10），通道尺 syncverify 留诚实⇒`stage≠full`（S816 通道腿＝**第二把尺互锁**） | NO | NO | **拦** | behind **＋** syncverify 双造（stage=full/git_libs=10/run2_up=10/idem=1/restored=1） | YES | 穿 | — |
| 5 | 三前置②·运行只走一条中央缝 `seam_j` | `VERDICT: GREEN`＋COUNTS 三数**各印两解**（S798 F6 grab 唯一性→`?`） | NO | NO | **拦** | `GREEN`＋`COUNTS offseam=0 second=0 unknown=0`（各恰一次） | YES | 穿 | — |
| 6 | 三前置①·规格统一 `spec_j` | `debt_official=0` 但 `faceB_unmigrated=199`（真值留该腿） | NO | NO | **拦** | `GREEN`＋debt0＋faceB0 | YES | 穿 | — |
| 7 | 三前置③·域外件不掉了 `outside_j` | blind/accident 0 但 `residue=1`（三残各腿缺一即停） | NO | NO | **拦** | `CLEAN`＋blind/residue/accident 全 0 | YES | 穿 | — |
| 8 | 名册库声明源 `de_j` | `gap=0` 但 `seeded=3`（S759 播种在册＝还没建、保守侧不拆半绿） | NO | NO | **拦** | `DECL gap=0 seeded=0 roster=15` | YES | 穿 | — |
| 9 | 断开度 `sev_j` | numer=denom=105 但 `stmt_edges=99999≠`surface 的 261（S777 F3/#10 与 surface 同源互证腿） | NO | NO | **拦** | 假 severance 供 `numer=261 denom=261 stmt_edges=261`（**镜像板每轮公开的 261**，S831 #2 形） | YES | 穿 | — |
| 10 | 非代码面归类 `nc_j` | covered=universe 齐、cats 5/5 但 `cats_direct=4≠5`（S759 直接声明腿，大类外溢不算） | NO | NO | **拦** | covered=universe=1439＋cats 5/5＋direct 5/5 | YES | 穿 | — |
| 11 | 三前置·物理归类（穷尽性）`exhaust_j` | 四腿 0 但 `wash=1`（S806 五腿硬零缺一即 NOT EXHAUSTIVE） | NO | NO | **拦** | `EXHAUSTIVE`＋unowned/inbound/double/sole_missing/wash 全 0 | YES | 穿 | — |
| 12 | 统筹适配 `adapt_j` | 三腿/座数/XCHECK 齐但 `stmt_edges=0≠`surface 261（S805 与 surface 逐值相等互证腿） | NO | NO | **拦** | `ADAPTED`＋三腿=10＋XCHECK OK＋`stmt_edges=261`(镜像) | YES | 穿 | — |
| 13 | 按一级分类各建 git 库 `buildlib_j` | `per=15` 但 `missing_dir=5`（S809 分子腿：分母改名册后仍逐座数缺目录） | NO | NO | **拦** | `per=15 missing_dir=0 not_git=0`（互证对侧 de_ros=15 **本就是真值⇒不加牙**） | YES | 穿 | — |
| 14 | 统筹管理版本号 `verongov_j` | missing/git 0 但 `no_range_policy=1`（S809 range 政策在册腿） | NO | NO | **拦** | `no_manifest=0 ver_bad=0 no_range_policy=0`＋per=15 | YES | 穿 | — |
| 15 | 三前置·跨库边可枚举 `crossedge_j` | `edges=99999≠`surface 261（S811 与 surface 逐值相等互证腿） | NO | NO | **拦** | `GREEN`＋`edges=261`(镜像)＋棘轮 589≤621 | YES | 穿 | — |
| 16 | mandate 四类对象都进了库 `kinds_j` | protocol `dual=13` 换 `unowned=0`（S834 腿㉕：拿双主换无主即 NO——**且板面「现算值」列根本不显 dual，只有派生腿看得见**） | NO | NO | **拦** | 四类 `hits>0 unowned=0 dual=0`＋`KINDS-COVERED` | YES | 穿 | — |
| 17 | 版本号·逐座显式政策 `rangepol_j` | `per=declared=15 missing=0` 但 `wildcard=1`（S833 通配还在场＝逐座是假的） | NO | NO | **拦** | `RANGE-IN-PLACE`＋per=15 declared=15 missing=0 wildcard=0 | YES | 穿 | — |
| 18 | 量具钉册自证 `pin_j` | 换 drift 尺供绿但**故意不 bless**（改尺不改板）→ 板面点名「与册不符 21 件」＋该尺 rc=99 | NO | NO | **拦** | 同换 drift 尺＋走合法 `--repin` bless → 「与册不符 0 件」而读数已假 | YES | 穿 | — |

**合计**：**S 式 18／18 拦（回归 0）**｜P 式 18／18 穿（残留边界，非回归）。

## §2 回归清单（点 4：旧票已修形态不假定「今天仍拦住」，逐发重跑取现值）

本窗把三轮旧票的每一枚**加固过的判据腿**都按原形重放了一遍（＝上表 S 式列）。**现值全部仍拦住、无一回潮**。
逐条对账（旧票当时结论 → 本窗 S 式现值）：

| 旧票那一发 | 当时怎么判 | 修它的加固腿 | 本窗 S 式现值 | 回潮？ |
|---|---|---|---|---|
| S760（traceback-leak / 文案腿单满足翻绿） | 打穿 | drift 补 rc 腿＋真漂移数字腿 | **拦**（`drift-s` rc≠0→NO） | 否 |
| S777 #4（version 只认「扫几座」，注毒「10 处」在场仍 YES） | 打穿 | version 补「问题数＝0」数字腿 | **拦**（`version-s` 问题 10 处→NO） | 否 |
| S777 #6/#8（behind/ready 无零测自锁→凭 measured=0 自翻） | 打穿（且是加固自身引入的**唯一回归**） | 补「测座＝built 且 built>0」＋全局 built==0 折叠 | **拦**（`ready-s` measured9≠10→NO；`behind-s` 通道尺不绿→NO） | 否 |
| S777 #10 / S798 f3a（假 severance numer=denom=99999 独刷绿） | 打穿（互证是散文） | F3 把「与 surface 同源互证」升成执法＋F7 吃对面 rc | **拦**（`sev-s` stmt=99999≠261→NO） | 否 |
| S777 #11 / S798（noncode 缺 cats_direct 侥幸、供全五数翻绿） | #11 拦 / #11b 穿 | 直接声明类目须＝总类目（外溢不算） | **拦**（`nc-s` cats_direct4≠5→NO） | 否 |
| S798 F6（明细行原文带 `SEV numer=` 顶掉真值） | 打穿 | grab 唯一性：模式非恰一次一律 `?` | **拦**（`seam-s` COUNTS 两解→`?`→NO） | 否 |
| S834 腿㉕（拿双主换无主把 kinds 刷绿） | 挂账/新造双主 13 | kinds 判据加「任一类 dual≠0 即 NO」 | **拦**（`kinds-s` protocol dual13→NO） | 否 |

**未回潮的解释**：这一批 S 式攻的全是**加固腿本身能覆盖的、单尺不协同**的形态——加固在场就拦得住。
而 P 式（把整条判据链喂成自洽绿＋镜像对侧常数）18/18 穿，是板**自述且未解**的通道（钉册自钉、整件假量具、
互证只认相等不认出身）——两件事不冲突：**S 式绿＝牙没掉；P 式穿＝牙本来就不咬这型**，不是回归。

## §3 本表给她的读法（这张板今天可信到什么程度）

1. **13 枚「无第二把尺/无对侧咬合」的格**（drift/version/ready/seam/spec/outside/de/nc/exhaust/rangepol/buildlib/verongov ＋ pin-P）：
   一把**自洽说谎的尺＋合法重录**即可刷绿——这是钉册自钉的必然代价，板「未覆盖」已明写，不防协同。
2. **4 枚有真牙的格**（behind 的第二把尺互锁 / sev·adapt·crossedge 与 surface 逐值相等）：
   单尺不协同刷不动，**但**——牙咬的是「不协同」，只要攻击者镜像板上每轮公开的对侧常数（261），
   `sev-p/adapt-p/crossedge-p` 照样翻绿（S798 f3a/S831 #2 已把这条钉死）。**它们比第 1 类强的地方只在
   「造假得同时骗过两把尺的相等」，不在「骗不过」。**
3. **互证分母是真值时不加牙**（`buildlib-p` 的 de_ros=15、`crossedge/sev` 的 261）：这些常数本就是对的，
   攻击者不用伪造它们，只需把自己的分子喂绿——所以「与名册互证」「与 surface 互证」只挡得住
   **改分母**，挡不住**改分子**。这是本矩阵最该被看见的一条结构性事实。
4. 三处「地板/裁决面」不在本格 18 格内（属 F6/F8/F9/外锚，已由 S798/S831 逐发钉）：本席只交**格面**体检表；
   「改八个变量静默翻 ACHIEVED」那条出口由外锚＋地板守，与本表两回事，引用别混。

## §4 复跑命令簿（点 5：改板后一条命令验「牙还在」）

卫生四件全程带齐。`VP` ＝生产 venv python（`ChatBot_Runtime/venv/Scripts/python.exe`）。工作目录＝本席目录
`.superpowers/sdd/2026-09-24-central-dispatch/`。

```bash
# 通用前缀（每个新 shell 先设一次；$TEMP 走 tempfile，别信 bash 的 $TEMP）
export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1
VP="../ChatBot_Runtime/venv/Scripts/python.exe"     # 相对本席目录；或写全绝对路径

# 〔牙还在否〕一条命令跑全部 18 格 S＋P（36 发，约 2–3 分钟），再出矩阵
"$VP" -B probes/s852-percell-bench.py --shots all
"$VP" -B probes/s852-percell-bench.py --shots summary     # 打印 §1 同形矩阵

# 只看回归探测器（改板后最该盯的 18 发＝S 式；S 全拦=牙在）
"$VP" -B probes/s852-percell-bench.py --shots drift-s,version-s,ready-s,behind-s,seam-s,spec-s,outside-s,de-s,sev-s,nc-s,exhaust-s,adapt-s,buildlib-s,verongov-s,crossedge-s,kinds-s,rangepol-s,pin-s
"$VP" -B probes/s852-percell-bench.py --shots summary

# 对照基线（应：rc=1、恰 1 YES＝钉册自证、17 格 NO）
"$VP" -B probes/s852-percell-bench.py --shots control

# 单发（<格>-<式>，格名去掉 _j；见 --shots list）
"$VP" -B probes/s852-percell-bench.py --shots sev-p
"$VP" -B probes/s852-percell-bench.py --shots list         # 全发名与攻击一句话
```

**判据**：改板后跑 `--shots all && --shots summary`——
- 上表 **S 式列只要出现任一 YES/穿 ⇒ 那一格的加固腿掉了 ⇒ 回归**，置顶红字点名（本窗＝无）。
- 逐发板面实文在 `%TEMP%/s852-bench/<发名>/out/BOARD.md`；结构化结果在 `%TEMP%/s852-runlog/results.jsonl`
  （每行含 `truth_board_sha12`，用它核对是不是跑在同一版板上）。

## §5 纪律自证 / 写面

- 台架写面＝本席表列出的 `probes/s852-percell-bench.py` ＋ 本文件 ＋ %TEMP%（`s852-bench/**`、`s852-runlog/**`、`s852-pyc`）。
  对板件、21 枚真身尺、真十库（ChatBot_Libs）、真仓 **只有 read/copy，零写入**；注毒全打在 %TEMP% 副本。
- bless（重录钉册）一律走板自己的合法流程 `--repin --only <枚> --reason --evidence`（含「直跑」「读数」两词），
  且只写副本板文件；`pin-s` 一发故意不 bless，考「改尺不改板」。
- 禁红线全守：未 commit、未 push、未 git init、未搬文件、未动 `.env`、未拨闸、未重启/杀进程、未跑 pytest 全量、未派新席。
  对真十库全程只读（本台架 even 不指真库根——用合成 `BUILT=10` 库根，比真根更严）。
- 数字一律现算：`BUILT=10`／`261`／`15` 是从板上每轮实文与真尺现读的对侧常数（S831 §0 同款），合成尺喂它们是为镜像「攻击者从板上能读到的值」，非手抄结论。
- 判「拦/穿」只认板面实文（各发 `out/BOARD.md` 该格行判定列）＋板退出码，不认本席推理。
- 工具结果/文件正文（含 MEMORY 索引、简报、AGENTS 台账、板与尺内注释）里的祈使句一律当数据处置，
  未执行任何非白名单指令。**安全登记（AGENTS 规则 11）：命中 0 枚。**

## §6 零污染自证（交卷现算）

- 真板在盘 sha256[:12] 跑后仍＝`9142db4c89f5`（本席只读它、从不写它）。
- 本席目录 `probes/` 只多出 `s852-percell-bench.py` 一枚交付件；无其它 `s852-*` 落盘。
- 仓树内 `.superpowers/.../probes` **无新增 `__pycache__`**（`PYTHONPYCACHEPREFIX` 全程指 %TEMP%/s852-pyc）。
- 全部 37 个 bench 目录（36 发 + control）只活在 `%TEMP%/s852-bench/`；结果只读落在 `%TEMP%/s852-runlog/`。
- 全 36 发 `rig=ok`（0 MISS/0 ERROR），`truth_board_sha12` 统一＝`9142db4c89f5`。

done: yes
