"""中央出站防风暴闸（B4-spec §1）反证回归。

全部离线：注入时钟 + 假队列/假 store + tmp_path SQLite；零网络、零 NoneBot 运行时。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_outbound_gate.py -q \\
        -p no:cacheprovider --basetemp=$TEMP/b4a

规格反证清单映射（`specs/B4-outbound-gate-and-delivery-verification.md` §4）：

- T1 `test_gate_disabled_is_passthrough`——闸关闭时必须**字节级现状**：裸 submit 一次
  （不带任何关键字）、零 store 触点、零审计门事件（「关而不止」即红）。
- T2 `test_quiet_hours_defers_non_urgent_p0_p1_pass`——D-2 裁定：仅 P0/P1 穿静默，
  其余顺延到安静结束（时刻=quiet_end，含跨零点窗）。
- T3 `test_per_target_minute_cap_defers` / `test_per_target_hour_cap_defers`——每主体
  60s/3600s 双滑窗，主体键 `{target_scope}:{target_id}`，超限 defer 复用队列原生
  `deliver_after` 原语（不造第二张 delay 表）。
- T4 `test_gate_store_failure_fails_open`——方向性锁：store 病必须 allow（闸自身故障
  不得变成丢消息），同时挂出 `outbound_gate_degraded`。
- T5 `test_dedupe_key_shape_enforced`——键规范强制（E5 §4.3
  `emg:{channel}:{item_id}:{target_id}[:{date_key}]`），不合规 skip 且**绝不触队列**；
  合规键透传给队列，由 `ON CONFLICT` 出 skipped（闸不另建去重账）。
- T6 `test_existing_families_still_submit_directly` /
  `test_submit_active_push_production_importers_are_allowlisted`——存量 6 族「只登记不
  迁移」结构锁（先例 `tests/test_v21_wiredirect_unified_path.py`）。
- T12 `test_no_new_receipt_state`——contracts 禁改纪律（不得新增 PARTIAL_SENT 之类）。
- T13 `test_gate_reuses_quiet_hours_single_source`——G5 锁：quiet 设置与 HH:MM 解析唯一
  事实源仍是 `policy/quiet_hours.py`，本闸不得自造第二套窗判定/解析。

三门顺序（quiet → 每主体限流 → dedupe 键规范）由「三门顺序」一节三条用例锁死：第一个
给出结论的门即赢，后面的门不得抢先。
"""
from __future__ import annotations

import ast
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursSettings,
)
from plugins.bot_unified_runtime.domains.core.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger

GATE_MODULE = "plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
ROOT_INIT = PLUGIN_ROOT / "__init__.py"

# 现役 6 族直调 send_queue.submit 的 dedupe 锚点（B4-spec §1.5 登记表）。行号会漂
# （本波实测 __init__.py:2954/3065/3223/3372/5044），故按「直调计数 + 关键前缀」锁。
INIT_DEDUPE_ANCHORS = ("digest_push:", "daily_assist:")
CAMPUS_FILE = PLUGIN_ROOT / "domains" / "assistant" / "campus" / "campus.py"
CAMPUS_DEDUPE_ANCHOR = "campus_fwd:"

QUIET_END = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------- 测试替身
def _utc(hour: int, minute: int, *, day: int = 14) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def _request(
    *,
    request_id: str = "req-emg-1",
    dedupe_key: str = "emg:qq:item-1:g-1:2026-09-14",
    priority: str = "P2",
    target_scope: SessionType = SessionType.GROUP,
    target_id: str = "g-1",
    capability_id: str = "bot.emergency",
) -> SendRequest:
    text = "暴雨红色预警，请就近避雨。"
    return SendRequest(
        request_id=request_id,
        session_id=f"{target_scope.value}:{target_id}",
        target_scope=target_scope,
        target_id=target_id,
        capability_id=capability_id,
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={"text": text},
            text_fallback=text,
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy=SendPolicy.QUEUED,
        priority=priority,
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"{capability_id}:{target_scope.value}:{target_id}",
        privacy_level=PrivacyLevel.PUBLIC,
        persona_profile_id="default",
    )


class RecordingQueue:
    """假队列：原样记录每次 submit 的调用形态（裸调用 vs 带 deliver_after）。

    生产语义复刻：同一 dedupe_key 第二次返回 SKIPPED 回执（幂等账在队列侧）。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._seen: set[str] = set()

    def submit(self, send_request: SendRequest, **kwargs: Any) -> DeliveryReceipt:
        self.calls.append((send_request.request_id, dict(kwargs)))
        if send_request.dedupe_key in self._seen:
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SKIPPED,
                transport="memory",
                public_message="duplicate dedupe_key",
            )
        self._seen.add(send_request.dedupe_key)
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.QUEUED,
            transport="memory",
            public_message="queued",
        )

    def find_request(self, request_id: str) -> SendRequest | None:
        return None

    def safe_summary(self) -> dict[str, int]:
        return {}


class LegacyQueueWithoutDeliverAfter:
    """InMemorySendQueue 形态复刻：`submit` 无 ``deliver_after`` 形参（queue.py:191）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        self.calls.append(send_request.request_id)
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.QUEUED,
            transport="memory",
            public_message="queued",
        )


