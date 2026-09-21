"""Wave 0 契约唯一性门（WP8-W0）：全树只准存在**一份呈现契约 + 一份执行信封**。

背景（设计权威 ``docs/design/capability-orchestration-adoption-spec.md`` §2/§7）：
本项目曾长期并存两个**同名不同物**的 ``CapabilityResult``——

- 呈现契约：``plugins/bot_unified_runtime/domains/core/contracts/runtime.py``
  （回答「给用户看什么」：kind/title/body/media/actions…，handler 的返回类型、
  review/render/投递的消费类型；全树 207 处生产构造点用它）；
- 执行信封：``plugins/bot_unified_runtime/runtime/capability_protocols.py``
  （回答「这次调用执行得怎样」：status/via/elapsed_ms/attempts）。

Wave 0 把后者**改名 ``InvocationResult``**（改名即退役旧名，不留 alias），于是
「一份呈现契约 + 一份执行信封」成为可机器判定的常驻事实。本门执法四件事：

1. **计数唯一**：AST 与正则**双向判定** ``class CapabilityResult``=1、``class InvocationResult``=1，
   且各自落点在指定真身文件（两判据必须互相同意，防任一路数失明）。
2. **禁再合并**：执行信封不得长出呈现字段（``body``/``summary``/``kind``…）——
   那等于把刚分开的两层偷偷焊回去（规格 §7「不许第三套」的反向破口）。
3. **禁双向互喂**：两个 ``extra=forbid`` 契约的 ``model_dump()`` 喂对方构造必 ``ValidationError``
   （这是「不能合并成超集」的源码级证据，钉死防将来口头主张）。
4. **invoker 只产信封**：``CapabilityInvoker.invoke`` 的返回标注与实跑返回类型都必须是
   ``InvocationResult``，且**绝不是**呈现契约——「唯一调用点」的地基。
5. **不变量活性**：信封两条构造期不变量各带正/负样本（失败态缺诚实说明必须崩）。

执法面自带**负样本自证**（§注入第三套定义必咬红）：任何"恒过"的假锁会被当场打回。
全离线零网络，不写源码树（临时文件一律落 pytest ``tmp_path``）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    CapabilityResult as PresentationResult,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as shell
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    PRESENTATION_DATA_KEY,
    InvocationResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 扫描范围＝代码树（Runtime/Archive 是兄弟目录、天然不在范围内）。
SCAN_DIRS = ("plugins", "tests", "scripts")
SCAN_LOOSE_PY = ("bot.py",)

#: 两个契约各自的唯一真身（相对仓库根）。
PRESENTATION_HOME = "plugins/bot_unified_runtime/domains/core/contracts/runtime.py"
ENVELOPE_HOME = "plugins/bot_unified_runtime/runtime/capability_protocols.py"

#: 呈现契约独有、执行信封**永远不该长出**的字段（合并=分层失败的破口）。
PRESENTATION_ONLY_FIELDS = (
    "body",
    "summary",
    "kind",
    "title",
    "images",
    "request_id",
)


def _read_tree(root_str: str) -> tuple[tuple[str, str], ...]:
    """读入代码树的 (相对路径, 源码)。

    **不做记忆化**：本门的注毒自证会临时往树里加文件，缓存会把"刚写进去的毒"缓存外
    漏掉——门一旦失明比慢 0.5 秒严重得多（本项目已有"存在性糊过活性判据"的前例）。
    """
    root = Path(root_str)
    entries: list[tuple[str, str]] = []
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            entries.append((path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
    for name in SCAN_LOOSE_PY:
        path = root / name
        if path.is_file():
            entries.append((name, path.read_text(encoding="utf-8")))
    return tuple(entries)


def scan_class_definitions(
    root: Path, class_name: str
) -> tuple[list[str], list[str]]:
    """双向判定某个 ``class <class_name>`` 在树里的落点。

    返回 ``(ast_hits, regex_hits)``，二者均为相对仓库根的路径（同一文件多次定义会重复计入）。
    """
    pattern = re.compile(rf"^\s*class\s+{re.escape(class_name)}\b", re.MULTILINE)
    root = Path(root)
    ast_hits: list[str] = []
    regex_hits: list[str] = []
    for rel, text in _read_tree(str(root)):
        # 路数一：正则（行级，能抓缩进定义、能在 AST 之前就崩的半残文件上也照抓）。
        for _ in pattern.finditer(text):
            regex_hits.append(rel)
        # 路数二：AST（权威；只在文本粗含类名时才解析，避免 1200+ 次全量 parse）。
        if f"class {class_name}" in text:
            tree = ast.parse(text, filename=str(root / rel))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    ast_hits.append(rel)
    return ast_hits, regex_hits


def _count_in(hits: list[str], rel: str) -> int:
    return sum(1 for h in hits if h == rel)


# ---------------------------------------------------------------------------
# 1. 计数唯一（AST + 正则双向，且落点必须是各自真身）
# ---------------------------------------------------------------------------


def test_presentation_contract_class_is_unique():
    """全树 ``class CapabilityResult`` 恰 1 处，且就在 contracts 真身。"""
    ast_hits, regex_hits = scan_class_definitions(REPO_ROOT, "CapabilityResult")
    assert ast_hits == [PRESENTATION_HOME], (
        f"呈现契约定义必须全树唯一且落在 {PRESENTATION_HOME}，实得 AST 命中={ast_hits}；"
        "第二份同名呈现契约=规格 §7 定罪的『第三套』，必须改名或退役其一"
    )
    assert regex_hits == [PRESENTATION_HOME], (
        f"正则路数命中={regex_hits} 与 AST 路数={ast_hits} 不一致或不止一处"
    )


def test_envelope_class_is_unique_and_renamed():
    """全树 ``class InvocationResult`` 恰 1 处（壳真身），且旧名已从该文件彻底消失。"""
    ast_hits, regex_hits = scan_class_definitions(REPO_ROOT, "InvocationResult")
    assert ast_hits == [ENVELOPE_HOME], (
        f"执行信封定义应恰 1 处且在 {ENVELOPE_HOME}，实得={ast_hits}"
    )
    assert regex_hits == [ENVELOPE_HOME], f"正则路数={regex_hits} 与 AST={ast_hits} 不同意"
    assert _code_symbols_in(REPO_ROOT / ENVELOPE_HOME).count("CapabilityResult") == 0, (
        "壳内仍有把旧名当**代码符号**用的地方（类名/引用/__all__ 字符串/import）——"
        "改名未穷尽；纯注释与 docstring 里的互指文字不受此约束（见下一条）"
    )
    assert "CapabilityResult" in (REPO_ROOT / ENVELOPE_HOME).read_text(encoding="utf-8"), (
        "壳内已完全不提呈现契约名——审计 R3-7 要求两层『头注互指』，"
        "信封的 docstring 应指名它的另一层是谁，防止下一个 AI 又当它们是同一抽象"
    )


def _code_symbols_in(path: Path) -> list[str]:
    """收集一个模块里**作为代码符号**出现的名字（含 ``__all__`` 里的字符串）。

    注释与 docstring 不算：那是给人/AI 看的互指文字，正是审计想要的东西。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    uses: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            uses.append(node.id)
        elif isinstance(node, ast.Attribute):
            uses.append(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            uses.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(
                    node.value, (ast.List, ast.Tuple)
                ):
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            uses.append(element.value)
    return uses


def test_shell_no_longer_exports_the_colliding_name():
    """壳的公开导出面不得再提供 ``CapabilityResult``（不留 alias：留了＝撞名陷阱原样存活，
    因为 ``from 壳 import CapabilityResult`` 会给出信封、``from contracts import`` 给出呈现契约）。"""
    assert not hasattr(shell, "CapabilityResult"), (
        "壳仍导出 CapabilityResult：alias 会让两层契约在同一名字下再度混用，Wave 0 明令不留"
    )
    assert "CapabilityResult" not in shell.__all__
    assert "InvocationResult" in shell.__all__
    assert shell.InvocationResult is InvocationResult


# ---------------------------------------------------------------------------
# 2. 禁再合并：信封不得长出呈现字段
# ---------------------------------------------------------------------------


def test_envelope_does_not_grow_presentation_fields():
    """两层的字段集合必须仍正交：信封里出现任何呈现字段＝把分层焊回去。"""
    env_fields = set(InvocationResult.model_fields)
    pres_fields = set(PresentationResult.model_fields)
    overlap = env_fields & pres_fields
    assert overlap == {"capability_id"}, (
        f"两层契约字段交集应仅 capability_id（同名同义的归因键），实得={sorted(overlap)}"
    )
    leaked = env_fields & set(PRESENTATION_ONLY_FIELDS)
    assert not leaked, f"执行信封长出了呈现字段 {sorted(leaked)}——分层失败，规格 §2『不合并成超集』被破"


def test_presentation_contract_field_count_is_locked():
    """A 契约 Wave 0 硬约束＝**零字段改动**（208/207 构造点才敢一字不动）。"""
    assert len(PresentationResult.model_fields) == 25, (
        f"呈现契约字段数漂移为 {len(PresentationResult.model_fields)}（Wave 0 基线 25）："
        "改 A 契约字段属越界，须另立波次并对 207 构造点做影响评估"
    )


# ---------------------------------------------------------------------------
# 3. 禁双向互喂：extra=forbid 下两侧 dump 喂对方必崩（= 不能合并的源码级证据）
# ---------------------------------------------------------------------------


def test_cross_feeding_the_two_contracts_always_fails():
    env = InvocationResult(
        capability_id="bot.demo", status=shell.InvocationStatus.OK, detail="ok"
    )
    with pytest.raises(ValidationError):
        PresentationResult(**env.model_dump())
    pres = PresentationResult(request_id="r-1", kind="text", body="hello")
    with pytest.raises(ValidationError):
        InvocationResult(**pres.model_dump())


# ---------------------------------------------------------------------------
# 4. invoker 只产信封（唯一调用点的地基）
# ---------------------------------------------------------------------------


def _invoker_return_annotation_source() -> str:
    tree = ast.parse((REPO_ROOT / ENVELOPE_HOME).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CapabilityInvoker":
            for item in node.body:
                if (
                    isinstance(item, ast.FunctionDef)
                    and item.name == "invoke"
                    and item.returns is not None
                ):
                    return ast.unparse(item.returns)
    raise AssertionError("找不到 CapabilityInvoker.invoke 的返回标注")


def test_invoker_return_annotation_is_the_envelope():
    assert _invoker_return_annotation_source() == "InvocationResult", (
        "CapabilityInvoker.invoke 的返回标注被改回呈现契约/其它类型——"
        "「invoker 产出执行信封、把呈现契约装进 data」这条分层就此断裂"
    )


def test_invoke_returns_envelope_never_presentation_contract():
    """实跑面：invoke 的返回类型必须是信封，且**不是**呈现契约实例。"""
    invoker = shell.default_invoker()
    descriptor_ids = [d.capability_id for d in invoker.registry.iter()]
    assert descriptor_ids, "壳内应有 descriptor 在册，否则本门退化成空跑"
    outcome = invoker.invoke(
        shell.CapabilityRequest(
            capability_id=descriptor_ids[0],
            payload={},
            principal="tester",
            roles=("blocked",),  # 走确定性终态，零网络零实现体
        )
    )
    assert isinstance(outcome, InvocationResult)
    assert not isinstance(outcome, PresentationResult), (
        "invoke 返回了呈现契约实例——执行信封层被绕过，调用点唯一性失去意义"
    )


# ---------------------------------------------------------------------------
# 5. 不变量活性（正/负样本成对，防空锁）
# ---------------------------------------------------------------------------

OK = shell.InvocationStatus.OK
DEGRADED = shell.InvocationStatus.DEGRADED
FAILED = shell.InvocationStatus.FAILED


def test_invariant_success_may_carry_presentation_dump():
    """正样本：成功态 + 已序列化的呈现契约 dict = 合法信封（Wave 1 的标准形态）。"""
    pres = PresentationResult(request_id="r-1", kind="text", body="你好")
    env = InvocationResult(
        capability_id="bot.demo",
        status=OK,
        data={PRESENTATION_DATA_KEY: pres.model_dump(mode="json")},
    )
    payload = env.data[PRESENTATION_DATA_KEY]
    assert isinstance(payload, dict)
    assert PresentationResult(**payload).body == "你好"


def test_invariant_rejects_live_model_object_in_data():
    with pytest.raises(ValidationError, match="model_dump"):
        InvocationResult(
            capability_id="bot.demo", status=OK, data={PRESENTATION_DATA_KEY: object()}
        )


def test_invariant_failure_status_requires_honest_detail():
    with pytest.raises(ValidationError, match="诚实降级说明"):
        InvocationResult(capability_id="bot.demo", status=FAILED)  # 静默失败＝冒充
    with pytest.raises(ValidationError, match="诚实降级说明"):
        InvocationResult(capability_id="bot.demo", status=DEGRADED, detail="   ")


def test_invariant_failure_status_must_not_carry_presentation_payload():
    with pytest.raises(ValidationError, match="不得携带呈现载荷"):
        InvocationResult(
            capability_id="bot.demo",
            status=DEGRADED,
            detail="主链失败，诚实降级",
            data={PRESENTATION_DATA_KEY: {"body": "假装有条结果"}},
        )


def test_every_non_success_terminal_status_is_covered():
    """族派生自枚举：任何新终态自动落入"必须诚实说明"桶（fail-closed，不漏网）。"""
    assert set(shell._UNSUCCESS_STATUSES) | set(shell._SUCCESS_STATUSES) == set(
        shell.InvocationStatus
    )
    assert set(shell._UNSUCCESS_STATUSES) & set(shell._SUCCESS_STATUSES) == set()
    for status in shell._UNSUCCESS_STATUSES:
        with pytest.raises(ValidationError):
            InvocationResult(capability_id="bot.demo", status=status)
    for status in shell._SUCCESS_STATUSES:
        InvocationResult(capability_id="bot.demo", status=status)  # 不抛＝放行


# ---------------------------------------------------------------------------
# 6. 本门的负样本自证（注毒必红）
# ---------------------------------------------------------------------------

_POISON_ENVELOPE = (
    "class InvocationResult:\n"
    "    '''执行信封被复制到第二处——这不该放过。'''\n"
    "    pass\n"
)


def _stage_tree(tmp_path: Path, rel: str) -> Path:
    """把仓库真身文件按**同相对路径**复刻进 tmp_path，返回该临时树根。

    绝不往源码树写东西（项目铁律：源码树零残留）——注毒只发生在 pytest 私有临时目录。
    """
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_detector_bites_on_a_third_presentation_contract(tmp_path: Path):
    """注毒：合法真身之外再写一份 ``class CapabilityResult`` ⇒ 检测器必须报 2 处。

    若本测试红了，说明上面两条唯一性判据是恒过的假锁（"存在性糊过活性判据"）。
    """
    staged = _stage_tree(tmp_path, PRESENTATION_HOME)
    poison = staged / "plugins" / "poison_second_contract.py"
    poison.write_text("class CapabilityResult:\n    pass\n", encoding="utf-8")

    ast_hits, regex_hits = scan_class_definitions(staged, "CapabilityResult")
    assert _count_in(ast_hits, PRESENTATION_HOME) == 1, "复刻的真身自身都没被认出＝扫描根路径写错"
    assert len(ast_hits) == 2, f"注入第二份呈现契约后仍只报 {ast_hits}＝假锁"
    assert len(regex_hits) == 2, f"正则路数失明：{regex_hits}"

    # 真实树（只读）必须仍恰 1 处——与上面构成"注毒前后差一个"的对照。
    real_ast, real_regex = scan_class_definitions(REPO_ROOT, "CapabilityResult")
    assert real_ast == [PRESENTATION_HOME] and real_regex == [PRESENTATION_HOME]


def test_detector_bites_on_a_second_envelope(tmp_path: Path):
    """注毒：第二份 ``class InvocationResult``（含缩进/嵌套形态，两路数都必须抓住）。"""
    staged = _stage_tree(tmp_path, ENVELOPE_HOME)
    (staged / "tests").mkdir(parents=True, exist_ok=True)
    (staged / "tests" / "poison_shell.py").write_text(_POISON_ENVELOPE, encoding="utf-8")
    ast_hits, regex_hits = scan_class_definitions(staged, "InvocationResult")
    assert ast_hits == [ENVELOPE_HOME, "tests/poison_shell.py"], ast_hits
    assert regex_hits == ast_hits, f"两路数不同意：AST={ast_hits} 正则={regex_hits}"

    nested = staged / "tests" / "poison_nested.py"
    nested.write_text(
        "def build():\n    class InvocationResult:\n        pass\n    return InvocationResult\n",
        encoding="utf-8",
    )
    nested_ast, nested_regex = scan_class_definitions(staged, "InvocationResult")
    assert len(nested_ast) == 3 and len(nested_regex) == 3, (
        f"缩进/嵌套定义被某一路数漏看：AST={nested_ast} 正则={nested_regex}"
    )
