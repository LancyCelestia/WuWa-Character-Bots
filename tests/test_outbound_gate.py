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
import hashlib
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
    RiskLevel,
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


def _expected_subject_hash(target_scope: SessionType, target_id: str) -> str:
    """日志/审计里该出现的主体标识：`sha256("{scope.value}:{target_id}")[:12]`。

    刻意在测试里用 hashlib 独立算一遍，而不是 import 闸的 `_subject_hash`——拿被测
    实现算期望值再和被测实现输出比＝同源自比，判 C 类恒真（LOCK-AUDIT 纪律）。
    """
    subject = f"{target_scope.value}:{target_id}"
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]


def _request(
    *,
    request_id: str = "req-emg-1",
    dedupe_key: str = "emg:qq:item-1:g-1:2026-09-14",
    priority: str = "P2",
    target_scope: SessionType = SessionType.GROUP,
    target_id: str = "g-1",
    capability_id: str = "bot.emergency",
    risk_level: RiskLevel = RiskLevel.LOW,
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
            risk_level=risk_level,
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
    # 钉**这条日志本身**（LOCK-AUDIT GAP-7：旧断言 `assert "outbound_gate" in
    # caplog.text` 会被 exc_info=True 回溯里的模块文件路径喂饱 ⇒ 把消息文本改成
    # 「gate counting broke (see traceback)」59 条全绿，只有整块删掉才红）。
    # 收窄到短语 + 结构化字段名与取值，文本漂移与字段涂值都必红。
    # LOCK-FIX-2 变异检验（C1）实证：只钉 `startswith("outbound_gate record_failure")`
    # 时，把消息改成「record_failure BROKEN subject_key_hash=…」测不到（短语前缀与
    # 字段子串都还在）——中间插词正是「文本漂移」的一种，短语+子串的组合拦不住它。
    # 故对这条 WARNING 取**整行等值**：格式串与取值一起钉，任何增删改词都红。
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
    ]
    assert (
        "outbound_gate record_failure subject_key_hash="
        f"{_expected_subject_hash(SessionType.GROUP, 'g-1')}"
    ) in messages, messages
    assert "暴雨红色预警" not in caplog.text
    assert "group:g-1" not in caplog.text


# --------------------------------- T7 观测面值（LOCK-FIX F-3：GAP-5 六面零锁补齐）
def test_log_line_carries_spec_fields_and_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """中央日志行的每个字段都钉**取值**，不钉「整条 text 里出现过某个词」。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(3, 0)
    store = FakeStore()
    # 预置一笔窗内已投：window_count 必须是**真数**（0 会让「涂成常数 0」这种病检不出）。
    store.rows.append(("group:g-1", now - timedelta(seconds=30)))
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=5),
        quiet=_quiet(),
        store=store,
        now=now,
    )
    with caplog.at_level("INFO"):
        _push(
            RecordingQueue(),
            _request(dedupe_key="emg:qq:lg:g-1", priority="P0"),
            gate,
            now=now,
        )
    line = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("outbound_gate action=")
    )
    subject_hash = _expected_subject_hash(SessionType.GROUP, "g-1")
    assert "action=allow" in line
    assert "reason=allowed" in line
    assert "request_id=req-emg-1" in line
    assert "capability_id=bot.emergency" in line
    assert f"subject_key_hash={subject_hash}" in line
    assert "window_count=1" in line  # 不含本次（判定时刻的窗内已投数）
    assert "deliver_after=none" in line  # 放行无顺延
    assert "暴雨红色预警" not in line
    assert "group:g-1" not in line  # 主体只以 sha256[:12] 出现
    assert subject_hash not in {"", "none"}


def test_audit_private_debug_carries_window_count_and_deliver_after() -> None:
    """审计 `private_debug` 四面：action / reason / subject 哈希 / window_count /
    deliver_after。GAP-5 的原始证据是「G23 G24 G25 三涂字段值 59 全绿」，本条起牙。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(12, 0)
    audit = InMemoryAuditLogger()
    store = FakeStore()
    store.rows.append(("group:g-1", now - timedelta(seconds=20)))
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=5),
        quiet=_quiet(enabled=False),
        store=store,
        audit=audit,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(request_id="req-dbg", dedupe_key="emg:qq:dbg:g-1"),
        gate,
        now=now,
    )
    records = audit.list_records("req-dbg")
    assert [record.event for record in records] == ["outbound_gate_allow"]
    debug = records[0].private_debug
    subject_hash = _expected_subject_hash(SessionType.GROUP, "g-1")
    assert f"action=allow reason=allowed subject={subject_hash}" in debug
    assert "window_count=1" in debug
    assert "deliver_after=none" in debug
    joined = f"{records[0].public_message} {debug}"
    assert "暴雨红色预警" not in joined and "group:g-1" not in joined


