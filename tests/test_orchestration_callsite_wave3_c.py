"""Wave 3-C 常驻门：ops / music / divination 三域「禁第二调用点」+ 端到端等值（S-W3C 席）。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-a/D-b/D-d、
§4 Wave3、§5（主动投递不经 pipeline 是既定语义）、§7（禁第三套）。

三件事实本件执法：

1. **活性 ledger（真树）**——复用 Wave 1 门 ``test_orchestration_callsite_single`` 的
   *结构判据*（``_execution_calls``：赋值即用/裸调用=执行直呼，``*provider`` 关键字实参=注入）
   与 ``check_invariants`` 三条不变量，扫本三域 24 个 handler 真身符号的生产直呼点与
   invoker 调用点，登记式比对。组合而非复制：分类逻辑只有一份，被两波门共用。
2. **未通电现状如实钉死**——本三域 **零能力走 invoker**（``WIRED_W3C`` 为空集），
   全部直呼点集中在根 ``__init__.py``；同时钉住两个**结构性缺口**：
   ``bot.admin_alert`` / ``bot.error_report`` 在唯一表 ``CAPABILITY_DESCRIPTOR`` **整行缺失**
   （主动投递族无 gate/健康/审计归属），以及 ``CapabilityFamily`` 还没有
   OPS/MUSIC/DIVINATION 三个成员（descriptor「无家可归」）。
3. **端到端逐字段等值 + 注毒自证**——证明「接入不改行为」可判定，且每条不变量真的会红。

全离线：三域真身的网络/存储依赖全部以确定性替身注入，零真实 I/O、零消息发送。
"""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 复用 Wave 1 门的判据（tests/ 非包：按路径装载，不依赖 pytest 的 sys.path 注入顺序）
# ---------------------------------------------------------------------------
_V1_PATH = Path(__file__).resolve().parent / "test_orchestration_callsite_single.py"
_spec = importlib.util.spec_from_file_location("_gate_v1", _V1_PATH)
assert _spec is not None and _spec.loader is not None
_gate_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate_v1)

_PKG_ROOT = _gate_v1._PKG_ROOT  # plugins/bot_unified_runtime
_SHELL_REL = _gate_v1._SHELL_REL  # 受控适配器不算直呼（同一份豁免口径）
_execution_calls = _gate_v1._execution_calls
_invoker_cids = _gate_v1._invoker_cids
check_invariants = _gate_v1.check_invariants

# ---------------------------------------------------------------------------
# 本三域追踪表：handler 真身符号 → capability_id（呈现契约上盖的 id）
# 只收「每消息执行的 capability 构造器」；装配/记账助手（build_diagnostics_store、
# build_runtime_diagnostic 产 RuntimeDiagnostic 非 CapabilityResult）刻意不入表，
# 它们是层 1 的旁挂记录件，不是 D-b 语义下的「能力执行入口」。
# ---------------------------------------------------------------------------
_TRACKED_W3C: dict[str, str] = {
    # music（域内直调 handler，不走根泛型执行器）
    "build_music_capability": "bot.music",
    "build_music_mode_result": "bot.music_mode",
    # divination（根侧闭包体内直呼 ⇒ 结构门可见，与泛型执行器不可见点不同）
    "build_divination_capability": "bot.divination",
    # ops / admin 查询面（debug.py 14 条）
    "build_receipt_query_result": "bot.receipt",
    "build_audit_query_result": "bot.audit",
    "build_recent_query_result": "bot.recent",
    "build_queue_query_result": "bot.queue",
    "build_roles_query_result": "bot.roles",
    "build_persona_query_result": "bot.persona",
    "build_runtime_control_result": "bot.control",
    "build_history_clear_result": "bot.history",
    "build_context_query_result": "bot.context",
    "build_config_query_result": "bot.config",
    "build_readiness_query_result": "bot.readiness",
    "build_dialogue_query_result": "bot.dialogue",
    "build_llm_query_result": "bot.llm",
    "build_llm_setup_query_result": "bot.setup.llm",
    # ops / admin 其余面
    "build_logs_query_result": "bot.logs",
    "build_runtime_admin_result": "bot.runtime",
    "build_session_identity_admin_result": "bot.identity",
    "build_quirk_admin_result": "bot.quirk",
    "build_alert_check_result": "bot.alert",
    "build_feature_control_result": "bot.runtime",  # 同 id 二真身：见 test_presentation_id_collision_*
    # ops / 诊断
    "build_why_result": "bot.why",
}

