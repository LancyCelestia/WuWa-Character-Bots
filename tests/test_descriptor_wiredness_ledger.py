"""统一接入波 · S-GAP 席常驻门：中央在册表 vs 生产真实通路的「登记式缺口门」。

权威：``docs/design/capability-orchestration-adoption-spec.md``（Wave 1–4）。用户原令
「所有内容走中央调度层，TTS 也不例外」缺的可核对形态就是这把门——它把「还剩多少没接入」
从一句没人能答的话，变成一个**可减的登记数**。

一句话判据：``CAPABILITY_DESCRIPTOR`` 里每一条 ``capability_id``，生产要么真走了
``….invoke(...)``（wired）、要么走了泛型执行器 ``pipeline.handle_async`` /
``_run_simple_capability``（generic_executor）、要么就是**在册零调用点**（not_wired，挂账）。
三条清单必须**恰好铺满**在册表，且真树扫描结果与清单逐桶相等。

四条不变量（各自可单独归因，见注毒）：
- INV-COVERAGE  在册集合 == (wired ∪ generic ∪ not_wired)：新冒一条不属于任何清单的 descriptor ⇒ 红；
                清单里登记了一条而真册没有 ⇒ 也红（防"清单糊住真实退化"）。
- INV-WIRED     登记的 invoke 点在真树找不到 ⇒ 红；真树冒出未登记的 invoke 点 ⇒ 红。
- INV-GENERIC   泛型执行器上出现的 ``capability_id=`` 字面量集合（去 wired 后）必须恰好 == 登记面。
- INV-RATCHET   「未通电缺口」= generic + not_wired 的条数 **只准降不准升**（Wave 4.1 每迁一处 invoke，
                把它从 generic/not_wired 挪进 wired，缺口 −1，接入进度第一次成为可减的数）。

设计纪律：
- **组合复用**，不复制第二套扫描器（铁律 7）：invoke 判据 import 自 v1 门
  ``test_orchestration_callsite_single``，泛型执行器判据 import 自本席只读扫描器
  ``scripts/orchestration_wired_census``。本件只加"清单比对"这一层新逻辑。
- **只 import 表，不 import nonebot、不启动插件装配**；descriptor 表若在飞不可导入 → 诚实 skip 点名外因
  （中央件由主会话在改），绝不因外因放宽判据（先例 ``test_creation_tts_drift_gate._cp``）。
- 纯 ast 静态扫描，零运行时副作用；``BOT_AUTOSYNC=0`` 下稳定绿（不依赖任何生成物）。
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import test_orchestration_callsite_single as _v1  # 复用 invoke 判据 + _PKG_ROOT + _rel

_SPEC = importlib.util.spec_from_file_location(
    "orchestration_wired_census", _REPO_ROOT / "scripts" / "orchestration_wired_census.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_census)


def _load_descriptor_ids() -> frozenset[str]:
    try:
        module = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    except Exception as exc:  # noqa: BLE001  中央件在飞不可导入属外因，诚实 skip，不放宽判据
        pytest.skip(f"CAPABILITY_DESCRIPTOR 不可导入（中央件在飞，非本门缺陷）：{exc!r}")
    table = getattr(module, "CAPABILITY_DESCRIPTOR", None)
    if table is None:  # Wave2 收口前表可能不存在——那也是外因，诚实 skip 不放宽判据
        pytest.skip("CAPABILITY_DESCRIPTOR 尚未导出（Wave 2 未落，非本门缺陷）")
    return frozenset(table)


# ===========================================================================
# 已登记清单（2026-09-22 真树实测）。Wave 4.1 迁一处 invoke：把该 cid 从
# NOT_WIRED/GENERIC 挪进 WIRED，缺口自动 −1。
# ===========================================================================
#: cid → 登记的生产 invoke 点（相对包根路径）。
WIRED: dict[str, frozenset[str]] = {
    "media.vision.anime_ip": frozenset({"domains/media/capabilities/image_search.py"}),
    "search.web": frozenset({"__init__.py"}),
}

#: 走泛型执行器（_run_simple_capability / pipeline.handle_async）的能力 id。
GENERIC: frozenset[str] = frozenset(
    {
        "bot.campus_forward", "bot.chat", "bot.content", "bot.group_info", "bot.image_search",
        "bot.media_archive", "bot.meme_library", "bot.music", "bot.subscribe", "bot.today_history",
    }
)

#: 在册但全树零调用点。value=挂账理由（仅人读；比对只看键集，authored_by 漂移不误红）。
#: interface_only：capability./core./parser./persona./transport. 的接口联动 id，本非可 invoke 入口，永久挂账属设计语义。
#: controlled_no_callsite：后台 job/管理链，无会话侧能力入口（是否该接由主会话逐项裁）。
#: route_capability_unmigrated：有 RouteKind/matcher 工厂、生产仍直呼，Wave 3/4 待翻面。
#: orchestration_unwired：编排侧已 author descriptor + 壳 handler，但生产零 invoke（Wave 4 欠账集中营）。
NOT_WIRED: frozenset[str] = frozenset(
    {
        # ---- interface_only（设计语义，非欠账）----
        "capability.auto_send", "capability.daily_assist", "capability.emotion", "capability.epic",
        "capability.game_live", "capability.group_info", "capability.gscore", "capability.meme",
        "capability.meme_absorb", "capability.moegirl", "capability.music", "capability.subscribe",
        "capability.today_history", "capability.tts", "capability.weather", "capability.wiki",
        "core.gscore", "parser.content", "persona.chat", "transport.onebot",
        # ---- controlled_no_callsite ----
        "bot.alert", "bot.audit", "bot.auto_send.preview", "bot.config", "bot.context", "bot.control",
        "bot.cookie_expiry_notice", "bot.cookie_login", "bot.credential_check", "bot.dialogue",
        "bot.download", "bot.emergency_info_push", "bot.file", "bot.group_digest_push", "bot.group_policy",
        "bot.group_welcome", "bot.help", "bot.history", "bot.identity", "bot.llm", "bot.logs",
        "bot.mail.control", "bot.mail.notify", "bot.memory", "bot.parse", "bot.persona", "bot.poke",
        "bot.queue", "bot.quirk", "bot.readiness", "bot.receipt", "bot.recent", "bot.reply", "bot.roles",
        "bot.route", "bot.routes", "bot.runtime", "bot.search", "bot.send_queue_worker", "bot.setup.llm",
        "bot.why",
        # ---- orchestration_unwired（有 handler_ref，生产零 invoke）----
        "creation.image.generate", "creation.tts.synthesize", "files.artifact.generate", "files.read.code",
        "files.read.excel", "files.read.latex", "files.read.markdown", "files.read.pdf", "files.read.ppt",
        "files.read.word", "media.asr.audio_file", "media.asr.speech", "media.video.frame_extract",
        "media.video.recognize", "media.video.subtitle", "media.vision.image", "media.vision.ocr",
        "search.acg", "search.reference.fetch", "search.unified",
        # ---- route_capability_unmigrated ----
        "bot.affinity", "bot.alias", "bot.auto_send", "bot.bond", "bot.commodities", "bot.daily_assist",
        "bot.divination", "bot.eat", "bot.emergency_info", "bot.epic", "bot.fx", "bot.ignore", "bot.market",
        "bot.meme", "bot.moegirl", "bot.music_mode", "bot.natural_command", "bot.news", "bot.northbound",
        "bot.randpic", "bot.reminder", "bot.status", "bot.stocks", "bot.tts", "bot.weather", "bot.wiki",
    }
)

#: INV-RATCHET 上限：未通电缺口 = len(GENERIC) + len(NOT_WIRED)。Wave 4.1 只准降。
GAP_CEILING: int = len(GENERIC) + len(NOT_WIRED)


# ===========================================================================
# 真树扫描（复用 import 进来的两套判据，零复制）
# ===========================================================================
def _scan_real_tree() -> tuple[dict[str, set[str]], set[str]]:
    """返回 (invoke 点 by cid, 泛型执行器 cid 集合)。"""
    invoke_hits: dict[str, set[str]] = {}
    generic_hits: set[str] = set()
    for rel, src in _census._iter_sources():
        if rel == "runtime/capability_protocols.py":
            continue  # 中央真源自身的 descriptor 构造不算生产调用点
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for cid in _v1._invoker_cids(tree):
            invoke_hits.setdefault(cid, set()).add(rel)
        generic_hits |= _census._generic_executor_cids(tree)
    return invoke_hits, generic_hits


def _live_partition(
    descriptor_ids: Iterable[str],
    invoke_hits: dict[str, set[str]],
    generic_hits: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """按 wired 优先归三桶（invoke 出现即 wired，其残留泛型字面量不计 generic）。"""
    ids = set(descriptor_ids)
    wired = {cid for cid in ids if invoke_hits.get(cid)}
    generic = {cid for cid in ids if not invoke_hits.get(cid) and cid in generic_hits}
    not_wired = ids - wired - generic
    return wired, generic, not_wired


# ===========================================================================
# 四条不变量谓词（各回带不变量标签的违规清单；喂真树或合成皆可）
# ===========================================================================
def _check_coverage(descriptor_ids: Iterable[str]) -> list[str]:
    ids = set(descriptor_ids)
    registered = set(WIRED) | set(GENERIC) | NOT_WIRED
    v: list[str] = []
    missing = ids - registered
    ghost = registered - ids
    if missing:
        v.append(f"[INV-COVERAGE] 新出现未登记 descriptor（注册≠接完，须归入 wired/generic/not_wired 之一）：{sorted(missing)}")
    if ghost:
        v.append(f"[INV-COVERAGE] 清单在册而真册已无此 descriptor（清单糊住真实退化）：{sorted(ghost)}")
    return v


def _check_wired(invoke_hits: dict[str, set[str]]) -> list[str]:
    v: list[str] = []
    for cid, files in sorted(WIRED.items()):
        live = invoke_hits.get(cid, set())
        gone = files - live
        if gone:
            v.append(f"[INV-WIRED] {cid} 登记的 invoke 点在真树找不到（通电退化）：{sorted(gone)}")
    unregistered_invoke = {cid for cid, files in invoke_hits.items() if files and cid not in WIRED}
    if unregistered_invoke:
        v.append(f"[INV-WIRED] 真树冒出未登记的 invoke 点（须先评审入 WIRED）：{sorted(unregistered_invoke)}")
    return v


def _check_generic(descriptor_ids: Iterable[str], invoke_hits: dict[str, set[str]], generic_hits: set[str]) -> list[str]:
    _wired, live_generic, _nw = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    v: list[str] = []
    if live_generic != set(GENERIC):
        added = live_generic - set(GENERIC)
        removed = set(GENERIC) - live_generic
        if added:
            v.append(f"[INV-GENERIC] 新增未登记的泛型执行器 id：{sorted(added)}")
        if removed:
            v.append(f"[INV-GENERIC] 登记的泛型执行器 id 在真树消失：{sorted(removed)}")
    return v


def _check_ratchet(descriptor_ids: Iterable[str], invoke_hits: dict[str, set[str]], generic_hits: set[str]) -> list[str]:
    _wired, live_generic, live_not_wired = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    gap = len(live_generic) + len(live_not_wired)
    if gap > GAP_CEILING:
        return [f"[INV-RATCHET] 未通电缺口上升：实得 {gap} > 上限 {GAP_CEILING}（只准降不准升；确属迁移请先更新清单）"]
    return []


# ===========================================================================
# ① 真树活性判据：真树 == 清单，四条不变量全绿
# ===========================================================================
def test_real_tree_matches_wiredness_ledger() -> None:
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    violations = (
        _check_coverage(descriptor_ids)
        + _check_wired(invoke_hits)
        + _check_generic(descriptor_ids, invoke_hits, generic_hits)
        + _check_ratchet(descriptor_ids, invoke_hits, generic_hits)
    )
    assert violations == [], "接入缺口台账漂移：\n" + "\n".join(violations)


# ===========================================================================
# ② 注毒自证：四条不变量各真的会红，且红在点名那一条（合成输入，不碰真树）
# ===========================================================================
def test_poison_unregistered_descriptor_is_red_on_coverage() -> None:
    """注毒：在册表凭空多一条不属于任何清单的 descriptor → 只杀 INV-COVERAGE。"""
    poisoned = set(_load_descriptor_ids()) | {"brand.new.capability"}
    v = _check_coverage(poisoned)
    assert any("[INV-COVERAGE]" in s and "brand.new.capability" in s for s in v), v
    # 归因唯一：真树扫描（invoke/generic）不含该合成 id，另两条谓词不该因这条毒而红
    invoke_hits, generic_hits = _scan_real_tree()
    assert _check_wired(invoke_hits) == []
    assert _check_generic(poisoned, invoke_hits, generic_hits) == []


def test_poison_ghost_ledger_entry_is_red_on_coverage() -> None:
    """注毒：清单里登记了一条而真册已删 → 消失也红（INV-COVERAGE 反向）。"""
    shrunken = set(_load_descriptor_ids()) - {"search.web"}
    v = _check_coverage(shrunken)
    assert any("[INV-COVERAGE]" in s and "search.web" in s for s in v), v


def test_poison_vanished_wired_site_is_red_on_wired() -> None:
    """注毒：抽掉 search.web 登记的 invoke 点 → 杀 INV-WIRED。"""
    invoke_hits, _generic_hits = _scan_real_tree()
    invoke_hits.pop("search.web", None)
    v = _check_wired(invoke_hits)
    assert any("[INV-WIRED]" in s and "search.web" in s for s in v), v


def test_poison_new_invoke_site_is_red_on_wired() -> None:
    """注毒：一条 not_wired 的能力突然冒出 invoke 点却不更新清单 → 杀 INV-WIRED（未登记 invoke）。"""
    invoke_hits, _generic = _scan_real_tree()
    invoke_hits["bot.weather"] = {"__init__.py"}  # bot.weather 在 NOT_WIRED，未进 WIRED
    v = _check_wired(invoke_hits)
    assert any("[INV-WIRED]" in s and "bot.weather" in s for s in v), v


def test_poison_new_generic_id_is_red_on_generic_and_ratchet() -> None:
    """注毒：泛型执行器上多出一个未登记 capability_id → 同时杀 INV-GENERIC 与 INV-RATCHET。"""
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    generic_hits = generic_hits | {"bot.brand.new.generic"}
    # 该 id 需先在 descriptor 里才会计入 generic 面——用合成 descriptor 集模拟"在册且走泛型但没登记"
    synthetic_ids = set(descriptor_ids) | {"bot.brand.new.generic"}
    # 清单没这条 ⇒ coverage 也会红；本毒只验 generic/ratchet 各自归因
    g = _check_generic(synthetic_ids, invoke_hits, generic_hits)
    assert any("[INV-GENERIC]" in s and "bot.brand.new.generic" in s for s in g), g
    r = _check_ratchet(synthetic_ids, invoke_hits, generic_hits)
    assert any("[INV-RATCHET]" in s for s in r), r


def test_generic_executor_scanner_reads_capability_id_literal() -> None:
    """扫描器自证（防门变哑）：泛型执行器判据确实从 handle_async / _run_simple_capability
    的关键字字面量提 id；换个方法名或换个参数名都不该命中。"""
    src = (
        "async def f(pipeline, msg):\n"
        "    await pipeline.handle_async(msg, cap, capability_id='bot.demo')\n"
        "    await _run_simple_capability(bot, ev, factory, capability_id='bot.demo2', matcher=m)\n"
        "    await pipeline.other_async(msg, capability_id='bot.ignored')\n"
        "    await pipeline.handle_async(msg, cap, some_id='bot.wrong_kwarg')\n"
    )
    found = _census._generic_executor_cids(ast.parse(src))
    assert found == {"bot.demo", "bot.demo2"}, found


def test_ledger_partitions_are_disjoint_and_complete() -> None:
    """清单自身自洽（结构性锁）：三桶两两不相交，并起来即在册全集。"""
    assert not (set(WIRED) & GENERIC), "wired 与 generic 不能重叠"
    assert not (set(WIRED) & NOT_WIRED), "wired 与 not_wired 不能重叠"
    assert not (GENERIC & NOT_WIRED), "generic 与 not_wired 不能重叠"
    descriptor_ids = _load_descriptor_ids()
    assert set(WIRED) | GENERIC | NOT_WIRED == set(descriptor_ids)


def test_wired_sites_are_actually_invoke_callsites_in_tree() -> None:
    """活性质地锁：登记的每个 wired 点必须真的能在真树里按 invoke-capability_id 找回来
    （防清单写成字符串快照却与扫描判据脱节）。"""
    descriptor_ids = _load_descriptor_ids()
    invoke_hits, generic_hits = _scan_real_tree()
    wired, _gen, _nw = _live_partition(descriptor_ids, invoke_hits, generic_hits)
    assert wired == set(WIRED), f"真树 invoke 面与清单不符：{sorted(wired)} ≠ {sorted(set(WIRED))}"
    for cid, files in WIRED.items():
        assert files <= invoke_hits.get(cid, set()), f"{cid} 登记的 invoke 文件不在真树扫描结果里"
