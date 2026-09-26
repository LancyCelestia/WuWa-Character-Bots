"""视频理解编排器回归：信号收集、ASR 跳过、单次 VLM 融合与原生直传回退。

build_video_brief 汇聚画面抽帧(VLM)、音轨转写(ASR)、CC 字幕与元数据四路信号，
输出材料式视频简报；本文件锁定成本纪律（一次 VLM 调用、有字幕跳 ASR）、
失败降级语义（单信号失败不阻断、全空返回空文本）与原生 video_url 直传
的回退路径。全部用注入桩驱动，不依赖 ffmpeg 与真实模型。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
)
from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
    VideoBrief,
    build_video_brief,
)


class FakeVision:
    """记录调用次数与完整 messages 的假 VLM；fail_times 控制先失败后成功。"""

    def __init__(self, *, text: str = "画面：测试", fail_times: int = 0) -> None:
        self.text = text
        self.fail_times = fail_times
        self.calls: list[list[dict]] = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        if len(self.calls) <= self.fail_times:
            raise LLMProviderError("boom", error_kind="server")
        return SimpleNamespace(text=self.text)


class FakeASR:
    """记录 (audio_bytes, filename, timeout_seconds) 的假转写器；result 可为异常。"""

    def __init__(self, result: object = "转写文本") -> None:
        self.result = result
        self.calls: list[tuple[bytes, str, object]] = []

    def generate(self, audio_bytes: bytes, filename: str, **kwargs):
        self.calls.append((audio_bytes, filename, kwargs.get("timeout_seconds")))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _make_frames(tmp_path: Path, count: int = 2) -> list[Path]:
    """造几个可直接 read_bytes 的假帧文件（无需 ffmpeg/PIL）。"""
    frames: list[Path] = []
    for index in range(count):
        frame = tmp_path / f"frame_{index:03d}.jpg"
        frame.write_bytes(b"\xff\xd8" + b"jpeg" * 4)
        frames.append(frame)
    return frames


def test_frames_and_vlm_single_call_builds_material_brief(tmp_path: Path) -> None:
    frames = _make_frames(tmp_path, 2)
    vision = FakeVision()
    brief = build_video_brief(
        SimpleNamespace(),
        vision_provider=vision,
        video_source=r"C:\fake\clip.mp4",
        subtitle_text="大家好，今天教大家做菜",
        metadata_text="标题：家常菜教程",
        question="这是哪里的菜",
        frame_loader=lambda source, count, out_dir: frames,
    )
    assert isinstance(brief, VideoBrief)
    assert brief.signals["frames"] is True
    # 成本纪律：一次分析只发一次 VLM 请求。
    assert len(vision.calls) == 1
    content = vision.calls[0][1]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert len(image_parts) == 2
    assert all(
        part["image_url"]["url"].startswith("data:image/jpeg;base64,")
        for part in image_parts
    )
    text_part = next(part for part in content if part["type"] == "text")
    assert "这是哪里的菜" in text_part["text"]
    assert "标题：家常菜教程" in text_part["text"]
    assert "大家好，今天教大家做菜" in text_part["text"]
    assert vision.calls[0][0]["role"] == "system"
    assert brief.text.startswith("[视频档案]")
    assert "基本信息：标题：家常菜教程" in brief.text
    assert "字幕摘录：大家好，今天教大家做菜" in brief.text
    assert "画面识别：画面：测试" in brief.text
    assert "声音转写" not in brief.text


def test_subtitle_present_skips_asr_by_default() -> None:
    asr = FakeASR()
    brief = build_video_brief(
        SimpleNamespace(),
        asr_provider=asr,
        video_source=r"C:\fake\clip.mp4",
        subtitle_text="字幕内容",
    )
    # 已有 CC 字幕时默认跳过 ASR：音频转写是纯增量成本。
    assert asr.calls == []
    assert brief.signals["asr"] is False
    assert brief.signals["subtitle"] is True
    assert "字幕摘录：字幕内容" in brief.text


def test_asr_runs_when_skip_disabled_and_passes_timeout(tmp_path: Path) -> None:
    asr = FakeASR(result="转写文本")
    seen_max_seconds: list[float] = []

    def audio_extractor(source: str, work_dir: str, max_seconds: float):
        seen_max_seconds.append(max_seconds)
        return b"mp3-bytes", "audio.mp3"

    config = SimpleNamespace(bot_video_skip_asr_with_subtitle=False)
    brief = build_video_brief(
        config,
        asr_provider=asr,
        video_source=r"C:\fake\clip.mp4",
        subtitle_text="字幕内容",
        audio_extractor=audio_extractor,
    )
    assert brief.signals["asr"] is True
    assert len(asr.calls) == 1
    audio_bytes, filename, timeout = asr.calls[0]
    assert audio_bytes == b"mp3-bytes"
    assert filename == "audio.mp3"
    # ASR 超时按时长上限缩放（600s→150s）再被整体 deadline（默认 75s）封顶：
    # 单次尝试不得超过编排器的等待窗口，防止放弃后 worker 白烧转写费。
    assert timeout == 75.0
    assert seen_max_seconds == [600]  # bot_video_asr_max_seconds 默认值
    assert "声音转写：转写文本" in brief.text
    assert "字幕摘录：字幕内容" in brief.text


def test_vlm_failure_degrades_to_text_signals(tmp_path: Path) -> None:
    frames = _make_frames(tmp_path, 1)
    vision = FakeVision(fail_times=99)
    brief = build_video_brief(
        SimpleNamespace(),
        vision_provider=vision,
        video_source="x.mp4",
        subtitle_text="CC",
        metadata_text="META",
        frame_loader=lambda source, count, out_dir: frames,
    )
    assert brief.signals["frames"] is False
    assert "字幕摘录：CC" in brief.text
    assert "基本信息：META" in brief.text
    assert "画面识别" not in brief.text


def test_text_only_brief_without_media_skips_providers() -> None:
    vision = FakeVision()
    asr = FakeASR()
    brief = build_video_brief(
        SimpleNamespace(),
        vision_provider=vision,
        asr_provider=asr,
        subtitle_text="字幕",
        metadata_text="元数据",
    )
    assert vision.calls == []
    assert asr.calls == []
    assert brief.signals["frames"] is False
    assert brief.signals["asr"] is False
    assert "字幕摘录：字幕" in brief.text
    assert "基本信息：元数据" in brief.text


def test_all_signals_empty_returns_empty_text() -> None:
    brief = build_video_brief(SimpleNamespace())
    assert brief.text == ""
    assert brief.signals == {
        "frames": False,
        "asr": False,
        "subtitle": False,
        "metadata": False,
        "native_video": False,
    }


def test_asr_failure_degrades_but_brief_synthesized() -> None:
    asr = FakeASR(result=RuntimeError("asr down"))
    brief = build_video_brief(
        SimpleNamespace(),
        asr_provider=asr,
        video_source="x.mp4",
        metadata_text="标题：测试视频",
        audio_extractor=lambda source, work_dir, max_seconds: (b"a", "audio.mp3"),
    )
    assert asr.calls
    assert brief.signals["asr"] is False
    assert "基本信息：标题：测试视频" in brief.text
    assert brief.text


def test_native_video_input_sends_video_part_and_skips_frames(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    frame_calls: list[tuple] = []

    def frame_loader(source: str, count: int, out_dir: str):
        frame_calls.append((source, count, out_dir))
        return []

    vision = FakeVision()
    config = SimpleNamespace(bot_video_native_input=True)
    brief = build_video_brief(
        config,
        vision_provider=vision,
        video_source=str(clip),
        frame_loader=frame_loader,
    )
    # 有原生视频就跳过抽帧，省 token。
    assert frame_calls == []
    assert len(vision.calls) == 1
    content = vision.calls[0][1]["content"]
    video_parts = [part for part in content if part["type"] == "video_url"]
    assert len(video_parts) == 1
    assert video_parts[0]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert brief.signals["native_video"] is True
    assert brief.signals["frames"] is False
    assert "画面识别：画面：测试" in brief.text


def test_native_failure_falls_back_to_frames(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    frames = _make_frames(tmp_path, 1)
    frame_calls: list[tuple] = []

    def frame_loader(source: str, count: int, out_dir: str):
        frame_calls.append((source, count, out_dir))
        return frames

    vision = FakeVision(fail_times=1)
    config = SimpleNamespace(bot_video_native_input=True)
    brief = build_video_brief(
        config,
        vision_provider=vision,
        video_source=str(clip),
        frame_loader=frame_loader,
    )
    assert len(vision.calls) == 2
    assert brief.signals["native_video"] is False
    assert brief.signals["frames"] is True
    assert len(frame_calls) == 1
    content = vision.calls[1][1]["content"]
    assert any(part["type"] == "image_url" for part in content)
    assert not any(part["type"] == "video_url" for part in content)
    assert "画面识别：画面：测试" in brief.text


def test_brief_clipped_to_max_chars() -> None:
    config = SimpleNamespace(bot_video_brief_max_chars=100)
    brief = build_video_brief(config, subtitle_text="字" * 500)
    assert len(brief.text) == 100
    assert brief.text.endswith("…")


def test_deep_mode_expands_frames_and_forces_asr(tmp_path: Path) -> None:
    frames = _make_frames(tmp_path, 2)
    seen_counts: list[int] = []

    def frame_loader(source: str, count: int, out_dir: str):
        seen_counts.append(count)
        return frames

    vision = FakeVision()
    asr = FakeASR(result="转写文本")
    brief = build_video_brief(
        SimpleNamespace(),
        vision_provider=vision,
        asr_provider=asr,
        video_source=r"C:\fake\clip.mp4",
        subtitle_text="CC字幕",
        deep=True,
        frame_loader=frame_loader,
        audio_extractor=lambda source, work_dir, max_seconds: (b"a", "audio.mp3"),
    )
    assert seen_counts == [16]  # deep 帧数默认 bot_video_deep_frames=16
    assert len(asr.calls) == 1  # deep 强制 ASR，即使已有 CC 字幕
    assert brief.signals["asr"] is True
    assert brief.signals["frames"] is True


def test_detect_deep_video_request_phrases() -> None:
    from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
        detect_deep_video_request,
    )

    assert detect_deep_video_request("再仔细看看这个视频") is True
    assert detect_deep_video_request("刚才那段我没看懂") is True
    assert detect_deep_video_request("能详细讲讲吗") is True
    assert detect_deep_video_request("这是什么") is False
    assert detect_deep_video_request("") is False
