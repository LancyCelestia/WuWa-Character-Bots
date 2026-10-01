"""S-FIX-BILLING-RESID 账单残项修复锁（承接 SEAT-FIX-BILLING 移交 §1）。

对照：
- 上游审计 `.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-BILLING.md`
- 前席报告 `.superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-BILLING.md`

锁面（全部离线 mock：tmp_path 库，不起线程、不连网）：
1. **同病判定实锁**：usage_monitor 主账单行真身读事件逐行整数毫厘（F-1 镜像），
   `_apply_ledger_main_row` 换账本微元聚合后主行不再塌零，且与渠道子行同窗口
   （`since_iso` 日内区间）。账本关（db_path 空）⇒ 逐字节回旧事件毫厘、零注记。
2. **ledger since_iso 腿**：`aggregate_usage_totals` 加 `since_iso` 后主行可按
   报告窗口收窄，缺省（空 since_iso）行为逐字节不变（echo 全日窗口不受影响）。
3. **反向数字锁（Task 4）**：单发 <0.5 毫厘（0.219 毫厘）× 数百发的账，旧逐行
   毫厘口径恒 0、新微元聚合 ≠ 0——这是 F-1 塌零病灶的反证。
4. **F-4**：`_optional_price` 拒负价/NaN/±inf；模型覆盖/兜底价读侧复用同一校验，
   脏覆盖视同缺席自然下探，不再 `float()` 直用产生负成本或 round(inf) 炸账。
5. **F-7（行膨胀臂）**：响应体 id → remote_request_id 截断到 128 字符上限。
"""

from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    LedgerService,
    aggregate_usage_totals,
    build_call_draft,
)
from plugins.bot_unified_runtime.domains.ops.monitor.usage_monitor import (
    _LEDGER_FALLBACK_NOTE,
    _apply_ledger_main_row,
    build_report_alert,
    build_report_text,
)


@pytest.fixture(autouse=True)
def _clean_billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)


def _stub_writer() -> threading.Thread:
    return threading.Thread(target=lambda: None)


def _service(tmp_path) -> LedgerService:
    return LedgerService(
        str(tmp_path / "ledger.sqlite3"), writer_thread=_stub_writer()
    )


def _event_flat_aggregate() -> dict:
    """旧 usage_monitor 主行口径：事件逐行整数毫厘，亚毫厘单价已塌成 0。"""
    return {
        "prompt_tokens": 68_000,
        "completion_tokens": 58_000,
        "total_tokens": 126_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_milli": 0,  # 500 发 × round(0.219 毫厘)=0 ⇒ 日账单塌零
        "calls": 500,
        "by_model": {"gemini-3.8-flash": 126_000},
        "by_model_prompt": {"gemini-3.8-flash": 68_000},
        "by_model_completion": {"gemini-3.8-flash": 58_000},
        "by_model_cost_milli": {"gemini-3.8-flash": 0},
        "by_model_calls": {"gemini-3.8-flash": 500},
        "unpriced_calls": 0,
    }


def _seed_submilli(tmp_path, *, rows: int, cost_yuan: float) -> str:
    service = _service(tmp_path)
    for index in range(rows):
        service.submit(
            build_call_draft(
                request_id=f"req-{index}",
                started_at="2026-09-28T10:00:00.000+08:00",
                completed_at="2026-09-28T10:00:01.000+08:00",
                model_id="axon-a",
                actual_model="gemini-3.8-flash",
                usage={
                    "prompt_tokens": 136,
                    "completion_tokens": 116,
                    "total_tokens": 252,
                    "cost": cost_yuan,
                },
                attempts=["axon-a:success"],
                status="success",
            )
        )
    assert service.flush() == rows
    service.close()
    return str(tmp_path / "ledger.sqlite3")


def _seed_timed(tmp_path, *, morning: int, afternoon: int, cost_yuan: float) -> str:
    service = _service(tmp_path)
    for index in range(morning):
        service.submit(
            build_call_draft(
                request_id=f"am-{index}",
                started_at="2026-09-28T09:00:00.000+08:00",
                completed_at="2026-09-28T09:00:01.000+08:00",
                model_id="axon-a",
                actual_model="gemini-3.8-flash",
                usage={"prompt_tokens": 100, "completion_tokens": 100,
                       "total_tokens": 200, "cost": cost_yuan},
                attempts=["axon-a:success"],
                status="success",
            )
        )
    for index in range(afternoon):
        service.submit(
            build_call_draft(
                request_id=f"pm-{index}",
                started_at="2026-09-28T15:00:00.000+08:00",
                completed_at="2026-09-28T15:00:01.000+08:00",
                model_id="axon-a",
                actual_model="gemini-3.8-flash",
                usage={"prompt_tokens": 100, "completion_tokens": 100,
                       "total_tokens": 200, "cost": cost_yuan},
                attempts=["axon-a:success"],
                status="success",
            )
        )
    assert service.flush() == morning + afternoon
    service.close()
    return str(tmp_path / "ledger.sqlite3")


# ==================== 同病判定：_apply_ledger_main_row 换源 ====================


