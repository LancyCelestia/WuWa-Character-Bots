"""席 G1 尺②：`MigrationStatus` **赋值门**（接管阶必须能被现算读出、逐阶推进、非 LEGACY 只准增）。

**为什么必须有这把尺**（起点取证，全部只读现算；复跑命令见本席工单 §3-B）：
`domains/core/decision/outbound_registry.py::build_default_takeover_registry()` 在册
50 matcher + 12 调度族 + 7 控制面路由组 ＝ **69 枚条目（当时值，2026-10-02 现算）**，
状态**全部**吃 dataclass 字段缺省 `MigrationStatus.LEGACY`；而另两阶
`TAKEOVER_READY` / `TAKEN_OVER` 全仓从未被赋值过一次。缺席证据（尺＝
`grep -rn "MigrationStatus\\.\\|takeover_ready\\|taken_over" plugins scripts tests bot.py`，
现算命中 7 行，逐行看）：

- `outbound_registry.py:329` / `:330` ←两阶的**枚举定义**本身（`:330` 注释自陈"本轮无"）
- `outbound_registry.py:360` / `:370` / `:383` ←三处 `status: MigrationStatus = MigrationStatus.LEGACY`
  字段缺省（matcher / scheduler / route_group 各一枚）
- `outbound_registry.py:335`、`tests/test_outbound_v21.py:784` ←两行散文与注释

⇒ 「中央调度零旁路」这句话**结构上不可证**：册子只能说"所有人都在旧入口"，
说不出"谁已收编"，也说不出"还差谁"；影子对照的样本边界
（`docs/design/audit-20260920-unify-U24-decision.md` §F-4）因此只剩散文。
既有门 `tests/test_outbound_v21.py::TestTakeoverRegistryIntegrity::test_all_entries_default_legacy_with_checklist`
钉的是"**永远全 LEGACY**"（等值冻结）——本席**不改那件**（非本席独占面），
只把"合法推进长什么样"定义出来，并按 #68★ 把随迁需求写进工单 §5。

**这把尺判什么**
1. **可现算读出**（`census()`）：状态分布只能从条目字段现算，不接受散文口径、不接受裸字符串。
2. **逐阶推进**（`advance()`）：阶梯 `LEGACY → TAKEOVER_READY → TAKEN_OVER`；
   禁倒退、禁跳阶（跳阶＝账面一步登绿，审计链上缺一格读数）。
3. **推进要有内容**：`TAKEOVER_READY` 必须 `TakeoverChecklist.is_complete()`（接管三问齐）；
   `TAKEN_OVER` 除三问齐外还必须在 `note` 里点名一枚**在岗中央汇缝符号**
   （`CENTRAL_SEAM_SYMBOLS`），且该符号经 AST 现算真在生产面存在——指不到汇缝＝证不成收编。
4. **非 LEGACY 只准增**：`BASELINE_NON_LEGACY`（现算起点 0）以下必红；且升阶必须**逐枚**登记进
   `ADVANCED_ENTRY_ROSTER`——名册外出现非 LEGACY＝静默改判，名册内消失＝撤销没走账，两条都红。
5. **台账 #56★K-1 硬口径进语义**：控制面 features API 的 `enabled` 值变化**不等于**
   生产插件已停用/已收编。两腿机械判据——① 登记表源文本禁止 import `control_plane`
   或以其视图派生状态；② 拿"features enable/disable"读数当收编证据，`seam_evidence_verdict` 直接拒。
6. **赋值只能发生在源文本里**：条目是 `@dataclass(frozen=True)`，运行期改不动（本尺实跑证明），
   所以任何升阶都会留下一条可评审的源码改动，不存在"跑着跑着状态自己变了"。

诚实边界：本尺只判"赋值这件事合不合法、证据指没指到汇缝"，**不判该不该收编**
（哪些调度族许接管＝用户裁决债，U24 §G6 在册）；汇缝符号名在场也不等于该条目真走了
中央管线——行为等值属真机验收，不在本波离线面。
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "bot_unified_runtime"
OUTBOUND_REGISTRY_PY = PLUGIN / "domains/core/decision/outbound_registry.py"
PIPELINE_PY = PLUGIN / "domains/chat_reply/runtime/pipeline.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 本文件刻意先把仓库根塞进 sys.path 再导主包（见上方两行），import 落在代码后是有意形态：
from plugins.bot_unified_runtime.domains.core.decision.outbound_registry import (
    DirectSendCategory,
    MatcherEntry,
    MigrationStatus,
    TakeoverChecklist,
    build_default_takeover_registry,
)

# ---------------------------------------------------------------------------
# 判据常量（起点＝2026-10-02 现算；方向＝只准增，容差一字不动）
# ---------------------------------------------------------------------------

#: 迁移阶梯：序＝唯一允许方向。
STATUS_LADDER: tuple[MigrationStatus, ...] = (
    MigrationStatus.LEGACY,
    MigrationStatus.TAKEOVER_READY,
    MigrationStatus.TAKEN_OVER,
)

#: 非 LEGACY 枚数地板（现算起点 0）。"只准增"＝低于本值必红；升阶还得逐枚进名册。
BASELINE_NON_LEGACY = 0

#: 升阶名册：任何一枚条目离开 LEGACY，必须在这里登记身份串（同批带上三问答案与汇缝证据）。
#: 名册外出现非 LEGACY＝静默改判；名册内消失＝撤销没走账。两条都红。
ADVANCED_ENTRY_ROSTER: frozenset[str] = frozenset()

#: 未达阶名册：现算没有任何条目到达的两阶。推进了就得同批改这张表（拦的不是进步，是"静默"）。
UNASSIGNED_STAGES_AT_BASELINE: frozenset[str] = frozenset({"takeover_ready", "taken_over"})

#: `TAKEN_OVER` 证据必须点名的在岗中央汇缝符号（层 2 主缝与层 1 管线）。
#: 口径照 `capability_registry.py::PipelineManagedExecution` 注：这几枚才是"经中央调度投递"
#: 的在岗形状；点不到它们＝第二条通路，不许宣称收编（禁第二通路，AGENTS 第三部分）。
CENTRAL_SEAM_SYMBOLS: tuple[str, ...] = (
    "_run_capability_through_pipeline",
    "_run_simple_capability",
    "RuntimePipeline.handle_async",
    "RuntimePipeline.handle",
)

#: **不构成**收编证据的写法（台账 #56★K-1 的机械形态）。
FEATURE_FLAG_EVIDENCE_TERMS: tuple[str, ...] = (
    "features/enable",
    "features/disable",
    "feature enabled",
    "enabled=true",
    "enabled=False",
    "已停用插件",
)

#: `TransportEntry` 绑定生命周期的已知字面量（outbound_registry.py:101 注释自陈
#: placeholder / bound；:123 直写、:185→:200 经局部别名）。这是与 `MigrationStatus`
#: **互不相干的第二状态概念**——出站通道的绑定态，不是接管迁移态，本不该被
#: 判据 6 的 `status=` 谓词拦下。白名单收窄量具：仅这三个已知值放行，
#: 成员名已现算核对不在 MigrationStatus 枚举内（outbound_registry.py:327-330 仅三阶）；
#: 白名单之外的一切字面量／派生表达式仍然红。
TRANSPORT_BINDING_LIFECYCLE_LITERALS: frozenset[str] = frozenset({"bound", "placeholder"})


class MigrationAssignmentError(ValueError):
    """非法赋值：倒退／跳阶／三问未齐／汇缝证据不合格／状态不是枚举成员。"""


# ---------------------------------------------------------------------------
# 判据本体（纯函数；喂合成条目即可试牙，不写盘、不碰生产装配）
# ---------------------------------------------------------------------------
def rank_of(status: object) -> int:
    if isinstance(status, MigrationStatus):
        return STATUS_LADDER.index(status)
    raise MigrationAssignmentError(
        f"迁移状态必须是 MigrationStatus 枚举成员，收到 {type(status).__name__}({status!r})"
        "——裸字符串态＝可以在装配期被随手拼接，本门禁止"
    )


def entry_identity(entry: object) -> str:
    """条目稳定身份（认名字/族/模块，不认行号——行号按 #50★ 必漂）。"""
    for attr in ("name", "family", "module"):
        value = getattr(entry, attr, None)
        if isinstance(value, str) and value.strip():
            return f"{type(entry).__name__}:{value.strip()}"
    return f"{type(entry).__name__}:{getattr(entry, 'location', '')}"


