"""群聊表情包库测试：去重、权重、命令解析、监听段提取。"""

import asyncio
import types
from pathlib import Path

from plugins.bot_unified_runtime.capabilities.meme_library import (
    build_meme_library_capability,
    is_meme_library_command,
    parse_meme_library_command,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.meme_library import MemeLibraryStore
from plugins.bot_unified_runtime.sources.meme_library_listener import _segment_urls


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="private:42",
        session_type=SessionType.PRIVATE,
        sender_id="42",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
    )


def test_command_detection_and_parse():
    for text in ["偷表情", "/偷表情 可爱", "随机表情", "/表情库统计", "meme random", "偷表情包"]:
        assert is_meme_library_command(text), text
    assert parse_meme_library_command("偷表情 可爱") == ("pick", "可爱")
    assert parse_meme_library_command("/表情库统计") == ("stats", "")


def test_store_dedupe_and_weighted_pick(tmp_path):
    store = MemeLibraryStore(
        tmp_path / "db.sqlite3",
        prefer=["守岸人", "鸣潮"],
    )
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    a = image_dir / "a.gif"
    a.write_bytes(b"GIF89a" + b"a" * 20)
    b = image_dir / "b.png"
    b.write_bytes(b"\x89PNG" + b"b" * 20)

    store.add(md5="m1", path=str(a), ext="gif", group_id="100")
    assert store.add(md5="m1", path=str(a), ext="gif", group_id="100")["inserted"] is False
    store.add(md5="m2", path=str(b), ext="png", group_id="100")

    # 守岸人标签拉高权重，应被优先选中
    store.apply_tags("m1", is_meme=True, description="守岸人表情包", nsfw_score=0.0)
    store.apply_tags("m2", is_meme=True, description="普通风景", nsfw_score=0.0)
    picked = store.weighted_pick(keyword="守岸人")
    assert picked is not None and picked["md5"] == "m1"

    assert store.stats()["total"] == 2


def test_nsfw_high_never_picked(tmp_path):
    store = MemeLibraryStore(tmp_path / "db.sqlite3")
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG" + b"x" * 20)
    store.add(md5="bad", path=str(image), ext="png")
    store.apply_tags("bad", is_meme=True, description="图", nsfw_score=0.9)
    assert store.weighted_pick() is None


def test_capability_pick_and_cooldown(tmp_path):
    store = MemeLibraryStore(tmp_path / "db.sqlite3", prefer=["守岸人"])
    image = tmp_path / "s.gif"
    image.write_bytes(b"GIF89a" + b"s" * 20)
    store.add(md5="s1", path=str(image), ext="gif")
    store.apply_tags("s1", is_meme=True, description="守岸人")
    capability = build_meme_library_capability(
        store, Config(bot_meme_library_cooldown_seconds=5)
    )
    first = capability(_message("偷表情"), None)
    assert first.kind == "mixed" and first.images
    second = capability(_message("偷表情"), None)
    assert "冷却" in second.body


def test_segment_urls_extraction():
    segments = [
        types.SimpleNamespace(type="image", data={"url": "https://a/b.gif"}),
        types.SimpleNamespace(type="text", data={"text": "hello"}),
    ]
    assert _segment_urls(segments) == ["https://a/b.gif"]
    assert _segment_urls([{"type": "image", "data": {"url": "https://c/d.png"}}]) == [
        "https://c/d.png"
    ]


def test_remove_deletes_row_and_file(tmp_path):
    store = MemeLibraryStore(tmp_path / "db.sqlite3")
    image = tmp_path / "rm.png"
    image.write_bytes(bytes([0x89]) + b"PNG" + b"r" * 20)
    store.add(md5="r1", path=str(image), ext="png")
    assert store.remove("r1") is True
    assert not image.exists()
    assert store.stats()["total"] == 0


def test_vision_preset_resolves_env_ref(monkeypatch):
    from plugins.bot_unified_runtime.sources.meme_library_listener import _resolve_vision_config

    monkeypatch.setenv("BOT_API_KEY_VISION", "sk-secret")
    config = Config(
        bot_meme_library_vlm_preset="stone-next",
        bot_vision_model_registry={
            "stone-next": {
                "model": "stone-vision-pro",
                "base_url": "https://stone.example/v1",
                "api_key": "env:BOT_API_KEY_VISION",
            }
        },
    )
    vision = _resolve_vision_config(config)
    assert vision == {
        "model": "stone-vision-pro",
        "base_url": "https://stone.example/v1",
        "api_key": "sk-secret",
    }
