"""占卜套件回归：干支八字 / 塔罗 / 六十四卦金钱卦 / 能力解析与文案。

全部为纯本地计算测试，无网络。干支向量均标注参考来源。
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
    parse_divination_intent,
)
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.sources.ganzhi import (
    CST,
    NAYIN_TABLE,
    Pillar,
    bazi_chart,
    format_bazi_text,
    solar_term_beijing,
)
from plugins.bot_unified_runtime.sources.iching import (
    HEXAGRAMS,
    CastResult,
    cast_hexagram,
    format_cast_text,
    hexagram_of,
    toss_yao,
)
from plugins.bot_unified_runtime.sources.tarot import (
    DECK,
    daily_card,
    draw_cards,
    format_single_text,
    format_three_text,
    single_guidance,
    three_card_spread,
)

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# 干支 / 八字。
# ---------------------------------------------------------------------------


class TestDayPillarAnchors:
    """日柱 JDN 公式 (JDN + 49) mod 60 的万年历锚点。

    来源：榜信万年历 https://wannianrili.bmcx.com/<年-月>__wannianrili/
    （2000-01/1949-10/1998-03/2024-02/2026-09 各页干支纪日栏）。
    """

    @pytest.mark.parametrize(
        ("day", "expected"),
        [
            (date(1949, 10, 1), "甲子"),  # 开国大典当日（bmcx 1949-10 页）
            (date(1998, 3, 2), "戊申"),  # bmcx 1998-03 页
            (date(2000, 1, 1), "戊午"),  # bmcx 2000-01 页
            (date(2008, 8, 8), "庚辰"),  # bmcx 2008-08 页（立秋次日）
            (date(2024, 2, 4), "戊戌"),  # bmcx 2024-02 页（立春当日）
            (date(2026, 9, 9), "丙戌"),  # bmcx 2026-09 页
            (date(2026, 9, 10), "丁亥"),  # bmcx 2026-09 页
        ],
    )
    def test_day_pillar_matches_wannianli(self, day: date, expected: str) -> None:
        chart = bazi_chart(datetime(day.year, day.month, day.day, 12, tzinfo=CST))
        assert chart.day_pillar.name == expected

    def test_day_pillar_rolls_at_local_midnight(self) -> None:
        before = bazi_chart(datetime(2026, 9, 9, 23, 59, tzinfo=CST))
        after = bazi_chart(datetime(2026, 9, 10, 0, 1, tzinfo=CST))
        assert before.day_pillar.name == "丙戌"
        assert after.day_pillar.name == "丁亥"

    def test_naive_datetime_treated_as_cst(self) -> None:
        naive = bazi_chart(datetime(2000, 1, 1, 12, 0))  # noqa: DTZ001 - 专测 naive 视作东八区
        aware = bazi_chart(datetime(2000, 1, 1, 12, 0, tzinfo=CST))
        assert naive.day_pillar.name == aware.day_pillar.name == "戊午"


class TestBaziVectors:
    """八字四柱全量向量（年柱立春界 / 月柱节气界 / 日柱 JDN / 时柱五鼠遁）。

    来源：榜信万年历 https://wannianrili.bmcx.com/ 对应年月页
    （页面按日标注「X年【生肖】X月X日」，月柱与日柱可直接对出；
    年柱以立春交节为界，晚子时约定见模块文档）。
    """

    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            # bmcx 2026-09：丙午年 丁酉月（白露 09-07 22:40 交节后）丁亥日。
            (datetime(2026, 9, 10, 21, 51, tzinfo=CST), "丙午丁酉丁亥辛亥"),
            # 任务验收向量对应的真实日期：己丑日在 2026-09-12（丁亥 + 2 天）。
            (datetime(2026, 9, 12, 21, 51, tzinfo=CST), "丙午丁酉己丑乙亥"),
            # bmcx 1949-10：己丑年 癸酉月 甲子日；15:00 开国大典，甲日申时壬申。
            (datetime(1949, 10, 1, 15, 0, tzinfo=CST), "己丑癸酉甲子壬申"),
            # bmcx 2000-01：己卯年（立春 2000-02-04 前）丙子月（大雪后）戊午日。
            (datetime(2000, 1, 1, 12, 0, tzinfo=CST), "己卯丙子戊午戊午"),
            # bmcx 2008-08：戊子年 庚申月（立秋 08-07 11:16 交节后第一天）庚辰日。
            (datetime(2008, 8, 8, 20, 0, tzinfo=CST), "戊子庚申庚辰丙戌"),
            # bmcx 2024-02：立春 02-04 16:26:53 交节后 → 甲辰年 丙寅月 戊戌日。
            (datetime(2024, 2, 4, 18, 0, tzinfo=CST), "甲辰丙寅戊戌辛酉"),
            # 节气当天交节时刻之前：仍属旧年癸卯、丑月（八字行业通行约定）。
            (datetime(2024, 2, 4, 10, 0, tzinfo=CST), "癸卯乙丑戊戌丁巳"),
            # bmcx 1998-03：戊寅年 甲寅月（惊蛰 03-06 02:57 前）戊申日；辰时丙辰。
            (datetime(1998, 3, 2, 7, 0, tzinfo=CST), "戊寅甲寅戊申丙辰"),
        ],
    )
    def test_four_pillars(self, moment: datetime, expected: str) -> None:
        chart = bazi_chart(moment)
        assert "".join(p.name for p in chart.pillars) == expected

    def test_late_zi_hour_uses_next_day_stem(self) -> None:
        # 晚子时约定：日柱归本日（丁亥），时干按次日（戊子日）五鼠遁 → 壬子时。
        chart = bazi_chart(datetime(2026, 9, 10, 23, 30, tzinfo=CST))
        assert chart.day_pillar.name == "丁亥"
        assert chart.hour_pillar.name == "壬子"

    def test_year_range_enforced(self) -> None:
        with pytest.raises(ValueError):
            bazi_chart(datetime(1899, 12, 31, tzinfo=CST))
        with pytest.raises(ValueError):
            bazi_chart(datetime(2101, 6, 1, tzinfo=CST))


class TestNayinAndElements:
    """纳音 30 表与五行计数（验收向量在 2026-09-12 21:51 复现）。"""

    def test_acceptance_chart_details(self) -> None:
        chart = bazi_chart(datetime(2026, 9, 12, 21, 51, tzinfo=CST))
        assert "".join(p.name for p in chart.pillars) == "丙午丁酉己丑乙亥"
        assert chart.nayin == ("天河水", "山下火", "霹雳火", "山头火")
        assert chart.element_counts == {"木": 1, "火": 3, "土": 2, "金": 1, "水": 1}
        assert chart.day_master == "己"
        assert chart.day_master_element == "土"

    @pytest.mark.parametrize(
        ("stem_index", "branch_index", "nayin"),
        [
            (0, 0, "海中金"),  # 甲子乙丑海中金（六十甲子序 0）
            (2, 6, "天河水"),  # 丙午丁未天河水（序 42）
            (8, 10, "大海水"),  # 壬戌癸亥大海水（序 58）
            (5, 1, "霹雳火"),  # 戊子己丑霹雳火（序 25）
        ],
    )
    def test_nayin_table_entries(
        self, stem_index: int, branch_index: int, nayin: str
    ) -> None:
        assert (
            Pillar(stem_index=stem_index, branch_index=branch_index).nayin == nayin
        )

    def test_nayin_table_has_30_entries(self) -> None:
        assert len(NAYIN_TABLE) == 30


class TestSolarTerms:
    """节气交节日（北京时间）对照。

    来源：bmcx 万年历节气时刻（与香港天文台一致）：
    白露 2026-09-07 22:40:59、立秋 2008-08-07 11:16:10、
    立春 2024-02-04 16:26:53、惊蛰 1998-03-06 02:57:15。
    """

    @pytest.mark.parametrize(
        ("year", "term_index", "expected_month", "expected_day"),
        [
            (2026, 14, 9, 7),  # 白露
            (2008, 12, 8, 7),  # 立秋（寿星公式给 08-08，天文实况 08-07）
            (2024, 0, 2, 4),  # 立春
            (1998, 2, 3, 6),  # 惊蛰
        ],
    )
    def test_term_day(
        self, year: int, term_index: int, expected_month: int, expected_day: int
    ) -> None:
        moment = solar_term_beijing(year, term_index)
        assert (moment.month, moment.day) == (expected_month, expected_day)


def test_format_bazi_text_contains_key_sections() -> None:
    chart = bazi_chart(datetime(2026, 9, 12, 21, 51, tzinfo=CST))
    text = format_bazi_text(chart)
    assert "八字排盘" in text
    assert "年柱 丙午（天河水）" in text
    assert "日主：己土" in text
    assert "火3" in text
    assert "仅供娱乐" in text


# ---------------------------------------------------------------------------
# 塔罗。
# ---------------------------------------------------------------------------


class TestTarotDeck:
    def test_deck_has_78_unique_cards(self) -> None:
        assert len(DECK) == 78
        assert len({card.name for card in DECK}) == 78
        majors = [card for card in DECK if card.arcana == "大阿卡纳"]
        assert len(majors) == 22
        for suit in ("权杖", "圣杯", "宝剑", "星币"):
            subset = [card for card in DECK if card.arcana == suit]
            assert len(subset) == 14
            assert len({card.name for card in subset}) == 14

    def test_every_card_has_upright_and_reversed_meanings(self) -> None:
        for card in DECK:
            assert card.upright_keywords and card.reversed_keywords
            assert card.upright_hint and card.reversed_hint

    def test_draw_is_deterministic_given_seeded_rng(self) -> None:
        first = draw_cards(5, random.Random(2026))
        second = draw_cards(5, random.Random(2026))
        assert [(d.card.name, d.is_reversed) for d in first] == [
            (d.card.name, d.is_reversed) for d in second
        ]

    def test_draw_samples_without_replacement(self) -> None:
        drawn = draw_cards(78, random.Random(1))
        assert len({d.card.name for d in drawn}) == 78

    def test_reversed_and_upright_both_reachable(self) -> None:
        orientations = set()
        for seed in range(200):
            orientations.add(draw_cards(1, random.Random(seed))[0].is_reversed)
        assert orientations == {True, False}

    def test_draw_count_bounds(self) -> None:
        with pytest.raises(ValueError):
            draw_cards(0, random.Random(1))
        with pytest.raises(ValueError):
            draw_cards(79, random.Random(1))


class TestTarotSpreads:
    def test_three_card_positions(self) -> None:
        spread = three_card_spread(random.Random(7))
        assert [d.position for d in spread] == ["过去", "现在", "未来"]
        assert len({d.card.name for d in spread}) == 3

    def test_three_card_deterministic(self) -> None:
        a = three_card_spread(random.Random(99))
        b = three_card_spread(random.Random(99))
        assert [(d.card.name, d.is_reversed) for d in a] == [
            (d.card.name, d.is_reversed) for d in b
        ]

    def test_single_guidance_returns_one_card(self) -> None:
        drawn = single_guidance(random.Random(3))
        assert drawn.position == ""
        assert drawn.card.name

    def test_daily_card_stable_for_same_day_and_user(self) -> None:
        first = daily_card(date(2026, 9, 11), "user-42")
        second = daily_card(date(2026, 9, 11), "user-42")
        assert (first.card.name, first.is_reversed) == (
            second.card.name,
            second.is_reversed,
        )

    def test_daily_card_differs_across_users_or_days(self) -> None:
        pairs = {
            (daily_card(date(2026, 9, 11), user).card.name, day)
            for day in (date(2026, 9, 11), date(2026, 9, 12))
            for user in ("a", "b", "c", "d")
        }
        # 同日不同用户 / 不同日期应能产生不同牌（确定性下抽查这组固定输入）。
        assert len(pairs) == 8

    def test_format_single_text(self) -> None:
        text = format_single_text(single_guidance(random.Random(5)))
        assert "（正位）" in text or "（逆位）" in text
        assert "关键词" in text

    def test_format_three_text_positions(self) -> None:
        text = format_three_text(three_card_spread(random.Random(5)))
        assert "过去" in text and "现在" in text and "未来" in text


# ---------------------------------------------------------------------------
# 金钱卦。
# ---------------------------------------------------------------------------


class _ScriptedRng(random.Random):
    """按脚本吐 random() 值的假随机源（<0.5 视为背面），仅测试用。"""

    def __init__(self, values: Iterator[float]) -> None:
        super().__init__()
        self._values = values

    def random(self) -> float:
        return next(self._values)


class TestCoinTossMapping:
    def test_three_backs_is_old_yang(self) -> None:
        value, coins = toss_yao(_ScriptedRng(iter([0.1, 0.2, 0.3])))
        assert (value, coins) == (9, (True, True, True))

    def test_no_backs_is_old_yin(self) -> None:
        value, _ = toss_yao(_ScriptedRng(iter([0.9, 0.8, 0.7])))
        assert value == 6

    def test_one_back_is_young_yang(self) -> None:
        value, _ = toss_yao(_ScriptedRng(iter([0.1, 0.8, 0.9])))
        assert value == 7

    def test_two_backs_is_young_yin(self) -> None:
        value, _ = toss_yao(_ScriptedRng(iter([0.1, 0.2, 0.9])))
        assert value == 8


class TestHexagramTable:
    def test_table_covers_64_unique_names(self) -> None:
        assert len(HEXAGRAMS) == 64
        names = [info.name for info in HEXAGRAMS.values()]
        assert len(set(names)) == 64

    @pytest.mark.parametrize(
        ("lines", "expected"),
        [
            ((1, 1, 1, 1, 1, 1), "乾为天"),  # 六爻全阳
            ((0, 0, 0, 0, 0, 0), "坤为地"),  # 六爻全阴
            ((1, 0, 1, 0, 1, 0), "水火既济"),  # 离下坎上
            ((0, 1, 0, 1, 0, 1), "火水未济"),  # 坎下离上
            ((1, 1, 1, 0, 0, 0), "地天泰"),  # 乾下坤上
            ((0, 0, 0, 1, 1, 1), "天地否"),  # 坤下乾上
        ],
    )
    def test_known_hexagram_mapping(
        self, lines: tuple[int, ...], expected: str
    ) -> None:
        assert hexagram_of(lines).name == expected

    def test_hexagram_of_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError):
            hexagram_of((1, 1, 1))
        with pytest.raises(ValueError):
            hexagram_of((1, 1, 1, 1, 1, 2))


class TestCast:
    def test_all_old_yang_casts_qian_and_changes_to_kun(self) -> None:
        rng = _ScriptedRng(iter([0.1] * 18))
        cast = cast_hexagram(rng)
        assert cast.yao_values == (9, 9, 9, 9, 9, 9)
        assert cast.original.name == "乾为天"
        assert cast.changed is not None
        assert cast.changed.name == "坤为地"

    def test_no_moving_lines_gives_no_changed_hexagram(self) -> None:
        rng = _ScriptedRng(iter([0.1, 0.8] * 9))
        cast = cast_hexagram(rng)
        assert all(value in (7, 8) for value in cast.yao_values)
        assert cast.changed is None

    def test_cast_deterministic_given_seed(self) -> None:
        a = cast_hexagram(random.Random(11))
        b = cast_hexagram(random.Random(11))
        assert a.yao_values == b.yao_values
        assert a.original.name == b.original.name

    def test_cast_result_lines_helpers(self) -> None:
        cast = CastResult(
            yao_values=(9, 8, 7, 6, 7, 8),
            original=hexagram_of((1, 0, 1, 0, 1, 0)),
            changed=None,
        )
        assert cast.lines == (1, 0, 1, 0, 1, 0)
        assert cast.moving_positions == (0, 3)
        assert cast.changed_lines == (0, 0, 1, 1, 1, 0)

    def test_format_cast_text_sections(self) -> None:
        cast = cast_hexagram(random.Random(2))
        text = format_cast_text(cast)
        assert "本卦" in text
        assert "爻象" in text
        assert "初" in text
        if cast.changed is not None:
            assert "变卦" in text


# ---------------------------------------------------------------------------
# 能力层：意图解析 + CapabilityResult。
# ---------------------------------------------------------------------------


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    timestamp: datetime | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        timestamp=timestamp or datetime(2026, 9, 12, 13, 51, tzinfo=_UTC),
    )


def _capability():
    return build_divination_capability(None)


class TestIntentParsing:
    def test_bazi_with_full_datetime(self) -> None:
        intent = parse_divination_intent("八字 1998年3月2日早上7点")
        assert intent is not None and intent.kind == "bazi"
        assert intent.when is not None
        assert intent.when == datetime(1998, 3, 2, 7, 0, tzinfo=CST)
        assert intent.date_given and not intent.error

    def test_bazi_afternoon_and_night_periods(self) -> None:
        intent = parse_divination_intent("排盘 2000年1月1日下午3点30分")
        assert intent is not None and intent.when is not None
        assert intent.when.hour == 15 and intent.when.minute == 30

        intent = parse_divination_intent("四柱 1990-06-15 晚上11点")
        assert intent is not None and intent.when is not None
        assert intent.when.hour == 23

    def test_bazi_date_only_defaults_to_noon(self) -> None:
        intent = parse_divination_intent("命盘 1998年3月2日")
        assert intent is not None and intent.when is not None
        assert (intent.when.hour, intent.when.minute) == (12, 0)

    def test_bazi_invalid_date_reports_error(self) -> None:
        intent = parse_divination_intent("八字 1998年2月30日")
        assert intent is not None and intent.kind == "bazi"
        assert intent.error
        assert intent.when is None

    def test_tarot_single_three_and_daily(self) -> None:
        assert parse_divination_intent("抽塔罗") is not None
        intent = parse_divination_intent("塔罗牌 看看过去现在未来")
        assert intent is not None and intent.target == "three"
        intent = parse_divination_intent("塔罗 三张")
        assert intent is not None and intent.target == "three"
        intent = parse_divination_intent("今日塔罗")
        assert intent is not None and intent.target == "daily"
        intent = parse_divination_intent("塔罗 每日一抽")
        assert intent is not None and intent.target == "daily"

    def test_iching_keywords(self) -> None:
        for text in ("占卜", "起卦", "算卦", "摇卦", "六十四卦"):
            intent = parse_divination_intent(text)
            assert intent is not None and intent.kind == "iching", text

    def test_non_divination_text_returns_none(self) -> None:
        for text in ("今天天气怎么样", "吃什么", "你好", ""):
            assert parse_divination_intent(text) is None, text


class TestCapabilityResults:
    def test_bazi_capability_formats_chart(self) -> None:
        result = _capability()(
            _message("八字 1998年3月2日早上7点"), None
        )
        assert result.kind == "divination"
        assert result.capability_id == "bot.divination"
        assert "capability:divination" in result.audit_tags
        assert "戊寅" in result.body and "甲寅" in result.body
        assert "戊申" in result.body and "丙辰" in result.body
        assert "仅供娱乐" in result.body

    def test_bazi_invalid_date_is_graceful(self) -> None:
        result = _capability()(_message("八字 1998年2月30日"), None)
        assert result.kind == "divination"
        assert "不太对" in result.body
        assert any("invalid_date" in tag for tag in result.audit_tags)

    def test_bazi_out_of_range_is_graceful(self) -> None:
        result = _capability()(_message("排盘 1850年5月1日"), None)
        assert result.kind == "divination"
        assert "超出" in result.body
        assert any("out_of_range" in tag for tag in result.audit_tags)

    def test_bazi_without_date_uses_now_and_hint(self) -> None:
        result = _capability()(_message("算命"), None)
        assert "八字排盘" in result.body
        assert "按当前时点排盘" in result.body

    def test_tarot_capability(self) -> None:
        result = _capability()(_message("抽塔罗"), None)
        assert result.kind == "divination"
        assert "（正位）" in result.body or "（逆位）" in result.body

    def test_tarot_three_card_capability(self) -> None:
        result = _capability()(_message("塔罗 三张"), None)
        assert "过去" in result.body and "未来" in result.body

    def test_tarot_daily_stable_within_day(self) -> None:
        timestamp = datetime(2026, 9, 12, 13, 51, tzinfo=_UTC)
        first = _capability()(
            _message("塔罗 每日一抽", timestamp=timestamp), None
        )
        second = _capability()(
            _message("塔罗 每日一抽", timestamp=timestamp), None
        )
        assert first.body == second.body
        assert "每日一抽" in first.body

    def test_tarot_daily_differs_by_user(self) -> None:
        timestamp = datetime(2026, 9, 12, 13, 51, tzinfo=_UTC)
        first = _capability()(
            _message("塔罗 每日一抽", sender_id="alice", timestamp=timestamp), None
        )
        second = _capability()(
            _message("塔罗 每日一抽", sender_id="bob", timestamp=timestamp), None
        )
        # 确定性哈希下，这两个固定用户当天的抽牌结果必然不同。
        assert first.body != second.body

    def test_iching_capability(self) -> None:
        result = _capability()(_message("帮我占卜一下"), None)
        assert result.kind == "divination"
        assert "本卦" in result.body
        assert "爻象" in result.body
