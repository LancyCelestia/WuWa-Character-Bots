"""S-ACG-TIER：ACG 检索意图**分档词表**的分区锁、语义锁与隔离矩阵。

背景（前席账：``.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-ACGFUSE.md`` §2/§5）：
词表原为一级平铺，专名（``鸣潮``）与普通汉语词（``日常``）在判据上等价，
且 ``_NON_ACG_HINTS`` 只在「一枚词都没命中」时才被读 ⇒ 命中泛用词即绕过反证。
现算实证 21 句非 ACG 问话被放行（其中前席点名 5 句，本席另现算 16 句）。

本件只锁三件事，且**一切取值都从真身常量 ``ACG_DOMAIN_TERMS`` 派生**：

① 分区锁——三档存在、无词跨格、无词漏档；
② 语义锁——weak 永不单独成判 / medium 可判但被反证否决 / strong 反证不可否决；
③ 隔离矩阵——改一枚词的档位，只准改变含这枚词的句子的判定，其余逐字不变。

病灶逐例锁（5 假开 + 5 漏判）在 ``tests/test_search_intent_acg.py``（已摘牌转正），
本件补的是那 16 枚现算误开与分档结构本身。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.core.search import search_intent as si
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_MEDIUM,
    ACG_TIER_STRONG,
    ACG_TIER_WEAK,
    ACG_TIERS,
    detect_acg_intent,
)


# 反证信号用的干扰词也一律从真身读，不在夹具里另抄一份字面量。
def _terms_of_tier(tier: str) -> frozenset[str]:
    """某一档的全部词（投影真身注册表，测试不自带名单）。"""
    return frozenset(
        term for tiers in ACG_DOMAIN_TERMS.values() for term in tiers[tier]
    )


ALL_TERMS: frozenset[str] = _terms_of_tier(ACG_TIER_STRONG) | _terms_of_tier(
    ACG_TIER_MEDIUM
) | _terms_of_tier(ACG_TIER_WEAK)

#: 一条**与二次元无关**的高频干扰词：按内容从 ``_NON_ACG_HINTS`` 里挑，
#: 而不是写死字面量——日后这张表增删，测试跟着真身走。
def _one_hint_word() -> str:
    assert si._NON_ACG_HINTS, "反证词表为空，下面的共存裁决无从谈起"
    return next(h for h in si._NON_ACG_HINTS if h in ("菜谱", "怎么做", "教程"))


# ---------------------------------------------------------------------------
# ① 分区锁：注册表结构自洽
# ---------------------------------------------------------------------------


def test_every_domain_declares_exactly_the_three_tiers() -> None:
    for domain, tiers in ACG_DOMAIN_TERMS.items():
        assert set(tiers) == set(ACG_TIERS), f"{domain} 的档位键与 ACG_TIERS 不符"


def test_no_term_is_missing_a_tier_or_double_booked() -> None:
    """一枚词只能落在一个格子里；漏档或跨格都是分档表的账目不平。"""
    booked: dict[str, tuple[str, str]] = {}
    for domain, tiers in ACG_DOMAIN_TERMS.items():
        for tier, terms in tiers.items():
            assert len(terms) == len(set(terms)), f"{domain}/{tier} 内部有重复词"
            for term in terms:
                assert term not in booked, (
                    f"{term!r} 同时登记在 {booked[term]} 与 {(domain, tier)}"
                    "——两档并存时判据按哪一档都不对"
                )
                booked[term] = (domain, tier)


def test_tier_population_is_ordered_strong_medium_weak() -> None:
    """档位不是装饰品：三档都必须真的有人，否则"分级"退化成单级。"""
    counts = {tier: len(_terms_of_tier(tier)) for tier in ACG_TIERS}
    assert counts[ACG_TIER_WEAK] >= 10, counts
    assert counts[ACG_TIER_MEDIUM] >= 10, counts
    assert counts[ACG_TIER_STRONG] >= 10, counts


def test_every_domain_keeps_a_decisive_entry() -> None:
    """每个子域至少留一枚可单独成判的词，别让某个竖源域被整族降空。"""
    for domain, tiers in ACG_DOMAIN_TERMS.items():
        assert tiers[ACG_TIER_STRONG] or tiers[ACG_TIER_MEDIUM], domain


def test_hint_table_still_covers_the_everyday_domains_it_was_written_for() -> None:
    """反证词表本身不空，且仍认得当年那几枚高频干扰词（防止被整段清空）。"""
    assert si._NON_ACG_HINTS
    for hint in ("天气", "股价", "菜谱", "怎么做"):
        assert hint in si._NON_ACG_HINTS, hint


# ---------------------------------------------------------------------------
# ② 语义锁：三档的判据含义（逐词穷尽，不抽样）
# ---------------------------------------------------------------------------

WEAK_TERMS = sorted(_terms_of_tier(ACG_TIER_WEAK))
MEDIUM_TERMS = sorted(_terms_of_tier(ACG_TIER_MEDIUM))
STRONG_TERMS = sorted(_terms_of_tier(ACG_TIER_STRONG))


@pytest.mark.parametrize("term", WEAK_TERMS)
def test_weak_term_never_decides_alone(term: str) -> None:
    """弱通用词单独成句一律不判 ACG——这正是 21 句误开的总闸门。"""
    assert detect_acg_intent(term).is_acg is False, (
        f"{term!r} 被当成单独可定罪的证据；它应留在 weak 档"
    )


@pytest.mark.parametrize("term", STRONG_TERMS)
def test_strong_term_decides_and_survives_a_non_acg_hint(term: str) -> None:
    """强专名：库里有的条目名不该被反证词挡在门外。"""
    assert detect_acg_intent(term).is_acg is True
    assert detect_acg_intent(f"{term}{_one_hint_word()}").is_acg is True, (
        f"{term!r} 被反证词否决了——它不在 strong 档，或被谁挪走了"
    )


@pytest.mark.parametrize("term", MEDIUM_TERMS)
def test_medium_term_decides_alone_but_not_against_a_hint(term: str) -> None:
    """中等域专名：单独可判，与反证词共现时判否（共决，取代旧的"零命中才看"）。"""
    assert detect_acg_intent(term).is_acg is True
    assert detect_acg_intent(f"{term}{_one_hint_word()}").is_acg is False, (
        f"{term!r} 命中了反证词仍然放行 ⇒ 反证信号又被词表命中架空了"
    )


@pytest.mark.parametrize(
    "weak,anchor",
    [
        ("日常", "原神"),  # game 强专名 + game 弱通用词
        ("切片", "hololive"),  # vtuber 专名 + 当年误开的泛用词
        ("毕业", "初音未来"),
        ("连载", "漫画"),  # 弱 + 中 ⇒ 由中档抬进 ACG
        ("复刻", "鸣潮"),
    ],
)
def test_weak_term_still_contributes_evidence_when_not_deciding(
    weak: str, anchor: str
) -> None:
    """弱档"不单独定罪"不等于"当作没看见"：被放行时它仍要进审计词与子域标签。"""
    intent = detect_acg_intent(f"{anchor}{weak}")
    assert intent.is_acg is True
    assert weak in intent.matched_terms, (
        f"{weak} 既没参与判定也没进审计，说明它被整枚删掉了而不是降档"
    )


# ---------------------------------------------------------------------------
# ③ 现算误开：前席点名 5 枚之外的另外 16 枚，逐例建锁
# ---------------------------------------------------------------------------

# (问句, 现算命中的那枚泛用词) —— 两侧都是 2026-09-26 探针实测值。
EXTRA_FALSE_POSITIVES: tuple[tuple[str, str], ...] = (
    ("今天气温高达30度", "高达"),
    ("手机充电慢怎么办", "充电"),
    ("我们干杯一个", "干杯"),
    ("我的基金腰斩了", "腰斩"),
    ("手机皮套哪个牌子好", "皮套"),
    ("蓝莓松饼怎么做", "蓝莓"),
    ("iOS 18 版本更新了什么", "版本更新"),
    ("PPT动画怎么做", "动画"),
    ("这个栏目日更吗", "日更"),
    ("他的论文停更了", "停更"),
    ("工资保底多少", "保底"),
    ("鼻子歪了能恢复吗", "歪了"),
    ("市场前瞻：第三季度经济", "前瞻"),
    ("复刻版球鞋值得买吗", "复刻"),
    ("公司周年庆发礼品卡", "周年庆"),
    ("jump 键没反应", "jump"),
)


@pytest.mark.parametrize("question,culprit", EXTRA_FALSE_POSITIVES)
def test_recounted_false_opens_are_now_closed(
    question: str, culprit: str
) -> None:
    intent = detect_acg_intent(question)
    assert intent.is_acg is False, f"{question} 仍被 {culprit} 单独抬进 ACG"
    assert intent.tags == ()
    # 判据归属：那枚词必须**还在表里**、且归在 weak（降档≠删词）。
    assert culprit in ALL_TERMS, f"{culprit} 被从词表里删掉了，不是降档"


@pytest.mark.parametrize("question,culprit", EXTRA_FALSE_POSITIVES)
def test_recounted_false_opens_rooted_in_weak_or_hint(
    question: str, culprit: str
) -> None:
    """现算每条误开的归因：要么 culprit 是 weak 档，要么是 medium 撞上反证词。"""
    in_weak = culprit in _terms_of_tier(ACG_TIER_WEAK)
    in_medium = culprit in _terms_of_tier(ACG_TIER_MEDIUM)
    hits_hint = any(h in question for h in si._NON_ACG_HINTS)
    assert (in_weak or (in_medium and hits_hint)), (
        f"{question}：{culprit} 既不在 weak 档也没撞上反证词，说明它压根不是元凶"
    )


def test_generic_encyclopedia_bump_is_no_longer_triggered() -> None:
    """后果面（今天唯一不受开关影响的一条腿）：这些句子不再抬百科档。"""
    from plugins.bot_unified_runtime.domains.core.search import source_authority

    for question, _culprit in EXTRA_FALSE_POSITIVES:
        is_acg = detect_acg_intent(question).is_acg
        assert is_acg is False, question
        assert source_authority.authority_tier(
            "baike.baidu.com", acg_topic=is_acg
        ) == source_authority.TIER_NEUTRAL, question


# ---------------------------------------------------------------------------
# ④ 共存裁决式：反证信号必须能与词表命中同时生效
#    （旧写法 ``if not tag_terms and strong_pattern_hit and any(hint…)`` 做不到）
# ---------------------------------------------------------------------------


def test_disconfirming_signal_coexists_with_a_vocabulary_hit() -> None:
    # 「牛肉切片怎么做」：旧版 tag_terms 非空（切片）⇒ 整段跳过反证 ⇒ 判是；
    # 新版切片是 weak、怎么做是反证 ⇒ 判否。
    assert detect_acg_intent("牛肉切片怎么做才嫩").is_acg is False
    # 「我的日常」：弱档单独命中，旧版判是、新版判否。
    assert detect_acg_intent("我的日常").is_acg is False
    # 「原神教程怎么做」：强专名免疫反证词（库里有的条目名不该被挡）。
    assert detect_acg_intent("原神教程怎么做").is_acg is True
    # 纯模式兜底 + 反证词：仍是"不算"（这条旧版就在执法，不许被顺手放宽）。
    assert detect_acg_intent("第12集怎么做的").is_acg is False
    assert detect_acg_intent("第12集什么时候出").is_acg is True


def test_pattern_and_weak_term_still_open_the_gate() -> None:
    """模式规则是独立证据：弱档词与它共现时足以放行（旧行为保持）。"""
    intent = detect_acg_intent("这个梗第3集了")
    assert intent.is_acg is True
    assert "meme" in intent.tags


# ---------------------------------------------------------------------------
# ⑤ 隔离矩阵：改档只准动含这枚词的句子
# ---------------------------------------------------------------------------

#: 隔离矩阵的语料。句子（不是词条）抄自两件现有测试件的现成问句
#: ``tests/test_v21r2_search_intent.py`` / ``tests/test_search_intent_acg.py``
#: 加本席的 16 枚现算误开——词条一律走 ``ACG_DOMAIN_TERMS`` 派生，不在这里挑。
CORPUS: tuple[str, ...] = (
    # 正例
    "芙莉莲第三季出了吗",
    "鬼灭之刃最新话更新到哪了",
    "咒术回战第25集什么时候出",
    "一月新番有哪些值得追",
    "孤独摇滚漫画连载到第几话",
    "进击的巨人漫画完结了吗",
    "原神5.0卡池什么时候复刻",
    "明日方舟新版本前瞻直播",
    "鸣潮今天有什么活动",
    "星穹铁道深渊这期怎么配队",
    "少女前线2追放公测了吗",
    "硬控是什么梗",
    "下次一定这个梗出自哪里",
    "最近B站有什么热梗",
    "百大UP主公布了吗",
    "B站鬼畜区最近的名场面",
    "vtuber中之人是什么意思",
    "EVA剧场版剧情讲了什么",
    "芙莉莲的声优是谁",
    "第12集什么时候出",
    "崩铁最新卡池有谁",
    "虚拟偶像初音未来和巡音流歌分别是谁",
    "初音未来的代表作品有哪些",
    "辉夜大小姐想让我告白 更新到哪了",
    "hololive 新成员有哪些",
    "鹿鸣 新视频出了吗",
    "命运石之门好看吗",
    # 反例
    "今天天气怎么样",
    "最新基金行情如何",
    "提醒我12点吃药",
    "用Python写个快速排序",
    "美股最新股价",
    "红烧肉怎么做比较好吃",
    "崩铁值得抽吗",
    "我下个月就要毕业了",
    "牛肉切片怎么炒才嫩",
    "我的工作日常真的很无聊",
    "这款手机续航日常够用吗",
    "高血压病人日常吃什么药",
) + tuple(q for q, _ in EXTRA_FALSE_POSITIVES)


def _registry_with_tier(term: str, tier: str) -> dict[str, dict[str, tuple[str, ...]]]:
    """构造一份"把 term 挪到 tier（保持子域不变）"的注册表**副本**。

    真身一字不动：所有变异都发生在派生副本上，由 monkeypatch 顶包。
    """
    rebuilt: dict[str, dict[str, list[str]]] = {
        domain: {t: list(terms) for t, terms in tiers.items()}
        for domain, tiers in ACG_DOMAIN_TERMS.items()
    }
    moved = False
    for tiers in rebuilt.values():
        for source_tier, terms in tiers.items():
            if term in terms and source_tier != tier:
                terms.remove(term)
                tiers[tier].append(term)
                moved = True
    assert moved, f"{term} 本来就在 {tier} 档，这次变异是空跑"
    return {
        domain: {t: tuple(terms) for t, terms in tiers.items()}
        for domain, tiers in rebuilt.items()
    }


MUTATIONS: tuple[tuple[str, str], ...] = (
    ("日常", ACG_TIER_STRONG),
    ("切片", ACG_TIER_STRONG),
    ("毕业", ACG_TIER_STRONG),
    ("高达", ACG_TIER_MEDIUM),
    ("芙莉莲", ACG_TIER_WEAK),
    ("漫画", ACG_TIER_WEAK),
    ("原神", ACG_TIER_MEDIUM),
    ("卡池", ACG_TIER_WEAK),
)


@pytest.mark.parametrize("term,target_tier", MUTATIONS)
def test_retiering_moves_only_sentences_that_contain_the_term(
    monkeypatch: pytest.MonkeyPatch, term: str, target_tier: str
) -> None:
    """回归矩阵的正腿：改一枚词的档位，判定只准在**含这枚词**的句子上变。

    这一条锁的是实现而不是词表——若哪天有人把分档写成"整表重算"（例如改了
    ``_hit_terms`` 的作用域、或让档位污染标签收集），不含该词的句子会先红。
    """
    before = {q: detect_acg_intent(q).is_acg for q in CORPUS}
    monkeypatch.setattr(si, "ACG_DOMAIN_TERMS", _registry_with_tier(term, target_tier))
    after = {q: detect_acg_intent(q).is_acg for q in CORPUS}

    changed = {q for q in CORPUS if before[q] != after[q]}
    innocent = {q for q in changed if term not in q}
    assert not innocent, f"{term}→{target_tier} 影响了不含它的句子：{innocent}"


@pytest.mark.parametrize(
    "term,target_tier,expected_flips",
    [
        ("日常", ACG_TIER_STRONG, 3),  # 语料里含「日常」的三句全部翻回 ACG
        ("切片", ACG_TIER_STRONG, 1),
        ("毕业", ACG_TIER_STRONG, 1),
    ],
)
def test_retiering_a_weak_term_back_to_strong_reopens_exactly_its_sentences(
    monkeypatch: pytest.MonkeyPatch,
    term: str,
    target_tier: str,
    expected_flips: int,
) -> None:
    """回归矩阵的反腿：降档之所以拦得住，就是因为档位本身——提回去必须逐句翻回。

    它同时是"本锁有杀伤力"的自证：若断言只看 is_acg 而判据其实写死，这里翻不了。
    """
    before = {q: detect_acg_intent(q).is_acg for q in CORPUS}
    monkeypatch.setattr(si, "ACG_DOMAIN_TERMS", _registry_with_tier(term, target_tier))
    after = {q: detect_acg_intent(q).is_acg for q in CORPUS}
    flipped = {q for q in CORPUS if before[q] != after[q]}
    assert len(flipped) == expected_flips, flipped
    assert all(term in q for q in flipped)


def test_mutation_helper_never_touches_the_real_registry() -> None:
    """变异必须发生在副本上：真身注册表在整件事里一个字都不该动。

    这条锁防的是"改档测试把生产词表改了"——一旦发生，别的用例就在测被改过的表，
    全套绿都不作数（本仓"注毒只准打副本"的同型教训）。
    """
    before = {
        domain: {tier: list(terms) for tier, terms in tiers.items()}
        for domain, tiers in ACG_DOMAIN_TERMS.items()
    }
    mutated = _registry_with_tier("日常", ACG_TIER_STRONG)
    after = {
        domain: {tier: list(terms) for tier, terms in tiers.items()}
        for domain, tiers in ACG_DOMAIN_TERMS.items()
    }
    assert before == after, "真身词表被变异函数原地改写了"
    assert "日常" not in [
        t for t in mutated["game"][ACG_TIER_WEAK]
    ], "副本里也没改成功，那变异是空跑"
    assert "日常" in mutated["game"][ACG_TIER_STRONG]
