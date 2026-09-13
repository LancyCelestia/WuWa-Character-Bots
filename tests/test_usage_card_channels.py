"""渠道子行上卡回归（2026-09-13 账单展示层批，全离线）。

锁定 ``/bot model usage`` 账单展示三态：
- 有渠道数据（账本开）：Mica 卡（usage_report_mica_html）家族行下渲染
  ``.crow`` 玻璃胶囊子行（渠道名+次数+费用，build_model_rows 费用降序
  原样透传）；交互文本（runtime_admin 链路）出 ``└ 渠道`` 缩进子行，
  折叠口径与 usage_monitor 一致（_usage_channel_stats 家族键归一）；
- 账本关/无渠道数据：卡面 HTML 零渠道痕迹（无 .crow CSS/markup、相位
  不变）＝与旧版字节级一致（改动前副本 A/B 实测佐证见交付报告）；交互
  文本零 ``└ 渠道`` 行；
- 渠道数据空（channels=[]）：不渲染空子行壳，且与无键情况字节一致
  （相位 digest 对空 channels 归一）。

另锁：账本读失败不阻塞账单（文本回退无子行）；渠道 id HTML 转义；
带子行时渲染契约红线不破（两枚阴影 token/无 viewport/字重≤700）。
"""

from __future__ import annotations

