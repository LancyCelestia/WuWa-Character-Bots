"""S13 收尾验收 · 联网判定阈值两枚键的「优先级方向」与「非法值边界」锁。

被锁的机制（真身坐标，2026-09-24 现算）：
  * ``config.py`` 两枚字段 ``bot_web_search_knowledge_threshold`` /
    ``bot_web_search_confidence_floor`` 由根 ``__init__.py`` 作为**装配期实参**
    透传给 ``chat.py`` 的 ``build_chat_capability``（形参
    ``web_knowledge_threshold`` / ``web_confidence_floor``）。
  * 能力体内 ``runtime_settings.get_or("BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD", <装配期值>)``
    是**第二腿**，且它写在第一腿之后 ⇒ 生效值 = store 那份（store 优先于 config）。
  * ``settings.py::_web_ratio_converter`` 是这两枚键进热改白名单时的转换器：
    非法值必须**抛 ValueError 拒绝**，而不是钳制进 [0,1] 后照样写库。

本格锁两件事，都是「方向」而不是「存在」：
  1. **优先级方向**——同一键 store 与 config 给不同值时，生效的必须是 store 那份；
     反序（config 覆盖 store）、摘掉 store 腿、读错键、把 config 腿换成硬编码常量
     这四类改动都必须被本机锁当场点名。
  2. **非法值边界**——>1 / <0 / 非数字 / 空串 / nan / inf 一律被拒，
     且被拒之后库里**不得留下任何覆盖**（否则下次读取就吃了坏判定）。

全离线、零网络、零生产副作用（store 只写 ``tmp_path``）。
注毒一律进程内构造源码 / ``monkeypatch.setitem``，绝不编辑磁盘文件。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _resolve_web_ratio,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    settings as settings_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)

_CHAT_CAPABILITY_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)

# (生效值变量名, store 键, 装配期 config 形参名)
_PRECEDENCE_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("effective_web_knowledge_threshold", "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD", "web_knowledge_threshold"),
    ("effective_web_confidence_floor", "BOT_WEB_SEARCH_CONFIDENCE_FLOOR", "web_confidence_floor"),
)

_GET_OR_ATTR = "get_or"


def _assignments(tree: ast.AST, name: str) -> list[ast.Assign]:
    """按源码顺序返回函数体内对 ``name`` 的所有简单赋值。"""
    found: list[ast.Assign] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(node)
                    break
    return sorted(found, key=lambda n: (n.lineno, n.col_offset))


def _innermost_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """找到「含该赋值」的最内层函数，用于确认赋值真的在能力装配体内部。"""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    best_line = -1
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inner = {id(a) for a in _assignments(node, name)}
        outer = {id(a) for a in _assignments(tree, name)}
        if inner and inner <= outer and node.lineno > best_line:
            best, best_line = node, node.lineno
    return best


def _store_override_if_node(tree: ast.AST, name: str) -> ast.If | None:
    """找到 body 内直接含 ``name`` 赋值的那个 ``if runtime_settings is not None`` 块。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or "runtime_settings" not in ast.unparse(node.test):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in stmt.targets
            ):
                return node
    return None


def _reads_store(value: ast.expr, key: str, config_param: str) -> bool:
    """判定赋值右值是否为 ``get_or("<key>", <config_param>)``（顺序无关、允许外层钳制包装）。"""
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == _GET_OR_ATTR):
            continue
        literals = [n.value for n in node.args if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        if key not in literals:
            continue
        names = {n.id for n in node.args if isinstance(n, ast.Name)}
        names |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == config_param}
        if config_param in names:
            return True
    return False


