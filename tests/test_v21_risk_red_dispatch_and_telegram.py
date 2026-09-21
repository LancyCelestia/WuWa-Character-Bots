"""V2.1 A5 取证席 RED 测试——风险域 5/6（双 Dispatcher 未接管 + 平台副作用直连、TG catch-all）。

- 风险 5（**2026-09-18 V21-DISPATCH-001 已收口，三条转正为回归锁**）：
  统一出站面已接生产——``control_plane/dispatcher.py`` 新增
  ``OutboundSideEffectExecutor``（OutboundIntent → 准入复验 → 许可租约线性化 →
  Transport 固定映射 → ``bot.call_api`` 通道本体）+ ``build_interaction_dispatcher``
  门面装配；``decision/dispatcher.py`` dispatch 为阶段 1 真实派发周期（shadow
  绝不发送语义保持）；回戳（__init__.py poke handler）与贴表情
  （domains/meme/reactions/engine.py）改走 Poke/Reaction 服务门面，
  平台副作用方法名字面量只允许存在于登记表数据与两份 dispatcher 定义模块。
- 风险 6（2026-09-17 A13 修复席已修，转正为回归测试）：scripts/telegram_resilience.py
  poll 阶段不再把 401 鉴权失败/409 实例冲突当作"网络暂不可用"无限退避——
  命中 401/403/409 时记定向告警并停止本层轮询（不上抛，保住 2026-09-16
  的启动链不逃逸不变量）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

import plugins.bot_unified_runtime as _pkg
from plugins.bot_unified_runtime.domains.core.decision.dispatcher import (
    Dispatcher as DecisionDispatcher,
)
from scripts.telegram_resilience import (
    build_resilient_telegram_adapter,
    is_transient_telegram_error,
)

_PKG_ROOT = Path(_pkg.__file__).parent


# ==================== 风险 5：双 Dispatcher 接管（已收口回归锁） ====================


def test_risk5_dispatcher_facade_wired_into_production() -> None:
    """回归锁（V21-DISPATCH-001）：门面四名至少其一被生产包真实导入接线
    （__init__.py → PokeInteractionService；reactions engine → ReactionService）。"""
    facade_names = {"Dispatcher", "PokeInteractionService", "ReactionService", "MemeService"}
    wired: list[str] = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        if rel in {"control_plane/dispatcher.py", "decision/dispatcher.py"}:
            continue  # 定义模块自身不计
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[-1] == "dispatcher":
                    names = {alias.name for alias in node.names}
                    if names & facade_names:
                        wired.append(rel)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[-1] == "dispatcher":
                        wired.append(rel)
    assert wired, (
        "两份 Dispatcher 在生产包内无任何 import——统一派发未接管；"
        "平台副作用（group_poke/friend_poke/set_msg_emoji_like）仍走处理器直连 call_api"
    )


def test_risk5_decision_dispatcher_can_dispatch() -> None:
    """回归锁（V21-DISPATCH-001）：dispatch(plan, ctx) 为阶段 1 真实派发周期，
    任意鸭子协议对象（裸 object()）也能走完决策周期显式返回（shadow 语境
    绝不发送语义保持），不再恒抛 NotImplementedError。"""

    async def _run() -> None:
        dispatcher = DecisionDispatcher(engine=object(), pipeline=object())
        await dispatcher.dispatch(object(), object())  # 期望：阶段 1+ 真实派发，不抛

    asyncio.run(_run())


def test_risk5_platform_side_effects_route_through_dispatcher() -> None:
    """回归锁（V21-DISPATCH-001）：等价 rg "call_api\\\\(|set_msg_emoji_like|friend_poke|group_poke"
    的 AST 精确版——副作用动作名字面量只允许出现在两份 dispatcher 定义模块与
    出站登记表数据内，其余生产码一律 RED（直连回戳/贴表情已收编统一出站面）。"""
    side_effects = {
        "group_poke",
        "friend_poke",
        "set_msg_emoji_like",
        "set_message_reaction",
    }
    offenders: list[str] = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        if rel in {"control_plane/dispatcher.py", "decision/dispatcher.py"}:
            continue  # 门面/骨架定义模块自身放行
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "call_api"):
                continue
            consts = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            consts += [
                kw.value.value
                for kw in node.keywords
                if kw.arg == "action"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ]
            offenders += [f"{rel}:{value}" for value in consts if value in side_effects]
    assert offenders == [], f"平台副作用 call_api 直连（未经 dispatcher 门面）：{offenders}"


# ==================== 风险 6：TG 轮询 catch-all 误归类 ====================


class _NetworkError(Exception):
    """模拟 nonebot.adapters.telegram.exception.NetworkError（带 .msg 属性）。"""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.msg = msg


class _UpstreamAdapter:
    """上游 TG 适配器替身：poll 抛给定异常（401/409 被上游包装为 NetworkError）。"""

    exc: Exception | None = None

    async def poll(self, bot: object) -> object:
        assert self.exc is not None
        raise self.exc


class _Logger:
    def warning(self, *args: object, **kwargs: object) -> None: ...
    def info(self, *args: object, **kwargs: object) -> None: ...


class _LoopEscape(BaseException):
    """从重试循环中确定性逃逸的哨兵（真实实现 sleep=asyncio.sleep）。"""


@pytest.mark.parametrize("code", ["401", "409"])
def test_risk6_poll_does_not_retry_auth_conflict(code: str) -> None:
    """转正回归（V21-risk-6 修复，2026-09-17）：poll 阶段 401/403/409 不被
    退避吞掉——不再进入重试 sleep，异常也不沿启动链逃逸（优雅停轮询）。"""
    async def _sleep(_delay: float) -> None:
        raise _LoopEscape

    adapter = build_resilient_telegram_adapter(
        _UpstreamAdapter,
        network_error=_NetworkError,
        logger=_Logger(),
        sleep=_sleep,
        retryable=is_transient_telegram_error,
    )
    instance = adapter()
    instance.exc = _NetworkError(
        f"Received unexpected {code}: authentication/conflict failure"
    )
    # 修复后语义：非临时故障（401/409）按合同停止本层重试并定向告警，
    # 绝不进退避 sleep（进 sleep 即 _LoopEscape 逃逸判红），也不上抛。
    assert asyncio.run(instance.poll(None)) is None