def seam_evidence_verdict(evidence: str) -> tuple[bool, str]:
    """收编证据形状：非空 + 点名在岗汇缝 + 不得只靠控制面开关读数。"""
    text = (evidence or "").strip()
    if not text:
        return False, "TAKEN_OVER 的汇缝证据是空串（note 里一个字都没写）"
    named = tuple(symbol for symbol in CENTRAL_SEAM_SYMBOLS if symbol in text)
    lowered = text.lower()
    flag_only = [term for term in FEATURE_FLAG_EVIDENCE_TERMS if term.lower() in lowered]
    if not named:
        if flag_only:
            return False, (
                f"证据只落在控制面开关读数（命中 {flag_only}）——台账 #56★K-1 硬口径："
                "features API 的 enabled 值变化 ≠ 生产插件已停用/已收编"
            )
        return False, (
            f"证据未点名在岗中央汇缝符号（需要 {' / '.join(CENTRAL_SEAM_SYMBOLS)} 之一）"
        )
    return True, f"ok：点名汇缝 {named}"


def advance(
    entry: object,
    new_status: MigrationStatus,
    *,
    checklist: TakeoverChecklist | None = None,
    seam_evidence: str | None = None,
) -> object:
    """唯一合法的状态推进形状（返回**新值副本**，原条目不动）。

    生产侧真要用时，等价动作是把 registry 源文本里那一行写成
    `status=…, checklist=TakeoverChecklist(…), note=…`——本函数只是把那三条要求预先跑一遍，
    让"能不能这么写"变成可复算的问题，而不是评审时靠人记。
    """
    rank_of(new_status)
    old_status = getattr(entry, "status", None)
    rank_of(old_status)
    resolved_checklist = checklist if checklist is not None else getattr(entry, "checklist", None)
    if not isinstance(resolved_checklist, TakeoverChecklist):
        raise MigrationAssignmentError(f"{entry_identity(entry)} 缺 TakeoverChecklist 字段")
    old_rank, new_rank = rank_of(old_status), rank_of(new_status)
    if new_rank < old_rank:
        raise MigrationAssignmentError(
            f"迁移状态禁倒退：{entry_identity(entry)} {old_status.value} → {new_status.value}"
        )
    if new_rank == old_rank:
        return entry
    if new_rank - old_rank > 1:
        raise MigrationAssignmentError(
            f"必须逐阶推进：{entry_identity(entry)} 从 {old_status.value} 跳到 {new_status.value}"
            "（跳过 TAKEOVER_READY＝审计链少一格，账面直接登绿）"
        )
    if new_rank >= rank_of(MigrationStatus.TAKEOVER_READY) and not resolved_checklist.is_complete():
        raise MigrationAssignmentError(
            f"接管三问未齐，不得置 {new_status.value}：{entry_identity(entry)}"
            f"（idempotency={resolved_checklist.idempotency_key_source!r} "
            f"gate={resolved_checklist.feature_gate!r} trace={resolved_checklist.trace_point!r}）"
        )
    if new_rank == rank_of(MigrationStatus.TAKEN_OVER):
        evidence = seam_evidence if seam_evidence is not None else getattr(entry, "note", "")
        ok, why = seam_evidence_verdict(str(evidence))
        if not ok:
            raise MigrationAssignmentError(f"{entry_identity(entry)} 收编证据不合格：{why}")
    return dataclasses.replace(entry, status=new_status, checklist=resolved_checklist)


