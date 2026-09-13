"""fx 卡语义回归（评审域 B 发现 6 / C 交接 P3，2026-09-13，全离线）。

锁定三件事：
1. 定向换算查询（「美元兑人民币」等）的卡上显式标注面板语义
   （副标题含「主要货币面板」+ 货币对），消除「问 A 答 B」的 body/card 错位；
2. 卡文件名 digest 纳入查询语义：不同货币对的定向卡不再同名互覆；
   面板卡=同文件幂等（行情刷新覆写同一面板文件）；
3. 既有 fx 回归语义不变：panel/正向/反向/无源四条 body 文案逐字保持，
   面板副标题、audit_tags 口径不变。

离线手段：``fetch_fx_rates`` 打桩、渲染后端 fake（记录 payload、按次编号出 PNG）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.capabilities import fx as fx_cap
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.finance import FxRate

_PANEL_SUBTITLE = "中间价/参考价 · 延迟行情"
_PANEL_BODY = "主要货币汇率速览\n1美元 ≈ 6.71 人民币\n100日元 ≈ 4.36 人民币"
_USDCNY_BODY = "1美元 ≈ 6.71 人民币\n1 USD = 6.7081 CNY（eastmoney · spot）"
_CNYUSD_BODY = "1 CNY ≈ 0.15 USD\n1 CNY = 0.1491 USD（由 USD/CNY 反向换算）"


def _rates() -> list[FxRate]:
    return [
        FxRate(
            base_currency="USD",
            quote_currency="CNY",
            rate=6.7081,
            timestamp="2026-09-12 20:00:00",
            rate_type="spot",
        ),
        FxRate(
            base_currency="JPY",
            quote_currency="CNY",
            rate=4.3614,
            unit_base=100.0,
            timestamp="2026-09-12 20:00:00",
            rate_type="parity",
        ),
    ]


def _rates_alt() -> list[FxRate]:
    """与主夹具数值不同的面板数据：验证面板卡刷新走同一文件。"""
    return [
        FxRate(
            base_currency="USD",
            quote_currency="CNY",
            rate=7.1234,
            timestamp="2026-09-13 08:00:00",
            rate_type="spot",
        )
    ]


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-fx-card-test",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision() -> BotDecision:
    return BotDecision(
        request_id="req-fx-card-test",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id="bot.fx",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self._n = 0

    def render_card(self, payload: dict) -> bytes:
        self.payloads.append(payload)
        self._n += 1
        return f"png-{self._n}".encode()


@pytest.fixture()
def _stub_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.fx_data.fetch_fx_rates",
        lambda timeout_seconds=6.0, cache_seconds=60.0: _rates(),
    )


def _capability(
    tmp_path: Path, backend: _FakeBackend
) -> Callable[[IncomingMessage, BotDecision], object]:
    config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
    return fx_cap.build_fx_capability(config, render_backend=backend)


# ---------------------------------------------------------------------------
# ① 定向查询的卡标注面板语义；body 文案逐字不变
# ---------------------------------------------------------------------------


class TestDirectedQueryCardSemantics:
    def test_directed_pair_card_annotates_panel_semantics(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        result = capability(_make_message("美元兑人民币"), _make_decision())
        assert result.kind == "mixed"
        html_text = backend.payloads[0]["html"]
        assert "主要货币面板" in html_text
        assert "USD兑CNY" in html_text
        # 面板分区语义保持：卡上仍是完整主要货币面板（USD 基准）。
        assert "主要货币（USD 基准面板）" in html_text

    def test_inverted_pair_card_annotates_panel_semantics(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        result = capability(_make_message("人民币兑美元"), _make_decision())
        assert result.kind == "mixed"
        html_text = backend.payloads[0]["html"]
        assert "主要货币面板" in html_text
        assert "CNY兑USD" in html_text

    def test_directed_pair_body_copy_byte_identical(self, _stub_fetch: None) -> None:
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑人民币"), _make_decision())
        assert result.body == _USDCNY_BODY
        assert result.title == "USD兑CNY"
        assert "fx:pair:USD/CNY" in result.audit_tags

    def test_inverted_pair_body_copy_byte_identical(self, _stub_fetch: None) -> None:
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("人民币兑美元"), _make_decision())
        assert result.body == _CNYUSD_BODY
        assert result.title == "CNY兑USD"
        assert "fx:pair:USD/CNY" in result.audit_tags

    def test_panel_body_copy_byte_identical(self, _stub_fetch: None) -> None:
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("汇率"), _make_decision())
        assert result.body == _PANEL_BODY
        assert result.title == "汇率速览"
        assert "fx:major_panel" in result.audit_tags

    def test_panel_card_subtitle_unchanged(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        result = capability(_make_message("汇率"), _make_decision())
        assert result.kind == "mixed"
        html_text = backend.payloads[0]["html"]
        assert _PANEL_SUBTITLE in html_text
        # 面板查询卡上不出现定向标注。
        assert "主要货币面板" not in html_text

    def test_unavailable_pair_keeps_plain_panel_card(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        # 无源货币对：body 明说暂无数据；卡上没有换算结果可指，
        # 保持无标注的 plain 面板（不声称「换算结果见消息文字」）。
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        result = capability(_make_message("美元兑新台币"), _make_decision())
        assert "暂无数据" in result.body
        html_text = backend.payloads[0]["html"]
        assert _PANEL_SUBTITLE in html_text
        assert "主要货币面板" not in html_text


# ---------------------------------------------------------------------------
# ② 卡文件名语义：定向按货币对分文件，面板同文件幂等
# ---------------------------------------------------------------------------


class TestCardFilenameSemantics:
    def test_distinct_queries_never_overwrite_each_other(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        r_panel = capability(_make_message("汇率"), _make_decision())
        r_usdcny = capability(_make_message("美元兑人民币"), _make_decision())
        r_jpycny = capability(_make_message("日元汇率"), _make_decision())
        name_panel = Path(r_panel.images[0]["file"]).name
        name_usdcny = Path(r_usdcny.images[0]["file"]).name
        name_jpycny = Path(r_jpycny.images[0]["file"]).name
        assert len({name_panel, name_usdcny, name_jpycny}) == 3
        # 第一张卡未被后续同名覆写：内容仍是各自那次渲染的字节。
        assert (tmp_path / name_panel).read_bytes() == b"png-1"
        assert (tmp_path / name_usdcny).read_bytes() == b"png-2"
        assert (tmp_path / name_jpycny).read_bytes() == b"png-3"

    def test_panel_card_is_same_file_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.sources.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _rates(),
        )
        r1 = capability(_make_message("汇率"), _make_decision())
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.sources.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _rates_alt(),
        )
        r2 = capability(_make_message("汇率"), _make_decision())
        # 面板卡=同文件幂等：行情数值刷新仍覆写同一枚面板文件。
        assert Path(r1.images[0]["file"]).name == Path(r2.images[0]["file"]).name
        files = list(tmp_path.glob("fx_*.png"))
        assert len(files) == 1
        assert files[0].read_bytes() == b"png-2"

    def test_same_pair_different_amounts_share_file(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        r1 = capability(_make_message("美元兑人民币"), _make_decision())
        r2 = capability(_make_message("1000美元兑人民币"), _make_decision())
        # 卡面不承载金额（换算结果在消息文字里）：同货币对共用一枚文件。
        assert Path(r1.images[0]["file"]).name == Path(r2.images[0]["file"]).name
        assert len(list(tmp_path.glob("fx_*.png"))) == 1

    def test_directed_and_panel_files_differ(
        self, _stub_fetch: None, tmp_path: Path
    ) -> None:
        backend = _FakeBackend()
        capability = _capability(tmp_path, backend)
        r_panel = capability(_make_message("汇率"), _make_decision())
        r_directed = capability(_make_message("美元兑人民币"), _make_decision())
        assert (
            Path(r_panel.images[0]["file"]).name
            != Path(r_directed.images[0]["file"]).name
        )
