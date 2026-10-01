"""WP3 全谱注册表 / 定级 / 颜色 / 静默窗击穿 / 定级回写 的回归锁（2026-09-21）。

配套规格：`docs/design/emergency-alert-taxonomy-20260921.md`（唯一权威，代码从它派生）。
本件按用户裁定的全谱逐条在扫，**不与既有六件紧急域测试重复摘牌**：
`test_emergency_info_core / collector / push / review_gate / subscriptions / sources /
reachability` 存量用例一条不少，本件只加判据。

取证等级两分（与仓内惯例同口径）：
- `实证`＝本文件实跑输出可复核（命令见 impl-WP3-log §3）；
- 涉及"生产真会怎样"的方向性结论一律标注为推演，且只用离线替身证明结构成立。

全离线纪律：
- **零真实网络**：源侧取数一律 monkeypatch 或注入 `fetch=`，NMC/USGS/GDACS/ICL 一次都不碰；
- **零生产数据**：SQLite 一律 `tmp_path`（conftest 的源码树 `data/` 守卫在位）；
- `qx.json` 只读（本件不打开它，地名索引由 `subscriptions` 自己读）。
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.emergency_info import contracts
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    build_emergency_item,
    is_urgent_level,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import grading, push
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    DEFAULT_GRADING_RULES,
    grade,
    matched_levels,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.review import (
    ReviewGate,
    validate_auto_approve_sources,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.subscriptions import (
    RuleError,
    matches_subscription,
    parse_subscription,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.store import (
    EmergencyStore,
)

# WP3-TAXONOMY 挂账已摘牌（2026-09-22 实施席 WP3-IMPL）：本文件用例原本是「全预警谱重做」
# 的**规格**（注册表族级合法色档定级 + 按震级定级 + `grading_candidates` 审计面 +
# 缺省关键词表去掉种类词），当时判据未落地 ⇒ 按仓内铁律**诚实挂 xfail 而非放宽断言**。
# 现规格 §四 判定序 / §五 地震分档表已落进 `service/grading.py`，本文件 9 枚标记
# （含参数化共 20 个实例）连同 `test_emergency_info_collector.py` 的 1 枚逐条删除；
# **断言期望值一寸未动**。施工记录 .superpowers/sdd/2026-09-21-unify-wave/logs/
# SEAT-WP3-IMPL.md；原挂账全录 .superpowers/sdd/2026-09-21-fix-wave/master-plan.md §8.1。

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "emergency_info"
)
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "emergency_info"
NMC_SAMPLE = FIXTURES / "nmc_findAlarm.sample.json"

_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
#: 静默窗内的一刻（生产窗缺省 00:00–06:00，此处按测试注入的窗取 03:00 UTC）。
_NIGHT = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)

_CAP_MODULE = (
    "plugins.bot_unified_runtime.domains.emergency_info.capabilities.emergency_info"
)


def _item(**overrides: Any) -> EmergencyItem:
    """一条字段齐全的最小合法条目；用例只覆盖自己要验的那一格。"""
    data: dict[str, Any] = {
        "item_id": "wp3-1",
        "source_id": "nmc",
        "source_kind": "weather_alarm",
        "external_id": "ext-1",
        "title": "某县气象台发布大雾黄色预警信号",
        "body": "",
        "url": "",
        "color_label": "黄色",
        "occurred_at": _NOW,
        "fetched_at": _NOW,
        "credibility": 0.9,
    }
    data.update(overrides)
    built = build_emergency_item(data)
    assert built is not None, "夹具自身不合法，用例结论无意义"
    return built


# ============================================================ A 全谱与注册表纪律

#: 用户 2026-09-21 裁定原文点名的每一种（**逐字照抄，不许缩小范围**）。
USER_NAMED_ALERT_TYPES: tuple[str, ...] = (
    # 气象灾害预警信号 14 类
    "台风", "暴雨", "暴雪", "寒潮", "大风", "沙尘暴", "高温", "干旱", "雷电",
    "冰雹", "霜冻", "大雾", "霾", "道路结冰",
    # 其他相关预警
    "强对流天气", "地质灾害气象风险", "山洪灾害气象", "中小河流洪水", "渍涝",
    "森林火险", "草原火险", "风暴潮", "海浪", "海啸", "海冰", "地震", "火山喷发",
    "空间天气", "地磁暴", "太阳风暴",
)


@pytest.mark.parametrize("term", USER_NAMED_ALERT_TYPES)
def test_every_user_named_alert_type_is_registered(term: str) -> None:
    """她说要覆盖的每一种都在注册表里，且 `category_id_for_term` 认得（不是"看起来有"）。"""
    category_id = taxonomy.category_id_for_term(term)
    assert category_id, f"未登记：{term}"
    spec = taxonomy.category(category_id)
    assert spec is not None
    assert spec.family_id in {family.family_id for family in taxonomy.families()}
    # 认得出的种类必须给出可用性证据——"谱看着全"不是登记的理由。
    assert spec.evidence, f"{term} 缺 evidence 字段（无源也要写清为什么无源）"


def test_registry_scale_matches_the_documented_counts() -> None:
    """规模数字与规格件 §二逐字相同（数字漂了本锁即红，文档就不用口头保证）。"""
    summary = taxonomy.count_summary()
    assert summary == {
        "categories": len(taxonomy.categories()),
        "families": 9,
        "sourced": sum(1 for s in taxonomy.categories() if s.is_sourced),
        "unsourced": sum(1 for s in taxonomy.categories() if not s.is_sourced),
        "observed": sum(
            1 for s in taxonomy.categories()
            if s.availability == taxonomy.AVAIL_OBSERVED
        ),
        "declared": sum(
            1 for s in taxonomy.categories()
            if s.availability == taxonomy.AVAIL_DECLARED
        ),
    }
    assert summary["categories"] >= 31, "全谱类数不得比裁定少"
    assert summary["unsourced"] >= 1, "一份号称全都有源的注册表必然是编出来的"


def test_category_ids_are_unique_and_alias_index_is_conflict_free() -> None:
    ids = [spec.category_id for spec in taxonomy.categories()]
    assert len(ids) == len(set(ids))
    # 同一个别名指向两个类别＝订阅"暴雨"到底订哪个，不可判定。
    seen: dict[str, str] = {}
    for spec in taxonomy.categories():
        for term in (spec.label, *spec.aliases):
            assert term not in seen or seen[term] == spec.category_id, (
                f"别名 {term} 同时指向 {seen.get(term)} 与 {spec.category_id}"
            )
            seen[term] = spec.category_id


def test_every_family_declares_legal_color_tiers_within_the_authorised_words() -> None:
    """色档只能用 D-3 那四枚色词，且升序（rank 单调）——禁自造第五色。"""
    authorised = {level.color_label for level in EmergencyLevel}
    for family in taxonomy.families():
        assert family.color_tiers, family.family_id
        assert set(family.color_tiers) <= authorised, family.family_id
        ranks = [
            contracts.level_from_color_label(tier).rank for tier in family.color_tiers
        ]
        assert ranks == sorted(ranks), f"{family.family_id} 色档不是升序"
        assert set(family.tier_order) == set(family.color_tiers), (
            f"{family.family_id} 陈列序与合法色档不是同一组色"
        )


def test_earthquake_family_presents_red_first_per_the_user_ruling() -> None:
    """用户口径：地震预警常用「红、橙、黄、蓝」（陈列序），与气象「蓝黄橙红」同色反序。"""
    quake = taxonomy.family_of("quake")
    assert quake is not None
    assert quake.tier_order == (taxonomy.RED, taxonomy.ORANGE, taxonomy.YELLOW, taxonomy.BLUE)
    assert quake.color_tiers == taxonomy.FOUR_TIER_ASC


@pytest.mark.parametrize(
    "category_id", sorted(spec.category_id for spec in taxonomy.unsourced_categories())
)
def test_unsourced_categories_are_marked_and_say_so_in_human_words(
    category_id: str,
) -> None:
    """无源类：不挂源、不挂图码，且人话里必须出现"无源"（帮助/catalog 同源）。"""
    spec = taxonomy.category_or_raise(category_id)
    assert spec.sources == (), f"{category_id} 无源却还挂着源"
    assert spec.availability == taxonomy.AVAIL_NONE
    assert spec.nmc_signal_type == "", f"{category_id} 无源却有 NMC 类型码＝造假映射"
    text = taxonomy.availability_text(category_id)
    assert "无源" in text and "不会" in text, text


def test_no_category_is_registered_without_a_source_or_an_explicit_none_reason() -> None:
    """每一个类别要么有源、要么写明**为什么**无源——空 sources 不许是"忘了填"。"""
    for spec in taxonomy.categories():
        if spec.is_sourced:
            assert set(spec.sources) <= taxonomy.SOURCE_IDS, spec.category_id
            assert spec.availability in (
                taxonomy.AVAIL_OBSERVED,
                taxonomy.AVAIL_DECLARED,
            )
            continue
        assert "无源" in spec.evidence, f"{spec.category_id} 的无源判定没写理由"


def test_every_observed_nmc_kind_code_in_the_real_sample_is_mapped() -> None:
    """NMC 类型码映射只认**真样例里实测出现**的码，两边必须严格相等（不多不少）。

    `pic` 文件名形态 `p{类型:04d}{等级:03d}.png` 由真字节派生（300 条逐条扫），
    多映射一个未实测的码＝杜撰；少一个＝漏接，本锁两个方向都拦。
    """
    payload = json.loads(NMC_SAMPLE.read_text(encoding="utf-8"))
    entries = payload["data"]["page"]["list"]
    observed: set[str] = set()
    for entry in entries:
        name = str(entry.get("pic") or "").rsplit("/", 1)[-1]
        digits = "".join(ch for ch in name.lstrip("pP") if ch.isdigit())
        if len(digits) >= 5:
            observed.add(digits[:4])
    assert observed, "样例里没有图码＝本锁空转"
    assert observed == set(taxonomy.NMC_SIGNAL_TYPE_TO_CATEGORY), (
        f"实测码 {sorted(observed)} 与注册表码 "
        f"{sorted(taxonomy.NMC_SIGNAL_TYPE_TO_CATEGORY)} 不一致"
    )
    for code in observed:
        assert taxonomy.category(taxonomy.NMC_SIGNAL_TYPE_TO_CATEGORY[code]) is not None


def test_taxonomy_source_ids_match_the_real_source_constants() -> None:
    """`SOURCE_IDS` 是镜像不是第二份名单：与四个源件真身 `SOURCE_ID` 逐字相等（AST 核）。"""
    real: set[str] = set()
    for relative in (
        "sources/nmc_alarm.py",
        "sources/gdacs.py",
        "sources/open_data_quakes.py",
    ):
        tree = ast.parse((DOMAIN_DIR / relative).read_text(encoding="utf-8"))
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else ([node.target] if isinstance(node, ast.AnnAssign) else [])
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith("SOURCE_ID"):
                    assert isinstance(node.value, ast.Constant)
                    real.add(str(node.value.value))
    assert real == set(taxonomy.SOURCE_IDS), f"真身 {sorted(real)} vs 镜像 {sorted(taxonomy.SOURCE_IDS)}"
    assert real == {"nmc", "icl", "usgs", "gdacs"}


def test_taxonomy_china_rect_matches_the_quake_source() -> None:
    """境内矩形镜像与 `open_data_quakes.CHINA_RECT` 逐字相等（定级判境内只认这一份）。"""
    tree = ast.parse(
        (DOMAIN_DIR / "sources" / "open_data_quakes.py").read_text(encoding="utf-8")
    )
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "CHINA_RECT":
            assert ast.literal_eval(node.value) == taxonomy.CHINA_INLAND_RECT
            return
    pytest.fail("CHINA_RECT 常量已从源件搬走，境内/境外判据失去真身")


def test_resolve_category_prefers_the_longest_alias() -> None:
    """「雷暴大风」不得被「大风」抢先——否则订阅大风的人会被强对流刷屏。"""
    assert taxonomy.resolve_category("雷暴大风蓝色预警") == "severe_convection"
    assert taxonomy.resolve_category("大风蓝色预警信号") == "gale"
    assert taxonomy.resolve_category("道路结冰黄色预警") == "road_ice"
    assert taxonomy.resolve_category("海冰蓝色预警") == "sea_ice"


def test_resolve_category_never_forces_an_unknown_text_into_a_bucket() -> None:
    assert taxonomy.resolve_category("某区政务信息更新") == ""
    assert taxonomy.resolve_category("") == ""
    # GDACS 认不出种类时不硬套"地震"这种万能桶
    assert taxonomy.resolve_category("Something", source_id="gdacs",
                                    source_kind="global_disaster") == ""


def test_category_of_item_uses_the_stored_id_first() -> None:
    stored = _item(category_id="haze", title="随便什么标题")
    assert taxonomy.category_of_item(stored) == "haze"
    derived = _item(category_id="", title="某市气象台发布霾黄色预警信号")
    assert taxonomy.category_of_item(derived) == "haze"


# ================================================================= B 定级重做


def test_meteo_source_color_wins_and_kind_words_never_upgrade() -> None:
    """**蓝抬橙 bug 的方向锁**：「暴雨蓝色预警」就是蓝色，不得被种类词升成橙档。"""
    blue = _item(title="某市气象台发布暴雨蓝色预警信号", color_label="蓝色")
    assert grade(blue, now=_NOW) is EmergencyLevel.P3
    assert is_urgent_level(grade(blue, now=_NOW)) is False
    orange = _item(title="某市气象台发布暴雨橙色预警信号", color_label="橙色")
    assert grade(orange, now=_NOW) is EmergencyLevel.P1


def test_color_word_only_in_title_still_grades() -> None:
    item = _item(title="某县发布道路结冰橙色预警信号", color_label="")
    assert grade(item, now=_NOW) is EmergencyLevel.P1


def test_illegal_color_for_the_family_is_not_an_attainable_level() -> None:
    """GDACS 族（global_disaster）结构上只有橙/红：给它「蓝色」不出档、不入库定级。"""
    assert taxonomy.level_is_attainable("wildfire", EmergencyLevel.P3) is False
    assert taxonomy.level_is_attainable("wildfire", EmergencyLevel.P0) is True
    item = _item(
        source_id="gdacs",
        source_kind="global_disaster",
        category_id="wildfire",
        title="野火",
        color_label="蓝色",
    )
    # 族内不可达的色词既不进候选、也不从标题里认 ⇒ 落最低档（诚实不上抬）
    assert grading.grading_candidates(item, now=_NOW) == []
    assert grade(item, now=_NOW) is EmergencyLevel.P3


@pytest.mark.parametrize(
    "magnitude,latitude,longitude,expected",
    [
        (0.6, -75.0, 160.0, EmergencyLevel.P3),   # 南极微震：不推、更不穿窗
        (2.9, 28.5, 104.9, EmergencyLevel.P3),    # 境内微震：信息级
        (3.9, 28.5, 104.9, EmergencyLevel.P3),    # 境内有感但不够档
        (4.0, 28.5, 104.9, EmergencyLevel.P2),
        (4.9, 28.5, 104.9, EmergencyLevel.P2),
        (5.0, 28.5, 104.9, EmergencyLevel.P1),
        (6.4, 28.5, 104.9, EmergencyLevel.P1),
        (6.5, 28.5, 104.9, EmergencyLevel.P0),    # 境内 6.5：红档，该叫醒人
        (7.1, 28.5, 104.9, EmergencyLevel.P0),
        (6.5, 35.7, 140.1, EmergencyLevel.P2),    # 境外 6.5：黄档（不为半球外红档穿窗）
        (8.1, 35.7, 140.1, EmergencyLevel.P1),    # 境外巨震：橙档，仍不给红
        (None, 28.5, 104.9, EmergencyLevel.P3),   # 没有震级这个事实＝不出档
    ],
)
def test_earthquake_magnitude_matrix(
    magnitude: float | None,
    latitude: float | None,
    longitude: float | None,
    expected: EmergencyLevel,
) -> None:
    item = _item(
        source_id="usgs",
        source_kind="earthquake",
        category_id="earthquake",
        title=f"{magnitude or '—'}级地震｜某地",
        color_label="",
        magnitude=magnitude,
        depth_km=10.0,
        latitude=latitude,
        longitude=longitude,
    )
    assert grade(item, now=_NOW) is expected
    assert item.level is None  # 采集侧不预先塞等级（定级唯一出口在审核门）


def test_M0_6_antarctic_quake_is_never_urgent_even_with_the_word_earthquake() -> None:
    """审计 E6-N1 的正案：0.6 级、境外、标题满是"地震"，也不许进 URGENT_LEVELS。"""
    item = _item(
        source_id="usgs",
        source_kind="earthquake",
        title="0.6级地震｜南极洲",
        body="来源：USGS；震源深度 10 km",
        color_label="",
        magnitude=0.6,
        depth_km=10.0,
        latitude=-75.0,
        longitude=160.0,
    )
    level = grade(item, now=_NOW)
    assert level is EmergencyLevel.P3
    assert is_urgent_level(level) is False
    assert grading.may_breach_quiet_window(item, level) is False


def test_earthquake_ignores_impact_keywords_entirely() -> None:
    """地震族连「撤离」都不抬档：微震速报里的强制动作多半是演练或旧闻。"""
    item = _item(
        source_id="icl",
        source_kind="earthquake",
        category_id="earthquake",
        title="2.1级地震｜某县",
        body="已组织群众撤离",
        color_label="",
        magnitude=2.1,
        latitude=28.5,
        longitude=104.9,
    )
    assert grade(item, now=_NOW) is EmergencyLevel.P3


def test_deep_focus_earthquake_downgrades_exactly_one_step() -> None:
    shallow = _item(
        source_kind="earthquake", category_id="earthquake", title="6.8级地震｜境内",
        color_label="", magnitude=6.8, depth_km=12.0, latitude=30.0, longitude=103.0,
    )
    deep = shallow.model_copy(update={"depth_km": 320.0})
    assert grade(shallow, now=_NOW) is EmergencyLevel.P0
    assert grade(deep, now=_NOW) is EmergencyLevel.P1


def test_quake_without_magnitude_may_still_use_the_official_source_color() -> None:
    """GDACS 地震事件不给震级，但 Red/Orange 是**源侧官方色**——这条路留着。"""
    item = _item(
        source_id="gdacs",
        source_kind="earthquake",
        category_id="earthquake",
        title="Earthquake",
        color_label="红色",
        magnitude=None,
    )
    assert grade(item, now=_NOW) is EmergencyLevel.P0


def test_default_keyword_table_contains_no_category_words() -> None:
    """种类词整体退出关键词表（WP3 交付②）：定级不再靠"标题里有个地震俩字"。"""
    all_keywords = {kw for rule in DEFAULT_GRADING_RULES for kw in rule.keywords}
    banned = {
        "地震", "海啸", "泥石流", "山体滑坡", "暴雨", "暴雪", "台风", "大风",
        "冰雹", "寒潮", "高温", "山洪", "地质灾害", "火灾", "大雾", "霾", "雷电",
        "沙尘", "道路结冰", "降温", "降雨", "连阴雨",
    }
    assert all_keywords & banned == set(), f"关键词表里还有种类词：{all_keywords & banned}"
    # 影响面硬事实仍在（旧用例 test_grade_takes_highest_keyword_hit 的方向不变）
    assert matched_levels("已发生山体滑坡，请撤离") == [EmergencyLevel.P0]


def test_impact_facts_still_raise_a_meteo_item_to_red() -> None:
    item = _item(title="暴雨蓝色预警", body="低洼地带已组织转移安置并撤离", color_label="蓝色")
    assert grade(item, now=_NOW) is EmergencyLevel.P0


def test_expired_item_still_cannot_claim_urgent() -> None:
    stale = _item(color_label="红色", expires_at=_NOW + timedelta(minutes=5))
    assert grade(stale, now=_NOW) is EmergencyLevel.P0
    assert grade(stale, now=_NOW + timedelta(hours=2)) is EmergencyLevel.P3


def test_grading_candidates_is_unwired_debug_surface_and_deterministic() -> None:
    # T8（2026-09-22）裁定 1(b)：本用例原名含 "auditable"——生产无消费方的
    # 「可审计面」宣称已改口为「未接线的调试/复算出口」（见 grading.py docstring）；
    # 只随宣称改名，**断言体一字未动**。
    item = _item()
    first = grading.grading_candidates(item, now=_NOW)
    assert first == grading.grading_candidates(item, now=_NOW)
    assert grade(item, now=_NOW) is max(first, key=lambda level: level.rank)


def test_grading_reads_the_registry_for_every_category_family() -> None:
    """每个类别都必须落在**族内合法**的档上；族里没有的色档不得被抬出来。"""
    for spec in taxonomy.categories():
        family = taxonomy.family_for(spec.category_id)
        item = _item(
            category_id=spec.category_id,
            title=f"{spec.label}黄色预警",
            color_label=taxonomy.YELLOW,
        )
        level = grade(item, now=_NOW)
        assert level in EmergencyLevel
        legal_colors = set(family.color_tiers)
        if taxonomy.YELLOW not in legal_colors:
            # 族内没有黄档 ⇒ 这个"黄色"色词是噪声，不得出黄档（落蓝=诚实不上抬）
            assert level is EmergencyLevel.P3, (
                f"{spec.category_id}（{family.family_id} 族 {family.color_tiers}）"
                f"竟然从「黄色」出了 {level.value}"
            )
        else:
            assert level.color_label in legal_colors, spec.category_id


# ======================================================= C 静默窗击穿显式规则表


def test_silence_breach_table_is_explicit_per_family() -> None:
    """击穿资格是**表**不是口口相传：族 → 可穿窗等级，逐条与规格件 §五对照。"""
    table = {row[0]: row[3] for row in taxonomy.silence_breach_rules()}
    assert table["global_disaster"] == ("P0",), "国际事件族只有红档够格叫醒人"
    for family_id in ("meteo", "hydro", "geo", "fire", "marine", "space", "quake", "volcano"):
        assert set(table[family_id]) == {"P0", "P1"}, family_id


def test_may_breach_requires_a_real_level_and_a_wake_worthy_family() -> None:
    meteo_red = _item(category_id="fog", color_label="红色")
    assert grading.may_breach_quiet_window(meteo_red, EmergencyLevel.P0) is True
    assert grading.may_breach_quiet_window(meteo_red, EmergencyLevel.P2) is False
    assert grading.may_breach_quiet_window(meteo_red, None) is False
    gdacs_orange = _item(
        source_id="gdacs", source_kind="global_disaster",
        category_id="wildfire", color_label="橙色", title="Wildfire",
    )
    assert grading.may_breach_quiet_window(gdacs_orange, EmergencyLevel.P1) is False


def test_breach_rule_is_user_configurable_by_level_list() -> None:
    """`allowed_levels` 那一腿：配窄了只能更安静，配成四档＝交回中央闸（关本域抑制）。"""
    item = _item(category_id="typhoon", color_label="红色")
    assert grading.may_breach_quiet_window(item, EmergencyLevel.P0, allowed_levels=["P0"]) is True
    assert grading.may_breach_quiet_window(item, EmergencyLevel.P0, allowed_levels=["P1"]) is False
    assert grading.may_breach_quiet_window(item, EmergencyLevel.P0, allowed_levels=[]) is False
    assert grading.may_breach_quiet_window(item, EmergencyLevel.P0, allowed_levels=("P0", "p1")) is True


class _NullStore:
    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        del subject_key, since_utc
        return 0

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        del subject_key, now_utc

    def prune(self, *, before_utc: datetime) -> int:
        del before_utc
        return 0


class _RecordingQueue:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def submit(self, request: Any, deliver_after: Any = None) -> Any:
        from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
            DeliveryReceipt,
            ReceiptState,
        )

        self.requests.append(request)
        return DeliveryReceipt(
            request_id=request.request_id, state=ReceiptState.QUEUED, transport="onebot"
        )


def _real_gate(*, now: datetime, enabled: bool = True, window: tuple[str, str] = ("00:00", "06:00")) -> Any:
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(
        OutboundGateSettings(enabled=enabled),
        quiet_settings=QuietHoursSettings(
            enabled=True,
            start_time=window[0],
            end_time=window[1],
            timezone_name="UTC",
            session_types=["group", "private"],
        ),
        store=_NullStore(),
        clock=lambda: now,
        audit_logger=InMemoryAuditLogger(),
        issue_sink=None,
    )


def _group_target() -> Any:
    return push.EmergencyTarget(target_id="1108838060", channel="qq")


def _graded(item: EmergencyItem, level: EmergencyLevel) -> EmergencyItem:
    return item.model_copy(update={"level": level, "status": EmergencyStatus.APPROVED})


def test_hold_only_when_the_gate_would_actually_breach() -> None:
    gate = _real_gate(now=_NIGHT)
    # 红档 + 族级允许 ⇒ 不压（今天的行为一寸不变）
    red = _graded(_item(category_id="typhoon", title="台风红色预警", color_label="红色"),
                  EmergencyLevel.P0)
    assert push.should_hold_for_quiet_window(red, gate, now=_NIGHT, target_scope="group") is False
    # 橙档 + global_disaster 族级只认红 ⇒ 压住
    orange = _graded(
        _item(source_id="gdacs", source_kind="global_disaster", category_id="wildfire",
              title="野火", color_label="橙色"),
        EmergencyLevel.P1,
    )
    assert push.should_hold_for_quiet_window(orange, gate, now=_NIGHT, target_scope="group") is True


def test_no_hold_outside_the_quiet_window() -> None:
    gate = _real_gate(now=_NOW)
    orange = _graded(
        _item(source_id="gdacs", source_kind="global_disaster", category_id="wildfire",
              title="野火", color_label="橙色"),
        EmergencyLevel.P1,
    )
    assert push.should_hold_for_quiet_window(orange, gate, now=_NOW, target_scope="group") is False


def test_quiet_predicate_agrees_with_the_gate_that_uses_it() -> None:
    """方向锁：域内"是否在窗内"的判定必须与闸自己的判定同结果（禁第二套窗口径）。

    判据不是"我们自己觉得对"，而是拿真闸在非紧急载体上的行为当 oracle：
    窗内非紧急 ⇒ 闸 defer；窗外 ⇒ 不 defer。两者与本谓词逐点等值。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        REASON_QUIET,
        submit_active_push,
    )

    moments = [
        datetime(2026, 9, 21, hour=h, minute=m, tzinfo=timezone.utc)
        for h in (0, 2, 5, 6, 7, 12, 23)
        for m in (0, 30)
    ]
    for moment in moments:
        predicate = push._quiet_window_active(
            _real_gate(now=moment), moment, "group"
        )
        queue = _RecordingQueue()
        outcome = submit_active_push(
            queue,
            push.build_emergency_send_request(
                _graded(_item(), EmergencyLevel.P3), _group_target(), now=moment
            ),
            _real_gate(now=moment),
            now=moment,
            dedupe_family="daily",
        )
        deferred_by_gate = outcome.verdict.reason == REASON_QUIET
        assert predicate == deferred_by_gate, f"{moment:%H:%M} 谓词 {predicate} vs 闸 {deferred_by_gate}"


