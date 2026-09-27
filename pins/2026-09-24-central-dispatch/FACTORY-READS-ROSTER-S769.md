# S769 · 让工厂真读名册（FACTORY-READS-ROSTER）

> 席位 S769（批次 250926A-8）。任务＝①现算「要让工厂产出 S741 的 5 座」最少改哪几处（三档：必改／可不改／改了必带跟改）；
> ②工厂侧可粘贴增量（唯一真身＝`probes/s0-main-lib-factory.py`，本席已按简报授权**落码在该件本身**，其余面一律只出文本）；
> ③端到端预演只在 `%TEMP%`：S741 增量打到 taxonomy 副本 → 改后工厂 → 应产出 15 座，逐库成员枚数与守恒；
> ④零写主仓真身十库与 `ChatBot_Libs`；不 commit；注毒产物只进 `%TEMP%`。

## §〇 证据头（本席现算）

| 件 | 读数 |
|---|---|
| 预演完成时刻（UTC） | `2026-09-26T07:2x`（R0 采样 `07:20:25Z`；全程同一棵树的两次跑：首跑 `07:16Z` 数值与终跑全等） |
| HEAD | `a5226ec`（与 S741 交卷时同值——声明源未再漂） |
| `board_taxonomy.py` 真身 | sha256[:16] `a76235f025024d69`，1023 行（`wc -l` 尺）＝S741 记录值逐字节同；**真身无 `LIBRARY_TAXONOMY`/`ReleaseLibNode`（本席零落码于声明源，复跑 grep 即见）** |
| S741 增量 `%TEMP%` 副本 | 本席重跑 `probes/s741-roster-delta.py` 现打现算：sha16 `3cceb62d2116e70d`（＝S741 记录值），守恒前 `499+130+5=634`、后 `499+14+116+5=634` |
| 工厂改前 | sha16 `b4ee9fcb03dbda4e`（备份 `%TEMP%/s769/s0-main-lib-factory.pre-edit.py`） |
| 工厂改后（唯一真身，已落码） | sha16 `e0cb6055405a44e6`，519 行；逐字节回退依据＝`%TEMP%/s769/factory.increment.diff`（365 行 unified diff） |
| 静态门 | 改后工厂 ruff（`--no-cache --isolated`）统计与**改前逐类等值（8 错，全为改前既有的探针族风格项：PLW1510×4/F541/FURB192/ISC004/SIM102）＝本席净新增 0**；改前首版本席自造 2 枚（BLE001＋ISC004）已当场清掉 |
| 预演台 | `probes/s769-factory-rehearsal.py`（本席写面），全 JSON 落 `%TEMP%/s769/s769-rehearsal.json` |

复跑（本席全部读数都可自跑）：

```bash
# ① 先重打 S741 补丁副本（只写 %TEMP%/s741）
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s769-pyc" \
"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B \
.superpowers/sdd/2026-09-24-central-dispatch/probes/s741-roster-delta.py
# ② 预演台（R1 基线对照＋R2 旧锁复证＋R3 十五座＋R4 六发注毒＋R5 prune＋R6 漂移尺盲区＋R7 零写自证）
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s769-pyc" \
"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B \
.superpowers/sdd/2026-09-24-central-dispatch/probes/s769-factory-rehearsal.py
```

## §一 最少改动面三档表（必改／可不改／改了必带跟改）

现算口径：本表逐行由本席在改前工厂（sha16 `b4ee9fcb03dbda4e`，339 行）上核过取数路径，
预演实跑（§三）给每行配证据；「最少」＝除这一档外任何一行都不动也能端到端出 15 座者不列入必改。

### 甲档｜必改（不改则五座今天建不出来，或建出来是假账）——共 **6 处**，全部落在唯一真身工厂一件内

