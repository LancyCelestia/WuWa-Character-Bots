"""S-T-ACGFUSE 起、S-ACG-TIER 转正：ACG 种类闸门（`detect_acg_intent`）的病灶账。

这份文件把 2026-09-26 现算到的闸门实况钉成可复跑的账：

1. 二游问句仍判 game/anime/manga/vtuber/meme（用户第 3 项要的"库里已有的内容"
   就是靠这道门才够得着竖源）；
2. 一般日系 IP 与圈内简称当时判不出来（初音未来；「崩铁」这一枚**至今仍不在表**，
   见 ``test_missing_gacha_shorthand_is_only_carried_by_a_peripheral_term``）；
3. 五枚高频泛用词（日常/毕业/切片 等）当时把非 ACG 问句判成 ACG——现已按 weak
   档锁死，另 16 枚同型误开（高达/充电/干杯/腰斩/皮套…）一并见
   ``tests/test_acg_intent_tiers.py``。

误判的代价不对称：判成 ACG ⇒ ①对 bgm.tv/萌百/B站 发三次与本题无关的外呼、
②若通用检索本轮不该开，则一整块二次元条目会被塞进【联网检索】、
③`source_authority.authority_tier(acg_topic=True)` 会把百科域从 tier 3 抬到 1，
于是「高血压病人日常吃什么药」这种题的排序也会偏向萌百/百度百科。

**状态更新（2026-09-26 S-ACG-TIER）**：本件原先"只登记不动词表"——词表真身
不在原席可写面。那一面现已改造完毕：``search_intent.ACG_DOMAIN_TERMS`` 分
strong/medium/weak 三档，弱档通用词不得单独成判，反证词改为与词表共存裁决。
于是上面第 ② ③ 两块从 xfail 摘牌转正为硬锁（原判据原文保留在摘牌注释里），
本文件因此从"现算探针"升为**病灶回归锁**：一旦有人把某枚弱词提档、
或把反证词改回"零命中才看"，这里立刻红。
分档表自身的分区/派生/隔离判据在 ``tests/test_acg_intent_tiers.py``。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.core.search import source_authority
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_STRONG,
    ACG_TIER_WEAK,
    acg_search_allowed,
    detect_acg_intent,
    extract_acg_query,
)


def _terms_of_tier(tier: str) -> frozenset[str]:
    """从真身词表派生「某一档的全部词」——测试不自带名单，只投影。"""
    return frozenset(
        term for tiers in ACG_DOMAIN_TERMS.values() for term in tiers[tier]
    )

# ---------------------------------------------------------------------------
# ①必须判是的探针（10 条）：今天全绿
# ---------------------------------------------------------------------------

ACG_POSITIVE: tuple[tuple[str, str], ...] = (
    ("鸣潮 3.0 版本更新了什么内容", "game"),
    ("绝区零新角色什么时候实装", "game"),
    ("原神月神卡池复刻吗", "game"),
    ("星穹铁道剧情里流萤是谁", "game"),
    ("崩铁最新卡池有谁", "game"),  # 靠「卡池」命中，条目简称本身不在词表
    ("葬送的芙莉莲动画第三季出了吗", "anime"),
    ("咒术回战漫画连载到哪了", "manga"),
    ("这个虚拟主播的中之人是谁", "vtuber"),
    ("B站百大UP主名单公布了吗", "bilibili"),
    ("硬控是什么梗", "meme"),
)


@pytest.mark.parametrize("question,tag", ACG_POSITIVE)
def test_acg_questions_still_open_the_gate(question: str, tag: str) -> None:
    intent = detect_acg_intent(question)
    assert intent.is_acg, f"二游/ACG 问句被闸门关掉了：{question}"
    assert tag in intent.tags, f"{question} 命中域不含 {tag}：{intent.tags}"


def test_missing_gacha_shorthand_is_only_carried_by_a_peripheral_term() -> None:
    """「崩铁」这两个字本身**不是**证据——去掉「卡池」这句就判不出来。

    这条锁的是现状而不是愿望：它证明简称类条目名在词表里是缺口（见 §②），
    一旦有人把「崩铁」补进词表，这条会转成 xpass 提示来收掉它。
    """
    assert detect_acg_intent("崩铁最新卡池有谁").is_acg is True
    assert detect_acg_intent("崩铁值得抽吗").is_acg is False, (
        "词表已补上简称？那就把这条摘成'仅靠条目名即可命中'的硬锁"
    )


# ---------------------------------------------------------------------------
# ②判不出来的主流 IP（现算缺口，挂账给 SEARCHQ 线）
# ---------------------------------------------------------------------------

ACG_MISSES: tuple[str, ...] = (
    "初音未来的代表作品有哪些",  # VOCALOID/虚拟歌姬：词表里没有这枚条目名
    "辉夜大小姐想让我告白 更新到哪了",  # 高热恋爱喜剧，词表未收（同类还有「我推的孩子」已收）
    "hololive 新成员有哪些",  # 团体名未收，只能靠成员个人词碰运气
    "鹿鸣 新视频出了吗",  # 库洛自家虚拟主播：条目名不在表，「新视频」也不是模式
    "命运石之门好看吗",  # 同一部作品写成「…是谁做的动画」才判得出——靠的是通用词「动画」，不是条目名
)


@pytest.mark.parametrize("question", ACG_MISSES)
def test_mainstream_jp_ip_should_open_the_gate(question: str) -> None:
    # 摘牌记录（2026-09-26 S-ACG-TIER）：此前十枚 xfail 之一。原判据原文——
    #   "2026-09-26 现算缺口：种类闸门只认二游与少数长青条目名，一般日系 IP 判不
    #    出来 ⇒ 库里有的东西到不了竖源。修法在 search_intent.py 的词表。"
    # 转正理由：`ACG_DOMAIN_TERMS` 已把这五枚条目名登记为 **strong 档专名**
    # （初音未来 / 辉夜大小姐 / hololive / 鹿鸣 / 命运石之门，巡音流歌同批补入），
    # 单独命中即判，不再需要「动画」「虚拟偶像」一类周边词抬。
    assert detect_acg_intent(question).is_acg is True


def test_new_strong_entries_are_derived_from_the_real_table() -> None:
    """上面那五枚必须**真在** strong 档里——判据从真身常量派生，不凭注释。

    本仓教训：往夹具里自选符号会把"测代码"写成"测夹具"。这里读的是
    ``ACG_DOMAIN_TERMS`` 本身，词条一旦被挪档或删掉，这条立即红。
    """
    strong = {
        term
        for tiers in ACG_DOMAIN_TERMS.values()
        for term in tiers[ACG_TIER_STRONG]
    }
    for question, entry in zip(
        ACG_MISSES,
        ("初音未来", "辉夜大小姐", "hololive", "鹿鸣", "命运石之门"),
        strict=True,
    ):
        assert entry in strong, f"{entry} 不在 strong 档，{question} 的命中靠不住"


# ---------------------------------------------------------------------------
# ③必须判否的探针：5 条干净否 + 5 条今天误判的（挂账）
# ---------------------------------------------------------------------------

ACG_NEGATIVE: tuple[str, ...] = (
    "美联储这个月加息了吗",
    "英伟达今天股价多少",
    "OpenAI GPT-5 什么时候发布",
    "个人所得税起征点是多少",
    "红烧肉怎么做比较好吃",
)


@pytest.mark.parametrize("question", ACG_NEGATIVE)
def test_non_acg_questions_stay_out(question: str) -> None:
    assert detect_acg_intent(question).is_acg is False


# 误判样本：每条都点名了它是**哪枚词**造成的（现算 matched_terms）。
ACG_FALSE_POSITIVES: tuple[tuple[str, str], ...] = (
    ("我下个月就要毕业了", "毕业"),
    ("牛肉切片怎么炒才嫩", "切片"),
    ("我的工作日常真的很无聊", "日常"),
    ("这款手机续航日常够用吗", "日常"),
    ("高血压病人日常吃什么药", "日常"),
)


@pytest.mark.parametrize("question,culprit", ACG_FALSE_POSITIVES)
def test_daily_life_questions_must_not_open_the_acg_gate(
    question: str, culprit: str
) -> None:
    # 摘牌记录（2026-09-26 S-ACG-TIER）：此前十枚 xfail 之一。原判据原文——
    #   "2026-09-26 现算误开：泛用日常词被当成实体证据，且 `_NON_ACG_HINTS` 那条
    #    拦截只在'一个词表词都没命中'时才生效——命中了泛用词就绕过它。
    #    修法（把词分成'实体证据'与'域提示'两级）在 search_intent.py。"
    # 转正理由：词表已分 strong/medium/weak 三档，这几枚 culprit 全部落在 **weak**
    # 档 ⇒ 单独命中一律不判；反证词也不再要求"零命中"才生效（共存裁决）。
    assert detect_acg_intent(question).is_acg is False


@pytest.mark.parametrize("question,culprit", ACG_FALSE_POSITIVES)
def test_false_positive_root_cause_is_recorded_as_measured(
    question: str, culprit: str
) -> None:
    """上一块记的是"应该怎样"，这一记块记的是"今天到底怎样"：
    误判由哪枚词造成、后果走到哪一步，全部现算进断言，免得日后凭记忆争论。

    2026-09-26 起本条随分档改造**改写为改造后的实况**（旧版断言的是误开现状，
    其原文见上块的摘牌记录）：culprit 仍在词表里、仍被算作一次命中，
    但它不再是**可单独定罪**的证据。
    """
    intent = detect_acg_intent(question)
    assert intent.is_acg is False, (
        "闸门行为又变了：弱通用词重新获得了单独成判的权力，请回查词表档位"
    )
    assert intent.tags == ()
    # 判据本身：这枚词今天归在 weak 档（从真身常量读，不是测试自选的名单）。
    assert culprit in _terms_of_tier(ACG_TIER_WEAK), (
        f"{culprit} 被移出了 weak 档——上面那条「应该不判」的锁需要重审"
    )
    # 后果面（原样保留、方向翻转）：百科域不再被抬进与主流媒体同档。
    # 这条路径今天**不受 BOT_SEARCH_ACG_ENABLED 开关影响**（见席报告判流图腿②），
    # 所以它才是这五句误开在现网的实际代价。
    assert source_authority.authority_tier(
        "baike.baidu.com", acg_topic=intent.is_acg
    ) == source_authority.TIER_NEUTRAL
    assert source_authority.authority_tier(
        "baike.baidu.com", acg_topic=True
    ) == source_authority.TIER_MAJOR_MEDIA, "抬档机制本身没坏，只是不再被误触发"
    # 检索门这一层的语义不变：这些 reason 仍然可被 ACG 检索放行，
    # 拦住它们的是**意图判定**，不是门禁。
    assert acg_search_allowed("general_static_knowledge") is True


# ---------------------------------------------------------------------------
# ④洗涤后的查询仍是一条可读的检索词（不产生空查询、不带上客套话）
# ---------------------------------------------------------------------------


def test_extracted_query_stays_searchable() -> None:
    assert extract_acg_query("请问帮我看看芙莉莲第三季出了吗？") == "芙莉莲第三季"
    assert extract_acg_query("硬控是什么梗") == "硬控"
    assert extract_acg_query("原神5.0卡池最新消息") == "原神5.0卡池"
    assert extract_acg_query("") == ""


# ---------------------------------------------------------------------------
# ⑤竖源域名必须在权威表在册（不认就是未登记域名，会污染排序）
# ---------------------------------------------------------------------------


def test_vertical_domains_are_known_to_the_authority_table() -> None:
    from plugins.bot_unified_runtime.domains.core.search import acg_search

    for source in ("bangumi", "moegirl", "bilibili"):
        domain = acg_search._source_domain(source)  # 融合口写的就是这一枚域名，测试与之同源
        tier = source_authority.authority_tier(domain)
        assert tier != source_authority.TIER_UNKNOWN, f"{source}→{domain} 未登记"
        # 同一枚域名在 ACG 话题下只允许被**抬**不许被降。
        assert source_authority.authority_tier(domain, acg_topic=True) <= tier
