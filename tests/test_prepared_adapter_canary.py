"""prepared 执行形（B0 地基 + `bot.weather` 金丝雀）的登记与活性锁。

为什么单开一件（而不是塞进 `test_orchestration_callsite_single.py`）：那件是**直呼点唯一性**
门，owner 判据是"每个直呼点恰一处登记"；本件管的是"执行体由装配现场交来的那一族能力，
中央确实在管、且中央没有偷偷自己再造一条"。两件事失败方式不同，混在一起将来谁也不敢改。

prepared 形与命令形只差一句生死：命令形的 builder 只吃 config，拿不到成品时按
`implementation_ref` 自建是同构的；prepared 形的 builder 还要运行期件（本金丝雀是
`render_backend`），**自建＝丢注入**，会跑出一条与装配现场不同的第二通路——比"没走中央"
更坏，因为看起来走了中央，实际跑的是另一套引擎。所以本件的核心判据不是"能跑"，
而是"**跑的就是交来的那一个**"。
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from types import SimpleNamespace

import pytest

#: via 全身份等值判据真身（HARDEN-1 I-1）：期望值从注入成品现读、不走被审拼接函数；
#: 本件与矩阵件/batch3 共用同一支判据，不留第二份拼接逻辑。
from test_central_via_identity_and_entry_durability import expected_via

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

WEATHER_CID = "bot.weather"
REGISTRY_FILE = "domains/chat_reply/runtime/capability_registry.py"
#: 建请求一律走这个引用：下面有条用例会把 `cp.CapabilityRequest` 换成假构造器（模拟装配
#: 现场没交成品），若本件自己也按模块属性取类，就会套娃调用自己。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-w-1",
        capability_id=WEATHER_CID,
        kind="text",
        body=body,
        audit_tags=["weather", "prepared-canary"],
    )


def _assembled(body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是 `_build_weather_with_backend` 的产物）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(body)

    return _capability


def _request(capability: object | None) -> cp.CapabilityRequest:
    context: dict[str, object] = {"config": SimpleNamespace(), "decision": SimpleNamespace()}
    if capability is not None:
        context["capability"] = capability
    return _REAL_REQUEST(
        capability_id=WEATHER_CID,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-w-1")},
        principal="3865067623",
        roles=("user",),
        request_id="req-w-1",
        session_key="private:3865067623",
        context=context,
    )


def _message() -> SimpleNamespace:
    return SimpleNamespace(request_id="req-w-1", text="天气", session_key="private:9", sender_id="9")


# --------------------------------------------------------------------- 登记面
def test_weather_row_declares_prepared_shape() -> None:
    """金丝雀在册：`bot.weather` 的执行形必须是 prepared，名册里必须有这一形。"""
    adapters = cp._route_execution_adapters()
    assert adapters.get(WEATHER_CID) == "prepared", (
        f"bot.weather 执行形漂移为 {adapters.get(WEATHER_CID)!r}"
        "＝prepared 地基失去在册样本（本件与缺口账同时失效）"
    )
    assert "prepared" in cp._KNOWN_ADAPTERS, "壳侧适配器名册没有 prepared＝地基被拆"


def test_prepared_row_gets_a_handler_from_derivation() -> None:
    """派生同源：每个已知 adapter 的行都必须有 handler，**不许只放开登记不实现信封**。

    施工图点名的最坏失效模式：只把 `"prepared"` 加进 `_KNOWN_ADAPTERS`、没写
    `_make_prepared_handler` ⇒ 派生期 `ValueError` ⇒ 中央件 import 崩 ⇒ 依赖它的门
    `pytest.skip` 静默变哑（**不是红**）。本锁直接量 `handlers`，把这条变成响亮判定。
    """
    handlers = cp.default_invoker().handlers
    for cid, adapter in cp._route_execution_adapters().items():
        assert adapter in cp._KNOWN_ADAPTERS, f"{cid}: 在册 adapter {adapter!r} 不在名册里"
        assert handlers.get(cid) is not None, (
            f"{cid}: adapter={adapter} 已放开登记却没有派生出 handler"
            "＝半批施工，中央件会在 import 期炸、门会静默变哑"
        )


# --------------------------------------------------------------------- 活性面
def test_prepared_handler_runs_the_injected_capability_not_a_rebuild() -> None:
    """核心判据：中央跑的就是调用方交来那一个成品（注入件没被 `ref` 重建偷偷替换）。"""
    calls: list[str] = []
    fake = _assembled("装配现场那一个", calls)
    result = cp.default_invoker().invoke(_request(fake))

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], "成品没被执行＝中央自己另跑了一条"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "装配现场那一个", (
        f"信封里的呈现结果不是成品吐出的那份：{presented}"
    )
    # via 必须**逐字符**说得出跑的是谁（HARDEN-1 I-1）：旧尺 `"_capability" in via` 恒真
    # （前缀自带这五个字），评审席注毒"砍成常量前缀"全绿；等值尺下常量前缀/恒定占位都红
    # （两形态自证见 test_central_via_identity_and_entry_durability）。
    assert result.via == expected_via(fake), (
        f"via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


def test_prepared_handler_without_capability_is_unavailable_never_rebuilt() -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail；**绝不允许**退回去按 ref 自建。"""
    result = cp.default_invoker().invoke(_request(None))

    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"缺执行体却给出 {result.status}＝中央可能偷偷按 ref 自建了一条第二通路"
    )
    assert "prepared" in result.detail, result.detail
    assert "build_weather_capability" in result.detail, (
        f"detail 没带在册真身，事后无从判断本该由谁交成品：{result.detail}"
    )
    assert cp.PRESENTATION_DATA_KEY not in result.data