def test_deferred_audit_and_log_carry_the_real_defer_moment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """顺延时刻是「什么时候会发」的唯一可观测线索：钉到秒级 ISO 串。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(12, 0)
    audit = InMemoryAuditLogger()
    store = FakeStore()
    store.rows.append(("group:g-1", now - timedelta(seconds=10)))
    gate = _gate(
        settings=OutboundGateSettings(enabled=True, max_per_target_per_minute=1),
        quiet=_quiet(enabled=False),
        store=store,
        audit=audit,
        now=now,
    )
    with caplog.at_level("INFO"):
        outcome = _push(
            RecordingQueue(),
            _request(request_id="req-defer", dedupe_key="emg:qq:def:g-1"),
            gate,
            now=now,
        )
    assert outcome.verdict.action == "defer"
    assert outcome.verdict.deliver_after == now + timedelta(seconds=60)
    moment = "2026-09-14T12:01:00+00:00"
    debug = audit.list_records("req-defer")[0].private_debug
    assert f"deliver_after={moment}" in debug
    assert "action=defer" in debug and "reason=rate_limit_per_minute" in debug
    assert f"deliver_after={moment}" in caplog.text
    assert "window_count=1" in caplog.text


def test_skip_receipt_is_shaped_by_the_gate_and_never_invents_a_handle() -> None:
    """skip 回执三字段：`transport` 是闸自造口、`public_message` 带机读原因、
    `provider_message_id` 绝不臆造（闸没碰协议，就没有把手）。

    GAP-5 原证：G49 把 transport 改名、G50 把 public_message 恒置空 ⇒ 59 全绿。
    两条各有一侧正/负样本，所以「恒空」与「恒非空」都会红。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
    )
    outcome = _push(
        RecordingQueue(),
        _request(dedupe_key="emg:qq:a:b:c:d", priority="P0"),  # 六段超限
        gate,
        now=now,
    )
    receipt = outcome.receipt
    assert receipt is not None
    assert receipt.state is ReceiptState.SKIPPED
    assert receipt.transport == "outbound_gate"
    assert receipt.provider_message_id is None
    assert receipt.public_message == "dedupe_key_shape"  # 机读原因短语，非空也非正文
    assert "暴雨红色预警" not in receipt.public_message

    # 另一侧：请求自带 issue 时，public_message 让位为空串（issue 才是事实载体）。
    issue = OperationalIssue(stage="sender", kind="pre_existing", retryable=False)
    with_issue = _request(request_id="req-issue", dedupe_key="emg:qq:a:b:c:d")
    with_issue = with_issue.model_copy(update={"operational_issue": issue})
    second = _push(RecordingQueue(), with_issue, gate, now=now)
    assert second.receipt is not None
    assert second.receipt.public_message == ""
    assert second.receipt.operational_issue is not None
    assert second.receipt.operational_issue.kind == "pre_existing"


def test_audit_severity_comes_from_the_request_content_risk_level() -> None:
    """审计 severity 取值：来自 `send_request.content.risk_level`，不是常数也不是 issue 默认。

    GAP-5 原证：G47b 换源之所以「红」是因为 append 抛异常（`RiskLevel` 无该常量），
    不是断言在查值。本用例喂一个**合法但不同**的枚举值（HIGH），且请求缺省是 LOW，
    所以「写死 LOW / 写死 issue.severity(MEDIUM)」这类换源都会在这里红。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    now = _utc(3, 0)
    audit = InMemoryAuditLogger()
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(),
        store=FakeStore(),
        audit=audit,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(request_id="req-s1", priority="P0", risk_level=RiskLevel.HIGH),
        gate,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(
            request_id="req-s2",
            dedupe_key="emg:qq:s2:g-1",
            priority="P2",
            risk_level=RiskLevel.CRITICAL,
        ),
        gate,
        now=now,
    )
    _push(
        RecordingQueue(),
        _request(
            request_id="req-s3",
            dedupe_key="bad",
            priority="P0",
            risk_level=RiskLevel.MEDIUM,
        ),
        gate,
        now=now,
        dedupe_family="daily",
    )
    assert [record.event for record in audit.list_records()] == [
        "outbound_gate_allow",
        "outbound_gate_defer",
        "outbound_gate_skip",
    ]
    assert [record.severity for record in audit.list_records()] == [
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
        RiskLevel.MEDIUM,
    ]


def test_severity_normalisation_and_blank_severity_is_never_urgent() -> None:
    """`_severity_of` 归一（strip + upper + 空值→""）与「空串白名单不穿窗」。

    取值归一在 GAP-5/GAP-9 里都是零锁：GAP-9 的注毒（删掉 `if str(value).strip()`
    过滤）不红 ⇒ `urgent_severities=[""]` 配上 priority 为空的请求，会被当成紧急
    **穿静默窗**——保守性反了（该顺延的反而深夜抢发）。本条把两件事一起钉住。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        _is_urgent,
        _severity_of,
    )

    assert _severity_of(_request(priority=" p2 ")) == "P2"
    assert _severity_of(_request(priority="P0")) == "P0"
    assert _severity_of(_request(priority="")) == ""
    # priority 的载体是 str（contracts 必填）：None 进不了契约，归一只服务空串/空白。
    with pytest.raises(ValidationError):
        _request(priority=None)

    assert _is_urgent(_request(priority="p1"), ["P0", "P1"]) is True
    assert _is_urgent(_request(priority="P2"), ["P0", "P1"]) is False
    assert _is_urgent(_request(priority="  "), ["P0", "P1"]) is False
    # 空串白名单 + 空 priority：过滤一删就被判紧急 ⇒ 必须 False（保守顺延方向）。
    assert _is_urgent(_request(priority=""), ["", " "]) is False
    assert _is_urgent(_request(priority=""), [""]) is False
    assert _is_urgent(_request(priority="P0"), []) is False


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
        # 原实例写的是 `digest_push:g-1:2026-09-14`——只有三段，实际拦它的是**段数**
        # 规则，命名空间规则对它零判别（LOCK-AUDIT G10 删前缀校验 59 全绿）。
        # 改挂真身键形（四段、各段非空），让「非 emg 命名空间」这条规则单独受审。
        ("digest_push:g-1:u-2:2026-09-14", "非 emg 命名空间（存量族键不得混入）"),
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