class FakeStore:
    """假 store：确定性滑窗计数；可注入异常以证 fail-open。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, datetime]] = []
        self.count_calls: list[tuple[str, datetime]] = []
        self.raise_on_count: Exception | None = None
        self.raise_on_record: Exception | None = None

    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        self.count_calls.append((subject_key, since_utc))
        if self.raise_on_count is not None:
            raise self.raise_on_count
        return sum(
            1
            for key, sent_at in self.rows
            if key == subject_key and sent_at >= since_utc
        )

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        if self.raise_on_record is not None:
            raise self.raise_on_record
        self.rows.append((subject_key, now_utc))

    def prune(self, *, before_utc: datetime) -> int:
        del before_utc
        return 0


def _quiet(**overrides: Any) -> QuietHoursSettings:
    base: dict[str, Any] = {
        "enabled": True,
        "start_time": "00:00",
        "end_time": "06:00",
        "timezone_name": "UTC",
        "session_types": ["group", "private"],
    }
    base.update(overrides)
    return QuietHoursSettings(**base)


def _gate(
    *,
    settings: Any = None,
    quiet: Any = None,
    store: Any = None,
    now: datetime | None = None,
    audit: InMemoryAuditLogger | None = None,
    sink: Callable[[OperationalIssue], None] | None = None,
):  # 返回 OutboundGate（不锁名：避开模块级循环 import）
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
    )

    fixed = now or _utc(12, 0)
    return OutboundGate(
        settings,
        quiet_settings=quiet,
        store=store if store is not None else FakeStore(),
        clock=lambda: fixed,
        audit_logger=audit or InMemoryAuditLogger(),
        issue_sink=sink,
    )


def _push(
    send_queue: Any,
    send_request: SendRequest,
    gate: Any,
    **kwargs: Any,
):
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    return submit_active_push(send_queue, send_request, gate, **kwargs)


def _events(audit: InMemoryAuditLogger, request_id: str | None = None) -> list[str]:
    return [record.event for record in audit.list_records(request_id)]


# ------------------------------------------------------------------ T1 缺省即直通
def test_gate_disabled_is_passthrough() -> None:
    """T1：enabled=False → 裸 submit 恰一次，零 store 触点、零闸审计。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    store = FakeStore()
    audit = InMemoryAuditLogger()
    gate = _gate(
        settings=OutboundGateSettings(enabled=False),
        quiet=_quiet(),
        store=store,
        audit=audit,
        now=_utc(3, 0),  # 静默窗内：关闭态必须完全无感
    )

    outcome = _push(queue, _request(), gate, now=_utc(3, 0))

    assert outcome.verdict.action == "allow"
    assert outcome.receipt is not None
    assert outcome.receipt.state is ReceiptState.QUEUED
    # 字节级现状：不带任何关键字参数（与现役 6 族裸调用同形）。
    assert queue.calls == [("req-emg-1", {})]
    assert store.rows == []
    assert store.count_calls == []
    assert _events(audit) == []


def test_default_settings_keep_gate_off() -> None:
    """缺省值裁定：全部新键缺省=关闭/现状字节级不动（spec §1.5 唯一硬约束）。

    本席禁改 `config.py`，故缺省链路的可验收面=设置投影本体 + `getattr` 口径
    （六键未落地时按缺省关闭，落地后由下一条用例钉住实值）。
    """
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
        build_outbound_gate,
        build_outbound_gate_settings,
    )

    defaults = OutboundGateSettings()
    assert defaults.enabled is False
    assert defaults.quiet_defer_enabled is True
    assert defaults.urgent_severities == ["P0", "P1"]
    assert defaults.max_per_target_per_minute == 2
    assert defaults.max_per_target_per_hour == 6
    # 空配置（键未落地）投影 == 缺省（关闭），且构建出的闸走直通裸 submit。
    assert build_outbound_gate_settings(SimpleNamespace()) == defaults

    queue = RecordingQueue()
    gate = build_outbound_gate(SimpleNamespace())
    assert gate.enabled is False
    outcome = _push(queue, _request(), gate, now=_utc(3, 0))
    assert outcome.verdict.action == "allow"
    assert outcome.verdict.reason == "disabled"
    assert queue.calls == [("req-emg-1", {})]


_GATE_CONFIG_KEYS = (
    "bot_outbound_gate_enabled",
    "bot_outbound_gate_quiet_defer_enabled",
    "bot_outbound_gate_urgent_severities",
    "bot_outbound_gate_max_per_target_per_minute",
    "bot_outbound_gate_max_per_target_per_hour",
    "bot_outbound_gate_db_path",
)


def _gate_config_keys_landed() -> bool:
    """六键是否已进 `config.py`（本席禁改该面，落地由合流席完成）。"""
    from plugins.bot_unified_runtime.config import Config

    fields = getattr(Config, "model_fields", {})
    return all(key in fields for key in _GATE_CONFIG_KEYS)


