"""中央常驻门（HARDEN-1）：`via` 执行体**全身份等值** + 根汇缝**入口耐久**的判据真身。

为什么单开一件（评审席 I-1/I-2 两条 Important 的落点）：

**I-1**——历次归因用例的断言长这样：
`via.startswith("caller_capability:") and "_capability" in via`。第二把尺**恒真**
（前缀 `caller_capability:` 本身就含 `_capability`），评审席注毒实测把生产 via 砍成
常量 `"caller_capability:"`（丢掉"到底跑了谁"）⇒ 全部逐 id 归因用例照样绿。全树没有
任何一处钉 `via == "caller_capability:<模块>.<qualname>"` 的**完整身份等值**。本件是
该等值判据的唯一真身：期望值从**注入的那枚成品对象**现读（`__module__` + `__qualname__`，
刻意不调用被审的 `cp._callable_identity`，防"期望与实际同源"式恒真），逐 id 活性锁住在
`test_central_dispatch_matrix.py`（prepared/command 两形、现算全集），批次件
（canary/batch3）与矩阵件一律 import 本件判据，不留第二份拼接逻辑。

**I-2**——"每个在册执行形 id 在根里确有汇缝入口"此前只住
`test_prepared_adapter_batch3.py` 的批次件（root-literal AST 锁）。批次测试将来一旦被
退役而判据没搬走，缺口账仍报现值、根却可以静默漂走。本件收编该抽取判据为唯一真身
（`root_funnel_literal_cids`），活性执法提进常驻缺口账门
`test_descriptor_wiredness_ledger.py`（落点理由：说谎的是**账面**——该门的 R9 注记本就
写着"两把锁缺一即假账"，本锁是第三把）；参数化源=唯一表现算，零手抄名单；注毒自证在
本件（内存源码副本，绝不碰 `plugins/**`）。

纪律：与矩阵件同——**绝不往 `default_invoker()` 注册任何东西**（单例，塞探针会让
`registry_ids == …` 那类集合比对门当场假红）；需要 handler 一律经
`_derived_handler` 从单例**读**派生件、放**私有** invoker 里跑。
"""

from __future__ import annotations

import ast
import pathlib
import sys
from types import SimpleNamespace

import pytest

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: 建请求一律走这个引用：注毒用例会把 `cp.CapabilityRequest` 等模块属性换掉，
#: 本件若按模块属性取类就可能套娃调用自己（canary/matrix 同款教训）。
_REAL_REQUEST = cp.CapabilityRequest

_ROOT_INIT = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


# ===========================================================================
# 判据真身 ①（I-1）：via 的期望值 = "caller_capability:" + 注入件现读全身份
# ===========================================================================
def expected_via(fn: object) -> str:
    """审计 via 的期望值——从**被注入的那枚成品**现读 `模块.限定名` 全身份。

    刻意**不**复用 `cp._callable_identity`：本门审的正是"壳侧拼接是否等于注入件的身份"。
    若期望值由被审函数自己算出，注毒身份提取器（返回空串/常量）会让判据同源恒真——
    那是台账 #49 记过的同型假绿。取法与生产 `_callable_identity` **同构但独立**
    （`__qualname__` 缺失退 `__name__`，再退 "?"），生产改拼接、换身份提取、整段丢身份
    三种漂移都会被这里的等值当场抓。`<locals>` 原样保留：装配现场的闭包身份正是证据。
    """
    module = str(getattr(fn, "__module__", "?") or "?")
    qualname = str(getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "?") or "?")
    return f"caller_capability:{module}.{qualname}"


# ===========================================================================
# 判据真身 ②（I-2）：根"汇缝字面量站点"抽取 + 唯一表现算 + 违规谓词
# ===========================================================================
#: 汇到层 2 主缝的两条生产通路（与 canary 的多入口活性锁同一对名字；那里管
#: "分流过的函数必须汇缝"，这里管"在册执行形必须确有汇缝站点"，两判据不同腿）。
_SEAM_FUNNELS = frozenset({"_run_simple_capability", "_run_capability_through_pipeline"})


def read_root_init_source() -> str:
    return _ROOT_INIT.read_text(encoding="utf-8")


