"""S-HEALTH 席（2026-09-21 统一波 R2）：中央能力健康度在生产的第一个读者。

R2 的原始事实：``runtime/capability_protocols.py`` 里 ``HealthProbeRegistry`` 登记了九枚
探针（含现役 TTS 的 ``_PROBE_TTS``），但 ``CapabilityInvoker.health()`` / ``compute_health()``
全树**零生产调用点** ⇒ 中央登记了探针却没人看，等于没接。本席把它接进 ``/bot status``。

钉死四件事：
1. **活性**：``/bot status`` 真的逐个问了中央 invoker，且拿到的**值**进了输出
   （不读必红；读了但把值丢了也必红）；
2. **fail-open**：取不到 invoker / 探针抛异常 / 中央无可报项 ⇒ 诚实降级；命令不炸，
   绝不把"没读到"写成任何正面判定；
3. **不假绿**：任何非 ``available`` 组合下输出不得出现「全部可用 / 正常 / 健康」，
   并配「全 available ⇒ 必须出现全部可用」的对照锁（防锁退化成永真）；
4. **零行为回归**：新行是**追加**（既有语音行退到倒数第二且字节不变），且新行
   **不引入网络探测**、**不在 import/装配期触发**探测。

全离线：中央替身用 monkeypatch（先例 ``tests/test_media_orchestration_wiring.py:204``）；
真探针用例额外把 ``socket.create_connection`` 桩成"碰一下就炸"，零真实网络。
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _capability_health_line,
    build_status_result,
)
from plugins.bot_unified_runtime.runtime import capability_protocols
from plugins.bot_unified_runtime.runtime.capability_protocols import CapabilityHealth

_ECHO_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "echo.py"
)

#: 替身世界里的在册能力 id（与真实注册表解耦，计数才可钉死）。
_FAKE_IDS = ("alpha.one", "alpha.two")
#: 任何"读到了但判定为不绿"的分支里都不许出现的正面字样。
_GREEN_WORDS = ("全部可用", "正常", "健康")
#: 既有语音健康行在缺省配置下的逐字节现状（本席只追加、不得改它）。
_VOICE_LINE_DEFAULT = "语音：disabled，engine=not_probed"


class _FakeInvoker:
    """只实现本席用到的 ``health()``，并把"被问了哪些 id"如实记账。"""

    def __init__(self, states: dict[str, CapabilityHealth | None]) -> None:
        self._states = states
        self.asks: list[str] = []

    def health(
        self, capability_id: str, config: Any = None
    ) -> tuple[Any, CapabilityHealth] | None:
        self.asks.append(capability_id)
        state = self._states[capability_id]
        if state is None:
            return None
        descriptor = SimpleNamespace(capability_id=capability_id, health_probe="fake")
        return descriptor, state


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    ids: tuple[str, ...] = _FAKE_IDS,
    invoker: Any = None,
) -> Any:
    """把替身挂上中央唯一入口（``default_invoker``）并钉死在册 id 清单。"""
    target = invoker or _FakeInvoker(
        {cid: CapabilityHealth.AVAILABLE for cid in ids}
    )
    monkeypatch.setattr(
        capability_protocols, "registered_capability_ids", lambda: frozenset(ids)
    )
    monkeypatch.setattr(capability_protocols, "default_invoker", lambda: target)
    return target


def _status_lines(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    result = build_status_result(request_id="r", actor_roles=["admin", "user"])
    return str(result.body).split("\n")


# ---------------------------------------------------------------------------
# ① 活性：真读中央面，且值进输出
# ---------------------------------------------------------------------------
def test_status_appends_central_health_line_as_pure_addition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新行只能是追加：既有末行（语音健康行）文案与位置逐字节不动。"""
    _wire(
        monkeypatch,
        invoker=_FakeInvoker(
            {
                "alpha.one": CapabilityHealth.AVAILABLE,
                "alpha.two": CapabilityHealth.DEGRADED,
            }
        ),
    )
    lines = _status_lines(monkeypatch)
    assert lines[-2] == _VOICE_LINE_DEFAULT, "既有语音行被改动＝行为回归"
    assert lines[-1].startswith("中央能力态：probed=2，"), lines[-1]
    assert "available=1" in lines[-1] and "degraded=1" in lines[-1]


