# S777 复攻：S760 的 13 发逐发重放（打在 250926A-14 加固板上）＋加发一发

> 席位 S777（批次 250926A-14）。被攻板＝`probes/s0-main-goal-audit.py`，开窗现算 sha256[:12]＝`331ccf69`（10 把量具 13 格），
> 正式复攻对象＝本席建台架时板 owner 已推进到的 `3b09841c`（**11 把量具 14 格**，新接 `s0-main-lib-readiness.py`）。
> 板件与十一把量具＋工厂＋名册探针**全程只读**；攻击全部打在 `%TEMP%\s777-bench\<发名>\probes\` 副本上。
> 台架＝`probes/s777-reattack.py`（可重跑：`--shots a,b,c`／`--shots summary`）；逐发全文＝`%TEMP%\s777-runlog\{batchA,batchB,batchC,baseline}.txt`。

## §0 纪律自证

- 台架对原件只有 read/copyfile 两种访问（源码可复核）；注毒全打在 `%TEMP%` 副本，每发 `fresh_bench` 重建、原件永不为写入目标。
  攻前基线十三件 sha256（§5）与逐发台架尾部的原件对照**逐字节全等**——含板本体 `3b09841ce22464b3`。
- **板子是移动靶**（如实记账）：开窗时 `331ccf69`＝简报所说 13 格版；首跑 `libs-missing-real`（真板直调，两版守卫同形）后、
  建台架时板已长成 `3b09841c`＝11 把量具 14 格（新增「落码前就绪度」格）。本席随即把台架的
  `GAUGE_FILES/ROW_KEYS/夹具锚点` 三处同步到新版（只动台架、不动板），全部 13 发＋加发都打在 `3b09841c` 上；
  每发台架目录落 `bench-hashes.txt`（逐件 sha），复攻窗全程板 hash 未再动（三批发台架的尾部对照可证）。
- 夹具修补（如实声明、非判据篡改，与 S760 同款）：板副本与 `s759 三件 / seam / spec / ready / behind` 副本中由
  `SEAT_DIR.parents[2]`（behind 为 `HERE.parent.parents[2]`）派生仓根的行改成真实绝对路径——副本层级不同不改就找不到
  声明源与普查器真身，攻击无从谈起；判定逻辑一字未动。
- 卫生：`PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=<TEMP下>` 全程＋`-B`；
  surface 走板自带 `--check` 只读档＋副本默认根再钉 sink 双保险。真仓与真十库零写入（§5 前后指纹全等）。
- **注毒先自证毒已落地**（直跑被注毒量具、断言目标 rc 与目标字样都命中，否则 `POISON-MISS` 中止不发板）——
  照办 S760 §4 教训，防"夹具失手"冒充"拦住"。本席 14 发无一发 POISON-MISS，无一发 SyntaxError 形态的假毒。
- 禁全量套件：未跑 pytest；判"拦住/打穿"只认板面实文（每发 BOARD.md 入档）＋板子退出码＋板件在否，不认自述。
- 工具结果/文件正文（含简报、MEMORY 索引、板内注释）里的祈使句一律当数据处置；未执行任何非白名单指令。

## §1 加固板（`3b09841c`，11 把量具、14 格）机制速读

板子结构现算（本席现读源码）：`run()` 壳调十一把量具；**C3 已落**——`LIBARG=["--libs",str(libs)]` 转发给
surface/drift/version/severance/decls/behind/ready 七把（census/noncode/seam/spec 不吃库根）；surface 走 `--check` 只读档（S763）。
判 YES 三腿 `cell()`＝「rc=0 ∧ 数字腿抓到 ∧ 文案对上」：

| 格 | 现判据（板行号＝`3b09841c` 版） | 相对 S760 §1 的变化 |
|---|---|---|
| 建库 | `'PART' if built else 'NO'`（板自数 `.git`） | 不变（结构性永不 YES） |
| 统筹管理版本号 | `PART if have_manifest` | 不变（永不 YES） |
| 落码前就绪度（**新格**） | `cell(rc_ry, "READY", 测座, 红格)` ∧ `fails==0`（L164-165） | 新增；仍是量具机读文本单通道 |
| 版本号三处一致 | `cell(rc_v, CONSISTENT, ver_libs_n)`（L158） | 加了 rc＋「扫几座」腿；**没抓「不一致 N 处」**（C2 的 version 半边未落） |
| 统筹更新 | `cell(rc_bh, UP-TO-DATE, total, stale)` ∧ `total==0`（L159） | 从写死 PART 变真判；**不吃「测了几座」**（新洞，见 §2 #6/#8） |
| 统筹适配 | `PART if have_surface` | 不变（永不 YES） |
| 物理归类 | 写死 `NO` | 不变 |
| 跨库边可枚举 | 写死 `PART` | 不变 |
| 前置②中央缝 | `cell(...)` ∧ 三数全 0（L160-161） | 从写死 PART 变真判 |
| 前置①规格统一 | `cell(...)` ∧ 两数全 0（L162-163） | 同上 |
| 快照可信度 | `cell(rc_d, CLEAN, DRIFT数)` ∧ `DRIFT==0`（L157） | **C1＋C2(drift 半边) 已落**：rc 腿＋真漂移数字腿 |
| 断开度 | `rc ∧ num/denom 抓到 ∧ (num==den>0)`（L124-131） | `stmt_edges` 与 surface 的「同源互证」**仍是散文**（C8 未落） |
| 非代码面 | `rc ∧ 五数抓到 ∧ cats 5/5 ∧ cov==uni`（L134-142） | 五数全同源单行，无交叉核验 |
| 名册库声明源 | `rc==0 ∧ gap==0`（L144） | 单通道 |

- **C5（总判）已落**：总判由表格派生、PART 同判不达、未达格逐格点名、`return 0 if achieved else 1`（L194-212）；
  且建库/版本号①/归类/跨库边四格结构性永不为 YES ⇒ **总判面今天不可能被翻成 ACHIEVED**（这一面是真闭合）。
- **C6（量具哈希钉册）未落**——简报称按 C1/C2/C3/C5/C6 加固，但板全文 `sha256|hashlib|PINNED|钉册` grep **零命中**（本席现算）。
  「整件假量具」这一类今天仍无防线；本席据实报备这条**简报与板上现值不符**。
- `grab` 仍吃 stdout+stderr 合并流（L52），但 `cell()` 的 rc 腿把 S760 最危险那发掐死在「崩溃 ⇒ rc≠0 ⇒ NO」。
- **baseline 今日真值**（未注毒，07:32Z）：唯一 YES＝版本号三处一致；快照 `STALE（DRIFT=26）`、统筹更新 `BEHIND 5 笔/3 座`、
  就绪度 `NOT-READY（红 10 格）`、断开度 0/52、非代码面 782/1433、seam/spec RED、decls gap 5。
  ⇒ 凡注毒发把这些格翻成 YES 的都是板上确凿的假绿，不是把灰洗成绿。

## §2 十三发逐发战果表（＋一发加发，标注「shot 外」）

「S760 当时」列＝旧板（`b40b3fde…2f6fae50`）结果，来自 `AUDIT-BOARD-ADVERSARY-S760.md` §2；本表全部打在 `3b09841c`。

| # | shot | 攻击怎么做 | 板子判成什么 | 应当判成什么 | 拦住还是仍打穿 | S760 当时 |
|---|---|---|---|---|---|---|
| 1 | libs-missing-real | 真板直调 `--libs` 指不存在目录 | FATAL、rc=2、不出板 | 拒判 | **拦住** | 拦住 |
| 2 | drift-rc1-clean | drift 副本 hard 强+1（rc 必 1）＋STALE 文案改 CLEAN，真分账不动 | 快照 **NO**（板头 drift=1 与 DRIFT=26 双双在案） | NO | **拦住**（rc 腿＋数字腿双闸） | 打穿 |
| 3 | drift-hard-zero | drift 副本 hard=0 ⇒ CLEAN 文案＋rc=0，合计行真数 DRIFT=26 原样在 stdout | 快照 **NO**（数字腿抓到 26≠0） | NO | **拦住** | 打穿 |
| 4 | version-lie | version 副本三处注毒：ok 恒 False＋假 CONSISTENT＋伪 return 0；stdout 逐行 DIVERGES×10、`不一致/缺件/缺 tag 10 处` | 版本格 **YES**（数字腿只认「扫 10 座」＝真数，无人读「10 处」） | NO | **仍打穿** | 打穿 |
| 5 | traceback-leak（最危险发） | drift 纯崩（future-import 后插 raise），异常消息含 `VERDICT: CLEAN`，零业务输出 | 快照 **NO**（rc=1；且 traceback 无 `DRIFT=` 数） | NO | **拦住**（C1 把这一发真杀死了） | 打穿 |
| 6 | all-empty | 板+量具全指空库根：drift/version/ready 各自 FATAL rc=2，behind 无零测自锁 ⇒ rc=0＋`libs_measured=0` 印 UP-TO-DATE | 「统筹更新」格 **YES**，且总判未达格清单**不含**统筹更新（派生句反向为假格背书） | 任何 YES 都不许出现 | **仍打穿（加固带来的回归）** | 拦住 |
| 7 | all-crash | 十一把量具全崩（运行时崩、rc=1、零业务行） | 板 rc=1、无 YES、总判逐列 14 格未达（PART 四行照挂但判不达） | 退非 0＋整句在不达 | **拦住**（C5 闭合） | 打穿 |
| 8 | root-decoupling | 只把板 `--libs` 换空目录、量具不注毒——考「逐把转发」是否焊死两库根 | 旧矛盾通道死（板头 `drift=2 version=2`，无「扫 10 座」）；**残余同 #6**：建 0 座与统筹更新 YES 同板 | 建 0 座时任何 YES ⇒ 拒判 | **仍打穿**（通道变形、本质续） | 打穿 |
| 9 | surface-vacuous | surface 副本默认根注空→直跑 `--check`（rc=0、数字全打、实写 0 张）；整板照跑 | 板显式传 `--libs` ⇒ 默认注毒通道**已死**；统筹适配永不吃量具数，YES 集与 baseline 全等 | 板侧拦住；量具空洞另案 | **板侧拦住**（C7 未落仍挂账） | 板侧拦住 |
| 10 | severance-crosscheck | 整件假 severance：只印 `SEV numer=99999 denom=99999 stmt_edges=99999` rc=0 | 断开度格 **YES**；99999 与同板 surface 真数 261 并存、全板零点名 | 互证不等必点名/落 NO | **仍打穿**（格面那句「与 surface 格同源互证」仍是散文） | 打穿 |
| 11 | noncode-lie | 整件假 noncode 只供四个数（缺 cats_direct） | 非代码面 **NO**（板面「有直接声明类目 ?/5」） | NO | **拦住**（侥幸：没编到字段，非格有防线） | 拦住（侥幸） |
| 11b | noncode-lie2 | 假 noncode 供全五个数：covered=universe=987654、cats 5/5、direct 5/5、rc=0 | 非代码面 **YES**，987654/987654 原样入板 | NO（真盘面 782/1433） | **仍打穿** | 打穿 |
| 12 | traceback-honest（对照） | 普通崩溃、消息不含判据字样 | 快照 NO | NO | **拦住**（对照仍对） | 拦住 |
| 加 | ready-lie（shot 外） | 整件假 readiness：只印 `READY libs_measured=10 fails=0`＋VERDICT READY，rc=0 | 就绪度格 **YES**（真盘同窗红 10 格） | NO | **仍打穿**（加固新格带旧病） | ——（旧板无此格） |

**总裁决**：13 发重放＝**8 拦／5 穿**（穿：#4、#6、#8、#10、#11b）。与 S760 当时对账：
加固真修好 **4 发**（#2、#3、#5、#7——含最危险的 traceback-leak 与"无整句"那族），未修 **3 发**（#4、#10、#11b），
#8 旧通道被转发掐死但残余假绿换了管道，#6 由拦转穿是**加固自身引入的唯一回归**
（把散文 PART 格改真判时，接的是一把没有零测自锁的量具）；加发 ready-lie 证明新「落码前就绪度」格与 S759 三格同病。
总判面（ACHIEVED 翻绿）本席无发能打穿——四格结构性永不 YES，这一层是真闭合的。

### §2.1 逐发关键板面原文（证据摘录，全文在各发 `%TEMP%\s777-bench\<发>\out\BOARD.md`）

- #5 traceback-leak：`退出码行 … drift=1 …`；板面判定 `"snapshot": "NO"`；直跑量具 `rc=1；其输出含 'VERDICT: CLEAN'＝True；含 'DRIFT='＝False`。
- #2 尾行直跑：`合计 SAME=439 DRIFT=26 …`＋`VERDICT: CLEAN（S777复攻注毒：账不为零却印干净）`；板仍 NO。
- #4 直跑：`逐行 DIVERGES 条数=10；合计行含『不一致/缺件/缺 tag 10 处』＝True`；板面 `"version": "YES"`。
- #6 板面：`| 按一级分类各建 git 库 | … | 建 0 座（…libs-empty） | NO |` 与
  `| 统筹更新 | … | 落后合计 0 笔／0 座（UP-TO-DATE）；幂等由 s0-main-lib-gitinit.py 实跑 | YES |` 同板并存；
  总判行未达格清单 13 项**独缺统筹更新**。真量具空根直跑实弹（本席现跑）：`BEHIND total=0 libs_stale=0 libs_measured=0` ＋ `VERDICT: UP-TO-DATE（全部落后 0 笔）` ＋ RC=0。
- #7 板面：`census=1 … ready=1` 全崩行；YES 格：无；总判逐格点名 True；板 rc=1。
- #10 板面两行：`分子 99999／分母 99999（仍直连语句边 99999，与 surface 格同源互证） | YES |` 与 `跨库 261、总目标边 1344 | PART |`。
- #11b 板面：`覆盖 987654/987654（有认领类目 5/5，有直接声明类目 5/5） | YES |`。
- 加发：`| 落码前就绪度（逐库十列） | … | READY（测 10 座／红 0 格） | YES |`（baseline 同格为 `NOT-READY（测 10 座／红 10 格） | NO`）。

## §3 仍打穿各发的可粘贴判据（指到具体格与函数口；写面归板 owner，本席只出文本）

以下行号按 `3b09841c` 版。每条附实弹依据与"不伤今日诚实绿"验算。

**F1（#4 version 格：补真问题数数字腿＋同根锁——C2 的 version 半边＋C3 尾巴）** 把 L158 改为：

```python
    ver_bad = grab(out_v, r"不一致/缺件/缺 tag (\d+) 处")
    ver_bad_n = num(ver_bad)
    version_j = cell(rc_v, ver_verdict, "CONSISTENT", ver_libs_n, ver_bad_n) \
        if (ver_bad_n == 0 and ver_libs_n == built) else "NO"