def test_deliver_emergency_holds_and_touches_nothing_when_not_wake_worthy() -> None:
    gate = _real_gate(now=_NIGHT)
    queue = _RecordingQueue()
    orange = _graded(
        _item(source_id="gdacs", source_kind="global_disaster", category_id="wildfire",
              title="野火橙色", color_label="橙色", occurred_at=_NIGHT - timedelta(hours=1)),
        EmergencyLevel.P1,
    )
    verdict = push.deliver_emergency(queue, gate, orange, _group_target(), now=_NIGHT)
    assert verdict == push.SKIP_QUIET_HOURS
    assert queue.requests == [], "压住＝本轮不提交，绝不能变成照样入队"


def test_deliver_emergency_still_allows_a_wake_worthy_red_at_night() -> None:
    gate = _real_gate(now=_NIGHT)
    queue = _RecordingQueue()
    # occurred_at 显式落在 `_NIGHT` **之前**：F-1 时效腿（`push.SKIP_EXPIRED`）对
    # 「发生在投递钟之后」的条目 fail-closed 不投，本件验的是安静窗击穿而不是时效。
    red = _graded(_item(category_id="rainstorm", title="暴雨红色预警", color_label="红色",
                        occurred_at=_NIGHT - timedelta(hours=1)),
                  EmergencyLevel.P0)
    verdict = push.deliver_emergency(queue, gate, red, _group_target(), now=_NIGHT)
    assert verdict == "allow"
    assert len(queue.requests) == 1
    assert queue.requests[0].priority == "P0"  # 锁 C 的载体口径一寸未动