def audit_precedence(source: str) -> list[str]:
    """返回优先级方向的违规清单；空列表 == 现状正确。

    判据（每条都可被一发注毒单独打红）：
      V1 该变量在能力体内至少被赋值一次；
      V2 **最后一次**赋值必须读 store（``get_or(key, config_param)``）；
      V3 该次赋值必须处于 ``if runtime_settings is not None`` 的保护块内；
      V4 变量↔store 键↔config 形参三者不得错位（错位=读错键/拿错默认值）；
      V5 存在一条**只用装配期 config 值**的赋值且它排在 store 腿之前
         （缺了它=store 无覆盖时没有兜底，也算方向缺陷）。
    """
    violations: list[str] = []
    tree = ast.parse(source)
    for var, key, param in _PRECEDENCE_TARGETS:
        assigns = _assignments(tree, var)
        if not assigns:
            violations.append(f"V1 {var} 在 chat.py 中没有任何赋值")
            continue
        last = assigns[-1]
        if not _reads_store(last.value, key, param):
            violations.append(f"V2 {var} 的最终值没有走 {key} 的 get_or({var} ← {param})")
            continue
        guard = _store_override_if_node(tree, var)
        if guard is None or not any(
            isinstance(s, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == var for t in s.targets)
            for s in guard.body
        ):
            violations.append(f"V3 {var} 的 store 读取不在 runtime_settings 保护块内")
        # 错位检查：另一枚键的字面量不得成为本变量的 get_or 参数
        for node in ast.walk(last.value):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == _GET_OR_ATTR
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        other = (
                            "BOT_WEB_SEARCH_CONFIDENCE_FLOOR"
                            if key == "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"
                            else "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"
                        )
                        if arg.value == other:
                            violations.append(f"V4 {var} 读了另一枚键 {other}")
        if not any(not _reads_store(a.value, key, param) for a in assigns[:-1]):
            violations.append(f"V5 {var} 缺少排在 store 腿之前的装配期 config 兜底赋值")
    return violations


@pytest.fixture(scope="module")
def chat_source() -> str:
    assert _CHAT_CAPABILITY_PATH.exists(), _CHAT_CAPABILITY_PATH
    return _CHAT_CAPABILITY_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) 优先级方向：行为腿（真 store 对象，非重写实现）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [t[1] for t in _PRECEDENCE_TARGETS])
def test_store_override_beats_assembly_time_config(tmp_path: Path, key: str) -> None:
    """同一键 store 与 config 给不同值 ⇒ 生效的必须是 store 那份。

    ``config_default`` 代表装配期从 ``config.py`` 透传进能力的值；
    chat.py 唯一取数口是 ``get_or(key, config_default)``，所以这条锁的是
    「覆盖优先」这一方向本身，不是重复实现一遍判定。
    """
    # allow_no_gate：F-2 后裸构造 store 写非 R0 键会被咽喉门拒；本族锁 store>config
    # 优先级与 converter 拒绝，档位执法另由 test_atkfix_cfg12_throat_import_locks 锁。
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    config_default = 0.60 if key.endswith("THRESHOLD") else 0.20
    # 控制组：库里没有这条覆盖时，取数口必须回落到装配期 config 值。
    assert store.get_or(key, config_default) == pytest.approx(config_default)
    store_value = "0.90" if key.endswith("THRESHOLD") else "0.05"
    store.set_override(key, store_value)
    effective = store.get_or(key, config_default)
    assert effective == pytest.approx(float(store_value)), (
        f"{key}：store 已写入 {store_value} 而生效值仍是 {effective} ⇒ 覆盖没赢过 config"
    )
    # 两向都钉死：config 那份绝不能再把 store 顶掉。
    assert effective != pytest.approx(config_default)


@pytest.mark.parametrize("key", [t[1] for t in _PRECEDENCE_TARGETS])
def test_reset_override_restores_config_precedence(tmp_path: Path, key: str) -> None:
    """撤销覆盖后必须回到 config 那份（防止「store 里其实一直是空的」被当成方向正确）。"""
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    config_default = 0.60 if key.endswith("THRESHOLD") else 0.20
    store.set_override(key, "0.90" if key.endswith("THRESHOLD") else "0.05")
    assert store.get_or(key, config_default) != pytest.approx(config_default)
    assert store.reset_override(key) == 1
    assert store.get_or(key, config_default) == pytest.approx(config_default)


def test_store_precedence_survives_reload_from_disk(tmp_path: Path) -> None:
    """覆盖落盘后由**新实例**读回仍然优先——生产是跨进程重启后继续生效的那一条。"""
    path = tmp_path / "runtime_settings.json"
    writer = RuntimeSettingsStore(path, allow_no_gate=True)
    writer.set_override("BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD", "0.90")
    reloaded = RuntimeSettingsStore(path, allow_no_gate=True)
    assert reloaded.get_or("BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD", 0.60) == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# 2) 优先级方向：接线腿（真 chat.py 源码结构锁 + 四发进程内注毒）
# ---------------------------------------------------------------------------

def test_effective_thresholds_read_store_last_in_chat_source(chat_source: str) -> None:
    assert audit_precedence(chat_source) == []


