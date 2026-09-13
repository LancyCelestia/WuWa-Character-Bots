"""T-Spec 触发指令规范化——规格无关机械化体检（红点台账制）。

基础设施（scripts/extract_trigger_words.py）从当前源码机械化提取：
RouteRule↔检测函数映射、各 ``is_*`` 函数字面触发素材、help 触发记录、
DEFAULT_VERB_MAP，并做行为级体检（探针实跑，非纸面词表比对）：

1. 映射完整性：每条 RouteRule 有可调用 matcher；命令类路由必有 ``is_*``
   行为检测器；help 每个 topic 必有触发记录（aliases/triggers_nl/
   triggers_nickname 至少其一）。
2. 冲突检测：任一 verified 触发词探针跑全部 ``is_*`` 检测器必须唯一命中
   所属 capability。
3. 词边界纪律：ASCII 触发词按 ``_alias_hit`` 模式（词边界）匹配——
   ``qq<word>`` / ``<word>qq`` 胶合探针不得命中自身能力。

现状红点以**台账制**管理（这是体检不是改造，不改源码凑绿）：
- ``KNOWN_CONFLICT_WORDS`` / ``KNOWN_BOUNDARY_KEYS`` 登记基线实测红点
  （2026-09-12 基线，含并行 T1.2 英文触发在途改动），用例内
  ``pytest.xfail`` 标记，并带双向棘轮：台账条目被修复 → 强制失败提醒清
  台账；台账外新增红点 → 硬断言失败，自动浮出为规范化波工作清单。
- 规格相关断言（七格矩阵：英文/简体/繁體/全拼/缩写/昵称/自然语言的
  全量覆盖与唯一性）待 T-Spec 终确认后启用，见文末 skip 占位。
"""

from __future__ import annotations

import importlib

import pytest

from scripts.extract_trigger_words import (
    _ASCII_WORD_RE,
    _STRUCTURAL_KINDS,
    build_inventory,
)

INV = build_inventory()

# 行为检测器实跑表：capability_id -> [callable]（排序保证确定性）。
_LIVE_DETECTORS: dict[str, list] = {}
_DETECTOR_BY_NAME: dict[tuple[str, str], object] = {}
for _cap in sorted(INV["capabilities"]):
    for _report in INV["capabilities"][_cap]["detectors"]:
        if not _report.get("callable") or not _report["name"].startswith("is_"):
            continue
        _func = getattr(importlib.import_module(_report["module"]), _report["name"])
        _LIVE_DETECTORS.setdefault(_cap, []).append(_func)
        _DETECTOR_BY_NAME[(_cap, _report["name"])] = _func

# verified 触发词探针全集：(capability_id, word, probe, detector_name)。
_VERIFIED_CASES: list[tuple[str, str, str, str]] = sorted(
    (_cap, _word, _info["probe"], _info["detector"])
    for _cap, _item in INV["capabilities"].items()
    for _word, _info in _item["verified_triggers"].items()
)

# ASCII 词边界探针全集：(capability_id, word, side, glued_probe, detector)。
_BOUNDARY_CASES: list[tuple[str, str, str, str, str]] = sorted(
    (
        _cap,
        _word,
        _side,
        _glued,
        INV["capabilities"][_cap]["verified_triggers"][_word]["detector"],
    )
    for _cap, _item in INV["capabilities"].items()
    for _word in sorted(_item["verified_triggers"])
    if len(_word.strip()) >= 2 and _ASCII_WORD_RE.fullmatch(_word.strip())
    for _side, _glued in (("left", "qq" + _word.strip()), ("right", _word.strip() + "qq"))
)


def _probe_hits_all(probe: str) -> list[str]:
    """探针跑全部 is_* 检测器，返回命中的 capability_id 列表（排序）。"""
    return sorted(
        cap for cap in sorted(_LIVE_DETECTORS) if any(func(probe) for func in _LIVE_DETECTORS[cap])
    )


# ---------------------------------------------------------------------------
# 现状红点台账（2026-09-12 基线；规范化波工作清单，修复后必须同步清账）
# ---------------------------------------------------------------------------

# 跨能力触发冲突：同一探针命中多个 capability（当前由路由优先级兜底，词表层未收敛）。
# 已全部清账（2026-09-13 RF 波，xfail 11→0）：music_mode ×4（点歌模式/點歌模式/
# music mode/song mode）裸词由 music._COMMAND_RE 加 mode 负前瞻整体让渡，
# 裸词唯一命中 music_mode；带歌名/参数后继形态保持双命中让路对（既有形态）。
# 详见 .superpowers/sdd/2026-09-12-shorekeeper-global-audit/fix-rf-report.md。
KNOWN_CONFLICT_WORDS: frozenset[tuple[str, str]] = frozenset()

# ASCII 词边界违规：胶合探针命中自身能力（_alias_hit 纪律：ASCII 词须词边界）。
# 已全部清账（2026-09-13，两波）：
# ①对账波（fix-ratchet-report.md）：bot.stocks openai/anthropic/bytedance
#   left/right ×6 死账移除——HIJACK-FIX 后裸英文公司名已非 verified 触发词，
#   对应参数化用例不再生成，靠人工对账清除。
# ②RF 波（fix-rf-report.md，xfail 11→0）：affinity/meme/meme_library ×2/
#   music/weather ×7 右胶合已补词边界（IGNORECASE 正则用 (?![a-z0-9])，
#   weather 无 IGNORECASE 用 (?![A-Za-z0-9])）。
KNOWN_BOUNDARY_KEYS: frozenset[tuple[str, str, str]] = frozenset()


