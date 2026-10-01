"""S-FIX-QUIET-T3 锁 | quiet_breach_levels「源级表 ∩ 族级地板」取交语义四态锁。

病灶（审计票 SEAT-FIX-ATK-WXEMG §T3「双死腿」，主代理裁定＝取交语义）：
`bot_emergency_info_quiet_breach_levels` 键未声明 ⇒ 用户值进不来（腿一）；
root `deliver_emergency` 不传 `breach_levels` ⇒ 值到不了判据（腿二）。
而单独落根线的回退风险在 `grading.may_breach_quiet_window` 的显式腿语义
＝「只看这张表、不查族级地板」——直用会把族级地板架空（`global_disaster`
只认红档的族被 P1 穿窗＝静默窗行为变更）。

本席已落域内取交腿（`grading.may_breach_quiet_window_intersects_floor` ＋
`push.should_hold_for_quiet_window` ② 腿改走它）；root 实参与 config 键声明
两腿是禁写面，diff 备在
`.superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-QUIET-T3.md` §待主代理落盘。

本锁四态（全部函数级直调，不经 root job——root 腿未落盘不影响行为面证明）：
① 源级表含 P1 + 族级地板只认红 ⇒ P1 **不**穿窗（取交拦得住架空回退）；
② 两边都含 ⇒ 穿窗（缺省 P0,P1 全落地板内＝与今天一致）；
③ 源级空表 ⇒ 一切不穿窗（配窄只能更安静），同时族级单独判（None）维持现状；
④ 未配置（None）⇒ 与既有族级地板判据逐字节等值（现网实况一寸不动）。

外加：
- 判别力注毒自证（内存重放 `grading.py` 源码，零写树——先例
  `tests/test_emergency_grading_family_legality.py:277 _rebuilt`）：
  把取交腿注毒成「只看这张表」或「无视源级表」，①/③ 判据当场翻转，
  证明本锁红得了；
- root 接线 AST 锁：现盘 `skip`（文案指名「待主代理落盘后转绿」，先例
  `tests/test_emergency_target_key_segment_lock.py:321`），并在内存副本上
  验讫「打上待落盘 diff 即转真」的判别力（现盘 False／打补丁副本 True）。

全部离线：零网络、零 NoneBot、零 config、时钟一律注入；假队列/真闸形态抄
`tests/test_emergency_info_taxonomy.py` §C 与 `test_emergency_target_key_segment_lock.py`。
"""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import grading, push
from plugins.bot_unified_runtime.domains.emergency_info.service.push import (
    EmergencyTarget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_NOON = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
#: 静默窗（00:00–06:00 UTC）内的一刻，窗事实抄既有锁件注入口径，不自建第二套。
_NIGHT = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)

PATCH_POINTER = (
    ".superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-QUIET-T3.md §待主代理落盘"
)


def _item(**overrides: Any) -> EmergencyItem:
    """字段齐全的最小合法条目（形态抄 `test_emergency_info_taxonomy.py:83 _item`）。"""
    data: dict[str, Any] = {
        "item_id": "t3lock-0001",
        "source_id": "nmc",
        "source_kind": "weather_alarm",
        "external_id": "ext-t3",
        "title": "台风红色预警",
        "body": "",
        "url": "",
        "color_label": "红色",
        "occurred_at": _NIGHT - timedelta(hours=1),
        "fetched_at": _NIGHT,
        "credibility": 0.9,
    }
    data.update(overrides)
    built = build_emergency_item(data)
    assert built is not None, "夹具自身不合法，用例结论无意义"
    return built.model_copy(update={"status": EmergencyStatus.APPROVED})


def _gdacs_orange() -> EmergencyItem:
    """global_disaster 族橙档：族级地板 {P0} 把它挡在窗外的现行实况样本。"""
    return _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="野火",
        color_label="橙色",
        level=EmergencyLevel.P1,
    )


def _gdacs_red() -> EmergencyItem:
    return _gdacs_orange().model_copy(
        update={"level": EmergencyLevel.P0, "color_label": "红色", "title": "野火（红）"}
    )


