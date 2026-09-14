"""Bot 头像本地优先（F3，2026-09-14 素材本地化批次，全离线）。

锁定 _resolve_bot_avatar_url 三级解析与 bot_avatar.py 磁盘兜底发现：
1. 本地命中（内存登记 / 磁盘 avatar/bot_*.png）→ file URI，远端 RPC 计数=0
   （不再 600s 周期回源）；
2. 本地缺失 → 既有远端链原样（get_stranger_info / qlogo 回退语义不变）；
3. bot_avatar_uri 统一入口的「配置 > 本地 > 空」优先级不被破坏。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime_pkg
from plugins.bot_unified_runtime import _resolve_bot_avatar_url
from plugins.bot_unified_runtime.output import bot_avatar

_PNG = b"\x89PNG\r\n\x1a\n" + b"avatar-payload"


@pytest.fixture()
def _isolated(monkeypatch: pytest.MonkeyPatch):
    """隔离三处进程级全局：bot_avatar 内存 URI、600s 远端 URL 缓存、
    磁盘兜底负结果 TTL 缓存（审查 L-14）。"""
    monkeypatch.setattr(bot_avatar, "_LOCAL_AVATAR_URI", "")
    monkeypatch.setattr(runtime_pkg, "_BOT_AVATAR_URL_CACHE", {})
    monkeypatch.setattr(bot_avatar, "_DISCOVER_MISS_TS", {})


def _remote_recorder(url: str = "https://remote.example/a.png"):
    calls: list[dict] = []

    async def _get_stranger_info(**kwargs):
        calls.append(kwargs)
        return {"data": {"avatar": url}}

    return calls, _get_stranger_info


def test_resolve_local_memory_hit_skips_remote(
    _isolated, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    avatar_file = tmp_path / "bot_10000.png"
    avatar_file.write_bytes(_PNG)
    bot_avatar.set_local_path(avatar_file)

    calls, get_stranger_info = _remote_recorder()
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == avatar_file.as_uri()  # 本地 file URI 直出
    assert calls == []  # 零远端调用：600s 周期回源被消灭


def test_resolve_disk_fallback_when_memory_empty(
    _isolated, tmp_path: Path
) -> None:
    # 内存未登记（模拟重启后 qlogo 拉取失败），磁盘文件还在 → 直接用。
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    avatar_file = avatar_dir / "bot_10000.png"
    avatar_file.write_bytes(_PNG)

    calls, get_stranger_info = _remote_recorder()
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == avatar_file.as_uri()  # 磁盘兜底发现并激活
    assert calls == []


def test_discover_picks_newest_avatar_file(_isolated, tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    old_file = avatar_dir / "bot_11111.png"
    new_file = avatar_dir / "bot_10000.png"
    old_file.write_bytes(_PNG)
    new_file.write_bytes(_PNG)
    os.utime(old_file, (1_000_000_000, 1_000_000_000))
    os.utime(new_file, (2_000_000_000, 2_000_000_000))

    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )
    assert bot_avatar.bot_avatar_uri(config) == new_file.as_uri()  # 取最新 mtime


def test_resolve_local_missing_goes_remote(_isolated, tmp_path: Path) -> None:
    calls, get_stranger_info = _remote_recorder("https://napcat.example/a.png")
    bot = SimpleNamespace(self_id="10000", get_stranger_info=get_stranger_info)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 无 avatar 目录
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    assert url == "https://napcat.example/a.png"  # 远端链语义原样
    assert len(calls) == 1  # 本地缺失才走远端


def test_resolve_remote_failure_keeps_qlogo_fallback(
    _isolated, tmp_path: Path
) -> None:
    async def _boom(**kwargs):
        raise TimeoutError("napcat rpc timeout")

    bot = SimpleNamespace(self_id="10000", get_stranger_info=_boom)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    url = asyncio.run(_resolve_bot_avatar_url(bot, config))
    # 既有回退语义不变：RPC 失败 → qlogo 直链（最终加载失败仍由卡片回落圆点）。
    assert url == "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"


def test_bot_avatar_uri_configured_url_wins(_isolated, tmp_path: Path) -> None:
    avatar_file = tmp_path / "bot_10000.png"
    avatar_file.write_bytes(_PNG)
    bot_avatar.set_local_path(avatar_file)
    config = SimpleNamespace(
        bot_persona_avatar_url="https://cfg.example/a.png",
        bot_runtime_data_dir=str(tmp_path),
    )
    assert bot_avatar.bot_avatar_uri(config) == "https://cfg.example/a.png"


def test_bot_avatar_uri_no_config_no_file_returns_empty(
    _isolated, tmp_path: Path
) -> None:
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 空目录
    )
    assert bot_avatar.bot_avatar_uri(config) == ""  # 调用方回落「守」字圆点


# ---------------------------------------------------------------------------
# 审查 L-14：磁盘兜底缺失探测的负结果 TTL 缓存（全离线注入时钟）。
# ---------------------------------------------------------------------------


class _Clock:
    """可推进的单调钟替身：monkeypatch 进 bot_avatar._MONOTONIC。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _count_globs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """给 Path.glob 套计数壳（委托真 glob，探测真实发生与否可断言）。"""
    calls: list[str] = []
    real_glob = Path.glob

    def counting_glob(self: Path, pattern: str):
        calls.append(pattern)
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", counting_glob)
    return calls


def test_miss_probes_once_within_ttl(_isolated, monkeypatch, tmp_path) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)  # 无 avatar 目录
    )

    assert bot_avatar.bot_avatar_uri(config) == ""  # 首次：真探测，确认缺失
    assert len(globs) == 1
    assert bot_avatar.bot_avatar_uri(config) == ""  # TTL 内：负缓存回空
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1  # 计数不变 → glob+stat 探测未重复（审查 L-14）


def test_miss_reprobes_after_ttl_expiry(_isolated, monkeypatch, tmp_path) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1
    clock.advance(300.0)  # 恰到 TTL 边界：仍算新鲜（<= 语义，对齐 randpic）
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 1
    clock.advance(0.5)  # 越过 TTL：过期重探
    assert bot_avatar.bot_avatar_uri(config) == ""
    assert len(globs) == 2


def test_file_appears_after_ttl_returns_uri_then_memory_shortcut(
    _isolated, monkeypatch, tmp_path
) -> None:
    clock = _Clock()
    monkeypatch.setattr(bot_avatar, "_MONOTONIC", clock)
    globs = _count_globs(monkeypatch)
    config = SimpleNamespace(
        bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path)
    )

    assert bot_avatar.bot_avatar_uri(config) == ""  # 先记负结果
    avatar_file = tmp_path / "avatar" / "bot_10000.png"
    avatar_file.parent.mkdir()
    avatar_file.write_bytes(_PNG)  # 期间头像文件落盘

    clock.advance(301.0)  # TTL 过期 → 重探发现
    assert bot_avatar.bot_avatar_uri(config) == avatar_file.as_uri()
    assert len(globs) == 2

    # 正结果登记内存后：内存短路，再推进时间也不探测（既有语义不变）。
    clock.advance(10_000.0)
    assert bot_avatar.bot_avatar_uri(config) == avatar_file.as_uri()
    assert len(globs) == 2
