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
