"""S14 席：IncidentService 离线回归（V21-INCIDENT-001）。

覆盖：结构化字段、脱敏（render 真身 + 本地兜底 + 崩溃降级不泄漏）、
用户文本零保留、截断、同因聚合（窗内抑制/stride 重通知/窗过期重发/
count 累积 first_seen 保留）、sink 注入与默认日志面、sink 异常防递归、
查询过滤、环形上限、协议满足（IncidentSink/IncidentReporter）。
全离线：clock 注入，零网络零真实出站。
"""
from __future__ import annotations

import logging
from typing import Any

from plugins.bot_unified_runtime.domains.ops.incident import (
    Incident,
    IncidentAggregate,
    IncidentService,
    IncidentSink,
    LoggingIncidentSink,
    redact_text,
    redact_user_text,
)
from plugins.bot_unified_runtime.domains.ops.incident import service as incident_module
from plugins.bot_unified_runtime.domains.ops.recovery.service import IncidentReporter


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingSink:
    def __init__(self) -> None:
        self.emitted: list[Incident] = []

    def emit(self, incident: Incident) -> None:
        self.emitted.append(incident)


class ExplodingSink:
    def __init__(self) -> None:
        self.calls = 0

    def emit(self, incident: Incident) -> None:
        self.calls += 1
        raise RuntimeError("webhook down")


# ----------------------------------------------------------------------
# 脱敏
# ----------------------------------------------------------------------


def test_redact_masks_secret_shapes_via_render_truth():
    text = (
        "connect failed: key sk-abcdef123456 at C:\\Users\\me\\secret.pem, "
        "BOT_TOKEN=zzzsecret123 Bearer qqq1234567890 done"
    )
    masked = redact_text(text)
    assert "sk-abcdef123456" not in masked
    assert "Users" not in masked or masked != text  # 盘符路径形态必被处理
    assert masked != text
    assert redact_text("普通文本，无敏感形态。") == "普通文本，无敏感形态。"


def test_redact_fallback_masks_when_truth_missing():
    masked = incident_module._fallback_redact(
        "key sk-abcdef123456 C:\\Users\\me\\a.pem BOT_TOKEN=zzz Bearer qqq12345678"
    )
    assert "sk-abcdef123456" not in masked
    assert "Users" not in masked
    assert "zzz" not in masked
    assert "qqq12345678" not in masked


def test_redact_crash_falls_back_without_leak(monkeypatch):
    def broken(text: str) -> str:
        raise RuntimeError("redactor bug")

    monkeypatch.setattr(incident_module, "_REDACT_FN", broken)
    masked = redact_text("token sk-abcdef123456 end")
    assert "sk-abcdef123456" not in masked  # 兜底正则接住，不裸奔


def test_redact_idempotent():
    once = redact_text("call sk-abcdef123456 from C:\\tmp\\x.log")
    twice = redact_text(once)
    assert twice == once


def test_redact_user_text_keeps_only_length():
    assert redact_user_text("") == ""
    note = redact_user_text("机密内容abc")
    assert note == "<用户文本 7 字，已隐去>"
    assert "机密" not in note


# ----------------------------------------------------------------------
# 结构化字段
# ----------------------------------------------------------------------


def test_structured_fields_and_severity_normalization():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    first = service.report_incident(
        component="napcat_ws",
        severity="error",
        explanation="连接断开",
        method="reconnect",
        trace_id="tr-1",
    )
    assert first.seq == 1
    assert first.timestamp == clock.now
    assert first.component == "napcat_ws"
    assert first.severity == "error"
    assert first.explanation == "连接断开"
    assert first.method == "reconnect"
    assert first.trace_id == "tr-1"
    assert first.occurrence_count == 1
    second = service.report_incident(
        component="x", severity="不是合法档位", explanation="y"
    )
    assert second.severity == "warning"  # 未知档不猜高，落 warning
    assert second.seq == 2


def test_user_text_never_stored():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    incident = service.report_incident(
        component="chat",
        severity="warning",
        explanation="用户消息触发异常",
        user_text="这是用户发来的机密内容xyz",
    )
    assert "机密内容xyz" not in incident.explanation
    assert "已隐去" in incident.explanation
    stored = service.list_incidents()[0]
    assert "机密内容xyz" not in stored.explanation


