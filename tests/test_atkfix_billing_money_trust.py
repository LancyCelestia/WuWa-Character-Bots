"""S-FIX-BILLING F-1/F-2 修复锁（对照 .superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-BILLING.md）。

F-1（钱两处口径塌零）：
- ``/bot model usage`` 主账单行改读账本 ``total_cost_micro`` 聚合
  （``aggregate_usage_totals``），与渠道子行**同源**；取整只在聚合末端
  做一次——逐行整数毫厘把 0.000219 元这类亚毫厘单价塌成 0 的旧路径退出主行。
- 账本关（缺省）主行行为逐字节不变；账本开但窗口读不到 ⇒ 回落事件毫厘并
  **注记口径**，绝不静默换源。

F-2（回包 usage.cost 无条件采信）：
- 信任边界 ``gateway_cost_trust``：负数/NaN/inf/bool/超对照比率/无基线超上限
  ⇒ 拒采**并记原因入列**（cost_trust_note）；缺席/零 ⇒ 维持旧语义（落回
  本地重算价/未计价，零不当成本）。
- 归因段 PG total 同判负数（留痕不覆盖 A 段原因），零仍为真实价（既有裁定）。
- ``_micro`` 对非有限值回 None：round(inf×1e6) 会 OverflowError 抛穿
  parse_rows 的"永不抛"承诺。

离线 mock：不起线程、不连网、全部落 tmp_path 库。
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.axonhub_attribution import (
    Attribution,
    parse_rows,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    LedgerService,
    LLMCallDraft,
    aggregate_usage_totals,
    apply_attribution,
    build_call_draft,
    gateway_cost_trust,
)


@pytest.fixture(autouse=True)
def _clean_billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """与 test_llm_ledger 同法：账本开关环境变量不进测试判定。"""
    monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)


def _stub_writer() -> threading.Thread:
    """未启动的桩线程：不起后台写线程，flush 全同步。"""
    return threading.Thread(target=lambda: None)


def _service(tmp_path, **kwargs: object) -> LedgerService:
    return LedgerService(
        str(tmp_path / "ledger.sqlite3"), writer_thread=_stub_writer(), **kwargs
    )


def _fetch_row(db_path: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM llm_call_records").fetchone()


def _draft_cost(request_id: str, cost: object, **extra: object) -> LLMCallDraft:
    """一发 0.000219 元形态的草稿：整数毫厘列=0，微元列才是真钱。"""
    base: dict[str, object] = {
        "request_id": request_id,
        "started_at": "2026-09-28T10:00:00.000+08:00",
        "completed_at": "2026-09-28T10:00:01.000+08:00",
        "model_id": "axon-gemini-38-flash",
        "actual_model": "gemini-3.8-flash",
        "usage": {
            "prompt_tokens": 136,
            "completion_tokens": 116,
            "total_tokens": 252,
            "cost": cost,
        },
        "attempts": ["axon-gemini-38-flash:success"],
        "status": "success",
    }
    base.update(extra)
    return build_call_draft(**base)  # type: ignore[arg-type]


# ==================== F-2：信任边界本体（纯函数） ====================


def test_trust_negative_rejected_with_reason() -> None:
    micro, note = gateway_cost_trust(-5.0, 1_000)
    assert micro is None
    assert note == "gateway_cost_rejected:negative"


def test_trust_non_finite_rejected_with_reason() -> None:
    for poison in (float("nan"), float("inf"), float("-inf")):
        micro, note = gateway_cost_trust(poison, 1_000)
        assert micro is None, poison
        assert note == "gateway_cost_rejected:non_finite", poison


def test_trust_bool_rejected_with_reason() -> None:
    # True 是 int 的子类：不显式挡就会当 1 元入账——响应体里没有合法的 bool 价。
    micro, note = gateway_cost_trust(True, 1_000)
    assert micro is None
    assert note == "gateway_cost_rejected:bool"


def test_trust_absent_and_zero_keep_old_semantics() -> None:
    # 缺席 ⇒ 落回本地重算价；零 ⇒ 「零不当成本」旧裁定：两者都不留痕。
    assert gateway_cost_trust(None, 1_000) == (None, "")
    assert gateway_cost_trust("0.000219", 1_000) == (None, "")
    assert gateway_cost_trust(object(), 1_000) == (None, "")


def test_trust_over_sanity_rejected_under_billing_accepted() -> None:
    local_micro = 2_000  # 0.002 元的本地估价
    # 篡改形态：51 倍 ⇒ 拒并留痕
    micro, note = gateway_cost_trust(0.102, local_micro)
    assert micro is None
    assert note == "gateway_cost_rejected:over_sanity"
    # 合法形态：网关按实际渠道计价，低于本地估价的欠账也是真实扣款 ⇒ 采信。
    micro, note = gateway_cost_trust(0.000001, local_micro)
    assert micro == 1
    assert note == ""
    # 恰在界内（= 50×）⇒ 采信：边界值不误伤。
    micro, note = gateway_cost_trust(0.1, local_micro)
    assert micro == 100_000
    assert note == ""


def test_trust_no_basis_absolute_cap() -> None:
    # 无本地基线时以绝对上限兜底：单发 >100 元即异常形态。
    assert gateway_cost_trust(100.0, None) == (100_000_000, "")
    micro, note = gateway_cost_trust(100.000001, None)
    assert micro is None
    assert note == "gateway_cost_rejected:over_cap"
    # 基线为 0（token/价全空）视作无基线，走绝对上限臂。
    assert gateway_cost_trust(0.5, 0)[1] == ""


def test_build_call_draft_rejects_anomalous_gateway_cost() -> None:
    """拒采 ≠ 免单：回包 cost 异常时账落回本地重算价，且原因入列。"""
    draft = build_call_draft(
        request_id="req-trust-1",
        started_at="2026-09-28T10:00:00.000+08:00",
        completed_at="2026-09-28T10:00:01.000+08:00",
        model_id="ch-a",
        usage={"prompt_tokens": 1_000, "completion_tokens": 1_000,
               "total_tokens": 2_000, "cost": 0.5},
        attempts=["ch-a:success"],
        status="success",
        price_in=1.0,
        price_out=1.0,
    )
    assert draft.pricing_source == "channel_spec"
    assert draft.total_cost_micro == 2_000  # 本地估价，不是网关的 50 万微元
    assert draft.cost_trust_note == "gateway_cost_rejected:over_sanity"
    # inf 不再把 round() 抛穿（旧实现：OverflowError ⇒ 整行静默丢）。
    draft_inf = build_call_draft(
        request_id="req-trust-2",
        started_at="2026-09-28T10:00:00.000+08:00",
        completed_at="2026-09-28T10:00:01.000+08:00",
        model_id="ch-a",
        usage={"prompt_tokens": 10, "completion_tokens": 10,
               "total_tokens": 20, "cost": float("inf")},
        attempts=["ch-a:success"],
        status="success",
    )
    assert draft_inf.total_cost_milli is None
    assert draft_inf.unpriced == 1
    assert draft_inf.cost_trust_note == "gateway_cost_rejected:non_finite"


def test_cost_trust_note_persists(tmp_path) -> None:
    service = _service(tmp_path)
    service.submit(_draft_cost("req-note", -0.000219))
    assert service.flush() == 1
    row = _fetch_row(service.db_path)
    assert row["cost_trust_note"] == "gateway_cost_rejected:negative"
    service.close()


def test_legacy_database_gains_trust_note_column(tmp_path) -> None:
    """旧库迁移：cost_trust_note 走 ADD-if-missing，存量行不动。"""
    db_path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE llm_call_records ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,"
            " call_seq INTEGER NOT NULL DEFAULT 1, session_id TEXT NOT NULL DEFAULT '',"
            " capability TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL,"
            " completed_at TEXT NOT NULL, duration_ms INTEGER,"
            " first_token_latency_ms INTEGER, provider_id TEXT NOT NULL DEFAULT '',"
            " model_id TEXT NOT NULL, actual_model TEXT NOT NULL DEFAULT '',"
            " effort TEXT NOT NULL DEFAULT '', routing_group TEXT NOT NULL DEFAULT '',"
            " prompt_tokens INTEGER, cache_creation_tokens INTEGER,"
            " cache_read_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,"
            " input_cost_milli INTEGER, cache_read_cost_milli INTEGER,"
            " output_cost_milli INTEGER, total_cost_milli INTEGER,"
            " total_cost_micro INTEGER,"
            " currency TEXT NOT NULL DEFAULT 'CNY',"
            " pricing_source TEXT NOT NULL DEFAULT 'unknown',"
            " unpriced INTEGER NOT NULL DEFAULT 0, attempts_json TEXT NOT NULL DEFAULT '[]',"
            " attempts_count INTEGER NOT NULL DEFAULT 0, finish_reason TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL, error_kind TEXT NOT NULL DEFAULT '',"
            " error_summary TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'router',"
            " schema_ver INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)"
        )
        con.execute(
            "INSERT INTO llm_call_records (request_id, started_at, completed_at,"
            " model_id, status, created_at)"
            " VALUES ('old-row','a','b','m','success','c')"
        )
        con.commit()
    service = LedgerService(db_path, writer_thread=_stub_writer())
    service.flush()
    with sqlite3.connect(db_path) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(llm_call_records)")}
        n = con.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0]
    assert "cost_trust_note" in cols
    assert n == 1, "迁移不得动存量行"
    service.close()


def test_apply_attribution_negative_total_rejected_keeps_a_stage_note() -> None:
    """归因段同防线：负 total 拒采留痕；A 段已拒过的原因不被覆写（叠痕）。"""
    draft = _draft_cost("req-attr-neg", -1.0, remote_request_id="w-neg")  # A 段已记 negative
    before_micro = draft.total_cost_micro
    apply_attribution(draft, Attribution(remote_request_id="", total_cost_micro=-999))
    assert draft.total_cost_micro == before_micro, "负数归因价不得冲账"
    assert draft.cost_trust_note == (
        "gateway_cost_rejected:negative;gateway_total_rejected:negative"
    )


def test_apply_attribution_zero_total_is_a_real_price() -> None:
    """既有裁定保持：网关库里的 0 是真实价（零价 ≠ 缺席），只有负数被拒。"""
    draft = _draft_cost("req-attr-zero", None, remote_request_id="w-zero")
    draft.cost_trust_note = ""
    apply_attribution(draft, Attribution(remote_request_id="", total_cost_micro=0))
    assert draft.total_cost_micro == 0
    assert draft.unpriced == 0
    assert draft.pricing_source.startswith("gateway_cost")
    assert draft.cost_trust_note == ""


def test_micro_non_finite_is_not_a_cost() -> None:
    """parse_rows 的「永不抛」承诺：inf 字符串过去会 OverflowError 抛穿。"""
    rows = parse_rows(
        ["k1"],
        [{"external_id": "k1", "total_cost": "inf", "cost_items": []}],
    )
    assert rows["k1"].total_cost_micro is None
    rows2 = parse_rows(
        ["k2"], [{"external_id": "k2", "total_cost": float("nan")}]
    )
    assert rows2["k2"].total_cost_micro is None
    assert rows2["k2"].total_cost_milli is None


# ==================== F-1：主账单行与渠道子行同源 ====================


def _seed_micro_ledger(tmp_path, *, rows: int, cost_yuan: float,
                       model: str = "gemini-3.8-flash",
                       model_ids: tuple[str, ...] = ("axon-a",)) -> str:
    """灌 N 发亚毫厘单价行（整数毫厘列全为 0，微元列才是真钱）。"""
    service = _service(tmp_path)
    milli_per_row = round(cost_yuan * 1000)
    for index in range(rows):
        draft = _draft_cost(
            f"req-{index}",
            cost_yuan,
            model_id=model_ids[index % len(model_ids)],
            actual_model=model,
        )
        # 信任边界在无基线时按绝对上限兜底，此处逐行必须被采信。
        assert draft.total_cost_micro is not None
        assert draft.total_cost_milli == milli_per_row
        service.submit(draft)
    assert service.flush() == rows
    service.close()
    return str(tmp_path / "ledger.sqlite3")


def test_aggregate_usage_totals_rounds_once_and_does_not_collapse(tmp_path) -> None:
    day = "2026-09-28"
    db_path = _seed_micro_ledger(tmp_path, rows=1000, cost_yuan=0.000219)
    # 旧主行口径（逐行整数毫厘求和）在这批行上恒为 0——这正是 F-1 的塌零面。
    with sqlite3.connect(db_path) as con:
        legacy_sum = con.execute(
            "SELECT COALESCE(SUM(total_cost_milli), 0) FROM llm_call_records"
        ).fetchone()[0]
    assert legacy_sum == 0
    agg = aggregate_usage_totals(db_path, start_day=day, end_day=day)
    assert agg is not None
    # 1000 × 0.000219 = 0.219 元 ⇒ 219 毫厘，取整只在聚合末端一次。
    assert agg["cost_micro"] == 219_000
    assert agg["cost_milli"] == 219
    assert sum(agg["by_model_cost_milli"].values()) == 219
    assert agg["calls"] == 1000
    assert agg["total_tokens"] == 252_000
    # 主行键面与事件聚合同形（echo 读侧共用同一 fill 块的前提）。
    for key in ("by_model", "by_model_prompt", "by_model_completion",
                "by_model_cache_read", "by_model_cache_write",
                "by_model_cost_milli", "by_model_calls", "by_model_unpriced",
                "unpriced_calls", "prompt_tokens", "completion_tokens",
                "total_tokens", "cache_read_tokens", "cache_write_tokens"):
        assert key in agg, key


def test_aggregate_usage_totals_folds_family_like_subrows(tmp_path) -> None:
    """家族折叠与代表名口径 = 渠道子行同式（大小写变体并入一行不裂账）。"""
    day = "2026-09-28"
    service = _service(tmp_path)
    # 2 发规范小写 + 1 发大写变体：同族并入一行，代表名 = 调用次数最多者。
    for index, actual in enumerate(
        ("gemini-3.8-flash", "gemini-3.8-flash", "Gemini-3.8-Flash")
    ):
        service.submit(
            _draft_cost(f"req-f{index}", 0.00219, actual_model=actual)
        )
    assert service.flush() == 3
    service.close()
    agg = aggregate_usage_totals(
        str(tmp_path / "ledger.sqlite3"), start_day=day, end_day=day
    )
    assert agg is not None
    assert list(agg["by_model_cost_milli"]) == ["gemini-3.8-flash"], (
        "代表名按调用次数最多（与 build_model_rows 选取一致）"
    )
    # 3 × 0.00219 = 0.00657 元 ⇒ 末端一次取整 = 7 毫厘（逐行取整则 2+2+0 各案）。
    assert agg["by_model_cost_milli"]["gemini-3.8-flash"] == 7
    assert agg["cost_milli"] == 7
    assert agg["by_model_calls"]["gemini-3.8-flash"] == 3


def test_aggregate_usage_totals_unreadable_is_none_not_empty(tmp_path) -> None:
    # 读不到（空路径/坏日期/库不存在）⇒ None：调用方要能区分「读不到」与「真空」。
    assert aggregate_usage_totals("", start_day="2026-09-28", end_day="2026-09-28") is None
    assert aggregate_usage_totals(
        str(tmp_path / "missing.sqlite3"), start_day="x", end_day="2026-09-28"
    ) is None
    assert aggregate_usage_totals(
        str(tmp_path / "missing.sqlite3"), start_day="2026-09-28", end_day="2026-09-28"
    ) is None
    db_path = _seed_micro_ledger(tmp_path, rows=3, cost_yuan=0.000219)
    # 窗口真空（库在、当日无行）⇒ 是聚合不是 None：读侧据 by_model/calls 判回落。
    empty = aggregate_usage_totals(
        db_path, start_day="2020-01-01", end_day="2020-01-01"
    )
    assert empty is not None
    assert not empty["by_model"] and empty["calls"] == 0


def test_usage_main_row_reads_ledger_with_channel_subrows(tmp_path, monkeypatch) -> None:
    """端到端 echo 锁：主行 0.22 元（账本微元聚合），不再是事件毫厘的 0.00。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _handle_model_command,
    )

    day = "2026-09-28"
    db_path = _seed_micro_ledger(tmp_path, rows=1000, cost_yuan=0.000219)

    def _temp_dir() -> Path:
        return Path(tempfile.mkdtemp(prefix="atkfix-billing-"))

    store = RuntimeSettingsStore(_temp_dir() / "settings.json", allow_no_gate=True)
    config = SimpleNamespace(
        bot_llm_billing_enabled=True,
        bot_model_registry={},
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )
    monkeypatch.setattr(
        ledger_module, "resolve_default_db_path", lambda: db_path
    )
    # 事件侧聚合刻意给塌零值：若主行仍读事件，账单会是 0.00 元。
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 136_000,
            "completion_tokens": 116_000,
            "total_tokens": 252_000,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_milli": 0,
            "calls": 1000,
            "by_model": {"gemini-3.8-flash": 252_000},
            "by_model_prompt": {"gemini-3.8-flash": 136_000},
            "by_model_completion": {"gemini-3.8-flash": 116_000},
            "by_model_cost_milli": {"gemini-3.8-flash": 0},
            "by_model_calls": {"gemini-3.8-flash": 1000},
            "unpriced_calls": 0,
        }
    )
    result = _handle_model_command(
        store, config, ["usage", day], usage_store=usage_store
    )
    assert "账单：0.22 元" in result, result
    assert "口径注记" not in result, "账本窗口有行时不得回落还不出注记"
    # 渠道子行与主行同源：子行之和 == 主行（同为 219 毫厘）。
    assert "axon-a" in result