# ------------------------------------- T5b 键命名空间与段字符集（LOCK-FIX F-1 补锁）
# 原缺口（LOCK-AUDIT GAP-1）：闸侧谓词既不查段字符集，命名空间规则也**零覆盖**
# （G10 删掉 `emg` 前缀校验 ⇒ 59 条全绿）。真实后果不是漏报而是**重发**：队列
# `ON CONFLICT(dedupe_key) DO NOTHING`（queue.py:443-475）是幂等唯一执行点，脏键
# 与现役族键各存一行＝同一推送发两遍。下面三条把「命名空间 / 段字符集 / 现役合法
# 键仍放行」三面各自钉死，且每条都带「只有这一关可红」的前置断言。
_NAMESPACE_ONLY_KEYS: tuple[tuple[str, str], ...] = (
    ("daily_assist:morning:3865067623:2026-09-19", "日常助理按日键（四段真形）"),
    ("campus_fwd:1108838060:12345:2026-09-19", "校园转发键（四段真形）"),
    ("emergency:qq:item-1:g-1", "近亲前缀 `emergency` 不等同 `emg`（D-6 唯一前缀）"),
    ("emg_push:qq:item-1:g-1", "第二前缀形态：禁各推送族再造一套"),
)


@pytest.mark.parametrize(("bad_key", "why"), list(_NAMESPACE_ONLY_KEYS))
def test_namespace_only_violations_are_skipped(bad_key: str, why: str) -> None:
    """四段、各段非空、字符合规——唯一不合规的只有命名空间这一关。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
        dedupe_key_shape_ok,
    )

    # 防空转：段数与空段两条规则都必须放过它，才证明本用例考的是前缀规则本身。
    segments = bad_key.split(":")
    assert len(segments) == 4, why
    assert all(segment.strip() for segment in segments), why

    assert dedupe_key_shape_ok(bad_key) is False, why

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


@pytest.mark.parametrize(
    ("bad_key", "why"),
    [
        ("emg:qq:has space:g-1", "段内空白：配置串按逗号切开不 strip 的直达形态"),
        ("emg:  qq:item-1:g-1", "段前空白：`strip()` 判空拦不住（段非空）"),
        ("emg:qq:item-1:g-1 ", "尾段尾随空白：与干净键是两条队列行＝重发"),
        ("emg:qq:预警:g-1", "段字符集只认 [A-Za-z0-9_.-]：条目号必须先消毒"),
        ("emg:qq:item-1:private:3865067623", "目标未消毒带冒号：伪装成五段且日期段非法"),
        ("emg:qq:item-1:g-1:2026-9-14", "日期段未补零：与 B4 规格 §1.3-3 形态不符"),
        ("emg:qq:item-1:g-1:20260914", "日期段缺分隔符"),
    ],
)
def test_segment_charset_and_date_key_shape_are_enforced(bad_key: str, why: str) -> None:
    """段字符集与日期段形态：脏键过闸＝幂等失效，故闸侧必须逐段查字符。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
        dedupe_key_shape_ok,
    )

    # 防空转：这些键今天都「过」得了段数与空段两关，缺的只有逐段字符集这一关。
    assert len(bad_key.split(":")) in (4, 5), why
    assert all(segment.strip() for segment in bad_key.split(":")), why
    assert bad_key.split(":")[0] == "emg", why

    assert dedupe_key_shape_ok(bad_key) is False, why
    assert dedupe_key_shape_ok(bad_key, family="daily") is False, why

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
    assert queue.calls == []


def test_canonical_emg_keys_still_pass_after_charset_tightening() -> None:
    """收紧的另一侧：现役合法键（含 `.`/`_`/`-` 段）必须照旧放行，不许过拦。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    once_ok = (
        "emg:qq:item-1:g-1",
        "emg:qq:alarm-001:1108838060",
        "emg:telegram:gov_9.2:chat.123",  # `.`/`_`/`-` 都在段字符集内
    )
    for key in once_ok:
        assert dedupe_key_shape_ok(key) is True, key
        assert dedupe_key_shape_ok(key, family="daily") is False, key
    daily_ok = (
        "emg:qq:item-1:g-1:2026-09-14",
        "emg:telegram:gov_9.2:chat.123:2026-09-19",
    )
    for key in daily_ok:
        assert dedupe_key_shape_ok(key) is True, key
        assert dedupe_key_shape_ok(key, family="daily") is True, key


def test_dedupe_predicates_share_one_implementation() -> None:
    """F-1/F-4 同源锁：闸侧 `dedupe_key_shape_ok` 必须是紧急域谓词的**委托口**。

    刻意用结构锁而不是「取值互比」：两侧同源之后取值互比就是恒真子句（LOCK-AUDIT
    判例 C 类，本席不许再犯）。只有「谁 import 谁、谁调用谁、第二套正则在不在」
    能在有人重新分叉的那一刻变红。方向也钉死：域内核不得反向 import 闸
    （`test_emergency_info_core.py::test_kernel_never_imports_network_or_llm` 禁
    `transport` 令牌，反向即成 import 环）。
    """
    gate_path = REPO_ROOT / GATE_MODULE
    tree = ast.parse(gate_path.read_text(encoding="utf-8"))
    dedupe_module = (
        "plugins.bot_unified_runtime.domains.emergency_info.service.dedupe"
    )
    imported: dict[str, set[str]] = {}
    shape_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )
        elif isinstance(node, ast.FunctionDef) and node.name == "dedupe_key_shape_ok":
            shape_fn = node
    assert dedupe_module in imported, (
        f"闸侧不再引用紧急域的唯一键规范实现（闸实有 import：{sorted(imported)}）"
        "⇒ 键规范又变成两套，闸侧漏查的段字符集/日期段形态会在这里复活"
    )
    assert "is_emergency_dedupe_key" in imported[dedupe_module]
    # 2026-09-22 R-CENTRAL-b I-1：闸现在有**两条**委托边（紧急族 + 其余主动投递族）。
    # 只断言前者的话，把后者内联成一条宽松谓词（丢掉段字符集/首段等值/日期形态）锁照样
    # 全绿——注毒 POISON1 实证。两枚谓词都得在册且都被调用，缺一即分叉。
    assert "active_push_key_shape_ok" in imported[dedupe_module], (
        "非紧急族的键规范谓词不再从域侧引用＝闸侧长出第二套规则（C-1 修复被架空）"
    )
    assert shape_fn is not None, "闸侧键规范函数被搬走，须同步本锁与规格 §1.3-3"
    called = {
        call.func.id
        for call in ast.walk(shape_fn)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "is_emergency_dedupe_key" in called, (
        "`dedupe_key_shape_ok` 已不再委托域侧实现＝函数壳还在、规则已分叉"
    )
    assert "active_push_key_shape_ok" in called, (
        "`dedupe_key_shape_ok` 的非紧急分支不再委托域侧实现＝那条分支的规则已分叉"
    )
    gate_source = gate_path.read_text(encoding="utf-8")
    assert "re.compile" not in gate_source, (
        "闸侧自己写了正则＝造出第二套（第三套）键规范；段字符集与日期段形态的唯一"
        "出处是 `domains/emergency_info/service/dedupe.py`"
    )
    namespace_literals = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DEDUPE_NAMESPACE"
            for target in node.targets
        )
    ]
    assert namespace_literals and not any(
        isinstance(value, ast.Constant) for value in namespace_literals
    ), (
        "DEDUPE_NAMESPACE 又落成字面量：前缀必须引用域侧 EMERGENCY_DEDUPE_PREFIX，"
        "否则改一处漏一处（近亲前缀 `emg_push` 就是这么穿过去的）"
    )
    # 反向防环：域内核只准被引用，不准引用 transport 闸。
    dedupe_source = (
        PLUGIN_ROOT / "domains" / "emergency_info" / "service" / "dedupe.py"
    ).read_text(encoding="utf-8")
    assert "outbound_gate" not in dedupe_source.split('"""')[2], (
        "紧急域 `dedupe.py` 的**代码段**出现 outbound_gate＝方向倒转 + import 环风险"
        "（键规范归域侧，闸侧只做委托）"
    )


