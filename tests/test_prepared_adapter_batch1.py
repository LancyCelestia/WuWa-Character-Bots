"""prepared 执行形 P1 批（S-PREP-B1）的登记与活性锁（逐枚参数化，全离线）。

为什么单开一件（而不是塞进 canary/缺口账）：canary 只管金丝雀 `bot.weather` 一枚，
`test_descriptor_wiredness_ledger` 只管"账面缺口 −N"这一数字；本件管的是"这一批每一枚，
中央确实跑的就是装配现场交来的那一个成品、且拿不到成品时绝不按 ref 自建"。三件事失败方式
不同，各管一段。

prepared 形与命令形只差一句生死：命令形的 builder 只吃 config，拿不到成品时按
`implementation_ref` 自建是同构的；prepared 批的 builder 还要运行期 `render_backend`
（divination 另带 draw_store/fortune_key/clock），**自建＝丢注入**，会跑出一条与装配现场
不同的第二通路——比"没走中央"更坏。所以本件每枚的核心判据不是"能跑"，而是
"**跑的就是交来的那一个**"，且"没交来 ⇒ UNAVAILABLE，绝不偷偷自建"。

真身生产可达性（证明登记不是假绿）：这 10 枚的根 handler 全部走
`await _run_simple_capability(bot, event, _build_*_with_backend, "<cid>", <matcher>)`，
而 `_run_simple_capability` 内部把 `orchestrated_command(cid, factory(config), config)`
喂给 pipeline —— 即成品在装配现场就交进了中央缝。逐枚 seam 调用点行号见
`.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-PREP-B1.md`。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: P1 批本轮登记的 10 枚（canary 的 bot.weather 不在内，它由
#: tests/test_prepared_adapter_canary.py 单独钉）。implementation_ref 尾段=域内 builder 符号，
#: (d) 用它断言"缺成品时诚实点名本该由谁交，而不是静默自建"。
BATCH1: tuple[tuple[str, str], ...] = (
    ("bot.market", "build_market_capability"),
    ("bot.stocks", "build_stocks_capability"),
    ("bot.fx", "build_fx_capability"),
    ("bot.commodities", "build_commodities_capability"),
    ("bot.bond", "build_bond_capability"),
    ("bot.northbound", "build_northbound_capability"),
    ("bot.epic", "build_epic_capability"),
    ("bot.eat", "build_eat_capability"),
    ("bot.divination", "build_divination_capability"),
    ("bot.emergency_info", "build_emergency_info_capability"),
)
CIDS = tuple(cid for cid, _ in BATCH1)
#: (cid → builder 符号) 查表，供 (d) 断言 detail 点名。
_BUILDER = dict(BATCH1)
# 建请求走这个引用：下面有条用例会把 cp.CapabilityRequest 换成假构造器（模拟装配现场没交
# 成品），若本件自己也按模块属性取类，就会套娃调用自己（canary 同型教训）。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(cid: str, body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-pb1",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["prepared-batch1"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是 `_build_*_with_backend` 的产物）。"""

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
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-pb1")},
        principal="3865067623",
        roles=("user",),
        request_id="req-pb1",
        session_key="private:3865067623",
        context=context,
    )


def _message(cid: str) -> SimpleNamespace:
    return SimpleNamespace(request_id="req-pb1", text=cid, session_key="private:9", sender_id="9")


# --------------------------------------------------------------------- (a) 登记面
@pytest.mark.parametrize("cid", CIDS)
def test_row_declares_prepared_shape(cid: str) -> None:
    """P1 批在册：每枚执行形必须是 prepared（不是 command、不是没填），名册里有 prepared。"""
    adapters = cp._route_execution_adapters()
    assert adapters.get(cid) == "prepared", (
        f"{cid} 执行形漂移为 {adapters.get(cid)!r}＝没登记成 prepared（登记假绿或被别的席改回）"
    )
    assert "prepared" in cp._KNOWN_ADAPTERS, "壳侧适配器名册没有 prepared＝地基被拆"


# --------------------------------------------------------------------- (b) 派生面
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
    """活性（invoker 侧）：交进成品 ⇒ OK 且 via 说得出跑的是谁（I-1 同口径），
    "在册说 prepared、实跑另一套"从此可判。"""
    calls: list[str] = []
    result = cp.default_invoker().invoke(_request(cid, _assembled(cid, "成品", calls)))
    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["成品"], f"{cid}: 成品没被执行"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "成品", f"{cid}: {presented}"
    assert result.via.startswith("caller_capability:") and "_capability" in result.via, result.via


# --------------------------------------------------------------------- (d) 缺成品 ⇒ UNAVAILABLE，绝不自建
@pytest.mark.parametrize("cid", CIDS)
def test_without_injected_capability_is_unavailable_never_rebuilt(cid: str) -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail（点名本该交成品的 builder）；绝不允许退回按 ref 自建。"""
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
    """缝侧两态：交不进成品 ⇒ 温和短句 + 终态入审计，且**绝不解封直调成品**（不越过中央）。

    这里 fake 仍被 orchestrated_command 收下（模拟装配现场手上有成品），但 monkeypatch 把
    CapabilityRequest 换成"往 context 里不放 capability"的形态 ⇒ handler 拿不到成品 ⇒ UNAVAILABLE
    ⇒ 缝回落温和短句。关键：`calls` 必须为空——handler 不许因为拿不到 context 成品就直接
    `capability(message, decision)` 解封装，也不许 import ref 真身自建。
    """
    calls: list[str] = []
    fake = _assembled(cid, "成品", calls)
    step = cp.orchestrated_command(cid, fake, SimpleNamespace())
    monkeypatch.setattr(cp, "CapabilityRequest", lambda **_kw: _request(cid, None))
    blocked = step(_message(cid), SimpleNamespace(actor_roles=("user",)))

    assert calls == [], f"{cid}: 拿不到 context 成品却直接解封调用＝绕过中央 invoker"
    assert str(getattr(blocked, "body", "")).strip(), f"{cid}: 中央拦下后返回空体＝用户侧静默丢回复"
    tags = list(getattr(blocked, "audit_tags", ()) or ())
    assert any("unavailable" in tag for tag in tags), f"{cid}: 终态没进审计：{tags}"
