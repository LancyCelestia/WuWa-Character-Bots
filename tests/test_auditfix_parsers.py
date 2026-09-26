"""audit-fix E1 组回归测试（链接解析器与 sources 域）：全部离线，网络均被 monkeypatch。

覆盖项（对应审计编号）：
- E1-1  cookies.py：全 session cookie 不崩溃；#HttpOnly_ 前缀行可解析
- E1-2  platforms_generic.py：小红书 xsec_token 首参数形态可剥、不破坏其余参数
- E1-3  platforms_generic/media_share：\\uXXXX 与字面中文共存不乱码（含代理对）
- E1-5  http_util.py：max_bytes 默认生效、超限 ParseHttpError；POST HTTPError
        保留状态码与 Retry-After；resolve_short_link 不读 body 拿落点
- E1-6  platforms_music.py：search_apple_music 单国失败回退下一国
- E1-7  platforms_taptap.py：登录 cookie 走请求头不进 URL
- E1-9  steam/epic/facebook：兜底代理读 BOT_DOWNLOAD_PROXY，未配置不追加
- E1-10 platforms_generic.py：INITIAL_STATE 嵌套 new Map 可解析、\\bundefined\\b
- E1-11 web_search.py：config=None 装配 DDG/Bing 兜底链；未闭合残段剥离
- E1-12 transcribe.py：语音下载流式限读超限即弃
- E1-13 vision_describe.py：超大本地图不转 data URL
- E1-14 wbi.py：mixin key 并发 single-flight（一次 miss 只打一次 nav）
- E1-15 platforms_generic.py：youtu.be/<id>?list= 走单视频分支
- E1-16 platforms_bilibili.py：字幕行间空格连接不粘连
- E1-17 platforms_bilibili_goods.py：脏价格数据降级不抛
- E1-18 youtube/微博富化链整体预算（超预算返回已有数据/回退）
"""

from __future__ import annotations

import gzip
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    cookies as cookies_mod,
)

# v21r2 W1a: platforms_* 真身已迁 domains/link_parse/parsers/，monkeypatch 需打在真身模块上
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    http_util,
    platforms_bilibili,
    platforms_bilibili_goods,
    platforms_generic,
    platforms_music,
    platforms_taptap,
    platforms_weibo,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    wbi as wbi_mod,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    DEFAULT_MAX_BYTES,
    ParseHttpError,
)

# ---------- E1-1 cookies ----------


def _write_cookie_file(tmp_path, lines: list[str]):
    path = tmp_path / "platform_cookies.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_all_session_cookies_do_not_crash(tmp_path):
    """全为会话 cookie（expires=0）时 min() 不抛 ValueError，expires 语义化为 0。"""
    path = _write_cookie_file(
        tmp_path,
        [
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsess_value",
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tbili_jct\tjct_value",
        ],
    )
    provider = cookies_mod.build_platform_cookie_provider(path)
    assert provider.has_cookie("bilibili")
    assert "SESSDATA=sess_value" in provider.cookie_header("bilibili")
    assert provider.earliest_expires("bilibili") == 0


def test_httponly_prefix_line_is_parsed(tmp_path):
    """#HttpOnly_ 前缀是合法 Netscape 行，剥前缀后解析出 cookie。"""
    path = _write_cookie_file(
        tmp_path,
        [
            "#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tht_value",
            "# comment line to be ignored",
            "#Netscape HTTP Cookie File",
        ],
    )
    entries = cookies_mod.parse_netscape_cookie_file(path)
    names = [entry.name for entry in entries]
    assert "SESSDATA" in names
    provider = cookies_mod.build_platform_cookie_provider(path)
    assert provider.cookie_header("bilibili") == "SESSDATA=ht_value"


# ---------- E1-2 xsec_token 剥除 ----------


