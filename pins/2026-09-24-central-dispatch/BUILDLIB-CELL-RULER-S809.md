# BUILDLIB-CELL-RULER-S809 — 「各建 git 库」与「统筹管理版本号」两格真判化（逐座五腿尺）

席位 S809（批次 250926A-B3）。写面：`probes/s809-buildlib-per-lib.py`、`probes/s809-selftest.py`、本件。
审计板与一切尺件真身**零改动**（板侧接线只交可粘贴片段，落板权在板 owner）。

## 一、病与方（一句话）

板（`probes/s0-main-goal-audit.py`，本席现读）两格是手写 PART：
「按一级分类各建 git 库」＝`'PART' if built else 'NO'`（built 只数盘上 `.git` 是**目录**的座数）、
「统筹管理版本号」＝`PART if have_manifest else 'NO'`——两格都不对 15 座在册名册逐座负责。
本席出一把逐座尺：`在册 slug ⇒ 目录在 ⇒ 已 git init ⇒ 带 manifest ⇒ 版本三处一致 ⇒ range 政策在册`，
任一腿缺 ⇒ 该座点名、整体落 NO；YES 只给「在册 ⇒ 逐座全腿」。

## 二、判据定义（全部现算，无手写数）

- **名册（在册）**：与 `s759-decl-sources.py` 同缝两路派生，不抄清单——10 座板块 slug
  （`board_taxonomy.py` 的 BoardNode.slug，经工厂 `parse_taxonomy` AST）＋ 5 座非板块 slug
  （`s715-deps.py::NONBOARD_ROOTS` 键名）；派生 ≠15、有重复、板块或非板块任一为 0 ⇒ **FATAL rc=2**（口径变了＝量具该改，不与缺口账混报）。
- **目录在**：`<库根>/<slug>` 是目录。
- **已 git init（含本窗踩过的坑）**：`.git` **目录形与 gitdir 指针文件形都收**——板侧 `built` 用 `.is_dir()`
  会把指针形真库判成没 init；指针文件还要求首行 `gitdir:` 形态、目标存在（否则 `GIT-POINTER-BAD`），
  两形统一再过一发 `git rev-parse --is-inside-work-tree` 真验。
- **带 manifest**：`workspace-lib.manifest.json` 在场且能解析成 JSON 对象。
- **版本三处一致**：`VERSION` 文本 == `manifest["version"]` == 存在 tag `<slug>/v<VERSION>`。
  与旧尺 `s0-main-lib-version-check.py` 的一处**刻意差异**：旧尺拿 `tags[0]` 比对，库 bump 第二版后
  旧 tag 按字母序打头会把 SAME 判成 DIVERGE；本尺判「当前版本的 tag 存在」。今日两尺对同十座的
  判定结果一致（每座恰一枚 tag），差异只在 bump 之后生效——板侧版本格仍归 version-check 家判，本尺腿只吃「三处是否一致」这一语义。
- **range 政策在册**：策略值读 ②声明源真身 `probes/s727-wsm-decl.py::RANGE_POLICY`，解析序＝slug 显式条目
  优先、缺省落 `"*"` 通配；**合法词表不手抄**——拿 `s727-wsm-sync.py::derive_range` 探测（表外值它生成期拒，
  本尺即判 `RANGE-TABLE-OUT`）。声明源/生成器读不到 ⇒ 逐座该腿 fail-closed 点名（禁「读不到＝都通过」）。
- **计数口径（写死）**：每列＝「该腿不成立的在册座数」；缺目录的座其后三腿（git/manifest/version）物理无从成立，
  **按不成立计数**并行内标 `NA:DIR-MISSING`（这就是「抓不到⇒判 NO」的逐座形态）；range 腿与盘无关不受级联影响。

## 三、机读接口

逐座一行：
`LIB <slug>\tD=…\tG=…\tM=…\tV3=…\tR=…\t=> ALL-OK | BAD:<缺的腿,逗号分隔>`
汇总（简报要求的原式 + 两枚辅助机读行）：