def root_funnel_literal_cids(source: str | None = None) -> frozenset[str]:
    """根里被**字面量点名**送进汇缝函数的 capability_id 集合。

    只认字面量：别名/自然语言那些交动态 cid 的站点由 canary 的多入口活性锁负责。
    原 `test_prepared_adapter_batch3.py::test_root_seam_cid_set_matches_this_batches_claim`
    的内联 AST 判据收编至此（批次件改为 import 本函数），全树只留这一支。
    `source` 只为注毒自证留口：传入内存改写串即可验判据有牙，绝不改真树。
    """
    tree = ast.parse(source if source is not None else read_root_init_source())
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _SEAM_FUNNELS
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
            for kw in node.keywords:
                if (
                    kw.arg == "capability_id"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    found.add(str(kw.value.value))
    return frozenset(found)


def execution_shape_cids() -> dict[str, str]:
    """唯一表现算「在册执行形」cid → adapter（参数化/比对的唯一取数口，零手抄）。"""
    return dict(cp._route_execution_adapters())


def root_seam_durability_violations(
    declared: dict[str, str], funnel_cids: frozenset[str]
) -> list[str]:
    """在册执行形 id 在根汇缝字面量站点里消失 ⇒ 逐枚一条点名（归因唯一，可喂真树亦可喂毒源）。"""
    return [
        f"{cid}（执行形 {adapter}）已无根汇缝字面量站点＝缺口账仍按在册记电，根却漂了"
        for cid, adapter in sorted(declared.items())
        if cid not in funnel_cids
    ]


# ===========================================================================
# 夹具（与矩阵件同型；判据共享、夹具各留一份是仓库既有口径）
# ===========================================================================
def _presented(cid: str, body: str) -> object:
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-hdn1",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["harden-1"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟装配现场造出来的成品（身份=本件 `_assembled.<locals>._capability`）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(cid, body)

    return _capability


def _request(cid: str, capability: object | None) -> cp.CapabilityRequest:
    context: dict[str, object] = {"config": SimpleNamespace(), "decision": SimpleNamespace()}
    if capability is not None:
        context["capability"] = capability
    return _REAL_REQUEST(
        capability_id=cid,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-hdn1")},
        principal="3865067623",
        roles=("user",),
        request_id="req-hdn1",
        session_key="private:3865067623",
        context=context,
    )


def _derived_handler(cid: str) -> cp.HandlerFn:
    handler = cp.default_invoker().handlers.get(cid)
    assert handler is not None, f"{cid} 没派生出 handler（前提失效）"
    return handler


def _private_invoker(cid: str, handler: cp.HandlerFn) -> cp.CapabilityInvoker:
    invoker = cp.CapabilityInvoker(
        registry=cp.CapabilityRegistry(), handlers=cp.HandlerRegistry()
    )
    invoker.registry.register(cp.default_invoker().registry.get(cid))
    invoker.handlers.register(cid, handler)
    return invoker


# 采集期现算（矩阵件同款纪律：空表当场响亮炸，不给"0 条用例全绿"留空间）。
_COLLECTED: tuple[tuple[str, str], ...] = tuple(sorted(cp._route_execution_adapters().items()))
if not _COLLECTED:
    raise RuntimeError(
        "_route_execution_adapters() 一枚都没有＝唯一表执行形面消失或被改名，"
        "本件的 via 全身份锁与入口耐久锁会集体空转（不许靠 0 条用例通过）"
    )
PREPARED_IDS: tuple[str, ...] = tuple(cid for cid, a in _COLLECTED if a == "prepared")
COMMAND_IDS: tuple[str, ...] = tuple(cid for cid, a in _COLLECTED if a == "command")


# ===========================================================================
# ① I-1 活性：每一枚 prepared / command（注入优先分支）的 via 逐字符等值
# ===========================================================================
@pytest.mark.parametrize("cid", PREPARED_IDS)
def test_prepared_via_names_the_exact_executable(cid: str) -> None:
    """prepared 形：via **逐字符等于**注入成品的现读全身份（不是"带前缀"就完事）。"""
    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    result = _private_invoker(cid, _derived_handler(cid)).invoke(_request(cid, fake))

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], f"{cid}: 成品没被执行"
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


@pytest.mark.parametrize("cid", COMMAND_IDS)
def test_command_injected_via_names_the_exact_executable(cid: str) -> None:
    """command 形（注入优先分支）：同一把等值尺——两形共用一个判据真身。"""
    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    result = _private_invoker(cid, _derived_handler(cid)).invoke(_request(cid, fake))

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], f"{cid}: 交来的成品没被执行"
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