def test_whitespace_padded_dedupe_key_is_rejected() -> None:
    """整串带空白的键：核验口不替你洗，两侧同源后一律判不合规。

    旧态：域侧先 `strip()` 整串再判 ⇒ True，闸侧严格 ⇒ False——同一个键两侧结论
    相反。队列 `ON CONFLICT` 按整串相等做幂等 ⇒ 干净键与脏键各存一行＝重发。
    """
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        is_emergency_dedupe_key,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    padded = "  emg:qq:item-1:g-1  "
    assert all(segment.strip() for segment in padded.split(":"))  # 防空转
    assert dedupe_key_shape_ok(padded) is False
    assert is_emergency_dedupe_key(padded) is False
    # 要清洗就走构造函数：它逐段 strip 后拼键，产出的一定过同一个谓词。
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        build_emergency_dedupe_key,
    )

    clean = build_emergency_dedupe_key(" qq ", " item-1 ", " g-1 ")
    assert dedupe_key_shape_ok(clean) is True


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
    """T6：仍直调 `send_queue.submit` 的存量族清点（**现役 2 族**）。

    校园族已改道中央管线（`pipeline.handle_async`），从直调清单除名 ⇒ 下限 5→4。
    依据是**并行审计席的设计件** `docs/design/audit-20260920-unify-U17-campus-wire.md`
    （§0.2 现状坐标 / §0.3 取形态 A=合成目标会话消息交中央管线 / §0.4 门语义实测），
    **不是用户裁决**——改此门槛者须引该件路径与结构断言，不得引不存在的裁决编号。

    2026-09-22 口径变更（须连读，别只看本行）：B4-spec §1.5「存量族只登记不迁移」的
    立由=「避免波及**该波在飞会话**」（`docs/design/emergency-info-unify-summary-20260919.md:79`），
    紧急波收尾后该理由失效；统一波用户 mandate 明写「所有内容走中央调度层」
    ⇒ 群摘要 + 日常助理两族按裁定件
    `.superpowers/sdd/2026-09-21-unify-wave/decisions/WAVE42-active-push-central-exit.md`
    改道中央出口，本锁的直调下限随之 4→2，并**新增**一条正向锁：改过道的族不得退回裸 submit。
    提醒 / cookie 到期两族**也已**改道：它们"送达才销账"读的是内联投递的同步回执，
    闸的判定必须站在投递之前，故走 `_push_via_central_exit_now`（root 侧）而不是裸
    `submit_active_push`。本函数下半段的"零裸 submit"断言只有四族全改道才绿。
    回执落点细节见裁定件 §未裁项（A′ 案，2026-09-22 用户确认前不 commit）。
    """
    assert ROOT_INIT.is_file(), ROOT_INIT
    source = ROOT_INIT.read_text(encoding="utf-8")
    assert "submit_active_push" in source, (
        "根装配已把群摘要/日常助理两族接进中央出口；该行消失＝被退回裸 submit（第二出口复活）"
    )
    assert not _direct_submit_calls(ROOT_INIT), (
        "root 四条主动投递（提醒/cookie 到期/群摘要/日常助理）已全部改走中央出口"
        "（2026-09-22 Wave 4.2/4.3）；再出现裸 send_queue.submit=第二投递出口复活"
    )
    for anchor in INIT_DEDUPE_ANCHORS:
        assert anchor in source, f"存量族 dedupe 锚点 {anchor} 消失，需复核是否被顺手迁移"
    assert "bot.campus_forward" in source, (
        "campus 已按 U17 设计件收编中央管线（dedupe 由管线 _complete 公式承接），"
        "capability_id 必须仍在 root 分发段在位"
    )


