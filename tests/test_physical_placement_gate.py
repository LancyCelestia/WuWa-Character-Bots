"""物理归位门 G-P1 / G-P2（2026-09-22 规格统一波，席 T-GP-IMPL 立）。

两扇门的判据（用户原话，不许缩水）：

- **G-P1**：每个二级功能声明的 `impl_paths` 必须落在**它自己声明的** `domains/<domain>/**`
  白名单内；越界 / 未登记域 / 被两个功能同时认领 ⇒ 红。
  "自己声明的白名单"= 该功能自己的 `impl_paths` 落进的那些 `domains/<d>`（跨域功能天然得到
  两枚白名单，不需要新字段——本席被明令**只准改 `impl_paths` 声明、不动 `FeatureNode` 结构**）。
- **G-P2**：`plugins/**` 与仓库根下任何 `.py` 未被任何二级功能 `impl_paths` 认领 ⇒ 红；
  豁免清单必须是**枚举的字面路径**（不许通配符兜底）。未认领与违规两笔账**只准降不准升，终态 0**。

成熟骨架（本仓踩出来的六件套，照抄没自创）：
① 单一取数口 `scripts/physical_placement_census.py`（违规、总数、`--report` 三处同源）；
② 上限是手写字面量 + AST 自锁（同时走 `ast.Assign` 与 `ast.AnnAssign`）；
③ 方向锁 AUDIT_HISTORY（首行=本席开工现算，命令见各行注释）；
④ 扫描面地板 + "命中非空"（一条都没数到＝取数口坏了，不是大家都归位了）；
⑤ 反向自证全部走**内存合成数据**（判据收参数），不往源码树写一个字；
⑥ 语义 A（目录前缀）/ 语义 B（字面文件）双实现成参数，门的判据用 A，并锁死两者之差有限。

**本门的限缩（读绿之前先记住）**：G-P2 是**存在性**判据（有没有被认领），不是活性判据
（认领得对不对）。159/160 枚未认领里 **87 枚是旧顶层残留**（含 49 枚 `_CANONICAL` 退役垫片），
它们要**退役或改道**、不该豁免——本席因此只豁免 ORPHAN-MAP §5-A/B 的 29 枚结构性件，
§5-C 的 13 枚"无机械归主"照原样计入违规并标 `待用户裁`。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import physical_placement_census as pc  # 唯一取数口（判据 / 总数 / --report 三处同源）

# --------------------------------------------------------------------------
# 手写字面量上限（只准降）。迁一批 / 改一批声明后调小，并在对应 AUDIT_HISTORY 追加一行。
# --------------------------------------------------------------------------
#: G-P1 ①越界声明点数。2026-09-22 本席现算：
#: `PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --report`
#: ⇒ ①越界 36（与 ORPHAN-MAP §4.1 的 36 逐条同集合）。
G_P1_OUTSIDE_CEILING = 36
#: G-P1 附账：目录认领套住别的 fid 认领的"包含对"（影子认领＝归属含糊，只准降）。
G_P1_CONTAIN_CEILING = 19
#: G-P2 语义 A 未认领数（**真债**，不受豁免影响，终态 0）。
#: 本席现算 160 = ORPHAN-MAP 的 159 + 1，多的那一枚是本席新建的
#: `plugins/bot_unified_runtime/domains/core/board_placement.py`（声明数据件，同样未认领，
#: 本席**不给自己开后门**：不豁免、不自认领，如实进账，由后续迁移批归主）。
G_P2_UNCLAIMED_CEILING = 160
#: G-P2 违规数 = 未认领 ∧ 未豁免（终态 0）。本席现算 131 = 160 − 29 枚 §5-A/B 豁免。
G_P2_VIOLATION_CEILING = 131
#: G-P2 豁免条数：豁免即债账，**只准降**（摘一条就改小此数并追加历史）。
G_P2_EXEMPT_CEILING = 29

#: 扫描面地板：现算 655（plugins 654 + 根 1）。低于此＝扫描面塌陷，不是"大家都归位了"。
MIN_SCANNED_PY_FILES = 600
#: 板块树规模地板（现算 57 个二级功能 / 94 个声明点）——防有人删声明源把账做没。
MIN_FEATURES = 50
MIN_CLAIMS = 90

AUDIT_HISTORY_G_P1_OUTSIDE: tuple[tuple[str, int], ...] = (("2026-09-22", 36),)
AUDIT_HISTORY_G_P1_CONTAIN: tuple[tuple[str, int], ...] = (("2026-09-22", 19),)
AUDIT_HISTORY_G_P2_UNCLAIMED: tuple[tuple[str, int], ...] = (("2026-09-22", 160),)
AUDIT_HISTORY_G_P2_VIOLATION: tuple[tuple[str, int], ...] = (("2026-09-22", 131),)
AUDIT_HISTORY_G_P2_EXEMPT: tuple[tuple[str, int], ...] = (("2026-09-22", 29),)

#: AST 自锁要盯的字面量名（上限不许写成 len(...)/sum(...) 派生）。
_CEILING_NAMES = (
    "G_P1_OUTSIDE_CEILING",
    "G_P1_CONTAIN_CEILING",
    "G_P2_UNCLAIMED_CEILING",
    "G_P2_VIOLATION_CEILING",
    "G_P2_EXEMPT_CEILING",
    "MIN_SCANNED_PY_FILES",
    "MIN_FEATURES",
    "MIN_CLAIMS",
)
_HISTORY_NAMES = (
    "AUDIT_HISTORY_G_P1_OUTSIDE",
    "AUDIT_HISTORY_G_P1_CONTAIN",
    "AUDIT_HISTORY_G_P2_UNCLAIMED",
    "AUDIT_HISTORY_G_P2_VIOLATION",
    "AUDIT_HISTORY_G_P2_EXEMPT",
)

_REAL = pc.compute()  # 全模块只现算一次（判据与 report 同一支）


# --------------------------------------------------------------------------
# G-P1
# --------------------------------------------------------------------------
def test_g_p1_impl_paths_never_escape_own_domain_whitelist() -> None:
    findings = _REAL["g_p1"]["outside_domain"]
    assert len(findings) <= G_P1_OUTSIDE_CEILING, (
        f"越界声明点 {len(findings)} > 上限 {G_P1_OUTSIDE_CEILING}＝又长了落在 domains 之外的新认领。"
        f"修法：把实现放进 `domains/<域>/<层>/` 再声明；确属工程面（docs/scripts/tests）的新条目"
        f"要么改道、要么走用户裁进 `board_placement.G_P1_EXEMPT`（大户："
        f"{[(f, p) for f, p in findings][:6]}）"
    )
    # 命中非空：一条越界都没数到而账上还有 36 个额度＝取数口坏了（本仓的"空跑门"教训）
    assert findings, "G-P1 一个越界都没数到，但基线是 36——取数口对越界失明"


def test_g_p1_hard_zero_classes_stay_zero() -> None:
    findings = _REAL["g_p1"]
    assert not findings["double_claim"], f"同一字面路径被两个 fid 认领（无条件红）：{findings['double_claim']}"
    assert not findings["duplicate_within"], f"同一功能内重复声明：{findings['duplicate_within']}"
    assert not findings["unknown_domain"], (
        f"impl_paths 指向未登记的域根（现役 21 枚以 `domains/` 目录派生为准）：{findings['unknown_domain']}"
    )
    assert not findings["empty_dir_claims"], (
        f"包内目录形声明覆盖 0 个 py＝空认领（洗账通道）：{findings['empty_dir_claims']}"
    )
    assert not findings["banned_claims"], (
        f"拿包根当认领声明＝一把吞掉全仓、门自毁：{findings['banned_claims']}"
    )


def test_g_p1_containment_ledger_never_grows() -> None:
    pairs = _REAL["g_p1"]["contain_pairs"]
    assert len(pairs) <= G_P1_CONTAIN_CEILING, (
        f"包含对（目录认领套住别的 fid 的认领）{len(pairs)} > 上限 {G_P1_CONTAIN_CEILING}。"
        f"影子认领＝归属含糊，新增必须先把粒度统一到同一层：{pairs[:6]}"
    )
    assert pairs, "包含对基线是 19 却一条没数到＝归因逻辑瞎了"


# --------------------------------------------------------------------------
# G-P2
# --------------------------------------------------------------------------
def test_g_p2_unclaimed_debt_never_grows() -> None:
    counts = _REAL["counts"]
    assert counts["scanned_py"] >= MIN_SCANNED_PY_FILES, (
        f"只扫到 {counts['scanned_py']} 个 py（地板 {MIN_SCANNED_PY_FILES}）＝扫描面塌陷"
    )
    assert counts["features"] >= MIN_FEATURES, f"二级功能只剩 {counts['features']} 枚＝声明源被掏空"
    assert counts["claims"] >= MIN_CLAIMS, f"声明点只剩 {counts['claims']} 条＝声明源被掏空"
    unclaimed = _REAL["g_p2_semantic_a"]["unclaimed"]
    violations = _REAL["g_p2_semantic_a"]["violations"]
    assert unclaimed <= G_P2_UNCLAIMED_CEILING, (
        f"未认领 py {unclaimed} > 上限 {G_P2_UNCLAIMED_CEILING}＝新文件没人认领。"
        f"修法：在 `board_taxonomy.py` 对应二级功能补 `impl_paths`（终态 0，不许拿豁免抵数）。"
        f"新增大户：{_REAL['a_unclaimed_list'][-6:]}"
    )
    assert violations <= G_P2_VIOLATION_CEILING, (
        f"未认领且未豁免 {violations} > 上限 {G_P2_VIOLATION_CEILING}（终态 0）。"
        f"未豁免的债：{_REAL['a_violation_list'][-6:]}"
    )
    assert violations and unclaimed, "一条都没数到＝取数口坏了，不是'大家都归位了'"
    # 未认领 ⊇ 违规，且差值恰等于"豁免真正吞掉的未认领枚数"（三处同源，不许各算一套）
    assert unclaimed - violations == len(set(_REAL["a_unclaimed_list"]) - set(_REAL["a_violation_list"]))


def test_g_p2_exemptions_are_literal_existing_and_still_needed() -> None:
    placement = pc.load_placement()
    entries = [tuple(e) for e in placement["G_P2_EXEMPT"]]
    paths = [p for p, _r in entries]
    assert len(entries) <= G_P2_EXEMPT_CEILING, (
        f"豁免 {len(entries)} 条 > 上限 {G_P2_EXEMPT_CEILING}＝拿豁免把债搬家；只准降"
    )
    assert len(set(paths)) == len(paths), f"豁免清单有重复条目：{sorted(p for p in set(paths) if paths.count(p) > 1)}"
    # ① 形状：枚举字面路径，禁通配符 / 正则 / 目录兜底（用户原话："通配＝等于没门"）
    shape = pc.exemption_shape_errors(entries)
    assert not shape, f"豁免清单形状违规（必须字面 .py/.md 路径，禁 * ? [] \\ 目录兜底）：{shape}"
    # ② 每条仍真实存在（stale 即红——media 门"欠款仍真锁"同型）
    stale = _REAL["stale_exempts"]
    assert not stale, f"这些豁免指向不存在的路径（假豁免）：{stale}"
    # ③ 每条仍然必要：被豁免的东西必须当前确实未认领，否则是"死豁免"白占额度
    dead = _REAL["dead_exempts"]
    assert not dead, f"这些豁免对象其实已被认领＝死豁免，请删除并降 G_P2_EXEMPT_CEILING：{dead}"
    # ④ 每条带一句"为什么"
    no_reason = [p for p, reason in entries if not str(reason).strip()]
    assert not no_reason, f"豁免条目缺理由：{no_reason}"


def test_g_p2_root_py_is_on_the_books() -> None:
    """"根 py 在册"专锁：整根漏扫时，本条先红（ORPHAN-MAP §5-B 的 root 件）。"""
    claims = {path for _fid, path in pc.flatten_claims(pc.feature_impl_paths())}
    exempt = {path for path, _r in pc.load_placement()["G_P2_EXEMPT"]}
    roots = [p.name for p in REPO_ROOT.glob("*.py")]
    assert "bot.py" in roots, f"仓库根 py 扫到的是 {roots}——根面漏扫"
    unaccounted = [name for name in roots if name not in claims and name not in exempt]
    assert not unaccounted, f"仓库根 py 既没被认领也没被枚举豁免：{unaccounted}"


def test_report_and_gate_read_the_same_numbers() -> None:
    """单一取数口自证：`--report` 打印的每个数必须等于本门判据用的同一个现算值。"""
    lines = "\n".join(pc.report_lines(_REAL))
    size = _REAL["g_p1_size"]
    a, b = _REAL["g_p2_semantic_a"], _REAL["g_p2_semantic_b"]
    assert f"①越界 {size['outside_domain']}" in lines
    assert f"附账:包含对 {size['contain_pairs']}" in lines
    assert f"未认领 {a['unclaimed']} / 违规 {a['violations']}" in lines
    assert f"未认领 {b['unclaimed']} / 违规 {b['violations']}" in lines
    assert f"扫描 py（plugins/** + 根）: {_REAL['counts']['scanned_py']}" in lines


def test_two_claiming_semantics_are_both_computed_and_gap_is_bounded() -> None:
    """语义 A / B 都实现成参数，门的判据用 A；把两者之差钉成有限数并打印——
    否则将来有人"改用字面文件语义"就能把账做成 626，或反向用通配吞掉一切。"""
    claims = pc.flatten_claims(pc.feature_impl_paths())
    universe = pc.py_universe()
    exempt = {path for path, _r in pc.load_placement()["G_P2_EXEMPT"]}
    a = pc.gp2_findings(claims, universe, exempt, semantic="prefix")
    b = pc.gp2_findings(claims, universe, exempt, semantic="literal")
    assert len(a["unclaimed"]) == _REAL["g_p2_semantic_a"]["unclaimed"], "A 语义现算与 report 不同源"
    assert len(b["unclaimed"]) == _REAL["g_p2_semantic_b"]["unclaimed"], "B 语义现算与 report 不同源"
    gap = len(b["unclaimed"]) - len(a["unclaimed"])
    assert 0 <= gap <= len(universe), f"两语义未认领之差 {gap} 越界（扫描面 {len(universe)}）＝口径失控"
    assert gap == _REAL["unclaimed_gap_a_b"]
    print(f"语义 A 未认领 {len(a['unclaimed'])} / 语义 B 未认领 {len(b['unclaimed'])} / 差 {gap}")


# --------------------------------------------------------------------------
# 上限字面量 + 方向锁
# --------------------------------------------------------------------------
def test_ceilings_are_hand_written_literals() -> None:
    """结构锁：上限必须是字面整数，不许 len(...)/sum(...) 派生；历史必须留在本文件且非空。

    注意 AST 自锁要**同时**走 `ast.Assign` 与 `ast.AnnAssign`——本仓的门曾因只认 `Assign`
    把自己要盯的带注解常量看漏。
    """
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value
    for name in _CEILING_NAMES:
        value = assigned.get(name)
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"{name} 被改成派生表达式＝上限跟着被检对象一起动，本门结构性失效"
        )
    for name in _HISTORY_NAMES:
        history = assigned.get(name)
        assert isinstance(history, ast.Tuple) and history.elts, f"{name} 必须留在本文件且非空（只降的对账凭据）"


def test_audit_histories_never_rise() -> None:
    pairs = (
        (AUDIT_HISTORY_G_P1_OUTSIDE, G_P1_OUTSIDE_CEILING, _REAL["g_p1_size"]["outside_domain"]),
        (AUDIT_HISTORY_G_P1_CONTAIN, G_P1_CONTAIN_CEILING, _REAL["g_p1_size"]["contain_pairs"]),
        (AUDIT_HISTORY_G_P2_UNCLAIMED, G_P2_UNCLAIMED_CEILING, _REAL["g_p2_semantic_a"]["unclaimed"]),
        (AUDIT_HISTORY_G_P2_VIOLATION, G_P2_VIOLATION_CEILING, _REAL["g_p2_semantic_a"]["violations"]),
        (AUDIT_HISTORY_G_P2_EXEMPT, G_P2_EXEMPT_CEILING, _REAL["counts"]["g_p2_exempt_entries"]),
    )
    for history, ceiling, current in pairs:
        counts = [count for _date, count in history]
        assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{history}"
        assert ceiling <= counts[0], f"上限 {ceiling} 超过首届核账值 {counts[0]}＝调大换绿"
        assert current <= ceiling, f"现算值 {current} 已超上限 {ceiling}（本门主判据的兜底复述）"


# --------------------------------------------------------------------------
# 反向自证（内存合成数据，不碰源码树一个字）
# --------------------------------------------------------------------------
_DOMAINS = "plugins/bot_unified_runtime/domains"
_PKG = "plugins/bot_unified_runtime"


def _g_p1(rows, *, domain_roots=("chat_reply", "core"), exempt=()):  # type: ignore[no-untyped-def]
    return pc.gp1_findings(
        rows,
        domains_root=_DOMAINS,
        package_root=_PKG,
        domain_roots=set(domain_roots),
        exempt=set(exempt),
    )


def test_poison_escape_into_pkg_root_is_caught() -> None:
    """毒①：声明落在插件包根（domains 之外）必须被点名。"""
    out = _g_p1([("B02.x", (f"{_PKG}/sender",))])
    assert out["outside_domain"] == [("B02.x", f"{_PKG}/sender")], "包根越界没数到＝取数口对越界失明"
    # 正样控制：同一路径声明在**已登记域内**必不红（判据看不见合法件＝空跑）
    ok = _g_p1([("B02.x", (f"{_DOMAINS}/chat_reply/runtime/y.py",))])
    assert not ok["outside_domain"] and not ok["unknown_domain"], ok


def test_poison_unknown_domain_is_caught() -> None:
    out = _g_p1([("B02.x", (f"{_DOMAINS}/ghostly/y.py",))])
    assert out["unknown_domain"] == [("B02.x", f"{_DOMAINS}/ghostly/y.py")], "未登记域根没被点名"


def test_poison_double_claim_is_caught() -> None:
    path = f"{_DOMAINS}/core/board_taxonomy.py"
    out = _g_p1([("B01.a", (path,)), ("B02.b", (path,))])
    assert {fid for fid, _p in out["double_claim"]} == {"B01.a", "B02.b"}, "同路径双认领没被点名"


def test_poison_duplicate_within_feature_is_caught() -> None:
    path = f"{_DOMAINS}/core/config.py"
    out = _g_p1([("B09.a", (path, path))])
    assert out["duplicate_within"], "同一功能内重复声明没被点名"


def test_poison_containment_pair_is_counted_separately() -> None:
    """目录认领套住别的 fid 的字面认领 ⇒ 进"包含对"附账，而不是双认领（最长前缀归因）。"""
    outer = f"{_DOMAINS}/chat_reply/character"
    inner = f"{_DOMAINS}/chat_reply/character/affinity.py"
    out = _g_p1([("B03.persona", (outer,)), ("B03.mood", (inner,))])
    assert not out["double_claim"], "包含形被误判成双认领＝归因口径坏了"
    assert out["contain_pairs"], "包含对没被记账（19 对这笔影子认领账会变瞎）"


def test_poison_empty_and_banned_claims_are_caught() -> None:
    universe = [f"{_DOMAINS}/chat_reply/x.py"]
    empty = pc.empty_plugin_dir_claims([("B02.a", (f"{_DOMAINS}/chat_reply/empty_dir",))], universe, package_root=_PKG)
    assert empty == [("B02.a", f"{_DOMAINS}/chat_reply/empty_dir")], "包内空目录认领（空洗账）没被抓"
    out = _g_p1([("B02.a", (_PKG,))])
    assert out["banned_claims"] == [_PKG], "拿包根当认领没被抓＝门可被一把吞掉全仓"


def test_claiming_semantics_are_two_different_rulers() -> None:
    """注毒②（双形态各一枚）：目录形认领在 A 语义覆盖子文件、在 B 语义不覆盖；孤儿新文件两边都不覆盖。"""
    claims = [("B02.a", f"{_DOMAINS}/chat_reply/runtime")]
    child = f"{_DOMAINS}/chat_reply/runtime/deep/b.py"
    assert child.startswith(claims[0][1] + "/"), "合成样本没造对（目录形认领的子文件）"
    assert pc.claiming_fids(child, claims, semantic="prefix") == {"B02.a"}, "A 语义对目录认领失明"
    assert pc.claiming_fids(child, claims, semantic="literal") == set(), "B 语义被写成了 A（两把尺子塌成一把）"
    assert pc.claiming_fids(f"{_DOMAINS}/core/orphan.py", claims, semantic="prefix") == set()
    # 目录声明自身的字面形：两条语义都必须认得（防"字面文件被目录规则误吞"）
    assert pc.claiming_fids(child, [(claims[0][0], child)], semantic="literal") == {"B02.a"}


def test_poison_unclaimed_new_file_is_caught() -> None:
    """注毒③：新增一枚没认领的 py 必须进违规；被豁免的必须不进违规。"""
    claims = [("B02.a", f"{_DOMAINS}/chat_reply/runtime")]
    universe = [f"{_DOMAINS}/chat_reply/runtime/x.py", f"{_DOMAINS}/core/newcomer.py", "bot.py"]
    out = pc.gp2_findings(claims, universe, {"bot.py"}, semantic="prefix")
    assert out["unclaimed"] == [f"{_DOMAINS}/core/newcomer.py", "bot.py"], out["unclaimed"]
    assert out["violations"] == [f"{_DOMAINS}/core/newcomer.py"], "豁免没生效或把违规算多了"
    assert out["stale_exempts"] == [], "合法豁免被误判 stale"


def test_poison_fake_and_dead_exemptions_are_caught() -> None:
    claims = [("B02.a", f"{_DOMAINS}/chat_reply/runtime")]
    universe = [f"{_DOMAINS}/chat_reply/runtime/x.py", f"{_DOMAINS}/core/newcomer.py"]
    fake = pc.gp2_findings(claims, universe, {f"{_DOMAINS}/core/never_existed.py"}, semantic="prefix")
    assert fake["stale_exempts"], "指向不存在路径的假豁免没被抓"
    dead = pc.gp2_findings(claims, universe, {f"{_DOMAINS}/chat_reply/runtime/x.py"}, semantic="prefix")
    assert dead["dead_exempts"], "豁免了其实已被认领的文件＝死豁免没被抓"


def test_poison_wildcard_exemption_is_rejected() -> None:
    """注毒④：通配符 / 正则 / 目录兜底混进豁免清单必红（用户原话："通配＝等于没门"）。"""
    bad = [
        ("plugins/**/x.py", "通配"),
        (f"{_DOMAINS}/chat_reply/", "目录兜底"),
        (f"{_DOMAINS}/core/[ab].py", "字符类正则"),
        (f"{_PKG}\\sender\\y.py", "反斜杠/非 posix"),
        ("C:/abs/path/x.py", "绝对路径"),
    ]
    errors = pc.exemption_shape_errors(bad)
    assert len(errors) == len(bad), f"形状校验漏掉了 {len(bad) - len(errors)} 种假豁免写法：{errors}"
    assert not pc.exemption_shape_errors([(f"{_PKG}/sources/z.py", "包命名空间占位")]), "合法字面条目被误杀"


# --------------------------------------------------------------------------
# 读侧 fail-closed 自证（P-S60-2）：读不到＝判红拒算，绝不静默当成"缺键/空集合"。
# 全部在内存合成声明源上跑（`load_placement(source=...)`），不往源码树写一个字。
# --------------------------------------------------------------------------
_PLACEMENT_NAMES = {"DOMAINS_ROOT", "PACKAGE_ROOT", "BANNED_CLAIM_PATHS", "G_P1_EXEMPT", "G_P2_EXEMPT"}
# 一份形状合法、五枚齐全的最小声明源（含 tuple-of-tuple 嵌套容器），作为投毒底本。
_OK_SRC = (
    'DOMAINS_ROOT: str = "plugins/bot_unified_runtime/domains"\n'
    'PACKAGE_ROOT: str = "plugins/bot_unified_runtime"\n'
    'BANNED_CLAIM_PATHS: tuple[str, ...] = ("plugins",)\n'
    'G_P1_EXEMPT: tuple[tuple[str, str, str], ...] = ()\n'
    "G_P2_EXEMPT: tuple[tuple[str, str], ...] = (\n"
    '    ("bot.py", "启动件"),\n'
    '    ("plugins/x/__init__.py", "命名空间占位"),\n'
    ")\n"
)


def test_reader_extracts_every_declaration_element_from_real_source() -> None:
    """步骤①：现役声明源"读得动"——解析条数必须逐枚等于源里字面量条数（不等＝已静默失效）。

    这是防"账具失明"的常驻锁：嵌套容器（tuple-of-tuple）整棵求值，条数不丢。
    """
    text = pc.PLACEMENT_PY.read_text(encoding="utf-8")
    parsed = pc._read_literals(text, _PLACEMENT_NAMES, source_label="board_placement.py")
    src_counts: dict[str, int] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Assign):
            tg = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tg = [node.target]
        else:
            continue
        for t in tg:
            if t.id in _PLACEMENT_NAMES and isinstance(node.value, ast.Tuple):
                src_counts[t.id] = len(node.value.elts)
    assert src_counts, "源里一枚 tuple 字面量都没数到——这份自证本身失效了"
    for name, n in src_counts.items():
        assert len(parsed[name]) == n, f"{name} 解析出 {len(parsed[name])} 枚，源里写了 {n} 枚＝取数口在失明"
    assert parsed["G_P2_EXEMPT"], "G_P2_EXEMPT 被读成空——现役声明源明明有豁免，取数口对豁免失明"


def test_poison_illegal_literal_is_fail_closed_and_names_file_line() -> None:
    """反向自证③a：把某条声明改成非法字面量（`frozenset(...)`）⇒ 必红并点名 文件:行。"""
    bad = _OK_SRC.replace(
        'BANNED_CLAIM_PATHS: tuple[str, ...] = ("plugins",)',
        'BANNED_CLAIM_PATHS: tuple[str, ...] = frozenset(("plugins",))',
    )
    try:
        pc.load_placement(source=bad, source_label="fake/board_placement.py")
    except pc.PlacementDeclarationError as exc:
        msg = str(exc)
        assert "fake/board_placement.py:" in msg, f"没点名文件:行——{msg}"
        assert "BANNED_CLAIM_PATHS" in msg, f"没点名受害声明——{msg}"
    else:
        raise AssertionError("非法字面量被静默放行（读不到当成 None/空），fail-closed 未生效")


def test_poison_none_value_is_fail_closed_not_empty_list() -> None:
    """反向自证③a 补刀：值写成合法字面量 `None`（可解析却语义为空）⇒ 仍判红，绝不补空。"""
    bad = _OK_SRC.replace(
        'BANNED_CLAIM_PATHS: tuple[str, ...] = ("plugins",)',
        "BANNED_CLAIM_PATHS: tuple[str, ...] = None",
    )
    try:
        pc.load_placement(source=bad, source_label="fake/board_placement.py")
    except AssertionError as exc:
        assert "None" in str(exc), str(exc)
    else:
        raise AssertionError("None 值被当成合法空清单放行＝账具失明")


def test_poison_missing_assignment_is_fail_closed_not_empty_set() -> None:
    """反向自证③b：删掉整条赋值 ⇒ 必红（不许"当成空集合"继续算）。"""
    gone = "".join(line + "\n" for line in _OK_SRC.splitlines() if "G_P1_EXEMPT" not in line)
    try:
        pc.load_placement(source=gone, source_label="fake/board_placement.py")
    except AssertionError as exc:
        assert "G_P1_EXEMPT" in str(exc), f"缺声明没被点名：{exc}"
    else:
        raise AssertionError("整条赋值被删后静默当空集合放行＝账具失明")


def test_normal_state_reads_all_five_and_keeps_nested_counts() -> None:
    """反向自证③c：正常态声明源 ⇒ 五枚齐全、嵌套容器逐枚读全（判据不顺手改数，真值由 report/棘轮守）。"""
    ok = pc.load_placement(source=_OK_SRC, source_label="fake/board_placement.py")
    assert set(ok) == _PLACEMENT_NAMES, sorted(ok)
    assert len(ok["G_P2_EXEMPT"]) == 2 and len(ok["BANNED_CLAIM_PATHS"]) == 1
    assert ok["G_P1_EXEMPT"] == ()


# --------------------------------------------------------------------------
# G-P1 豁免通道「形状对得上、条目活得着」三把锁（P-S70-4，席 S100 追加 2026-09-22）。
# 历史形状：构造侧 `compute()` 装 (fid, path) 元组、查侧拿裸路径查表——形状不合**不报错**、
# 只是永远匹配不上 ⇒ 门报错里"把它加进 G_P1_EXEMPT"这条路按下去无效（现值 0 把它盖住）。
# 三把锁把构造侧、查侧与报错"下一步"钉成同源；全部内存合成数据，不往源码树写一个字。
# --------------------------------------------------------------------------
_P1_POISON_FID = "B99.poison"
_P1_POISON_PATH = f"{_PKG}/docs/engineering_surface.py"  # 包内域外形 ⇒ 天然越界（根 py 现算只有 bot.py，别用简报例子的形状）


def _p1_placement_src(exempt_literal: str) -> str:
    return (
        f'DOMAINS_ROOT: str = "{_DOMAINS}"\n'
        f'PACKAGE_ROOT: str = "{_PKG}"\n'
        'BANNED_CLAIM_PATHS: tuple[str, ...] = ("plugins",)\n'
        f"G_P1_EXEMPT: tuple[tuple[str, str, str], ...] = {exempt_literal}\n"
        "G_P2_EXEMPT: tuple[tuple[str, str], ...] = ()\n"
    )


def test_g_p1_exempt_channel_is_alive_end_to_end() -> None:
    """存活锁（简报③b/④）：往 `G_P1_EXEMPT` 放一条真实越界路径 ⇒ 该条必须从违规集消失。

    走生产全链：合成声明源 → `load_placement` → 唯一构造口 `g_p1_exempt_keys` → `gp1_findings` 查表。
    修复前此测必死在第三段（元组 vs 裸路径永不匹配）——那正是 P-S70-4 的形状。
    """
    rows = [(_P1_POISON_FID, (_P1_POISON_PATH,))]
    placement = pc.load_placement(source=_p1_placement_src("()"), source_label="fake/board_placement.py")
    assert placement["G_P1_EXEMPT"] == ()
    bare = pc.gp1_findings(rows, domains_root=_DOMAINS, package_root=_PKG, domain_roots={"chat_reply"}, exempt=set())
    assert bare["outside_domain"] == [(_P1_POISON_FID, _P1_POISON_PATH)], "空白样本自己没数到越界＝本锁样本失效（空跑）"
    entry_src = _p1_placement_src(f"({pc.g_p1_exempt_entry_literal(_P1_POISON_FID, _P1_POISON_PATH, '工程面·用户裁')},)")
    placed = pc.load_placement(source=entry_src, source_label="fake/board_placement.py")
    keys = pc.g_p1_exempt_keys(placed["G_P1_EXEMPT"])
    assert keys == {(_P1_POISON_FID, _P1_POISON_PATH)}, f"构造口产物不是 (fid, impl_path) 对集合：{keys}"
    gone = pc.gp1_findings(rows, domains_root=_DOMAINS, package_root=_PKG, domain_roots={"chat_reply"}, exempt=keys)
    assert not gone["outside_domain"], "按声明加了豁免仍留在违规集 ⇒ 通道无牙（P-S70-4 回潮）"
    # fid 精度：别的 fid 的豁免不得吞掉本条（防豁免面放宽成"只看路径就放行"的第二形态死通道）
    wrong_fid = pc.gp1_findings(rows, domains_root=_DOMAINS, package_root=_PKG,
                                domain_roots={"chat_reply"}, exempt={("B00.other", _P1_POISON_PATH)})
    assert wrong_fid["outside_domain"] == [(_P1_POISON_FID, _P1_POISON_PATH)], "跨 fid 豁免生效＝豁免面放宽成按路径全放行"


def test_g_p1_exempt_shape_lock_rejects_drifted_shapes() -> None:
    """形状锁（简报③a/④）：裸路径／二元／四元／非 str／空理由／通配全判红；故意把形状改坏 ⇒ 查侧当场抛错。"""
    good = ((_P1_POISON_FID, _P1_POISON_PATH, "工程面"),)
    assert not pc.gp1_exemption_shape_errors(good), "合法三元被误杀"
    assert pc.g_p1_exempt_keys(good) == {(_P1_POISON_FID, _P1_POISON_PATH)}
    drifted = [
        _P1_POISON_PATH,                                            # 裸路径（无 fid）
        (_P1_POISON_FID, _P1_POISON_PATH),                          # 二元（缺理由）
        (_P1_POISON_FID, _P1_POISON_PATH, "理由", "余"),            # 四元
        (_P1_POISON_FID, 42, "理由"),                               # 非字符串成员
        (_P1_POISON_FID, _P1_POISON_PATH, "   "),                   # 空理由
        (_P1_POISON_FID, f"{_PKG}/docs/*", "通配"),                 # 通配符路径
    ]
    for entry in drifted:
        assert pc.gp1_exemption_shape_errors([entry]), f"形状漂移没被抓（尺子失明）：{entry!r}"
        try:
            pc.g_p1_exempt_keys((entry,))
        except pc.PlacementDeclarationError as exc:
            assert "G_P1_EXEMPT" in str(exc), f"构造口报错没点名受害清单：{exc}"
        else:
            raise AssertionError(f"构造口放行了坏形状（fail-closed 失效）：{entry!r}")
    # 查侧类型锁的运行时腿：拿**裸路径集合**（历史漂移形）来查表 ⇒ 必抛红并点名唯一构造口
    try:
        pc.gp1_findings([(_P1_POISON_FID, (_P1_POISON_PATH,))], domains_root=_DOMAINS,
                        package_root=_PKG, domain_roots={"chat_reply"}, exempt={_P1_POISON_PATH})
    except pc.PlacementDeclarationError as exc:
        assert "g_p1_exempt_keys" in str(exc), f"查侧报错没指向唯一构造口（下一步不可执行）：{exc}"
    else:
        raise AssertionError("查侧接受了裸路径集合 ⇒ P-S70-4 同型漂移将再次不被发现")


def test_g_p1_channel_single_construction_port_and_next_step_is_executable() -> None:
    """反空跑锁（简报③c）＋同源结构锁（简报②）：构造口唯一、报错"下一步"照做即生效、真树死豁免为 0。

    反空跑的立场：真树通道现值 0 枚——**「零违规」永远不得当作达标证据**；牙齿的存在性由
    `test_g_p1_exempt_channel_is_alive_end_to_end` / `test_g_p1_exempt_shape_lock_rejects_drifted_shapes`
    两枚合成注毒立住（有违规必数、豁免必消、坏形必抛；F-15/P-46 教训）。本测钉的是**结构不变量**，
    不钉现值，所以既不挡未来正当豁免、也不给静默回改留缝：
    ① `compute()` 必须调 `g_p1_exempt_keys` 构造键，且自身不得 inline 第二处 pair 构造（SetComp-of-Tuple）；
    ② 查侧必须是 `(fid, path) in exempt` 的元组键，不得再现 `path in exempt` 裸形；
    ③ 报错字面量 `literal_eval` 回读即声明条目本尊，过构造口所得 == 查侧键（"下一步"可执行）；
    ④ 真树每条 G-P1 豁免今天都必须正吞着一条真违规（死豁免 ⇒ 红，条目"活得着"）。
    """
    tree = ast.parse(Path(pc.__file__).read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    compute_nodes = list(ast.walk(fns["compute"]))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "g_p1_exempt_keys"
               for n in compute_nodes), "compute() 不再经唯一构造口 ⇒ 出现第二处构造位（形状漂移的根源土壤）"
    assert not any(isinstance(n, ast.SetComp) and isinstance(n.elt, ast.Tuple) for n in compute_nodes), \
        "compute() 又 inline 了 pair 构造——P-S70-4 历史形状（构造侧绕过构造口自装元组）"
    gp1_nodes = list(ast.walk(fns["gp1_findings"]))
    assert any(
        isinstance(n, ast.Compare) and isinstance(n.left, ast.Tuple)
        and {e.id for e in n.left.elts if isinstance(e, ast.Name)} >= {"fid", "path"}
        and isinstance(n.ops[0], ast.In)
        and isinstance(n.comparators[0], ast.Name) and n.comparators[0].id == "exempt"
        for n in gp1_nodes
    ), "查侧不再用 (fid, path) 元组键——形状锁的静态腿失明"
    assert not any(
        isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "path"
        and isinstance(n.ops[0], ast.In)
        and isinstance(n.comparators[0], ast.Name) and n.comparators[0].id == "exempt"
        for n in gp1_nodes
    ), "gp1_findings 里再现裸 `path in exempt`（P-S70-4 同型回潮）"
    lit = pc.g_p1_exempt_entry_literal("B02.x", f"{_PKG}/docs/a.py", "工程面")
    entry = ast.literal_eval(lit)
    assert entry == ("B02.x", f"{_PKG}/docs/a.py", "工程面"), lit
    assert (entry[0], entry[1]) in pc.g_p1_exempt_keys((entry,)), "报错给的『下一步』与构造口产物不同源 ⇒ 照做也无效"
    assert _REAL["g_p1_dead_exempts"] == [], f"G-P1 死豁免（豁免对象已不在违规集，该摘并降账）：{_REAL['g_p1_dead_exempts']}"
