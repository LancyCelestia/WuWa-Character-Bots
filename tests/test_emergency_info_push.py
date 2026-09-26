"""WIRE-A2｜紧急域唯一投递触点 `service/push.py` + 施工图 §7.4 三把门里的两把。

覆盖分工（与既有锁的关系写清楚，防「同一条事实两把尺子」）：

- **结构锁 1/2**（施工图 §5-钉死③.3 点名给开工席的两条）：域内零裸 `queue.submit`、
  触闸点恰有一处。`tests/test_emergency_info_core.py` 锁 B 也在钉这件事，但它的
  ②段依赖**闸席 T6 白名单的 AST 提取**；本件只钉「域内自身」这一侧，两侧互为反证。
- **门 2（severity 载体，治 R-3）**：`SendRequest.priority` 必须是 `"P0".."P3"`
  字面量。这里不止钉字段值，还用**真闸**在 00:00–06:00 静默窗内跑一遍：
  P0 出 `allow`、把载体写成 `"normal"` 就出 `defer`＝漏报，方向性后果当场可见。
- **门 1（双钉一致性，治 R-1）**：根 `__init__.py` matcher 的 `priority` 与
  `ROUTE_RULES` 同 capability 的 `priority` 比对（只比 `block=True` 族）。
  紧急域两侧已由 WIRE-B3（装配席）落地为同值 44，故本件的门 1 = 「全族扫描 +
  一条紧急域正向锁 `test_emergency_info_double_pin_is_registered_and_equal`」；
  此前的「待接线登记」探测器（半接线抓形）语义已被正向锁的①②两条断言逐字接管，
  **没有为了让它现在绿而放宽任何断言**。
- **门 3（白名单整段化，治 R-2）** 落在 `tests/test_outbound_gate.py`（本波自有件），
  不在本文件重复。

全部离线：零网络、零 NoneBot、零 config、时钟一律注入。
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
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
    URGENT_LEVELS,
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import push
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    EMERGENCY_DEDUPE_PREFIX,
    build_emergency_dedupe_key,
    date_key_of,
    is_emergency_dedupe_key,
)
from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
DOMAIN_DIR = PLUGIN_ROOT / "domains" / "emergency_info"
ROOT_INIT = PLUGIN_ROOT / "__init__.py"
BASE_ROUTER = (
    PLUGIN_ROOT / "domains" / "chat_reply" / "runtime" / "base_router.py"
)

_NOON = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
_QUIET_NIGHT = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)


def _item(
    level: EmergencyLevel | None = EmergencyLevel.P0,
    *,
    item_id: str = "nmc-20260920-0001",
) -> EmergencyItem:
    """一条已过审的紧急条目（审核面归 A3，本件只吃它的产物形态）。"""
    return EmergencyItem(
        item_id=item_id,
        source_id="nmc",
        source_kind="nmc_alarm",
        external_id="0001",
        title="暴雨红色预警",
        body="预计 6 小时内降雨量超过 100 毫米。",
        url="https://example.invalid/alarm/0001",
        occurred_at=_NOON,
        fetched_at=_NOON,
        level=level,
        status=EmergencyStatus.APPROVED,
        credibility=0.9,
    )


def _group_target() -> push.EmergencyTarget:
    return push.EmergencyTarget(
        target_id="1108838060",
        target_scope=SessionType.GROUP,
        channel="qq",
        adapter="OneBot V11",
        bot_id="3865067623",
    )


class _FakeStore:
    """滑窗计数假 store（`SendStore` 三面，零落盘）。"""

    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        del subject_key, since_utc
        return 0

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        del subject_key, now_utc

    def prune(self, *, before_utc: datetime) -> int:
        del before_utc
        return 0


class _RecordingQueue:
    """只记账的队列替身：本席不许碰真队列，也不许被误当成旁路。"""

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


def _real_gate(*, now: datetime, enabled: bool = True) -> Any:
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


# ------------------------------------------------------------- 结构锁（§5-钉死③）


def _direct_submit_sites(root: Path) -> list[str]:
    """域内生产件里 `*queue*.submit(...)` 的直调点（绕闸）。"""
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "submit":
                continue
            if "queue" in ast.unparse(node.func.value).lower():
                offenders.append(f"{path.name}:{node.lineno}")
    return offenders


def test_emergency_domain_has_zero_direct_queue_submit() -> None:
    """唯一投递触点=中央闸：域内出现裸 `*queue*.submit(...)` 即红（与 T6 同向、互补）。"""
    assert DOMAIN_DIR.is_dir(), DOMAIN_DIR
    offenders = _direct_submit_sites(DOMAIN_DIR)
    assert offenders == [], f"紧急域绕过中央闸直调发送队列：{offenders}"


def test_emergency_domain_push_touchpoint_exists() -> None:
    """反证自锁：上一条在「域内零投递」时恒真 ⇒ 触点必须确实存在且**恰有一处**。

    缺了这条，域内一行投递代码都不写也能让上一条永远绿（施工图 §5-钉死③.3 原话）。
    """
    hits = [
        path.name
        for path in sorted(DOMAIN_DIR.rglob("*.py"))
        if "__pycache__" not in path.parts
        and "submit_active_push" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["push.py"], f"紧急域投递触点应恰有一处（实读：{hits}）"


# -------------------------------------------------- 门 2｜severity 载体（治 R-3）


@pytest.mark.parametrize("level", list(EmergencyLevel))
def test_send_request_priority_is_the_level_literal(level: EmergencyLevel) -> None:
    """四档各自的载体字面量必须是 `"P0".."P3"`（大写字面值，闸侧 `.upper()` 后比对）。"""
    request = push.build_emergency_send_request(
        _item(level), _group_target(), now=_NOON
    )
    assert request.priority == level.value
    assert request.priority == str(level.value)


@pytest.mark.parametrize("level", list(EmergencyLevel))
def test_deliver_emergency_carries_the_level_into_the_gate(level: EmergencyLevel) -> None:
    """经 `deliver_emergency` 走一遍：落到队列的那条请求的 priority 就是等级字面量。

    这里用真闸（关闭态＝透传），因此断的是「本席有没有把字段带过去」，
    不是闸的判断——闸的判断见下面两条静默窗用例。
    """
    queue = _RecordingQueue()
    verdict = push.deliver_emergency(
        queue, _real_gate(now=_NOON, enabled=False), _item(level), _group_target(), now=_NOON
    )
    assert verdict == "allow"
    assert len(queue.calls) == 1
    submitted, deliver_after = queue.calls[0]
    assert deliver_after is None
    assert submitted.priority == level.value
    assert submitted.capability_id == push.EMERGENCY_CAPABILITY_ID


def test_urgent_severity_vocabulary_is_shared_with_the_gate() -> None:
    """本域 URGENT_LEVELS 与闸的 DEFAULT_URGENT_SEVERITIES 必须是同一套词。

    字面量对不上（例如闸侧只认 `"urgent"`）时，`str(level.value)` 这个载体就是一条
    永不被读到的字符串：安静窗照旧把 P0 顺延，而所有单元测试仍然全绿。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        DEFAULT_URGENT_SEVERITIES,
    )

    mine = {str(level.value) for level in URGENT_LEVELS}
    assert mine == set(DEFAULT_URGENT_SEVERITIES), (
        f"紧急域 urgent 档 {sorted(mine)} 与闸侧 {list(DEFAULT_URGENT_SEVERITIES)} 不同源"
    )