def test_usage_falls_back_to_event_milli_with_note_when_ledger_window_empty(
    tmp_path, monkeypatch
) -> None:
    """账本开但当日窗口真空 ⇒ 回落事件毫厘 **且必须注记口径**（不静默换源）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _handle_model_command,
    )

    db_path = _seed_micro_ledger(tmp_path, rows=10, cost_yuan=0.000219)

    def _temp_dir() -> Path:
        return Path(tempfile.mkdtemp(prefix="atkfix-billing-"))

    store = RuntimeSettingsStore(_temp_dir() / "settings.json", allow_no_gate=True)
    config = SimpleNamespace(
        bot_llm_billing_enabled=True,
        bot_model_registry={},
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )
    monkeypatch.setattr(ledger_module, "resolve_default_db_path", lambda: db_path)
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "cost_milli": 3_000, "calls": 1,
            "by_model": {"m": 20}, "by_model_prompt": {"m": 10},
            "by_model_completion": {"m": 10}, "by_model_cost_milli": {"m": 3_000},
            "by_model_calls": {"m": 1}, "unpriced_calls": 0,
        }
    )
    result = _handle_model_command(
        store, config, ["usage", "2020-01-01"], usage_store=usage_store
    )
    assert "账单：3.00 元" in result
    assert "口径注记" in result


def test_usage_ledger_off_byte_identical(tmp_path, monkeypatch) -> None:
    """账本关（缺省）⇒ 主行仍读事件聚合、零注记零健康行——旧行为逐字节不动。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _handle_model_command,
    )

    def _temp_dir() -> Path:
        return Path(tempfile.mkdtemp(prefix="atkfix-billing-"))

    store = RuntimeSettingsStore(_temp_dir() / "settings.json", allow_no_gate=True)
    config = SimpleNamespace(
        bot_model_registry={},
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )
    # 账本关时读侧绝不能碰到库：解析路径直接炸给测试看（真炸=没调用）。
    def _forbidden() -> str:
        raise AssertionError("账本关闭不得解析账本库路径")

    monkeypatch.setattr(ledger_module, "resolve_default_db_path", _forbidden)
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 2_000_000, "completion_tokens": 500_000,
            "total_tokens": 2_500_000, "cache_read_tokens": 800_000,
            "cache_write_tokens": 100_000, "cost_milli": 12_000, "calls": 7,
            "by_model": {"deepseek-v4-pro": 2_500_000},
            "by_model_prompt": {"deepseek-v4-pro": 2_000_000},
            "by_model_completion": {"deepseek-v4-pro": 500_000},
            "by_model_cost_milli": {"deepseek-v4-pro": 12_000},
            "by_model_calls": {"deepseek-v4-pro": 7},
            "unpriced_calls": 2,
        }
    )
    result = _handle_model_command(
        store, config, ["usage"], usage_store=usage_store
    )
    assert "账单：12.00 元" in result
    assert "口径注记" not in result
    assert "账本健康" not in result