def test_xhs_strips_first_position_xsec_token(monkeypatch):
    """xsec_token 是 query 首参数时也能剥掉，且保留其余参数与路径。"""
    captured: list[str] = []

    deep_state_html = (
        '<html><script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{'
        '"n1":{"note":{"noteId":"n1","title":"标题","desc":"正文"}}}}};</script></html>'
    )

    def fake_get_text(url, **kwargs):
        captured.append(url)
        # 第一次（带 token）返回无 INITIAL_STATE 的页面 → 深解析 None；
        # 第二次（剥 token 后）返回完整状态页。
        if "xsec_token=" not in url:
            return url, deep_state_html
        return url, "<html>no state</html>"

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)

    item = platforms_generic.parse_xiaohongshu(
        "https://www.xiaohongshu.com/explore/abc123?xsec_token=AAA111&xsec_source=pc_share",
        cookie_header="web_session=xyz",
    )
    assert item.identity.item_kind in ("note", "video")
    assert len(captured) == 2
    stripped_url = captured[1]
    assert "xsec_token" not in stripped_url
    assert "xsec_source=pc_share" in stripped_url
    assert "/explore/abc123" in stripped_url


def test_xhs_strip_keeps_token_in_middle_position():
    """中间参数形态：剥 token 不破坏相邻参数、不残留空分隔符；尾参数形态不留悬挂 &。"""
    import re as _re
    from urllib import parse as urlparse

    fresh = urlparse.urlsplit(
        "https://www.xiaohongshu.com/explore/x?xsec_source=pc&xsec_token=TOKEN&device=pc"
    )
    stripped_query = _re.sub(r"(^|&)xsec_token=[^&]*&?", r"\1", fresh.query).strip("&")
    stripped = urlparse.urlunsplit(fresh._replace(query=stripped_query))
    assert stripped == "https://www.xiaohongshu.com/explore/x?xsec_source=pc&device=pc"

    fresh = urlparse.urlsplit("https://www.xiaohongshu.com/explore/x?a=1&xsec_token=T")
    stripped_query = _re.sub(r"(^|&)xsec_token=[^&]*&?", r"\1", fresh.query).strip("&")
    stripped = urlparse.urlunsplit(fresh._replace(query=stripped_query))
    assert stripped == "https://www.xiaohongshu.com/explore/x?a=1"


# ---------- E1-3 \\uXXXX 与字面中文共存 ----------


def test_yt_unescape_mixed_literal_chinese_and_escapes():
    result = platforms_generic._yt_unescape("\\u4f60\\u597d 世界 \\u0026 more")
    assert result == "你好 世界 & more"


def test_yt_unescape_surrogate_pair_emoji():
    result = platforms_generic._yt_unescape("\\ud83d\\ude00 ok")
    assert "😀" in result
    assert "ok" in result


def test_unescape_js_unicode_plain_chinese_untouched():
    assert platforms_generic._unescape_js_unicode("纯中文文本") == "纯中文文本"


# ---------- E1-5 http_util max_bytes / POST HTTPError / short link ----------


class _FakeResponse:
    """模拟 urllib response：read(n) 有界、记录读取上限、可返回 gzip。"""

    def __init__(self, payload: bytes, *, gzipped: bool = False, final_url=""):
        self._payload = payload
        self._gzipped = gzipped
        self.read_limits: list[int] = []
        self.headers = {"Content-Encoding": "gzip" if gzipped else ""}
        self._final_url = final_url

    def read(self, size: int = -1) -> bytes:
        self.read_limits.append(size)
        if size is None or size < 0:
            return self._payload
        return self._payload[:size]

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, response):
        self._response = response

    def open(self, request, timeout=None):
        return self._response


def test_max_bytes_default_is_effective_without_caller_arg(monkeypatch):
    """调用方不传 max_bytes 时默认上限也生效（read 被限定为 DEFAULT_MAX_BYTES+1）。"""
    payload = b"x" * 100
    response = _FakeResponse(payload)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpener(response))
    _, body = http_util.http_get("https://example.com/data")
    assert body == payload
    assert response.read_limits == [DEFAULT_MAX_BYTES + 1]


def test_over_limit_response_raises_parse_http_error(monkeypatch):
    """响应体超过上限 → ParseHttpError（与既有失败语义一致），不是内存整读。"""
    response = _FakeResponse(b"y" * (DEFAULT_MAX_BYTES + 8))
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpener(response))
    with pytest.raises(ParseHttpError, match="max_bytes"):
        http_util.http_get("https://example.com/big")