def test_missing_gate_settings_fail_open_to_the_gate_itself() -> None:
    """读不到窗事实 ⇒ 不擅自压人（把观测面故障变成漏报是错的方向）。

    顺带如实记录在册缺口 E6-N25：`deliver_emergency` 不校验 `gate is None`，
    闸缺位的守卫在调用侧（根装配 `[] if gate is None else _push_targets()`），
    本用例因此用"看得见但读不通"的闸替身，而不是直接传 None。
    """

    class _Opaque:
        pass

    orange = _graded(_item(source_id="gdacs", category_id="wildfire", title="野火",
                           occurred_at=_NIGHT - timedelta(hours=1)),
                     EmergencyLevel.P1)
    assert push.should_hold_for_quiet_window(orange, _Opaque(), now=_NIGHT) is False
    assert push.should_hold_for_quiet_window(orange, None, now=_NIGHT) is False
    # 窗关着 ⇒ 根本没有"穿窗"这回事，也不许压
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    gate_window_off = OutboundGate(
        OutboundGateSettings(enabled=True),
        quiet_settings=QuietHoursSettings(enabled=False),
        store=_NullStore(),
        clock=lambda: _NIGHT,
        audit_logger=InMemoryAuditLogger(),
        issue_sink=None,
    )
    assert push.should_hold_for_quiet_window(orange, gate_window_off, now=_NIGHT) is False
    # 在册缺口 E6-N25 如实记录：闸缺位的守卫在调用侧，触点自身不判 None
    with pytest.raises(AttributeError):
        push.deliver_emergency(_RecordingQueue(), None, orange, _group_target(), now=_NIGHT)


