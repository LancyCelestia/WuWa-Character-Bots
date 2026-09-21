"""Wave 3 前三域（notes / reminder / daily_assist）调用点门 + 端到端离线等值（SEAT-V2 席）。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §4 Wave3 / §4.3。
沿用 U2 席的 ``tests/test_orchestration_callsite_single.py`` **结构判据函数**（组合复用，
不复制第二套扫描器——铁律 1「禁第三套」），把同一不变量套到本波三域真身符号：
``build_notes_capability`` / ``build_reminder_capability`` / ``build_daily_assist_capability``。

三层执法（与 v1 门同型）：
- **活性判据（真树）**：三域直呼/invoker 两面 == 评审过的 wave3 ledger，漂移当场红。
  实况：``bot.notes`` 唯一生产执行点是 ``domains/schedule/capabilities/reminder.py:356``
  （root 无独立 notes matcher）——descriptor 未在册，切换块在 SEAT-V2 §6-A 待原子批；
  ``bot.reminder`` / ``bot.daily_assist`` 的反应面执行经 root 泛型执行器
  ``_run_simple_capability``(:8216, 直呼发生在 :8230 的 ``capability_factory(config)``)，
  参数化调用对符号级结构判据不可见——该盲区如实登记于 SEAT-V2 §2-⑥，Wave 4.1 统一处置。
- **注毒自证（合成树）**：新增直呼点⇒红；第二 invoker 点⇒红；半迁移⇒红。
- **端到端离线等值 + 机制自证**：fixture 现场注册 descriptor+adapter 的**局部**
  ``CapabilityInvoker``（不碰 default_invoker 单例、不给生产加旁路），invoke 产出的
  呈现契约 model_dump 与直呼真身逐字段相等；摘 descriptor（局部 invoker 不注册）⇒
  UNAVAILABLE 不崩且旧直调路径仍全绿（「未接线→回落」判据）。

全离线：SQLite/收件箱文件全部 tmp_path，零网络、零消息发送。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 复用 v1 门的结构判据与不变量检查器（同目录顶层导入，pytest 已把 tests/ 放上 sys.path）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as v1gate

_PKG_ROOT = v1gate._PKG_ROOT
_SHELL_REL = "runtime/capability_protocols.py"  # descriptor 落地后壳内 adapter 不算「域直呼」（同 v1 门）

# 真身 builder → (能力 id, 定义文件不计直呼)
_TRACKED_V2: dict[str, tuple[str, str]] = {
    "build_notes_capability": ("bot.notes", "domains/notes/capabilities/notes.py"),
    "build_reminder_capability": ("bot.reminder", "domains/schedule/capabilities/reminder.py"),
    "build_daily_assist_capability": (
        "bot.daily_assist",
        "domains/assistant/daily/capabilities/daily_assist.py",
    ),
}
_ALL_CAPS = sorted({cap for cap, _ in _TRACKED_V2.values()})


# ---------------------------------------------------------------------------
# 扫描器（组合复用 v1 门的结构判据；可喂真树或合成树）
# ---------------------------------------------------------------------------
def scan(index: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    direct: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS}
    invoker: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS}
    for rel, src in index.items():
        if rel == _SHELL_REL:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for symbol, (cap, def_file) in _TRACKED_V2.items():
            if rel != def_file and symbol in src and v1gate._execution_calls(tree, symbol):
                direct[cap].add(rel)
        for cid in v1gate._invoker_cids(tree):
            if cid in invoker:
                invoker[cid].add(rel)
    return direct, invoker


def _load_real_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sym in text for sym in _TRACKED_V2) or "capability_id=" in text:
            index[rel] = text
    return index


# ---------------------------------------------------------------------------
# wave3 前三域 ledger（2026-09-21 SEAT-V2 实测登记）
# ---------------------------------------------------------------------------
# bot.notes：唯一执行直呼=reminder.py:356（本席独占面，待 descriptor 原子批翻 invoker，
# 切换块 SEAT-V2 §6-A）。bot.reminder/bot.daily_assist：结构判据直呼面为空（执行在
# root 泛型执行器 :8230，参数化不可见，Wave 4.1 统一处置）。
KNOWN_DIRECT_ALLOWLIST_V2: dict[str, set[str]] = {
    "bot.notes": {"domains/schedule/capabilities/reminder.py"},
    "bot.reminder": set(),
    "bot.daily_assist": set(),
}
# 通电判据=该能力直呼清零：三能力均未通电（shell 无 ASSIST descriptor）。
WIRED_V2: set[str] = set()
# 域内 invoker 点登记（root :8230 的泛型调用非 capability_id 字面量，不在本面）。
KNOWN_INVOKER_SITES_V2: dict[str, set[str]] = {}


def test_real_tree_matches_wave3_ledger() -> None:
    """活性判据：真树直呼/invoker == 评审过的 wave3 ledger，任一漂移当场红。"""
    direct, invoker = scan(_load_real_index())
    assert direct == KNOWN_DIRECT_ALLOWLIST_V2, (
        f"直呼面漂移：实得 {direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST_V2}"
    )
    actual_invoker = {cap: mods for cap, mods in invoker.items() if mods}
    assert actual_invoker == KNOWN_INVOKER_SITES_V2, (
        f"invoker 调用点漂移：实得 {actual_invoker} ≠ 登记 {KNOWN_INVOKER_SITES_V2}"
    )
    assert v1gate.check_invariants(
        direct, invoker, wired=WIRED_V2, allowlist=KNOWN_DIRECT_ALLOWLIST_V2
    ) == []


# ---------------------------------------------------------------------------
# 注毒自证（合成树，非真树；证明每条不变量真的会红）
# ---------------------------------------------------------------------------
def _poison_direct(mod: str, symbol: str) -> dict[str, str]:
    return {mod: f"from x import {symbol}\ndef f(cfg):\n    return {symbol}(cfg)\n"}


def test_poison_new_direct_site_is_red() -> None:
    """注毒①：allowlist 之外新增一处 build_notes_capability 直呼点 → 「未登记直呼点」红。"""
    direct, invoker = scan(
        _poison_direct("domains/food/capabilities/sneaky.py", "build_notes_capability")
    )
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_V2, allowlist=KNOWN_DIRECT_ALLOWLIST_V2
    )
    assert any("未登记直呼点" in s and "bot.notes" in s for s in v), f"注毒未被拦：{v}"


def test_poison_second_invoker_site_is_red() -> None:
    """注毒②：两个模块各 invoke bot.reminder → 「第二调用点」红。"""
    src = "def f():\n    default_invoker().invoke(CapabilityRequest(capability_id='bot.reminder'))\n"
    direct, invoker = scan({"m1.py": src, "m2.py": src})
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_V2, allowlist=KNOWN_DIRECT_ALLOWLIST_V2
    )
    assert any("第二调用点" in s and "bot.reminder" in s for s in v), f"第二 invoker 点未被拦：{v}"


def test_poison_half_migration_is_red() -> None:
    """注毒③：同模块既直呼 build_daily_assist_capability 又 invoke 它 → 「半迁移」红。"""
    src = (
        "from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist"
        " import build_daily_assist_capability\n"
        "def f(cfg):\n"
        "    build_daily_assist_capability(cfg)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='bot.daily_assist'))\n"
    )
    direct, invoker = scan({"domains/schedule/half.py": src})
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_V2, allowlist=KNOWN_DIRECT_ALLOWLIST_V2
    )
    assert any("半迁移" in s and "bot.daily_assist" in s for s in v), f"半迁移未被拦：{v}"


def test_wired_invariant_binds_after_migration() -> None:
    """「已通电=直呼清零」判据的杀伤力：同样 ledger 若 bot.notes 标通电，直呼点存在即红。"""
    direct, invoker = scan(_load_real_index())
    v = v1gate.check_invariants(
        direct, invoker, wired={"bot.notes"}, allowlist=KNOWN_DIRECT_ALLOWLIST_V2
    )
    assert any("已通电却仍直呼真身" in s for s in v), (
        f"通电判据无牙（descriptor 落地当笔须靠它拦住忘切 :356）：{v}"
    )


# ---------------------------------------------------------------------------
# 机制自证：摘 descriptor → UNAVAILABLE 不崩；旧直调路径照旧全绿
# ---------------------------------------------------------------------------
def _local_invoker(
    *,
    with_descriptor: bool,
    builder,
    capability_id: str,
    with_handler: bool = True,
):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityDescriptor,
        CapabilityFamily,
        CapabilityInvoker,
        CapabilityRegistry,
        HandlerRegistry,
        InvocationResult,
        InvocationStatus,
    )

    reg = CapabilityRegistry()
    hreg = HandlerRegistry()
    if with_descriptor:
        # family 借用既有枚举成员：ASSIST 成员在 shell 文件里（V1 独占），
        # 本 fixture 不私造枚举成员（Enum 也不可 monkeypatch），语义见 SEAT-V2 §5a-1。
        reg.register(
            CapabilityDescriptor(
                capability_id=capability_id,
                family=CapabilityFamily.SEARCH,
                title=capability_id,
                input_protocol="payload.message",
                output_protocol=f"data[{PRESENTATION_DATA_KEY}]",
            )
        )

    def _handle(request) -> InvocationResult:
        presented = builder(request.context.get("config"))(
            request.payload["message"], request.context.get("decision")
        )
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via="wave3_fixture",
        )

    if with_handler:
        hreg.register(capability_id, _handle)
    return CapabilityInvoker(registry=reg, handlers=hreg)


def test_descriptor_missing_falls_back_failed_and_legacy_works(tmp_path) -> None:
    """摘 descriptor ⇒ invoke 诚实终态不崩（实况：**descriptor 缺失=FAILED**
    「未登记能力」，而 descriptor 在册+handler 缺位才是 UNAVAILABLE——两种回落形态
    都带诚实 detail、都不携带呈现载荷）且旧直呼路径零损伤。

    这同时是「本席为什么生产码零切换」的证据：descriptor 未在册时若先翻
    reminder.py:356，笔记指令面当场断——必须与 §5a descriptor 落地原子同笔。
    """
    from plugins.bot_unified_runtime.domains.notes.capabilities.notes import (
        build_notes_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
    )

    inv = _local_invoker(
        with_descriptor=False, builder=build_notes_capability, capability_id="bot.notes"
    )
    result = inv.invoke(
        CapabilityRequest(
            capability_id="bot.notes",
            payload={"message": _notes_message("笔记列表")},
            principal="u1",
            roles=("user",),
            context={"config": _notes_config(tmp_path / "no-desc")},
        )
    )
    assert result.status is InvocationStatus.FAILED  # 未登记能力：诚实拒绝而非静默
    assert result.detail.strip(), "失败终态必须带诚实说明"
    assert "presentation_result" not in result.data
    # 第二形态：descriptor 在册、handler 未接线 → UNAVAILABLE（生产据此回落旧直调）。
    inv2 = _local_invoker(
        with_descriptor=True,
        with_handler=False,
        builder=build_notes_capability,
        capability_id="bot.notes",
    )
    result2 = inv2.invoke(
        CapabilityRequest(
            capability_id="bot.notes",
            payload={"message": _notes_message("笔记列表")},
            principal="u1",
            roles=("user",),
            context={"config": _notes_config(tmp_path / "no-handler")},
        )
    )
    assert result2.status is InvocationStatus.UNAVAILABLE
    assert result2.detail.strip() and "presentation_result" not in result2.data
    # 回落自证：旧直调路径仍正常产出（不押 id 字面——笔记空清单分支的归因 id
    # 属域内既有语义，等值判据由上面两路 dump 全等承担）。
    legacy = build_notes_capability(_notes_config(tmp_path / "legacy"))(_notes_message("笔记列表"), None)
    assert legacy.body


# ---------------------------------------------------------------------------
# 端到端逐字段等值（每能力一条；fixture 局部 invoker，零生产旁路）
# ---------------------------------------------------------------------------
def _notes_config(root: Path) -> SimpleNamespace:
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        bot_notes_enabled=True,
        bot_notes_db_path=str(root / "n.sqlite3"),
        bot_reminder_db_path=str(root / "r.sqlite3"),
    )


def _notes_message(text: str):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1", raw_segments=[],
    )


def _assert_envelope_equals_handler(invoker_result, direct_result) -> None:
    """等值判据：信封里装的呈现契约与直呼真身返回值**逐字段**全等（返回体/文案/限额
    语义/audit_tags/send_policy 一字不改——接入只换调用点，不改产出）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationStatus,
    )

    assert invoker_result.status in (InvocationStatus.OK, InvocationStatus.FALLBACK_OK)
    payload = invoker_result.data[PRESENTATION_DATA_KEY]
    assert isinstance(payload, dict)
    invoked_dump = dict(payload)
    direct_dump = direct_result.model_dump()
    # 唯一豁免：debug_id=每次构造的随机对账 id（错误卡关联用），跨构造必不同；
    # 其余字段（含文案/audit_tags/send_policy）逐字段全等。
    inv_dbg, dir_dbg = invoked_dump.pop("debug_id", None), direct_dump.pop("debug_id", None)
    assert inv_dbg and dir_dbg, "两路都必须照常产出 debug_id 对账字段"
    assert invoked_dump == direct_dump, "经 invoker 的呈现契约与直呼真身不逐字段等值"