```
BUILDLIB per=<座数> missing_dir=<n> not_git=<n> no_manifest=<n> ver_bad=<n> no_range_policy=<n>
BUILDLIB all5=<全腿座数> gap_names=<逗号分隔缺腿座|none>
BUILDLIBX extra_git_dirs=<n> names=<盘上有.git却不在名册的目录名|none>
VERDICT: YES|NO
```

退出码：0＝逐座全腿；1＝有腿缺（NO，逐座点名）；2＝尺瞎（FATAL）。

## 四、🔴 零测即 FATAL 自锁 + 注毒有牙实录

尺瞎路径（名册派生 0／≠15、库根不存在、库根下无任何子目录、库根落进主仓工作树、尺自身崩溃）
一律 **rc=2、只写 stderr（含「别把没扫到报成没问题」）、stdout 一个字不出**——裁决词更无处可出。
验牙台 `probes/s809-selftest.py`（只写 %TEMP%，真仓真库根零写入）实跑 **12/12 PASS**（UTC 2026-09-26 08:4x）：

```
[PASS] S0-positive  rc=0 counts={'per': 15, 'missing_dir': 0, ..., 'no_range_policy': 0} verdict=YES
[PASS] S1-empty-libroot  rc=2 stderr含字句=True stdout纯净=True｜stdout前40字=''
[PASS] S2-missing-libroot rc=2 stderr含字句=True stdout纯净=True｜stdout前40字=''
[PASS] S3-roster-zero    rc=2 …（--tax 注毒派生 0 座）
[PASS] S4-roster-not15   rc=2 …（--tax 注毒派生 14 座）
[PASS] S5-strip-dotgit   not_git=1 ver_bad=1 missing_dir=0
[PASS] S6-gitdir-pointer 指针文件形真库（git init --separate-git-dir）仍全腿 OK ←本窗踩过的坑的反向锁
[PASS] S7-pointer-broken GIT-POINTER-BAD 点名，not_git=1 ver_bad=1
[PASS] S8-no-manifest    no_manifest=1 ver_bad=1
[PASS] S9-version-bump-untagged ver_bad=1，行内 NO-TAG(<slug>/v0.0.2)
[PASS] S10-range-out-of-table   banana 落表外 ⇒ no_range_policy=1 且点名该座（词表拿真身 derive_range 探）
[PASS] S11-range-no-wildcard    删 "*" 通配只留一枚显式 ⇒ no_range_policy=14
SELFTEST checks=12 passed=12 failed=0 ／ SELFTEST VERDICT: PASS
```

复跑：`<venv-py> -B probes/s809-selftest.py`（收尾自动删 %TEMP% 夹具）。

## 五、可粘贴接线片段（板侧两格怎么吃这把尺）

前提（板 owner 亲笔，两行缺一不可——`run()` 对未入钉册的尺直接 rc=99）：

```python
# ① SOURCES 字典加一键：
    "buildlib": "s809-buildlib-per-lib.py",   # S809 逐座五腿尺：「各建 git 库」「统筹版本号」两格真判化
# ② PINNED_GAUGES 块加一行（2026-09-26 08:46Z 本席交卷现算 sha256；此后如再改版走 --repin --reason）：
    "s809-buildlib-per-lib.py": "39f03cc532d78f05694ad8cc6288f2c6780e1d549293a5afc78180d6ecab2b3f",
```

取数与两格判定（贴在既有 `rc_ou, out_ou = run("outside", [])` 之后；
替换表里那两行手写 PART——**分母裁定＝roster（per，名册派生），不是盘上 built**，built 降为展示值）：