def test_line_asks_central_for_every_registered_id_and_carries_the_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正向活性锁：逐个问到位（不读必红），中央给的值原样进输出（丢值也必红）。"""
    invoker = _wire(
        monkeypatch,
        invoker=_FakeInvoker(
            {
                "alpha.one": CapabilityHealth.AVAILABLE,
                "alpha.two": CapabilityHealth.NOT_CONFIGURED,
            }
        ),
    )
    line = _capability_health_line(Config())
    assert invoker.asks == sorted(_FAKE_IDS), f"中央未被逐个问到位：{invoker.asks}"
    assert "probed=2" in line
    assert "alpha.two:not_configured" in line, f"中央返回值没有进输出：{line}"
    assert "verdict=部分不可用" in line


def test_real_registry_values_reach_the_line() -> None:
    """真身一致性：不加替身时，行内点名必须等于中央实跑结论（本部署缺省态）。"""
    line = _capability_health_line(Config())
    probed = _field(line, "probed")
    assert probed is not None and int(probed) > 0, f"真注册表下探到 0 项：{line}"

    invoker = capability_protocols.default_invoker()
    config = Config()
    real: dict[str, str] = {}
    for capability_id in sorted(capability_protocols.registered_capability_ids()):
        probed_pair = invoker.health(capability_id, config)
        if probed_pair is None or not getattr(probed_pair[0], "health_probe", ""):
            continue
        real[capability_id] = probed_pair[1].value
    assert real, "中央探针覆盖为空＝本锁前提失效"
    assert int(probed or 0) == len(real), "行内计数与中央探针覆盖面不符"
    non_green = sorted(cid for cid, state in real.items() if state != "available")
    assert non_green, "中央实态全绿＝点名断言无从校验（改本用例前先核实）"
    for capability_id in non_green[: echo._HEALTH_ATTENTION_PREVIEW]:
        assert f"{capability_id}:{real[capability_id]}" in line, (
            f"{capability_id} 的真值没进输出：{line}"
        )


def test_descriptor_without_probe_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只统计**探针结论**：无 health_probe 的 descriptor 只是静态缺省，不算"探测过"。"""

    class _StaticOnlyInvoker:
        def __init__(self) -> None:
            self.asks: list[str] = []

        def health(
            self, capability_id: str, config: Any = None
        ) -> tuple[Any, CapabilityHealth]:
            self.asks.append(capability_id)
            descriptor = SimpleNamespace(capability_id=capability_id, health_probe="")
            return descriptor, CapabilityHealth.AVAILABLE

    invoker = _wire(monkeypatch, invoker=_StaticOnlyInvoker())
    line = _capability_health_line(Config())
    assert invoker.asks == sorted(_FAKE_IDS)
    assert "probe=no_probe_registered" in line, f"静态缺省被冒充成探测结论：{line}"
    assert not any(word in line for word in _GREEN_WORDS)


# ---------------------------------------------------------------------------
# ② fail-open：取不到 / 抛异常 / 无可报项，都不许炸、都不许给出正面判定
# ---------------------------------------------------------------------------
def test_failopen_when_default_invoker_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise RuntimeError("中央 invoker 装配失败")

    monkeypatch.setattr(capability_protocols, "default_invoker", _boom)
    line = _capability_health_line(Config())
    assert "probe=unavailable" in line and "reason=RuntimeError" in line, line
    assert "不作判定" in line
    assert not any(word in line for word in _GREEN_WORDS)


def test_status_command_still_succeeds_when_central_face_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令整体不得因中央面坏掉而失败（status 本身没失败，只是这一行诚实降级）。"""

    def _boom() -> Any:
        raise RuntimeError("中央 invoker 不可得")

    monkeypatch.setattr(capability_protocols, "default_invoker", _boom)
    lines = _status_lines(monkeypatch)
    assert lines[-1].startswith("中央能力态：probe=unavailable")
    assert lines[-2] == _VOICE_LINE_DEFAULT


def _raise_value_error(capability_id: str, config: Any = None) -> Any:
    raise ValueError("探针自身炸了")


def _raise_os_error(capability_id: str, config: Any = None) -> Any:
    raise OSError("中央注册表读不动")


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(_raise_value_error, id="value-error"),
        pytest.param(_raise_os_error, id="os-error"),
    ],
)
def test_failopen_when_probe_raises(
    monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    class _ThrowingInvoker:
        def health(self, capability_id: str, config: Any = None) -> Any:
            return failure(capability_id, config)

    _wire(monkeypatch, invoker=_ThrowingInvoker())
    line = _capability_health_line(Config())
    assert "probe=unavailable" in line, line
    assert not any(word in line for word in _GREEN_WORDS)


def test_failopen_when_central_reports_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``health()`` 返回 None（不在册）⇒ 诚实"无从判定"，不是"全绿"。"""
    invoker = _wire(
        monkeypatch, invoker=_FakeInvoker({cid: None for cid in _FAKE_IDS})
    )
    line = _capability_health_line(Config())
    assert invoker.asks == sorted(_FAKE_IDS)
    assert "probe=no_probe_registered" in line
    assert not any(word in line for word in _GREEN_WORDS)


