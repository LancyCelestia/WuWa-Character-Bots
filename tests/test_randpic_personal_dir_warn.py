"""randpic 登记根个人目录防呆（B4 软提示，2026-09-30）回归。

锁三件事（判据真身 ``randpic._warn_if_personal_root``）：
1. 登记根命中个人目录名（``Picture``/``图片``/``桌面``…）或家目录/进程 CWD 本身
   ⇒ ``logger.warning`` 一声（每根进程内至多一次）；
2. **软提示不拦**：命中根照常进 ``registered_gallery_roots``，取图行为不变；
3. 不命中 ⇒ 零告警（不狼来了）。

全部离线、只写 ``tmp_path``；家目录经 ``os.path.expanduser`` 打桩到 tmp_path。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
    return home


def _config(*dirs: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_randpic_dirs=[str(item) for item in dirs],
        bot_randpic_trigger_words=["随机图"],
        bot_randpic_min_file_kb=0,
        bot_randpic_min_side=0,
    )


def test_personal_dir_warns_but_still_registered(
    fake_home: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``home/Picture`` 登记成图库 ⇒ 告警一声，且**照常登记可读**（软提示不拦）。"""
    gallery = fake_home / "Picture"
    gallery.mkdir(parents=True)
    (gallery / "a.png").write_bytes(PNG_HEAD)
    config = _config(gallery)
    randpic.reset_gallery_warning_state()
    try:
        with caplog.at_level(logging.WARNING, logger=randpic.logger.name):
            roots = randpic.registered_gallery_roots(config)
        assert roots, "软提示不得把登记根拦掉（那是替用户做决定）"
        personal_warnings = [
            record for record in caplog.records if "personal directory" in record.getMessage()
        ]
        assert personal_warnings, "登记个人图片目录必须有 warning 落日志"
    finally:
        randpic.reset_gallery_warning_state()


def test_personal_dir_warns_once_per_root(
    fake_home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """同一根进程内只告警一次（去重），不刷屏。"""
    gallery = fake_home / "Documents"
    gallery.mkdir(parents=True)
    config = _config(gallery)
    randpic.reset_gallery_warning_state()
    try:
        with caplog.at_level(logging.WARNING, logger=randpic.logger.name):
            randpic.registered_gallery_roots(config)
            first = len(
                [r for r in caplog.records if "personal directory" in r.getMessage()]
            )
            randpic.registered_gallery_roots(config)
            second = len(
                [r for r in caplog.records if "personal directory" in r.getMessage()]
            )
        assert first == 1, f"首次读取应告警一次，实际 {first}"
        assert second == 1, f"同根第二次读取不得重复告警，实际 {second}"
    finally:
        randpic.reset_gallery_warning_state()


def test_plain_dir_does_not_warn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """普通名字的专用图库 ⇒ 零告警（不狼来了）。"""
    gallery = tmp_path / "sticker_gallery"
    gallery.mkdir()
    (gallery / "a.png").write_bytes(PNG_HEAD)
    config = _config(gallery)
    randpic.reset_gallery_warning_state()
    try:
        with caplog.at_level(logging.WARNING, logger=randpic.logger.name):
            randpic.registered_gallery_roots(config)
        assert not [
            r for r in caplog.records if "personal directory" in r.getMessage()
        ]
    finally:
        randpic.reset_gallery_warning_state()
