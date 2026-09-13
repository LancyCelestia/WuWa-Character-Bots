"""Phase-2 渲染开关接线回归（perf-optimization-plan §三.1；缺省=字节级现状）。

四组锁定：
1. 缺省等价现状——两键（``BOT_RENDER_MAX_CONCURRENCY`` /
   ``BOT_RENDER_WAIT_BUDGET_MS``）不配置时：解析值 = 串行 1 / 预算不启用，
   render_card 的 page 操作序列与旧实现逐项一致（同参同一序列）。
2. 预算键生效——env/driver config 注入后，payload 未显式携带的渲染走
   预算路径（就绪信号替代固定 sleep）；非法值（空/0/负/非数字）回落旧路径；
   payload 显式值恒优先于全局缺省。
3. 并发键生效——env 注入后 build_render_backend 把 max_concurrency 透传给
   PlaywrightRenderBackend；并发 2 时信号量确实放行两个槽位。
4. 解析链优先级——driver config（nonebot）→ 进程 env → 缺省，高一级存在
   即压住低一级（与 decision.resolve_decision_mode 同源模式）。

中毒修复面零触碰：本文件不改动 _get_browser/_close_thread_browser 语义
（C-1 回归门在 test_browser_ctx_leak.py）。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.output import render_backends
from plugins.bot_unified_runtime.output.render_backends import (
    _RENDER_READY_SIGNALS,
    PlaywrightRenderBackend,
    resolve_render_max_concurrency,
    resolve_render_wait_budget_ms,
)

_HTML = "<html><body><div class='card'>ok</div></body></html>"
_IMG_COMPLETE_SUBSTRING = "every(img => img.complete)"
_CONCURRENCY_ENV = "BOT_RENDER_MAX_CONCURRENCY"
_BUDGET_ENV = "BOT_RENDER_WAIT_BUDGET_MS"


@pytest.fixture(autouse=True)
def _clean_render_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离环境：本模块所有用例默认两键未配置（缺省=字节级现状的前提）。"""
    monkeypatch.delenv(_CONCURRENCY_ENV, raising=False)
    monkeypatch.delenv(_BUDGET_ENV, raising=False)


# ==================== 替身：记录 render_card 全部 page 级操作 ====================
class _ShotElement:
    def __init__(self, ops: list[tuple[Any, ...]]) -> None:
        self._ops = ops

    def screenshot(self, **kwargs: Any) -> bytes:
        self._ops.append(("element_screenshot", kwargs))
        return b"png-bytes"


class _ScriptedPage:
    def __init__(self, ops: list[tuple[Any, ...]]) -> None:
        self.ops = ops
        self.closed = False

    def set_default_timeout(self, ms: int) -> None:
        self.ops.append(("set_default_timeout", ms))

    def set_content(self, html: str, wait_until: str = "load") -> None:
        self.ops.append(("set_content", html, wait_until))

    def wait_for_function(self, expression: str, timeout: int = 0) -> None:
        self.ops.append(("wff", expression, timeout))

    def wait_for_timeout(self, ms: int) -> None:
        self.ops.append(("wait_for_timeout", ms))

    def query_selector(self, selector: str) -> _ShotElement | None:
        self.ops.append(("query_selector", selector))
        if selector == ".card":
            return _ShotElement(self.ops)
        return None

    def screenshot(self, **kwargs: Any) -> bytes:
        self.ops.append(("page_screenshot", kwargs))
        return b"png-bytes"

    def close(self) -> None:
        self.closed = True
        self.ops.append(("close",))


class _SinglePageBrowser:
    def __init__(self, page: _ScriptedPage) -> None:
        self._page = page

    def new_page(self, **kwargs: Any) -> _ScriptedPage:
        self._page.ops.append(("new_page", kwargs))
        return self._page


def _make_backend(
    page: _ScriptedPage, monkeypatch: pytest.MonkeyPatch
) -> PlaywrightRenderBackend:
    """离线替身后端：_get_browser 换成单页浏览器，playwright 可用性强制开启。"""
    backend = PlaywrightRenderBackend(
        max_concurrency=resolve_render_max_concurrency()
    )
    backend.available = True
    if backend._sync_playwright is None:
        backend._sync_playwright = object()  # 不会被真正调用
    monkeypatch.setattr(backend, "_get_browser", lambda: _SinglePageBrowser(page))
    return backend