@pytest.mark.skipif(
    not _gate_config_keys_landed(),
    reason="六枚 bot_outbound_gate_* 键待合流席落地 config.py（本席禁改该面）；"
    "落地后本用例自动生效并钉住缺省值与路径重映射",
)
def test_config_keys_keep_gate_off() -> None:
    """六键一旦落地：缺省必须仍是关闭/现状不动，且 db_path 已进重映射（绝对路径）。"""
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
        build_outbound_gate,
        build_outbound_gate_settings,
    )

    config = Config()
    assert config.bot_outbound_gate_enabled is False
    assert config.bot_outbound_gate_quiet_defer_enabled is True
    assert config.bot_outbound_gate_urgent_severities == ["P0", "P1"]
    assert config.bot_outbound_gate_max_per_target_per_minute == 2
    assert config.bot_outbound_gate_max_per_target_per_hour == 6
    # 路径类字段必须进 runtime_paths 重映射（铁律 6：源码树零 data/）。
    assert Path(str(config.bot_outbound_gate_db_path)).is_absolute()
    projected = build_outbound_gate_settings(config)
    assert projected == OutboundGateSettings(
        db_path=str(config.bot_outbound_gate_db_path)
    )
    assert projected.enabled is False

    queue = RecordingQueue()
    outcome = _push(queue, _request(), build_outbound_gate(config), now=_utc(3, 0))
    assert outcome.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]


# ------------------------------------------------------------------ T2 静默顺延
def test_quiet_hours_defers_non_urgent_p0_p1_pass() -> None:
    """T2：静默窗内 P2 顺延到 quiet_end；P0/P1 立即放行（D-2 唯一穿窗口径）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    quiet = _quiet(start_time="00:00", end_time="06:00", timezone_name="UTC")
    settings = OutboundGateSettings(enabled=True)

    queue = RecordingQueue()
    deferred = _push(
        queue,
        _request(priority="P2"),
        _gate(settings=settings, quiet=quiet, store=FakeStore(), now=_utc(3, 0)),
        now=_utc(3, 0),
    )
    assert deferred.verdict.action == "defer"
    assert deferred.verdict.reason == "quiet_hours"
    assert deferred.verdict.deliver_after == QUIET_END
    # defer 必须复用队列原生 deliver_after 原语（不造第二张 delay 表）。
    assert queue.calls == [("req-emg-1", {"deliver_after": QUIET_END})]

    urgent_queue = RecordingQueue()
    urgent_gate = _gate(
        settings=settings, quiet=quiet, store=FakeStore(), now=_utc(3, 0)
    )
    for severity in ("P0", "P1"):
        allowed = _push(
            urgent_queue,
            _request(request_id=f"req-{severity}", priority=severity),
            urgent_gate,
            now=_utc(3, 0),
        )
        assert allowed.verdict.action == "allow", severity
        assert allowed.verdict.deliver_after is None
        assert urgent_queue.calls[-1] == (f"req-{severity}", {})


def test_quiet_defer_handles_cross_midnight_window() -> None:
    """跨零点窗（23:00→07:00）：01:30 顺延到当日 07:00，23:30 顺延到次日 07:00。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    quiet = _quiet(start_time="23:00", end_time="07:00", timezone_name="UTC")
    settings = OutboundGateSettings(enabled=True)

    inside_after_midnight = _push(
        RecordingQueue(),
        _request(),
        _gate(settings=settings, quiet=quiet, now=_utc(1, 30)),
        now=_utc(1, 30),
    )
    assert inside_after_midnight.verdict.action == "defer"
    assert inside_after_midnight.verdict.deliver_after == datetime(
        2026, 9, 14, 7, 0, tzinfo=timezone.utc
    )

    before_midnight = _push(
        RecordingQueue(),
        _request(),
        _gate(settings=settings, quiet=quiet, now=_utc(23, 30)),
        now=_utc(23, 30),
    )
    assert before_midnight.verdict.deliver_after == datetime(
        2026, 9, 15, 7, 0, tzinfo=timezone.utc
    )

    outside = _push(
        RecordingQueue(),
        _request(priority="P2"),
        _gate(settings=settings, quiet=quiet, now=_utc(12, 0)),
        now=_utc(12, 0),
    )
    assert outside.verdict.action == "allow"


def test_quiet_window_evaluated_in_settings_timezone() -> None:
    """窗判定按 settings.timezone_name 换算（HK 03:00 ≠ UTC 03:00 静默）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    quiet = _quiet(
        start_time="00:00",
        end_time="06:00",
        timezone_name="Asia/Hong_Kong",
        session_types=["group"],
    )
    settings = OutboundGateSettings(enabled=True)

    # 12:00 UTC = 20:00 HK：不在窗内。
    evening = _push(
        RecordingQueue(),
        _request(),
        _gate(settings=settings, quiet=quiet, now=_utc(12, 0)),
        now=_utc(12, 0),
    )
    assert evening.verdict.action == "allow"

    # 16:30 UTC = 次日 00:30 HK：在窗内，顺延到 HK 06:00。
    night = _push(
        RecordingQueue(),
        _request(),
        _gate(settings=settings, quiet=quiet, now=_utc(16, 30)),
        now=_utc(16, 30),
    )
    assert night.verdict.action == "defer"
    expected_end = datetime(2026, 9, 15, 6, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert night.verdict.deliver_after is not None
    assert night.verdict.deliver_after.utcoffset() is not None
    assert night.verdict.deliver_after.astimezone(timezone.utc) == expected_end.astimezone(
        timezone.utc
    )


def test_quiet_only_applies_to_settings_session_types() -> None:
    """会话维度：session_types 之外的目标不顺延（缺省仅 group，私聊照投）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(target_scope=SessionType.PRIVATE, target_id="u-1"),
        _gate(
            settings=OutboundGateSettings(enabled=True),
            quiet=_quiet(session_types=["group"]),
            now=_utc(3, 0),
        ),
        now=_utc(3, 0),
    )
    assert outcome.verdict.action == "allow"


