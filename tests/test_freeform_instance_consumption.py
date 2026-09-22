"""S196 freeform「启用前置锁」：有槽无消费方 = 假绿（席 S196，2026-09-22 立）。

任务书（`BRIEFS.md`《第廿九批》《S196》）一句话：
`doc_template_sync.py` 的自由槽机制（`Schema.freeform` / `freeform_guard()` /
`_freeform_allowed_template_ids()` / `freeform_instances()`）**已存在**，但全仓**没有任何一把锁
验证「声明了 freeform 的模板，其自由槽真被某个实例消费过」**——即「机制存在但装配落空」
（紧急域 D-8(a) 前例）。若此刻再启用三枚候选模板的 freeform，账面显示「该类已可驱动」，实际零页受益。

本门只锁这一件事，四条锁：

- 锁一（②）：**声明 freeform 而实例数为 0 的模板 = 零消费方违规**。今日现算违规全集
  ＝ `handbook / handoff / incident-report / runbook` 四枚（且这四枚今日**连一枚驱动页都没有**）。
  执法形态＝**只准减的棘轮**：新增一枚「零消费方就启用 freeform」⇒ 立刻红；
  存量四枚记成手写欠账，驱动到位即摘牌。
  为什么不写成无条件硬红：本波开工时四枚已经 `freeform: on`（S153 落码），
  写死硬红＝今天整棵树红，而简报要的是**启用前置**（拦住第五枚、并给存量记欠账）。
  该取舍已在 `SEAT-S196.md` 首段如实交回主会话裁定，判据本体一字未放宽。
- 锁二（③）：自由槽的**资格判据只准用真身**——装载期一律走 `dts.freeform_guard(schemas)`，
  本门另加一条「在册即须在允许集」的反向核对（`sgc.freeform_allowed_template_ids()`），
  两支判据若不一致（能过 A 过不了 B）**不调和**，如实红并点名交回主会话（公共面缺陷）。
- 锁三（④）：每枚模板的 freeform **实例数只准升不准降**，基线＝本席现算手写字面量。
- 锁四（⑤）：**启用前置实证**——三枚候选模板（`SEAT-S184.md` 的桶：`sdd-ledger`／`brief`／
  `seat-report`，本席现算核实其 id 与必选槽）在被 S198 之类席位驱动之前，
  谁先把 `freeform: on` 加上，本锁必须拦住。

六件套骨架（照抄 `tests/test_schema_slot_direction_lock.py` 的 S150 先例，未自创）：
① 单一取数口（`load_schemas` + `walk_content_pages` + `annotate` + `freeform_instances`，
   本文件**不重解析模板头**——重解析＝第二真身，假绿册形态之一）；
② 基准＝手写字面量 + AST 自锁（`Assign`/`AnnAssign` 双形态，禁派生表达式）；
③ 方向锁（实例数只升不降、零消费方集合只减不增）；④ 扫描面地板（模板面/页面/自由槽面三档）；
⑤ 反向自测全走内存样本（不往 `docs/templates/**` 写一个字）；⑥ 正样控制（判据看得见合法件）。

§0 六禁对齐：让本门变绿只有一条合法路——**把自由槽真驱动出来**。
不许：缩小扫描面、调小基线、加 skip/xfail/noqa、放宽 `freeform_instances` 判据、另建第二取数口。

复跑（四必带环境）：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_freeform_instance_consumption.py -q -s \\
    -p no:cacheprovider --basetemp="$TEMP/s196-bt"
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doc_template_sync as dts
import spec_gates_census as sgc

# ---------------------------------------------------------------------------
# ① 单一取数口（三张表共用一次扫描，禁一文件一次调用）
# ---------------------------------------------------------------------------
_TREE_CACHE: dict[str, tuple[dict[str, dts.Schema], list[Any]]] = {}


def load_tree() -> tuple[dict[str, dts.Schema], list[Any]]:
    """生产取数口：在册模板 + 已标注内容页（`annotate` 只填 fm/violations，不判红）。"""
    cached = _TREE_CACHE.get("tree")
    if cached is not None:
        return cached
    schemas = dts.load_schemas()
    pages = dts.annotate(dts.walk_content_pages(), schemas)
    _TREE_CACHE["tree"] = (schemas, pages)
    return schemas, pages


def freeform_state(
    schemas: dict[str, dts.Schema], pages: list[Any]
) -> dict[str, tuple[int, int]]:
    """`{template_id: (驱动页数, freeform 实例数)}`，只算声明了 freeform 的模板。

    实例数的唯一判据＝真身 `dts.freeform_instances(schema, text)`（观测口，判据仍在
    `check_sections` 一处）；本函数一律不自己正则扫 H2。
    """
    on = sorted(tid for tid, sch in schemas.items() if sch.freeform)
    out: dict[str, tuple[int, int]] = {tid: (0, 0) for tid in on}
    for pg in pages:
        fm = getattr(pg, "fm", None)
        tid = getattr(fm, "template", None) if fm is not None else None
        if tid not in out:
            continue
        schema = schemas[tid]
        inst = dts.freeform_instances(schema, pg.text)
        if inst:
            out[tid] = (out[tid][0] + 1, out[tid][1] + len(inst))
        else:
            out[tid] = (out[tid][0] + 1, out[tid][1])
    return out


def zero_consumer_templates(state: dict[str, tuple[int, int]]) -> list[str]:
    """声明 freeform 而实例数为 0 = 有槽无消费方。"""
    return sorted(tid for tid, (_pages, inst) in state.items() if inst == 0)


def instance_regressions(
    state: dict[str, tuple[int, int]]
) -> list[tuple[str, int, int]]:
    """现算实例数低于手写基线者 = 降实例（只准升不准降）。"""
    bad: list[tuple[str, int, int]] = []
    for tid, base in BASELINE_FREEFORM_INSTANCES.items():
        now = state.get(tid, (0, 0))[1]
        if now < base:
            bad.append((tid, base, now))
    return bad


# ---------------------------------------------------------------------------
# ② 手写基准（本席 2026-09-22 现算值；必须是字面量，由 AST 自锁执法）
# ---------------------------------------------------------------------------
#: 现算：`freeform: on` 的模板 id（枚数 4）。
BASELINE_FREEFORM_ON_SRC: str = "handbook\nhandoff\nincident-report\nrunbook"

#: 现算：上述每枚的 freeform 实例数（锁三基线，只准升）。今日四枚全 0——
#: 连带事实是这四枚今日**没有一枚驱动页**（`驱动页数` 亦全 0，见本文件 `-- -s` 现态表）。
BASELINE_FREEFORM_INSTANCES: dict[str, int] = {
    "handbook": 0,
    "handoff": 0,
    "incident-report": 0,
    "runbook": 0,
}

#: 现算：零消费方欠账（锁一棘轮基线，枚数只准降）。今日＝全部四枚。
BASELINE_ZERO_CONSUMER_SRC: str = "handbook\nhandoff\nincident-report\nrunbook"

#: 锁四候选桶（`SEAT-S184.md` 点名的三枚，本席现算核实：`sdd-ledger`/`brief` 必选槽=0、
#: `seat-report` 必选槽=['交付']；三枚今日 freeform 均为 off）。
CANDIDATE_FREEFORM_TEMPLATES_SRC: str = "sdd-ledger\nbrief\nseat-report"

#: 扫描面地板（三档；现算值 22 模板 / 1499 内容页 / 4 枚启用自由槽。
#: 模板档取 20 而非 22——本席不拥有「谁删模板」的账，只拦「glob 塌陷让判据空转」。
#: 页档取 1200：他波合法增删页会动这个数，留余量而仍非零。自由槽启用档取 1：
#: 今日已有 4 枚启用，若哪天 `freeform` 行被整体摘光＝把尺子拆了，必红。）
_SCAN_FACE_TEMPLATE_FLOOR: int = 20
_SCAN_FACE_PAGE_FLOOR: int = 1200
_SCAN_FACE_FREEFORM_FLOOR: int = 1

_PAIR_SEP = "\n"


def _parse_set(src: str) -> tuple[str, ...]:
    """把多行字面量串解析成有序元组（纯函数，只吃传入参数，绝不读盘）。"""
    return tuple(line for line in src.split(_PAIR_SEP) if line)


BASELINE_FREEFORM_ON: frozenset[str] = frozenset(_parse_set(BASELINE_FREEFORM_ON_SRC))
BASELINE_ZERO_CONSUMER: frozenset[str] = frozenset(_parse_set(BASELINE_ZERO_CONSUMER_SRC))
CANDIDATE_FREEFORM_TEMPLATES: frozenset[str] = frozenset(
    _parse_set(CANDIDATE_FREEFORM_TEMPLATES_SRC)
)


# ---------------------------------------------------------------------------
# 内存样本工厂（⑤ 反向自测用；不落盘、不碰 docs/templates）
# ---------------------------------------------------------------------------
def make_schema(
    tid: str, *, freeform: bool, slots: tuple[tuple[str, bool], ...]
) -> dts.Schema:
    """造一枚内存 Schema：slots = (name, optional)；params/render_zone 本门不读。"""
    dummy_param = dts.Param(key="x", kind="text", source="literal", required=False, domain="t")
    return dts.Schema(
        template_id=tid,
        sections=tuple(dts.Section(n, opt) for n, opt in slots),
        params=(dummy_param,),
        render_zone="{{fact:x}}",
        slot_aliases=tuple(frozenset() for _ in slots),
        freeform=freeform,
    )


class _FakePage:
    """最小 PageInfo 替身（只喂 `freeform_state` 读的四个字段）。"""

    def __init__(self, rel: str, template: str, text: str) -> None:
        self.rel = rel
        self.fm = dts.FrontMatter(template=template, params={}, extra_keys=())
        self.text = text
        self.violations: list[str] = []


#: 内存样本骨架的必选槽名（两页共用；`## 交付` 命中骨架 ⇒ 自由槽实例 0）
_FAKE_REQUIRED_SLOT = "交付"


def _page_with_freeform_section(template: str) -> _FakePage:
    """骨架必选节在位 + 一枚**骨架外** H2 ⇒ 真身 `freeform_instances` 计 1。"""
    return _FakePage(
        rel=f"docs/design/{template}-poison.md",
        template=template,
        text=(
            f"---\ntemplate: {template}\n---\n\n## {_FAKE_REQUIRED_SLOT}\n\n事实。\n\n"
            "## 一枚骨架外的过程小节\n\n内容。\n"
        ),
    )


def _page_without_freeform_section(template: str) -> _FakePage:
    """只有骨架内小节 ⇒ 真身 `freeform_instances` 恒 0（有槽无消费方）。"""
    return _FakePage(
        rel=f"docs/design/{template}-poison2.md",
        template=template,
        text=f"---\ntemplate: {template}\n---\n\n## {_FAKE_REQUIRED_SLOT}\n\n事实。\n",
    )


# ---------------------------------------------------------------------------
# 锁〇：现态表 + 扫描面地板（-s 打印，收尾贴的出处）
# ---------------------------------------------------------------------------
def test_report_current_freeform_state() -> None:
    schemas, pages = load_tree()
    state = freeform_state(schemas, pages)
    assert len(schemas) >= _SCAN_FACE_TEMPLATE_FLOOR, (
        f"在册模板数塌陷（{len(schemas)} < {_SCAN_FACE_TEMPLATE_FLOOR}）＝glob 塌陷、本门空转"
    )
    assert len(pages) >= _SCAN_FACE_PAGE_FLOOR, (
        f"内容页扫描面塌陷（{len(pages)} < {_SCAN_FACE_PAGE_FLOOR}）＝判据在空转"
    )
    assert len(state) >= _SCAN_FACE_FREEFORM_FLOOR, (
        f"启用自由槽的模板数为 0（地板 {_SCAN_FACE_FREEFORM_FLOOR}）＝`freeform` 声明被整体摘光"
    )
    eligible = set(sgc.freeform_allowed_template_ids())
    print("\n=== S196 freeform 现态表（唯一取数口现算，模板 × 实例数）===")
    print(f"在册模板 {len(schemas)} 枚 / 内容页 {len(pages)} 页 / 启用自由槽 {len(state)} 枚")
    for tid in sorted(state):
        driven, inst = state[tid]
        print(
            f"  {tid:<16} freeform=on 驱动页={driven:<4} 实例数={inst:<4} "
            f"基线={BASELINE_FREEFORM_INSTANCES.get(tid)} 在允许集={tid in eligible}"
        )
    print(f"  零消费方（实例数=0）：{zero_consumer_templates(state)}")
    print(f"  允许集（sgc.freeform_allowed_template_ids）：{sorted(eligible)}")
    # 正样控制：判据必须同时看得见「启用」与「未启用」，否则 `sch.freeform` 这条腿没被执行过。
    assert any(not s.freeform for s in schemas.values()), "全树都启用 freeform＝freeform 位判据失去区分力"


# ---------------------------------------------------------------------------
# 锁一（②）：有槽无消费方 ⇒ 新增即红；存量四枚记欠账、只准减
# ---------------------------------------------------------------------------
def test_freeform_declared_but_never_consumed_is_a_debt_ratchet() -> None:
    schemas, pages = load_tree()
    now = set(zero_consumer_templates(freeform_state(schemas, pages)))
    grew = sorted(now - BASELINE_ZERO_CONSUMER)
    assert not grew, (
        f"新增「声明 freeform 却零实例消费」的模板 {grew}＝启用前置锁该拦的那一刀没拦住。"
        "合法修法只有一条：先把该类页面真驱动出来（有 freeform 实例），再加 `freeform: on`。"
    )


def test_freeform_on_set_matches_hand_written_baseline_or_only_shrinks() -> None:
    """启用面与手写基准对账：今日恰为四枚；他日**摘掉**启用（回到骨架）合法，
    **新增**启用必须先过锁一，故此处只查「新增者是否已在欠账基线之外被抓」——由锁一执法，
    本条只钉住「不许悄悄换人」（现算启用集 ⊆ 基线 ∪ 允许集）。"""
    schemas, _pages = load_tree()
    now = {tid for tid, s in schemas.items() if s.freeform}
    eligible = set(sgc.freeform_allowed_template_ids())
    assert now <= (BASELINE_FREEFORM_ON | eligible), (
        f"启用了资格集之外的模板 {sorted(now - (BASELINE_FREEFORM_ON | eligible))}"
    )


# ---------------------------------------------------------------------------
# 锁二（③）：槽名资格只认真身判据（freeform_guard），并核两支一致
# ---------------------------------------------------------------------------
def test_slot_naming_authority_is_freeform_guard_not_a_second_table() -> None:
    """生产装载三处共用 `freeform_guard`；本门不许另发明命名判定 ⇒ 现算必须零违规。"""
    schemas, _pages = load_tree()
    errs = dts.freeform_guard(schemas)
    assert not errs, f"装载期自由槽资格判据红（真身原文）：{errs}"


def test_guard_and_eligibility_source_agree_on_the_real_tree() -> None:
    """两支判据一致性核对（`freeform_guard` vs `freeform_allowed_template_ids`）。
    若不一致 ⇒ **不调和**，红并点名交回主会话（公共面缺陷）。"""
    schemas, _pages = load_tree()
    on = {tid for tid, s in schemas.items() if s.freeform}
    allowed = set(sgc.freeform_allowed_template_ids())
    only_guard_pass = sorted(on - allowed)  # 能过装载却不在允许集
    assert not only_guard_pass, (
        f"判据不一致：{only_guard_pass} 过了 `freeform_guard` 却不在 "
        f"`freeform_allowed_template_ids()` 允许集 ⇒ 公共面缺陷，交回主会话（本席不调和）"
    )
    assert allowed, "允许集为空＝资格取数口塌陷，锁二在空转"


# ---------------------------------------------------------------------------
# 锁三（④）：每枚模板的 freeform 实例数只准升不准降
# ---------------------------------------------------------------------------
def test_freeform_instance_counts_never_shrink() -> None:
    schemas, pages = load_tree()
    bad = instance_regressions(freeform_state(schemas, pages))
    assert not bad, (
        f"freeform 实例数下降 {bad}（模板/基线/现算）＝消费方被拆。"
        "要么把这些小节改回骨架内，要么走模板升级；不许调小基线。"
    )


# ---------------------------------------------------------------------------
# 锁四（⑤）：启用前置实证——三枚候选在驱动之前先加 freeform 必被拦
# ---------------------------------------------------------------------------
def test_candidates_are_not_yet_enabled_and_have_the_expected_shape() -> None:
    """现算核实 `SEAT-S184.md` 的桶：三枚 id 真实存在、今日未启用、且其中两枚必选槽=0
    （即「加了 freeform 直接 `SchemaError`」那一族），一枚（`seat-report`）装得上 ⇒
    它才是必须被本锁拦住的活口。"""
    schemas, _pages = load_tree()
    assert CANDIDATE_FREEFORM_TEMPLATES <= set(schemas), (
        f"候选桶里的模板不在册：{sorted(CANDIDATE_FREEFORM_TEMPLATES - set(schemas))}"
    )
    for tid in CANDIDATE_FREEFORM_TEMPLATES:
        assert not schemas[tid].freeform, f"候选 {tid} 已被启用——先过锁一（零消费方）再说"
    zero_required = sorted(
        tid for tid in CANDIDATE_FREEFORM_TEMPLATES
        if not any(not sec.optional for sec in schemas[tid].sections)
    )
    assert zero_required, "三枚候选全都有必选槽＝S184 的『必选槽=0 直接装载红』结论过期，交回主会话"
    print(f"\n[S196] 候选必选槽=0（加 freeform 即 SchemaError）：{zero_required}")


# ---------------------------------------------------------------------------
# ⑤ 反向自测五发（全内存；每发都是「判据必须有牙」的证明）
# ---------------------------------------------------------------------------
def test_poison1_new_freeform_template_with_zero_instances_is_red() -> None:
    """发一：一枚「声明 freeform、零实例」的假模板 ⇒ 锁一必红（启用前置）。"""
    tid = "yet-unborn-process-ledger"
    fake = {tid: make_schema(tid, freeform=True, slots=(("交付", False), ("骨架外?", True)))}
    state = freeform_state(fake, [_page_without_freeform_section(tid)])
    grew = sorted(set(zero_consumer_templates(state)) - BASELINE_ZERO_CONSUMER)
    assert grew == [tid], f"注毒未被抓到（实得 {grew}）＝探针恒假，本锁没有牙"


def test_poison2_same_template_with_one_instance_is_green() -> None:
    """发二：同枚模板改为「有一页真把自由槽用了」⇒ 必不红（探针非恒真）。"""
    tid = "yet-unborn-process-ledger"
    fake = {tid: make_schema(tid, freeform=True, slots=(("交付", False), ("骨架外?", True)))}
    state = freeform_state(fake, [_page_with_freeform_section(tid)])
    assert zero_consumer_templates(state) == [], "有消费方却被判零消费＝判据反了"
    assert state[tid] == (1, 1), f"实例计数失真（实得 {state[tid]}）"


def test_poison3_real_candidate_seat_report_enabled_without_driver_is_red() -> None:
    """发三：把**真实候选** `seat-report` 在内存里加上 freeform、且没有任何驱动页
    ⇒ 锁一必红（简报⑤要的正是这一刀：S198 驱动之前不许先启用）。"""
    schemas, _pages = load_tree()
    tid = "seat-report"
    assert tid in schemas
    poisoned = dict(schemas)
    poisoned[tid] = make_schema(tid, freeform=True, slots=(("交付", False),))
    # 只喂「该模板零驱动页」的页集，复现"启用而未驱动"的现场
    state = freeform_state({tid: poisoned[tid]}, [])
    grew = sorted(set(zero_consumer_templates(state)) - BASELINE_ZERO_CONSUMER)
    assert grew == [tid], f"候选先启用后驱动未被抓到（实得 {grew}）"
    # 且它在允许集内（S184 结论：`seat-report` 是三枚里唯一装得上的），
    # 说明"能过资格判据"和"有消费方"是两件事——本锁管后者。
    assert tid in set(sgc.freeform_allowed_template_ids())


def test_poison4_instance_count_drop_is_caught() -> None:
    """发四：基线之上把实例拆掉（该页小节改回骨架内）⇒ 锁三必红。"""
    tid = "handbook"
    baseline_one = {tid: 1}
    original = dict(BASELINE_FREEFORM_INSTANCES)
    try:
        BASELINE_FREEFORM_INSTANCES.clear()
        BASELINE_FREEFORM_INSTANCES.update(baseline_one)
        bad = instance_regressions({tid: (1, 0)})
        assert bad == [(tid, 1, 0)], f"实例数下降未被抓到（实得 {bad}）"
    finally:
        BASELINE_FREEFORM_INSTANCES.clear()
        BASELINE_FREEFORM_INSTANCES.update(original)


def test_poison5_ineligible_template_declaring_freeform_is_red_by_guard() -> None:
    """发五：一枚**不在允许集**的模板声明 freeform ⇒ 资格判据（真身 `freeform_guard`）必红，
    证明本门没有把"资格"这半桩糊过去（槽名/资格判定只有真身一支）。"""
    tid = "现役规格类模板-不该有自由槽"
    fake = {tid: make_schema(tid, freeform=True, slots=(("交付", False),))}
    errs = dts.freeform_guard(fake)
    assert errs and tid in errs[0], f"非资格模板启用 freeform 未被真身判据抓到（实得 {errs}）"


# ---------------------------------------------------------------------------
# ⑥ AST 自锁：所有基准/地板必须是手写字面量，不许由取数口派生
# ---------------------------------------------------------------------------
def test_baselines_are_hand_written_literals_not_derived() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(tree):
        value: ast.expr | None
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            value = node.value
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value, targets = node.value, [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = value

    for name in (
        "BASELINE_FREEFORM_ON_SRC",
        "BASELINE_ZERO_CONSUMER_SRC",
        "CANDIDATE_FREEFORM_TEMPLATES_SRC",
    ):
        entry = assigned.get(name)
        assert isinstance(entry, ast.Constant) and isinstance(entry.value, str), (
            f"{name} 被改成派生表达式＝基准跟着现算走，锁一/锁四作废"
        )
    counts = assigned.get("BASELINE_FREEFORM_INSTANCES")
    assert isinstance(counts, ast.Dict), (
        "BASELINE_FREEFORM_INSTANCES 必须是字面量字典，不许 freeform_state(...) 派生"
    )
    for key, val in zip(counts.keys, counts.values):
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        assert isinstance(val, ast.Constant) and isinstance(val.value, int) and not isinstance(
            val.value, bool
        ), "实例基线必须逐枚写字面量整数"
    for name in (
        "_SCAN_FACE_TEMPLATE_FLOOR",
        "_SCAN_FACE_PAGE_FLOOR",
        "_SCAN_FACE_FREEFORM_FLOOR",
    ):
        entry = assigned.get(name)
        assert isinstance(entry, ast.Constant) and isinstance(entry.value, int), (
            f"{name} 必须是字面量整数，不许 len(...) 派生"
        )
    for name in (
        "BASELINE_FREEFORM_ON",
        "BASELINE_ZERO_CONSUMER",
        "CANDIDATE_FREEFORM_TEMPLATES",
    ):
        entry = assigned.get(name)
        assert isinstance(entry, ast.Call) and isinstance(entry.func, ast.Name) and entry.func.id == "frozenset", (
            f"{name} 必须由 frozenset(_parse_set(手写字面量串)) 得到"
        )
        inner = entry.args[0] if entry.args else None
        assert isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "_parse_set", (
            f"{name} 的入参必须是 _parse_set(字面量串)"
        )
