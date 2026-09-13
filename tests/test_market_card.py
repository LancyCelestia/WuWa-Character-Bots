"""render_market_card_html + 行情能力卡片链路契约（C 方向补齐，2026-09-12）。

市场卡此前是唯一零测试覆盖的模板函数。本文件锁定：
- 分组/行/涨跌徽章/涨跌额渲染与红涨绿跌折线语义；
- 无历史走势指数（MOEX）的 trend_note 明示契约——不伪造折线；
- 数据源/数据时间/延迟提示脚注；
- 根元素 .card（元素截图契约）与恶意载荷转义；
- 能力层卡片胶水：payload 组装（change/trend_note 进入渲染）、
  后端失败/缺失回退纯文字（text_only 审计标签）。

全部离线：HTML 渲染纯字符串断言；能力层 monkeypatch 数据源 + 假渲染后端。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.market import (
    build_market_capability,
    is_market_command,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_market_card_html,
)
from plugins.bot_unified_runtime.sources.market_data import IndexQuote

_PAYLOAD: dict[str, Any] = {
    "subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘",
    "groups": [
        {
            "name": "中国区",
            "rows": [
                {
                    "name": "上证指数",
                    "price": "3934.40",
                    "pct": "-0.43%",
                    "change": "-17.11",
                    "change_pct": -0.43,
                    "trend": [3900.0, 3920.5, 3934.4],
                },
                {
                    "name": "俄罗斯MOEX",
                    "price": "2610.50",
                    "pct": "+0.20%",
                    "change": "+5.20",
                    "change_pct": 0.2,
                    "trend": [],
                    "trend_note": "暂无历史走势数据",
                },
            ],
        },
        {
            "name": "欧美",
            "rows": [
                {
                    "name": "道琼斯",
                    "price": "42114.40",
                    "pct": "+0.58%",
                    "change": "+242.11",
                    "change_pct": 0.58,
                    "trend": [41800.0, 42000.0, 42114.4],
                }
            ],
        },
    ],
    "source_note": "数据源：东方财富 · MOEX ISS（俄罗斯）",
    "updated_at": "2026-09-12 20:00:00",
    "delayed_note": "部分海外指数行情可能有延迟",
}


def test_market_card_renders_rows_and_change_abs() -> None:
    html_text = render_market_card_html(_PAYLOAD)
    for name in ("上证指数", "俄罗斯MOEX", "道琼斯"):
        assert name in html_text
    for price in ("3934.40", "2610.50", "42114.40"):
        assert price in html_text
    for badge in ("+0.58%", "-0.43%"):
        assert badge in html_text
    # 涨跌额（C 方向新增字段）：带符号展示。
    assert "-17.11" in html_text
    assert "+242.11" in html_text
    # 涨跌语义 class。
    assert "pct up" in html_text
    assert "pct down" in html_text


def test_market_card_sparkline_direction_colors() -> None:
    html_text = render_market_card_html(_PAYLOAD)
    # 两条有走势的指数各出一条 polyline；收涨红 / 收跌绿。
    assert html_text.count("<polyline") == 2
    assert "#d54941" in html_text  # 道琼斯收涨 → 红
    assert "#2e9e6b" in html_text  # 上证收跌 → 绿


def test_market_card_moex_trend_gap_note_no_fake_line() -> None:
    """无历史 K 线源的指数（MOEX）：明示「暂无历史走势数据」，绝不伪造折线。"""
    html_text = render_market_card_html(_PAYLOAD)
    assert "暂无历史走势数据" in html_text


def test_market_card_data_footer() -> None:
    html_text = render_market_card_html(_PAYLOAD)
    assert "数据源：东方财富 · MOEX ISS（俄罗斯）" in html_text
    assert "数据时间 2026-09-12 20:00:00" in html_text
    assert "部分海外指数行情可能有延迟" in html_text


def test_market_card_root_has_card_class_and_no_viewport() -> None:
    html_text = render_market_card_html(_PAYLOAD)
    assert '<div class="shell card">' in html_text
    assert "viewport" not in html_text


def test_market_card_empty_payload_renders_safely() -> None:
    html_text = render_market_card_html({})
    assert "全球股指速览" in html_text
    assert "守岸人" in html_text
    assert "None" not in html_text


def test_market_card_escapes_malicious_payload() -> None:
    payload = {
        "groups": [
            {
                "name": "<script>alert(1)</script>",
                "rows": [
                    {
                        "name": "<img src=x onerror=alert(2)>",
                        "price": "1",
                        "pct": "0%",
                        "change_pct": 0,
                        "trend_note": "<b>fake</b>",
                    }
                ],
            }
        ],
        "source_note": "<script>alert(3)</script>",
    }
    html_text = render_market_card_html(payload)
    assert "<script>alert" not in html_text
    assert "<img src=x" not in html_text
    assert "&lt;script&gt;" in html_text


# ==================== 能力层卡片胶水（假后端，离线） ====================
class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.captured: dict[str, Any] | None = None

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.captured = payload
        return b"fake-png"


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-market-card-test",
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
        request_id="req-market-card-test",
        should_respond=True,
        mode="command",
        trigger="行情",
        capability_id="bot.market",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


_QUOTES = [
    IndexQuote("上证指数", "1.000001", 3934.4, -0.43, -17.11),
    IndexQuote("俄罗斯MOEX", "100.IMOEX", 2610.5, 0.2, 5.2),
]


def test_market_capability_card_payload_carries_change_and_gap_note(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: list(_QUOTES),
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_trend",
        lambda secid, timeout_seconds=6.0: (
            (3900.0, 3920.5, 3934.4) if secid == "1.000001" else ()
        ),
    )
    backend = _FakeBackend()
    config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
    capability = build_market_capability(config, render_backend=backend)
    result = capability(_make_message("行情"), _make_decision())

    assert result.kind == "mixed"
    assert "card_rendered" in result.audit_tags
    assert (tmp_path / "market_5ae3d93ba2d9.png").exists() or any(
        p.name.startswith("market_") for p in tmp_path.iterdir()
    )
    html_text = backend.captured["html"]
    assert "-17.11" in html_text  # 涨跌额进入渲染
    assert "暂无历史走势数据" in html_text  # MOEX 走势缺口明示
    assert "数据源：东方财富 · MOEX ISS（俄罗斯）" in html_text


def test_market_capability_backend_failure_falls_back_to_text(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: list(_QUOTES),
    )

    class _BrokenBackend:
        name = "broken"
        available = True

        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            return None

    config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
    capability = build_market_capability(config, render_backend=_BrokenBackend())
    result = capability(_make_message("行情"), _make_decision())
    assert result.kind == "text"
    assert "text_only" in result.audit_tags
    assert "上证指数" in result.body


def test_market_capability_without_backend_is_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: list(_QUOTES),
    )
    capability = build_market_capability(config=None)
    result = capability(_make_message("行情"), _make_decision())
    assert result.kind == "text"
    assert "text_only" in result.audit_tags


# ---------------------------------------------------------------------------
# 多源交叉查验（腾讯）+ 繁体触发 + kline end 参数回归（C 方向增量 2026-09-13）
# ---------------------------------------------------------------------------


class TestMarketCrossCheck:
    def _quotes(self):
        from plugins.bot_unified_runtime.sources.market_data import IndexQuote

        return [
            IndexQuote("上证指数", "1.000001", 3888.11, -1.18, -46.29),
            IndexQuote("道琼斯", "100.DJIA", 52573.29, 0.98, 509.19),
            IndexQuote("俄罗斯MOEX", "100.IMOEX", 2281.04, -1.21, -27.89),
        ]

    def test_matched_declares_verification(self, monkeypatch):
        from plugins.bot_unified_runtime.sources import market_crosscheck as mc

        mc.reset_crosscheck_cache()
        monkeypatch.setattr(
            mc,
            "_fetch_tencent_snapshot",
            lambda codes, timeout_seconds: {
                "1.000001": (3888.11, -1.18),
                "100.DJIA": (52573.29, 0.98),
            },
        )
        result = mc.crosscheck_quotes(self._quotes())
        assert result.checked == 2 and result.matched == 2 and result.ok
        note = mc.format_crosscheck_note(result)
        assert "已与腾讯行情交叉核验 ✓ 2/2" in note

    def test_mismatch_declares_divergence(self, monkeypatch):
        from plugins.bot_unified_runtime.sources import market_crosscheck as mc

        mc.reset_crosscheck_cache()
        monkeypatch.setattr(
            mc,
            "_fetch_tencent_snapshot",
            lambda codes, timeout_seconds: {"1.000001": (3950.0, +1.0)},
        )
        result = mc.crosscheck_quotes(self._quotes())
        assert not result.ok
        note = mc.format_crosscheck_note(result)
        assert "⚠" in note and "3950.00" in note

    def test_unavailable_channel_stays_silent(self, monkeypatch):
        from plugins.bot_unified_runtime.sources import market_crosscheck as mc

        mc.reset_crosscheck_cache()

        def _boom(codes, timeout_seconds):
            raise OSError("network down")

        monkeypatch.setattr(mc, "_fetch_tencent_snapshot", _boom)
        result = mc.crosscheck_quotes(self._quotes())
        assert result.checked == 0
        assert mc.format_crosscheck_note(result) == ""  # 不声明、不阻塞

    def test_capability_card_carries_crosscheck_note(self, monkeypatch, tmp_path):
        quotes = self._quotes()
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
            lambda timeout_seconds, cache_seconds: list(quotes),
        )
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.market.fetch_index_trend",
            lambda secid, timeout_seconds=6.0: (3900.0, 3888.11),
        )
        from plugins.bot_unified_runtime.sources import market_crosscheck as mc

        monkeypatch.setattr(
            mc,
            "_fetch_tencent_snapshot",
            lambda codes, timeout_seconds: {
                "1.000001": (3888.11, -1.18),
                "100.DJIA": (52573.29, 0.98),
            },
        )
        captured: dict = {}

        class _Backend:
            name = "fake"
            available = True

            def render_card(self, payload):
                captured.update(payload)
                return b"png"

        config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
        capability = build_market_capability(config, render_backend=_Backend())
        result = capability(_make_message("行情"), _make_decision())
        assert result.kind == "mixed"
        html_text = captured["html"]
        assert "已与腾讯行情交叉核验 ✓ 2/2" in html_text
        assert "已与腾讯行情交叉核验" in result.body

    def test_traditional_variant_triggers(self):
        assert is_market_command("大盤")

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("房價大盤", True),  # 繁体守卫与简体同语义（大盤在 hint 表）
            ("显卡大盘", True),  # 大盘是明确股票词（既有语义，非股市守卫被显式词覆盖）
            ("显卡大盤", True),  # 繁体同语义（评审 P1-2：繁简一致）
            ("房價行情", False),  # 繁体非股市词让路（_NON_STOCK_RE 繁体覆盖）
        ],
    )
    def test_traditional_guard_consistency(self, text, expected):
        assert is_market_command(text) is expected


def test_index_trend_url_carries_end_param(monkeypatch):
    """2026-09-13 实测：东财 kline 缺 end 参数返回空 klines——回归锁。"""
    captured: dict = {}

    def _fake_http_get_json(url, **kwargs):
        captured["url"] = url
        return {"data": {"klines": ["2026-09-11,3888.11"]}}

    from plugins.bot_unified_runtime.sources import market_data

    monkeypatch.setattr(market_data, "http_get_json", _fake_http_get_json)
    market_data.reset_market_trend_cache()
    closes = market_data.fetch_index_trend("1.000001")
    assert closes == (3888.11,)
    assert "end=20500101" in captured["url"]


def test_trend_empty_result_not_cached(monkeypatch):
    """失败/空序列不缓存（失败缓存会把缺口钉死 10 分钟）——回归锁。"""
    from plugins.bot_unified_runtime.sources import market_data

    calls: list[int] = []

    def _fake_http_get_json(url, **kwargs):
        calls.append(1)
        return {"data": {"klines": []}}

    monkeypatch.setattr(market_data, "http_get_json", _fake_http_get_json)
    market_data.reset_market_trend_cache()
    assert market_data.fetch_index_trend("1.000001") == ()
    assert market_data.fetch_index_trend("1.000001") == ()
    # 空响应受控重试（bot_market_retry_on_empty）：每次 fetch = 首呼 + 1 次重试，
    # 两次 fetch 共 4 次；仍不写缓存（第二次未被缓存拦下）。
    assert len(calls) == 4
