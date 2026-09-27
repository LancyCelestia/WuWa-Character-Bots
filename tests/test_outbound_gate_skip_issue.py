"""Q-G9② 反证回归：出站闸 skip 分支必须经 `note_issue` 出运营告警（闸吃条目不许无声）。

发现（`.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-QUEUE.md` Q-G9 第②项）：
键形门的 skip 分支原先只出 verdict、从不调 `note_issue` ⇒ 条目被闸吃掉、队列未触，
而运维在告警面上零观测（比 #46 的「脏键静默 skip」更黑一层：连 issue 通道都不响）。

修法口径（本文件锁死）：
- 开闸态每一发被 skip 的条目，经**既有** `note_issue` 单源恰好出一枚
  `outbound_gate_skipped`（复用 `_issue` 构造 ⇒ `retryable=False`、`stage=outbound_gate`）；
- **闸内零本地抑制**：折叠/300s 抑制归中央 `AdminAlertSuppression`（`ops/monitor/alerts.py`），
  与本件 store 降级分支同一先例——降级分支同样每判定一枚、不自建时间闸；
  禁第二本账/第二计数器（简报明禁，`_note_ttl_state` 头注同口径）。
- 关闭态是 passthrough、结构上不产生 skip ⇒ 零 issue（锁「关闭=现状字节级不动」
  这条硬约束不被观测面反向污染：没有 skip 就没有 skipped issue）。

issue 文本只留代号（kind/reason）与主体哈希，禁消息正文、禁原始键形、禁密钥形态
（对齐 AGENTS 铁律 3 的 redact 惯例与本件「日志与审计零正文」头注）。

全部离线：注入时钟 + 假队列 + 假 store，零网络零 NoneBot 运行时。

    BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \\
    python -m pytest tests/test_outbound_gate_skip_issue.py -q \\
        -p no:cacheprovider --basetemp=$TEMP/qg9
"""
from __future__ import annotations

import hashlib
from typing import Any

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

# 被闸吃掉的条目「该有的那枚」告警的机读身份（kind 短语与本件既有族同形：
# outbound_gate_degraded / outbound_gate_storm / …）。
KIND_SKIPPED_LITERALLY = "outbound_gate_skipped"
GATE_STAGE_LITERALLY = "outbound_gate"
REASON_LITERALLY = "dedupe_key_shape"

# 正文哨兵：一旦以任何形态出现在 issue 文本里即为泄漏（正文/键形只准留在队列侧事实）。
BODY_TEXT = "暴雨红色预警，请就近避雨。"
DIRTY_KEY = "emg:qq:only-three"  # 结构级脏：段数不足，出口洗段修不动 ⇒ 真 skip


def _utc(hour: int, minute: int) -> Any:
    from datetime import datetime, timezone

    return datetime(2026, 9, day=14, hour=hour, minute=minute, tzinfo=timezone.utc)


def _request(
    *,
    request_id: str = "req-qg9-1",
    dedupe_key: str = DIRTY_KEY,
    priority: str = "P2",
    target_scope: SessionType = SessionType.GROUP,
    target_id: str = "g-1",
    capability_id: str = "bot.emergency",
) -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id=f"{target_scope.value}:{target_id}",
        target_scope=target_scope,
        target_id=target_id,
        capability_id=capability_id,
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={"text": BODY_TEXT},
            text_fallback=BODY_TEXT,
            privacy_level=PrivacyLevel.PUBLIC,
            risk_level=RiskLevel.LOW,
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
    """假队列：只记录是否被触达（本文件判据＝skip 绝不触队列，与闸头注同口径）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, send_request: SendRequest, **kwargs: Any) -> DeliveryReceipt:
        self.calls.append(send_request.request_id)
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.QUEUED,
            transport="memory",
        )


class FakeStore:
    """假滑窗计数：不预置任何历史 ⇒ 限流门零干扰，判定只能落到键形门。"""

    def count_sends(self, subject_key: str, *, since_utc: Any) -> int:
        return 0

    def record_send(self, subject_key: str, *, now_utc: Any) -> None:
        return None

    def prune(self, *, before_utc: Any) -> int:
        return 0


def _expected_subject_hash(target_scope: SessionType, target_id: str) -> str:
    """独立复算主体哈希（LOCK-AUDIT 纪律：不拿被测实现算期望值再自比）。"""
    subject = f"{target_scope.value}:{target_id}"
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]


def _gate(
    *,
    enabled: bool,
    now: Any,
    issues: list[OperationalIssue],
) -> Any:
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(
        OutboundGateSettings(enabled=enabled),
        quiet_settings=QuietHoursSettings(enabled=False),
        store=FakeStore(),
        clock=lambda: now,
        audit_logger=None,
        issue_sink=issues.append,
    )


# ------------------------------------------------------------------ RED 主体
def test_enabled_skip_emits_exactly_one_skipped_issue() -> None:
    """开闸态：脏键被 skip ⇒ 队列零触达，且经 note_issue 恰好出一枚 skipped issue。

    现有实现（Q-G9② 修复前）此条必红：skip 分支只出 verdict、告警面全哑。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=True, now=now, issues=issues)
    queue = RecordingQueue()

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    outcome = submit_active_push(queue, _request(), gate, now=now)

    assert outcome.verdict.action == "skip"
    assert outcome.verdict.reason == REASON_LITERALLY
    assert queue.calls == []  # 拒绝绝不触队列（既有语义，不许被本修带动）
    kinds = [issue.kind for issue in issues]
    assert kinds == [KIND_SKIPPED_LITERALLY], (
        f"被闸吃掉的条目必须冒恰一枚 skipped 告警，实收 {kinds}"
    )


