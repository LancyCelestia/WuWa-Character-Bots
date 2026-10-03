"""计时伞「剩余口径」锁（席 V1 · P5.7 / P5.12，2026-10-02）。

一句话——**中央 invoker 的每一次尝试过去各拿一份满预算，串起来远超用户等待上限**
（2026-10-01 实测叠加 ≈580s＝能力硬超时 400s + 一整段 180s 配音，而配音段整个跑在
硬超时之外）。本件锁的是修法后的新判据：请求带了计时伞
（``request.context[DEADLINE_CONTEXT_KEY]``＝单调时钟绝对值）时，每一腿只准花
「伞里剩多少 ÷ 还要跑的腿数」；伞耗尽即**停腿**并交回在册那一族 ``CapabilityTimeout``。

双向自测（SEAT-RULES 判据纪律）——每个新判据都配一枚"做对必须绿"的反向腿：

* 注毒方向：把 `_attempt_budget` 改回"每腿一份满预算"、把 `_bind_umbrella` 删掉、
  把伞耗尽那一支改成静默返回 ⇒ 本文件必红；
* 不误伤方向：**没有伞时逐字节现状**（``test_umbrella_absent_*``），这一条同时是
  SEAT-F-BAKE 那把锁（``tests/test_central_fallback_budget.py``）的前提——它钉的正是
  "无伞时降级腿预算与主链耗时无关"，本波只在伞在场时做除法，两把锁不打架。

全离线、零真实等待：假钟替入 ``capability_protocols`` 模块内的 ``time`` **名字**
（只换 ``monotonic``），执行体替身把「X 秒内没回来就 TimeoutError」搬到虚拟钟上，
并把**每次尝试真正拿到的预算 X** 记进 ``offered`` 供断言直读。
唯一用到真线程的那件（``test_nested_invoke_inherits_*``）是刻意的：contextvar
**不跨线程自动传播**，只有起一枚真线程才能证明「嵌套腿继承同一把伞」靠的是
``_bind_umbrella`` 那一绑，而不是运气。

纪律：一律走私有 invoker，绝不往 ``default_invoker()`` 注册任何东西（单例，
塞探针会让集合比对类门当场假红——``test_central_dispatch_matrix.py`` 同款教训）。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import math
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import deadline as dl
from plugins.bot_unified_runtime.runtime import capability_protocols as cp
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    HONEST_DEGRADE_PREFIX,
    INVOKER_ERROR_DATA_KEY,
    CapabilityDescriptor,
    CapabilityFamily,
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilityRequest,
    FallbackRegistry,
    HandlerRegistry,
    HealthProbeRegistry,
    InvocationResult,
    InvocationStatus,
)

_REAL_TIME = time
ATTEMPT_CAP = 20.0
CID = "media.test.umbrella"
INNER_CID = "media.test.umbrella.inner"
HONEST = (HONEST_DEGRADE_PREFIX + "诚实无结果",)


# ---------------------------------------------------------------------------
# 确定性装置（假钟 + 记账执行体）
# ---------------------------------------------------------------------------


class FakeClock:
    """单调假钟：只由被测 handler 自己「烧」着前进，进程真实耗时对判据零贡献。"""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def burn(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


class TimeNamespace:
    """``capability_protocols`` 里 ``time`` 这个名字的替身（只换 ``monotonic``）。"""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._real = _REAL_TIME

    def monotonic(self) -> float:
        return self._clock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


@dataclasses.dataclass
class VirtualExecutor:
    """执行体替身：按序记账「谁被调了 / 拿到的预算 / 烧掉的虚拟时长」。

    ``threaded=True`` ⇒ 每次 submit 起一枚**真线程**（证明伞的跨线程绑定是承重件）。
    默认同步执行（零真实等待，与 ``test_central_fallback_budget`` 同量具口径）。
    """

    clock: FakeClock
    threaded: bool = False
    invocations: list[str] = dataclasses.field(default_factory=list)
    offered: list[float | None] = dataclasses.field(default_factory=list)
    durations: list[float] = dataclasses.field(default_factory=list)
    seen_umbrella: list[float | None] = dataclasses.field(default_factory=list)

    def _run(
        self, fn: Callable[[], InvocationResult]
    ) -> tuple[float, InvocationResult | None, BaseException | None]:
        before = self.clock()
        value: InvocationResult | None = None
        error: BaseException | None = None
        try:
            value = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样交回，判据在 result() 落
            error = exc
        return self.clock() - before, value, error

    def submit(self, fn: Callable[[], InvocationResult]) -> VirtualFuture:
        if self.threaded:
            box: dict[str, Any] = {}

            def _target() -> None:
                box["duration"], box["value"], box["error"] = self._run(fn)

            thread = threading.Thread(target=_target)
            thread.start()
            thread.join()
            duration, value, error = (
                float(box["duration"]),
                box.get("value"),
                box.get("error"),
            )
        else:
            duration, value, error = self._run(fn)
        self.durations.append(duration)
        return VirtualFuture(self, duration, value, error)

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class VirtualFuture:
    """真池 Future 的契约替身：``result(timeout=X)`` 用虚拟时长判超时，并记下 X。"""

    def __init__(
        self,
        owner: VirtualExecutor,
        duration: float,
        value: InvocationResult | None,
        error: BaseException | None,
    ) -> None:
        self._owner = owner
        self._duration = duration
        self._value = value
        self._error = error

    def result(self, timeout: float | None = None) -> InvocationResult:
        self._owner.offered.append(timeout)
        if timeout is not None and self._duration > timeout:
            raise concurrent.futures.TimeoutError()
        if self._error is not None:
            raise self._error
        assert self._value is not None, "既没超时、又无异常，却也没有结果体"
        return self._value

    def cancel(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


def _request(
    capability_id: str = CID,
    *,
    deadline: object = None,
    roles: tuple[str, ...] = ("user",),
) -> CapabilityRequest:
    context: dict[str, Any] = {}
    if deadline is not None:
        context[dl.DEADLINE_CONTEXT_KEY] = deadline
    return CapabilityRequest(
        capability_id=capability_id,
        payload={},
        principal="tester",
        roles=roles,
        context=context,
        request_id="req-umbrella-1",
        session_key="group_111_222",
    )


@dataclasses.dataclass
class Scenario:
    invoker: CapabilityInvoker
    executor: VirtualExecutor

    @contextlib.contextmanager
    def shell(self) -> Iterator[None]:
        with mock.patch.object(
            cp, "time", TimeNamespace(self.executor.clock)
        ), mock.patch.object(cp, "_get_capability_executor", lambda: self.executor):
            yield

    def invoke(self, request: CapabilityRequest) -> InvocationResult:
        """唯一入口：把假钟/虚拟池只替入这一次调用（装配期 patch 会让后建场景顶掉先建的）。"""
        with self.shell():
            return self.invoker.invoke(request)


def _ok(label: str, burn: float = 0.0) -> Callable[..., InvocationResult]:
    def _handler(request: CapabilityRequest) -> InvocationResult:
        rig_note(label)
        _CLOCK_SINK["clock"].burn(burn)
        return InvocationResult(
            capability_id=request.capability_id, status=InvocationStatus.OK, data={}
        )

    return _handler


#: handler 需要两件事：报身份、烧虚拟钟。装配期把这两样接到模块级句柄上，
#: 免得每枚 handler 都闭包一份 rig（闭包引用宿主函数内的名字＝台账 #59★ 那型）。
rig_note: Callable[[str], None] = lambda _label: None
_CLOCK_SINK: dict[str, FakeClock] = {"clock": FakeClock()}


def _boom(label: str, burn: float) -> Callable[..., InvocationResult]:
    def _handler(request: CapabilityRequest) -> InvocationResult:
        rig_note(label)
        _CLOCK_SINK["clock"].burn(burn)
        raise RuntimeError(f"{label} 慢失败")

    return _handler


def wire(
    *,
    timeout_seconds: float = ATTEMPT_CAP,
    handler: Callable[..., InvocationResult] | None = None,
    fallback_chain: tuple[str, ...] = HONEST,
    fallbacks: tuple[tuple[str, Callable[..., InvocationResult]], ...] = (),
    inner_timeout: float = ATTEMPT_CAP,
    inner_handler: Callable[..., InvocationResult] | None = None,
    threaded: bool = False,
    clock_start: float = 1_000.0,
) -> Scenario:
    """私有 invoker（outer + 可选 inner 两枚描述符）并绑定一套确定性装置。"""
    global rig_note
    clock = FakeClock(clock_start)
    executor = VirtualExecutor(clock=clock, threaded=threaded)
    rig_note = executor.invocations.append
    _CLOCK_SINK["clock"] = clock
    invoker = CapabilityInvoker(
        registry=CapabilityRegistry(),
        handlers=HandlerRegistry(),
        fallbacks=FallbackRegistry(),
        probes=HealthProbeRegistry(),
    )
    invoker.registry.register(
        CapabilityDescriptor(
            capability_id=CID,
            family=CapabilityFamily.MEDIA,
            title="计时伞被测能力",
            input_protocol="test.v1{in}",
            output_protocol="test.v1{out}",
            timeout_seconds=timeout_seconds,
            fallback_chain=fallback_chain,
        )
    )
    if inner_handler is not None:
        invoker.registry.register(
            CapabilityDescriptor(
                capability_id=INNER_CID,
                family=CapabilityFamily.MEDIA,
                title="计时伞嵌套腿（＝逐块产出步的形状）",
                input_protocol="test.v1{chunk}",
                output_protocol="test.v1{audio}",
                timeout_seconds=inner_timeout,
                fallback_chain=HONEST,
            )
        )
        invoker.handlers.register(INNER_CID, inner_handler)
    if handler is not None:
        invoker.handlers.register(CID, handler)
    for name, fb in fallbacks:
        invoker.fallbacks.register(CID, name, fb)
    return Scenario(invoker=invoker, executor=executor)


# ---------------------------------------------------------------------------
# ① 剩余口径（新判据本体）
# ---------------------------------------------------------------------------


def test_primary_and_registered_fallback_share_remaining_not_full_copies() -> None:
    """伞剩 20s、链＝主链 + 一枚注册降级腿 ⇒ 两腿共享剩余，而不是各拿一份满 20s。

    注毒自证：把 ``_leg_budget_seconds`` 退回 ``_attempt_budget``（每腿一份满预算）
    本用例立刻红（左 [10.0, 12.0]，右 [20.0, 20.0]＝旧形态最坏 40s）。
    """
    sc = wire(
        handler=_boom("primary", 8.0),
        fallback_chain=("vlm_candidate", HONEST[0]),
        fallbacks=(("vlm_candidate", _ok("vlm_candidate", 2.0)),),
    )
    request = _request(deadline=sc.executor.clock() + 20.0)
    result = sc.invoke(request)

    assert sc.executor.invocations == ["primary", "vlm_candidate"]
    # 主链：legs_left=1+1 ⇒ min(20, 20/2)=10.0（8s 的慢失败放得下，照常进降级链）。
    # 降级腿：已烧 8 ⇒ 剩 12，legs_left=1 ⇒ min(20, 12)=12.0。
    assert sc.executor.offered == [10.0, 12.0], sc.executor.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status
    # 不变量：串起来的真实耗时永远不越过伞（这里 8+2=10 ≤ 20）。
    assert sum(sc.executor.durations) <= 20.0, sc.executor.durations


def test_multiple_registered_legs_reserve_for_every_one_of_them() -> None:
    """两枚注册降级腿也要各留一份：主链只能拿 12÷3=4，链上逐腿按剩余重算。"""
    sc = wire(
        handler=_boom("primary", 0.0),
        fallback_chain=("leg_one", "leg_two", HONEST[0]),
        fallbacks=(
            ("leg_one", _boom("leg_one", 0.0)),
            ("leg_two", _ok("leg_two", 0.0)),
        ),
    )
    result = sc.invoke(_request(deadline=sc.executor.clock() + 12.0))
    assert sc.executor.invocations == ["primary", "leg_one", "leg_two"]
    # 主链 12/3=4.0；腿一还剩 12、还有两腿 ⇒ 6.0；腿二还剩 12、只剩它自己 ⇒ 12.0。
    assert sc.executor.offered == [4.0, 6.0, 12.0], sc.executor.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status
    assert result.attempts == 3, result.attempts


def test_exhausted_umbrella_stops_before_dispatch_and_keeps_one_family() -> None:
    """伞已耗尽 ⇒ **不派执行体**，落 TIMEOUT 并交回在册那一族 ``CapabilityTimeout``。

    两条硬判据一次量到：① 禁第二族异常（``type(...) is`` 精确身份，不是"是它的子类"）；
    ② 不许静默返回结果（那正是 AGENTS #49「不抛异常所以不出卡」的旧形态）。
    """
    sc = wire(handler=_ok("primary", 0.0))
    result = sc.invoke(_request(deadline=sc.executor.clock() - 1.0))

    assert sc.executor.invocations == [], "伞耗尽还派执行体＝白等"
    assert sc.executor.offered == [], sc.executor.offered
    assert result.status is InvocationStatus.TIMEOUT, result.status
    carried = result.data.get(INVOKER_ERROR_DATA_KEY)
    assert type(carried) is cp.CapabilityTimeout, f"冒出第二族异常：{type(carried)!r}"


def test_umbrella_only_shaves_never_leniens_a_leg() -> None:
    """只削不加：伞再宽裕也不许让某一腿超过声明的单次上限，中央硬顶一寸未松。"""
    sc = wire(timeout_seconds=900.0, handler=_ok("primary", 0.0))
    result = sc.invoke(_request(deadline=sc.executor.clock() + 5_000.0))
    assert result.status is InvocationStatus.OK, result.detail
    # 900 越界 ⇒ 仍被 _MAX_TIMEOUT_SECONDS 钳制，且 min() 那一刀与伞无关。
    assert sc.executor.offered == [cp._MAX_TIMEOUT_SECONDS], sc.executor.offered


# ---------------------------------------------------------------------------
# ② 反向不误伤（没伞＝现状；畸形伞＝当没伞）
# ---------------------------------------------------------------------------


def test_umbrella_absent_keeps_full_per_leg_budget_f_bake_semantics() -> None:
    """无伞 ⇒ 逐字节现状：主链烧 19s 后抛，降级腿照旧拿整份 20s。

    这一条保住 ``tests/test_central_fallback_budget.py``（SEAT-F-BAKE）的前提——
    「降级腿预算与主链耗时无关」只在没有伞时才成立，本波不许把它悄悄改成相反形。
    """
    sc = wire(
        handler=_boom("primary", 19.0),
        fallback_chain=("vlm_candidate", HONEST[0]),
        fallbacks=(("vlm_candidate", _ok("vlm_candidate", 6.0)),),
    )
    result = sc.invoke(_request())
    assert sc.executor.offered == [ATTEMPT_CAP, ATTEMPT_CAP], sc.executor.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status


@pytest.mark.parametrize(
    "garbage",
    ["12", -1.0, 0.0, float("inf"), float("nan"), True, object()],
    ids=["str", "negative", "zero", "inf", "nan", "bool", "object"],
)
def test_garbage_deadline_is_treated_as_no_umbrella(garbage: object) -> None:
    """消毒优先于记账：畸形伞一律当"没有伞"，**绝不**掐成 0 把每条回复变成超时。

    注毒自证：把 ``normalize_deadline`` 的 ``isfinite``/``<=0`` 守卫摘掉，本用例必红
    （inf/nan/负数会把预算烧成荒谬值或直接停腿）。
    """
    sc = wire(handler=_ok("primary", 0.0))
    result = sc.invoke(_request(deadline=garbage))
    assert result.status is InvocationStatus.OK, (garbage, result.status, result.detail)
    assert sc.executor.offered == [ATTEMPT_CAP], sc.executor.offered


def test_normalize_deadline_accepts_only_finite_positive() -> None:
    """尺子本体的双向腿：好值原样、坏值 None（``None``＝无伞，不是 0）。"""
    assert dl.normalize_deadline(1_234.5) == 1_234.5
    for bad in (None, "abc", -0.5, 0.0, math.inf, math.nan, True):
        assert dl.normalize_deadline(bad) is None, bad


def test_leg_budget_seconds_pure_math_has_no_hidden_clock() -> None:
    """算式直读（不依赖被测模块的钟）：无伞原样、有伞按份、耗尽给 0。"""
    assert dl.leg_budget_seconds(None, now=0.0, attempt_seconds=20.0, legs_left=3) == 20.0
    assert dl.leg_budget_seconds(100.0, now=94.0, attempt_seconds=20.0, legs_left=2) == 3.0
    assert dl.leg_budget_seconds(100.0, now=99.5, attempt_seconds=20.0, legs_left=4) == 0.125
    assert dl.leg_budget_seconds(100.0, now=100.0, attempt_seconds=20.0, legs_left=1) == 0.0
    # legs_left 只作下限保护：0/负数不得翻成"多留一份"或"吃掉全部"。
    assert dl.leg_budget_seconds(100.0, now=90.0, attempt_seconds=20.0, legs_left=0) == 10.0


# ---------------------------------------------------------------------------
# ③ TTS 段入伞（嵌套继承）
# ---------------------------------------------------------------------------


def test_nested_invoke_inherits_the_same_umbrella_across_worker_thread() -> None:
    """逐块合成的形状：外层派发占一枚 worker，内层腿**必须继承同一把伞**。

    这是「TTS 合成段纳入同一把伞」的机制本体——伞由 ``_execute_handler`` 提交进池时
    ``_bind_umbrella`` 显式绑进 worker 线程（contextvar 不跨线程自动传播）。
    注毒自证：删掉那一绑，内层读到的伞就是 ``None`` ⇒ 本用例红，而生产表现是
    "配音段重新各拿一份满预算"（＝本波要修的原缺陷回潮）。
    """
    sc = wire(
        threaded=True, clock_start=2_000.0, inner_handler=_ok("inner", 0.0)
    )

    def outer(request: CapabilityRequest) -> InvocationResult:
        # 一枚 handler 里连发三次 inner＝transform 逐块调产出步的同构形状。
        for _ in range(3):
            sc.executor.seen_umbrella.append(cp._UMBRELLA.get())
            sc.invoker.invoke(_request(INNER_CID, deadline=None))
        return InvocationResult(
            capability_id=request.capability_id, status=InvocationStatus.OK, data={}
        )

    sc.invoker.handlers.register(CID, outer)
    deadline = sc.executor.clock() + 30.0
    result = sc.invoke(_request(deadline=deadline))

    assert result.status is InvocationStatus.OK, result.detail
    # ① 外层这一腿的预算被伞削到 30s（声明值 20 更小 ⇒ 仍给 20；见下一条的宽顶形状）。
    assert sc.executor.offered[0] == ATTEMPT_CAP, sc.executor.offered
    # ② 三次嵌套都看见同一把伞——不是 None、不是外层声明值。
    assert sc.executor.seen_umbrella == [deadline] * 3, sc.executor.seen_umbrella
    # ③ 线程用完即复原，绝不把上一轮的伞粘给下一轮（worker 是复用的）。
    assert cp._UMBRELLA.get() is None


def test_nested_chunks_are_bounded_by_the_umbrella_not_by_full_copies() -> None:
    """宽伞下的逐块形状：外层顶 180s、内层顶 90s，伞只剩 25s ⇒ 交出去的那一腿就是 25s。

    对应实测缺口：配音段今天最坏 180s，而它整段跑在能力硬超时之外 ⇒ 叠加 ≈580s。
    """
    sc = wire(timeout_seconds=180.0, threaded=True, clock_start=5_000.0)

    def outer(request: CapabilityRequest) -> InvocationResult:
        sc.executor.seen_umbrella.append(cp._UMBRELLA.get())
        return InvocationResult(
            capability_id=request.capability_id, status=InvocationStatus.OK, data={}
        )

    sc.invoker.handlers.register(CID, outer)
    result = sc.invoke(_request(deadline=sc.executor.clock() + 25.0))
    assert result.status is InvocationStatus.OK, result.detail
    # 声明顶 180s、伞只剩 25s ⇒ 交出去的那一腿就是 25s（旧形态这里是 180s，整段白等）。
    assert sc.executor.offered == [25.0], sc.executor.offered


# ---------------------------------------------------------------------------
# ④ 接线与单一真身
# ---------------------------------------------------------------------------


def test_deadline_context_key_has_exactly_one_home() -> None:
    """伞的载体键只准有一个家（``deadline.py``）——禁第二处字面量/第二个定义。

    判据形态：全树 ``plugins/`` 里"赋值形态"的 ``DEADLINE_CONTEXT_KEY = "..."`` 恰一枚。
    """
    root = Path(cp.__file__).resolve().parents[1]
    homes: list[str] = []
    pattern = re.compile(r"^DEADLINE_CONTEXT_KEY\s*=\s*[\"']")
    for py in root.rglob("*.py"):
        for line in py.read_text(encoding="utf-8", errors="replace").splitlines():
            if pattern.match(line.strip()):
                homes.append(py.relative_to(root).as_posix())
    assert homes == ["domains/chat_reply/runtime/deadline.py"], homes


def test_voice_enricher_hands_the_request_deadline_to_the_central_request() -> None:
    """TTS 调用侧接线锁：hook 派发中央第三形时必须把 ``result.deadline_monotonic`` 交出去。

    这条是"合成段在伞外"那半缺陷的正向锁——摘掉 hook 里那一枚 context 赋值，
    内层腿就再也读不到伞（``test_nested_invoke_inherits_*`` 只管机制，本条只管接线）。
    反向不误伤腿同批：结果没带 deadline ⇒ **不加那一枚键**，派发形状逐字节保持现状。
    """
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        BotDecision,
        CapabilityResult,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.media import voice_enricher as ve

    captured: list[CapabilityRequest] = []

    class _StubInvoker:
        def invoke(self, request: CapabilityRequest) -> InvocationResult:
            captured.append(request)
            return InvocationResult(
                capability_id=request.capability_id,
                status=InvocationStatus.FAILED,
                detail="stub：只验派发形状，成败另件已锁",
            )

    class _Cfg:
        bot_tts_voice_hook_enabled = True

    def _result(deadline: float | None) -> CapabilityResult:
        return CapabilityResult(
            request_id="req-hook-1",
            capability_id="bot.chat",
            kind="text",
            body="潮汐今天很安静。",
            deadline_monotonic=deadline,
        )

    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:111",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="111",
        plain_text="今天天气不错",
        message_id="m-1",
        debug_id="dbg-1",
    )
    decision = BotDecision(
        request_id="req-hook-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )
    enrich = ve.build_voice_enricher(_Cfg())

    with (
        mock.patch.object(ve, "default_invoker", lambda: _StubInvoker()),
        # 门链第 2 道（该不该配）与派发形状无关，钉成真：三道门全过才会派中央。
        mock.patch.object(ve, "should_voice_reply", lambda *args, **kwargs: True),
    ):
        with_deadline = _result(_REAL_TIME.monotonic() + 60.0)
        enrich(message, decision, with_deadline)
        enrich(message, decision, _result(None))

    assert len(captured) == 2, "门链没过 ⇒ 一次都没派中央，本锁量不到东西"
    key = dl.DEADLINE_CONTEXT_KEY
    assert captured[0].context.get(key) == pytest.approx(
        float(with_deadline.deadline_monotonic or 0.0)
    ), captured[0].context
    assert key not in captured[1].context, captured[1].context
    assert set(captured[1].context) == {"config", "dub"}, captured[1].context


# ---------------------------------------------------------------------------
# ⑤ 量具自证（注毒腿：把修法退回旧形态，判据必须改口）
# ---------------------------------------------------------------------------


def test_ruler_self_check_reverting_to_full_copies_would_change_the_reading() -> None:
    """把 ``_leg_budget_seconds`` 退回「每腿一份满预算」⇒ 读数必须变回 [20, 20]。

    这条证明 ① 那枚判据量的确实是**除法本身**，而不是 handler 恰好跑多快；
    同一形状也顺手钉住"地板"那型假修法——伞耗尽时若退回地板，执行体会被派出去，
    与 ``test_exhausted_umbrella_stops_before_dispatch_*`` 的 ``invocations == []`` 相反。
    """
    sc = wire(
        handler=_boom("primary", 8.0),
        fallback_chain=("vlm_candidate", HONEST[0]),
        fallbacks=(("vlm_candidate", _ok("vlm_candidate", 2.0)),),
    )
    with mock.patch.object(
        cp, "_leg_budget_seconds", lambda umbrella, attempt, legs: float(attempt)
    ):
        result = sc.invoke(_request(deadline=sc.executor.clock() + 20.0))
    assert sc.executor.offered == [ATTEMPT_CAP, ATTEMPT_CAP], sc.executor.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status


def test_ruler_self_check_the_binding_is_what_lets_nested_legs_see_the_umbrella() -> None:
    """删掉 ``_bind_umbrella`` 那一绑 ⇒ 嵌套腿读到的伞必须全是 ``None``（旧缺陷回潮形状）。

    与 ``test_nested_invoke_inherits_the_same_umbrella_*`` 成对：那条断"做对＝三次都
    读到同一枚"，这条断"做错＝一次都读不到"——contextvar 不跨线程自动传播，
    所以这一绑是承重件而不是装饰。
    """
    sc = wire(threaded=True, clock_start=9_000.0, inner_handler=_ok("inner", 0.0))

    def outer(request: CapabilityRequest) -> InvocationResult:
        for _ in range(3):
            sc.executor.seen_umbrella.append(cp._UMBRELLA.get())
            sc.invoker.invoke(_request(INNER_CID, deadline=None))
        return InvocationResult(
            capability_id=request.capability_id, status=InvocationStatus.OK, data={}
        )

    sc.invoker.handlers.register(CID, outer)
    with mock.patch.object(cp, "_bind_umbrella", lambda task, umbrella: task):  # 注毒：不绑
        sc.invoke(_request(deadline=sc.executor.clock() + 30.0))
    assert sc.executor.seen_umbrella == [None, None, None], sc.executor.seen_umbrella
