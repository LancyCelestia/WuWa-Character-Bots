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

# ---- 中央出口「被谁引用」的单一判据（S274 立，两侧对齐锚见 `central_entry_executable_hits`）----
CENTRAL_ENTRY = "submit_active_push"
#: 唯一出口的**定义处**（精确路径，不是名字子串——旧写法 `"outbound_gate.py" in path.name`
#: 会让任何文件名含这串的生产件（`evil_outbound_gate.py`、`outbound_gate_v2.py`）整件免检，
#: 那是本锁自带的一条自我豁免通道。现算全仓该名字只命中这一个文件，收紧为零行为变化。
GATE_FILE = PLUGIN_ROOT / "domains" / "transport" / "sender" / "outbound_gate.py"

#: 「只在名字层面提到中央出口、并没有伸手去够它」的生产件**点名册**（S274 立）。
#: 立由：`submit_active_push` 这个名字有两种完全不同的出现——①**可执行引用**（import／调用／
#: 别名／字符串派发，真能经或绕过唯一出口）；②**声明性提及**（docstring、注释、形↔缝投影表里
#: 的字符串值）。把②当①判＝把名册当成旁路；把①当②放＝把旁路写成名册。本册只豁免②，
#: 且豁免面是**显式闭集**：新长出一枚声明性提及当场红（要么改道、要么点名进册并写明理由），
#: 册内件一旦长出可执行引用立刻落回越界面（反查腿在 T6 尾段，不只在这段散文里）。
DECLARATIVE_NAMEPLATE: frozenset[str] = frozenset(
    {
        # 形↔缝单源投影表 `ARM_FORM_SEAMS` 的两枚**值位**（`active_push`/`voice_ack` →
        # "submit_active_push"，字符串常量，不是调用）＋ 该表注释与字段 docstring 各一处。
        # 它声明"这两形经由哪条中央汇缝"，逐臂 `seam_host` 由它投影；等值另由
        # `tests/test_capability_manifest_gate.py` 腿㉓双向钉到入口活性件（在册无执法＝红）。
        "domains/core/capability_manifest.py",
        # 第 17/18 项反攻击波（2026-09-26，十八项收尾波）两枚**纯散文**提及，逐枚现算核过：
        # ① `attack_surface.py:416` —— 一处人话清单字符串，逐一点名"路径域守卫 + 出站闸 +
        #    submit_active_push 唯一出口 + dedupe 键段规范"四把咽喉，用来解释某面攻击为什么
        #    打不穿；② `policy.py:120` —— docstring 里"危险动作须出示守卫结论"的三枚出口清单
        #    （``check_sendable`` / ``submit_active_push`` / ``check_download_url``）。
        # 两枚都不 import、不调用、不做字符串派发（`central_entry_executable_hits` 各判 0），
        # 属"被名字提到"而非"被伸手够到"。入册理由：本波不打算让安全域去够唯一出口——
        # 安全域只判定放不放行，投递永远归出站闸与根装配，所以这两枚提及今后也必须停在散文层；
        # 若谁把它们改成真引用，上面的 `offenders` 腿当场红（在册 ≠ 可以够它）。
        "domains/core/safety_exec/attack_surface.py",
        "domains/core/safety_exec/policy.py",
    }
)


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
    """假队列：原样记录每次 submit 的调用形态（裸调用 vs 带 deliver_after）与**落库键**。

    生产语义复刻：同一 dedupe_key 第二次返回 SKIPPED 回执（幂等账在队列侧）。

    `keys` 记录的是**抵达队列那一行**的 `dedupe_key`，不是调用方交来的那一枚——中央出口
    会在过闸之前把键规范一次（`submit_active_push` 调 `wash_active_push_key`），本席的
    三条不变量（过形 / 同身份收敛 / 不同身份不撞段）全部只能按队列侧真键来判，
    拿调用方的脏串判＝判的是根本没发出去的东西。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.keys: list[str] = []
        self._seen: set[str] = set()

    def submit(self, send_request: SendRequest, **kwargs: Any) -> DeliveryReceipt:
        self.calls.append((send_request.request_id, dict(kwargs)))
        self.keys.append(send_request.dedupe_key)
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


# ------------------------------------------------ 出口洗段跟随件（S184，2026-09-24）
# 新现实：`submit_active_push` 在 `gate.decide` **之前**把 `send_request.dedupe_key`
# 交给 `domains/emergency_info/service/dedupe.py:wash_active_push_key` 规范一次，真被
# 改写就留一行 WARNING。于是本文件的判据从「脏键 ⇒ 闸 skip」改成三条真不变量：
#   ① 抵达队列那一行的键必过形（⇒ 结构上不存在「因键形而生的静默 skip」）；
#   ② 同一身份的多种脏形在出口收敛成**逐字相同**的一条键（重发防护比 skip 更强）；
#   ③ 不同身份绝不撞段（退化输入走摘要兜底，不塌成同一段）。
# 判据是宪法、洗的是出口：读侧谓词（`dedupe_key_shape_ok` / `is_legal_segment`）对**原始
# 串**的负样本断言一条不动，改的只是「过完出口之后会发生什么」。

def _digest_segment(text: str) -> str:
    """测试侧独立复算「洗完没有字母数字」时的摘要兜底段。

    刻意不 import 被测实现来算期望值（LOCK-AUDIT 纪律：同源自比＝判据空转）。这里按
    `dedupe.py:active_push_key_segment` 头注**写明**的规则（blake2b、digest_size=8、前缀
    `h`）用标准库另算一遍——与本文件 `_expected_subject_hash` 同一个手法。兜底规则一换，
    这里当场红，逼规格与判据一起跟随。
    """
    return "h" + hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


#: 段合法字符集（与 `dedupe.py:_SEGMENT_RE` 的 `[A-Za-z0-9_.\-]` 同口径），供下方
#: 独立复算用；测试侧另立一份是**故意的**——被测件规则漂移时这里当场红（`_digest_segment`
#: 同一哲学：不复用被测实现算期望值，否则同源自比＝判据空转）。
_LEGAL_SEGMENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)
_KEY_SEGMENT_MAX = 120


def _rescued_segment(text: str) -> str:
    """洗完仍含字母数字时的段：`washed + "_h" + digest`（S192 跟随洗段近似单射）。

    按 `dedupe.py:active_push_key_segment` 头注写明的规则用标准库**独立复算**，不 import
    被测实现：后缀 `_h` + blake2b(digest_size=8) 的 16 hex（共 18 字符），非法字符换成 `_`，
    截断预算 `120 - len(suffix)`。任一规则（摘要/前缀/预算）改动都会让这里与真身分叉 → 红。
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
    suffix = "_h" + digest
    washed = "".join(
        char if char in _LEGAL_SEGMENT_CHARS else "_" for char in text
    )[: _KEY_SEGMENT_MAX - len(suffix)]
    return washed + suffix


def _naive_wash_without_digest(value: object) -> str:
    """注毒体①：把「真身摘要后缀 + 退化兜底摘要」整个抹掉的塌段洗段（回到修前形态）。

    只 `strip → 判合法 → 非法换 `_` → 截 120`，无 `_h<digest>` 后缀、无 `h<digest>` 兜底 ⇒
    `11 08838060` 与 `11_08838060`、`中文群` 与 `：：：`、121/122 位长 id 全部塌成同段。
    只在内存 monkeypatch 里用，绝不落盘改 `dedupe.py`。
    """
    text = str(value or "").strip()
    if all(char in _LEGAL_SEGMENT_CHARS for char in text) and 1 <= len(text) <= _KEY_SEGMENT_MAX:
        return text
    return "".join(
        char if char in _LEGAL_SEGMENT_CHARS else "_" for char in text
    )[:_KEY_SEGMENT_MAX]


def _open_gate(now: datetime | None = None) -> Any:
    """开闸 + 静默关 + 双窗不限流：让「键形」成为唯一变量（0=该窗不生效，见上）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    fixed = now or _utc(12, 0)
    return _gate(
        settings=OutboundGateSettings(
            enabled=True, max_per_target_per_minute=0, max_per_target_per_hour=0
        ),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=fixed,
    )


def _exit_key_of(queue: RecordingQueue, index: int = 0) -> str:
    """取第 `index` 次**抵达队列**那一行的 dedupe_key（出口处理之后的真键）。"""
    assert len(queue.keys) > index, f"队列只收到 {len(queue.keys)} 行，取不到第 {index} 行"
    return queue.keys[index]


def _segments_all_legal(key: str) -> bool:
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        is_legal_segment,
    )

    return all(is_legal_segment(segment) for segment in key.split(":"))


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


#: 脏键在「唯一出口先规范一次」之后的两种归类。判据＝洗段口的**能力边界**，不是
#: 「哪种结论让我省事」：
#:   "rescued" 段级脏（空段 / 段内段前段尾空白 / 非 ASCII / 超 120 长）⇒ 出口洗得动
#:             ⇒ 必须 allow，且落库键逐字等于按规则手算的那一枚；
#:   "skip"    结构级脏（命名空间不等值 / 段数越界 / 日期段形态）⇒ 洗段修不动
#:             ⇒ 必须**响亮** skip（回执带机读原因），绝不静默。
#: 两归类必须同时存在，由 `test_malformed_key_classes_are_both_populated` 钉死，
#: 否则整张表会悄悄退化成「只测一种结论」。
_MALFORMED_KEY_CASES: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "digest_push:g-1:u-2:2026-09-14",
        "skip",
        # 原实例写的是 `digest_push:g-1:2026-09-14`——只有三段，实际拦它的是**段数**
        # 规则，命名空间规则对它零判别（LOCK-AUDIT G10 删前缀校验 59 全绿）。
        # 改挂真身键形（四段、各段非空），让「非 emg 命名空间」这条规则单独受审。
        "非 emg 命名空间（存量族键不得混入）",
        None,
    ),
    ("emg:qq::target", "rescued", "空段（出口洗成摘要兜底段，不再整条判死）",
     f"emg:qq:{_digest_segment('')}:target"),
    ("emg:qq:only-three", "skip", "段数不足（洗段变不出一个段）", None),
    ("emg:qq:a:b:c:d", "skip", "段数超限（洗段吃不掉一个段）", None),
    ("emgqqabcd", "skip", "无分隔（首段不等值于 emg）", None),
)


@pytest.mark.parametrize(
    ("bad_key", "expect", "why", "canonical"), list(_MALFORMED_KEY_CASES)
)
def test_malformed_dedupe_keys_are_skipped(
    bad_key: str, expect: str, why: str, canonical: str | None
) -> None:
    """段级脏由出口救回、结构级脏必须响亮拒——两半都是「不静默」，只是方向不同。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    queue = RecordingQueue()
    outcome = _push(queue, _request(dedupe_key=bad_key), _open_gate(), now=_utc(12, 0))

    if expect == "skip":
        assert outcome.verdict.action == "skip", why
        assert outcome.verdict.reason == "dedupe_key_shape"
        assert queue.calls == []  # 绝不触队列
        # 响亮而非静默：被拒的那一发自己带机读原因（skip 回执由闸自造，见 T5 那一条）。
        assert outcome.receipt is not None
        assert outcome.receipt.state is ReceiptState.SKIPPED
        assert outcome.receipt.public_message == "dedupe_key_shape"
        return

    assert outcome.verdict.action == "allow", f"{why}：出口该救回却被判死"
    assert queue.calls == [("req-emg-1", {})]
    landed = _exit_key_of(queue)
    assert landed == canonical, f"{why}：落库键与按规则手算的规范形不符"
    # ① 的正半：抵达队列那一枚键**过形**（用读侧宪法谓词判，不用出口自己判自己）。
    assert dedupe_key_shape_ok(landed) is True, f"{why}：落库键仍不过形：{landed!r}"
    assert _segments_all_legal(landed), f"{why}：落库键含非法段：{landed!r}"
    # 出口洗过＝必须可见（不许变成「消息发了但没人知道键被改过」）。
    assert landed != bad_key, f"{why}：本该改写却逐字节未变，本行判据成空跑"