# ---------------------------------------------------------------------------
# 映射完整性（规格无关，硬断言）
# ---------------------------------------------------------------------------


def test_route_registry_matches_live_route_rules() -> None:
    """AST 提取的规则表必须与运行时 ROUTE_RULES 同构（防提取器脱册）。"""
    from plugins.bot_unified_runtime.runtime.base_router import ROUTE_RULES

    live = sorted(
        (rule.kind.name, rule.capability_id, rule.priority) for rule in ROUTE_RULES
    )
    extracted = sorted(
        (rule["kind"], rule["capability_id"], rule["priority"])
        for rule in INV["route_rules"]
    )
    assert extracted == live
    assert all(rule.matcher is not None and callable(rule.matcher) for rule in ROUTE_RULES)


def test_command_rules_have_behavioral_detector() -> None:
    """命令类路由（非结构类）必须至少挂一个 is_* 行为检测器。"""
    weak = [
        rule["capability_id"]
        for rule in INV["route_rules"]
        if rule["kind"] not in _STRUCTURAL_KINDS
        and not any(name.startswith("is_") for name in rule["detectors"])
    ]
    assert weak == []


def test_all_behavioral_detectors_callable() -> None:
    broken = [
        (cap, report["name"])
        for cap, item in INV["capabilities"].items()
        for report in item["detectors"]
        if report["name"].startswith("is_") and not report.get("callable")
    ]
    assert broken == []


def test_structural_rules_are_classified() -> None:
    """结构类路由（别名/管理员/自然语言/链接/聊天）登记在案，防漏分诊。"""
    structural = sorted(set(INV["structural_rule_kinds"]))
    assert structural == ["ADMIN", "ALIAS", "CHAT", "CONTENT", "NATURAL_COMMAND"]


def test_help_topics_have_trigger_records() -> None:
    """help 每个 topic 必有触发记录（aliases / triggers_nl / triggers_nickname）。"""
    assert INV["help_topics_missing_trigger_records"] == []


def test_help_topics_have_capability_ref() -> None:
    missing = [
        topic
        for topic, info in INV["help_topics"].items()
        if not info["capability"]
    ]
    assert missing == []


def test_default_verb_map_registered() -> None:
    """DEFAULT_VERB_MAP 非空且逐条指向能力 id（昵称命令动词映射基线）。"""
    groups = INV["verb_map_groups"]
    assert groups
    assert all(verb for verbs in groups.values() for verb in verbs)


# ---------------------------------------------------------------------------
# 冲突检测：verified 触发词探针必须唯一命中所属能力（台账制棘轮）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap,word,probe,_detector", _VERIFIED_CASES, ids=lambda x: str(x))
def test_verified_trigger_hits_owner_capability(cap: str, word: str, probe: str, _detector: str) -> None:
    hits = _probe_hits_all(probe)
    if (cap, word) in KNOWN_CONFLICT_WORDS:
        if hits == [cap]:
            pytest.fail(
                f"红点已修复：{word!r} 不再跨能力冲突，请从 KNOWN_CONFLICT_WORDS 移除 {(cap, word)}"
            )
        pytest.xfail(f"现状红点（台账已登记）：{word!r} 同时命中 {hits}")
    assert hits == [cap], f"新增跨能力冲突（未登记台账）：{word!r} 探针 {probe!r} 命中 {hits}"


# ---------------------------------------------------------------------------
# 词边界纪律：ASCII 触发词胶合探针不得命中（_alias_hit 模式，台账制棘轮）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cap,word,side,glued,detector_name", _BOUNDARY_CASES, ids=lambda x: str(x)
)
def test_ascii_trigger_word_boundary(
    cap: str, word: str, side: str, glued: str, detector_name: str
) -> None:
    func = _DETECTOR_BY_NAME[(cap, detector_name)]
    violated = bool(func(glued))
    if (cap, word, side) in KNOWN_BOUNDARY_KEYS:
        if not violated:
            pytest.fail(
                f"红点已修复：{word!r} {side} 侧已词边界，请从 KNOWN_BOUNDARY_KEYS 移除"
            )
        pytest.xfail(
            f"现状红点（台账已登记）：{detector_name} 对胶合探针 {glued!r} 仍裸子串命中"
        )
    assert not violated, (
        f"新增 ASCII 词边界违规（未登记台账）：{cap} {detector_name} 命中 {glued!r}"
    )


# ---------------------------------------------------------------------------
# T-Spec 七格矩阵（规格相关，待用户终确认后启用）
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="待 T-Spec 七格触发矩阵终确认后启用：英文/简体/繁體/昵称/自然语言全量覆盖与唯一性断言")
def test_seven_grid_spec_coverage() -> None:
    raise AssertionError("placeholder")


@pytest.mark.skip(reason="待 T-Spec 终确认且 PYN 拼音表落地后启用：全拼/缩写格覆盖断言")
def test_pinyin_abbreviation_grid_coverage() -> None:
    raise AssertionError("placeholder")