| # | 改动 | 为什么非改不可（改前工厂的反证形态） | 预演证据 |
|---|---|---|---|
| 1 | `parse_libs(text)` 一支派生尺（与 `parse_taxonomy` 同一次读文件、同一种字面量抽法） | 改前工厂只认 `BoardNode`/`FeatureNode` 两种 call，`ReleaseLibNode` 一眼不看（S741 I2 实跑＝名册无读者）| R0 冒烟＋R3 |
| 2 | 名册守卫四连：L4 形状（非字面量／成员越出 `plugins/**.py`／`kind=='board'` 手抄／slug 不过 kebab／lid·slug 重号）、L5 库 slug 撞板块命名空间、L7 库级双认领、L8 库板相撞 | 没有 L8 时「contracts 里塞一枚已被 B01 前缀罩住的件」会被静默派给两支仓＝同一字节进两支仓；没有 L5 时同名 slug 会覆写板块库目录（`out / slug` 同一命名空间）| R4 注毒五发各杀各档 |
| 3 | 归因环接 `lib_exact`（逐枚字面路径精确认领，先板块相撞判定、再名册认领、再板块前缀） | 不接则 14 枚成员永远躺在「无主 130」桶里，五座库成员恒 0 | R3 守恒 |
| 4 | L6 名册成员落空 ⇒ FATAL | 在册而不在成员宇宙（如 gitignored 件、`caliber=head` 下的未跟踪件）会被静默丢掉——「名册说 12 枚、库实发 11 枚」正是本仓反复踩的「把缺数读成没数」 | R4 幽灵路径注毒 |
| 5 | L1 对「零成员且带 `pending_seed`」的名册库放行＋诚实空仓也要 `lib_dir.mkdir` | A1/A2/A4 三座今天按字面零成员（S741 播种三态①②③）；不改 L1 则「五座一起建」当天退 2（S741 §三预警原文），且空目录下写三件套会 `FileNotFoundError` | R3 出 15 座、A1/A2/A4 各 0 成员带 pending 1 条 |
| 6 | 发册循环并两轴一条队列＋manifest `board_bid` 形状改可空＋守恒账接库轴 | 旧循环硬取 `boards[bid]["slug"]`，名册库无 bid 可套；`board_bid` 无处可填——**不拿 lid 冒充 BNN**，填 `None` 另立 `release` 块（形状先例＝`probes/s715-gate-replica.py` 的 `board_bid: str \| None`，非板块库＝None；`s727-wsm-sync.py` 的 `slug2bid.get(slug)` 本就允许 None）；旧恒等式 `已认领+无主==宇宙` 接不进库轴 14 枚 | R3 十五库 manifest 逐座回读 |

### 乙档｜可不改（现算核过：库里没有货或不换语义，本席一律未动）

- `--prune`：发册循环内按 `keep=set(members)` 逐库拔残骸，名册库进循环即自动复用，零改动（R5 实拔两枚幽灵验证）；
- `emit_pyproject` 的 `include`/`requires-python`/`dependencies` 缺省——成员全在 `plugins/**` 下，五座同构（仅 description 随甲 6 传参，板块库不传＝逐字节旧形）；
- `standalone_import_probe` 空成员样本已有 `NO-SAMPLE` 语义；`SEM_RE`/`NEVER_PIN`/`VERSION`/`planned_tag`/`SNAPSHOT-STAMP` 全轴无关；
- `MANIFEST.md` 表格只把表头「板块」改「板块/名册」（首列对名册库填 lid）；行正则消费者（`s768-version-residence.py`）按 `` `slug` `` 抓取，不依赖表头字样；
- 成员宇宙 `--caliber` 语义、`--out` 双白名单守卫、`--tie-break` 本体——一字未动（R2 无 tie 仍拦 L2 证明旧锁未放宽）。

### 丙档｜改了必带别人跟改（本席只出文本，不落码）

| 跟改面 | 今天会怎么瞎 | 证据 |
|---|---|---|
| 漂移尺 `probes/s0-main-lib-drift-checker.py` | 它只按 `parse_taxonomy` 派生板块十库走快照 ⇒ 五座新库**一列都不查**（「声明了但没人读＝假零」的库级同型）| R6 实跑：15 座目录下它只走 10 行、名册五座被走到 0 |
| `probes/s0-main-lib-api-surface.py` | 同样只派生板块库 ⇒ 新五座的跨库边不进接口面账 | 代码路径现算（第 66–79 行同一族） |
| `probes/s0-main-lib-sync-verify.py` | `BOARD_ROW_RE` 钉 `^(B\d{2}) …`；漂移尺跟随丙-1 补出 `L0/A1…` 行后它必须同步放行，否则新行被**静默不 parse**（它自己的「porcelain 整串 strip」教训同型）| 代码现算（第 62 行） |
| `probes/s747-factory-invariants.py` | 它注毒 `parse_taxonomy` 返回缓存值来驱动 main；main 现多读一支 `parse_libs` ⇒ 它的 patches 需补同名册桩（该席件自改）| 代码现算（第 293/321 行） |
| 常驻门 `tests/test_board_taxonomy_gate.py` | 三把腿（名册自洽／库级互斥＋播种三态／活性腿）本就要求与工厂**同批**落地（S741 §三），工厂这半已就位，门那半在门 owner 手里 | S741 文本＋本席 R3 后「门未动」如实账 |

