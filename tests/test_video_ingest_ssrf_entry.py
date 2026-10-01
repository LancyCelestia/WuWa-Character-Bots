"""视频腿 ffmpeg 直连源入口咽喉复查锁（攻击者复查残余收口，席位 S-ATKFIX-SSRF2）。

出处：SEAT-ATKFIX-SSRF1.md §6.4 把「视频腿（describe_video/ffmpeg -i url）」登记为
未做边界；SEAT-ATK-SSRF.md 表 #5 记「yt-dlp 独立栈」残余（F-5）。本席现算坐实视频腿
字节来源：``build_video_brief``/``describe_video`` 把 ``video_source`` 直送
``ffmpeg -i <url>``（``vision_describe._extract_video_frames`` 与
``video_understanding._extract_audio_clip``），http 源由 **ffmpeg 自带网络栈自取**，
绕开 Python 咽喉——而 ``chat.py`` 视频腿（禁碰面）grep 中央咽喉零命中，能力协议壳
仅入口一查。攻击者可经消息视频段的 http url 让 bot 本机 ffmpeg 直连内网/云元数据
（盲 SSRF/端口探测）。

修法（本席）：在把 http 源交给 ffmpeg 之前，先过**中央唯一判据**
``check_download_url``——明确拒绝即按「无帧/无音轨」降级（返回 ``[]``/``None``，
与 ffmpeg 缺失同口径），绝不把内网地址下发给 ffmpeg。ffmpeg 自身跟随的重定向落点
属连接级残余（同 F-5/F-8），登记不堵（见席位报告）。

全离线纪律：monkeypatch ``_find_ffmpeg_locate`` 返回真值、``subprocess.run`` 记账
argv 且不真跑（避免真 ffmpeg/真网络）；URL 全用字面量 IP，零 DNS。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.media.ingest import video_understanding as VU
from plugins.bot_unified_runtime.domains.media.ingest import vision_describe as V

_INTERNAL = "http://127.0.0.1:9/clip.mp4"
_METADATA = "http://169.254.169.254/latest"
_PUBLIC = "http://93.184.216.34/clip.mp4"


def _stub_ffmpeg_boundary(monkeypatch: pytest.MonkeyPatch, module):
    """把「定位 ffmpeg」钉成存在、把 subprocess.run 换成 argv 记账件（绝不真跑）。"""
    monkeypatch.setattr(module, "_find_ffmpeg_locate", lambda: "ffmpeg-stub")
    commands: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        commands.append([str(token) for token in cmd])
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return commands


# ---- 抽帧腿（vision_describe._extract_video_frames，build_video_brief + describe_video 共用）----


def test_frames_reject_internal_url_before_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """RED（修复前）：内网 http 源当前直送 ``ffmpeg -i`` → 记账到内网命令行。

    修复后：入口咽喉在建连前拒掉，``subprocess.run`` 一次都不被调、返回空帧列表。
    """
    commands = _stub_ffmpeg_boundary(monkeypatch, V)
    out = V._extract_video_frames(_INTERNAL, 1, str(tmp_path))
    assert out == []
    assert commands == [], "内网 http 源绝不可抵达 ffmpeg（未过入口咽喉即红）"


def test_frames_reject_metadata_url_before_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    commands = _stub_ffmpeg_boundary(monkeypatch, V)
    out = V._extract_video_frames(_METADATA, 1, str(tmp_path))
    assert out == []
    assert commands == []


def test_frames_allow_public_literal_ip(monkeypatch, tmp_path: Path) -> None:
    """正向锁：公网字面 IP 源放行、ffmpeg 照旧被调（不过度拦）。"""
    commands = _stub_ffmpeg_boundary(monkeypatch, V)
    V._extract_video_frames(_PUBLIC, 1, str(tmp_path))
    assert any(_PUBLIC in token for cmd in commands for token in cmd)


def test_frames_local_path_not_blocked_by_guard(monkeypatch, tmp_path: Path) -> None:
    """本机文件源不受入口咽喉影响（guard 只管 http）：ffmpeg 仍收到该路径。"""
    commands = _stub_ffmpeg_boundary(monkeypatch, V)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x01")
    V._extract_video_frames(str(src), 1, str(tmp_path))
    assert any(str(src) in token for cmd in commands for token in cmd)


# ---- 音轨腿（video_understanding._extract_audio_clip）----


def test_audio_clip_rejects_internal_url_before_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """RED（修复前）：视频音轨腿同样把内网 http 源直送 ffmpeg。"""
    commands = _stub_ffmpeg_boundary(monkeypatch, VU)
    out = VU._extract_audio_clip(_INTERNAL, str(tmp_path), 30.0)
    assert out is None
    assert commands == [], "内网 http 源绝不可抵达 ffmpeg"


def test_audio_clip_allows_public_literal_ip(monkeypatch, tmp_path: Path) -> None:
    commands = _stub_ffmpeg_boundary(monkeypatch, VU)
    VU._extract_audio_clip(_PUBLIC, str(tmp_path), 30.0)
    assert any(_PUBLIC in token for cmd in commands for token in cmd)


def test_audio_clip_local_path_not_blocked(monkeypatch, tmp_path: Path) -> None:
    commands = _stub_ffmpeg_boundary(monkeypatch, VU)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x01")
    VU._extract_audio_clip(str(src), str(tmp_path), 30.0)
    assert any(str(src) in token for cmd in commands for token in cmd)
