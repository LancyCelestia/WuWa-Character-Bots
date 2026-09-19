"""中央媒体摘要层——媒体字节内容摘要唯一真身（S-08 / Wave H，席位 T109）。

蓝图：``docs/design/media-digest-layer.md`` §3.1（T107 方案件，零施工先例）。
规约三条（蓝图钉死）：

- **单一算法**：sha256 全长 64 hex 小写；截短是**消费侧**决定（如出站键内
  ``[:16]``，U-107-A 口径），算法本身不截短——全局去重/跨库对账可互查。
- **单一入口**：全仓媒体字节哈希只准经此件；禁再造
  ``hashlib.sha256(media_bytes)`` 手抄（D4 审计原意；media_archive 归档去重
  的收编为消费点，另立批次不在本件最小面）。
- **不裁决可播性**：本件只答「字节是什么」，「字节能不能播」归
  ``tts._inspect_wav_bytes`` 族质检闸（S-08 质检席另立）；两件同域不同责，
  禁合并成上帝件。

纯函数零包内依赖零 IO（``media_digest_file`` 流式变体除外）；消费点唯一=
渲染收口 ``canonicalize_audio_parts``（domains/render/renderer.py，第三冻结
键 ``content_sha256`` 已于 T109 S3 转正）。

**S2 预留调用契约（合成落盘点挂 digest 免费，交下一席施工；本席不动
tts.py）**：``domains/media/capabilities/tts.py`` ``synthesize`` 落盘点
``target.write_bytes(audio)``（tts.py:760 读码锚点，随树漂移以符号为准）
同点 ``digest = media_digest(audio)``——bytes 已在内存，零第二次读盘
（bot_tts_max_audio_bytes 顶 8MB ⇒ <10ms，相对秒级合成可忽略）；随后两处
audio 构造（tts.py:1067/:1426 读码锚点）``[{"file": str(path),
"review_text": speech}]`` 增第三键 ``"content_sha256": digest`` 即可——
渲染收口/worker 段级键/onebot 白名单全链自动随行，传输层零改动。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["media_digest", "media_digest_file"]


def media_digest(data: bytes) -> str:
    """媒体字节内容摘要唯一算法：sha256 全长 64 hex 小写。"""
    return hashlib.sha256(data).hexdigest()


def media_digest_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str | None:
    """流式摘要（1MB chunk 迭代 ``update``，O(1) 内存）。

    供未来非内存面（质检闸/归档/审计）使用；读不到/OSError → ``None``
    （调用方决定降级语义，本件不吞、更不补算——U-107-B 口径：缺即缺）。
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(chunk_size), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
