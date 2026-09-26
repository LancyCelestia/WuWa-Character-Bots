"""能力唯一在册表迁移的 **AST 逐字段等值锁**（中央调度收编波 S12）。

被迁的东西：`runtime/capability_protocols.py::CAPABILITY_DESCRIPTOR`（唯一在册表）搬进
`domains/core/capability_manifest.py`；旧 registry / 板块 taxonomy / 多模态 tags 降为再导出垫片。
**迁移本体由主代理落**（那两枚真身文件主代理独占），本件只做**迁移前后的等值锁**——
不 import 包、不起进程、不读 config、不碰网络，只用 ``ast`` 静态解析两枚真身。

## 锁的语义（不是"今天两侧都空所以绿"）
  · **一旦册开始供出某字段，投影值必须与表值逐字段等值**：当 ``capability_manifest.py`` 里
    出现同名 dataclass 的某个字段，其「注解文本 + 缺省文本」必须与 ``capability_protocols.py``
    里该字段逐字相等（含 dataclass 声明序）。搬进去时改了任一项 = ``BOTH-DIFFER`` = 红。
  · **今日两侧不重叠的字段显式记为未迁移，不许静默跳过**：迁移前册不供出任何一列 ⇒ 全部字段
    落在 ``*_UNMIGRATED_FIELDS`` 这本**写死的账**里。计算所得的"表有册无"集合必须与这本账
    **逐名全等**——既不许把未迁移糊成绿（账漏一名就红），也不许册悄悄多供一列
    （多供 = ``MANIFEST-ONLY`` = 改账嫌疑 = 红）。册一旦开始供出某列，该列自动离开未迁移账、
    转由等值判据接管：本件在"迁移进行中"与"迁移完成后"都必须仍成立，只随账同步，不放宽判据。

## 本件的两处自我限制（如实，别当已证）
 1. 本件比的是 **dataclass 声明层**（字段名/注解/缺省/序）与**迁移标的的单一真身归属**，
    不重现 ``_build_capability_descriptor()`` 的**行值**。逐行值往返等值由
    ``scripts/capability_manifest_projection_check.py``（S10 量具）负责，两者互补不重叠。
 2. ``CAPABILITY_DESCRIPTOR`` / ``DESCRIPTOR_BUILDERS`` 是派生 Mapping / 函数对象元组，
    静态无法逐字节比"值"——本件对它们只锁**单一真身归属**（不许协议侧与册侧各供一份 = 第二真身），
    值的搬运等值以 S10 量具为准。

造绿六禁（缩扫描面/抬基线/删断言/加 skip·xfail/放宽判据/预填达标值）在本件一票否决：
所有基线都是**现读源码算出**、未迁移账是**显式点名**、每发判据都配注毒自证。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "plugins/bot_unified_runtime/runtime/capability_protocols.py"
MANIFEST = ROOT / "plugins/bot_unified_runtime/domains/core/capability_manifest.py"

# 两枚 dataclass 的迁移判据面（口径与 S10 量具 MIGRATION_TARGETS 对齐）。
REGISTRATION_CLS = "CapabilityRegistration"
DESCRIPTOR_CLS = "CapabilityDescriptor"

# 迁移标的：真身住 ``capability_protocols`` 的派生 Mapping / 函数对象元组 / 派生函数 / 派生 tuple。
# 迁移前它们只由协议侧供出；册侧一旦独立再供一份 = 第二真身 = 红。
MIGRATION_MODULE_NAMES: tuple[str, ...] = (
    "CAPABILITY_DESCRIPTOR",
    "DESCRIPTOR_BUILDERS",
    "_build_capability_descriptor",
    "_ORCHESTRATION_DESCRIPTORS",
)

# 册自有的新维度（迁移的目的地要补的、今日协议表里根本没有的三件 + 棘轮）：
# 判据 = 册侧必须有、协议侧必须没有（反向差集，证明它们是"新维度"而非"被搬进来的旧账"）。
MANIFEST_NATIVE_DIMENSIONS: tuple[str, ...] = (
    "FACETS",
    "EVIDENCE",
    "PLACEHOLDER_UNIMPLEMENTED",
    "UNCOVERED_CEILING",
)

# ── 未迁移账（写死，现算须逐名全等；只随迁移进度同步，不许拿它糊绿）────────────────
# 首届核账 = 2026-09-24 本席现算：册尚未供出任一 dataclass ⇒ 全字段入此账。
# 尺身份三元组见报告 §1；改这两枚真身任一 dataclass 的列集 ⇒ 本账必红，逼同步。
REGISTRATION_UNMIGRATED_FIELDS: tuple[str, ...] = (
    "capability_id", "title", "handler_ref", "health_probe", "health_default",
    "fallbacks", "timeout_seconds", "family", "gate_feature_id", "routes",
    "help_topics", "interface_id", "authored_by",
)
DESCRIPTOR_UNMIGRATED_FIELDS: tuple[str, ...] = (
    "capability_id", "family", "title", "input_protocol", "output_protocol",
    "required_roles", "timeout_seconds", "limits", "limit_fields", "fallback_chain",
    "implementation_ref", "config_keys", "health_probe", "health_default", "notes",
)


# =========================================================================
# 纯静态解析件（全部可被注毒用例直接打靶，不触盘）
# =========================================================================
def _load_tree(path: Path) -> ast.Module:
    """读源码并解析；读不出/解析不了即抛（绝不让"量具失明"降级成"没扫到=没问题"）。"""
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"))


def _unparse(node: ast.expr | None) -> str:
    return "<none>" if node is None else ast.unparse(node)


def dataclass_field_specs(tree: ast.Module) -> dict[str, list[tuple[str, str, str]]]:
    """顶层 dataclass 的 (类名 -> 声明序字段表)，字段 = (名, 注解文本, 缺省文本)。"""
    out: dict[str, list[tuple[str, str, str]]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        is_dataclass = any(
            (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "dataclass")
            or getattr(dec, "id", "") == "dataclass"
            for dec in node.decorator_list
        )
        if not is_dataclass:
            continue
        fields: list[tuple[str, str, str]] = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.append((stmt.target.id, _unparse(stmt.annotation), _unparse(stmt.value)))
        out[node.name] = fields
    return out


def module_assigned_names(tree: ast.Module) -> set[str]:
    """模块级「被定义/赋值」的名字（Assign/AnnAssign/FunctionDef/ClassDef），不含 import 再导出。"""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


def imported_symbols(tree: ast.Module) -> dict[str, str]:
    """import-from 得到的 本地名 -> 来源模块末段（垫片再导出的识别用）。"""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            tail = node.module.split(".")[-1]
            for alias in node.names:
                out[alias.asname or alias.name] = tail
    return out


def classify_fields(
    table_fields: list[tuple[str, str, str]],
    manifest_fields: list[tuple[str, str, str]] | None,
) -> dict[str, list[str]]:
    """逐字段把「表列 × 册列」归入四类。册未定义该类 ⇒ manifest_fields=None ⇒ 全 NOT_MIGRATED。"""
    manifest_map = {name: (ann, dflt) for name, ann, dflt in (manifest_fields or [])}
    table_map = {name: (ann, dflt) for name, ann, dflt in table_fields}
    buckets: dict[str, list[str]] = {
        "NOT_MIGRATED": [], "MANIFEST_ONLY": [], "BOTH_EQUAL": [], "BOTH_DIFFER": [],
    }
    for name, spec in table_map.items():
        if name not in manifest_map:
            buckets["NOT_MIGRATED"].append(name)
        elif manifest_map[name] == spec:
            buckets["BOTH_EQUAL"].append(name)
        else:
            buckets["BOTH_DIFFER"].append(name)
    for name in manifest_map:
        if name not in table_map:
            buckets["MANIFEST_ONLY"].append(name)
    return buckets


def ledger_matches(computed_not_migrated: set[str], ledger: tuple[str, ...]) -> bool:
    """未迁移账逐名全等判据（不缩不涨）：册每供出一列、计算集缩一名，账不同步即红。"""
    return computed_not_migrated == set(ledger)


def declaration_order_preserved(
    table_fields: list[tuple[str, str, str]],
    manifest_fields: list[tuple[str, str, str]] | None,
) -> bool:
    """两侧都定义该类时，声明序（字段名序列）必须一致——重排 = 位置构造语义变 = 改账。"""
    if manifest_fields is None:
        return True  # 册未供出 ⇒ 无从谈序，属未迁移，另由账管
    return [n for n, _a, _d in table_fields] == [n for n, _a, _d in manifest_fields]


# =========================================================================
# 等值锁主体
# =========================================================================
def _parity(cls: str, ledger: tuple[str, ...]) -> dict[str, list[str]]:
    table = dataclass_field_specs(_load_tree(PROTOCOLS))
    manifest = dataclass_field_specs(_load_tree(MANIFEST))
    # 量具失明地板：唯一表侧必须解析到该类，否则"没扫到"会被读成"已迁移/无差异"。
    assert cls in table, f"协议侧未解析到 dataclass {cls}＝尺瞎了，不许当已迁移放绿"
    return classify_fields(table[cls], manifest.get(cls))


def test_registration_field_parity() -> None:
    """唯一表 ``CapabilityRegistration`` 逐字段等值锁 + 未迁移账逐名全等。"""
    buckets = _parity(REGISTRATION_CLS, REGISTRATION_UNMIGRATED_FIELDS)
    assert not buckets["BOTH_DIFFER"], (
        "册供出的列与表不逐字相等（搬账改了账）：" + "、".join(buckets["BOTH_DIFFER"]))
    assert not buckets["MANIFEST_ONLY"], (
        "册供出表里没有的列（第二真身/改账嫌疑）：" + "、".join(buckets["MANIFEST_ONLY"]))
    assert ledger_matches(set(buckets["NOT_MIGRATED"]), REGISTRATION_UNMIGRATED_FIELDS), (
        f"未迁移账与实况不符（不许静默跳过/缩面）：实况={sorted(buckets['NOT_MIGRATED'])}"
        f" vs 账={sorted(REGISTRATION_UNMIGRATED_FIELDS)}")
    # 每一列必居其一（无第三态漏网 ⇒ 既没被悄悄比、也没被悄悄跳）。
    assert set(buckets["NOT_MIGRATED"]) | set(buckets["BOTH_EQUAL"]) == set(
        REGISTRATION_UNMIGRATED_FIELDS) | set(buckets["BOTH_EQUAL"])


def test_descriptor_field_parity() -> None:
    """唯一表 ``CapabilityDescriptor`` 逐字段等值锁 + 未迁移账逐名全等。"""
    buckets = _parity(DESCRIPTOR_CLS, DESCRIPTOR_UNMIGRATED_FIELDS)
    assert not buckets["BOTH_DIFFER"], (
        "册供出的列与表不逐字相等（搬账改了账）：" + "、".join(buckets["BOTH_DIFFER"]))
    assert not buckets["MANIFEST_ONLY"], (
        "册供出表里没有的列（第二真身/改账嫌疑）：" + "、".join(buckets["MANIFEST_ONLY"]))
    assert ledger_matches(set(buckets["NOT_MIGRATED"]), DESCRIPTOR_UNMIGRATED_FIELDS), (
        f"未迁移账与实况不符（不许静默跳过/缩面）：实况={sorted(buckets['NOT_MIGRATED'])}"
        f" vs 账={sorted(DESCRIPTOR_UNMIGRATED_FIELDS)}")


def test_registration_declaration_order_stable_when_duplicated() -> None:
    """两侧都定义该类时段声明序一致（迁移进行中/完成后都锁；册未定义=未迁移=本判据休眠但必真）。"""
    table = dataclass_field_specs(_load_tree(PROTOCOLS))
    manifest = dataclass_field_specs(_load_tree(MANIFEST))
    assert declaration_order_preserved(table[REGISTRATION_CLS], manifest.get(REGISTRATION_CLS)), (
        "册内 CapabilityRegistration 字段序与表不一致 = 位置构造语义被改")


def test_migration_targets_have_single_home() -> None:
    """迁移标的（派生 Mapping / 函数对象元组 / 派生函数 / 派生 tuple）只许一侧独立供出。

    协议侧今日全部供出（真源）；册侧今日一律不供出（未迁移）。任一标的若两侧**都各自定义**，
    即在册里长出第二真身（例：把 ``CAPABILITY_DESCRIPTOR`` 又抄一份成字面量表）= 红。
    迁移完成后册侧供出、协议侧改为再导出 ⇒ 仍单侧独立定义，判据不放宽。"""
    table = module_assigned_names(_load_tree(PROTOCOLS))
    manifest = module_assigned_names(_load_tree(MANIFEST))
    for name in MIGRATION_MODULE_NAMES:
        in_table = name in table
        in_manifest = name in manifest
        assert not (in_table and in_manifest), (
            f"{name} 在协议侧与册侧各自独立定义 = 唯一在册表第二真身")
        assert in_table, f"{name} 协议侧未供出＝尺瞎了/被悄悄挪走，不许当已迁移放绿"
    # 首届核账：册侧今日对这四枚标的独立定义集必为空（迁移本体尚未落，未做≠绿，显式记此账）。
    assert not (manifest & set(MIGRATION_MODULE_NAMES)), (
        f"册侧已独立供出迁移标的 {sorted(manifest & set(MIGRATION_MODULE_NAMES))}"
        "——若为迁移完成后态，须同步把协议侧改为再导出，勿两侧并存")


def test_manifest_native_dimensions_are_manifest_only() -> None:
    """册自有维度（FACETS/EVIDENCE/PLACEHOLDER/CEILING）：册侧必须有、协议侧必须没有。

    这是差集的反向半：证明这四件是真身册新补的维度，不是从唯一表搬来的旧账；
    协议侧一旦出现同名 ⇒ 说明有人在表里另立一份维度真身 = 第二真身 = 红。"""
    table = module_assigned_names(_load_tree(PROTOCOLS))
    manifest = module_assigned_names(_load_tree(MANIFEST))
    for name in MANIFEST_NATIVE_DIMENSIONS:
        assert name in manifest, f"册侧缺 {name}＝真身册瘦身或改名，本锁失去对账对象"
        assert name not in table, f"{name} 竟在协议侧定义＝维度真身分裂为二"


# =========================================================================
# 注毒自证（证明判据真有牙，不触盘、只喂合成字段表）
# =========================================================================
def test_poison_divergent_default_is_not_equal() -> None:
    """注毒①：册把 timeout_seconds 缺省从 30.0 改成 45.0 ⇒ 必须落 BOTH-DIFFER，绝不当等值。"""
    table = [
        ("capability_id", "str", "<none>"),
        ("timeout_seconds", "float", "30.0"),
        ("notes", "str", "''"),
    ]
    manifest = [
        ("capability_id", "str", "<none>"),
        ("timeout_seconds", "float", "45.0"),  # ← 注毒：改了缺省
        ("notes", "str", "''"),
    ]
    buckets = classify_fields(table, manifest)
    assert buckets["BOTH_DIFFER"] == ["timeout_seconds"], f"改缺省未被抓到＝等值无牙：{buckets}"


def test_poison_dropped_field_silently_passes_ledger_only_if_synced() -> None:
    """注毒②：册供出了一列（该列离开未迁移账）⇒ 账若不同步（仍列着它）必须红。

    这正是"不许把未迁移糊成绿"的反面：迁移推进时账必须手动跟进，漏改当场被
    ``ledger_matches`` 抓到（模拟：账漏记一名，实况与账不等）。"""
    table = [
        ("capability_id", "str", "<none>"),
        ("title", "str", "''"),
        ("handler_ref", "str", "''"),
    ]
    manifest = [("capability_id", "str", "<none>"), ("title", "str", "''")]  # 只供两列
    buckets = classify_fields(table, manifest)
    computed_not_migrated = set(buckets["NOT_MIGRATED"])
    assert computed_not_migrated == {"handler_ref"}
    # 陈旧账（还把 title 记作未迁移）→ 不等 → 红；同步后账 = {handler_ref} → 等 → 绿。
    assert not ledger_matches(computed_not_migrated, ("capability_id", "title", "handler_ref")), (
        "账未随迁移同步却判等＝可被静默跳过")
    assert ledger_matches(computed_not_migrated, ("handler_ref",))


def test_poison_manifest_only_column_is_flagged() -> None:
    """注毒③：册凭空多供一列（表里没有）⇒ 必须落 MANIFEST-ONLY（改账/第二真身嫌疑）。"""
    table = [("capability_id", "str", "<none>")]
    manifest = [("capability_id", "str", "<none>"), ("shadowed_field", "str", "''")]
    buckets = classify_fields(table, manifest)
    assert buckets["MANIFEST_ONLY"] == ["shadowed_field"], f"多供列未被抓到：{buckets}"


def test_poison_reordered_declaration_is_flagged() -> None:
    """注毒④：两侧字段集相同但声明序不同 ⇒ 段序判据必须红（位置构造语义变）。"""
    table = [("a", "str", "<none>"), ("b", "str", "<none>")]
    manifest = [("b", "str", "<none>"), ("a", "str", "<none>")]
    assert not declaration_order_preserved(table, manifest), "重排未被抓到＝段序无牙"


# =========================================================================
# 防回潮锁（S193 补）：真身册的每一维都必须有对应判据
#
# 立门缘由：S187 半程落码把 `arms` 字段写进 `CapabilityFacets`、docstring 点名"腿㉓"、
# 而门件当时零命中该判据 ⇒ 维度空挂（现由 S190 补腿㉓）。S193 现算发现**同一形态的第二个
# 空挂维**：`board`（`CapabilityFacets.board`）当时全树唯一引用是
# `tests/test_capability_manifest_gate.py:1098` 的注毒夹具 pass-through（`board=src.board`），
# 无任何门腿核其合法性/活性——与 trigger_source 有腿④（"指针必须解析到真实符号"）对照即见缺口。
# 【S196 收口】按 S193 §3 补丁 B 给 board 补真腿 `test_leg24_board_is_a_real_and_consistent_board`
# （双向：正向核板块码合法、反向核板块树归属一致），据此把 board 从 KNOWN_GAPS 摘牌 ⇒
# 现算无腿维集合 == KNOWN_GAPS == ∅（本文件下方快照锁 `test_no_manifest_dimension_is_left_dangling` 钉死）。
#
# 本锁要拦的：**新增字段却无人执法 ⇒ 红**。四类违规各可单独归因（见注毒①②③④）：
#   ①空挂维（既无腿又未登记豁免）
#   ②假覆盖（申报的执法腿在门件里根本不存在）
#   ③幽灵维（账上有、真身册已无此字段）
#   ④非法自造豁免（塞进 KNOWN_GAPS 却不在历史白名单 ⇒ 不许靠自塞名册逃避执法）
#
# 造绿六禁（缩扫描面/抬基线/删断言/加 skip·xfail/放宽判据/预填达标值）在本段仍一票否决：
# 所有集合都是 AST 现算、执法腿名以门件 AST 定义集为准、KNOWN_GAPS 是**只准缩 + 成员须 ⊆
# 硬编码历史白名单**（S196 后白名单清空为 frozenset()，即"当前无一维允许空挂"）——新维度既
# 无法靠"顺手塞进 KNOWN_GAPS"混过去（注毒③自证），也无法靠"删掉 board 字段"冒充摘牌
# （快照锁 `assert "board" in dims and "board" in DIMENSION_TO_LEG` 反真空自证拦死）。
#
# 尺身份三元组：件＝本文件；函数＝`_dimension_coverage_violations`；复跑命令见
#   `.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S193.md` §2。
#   本锁只 AST 静态解析、不 import 包、不触盘、不改别人写面。
# =========================================================================
GATE = ROOT / "tests" / "test_capability_manifest_gate.py"

#: 真身册 `CapabilityFacets` 的每一维 → 门件里执法它的那把常驻腿函数名（AST 现算存在性）。
#: 一腿管一维、职责不重叠：可解析性 / 镜像等值 / 行号 / 指针 / 票根 / 直呼点 / 配置键 / 臂 / 板块指针 / id 在册。
#: `entry_kinds` 无独立腿（docstring 明确"自由声明、没有外部活性校验"），
#: 但它被腿㉓ 双向消费（`arms ⊆ entry_kinds` 且 `arms == entry_kinds ∩ 活形集`）⇒ 有真执法。
DIMENSION_TO_LEG: dict[str, str] = {
    "capability_id": "test_leg1_declared_must_be_registered",
    "entry_kinds": "test_leg23_arms_pinned_bidirectionally_to_liveness",
    "tags": "test_leg6_native_tags_require_evidence",
    "trigger_source": "test_leg4_trigger_source_is_a_pointer",
    "implementation_ref": "test_leg2c_manifest_impl_ref_matches_descriptor",
    "implementation_line": "test_leg2d_execution_body_line_matches_ast",
    "direct_callsites": "test_leg8_direct_callsites_declared_match_census",
    "config_keys": "test_leg9_config_keys_declared_match_descriptors",
    "arms": "test_leg23_arms_pinned_bidirectionally_to_liveness",
    # S196 摘牌（按 S193 §3 补丁 B）：board 从"字段在册、门不检查"的空挂维升成有真腿的维。
    # 腿㉔双向钉——正向核板块码合法（真解析到 board_taxonomy 一级板块）、反向核归属一致（跟随）。
    "board": "test_leg24_board_is_a_real_and_consistent_board",
}

#: 在册却暂无门腿的维度（已知空挂维，**只准缩不许涨**；成员须 ⊆ 下方历史白名单）。
#: S196 已把最后一枚 `board` 补真腿并摘牌 ⇒ 本表清空为空 dict。空 dict 合法（非"没写"）：
#: 它记录"当前无一维空挂"这一现算事实，任何新维若缺腿会被 `[DIM-UNCOVERED]` 当场点破。
#: ⚠ 摘牌≠删除本判据：`test_no_manifest_dimension_is_left_dangling` 仍钉"无腿维集合 == KNOWN_GAPS"，
#:   想再空挂一枚维（既无腿又塞 KNOWN_GAPS）会被 `[DIM-UNCOVERED]`/`[DIM-SELFEXEMPT]` 两判据拦。
DIMENSION_KNOWN_GAPS: dict[str, str] = {}

#: KNOWN_GAPS 的历史白名单：允许处于"已知空挂"槽位的维度。只准缩、不许被新维撑大。
#: 与全仓棘轮同纪律——想动它＝故意留痕（把某新维加进此 frozenset 才允许其被塞 KNOWN_GAPS）。
#: S196：board 补真腿摘牌后，唯一在册空挂维归零 ⇒ 白名单随之清空（frozenset()）。
_HISTORICAL_KNOWN_GAP_DIMENSIONS: frozenset[str] = frozenset()


def gate_top_level_functions(tree: ast.Module) -> set[str]:
    """门件顶层函数名集合（Lock B 用：申报的执法腿必须真在门件里定义，防"假覆盖"）。"""
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _dimension_coverage_violations(
    dims: list[str],
    enforced: dict[str, str],
    gaps: dict[str, str],
    historical_gaps: frozenset[str],
    gate_funcs: set[str],
) -> list[str]:
    """纯谓词：逐维核"要么有真在门件里的执法腿、要么是登记在册的已知空挂维"。

    四类违规各自可单独归因（注毒①②③④逐发打靶各一类）。输入皆可喂合成数据，
    不 import 包、不触盘。返回违规清单，空即全绿。"""
    v: list[str] = []
    dim_set = set(dims)
    covered = set(enforced) | set(gaps)
    for d in sorted(dim_set - covered):
        v.append(f"[DIM-UNCOVERED] 空挂维（门件无判据、亦未登记豁免）：{d}")
    for d, fn in sorted(enforced.items()):
        if fn not in gate_funcs:
            v.append(f"[DIM-FAKELEG] 假覆盖（申报的执法腿在门件里不存在）：{d}→{fn}")
    for d in sorted(covered - dim_set):
        v.append(f"[DIM-GHOST] 幽灵维（账上有、真身册 CapabilityFacets 已无此字段）：{d}")
    for d in sorted(set(gaps) - historical_gaps):
        v.append(f"[DIM-SELFEXEMPT] 非法自造豁免（不在历史白名单，不得靠塞名册逃避执法）：{d}")
    return v


def test_every_manifest_dimension_has_a_leg_or_declared_gap() -> None:
    """防回潮锁主体：真身册 CapabilityFacets 的每一维都有对应判据，或登记为已知空挂维。

    维度集与门件腿名集都**现算 AST**，零手抄：册新供一维而本表不同步 ⇒ 当场红。
    现算只读源码文本、不 import 包、不触盘。"""
    dims = [name for name, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]]
    gate_funcs = gate_top_level_functions(_load_tree(GATE))
    violations = _dimension_coverage_violations(
        dims, DIMENSION_TO_LEG, DIMENSION_KNOWN_GAPS, _HISTORICAL_KNOWN_GAP_DIMENSIONS, gate_funcs)
    assert violations == [], "真身册维度执法覆盖账漂移（逐枚点名见明细）：\n" + "\n".join(violations)


def test_no_manifest_dimension_is_left_dangling() -> None:
    """现状快照锁（S196 更新）：给 board 补真腿并摘牌后，在册无腿维集合恰为空。

    仍是"防悄悄再空挂一枚却没人知道"的快照——只把期望值从 {board} 收紧为空集：
      · 再有一维既无腿又未登记 ⇒ 无腿维 != KNOWN_GAPS（={}) ⇒ 当场点破；
      · 某维补了腿却忘同步 DIMENSION_TO_LEG ⇒ 同样被"无腿 == KNOWN_GAPS"抓。
    两条反真空自证钉"摘牌＝真补腿、不是删维糊绿"。"""
    dims = {
        name for name, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]
    }
    dangling = {d for d in dims if d not in DIMENSION_TO_LEG}
    assert dangling == set(DIMENSION_KNOWN_GAPS) == set(), (
        f"在册无腿维集合变动须同步账：无腿={sorted(dangling)} / 登记={sorted(DIMENSION_KNOWN_GAPS)}")
    # 反真空 ①：board 确在真身册字段里（否则"上面等值"会被"board 已删"假满足＝删维冒充摘牌）。
    assert "board" in dims, "board 已不在 CapabilityFacets？摘牌前须确认是补腿而非删维"
    # 反真空 ②：board 已被 DIMENSION_TO_LEG 认领（否则 KNOWN_GAPS 清空＝把空挂维搬走而非补腿）。
    assert "board" in DIMENSION_TO_LEG, (
        "board 未进 DIMENSION_TO_LEG＝摘牌未真补腿（把豁免删了却没执法＝假摘牌）")


# ---- 注毒自证（证明本锁真有牙；全喂合成数据，不 import 包、不触盘、不改别人写面）----
def test_poison_new_unenforced_dimension_is_red() -> None:
    """注毒①（本席核心关切）：在册面加一个未受检字段 ⇒ 必红。"""
    real_dims = [n for n, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]]
    gate_funcs = gate_top_level_functions(_load_tree(GATE))
    poisoned = real_dims + ["brand_new_unenforced_dim"]
    v = _dimension_coverage_violations(
        poisoned, DIMENSION_TO_LEG, DIMENSION_KNOWN_GAPS, _HISTORICAL_KNOWN_GAP_DIMENSIONS, gate_funcs)
    assert any("[DIM-UNCOVERED]" in s and "brand_new_unenforced_dim" in s for s in v), v
    # 归因唯一：只有 UNCOVERED 该响，其他三类不该被这一发毒顺带触发
    assert sum(1 for s in v if "[DIM-FAKELEG]" in s) == 0, v
    assert sum(1 for s in v if "[DIM-GHOST]" in s) == 0, v
    assert sum(1 for s in v if "[DIM-SELFEXEMPT]" in s) == 0, v


def test_poison_fake_enforcement_leg_is_red() -> None:
    """注毒②：申报的执法腿在门件里根本不存在 ⇒ 假覆盖必红（防"写个不存在的腿名糊账"）。"""
    real_dims = [n for n, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]]
    gate_funcs = gate_top_level_functions(_load_tree(GATE))
    bad = dict(DIMENSION_TO_LEG)
    bad["config_keys"] = "test_leg_that_was_never_written"
    v = _dimension_coverage_violations(
        real_dims, bad, DIMENSION_KNOWN_GAPS, _HISTORICAL_KNOWN_GAP_DIMENSIONS, gate_funcs)
    assert any("[DIM-FAKELEG]" in s and "config_keys" in s for s in v), v


def test_poison_new_field_cannot_self_exempt_via_roster() -> None:
    """注毒③：新维度靠自塞 KNOWN_GAPS 逃避执法 ⇒ 必红（历史白名单只准缩、不许被新维撑大）。"""
    real_dims = [n for n, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]]
    gate_funcs = gate_top_level_functions(_load_tree(GATE))
    poisoned_dims = real_dims + ["sneaky_dim"]
    bad_gaps = dict(DIMENSION_KNOWN_GAPS)
    bad_gaps["sneaky_dim"] = "想塞名册蒙过去"
    v = _dimension_coverage_violations(
        poisoned_dims, DIMENSION_TO_LEG, bad_gaps, _HISTORICAL_KNOWN_GAP_DIMENSIONS, gate_funcs)
    assert any("[DIM-SELFEXEMPT]" in s and "sneaky_dim" in s for s in v), v
    # 归因分工：sneaky_dim 只该被 SELFEXEMPT 抓到（它已进入 covered 集），不该同时被 UNCOVERED 报
    assert not any("[DIM-UNCOVERED]" in s and "sneaky_dim" in s for s in v), v
    # 反证：若把该维也塞进历史白名单（=主代理故意留痕）才允许通过——但白名单在 frozenset 字面量里、
    # 修改必须显式改动本文件常量，不是运行时能"顺手"办到的（这是"故意留痕"的形态）。
    wider = _dimension_coverage_violations(
        poisoned_dims, DIMENSION_TO_LEG, bad_gaps,
        frozenset({"board", "sneaky_dim"}), gate_funcs)
    assert not any("[DIM-SELFEXEMPT]" in s and "sneaky_dim" in s for s in wider), wider


def test_poison_ghost_ledger_entry_is_red() -> None:
    """注毒④：账上留着一维而真身册已删该字段 ⇒ 幽灵维必红（册瘦身账要跟）。"""
    real_dims = [n for n, _a, _d in dataclass_field_specs(_load_tree(MANIFEST))["CapabilityFacets"]]
    shrunk = [d for d in real_dims if d != "trigger_source"]  # 模拟册删了 trigger_source
    gate_funcs = gate_top_level_functions(_load_tree(GATE))
    v = _dimension_coverage_violations(
        shrunk, DIMENSION_TO_LEG, DIMENSION_KNOWN_GAPS, _HISTORICAL_KNOWN_GAP_DIMENSIONS, gate_funcs)
    assert any("[DIM-GHOST]" in s and "trigger_source" in s for s in v), v