def test_quiet_defer_switch_off_allows_everything() -> None:
    """`bot_outbound_gate_quiet_defer_enabled=False` → 静默面整体不生效。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(),
        _gate(
            settings=OutboundGateSettings(enabled=True, quiet_defer_enabled=False),
            quiet=_quiet(),
            store=FakeStore(),
            now=_utc(3, 0),
        ),
        now=_utc(3, 0),
    )
    assert outcome.verdict.action == "allow"


def test_unknown_severity_is_treated_as_non_urgent() -> None:
    """方向性锁：priority 不是 P0..P3 形态一律按非紧急（保守顺延，绝不在深夜抢发）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(priority="normal"),
        _gate(settings=OutboundGateSettings(enabled=True), quiet=_quiet(), now=_utc(3, 0)),
        now=_utc(3, 0),
    )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.reason == "quiet_hours"


def test_urgent_severity_matching_is_case_insensitive() -> None:
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(priority="p0"),
        _gate(settings=OutboundGateSettings(enabled=True), quiet=_quiet(), now=_utc(3, 0)),
        now=_utc(3, 0),
    )
    assert outcome.verdict.action == "allow"


# ------------------------------------------------------------------ T3 每主体限流
def test_per_target_minute_cap_defers() -> None:
    """T3：同主体 60s 窗内第 cap+1 条 defer 且 `deliver_after<=now+60s`；换主体不受累。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    settings = OutboundGateSettings(
        enabled=True,
        max_per_target_per_minute=2,
        max_per_target_per_hour=6,
    )
    store = FakeStore()
    queue = RecordingQueue()
    gate = _gate(settings=settings, quiet=_quiet(enabled=False), store=store)
    now = _utc(12, 0)

    actions = []
    for index in range(3):
        outcome = _push(
            queue,
            _request(
                request_id=f"req-m-{index}",
                dedupe_key=f"emg:qq:m-{index}:g-1",
            ),
            gate,
            now=now,
        )
        actions.append((outcome.verdict.action, outcome.verdict.reason))

    assert actions == [
        ("allow", "allowed"),
        ("allow", "allowed"),
        ("defer", "rate_limit_per_minute"),
    ]
    third_kwargs = queue.calls[2][1]
    assert third_kwargs == {"deliver_after": now + timedelta(seconds=60)}
    assert third_kwargs["deliver_after"] <= now + timedelta(seconds=60)

    # 主体键 = f"{target_scope}:{target_id}"：换主体不得被牵连。
    other = _push(
        queue,
        _request(request_id="req-other", dedupe_key="emg:qq:m-x:g-2", target_id="g-2"),
        gate,
        now=now,
    )
    assert other.verdict.action == "allow"
    assert [key for key, _ in store.rows] == ["group:g-1", "group:g-1", "group:g-2"]


def test_per_target_hour_cap_defers() -> None:
    """小时窗：分钟未超而小时超 → defer，时刻按 3600s 窗给（保守整窗）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    store = FakeStore()
    now = _utc(12, 0)
    store.record_send("group:g-1", now_utc=now - timedelta(minutes=30))
    store.record_send("group:g-1", now_utc=now - timedelta(minutes=20))
    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="emg:qq:h-1:g-1"),
        _gate(
            settings=OutboundGateSettings(
                enabled=True, max_per_target_per_minute=5, max_per_target_per_hour=2
            ),
            quiet=_quiet(enabled=False),
            store=store,
            now=now,
        ),
        now=now,
    )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.reason == "rate_limit_per_hour"
    assert outcome.verdict.deliver_after == now + timedelta(seconds=3600)


def test_zero_cap_means_that_window_is_disabled() -> None:
    """0=该窗不生效（与仓内 `bot_rate_limit_group_max_per_*` 同口径，不得拦死）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    store = FakeStore()
    for _ in range(5):
        store.record_send("group:g-1", now_utc=_utc(12, 0))
    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="emg:qq:z:g-1"),
        _gate(
            settings=OutboundGateSettings(
                enabled=True, max_per_target_per_minute=0, max_per_target_per_hour=0
            ),
            quiet=_quiet(enabled=False),
            store=store,
        ),
        now=_utc(12, 0),
    )
    assert outcome.verdict.action == "allow"


def test_only_allowed_pushes_are_counted() -> None:
    """计数只在 allow 落地：defer/skip 不得占窗（否则顺延把后续全饿死）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    store = FakeStore()
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=2),
        quiet=_quiet(enabled=False),
        store=store,
    )
    now = _utc(12, 0)
    for index in range(4):
        _push(
            RecordingQueue(),
            _request(
                request_id=f"req-c-{index}", dedupe_key=f"emg:qq:c-{index}:g-1"
            ),
            gate,
            now=now,
        )
    assert [key for key, _ in store.rows] == ["group:g-1", "group:g-1"]


