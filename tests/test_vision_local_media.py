"""本地媒体 vision 链路回归：file:/// 图片、GIF 首帧、视频抽帧。

NapCat 收到的 image/video 段常带本机 nt_data 路径而非 http URL，
extract_image_urls 此前只认 http 前缀导致 vision 链路静默跳过
（人格模型只看到 [图片] 占位符）。本文件锁定修复后的行为。
"""
from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime import contains_visual_message_segments
from plugins.bot_unified_runtime.sources import vision_describe
from plugins.bot_unified_runtime.sources.vision_describe import (
    describe_images,
    describe_video,
    extract_image_urls,
    extract_video_source,
)


def _write_png(path: Path, color: tuple[int, int, int] = (10, 20, 30)) -> Path:
    from PIL import Image

    Image.new("RGB", (4, 4), color).save(path, format="PNG")
    return path


def _write_gif(path: Path) -> Path:
    from PIL import Image

    first = Image.new("RGB", (6, 6), (255, 0, 0))
    second = Image.new("RGB", (6, 6), (0, 0, 255))
    first.save(path, format="GIF", save_all=True, append_images=[second], duration=200)
    return path


def _data_url_mime(value: str) -> str:
    assert value.startswith("data:"), value[:60]
    return value.split(";", 1)[0][len("data:") :]


def test_extract_image_urls_resolves_local_file_path(tmp_path: Path) -> None:
    png = _write_png(tmp_path / "ori.png")
    segments = [{"type": "image", "data": {"file": png.as_uri()}}]
    urls = extract_image_urls(segments)
    assert len(urls) == 1
    assert urls[0].startswith("data:image/png;base64,")
    _, payload = urls[0].split(",", 1)
    base64.b64decode(payload, validate=True)


def test_extract_image_urls_resolves_plain_absolute_path(tmp_path: Path) -> None:
    png = _write_png(tmp_path / "plain.png")
    segments = [{"type": "image", "data": {"file": str(png)}}]
    urls = extract_image_urls(segments)
    assert len(urls) == 1
    assert _data_url_mime(urls[0]) == "image/png"


def test_extract_image_urls_prefers_local_path_over_http(tmp_path: Path) -> None:
    png = _write_png(tmp_path / "fresh.png")
    segments = [
        {
            "type": "image",
            "data": {"url": "https://multimedia.nt.qq.com/download?signed=1", "file": str(png)},
        }
    ]
    urls = extract_image_urls(segments)
    # 本机文件直读优先：NTQQ 签名 URL 对部分 VLM 不可达，落盘字节最可靠。
    assert urls and urls[0].startswith("data:image/png;base64,")


def test_extract_image_urls_converts_gif_to_first_frame(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "sticker.gif")
    segments = [{"type": "image", "data": {"file": str(gif)}}]
    urls = extract_image_urls(segments)
    assert len(urls) == 1
    # 主流 OpenAI 兼容 VLM 不收 image/gif，首帧必须重编（统一 JPEG，体积最小）。
    assert _data_url_mime(urls[0]) == "image/jpeg"


def test_extract_image_urls_http_and_unresolvable_unchanged() -> None:
    segments = [
        {"type": "image", "data": {"url": "https://img.example/a.jpg"}},
        {"type": "image", "data": {"file": "local_only.png"}},
        {"type": "image", "data": {"file": "Z:\\definitely\\missing\\x.png"}},
        {"type": "image", "data": {"url": "not-a-url"}},
    ]
    assert extract_image_urls(segments) == ["https://img.example/a.jpg"]


def test_describe_images_accepts_data_url_images() -> None:
    class _Capture:
        def __init__(self) -> None:
            self.calls: list[list[dict]] = []

        def generate(self, messages, **kwargs):
            self.calls.append(messages)
            return SimpleNamespace(text="ok", provider="f", model="f", confidence=1.0)

    provider = _Capture()
    data_url = "data:image/png;base64,iVBORw0KGgo="
    describe_images(provider, image_urls=[data_url])
    content = provider.calls[0][1]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert [part["image_url"]["url"] for part in image_parts] == [data_url]


