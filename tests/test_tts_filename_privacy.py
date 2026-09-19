"""M-39 产物文件名去内容指纹锁（Wave H 席 T101）。

历史事实（report-T97.md M-39 行 / report-T39.md H-5）：落盘名曾是
``f"{cache_key}.wav"``，而 ``cache_key = sha256(preimage + SEED_RULE_VERSION)[:20]``、
preimage 明文含 text 全文 + ref.text + 参数快照——拿到盘上文件名（或 DB request_json
里的路径键）即可离线字典反推「哪句话被合成过」。

本文件锁死修复后的隐私语义（T101 施工口径）：

- **盘上文件名与内容指纹无确定映射**（uuid4 随机名，非 text/preimage 的函数）；
- **缓存身份逻辑零改动**：内存键仍内容寻址（同键命中同一路径=显式单文件语义），
  缓存未命中/关闭时同文本两次合成→盘上两个不同名文件，孤儿回收靠中央配额
  （M-27/T61 已接线，``enforce_quota``）。
"""

from __future__ import annotations

import hashlib
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


def _params(**overrides: object) -> TtsParams:
    base: dict[str, object] = {
        "text_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.9,
        "top_k": 15,
        "top_p": 1.0,
        "text_split_method": "cut5",
    }
    base.update(overrides)
    return TtsParams(**base)  # type: ignore[arg-type]


def _ref_file(tmp_path: Path, name: str = "ref.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav 字节（能过 M-06 体检闸，夹具惯例同 tests/test_tts.py）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * int(seconds * rate))
    return buf.getvalue()


def _install_fake_engine(
    monkeypatch: pytest.MonkeyPatch, audio: bytes | None = None
) -> None:
    monkeypatch.setattr(
        tts_mod,
        "_request_tts",
        lambda **_kwargs: ((audio if audio is not None else _wav_bytes()), ""),
    )


def _content_fingerprint_candidates(text: str, ref: RefAudio, params: TtsParams) -> set[str]:
    """从 text/ref/params 可离线推导的一切指纹候选（修复前文件名必命中其一）。"""
    ref_text = f"{ref.path}|{ref.text}|{ref.lang}"
    payload = (
        f"{tts_mod.IDENTITY_VERSION}|http://127.0.0.1:9880|{ref_text}|"
        f"{params.text_lang}|{params.speed_factor}|{text}"
    )
    preimage = f'{{"identity_version": {tts_mod.IDENTITY_VERSION}, "text": "{text}"}}'
    return {
        tts_mod._cache_key(text, ref, params, api_url="http://127.0.0.1:9880", preset_id="shorekeeper"),
        hashlib.sha256(text.encode("utf-8")).hexdigest()[:20],
        hashlib.sha256((text + ref.text).encode("utf-8")).hexdigest()[:20],
        hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20],
        hashlib.sha256(preimage.encode("utf-8")).hexdigest()[:20],
    }


def test_filename_not_derivable_from_content_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘文件名不得是 text/preimage 的任何可推导指纹（M-39 核心锁）。"""
    _install_fake_engine(monkeypatch)
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="参考文本甲", lang="zh")
    text = "这句私密文本不该被文件名出卖"
    path, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text=text,
        ref=ref,
        params=_params(),
        output_dir=tmp_path / "out",
        cache_enabled=False,
    )
    assert path is not None and reason == ""
    stem = path.stem
    candidates = _content_fingerprint_candidates(text, ref, _params())
    assert stem not in candidates, f"文件名仍是内容指纹：{stem}"
    assert len(stem) != 20, "20 hex 定长名=旧缓存键形态，必须换代"
    assert text not in stem and ref.text not in stem


def test_same_text_cache_disabled_writes_distinct_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存关闭时同文本两次合成→两个不同名文件（随机名语义；修复前同名互覆）。"""
    _install_fake_engine(monkeypatch)
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    out = tmp_path / "out"
    names: list[str] = []
    for _ in range(2):
        path, _reason = synthesize(
            api_url="http://127.0.0.1:9880",
            text="同一句话",
            ref=ref,
            params=_params(),
            output_dir=out,
            cache_enabled=False,
        )
        assert path is not None
        names.append(path.name)
    assert names[0] != names[1], "随机名语义下两次落盘不得同名"
    assert len(list(out.glob("*.wav"))) == 2


def test_cache_hit_keeps_single_file_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存身份零改动的正面锁：同键命中同一路径，盘上恒一个文件、只打一次服务。"""
    calls: list[str] = []
    audio = _wav_bytes()

    def _fake_request(**_kwargs: object) -> tuple[bytes, str]:
        calls.append("hit")
        return audio, ""

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    out = tmp_path / "out"
    first, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text="同一句话",
        ref=ref,
        params=_params(),
        output_dir=out,
    )
    assert first is not None and reason == ""
    second, _reason2 = synthesize(
        api_url="http://127.0.0.1:9880",
        text="同一句话",
        ref=ref,
        params=_params(),
        output_dir=out,
    )
    assert second == first, "缓存命中必须复用同一路径（单文件语义）"
    assert calls == ["hit"]
    assert len(list(out.glob("*.wav"))) == 1


def test_cache_key_derivation_untouched_by_rename(
    tmp_path: Path,
) -> None:
    """文件名随机化不许波及缓存键算法：键仍=20 hex 且对 preimage 稳定。"""
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="甲", lang="zh")
    key_a = tts_mod._cache_key(
        "正文", ref, _params(), api_url="http://127.0.0.1:9880/", preset_id="shorekeeper"
    )
    key_b = tts_mod._cache_key(
        "正文", ref, _params(), api_url="http://127.0.0.1:9880", preset_id="shorekeeper"
    )
    assert key_a == key_b  # 尾斜杠归一（T57 基线）不回归
    assert len(key_a) == 20 and all(ch in "0123456789abcdef" for ch in key_a)