def test_prepared_seam_falls_back_to_honest_line_not_silence(monkeypatch) -> None:
    """缝侧两态：交得进成品⇒跑成品；交不进⇒温和短句 + 终态入审计，绝不静默丢回复。"""
    calls: list[str] = []
    step = cp.orchestrated_command(WEATHER_CID, _assembled("成品", calls), SimpleNamespace())

    ok = step(_message(), SimpleNamespace(actor_roles=("user",)))
    assert calls == ["成品"], "缝没把成品交给中央执行（或中央另跑了一条）"
    assert ok.body == "成品" and ok.capability_id == WEATHER_CID, ok

    # 抽掉 context 里的成品：构造请求那一步换成"没交成品"的形态，模拟装配现场漏交。
    monkeypatch.setattr(cp, "CapabilityRequest", lambda **kwargs: _request(None))
    blocked = step(_message(), SimpleNamespace(actor_roles=("user",)))
    body = str(getattr(blocked, "body", "") or "")
    assert body.strip(), "中央拦下后缝返回空体＝用户侧静默丢回复"
    tags = list(getattr(blocked, "audit_tags", ()) or ())
    assert any("unavailable" in tag for tag in tags), f"终态没进审计：{tags}"


# --------------------------------------------------------------------- 自证
def test_prepared_locks_have_teeth() -> None:
    """注毒：把名册里的 prepared 摘掉 ⇒ 派生必须**响亮**炸，而不是静默少一条。

    这是施工图那条最坏路径的正向自证：地基被拆时全树 import 期就红，
    绝不给"门 skip、缺口账变哑"留空间。
    """
    original = cp._KNOWN_ADAPTERS
    try:
        cp._KNOWN_ADAPTERS = frozenset({"command"})
        with pytest.raises(ValueError) as caught:
            cp._route_execution_rows()
        assert "prepared" in str(caught.value), (
            f"摘掉名册后派生没有点名 prepared，而是给了别的错：{caught.value}"
        )
    finally:
        cp._KNOWN_ADAPTERS = original
    # 还原后立刻可派生（证明上面那发毒没留下半坏状态）。
    assert any(adapter == "prepared" for _descriptor, adapter in cp._route_execution_rows())


# ------------------------------------------------ 多入口活性锁（R-PREP C-1 根修的常驻证据）
_ROOT_INIT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)
#: 汇到层 2 主缝的两条生产通路（`_run_simple_capability` 内部亦经 `_run_capability_through_pipeline`）。
_SEAM_FUNNELS = frozenset({"_run_simple_capability", "_run_capability_through_pipeline"})