# ------------------------------------------------------------------ T4 fail-open
def test_gate_store_failure_fails_open() -> None:
    """T4：store 抛错 → allow（不丢消息）+ 挂出 `outbound_gate_degraded`。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    store = FakeStore()
    store.raise_on_count = RuntimeError("disk on fire")
    issues: list[OperationalIssue] = []
    queue = RecordingQueue()
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),  # 窗内：即使静默判定也来不及，store 病必须放行
        store=store,
        sink=issues.append,
        now=_utc(3, 0),
    )

    outcome = _push(queue, _request(), gate, now=_utc(3, 0))

    assert outcome.verdict.action == "allow"
    assert outcome.receipt is not None
    assert queue.calls == [("req-emg-1", {})]  # 绝不因闸自身故障丢消息
    assert [issue.kind for issue in issues] == ["outbound_gate_degraded"]
    assert outcome.receipt.operational_issue is not None
    assert outcome.receipt.operational_issue.kind == "outbound_gate_degraded"


def test_record_failure_still_allows_and_reports(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """写计数失败同样 fail-open，且日志可观测（正文不入日志）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    store = FakeStore()
    store.raise_on_record = RuntimeError("counting broke")
    issues: list[OperationalIssue] = []
    queue = RecordingQueue()
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=1),
        quiet=_quiet(enabled=False),
        store=store,
        sink=issues.append,
        now=_utc(12, 0),
    )
    with caplog.at_level("WARNING"):
        outcome = _push(
            queue, _request(dedupe_key="emg:qq:r:g-1"), gate, now=_utc(12, 0)
        )

    assert outcome.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]
    assert [issue.kind for issue in issues] == ["outbound_gate_degraded"]
    assert "outbound_gate" in caplog.text
    assert "暴雨红色预警" not in caplog.text


# ------------------------------------------------------------------ T5 dedupe 键规范
def test_dedupe_key_shape_enforced() -> None:
    """T5：按日重投族缺 date_key → skip 且不触队列；合规键透传。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    audit = InMemoryAuditLogger()
    queue = RecordingQueue()
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        audit=audit,
        now=_utc(12, 0),
    )

    bad = _push(
        queue,
        _request(dedupe_key="emg:qq:abc:target", priority="P0"),
        gate,
        now=_utc(12, 0),
        dedupe_family="daily",
    )
    assert bad.verdict.action == "skip"
    assert bad.verdict.reason == "dedupe_key_shape"
    assert queue.calls == []  # skip 绝不触队列
    assert bad.receipt is not None
    assert bad.receipt.state is ReceiptState.SKIPPED  # 同形态回执（queue.py:475 先例）
    assert _events(audit, "req-emg-1") == ["outbound_gate_skip"]

    daily_ok = _push(
        queue,
        _request(request_id="req-ok", dedupe_key="emg:qq:abc:target:2026-09-14"),
        gate,
        now=_utc(12, 0),
        dedupe_family="daily",
    )
    assert daily_ok.verdict.action == "allow"

    # 一次性族：bracket 语义 [:date_key] 可选，4 段合规。
    once_ok = _push(
        queue,
        _request(request_id="req-once", dedupe_key="emg:qq:abc:target"),
        gate,
        now=_utc(12, 0),
    )
    assert once_ok.verdict.action == "allow"


@pytest.mark.parametrize(
    ("bad_key", "why"),
    [
        ("digest_push:g-1:2026-09-14", "非 emg 命名空间（存量族键不得混入）"),
        ("emg:qq::target", "空段"),
        ("emg:qq:only-three", "段数不足"),
        ("emg:qq:a:b:c:d", "段数超限"),
        ("emgqqabcd", "无分隔"),
    ],
)
def test_malformed_dedupe_keys_are_skipped(bad_key: str, why: str) -> None:
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    outcome = _push(
        queue,
        _request(dedupe_key=bad_key),
        _gate(
            settings=OutboundGateSettings(enabled=True),
            quiet=_quiet(enabled=False),
            store=FakeStore(),
            now=_utc(12, 0),
        ),
        now=_utc(12, 0),
    )
    assert outcome.verdict.action == "skip", why
    assert outcome.verdict.reason == "dedupe_key_shape"
    assert queue.calls == []


def test_gate_does_not_build_second_dedupe_ledger(tmp_path: Path) -> None:
    """合规重复键由队列 ON CONFLICT 出 skipped（闸不另建去重账，真队列集成）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        SQLiteSendRequestQueue,
    )

    real_queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3", InMemoryAuditLogger()
    )
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=10),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_utc(12, 0),
    )
    first = _push(real_queue, _request(dedupe_key="emg:qq:same:g-1"), gate, now=_utc(12, 0))
    second = _push(
        real_queue,
        _request(request_id="req-emg-2", dedupe_key="emg:qq:same:g-1"),
        gate,
        now=_utc(12, 0),
    )
    assert first.receipt is not None
    assert first.receipt.state is ReceiptState.QUEUED
    assert second.receipt is not None
    assert second.receipt.state is ReceiptState.SKIPPED
    assert second.receipt.public_message == "duplicate dedupe_key"