def test_malformed_key_classes_are_both_populated() -> None:
    """反空跑：`_MALFORMED_KEY_CASES` 两归类都得有人（只剩一种＝表被掏空，判据失明）。"""
    classes = {case[1] for case in _MALFORMED_KEY_CASES}
    assert classes == {"skip", "rescued"}, classes
    assert sum(1 for case in _MALFORMED_KEY_CASES if case[1] == "rescued") >= 1
    assert sum(1 for case in _MALFORMED_KEY_CASES if case[1] == "skip") >= 3


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


#: 段字符集 / 日期段形态用例（S184 起带归类列，理由同 `_MALFORMED_KEY_CASES` 头注）。
#: `canonical` 一律是**按规则手算**的字面量，不是拿出口算出来的自比对值。
_SEGMENT_SHAPE_CASES: tuple[tuple[str, str, str | None, str], ...] = (
    # 段内空白洗完仍含字母数字 ⇒ 走「真被洗过」分支带摘要后缀（洗段近似单射，S184 §3-①）；
    # 期望值由本文件 `_rescued_segment` 独立复算，与 `_digest_segment` 同法，不 import 出口。
    ("emg:qq:has space:g-1", "rescued", f"emg:qq:{_rescued_segment('has space')}:g-1",
     "段内空白：配置串按逗号切开不 strip 的直达形态（洗完带 `_h<摘要>` 后缀防与裸 `has_space` 撞段）"),
    ("emg:  qq:item-1:g-1", "rescued", "emg:qq:item-1:g-1",
     "段前空白：`strip()` 判空拦不住（段非空）"),
    ("emg:qq:item-1:g-1 ", "rescued", "emg:qq:item-1:g-1",
     "尾段尾随空白：与干净键收敛成同一条（旧判据「两条队列行＝重发」由出口消除）"),
    ("emg:qq:预警:g-1", "rescued", f"emg:qq:{_digest_segment('预警')}:g-1",
     "段字符集只认 [A-Za-z0-9_.-]：非 ASCII 条目号退化成摘要段"),
    ("emg:qq:item-1:private:3865067623", "skip", None,
     "目标未消毒带冒号：伪装成五段且日期段非法（洗段修不了段数）"),
    ("emg:qq:item-1:g-1:2026-9-14", "skip", None, "日期段未补零：与 B4 规格 §1.3-3 形态不符"),
    ("emg:qq:item-1:g-1:20260914", "skip", None, "日期段缺分隔符"),
)


