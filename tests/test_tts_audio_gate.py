"""引擎返回字节的「音频体检」闸（bot.tts，M-06 P1 / M-37 部分，2026-09-19 修复波 S9）。

审计实证（`report-T29.md` M-06、`report-T4.md` P0-1、`report-T19.md` E、`report-T8.md`）：
- 旧成功判据 = **HTTP 200 且字节非空**，随后**不校验即写 `.wav`、即入缓存、即发**；
- 引擎侧存在「yield 静音 + 单个 next 吞 raise」的形态（`TTS.py:1516-1527`）⇒
  **200 + 约 1 秒静音**是真会发生的，另有非音频字节（反代 HTML/JSON 错误体）同形；
- 缓存只验 `is_file` 不验内容 ⇒ 毒件在**进程存活期**被同句复放。

换件后果升级（`report-T46.md` 2026-09-19 复判决）：QQ 端由 NapCat 换成 **SnowLuma**
后，**坏 record 段是 fatal（整条消息一字不发）**，不再是 NapCat 的「丢段留文字」
（`index.mjs:4285-4287`，全树唯一丢段出口只给 `reply`）。因此「把不可播的字节送去发」
的代价从「静默没声」变成「连累同条消息的文字」。

本闸的边界（诚实划线）：
- **只判结构**（RIFF/WAVE 魔数 + 可解析 + 帧数>0 + 时长>0）；
- **不判时长上限**——QQ 语音条时长红线属真机未定项（U-02），拿估出来的秒数硬拦
  会把正常长回复误杀，故只把测得时长写进原因串供取证，不设阈值。
全离线，零网络零落盘（落盘只写 tmp_path）。
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    RefAudio,
    TtsParams,
    synthesize,
)


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav 字节（GPT-SoVITS `media_type=wav` 的产物形态）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _params() -> TtsParams:
    return TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "_CACHE", __import__("collections").OrderedDict())
    # 退避时刻一并隔离：M-09 接线后它被 synthesize 的健康闸真实读取。
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes):
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_kw: (payload, ""))
    ref = RefAudio(path=str(tmp_path / "ref.wav"), text="你好", lang="zh")
    out = tmp_path / "out"
    return synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=out,
    ), out


def test_valid_wav_passes_gate_and_lands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (path, reason), _out = _run(tmp_path, monkeypatch, _wav_bytes())
    assert path is not None and reason == ""
    assert path.read_bytes().startswith(b"RIFF")


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        (b"<html><body>502 Bad Gateway</body></html>", "非 RIFF/WAVE"),
        (b'{"message": "tts failed", "Exception": "boom"}', "非 RIFF/WAVE"),
        (_wav_bytes(seconds=0), "零帧"),
        (b"not audio at all", "非 RIFF/WAVE"),
    ],
)
def test_non_audio_bytes_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, needle: str
) -> None:
    (path, reason), out = _run(tmp_path, monkeypatch, payload)
    assert path is None
    assert "音频体检失败" in reason
    assert needle in reason
    assert not out.exists() or not list(out.glob("*.wav")), "不可播字节绝不允许落盘"


def test_poison_artifact_never_enters_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒件被拒后不得入内存缓存：下一句同文本仍会真打引擎（不留复放捷径）。"""
    calls: list[str] = []

    def _fake_request(**_kw: object) -> tuple[bytes, str]:
        calls.append("hit")
        return b"garbage-not-audio", ""

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    ref = RefAudio(path=str(tmp_path / "ref.wav"), text="你好", lang="zh")
    for _ in range(2):
        path, _reason = synthesize(
            api_url="http://127.0.0.1:9880",
            text="正文",
            ref=ref,
            params=_params(),
            output_dir=tmp_path / "out",
        )
        assert path is None
    assert calls == ["hit", "hit"]


def test_rejection_maps_to_non_retryable_issue() -> None:
    """体检失败必须是**不可重试**的新 kind：重打引擎只会拿回同一份坏字节。"""
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    message = IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id="",
        plain_text="说 你好",
    )
    issue = tts_mod._failure_issue(message, "音频体检失败：非 RIFF/WAVE 字节")
    assert issue.kind == "tts_bad_audio"
    assert issue.retryable is False
    assert issue.safe_summary.startswith("tts_bad_audio")
