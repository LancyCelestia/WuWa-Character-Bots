"""B1：把 AxonHub 网关侧的归因事实回填进 bot 账本（2026-09-25 用户裁定 C）。

用户要的字段与来源（全部实测过，见 docs/HANDBOOK.md §44）：

| 要什么 | 网关真身 |
|---|---|
| 路由到哪个渠道的哪个模型 | ``requests.channel_id`` → ``channels.name`` |
| 中间试了哪些渠道/模型、有什么错误 | ``request_executions``（逐跳 channel/model/status/code/error/latency） |
| 首字时间、总输出时间 | ``requests.metrics_first_token_latency_ms`` / ``metrics_latency_ms`` |
| 输入/缓存创建/缓存读取/输出 token | ``usage_logs`` 四列（含 ``prompt_write_cached_tokens``） |
| 四项分项价格 | ``usage_logs.cost_items`` 四 itemCode 的 subtotal |

**关联键**：响应体 ``id`` == ``requests.external_id``（实测 12384 逐字符相等）。
响应头 ``Ah-Request-Id`` 反而**不落库**（requests.trace_id 是 bigint），所以不走头。

三态可区分是本文件的主要职责：``attribution_status`` 为 ``matched`` / ``miss``
/ ``unavailable`` / ``''``（未启用），缺了它「没查到」会被读成「没有渠道」。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    axonhub_attribution,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.axonhub_attribution import (
    Attribution,
    AttributionResolver,
    HopFact,
    make_batch_lookup,
    parse_rows,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    LedgerService,
    LLMCallDraft,
    apply_attribution,
    build_call_draft,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    OpenAICompatibleLLMProvider,
)

# ---------------------------------------------------------------- 夹具


def _draft(**kwargs: object) -> LLMCallDraft:
    base: dict[str, object] = {
        "request_id": "req-1",
        "started_at": "2026-09-25T01:00:00.000+08:00",
        "completed_at": "2026-09-25T01:00:12.000+08:00",
        "model_id": "axon-gemini-38-flash",
        "usage": {"prompt_tokens": 3, "completion_tokens": 66, "total_tokens": 69},
        "attempts": ["axon-gemini-38-flash:success"],
        "status": "success",
    }
    base.update(kwargs)
    return build_call_draft(**base)  # type: ignore[arg-type]


def _attribution(**kwargs: object) -> Attribution:
    base: dict[str, object] = {
        # 单体形态缺省不带 id＝"调用方已按键取好了这一条"；带上别的 id 则不许并（见
        # test_single_form_with_other_id_is_not_merged）。
        "remote_request_id": "",
        "gateway_channel": "恒星纪元 - Gemini",
        "gateway_model_id": "gemini-3.8-flash",
        "status": "completed",
        "latency_ms": 22319,
        "first_token_latency_ms": None,
        "hops": [
            HopFact(
                channel="恒星纪元 - Gemini",
                model_id="gemini-3.8-flash",
                status="failed",
                status_code=502,
                latency_ms=None,
                error="Upstream provider closed the connection",
            ),
            HopFact(
                channel="恒星纪元 - Gemini",
                model_id="gemini-3.8-flash",
                status="completed",
                status_code=None,
                latency_ms=22319,
                error="",
            ),
        ],
        "prompt_tokens": 3,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "completion_tokens": 66,
        "total_cost_micro": 0,
        "item_cost_milli": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cached_tokens": 0,
            "prompt_write_cached_tokens": 0,
        },
    }
    base.update(kwargs)
    return Attribution(**base)  # type: ignore[arg-type]


# ------------------------------------------------- 1. providers：拿到关联键


def test_provider_records_response_id(_monkeypatch_provider) -> None:
    """响应体 id 是网关的 external_id——B1 全靠它，必须进 LLMReply。"""
    reply = _monkeypatch_provider.generate([{"role": "user", "content": "hi"}])
    assert reply.remote_request_id == "Hlq1atqaIImw1MkP1LCm4A4"


def test_provider_without_id_stays_empty(_monkeypatch_provider_no_id) -> None:
    assert _monkeypatch_provider_no_id.generate(
        [{"role": "user", "content": "hi"}]
    ).remote_request_id == ""


# ------------------------------------------------- 2. draft 承载关联键


def test_draft_carries_remote_request_id() -> None:
    draft = _draft(remote_request_id="abc123")
    assert draft.remote_request_id == "abc123"
    assert draft.attribution_status == "", "未查过必须留空，不能写成 miss"


# ------------------------------------------------- 3. 回填语义


def test_matched_row_fills_channel_hops_and_item_costs() -> None:
    draft = _draft(remote_request_id="Hlq1atqaIImw1MkP1LCm4A4")
    attr = _attribution(
        total_cost_micro=999_000,
        item_cost_milli={
            "prompt_tokens": 1,
            "completion_tokens": 99,
            "prompt_cached_tokens": 8,
            "prompt_write_cached_tokens": 3,
        },
    )
    apply_attribution(draft, attr)
    assert draft.attribution_status == "matched"
    assert draft.gateway_channel == "恒星纪元 - Gemini"
    hops = json.loads(draft.gateway_hops_json)
    assert [h["status"] for h in hops] == ["failed", "completed"], "逐跳顺序即时间序"
    assert draft.input_cost_milli == 1
    assert draft.output_cost_milli == 99
    assert draft.cache_read_cost_milli == 8
    assert draft.cache_creation_cost_milli == 3
    assert draft.total_cost_milli == 999
    assert draft.pricing_source == "gateway_cost_items"
    assert draft.unpriced == 0


def test_gateway_costs_are_authoritative_over_local_estimate() -> None:
    """A 段已让 usage.cost 压过本地自算价；分项到齐时更进一步，仍不许反向覆盖。"""
    draft = _draft(
        remote_request_id="x",
        usage={
            "prompt_tokens": 3,
            "completion_tokens": 66,
            "total_tokens": 69,
            "cost": 0.0001,
        },
        price_in=999.0,
        price_out=999.0,
    )
    assert draft.pricing_source == "gateway_cost"
    apply_attribution(draft, _attribution(total_cost_micro=999_000))
    assert draft.total_cost_milli == 999
    assert draft.pricing_source == "gateway_cost_items"


def test_missing_item_costs_keep_previous_total_not_zero() -> None:
    """cost_items 为空（未计价渠道）时不得把已有的合计冲成 0。"""
    draft = _draft(
        remote_request_id="x",
        usage={
            "prompt_tokens": 3,
            "completion_tokens": 66,
            "total_tokens": 69,
            "cost": 0.5,
        },
    )
    assert draft.total_cost_milli == 500
    apply_attribution(draft, _attribution(total_cost_micro=None, item_cost_milli={}))
    assert draft.total_cost_milli == 500
    assert draft.pricing_source == "gateway_cost"
    assert draft.attribution_status == "matched", "归因成功与是否计价是两件事"


def test_first_token_latency_only_filled_when_absent() -> None:
    draft = _draft(remote_request_id="x")
    apply_attribution(draft, _attribution(first_token_latency_ms=1234))
    assert draft.first_token_latency_ms == 1234
    apply_attribution(draft, _attribution(first_token_latency_ms=9999))
    assert draft.first_token_latency_ms == 1234, "已有观测值不许被后到的数改写"


def test_duration_ms_stays_bot_side() -> None:
    """duration_ms 是用户等的时间（含排队与 bot 侧开销），网关耗时另存列。"""
    draft = _draft(remote_request_id="x", duration_ms=30000)
    apply_attribution(draft, _attribution(latency_ms=22319))
    assert draft.duration_ms == 30000
    assert draft.gateway_latency_ms == 22319


def test_unmatched_and_unavailable_are_distinguishable() -> None:
    draft = _draft(remote_request_id="gone")
    apply_attribution(draft, None)
    assert draft.attribution_status == "unavailable"
    assert draft.gateway_channel == ""

    other = _draft(remote_request_id="gone")
    apply_attribution(other, {}, unavailable=False)
    assert other.attribution_status == "miss"


def test_apply_attribution_without_key_is_noop() -> None:
    draft = _draft()
    apply_attribution(draft, {"abc": _attribution()})
    assert draft.attribution_status == ""


def test_single_form_with_other_id_is_not_merged() -> None:
    """单体形态也必须对键：拿别人的归因并到这条上，比不并更糟。"""
    draft = _draft(remote_request_id="mine")
    apply_attribution(draft, _attribution(remote_request_id="someone-elses-row"))
    assert draft.attribution_status == "miss"
    assert draft.gateway_channel == ""


def test_batch_lookup_distinguishes_outage_from_miss() -> None:
    """``make_batch_lookup``：库不通回 None（unavailable），查了没有回 {}（miss）。

    这一层是必须的：resolver 自己永不抛、失败也只回空 dict，若直接接给账本，
    网关停机一晚之后的第一批会被标成「这批请求网关没记到渠道」——那是假事实。
    """
    def boom(_ids):
        raise RuntimeError("connection refused")

    down = AttributionResolver(dsn={}, timeout_seconds=1.0, fetch=boom)
    assert make_batch_lookup(down)(["a"]) is None

    def empty(_ids):
        return []

    up = AttributionResolver(dsn={}, timeout_seconds=1.0, fetch=empty)
    assert make_batch_lookup(up)(["a"]) == {}


def test_unavailable_marks_unavailable_not_miss(tmp_path) -> None:
    """落库侧走一遍：resolver 报障时账本上必须是 unavailable。"""
    def boom(_ids):
        raise RuntimeError("pg down")

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=make_batch_lookup(
            AttributionResolver(dsn={}, timeout_seconds=1.0, fetch=boom)
        ),
    )
    service.submit(_draft(remote_request_id="wid-9"))
    assert service.flush() == 1
    assert _fetch_row(service.db_path)["attribution_status"] == "unavailable"
    service.close()


def test_gateway_token_columns_fill_only_blanks() -> None:
    """token 四列只补空、不覆盖：bot 侧 `>0 才写键`，None 可能是"没缓存"也可能"上游没报"。

    网关是计费方，它给的数就是入账依据；但已有的本地观测值不能被后到的数改写。
    """
    draft = _draft(remote_request_id="x", usage={"prompt_tokens": 3})
    apply_attribution(
        draft,
        _attribution(
            prompt_tokens=999, cache_read_tokens=0, cache_creation_tokens=5,
            completion_tokens=7,
        ),
    )
    assert draft.prompt_tokens == 3, "已有值不被网关数覆盖"
    assert draft.cache_read_tokens == 0, "0 是有效观测，不是缺失"
    assert draft.cache_creation_tokens == 5
    assert draft.completion_tokens == 7


def test_gateway_zero_cache_tokens_replaces_none() -> None:
    """`cache_read_tokens` 从 None 变 0 是有意义的：报表据此区分"未报"与"确实没命中"。"""
    draft = _draft(remote_request_id="x")   # usage 里没缓存字段 → 两列 None
    apply_attribution(draft, _attribution(cache_read_tokens=0, cache_creation_tokens=0))
    assert draft.cache_read_tokens == 0
    assert draft.cache_creation_tokens == 0


# ------------------------------------------------- 4. 解析层（纯函数）


def test_parse_rows_maps_cost_items_to_milli() -> None:
    rows = [
        {
            "external_id": "id1",
            "gateway_request_pk": 12384,
            "channel_name": "恒星纪元 - Grok",
            "gateway_model_id": "grok-4.6",
            "request_status": "completed",
            "latency_ms": 35726,
            "first_token_latency_ms": None,
            "total_cost": 0.00231616,
            "cost_items": [
                {"itemCode": "prompt_tokens", "quantity": 7094, "subtotal": "0.00198632"},
                {"itemCode": "completion_tokens", "quantity": 382, "subtotal": "0.00032088"},
                {"itemCode": "prompt_cached_tokens", "quantity": 128, "subtotal": "0.00000896"},
            ],
            "prompt_tokens": 7222,
            "prompt_cached_tokens": 128,
            "prompt_write_cached_tokens": 0,
            "completion_tokens": 382,
            "hops": [
                {"channel": "恒星纪元 - Grok", "model_id": "grok-4.6",
                 "status": "failed", "code": 502, "latency_ms": None,
                 "error": "Upstream provider closed the connection"},
                {"channel": "恒星纪元 - Grok", "model_id": "grok-4.6",
                 "status": "completed", "code": None, "latency_ms": 35726, "error": ""},
            ],
        }
    ]
    got = parse_rows(["id1"], rows)
    attr = got["id1"]
    assert attr.gateway_channel == "恒星纪元 - Grok"
    assert attr.total_cost_milli == 2
    assert attr.item_cost_milli["prompt_tokens"] == 2
    assert attr.item_cost_milli["prompt_cached_tokens"] == 0
    assert "prompt_write_cached_tokens" not in attr.item_cost_milli, "网关没回这一项就不编"
    assert len(attr.hops) == 2
    assert attr.hops[0].error.startswith("Upstream")


def test_parse_rows_survives_dirty_payload() -> None:
    """网关列可空、cost_items 可能是字符串/None——解析层不许抛。"""
    rows = [{"external_id": "id2", "channel_name": None, "cost_items": "not-json",
             "total_cost": None, "hops": None, "latency_ms": "abc"}]
    attr = parse_rows(["id2"], rows)["id2"]
    assert attr.gateway_channel == ""
    assert attr.total_cost_milli is None
    assert attr.hops == []
    assert attr.latency_ms is None


# ------------------------------------------------- 5. resolver 的降级面


def test_resolver_disabled_without_dsn() -> None:
    assert AttributionResolver.from_config(
        SimpleNamespace(
            bot_axonhub_attribution_enabled=True,
            bot_axonhub_db_host="",
            bot_axonhub_db_port=5432,
            bot_axonhub_db_database="axonhub",
            bot_axonhub_db_user="",
            bot_axonhub_db_password="",
            bot_axonhub_attribution_timeout_seconds=3.0,
        )
    ) is None, "host/user 任一为空 ⇒ fail-closed 不建 resolver"


def test_resolver_disabled_by_switch() -> None:
    assert AttributionResolver.from_config(
        SimpleNamespace(
            bot_axonhub_attribution_enabled=False,
            bot_axonhub_db_host="127.0.0.1",
            bot_axonhub_db_port=5432,
            bot_axonhub_db_database="axonhub",
            bot_axonhub_db_user="axonhub_ro",
            bot_axonhub_db_password="pw",
            bot_axonhub_attribution_timeout_seconds=3.0,
        )
    ) is None


def test_resolver_never_raises_on_fetch_error() -> None:
    def boom(_ids):
        raise RuntimeError("connection refused")

    resolver = AttributionResolver(
        dsn={"host": "127.0.0.1"}, timeout_seconds=0.5, fetch=boom
    )
    assert resolver.lookup(["a", "b"]) == {}
    assert resolver.last_error.startswith("RuntimeError")


def test_resolver_skips_empty_ids_without_calling_fetch() -> None:
    calls: list[list[str]] = []

    def spy(ids):
        calls.append(list(ids))
        return []

    resolver = AttributionResolver(dsn={}, timeout_seconds=1.0, fetch=spy)
    assert resolver.lookup(["", None]) == {}  # type: ignore[list-item]
    assert calls == [], "空 id 不该发查询"


def test_resolver_drops_password_from_repr() -> None:
    resolver = AttributionResolver(
        dsn={"host": "h", "password": "s3cret"}, timeout_seconds=1.0, fetch=lambda _i: []
    )
    assert "s3cret" not in repr(resolver)
    assert "s3cret" not in str(resolver.dsn_summary())


# ------------------------------------------------- 6. SQL 只走参数


def test_lookup_sql_is_parameterized() -> None:
    sql = axonhub_attribution.ATTRIBUTION_SQL
    assert "$1" in sql
    assert "%s" not in sql
    for value in ("Hlq1atqaIImw1MkP1LCm4A4", "'; DROP TABLE requests; --"):
        assert value not in sql


# ------------------------------------------------- 7. 落库与迁移


def test_new_columns_persist(tmp_path) -> None:
    service = LedgerService(str(tmp_path / "ledger.sqlite3"),
                            writer_thread=_stub_writer())
    draft = _draft(remote_request_id="Hlq1atqaIImw1MkP1LCm4A4")
    apply_attribution(draft, _attribution(total_cost_micro=999_000))
    service.submit(draft)
    service.flush()
    row = _fetch_row(service.db_path)
    assert row["remote_request_id"] == "Hlq1atqaIImw1MkP1LCm4A4"
    assert row["gateway_channel"] == "恒星纪元 - Gemini"
    assert row["attribution_status"] == "matched"
    assert row["gateway_latency_ms"] == 22319
    assert json.loads(row["gateway_hops_json"])[0]["status"] == "failed"
    service.close()


def test_old_database_gets_columns_added(tmp_path) -> None:
    """生产库已按旧 DDL 建好 ⇒ 迁移必须 ALTER-if-missing，且不清空存量行。"""
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
    with sqlite3.connect(db_path) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(llm_call_records)")}
        n = con.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0]
    for column in ledger_module.ATTRIBUTION_COLUMNS:
        assert column in cols, column
    assert n == 1, "迁移不得动存量行"
    service.close()


def test_column_order_matches_payload_field_by_field(tmp_path) -> None:
    """逐列对账，防"列序与值序错一格"。

    为什么单独立这一条：占位符数量相等的锁**抓不到错位**——2026-09-25 本波插
    ``total_cost_micro`` 时就把它插到了 ``currency/pricing_source`` 之后，数量仍然
    对得上，而 ``executemany`` 当场整批失败（表现为"账本一行都没写进去"）。
    这里给每列一个互不相同的值，逐列比回来：错位＝某列拿到别人的值 ⇒ 立刻红。
    """
    from dataclasses import fields as dc_fields

    draft = LLMCallDraft()
    markers: dict[str, object] = {}
    for index, field_ in enumerate(dc_fields(LLMCallDraft), start=1):
        if field_.name in {"attempts", "gateway_hops"}:
            continue
        current = getattr(draft, field_.name)
        if isinstance(current, bool):
            continue
        if isinstance(current, int) or current is None:
            setattr(draft, field_.name, 1000 + index)
            markers[field_.name] = 1000 + index
        elif isinstance(current, str):
            value = f"m{index}"
            setattr(draft, field_.name, value)
            markers[field_.name] = value
    service = LedgerService(str(tmp_path / "ledger.sqlite3"),
                            writer_thread=_stub_writer())
    service.submit(draft)
    assert service.flush() == 1, "整批写失败＝列序与值序数量对不上但顺序错位"
    row = _fetch_row(service.db_path)
    columns = [
        c.strip() for c in ledger_module._INSERT_SQL.split("(", 1)[1]
        .split(")")[0].split(",")
    ]
    mismatched = {}
    for column in columns:
        if column == "created_at":
            continue
        expected = {
            "attempts_count": len(draft.attempts),
        }.get(column, markers.get(column, getattr(draft, column, None)))
        if expected is None:
            continue
        if row[column] != expected:
            mismatched[column] = (expected, row[column])
    assert not mismatched, f"列↔值错位：{mismatched}"
    service.close()


def test_insert_placeholder_count_matches_payload(tmp_path) -> None:
    service = LedgerService(str(tmp_path / "ledger.sqlite3"),
                            writer_thread=_stub_writer())
    sql = ledger_module._INSERT_SQL
    columns = sql.split("(", 1)[1].split(")")[0].split(",")
    placeholders = sql.split("VALUES")[1].count("?")
    assert len(columns) == placeholders
    draft = _draft(remote_request_id="x")
    apply_attribution(draft, _attribution())
    service.submit(draft)
    assert service.flush() == 1
    service.close()


# ------------------------------------------------- 8. 写线程富化（不碰回复路径）


def test_flush_enriches_via_resolver(tmp_path) -> None:
    seen: list[list[str]] = []

    def fake_lookup(ids):
        seen.append(list(ids))
        return {"wid-1": _attribution(total_cost_micro=999_000)}

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=fake_lookup,
    )
    service.submit(_draft(remote_request_id="wid-1"))
    service.submit(_draft(request_id="req-no-id", remote_request_id=""))
    service.flush()
    assert seen == [["wid-1"]], "只对有关联键的行发一次批量查询"
    rows = _fetch_rows(service.db_path)
    by_key = {r["request_id"]: r for r in rows}
    assert by_key["req-1"]["attribution_status"] == "matched"
    assert by_key["req-no-id"]["attribution_status"] == "", "无键行不该被标 miss"
    service.close()


def test_resolver_failure_does_not_block_write(tmp_path) -> None:
    def boom(_ids):
        raise RuntimeError("pg down")

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=boom,
    )
    service.submit(_draft(remote_request_id="wid-2"))
    assert service.flush() == 1, "归因故障绝不能连账本一起丢"
    row = _fetch_row(service.db_path)
    assert row["attribution_status"] == "unavailable"
    service.close()


def test_disabled_service_never_calls_lookup(tmp_path) -> None:
    """关闭态＝根本没装反查口（LedgerService 不接 lookup），不是装了个不调的。"""
    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
    )
    service.submit(_draft(remote_request_id="wid-3"))
    assert service.flush() == 1
    row = _fetch_row(service.db_path)
    assert row["attribution_status"] == ""
    assert row["gateway_channel"] == ""
    service.close()


def test_submilli_costs_survive_the_daily_sum(tmp_path) -> None:
    """钱数锁：单发 0.219 毫厘若按行取整就是 0，一天 500 发会报成 0 元。

    实测口径（2026-09-25，直连网关一发 gemini 短回复）``usage.cost = 0.000219`` 元。
    微元列让逐行不丢精度、聚合处才取整 ⇒ 三发合计 0.657 毫厘四舍五入＝1 毫厘，
    而不是 0。钉这一条是因为"账单看着 0 元"比"没账"更危险：会被当成本极低来决策。
    """
    service = LedgerService(str(tmp_path / "ledger.sqlite3"),
                            writer_thread=_stub_writer())
    for index in range(3):
        service.submit(
            build_call_draft(
                request_id=f"req-{index}",
                started_at="2026-09-25T01:00:00.000+08:00",
                completed_at="2026-09-25T01:00:12.000+08:00",
                model_id="axon-gemini-38-flash",
                actual_model="gemini-3.8-flash",
                usage={"prompt_tokens": 5, "completion_tokens": 145,
                       "total_tokens": 150, "cost": 0.000219},
                attempts=["axon-gemini-38-flash:success"],
                status="success",
            )
        )
    assert service.flush() == 3
    with sqlite3.connect(service.db_path) as con:
        con.row_factory = sqlite3.Row
        rows = list(con.execute(
            "SELECT total_cost_milli, total_cost_micro FROM llm_call_records"
        ))
    assert {r["total_cost_micro"] for r in rows} == {219}
    assert {r["total_cost_milli"] for r in rows} == {0}, "逐行仍是整数毫厘（兼容旧列）"
    aggregated = ledger_module.aggregate_channel_usage(
        service.db_path, start_day="2026-09-25", end_day="2026-09-26"
    )
    assert sum(int(v["cost_milli"]) for v in aggregated.values()) == 1
    service.close()


def test_unavailable_when_gateway_db_absent(tmp_path) -> None:
    """网关库不在（没起 / 换机 / 只读账号没建）⇒ 账本照写，并把"没查成"记在账上。

    这一走的是真 asyncpg + 真 TCP（端口 1 必拒），不是桩：验的是"生产上没装/没起
    会发生什么"，桩验不出来。
    """
    resolver = AttributionResolver(
        dsn={"host": "127.0.0.1", "port": 1, "database": "x", "user": "y",
             "password": "z"},
        timeout_seconds=0.4,
    )
    assert resolver.lookup(["whatever"]) == {}
    assert resolver.last_error, "必须留下可读原因，不能静默空手而归"
    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=make_batch_lookup(resolver),
    )
    service.submit(_draft(remote_request_id="wid-live"))
    assert service.flush() == 1
    assert _fetch_row(service.db_path)["attribution_status"] == "unavailable"
    service.close()


# ------------------------------------------------- 9. 配置键在册（防静默丢弃）


def test_attribution_config_fields_are_declared() -> None:
    from plugins.bot_unified_runtime.config import Config

    for field_name in axonhub_attribution.ATTRIBUTION_CONFIG_FIELDS:
        assert field_name in Config.model_fields, field_name


def test_restart_required_keys_cover_the_switch() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RESTART_REQUIRED_KEYS,
    )

    assert "BOT_AXONHUB_ATTRIBUTION_ENABLED" in RESTART_REQUIRED_KEYS


# ------------------------------------------------- 夹具实现


@pytest.fixture
def _monkeypatch_provider(monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleLLMProvider:
    return _provider_with(monkeypatch, {"id": "Hlq1atqaIImw1MkP1LCm4A4"})


@pytest.fixture
def _monkeypatch_provider_no_id(monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleLLMProvider:
    return _provider_with(monkeypatch, {})


def _provider_with(
    monkeypatch: pytest.MonkeyPatch, extra: dict
) -> OpenAICompatibleLLMProvider:
    payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "model": "gemini-3.8-flash",
    }
    payload.update(extra)
    provider = OpenAICompatibleLLMProvider(
        api_key="k", base_url="http://127.0.0.1:8090/v1", model="gemini-3.8-flash"
    )
    monkeypatch.setattr(
        provider,
        "_post_via_httpx",
        lambda body, headers, timeout: json.dumps(payload),
    )
    return provider


def _stub_writer() -> threading.Thread:
    """未启动的桩线程：LedgerService 不起后台写线程，flush 全同步（与 test_llm_ledger 同法）。"""
    return threading.Thread(target=lambda: None)


def _fetch_row(db_path: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM llm_call_records ORDER BY id DESC LIMIT 1"
        ).fetchone()


def _fetch_rows(db_path: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return list(con.execute("SELECT * FROM llm_call_records ORDER BY id"))


def test_empty_batch_result_is_miss_not_unavailable(tmp_path) -> None:
    """查成了但网关没有这些 id ⇒ ``miss``；只有没查成才 ``unavailable``。

    两态混同的代价是假的否定事实：``unavailable`` 读起来像「网关没记到渠道」，
    而真相可能是「这条压根不是走这个网关的」。E2 复算坐实批量路径把 ``{}``
    写成了 unavailable（单条路径由 ``apply_attribution`` 缺省值兜着，所以离线
    单测全绿）。
    """
    def empty(_ids):
        return []

    service = LedgerService(
        str(tmp_path / "ledger-miss.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=empty,
    )
    service.submit(_draft(remote_request_id="wid-empty"))
    assert service.flush() == 1
    assert _fetch_row(service.db_path)["attribution_status"] == "miss"
    service.close()


def test_hop_error_text_is_redacted_before_storage() -> None:
    """逐跳错误原文是**网关原文**，实测含上游 base URL 与键形态；入库前必须过
    统一脱敏咽喉（铁律 3），否则将来把它投影到诊断卡/报表就是一次外泄面。"""
    rows = [
        {
            "external_id": "wid-hop",
            "channel_name": "恒星纪元 - Grok",
            "model_id": "grok-4.6",
            "latency_ms": 1200,
            "hops": [
                {
                    "channel": "x",
                    "model_id": "m",
                    "status": "failed",
                    "code": 401,
                    "error": "Bearer sk-abcdefghijklmnopqrstuvwxyz012345 denied "
                    r"at C:\Users\LancyCelestia\.env",
                }
            ],
        }
    ]
    parsed = parse_rows(["wid-hop"], rows)
    error = parsed["wid-hop"].hops[0].error
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in error, error
    assert "LancyCelestia" not in error, error
