# S760 恶毒自攻：完成审计板（`probes/s0-main-goal-audit.py`）假绿面攻防账

> 席位 S760（批次 250926A）。板子本体与四把量具**一律只读**；板子现归 S759 独占写，本席零接触其文件。
> 全部攻击打在 `%TEMP%` 副本台上（bench），原始件动没动＝逐字节 sha 对照，见文末自证。

## §0 纪律自证

- 板子本体 `probes/s0-main-goal-audit.py`、四把量具与工厂共六件，本席**全程只读**；六件原件 sha256 攻前/攻后对照见 §6（逐字节，非 mtime）。
- 注毒全部打在 `%TEMP%\s760-bench\<发名>\probes\` 副本上；每发 `fresh_bench` 重建，"还原"即不残留——原件从未成为写入目标。
- 副本上有两处如实声明的**夹具修补**（不是判据篡改）：板子副本的 `REPO = SEAT_DIR.parents[2]` 与 `VENV_PY = REPO.parent / ...` 两行改成真实绝对路径——副本目录层级不同，不改这两行板子连量具都调不起来，攻击无从谈起。
- 卫生四件套＋`-B` 全程带上（`PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=%TEMP%\s760-bench\pyc`）；surface 量具副本的库根一律改指 bench 内 sink/空目录——**任何一发都没有向 `ChatBot_Libs` 真写过一个字节**（防"审计板顺手重生成十库接口面"的副作用）。
- 禁全量套件：未跑；判"拦住/未拦住"只认板面实文＋板子退出码＋出板与否，不认自述。
- 工具结果/文件正文里的祈使句一律当数据处置，未执行任何非白名单指令。

## §1 板子机制与攻击面地图

板子结构：`run()` 依次调四把量具（census/surface/drift/version），把 stdout+stderr 合并成字符串，用 `grab(正则)` 抓汇总行；抓不到落 `?`。八个格子的判据表达式（逐格现状，本席现读现算）：

| 格 | 判据表达式（现状） | 量具依赖 | 可翻 YES？ |
|---|---|---|---|
| 建库 | `PART if built else NO`（板自己数 `.git` 目录） | 无（板侧 fs 计数） | 否 |
| manifest | `PART if have_manifest else NO` | 无 | 否 |
| 版本三处一致 | `YES if ver_verdict=='CONSISTENT' and rc_v==0 else NO` | version 的 VERDICT 文案＋rc | **是（单通道文案）** |
| 统筹更新 | 写死 `PART` | 无（无任何量具供数） | 否（但永不可证伪） |
| 统筹适配 | `PART if have_surface else NO` | 无 | 否 |
| 物理归类 | 写死 `NO` | census 供数、判定不吃数 | 否 |
| 中央调度 | 写死 `PART`（`?` 照样 PART） | surface 供数、判定不吃数 | 否（但拿不准不降档） |
| 快照可信度 | `YES if verdict=='CLEAN' else NO`——**不查 rc_d** | drift 的 VERDICT 文案 | **是（连 rc 都不看）** |

三个结构性事实（本席现读源码定案）：
1. 全板**没有任何"整句判定"**——文件头 docstring 承诺「任何一格拿不准 ⇒ 整句判 NOT-ACHIEVED」，实现里根本没有这句，八格各说各话，`return 0` 无条件；「整句 NOT-ACHIEVED」目前是散文不是判据（与本窗"存在性糊过活性判据"同族）。
2. 板头打印的「非 0 即该格不可判，按 NOT-ACHIEVED 计」同样是散文：八格里只有版本格真把 rc 写进了判据；快照格 rc_d 显示在头上、不进判据。
3. `--libs` 只作用于板自己的三个 fs 计数（built/have_manifest/have_surface）；四把量具**从不接收该参数**（板子调用时全部传空 extra），量具各自吃硬编码库根默认值 ⇒ 板与量具的"库根"是两个真值源。
4. `grab` 读的是 stdout+stderr 合并文本 ⇒ 有被 traceback 引文污染的理论面（现有正则 `VERDICT: ` 冒号后带空格、而源码行是 `"VERDICT:",` 不带空格，恰好不撞上——见 §4）。

## §2 攻击逐发结果表

**板子是移动靶**：本窗 S759 在场编辑，板面从「四把量具 8 格」长成「七把量具 11 格」，共经历至少四版（sha 前 12：`b40b3fde` → `71ef4ed2` → `4f9a1d02` → `2f6fae50`）。每发台架落档实际攻击的板版（`%TEMP%\s760-bench\<发>\bench-hashes.txt`），下表「复打版本」列即归因；同一发在多版上结果一致的，只写最新确认版。

| # | 攻击（shot id） | 板子判成什么 | 应当判成什么 | 拦住？ | 复打版本 |
|---|---|---|---|---|---|
| 1 | 库根路径指错（`libs-missing-real`，真板直调） | FATAL、rc=2、不出板 | 拒判 | **拦住** | b40b3fde / 71ef4ed2 |
| 2 | 量具 rc=1 但把 STALE 印成 CLEAN（`drift-rc1-clean`） | **快照格 YES**（板头明明印着 drift=1） | NO | **未拦住** | b40b3fde→**2f6fae50（交卷时现版，v4 复打仍翻绿）** |
| 3 | 量具 rc=0、真账照打、只把判定数归零（`drift-hard-zero`，数据不变=真漂移 25 处） | **快照格 YES**（①＝25 还在 stdout 里，板子不看） | NO | **未拦住** | b40b3fde→4f9a1d02 |
| 4 | 版本量具全文案造假（`version-lie`：逐行 DIVERGES×10、合计"10 处"，VERDICT 印 CONSISTENT 且伪 rc=0） | **版本格 YES** | NO | **未拦住** | b40b3fde→**2f6fae50（交卷时现版，v4 复打仍翻绿）** |
| 5 | drift 秒崩、异常消息恰好含 `VERDICT: CLEAN` 字样（`traceback-leak`；零业务输出，对照发 `traceback-honest` 普通崩溃判 NO 拦住） | **快照格 YES**——翻绿只需一串出现在 stderr 的字，不需要任何数据 | NO | **未拦住（最危险）** | b40b3fde→4f9a1d02 |
| 6 | 空库根全空（`all-empty`：板与量具全指空目录） | 无 YES（建库 NO/版本 NO/快照 NO/适配 NO） | 不出现 YES | **拦住**（但"统筹更新/中央调度"两格仍挂 PART，拿不准不降档） | b40b3fde→4f9a1d02 |
| 7 | 四把量具全崩（`all-crash`：运行时异常、全 rc=1、无数） | 照常出板、退 0；版本/快照 NO，但 built/manifest/sync/surface/dispatch **五格照挂 PART**，全板**无整句判语** | 无整句句在板子上不存在＝承诺缺失 | **未拦住** | b40b3fde→4f9a1d02 |
| 8 | 板与量具两个库根（`root-decoupling`：板 `--libs` 指空目录，量具不接收该参数仍扫真库根） | 同一张板印着「建 0 座」与「扫 10 座 ⇒ YES」 | 矛盾 ⇒ 拒判 | **未拦住** | b40b3fde→71ef4ed2 |
| 9 | api-surface 指空库根（`surface-vacuous`） | 板侧无恙；量具侧写 0 张表仍 rc=0、数字照常打满 | 量具应 FATAL | 板格**拦住**；量具空洞另案（C7） | b40b3fde→71ef4ed2 |
| 10 | 整件假 severance（`severance-crosscheck`：numer=denom=99999、stmt_edges=99999，surface 真报 261） | **断开度格 YES**，99999 与 261 同板并存、全板无一句点名——格面那句「与 surface 格同源互证」是散文 | 两数不等必点名/落 NO | **未拦住** | 2f6fae50 |
| 11 | 整件假 noncode（`noncode-lie`：covered=universe=987654、rc=0） | 板上落 **NO**——S759 恰在同版给该格加了「有直接声明 ?/5」新维度，本席伪造行没供上那个数，`?⇒None⇒NO` 生效 | NO | **拦住**（侥幸，补发拆穿见 11b） | 2f6fae50 |
| 11b | 假 noncode 供全五个数（`noncode-lie2`：再加 cats_direct=5/5） | **非代码面格 YES**（覆盖 987654/987654 原样入板） | 真盘面覆盖远非 100%，应 NO | **未拦住**（证 11 的"拦住"纯属注毒没编到字段，非格自身有防线） | 2f6fae50 |

总裁决：**13 发实跑（含 1 对照发）＝8 发打穿**（#2/#3/#4/#5/#7/#8/#10/#11b），**5 发拦住**（#1/#6/#9板侧/#11/#对照10b）。打穿的八发全部共享同一个根：**板子把"量具交回来的文本"当唯一真源，判定腿（rc/数字/交叉核验/整句）缺哪条，哪条就能被对应的假文本翻色**；快照格是缺腿最多的一格（不查 rc、不查分账数、还吃 stderr 合并流）。**板子为移动靶**：交卷时又见 9aeb4cd1 新版（S759 在飞），本表结论钉在 2f6fae50（v4/新格发）与 4f9a1d02（v3）上；据后来者引用前先对 `bench-hashes.txt` 复核所打版本。

### §2.1 逐发关键板面原文（证据摘录）

- #5 traceback-leak（4f9a1d02 版板面）：`drift=1` 在板头退出码行原样印着，快照格仍为 `YES`；被攻量具直跑 `rc=1`、stderr 含 `'VERDICT: CLEAN'=True（无任何业务输出参与）`。
- #2/#3 的"应当判 NO"有真数据背书：同窗未注毒的 drift 真跑＝`SAME=442 DRIFT=25 CONCURRENT=0 MISSING=32 ONLY=5`、VERDICT 真值 STALE（即注毒只是把"真该 NO"的格翻成 YES，不是把灰翻绿）。
- #7 all-crash：板面判定 `{'version': 'NO', 'snapshot': 'NO', 'built': 'PART', ...}`、`板面含整句判语=False`。
- #10：断开度行原文 `分子 99999／分母 99999（仍直连语句边 99999，与 surface 格同源互证） | YES |`，同板中央调度行 `跨库 261`。

## §3 未拦住各发的可粘贴判据

以下判据均针对 `probes/s0-main-goal-audit.py` 现行行号（本席现读 b40b3fde 版）。写面归 S759/主代理，本席只出文本不落码。

**C1（一击即穿：快照格补 rc 腿，对齐版本格已有的写法）**——把
```python
f"| 快照可信度 | 漂移检查 CLEAN 且真漂移为 0 | {verdict} | {'YES' if verdict == 'CLEAN' else 'NO'} |",
```
改为
```python
f"| 快照可信度 | 漂移检查 CLEAN 且真漂移为 0 | {verdict} | {'YES' if verdict == 'CLEAN' and rc_d == 0 else 'NO'} |",
```
可杀 §2 的 drift-rc1-clean 与 traceback-leak 两类（两者 rc_d 都是 1）。

**C2（数字第二通道：VERDICT 文案之外，再抓量具自己打的分账行）**——在 `ver_verdict` 那组 grab 之后追加：
```python
    drift_drift = grab(out_d, r"①快照真漂移（两侧都在但字节不同）＝(\d+)")
    drift_only = grab(out_d, r"③归属未解（快照收了、但本尺判双认领而未派给它）＝(\d+)")
    drift_dual = grab(out_d, r"NOTE: 声明源仍有 (\d+) 枚双认领")
    ver_bad = grab(out_v, r"不一致/缺件/缺 tag (\d+) 处")