_IMG_COMPLETE_EXPR = "Array.from(document.images).every(img => img.complete)"


def _legacy_expected_ops(viewport: dict[str, int], wait_ms: int) -> list[tuple[Any, ...]]:
    """旧固定等待路径的完整 page 操作序列（与既有实现同参同序）。"""
    return [
        ("new_page", {"viewport": viewport, "device_scale_factor": 2}),
        ("set_default_timeout", 8000),
        ("set_content", _HTML, "networkidle"),
        ("wff", _IMG_COMPLETE_EXPR, 8000),
        ("wait_for_timeout", wait_ms),
        ("query_selector", ".card"),
        ("element_screenshot", {"type": "png", "omit_background": True}),
        ("close",),
    ]


# ==================== ① 缺省等价现状 ====================
def test_unconfigured_resolvers_return_status_quo() -> None:
    assert resolve_render_max_concurrency() == 1
    assert resolve_render_wait_budget_ms() is None


def test_unconfigured_render_keeps_legacy_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops: list[tuple[Any, ...]] = []
    page = _ScriptedPage(ops)
    backend = _make_backend(page, monkeypatch)
    payload = {"html": _HTML, "viewport": {"width": 320, "height": 240}}

    assert backend.render_card(dict(payload)) == b"png-bytes"

    expected = _legacy_expected_ops({"width": 320, "height": 240}, 1500)
    # img-complete 表达式用子串宽松比对（与实现内联字符串等价即可）。
    assert len(ops) == len(expected)
    assert ops[:3] == expected[:3]
    assert ops[3][0] == "wff" and ops[3][2] == 8000
    assert _IMG_COMPLETE_SUBSTRING in ops[3][1]
    assert ops[4:] == expected[4:]
    assert page.closed is True


# ==================== ② 预算键生效 / 失效回落 / payload 优先 ====================
def test_env_wait_budget_activates_budget_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_BUDGET_ENV, "1500")
    ops: list[tuple[Any, ...]] = []
    page = _ScriptedPage(ops)
    backend = _make_backend(page, monkeypatch)

    assert backend.render_card({"html": _HTML, "wait_ms": 1500}) == b"png-bytes"

    wff_ops = [op for op in ops if op[0] == "wff"]
    # img-complete（既有等待）之后依次是 3 个预算就绪信号，预算全额可用。
    assert [op[1] for op in wff_ops[1:]] == list(_RENDER_READY_SIGNALS)
    assert all(op[2] == 1500 for op in wff_ops[1:])
    # 预算模式下不再发生固定 sleep。
    assert all(op[0] != "wait_for_timeout" for op in ops)


@pytest.mark.parametrize("bad", ["0", "", "abc", "-5", "12.5x"])
def test_env_wait_budget_disabled_values_keep_legacy_path(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv(_BUDGET_ENV, bad)
    assert resolve_render_wait_budget_ms() is None

    ops: list[tuple[Any, ...]] = []
    page = _ScriptedPage(ops)
    backend = _make_backend(page, monkeypatch)

    assert backend.render_card({"html": _HTML}) == b"png-bytes"

    waits = [op for op in ops if op[0] == "wait_for_timeout"]
    assert waits == [("wait_for_timeout", 1500)]
    wff_ops = [op for op in ops if op[0] == "wff"]
    assert len(wff_ops) == 1  # 仅既有 img-complete 等待，无预算信号


def test_payload_wait_budget_ms_overrides_env_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_BUDGET_ENV, "1500")
    ops: list[tuple[Any, ...]] = []
    page = _ScriptedPage(ops)
    backend = _make_backend(page, monkeypatch)

    # payload 显式 800 压住 env 1500：信号预算按 800 计。
    assert backend.render_card({"html": _HTML, "wait_budget_ms": 800}) == b"png-bytes"
    wff_ops = [op for op in ops if op[0] == "wff"]
    assert [op[1] for op in wff_ops[1:]] == list(_RENDER_READY_SIGNALS)
    assert all(op[2] == 800 for op in wff_ops[1:])

    # payload 显式 0（预算为零=立即截断）也压住 env：无固定 sleep、无信号等待。
    ops_zero: list[tuple[Any, ...]] = []
    page_zero = _ScriptedPage(ops_zero)
    backend_zero = _make_backend(page_zero, monkeypatch)
    assert backend_zero.render_card({"html": _HTML, "wait_budget_ms": 0}) == b"png-bytes"
    assert all(op[0] != "wait_for_timeout" for op in ops_zero)
    assert len([op for op in ops_zero if op[0] == "wff"]) == 1