#: 各真身的定义文件（同文件内的自用组合不算「第二执行入口」，与 Wave 1 门同口径）。
_DEF_FILES_W3C: dict[str, set[str]] = {
    "build_music_capability": {"domains/music/capabilities/music.py"},
    "build_music_mode_result": {"domains/music/capabilities/music.py"},
    "build_divination_capability": {"domains/divination/capabilities/divination.py"},
    **{
        symbol: {"domains/ops/admin/debug.py"}
        for symbol in (
            "build_receipt_query_result",
            "build_audit_query_result",
            "build_recent_query_result",
            "build_queue_query_result",
            "build_roles_query_result",
            "build_persona_query_result",
            "build_runtime_control_result",
            "build_history_clear_result",
            "build_context_query_result",
            "build_config_query_result",
            "build_readiness_query_result",
            "build_dialogue_query_result",
            "build_llm_query_result",
            "build_llm_setup_query_result",
        )
    },
    "build_logs_query_result": {"domains/ops/admin/runtime_logs.py"},
    "build_runtime_admin_result": {"domains/ops/admin/runtime_admin.py"},
    "build_session_identity_admin_result": {"domains/ops/admin/runtime_admin.py"},
    "build_quirk_admin_result": {"domains/ops/admin/runtime_admin.py"},
    "build_alert_check_result": {"domains/ops/admin/runtime_admin.py"},
    "build_feature_control_result": {"domains/ops/features/feature_control.py"},
    "build_why_result": {"domains/ops/smoke/diagnostics.py"},
}

#: 三域全部在册 capability_id（invoker 调用点归属用；同 id 多符号是既有事实，见碰撞锁）。
_ALL_CAPS_W3C: frozenset[str] = frozenset(_TRACKED_W3C.values())


def scan_w3c(index: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """与 Wave 1 门同判据，只换追踪表（组合：判据一份、覆盖面两处）。"""
    direct: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS_W3C}
    invoker: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS_W3C}
    for rel, src in index.items():
        if rel == _SHELL_REL:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for symbol, cap in _TRACKED_W3C.items():
            if rel not in _DEF_FILES_W3C[symbol] and symbol in src and _execution_calls(tree, symbol):
                direct[cap].add(rel)
        for cid in _invoker_cids(tree):
            if cid in invoker:
                invoker[cid].add(rel)
    return direct, invoker


def _load_real_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(symbol in text for symbol in _TRACKED_W3C) or "capability_id=" in text:
            index[rel] = text
    return index


# ---------------------------------------------------------------------------
# ① 活性 ledger：三域现况=全部直呼、零 invoker（本席未翻任何生产调用点）
# 登记式比对：新出现未登记的直呼/invoker 点当场红；登记点消失也红。
# ---------------------------------------------------------------------------
_ROOT = "__init__.py"

#: 每个 capability_id 的已评审直呼点。全部落在根 ``__init__.py``：
#: - music：:6481（/bot 别名链）/:8123（@music matcher）/:8589（自然语言链）
#: - music_mode：:6524/:6687/:8660（各自就近 import）
#: - divination：:4158 ``_build_divination_with_backend`` 闭包体内直呼，
#:   该闭包再按位置参交给根泛型执行器 :8230 执行
#: - ops：/bot 命令链 if/elif 内 21 处 ``return build_*_result(...)`` + :8566
#:
#: 另两处是**离线 CLI 冒烟 harness**（``ops/smoke/console_chat.py`` 的
#: ``main()/run_interactive()`` 与 ``ops/smoke/route_demo.py``），不在 NoneBot 消息路径上
#: （根文件不 import 它们的 run_* —— 由
#: ``test_smoke_harness_second_assembly_is_offline_only`` 活性核验）。它们与生产
#: 同真身但**不同装配**（console 版 music 不传 request_store/candidate_providers/
#: render_backend），故 descriptor 落地后必须一并改走 invoker，否则口径继续分叉。
_SMOKE_CONSOLE = "domains/ops/smoke/console_chat.py"
_SMOKE_ROUTE_DEMO = "domains/ops/smoke/route_demo.py"

KNOWN_DIRECT_ALLOWLIST_W3C: dict[str, set[str]] = {
    "bot.music": {_ROOT, _SMOKE_CONSOLE, _SMOKE_ROUTE_DEMO},
    "bot.music_mode": {_ROOT},
    "bot.divination": {_ROOT},
    "bot.receipt": {_ROOT},
    "bot.audit": {_ROOT},
    "bot.recent": {_ROOT},
    "bot.queue": {_ROOT},
    "bot.roles": {_ROOT},
    "bot.persona": {_ROOT},
    "bot.control": {_ROOT},
    "bot.history": {_ROOT},
    "bot.context": {_ROOT},
    "bot.config": {_ROOT},
    "bot.readiness": {_ROOT},
    "bot.dialogue": {_ROOT},
    "bot.llm": {_ROOT},
    "bot.setup.llm": {_ROOT},
    "bot.logs": {_ROOT},
    "bot.runtime": {_ROOT, _SMOKE_CONSOLE},
    "bot.identity": {_ROOT},
    "bot.quirk": {_ROOT},
    "bot.alert": {_ROOT},
    "bot.why": {_ROOT},
}

