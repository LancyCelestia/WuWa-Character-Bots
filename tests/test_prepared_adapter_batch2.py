"""prepared 执行形 P2 批（S-PREP-B2）的登记与活性锁（逐枚参数化，全离线）。

分工（与 batch1 同哲学，三件事失败方式不同、各管一段）：
``tests/test_prepared_adapter_canary.py`` 只管金丝雀 ``bot.weather`` 一枚；
``tests/test_descriptor_wiredness_ledger.py`` 只管「账面缺口 −N」这一个数；
本件管「这一批每一枚，中央确实跑的就是装配现场交来的那一个成品，且拿不到成品时
绝不按 ref 自建」。

P2 形态与 P1 的差别正是本件存在的理由：**两件**运行期注入而非一件。
``build_affinity_capability(config, *, affinity_store, render_backend, card_dir)``
（inspect 实跑原文），装配现场（根 ``__init__.py:4338-4343``）现构
``affinity_store=build_character_affinity_store(config_)`` 并捕获函数局部 ``render_backend``。
⇒ 按 ``implementation_ref`` 自建只会得到 ``affinity_store=None``，而真身第一句就回
「好感度功能未开启。」（``domains/chat_reply/capabilities/affinity.py:376-383``）——
**把一项能用的功能静默变成永久关闭**，比"没走中央"更坏。所以核心判据不是"能跑"，
而是"跑的就是交来那一个"，且"没交来 ⇒ UNAVAILABLE，绝不偷偷自建"。

真身生产可达性（证明登记不是假绿）：本枚根 handler 走
``await _run_simple_capability(bot, event, _build_affinity_with_backend, "bot.affinity", affinity)``
（根 ``:9000``），而 ``_run_simple_capability`` 内部把
``orchestrated_command(capability_id, capability_factory(config), config)`` 喂给 pipeline
——成品在装配现场就交进了中央缝。施工台账与本批**拒登**三枚的判据见
``.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-PREP-B2.md``。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_central_via_identity_and_entry_durability import expected_via

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: P2 批本轮登记的 1 枚（canary 的 bot.weather 与 batch1 的 10 枚不在内，各由自家钉）。
#: implementation_ref 尾段=域内 builder 符号，(d) 用它断言"缺成品时诚实点名本该由谁交，
#: 而不是静默自建"。
BATCH2: tuple[tuple[str, str], ...] = (
    ("bot.affinity", "build_affinity_capability"),
)
CIDS = tuple(cid for cid, _ in BATCH2)
#: (cid → builder 符号) 查表，供 (d) 断言 detail 点名。
_BUILDER = dict(BATCH2)
#: 拒登三枚的现状锁对象（判据与复跑见文件末 (e) 节；解除前先读那里的两把尺子）。
# 2026-09-22 退役 `bot.ignore`：本锁第②条尺子（title 缺失）已由主会话在派生器修好，
# 该枚随即被 S-PREP-B3 按本件 docstring  prescribed 的方式登记为 prepared（13 例矩阵全绿）。
REFUSED = ("bot.meme_library", "bot.group_info")
# 建请求走这个引用：下面有条用例会把 cp.CapabilityRequest 换成假构造器（模拟装配现场没交
# 成品），若本件自己也按模块属性取类，就会套娃调用自己（canary 同型教训）。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(cid: str, body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-pb2",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["prepared-batch2"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是 `_build_affinity_with_backend` 的产物）。"""

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
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-pb2")},
        principal="3865067623",
        roles=("user",),
        request_id="req-pb2",
        session_key="private:3865067623",
        context=context,
    )


def _message(cid: str) -> SimpleNamespace:
    return SimpleNamespace(request_id="req-pb2", text=cid, session_key="private:9", sender_id="9")


# --------------------------------------------------------------------- (a) 登记面
@pytest.mark.parametrize("cid", CIDS)
def test_row_declares_prepared_shape(cid: str) -> None:
    """P2 批在册：执行形必须是 prepared（不是 command、不是没填），名册里有 prepared。"""
    adapters = cp._route_execution_adapters()
    assert adapters.get(cid) == "prepared", (
        f"{cid} 执行形漂移为 {adapters.get(cid)!r}＝没登记成 prepared（登记假绿或被别的席改回）"
    )
    assert "prepared" in cp._KNOWN_ADAPTERS, "壳侧适配器名册没有 prepared＝地基被拆"