# ---------------------------------------------------------------------------
# ③ 不假绿（含反向对照，防锁退化成永真）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "state",
    [
        CapabilityHealth.DEGRADED,
        CapabilityHealth.DISABLED,
        CapabilityHealth.NOT_CONFIGURED,
        CapabilityHealth.UNKNOWN,
    ],
)
def test_non_available_state_never_reads_as_green(
    monkeypatch: pytest.MonkeyPatch, state: CapabilityHealth
) -> None:
    _wire(
        monkeypatch,
        invoker=_FakeInvoker(
            {"alpha.one": CapabilityHealth.AVAILABLE, "alpha.two": state}
        ),
    )
    line = _capability_health_line(Config())
    for word in _GREEN_WORDS:
        assert word not in line, f"{state.value} 态下输出仍出现「{word}」＝假绿：{line}"
    assert "verdict=部分不可用" in line
    assert f"alpha.two:{state.value}" in line


def test_all_available_is_the_only_green_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对照锁：全 available 时**必须**给出全部可用——否则上一条锁会因"永不写结论"而假绿。"""
    _wire(monkeypatch)
    line = _capability_health_line(Config())
    assert "verdict=全部可用" in line and "待关注=无" in line
    assert "available=2" in line


def test_attention_list_is_capped_not_endless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """点名定额：超出上限折叠为「等 N 项」（防 status 被撑爆）。"""
    many = tuple(
        f"zeta.{index}" for index in range(echo._HEALTH_ATTENTION_PREVIEW + 3)
    )
    _wire(
        monkeypatch,
        ids=many,
        invoker=_FakeInvoker(
            {cid: CapabilityHealth.NOT_CONFIGURED for cid in many}
        ),
    )
    line = _capability_health_line(Config())
    assert f"等{len(many)}项" in line
    assert line.count("zeta.") == echo._HEALTH_ATTENTION_PREVIEW


# ---------------------------------------------------------------------------
# ④ 惰性 + 零新探测（本席不得把 status 变成网络探测点）
# ---------------------------------------------------------------------------
def test_new_line_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """真探针下也不得触网：中央探针是配置/文件面（``_probe_tts`` docstring 明写零网络）。"""

    def _no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("中央健康面聚合里出现了真实网络连接")

    monkeypatch.setattr(socket, "create_connection", _no_network)
    line = _capability_health_line(Config())
    assert "probed=" in line, line


def test_default_invoker_is_never_touched_at_module_level() -> None:
    """惰性结构锁：``default_invoker`` 的取用点必须**在函数体内部**。

    写在模块顶层会把探测提前到 import 期（装配期慢启动 + 探测时序失控）。
    判据是 AST 而非文本：把调用挪到模块级就红，注释里提到这个名字不会假红。
    """
    tree = ast.parse(_ECHO_SOURCE.read_text(encoding="utf-8"))

    def _invoker_calls(node: ast.AST) -> list[ast.Call]:
        found: list[ast.Call] = []
        for item in ast.walk(node):
            if not isinstance(item, ast.Call):
                continue
            func = item.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "default_invoker":
                found.append(item)
        return found

    module_level: list[ast.AST] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        module_level.extend(ast.walk(stmt))
    offenders = [call for node in module_level for call in _invoker_calls(node)]
    assert not offenders, f"import 期就会触发中央探测：{offenders}"

    # 自证覆盖面：函数体内那一处确实存在（否则上面的断言是空转）。
    hosts = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _invoker_calls(node)
    ]
    assert hosts == ["_capability_health_line"], hosts


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _field(line: str, key: str) -> str | None:
    """从「前缀：k=v，k2=v2」形态的摘要行里取 v（取不到返回 None）。"""
    marker = f"{key}="
    start = line.find(marker)
    if start < 0:
        return None
    rest = line[start + len(marker) :]
    return rest.split("，", 1)[0].strip()