#: 「通电」=直呼清零 + invoker 调用点恰一处。本席生产码零改动 ⇒ 空集。
#: 主会话落 descriptor + 切换块当笔，须同步把该 id 加进 WIRED 与 invoker 面。
WIRED_W3C: set[str] = set()
KNOWN_INVOKER_SITES_W3C: dict[str, set[str]] = {}


def test_three_domain_ledger_is_live_accurate() -> None:
    """真树直呼/invoker 两面 == 登记 ledger；三条不变量同时为绿。"""
    direct, invoker = scan_w3c(_load_real_index())
    assert direct == KNOWN_DIRECT_ALLOWLIST_W3C, f"直呼面漂移：实得 {direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST_W3C}"
    actual_invoker = {cap: mods for cap, mods in invoker.items() if mods}
    assert actual_invoker == KNOWN_INVOKER_SITES_W3C, (
        f"invoker 调用点漂移：实得 {actual_invoker} ≠ 登记 {KNOWN_INVOKER_SITES_W3C}"
    )
    assert check_invariants(direct, invoker, wired=WIRED_W3C, allowlist=KNOWN_DIRECT_ALLOWLIST_W3C) == []


def test_tracked_symbols_are_the_real_handlers_not_ghosts() -> None:
    """门自身覆盖面自证：每个追踪符号必须在登记的真身文件里**确有定义**，
    且其签名确实产呈现契约（``-> CapabilityResult``）或是**返回闭包的工厂**
    （``-> Any`` + 内层 ``def capability(...) -> CapabilityResult``）。
    漏定义/坐标漂＝该符号的直呼永远不会红（门变哑），这里当场揭穿。
    """
    for symbol, cap in _TRACKED_W3C.items():
        trees: list[ast.AST] = []
        for rel in _DEF_FILES_W3C[symbol]:
            path = _PKG_ROOT / rel
            assert path.is_file(), f"{symbol} 的真身文件不存在：{rel}"
            trees.append(ast.parse(path.read_text(encoding="utf-8")))
        found: ast.FunctionDef | None = None
        for tree in trees:
            found = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == symbol
                ),
                None,
            )
            if found is not None:
                break
        assert found is not None, f"{symbol} 在 {_DEF_FILES_W3C[symbol]} 里找不到定义（坐标漂移）"
        annotation = getattr(found.returns, "id", None) or getattr(
            getattr(found.returns, "value", None), "id", ""
        )
        produces_presentation = annotation == "CapabilityResult" or any(
            isinstance(node, ast.FunctionDef)
            and getattr(node.returns, "id", "") == "CapabilityResult"
            for node in ast.walk(found)
        )
        assert produces_presentation, (
            f"{symbol} 既非 CapabilityResult 构造器也非返回该型闭包的工厂："
            f"追踪表需随迁移更新（cap={cap}）"
        )