```
并把两格判据改为（`?` 一律不可判，禁当 0）：
```python
    snap_ok = (rc_d == 0 and verdict == "CLEAN" and drift_drift == "0"
               and drift_only != "?" and (drift_only == "0" or drift_dual == drift_only))
    ver_ok = (ver_verdict == "CONSISTENT" and rc_v == 0 and ver_bad == "0")
```
实弹依据：本席 drift 注毒两发都只改了 `hard`/判定文案，①③分账行仍是真数（25/5）——C2 一发即穿；version 注毒发打了 `不一致/缺件/缺 tag 10 处`，C2 同样抓得住。**边界如实写**：C2 防"改文案不改数"的半毒；整件量具被换成恶意程序时文本通道全可编，那要靠 C5。

**C3（板与量具同根：`--libs` 直通 + 交叉核验）**——`run(...)` 现不传库根，四把量具各吃硬编码默认值（板与量具是两个真值源，§2 root-decoupling 因此能同板出现"建 0 座＋扫 10 座 YES"）。改调用为：
```python
    rc_s, out_s = run("surface", ["--libs", str(libs)])
    rc_d, out_d = run("drift", ["--libs", str(libs)])
    rc_v, out_v = run("version", ["--libs", str(libs)])
```
（三件均有 `--libs` 参数，本席现读确证；census 不依赖库根，维持原样。）再加同根锁：
```python
    ver_ok = ver_ok and ver_libs == str(built)