```

杀法实据：本席注毒板 stdout 里 `不一致/缺件/缺 tag 10 处` 逐字在场（§2.1 #4），`num(...)==0` 不成立 ⇒ NO。
不伤诚实绿：baseline `ver_bad_n=0`、`ver_libs_n=10==built` ⇒ 仍 YES。空根场景版本尺本就 rc=2 ⇒ 双保险。

**F2（#6/#8 sync 格：零测绿洞——量具供「测了几座」，判定必须吃它）** 把 L159 改为：

```python
    bh_measured = grab(out_bh, r"libs_measured=(\d+)")
    bh_measured_n = num(bh_measured)
    behind_j = cell(rc_bh, bh_ver, "UP-TO-DATE", bh_total_n, bh_stale_n, bh_measured_n) \
        if (bh_total_n == 0 and bh_measured_n == built and built > 0) else "NO"
```

杀法实据：本席现跑真尺指空根 ⇒ `libs_measured=0`＋UP-TO-DATE＋rc=0（§2.1 #6），`0 != built(0)` 且 `built > 0` 不成立 ⇒ NO。
配套量具侧根修（behind 件 owner 落，本席不动该件）：`dirs = sorted(...)` 之后镜像 version-check L40-42 的零扫守卫——
`if not dirs: print(f"FATAL: 库根下没有 git 库（{libs}）——别把'没扫到'报成'全部落后 0 笔'", file=sys.stderr); return 2`。
不伤诚实绿：baseline 尺 rc=1（BEHIND）本就 NO；将来全同步真时 `measured==built==10` 照常 YES。

**F3（#10 severance 格：「同源互证」从散文变执法——C8）** 在 L124-131 块之后、拼行之前加：

```python
    sev_cross_ok = (sev_e == cross_edges and "?" not in (sev_e, cross_edges))
    if sev_j == "YES" and not sev_cross_ok:
        sev_j = "NO"