def _typhoon_red() -> EmergencyItem:
    """meteo 族红档：地板 {P0,P1} 与源级缺省 {P0,P1} 的交集成员。"""
    return _item(
        category_id="typhoon", title="台风红色预警", color_label="红色",
        level=EmergencyLevel.P0,
    )


def _typhoon_orange() -> EmergencyItem:
    return _item(
        category_id="typhoon", title="台风橙色预警", color_label="橙色",
        level=EmergencyLevel.P1,
    )


class _NullStore:
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
        self.requests: list[Any] = []

    def submit(self, request: Any, deliver_after: Any = None) -> Any:
        from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
            DeliveryReceipt,
            ReceiptState,
        )

        del deliver_after
        self.requests.append(request)
        return DeliveryReceipt(
            request_id=request.request_id, state=ReceiptState.QUEUED, transport="onebot"
        )


def _real_gate(
    *, now: datetime, enabled: bool = True, window: tuple[str, str] = ("00:00", "06:00")
) -> Any:
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(
        OutboundGateSettings(enabled=enabled),
        quiet_settings=QuietHoursSettings(
            enabled=True,
            start_time=window[0],
            end_time=window[1],
            timezone_name="UTC",
            session_types=["group", "private"],
        ),
        store=_NullStore(),
        clock=lambda: now,
        audit_logger=InMemoryAuditLogger(),
        issue_sink=None,
    )


def _hold(item: EmergencyItem, *, breach: Any, gate: Any = None, now: datetime = _NIGHT):
    return push.should_hold_for_quiet_window(
        item,
        gate if gate is not None else _real_gate(now=now),
        now=now,
        target_scope="group",
        breach_levels=breach,
    )


# ===================================================== 态①|源级含 P1 抬不动族级地板


def test_state1_source_table_cannot_lift_family_floor() -> None:
    """global_disaster 地板＝{P0}；源级表给足 {P0,P1} 也不得让橙档穿窗（回退风险钉死）。"""
    orange = _gdacs_orange()
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            orange, EmergencyLevel.P1, source_levels=["P0", "P1"]
        )
        is False
    )
    assert _hold(orange, breach=["P0", "P1"]) is True


def test_state1_lock_anchors_on_untouched_raw_override_leg() -> None:
    """对照锚：旧显式腿语义一寸未动（`allowed_levels` 仍＝只看这张表）。

    这正是取交腿必须存在的原因——直用显式腿，上一用例的橙档就会穿窗。
    本用例同时是对「禁止放宽/篡改既有断言」的现场证词：既有件
    `test_emergency_info_taxonomy.py:508-511` 依赖的语义在这里原样可复核。
    """
    orange = _gdacs_orange()
    assert (
        grading.may_breach_quiet_window(orange, EmergencyLevel.P1, allowed_levels=["P0", "P1"])
        is True
    )
    assert grading.may_breach_quiet_window(orange, EmergencyLevel.P1) is False


# ============================================================ 态②|两边都含＝穿窗


def test_state2_intersection_member_breaches() -> None:
    """P0 ∈ 地板 ∧ P0 ∈ 源级表 ⇒ 够格穿窗：判据压不住、投递不压。"""
    red = _gdacs_red()
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            red, EmergencyLevel.P0, source_levels=["P0", "P1"]
        )
        is True
    )
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            _typhoon_orange(), EmergencyLevel.P1, source_levels=["P0", "P1"]
        )
        is True
    )
    gate = _real_gate(now=_NIGHT)
    assert _hold(red, breach=["P0", "P1"], gate=gate) is False
    assert _hold(_typhoon_orange(), breach=["P0", "P1"], gate=gate) is False