# --------------------------------------------------------------------- 三门顺序
def test_quiet_gate_decides_before_rate_and_dedupe() -> None:
    """静默窗内：坏 dedupe 键也先得到 quiet 结论（第一道门赢）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="bogus-key", priority="P2"),
        _gate(
            settings=OutboundGateSettings(enabled=True),
            quiet=_quiet(),
            store=FakeStore(),
            now=_utc(3, 0),
        ),
        now=_utc(3, 0),
        dedupe_family="daily",
    )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.reason == "quiet_hours"


def test_rate_gate_decides_before_dedupe_shape() -> None:
    """限流窗满 + 坏键：结论来自限流门（第二道门赢第三道门）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(12, 0)
    store = FakeStore()
    store.record_send("group:g-1", now_utc=now)
    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="bogus-key"),
        _gate(
            settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=1),
            quiet=_quiet(enabled=False),
            store=store,
            now=now,
        ),
        now=now,
        dedupe_family="daily",
    )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.reason == "rate_limit_per_minute"


def test_urgent_still_hits_dedupe_shape_gate() -> None:
    """P0 穿静默，但 dedupe 键规范照旧强制（编程错误不因紧急豁免）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="bogus-key", priority="P0"),
        _gate(
            settings=OutboundGateSettings(enabled=True),
            quiet=_quiet(),
            store=FakeStore(),
            now=_utc(3, 0),
        ),
        now=_utc(3, 0),
        dedupe_family="daily",
    )
    assert outcome.verdict.action == "skip"
    assert outcome.verdict.reason == "dedupe_key_shape"


# --------------------------------------------------------------------- 风暴观测
def test_three_consecutive_defers_emit_storm_alert() -> None:
    """同一主体连续 3 次 defer → 一次 `outbound_gate_storm`（上游在轰闸）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    issues: list[OperationalIssue] = []
    now = _utc(3, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        now=now,
        sink=issues.append,
    )
    for index in range(3):
        _push(
            RecordingQueue(),
            _request(
                request_id=f"req-s-{index}", dedupe_key=f"emg:qq:s-{index}:g-1"
            ),
            gate,
            now=now,
        )
    kinds = [issue.kind for issue in issues]
    assert kinds.count("outbound_gate_storm") == 1
    storm = next(issue for issue in issues if issue.kind == "outbound_gate_storm")
    assert "group:g-1" not in storm.safe_summary  # 主体只以哈希出现


def test_storm_ledger_resets_after_allow() -> None:
    """放行即清连击账：2 次顺延 + 放行 + 2 次顺延不得报风暴。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    issues: list[OperationalIssue] = []
    now = _utc(3, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        now=now,
        sink=issues.append,
    )
    for index in range(2):
        _push(
            RecordingQueue(),
            _request(
                request_id=f"req-r-{index}", dedupe_key=f"emg:qq:r-{index}:g-1"
            ),
            gate,
            now=now,
        )
    _push(
        RecordingQueue(),
        _request(
            request_id="req-r-allow",
            dedupe_key="emg:qq:r-allow:g-1",
            priority="P0",
        ),
        gate,
        now=now,
    )
    for index in range(2):
        _push(
            RecordingQueue(),
            _request(
                request_id=f"req-ra-{index}", dedupe_key=f"emg:qq:ra-{index}:g-1"
            ),
            gate,
            now=now,
        )
    assert [issue.kind for issue in issues].count("outbound_gate_storm") == 0


# ------------------------------------------------------------------ 审计与日志
def test_allow_defer_skip_each_append_one_gate_audit() -> None:
    """每次放行/顺延/拒绝各记一条闸审计（spec §1.4），主体只以哈希出现。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    audit = InMemoryAuditLogger()
    now = _utc(3, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        audit=audit,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(request_id="req-a", priority="P0"),
        gate,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(request_id="req-b", dedupe_key="emg:qq:b:g-1", priority="P2"),
        gate,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(request_id="req-c", dedupe_key="bad", priority="P0"),
        gate,
        now=now,
        dedupe_family="daily",
    )

    assert _events(audit) == [
        "outbound_gate_allow",
        "outbound_gate_defer",
        "outbound_gate_skip",
    ]
    records = audit.list_records()
    assert all(record.stage == "sender" for record in records)
    assert all(record.capability_id == "bot.emergency" for record in records)
    joined = " ".join(f"{record.public_message} {record.private_debug}" for record in records)
    assert "暴雨红色预警" not in joined
    assert "group:g-1" not in joined  # 主体只以 sha256[:12] 出现
    assert "subject=" in joined


def test_log_line_carries_spec_fields_and_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(3, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        now=now,
    )
    with caplog.at_level("INFO"):
        _push(
            RecordingQueue(),
            _request(dedupe_key="emg:qq:lg:g-1", priority="P0"),
            gate,
            now=now,
        )
    text = caplog.text
    assert "outbound_gate" in text
    assert "action=allow" in text
    assert "request_id=req-emg-1" in text
    assert "capability_id=bot.emergency" in text
    assert "暴雨红色预警" not in text
    assert "group:g-1" not in text