def test_p0_passes_quiet_hours_but_a_normal_carrier_defers() -> None:
    """方向性锁（真闸 + 静默窗 00:00–06:00）：载体写对＝allow，写错＝defer＝漏报。

    这条就是 R-3 的现形：`priority` 漏传/写成现役族的 `"normal"` 时，P0 预警在夜里
    被当非紧急推到 06:00，不抛不记 degraded 不进告警。
    """
    gate = _real_gate(now=_QUIET_NIGHT)
    queue = _RecordingQueue()
    verdict = push.deliver_emergency(
        queue, gate, _item(EmergencyLevel.P0), _group_target(), now=_QUIET_NIGHT
    )
    assert verdict == "allow", "P0 在安静时间窗内被顺延＝漏报（载体没被闸认出来）"
    assert queue.calls[0][1] is None

    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    leaked = push.build_emergency_send_request(
        _item(EmergencyLevel.P0), _group_target(), now=_QUIET_NIGHT, priority="normal"
    )
    outcome = submit_active_push(
        _RecordingQueue(), leaked, gate, now=_QUIET_NIGHT, dedupe_family="daily"
    )
    assert outcome.verdict.action == "defer", (
        "把载体写成 \"normal\" 竟然也过了静默窗＝本锁断不到 R-3 的失败方向"
    )
    assert outcome.verdict.deliver_after is not None