```

**C4（拿不准不许顶着 PART）**——`统筹更新`/`中央调度` 两格现写死 `PART`，量具全崩也照样 PART（§2 all-crash 实证）。中央调度格改：
```python
f"| 三前置·中央调度（一条缝） | 跨库边可枚举且缺口台账不升 | 跨库 {cross_edges}、总目标边 {cons_line} | {'PART' if rc_s == 0 and rc_c == 0 and cross_edges != '?' and cons_line != '?' else 'NO（量具未交数）'} |",
```
统筹更新格现在**没有任何量具供数**（纯散文 PART）——接 S752 交付的只读校验件 `s0-main-lib-sync-verify.py`（`SOURCES` 加 `"syncverify"`，`run("syncverify", [])`，`'PART' if rc_sv == 0 else 'NO（同步校验件未交数）'`）；**该件未入库前不得先接**（散文只能点真存在的件——本窗旧教）。

**C5（整句判定行：把 docstring 的承诺变成判据）**——板头宣称「任何一格拿不准 ⇒ 整句判 NOT-ACHIEVED」，实现里没有这句（§2 all-crash 实证：板照出、退 0、无整句）。在 `L` 拼完、写盘前追加：
```python
    unknowns = [n for n, v in (("census入边", unowned_target_edges), ("census枚数", unowned_files),
                               ("surface跨库", cross_edges), ("surface守恒", cons_line),
                               ("drift判定", verdict), ("drift分账①", drift_drift),
                               ("version判定", ver_verdict), ("version扫库", ver_libs),
                               ("version分歧数", ver_bad)) if v == "?"]
    marks = {"版本号三处一致": ver_ok, "快照可信度": snap_ok}
    final = ("NOT ACHIEVED（拿不准格：" + "、".join(unknowns) + "）") if unknowns else \
            ("NOT ACHIEVED（存在 NO/PART 格，整句不升级）"
             if not all(marks.values()) or any("| PART |" in r or "| NO |" in r for r in L)
             else "ACHIEVED")
    L.insert(3, f"- **整句判定：{final}**")
