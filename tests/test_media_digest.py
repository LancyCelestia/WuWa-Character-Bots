"""中央媒体摘要层回归（S-08 / Wave H 席位 T109，蓝图 docs/design/media-digest-layer.md §3.1）。

S1 中央件三条规约（蓝图钉死，测试逐一锁）：

- 单一算法：``media_digest`` = sha256 全长 64 hex 小写；截短是消费侧决定，
  算法本身不截短（全局去重/跨库对账可互查）。
- 单一入口：全仓媒体字节哈希只准经此件（禁再造 ``hashlib.sha256(media_bytes)``
  手抄，D4 审计原意；media_archive 收编另立批次）。
- 不裁决可播性：本件只答「字节是什么」，「字节能不能播」归
  ``_inspect_wav_bytes`` 族质检闸（S-08 另席）；两件同域不同责。

``media_digest_file`` 流式变体：1MB chunk 迭代（O(1) 内存），供未来非内存面
（质检/归档）使用；读不到/OSError → None（调用方决定降级语义，本件不吞）。

S2 预留调用契约（蓝图 §3.3-1，本席只留注释不动 tts.py）：合成落盘点
``target.write_bytes(audio)`` 同点 ``media_digest(audio)``（bytes 已在内存，
零读盘）→ audio item 增 ``"content_sha256": digest``；渲染收口
``canonicalize_audio_parts``（T109 S3 已转正第三冻结键）自动随行。

全离线零网络零包内依赖（纯函数，file 变体只碰 tmp_path）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from plugins.bot_unified_runtime.domains.media.digest import (
    media_digest,
    media_digest_file,
)


def test_media_digest_matches_sha256_full_length() -> None:
    """唯一真身：与 hashlib.sha256 全长 hexdigest 恒等（64 hex 小写）。"""
    assert media_digest(b"x") == hashlib.sha256(b"x").hexdigest()
    digest = media_digest(b"")
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_media_digest_different_bytes_different_digest() -> None:
    """内容寻语义：不同字节 ⇒ 不同摘要（同字节 ⇒ 同摘要）。"""
    assert media_digest(b"same") == media_digest(b"same")
    assert media_digest(b"a") != media_digest(b"b")


def test_media_digest_not_truncated() -> None:
    """算法本身不截短：截短是消费侧（键内 [:16]）决定（U-107-A 口径）。"""
    assert media_digest(b"truncation-probe") == hashlib.sha256(
        b"truncation-probe"
    ).hexdigest()
    assert len(media_digest(b"truncation-probe")) == 64


def test_media_digest_file_streaming_equals_oneshot(tmp_path: Path) -> None:
    """流式与一次性等值：跨多 chunk（>1MB）逐块 update 与全量 sha256 恒等。"""
    data = bytes(range(256)) * 8192  # 2 MiB，跨 ≥2 个 1MB chunk
    path = tmp_path / "stream.wav"
    path.write_bytes(data)
    assert media_digest_file(path) == media_digest(data)
    assert media_digest_file(path) == hashlib.sha256(data).hexdigest()


def test_media_digest_file_custom_chunk_size_same_digest(tmp_path: Path) -> None:
    """chunk_size 只是吞吐参数：改小不改摘要值。"""
    data = b"chunk-size-probe" * 1000
    path = tmp_path / "chunked.wav"
    path.write_bytes(data)
    assert media_digest_file(path, chunk_size=7) == media_digest(data)


def test_media_digest_file_missing_returns_none(tmp_path: Path) -> None:
    """缺文件 → None（调用方决定降级语义，本件不吞不补算）。"""
    assert media_digest_file(tmp_path / "nope.wav") is None


def test_media_digest_file_directory_returns_none(tmp_path: Path) -> None:
    """OSError 面（目录不可 read）→ None，不逃异常。"""
    assert media_digest_file(tmp_path) is None


def test_media_digest_accepts_path_and_str(tmp_path: Path) -> None:
    """path 入参 str|Path 双形态（蓝图签名口径）。"""
    path = tmp_path / "both.wav"
    path.write_bytes(b"both-forms")
    assert media_digest_file(str(path)) == media_digest(b"both-forms")
    assert media_digest_file(path) == media_digest(b"both-forms")