@pytest.mark.parametrize(
    ("bad_key", "expect", "canonical", "why"), list(_SEGMENT_SHAPE_CASES)
)
def test_segment_charset_and_date_key_shape_are_enforced(
    bad_key: str, expect: str, canonical: str | None, why: str
) -> None:
    """段字符集与日期段形态：读侧谓词照旧逐段查（判据是宪法），出口另救段级脏。

    分工写死在这一条里：**判据是宪法、洗的是出口**。
    - 读侧 `dedupe_key_shape_ok(原始脏串)` 永远 False——闸的形门一条没松，本文件下方
      `test_dedupe_predicates_share_one_implementation` 继续钉死「闸侧不许长第二套规则」；
    - 出口 `submit_active_push` 先把段级脏洗成规范形再送闸 ⇒ 落库键过形、且与干净形同键；
    - 结构级脏（段数 / 日期形态）洗不动 ⇒ 仍旧响亮 skip，绝不变静默。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    # 防空转：这些键今天都「过」得了段数与空段两关，缺的只有逐段字符集这一关。
    assert len(bad_key.split(":")) in (4, 5), why
    assert all(segment.strip() for segment in bad_key.split(":")), why
    assert bad_key.split(":")[0] == "emg", why

    # 读侧（原始串）：一格都不许松。
    assert dedupe_key_shape_ok(bad_key) is False, why
    assert dedupe_key_shape_ok(bad_key, family="daily") is False, why

    queue = RecordingQueue()
    outcome = _push(queue, _request(dedupe_key=bad_key), _open_gate(), now=_utc(12, 0))

    if expect == "skip":
        assert outcome.verdict.action == "skip", why
        assert outcome.verdict.reason == "dedupe_key_shape"
        assert queue.calls == []
        assert outcome.receipt is not None
        assert outcome.receipt.public_message == "dedupe_key_shape"
        return

    assert outcome.verdict.action == "allow", f"{why}：段级脏该被出口救回"
    landed = _exit_key_of(queue)
    assert landed == canonical, f"{why}：落库键 ≠ 手算规范形"
    assert dedupe_key_shape_ok(landed) is True, f"{why}：落库键不过形：{landed!r}"
    assert _segments_all_legal(landed), f"{why}：落库键含非法段：{landed!r}"



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


def central_entry_executable_hits(path: Path) -> list[int]:
    """文件里**真的伸手去够** `submit_active_push` 的行号（可执行引用；空＝没有）。

    判据真身只有这一支：`test_submit_active_push_has_at_least_one_production_caller`
    （活性侧）、`test_submit_active_push_production_importers_are_allowlisted`
    （越界面）、以及 `tests/test_emergency_info_core.py::
    test_domain_reaches_the_queue_only_through_the_central_gate` ① 段（域侧对齐锁，
    它 `import test_outbound_gate` 复用本函数）三处共用，**禁另立第二把尺**。

    收哪些形态（与 `tests/test_active_push_entry_teeth.py` 的 `_is_call_api_channel`
    同一套「别名／动态派发也算够到了」的口径，那条先例已实证"只认字面调用"是瞎的）：

    - `from x import submit_active_push`（含 `as 别名`）与 `import a.submit_active_push`；
    - 名字出现在任何表达式位置：直接调用、**别名赋值** `f = submit_active_push`、
      当实参交出去、`return`／`yield`、`submit_active_push.__doc__`；
    - 属性形态 `mod.submit_active_push(...)`；
    - **字符串派发**：字符串作为**调用实参**（`getattr(m, "submit_active_push")`）或
      **下标索引**（`globals()["submit_active_push"]`）——这类没有名字节点可抓，
      不认就等于给"用字符串绕过 import 扫描"留门。

    不收的形态（诚实边界，别叙述成"动态引用全视"）：写在**字典键值／集合元素／普通赋值
    右侧的字符串常量**里仍算声明性——`ARM_FORM_SEAMS` 这类投影表就长这样，把它判成可执行
    等于判死名册自己。真要堵那一形态只能靠"禁止用字符串表派发中央出口"的硬规则，另案。
    `foo(submit_active_push=...)` 这种**关键字名**同样不算引用（那是参数名，不是引用）。

    fail-closed：文本含该名字但 `ast.parse` 失败 ⇒ 返回 `[-1]`，即"按可执行算"，
    读不动的代码不配拿声明性豁免。
    """
    source = path.read_text(encoding="utf-8")
    if CENTRAL_ENTRY not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [-1]
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == CENTRAL_ENTRY for alias in node.names):
                hits.append(int(node.lineno))
        elif isinstance(node, ast.Import):
            if any(
                alias.name == CENTRAL_ENTRY or alias.name.endswith(f".{CENTRAL_ENTRY}")
                for alias in node.names
            ):
                hits.append(int(node.lineno))
        elif isinstance(node, ast.Name):
            if node.id == CENTRAL_ENTRY:
                hits.append(int(node.lineno))
        elif isinstance(node, ast.Attribute):
            if node.attr == CENTRAL_ENTRY:
                hits.append(int(node.lineno))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if CENTRAL_ENTRY not in node.value:
                continue
            parent = parents.get(id(node))
            direct_call_arg = isinstance(parent, ast.Call) and any(
                arg is node for arg in parent.args
            )
            subscript_index = isinstance(parent, ast.Subscript) and parent.slice is node
            if direct_call_arg or subscript_index:
                hits.append(int(node.lineno))
    return hits


def _production_uses_of_central_entry() -> list[str]:
    """生产面**真的**用上 `submit_active_push` 的文件（判据＝`central_entry_executable_hits`）。

    只按文本命中算的话，一句注释就能造假；这里走 AST 的可执行引用判据。
    闸自身（定义处 `GATE_FILE`）排除。
    """
    found: list[str] = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path == GATE_FILE:
            continue
        if central_entry_executable_hits(path):
            found.append(path.relative_to(PLUGIN_ROOT).as_posix())
    return found


def test_submit_active_push_production_importers_are_allowlisted() -> None:
    """T6：`submit_active_push` 的生产**可执行引用**只允许出现在 transport 本体与紧急域。

    两态分开判（S274 收口，别把这两件事再混回同一把尺）：
    - **可执行引用**（import／调用／别名／字符串派发，判据真身 `central_entry_executable_hits`）
      落在白名单之外 ⇒ 进 `offenders`，当场红；
    - **声明性提及**（docstring／注释／形↔缝投影表里的字符串值）⇒ 不算旁路，但必须落在
      `DECLARATIVE_NAMEPLATE` 这本显式点名册里，册子本身受等值反查腿执法。
    """
    # 前缀必须是真身目录名 `emergency_info`：写成 `domains/emergency` 会同时放行任何
    # `domains/emergency*` 兄弟目录（过松）。另注：本锁在零消费者期是"空真"通过，
    # 接线落地后须由接线席补一条正向断言（生产 import 数 ≥ 1）才算闭合——那条正向
    # 断言在本文件 `test_submit_active_push_has_at_least_one_production_caller`
    # （WIRE-A2 后已摘牌转正，见该件上方转正记录），不是等接线席想起来。
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
    declarative_only: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path == GATE_FILE:  # 只放行定义处那一个文件（精确路径，见 `GATE_FILE` 注记）
            continue
        if CENTRAL_ENTRY not in path.read_text(encoding="utf-8"):
            continue
        if path in allowed_files:
            continue
        if _under_directory(path, allowed_roots):
            continue
        # 白名单之外还要分一刀：这个名字是「被伸手够到」还是「被名字提到」。
        # 前者才是旁路（第二消费者／绕过唯一出口），后者是声明性名册，两件事
        # 不该混在同一把尺里——但豁免面必须点名（见下方反查腿），不得凭"看起来是注释"放行。
        if central_entry_executable_hits(path):
            offenders.append(path.relative_to(PLUGIN_ROOT).as_posix())
        else:
            declarative_only.append(path.relative_to(PLUGIN_ROOT).as_posix())
    assert offenders == [], (
        f"中央闸的唯一入口只允许紧急域（与 transport 本体）引用，越界：{offenders}"
    )
    # 反查腿（S274）：声明性提及的豁免面是**显式闭集**，只准点名进册、不准无声增长。
    # ① 多一枚（新件在名字层面提到中央出口却没进册）→ 红：要么改道、要么带理由登记；
    # ② 少一枚（在册件不再提这个名字）→ 红：册子不许攒"预授权豁免"等着将来用；
    # ③ 在册件一旦长出可执行引用 → 它落进上面的 `offenders` 当场红（在册≠可以够它）。
    # 这条腿的存在理由：没有它，"声明性"三个字就是一个可以无限装东西的口袋。
    assert set(declarative_only) == set(DECLARATIVE_NAMEPLATE), (
        f"中央出口的声明性提及册不匹配：实扫 {sorted(declarative_only)} ≠ 在册 "
        f"{sorted(DECLARATIVE_NAMEPLATE)}（新增须点名并写明理由，撤销须同步删行）"
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
#   S274 改版跟随：上面"AST 判 import 该符号或直接调用它"是**当时**的判据宽度；现役尺
#   `central_entry_executable_hits` 另认别名赋值与字符串派发（形态清单见其 docstring）。
#   只扩不缩——当年成立的转正在新尺下命中的文件集合不变（现算＝`push.py` 与根 `__init__.py`）。
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
    """T13：闸**不得自造任何时间解析**，两类解析各有一座唯一事实源。

    - HH:MM 静默窗 → `domains/chat_reply/policy/quiet_hours.py`（G5 原判据）；
    - ISO-8601 时刻 → `domains/core/moment_parsing.py::parse_moment`（S232 2026-09-25 补）。

    第二腿是**更强的形、不是放宽**：旧判据只禁字面量 `fromisoformat`（禁了自造却没给
    可去的家，TTL 一落地就必红），现在同时要求「import 真身 + 真身在 `parse_gate_ttl`
    里被真调用」——退回直调标准库、或只 import 不使用，都当场红（注毒自证见本席日志）。
    """
    gate_path = REPO_ROOT / GATE_MODULE
    tree = ast.parse(gate_path.read_text(encoding="utf-8"))
    imported: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )
    quiet_module = "plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours"
    moment_module = "plugins.bot_unified_runtime.domains.core.moment_parsing"
    assert quiet_module in imported, f"闸必须 import quiet_hours 设置族，实有 {sorted(imported)}"
    assert "QuietHoursSettings" in imported[quiet_module]
    assert "_parse_hhmm" in imported[quiet_module], (
        "HH:MM 解析必须复用 quiet_hours._parse_hhmm（唯一事实源），不得自造第二套"
    )
    assert moment_module in imported, (
        "闸必须 import ISO 时刻解析真身 domains/core/moment_parsing.py，"
        f"实有 {sorted(imported)}"
    )
    assert "parse_moment" in imported[moment_module], (
        "TTL 时刻解析必须复用 parse_moment（唯一事实源），不得自造第二套"
    )

    def _really_called(host_func: str, callee: str) -> bool:
        """`callee` 是否是 `host_func` 体内的**真调用点**（死导入不算复用）。"""
        host = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == host_func
            ),
            None,
        )
        if host is None:
            return False
        return any(
            isinstance(call, ast.Call)
            and (
                (isinstance(call.func, ast.Name) and call.func.id == callee)
                or (isinstance(call.func, ast.Attribute) and call.func.attr == callee)
            )
            for call in ast.walk(host)
        )

    assert _really_called("parse_gate_ttl", "parse_moment"), (
        "parse_gate_ttl 必须真调用 parse_moment——只 import 不使用＝自造解析没拆干净"
    )
    source = gate_path.read_text(encoding="utf-8")
    assert "fromisoformat" not in source, (
        "不得自造时间解析（正解：走 domains/core/moment_parsing.parse_moment）"
    )
    # 复用即证据：_parse_hhmm 不但要 import，还要真的被调用（自造解析则这里是死导入）。
    assert source.count("_parse_hhmm") >= 2, "quiet 窗必须真调用共享解析器"
    for name in (
        "_parse_hhmm",
        "parse_hhmm",
        "_parse_time",
        "_parse_clock",
        "_parse_moment",
        "parse_iso",
        "_parse_iso",
    ):
        assert f"def {name}(" not in source, (
            "不得在本文件定义第二套 HH:MM / ISO 时刻解析"
        )


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
    ("key", "namespace", "family", "expect", "canonical"),
    [
        (
            "digest_push:631 785:2026-09-14",
            "digest_push",
            "daily",
            "rescued",  # 段内空白 ⇒ 出口洗成 `631_785` 后照样过形，且带摘要后缀防撞段
            f"digest_push:{_rescued_segment('631 785')}:2026-09-14",
        ),
        (
            "daily_assist:inbox:386:2026-09:14",
            "daily_assist",
            "daily",
            "skip",  # 段内冒号＝段数被撑开，末段不再是日期 ⇒ 洗段修不了
            None,
        ),
        ("cookie-expiry:3865067623", "cookie-expiry", "daily", "skip", None),  # 按日族缺日期段
        ("reminder:7c1f2a9b:20261345", "reminder", "daily", "skip", None),  # 日期段形态假（无连字符）
        # 注：**形态**核验不查历法真值——`2026-13-45` 与紧急域一样判过。口径同源优先，
        # 别在这里"顺手加严"造成两侧分叉；现役日期一律来自 `date().isoformat()`，恒为真值。
    ],
)
def test_non_emergency_shape_rules_still_bit(
    key: str, namespace: str, family: str, expect: str, canonical: str | None
) -> None:
    """放宽的只有「前缀必须是 emg」，段字符集与日期段形态**一条没松**（读侧判据）。

    新现实补记（S184）：段级脏在**出口**被规范掉，所以本条的 skip 半边只剩「结构级脏」
    那三行；`digest_push` 那行段内空白改为验证「出口救回 + 落库键 = 手算规范形」。
    两半都在，判据没被抹平。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    # 读侧对原始脏串一律 False（这条是本用例的老本行，一字不动）。
    assert dedupe_key_shape_ok(key, family=family, namespace=namespace) is False, key

    queue = RecordingQueue()
    now = _utc(12, 0)
    outcome = _push(
        queue,
        _request(dedupe_key=key),
        _open_gate(now),
        now=now,
        dedupe_family=family,
        dedupe_namespace=namespace,
    )

    if expect == "skip":
        assert outcome.verdict.action == "skip", key
        assert outcome.verdict.reason == "dedupe_key_shape"
        assert queue.calls == []
        assert outcome.receipt is not None
        assert outcome.receipt.public_message == "dedupe_key_shape"
        return

    assert outcome.verdict.action == "allow", (
        f"{key}：段级脏该由出口救回，reason={outcome.verdict.reason}"
    )
    landed = _exit_key_of(queue)
    assert landed == canonical, f"{key}：落库键 ≠ 手算规范形 {landed!r}"
    assert (
        dedupe_key_shape_ok(landed, family=family, namespace=namespace) is True
    ), f"落库键不过形：{landed!r}"



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


# ======================= S184 出口洗段的三条真不变量 + 活性锁 + 注毒自证 ==========
#: 现役投递族**真实可达**的脏键（逐条抄自两本欠账名册的输入形态：白名单裸群号、
#: 推送名单裸用户号、逗号切人不 strip 的管理员号、TG 侧带空格会话键、超长 id）。
#: 每一行都必须是「原始串过不了形门」的键——否则本条只是把干净键投了一遍，空跑。
_EXIT_SHAPE_BATTERY: tuple[tuple[str, str, str, str], ...] = (
    ("digest_push:湘潭群:2026-09-14", "digest_push", "daily", "中文群号（白名单裸值）"),
    ("digest_push:11 08838060:2026-09-14", "digest_push", "daily", "带空格群键"),
    ("digest_push:1108838060::2026-09-14", "digest_push", "daily", "尾随冒号→空段"),
    ("digest_push:" + "9" * 121 + ":2026-09-14", "digest_push", "daily", "超长 id（>120）"),
    ("daily_assist:morning:用户甲:2026-09-14", "daily_assist", "daily", "中文 user_id"),
    ("daily_assist:evening:user one:2026-09-14", "daily_assist", "daily", "带空格 user_id"),
    ("cookie-expiry: 3865067623:2026-09-14", "cookie-expiry", "daily", "逗号切人不 strip"),
    ("emg:qq:预警-A1:g-1", "emg", "once", "非 ASCII 条目号混合法字符"),
    ("ack:chat:chan nel:1:deadbeef", "ack", "once", "TG 侧带空格会话键"),
)