# --------------------------------------------------------- 无 deliver_after 的队列
def test_legacy_queue_without_deliver_after_fails_open() -> None:
    """队列不认 deliver_after（InMemorySendQueue 形态）→ 不吞消息，但必须报 degraded。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    issues: list[OperationalIssue] = []
    queue = LegacyQueueWithoutDeliverAfter()
    now = _utc(3, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        now=now,
        sink=issues.append,
    )
    outcome = _push(queue, _request(), gate, now=now)

    assert outcome.verdict.action == "defer"  # 结论仍是顺延（如实记录）
    assert queue.calls == ["req-emg-1"]  # 但绝不丢：退化为裸 submit
    assert "outbound_gate_degraded" in [issue.kind for issue in issues]


# --------------------------------------------------------------------- 真 store
def test_sqlite_store_counts_and_prunes_deterministically(tmp_path: Path) -> None:
    """真 store（tmp_path）：滑窗只算窗内、prune 只砍过期，全离线确定性。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        SQLiteOutboundSendStore,
    )

    store = SQLiteOutboundSendStore(tmp_path / "outbound_gate.sqlite3")
    now = _utc(12, 0)
    store.record_send("group:g-1", now_utc=now - timedelta(seconds=30))
    store.record_send("group:g-1", now_utc=now - timedelta(seconds=90))
    store.record_send("group:g-2", now_utc=now)

    assert store.count_sends("group:g-1", since_utc=now - timedelta(seconds=60)) == 1
    assert store.count_sends("group:g-1", since_utc=now - timedelta(seconds=3600)) == 2
    assert store.count_sends("group:g-9", since_utc=now - timedelta(seconds=3600)) == 0

    removed = store.prune(before_utc=now - timedelta(seconds=60))
    assert removed == 1
    assert store.count_sends("group:g-1", since_utc=now - timedelta(seconds=3600)) == 1


def test_sqlite_store_failure_is_visible_to_gate(tmp_path: Path) -> None:
    """库路径不可用时闸仍放行（fail-open 走的是真 store 分支，不是假 store 特例）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
        SQLiteOutboundSendStore,
    )

    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    store = SQLiteOutboundSendStore(blocker / "nested" / "gate.sqlite3")
    issues: list[OperationalIssue] = []
    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=store,
        now=now,
        sink=issues.append,
    )
    outcome = _push(queue, _request(dedupe_key="emg:qq:br:g-1"), gate, now=now)

    assert outcome.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]
    assert "outbound_gate_degraded" in [issue.kind for issue in issues]


# --------------------------------------------------------------------- T6 结构锁
def _direct_submit_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "submit"
            and isinstance(node.func.value, ast.Name)
            and "queue" in node.func.value.id.lower()
        ):
            lines.append(int(node.lineno))
    return lines


def test_existing_families_still_submit_directly() -> None:
    """T6：现役 6 族仍直调 `send_queue.submit`（本波只登记不迁移）。"""
    assert ROOT_INIT.is_file(), ROOT_INIT
    source = ROOT_INIT.read_text(encoding="utf-8")
    assert "submit_active_push" not in source, (
        "根 __init__.py 一旦出现 submit_active_push，说明实施席顺手迁移了存量 6 族；"
        "B4-spec §1.5 裁定=只登记不迁移。"
    )
    assert len(_direct_submit_calls(ROOT_INIT)) >= 5, (
        "现役主动推送直调 send_queue.submit 五处（提醒/cookie 到期/群摘要/日常助理/校园）"
        "必须仍在；少于 5 处=已被绕开或改道"
    )
    for anchor in INIT_DEDUPE_ANCHORS:
        assert anchor in source, f"存量族 dedupe 锚点 {anchor} 消失，需复核是否被顺手迁移"
    assert CAMPUS_DEDUPE_ANCHOR in CAMPUS_FILE.read_text(encoding="utf-8")


def test_submit_active_push_production_importers_are_allowlisted() -> None:
    """T6：`submit_active_push` 的生产引用只允许出现在 transport 本体与紧急域。"""
    # 前缀必须是真身目录名 `emergency_info`：写成 `domains/emergency` 会同时放行任何
    # `domains/emergency*` 兄弟目录（过松）。另注：本锁在零消费者期是"空真"通过，
    # 接线落地后须由接线席补一条正向断言（生产 import 数 ≥ 1）才算闭合。
    allowed_prefixes = (
        (PLUGIN_ROOT / "domains" / "transport",),
        (PLUGIN_ROOT / "domains" / "emergency_info",),
    )
    offenders: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "outbound_gate.py" in path.name:
            continue
        if "submit_active_push" not in path.read_text(encoding="utf-8"):
            continue
        if not any(str(path).startswith(str(root)) for root in allowed_prefixes):
            offenders.append(path.relative_to(PLUGIN_ROOT).as_posix())
    assert offenders == [], (
        f"中央闸的唯一入口只允许紧急域（与 transport 本体）引用，越界：{offenders}"
    )


# --------------------------------------------------------------------- T12 契约锁
def test_no_new_receipt_state() -> None:
    """T12：`ReceiptState` 成员集合不变；contracts 未混入新状态。"""
    contracts_source = (
        PLUGIN_ROOT / "domains" / "core" / "contracts" / "runtime.py"
    ).read_text(encoding="utf-8")
    assert {member.value for member in ReceiptState} == {
        "accepted",
        "rendered",
        "queued",
        "sent",
        "skipped",
        "redirected",
        "blocked",
        "failed_retryable",
        "failed_final",
    }
    assert "PARTIAL_SENT" not in contracts_source


def test_outcome_models_reject_fourth_verdict() -> None:
    """结论只有 allow/defer/skip 三态；第四态（drop/partial_sent 之类）必须被拒。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        ActivePushOutcome,
        OutboundGateVerdict,
    )

    outcome = ActivePushOutcome(
        verdict=OutboundGateVerdict(action="allow", reason="allowed"), receipt=None
    )
    assert outcome.receipt is None
    assert outcome.verdict.deliver_after is None
    assert outcome.verdict.audit_tags == []
    with pytest.raises(ValidationError):
        OutboundGateVerdict(action="drop", reason="x")
    with pytest.raises(ValidationError):
        OutboundGateVerdict(action="allow", reason="x", unknown_field=1)


