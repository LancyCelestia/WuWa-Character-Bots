"""T120 S2：合成产物内容摘要挂上 bot.tts 出站 audio 部件（M-64 最后一环）。

蓝图：``docs/design/media-digest-layer.md`` §3.3（S2 行）+ report-T109 §五衔接清单。
出站键规约「消息身份 ∧ 段类型 ∧ 内容摘要」的合成侧半句：``CapabilityResult.audio``
部件随件携带落盘字节的 sha256（``content_sha256``，64 hex 小写全长，U-107-A 口径），
经渲染收口（S3 第三冻结键）随 worker 段级键自动下行，传输层零改动。

锁四面：

1. **命令路 + 自动路 + 缓存命中路**三形态都携带 digest，且与落盘字节
   ``media_digest`` 全等（禁造假值——摘要必须来自真实产物字节）；
2. digest 计算失败（读不到/OSError/异常注入）→ 部件**不带键**、出站链不炸
   （诚实降级，与渲染收口 S3 缺省退化咬合）；
3. 形态=64 hex 小写全长（``media_digest_file`` 真值，非截短）。

施工位（T109 §五）：``tts.py`` 两处 audio 构造（锚 :1067/:1426 一带）+
digest 获取缝；本文件零触碰 digest.py/renderer.py/transport。
"""

from __future__ import annotations

import io
import re
import wave
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import CapabilityResult
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.digest import media_digest

_API = "http://127.0.0.1:9880"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _config(**overrides: object) -> SimpleNamespace:
    """最小配置对象（口径同 test_tts._config；output_dir 恒指 tmp 隔离区）。"""
    base: dict[str, object] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": _API,
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": "data/tts_output",
        "bot_tts_max_chars": 200,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
        "bot_tts_cache_enabled": True,
        "bot_tts_auto_reply_enabled": False,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_probability": 0.05,
        "bot_tts_auto_reply_always": False,
        "bot_tts_preset": "shorekeeper",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str) -> object:
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id=None,
        plain_text=text,
    )