def _root_dispatch_comparisons(
    source: str | None = None,
) -> dict[str, set[str]]:
    """root 里"按 capability_id 分流"的函数 ⇒ 它比较过的那些 id（单一取数口，两处判据共用）。

    `source` 只为注毒自证留口：传入改写后的源码字符串就能在**内存里**验判据有无牙，
    不必也不许去改真树。
    """
    tree = ast.parse(source if source is not None else _ROOT_INIT.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        compared = {
            cmp.comparators[0].value
            for cmp in _own_nodes(node)
            if isinstance(cmp, ast.Compare)
            and isinstance(cmp.left, ast.Attribute)
            and cmp.left.attr == "capability_id"
            and isinstance(cmp.ops[0], ast.Eq)
            and isinstance(cmp.comparators[0], ast.Constant)
            and isinstance(cmp.comparators[0].value, str)
        }
        if compared:
            result[node.name] = compared
    return result


def _root_resolved_cids(source: str | None = None) -> set[str]:
    return {cid for cids in _root_dispatch_comparisons(source).values() for cid in cids}


def _root_entry_violations(
    source: str | None = None,
) -> tuple[list[str], int]:
    """返回 (违规函数清单, 参与判定的分发函数数)。"""
    text = source if source is not None else _ROOT_INIT.read_text(encoding="utf-8")
    comparisons = _root_dispatch_comparisons(text)
    tree = ast.parse(text)
    fn_by_name: dict[str, ast.AST] = {}
    funnels_by_fn: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        fn_by_name.setdefault(node.name, node)
        funnels_by_fn[node.name] = {
            call.func.id
            for call in _own_nodes(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in _SEAM_FUNNELS
        }
    del tree  # 判据一律走 _own_nodes，见下方"内层归内层"说明
    violations = [
        f"{name}: {sorted(cids)}"
        for name, cids in sorted(comparisons.items())
        if not funnels_by_fn.get(name)
    ]
    # 第二腿（R-CHOKE I-1 的形态）：函数按多个 capability_id 分流，却把汇合点的
    # `capability_id` 交成一个**只被字面量赋过值**的变量（或直接字面量）⇒ 它报给层 2 的
    # 永远不是被解析出来的那个 id。`_handle_alias` 当年正是这样绕过全部三把锁的。
    for name, cids in sorted(comparisons.items()):
        if len(cids) < 2:
            continue
        for literal in _funnel_literal_cids(fn_by_name[name], cids):
            violations.append(f"{name} 交固定 id {literal!r} 而非解析结果: {sorted(cids)}")
    return violations, len(comparisons)


def _own_nodes(scope: ast.AST):
    """该函数**自己**的节点，不下钻进更内层的函数。

    根的装配全嵌套在 `_register_nonebot_handlers` 里：不做这层隔离，外层函数会
    "看见"所有内层 handler 的比较与字面量，判据立刻变成假阳性一片
    （与 `test_outbound_bypass_prohibition_gate._own_nodes` 同一条教训，两处各写一份
    是因为它属另一门 owner 的私有工具，跨测试件互相 import 会让两门耦合到谁也不敢改）。
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _funnel_literal_cids(fn: ast.AST, cids: set[str]) -> list[str]:
    """分发函数交给汇合点的 capability_id：返回"注定是字面量"的那些。"""
    # 变量都只被常量赋过值 ⇒ 交出去的 id 与解析结果无关
    assigned: dict[str, set[ast.expr]] = {}
    for node in _own_nodes(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("capability_id"):
                    assigned.setdefault(target.id, set()).add(node.value)
    bad: list[str] = []
    for call in _own_nodes(fn):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in _SEAM_FUNNELS
        ):
            continue
        given: ast.expr | None = None
        for keyword in call.keywords:
            if keyword.arg == "capability_id":
                given = keyword.value
        if given is None and call.func.id == "_run_simple_capability" and len(call.args) > 3:
            given = call.args[3]
        if given is None:
            continue
        if isinstance(given, ast.Constant) and isinstance(given.value, str):
            bad.append(given.value)
            continue
        if isinstance(given, ast.Name):
            values = assigned.get(given.id)
            if values and all(
                isinstance(value, ast.Constant) for value in values
            ):
                bad.extend(
                    sorted({value.value for value in values if isinstance(value, ast.Constant)})
                )
    return bad


def test_every_resolved_capability_entry_reaches_the_central_seam() -> None:
    """在册执行形的能力，root 的**每一条**分发入口都必须汇到缝（不得有旁路入口）。

    立门前因（R-PREP C-1，本波第二个"全绿但没执法"）：`bot.weather`/`wiki`/`news`/`eat`/`epic`
    除命令入口外，还有别名与自然语言两条 `resolution.capability_id == "…"` 分支；那两条历史上
    把闭包直接交给 `_run_capability_through_pipeline` 而**不包缝** ⇒ 一个能力三条入口里两条
    不经层 2 治理，而缺口账按"唯一表声明了执行形"就记 WIRED 并降棘轮＝在记账面上作弊。
    修法是把"包缝"下沉到该汇合函数本体（一处覆盖全部入口），本锁把这个不变量钉成常驻判据：
    **凡比较过某 capability_id 的分发函数，必须汇到两条缝之一**。
    """
    violations, judged = _root_entry_violations()
    assert judged >= 1, (
        f"本锁扫到 {judged} 个按 capability_id 分发的函数＝root 的分发形态已换，须改写本锁"
    )
    # 非空转的真正锚点不是"函数有几个"，而是"当年出事那批双入口能力确实被本锁看着"：
    # R-PREP 点名的就是这五枚（命令入口走缝、别名/自然语言入口历史上不走缝）。
    covered = _root_resolved_cids()
    must_watch = {"bot.weather", "bot.wiki", "bot.news", "bot.eat", "bot.epic"}
    blind = must_watch - covered
    assert not blind, f"这些双入口能力没被任何分发函数比较到＝本锁对它们失明：{sorted(blind)}"
    assert not violations, (
        "这些分发函数按 capability_id 分流却不汇到中央缝＝存在绕过层 2 的第二入口："
        + "；".join(violations)
    )


def test_multi_entry_liveness_lock_has_teeth() -> None:
    """注毒：抹掉汇合点调用 ⇒ 同一判据必须点名那些只分流不汇缝的函数。

    刻意复用 `_root_entry_violations(source=…)` 而不是在这里再写一遍 AST 抽取：
    判据有两个副本时，将来改一个忘一个，注毒自证就会验一条已经没人走的路。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    clean_violations, judged = _root_entry_violations(source)
    assert not clean_violations and judged >= 1, "基线不干净，本自证失去意义"

    poisoned = source.replace("_run_capability_through_pipeline(", "_legacy_direct_dispatch(")
    assert poisoned != source, "注毒点消失（汇合函数被改名/搬走），须同步本自证"
    violations, _ = _root_entry_violations(poisoned)
    assert violations, "抹掉全部汇合点调用后仍无违规＝上面那条锁是空转判据"
    assert _root_resolved_cids(poisoned) == _root_resolved_cids(source), (
        "注毒把判据覆盖面也改了＝抽取出问题的不是汇合点，本自证没验到点上"
    )


def test_row_without_human_label_still_derives_a_title(monkeypatch) -> None:
    """内部席位在册 `label=""` 是诚实形态，派生器不得因此把整表判炸。

    立门前因（S-PREP-B2 实测）：想给 `bot.ignore` 登记执行形时，壳按 `title=decl.label`
    派生 ⇒ 空标签行让 `validate_registry` 报 `title 缺失`，**全表**跟着红。
    那是派生器把"这行没有人类可读标签"错当成"这行坏"。修法用 `label or value`，
    本锁钉住这条兜底仍然成立（不许再用"给内部席位补个标签"绕过去——那是为了让测试变绿
    而改在册事实）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    template = next(
        decl for decl in reg.ROUTE_CAPABILITY_DECLARATIONS if getattr(decl, "execution", None)
    )
    blank = dataclasses.replace(
        template,
        capability_id="bot.probe.no_label",
        label="",
        value="no_label",
        execution=dataclasses.replace(
            template.execution,
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
                "#build_echo_capability"
            ),
        ),
    )
    monkeypatch.setattr(reg, "ROUTE_CAPABILITY_DECLARATIONS", (blank,))

    rows = cp._route_execution_rows()
    assert [descriptor.capability_id for descriptor, _adapter in rows] == ["bot.probe.no_label"]
    assert rows[0][0].title == "no_label", (
        f"空标签行没兜到 value，而是给出 {rows[0][0].title!r}＝内部席位永远接不进中央"
    )