# ==================== ③ 并发键生效 ====================
def test_env_max_concurrency_feeds_build_render_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int] = []

    class _SpyBackend:
        def __init__(self, *, max_concurrency: int = 1) -> None:
            captured.append(max_concurrency)
            self.available = False  # 走 Null 兜底即可，只看装配参数。

    monkeypatch.setattr(render_backends, "PlaywrightRenderBackend", _SpyBackend)

    monkeypatch.setenv(_CONCURRENCY_ENV, "2")
    render_backends.build_render_backend("playwright")
    assert captured == [2]

    monkeypatch.delenv(_CONCURRENCY_ENV)
    render_backends.build_render_backend("playwright")
    assert captured == [2, 1]

    for bad in ("abc", "0", "-3"):
        monkeypatch.setenv(_CONCURRENCY_ENV, bad)
        render_backends.build_render_backend("playwright")
    assert captured == [2, 1, 1, 1, 1]


def test_env_max_concurrency_admits_parallel_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CONCURRENCY_ENV, "2")
    backend = PlaywrightRenderBackend(
        max_concurrency=resolve_render_max_concurrency()
    )

    assert backend._max_concurrency == 2
    # 两个槽位都可非阻塞获取（=允许两卡跨线程并行）；过释放必须暴露。
    assert backend._lock.acquire(blocking=False) is True
    try:
        assert backend._lock.acquire(blocking=False) is True
    finally:
        backend._lock.release()
        backend._lock.release()
    with pytest.raises(ValueError):
        backend._lock.release()


# ==================== ④ 解析链优先级：driver config → env → 缺省 ====================
class _FakeDriverConfig:
    pass


def _install_fake_nonebot(
    monkeypatch: pytest.MonkeyPatch, **attrs: Any
) -> _FakeDriverConfig:
    config = _FakeDriverConfig()
    for key, value in attrs.items():
        setattr(config, key, value)
    fake = SimpleNamespace(
        get_driver=lambda: SimpleNamespace(config=config)
    )
    monkeypatch.setitem(sys.modules, "nonebot", fake)
    return config


def test_driver_config_precedes_env_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # driver config（小写字段名，translate_env_keys 形态）压住 env。
    _install_fake_nonebot(
        monkeypatch,
        bot_render_max_concurrency="3",
        bot_render_wait_budget_ms="1200",
    )
    monkeypatch.setenv(_CONCURRENCY_ENV, "9")
    monkeypatch.setenv(_BUDGET_ENV, "9000")
    assert resolve_render_max_concurrency() == 3
    assert resolve_render_wait_budget_ms() == 1200


def test_driver_config_raw_bot_key_form_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # .env 原样键（BOT_* 大写）也必须被识别（nonebot driver 保存原始键名）。
    _install_fake_nonebot(
        monkeypatch,
        BOT_RENDER_MAX_CONCURRENCY="4",
        BOT_RENDER_WAIT_BUDGET_MS="777",
    )
    assert resolve_render_max_concurrency() == 4
    assert resolve_render_wait_budget_ms() == 777


def test_env_used_when_driver_config_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 无 driver（裸脚本/单测）：env 兜底生效；driver 存在但无该字段亦然。
    _install_fake_nonebot(monkeypatch)  # 空配置对象
    monkeypatch.setenv(_CONCURRENCY_ENV, "2")
    monkeypatch.setenv(_BUDGET_ENV, "800")
    assert resolve_render_max_concurrency() == 2
    assert resolve_render_wait_budget_ms() == 800


def test_garbage_at_every_level_falls_back_to_status_quo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nonebot(
        monkeypatch,
        bot_render_max_concurrency="not-a-number",
        bot_render_wait_budget_ms="0",
    )
    monkeypatch.setenv(_CONCURRENCY_ENV, "??")
    monkeypatch.setenv(_BUDGET_ENV, "-1")
    assert resolve_render_max_concurrency() == 1
    assert resolve_render_wait_budget_ms() is None