def test_ungraded_item_skips_and_touches_nothing() -> None:
    """D-1：未定级 ⇒ `skip_ungraded`，不碰闸、不碰队列、不自称任何等级。"""
    queue = _RecordingQueue()
    gate = _real_gate(now=_NOON)
    verdict = push.deliver_emergency(
        queue, gate, _item(None), _group_target(), now=_NOON
    )
    assert verdict == push.SKIP_UNGRADED
    assert queue.calls == []


def test_ungraded_item_cannot_build_a_request() -> None:
    """建请求口同样拒未定级条目（`deliver_emergency` 之外的旁路也得撞墙）。"""
    with pytest.raises(ValueError, match="ungraded"):
        push.build_emergency_send_request(_item(None), _group_target(), now=_NOON)


# ------------------------------------------------ 键形同源（禁止第二套键形）


def test_keys_come_from_the_single_emergency_key_builder() -> None:
    """dedupe/cooldown 两键都必须出自 `build_emergency_dedupe_key`，且形状可核验。

    队列按整串做幂等：脏键与干净键各存一行＝重发（LOCK-AUDIT GAP-1）；
    `dedupe_key`/`cooldown_key` 空串则被 `SendRequest` 的 `field_validator` 直接拒。
    """
    item = _item(EmergencyLevel.P1)
    target = _group_target()
    request = push.build_emergency_send_request(item, target, now=_NOON)
    date_key = date_key_of(_NOON)
    assert request.dedupe_key == build_emergency_dedupe_key(
        target.channel, item.item_id, target.target_id, date_key=date_key
    )
    assert request.cooldown_key == build_emergency_dedupe_key(
        target.channel, item.item_id, target.target_id
    )
    assert is_emergency_dedupe_key(request.dedupe_key, require_date_key=True)
    assert is_emergency_dedupe_key(request.cooldown_key)
    assert request.dedupe_key.startswith(f"{EMERGENCY_DEDUPE_PREFIX}:")
    assert request.cooldown_key.strip() and request.dedupe_key.strip()