```python
    rc_bl, out_bl = run("buildlib", LIBARG)
    bl_per  = num(grab(out_bl, r"BUILDLIB per=(\d+)"))
    bl_md   = num(grab(out_bl, r"missing_dir=(\d+)"))
    bl_ng   = num(grab(out_bl, r"not_git=(\d+)"))
    bl_nm   = num(grab(out_bl, r"no_manifest=(\d+)"))
    bl_vb   = num(grab(out_bl, r"ver_bad=(\d+)"))
    bl_nr   = num(grab(out_bl, r"no_range_policy=(\d+)"))
    bl_ver  = grab(out_bl, r"VERDICT: (\w+)")
    bl_gaps = grab(out_bl, r"gap_names=([^\n]*)")
    # 两尺互证（F3 同型）：本尺名册派生必须等于 s759 声明源尺的在册数，不等＝其中一把口径漂了
    bl_xr = (bl_per is not None and num(de_ros) == bl_per)
    # 腿的级联是判据的一部分：not_git/no_manifest/ver_bad 含缺目录座（尺 docstring 写死），
    # 所以「各建 git 库」看 dir+git 两列、「统筹版本号」看 manifest+version+range 三列，
    # 两格各自数字腿齐＋rc=0＋VERDICT 词在场才许 YES——缺一腿即 NO，禁「抓不到＝没问题」。
    buildlib_cells_j = ("NO" if (rc_bl != 0 or not bl_xr or None in (bl_per, bl_md, bl_ng, bl_nm, bl_vb, bl_nr)
                                 or bl_per != ROSTER_EXPECT) else
                        ("YES" if (bl_md == 0 and bl_ng == 0) else "NO"))
    versiongov_j = ("NO" if (rc_bl != 0 or not bl_xr or None in (bl_per, bl_md, bl_ng, bl_nm, bl_vb, bl_nr)
                             or bl_per != ROSTER_EXPECT) else
                    ("YES" if (bl_nm == 0 and bl_vb == 0 and bl_nr == 0) else "NO"))
```

表里两行改为（放在既有 f-string 表行区，替掉原 `{'PART' if built ...}` / `{'PART' if have_manifest ...}` 两行）：

```python
    f"| 按一级分类各建 git 库 | 名册（两路派生＝{ROSTER_EXPECT}）逐座〔目录在 ∧ 已 git init（.git 目录形或 gitdir 指针形均收＋rev-parse 真验）〕，且与 s759 名册尺互证相等；尺 rc=0 | 在册 {bl_per}／git 腿不成立 {bl_ng}（其中缺目录 {bl_md}）／盘上 built={built}（展示值，非分母）／缺腿座＝{bl_gaps or '?'} | {buildlib_cells_j} |",
    f"| 统筹管理版本号 | 名册逐座〔带 manifest ∧ 版本三处一致 ∧ range 政策在册（词表拿 wsm-sync.derive_range 探）〕；尺 rc=0 | manifest 不成立 {bl_nm}／三处不一致 {bl_vb}／range 不在册 {bl_nr}（尺整体 `{bl_ver}`） | {versiongov_j} |",
```

要点：
- `ROSTER_EXPECT = 15` 板内以常量登记一次并注明真身＝尺内两路派生（尺里 ≠15 即 FATAL，板里的值只用于互证，不当第二个分母）。
- 本尺 `VERDICT: YES` ⇔ 两格同 YES（级联设计下五列全 0 与两格条件等价）——可加一行派生自检：
  `(bl_ver == "YES") == (buildlib_cells_j == versiongov_j == "YES")`，不成立即双 NO（尺与板算不同形＝有谁在漂）。
- `built` 那行盘扫代码可留给其余格当展示/交叉值；它带 `.is_dir()` 的指针形盲区属板件既有病，
  归板 owner（S799 在补尺侧零测锁同型事），本席不代改板。

## 六、今值（本席 2026-09-26 08:4xZ 现算，当时值）

真跑 `probes/s809-buildlib-per-lib.py`（真名册＋真库根只读）：

```
BUILDLIB per=15 missing_dir=5 not_git=5 no_manifest=5 ver_bad=5 no_range_policy=0
BUILDLIB all5=10 gap_names=adapter-console,adapter-mail,adapter-qq,adapter-telegram,contracts
BUILDLIBX extra_git_dirs=0 names=none
VERDICT: NO   （rc=1）
```