@pytest.mark.parametrize("cid,builder", BATCH2)
def test_registered_builder_really_needs_runtime_injection(cid: str, builder: str) -> None:
    """形态自证（本席四证之一钉成常驻门）：在册真身的**活签名**确实要 config 之外的件。

    为什么钉在这儿：prepared 与 command 的唯一分界就是"builder 只吃 config 吗"。这句在本批
    是手工 `inspect.signature` 实跑得出的（见 SEAT-S-PREP-B2 §Proof1），落成常驻马后就能被
    后来者"顺手改成 command 形"而无人复核——真身哪天把 store 改成自己现构（那时才该走命令形），
    本锁先响，改动就得带着理由来。判据不认行号、不抄字符串：直接 import 在册 ref 取签名。
    """
    import importlib
    import inspect

    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as cr,
    )

    row = next(
        decl for decl in cr.ROUTE_CAPABILITY_DECLARATIONS
        if decl.capability_id == cid and decl.execution is not None
    )
    assert row.execution is not None
    module_part, _, symbol = row.execution.implementation_ref.partition("#")
    assert symbol == builder, f"{cid}: 在册 provenance 漂了：{symbol!r} ≠ {builder!r}"
    fn = getattr(importlib.import_module(module_part.removesuffix(".py").replace("/", ".")), symbol)
    params = inspect.signature(fn).parameters
    beyond_config = [name for name in params if name != "config"]
    assert {"affinity_store", "render_backend"} <= set(beyond_config), (
        f"{cid}: builder 形参表 {list(params)} 里取不到装配期注入件＝它已退回命令形，"
        "本行该改 adapter=\"command\" 并同步缺口账，而不是留着 prepared 骗人"
    )


# --------------------------------------------------------------------- (b) 派生面
@pytest.mark.parametrize("cid", CIDS)
def test_declared_config_keys_exist_on_config_model(cid: str) -> None:
    """幽灵键锁（本席四证之一钉成常驻门）：`config_keys` 每一枚必须是真字段。

    ⚠ 判据只认 ``Config.model_fields``——``hasattr(Config, k)`` 对**真**字段也返回 False
    （pydantic 模型上字段是 descriptor，实例属性才解析），拿 hasattr 当尺子会把好键判成幽灵、
    把幽灵判成好键，两头都错。
    """
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as cr,
    )

    row = next(
        decl for decl in cr.ROUTE_CAPABILITY_DECLARATIONS
        if decl.capability_id == cid and decl.execution is not None
    )
    assert row.execution is not None
    fields = set(Config.model_fields)
    ghost = [key for key in row.execution.config_keys if key not in fields]
    assert not ghost, f"{cid}: config_keys 有幽灵键（Config 无此字段）：{ghost}"


@pytest.mark.parametrize("cid", CIDS)
def test_prepared_row_gets_a_handler_from_derivation(cid: str) -> None:
    """派生同源：prepared 行必须真的派生出 handler，不许只放开登记不实现信封。"""
    handlers = cp.default_invoker().handlers
    assert handlers.get(cid) is not None, (
        f"{cid}: adapter=prepared 已登记却没派生出 handler＝半批施工，"
        "中央件会在 import 期炸、缺口账门会静默变哑"
    )


# --------------------------------------------------------------------- (c) 活性：跑的就是交来那一个
@pytest.mark.parametrize("cid", CIDS)
def test_seam_runs_the_injected_capability_not_a_rebuild(cid: str) -> None:
    """核心判据（缝侧）：中央跑的就是调用方交来那一个成品，注入件没被 `ref` 重建偷偷替换。"""
    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    step = cp.orchestrated_command(cid, fake, SimpleNamespace())
    result = step(_message(cid), SimpleNamespace(actor_roles=("user",)))

    assert calls == ["装配现场那一个"], f"{cid}: 成品没被执行＝中央自己另跑了一条（丢注入的第二通路）"
    assert result.body == "装配现场那一个", f"{cid}: 返回的呈现不是成品吐出的那份：{result}"
    assert result.capability_id == cid, f"{cid}: 呈现结果串了能力 id：{result.capability_id}"


