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

另含触发词双向机械门（P2-9，``gate_route_to_help`` /
``gate_help_to_route``）：路由侧（verified_triggers ∪ 动词表）与 help 侧
（aliases ∪ META 触发词，按 capability 字段聚合）各自机械提取后词级
diff，治「路由有、help 无」（求籤先例）与「help 有、路由坠兜底」两类
复发缺口；现状缺口由 tests/test_trigger_bidirectional_gate.py 台账制管理。

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
BASE_ROUTER_MODULE = "plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router"
BASE_ROUTER_REL = Path("plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py")

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
# L-C04 单行委托追踪深度（is_tts_command→extract_tts_text→
# effective_trigger_words→DEFAULT_TRIGGER_WORDS 需两跳，留一跳余量）。
_MAX_DELEGATION_DEPTH = 3


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
        head = args[0]
        kind = head.attr if isinstance(head, ast.Attribute) else ast.unparse(head)
        capability_id = args[1].value if isinstance(args[1], ast.Constant) else ""
        priority = args[2].value if isinstance(args[2], ast.Constant) else 0
        matcher_name = ""
        if len(args) >= 7 and isinstance(args[6], ast.Name):
            matcher_name = args[6].id
        for keyword in node.keywords:
            if keyword.arg == "matcher" and isinstance(keyword.value, ast.Name):
                matcher_name = keyword.value.id
        rules.append(
            {
                "kind": kind,
                "capability_id": capability_id,
                "priority": priority,
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


def harvest_function_material(
    func: Any,
    *,
    _trace: bool = False,
    _depth: int = 0,
    _seen: frozenset[int] = frozenset(),
) -> dict[str, list[str]]:
    """摘取检测函数体内的字面素材：函数内字符串字面量 + 引用的模块级常量。

    L-C04 单行委托陷阱：检测函数体可能是 ``bool(extract_xxx(...))`` 这类
    零字面量委托（bot.tts 的 ``is_tts_command`` 先例），真词表住被委托
    实现函数的 globals。缺省（``_trace=False``）行为与历史版本逐字节一致；
    ``_trace=True`` 时沿体内调用名向**同模块**可调用对象递归追踪（深度
    受限 + 防环，中间跳不设素材门），跨模块委托追不动（不在本机制覆盖
    面），须按 L-C04 修法手动登记 harvest 源。
    """
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
    delegated_calls: list[str] = []
    for node in ast.walk(fn_def):
        if id(node) in skip_nodes:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            raws.add(node.value)
            words.update(_harvest_words(node.value))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            delegated_calls.append(node.func.id)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            child_words, child_raws = _collect_from_value(func.__globals__.get(node.id), 1)
            words |= child_words
            raws |= child_raws
    if _trace and _depth < _MAX_DELEGATION_DEPTH:
        seen = _seen | {id(func)}
        for name in delegated_calls:
            target = func.__globals__.get(name)
            if target is None or id(target) in seen:
                continue
            if not (inspect.isfunction(target) or inspect.ismethod(target)):
                continue
            try:
                child = harvest_function_material(
                    target, _trace=True, _depth=_depth + 1, _seen=seen
                )
            except (OSError, TypeError, StopIteration, SyntaxError):
                continue  # 源码不可得/非常规函数体：按未追踪记账，体检不红。
            words.update(child["words"])
            raws.update(child["raw_literals"])
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
        # L-C04 补收（能力级门）：能力零 verified 且某检测器本体零素材时，
        # 才对其开委托追踪（``_trace=True``）。门设在能力级——本体暗体但
        # 能力已有其他检测器供词的（bot.moegirl 先例）保持逐字节不变；
        # 只有 bot.tts 这类「整能力皆暗」的盲区被点亮（空→非空单向）。
        if not verified:
            for report in detector_reports:
                if not (report.get("callable") and "words" in report):
                    continue
                if report["words"] or report["raw_literals"]:
                    continue  # 本体有素材仍验证失败：非委托断链，保持现状。
                func = getattr(
                    importlib.import_module(report["module"]), report["name"], None
                )
                if not callable(func):
                    continue
                try:
                    traced = harvest_function_material(func, _trace=True)
                except (OSError, TypeError, StopIteration, SyntaxError):
                    continue
                if not traced["words"]:
                    continue
                report["words"] = traced["words"]
                report["raw_literals"] = traced["raw_literals"]
                for word in traced["words"]:
                    if not word.strip() or word in verified:
                        continue
                    probe = verify_word(func, word)
                    if probe is None:
                        passive.append(word)
                    else:
                        verified[word] = {"probe": probe, "detector": report["name"]}
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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

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
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        DEFAULT_VERB_MAP,
    )

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
# 4) 触发词双向机械门（P2-9）：路由侧 ↔ help 侧词级全量 diff
# ---------------------------------------------------------------------------


def normalize_trigger_key(word: str) -> str:
    """双向比对归一键：剥 ``<占位符>``/省略号 + 去空白 + casefold。

    help 侧 triggers 常写「<时间>提醒我…」这类模式文档；剥掉占位骨架后
    剩「提醒我」才是可与路由面比对的实体词。路由侧 verified 词全部经过
    行为验证、不含占位符，此规则对其零影响（两侧同口径）。
    """
    text = re.sub(r"<[^>]*>", "", str(word or ""))
    text = re.sub(r"(…|\.{3,})$", "", text)
    return re.sub(r"\s+", "", text).casefold()


def _lookup_keys(word: str) -> list[str]:
    """动词表/探针查找键变体：原形、casefold、去空白、去空白+casefold。

    'music mode' / 'steam free' 这类带空格触发词在 help 侧原样书写、在
    DEFAULT_VERB_MAP 里也带空格，而归一键两侧都已去空白——路由面命中
    判定把几种形态都试到，宁可放行也不误报。
    """
    raw = str(word or "").strip()
    keys = {raw, raw.casefold(), re.sub(r"\s+", "", raw), re.sub(r"\s+", "", raw).casefold()}
    return sorted(key for key in keys if key)


def classify_help_topics(topics: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 capability 字段机械分类 help topic（零手工清单）。

    每项含：caps（字段引用的 bot.* 能力 id 集）、admin_path（字段整体恰为
    裸 ``/bot …`` 命令声明，带「（…）」注记的不算）、admin_caps（由命令头
    派生的 ``bot.<名>``，仅当与真实能力 id 同名才可能在动词表命中）、
    words（归一触发词全集）、doc_only（无能力 id 也无命令声明——纯文档
    检索词，设计上不可路由，方向2 豁免）。
    """
    classified: dict[str, dict[str, Any]] = {}
    for topic, info in topics.items():
        field = str(info.get("capability", "")).strip()
        core = re.split(r"[（(]", field)[0].strip()
        admin_path = core if core.startswith("/bot ") and core == field else ""
        parsed: dict[str, Any] = {
            "caps": set(re.findall(r"bot\.[a-z_]+", field)),
            "admin_path": admin_path,
            "words": {
                key
                for field_name in ("aliases", "triggers_nl", "triggers_nickname")
                for word in info.get(field_name) or ()
                if (key := normalize_trigger_key(word))
            },
        }
        parsed["admin_caps"] = {f"bot.{admin_path[5:].strip().split()[0]}"} if admin_path else set()
        parsed["doc_only"] = not parsed["caps"] and not admin_path
        classified[topic] = parsed
    return classified


def build_help_trigger_side(topics: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """help 侧词表：按能力 id 聚合触发词（含 '/bot <名>' 派生落点）。"""
    side: dict[str, set[str]] = {}
    for parsed in classify_help_topics(topics).values():
        for capability_id in parsed["caps"] | parsed["admin_caps"]:
            side.setdefault(capability_id, set()).update(parsed["words"])
    return side


def build_route_trigger_side(inventory: dict[str, Any]) -> dict[str, set[str]]:
    """路由侧词表：行为验证 verified_triggers ∪ DEFAULT_VERB_MAP 动词。"""
    side = {
        capability_id: {
            key
            for word in item["verified_triggers"]
            if (key := normalize_trigger_key(word))
        }
        for capability_id, item in inventory["capabilities"].items()
    }
    for capability_id, verbs in inventory["verb_map_groups"].items():
        side.setdefault(capability_id, set()).update(
            key for verb in verbs if (key := normalize_trigger_key(verb))
        )
    return side


def gate_route_to_help(
    route_side: dict[str, set[str]],
    help_side: dict[str, set[str]],
) -> list[tuple[str, str]]:
    """方向1（路由→帮助）：路由侧每个触发词必须在同能力 help 词表有落点。

    缺口即求籤先例形态：路由正则收得下、``/bot help <词>`` 搜不到。
    """
    return sorted(
        (capability_id, word)
        for capability_id, words in sorted(route_side.items())
        for word in sorted(words)
        if word not in help_side.get(capability_id, set())
    )


def live_detectors_by_capability(
    inventory: dict[str, Any] | None = None,
) -> dict[str, list[Any]]:
    """行为检测器实跑表：capability_id → [callable]（排序保证确定性）。"""
    inventory = inventory if inventory is not None else build_inventory()
    detectors: dict[str, list[Any]] = {}
    for capability_id, item in sorted(inventory["capabilities"].items()):
        for report in sorted(item["detectors"], key=lambda entry: entry["name"]):
            if not report.get("callable") or not report["name"].startswith("is_"):
                continue
            func = getattr(importlib.import_module(report["module"]), report["name"])
            if callable(func):
                detectors.setdefault(capability_id, []).append(func)
    return detectors


def flat_verb_map(inventory: dict[str, Any]) -> dict[str, str]:
    """DEFAULT_VERB_MAP 平铺（动词原样 → capability_id），方向2 路由面之一。"""
    return {
        verb: capability_id
        for capability_id, verbs in inventory["verb_map_groups"].items()
        for verb in verbs
    }


def _route_face_hit(
    word: str,
    detector_caps: set[str],
    reachable_caps: set[str],
    verb_map: dict[str, str],
    detectors: dict[str, list[Any]],
    nl_detect: Any = None,
) -> bool:
    """单词路由面命中：动词映射 / 行为检测器探针 / 自然语言归一，三选一。"""
    keys = _lookup_keys(word)
    alias_path = "bot.alias" in reachable_caps  # 昵称命令主题：任一动词经别名路径可达。
    for key in keys:
        capability_id = verb_map.get(key)
        if capability_id is not None and (
            capability_id in reachable_caps or alias_path
        ):
            return True
    for key in keys:
        for suffix in _PROBE_SUFFIXES:
            probe = key + suffix
            for capability_id in sorted(detector_caps):
                for func in detectors.get(capability_id, ()):
                    if _probe_hits(func, probe):
                        return True
            if nl_detect is not None:
                resolution = _probe_nl(nl_detect, probe)
                if resolution is not None and getattr(
                    resolution, "capability_id", ""
                ) in reachable_caps:
                    return True
    return False


def _probe_nl(nl_detect: Any, probe: str) -> Any:
    """自然语言归一探针：任何异常按未命中记账，不阻塞门检。"""
    try:
        return nl_detect(probe)
    except Exception:  # noqa: BLE001 - 同 _probe_hits 口径。
        return None


def gate_help_to_route(
    topics: dict[str, dict[str, Any]],
    verb_map: dict[str, str],
    detectors: dict[str, list[Any]] | None = None,
    nl_detect: Any | None = None,
) -> list[dict[str, Any]]:
    """方向2（帮助→路由）：help 每条触发词必须能被路由面命中。

    路由面三选一：动词映射（昵称命令，「守岸人 决策」不坠 help 兜底）、
    行为检测器探针（裸词/中性后缀，同 verified 口径）、自然语言归一
    （``detect_natural_command`` 返回的 capability_id 必须落在本 topic
    声明的能力内）。纯文档 topic（doc_only）豁免——capability 字段自己
    声明了无命令入口。返回缺口清单（topic/word/caps），排序保证确定性。
    """
    if nl_detect is None:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.natural_language import (
            detect_natural_command,
        )

        nl_detect = detect_natural_command
    detectors = detectors if detectors is not None else live_detectors_by_capability()
    violations: list[dict[str, Any]] = []
    for topic, parsed in sorted(classify_help_topics(topics).items()):
        if parsed["doc_only"]:
            continue
        reachable = parsed["caps"] | parsed["admin_caps"]
        for word in sorted(parsed["words"]):
            if _route_face_hit(
                word, parsed["caps"], reachable, verb_map, detectors, nl_detect
            ):
                continue
            violations.append({"topic": topic, "word": word, "caps": sorted(reachable)})
    return violations


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
    route_side = build_route_trigger_side(inventory)
    help_side = build_help_trigger_side(inventory["help_topics"])
    gate_detectors = live_detectors_by_capability(inventory)
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
        "gate_route_to_help_gaps": gate_route_to_help(route_side, help_side),
        "gate_help_to_route_violations": gate_help_to_route(
            inventory["help_topics"], flat_verb_map(inventory), gate_detectors
        ),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    inventory = build_inventory()
    payload = inventory if "--full" in argv else summarize(inventory)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):  # pragma: no cover - 老终端兜底。
        reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