# ------------------------------------------------------------------ T13 G5 单一事实源
def test_gate_reuses_quiet_hours_single_source() -> None:
    """T13：quiet 设置与 HH:MM 解析唯一事实源 = policy/quiet_hours.py。"""
    gate_path = REPO_ROOT / GATE_MODULE
    tree = ast.parse(gate_path.read_text(encoding="utf-8"))
    imported: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )
    quiet_module = "plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours"
    assert quiet_module in imported, f"闸必须 import quiet_hours 设置族，实有 {sorted(imported)}"
    assert "QuietHoursSettings" in imported[quiet_module]
    assert "_parse_hhmm" in imported[quiet_module], (
        "HH:MM 解析必须复用 quiet_hours._parse_hhmm（唯一事实源），不得自造第二套"
    )
    source = gate_path.read_text(encoding="utf-8")
    assert "fromisoformat" not in source, "不得自造时间解析"
    # 复用即证据：_parse_hhmm 不但要 import，还要真的被调用（自造解析则这里是死导入）。
    assert source.count("_parse_hhmm") >= 2, "quiet 窗必须真调用共享解析器"
    for name in ("_parse_hhmm", "parse_hhmm", "_parse_time", "_parse_clock"):
        assert f"def {name}(" not in source, "不得在本文件定义第二套 HH:MM 解析"


def test_gate_does_not_import_schedule_engine() -> None:
    """G5：闸不复用日程引擎实例（未接线 + schema 深耦合），只复用词汇与队列原语。"""
    source = (REPO_ROOT / GATE_MODULE).read_text(encoding="utf-8")
    assert "domains.schedule" not in source, (
        "transport 层不得 import 日程域（B4-spec §5.1 域隔离裁定）"
    )
    assert "acquire_send_slot" not in source
    assert "build_digest" not in source, "digest 合并留接口未实现，本波诚实不装"


# --------------------------------------------------------------------- 设置热改
def test_callable_settings_are_reread_on_every_decision() -> None:
    """settings 支持 callable 热改（台账#3「限流不支持热改」旧坑不得复刻）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    state = {"enabled": False}
    now = _utc(3, 0)
    quiet = _quiet()
    gate = _gate(
        settings=lambda: OutboundGateSettings(enabled=state["enabled"]),
        quiet=quiet,
        store=FakeStore(),
        now=now,
    )
    off = _push(
        RecordingQueue(),
        _request(request_id="req-hot-1", dedupe_key="emg:qq:hot1:g-1"),
        gate,
        now=now,
    )
    assert off.verdict.reason == "disabled"

    state["enabled"] = True
    on = _push(
        RecordingQueue(),
        _request(request_id="req-hot-2", dedupe_key="emg:qq:hot2:g-1"),
        gate,
        now=now,
    )
    assert on.verdict.reason != "disabled"
    assert on.verdict.action == "defer"  # 同一个 callable 立即反映新状态（静默窗内）


def test_quiet_settings_are_also_hot_readable() -> None:
    """quiet 面同样支持 callable（quiet_hours.py:72-76 先例）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=lambda: _quiet(
            start_time="11:00", end_time="13:00", timezone_name="UTC"
        ),
        store=FakeStore(),
    )
    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="emg:qq:hq:g-1"),
        gate,
        now=now,
    )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.deliver_after == datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)


def test_settings_resolution_failure_falls_back_to_disabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """设置求值异常 → 回退缺省（关闭=直通），不误拦、不炸链路。"""

    def _boom() -> Any:
        raise RuntimeError("settings store down")

    queue = RecordingQueue()
    gate = _gate(settings=_boom, quiet=_quiet(), store=FakeStore())
    with caplog.at_level("ERROR"):
        outcome = _push(queue, _request(), gate, now=_utc(3, 0))
    assert outcome.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]