@pytest.mark.parametrize(("raw_key", "namespace", "family", "why"), list(_EXIT_SHAPE_BATTERY))
def test_central_exit_leaves_no_shape_failing_key_behind_it(
    raw_key: str, namespace: str, family: str, why: str
) -> None:
    """①：无论调用方交出什么键，**抵达队列那一行**必过形 ⇒ 键形不再产生静默 skip。

    判据用读侧宪法谓词（`dedupe_key_shape_ok` 委托到 `dedupe.py` 那一份实现），
    不是拿出口自己的输出判自己。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        dedupe_key_shape_ok,
    )

    # 前置：这枚键在出口之前确实过不了形（不然本行什么都没考）。
    assert (
        dedupe_key_shape_ok(raw_key, family=family, namespace=namespace) is False
    ), f"{why}：原始键本来就过形，本行是空跑，请换脏样本"

    queue = RecordingQueue()
    outcome = _push(
        queue,
        _request(dedupe_key=raw_key),
        _open_gate(),
        now=_utc(12, 0),
        dedupe_family=family,
        dedupe_namespace=namespace,
    )

    assert outcome.verdict.action == "allow", (
        f"{why}：出口没能把它规范成过形键，reason={outcome.verdict.reason}"
        "＝「开闸即静默丢」复发"
    )
    landed = _exit_key_of(queue)
    assert (
        dedupe_key_shape_ok(landed, family=family, namespace=namespace) is True
    ), f"{why}：落库键仍不过形：{landed!r}"
    assert _segments_all_legal(landed), f"{why}：落库键含非法段：{landed!r}"
    assert queue.calls == [("req-emg-1", {})]


def test_shape_battery_covers_every_active_push_namespace() -> None:
    """反空跑：①的样本表必须**真的**覆盖到各申报族，不能全是 emg 一家。"""
    namespaces = {row[1] for row in _EXIT_SHAPE_BATTERY}
    assert {"digest_push", "daily_assist", "cookie-expiry", "emg", "ack"} <= namespaces
    assert len({row[0] for row in _EXIT_SHAPE_BATTERY}) == len(_EXIT_SHAPE_BATTERY), (
        "样本表出现重复原始键：某族被静默少测一行"
    )


def test_same_identity_dirty_forms_converge_to_one_key_at_the_exit() -> None:
    """②：同一身份的多种脏形在出口产出**逐字相同**的键（旧判据「skip 挡重发」作废）。

    旧用例说的是「带空格与不带空格是两条队列行＝重发」，靠闸把它 skip 掉来防重发；
    新现实直接让两者收敛成同一枚键——收敛比 skip 强（消息照发，幂等照成立）。
    """
    clean = "emg:qq:item-1:g-1"
    dirty_forms = (
        "emg:qq:item-1:g-1 ",  # 尾随空白
        "emg:  qq:item-1:g-1",  # 段前空白
        "emg:qq: item-1:g-1",  # 段内前导空白
        "emg:qq:item-1:g-1\t",  # 制表符同样是段级脏
    )
    landed: list[str] = []
    for form in (clean,) + dirty_forms:
        queue = RecordingQueue()
        outcome = _push(
            queue, _request(dedupe_key=form), _open_gate(), now=_utc(12, 0)
        )
        assert outcome.verdict.action == "allow", f"{form!r} 被拒收"
        landed.append(_exit_key_of(queue))

    assert set(landed) == {clean}, f"同身份未收敛成一枚键：{landed}"


def test_converged_forms_land_in_one_idempotency_bucket_in_real_queue(
    tmp_path: Path,
) -> None:
    """②的另一半（真队列）：干净键已占坑时，脏形同身份被 `ON CONFLICT` 判重复。

    这条才叫「重发防护」——不是闸 skip（skip 是漏报），而是幂等真成立。
    """
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
        settings=OutboundGateSettings(
            enabled=True, max_per_target_per_minute=0, max_per_target_per_hour=0
        ),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_utc(12, 0),
    )
    first = _push(real_queue, _request(dedupe_key="emg:qq:item-1:g-1"), gate, now=_utc(12, 0))
    dirty_same = _push(
        real_queue,
        _request(request_id="req-dirty-same", dedupe_key="emg:qq:item-1:g-1 "),
        gate,
        now=_utc(12, 0),
    )
    dirty_other = _push(
        real_queue,
        _request(request_id="req-dirty-other", dedupe_key="emg:qq:item-2:g-1 "),
        gate,
        now=_utc(12, 0),
    )
    assert first.receipt is not None and first.receipt.state is ReceiptState.QUEUED
    assert dirty_same.receipt is not None
    assert dirty_same.receipt.state is ReceiptState.SKIPPED, (
        "脏形没落进同一个幂等桶 ⇒ 同一推送发两遍（收敛失效）"
    )
    assert dirty_other.receipt is not None
    assert dirty_other.receipt.state is ReceiptState.QUEUED, (
        "不同身份被并进了同一桶 ⇒ 洗段把两件事当一件（撞段）"
    )


def test_closed_gate_path_is_normalised_too() -> None:
    """关态同样过一遍出口洗段：闸没开≠没人治理（「本地测通、上线丢」的反打）。

    这正是本波同型炸三次的病根——旧现实里关态 passthrough 照发脏键，开闸才判死；
    新现实下两种状态落库的都是同一枚规范键。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    gate = _gate(
        settings=OutboundGateSettings(enabled=False),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_utc(12, 0),
    )
    queue = RecordingQueue()
    # 选「同一身份的段尾空白 vs 干净形」而不是「`631 785` vs `631_785`」：后者在洗段
    # 近似单射（S184 §3-① 修复）后**本就是两个不同身份**（空格段带 `_h<摘要>` 后缀、下划线段
    # 原样保留），再断它们收敛成同一枚就是断一条被刻意拆开的假命题。段尾空白 `strip()` 掉后
    # 与干净段同值 ⇒ 仍是「同身份多形收敛」，且脏形（带空格）非经出口洗段不可归一，判据照有牙。
    for form, request_id in (
        ("digest_push:631_785:2026-09-14", "req-a"),
        ("digest_push:631_785 :2026-09-14", "req-b"),
    ):
        outcome = _push(
            queue,
            _request(request_id=request_id, dedupe_key=form),
            gate,
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
        assert outcome.verdict.reason == "disabled"
    assert queue.keys == ["digest_push:631_785:2026-09-14"] * 2, (
        f"关态没洗段（或把两身份错并成一桶）：{queue.keys}"
    )


def test_distinct_identities_never_collide_into_one_key_at_the_exit() -> None:
    """③：不同身份绝不撞段——尤其是「洗完只剩分隔符」走摘要兜底那两条路。

    第二对是全角冒号 `：`（U+FF1A，**不是**段分隔符）与中文群号：两者按字符替换都会塌成
    `___`，只有摘要兜底能让它们保持两枚不同的键。塌成同一段＝两件事共用一个幂等桶。
    """
    pairs: tuple[tuple[str, str], ...] = (
        ("emg:qq:预警:g-1", "emg:qq:预警:g-2"),  # 同脏段、不同目标
        ("digest_push:中文群:2026-09-14", "digest_push:\uff1a\uff1a\uff1a:2026-09-14"),
        ("daily_assist:morning:用户甲:2026-09-14", "daily_assist:morning:用户乙:2026-09-14"),
    )
    for left, right in pairs:
        left_queue, right_queue = RecordingQueue(), RecordingQueue()
        namespace = left.split(":")[0]
        family = "daily" if namespace != "emg" else "once"
        for source, sink in ((left, left_queue), (right, right_queue)):
            outcome = _push(
                sink,
                _request(dedupe_key=source),
                _open_gate(),
                now=_utc(12, 0),
                dedupe_family=family,
                dedupe_namespace=namespace,
            )
            assert outcome.verdict.action == "allow", source
        assert left_queue.keys != right_queue.keys, (
            f"两枚不同身份撞成同一键：{left_queue.keys} == {right_queue.keys}"
        )
        assert _segments_all_legal(left_queue.keys[0]), left_queue.keys
        assert _segments_all_legal(right_queue.keys[0]), right_queue.keys


def test_degenerate_segments_fall_back_to_a_digest_not_a_collapse() -> None:
    """③的成因面：洗完只剩分隔符的退化段必须变成 `h`+摘要，且同一文本恒等、可复算。

    期望值由本文件 `_digest_segment` 用标准库**独立复算**，不 import 出口实现。
    """
    queue = RecordingQueue()
    _push(queue, _request(dedupe_key="emg:qq:预警:g-1"), _open_gate(), now=_utc(12, 0))
    landed = _exit_key_of(queue)
    segments = landed.split(":")
    assert segments[0] == "emg" and segments[3] == "g-1", landed
    assert segments[2] == _digest_segment("预警"), landed
    assert segments[2] != "__", "退化段塌成纯分隔符＝不同身份必撞"

    # 同一文本两次投递必须恒等（幂等只认整串，摘要一抖动桶就对不上）。
    again = RecordingQueue()
    _push(again, _request(dedupe_key="emg:qq:预警:g-1"), _open_gate(), now=_utc(12, 0))
    assert again.keys == [landed]

    # 空段同理：`emg:qq::target` 的第三段是「空串的摘要」，不是空串。
    empty = RecordingQueue()
    _push(empty, _request(dedupe_key="emg:qq::target"), _open_gate(), now=_utc(12, 0))
    assert empty.keys == [f"emg:qq:{_digest_segment('')}:target"], empty.keys


def test_washing_is_idempotent_so_construction_and_exit_double_wash_is_safe() -> None:
    """构造侧已洗过（ack 族）+ 出口再洗一次 ⇒ 逐字节不变 ⇒ 双保险不是双重改写。

    没有这条，「把 `ack_key_segment` 撤掉只留出口」与「两处都洗」看起来等价；
    实际只有幂等成立时，名册里那两本账才能各自降、不互相顶替。
    """
    already_washed = f"emg:qq:{_digest_segment('湘潭')}:g-1"
    queue = RecordingQueue()
    outcome = _push(
        queue, _request(dedupe_key=already_washed), _open_gate(), now=_utc(12, 0)
    )
    assert outcome.verdict.action == "allow"
    assert _exit_key_of(queue) == already_washed, "已规范的键被二次改写＝幂等桶会漂"


def test_dirty_key_at_the_exit_is_announced_and_clean_keys_stay_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """改写必留一行 WARNING（不静默），干净键一行都不许多（不刷日志）。

    取**整行等值**（与本文件 `test_record_failure_still_allows_and_reports` 同一纪律）：
    只钉短语会让「字段被涂值/被删词」溜过去。日志里只有长度与哈希，没有键原文。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        _subject_hash,
    )

    raw = "digest_push:631 785:2026-09-14"
    # 洗完带 `_h<摘要>` 后缀（近似单射）：canonical 由本文件独立复算，after_len/after_hash
    # 随之跟随；断的是「播报的行 = 出口真正落库那一枚规范键」，不是把键原文写进日志。
    canonical = f"digest_push:{_rescued_segment('631 785')}:2026-09-14"
    with caplog.at_level("WARNING"):
        _push(
            RecordingQueue(),
            _request(dedupe_key=raw),
            _open_gate(),
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
    messages = [
        record.getMessage() for record in caplog.records if record.levelname == "WARNING"
    ]
    assert messages == [
        (
            "outbound_gate dedupe_key_normalized capability_id=bot.emergency"
            " dedupe_family=daily"
            f" before_len={len(raw)} after_len={len(canonical)}"
            f" after_hash={_subject_hash(canonical)}"
        )
    ], messages
    assert raw not in " ".join(messages)  # 键原文不入日志

    caplog.records.clear()
    with caplog.at_level("WARNING"):
        _push(
            RecordingQueue(),
            _request(dedupe_key=canonical),
            _open_gate(),
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
    assert [
        record.getMessage()
        for record in caplog.records
        if "dedupe_key_normalized" in record.getMessage()
    ] == [], "干净键也被播报＝每次投递刷一行，日志噪音会把真改写埋掉"


def test_bypass_of_the_central_exit_ships_the_raw_dirty_key() -> None:
    """出口洗段的作用域只有它自己：绕过去直调 `queue.submit`，脏键原样落库。

    这条是两本欠账名册（`test_active_push_key_shape_ledger.py` /
    `test_outbound_gate_opening_preconditions.py`）**不许被抹成零**的理由：
    治理发生在 `submit_active_push`，直调点没有这层保护。判据只说事实——
    「构造侧仍该洗段」，不说「已经安全」。
    """
    dirty = "digest_push:湘潭群:2026-09-14"
    direct = RecordingQueue()
    direct.submit(_request(request_id="req-bypass", dedupe_key=dirty))
    assert direct.keys == [dirty], (
        "直调队列竟也被洗段了——那出口的作用域锁要一起改写"
    )
    assert _segments_all_legal(direct.keys[0]) is False

    through_exit = RecordingQueue()
    _push(
        through_exit,
        _request(request_id="req-via-exit", dedupe_key=dirty),
        _open_gate(),
        now=_utc(12, 0),
        dedupe_family="daily",
        dedupe_namespace="digest_push",
    )
    assert through_exit.keys != [dirty], "同一枚脏键走出口却没被规范＝出口洗段不生效"
    assert _segments_all_legal(through_exit.keys[0]) is True


# ------------------------------------------------------------------ 活性锁（洗段↔判定顺序）
def _wash_pipeline_findings(source: str) -> dict[str, bool]:
    """静态判据：`submit_active_push` 里「洗段 → 改写请求 → 送闸」这条链是否成立。

    只做**结构**判定（AST），不执行代码，因此注毒可以在内存里改源码文本来跑
    （禁写面 `outbound_gate.py` 一个字节都不落盘）。
    """
    tree = ast.parse(source)
    dedupe_module = (
        "plugins.bot_unified_runtime.domains.emergency_info.service.dedupe"
    )
    findings = {
        "import_wash": any(
            isinstance(node, ast.ImportFrom)
            and node.module == dedupe_module
            and any(alias.name == "wash_active_push_key" for alias in node.names)
            for node in ast.walk(tree)
        ),
        "function_present": False,
        "call_wash": False,
        "wash_before_decide": False,
        "rebind_before_decide": False,
        "decide_gets_the_request": False,
        "update_carries_dedupe_key": False,
        "warning_present": False,
    }
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "submit_active_push"
        ),
        None,
    )
    if fn is None:
        return findings
    findings["function_present"] = True

    wash_lines: list[int] = []
    decide_lines: list[int] = []
    copy_update_keys: set[str] = set()
    decide_first_args: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "wash_active_push_key":
            wash_lines.append(int(node.lineno))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "decide":
            decide_lines.append(int(node.lineno))
            if node.args and isinstance(node.args[0], ast.Name):
                decide_first_args.add(node.args[0].id)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "model_copy":
            for keyword in node.keywords:
                if keyword.arg != "update" or not isinstance(keyword.value, ast.Dict):
                    continue
                for dict_key in keyword.value.keys:
                    if isinstance(dict_key, ast.Constant) and isinstance(
                        dict_key.value, str
                    ):
                        copy_update_keys.add(dict_key.value)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "warning"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and "dedupe_key_normalized" in node.args[0].value
        ):
            findings["warning_present"] = True

    rebind_lines = [
        int(node.lineno)
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "send_request" for target in node.targets)
    ]
    findings["call_wash"] = bool(wash_lines)
    findings["update_carries_dedupe_key"] = "dedupe_key" in copy_update_keys
    findings["decide_gets_the_request"] = "send_request" in decide_first_args
    if wash_lines and decide_lines:
        findings["wash_before_decide"] = min(wash_lines) < min(decide_lines)
        findings["rebind_before_decide"] = bool(rebind_lines) and min(rebind_lines) < min(
            decide_lines
        )
    return findings


def _gate_source() -> str:
    return (REPO_ROOT / GATE_MODULE).read_text(encoding="utf-8")


def test_central_exit_washes_the_key_before_the_gate_decides() -> None:
    """活性锁：出口真的调了 `wash_active_push_key`，且发生在 `gate.decide` **之前**。

    为什么必须是结构锁而不是「取值互比」：洗段与判定都在同一个函数里，只比最终落库键
    的话，「先判后洗」（skip 已经发生、洗了也来不及）与「先洗后判」取值完全同形——
    而恰恰是顺序决定了「静默丢」还是「规范后放行」。故钉 lineno 顺序 + 改写发生在
    decide 之前 + decide 收到的就是那枚被改写过的 `send_request`。
    """
    findings = _wash_pipeline_findings(_gate_source())
    assert findings and all(findings.values()), (
        f"出口洗段链路断裂：{ {k: v for k, v in findings.items() if not v} }"
    )


def test_wash_before_decide_lock_has_teeth() -> None:
    """注毒（结构面，两发）：删掉那行调用 / 把洗段口换成恒等 lambda ⇒ 本锁必红。

    两发都是**内存里改源码文本**，生产件不落盘（`outbound_gate.py` 在禁写面上）。
    """
    source = _gate_source()
    baseline = _wash_pipeline_findings(source)
    assert baseline and all(baseline.values()), f"基线本就不干净：{baseline}"

    dropped = source.replace(
        "    canonical_key = wash_active_push_key(send_request.dedupe_key)\n", "", 1
    )
    assert dropped != source, (
        "注毒点消失（出口那行洗段调用改了形态），须同步本自证——否则锁已失明"
    )
    poison_a = _wash_pipeline_findings(dropped)
    assert not poison_a["call_wash"] and not poison_a["wash_before_decide"], poison_a

    identity = source.replace(
        "wash_active_push_key(send_request.dedupe_key)",
        "(lambda _k: _k)(send_request.dedupe_key)",
        1,
    )
    assert identity != source, "注毒点消失（洗段调用的写法变了），须同步本自证"
    poison_b = _wash_pipeline_findings(identity)
    assert not poison_b["call_wash"], poison_b

    # 第三发：把改写挪到 decide **之后**（顺序病，取值面看不出来）。
    swapped = source.replace(
        "    canonical_key = wash_active_push_key(send_request.dedupe_key)\n"
        "    if canonical_key != send_request.dedupe_key:\n",
        "    if False:\n",
        1,
    )
    if swapped != source:  # 结构对不上时不强求，前两发已各自咬到独立判据
        assert not _wash_pipeline_findings(swapped)["wash_before_decide"]


# ------------------------------------------------------------------ 注毒自证（行为面）
def test_identity_wash_poison_brings_the_silent_drop_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（行为面）：把洗段口换成恒等函数 ⇒ ①②当场退化，证明真不变量靠的是那一行。

    「删掉调用」与「换成恒等」在行为上严格同形（键不变 ⇒ 不比较 ⇒ 不改写 ⇒ 不播报），
    故行为面一发即覆盖两发；结构面对恒等 lambda 也能抓（调用名没了），两把尺互不替代。
    """
    from plugins.bot_unified_runtime.domains.transport.sender import outbound_gate as og

    monkeypatch.setattr(og, "wash_active_push_key", lambda key: str(key))

    dirty = "emg:qq:预警:g-1"
    queue = RecordingQueue()
    outcome = _push(queue, _request(dedupe_key=dirty), _open_gate(), now=_utc(12, 0))
    assert outcome.verdict.action == "skip", (
        "恒等洗段下居然还放行——那说明本锁考的形门根本没生效"
    )
    assert outcome.verdict.reason == "dedupe_key_shape"
    assert queue.calls == [], "①被破：脏键仍会「开闸即静默丢」"

    # ②的另一面：关态下两形各落一行＝重发（这正是本波炸过三次的原形）。
    closed = _gate(
        settings=og.OutboundGateSettings(enabled=False),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_utc(12, 0),
    )
    passthrough = RecordingQueue()
    for form, request_id in (
        ("digest_push:631 785:2026-09-14", "req-a"),
        ("digest_push:631_785:2026-09-14", "req-b"),
    ):
        _push(
            passthrough,
            _request(request_id=request_id, dedupe_key=form),
            closed,
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
    assert passthrough.keys[0] != passthrough.keys[1], (
        f"恒等洗段下两形仍同键（{passthrough.keys}）＝本发注毒没打到点上"
    )


def _naive_wash_without_digest_fallback(key: str) -> str:
    """反事实洗段体：**只**把非法字符换成 `_`、没有摘要兜底（现役规则明令要避免的退化形）。

    不是生产代码，只用来证明 ③ 那条用例有牙：塌段一发生，不同身份必撞同一键。
    """
    legal = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    )

    def _segment(raw: str) -> str:
        text = raw.strip()
        if text and all(char in legal for char in text):
            return text
        return "".join(char if char in legal else "_" for char in text)

    return ":".join(_segment(part) for part in str(key).split(":"))


def test_digestless_wash_poison_collapses_distinct_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒（③）：去掉摘要兜底 ⇒ `中文群` 与 `：：：` 同塌成 `___` ⇒ 两件事共用一个桶。

    与上一条同一手法（内存替换出口符号），生产件零改动。
    """
    from plugins.bot_unified_runtime.domains.transport.sender import outbound_gate as og

    left, right = "digest_push:中文群:2026-09-14", "digest_push:\uff1a\uff1a\uff1a:2026-09-14"
    assert _naive_wash_without_digest_fallback(left.split(":")[1]) == (
        _naive_wash_without_digest_fallback(right.split(":")[1])
    ), "反事实体本身没造出塌段——本发注毒无从验证，请改写退化样本"

    monkeypatch.setattr(og, "wash_active_push_key", _naive_wash_without_digest_fallback)
    keys: list[str] = []
    for raw in (left, right):
        queue = RecordingQueue()
        _push(
            queue,
            _request(dedupe_key=raw),
            _open_gate(),
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
        keys.append(_exit_key_of(queue))
    assert keys[0] == keys[1], (
        f"塌段注毒下两身份仍未撞（{keys}）＝③用例的判别力落空，须换样本"
    )


def test_wash_is_injective_on_the_two_s184_collapse_classes() -> None:
    """正向锁（S192，接管 S184 §3-① 交回的「洗段非单射」缺陷）。

    旧版本 `test_wash_residual_non_injective_punctuation_and_truncation` 是一枚**现状刻画锁**，
    docstring 自证「修法落地之日就是本条翻红之时——届时请改成不撞段的正断言」。主代理已把
    「真被洗过的段」统一带上原串 blake2b 摘要后缀（`dedupe.py:active_push_key_segment`），
    那两类塌陷都被拆开，本条据此翻正：

    - ①「非法字符映到合法字符」：`11 08838060`（空格）与 `11_08838060`（下划线）不再同段——
      空格段走洗段分支带 `_h<摘要>`，下划线段本就合法原样保留，二者逐字不同；
    - ②「超长截断」：第 121 位与第 122 位不同的长 id 不再同段——摘要算在**截断前的整串**上，
      截断后的 `washed` 前缀虽相同，后缀却不同。

    期望走**出口**（`submit_active_push` 真洗一遍再过闸落库），与 §2 的构造侧直测互补；
    杀伤力由 `test_poison_nodigest_restores_the_s184_collisions` 反向验过。
    """

    def _landed(raw: str) -> str:
        queue = RecordingQueue()
        _push(
            queue,
            _request(dedupe_key=raw),
            _open_gate(),
            now=_utc(12, 0),
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
        return _exit_key_of(queue)

    left, right = (
        _landed("digest_push:11 08838060:2026-09-14"),
        _landed("digest_push:11_08838060:2026-09-14"),
    )
    assert left != right, f"①仍互撞（{left} == {right}）＝洗段可注入性回退"
    long_a, long_b = (
        _landed(f"digest_push:{'9' * 121}:2026-09-14"),
        _landed(f"digest_push:{'9' * 122}:2026-09-14"),
    )
    assert long_a != long_b, f"②仍互撞（截断又吃掉了身份）：{long_a} == {long_b}"


def test_active_push_key_segment_is_injective_legal_idempotent_and_bounded() -> None:
    """构造侧四把尺（S192 §2 ③④⑤⑥）：退化输入两两不撞、幂等、合法逐字节不变、过谓词且 ≤120。

    全部直接调用被测件，不走出口，把「洗段近似单射」的四条承诺钉在最内层：
    - ③ `中文群` / `：：：` / `空段` 三类退化输入两两不撞；`""` 与 `"   "` **刻意同为空桶**
      （`active_push_key_segment` 先 `strip()` 再算，空白变体本就是「同一枚空身份」——这正是
      主代理修法的原话「先 strip() 再算，故 " x" 与 "x" 仍同为 x」，若断它们不等反而是造假红）；
    - ④ 同输入两次调用逐字相同（幂等不被摘要破坏）；
    - ⑤ 合法输入输出逐字节等于输入（现役键零变化的那条承诺要有机检）；
    - ⑥ 洗完的段仍过中央谓词 `is_legal_segment` 且长度 ≤ `_KEY_SEGMENT_MAX`。
    """
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        active_push_key_segment,
        is_legal_segment,
    )

    # ③ 三类真正承载不同信息的退化输入：两两不撞。
    distinct_inputs = ["", "中文群", "：：："]
    distinct_segments = [active_push_key_segment(x) for x in distinct_inputs]
    assert len(set(distinct_segments)) == len(distinct_segments), distinct_segments
    # 空段与纯空白同属「空身份」一桶（strip 语义），这是**设计**、不是塌陷：显式钉死，
    # 免得有人误把它当第二个 S184 缺陷去「修」（真去修就会与 " x"=="x" 那条承诺打架）。
    assert active_push_key_segment("") == active_push_key_segment("   ") == "h" + (
        hashlib.blake2b(b"", digest_size=8).hexdigest()
    ), "空/空白应同为空桶"
    # ⑤+空白不变（`_h` 摘要前的 strip）：带前后空白的合法段与裸段同值。
    assert active_push_key_segment(" x") == active_push_key_segment("x") == "x"
    assert active_push_key_segment("  qq  ") == "qq"

    # ④ 幂等：对退化/合法/脏样本各调两次都逐字相同；且洗过的段再喂回去仍不动（双洗同键）。
    idempotent_inputs = distinct_inputs + [
        " x", "中文群", "has space", "631 785", "group:1", "9" * 121, "3865067623",
    ]
    for sample in idempotent_inputs:
        once = active_push_key_segment(sample)
        assert active_push_key_segment(sample) == once, sample
        assert active_push_key_segment(once) == once, f"双洗漂移：{sample!r}→{once!r}"

    # ⑤ 合法输入逐字节不变（现役键零变化的机检，覆盖纯数字/含 ._-/恰 120 长）。
    for legal in ["3865067623", "item-1", "gov_9.2", "chat.123", "a" * _KEY_SEGMENT_MAX]:
        assert active_push_key_segment(legal) == legal, legal

    # ⑥ 洗完一律是合法段且不超长（含边界：长 id 洗后恰 ≤120 且过谓词，否则开闸即判死）。
    for sample in idempotent_inputs + ["digest_push", "预警", "！!xx！"]:
        washed = active_push_key_segment(sample)
        assert is_legal_segment(washed), (sample, washed)
        assert 1 <= len(washed) <= _KEY_SEGMENT_MAX, (sample, len(washed))


def test_poison_nodigest_restores_the_s184_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒①（不落盘）：把摘要后缀与退化兜底抹回裸形态 ⇒ ①②③三类塌陷全部复现。

    反证「近似单射这条腿真的存在」：真身下 `11 08838060`/`11_08838060`、`中文群`/`：：：`、
    121/122 位长 id 都不同段；换成 `_naive_wash_without_digest` 后逐对**同段**。若某对在注毒体下
    仍未撞，说明正锁那一格是空跑（本席判据落空，须换样本）。monkeypatch 由 pytest 自动还原，
    `dedupe.py` 一个字节未动。
    """
    import plugins.bot_unified_runtime.domains.emergency_info.service.dedupe as dedupe_mod

    def _seg(value: object) -> str:
        return dedupe_mod.wash_active_push_key(f"x:{value}")  # 借出口逐段洗，取洗后的身份段

    monkeypatch.setattr(dedupe_mod, "active_push_key_segment", _naive_wash_without_digest)
    assert _seg("11 08838060") == _seg("11_08838060"), "①腿不存在：无摘要也拆不开空格/下划线"
    assert _seg("中文群") == _seg("：：："), "③腿不存在：无兜底摘要也拆不开中文/标点"
    assert _seg("9" * 121) == _seg("9" * 122), "②腿不存在：无摘要截断也没吃回同段"


def test_poison_truncate_at_budget_breaks_long_id_legality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒②（不落盘）：截断预算从 `120-len(suffix)` 改回 `120` ⇒ 长 id 洗完越界、不过谓词。

    这咬的是 ⑥「洗后段仍 ≤120 且合法」那一格：后缀 `_h<16hex>` 占 18 字符，若 `washed` 仍截满
    120，拼出的段就是 138 字符，`is_legal_segment` 判 False ⇒ 开闸态这枚键注定被 skip（又一例
    「本地测通、上线丢」）。真身按 102 预算截，段恒 ≤120。
    """
    import plugins.bot_unified_runtime.domains.emergency_info.service.dedupe as dedupe_mod
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        is_legal_segment,
    )

    def _overlong_wash(value: object) -> str:
        text = str(value or "").strip()
        if is_legal_segment(text):
            return text
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
        washed = "".join(
            c if c in _LEGAL_SEGMENT_CHARS else "_" for c in text
        )[:_KEY_SEGMENT_MAX]  # ← 毒：预算忘了减 len(suffix)
        if is_legal_segment(washed) and any(c.isalnum() for c in washed):
            return washed + "_h" + digest
        return "h" + digest

    monkeypatch.setattr(dedupe_mod, "active_push_key_segment", _overlong_wash)
    long_wash = dedupe_mod.wash_active_push_key(f"digest_push:{'9' * 121}:2026-09-14")
    seg = long_wash.split(":")[1]
    assert len(seg) > _KEY_SEGMENT_MAX or not is_legal_segment(seg), (
        "注毒未造出越界段 ⇒ ⑥的截断预算这一腿是空的（真身与毒同形），判据落空"
    )


def test_poison_nostrip_breaks_whitespace_invariance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒③（不落盘）：去掉 `text.strip()` ⇒ `" x"` 与 `"x"` 不再同键（空白粘进段里）。

    这咬的是「空/空白同为空桶、`" x"=="x"`」这条 strip 语义承诺（与 ①②③ 的近似单射配套）：
    真身先 strip 再判/算，`" x"`→`"x"`；去掉 strip 后 `" x"` 被当脏段，`is_legal_segment` 因内部
    又 strip 仍判 True ⇒ 直接原样返回带空格的 `" x"`，于是 `" x" != "x"`。若注毒后二者仍相等，
    说明这一腿没被真正判到（判据落空）。
    """
    import plugins.bot_unified_runtime.domains.emergency_info.service.dedupe as dedupe_mod
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        is_legal_segment,
    )

    def _no_strip(value: object) -> str:
        text = str(value or "")  # ← 毒：漏了 .strip()
        if is_legal_segment(text):
            return text
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
        suffix = "_h" + digest
        washed = "".join(
            c if c in _LEGAL_SEGMENT_CHARS else "_" for c in text
        )[: _KEY_SEGMENT_MAX - len(suffix)]
        if is_legal_segment(washed) and any(c.isalnum() for c in washed):
            return washed + suffix
        return "h" + digest

    monkeypatch.setattr(dedupe_mod, "active_push_key_segment", _no_strip)
    assert dedupe_mod.wash_active_push_key("ack:x: x") != dedupe_mod.wash_active_push_key(
        "ack:x:x"
    ), "注毒未打破空白不变 ⇒ 该腿判据落空（真身与注毒同形）"


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