def all_entries() -> list[object]:
    registry = build_default_takeover_registry()
    return [*registry.matchers, *registry.schedulers, *registry.route_groups]


def census(entries: list[object] | None = None) -> dict[str, int]:
    """状态分布现算（读不出就抛——"静默跳过一枚"比"当场炸"更坏）。"""
    counts: dict[str, int] = {}
    for entry in entries if entries is not None else all_entries():
        status = getattr(entry, "status", None)
        if not isinstance(status, MigrationStatus):
            raise MigrationAssignmentError(
                f"{entry_identity(entry)} 的 status 不是枚举成员：{status!r}"
            )
        counts[status.value] = counts.get(status.value, 0) + 1
    return counts


def non_legacy_identities(entries: list[object] | None = None) -> list[str]:
    return sorted(
        entry_identity(entry)
        for entry in (entries if entries is not None else all_entries())
        if getattr(entry, "status", None) is not MigrationStatus.LEGACY
    )


def central_seam_liveness() -> dict[str, bool]:
    """AST 现算：这些汇缝符号今天到底在不在生产面（证据不许指名不存在的东西）。"""
    alive = dict.fromkeys(CENTRAL_SEAM_SYMBOLS, False)
    for path in (PLUGIN / "__init__.py", PIPELINE_PY):
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        for symbol in alive:
            if "." in symbol:
                cls, _, method = symbol.partition(".")
                node = classes.get(cls)
                if node is not None and any(
                    isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    and child.name == method
                    for child in node.body
                ):
                    alive[symbol] = True
            elif symbol in functions:
                alive[symbol] = True
    return alive


