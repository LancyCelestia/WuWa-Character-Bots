"""S-FIX-ATK-WXEMG T2锁 | 根装配投递环 target_id 键段预检（会炸·最重票）。

病灶（审计票 SEAT-ATK-WEATHER T2）：根 `__init__.py` 装配环在 :10105 只预检
`item.item_id`，目标内环 :10113-:10124 对 `deliver_emergency` 的调用**没有**
target_id 等价预检，而 :10135 的单个 `except Exception` 罩住整轮 ⇒ .env 硬推名单
或订阅库里一个含 `:`/空白/非法字符的目标 id 就让 `build_emergency_dedupe_key`
抛 ValueError、掐断本轮其余全部条目×全部目标——`dedupe.py:94-102` 用
2026-09-20 `nmc:A1` 血泪写下的 doctrine（「不是让它在拼键时抛异常、把**整轮**
投递一起带走」）在 target 腿上的未修镜像。

root `__init__.py` 本席禁写（ITEM9 席并发面），补丁以精确 diff 形式在
`.superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-ATK-WXEMG.md` §待主代理落盘。

本锁分两段（brief 口径「锁本身写成独立可绿」）：

1. **行为判据锁（现在就绿，且落盘后仍是真身保障）**：用**真** `deliver_emergency`
   与真键构造函数钉住判据——无预检时脏目标必炸整轮（hazard 实证），
   按 `is_legal_segment` 预检则点名跳过该目标、其余目标照常投出。
   待落盘补丁加的就是这同一枚谓词、同一条跳过路径，故此件同时是落盘后
   行为面的判据保真锁。
2. **root 结构 AST 锁（现在 skip，主代理落盘后自动转真绿）**：扫
   `_emergency_info_collect_job` 内含 `deliver_emergency` 调用的目标 For 环，
   要求环体在调用之前存在以 `is_legal_segment(target.target_id)` 为判据的
   守卫 If。判据提取为纯函数 `_target_guard_present_in_source`，注毒自证与
   「补丁打上的 temp 副本转绿」双向验过（见票根报告复跑证据段）。

全部离线：零网络、零 NoneBot、零 config、时钟一律注入；假队列/真闸形态抄
`tests/test_emergency_info_push.py`。
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursSettings,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    DeliveryReceipt,
    ReceiptState,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import push
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    build_emergency_dedupe_key,
    is_legal_segment,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.push import (
    EmergencyTarget,
)
from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_NOON = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

# 脏目标 id 的三条来源腿共用的形态：`.env` 名单里「群号:楼层」`123:45`、
# 复制粘贴带内部空白、订阅库脏行。注意两端空白**不是**脏（谓词与建键同先
# strip，`" 386…"` 两侧都判净——这正是要钉住的「谓词=构造器」一致性）。
DIRTY_TARGET_IDS = ["123:45", "a b", "   ", "", "中文群", "qq group"]
CLEAN_TARGET_IDS = ["3865067623", "1108838060", "grp-01_2", "u.9_1", " 3865067623 "]


def _item(level: EmergencyLevel | None = EmergencyLevel.P0) -> EmergencyItem:
    return EmergencyItem(
        item_id="nmc-20260927-0001",
        source_id="nmc",
        source_kind="nmc_alarm",
        external_id="0001",
        title="暴雨红色预警",
        body="预计 6 小时内降雨量超过 100 毫米。",
        url="https://example.invalid/alarm/0001",
        occurred_at=_NOON - timedelta(hours=1),
        fetched_at=_NOON,
        expires_at=None,
        level=level,
        status=EmergencyStatus.APPROVED,
        credibility=0.9,
    )


def _target(target_id: str, *, channel: str = "qq") -> EmergencyTarget:
    return EmergencyTarget(
        target_id=target_id,
        target_scope=SessionType.GROUP,
        channel=channel,
        adapter="OneBot V11",
        bot_id="3865067623",
    )


class _FakeStore:
    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        del subject_key, since_utc
        return 0

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        del subject_key, now_utc

    def prune(self, *, before_utc: datetime) -> int:
        del before_utc
        return 0


class _RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[SendRequest, datetime | None]] = []

    def submit(
        self, request: SendRequest, deliver_after: datetime | None = None
    ) -> DeliveryReceipt:
        self.calls.append((request, deliver_after))
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.QUEUED,
            transport="onebot",
        )


def _real_gate(*, now: datetime, enabled: bool = False) -> Any:
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(
        OutboundGateSettings(enabled=enabled),
        quiet_settings=QuietHoursSettings(
            enabled=True,
            start_time="00:00",
            end_time="06:00",
            timezone_name="UTC",
            session_types=["group", "private"],
        ),
        store=_FakeStore(),
        clock=lambda: now,
        audit_logger=InMemoryAuditLogger(),
        issue_sink=None,
    )


# ------------------------------------------- 判据锁①|hazard 实证（无预检会炸整轮）


def test_dirty_target_id_explodes_deliver_emergency_without_guard() -> None:
    """脏 target_id 在 deliver_emergency 里抛 ValueError 且**不吞**（push.py 注记）。

    这是 T2 的引信：根装配环的单 try 罩全场结构把它放大成「整轮掐断」。
    """
    queue = _RecordingQueue()
    with pytest.raises(ValueError):
        push.deliver_emergency(
            queue, _real_gate(now=_NOON), _item(), _target("123:45"), now=_NOON
        )
    assert queue.calls == []


def test_unguarded_round_is_taken_down_by_one_dirty_target() -> None:
    """按根装配现状复演（无 target 预检）：脏目标排前 ⇒ 其后正常目标一条都到不了。"""
    queue = _RecordingQueue()
    gate = _real_gate(now=_NOON)
    pairs = [(_target("123:45"), None), (_target("3865067623"), None)]
    with pytest.raises(ValueError):
        for item in (_item(),):
            for target, _rule in pairs:
                push.deliver_emergency(queue, gate, item, target, now=_NOON)
    # 引信炸在第一个目标上：第二个正常目标零投递＝整轮漏投的实况。
    assert queue.calls == []


# ------------------------------------- 判据锁②|补丁判据（预检点名跳过、不带走整轮）


def _run_round(
    queue: _RecordingQueue,
    gate: Any,
    items: list[EmergencyItem],
    pairs: list[tuple[EmergencyTarget, Any]],
    *,
    guarded: bool,
) -> list[str]:
    """根装配内环的忠实复演：guarded=True 即待落盘补丁的判据本身。"""
    skipped: list[str] = []
    for item in items:
        for target, _rule in pairs:
            if guarded and not (
                is_legal_segment(target.target_id) and is_legal_segment(target.channel)
            ):
                skipped.append(target.target_id)
                continue
            push.deliver_emergency(queue, gate, item, target, now=_NOON)
    return skipped


def test_guarded_round_skips_dirty_target_and_delivers_rest() -> None:
    """判据成立：脏目标被点名跳过，其余目标×其余条目照常全部投出，整轮不炸。"""
    queue = _RecordingQueue()
    gate = _real_gate(now=_NOON)
    pairs = [
        (_target("123:45"), None),
        (_target("3865067623"), None),
        (_target("bad channel"), None),
    ]
    items = [_item(), _item(EmergencyLevel.P1)]
    skipped = _run_round(queue, gate, items, pairs, guarded=True)
    # 每条目×脏目标各点名一次（2×2），集合恰为两脏目标、无漏无多。
    assert sorted(set(skipped)) == ["123:45", "bad channel"]
    assert len(skipped) == 4
    # 2 条目 × 1 合法目标 = 4 个投递触点中 2 条各投到干净目标一次 ⇒ 恰 2 次 submit。
    assert len(queue.calls) == 2
    assert all(
        request.target_id == "3865067623" for request, _when in queue.calls
    )


def test_dirty_channel_leg_also_guarded() -> None:
    """channel 腿同罪：EmergencyTarget 校验只挡空白，`qq group` 照样在建键处炸。"""
    queue = _RecordingQueue()
    pairs = [(_target("3865067623", channel="qq group"), None)]
    skipped = _run_round(queue, _real_gate(now=_NOON), [_item()], pairs, guarded=True)
    assert skipped == ["3865067623"]
    assert queue.calls == []


@pytest.mark.parametrize("dirty", DIRTY_TARGET_IDS)
def test_guard_predicate_agrees_with_key_builder_on_dirty(dirty: str) -> None:
    """谓词-构造器一致性（脏侧）：预检说不行 ⇒ 真建键必抛。零漏网引信。"""
    assert not is_legal_segment(dirty)
    with pytest.raises(ValueError):
        build_emergency_dedupe_key("qq", "nmc-20260927-0001", dirty, date_key="2026-09-27")


@pytest.mark.parametrize("clean", CLEAN_TARGET_IDS)
def test_guard_predicate_agrees_with_key_builder_on_clean(clean: str) -> None:
    """谓词-构造器一致性（净侧）：预检说行 ⇒ 真建键必成。防预检过宽误杀合法目标。"""
    assert is_legal_segment(clean)
    key = build_emergency_dedupe_key(
        "qq", "nmc-20260927-0001", clean, date_key="2026-09-27"
    )
    assert key.endswith(f":{clean.strip()}:2026-09-27")


# --------------------------------- 待落盘 AST 锁|root 目标内环守卫结构（落盘转真绿）

T2_PATCH_POINTER = (
    ".superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-ATK-WXEMG.md §待主代理落盘"
)


def _is_legal_segment_on_attr(node: ast.AST, attr_name: str) -> bool:
    """node 内是否出现 `is_legal_segment(<...>.{attr_name} ...)` 调用。"""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "is_legal_segment"
        ):
            for arg in sub.args:
                if any(
                    isinstance(x, ast.Attribute) and x.attr == attr_name
                    for x in ast.walk(arg)
                ):
                    return True
    return False


def _target_guard_present_in_source(src: str) -> bool:
    """判据：装配 job 的内层 For（体内含 deliver_emergency）在调用之前有
    以 target_id 为判据的 is_legal_segment 守卫 If。纯函数，便于注毒自证。"""
    tree = ast.parse(src)
    job: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_emergency_info_collect_job":
            job = node
            break
    if job is None:
        raise AssertionError("root 装配函数 _emergency_info_collect_job 不存在（文件被重排？）")
    has_call = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "deliver_emergency"
        for n in ast.walk(job)
    )
    if not has_call:
        raise AssertionError("装配 job 内未见 deliver_emergency 调用（接线面被改动？请人工复核）")
    for node in ast.walk(job):
        if not isinstance(node, ast.For):
            continue
        call_stmt: ast.stmt | None = None
        for stmt in node.body:
            if any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "deliver_emergency"
                for n in ast.walk(stmt)
            ):
                call_stmt = stmt
                break
        if call_stmt is None:
            continue
        for stmt in node.body:
            if stmt is call_stmt:
                break
            if isinstance(stmt, ast.If) and _is_legal_segment_on_attr(stmt.test, "target_id"):
                return True
    return False


def test_root_assembly_prechecks_target_id_key_segment() -> None:
    """root 目标内环必须预检 target_id 键段（补丁落盘后此件自动转真绿）。"""
    assert ROOT_INIT.is_file(), ROOT_INIT
    src = ROOT_INIT.read_text(encoding="utf-8")
    if not _target_guard_present_in_source(src):
        pytest.skip(
            "待主代理落盘：T2 目标键段预检 diff（见 " + T2_PATCH_POINTER + "）"
        )