def test_state2_delivery_surface_end_to_end() -> None:
    """投递面实证（仍不经 root）：窗内红档带源级表 ⇒ allow 投出；橙档 gdacs ⇒ 压住。"""
    queue = _RecordingQueue()
    gate = _real_gate(now=_NIGHT)
    target = EmergencyTarget(target_id="1108838060", channel="qq")
    verdict = push.deliver_emergency(
        queue, gate, _gdacs_red(), target, now=_NIGHT, breach_levels=["P0", "P1"]
    )
    assert verdict == "allow" and len(queue.requests) == 1
    verdict = push.deliver_emergency(
        queue, gate, _gdacs_orange(), target, now=_NIGHT, breach_levels=["P0", "P1"]
    )
    assert verdict == push.SKIP_QUIET_HOURS and len(queue.requests) == 1


# ==================================================== 态③|源级空表＝一切不穿窗


def test_state3_empty_source_table_silences_everything() -> None:
    """空表⇒一切不穿窗（配窄了只能更安静）：连地板允许的红档也压住。"""
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            _typhoon_red(), EmergencyLevel.P0, source_levels=[]
        )
        is False
    )
    assert _hold(_typhoon_red(), breach=[]) is True
    assert _hold(_gdacs_red(), breach=[]) is True


def test_state3_family_only_path_keeps_current_state() -> None:
    """同一批条目源级腿缺席（None）⇒ 族级单独判维持现状：红档照常穿窗、不压。"""
    gate = _real_gate(now=_NIGHT)
    assert _hold(_typhoon_red(), breach=None, gate=gate) is False
    assert _hold(_gdacs_red(), breach=None, gate=gate) is False
    # 而橙档 gdacs 在 None 腿下也和现状逐字相同（被地板压住）。
    assert _hold(_gdacs_orange(), breach=None, gate=gate) is True


# ==================================================== 态④|未配置＝逐字节等于现状

_CORPUS = [_typhoon_red(), _typhoon_orange(), _gdacs_red(), _gdacs_orange()]


@pytest.mark.parametrize("item", _CORPUS, ids=lambda x: f"{x.category_id}-{x.level.value}")
def test_state4_none_source_table_is_byte_identical_to_family_floor(item: EmergencyItem) -> None:
    """`source_levels=None` ⇒ 合成腿与既有族级地板判据（现网真身）逐条等值。"""
    level = item.level
    assert (
        grading.may_breach_quiet_window_intersects_floor(item, level, source_levels=None)
        == grading.may_breach_quiet_window(item, level)
    )


@pytest.mark.parametrize("item", _CORPUS, ids=lambda x: f"{x.category_id}-{x.level.value}")
@pytest.mark.parametrize("scope", ["group", "private"])
def test_state4_hold_path_none_equals_legacy_expression(item: EmergencyItem, scope: str) -> None:
    """push ② 腿改道后，`breach_levels=None` 的 hold 结论与旧式表达逐条等值。

    旧式表达＝`_gate_urgent ∧ ¬grading.may_breach_quiet_window(…, None) ∧ 在窗`
    ——直接调既有被锁的原始函数复演旧判据，新判据必须处处同值。
    """
    gate = _real_gate(now=_NIGHT)
    legacy = (
        str(item.level.value).upper() in push._gate_urgent_levels(gate)
        and not grading.may_breach_quiet_window(item, item.level)
        and push._quiet_window_active(gate, _NIGHT, scope)
    )
    assert push.should_hold_for_quiet_window(
        item, gate, now=_NIGHT, target_scope=scope, breach_levels=None
    ) == legacy


def test_state4_default_config_never_widens() -> None:
    """结构证词：键缺省表 {P0,P1} 对**每一族**取交都＝该族地板原样 ⇒ 三腿落齐当天
    行为与现状逐字节相同（票面 §T3-3 回退风险的正面消解）。缺省表取自能力层快照
    真身 `DEFAULT_QUIET_BREACH_LEVELS`，不抄第二份。"""
    from plugins.bot_unified_runtime.domains.emergency_info.capabilities.emergency_info import (
        DEFAULT_QUIET_BREACH_LEVELS,
    )
    from plugins.bot_unified_runtime.domains.emergency_info.service import (
        alert_taxonomy as taxonomy,
    )

    default_table = sorted(DEFAULT_QUIET_BREACH_LEVELS)
    assert set(default_table) == {"P0", "P1"}
    for spec in taxonomy.families():
        for level in (EmergencyLevel.P0, EmergencyLevel.P1, EmergencyLevel.P2, EmergencyLevel.P3):
            # 地板成员缺省表必含（wake_levels ⊆ {P0,P1}），取交不收窄掉任何现状成员。
            if level in spec.wake_levels:
                assert level.value in default_table, f"{spec.family_id} 地板成员被缺省表收窄"