# ================================================================== T15 TTL 执法（S260）
# 用户 2026-09-25 裁定「开，A+B」＝开闸**带自动到期**（临时停用要自己下班，不留人工
# 回滚债）。S231 落了 `enabled_until` 字段与判据函数，S232R 现算坐实它**四处断链**
# （config 无键／投影不带／`enabled`+`decide` 读裸值／两枚告警 kind 零消费者）＝
# 「在册未执法」（#49 那一族的本症）。席 S260 把四条腿一次接上，本节是它的**常驻锁**。
#
# 判据取向（为什么这么写）：
# - **行为锁优先**，AST 只当防回潮的第二条腿。本波反复咬人的正是「存在性糊过活性判据」
#   （#46 的 `nmc:A1`：静态可达性锁全绿而实际零投递；S232 的旧 G5 锁对 `strptime` 自造是瞎的）。
# - **缺省必须逐字节中性**：无 TTL（空串）时有效开启==`enabled` 本身，且好沿零告警。
# - 「关」的形态==既有 `REASON_DISABLED`（passthrough：直通裸 submit、零 store、零审计），
#   不新造第四态——那会同时改掉 `submit_active_push` 的 passthrough 计算与一批关态锁。
_TTL_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)  # == _utc(12, 0)
_TTL_PAST = "2026-09-14T00:00:00Z"
_TTL_FUTURE = "2026-09-15T00:00:00Z"
_TTL_GARBAGE = "2026-13-45"  # 月份 13：既不是「没配」也不是「已过期」，只可能是写错了