def _under_directory(path: Path, roots: tuple[Path, ...]) -> bool:
    """文件是否落在 `roots` 这批**目录**之下——按目录段等值判定，不按字符串前缀。

    为什么不能用 `str(path).startswith(str(root))`（LOCK-AUDIT PROBE-2 实证）：那样
    `domains/transport_legacy`、`domains/transporter` 都被判进 `domains/transport`，
    「唯一入口只服务紧急域」这条边界同名实存。取 `domains/` 下第一段目录名等值比较，
    兄弟目录当场出局，域内任意深度照常算数。
    """
    try:
        relative = path.relative_to(PLUGIN_ROOT / "domains")
    except ValueError:
        return False
    directory_parts = relative.parts[:-1]  # 去掉文件名本身
    if not directory_parts:
        return False
    directory_names = {root.name for root in roots}
    return directory_parts[0] in directory_names


def _production_uses_of_central_entry() -> list[str]:
    """生产面**真的**用上 `submit_active_push` 的文件（import 该符号或调用它）。

    只按文本命中算的话，一句注释就能造假；这里走 AST：`ImportFrom` 里出现该符号，
    或存在 `submit_active_push(...)` 调用点。闸自身（定义处）排除。
    """
    gate_name = "outbound_gate.py"
    found: list[str] = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == gate_name:
            continue
        text = path.read_text(encoding="utf-8")
        if "submit_active_push" not in text:
            continue
        tree = ast.parse(text)
        imported = any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == "submit_active_push" for alias in node.names)
            for node in ast.walk(tree)
        )
        called = any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "submit_active_push")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "submit_active_push"
                )
            )
            for node in ast.walk(tree)
        )
        if imported or called:
            found.append(path.relative_to(PLUGIN_ROOT).as_posix())
    return found


def test_submit_active_push_production_importers_are_allowlisted() -> None:
    """T6：`submit_active_push` 的生产引用只允许出现在 transport 本体与紧急域。"""
    # 前缀必须是真身目录名 `emergency_info`：写成 `domains/emergency` 会同时放行任何
    # `domains/emergency*` 兄弟目录（过松）。另注：本锁在零消费者期是"空真"通过，
    # 接线落地后须由接线席补一条正向断言（生产 import 数 ≥ 1）才算闭合——那条正向
    # 断言在本文件 `test_submit_active_push_has_at_least_one_production_caller`
    # （xfail strict=True），不是等接线席想起来。
    #
    # 形制纪律（两侧对齐锚，别随手改）：`test_emergency_info_core.py::
    # _gate_t6_allowed_roots` 用 AST 从**本函数体内**抓第一个名字含 `allowed` 的赋值，
    # 按字符串常量顺序拼回 `PLUGIN_ROOT.joinpath(*segments)`。所以：①本赋值必须留在
    # 函数体内（挪去模块级＝那侧提取失败当场红）；②必须写全
    # `PLUGIN_ROOT / "domains" / "<目录名>"` 三段字面量（写成裸目录名会让那侧的
    # `covered` 判定失效）。原形是 `((...,), (...,))` 嵌套元组——那是个真缺陷：
    # `str(root)` 得到的是 "(WindowsPath('...'),)" 这种 repr，任何真实路径都
    # 不可能 startswith 它 ⇒ 白名单其实**谁都拦在外面**，接线当天紧急域自己的合法
    # import 会被误判越界（假红），而今天它只是叠加在空集上没人发现。已摊平。
    allowed_roots = (
        PLUGIN_ROOT / "domains" / "transport",
        PLUGIN_ROOT / "domains" / "emergency_info",
    )
    # Wave 4.2（2026-09-22）：根装配把群摘要/日常助理两族接进中央出口 ⇒ root 成为合法
    # 引用方。逐文件精确放行（不放开成"PLUGIN_ROOT 全树"），新增引用方仍当场出局。
    # 与本函数上方 `allowed_roots` 的先后顺序不得调换：`test_emergency_info_core.py`
    # 的两侧对齐锁按"第一个含 allowed 的赋值"提取根目录白名单。
    allowed_files = {PLUGIN_ROOT / "__init__.py"}
    offenders: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "outbound_gate.py" in path.name:
            continue
        if "submit_active_push" not in path.read_text(encoding="utf-8"):
            continue
        if path in allowed_files:
            continue
        if not _under_directory(path, allowed_roots):
            offenders.append(path.relative_to(PLUGIN_ROOT).as_posix())
    assert offenders == [], (
        f"中央闸的唯一入口只允许紧急域（与 transport 本体）引用，越界：{offenders}"
    )
    # 收紧只做一半的反证（LOCK-AUDIT PROBE-2 实测：`domains/transport_legacy`、
    # `domains/transporter` 用 startswith 判 **allowed=True**）：兄弟目录必须出局，
    # 同时白名单目录本身必须仍在内（只有负样本时本锁会因「全判 False」假绿）。
    for sibling in (
        "transport_legacy/old.py",
        "transporter/evil.py",
        "emergency_other/x.py",
        "emergencyinfo/x.py",
        # WIRE-A2（施工图 §7.4-3 负样本）：目录名**以真身名开头**的兄弟目录。
        # 这是 `startswith("domains/emergency_info")` 那种"看起来已经收紧"的写法
        # 唯一还会放行的形态——今天 `emergency_info_v2` 若被谁建出来并 import 闸，
        # 按字符串前缀判定它无声通过，而按目录段等值判定它当场出局。
        "emergency_information/x.py",
        "emergency_info_v2/x.py",
    ):
        path = PLUGIN_ROOT / "domains" / Path(sibling)
        assert not _under_directory(path, allowed_roots), (
            f"兄弟目录 {sibling} 被判进白名单＝`transport*` 前缀仍松"
        )
    # 不在任何域目录之下的散文件同样出局（`domains/stray.py`：域段为空）。
    assert not _under_directory(PLUGIN_ROOT / "domains" / "stray.py", allowed_roots)
    for insider in (
        "transport/sender/outbound_gate.py",
        "transport/sender/sub/queue.py",
        "emergency_info/service/dedupe.py",
    ):
        assert _under_directory(PLUGIN_ROOT / "domains" / insider, allowed_roots), insider