def test_smoke_harness_second_assembly_is_offline_only() -> None:
    """豁免不靠注释：活性核验 ops 冒烟 harness 确实**不在消息路径上**。

    判据=根 ``__init__.py`` 只从 ``domains/ops/smoke/diagnostics`` 取件，
    从不 import ``console_chat``/``route_demo`` 的 ``run_*``/``main``；且这两个模块
    自带 CLI 入口（``if __name__ == "__main__"`` 或 ``main(argv)``）。
    一旦有席把 harness 接进生产消息路径，本测试红 ⇒ 直呼面必须重判。
    """
    root_src = (_PKG_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "smoke.console_chat" not in root_src and "route_demo" not in root_src, (
        "根文件开始 import 冒烟 harness ⇒ 它已是生产执行点，豁免作废"
    )
    for rel in (_SMOKE_CONSOLE, _SMOKE_ROUTE_DEMO):
        src = (_PKG_ROOT / rel).read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in src or "def main(" in src, f"{rel} 不再是 CLI 入口件"


def test_no_second_presentation_id_is_silently_consolidated() -> None:
    """一个 capability_id 被两个真身盖章＝中央表按 id 归并时折成一行。

    现况：``bot.runtime`` 同时由 ``build_runtime_admin_result``（/bot runtime 设置面）
    与 ``build_feature_control_result``（/bot feature 管理面）盖章。本席**不私改**、
    只把事实钉成登记值：若主会话给 feature 面立独立 id（建议 ``bot.feature_control``），
    本测试红 ⇒ 按提示更新 _TRACKED_W3C 与 SEAT-S-W3C §5。
    """
    from collections import defaultdict

    by_id: dict[str, set[str]] = defaultdict(set)
    for symbol, cap in _TRACKED_W3C.items():
        by_id[cap].add(symbol)
    collisions = {cap: symbols for cap, symbols in by_id.items() if len(symbols) > 1}
    assert collisions == {"bot.runtime": {"build_runtime_admin_result", "build_feature_control_result"}}, (
        f"id 碰撞面与登记不符（多真身同 id 会绕开 descriptor 一 id 一行）：{collisions}"
    )


# ---------------------------------------------------------------------------
# ② 唯一表在册真值：路由/门在派生行里、健康/降级/族全无 ⇒ D-d 缺口如实登记
# ---------------------------------------------------------------------------
#: 主动投递族的两个 id：既不在 ROUTE/CONTROLLED/HELP，也不在编排侧 descriptor ⇒
#: 唯一表整行缺失（feature gate 无法关它们、审计无归属）。补齐前本登记锁住现状。
MISSING_FROM_CAPABILITY_DESCRIPTOR: frozenset[str] = frozenset({"bot.admin_alert", "bot.error_report"})

#: 三域在册但「只有路由/门事实、没有编排事实」的 id（D-a 名义满足 / D-d 未满足）。
DESCRIPTOR_SHELL_ONLY_IDS: tuple[str, ...] = (
    "bot.music",
    "bot.music_mode",
    "bot.divination",
    "bot.status",
    "bot.logs",
    "bot.alert",
    "bot.runtime",
)


def test_active_push_capability_ids_are_absent_from_unique_table() -> None:
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CAPABILITY_DESCRIPTOR,
    )

    missing = frozenset(cid for cid in MISSING_FROM_CAPABILITY_DESCRIPTOR if cid not in CAPABILITY_DESCRIPTOR)
    assert missing == MISSING_FROM_CAPABILITY_DESCRIPTOR, (
        f"主动投递族 id 已被登记（请把 MISSING_* 清空并补 gate/健康交接段）：仍缺 {missing}"
    )


def test_three_domain_rows_have_no_orchestration_facts_yet() -> None:
    """在册行的 family/health_probe/fallbacks/timeout 全为空 = D-d 未满足的机器证据。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CAPABILITY_DESCRIPTOR,
    )

    for capability_id in DESCRIPTOR_SHELL_ONLY_IDS:
        row = CAPABILITY_DESCRIPTOR.get(capability_id)
        assert row is not None, f"{capability_id} 连派生行都没有（D-a 缺）"
        assert row.family is None, f"{capability_id} 已有 family ⇒ 编排侧已落，本锁需随迁更新"
        assert row.health_probe == "", f"{capability_id} 已有健康探测 ⇒ 同上"
        assert row.fallbacks == (), f"{capability_id} 已有降级链 ⇒ 同上"
        assert row.timeout_seconds is None, f"{capability_id} 已有 timeout ⇒ 同上"


def test_capability_family_has_no_home_for_these_three_domains() -> None:
    """descriptor 交接段的**前置阻塞**：CapabilityFamily 无 OPS/MUSIC/DIVINATION 成员。

    主会话扩员后本测试红 ⇒ 那是「阻塞已解」的信号，按 SEAT-S-W3C §5a 把三域
    descriptor 落进 ``DESCRIPTOR_BUILDERS`` 并删掉本测试（本席禁改该文件）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityFamily,
    )

    values = {member.value for member in CapabilityFamily}
    assert not ({"ops", "music", "divination"} & values), (
        f"family 已扩员 {sorted(values)} ⇒ 请落三域 descriptor 并退役本阻塞锁（SEAT-S-W3C §5a）"
    )


# ---------------------------------------------------------------------------
# ③ divination 双算法残余（WP9 收编未装配 ⇒ 现网跑的是第二套）
# ---------------------------------------------------------------------------
_CAP_FILE = "domains/divination/capabilities/divination.py"
#: 聊天能力同时 import 两套发牌算法的符号（deck_math 真身 / data.tarot 旧路径）。
_DECK_MATH_DRAWING = ("draw_tarot_cards", "draw_daily_fortune")
_TAROT_LEGACY_DRAWING = ("daily_card", "single_guidance", "three_card_spread")


