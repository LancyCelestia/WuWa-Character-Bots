"""免费游戏（Epic/Steam）卡片适配回归（Task3 收尾，全离线）。

锁定三态（范式与 tests/test_feature_cards.py 一致）：
- 出图分支：假后端可用 → kind=mixed、PNG 落盘 bot_card_render_dir、
  卡片 html 携带真实拉取的游戏条目（禁止编造数据）；
- 后端缺失 / 返回 None / 渲染抛异常：输出与无卡片时逐字节一致
  （body 相等、kind=text、images 空、text_only 审计），纯文字契约零破坏；
- 双源都失败：保持纯文本报错，任何后端都不出卡。

数据源全部打桩，不触网；不写源码树 data/（卡片落 tmp_path）。
iPad 免费游戏当前无数据源能力，不在本能力域（见 task-6 报告）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.epic import (
    build_epic_capability,
)

_EPIC_GAMES = [
    {"title": "游戏甲", "source": "Epic", "end": "09/18", "url": "https://example.com/a", "image": ""},
    {"title": "游戏乙", "source": "Epic", "end": "09/18", "url": "https://example.com/b", "image": ""},
]
_STEAM_GAMES = [
    {"title": "游戏丙", "source": "Steam", "end": "09/20", "url": "https://example.com/c", "image": ""},
]


class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def render_card(self, payload: dict) -> bytes | None:
        self.captured.append(payload)
        return b"fake-png"


class _BrokenBackend:
    name = "broken"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        return None


class _RaisingBackend:
    name = "raising"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        raise RuntimeError("boom")


class _StubConfig:
    def __init__(self, card_dir: str) -> None:
        self.bot_card_render_dir = card_dir


def _private_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    epic_games: list[dict[str, Any]] | Exception,
    steam_games: list[dict[str, Any]] | Exception,
) -> None:
    def _install(name: str, value: list[dict[str, Any]] | Exception) -> None:
        if isinstance(value, Exception):
            def _raise(*args: Any, **kwargs: Any) -> Any:
                raise value
            monkeypatch.setattr(
                f"plugins.bot_unified_runtime.domains.subscribe.capabilities.epic.{name}", _raise
            )
        else:
            monkeypatch.setattr(
                f"plugins.bot_unified_runtime.domains.subscribe.capabilities.epic.{name}",
                lambda proxy="", _v=value: list(_v),
            )

    _install("fetch_epic_free_games", epic_games)
    _install("fetch_steam_free_games", steam_games)


# ---------------------------------------------------------------------------
# 出图分支。
# ---------------------------------------------------------------------------


class TestEpicCardRendered:
    def test_both_sources_with_backend_is_mixed_and_png_written(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_sources(monkeypatch, epic_games=_EPIC_GAMES, steam_games=_STEAM_GAMES)
        backend = _FakeBackend()
        capability = build_epic_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("免费游戏"), None)
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        png_path = Path(result.images[0]["file"])
        assert png_path.exists()
        assert png_path.read_bytes() == b"fake-png"
        assert "card_rendered" in result.audit_tags
        assert "epic_games:3" in result.audit_tags
        # 卡片 html 携带真实拉取的全部条目与标题，禁止编造。
        html_text = str(backend.captured[0]["html"])
        assert "本周免费游戏" in html_text
        for title in ("游戏甲", "游戏乙", "游戏丙"):
            assert title in html_text
        assert "09/18" in html_text and "09/20" in html_text

    def test_single_source_failure_still_renders_card(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_sources(
            monkeypatch,
            epic_games=_EPIC_GAMES,
            steam_games=OSError("steam down"),
        )
        backend = _FakeBackend()
        capability = build_epic_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("epic"), None)
        assert result.kind == "mixed"
        assert "Steam 源暂时拉取失败" in result.body
        html_text = str(backend.captured[0]["html"])
        assert "游戏甲" in html_text  # 幸存源条目照常上卡
        assert "游戏丙" not in html_text  # 失败源条目不存在，不编造


# ---------------------------------------------------------------------------
# 回退三态。
# ---------------------------------------------------------------------------


class TestEpicCardFallback:
    def test_failing_backends_keep_body_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_sources(monkeypatch, epic_games=_EPIC_GAMES, steam_games=_STEAM_GAMES)
        baseline = build_epic_capability(
            _StubConfig(str(tmp_path)), render_backend=None
        )(_private_message("免费游戏"), None)
        assert baseline.kind == "text"
        assert baseline.images == []
        assert baseline.body.startswith("本周免费游戏：")
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = build_epic_capability(
                _StubConfig(str(tmp_path)), render_backend=backend
            )(_private_message("免费游戏"), None)
            assert result.kind == "text"
            assert result.images == []
            assert result.body == baseline.body
            assert "text_only" in result.audit_tags

    def test_all_sources_fail_stays_text_without_card(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_sources(
            monkeypatch,
            epic_games=OSError("epic down"),
            steam_games=OSError("steam down"),
        )
        backend = _FakeBackend()
        capability = build_epic_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("免费游戏"), None)
        assert result.kind == "text"
        assert result.images == []
        assert "免费游戏信息拉取失败" in result.body
        assert backend.captured == []  # 无数据不出卡、不编造

    def test_empty_result_list_stays_text_without_card(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 双源成功但均无活动：与全失败同走纯文本分支，不出卡。
        _patch_sources(monkeypatch, epic_games=[], steam_games=[])
        backend = _FakeBackend()
        capability = build_epic_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("免费游戏"), None)
        assert result.kind == "text"
        assert result.images == []
        assert backend.captured == []