```

并把断开度行的「与 surface 格同源互证」字样改成带执法的投影：
`（仍直连语句边 {sev_e}，与 surface 格互证{'成立' if sev_cross_ok else '失败：' + str(sev_e) + '≠' + str(cross_edges)}）`。
杀法实据：假件 99999 ≠ 真 surface 261（§2.1 #10）⇒ NO＋板面点名。
不伤诚实绿：baseline 两数同为 261（本席现读两行）⇒ 互证成立、判定不变。两尺同宇宙同 AST 口径（severance 头注自陈
「语句形应与 surface 尺那格逐值相等」），真不等就是有一把瞎了——正是该点名的时刻。

**F4（#4/#10/#11b/加发的通用反制：C6 钉册，简报称已落而板上零命中——这是全类"整件假量具"唯一通用防线）** 板内加：

```python
PINNED_GAUGES = {  # 量具改版必须 --repin 重录并附理由，禁静默改册（钉住工厂与名册探针：换它们＝换掉其全部消费者）
    "s0-main-unowned-edge-ranker.py": "04101548b2078e73dd4f41dae4ed38c43db127d6f61ff306f5874c53580bbb94",
    "s0-main-lib-api-surface.py": "d7ef7694a394ada1b206b5caa99854367d47662a9b32cafe01ffada4b767810e",
    "s0-main-lib-drift-checker.py": "09f4f237437b31b5e493e1ea37527db3c918fad0ea036031efeb9317af1b693e",
    "s0-main-lib-version-check.py": "1d7a4b6562243a6b87c55457b910f77ca51db9fb7abbe10afa7ad8ebf7b9bcb7",
    "s759-severance.py": "845373dcaf1438fde2751645bddaea62dc68fcfcd97f9f49b3974c36e02f81a0",
    "s759-noncode.py": "fc3352cb000e665f4c50827f2a3a4b1055ec88ff12a80b0d7e3cdabe6e4a9138",
    "s759-decl-sources.py": "4bbf38de99b399212a5143f32401835f11c65afc614c65bffdf1a4c10c663347",
    "s0-main-central-seam-check.py": "94e5d97601b5527f466c2b566cff9188053a459543df456093dc82cc4d979509",
    "s0-main-spec-uniform-check.py": "6a38a056b0fb028863ddb882baff441635852a2f242cfe756ff2e8310dfce6c4",
    "s0-main-lib-behind-commits.py": "d69e58272eb8278046c4b102dbcf759da6cda2e0043cd4a7f24b35244be1c3c1",
    "s0-main-lib-readiness.py": "b31f053161e31a8f399de469c6d4c9d8b767b2296701c9e40d30e965ce2cafeb",
    "s0-main-lib-factory.py": "e0cb6055405a44e6ec3c00b40392199bdbe1a164c1e3aa045b2565a4145885ed",
    "s715-deps.py": "28724bed9a907cb317228769bf6ce0edb448f9ca6a5b2687ad3010eb5177b278",
}