def test_extract_video_source_local_path_and_http(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    local = extract_video_source([{"type": "video", "data": {"file": str(clip)}}])
    assert local == str(clip)
    remote = extract_video_source(
        [{"type": "video", "data": {"url": "https://v.example/a.mp4"}}]
    )
    assert remote == "https://v.example/a.mp4"
    assert (
        extract_video_source([{"type": "video", "data": {"file": "missing.mp4"}}])
        is None
    )
    assert extract_video_source([{"type": "text", "data": {"text": "hi"}}]) is None


def test_describe_video_sends_frames_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame_a = _write_png(tmp_path / "frame_000.jpg")
    frame_b = _write_png(tmp_path / "frame_001.jpg")

    seen_dirs: list[str] = []

    def fake_frames(source: str, count: int, out_dir: str, timeout: float):
        assert count >= 2
        seen_dirs.append(out_dir)
        return [frame_a, frame_b]

    monkeypatch.setattr(vision_describe, "_extract_video_frames", fake_frames)

    class _Capture:
        def __init__(self) -> None:
            self.calls: list[list[dict]] = []

        def generate(self, messages, **kwargs):
            self.calls.append(messages)
            return SimpleNamespace(
                text="内容：一只猫跳上桌子。\n文字：无\n细节：动作很快。",
                provider="f",
                model="f",
                confidence=1.0,
            )

    provider = _Capture()
    result = describe_video(
        provider,
        video_source="C:\\fake\\clip.mp4",
        query_text="看看这个视频",
        frames=2,
    )
    assert result.startswith("内容：一只猫跳上桌子")
    content = provider.calls[0][1]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert len(image_parts) == 2
    assert all(
        part["image_url"]["url"].startswith("data:image/") for part in image_parts
    )
    assert "看看这个视频" in content[0]["text"]
    # 抽帧临时目录用后即焚，不残留源码树或临时区。
    assert seen_dirs and not Path(seen_dirs[0]).exists()


def test_describe_video_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_frames(source: str, count: int, out_dir: str, timeout: float):
        return []

    monkeypatch.setattr(vision_describe, "_extract_video_frames", no_frames)

    class _Boom:
        def generate(self, messages, **kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("provider must not be called without frames")

    assert describe_video(_Boom(), video_source="x.mp4") == ""


@pytest.mark.skipif(
    not vision_describe._find_ffmpeg_locate(), reason="ffmpeg not installed"
)
def test_extract_video_frames_with_real_ffmpeg(tmp_path: Path) -> None:
    import subprocess

    clip = tmp_path / "src.mp4"
    subprocess.run(
        [
            vision_describe._find_ffmpeg_locate(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    frames = vision_describe._extract_video_frames(str(clip), 4, str(out_dir), 60.0)
    assert len(frames) >= 2
    assert all(frame.exists() and frame.stat().st_size > 0 for frame in frames)


def test_direct_vision_builder_accepts_data_urls() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import (
        build_direct_vision_messages,
    )

    data_url = "data:image/png;base64,iVBORw0KGgo="
    messages = build_direct_vision_messages(
        [{"role": "system", "content": "system"}],
        query_text="看图",
        image_urls=[data_url],
        max_images=2,
    )
    content = messages[-1]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert [part["image_url"]["url"] for part in image_parts] == [data_url]


def test_visual_segments_include_video() -> None:
    assert contains_visual_message_segments(
        [{"type": "video", "data": {"file": "clip.mp4"}}]
    ) is True


def test_gate_message_has_media_with_local_video(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.policy.gate import _message_has_image

    monkeypatch.setattr(
        vision_describe,
        "extract_video_source",
        lambda segments: "C:\\fake\\clip.mp4" if segments else None,
    )
    message = SimpleNamespace(raw_segments=[{"type": "video", "data": {"file": "c.mp4"}}])
    assert _message_has_image(message) is True
    assert _message_has_image(SimpleNamespace(raw_segments=[])) is False


def test_extract_image_urls_gif_filmstrip_carries_motion(tmp_path: Path) -> None:
    import base64 as _b64
    from io import BytesIO

    from PIL import Image

    frames = [
        Image.new("RGB", (40, 20), color)
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
    ]
    gif = tmp_path / "anim.gif"
    frames[0].save(
        gif, format="GIF", save_all=True, append_images=frames[1:], duration=100
    )
    urls = extract_image_urls([{"type": "image", "data": {"file": str(gif)}}])
    assert len(urls) == 1
    assert _data_url_mime(urls[0]) == "image/jpeg"
    decoded = Image.open(BytesIO(_b64.b64decode(urls[0].split(",", 1)[1])))
    # 三帧横向拼接：宽度约为单帧高度的 3 倍以上，保留运动过程。
    assert decoded.width >= decoded.height * 2


def test_extract_image_urls_single_frame_gif_still_works(tmp_path: Path) -> None:
    from PIL import Image

    gif = tmp_path / "still.gif"
    Image.new("RGB", (10, 10), (9, 9, 9)).save(gif, format="GIF")
    urls = extract_image_urls([{"type": "image", "data": {"file": str(gif)}}])
    assert len(urls) == 1
    assert _data_url_mime(urls[0]) == "image/jpeg"