import re
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import plugins.bot_unified_runtime.llm.ledger as ledger_mod
from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    _handle_model_command,
    _usage_channel_stats,
)
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    derive_wash_tokens,
)
from plugins.bot_unified_runtime.output.card_render.usage_cards import (
    usage_card_accent,
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore
from plugins.bot_unified_runtime.runtime.usage_monitor import build_model_rows

_ACCENT = "#318ce7"


class _StubConfig:
    def __init__(self, card_color: str = _ACCENT) -> None:
        self.bot_help_card_color = card_color


_AGGREGATE = {
    "prompt_tokens": 1200,
    "cache_read_tokens": 300,
    "cache_write_tokens": 400,
    "completion_tokens": 560,
    "total_tokens": 2460,
    "calls": 12,
    "cost_milli": 1500,
    "unpriced_calls": 0,
}

_MODEL_ROWS = [
    {
        "model": "model-alpha",
        "prompt": 1000,
        "cache_read": 300,
        "cache_write": 400,
        "completion": 500,
        "cost_text": "1.50",
        "priced": True,
        # build_model_rows 渠道子行形状：按费用降序排好的列表。
        "channels": [
            {"channel": "ch-a", "calls": 1234, "cost_milli": 4500, "cost_text": "4.50"},
            {"channel": "ch-b", "calls": 2, "cost_milli": 100, "cost_text": "0.10"},
        ],
    },
    {
        "model": "model-beta",
        "prompt": 200,
        "cache_read": 0,
        "cache_write": 0,
        "completion": 60,
        "cost_text": "未计价",
        "priced": False,
    },
]


def _html(model_rows: list[dict[str, Any]] | None = None, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "kicker": "定时报告 · 模型用量",
        "title": "模型用量账单报告",
        "status_label": "账单 1.50 元",
        "status_kind": "ok",
        "window_label": "09-13 13:00 至 09-13 18:00",
        "generated_at": "2026-09-13 18:00:00",
        "totals": dict(_AGGREGATE),
        "model_rows": [dict(row) for row in (model_rows or _MODEL_ROWS)],
    }
    kwargs.update(overrides)
    return usage_report_mica_html(_StubConfig(), **kwargs)


# ---------------------------------------------------------------------------
# 有渠道数据：子行渲染（名称/次数/费用/顺序/转义/契约红线）。
# ---------------------------------------------------------------------------


class TestUsageCardChannelSubrows:
    def test_channel_subrows_rendered_with_name_calls_cost(self) -> None:
        html_text = _html()
        assert '<div class="crow glass">' in html_text
        assert '└ 渠道 ch-a</span>' in html_text
        assert 'title="ch-a"' in html_text
        assert "1,234 次" in html_text
        assert '<span class="ccost">4.50</span> 元' in html_text
        # 子行样式只在有渠道数据时注入 <style>（token 全 var() 引用）。
        assert ".crow { margin-left:26px;" in html_text
        assert "border-radius:var(--r-tile)" in html_text
        assert "color:var(--accent-ink)" in html_text

    def test_channel_order_passthrough_cost_desc(self) -> None:
        # build_model_rows 已按费用降序排好；渲染层原样透传（ch-a 在 ch-b 前）。
        html_text = _html()
        assert html_text.index("└ 渠道 ch-a") < html_text.index("└ 渠道 ch-b")

    def test_row_without_channels_gets_no_subrow_shell(self) -> None:
        html_text = _html()
        # model-beta 无渠道数据 → 只有 model-alpha 的两个子行，无空壳。
        assert html_text.count('<div class="crow glass">') == 2

    def test_channel_id_html_escaped(self) -> None:
        rows = [dict(_MODEL_ROWS[0], channels=[
            {"channel": "<b>evil</b>", "calls": 1, "cost_milli": 1, "cost_text": "0.01"},
        ])]
        html_text = _html(model_rows=rows)
        assert "&lt;b&gt;evil&lt;/b&gt;" in html_text
        assert "<b>evil</b>" not in html_text

    def test_render_contract_basics_hold_with_channels(self) -> None:
        html_text = _html()
        low = html_text.lower()
        assert "name=\"viewport\"" not in low and "<meta viewport" not in low
        assert "background:transparent" in low
        assert 'class="stage card"' in html_text
        assert html_text.count("--mica-shadow:") == 1
        assert html_text.count("--mica-shadow-soft:") == 1
        for banned in ("font-weight:8", "font-weight:9", "font-weight: 8", "font-weight: 9"):
            assert banned not in low

    def test_wash_tokens_unchanged_with_channels(self) -> None:
        html_text = _html()
        accent, _ink = usage_card_accent(_StubConfig())
        expected = derive_wash_tokens(accent)
        match = re.search(r"--wash-mist:(#[0-9a-f]{6})", html_text)
        assert match is not None
        assert match.group(1) == expected["wash_mist"]


# ---------------------------------------------------------------------------
# 账本关/无渠道数据：字节级零回归；空 channels 不渲染壳且相位归一。
# ---------------------------------------------------------------------------


class TestUsageCardChannelZeroRegression:
    def test_no_channel_data_html_has_zero_channel_artifacts(self) -> None:
        rows = [{key: value for key, value in row.items() if key != "channels"} for row in _MODEL_ROWS]
        html_text = _html(model_rows=rows)
        assert "crow" not in html_text
        assert "cmeta" not in html_text
        assert "ccost" not in html_text
        assert "└ 渠道" not in html_text

    def test_empty_channels_byte_identical_to_missing_key(self) -> None:
        without_key = [
            {key: value for key, value in row.items() if key != "channels"}
            for row in _MODEL_ROWS
        ]
        empty_list = [dict(row, channels=[]) for row in without_key]
        # 空列表 = 无数据：不渲染壳，相位 digest 归一后整卡字节一致。
        assert _html(model_rows=empty_list) == _html(model_rows=without_key)

    def test_empty_channels_only_row_renders_no_shell(self) -> None:
        rows = [dict(_MODEL_ROWS[0], channels=[])]
        html_text = _html(model_rows=rows)
        assert "crow" not in html_text
        assert "└ 渠道" not in html_text


# ---------------------------------------------------------------------------
# 交互文本链路（runtime_admin._handle_model_command usage 分支）。
# ---------------------------------------------------------------------------


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_model_registry={
            "ds": {
                "model": "deepseek-v4-pro",
                "base_url": "https://x/v1",
                "api_key": "env:BOT_API_KEY_X",
                "tags": ["low", "high", "max"],
                "priority": 1,
            }
        },
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_prices={},
    )


def _temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="usage-card-ch-"))


def _usage_store() -> SimpleNamespace:
    return SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_milli": 1500,
            "calls": 3,
            "by_model": {"m1-pro": 1500},
            "by_model_prompt": {"m1-pro": 1000},
            "by_model_completion": {"m1-pro": 500},
            "by_model_cost_milli": {"m1-pro": 1500},
            "by_model_calls": {"m1-pro": 3},
            "unpriced_calls": 0,
        }
    )


_CHANNEL_RAW = {
    ("m1-pro", "ch-a"): {"calls": 1234, "cost_milli": 4500},
    ("m1-pro", "ch-b"): {"calls": 2, "cost_milli": 100},
}


