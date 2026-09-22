"""Wave 2 唯一在册表常驻门（统一接入波 · 席位 U1）。

执法两维（docs/design/capability-orchestration-adoption-spec.md §1）：
- **D-a 唯一在册**：「capability_id 是否在册」的唯一答案 =
  ``runtime/capability_protocols.CAPABILITY_DESCRIPTOR``；全树不得为同一 id 在第二处
  authoring 表里另立注册（本门按 AST 扫两处 authoring 面 + 全树 descriptor 构造点）。
- **D-f gate 读同一处**：feature gate 的绑定表必须由唯一表投影，消费面不得回退到
  直接读 ``CONTROLLED_INTERNAL_CAPABILITIES`` / ``ROUTE_CAPABILITY_DECLARATIONS``。

行为等价判据（合并语义=缺省取并集）：唯一表的 gate 投影与迁移前
``feature_catalog`` 内联两表并集的结果**逐键等价**——本门以此反对「为了绿而放宽」。
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    capability_registry as cr,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
SHELL = PLUGIN_ROOT / "runtime" / "capability_protocols.py"
REGISTRY = PLUGIN_ROOT / "domains" / "chat_reply" / "runtime" / "capability_registry.py"
FEATURE_CATALOG = PLUGIN_ROOT / "domains" / "ops" / "features" / "feature_catalog.py"

_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _string_literals_of_call(tree: ast.Module, func_names: set[str]) -> list[str]:
    """收集 ``name("literal", ...)`` 的第一个字符串字面量参数（positional 才收）。"""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in func_names:
            continue
        for arg in node.args[:1]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value)
    return found


def _descriptor_authored_ids() -> list[str]:
    """编排侧 authoring 面：capability_protocols.py 里 CapabilityDescriptor(...) 的 capability_id。"""
    ids: list[str] = []
    for node in ast.walk(_tree(SHELL)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "CapabilityDescriptor"
        ):
            for keyword in node.keywords:
                if keyword.arg == "capability_id" and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, str):
                        ids.append(value)
    return ids


def _route_authored_ids() -> list[str]:
    """注册册 authoring 面：ROUTE_CAPABILITY_DECLARATIONS 的 capability_id 列。"""
    ids: list[str] = []
    for decl in cr.ROUTE_CAPABILITY_DECLARATIONS:
        ids.append(decl.capability_id)
    return ids


def test_descriptor_is_union_of_all_inputs() -> None:
    """唯一表=五路输入的并集，一条不多一条不少（并集语义的直接判据）。"""
    help_ids = {
        decl.capability.strip()
        for decl in cr.HELP_TOPIC_DECLARATIONS
        if _CAPABILITY_ID_RE.match(decl.capability.strip())
    }
    interface_ids = {
        decl.interface_id for decl in cr.INTERFACE_DECLARATIONS if _CAPABILITY_ID_RE.match(decl.interface_id)
    }
    expected = (
        {row.capability_id for row in cp.orchestration_descriptor_rows()}
        | set(_route_authored_ids())
        | set(cr.CONTROLLED_INTERNAL_CAPABILITIES)
        | help_ids
        | interface_ids
    )
    assert set(cp.CAPABILITY_DESCRIPTOR) == expected
    assert len(cp.CAPABILITY_DESCRIPTOR) == len(expected)
    # 字面 authoring 面（AST 可见）必须全部落到在册集里——循环生成的 id 由 builders 自证。
    assert set(_descriptor_authored_ids()) <= {row.capability_id for row in cp.orchestration_descriptor_rows()}
    # 每一行的 provenance 非空且都是已登记的输入源名（派生表不得凭空长出行）。
    known_sources = {
        cp.CAPABILITY_SOURCE_ORCHESTRATION,
        cp.CAPABILITY_SOURCE_ROUTE,
        cp.CAPABILITY_SOURCE_CONTROLLED,
        cp.CAPABILITY_SOURCE_HELP,
        cp.CAPABILITY_SOURCE_INTERFACE,
    }
    for capability_id, row in cp.CAPABILITY_DESCRIPTOR.items():
        assert row.authored_by, f"{capability_id} 无 provenance"
        assert set(row.authored_by) <= known_sources, capability_id
        assert row.capability_id == capability_id


def test_gate_projection_is_behavior_equivalent_to_pre_merge() -> None:
    """迁移前 feature_catalog 的两表内联式 == 唯一表 gate 投影（逐键等价，不许放宽）。"""
    ids = {item.capability_id for item in cr.ROUTE_CAPABILITY_DECLARATIONS if item.has_rule}
    ids.update(cr.CONTROLLED_INTERNAL_CAPABILITIES)
    legacy_bindings = {item: item.replace("bot.", "bot.plugin.", 1) for item in sorted(ids)}
    assert cp.gate_feature_bindings() == legacy_bindings

    legacy_routes = {
        item.capability_id: (item.value, item.label)
        for item in cr.ROUTE_CAPABILITY_DECLARATIONS
        if item.has_rule
    }
    assert cp.gate_route_projection() == legacy_routes
    # 只有 route/controlled 贡献者才可能有 gate id（编排侧/帮助侧不假称受门执法）。
    for capability_id, row in cp.CAPABILITY_DESCRIPTOR.items():
        if row.gate_scoped:
            assert capability_id in legacy_bindings, capability_id
        else:
            assert capability_id not in legacy_bindings, capability_id


def test_feature_gate_consumers_read_the_unique_table() -> None:
    """D-f：feature_catalog 只准 import 唯一表投影，不得再直接读两张旧输入表。"""
    tree = _tree(FEATURE_CATALOG)
    imported_from: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_from.setdefault(node.module, set()).update(alias.name for alias in node.names)
    shell_names = imported_from.get("plugins.bot_unified_runtime.runtime.capability_protocols", set())
    assert "gate_feature_bindings" in shell_names, "gate 绑定未走唯一表"
    for module, names in imported_from.items():
        assert not (names & {"CONTROLLED_INTERNAL_CAPABILITIES", "ROUTE_CAPABILITY_DECLARATIONS"}), (
            f"{module} 直读旧输入表 = 第二消费面回退（D-f 违例）"
        )
    source = FEATURE_CATALOG.read_text(encoding="utf-8")
    assert "for item in ROUTE_CAPABILITY_DECLARATIONS" not in source


def test_no_capability_id_is_authored_in_two_places() -> None:
    """D-a：同一 capability_id 全树只有一处 authoring（两处各自登记即红）。"""
    orchestration = _descriptor_authored_ids()
    route_rows = [(item.kind, item.capability_id) for item in cr.ROUTE_CAPABILITY_DECLARATIONS]
    controlled = list(cr.CONTROLLED_INTERNAL_CAPABILITIES)
    # route 表的键是 RouteKind（同 id 挂两 kind 合法：bot.moegirl=MOEGIRL+MOEGIRL_QUESTION），
    # 「同一 kind 重复登记同一/不同能力」才是重复 authoring。
    for label, keys in (("orchestration", orchestration), ("route", route_rows), ("controlled", controlled)):
        duplicates = {item for item in keys if keys.count(item) > 1}
        assert not duplicates, f"{label} 输入源内部重复登记：{sorted(duplicates)}"
    route = [capability_id for _, capability_id in route_rows]
    clash = (set(orchestration) & set(route)) | (set(orchestration) & set(controlled))
    assert not clash, f"编排侧与注册册为同一 id 各自立了注册：{sorted(clash)}"
    # route 与 controlled 的重叠只允许在「有路由行也仍受门」这一既有语义下发生，
    # 且两条必须派生出同一个 feature id（唯一表冲突检测兜底）。
    for capability_id in set(route) & set(controlled):
        assert cp.CAPABILITY_DESCRIPTOR[capability_id].gate_feature_id == cp._gate_feature_id(capability_id)


def test_route_execution_facets_all_get_envelop_handlers() -> None:
    """A 案机制的牙：注册册每写一行 execution，壳必须真给它挂上信封 handler + 派生描述符。

    缺这锁的后果：`execution` 声明了却因 adapter 不认识/循环漏注册而静默无 handler
    ⇒ 「在册且看似可执行」是假的，invoke 恒 UNAVAILABLE 而门全绿。
    """
    declared = sorted(cp._route_execution_adapters())
    assert declared, "路由执行面整条机制空转（没有任何一行声明 execution）"
    invoker = cp.default_invoker()
    for capability_id in declared:
        assert capability_id in cp._DESCRIPTOR_VIEW, f"{capability_id}: 声明了 execution 却没派生出描述符"
        assert invoker.handlers.get(capability_id) is not None, f"{capability_id}: 无信封 handler"
        # 唯一 authoring 之家＝注册册：壳内不得同时为该 id 写字面 CapabilityDescriptor(
        assert capability_id not in _descriptor_authored_ids(), f"{capability_id}: 壳与注册册两处 authoring"


def test_registration_and_derivation_share_one_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-A/C-03 收口：描述符与 adapter 视图必须**同源同代际**，"半新半旧"要结构上不可能。

    做法＝派生成纯函数（返回 (描述符, adapter) 对，不写全局），两个视图都从同一次调用投影。
    本用例同时证明：注册册多出一行时两侧**一起**看见（不会一边有一边没有）。
    """
    rows = cp._route_execution_rows()
    assert {d.capability_id for d, _ in rows} == set(cp._route_execution_adapters()), "两侧视图脱钩"
    assert {d.capability_id for d in cp._route_execution_descriptors()} == {d.capability_id for d, _ in rows}
    assert rows, "路由执行面整条机制空转（没有任何一行声明 execution）"

    row = next(d for d in cr.ROUTE_CAPABILITY_DECLARATIONS if d.execution is not None)
    twin = dataclasses.replace(row, capability_id="bot.ra_probe", kind="RA_PROBE", value="ra_probe")
    seen = [d for d in cr.ROUTE_CAPABILITY_DECLARATIONS if d.capability_id != row.capability_id] + [twin]
    monkeypatch.setattr(cr, "ROUTE_CAPABILITY_DECLARATIONS", tuple(seen))
    fresh = cp._route_execution_rows()
    assert "bot.ra_probe" in {d.capability_id for d, _ in fresh}
    assert cp._route_execution_adapters().get("bot.ra_probe") == "command", "描述符看见了而 adapter 没看见"