def _override_block(chat_source: str) -> tuple[str, str]:
    """取出 store 覆盖那一整块（``if runtime_settings is not None:`` 的源码片段）与其缩进。"""
    tree = ast.parse(chat_source)
    guard = _store_override_if_node(tree, _PRECEDENCE_TARGETS[0][0])
    assert guard is not None, "找不到 store 覆盖块——前置结构锁已失效"
    segment = ast.get_source_segment(chat_source, guard)
    assert segment
    return segment, " " * guard.col_offset


def test_poison_dropping_store_leg_is_detected(chat_source: str) -> None:
    segment, _ = _override_block(chat_source)
    mutated = chat_source.replace(segment, "pass  # poison: store 腿被摘掉")
    assert mutated != chat_source
    assert audit_precedence(mutated)


def test_poison_reversed_precedence_is_detected(chat_source: str) -> None:
    """config 腿被挪到 store 腿**之后** ⇒ 覆盖被顶掉，必须点名。"""
    segment, indent = _override_block(chat_source)
    appended = segment + (
        f"\n{indent}effective_web_knowledge_threshold = max(0.0, min(1.0, float(web_knowledge_threshold)))"
        f"\n{indent}effective_web_confidence_floor = max(0.0, min(1.0, float(web_confidence_floor)))"
    )
    mutated = chat_source.replace(segment, appended)
    assert mutated != chat_source
    assert audit_precedence(mutated)


def test_poison_swapped_store_keys_is_detected(chat_source: str) -> None:
    mutated = chat_source.replace(
        '"BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"', '"BOT_WEB_SEARCH_CONFIDENCE_FLOOR"'
    )
    assert mutated != chat_source
    assert audit_precedence(mutated)


def test_poison_hardcoded_default_instead_of_config_is_detected(chat_source: str) -> None:
    """get_or 的兜底写成常量 ⇒ 装配期 config 值再也不参与判定（方向被偷偷改成「只有 store」）。

    注毒定位方式改过一版：旧代码按文本 `replace("web_knowledge_threshold,", "0.60,")` 下手，
    而本窗把越界拒绝口写成 `fallback=web_knowledge_threshold,` 之后，**同一串文本先命中了
    fallback 实参**——毒注到别处、门却照样绿（一发实测当场把它打成 `assert audit_precedence` 失败
    才发现）。现在按 `get_or("<key>", <param>)` 的调用形状定位，只可能打到兜底位。
    """
    segment, _ = _override_block(chat_source)
    poisoned_segment = segment
    total = 0
    for _var, key, param in _PRECEDENCE_TARGETS:
        pattern = re.compile(
            r'(get_or\(\s*"' + re.escape(key) + r'",\s*)' + re.escape(param)
        )
        poisoned_segment, hits = pattern.subn(r"\g<1>0.60", poisoned_segment)
        total += hits
    assert total == 2, f"注毒点没落在兜底位（命中 {total}）"
    assert poisoned_segment != segment
    mutated = chat_source.replace(segment, poisoned_segment)
    assert mutated != chat_source
    assert audit_precedence(mutated)


# ---------------------------------------------------------------------------
# 3) 非法值边界：converter 必须拒，不得静默钳制、不得写坏判定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "1.5",   # 越上界
        "1.0001",
        "1e5",
        "-0.1",  # 越下界
        "-1",
        "abc",   # 非数字
        "",
        "   ",
        "0.6abc",
        "nan",   # 概率域外的浮点
        "inf",
        "-inf",
    ],
)
def test_illegal_threshold_values_are_rejected_not_clamped(tmp_path: Path, raw: str) -> None:
    # allow_no_gate 不可省：不豁免时咽喉门也会抛同型 ValueError，会把「converter 被摘出
    # 白名单／坏成钳制」伪造成拒绝而假绿。豁免后门旁路，本锁的牙才唯一落在 converter。
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    key = "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"
    with pytest.raises(ValueError):
        store.set_override(key, raw)
    # 拒了还不算完：库里绝不能留下这枚坏值。
    assert key not in store.list_overrides()
    assert store.get_or(key, 0.60) == pytest.approx(0.60)


@pytest.mark.parametrize("key", ["BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD", "BOT_WEB_SEARCH_CONFIDENCE_FLOOR"])
def test_illegal_floor_values_rejected_too(tmp_path: Path, key: str) -> None:
    # 同 test_illegal_threshold_values_are_rejected_not_clamped：豁免咽喉门，
    # 确保 ValueError 只可能来自 converter 而非门（禁假绿）。
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    for raw in ("1.5", "-0.1", "abc", "nan"):
        with pytest.raises(ValueError):
            store.set_override(key, raw)
    assert store.list_overrides() == {}


