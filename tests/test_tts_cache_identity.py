"""缓存键身份维度（bot.tts，M-11 P1，2026-09-19 统一波 T57）。

审计实证（`report-T29.md` M-11）：`_cache_key` 只含「请求参数快照」
（text / ref 路径 / ref 文本 / 采样参数），不含「被请求的那台引擎、那份素材
**此刻**是什么」——
- 换 api_url（换引擎地址 / 引擎回退底模再恢复）后，同句永久命中旧音色 wav；
- 原地重录 ref 文件（路径不变、内容变）后，同句永久命中旧音色 wav。

本席修法（按现状实现；契约层规格席 T54/G-2 可能产出更好的键算法，收编点见
report-T57.md）：
- 键补 ``api_url`` 段（``rstrip('/')`` 归一：尾斜杠不算换引擎）；
- 键补 ``ref_fp`` 段：ref 文件内容指纹——**首次读取做 sha256**，之后只 stat 比
  ``(size, mtime)``，一致即沿用指纹（避免每次合成全文件哈希），stat 变了才重算
  （真实现场「原地换文件」必然更新 mtime）；
- **已知边界（写死进用例）**：内容变而 size+mtime 都不变（如 touch 回写旧时间戳）
  检测不到——为它每次全文件哈希不划算，按设计接受；
- 键空间换代副作用：旧键生成的 wav 文件名全部失配成为孤儿（落盘目录回收归
  M-27 配额闸，不在本席）。

全离线，零网络零落盘（落盘只写 tmp_path）。
"""

from __future__ import annotations

import io
import os
import wave
from collections import OrderedDict
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    RefAudio,
    TtsParams,
    synthesize,
)

_API_A = "http://127.0.0.1:9880"
_API_B = "http://127.0.0.1:9999"


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav（能过音频体检闸的产物形态）。"""
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
    """每条用例干净 LRU 索引。

    指纹缓存（``_REF_FINGERPRINTS``）按路径键控、pytest tmp_path 每用例唯一，
    不存在跨用例同路径串味，无需重置；同 stat 换内容的边界用例各自独占路径。
    """
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())


def _ref(tmp_path: Path, name: str = "ref.wav", content: bytes = b"RIFF....WAVEfmt ") -> RefAudio:
    path = tmp_path / name
    path.write_bytes(content)
    return RefAudio(path=str(path), text="你好", lang="zh")


def test_cache_key_differs_by_api_url(tmp_path: Path) -> None:
    """换引擎地址 = 换身份：同句同素材同参数也不得共用同一份旧音色缓存。"""
    ref = _ref(tmp_path)
    key_a = tts_mod._cache_key("正文", ref, _params(), api_url=_API_A)
    key_b = tts_mod._cache_key("正文", ref, _params(), api_url=_API_B)
    assert key_a != key_b


def test_trailing_slash_api_url_is_same_engine(tmp_path: Path) -> None:
    """尾斜杠不是换引擎：``http://h:9880`` 与 ``http://h:9880/`` 必须同键。"""
    ref = _ref(tmp_path)
    key_a = tts_mod._cache_key("正文", ref, _params(), api_url=_API_A)
    key_b = tts_mod._cache_key("正文", ref, _params(), api_url=f"{_API_A}/")
    assert key_a == key_b


def test_cache_key_differs_when_ref_content_changes(tmp_path: Path) -> None:
    """原地重录 ref（路径不变、内容变）= 换素材：旧键必须失配。"""
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF-first-take-bytes")
    ref = RefAudio(path=str(path), text="你好", lang="zh")
    first = tts_mod._cache_key("正文", ref, _params(), api_url=_API_A)

    stat_before = path.stat()
    path.write_bytes(b"RIFF-second-take-voice!")
    # 显式把 mtime 拨到原值之后，杜绝同秒写入 mtime 撞车的偶现假绿。
    os.utime(path, (stat_before.st_atime, stat_before.st_mtime + 5.0))
    second = tts_mod._cache_key("正文", ref, _params(), api_url=_API_A)
    assert first != second, "ref 内容变了键却没变 = 永久命中旧音色（M-11 本体）"


def test_cache_key_still_differs_by_ref_path(tmp_path: Path) -> None:
    """回归守卫：路径与内容指纹都参与键——两份不同素材不得互撞。"""
    ref_a = _ref(tmp_path, "a.wav", b"RIFF-voice-take-A")
    ref_b = _ref(tmp_path, "b.wav", b"RIFF-voice-take-B")
    key_a = tts_mod._cache_key("正文", ref_a, _params(), api_url=_API_A)
    key_b = tts_mod._cache_key("正文", ref_b, _params(), api_url=_API_A)
    assert key_a != key_b


def test_same_stat_content_change_is_documented_boundary(tmp_path: Path) -> None:
    """边界锁：内容变而 size+mtime 都不变时，按设计沿用旧指纹（键不变）。

    stat 快路径是 M-11 修法里「避免每次合成全文件哈希」的承重结构：真实现场
    原地换文件必然更新 mtime，只有 touch 回写旧时间戳这类刻意构造才探测不到。
    若未来改成每次全文件哈希，本用例会转红——那是有意为之的规格变更信号。
    """
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF-AAAA-take-one")
    stat_before = path.stat()
    first = tts_mod._cache_key("正文", RefAudio(path=str(path), text="你好"), _params(), api_url=_API_A)

    path.write_bytes(b"RIFF-BBBB-take-two")  # 同长度换内容
    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))  # 还原 stat
    second = tts_mod._cache_key("正文", RefAudio(path=str(path), text="你好"), _params(), api_url=_API_A)
    assert first == second, "size+mtime 未变时必须走指纹快路径（性能约束的锁）"


def test_synthesize_engine_and_ref_identity_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端：换引擎地址 / 原地换 ref 内容都要真重合成，且新键缓存照常工作。"""
    seen_urls: list[str] = []

    def _fake_request(**kwargs: object) -> bytes:
        url = str(kwargs.get("api_url", ""))
        seen_urls.append(url)
        return _wav_bytes(rate=44100 if url.endswith("9880") else 8000)

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    ref_path = tmp_path / "ref.wav"
    ref_path.write_bytes(b"RIFF-take-one-bytes")
    ref = RefAudio(path=str(ref_path), text="你好", lang="zh")
    out = tmp_path / "out"

    p1, r1 = synthesize(
        api_url=_API_A, text="正文", ref=ref, params=_params(), output_dir=out
    )
    p2, r2 = synthesize(
        api_url=_API_B, text="正文", ref=ref, params=_params(), output_dir=out
    )
    assert p1 is not None and p2 is not None and r1 == "" and r2 == ""
    assert p1 != p2, "换引擎地址后同句不得命中旧引擎的 wav"
    assert len(seen_urls) == 2, "换引擎地址必须真重合成，不得吃旧键缓存"

    p3, _r3 = synthesize(
        api_url=_API_B, text="正文", ref=ref, params=_params(), output_dir=out
    )
    assert p3 == p2 and len(seen_urls) == 2, "新键自身的缓存命中必须照常工作"

    # 原地换 ref 内容（mtime 必然更新）→ 旧键失配，重新合成。
    stat_before = ref_path.stat()
    ref_path.write_bytes(b"RIFF-take-two-bytes!")
    os.utime(ref_path, (stat_before.st_atime, stat_before.st_mtime + 5.0))
    p4, _r4 = synthesize(
        api_url=_API_A, text="正文", ref=ref, params=_params(), output_dir=out
    )
    assert p4 is not None and p4 != p1, "原地换 ref 内容后不得命中旧素材的 wav"
    assert len(seen_urls) == 3
