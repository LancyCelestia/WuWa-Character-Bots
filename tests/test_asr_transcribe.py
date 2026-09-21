"""语音转写（ASR）链路回归：record 段提取、registry 展平、转写与 mp3 预处理。

NapCat 时期的 record 段常带本机 nt_data 路径或过期 http URL；本文件锁定
extract_audio_source 的来源优先级、DynamicASRProvider 的故障转移语义
（失败返回空串、绝不阻断聊天）与 _prepare_audio 的 ffmpeg 转码行为。

E-13 口径：transcribe_audio 编排用例为 mock 路径（_prepare_audio 打桩，
docstring 逐例声明）；真实 ffmpeg 转码烟测在文件尾，由 BOT_ASR_SMOKE=1
门控（默认跳过，仅在有真实引擎环境跑极小样本，不联网）。
"""
from __future__ import annotations

import math
import os
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.media.ingest import transcribe
from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    DynamicASRProvider,
    _flatten_asr_entries,
    _prepare_audio,
    extract_audio_source,
    transcribe_audio,
)
from plugins.bot_unified_runtime.llm import LLMProviderError


def test_extract_audio_source_resolves_local_file_path(tmp_path: Path) -> None:
    audio = tmp_path / "Record" / "voice.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\x00\x01")
    source = extract_audio_source([{"type": "record", "data": {"file": audio.as_uri()}}])
    assert source == str(audio)


def test_extract_audio_source_plain_absolute_path_and_http(tmp_path: Path) -> None:
    audio = tmp_path / "plain.wav"
    audio.write_bytes(b"\x00\x01")
    local = extract_audio_source([{"type": "record", "data": {"file": str(audio)}}])
    assert local == str(audio)
    remote = extract_audio_source(
        [{"type": "record", "data": {"url": "https://multimedia.nt.qq.com/a.silk"}}]
    )
    assert remote == "https://multimedia.nt.qq.com/a.silk"


def test_extract_audio_source_prefers_local_over_http(tmp_path: Path) -> None:
    audio = tmp_path / "fresh.amr"
    audio.write_bytes(b"\x00\x01")
    source = extract_audio_source(
        [
            {
                "type": "record",
                "data": {
                    "url": "https://grouptalk.c2c.qq.com/?signed=1",
                    "file": str(audio),
                },
            }
        ]
    )
    # 本机落盘字节优先：NTQQ 媒体 URL 会过期且可能不可达。
    assert source == str(audio)


def test_extract_audio_source_unresolvable_returns_none() -> None:
    segments = [
        {"type": "record", "data": {"file": "missing.mp4"}},
        {"type": "record", "data": {"file": "Z:\\definitely\\missing\\x.amr"}},
        {"type": "record", "data": {"url": "not-a-url"}},
        {"type": "text", "data": {"text": "hi"}},
    ]
    assert extract_audio_source(segments) is None
    assert extract_audio_source(None) is None
    assert extract_audio_source([{"type": "image", "data": {"file": "a.png"}}]) is None


