"""被动 matcher 第三类认领锁（席7 安全与文档波，2026-10-03）。

判据面（``domains/core/board_taxonomy.py::FeatureNode.passive_matchers`` 的 docstring
是声明源，本件执法）：

- **认领必真**：taxonomoy 里登记的每枚被动 matcher，必须在
  ``plugins/bot_unified_runtime/__init__.py`` 有字面注册 ``name = on_message/on_notice(...)``，
  且注册面与 priority 与登记**同值**（字面锁，行号漂移免疫）；
- **覆盖必全**：``__init__.py`` 里每条 on_message/on_notice 注册，要么其 rule 函数体
  引用 ``_cached_route_decision``（＝走 base_router，由 ``route_kinds`` 认领），要么
  必须被某枚二级功能的 ``passive_matchers`` 认领——漏登记即红（本波立类前的实况）；
- **两腿互斥**：route-backed 的 matcher 不许被 passive_matchers 认领（顶替 RouteKind
  ＝第二真身）；一枚 matcher 不许被两个二级功能同时认领；
- **on_command 出管**：命令面 matcher（``status``/``mail_control`` 族）不属「被动」，
  本锁不管（ADMIN/命令族另有 route_kinds 账）。

全部 AST 现算，不吃任何行号（#50★「行号会漂移」）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.bot_unified_runtime.domains.core.board_taxonomy import (
    BOARD_TAXONOMY,
)

INIT_PY = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_PASSIVE_FUNCS = {"on_message", "on_notice"}


def _registrations() -> dict[str, tuple[str, int | None, str | None]]:
    """AST 提取 ``__init__.py`` 全部 on_message/on_notice 注册：
    ``name -> (注册面, priority, rule 函数名或 None)``。"""
    tree = ast.parse(INIT_PY.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, int | None, str | None]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        func = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
        if func not in _PASSIVE_FUNCS:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            continue
        priority: int | None = None
        rule_name: str | None = None
        for kw in value.keywords:
            if kw.arg == "priority" and isinstance(kw.value, ast.Constant):
                priority = int(kw.value.value)
            if kw.arg == "rule" and isinstance(kw.value, ast.Name):
                rule_name = kw.value.id
        for name in names:
            out[name] = (str(func), priority, rule_name)
    return out


def _route_backed_rules() -> set[str]:
    """rule 函数体内引用 ``_cached_route_decision`` 的函数名集合（route-backed 判据）。"""
    tree = ast.parse(INIT_PY.read_text(encoding="utf-8"))
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "_cached_route_decision" in ast.dump(node):
            hits.add(node.name)
    return hits


def _claimed() -> list[tuple[str, str, int, str]]:
    """taxonomy 全部被动认领：``(matcher 名, 注册面, priority, fid)``。

    动态读模块属性（不 import 绑定）＝内存注毒腿能生效（monkeypatch 换表看得见）。
    """
    from plugins.bot_unified_runtime.domains.core import board_taxonomy as bt

    rows: list[tuple[str, str, int, str]] = []
    for board in bt.BOARD_TAXONOMY:
        for feature in board.features:
            for name, func, priority in feature.passive_matchers:
                rows.append((name, func, priority, feature.fid))
    return rows


def test_every_claimed_passive_matcher_exists_with_matching_shape() -> None:
    """认领必真：登记的名字在册、注册面与 priority 与字面同值。"""
    regs = _registrations()
    assert regs, "AST 提零＝__init__.py 注册形态改版，本锁失明"
    for name, func, priority, fid in _claimed():
        reg = regs.get(name)
        assert reg is not None, f"{fid} 认领的被动 matcher {name} 在 __init__.py 无字面注册"
        real_func, real_priority, _rule = reg
        assert real_func == func, f"{name}（{fid}）注册面漂移：登记 {func}，实际 {real_func}"
        assert real_priority == priority, f"{name}（{fid}）priority 漂移：登记 {priority}，实际 {real_priority}"


def test_every_passive_registration_is_claimed() -> None:
    """覆盖必全：route-backed 之外的每条 on_message/on_notice 注册都必须被认领。"""
    regs = _registrations()
    route_backed = _route_backed_rules()
    claimed_names = {name for name, _f, _p, _fid in _claimed()}
    orphans: list[str] = []
    for name, (_func, _priority, rule) in regs.items():
        if rule is not None and rule in route_backed:
            continue  # 走 base_router 的，由 route_kinds 认领
        if name not in claimed_names:
            orphans.append(name)
    assert not orphans, (
        f"被动 matcher 漏登记（板块树第三类缺认领）：{sorted(orphans)}"
        "——新增旁路 matcher 时必须在 board_taxonomy.py 对应二级功能 passive_matchers 在案"
    )


def test_route_backed_matchers_are_never_claimed_as_passive() -> None:
    """两腿互斥：route-backed 的不许顶替 RouteKind 进被动类（第二真身）。"""
    regs = _registrations()
    route_backed = _route_backed_rules()
    offenders: list[str] = []
    for name, func, _p, fid in _claimed():
        _rf, _rp, rule = regs[name]
        if rule is not None and rule in route_backed:
            offenders.append(f"{name}（{fid}，rule={rule}）")
    assert not offenders, f"route-backed matcher 被认领成被动类：{offenders}"


def test_no_matcher_claimed_by_two_features() -> None:
    """一枚 matcher 一个主人：双认领即红（与 RouteKind 抢认领同一纪律）。"""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for name, _f, _p, fid in _claimed():
        if name in seen:
            dupes.append(f"{name} ⇒ {seen[name]} / {fid}")
        seen[name] = fid
    assert not dupes, f"被动 matcher 被两个二级功能抢：{dupes}"


def test_passive_roster_is_live_not_empty() -> None:
    """活性地板：被动类在册数≥8（本波登记 16 枚；塌到个位数＝登记面被人拆了）。"""
    claimed = _claimed()
    assert len(claimed) >= 8, f"被动认领只剩 {len(claimed)} 枚＝第三类被掏空"


def test_poisoned_claim_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反向自证：往内存塞一枚不存在的 matcher 认领，锁必须当场点名（防空跑）。"""
    import dataclasses

    from plugins.bot_unified_runtime.domains.core import board_taxonomy as bt

    boards = list(BOARD_TAXONOMY)
    poisoned: list[object] = []
    for board in boards:
        feats = list(board.features)
        new_feats = []
        for feat in feats:
            if feat.fid == "B03.chat-reply":
                new_feats.append(dataclasses.replace(
                    feat, passive_matchers=feat.passive_matchers + (("no_such_matcher", "on_message", 1),)
                ))
            else:
                new_feats.append(feat)
        poisoned.append(dataclasses.replace(board, features=tuple(new_feats)))
    monkeypatch.setattr(bt, "BOARD_TAXONOMY", tuple(poisoned))
    regs = _registrations()
    missing = [name for name, _f, _p, fid in _claimed() if name not in regs]
    assert "no_such_matcher" in missing and any(fid == "B03.chat-reply" for _n, _f, _p, fid in _claimed() if fid == "B03.chat-reply")
