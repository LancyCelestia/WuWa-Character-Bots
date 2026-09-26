"""T8 残项②：关键词腿族的约束锁（2026-09-23，实施席 TX115）。

背景（`.superpowers/sdd/2026-09-22-taxonomy/BRIEFS-BATCH50.md`《TX115》、
`service/grading.py` 头注 §设计要点 2）：旧词表把**种类词**「地震」写进 P0 关键词档，
与颜色取最高档 ⇒ 定级矩阵 12 格全判 P0、把 M0.6 南极微震抬成红，是穿窗误报根因
（审计 E6-N1）。WP3-IMPL 已把种类词整体退出缺省关键词表，但**残项是**：没有一把机器锁
防止种类词再次被塞回「定级词表」（等级词族 / 色档表）。既有两把锁都不足以封死这类回归：

- `test_emergency_info_taxonomy.py::test_default_keyword_table_contains_no_category_words`
  比对的是**手写 ~22 词黑名单**，凡新增类别或别名（如 wildfire 的别名「野火」、
  「空间天气」「渍涝」）被塞进关键词表，它一概放过；
- `test_emergency_info_taxonomy.py::test_every_family_declares_legal_color_tiers_within_the_authorised_words`
  只锁「色档 ⊆ 四色」，不锁「色档词与种类词两套词汇互斥」。

本件补两条约束锁 + 两条注毒自证（全离线：零网络、零写库、零生产数据；
**既有测试件一寸未动、alert_taxonomy.py / grading.py 只读**）：

1. **锁① 色档种类表 ⊥ 种类词表**：每个族的 `color_tiers` / `tier_order`
   只能取 `LEVEL_COLOR_LABEL` 那四枚色词（⊆ 权威种类表），
   且这些色档词本身绝不得同时是注册表里的预警种类词（label ∪ alias）——
   封的是"把种类词当色档 / 把色档词当种类"这一类词汇串味（地震→P0 的根因家族）。
   注毒①：往色档夹具塞一枚真种类词「地震」⇒ 谓词必点违例。
2. **锁② 缺省关键词表不含种类词（现算版）**：从**权威注册表现算**种类词全集
   （全部类别的 label ∪ aliases，禁手抄黑名单），断言缺省关键词表逐词 ⊥ 该全集。
   注毒②：往关键词夹具塞一枚**不在旧手抄黑名单内**的真种类词「野火」⇒
   现算谓词当场点出，实证本锁严格强于手抄表那把。
"""

from __future__ import annotations

from collections.abc import Iterable

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyLevel,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    DEFAULT_GRADING_RULES,
)

# ------------------------------------------------------------- 真身派生的两套词汇

#: 权威「色档种类表」：D-3 单一枚举的四枚色词（红/橙/黄/蓝），禁各处手抄色列表。
_CANONICAL_COLOR_WORDS: frozenset[str] = frozenset(
    level.color_label for level in EmergencyLevel
)


def _category_word_vocabulary() -> frozenset[str]:
    """现算「种类词全集」＝注册表全部类别的 label ∪ aliases（唯一真身，禁手抄）。

    这是本件两条锁的执法依据：一旦新增类别或别名，词表自动跟随，
    无需像 test_emergency_info_taxonomy 那份手抄黑名单那样逐字补录。
    """
    words: set[str] = set()
    for spec in taxonomy.categories():
        if spec.label:
            words.add(spec.label)
        words.update(alias for alias in spec.aliases if alias)
    return frozenset(words)


def _default_keyword_vocabulary() -> frozenset[str]:
    """现算「缺省关键词表」全部关键词（跨等级扁平化）。"""
    return frozenset(
        keyword for rule in DEFAULT_GRADING_RULES for keyword in rule.keywords if keyword
    )


# ------------------------------------------------------------- 谓词（注毒自证复用）


def _color_tier_violations(tiers: Iterable[str]) -> set[str]:
    """给定色档词序列，返回「越出权威四色种类表」或「命中种类词表」的违例词集合。"""
    vocab = _category_word_vocabulary()
    bad: set[str] = set()
    for tier in tiers:
        if tier not in _CANONICAL_COLOR_WORDS:
            bad.add(tier)
        if tier in vocab:
            bad.add(tier)
    return bad


