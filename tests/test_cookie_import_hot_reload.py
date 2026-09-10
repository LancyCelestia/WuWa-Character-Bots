"""cookie import 热生效回归：cookies 文件 mtime 变化必须让解析注册表下一条消息重建（handoff C-7）。

`/bot cookie import` 的语义是写 platform_cookies.txt 后不重启即生效；
生效机制 = _cached_content_parser_registry 按 (路径, mtime, 平台, 代理) 单槽缓存。
本文件锁定：mtime 未变命中缓存；文件被改写（import）后重建且携带新 cookie provider。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime import (
    _CONTENT_REGISTRY_CACHE,
    _cached_content_parser_registry,
)
from plugins.bot_unified_runtime.sources import parsers as parsers_module


@pytest.fixture(autouse=True)
def _isolated_registry_cache():
    _CONTENT_REGISTRY_CACHE.clear()
    yield
    _CONTENT_REGISTRY_CACHE.clear()


def _fake_config(cookies_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_cookies_file=str(cookies_path),
        bot_content_parse_platforms=["bilibili"],
        bot_download_proxy="",
    )


def _stub_builders(monkeypatch):
    calls = {"build": 0, "provider": 0}

    def fake_build(platforms, cookie_provider=None, proxy="", playwright_backend=None):
        calls["build"] += 1
        return {"registry": object(), "parsers": object(), "call": calls["build"]}

    def fake_provider(config):
        calls["provider"] += 1
        return f"provider#{calls['provider']}"

    monkeypatch.setattr(parsers_module, "build_content_parser_registry", fake_build)
    monkeypatch.setattr(parsers_module, "build_cookie_provider", fake_provider)
    return calls


def test_registry_rebuilt_after_cookies_file_changes(tmp_path, monkeypatch) -> None:
    cookies_file = tmp_path / "platform_cookies.txt"
    cookies_file.write_text(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\told\n", encoding="utf-8")
    calls = _stub_builders(monkeypatch)
    config = _fake_config(cookies_file)

    first = _cached_content_parser_registry(config, playwright_backend=None)
    assert calls["build"] == 1
    # 同一 mtime 下重复调用（每条消息都会走这里）：命中缓存，不重建。
    assert _cached_content_parser_registry(config, playwright_backend=None) is first
    assert calls["build"] == 1

    # 模拟 /bot cookie import：改写 cookies 文件 → mtime 变化 → 下一条消息重建。
    stamped = cookies_file.stat().st_mtime_ns + 2_000_000
    os.utime(cookies_file, ns=(stamped, stamped))
    second = _cached_content_parser_registry(config, playwright_backend=None)
    assert second is not first
    assert calls["build"] == 2
    assert calls["provider"] == 2

    # 重建后再次稳定命中。
    assert _cached_content_parser_registry(config, playwright_backend=None) is second
    assert calls["build"] == 2


def test_registry_rebuilt_when_platform_scope_changes(tmp_path, monkeypatch) -> None:
    cookies_file = tmp_path / "platform_cookies.txt"
    cookies_file.write_text(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\told\n", encoding="utf-8")
    calls = _stub_builders(monkeypatch)
    config = _fake_config(cookies_file)

    _cached_content_parser_registry(config, playwright_backend=None)
    config.bot_content_parse_platforms = ["bilibili", "weibo"]
    _cached_content_parser_registry(config, playwright_backend=None)
    assert calls["build"] == 2


def test_missing_cookies_file_yields_stable_cache_key(tmp_path, monkeypatch) -> None:
    calls = _stub_builders(monkeypatch)
    config = _fake_config(tmp_path / "not_exists.txt")

    first = _cached_content_parser_registry(config, playwright_backend=None)
    assert _cached_content_parser_registry(config, playwright_backend=None) is first
    assert calls["build"] == 1