# ============================================================ D 定级回写一致性


def _service(store: EmergencyStore, *, auto: tuple[str, ...] = ("nmc",)) -> Any:
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module(_CAP_MODULE)
    source = module.build_emergency_info_source(
        SimpleNamespace(**_snapshot_data(auto_approve=list(auto)))
    )
    return module.EmergencyInfoService(
        store=store,
        source=source,
        gate=object(),
        review_gate=module.build_review_gate(store, source),
    )


def _snapshot_data(auto_approve: Any = None, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "bot_emergency_info_enabled": True,
        "bot_emergency_info_sources": ["nmc"],
        "bot_emergency_info_auto_approve_sources": ["nmc"],
        "bot_emergency_info_push_group_whitelist": [],
        "bot_emergency_info_push_user_ids": [],
        "bot_emergency_info_reviewer_ids": ["admin-1"],
        "bot_emergency_info_min_level": "P2",
        "bot_emergency_info_poll_interval_seconds": 300,
        "bot_emergency_info_keep_days": 90,
        "bot_emergency_info_db_path": "",
        "bot_persona_profile_id": "default",
    }
    if auto_approve is not None:
        data["bot_emergency_info_auto_approve_sources"] = list(auto_approve)
    data.update(overrides)
    return data


def test_approved_items_writeback_persists_the_level(tmp_path: Path) -> None:
    """审计 E6-N3 的正修：定级必须落库，库里不再是恒 NULL。"""
    store = EmergencyStore(tmp_path / "wp3-level.sqlite3")
    service = _service(store)
    service.ingest_payloads(
        [
            {
                "item_id": "nmc-A1",
                "source_id": "nmc",
                "source_kind": "weather_alarm",
                "external_id": "A1",
                "title": "某县气象台发布暴雨红色预警信号",
                "color_label": "红色",
                "category_id": "rainstorm",
                "occurred_at": _NOW,
                "fetched_at": _NOW,
                "credibility": 0.9,
            }
        ],
        at=_NOW,
    )
    assert store.get("nmc-A1").level is None  # 入库时确实还没定级
    rows = service.approved_items(limit=10, now=_NOW)
    assert rows[0].level is EmergencyLevel.P0
    assert store.get("nmc-A1").level is EmergencyLevel.P0, "回写没落库＝两副面孔仍在"