def test_ledger_off_returns_event_identical_no_note() -> None:
    """账本关（db_path 空）⇒ 主行原样回事件聚合、无注记：逐字节旧行为不动。"""
    event = _event_flat_aggregate()
    out, note = _apply_ledger_main_row(event, db_path="", start_day="2026-09-28",
                                       end_day="2026-09-28")
    assert out is event, "账本关不得复制/改动事件聚合，必须原样返回"
    assert note == ""


def test_ledger_on_main_row_no_longer_collapses(tmp_path) -> None:
    """账本开且有行 ⇒ 主行换微元聚合：0.219 毫厘 × 500 发不再塌零。"""
    db_path = _seed_submilli(tmp_path, rows=500, cost_yuan=0.000219)
    event = _event_flat_aggregate()
    assert event["cost_milli"] == 0  # 旧口径日账单塌零（病灶）
    out, note = _apply_ledger_main_row(
        event, db_path=db_path, start_day="2026-09-28", end_day="2026-09-28"
    )
    assert note == ""
    # 500 × 219 微元 = 109500 微元 ⇒ 末端一次取整 = 110 毫厘（非 0）。
    assert out["cost_micro"] == 109_500
    assert out["cost_milli"] == 110
    assert out["cost_milli"] != event["cost_milli"]
    assert out["calls"] == 500


def test_ledger_on_but_empty_window_falls_back_with_note(tmp_path) -> None:
    """账本开、窗口真空 ⇒ 回落事件毫厘并注记口径（不静默换源、不谎报同源）。"""
    db_path = _seed_submilli(tmp_path, rows=5, cost_yuan=0.000219)
    event = _event_flat_aggregate()
    out, note = _apply_ledger_main_row(
        event, db_path=db_path, start_day="2020-01-01", end_day="2020-01-01"
    )
    assert out is event
    assert note == _LEDGER_FALLBACK_NOTE


def test_ledger_unreadable_falls_back_with_note(tmp_path) -> None:
    """库不可达 ⇒ aggregate_usage_totals 返回 None ⇒ 回落事件毫厘 + 注记。"""
    event = _event_flat_aggregate()
    out, note = _apply_ledger_main_row(
        event, db_path=str(tmp_path / "missing.sqlite3"),
        start_day="2026-09-28", end_day="2026-09-28",
    )
    assert out is event
    assert note == _LEDGER_FALLBACK_NOTE


# ==================== since_iso 日内窗口：主行与子行同窗口 ====================


def test_apply_ledger_main_row_honors_since_window(tmp_path) -> None:
    """报告窗口是日内区间（如 13→now）：主行必须按 since_iso 收窄，与子行同窗。

    否则主行算全天、子行算区间，等于把 F-1「两套钱」从塌零换成窗口错配。
    """
    db_path = _seed_timed(tmp_path, morning=3, afternoon=2, cost_yuan=0.02)
    event = _event_flat_aggregate()
    # 无 since ⇒ 全天 5 发 × 20 毫厘 = 100 毫厘。
    full, _ = _apply_ledger_main_row(
        event, db_path=db_path, start_day="2026-09-28", end_day="2026-09-28"
    )
    assert full["cost_milli"] == 100
    # 14:00 起 ⇒ 仅下午 2 发 = 40 毫厘（下界收窄到窗口起点）。
    window, note = _apply_ledger_main_row(
        event, db_path=db_path, start_day="2026-09-28", end_day="2026-09-28",
        since_iso="2026-09-28T14:00:00+08:00",
    )
    assert note == ""
    assert window["cost_milli"] == 40
    assert window["calls"] == 2


def test_aggregate_usage_totals_default_window_unchanged(tmp_path) -> None:
    """回归：缺省（空 since_iso）签名/语义逐字节不变，echo 全日窗口不受影响。"""
    db_path = _seed_timed(tmp_path, morning=3, afternoon=2, cost_yuan=0.02)
    agg = aggregate_usage_totals(db_path, start_day="2026-09-28", end_day="2026-09-28")
    assert agg is not None
    assert agg["calls"] == 5 and agg["cost_milli"] == 100


# ==================== build_report_text 端到端：主行换源后金额 ====================


def test_report_text_main_row_uses_ledger_money(tmp_path) -> None:
    db_path = _seed_submilli(tmp_path, rows=500, cost_yuan=0.000219)
    ledger_agg, note = _apply_ledger_main_row(
        _event_flat_aggregate(), db_path=db_path,
        start_day="2026-09-28", end_day="2026-09-28",
    )
    text = build_report_text(ledger_agg, window_label="09-28 13:00 至 09-28 18:00")
    assert note == ""
    assert "账单 0.11 元" in text, text  # 110 毫厘 = 0.11 元（非旧口径 0.00）
    assert "口径注记" not in text