def _ttl_gate(
    *,
    until: str,
    enabled: bool = True,
    store: FakeStore | None = None,
    sink: Callable[[Any], None] | None = None,
) -> Any:
    """开闸 + 三门全不生效（限流 0／静默关）+ 一枚 TTL：让 TTL 成为唯一变量。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    return _gate(
        settings=OutboundGateSettings(
            enabled=enabled,
            quiet_defer_enabled=False,
            max_per_target_per_minute=0,
            max_per_target_per_hour=0,
            enabled_until=until,
        ),
        quiet=_quiet(enabled=False),
        store=store or FakeStore(),
        now=_TTL_NOW,
        sink=sink,
    )


# ------------------------------------------------------------- 腿①+②：键与投影
def test_ttl_absent_by_default_keeps_the_gate_byte_identical() -> None:
    """缺省中性：无 TTL（空串）⇒ 有效开启==`enabled`，三门照跑，零告警。

    这条是「新键一上就改变现网」的反证。现网 `bot_outbound_gate_enabled=False`，
    所以本用例钉的是**开闸之后**那一格：开闸且没配到期 ⇒ 行为与 TTL 落地前逐字相同。
    """
    issues: list[Any] = []
    store = FakeStore()
    gate = _ttl_gate(until="", store=store, sink=issues.append)
    assert gate.enabled is True
    verdict = gate.decide(_request(), now=_TTL_NOW)
    assert verdict.action == "allow" and verdict.reason == "allowed"
    assert store.count_calls, "无 TTL 时三门应照跑（滑窗计数是判定前置）"
    assert issues == [], f"好沿不该出声（否则缺省就改变了现网）：{[i.kind for i in issues]}"


def test_projection_lands_ttl_from_config_field() -> None:
    """腿②活性：值从 `Config` 字段一路走到 `OutboundGateSettings.enabled_until`。

    刻意用真 `Config`（`model_copy` 改一枚字段）而不是直接造 settings——断链②的本症
    就是「字段在、投影不带」，只比 settings 的话投影根本没被经过＝测了个寂寞。
    """
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        build_outbound_gate_settings,
    )

    config = Config().model_copy(
        update={"bot_outbound_gate_enabled_until": _TTL_FUTURE}
    )
    projected = build_outbound_gate_settings(config)
    assert projected.enabled_until == _TTL_FUTURE, (
        f"投影没带上 TTL（实得 {projected.enabled_until!r}）⇒ 判据永远只见「无到期」"
    )
    # 缺省值本身也钉死：空串（=无到期），不是 None、不是任何真值。
    assert Config().bot_outbound_gate_enabled_until == ""


def test_missing_ttl_key_while_siblings_present_is_loud() -> None:
    """腿②的响亮半句：同族六枚在、TTL 键不在 ⇒ 抛，且经既有出口冒 unreadable 告警。

    为什么不能静默当「无到期」：那正是用户否决的那笔债——一枚临时开关被读成永久开关。
    为什么**又不**判成「任何读不到都抛」：`SimpleNamespace()`（零键）是全仓既有缺省形态，
    `test_empty_config_projects_defaults_and_passes_through` 与四支在飞测试件都靠它造
    关态闸 ⇒ 响亮只针对「像一份闸配置却落后一步」那一形。
    """
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        build_outbound_gate_settings,
    )

    with pytest.raises(LookupError):
        build_outbound_gate_settings(SimpleNamespace(bot_outbound_gate_enabled=True))
    assert build_outbound_gate_settings(SimpleNamespace()).enabled_until == ""

    # 端到端：抛出去之后必须冒**既有那枚** KIND_SETTINGS_UNREADABLE，不是静默关闸。
    issues: list[Any] = []
    gate = _gate(
        settings=lambda: build_outbound_gate_settings(
            SimpleNamespace(bot_outbound_gate_enabled=True)
        ),
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_TTL_NOW,
        sink=issues.append,
    )
    assert gate.enabled is False, "读不到须回退缺省（关闭）"
    assert [issue.kind for issue in issues] == ["outbound_gate_settings_unreadable"], (
        f"读不到没冒既有那枚告警：{[i.kind for i in issues]}"
    )


# ------------------------------------------------------------- 腿③：判定入口
def test_expired_ttl_closes_gate_on_all_three_read_points() -> None:
    """到期即关：`enabled`／`decide`／中央出口三处**同判**，且形态==既有关态。

    三处分开的理由：断链③原本就是「两处各读裸值」。只钉一处，另一处回潮照样绿
    （#49 多入口活性锁同型判据）。关态必须逐字节等于 `enabled=False`：
    直通裸 submit（零关键字）、零 store 触点。
    """
    store = FakeStore()
    queue = RecordingQueue()
    gate = _ttl_gate(until=_TTL_PAST, store=store)
    assert gate.enabled is False

    verdict = gate.decide(_request(), now=_TTL_NOW)
    assert verdict.action == "allow" and verdict.reason == "disabled"

    outcome = _push(queue, _request(request_id="req-ttl-1"), gate)
    assert outcome.verdict.reason == "disabled"
    assert queue.calls == [("req-ttl-1", {})], "关态必须是裸 submit（与现状同形）"
    assert store.count_calls == [] and store.rows == [], (
        "到期关闸后不得再触 store（passthrough 语义=零判定零计数）"
    )


def test_unparsable_ttl_fails_closed_never_passes() -> None:
    """读不懂＝当作到期关闭并告警，**绝不**因「读不懂」当「没到期」继续放行。"""
    gate = _ttl_gate(until=_TTL_GARBAGE)
    assert gate.enabled is False
    verdict = gate.decide(_request(), now=_TTL_NOW)
    assert verdict.reason == "disabled"


def test_future_ttl_still_enforces_the_three_doors() -> None:
    """未到期⇒三门照跑（这里用键形门出 skip），证明 TTL 不是「一切直通」的旁路。"""
    queue = RecordingQueue()
    gate = _ttl_gate(until=_TTL_FUTURE)
    verdict = gate.decide(
        _request(request_id="req-ttl-shape", dedupe_key="脏/键:形"), now=_TTL_NOW
    )
    assert verdict.action == "skip" and verdict.reason == "dedupe_key_shape"
    _push(queue, _request(request_id="req-ttl-shape", dedupe_key="脏/键:形"), gate)


def test_ttl_state_words_and_effective_predicate_agree() -> None:
    """判据表：五态逐一对号（纯函数面，防「状态词与实际结论分叉」）。"""
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        TTL_STATE_ABSENT,
        TTL_STATE_ACTIVE,
        TTL_STATE_EXPIRED,
        TTL_STATE_INVALID,
        TTL_STATE_OFF,
        OutboundGateSettings,
        effective_gate_enabled,
    )

    cases: tuple[tuple[bool, str, bool, str], ...] = (
        (False, _TTL_FUTURE, False, TTL_STATE_OFF),
        (True, "", True, TTL_STATE_ABSENT),
        (True, _TTL_FUTURE, True, TTL_STATE_ACTIVE),
        (True, _TTL_PAST, False, TTL_STATE_EXPIRED),
        (True, _TTL_GARBAGE, False, TTL_STATE_INVALID),
        (False, _TTL_GARBAGE, False, TTL_STATE_OFF),  # 关态下 TTL irrelevant
    )
    for enabled, until, expect_on, expect_state in cases:
        on, state = effective_gate_enabled(
            OutboundGateSettings(enabled=enabled, enabled_until=until), _TTL_NOW
        )
        assert (on, state) == (expect_on, expect_state), (
            f"enabled={enabled} until={until!r} ⇒ 实得 {(on, state)}，应为 "
            f"{(expect_on, expect_state)}"
        )


# ------------------------------------------------------------- 腿④：告警消费者
def test_expired_ttl_emits_exactly_one_alert_per_edge() -> None:
    """到期沿出恰一枚 `outbound_gate_ttl_expired`，且**五连判不刷**（边沿闩）。

    「别新造第二套节流」的正解：本件只报边沿，时间折叠归中央 `AdminAlertSuppression`。
    一次性静音（报完不再清账）同样不许——那是更糟的形态，故另有一发复位锁。
    """
    issues: list[Any] = []
    gate = _ttl_gate(until=_TTL_PAST, sink=issues.append)
    for index in range(5):
        gate.decide(_request(request_id=f"req-edge-{index}"), now=_TTL_NOW)
    kinds = [issue.kind for issue in issues]
    assert kinds == ["outbound_gate_ttl_expired"], f"实得 {kinds}"
    assert issues[0].stage == "outbound_gate"
    assert "ttl_expired" in issues[0].safe_summary


def test_unparsable_ttl_emits_its_own_distinct_kind() -> None:
    """不可解析沿必须冒**另一枚** kind——与「到期」混成一枚就分不出「写错」与「到点」。"""
    issues: list[Any] = []
    gate = _ttl_gate(until=_TTL_GARBAGE, sink=issues.append)
    for index in range(3):
        gate.decide(_request(request_id=f"req-bad-{index}"), now=_TTL_NOW)
    assert [issue.kind for issue in issues] == ["outbound_gate_ttl_invalid"]
    # 零正文纪律：读不懂那枚不得把原值灌进 safe_summary（只许长度+摘要）。
    assert _TTL_GARBAGE not in issues[0].safe_summary


def test_ttl_edge_latch_relearms_after_recovery() -> None:
    """坏→好→坏 必须再报一次（否则「报过=永远报过」＝一次性静音，比不报更糟）。

    设置源用可变对象：同进程内「管理员续期之后又到期」的真实形状。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    mutable = OutboundGateSettings(
        enabled=True,
        quiet_defer_enabled=False,
        max_per_target_per_minute=0,
        max_per_target_per_hour=0,
        enabled_until=_TTL_PAST,
    )
    issues: list[Any] = []
    gate = _gate(
        settings=mutable,
        quiet=_quiet(enabled=False),
        store=FakeStore(),
        now=_TTL_NOW,
        sink=issues.append,
    )
    gate.decide(_request(request_id="req-a"), now=_TTL_NOW)
    mutable.enabled_until = _TTL_FUTURE  # 续期 ⇒ 好沿清账
    gate.decide(_request(request_id="req-b"), now=_TTL_NOW)
    mutable.enabled_until = _TTL_PAST    # 再次到期 ⇒ 必须再报
    gate.decide(_request(request_id="req-c"), now=_TTL_NOW)
    assert [issue.kind for issue in issues] == [
        "outbound_gate_ttl_expired",
        "outbound_gate_ttl_expired",
    ], f"实得 {[i.kind for i in issues]}"


