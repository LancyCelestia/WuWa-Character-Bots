"""B2 席：紧急信息采集源回归（全离线，零真实请求）。

真样例即夹具（简报硬约束「解析测试必须吃这些真字节，不得自造 fixture 字段」）：
`tests/fixtures/emergency_info/` 下 E11 席 2026-09-20 实测落盘的响应字节——

| 文件 | 字节数 | 对应端点（E11 §2 矩阵行） |
|---|---|---|
| `nmc_findAlarm.sample.json` | 83,370 | #1 全国在报预警清单 |
| `nmc_restWeather.sample.json` | 10,473 | #2 站点级当前预警 `data.real.warn` |
| `icl_earlywarnings.sample.json` | 4,232 | #6 ICL 地震速报 |
| `usgs_all_hour.sample.geojson` | 3,163 | #10 USGS summary feed |
| `gdacs_eventlist.sample.json` | 63,829 | #14 GDACS allpaging |
| `nws_alerts.sample.json` | 8,234 | #12 NWS alerts（本席判定不接，仅留证据样例） |

夹具目录**受 git 跟踪**（B10-FIX 席 2026-09-20 从 `.superpowers/` 迁来：原路径落在
`.gitignore:42` 的 `.superpowers/` 之内，干净克隆上不存在 ⇒ 56 条采集器用例（B2 交付时
口径，本席补 1 条完整性锁后共 57 条）整体静默 `skip`＝假绿）。⇒ 现在**缺夹具一律判红**
（`pytest.fail`，见 `sample_bytes`），不再 `skip`：夹具在仓库里，读不到就是仓库损坏，
必须让人看见。逐件的端点/抓取时间/抓取命令原文见
`tests/fixtures/emergency_info/README.md`；波次取证原件仍留在
`.superpowers/sdd/2026-09-19-emergency-info-unify/probes/samples/` 不动（同字节双份）。

**本文件的核心命题不是「能不能解析」，而是「无数据」与「取数失败」必须
分成两种状态**（现役 `domains/weather/capabilities/weather.py:155-190`
`fetch_city_alerts` 把两者共用一个 `[]`，E11 §1.5 实锤 findAlarm 冷页 24.9s
vs 现码 timeout=8s ⇒ 生产间歇性把「取数失败」说成「无预警」）。故
`test_空字典信封一律判_FAILED_不判_NO_DATA`、
`test_站点预警真样例判_NO_DATA_而非_FAILED`、
`test_取数抛异常必须落到_FAILED` 三族用例是本席的锁。

样板坐标（抄谁）：注入取数替身 + 结构化断言的写法对齐
`tests/test_market_backoff.py` / `tests/test_finance_data.py`（金融域同源做法：
测试里 monkeypatch 网络层，断言退避与显式失败态，绝不发真实请求）。
"""

from __future__ import annotations