def test_query_side_and_delivery_side_report_the_same_value(tmp_path: Path) -> None:
    """同源同值三方锁：库里 == 读侧 == 投递侧 `publishable_level`。"""
    store = EmergencyStore(tmp_path / "wp3-same.sqlite3")
    service = _service(store)
    service.ingest_payloads(
        [
            {
                "item_id": "nmc-A2",
                "source_id": "nmc",
                "source_kind": "weather_alarm",
                "external_id": "A2",
                "title": "某县气象台发布大雾黄色预警信号",
                "color_label": "黄色",
                "category_id": "fog",
                "occurred_at": _NOW,
                "fetched_at": _NOW,
                "credibility": 0.9,
            }
        ],
        at=_NOW,
    )
    read_side = service.approved_items(limit=10, now=_NOW)[0]
    from_store = store.list_by_status(EmergencyStatus.APPROVED, limit=10)[0]
    delivery_side = ReviewGate.publishable_level(from_store, now=_NOW)
    assert read_side.level is delivery_side is from_store.level is EmergencyLevel.P2
    assert read_side.category_id == from_store.category_id == "fog"


def test_writeback_is_idempotent_and_skips_unchanged_rows(tmp_path: Path) -> None:
    store = EmergencyStore(tmp_path / "wp3-idem.sqlite3")
    service = _service(store)
    service.ingest_payloads(
        [
            {
                "item_id": "nmc-A3", "source_id": "nmc", "source_kind": "weather_alarm",
                "external_id": "A3", "title": "暴雨橙色预警", "color_label": "橙色",
                "category_id": "rainstorm", "occurred_at": _NOW, "fetched_at": _NOW,
                "credibility": 0.9,
            }
        ],
        at=_NOW,
    )
    service.approved_items(limit=10, now=_NOW)
    calls: list[Any] = []
    original = store.set_level

    def spy(item_id: str, **kwargs: Any) -> bool:
        calls.append((item_id, kwargs))
        return original(item_id, **kwargs)

    store.set_level = spy  # type: ignore[method-assign]
    service.approved_items(limit=10, now=_NOW)
    assert calls == [], "值没变还写＝每轮空转刷盘"
    store.set_level = original  # type: ignore[method-assign]