def test_daily_family_literal_equals_the_gate_constant() -> None:
    """`deliver_emergency` 的家族参数：AST 定位、字面量、且仍等于闸侧常量。

    注毒 M3 复验时发现**文本包含判定是空锁**：本文件散文里也写着
    `dedupe_family="daily"`，把真调用改成 `"once"` 文本判定照样绿（比没锁更坏）。
    改成 AST 后判到具体调用点；家族值刻意写字面量而非闸侧常量，是因为
    `tests/test_emergency_info_core.py` 锁 D 的静态判定只认字面量。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        DEDUPE_FAMILY_DAILY,
    )

    assert DEDUPE_FAMILY_DAILY == "daily"
    tree = ast.parse((DOMAIN_DIR / "service" / "push.py").read_text(encoding="utf-8"))
    entry = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "deliver_emergency"
    )
    touches = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "submit_active_push"
    ]
    assert len(touches) == 1, f"触闸调用点应恰有一处（实读 {len(touches)}）"
    family = next((kw for kw in touches[0].keywords if kw.arg == "dedupe_family"), None)
    assert family is not None and isinstance(family.value, ast.Constant), (
        "dedupe_family 必须是字面量常量：非字面量形态既过不了闸侧静态锁，"
        "也无法在本锁里被判定"
    )
    assert family.value.value == DEDUPE_FAMILY_DAILY, (
        f"投递家族={family.value.value!r}，闸侧 DEDUPE_FAMILY_DAILY={DEDUPE_FAMILY_DAILY!r}"
        "——改成 once 会让按日重投退化成永久不再投（漏发）"
    )
    keyed = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_emergency_dedupe_key"
    ]
    assert keyed and all(
        any(
            kw.arg == "date_key" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
            for kw in call.keywords
        )
        or len(call.args) >= 4
        for call in keyed
    ), "家族=daily 而建键没传 date_key ⇒ 闸侧五段强校验会把键判死（静默不发）"


def test_delivered_key_is_five_segment_when_family_is_daily() -> None:
    """家族与键段数同真同假（运行时侧）：daily ⇒ 五段带日期，绝不四段。"""
    queue = _RecordingQueue()
    push.deliver_emergency(
        queue, _real_gate(now=_NOON, enabled=False), _item(), _group_target(), now=_NOON
    )
    request = queue.calls[0][0]
    segments = request.dedupe_key.split(":")
    assert len(segments) == 5 and segments[4] == date_key_of(_NOON)


# ------------------------------------------ 门 3 之外的请求面必填项（13 项齐）


def test_send_request_required_surface_is_populated() -> None:
    """施工图 §4-面11 点名的必填面逐项非空、形态正确。"""
    request = push.build_emergency_send_request(_item(), _group_target(), now=_NOON)
    assert request.session_id == "group:1108838060"
    assert request.target_scope is SessionType.GROUP
    assert request.target_id == "1108838060"
    assert request.max_messages == 1
    assert request.send_policy.value == "queued"
    assert request.privacy_level.value == "group"
    assert request.persona_profile_id == "default"
    assert request.content.text_fallback.startswith("【红色预警】")
    assert request.content.risk_level.value in {"critical", "high", "medium", "low"}
    assert request.audit_tags == ["emergency_info", "daily"]


def test_group_target_privacy_and_private_fallback_shape() -> None:
    """退化形态（装配面手里只有裸 QQ 号）按私聊档出请求，不靠猜把群号当私聊。"""
    request = push.build_emergency_send_request(
        _item(), None, now=_NOON, channel="qq", target_id="3865067623"
    )
    assert request.target_scope is SessionType.PRIVATE
    assert request.session_id == "private:3865067623"
    assert request.privacy_level.value == "personal"
    assert request.content.privacy_level.value == "personal"


def test_illegal_key_parts_raise_instead_of_building_a_silent_key() -> None:
    """`item_id` 带冒号 ⇒ 建键当场抛，绝不产出一条闸会 skip 掉的静默键（漏报）。"""
    with pytest.raises(ValueError, match="illegal characters"):
        push.build_emergency_send_request(
            _item(item_id="bad:id"), _group_target(), now=_NOON
        )


# ---------------------------------------------- 门 1｜双钉一致性（治 R-1，现形）


def _root_block_true_matchers() -> tuple[dict[str, int], list[str]]:
    """根 `__init__.py` 里 `name = on_message(..., priority=N, block=True)` 的 N。

    被动旁路族（`block=False`，实测 priority 3–13）与中央判定序不是同一件事，
    按施工图 §7.4-1 的口径排除在外。第二个返回值是「block=True 但 priority 不是
    整数字面量」的名单——本门**不静默跳过**这类形态（跳过了就等于把锁放宽）。
    """
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    opaque: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        call = node.value
        if not isinstance(target, ast.Name) or not isinstance(call, ast.Call):
            continue
        func = call.func
        if not (isinstance(func, ast.Name) and func.id == "on_message"):
            continue
        keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        block = keywords.get("block")
        if not (isinstance(block, ast.Constant) and block.value is True):
            continue  # 被动旁路族（block=False / 未写 block）：不适用双钉口径
        priority = keywords.get("priority")
        if (
            isinstance(priority, ast.Constant)
            and isinstance(priority.value, int)
            and not isinstance(priority.value, bool)
        ):
            found[str(target.id)] = int(priority.value)
        else:
            opaque.append(f"{target.id}:{ast.unparse(priority) if priority else '缺省'}")
    return found, opaque


def _route_rule_priorities() -> dict[str, int]:
    """`ROUTE_RULES` 的 RouteKind 值 → priority（真身 import，不走垫片路径）。

    为什么按 `kind` 而不是 `capability_id` 与本席的 matcher 变量名对齐：实测
    `capability_id` 有一对共享（`base_router.py:579` `bot.moegirl`=41 与 `:601`
    `bot.moegirl`＝MOEGIRL_QUESTION=46，二次元问句族故意挂在同一能力名下），按
    capability 拼表会被后写条目盖掉，制造一条假 offender；`RouteKind` 值实测零重复，
    且与根面 matcher 变量名同形态（`weather`↔`RouteKind.WEATHER="weather"`）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        ROUTE_RULES,
    )

    seen: dict[str, int] = {}
    duplicated: list[str] = []
    for rule in ROUTE_RULES:
        kind = str(rule.kind.value)
        if kind in seen and seen[kind] != int(rule.priority):
            duplicated.append(f"{kind}:{seen[kind]}!={rule.priority}")
        seen[kind] = int(rule.priority)
    assert duplicated == [], f"RouteKind 重复且 priority 不一致（判定序不可复现）：{duplicated}"
    return seen