def pinned_ok(name: str) -> bool:
    p = HERE / SOURCES[name]
    import hashlib
    want = PINNED_GAUGES.get(p.name)
    return bool(want) and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == want
```

`run()` 里 subprocess 之前加一行：`if not pinned_ok(name): return 99, f"FATAL: 量具 {name} 与钉册不符（换件/篡改 ⇒ 不可判）"`
——rc=99 非 0，`cell()` 与派生句自然把该格落 NO、总判点名。**上面十三枚值＝本席 2026-09-26 现算**（§5 表同源）；
readiness 今日新落、钉册随他合法改版重录，这正是钉册该有的摩擦。
边界如实写：F1–F3 防"改文案不改真数"的半毒与格间断言兑现；F4 防"整件换尺"。两类合起来才封住
#4/#10/#11b/加发四条通道——单给任何一类都还剩门开着。

**F5（#9 量具侧 C7 残账＋新观察：surface 的 `--check` 同样零测不 FATAL）** surface 件 `--check` 分支打印盘面对账行之后加（件 owner 落）：

```python
    if args.check and boards and (disk_same + disk_drift + disk_missing) == 0:
        print(f"FATAL: 盘面对账 0/0/0＝一座库的接口面都没摸到（库根 {libs}），空转不是成果", file=sys.stderr)
        return 2