def test_via_identity_lock_has_teeth() -> None:
    """注毒（内存、monkeypatch 壳侧，不碰任何文件）：两种"丢身份"形态必须被等值尺抓。

    形态 A＝评审席定罪现场：via 被砍成常量 `"caller_capability:"`（身份提取返回空串）。
    形态 B＝更隐蔽的"恒定占位"：身份提取返回固定常量（永远说跑了同一个人）。
    两形态下**旧弱尺都绿**（本用例顺手把病灶钉成实据），新等值尺都红。
    """
    victim = min(PREPARED_IDS) if PREPARED_IDS else min(COMMAND_IDS)
    original = cp._callable_identity
    try:
        # —— 形态 A：常量前缀（身份整段丢失）
        cp._callable_identity = lambda fn: ""
        calls: list[str] = []
        fake = _assembled(victim, "成品", calls)
        poisoned = _private_invoker(victim, _derived_handler(victim)).invoke(_request(victim, fake))
        assert poisoned.via == "caller_capability:", f"毒没下进去：{poisoned.via!r}"
        # 病灶实据：旧弱断言在这种毒下照样通过（这正是 I-1 成立的原因）
        assert poisoned.via.startswith("caller_capability:") and "_capability" in poisoned.via
        assert poisoned.via != expected_via(fake), "等值尺在常量前缀毒下没红＝锁是空转"

        # —— 形态 B：恒定占位（永远同一个假身份）
        cp._callable_identity = lambda fn: "somebody.else"
        ghosted = _private_invoker(victim, _derived_handler(victim)).invoke(_request(victim, fake))
        assert ghosted.via == "caller_capability:somebody.else"
        assert ghosted.via != expected_via(fake), "等值尺在恒定占位毒下没红＝锁是空转"
    finally:
        cp._callable_identity = original
    # 还原后立刻恢复等值（证明上面两发毒没留下半坏状态）。
    restored = _private_invoker(victim, _derived_handler(victim)).invoke(_request(victim, fake))
    assert restored.via == expected_via(fake), restored.via


def test_via_attribution_covers_current_registry() -> None:
    """非空转守卫：本件参数化覆盖面必须**始终等于**唯一表现算（现算比对，零手抄名单）。

    新增一枚执行形而本件没看着它 ⇒ 红（参数化列表与现算不一致）；某形整批消失 ⇒ 也红
    （对应等值腿失去样本）。与矩阵件的覆盖守卫同源不同腿：那件管五行为矩阵，本件管
    via 身份与根汇缝两条新判据的覆盖面。
    """
    declared = execution_shape_cids()
    assert declared, "唯一表一枚执行形都没有＝本件全部判据空转"
    live_prepared = {cid for cid, adapter in declared.items() if adapter == "prepared"}
    live_command = {cid for cid, adapter in declared.items() if adapter == "command"}
    assert set(PREPARED_IDS) == live_prepared, (
        f"prepared 覆盖漂移：采集期 {sorted(PREPARED_IDS)} ≠ 现算 {sorted(live_prepared)}"
    )
    assert set(COMMAND_IDS) == live_command, (
        f"command 覆盖漂移：采集期 {sorted(COMMAND_IDS)} ≠ 现算 {sorted(live_command)}"
    )
    assert live_prepared and live_command, (
        f"某一形整批消失（prepared={len(live_prepared)}, command={len(live_command)}）"
        "＝对应等值腿在空转，须重判本件形态"
    )


# ===========================================================================
# ② I-2 注毒自证：拿掉某枚的根汇缝字面量 ⇒ 常驻锁必红且归因唯一
#    （活性锁本体住 test_descriptor_wiredness_ledger——"账面说谎处"；此处备牙）
# ===========================================================================
def test_root_seam_durability_lock_has_teeth() -> None:
    """注毒（内存源码副本）：抹掉受害 id 的全部字面量点名 ⇒ 违规谓词**恰好**点名该枚。

    先证干净现状零违规（否则本自证失去意义），再逐枚断言"覆盖面只少受害者一枚"——
    防止"整棵判据被抹平也能过"的粗注毒糊住归因。
    """
    source = read_root_init_source()
    declared = execution_shape_cids()
    clean = root_funnel_literal_cids(source)
    assert root_seam_durability_violations(declared, clean) == [], "基线不干净，本自证失去意义"
    assert clean & set(declared), "扫描一枚汇缝字面量站点都没看见＝判据对真树失明"

    victim = min(declared)
    # 毒形态=把受害者的字面量点名换成一个不在册的标记串：站点仍在、身份没了，
    # 且**语法合法**（不引入解析噪音，也不像裸 Name 那样只在部分上下文合法）。
    marker = "harden1.poison.gone"
    poisoned_source = source.replace(f'"{victim}"', f'"{marker}"')
    assert poisoned_source != source, f"注毒点消失（根里已无 {victim!r} 字面量），须同步本自证"
    poisoned = root_funnel_literal_cids(poisoned_source)
    assert victim not in poisoned
    assert poisoned == (clean - {victim}) | {marker}, (
        f"注毒波及了别的 id（应只掉 {victim}、只多标记）："
        f"多掉了 {sorted(clean - poisoned - {victim})}，多出了 {sorted(poisoned - clean - {marker})}"
    )
    violations = root_seam_durability_violations(declared, poisoned)
    assert len(violations) == 1 and victim in violations[0], (
        f"常驻锁对『拿掉某枚根汇缝字面量』没红或归因不唯一：{violations}"
    )
