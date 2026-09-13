"""占卜 / 历史上的今天 卡片适配回归（TDD，全离线）。

锁定三件事：
- payload 构造函数：结构化输入 → 期望字段（平台/标题/摘要/来源；
  canonical_url 恒为 about:blank 约定值，footer 不渲染内部伪 URL）；
- 假后端可用：kind 变 mixed、images 非空、PNG 落盘到 bot_card_render_dir，
  卡片 html 携带真实计算结果（卦名/牌名/历史事件等，禁止编造数据），
  且 footer 不泄漏 divination:///history:///请求 ID（评审 C2）；
- 后端缺失 / 返回 None / 渲染抛异常：输出与无卡片时完全一致
  （body 逐字节相等、kind 保持原值、images 为空），纯文字契约零破坏
  （原 body 另由 tests/test_divination.py 与 test_today_history_robustness.py 锁定）。

渲染管线复用 weather/epic 的 render_card_png 范式；全部打桩，不触网。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
    build_divination_card_content,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    build_history_card_content,
    build_today_history_capability,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.sources.today_history import HistoryEvent

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# 打桩工具。
# ---------------------------------------------------------------------------


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


class _StubProvider:
    """固定事件桩：离线驱动 today_history 能力（不触缓存与网络）。"""

    def __init__(self, events: list[HistoryEvent]) -> None:
        self._events = events

    def get_events(self, *, force: bool = False) -> list[HistoryEvent]:
        return list(self._events)


def _message(text: str, *, sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        timestamp=datetime(2026, 9, 12, 13, 51, tzinfo=_UTC),
    )


def _decision(capability_id: str) -> Any:
    from plugins.bot_unified_runtime.contracts import BotDecision

    return BotDecision(
        request_id="req-feature-cards",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id=capability_id,
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


_EVENTS = [
    HistoryEvent(year="1998", title="事件甲发生"),
    HistoryEvent(year="1949", title="事件乙发生"),
]


def _history_capability(
    card_dir: str,
    backend: Any = None,
    provider: Any = None,
) -> Any:
    return build_today_history_capability(
        _StubConfig(card_dir),
        provider=provider or _StubProvider(_EVENTS),
        push_file=str(Path(card_dir) / "push.json"),
        render_backend=backend,
    )


# ---------------------------------------------------------------------------
# payload 构造函数（纯断言，无 IO）。
# ---------------------------------------------------------------------------


class TestDivinationCardPayload:
    def test_bazi_payload_fields(self) -> None:
        item = build_divination_card_content("bazi", "八字排盘", "正文文本")
        assert item.identity.platform == "divination"
        assert item.identity.item_id == "bazi"
        assert item.content.title == "八字排盘"
        assert item.content.summary == "正文文本"
        # F10 约定：about:blank 是「无真实来源页脚」占位值，渲染层按无 footer 处理。
        assert item.identity.canonical_url == "about:blank"

    def test_author_by_kind(self) -> None:
        for kind, fragment in (
            ("bazi", "排盘"),
            ("tarot", "塔罗"),
            ("iching", "金钱卦"),
        ):
            item = build_divination_card_content(kind, "标题", "正文")
            assert item.creator is not None and fragment in (item.creator.name or ""), kind

    def test_canonical_url_constant_about_blank(self) -> None:
        """去重键与 canonical_url 解耦（评审 C2）：footer 不再编码内部伪 URL，
        每抽唯一性由能力层经 card_dir 子目录承载。"""
        first = build_divination_card_content("tarot", "塔罗指引", "A")
        second = build_divination_card_content("iching", "金钱卦", "B")
        assert first.identity.canonical_url == "about:blank"
        assert second.identity.canonical_url == "about:blank"

    def test_summary_truncated_at_1200(self) -> None:
        item = build_divination_card_content("iching", "金钱卦", "卦" * 2000)
        assert len(item.content.summary) == 1200


class TestHistoryCardPayload:
    def test_title_carries_month_day(self) -> None:
        body = "历史上的今天 0912\n1998 事件甲发生\n1949 事件乙发生"
        item = build_history_card_content(body, month_day="0912")
        assert item.identity.platform == "today_history"
        assert item.content.title == "历史上的今天 0912"
        assert "1998 事件甲发生" in (item.content.summary or "")
        assert "1949 事件乙发生" in (item.content.summary or "")

    def test_no_month_day_falls_back_to_plain_title(self) -> None:
        item = build_history_card_content("正文")
        assert item.content.title == "历史上的今天"
        assert item.identity.canonical_url == "about:blank"

    def test_only_real_events_enter_summary(self) -> None:
        body = "历史上的今天 0912\n1998 事件甲发生"
        item = build_history_card_content(body, month_day="0912")
        assert "1998 事件甲发生" in (item.content.summary or "")
        assert "1999" not in (item.content.summary or "")  # 不为凑数编造年份


# ---------------------------------------------------------------------------
# 评审 C2 回归：footer 不泄漏内部伪 URL / 请求 ID；去重键不进 canonical_url。
# ---------------------------------------------------------------------------


class TestCardFooterPrivacy:
    def test_divination_footer_free_of_internal_pseudo_url(
        self, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        message = _message("今日塔罗")
        result = capability(message, _decision("bot.divination"))
        assert result.kind == "mixed"
        html_text = str(backend.captured[0]["html"])
        assert "divination://" not in html_text
        assert "history://" not in html_text
        assert "about:blank" not in html_text  # 占位值被清空，不是渲染出来
        assert message.request_id not in html_text
        assert 'class="footer"' not in html_text  # 无来源卡不渲染页脚区块

    def test_history_footer_free_of_internal_pseudo_url(
        self, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        result = _history_capability(str(tmp_path), backend)(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert result.kind == "mixed"
        html_text = str(backend.captured[0]["html"])
        assert "history://" not in html_text
        assert "about:blank" not in html_text
        assert 'class="footer"' not in html_text

    def test_two_divination_draws_produce_distinct_card_files(
        self, tmp_path: Path
    ) -> None:
        """每次抽牌（不同 request_id）落在独立子目录，文件互不覆写。"""
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        first = capability(_message("抽塔罗"), _decision("bot.divination"))
        second = capability(_message("抽塔罗"), _decision("bot.divination"))
        assert first.images and second.images
        first_path = Path(first.images[0]["file"])
        second_path = Path(second.images[0]["file"])
        assert first_path != second_path
        assert first_path.exists() and second_path.exists()

    def test_history_same_day_cards_share_cache_file(self, tmp_path: Path) -> None:
        """历史上的今天：同日（同 month_day）内容一致，同文件去重。"""
        backend = _FakeBackend()
        capability = _history_capability(str(tmp_path), backend)
        first = capability(_message("历史上的今天"), _decision("bot.today_history"))
        second = capability(_message("历史上的今天"), _decision("bot.today_history"))
        assert first.images and second.images
        assert first.images[0]["file"] == second.images[0]["file"]
        assert Path(first.images[0]["file"]).exists()


# ---------------------------------------------------------------------------
# 占卜能力 × 卡片：mixed 出图。
# ---------------------------------------------------------------------------


class TestDivinationCardRendered:
    def test_bazi_with_backend_is_mixed_and_png_written(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_message("八字 1998年3月2日早上7点"), _decision("bot.divination"))
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        png_path = Path(result.images[0]["file"])
        assert png_path.exists()
        assert png_path.read_bytes() == b"fake-png"
        assert "card_rendered" in result.audit_tags
        # 卡片携带真实排盘数据（1998-03-02 07:00 → 戊寅年 甲寅月 戊申日 丙辰时）。
        html_text = str(backend.captured[0]["html"])
        assert "八字排盘" in html_text
        assert "戊寅" in html_text and "戊申" in html_text and "丙辰" in html_text
        assert "仅供娱乐" in html_text

    def test_tarot_with_backend_is_mixed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        real_random = random.Random

        def _seeded() -> random.Random:
            return real_random(20260912)

        monkeypatch.setattr(random, "Random", _seeded)
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_message("抽塔罗"), _decision("bot.divination"))
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        assert Path(result.images[0]["file"]).exists()
        assert "card_rendered" in result.audit_tags
        html_text = str(backend.captured[0]["html"])
        assert "塔罗" in html_text
        assert "（正位）" in html_text or "（逆位）" in html_text
        assert "关键词" in html_text

    def test_iching_with_backend_is_mixed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        real_random = random.Random

        def _seeded() -> random.Random:
            return real_random(7)

        monkeypatch.setattr(random, "Random", _seeded)
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_message("帮我占卜一下"), _decision("bot.divination"))
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        html_text = str(backend.captured[0]["html"])
        assert "金钱卦" in html_text
        assert "本卦" in html_text and "爻象" in html_text

    def test_daily_tarot_with_backend_is_mixed(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_message("今日塔罗"), _decision("bot.divination"))
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        html_text = str(backend.captured[0]["html"])
        assert "今日塔罗" in html_text
        assert "每日一抽" in html_text


# ---------------------------------------------------------------------------
# 占卜能力 × 回退：后端缺失/失败 → 与无卡片时逐字节一致。
# ---------------------------------------------------------------------------


class TestDivinationFallback:
    @pytest.mark.parametrize(
        "text", ["八字 1998年3月2日早上7点", "塔罗 每日一抽"]
    )
    def test_failing_backends_keep_body_byte_identical(
        self, text: str, tmp_path: Path
    ) -> None:
        baseline = build_divination_capability(None)(
            _message(text), _decision("bot.divination")
        )
        assert baseline.kind == "divination"
        assert baseline.images == []
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = build_divination_capability(
                _StubConfig(str(tmp_path)), render_backend=backend
            )(_message(text), _decision("bot.divination"))
            assert result.kind == "divination"
            assert result.images == []
            assert result.body == baseline.body
            assert "text_only" in result.audit_tags

    @pytest.mark.parametrize("text", ["抽塔罗", "塔罗 三张", "占卜"])
    def test_random_draws_fallback_body_identical(
        self, text: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 抽牌/起卦内部用无种子 random.Random：钉住种子让两次调用逐字节可比。
        real_random = random.Random

        def _seeded() -> random.Random:
            return real_random(42)

        monkeypatch.setattr(random, "Random", _seeded)
        baseline = build_divination_capability(None)(
            _message(text), _decision("bot.divination")
        )
        assert baseline.kind == "divination"
        assert baseline.images == []
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = build_divination_capability(
                _StubConfig(str(tmp_path)), render_backend=backend
            )(_message(text), _decision("bot.divination"))
            assert result.kind == "divination"
            assert result.images == []
            assert result.body == baseline.body

    def test_error_paths_never_render_cards(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        invalid = capability(_message("八字 1998年2月30日"), _decision("bot.divination"))
        assert invalid.kind == "divination"
        assert invalid.images == []
        out_of_range = capability(_message("排盘 1850年5月1日"), _decision("bot.divination"))
        assert out_of_range.kind == "divination"
        assert out_of_range.images == []
        assert backend.captured == []  # 错误提示路径不出卡


# ---------------------------------------------------------------------------
# 历史上的今天 × 卡片。
# ---------------------------------------------------------------------------


class TestTodayHistoryCard:
    def test_events_with_backend_is_mixed_and_png_written(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        result = _history_capability(str(tmp_path), backend)(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        png_path = Path(result.images[0]["file"])
        assert png_path.exists()
        assert png_path.read_bytes() == b"fake-png"
        assert "card_rendered" in result.audit_tags
        html_text = str(backend.captured[0]["html"])
        assert "历史上的今天" in html_text
        assert "1998 事件甲发生" in html_text
        assert "1949 事件乙发生" in html_text

    def test_failing_backends_keep_body_byte_identical(self, tmp_path: Path) -> None:
        baseline = _history_capability(str(tmp_path))(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert baseline.kind == "text"
        assert baseline.images == []
        assert baseline.body.startswith("历史上的今天")
        assert "1998 事件甲发生" in baseline.body
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = _history_capability(str(tmp_path), backend)(
                _message("历史上的今天"), _decision("bot.today_history")
            )
            assert result.kind == "text"
            assert result.images == []
            assert result.body == baseline.body
            assert "text_only" in result.audit_tags

    def test_fetch_failure_branch_stays_text(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        result = _history_capability(str(tmp_path), backend, _StubProvider([]))(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert result.kind == "text"
        assert result.images == []
        assert "拉取失败" in result.body
        assert backend.captured == []  # 无数据不出卡、不编造