# ======================================================== 注毒自证（内存重放，零写树）

_GRADING_SOURCE = Path(grading.__file__).resolve().read_text(encoding="utf-8")

# 注毒锚：取交腿真身源码字面（唯一性由 _rebuilt 现算核验，锚漂即 raise）。
_INTERSECT_FLOOR_LEG = (
    "    if not _taxonomy.may_breach_quiet_window(_taxonomy.category_of_item(item), level):\n"
    "        return False\n"
)
_INTERSECT_SOURCE_LEG = (
    "    wanted = {str(raw).strip().upper() for raw in source_levels if str(raw).strip()}\n"
    "    return level.value in wanted\n"
)


def _rebuilt(mutations: list[tuple[str, str]], tag: str) -> ModuleType:
    """把 grading.py 源码按注毒表改松后在内存重放编译（不写任何源码树文件）。"""
    source = _GRADING_SOURCE
    for old, new in mutations:
        assert source.count(old) == 1, f"注毒锚点在现源码出现 {source.count(old)} 次：{tag}"
        source = source.replace(old, new)
    module = ModuleType(f"grading_poison_{tag}")
    # dataclasses 经 __module__ 回找命名空间需要 sys.modules 注册（首版装置自伤教训，
    # 见 test_emergency_grading_family_legality.py:284-287 同注）。
    sys.modules[module.__name__] = module
    exec(compile(source, f"<grading-poison:{tag}>", "exec"), module.__dict__)  # noqa: S102
    return module


def test_poison_harness_control_matches_production() -> None:
    """装置自检：零替换重放与生产模块逐字同值（否则「注毒变红」是装置自己坏）。"""
    control = _rebuilt([], "control")
    for item in _CORPUS:
        for table in (None, [], ["P0", "P1"], ["p1", " P0 "]):
            assert control.may_breach_quiet_window_intersects_floor(
                item, item.level, source_levels=table
            ) == grading.may_breach_quiet_window_intersects_floor(
                item, item.level, source_levels=table
            )


def test_poison_raw_override_leg_flips_state1() -> None:
    """注毒①：把取交腿拆回「只看这张表」（删地板腿）⇒ 态① 判据当场翻转。

    证明本席锁红得了：若实现席把取交写成直用显式腿，`test_state1_*` 必红。
    """
    poison = _rebuilt([(_INTERSECT_FLOOR_LEG, "")], "raw_override")
    assert (
        poison.may_breach_quiet_window_intersects_floor(
            _gdacs_orange(), EmergencyLevel.P1, source_levels=["P0", "P1"]
        )
        is True
    ), "注毒未翻转判据＝装置失效，本锁的判别力宣称作废"
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            _gdacs_orange(), EmergencyLevel.P1, source_levels=["P0", "P1"]
        )
        is False
    )


def test_poison_ignoring_source_table_flips_state3() -> None:
    """注毒②：让源级表形同虚设（删表腿＝一切走地板）⇒ 态③ 空表判据翻转。"""
    poison = _rebuilt([(_INTERSECT_SOURCE_LEG, "    return True\n")], "ignore_table")
    assert (
        poison.may_breach_quiet_window_intersects_floor(
            _typhoon_red(), EmergencyLevel.P0, source_levels=[]
        )
        is True
    ), "注毒未翻转判据＝装置失效，本锁的判别力宣称作废"
    assert (
        grading.may_breach_quiet_window_intersects_floor(
            _typhoon_red(), EmergencyLevel.P0, source_levels=[]
        )
        is False
    )


