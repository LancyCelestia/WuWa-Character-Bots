"""creation 缺位告警的跨进程露头账本（S-CREATION-GAP-LEDGER，2026-09-28）。

现场：09-28 一天约 10 次 bot 重启 ⇒ 同一件「预留位没接后端、不是故障」的缺位报了约
7 波，每波 2 个收件人 ×（文本 + 诊断卡）＝4 条，合计约 28 条出站私聊。原因不是门写错
（`_not_configured_fired` 的语义就是「每进程实例一次」，文案也已改准），而是**那枚门只
活在进程内存里**——重启即失忆。

本文件锁三层：
① 账本本体（ops/monitor 层）：记时、到期、坏盘 fail-open 偏向**多报**、原子落盘不留 tmp；
② creation 侧接线：注入账本后跨进程收敛；**未注入 ⇒ 行为与改动前逐字相同**（每进程一次）；
   通道集合变化算新缺位、重新露头（陈旧不粘滞）；投递失败绝不记账（宁可晚到不可静默丢件）；
③ 派生覆盖锁：本域硬编码的键式（不许 import ops 层）必须与运维层 ``gap_key`` 同式。

全离线：SQLite/网络零触碰，盘只写 tmp_path（铁律 6）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_health_alert as RHA
from plugins.bot_unified_runtime.domains.ops.monitor import (
    reserved_gap_ledger as LEDGER,
)


class _Clock:
    """可推进的假钟：本文件不许靠 sleep 过 TTL。"""

    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ledger(tmp_path: Path, clock: _Clock) -> LEDGER.ReservedGapLedger:
    return LEDGER.ReservedGapLedger(tmp_path / "gap.json", ttl_seconds=3600, clock=clock)


# ------------------------------------------------------------------
# ① 账本本体
# ------------------------------------------------------------------


def test_ledger_recalls_reported_key_within_window(tmp_path: Path) -> None:
    clock = _Clock()
    ledger = _ledger(tmp_path, clock)
    assert not ledger.already_reported("k")
    ledger.mark_reported("k")
    clock.advance(3599)
    assert ledger.already_reported("k"), "窗口内必须认得这笔露头"


def test_ledger_expires_so_gap_can_surface_again(tmp_path: Path) -> None:
    """超窗后必须重新露头——缺位不许永久隐身，这是「少刷屏」的对价上限。"""
    clock = _Clock()
    ledger = _ledger(tmp_path, clock)
    ledger.mark_reported("k")
    clock.advance(3601)
    assert not ledger.already_reported("k")


def test_ledger_survives_instance_recreation(tmp_path: Path) -> None:
    """跨「进程」的唯一证据＝换一枚全新实例（同路径）仍认得这笔。"""
    clock = _Clock()
    _ledger(tmp_path, clock).mark_reported("k")
    assert _ledger(tmp_path, clock).already_reported("k")


def test_ledger_reads_garbage_as_never_reported(tmp_path: Path) -> None:
    """坏盘口径＝当作没报过：宁可多敲一次运维，也不因账本坏了让缺位静默隐身。"""
    path = tmp_path / "gap.json"
    path.write_text("{ 这不是合法 json", encoding="utf-8")
    ledger = LEDGER.ReservedGapLedger(path, ttl_seconds=3600, clock=_Clock())
    assert not ledger.already_reported("k")


def test_ledger_write_leaves_no_temp_file_and_is_atomically_readable(tmp_path: Path) -> None:
    clock = _Clock()
    ledger = _ledger(tmp_path, clock)
    ledger.mark_reported("a")
    ledger.mark_reported("b")
    assert not list(tmp_path.glob("gap.json.tmp-*")), "临时文件必须被 replace 吃掉"
    entries = json.loads((tmp_path / "gap.json").read_text(encoding="utf-8"))["entries"]
    assert sorted(entries) == ["a", "b"]


def test_ledger_forget_clears_one_or_all(tmp_path: Path) -> None:
    clock = _Clock()
    ledger = _ledger(tmp_path, clock)
    ledger.mark_reported("a")
    ledger.mark_reported("b")
    ledger.forget("a")
    assert not ledger.already_reported("a")
    assert ledger.already_reported("b")
    ledger.forget()
    assert not ledger.already_reported("b")


def test_gap_key_is_order_insensitive_and_set_sensitive() -> None:
    a = LEDGER.gap_key("creation", "creation_not_configured", ["creation.tts", "creation.image"])
    b = LEDGER.gap_key("creation", "creation_not_configured", ["creation.image"])
    assert a != b, "通道集合变了必须算新的缺位（陈旧不粘滞）"
    assert a == LEDGER.gap_key("creation", "creation_not_configured", ["creation.image", "creation.tts"])


# ------------------------------------------------------------------
# ② creation 侧接线
# ------------------------------------------------------------------


_UNCONFIGURED = SimpleNamespace(bot_creation_image_provider="", bot_creation_tts_provider="")


def _both_channels_missing(config: SimpleNamespace) -> tuple[str, ...]:
    return RHA.not_configured_channels(config)


@pytest.fixture()
def _clean(tmp_path: Path):
    RHA.reset_state()
    RHA.install_not_configured_ledger(None)
    RHA.install_reserved_alert_sink(None)
    yield RHA
    RHA.reset_state()
    RHA.install_not_configured_ledger(None)
    RHA.install_reserved_alert_sink(None)


def _patrol_with(tmp_path: Path, clock: _Clock) -> list:
    """接好 sink + 账本，返回投递记录表（巡检两口都走它）。"""
    delivered: list = []
    RHA.install_reserved_alert_sink(delivered.append)
    RHA.install_not_configured_ledger(_ledger(tmp_path, clock))
    return delivered


def test_key_formula_matches_ops_ledger(_clean: None) -> None:
    """派生覆盖锁：本域不许 import ops 层，于是键式各写一份——这份必须与真身同式。"""
    channels = _both_channels_missing(_UNCONFIGURED)
    assert channels, "替身 config 应判出两条通道都未配置"
    assert RHA.gap_ledger_key(channels) == LEDGER.gap_key(
        "creation", RHA._NOT_CONFIGURED_KIND, list(channels)
    )


def test_second_process_does_not_refire_same_gap(_clean: None, tmp_path: Path) -> None:
    """注入账本后：模拟重启（reset_state 清进程内存），同一无配状态不再重报。"""
    clock = _Clock()
    delivered = _patrol_with(tmp_path, clock)
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 1
    assert len(delivered) == 1

    RHA.reset_state()  # ＝重启：内存里的 fired 门失忆，账本还在
    assert RHA.has_alert_sink()
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 0
    assert len(delivered) == 1, "跨进程账本没起作用 ⇒ 又要刷一波"


def test_without_ledger_legacy_per_process_semantics_hold(_clean: None) -> None:
    """未注入账本 ⇒ 与改动前逐字相同：每进程一次，重启后再来一次。"""
    delivered: list = []
    RHA.install_reserved_alert_sink(delivered.append)
    assert not RHA.has_not_configured_ledger()
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 1
    RHA.reset_state()
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 1
    assert len(delivered) == 2, "没接账本却不再重报＝偷改既有口径"


def test_ledger_not_marked_when_delivery_fails(_clean: None, tmp_path: Path) -> None:
    """sink 抛错 ⇒ 不记账（宁可晚到，不可静默丢件）；修好后下一轮仍能露头。"""
    clock = _Clock()
    delivered: list = []
    fails = {"left": 1}

    def _sink(issue: object) -> None:
        if fails["left"]:
            fails["left"] -= 1
            raise RuntimeError("告警链坏了这一次")
        delivered.append(issue)

    ledger = _ledger(tmp_path, clock)
    RHA.install_reserved_alert_sink(_sink)
    RHA.install_not_configured_ledger(ledger)
    key = RHA.gap_ledger_key(_both_channels_missing(_UNCONFIGURED))
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 0, "投失败必须报 0"
    assert not ledger.already_reported(key), "投递没成功就记账＝把缺位永久隐身"

    fails["left"] = 0
    assert RHA.patrol_reserved_health(_UNCONFIGURED) == 1, "件还在桶里，修好即投"
    assert ledger.already_reported(key)
    assert len(delivered) == 1


def test_changed_channel_set_surfaces_again(_clean: None, tmp_path: Path) -> None:
    """接上绘画、只剩语音 ⇒ 键不同 ⇒ 重新武装露头一次（陈旧不粘滞）。

    只用武装/投递两口，不走 patrol：`check_reserved_channels` 那条「要而不得」腿
    会因「填了 provider 却派不出适配器」另投一件，混进计数就认不出本锁在锁什么。
    """
    clock = _Clock()
    delivered: list = []
    ledger = _ledger(tmp_path, clock)
    RHA.install_reserved_alert_sink(delivered.append)
    RHA.install_not_configured_ledger(ledger)

    assert RHA.check_and_arm_not_configured(_UNCONFIGURED) is True
    assert RHA.flush_not_configured_issue() == 1

    RHA.reset_state()  # ＝重启
    half = SimpleNamespace(bot_creation_image_provider="openai", bot_creation_tts_provider="")
    assert _both_channels_missing(half) == ("creation.tts",), "替身应只剩语音缺位"
    assert RHA.check_and_arm_not_configured(half) is True, "通道集合变了却被旧键压住＝粘滞"
    assert RHA.flush_not_configured_issue() == 1
    assert len(delivered) == 2


# ------------------------------------------------------------------
# ③ 装配接线锁：`_register_nonebot_handlers` 无法离线单测 ⇒ 按既有 AST 切口锁
#    （本仓对该函数的接线存在性一律用 AST 断言，见 tests/test_production_wiring.py
#     模块注；少了这一锁，账本就会「件落了、口没接」地表成「修好了」——
#     台账里这类"零接线"反例不止一次。）
# ------------------------------------------------------------------

_ROOT_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)


def _calls_in_root_assembly(function_name: str) -> set[str]:
    tree = ast.parse(_ROOT_SOURCE.read_text(encoding="utf-8"))
    holder = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    assert holder is not None, f"root 里找不到 {function_name}（装配函数改名要先惊动本锁）"
    names: set[str] = set()
    for node in ast.walk(holder):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_root_assembly_wires_the_gap_ledger() -> None:
    """装配层必须真把账本注进 creation 域，且给的是运维层那枚真身而不是自建替身。"""
    calls = _calls_in_root_assembly("_register_nonebot_handlers")
    assert {"install_reserved_alert_sink", "install_execution_presence_probe"} <= calls, (
        "同一装配块的两枚既有注入都不见了 ⇒ 本锁的落点被挪动，先核对再改"
    )
    assert "install_not_configured_ledger" in calls, (
        "缺位露头账本没接进装配 ⇒ 跨进程去重在生产里是死代码"
    )
    assert "ReservedGapLedger" in calls, "接的不是 ops/monitor 那枚真身"
