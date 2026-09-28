"""根装配 ``__init__.py`` 戳一戳读点兜底 = ``config.py`` 真身缺省 的 AST 对账锁（ITEM 13 残账 D-2，S-PATCH-POKE-HOST）。

背景（坐标按符号名认，行号当旧账）：``tests/test_poke_five_way_matrix.py`` 的
``test_dispatcher_knob_fallbacks_match_config_defaults`` 只扫**分发器源文件**
（``capabilities/poke.py``）的 ``_knobs`` 读点；根 ``__init__.py`` 里
``_record_poke_affinity``（好感三枚）与跟戳/回复后戳（``ProactiveActionKnobs``
两组旋钮）的 ``getattr(config, "bot_poke_*", 兜底)`` 读点**没有任何等价锁**——
审计票 D-2 正是在这里咬人：好感两枚兜底曾写 0.5/5.0，与真身缺省 0.1/0.5 分岔，
字段装载时永远走不到兜底、生产行为不显，字段一旦缺失就静默按错值走。

判据三块，全离线、零写盘、生产文件零接触（注毒只打在**内存字符串**上）：

① 根文件里每一枚 ``bot_poke_*`` 字面读点（含 ``getattr`` 第三参与 ``or`` 护栏
   两种形态）必须与 ``Config.model_fields`` 的缺省**逐枚等值且同型**——期望值
   从真身现读，测试里一个数字都不抄（规则 10）。
② 自证·非空转：扫描必须认出好感 delta/daily_max 两枚，且 ``getattr-default``
   与 ``or-guard`` 两种形态都看得见（否则 ① 在空跑）。
③ 自证·有牙：往内存副本注两种毒（打歪全部字面兜底 / 打歪全部 ``or`` 护栏），
   锁必须逐枚点名被注毒的键；注毒前后生产文件 sha 不变。

HEAD 语义提示：本锁在「根兜底已对齐真身」的树态全绿；在兜底分岔的旧提交上
①（及对岔键的点名）会红——那是**修复未提交**的证据，不是锁的误报；③ 两枚
自证在两种树态下都绿（断言只依赖注毒副本，不依赖原态对错）。
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic_core import PydanticUndefined

from plugins.bot_unified_runtime.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"

#: 注毒用的必错值：与任何一枚在册旋钮缺省都不像（bool 键靠「类型不同形」拦）。
_POISON = "917.25"

_KEY = r'"(bot_poke_[a-z_]+)"'
# ``getattr(<obj>, "bot_poke_x", <第三参>)``——第三参允许跨行；遇 ')' 即止。
# 现册第三参全是纯字面量；若未来出现带括号的可调用兜底，注毒副本 ast.parse
# 会先炸——红指向锁自身需要换代，属预期告警而非误报。
_DEFAULT_POISON_RE = re.compile(
    r"(getattr\(\s*\w+,\s*" + _KEY + r",\s*)[^)]+?(\))", re.DOTALL
)
# ``getattr(..., <字面>) or <护栏字面>``：护栏是第二枚兜底（挡 0/"" 假值路径），
# 同样必须等于真身缺省。
_GUARD_RE = re.compile(
    r"(getattr\(\s*\w+,\s*" + _KEY + r",\s*[^)]+?\)\s*or\s+)(True|False|[\d.]+)",
    re.DOTALL,
)


def _root_src() -> str:
    return ROOT_INIT.read_text(encoding="utf-8-sig")


def _poke_getattr(node: ast.AST) -> tuple[str, ast.expr] | None:
    """认出 ``getattr(<任意对象>, "bot_poke_*", <字面候选>)`` 三参形态。"""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
        and node.args[1].value.startswith("bot_poke_")
    ):
        return (node.args[1].value, node.args[2])
    return None


def _scan_read_points(src: str) -> list[tuple[str, str, Any]]:
    """AST 现读根文件全部 ``bot_poke_*`` 字面读点 → (键名, 形态, 字面值)。

    形态 ∈ {"getattr-default", "or-guard"}；非字面量一律不收（收了就没法对账）。
    """
    found: list[tuple[str, str, Any]] = []
    for node in ast.walk(ast.parse(src)):
        hit = _poke_getattr(node)
        if hit is not None and isinstance(hit[1], ast.Constant):
            found.append((hit[0], "getattr-default", hit[1].value))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            head = _poke_getattr(node.values[0])
            if head is not None:
                for tail in node.values[1:]:
                    if isinstance(tail, ast.Constant):
                        found.append((head[0], "or-guard", tail.value))
    return found


def _expected_default(key: str) -> tuple[bool, Any]:
    """从 ``Config`` 真身现读缺省；返回 (在册且为标量?, 值)。测试零手抄数字。"""
    field = Config.model_fields.get(key)
    if field is None or field.default is PydanticUndefined:
        return (False, None)
    return (True, field.default)


def _violations(src: str) -> list[str]:
    """逐枚读点对账真身缺省；返回点名串列表（空=全对账）。"""
    problems: list[str] = []
    for key, role, fallback in _scan_read_points(src):
        known, expected = _expected_default(key)
        if not known:
            problems.append(f"{key}: 读点({role})键名不在 config.py 真身名册（或无标量缺省）")
            continue
        if type(fallback) is not type(expected):
            problems.append(
                f"{key}: {role} 兜底 {fallback!r} 与真身缺省 {expected!r} 类型不同形"
            )
        elif fallback != expected:
            problems.append(
                f"{key}: {role} 兜底 {fallback!r} ≠ config.py 缺省 {expected!r}"
            )
    return problems


# ---------------------------------------------------- ① 正判据：兜底=真身缺省


def test_root_poke_knob_fallbacks_match_config_defaults() -> None:
    problems = _violations(_root_src())
    assert not problems, "根装配兜底值与真身缺省不一致：" + "；".join(problems)


# ---------------------------------------------------- ② 自证：扫描非空转


def test_root_knob_lock_is_not_an_empty_scan() -> None:
    pairs = _scan_read_points(_root_src())
    keys = {key for key, _, _ in pairs}
    assert {"bot_poke_affinity_delta", "bot_poke_affinity_daily_max"} <= keys, (
        f"好感读点没被认出（现算只见 {sorted(keys)}）⇒ 锁对本票靶点空转"
    )
    roles = {role for _, role, _ in pairs}
    assert roles == {"getattr-default", "or-guard"}, (
        f"形态视野残缺：只见 {roles}——getattr 第三参与 or 护栏两腿都得看得见"
    )
    assert all(key.startswith("bot_poke_") for key in keys)
    for key in keys:
        assert _expected_default(key)[0], f"{key} 不在真身名册——先查键名再谈对账"


# ---------------------------------------------------- ③ 自证：注毒两腿


def test_root_knob_lock_has_teeth_on_poisoned_defaults() -> None:
    """把全部 getattr 第三参注成 ``_POISON``（内存副本）：每键必被点名。

    生产文件零接触：注毒前后磁盘 sha 逐字节不变。断言只看注毒副本，故在
    「原态即分岔」的旧提交上本判据同样绿——它验的是锁有牙，不是树干净。
    """
    src = _root_src()
    sha_before = hashlib.sha256(ROOT_INIT.read_bytes()).hexdigest()
    poisoned, n_sub = _DEFAULT_POISON_RE.subn(
        lambda m: m.group(1) + _POISON + ")", src
    )
    assert n_sub > 0 and poisoned != src, "注毒正则零命中＝自证在空跑"
    ast.parse(poisoned)  # 注毒副本必须仍是合法语法，否则红指向锁自身失效
    default_keys = {key for key, role, _ in _scan_read_points(src) if role == "getattr-default"}
    problems = _violations(poisoned)
    assert problems, "注毒后零违规＝锁是常量绿"
    unnamed = {
        key
        for key in default_keys
        if not any(key in p and _POISON in p for p in problems)
    }
    assert not unnamed, f"以下键被注毒却没点名：{sorted(unnamed)}"
    assert hashlib.sha256(ROOT_INIT.read_bytes()).hexdigest() == sha_before


def test_root_knob_lock_has_teeth_on_poisoned_guards() -> None:
    """只注歪 ``or`` 护栏（getattr 第三参不动）：护栏腿必须单独有牙。"""
    src = _root_src()
    guarded_keys = {
        key for key, role, _ in _scan_read_points(src) if role == "or-guard"
    }
    assert guarded_keys, "根文件没有 or 护栏形态？先查扫描器再谈本判据"
    poisoned, n_sub = _GUARD_RE.subn(lambda m: m.group(1) + _POISON, src)
    assert n_sub > 0 and poisoned != src, "护栏注毒零命中＝自证在空跑"
    ast.parse(poisoned)
    problems = _violations(poisoned)
    unnamed = {
        key
        for key in guarded_keys
        if not any(key in p and _POISON in p for p in problems)
    }
    assert not unnamed, f"以下护栏键被注毒却没点名：{sorted(unnamed)}"
