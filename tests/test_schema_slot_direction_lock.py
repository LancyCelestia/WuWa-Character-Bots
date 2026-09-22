"""S150 必选槽「只升不降方向锁」常驻门（席 S150，2026-09-22 立）。

任务书（BRIEFS.md《S150》）：S141 现算证伪 S125 的机械判据「必选 ⇔ 覆盖页数 > 2/3」
——拿该判据去套**在册必选集自己**，今天就要降 3 枚必选（`改动清单`／`复跑命令簿` 等）＝放宽判据。
本门把「在册必选槽集合」钉成**只准增、不准减**的方向锁：

- 在册必选集 = `load_schemas()` 现算的 `{(template_id, section_name) | not section.optional}`（唯一取数口）。
- 基准值 = 本席开工时刻（2026-09-22）现算的那一套 57 枚（写成本文件的**手写字面量**，是**新账**，不改任何旧账/上限）。
- 任何一枚在册必选**被摘掉**（改成可选 / 从 sections 删除 / 模板被删）⇒ 本门红，点名「谁在降必选」。

六件套骨架（照抄 `tests/test_taxonomy_spec_gates.py`，未自创）：
① 单一取数口；② 基准=手写字面量 + AST 自锁（`Assign` 与 `AnnAssign` 双形态，禁派生表达式）；
③ 方向锁（基准 ⊆ 现算，且基准枚数不许被改小）；④ 扫描面地板（塌陷即红）；
⑤ 反向自测全走内存样本（**不往 `docs/templates/**` 写一个字**）；⑥ 正样控制（判据看得见合法件本身）。

§0 六禁对齐：让本门变绿**只有**一条合法路——把被摘掉的必选槽改回必选。
不许：缩小扫描面、调小基准枚数、加 skip/xfail/noqa、放宽 `not optional` 判据、发明第二取数口。

复跑（四必带环境）：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_schema_slot_direction_lock.py -q \\
    -p no:cacheprovider --basetemp="$TEMP/s150"
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doc_template_sync as dts

# ---------------------------------------------------------------------------
# ① 单一取数口：在册必选集现算（{(template_id, section_name)}，optional=False）
# ---------------------------------------------------------------------------
FieldSep = "\t"
PairSep = "\n"


def required_pairs_from(schemas: dict[str, dts.Schema]) -> frozenset[tuple[str, str]]:
    """唯一取数：把一批 Schema 里的必选槽（非 optional 的 section）现算成 (模板, 槽名) 集合。

    判据 `not sec.optional` 与 `load_schemas()` 装载 `Section(..., s.endswith("?"))` 同源，
    禁在此另立第二套必选定义。
    """
    return frozenset(
        (tid, sec.name)
        for tid, schema in schemas.items()
        for sec in schema.sections
        if not sec.optional
    )


def current_required_slots() -> frozenset[tuple[str, str]]:
    """生产取数口：读真树模板 → 现算在册必选集。"""
    return required_pairs_from(dts.load_schemas())


# ---------------------------------------------------------------------------
# ② 手写基准（新账，非改旧账）：必须是 ast.Constant 字面量，由 AST 自锁执法。
#    基准值 = 2026-09-22 本席开工时刻 `current_required_slots()` 现算的那 57 枚。
#    每行 `模板<TAB>槽名`；枚数见 BASELINE_SIZE_FLOOR。
# ---------------------------------------------------------------------------
BASELINE_REQUIRED_SLOTS_SRC: str = "card-fstring\t壳与注入\ncard-fstring\t契约锚点\ncard-fstring\t登记入口\ncard-html\t变量供给\ncard-html\t契约锚点\ncard-html\t降级路径\ncard-jinja\t模板契约\ncard-jinja\t注入上下文\ncard-jinja\t降级路径\nconfig-field\t取值域与默认\nconfig-field\t说明形状\nconfig-field\t键与类型\nconvention\t代码质量红线\nconvention\t命名规范\nconvention\t开发约束\nconvention\t文件结构规范\nconvention\t术语与结构\nconvention\t统一口径\nconvention\t自动化变更契约\nconvention\t问题处理分级\ncopy-pool\t副本与游标\ncopy-pool\t池身份\ncopy-pool\t红线\ndesign-spec\t目的与范围\ndesign-spec\t设计\ndesign-spec\t验收\nguide\t正文\nguide\t用途\nguide\t读者\nhandbook\t文档族谱与权威链\nhandbook\t未完成总账\nhandbook\t现行事实速查\nhandoff\t复跑命令簿\nhandoff\t改动清单\nhandoff\t概览\nhandoff\t现状\nhandoff\t问题与处置\nhelp-entry\t元数据 schema\nhelp-entry\t字段序\nhelp-entry\t生成物\nincident-report\t事实与时间线\nincident-report\t处置\nincident-report\t影响面\nledger\t取数口\nledger\t口径\nledger\t用途\nledger\t维护规矩\npersona\t表达规范\npersona\t身份设定\npersona\t边界与红线\npersona-inject-data\t一、鸣潮核心名词\npersona-inject-data\t二、游戏黑话/缩写\nrunbook\t前置\nrunbook\t检查表\nrunbook\t步骤\nseat-report\t交付\nworkspace-rule\t工作区规则"

#: 基准枚数地板（手写字面量整数）。与基准串逐位对拍＝57（2026-09-22 本席现算）。
#: 只有本文件 owner 在**新增**合法必选槽时才可上调；任何调小即被方向锁抓到。
BASELINE_SIZE_FLOOR: int = 57

#: 扫描面地板（开工时现算：22 张在册模板）。低于此＝glob 塌陷／装载大面积炸，判据在空转。
_SCAN_FACE_TEMPLATE_FLOOR: int = 22


def parse_baseline(src: str) -> frozenset[tuple[str, str]]:
    """把手写基准串解析成 (模板, 槽名) 集合（纯函数，只吃传入参数，绝不读盘）。"""
    out: set[tuple[str, str]] = set()
    for line in src.split(PairSep):
        if not line:
            continue
        tid, sep, name = line.partition(FieldSep)
        if not sep:
            raise AssertionError(f"基准串行缺字段分隔符（TAB）：{line!r}")
        out.add((tid, name))
    return frozenset(out)


BASELINE_REQUIRED_SLOTS = parse_baseline(BASELINE_REQUIRED_SLOTS_SRC)


# ---------------------------------------------------------------------------
# 方向锁判据本体（纯函数，便于注毒走内存样本）
# ---------------------------------------------------------------------------
def demotion_violations(
    current: frozenset[tuple[str, str]], baseline: frozenset[tuple[str, str]]
) -> list[tuple[str, str]]:
    """基准里存在、现算里已不被判必选的槽 = 被降必选者（升必选不在此列，天然放行）。"""
    return sorted(baseline - current)


def _template_file(tid: str) -> str:
    return f"docs/templates/{tid}.md"


# ---------------------------------------------------------------------------
# ③ 主判据：在册必选集只准增、不准减（基准 ⊆ 现算）
# ---------------------------------------------------------------------------
def test_registered_required_slots_are_never_demoted() -> None:
    current = current_required_slots()
    bad = demotion_violations(current, BASELINE_REQUIRED_SLOTS)
    if bad:
        who = "；".join(f"{tid}::{name}（降必选点在 {_template_file(tid)} 的 sections 行）" for tid, name in bad)
        raise AssertionError(
            "必选槽被降级＝放宽判据（S125 机械判据被在册集自身证伪那一族的复发）。"
            f"谁在降必选：{who}。合法修法只有把该槽改回必选（去掉 `?`），不许调小基准、不许删断言。"
        )


# ---------------------------------------------------------------------------
# ②b 基准枚数地板：基准集本身不许被改小（防有人从字面量里抠行躲检）
# ---------------------------------------------------------------------------
def test_baseline_size_floor_never_shrinks() -> None:
    assert len(BASELINE_REQUIRED_SLOTS) >= BASELINE_SIZE_FLOOR, (
        f"基准必选枚数被改小（现 {len(BASELINE_REQUIRED_SLOTS)} < 地板 {BASELINE_SIZE_FLOOR}）"
        "＝有人从手写字面量里摘行来让方向锁闭眼。方向锁只准增不准减。"
    )


# ---------------------------------------------------------------------------
# ④ 扫描面地板：判据必须真的在看东西（空转假绿的反面）
# ---------------------------------------------------------------------------
def test_scan_face_has_not_collapsed() -> None:
    schemas = dts.load_schemas()
    assert len(schemas) >= _SCAN_FACE_TEMPLATE_FLOOR, (
        f"在册模板数塌陷（{len(schemas)} < {_SCAN_FACE_TEMPLATE_FLOOR}）——glob/装载被缩，本门在空转"
    )
    current = current_required_slots()
    assert current, "现算必选集为空＝判据没吃到任何合法件，红绿都无意义"
    # 正样控制：合法件里必须同时看得见必选与可选，否则「not optional」这条腿根本没被执行过。
    optional_pairs = frozenset(
        (tid, sec.name)
        for tid, schema in schemas.items()
        for sec in schema.sections
        if sec.optional
    )
    assert optional_pairs, "全树无可选槽＝optional 判据这条腿从未被区分，正样控制失效"


# ---------------------------------------------------------------------------
# ⑥ AST 自锁：基准值必须是手写字面量（ast.Constant），不许写成 load_schemas() 派生
#    ——否则基准跟着被检对象一起动，本门结构性失效（假绿）。
# ---------------------------------------------------------------------------
def test_baseline_is_hand_written_literal_not_derived() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
        else:
            continue
        for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets):
            if isinstance(target, ast.Name):
                assigned[target.id] = value

    src = assigned.get("BASELINE_REQUIRED_SLOTS_SRC")
    assert isinstance(src, ast.Constant) and isinstance(src.value, str), (
        "BASELINE_REQUIRED_SLOTS_SRC 被改成派生表达式（如 join(load_schemas())）＝基准跟着现算走，方向锁作废"
    )
    floor = assigned.get("BASELINE_SIZE_FLOOR")
    assert isinstance(floor, ast.Constant) and isinstance(floor.value, int) and not isinstance(
        floor.value, bool
    ), "BASELINE_SIZE_FLOOR 必须是字面量整数，不许 len(...) 派生（那会被摘行反推塌下来）"
    scan_floor = assigned.get("_SCAN_FACE_TEMPLATE_FLOOR")
    assert isinstance(scan_floor, ast.Constant) and isinstance(scan_floor.value, int), (
        "_SCAN_FACE_TEMPLATE_FLOOR 必须是字面量整数，不许派生"
    )
    # 取数口自身不得在模块级被写成 `BASELINE = current_required_slots()`（基准必须来自字面量串）
    base = assigned.get("BASELINE_REQUIRED_SLOTS")
    assert isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "parse_baseline", (
        "BASELINE_REQUIRED_SLOTS 必须由 parse_baseline(手写字面量串) 得到，不许直接等于现算取数口"
    )


# ---------------------------------------------------------------------------
# ⑤ 反向自测三发（内存样本，不碰源码树）
# ---------------------------------------------------------------------------
def _one_schema(tid: str, *slots: tuple[str, bool]) -> dict[str, dts.Schema]:
    """造一枚内存 Schema：slots = (name, optional)。params/render_zone 用占位（本门不读）。"""
    dummy_param = dts.Param(key="x", kind="text", source="literal", required=False, domain="t")
    zone = "{{fact:x}}"
    return {
        tid: dts.Schema(
            template_id=tid,
            sections=tuple(dts.Section(n, opt) for n, opt in slots),
            params=(dummy_param,),
            render_zone=zone,
        )
    }


def test_poison_drop_one_required_is_caught() -> None:
    """a) 摘掉一枚基准必选（改成可选）⇒ 方向锁必红并点名。"""
    tid, name = next(iter(BASELINE_REQUIRED_SLOTS))
    shrunk = _one_schema(tid, (name, True))  # 曾经必选，现在 optional=True
    current = required_pairs_from(shrunk)
    bad = demotion_violations(current, frozenset({(tid, name)}))
    assert (tid, name) in bad, "摘必选未被抓到＝方向锁没牙（假绿）"


def test_poison_add_one_optional_is_allowed() -> None:
    """b) 新增一枚可选槽 ⇒ 在册必选集不缩，方向锁放行（只准增的『增』合法）。"""
    tid, name = next(iter(BASELINE_REQUIRED_SLOTS))
    grown = _one_schema(tid, (name, False), ("新增可选小节", True))
    current = required_pairs_from(grown)
    assert demotion_violations(current, frozenset({(tid, name)})) == [], "加可选槽被误判为降必选＝判据反了"


def test_poison_baseline_claimed_as_future_value_is_red() -> None:
    """c) 把基准改成『未来值』（塞进现算里还不存在的必选）⇒ 自锁必红（基准枚数地板 + 子集方向锁双向抓）。"""
    ghost_tid, ghost_name = "yet-unborn-template", "未来的必选槽"
    ghost_baseline = BASELINE_REQUIRED_SLOTS | {(ghost_tid, ghost_name)}
    current = current_required_slots()  # 现算里没有这枚幽灵
    assert demotion_violations(current, ghost_baseline), "基准被改成未来值却没被抓到＝方向锁可被架空"
    # 且枚数地板随基准被抠行时（反向：基准 < 地板）也必须红
    assert len(BASELINE_REQUIRED_SLOTS) >= BASELINE_SIZE_FLOOR
