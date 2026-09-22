"""T8 族合法性锁（2026-09-22）：定级的**任何腿**（色词 / 关键词 / 震级）不得提出族外档。

背景（`.superpowers/sdd/2026-09-22-taxonomy/SEAT-MAIN.md` §1 判定 6 第 2 条，
REV-WP3 评审遗留 Important）：色腿早带「族内合法才计」闸，**关键词腿没有闸**——
`category_id="wildfire"`（`global_disaster` 族结构上只有橙/红，注册表判
`level_is_attainable("wildfire", P2) is False`）配正文「航班延误」，修复前的
`grading_candidates()` 照样提出 P2、`grade()` 取其作终档。既有摘牌锁
`test_emergency_info_taxonomy.py::test_grading_reads_the_registry_for_every_category_family`
只喂色词、从不喂关键词，这条不变式在那之前无执法。

本件三层执法（全离线：零网络、零写库、零生产数据；仓库内既有测试件一寸未动）：

1. **参数化不变式**——注册表全族 × 缺省关键词表逐词、四色（标题色词腿与源侧色腿）、
   震级矩阵：候选必须 ⊆ 该族可达档；族外档既不得出现，族内合法档不得被误杀。
2. **复现钉死 + 反例**——简报样本 wildfire+「航班延误」出档即红；wildfire+「爆炸」
   （P0，族内合法）照提；注入表与缺省表同闸（评审侧词表不得架空族约束）。
3. **注毒自证 ×3**——把 `grading.py` 源码在**内存中**改松（分别去掉三条腿的族闸），
   重放编译后同一批样本必须漏出族外档 ⇒ 本件谓词在该构建下必红，证明锁有牙
   （不写任何源码树文件；对照构建还锁了「重放装置与生产等值」，防注毒装置空跑）。

「改松必红」另有一发活证据：修复前（关键词腿无闸的 HEAD 态）直接跑本件，
invariant/reproduction/injected/M1 应红——现码即"族约束改松"态，见 T8 报告。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    LEVEL_COLOR_LABEL,
    EmergencyItem,
    EmergencyLevel,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import grading
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    DEFAULT_GRADING_RULES,
    GradingRule,
)

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _item(**overrides: Any) -> EmergencyItem:
    """最小合法条目；缺省无颜色、无震级，用例只覆盖自己要验的那一格。"""
    data: dict[str, Any] = {
        "item_id": "t8-1",
        "source_id": "nmc",
        "source_kind": "weather_alarm",
        "external_id": "ext-t8",
        "title": "某地事件通报",
        "body": "",
        "url": "",
        "color_label": "",
        "occurred_at": _NOW,
        "fetched_at": _NOW,
        "credibility": 0.9,
    }
    data.update(overrides)
    built = build_emergency_item(data)
    assert built is not None, "夹具自身不合法，用例结论无意义"
    return built


def _assert_all_family_legal(category_id: str, candidates: list[EmergencyLevel]) -> None:
    """不变式谓词：候选 ⊆ 该族可达档。"""
    for level in candidates:
        assert taxonomy.level_is_attainable(category_id, level), (
            f"族外档漏出：{category_id} 族可达档不含 {level.value}，候选={candidates}"
        )


# ================================================== 1. 关键词腿 × 全族参数化不变式


@pytest.mark.parametrize("spec", taxonomy.categories(), ids=lambda s: s.category_id)
def test_keyword_leg_never_proposes_levels_outside_the_family(spec: Any) -> None:
    """缺省关键词表逐词喂给每个注册类别：只准提出「该族结构上可达」的档。

    同时反向锁「合法档不得被误杀」：族内可达且该词所属档 ⇒ 必须出现
    （quake 族无震级时关键词腿按 §四 整条不参与，候选必须为空，另设断言）。
    """
    family = taxonomy.family_for(spec.category_id)
    for rule in DEFAULT_GRADING_RULES:
        for keyword in rule.keywords:
            item = _item(
                category_id=spec.category_id,
                title=f"{spec.label}事件通报",
                body=f"现场通报：{keyword}",
            )
            candidates = grading.grading_candidates(item, now=_NOW)
            _assert_all_family_legal(spec.category_id, candidates)
            if family.family_id == taxonomy.QUAKE_FAMILY_ID:
                assert candidates == [], (
                    f"quake 族无震级时关键词腿不得出档：{keyword} → {candidates}"
                )
                continue
            attainable = taxonomy.level_is_attainable(spec.category_id, rule.level)
            assert (rule.level in candidates) is attainable, (
                f"{spec.category_id} +「{keyword}」：可达={attainable}，候选={candidates}"
            )


# ================================================== 2. 复现样本 / 正反例 / 注入表同闸


def test_wildfire_delay_keyword_cannot_propose_p2() -> None:
    """评审席钉死的复现样本：wildfire + 「航班延误」不得再出 P2（族外档＝错配噪声）。"""
    assert taxonomy.level_is_attainable("wildfire", EmergencyLevel.P2) is False
    item = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="森林草原火灾事件通报",
        body="航班延误",
    )
    assert grading.grading_candidates(item, now=_NOW) == []
    assert grading.grade(item, now=_NOW) is EmergencyLevel.P3


def test_family_legal_keyword_still_proposes_for_global_disaster() -> None:
    """收紧只杀族外档：橙/红是 global_disaster 的合法档，硬事实词照旧出档。"""
    fire = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="森林草原火灾事件通报",
        body="现场发生爆炸",
    )
    assert grading.grading_candidates(fire, now=_NOW) == [EmergencyLevel.P0]
    flood = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="flood_event",
        title="洪水事件通报",
        body="重大泄漏",
    )
    assert EmergencyLevel.P1 in grading.grading_candidates(flood, now=_NOW)


def test_injected_rules_are_bound_by_the_family_gate_too() -> None:
    """注入表与缺省表同闸（§四 6「只影响关键词腿」≠可以架空族约束）。"""
    injected = (
        GradingRule(
            level=EmergencyLevel.P2,
            keywords=("聚集围观",),
            note="评审侧注入的档外词",
        ),
    )
    wildfire = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="森林草原火灾事件通报",
        body="现场聚集围观",
    )
    assert grading.grading_candidates(wildfire, now=_NOW, rules=injected) == []
    # 族内合法（meteo 四色俱全）⇒ 同一个注入词照常出档，防收紧误杀正常腿。
    storm = _item(category_id="rainstorm", title="暴雨事件通报", body="现场聚集围观")
    assert grading.grading_candidates(storm, now=_NOW, rules=injected) == [
        EmergencyLevel.P2
    ]


# ================================================== 3. 色腿与震级腿（既有闸不得回退）


@pytest.mark.parametrize("spec", taxonomy.categories(), ids=lambda s: s.category_id)
def test_color_legs_and_fallback_stay_family_legal(spec: Any) -> None:
    """源侧色与标题色词逐色扫一遍：可达色必须出档、族外色必须无声，等级=候选最高或 P3。"""
    family = taxonomy.family_for(spec.category_id)
    for level, color in LEVEL_COLOR_LABEL.items():
        attainable = taxonomy.level_is_attainable(spec.category_id, level)
        source_item = _item(
            category_id=spec.category_id,
            title=f"{spec.label}事件通报",
            color_label=color,
        )
        source_cands = grading.grading_candidates(source_item, now=_NOW)
        _assert_all_family_legal(spec.category_id, source_cands)
        assert (level in source_cands) is attainable, (
            f"{spec.category_id} 源侧「{color}」：可达={attainable}，候选={source_cands}"
        )
        title_item = _item(
            category_id=spec.category_id,
            title=f"{spec.label}事件通报：{color}预警",
        )
        title_cands = grading.grading_candidates(title_item, now=_NOW)
        _assert_all_family_legal(spec.category_id, title_cands)
        # quake 族无震级时标题色词整条不参与（数才是事实，§四 2），只有源侧官方色可出档。
        expect_title = attainable and family.family_id != taxonomy.QUAKE_FAMILY_ID
        assert (level in title_cands) is expect_title, (
            f"{spec.category_id} 标题「{color}」：应出档={expect_title}，候选={title_cands}"
        )


@pytest.mark.parametrize(
    "magnitude,latitude,longitude,expected",
    [
        (4.0, 28.5, 104.9, EmergencyLevel.P2),
        (6.5, 28.5, 104.9, EmergencyLevel.P0),
        (6.5, 35.7, 140.1, EmergencyLevel.P2),
        (8.1, 35.7, 140.1, EmergencyLevel.P1),
        (2.9, 28.5, 104.9, EmergencyLevel.P3),
    ],
)
def test_quake_magnitude_leg_levels_are_family_legal(
    magnitude: float,
    latitude: float,
    longitude: float,
    expected: EmergencyLevel,
) -> None:
    """震级腿唯一档、且 quake 族四色俱全 ⇒ 恒族内合法；关键词与颜色不得再叠第二候选。"""
    item = _item(
        source_id="usgs",
        source_kind="earthquake",
        category_id="earthquake",
        title=f"{magnitude}级地震｜某地",
        body="现场通报：积水、航班延误",
        magnitude=magnitude,
        depth_km=10.0,
        latitude=latitude,
        longitude=longitude,
    )
    candidates = grading.grading_candidates(item, now=_NOW)
    _assert_all_family_legal("earthquake", candidates)
    assert candidates == [expected]


def test_grade_is_still_a_projection_of_candidates() -> None:
    """投影关系不变：非空取最高档、空集落 P3（本件所有新闸都走同一真身）。"""
    samples = (
        _item(category_id="rainstorm", title="暴雨事件通报", body="现场通报：积水"),
        _item(category_id="wildfire", title="野火事件通报", body="航班延误"),
        _item(category_id="fog", title="大雾黄色预警信号", color_label="黄色"),
    )
    for item in samples:
        candidates = grading.grading_candidates(item, now=_NOW)
        expected = (
            max(candidates, key=lambda level: level.rank)
            if candidates
            else EmergencyLevel.P3
        )
        assert grading.grade(item, now=_NOW) is expected


# ================================================== 4. 注毒自证 ×3（内存重放，零写树）

_GRADING_SOURCE = Path(grading.__file__).resolve().read_text(encoding="utf-8")

# 三条腿各自的「族闸」原文（收紧后的源码字面，锚点唯一性由 _rebuilt 现算核验）。
_KEYWORD_LEG_FILTERED = (
    "    candidates.extend(\n"
    "        level for level in matched_levels(text, rules) if level in legal\n"
    "    )"
)
_TEXT_COLOR_LEG_FILTERED = (
    "    candidates.extend(\n"
    "        level for level in color_levels_in_text(text) if level in legal\n"
    "    )"
)
_SOURCE_COLOR_LEG_FILTERED = (
    "    if source_level is not None and source_level in legal:\n"
    "        candidates.append(source_level)"
)


def _rebuilt(mutations: list[tuple[str, str]], tag: str) -> ModuleType:
    """把 grading.py 源码按注毒表改松后在内存重放编译（不写任何源码树文件）。"""
    source = _GRADING_SOURCE
    for old, new in mutations:
        assert source.count(old) == 1, f"注毒锚点在现源码出现 {source.count(old)} 次：{tag}"
        source = source.replace(old, new)
    module = ModuleType(f"grading_poison_{tag}")
    # dataclasses 解析 `from __future__ import annotations` 的字符串注解时要经
    # sys.modules 按 __module__ 找回本模块命名空间——不注册，注毒重放会死在
    # @dataclass 构造上（首版装置自伤，见 SEAT-T8.md [t3]）。
    sys.modules[module.__name__] = module
    exec(compile(source, f"<grading-poison:{tag}>", "exec"), module.__dict__)  # noqa: S102
    return module


def _wildfire_illegal_candidates(module: ModuleType) -> list[EmergencyLevel]:
    return list(
        module.grading_candidates(
            _item(category_id="wildfire", title="森林草原火灾事件通报", body="航班延误"),
            now=_NOW,
        )
    )


def test_poison_harness_control_build_matches_production() -> None:
    """注毒装置自检：零替换重放必须与生产模块逐字同值（否则注毒「变红」是装置自己坏）。"""
    control = _rebuilt([], "control")
    for item in (
        _item(category_id="wildfire", title="野火事件通报", body="航班延误"),
        _item(category_id="rainstorm", title="暴雨事件通报", body="现场通报：积水"),
    ):
        assert control.grading_candidates(item, now=_NOW) == grading.grading_candidates(
            item, now=_NOW
        )


def test_poison_unfiltered_keyword_leg_leaks_illegal_level() -> None:
    """注毒①：拆掉关键词腿族闸（回到 2026-09-22 修复前形态）⇒ wildfire+「航班延误」漏 P2。"""
    mutant = _rebuilt([(_KEYWORD_LEG_FILTERED, "    candidates.extend(matched_levels(text, rules))")], "kw")
    leaked = _wildfire_illegal_candidates(mutant)
    assert EmergencyLevel.P2 in leaked
    assert not all(taxonomy.level_is_attainable("wildfire", lv) for lv in leaked)


def test_poison_unfiltered_text_color_leg_leaks_illegal_level() -> None:
    """注毒②：拆掉标题色词腿族闸 ⇒ global_disaster 标题里的「蓝色」漏成不可达 P3。"""
    mutant = _rebuilt(
        [(_TEXT_COLOR_LEG_FILTERED, "    candidates.extend(color_levels_in_text(text))")],
        "color",
    )
    item = _item(category_id="wildfire", title="野火事件通报：蓝色预警")
    leaked = mutant.grading_candidates(item, now=_NOW)
    assert EmergencyLevel.P3 in leaked
    assert not all(taxonomy.level_is_attainable("wildfire", lv) for lv in leaked)


def test_poison_unfiltered_source_color_leg_leaks_illegal_level() -> None:
    """注毒③：拆掉源侧色腿族闸 ⇒ GDACS 侧若塞来「黄色」也照收，漏成不可达 P2。"""
    mutant = _rebuilt(
        [
            (
                _SOURCE_COLOR_LEG_FILTERED,
                "    if source_level is not None:\n        candidates.append(source_level)",
            )
        ],
        "source",
    )
    item = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="野火事件通报",
        color_label="黄色",
    )
    leaked = mutant.grading_candidates(item, now=_NOW)
    assert EmergencyLevel.P2 in leaked
    assert not all(taxonomy.level_is_attainable("wildfire", lv) for lv in leaked)
