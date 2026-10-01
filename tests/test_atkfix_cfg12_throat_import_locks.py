"""SEAT-ATKFIX-CFG12（2026-09-28）：F-1 导入咽喉 + F-2 未装配 fail-closed 的**行为与结构双锁**。

钉的是什么
----
F-1（`SQLiteConfigStateStore.import_legacy`）：首次接 backend 时旧实现把 legacy
JSON 覆盖**无条件**灌进权威 SQL 库——改 JSON + 清库/新实例 = 绕开咽喉写 R2 参数。
现在导入循环只带 R0（`config_risk.allows_unattended_change` 当场判），非 R0 拒入
并留一条 `import_refused` 审计；被拒键留在 JSON，不迁不认。

F-2（`RuntimeSettingsStore._throat_guard`）：`_safety_gate_config is None` 旧形态
= 整个咽喉无声放行。现在「未装配」与「门装载失败」同口径 fail-closed：非 R0 当场拒，
唯一豁免是构造时显式 `allow_no_gate=True`（测试/夹具出口；生产面出现即被本件 AST 锁点名）。

结构锁（AST，纯源码，零导入副作用）：
- `import_legacy` 的调用者名册（只许 settings.py::attach_config_backend 与
  factory.py::_get——后者是 `SQLiteFeatureStateStore` 的另一族 import_legacy）；
- 生产面 `RuntimeSettingsStore(...)` 构造名册（新裸构造点必须过审入册）；
- 生产面零 `allow_no_gate=` 实参（豁免通道的唯一入口是显式声明）；
- 档位判据单一真身：`UNATTENDED_CHANGE_TIERS` 等只许在 `config_risk.py` 里定义
  （禁造第二套档位判据）。

全离线：一律 `tmp_path`，不碰 Runtime 真库、不 import NoneBot、不联网。
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

from plugins.bot_unified_runtime.control_plane.config_store import (
    SQLiteConfigStateStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    InstanceSettingsManager,
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk

R0_KEY = "BOT_TRANSPORT_TIMEOUT_SECONDS"
R2_KEY = "BOT_CHAT_TEMPERATURE"
NOT_SETTABLE_KEY = "BOT_TOTALLY_NOT_A_SETTABLE_KEY"
R0_VALUE = 12.0
R2_VALUE = 1.9

CONFIG_RISK_REL = "plugins/bot_unified_runtime/domains/core/safety_exec/config_risk.py"

# ===========================================================================
# 工具：F-1 现场搭建（篡改 JSON → 裸 load → 首次 attach 触发 import_legacy）
# ===========================================================================


def _tamper_legacy_json(dir_path: Path, overrides: dict[str, Any]) -> Path:
    """把篡改值直接写进旧 JSON——模拟「改文件」本身（不过任何写面）。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "runtime_settings_default.json"
    path.write_text(
        json.dumps({"overrides": overrides}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _attach_fresh_backend(store: RuntimeSettingsStore, tmp_path: Path) -> SQLiteConfigStateStore:
    backend = SQLiteConfigStateStore(tmp_path / "config.db", instance=store.instance)
    store.attach_config_backend(backend)
    return backend


# ===========================================================================
# F-1 行为锁：导入也是「改参数」
# ===========================================================================


def test_legacy_import_refuses_non_r0_and_keeps_it_out_of_sql(tmp_path: Path) -> None:
    path = _tamper_legacy_json(
        tmp_path / "legacy", {R2_KEY: R2_VALUE, R0_KEY: R0_VALUE}
    )
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)

    snap = backend.snapshot()
    assert R0_KEY in snap.overrides, "R0 对照组没迁进去——导入腿本身坏了"
    assert snap.overrides[R0_KEY] == R0_VALUE
    assert R2_KEY not in snap.overrides, "R2 未经咽喉就进了权威库——F-1 没修上"
    # attach 之后读面全部换到 SQL：被拒键「留在 JSON，不迁不认」。
    assert store.list_overrides() == {R0_KEY: R0_VALUE}
    assert R2_KEY in json.loads(path.read_text(encoding="utf-8"))["overrides"], (
        "被拒键被顺手删了——拒绝路径不该动旧账"
    )

    rows = backend.changes(since_version=0)
    actions = [row["action"] for row in rows]
    assert actions == ["import", "import_refused"], f"审计形态漂了：{rows}"
    assert [row["version"] for row in rows] == [1, 2]
    assert all(row["actor"] == "legacy_import" for row in rows)
    refused = rows[1]
    assert refused["after"][R2_KEY]["state"] == "default"
    # 拒入审计不许带被篡改的明文值（只留键名与形态）。
    assert str(R2_VALUE) not in json.dumps(refused["after"], ensure_ascii=False)
    assert refused["after"][R2_KEY].get("value") in (None, "default")
    # 版本推进 = 发生的审计事件数（迁入+拒入各占一枚戳）。
    assert snap.version == 2


def test_legacy_import_r0_only_is_byte_identical_to_old_form(tmp_path: Path) -> None:
    """R0-only 的旧合法形态**逐字节保留**：revision 只 +1，审计只有一条 `import`
    （v1），值原样入库。F-1 收紧的是档位，不是搬家流程本身。"""
    path = _tamper_legacy_json(tmp_path / "legacy", {R0_KEY: R0_VALUE})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    snap = backend.snapshot()
    assert snap.overrides == {R0_KEY: R0_VALUE}
    assert snap.version == 1
    rows = backend.changes(since_version=0)
    assert [row["action"] for row in rows] == ["import"]
    assert rows[0]["version"] == 1


def test_legacy_import_refused_only_bumps_one_revision(tmp_path: Path) -> None:
    path = _tamper_legacy_json(tmp_path / "legacy", {R2_KEY: R2_VALUE})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    snap = backend.snapshot()
    assert snap.overrides == {}
    assert snap.version == 1, "只拒入时也占一枚版本戳（事件数=1），不许多跳"
    rows = backend.changes(since_version=0)
    assert [row["action"] for row in rows] == ["import_refused"]


def test_legacy_import_non_settable_keys_stay_silently_skipped(tmp_path: Path) -> None:
    """白名单外的键维持旧形态：既不迁入也不记拒入——它们是「无此参数」，
    不是「被护栏挡下的参数」；混淆这两种形态会污染审计语义。"""
    path = _tamper_legacy_json(tmp_path / "legacy", {NOT_SETTABLE_KEY: "x"})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    assert backend.snapshot().overrides == {}
    assert backend.changes(since_version=0) == []


def test_legacy_import_is_idempotent_after_refusal(tmp_path: Path) -> None:
    path = _tamper_legacy_json(tmp_path / "legacy", {R2_KEY: R2_VALUE, R0_KEY: R0_VALUE})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    before = backend.snapshot()
    assert backend.import_legacy({R2_KEY: 0.1}) is False, "封口后还能再灌——单次消费被破"
    after = backend.snapshot()
    assert (after.version, after.overrides, after.tombstones) == (
        before.version, before.overrides, before.tombstones
    )
    assert len(backend.changes(since_version=0)) == 2


def test_legacy_import_tier_judgement_goes_through_config_risk_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """档位判定必须**当场**问 `config_risk`（单一真身）：把它钳成「什么都不放行」，
    R0 也要被拒——证明导入循环没有第二套判据、也没有把 R0 结果烧进代码里。"""
    monkeypatch.setattr(config_risk, "allows_unattended_change", lambda _x: False)
    path = _tamper_legacy_json(tmp_path / "legacy", {R0_KEY: R0_VALUE})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    assert backend.snapshot().overrides == {}
    rows = backend.changes(since_version=0)
    assert [row["action"] for row in rows] == ["import_refused"]
    assert rows[0]["after"][R0_KEY]["state"] == "default"


def test_legacy_import_fails_closed_when_tier_table_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分级表读不进来（这里把包属性钳成 None 模拟）⇒ 一枚都不带：
    「判不出档但先迁」正是 F-1 要关死的那扇门。"""
    import plugins.bot_unified_runtime.domains.core.safety_exec as safety_exec_pkg

    monkeypatch.setattr(safety_exec_pkg, "config_risk", None, raising=False)
    path = _tamper_legacy_json(tmp_path / "legacy", {R0_KEY: R0_VALUE})
    store = RuntimeSettingsStore(path)
    backend = _attach_fresh_backend(store, tmp_path)
    assert backend.snapshot().overrides == {}
    assert [row["action"] for row in backend.changes(since_version=0)] == ["import_refused"]


# ===========================================================================
# F-2 行为锁：未装配 ≠ 无声放行
# ===========================================================================


def test_naked_store_refuses_non_r0_and_reset_all(tmp_path: Path) -> None:
    bare_store = InstanceSettingsManager(tmp_path / "bare").get("default")
    with pytest.raises(ValueError) as refused:
        bare_store.set_override(R2_KEY, "1.9", actor="qq:1")
    assert "装载失败" in str(refused.value), "拒语没走 `_refuse_without_gate` 同口径"
    assert bare_store.list_overrides() == {}, "被拒的写把值落下去了——拒绝路径泄了"
    # R0 按档仍直写（兜底判据是「按档放行」，不是「一未装全堵」）。
    assert bare_store.set_override(R0_KEY, "45.0", actor="qq:1") == 45.0
    # 聚合目标无单键可分级 ⇒ 落缺省 R2：裸 store 的「全撤」同样当场拒。
    with pytest.raises(ValueError) as reset_all:
        bare_store.reset_override(None, actor="qq:1")
    assert "装载失败" in str(reset_all.value)
    assert bare_store.list_overrides().get(R0_KEY) == 45.0, "被拒的全撤动了已落的值"


def test_opt_out_hatch_is_the_only_old_form_channel(tmp_path: Path) -> None:
    """显式声明 `allow_no_gate=True` 的夹具 store 维持旧形态：R2 写落地、走 JSON。
    这枚出口只许「声明」，不许「默认」——默认放行才是这次的洞。"""
    hatch_store = RuntimeSettingsStore(
        tmp_path / "hatch.json", allow_no_gate=True
    )
    assert hatch_store.set_override(R2_KEY, "1.9", actor="qq:1") is not None
    assert hatch_store.list_overrides()[R2_KEY] == pytest.approx(1.9)
    payload = json.loads((tmp_path / "hatch.json").read_text(encoding="utf-8"))
    assert R2_KEY in payload["overrides"]


# ===========================================================================
# 结构锁（AST 名册）：调用者 / 构造点 / 豁免通道 / 档位判据单一真身
# ===========================================================================

#: `import_legacy` 的合法调用者（rel_path, 最内层函数名；模块级为 None）。
#: settings.py::attach_config_backend —— F-1 本尊（SQLiteConfigStateStore）；
#: factory.py::_get —— `SQLiteFeatureStateStore.import_legacy`，另一族同名方法，
#: 消费的是 feature 开关旧档，与参数咽喉无关（S-ATK-CONFIG 复核确认非漏洞）。
IMPORT_LEGACY_CALLER_ROSTER: dict[tuple[str, str | None], str] = {
    (
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py",
        "attach_config_backend",
    ): "SQLiteConfigStateStore：唯一生产触发点（首 attach 一次性导入）",
    ("plugins/bot_unified_runtime/control_plane/factory.py", "_get"): (
        "同名不同族：SQLiteFeatureStateStore 的 feature 开关导入"
    ),
}

#: 生产面 `RuntimeSettingsStore(...)` 构造名册。全部核对过写面：
#: manager.get 出的 store 都被 configure_safety_gate 装配；_app/backend_unit/
#: prompt_preview 三处是无写面的读视图（控制面/单测后端/预览），无 configure 也
#: 无 mutator 调用者——新增此列外构造点必须先过审，要么走 manager 装配口。
STORE_CONSTRUCTION_ROSTER: dict[tuple[str, str | None], str] = {
    ("plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py", "get"): (
        "manager 惰性建 store（随后 configure_safety_gate 装配）"
    ),
    ("plugins/bot_unified_runtime/control_plane/_app.py", "create_control_plane_app"): "控制面读视图（无写面）",
    ("plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py", "_build_runtime"): (
        "独立后端单元的读视图（无写面）"
    ),
    ("plugins/bot_unified_runtime/domains/chat_reply/runtime/prompt_preview.py", "build_prompt_preview"): (
        "提示词预览读视图（无写面）"
    ),
}

#: 只许在 config_risk.py 里定义的档位判据名（第二套判据的候选形态，一律点名）。
TIER_AUTHORITY_NAMES = frozenset({
    "DEFAULT_TIER",
    "UNATTENDED_CHANGE_TIERS",
    "CONSENT_REQUIRED_TIERS",
    "WRITTEN_CONSENT_TIERS",
    "NEVER_AUTO_TIERS",
    "_TIER_PATTERNS",
})


def _iter_production_sources() -> Iterator[tuple[str, str]]:
    for path in sorted((ROOT / "plugins").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        yield rel, path.read_text(encoding="utf-8")


def _enclosing_functions(tree: ast.Module) -> dict[int, str | None]:
    """node_id -> 最内层 enclosing def 名（模块级为 None）。"""

    def walk(node: ast.AST, current: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            child_current = current
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_current = child.name
            elif isinstance(child, ast.ClassDef):
                child_current = current  # 类体不算「函数」，方法自己会覆盖
            enclosing[id(child)] = child_current
            walk(child, child_current)

    enclosing: dict[int, str | None] = {}
    walk(tree, None)
    return enclosing


def _call_sites(source: str) -> list[tuple[str | None, ast.Call]]:
    tree = ast.parse(source)
    enclosing = _enclosing_functions(tree)
    return [(enclosing.get(id(node)), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _func_of(callee: ast.expr) -> str:
    if isinstance(callee, ast.Name):
        return callee.id
    if isinstance(callee, ast.Attribute):
        return callee.attr
    return ""


def import_legacy_call_violations(rel: str, source: str) -> list[str]:
    problems = []
    for func, call in _call_sites(source):
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "import_legacy"
            and (rel, func) not in IMPORT_LEGACY_CALLER_ROSTER
        ):
            problems.append(f"{rel}::{func} 出现名册外 import_legacy 调用")
    return problems


def store_construction_violations(rel: str, source: str) -> list[str]:
    problems = []
    for func, call in _call_sites(source):
        if _func_of(call.func) != "RuntimeSettingsStore":
            continue
        if (rel, func) not in STORE_CONSTRUCTION_ROSTER:
            problems.append(f"{rel}::{func} 出现名册外 RuntimeSettingsStore 构造")
        for kw in call.keywords:
            if kw.arg == "allow_no_gate":
                problems.append(f"{rel}::{func} 生产面传了 allow_no_gate——豁免通道只许测试声明")
    return problems


def tier_authority_violations(rel: str, source: str) -> list[str]:
    if rel == CONFIG_RISK_REL:
        return []
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in TIER_AUTHORITY_NAMES:
                    problems.append(
                        f"{rel}:{node.lineno} 定义了 {target.id}——禁造第二套档位判据"
                    )
    return problems


def test_production_rosters_are_clean() -> None:
    violations: list[str] = []
    for rel, source in _iter_production_sources():
        violations += import_legacy_call_violations(rel, source)
        violations += store_construction_violations(rel, source)
        violations += tier_authority_violations(rel, source)
    assert violations == [], "名册/单一真身被破：\n" + "\n".join(violations)


def test_rosters_are_not_stale() -> None:
    """名册只许被现实追认、不许空挂死名：每枚在册 (rel, func) 今天必须真有一个
    对应调用/构造点在源码里站着（名册腐坏与名册被绕同样是事故）。"""
    seen: set[tuple[str, str | None]] = set()
    for rel, source in _iter_production_sources():
        for func, call in _call_sites(source):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "import_legacy":
                seen.add((rel, func))
            if _func_of(call.func) == "RuntimeSettingsStore":
                seen.add((rel, func))
    assert seen == set(IMPORT_LEGACY_CALLER_ROSTER) | set(STORE_CONSTRUCTION_ROSTER)


# ---- 注毒自证（纯内存，零落盘）：每把尺都要当场证明它抓得住对应的毒 ----


def _poison(rel: str, extra: str) -> tuple[str, str]:
    path = ROOT / Path(*rel.split("/"))
    source = path.read_text(encoding="utf-8")
    poisoned = source + "\n\n" + extra + "\n"
    assert poisoned != source, "注毒锚点已失效"
    return rel, poisoned


def test_poison_new_import_legacy_caller_is_named() -> None:
    rel = "plugins/bot_unified_runtime/control_plane/sqlite_features.py"
    rel, poisoned = _poison(rel, "_poison_backend.import_legacy({})  # 注毒：新开导入旁路")
    violations = import_legacy_call_violations(rel, poisoned)
    assert any("import_legacy" in problem for problem in violations), f"毒没被抓：{violations}"


def test_poison_new_bare_store_construction_is_named() -> None:
    rel = "plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py"
    rel, poisoned = _poison(rel, "_poison_store = RuntimeSettingsStore()  # 注毒：名册外裸构造")
    violations = store_construction_violations(rel, poisoned)
    assert any("名册外" in problem for problem in violations), f"毒没被抓：{violations}"


def test_poison_production_hatch_claim_is_named() -> None:
    rel = "plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py"
    rel, poisoned = _poison(
        rel, "_poison_store = RuntimeSettingsStore(allow_no_gate=True)  # 注毒：生产偷用豁免通道"
    )
    violations = store_construction_violations(rel, poisoned)
    assert any("allow_no_gate" in problem for problem in violations), f"毒没被抓：{violations}"


def test_poison_second_tier_authority_is_named() -> None:
    rel = "plugins/bot_unified_runtime/control_plane/config_store.py"
    rel, poisoned = _poison(
        rel, "UNATTENDED_CHANGE_TIERS = frozenset()  # 注毒：第二套档位判据出现"
    )
    violations = tier_authority_violations(rel, poisoned)
    assert any("UNATTENDED_CHANGE_TIERS" in problem for problem in violations), (
        f"毒没被抓：{violations}"
    )
