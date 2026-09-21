"""R3 停摆批：timesync HTTPS Date 兜底回归（全离线 mock，零真实网络）。

覆盖项：
- RFC 7231 Date 头解析（IMF-fixdate / 旧格式 naive 补 UTC / 畸形拒收）；
- HTTPS 偏移公式 θ = server + 0.5 − (t0+t3)/2（Date 1s 粒度量化居中）；
- 状态码/缺 Date/RTT 超限/非 https 端点拒收；
- 失败链 NTP→HTTPS→系统钟（每级一行日志；全败回退告警保留"回退系统钟"）；
- 偏移钳制复用（HTTPS 源漂移同样拒收）；
- configure_from 新键绑定（字段缺失=不启用，保住离线测试零网络语义）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.schedule.timesync import timesync


class FakeClock:
    """可手动推进的假钟（clock 与 monotonic 同源，存量测试同款）。"""

    def __init__(self, value: float) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class BrokenSocket:
    """UDP 123 被墙替身：sendto 必失败。"""

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendto(self, _data: bytes, _addr: object) -> int:
        raise OSError("udp 123 blocked")

    def close(self) -> None:
        return None


def _http_date(epoch: float) -> str:
    return format_datetime(
        datetime.fromtimestamp(epoch, tz=timezone.utc), usegmt=True
    )


def _build_sync(clock: FakeClock, *, http_factory=None, **kwargs):
    kwargs.setdefault("http_enabled", True)
    kwargs.setdefault("http_urls", ["https://a.example"])
    return timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=lambda: BrokenSocket(),
        http_factory=http_factory,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _reset_shared():
    timesync.reset_shared_for_tests()
    yield
    timesync.reset_shared_for_tests()


# ---------------------------------------------------------------- Date 解析


def test_parse_http_date_imf_fixdate() -> None:
    expected = datetime(1994, 11, 15, 8, 12, 31, tzinfo=timezone.utc).timestamp()
    assert timesync._parse_http_date("Tue, 15 Nov 1994 08:12:31 GMT") == expected


def test_parse_http_date_legacy_and_junk() -> None:
    # 旧格式（RFC 850）naive → 按 GMT 补 UTC。
    legacy = timesync._parse_http_date("Sunday, 06-Nov-94 08:49:37 GMT")
    expected = datetime(1994, 11, 6, 8, 49, 37, tzinfo=timezone.utc).timestamp()
    assert legacy == expected
    assert timesync._parse_http_date("") is None
    assert timesync._parse_http_date(None) is None
    assert timesync._parse_http_date("not a date at all") is None
    assert timesync._parse_http_date("Thu, 01 Jan 1970 00:00:00 GMT") is None


# ---------------------------------------------------------------- 偏移公式


def test_query_http_offset_formula_with_quantization_centering() -> None:
    clock = FakeClock(1_000_000.0)  # t0 = t3 = 1000000（假钟不自行走）。
    # Date 粒度 1s：服务器时刻 1000000.0 被截断下发 → +0.5s 居中后
    # offset = (1000000.0 + 0.5) − (1000000 + 1000000)/2 = +0.5。
    seen_urls: list[str] = []

    def factory(url: str, timeout: float) -> tuple[int, str]:
        seen_urls.append(url)
        assert timeout > 0
        return 200, _http_date(1_000_000.0)

    sync = _build_sync(clock, http_factory=factory)
    offset = sync._query_http("https://time.example/ping")
    assert offset == pytest.approx(0.5)
    assert seen_urls == ["https://time.example/ping"]


def test_query_http_rejects_bad_status_missing_date_and_long_rtt() -> None:
    clock = FakeClock(2_000_000.0)
    responses: list[tuple[int, str]] = [(500, ""), (200, ""), (200, _http_date(2_000_000.0))]
    calls: list[int] = []

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        calls.append(1)
        return responses[len(calls) - 1]

    sync = _build_sync(clock, http_factory=factory)
    assert sync._query_http("https://a.example") is None  # 500
    assert sync._query_http("https://a.example") is None  # 无 Date
    # RTT 超限：工厂内把假钟快进 >10s。
    def slow_factory(_url: str, _timeout: float) -> tuple[int, str]:
        clock.advance(11.0)
        return 200, _http_date(clock.value)

    sync._http_factory = slow_factory  # type: ignore[method-assign]
    assert sync._query_http("https://a.example") is None
    assert len(calls) == 2


def test_query_http_refuses_non_https_url_before_connect() -> None:
    clock = FakeClock(3_000_000.0)
    tried: list[str] = []

    def factory(url: str, _timeout: float) -> tuple[int, str]:
        tried.append(url)
        # 走真实工厂的 https 门（连不连网在门之后）：非 https 必抛 ValueError。
        return timesync._https_head_factory(url, _timeout)

    sync = _build_sync(clock, http_factory=factory)
    assert sync._query_http("http://time.example") is None
    assert sync._query_http("ftp://time.example") is None


# ---------------------------------------------------------------- 失败链


def test_chain_ntp_fail_then_https_success(caplog) -> None:
    clock = FakeClock(5_000_000.0)
    # Date 只有秒级粒度：server=本地钟值 → θ=+0.5（量化居中项本身）。
    # 可辨识的最小非零偏移即 ±0.5s 量级，±1.5s 钳制口径对其完全容纳。
    true_offset = 0.5

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        return 200, _http_date(clock.value + true_offset - 0.5)

    sync = _build_sync(clock, http_factory=factory, max_drift_ms=1500)
    with caplog.at_level(
        logging.INFO, logger="plugins.bot_unified_runtime.domains.schedule.timesync.timesync"
    ):
        corrected = sync.now()
    assert sync.offset_seconds is not None
    assert abs(sync.offset_seconds - true_offset) < 0.05
    expected = datetime.fromtimestamp(clock.value + true_offset).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.05
    messages = [record.message for record in caplog.records]
    assert any("转 HTTPS 时间源" in message for message in messages), messages
    assert any("HTTPS）校准成功" in message for message in messages), messages


def test_all_sources_fail_falls_back_to_system_clock(caplog) -> None:
    clock = FakeClock(6_000_000.0)

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        raise OSError("https blocked too")

    sync = _build_sync(clock, http_factory=factory)
    with caplog.at_level(
        logging.INFO, logger="plugins.bot_unified_runtime.domains.schedule.timesync.timesync"
    ):
        result = sync.now()
    assert sync.offset_seconds is None, "全失败必须回退系统钟（不留陈旧偏移）"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    messages = [record.message for record in caplog.records]
    assert any("回退系统钟" in message for message in messages), messages
    assert any("转 HTTPS 时间源" in message for message in messages), messages


def test_http_source_drift_rejected_by_existing_clamp(caplog) -> None:
    clock = FakeClock(7_000_000.0)

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        # 漂移 +100s：远超 ±1.5s 钳制，必须拒收（HTTPS 源与 NTP 同口径）。
        return 200, _http_date(clock.value + 100.0)

    sync = _build_sync(clock, http_factory=factory, max_drift_ms=1500)
    with caplog.at_level(
        logging.WARNING, logger="plugins.bot_unified_runtime.domains.schedule.timesync.timesync"
    ):
        sync.now()
    assert sync.offset_seconds is None
    assert any("超过可信上限" in record.message for record in caplog.records)


def test_http_disabled_never_touches_http_factory() -> None:
    clock = FakeClock(8_000_000.0)
    calls: list[int] = []

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        calls.append(1)
        return 200, _http_date(clock.value)

    sync = _build_sync(clock, http_factory=factory, http_enabled=False, http_urls=[])
    assert sync._http_enabled is False  # 显式关闭：HTTP 分支不启用。
    sync.now()  # NTP 全败（UDP 墙），HTTP 关 → 直接回退。
    assert calls == []
    assert sync.offset_seconds is None


# ---------------------------------------------------------------- 配置绑定


def test_configure_from_binds_http_keys_and_missing_means_disabled() -> None:
    enabled_config = SimpleNamespace(
        bot_time_sync_enabled=True,
        bot_time_sync_servers="ntp.aliyun.com",
        bot_time_sync_max_drift_ms=1500,
        bot_time_sync_http_enabled=True,
        bot_time_sync_http_url="https://time.example,https://back.example",
    )
    shared = timesync.configure_from(enabled_config)
    assert shared.enabled is True
    assert shared._http_enabled is True
    assert shared._http_urls == ["https://time.example", "https://back.example"]

    # 旧测试局部配置（无 http 字段）→ HTTP 兜底不启用（离线零网络语义不变）。
    legacy_config = SimpleNamespace(
        bot_time_sync_enabled=True,
        bot_time_sync_servers="ntp.aliyun.com",
        bot_time_sync_max_drift_ms=1500,
    )
    legacy = timesync.configure_from(legacy_config)
    assert legacy._http_enabled is False

    # url 留空 → 内置默认端点。
    default_url_config = SimpleNamespace(
        bot_time_sync_enabled=True,
        bot_time_sync_servers="ntp.aliyun.com",
        bot_time_sync_max_drift_ms=1500,
        bot_time_sync_http_enabled=True,
    )
    defaulted = timesync.configure_from(default_url_config)
    assert defaulted._http_urls == [
        part.strip()
        for part in timesync.DEFAULT_HTTP_TIME_URLS_RAW.split(",")
    ]
