"""FACETS 扩册候选表·机械化产线（S32 · 中央调度收编波 · 2026-09-24）.

一句话——为 `domains/core/capability_manifest.py::FACETS` 还没申报的每一枚在册能力，
把「要不要申报、申报成什么」变成**照抄机器输出**的活，而不是逐枚考古。

## 它回答什么（每枚在册 id 一行候选）
  · `entry_kinds`   八个入口形态各一格，每格带**判定依据 + 文件:行号**；取不到证据显式 `none` + 原因。
  · `direct_callsites` 唯一直呼点（invoke / 汇合缝 / 泛型执行器 / 缝外直呼四类站点全列，判「唯一/多处/零处」）。
  · `triggers`      触发词 + **真身位置**（指针，绝不抄词表；指针按 G-CM 门④的 `_resolve_symbol` 现验）。
  · `config_keys`   键 + 出处类别（执行面申报 / 帮助侧表自述 / 板块前缀命中 / 执行体模块内真实读点）。
  · `executable`    `路径#符号` 是否**解析得到**（判据直接加载 G-CM 门的 `_resolve_symbol`，不抄第二份）。
  · `tags`          可给标签 + **票根出处**：`tests/xxx.py::用例` 且本件**实跑过并绿**。
                    以下三样按本仓纪律**都不算票根**：HTTP 200、文档/注释散文、`_HELP_ENTRY_META.tests`
                    的自述（自述只当"去哪儿找票"的线索，最后一步必须是跑出来的结果）。
                    另分 `mention-only`（用例体内只提 id 字面量、无调用性证据）——那类是
                    "存在性糊过活性判据"，同样不算票根，但会列出来供人复核。
                    ⚠ 例外一枚：`serves-image`（用户裁定 D3=B 扩枚）**不靠词面提候选**，
                    而是直接问 G-CM 门㉖ 的派生尺 `derive_image_serving_sites()`
                    （"执行体把既有图像装进结果契约 `images=`"是现算出来的，不是猜出来的）。

## 分桶（互斥主桶，优先级 B4>B3>B2>B1>B0；全量成员账单列，防"归不进桶=消失"）
  B1 有票根可直接入册 / B2 有执行体无票根 / B3 无执行体（在册必有执行面欠账）
  / B4 触发词有副本需先归一 / B0 证据不足无法归桶（显式点名）

## 复用不复制（铁律 6「禁第二真身」）
  名册真身   `runtime/capability_protocols.py::CAPABILITY_DESCRIPTOR`（运行时 import；本件**不**另立 id 集）
  入口/站点  `scripts/central_seam_census.py --json`（S01 尺；本件只读其产物，不重扫一遍判据）
  触发词     `scripts/extract_trigger_words.py`（T-Spec 提取器 + 跨能力冲突判据）
  执行体判据 `tests/test_capability_manifest_gate.py::_resolve_symbol`（G-CM 门②④的尺，importlib 按路径加载）
  图像交付判据 `tests/test_capability_manifest_gate.py::derive_image_serving_sites`（G-CM 门㉖ 的尺，同上按路径加载）
  板块       `domains/core/board_taxonomy.py::BOARD_TAXONOMY`
  配置       `config.py` 字段名 + 上述各出处表

## 输出与退出码
  `--markdown`（缺省，人读）/ `--json`（机读）——同一份账的两个出口，不是两套判据。
  结果**只打 stdout**（本件不写任何仓内文件；要存档请自行重定向到仓外）。
  0 正常 / 2 某份真身读不出或量具跑不动（**缺件即红，绝不降级成"没扫到=没问题"**）
  / 3 票根实跑有批次崩掉（该批格子记 unknown，不当"无票"）。

## 复跑命令（环境咒语见 .superpowers/sdd/2026-09-24-central-dispatch/BRIEFS.md 前言）
  PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
  PYTHONPYCACHEPREFIX="$TEMP/s32-pyc" ../ChatBot_Runtime/venv/Scripts/python.exe \\
      scripts/facets_candidate_dump.py --markdown
  … 同上 … scripts/facets_candidate_dump.py --json
  … 同上 … scripts/facets_candidate_dump.py --buckets-only        # 只出分桶汇总
  … 同上 … scripts/facets_candidate_dump.py --cid bot.weather     # 单枚全明细
  … 同上 … scripts/facets_candidate_dump.py --tickets=collect      # 只收候选不跑（该次不得入册）
  … 同上 … scripts/facets_candidate_dump.py --tickets=off          # 跳票根（该次**不得**入册）
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

VERSION = "0.1.0"
CENSUS = REPO_ROOT / "scripts" / "central_seam_census.py"
GATE_TEST = REPO_ROOT / "tests" / "test_capability_manifest_gate.py"
ROOT_INIT = PKG_ROOT / "__init__.py"
CONFIG_PY = PKG_ROOT / "config.py"
CONTROL_PLANE_DIR = PKG_ROOT / "control_plane"
VOICE_FACES = (
    PKG_ROOT / "domains" / "chat_reply" / "runtime" / "progress_ack.py",
    PKG_ROOT / "domains" / "chat_reply" / "runtime" / "voice_enricher.py",
)
SUBPROCESS_TIMEOUT = 900

#: 本件自带的在册地板（防"名册被缩而本件跟着沉默"；与门里的 REGISTERED_FLOOR 各自独立计数）。
#: 现算时点 2026-09-24 本席实跑 = 120。只准降不准涨。
REGISTERED_FLOOR = 120

_NONE = "none"
#: 主动投递族「dedupe_namespace → 能力 id」目前**没有**在册映射（根文件只写 namespace）。
#: 本件禁建第二真身，故遇到这种情况一律记 unknown+原因，见 §6 与 `why_no` 文本。
PUSH_NAMESPACE_HINTS: dict[str, str] = {
    "reminder": "bot.reminder",
    "digest_push": "bot.group_digest_push",
    "daily_assist": "bot.daily_assist",
    "cookie-expiry": "bot.cookie_expiry（未在册则本席不猜）",
    "emg": "bot.emergency_info",
}

BUCKET_LABEL = {
    "B1": "有票根可直接入册",
    "B2": "有执行体无票根",
    "B3": "无执行体（在册必有执行面欠账）",
    "B4": "触发词有副本需先归一",
    "B0": "证据不足无法归桶",
}
BUCKET_ACTION = {
    "B1": "照抄本格 entry_kinds/tags/trigger_source 进 FACETS，并把 `UNCOVERED_CEILING` 同步下调同枚数"
          "（降账须由现算证据驱动；多入口活性锁与申报锁**同时成立**才许降，见 HANDOFF-UNIFY §禁碰面）",
    "B2": "先让候选用例真跑到绿（`--json` 的 `tickets.executed_candidates_strong` 给了件与用例名），"
          "再照抄申报；禁止把 mention-only 用例当票根",
    "B3": "先补 `handler_ref`（或诚实挂进 `PLACEHOLDER_UNIMPLEMENTED` 让缺位可见），再走 B1/B2；"
          "此桶非空期间门⑤基线不许降",
    "B4": "先按中央触发词件（`domains/core/text_boundary.py` 及路由真身）归一副本，"
          "归一后回本表复算——禁在本席册里抄第二份词表",
    "B0": "人工定入口形态；若判据该修，去改普查件（尺）而不是给这枚手写申报",
}


class SourceError(RuntimeError):
    """真身读不出 / 量具跑不动 ⇒ 整件红（不许把失明读成空集）。"""


# ==========================================================================
# 真身加载
# ==========================================================================
def load_roster() -> dict[str, Any]:
    """唯一在册表（运行时 import＝名册真身本身；本件绝不另立一份 id 集）。"""
    try:
        from plugins.bot_unified_runtime.domains.core import capability_manifest as cm
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:
        raise SourceError(f"名册/本册 import 失败：{type(exc).__name__}: {exc}") from exc
    return {"cm": cm, "descriptor": cp.CAPABILITY_DESCRIPTOR, "ids": cp.registered_capability_ids()}


_GATE_ATTRS = ("_resolve_symbol", "EXECUTION_SURFACE_BASELINE", "DECLARED_UNWIRED_BASELINE",
               "PLACEHOLDER_BASELINE", "REGISTERED_FLOOR", "derive_image_serving_sites")


def load_gate_module() -> Any:
    """按路径加载 G-CM 门件，取其判据与基线常量（复用判据，不抄第二份）。"""
    if not GATE_TEST.is_file():
        raise SourceError(f"缺件：{GATE_TEST}")
    spec = importlib.util.spec_from_file_location("_s32_gate_predicates", GATE_TEST)
    if spec is None or spec.loader is None:
        raise SourceError(f"门件无法加载：{GATE_TEST}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise SourceError(f"门件执行失败（{', '.join(_GATE_ATTRS)} 取不到）：{type(exc).__name__}: {exc}") from exc
    for attr in _GATE_ATTRS:
        if not hasattr(module, attr):
            raise SourceError(f"门件缺属性 {attr} ⇒ 本件的判据/基线无处可取")
    return module


def load_census() -> dict[str, Any]:
    """S01 缝外普查件（入口/站点唯一尺）；跑不动或自报不完整 ⇒ 整件红。"""
    if not CENSUS.is_file():
        raise SourceError(f"缺件：{CENSUS}")
    out = _run_python([str(CENSUS), "--json"])
    if out.returncode != 0:
        raise SourceError(f"普查件 RC={out.returncode}：{(out.stderr or '')[-400:]}")
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise SourceError(f"普查件 stdout 非 JSON：{exc}") from exc
    roster = payload.get("roster")
    if not isinstance(roster, dict) or not roster:
        raise SourceError("普查件 roster 为空＝量具瞎了")
    integrity = payload.get("integrity") or {}
    if not integrity.get("ok"):
        raise SourceError(f"普查件自报不完整（缺件/读不出/语法错）：{json.dumps(integrity, ensure_ascii=False)[:400]}")
    return payload


def load_trigger_tables() -> dict[str, Any]:
    """T-Spec 提取器（触发词 + 跨能力冲突）；不可用 ⇒ 整件红。"""
    try:
        import extract_trigger_words as etw
        inventory = etw.build_inventory()
    except Exception as exc:
        raise SourceError(f"触发词提取器不可用：{type(exc).__name__}: {exc}") from exc

    capabilities: dict[str, dict[str, Any]] = {}
    for cid, item in (inventory.get("capabilities") or {}).items():
        reports: list[dict[str, Any]] = []
        modules: dict[str, set[str]] = {}
        for rep in item.get("detectors") or []:
            module = rep.get("module") or ""
            reports.append({"name": rep.get("name"), "module": module,
                            "file_rel": _module_to_rel(module),
                            "word_count": len(rep.get("words") or [])})
            if rep.get("name"):
                modules.setdefault(str(rep["name"]), set()).add(module or "?")
        capabilities[cid] = {
            "kinds": list(item.get("kinds") or []),
            "verified_triggers": sorted(item.get("verified_triggers") or []),
            "passive_words": sorted(item.get("passive_words") or []),
            "detector_reports": reports,
            "detector_modules": {k: sorted(v) for k, v in modules.items()},
        }

    word_owners: dict[str, set[str]] = {}
    for cid, item in capabilities.items():
        for word in item["verified_triggers"]:
            word_owners.setdefault(etw.normalize_trigger_key(word) or word, set()).add(cid)
    verb_groups = {k: list(v) for k, v in (inventory.get("verb_map_groups") or {}).items()}
    for cid, verbs in verb_groups.items():
        for verb in verbs:
            word_owners.setdefault(etw.normalize_trigger_key(verb) or verb, set()).add(cid)

    conflicts_by_cid: dict[str, list[str]] = {}
    raw_conflicts = inventory.get("cross_capability_conflicts") or []
    # 行形态必须现读，不许按猜的键名取数：本席第一版用 `capabilities`/`hits` 取命中列，
    # 真身其实叫 `hit_capabilities` ⇒ 取不到就静默成空表 ⇒ B4 **假零**（把"没有副本"写进报告）。
    # 现在：认不出一行 ⇒ 整件红，绝不把"我没读懂"写成"没有"。
    for row in raw_conflicts:
        if not isinstance(row, dict):
            raise SourceError(f"跨能力冲突行形态不认识（非 dict）：{row!r}")
        probe = next((row[k] for k in ("probe", "word", "text", "sample")
                      if isinstance(row.get(k), str) and row.get(k)), None)
        hit_key = next((k for k in ("hit_capabilities", "capabilities", "hits", "matched",
                                    "conflicts_with") if isinstance(row.get(k), list)), None)
        hits = list(row[hit_key]) if hit_key else []
        if isinstance(row.get("capability_id"), str):
            hits = sorted(set(hits) | {row["capability_id"]})
        if probe is None or not hits:
            raise SourceError(f"跨能力冲突行缺探针或缺命中列，实到键={sorted(row)} ⇒ "
                              "本席拒绝把读不懂当成「没有副本」")
        for cid in hits:
            conflicts_by_cid.setdefault(cid, []).append(f"{probe} → {'、'.join(sorted(hits))}")

    return {"capabilities": capabilities, "verb_map_groups": verb_groups,
            "help_topics": inventory.get("help_topics") or {},
            "word_owners": word_owners, "conflicts_by_cid": conflicts_by_cid,
            "conflicts_total": len(raw_conflicts),
            "ascii_boundary_violations": len(inventory.get("ascii_boundary_violations") or [])}


def _module_to_rel(module: str) -> str:
    if not module.startswith("plugins."):
        return ""
    return module.replace("plugins.bot_unified_runtime", "plugins/bot_unified_runtime").replace(".", "/") + ".py"


def load_boards() -> dict[str, list[dict[str, Any]]]:
    """cid → 板块认领（由 board_taxonomy 现派生，不手抄）。"""
    try:
        from plugins.bot_unified_runtime.domains.core import board_taxonomy as bt
    except Exception as exc:
        raise SourceError(f"板块声明源读不出：{type(exc).__name__}: {exc}") from exc
    index: dict[str, list[dict[str, Any]]] = {}
    for board in bt.BOARD_TAXONOMY:
        for feature in board.features:
            for cid in feature.capability_ids:
                index.setdefault(cid, []).append({
                    "bid": board.bid, "board_label": board.label, "fid": feature.fid,
                    "feature_label": feature.label, "slug": feature.slug,
                    "config_prefixes": list(feature.config_prefixes), "matched_by": "capability_ids"})
    return index


def load_config_fields() -> frozenset[str]:
    """`config.py` 的 `bot_*` 字段名（真身 AST；本件只列名不抄值）。"""
    names: set[str] = set()
    for node in _parse(CONFIG_PY).body:
        for sub in ast.walk(node):
            if (isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name)
                    and sub.target.id.startswith("bot_")):
                names.add(sub.target.id)
    return frozenset(names)


def load_route_decls() -> dict[str, Any]:
    """路由声明（执行面 config_keys / matcher / command 旗标）+ 受门在册 + 管线管理形。"""
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
            capability_registry as cr,
        )
    except Exception as exc:
        raise SourceError(f"路由声明源读不出：{type(exc).__name__}: {exc}") from exc
    grouped: dict[str, list[dict[str, Any]]] = {}
    for decl in cr.ROUTE_CAPABILITY_DECLARATIONS:
        grouped.setdefault(decl.capability_id, []).append({
            "kind": decl.kind, "value": decl.value, "priority": decl.priority, "label": decl.label,
            "matcher_name": decl.matcher_name, "has_rule": decl.has_rule, "command": decl.command,
            "tags": list(decl.tags),
            "execution": None if decl.execution is None else {
                "implementation_ref": decl.execution.implementation_ref, "adapter": decl.execution.adapter,
                "family": decl.execution.family, "config_keys": list(decl.execution.config_keys),
                "health_probe": decl.execution.health_probe}})
    return {"by_cid": grouped,
            "controlled": list(cr.CONTROLLED_INTERNAL_CAPABILITIES),
            "pipeline_managed": {p.capability_id: p.implementation_ref
                                 for p in cr.PIPELINE_MANAGED_CAPABILITY_DECLARATIONS},
            "command_route_kinds": frozenset(cr.COMMAND_ROUTE_KIND_NAMES)}


def load_help_meta() -> dict[str, dict[str, Any]]:
    """echo 帮助侧表（capability / config_vars / triggers_nl / triggers_nickname / tests 自述列）。"""
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    except Exception as exc:
        raise SourceError(f"echo 帮助侧表读不出：{type(exc).__name__}: {exc}") from exc
    return dict(echo._HELP_ENTRY_META)


# ==========================================================================
# AST 小工具（本件自己的站点定位；不重做别人的判据）
# ==========================================================================
_TREES: dict[Path, ast.Module] = {}


def _parse(path: Path) -> ast.Module:
    cached = _TREES.get(path)
    if cached is not None:
        return cached
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise SourceError(f"{_rel(path)} 读不出/解析失败：{type(exc).__name__}: {exc}") from exc
    _TREES[path] = tree
    return tree


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _cid_literals(node: ast.AST, known: frozenset[str]) -> dict[str, list[int]]:
    """子树里出现的**在册** cid 字面量 → 行号（只认在册集内的串，防把散文当 id）。"""
    found: dict[str, list[int]] = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in known:
            found.setdefault(sub.value, []).append(getattr(sub, "lineno", 0))
    return found


def _iter_funcs(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            yield node


def _nearest_bindings(tree: ast.Module) -> dict[str, Any]:
    """根文件里每一处 **在册绑定**：`capability_id=`/`capability=` 关键字的字符串字面量。

    只认关键字值这一种形态（而不是"函数体内任意位置提到过这个串"）。原因：
    `_register_nonebot_handlers` 是个巨型函数，若按"体内出现即归因"，会把几十个 id
    同时判成"主动投递"——那是把假账写进候选表（本席禁）。
    每条绑定带：cid、行号、**最近外层函数**（含嵌套链名）、该函数自己的调用集。
    """
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def qual(func: ast.AST) -> str:
        chain: list[str] = []
        node: ast.AST | None = func
        while isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            chain.append(node.name)
            node = parents.get(node)
        return ".".join(reversed(chain))

    def nearest_func(node: ast.AST) -> ast.AST | None:
        cursor = parents.get(node)
        while cursor is not None:
            if isinstance(cursor, ast.AsyncFunctionDef | ast.FunctionDef):
                return cursor
            cursor = parents.get(cursor)
        return None

    funcs: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            funcs.setdefault(qual(node), node)

    rows: list[dict[str, Any]] = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        for kw in call.keywords:
            if kw.arg not in {"capability_id", "capability"} or not isinstance(kw.value, ast.Constant):
                continue
            value = kw.value.value
            if not isinstance(value, str):
                continue
            owner = nearest_func(call)
            rows.append({
                "text": value, "line": call.lineno, "callee": _callee(call),
                "func": qual(owner) if owner is not None else "<module>",
                "func_node": owner,
                "func_calls": sorted({_callee(c) for c in ast.walk(owner) if isinstance(c, ast.Call)})
                if owner is not None else [],
                "decorators": [ast.dump(d)[:60] for d in getattr(owner, "decorator_list", [])]
                if owner is not None else [],
            })
    return {"rows": rows, "funcs": funcs, "qual": qual}


def _is_scheduler_name(qualified: str) -> bool:
    """`_register_*_scheduler` 形态名（可能是嵌套链，取末段判）。"""
    leaf = qualified.rpartition(".")[2]
    return leaf.startswith("_register_") and leaf.endswith("_scheduler")


def index_root_init(known: frozenset[str]) -> dict[str, Any]:
    """根 `__init__.py` 的装配期站点索引（matcher / 主动投递 / 调度器可达面）。

    三张子账的判据（全部 AST 现算，只认 `capability_id=` 字面量绑定）：
      · matcher：`X = on_message/on_command/on_notice(...)` → `@X.handle()` 装饰的函数；
        带回 matcher 的 `block=`（`block=False` = 不改写回复 = 被动监听语义）。
      · push：绑定所在函数**自己**调用 `submit_active_push` / `_push_via_central_exit_now`
        （只认直接调用者，不把"上游函数也调过"算进来）。
      · scheduler：绑定所在函数可从某个 `_register_*_scheduler` 沿调用图（含
        `add_job(f`/`f=f` 这种把函数当实参交的边）在 ≤3 步内到达；到达即记"调度驱动"，
        边与深度都写进依据，人可复核。
    """
    tree = _parse(ROOT_INIT)
    rel = _rel(ROOT_INIT)
    bindings = _nearest_bindings(tree)
    rows: list[dict[str, Any]] = bindings["rows"]
    funcs: dict[str, ast.AST] = bindings["funcs"]

    # matcher 注册与 handler 归属
    matcher_reg: dict[str, tuple[int, Any, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = _callee(node.value)
            if fn in {"on_message", "on_command", "on_notice"}:
                block_kw = next((k for k in node.value.keywords if k.arg == "block"), None)
                block_value = block_kw.value if block_kw is not None else None
                block = block_value.value if isinstance(block_value, ast.Constant) else None
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        matcher_reg.setdefault(target.id, (node.lineno, block, fn))
    handler_owner: dict[str, str] = {}
    for owner_key, func_node in funcs.items():
        if not isinstance(func_node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for dec in func_node.decorator_list:
            inner = dec.func if isinstance(dec, ast.Call) else dec
            owner = getattr(getattr(inner, "value", None), "id", "")
            if owner in matcher_reg:
                handler_owner[owner_key] = owner
                break

    # 调度驱动面判据（**只做一跳，不做传递闭包**——闭包会把 `_register_nonebot_handlers`
    # 那种"启动期兄弟"也拖进来，实测会把 bot.alias/bot.search/bot.status 误判成调度驱动）：
    #   (a) 词法：绑定所在函数的外层链里有 `_register_*_scheduler`（调度器就地闭包）；
    #   (b) 一跳：某个 `_register_*_scheduler` 的体内（含其嵌套闭包）以**裸名调用**或
    #       **把函数名当实参交出**（`add_job(f, ...)` 形态）引用了绑定所在函数。
    #   两者都把证据行号写进依据，人工可复核。
    # 只认**模块级、且名字唯一**的函数做一跳目标：根文件里有几十个叫 `capability` 的嵌套闭包，
    # 按裸名连边会把 `bot.alias`/`bot.search`/`bot.reply` 全误判成"调度驱动"
    # （本席实测踩过：不缩面时 scheduler 桶虚涨到 17 枚，逐条查站点全是 `fn=capability` 假命中）。
    top_defs: dict[str, list[ast.AST]] = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            top_defs.setdefault(node.name, []).append(node)
    ambiguous = sorted(k for k, v in top_defs.items() if len(v) > 1)
    unique_top = {k: v[0] for k, v in top_defs.items() if len(v) == 1}
    sched_funcs = {q: f for q, f in funcs.items() if _is_scheduler_name(q) and q in unique_top}

    # 一跳引用**只认模块级函数名**：嵌套闭包的重名（根文件里有几十个叫 `capability` 的闭包）
    # 跨作用域不可解析，按裸名连边会把 `bot.alias`/`bot.search` 之类误判成"调度驱动"
    # （本席实测踩过：判据不缩面时 scheduler 桶 13→17 枚全是这种假命中）。
    one_hop: dict[str, list[tuple[str, int]]] = {}   # 被引用函数名 → [(调度器名, 引用行)]
    for sched_name, sched_node in sched_funcs.items():
        for node in ast.walk(sched_node):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in unique_top:
                one_hop.setdefault(node.func.id, []).append((sched_name, node.lineno))
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, ast.Name) and arg.id in unique_top:
                    one_hop.setdefault(arg.id, []).append((sched_name, arg.lineno))

    out: dict[str, Any] = {"push": {}, "scheduler": {}, "passive": {}, "blocking_matcher": {},
                           "file": rel, "matcher_count": len(matcher_reg),
                           "scheduler_roots": sorted(sched_funcs),
                           # 盲区显式化：这些模块级名字不唯一 ⇒ 本席不做一跳归因（宁可少记不误记）
                           "ambiguous_top_level_names": ambiguous}
    for row in rows:
        cid = _match_known(row["text"], known)
        if cid is None:
            continue
        qname: str = row["func"]
        leaf = qname.rpartition(".")[2]
        site = {"file": rel, "line": row["line"], "fn": leaf, "fn_path": qname, "carrier": row["callee"]}
        # ① matcher 归属（含 block 旗标）
        owner = handler_owner.get(qname)
        if owner is not None:
            reg_line, block, kind = matcher_reg[owner]
            entry = {**site, "matcher": owner, "matcher_line": reg_line, "matcher_kind": kind,
                     "block": block}
            out["passive" if block is False else "blocking_matcher"].setdefault(cid, []).append(entry)
        # ② 主动投递：绑定所在函数**自己**调中央出口
        if set(row["func_calls"]) & {"submit_active_push", "_push_via_central_exit_now"}:
            out["push"].setdefault(cid, []).append(site)
        # ③ 调度驱动：(a) 词法在调度器体内 或 (b) 被调度器体一跳引用
        if any(_is_scheduler_name(part) for part in qname.split(".")):
            out["scheduler"].setdefault(cid, []).append({**site, "rule": "a-lexical"})
        for ref_qname, ref_line in (one_hop.get(leaf, []) if "." not in qname else []):
            out["scheduler"].setdefault(cid, []).append(
                {**site, "rule": "b-one-hop", "scheduler_fn": ref_qname, "referenced_at": ref_line})
    return out


def _match_known(text: str, known: frozenset[str]) -> str | None:
    """`capability_id=` 的值可能是 f-string 片段或带后缀串；只认**精确等值**在册 id。"""
    return text if text in known else None


def index_dir_for_cids(root: Path, known: frozenset[str], label: str) -> dict[str, list[dict[str, Any]]]:
    """某个面（控制面 / 语音回执面）内的在册绑定站点（同样只认 `capability_id=` 关键字）。"""
    hits: dict[str, list[dict[str, Any]]] = {}
    paths = sorted(root.rglob("*.py")) if root.is_dir() else [p for p in (root,) if p.is_file()]
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue  # 非名册真身面：单文件读不出只降该文件，不谎称整面为空
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for kw in call.keywords:
                if kw.arg not in {"capability_id", "capability"} or not isinstance(kw.value, ast.Constant):
                    continue
                cid = _match_known(str(kw.value.value), known)
                if cid is None:
                    continue
                owner: ast.AST | None = parents.get(call)
                while owner is not None and not isinstance(owner, ast.AsyncFunctionDef | ast.FunctionDef):
                    owner = parents.get(owner)
                hits.setdefault(cid, []).append({
                    "file": _rel(path), "line": call.lineno, "carrier": _callee(call),
                    "fn": getattr(owner, "name", "<module>"), "face": label})
    return hits


# ==========================================================================
# 每枚 id 的候选装配
# ==========================================================================
def build_candidate(cid: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """一枚 id 的全部候选格：每格要么给证据，要么 `none` + 为什么取不到。"""
    reg = ctx["descriptor"][cid]
    cm = ctx["cm"]
    resolve = ctx["gate"]._resolve_symbol
    census_row = ctx["census"]["roster"].get(cid)
    census_visible = census_row is not None
    handler_ref = getattr(reg, "handler_ref", "") or ""
    ref_path = handler_ref.split("#", 1)[0] if "#" in handler_ref else ""
    routes = [{"kind": r.kind, "value": r.value, "priority": r.priority, "label": r.label,
               "matcher_name": r.matcher_name, "has_rule": r.has_rule, "command": r.command}
              for r in getattr(reg, "routes", ())]
    topics = [t.topic for t in getattr(reg, "help_topics", ())]
    entry_forms = sorted((census_row or {}).get("entry_forms") or [])
    route_decls = ctx["routes"]["by_cid"].get(cid, [])
    boards = ctx["boards"].get(cid, [])
    tables = ctx["triggers"]

    # ---------------- 执行体 ----------------
    resolves = bool(handler_ref) and bool(resolve(handler_ref))
    file_exists = bool(ref_path) and any(
        (base / ref_path).is_file() for base in (REPO_ROOT, PKG_ROOT)) or bool(ref_path) and Path(ref_path).is_file()
    if resolves:
        why_exec = _NONE
    elif not handler_ref:
        why_exec = ("handler_ref 为空：本行仅由 " + "+".join(sorted(getattr(reg, "authored_by", ()))) +
                    " 路输入派生，没有任何一处 author 执行面（教义「在册必有执行面」的欠账）")
    elif not file_exists:
        why_exec = f"handler_ref 指向的文件不在盘：{handler_ref}"
    else:
        why_exec = f"文件在盘但符号解析不到：{handler_ref}（G-CM `_resolve_symbol` 现判 False）"
    executable = {
        "handler_ref": handler_ref or _NONE, "resolves": resolves, "file_exists": bool(file_exists),
        "placeholder_reserved": handler_ref.endswith("#reserved"), "why_not_resolved": why_exec,
        "census_state": (census_row or {}).get("state", _NONE) if census_visible else
                        "census-invisible：普查件只认 AST 的 `capability_id=` 字面量，"
                        "本枚由 interface_id=/controlled_internal 单路派生 ⇒ 它看不见≠它没有",
        "declared_execution_refs": [d["execution"]["implementation_ref"]
                                    for d in route_decls if d.get("execution")],
        "pipeline_managed_ref": ctx["routes"]["pipeline_managed"].get(cid, _NONE),
    }

    # ---------------- 直呼点 ----------------
    def _sites(key: str) -> list[dict[str, Any]]:
        return list((census_row or {}).get(key) or [])

    invoke_sites, seam_sites = _sites("invoke_sites"), _sites("seam_sites")
    generic_sites, offseam_sites = _sites("generic_sites"), _sites("offseam_sites")
    prod = invoke_sites + seam_sites + generic_sites + offseam_sites
    direct = {
        "count": len(prod),
        "verdict": "unique" if len(prod) == 1 else "multiple" if len(prod) > 1 else "zero",
        "invoke": [_fmt_site(s) for s in invoke_sites] or _NONE,
        "seam": [_fmt_site(s) for s in seam_sites] or _NONE,
        "generic_executor": [_fmt_site(s) for s in generic_sites] or _NONE,
        "offseam": [_fmt_site(s) for s in offseam_sites] or _NONE,
        "why_zero": _NONE if prod else (
            "全树零生产调用点（在册未接＝缺口账；门 leg3b 的 DECLARED_UNWIRED 记这本账）"
            if census_visible else "普查对本枚失明 ⇒ 不能断言零调用，须补尺或人工复核"),
    }

    # ---------------- 入口形态八格 ----------------
    ek: dict[str, dict[str, Any]] = {k.value: {"verdict": "no", "basis": []} for k in cm.EntryKind}

    def _hit(kind: Any, basis: str, sites: list[dict[str, Any]] | None = None, note: str = "") -> None:
        cell = ek[kind.value]
        cell["verdict"] = "candidate"
        text = basis + (f"  〔{note}〕" if note else "")
        if sites:
            text += "  @" + " | ".join(_fmt_site(s) for s in sites[:3])
        if text not in cell["basis"]:
            cell["basis"].append(text)

    cmd_routes = [r for r in routes if r["command"]]
    if cmd_routes:
        _hit(cm.EntryKind.COMMAND, "路由声明 command=True（RouteRule 在册）", note="kinds=" +
             ",".join(sorted({str(r["kind"]) for r in cmd_routes})) +
             "；priorities=" + ",".join(str(r["priority"]) for r in cmd_routes))
    elif "命令" in entry_forms:
        _hit(cm.EntryKind.COMMAND, "普查入口形态=命令（调用点包络函数链判定）")
    else:
        ek["command"]["why_no"] = "无 command=True 路由行，普查入口形态亦无「命令」"

    blocking_sites = ctx["root_index"].get("blocking_matcher", {}).get(cid, [])
    if blocking_sites:
        _hit(cm.EntryKind.COMMAND, "根 NoneBot matcher 闭包（block=True）内以 `capability_id=` 绑定本 id",
             blocking_sites[:2])

    if any(r["kind"] == "ALIAS" for r in routes):
        # 注意：ALIAS 是**结构位**（昵称动词由中央解析器承担），不是"某个动词表的指针"。
        # 曾把"它有一条 ALIAS 行"写成"它没有触发词真身"⇒ 门④会问"指针在哪"而这里答不出。
        _hit(cm.EntryKind.ALIAS, "路由声明 kind=ALIAS（结构位：昵称命令解析器，见 base_router）",
             note="词表真身不在本枚名下，故 trigger_source 不给假指针")
    elif cid in tables["verb_map_groups"]:
        _hit(cm.EntryKind.ALIAS, "runtime/aliases.py DEFAULT_VERB_MAP 动词指向本 id",
             note="verbs=" + ",".join(tables["verb_map_groups"][cid][:8]))
    elif "别名" in entry_forms:
        _hit(cm.EntryKind.ALIAS, "普查入口形态=别名")
    else:
        ek["alias"]["why_no"] = "无 ALIAS 路由行、不在 DEFAULT_VERB_MAP、普查入口形态无「别名」"

    nl_words = sorted({str(w) for topic in topics
                       for w in ((ctx["help_meta"].get(topic) or {}).get("triggers_nl") or ())})
    if any(r["kind"] == "NATURAL_COMMAND" for r in routes):
        _hit(cm.EntryKind.NATURAL_LANGUAGE, "路由声明 kind=NATURAL_COMMAND")
    elif nl_words:
        _hit(cm.EntryKind.NATURAL_LANGUAGE, "echo._HELP_ENTRY_META.triggers_nl 非空（真身=echo 侧表）",
             note="triggers_nl=" + ",".join(nl_words[:8]))
    elif "自然语言" in entry_forms:
        _hit(cm.EntryKind.NATURAL_LANGUAGE, "普查入口形态=自然语言")
    else:
        ek["natural_language"]["why_no"] = "无 NATURAL_COMMAND 行、META 无 triggers_nl、普查无「自然语言」"

    push_sites = ctx["root_index"]["push"].get(cid, [])
    if push_sites:
        _hit(cm.EntryKind.ACTIVE_PUSH, "根装配现场：同函数体内既有本 id 又有 submit_active_push/SendRequest",
             push_sites)
    elif "主动投递" in entry_forms:
        _hit(cm.EntryKind.ACTIVE_PUSH, "普查入口形态=主动投递（`_push*`/`_deliver*`/`*_job` 包络）")
    else:
        ns = [n for n, mapped in PUSH_NAMESPACE_HINTS.items() if mapped.split("（")[0] == cid]
        ek["active_push"]["why_no"] = (
            "根投递点无本 id 字面量、普查入口形态无「主动投递」" +
            (f"（提示：namespace `{ns[0]}` 在册映射待补，见 §6）" if ns else
             "；若它其实走主动投递，那是投递点只写 dedupe_namespace 导致不可归因 ⇒ 需先在册"
             "「namespace→能力 id」映射，本席禁建第二真身"))

    if cid in ctx["ack_index"]:
        _hit(cm.EntryKind.VOICE_ACK, "语音/等待回执面（progress_ack/voice_enricher）内出现本 id",
             ctx["ack_index"][cid])
    elif "语音回执" in entry_forms:
        _hit(cm.EntryKind.VOICE_ACK, "普查入口形态=语音回执")
    else:
        ek["voice_ack"]["why_no"] = "不在 progress_ack/voice_enricher 字面量内，普查无「语音回执」"

    sched_sites = ctx["root_index"]["scheduler"].get(cid, [])
    if sched_sites:
        _hit(cm.EntryKind.SCHEDULER, "根 `_register_*_scheduler` 函数体内出现本 id", sched_sites)
    else:
        ek["scheduler"]["why_no"] = "不在任何 `_register_*_scheduler` 体内（含 cron 直投但不带 id 的写法）"

    cp_sites = ctx["cp_index"].get(cid, [])
    if cp_sites:
        _hit(cm.EntryKind.CONTROL_PLANE, "control_plane/** 内出现本 id", cp_sites)
    else:
        ek["control_plane"]["why_no"] = "control_plane 目录零字面量引用（含 features 节点表）"

    passive_sites = ctx["root_index"]["passive"].get(cid, [])
    non_blocking = [s for s in passive_sites if s.get("block") is False]
    if non_blocking:
        _hit(cm.EntryKind.PASSIVE_MATCHER, "根 on_message(block=False) 闭包体内出现本 id（被动监听语义）",
             non_blocking)
    elif passive_sites:
        _hit(cm.EntryKind.PASSIVE_MATCHER, "根 matcher 闭包引用本 id，但该 matcher `block=True`（会改写回复）",
             passive_sites, note="严格义偏「命令」而非「被动」，申报前人工确认这格要不要给")
    else:
        ek["passive_matcher"]["why_no"] = "不在任何 on_message/on_command 闭包体内出现"

    # ---------------- 触发词 + 真身指针 ----------------
    trig = tables["capabilities"].get(cid)
    words = sorted(trig["verified_triggers"]) if trig else []
    help_alias_index = tables["help_topics"]
    aliases = sorted({str(w) for topic in topics for w in
                      (list((help_alias_index.get(topic) or {}).get("aliases") or ()) +
                       list((help_alias_index.get(topic) or {}).get("triggers_nickname") or ()))})
    verb_map = sorted(tables["verb_map_groups"].get(cid, []))
    pointer, pointer_basis = _pick_trigger_source(handler_ref, topics, trig, resolve)
    any_words = bool(words or aliases or verb_map)
    triggers_cell = {
        "verified_triggers": words if words else (_NONE if trig is not None else "none（提取器无本枚行）"),
        "passive_words": (sorted(trig["passive_words"]) if trig and trig["passive_words"]
                          else _NONE if trig is not None else "none（提取器无本枚行）"),
        "help_aliases_or_nickname": aliases or _NONE,
        "verb_map": verb_map or _NONE,
        "trigger_source_pointer": pointer or _NONE,
        "pointer_basis": pointer_basis,
        "pointer_resolves_by_gate_leg4": bool(pointer) and bool(resolve(pointer)),
        "detectors": (trig or {}).get("detector_reports") or _NONE,
        "why_no_words": _NONE if any_words else (
            "提取器覆盖两路（路由 `is_*` 行为检测器 + help 侧词表）皆零命中，且本枚不在 DEFAULT_VERB_MAP"
            f"（路由行数={len(routes)}，help 主题={topics or '无'}）⇒ 它今天**没有**触发词真身，"
            "别为它编一个指针；要申报命令面得先立真身"),
    }

    # ---------------- 触发词副本账 ----------------
    own_words = {w for w in words + aliases + verb_map}
    shared = sorted({
        f"'{word}' 亦被 {'、'.join(sorted(others))} 认领"
        for word in sorted(own_words)
        for others in [ctx["word_index"].get(word, set()) - {cid}] if others})
    multi_module = sorted({
        f"{name} 在 {len(mods)} 个模块各有一份：{', '.join(mods)}"
        for name, mods in ((trig or {}).get("detector_modules") or {}).items() if len(mods) > 1})
    conflicts = sorted(set(ctx["triggers"]["conflicts_by_cid"].get(cid, [])))
    copy_cell = {
        "cross_capability_conflicts": conflicts or _NONE,
        "words_shared_with_other_caps": shared or _NONE,
        "same_detector_in_multiple_modules": multi_module or _NONE,
        "needs_normalization": bool(conflicts or multi_module),
    }

    # ---------------- 配置键 ----------------
    keys: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add_key(raw: Any, provenance: str) -> None:
        token = str(raw).strip()
        if not token:
            return
        lowered = token.lower()
        field = lowered if lowered in ctx["config_fields"] else (
            lowered[4:] if lowered.startswith("bot_") and f"bot_{lowered[4:]}" in ctx["config_fields"] else "")
        if field:
            if field in seen:
                return
            seen.add(field)
            keys.append({"key": field, "provenance": provenance, "in_config_py": "yes"})
        else:
            if token in seen:
                return
            seen.add(token)
            keys.append({"key": token, "provenance": provenance,
                         "in_config_py": "no（该串不在 config.py 字段名内：可能是 env 变量名，或出处表已漂移）"})

    for decl in route_decls:
        for key in (decl.get("execution") or {}).get("config_keys", []):
            _add_key(key, f"capability_registry 执行面申报（kind={decl['kind']}）")
    for topic in topics:
        for key in (ctx["help_meta"].get(topic) or {}).get("config_vars", ()):
            _add_key(key, f"echo._HELP_ENTRY_META[{topic}].config_vars（自述列，非执法）")
    prefixes = sorted({p for b in boards for p in b["config_prefixes"]})
    for prefix in prefixes:
        for field in sorted(f for f in ctx["config_fields"] if f.startswith(prefix)):
            _add_key(field, f"board_taxonomy 板块前缀 {prefix}*（前缀命中，未逐键核实归属）")
    for key in _module_config_reads(handler_ref):
        _add_key(key, f"执行体模块内真实读点 {ref_path}")
    config_cell = {"keys": keys or _NONE, "count": len(keys),
                   "prefixes_used": prefixes or _NONE,
                   "why_none": _NONE if keys else
                   "四路出处（执行面申报 / help config_vars / 板块前缀 / 模块内读点）全零命中"}

    tags = _propose_tags(cid, reg, routes, handler_ref, topics, ctx)

    return {
        "capability_id": cid, "title": getattr(reg, "title", "") or _NONE,
        "family": getattr(getattr(reg, "family", None), "value", None) or _NONE,
        "interface_id": getattr(reg, "interface_id", "") or _NONE,
        "gate_feature_id": getattr(reg, "gate_feature_id", "") or _NONE,
        "authored_by": sorted(getattr(reg, "authored_by", ())),
        "routes": routes or _NONE, "help_topics": topics or _NONE,
        "census_visible": census_visible, "entry_forms_from_census": entry_forms or _NONE,
        "executable": executable, "direct_callsites": direct, "entry_kinds": ek,
        "triggers": triggers_cell, "trigger_copies": copy_cell,
        "config_keys": config_cell, "tags": tags, "board": boards or _NONE,
    }


def _fmt_site(site: dict[str, Any]) -> str:
    bits = [f"{site.get('file')}:{site.get('line')}"]
    for key, label in (("fn", "fn"), ("enclosing", "fn"), ("symbol", "sym"),
                       ("matcher", "matcher"), ("tag", "tag"), ("face", "face")):
        if site.get(key):
            bits.append(f"{label}={site[key]}")
            break
    return " ".join(str(b) for b in bits)


def _pick_trigger_source(handler_ref: str, topics: list[str], trig: dict[str, Any] | None,
                         resolve: Any) -> tuple[str, str]:
    """挑一个**能过门④ `_resolve_symbol`** 的触发词真身指针（指针，不是词表副本）。"""
    candidates: list[tuple[str, str]] = []
    if handler_ref and "#" in handler_ref:
        module = handler_ref.split("#", 1)[0]
        for symbol in ("DEFAULT_TRIGGER_WORDS", "TRIGGER_WORDS", "_TRIGGER_WORDS", "TRIGGER_WORDS_CN",
                       "ALIASES", "_ALIASES", "COMMAND_WORDS"):
            candidates.append((f"{module}#{symbol}", f"执行体同模块词表符号 {symbol}"))
    for rep in ((trig or {}).get("detector_reports") or []):
        if rep.get("file_rel") and rep.get("name"):
            candidates.append((f"{rep['file_rel']}#{rep['name']}", "路由行为检测器（is_*）真身"))
    if topics:
        joined = "/".join(topics)
        candidates += [
            ("domains/chat_reply/capabilities/echo.py#_HELP_ENTRIES", f"帮助主题词表真身（topic={joined}）"),
            ("domains/chat_reply/runtime/capability_registry.py#ROUTE_CAPABILITY_DECLARATIONS", "路由声明表"),
            ("domains/chat_reply/runtime/aliases.py#DEFAULT_VERB_MAP", "别名动词表"),
        ]
    for ref, basis in candidates:
        if resolve(ref):
            return ref, basis
    return (candidates[0][0] if candidates else "",
            "候选指针全部解析失败（保留首条供人工核，本席不硬凑）" if candidates
            else "无任何候选：既无执行体同模块词表、也无路由检测器、也无 help 主题")


def _module_config_reads(handler_ref: str) -> list[str]:
    """执行体模块内 `config.bot_x` / `getattr(config, "bot_x")` 真实读点（键归属最硬的一路）。"""
    if "#" not in handler_ref:
        return []
    path_part = handler_ref.split("#", 1)[0]
    for base in (REPO_ROOT, PKG_ROOT):
        candidate = base / path_part
        if candidate.is_file():
            break
    else:
        return []
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id.endswith(("config", "cfg")) and node.attr.startswith("bot_"):
            found.append(node.attr)
        elif (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr" and len(node.args) >= 2
              and isinstance(node.args[0], ast.Name) and node.args[0].id.endswith(("config", "cfg"))
              and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
              and node.args[1].value.startswith("bot_")):
            found.append(str(node.args[1].value))
    return sorted(set(found))


def _propose_tags(cid: str, reg: Any, routes: list[dict[str, Any]], handler_ref: str,
                  topics: list[str], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """机械提出候选标签：每枚自带出处；票根由票根阶段回填。"""
    cm = ctx["cm"]
    blob = " ".join([cid, handler_ref, getattr(reg, "title", "") or "",
                     " ".join(str(r["kind"]) for r in routes), " ".join(str(r["value"]) for r in routes),
                     " ".join(str(r["label"]) for r in routes),
                     " ".join(str(t) for d in ctx["routes"]["by_cid"].get(cid, []) for t in d["tags"]),
                     " ".join(str(b["fid"]) for b in ctx["boards"].get(cid, [])),
                     " ".join(topics)]).lower()
    rows: list[dict[str, Any]] = []

    def _add(tag: Any, basis: str) -> None:
        rows.append({"tag": tag.value, "basis": basis, "ticket": _NONE,
                     "ticket_status": "unverified", "verified_test": _NONE})

    if "tts" in blob or "语音" in blob or "朗读" in blob:
        _add(cm.CapabilityTag.TTS, "id/路由标签/标题/help 主题含 tts|语音|朗读")
    if "vision" in blob or "识图" in blob or "ocr" in blob or "看图" in blob:
        _add(cm.CapabilityTag.VISION, "id/路由标签/标题含 vision|识图|ocr|看图")
    if "video" in blob or "视频" in blob:
        _add(cm.CapabilityTag.NATIVE_VIDEO,
             "id/标签含 video|视频 ⇒ **只算候选**：native-* 必须另有真跑票根（门⑥），HTTP 200 不算")
    if "audio" in blob or "asr" in blob or "转写" in blob:
        _add(cm.CapabilityTag.NATIVE_AUDIO,
             "id/标签含 audio|asr|转写 ⇒ 同上：票根不齐不得申报")
    if "sticker" in blob or "animation" in blob or "表情包" in blob or "动图" in blob:
        _add(cm.CapabilityTag.NATIVE_ANIMATION,
             "id/标签含 sticker|animation|表情包 ⇒ 同上（本仓实证 gemini 亦不解 gif）")
    if any(k in blob for k in ("media", "parse", "content", "archive", "link", "file")):
        _add(cm.CapabilityTag.MEDIA_READ, "id/路径/标签含 media|parse|content|archive|file（读入媒体段）")
    if "creation" in blob and "image" in blob:
        _add(cm.CapabilityTag.IMAGE, "creation.image 族（**生成**图像＝AI 绘画；搬运既有图走 serves-image）")
    # `serves-image` 不走词面猜：问门㉖ 那把派生尺（结果契约真把图像装进 `images=` 才算候选）。
    serving_sites = (ctx.get("image_serving") or {}).get(cid)
    if serving_sites:
        note = "" if cid not in (ctx.get("image_serving_exempt") or frozenset()) else \
            "〔在册侧已点名豁免（SERVES_IMAGE_UNDECLARED_ROSTER）：候选照列，挂不挂由裁定说，不由本件替裁〕"
        _add(cm.CapabilityTag.SERVES_IMAGE,
             "门㉖ 派生尺现算命中：" + "、".join(serving_sites[:2]) + note)
    if not rows:
        rows.append({"tag": _NONE,
                     "basis": "无任何内容形态信号命中（判据词见函数内 blob 组成），故不提标签",
                     "ticket": _NONE, "ticket_status": "not-applicable", "verified_test": _NONE})
    allowed = {t.value for t in cm.CapabilityTag}
    for row in rows:
        if row["tag"] != _NONE and row["tag"] not in allowed:
            row["basis"] += "〔⚠ 不在 CapabilityTag 枚举内 ⇒ 须先裁枚举，本席不擅自扩〕"
    return rows


# ==========================================================================
# 票根：候选收集 + 实跑归账
# ==========================================================================
def collect_ticket_candidates(cids: list[str], census: dict[str, Any]) -> dict[str, Any]:
    """两类候选：①普查在 tests 面看到的真身直调；②cid 字面量出现在某 test 用例体内。
       ②按"有无调用性证据"分 strong / mention-only（mention-only 不算票根，只算线索）。"""
    known = set(cids)
    nodes: dict[str, dict[str, Any]] = {}
    per_cid: dict[str, dict[str, set[str]]] = {cid: {"strong": set(), "mention": set()} for cid in cids}

    for cid in cids:
        for site in (census["roster"].get(cid) or {}).get("test_sites") or []:
            enclosing = site.get("enclosing") or ""
            if not enclosing.startswith("test"):
                continue
            node = f"{site['file']}::{enclosing}"
            entry = nodes.setdefault(node, {"cids": set(), "kind": set()})
            entry["cids"].add(cid)
            entry["kind"].add("census-direct")
            per_cid[cid]["strong"].add(node)

    unreadable: list[str] = []
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = _rel(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, UnicodeDecodeError, SyntaxError):
            unreadable.append(rel)
            continue
        hits = {cid for cid in known if f'"{cid}"' in text or f"'{cid}'" in text}
        if not hits:
            continue
        for func in _iter_funcs(tree):
            if not func.name.startswith("test"):
                continue
            dump = ast.dump(func)
            for cid in sorted(hits):
                if f"'{cid}'" not in dump and f'"{cid}"' not in dump:
                    continue
                node = f"{rel}::{func.name}"
                strong = _has_invocation(func)
                entry = nodes.setdefault(node, {"cids": set(), "kind": set()})
                entry["cids"].add(cid)
                entry["kind"].add("strong" if strong else "mention")
                per_cid[cid]["strong" if strong else "mention"].add(node)
    return {"nodes": {k: {"cids": sorted(v["cids"]), "kind": sorted(v["kind"])} for k, v in sorted(nodes.items())},
            "per_cid": {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in per_cid.items()},
            "tests_unreadable": unreadable}


def _has_invocation(func: ast.AST) -> bool:
    """用例体内是否有"调用性"证据（直呼执行体 / invoke / 管线 / 投递 / 装配口）。"""
    for sub in ast.walk(func):
        if not isinstance(sub, ast.Call):
            continue
        if _callee(sub) in {"invoke", "handle_async", "handle", "submit_active_push", "deliver",
                            "submit", "synthesize", "transcribe", "describe_images", "run", "main",
                            "build_capability", "chat", "generate"}:
            return True
        if any(k.arg in {"capability_id", "capability"} for k in sub.keywords):
            return True
    return False


def _run_python(args: list[str], timeout: int = SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "BOT_AUTOSYNC": "0", "PYTHONIOENCODING": "utf-8"})
    if not env.get("PYTHONPYCACHEPREFIX"):
        # 调用方没给前缀时自己也留一个，绝不留空串（空串＝字节码可能落回源码树，撞铁律 6）
        env["PYTHONPYCACHEPREFIX"] = str(Path(tempfile.gettempdir()) / "s32-facets-pyc")
    return subprocess.run([sys.executable, *args], cwd=str(REPO_ROOT), capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, check=False, env=env)


def collect_real_test_index(files: list[str], workdir: Path) -> tuple[dict[tuple[str, str], list[str]], dict[str, Any]]:
    """`pytest --collect-only` 建"真节点 id 索引"：(件, 用例基名) → [完整节点 id]。

    为什么必须有这一步（本席实跑踩到的）：普查件的 `test_sites.enclosing` 给的是
    **AST 里的函数名**，而 pytest 节点 id 对类内方法要写成 `件::类::方法`、参数化还要带 `[参数]`。
    直接把 `件::方法` 丢给 pytest ⇒ 退出码 4（usage error）**整批不跑**，
    上一版就是这么跑出 480/672 个 `unknown(not-in-junit rc=4)` ——看着像"没票根"，
    其实是尺子自己把节点名拼错了。先 collect 再跑，才分得清"没测"与"我没问对"。
    """
    index: dict[tuple[str, str], list[str]] = {}
    meta: dict[str, Any] = {"files": len(files), "batches": 0, "rc": [], "collect_errors": [],
                            "nodes_indexed": 0, "index_files": len(files)}
    for start in range(0, len(files), 25):
        chunk = files[start:start + 25]
        meta["batches"] += 1
        proc = _run_python(["-m", "pytest", *chunk, "--collect-only", "-q", "--no-header",
                            "-p", "no:cacheprovider", f"--basetemp={workdir / f'ct-{start}'}"])
        meta["rc"].append(proc.returncode)
        lines = (proc.stdout or "").splitlines()
        got = 0
        for line in lines:
            text = line.strip()
            if "::" not in text or not text.startswith("tests/"):
                continue
            file_rel, _, rest = text.partition("::")
            base = rest.partition("[")[0]
            # 类内方法：base = "TestX::test_y" ⇒ 用例基名取末段
            case_name = base.rpartition("::")[2] or base
            index.setdefault((file_rel, case_name), []).append(text)
            index.setdefault((Path(file_rel).name, case_name), []).append(text)
            got += 1
        meta["nodes_indexed"] += got
        if got == 0 and proc.returncode != 0:
            meta["collect_errors"].append({"files": chunk[:3], "rc": proc.returncode,
                                           "tail": "\n".join(lines[-6:])[-300:]})
    return index, meta


def resolve_nodes(candidates: list[str], index: dict[tuple[str, str], list[str]]) -> dict[str, Any]:
    """候选 `件::用例名` → 真节点族 id（跑族 id 即覆盖其全部参数化）；对不上的显式点名。"""
    families: dict[str, str] = {}      # 候选 → 族 id
    unresolved: dict[str, str] = {}    # 候选 → 为什么对不上
    for node in candidates:
        file_rel, _, case = node.partition("::")
        real = index.get((file_rel, case)) or index.get((Path(file_rel).name, case))
        if not real:
            unresolved[node] = "collect 索引里无此节点（普查给的 enclosing 可能是嵌套 helper、" \
                               "fixture 或被改名装饰的用例）⇒ 不当票根也不当'没测过'，单独点名"
            continue
        families[node] = real[0].partition("[")[0]
    return {"families": families, "unresolved": unresolved,
            "run_list": sorted(set(families.values()))}


def run_tickets(nodes: list[str], batch_size: int, workdir: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """实跑候选用例，逐用例归账。整批崩 ⇒ unknown（**绝不当"没票"**，更不当"有票"）。

    批次里若出现 usage error（rc=4：某条节点 id 不被认识），**二分下钻**到单条为止，
    让一条坏 id 只污染它自己——否则一批 60 枚全记 unknown，等于把尺子的错写成能力的账。
    """
    results: dict[str, str] = {}
    meta: dict[str, Any] = {"batch_size": batch_size, "requested": len(nodes), "rc": [],
                            "crashed_batches": [], "split_depth_max": 0}
    started = time.time()

    def _run_batch(batch: list[str], depth: int) -> None:
        meta["split_depth_max"] = max(meta["split_depth_max"], depth)
        stamp = f"{depth}-{abs(hash(tuple(batch))) % 10**8}"
        xml_path = workdir / f"junit-{stamp}.xml"
        try:
            proc = _run_python(["-m", "pytest", *batch, "-q", "--no-header", "-p", "no:cacheprovider",
                                f"--basetemp={workdir / f'bt-{stamp}'}", f"--junitxml={xml_path}"])
        except subprocess.TimeoutExpired:
            meta["crashed_batches"].append({"nodes": len(batch), "error": f"timeout depth={depth}"})
            for node in batch:
                results[node] = "unknown(timeout)"
            return
        meta["rc"].append(proc.returncode)
        if proc.returncode == 4 and len(batch) > 1:
            mid = len(batch) // 2
            _run_batch(batch[:mid], depth + 1)
            _run_batch(batch[mid:], depth + 1)
            return
        if not xml_path.is_file():
            meta["crashed_batches"].append({"nodes": len(batch), "error": f"no-junit rc={proc.returncode}",
                                            "tail": ((proc.stdout or "") + (proc.stderr or ""))[-300:]})
            for node in batch:
                results[node] = f"unknown(no-junit rc={proc.returncode})"
            return
        seen = _parse_junit(xml_path)
        for node in batch:
            file_rel, _, case = node.partition("::")
            case_name = case.rpartition("::")[2] or case
            status = seen.get((_norm(file_rel), case_name))
            results[node] = status or f"unknown(not-in-junit rc={proc.returncode})"

    for start in range(0, len(nodes), batch_size):
        _run_batch(nodes[start:start + batch_size], 0)
    meta["batches"] = len(meta["rc"])
    meta["elapsed_s"] = round(time.time() - started, 1)
    meta["statuses"] = dict(Counter(results.values()))
    return results, meta


def _norm(file_rel: str) -> str:
    return Path(file_rel).as_posix()


def _parse_junit(xml_path: Path) -> dict[tuple[str, str], str]:
    """junit ⇒ (tests 相对路径, 用例名去参) → 状态。

    输入是本件**自己刚生成**的 pytest junit 文件（非外部不可信 XML）；
    本件不解析外部 XML，且 ElementTree 默认不解外部实体 ⇒ 无网络/文件外联面。
    """
    out: dict[tuple[str, str], str] = {}
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError):
        return out
    for case in root.iter("testcase"):
        parts = (case.get("classname") or "").split(".")
        if len(parts) < 2 or parts[0] != "tests":
            continue
        file_rel = f"tests/{parts[1]}.py"
        name = (case.get("name") or "").partition("[")[0]
        status = "passed"
        for child in case:
            if child.tag == "failure":
                status = "failed"
            elif child.tag == "error":
                status = "error"
            elif child.tag == "skipped":
                status = "skipped"
        key = (file_rel, name)
        if out.get(key) == "passed":
            continue  # 同用例多参：任一次绿即算绿，但红也不覆盖既有绿（保守取"跑过"）
        out[key] = status
    return out


def _node_matches_tag(node: str, tag: str) -> bool:
    """这条用例自己是否指向该标签的形态（件名 + 用例名双查，中英词面都认）。"""
    keywords = {
        "tts": ("tts", "voice", "语音", "朗读", "播报"),
        "vision": ("vision", "image", "ocr", "图", "识图", "看"),
        "media-read": ("media", "file", "attach", "parse", "link", "archive", "媒体", "附件", "链接", "文件"),
        "image": ("draw", "paint", "image_generate", "绘画", "生图"),
        "native-audio": ("native_audio", "input_audio", "audio"),
        "native-video": ("native_video", "video_url", "video", "视频"),
        "native-animation": ("animation", "sticker", "gif", "动图", "表情"),
        "native-vision": ("native_vision", "native-image"),
    }
    probe = node.lower()
    return any(k in probe for k in keywords.get(tag, ()))


def attach_tickets(candidates: dict[str, dict[str, Any]], per_cid: dict[str, dict[str, list[str]]],
                   results: dict[str, str], mode: str, node_kinds: dict[str, list[str]],
                   unresolved: dict[str, str] | None = None) -> None:
    unresolved = unresolved or {}
    for cid, buckets in per_cid.items():
        row = candidates[cid]
        strong = buckets["strong"]
        mention = buckets["mention"]
        passed = [n for n in sorted(set(strong) | set(mention)) if results.get(n) == "passed"]
        unknown = [n for n in sorted(set(strong) | set(mention))
                   if str(results.get(n, "")).startswith(("unknown", "unresolved"))]
        if mode == "off":
            row["tickets"] = {"mode": "off", "verified_passed": _NONE, "verified_passed_count": 0,
                              "candidates_strong": strong[:12], "candidates_mention_only": mention[:8],
                              "why": "票根扫描被 `--tickets=off` 跳过 ⇒ 本次输出**不得**用于入册"}
        else:
            row["tickets"] = {
                "mode": mode, "verified_passed": passed or _NONE, "verified_passed_count": len(passed),
                "executed_candidates_strong": [f"{n}={results.get(n, 'not-run')}" for n in strong][:12],
                "mention_only_not_a_ticket": [f"{n}={results.get(n, 'not-run')}" for n in mention][:8],
                "unknown_or_unresolved_cells": unknown[:8],
                "why": _NONE if passed else (
                    "候选用例无一跑绿：要么真没人测过这条能力，要么用例只提 id 不执行"
                    "（后者按本仓纪律属「存在性糊过活性判据」，同样不算票根）" if mode == "run"
                    else "只收候选未执行（`--tickets=collect`）⇒ 票根一律 unverified，不得据此入册"),
            }
        best = passed[0] if passed else _NONE
        # ⚠ 一条能力级绿用例**不等于**某一枚内容形态标签有票根：本席第一版直接把"最好的绿用例"
        # 发给该能力提出的**每一枚**标签，那是把"weather 被测过"糊弄成"weather 读过媒体"。
        # 现行判据分两档：
        #   tag-level  = 跑绿的**那条用例自己**（件名或用例名）指向这一内容形态；
        #   native-*   = 一律 `needs-channel-evidence`：门⑥要的是"渠道 tag × 真实例"的票根，
        #                能力级/形态级绿证都不够（本仓实证：HTTP 200 却自陈没收到视频）。
        for tag in row["tags"]:
            if tag["tag"] == _NONE:
                continue
            evidence = [n for n in passed if _node_matches_tag(n, tag["tag"])]
            if str(tag["tag"]).startswith("native-"):
                tag.update({"ticket": "none（需渠道侧实测票根：件::用例 + 渠道 id + 真实例）",
                            "ticket_status": "needs-channel-evidence",
                            "capability_level_green_tests": len(passed)})
            elif evidence:
                tag.update({"ticket": evidence[0], "ticket_status": "passed",
                            "verified_test": evidence[0], "ticket_kind": node_kinds.get(evidence[0], []),
                            "ticket_tier": "tag-level",
                            "ticket_tier_note": "跑绿的这条用例自己指向该形态"})
            elif mode == "run" and passed:
                tag.update({"ticket": _NONE, "ticket_status": "capability-level-only",
                            "capability_level_green_tests": len(passed),
                            "why": "该能力有跑绿用例，但没有一条用例名/件名指向这一形态"
                                   "⇒ 标签级票根缺位，不许据此申报（要申报先补一条真测这形态的用例）"})
            else:
                tag.update({"ticket": f"none（{'候选未执行' if mode == 'collect' else '无实跑绿候选'}）",
                            "ticket_status": "unverified"})
        row["ticket_tool_health"] = {
            "capability_level_best_green_test": best,
            "unresolved_candidates_total": len(unresolved),
            "note": "unresolved=尺子拼不出合法节点 id 的候选（嵌套 helper/改名用例），"
                    "**不等于**该能力没被测过；桶判据只看实跑绿"}


# ==========================================================================
# 分桶
# ==========================================================================
def assign_bucket(row: dict[str, Any]) -> tuple[str, str]:
    """主桶（互斥；优先级 B4>B3>B2>B1>B0）＋下一步动作。"""
    has_ticket = bool(row["tickets"]["verified_passed_count"])
    entry_any = any(cell["verdict"] == "candidate" for cell in row["entry_kinds"].values())
    if row["trigger_copies"]["needs_normalization"]:
        return "B4", BUCKET_ACTION["B4"]
    if not row["executable"]["resolves"]:
        return "B3", BUCKET_ACTION["B3"]
    if not has_ticket:
        return "B2", BUCKET_ACTION["B2"]
    if not entry_any:
        return "B0", BUCKET_ACTION["B0"]
    return "B1", BUCKET_ACTION["B1"]


# ==========================================================================
# 主流程
# ==========================================================================
def build_payload(tickets_mode: str, batch_size: int, keep_detail: bool) -> tuple[dict[str, Any], int]:
    exit_code = 0
    workdir = Path(tempfile.mkdtemp(prefix="s32-facets-"))
    roster = load_roster()
    cm = roster["cm"]
    ids = frozenset(roster["ids"])
    if len(ids) < REGISTERED_FLOOR:
        raise SourceError(f"在册 id 总数 {len(ids)} < 地板 {REGISTERED_FLOOR} ⇒ 名册被缩，本件拒绝出账")
    ctx: dict[str, Any] = {
        "cm": cm, "descriptor": roster["descriptor"],
        "gate": (gate := load_gate_module()), "census": load_census(), "triggers": load_trigger_tables(),
        "boards": load_boards(), "config_fields": load_config_fields(),
        "help_meta": load_help_meta(), "routes": load_route_decls(),
    }
    # `serves-image`（用户裁定 D3=B 扩出的一枚）的候选**不靠词面猜**：直接问门㉖ 那把派生尺。
    # 复用不复制＝铁律 6：本件是**消费方**，判据真身只有 `test_capability_manifest_gate.py` 那一把。
    # 尺自己回 (hits, blind, parsed, total)，本件只取 hits——"失明/缩面"归门执法，不在这里再数一遍。
    ctx["image_serving"] = gate.derive_image_serving_sites()[0]
    # 在册侧已点名豁免的（真身带图但按裁定不挂标签），候选照列、另标一档，不静默抹掉。
    ctx["image_serving_exempt"] = cm.SERVES_IMAGE_UNDECLARED_ROSTER
    ctx["word_index"] = ctx["triggers"]["word_owners"]
    known = ids  # 在册 id 全集（字面量匹配的唯一合法词表：不在册的串一律不当 id）
    ctx["root_index"] = index_root_init(known)
    ctx["cp_index"] = index_dir_for_cids(CONTROL_PLANE_DIR, known, "control_plane")
    ack: dict[str, list[dict[str, Any]]] = {}
    for face in VOICE_FACES:  # 只扫这两支件本身（扫父目录再把别的件滤掉＝键会残留空表=假命中）
        for cid, sites in index_dir_for_cids(face, known, face.name).items():
            if sites:
                ack.setdefault(cid, []).extend(sites)
    ctx["ack_index"] = ack

    cids = sorted(ids)
    candidates = {cid: build_candidate(cid, ctx) for cid in cids}

    collected = collect_ticket_candidates(cids, ctx["census"])
    nodes = list(collected["nodes"])
    node_kinds = {n: v["kind"] for n, v in collected["nodes"].items()}
    results: dict[str, str] = {}
    resolved: dict[str, Any] = {"families": {}, "unresolved": {}, "run_list": []}
    cmeta: dict[str, Any] = {"mode": tickets_mode, "candidates": len(nodes)}
    if tickets_mode == "run":
        # 先 collect 建真节点索引再跑：普查给的 `件::函数名` 对类内方法/参数化不是合法节点 id，
        # 直接送 pytest 会 rc=4 整批不跑（上一版 480/672 unknown 就是这么来的）。
        files = sorted({n.partition("::")[0] for n in nodes})
        index, cmeta_collect = collect_real_test_index(files, workdir)
        cmeta_collect["index_files"] = len(files)
        resolved = resolve_nodes(nodes, index)
        family_results, tmeta = run_tickets(resolved["run_list"], batch_size, workdir)
        for node, family in resolved["families"].items():
            results[node] = family_results.get(family, "unknown(family-not-in-junit)")
        for node, reason in resolved["unresolved"].items():
            results[node] = f"unresolved({reason.split('（')[0]})"
        cmeta = {**tmeta, **cmeta_collect}
    cmeta.update({"candidates": len(nodes), "resolved": len(resolved["families"]),
                  "unresolved": len(resolved["unresolved"]),
                  "run_list": len(resolved["run_list"]),
                  "tests_unreadable": collected["tests_unreadable"]})
    tmeta = cmeta  # 单一出口：告警与 meta 都读这份合并后的账
    attach_tickets(candidates, collected["per_cid"], results, tickets_mode, node_kinds,
                   unresolved=resolved["unresolved"])

    for cid, row in candidates.items():
        bucket, action = assign_bucket(row)
        row["bucket"], row["bucket_label"], row["next_action"] = bucket, BUCKET_LABEL[bucket], action

    buckets = Counter(row["bucket"] for row in candidates.values())
    members: dict[str, list[str]] = {}
    for cid, row in candidates.items():
        members.setdefault(row["bucket"], []).append(cid)

    declared = cm.declared_ids()
    uncovered = len(ids - declared)
    visible = sum(1 for row in candidates.values() if row["census_visible"])
    invisible_ids = sorted(cid for cid, row in candidates.items() if not row["census_visible"])
    alerts: list[str] = []
    if uncovered != cm.UNCOVERED_CEILING:
        alerts.append(f"现算未申报 {uncovered} ≠ 册内 `UNCOVERED_CEILING={cm.UNCOVERED_CEILING}`："
                      + ("现算更小 ⇒ 上限可下调，但须逐枚点名是谁降的账。" if uncovered < cm.UNCOVERED_CEILING
                         else "现算更大 ⇒ 有新能力没入册，门⑦此刻应已红。"))
    blind = sorted(declared - set(ctx["census"]["roster"]))
    if blind:
        alerts.append(f"已申报却普查不可见（门 leg3b 的「量具失明」）：{blind}")
    if cmeta.get("crashed_batches"):
        alerts.append(f"票根实跑崩掉 {len(cmeta['crashed_batches'])} 批 ⇒ 该批格子记 unknown，"
                      "既不判「无票」也不判「有票」：" + json.dumps(cmeta["crashed_batches"], ensure_ascii=False)[:400])
        exit_code = 3

    gate = ctx["gate"]
    payload = {
        "meta": {
            "tool": "scripts/facets_candidate_dump.py", "version": VERSION,
            "seat": "S32 中央调度收编波·FACETS 扩册候选表",
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "registered_total": len(ids), "declared_total": len(declared), "uncovered": uncovered,
            "uncovered_ceiling": cm.UNCOVERED_CEILING,
            "census_visible": visible, "census_invisible": len(invisible_ids),
            "census_invisible_ids": invisible_ids,
            "tickets_mode": tickets_mode, "ticket_run_meta": cmeta,
            "trigger_conflicts_total": ctx["triggers"]["conflicts_total"],
            "trigger_ascii_boundary_violations": ctx["triggers"]["ascii_boundary_violations"],
            "root_init_sites": {"scheduler_cids": len(ctx["root_index"]["scheduler"]),
                                "push_cids": len(ctx["root_index"]["push"]),
                                "passive_cids": len(ctx["root_index"]["passive"]),
                                "matcher_count": ctx["root_index"]["matcher_count"]},
            "gate_baselines": {"EXECUTION_SURFACE_BASELINE": gate.EXECUTION_SURFACE_BASELINE,
                               "DECLARED_UNWIRED_BASELINE": gate.DECLARED_UNWIRED_BASELINE,
                               "PLACEHOLDER_BASELINE": gate.PLACEHOLDER_BASELINE,
                               "gate_REGISTERED_FLOOR": gate.REGISTERED_FLOOR,
                               "seat_REGISTERED_FLOOR": REGISTERED_FLOOR},
            "sources_of_truth": [
                "runtime/capability_protocols.py::CAPABILITY_DESCRIPTOR（名册唯一真身，本件 import 之）",
                "scripts/central_seam_census.py --json（入口/站点唯一尺）",
                "scripts/extract_trigger_words.py::build_inventory（触发词唯一提取器）",
                "tests/test_capability_manifest_gate.py::_resolve_symbol（执行体/指针唯一判据）",
                "domains/core/board_taxonomy.py::BOARD_TAXONOMY（板块唯一声明源）",
                "config.py（字段名真身，本件只列名）",
            ],
            "not_a_ticket": ["HTTP 200", "文档/注释散文", "_HELP_ENTRY_META.tests 自述",
                             "mention-only 用例（只提 id 不执行）"],
            "alerts": alerts,
        },
        "counts": {
            "buckets": dict(buckets), "bucket_members": {k: sorted(v) for k, v in members.items()},
            "actions": BUCKET_ACTION,
            "no_entry_kind_candidate": sorted(
                cid for cid, row in candidates.items()
                if not any(c["verdict"] == "candidate" for c in row["entry_kinds"].values())),
            "with_ticket": sorted(cid for cid, row in candidates.items()
                                  if row["tickets"]["verified_passed_count"]),
        },
        "candidates": candidates,
    }
    if not keep_detail:  # --buckets-only：不留逐格明细，只留汇总（同一份账，不是第二次计算）
        for row in candidates.values():
            detectors = row["triggers"]["detectors"]
            row["triggers"]["detectors"] = (
                f"<{len(detectors)} 条检测器明细，请去 --json 全量看>" if isinstance(detectors, list) else detectors)
    return payload, exit_code


# ==========================================================================
# 渲染
# ==========================================================================
def render_markdown(payload: dict[str, Any]) -> str:
    meta, counts, cands = payload["meta"], payload["counts"], payload["candidates"]
    out: list[str] = ["# FACETS 扩册候选表（机械化产线输出）", ""]
    out.append(f"- 生成（UTC）：{meta['generated_at_utc']}　量具：`{meta['tool']}` v{meta['version']}　席位：{meta['seat']}")
    out.append(f"- 名册真身：`CAPABILITY_DESCRIPTOR` 在册 **{meta['registered_total']}** 枚　本册已申报 "
               f"**{meta['declared_total']}** 枚　未申报 **{meta['uncovered']}** 枚"
               f"（册内上限 `UNCOVERED_CEILING={meta['uncovered_ceiling']}`）")
    out.append(f"- 票根模式：**{meta['tickets_mode']}**" + (
        "——只有本模式下的 `verified_passed` 才算票根" if meta["tickets_mode"] == "run"
        else "——本次输出**不得**用于入册"))
    out.append(f"- 不算票根的东西（写死）：{'、'.join(meta['not_a_ticket'])}")
    out.append(f"- 普查可见 {meta['census_visible']} / 不可见 {meta['census_invisible']}"
               "（不可见者的格子一律 `none`+原因，绝不「没扫到=没问题」）")
    out.append("")
    out.append("## 分桶汇总")
    out.append("")
    out.append("| 桶 | 含义 | 枚数 | 下一步动作 |")
    out.append("|---|---|---|---|")
    for bucket in ("B1", "B2", "B3", "B4", "B0"):
        members = counts["bucket_members"].get(bucket, [])
        out.append(f"| {bucket} | {BUCKET_LABEL[bucket]} | **{len(members)}** | {BUCKET_ACTION[bucket]} |")
    out.append(f"| 合计 | — | **{sum(len(v) for v in counts['bucket_members'].values())}** | 复跑命令见文末 |")
    out.append("")
    out.append("### 桶成员名册（逐枚点名）")
    for bucket in ("B1", "B2", "B3", "B4", "B0"):
        members = counts["bucket_members"].get(bucket, [])
        out.append(f"- **{bucket} {BUCKET_LABEL[bucket]}**（{len(members)}）："
                   + ("、".join(f"`{c}`" for c in members) if members else "（空）"))
    out.append("")
    out.append(f"- 提不出任何入口形态的枚（{len(counts['no_entry_kind_candidate'])}）："
               + ("、".join(f"`{c}`" for c in counts["no_entry_kind_candidate"][:40]) or "（空）"))
    out.append(f"- 有实跑绿票根的枚（{len(counts['with_ticket'])}）："
               + ("、".join(f"`{c}`" for c in counts["with_ticket"][:40]) or "（空）"))
    out.append("")
    if meta.get("alerts"):
        out.append("## ⚠ 现算与在册口径的差（如实报备，不代修）")
        out += [f"- {line}" for line in meta["alerts"]]
        out.append("")
    out.append("## 候选表")
    out.append("")
    out.append("| capability_id | 桶 | 入口形态候选 | 执行体 | 直呼点 | 触发词真身（指针，可解析？） | 键 | 标签 ← 票根 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for cid, row in cands.items():
        kinds = sorted(k for k, c in row["entry_kinds"].items() if c["verdict"] == "candidate")
        tags_cell = "；".join(f"{t['tag']}←{t['ticket']}" + ("✔" if t["ticket_status"] == "passed" else "")
                               for t in row["tags"])
        exec_cell = ("✔ " if row["executable"]["resolves"] else "✘ ") + row["executable"]["handler_ref"]
        pointer = row["triggers"]["trigger_source_pointer"]
        pointer_cell = pointer + ("" if not row["triggers"]["pointer_resolves_by_gate_leg4"] else " ✔") \
            if pointer != _NONE else _NONE
        out.append(f"| `{cid}` | {row['bucket']} | {', '.join(kinds) or _NONE} | {exec_cell} | "
                   f"{row['direct_callsites']['verdict']}({row['direct_callsites']['count']}) | "
                   f"{pointer_cell} | {row['config_keys']['count']} | {tags_cell} |")
    out.append("")
    out.append("## B4 触发词副本账（逐枚：为什么不能直接入册）")
    lines = 0
    for cid, row in cands.items():
        copies = row["trigger_copies"]
        if copies["needs_normalization"]:
            out.append(f"- `{cid}`：跨能力冲突 `{copies['cross_capability_conflicts']}`；"
                       f"同检测器多模块 `{copies['same_detector_in_multiple_modules']}`")
            lines += 1
    if not lines:
        out.append(f"- （零枚：提取器现算跨能力冲突 {meta['trigger_conflicts_total']} 条、"
                   "同检测器多模块两路对本席名册的命中为空）")
    out.append("")
    out.append("## B3 无执行体账（＝门⑤「在册必有执行面」欠账，逐枚）")
    rows = [(cid, row) for cid, row in cands.items() if not row["executable"]["resolves"]]
    for cid, row in rows:
        out.append(f"- `{cid}` handler_ref=`{row['executable']['handler_ref']}` —— {row['executable']['why_not_resolved']}")
    out.append(f"- 合计 **{len(rows)}** 枚；门⑤基线 `EXECUTION_SURFACE_BASELINE="
               f"{meta['gate_baselines']['EXECUTION_SURFACE_BASELINE']}`（只降不升）")
    out.append("")
    out.append("## 普查看不见的在册枚（本席量具的诚实边界）")
    if meta["census_invisible_ids"]:
        for cid in meta["census_invisible_ids"]:
            out.append(f"- `{cid}` authored_by={cands[cid]['authored_by']} handler_ref="
                       f"`{cands[cid]['executable']['handler_ref']}` ⇒ 普查件只认 `capability_id=` 字面量")
    else:
        out.append("- （零枚）")
    out.append("")
    out.append("## 入口形态判定依据样例（每格都带 文件:行号，此处给前 3 枚全展开）")
    for cid in list(cands)[:3]:
        out.append(f"- `{cid}`")
        for kind, cell in cands[cid]["entry_kinds"].items():
            if cell["verdict"] == "candidate":
                out.append(f"  - **{kind}** ← " + "；".join(cell["basis"]))
            else:
                out.append(f"  - {kind}: none —— {cell.get('why_no', '（无依据）')}")
    out.append("")
    out.append("## 复跑命令")
    out.append("")
    out.append("```bash")
    out.append("# 环境咒语（缺一即可能污染源码树 / 读到脏缓存 / GBK 崩）")
    out.append("export PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8")
    out.append('export PYTHONPYCACHEPREFIX="$TEMP/s32-pyc"')
    out.append('PY=../ChatBot_Runtime/venv/Scripts/python.exe')
    out.append('$PY scripts/facets_candidate_dump.py --markdown      # 人读全表（缺省票根=实跑）')
    out.append('$PY scripts/facets_candidate_dump.py --json          # 机读同一份账')
    out.append('$PY scripts/facets_candidate_dump.py --buckets-only   # 只出分桶')
    out.append('$PY scripts/facets_candidate_dump.py --cid bot.weather # 单枚全明细（见下方单枚段）')
    out.append('$PY scripts/facets_candidate_dump.py --tickets=collect # 只收候选不跑（快，不得入册）')
    out.append("$PY scripts/facets_candidate_dump.py --tickets=off     # 跳票根（不得入册）")
    out.append("```")
    return "\n".join(out) + "\n"


def render_single(payload: dict[str, Any], cid: str) -> str:
    row = payload["candidates"].get(cid)
    if row is None:
        return f"（`--cid {cid}` 不在册：本件拒绝为不在册 id 出候选）\n"
    lines = [f"# 单枚候选明细：`{cid}`", "", "```json",
             json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True), "```"]
    lines += ["", "## 可照抄进 FACETS 的 `_f(...)` 草稿（票根不足处已留空并说明）", "```python"]
    kinds = sorted(k for k, c in row["entry_kinds"].items() if c["verdict"] == "candidate")
    kind_args = ", ".join(f"_EK.{_entry_name_for(k)}" for k in kinds)
    tags = [t["tag"] for t in row["tags"] if t["ticket_status"] == "passed" and t["tag"] != _NONE]
    tag_args = ", ".join(f"_TG.{_tag_name_for(t)}" for t in tags)
    pointer = row["triggers"]["trigger_source_pointer"]
    draft = (f"_f(\"{cid}\", {kind_args}"
             + (f", tags=({tag_args},)" if tag_args else "")
             + (f", trigger_source=\"{pointer}\"" if pointer != _NONE and row["triggers"]["pointer_resolves_by_gate_leg4"] else "")
             + "),")
    lines.append(draft)
    lines.append("```")
    if pointer != _NONE and not row["triggers"]["pointer_resolves_by_gate_leg4"]:
        lines.append(f"⚠ trigger_source `{pointer}` 现判不可解析 ⇒ 门④会红，先修真身再抄。")
    if not tags:
        lines.append("⚠ 无可入册标签：native-*/tts 等全部缺**实跑绿票根**（门⑥）。")
    return "\n".join(lines) + "\n"


_NAME_CACHE: dict[str, Any] = {}


def _entry_enum(which: str) -> Any:
    from plugins.bot_unified_runtime.domains.core import capability_manifest as cm
    return cm.EntryKind if which == "entry" else cm.CapabilityTag


def _entry_name_for(value: str) -> str:
    return next((m.name for m in _entry_enum("entry") if m.value == value), value.upper().replace("-", "_"))


def _tag_name_for(value: str) -> str:
    return next((m.name for m in _entry_enum("tags") if m.value == value), value.upper().replace("-", "_"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FACETS 扩册候选表（只读，结果只打 stdout）")
    parser.add_argument("--json", action="store_true", help="机读全量")
    parser.add_argument("--markdown", action="store_true", help="人读全表（缺省）")
    parser.add_argument("--tickets", choices=("run", "collect", "off"), default="run",
                        help="run=实跑绿才算票根（缺省）/ collect=只收候选不跑 / off=跳过")
    parser.add_argument("--batch-size", type=int, default=40, help="票根实跑每批节点数")
    parser.add_argument("--cid", default=None, help="只出某一枚的完整明细 + 可抄草稿")
    parser.add_argument("--buckets-only", action="store_true", help="只出分桶汇总")
    args = parser.parse_args(argv)

    try:
        payload, exit_code = build_payload(args.tickets, args.batch_size, not args.buckets_only)
    except SourceError as exc:
        print(json.dumps({"error": "缺件/量具失明", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.cid:
        if args.json:
            print(json.dumps(payload["candidates"].get(args.cid, {"error": "不在册"}),
                             ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_single(payload, args.cid))
        return exit_code
    if args.buckets_only:
        slim = {"meta": {k: v for k, v in payload["meta"].items() if k != "alerts"},
                "alerts": payload["meta"]["alerts"], "counts": {"buckets": payload["counts"]["buckets"]}}
        print(json.dumps(slim, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    print(render_markdown(payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
