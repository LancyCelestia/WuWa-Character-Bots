"""占卜 / 历史卡 每抽子目录配额清理回归（Minor C5 收口，全离线）。

锁定三件事：
- 占卜卡每抽落 ``<card_dir>/divination/<token>/`` 独立子目录，高频抽牌
  会无限累积 PNG；写盘后须按 stocks 同款 keep=120 清理最旧子目录，
  最新一抽永远保留且 PNG 完整；
- 历史卡同族路径 ``<card_dir>/today_history/<month_day>/`` 用同一套
  子目录淘汰语义（按 mtime，最旧先删）；
- 配额清理自身抛异常（如 rmtree 权限错误）绝不影响本次出图——
  kind 保持 mixed、images 非空、PNG 落盘，与清理成功时同构。

全部打桩（假渲染后端 + tmp_path），不触网、不写源码树。
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import plugins.bot_unified_runtime.capabilities.divination as divination_module
import plugins.bot_unified_runtime.capabilities.today_history as today_history_module
from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    build_today_history_capability,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.sources.today_history import HistoryEvent

_UTC = timezone.utc

# 与 stocks/fx/market 同一口径（prune_prefixed keep=120）。
_KEEP = 120


# ---------------------------------------------------------------------------
# 打桩工具（与 tests/test_feature_cards.py 同构）。
# ---------------------------------------------------------------------------


class _FakeBackend:
    name = "fake"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        return b"fake-png"


class _StubConfig:
    def __init__(self, card_dir: str) -> None:
        self.bot_card_render_dir = card_dir


class _StubProvider:
    def __init__(self, events: list[HistoryEvent]) -> None:
        self._events = events

    def get_events(self, *, force: bool = False) -> list[HistoryEvent]:
        return list(self._events)


def _message(text: str, *, request_id: str = "req-prune") -> IncomingMessage:
    return IncomingMessage(
        request_id=request_id,
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        timestamp=datetime(2026, 9, 12, 13, 51, tzinfo=_UTC),
    )


def _decision() -> Any:
    return BotDecision(
        request_id="req-prune",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id="bot.divination",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


_EVENTS = [
    HistoryEvent(year="1998", title="事件甲发生"),
    HistoryEvent(year="1949", title="事件乙发生"),
]


def _history_capability(card_dir: str, backend: Any = None) -> Any:
    return build_today_history_capability(
        _StubConfig(card_dir),
        provider=_StubProvider(_EVENTS),
        push_file=str(Path(card_dir) / "push.json"),
        render_backend=backend,
    )


def _age_subdirs(root: Path, names: list[str], *, step: int = 100) -> None:
    """显式拉开子目录 mtime：names[i] 比 names[i+1] 旧，避免粒度抖动。"""
    base = time.time() - 10_000_000
    for i, name in enumerate(names):
        stamp = base + i * step
        os.utime(root / name, (stamp, stamp))


# ---------------------------------------------------------------------------
# 占卜卡：每抽子目录超 keep 后最旧被清、最新保留。
# ---------------------------------------------------------------------------


class TestDivinationCardDirPrune:
    def test_over_keep_oldest_subdir_removed_newest_kept(self, tmp_path: Path) -> None:
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=_FakeBackend()
        )
        root = tmp_path / "divination"
        names = [f"req-{i:03d}" for i in range(_KEEP)]
        for name in names:
            result = capability(_message("塔罗", request_id=name), _decision())
            assert result.kind == "mixed"
        assert len(list(root.iterdir())) == _KEEP  # 未超限不误删
        _age_subdirs(root, names)  # req-000 最旧 …… req-119 最新
        result = capability(_message("塔罗", request_id="req-new"), _decision())
        assert result.kind == "mixed"
        subdirs = {p.name for p in root.iterdir() if p.is_dir()}
        assert len(subdirs) == _KEEP
        assert "req-000" not in subdirs  # 最旧被清
        assert "req-001" in subdirs  # 其余保留
        assert "req-new" in subdirs  # 最新一抽保留且 PNG 完整
        assert list((root / "req-new").glob("*.png"))

    def test_prune_failure_never_blocks_card_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=_FakeBackend()
        )

        def _boom(root: Path, *, keep: int = _KEEP) -> int:
            raise RuntimeError("prune boom")

        monkeypatch.setattr(divination_module, "_prune_card_dirs", _boom)
        result = capability(_message("塔罗", request_id="req-x"), _decision())
        assert result.kind == "mixed"  # 出图不受清理异常影响
        assert result.images
        assert Path(str(result.images[0]["file"])).exists()


# ---------------------------------------------------------------------------
# 历史卡：同族子目录淘汰语义 + 清理异常不阻塞出图。
# ---------------------------------------------------------------------------


class TestTodayHistoryCardDirPrune:
    def test_helper_keeps_newest_subdirs(self, tmp_path: Path) -> None:
        root = tmp_path / "today_history"
        names = ["day-a", "day-b", "day-c"]
        for name in names:
            (root / name).mkdir(parents=True)
            (root / name / "card_x.png").write_bytes(b"png")
        _age_subdirs(root, names)  # day-a 最旧
        removed = today_history_module._prune_card_dirs(root, keep=2)
        assert removed == 1
        assert (root / "day-a").exists() is False  # 最旧被清
        assert (root / "day-b").exists() and (root / "day-c").exists()

    def test_helper_edge_cases(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        assert today_history_module._prune_card_dirs(missing, keep=2) == 0
        root = tmp_path / "today_history"
        root.mkdir()
        assert today_history_module._prune_card_dirs(root, keep=0) == 0  # 不误删
        (root / "loose.png").write_bytes(b"png")  # 散落文件不是子目录，不碰
        (root / "d1").mkdir()
        assert today_history_module._prune_card_dirs(root, keep=5) == 0
        assert (root / "loose.png").exists() and (root / "d1").exists()

    def test_prune_failure_never_blocks_card_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capability = _history_capability(str(tmp_path), _FakeBackend())

        def _boom(root: Path, *, keep: int = _KEEP) -> int:
            raise RuntimeError("prune boom")

        monkeypatch.setattr(today_history_module, "_prune_card_dirs", _boom)
        result = capability(_message("历史上的今天"), _decision())
        assert result.kind == "mixed"
        assert result.images
        assert Path(str(result.images[0]["file"])).exists()
