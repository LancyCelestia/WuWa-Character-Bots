"""persona 命令面 super_admin 角色门「单一真身」锁（席位 S-FIX-PERSONA-GATE，缺陷 F-A）。

背景（攻击面审计 .superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-PERSONA.md §F-A）：
runtime_admin.py 门谓词（原 :1950）只枚举 persona switch/probability/reset 英文三形，
而处理腿（原 :1705）实收 ``auto`` 与中文 ``概率`` ⇒ 普通 admin 可发 ``persona auto`` /
``persona 概率 <id> <w>`` 越过 super_admin 门改人格状态；且 ``persona --instance <x> switch``
形态令 token 位置绕门。本件锁三件事：

1. **行为腿**（全离线假 store/假 manager，人格册 monkeypatch，零触网零写盘）：
   每一个改状态形态对普通 admin 被拒、对 super_admin 放行到处理腿并落到预期写口；
   只读形态（persona list）对 admin 放行且零写；未知形态一律零写。
2. **结构腿（AST）**：门谓词与处理腿都引用模块级常量 ``_PERSONA_WRITE_ACTIONS``
   （单一真身），门函数体内不得再手抄 persona 动作词字面量（防静默退回硬编码列表）。
3. **注毒自证腿**：全部变异在内存源码字符串副本上做（真文件零字节改动），
   谓词改手抄 / 分派去常量引用 ⇒ 结构锁必红，证明锁真咬人。

persona 形态全集以模块常量为准（从 import 派生，本件不另写 persona 词表容器——
触发词双棘轮零余量）；绕门回放册 `_BYPASS_COMMAND_FORMS` 存的是**整条命令串**
（含 `--instance` 插位与大小写混写两种插法），不是词表，故不与该棘轮相干。
nickname 写面（`add`/`remove`）与 persona 同吃 `gate_parts`，门同病同修，一并点名锁死。
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
ADMIN_REL = "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
_ADMIN_SRC = _ROOT / Path(ADMIN_REL)
_MODULE_NAME = "plugins.bot_unified_runtime.domains.ops.admin.runtime_admin"

DENY_MARK = "需要 super_admin"


def _module() -> Any:
    return importlib.import_module(_MODULE_NAME)


def _write_forms() -> frozenset[str]:
    """从模块常量派生形态全集；常量缺席（修复前）返回空集而非炸采集。"""
    forms = getattr(_module(), "_PERSONA_WRITE_ACTIONS", None)
    return frozenset(forms) if isinstance(forms, frozenset) else frozenset()


# ---------------------------------------------------------------------------
# 行为腿工装：假 store / 假 manager / 假人格册
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, name: str) -> None:
        self.instance = name
        self.config_backend: Any = None
        self.override = "stale-persona"
        self.weights: dict[str, float] = {"alt1": 0.2}
        self.nicknames: list[str] = ["守岸人"]
        self.calls: list[tuple[Any, ...]] = []

    def get_persona_override(self) -> str:
        return self.override

    def set_persona_override(self, profile_id: str) -> None:
        self.calls.append(("override", profile_id))
        self.override = (profile_id or "").strip()

    def get_persona_weights(self) -> dict[str, float]:
        return dict(self.weights)

    def set_persona_weight(self, profile_id: str, weight: float) -> None:
        self.calls.append(("weight", profile_id, float(weight)))
        self.weights[profile_id] = max(0.0, min(1.0, float(weight)))

    # nickname 写面（与 persona 同吃 gate_parts 的同族旁路，取证 §③ 末行）：
    # 记录器只登记调用，绝不落盘。
    def list_nicknames(self) -> list[str]:
        return list(self.nicknames)

    def add_nickname(self, name: str) -> bool:
        self.calls.append(("nickname_add", name))
        self.nicknames.append(name)
        return True

    def remove_nickname(self, name: str) -> bool:
        self.calls.append(("nickname_remove", name))
        if name in self.nicknames:
            self.nicknames.remove(name)
            return True
        return False


class _FakeManager:
    def __init__(self) -> None:
        self.stores = {"default": _FakeStore("default"), "second": _FakeStore("second")}

    def get(self, instance: str) -> _FakeStore:
        return self.stores[instance]

    def list_instances(self) -> list[str]:
        return sorted(self.stores)


@pytest.fixture()
def persona_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile as pp

    spec = SimpleNamespace(display_name="备选人格", weight=0.3, emotions=())
    monkeypatch.setattr(pp, "build_effective_alt_personas", lambda config: {"alt1": spec})


def _drive(command_text: str, roles: list[str]) -> tuple[str, _FakeManager]:
    config = SimpleNamespace(
        bot_persona_profile_id="main",
        bot_persona_display_name="主人格",
    )
    manager = _FakeManager()
    result = _module().build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req-persona-gate",
        actor_roles=roles,
        command_text=command_text,
    )
    return result.body, manager


def _command_for(action: str) -> str:
    if action == "switch":
        return "persona switch alt1"
    if action == "probability" or action == "概率":
        return f"persona {action} alt1 0.5"
    return f"persona {action}"


def _expected_calls(action: str) -> list[tuple[Any, ...]]:
    if action == "switch":
        return [("override", "alt1")]
    if action == "probability" or action == "概率":
        return [("weight", "alt1", 0.5)]
    return [("override", "")]


# ---------------------------------------------------------------------------
# 行为腿：全形态门禁
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", sorted(_write_forms()))
def test_admin_denied_for_every_state_changing_form(
    persona_env: None, action: str
) -> None:
    body, manager = _drive(_command_for(action), ["admin"])
    assert DENY_MARK in body, f"普通 admin 发 {action!r} 形未被 super_admin 门拦下：{body}"
    assert manager.stores["default"].calls == []
    assert manager.stores["second"].calls == []


@pytest.mark.parametrize("action", sorted(_write_forms()))
def test_super_admin_every_form_reaches_processing_leg(
    persona_env: None, action: str
) -> None:
    body, manager = _drive(_command_for(action), ["super_admin"])
    assert DENY_MARK not in body, f"super_admin 发 {action!r} 形被误拦：{body}"
    assert manager.stores["default"].calls == _expected_calls(action)


def test_admin_denied_persona_auto_replay(persona_env: None) -> None:
    """F-A 回放（硬编码，不经常量参数化）：persona auto 曾漏出英文三形门。"""
    body, manager = _drive("persona auto", ["admin"])
    assert DENY_MARK in body, f"persona auto 越过 super_admin 门：{body}"
    assert manager.stores["default"].calls == []


def test_admin_denied_persona_chinese_probability_replay(persona_env: None) -> None:
    """F-A 回放：中文「概率」形曾漏出英文三形门（改切换权重）。"""
    body, manager = _drive("persona 概率 alt1 0.5", ["admin"])
    assert DENY_MARK in body, f"persona 概率 越过 super_admin 门：{body}"
    assert manager.stores["default"].calls == []


def test_admin_denied_persona_switch_with_instance_flag(persona_env: None) -> None:
    """绕门回放：persona --instance <x> switch <id> 以 token 位置躲过 command_parts[:2] 判据。"""
    body, manager = _drive("persona --instance second switch alt1", ["admin"])
    assert DENY_MARK in body, f"--instance 插位绕过 super_admin 门：{body}"
    assert manager.stores["second"].calls == []
    assert manager.stores["default"].calls == []


def test_super_admin_instance_flag_switch_lands_on_target_store(persona_env: None) -> None:
    """同形对 super_admin 放行且写在对的实例 store 上（门禁收紧不得误伤合法面）。"""
    body, manager = _drive("persona --instance second switch alt1", ["super_admin"])
    assert DENY_MARK not in body
    assert manager.stores["second"].calls == [("override", "alt1")]
    assert manager.stores["default"].calls == []


def test_admin_denied_persona_auto_uppercase_mixed(persona_env: None) -> None:
    """大小写归一后同判：门与分派都按 lower 口径，混写不得成为第三条缝。"""
    body, manager = _drive("Persona AUTO", ["admin"])
    assert DENY_MARK in body
    assert manager.stores["default"].calls == []


def test_admin_persona_list_readonly_allowed(persona_env: None) -> None:
    body, manager = _drive("persona list", ["admin"])
    assert DENY_MARK not in body, f"只读形被误拦：{body}"
    assert "当前覆盖" in body
    assert manager.stores["default"].calls == []


def test_unknown_and_bare_persona_forms_write_nothing(persona_env: None) -> None:
    for command_text in ("persona", "persona bogusverb", "persona --instance second"):
        for roles in (["admin"], ["super_admin"]):
            body, manager = _drive(command_text, roles)
            assert manager.stores["default"].calls == [], f"{command_text!r} 不该有写"
            assert manager.stores["second"].calls == [], f"{command_text!r} 不该有写"
            assert DENY_MARK not in body or "用法" in body


def test_super_admin_persona_reset_clears_override(persona_env: None) -> None:
    """reset 形口径统一：门与分派同源后，reset 与 auto 同为清强制切换（历史上门收 reset
    但处理腿只回用法——两向漂移一并收口）。"""
    body, manager = _drive("persona reset", ["super_admin"])
    assert DENY_MARK not in body
    assert manager.stores["default"].calls == [("override", "")]


#: 越权回放形集（取证 S-RECON-PADMIN-20260929.md §③：HEAD 门按裸 `command_parts[:2]`
#: 判，下列每一形在 HEAD 上都实打实落写）。整条命令串而非词表，与触发词棘轮无涉。
_BYPASS_COMMAND_FORMS: tuple[str, ...] = (
    "persona auto",
    "Persona AUTO",
    "persona reset",
    "persona switch alt1",
    "persona probability alt1 0.5",
    "persona 概率 alt1 0.5",
    "persona --instance second auto",
    "persona --instance second reset",
    "persona --instance second switch alt1",
    "persona --instance second probability alt1 0.5",
    "persona --instance second 概率 alt1 0.5",
    "persona switch --instance second alt1",
    "nickname add 小岸",
    "nickname remove 小岸",
    "NICKNAME ADD 小岸",
    "nickname --instance second add 小岸",
    "nickname --instance second remove 小岸",
    "nickname add --instance second 小岸",
    "--instance second persona switch alt1",
    "--instance second nickname add 小岸",
)


@pytest.mark.parametrize("command_text", _BYPASS_COMMAND_FORMS)
def test_admin_denied_for_every_bypass_shape(persona_env: None, command_text: str) -> None:
    """插位、中英别名、大小写混写、flag 落在动作后——super_admin 门只认归一化后的命令。

    判据取「被拒 ∧ 任何实例零写」两枚同现：只查回执串会放过「拦了但还是写了」的半洞。
    """
    body, manager = _drive(command_text, ["admin"])
    assert DENY_MARK in body, f"{command_text!r} 越过 super_admin 门：{body}"
    assert manager.stores["default"].calls == [], f"{command_text!r} 被拒后仍有写"
    assert manager.stores["second"].calls == [], f"{command_text!r} 被拒后仍有写"


@pytest.mark.parametrize("command_text", _BYPASS_COMMAND_FORMS)
def test_super_admin_not_false_blocked_on_bypass_shapes(
    persona_env: None, command_text: str
) -> None:
    """收紧只准往下走：同一形集对 super_admin 一律不得撞门（误拦＝把超管自己的写面也削了）。"""
    body, _manager = _drive(command_text, ["super_admin"])
    assert DENY_MARK not in body, f"super_admin 被误拦：{command_text!r} -> {body}"


def test_super_admin_nickname_instance_flag_lands_on_target_store(persona_env: None) -> None:
    """门归一化不许动处理腿的实例路由：超管的 nickname 写照落 `--instance` 指的那枚 store。"""
    body, manager = _drive("nickname --instance second add 小岸", ["super_admin"])
    assert DENY_MARK not in body
    assert ("nickname_add", "小岸") in manager.stores["second"].calls
    assert manager.stores["default"].calls == []


def test_admin_denied_nickname_list_still_readable(persona_env: None) -> None:
    """只读昵称面不许被写面收紧连坐：admin 发 nickname list 放行且零写。"""
    body, manager = _drive("nickname list", ["admin"])
    assert DENY_MARK not in body, f"只读昵称形被误拦：{body}"
    assert manager.stores["default"].calls == []


def test_constant_covers_every_known_state_changing_form() -> None:
    """形态全集点名锁：摘掉常量里任意一枚形态，本锁与对应回放锁必红。"""
    forms = _write_forms()
    assert "switch" in forms
    assert "probability" in forms
    assert "概率" in forms
    assert "auto" in forms
    assert "reset" in forms
    assert "list" not in forms, "只读形混进改状态名册＝把 admin 的查看权一并锁死"


# ---------------------------------------------------------------------------
# 结构腿（AST）：单一真身
# ---------------------------------------------------------------------------


def _constant_forms(source: str) -> frozenset[str]:
    tree = ast.parse(source)
    found = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(t, ast.Name) and t.id == "_PERSONA_WRITE_ACTIONS"
            for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        )
    ]
    assert len(found) == 1, (
        "_PERSONA_WRITE_ACTIONS 应在模块层恰一枚定义（第二真身或真身被摘都算红）"
    )
    value = found[0].value
    assert value is not None, "常量定义位应含字面量集合（真身塌陷）"
    literals = [
        c.value
        for c in ast.walk(value)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    ]
    assert literals, "常量定义位应含形态字面量（掏空＝真身塌陷）"
    return frozenset(literals)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(hits) == 1, f"{name} 应恰一枚，实={len(hits)}"
    return hits[0]


def check_single_source_locks(source: str) -> None:
    """门谓词与处理腿都吃常量、门函数不再手抄动作词——两腿同红的判据本体。"""
    tree = ast.parse(source)
    gate = _func(tree, "build_runtime_admin_result")
    dispatch = _func(tree, "_handle_persona_command")
    gate_names = {n.id for n in ast.walk(gate) if isinstance(n, ast.Name)}
    dispatch_names = {n.id for n in ast.walk(dispatch) if isinstance(n, ast.Name)}
    assert "_PERSONA_WRITE_ACTIONS" in gate_names, (
        "角色门谓词不再引用 _PERSONA_WRITE_ACTIONS＝静默退回硬编码形态列表（F-A 复发口）"
    )
    assert "_PERSONA_WRITE_ACTIONS" in dispatch_names, (
        "处理腿分派不再引用 _PERSONA_WRITE_ACTIONS＝门与实收两本账（F-A 同型病）"
    )
    forms = _constant_forms(source)
    # reset 在门函数里合法另现：顶层 /bot runtime reset 命令形（与 persona 无关）同函数判权。
    banned = frozenset(w for w in forms if w != "reset")
    gate_strings = {
        c.value
        for c in ast.walk(gate)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    }
    offenders = banned & gate_strings
    assert not offenders, f"门函数内手抄了 persona 动作词字面量（第二真身）：{sorted(offenders)}"
    const_assigns = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(t, ast.Name) and t.id == "_PERSONA_WRITE_ACTIONS"
            for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        )
    ]
    assert len(const_assigns) == 1, "模块层常量必须恰一枚"


def test_single_source_locks_hold_on_live_source() -> None:
    check_single_source_locks(_ADMIN_SRC.read_text(encoding="utf-8"))


def _replace_once(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"注毒目标命中 {src.count(old)} 次，判据不唯一"
    out = src.replace(old, new)
    assert out != src, "注毒未生效（等于空跑）"
    return out


def test_kill_power_reliteralized_predicate_turns_structure_lock_red() -> None:
    """注毒①（内存副本）：把谓词改回硬编码英文三形（F-A 原样）⇒ 结构锁必红。"""
    src = _replace_once(
        _ADMIN_SRC.read_text(encoding="utf-8"),
        "gate_parts[1] in _PERSONA_WRITE_ACTIONS",
        'gate_parts[1] in ("switch", "probability", "reset")',
    )
    with pytest.raises(AssertionError):
        check_single_source_locks(src)


def test_kill_power_dispatch_off_constant_turns_lock_red() -> None:
    """注毒②（内存副本）：处理腿守卫改吃自备字面量集合（门/实收分账）⇒ 结构锁必红。"""
    src = _replace_once(
        _ADMIN_SRC.read_text(encoding="utf-8"),
        "if action not in _PERSONA_WRITE_ACTIONS:",
        'if action not in {"switch", "auto", "probability"}:',
    )
    with pytest.raises(AssertionError):
        check_single_source_locks(src)


def test_kill_power_hollow_constant_turns_lock_red() -> None:
    """注毒③（内存副本）：常量定义位掏空（真身塌陷）⇒ 结构锁必红。"""
    src = re.sub(
        r"_PERSONA_WRITE_ACTIONS: frozenset\[str\] = frozenset\(\{[^}]*\}\)",
        "_PERSONA_WRITE_ACTIONS: frozenset[str] = frozenset(_env_derived_forms())",
        _ADMIN_SRC.read_text(encoding="utf-8"),
        count=1,
    )
    assert src.count("_env_derived_forms()") == 1, "注毒未生效（等于空跑）"
    with pytest.raises(AssertionError):
        check_single_source_locks(src)