def test_explanation_truncated_to_max_chars():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock, max_text_chars=50)
    incident = service.report_incident(
        component="c",
        severity="info",
        explanation="长" * 300,
    )
    assert incident.explanation.endswith("…(已截断)")
    assert len(incident.explanation) <= 50 + len("…(已截断)") + 1


def test_component_and_trace_clipped():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    incident = service.report_incident(
        component="C" * 500,
        severity="info",
        explanation="ok",
        trace_id="T" * 500,
    )
    assert len(incident.component) <= 120 + len("…(已截断)")
    assert incident.trace_id is not None
    assert len(incident.trace_id) <= 200 + len("…(已截断)")


# ----------------------------------------------------------------------
# 同因聚合
# ----------------------------------------------------------------------


def test_same_cause_within_window_suppresses_sink_but_counts():
    clock = FakeClock()
    sink = RecordingSink()
    service = IncidentService(sink=sink, clock=clock)
    service.report_incident(component="ws", severity="error", explanation="连接断开")
    second = service.report_incident(
        component="ws", severity="error", explanation="连接断开"
    )
    assert len(sink.emitted) == 1  # 窗内重复不刷通知
    assert second.occurrence_count == 2  # 计数照常累积
    assert service.sink_suppressed == 1
    assert service.list_incidents()[0].occurrence_count == 2


def test_stride_renotifies_on_multiple_of_stride():
    clock = FakeClock()
    sink = RecordingSink()
    service = IncidentService(sink=sink, clock=clock, notify_stride=2)
    service.report_incident(component="ws", severity="error", explanation="断")
    service.report_incident(component="ws", severity="error", explanation="断")
    service.report_incident(component="ws", severity="error", explanation="断")
    assert [i.occurrence_count for i in sink.emitted] == [1, 2]  # 第 3 次被抑制


def test_window_expiry_renotifies_and_count_accumulates():
    clock = FakeClock()
    sink = RecordingSink()
    service = IncidentService(
        sink=sink, clock=clock, aggregation_window_seconds=300.0
    )
    service.report_incident(component="ws", severity="error", explanation="断")
    clock.advance(1.0)
    service.report_incident(component="ws", severity="error", explanation="断")
    clock.advance(400.0)  # 距上次通知超窗 → 新 episode
    third = service.report_incident(component="ws", severity="error", explanation="断")
    assert len(sink.emitted) == 2
    assert third.occurrence_count == 3  # count 累积不清零
    aggregates = service.aggregates()
    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.count == 3
    assert agg.first_seen == 1_000_000.0  # 首见时间全历史保留
    assert agg.last_seen == 1_000_401.0


def test_different_cause_same_component_separate_fingerprints():
    clock = FakeClock()
    sink = RecordingSink()
    service = IncidentService(sink=sink, clock=clock)
    service.report_incident(component="ws", severity="error", explanation="连接断开")
    service.report_incident(component="ws", severity="error", explanation="鉴权被拒")
    assert len(sink.emitted) == 2
    assert len(service.aggregates()) == 2
    assert len({i.fingerprint for i in sink.emitted}) == 2


def test_same_text_different_component_separate_fingerprints():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    a = service.report_incident(component="a", severity="error", explanation="boom")
    b = service.report_incident(component="b", severity="error", explanation="boom")
    assert a.fingerprint != b.fingerprint


# ----------------------------------------------------------------------
# 通知面与防递归
# ----------------------------------------------------------------------


def test_sink_failure_is_counted_and_never_raises():
    clock = FakeClock()
    sink = ExplodingSink()
    service = IncidentService(sink=sink, clock=clock)
    incident = service.report_incident(component="ws", severity="error", explanation="断")
    assert incident.seq == 1  # 不外抛
    assert service.sink_failures == 1
    assert sink.calls == 1
    assert len(service.list_incidents()) == 1  # 照常入环
    second = service.report_incident(
        component="ws2", severity="error", explanation="别的故障"
    )
    assert second.seq == 2