# ================================================ root 接线 AST 锁（2026-09-27 主代理已落盘，skip 臂留作回潮兜底）

_ROOT_DIFF_BEFORE = (
    "                    verdict = deliver_emergency(\n"
    "                        send_queue, gate, graded, target, now=now\n"
    "                    )\n"
)
_ROOT_DIFF_AFTER = (
    "                    verdict = deliver_emergency(\n"
    "                        send_queue, gate, graded, target, now=now,\n"
    "                        breach_levels=sorted(source.quiet_breach_levels),\n"
    "                    )\n"
)


def _deliver_callsites(tree: ast.Module) -> list[ast.Call]:
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "deliver_emergency"
        ):
            out.append(node)
    return out


def _breach_wired_in_source(src: str) -> bool:
    """判据（纯函数，供现盘 skip 与副本转绿双向验证）：装配 job 内每一处
    `deliver_emergency` 调用都带 `breach_levels=` 关键字实参，且实参读
    `source.quiet_breach_levels`（搬运自快照真身，不是第二份缺省）。"""
    tree = ast.parse(src)
    calls = _deliver_callsites(tree)
    if not calls:
        raise AssertionError("全文件未见 deliver_emergency 调用（接线面被删除？请人工复核）")
    job = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_emergency_info_collect_job"
        ),
        None,
    )
    if job is None:
        raise AssertionError("root 装配函数 _emergency_info_collect_job 不存在（文件被重排？）")
    job_calls = [
        node
        for node in ast.walk(job)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "deliver_emergency"
    ]
    if not job_calls:
        raise AssertionError("装配 job 内未见 deliver_emergency 调用（接线面被改动？请人工复核）")
    for call in job_calls:
        kw = next((k for k in call.keywords if k.arg == "breach_levels"), None)
        if kw is None:
            return False
        if not any(
            isinstance(x, ast.Attribute) and x.attr == "quiet_breach_levels"
            for x in ast.walk(kw.value)
        ):
            return False
    return True


def test_root_wiring_ast_lock() -> None:
    """root :10135 实参腿必须把源级表搬进 deliver_emergency（落盘后自动转真绿）。"""
    assert ROOT_INIT.is_file(), ROOT_INIT
    src = ROOT_INIT.read_text(encoding="utf-8")
    if not _breach_wired_in_source(src):
        pytest.skip(
            "待主代理落盘后转绿：root breach_levels 实参 diff（见 " + PATCH_POINTER + "）"
        )


def test_root_ast_predicate_discriminates_pending_diff() -> None:
    """AST 锁判别力自证（落盘后形态，内存副本，零写树）：
    现盘 root 已带 breach_levels 实参判 True（与上一锁同翻转，两处单边即装置漂移）；
    把实参腿摘回旧三行形态判 False——回潮当场被本锁抓住；
    只加空关键字的残缺变体（breach_levels=None）判 False——落错形态不会被锁放过。"""
    assert ROOT_INIT.is_file(), ROOT_INIT
    src = ROOT_INIT.read_text(encoding="utf-8")
    assert _breach_wired_in_source(src) is True, (
        "root 接线从盘上消失了——落盘被回退或被别席重写；按 " + PATCH_POINTER + " 的 diff 重落"
    )
    assert src.count(_ROOT_DIFF_AFTER) == 1, (
        "已落盘 diff 的三行锚点在现盘 root 不唯一/不存在：锚已漂移，本锁需按现盘重出"
    )
    reverted = src.replace(_ROOT_DIFF_AFTER, _ROOT_DIFF_BEFORE)
    assert _breach_wired_in_source(reverted) is False, (
        "摘掉 breach_levels 实参仍判 True：判据失去杀伤力（永真锁）"
    )
    half_wired = src.replace(
        _ROOT_DIFF_AFTER,
        "                    verdict = deliver_emergency(\n"
        "                        send_queue, gate, graded, target, now=now,\n"
        "                        breach_levels=None,\n"
        "                    )\n",
    )
    assert _breach_wired_in_source(half_wired) is False
