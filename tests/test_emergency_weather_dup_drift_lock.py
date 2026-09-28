"""S-FIX-ATK-WXEMG T5锁 | 报警拆色/颜色序位/haversine 双身防漂移。

对应审计票 SEAT-ATK-WEATHER T5（欠账·自认未收口）：
- `weather/capabilities/weather.py`（parse_alert_title + _ALARM_COLOR_RANK）与
  `emergency_info/sources/nmc_alarm.py`（split_alarm_title + ALARM_COLOR_RANK）
  两份拆色逐字同语义；
- `emergency_info/service/subscriptions.py` 与 `emergency_info/sources/open_data_quakes.py`
  各一份 haversine_km（asin 形 / atan2 形，数学同式）。

真正的收口（上提公共件）落点在本席写面之外（公共件目录不属于 weather/
emergency_info 两域），且 nmc_alarm.py:17-22 头注已登记「上提为单一事实源」的
§4 落地请求——本席不强做反向依赖搬迁，改为**先把漂移钉死**：一改一漏当天
本件即红（这正是票面点名的危害「两处日后一改一漏 ⇒ 判读分叉」）。
收口落盘后本件自然退役或改锁单源。

注毒自证：%TEMP% 副本改一枚颜色序位值 ⇒ 对账必红（见票根报告复跑证据段）。
全部离线。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.emergency_info.service.subscriptions import (
    haversine_km as haversine_subs,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
    ALARM_COLOR_RANK,
    split_alarm_title,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.open_data_quakes import (
    haversine_km as haversine_odq,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    _ALARM_COLOR_RANK,
    parse_alert_title,
)

# ---------------------------------------------------------------- 颜色序位表


def test_alarm_color_rank_tables_are_identical_including_order() -> None:
    """两张序位表逐键等值且**迭代序一致**（拆色取「表序中首个命中」，序也是语义）。"""
    assert _ALARM_COLOR_RANK == ALARM_COLOR_RANK
    assert list(_ALARM_COLOR_RANK) == list(ALARM_COLOR_RANK)


# ---------------------------------------------------------------- 标题拆色对账

_ALERT_TITLE_CORPUS: list[str] = [
    # 真样例形态（nmc_findAlarm.sample.json 首条同型）。
    "湖南省湘西土家族苗族自治州保靖县气象台发布大雾黄色预警信号",
    "辽宁省锦州市黑山县气象台发布大雾橙色预警信号",
    "中央气象台发布暴雨红色预警",
    "北京市气象台发布雷电黄色预警信号",
    # 后缀两分支与无「发布」/无颜色/颜色在类型段的边角。
    "上海市青浦区气象台发布大风蓝色预警信号",
    "大风黄色预警",
    "强对流天气预警信号",
    "发布冰雹橙色预警信号",
    "气象台发布大雾预警",
    "无发布无颜色的裸标题",
    "发布（台风）红色预警信号",
    # 双颜色词：表序首个命中，两侧必须一致。
    "县气象台发布大雾转暴雨橙色和红色预警信号",
    # 「预警」嵌套在「预警信号」之前的标题：后缀尝试序（先「预警信号」后
    # 「预警」）唯一的可观察分叉点——注毒实测：不喂这类样本，后缀序漂移抓不住。
    "县气象台发布暴雪预警升级为橙色预警信号",
    "市气象台发布寒潮蓝色预警信号解除后再次预警",
    "",
]


@pytest.mark.parametrize("title", _ALERT_TITLE_CORPUS)
def test_title_split_semantics_pinned(title: str) -> None:
    """同一标题在两域解析结果必须逐字相等（漂移=判读分叉，当场抓红）。"""
    assert parse_alert_title(title) == split_alarm_title(title)


def test_title_split_accepts_none_like_inputs() -> None:
    """非 str 入参（None）两侧行为同形：都不炸、都回空。"""
    assert parse_alert_title(None) == split_alarm_title(None) == ("", "")


# ---------------------------------------------------------------- haversine 对账

_COORD_PAIRS: list[tuple[float, float, float, float]] = [
    (39.9042, 116.4074, 39.9151, 116.4039),  # 同城近距离
    (34.0522, -118.2437, 40.7128, -74.0060),  # 跨洲
    (0.0, 0.0, 0.0, 0.0),  # 零距离
    (39.9042, 116.4074, 39.9042, 116.4074),  # 同点
    (-33.8688, 151.2093, 64.1355, -21.8954),  # 高纬度跨半球
    (89.9, 0.0, -89.9, 179.9),  # 近对跖（atan2/asin 两形的数值差界点）
]


@pytest.mark.parametrize("lat1,lon1,lat2,lon2", _COORD_PAIRS)
def test_haversine_two_implementations_agree(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> None:
    """两份 haversine 半径门共用后必须数值一致（1 m 容差；分叉即圈选漂移）。"""
    a = haversine_subs(lat1, lon1, lat2, lon2)
    b = haversine_odq(lat1, lon1, lat2, lon2)
    assert abs(a - b) < 1e-3, (a, b)