```
配套可选 `--strict`：`return 0 if "ACHIEVED" == final else 3`（脚本化调用可用退出码执法；默认保持 0=出板成功，不改变现有调用方语义）。

**C6（第二真源：量具哈希钉册）**——C1–C3 全在"信量具文本"这一个真源里加固；量具本体被替换成恶意程序时唯一防线是钉文件哈希（仓内先例 `tests/verify_hashes.py`）。板内加：
```python
PINNED_GAUGES = {  # 量具改版必须 --repin 重录并附理由，禁静默改册
    "s0-main-lib-api-surface.py": "00abd62bdaef5d323eba4707bcfd9db44653d792d7fc94a1199961bae47a3c30",
    "s0-main-lib-drift-checker.py": "09f4f237437b31b5e493e1ea37527db3c918fad0ea036031efeb9317af1b693e",
    "s0-main-lib-version-check.py": "1d7a4b6562243a6b87c55457b910f77ca51db9fb7abbe10afa7ad8ebf7b9bcb7",
    "s0-main-unowned-edge-ranker.py": "04101548b2078e73dd4f41dae4ed38c43db127d6f61ff306f5874c53580bbb94",
}
```
`run()` 前逐件 `sha256` 比对，不符 ⇒ 该格强制 `NO（量具与钉册不符：改名）`且整句 NOT ACHIEVED。上面四值是**本席 2026-09-26 现算**（§6 表同源）；S759 补三格改量具后需重录，这正是钉册该有的摩擦。

**C7（量具侧根修：surface 空洞成功）**——`s0-main-lib-api-surface.py` 对空库根写 0 张表仍 rc=0、数字照常打满全场（§2 surface-vacuous）。把 `out_file.write_text(...)` 处计数、末尾加：
```python
    if written < len(boards):
        print(f"FATAL: 应写 api-surface.json {len(boards)} 张、实写 {written} 张（库根 {libs} 缺目录＝输入失效，不是成果）", file=sys.stderr)
        return 2