def _keyword_category_violations(
    keywords: Iterable[str], vocab: frozenset[str] | None = None
) -> set[str]:
    """给定关键词集合，返回其中命中「种类词全集」的词（缺省现算词表）。"""
    table = _category_word_vocabulary() if vocab is None else vocab
    return {keyword for keyword in keywords if keyword in table}


# ================================================== 锁① 色档种类表 ⊥ 种类词表


def test_every_family_color_tiers_are_authorised_colors_clear_of_category_words() -> None:
    """真身不变式：全族合法色档 ⊆ 权威四色，且色档词与种类词表两套词汇互斥（陈列序同检）。"""
    vocab = _category_word_vocabulary()
    assert vocab, "种类词全集现算为空 ⇒ 谓词空跑，本锁失去意义"
    checked_any = False
    for family in taxonomy.families():
        for field_name, tiers in (
            ("color_tiers", family.color_tiers),
            ("tier_order", family.tier_order),
        ):
            checked_any = True
            tier_set = set(tiers)
            assert tiers, f"{family.family_id}.{field_name} 不得为空"
            assert tier_set <= _CANONICAL_COLOR_WORDS, (
                f"{family.family_id}.{field_name} 越出权威四色种类表："
                f"{tier_set - _CANONICAL_COLOR_WORDS}"
            )
            bleed = tier_set & vocab
            assert not bleed, (
                f"色档词与种类词表串味：{family.family_id}.{field_name} ∩ 种类词 = {bleed}"
            )
    assert checked_any, "注册表里没有任何族 ⇒ 本锁成了空跑"


# ================================================== 锁② 缺省关键词表不含种类词（现算版）


def test_default_keyword_table_contains_no_category_words_derived_from_registry() -> None:
    """真身不变式：缺省关键词表逐词 ⊥ 现算种类词全集（严格强于手抄黑名单）。"""
    keywords = _default_keyword_vocabulary()
    assert keywords, "缺省关键词表为空 ⇒ 本锁成了空跑"
    bleed = keywords & _category_word_vocabulary()
    assert not bleed, f"关键词表里还藏着种类词：{bleed}"


# ================================================== 注毒自证 ×2（塞种类词必红）


def test_poison_category_word_in_color_tier_fixture_is_caught() -> None:
    """注毒①：把真种类词「地震」当色档塞进夹具 ⇒ 谓词必点违例（锁有牙，非空跑）。"""
    quake = taxonomy.category("earthquake")
    assert quake is not None
    assert quake.label == "地震" and "地震" in _category_word_vocabulary()

    poisoned = (taxonomy.RED, "地震")
    assert "地震" in _color_tier_violations(poisoned)
    # 反向对照：纯合法色档夹具在同谓词下零违例（收紧不误杀正常腿）。
    assert _color_tier_violations(taxonomy.FOUR_TIER_ASC) == set()


def test_poison_category_word_outside_legacy_list_in_keyword_fixture_is_caught() -> None:
    """注毒②：塞一枚**不在旧手抄黑名单内**的真种类词 ⇒ 现算谓词当场点出。

    「野火」是 wildfire 的注册表别名：现算词表收得到，而
    test_emergency_info_taxonomy 那份手抄 ~22 词黑名单里没有它——
    这正是本锁要补的洞，故用它做注毒样本以实证「严格强于手抄」。
    """
    vocab = _category_word_vocabulary()
    assert "野火" in vocab, "野火 应是 wildfire 别名，现算词表却收不到 ⇒ 派生逻辑坏"

    # 兄弟锁手抄黑名单的代表样本（仅作对照，不是本件的执法依据）。
    legacy_banned = {
        "地震", "海啸", "泥石流", "山体滑坡", "暴雨", "暴雪", "台风", "大风",
        "冰雹", "寒潮", "高温", "山洪", "地质灾害", "火灾", "大雾", "霾", "雷电",
        "沙尘", "道路结冰", "降温", "降雨", "连阴雨",
    }
    assert "野火" not in legacy_banned, "对照失效：野火 竟在旧手抄表内"

    assert _keyword_category_violations(("爆炸", "野火"), vocab) == {"野火"}
    # 反向对照：真实缺省关键词表在同谓词下零违例。
    assert _keyword_category_violations(_default_keyword_vocabulary(), vocab) == set()