**另记一枚落地面形状问题（待她裁，非本席可解）**：工厂真身住 `.superpowers/`（gitignore），
而常驻门在仓内 `tests/`——门若要复用同一支 `parse_libs` 判名册，就得让工厂件**同批入仓**
（如 `scripts/`），否则门只能自写 AST 尺＝正是本波禁的「第二份派生尺」。这是「唯一真身」与
「gitignored 工具区」的既有摩擦，本席预演不受其影响（仓外 importlib 直取）。

## §二 工厂侧增量（已落码，唯一真身＝`probes/s0-main-lib-factory.py`）

改前备份：`%TEMP%/s769/s0-main-lib-factory.pre-edit.py`（sha16 `b4ee9fcb03dbda4e`）。
改后工厂 sha16 `e0cb6055405a44e6`、519 行。**无第二把工厂、无第二份派生尺**：新尺 `parse_libs` 就住在工厂件内，
下游（漂移尺等）按丙档文本复用同一支。逐字节全量 diff＝`%TEMP%/s769/factory.increment.diff`；
下面是六块的落位原文（锚点＝紧邻真实行，粘贴/回退都按锚点找、不靠行号）。

### 块 1｜常量锚（`SEM_RE = …` 之后插一行）

```python
# 与板块门那把 kebab 尺同名同形（库 slug＝仓外目录名＋tag 命名空间，S741 名册纪律 K0）
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
```

### 块 2｜`parse_libs`（新函数，紧跟 `parse_taxonomy` 的 `return boards, feats` 之后）