def _binding_alias_lifecycle(tree: ast.AST) -> tuple[dict[str, str], set[str], set[str]]:
    """现算绑定生命周期字面量的局部别名（:185 `placeholder = "placeholder"` → :200 `status=placeholder`）。

    返回 (字符串常量别名表, 被非字面量赋值污染的名字, 形参名全集)。后两者让别名解析
    **宁红勿漏**：名字只要在任何一处被赋成非字面量（含 AnnAssign 带值与海象式）、
    或是任何函数/lambda 的形参（可能绑运行期值），就不许当别名放行。
    """
    constants: dict[str, str] = {}
    tainted: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif (
            isinstance(node, ast.AnnAssign) and node.value is not None
        ) or isinstance(node, ast.NamedExpr):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    constants[target.id] = node.value.value
                else:
                    tainted.add(target.id)
    parameters = {
        arg.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
        for arg in ast.walk(node.args)
        if isinstance(arg, ast.arg)
    }
    return constants, tainted, parameters


def status_keyword_offenders(tree: ast.AST) -> list[str]:
    """判据 6 腿①：`status=` 关键字实参里**不是合法形态**的行（按行序，`line N: 源码片段`）。

    合法形态只有三族——
    ① `MigrationStatus.X`（字面枚举成员）；
    ② 字符串字面量 ∈ TRANSPORT_BINDING_LIFECYCLE_LITERALS（`TransportEntry` 绑定
       生命周期，:123，与 MigrationStatus 互不相干的第二状态概念）；
    ③ 名字解析到 ② 的字面量别名（:200 `status=placeholder`），且该名字从未被
       派生式赋值污染、也不是任何函数的形参。
    其余一切（函数调用 / 下标 / 非 MigrationStatus 属性链 / 未知名字 /
    白名单外字面量）一律报——「状态可由读数算出来」这条红线不许松。
    """
    constants, tainted, parameters = _binding_alias_lifecycle(tree)
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.keyword) and node.arg == "status"):
            continue
        value = node.value
        legal = (
            (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "MigrationStatus"
            )
            or (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value in TRANSPORT_BINDING_LIFECYCLE_LITERALS
            )
            or (
                isinstance(value, ast.Name)
                and value.id not in tainted
                and value.id not in parameters
                and constants.get(value.id) in TRANSPORT_BINDING_LIFECYCLE_LITERALS
            )
        )
        if not legal:
            offenders.append((node.lineno, ast.unparse(value)))
    return [f"line {lineno}: {snippet}" for lineno, snippet in sorted(offenders)]


