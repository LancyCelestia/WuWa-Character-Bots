"""音频腿 SSRF 逐跳落点复查 + 咽喉拒绝不外透的回归锁。

出处：.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-SSRF.md 调用点表 #11；
SEAT-ATKFIX-SSRF1.md §6 把「transcribe 音频腿」登记为未做边界。本席（S-ATKFIX-SSRF2）
现算坐实：SSRF1 在图片腿修的两类缺陷在音频腿**都不存在**，并以活锁固定——

1. 入口 ``check_download_url``：明确拒绝即丢音（返回 None），绝不进任何兜底；
2. 逐跳落点复查：httpx ``request`` 事件钩子（``_guard_hop``）在**每一跳发出前**
   再过中央咽喉——公网入口 302→内网落点时，内网那一跳绝不发出；
3. 咽喉拒音后 provider 只可能收到「字节」：本模块从不把原始 URL 透传给 ASR
   provider（与图片腿 F-2「拒绝→原 URL 透传给会自取的本机 provider」结构性不同）。

全离线纪律：monkeypatch ``httpx.Client`` 为假件，忠实模拟 ``follow_redirects`` 逐跳
语义——每一跳「发出」前先跑生产注册的 request 事件钩子，钩子内 ``check_download_url``
抛 ``RejectedUrlError`` 即中止、绝不记账为已发出；入口/落点全用字面量 IP
（93.x 公网、127.0.0.1/169.254.169.254 内网）走咽喉离线判定，零 DNS、零真网络。
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import httpx
import pytest

from plugins.bot_unified_runtime.domains.media.ingest import transcribe as T

# 字面量公网 IP（咽喉按字面量放行，零 DNS）与内网/元数据落点。
_ENTRY = "http://93.184.216.34/voice.mp3"
_PUBLIC_LANDING = "http://93.184.216.35/real.mp3"
_INTERNAL_LANDING = "http://127.0.0.1:9/secret"
_METADATA_LANDING = "http://169.254.169.254/latest"
_PRIVATE_ENTRY = "http://169.254.169.254/l"
# 302 后落点为非法协议（判据层必拒的三形态；零示范面见席报 SEAT-ATK-SSRF-LOCKS.md
# 追加三问 #3）。公网主机（8.8.8.8）两枚**只被协议白名单拦住**——摘掉
# ``_ALLOWED_SCHEMES`` 那一步即穿；无主机的 ``file://`` 另有「缺少主机名」兜底，
# 注毒归因在席报里分开记账。
_ILLEGAL_SCHEME_LANDINGS = [
    "file:///C:/Windows/win.ini",
    "gopher://8.8.8.8:11211/_probe",
    "dict://8.8.8.8:11211/x",
]


class _Req:
    """httpx ``Request`` 替身：钩子只用到 ``str(request.url)``。"""

    def __init__(self, url: str) -> None:
        self.url = url


class _Resp:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    def iter_bytes(self, chunk_size: int | None = None):
        if self._body:
            yield self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, script: dict[str, tuple]):
    """把 ``httpx.Client`` 替身为忠实逐跳假件。

    ``script``: url -> ("redirect", location) | ("body", bytes)。钩子（生产的
    ``_guard_hop``）在记账「这一跳已发出」之前运行——若咽喉抛错，该跳不记账、
    异常上抛被 ``_download_audio`` 的 ``except Exception`` 吞成 None（丢音）。
    返回 ``(sent, built)``：sent=真正「发出」的 URL 序，built=Client 构造次数。
    """
    sent: list[str] = []
    built: list[dict] = []

    class _StreamCtx:
        def __init__(self, client: _FakeClient, url: str) -> None:
            self._c = client
            self._url = url

        def __enter__(self) -> _Resp:
            url = self._url
            seen: set[str] = set()
            while True:
                for hook in self._c._hooks:  # 发请求前跑逐跳咽喉
                    hook(_Req(url))
                sent.append(url)  # 钩子放行 = 这一跳真会发出
                spec = self._c._script.get(url)
                if spec is None:
                    return _Resp(404, b"")
                kind = spec[0]
                if kind == "redirect":
                    location = str(spec[1])
                    if self._c._follow and location and location not in seen:
                        seen.add(url)
                        url = location
                        continue
                    return _Resp(302, b"")
                if kind == "body":
                    return _Resp(200, bytes(spec[1]))
                return _Resp(404, b"")

        def __exit__(self, *exc: object) -> bool:
            return False

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            built.append(dict(kwargs))
            self._hooks = (kwargs.get("event_hooks") or {}).get("request", [])
            self._follow = kwargs.get("follow_redirects") is True
            self._script = script

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCtx:
            return _StreamCtx(self, str(url))

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return sent, built


def test_audio_entry_rejected_before_any_request(tmp_path: Path, monkeypatch) -> None:
    """入口咽喉明确拒绝：``_download_audio`` 直接返回 None——连 httpx 客户端都不建。"""
    dest = tmp_path / "src.mp3"
    sent, built = _install_fake_httpx(monkeypatch, {})
    assert T._download_audio(_PRIVATE_ENTRY, dest, timeout_seconds=5.0) is None
    assert built == [], "内网入口不得建客户端"
    assert sent == [] and not dest.exists()


def test_audio_redirect_to_internal_landing_never_sent(
    tmp_path: Path, monkeypatch
) -> None:
    """逐跳主锁：公网入口 302→内网落点——内网那一跳发出前即被咽喉拒，绝不发出。

    RED 反证（钩子被摘的回归）：若生产 ``_guard_hop`` 事件钩子被删，落点将记账为
    「已发出」（sent 含内网）——本锁即红。当前音频腿有钩子，故为绿（锁定既有正确）。
    """
    dest = tmp_path / "src.mp3"
    script = {_ENTRY: ("redirect", _INTERNAL_LANDING)}
    sent, _built = _install_fake_httpx(monkeypatch, script)
    assert T._download_audio(_ENTRY, dest, timeout_seconds=5.0) is None
    assert sent == [_ENTRY], "只有入口这一跳发出，内网落点零连接"
    assert _INTERNAL_LANDING not in sent
    assert not dest.exists()


def test_audio_redirect_to_metadata_landing_never_sent(
    tmp_path: Path, monkeypatch
) -> None:
    """落点=云元数据面：与回环同级，逐跳复查在建连前拒掉。"""
    dest = tmp_path / "src.mp3"
    script = {_ENTRY: ("redirect", _METADATA_LANDING)}
    sent, _built = _install_fake_httpx(monkeypatch, script)
    assert T._download_audio(_ENTRY, dest, timeout_seconds=5.0) is None
    assert sent == [_ENTRY] and _METADATA_LANDING not in sent


@pytest.mark.parametrize("landing", _ILLEGAL_SCHEME_LANDINGS)
def test_audio_redirect_to_illegal_scheme_landing_never_sent(
    tmp_path: Path, monkeypatch, landing: str
) -> None:
    """逐跳落点=非法协议（302→file/gopher/dict）：与内网落点同判据、同一时机拦下。

    加固出处：SEAT-ATK-SSRF-LOCKS.md 追加三问 #3——判据层必拒、六锁零示范。吃的是
    与 ``_guard_hop`` 同一份逐跳记账：钩子被摘、或协议判定被放宽时，这一跳会记进
    ``sent``（本假件忠实模拟 httpx：非 http scheme 的 Location 照样回调 request 钩子）
    → 本锁当场红。
    """
    dest = tmp_path / "src.mp3"
    script = {_ENTRY: ("redirect", landing)}
    sent, _built = _install_fake_httpx(monkeypatch, script)
    assert T._download_audio(_ENTRY, dest, timeout_seconds=5.0) is None
    assert sent == [_ENTRY], f"非法协议落点被记账为已发出：{landing}"
    assert landing not in sent
    assert not dest.exists()


def test_audio_public_redirect_fetches_bytes(tmp_path: Path, monkeypatch) -> None:
    """正向锁：公网入口→公网落点照旧取回字节写盘（咽喉不过度拦、契约不变）。"""
    dest = tmp_path / "src.mp3"
    script = {
        _ENTRY: ("redirect", _PUBLIC_LANDING),
        _PUBLIC_LANDING: ("body", b"AUDIO-BYTES"),
    }
    sent, _built = _install_fake_httpx(monkeypatch, script)
    assert T._download_audio(_ENTRY, dest, timeout_seconds=5.0) is dest
    assert sent == [_ENTRY, _PUBLIC_LANDING]
    assert dest.read_bytes() == b"AUDIO-BYTES"


def test_transcribe_rejected_source_never_reaches_provider() -> None:
    """F-2 类比缺席锁：入口被拒→转写整链返回空，provider 一次都不被调（无 URL 透传通道）。"""

    class _RecordingProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[bytes, str]] = []

        def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
            self.calls.append((audio_bytes, filename))
            return "绝不该出现"

    provider = _RecordingProvider()
    assert T.transcribe_audio(provider, audio_source=_PRIVATE_ENTRY) == ""
    assert provider.calls == [], "被拒音频不得空跑 provider，更不得把 URL 交给它"