import ast
import copy
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from plugins.bot_unified_runtime.domains.emergency_info import contracts
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyStatus,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources import (
    gdacs as gdacs_source,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources import http_get
from plugins.bot_unified_runtime.domains.emergency_info.sources import (
    nmc_alarm as nmc_alarm_source,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources import (
    open_data_quakes as quake_source,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.gdacs import (
    fetch_gdacs_events,
    parse_gdacs_events,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.http_get import (
    ALLOWED_HOSTS,
    FetchState,
    SsrfRejectedError,
    UnsafeIdentifier,
    check_whitelisted_url,
    guard_outbound_url,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
    AlarmAlert,
    build_nmc_alarm_detail_url,
    build_nmc_find_alarm_url,
    build_nmc_rest_weather_url,
    fetch_nmc_alarms,
    fetch_nmc_station_alarm,
    parse_beijing_time,
    parse_nmc_alarm_page,
    parse_nmc_station_alarm,
    split_alarm_title,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.open_data_quakes import (
    CHINA_RECT,
    ICL_SOURCE_LABEL,
    QuakeEvent,
    build_icl_earlywarnings_url,
    build_usgs_fdsnws_url,
    build_usgs_feed_url,
    crosscheck_quakes,
    epoch_ms_to_utc,
    fetch_icl_earthquakes,
    fetch_usgs_quakes,
    fetch_usgs_recent_feed,
    haversine_km,
    parse_icl_earlywarnings,
    parse_usgs_geojson,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "emergency_info"

#: 域模型唯一安全构造口所在文件（`plugins/**` 相对路径；正向缝合锁的白名单）。
CONTRACTS_FILE_REL = "domains/emergency_info/contracts.py"

# 期望字节数=E11 落盘后实测（同一份磁盘字节被本席的解析测试直接吃）。
# 六件全部受 git 跟踪 ⇒ 缺件/漂移一律判红，不许静默 skip（见 sample_bytes）。
SAMPLE_SIZES = {
    "nmc_findAlarm.sample.json": 83370,
    "nmc_restWeather.sample.json": 10473,
    "icl_earlywarnings.sample.json": 4232,
    "usgs_all_hour.sample.geojson": 3163,
    "gdacs_eventlist.sample.json": 63829,
    # #12 NWS 判定「不接」：解析器不消费它，但它是本席「实测过、故意不接」的证据。
    "nws_alerts.sample.json": 8234,
}

BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")

# 刻意造 naive datetime（DTZ 规则不允许裸 datetime()）：验证 builder 把 naive 当 UTC 读。
NAIVE_START = datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
NAIVE_END = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)


def sample_bytes(name: str) -> bytes:
    """读真夹具原始字节；**缺件即判红**（绝不 skip、绝不用自造夹具替）。

    理由：夹具目录 `tests/fixtures/emergency_info/` 受 git 跟踪，干净克隆必然带着它
    ⇒ 读不到只可能是仓库损坏（被误删/被 .gitignore 吞掉/改名未同步），
    这时若放行 skip，本文件全部采集器用例就会整体静默失效（＝本仓点名的
    「牙口不足的门」，B2 席 report §4 R-5 的原始事故）。
    """
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.fail(
            f"真夹具缺失：{path}——夹具受 git 跟踪，缺失即仓库损坏，不得静默放行。"
            "（历史成因：样例曾放在 .superpowers/ 下被 .gitignore:42 忽略，"
            "干净克隆上 56 条用例全体 skip。恢复办法见该目录 README.md 的抓取命令原文。）"
        )
    data = path.read_bytes()
    expected = SAMPLE_SIZES.get(name)
    if expected is not None and len(data) != expected:
        pytest.fail(
            f"真夹具字节数漂移：{name} 期望 {expected}B，实得 {len(data)}B"
            "（E11 落盘后样例被改动过，本席断言以原始字节为准）"
        )
    return data


def load_sample(name: str) -> Any:
    return json.loads(sample_bytes(name).decode("utf-8"))


# ================================================================ 真样例：结构与不变量

def test_fixtures_are_all_present_and_non_empty() -> None:
    """夹具完整性锁：六件齐全、字节数>0、且逐件与 `SAMPLE_SIZES` 记录一致。

    这条用例**不经过** `sample_bytes`（不靠别的解析用例顺带触发），专门堵
    「将来有人误删/改名一份夹具后靠 skip 蒙过去」的路：本文件全部真夹具断言
    都吃这六份字节，任何一件不见 => 这里立刻红并点名。
    """
    assert FIXTURE_DIR.is_dir(), f"夹具目录不存在：{FIXTURE_DIR}"
    present = sorted(p.name for p in FIXTURE_DIR.iterdir() if ".sample." in p.name)
    assert present == sorted(SAMPLE_SIZES), (
        f"夹具目录里的 *.sample.* 件与本文件登记的不一致：实得 {present}"
    )
    for name, expected in SAMPLE_SIZES.items():
        path = FIXTURE_DIR / name
        assert path.is_file(), (
            f"缺夹具：{path}（README.md 有该端点的抓取命令原文，重抓后须同步 SAMPLE_SIZES）"
        )
        size = path.stat().st_size
        assert size > 0, f"夹具是空文件：{name}"
        assert size == expected, f"夹具字节数漂移：{name} 期望 {expected}B，实得 {size}B"


def test_nmc_find_alarm_sample_parses_all_real_items() -> None:
    payload = load_sample("nmc_findAlarm.sample.json")
    outcome = parse_nmc_alarm_page(payload)

    assert outcome.state is FetchState.OK
    assert outcome.source_id == "nmc"
    assert len(outcome.items) == 300  # 真样例 page.list 恰 300 条
    assert outcome.total_hint == 328  # 源端自报 count=328（E11 §5.2 一致）
    assert outcome.dropped == 0
    assert outcome.truncated is True
    assert "page_truncated:300/328" in outcome.notes

    first = outcome.items[0]
    assert first.alertid == "43312541600000_20260920004312"
    assert first.title == "湖南省湘西土家族苗族自治州保靖县气象台发布大雾黄色预警信号"
    assert (first.kind, first.color_label) == ("大雾", "黄色")
    assert first.issued_at == datetime(2026, 9, 20, 0, 43, tzinfo=BEIJING_TZ)
    # 分隔符按真样例字节是斜杠（见下方 test_nmc_issuetime_real_bytes_use_slashes），用码点写死
    assert first.issued_text == "2026" + chr(0x2F) + "09" + chr(0x2F) + "20 00:43"
    assert first.url == (
        "https://www.nmc.cn/publish/alarm/43312541600000_20260920004312.html"
    )
    assert first.detail_url == first.url
    assert first.pic == "https://image.nmc.cn/assets/img/alarm/p0005003.png"
    assert first.province_level is False


def test_nmc_find_alarm_color_distribution_matches_sample() -> None:
    outcome = parse_nmc_alarm_page(load_sample("nmc_findAlarm.sample.json"))
    counter = Counter(item.color_label for item in outcome.items)
    # E11 §5.2 词表实测（本样例时点）：黄183 / 蓝109 / 橙8，无红。
    assert counter == {"黄色": 183, "蓝色": 109, "橙色": 8}
    assert "" not in counter  # 300/300 条都从标题拿到了颜色词


def test_nmc_province_alarms_merge_without_double_counting() -> None:
    payload = load_sample("nmc_findAlarm.sample.json")
    province_ids = {item["alertid"] for item in payload["data"]["provinceAlarms"]}
    list_ids = {item["alertid"] for item in payload["data"]["page"]["list"]}
    # 真样例事实：4 条省级预警全部已在 list 内 ⇒ 合并只打标、不增条目。
    assert province_ids == list_ids & province_ids
    assert len(province_ids) == 4

    outcome = parse_nmc_alarm_page(payload)
    assert len(outcome.items) == 300
    flagged = {item.alertid for item in outcome.items if item.province_level}
    assert flagged == province_ids


def test_nmc_station_alarm_real_sample_is_no_data_not_failed() -> None:
    """本席最重要的一条锁：真样例（北京站 Wqsps）`warn.alert="9999"` = 确实无预警。

    现役天气支路遇到这种情况返回 `[]`，与「接口不可达」的 `[]` 不可分辨
    （weather.py:155-190 源码原文即如此声明）。本席必须给出 NO_DATA。
    """
    payload = load_sample("nmc_restWeather.sample.json")
    assert payload["data"]["real"]["warn"]["alert"] == "9999"

    outcome = parse_nmc_station_alarm(payload, stationid="Wqsps")
    assert outcome.state is FetchState.NO_DATA
    assert outcome.items == ()
    assert outcome.reason == "station_has_no_active_alarm"
    assert outcome.transport_ok is True  # 链路是好的，只是没预警


def test_icl_sample_parses_and_never_claims_to_be_cenc() -> None:
    outcome = parse_icl_earlywarnings(load_sample("icl_earlywarnings.sample.json"))
    assert outcome.state is FetchState.OK
    assert len(outcome.items) == 20
    assert outcome.dropped == 0

    first = outcome.items[0]
    assert first.source_id == "icl"
    assert first.event_id == "98395394"
    assert first.updates == 5
    assert first.station_count == 6  # 源端拼写 `sations`（E11 §4 容错注记）
    assert first.magnitude_display == "3.9"  # 源值 3.900001 的显示态
    assert first.depth_km == pytest.approx(8.156873)
    assert first.epicenter_text == "四川长宁"
    assert (first.latitude, first.longitude) == (28.303818, 104.98669)
    assert first.origin_at == datetime(2026, 8, 24, 0, 26, 21, 614000, tzinfo=timezone.utc)
    assert first.origin_at_beijing == datetime(
        2026, 8, 24, 8, 26, 21, 614000, tzinfo=BEIJING_TZ
    )
    # D-1/E11 §6 红线：降级代理源不得冒充 CENC 官网口径。
    assert first.label == ICL_SOURCE_LABEL == "ICL（中国地震预警网联盟）"
    assert "CENC" not in first.label.upper()
    assert "台网" not in first.label  # 也不写成「中国地震台网」那种官方口径

    third = outcome.items[2]  # 真样例第 3 条（轮台县）无 `sations` 字段
    assert "sations" not in load_sample("icl_earlywarnings.sample.json")["data"][2]
    assert third.station_count is None
    assert third.mag_type == ""  # ICL 不披露震级类型 ⇒ 空串，不硬造 mw


def test_usgs_sample_parses_with_geojson_coordinate_order_respected() -> None:
    outcome = parse_usgs_geojson(load_sample("usgs_all_hour.sample.geojson"))
    assert outcome.state is FetchState.OK
    assert len(outcome.items) == 4
    assert outcome.total_hint == 4
    assert outcome.dropped == 0

    first = outcome.items[0]
    assert first.event_id == "aka2026spjbip"
    assert first.magnitude == 0.6
    assert first.mag_type == "ml"
    assert first.status == "automatic"
    assert first.epicenter_text == "78 km NNW of Karluk, Alaska"
    # GeoJSON coordinates 是 [lon, lat, depth]：写反就是「地震跑到几内亚湾」。
    assert first.longitude == pytest.approx(-154.793)
    assert first.latitude == pytest.approx(58.249)
    assert first.depth_km == pytest.approx(5.0)
    assert first.station_count == 8  # USGS 的 nst（台数）对 ICL 的 sations
    assert first.origin_at_beijing == datetime(
        2026, 9, 20, 0, 39, 55, 747000, tzinfo=BEIJING_TZ
    )
    assert [item.magnitude for item in outcome.items] == [0.6, 0.7, 1.03, 2.6]


def test_gdacs_sample_drops_the_meta_entry_and_never_invents_a_color() -> None:
    outcome = parse_gdacs_events(load_sample("gdacs_eventlist.sample.json"))
    assert outcome.state is FetchState.OK
    assert len(outcome.items) == 100
    assert outcome.dropped == 1  # features[0] 只有 properties.meta.maxelement
    assert outcome.total_hint == 101
    assert "gdacs_time_tz_assumed_utc" in outcome.notes
    assert "unmapped_alert_level=100" in outcome.notes

    by_id = {item.event_id: item for item in outcome.items}
    flood = by_id["1104169"]
    assert (flood.event_type, flood.event_type_label) == ("FL", "洪水")
    assert flood.name == "Flood in Thailand"
    assert flood.country == "Thailand"
    assert flood.iso3 == "THA"
    assert flood.alert_score == 1
    assert flood.alert_level == "Green"
    # Green 语义是「未发布警报」⇒ 不映射成黄/蓝，凭空造一档就是 D-1 违例。
    assert flood.color_label == ""
    assert flood.from_at == datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
    assert flood.to_at == datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    assert flood.modified_at == datetime(2026, 9, 18, 6, 16, 34, tzinfo=timezone.utc)
    assert (flood.longitude, flood.latitude) == (pytest.approx(98.9954), pytest.approx(17.1054))

    kinds = Counter(item.event_type for item in outcome.items)
    assert kinds == {"WF": 84, "EQ": 9, "FL": 5, "TC": 2}
    assert all(item.event_type_label for item in outcome.items)  # 四码全覆盖


# ================================================================ 「缺关键字段 → 显式失败态」

def test_empty_envelope_is_always_failed_never_no_data() -> None:
    """五个解析入口吃 `{}` 必须全部判 FAILED——这是「不猜」的结构锁。"""
    parsers = (
        parse_nmc_alarm_page,
        parse_nmc_station_alarm,
        parse_icl_earlywarnings,
        parse_usgs_geojson,
        parse_gdacs_events,
    )
    for parse in parsers:
        outcome = parse({})
        assert outcome.state is FetchState.FAILED, parse.__name__
        assert outcome.items == (), parse.__name__
        assert outcome.reason, parse.__name__


def test_nmc_missing_page_and_non_zero_code_are_failed() -> None:
    payload = load_sample("nmc_findAlarm.sample.json")
    broken = copy.deepcopy(payload)
    del broken["data"]["page"]
    outcome = parse_nmc_alarm_page(broken)
    assert outcome.state is FetchState.FAILED
    assert outcome.reason == "missing_field:data.page"

    wrong_code = copy.deepcopy(payload)
    wrong_code["code"] = 500
    assert parse_nmc_alarm_page(wrong_code).reason.startswith("source_error:code=")

    not_list = copy.deepcopy(payload)
    not_list["data"]["page"]["list"] = {"oops": 1}
    assert parse_nmc_alarm_page(not_list).reason == "missing_field:data.page.list"


def test_nmc_zero_count_is_no_data_but_count_with_empty_page_is_failed() -> None:
    payload = load_sample("nmc_findAlarm.sample.json")

    truly_empty = copy.deepcopy(payload)
    truly_empty["data"]["page"]["list"] = []
    truly_empty["data"]["page"]["count"] = 0
    truly_empty["data"]["provinceAlarms"] = []
    empty_outcome = parse_nmc_alarm_page(truly_empty)
    assert empty_outcome.state is FetchState.NO_DATA
    assert empty_outcome.reason == "no_alarm_in_report"

    lying_page = copy.deepcopy(payload)
    lying_page["data"]["page"]["list"] = []
    lying_page["data"]["provinceAlarms"] = []  # count 仍自报 328
    lie_outcome = parse_nmc_alarm_page(lying_page)
    assert lie_outcome.state is FetchState.FAILED
    assert lie_outcome.reason.startswith("count_mismatch")


def test_nmc_entries_missing_alertid_are_dropped_not_padded() -> None:
    payload = load_sample("nmc_findAlarm.sample.json")
    payload["data"]["page"]["list"][0]["alertid"] = "   "
    payload["data"]["page"]["list"][1]["title"] = ""
    payload["data"]["page"]["list"][2] = "不是对象"
    outcome = parse_nmc_alarm_page(payload)
    assert outcome.state is FetchState.OK
    assert outcome.dropped == 3
    assert len(outcome.items) == 297
    assert all(item.alertid and item.title for item in outcome.items)


def test_nmc_station_alarm_missing_warn_is_failed() -> None:
    payload = load_sample("nmc_restWeather.sample.json")
    broken = copy.deepcopy(payload)
    del broken["data"]["real"]["warn"]
    outcome = parse_nmc_station_alarm(broken, stationid="Wqsps")
    assert outcome.state is FetchState.FAILED
    assert outcome.reason == "missing_field:data.real.warn"

    no_real = copy.deepcopy(payload)
    del no_real["data"]["real"]
    assert parse_nmc_station_alarm(no_real).reason == "missing_field:data.real"


def test_nmc_station_alarm_with_a_real_shaped_alert_parses() -> None:
    """把真样例的哨兵换成一条形态同源的在报预警（字段名全部来自真样例）。"""
    payload = load_sample("nmc_restWeather.sample.json")
    warn = payload["data"]["real"]["warn"]
    warn["alert"] = "北京市气象台发布大风蓝色预警信号"
    warn["signaltype"] = "大风"
    warn["signallevel"] = "蓝色"
    warn["issuetime"] = "2026/09/20 00:40"
    warn["url"] = "/publish/alarm/11000041600000_20260920004000.html"
    warn["pic"] = "https://image.nmc.cn/assets/img/alarm/p0005004.png"
    warn["issuecontent"] = "预计未来 12 小时内本市将出现六级以上阵风。"

    outcome = parse_nmc_station_alarm(payload, stationid="Wqsps")
    assert outcome.state is FetchState.OK
    (item,) = outcome.items
    assert item.alert_text == "北京市气象台发布大风蓝色预警信号"
    assert item.signal_type == "大风"
    assert item.signal_level == "蓝色"  # 标题颜色词优先，源端 signallevel 兜底
    assert item.issued_at == datetime(2026, 9, 20, 0, 40, tzinfo=BEIJING_TZ)
    assert item.url == "https://www.nmc.cn/publish/alarm/11000041600000_20260920004000.html"
    assert item.station_code == "Wqsps"
    assert item.station_text == "北京市 北京"


def test_icl_bad_envelope_and_dropped_entries() -> None:
    payload = load_sample("icl_earlywarnings.sample.json")

    wrong_code = copy.deepcopy(payload)
    wrong_code["code"] = 500
    assert parse_icl_earlywarnings(wrong_code).state is FetchState.FAILED

    not_list = copy.deepcopy(payload)
    not_list["data"] = {"eventId": 1}
    assert parse_icl_earlywarnings(not_list).reason == "bad_type:data"

    empty = copy.deepcopy(payload)
    empty["data"] = []
    no_data = parse_icl_earlywarnings(empty)
    assert no_data.state is FetchState.NO_DATA
    assert no_data.reason == "no_earlywarning_in_window"

    geoless = copy.deepcopy(payload)
    for entry in geoless["data"]:
        entry.pop("latitude", None)
    failed = parse_icl_earlywarnings(geoless)
    assert failed.state is FetchState.FAILED
    assert failed.reason == "all_entries_invalid"
    assert failed.dropped == 20


def test_usgs_features_missing_vs_null_magnitude_vs_magnitude_gate() -> None:
    payload = load_sample("usgs_all_hour.sample.geojson")

    no_features = copy.deepcopy(payload)
    del no_features["features"]
    assert parse_usgs_geojson(no_features).reason == "missing_field:features"

    # 真样例 4 条 mag 全 < 4.0 ⇒ 被震级门滤空 = 「确实没有满足条件的」，不是失败。
    gated = parse_usgs_geojson(payload, min_magnitude=4.0)
    assert gated.state is FetchState.NO_DATA
    assert gated.reason == "no_event_above_m4"
    assert gated.notes == ("filtered_out=4",)
    assert gated.total_hint == 4
    assert gated.transport_ok is True

    null_mag = copy.deepcopy(payload)
    for feature in null_mag["features"]:
        feature["properties"]["mag"] = None  # USGS 火山/非震条目常见形态
    dropped = parse_usgs_geojson(null_mag)
    assert dropped.state is FetchState.FAILED
    assert dropped.reason == "all_entries_invalid"
    assert dropped.dropped == 4

    empty_features = copy.deepcopy(payload)
    empty_features["features"] = []
    empty_features["metadata"]["count"] = 0
    assert parse_usgs_geojson(empty_features).state is FetchState.NO_DATA


def test_gdacs_missing_features_and_all_meta_only_payloads() -> None:
    payload = load_sample("gdacs_eventlist.sample.json")

    no_features = copy.deepcopy(payload)
    del no_features["features"]
    assert parse_gdacs_events(no_features).reason == "missing_field:features"

    junk_only = {"type": "FeatureCollection", "features": payload["features"][:1]}
    junk_outcome = parse_gdacs_events(junk_only)
    assert junk_outcome.state is FetchState.FAILED  # 唯一一条是元信息条目
    assert junk_outcome.reason == "all_entries_invalid"
    assert junk_outcome.dropped == 1

    empty = {"type": "FeatureCollection", "features": []}
    assert parse_gdacs_events(empty).state is FetchState.NO_DATA


# ================================================================ 取数失败 → 显式 FAILED

class Boom(Exception):
    """替身抛的网络异常（不出网）。"""


def _raising_fetch(exc: Exception):
    calls: list[str] = []

    def fetch(url: str) -> Any:
        calls.append(url)
        raise exc

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


@pytest.mark.parametrize(
    "runner,source_id",
    [
        (lambda f: fetch_nmc_alarms(fetch=f), "nmc"),
        (lambda f: fetch_nmc_station_alarm("Wqsps", fetch=f), "nmc"),
        (lambda f: fetch_icl_earthquakes(fetch=f), "icl"),
        (lambda f: fetch_usgs_recent_feed(fetch=f), "usgs"),
        (lambda f: fetch_usgs_quakes(fetch=f, now=datetime(2026, 9, 20, tzinfo=timezone.utc)), "usgs"),
        (lambda f: fetch_gdacs_events(fetch=f), "gdacs"),
    ],
)
def test_fetch_failure_never_becomes_no_data_or_ok(runner, source_id: str) -> None:
    for exc in (Boom("连接被掐断"), TimeoutError("读超时"), ValueError("非 JSON")):
        outcome = runner(_raising_fetch(exc))
        assert outcome.state is FetchState.FAILED, (source_id, type(exc).__name__)
        assert outcome.items == ()
        assert outcome.reason.startswith("http_error:")
        assert source_id in outcome.describe()
        # 反证：同一条链的失败绝不冒充「无预警/无地震」。
        assert outcome.state is not FetchState.NO_DATA


def test_two_kinds_of_empty_are_different_states() -> None:
    """同一入口两种「空」：源端自报零条目 ⇒ NO_DATA；接口炸 ⇒ FAILED。"""
    empty_payload = {
        "msg": "success",
        "code": 0,
        "data": {"page": {"count": 0, "list": []}, "provinceAlarms": []},
    }
    ok = fetch_nmc_alarms(fetch=lambda url: empty_payload)
    assert ok.state is FetchState.NO_DATA and ok.transport_ok

    dead = fetch_nmc_alarms(fetch=_raising_fetch(Boom("502")))
    assert dead.state is FetchState.FAILED and not dead.transport_ok


# ================================================================ 护栏与重试（真默认链路，零出网）

class GuardSpy:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.urls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.urls.append(url)
        return self.reason


def test_default_transport_passes_every_url_through_the_ssrf_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = load_sample("nmc_findAlarm.sample.json")
    seen: list[str] = []

    def fake_http_get_json(url: str, **kwargs: Any) -> Any:
        seen.append(url)
        assert kwargs.get("verify_ssl") is False  # nmc.cn 证书链不完整（nmc_weather.py:119 同口径）
        return payload

    guard = GuardSpy()
    monkeypatch.setattr(http_get, "guard_user_url", guard)
    monkeypatch.setattr(http_get, "http_get_json", fake_http_get_json)

    outcome = fetch_nmc_alarms()
    assert outcome.state is FetchState.OK
    assert len(outcome.items) == 300
    assert seen == [build_nmc_find_alarm_url()]
    assert guard.urls == seen  # 每次外呼之前都过了闸


def test_guard_rejection_stops_before_any_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(http_get, "guard_user_url", GuardSpy("该地址解析到内网/保留网段，已拒绝"))
    monkeypatch.setattr(
        http_get, "http_get_json", lambda url, **kw: calls.append(url) or {}
    )

    outcome = fetch_icl_earthquakes()
    assert outcome.state is FetchState.FAILED
    assert outcome.reason.startswith("ssrf_rejected:")
    assert calls == []  # 护栏拒绝 ⇒ 请求根本没发出去


def test_transient_failure_is_retried_then_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    sleeps: list[int] = []

    def fake_http_get_json(url: str, **kwargs: Any) -> Any:
        attempts.append(url)
        raise http_get.ParseHttpError("GET failed: timeout")

    monkeypatch.setattr(http_get, "guard_user_url", GuardSpy())
    monkeypatch.setattr(http_get, "http_get_json", fake_http_get_json)
    monkeypatch.setattr(http_get, "_backoff_sleep", lambda attempt: sleeps.append(attempt))

    outcome = fetch_gdacs_events(retry=3)
    assert outcome.state is FetchState.FAILED
    assert outcome.reason == "http_error:ParseHttpError"
    assert len(attempts) == 3  # 首试 + 2 次重试（判据同 stock_data.py:90）
    assert sleeps == [0, 1]  # 每次重试前退避一次
    assert outcome.attempts == 3


def test_whitelist_gate_rejects_hosts_outside_the_constant_list() -> None:
    check_whitelisted_url("https://earthquake.usgs.gov/fdsnws/event/1/query?x=1")
    with pytest.raises(SsrfRejectedError):
        check_whitelisted_url("https://attacker.example.com/nmc")
    with pytest.raises(SsrfRejectedError):
        check_whitelisted_url("http://127.0.0.1:8080/rest/findAlarm")
    with pytest.raises(SsrfRejectedError):
        check_whitelisted_url("file:///etc/passwd")
    with pytest.raises(SsrfRejectedError):
        guard_outbound_url("")


@pytest.mark.parametrize(
    "bad_id",
    ["../../etc/passwd", "Wqsps&admin=1", "a b", "", "x" * 65, "中文站点"],
)
def test_url_identifiers_are_sanitised_before_being_interpolated(bad_id: str) -> None:
    with pytest.raises(UnsafeIdentifier):
        build_nmc_alarm_detail_url(bad_id)
    # stationid 走取数门面时：形态非法 ⇒ 直接 FAILED，且一次外呼都不发。
    calls: list[str] = []

    def spy_fetch(url: str) -> Any:
        calls.append(url)
        return {}

    outcome = fetch_nmc_station_alarm(bad_id, fetch=spy_fetch)
    assert outcome.state is FetchState.FAILED
    assert outcome.reason.startswith("unsafe_stationid:")
    assert calls == []


def test_safe_identifiers_build_expected_urls() -> None:
    assert build_nmc_find_alarm_url(1, 300) == (
        "https://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=300"
    )
    assert build_nmc_rest_weather_url("Wqsps", timestamp_ms=1) == (
        "https://www.nmc.cn/rest/weather?stationid=Wqsps&_=1"
    )
    # E11 §5.2 实测 200 / 51,921B 的那一条详情页 URL，主键就在真样例里。
    assert build_nmc_alarm_detail_url("51178141600000_20260920002955") == (
        "https://www.nmc.cn/publish/alarm/51178141600000_20260920002955.html"
    )
    real_ids = [item["alertid"] for item in load_sample("nmc_findAlarm.sample.json")["data"]["page"]["list"]]
    assert "51178141600000_20260920002955" in real_ids


def test_every_builder_url_is_https_and_on_the_allowlist() -> None:
    urls = [
        build_nmc_find_alarm_url(),
        build_nmc_rest_weather_url("Wqsps"),
        build_nmc_alarm_detail_url("51178141600000_20260920002955"),
        build_icl_earlywarnings_url(),
        build_usgs_feed_url("all_hour"),
        build_usgs_fdsnws_url(
            start=datetime(2026, 9, 19, tzinfo=timezone.utc),
            end=datetime(2026, 9, 20, tzinfo=timezone.utc),
        ),
        gdacs_source.GDACS_EVENT_LIST_URL,
    ]
    for url in urls:
        assert url.startswith("https://"), url
        check_whitelisted_url(url)
    # 四个源 host 恰为常量白名单的四枚（E11 §2 矩阵实测 200 的 host）。
    hosts = {urlsplit(url).hostname for url in urls}
    assert hosts == set(ALLOWED_HOSTS)


# ================================================================ USGS 参数形态（实测坑回归）

def test_fdsnws_uses_min_max_four_params_and_never_bbox() -> None:
    url = build_usgs_fdsnws_url(
        start=datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc),
        min_magnitude=4.0,
        rect=CHINA_RECT,
    )
    assert "bbox" not in url  # 实测 400 Unknown parameter "bbox"（E11 §5.6）
    for piece in (
        "minlatitude=18.0",
        "minlongitude=73.0",
        "maxlatitude=54.0",
        "maxlongitude=135.0",
        "minmagnitude=4.0",
        "starttime=2026-09-19T00:00:00",
        "endtime=2026-09-20T00:00:00",
        "format=geojson",
    ):
        assert piece in url, piece
    # naive 输入按 UTC 读，不猜本地时区
    naive = build_usgs_fdsnws_url(
        start=NAIVE_START, end=NAIVE_END  # naive 入参：由上层按 UTC 读
    )
    assert "starttime=2026-09-19T00:00:00" in naive


def test_feed_window_is_a_closed_set() -> None:
    assert build_usgs_feed_url("all_hour").endswith("/summary/all_hour.geojson")
    with pytest.raises(ValueError):
        build_usgs_feed_url("../evil")
    assert fetch_usgs_recent_feed(window="nope").reason.startswith("bad_window:")


# ================================================================ 交叉核验（E11 §3 口径）

def test_crosscheck_on_real_samples_reports_unconfirmed_not_silently_picking_one() -> None:
    icl = parse_icl_earlywarnings(load_sample("icl_earlywarnings.sample.json"))
    usgs = parse_usgs_geojson(load_sample("usgs_all_hour.sample.geojson"))
    matches = crosscheck_quakes(icl.items, usgs.items)

    assert len(matches) == len(icl.items) + len(usgs.items)  # 两源各自都出一条，不吞
    assert all(match.confirmed is False for match in matches)
    assert all(match.secondary is None for match in matches)
    assert "未获第二源确认" in matches[0].footnote
    # 真样例事实：ICL 首条 2026-08-24、USGS 首条 2026-09-19 ⇒ 相差 26 天，配不上。
    assert matches[0].primary.source_id == "icl"


def test_crosscheck_pairs_the_same_event_and_shows_both_sources() -> None:
    primary = parse_icl_earlywarnings(load_sample("icl_earlywarnings.sample.json")).items[0]
    # 用真样例的同一批实测值造一条 USGS 侧条目（字段名与 usgs 真样例逐字一致）：
    # E11 §5.6 的 fdsnws 实测原文就是「273 km NNW of Dêqên, China M4.5」形态。
    twin = QuakeEvent(
        source_id="usgs",
        event_id="usp000abcd",
        origin_at=primary.origin_at + timedelta(minutes=12),
        magnitude=4.5,
        mag_type="mw",
        depth_km=10.0,
        epicenter_text="273 km NNW of Dêqên, China",
        latitude=primary.latitude + 0.05,
        longitude=primary.longitude,
        updates=None,
        station_count=8,
        url="https://earthquake.usgs.gov/earthquakes/eventpage/usp000abcd",
        status="automatic",
        label="USGS（美国地质调查局）",
    )
    (match,) = crosscheck_quakes([primary], [twin])
    assert match.confirmed is True
    assert match.secondary is twin
    assert match.time_delta_minutes == pytest.approx(12.0)
    assert match.distance_km is not None and match.distance_km < 200
    footnote = match.footnote
    assert "ICL（中国地震预警网联盟）" in footnote and "USGS" in footnote
    assert "3.9" in footnote and "4.5" in footnote  # 两源数值并列，不静默择一


def test_crosscheck_respects_the_radius_gate() -> None:
    far = QuakeEvent(
        source_id="usgs",
        event_id="x1",
        origin_at=datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc),
        magnitude=5.0,
        mag_type="mw",
        depth_km=10.0,
        epicenter_text="elsewhere",
        latitude=1.0,
        longitude=1.0,
        updates=None,
        station_count=None,
        url="",
        status="",
        label="USGS",
    )
    base = parse_icl_earlywarnings(load_sample("icl_earlywarnings.sample.json")).items[0]
    matches = crosscheck_quakes([base], [far])
    # 两条都要出（主源一条 + 核验源独有的一条），谁也不许被静默吞掉。
    assert len(matches) == 2
    assert all(match.confirmed is False for match in matches)
    assert matches[0].primary is base and matches[0].secondary is None


def test_nmc_issuetime_real_bytes_use_slashes() -> None:
    """真样例事实锁：findAlarm 的 issuetime 是 `YYYY/MM/DD HH:MM`（斜杠，0x2f）。

    E11 §5 把它转写成了短横；本席以磁盘字节为准并两种分隔符都收
    （`rest/weather` 的 `real.publish_time` 实测确实是短横）。
    现役 `weather.py:190` 从不解析该字段，所以这个差异一直没暴露。
    """
    raw = sample_bytes("nmc_findAlarm.sample.json")
    entry = json.loads(raw.decode("utf-8"))["data"]["page"]["list"][0]
    assert entry["issuetime"][4] == "/" and entry["issuetime"][7] == "/"
    assert parse_beijing_time(entry["issuetime"]) == datetime(
        2026, 9, 20, 0, 43, tzinfo=BEIJING_TZ
    )
    # 分隔符用码点写死，避免任何转写歧义：真样例 findAlarm 用斜杠、rest/weather 用短横。
    slash = b'"issuetime":"2026' + bytes([0x2F]) + b"09" + bytes([0x2F]) + b'20 00:43"'
    dash = b'"issuetime":"2026' + bytes([0x2D]) + b"09" + bytes([0x2D]) + b'20 00:43"'
    assert slash in raw
    assert dash not in raw


def test_nmc_publish_time_uses_dashes_and_still_parses() -> None:
    raw = sample_bytes("nmc_restWeather.sample.json")
    publish = json.loads(raw.decode("utf-8"))["data"]["real"]["publish_time"]
    assert publish[4] == "-"
    assert parse_beijing_time(publish) == datetime(
        2026, 9, 20, 0, 15, tzinfo=BEIJING_TZ
    )


def test_haversine_matches_known_arc_length() -> None:
    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, abs=0.2)
    assert haversine_km(39.9, 116.4, 39.9, 116.4) == pytest.approx(0.0)


# ================================================================ 标题解析与时间口径

@pytest.mark.parametrize(
    "title,kind,color",
    [
        ("湖南省湘西土家族苗族自治州保靖县气象台发布大雾黄色预警信号", "大雾", "黄色"),
        ("陕西省气象台发布地质灾害黄色预警", "地质灾害", "黄色"),
        ("辽宁省锦州市黑山县气象台发布大雾橙色预警信号", "大雾", "橙色"),
        ("四川省达州市万源市气象台发布暴雨黄色预警信号", "暴雨", "黄色"),
        ("北京市朝阳区发布雷电预警", "雷电", ""),  # 无颜色词 ⇒ 不猜（E11 §3）
        ("随手发的一条消息", "", ""),
    ],
)
def test_split_alarm_title_semantics(title: str, kind: str, color: str) -> None:
    assert split_alarm_title(title) == (kind, color)


def test_split_alarm_title_matches_every_real_title() -> None:
    for entry in load_sample("nmc_findAlarm.sample.json")["data"]["page"]["list"]:
        kind, color = split_alarm_title(entry["title"])
        assert color in {"蓝色", "黄色", "橙色", "红色"}
        assert kind and kind in entry["title"]
        assert color not in kind  # 颜色词不得混进类型段


def test_time_parsing_is_beijing_aware_and_rejects_garbage() -> None:
    assert parse_beijing_time("2026-09-20 00:43") == datetime(
        2026, 9, 20, 0, 43, tzinfo=BEIJING_TZ
    )
    assert parse_beijing_time("2026-09-20 00:43:07").second == 7
    for garbage in ("9999", "", "   ", "2026-13-45 99:99", "not-a-time"):
        assert parse_beijing_time(garbage) is None
    assert epoch_ms_to_utc("1787531181614") == datetime(
        2026, 8, 24, 0, 26, 21, 614000, tzinfo=timezone.utc
    )
    for garbage in (0, -1, "", "abc", 1e18):
        assert epoch_ms_to_utc(garbage) is None


# ================================================================ 状态机与零耦合结构锁

def test_outcome_helpers_never_imply_success_from_empty_items() -> None:
    outcome = parse_nmc_alarm_page(load_sample("nmc_findAlarm.sample.json"))
    assert outcome.has_items and outcome.transport_ok
    assert "state=ok" in outcome.describe()
    empty = parse_nmc_station_alarm(load_sample("nmc_restWeather.sample.json"))
    assert not empty.has_items and empty.transport_ok
    assert "state=no_data" in empty.describe()
    dead = parse_nmc_station_alarm({})
    assert "state=failed" in dead.describe() and "reason=" in dead.describe()


SOURCE_FILES = (
    Path(http_get.__file__),
    Path(nmc_alarm_source.__file__),
    Path(quake_source.__file__),
    Path(gdacs_source.__file__),
)


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(str(alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_sources_do_not_import_the_domain_model_of_the_parallel_seat() -> None:
    """接缝归属锁（原「零耦合锁」，D1-FIX 按规格 §8.1-6 处置=**保留意图、收窄手段**）。

    意图不变：采集器只做「payload/DTO + 三态」，不持 B1R3 的域模型，也不自己触闸
    （写它的四个源件当时正被并行席编辑，锁住边界才敢并行）。
    换掉的是手段：旧形态是三条 `not in source` **文本**断言，注释里提一句
    `EmergencyItem` 都会红，而且它把「接缝不存在」本身当成被保护物——真缝合时
    **没有任何测试**会因为绕过 `build_emergency_item` / `ReviewGate.submit` 而变红。
    现在按 AST 只判**代码**里的 import 与名字使用，并把投递面禁令一并写进来；
    「构造必须经内核公开口」的正向一半由
    `test_items_can_only_be_built_through_the_domain_factory`（本文件）与
    `tests/test_emergency_info_core.py` §G 锁 A/B/E 钉住。
    """
    forbidden_names = {
        "EmergencyItem",  # 域模型：只能经 build_emergency_item 造
        "build_emergency_item",
        "ReviewGate",
        "EmergencyStore",
        "SendRequest",  # 采集器不产投递请求，更不触闸
        "OutboundGate",
        "submit_active_push",
        "build_emergency_send_request",
    }
    for path in SOURCE_FILES:
        joined = "\n".join(_all_dotted_imports(path))
        assert "emergency_info.contracts" not in joined, path
        assert "emergency_info.service" not in joined, path
        assert "emergency_info.sources.store" not in joined, path
        used = _used_symbol_names(path)
        assert not (used & forbidden_names), (
            f"{path.name} 触碰了不属于采集层的名字：{sorted(used & forbidden_names)}"
        )
        roots = _imported_roots(path)
        assert "nonebot" not in roots, path
        assert "httpx" not in roots, path
        assert "requests" not in roots, path


def _used_symbol_names(path: Path) -> set[str]:
    """该文件**代码**里出现的名字（import 别名 / Name / 属性访问），docstring 不算。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                (alias.asname or alias.name.split(".")[0]) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update((alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            names.add(node.name)
    return names


# ---- 正向缝合锁（规格 §8.1：把「必须经内核」写清，取代「接缝缺失即安全」）----

def _item_construction_sites(root: Path | None = None) -> list[str]:
    """生产面里直接构造域模型的调用点：`EmergencyItem(...)` 与 `EmergencyItem.model_validate(...)`。

    `root` 可指向别的目录（变异自证用：拿 $TEMP 里的影子文件验本锁有没有眼睛），
    缺省=全仓生产面。
    """
    plugin_root = root or REPO_ROOT / "plugins" / "bot_unified_runtime"
    sites: list[str] = []
    for path in sorted(p for p in plugin_root.rglob("*.py") if "__pycache__" not in p.parts):
        text = path.read_text(encoding="utf-8")
        if "EmergencyItem" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            direct = isinstance(func, ast.Name) and func.id == "EmergencyItem"
            via_model = (
                isinstance(func, ast.Attribute)
                and func.attr == "model_validate"
                and isinstance(func.value, ast.Name)
                and func.value.id == "EmergencyItem"
            )
            if direct or via_model:
                sites.append(
                    f"{path.relative_to(plugin_root).as_posix()}:{node.lineno}"
                    f" {ast.unparse(func)}"
                )
    return sites


def test_items_can_only_be_built_through_the_domain_factory() -> None:
    """正向锁：全仓生产面构造 `EmergencyItem` 只有一条路＝`contracts.build_emergency_item`。

    这才是本条锁**应该**保护的东西：不关心源件认不认得内核，只钉「谁的构造口算数」。
    接线席落地后 import `build_emergency_item` 是**正确**的（不红）；自行
    `EmergencyItem(...)` / `EmergencyItem.model_validate(payload)` 一律红——那正是
    规格 §8.1 表第 1 行的破 **D-1** 形态：pydantic 之外多一条构造路，缺字段可以拿
    假 id / 假时间凑，「不成立即 None」被旁路成「源侧有啥就填啥」。
    """
    sites = _item_construction_sites()
    sanctioned = [s for s in sites if s.startswith(CONTRACTS_FILE_REL)]
    assert sanctioned, (
        f"{CONTRACTS_FILE_REL} 里已无 `EmergencyItem` 构造点＝安全构造口被搬走，"
        "本锁的锚点失效，请与本域一起改口径而不是删锁"
    )
    offenders = [s for s in sites if not s.startswith(CONTRACTS_FILE_REL)]
    assert offenders == [], f"绕过 `build_emergency_item` 的第二构造口：{offenders}"
    # 工厂必须是公开导出面（接线席照这个名字 import，别改名）。
    assert "build_emergency_item" in contracts.__all__
    assert "EmergencyItem" in contracts.__all__


@pytest.mark.xfail(
    strict=True,
    reason=(
        "接缝锁·前提未落地：三个源件 DTO 的 `to_payload()` 全仓 0 命中（规格 §8.1 强制路径"
        "第 2 格）。装配适配器席落地后删本标记转正。"
    ),
)
def test_source_dtos_expose_the_payload_the_domain_factory_consumes() -> None:
    """正向接缝锁：采集产物必须自带「喂得进工厂」的 payload，且绝不夹带审核状态。

    断言的是接缝**两端对得上**，不是「接缝存在」：
    - `to_payload()` 返回 Mapping，键必须落在 `EmergencyItem` 的字段集内（防自造别名）；
    - 不得自带 `status`（D-8：过审与否由 `ReviewGate` 判，报料侧自称 approved 一律红）；
    - 真样例条目经 `build_emergency_item` 至少能成立一条，成立者的
      `source_id/external_id/title` 与源件字段同源（不假填、不 1970）。
    """
    cases = (
        ("nmc", parse_nmc_alarm_page(load_sample("nmc_findAlarm.sample.json")).items, "alertid"),
        ("icl", parse_icl_earlywarnings(load_sample("icl_earlywarnings.sample.json")).items, "event_id"),
        ("gdacs", parse_gdacs_events(load_sample("gdacs_eventlist.sample.json")).items, "event_id"),
    )
    for expected_source, items, id_attr in cases:
        assert items, f"{expected_source} 夹具里没有条目，本锁不许空转"
        first_payload = items[0].to_payload()
        assert isinstance(first_payload, Mapping), expected_source
        unknown = set(first_payload) - set(EmergencyItem.model_fields)
        assert not unknown, f"{expected_source} 的 payload 含 EmergencyItem 没有的字段：{unknown}"
        assert first_payload.get("status", "pending") == "pending", (
            f"{expected_source} 不得自带审核状态（D-8）"
        )
        built = [build_emergency_item(item.to_payload()) for item in items]
        assert any(b is not None for b in built), (
            f"{expected_source} 整源一条也建不出来＝payload 与工厂字段不对齐"
        )
        for source_item, built_item in zip(items, built):
            if built_item is None:
                continue  # D-1：这条确实缺必需字段（如源端无时间），丢就是丢
            assert built_item.source_id == expected_source, built_item.source_id
            assert built_item.external_id == str(getattr(source_item, id_attr)).strip()
            assert built_item.title, built_item
            assert built_item.occurred_at.year > 2000, "拿 1970 凑时间＝造第二个事实源"
            assert built_item.status is EmergencyStatus.PENDING


def test_sources_reach_the_network_only_through_the_existing_http_and_guard_layer() -> None:
    """唯一外呼出口锁：只有 http_get.py 允许 import http_util / ssrf_guard。"""
    for path in SOURCE_FILES:
        modules = _all_dotted_imports(path)
        uses_http = any("parsers.http_util" in m for m in modules)
        uses_guard = any("parsers.ssrf_guard" in m for m in modules)
        if path.name == "http_get.py":
            assert uses_http and uses_guard, path
        else:
            assert not uses_http and not uses_guard, (
                f"{path.name} 绕过了共享取数件，直连 HTTP 层或护栏"
            )
        joined = "\n".join(modules)
        assert "urllib.request" not in joined, path  # 不自建第二套客户端


def _all_dotted_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(str(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_no_source_parses_is_reachable_without_the_transport_layer() -> None:
    """纯函数可达性锁：五个 parse 入口不需要任何 fetch/monkeypatch 即可测。"""
    payloads = (
        "nmc_findAlarm.sample.json",
        "nmc_restWeather.sample.json",
        "icl_earlywarnings.sample.json",
        "usgs_all_hour.sample.geojson",
        "gdacs_eventlist.sample.json",
    )
    for name in payloads:
        assert sample_bytes(name)[:1] in {b"{", b"["}, name


def test_alarm_alert_dataclass_is_a_plain_local_type_not_a_domain_model() -> None:
    """本席解析产物是本席文件内的普通 frozen dataclass（零耦合要求的正向证据）。"""
    assert AlarmAlert.__module__.endswith("sources.nmc_alarm")
    assert not hasattr(AlarmAlert, "model_validate")  # 不是 pydantic 域模型
    with pytest.raises(TypeError):
        AlarmAlert()  # 必需字段不给即 TypeError，不造空条目
    sample = AlarmAlert(
        alertid="a",
        title="t",
        kind="k",
        color_label="黄色",
        issued_at=None,
        issued_text="",
        url="",
        detail_url="",
        pic="",
    )
    assert sample.issued_at is None  # 无时间就是 None，不造 1970