def migration_status_field_defaults(tree: ast.AST) -> list[ast.AnnAssign]:
    """判据 6 腿②：**注解为 `MigrationStatus`**（Name 或 Attribute 形态）的 `status` 字段缺省。

    `TransportEntry.status: str`（绑定生命周期，:101）注解不同 ⇒ 不属接管概念，
    不进本门的计数覆盖面；本门数的是 matcher/scheduler/route_group 三族条目的字段缺省。
    """
    def _annotated_migration_status(annotation: ast.expr) -> bool:
        return (
            isinstance(annotation, ast.Name) and annotation.id == "MigrationStatus"
        ) or (
            isinstance(annotation, ast.Attribute) and annotation.attr == "MigrationStatus"
        )

    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "status"
        and _annotated_migration_status(node.annotation)
    ]


# ---------------------------------------------------------------------------
# 常驻判据
# ---------------------------------------------------------------------------
def test_status_census_is_computable_and_typed() -> None:
    """判据 1：状态只能从条目字段现算读出，且逐枚是枚举成员（禁裸字符串）。"""
    entries = all_entries()
    assert entries, "接管登记表读空 ⇒ 本尺失去对象，不是『大家都归位了』"
    counts = census(entries)
    assert set(counts) <= {status.value for status in MigrationStatus}, (
        f"读出了枚举之外的状态：{sorted(counts)}"
    )
    assert sum(counts.values()) == len(entries), "分布之和 ≠ 在册枚数 ⇒ 有条目被静默跳过"


def test_takeover_stages_are_recorded_as_unassigned_ledger() -> None:
    """判据 2：每一阶要么有读数、要么**显式登记**为未达阶——不许拿"没人赋值过"当默认。

    这条把起点取证钉成一条会过期的账：谁真推进了那一阶，必须同时改这张表，否则当场红
    （拦的不是进步，是"静默"）。
    """
    counts = census()
    unassigned = sorted(status.value for status in MigrationStatus if status.value not in counts)
    assert set(unassigned) == UNASSIGNED_STAGES_AT_BASELINE, (
        f"未达阶名册漂移：现算 {unassigned}｜在册 {sorted(UNASSIGNED_STAGES_AT_BASELINE)}"
        "｜推进了就把本常量同批改掉（并同步 ADVANCED_ENTRY_ROSTER），别一边推进一边留旧账"
    )


def test_non_legacy_count_only_increases() -> None:
    """判据 3：非 LEGACY 枚数只准增（地板＝现算起点 0），且升阶必须逐枚进名册。"""
    advanced = non_legacy_identities()
    assert len(advanced) >= BASELINE_NON_LEGACY, (
        f"非 LEGACY 枚数现算 {len(advanced)} < 地板 {BASELINE_NON_LEGACY} ⇒ 有人撤了阶却不走撤销账"
    )
    unrostered = sorted(set(advanced) - set(ADVANCED_ENTRY_ROSTER))
    assert not unrostered, (
        f"这些条目离开了 LEGACY 却没登进升阶名册（静默改判）：{unrostered}"
        "｜登记要求＝同批带上接管三问答案与在岗汇缝证据"
    )
    stale = sorted(set(ADVANCED_ENTRY_ROSTER) - set(advanced))
    assert not stale, f"名册里还挂着已回到 LEGACY 的条目（撤销没走账）：{stale}"


def test_every_advanced_entry_carries_complete_checklist_and_seam() -> None:
    """判据 4：名册里每一枚都必须三问齐 +（TAKEN_OVER 时）汇缝证据合格——现算，不靠人记。"""
    entries = all_entries()
    advanced = [
        entry for entry in entries
        if getattr(entry, "status", None) is not MigrationStatus.LEGACY
    ]
    for entry in advanced:
        checklist = getattr(entry, "checklist", None)
        assert isinstance(checklist, TakeoverChecklist) and checklist.is_complete(), (
            f"{entry_identity(entry)} 已升阶但接管三问未齐 ⇒ 判据 4 被绕"
        )
        if getattr(entry, "status", None) is MigrationStatus.TAKEN_OVER:
            ok, why = seam_evidence_verdict(str(getattr(entry, "note", "")))
            assert ok, f"{entry_identity(entry)} TAKEN_OVER 证据不合格：{why}"
    legacy_count = census(entries).get(MigrationStatus.LEGACY.value, 0)
    assert len(advanced) == len(entries) - legacy_count, "升阶计数与分布不自洽"