#: 根面 `block=True` 却对不上任何 RouteKind 的 matcher（**显式登记面**，不是放宽）。
#: 本门断言「实际未覆盖集 ⊆ 本表」且「本表每一项今天确实未覆盖」——新增一个对不上号
#: 的 matcher 会当场红，把本表任何一条修好接线也会红（要求同批删名）。
#: 逐条归属与可信度见 report §6（管理员命令族=设计如此；其余=命名漂移，未逐条核实）。
UNPINNABLE_MATCHERS: frozenset[str] = frozenset(
    {
        "cookie_admin",
        "file_export",
        "group_file_stats",
        "nickname_set",
        "group_info_matcher",
        "ignore_guide",
        "image_search",
        "natural",
        "subscribe_cmd",
        # ↓ 2026-09-26 十八项收尾波新装的两枚命令族（第 18 项书面同意入口 / 第 5 项宿主机状态）。
        # 它们**有** RouteKind  twin（`RouteKind.CONSENT="consent"`、`RouteKind.HOST_STATE="host_state"`），
        # 只是根面变量名取 `<kind>_matcher` 形态，与"变量名 == RouteKind 值"的实比惯例不合，
        # 所以落进未覆盖集。刻意不静默豁免：等值改由
        # `test_consent_and_host_state_double_pins_are_registered_and_equal` 逐枚钉死
        # （两侧都在位 + 两侧相等 + 值必须为 41），强度不低于实比——这条先例就是上面紧急域
        # 那枚 `_EMERGENCY_DOUBLE_PIN_PRIORITY` 的写法。为什么不直接改名进实比：
        # `tests/test_consent_command_surface.py:664` 的 AST 活性锁按 `endswith("consent_matcher")`
        # 取节，改名会打断装配可达性锁；改锁与改名谁先谁后由该件 owner 定，本波不动它。
        "consent_matcher",
        "host_state_matcher",
    }
)


def test_matcher_priority_equals_route_rule_priority_for_comparable_families() -> None:
    """既有全部可比对族的双钉一致性：matcher `priority` == RouteRule `priority`。

    覆盖判据=根 matcher 变量名 == `RouteKind` 值（现役 38 个 `block=True` matcher 里
    实测 29 对可比、零漂移）。覆盖不到的 9 条只能来自 `UNPINNABLE_MATCHERS` 登记面。
    """
    assert BASE_ROUTER.is_file(), BASE_ROUTER
    matchers, opaque = _root_block_true_matchers()
    rules = _route_rule_priorities()
    assert matchers and rules, "双钉两侧都读到了空集＝本锁在空转"
    assert opaque == [], f"block=True 但 priority 不是整数字面量，本锁判不动：{opaque}"
    compared: list[str] = []
    offenders: list[str] = []
    for kind, rule_priority in rules.items():
        if kind not in matchers:
            continue
        compared.append(kind)
        if matchers[kind] != rule_priority:
            offenders.append(f"{kind}: matcher={matchers[kind]} rule={rule_priority}")
    assert len(compared) >= 20, (
        f"双钉一致性只比到 {len(compared)} 对（{sorted(compared)}）——"
        "命名形态变了要同步本锁的判据，别让它悄悄空转"
    )
    assert offenders == [], (
        f"NoneBot matcher 与中央判定序的 priority 不一致（R-1）：{offenders}"
    )
    uncovered = set(matchers) - set(rules)
    assert uncovered <= set(UNPINNABLE_MATCHERS), (
        f"出现未登记的双钉盲区 matcher {sorted(uncovered - set(UNPINNABLE_MATCHERS))}："
        "要么补 RouteKind/改命名让它进入实比，要么在此登记并写明归属（不许静默扩表）"
    )
    stale = sorted(name for name in UNPINNABLE_MATCHERS if name not in uncovered)
    assert stale == [], f"登记面里的 {stale} 已能实比＝同批删名，别让登记变成永久豁免"



#: 紧急域双钉的唯一期望值（施工图 §4-面2③ + §4-面5c：RouteRule 与根 matcher 同为 44）。
_EMERGENCY_DOUBLE_PIN_PRIORITY = 44