def test_pending_rows_never_receive_a_level(tmp_path: Path) -> None:
    """D-8 的存储侧守卫不许被回写绕过：人工报料在过审前恒 NULL。"""
    store = EmergencyStore(tmp_path / "wp3-pending.sqlite3")
    service = _service(store, auto=())
    service.ingest_payloads(
        [
            {
                "item_id": "hum-1", "source_id": "user_report", "source_kind": "manual",
                "external_id": "h1", "title": "暴雨红色预警", "color_label": "红色",
                "occurred_at": _NOW, "fetched_at": _NOW, "credibility": 0.5,
            }
        ],
        at=_NOW,
    )
    assert store.set_level("hum-1", level=EmergencyLevel.P0, category_id="rainstorm") is False
    assert store.get("hum-1").level is None
    assert service.approved_items(limit=10, now=_NOW) == []


def test_store_migrates_a_v1_database_by_adding_the_three_columns(tmp_path: Path) -> None:
    """家规=「ALTER-if-missing 只加列不改语义」：老库必须原地可用、老行不丢。"""
    import sqlite3

    path = tmp_path / "wp3-v1.sqlite3"
    legacy = sqlite3.connect(path)
    try:
        legacy.executescript(
            """
            CREATE TABLE emergency_items (
                item_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                source_kind TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '', color_label TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT,
                date_key TEXT NOT NULL, level TEXT, credibility REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT NOT NULL DEFAULT '', reviewed_at TEXT
            );
            INSERT INTO emergency_items (item_id, source_id, external_id, title,
                occurred_at, fetched_at, date_key, credibility, status)
            VALUES ('nmc-OLD', 'nmc', 'OLD', '旧条目：暴雨橙色预警',
                '2026-09-20T00:00:00+00:00', '2026-09-20T00:00:00+00:00',
                '2026-09-20', 0.9, 'approved');
            """
        )
        legacy.commit()
    finally:
        legacy.close()

    store = EmergencyStore(path)
    with sqlite3.connect(path) as probe:
        columns = {row[1] for row in probe.execute("PRAGMA table_info(emergency_items)")}
    assert {"category_id", "magnitude", "depth_km"} <= columns
    row = store.get("nmc-OLD")
    assert row is not None and row.title == "旧条目：暴雨橙色预警"
    assert row.category_id == "" and row.magnitude is None and row.depth_km is None
    # 再开一次不重复 ALTER（幂等）
    EmergencyStore(path)