class TestInteractiveUsageChannelLines:
    def test_ledger_off_text_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)
        store = RuntimeSettingsStore(_temp_dir() / "settings.json")
        result = _handle_model_command(
            store, _fake_config(), ["usage"], usage_store=_usage_store()
        )
        assert "- m1-pro（未配置价格）：入 1,000 / 出 500 / 共 1,500 / 费 未计价" in result  # I6：不挂悬空元
        assert "└ 渠道" not in result

    def test_ledger_on_renders_channel_sublines_cost_desc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ledger_mod, "ledger_enabled", lambda config=None: True)
        monkeypatch.setattr(ledger_mod, "resolve_default_db_path", lambda: "unused")
        monkeypatch.setattr(
            ledger_mod,
            "aggregate_channel_usage",
            lambda db_path, *, start_day, end_day, since_iso="": dict(_CHANNEL_RAW),
        )
        store = RuntimeSettingsStore(_temp_dir() / "settings.json")
        result = _handle_model_command(
            store, _fake_config(), ["usage"], usage_store=_usage_store()
        )
        assert "  └ 渠道 ch-a：1,234 次 / 费 4.50 元" in result
        assert "  └ 渠道 ch-b：2 次 / 费 0.10 元" in result
        assert result.index("└ 渠道 ch-a") < result.index("└ 渠道 ch-b")
        # 子行挂在对应家族行之后。
        assert result.index("- m1-pro（未配置价格）：") < result.index("└ 渠道 ch-a")

    def test_ledger_read_failure_falls_back_to_no_sublines(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ledger_mod, "ledger_enabled", lambda config=None: True)
        monkeypatch.setattr(ledger_mod, "resolve_default_db_path", lambda: "unused")

        def _boom(*args: Any, **kwargs: Any) -> dict[Any, Any]:
            raise RuntimeError("db locked")

        monkeypatch.setattr(ledger_mod, "aggregate_channel_usage", _boom)
        store = RuntimeSettingsStore(_temp_dir() / "settings.json")
        result = _handle_model_command(
            store, _fake_config(), ["usage"], usage_store=_usage_store()
        )
        assert "- m1-pro（未配置价格）：入 1,000 / 出 500 / 共 1,500 / 费 未计价" in result
        assert "└ 渠道" not in result

    def test_usage_channel_stats_folds_family_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 大小写变体 + 档位后缀归一同家族（与 usage_monitor 折叠口径一致）。
        raw = {
            ("M1-Pro", "ch-a"): {"calls": 1, "cost_milli": 10},
            ("m1-pro-high", "ch-b"): {"calls": 2, "cost_milli": 20},
        }
        monkeypatch.setattr(ledger_mod, "ledger_enabled", lambda config=None: True)
        monkeypatch.setattr(ledger_mod, "resolve_default_db_path", lambda: "unused")
        monkeypatch.setattr(
            ledger_mod,
            "aggregate_channel_usage",
            lambda db_path, *, start_day, end_day, since_iso="": raw,
        )
        stats = _usage_channel_stats(_fake_config(), date(2026, 9, 13))
        assert stats is not None
        assert set(stats) == {"m1-pro"}
        assert stats["m1-pro"]["ch-a"] == {"calls": 1, "cost_milli": 10}
        assert stats["m1-pro"]["ch-b"] == {"calls": 2, "cost_milli": 20}

    def test_usage_channel_stats_ledger_disabled_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)
        assert _usage_channel_stats(_fake_config(), date(2026, 9, 13)) is None


# ---------------------------------------------------------------------------
# 端到端（离线）：真实 build_model_rows + 渠道统计 → 卡面子行。
# ---------------------------------------------------------------------------


class TestCardWithRealBuildModelRows:
    def test_family_row_channels_flow_into_card(self) -> None:
        aggregate = {
            "by_model": {"m1-pro": 1500},
            "by_model_prompt": {"m1-pro": 1000},
            "by_model_completion": {"m1-pro": 500},
            "by_model_cost_milli": {"m1-pro": 4600},
            "by_model_calls": {"m1-pro": 3},
        }
        channel_stats = {
            "m1-pro": {
                "ch-a": {"calls": 1234, "cost_milli": 4500},
                "ch-b": {"calls": 2, "cost_milli": 100},
            }
        }
        rows = build_model_rows(aggregate, channel_stats=channel_stats)
        assert [sub["channel"] for sub in rows[0]["channels"]] == ["ch-a", "ch-b"]
        html_text = _html(model_rows=rows)
        assert html_text.index("└ 渠道 ch-a") < html_text.index("└ 渠道 ch-b")
        assert '<div class="crow glass">' in html_text