def _imported_symbols(rel: str) -> dict[str, set[str]]:
    tree = ast.parse((_PKG_ROOT / rel).read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return out


def test_divination_still_holds_two_tarot_drawing_paths() -> None:
    """如实登记（高价值发现，非本席可修）：同一能力件内两套发牌算法并存。

    取证：``capabilities/divination.py`` 从 ``data.deck_math`` 取
    ``draw_tarot_cards``，又从 ``data.tarot`` 取 ``three_card_spread``/``single_guidance``；
    后者是 WP9 收编前的 rng.sample 老路径，只在 ``draw_store`` **未注入**时执行。
    修法是「root 装配注入 DrawStore + 删旧分支」，不是再写第三套（§7）。
    残余被清掉时本测试红 ⇒ 按提示删除本锁。
    """
    imports = _imported_symbols(_CAP_FILE)
    math_module = "plugins.bot_unified_runtime.domains.divination.data.deck_math"
    tarot_module = "plugins.bot_unified_runtime.domains.divination.data.tarot"
    math_draws = set(imports.get(math_module, ())) & set(_DECK_MATH_DRAWING)
    legacy_draws = set(imports.get(tarot_module, ())) & set(_TAROT_LEGACY_DRAWING)
    assert math_draws and legacy_draws, (
        f"双算法面与登记不符（真身={sorted(math_draws)} 旧路径={sorted(legacy_draws)}）"
        " ⇒ 残余已收编/已漂移，请更新 SEAT-S-W3C §2 与本锁"
    )


def test_production_does_not_assemble_divination_draw_store() -> None:
    """活性判据：根装配只传 ``render_backend``，从不传 ``draw_store`` ⇒
    现网占卜走的是 ``data/tarot`` 第二套算法、不落库、不过完整性门。
    「唯一真身存在」≠「唯一真身在跑」——这条锁的是后者。
    """
    root = (_PKG_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "draw_store=" not in root and "DrawStore(" not in root, (
        "根文件已装配 draw_store ⇒ 第二套算法在现网已失活，"
        "本锁与 test_divination_still_holds_two_tarot_drawing_paths 需一并重判"
    )
    tree = ast.parse(root)
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "build_divination_capability"
    ]
    assert len(sites) == 1, f"根侧 build_divination_capability 调用点数漂移（实 {len(sites)}）"
    kwargs = {keyword.arg for keyword in sites[0].keywords if keyword.arg}
    assert "draw_store" not in kwargs, "装配已注入 draw_store ⇒ 现网不再跑第二套算法，重判本锁"


def test_only_one_draw_error_class_in_the_domain() -> None:
    """WP9 的「异常只留一颗」是真的：全树恰一处 ``class DrawError``（本席复核非照抄）。"""
    definitions: list[str] = []
    for path in _PKG_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "class DrawError" not in text:
            continue
        tree = ast.parse(text)
        definitions.extend(
            f"{path.relative_to(_PKG_ROOT).as_posix()}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "DrawError"
        )
    assert definitions == ["domains/divination/store/draw_store.py:57"], f"第二颗 DrawError 现身：{definitions}"


# ---------------------------------------------------------------------------
# ④ 端到端逐字段等值：经 invoker 通电 == 直呼真身（本地夹具，不改生产）
# ---------------------------------------------------------------------------
def _message(text: str, *, sender_id: str = "u1") -> Any:
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        timestamp=datetime(2026, 9, 22, 13, 51, tzinfo=timezone.utc),
    )


def _local_invoker(capability_id: str, handler: Any, *, required_roles: tuple[str, ...]) -> Any:
    """现场注册「descriptor + adapter」的局部 invoker，形态照 §5a 交接块。

    family 借 ``FILES`` 占位：本三域尚无 family 成员（见
    ``test_capability_family_has_no_home_for_these_three_domains``），且 family 只被
    ``CapabilityRegistry.iter`` 与 ``validate_registry`` 消费、不参与 invoke 的门序，
    故对「信封逐字段等值」这一判据行为惰性——不是把三域当 media。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityDescriptor,
        CapabilityInvoker,
        CapabilityRegistry,
        HandlerRegistry,
        default_invoker,
    )

    base: CapabilityDescriptor = default_invoker().registry.get("files.read.code")  # 型别正确的模板行
    descriptor = replace(
        base,
        capability_id=capability_id,
        title=f"Wave3-C 夹具 {capability_id}",
        required_roles=required_roles,
        fallback_chain=("honest_degrade:夹具无外部依赖",),
    )
    registry = CapabilityRegistry()
    registry.register(descriptor)
    handlers = HandlerRegistry()
    handlers.register(capability_id, handler)
    return CapabilityInvoker(registry=registry, handlers=handlers)


def _assert_presentation_equals_envelope(result: Any, expected: Any, capability_id: str) -> None:
    """信封 ``data[PRESENTATION_DATA_KEY]`` 与直呼产出的 ``model_dump()`` 等值。

    唯一的例外列 = ``debug_id``：呈现契约 ``domains/core/contracts/runtime.py:48`` 用
    ``Field(default_factory=new_debug_id)`` 给**每次构造**发一个一次性 nonce，
    两条路径各构造一次 ⇒ 该列必不相同，与「接入是否改行为」无关。
    因此本判据=「除一次性 nonce 外全字段等值 + 字段集完全相同」，
    并显式要求 nonce 两边都非空（防有人把 debug_id 洗成常量把这条门变哑）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationStatus,
    )

    assert result.status is InvocationStatus.OK, f"{capability_id} 未走通：{result.status} {result.detail}"
    payload = result.data.get(PRESENTATION_DATA_KEY)
    assert isinstance(payload, dict), "成功态必须携带已序列化的呈现载荷（dict）"
    dumped = expected.model_dump()
    assert set(payload) == set(dumped), (
        f"{capability_id} 字段集被增删：多 {set(payload) - set(dumped)} 少 {set(dumped) - set(payload)}"
    )
    one_time = {key for key in payload if payload[key] != dumped[key]}
    assert one_time <= {"debug_id"}, f"{capability_id} 呈现体被改写字段：{sorted(one_time)}"
    assert payload["debug_id"] and dumped["debug_id"], "debug_id 两边都必须是非空一次性 nonce"
    # 显式点验易被「只比 dict」糊过去的语义面（出站/审核/权限相关列）
    for field in ("body", "summary", "title", "kind", "audit_tags", "send_policy", "risk_level", "privacy_level"):
        assert payload[field] == dumped[field], f"{capability_id} 字段 {field} 不等值"
    for field in ("images", "audio", "video", "files", "actions", "text_parts", "prefix_parts"):
        assert payload[field] == dumped[field], f"{capability_id} 出站载荷 {field} 不等值"
    assert payload["capability_id"] == capability_id == expected.capability_id
    assert payload["request_id"] == expected.request_id, "request_id 必须同源（不得二次生成）"