def test_central_seam_symbols_are_live_in_production() -> None:
    """判据 5：证据允许点名的汇缝符号，今天必须真在生产面（不许拿死符号当收编凭据）。"""
    liveness = central_seam_liveness()
    dead = sorted(symbol for symbol, alive in liveness.items() if not alive)
    assert not dead, (
        f"这些「中央汇缝符号」在生产面找不到：{dead}｜要么改证据口径，要么把符号名随迁"
    )


def test_status_is_not_derived_from_control_plane() -> None:
    """判据 6（台账 #56★K-1）：接管状态**不得**由控制面 features 的 enabled 派生。

    只判登记表自身的两条代码面（散文/证据串里提 `control_plane/dispatcher.py` 是合法坐标，
    本席首版拿全文子串判这件事，被在册证据串误伤一次 ⇒ 改成 AST 判）：
    ① 不许 import 控制面；
    ② `status=` 只能被赋成**字面枚举成员**（`MigrationStatus.X`），
       一旦出现函数调用/下标/属性链以外的派生式（例如读 features 视图、读 enabled），当场红。
    一旦状态能从控制面视图算出来，「enabled 关了就等于收编了」这句假话会自动账面成立。

    2026-10-02 MIG 复核收窄：`TransportEntry` 的绑定生命周期（`status="bound"` / `placeholder`
    别名，:123/:185/:200）是与 MigrationStatus 互不相干的第二状态概念，走显式白名单放行
    （TRANSPORT_BINDING_LIFECYCLE_LITERALS）；AnnAssign 腿改按**注解类型**过滤（只数注解为
    `MigrationStatus` 的字段缺省）。白名单之外的派生式照旧必红，末尾注毒腿现算自证。
    """
    source = OUTBOUND_REGISTRY_PY.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = sorted(name for name in imported if "control_plane" in name)
    assert not offenders, (
        f"接管登记表 import 了控制面（{offenders}）⇒ 状态可能被 enabled 读数派生，违 #56★K-1"
    )
    derived = status_keyword_offenders(tree)
    assert not derived, (
        f"这些 status= 赋值不是字面枚举成员（派生式＝状态可由读数算出来）：{derived}"
    )
    defaults = migration_status_field_defaults(tree)
    assert len(defaults) == 3, (
        f"接管登记表该有三处注解为 MigrationStatus 的 `status` 字段缺省"
        f"（matcher/scheduler/route_group），现算 {len(defaults)}"
        "⇒ 条目结构变了，本判据的覆盖面要重新核"
    )
    for node in defaults:
        assert (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "MigrationStatus"
        ), (
            f"line {node.lineno}: `status` 字段缺省不是字面枚举成员（{ast.unparse(node.value)}）"
            "⇒ 缺省由读数算出，同违 #56★K-1"
        )
    # ---- 注毒腿（合成源码喂同一谓词；不写盘、不碰生产登记表）----
    # 毒 1：控制面读数/函数调用返回值派生 ⇒ 必红（判据核心，不许松）。
    poison_derived = (
        "entry = make(status=features_view('chat').enabled)\n",  # 函数调用链取 enabled
        "entry = make(status=control_plane.enabled)\n",  # 非 MigrationStatus 属性链
        "entry = make(status=roster['status'])\n",  # 下标读数
        'entry = make(status="shipped")\n',  # 白名单外字面量
        "entry = make(status=enabled)\n",  # 未知名字（无字面量别名可解）
        "flag = 'bound'\nflag = read_runtime_flag()\nentry = make(status=flag)\n",  # 别名被派生式污染
        "def handler(placeholder):\n    return make(status=placeholder)\n",  # 形参遮蔽（可能绑运行期值）
    )
    bitten = {snippet: status_keyword_offenders(ast.parse(snippet)) for snippet in poison_derived}
    unbit = [snippet for snippet, hits in bitten.items() if not hits]
    assert not unbit, f"合成派生式没被咬住（判据 6 腿①空转）：{unbit}"
    # 毒 2 反向：合法三族 ⇒ 一枚不报（证明毒 1 咬的是「派生」，不是「赋值这件事」）。
    legal = (
        "entry = make(status=MigrationStatus.TAKEOVER_READY)\n"
        'entry = make(status="bound")\n'
        'placeholder = "placeholder"\nentry = make(status=placeholder)\n'
    )
    assert status_keyword_offenders(ast.parse(legal)) == [], "合法形态被误伤 ⇒ 白名单收窄过了头"



