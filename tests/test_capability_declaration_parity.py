"""能力声明齐（D-g）与「声明==执法」常驻门（统一接入波 · 席位 S-PARITY）。

判据三维 + 注毒自证，全离线（零网络/零线程/零生产 .env 读；builder 只在 deny
分支前返回，喂 None/"" 占位不触碰 store/config）：

① D-g 三处声明齐：每个「有 RouteKind 的能力 id」必须在受控表或在帮助表被引用；
   每个帮助主题声明的 capability 必须是合法 id 形态且在册，散文按形态登记例外。
② 权限口径一致（最硬）：凡帮助条目 admin_only=True，其能力执行路径必须真的拒绝
   非管理员——活性拿真 builder 走 user（必拒），不许只看 required_roles 字段。
③ 一 id 一入口：同一 capability id 被两个不同模块字面构造 CapabilityResult ⇒ 现形。

每条判据登记式例外双向：新破缺失⇒红；登记的例外在真树已不再破⇒也红（逼清单跟真值）。
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    capability_registry as cr,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

_ID_ANCHORED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
_ID_EMBEDDED = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")


# ---------------------------------------------------------------------------
# 纯判据函数（喂合成数据即可注毒自证）
# ---------------------------------------------------------------------------
def check_route_orphan(route_caps, controlled, help_refs, exceptions):
    """①a：路由能力既不在受控表也不被帮助引用 ⇒ 孤儿（除非登记例外）；已不再孤儿的例外 ⇒ 陈旧。"""
    orphans = {cid for cid in route_caps if cid not in controlled and cid not in help_refs}
    missing = sorted(orphans - set(exceptions))
    stale = sorted(set(exceptions) - orphans)
    return missing, stale


def check_help_reference(help_decls, on_register_ids, no_id_forms):
    """①b：帮助主题引用的干净/嵌入 id 必须都在册；无 id 的散文必须命中登记形态。"""
    bad_ref: list[tuple[str, str]] = []
    unregistered: list[str] = []
    matched: set[str] = set()
    for decl in help_decls:
        cap = decl.capability.strip()
        if _ID_ANCHORED.match(cap):
            if cap not in on_register_ids:
                bad_ref.append((decl.topic, cap))
            continue
        embedded = _ID_EMBEDDED.findall(cap)
        if embedded:
            bad_ref.extend((decl.topic, cid) for cid in embedded if cid not in on_register_ids)
            continue
        hit = next((name for name, pat in no_id_forms.items() if pat.match(cap)), None)
        if hit is None:
            unregistered.append(decl.topic)
        else:
            matched.add(hit)
    stale_forms = sorted(set(no_id_forms) - matched)
    return bad_ref, unregistered, stale_forms


def check_duplicate_authors(authors_by_id, exceptions):
    """③：字面构造同一 id 跨 ≥2 模块 ⇒ 未登记的重复入口；登记模块集与实况不符 ⇒ 陈旧。"""
    dup_unregistered = sorted(
        cid for cid, mods in authors_by_id.items() if len(mods) > 1 and cid not in exceptions
    )
    stale: list[str] = []
    for cid, expected in exceptions.items():
        current = authors_by_id.get(cid, set())
        if set(current) != set(expected):
            stale.append(cid)
    return dup_unregistered, stale


def check_admin_parity(admin_required, covered):
    """②集合相等：声明 admin_only 的能力必须逐个被覆盖（活性/结构/缺口），双向锁陈旧。"""
    unregistered = sorted(admin_required - covered)
    stale = sorted(covered - admin_required)
    return unregistered, stale


# ---------------------------------------------------------------------------
# 真树数据提取（live import + AST 扫描，无行号依赖）
# ---------------------------------------------------------------------------
def _route_capability_ids() -> set[str]:
    return {d.capability_id for d in cr.ROUTE_CAPABILITY_DECLARATIONS}


def _help_referenced_ids() -> set[str]:
    ids: set[str] = set()
    for decl in cr.HELP_TOPIC_DECLARATIONS:
        ids.update(_ID_EMBEDDED.findall(decl.capability))
    return ids


def _admin_required_ids() -> set[str]:
    ids: set[str] = set()
    for decl in cr.HELP_TOPIC_DECLARATIONS:
        if decl.admin_only:
            ids.update(_ID_EMBEDDED.findall(decl.capability))
    return ids


def _literal_capability_authors() -> dict[str, set[str]]:
    """扫主包源码：把 ``CapabilityResult(..., capability_id="X", ...)`` 的字面 id 按相对模块归组。"""
    by_id: dict[str, set[str]] = {}
    for py in sorted(PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:  # 生产文件语法坏 = 全树问题，如实抛给门
            raise AssertionError(f"无法解析生产源文件 {py}: {exc}") from exc
        rel = str(py.relative_to(PLUGIN_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "CapabilityResult":
                continue
            for kw in node.keywords:
                if kw.arg == "capability_id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    by_id.setdefault(kw.value.value, set()).add(rel)
    return by_id


# ---------------------------------------------------------------------------
# 登记式例外（每条写明理由；真值变了必须同步，否则红）
# ---------------------------------------------------------------------------
ROUTE_ORPHAN_EXCEPTIONS: dict[str, str] = {
    # IGNORE 兜底席：has_rule=False、无独立命令/帮助/gate，classify 命中空消息/未知形态，设计语义。
    "bot.ignore": "RouteKind.IGNORE 兜底席（无 RouteRule、无用户命令、无帮助主题），设计语义而非漏登。",
}

NO_ID_HELP_FORMS: dict[str, re.Pattern[str]] = {
    "subcommand": re.compile(r"^/bot .+"),          # /bot 子命令入口，能力经 ADMIN/bot.* 分发，无独立 id
    "config": re.compile(r"^\.env"),                # 纯配置项说明（改后重启），非命令非能力
    "on_command": re.compile(r"^on_command:"),      # NoneBot on_command 事件型入口
    "on_message": re.compile(r"^on_message:"),      # NoneBot on_message 事件型入口
    "on_notice": re.compile(r"^on_notice:"),        # NoneBot on_notice 事件型入口
    "matcher": re.compile(r"^matcher:"),            # 纯 matcher 判定型（文件导出/IGNORE）
    "interface_name": re.compile(r"^meme_absorb\b"),  # 接口清单 id（非 bot.* 形态，无独立命令）
}

DUP_ID_AUTHOR_EXCEPTIONS: dict[str, tuple[str, frozenset[str]]] = {
    "bot.runtime": (
        (
            "两个 /bot admin 子命令族共用单一 id（运行时设置 settings 与功能管理 feature）；Wave2 唯一表按 id 折成一行。"
            "建议 owner 拆分（feature 另立 bot.feature_control）。"
        ),
        frozenset({"domains/ops/admin/runtime_admin.py", "domains/ops/features/feature_control.py"}),
    ),
    "bot.subscribe": (
        "subscribe.py（旧）与 subscribe_v2.py（现役）双实现并存 + 根与内容解析器各出一张回执卡；疑第二真身，待 owner 收敛。",
        frozenset({
            "__init__.py",
            "domains/link_parse/capabilities/content_parser.py",
            "domains/subscribe/capabilities/subscribe.py",
            "domains/subscribe/capabilities/subscribe_v2.py",
        }),
    ),
    "bot.reminder": (
        "提醒（schedule/reminder.py）与笔记（notes/notes.py）同属 bot.reminder 能力面（HELP 提醒/笔记两主题都指它），设计语义。",
        frozenset({"domains/notes/capabilities/notes.py", "domains/schedule/capabilities/reminder.py"}),
    ),
    "bot.meme_library": (
        "域内能力 + 根装配各构造一张（根=兜底/预览回执）；待 owner 判定是否收成单点。",
        frozenset({"__init__.py", "domains/meme/capabilities/meme_library.py"}),
    ),
    # bot.moegirl 双作者（域内能力 + 根降级回执）已于 2026-09-27 百科接地批收敛为
    # 单点：根处理程序不再字面构造 bot.moegirl 回执（命中只作接地块交 bot.chat，
    # 锁 tests/test_kb_grounding_chat.py 结构面）⇒ 例外清单同步移除（清单只减不增）。
    "bot.parse": (
        "解析能力 + 解析历史支持件（parse_history）共享 id；设计语义（同一能力的历史视图出口）。",
        frozenset({"__init__.py", "domains/link_parse/support/parse_history.py"}),
    ),
}


# ---------------------------------------------------------------------------
# ② 权限口径：activity probe 装配
# ---------------------------------------------------------------------------
# deny-only（真 builder，喂 actor_roles=["user"]，断结果是被拒形态）
_DENY_BUILDERS: dict[str, object] = {}


def _load_deny_builders():
    """延迟 import：仅在运行 activity 测试时拉入 ops/admin builders（避免 collect 期硬依赖）。"""
    from plugins.bot_unified_runtime.domains.ops.admin import debug as _dbg
    from plugins.bot_unified_runtime.domains.ops.admin import runtime_logs as _logs
    from plugins.bot_unified_runtime.domains.ops.smoke import diagnostics as _diag

    return {
        "bot.config": _dbg.build_config_query_result,
        "bot.readiness": _dbg.build_readiness_query_result,
        "bot.dialogue": _dbg.build_dialogue_query_result,
        "bot.persona": _dbg.build_persona_query_result,
        "bot.roles": _dbg.build_roles_query_result,
        "bot.control": _dbg.build_runtime_control_result,
        "bot.history": _dbg.build_history_clear_result,
        "bot.logs": _logs.build_logs_query_result,
        # S-WHY 2026-09-22：原 GAP 转 activity（角色门已执法，deny 先于 store 触碰）。
        "bot.why": _diag.build_why_result,
    }


def _invoke_with_roles(fn, actor_roles):
    """通用调用：required positional→None、required keyword-only→""、request_id/actor_roles 显式。

    安全前提：这些 builder 的角色门是首行判据（deny 在任何 store/config 触碰前 return），
    故 None/"" 永不被使用。
    """
    sig = inspect.signature(fn)
    args: list = []
    kwargs: dict = {"request_id": "parity-probe", "actor_roles": list(actor_roles)}
    for name, param in sig.parameters.items():
        if name in ("request_id", "actor_roles"):
            continue
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD) and param.default is param.empty:
            args.append(None)
        elif param.kind is param.KEYWORD_ONLY and param.default is param.empty:
            kwargs[name] = ""
    return fn(*args, **kwargs)


# 覆盖集（三类之和；须恰等于 _admin_required_ids()）
ACTIVITY_DENY_IDS = frozenset({
    "bot.runtime", "bot.status", "bot.media_archive",
    "bot.config", "bot.readiness", "bot.dialogue", "bot.persona", "bot.roles", "bot.control", "bot.history", "bot.logs",
    "bot.why",
})
STRUCTURAL_IDS = frozenset({"bot.emergency_info"})
GAP_IDS = frozenset()  # 2026-09-22 S-WHY：bot.why 执行面角色门已执法，移出缺口清单。
COVERED_IDS = ACTIVITY_DENY_IDS | STRUCTURAL_IDS | GAP_IDS

ADMIN_GAP_REASONS: dict[str, str] = {
    # bot.why 缺口已于 2026-09-22 关闭（build_why_result 补中央 roles_satisfy 门，
    # 转 ACTIVITY_DENY_IDS 活性覆盖；专属锁 tests/test_why_role_gate.py）。
}


# ---------------------------------------------------------------------------
# 活性门：① 三处声明齐（真树）
# ---------------------------------------------------------------------------
def test_route_capabilities_have_help_or_controlled():
    missing, stale = check_route_orphan(
        _route_capability_ids(), set(cr.CONTROLLED_INTERNAL_CAPABILITIES), _help_referenced_ids(), ROUTE_ORPHAN_EXCEPTIONS
    )
    assert not missing, f"路由能力既无受控登记也无帮助主题（D-g 孤儿）: {missing}"
    assert not stale, f"登记的孤儿例外在真树已不再成立（清单未同步真值）: {stale}"


def test_help_topics_reference_registered_ids():
    bad_ref, unregistered, stale_forms = check_help_reference(
        cr.HELP_TOPIC_DECLARATIONS, set(cp.CAPABILITY_DESCRIPTOR), NO_ID_HELP_FORMS
    )
    assert not bad_ref, f"帮助主题引用的能力 id 不在唯一在册表: {bad_ref}"
    assert not unregistered, f"无 id 帮助主题未命中任何登记形态: {unregistered}"
    assert not stale_forms, f"登记的散文形态在真树已无对应主题（清单未同步）: {stale_forms}"


# ---------------------------------------------------------------------------
# 活性门：③ 一 id 一入口
# ---------------------------------------------------------------------------
def test_capability_id_not_reshaped_by_two_unregistered_authors():
    authors = _literal_capability_authors()
    dup_unregistered, stale = check_duplicate_authors(
        authors, {cid: mods for cid, (_, mods) in DUP_ID_AUTHOR_EXCEPTIONS.items()}
    )
    assert not dup_unregistered, (
        "同一 capability id 被 ≥2 模块字面构造 CapabilityResult 且未登记例外（一 id 多入口，需 owner 定性/拆分）: "
        f"{[(cid, sorted(authors[cid])) for cid in dup_unregistered]}"
    )
    assert not stale, f"登记的重复印外模块集与真树实况不符（重构需同步清单）: {stale}"


def test_known_runtime_id_collision_is_still_two_builders():
    """bot.runtime 双 builder 是本席证实的核心重复入口，锁其仍成立（若被拆分则逼清单更新）。"""
    authors = _literal_capability_authors()
    assert authors.get("bot.runtime") == set(DUP_ID_AUTHOR_EXCEPTIONS["bot.runtime"][1]), (
        "bot.runtime 的构造模块集发生变化——若已拆成不同 id（缺陷修复），请从例外清单移除本条。"
    )


# ---------------------------------------------------------------------------
# 活性门：② 权限口径——集合相等 + 真 builder activity + 结构 + 缺口
# ---------------------------------------------------------------------------
def test_admin_only_help_set_is_fully_covered():
    unregistered, stale = check_admin_parity(_admin_required_ids(), COVERED_IDS)
    assert not unregistered, (
        f"新增 admin_only 能力未被执法判据覆盖（须加 activity/structural/gap）: {unregistered}"
    )
    assert not stale, f"覆盖清单里存在已不再声明 admin_only 的能力（清单未同步）: {stale}"
    assert set(ADMIN_GAP_REASONS) == GAP_IDS, "GAP 登记与理由表不一致"


def test_admin_only_builders_actually_deny_non_admin():
    """活性：真 builder 收 actor_roles=["user"] 必须返回被拒形态（tag 以 _denied 结尾）——不是只看字段。"""
    builders = _load_deny_builders()
    assert set(builders) == (ACTIVITY_DENY_IDS - {"bot.runtime", "bot.status", "bot.media_archive"}), (
        "deny-builder 清单与登记集不一致（新增/删除 admin 能力须同步）"
    )
    for cap_id, fn in builders.items():
        result = _invoke_with_roles(fn, ["user"])
        denied = any(str(tag).endswith("_denied") for tag in (result.audit_tags or []))
        assert denied, f"{cap_id}：非管理员未在执行面被拒（audit_tags={result.audit_tags}），权限口径分裂"
        assert result.capability_id == cap_id, f"{cap_id}：deny 结果 capability_id 漂到 {result.capability_id}"


def test_status_admin_gate_denies_non_admin():
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        build_status_result,
    )

    denied = build_status_result(config=None, request_id="parity", actor_roles=["user"])
    assert "看运行时状态" in denied.body, f"bot.status 非管理员未走权限门（body 异常）: {denied.body[:60]}"
    assert denied.capability_id == "bot.status"


def test_feature_control_runtime_gate_denies_non_admin_and_allows_admin():
    """bot.runtime 双向活性（唯一 IO-free 的 admin 门）：user 被拒、admin 放行。"""
    from plugins.bot_unified_runtime.domains.ops.features.feature_control import (
        build_feature_control_result,
    )

    denied = build_feature_control_result(None, request_id="p", actor_id="a", actor_roles=["user"], command_text="")
    assert "forbidden" in (denied.audit_tags or []), f"bot.runtime 非管理员未被拒: {denied.audit_tags}"
    assert denied.capability_id == "bot.runtime"
    allowed = build_feature_control_result(None, request_id="p", actor_id="a", actor_roles=["admin"], command_text="")
    assert "forbidden" not in (allowed.audit_tags or []), "bot.runtime 管理员被误拒"


def test_media_archive_role_predicate_denies_below_min_role():
    """活性：_role_at_least 直接判 user<super_admin 拒、super_admin 放行（归档落本机，缺省超管门）。"""
    from plugins.bot_unified_runtime.domains.media.capabilities.media_archive import (
        _role_at_least,
    )

    assert _role_at_least(["user"], "super_admin") is False
    assert _role_at_least(["super_admin"], "super_admin") is True
    assert _role_at_least(["admin"], "admin") is True


def test_emergency_info_has_real_role_gate_structural():
    """结构（需 runtime message+source 才活性，本席诚实降级为 AST/文本级真门存在证据，非字段检查）。"""
    src = (PLUGIN_ROOT / "domains/emergency_info/capabilities/emergency_info.py").read_text(encoding="utf-8")
    assert re.search(r'any\([^)]*in \{[^}]*"admin"[^}]*"super_admin"[^}]*\}[^)]*roles', src), (
        "bot.emergency_info 执行面未见 admin/super_admin 角色成员判定（执法可能已移除）"
    )


def test_why_gap_closed_role_gate_enforced():
    """已执法断言（原登记为缺口自证 test_why_is_still_an_unenforced_gap，2026-09-22 S-WHY 随修复翻向）：
    build_why_result 现必须带角色形参、user 主体活性被拒、且 bot.why 的登记从 GAP 移到 activity。"""
    from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (
        build_why_result,
    )

    role_params = [n for n in inspect.signature(build_why_result).parameters if "role" in n.lower() or "admin" in n.lower()]
    assert role_params, "build_why_result 角色形参消失——执行面门被移除，权限口径分裂复活"
    assert "bot.why" not in GAP_IDS and "bot.why" in ACTIVITY_DENY_IDS, (
        "bot.why 登记位与执法实况不符（应 activity 覆盖，不再挂 GAP）"
    )
    denied = _invoke_with_roles(build_why_result, ["user"])
    assert any(str(tag).endswith("_denied") for tag in (denied.audit_tags or [])), (
        f"bot.why：非管理员未在执行面被拒（tags={denied.audit_tags}）"
    )
    assert denied.capability_id == "bot.why"


# ---------------------------------------------------------------------------
# ⑤ 枚举诚实性：InvocationStatus 无 REJECTED，全树不得引用不存在的成员
# ---------------------------------------------------------------------------
def test_invocation_status_has_no_rejected_member():
    assert not hasattr(cp.InvocationStatus, "REJECTED")
    assert {m.name for m in cp.InvocationStatus} == {
        "OK", "FALLBACK_OK", "DEGRADED", "DENIED", "TIMEOUT",
        "LIMIT_EXCEEDED", "NOT_CONFIGURED", "UNAVAILABLE", "FAILED",
    }


def test_no_code_references_nonexistent_invocation_status():
    valid = {m.name for m in cp.InvocationStatus}
    offenders: list[str] = []
    for py in sorted(PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue
        rel = str(py.relative_to(PLUGIN_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "InvocationStatus"
                and node.attr not in valid
            ):
                offenders.append(f"{rel}:{node.attr}")
    assert not offenders, f"引用了不存在的 InvocationStatus 成员: {offenders}"


# ---------------------------------------------------------------------------
# ④ 注毒自证：每条判据喂合成声明，断「红在该条且无连带」
# ---------------------------------------------------------------------------
class _FakeDecl:
    def __init__(self, topic, capability, admin_only=False):
        self.topic = topic
        self.capability = capability
        self.admin_only = admin_only


def test_poison_route_orphan_fires_only_on_missing_and_stale():
    # 孤儿：bot.x 既非受控也不被帮助引用
    missing, stale = check_route_orphan({"bot.x", "bot.ok"}, set(), {"bot.ok"}, {})
    assert missing == ["bot.x"] and stale == []
    # 陈旧：登记的例外其实已被帮助引用（不再孤儿）
    missing2, stale2 = check_route_orphan({"bot.y"}, set(), {"bot.y"}, {"bot.y": "reason"})
    assert missing2 == [] and stale2 == ["bot.y"]


def test_poison_help_reference_fires_on_unregistered_and_stale_form():
    decls = [_FakeDecl("t1", "bot.ghost"), _FakeDecl("t2", "/bot ok"), _FakeDecl("t3", "mystery-form")]
    bad_ref, unreg, _stale = check_help_reference(decls, {"bot.ghost"}, NO_ID_HELP_FORMS)
    assert bad_ref == []                              # bot.ghost 在册 → 不该报
    assert unreg == ["t3"]                            # mystery-form 未命中任何登记形态
    # 陈旧形态：所有主题都不再是 on_command → 该形态登记失效
    _, _, stale2 = check_help_reference([_FakeDecl("t", "/bot a")], set(), NO_ID_HELP_FORMS)
    assert "on_command" in stale2 and "config" in stale2


def test_poison_duplicate_authors_fires_only_on_unregistered_dup():
    authors = {"bot.a": {"m1.py", "m2.py"}, "bot.b": {"m1.py"}}
    dup, stale = check_duplicate_authors(authors, {"bot.b": {"m1.py"}})
    assert dup == ["bot.a"]                           # bot.b 单模块 → 不连带
    assert stale == []
    # 陈旧：登记的例外模块集与实况不符
    _dup2, stale2 = check_duplicate_authors({"bot.a": {"m1.py", "m2.py"}}, {"bot.a": {"m1.py", "mX.py"}})
    assert stale2 == ["bot.a"]


def test_poison_admin_parity_fires_both_directions():
    unreg, stale = check_admin_parity({"bot.a", "bot.new"}, {"bot.a", "bot.gone"})
    assert unreg == ["bot.new"] and stale == ["bot.gone"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