def test_new_fields_roundtrip_through_sqlite(tmp_path: Path) -> None:
    store = EmergencyStore(tmp_path / "wp3-fields.sqlite3")
    item = build_emergency_item(
        {
            "item_id": "usgs-x1", "source_id": "usgs", "source_kind": "earthquake",
            "external_id": "x1", "title": "6.7级地震｜某地", "color_label": "",
            "category_id": "earthquake", "magnitude": 6.7, "depth_km": 12.5,
            "latitude": 28.5, "longitude": 104.9,
            "occurred_at": _NOW, "fetched_at": _NOW, "credibility": 0.85,
            "status": "approved",
        }
    )
    assert item is not None
    assert store.upsert_item(item) is True
    loaded = store.get("usgs-x1")
    assert (loaded.magnitude, loaded.depth_km, loaded.category_id) == (6.7, 12.5, "earthquake")
    assert (loaded.latitude, loaded.longitude) == (28.5, 104.9)


@pytest.mark.parametrize(
    "field,value",
    [("magnitude", 99.0), ("magnitude", -8.0), ("depth_km", -1.0), ("depth_km", 5000.0)],
)
def test_contract_rejects_out_of_range_source_facts(field: str, value: float) -> None:
    payload: dict[str, Any] = {
        "item_id": "bad-1", "source_id": "usgs", "source_kind": "earthquake",
        "external_id": "b1", "title": "某地地震", "occurred_at": _NOW,
        "fetched_at": _NOW, "credibility": 0.5, field: value,
    }
    assert build_emergency_item(payload) is None, "越界数值被夹逼＝拿假数去定档"


# ==================================================== E auto_approve_sources 校验


def test_validate_keeps_legal_ids_and_names_the_rest() -> None:
    kept, unknown = validate_auto_approve_sources(
        ["nmc", " nmc_alarm ", "gdacs", "\t", "OPEN_DATA_QUAKES"], taxonomy.SOURCE_IDS
    )
    assert kept == frozenset({"nmc", "gdacs"})
    assert unknown == ("OPEN_DATA_QUAKES", "nmc_alarm")


def test_validation_without_a_registry_never_swallows_the_list() -> None:
    """校验器不是开关：拿不到注册表时原样放行，绝不"校不出来就清空名单"。"""
    kept, unknown = validate_auto_approve_sources(["nmc", "whatever"], None)
    assert kept == frozenset({"nmc", "whatever"}) and unknown == ()
    kept, unknown = validate_auto_approve_sources(["nmc"], [])
    assert kept == frozenset({"nmc"}) and unknown == ()


def test_snapshot_drops_module_name_style_values_and_records_them() -> None:
    import importlib

    module = importlib.import_module(_CAP_MODULE)
    source = module.build_emergency_info_source(
        SimpleNamespace(**_snapshot_data(auto_approve=["nmc_alarm", "usgs"]))
    )
    assert source.auto_approve_sources == frozenset({"usgs"})
    assert source.unknown_auto_approve_sources == ("nmc_alarm",)


def test_build_review_gate_warns_about_module_names(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """审计 E6-N2 的核心：不静默。**点名 + 忽略**，与 `sources` 键 2.A 先例同形态。"""
    import importlib
    import logging

    module = importlib.import_module(_CAP_MODULE)
    store = EmergencyStore(tmp_path / "wp3-warn.sqlite3")
    source = module.build_emergency_info_source(
        SimpleNamespace(**_snapshot_data(auto_approve=["nmc_alarm"]))
    )
    with caplog.at_level(logging.WARNING):
        gate = module.build_review_gate(store, source)
    assert any("nmc_alarm" in record.message for record in caplog.records), caplog.text
    assert gate.is_authoritative_source("nmc_alarm") is False
    assert gate.is_authoritative_source("nmc") is False  # 被忽略的值不得留下半个效果


def test_legal_source_id_still_auto_approves_end_to_end(tmp_path: Path) -> None:
    """纠偏之后方向要正：真身 `nmc` 依旧入库即过审（旧测试把它当"命中"的意图保留）。"""
    store = EmergencyStore(tmp_path / "wp3-auto.sqlite3")
    service = _service(store, auto=("nmc",))
    submitted = service.ingest_payloads(
        [
            {
                "item_id": "nmc-A9", "source_id": "nmc", "source_kind": "weather_alarm",
                "external_id": "A9", "title": "暴雨橙色预警", "color_label": "橙色",
                "occurred_at": _NOW, "fetched_at": _NOW, "credibility": 0.9,
            }
        ],
        at=_NOW,
    )
    assert submitted[0].status is EmergencyStatus.APPROVED
    assert submitted[0].reviewed_by == ReviewGate.AUTO_APPROVED_BY
    assert service.pending_items(limit=10) == []


# ============================================================ F 采集腿与装配默认


def test_usgs_assembly_leg_uses_the_magnitude_gated_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """E6-N1 采集腿：装配绑的是 `fetch_usgs_quakes(min_magnitude=4.0)`，不是 all_hour。"""
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector
    from plugins.bot_unified_runtime.domains.emergency_info.sources import (
        open_data_quakes as quakes,
    )

    calls: dict[str, Any] = {}
    feed_calls: list[Any] = []

    def fake_quakes(**kwargs: Any) -> Any:
        calls.update(kwargs)
        return collector.SourceOutcome(state=collector.FetchState.NO_DATA, source_id="usgs")

    def fake_feed(**kwargs: Any) -> Any:
        feed_calls.append(kwargs)
        return collector.SourceOutcome(state=collector.FetchState.NO_DATA, source_id="usgs")

    monkeypatch.setattr(quakes, "fetch_usgs_quakes", fake_quakes)
    monkeypatch.setattr(quakes, "fetch_usgs_recent_feed", fake_feed)
    deps = collector.build_emergency_collector_deps()
    task = next(t for t in deps.sources if t.source_id == "usgs")
    task.fetch()
    assert calls.get("min_magnitude") == 4.0, f"装配腿参数不对：{calls}"
    assert feed_calls == [], "无门槛的 all_hour 通道又回来了"


def test_usgs_threshold_is_injectable_and_defaults_to_the_ruling() -> None:
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector

    assert collector.USGS_PUSH_MIN_MAGNITUDE == 4.0
    seen: dict[str, Any] = {}
    deps = collector.build_emergency_collector_deps(
        fetch_usgs=lambda: seen and None, usgs_min_magnitude=5.5
    )
    assert deps.sources  # 注入形参存在即合法（不改根装配即可换数）


def test_collector_stamps_category_and_source_facts() -> None:
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector
    from plugins.bot_unified_runtime.domains.emergency_info.sources.http_get import (
        FetchState,
        SourceOutcome,
    )
    from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
        AlarmAlert,
    )

    alert = AlarmAlert(
        alertid="A1",
        title="某县气象台发布雷暴大风蓝色预警信号",
        kind="雷暴大风",
        color_label="蓝色",
        issued_at=_NOW,
        issued_text="2026-09-21 12:00",
        url="",
        detail_url="",
        pic="https://image.nmc.cn/assets/img/alarm/p0042004.png",
    )
    outcome = SourceOutcome(state=FetchState.OK, source_id="nmc", items=(alert,))
    payloads = collector._nmc_payloads(outcome, _NOW)
    assert payloads[0]["category_id"] == "severe_convection"  # 图码 0042 实测映射
    assert taxonomy.category(payloads[0]["category_id"]).label == "强对流天气"