def test_e2e_bot_notes_invoker_equals_direct(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.notes.capabilities.notes import (
        build_notes_capability,
    )
    from plugins.bot_unified_runtime.domains.notes.store.notes_store import (
        reset_stores_for_tests,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    reset_stores_for_tests()
    msg = _notes_message("笔记列表")
    inv = _local_invoker(
        with_descriptor=True, builder=build_notes_capability, capability_id="bot.notes"
    )
    invoked = inv.invoke(
        CapabilityRequest(
            capability_id="bot.notes", payload={"message": msg},
            principal="u1", roles=("user",),
            context={"config": _notes_config(tmp_path / "via-invoker")},
        )
    )
    direct = build_notes_capability(_notes_config(tmp_path / "via-direct"))(msg, None)
    reset_stores_for_tests()
    _assert_envelope_equals_handler(invoked, direct)


def test_e2e_bot_reminder_invoker_equals_direct(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
        build_reminder_capability,
        clear_checkoff_pending_for_tests,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    def _cfg(root: Path) -> SimpleNamespace:
        return _notes_config(root)  # reminder 读 bot_reminder_db_path + bot_notes_enabled

    clear_checkoff_pending_for_tests()
    msg = _notes_message("提醒列表")
    inv = _local_invoker(
        with_descriptor=True, builder=build_reminder_capability, capability_id="bot.reminder"
    )
    invoked = inv.invoke(
        CapabilityRequest(
            capability_id="bot.reminder", payload={"message": msg},
            principal="u1", roles=("user",),
            context={"config": _cfg(tmp_path / "via-invoker")},
        )
    )
    direct = build_reminder_capability(_cfg(tmp_path / "via-direct"))(msg, None)
    assert "目前没有待办的提醒" in direct.body  # 双路同打这条确定性分支
    _assert_envelope_equals_handler(invoked, direct)


def test_e2e_bot_daily_assist_invoker_equals_direct(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist as da_store
    from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist import (
        build_daily_assist_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    def _cfg(root: Path) -> SimpleNamespace:
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(bot_daily_assist_dir=str(root))

    # 文案池按进程级游标轮换（跨调用非确定）——钉成首变体后两路同构可比。
    monkeypatch.setattr(
        da_store,
        "pick_variant",
        lambda key, variants, **kw: (variants[0].format(**kw) if kw else variants[0]),
    )
    msg = _notes_message("收件箱")
    inv = _local_invoker(
        with_descriptor=True,
        builder=build_daily_assist_capability,
        capability_id="bot.daily_assist",
    )
    invoked = inv.invoke(
        CapabilityRequest(
            capability_id="bot.daily_assist", payload={"message": msg},
            principal="u1", roles=("user",),
            context={"config": _cfg(tmp_path / "via-invoker")},
        )
    )
    direct = build_daily_assist_capability(_cfg(tmp_path / "via-direct"))(msg, None)
    _assert_envelope_equals_handler(invoked, direct)