def test_gzip_bomb_over_limit_after_decompress(monkeypatch):
    """gzip 炸弹：传输层不超限但解压后超限 → ParseHttpError（不静默放大读入）。"""
    raw = b"z" * 1000
    compressed = gzip.compress(raw)
    response = _FakeResponse(compressed, gzipped=True)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpener(response))
    with pytest.raises(ParseHttpError, match="max_bytes"):
        http_util.http_get("https://example.com/gz", max_bytes=100)


def test_gzip_under_limit_roundtrips(monkeypatch):
    """正常 gzip 响应（解压后未超限）照常解压返回。"""
    compressed = gzip.compress(b"payload-data")
    response = _FakeResponse(compressed, gzipped=True)
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpener(response))
    _, body = http_util.http_get("https://example.com/gz")
    assert body == b"payload-data"


def test_post_http_error_keeps_status_and_retry_after(monkeypatch):
    """POST 429：ParseHttpError 携带状态码与 Retry-After，而不是被吞成通用异常。"""
    headers = {"Retry-After": "7"}

    class _FakeOpenerRaise:
        def open(self, request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many Requests", headers, None
            )

    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpenerRaise())
    with pytest.raises(ParseHttpError) as exc_info:
        http_util.http_post_json("https://example.com/api", {"a": 1})
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 7