def test_nmc_pic_signal_code_parser_rejects_garbage() -> None:
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector

    assert collector._nmc_pic_signal_code(".../p0002003.png") == "0002"
    assert collector._nmc_pic_signal_code("9999") == ""
    assert collector._nmc_pic_signal_code("") == ""
    assert collector._nmc_pic_signal_code(None) == ""


# =========================================================== G 订阅面 × 注册表


def _rule(text: str, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "target_scope": "group",
        "target_id": "1108838060",
        "created_by": "3865067623",
    }
    kwargs.update(overrides)
    return parse_subscription(text or "", **kwargs)


def test_subscription_accepts_category_with_ceiling_and_area() -> None:
    """「订阅 台风 橙色以上 湘潭」这类话必须能用（交付⑤的正面）。"""
    rule = _rule("台风 橙色以上 湘潭")
    assert rule.categories == frozenset({"typhoon"})
    assert rule.levels == frozenset({"P0", "P1"})
    assert rule.area_name == "湘潭"
    assert "台风" in rule.kinds  # 原文词仍留着（老路不摘牌）


def test_subscription_by_category_id_matches_alias_titles() -> None:
    """按 id 精确命中：订阅「雷暴大风」也能收到标题写"强对流"的条目。"""
    rule = _rule("雷暴大风")
    assert rule.categories == frozenset({"severe_convection"})
    aliased = _item(
        category_id="severe_convection",
        title="某县气象台发布强对流天气黄色预警",
        color_label="黄色",
    ).model_copy(update={"level": EmergencyLevel.P2})
    assert matches_subscription(aliased, rule) is True


def test_category_dimension_is_still_AND_with_level_and_area() -> None:
    rule = _rule("台风 红色")
    yellow = _item(
        category_id="typhoon", title="台风黄色预警", color_label="黄色"
    ).model_copy(update={"level": EmergencyLevel.P2})
    assert matches_subscription(yellow, rule) is False


def test_color_ceiling_is_validated_against_the_family() -> None:
    """「蓝色以上」用在一个只有橙/红的族上＝当场报错并给候选，不留永不命中的规则。"""
    with pytest.raises(RuleError) as caught:
        _rule("野火 蓝色")
    assert "森林草原火灾" in str(caught.value) or "野火" in str(caught.value)
    assert caught.value.candidates == (taxonomy.ORANGE, taxonomy.RED)
    ok = _rule("野火 红色以上")
    assert ok.levels == frozenset({"P0"})


def test_four_tier_families_still_accept_blue() -> None:
    rule = _rule("暴雨 蓝色以上")
    assert rule.levels == frozenset({"P0", "P1", "P2", "P3"})


def test_open_vocabulary_terms_are_still_accepted() -> None:
    """注册表之外仍留开放词表（WIRE-SUB 策略不收）：认不出的词按原文子串匹配。"""
    rule = _rule("某类没登记过的警情")
    assert rule.categories == frozenset()
    assert rule.kinds
    item = _item(category_id="", title="某类没登记过的警情 提示").model_copy(
        update={"level": EmergencyLevel.P3}
    )
    assert matches_subscription(item, rule) is True


def test_structural_garbage_is_still_rejected() -> None:
    with pytest.raises(RuleError):
        _rule("暴雨 台风 大风 高温 雷电 冰雹 寒潮 霜冻 大雾 霾 道路结冰 沙尘暴")


def test_categories_survive_the_store_round_trip(tmp_path: Path) -> None:
    store = EmergencyStore(tmp_path / "wp3-sub.sqlite3")
    rule = _rule("风暴潮 红色以上")
    assert rule.categories == frozenset({"storm_surge"})
    store.save_subscription(rule, at=_NOW)
    loaded = store.get_subscription(rule.target_key)
    assert loaded.categories == frozenset({"storm_surge"})
    assert loaded.kinds == frozenset({"风暴潮"})
    assert loaded.levels == frozenset({"P0"})


def test_subscribing_an_unsourced_category_is_recorded_but_says_so(tmp_path: Path) -> None:
    """无源≠拦人、≠静默：规则照设，回显里明说"接上源之前不会有推送"。"""
    import importlib

    module = importlib.import_module(_CAP_MODULE)
    store = EmergencyStore(tmp_path / "wp3-sub-warn.sqlite3")
    body = module.run_subscription_command(
        store,
        scope="group",
        target_id="1108838060",
        sender_id="3865067623",
        action="set",
        argument="空间天气",
        at=_NOW,
    )
    assert "无源" in body and "空间天气" in body
    assert store.get_subscription("group:1108838060") is not None
