"""T-Spec 基础设施（规格无关）：触发指令词表机械化提取器。

从当前源码提取事实表，供 tests/test_trigger_spec.py 体检断言与后续
T-Spec（七格触发矩阵：英文/简体/繁體/全拼/缩写/昵称/自然语言）规范化波
使用。本模块只读源码与运行时对象，不写任何文件。

提取范围（全部机械化，零手抄词表）：
1. runtime/base_router.py 的 RouteRule 注册表（AST 静态提取）：
   kind / capability_id / priority / matcher 名 → matcher 体内调用的
   检测函数（``is_*`` 行为检测器 + 结构检测器）。
2. 各 ``is_*`` 检测函数的字面触发素材（AST 摘函数内字符串字面量 + 函数
   引用的模块级常量：str / re.Pattern / 字符串集合，正则再按字面连续段
   切词），随后做行为验证：裸词或「词 + 后缀」探针能命中自身能力者记
   ``verified_triggers``，其余记 ``passive_words``（守卫词/语境词天然被
   行为验证过滤，不混入触发表）。
3. capabilities/echo.py 的 ``_HELP_ENTRIES`` aliases、``_HELP_ENTRY_META``
   的 triggers_nl / triggers_nickname / capability，以及
   runtime/aliases.py 的 ``DEFAULT_VERB_MAP``。

本模块同时机械化产出两类体检结果（现状红点原样上报，这是体检不是
改造，不改任何源码）：
- 跨能力触发冲突：verified 探针文本跑全部 is_* 检测器，命中多于一个
  capability_id 即冲突；
- ASCII 词边界违规：_alias_hit 模式（ASCII 词边界、中文子串）——verified
  ASCII 词以 ``qq<word>`` / ``<word>qq`` 胶合探针命中自身能力即违规。

用法：
    python scripts/extract_trigger_words.py           # 摘要（stdout JSON）
    python scripts/extract_trigger_words.py --full    # 全量清单（stdout JSON）
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import sys
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BASE_ROUTER_MODULE = "plugins.bot_unified_runtime.runtime.base_router"
BASE_ROUTER_REL = Path("plugins/bot_unified_runtime/runtime/base_router.py")

# matcher 体内不算检测器的调用名（内建 / 路由构造辅助）。
_NON_DETECTOR_CALLS = frozenset(
    {
        "getattr", "bool", "str", "sorted", "set", "len", "list", "tuple",
        "frozenset", "dict", "RouteDecision", "_resolve_alias",
    }
)
# 结构检测器：非 is_* 命名但承担路由判定的函数。
_STRUCTURAL_DETECTORS = frozenset(
    {"_admin_command_match", "looks_like_chat_text", "detect_natural_command", "extract_http_urls"}
)
# 无 is_* 行为检测器、靠别名解析器或结构判定的路由种类。
_STRUCTURAL_KINDS = frozenset({"ALIAS", "ADMIN", "NATURAL_COMMAND", "CONTENT", "CHAT"})

# 正则模式文本里按字面连续段切词（CJK/ASCII 连续段，空格允许在段中，
# 保留 "epic free" / "AI新闻" 这类复合词）。
_WORD_RUN_RE = re.compile(
    r"[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff ]*[0-9A-Za-z\u4e00-\u9fff]"
    r"|[0-9A-Za-z\u4e00-\u9fff]"
)
# 纯 ASCII 词（词边界纪律只约束这类；长度 >=2 由调用方把关）。
_ASCII_WORD_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z ]*[0-9A-Za-z]")
# 行为验证探针后缀：裸词优先，其次带中性后缀（维基/点歌类要求带 query）。
_PROBE_SUFFIXES = ("", " 测试", "？")
_MAX_CONTAINER_ITEMS = 512
_MAX_RESOLVE_DEPTH = 3


# ---------------------------------------------------------------------------
# 1) RouteRule 注册表（AST 静态提取）
# ---------------------------------------------------------------------------


def extract_base_router_map() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """AST 提取 build_route_rules 的规则表与 matcher→检测函数映射。

    返回 (rules, imported)：rules 每项含
    kind/capability_id/priority/matcher/detectors；imported 把
    base_router 顶部 import 进来的名字映射回源模块路径。
    """
    source = (REPO_ROOT / BASE_ROUTER_REL).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
    builder = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "build_route_rules"
    )
    matcher_detectors: dict[str, list[str]] = {}
    for node in builder.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        calls: set[str] = set()
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)):
                continue
            name = sub.func.id
            if name in _NON_DETECTOR_CALLS:
                continue
            if name in imported or name in _STRUCTURAL_DETECTORS:
                calls.add(name)
        matcher_detectors[node.name] = sorted(calls)
    rules: list[dict[str, Any]] = []
    for node in ast.walk(builder):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RouteRule"):
            continue
        args = node.args
        kind = args[0].attr if isinstance(args[0], ast.Attribute) else ast.unparse(args[0])
        matcher_name = ""
        if len(args) >= 7 and isinstance(args[6], ast.Name):
            matcher_name = args[6].id
        for keyword in node.keywords:
            if keyword.arg == "matcher" and isinstance(keyword.value, ast.Name):
                matcher_name = keyword.value.id
        rules.append(
            {
                "kind": kind,
                "capability_id": args[1].value,
                "priority": args[2].value,
                "matcher": matcher_name,
                "detectors": matcher_detectors.get(matcher_name, []),
            }
        )
    rules.sort(key=lambda item: (item["priority"], item["kind"]))
    return rules, imported


# ---------------------------------------------------------------------------
# 2) 检测函数字面素材提取 + 行为验证
# ---------------------------------------------------------------------------


def _harvest_words(text: str) -> list[str]:
    """从任意字符串（含正则模式文本）切出字面连续段。"""
    return _WORD_RUN_RE.findall(text or "")


def _collect_from_value(value: Any, depth: int) -> tuple[set[str], set[str]]:
    """从常量值收集 (words, raw_literals)；容器递归，深度受限。"""
    words: set[str] = set()
    raws: set[str] = set()
    if depth > _MAX_RESOLVE_DEPTH:
        return words, raws
    if isinstance(value, re.Pattern):
        raws.add(value.pattern)
        words.update(_harvest_words(value.pattern))
    elif isinstance(value, str):
        raws.add(value)
        words.update(_harvest_words(value))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value)[:_MAX_CONTAINER_ITEMS]:
            child_words, child_raws = _collect_from_value(item, depth + 1)
            words |= child_words
            raws |= child_raws
    elif isinstance(value, dict):
        for key, item in list(value.items())[:_MAX_CONTAINER_ITEMS]:
            child_words, child_raws = _collect_from_value(key, depth + 1)
            words |= child_words
            raws |= child_raws
            child_words, child_raws = _collect_from_value(item, depth + 1)
            words |= child_words
            raws |= child_raws
    return words, raws


def harvest_function_material(func: Any) -> dict[str, list[str]]:
    """摘取检测函数体内的字面素材：函数内字符串字面量 + 引用的模块级常量。"""
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    fn_def = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    words: set[str] = set()
    raws: set[str] = set()
    # 跳过 docstring：注释性文本里的词不是触发词（防「显式股票词」这类
    # 文档短语混入触发表）。
    skip_nodes: set[int] = set()
    if (
        fn_def.body
        and isinstance(fn_def.body[0], ast.Expr)
        and isinstance(fn_def.body[0].value, ast.Constant)
        and isinstance(fn_def.body[0].value.value, str)
    ):
        skip_nodes.add(id(fn_def.body[0].value))
    for node in ast.walk(fn_def):
        if id(node) in skip_nodes:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            raws.add(node.value)
            words.update(_harvest_words(node.value))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            child_words, child_raws = _collect_from_value(func.__globals__.get(node.id), 1)
            words |= child_words
            raws |= child_raws
    return {"words": sorted(words), "raw_literals": sorted(raws)}


def _probe_hits(func: Any, probe: str) -> bool:
    try:
        return bool(func(probe))
    except Exception:  # noqa: BLE001 - 检测器任何异常按未命中记账，不阻塞体检。
        return False


def verify_word(func: Any, word: str) -> str | None:
    """返回能命中该检测函数的探针文本；都不命中则 None（passive）。"""
    for suffix in _PROBE_SUFFIXES:
        probe = word + suffix
        if _probe_hits(func, probe):
            return probe
    return None


def build_capability_inventory(
    rules: list[dict[str, Any]], imported: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """按 capability_id 聚合检测器，做字面提取 + 行为验证 + 两类体检。"""
    grouped: dict[str, dict[str, Any]] = {}
    for rule in rules:
        entry = grouped.setdefault(rule["capability_id"], {"detectors": {}, "kinds": []})
        entry["kinds"].append(rule["kind"])
        # 结构路由（ALIAS/ADMIN/NATURAL/CONTENT/CHAT）matcher 里的 is_* 调用
        # 是排除/守卫（如 chat_match 用 is_auto_send_command_text 让路），
        # 不算该能力的触发检测器。
        if rule["kind"] in _STRUCTURAL_KINDS:
            continue
        for name in rule["detectors"]:
            if not name.startswith("is_"):
                continue
            module_name = imported.get(name)
            if not module_name:
                continue
            entry["detectors"].setdefault(name, module_name)

    inventory: dict[str, dict[str, Any]] = {}
    for capability_id in sorted(grouped):
        entry = grouped[capability_id]
        detector_reports: list[dict[str, Any]] = []
        verified: dict[str, dict[str, str]] = {}
        passive: list[str] = []
        for func_name in sorted(entry["detectors"]):
            module_name = entry["detectors"][func_name]
            try:
                func = getattr(importlib.import_module(module_name), func_name)
                callable_ok = callable(func)
            except Exception as exc:  # noqa: BLE001 - 导入失败按体检红点记账。
                detector_reports.append(
                    {"name": func_name, "module": module_name, "callable": False, "error": repr(exc)}
                )
                continue
            report: dict[str, Any] = {
                "name": func_name,
                "module": module_name,
                "callable": callable_ok,
            }
            if callable_ok:
                material = harvest_function_material(func)
                report["words"] = material["words"]
                report["raw_literals"] = material["raw_literals"]
                for word in material["words"]:
                    if not word.strip() or word in verified:
                        continue
                    probe = verify_word(func, word)
                    if probe is None:
                        passive.append(word)
                    else:
                        verified[word] = {"probe": probe, "detector": func_name}
            detector_reports.append(report)
        inventory[capability_id] = {
            "kinds": sorted(entry["kinds"]),
            "detectors": detector_reports,
            "verified_triggers": dict(sorted(verified.items())),
            "passive_words": sorted(set(passive) - set(verified)),
        }
    return inventory


def run_cross_capability_conflicts(
    inventory: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """verified 探针文本跑全部 is_* 检测器；命中多个 capability 即冲突。"""
    all_detectors: dict[str, list[tuple[str, Any]]] = {}
    for capability_id, entry in inventory.items():
        for report in entry["detectors"]:
            if not report.get("callable") or not report["name"].startswith("is_"):
                continue
            func = getattr(
                importlib.import_module(report["module"]), report["name"]
            )
            all_detectors.setdefault(capability_id, []).append((report["name"], func))

    conflicts: list[dict[str, Any]] = []
    for owner_id in sorted(inventory):
        for word in sorted(inventory[owner_id]["verified_triggers"]):
            probe = inventory[owner_id]["verified_triggers"][word]["probe"]
            hits = sorted(
                capability_id
                for capability_id, detectors in all_detectors.items()
                if any(_probe_hits(func, probe) for _name, func in detectors)
            )
            if hits != [owner_id]:
                conflicts.append(
                    {"capability_id": owner_id, "word": word, "probe": probe, "hit_capabilities": hits}
                )
    return conflicts


def run_ascii_boundary_violations(
    inventory: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """ASCII 词边界体检（_alias_hit 模式）：胶合探针 qq<word>/<word>qq
    命中自身能力即违规（中文词走子串属约定内，不检）。"""
    violations: list[dict[str, Any]] = []
    for capability_id in sorted(inventory):
        for word in sorted(inventory[capability_id]["verified_triggers"]):
            token = word.strip()
            if len(token) < 2 or not _ASCII_WORD_RE.fullmatch(token):
                continue
            info = inventory[capability_id]["verified_triggers"][word]
            func = getattr(
                importlib.import_module(
                    next(
                        report["module"]
                        for report in inventory[capability_id]["detectors"]
                        if report["name"] == info["detector"]
                    )
                ),
                info["detector"],
            )
            for side, glued in (
                ("left", "qq" + token),
                ("right", token + "qq"),
            ):
                if _probe_hits(func, glued):
                    violations.append(
                        {
                            "capability_id": capability_id,
                            "word": token,
                            "side": side,
                            "glued_probe": glued,
                            "detector": info["detector"],
                        }
                    )
    return violations


# ---------------------------------------------------------------------------
# 3) help 侧表与动词映射
# ---------------------------------------------------------------------------


def extract_help_topics() -> dict[str, dict[str, Any]]:
    """capabilities/echo.py 的 _HELP_ENTRIES × _HELP_ENTRY_META 结构化提取。"""
    from plugins.bot_unified_runtime.capabilities import echo

    topics: dict[str, dict[str, Any]] = {}
    for entry in echo._HELP_ENTRIES:
        topic = str(entry["topic"])
        meta = echo._HELP_ENTRY_META.get(topic, {})
        topics[topic] = {
            "aliases": list(entry.get("aliases", ())),
            "triggers_nl": list(meta.get("triggers_nl", ())),
            "triggers_nickname": list(meta.get("triggers_nickname", ())),
            "capability": str(meta.get("capability", "")),
            "admin_only": bool(entry.get("admin_only", False)),
        }
    return dict(sorted(topics.items()))


def extract_default_verb_map() -> dict[str, list[str]]:
    """runtime/aliases.py DEFAULT_VERB_MAP 按能力分组。"""
    from plugins.bot_unified_runtime.runtime.aliases import DEFAULT_VERB_MAP

    grouped: dict[str, list[str]] = {}
    for verb, capability_id in DEFAULT_VERB_MAP.items():
        grouped.setdefault(capability_id, []).append(verb)
    return {key: sorted(values) for key, values in sorted(grouped.items())}


def topics_missing_trigger_records(topics: dict[str, dict[str, Any]]) -> list[str]:
    """help topic 既无 aliases 也无 triggers_nl/triggers_nickname 记为缺。"""
    return sorted(
        topic
        for topic, info in topics.items()
        if not info["aliases"] and not info["triggers_nl"] and not info["triggers_nickname"]
    )


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def build_inventory() -> dict[str, Any]:
    """一次性构建全部事实表（进程内缓存；纯读，不写文件）。"""
    rules, imported = extract_base_router_map()
    capabilities = build_capability_inventory(rules, imported)
    help_topics = extract_help_topics()
    return {
        "route_rules": rules,
        "capabilities": capabilities,
        "cross_capability_conflicts": run_cross_capability_conflicts(capabilities),
        "ascii_boundary_violations": run_ascii_boundary_violations(capabilities),
        "structural_rule_kinds": sorted(
            rule["kind"] for rule in rules if rule["kind"] in _STRUCTURAL_KINDS
        ),
        "help_topics": help_topics,
        "help_topics_missing_trigger_records": topics_missing_trigger_records(help_topics),
        "verb_map_groups": extract_default_verb_map(),
    }


def summarize(inventory: dict[str, Any]) -> dict[str, Any]:
    """CLI/报告用的摘要（计数 + 红点清单）。"""
    capabilities = inventory["capabilities"]
    verified_total = sum(len(item["verified_triggers"]) for item in capabilities.values())
    passive_total = sum(len(item["passive_words"]) for item in capabilities.values())
    detector_total = sum(
        1
        for item in capabilities.values()
        for report in item["detectors"]
        if report["name"].startswith("is_")
    )
    no_verified = sorted(
        capability_id
        for capability_id, item in capabilities.items()
        if not item["verified_triggers"]
    )
    return {
        "route_rule_count": len(inventory["route_rules"]),
        "capability_count": len(capabilities),
        "behavioral_detector_count": detector_total,
        "verified_trigger_total": verified_total,
        "passive_word_total": passive_total,
        "capabilities_without_verified_triggers": no_verified,
        "cross_capability_conflicts": inventory["cross_capability_conflicts"],
        "ascii_boundary_violations": inventory["ascii_boundary_violations"],
        "help_topic_count": len(inventory["help_topics"]),
        "help_topics_missing_trigger_records": inventory["help_topics_missing_trigger_records"],
        "verb_map_group_count": len(inventory["verb_map_groups"]),
        "verb_map_verb_total": sum(len(v) for v in inventory["verb_map_groups"].values()),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    inventory = build_inventory()
    payload = inventory if "--full" in argv else summarize(inventory)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):  # pragma: no cover - 老终端兜底。
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