# ------------------------------------------------------------------ T6b 白名单活性
# 转正记录（LOCK-FIX F-2 的原始转正条件，标记删掉、文字留在这里别丢）：
#   转正条件＝生产面出现 ≥1 个 `submit_active_push` 的真实使用（AST 判 import 该符号
#   或直接调用它）。LOCK-AUDIT PROBE-3 曾实证全 plugins/ 树含该符号的文件只有闸自身
#   ⇒ 当时的白名单锁是空集上的恒真。2026-09-20 WIRE-A2 落 `domains/emergency_info/
#   service/push.py`（4-面11 规定的唯一主动投递触点）后条件成立，按纪律**删标记转正**，
#   未改成 `assert True`、未 skip。
#   诚实边界：本条只证明「域内触点确实存在且只有它引用闸」；它**不**证明
#   「已有一条预警真的投出去了」——那要等根 `__init__.py` 装配 + 用户提权重启。
def test_submit_active_push_has_at_least_one_production_caller() -> None:
    """正向断言：唯一入口不是「没人用所以没人越界」的空中楼阁。

    与 `test_submit_active_push_production_importers_are_allowlisted` 构成双侧：
    那条钉「越界者为零」（白名单侧），本条钉「引用者不为零」（活性侧）。两条同时
    为真，才叫「生产投递确实只从这一个口子走」。
    """
    users = _production_uses_of_central_entry()
    assert len(users) >= 1, (
        f"生产面对 `submit_active_push` 的真实使用数={len(users)}（{users}）："
        "白名单仍是空集恒真，中央闸的『唯一入口』尚未被任何生产件走通"
    )
    # 活性一旦成立，越界面必须同时为零（本文件另一条锁的口径），此处只报不断言：
    # 判定归 allowlisted 那条，避免同一条事实两把尺子。


def test_allowlist_helper_itself_is_not_vacuous() -> None:
    """防「白名单收紧把合法侧也收死」：判定函数两侧的取值都必须真出现过。

    这条不依赖接线（不像 T6b 那样恒 xfail），现在就能跑：目录段匹配既要把兄弟目录
    判出去，也要把 `domains/transport/sender/**` 与 `domains/emergency_info/**`
    判进来。任何一侧失灵（例如 `relative_to` 抛错被吞成 False）都会在这里红，
    而不是等到接线当天用假红去撞。
    """
    roots = (
        PLUGIN_ROOT / "domains" / "transport",
        PLUGIN_ROOT / "domains" / "emergency_info",
    )
    inside = [
        "transport/sender/outbound_gate.py",
        "transport/sender/deep/nested.py",
        "emergency_info/service/dedupe.py",
        "emergency_info/sources/nmc_alarm.py",
        # WIRE-A2：域内唯一投递触点必须落在白名单**内侧**（接线当天若判外，
        # T6 会以「越界者」的形式假红，这条先行把它钉成实比）。
        "emergency_info/service/push.py",
    ]
    outside = [
        "transport_legacy/old.py",
        "transporter/evil.py",
        "chat_reply/capabilities/echo.py",
        "assistant/campus/campus.py",
        # 同 WIRE-A2 负样本口径：以真身名开头的兄弟目录不得放行。
        "emergency_info_v2/service/push.py",
    ]
    assert all(_under_directory(PLUGIN_ROOT / "domains" / rel, roots) for rel in inside)
    assert not any(_under_directory(PLUGIN_ROOT / "domains" / rel, roots) for rel in outside)
    # domains 之外的任何文件一律出局（根 `__init__.py` 是未来最容易长出旁路的地方）。
    assert not _under_directory(PLUGIN_ROOT / "__init__.py", roots)


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