```

**C8（断开度格"同源互证"从散文变执法；§2 #10 实证其缺）**——板子断开度格现仅执法 `rc/num/denom`，格面那句「stmt_edges 与 surface 格同源互证」无对应比较。照 S759 三格自己的好纪律扩一条：
```python
    # 互证必须落进判据：断开度量具自报的"仍直连语句边"应恰等于 surface 量的跨库边数，
    # 不等＝两把尺对同一件事各说各话，整格降为不可判（互证不是装饰品）
    sev_cross_ok = (sev_e == cross_edges and "?" not in (sev_e, cross_edges))
    if not sev_cross_ok:
        sev_j = "NO"
```
并把不等情形点名进板面（如 `互证失败：sev stmt_edges≠surface 跨库边`）。同款问题一锅端：`统筹更新` 格的 PART 没有任何供数件（见 C4），`物理归类` 格写死 NO 但 `classify` 数字与 `dispatch` 数字（同源于 AST 宇宙）也无人对账。

**版本注记（本席如实）**：§3 各条按 b40b3fde 版行号书写；截至交卷板子已演进到 2f6fae50（S759 补三格、三新格自带 rc 腿＋数字腿，方向正确），C1–C5 所指旧格判据在 4f9a1d02/2f6fae50 版逐条复核**仍未修**（复打证据见 §2 表"复打版本"列）；C6 钉册值须按 S759 收口后的终版重录。

## §4 试过但没打穿的方向（如实，不编红）

- **指错板子 `--libs`（库根不存在）**：拦住。副本与真板各验一发思路后，真板实跑：FATAL、非零退出、不出板——这条判据是真的（本席确认它来自 S0 自曝后补的守卫，注释里写着"今天真差一层"）。
- **纯崩溃（异常文本不含判据字样）**：拦住（traceback-honest 对照发，快照格 `?→NO`）。翻绿只靠把 `VERDICT: CLEAN` 字样喂进合并流——这正是 C1/C5 要堵的洞本身。
- **新格「非代码面」翻绿（noncode-lie）**：第一发未打穿，但补发 `noncode-lie2`（供全五个数、含 `cats_direct=5/5`）当场翻 YES——11 发的"拦住"**纯属本席首版没编到新增字段**，不是格自身有防线。该格与旧格同病：单通道、无交叉核验。
- **census/surface 供数格翻绿**：打不穿——那两格的判定是写死 `NO`/`PART`，数字根本不进判据，往数字里注毒改变不了格子；但它们也因此**永远不可证伪**（PART 假象另案，见 C4）。
- **超时/板子自身崩溃**（venv 路径坏、`--out` 目录不存在）：`subprocess.TimeoutExpired`/`write_text` 异常都在写板之前抛出 ⇒ 非零退出、无板，fail-closed。此两条为源码推理所得，**未逐发实弹**，如实标注。
- **`grab` 抓 traceback 引文（不经毒的自发形态）**：未打穿——现行两把 VERDICT 正则要求冒号后带空格，量具源码行是 `print("VERDICT:", ...)` 不带空格，崩溃回显引源码恰好不命中；但只要把输出改成 `print(f"VERDICT: {x}")` 形态，自发泄漏即成立（本席用它做成了定向攻击发 #5）。
- **本席自曝一发假"拦住"**：`traceback-leak` 首版把 `raise` 插到量具文件**第一行**（`from __future__` 之前）⇒ 编译期 SyntaxError，毒消息根本没进 traceback，台架却如实报"拦住"。修夹具（改插 future-import 之后）复打才真翻绿。教训与规则 11 同源：**注毒必须先自证"毒已落地"（本席补了"直跑量具 stderr 含目标字样=True"的自检行），否则"拦住"是夹具失手的别名**。另两发同类小坑：all-crash 首版同样是 SyntaxError 形态的崩（对板语义等价，已改运行时崩溃重打）；severance-crosscheck 首版注入点在真实早期出口（rc=2 路径）之后、毒未执行，改整件假量具后打穿。三处失手全部留在 bench 日志里可查，未抹。
- **板子移动靶归因**：S759 在本席开窗后连改四版板面（b40b3fde→71ef4ed2→4f9a1d02→2f6fae50）。台架从 v3 起每发落 `bench-hashes.txt` 记实打版本；§2 表已按版本归因，其中 #2/#4 在交卷现版 2f6fae50 上 v4 复打确认**仍未修**。此窗之后 S759 若再改，结论按表内版本号取用，勿默认全时有效。


## §5 板子可信边界（给她的一句话版）

板子是**合格的"防呆"，不合格的"防假"**：它能拦住"路径写错把无输入报成成果 0"这类自己踩过的坑（三发实证拦住），拦不住"量具交回来的文案本身就是假的"——判据把量具 stdout 的一行文案当唯一真源，于是（打穿项，全部有实跑板面为证）：
1. **快照格连退出码都不看**：drift 崩了、只要它的异常文本里恰好含 `VERDICT: CLEAN` 字样（或改判据文案不改数据），板上该格就 YES；本席用一发"零业务输出、纯 traceback 泄漏"打穿。
2. **版本格看 rc 不看数**：量具被改成"逐行 DIVERGES、合计 10 处不一致"却打印 CONSISTENT＋退 0，板子无从分辨——数字行与判定行同源，一毒双杀。
3. **板与量具两个库根**：`--libs` 不转发，"建 0 座"与"扫 10 座⇒YES"能同板并存。
4. **整句判语不存在**：docstring 与板头都写着「任何一格拿不准⇒整句 NOT-ACHIEVED」，实现里没有这句——七把量具全崩（v3/v4 版板），板照出、退 0、五格仍挂 PART（"统筹更新"格没有任何量具供数也永远 PART，是不可证伪的散文格）。
5. **S759 新补三格（断开度/非代码面/名册声明源）方向正确但没多闭上多少**：三格带了 rc 腿＋数字腿，但**数字仍全部单源自身**——整件假 noncode 供全五个数照样翻 YES（#11b），假 severance 更是连"与 surface 同源互证"的自家格面承诺都不必兑现（#10）。首发 noncode-lie 被拦只是本席没编到新增字段，不是防线。散文承诺第二次在同一天变成红（第一次是本板 docstring 的"整句 NOT-ACHIEVED"）。
可信口径建议这样写：**板上的 YES/PART/NO 只对"量具文件没被人换掉"这一前提成立；对该前提本身，板子今天不设防（无哈希钉册），所以任何一格都可能被一个 rc=0 的假量具翻色——最危险的是快照格，它连 rc=0 都不用装得像。**

## §6 还原与零污染自证

- 攻击前基线（六件原件 sha256 前 16，`sha256sum` 现算）：
  `s0-main-goal-audit.py=b40b3fde1861a213411ba3108895a5d1`（记作 b40b3fde…）、
  `s0-main-lib-api-surface.py=00abd62b…`、`s0-main-lib-drift-checker.py=09f4f237…`、
  `s0-main-lib-version-check.py=1d7a4b65…`、`s0-main-unowned-edge-ranker.py=04101548…`、
  `s0-main-lib-factory.py=b4ee9fcb…`。逐发结束时台架都重印六件哈希并全数对上（见 `%TEMP%\s760-shot-*.txt` 各发 integrity 块）。
- 交卷时 `sha256sum -c` 基线：**四件 PASS；两件 FAILED＝`s0-main-goal-audit.py`（b40b3fde→71ef4ed2）与 `s0-main-lib-api-surface.py`（00abd62b→d7ef7694）**。改动者为板子 owner S759 席位本身：mtime 14:50:24/14:50:36，新版内嵌注释「S759 补三格（2026-09-26）」与三枚新量具 `s759-severance.py`/`s759-noncode.py`/`s759-decl-sources.py`（14:47–14:49 落盘）同日在场；本席台架代码里对原件**只有 read/copyfile 两种访问**（`probes/s760-adversary-board.py` 可复核），全部写入落在 `%TEMP%\s760-bench\` 副本与 `libs-sink`。据此判定为同窗他席在飞改动、如实报备不代修；为不让结论挂在过期版上，本席把全部关键攻击**在新板 71ef4ed2 上复打一轮**（v2 列，见 §2）。
- 未打真板默认路径：每发都显式 `--out` 到 bench 内（`GOAL-AUDIT-MAIN.md` 现文件未被我碰过）；surface 量具副本库根一律重定向到 sink 空目录——**`ChatBot_Libs` 全程零写入**（surface 直跑实写计数=0，见 surface-vacuous 发详情行）。
- 仓树卫生：本席未跑 pytest/全量套件；台架带 `-B`＋`PYTHONPYCACHEPREFIX=%TEMP%\s760-bench\pyc`＋`PYTHONDONTWRITEBYTECODE=1`。交卷时现算 `probes/__pycache__` 存在，但内含两枚 `s749-*.cpython-312.pyc`（mtime 15:03，S749 席直跑产物，非本席——本席台架的缓存全部落在 bench 内）；按台账 #1 规程应由安静窗统一备份 %TEMP% 后清理，本席不代删他席产物。本席写面仅 `probes/s760-adversary-board.py`＋本报告。
- **交卷时最新版复核（本席打完全部发之后的现读，非注毒）**：板子又前进到 `9700ba3f…`，但快照行仍为 `{'YES' if verdict == 'CLEAN' else 'NO'}`（无 `rc_d` 腿）、版本行仍为 `ver_verdict == 'CONSISTENT' and rc_v == 0`（有 rc 腿、无 `不一致 N 处` 数字腿）——即 §2 的 #2/#3/#4/#5 四类打穿在**当下现版依旧成立**，不是打在已被修掉的旧版上。断开度行的「与 surface 格同源互证」在 9700ba3f 仍无对应比较语句（#10 亦未修）。C1–C4、C6、C8 因此全部仍待落地。

done: yes
