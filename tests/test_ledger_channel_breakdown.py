"""账本渠道维度聚合 + 报告家族行渠道子行 + 价格家族匹配边界（2026-09-13 账单批）。

锁定：①aggregate_channel_usage 按 (实际模型, 渠道) 只读聚合（缺库/坏库
返回 {}，绝不抛）；②build_model_rows / build_report_text 在账本渠道统计
下渲染「家族行 → 渠道子行」，同模型跨渠道费用可追溯，未提供时行为与
旧版一致；③价格家族匹配边界（精确优先于家族、按次/大小写、前缀家族如
``c-gemini-*`` 不被误剥）。全部离线（临时 SQLite，实写实读）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
    lookup_model_price,
    model_family_key,
    parse_model_prices,
)
from plugins.bot_unified_runtime.domains.ops.monitor.usage_monitor import (
    build_model_rows,
    build_report_alert,
    build_report_text,
)
from plugins.bot_unified_runtime.llm.ledger import (
    LedgerService,
    aggregate_channel_usage,
    build_call_draft,
)

# ==================== ① 账本按 (模型, 渠道) 聚合 ====================


def _write_call(db_path: Path, **overrides: object) -> None:
    """桩写线程（不起后台线程）：submit + flush 全同步，实写实读。"""
    usage: dict[str, object] = {
        key: overrides.pop(key)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if key in overrides
    }
    service = LedgerService(
        str(db_path), writer_thread=threading.Thread(target=lambda: None)
    )
    try:
        draft = build_call_draft(
            request_id=str(overrides.pop("request_id", "r1")),
            session_id="sess",
            capability="chat",
            started_at="2026-09-13T12:00:00.000+08:00",
            completed_at=str(
                overrides.pop("completed_at", "2026-09-13T12:00:01.000+08:00")
            ),
            status=str(overrides.pop("status", "success")),
            usage=usage,
            **overrides,  # type: ignore[arg-type]
        )
        service.submit(draft)
        assert service.flush() == 1
    finally:
        service.close()


def test_aggregate_channel_usage_splits_channels_per_model(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_call(
        db,
        request_id="r1",
        provider_id="ch-a",
        model_id="ch-a",
        actual_model="gemini-3.8-flash-high",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        price_in=4.5,
        price_out=22.5,
    )
    _write_call(
        db,
        request_id="r2",
        provider_id="ch-b",
        model_id="ch-b",
        actual_model="Gemini-3.8-Flash",
        prompt_tokens=2000,
        completion_tokens=100,
        total_tokens=2100,
        price_in=0.3,
        price_out=1.5,
    )
    _write_call(
        db,
        request_id="r3",
        provider_id="ch-b",
        model_id="ch-b",
        actual_model="gemini-3.8-flash",
        prompt_tokens=100_000,
        completion_tokens=50_000,
        total_tokens=150_000,
        price_in=0.3,
        price_out=1.5,
    )

    raw = aggregate_channel_usage(
        str(db), start_day="2026-09-13", end_day="2026-09-13"
    )

    # (实际模型名, 渠道) 按原始名分组（家族折叠由 usage_monitor 层做）：
    # 同模型跨渠道拆分，渠道差异可追溯。
    assert set(raw) == {
        ("gemini-3.8-flash-high", "ch-a"),
        ("Gemini-3.8-Flash", "ch-b"),
        ("gemini-3.8-flash", "ch-b"),
    }
    assert raw[("gemini-3.8-flash-high", "ch-a")]["calls"] == 1
    assert raw[("gemini-3.8-flash-high", "ch-a")]["total_tokens"] == 1500
    assert raw[("Gemini-3.8-Flash", "ch-b")]["calls"] == 1
    ch_b = raw[("gemini-3.8-flash", "ch-b")]
    assert ch_b["calls"] == 1
    assert ch_b["prompt_tokens"] == 100_000
    # 100k×0.3/1000 + 50k×1.5/1000 = 30 + 75 = 105 毫厘。
    assert ch_b["cost_milli"] == 105


def test_aggregate_channel_usage_day_window_and_failures(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_call(
        db,
        request_id="ok",
        provider_id="ch-a",
        model_id="ch-a",
        actual_model="m",
        completed_at="2026-09-13T23:59:59.000+08:00",
        prompt_tokens=10,
        total_tokens=10,
        price_in=1.0,
        price_out=1.0,
    )
    _write_call(
        db,
        request_id="bad",
        provider_id="ch-b",
        model_id="ch-b",
        actual_model="m",
        completed_at="2026-09-14T00:00:01.000+08:00",
        status="provider_failed",
        total_tokens=0,
    )

    day13 = aggregate_channel_usage(
        str(db), start_day="2026-09-13", end_day="2026-09-13"
    )
    assert set(day13) == {("m", "ch-a")}
    day14 = aggregate_channel_usage(
        str(db), start_day="2026-09-14", end_day="2026-09-14"
    )
    failed = day14[("m", "ch-b")]
    assert failed["calls"] == 1
    assert failed["failed_calls"] == 1
    assert failed["cost_milli"] == 0


def test_aggregate_channel_usage_missing_db_returns_empty(tmp_path: Path) -> None:
    assert (
        aggregate_channel_usage(
            str(tmp_path / "nope.sqlite3"),
            start_day="2026-09-13",
            end_day="2026-09-13",
        )
        == {}
    )
    assert (
        aggregate_channel_usage("", start_day="2026-09-13", end_day="2026-09-13")
        == {}
    )


# ==================== ② 报告家族行 → 渠道子行 ====================


def _aggregate() -> dict[str, object]:
    return {
        "prompt_tokens": 3_000,
        "completion_tokens": 600,
        "total_tokens": 3_600,
        "calls": 3,
        "cost_milli": 5_730,
        "by_model": {"gemini-3.8-flash-high": 3_600},
        "by_model_prompt": {"gemini-3.8-flash-high": 3_000},
        "by_model_completion": {"gemini-3.8-flash-high": 600},
        "by_model_cost_milli": {"gemini-3.8-flash-high": 5_730},
        "by_model_calls": {"gemini-3.8-flash-high": 3},
        "by_model_unpriced": {},
        "unpriced_calls": 0,
    }


def _channel_stats() -> dict[str, dict[str, dict[str, int]]]:
    # 家族键 → 渠道 → 统计（aggregate_channel_usage 折叠家族后的形状）。
    return {
        "gemini-3.8-flash": {
            "ch-b": {"calls": 2, "cost_milli": 1_230, "failed_calls": 0},
            "ch-a": {"calls": 1, "cost_milli": 4_500, "failed_calls": 1},
        }
    }


def test_build_model_rows_attaches_channel_subrows_cost_desc() -> None:
    rows = build_model_rows(_aggregate(), channel_stats=_channel_stats())
    assert len(rows) == 1
    channels = rows[0]["channels"]
    assert [item["channel"] for item in channels] == ["ch-a", "ch-b"]  # 费用降序
    assert channels[0]["cost_text"] == "4.50"
    assert channels[1]["calls"] == 2


def test_build_model_rows_without_channel_stats_unchanged() -> None:
    rows = build_model_rows(_aggregate())
    assert "channels" not in rows[0]


def test_build_report_text_renders_channel_subrows() -> None:
    text = build_report_text(
        _aggregate(),
        window_label="测试窗口",
        channel_stats=_channel_stats(),
    )
    assert "- gemini-3.8-flash-high：入 3,000 / 缓存读 0 / 缓存建 0 / 出 600 / 费 5.73 元" in text
    assert "  └ 渠道 ch-a：1 次 / 费 4.50 元" in text
    assert "  └ 渠道 ch-b：2 次 / 费 1.23 元" in text
    # 未提供渠道统计：无子行（旧版形态）。
    plain = build_report_text(_aggregate(), window_label="测试窗口")
    assert "└ 渠道" not in plain


def test_build_report_alert_carries_channel_subrows() -> None:
    alert = build_report_alert(
        _aggregate(),
        window_label="测试窗口",
        channel_stats=_channel_stats(),
    )
    assert "└ 渠道 ch-a" in alert.what_happened


def test_channel_subrows_merge_cross_channel_family_rows() -> None:
    """同模型三种写法 + 两个渠道：主行合并，子行按渠道拆分。"""
    aggregate = dict(_aggregate())
    aggregate["by_model"] = {
        "Gemini-3.8-Flash": 2_000,
        "gemini-3.8-flash-high": 1_600,
    }
    stats = {
        "gemini-3.8-flash": {
            "ch-a": {"calls": 2, "cost_milli": 900},
            "ch-b": {"calls": 1, "cost_milli": 330},
        }
    }
    rows = build_model_rows(aggregate, channel_stats=stats)  # type: ignore[arg-type]
    assert len(rows) == 1  # 家族合并仍是一行
    assert rows[0]["model"] == "Gemini-3.8-Flash"
    assert [item["channel"] for item in rows[0]["channels"]] == ["ch-a", "ch-b"]


# ==================== ③ 价格家族匹配边界 ====================


def test_family_key_keeps_prefixed_gateway_names() -> None:
    # 按次计费网关名（c-gemini-…）剥掉档位后缀但不吞渠道前缀。
    assert model_family_key("c-gemini-3.8-flash-high") == "c-gemini-3.8-flash"
    assert model_family_key("C-Gemini-3.8-Flash-High") == "c-gemini-3.8-flash"
    assert model_family_key("gpt-5.6-terra-xhigh") == "gpt-5.6-terra"


def test_lookup_prefers_exact_entry_over_family_fallback() -> None:
    prices = parse_model_prices(
        '{"gemini-3.8-flash":{"input":1,"output":2},'
        '"gemini-3.8-flash-high":{"input":4.5,"output":22.5}}'
    )
    # 表里同时有裸名与 -high 价：精确命中优先，不并到家族裸名价。
    assert lookup_model_price("gemini-3.8-flash-high", prices) == {
        "input": 4.5,
        "output": 22.5,
    }
    assert lookup_model_price("gemini-3.8-flash", prices) == {
        "input": 1.0,
        "output": 2.0,
    }


def test_parse_model_prices_rejects_bad_entries() -> None:
    prices = parse_model_prices(
        '{"m1":{"input":-1,"output":3},"m2":{"input":"x","output":2},'
        '"m3":{"input":0,"output":0},"m4":"junk"}'
    )
    # 非法键（负数/非数值）视为未配置：只保留同条目内合法的键。
    assert prices["m1"] == {"output": 3.0}
    assert prices["m2"] == {"output": 2.0}
    assert prices["m3"] == {"input": 0.0, "output": 0.0}  # 真免费保留
    assert "m4" not in prices
    assert parse_model_prices("not-json") == {}


def test_channel_subrows_carry_cache_when_ledger_reports_it() -> None:
    """渠道子行补缓存（2026-09-18）：账本按渠道存了缓存量，折叠时不再丢。"""
    stats = {
        "gemini-3.8-flash": {
            "ch-a": {
                "calls": 1,
                "cost_milli": 4_500,
                "cache_read_tokens": 250_000,
                "cache_creation_tokens": 40_000,
            },
            "ch-b": {"calls": 2, "cost_milli": 1_230},
        }
    }
    rows = build_model_rows(_aggregate(), channel_stats=stats)
    channels = rows[0]["channels"]
    assert channels[0]["cache_read"] == 250_000
    assert channels[0]["cache_write"] == 40_000
    # 账本没报缓存的渠道按 0，不凭空造数。
    assert channels[1]["cache_read"] == 0

    text = build_report_text(
        _aggregate(), window_label="测试窗口", channel_stats=stats
    )
    assert (
        "  └ 渠道 ch-a：1 次 / 缓存读 250,000 / 缓存建 40,000 / 费 4.50 元" in text
    )
    # 缓存为 0 的渠道不挂空段（子行已密，恒显 0 只会变噪声）。
    assert "  └ 渠道 ch-b：2 次 / 费 1.23 元" in text