def test_default_logging_sink_emits(caplog):
    service = IncidentService(clock=FakeClock())
    with caplog.at_level(logging.ERROR, logger="ops.incident"):
        service.report_incident(
            component="napcat_ws", severity="error", explanation="连接断开"
        )
    assert any("incident#" in r.getMessage() and "napcat_ws" in r.getMessage()
               for r in caplog.records)


# ----------------------------------------------------------------------
# 查询 API
# ----------------------------------------------------------------------


def _seed(service: IncidentService, clock: FakeClock) -> None:
    service.report_incident(component="c1", severity="warning", explanation="w1")
    clock.advance(10.0)
    service.report_incident(component="c1", severity="error", explanation="e1")
    clock.advance(10.0)
    service.report_incident(component="c2", severity="critical", explanation="k1")


def test_query_filters_and_ordering():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    _seed(service, clock)
    assert [i.component for i in service.list_incidents()] == ["c2", "c1", "c1"]
    only_c1 = service.list_incidents(component="c1")
    assert [i.severity for i in only_c1] == ["error", "warning"]
    serious = service.list_incidents(min_severity="error")
    assert [i.component for i in serious] == ["c2", "c1"]
    since = service.list_incidents(since=clock.now - 5.0)
    assert [i.component for i in since] == ["c2"]
    limited = service.list_incidents(limit=2)
    assert len(limited) == 2
    assert limited[0].seq > limited[-1].seq  # 新→旧


def test_get_incident_by_seq():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    created = service.report_incident(component="c", severity="info", explanation="x")
    assert service.get_incident(created.seq) is not None
    assert service.get_incident(created.seq).seq == created.seq
    assert service.get_incident(99999) is None


def test_aggregates_sorted_by_count_desc():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    service.report_incident(component="hot", severity="error", explanation="高频故障")
    for _ in range(4):
        clock.advance(400.0)  # 每次都过窗 → 全部通知、计数累积
        service.report_incident(component="hot", severity="error", explanation="高频故障")
    service.report_incident(component="cold", severity="info", explanation="偶发")
    aggs: list[IncidentAggregate] = service.aggregates()
    assert aggs[0].component == "hot"
    assert aggs[0].count == 5
    assert aggs[1].count == 1
    assert aggs[0].latest_severity == "error"


def test_ring_limit_drops_oldest_but_counts_total():
    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock, max_records=3)
    for n in range(5):
        service.report_incident(
            component="c", severity="info", explanation=f"故障编号-{n}"
        )
    stats: dict[str, int] = service.stats()
    assert stats["records"] == 3
    assert stats["total_reported"] == 5
    listed = service.list_incidents()
    assert listed[0].explanation.endswith("-4")  # 最新在
    assert not any(i.explanation.endswith("-0") for i in listed)  # 最旧被挤出环


# ----------------------------------------------------------------------
# 协议满足
# ----------------------------------------------------------------------


def test_protocols_satisfied():
    service = IncidentService(clock=FakeClock())
    assert isinstance(service, IncidentReporter)  # 事件源可直接注入 RecoveryService
    assert isinstance(LoggingIncidentSink(), IncidentSink)
    assert isinstance(RecordingSink(), IncidentSink)


def test_recovery_can_consume_incident_service_as_reporter():
    from plugins.bot_unified_runtime.domains.ops.recovery import (
        FailureKind,
        RecoveryOutcome,
        RecoveryService,
    )

    class OkExecutor:
        def execute(self, action: Any, context: Any) -> Any:
            return RecoveryOutcome(success=True)

    clock = FakeClock()
    service = IncidentService(sink=RecordingSink(), clock=clock)
    recovery = RecoveryService(
        executor=OkExecutor(), reporter=service, monotonic=clock  # type: ignore[arg-type]
    )
    recovery.handle_failure("ws", FailureKind.TRANSIENT_NETWORK, summary="断连")
    recovery.handle_failure("ws", FailureKind.PATCH_REQUIRED, summary="需要补丁")
    found = service.list_incidents()
    assert len(found) == 1  # 成功动作安静；不可重试上报 1 条
    assert found[0].component == "ws"