def test_decide_directly_also_emits_issue_for_assembly_side() -> None:
    """装配侧直调 `decide`（不经唯一出口）同样要有观测面——issue 接在判定处本身。

    这正是「接了 sink 也看不见」缺口的另一半：告警必须挂在 verdict 的出生点，
    而不是某一条投递路径的尾巴上。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=True, now=now, issues=issues)

    verdict = gate.decide(_request(), now=now)

    assert verdict.action == "skip"
    assert [issue.kind for issue in issues] == [KIND_SKIPPED_LITERALLY]


def test_each_skipped_entry_gets_its_own_issue_no_local_latch() -> None:
    """逐发记账：三发被吃＝三枚 issue，闸内不自建闩/计数器吞后续观测。

    反证「第二本账」方向锁：折叠归中央 `AdminAlertSuppression`（300s）与 sink 侧；
    闸若学 `_note_settings_unreadable` 的边沿闩把第 2、3 发静音，就是在本件里
    私搭第二套抑制——恰是简报与 `_note_ttl_state` 头注明令禁止的形态。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=True, now=now, issues=issues)
    queue = RecordingQueue()

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    for index in range(3):
        submit_active_push(
            queue,
            _request(request_id=f"req-qg9-{index}"),
            gate,
            now=now,
        )

    assert [issue.kind for issue in issues] == [KIND_SKIPPED_LITERALLY] * 3
    assert queue.calls == []


def test_skipped_issue_text_is_codes_only_no_body_no_key_no_secrets() -> None:
    """issue 文本纪律：只留代号（kind/stage/reason）与主体哈希，禁正文、禁原始键形。

    注毒位：若实现把正文/键串拼进 safe_summary，本条必红。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=True, now=now, issues=issues)

    gate.decide(_request(), now=now)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.stage == GATE_STAGE_LITERALLY
    assert issue.kind == KIND_SKIPPED_LITERALLY
    assert issue.retryable is False  # 键形被吃非瞬态故障，重投不解决问题
    assert REASON_LITERALLY in issue.safe_summary
    assert _expected_subject_hash(SessionType.GROUP, "g-1") in issue.safe_summary
    # 正文与原始键形不得以任何形态入文本（主体只准以哈希出现）。
    assert BODY_TEXT not in issue.safe_summary
    assert "暴雨" not in issue.safe_summary
    assert DIRTY_KEY not in issue.safe_summary
    assert "only-three" not in issue.safe_summary
    # 密钥形态零命中（redact 惯例的负样本面：出现即事故）。
    for marker in ("sk-", "BOT_", "Bearer", "C:/", "C:\\"):
        assert marker not in issue.safe_summary


def test_disabled_passthrough_emits_no_issue_and_never_skips() -> None:
    """关闸态：脏键直通队列（出口洗不动结构脏，但关态零判定）⇒ 零 skip 零 issue。

    锁「enabled=False = 现状字节级不动、零审计零观测副作用」：观测面接入不许
    反向把关闭态变成有行为差的状态。「闸关/开两态」在此对齐——关态无被吃条目，
    故无 issue 是正确行为；开态被吃必发（上文三条）。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=False, now=now, issues=issues)
    queue = RecordingQueue()

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    outcome = submit_active_push(queue, _request(), gate, now=now)

    assert outcome.verdict.action == "allow"
    assert outcome.verdict.reason == "disabled"
    assert queue.calls == ["req-qg9-1"]  # 关态照发（结构脏键原样落队列，现役语义）
    assert issues == []


def test_valid_key_allow_path_stays_issue_free() -> None:
    """反空跑：合规键放行不得顺带冒 issue（issue 只挂在 skip 出生点，不是全门广播）。

    若实现把 note_issue 撒在 decide 出口统一处，本条与上面几条一起才分得清方向。
    """
    now = _utc(12, 0)
    issues: list[OperationalIssue] = []
    gate = _gate(enabled=True, now=now, issues=issues)
    queue = RecordingQueue()

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    outcome = submit_active_push(
        queue,
        _request(request_id="req-qg9-ok", dedupe_key="emg:qq:i-1:g-1"),
        gate,
        now=now,
    )

    assert outcome.verdict.action == "allow"
    assert queue.calls == ["req-qg9-ok"]
    assert issues == []