def test_report_text_and_alert_surface_fallback_note(tmp_path) -> None:
    event = _event_flat_aggregate()
    # 账本开但读不到 ⇒ 带注记
    out, note = _apply_ledger_main_row(
        event, db_path=str(tmp_path / "missing.sqlite3"),
        start_day="2026-09-28", end_day="2026-09-28",
    )
    assert note == _LEDGER_FALLBACK_NOTE
    text = build_report_text(out, window_label="w", cost_basis_note=note)
    assert text.rstrip().endswith(_LEDGER_FALLBACK_NOTE)
    alert = build_report_alert(
        out, window_label="w", cost_basis_note=note
    )
    assert _LEDGER_FALLBACK_NOTE in alert.what_happened


def test_report_text_default_no_note_line_byte_compatible() -> None:
    """不传 cost_basis_note ⇒ 报告尾部零注记，旧纯文本行为逐字节不变。"""
    event = _event_flat_aggregate()
    text = build_report_text(event, window_label="w")
    assert "口径注记" not in text
    assert "账单 0.00 元" in text  # 事件毫厘原样（旧口径，未换源）


# ==================== F-4：模型价目表覆盖/兜底校验 ====================


def test_optional_price_rejects_negative_and_non_finite() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        _optional_price,
    )

    assert _optional_price("abc") is None
    assert _optional_price(None) is None
    assert _optional_price(-1.0) is None
    assert _optional_price(float("nan")) is None
    assert _optional_price(float("inf")) is None, "F-4：+inf 价会下游 round 炸账"
    assert _optional_price(float("-inf")) is None
    assert _optional_price(0) == 0.0  # 0 价既有裁定保留
    assert _optional_price(0.00219) == 0.00219


def test_apply_model_price_fallback_rejects_poison_override() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        ModelSpec,
        _apply_model_price_fallback,
    )

    spec = ModelSpec(
        model_id="ch-a",
        model="deepseek-v4.1-flash",  # 兜底表有此键
        base_url="https://example.test/v1",
        api_key="k",
        # price_in/out 默认 None → needs=True → 进 override 路径
    )
    # 脏覆盖（负价/inf/NaN/字符串）⇒ 视同缺席，自然下探兜底（1.0），不崩。
    for poison in (-5.0, float("inf"), float("nan"), "junk"):
        config = SimpleNamespace(
            bot_llm_model_price_overrides={
                "deepseek-v4.1-flash": {"price_in": poison},
            }
        )
        out = _apply_model_price_fallback(spec, config)
        assert out.price_in == 1.0, f"脏覆盖 {poison!r} 应被拒并下探兜底 1.0"
        assert out.price_out == 4.0
    # 合法覆盖仍生效并优先于兜底。
    config = SimpleNamespace(
        bot_llm_model_price_overrides={
            "deepseek-v4.1-flash": {"price_in": 3.0},
        }
    )
    out = _apply_model_price_fallback(spec, config)
    assert out.price_in == 3.0


# ==================== F-7：remote_request_id 行膨胀截断 ====================


def test_remote_request_id_truncated_to_cap() -> None:
    import json as _json

    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        _REMOTE_REQUEST_ID_MAX_LEN,
        OpenAICompatibleLLMProvider,
    )

    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
    )
    # 触发 urllib 传输路径（注入 _urlopen 即可，再覆盖 _post_via_urllib 返回 canned）。
    provider._urlopen = lambda *a, **kw: None  # type: ignore[assignment]
    huge_id = "x" * 5000
    canned = _json.dumps(
        {
            "id": huge_id,
            "choices": [
                {"message": {"content": "hi"}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }
    )
    provider._post_via_urllib = lambda *a, **kw: canned  # type: ignore[assignment]
    reply = provider.generate([{"role": "user", "content": "hello"}])
    assert len(reply.remote_request_id) <= _REMOTE_REQUEST_ID_MAX_LEN
    assert reply.remote_request_id == huge_id[:_REMOTE_REQUEST_ID_MAX_LEN]


# ==================== 反向数字锁（Task 4）：塌零病灶的反证 ====================


def test_reverse_lock_hundreds_submilli_not_zero(tmp_path) -> None:
    """单发 <0.5 毫厘（0.219 毫厘）× 数百发：旧逐行毫厘恒 0、新微元聚合 ≠ 0。"""
    rows, cost_yuan = 300, 0.000219  # 单发 0.219 毫厘 < 0.5 毫厘
    db_path = _seed_submilli(tmp_path, rows=rows, cost_yuan=cost_yuan)
    with sqlite3.connect(db_path) as con:
        legacy = con.execute(
            "SELECT COALESCE(SUM(total_cost_milli), 0) FROM llm_call_records"
        ).fetchone()[0]
    assert legacy == 0, "旧口径：每行 round(0.219)=0，一天求和仍 0（病灶）"
    agg = aggregate_usage_totals(db_path, start_day="2026-09-28", end_day="2026-09-28")
    assert agg is not None
    assert agg["cost_milli"] != 0, "新口径不得塌零"
    assert agg["cost_micro"] == rows * 219
    assert agg["cost_milli"] == round(rows * 219 / 1000)
    # 300 × 0.219 毫厘 = 65.7 毫厘 ⇒ 末端一次取整 66 毫厘，非 0。
    assert agg["cost_milli"] == 66