# ------------------------------------------------------------- 结构腿（防回潮）
def _function_node(tree: Any, name: str) -> Any:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: Any) -> set[str]:
    called: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            called.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            called.add(child.func.attr)
    return called


def test_enabled_readpoints_delegate_to_single_judgment() -> None:
    """结构腿：`enabled` 与 `decide` 必须**真调用**统一判据，且体内不再裸读 enabled。

    与上面的行为锁分两把是刻意的：行为锁抓「判错了」；本锁抓「改回去读裸值、而今天
    恰好没配 TTL」——后者在缺省态下与现状逐字同形，行为锁天生看不见（＝假绿的那条路）。
    """
    tree = ast.parse(_gate_source())
    gate_class = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "OutboundGate"
    )
    report: dict[str, bool] = {}
    for method in ("enabled", "decide"):
        node = _function_node(gate_class, method)
        assert node is not None, f"闸内找不到 {method}（判据面变了，须改写本锁而不是删）"
        called = _called_names(node)
        delegated = bool({"effective_enabled", "effective_gate_enabled"} & called)
        bare_read = any(
            isinstance(child, ast.Attribute)
            and child.attr == "enabled"
            and isinstance(child.value, ast.Name)
            and child.value.id == "settings"
            for child in node.body
        )
        report[method] = delegated and not bare_read
    assert all(report.values()), f"enabled 读点未收敛到唯一判据：{report}"


