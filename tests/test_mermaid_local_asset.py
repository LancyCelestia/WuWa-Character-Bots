"""mermaid.min.js 本地供给：fetch 工具 + render_backends 传输层拦截离线单测。

覆盖（素材本地化 F1）：
- fetch 工具：落盘+sidecar、幂等跳过、--force 重拉、拒收（截断/HTML 错误页）
  不落盘、sidecar 缺失零网络自愈；
- render_backends：mermaid HTML + 本地素材在 → page.route 注册且 fulfill
  本地字节；本地缺失 → 不注册放行网络；非 mermaid HTML → 不注册；
  收货校验三道闸。
全部离线（下载用 checker 替身），真身文件不参与断言（走 tmp_path）。

PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_mermaid_local_asset.py \
    --basetemp="$TEMP/mmd" -p no:cacheprovider
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.output import render_backends as rb
from scripts import fetch_mermaid_js

MERMAID_HTML = (
    "<html><head><script src="
    "'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js'>"
    "</script></head><body><div class='card'>x</div></body></html>"
)
PLAIN_HTML = "<html><body><div class='card'>x</div></body></html>"


def _fake_min_js(seed: str = "mermaid-bundle") -> bytes:
    """合格假身：过三道闸（>512KB、非 < 开头、前部含 mermaid 标记）。"""
    return b"/*! mermaid v11.17.2 */\n" + seed.encode() * (600 * 1024)


@pytest.fixture()
def asset_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把素材目录解析钉到 tmp_path，隔离真身（render_backends 与工具双侧）。"""
    d = tmp_path / "assets" / "mermaid"
    monkeypatch.setattr(rb, "mermaid_asset_dir", lambda: d)
    monkeypatch.setattr(fetch_mermaid_js, "mermaid_asset_dir", lambda: d)
    return d


# ==================== 收货校验 ====================
def test_validate_accepts_realistic_bundle() -> None:
    assert rb.validate_mermaid_asset_bytes(_fake_min_js()) == _fake_min_js()


def test_validate_rejects_truncated_html_and_markerless() -> None:
    assert rb.validate_mermaid_asset_bytes(b"") is None
    assert rb.validate_mermaid_asset_bytes(b"<html>gateway timeout</html>") is None
    assert rb.validate_mermaid_asset_bytes(b"short") is None
    big_no_marker = (b"x" * (600 * 1024))
    assert rb.validate_mermaid_asset_bytes(big_no_marker) is None


def test_mermaid_asset_bytes_missing_or_corrupt_is_none(
    asset_dir: Path,
) -> None:
    assert rb._mermaid_asset_bytes() is None  # 缺失
    asset_dir.mkdir(parents=True)
    (asset_dir / "mermaid.min.js").write_bytes(b"<html>err</html>")
    assert rb._mermaid_asset_bytes() is None  # 损坏拒收


# ==================== render_backends：route 拦截 ====================
class _FakeRoute:
    def __init__(self) -> None:
        self.fulfilled: dict | None = None

    def fulfill(self, **kwargs: object) -> None:
        self.fulfilled = kwargs


class _FakePage:
    """记录 route 注册；按需支持/禁用 route 方法（模拟假 page 测试替身）。"""

    def __init__(self, *, with_route: bool = True) -> None:
        self.routes: list[tuple[str, object]] = []
        if with_route:
            self.route = self._route

    def _route(self, pattern: str, handler: object) -> None:
        self.routes.append((pattern, handler))

    def set_default_timeout(self, ms: int) -> None:
        pass

    def set_content(self, html: str, wait_until: str) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector(self, selector: str):
        element = SimpleNamespace()
        element.screenshot = lambda **kwargs: b"png-bytes"
        return element

    def close(self) -> None:
        pass


def _make_backend() -> rb.PlaywrightRenderBackend:
    backend = rb.PlaywrightRenderBackend.__new__(rb.PlaywrightRenderBackend)
    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1
    return backend


def _render(backend: rb.PlaywrightRenderBackend, page: _FakePage, html: str) -> bytes | None:
    browser = SimpleNamespace(new_page=lambda **kw: page, is_connected=lambda: True)
    handle = SimpleNamespace(
        start=lambda: SimpleNamespace(chromium=SimpleNamespace(launch=lambda: browser))
    )
    backend._sync_playwright = lambda: handle
    return backend.render_card(
        {"html": html, "viewport": {"width": 10, "height": 10}, "wait_ms": 0}
    )