def test_e2e_ops_logs_through_invoker_equals_direct_call() -> None:
    """ops 面：管理员日志查询经 invoker（中央 roles 门）与直呼逐字段等值。"""
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_logs import (
        build_logs_query_result,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )

    class _StubLog:
        def read_recent(self, *, limit: int = 50, min_level: str = "info") -> list[str]:
            return [f"evt-{limit}-{min_level}"]

    log = _StubLog()
    expected = build_logs_query_result(
        log, request_id="req-ops-1", actor_roles=["user", "admin"], level="warn", limit=7
    )

    def _handle(request: CapabilityRequest) -> Any:
        from plugins.bot_unified_runtime.runtime.capability_protocols import _result

        services = request.context.get("services") or {}
        arguments = request.payload.get("arguments") or {}
        presented = build_logs_query_result(
            services.get("runtime_event_log"),
            actor_roles=list(request.roles),
            request_id=arguments.get("request_id"),
            level=str(arguments.get("level", "info")),
            limit=int(arguments.get("limit", 50)),
        )
        return _result(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via="runtime_logs",
        )

    invoker = _local_invoker("bot.logs", _handle, required_roles=("admin",))
    result = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.logs",
            payload={"arguments": {"request_id": "req-ops-1", "level": "warn", "limit": 7}},
            principal="3865067623",
            roles=("user", "admin"),
            context={"services": {"runtime_event_log": log}},
        )
    )
    _assert_presentation_equals_envelope(result, expected, "bot.logs")
    assert result.via == "runtime_logs"


def test_e2e_music_through_invoker_equals_direct_call() -> None:
    """music 面：点歌（providers 显式空表=零网络）经 invoker 与直呼逐字段等值。"""
    from plugins.bot_unified_runtime.domains.music.capabilities.music import (
        build_music_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )

    message = _message("点歌 晴天")
    assembly = {
        "providers": [],
        "audio_downloader": lambda url: None,
        "candidate_providers": None,
        "render_backend": None,
        "request_store": None,
    }
    expected = build_music_capability(None, **assembly)(message, None)

    def _handle(request: CapabilityRequest) -> Any:
        from plugins.bot_unified_runtime.runtime.capability_protocols import _result

        context_config = request.context.get("config")
        music = build_music_capability(
            context_config,
            **request.context.get("music_assembly", {}),
        )
        presented = music(request.payload["message"], request.context.get("decision"))
        return _result(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via="music",
        )

    invoker = _local_invoker("bot.music", _handle, required_roles=("user",))
    result = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.music",
            payload={"message": message},
            principal="u1",
            roles=("user",),
            context={"config": None, "music_assembly": assembly},
        )
    )
    _assert_presentation_equals_envelope(result, expected, "bot.music")


def test_e2e_divination_through_invoker_equals_direct_call() -> None:
    """divination 面：每日一抽（日期+主体派生种子=可复现）经 invoker 与直呼等值。"""
    from plugins.bot_unified_runtime.domains.divination.capabilities.divination import (
        build_divination_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )

    message = _message("每日一抽")
    expected = build_divination_capability(None, render_backend=None)(message, None)

    def _handle(request: CapabilityRequest) -> Any:
        from plugins.bot_unified_runtime.runtime.capability_protocols import _result

        capability = build_divination_capability(
            request.context.get("config"),
            render_backend=request.context.get("render_backend"),
            draw_store=request.context.get("draw_store"),
        )
        presented = capability(request.payload["message"], request.context.get("decision"))
        return _result(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via="divination",
        )

    invoker = _local_invoker("bot.divination", _handle, required_roles=("user",))
    result = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.divination",
            payload={"message": message},
            principal="u1",
            roles=("user",),
            context={"config": None},
        )
    )
    _assert_presentation_equals_envelope(result, expected, "bot.divination")


