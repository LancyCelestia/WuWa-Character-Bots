"""审查 L-04 回归：mermaid 截图后端与主渲染后端单例合一。

背景：bridge._get_mermaid_backend 历史上经 build_render_backend("auto")
自建第二个 PlaywrightRenderBackend 常驻实例，与 __init__.py 装配态的主
渲染后端并存（审查 L-04：内存翻倍）。修复：build_render_backend 工厂按
「先到先得」登记进程级共享 playwright 实例（装配先于任何渲染调用，先到
者即主后端），bridge 优先复用同一实例；登记为空（渲染开关关闭/单测隔离
环境）才回退自建兜底，既有自愈钩子只施加于自建实例。

覆盖：
- 单例性：装配（build_render_backend）后 _get_mermaid_backend() 与主后端
  同一实例；登记先到先得；
- 缓存优先：已显式注入/已探测的 _MERMAID_BACKEND 不被登记覆盖（既有
  mermaid 测试桩语义保持）；
- 兜底：登记为空时自建并保留自愈钩子（共享实例不被改写方法）；形态
  不符的登记（防御）回退自建；不可用时缓存 False 返回 None；
- 冒烟：render_mermaid_png 经共享后端出图 / 失败降级 None（文本兜底
  契约零破坏）。

全离线：build_render_backend 只 import playwright、不启动浏览器。
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.render import render_backends as rb
from plugins.bot_unified_runtime.domains.render.card_render import bridge


class _StubPlaywrightBackend:
    """playwright 形态的后端替身（available + 可调用 render_card，零浏览器）。"""

    name = "playwright"
    available = True

    def __init__(self, result: bytes | None = b"PNG") -> None:
        self.result = result
        self.calls = 0
        self._local = threading.local()
        self._close_thread_browser = self._close  # 钩子包装目标（兜底路径）

    def _close(self) -> None:
        self.close_calls = getattr(self, "close_calls", 0) + 1

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls += 1
        return self.result


class _NullBackend:
    name = "null"
    available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        return None


@pytest.fixture()
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离共享登记与 bridge 单例缓存，用后还原（不污染同进程其他测试）。"""
    monkeypatch.setattr(rb, "_SHARED_RENDER_BACKEND", None)
    monkeypatch.setattr(bridge, "_MERMAID_BACKEND", None)


# ==================== 单例性 ====================
def test_mermaid_backend_reuses_assembly_shared_instance(isolated: None) -> None:
    """装配态构建的后端与 _get_mermaid_backend() 返回同一实例（L-04 核心）。"""
    backend = rb.build_render_backend("auto")  # 模拟 __init__.py 装配
    assert rb.get_shared_render_backend() is backend
    assert bridge._get_mermaid_backend() is backend


def test_shared_registry_first_wins(isolated: None) -> None:
    """先到先得：二次构建不覆盖登记，mermaid 始终取装配态实例。"""
    first = rb.build_render_backend("auto")
    rb.build_render_backend("auto")
    assert rb.get_shared_render_backend() is first
    assert bridge._get_mermaid_backend() is first


def test_cached_backend_beats_registry(isolated: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存优先：已显式注入的 _MERMAID_BACKEND 不被登记覆盖（桩语义保持）。"""
    own = _StubPlaywrightBackend()
    shared = _StubPlaywrightBackend()
    rb._register_shared_render_backend(shared)
    monkeypatch.setattr(bridge, "_MERMAID_BACKEND", own)
    assert bridge._get_mermaid_backend() is own


# ==================== 登记（render_backends 侧） ====================
def test_null_backend_not_registered(isolated: None) -> None:
    """Null 后端（未知名/不可用）不登记，避免 bridge 误持不可用实例。"""
    backend = rb.build_render_backend("definitely-not-a-backend")
    assert getattr(backend, "name", "") == "null"
    assert rb.get_shared_render_backend() is None


# ==================== 兜底（登记为空时保持既有行为） ====================
def test_fallback_builds_own_with_self_heal_hook(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登记为空：回退自建（auto），自愈钩子仍施加于自建实例。"""
    stub = _StubPlaywrightBackend()
    built: list[str] = []

    def _fake_build(name: str = "") -> Any:
        built.append(name)
        return stub

    monkeypatch.setattr(bridge, "build_render_backend", _fake_build)
    assert bridge._get_mermaid_backend() is stub
    assert built == ["auto"]
    assert stub._close_thread_browser is not stub._close  # 已被钩子包装
    # 包装语义：先退出 ctx（本替身无 ctx），再走原关闭路径。
    stub._close_thread_browser()
    assert stub.close_calls == 1


def test_shared_instance_not_mutated_by_hook(isolated: None) -> None:
    """共享实例是主后端：bridge 不得改写其方法（钩子只属于自建路径）。"""
    stub = _StubPlaywrightBackend()
    rb._register_shared_render_backend(stub)
    close_fn = stub._close_thread_browser
    assert bridge._get_mermaid_backend() is stub
    assert stub._close_thread_browser is close_fn


def test_unusable_shared_falls_back_to_build(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登记形态不符（防御，正常构造不会发生）：回退自建 playwright 后端。"""
    rb._register_shared_render_backend(_NullBackend())
    stub = _StubPlaywrightBackend()
    monkeypatch.setattr(bridge, "build_render_backend", lambda name="": stub)
    assert bridge._get_mermaid_backend() is stub


def test_unavailable_backend_caches_false(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """playwright 不可用：返回 None 且缓存 False（不重复探测，既有语义）。"""
    monkeypatch.setattr(bridge, "build_render_backend", lambda name="": _NullBackend())
    assert bridge._get_mermaid_backend() is None
    assert bridge._MERMAID_BACKEND is False


# ==================== 渲染冒烟（文本兜底契约） ====================
def test_render_mermaid_png_via_shared_backend(isolated: None) -> None:
    """共享后端出图：render_mermaid_png 正常返回 PNG 字节。"""
    stub = _StubPlaywrightBackend(b"PNG")
    rb._register_shared_render_backend(stub)
    assert bridge.render_mermaid_png("graph TD\nA --> B") == b"PNG"
    assert stub.calls == 1


def test_render_mermaid_png_failure_degrades_to_none(isolated: None) -> None:
    """共享后端失败：重试一次后仍失败 → None（调用方降级纯文本，契约不变）。"""
    stub = _StubPlaywrightBackend(None)
    rb._register_shared_render_backend(stub)
    assert bridge.render_mermaid_png("graph TD\nA --> B") is None
    assert stub.calls == 2  # 快速失败路径：紧接重试一次（既有 I-1 语义）