def test_execution_facet_misuse_fails_at_build_not_at_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """派生即校验（R-A/C-02、C-04）：坏 roles / 非法 ref / 未知 adapter ⇒ 装配当场炸；
    `roles_satisfy` 遇"要求侧全是非法角色"宁拒不抛（抛会绕过降级链与审计面）。

    注毒四发各打一处：非法角色名 / ref 指向包外 / ref 缺 `#symbol` / 未实现 adapter。
    """
    assert cp.roles_satisfy(("user",), ("godmode",)) is False
    assert cp.roles_satisfy(("admin",), ("blocked",)) is False

    row = next(d for d in cr.ROUTE_CAPABILITY_DECLARATIONS if d.execution is not None)
    good = row.execution
    poison = [
        dataclasses.replace(good, roles=("sup3r_admin",)),
        dataclasses.replace(good, implementation_ref="../ChatBot_Runtime/venv/pyvenv.cfg#x"),
        dataclasses.replace(good, implementation_ref="plugins/bot_unified_runtime/domains/media/capabilities/tts.py"),
        dataclasses.replace(good, adapter="teleport"),
    ]
    for bad in poison:
        seen = [
            dataclasses.replace(row, execution=bad) if d.capability_id == row.capability_id else d
            for d in cr.ROUTE_CAPABILITY_DECLARATIONS
        ]
        monkeypatch.setattr(cr, "ROUTE_CAPABILITY_DECLARATIONS", tuple(seen))
        with pytest.raises(ValueError):
            cp._route_execution_descriptors()