# ---------------------------------------------------------------------------
# ⑤ 注毒自证（合成树/局部 invoker；本席禁改生产树，故活性判据用「真树+投毒模块」并集）
# ---------------------------------------------------------------------------
def _poison_direct(symbol: str) -> dict[str, str]:
    return {"domains/ops/capabilities/sneaky_w3c.py": f"def f(c):\n    return {symbol}(c)\n"}


def test_poison_new_direct_callsite_is_red() -> None:
    """注毒①：真实树之外新增一处 build_music_capability 直呼 → 未登记直呼点红。"""
    index = _load_real_index()
    index.update(_poison_direct("build_music_capability"))
    direct, invoker = scan_w3c(index)
    violations = check_invariants(direct, invoker, wired=WIRED_W3C, allowlist=KNOWN_DIRECT_ALLOWLIST_W3C)
    assert any("bot.music" in item and "未登记直呼点" in item for item in violations), f"注毒未被拦：{violations}"


def test_poison_second_invoker_site_is_red() -> None:
    """注毒②：两个模块各 invoke bot.divination → 第二调用点红。"""
    src = "def f():\n    default_invoker().invoke(CapabilityRequest(capability_id='bot.divination'))\n"
    direct, invoker = scan_w3c({"m1.py": src, "m2.py": src})
    violations = check_invariants(direct, invoker, wired=WIRED_W3C, allowlist=KNOWN_DIRECT_ALLOWLIST_W3C)
    assert any("bot.divination" in item and "第二调用点" in item for item in violations), f"注毒未被拦：{violations}"


def test_poison_half_migration_is_red() -> None:
    """注毒③：同模块既直呼 build_logs_query_result 又 invoke bot.logs → 半迁移红。"""
    src = (
        "from plugins.bot_unified_runtime.domains.ops.admin.runtime_logs import build_logs_query_result\n"
        "def f(c):\n"
        "    build_logs_query_result(c)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='bot.logs'))\n"
    )
    direct, invoker = scan_w3c({"__init__.py": src})
    violations = check_invariants(direct, invoker, wired=WIRED_W3C, allowlist=KNOWN_DIRECT_ALLOWLIST_W3C)
    assert any("bot.logs" in item and "半迁移" in item for item in violations), f"注毒未被拦：{violations}"


def test_poison_wired_capability_keeps_direct_call_is_red() -> None:
    """注毒③b：某 id 一旦登记为已通电，任何直呼（哪怕文件本身合法）当场红。"""
    index = _load_real_index()
    direct, invoker = scan_w3c(index)
    violations = check_invariants(
        direct,
        invoker,
        wired={"bot.music"},  # 假装已通电，直呼仍在 ⇒ 必红
        allowlist=KNOWN_DIRECT_ALLOWLIST_W3C,
    )
    assert any("bot.music" in item and ("已通电却仍直呼" in item or "invoker 调用点非恰好一处" in item) for item in violations), (
        f"通电后回退老路未被拦：{violations}"
    )


def test_descriptor_removed_is_honest_and_old_path_still_works() -> None:
    """注毒④（两态分清，别把「摘 descriptor」与「不注册 handler」混为一谈）：

    - descriptor 在册、handler 未注册 → ``UNAVAILABLE``（not_wired）；
    - descriptor 整个摘掉 → ``FAILED``「未登记能力」（**不是** UNAVAILABLE，
      见 ``CapabilityInvoker.invoke`` :536-542；简报口径已修正）。
    两种都不崩，且**旧直呼路径不受影响**（这就是「未接线则行为不变」的回落自证）。
    """
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_logs import (
        build_logs_query_result,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityInvoker,
        CapabilityRegistry,
        CapabilityRequest,
        HandlerRegistry,
        InvocationStatus,
    )

    class _StubLog:
        def read_recent(self, *, limit: int = 50, min_level: str = "info") -> list[str]:
            return ["evt"]

    log = _StubLog()
    registry = CapabilityRegistry()
    handlers = HandlerRegistry()
    invoker = CapabilityInvoker(registry=registry, handlers=handlers)

    from plugins.bot_unified_runtime.runtime.capability_protocols import default_invoker

    base = default_invoker().registry.get("files.read.code")
    descriptor = replace(base, capability_id="bot.logs", title="运行时日志", required_roles=("admin",))
    registry.register(descriptor)

    absent = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.logs",
            payload={"arguments": {}},
            principal="u",
            roles=("admin",),
            context={"services": {"runtime_event_log": log}},
        )
    )
    assert absent.status is InvocationStatus.UNAVAILABLE
    assert absent.detail.strip(), "非 OK 终态必须给诚实说明（信封不变量）"

    # 摘 descriptor ⇒ FAILED（同一 invoker 换空表）
    empty = CapabilityInvoker(registry=CapabilityRegistry(), handlers=HandlerRegistry())
    removed = empty.invoke(
        CapabilityRequest(
            capability_id="bot.logs", payload={"arguments": {}}, principal="u", roles=("admin",)
        )
    )
    assert removed.status is InvocationStatus.FAILED and "未登记" in removed.detail

    # 旧直呼路径仍然完好（回落后现网零变更）
    still_ok = build_logs_query_result(log, request_id="req-fallback", actor_roles=["admin"])
    assert still_ok.capability_id == "bot.logs"
    assert still_ok.body