```

今日该空洞流不进任何格（统筹适配吃板自己数的 have_surface）；但它是 #6 同族第二例——**"判据格化"运动里每接一把无零测自锁的量具就新开一个洞**，
接线时务必带锁（见 §4 教训句）。

## §4 这版板子可信到什么程度（一句话边界）

**总判面已焊死（ACHIEVED 今天不可翻，四格结构性永不 YES、PART 同判不达、未达逐格点名、退出码随派生）；格面半焊——
"纯文案、纯崩溃"翻不动了（S760 快照格那四发全拦），但一张假机读数行仍能翻四个格（版本号／断开度／非代码面／就绪度——钉册 C6 未落，
版本格的『不一致 N 处』数字腿也还没接），而「统筹更新」格连注毒都不必吃：库根指空它就凭零测自翻绿（加固新开的回归洞）。
所以对这张板的正确读法是：YES 格只在「量具文件没被换过、库根不是空、格读的数恰好都是那把尺的真问题数」三重前提下可信，
且板面对这三重前提本身不设防。**

过程教训一句（给后续接线的人）：把散文格改判据格时，**先给量具配零测 FATAL 自锁再接线**——behind 与 surface 两把是同一族缺口的现值两处。

## §5 还原与零污染自证

- 攻前基线（开窗 `sha256sum` 现算，全 64 位）＝ 攻后台架三批尾部逐件 16 位前缀对照 **全等**、无一漂移：
  板 `3b09841ce22464b3…`、census `04101548…`、surface `d7ef7694…`、drift `09f4f237…`、version `1d7a4b65…`、
  severance `845373dc…`、noncode `fc3352cb…`、decls `4bbf38de…`、seam `94e5d976…`、spec `6a38a056…`、
  behind `d69e5827…`、ready `b31f0531…`、factory `e0cb6055…`、s715-deps `28724bed…`。
  （开窗时板曾为 `331ccf69…`，改版是板 owner 所为、非本席——本席未写过板一字。）
- 真仓零写：全席窗口前 `git status --porcelain -uno` 摘要＝`678a9c4483b8dccc`，全批发完后同值。
- 真十库零写：各库 `git status --porcelain` 摘要攻前攻后均为 `f022d2c3358b`×10（干净态不变），
  `api-surface.json` 无新写时刻（板走 `--check`、副本根钉 sink）。
- 台架全程写面：`%TEMP%\s777-bench\**`（副本、空根、sink、BOARD.md 存证）、`%TEMP%\s777-runlog\*.txt`、
  本席写面 `probes/s777-reattack.py` 与本文件——仓库/库/他席文件零触碰；未 commit、未跑 pytest、未重启任何进程。
- 已知小项：`libs-missing-real` 在移动靶窗口被打过两次（`331ccf69` 与 `3b09841c` 真板直调），结果同（FATAL/rc=2/不出板），
  正式记批次的为 `3b09841c` 一发；首跑那次留下的 `results.jsonl` 已从汇总档中剔除。
- **交卷时再核（本席现算）**：板又前进至 `04549d34504f…`（板 owner 在我终发之后又动过板），
  十三件量具/工厂/探针哈希逐件未动（F4 钉册值仍有效）。本席全部结论钉在 `3b09841c` 版（各发
  `bench-hashes.txt` 为凭）；后来者引用前先 diff `3b09841c→04549d34` 板面改动是否吃掉本表任何一发。

done: yes
