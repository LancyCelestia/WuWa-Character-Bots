"""中央降级链「预算活性」锁（SEAT-F-BAKE，2026-09-22）。

一句话——**主 attempt 把声明的预算烧完之后才抛异常，降级腿仍必须拿到属于它自己
那份完整的单次尝试预算**。旧写法把 ``descriptor.timeout_seconds`` 在同一处又当成
「整次调用的总 deadline」去减 elapsed，再用 ``max(1.0, …)`` 兜住不让它变成负数，
于是真实故障形态（上游跑到接近超时才抛）下降级腿固定只分到 1 秒——一次真实的
VLM/HTTP 尝试不可能在 1 秒内完成 ⇒ 降级链**在册而不可达**（AGENTS #49
「在册但未执法」同族：存在性糊过活性判据）。

⚠ 本件锁的是**判据**，不是某个数字：把地板从 1.0 抬到任意大数都过不了
``test_fallback_budget_does_not_depend_on_how_long_the_primary_took``——
那条要求「降级腿的预算与主 attempt 跑了多久无关」，这正是本次根修的语义。

全离线、零 sleep、零墙钟（机器负载翻脸也判得一样）：

* 时钟＝测试自带的可推进假钟，经 ``capability_protocols`` 模块内的 ``time`` **名字**
  替入（替身只换 ``monotonic``，其余属性原样转发真模块）——爆炸半径＝这一个模块，
  绝不去改 stdlib ``time``（那是全进程共享的，会毒化同会话别的门）；
* 线程池＝``VirtualExecutor`` 替身：把「X 秒内没回来就 TimeoutError」这条真池判据
  搬到虚拟钟上（X vs handler 自报的虚拟时长），并把**每次尝试真正拿到的预算 X**
  记进 ``offered`` 供断言直读——判据不猜、不抄，直接量。

纪律：一切用例走私有 invoker，**绝不往 ``default_invoker()`` 注册任何东西**
（单例，塞探针会让集合比对类门当场假红——``test_central_dispatch_matrix.py`` 同款教训）。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest import mock

import pytest

from plugins.bot_unified_runtime.runtime import capability_protocols as cp
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    HONEST_DEGRADE_PREFIX,
    PRESENTATION_DATA_KEY,
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

#: 被测描述符声明的**单次尝试**上限（本件唯一口径，与中央硬顶无关）。
ATTEMPT_CAP = 20.0
#: 降级腿一次诚实尝试需要的虚拟时长（真实 VLM 候选调用的量级，远大于 1 秒地板）。
HONEST_FALLBACK_SECONDS = 6.0
CID = "media.test.budget"
_REAL_TIME = time

#: 本席默认链形：一枚注册降级腿 + honest_degrade 终态（＝在册 media.vision.anime_ip 的形状）。
DEFAULT_CHAIN: tuple[str, ...] = (
    "vlm_candidate",
    HONEST_DEGRADE_PREFIX + "反搜无候选时不凭空猜 IP",
)


# ---------------------------------------------------------------------------
# 确定性装置：假钟 + 模块名字替身 + 虚拟执行体
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
    """``capability_protocols`` 里 ``time`` 这个名字的替身。

    只换 ``monotonic``（invoker 算 started/elapsed/remaining 用的就是它），其余属性
    一律转发真模块——本模块将来用到 ``time.sleep``/``time.time`` 也不会被悄悄改语义。
    """

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._real = _REAL_TIME

    def monotonic(self) -> float:
        return self._clock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


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
            # 真池语义：到点没回来即 TimeoutError，工作线程继续跑到自然结束、结果弃用。
            raise concurrent.futures.TimeoutError()
        if self._error is not None:
            raise self._error
        assert self._value is not None, "既没超时、又无异常，却也没有结果体"
        return self._value

    def cancel(self) -> bool:
        return False  # 真池：已经跑完的取消不掉


@dataclass
class VirtualExecutor:
    """共享工作线程池替身：同步执行 + 虚拟超时判据 + 把递来的预算原样记账。

    ``invocations[i]`` / ``offered[i]`` / ``durations[i]`` 三表同序＝第 i 次尝试的
    身份、真正拿到的预算、烧掉的虚拟时长。
    """

    clock: FakeClock
    invocations: list[str] = field(default_factory=list)
    offered: list[float | None] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)

    def submit(self, fn: Callable[[], InvocationResult]) -> VirtualFuture:
        before = self.clock()
        value: InvocationResult | None = None
        error: BaseException | None = None
        try:
            value = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样交回，判据在 result() 落
            error = exc
        self.durations.append(self.clock() - before)
        return VirtualFuture(self, self.durations[-1], value, error)

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class AuditLines:
    """终态审计行计数器（「每次终态恰一行」硬约束的度量面）。"""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def __call__(self, record: Any) -> None:
        self.records.append(record)


class Rig:
    """一整套确定性装置：时钟 + 记账执行体 + 审计计数。handler 与断言共用同一份。"""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.executor = VirtualExecutor(clock=self.clock)
        self.audit = AuditLines()

    def note(self, label: str) -> None:
        """handler 自报身份（谁被真调了、按序）。"""
        self.executor.invocations.append(label)

    @property
    def invocations(self) -> list[str]:
        return self.executor.invocations

    @property
    def offered(self) -> list[float | None]:
        return self.executor.offered


# ---------------------------------------------------------------------------
# 假 handler（全部经 Rig 烧虚拟钟，零真实耗时）
# ---------------------------------------------------------------------------


def slow_success(
    rig: Rig,
    label: str,
    burn: float,
    data: dict[str, Any] | None = None,
    *,
    error_after: BaseException | None = None,
) -> Callable[..., InvocationResult]:
    """跑 burn 秒后诚实成功的 handler（``error_after`` 用于「慢且抛」的故障形态）。"""

    def _handler(request: CapabilityRequest) -> InvocationResult:
        rig.note(label)
        rig.clock.burn(burn)
        if error_after is not None:
            raise error_after
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.OK,
            data=dict(data or {}),
        )

    return _handler


def slow_failure(
    rig: Rig, label: str, burn: float, error: BaseException | None = None
) -> Callable[..., InvocationResult]:
    """跑 burn 秒后抛异常的 handler＝真实故障形态（上游跑到接近超时才炸）。"""

    return slow_success(
        rig, label, burn, error_after=error or RuntimeError("上游跑到接近超时才抛")
    )


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    invoker: CapabilityInvoker
    rig: Rig

    @contextlib.contextmanager
    def _central_shell(self) -> Iterator[None]:
        """把假钟/虚拟池只替入**这一次调用**的窗口。

        刻意不在装配期 patch：中央壳是模块级名字，装配期打补丁会让后建的场景把先建
        场景的钟顶掉（本席首版就这么翻过一车——``timeout`` 终态被读成 ``ok``，因为
        invoker 读的是别人的钟、handler 烧的是自己的钟）。
        """
        with mock.patch.object(
            cp, "time", TimeNamespace(self.rig.clock)
        ), mock.patch.object(cp, "_get_capability_executor", lambda: self.rig.executor):
            yield

    def run(self, capability_id: str = CID, **kwargs: Any) -> InvocationResult:
        with self._central_shell():
            return self.invoker.invoke(_request(capability_id, **kwargs))


def _request(capability_id: str = CID, **kwargs: Any) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        payload=kwargs.pop("payload", None) or {},
        principal="tester",
        roles=kwargs.pop("roles", ("user",)),
        context=kwargs.pop("context", None) or {},
        request_id="req-budget-1",
        session_key="group_111_222",
    )


def wire(
    *,
    rig: Rig | None = None,
    capability_id: str = CID,
    timeout_seconds: float = ATTEMPT_CAP,
    handler: Callable[..., InvocationResult] | None = None,
    fallback_chain: tuple[str, ...] = DEFAULT_CHAIN,
    fallbacks: tuple[tuple[str, Callable[..., InvocationResult]], ...] = (),
    limits: dict[str, int] | None = None,
    limit_fields: tuple[tuple[str, str], ...] = (),
) -> Scenario:
    """私有 invoker（注册面自建），并绑定一份确定性装置 ``rig``。

    假钟/虚拟池的实际替入点在 ``Scenario._central_shell``（只管这一次调用）。
    ``rig`` 必须由调用方与 handler 共用同一份，否则「handler 烧的钟」与「invoker
    读的钟」是两套，判据就成了摆设。
    """
    rig = rig or Rig()
    invoker = CapabilityInvoker(
        registry=CapabilityRegistry(),
        handlers=HandlerRegistry(),
        fallbacks=FallbackRegistry(),
        probes=HealthProbeRegistry(),
    )
    invoker.registry.register(
        CapabilityDescriptor(
            capability_id=capability_id,
            family=CapabilityFamily.MEDIA,
            title="预算活性被测能力",
            input_protocol="test.v1{in}",
            output_protocol="test.v1{out}",
            timeout_seconds=timeout_seconds,
            limits=limits or {},
            limit_fields=limit_fields,
            fallback_chain=fallback_chain,
        )
    )
    if handler is not None:
        invoker.handlers.register(capability_id, handler)
    for name, fb in fallbacks:
        invoker.fallbacks.register(capability_id, name, fb)
    invoker.audit_hooks.register(rig.audit)
    return Scenario(invoker=invoker, rig=rig)


def primary_burns_budget_then_raises(*, primary_burn: float = 19.0) -> Scenario:
    """主 attempt 烧掉声明预算的 95%（19.0s / 20.0s）才抛，降级腿诚实需要 6.0s。"""
    rig = Rig()
    return wire(
        rig=rig,
        handler=slow_failure(rig, "primary", primary_burn),
        fallbacks=(
            (
                "vlm_candidate",
                slow_success(
                    rig,
                    "vlm_candidate",
                    HONEST_FALLBACK_SECONDS,
                    data={"hits": [{"title": "候选"}]},
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# ① 主缺陷复现 + 语义正锁
# ---------------------------------------------------------------------------


def test_fallback_still_gets_a_full_attempt_when_primary_burns_the_budget() -> None:
    """主 attempt 用满预算后抛 ⇒ 降级腿必须真跑到、且拿到整份单次预算。

    旧写法下本用例必红（任一即红）：offered[1]==1.0（地板）< 诚实时长 6.0
    ⇒ 虚拟超时 ⇒ 终态 failed，用户拿不到降级回复（FALLBACK_OK 缺席）。
    """
    sc = primary_burns_budget_then_raises()
    result = sc.run()

    # 活性面：降级腿被走到，用户真拿到降级回复（携结果体，不空手也不冒充）。
    assert sc.rig.invocations == ["primary", "vlm_candidate"], sc.rig.invocations
    assert result.status is InvocationStatus.FALLBACK_OK, result.status
    assert result.via == "fallback[0]:vlm_candidate", result.via
    assert result.data["hits"] == [{"title": "候选"}], result.data
    assert result.attempts == 2, result.attempts

    # 判据面：两次尝试同一口径＝描述符声明的单次上限（不是「总预算减剩余」，
    # 也不是任何魔法地板）。
    assert sc.rig.offered == [ATTEMPT_CAP, ATTEMPT_CAP], sc.rig.offered

    # 确定性自证：耗时口径完全来自假钟（19.0 + 6.0），与墙钟无关。
    assert result.elapsed_ms == 25_000, result.elapsed_ms


@pytest.mark.parametrize("primary_burn", [0.0, 5.0, 14.0, 19.0, 19.99])
def test_fallback_budget_does_not_depend_on_how_long_the_primary_took(
    primary_burn: float,
) -> None:
    """语义锁（杀「把地板数调大」这种假修法）：降级腿预算须为主 attempt 耗时的常量函数。

    旧写法 remaining = max(floor, cap - elapsed) 随 elapsed 变脸；本锁只认
    「每次尝试一份完整单次预算」，故地板从 1.0 抬到任意大数也照样红。
    """
    sc = primary_burns_budget_then_raises(primary_burn=primary_burn)
    result = sc.run()
    assert sc.rig.offered == [ATTEMPT_CAP, ATTEMPT_CAP], (primary_burn, sc.rig.offered)
    assert result.status is InvocationStatus.FALLBACK_OK, (primary_burn, result.status)


def test_second_fallback_leg_is_not_starved_by_the_first() -> None:
    """链上第二腿同样不许被地板饿死：第一腿慢失败后，第二腿仍该拿到整份预算。"""
    rig = Rig()
    sc = wire(
        rig=rig,
        handler=slow_failure(rig, "primary", 19.0),
        fallback_chain=("leg_one", "leg_two", HONEST_DEGRADE_PREFIX + "两条腿都不成"),
        fallbacks=(
            ("leg_one", slow_failure(rig, "leg_one", 19.0)),
            ("leg_two", slow_success(rig, "leg_two", HONEST_FALLBACK_SECONDS, data={"hits": []})),
        ),
    )
    result = sc.run()
    assert rig.invocations == ["primary", "leg_one", "leg_two"], rig.invocations
    assert rig.offered == [ATTEMPT_CAP] * 3, rig.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status
    assert result.via == "fallback[1]:leg_two", result.via
    assert result.attempts == 3, result.attempts


def test_attempt_budget_is_a_real_budget_not_an_unbounded_gift() -> None:
    """反空转锁：预算是真会咬人的——降级腿超出单次上限仍须按超时记账。

    防「为了修不可达干脆给无限预算」这种把判据从一端甩到另一端的假修。
    诚实账（既有语义）保持不变：有降级项崩 ⇒ 终态 failed 且点名降级链失败数。
    """
    rig = Rig()
    sc = wire(
        rig=rig,
        handler=slow_failure(rig, "primary", 1.0),
        fallbacks=(("vlm_candidate", slow_success(rig, "vlm_candidate", ATTEMPT_CAP + 5.0)),),
    )
    result = sc.run()
    assert rig.offered == [ATTEMPT_CAP, ATTEMPT_CAP], rig.offered
    assert result.status is InvocationStatus.FAILED, result.status
    assert "降级链 1 项失败" in result.detail, result.detail


def test_central_clamp_still_bounds_every_attempt() -> None:
    """硬顶不许动：``_MAX_TIMEOUT_SECONDS`` 仍是每次尝试（含降级腿）的钳制域。

    故意声明越界值（``validate_registry`` 会判它越界），只为验运行期钳制没被本修
    悄悄放宽成「降级腿可以吃更多」。
    """
    clamp = float(cp._MAX_TIMEOUT_SECONDS)
    rig = Rig()
    sc = wire(
        rig=rig,
        timeout_seconds=clamp + 300.0,
        handler=slow_failure(rig, "primary", clamp - 1.0),
        fallbacks=(
            ("vlm_candidate", slow_success(rig, "vlm_candidate", HONEST_FALLBACK_SECONDS)),
        ),
    )
    result = sc.run()
    assert rig.offered == [clamp, clamp], rig.offered
    assert result.status is InvocationStatus.FALLBACK_OK, result.status


# ---------------------------------------------------------------------------
# ② 不许被顺手改坏的既有语义
# ---------------------------------------------------------------------------


def test_honest_degrade_terminal_survives_a_slow_primary() -> None:
    """链里只有 honest_degrade（无注册降级项）＝在册绝大多数能力的形状：
    主 attempt 慢抛后仍须给诚实降级 degraded，且不为此多起一次尝试。"""
    rig = Rig()
    sc = wire(
        rig=rig,
        capability_id="media.test.honest",
        handler=slow_failure(rig, "primary", 19.0),
        fallback_chain=(HONEST_DEGRADE_PREFIX + "无独立引擎，诚实无结果",),
    )
    result = sc.run("media.test.honest")
    assert result.status is InvocationStatus.DEGRADED, result.status
    assert "诚实降级" in result.detail, result.detail
    assert rig.invocations == ["primary"], rig.invocations
    assert rig.offered == [ATTEMPT_CAP], rig.offered  # 没多起一次尝试


def test_primary_timeout_is_still_a_terminal_state_and_never_raises() -> None:
    """既有语义（不许顺手改成抛）：主 attempt 挂死到点 ⇒ 落 timeout 终态。"""
    rig = Rig()
    sc = wire(rig=rig, handler=slow_success(rig, "primary_hangs", ATTEMPT_CAP + 1.0))
    result = sc.run()
    assert result.status is InvocationStatus.TIMEOUT, result.status
    assert result.via == "invoker", result.via
    assert rig.invocations == ["primary_hangs"], rig.invocations


@pytest.mark.xfail(
    reason=(
        "R-FBAKE-1（待用户裁，见 SEAT-F-BAKE §9）：主 attempt **超时**（区别于抛异常）"
        "根本不进降级链，registered 降级腿对「挂死到超时」这一整类故障仍不可达。"
        "修它要同时动 test_v21_s10_protocols::test_timeout_reported_honestly 锁住的"
        "既有判据（超时直落终态），不属本席授权面。本用例期望红＝现状钉桩，非放宽任何门。"
    ),
    strict=False,
)
def test_registered_fallback_should_reach_a_hanging_primary_too() -> None:
    """同一族缺口的第二半：挂死到超时也该有降级可用（今日不成立，故期望红）。"""
    rig = Rig()
    sc = wire(
        rig=rig,
        handler=slow_success(rig, "primary_hangs", ATTEMPT_CAP + 1.0),
        fallbacks=(("vlm_candidate", slow_success(rig, "vlm_candidate", 1.0, data={"hits": []})),),
    )
    result = sc.run()
    assert rig.invocations == ["primary_hangs", "vlm_candidate"], rig.invocations
    assert result.status is InvocationStatus.FALLBACK_OK, result.status


def test_every_terminal_state_writes_exactly_one_audit_line() -> None:
    """「每次终态恰一行审计」硬约束（8 种终态各一行：不漏行、不双行）。

    本修动了 ``_run_fallbacks`` 的返回路径，正是最容易写出「降级腿 emit 一次 +
    终态再 emit 一次」双行的地方，故这枚锁与本修同件同生死。
    """
    cases: list[tuple[str, Scenario, InvocationStatus, dict[str, Any]]] = []

    rig = Rig()
    cases.append(("ok", wire(rig=rig, handler=slow_success(rig, "p", 0.5)), InvocationStatus.OK, {}))
    rig = Rig()
    cases.append(
        (
            "fallback_ok",
            wire(
                rig=rig,
                handler=slow_failure(rig, "p", 19.0),
                fallbacks=(("vlm_candidate", slow_success(rig, "f", 2.0)),),
            ),
            InvocationStatus.FALLBACK_OK,
            {},
        )
    )
    rig = Rig()
    cases.append(
        (
            "degraded",
            wire(rig=rig, handler=slow_failure(rig, "p", 1.0)),
            InvocationStatus.DEGRADED,
            {},
        )
    )
    rig = Rig()
    cases.append(
        (
            "failed_chain_exhausted",
            wire(
                rig=rig,
                handler=slow_failure(rig, "p", 1.0),
                fallbacks=(("vlm_candidate", slow_failure(rig, "f", 0.5)),),
            ),
            InvocationStatus.FAILED,
            {},
        )
    )
    rig = Rig()
    cases.append(
        (
            "timeout",
            wire(rig=rig, handler=slow_success(rig, "p", ATTEMPT_CAP + 1.0)),
            InvocationStatus.TIMEOUT,
            {},
        )
    )
    rig = Rig()
    cases.append(
        (
            "denied",
            wire(rig=rig, handler=slow_success(rig, "p", 0.0)),
            InvocationStatus.DENIED,
            {"roles": ("blocked",)},
        )
    )
    cases.append(
        ("unavailable", wire(rig=Rig(), handler=None), InvocationStatus.UNAVAILABLE, {})
    )
    rig = Rig()
    cases.append(
        (
            "limit_exceeded",
            wire(
                rig=rig,
                handler=slow_success(rig, "p", 0.0),
                limits={"max_chars": 3},
                limit_fields=(("query_text", "max_chars"),),
            ),
            InvocationStatus.LIMIT_EXCEEDED,
            {"payload": {"query_text": "abcd"}},
        )
    )

    assert len(cases) == 8, "终态样本被裁＝本锁会静默空跑"
    for shape, sc, expected, request_kwargs in cases:
        before = len(sc.rig.audit.records)
        result = sc.run(**request_kwargs)
        assert result.status is expected, (shape, result.status, result.detail)
        assert len(sc.rig.audit.records) - before == 1, (
            shape,
            "终态审计行数≠1（漏行＝中央跑了不留痕；双行＝一次调用写两笔账）",
        )
        # 审计行还要能与一条消息对上（关联键从请求带到记录）。
        assert sc.rig.audit.records[-1].request_id == "req-budget-1", shape


def test_fallback_leg_result_body_is_not_blended_with_the_failed_primary() -> None:
    """降级承接的载荷只能来自那一腿本身（防「预算改道」顺手把两次尝试的结果叠一起）。"""
    rig = Rig()
    sc = wire(
        rig=rig,
        handler=slow_failure(rig, "primary", 19.0),
        fallbacks=(
            (
                "vlm_candidate",
                slow_success(
                    rig,
                    "vlm_candidate",
                    2.0,
                    data={PRESENTATION_DATA_KEY: {"kind": "text", "body": "候选说明"}},
                ),
            ),
        ),
    )
    result = sc.run()
    assert result.status is InvocationStatus.FALLBACK_OK, result.status
    assert result.data[PRESENTATION_DATA_KEY]["body"] == "候选说明"
    assert set(result.data) == {PRESENTATION_DATA_KEY}, result.data
