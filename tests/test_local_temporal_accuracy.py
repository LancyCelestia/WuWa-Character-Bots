"""时间/日期/星期/年/节日/节气/季节的准确性回归。

2026-11-10 实测：内置节气近似公式在 2026 年 29 天报错（例：11-07 报「小雪」，
实为「立冬」；12-22 报空，实为「冬至」）；农历节日表只对 2026 成立，2027
春节（02-06）答不出。本件把「以 multi_calendar 为唯一历法真身」钉住。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    temporal as temporal_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.temporal import (
    RuleBasedTemporalProvider,
    holiday_of,
    season_of,
    solar_term_of,
)


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    [
        (2026, 2, 4, "立春"),
        (2026, 4, 5, "清明"),
        (2026, 11, 7, "立冬"),
        (2026, 12, 22, "冬至"),
        (2027, 2, 4, "立春"),
    ],
)
def test_solar_term_matches_multi_calendar(year: int, month: int, day: int, expected: str) -> None:
    assert solar_term_of(datetime(year, month, day, tzinfo=timezone.utc)) == expected


def test_non_solar_term_day_is_blank() -> None:
    assert solar_term_of(datetime(2026, 11, 10, tzinfo=timezone.utc)) == ""


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    [
        (2026, 2, 16, "除夕"),
        (2026, 2, 17, "春节"),
        (2026, 3, 3, "元宵节"),
        (2026, 6, 19, "端午节"),
        (2026, 9, 25, "中秋节"),
        (2027, 2, 6, "春节"),
        (2027, 9, 15, "中秋节"),
    ],
)
def test_lunar_festivals_are_derived_not_hardcoded_to_2026(
    year: int, month: int, day: int, expected: str
) -> None:
    assert holiday_of(datetime(year, month, day, tzinfo=timezone.utc)) == expected


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    [
        (2026, 2, 3, "冬季"),   # 立春前仍属冬
        (2026, 2, 4, "春季"),
        (2026, 5, 4, "春季"),
        (2026, 5, 5, "夏季"),
        (2026, 8, 6, "夏季"),
        (2026, 8, 7, "秋季"),
        (2026, 11, 6, "秋季"),
        (2026, 11, 7, "冬季"),
    ],
)
def test_season_follows_solar_terms(year: int, month: int, day: int, expected: str) -> None:
    assert season_of(datetime(year, month, day, tzinfo=timezone.utc)) == expected


def test_snapshot_carries_year_weekday_holiday_term_and_season(monkeypatch: pytest.MonkeyPatch) -> None:
    moment = datetime(2027, 2, 6, 9, 30, tzinfo=timezone.utc)  # 2027 春节
    monkeypatch.setattr(temporal_module, "_clocked_now", lambda zone: moment.replace(tzinfo=zone))
    snapshot = RuleBasedTemporalProvider(timezone="Asia/Singapore").snapshot("req-accuracy")

    assert snapshot.date_local == "2027-02-06"
    assert snapshot.weekday == "星期六"
    assert snapshot.now_local == "09:30"
    assert snapshot.holiday == "春节"
    assert snapshot.season == "春季"  # 2027 立春 02-04 已过
    assert snapshot.timezone == "Asia/Singapore"