def _ttl_kind_definitions(tree: ast.AST) -> set[str]:
    """模块级 `KIND_GATE_TTL_*` 常量赋值的目标名（在册清单）。"""
    return {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("KIND_GATE_TTL_")
    }


def _ttl_kind_producers(tree: ast.AST) -> set[str]:
    """被**函数体**引用的 TTL kind（=会执行的代码）。

    ⚠ 刻意只数函数体：`__all__` 里那两枚字符串是**导出面**、不是消费者——本席第一版
    把全树 Name 都算生产者，注毒「把告警消费摘掉」当场假绿（`__all__` 还在就永远红不了）。
    这正是 S232 对旧 G5 锁的同一批评：只抓字样、不抓活性。
    """
    used: set[str] = set()
    for func in (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ):
        names = {child.id for child in ast.walk(func) if isinstance(child, ast.Name)}
        used |= names & _ttl_kind_definitions(tree)
    return used


def test_ttl_alert_kinds_have_production_producers() -> None:
    """结构腿：两枚 TTL kind 必须被**函数体**引用（在册装饰≠消费者）。

    断链④原样就是「常量在册、全树零引用」。本锁剔掉定义与导出面两类假命中，
    否则「再补一行常量 / 塞进 `__all__`」就能把锁糊过去。
    """
    tree = ast.parse(_gate_source())
    defined = _ttl_kind_definitions(tree)
    assert defined == {"KIND_GATE_TTL_EXPIRED", "KIND_GATE_TTL_INVALID"}, (
        f"两枚在册 kind 形态变了（实得 {sorted(defined)}）：本锁须同步改写"
    )
    used = _ttl_kind_producers(tree)
    assert used == defined, f"这些 TTL kind 仍是装饰：缺 {sorted(defined - used)}"


# ------------------------------------------------------------- 自证（注毒四发）
def test_ttl_four_legs_are_each_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒四发，逐一对应简报四处断链：每摘一条腿，「到期必关」必须翻回「照样放行」。

    全部**内存 monkeypatch**，生产件零落盘。每发独立 `undo()`：不 undo 的话后一发会踩在
    前一发的残骸上，「四发各红」就退化成「一发红三次」（本波已自证过的假绿形态）。
    """
    from types import SimpleNamespace

    import plugins.bot_unified_runtime.domains.transport.sender.outbound_gate as mod

    config = SimpleNamespace(
        bot_outbound_gate_enabled=True,
        bot_outbound_gate_quiet_defer_enabled=False,
        bot_outbound_gate_urgent_severities=["P0", "P1"],
        bot_outbound_gate_max_per_target_per_minute=0,
        bot_outbound_gate_max_per_target_per_hour=0,
        bot_outbound_gate_db_path="data/outbound_gate.sqlite3",
        bot_outbound_gate_enabled_until=_TTL_PAST,
    )

    def enabled_now() -> bool:
        return mod.build_outbound_gate(config).enabled

    assert enabled_now() is False, "基线：到期必关（本自证的前提）"

    # ① 摘投影：值在 Config 里、投影不带 ⇒ 判据只见「无到期」⇒ 门照样开。
    def _without_ttl(cfg: object) -> Any:
        return mod.OutboundGateSettings(enabled=True, enabled_until="")

    monkeypatch.setattr(mod, "build_outbound_gate_settings", _without_ttl)
    assert enabled_now() is True, "摘投影仍关得住 ⇒ 投影那条腿是装饰"
    monkeypatch.undo()

    # ② 摘调用点：判据存在但没人调（回到读裸 `settings.enabled`）⇒ 门照样开。
    def _bare_read(
        self: Any, settings: Any = None, now: Any = None
    ) -> tuple[bool, str]:
        resolved = self.settings if settings is None else settings
        return bool(resolved.enabled), mod.TTL_STATE_OFF

    monkeypatch.setattr(mod.OutboundGate, "effective_enabled", _bare_read)
    assert enabled_now() is True, "摘调用点仍关得住 ⇒ 判据函数是死码"
    monkeypatch.undo()
    assert enabled_now() is False, "undo 后基线没复原 ⇒ 本自证的前提不可信"

    # ③ 摘告警消费：关闸仍成立，但坏沿不出声 ⇒ 观测腿单独承重（与①②不同判据）。
    issues: list[Any] = []
    monkeypatch.setattr(
        mod.OutboundGate, "_note_ttl_state", lambda self, state, settings: None
    )
    _ttl_gate(until=_TTL_PAST, sink=issues.append).decide(_request(), now=_TTL_NOW)
    assert issues == [], "摘掉告警消费仍有告警 ⇒ 本锁测的是别的东西"
    monkeypatch.undo()
    _ttl_gate(until=_TTL_PAST, sink=issues.append).decide(
        _request(request_id="req-after"), now=_TTL_NOW
    )
    assert [issue.kind for issue in issues] == ["outbound_gate_ttl_expired"]

    # ④ 把「不可解析」改回放行：写错的 TTL 被折成「无到期」⇒ 门永久开着。
    original_parse = mod.parse_gate_ttl

    def _fold_garbage_to_absent(value: object) -> Any:
        if str(value or "").strip() == _TTL_GARBAGE:
            return None
        return original_parse(value)

    monkeypatch.setattr(mod, "parse_gate_ttl", _fold_garbage_to_absent)
    assert _ttl_gate(until=_TTL_GARBAGE).enabled is True, (
        "把不可解析折成缺省后门仍关 ⇒ fail-closed 那条腿没被本判据管住"
    )
    monkeypatch.undo()
    assert _ttl_gate(until=_TTL_GARBAGE).enabled is False


def test_ttl_legs_locks_are_not_self_satisfying() -> None:
    """两把结构锁各自的注毒：内存改源码文本⇒必红（不落盘）。

    为什么还要这一节：`*_load_bearing` 注的是**运行时行为**，结构锁钉的是**源码形状**。
    「改回裸读但今天没配 TTL」那一形只有结构锁看得见，所以结构锁的牙也得单独验一次
    （否则它可能是一张贴在墙上的形状判据——项目失效形态册的「代理指标当结论」族）。
    """
    source = _gate_source()

    def decide_delegation(src: str) -> bool:
        tree = ast.parse(src)
        gate_class = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "OutboundGate"
        )
        node = _function_node(gate_class, "decide")
        assert node is not None
        return bool({"effective_enabled", "effective_gate_enabled"} & _called_names(node))

    assert decide_delegation(source) is True
    reverted = source.replace(
        "gate_on, _ttl_state = self.effective_enabled(settings, current)",
        "gate_on, _ttl_state = settings.enabled, TTL_STATE_OFF",
        1,
    )
    assert reverted != source, "注毒点消失（decide 的判据调用形态变了）⇒ 本自证已失明"
    assert decide_delegation(reverted) is False

    def kind_producers(src: str) -> set[str]:
        return _ttl_kind_producers(ast.parse(src))

    assert kind_producers(source) == {
        "KIND_GATE_TTL_EXPIRED",
        "KIND_GATE_TTL_INVALID",
    }
    silenced = source.replace(
        "kind = KIND_GATE_TTL_EXPIRED", 'kind = "outbound_gate_ttl_expired"', 1
    )
    assert silenced != source, "注毒点消失（到期那枚 kind 的引用形态变了）"
    assert "KIND_GATE_TTL_EXPIRED" not in kind_producers(silenced), (
        "摘掉告警消费后本锁仍认它有生产者 ⇒ 锁被 `__all__`/注释那类假命中糊住"
    )
