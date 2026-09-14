"""实战油猴脚本取图/取流算法移植回归（全部离线：无网络、无真实 sleep）。

三件移植：
- xhs 视频 media.stream 全键扫描按 (height, videoBitrate) 取最高档
  （移植自 xhs-download-helper.user-v1.5.1.js L252-278/L293-308）
- 推特 pbs.twimg.com 直链归一「原格式 + name=orig」
  （移植自 x-download-helper.user-v1.4.0.js L170-194）
- http_util GET 429 Retry-After 有界重试 + 其余 4xx 快速失败
  （移植自 x-download-helper.user-v1.4.0.js L615-695）
"""

from __future__ import annotations

import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from plugins.bot_unified_runtime.sources.parsers import http_util, platforms_generic
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

# ---------- ① xhs 视频 stream 质量排序 ----------


def test_xhs_stream_picks_highest_over_fixed_key_order():
    """多键多档：EF7 的 1080p 高码率必须胜出，av1 的 720p 不再顶替 1080p。"""
    stream = {
        "av1": [
            {
                "masterUrl": "https://sns-video-hw.xhscdn.com/720p.mp4",
                "height": 720,
                "videoBitrate": 900000,
            }
        ],
        "h264": [
            {
                "masterUrl": "https://sns-video-hw.xhscdn.com/480p.mp4",
                "height": 480,
                "videoBitrate": 500000,
            },
            {
                "masterUrl": "https://sns-video-hw.xhscdn.com/1080p.mp4",
                "height": 1080,
                "videoBitrate": 2000000,
            },
        ],
        "EF7": [
            {
                "masterUrl": "https://sns-video-hw.xhscdn.com/1080p-high.mp4",
                "height": 1080,
                "videoBitrate": 4000000,
            }
        ],
    }
    assert platforms_generic._xhs_best_stream_url(stream) == (
        "https://sns-video-hw.xhscdn.com/1080p-high.mp4"
    )


def test_xhs_stream_height_tie_breaks_by_bitrate_and_backup_fallback():
    """同高按下 videoBitrate 决胜；masterUrl 缺失时取 backupUrls[0]。"""
    stream = {
        "h264": [
            {
                "height": 1080,
                "videoBitrate": 2000000,
                "backupUrls": ["https://cdn.xhscdn.com/backup-1080p.mp4"],
            },
            {
                "masterUrl": "https://cdn.xhscdn.com/master-1080p-high.mp4",
                "height": 1080,
                "videoBitrate": 4000000,
            },
        ]
    }
    assert platforms_generic._xhs_best_stream_url(stream) == (
        "https://cdn.xhscdn.com/master-1080p-high.mp4"
    )
    only_backup = {
        "EF6": [
            {
                "height": 720,
                "videoBitrate": 800000,
                "backupUrls": ["https://cdn.xhscdn.com/backup-720p.mp4"],
            }
        ]
    }
    assert platforms_generic._xhs_best_stream_url(only_backup) == (
        "https://cdn.xhscdn.com/backup-720p.mp4"
    )


def test_xhs_stream_empty_or_urlless_returns_empty_string():
    """契约保持：取不到返回 ""（非 dict/空字典/有条目但无任何 URL）。"""
    assert platforms_generic._xhs_best_stream_url(None) == ""
    assert platforms_generic._xhs_best_stream_url({}) == ""
    assert platforms_generic._xhs_best_stream_url({"av1": [{"height": 720}]}) == ""
    assert platforms_generic._xhs_best_stream_url({"h264": "not-a-list"}) == ""


# ---------- ② 推特 pbs.twimg.com 原图 name=orig ----------


def _query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_twitter_plain_url_gets_format_and_orig():
    """无参直链 → 补 ?format={路径扩展名}&name=orig。"""
    out = platforms_generic._twitter_large_url("https://pbs.twimg.com/media/abc.jpg")
    assert out == "https://pbs.twimg.com/media/abc.jpg?format=jpg&name=orig"


def test_twitter_mismatched_format_replaced_by_path_ext():
    """已有错 format（CDN 转换已下线，不一致一律 404）→ 强制改写一致。"""
    out = platforms_generic._twitter_large_url(
        "https://pbs.twimg.com/media/abc.png?format=jpg"
    )
    params = _query_params(out)
    assert params["format"] == ["png"]
    assert params["name"] == ["orig"]


def test_twitter_existing_name_large_normalized_to_orig():
    """已有 name=large（旧实现口径）→ 归一为 name=orig 且补齐 format。"""
    out = platforms_generic._twitter_large_url(
        "https://pbs.twimg.com/media/abc.jpg?name=large"
    )
    params = _query_params(out)
    assert params["name"] == ["orig"]
    assert params["format"] == ["jpg"]


