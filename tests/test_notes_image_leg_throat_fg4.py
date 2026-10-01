"""F-G4 配对锁：笔记图片 URL 腿的 TOCTOU 收口——校验与取字节同会话、逐跳过中央咽喉。

工单：logs/BUGS-AGGREGATE.md:269「F-G4 notes 图片 URL 腿 TOCTOU」。
缺陷真身（HEAD 侧）：``domains/notes/capabilities/notes.py:_fetch_image_bytes``——
先 ``check_download_url`` 探一次、再**另起一条裸 ``urllib.request.urlopen``** 取字节，
且 urlopen 默认 opener 自动跟随 30x、逐跳落点零复查：公网入口一跳指进内网/云元数据
时，请求已发进内网（旧代码那句 ``check_download_url(response.geturl())`` 是事后复查，
只拦字节回显、拦不住已建成的连接），两次解析之间还有 DNS rebind 窗口。
``downloader.py`` / ``ssrf_guard.py`` 两处 docstring 都把这条登记为「已知残余（登记不堵）」。

正解（本锁钉死的形态）＝复用中央咽喉链上**唯一**的逐跳护栏
``link_parse.parsers.http_util._GuardedShortLinkRedirectHandler``：每一跳 30x 落点在
**建连之前**先过中央 ``check_download_url``（经 ``ssrf_guard.check_fetch_landing``，
F-04「解析失败=拒绝」），命中内网即抛 ``ParseHttpError``。口径与
``media_archive._fetch_url_media``、``vision_describe._guarded_image_opener`` 完全同源
（它们先趟出来的路），**不在 notes 里另写第二份 URL 校验、不留第二条裸 urlopen 通路**。

四道锁（缺一不可，全离线、零真网络）：
1. **形态锁** ``test_notes_image_leg_wired_through_central_throat``：图片腿源码里
   不得出现裸 ``urlopen``/``urlretrieve``，必须由 ``build_opener(中央护栏 handler)`` 取字节。
2. **装配锁** ``test_notes_image_leg_opener_actually_mounts_central_handler``：
   notes 的护栏 opener 工厂返回的 opener 里**真的装着** ``_GuardedShortLinkRedirectHandler``
   实例（证明复用的是中央那枚，不是自造）。
3. **行为锁** ``test_notes_image_leg_refuses_internal_redirect_landing``：公网入口
   30x → 内网/整型 IP 落点时，那一跳**绝不发出**（假传输件记账 ``== [_ENTRY]``）。
   正向对照：公网→公网落点照旧取回字节（护栏不过度拦）。
4. **反旁路锁** ``test_notes_module_defines_no_second_ssrf_throat``：notes 全文件
   不得定义第二套咽喉（``check_download_url`` 本体/``getaddrinfo``/私网判定字样），
   入口判定必须 import 中央 downloader。

注毒腿（证明本锁不空转）：
- ``test_detector_flags_bare_urlopen_poison``：把图片腿换回裸 urlopen 的形态喂给
  同一个 AST 判据 → 判据必判「越喉」（即真实形态锁必红）。
- ``test_urlopen_tripwire_catches_bypass``：真机上把 ``urllib.request.urlopen`` 装成
  绊线，若图片腿还敢调裸 urlopen（HEAD 中毒态），绊线必触发、测试必红。
全离线纪律：内网落点故意不建路由；``urlopen`` 一律绊线化（裸 urlopen 一旦真被调用即
抛，绝不外发）；URL 用字面量 IP 走咽喉离线判定（零 DNS）；生产护栏 handler 装配不被 mock。

落地腿（席位 S-FIX-NOTES-SSRF，2026-09-30 补，只增不改上面八枚的判据）：护栏拒取与
瞬时失败可分（refusal 登记册）、拒绝后绝不退回第二条通路、拒取必须回一句有人话出路的
回执（且不复述地址）、写侧落点双查（穿越形态的 URL 也只能落在会话目录内）。
"""

from __future__ import annotations

import ast
import email.message
import inspect
import io
import re
import urllib.request as urlrequest
from pathlib import Path
from urllib.response import addinfourl

import pytest

import plugins.bot_unified_runtime.domains.notes.capabilities.notes as N
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    check_download_url as _central_check_download_url,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    _GuardedShortLinkRedirectHandler,
)

