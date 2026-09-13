"""模型家族归一化 + 价格匹配 + 用量按家族合并回归（2026-09-13 bug A）。

背景：同一模型被上游回报成 ``Gemini-3.8-Flash`` / ``gemini-3.8-flash`` /
``gemini-3.8-flash-high`` 三种写法时，报告拆三行且费用静默 0.00（价格表
精确匹配不到）。本文件锁定：①家族键归一化；②价格查找 精确→casefold→家族；
③报告/聚合按家族合并一行（token/次数/费用求和，代表名=最常见原始名）；
④真免费/未配置价格显式注明，不静默 0.00。全部离线。
"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.runtime.pricing import (
    format_milli_yuan,
    lookup_model_price,
    model_call_cost_milli,
    model_family_key,
    parse_model_prices,
)
from plugins.bot_unified_runtime.runtime.usage_monitor import (
    build_model_rows,
    build_report_text,
)

# ---------- ① 家族键归一化 ----------

def test_model_family_key_merges_case_and_effort_suffixes() -> None:
    assert model_family_key("Gemini-3.8-Flash") == "gemini-3.8-flash"
    assert model_family_key("gemini-3.8-flash") == "gemini-3.8-flash"
    assert model_family_key("gemini-3.8-flash-high") == "gemini-3.8-flash"
    assert model_family_key("GPT-5.6-Terra-XHigh") == "gpt-5.6-terra"
    assert model_family_key("deepseek-v4-pro-max") == "deepseek-v4-pro"
    # 全模型通用：无后缀/其他家族原样保留（casefold 归一小写）。
    assert model_family_key("GLM-5.3-Flash") == "glm-5.3-flash"
    assert model_family_key("kimi-k3") == "kimi-k3"
    assert model_family_key("") == ""
    # 至少保留一段，单段词不剥成空串。
    assert model_family_key("high") == "high"
    # 组合后缀反复剥。
    assert model_family_key("model-x-max-high") == "model-x"


# ---------- ② 价格查找链：精确 → casefold → 家族 ----------

def test_lookup_model_price_chain() -> None:
    prices = parse_model_prices(
        '{"gemini-3.8-flash":{"input":1,"output":2},"DeepSeek-V4-Pro":{"input":4,"output":16}}'
    )
    assert lookup_model_price("gemini-3.8-flash", prices) == {"input": 1.0, "output": 2.0}
    # casefold 命中
    assert lookup_model_price("DEEPSEEK-V4-PRO", prices) == {"input": 4.0, "output": 16.0}
    # 家族命中（大小写 + 档位后缀都不同）
    assert lookup_model_price("Gemini-3.8-Flash", prices) == {"input": 1.0, "output": 2.0}
    assert lookup_model_price("gemini-3.8-flash-high", prices) == {"input": 1.0, "output": 2.0}
    # 查无 = 未配置
    assert lookup_model_price("unknown-model", prices) is None
    assert lookup_model_price("anything", {}) is None


def test_model_call_cost_milli_fuzzy_match_no_silent_zero() -> None:
    prices = parse_model_prices('{"gemini-3.8-flash":{"input":4,"output":16}}')
    # 旧实现这三笔全部 (0, False) 静默漏计；现在都能命中价格。
    for name in ("Gemini-3.8-Flash", "gemini-3.8-flash", "gemini-3.8-flash-high"):
        cost_milli, priced = model_call_cost_milli(name, 1_000_000, 500_000, prices)
        assert priced, name
        assert cost_milli == 12_000, name  # 4 + 8 = 12 元
    # 真未配置仍是 (0, False)。
    assert model_call_cost_milli("unknown", 100, 100, prices) == (0, False)
    assert format_milli_yuan(12_000) == "12.00"


# ---------- ③ 报告/聚合按家族合并 ----------

def _split_aggregate() -> dict[str, object]:
    return {
        "prompt_tokens": 3_600_000,
        "completion_tokens": 900_000,
        "total_tokens": 4_500_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_milli": 6_500,
        "calls": 14,
        "by_model": {
            "Gemini-3.8-Flash": 3_000_000,
            "gemini-3.8-flash": 1_400_000,
            "gemini-3.8-flash-high": 500_000,
            "deepseek-v4-pro": 100_000,
        },
        "by_model_prompt": {
            "Gemini-3.8-Flash": 2_000_000,
            "gemini-3.8-flash": 1_000_000,
            "gemini-3.8-flash-high": 500_000,
            "deepseek-v4-pro": 100_000,
        },
        "by_model_completion": {
            "Gemini-3.8-Flash": 500_000,
            "gemini-3.8-flash": 200_000,
            "gemini-3.8-flash-high": 100_000,
            "deepseek-v4-pro": 100_000,
        },
        "by_model_cache_read": {},
        "by_model_cache_write": {},
        "by_model_cost_milli": {
            "Gemini-3.8-Flash": 3_000,
            "gemini-3.8-flash": 1_800,
            "gemini-3.8-flash-high": 1_200,
            "deepseek-v4-pro": 500,
        },
        "by_model_calls": {
            "Gemini-3.8-Flash": 5,
            "gemini-3.8-flash": 3,
            "gemini-3.8-flash-high": 2,
            "deepseek-v4-pro": 4,
        },
        "by_model_unpriced": {},
        "unpriced_calls": 0,
    }


def test_build_model_rows_merges_family_variants() -> None:
    rows = build_model_rows(_split_aggregate())
    assert len(rows) == 2  # 三种 gemini 写法合并为一行
    gemini, deepseek = rows
    assert gemini["model"] == "Gemini-3.8-Flash"  # 代表名 = 调用次数最多的原始名
    assert gemini["prompt"] == 3_500_000
    assert gemini["completion"] == 800_000
    assert gemini["cost_milli"] == 6_000
    assert gemini["calls"] == 10
    assert gemini["variants"] == [
        "Gemini-3.8-Flash",
        "gemini-3.8-flash",
        "gemini-3.8-flash-high",
    ]
    assert deepseek["model"] == "deepseek-v4-pro"
    # 排序：按合并后费用降序。
    assert gemini["cost_milli"] > deepseek["cost_milli"]


def test_build_model_rows_representative_falls_back_to_tokens() -> None:
    # 无调用次数数据（旧聚合字典）时代表名退回 token 最多的写法。
    aggregate = {
        "by_model": {"gemini-3.8-flash": 100, "Gemini-3.8-Flash": 900},
        "by_model_prompt": {"gemini-3.8-flash": 100, "Gemini-3.8-Flash": 900},
        "by_model_completion": {},
        "by_model_cost_milli": {},
    }
    rows = build_model_rows(aggregate)
    assert len(rows) == 1
    assert rows[0]["model"] == "Gemini-3.8-Flash"


def test_build_model_rows_pricing_notes_not_silent_zero() -> None:
    base = {
        "by_model": {"gemini-3.8-flash-high": 1_000},
        "by_model_prompt": {"gemini-3.8-flash-high": 1_000},
        "by_model_completion": {"gemini-3.8-flash-high": 100},
        "by_model_cost_milli": {"gemini-3.8-flash-high": 0},
        "by_model_unpriced": {},
    }
    # 未配置价格：显式注明 + 费用列显示"未计价"，不静默 0.00。
    rows = build_model_rows(base, prices={})
    assert rows[0]["priced"] is False
    assert rows[0]["pricing_note"] == "未配置价格"
    assert rows[0]["cost_text"] == "未计价"
    # 真免费（价格配置为 0）：注明"免费"，0.00 有出处。
    rows = build_model_rows(base, prices={"gemini-3.8-flash": {"input": 0, "output": 0}})
    assert rows[0]["priced"] is True
    assert rows[0]["pricing_note"] == "免费"
    assert rows[0]["cost_text"] == "0.00"
    # 现在已配价但窗口内有按调用时刻记账时未配价的历史调用：注明笔数。
    rows = build_model_rows(
        {**base, "by_model_unpriced": {"gemini-3.8-flash-high": 2}},
        prices={"gemini-3.8-flash": {"input": 4, "output": 16}},
    )
    assert rows[0]["pricing_note"] == "历史未计价 2 次"
    # 不传价格表 = 旧行为（无注记，费用为数值文本）。
    rows = build_model_rows(base)
    assert rows[0]["pricing_note"] == ""
    assert rows[0]["cost_text"] == "0.00"


def test_build_report_text_merges_and_annotates() -> None:
    text = build_report_text(
        _split_aggregate(),
        window_label="测试窗口",
        prices={"gemini-3.8-flash": {"input": 1, "output": 2}},
    )
    assert "- Gemini-3.8-Flash（合并 3 种写法）：入 3,500,000 / 出 800,000 / 费 6.00 元" in text
    assert "gemini-3.8-flash-high" not in text  # 不再拆行
    assert "- deepseek-v4-pro（未配置价格）：入 100,000 / 出 100,000 / 费 未计价 元" in text


def test_build_report_text_annotates_unpriced_instead_of_zero() -> None:
    text = build_report_text(
        {
            "prompt_tokens": 1_000,
            "completion_tokens": 100,
            "total_tokens": 1_100,
            "calls": 1,
            "cost_milli": 0,
            "by_model": {"gemini-3.8-flash-high": 1_100},
            "by_model_prompt": {"gemini-3.8-flash-high": 1_000},
            "by_model_completion": {"gemini-3.8-flash-high": 100},
        },
        window_label="测试窗口",
        prices={},
    )
    assert "- gemini-3.8-flash-high（未配置价格）：入 1,000 / 出 100 / 费 未计价 元" in text


# ---------- 聚合源：按原始名计次数/未计价 ----------

def test_aggregate_llm_usage_counts_calls_and_unpriced_per_model(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog

    log_path = tmp_path / "events.log"
    log_path.write_text(
        "2026-09-13 12:00:00.000 INFO event=transport_receipt request_id=r1"
        " model=Gemini-3.8-Flash prompt_tokens=1000 completion_tokens=500"
        " total_tokens=1500 cost_milli=1200\n"
        "2026-09-13 12:01:00.000 INFO event=transport_receipt request_id=r2"
        " model=gemini-3.8-flash-high prompt_tokens=2000 completion_tokens=1000"
        " total_tokens=3000 cost_unpriced=1\n"
        # 同 request_id 重复行（幂等去重）：
        "2026-09-13 12:02:00.000 INFO event=transport_receipt request_id=r1"
        " model=Gemini-3.8-Flash prompt_tokens=1000 completion_tokens=500"
        " total_tokens=1500 cost_milli=1200\n",
        encoding="utf-8",
    )
    usage = RuntimeEventLog(log_path).aggregate_llm_usage_range("2026-09-13", "2026-09-13")
    assert usage["calls"] == 2
    assert usage["by_model_calls"] == {"Gemini-3.8-Flash": 1, "gemini-3.8-flash-high": 1}
    assert usage["by_model_unpriced"] == {"gemini-3.8-flash-high": 1}
    assert usage["unpriced_calls"] == 1
    assert usage["cost_milli"] == 1200
    # 聚合结果直接进报告构建：两种写法合并一行、代表名取与家族键同形的写法。
    rows = build_model_rows(
        dict(usage), prices={"gemini-3.8-flash": {"input": 4, "output": 16}}
    )
    assert len(rows) == 1
    assert rows[0]["model"] == "Gemini-3.8-Flash"
    assert rows[0]["calls"] == 2
    assert rows[0]["pricing_note"] == "历史未计价 1 次"
