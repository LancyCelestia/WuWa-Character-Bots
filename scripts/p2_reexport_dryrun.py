"""``scripts/p2_reexport_dryrun.py`` — P2「三处旧账降为再导出垫片」**干跑取证量具**（席位 S58）。

## 本件是什么、不是什么
- **是**：一把只读的尺。它不写任何生产文件、不迁移任何一张表、不起进程、不读 config、不碰网络。
  它对 P2 的三个降壳目标面（①多模态 tags ②板块 taxonomy ③旧 registry）各现算三件事——
  (a) 真身册 ``domains/core/capability_manifest.py`` 里**对应字段**的现值集合，
  (b) 该旧账**消费方实际读到**的值集合，
  (c) 消费方清单（谁 import / 谁按路径 AST 读 / 哪些门断言成员数或顺序），
  再把 (a)↔(b) 归入三态 ``identical`` / ``subset|superset`` / ``incompatible``，
  差集逐条点名、不可搬运形态逐条入册，最后给一份「先搬哪面最安全、每批搬完必跑哪几把门」的建议执行序。
- **不是**：迁移本体。迁移落地权在主代理；本件只出可粘贴执行的证据。它也**不是**常驻门禁
  （不落 tests/），是一次性干跑取证。

## 为什么三态一定带牙（不是"永远 identical"）
- 三态判据是**纯函数** ``classify()``：只吃显式传入的集合与标志，绝不读全局——便于注毒直接打靶。
- ``incompatible`` 优先于 ``identical``：只要消费方所读的任一符号是**函数 / Enum owner /
  MappingProxy 容器 / 运行期 f-string 构造**这类不可从值表"字面再导出"的形态，
  或真身册**根本不持有**该符号，即便值集合恰好相等也判 ``incompatible``（降壳即断供）。
  —— 造绿六禁里的"放宽判据 / 预填达标值"在此一票否决：判红就是判红，不许美化。
- **不可判态也判红**：某面因加载失败/符号缺失而算不出，记 ``incompatible(undetermined)``
  并点名，绝不静默跳过、绝不降级成"没扫到=没问题"。

## 独立文件加载（不触发插件重根）
三面旧账 + 真身册都是「只声明数据、不 import 包内任何模块」的自持件（顶层仅 stdlib，
且都 ``from __future__ import annotations``）。本件用 ``importlib.util.spec_from_file_location``
配**非点号合成模块名**加载，绕开 ``plugins/bot_unified_runtime/__init__.py``（NoneBot 重根），
加载后校验未把 ``nonebot`` 拽进该模块命名空间，否则判不可判。

## 复跑
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
    PYTHONPYCACHEPREFIX=$TEMP/s58-pyc \
    ../ChatBot_Runtime/venv/Scripts/python.exe scripts/p2_reexport_dryrun.py --report
    # 只验牙（不读生产面）：--selftest
    # 机器形态：--json
退出码：0=报告正常产出；3=自证失牙（判据被写松，红）。
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PKG_ROOT: Final[Path] = REPO_ROOT / "plugins" / "bot_unified_runtime"

MANIFEST_PATH: Final[Path] = PKG_ROOT / "domains" / "core" / "capability_manifest.py"

#: 三面旧账的仓内相对路径（供按路径 AST 读的消费者识别用）。
_REL = "plugins/bot_unified_runtime"


# =========================================================================
# 独立文件加载（只读、绕重根）
# =========================================================================
def load_standalone(path: Path, synth_name: str) -> types.ModuleType:
    """按文件路径独立加载一个自持模块；解析不出/拽进重依赖即抛（绝不当"没扫到"）。"""
    if not path.is_file():
        raise FileNotFoundError(f"干跑加载失败：文件不存在 {path}")
    spec = importlib.util.spec_from_file_location(synth_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"干跑加载失败：无法为 {path} 构造 import spec")
    module = importlib.util.module_from_spec(spec)
    # 经典 importlib 坑：dataclass/枚举在 __set_name__ 与 _process_class 里会
    # ``sys.modules[cls.__module__]`` 反查本模块符号，未注册即 None.__dict__ 崩。
    # 故 exec 前先挂进 sys.modules，失败再摘掉，绝不污染既有模块命名空间。
    sys.modules[synth_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(synth_name, None)
        raise
    # 防线：这些文件顶层不该 import nonebot；若被拽进，说明"自持"前提破了 ⇒ 判不可判。
    if any(name.startswith("nonebot") for name in getattr(module, "__dict__", {})):
        sys.modules.pop(synth_name, None)
        raise ValueError(f"干跑加载失败：{path} 顶层 import 了 nonebot，非自持件")
    sys.modules.pop(synth_name, None)
    return module


# =========================================================================
# 三态判据（纯函数，注毒直接打靶；不吃全局、不读盘）
# =========================================================================
STATE_IDENTICAL: Final[str] = "identical"
STATE_DIFF: Final[str] = "subset|superset"
STATE_INCOMPATIBLE: Final[str] = "incompatible"


@dataclass(frozen=True)
class Decision:
    """一面的三态判定结果（含差集名册与理由，供报告逐条点名）。"""

    state: str
    manifest_only: tuple[str, ...]
    consumer_only: tuple[str, ...]
    reasons: tuple[str, ...]
    determinate: bool


def classify(
    *,
    manifest_values: frozenset[str],
    consumer_values: frozenset[str],
    manifest_missing_symbols: tuple[str, ...],
    non_transplantable_symbols: tuple[str, ...],
    determinate: bool = True,
) -> Decision:
    """把「册现值集合 vs 消费方读到集合 + 形态阻断」归入三态。

    优先级（写死，防放宽）：不可判 > 形态阻断(incompatible) > 缺符号(incompatible)
    > identical > 差集(subset|superset)。差集两侧都点名，指明谁多谁少。
    """
    if not determinate:
        return Decision(
            state=STATE_INCOMPATIBLE,
            manifest_only=(),
            consumer_only=(),
            reasons=("不可判：该面无法算出可靠集合（加载失败/符号缺失），按红处理，绝不静默跳过",),
            determinate=False,
        )
    manifest_only = tuple(sorted(manifest_values - consumer_values))
    consumer_only = tuple(sorted(consumer_values - manifest_values))
    reasons: list[str] = []
    state = STATE_IDENTICAL
    if non_transplantable_symbols:
        state = STATE_INCOMPATIBLE
        reasons.append(
            "消费面含不可字面再导出形态（函数/Enum owner/MappingProxy/运行期 f-string）："
            + "、".join(sorted(non_transplantable_symbols))
        )
    if manifest_missing_symbols:
        state = STATE_INCOMPATIBLE
        reasons.append(
            "真身册未持有消费方所读符号，降壳即断供：" + "、".join(sorted(manifest_missing_symbols))
        )
    if state != STATE_INCOMPATIBLE:
        # 只有册供得出全部消费符号且无形态阻断，才轮到纯值集合比较。
        if manifest_values == consumer_values:
            state = STATE_IDENTICAL
            reasons.append("值集合逐元素相等：可零风险降壳（册已是该维度唯一值源）")
        else:
            state = STATE_DIFF
            if manifest_only:
                reasons.append("册比消费方多的（降壳会给消费方新增行为，须点名）：" + "、".join(manifest_only))
            if consumer_only:
                reasons.append("消费方比册多的（降壳会丢数据，须点名）：" + "、".join(consumer_only))
    return Decision(
        state=state,
        manifest_only=manifest_only,
        consumer_only=consumer_only,
        reasons=tuple(reasons),
        determinate=True,
    )


# =========================================================================
# 每面规格：消费方读什么符号、册的对应字段是什么、共享可比单元怎么取
# =========================================================================
@dataclass(frozen=True)
class FacetSpec:
    key: str
    display: str
    legacy_path: Path
    #: 消费方从该旧账读到的公开数据符号（薄壳要 re-export 的最低面）。
    consumed_data_symbols: tuple[str, ...]
    #: 消费方从该旧账读到的公开可调用符号（函数/类）——不可字面 re-export ⇒ 形态阻断。
    consumed_call_symbols: tuple[str, ...]
    #: 册里理论上可作 re-export 源的符号名（今日多半不存在 ⇒ manifest_missing）。
    manifest_candidate_symbols: tuple[str, ...]


FACETS: Final[tuple[FacetSpec, ...]] = (
    FacetSpec(
        key="tags",
        display="①多模态 tags（channel_capability_tags.py）",
        legacy_path=PKG_ROOT / "domains" / "core" / "channel_capability_tags.py",
        consumed_data_symbols=("NATIVE_TAG_PREFIX", "NATIVE_MEDIA_KINDS", "CHANNEL_CAPABILITY_KINDS"),
        consumed_call_symbols=(
            "capability_tag", "capability_tags_for", "declared_native_media_kinds",
            "is_capability_tag", "split_capability_tags", "preserve_capability_tags",
            "missing_capability_tags",
        ),
        manifest_candidate_symbols=("CHANNEL_CAPABILITY_KINDS", "NATIVE_MEDIA_KINDS", "NATIVE_TAG_PREFIX"),
    ),
    FacetSpec(
        key="board",
        display="②板块 taxonomy（board_taxonomy.py）",
        legacy_path=PKG_ROOT / "domains" / "core" / "board_taxonomy.py",
        consumed_data_symbols=("BOARD_TAXONOMY", "TAXONOMY_VERSION"),
        consumed_call_symbols=("board_by_id", "iter_features", "feature_by_id", "BoardNode", "FeatureNode"),
        manifest_candidate_symbols=("BOARD_TAXONOMY", "TAXONOMY_VERSION"),
    ),
    FacetSpec(
        key="registry",
        display="③旧 registry（domains/chat_reply/runtime/capability_registry.py）",
        legacy_path=PKG_ROOT / "domains" / "chat_reply" / "runtime" / "capability_registry.py",
        consumed_data_symbols=(
            "ROUTE_CAPABILITY_DECLARATIONS", "CONTROLLED_INTERNAL_CAPABILITIES",
            "HELP_TOPIC_DECLARATIONS", "INTERFACE_DECLARATIONS",
            "PIPELINE_MANAGED_CAPABILITY_DECLARATIONS", "COMMAND_ROUTE_KIND_NAMES",
        ),
        consumed_call_symbols=(
            "RouteCapabilityDecl", "CapabilityExecution", "InterfaceDecl",
            "HelpTopicDecl", "PipelineManagedExecution",
        ),
        manifest_candidate_symbols=("ROUTE_CAPABILITY_DECLARATIONS", "CONTROLLED_INTERNAL_CAPABILITIES"),
    ),
)


def _is_non_transplantable(obj: object) -> bool:
    """该对象能否被值表"字面再导出"？函数/类（含 Enum owner）/MappingProxy 容器 ⇒ 否。"""
    return isinstance(obj, (types.FunctionType, type, MappingProxyType))


def _native_kinds_of_manifest(manifest: types.ModuleType) -> frozenset[str]:
    """册里 native-* 能力标签对应的裸 kind 集合（今日应为空——EVIDENCE 未收 native 票根）。"""
    tags: Any = getattr(manifest, "FACETS", MappingProxyType({}))
    prefix = "native-"
    out: set[str] = set()
    for row in tags.values():
        for tag in getattr(row, "tags", ()) or ():
            value = getattr(tag, "value", str(tag))
            if value.startswith(prefix):
                out.add(value[len(prefix):])
    return frozenset(out)


def _board_ids_of_manifest(manifest: types.ModuleType) -> frozenset[str]:
    tags: Any = getattr(manifest, "FACETS", MappingProxyType({}))
    return frozenset(str(row.board) for row in tags.values() if getattr(row, "board", ""))


def _capability_ids_of_manifest(manifest: types.ModuleType) -> frozenset[str]:
    fn = getattr(manifest, "declared_ids", None)
    if callable(fn):
        return frozenset(str(x) for x in fn())
    return frozenset(str(k) for k in getattr(manifest, "FACETS", {}))


def _native_kinds_of_tags_facet(facet: types.ModuleType) -> frozenset[str]:
    table = getattr(facet, "CHANNEL_CAPABILITY_KINDS", {}) or {}
    out: set[str] = set()
    for kinds in table.values():
        out.update(str(kind) for kind in kinds)
    return frozenset(out)


def _board_ids_of_board_facet(facet: types.ModuleType) -> frozenset[str]:
    tree = getattr(facet, "BOARD_TAXONOMY", ()) or ()
    return frozenset(str(board.bid) for board in tree)


def _capability_ids_of_registry_facet(facet: types.ModuleType) -> frozenset[str]:
    out: set[str] = set()
    for decl in getattr(facet, "ROUTE_CAPABILITY_DECLARATIONS", ()) or ():
        out.add(str(decl.capability_id))
    out.update(str(cid) for cid in getattr(facet, "CONTROLLED_INTERNAL_CAPABILITIES", ()) or ())
    for row in getattr(facet, "PIPELINE_MANAGED_CAPABILITY_DECLARATIONS", ()) or ():
        out.add(str(row.capability_id))
    return frozenset(out)


#: key -> (册侧取值函数, 旧账侧取值函数)
_VALUE_PROBE: Final[dict[str, tuple[Any, Any]]] = {
    "tags": (_native_kinds_of_manifest, _native_kinds_of_tags_facet),
    "board": (_board_ids_of_manifest, _board_ids_of_board_facet),
    "registry": (_capability_ids_of_manifest, _capability_ids_of_registry_facet),
}


@dataclass
class FacetResult:
    spec: FacetSpec
    decision: Decision
    manifest_values: frozenset[str]
    consumer_values: frozenset[str]
    non_transplantable: tuple[str, ...]
    manifest_missing: tuple[str, ...]
    consumers: list[Consumer] = field(default_factory=list)


def analyze_facet(spec: FacetSpec, manifest: types.ModuleType, determinate_default: bool) -> FacetResult:
    """现算一面：加载旧账、抽值集合、判不可搬运、比册缺符号，喂 classify。"""
    loaded: types.ModuleType | None = None
    err: Exception | None = None
    det = determinate_default
    try:
        loaded = load_standalone(spec.legacy_path, f"_s58_{spec.key}")
    except Exception as exc:  # noqa: BLE001 - 不可判本身是要点名的红，绝不静默
        det = False
        err = exc

    if not det or loaded is None:
        decision = classify(
            manifest_values=frozenset(),
            consumer_values=frozenset(),
            manifest_missing_symbols=(),
            non_transplantable_symbols=(),
            determinate=False,
        )
        decision = Decision(
            state=decision.state,
            manifest_only=(),
            consumer_only=(),
            reasons=decision.reasons + (f"加载异常点名：{type(err).__name__}: {err}",),
            determinate=False,
        )
        return FacetResult(spec, decision, frozenset(), frozenset(), (), ())

    manifest_probe, facet_probe = _VALUE_PROBE[spec.key]
    try:
        manifest_values = manifest_probe(manifest)
        consumer_values = facet_probe(loaded)
    except Exception as exc:  # noqa: BLE001
        decision = classify(
            manifest_values=frozenset(), consumer_values=frozenset(),
            manifest_missing_symbols=(), non_transplantable_symbols=(), determinate=False,
        )
        decision = Decision(decision.state, (), (), decision.reasons + (f"取值异常点名：{exc}",), False)
        return FacetResult(spec, decision, frozenset(), frozenset(), (), ())

    # 不可搬运：消费方所读的可调用符号里，真身在旧账上确为函数/类/容器的。
    non_transplantable: list[str] = []
    for name in spec.consumed_call_symbols:
        obj = getattr(loaded, name, None)
        if obj is not None and _is_non_transplantable(obj):
            non_transplantable.append(name)

    # 册缺符号：薄壳要 re-export、但册根本没有的数据符号。
    manifest_missing = [
        name for name in spec.manifest_candidate_symbols
        if not hasattr(manifest, name)
    ]

    decision = classify(
        manifest_values=manifest_values,
        consumer_values=consumer_values,
        manifest_missing_symbols=tuple(manifest_missing),
        non_transplantable_symbols=tuple(non_transplantable),
        determinate=True,
    )
    return FacetResult(
        spec=spec, decision=decision, manifest_values=manifest_values,
        consumer_values=consumer_values, non_transplantable=tuple(non_transplantable),
        manifest_missing=tuple(manifest_missing),
    )


# =========================================================================
# 消费方清单：AST 扫全树候选（先文本过滤再解析），分类 + 摘断言原文
# =========================================================================
@dataclass
class Consumer:
    path: str
    line: int
    role: str  # runtime / static_reader / gate
    how: str   # import:<symbols> / path-ast / assert
    excerpt: str


_SCAN_ROOTS: Final[tuple[str, ...]] = ("plugins", "scripts", "tests")
_SKIP_DIRS: Final[set[str]] = {"__pycache__", ".venv", "node_modules", ".git", "_crawlwiki_patch2"}


def _iter_scan_files() -> Any:
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if _SKIP_DIRS & set(path.parts):
                continue
            yield path


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def scan_consumers(spec: FacetSpec) -> list[Consumer]:
    """找：谁 import 旧账（含 compat 薄壳）、谁按路径 AST 读它、哪些门断言成员数/顺序。"""
    tail = spec.legacy_path.stem
    path_frag = f"{_REL}/domains/"
    if spec.key == "registry":
        path_frag = "domains/chat_reply/runtime/capability_registry.py"
    elif spec.key == "board":
        path_frag = "domains/core/board_taxonomy.py"
    else:
        path_frag = "domains/core/channel_capability_tags.py"

    consumed_all = set(spec.consumed_data_symbols) | set(spec.consumed_call_symbols)
    out: list[Consumer] = []
    self_path = Path(__file__).resolve()
    for file in _iter_scan_files():
        if file == spec.legacy_path or file.resolve() == self_path:
            # 跳过旧账自身与本干跑件自身（本件含路径字面量，若计入=把尺当消费方，制造噪声）。
            continue
        try:
            src = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if tail not in src and path_frag not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = _rel(file)
        role = "gate" if rel.startswith("tests/") else ("static_reader" if rel.startswith("scripts/") else "runtime")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                hit = module == tail or module.endswith("." + tail)
                if spec.key == "registry" and not hit:
                    hit = module.endswith(".capability_registry")
                if hit:
                    names = ", ".join(a.asname or a.name for a in node.names)
                    out.append(Consumer(rel, node.lineno, role, f"import[{names}]", ""))
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and path_frag in node.value
                and node.value.endswith(".py")
            ):
                out.append(Consumer(rel, node.lineno, role, "path-ast-read", node.value[-60:]))
        # 门：断言里点名被消费符号，且常伴成员数/顺序判据。
        if role == "gate":
            for stmt in ast.walk(tree):
                if not isinstance(stmt, ast.Assert):
                    continue
                seg = ast.get_source_segment(src, stmt) or ""
                if any(sym in seg for sym in consumed_all) and any(
                    key in seg for key in ("len(", "sorted(", "min(", "== [", "== (", "=={", "set(", "index(")
                ):
                    one = " ".join(seg.split())
                    out.append(Consumer(rel, stmt.lineno, "gate", "assert-membership", one[:180]))
    # 去重（同 file:line:how 只留一次），按路径+行号稳定排序。
    seen: set[tuple[str, int, str]] = set()
    deduped: list[Consumer] = []
    for cons in sorted(out, key=lambda c: (c.path, c.line, c.how)):
        sig = (cons.path, cons.line, cons.how)
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(cons)
    return deduped


# =========================================================================
# 建议执行序 + 每批预期 diff 方向
# =========================================================================
def build_plan(results: dict[str, FacetResult]) -> list[dict[str, Any]]:
    """按"降壳后被顶红的门数"升序排风险；每批给前置与必跑门、预期 diff 方向。"""
    def gate_count(key: str) -> int:
        return len({c.path for c in results[key].consumers if c.role == "gate"})

    order = sorted(results, key=gate_count)  # 牵连门最少的先搬（相对最安全）
    plan: list[dict[str, Any]] = []
    for rank, key in enumerate(order, 1):
        res = results[key]
        red_paths = sorted({c.path for c in res.consumers if c.role in ("gate", "static_reader")})
        plan.append({
            "rank": rank,
            "facet": res.spec.display,
            "state": res.decision.state,
            "gates_touched": gate_count(key),
            "prerequisite": (
                "先由主代理把该维度逐字节写进真身册（S12 等值尺 + S10 量具复跑判等），"
                "再把旧账改成 ``from capability_manifest import ...``；两步缺一即降壳=断供"
            ),
            "run_after": red_paths,
            "expected_diff": {
                "unchanged_counts": "册内已声明面（FACETS/EVIDENCE/CEILING）本批不动",
                "should_decrease": "旧账文件行数应显著下降（数据搬进册、旧账只剩再导出）",
                "will_go_red_if_skipped_prereq": (
                    "S44 三支按路径读的脚本会顺链追到册、读到缺符号即抛 ⇒ 对应门红："
                    + "；".join(red_paths) if red_paths else "（无按路径 AST 消费者）"
                ),
            },
        })
    return plan


# =========================================================================
# 注毒自证（证明三态判据有牙，不读盘、只喂合成输入）
# =========================================================================
@dataclass
class Poison:
    name: str
    passed: bool
    detail: str


def run_poisons() -> list[Poison]:
    poisons: list[Poison] = []

    def check(name: str, cond: bool, detail: str) -> None:
        poisons.append(Poison(name, bool(cond), detail))

    # 注毒①：册供出与消费方完全相同、无形态阻断 ⇒ 必须判 identical（防"永远 incompatible"）。
    d1 = classify(
        manifest_values=frozenset({"a", "b"}), consumer_values=frozenset({"a", "b"}),
        manifest_missing_symbols=(), non_transplantable_symbols=(),
    )
    check("poison-1-identical-is-possible", d1.state == STATE_IDENTICAL, f"state={d1.state}")

    # 注毒②：消费方比册多一枚 ⇒ 必须判 subset|superset 并点名丢的那枚（防"悄悄丢数据也绿"）。
    d2 = classify(
        manifest_values=frozenset({"a"}), consumer_values=frozenset({"a", "b", "c"}),
        manifest_missing_symbols=(), non_transplantable_symbols=(),
    )
    check(
        "poison-2-consumer-extra-is-named-diff",
        d2.state == STATE_DIFF and set(d2.consumer_only) == {"b", "c"},
        f"state={d2.state} consumer_only={d2.consumer_only}",
    )

    # 注毒③：值集合相等但消费面含函数 ⇒ 必须判 incompatible（防"值等就放行、忽略断供")。
    d3 = classify(
        manifest_values=frozenset({"a", "b"}), consumer_values=frozenset({"a", "b"}),
        manifest_missing_symbols=(), non_transplantable_symbols=("declared_native_media_kinds",),
    )
    check(
        "poison-3-form-block-overrides-equal",
        d3.state == STATE_INCOMPATIBLE and "declared_native_media_kinds" in " ".join(d3.reasons),
        f"state={d3.state}",
    )

    # 注毒④：册根本没该符号 ⇒ 必须判 incompatible 点名缺符号（防"缺源也当已迁移")。
    d4 = classify(
        manifest_values=frozenset({"a"}), consumer_values=frozenset({"a"}),
        manifest_missing_symbols=("CHANNEL_CAPABILITY_KINDS",), non_transplantable_symbols=(),
    )
    check(
        "poison-4-missing-symbol-is-incompatible",
        d4.state == STATE_INCOMPATIBLE and "CHANNEL_CAPABILITY_KINDS" in " ".join(d4.reasons),
        f"state={d4.state}",
    )

    # 注毒⑤：determinate=False（不可判）⇒ 必须 incompatible，绝不降级成没扫到=绿。
    d5 = classify(
        manifest_values=frozenset(), consumer_values=frozenset(),
        manifest_missing_symbols=(), non_transplantable_symbols=(), determinate=False,
    )
    check(
        "poison-5-undetermined-is-red",
        d5.state == STATE_INCOMPATIBLE and d5.determinate is False,
        f"state={d5.state} determinate={d5.determinate}",
    )
    return poisons


# =========================================================================
# 输出
# =========================================================================
def _decision_dict(res: FacetResult) -> dict[str, Any]:
    return {
        "state": res.decision.state,
        "determinate": res.decision.determinate,
        "manifest_values": sorted(res.manifest_values),
        "consumer_values": sorted(res.consumer_values),
        "manifest_only": list(res.decision.manifest_only),
        "consumer_only": list(res.decision.consumer_only),
        "non_transplantable": list(res.non_transplantable),
        "manifest_missing": list(res.manifest_missing),
        "reasons": list(res.decision.reasons),
    }


def render_json(manifest: types.ModuleType, results: dict[str, FacetResult],
                plan: list[dict[str, Any]], poisons: list[Poison]) -> str:
    payload = {
        "declared_ids_in_manifest": sorted(_capability_ids_of_manifest(manifest)),
        "facets": {key: _decision_dict(res) for key, res in results.items()},
        "consumers": {
            key: [c.__dict__ for c in res.consumers] for key, res in results.items()
        },
        "plan": plan,
        "poisons": [p.__dict__ for p in poisons],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_report(manifest: types.ModuleType, results: dict[str, FacetResult],
                  plan: list[dict[str, Any]], poisons: list[Poison]) -> str:
    lines: list[str] = []
    push = lines.append
    push("=" * 72)
    push("P2 三处旧账降为再导出垫片 —— 干跑取证报告（S58）")
    push("=" * 72)
    push(f"真身册现声明能力面 declared_ids 数＝{len(_capability_ids_of_manifest(manifest))}")
    push("")
    push("## 三面三态全表")
    for key in ("tags", "board", "registry"):
        res = results[key]
        push(f"### {res.spec.display}")
        push(f"  三态＝{res.decision.state}  （determinate={res.decision.determinate}）")
        push(f"  册现值集合（共享可比单元）＝{sorted(res.manifest_values) or '∅'}")
        push(f"  消费方读到集合          ＝{sorted(res.consumer_values) or '∅'}")
        if res.decision.manifest_only:
            push(f"  差集·册多于消费方＝{list(res.decision.manifest_only)}")
        if res.decision.consumer_only:
            push(f"  差集·消费方多于册＝{list(res.decision.consumer_only)}")
        if res.non_transplantable:
            push(f"  不可字面搬运形态＝{list(res.non_transplantable)}")
        if res.manifest_missing:
            push(f"  册缺失的消费方所需符号＝{list(res.manifest_missing)}")
        for reason in res.decision.reasons:
            push(f"  · {reason}")
        push("")
    push("## 消费方与受影响门清单（逐条 文件:行）")
    for key in ("tags", "board", "registry"):
        res = results[key]
        push(f"### {res.spec.display} — 共 {len(res.consumers)} 条")
        if not res.consumers:
            push("  （无命中）")
        for cons in res.consumers:
            push(f"  [{cons.role:14}] {cons.path}:{cons.line}  {cons.how}")
            if cons.excerpt:
                push(f"                   ↳ {cons.excerpt}")
        push("")
    push("## 建议执行序 + 每批预期 diff 方向")
    for item in plan:
        push(f"### 第 {item['rank']} 批：{item['facet']}（当前态＝{item['state']}）")
        push(f"  前置＝{item['prerequisite']}")
        push(f"  本批搬完必跑（被顶红的按路径读口/门）＝{item['run_after'] or '（无）'}")
        for dk, dv in item["expected_diff"].items():
            push(f"  · {dk}：{dv}")
        push("")
    push("## 注毒自证逐发结果")
    for p in poisons:
        push(f"  [{'OK' if p.passed else 'FAIL'}] {p.name}  {p.detail}")
    push("=" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2 三处旧账降壳干跑取证（S58，零落码）")
    parser.add_argument("--report", action="store_true", help="人类可读报告（缺省即此）")
    parser.add_argument("--json", action="store_true", help="机器形态（同数据，非第二套判据）")
    parser.add_argument("--selftest", action="store_true", help="只跑注毒自证、不读生产面")
    args = parser.parse_args(argv)

    if args.selftest:
        poisons = run_poisons()
        for p in poisons:
            print(f"[{'OK' if p.passed else 'FAIL'}] {p.name}  {p.detail}")
        return 0 if all(p.passed for p in poisons) else 3

    # 只读加载真身册（自持件，绕重根）。
    try:
        manifest = load_standalone(MANIFEST_PATH, "_s58_manifest")
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] 真身册加载失败，无法干跑：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    poisons = run_poisons()
    results: dict[str, FacetResult] = {}
    for spec in FACETS:
        res = analyze_facet(spec, manifest, determinate_default=True)
        res.consumers = scan_consumers(spec)
        results[spec.key] = res
    plan = build_plan(results)

    if args.json:
        print(render_json(manifest, results, plan, poisons))
    else:
        print(render_report(manifest, results, plan, poisons))

    # 自证失牙 ⇒ 退出码红（判据被写松的常驻信号）。
    return 0 if all(p.passed for p in poisons) else 3


if __name__ == "__main__":
    raise SystemExit(main())