# 字面量公网地址：咽喉按字面量离线判定放行，零 DNS、零真网络。
_ENTRY = "http://93.184.216.34/pic.png"
_PUBLIC_LANDING = "http://93.184.216.35/final.png"
MAX_BYTES = 1 << 20

# 必拦的内网/整型 IP 落点（全部走字面量离线判定）。
INTERNAL_LANDINGS = [
    "http://127.0.0.1:3001/status.png",  # 本机回环（SnowLuma 端口场景）
    "http://169.254.169.254/latest/meta-data/",  # 云元数据凭据面
    "http://10.1.2.3/internal.png",  # 私网段
    "http://192.168.1.1/gateway.png",  # 局域网网关
    "http://2130706433/x.png",  # 十进制整型 IP == 127.0.0.1（F-04 归一化）
]

PNG_BODY = b"\x89PNG\r\n\x1a\n" + b"image-bytes"


# --------------------------------------------------------------------------- #
# AST 判据：图片腿有没有绕开中央逐跳护栏（供真实锁与注毒腿共用同一把尺）
# --------------------------------------------------------------------------- #
def _bypasses_central_throat(source: str) -> bool:
    """True＝图片腿走了「裸 urlopen / 未装中央逐跳护栏」的旁路形态。"""
    tree = ast.parse(source)
    has_raw_fetch_call = False
    has_build_opener_call = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in {"urlopen", "urlretrieve"}:
            has_raw_fetch_call = True
        elif name == "build_opener":
            has_build_opener_call = True
    references_central_handler = (
        "_GuardedShortLinkRedirectHandler" in source or "_GuardedRedirectHandler" in source
    )
    return bool(has_raw_fetch_call or not (has_build_opener_call and references_central_handler))


def _image_leg_source(module) -> str:
    """图片取字节那条腿的全部源码（取字节函数 + 其护栏 opener 工厂，若有）。"""
    parts = [inspect.getsource(module._fetch_image_bytes)]
    helper = getattr(module, "_guarded_image_opener", None)
    if helper is not None:
        parts.append(inspect.getsource(helper))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 合成形态（注毒腿/对照腿用）——与真身解耦，保证判据本身有牙
# --------------------------------------------------------------------------- #
_POISON_LEG_SRC = '''
def _fetch_image_bytes(url, max_bytes):
    import urllib.request
    from x.downloader import check_download_url
    try:
        check_download_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": "ua"})
        with urllib.request.urlopen(request, timeout=10) as response:
            final_url = response.geturl()
            check_download_url(final_url)
            data = response.read(max_bytes + 1)
    except Exception:
        return None
    return data
'''

_CORRECT_LEG_SRC = '''
import urllib.request


def _guarded_image_opener():
    from x.http_util import _GuardedShortLinkRedirectHandler
    return urllib.request.build_opener(_GuardedShortLinkRedirectHandler())


def _fetch_image_bytes(url, max_bytes):
    import urllib.request
    from x.downloader import RejectedUrlError, check_download_url
    from x.http_util import ParseHttpError
    try:
        check_download_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": "ua"})
        with _guarded_image_opener().open(request, timeout=10) as response:
            data = response.read(max_bytes + 1)
    except (RejectedUrlError, ParseHttpError):
        return None
    except Exception:
        return None
    if not data or len(data) > max_bytes:
        return None
    return data
'''