- **15 在册／10 全腿建成／5 缺**。缺的五座＝五枚非板块 slug，**第一腿就缺（目录不在）**；
  按级联口径其 git/manifest/version3 三腿同样不成立（行内 `NA:DIR-MISSING`），range 腿五座全在册。
- 10 座板块库：`.git` 全为目录形（`OK(DIR)`）、manifest 可解析、版本 SAME3、range OK(same-major) ⇒ 全腿。
- range 政策现值：声明源里只一枚通配条目 `"*": "same-major"` ⇒ 15/15 可解析且词表合法（`no_range_policy=0`）。
- `extra_git_dirs=0`：盘上没有名册外的幽灵库。
- 附带观察（不归本席、只如实报）：`ChatBot_Libs/render-outbound` 工作树现带 ` M api-surface.json`
  存量脏（早于本窗、历史 surface --write 波留下），本席全程只读未触碰。

## 七、本席自曝账

- **首版直跑即崩**（`LABELS` 元组解包序写反 ⇒ KeyError）：被尺自己的崩溃兜底抓住——rc=2、stderr 含字句、
  stdout 零输出，没留半截裁决。这正是 S785 那发 UnboundLocalError 教的纪律落地为码，修后复跑全绿。
- 验牙台第一轮 S6/S7/S9 三发夹具自身写错（既有目录 mkdir 不容错、往 .git 目录 write_text、bump 只抬一边撞 DIVERGE 非 NO-TAG）——
  全部是**检查台的错**被检查台自己现形，非尺的错；修正后 12/12，无一处放宽断言。

## 八、边界与未做

- 本尺**不接板**（板写面归主代理，简报明令「禁改审计板」）；上面片段是交给他的成品。
- 「盘上非空但指错路」的盲区（路径写对格式、底下有别的目录）与板 `built` 同型存在，尺以 FATAL 兜了
  「指空/不存在/在仓内」三种，剩一种如实标——要再封，得让库根来自登记而非命令行手输，未做。
- range 腿判「可解析＋词表合法」，**不判策略内容对不对**（same-major 是不是她要的每库政策，归她裁，不归尺）。
- 版本腿语义与 version-check 尺的 bump 差异（§二）若她裁「两尺必须逐字同形」，改哪一侧都是她一句话的事。

## 九、复跑命令簿（本席全部证据可复跑）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX="$TEMP/s809-pyc"
PY="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"
# 真跑（只读）：期望 rc=1、五列 5/5/5/5/0、VERDICT: NO
"$PY" -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s809-buildlib-per-lib.py
# 验牙（%TEMP% 沙盒）：期望 rc=0、checks=12 passed=12
"$PY" -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s809-selftest.py
# lint（两新件）：All checks passed!
"$PY" -m ruff check --no-cache .superpowers/sdd/2026-09-24-central-dispatch/probes/s809-buildlib-per-lib.py .superpowers/sdd/2026-09-24-central-dispatch/probes/s809-selftest.py
```

交卷件 sha256（现算 08:46Z）：`s809-buildlib-per-lib.py`＝`39f03cc532d78f05694ad8cc6288f2c6780e1d549293a5afc78180d6ecab2b3f`；
`s809-selftest.py`＝`f55e9a4e5b8f3f298cc0a8cc060a66b121ee5a184651de0245a353f4a211708f`。

## 十、安全台账（AGENTS 规则 11）

本席全程读过的简报/板/尺件/夹具/设计文档与全部工具结果中，**未遇到任何祈使句形态的可疑载荷**
（含伪装"系统规则/IMPORTANT/调用某技能"形态）＝命中 0；无需取证条目。
窗口内两条「MEMORY.md／s0-main-goal-audit.py 被并发修改」的提示为宿主文件变更通知，属同树他波在飞，非注入；
本席对二者零写入（板文件本席只读过原文）。

done: yes