def _ref_file(tmp_path: Path, name: str = "ref.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav 字节（能过 _inspect_wav_bytes 体检闸的夹具）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _ref_config(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    ref = _ref_file(tmp_path, "ref.wav")
    return _config(
        bot_tts_ref_audios=[f"{ref}|你好|zh"],
        bot_tts_output_dir=str(tmp_path / "out"),
        **overrides,
    )


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """进程级缓存/退避态隔离（口径同 test_tts._isolate_cache）。"""
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


def _fake_engine(audio: bytes):
    def _request(**_kwargs: object) -> tuple[bytes, str]:
        return audio, ""

    return _request


# ---------------------------------------------------------------------------
# 1. 携带面：命令路 / 自动路 / 缓存命中路
# ---------------------------------------------------------------------------


def test_command_path_audio_part_carries_content_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令路：audio 部件带 content_sha256，且与落盘字节 media_digest 全等。"""
    audio = _wav_bytes()
    monkeypatch.setattr(tts_mod, "_request_tts", _fake_engine(audio))
    capability = tts_mod.build_tts_capability(_ref_config(tmp_path))

    result = capability(_msg("说 今天的潮汐很安静"), None)  # type: ignore[operator]

    assert result.audio, "正常合成应带语音部件"
    part = result.audio[0]
    persisted = tmp_path / "out"
    files = sorted(persisted.glob("tts-*.wav"))
    assert len(files) == 1, "合成产物应落盘恰一个 wav"
    assert part["content_sha256"] == media_digest(files[0].read_bytes()), (
        "部件 digest 必须与落盘字节全等（禁造假值）"
    )
    assert part["content_sha256"] == media_digest(audio), "落盘字节=引擎产物字节"
    assert _DIGEST_RE.fullmatch(part["content_sha256"]), "64 hex 小写全长"


def test_auto_reply_path_audio_part_carries_content_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """自动配音路（maybe_attach_voice 构造点，锚 :1426）：同语义同全等。"""
    audio = _wav_bytes()
    monkeypatch.setattr(tts_mod, "_request_tts", _fake_engine(audio))
    original = CapabilityResult(
        request_id="req-1",
        capability_id="bot.chat",
        kind="text",
        body="今天的潮汐很安静。",
    )
    patched = tts_mod.maybe_attach_voice(
        _msg("在吗"),  # type: ignore[arg-type]
        original,
        config=_ref_config(tmp_path, bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True),
    )

    assert patched.audio, "自动配音应带上语音部件"
    part = patched.audio[0]
    files = sorted((tmp_path / "out").glob("tts-*.wav"))
    assert len(files) == 1
    assert part["content_sha256"] == media_digest(files[0].read_bytes())
    assert part["content_sha256"] == media_digest(audio)
    assert original.audio == [], "原结果不应被就地修改"


def test_cache_hit_path_carries_same_content_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存命中路（bytes 不在内存）也必须携带同一 digest——M-64 覆盖主路径。

    同句两次：第一次真合成落盘，第二次命中进程缓存复用同一路径；两次出站
    部件的 digest 必须一致且等于落盘字节摘要。
    """
    audio = _wav_bytes()
    engine_calls: list[str] = []

    def _request(**_kwargs: object) -> tuple[bytes, str]:
        engine_calls.append("hit")
        return audio, ""

    monkeypatch.setattr(tts_mod, "_request_tts", _request)
    capability = tts_mod.build_tts_capability(_ref_config(tmp_path))

    first = capability(_msg("说 同一句"), None)  # type: ignore[operator]
    second = capability(_msg("说 同一句"), None)  # type: ignore[operator]

    assert engine_calls == ["hit"], "第二次应命中缓存不再打服务"
    files = sorted((tmp_path / "out").glob("tts-*.wav"))
    assert len(files) == 1, "缓存命中复用同一路径（单文件语义）"
    expected = media_digest(files[0].read_bytes())
    assert first.audio and first.audio[0]["content_sha256"] == expected
    assert second.audio and second.audio[0]["content_sha256"] == expected


# ---------------------------------------------------------------------------
# 2. 诚实降级面：digest 计算失败 → 部件不带键、出站链不炸
# ---------------------------------------------------------------------------


def test_digest_unreadable_omits_key_without_breaking_outbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """media_digest_file 返 None（OSError 语义，U-107-B 缺即缺）→ 部件无第三键。

    与渲染收口 S3 的缺省退化咬合：无键部件走恰两键老路，全链零感知。
    （S2 前 media_digest_file 尚未入 tts 命名空间，raising=False 允许
    补丁先于接缝存在——本例为兼容根锁，改动前后语义一致。）
    """
    monkeypatch.setattr(tts_mod, "_request_tts", _fake_engine(_wav_bytes()))
    monkeypatch.setattr(tts_mod, "media_digest_file", lambda *_a, **_k: None, raising=False)
    capability = tts_mod.build_tts_capability(_ref_config(tmp_path))

    result = capability(_msg("说 正文"), None)  # type: ignore[operator]

    assert result.audio, "digest 缺失绝不吞件：音频部件保命"
    part = result.audio[0]
    assert "content_sha256" not in part, "算不出 digest 就不带键，禁静默造假值"
    assert part["file"] and part["review_text"]


def test_digest_exception_omits_key_without_bubbling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """digest 计算炸异常（非 OSError 族）→ 同样吞为缺键，绝不让能力面冒泡。"""
    monkeypatch.setattr(tts_mod, "_request_tts", _fake_engine(_wav_bytes()))

    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("digest boom")

    monkeypatch.setattr(tts_mod, "media_digest_file", _boom, raising=False)
    capability = tts_mod.build_tts_capability(_ref_config(tmp_path))

    result = capability(_msg("说 正文"), None)  # type: ignore[operator]

    assert result.audio, "digest 异常不阻断出站（fail-open，宁缺勿假）"
    assert "content_sha256" not in result.audio[0]