def test_central_role_gate_denies_what_direct_call_denies() -> None:
    """接入带来的中央权限门与 ops 现执法面对齐：非管理员被 invoker 拒。

    注意口径差（如实登记）：``_is_admin`` 只认字面 ``"admin"``，而 invoker 是
    ``roles ∩ required_roles`` 非空即放 ⇒ 超管两条路都过（roles.py 让超管自带
    admin 角色，实测见 test_super_admin_passes_ops_gate）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
    )

    def _handle(request: CapabilityRequest) -> Any:  # 走不到这里
        raise AssertionError("被中央权限门拒时 handler 不得执行")

    invoker = _local_invoker("bot.logs", _handle, required_roles=("admin",))
    denied = invoker.invoke(
        CapabilityRequest(capability_id="bot.logs", payload={"arguments": {}}, principal="u", roles=("user",))
    )
    assert denied.status is InvocationStatus.DENIED
    blocked = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.logs", payload={"arguments": {}}, principal="u", roles=("user", "blocked")
        )
    )
    assert blocked.status is InvocationStatus.DENIED


def test_super_admin_passes_ops_gate() -> None:
    """中央 roles 门不得把超管挡在 admin 门外（否则接入=提权者降权）。"""
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
        build_role_settings,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
    )

    service = build_role_settings(
        SimpleNamespace(  # 只喂 RoleSettings 需要的六张名单，不构造整个 Config
            bot_admin_user_ids=[],
            bot_telegram_admin_user_ids=[],
            bot_super_admin_user_ids=["3865067623"],
            bot_trusted_user_ids=[],
            bot_enterprise_user_ids=[],
            bot_blocked_user_ids=[],
        )
    )
    roles = tuple(service.resolve_roles(_message("查日志", sender_id="3865067623")))
    assert "admin" in roles, f"超管未叠加 admin（roles.py 语义变了）：{roles}"

    def _handle(request: CapabilityRequest) -> Any:
        from plugins.bot_unified_runtime.runtime.capability_protocols import (
            InvocationStatus as IS,
        )
        from plugins.bot_unified_runtime.runtime.capability_protocols import _result

        return _result(request, IS.OK, data={}, via="stub")

    invoker = _local_invoker("bot.logs", _handle, required_roles=("admin",))
    passed = invoker.invoke(
        CapabilityRequest(capability_id="bot.logs", payload={"arguments": {}}, principal="s", roles=roles)
    )
    assert passed.status is InvocationStatus.OK


def test_generic_executor_blind_spot_is_registered_not_pretended_away() -> None:
    """根泛型执行器 ``_run_simple_capability`` 的 ``capability_factory(config)`` 一点
    覆盖全树约 30 能力，符号不落在 Call 上 ⇒ 结构门看不见（D-b 永久盲区）。
    本锁不假装能看见它，只钉两件事：盲区仍在；本三域**只有 divination** 经它执行。
    """
    root_src = (_PKG_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "capability_factory(config)" in root_src, "泛型执行器已改造 ⇒ 盲区登记需重判"
    tree = ast.parse(root_src)
    executor_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_run_simple_capability":
            for arg in node.args[2:3]:
                if isinstance(arg, ast.Name):
                    executor_calls.append(arg.id)
    divination_sites = [name for name in executor_calls if "divination" in name]
    assert divination_sites == ["_build_divination_with_backend"], (
        f"本三域经泛型执行器的集合变了（实得 {divination_sites}）：Wave4.1 切换清单要重算"
    )
    # music / ops 全独立执行点 ⇒ 不在泛型执行器名单里（若在，本席 ledger 低估了直呼面）
    assert not [name for name in executor_calls if "music" in name or "logs" in name]