def test_route_registered_and_fulfills_local_bytes(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True)
    payload = _fake_min_js()
    (asset_dir / "mermaid.min.js").write_bytes(payload)
    backend = _make_backend()
    page = _FakePage()
    assert _render(backend, page, MERMAID_HTML) == b"png-bytes"
    assert len(page.routes) == 1
    pattern, handler = page.routes[0]
    assert pattern == rb._MERMAID_CDN_URL
    fake_route = _FakeRoute()
    handler(fake_route)
    assert fake_route.fulfilled is not None
    assert fake_route.fulfilled["body"] == payload
    assert fake_route.fulfilled["content_type"] == "text/javascript"
    assert fake_route.fulfilled["status"] == 200


def test_route_not_registered_when_local_asset_missing(asset_dir: Path) -> None:
    backend = _make_backend()
    page = _FakePage()
    assert _render(backend, page, MERMAID_HTML) == b"png-bytes"  # 优雅降级照常出图
    assert page.routes == []  # 放行走网络


def test_route_not_registered_for_non_mermaid_html(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True)
    (asset_dir / "mermaid.min.js").write_bytes(_fake_min_js())
    backend = _make_backend()
    page = _FakePage()
    assert _render(backend, page, PLAIN_HTML) == b"png-bytes"
    assert page.routes == []


def test_page_without_route_attribute_never_crashes(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True)
    (asset_dir / "mermaid.min.js").write_bytes(_fake_min_js())
    backend = _make_backend()
    page = _FakePage(with_route=False)  # 无 route 的假 page 替身
    assert _render(backend, page, MERMAID_HTML) == b"png-bytes"


# ==================== fetch 工具 ====================
def test_fetch_downloads_writes_asset_and_sidecar(asset_dir: Path) -> None:
    payload = _fake_min_js()
    target, digest, skipped = fetch_mermaid_js.fetch(
        "https://cdn.example/mermaid.min.js",
        asset_dir,
        checker=lambda url: payload,
    )
    assert skipped is False
    assert target == asset_dir / "mermaid.min.js"
    assert target.read_bytes() == payload
    expected = hashlib.sha256(payload).hexdigest()
    assert digest == expected
    sidecar = asset_dir / "mermaid.min.js.sha256"
    assert sidecar.read_text("ascii").split()[0] == expected


def test_fetch_idempotent_skips_when_ready(asset_dir: Path) -> None:
    calls: list[str] = []

    def checker(url: str) -> bytes:
        calls.append(url)
        return _fake_min_js()

    first = fetch_mermaid_js.fetch("u", asset_dir, checker=checker)
    assert first[2] is False and len(calls) == 1
    second = fetch_mermaid_js.fetch("u", asset_dir, checker=checker)
    assert second[2] is True  # skipped
    assert len(calls) == 1  # 幂等：零网络


def test_fetch_force_redownloads(asset_dir: Path) -> None:
    calls: list[str] = []
    payload = _fake_min_js()

    def checker(url: str) -> bytes:
        calls.append(url)
        return payload

    fetch_mermaid_js.fetch("u", asset_dir, checker=checker)
    forced = fetch_mermaid_js.fetch("u", asset_dir, checker=checker, force=True)
    assert forced[2] is False and len(calls) == 2
    assert (asset_dir / "mermaid.min.js").read_bytes() == payload


def test_fetch_rejects_and_writes_nothing(asset_dir: Path) -> None:
    for bad in (b"short", b"<html>rate limited</html>"):
        target, digest, skipped = fetch_mermaid_js.fetch(
            "u", asset_dir, checker=lambda url, _b=bad: _b
        )
        assert (target, digest, skipped) == (None, None, False)
    assert not asset_dir.exists() or not (asset_dir / "mermaid.min.js").exists()
    assert not (asset_dir / "mermaid.min.js.sha256").exists()


def test_fetch_self_heals_missing_sidecar_without_network(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True)
    payload = _fake_min_js()
    (asset_dir / "mermaid.min.js").write_bytes(payload)

    def boom(url: str) -> bytes:
        raise AssertionError("sidecar 自愈不得触网")

    result = fetch_mermaid_js.fetch("u", asset_dir, checker=boom)
    assert result[2] is True
    expected = hashlib.sha256(payload).hexdigest()
    assert (
        asset_dir / "mermaid.min.js.sha256"
    ).read_text("ascii").split()[0] == expected


def test_main_check_and_exit_codes(
    asset_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fetch_mermaid_js.main(["--check"]) == 1  # 未就绪
    fetch_mermaid_js.fetch("u", asset_dir, checker=lambda url: _fake_min_js())
    assert fetch_mermaid_js.main(["--check"]) == 0