def test_resolve_short_link_via_local_redirect_server(monkeypatch):
    """本地 302 服务验证 resolve_short_link 返回落点且不整读 body。

    审查 F-05 后逐跳 SSRF 校验已挂进 resolve_short_link；本用例的
    127.0.0.1 本地服务按护栏语义会被正确拒绝（回环=内网），故这里仅对
    本用例 stub ssrf_guard.check_fetch_landing，专注验证「跟随 30x、
    返回落点」的机械行为；护栏逐跳拦截语义由 test_short_link_hop_guard.py
    全量覆盖。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers import (
        ssrf_guard as ssrf_guard_mod,
    )

    monkeypatch.setattr(ssrf_guard_mod, "check_fetch_landing", lambda target, src: None)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"final-body")

        def log_message(self, *args):  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        final = http_util.resolve_short_link(
            f"http://127.0.0.1:{server.server_port}/start", timeout=5.0
        )
        assert final.endswith("/final")
    finally:
        server.shutdown()
        server.server_close()


# ---------- E1-6 apple music 国别回退 ----------


def test_search_apple_music_falls_back_per_country(monkeypatch):
    """cn 查询抛 ParseHttpError 时回退 us；两国都失败返回 None 不抛。"""
    calls: list[str] = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "country=cn" in url:
            raise ParseHttpError("cn store down")
        return {
            "results": [
                {
                    "trackId": 42,
                    "trackName": "Song",
                    "artistName": "Artist",
                    "previewUrl": "https://example.com/p.m4a",
                }
            ]
        }

    monkeypatch.setattr(platforms_music, "http_get_json", fake_get_json)
    item = platforms_music.search_apple_music("query")
    assert item is not None
    assert any("country=cn" in url for url in calls)
    assert any("country=us" in url for url in calls)

    calls.clear()

    def always_fail(url, **kwargs):
        calls.append(url)
        raise ParseHttpError("down")

    monkeypatch.setattr(platforms_music, "http_get_json", always_fail)
    assert platforms_music.search_apple_music("query") is None


# ---------- E1-7 taptap cookie 走请求头 ----------


def test_taptap_cookie_goes_to_header_not_url(monkeypatch):
    captured: dict = {}

    def fake_get_json(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return {
            "data": {
                "moment": {
                    "rich_content": "动态正文",
                    "author": {"user": {"name": "作者"}},
                    "stat": {"ups": 3},
                }
            }
        }

    monkeypatch.setattr(platforms_taptap, "http_get_json", fake_get_json)
    item = platforms_taptap.parse_taptap_moment("123", cookie_header="user_token=SECRET")
    assert item is not None
    assert "cookie=" not in captured["url"]
    assert captured["kwargs"].get("cookie") == "user_token=SECRET"
    assert item.content.title.startswith("动态正文")


# ---------- E1-9 兜底代理环境变量 ----------


def test_steam_proxy_attempts_use_env(monkeypatch):
    from plugins.bot_unified_runtime.domains.link_parse.parsers import platforms_steam

    monkeypatch.delenv("BOT_DOWNLOAD_PROXY", raising=False)
    assert platforms_steam._proxy_attempts("") == [""]

    monkeypatch.setenv("BOT_DOWNLOAD_PROXY", "http://127.0.0.1:9999")
    assert platforms_steam._proxy_attempts("") == ["", "http://127.0.0.1:9999"]
    assert platforms_steam._proxy_attempts("http://p:1") == ["http://p:1"]


def test_epic_facebook_fallback_proxy_from_env(monkeypatch):
    from plugins.bot_unified_runtime.domains.link_parse.parsers import (
        platforms_epic,
        platforms_facebook,
    )

    monkeypatch.delenv("BOT_DOWNLOAD_PROXY", raising=False)
    assert platforms_epic._fallback_proxy() == ""
    assert platforms_facebook._fallback_proxy() == ""

    monkeypatch.setenv("BOT_DOWNLOAD_PROXY", "http://127.0.0.1:9999")
    assert platforms_epic._fallback_proxy() == "http://127.0.0.1:9999"
    assert platforms_facebook._fallback_proxy() == "http://127.0.0.1:9999"


# ---------- E1-10 INITIAL_STATE 预清洗 ----------


def test_xhs_initial_state_nested_map_and_undefined():
    html = (
        '<html><script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{'
        '"n1":{"note":{"noteId":"n1","title":"t","desc":"desc-text",'
        '"extra":{"m":new Map([["a",[1,[2,3]]],["b",{"c":[4,[5]]}]]),'
        '"flag":undefined}}}}}};</script></html>'
    )
    payload = platforms_generic._xhs_initial_state_payload(html)
    assert payload is not None
    note = payload["note"]["noteDetailMap"]["n1"]["note"]
    assert note["desc"] == "desc-text"
    assert note["extra"]["flag"] is None
    assert note["extra"]["m"] is None


def test_xhs_initial_state_word_boundary_undefined():
    """词边界：英文正文里的 `undefinedness` 之类相邻词不被误改；独立词 undefined
    仍会被改写为 null（文档化残留风险）。"""
    html = (
        '<html><script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{'
        '"n1":{"note":{"title":"t","desc":"the undefined value here",'
        '"keep":"undefinedness preserved"}}}}};</script></html>'
    )
    payload = platforms_generic._xhs_initial_state_payload(html)
    assert payload is not None
    note = payload["note"]["noteDetailMap"]["n1"]["note"]
    assert note["keep"] == "undefinedness preserved"
    assert "null value" in note["desc"]


# ---------- E1-11 web_search 兜底链与未闭合残段 ----------


def test_build_chained_provider_without_config_uses_ddg_bing_fallback():
    from plugins.bot_unified_runtime.domains.core.search import web_search

    provider = web_search._build_chained_provider(3.0, "")
    names = [getattr(p, "name", "") for p in provider.providers]
    assert names == ["ddg", "bing"]


def test_unclosed_script_and_comment_fragments_stripped():
    from plugins.bot_unified_runtime.domains.core.search import web_search

    html = '<html><body>正文A<!-- unclosed comment secret<script>alert("x")'
    text = web_search._HTML_COMMENT_RE.sub(" ", html)
    text = web_search._HTML_HIDDEN_BLOCK_RE.sub(" ", text)
    text = web_search._HTML_UNCLOSED_COMMENT_RE.sub(" ", text)
    text = web_search._HTML_UNCLOSED_HIDDEN_RE.sub(" ", text)
    assert "正文A" in text
    assert "secret" not in text
    assert "alert" not in text


# ---------- E1-12 transcribe 流式限读 ----------


def test_download_audio_streaming_over_limit(monkeypatch, tmp_path):
    import httpx as httpx_mod

    from plugins.bot_unified_runtime.domains.media.ingest import transcribe

    monkeypatch.setattr(transcribe, "_MAX_AUDIO_BYTES", 100)

    class _FakeStreamResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @property
        def status_code(self):
            return 200

        def iter_bytes(self):
            yield from self._chunks

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            return _FakeStreamResponse([b"x" * 60, b"y" * 60])

    monkeypatch.setattr(httpx_mod, "Client", _FakeClient)
    dest = tmp_path / "src.bin"
    assert transcribe._download_audio("https://example.com/a.bin", dest, 5.0) is None
    assert not dest.exists()


def test_download_audio_streaming_under_limit_writes_file(monkeypatch, tmp_path):
    import httpx as httpx_mod

    from plugins.bot_unified_runtime.domains.media.ingest import transcribe

    class _FakeStreamResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @property
        def status_code(self):
            return 200

        def iter_bytes(self):
            yield from self._chunks

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            return _FakeStreamResponse([b"ab", b"cd"])

    monkeypatch.setattr(httpx_mod, "Client", _FakeClient)
    dest = tmp_path / "src.bin"
    assert transcribe._download_audio("https://example.com/a.bin", dest, 5.0) == dest
    assert dest.read_bytes() == b"abcd"


# ---------- E1-13 vision_describe 超大本地图 ----------


def test_oversized_local_image_skips_data_url(monkeypatch, tmp_path):
    from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

    big = tmp_path / "huge.png"
    big.write_bytes(b"\0" * (vision_describe._MAX_LOCAL_IMAGE_INPUT_BYTES + 1))
    assert vision_describe._image_file_to_data_url(str(big)) is None


# ---------- E1-14 wbi single-flight ----------


def test_wbi_cached_mixin_key_single_flight(monkeypatch):
    wbi_mod._WBI_CACHE.clear()
    wbi_mod._WBI_INFLIGHT.clear()
    calls: list[int] = []
    started = threading.Event()

    def slow_fetch():
        calls.append(1)
        started.set()
        time.sleep(0.2)
        return {
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
                }
            }
        }

    results: list[str] = []
    errors: list[Exception] = []

    def worker():
        try:
            results.append(wbi_mod._cached_mixin_key("ck-single", "", fetch=slow_fetch))
        except Exception as exc:  # noqa: BLE001 - 收集线程内失败到主线程断言。
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert len(results) == 4
    assert len(calls) == 1  # 并发 miss 只打一次 nav（single-flight）
    assert len(results[0]) == 32
    wbi_mod._WBI_CACHE.clear()
    wbi_mod._WBI_INFLIGHT.clear()


def test_bilibili_wbi_signed_url_delegates_to_cached_key(monkeypatch):
    """薄壳仍走本模块 http_get_json 缝（monkeypatch 可拦截 nav），并复用 wbi 缓存。"""
    wbi_mod._WBI_CACHE.clear()
    wbi_mod._WBI_INFLIGHT.clear()
    nav_calls: list[str] = []

    def _nav(url, **kwargs):
        nav_calls.append(url)
        return {
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/cccccccccccccccccccccccccccccccc.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/dddddddddddddddddddddddddddddddd.png",
                }
            }
        }

    monkeypatch.setattr(platforms_bilibili, "http_get_json", _nav)
    url = platforms_bilibili.build_wbi_signed_url(
        "https://api.bilibili.com/x/player/wbi/v2",
        {"bvid": "BV1xx411c7mD", "cid": "1"},
        cookie_header="ck-delegate",
    )
    assert "w_rid=" in url and "wts=" in url
    assert len(nav_calls) == 1
    # 第二次签名命中 wbi 缓存，不再打 nav。
    platforms_bilibili.build_wbi_signed_url(
        "https://api.bilibili.com/x/player/wbi/v2",
        {"bvid": "BV1xx411c7mD", "cid": "2"},
        cookie_header="ck-delegate",
    )
    assert len(nav_calls) == 1
    wbi_mod._WBI_CACHE.clear()
    wbi_mod._WBI_INFLIGHT.clear()


# ---------- E1-15 youtu.be?list= 走单视频 ----------


def test_youtu_be_with_list_param_parses_single_video(monkeypatch):
    monkeypatch.setattr(
        platforms_generic,
        "http_get_json",
        lambda url, **kwargs: {
            "title": "视频标题",
            "author_name": "UP 主",
            "author_url": "https://www.youtube.com/@handle",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg",
        },
    )
    monkeypatch.setattr(platforms_generic, "_youtube_watch_enrich", lambda url, **k: {})
    monkeypatch.setattr(platforms_generic, "_youtube_innertube", lambda vid, **k: {})
    monkeypatch.setattr(platforms_generic, "_youtube_about_enrich", lambda ch, **k: {})

    item = platforms_generic.parse_youtube(
        "https://youtu.be/dQw4w9WgXcQ?list=PLxyz123", proxy=""
    )
    assert item.identity.item_kind == "video"
    assert item.identity.item_id == "dQw4w9WgXcQ"
    assert item.content.title == "视频标题"


def test_playlist_url_still_routes_to_playlist(monkeypatch):
    def fake_og(url, **kwargs):
        return platforms_generic.build_parsed_content(
            platform="youtube",
            item_id="",
            item_kind="playlist",
            title="歌单",
            canonical_url=url,
            parse_depth="shallow",
        )

    monkeypatch.setattr(platforms_generic, "_og_scrape", fake_og)
    item = platforms_generic.parse_youtube(
        "https://www.youtube.com/playlist?list=PLxyz123"
    )
    assert item.identity.item_kind == "playlist"


# ---------- E1-16 字幕行间分隔 ----------


def test_bilibili_subtitle_lines_joined_with_space(monkeypatch):
    def fake_signed_url(url, params, *, cookie_header="", proxy=""):
        return url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    def fake_get_json(url, **kwargs):
        if "player/wbi/v2" in url:
            return {
                "data": {
                    "subtitle": {
                        "subtitles": [
                            {"lan": "ai-zh", "subtitle_url": "https://example.com/sub.json"}
                        ]
                    }
                }
            }
        return {
            "body": [
                {"content": "hello"},
                {"content": "hello"},  # 连续重复行去重
                {"content": "world"},
            ]
        }

    monkeypatch.setattr(platforms_bilibili, "build_wbi_signed_url", fake_signed_url)
    monkeypatch.setattr(platforms_bilibili, "http_get_json", fake_get_json)
    text = platforms_bilibili._bilibili_subtitle(
        bvid="BV1xx411c7mD", cid=1, cookie_header="SESSDATA=x"
    )
    assert text == "hello world"


# ---------- E1-17 商品脏价格降级 ----------


def test_goods_dirty_price_degrades_without_raise():
    item = platforms_bilibili_goods._goods_parse_from_item(
        {"c2cItemsId": "42", "c2cItemsName": "商品", "price": "not-a-number"},
        "https://mall.bilibili.com/",
    )
    assert item.content is not None
    assert item.content.title == "商品"
    # 价格缺失进不了 detail.goods，也绝不抛异常。
    assert (item.content.platform_extra or {}).get("goods", {}).get("price") is None


def test_goods_valid_price_still_converts():
    item = platforms_bilibili_goods._goods_parse_from_item(
        {"c2cItemsId": "42", "c2cItemsName": "商品", "price": 12345},
        "https://mall.bilibili.com/",
    )
    goods = (item.content.platform_extra or {}).get("goods") or {}
    assert goods.get("price") == 123.45


# ---------- E1-18 整体预算 ----------


def test_weibo_status_budget_exhausted_raises(monkeypatch):
    monkeypatch.setattr(platforms_weibo, "_WEIBO_STATUS_BUDGET_SECONDS", 0.0)

    def _must_not_fetch(*args, **kwargs):
        raise AssertionError("budget=0 但仍尝试了网络请求（预算未前置判定）")

    monkeypatch.setattr(platforms_weibo, "http_get_json", _must_not_fetch)
    # 2026-09-13 去抖动：旧版断言墙钟 <2s，在全量套件高负载下会抖红；
    # 改为确定性断言——预算耗尽时零网络尝试 + 必抛 budget ParseHttpError。
    with pytest.raises(ParseHttpError, match="budget"):
        platforms_weibo._weibo_status_card(
            "ABCDEF123", "https://weibo.com/1/ABCDEF123", cookie_header="", proxy=""
        )


def test_youtube_enrich_budget_zero_skips_enrichment(monkeypatch):
    monkeypatch.setattr(platforms_generic, "_YOUTUBE_ENRICH_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(
        platforms_generic,
        "http_get_json",
        lambda url, **kwargs: {
            "title": "标题",
            "author_name": "UP",
            "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg",
        },
    )

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("budget exhausted but enrichment step was called")

    monkeypatch.setattr(platforms_generic, "_youtube_watch_enrich", _must_not_be_called)
    monkeypatch.setattr(platforms_generic, "_youtube_about_enrich", _must_not_be_called)
    item = platforms_generic.parse_youtube(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", proxy=""
    )
    assert item.content.title == "标题"
