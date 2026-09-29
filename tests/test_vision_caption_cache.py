"""VLM 图片描述缓存行为锁（席位 MM-VIS-1 配对锁，2026-09-30）。

锁四条硬语义（判据真身 = modules 头注释，这里只钉行为）：
1. 命中省推理：put 后同键 lookup 返回描述（同一张图第二次进来零 VLM 调用）。
2. TTL 过期即未命中，且过期行就地删。
3. 缓存坏了绝不拖垮识图：坏库路径 lookup/put 全部静默降级（fail-open）。
4. 内容身份只走中央件且一票否决：取不到字节的 ref ⇒ 整批不建键（空串）；
   顺序不同＝不同的批（少一张图就是另一个键）。
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.media.registry.vision_caption_cache import (
    VisionCaptionCache,
    build_vision_caption_cache,
    caption_key_for_image_refs,
    caption_key_for_messages,
    image_ref_digest,
    reset_vision_caption_cache_for_tests,
)


def _png_bytes(color: bytes) -> bytes:
    """最小 PNG 形态字节（内容身份只看 sha256，格式不参与判据）。"""
    return b"\x89PNG\r\n\x1a\n" + color + b"tail"


def _data_url(payload: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


@pytest.fixture(autouse=True)
def _reset_instances():
    reset_vision_caption_cache_for_tests()
    yield
    reset_vision_caption_cache_for_tests()


def test_put_then_lookup_hits_and_overwrites(tmp_path: Path) -> None:
    cache = VisionCaptionCache(tmp_path / "cap.sqlite3")
    cache.put("a" * 64, "第一版描述", model="glm-4.6v")
    assert cache.lookup("a" * 64) == "第一版描述"
    cache.put("a" * 64, "第二版描述", model="glm-4.6v")
    assert cache.lookup("a" * 64) == "第二版描述"


def test_ttl_expiry_drops_row(tmp_path: Path) -> None:
    import time

    cache = VisionCaptionCache(tmp_path / "cap.sqlite3", ttl_seconds=0.05)
    cache.put("b" * 64, "转瞬即逝")
    assert cache.lookup("b" * 64) == "转瞬即逝"
    time.sleep(0.08)
    assert cache.lookup("b" * 64) is None
    # 过期行就地删：库里不再有该键。
    with sqlite3.connect(str(tmp_path / "cap.sqlite3")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vision_caption").fetchone()[0] == 0


def test_broken_db_fails_open(tmp_path: Path) -> None:
    # db_path 指向一个目录 ⇒ 连接必炸；语义＝"没有缓存"，绝不抛。
    cache = VisionCaptionCache(tmp_path / "not-a-db-dir")
    assert cache.lookup("c" * 64) is None
    cache.put("c" * 64, "写不进去也不许炸")
    assert cache.evict_expired() == 0


def test_empty_key_or_caption_is_noop(tmp_path: Path) -> None:
    cache = VisionCaptionCache(tmp_path / "cap.sqlite3")
    cache.put("", "无键")
    cache.put("d" * 64, "")
    cache.put("d" * 64, "   ")
    assert cache.lookup("") is None
    assert cache.lookup("d" * 64) is None


def test_caption_hard_cap_truncates(tmp_path: Path) -> None:
    cache = VisionCaptionCache(tmp_path / "cap.sqlite3")
    cache.put("e" * 64, "长" * 5000)
    got = cache.lookup("e" * 64)
    assert got is not None and len(got) <= 4000 and got.endswith("…")


def test_image_ref_digest_content_identity(tmp_path: Path) -> None:
    payload = _png_bytes(b"red")
    file_path = tmp_path / "same.png"
    file_path.write_bytes(payload)
    # 同一内容两种形态（本地文件 vs data URL）⇒ 同一内容身份。
    assert image_ref_digest(str(file_path)) == image_ref_digest(_data_url(payload))
    # 取不到字节的指针（http/不存在的路径/非 base64 data URL）⇒ 空串。
    assert image_ref_digest("https://example.com/a.png") == ""
    assert image_ref_digest(str(tmp_path / "ghost.png")) == ""
    assert image_ref_digest("data:image/png;base64,!!!") == ""


def test_batch_key_all_or_nothing_and_order_matters(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(_png_bytes(b"one"))
    b.write_bytes(_png_bytes(b"two"))
    key_ab = caption_key_for_image_refs([str(a), str(b)])
    key_ba = caption_key_for_image_refs([str(b), str(a)])
    assert key_ab and key_ab != key_ba  # 顺序即请求顺序，换序＝另一批
    # 一票否决：混进一枚取不到身份的 ref ⇒ 整批不缓存。
    assert caption_key_for_image_refs([str(a), "https://x/y.png"]) == ""
    assert caption_key_for_image_refs([]) == ""


def test_key_from_messages_collects_image_parts_only() -> None:
    import hashlib

    png = _png_bytes(b"msg")
    url = _data_url(png)
    messages = [
        {"content": [{"type": "text", "text": "问题文本不进键"}]},
        {"content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": "另一段文本"},
        ]},
        "不是 dict 的消息体",
        {"content": "content 不是 list"},
    ]
    key = caption_key_for_messages(messages)
    assert key == url_digest_pipe(png)


def url_digest_pipe(payload: bytes) -> str:
    """单图批键 = media_digest(digest)（与 caption_key_for_image_refs 同径）。"""
    from plugins.bot_unified_runtime.domains.media.digest import media_digest

    return media_digest(
        "|".join([image_ref_digest(_data_url(payload))]).encode("utf-8")
    )


def test_build_via_config_and_instance_reuse(tmp_path: Path) -> None:
    class _Cfg:
        bot_vision_caption_cache_db = str(tmp_path / "cap.sqlite3")
        bot_vision_caption_cache_ttl_seconds = 86400

    cfg = _Cfg()
    first = build_vision_caption_cache(cfg)
    assert first is not None
    assert build_vision_caption_cache(cfg) is first  # 同路径复用同一连接

    class _Off:
        bot_vision_caption_cache_db = ""
        bot_vision_caption_cache_ttl_seconds = 86400

    assert build_vision_caption_cache(_Off()) is None  # 空串＝整件关闭

    class _NoTtl:
        bot_vision_caption_cache_db = str(tmp_path / "cap2.sqlite3")
        bot_vision_caption_cache_ttl_seconds = 0

    assert build_vision_caption_cache(_NoTtl()) is None  # TTL≤0＝关闭