# ---------------------------------------------------------------------------
# 注毒腿（合成条目，内存内跑；绝不写盘、绝不改生产登记表）
# ---------------------------------------------------------------------------
def _sample_entry() -> MatcherEntry:
    return build_default_takeover_registry().matchers[0]


def _done_checklist() -> TakeoverChecklist:
    return TakeoverChecklist(
        idempotency_key_source="platform + event_id + matcher kind（摄取段现算，__init__.py 入站处）",
        feature_gate="bot.chat",
        trace_point="pipeline.handle_async 入口注入 trace_id",
    )


def test_poison_incomplete_checklist_cannot_be_takeover_ready() -> None:
    """注毒甲：三问没齐就想置 TAKEOVER_READY ⇒ 必红；齐了就必须放行（反向不误伤）。"""
    entry = _sample_entry()
    assert entry.status is MigrationStatus.LEGACY, "起点已不是 LEGACY ⇒ 本毒打的是别的东西"
    with pytest.raises(MigrationAssignmentError):
        advance(entry, MigrationStatus.TAKEOVER_READY)
    moved = advance(entry, MigrationStatus.TAKEOVER_READY, checklist=_done_checklist())
    assert moved.status is MigrationStatus.TAKEOVER_READY  # type: ignore[attr-defined]
    assert entry.status is MigrationStatus.LEGACY, "advance 原地改了生产条目 ⇒ purity 破了"


def test_poison_taken_over_without_seam_evidence_is_refused() -> None:
    """注毒乙：TAKEOVER_READY → TAKEN_OVER 但不指汇缝 ⇒ 必红；指了在岗汇缝 ⇒ 放行。"""
    ready = advance(_sample_entry(), MigrationStatus.TAKEOVER_READY, checklist=_done_checklist())
    with pytest.raises(MigrationAssignmentError):
        advance(ready, MigrationStatus.TAKEN_OVER, seam_evidence="")
    with pytest.raises(MigrationAssignmentError):
        advance(ready, MigrationStatus.TAKEN_OVER, seam_evidence="已接入中央调度（没写符号名）")
    taken = advance(
        ready,
        MigrationStatus.TAKEN_OVER,
        seam_evidence="投递经 __init__.py::_run_capability_through_pipeline（层 2 主缝）",
    )
    assert taken.status is MigrationStatus.TAKEN_OVER  # type: ignore[attr-defined]


def test_poison_feature_enabled_flip_is_not_takeover_evidence() -> None:
    """注毒丙（#56★K-1 专腿）：拿 features 的 enabled 翻转当收编证据 ⇒ 必须拒。"""
    ok, why = seam_evidence_verdict("已把 control_plane features/enable 关掉，插件即视为收编")
    assert not ok and "K-1" in why, f"K-1 硬口径没咬住：ok={ok} why={why}"
    ok2, _ = seam_evidence_verdict(
        "features enabled=False，同时经 RuntimePipeline.handle_async 投递"
    )
    assert ok2, "点名了在岗汇缝却被整条拒掉 ⇒ 误伤：要求是「指到汇缝」，不是「别提开关」"