def test_unreadable_gate_settings_is_announced_not_swallowed() -> None:
    """I-3 根修：读不到设置=闸按缺省**关闭**，这件事必须冒到告警口，且只冒一次。

    咬过的病型（台账 #47 同型）：设置面读起来仍是 true，实际行为恒等于关闭，而旧实现
    只 `_logger.exception`——日志会轮转，没人看日志的早晨闸就是"配了等于没配"。
    同时不许逐条播报：求值发生在每次判定之前，噪音会把告警通道本身打爆。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    state = {"broken": True}
    issues: list[OperationalIssue] = []

    def _flaky() -> Any:
        if state["broken"]:
            raise RuntimeError("settings store down")
        return OutboundGateSettings(enabled=True)

    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=_flaky, quiet=_quiet(enabled=False), store=FakeStore(), now=now,
        sink=issues.append,
    )

    for index in range(3):
        outcome = _push(
            queue, _request(request_id=f"req-{index}"), gate, now=now
        )
        assert outcome.verdict.action == "allow"
    kinds = [issue.kind for issue in issues]
    assert kinds == ["outbound_gate_settings_unreadable"], (
        f"读不到设置要么没报、要么报重了：{kinds}"
    )

    # 恢复一次即清账：再坏一次必须重新报（否则"报了=永远报了"）。
    state["broken"] = False
    assert gate.settings.enabled is True
    state["broken"] = True
    _push(queue, _request(request_id="req-again"), gate, now=now)
    assert [issue.kind for issue in issues] == [
        "outbound_gate_settings_unreadable",
        "outbound_gate_settings_unreadable",
    ], "恢复后再次失效没重新报＝告警一次性静音"


def test_wrong_typed_gate_settings_announces_like_a_failure() -> None:
    """求值成功但**类型不对**（返回 dict/None）＝同样按缺省关闭，同样必须报。

    这条不是凑数：设置源是 `lambda: build_outbound_gate_settings(config)`，装配期接错
    返回值、或未来加一层包装把对象吃掉，都会走到 `else` 分支——旧实现里这里是纯静默。
    """
    issues: list[OperationalIssue] = []
    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=lambda: {"enabled": True},  # 故意给错类型
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
        sink=issues.append,
    )

    outcome = _push(queue, _request(), gate, now=now)

    assert outcome.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]
    assert [issue.kind for issue in issues] == ["outbound_gate_settings_unreadable"]


# ----------------------------------------------------- T9 多族命名空间（Wave 4.2/4.3）
#: 现役四族主动投递的**真实键形 + 该族申报的命名空间 + 重投族**。键形逐条抄自根
#: `__init__.py`（`:2973` 提醒 / `:3096` cookie 到期 / `:3269` 群摘要 / `:3427` 日常助理），
#: 改键形必须同步本表——本表的目的就是让「闸开=这四族全被判 skip」这一类错当场可见
#: （R-CENTRAL C-1：中央出口接线后键规范仍只认 `emg` 前缀，四族全灭而关态测试全绿）。
ACTIVE_PUSH_KEY_FORMS: tuple[tuple[str, str, str], ...] = (
    ("reminder:7c1f2a9b", "reminder", "once"),
    ("cookie-expiry:3865067623:2026-09-14", "cookie-expiry", "daily"),
    ("digest_push:631785829:2026-09-14", "digest_push", "daily"),
    ("daily_assist:inbox:3865067623:2026-09-14", "daily_assist", "daily"),
)


@pytest.mark.parametrize(("key", "namespace", "family"), ACTIVE_PUSH_KEY_FORMS)
def test_enabled_gate_admits_each_active_push_namespace(
    key: str, namespace: str, family: str
) -> None:
    """开态活性：四族各自申报的命名空间必须真的过闸落队列（不是只「在册」）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
    )
    outcome = _push(
        queue,
        _request(dedupe_key=key),
        gate,
        now=now,
        dedupe_family=family,
        dedupe_namespace=namespace,
    )

    assert outcome.verdict.action == "allow", (
        f"{namespace} 族被自己的中央出口拒收：reason={outcome.verdict.reason}"
    )
    assert queue.calls == [("req-emg-1", {})]


@pytest.mark.parametrize(
    ("key", "namespace"),
    [
        # 近亲前缀：多一个字符也算不同族（紧急域的 `emg_push` 判例推广到全族）。
        ("reminderx:7c1f2a9b", "reminder"),
        # 串族：拿别人的键冒充自己的命名空间。
        ("emg:qq:item-1:g-1", "reminder"),
        # 无前缀（整串一段）＝无从判定归属，保守拒收。
        ("7c1f2a9b", "reminder"),
    ],
)
def test_namespace_must_equal_first_segment(key: str, namespace: str) -> None:
    """命名空间=键首段**等值**：不等即 skip，绝不让两族共用一个幂等桶。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
    )
    outcome = _push(
        queue, _request(dedupe_key=key), gate, now=now, dedupe_namespace=namespace
    )

    assert outcome.verdict.action == "skip"
    assert outcome.verdict.reason == "dedupe_key_shape"
    assert queue.calls == []


@pytest.mark.parametrize(
    ("key", "namespace", "family"),
    [
        ("digest_push:631 785:2026-09-14", "digest_push", "daily"),  # 段内空白
        ("daily_assist:inbox:386:2026-09:14", "daily_assist", "daily"),  # 段内冒号
        ("cookie-expiry:3865067623", "cookie-expiry", "daily"),  # 按日族缺日期段
        ("reminder:7c1f2a9b:20261345", "reminder", "daily"),  # 日期段形态假（无连字符）
        # 注：**形态**核验不查历法真值——`2026-13-45` 与紧急域一样判过。口径同源优先，
        # 别在这里"顺手加严"造成两侧分叉；现役日期一律来自 `date().isoformat()`，恒为真值。
    ],
)
def test_non_emergency_shape_rules_still_bit(
    key: str, namespace: str, family: str
) -> None:
    """放宽的只有「前缀必须是 emg」，段字符集与日期段形态**一条没松**（脏键=重发）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
    )
    outcome = _push(
        queue,
        _request(dedupe_key=key),
        gate,
        now=now,
        dedupe_family=family,
        dedupe_namespace=namespace,
    )

    assert outcome.verdict.action == "skip"
    assert outcome.verdict.reason == "dedupe_key_shape"