```python
def parse_libs(text: str) -> tuple[dict[str, dict[str, object]], list[str]]:
    """AST 取 ReleaseLibNode——库轴名册的唯一派生尺（与 parse_taxonomy 同一次读文件、同一种字面量抽法）。

    返回按声明序的 ({slug: 库账}, problems)；problems 非空即名册形状违规，由 main 定夺，本件不判不修。
    字面量纪律照 S741 名册约定：kwarg 只认 Constant 或全字面串的 Tuple；缺 slug、slug 不过 kebab、
    成员越出 `plugins/**.py`、`kind=='board'`（板块库只能派生、绝不许抄进名册）都进 problems。
    声明源尚无 LIBRARY_TAXONOMY ⇒ ({}, [])——工厂回到无库轴的逐字节旧行为，不是静默半成品。
    """
    libs: dict[str, dict[str, object]] = {}
    problems: list[str] = []
    seen_lids: dict[str, str] = {}
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname != "ReleaseLibNode":
            continue
        kw: dict[str, object] = {}
        for k in node.keywords:
            v = k.value
            if isinstance(v, ast.Constant):
                kw[k.arg] = v.value
            elif isinstance(v, (ast.Tuple, ast.List)):
                try:
                    lit = ast.literal_eval(v)
                except (ValueError, SyntaxError, TypeError):
                    lit = None
                if not isinstance(lit, tuple) or any(
                        not (isinstance(x, str) or
                             (isinstance(x, tuple) and len(x) == 2 and all(isinstance(y, str) for y in x)))
                        for x in lit):
                    problems.append(f"NONLITERAL kwarg={k.arg}（Tuple 只准全字面串或字面串二元组）")
                    kw[k.arg] = ()
                else:
                    kw[k.arg] = lit
            else:
                problems.append(f"NONLITERAL kwarg={k.arg}")
                kw[k.arg] = ()
        slug = str(kw.get("slug") or "")
        lid = str(kw.get("lid") or "")
        kind = str(kw.get("kind") or "")
        if not slug:
            problems.append(f"NOSLUG lid={lid or '?'}")
            continue
        if not KEBAB_RE.match(slug):
            problems.append(f"NOT-KEBAB slug={slug}")
        if kind == "board":
            problems.append(f"KIND-BOARD slug={slug}（板块库只能由 BOARD_TAXONOMY 派生，抄进名册＝第二真身）")
        if slug in libs:
            problems.append(f"SLUG-DUP slug={slug}")
            continue
        if lid in seen_lids:
            problems.append(f"LID-DUP lid={lid}（{seen_lids[lid]} 已占）")
            continue
        if lid:
            seen_lids[lid] = slug
        members: list[str] = []
        for m in kw.get("member_paths") or ():
            ms = str(m)
            members.append(ms)
            if not (ms.startswith("plugins/") and ms.endswith(".py")):
                problems.append(f"MEMBER-SHAPE {slug}/{ms}（只准 plugins/** 下逐枚 .py 字面路径；树外件走 pending_seed）")
        for d in sorted({m for m in members if members.count(m) > 1}):
            problems.append(f"MEMBER-DUP-IN-LIB {slug}/{d}")
        seeds: list[tuple[str, str]] = []
        for pair in kw.get("pending_seed") or ():
            if isinstance(pair, tuple) and len(pair) == 2:
                seeds.append((str(pair[0]), str(pair[1])))
            else:
                problems.append(f"PENDING-SEED-SHAPE {slug}（须为 (落点或 none, 理由) 二元组）")
        libs[slug] = {
            "lid": lid or slug,
            "label": str(kw.get("label") or ""),
            "slug": slug,
            "kind": kind,
            "channel": str(kw.get("channel") or ""),
            "members": sorted(set(members)),
            "pending_seed": seeds,
        }
    return libs, problems
```

### 块 3｜main 读取改一处＋守卫三连（锚：`boards, feats = parse_taxonomy(...)` 一段）

原一行 `boards, feats = parse_taxonomy(tax.read_text(encoding="utf-8", errors="replace"))` 改为同一次读入：

```python
    tax_text = tax.read_text(encoding="utf-8", errors="replace")  # 板块账与库轴名册共用同一次读取
    boards, feats = parse_taxonomy(tax_text)
    if not boards or not feats:
        print(f"FATAL: 派生到 boards={len(boards)} features={len(feats)}（尺自身失效，不下结论）", file=sys.stderr)
        return 2
    libs, lib_problems = parse_libs(tax_text)
    if lib_problems:
        print(f"FATAL L4 名册形状违规 {len(lib_problems)} 处（不猜、不修、不降级）：", file=sys.stderr)
        for x in lib_problems[:10]:
            print("  " + x, file=sys.stderr)
        return 2
    slug_clash = sorted(set(libs) & {v["slug"] for v in boards.values()})
    if slug_clash:
        print(f"FATAL L5 库 slug 撞板块命名空间：{slug_clash}（仓外库根目录与 tag 空间必须不相交）", file=sys.stderr)
        return 2
    lib_exact: dict[str, str] = {}
    lib_cross_dup: list[str] = []
    for slug, lib in libs.items():
        for p in lib["members"]:
            if p in lib_exact:
                lib_cross_dup.append(f"{p}（同在 {lib_exact[p]} 与 {slug}）")
            else:
                lib_exact[p] = slug
    if lib_cross_dup:
        print(f"FATAL L7 库级双认领 {len(lib_cross_dup)} 枚（一支文件只准进一支仓）：", file=sys.stderr)
        for x in lib_cross_dup[:10]:
            print("  " + x, file=sys.stderr)
        return 2
```

### 块 4｜归因环接库轴＋L8/L6（锚：`claims: dict[str, list[str]] = {b: [] for b in boards}` 起的整段循环）

```python
    lib_claims: dict[str, list[str]] = {slug: [] for slug in libs}
    unclaimed: list[str] = []
    libboard_conflicts: list[str] = []
    for rel in sorted(tracked):
        ...（plugins/ 与 .py 两道筛不变）
        owners = [b for b, roots in board_roots.items() if longest_prefix_owner(rel, roots)]
        lib_owner = lib_exact.get(rel)
        if lib_owner and owners:
            libboard_conflicts.append(f"{rel}（名册归 {lib_owner}，板块 {','.join(sorted(owners))} 的前缀也罩住它）")
        elif lib_owner:
            lib_claims[lib_owner].append(rel)
        elif len(owners) == 1:
            claims[owners[0]].append(rel)
        elif len(owners) > 1:
            unclaimed.append(f"DUAL:{rel}->" + ",".join(sorted(owners)))
        else:
            unclaimed.append(f"NONE:{rel}")
    if libboard_conflicts:
        print(f"FATAL L8 库板相撞 {len(libboard_conflicts)} 枚（同一字节进板块库与名册库两支仓；"
              f"--tie-break 只归板块账内部，救不了这条）：", file=sys.stderr)
        ...return 2
    lost_members: list[str] = []
    for slug, lib in libs.items():
        got = set(lib_claims[slug])
        for p in lib["members"]:
            if p not in got:
                lost_members.append(f"{slug}/{p}（在册而不在成员宇宙；caliber={args.caliber}，宇宙外件须走 pending_seed）")
    if lost_members:
        print(f"FATAL L6 名册成员落空 {len(lost_members)} 枚：", file=sys.stderr)
        ...return 2
```

（`--tie-break` 体、L2 本体一字未动——R2 复证：名册在场、无 tie 时仍拦在 `FATAL L2 双认领 5 枚`。）

### 块 5｜L1 诚实空仓通道＋发册队列并两轴（锚：`empty = [b for b, m in claims.items() if not m]` 与其后的 `for bid in sorted(claims):`）

```python
    empty = [b for b, m in claims.items() if not m]
    starved = [slug for slug, lib in libs.items() if not lib_claims[slug] and not lib["pending_seed"]]
    if empty or starved:
        print(f"FATAL L1 成员为 0 的库：{empty + starved}", file=sys.stderr)
        return 2

    emission: list[tuple[str, str, list[str], dict | None]] = [
        (bid, boards[bid]["slug"], claims[bid], None) for bid in sorted(claims)
    ] + [
        (str(libs[slug]["lid"]), slug, lib_claims[slug], libs[slug]) for slug in libs
    ]
    for key, slug, members, libmeta in emission:
        lib_dir = out / slug
        lib_dir.mkdir(parents=True, exist_ok=True)  # 空仓（待播种库）也要有目录：写盘三件套不靠成员拷贝顺手建
```

（`emit_pyproject` 加第三参 `description=None`——不传时输出与旧版逐字节同形；名册库传
`"守岸人 Bot 发行库（{kind}/{lid}，成员与待播种账由库工厂从库轴名册派生）"`。
PLANNED-GIT-COMMANDS 的 commit 说明按 `libmeta` 分支为「成员自库轴名册派生」。）

### 块 6｜manifest 形状＋守恒账接库轴

```python
            "board_bid": None if libmeta else key,   # 不拿 lid 冒充 BNN；形状先例＝s715-gate-replica / s727-wsm-sync
        ...
        if libmeta:
            manifest["release"] = {
                "lid": libmeta["lid"], "label": libmeta["label"],
                "kind": libmeta["kind"], "channel": libmeta["channel"],
                "declared_members": len(libmeta["members"]),
                "pending_seed": [list(pair) for pair in libmeta["pending_seed"]],
            }
```

```python
    total_lib = sum(len(m) for m in lib_claims.values())
    dual_folded = len(dual_note)          # 只有 --tie-break 演练档才非 0（默认档双认领早已 return 2）
    board_base = total_claimed - dual_folded
    ident = f"{board_base}+{total_lib}+{none_ct}+{dual_folded}"
    holds = board_base + total_lib + none_ct + dual_folded == len(py_tracked)
```

报告行「名册库（kind…在册成员 N／待播种 M 条）」只在真零成员且带播种时缀「零成员有理由，L1 诚实空仓放行」
——首版本席把这半句无条件写给了有货的 contracts，重读输出时抓到，已改成条件缀语后复跑。

## §三 端到端预演（全在 `%TEMP%`，主仓与十座真身库零写）

| 步 | 判据 | 实跑 |
|---|---|---|
| R1 基线零行为变更 | 老工厂 vs 改后工厂，**无名册真树**、`--caliber worktree --tie-break`：逐库成员**集合**（非只数）等值 | rc 0/0，十库集合等值 `True`（B01 13／B02 54／B03 34／B04 17／B05 122／B06 91／B07 32／B08 48／B09 86／B10 7；B04/B08 含归一 5 枚中的 4+1，与 S741 §四不含归一口径 `499` 恒等）⇒ **名册不在场时本增量 inert**，她若否掉 S741 增量，工厂侧这刀零代价 |
| R2 旧锁未放宽 | 名册在场、**无** `--tie-break` | `rc=2`、拦在 `FATAL L2 双认领 5 枚`、输出目录零文件 ⇒ D-5 仍是咽喉这一事实未被本增量绕过 |
| R3 十五座 | 名册副本＋`--tie-break` | `rc=0`、库目录 **15**＝板块 10＋名册 5；逐库：`contracts 12／adapter-mail 2／adapter-qq 0／adapter-telegram 0／adapter-console 0`（后三座各带 `pending_seed 1` 条、manifest `board_bid=None`、`release.kind/channel` 齐、planned_tag `adapter-qq/v0.0.1` 式样——`0.0.1` 不在 `NEVER_PIN` 集，与十座板块库同档）；**守恒＝S741 口径逐枚相等**：`499＋14＋116＋5＝634`（恒等式行「499+14+116+5 vs 634 ⇒ 成立」；库轴成员集合与 S741 现算尺 `lib_members_match: true`；`arith_ok: true`）⇒ **不需要逐枚点名差——本就相等** |
| R4 注毒六发 | 各发独立 `%TEMP%` taxonomy 副本，各拦各档、当场返回、输出目录零文件 | L8 库板相撞／L1 零成员无理由／L5 slug 撞板块／L7 库级双认领／L6 成员宇宙外（幽灵路径）／L4 非 kebab——**六发全 rc=2、全命中目标档、全零写**（明细 §四） |
| R5 `--prune` 复用 | 向 `contracts`（名册轴）与 `ingress-protocol`（板块轴）各插一枚幽灵 `.py`，带 `--prune` 重跑同一 `%TEMP%` 目录 | 两枚均被拔除、15 座仍在、rc=0 ⇒ prune 零改动即覆盖两轴 |
| R6 漂移尺盲区 | 对 15 座演练目录跑现役 `s0-main-lib-drift-checker.py` | rc=0、`VERDICT: CLEAN`、行数 **10**、名册五座被走到 **[]** ⇒ **五座新库今天一列都不被核对**——「声明了但没人读＝假零」的快照侧同型，实锤丙档-1（修法见 §五） |
| R7 零写自证 | 十座真库 `git status --porcelain` 跑前/跑后逐库全等；主仓 porcelain 对称差 | `libs_unchanged=True`（10 库）；主仓差分 `[]`（本席产物全在 gitignored 的 `.superpowers`＋`%TEMP%`） |

新库独立可导入实测（工厂 K3 腿顺带产出的**新证据**，S741 §四 K3 当时未做）：
`adapter-mail rc=0 / OK`（两枚成员真 import 得动；`MISSING-INIT` 是装配根不在库内的如实标注，非失败）；
`contracts rc=1 / FAIL ModuleNotFoundError: plugins.bot_unified_runtime.message_context`——契约层里
有成员吃库外兄弟模块，**这正是 S754「契约族 115 条边」问题在工厂侧的第一枚实弹读数**，本席不修、如实报（断边方案在她裁）；
A1/A2/A4 无样本 `rc=-1 NO-SAMPLE`（按字面空仓，可导入性无从测起，不冒充绿）。

## §四 注毒自证（只打 `%TEMP%` 副本；六发各杀各锁）

每发＝S741 补丁副本上的一处纯文本注毒（锚点出现次数≠1 即 `FATAL` 拒绝注毒，量具自带），
工厂在改后真身＋`--tie-break` 下跑一次；判"被抓到"只认目标 FATAL 档命中＋`rc=2`＋**输出目录零文件**
（守卫必须发生在任何写盘之前——六发全过这一条）。

| 发 | 注毒内容（`%TEMP%` taxonomy 副本） | 预期档 | 实跑 |
|---|---|---|---|
| P1 | `contracts.member_paths` 追加一枚**现役被 B01 前缀罩住**的成员（受害枚从基线 manifest 现取，非手挑） | L8 库板相撞 | `rc=2` 命中，零写 |
| P2 | 表首插一枚 `ReleaseLibNode(lid='X1', slug='poison-empty', …)`——零成员**又无** `pending_seed` | L1 成员为 0 | `rc=2` 命中，零写 |
| P3 | 表首插一枚 `slug='routing-dispatch'`（撞板块 B02 目录名，带播种理由使其余档不适用） | L5 命名空间相撞 | `rc=2` 命中，零写 |
| P4 | 把 `contracts/errors.py` 同写进 `adapter-mail.member_paths` | L7 库级双认领 | `rc=2` 命中，零写 |
| P5 | `contracts` 追加 `…/contracts/__s769_ghost__.py`（盘上与宇宙都不存在） | L6 名册成员落空 | `rc=2` 命中，零写 |
| P6 | 表首插一枚 `slug='Bad_Slug'`（非 kebab） | L4 名册形状 | `rc=2` 命中，零写 |

反向对照（同一预演台内）：R1 证明**不注毒的名册缺席态**下新旧工厂输出逐库集合等值——
六发的红都只能由注毒本身引起，不是新代码天生带红。

## §五 复用面：`--prune` 与漂移尺

**`--prune`＝零改动复用（实测）**：拔残骸的判据是发册循环里的 `keep=set(members)`，名册库进同一条循环即自动覆盖；
R5 向两轴各插一枚幽灵 `.py`、带 `--prune` 重跑全部拔掉。唯一前提是必改甲-5 的 `lib_dir.mkdir`——
否则空仓在 prune 档会因目录不存在而写三件套炸 `FileNotFoundError`（本席预演前现算发现，未让它有机会咬人）。

**漂移尺＝今天瞎五座（R6 实锤：15 座目录、10 行账、`VERDICT: CLEAN`）**。可粘贴跟随文本（**只出文本不落码**；
唯一落点＝该件自身，尺一律经 `load_factory()` 复用工厂的 `parse_libs`，禁第二份派生）：

```python
# —— s0-main-lib-drift-checker.py：三处纯插入/一处替换 ——
# ① L63 附近，替换取数三行为：
    tax_text = tax.read_text(encoding="utf-8", errors="replace")
    boards, feats = f.parse_taxonomy(tax_text)
    libs_axis, lib_problems = f.parse_libs(tax_text)   # 与工厂同尺（S769 唯一真身），禁在此重写解析
    if lib_problems:
        print(f"FATAL: 名册形状违规 {len(lib_problems)} 处（与工厂 L4 同判据）", file=sys.stderr)
        return 2
# ② claims 初始化处并库轴：
    lib_claims: dict[str, list[str]] = {slug: [] for slug in libs_axis}
    lib_exact: dict[str, str] = {}
    for slug, lib in libs_axis.items():
        for p in lib["members"]:
            if p in lib_exact:
                print(f"FATAL: 库级双认领 {p}（同工厂 L7）", file=sys.stderr)
                return 2
            lib_exact[p] = slug
# ③ 归因环前插 lib_owner 分流（相撞即 FATAL，与工厂 L8 同判据）：
        lib_owner = lib_exact.get(rel)
        if lib_owner and owners:
            collide += 1
        elif lib_owner:
            lib_claims[lib_owner].append(rel)
        elif len(owners) == 1: ...（旧行不动）
#    循环后：if collide: print(f"FATAL: 库板相撞 {collide} 枚（同工厂 L8）", file=sys.stderr); return 2
# ④ 走账循环并两轴（行首键改「bid 或 lid」）：
    ledger = [(b, boards[b]["slug"], ms) for b, ms in sorted(claims.items())] + \
             [(str(libs_axis[s]["lid"]), s, ms) for s, ms in lib_claims.items()]
    for key, slug, members in ledger:
        ...（体不动；rows 行首由 bid 改 key）
```

**同批必须跟随的第二处**：`s0-main-lib-sync-verify.py` 的 `BOARD_ROW_RE = ^(B\d{2})\s…`（第 62 行）——
漂移尺补出 `L0/A1…` 行后，该行首组要放宽为 `^(?:B\d{2}|[AL]\d)\s` 或改按 `^(\S+)\s`，
否则新行被它**静默不 parse**（正是该件自己写过的「整串 strip 读错文件名」同型的哑法）。
第三处：`s0-main-lib-api-surface.py` 只按板块派生十库（第 66–79 行同族尺），名册五座的跨库边今天不进接口面账——
跟随形同 ①–④（复用 `parse_libs`），owner 在 S763/S744 线。第四处：`s747-factory-invariants.py`
注毒 `parse_taxonomy` 桩的三处 `patches={...}` 需并注 `parse_libs` 桩（该席件自改，一句话的事）。
**常驻门**（`tests/test_board_taxonomy_gate.py`）三把腿是 S741 §三已交的文本，本席不重复产出——
但注意 §一丙档末「gitignored 工厂 vs 仓内门」的第二真身抉择：**要么工厂件随名册同批入仓（`scripts/`）供门 import，
要么门只能自写 AST 尺（＝被禁的那把第二尺）**，这一裁在她。

## §六 本席没做成什么（不留已完成假象）

1. **声明源一字未动**（`grep LIBRARY_TAXONOMY` 对真身＝0，R0 现算）；S741 增量仍等她/该件 owner 落——
   没有它，工厂新支在真树上派生为空（这正是设计：R1 证明缺席态逐字节旧行为）。
2. **没建十库之外的任何真库根**：`ChatBot_Libs` 零写（R7 逐库 porcelain 等值）；所有 15 座实体只活在 `%TEMP%/s769/libs15`。
3. **未 commit、未重启、未跑全量套件、未动 `--tie-break`/L2/D-5 那把咽喉**（FLEET 记 D-5 窄化补丁"待落"，落谁手不在本席）。
4. **contracts 的库外 import 洞（R3 K3 实弹）未修**——`domains/core/contracts/*` 吃 `plugins.bot_unified_runtime.message_context`
   一类库外兄弟，属 S754 的 115 条边归属题，修法是断边/带依赖而非工厂侧掩盖。
5. **本席自己的两处首版错，抓到并改掉**：①预演台首版把「恒等式行」从 stdout 里找（它只进 `FACTORY-REPORT.md`），
   提数口拿错——改读报告件后复跑；②改后工厂首版把「零成员有理由」无条件缀给所有名册库（有 12 枚货的 contracts 也被缀上）——
   重读自家输出抓到，改成条件缀语，并全量重跑 R1–R7。两处均未流到任何真面。
6. **`--out` 守卫的一处既有小刺（非本席引入、未代修）**：工厂在**校验 `--out` 白名单之前**就 `out.mkdir(...)`，
   非法 `--out` 会留下一个空目录才退 2。行为无害（零文件），归工厂该面 owner 一并裁；本席只照实登记。
7. 卫生自证：全程 `PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=%TEMP%/s769-pyc`
   ＋`-B`；仓树内零 `import plugins...`（装载判定全走 AST/子进程副本）；源码树本席窗口零新增 `__pycache__`（见 §〇 复跑后自查）。

## §七 总裁决与还剩什么

**总裁决**——「工厂读名册」这枚第二阻断已解：最少 6 处必改全部落在唯一真身 `probes/s0-main-lib-factory.py`
（`parse_libs` 一支尺／L4–L8 五档守卫／归因接库轴／L6 落空即死／L1 播种豁免＋空仓 mkdir／发册并轴＋
`board_bid=None`＋库轴守恒账），可不改者（prune、semver、宇宙尺、tie-break、L2）一律未动，
改了必带跟读者（漂移尺/api-surface/sync-verify 正则/s747 桩/常驻门）全出文本不落码。
端到端预演实跑：**15 座（10＋5）建成、成员逐库 `12/2/0/0/0`、恒等式 `499＋14＋116＋5＝634` 成立**，
与 S741 口径逐枚相等（无需点名差集）；注毒六发各拦各档且零写；十座真身库与主仓逐字节零写自证在案；
名册缺席时新旧工厂输出集合等值＝**她若暂不裁 S741 增量，本刀零代价可回退**（备份＋diff 在 `%TEMP%/s769`）。

**还剩**：①她把 S741 声明源增量＋工厂这一刀＋常驻门三把腿**同批**裁落（不同批＝名册无读者或门无判据）；
②D-5 双认领窄化落地（否则正式建库仍拦 L2——本席不绕）；③漂移尺/api-surface/sync-verify 的跟随文本落码者按 §五 执行；
④工厂真身入仓与否（`scripts/`？）与门侧「第二把尺」风险的裁定；⑤A1 让位、A2 搬家授权、A4 三案照旧等她。

done: yes