def test_twitter_jpeg_normalized_and_existing_query_preserved():
    """jpeg 归一 jpg；既有其他 query 参数保留（用 & 追加）。"""
    out = platforms_generic._twitter_large_url(
        "https://pbs.twimg.com/media/abc.jpeg?h=100&name=large"
    )
    assert out.startswith("https://pbs.twimg.com/media/abc.jpeg?h=100")
    params = _query_params(out)
    assert params["format"] == ["jpg"]
    assert params["name"] == ["orig"]


# ---------- ③ http_util GET：429 Retry-After 有界重试 + 4xx 快速失败 ----------


class _FakeResponse:
    """模拟 urllib response（与 test_auditfix_parsers 同款最小形态）。"""

    def __init__(self, payload: bytes = b"payload"):
        self._payload = payload
        self.headers = {"Content-Encoding": ""}

    def read(self, size: int = -1) -> bytes:
        return self._payload

    def geturl(self) -> str:
        return "https://example.com/final"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeStatusOpener:
    """前 raise_times 次抛指定状态码，之后放行假响应；记录调用次数。"""

    def __init__(self, status: int, raise_times: int, retry_after: str | None = None):
        self._status = status
        self._raise_times = raise_times
        self._retry_after = retry_after
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        if self.calls <= self._raise_times:
            headers = {}
            if self._retry_after is not None:
                headers["Retry-After"] = self._retry_after
            raise urllib.error.HTTPError(
                request.full_url, self._status, "error", headers, None
            )
        return _FakeResponse()


def test_http_get_429_honors_retry_after_then_succeeds(monkeypatch):
    """429 → 等待 Retry-After（秒）重试，≤2 次有界内成功。"""
    sleeps: list[float] = []
    monkeypatch.setattr(http_util, "_sleep", sleeps.append)
    opener = _FakeStatusOpener(429, raise_times=2, retry_after="7")
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: opener)
    _, body = http_util.http_get("https://example.com/api")
    assert body == b"payload"
    assert opener.calls == 3  # 首次 + 2 次重试（有界上限）
    assert sleeps == [7.0, 7.0]


def test_http_get_429_without_header_backs_off_exponentially(monkeypatch):
    """429 无 Retry-After 头 → 按退避基数指数退避（1s * 2^attempt）。"""
    sleeps: list[float] = []
    monkeypatch.setattr(http_util, "_sleep", sleeps.append)
    opener = _FakeStatusOpener(429, raise_times=1)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: opener)
    _, body = http_util.http_get("https://example.com/api")
    assert body == b"payload"
    assert opener.calls == 2
    assert sleeps == [1.0]


def test_http_get_429_exhausts_attempts_and_raises_with_headers(monkeypatch):
    """持续 429 → 达到有界上限后抛 ParseHttpError（状态码/头保留）；
    Retry-After 120s 按 60s 封顶等待。"""
    sleeps: list[float] = []
    monkeypatch.setattr(http_util, "_sleep", sleeps.append)
    opener = _FakeStatusOpener(429, raise_times=99, retry_after="120")
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: opener)
    with pytest.raises(ParseHttpError) as exc_info:
        http_util.http_get("https://example.com/api")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 120
    assert opener.calls == 3
    assert sleeps == [60.0, 60.0]


def test_http_get_other_4xx_fails_immediately(monkeypatch):
    """其余 4xx 是永久性失败（format 不匹配一律 404）→ 立即抛出不重试。"""
    sleeps: list[float] = []
    monkeypatch.setattr(http_util, "_sleep", sleeps.append)
    opener = _FakeStatusOpener(404, raise_times=99)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: opener)
    with pytest.raises(ParseHttpError) as exc_info:
        http_util.http_get("https://example.com/miss")
    assert exc_info.value.status_code == 404
    assert opener.calls == 1
    assert sleeps == []


def test_http_get_5xx_keeps_legacy_no_retry_semantics(monkeypatch):
    """5xx 维持现状：立即抛 ParseHttpError，不做 429 式等待重试。"""
    sleeps: list[float] = []
    monkeypatch.setattr(http_util, "_sleep", sleeps.append)
    opener = _FakeStatusOpener(503, raise_times=99)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: opener)
    with pytest.raises(ParseHttpError) as exc_info:
        http_util.http_get("https://example.com/down")
    assert exc_info.value.status_code == 503
    assert opener.calls == 1
    assert sleeps == []


def test_xhs_best_stream_url_legacy_url_key_fallback() -> None:
    """旧本地流形态（仅 "url" 键，无 masterUrl/backupUrls）不空转（回归）。"""
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        _xhs_best_stream_url,
    )

    assert (
        _xhs_best_stream_url({"h264": [{"url": "https://sns-video-hw.xhscdn.com/v.mp4"}]})
        == "https://sns-video-hw.xhscdn.com/v.mp4"
    )
    # 新旧混合：masterUrl 优先于 url。
    assert (
        _xhs_best_stream_url(
            {"EF7": [{"url": "https://legacy/v.mp4", "masterUrl": "https://new/v.mp4"}]}
        )
        == "https://new/v.mp4"
    )