def test_poison_regression_and_skip_are_refused() -> None:
    """注毒丁：倒退（TAKEN_OVER→LEGACY）与跳阶（LEGACY→TAKEN_OVER）都必须红。"""
    ready = advance(_sample_entry(), MigrationStatus.TAKEOVER_READY, checklist=_done_checklist())
    taken = advance(ready, MigrationStatus.TAKEN_OVER, seam_evidence="经 _run_simple_capability 汇缝")
    with pytest.raises(MigrationAssignmentError):
        advance(taken, MigrationStatus.LEGACY)
    with pytest.raises(MigrationAssignmentError):
        advance(_sample_entry(), MigrationStatus.TAKEN_OVER, checklist=_done_checklist())
    assert advance(taken, MigrationStatus.TAKEN_OVER) is taken, "同阶幂等不该造新值/报错"


def test_poison_bare_string_status_is_refused() -> None:
    """注毒戊：裸字符串状态（"takeover_ready"）一律拒——枚举之外无状态。"""
    with pytest.raises(MigrationAssignmentError):
        rank_of("takeover_ready")
    with pytest.raises(MigrationAssignmentError):
        advance(_sample_entry(), "takeover_ready")  # type: ignore[arg-type]
    assert rank_of(MigrationStatus.LEGACY) == 0


def test_poison_census_rejects_untyped_status() -> None:
    """注毒己：条目状态被写成裸串时，现算读数必须抛（不能"读不到就当没这枚"）。"""
    poisoned = dataclasses.replace(_sample_entry(), status="legacy")  # type: ignore[call-arg]
    with pytest.raises(MigrationAssignmentError):
        census([poisoned])


def test_poison_roster_detects_unregistered_promotion() -> None:
    """注毒庚：名册外冒出一枚升阶 ⇒ 判据 3 必须点名；同批反向腿证明"登了册就不再报"。"""
    promoted = advance(_sample_entry(), MigrationStatus.TAKEOVER_READY, checklist=_done_checklist())
    advanced = non_legacy_identities([promoted])
    assert advanced, "合成升阶没被读出来 ⇒ 判据 3 在空跑"
    assert set(advanced) - set(ADVANCED_ENTRY_ROSTER), (
        "名册外升阶竟然被判合规 ⇒ 本腿是摆设"
    )
    rostered = frozenset(advanced)
    assert not (set(advanced) - set(rostered)), "登记后仍报未登记 ⇒ 正向腿会误伤"


def test_registry_entries_are_frozen_at_runtime() -> None:
    """判据 7：赋值只能发生在源文本里——运行期改不动条目（frozen dataclass 实测）。

    这条钉的是"状态不会跑着跑着自己变"这个前提；前提破了，上面所有读数都可疑。
    """
    entry = _sample_entry()
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.status = MigrationStatus.TAKEN_OVER  # type: ignore[misc]


def test_baseline_reading_is_printed_for_the_ticket() -> None:
    """读数复跑自证：起点分布/未达阶/汇缝活性一次打全（工单 §3-B 抄这一段）。"""
    entries = all_entries()
    registry = build_default_takeover_registry()
    reading = {
        "matchers": len(registry.matchers),
        "schedulers": len(registry.schedulers),
        "route_groups": len(registry.route_groups),
        "在册总枚数": len(entries),
        "状态分布": census(entries),
        "非 LEGACY": non_legacy_identities(entries),
        "checklist 完整枚数": sum(
            1 for entry in entries
            if getattr(entry, "checklist", TakeoverChecklist()).is_complete()
        ),
        "汇缝活性": central_seam_liveness(),
        "bypass_suspect 在册": [
            entry.location for entry in registry.direct_sends
            if entry.category is DirectSendCategory.BYPASS_SUSPECT
        ],
    }
    print("\n[G1 尺② 现算读数] " + str(reading))
    assert reading["状态分布"] == {MigrationStatus.LEGACY.value: len(entries)}, (
        f"起点读数已变：{reading['状态分布']}｜同批改 UNASSIGNED_STAGES_AT_BASELINE 与本席工单"
    )
    assert reading["非 LEGACY"] == sorted(ADVANCED_ENTRY_ROSTER)