def test_no_second_descriptor_registration_site() -> None:
    """descriptor 构造点与壳注册表类的实例化点只准存在于壳的一个文件里。"""
    shell_classes = {
        "CapabilityRegistry",
        "HandlerRegistry",
        "FallbackRegistry",
        "HealthProbeRegistry",
        "AuditHookRegistry",
    }
    offenders: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        if path == SHELL:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 非 Python 源
            continue
        relative = path.relative_to(REPO_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name == "CapabilityDescriptor":
                    offenders.append(f"{relative}:{node.lineno} 构造 CapabilityDescriptor")
            elif isinstance(node, (ast.ImportFrom,)) and node.module and node.module.endswith(
                "capability_protocols"
            ):
                leaked = shell_classes & {alias.name for alias in node.names}
                if leaked:
                    offenders.append(f"{relative}:{node.lineno} 从壳 import 注册表类 {sorted(leaked)}")
    assert not offenders, "发现第二处 descriptor authoring 面：\n" + "\n".join(offenders)


def test_handler_and_fallback_ids_must_be_registered_in_unique_table() -> None:
    """invoker 的 handler/fallback 注册只准用唯一表已在册的 id（禁「表里没这条就先通电」）。"""
    tree = _tree(SHELL)
    ids = set(_string_literals_of_call(tree, {"register"}))
    registered = set(cp.CAPABILITY_DESCRIPTOR)
    orphans = {item for item in ids if _CAPABILITY_ID_RE.match(item) and item not in registered}
    assert not orphans, f"handler/fallback 注册了未在册的 capability_id：{sorted(orphans)}"
    # 反向：每条编排侧条目都必须真的被 invoker 收录（无幽灵条目）；
    # invoker 比编排侧**多**出的那些，必须恰好是 A案 route 执行形一行一条派生的 id
    # ——多一条来历不明的注册、或少一条 route 执行形，都当场红（旧写法用 len 相等
    # 只兜住"编排侧不缺席"，route 侧通电后它就是假红，改成显式集合判据）。
    invoker = cp.default_invoker()
    assert set(cp._DESCRIPTOR_VIEW) == {row.capability_id for row in cp.orchestration_descriptor_rows()}
    registry_ids = {item.capability_id for item in invoker.registry.iter()}
    orchestration_ids = {row.capability_id for row in cp.orchestration_descriptor_rows()}
    route_execution_ids = {
        descriptor.capability_id for descriptor, _adapter in cp._route_execution_rows()
    }
    assert registry_ids == orchestration_ids | route_execution_ids, (
        "invoker 收录集必须恰好等于「编排侧 ∪ route 执行形」两路派生："
        f"多出的={sorted(registry_ids - (orchestration_ids | route_execution_ids))} "
        f"缺的={sorted((orchestration_ids | route_execution_ids) - registry_ids)}"
    )


def test_every_input_table_carries_wave2_pointer_comment() -> None:
    """旧表不删但必须紧贴表头写明「已降为唯一表的输入源」——防止下一个 AI 又把它当真源。"""
    registry_lines = REGISTRY.read_text(encoding="utf-8").splitlines()
    for table in (
        "ROUTE_CAPABILITY_DECLARATIONS",
        "CONTROLLED_INTERNAL_CAPABILITIES",
        "HELP_TOPIC_DECLARATIONS",
        "INTERFACE_DECLARATIONS",
    ):
        declared_at = next(
            index
            for index, line in enumerate(registry_lines)
            if line.startswith(f"{table}: tuple")
        )
        window = registry_lines[max(0, declared_at - 8) : declared_at]
        assert any("指针（Wave 2）" in line for line in window), f"{table} 缺 Wave 2 指针注释"
        assert any("CAPABILITY_DESCRIPTOR" in line or "gate_feature_bindings" in line for line in window), table
    shell_text = SHELL.read_text(encoding="utf-8")
    assert "CAPABILITY_DESCRIPTOR" in shell_text and "Wave 2 起" in shell_text


def test_command_catalog_route_derivation_cannot_diverge() -> None:
    """静态解析器 command_catalog 用正则扫 base_router 得路由对——本门锁它不偏离声明源。

    生成物渲染序=判定序（base_router 字面表），与注册册书写序不同，故本波不改写
    该函数（改则需主会话 --write 重录）；先以等值锁消除「两份内容真源」的可能。
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import command_catalog
    except ImportError:  # pragma: no cover - 脚本不可导入时不假绿
        pytest.skip("scripts/command_catalog.py 不可导入")
    derived = set(command_catalog._route_capabilities())
    declared = {
        (item.value, item.capability_id) for item in cr.ROUTE_CAPABILITY_DECLARATIONS if item.has_rule
    }
    assert derived == declared, (
        f"路由能力对漂移：仅生成器有={sorted(derived - declared)} 仅声明源有={sorted(declared - derived)}"
    )


def test_no_capability_id_declares_execution_on_two_rows() -> None:
    """一个 capability id 只准有一行带执行面（R-CENTRAL M-2 的常驻锁）。

    背景：`bot.moegirl` 在 `ROUTE_CAPABILITY_DECLARATIONS` 里有**两行**（两个 RouteKind
    共用一个 id）。中央派生按 id 建描述符，两行都填 `execution=` 会在 import 期抛
    `ValueError`——响亮，但当时没有任何用例钉住"别再填第二行"。本锁把这条从
    "跑起来才知道"变成"提交就红"，且对全表生效（不只 moegirl）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.capability_registry import (
        ROUTE_CAPABILITY_DECLARATIONS,
    )

    seen: dict[str, list[str]] = {}
    for decl in ROUTE_CAPABILITY_DECLARATIONS:
        if getattr(decl, "execution", None) is None:
            continue
        seen.setdefault(decl.capability_id, []).append(decl.kind)
    doubled = {cid: kinds for cid, kinds in seen.items() if len(kinds) > 1}
    assert not doubled, (
        f"这些 id 在不止一行声明了执行面（派生期必炸）：{doubled}"
        "——双行同 id 的家族（如 MOEGIRL 两席）只准填其中一行"
    )