# --------------------------------------------------------------------------- #
# 离线假传输件（照搬已验证的 test_vision_image_ssrf_hop 纪律）
# --------------------------------------------------------------------------- #
class _FakeTransport(urlrequest.HTTPHandler):
    """假 HTTP 传输层：按路由表应答 30x/200，记账每个「真实会发出」的请求。

    内网落点故意不建路由——护栏被摘、请求真会发到此处时 http_open 抛 KeyError
    （记账已先落，正是本锁要的红灯证据）。
    """

    def __init__(self, routes: dict[str, tuple[int, str, bytes]]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def http_open(self, req):
        url = req.full_url
        self.requested.append(url)
        status, location, body = self.routes[url]
        headers = email.message.Message()
        if location:
            headers["Location"] = location
        response = addinfourl(io.BytesIO(body), headers, url, status)
        response.msg = "fake"
        return response


class _UrlopenTripwire:
    """把裸 urlopen 装成绊线：一旦被调即记账并抛出（绝不外发真网络）。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("裸 urlopen 被调用＝绕开中央逐跳护栏（F-G4 旁路）")


def _harden_offline(monkeypatch: pytest.MonkeyPatch, transport: _FakeTransport):
    """绊线化 urlopen + 给 build_opener 追加假传输层，护栏 handler 本体不 mock。

    生产 ``_guarded_image_opener`` 走 build_opener（被追加假传输件），逐跳护栏
    handler 的真实校验逻辑原样生效；摘掉护栏 handler，落点拒绝锁必红。裸 urlopen
    走绊线件，任何真网络出口被焊死。
    """
    trip = _UrlopenTripwire()
    monkeypatch.setattr(urlrequest, "urlopen", trip)
    real_build_opener = urlrequest.build_opener

    def wrapper(*handlers):
        return real_build_opener(*handlers, transport)

    monkeypatch.setattr(urlrequest, "build_opener", wrapper)
    return trip


# --------------------------------------------------------------------------- #
# 1) 形态锁：真实 notes 图片腿不得裸 urlopen，必须装中央逐跳护栏
# --------------------------------------------------------------------------- #
def test_notes_image_leg_wired_through_central_throat() -> None:
    src = _image_leg_source(N)
    assert not _bypasses_central_throat(src), (
        "F-G4：notes 图片 URL 腿必须复用中央逐跳护栏（build_opener + "
        "_GuardedShortLinkRedirectHandler），不得留裸 urlopen / 未复查的重定向旁路"
    )


# --------------------------------------------------------------------------- #
# 2) 装配锁：护栏 opener 工厂真的装着中央那枚 handler（非自造）
# --------------------------------------------------------------------------- #
def test_notes_image_leg_opener_actually_mounts_central_handler() -> None:
    helper = getattr(N, "_guarded_image_opener", None)
    assert helper is not None, (
        "F-G4：notes 需一个复用中央逐跳护栏的 opener 工厂 `_guarded_image_opener`"
    )
    opener = helper()
    assert any(
        isinstance(h, _GuardedShortLinkRedirectHandler) for h in opener.handlers
    ), "opener 必须装中央 _GuardedShortLinkRedirectHandler，不得另造第二套校验"


# --------------------------------------------------------------------------- #
# 3) 行为锁：逐跳落点在建连前过闸
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("landing", INTERNAL_LANDINGS)
def test_notes_image_leg_refuses_internal_redirect_landing(
    monkeypatch, landing
) -> None:
    """公网入口 30x → 内网/整型 IP 落点：那一跳绝不发出，且图片腿静默丢图。"""
    transport = _FakeTransport({_ENTRY: (302, landing, b"moved")})
    _harden_offline(monkeypatch, transport)

    assert N._fetch_image_bytes(_ENTRY, MAX_BYTES) is None
    assert transport.requested == [_ENTRY], (
        f"内网落点那一跳必须先过咽喉再建连，实测发出：{transport.requested}"
    )


def test_notes_image_leg_follows_public_redirect_chain(monkeypatch) -> None:
    """正向锁：公网入口 → 公网落点照旧取回字节（护栏不过度拦、正常链路契约不变）。"""
    transport = _FakeTransport(
        {
            _ENTRY: (302, _PUBLIC_LANDING, b"moved"),
            _PUBLIC_LANDING: (200, "", PNG_BODY),
        }
    )
    _harden_offline(monkeypatch, transport)

    assert N._fetch_image_bytes(_ENTRY, MAX_BYTES) == PNG_BODY
    assert transport.requested == [_ENTRY, _PUBLIC_LANDING]


def test_notes_image_leg_entry_internal_is_rejected(monkeypatch) -> None:
    """入口即内网：过不了中央咽喉，绝不建连（假传输件一条都不该记账）。"""
    transport = _FakeTransport({})
    trip = _harden_offline(monkeypatch, transport)

    assert N._fetch_image_bytes("http://127.0.0.1:8080/x.png", MAX_BYTES) is None
    assert transport.requested == []
    assert trip.calls == 0, "内网入口应被咽喉拒于建连前，不该退化到裸 urlopen"


# --------------------------------------------------------------------------- #
# 4) 反旁路锁：notes 不得定义第二套咽喉
# --------------------------------------------------------------------------- #
def test_notes_module_defines_no_second_ssrf_throat() -> None:
    src = Path(N.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^def check_download_url\(", src, re.MULTILINE), (
        "notes 不得自定义咽喉本体（唯一真身在 downloader）"
    )
    assert "getaddrinfo(" not in src, "notes 不得自做 DNS 解析判内网"
    assert not re.search(r"is_loopback|is_private|_ip_is_blocked", src), (
        "notes 不得复制私网/回环判定——一律委托中央 check_download_url"
    )
    assert "from plugins.bot_unified_runtime.domains.files.sources.downloader import" in src
    # 入口判定用的确实是中央那个函数对象，不是同名替身。
    assert _central_check_download_url.__module__.endswith("domains.files.sources.downloader")


# --------------------------------------------------------------------------- #
# 注毒腿 + 对照腿：判据本身有牙（与真身当前态无关，恒可跑）
# --------------------------------------------------------------------------- #
def test_detector_flags_bare_urlopen_poison() -> None:
    assert _bypasses_central_throat(_POISON_LEG_SRC), (
        "注毒腿：把图片腿换回裸 urlopen（HEAD 中毒态）时判据必须判越喉"
    )


def test_detector_passes_guarded_opener_shape() -> None:
    assert not _bypasses_central_throat(_CORRECT_LEG_SRC), (
        "对照腿：中央护栏 opener 形态必须放行，否则判据把正解也误杀＝空转假守卫"
    )


def test_urlopen_tripwire_catches_bypass(monkeypatch) -> None:
    """行为面注毒：真把 urlopen 绊线化后，若代码仍走裸 urlopen（中毒态）→ 绊线必触发。

    直接构造中毒调用，证明 ``_harden_offline`` 的绊线不是摆设。
    """
    transport = _FakeTransport({_ENTRY: (200, "", PNG_BODY)})
    trip = _harden_offline(monkeypatch, transport)
    with pytest.raises(AssertionError, match="裸 urlopen"):
        urlrequest.urlopen(urlrequest.Request(_ENTRY))
    assert trip.calls == 1


# --------------------------------------------------------------------------- #
# 落地腿（席位 S-FIX-NOTES-SSRF，2026-09-30）——只**增**锁，不动上面 8 枚判据：
# ① 护栏拒取与瞬时失败可分（否则「过不去的地址」会被瞒成「一时拿不到」）；
# ② 护栏拒绝之后不许找补第二条通路（裸 urlopen 绊线零触发）；
# ③ 拒取必须回人话（守岸人语气、给出路、不复述地址），公网正常链路不受扰；
# ④ 落点双查的写侧：穿越形态的 URL 也只能落在会话目录内。
# --------------------------------------------------------------------------- #
import hashlib
from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.notes.store import (
    notes_store as notes_store_mod,
)

_TRAVERSAL_ENTRY = "http://93.184.216.34/../../Windows/win.ini"


def _image_message(text: str, url: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="group:1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="1",
        plain_text=text,
        message_id="m-fg4",
        raw_segments=[{"type": "image", "data": {"url": url, "file": ""}}],
    )


def _wire_tmp_store(tmp_path, monkeypatch) -> SimpleNamespace:
    """图片根与两套库都指到 tmp（源码树 data/ 与生产 Runtime 零写入）。"""
    notes_store_mod.reset_stores_for_tests()
    monkeypatch.setattr(N, "_images_root", lambda _config: tmp_path / "imgs")
    return SimpleNamespace(
        bot_notes_db_path=str(tmp_path / "notes.sqlite3"),
        bot_reminder_db_path=str(tmp_path / "reminders.sqlite3"),
        bot_notes_max_per_chat=200,
    )


def test_guard_refusal_is_distinguishable_from_transient_failure(monkeypatch) -> None:
    """refusal 登记册：入口拒="entry"、落点拒="landing"、瞬时失败什么都不记。"""
    transport = _FakeTransport({_ENTRY: (302, INTERNAL_LANDINGS[0], b"moved")})
    _harden_offline(monkeypatch, transport)
    landing_refusal: list[str] = []
    assert N._fetch_image_bytes(_ENTRY, MAX_BYTES, refusal=landing_refusal) is None
    assert landing_refusal == ["landing"]

    entry_refusal: list[str] = []
    assert (
        N._fetch_image_bytes("http://169.254.169.254/latest/meta-data/", MAX_BYTES,
                             refusal=entry_refusal)
        is None
    )
    assert entry_refusal == ["entry"]

    # 公网判定成立、传输层没有这条路（＝瞬时失败）：护栏没开口，不该记任何拒因。
    transient = _FakeTransport({})
    _harden_offline(monkeypatch, transient)
    quiet: list[str] = []
    assert N._fetch_image_bytes(_ENTRY, MAX_BYTES, refusal=quiet) is None
    assert quiet == []


def test_guard_refusal_never_falls_back_to_second_throat(monkeypatch) -> None:
    """落点被护栏拒之后绝不许换裸 urlopen 找补：绊线零触发＝没有第二条通路。"""
    transport = _FakeTransport({_ENTRY: (302, "http://10.1.2.3/internal.png", b"moved")})
    trip = _harden_offline(monkeypatch, transport)
    assert N._fetch_image_bytes(_ENTRY, MAX_BYTES) is None
    assert trip.calls == 0, "护栏拒绝后退回裸 urlopen＝重开 F-G4 旁路"
    assert transport.requested == [_ENTRY]


def test_refused_image_is_told_in_human_words(tmp_path, monkeypatch) -> None:
    """入口内网：笔记照记，但缺的那张图如实说清并给出路；地址不进回话。"""
    cfg = _wire_tmp_store(tmp_path, monkeypatch)
    capability = N.build_notes_capability(cfg)
    result = capability(_image_message("笔记 记 一条", INTERNAL_LANDINGS[0]), object())

    assert "记下了" in result.body
    assert "没去取" in result.body, "护栏拒取被瞒成静默丢图＝不诚实回执"
    assert "内网" in result.body and "公网" in result.body, "要讲清边界在哪"
    assert "发给我" in result.body, "拒绝必须带出路，不能只说不行"
    assert "127.0.0.1" not in result.body and "10.1.2.3" not in result.body
    assert "image_guard_refused" in result.audit_tags
    # 文字没丢、图没落盘（拒绝发生在建连前，也没有半途文件）。
    from plugins.bot_unified_runtime.domains.notes.store.notes_store import (
        build_notes_store,
    )

    assert build_notes_store(cfg).list_notes("group:1"), "该记的文字仍要记上"
    assert not (tmp_path / "imgs").exists() or list((tmp_path / "imgs").rglob("*.png")) == []


def test_public_image_leg_reply_carries_no_refusal_hint(tmp_path, monkeypatch) -> None:
    """正向对照：公网链路照常落盘入库，回执不多一句（拒取话术不是万能前缀）。"""
    cfg = _wire_tmp_store(tmp_path, monkeypatch)
    transport = _FakeTransport({_ENTRY: (200, "", PNG_BODY)})
    _harden_offline(monkeypatch, transport)
    capability = N.build_notes_capability(cfg)
    result = capability(_image_message("笔记 记 一张图", _ENTRY), object())

    assert "附图 1 张" in result.body
    assert "没去取" not in result.body
    assert "image_guard_refused" not in result.audit_tags
    assert transport.requested == [_ENTRY]


def test_write_landing_stays_inside_session_dir(tmp_path, monkeypatch) -> None:
    """落点双查（写侧）：URL 路径带 ../ 也只落在会话目录内，文件名不含分隔符。"""
    _wire_tmp_store(tmp_path, monkeypatch)
    transport = _FakeTransport({_TRAVERSAL_ENTRY: (200, "", PNG_BODY)})
    _harden_offline(monkeypatch, transport)

    names, paths, blocked, refused = N._save_note_images(
        SimpleNamespace(), _image_message("笔记 记 穿越试试", _TRAVERSAL_ENTRY)
    )
    assert blocked is False and refused == 0
    assert len(names) == 1 and len(paths) == 1
    chat_dir = (
        tmp_path
        / "imgs"
        / hashlib.sha1(b"group:1").hexdigest()[:12]
    )
    for name, path in zip(names, paths):
        assert "/" not in name and "\\" not in name and ".." not in name
        resolved = Path(path).resolve()
        assert resolved.parent == chat_dir.resolve(), resolved
        assert resolved.is_file() and resolved.read_bytes() == PNG_BODY