@pytest.mark.parametrize("raw", ["0", "0.0", "1", "1.0", " 0.60 ", "0.2"])
def test_legal_closed_interval_values_are_accepted_verbatim(tmp_path: Path, raw: str) -> None:
    """闭区间端点必须放行——否则上一条「拒绝」可以是「什么都拒」这种假锁。"""
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    key = "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"
    assert store.set_override(key, raw) == pytest.approx(float(raw.strip()))
    assert store.get_or(key, 0.60) == pytest.approx(float(raw.strip()))


def test_both_keys_are_hot_settable_and_not_restart_frozen() -> None:
    """登记方向：两枚键必须是可热改（有每消息现读点），且绝不在 RESTART 冻结名单里。

    若被误登记进 ``RESTART_REQUIRED_KEYS``，``set_override`` 会在白名单校验前
    直接拒绝（settings.py 的 C-09 治理路径），本席上面所有 store 覆盖用例当场红。
    """
    for _, key, _ in _PRECEDENCE_TARGETS:
        assert key in SETTABLE_KEYS, f"{key} 未登记热改白名单 ⇒ store 覆盖这条路是死的"
        assert key not in RESTART_REQUIRED_KEYS, f"{key} 被冻结 ⇒ 与 get_or 现读点自相矛盾"
        assert SETTABLE_KEYS[key] is settings_mod._web_ratio_converter


def test_poison_clamping_converter_is_caught_by_rejection_lock(tmp_path: Path, monkeypatch) -> None:
    """注毒自证：把 converter 换成「钳制不拒」，非法值就会**悄悄写进库**。

    这一条不是给生产码加分，而是证明 ``test_illegal_..._are_rejected_not_clamped``
    真的有牙——它咬的是「拒 vs 钳」这个区别，不是「随便抛个异常」。
    """

    def _clamping(raw: str) -> float:
        return max(0.0, min(1.0, float(str(raw).strip())))

    key = "BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD"
    monkeypatch.setitem(SETTABLE_KEYS, key, _clamping)
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    store.set_override(key, "1.5")  # 钳制型 converter 不拒 ⇒ 坏值入库
    assert store.get_or(key, 0.60) == pytest.approx(1.0)


# ==================== 读侧：越界值「拒绝并点名」而不是夹到边界（S-W25 §BLOCKED 的落地） ==================== #

def _ratio_notes() -> list[str]:
    return []


def test_read_side_rejects_out_of_range_and_names_the_source() -> None:
    notes = _ratio_notes()
    assert _resolve_web_ratio("1.5", source="override.T", notes=notes, fallback=0.6) == 0.6
    assert notes == ["web_threshold_out_of_range:override.T"]
    # 非数值同样拒绝（旧写法在这两处会抛 ValueError 打断这一轮聊天，或直接夹成边界）
    assert _resolve_web_ratio("abc", source="override.T", notes=notes, fallback=0.6) == 0.6
    assert _resolve_web_ratio(-0.1, source="override.T", notes=notes, fallback=0.6) == 0.6
    # 同一天同一来源只点名一次，不刷日志/不刷标签
    assert len(notes) == 1


def test_read_side_accepts_in_range_and_keeps_precision() -> None:
    notes = _ratio_notes()
    assert _resolve_web_ratio(0.42, source="config.T", notes=notes) == 0.42
    assert _resolve_web_ratio("0", source="config.T", notes=notes) == 0.0
    assert _resolve_web_ratio("1.0", source="config.T", notes=notes) == 1.0
    assert notes == []


def test_chat_read_path_uses_the_rejecting_helper_everywhere() -> None:
    """两处阈值 × 两来源（装配值与运行时覆盖）都必须走同一拒绝口，禁再出现内联 min/max 夹用。"""
    tree = ast.parse(_CHAT_CAPABILITY_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_web_ratio"
    ]
    assert len(calls) == 4, f"读侧拒绝口调用点应恰为 4，现 {len(calls)}"
    sources = {
        ast.unparse(kw.value).strip().strip("'").strip('"')
        for call in calls
        for kw in call.keywords
        if kw.arg == "source"
    }
    assert sources == {
        "config.bot_web_search_knowledge_threshold",
        "config.bot_web_search_confidence_floor",
        "override.BOT_WEB_SEARCH_KNOWLEDGE_THRESHOLD",
        "override.BOT_WEB_SEARCH_CONFIDENCE_FLOOR",
    }, f"来源点名不全覆盖：{sorted(sources)}"