def test_default_namespace_keeps_emergency_rules_byte_identical() -> None:
    """不传 `dedupe_namespace` ⇒ 完全等于改道前的紧急域口径（四段/五段 + emg 等值）。

    这条是「本波没动别人的闸」的证据：紧急域全部现役用例与闸侧既有 T1–T8 都按缺省参
    调用，只要缺省分支的行为有任何一点漂移，这里就红。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    queue = RecordingQueue()
    now = _utc(12, 0)
    gate = _gate(
        settings=OutboundGateSettings(enabled=True),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=now,
    )

    # 紧急域：段数不足 / 近亲前缀 / 旁族键混入紧急通道 ⇒ 三条全 skip（改道前后同判）。
    for key in ("emg:qq:only-three", "emg_push:qq:item:g-1", "digest_push:63:2026-09-14"):
        outcome = _push(queue, _request(dedupe_key=key), gate, now=now)
        assert outcome.verdict.action == "skip", key
        assert outcome.verdict.reason == "dedupe_key_shape", key

    ok = _push(queue, _request(dedupe_key="emg:qq:item-1:g-1"), gate, now=now)
    assert ok.verdict.action == "allow"
    assert queue.calls == [("req-emg-1", {})]


# ------------------------------------------- T10 申报与建键同源锁（R-CENTRAL-b I-2）
_CENTRAL_PUSH_CALLS = frozenset({"submit_active_push", "_push_via_central_exit_now"})


def _key_first_segment(node: ast.expr) -> str | None:
    """`dedupe_key=` 实参的**首段字面量**（`f"reminder:{x}"` → `reminder`）。

    只认 f-string/常量开头的字面段：`dedupe_key=dedupe_key` 那种透传（值由形参带来，
    首段在别的函数里拼）返回 None，由那个真正建键的函数负责，别在这里猜。
    """
    if isinstance(node, ast.JoinedStr):
        head = node.values[0] if node.values else None
    elif isinstance(node, ast.Constant):
        head = node
    else:
        return None
    if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
        return None
    segment = head.value.split(":")[0].strip()
    return segment or None


def _central_push_stats(fn: ast.AST) -> tuple[set[str], set[str]]:
    """该函数**自身**（不下钻内层函数）的 (申报的命名空间, 建出的键首段)。"""
    declared: set[str] = set()
    built: set[str] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue  # 内层函数由它自己那一份统计负责，防重复计
        if isinstance(node, ast.Call):
            callee = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            for keyword in node.keywords:
                if callee in _CENTRAL_PUSH_CALLS and keyword.arg == "dedupe_namespace":
                    value = keyword.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        declared.add(value.value)
                if keyword.arg == "dedupe_key":
                    segment = _key_first_segment(keyword.value)
                    if segment:
                        built.add(segment)
        stack.extend(ast.iter_child_nodes(node))
    return declared, built


def test_root_declares_exactly_the_namespaces_it_builds() -> None:
    """每个建 `dedupe_key` 并走中央出口的函数，必须**就地**申报同名命名空间。

    为什么只有一张手抄表不够（R-CENTRAL-b Important-2）：`ACTIVE_PUSH_KEY_FORMS` 是
    测试侧抄本，改 root 不改表它不会红；而 T6 的 allowlist 放行整个 `__init__.py`，
    所以「新增一个直调点漏传 `dedupe_namespace`」＝回落 `emg` 缺省＝开闸态该族静默丢
    消息，与 C-1 同型且无门可拦。本锁按**函数**做双向对账：

    - 建了键没申报（漏报）→ 红；
    - 申报了没建键 / 报了别的族的段（错报、串族）→ 红；
    - 两集合等值 → 绿。

    段数下限 `_scanned` 是这条锁自己的活性地板：若哪天 root 改成键在别处拼、申报在
    另处传，本锁会静默扫不到东西而恒绿——那种「存在性糊过活性判据」不许发生。
    """
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    scanned = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        declared, built = _central_push_stats(node)
        if not declared and not built:
            continue
        scanned += 1
        if declared != built:
            mismatches.append(
                f"{node.name}: 建键首段={sorted(built)} 中央出口申报={sorted(declared)}"
            )

    assert not mismatches, (
        "主动投递族的命名空间申报与真实键形分叉 ⇒ 开闸态该族会被键规范整族 skip："
        + "；".join(mismatches)
    )
    assert scanned >= 4, (
        f"本锁只扫到 {scanned} 个『建键或申报』的函数（地板 4=现役四族各一处）"
        "⇒ 要么改道结构变了要么键改在别处拼，本锁已失明，须同步改写而不是降地板"
    )


def _root_mismatch_names(source: str) -> set[str]:
    """对给定 root 源码跑一遍上面的对账，返回被判分叉的函数名（注毒自证用）。"""
    result: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        declared, built = _central_push_stats(node)
        if (declared or built) and declared != built:
            result.add(node.name)
    return result


def test_namespace_declaration_lock_has_teeth() -> None:
    """注毒：改错一个申报值 / 删掉一个申报，本锁必须当场多出一个失配函数。

    没这一条，上面那把锁可能只是"永远等值的两集合"（判据空转）。两发毒分别代表
    C-1 同型的两种复发：报错了族、和干脆漏报（回落 `emg` 缺省）。
    刻意按「基线失配集 → 注毒后失配集」的**差集**判定而不是点名某个函数名：函数名会随
    重构漂移，点名函数名的自证本身就是一种手写坐标（本波已被过期行号咬过）。
    """
    source = ROOT_INIT.read_text(encoding="utf-8")
    clean = _root_mismatch_names(source)
    assert clean == set(), f"基线本就不干净：{sorted(clean)}"

    wrong = source.replace('dedupe_namespace="reminder"', 'dedupe_namespace="reminderx"')
    assert wrong != source, "注毒点消失（提醒族申报被改写或删掉），本锁的自证前提不成立"
    assert _root_mismatch_names(wrong) - clean, "报错命名空间没被抓＝锁无牙"

    dropped = source.replace(',\n            dedupe_namespace="reminder"', "", 1)
    assert dropped != source, "注毒点消失（提醒族调用参数形态变了），须同步本自证"
    assert _root_mismatch_names(dropped) - clean, "漏报命名空间没被抓＝锁无牙"