def test_emergency_info_double_pin_is_registered_and_equal() -> None:
    """紧急域双钉**正向一致性锁**（WIRE-B3 把 A2 的半接线探测器转正）。

    落地后的现场：`ROUTE_RULES` 里 `RouteRule(RouteKind.EMERGENCY_INFO,
    "bot.emergency_info", 44, ...)`，根 `__init__.py` 里
    `emergency_info = on_message(rule=_is_emergency_info_event, priority=44, block=True)`。
    本例三件事：① 任一侧消失（半接线/回退）当场红并点名缺哪一侧；② 两侧值必须相等；
    ③ 相等的那个值必须是 44（只锁「两侧一致」不够——一起漂到 45 也是一致，而 45 会
    撞上 `natural`=45 的判定序，属实质行为变更）。杀伤力已注毒复验：把根 matcher 的
    44 改成 45 ⇒ 本例与上一条全族一致性锁同时红。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        ROUTE_RULES,
    )

    matchers, _opaque = _root_block_true_matchers()
    kinds = _route_rule_priorities()
    capabilities = {str(rule.capability_id) for rule in ROUTE_RULES}
    rule_side = "emergency_info" in kinds or "bot.emergency_info" in capabilities
    matcher_side = "emergency_info" in matchers
    assert rule_side, (
        "紧急域 RouteRule 侧不在位：中央判定序收不到「紧急信息」，"
        "根 matcher 空转（施工图 §6 步骤 6 被摘）"
    )
    assert matcher_side, (
        "紧急域根 matcher 侧不在位：RouteRule 判出来了但没人接 ⇒ 消息坠地"
        "（施工图 §6 步骤 5 回退）"
    )
    assert matchers["emergency_info"] == kinds["emergency_info"], (
        f"紧急域双钉不一致：matcher={matchers['emergency_info']} "
        f"rule={kinds['emergency_info']}（NoneBot 侧与中央判定序必须同值）"
    )
    assert kinds["emergency_info"] == _EMERGENCY_DOUBLE_PIN_PRIORITY, (
        f"紧急域 priority 期望 {_EMERGENCY_DOUBLE_PIN_PRIORITY}，"
        f"实得 matcher={matchers['emergency_info']} rule={kinds['emergency_info']}："
        "两侧一起漂也是漂（45 会撞 natural 的判定序）"
    )


#: 书面同意 / 宿主机状态两族的双钉唯一期望值（2026-09-26 现算：RouteRule 与根 matcher 同为 41）。
_CONSENT_HOST_DOUBLE_PIN_PRIORITY = 41

#: (登记名, RouteKind 值, 族名) —— 命名不合"变量名==kind 值"惯例，故全族循环比不到，逐枚点名。
_DOUBLE_PIN_BY_NAME: tuple[tuple[str, str, str], ...] = (
    ("consent_matcher", "consent", "书面同意"),
    ("host_state_matcher", "host_state", "宿主机状态"),
)


def test_consent_and_host_state_double_pins_are_registered_and_equal() -> None:
    """`UNPINNABLE_MATCHERS` 新增两枚的**配套正向等值锁**（登记不等于豁免）。

    全族一致性锁按「根 matcher 变量名 == RouteKind 值」配对，这两枚变量带 `_matcher`
    后缀进不了循环 ⇒ 若只登记不补锁，priority 从此没人管（R-1 的双钉一致性对它们失效）。
    本例逐枚做三件事，与紧急域那枚同形：① 任一侧消失当场红并点名缺哪一侧
    （RouteRule 在而 matcher 没装 = 中央判出来了没人接、消息坠地；反之 = 根面空转）；
    ② 两侧值必须相等；③ 相等的那枚必须是 41 —— 只锁「两侧一致」不够，一起漂到 45
    也是一致，而 41 是这两族与 `bot.moegirl` 等同档的现役判定序位置，漂移属实质行为变更。
    """
    matchers, _opaque = _root_block_true_matchers()
    kinds = _route_rule_priorities()
    for matcher_name, kind, family in _DOUBLE_PIN_BY_NAME:
        assert kind in kinds, (
            f"{family} 的 RouteRule 侧不在位（kind={kind}）：中央判定序收不到该族，"
            f"根 matcher `{matcher_name}` 空转"
        )
        assert matcher_name in matchers, (
            f"{family} 的根 matcher 侧不在位（{matcher_name}）：RouteRule 判出来了但没人接"
            "⇒ 消息坠地"
        )
        assert matchers[matcher_name] == kinds[kind], (
            f"{family} 双钉不一致：matcher={matchers[matcher_name]} rule={kinds[kind]}"
            "（NoneBot 侧与中央判定序必须同值）"
        )
        assert kinds[kind] == _CONSENT_HOST_DOUBLE_PIN_PRIORITY, (
            f"{family} priority 期望 {_CONSENT_HOST_DOUBLE_PIN_PRIORITY}，"
            f"实得 matcher={matchers[matcher_name]} rule={kinds[kind]}："
            "两侧一起漂也是漂"
        )
        # 登记面必须与实比状态同步：这两枚若哪天改名进实比，本表的行要同批删。
        assert matcher_name in UNPINNABLE_MATCHERS, (
            f"{family} 的 {matcher_name} 仍进不了实比，却不在登记面 —— 反向漏登"
        )
