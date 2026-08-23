"""表情包能力（bot.meme）测试：命令解析 + 后端交互 + 优雅降级。"""

from pathlib import Path

from plugins.bot_unified_runtime.capabilities.meme import (
    build_meme_capability,
    is_meme_command,
    parse_meme_command,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType


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
    assert is_meme_command("/表情 列表")
    assert is_meme_command("表情 列表")
    assert is_meme_command("/meme petpet 可爱")
    assert is_meme_command("/表情帮助")
    assert not is_meme_command("表情包真好笑")

    assert parse_meme_command("/表情帮助")[0] == "help"
    assert parse_meme_command("表情列表")[0] == "list"
    action, key, texts = parse_meme_command("/表情 文字 早上好｜晚上好")
    assert (action, key, texts) == ("render", "文字", ["早上好", "晚上好"])


def test_disabled_returns_friendly_message():
    capability = build_meme_capability(Config(bot_meme_api_enabled=False))
    result = capability(_message("/表情 列表"), None)
    assert result.kind == "text"
    assert "未启用" in result.body


def test_help_command():
    capability = build_meme_capability(
        Config(bot_meme_api_enabled=True), request_fn=lambda *a, **k: (200, "1.0.0")
    )
    result = capability(_message("/表情帮助"), None)
    assert result.kind == "text"
    assert "用法" in result.body


def test_list_command_returns_keys():
    def fake(method, path, json=None):
        if method == "GET" and path == "/meme/keys":
            return 200, ["petpet", "摸", "亲"]
        return 200, "1.0.0"

    capability = build_meme_capability(
        Config(bot_meme_api_enabled=True), request_fn=fake
    )
    result = capability(_message("/表情 列表"), None)
    assert result.kind == "text"
    assert "petpet" in result.body
    assert "共 3 个" in result.body


def test_render_command_saves_image(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"fake-image" * 8

    calls = []

    def fake(method, path, json=None):
        calls.append((method, path, json))
        if method == "POST" and path == "/memes/petpet":
            assert json == {"images": [], "texts": ["可爱"], "options": {}}
            return 200, {"image_id": "img_1"}
        if method == "GET" and path == "/image/img_1":
            return 200, png
        return 200, "1.0.0"

    capability = build_meme_capability(
        Config(bot_meme_api_enabled=True, bot_meme_api_output_dir=str(tmp_path)),
        request_fn=fake,
    )
    result = capability(_message("/表情 petpet 可爱"), None)
    assert result.kind == "mixed"
    assert result.images and result.images[0]["file"].endswith(".png")
    assert Path(result.images[0]["file"]).read_bytes() == png


def test_backend_down_returns_friendly_message():
    def fake(method, path, json=None):
        return 0, None

    capability = build_meme_capability(
        Config(bot_meme_api_enabled=True, bot_meme_api_base_url="http://127.0.0.1:2233"),
        request_fn=fake,
    )
    result = capability(_message("/表情 petpet 可爱"), None)
    assert result.kind == "text"
    assert "未启动" in result.body
