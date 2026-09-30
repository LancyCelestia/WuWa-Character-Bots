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

__all__ = ["media_digest", "media_digest_file", "media_md5"]


def media_digest(data: bytes) -> str:
    """媒体字节内容摘要唯一算法：sha256 全长 64 hex 小写。"""
    return hashlib.sha256(data).hexdigest()


def media_md5(data: bytes) -> str:
    """表情库 ``md5`` 主键的唯一算法口（S-MEME-POOLSCAN，2026-09-29）。

    为什么中央件要长这张脸：``domains/meme`` 的库行主键历史上就是 **md5**（群聊吸收腿、
    离线导入脚本、库内 ``exists``/``remove`` 全按它对齐）。新增一条扫池腿时若在本地写
    ``hashlib.md5(image_bytes)``，就会踩中 ``tests/test_media_identity_single_source_ratchet.py``
    的「非中央件媒体身份实现」上限——那道门的原话是「禁第二份**实现**」，不是「禁 md5
    这个键」。所以把 md5 也收进同一个咽喉：值与手抄逐字节相同（跨腿去重不受影响），
    而全仓「媒体字节→哈希」的算法面仍然只住 ``domains/media/digest.py`` 这一处。

    它**不**替换 ``media_digest``：sha256 仍是内容身份（发送史/隔离墓碑用它）；md5 只是
    库行的历史主键形态。两把尺各答各的问题，别混。

    已知欠款（不属本件）：``domains/meme/sources/meme_library_listener.py`` 仍内联手抄
    一枚（该门 ``KNOWN_DEBT`` 在册，上限 1）。迁到本函数即可摘牌，但那要同时降棘轮数字，
    归该门业主席处置，本席不代改。
    """
    return hashlib.md5(data).hexdigest()


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
