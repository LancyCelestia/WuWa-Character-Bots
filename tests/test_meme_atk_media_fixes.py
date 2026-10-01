"""攻击审计 A-1/A-2/A-3/A-5 修复锁（席位 S-FIX-ATK-MEDIA，2026-09-27 fullload）。

每票先立 RED 锁（断言收紧后的行为），再修到绿；反向锁同文件登记：

- A-2：``_default_image_fetch_fn`` 每一跳过 ``check_download_url``——入口即
  内网/保留段 ⇒ **零请求发出**（MockTransport 录制计数，确定性无真网络）；
  公网合法跳转不得被误杀（过收紧反向锁）。
- A-3：key 白名单 ``^[A-Za-z0-9_-]{1,64}$``——非合规键拒绝且**不触碰后端**
  （录制 request_fn 断言零调用），绝不静默洗成近似值。
- A-1：落盘文件名判定收敛到中央真身 ``sanitize_write_segments``（设备名
  点号前首段判定唯一真身；本席只调用不修改）。``nul.txt``/``nul``/``con.md``
  必须收到中央人话理由（含「保留设备名」字样）。
- A-5：randpic 会话冷却——登记为待办（与 randpic 在飞行为锁冲突，详见文件末注）。
"""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import meme as meme_mod
from plugins.bot_unified_runtime.domains.meme.capabilities.meme import (
    _default_image_fetch_fn,
    build_meme_capability,
)

# ---------------------------------------------------------------------------
# 通用夹具
# ---------------------------------------------------------------------------

_DECISION = BotDecision(
    request_id="r-atk",
    should_respond=True,
    mode="command",
    trigger="test",
    capability_id="bot.meme",
    target_scope=SessionType.GROUP,
    decision_reason="unit-test",
)


def _message(
    text: str,
    *,
    segments: list[dict] | None = None,
    platform: str = "onebot",
    sender_id: str = "10001",
    session_id: str = "group:1",
) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="onebot.v11" if platform == "onebot" else platform,
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP,
        group_id="1",
        sender_id=sender_id,
        plain_text=text,
        raw_segments=segments or [],
    )


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_meme_api_enabled=True,
        bot_meme_api_base_url="http://127.0.0.1:2233",
        bot_meme_api_timeout_seconds=5,
        bot_meme_api_output_dir=str(tmp_path / "memes"),
        bot_meme_cache_max_bytes=0,
    )


def _recording_request_fn(routes: dict):
    calls: list[tuple[str, str, dict | None]] = []

    def request(method: str, path: str, json: dict | None = None):
        key = (method.upper(), path)
        calls.append((method.upper(), path, json))
        return routes[key]

    return request, calls


# ---------------------------------------------------------------------------
# A-2：抓图腿逐跳过咽喉（入口 + 每一跳落点），拒绝 = 零网络
# ---------------------------------------------------------------------------


def _patched_httpx_client(monkeypatch: pytest.MonkeyPatch, handler):
    """把 httpx.Client 包一层注入 MockTransport：真实构造参数原样保留。

    录制点即 transport handler——事件钩子在 transport 建连之前触发，
    咽喉抛 ``RejectedUrlError`` 时该跳**不会**出现在录制里，
    「零请求」断言因此是确定性的（不触任何真网络）。
    """
    received: list[str] = []
    real_client = httpx.Client

    def _handler(request: httpx.Request) -> httpx.Response:
        received.append(str(request.url))
        return handler(request)

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    return received


def test_fetch_entry_internal_url_zero_request(monkeypatch) -> None:
    # 锁死 DNS：入口判内网字面量不查 DNS，若实现误走域名分支即 AssertionError。
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dns")))
    received = _patched_httpx_client(
        monkeypatch, lambda request: httpx.Response(200, content=b"PNGDATA")
    )
    assert _default_image_fetch_fn("http://127.0.0.1:2233/x.png") is None
    assert received == [], "入口内网地址必须零请求（咽喉先于连接）"


def test_fetch_metadata_ip_entry_rejected(monkeypatch) -> None:
    received = _patched_httpx_client(
        monkeypatch, lambda request: httpx.Response(200, content=b"PNGDATA")
    )
    assert _default_image_fetch_fn("http://169.254.169.254/latest/meta-data") is None
    assert received == [], "云元数据地址必须零请求"


def test_fetch_redirect_to_internal_hop_never_fetched(monkeypatch) -> None:
    received = _patched_httpx_client(
        monkeypatch,
        lambda request: (
            httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})
            if request.url.host == "8.8.8.8"
            else httpx.Response(200, content=b"META-SECRET")
        ),
    )
    out = _default_image_fetch_fn("http://8.8.8.8/a.png")
    assert out is None, "302 落点内网：抓图必须失败"
    assert received == ["http://8.8.8.8/a.png"], "内网落点一跳都不能发出去"


def test_fetch_legitimate_public_redirect_still_works(monkeypatch) -> None:
    """反向锁（防过收紧）：公网→公网的合法跳转照旧取回字节。"""
    received = _patched_httpx_client(
        monkeypatch,
        lambda request: (
            httpx.Response(302, headers={"location": "http://9.9.9.9/b.png"})
            if str(request.url) == "http://8.8.8.8/a.png"
            else httpx.Response(200, content=b"PNGDATA")
        ),
    )
    out = _default_image_fetch_fn("http://8.8.8.8/a.png")
    assert out == b"PNGDATA"
    assert received == ["http://8.8.8.8/a.png", "http://9.9.9.9/b.png"]


