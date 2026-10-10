"""语音转写（ASR）链路回归：record 段提取、registry 展平、转写与 mp3 预处理。

NapCat 时期的 record 段常带本机 nt_data 路径或过期 http URL；本文件锁定
extract_audio_source 的来源优先级、DynamicASRProvider 的故障转移语义
（失败返回空串、绝不阻断聊天）与 _prepare_audio 的 ffmpeg 转码行为。

E-13 口径：transcribe_audio 编排用例为 mock 路径（_prepare_audio 打桩，
docstring 逐例声明）；真实 ffmpeg 转码烟测在文件尾，由 BOT_ASR_SMOKE=1
门控（默认跳过，仅在有真实引擎环境跑极小样本，不联网）。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
import struct
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
)
from plugins.bot_unified_runtime.domains.media.ingest import transcribe
from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    DynamicASRProvider,
    _flatten_asr_entries,
    _prepare_audio,
    extract_audio_source,
    transcribe_audio,
)


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


# ==================== 同层并发化（2026-10-11 席位 R，根链摄取段）================
# 待删的无用功：``_transcode_record_segments`` 对一条消息里的多枚 record 段逐段
# ``await bot.call_api("get_record", ...)``（单段上限 20s）。段与段**互不依赖**——
# 每段只写自己的 ``data["transcoded_path"]``，零共享可变状态，也没有"下一段的
# file_id 要从上一段回执里读"这种结构依赖。改法＝先按原序判完"要不要发"（纯同步），
# 再并发发起，最后按原序逐段回填。
# 🔴 单段 20s 上限一字未动（``test_record_transcode_20s_ceiling_is_untouched``
# 用 AST 现算钉死）；不新增配置键。
#
# 四类腿：① 段数组**逐字段相等**（同一份源对象 deepcopy 出两路输入）；② 墙钟 A/B；
# ③ 失败段"保持原样"＋日志逐条同序；④ 注毒（把"要不要发"挪进回调）⇒ 多余调用锁真红。


async def _serial_reference_transcode(bot: object, raw_segments: list[dict]) -> None:
    """**改前（串行）实现的逐字转写**——差分腿的参照尺，勿改（改了这条尺就废了）。

    转写自 2026-10-11 改动前的 ``_transcode_record_segments``（基线副本
    ``$TEMP/seatR-init-baseline.py`` :1272-1303 段）：四道跳过门、``wait_for``
    的 20s、失败分支与后缀采纳判据一字未动；只把失败日志收进
    ``_serial_reference_transcode_logs`` 以便逐条对序。
    """
    from pathlib import Path as _Path

    from plugins.bot_unified_runtime import _RECORD_CONVERTIBLE_SUFFIXES

    global _serial_reference_transcode_logs
    _serial_reference_transcode_logs = []

    for segment in raw_segments:
        if str(segment.get("type", "")).lower() != "record":
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict) or data.get("transcoded_path"):
            continue
        local = str(data.get("file") or data.get("path") or "").strip()
        suffix = _Path(local).suffix.lower() if local else ""
        if suffix in _RECORD_CONVERTIBLE_SUFFIXES:
            continue
        file_id = str(data.get("file_id") or data.get("file") or "").strip()
        if not file_id:
            continue
        try:
            result = await asyncio.wait_for(
                bot.call_api("get_record", file_id=file_id, out_format="mp3"),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001
            _serial_reference_transcode_logs.append(f"get_record skipped type={type(exc).__name__}")
            continue
        transcoded = str((result or {}).get("file") or "").strip()
        if transcoded and _Path(transcoded).suffix.lower() in _RECORD_CONVERTIBLE_SUFFIXES:
            data["transcoded_path"] = transcoded


_serial_reference_transcode_logs: list[str] = []


class _DelayRecordBot:
    """每枚 get_record 钉死延迟的假适配器（不触网、不落盘），记发起序与在飞峰值。"""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        result_file: str = r"C:\fake\out.mp3",
        errors: dict[str, Exception] | None = None,
        bad_suffix_ids: tuple[str, ...] = (),
    ) -> None:
        self.delay = delay
        self.result_file = result_file
        self.errors = errors or {}
        self.bad_suffix_ids = bad_suffix_ids
        self.calls: list[tuple[str, dict]] = []
        self.inflight = 0
        self.max_inflight = 0

    async def call_api(self, action: str, **params):
        self.calls.append((action, params))
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self.inflight -= 1
        file_id = str(params.get("file_id", ""))
        error = self.errors.get(file_id)
        if error is not None:
            raise error
        if file_id in self.bad_suffix_ids:
            return {"file": r"C:\fake\out.unknown"}
        return {"file": self.result_file}

    @property
    def fetched_file_ids(self) -> list[str]:
        return [str(params["file_id"]) for _action, params in self.calls]


def _build_record_segments(tmp_path) -> list[dict]:
    """一份覆盖全部门的合成段数组：待转码 5 枚 + 各类"不该发"的段各若干。"""
    mp3 = tmp_path / "already.mp3"
    mp3.write_bytes(b"\xff\xfb")
    return [
        {"type": "text", "data": {"text": "旁路文本段"}},
        {"type": "record", "data": {"file": "a.slk", "file_id": "fid-a"}},
        {"type": "record", "data": {"file": str(mp3)}},  # ffmpeg 能解：不发
        {"type": "record", "data": {"file": "b.slk", "file_id": "fid-b"}},
        {
            "type": "record",
            "data": {"file": "c.slk", "file_id": "fid-c", "transcoded_path": r"C:\fake\done.mp3"},
        },  # 已转码：不发
        {"type": "record", "data": {"path": "d.slk", "file_id": "fid-d"}},
        {"type": "record", "data": {"file": "e.slk"}},  # 无 file_id：file 兜底当 id，照样发
        {"type": "record", "data": {"file": "f.slk", "file_id": "fid-f"}},
        {"type": "record", "data": {}},  # 空 data＝既无 file 也无 path：不发
        {"type": "image", "data": {"file": "g.slk", "file_id": "fid-g"}},  # 非 record：不发
    ]


def _skipped_debug_logs(caplog, mark: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records[mark:]
        if r.getMessage().startswith("get_record skipped type=")
    ]


def test_concurrent_transcode_is_field_identical_to_serial_reference(tmp_path, caplog) -> None:
    """🔴 核心实证：并发版与改前串行版产出的**段数组逐字段相等**。

    两路喂的是同一份源数组派生的两份深拷贝（拷贝前现算两者与源全等，防止
    "输入本来就不同"糊住这条尺），比四件事：段数组整体、被反查的 file_id
    **集合**、失败段是否原样（无 ``transcoded_path``）、debug 日志逐条同序同文。
    """
    from plugins.bot_unified_runtime import _transcode_record_segments
    source = _build_record_segments(tmp_path)
    serial_input = copy.deepcopy(source)
    concurrent_input = copy.deepcopy(source)
    assert serial_input == source and concurrent_input == source, "两路输入并非同一份"

    result_path = str(tmp_path / "conv.mp3")
    serial_bot = _DelayRecordBot(result_file=result_path)
    concurrent_bot = _DelayRecordBot(result_file=result_path)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(_serial_reference_transcode(serial_bot, serial_input))
        serial_logs = list(_serial_reference_transcode_logs)
        mark = len(caplog.records)
        asyncio.run(_transcode_record_segments(concurrent_bot, concurrent_input))
        concurrent_logs = _skipped_debug_logs(caplog, mark)

    # ① 段数组逐字段相等（dict == 递归比每个键；含拼接落点 transcoded_path）
    assert concurrent_input == serial_input, (
        f"段数组不等\nserial   ={serial_input}\nconcurrent={concurrent_input}"
    )
    # ② 反查集合与次数一致（并发不许多发/少发）
    assert sorted(concurrent_bot.fetched_file_ids) == sorted(serial_bot.fetched_file_ids)
    assert len(concurrent_bot.calls) == len(serial_bot.calls)
    # ③ 回填位置一致：段 1/3/5/6/7 该发（含 data 里只有 file、被当 file_id 用的段 6），
    #    其余四类门（可解后缀 / 已转码 / 空 data / 非 record）一律原样。
    #    只数"新写入＝回执路径"的那些，别把段 4 的既有值算进来。
    filled = [
        i for i, seg in enumerate(concurrent_input)
        if seg.get("data", {}).get("transcoded_path") == result_path
    ]
    assert filled == [1, 3, 5, 6, 7], f"回填位置漂移：{filled}"
    assert concurrent_input[2]["data"] == {"file": str(tmp_path / "already.mp3")}
    assert concurrent_input[4]["data"]["transcoded_path"] == r"C:\fake\done.mp3"
    # ④ 调用形状（动作名与两个入参）逐条一致
    assert concurrent_bot.calls == serial_bot.calls
    assert concurrent_logs == serial_logs


def test_concurrent_transcode_keeps_failed_segments_verbatim(tmp_path, caplog) -> None:
    """失败段"保持原样"分支：抛错的段不许被写脏，且日志文本与**次序**与串行版全等。"""
    from plugins.bot_unified_runtime import _transcode_record_segments
    errors = {"fid-b": RuntimeError("adapter refused"), "fid-f": TimeoutError()}
    result_path = str(tmp_path / "conv.mp3")
    source = _build_record_segments(tmp_path)
    serial_input = copy.deepcopy(source)
    concurrent_input = copy.deepcopy(source)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(_serial_reference_transcode(_DelayRecordBot(result_file=result_path, errors=errors), serial_input))
        serial_logs = list(_serial_reference_transcode_logs)
        mark = len(caplog.records)
        asyncio.run(
            _transcode_record_segments(
                _DelayRecordBot(result_file=result_path, errors=errors), concurrent_input
            )
        )
        concurrent_logs = _skipped_debug_logs(caplog, mark)

    assert concurrent_input == serial_input
    assert concurrent_input[3]["data"] == {"file": "b.slk", "file_id": "fid-b"}, "失败段被写脏"
    assert "transcoded_path" not in concurrent_input[7]["data"]
    assert concurrent_logs == serial_logs == [
        "get_record skipped type=RuntimeError",
        "get_record skipped type=TimeoutError",
    ]


def test_concurrent_transcode_rejects_unknown_suffix_like_serial(tmp_path) -> None:
    """转码回执后缀不可采纳时：两路都不写 transcoded_path（采纳判据未动）。"""
    from plugins.bot_unified_runtime import _transcode_record_segments

    source = _build_record_segments(tmp_path)
    serial_input = copy.deepcopy(source)
    concurrent_input = copy.deepcopy(source)
    # 这份输入里会被反查的 file_id 全集（段 6 无 file_id，file 兜底成 "e.slk"）。
    bad = ("fid-a", "fid-b", "fid-d", "fid-f", "e.slk")

    serial_bot = _DelayRecordBot(bad_suffix_ids=bad)
    concurrent_bot = _DelayRecordBot(bad_suffix_ids=bad)
    asyncio.run(_serial_reference_transcode(serial_bot, serial_input))
    asyncio.run(_transcode_record_segments(concurrent_bot, concurrent_input))

    assert concurrent_input == serial_input
    assert concurrent_bot.fetched_file_ids == serial_bot.fetched_file_ids
    # 唯一还带 transcoded_path 的 record 段＝进来就已经有的那段（下标 4）。
    still = [
        i for i, seg in enumerate(concurrent_input)
        if seg["type"] == "record" and "transcoded_path" in seg["data"]
    ]
    assert still == [4], f"不可采纳的后缀被写进了段数组：{still}"
    assert concurrent_input[4]["data"]["transcoded_path"] == r"C:\fake\done.mp3"


def test_concurrent_transcode_wall_clock_collapses_n_rtts(tmp_path) -> None:
    """墙钟 A/B：每枚 get_record 钉 30ms，串行 N×RTT → 并发 1×RTT（不触网）。"""
    from plugins.bot_unified_runtime import _transcode_record_segments
    rtt = 0.03
    result_path = str(tmp_path / "conv.mp3")
    fids = [f"fid-{i}" for i in range(5)]
    segments_src = [{"type": "record", "data": {"file": f"{f}.slk", "file_id": f}} for f in fids]

    serial_input = copy.deepcopy(segments_src)
    serial_bot = _DelayRecordBot(delay=rtt, result_file=result_path)
    t0 = time.perf_counter()
    asyncio.run(_serial_reference_transcode(serial_bot, serial_input))
    serial_wall = time.perf_counter() - t0

    concurrent_input = copy.deepcopy(segments_src)
    concurrent_bot = _DelayRecordBot(delay=rtt, result_file=result_path)
    t0 = time.perf_counter()
    asyncio.run(_transcode_record_segments(concurrent_bot, concurrent_input))
    concurrent_wall = time.perf_counter() - t0

    assert concurrent_input == serial_input
    assert concurrent_bot.fetched_file_ids == fids, "发起序＝段的原序"
    assert concurrent_bot.max_inflight == 5, f"没有并发：峰值在飞={concurrent_bot.max_inflight}"
    ratio = serial_wall / concurrent_wall
    print(
        f"[wallclock records N=5] rtt={rtt * 1000:.0f}ms serial={serial_wall * 1000:.0f}ms "
        f"concurrent={concurrent_wall * 1000:.0f}ms ratio={ratio:.2f}x inflight={concurrent_bot.max_inflight}"
    )
    assert ratio > 2.5, f"墙钟没塌下来 ratio={ratio:.2f}"


def test_transcode_issues_no_extra_api_calls() -> None:
    """预算不放大锁：只有"该发"的段才被反查——四道跳过门一枚都不许多发一次。

    同层并发只改"何时发"，不改"发几枚"。下面这 7 枚段里只有 3 枚需要
    get_record（fid-a / fid-d / fid-e）：可解后缀、已转码、拿不到可用 id、
    非 record 四类门各拦住一枚。
    """
    from plugins.bot_unified_runtime import _transcode_record_segments
    segments = [
        {"type": "record", "data": {"file": "a.slk", "file_id": "fid-a"}},
        {"type": "record", "data": {"file": "ok.mp3", "file_id": "fid-mp3"}},
        {"type": "record", "data": {"file": "b.slk", "file_id": "fid-b", "transcoded_path": r"C:\x\y.mp3"}},
        {"type": "record", "data": {"type_only": True}},
        {"type": "record", "data": {"file": "d.slk", "file_id": "fid-d"}},
        {"type": "video", "data": {"file": "v.slk", "file_id": "fid-v"}},
        {"type": "record", "data": {"file": "e.slk", "file_id": "fid-e"}},
    ]
    bot = _DelayRecordBot()
    asyncio.run(_transcode_record_segments(bot, segments))
    assert bot.fetched_file_ids == ["fid-a", "fid-d", "fid-e"], bot.fetched_file_ids
    assert len(bot.calls) == 3


async def _poison_should_we_fetch_moved_into_callback(bot: _DelayRecordBot, raw_segments: list[dict]) -> None:
    """注毒变体：形状照并发版，但把"要不要发"的门挪进**回调里**判。

    发起时不判门 ⇒ 每一条 record 段（含 ffmpeg 本就能解的、已转码的、没有
    file_id 的）都会先打一次 get_record。只为 ``test_no_extra_call_lock_has_teeth``
    服务，真身里没有这段逻辑（内存内造违规，绝不写盘）。
    """
    from pathlib import Path as _Path

    from plugins.bot_unified_runtime import _RECORD_CONVERTIBLE_SUFFIXES

    async def _one(segment: dict) -> None:
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            return
        # 🔴 门被挪到回调里：下面这次 call_api 发起时一行门都没判。
        file_id = str(data.get("file_id") or data.get("file") or "").strip() or "NO-ID"
        result = await bot.call_api("get_record", file_id=file_id, out_format="mp3")
        if str(data.get("file") or "").lower().endswith(tuple(sorted(_RECORD_CONVERTIBLE_SUFFIXES))):
            return
        transcoded = str((result or {}).get("file") or "").strip()
        if transcoded and _Path(transcoded).suffix.lower() in _RECORD_CONVERTIBLE_SUFFIXES:
            data["transcoded_path"] = transcoded

    await asyncio.gather(*(_one(s) for s in raw_segments if str(s.get("type", "")).lower() == "record"))


def test_no_extra_call_lock_has_teeth_against_callback_side_poison() -> None:
    """量尺自证：把"要不要发"挪进回调 ⇒ 同一份输入必多发调用，那把锁当场真红。"""
    from plugins.bot_unified_runtime import _transcode_record_segments
    segments = [
        {"type": "record", "data": {"file": "a.slk", "file_id": "fid-a"}},
        {"type": "record", "data": {"file": "ok.mp3", "file_id": "fid-mp3"}},
        {"type": "record", "data": {"file": "b.slk", "file_id": "fid-b", "transcoded_path": r"C:\x\y.mp3"}},
        {"type": "record", "data": {"type_only": True}},
        {"type": "record", "data": {"file": "d.slk", "file_id": "fid-d"}},
    ]
    poisoned = _DelayRecordBot()
    asyncio.run(_poison_should_we_fetch_moved_into_callback(poisoned, copy.deepcopy(segments)))
    assert len(poisoned.calls) > 2, f"注毒未破多余调用门（{len(poisoned.calls)} 次）⇒ 锁是瞎的"

    real = _DelayRecordBot()
    asyncio.run(_transcode_record_segments(real, copy.deepcopy(segments)))
    assert [i for i in real.fetched_file_ids] == ["fid-a", "fid-d"]


def test_record_transcode_20s_ceiling_is_untouched() -> None:
    """天花板原值锁（AST 现算，不写行号）：``_transcode_record_segments`` 里
    ``asyncio.wait_for`` 的 timeout 字面量必须仍是 20.0，且 ``get_record``
    调用仍住在该函数子树内（``outbound_registry`` 的 ``::_transcode_record_segments:get_record``
    符号锚靠它撑着）。
    """
    import ast
    from pathlib import Path as _Path

    import plugins.bot_unified_runtime as _pkg

    source = _Path(_pkg.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_transcode_record_segments"
    )
    timeouts: list[float] = []
    get_record_calls = 0
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "wait_for":
            for kw in node.keywords:
                if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                    timeouts.append(float(kw.value.value))
        tail = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if tail == "call_api" and node.args and getattr(node.args[0], "value", None) == "get_record":
            get_record_calls += 1
    assert timeouts == [20.0], f"单段超时被改动：{timeouts}"
    assert get_record_calls == 1, f"get_record 调用腿被挪出真身函数：{get_record_calls}"


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