def test_flatten_asr_entries_single_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = {
        "main": {"model": "glm-asr", "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "plain"},
        "relay": [
            {"model": "whisper-1", "base_url": "https://a.example/v1", "api_key": "env:BOT_TEST_ASR_KEY"},
            {"model": "no-key", "base_url": "https://b.example/v1"},
        ],
    }
    monkeypatch.setenv("BOT_TEST_ASR_KEY", "sk-test-123")
    flattened = _flatten_asr_entries(registry, resolve_key=True)
    assert set(flattened) == {"main", "relay#1", "relay#2"}
    assert flattened["main"]["api_key"] == "plain"
    assert flattened["relay#1"]["api_key"] == "sk-test-123"
    # 缺 key 的条目仍保留（由 provider 侧判 config_missing），但 base_url/model 缺失直接丢弃。
    assert flattened["relay#2"]["api_key"] == ""


class _RecordingProvider:
    def __init__(self, result: str = "") -> None:
        self.result = result
        self.calls: list[tuple[bytes, str, float]] = []
        self.last_attempts: list[str] = []

    def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
        self.calls.append((audio_bytes, filename, float(kwargs.get("timeout_seconds", 0))))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_transcribe_audio_success_clips_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock 路径行为（E-13 声明）：_prepare_audio 打桩为假 mp3 字节，只验证
    transcribe_audio 编排语义（截断/临时目录清理）；真转码烟测见文件尾。"""
    seen_dirs: list[str] = []

    def fake_prepare(source: str, work_dir: str, *, timeout_seconds: float):
        seen_dirs.append(work_dir)
        return b"mp3-bytes", "audio.mp3"

    monkeypatch.setattr(transcribe, "_prepare_audio", fake_prepare)
    provider = _RecordingProvider(result="字" * 400)
    text = transcribe_audio(provider, audio_source="C:\\fake\\a.mp3", max_chars=300)
    assert len(text) == 300
    assert text.endswith("…")
    assert provider.calls[0][1] == "audio.mp3"
    # 转写临时目录用后即焚。
    assert seen_dirs and not Path(seen_dirs[0]).exists()


def test_transcribe_audio_prepare_failure_skips_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock 路径行为（E-13 声明）：打桩 _prepare_audio 返回 None，验证预处理
    失败时不触发 provider；真转码烟测见文件尾。"""
    monkeypatch.setattr(transcribe, "_prepare_audio", lambda *a, **k: None)
    provider = _RecordingProvider()
    assert transcribe_audio(provider, audio_source="x.silk") == ""
    assert provider.calls == []


def test_transcribe_audio_provider_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock 路径行为（E-13 声明）：_prepare_audio 与 provider 均为桩，验证
    LLMProviderError 被吞掉并返回空串。"""
    monkeypatch.setattr(
        transcribe,
        "_prepare_audio",
        lambda *a, **k: (b"mp3-bytes", "audio.mp3"),
    )
    provider = _RecordingProvider(
        result=LLMProviderError("boom", error_kind="auth")
    )
    provider.last_attempts = ["main:auth"]
    assert transcribe_audio(provider, audio_source="x.mp3") == ""


def test_transcribe_audio_unexpected_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock 路径行为（E-13 声明）：_prepare_audio 打桩，验证意外异常同样
    返回空串、不阻断聊天。"""
    monkeypatch.setattr(
        transcribe,
        "_prepare_audio",
        lambda *a, **k: (b"mp3-bytes", "audio.mp3"),
    )

    class _Boom(_RecordingProvider):
        def generate(self, *a: object, **k: object) -> str:
            raise RuntimeError("socket exploded")

    assert transcribe_audio(_Boom(), audio_source="x.mp3") == ""


def test_asr_provider_generate_failover_records_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = {
        "a": {"model": "m1", "base_url": "https://a.example", "api_key": "k1"},
        "b": {"model": "m2", "base_url": "https://b.example", "api_key": "k2"},
    }

    class _StubClient:
        def __init__(self, entries: dict[str, str]) -> None:
            self.entries = entries

        def post(self, url: str, **kwargs: object):
            entry = self.entries[url.split("/")[2]]

            class _Resp:
                def raise_for_status(self) -> None:
                    if entry == "fail":
                        raise _http_status_error(503)

                def json(self) -> dict:
                    return {"text": "  你好  "}

            return _Resp()

    def _http_status_error(status: int):
        import httpx

        request = httpx.Request("POST", "https://x/audio/transcriptions")
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError("err", request=request, response=response)

    stub = _StubClient({"a.example": "fail", "b.example": "ok"})
    monkeypatch.setattr(transcribe, "_find_ffmpeg_locate", lambda: "ffmpeg")
    provider = DynamicASRProvider(
        SimpleNamespace(bot_asr_model_registry=registry, bot_download_proxy="")
    )
    original_post = None
    import httpx

    original_post = httpx.post
    monkeypatch.setattr(httpx, "post", stub.post)
    try:
        text = provider.generate(b"audio", "audio.mp3", timeout_seconds=5.0)
    finally:
        httpx.post = original_post
    assert text == "你好"
    assert provider.last_attempts == ["a:server", "b:success"]


def test_asr_provider_is_enabled_settings_override() -> None:
    provider = DynamicASRProvider(
        SimpleNamespace(bot_asr_enabled=False),
        settings_store=SimpleNamespace(get_or=lambda key, default: True),
    )
    assert provider.is_enabled() is True
    fallback = DynamicASRProvider(
        SimpleNamespace(bot_asr_enabled=True),
        settings_store=SimpleNamespace(get_or=lambda key, default: default),
    )
    assert fallback.is_enabled() is True


@pytest.mark.skipif(
    not transcribe._find_ffmpeg_locate(), reason="ffmpeg not installed"
)
def test_prepare_audio_converts_wav_to_mp3_with_real_ffmpeg(
    tmp_path: Path,
) -> None:
    wav = tmp_path / "src.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        frames = bytearray()
        for index in range(16000):
            frames += struct.pack("<h", int(12000 * math.sin(index * 0.05)))
        handle.writeframes(bytes(frames))
    work = tmp_path / "work"
    work.mkdir()
    prepared = _prepare_audio(str(wav), str(work), timeout_seconds=60.0)
    assert prepared is not None
    audio_bytes, filename = prepared
    assert filename == "audio.mp3"
    assert audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb"
    assert 100 < len(audio_bytes) < 20_000_000


def test_prepare_audio_missing_source_and_download_failure_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 全部离线：下载失败用桩模拟，不触真网络。
    monkeypatch.setattr(transcribe, "_download_audio", lambda *a, **k: None)
    work = str(tmp_path / "work")
    missing = tmp_path / "nope.amr"
    assert _prepare_audio(str(missing), work, timeout_seconds=5.0) is None
    assert _prepare_audio("https://x.example/a.silk", work, timeout_seconds=5.0) is None


def test_prepare_audio_oversize_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcribe, "_MAX_AUDIO_BYTES", 10)
    big = tmp_path / "big.mp3"
    big.write_bytes(b"\xff\xfb" + b"\x00" * 64)
    assert _prepare_audio(str(big), str(tmp_path), timeout_seconds=5.0) is None