def test_fetch_non_http_scheme_rejected(monkeypatch) -> None:
    received = _patched_httpx_client(
        monkeypatch, lambda request: httpx.Response(200, content=b"X")
    )
    assert _default_image_fetch_fn("file:///C:/Windows/win.ini") is None
    assert received == []


# ---------------------------------------------------------------------------
# A-3：key 白名单——非合规键拒绝且不触碰后端
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_key", "sample_text"),
    [
        ("nul.txt", "你好"),                # 点号形态（A-1 同源攻击面）
        ("con.md", "x"),                    # 设备名+扩展名
        ("../../etc/passwd", "x"),          # 穿越
        ("a%2Fb", "x"),                     # 编码分隔符
        ("k" * 65, "x"),                    # 超长
    ],
)
def test_invalid_key_rejected_without_touching_backend(tmp_path, bad_key, sample_text) -> None:
    # 路由表按「旧代码会碰的路径」铺满：修复后一条都不该被调用。
    routes = {
        ("GET", f"/memes/{bad_key}/info"): (200, {"params": {}}),
        ("POST", f"/memes/{bad_key}"): (200, {"image_id": "gen"}),
        ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
    }
    request, calls = _recording_request_fn(routes)
    capability = build_meme_capability(
        _config(tmp_path), request_fn=request, image_fetch_fn=lambda url: b"PNGDATA"
    )
    result = capability(_message(f"/表情 {bad_key} {sample_text}"), _DECISION)

    assert result.kind == "text", "非合规键必须走失败面"
    assert "meme_invalid_key" in result.audit_tags
    assert calls == [], f"非合规键不得触碰后端任何端点，实际 {calls}"
    out_dir = tmp_path / "memes"
    assert not out_dir.exists() or list(out_dir.iterdir()) == [], "拒绝路径不得落盘"


def test_valid_key_still_renders(tmp_path) -> None:
    """反向锁：白名单放行合规键，链路照常（防过收紧）。"""
    routes = {
        ("GET", "/memes/petpet/info"): (
            200,
            {"params": {"min_images": 0, "max_images": 0, "min_texts": 1, "max_texts": 1}},
        ),
        ("POST", "/memes/petpet"): (200, {"image_id": "gen"}),
        ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
    }
    request, _calls = _recording_request_fn(routes)
    capability = build_meme_capability(_config(tmp_path), request_fn=request)
    result = capability(_message("/表情 petpet 可爱"), _DECISION)
    assert result.kind == "mixed"


# ---------------------------------------------------------------------------
# A-1：落盘名判定收敛到中央 sanitize_write_segments（调用不改）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["nul", "nul.txt", "con.md", "COM1.png", "aux.dat"])
def test_output_name_guard_rejects_reserved_forms_with_human_reason(bad_name) -> None:
    reason = meme_mod._output_name_rejection(bad_name)
    assert reason is not None, f"{bad_name!r} 必须被拒"
    assert "保留设备名" in reason, "拒绝理由必须出自中央人话表（DENY_PLAIN_TEXT）"


def test_output_name_guard_passes_normal_names() -> None:
    assert meme_mod._output_name_rejection("meme_petpet_a1b2c3d4e5f6.png") is None
    assert meme_mod._output_name_rejection("meme_5000choyen_0123456789ab.gif") is None


def test_output_name_guard_delegates_to_central_source(monkeypatch) -> None:
    """收敛锁：判定必须真调中央真身，而不是 meme 侧另抄一份点号首段逻辑。"""
    from plugins.bot_unified_runtime.domains.files.sender import restricted_runner

    calls: list[str] = []

    def spy(ref):
        calls.append(str(ref))
        return ()

    monkeypatch.setattr(restricted_runner, "sanitize_write_segments", spy)
    assert meme_mod._output_name_rejection("whatever.png") is None
    assert calls == ["whatever.png"], "必须经中央真身的模块属性调用（单一判据）"


# ---------------------------------------------------------------------------
# A-5：randpic 会话级冷却——本席**只登记不落地**（简报允许「可只登记」）。
# 原因：现网行为锁 test_randpic_no_repeat_ledger / test_randpic_identity /
# test_randpic_pool_side 都刻意对同一 capability/会话连续多触发验证「窗内不重发、
# 再触仍出图」；任何默认开启（>0 秒）的会话冷却都会先于取图挡下第二发，
# 与这些在飞他席锁冲突，需与 randpic 套件主协调后落地。登记正文见
# .superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-ATK-MEDIA.md。
# 待落地时的行为锁（设计留档，不启用）：首触正常；冷却窗内再触 audit_tags 含
# "randpic_cooldown" 且 images 为空；窗过恢复；跨会话互不影响；非触发词消息
# 不消耗冷却。实现形态对齐 meme_library :287-341（闭包 OrderedDict、
# session:sender 键、512 有界化、bot_randpic_cooldown_seconds 缺省 20）。
# ---------------------------------------------------------------------------