@pytest.mark.parametrize("cid", CIDS)
def test_invoker_runs_injected_capability_and_reports_via(cid: str) -> None:
    """活性（invoker 侧）：交进成品 ⇒ OK 且 via 说得出跑的是谁（I-1 同口径）。"""
    calls: list[str] = []
    fake = _assembled(cid, "成品", calls)
    result = cp.default_invoker().invoke(_request(cid, fake))
    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["成品"], f"{cid}: 成品没被执行"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "成品", f"{cid}: {presented}"
    # 等值而不是"前缀+含 _capability"——后者那把尺恒真（前缀本身已含），
    # 壳侧把 via 砍成常量前缀也照样绿（R-B3B4 评审 I-1 实跑坐效）。判据真身共享，别再抄第二支。
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


# --------------------------------------------------------------------- (d) 缺成品 ⇒ UNAVAILABLE，绝不自建
@pytest.mark.parametrize("cid", CIDS)
def test_without_injected_capability_is_unavailable_never_rebuilt(cid: str) -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail（点名在册真身 builder）；绝不允许退回按 ref 自建。

    P2 这里"自建"的后果比 P1 更硬：自建=affinity_store=None=真身直接回「功能未开启」，
    账面看起来跑成功、用户永远拿不到好感度——所以 detail 必须说得出本该由谁交。
    """
    result = cp.default_invoker().invoke(_request(cid, None))
    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"{cid}: 缺执行体却给出 {result.status}＝中央可能偷偷按 ref 自建了一条第二通路"
    )
    assert "prepared" in result.detail, result.detail
    assert _BUILDER[cid] in result.detail, (
        f"{cid}: detail 没带在册真身 builder，事后无从判断本该由谁交成品：{result.detail}"
    )
    assert cp.PRESENTATION_DATA_KEY not in result.data


@pytest.mark.parametrize("cid", CIDS)
def test_seam_without_capability_makes_no_direct_call(cid: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """缝侧两态：交不进成品 ⇒ 温和短句 + 终态入审计，且**绝不解封直调成品**（不越过中央）。"""
    calls: list[str] = []
    fake = _assembled(cid, "成品", calls)
    step = cp.orchestrated_command(cid, fake, SimpleNamespace())
    monkeypatch.setattr(cp, "CapabilityRequest", lambda **_kw: _request(cid, None))
    blocked = step(_message(cid), SimpleNamespace(actor_roles=("user",)))

    assert calls == [], f"{cid}: 拿不到 context 成品却直接解封调用＝绕过中央 invoker"
    assert str(getattr(blocked, "body", "")).strip(), f"{cid}: 中央拦下后返回空体＝用户侧静默丢回复"
    tags = list(getattr(blocked, "audit_tags", ()) or ())
    assert any("unavailable" in tag for tag in tags), f"{cid}: 终态没进审计：{tags}"


# ------------------------------------------------------------------ (e) 拒登现状锁
def test_refused_rows_still_declare_no_execution() -> None:
    """本批**实测拒登**的三枚必须仍然没有执行面——这是判据，不是遗留。

    为什么值得钉：``seam_registered_cids()`` 只读登记行就把 cid 记成 WIRED，而这三枚的
    生产路径**不经过** ``orchestrated_command``（根唯一 import 点在
    ``_run_simple_capability`` 体内）。谁在没改根之前先给它们填 execution，账面就会翻成
    WIRED 而生产零变化——正是本门最该拦的假绿。``bot.ignore`` 另有一把 title 判据在拦
    （兜底席 ``label=""`` ⇒ 派生描述符标题为空 ⇒ ``validate_registry`` 红）。
    摘牌指引（两把尺子任一不成立即须重测，别照抄本行删除）：
      ① 该 cid 出现 ``await _run_simple_capability(..., "<cid>", ...)`` 站点，或根里
         该能力改由 ``orchestrated_command`` 包裹；
      ② 壳侧描述符标题不再依赖空 label（`title=decl.label or decl.value` 一类一行修）。
    """
    adapters = cp._route_execution_adapters()
    for cid in REFUSED:
        assert cid not in adapters, (
            f"{cid} 长出执行面（adapter={adapters.get(cid)!r}）但本锁未随之核销＝账面可能已"
            "把没走中央的能力记成通电；请按 docstring 两把尺子复测后改本锁与缺口账"
        )