def test_extract_audio_source_prefers_transcoded_path(tmp_path: Path) -> None:
    transcoded = tmp_path / "transcoded.mp3"
    transcoded.write_bytes(b"\xff\xfb")
    original = tmp_path / "origin.silk"
    original.write_bytes(b"\x02#!SILK_V3")
    source = extract_audio_source(
        [
            {
                "type": "record",
                "data": {
                    "file": str(original),
                    "transcoded_path": str(transcoded),
                },
            }
        ]
    )
    assert source == str(transcoded)


def test_prepare_audio_silk_without_decoder_returns_none(tmp_path: Path) -> None:
    silk = tmp_path / "voice.slk"
    silk.write_bytes(b"\x02#!SILK_V3" + b"\x00" * 32)
    assert _prepare_audio(str(silk), str(tmp_path), timeout_seconds=5.0) is None


def test_transcode_record_segments_enriches_via_get_record(
    tmp_path: Path,
) -> None:
    import asyncio

    from plugins.bot_unified_runtime import _transcode_record_segments

    transcoded = tmp_path / "voice.mp3"
    transcoded.write_bytes(b"\xff\xfb")

    class _NapCat:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def call_api(self, action: str, **params):
            self.calls.append({"action": action, **params})
            return {"file": str(transcoded)}

    segments = [{"type": "record", "data": {"file": "abc.slk", "file_id": "fid-1"}}]
    bot = _NapCat()
    asyncio.run(_transcode_record_segments(bot, segments))
    assert bot.calls == [
        {"action": "get_record", "file_id": "fid-1", "out_format": "mp3"}
    ]
    assert segments[0]["data"]["transcoded_path"] == str(transcoded)


def test_transcode_record_segments_skips_convertible_and_failures(
    tmp_path: Path,
) -> None:
    import asyncio

    from plugins.bot_unified_runtime import _transcode_record_segments

    class _Boom:
        async def call_api(self, action: str, **params):
            raise RuntimeError("adapter refused")

    # 已是 mp3 本地文件：无需转码，不应调用 API。
    mp3 = tmp_path / "ok.mp3"
    mp3.write_bytes(b"\xff\xfb")
    convertible = [{"type": "record", "data": {"file": str(mp3)}}]
    asyncio.run(_transcode_record_segments(_Boom(), convertible))
    assert "transcoded_path" not in convertible[0]["data"]

    # 适配器拒绝（如非 NapCat 实现）：静默保持原段。
    silk_only = [{"type": "record", "data": {"file": "abc.slk", "file_id": "fid"}}]
    asyncio.run(_transcode_record_segments(_Boom(), silk_only))
    assert "transcoded_path" not in silk_only[0]["data"]

    # 转码返回不可识别后缀：不采纳。
    class _Bad:
        async def call_api(self, action: str, **params):
            return {"file": r"C:\tmp\out.unknown"}

    bad = [{"type": "record", "data": {"file": "abc.slk", "file_id": "fid"}}]
    asyncio.run(_transcode_record_segments(_Bad(), bad))
    assert "transcoded_path" not in bad[0]["data"]


# ==================== E-13 真转码烟测（默认跳过，BOT_ASR_SMOKE=1 启用） ====================
@pytest.mark.skipif(
    os.environ.get("BOT_ASR_SMOKE", "") != "1",
    reason="真转码烟测默认跳过（BOT_ASR_SMOKE=1 启用）",
)
@pytest.mark.skipif(
    not transcribe._find_ffmpeg_locate(), reason="ffmpeg not installed"
)
def test_transcribe_audio_real_transcode_smoke(tmp_path: Path) -> None:
    """E-13 真链路烟测：不打桩 _prepare_audio——1 秒静音 wav 经真实 ffmpeg
    转码流过 transcribe_audio 全链（provider 用离线桩，不联网），补上
    mock 用例覆盖不到的真实预处理段。"""
    wav = tmp_path / "smoke.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)  # 恰 1 秒静音。

    seen: list[tuple[bytes, str]] = []

    class _StubProvider:
        def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
            seen.append((audio_bytes, filename))
            return "字" * 400

    text = transcribe_audio(
        _StubProvider(), audio_source=str(wav), timeout_seconds=60.0
    )
    # 编排语义与 mock 用例同口径：文本截断到 300 字、省略号收尾。
    assert len(text) == 300
    assert text.endswith("…")
    # 真实 ffmpeg 产物：mp3 头（ID3 或 MPEG 帧同步），绝非打桩假字节。
    assert seen, "provider 未收到音频：真转码链路未走通"
    audio_bytes, filename = seen[0]
    assert filename == "audio.mp3"
    assert audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb"
    assert 100 < len(audio_bytes) < 20_000_000
