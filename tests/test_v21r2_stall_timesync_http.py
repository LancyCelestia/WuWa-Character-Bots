"""R3 停摆批：timesync HTTPS Date 兜底回归（全离线 mock，零真实网络）。

覆盖项：
- RFC 7231 Date 头解析（IMF-fixdate / 旧格式 naive 补 UTC / 畸形拒收）；
- HTTPS 偏移公式 θ = server + 0.5 − (t0+t3)/2（Date 1s 粒度量化居中）；
- 状态码/缺 Date/RTT 超限/非 https 端点拒收；
- 失败链 **NTP → HTTPS → 多源互证 → 系统钟**（每级一行日志；回退行带本轮各枚被拒读数）；
- 偏移钳制复用（HTTPS 源漂移同样拒收）；
- configure_from 新键绑定（字段缺失=不启用，保住离线测试零网络语义）。
TS-CONSENSUS 互证族（2026-09-29）：``bot_time_sync_max_drift_ms=1500`` 是**单源**上限
而不是"可校正范围"——本机钟偏超过 1.5s 时，唯一正确的读数必然也超限，于是永久修不好
（离线现算：偏 1.4s 可校、1.6s 起每轮都以回退收场）。单源口径一字不动，另加一级互证：
数 **独立供应商**（``_vendor_key``＝host 末两节，不是数端点）、按**簇直径**（max−min，
不是锚点半径）判彼此离散 ≤1 个量化步长、每枚往返 ≤0.5s（建连落在采样窗内会把好钟报成
超限）、中位校正量 ≤60s（过外圈＝系统级故障，不是钟漂）、非有限数一律拒。
T2 驱动口径（2026-09-29）：本文件一律用 ``refresh()`` 驱动同步链、用 ``now()`` 验纯内存
读语义——``now()`` 已经不在调用线程联网，凡靠它驱动同步的用例都会变成赛跑。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.schedule.timesync import timesync

_LOGGER = "plugins.bot_unified_runtime.domains.schedule.timesync.timesync"


class FakeClock:
    """可手动推进的假钟（clock 与 monotonic 同源，存量测试同款）。"""

    def __init__(self, value: float) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class BrokenSocket:
    """NTP 不可达替身：sendto 必失败（本文件的用例都以 HTTPS 为主源）。"""

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendto(self, _data: bytes, _addr: object) -> int:
        raise OSError("ntp unreachable")

    def close(self) -> None:
        return None


def _http_date(epoch: float) -> str:
    return format_datetime(
        datetime.fromtimestamp(epoch, tz=timezone.utc), usegmt=True
    )


def _date_factory(
    clock: FakeClock, wanted: dict[str, float], *, latency: float = 0.0
) -> Callable[[str, float], tuple[int, str]]:
    """按 URL 报 Date 头，使 timesync 算出的偏移恰为 ``wanted[url]``（含量化居中项）。

    ``latency`` 演的是 DNS+TCP+TLS **建连**：它整段落进 t0..t3 采样窗，而 Date 是
    建连之后才生成的，所以慢链路会把一个分毫不差的钟**虚报**成偏移（09-29 实测
    3s 建连即把本机好钟报过 ±1.5s 单源上限）。``wanted`` 已经是"被抬高之后的读数"，
    判互证资格时用的 ``round_trip`` 则恰为 ``latency``——那 0.5s 那道尺就是为它立的。

    ⚠ ``Date`` 只有**整秒**粒度（RFC 7231），所以不是任何数都报得出来：
    ``t0`` 取整秒时，可表读数恰为 ``整数 + (0.5 − latency/2)`` 那一格——
    ``latency=0`` ⇒ 读数只能是 ``x.5``；``latency=3`` ⇒ 读数才是整数。落在格子外
    会被这里当场抛，宁可测试写错数据，也不要静默少 0.5s 之后去猜为什么。
    """

    def factory(url: str, _timeout: float) -> tuple[int, str]:
        t0 = clock.value
        server_epoch = t0 + latency / 2.0 + wanted[url] - 0.5
        if abs(server_epoch - round(server_epoch)) > 1e-9:
            raise AssertionError(
                f"wanted={wanted[url]!r} latency={latency!r} 落在 Date 整秒格子外"
                f"（可表读数＝整数 + {0.5 - latency / 2.0:+}）"
            )
        clock.advance(latency)
        return 200, _http_date(round(server_epoch))

    return factory


def _spawn_recorder(log: list) -> Callable[[Callable[[], None]], None]:
    """``thread_starter`` 替身：只记"派了一轮"，不在测试线程跑、也不起真线程。

    不跑就得把单飞闸还回去（闸的语义＝"有一轮在飞"，替身里没有那一级）；对未
    持有的锁 ``release()`` 会抛 ``RuntimeError``，所以这枚替身同时也是"派发口
    确实取过闸"的反证。
    """

    def start(target: Callable[[], None]) -> None:
        log.append(("spawn",))
        owner = getattr(target, "__self__", None)
        if owner is None:
            raise AssertionError("派发替身拿不到 worker 归属实例：传参形态变了，重新对账")
        owner._sync_in_flight.release()

    return start


def _build_sync(
    clock: FakeClock, *, http_factory=None, **kwargs
) -> tuple[timesync.TimeSync, list]:
    """默认注入"只记账不跑"的派发替身：凡读 ``now()`` 的用例都因此零网络。"""
    log: list = []
    kwargs.setdefault("http_enabled", True)
    kwargs.setdefault("http_urls", ["https://a.example"])
    return (
        timesync.TimeSync(
            ["a.example"],
            clock=clock,
            monotonic=clock,
            socket_factory=lambda: BrokenSocket(),
            http_factory=http_factory,
            thread_starter=_spawn_recorder(log),
            **kwargs,
        ),
        log,
    )


def _urls(*hosts: str) -> list[str]:
    return [f"https://{host}" for host in hosts]


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

    sync, _log = _build_sync(clock, http_factory=factory)
    # 2026-09-29 起返回 (偏移, 往返)：往返是互证那级的资格尺，不再单独抛一个数。
    measured = sync._query_http("https://time.example/ping")
    assert measured is not None
    offset, round_trip = measured
    assert offset == pytest.approx(0.5)
    assert round_trip == pytest.approx(0.0)  # 假钟不自行走 ⇒ 这一枚往返为 0。
    assert seen_urls == ["https://time.example/ping"]


def test_query_http_rejects_bad_status_missing_date_and_long_rtt() -> None:
    clock = FakeClock(2_000_000.0)
    responses: list[tuple[int, str]] = [
        (500, ""),
        (200, ""),
        (200, _http_date(2_000_000.0)),
    ]
    calls: list[int] = []

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        calls.append(1)
        return responses[len(calls) - 1]

    sync, _log = _build_sync(clock, http_factory=factory)
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

    sync, _log = _build_sync(clock, http_factory=factory)
    assert sync._query_http("http://time.example") is None
    assert sync._query_http("ftp://time.example") is None


def test_date_factory_produces_the_declared_offset() -> None:
    """本文件的互证用例全靠这把尺：读数与往返必须如字面可控。"""
    clock = FakeClock(4_000_000.0)
    polluted, _log = _build_sync(
        clock,
        http_factory=_date_factory(clock, {"https://a.example": 2.0}, latency=3.0),
    )
    measured = polluted._query_http("https://a.example")
    assert measured is not None
    assert measured[0] == pytest.approx(2.0), "读数＝声明值，建连抬高已含在内"
    assert measured[1] == pytest.approx(3.0), "互证资格用的往返＝建连那 3s"

    # 干净腿只能落在 x.5 格上（Date 整秒粒度 + 0.5s 居中项）。
    clean_clock = FakeClock(4_500_000.0)
    clean, _l2 = _build_sync(
        clean_clock, http_factory=_date_factory(clean_clock, {"https://a.example": 4.5})
    )
    assert clean._query_http("https://a.example") == pytest.approx((4.5, 0.0))


# ---------------------------------------------------------------- 失败链


def test_chain_ntp_fail_then_https_success(caplog) -> None:
    clock = FakeClock(5_000_000.0)
    # Date 只有秒级粒度：server=本地钟值 → θ=+0.5（量化居中项本身）。
    # 可辨识的最小非零偏移即 ±0.5s 量级，±1.5s 钳制口径对其完全容纳。
    true_offset = 0.5

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        return 200, _http_date(clock.value + true_offset - 0.5)

    sync, _log = _build_sync(clock, http_factory=factory, max_drift_ms=1500)
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        sync.refresh()
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

    sync, _log = _build_sync(clock, http_factory=factory)
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        sync.refresh()
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

    sync, _log = _build_sync(clock, http_factory=factory, max_drift_ms=1500)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None
    assert any("超过可信上限" in record.message for record in caplog.records)


def test_http_disabled_never_touches_http_factory() -> None:
    clock = FakeClock(8_000_000.0)
    calls: list[int] = []

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        calls.append(1)
        return 200, _http_date(clock.value)

    sync, _log = _build_sync(
        clock, http_factory=factory, http_enabled=False, http_urls=[]
    )
    assert sync._http_enabled is False  # 显式关闭：HTTP 分支不启用。
    sync.refresh()  # NTP 全败（不可达替身），HTTP 关 → 直接回退。
    assert calls == []
    assert sync.offset_seconds is None


# ---------------------------------------------------------------- TS-CONSENSUS


def test_single_uncorroborated_source_still_refused(caplog) -> None:
    """单源口径一字未动：一枚超限读数就是拒收，互证那一级不替孤证开门。"""
    clock = FakeClock(9_000_000.0)
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(clock, {"https://www.baidu.com": 4.5}),
        http_urls=_urls("www.baidu.com"),
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None, "孤证超 ±1.5s 必须拒收（放宽的那一级要两家）"
    messages = [record.message for record in caplog.records]
    assert any("超过可信上限" in message for message in messages), messages
    assert not any("多源互证采纳" in message for message in messages), messages


def test_consensus_adopts_independent_pair_and_ignores_the_liar(caplog) -> None:
    """两家独立供应商彼此差一个量化步长 ⇒ 采纳中位数 4.0；说谎的第三家不进簇。"""
    clock = FakeClock(10_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com", "liar.example.net")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {
                "https://www.baidu.com": 3.5,
                "https://www.qq.com": 4.5,
                "https://liar.example.net": -30.5,  # 离簇 34s：不参与共识
            },
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds == pytest.approx(4.0), "采纳的必须是那一对的中位数"
    messages = [record.message for record in caplog.records]
    agreement = [m for m in messages if "多源互证采纳" in m]
    assert agreement, messages
    assert "彼此离散 1.000s" in agreement[0], agreement[0]
    assert "liar.example.net" not in agreement[0], agreement[0]


def test_three_independent_vendors_agreeing_is_adopted(caplog) -> None:
    """三家彼此都在一个量化步长内 ⇒ 直径 1.000s、取中位（数的是供应商，不是端点）。"""
    clock = FakeClock(11_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com", "time.example.net")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {
                "https://www.baidu.com": 3.5,
                "https://www.qq.com": 4.5,
                "https://time.example.net": 4.5,
            },
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds == pytest.approx(4.5), "三家成簇取中位，不是取最大"
    line = [r.message for r in caplog.records if "多源互证采纳" in r.message]
    assert line and "彼此离散 1.000s" in line[0], line
    for host in ("www.baidu.com", "www.qq.com", "time.example.net"):
        assert host in line[0], line[0]


def test_same_vendor_two_hosts_cannot_corroborate(caplog) -> None:
    """同家两个子域一起错＝伪造共识（taobao 边缘缓存那一形）：判据数的是供应商。"""
    clock = FakeClock(12_000_000.0)
    urls = _urls("img1.taobao.com", "img2.taobao.com")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {"https://img1.taobao.com": 4.5, "https://img2.taobao.com": 4.5},
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None, "同家两台一致不足以突破单源上限"
    assert not any("多源互证采纳" in r.message for r in caplog.records)


def test_vendor_key_folds_endpoint_names_to_vendors() -> None:
    """``_vendor_key`` 是本族判据的地基：折错了整级互证就是空话。"""
    assert timesync._vendor_key("https://www.baidu.com") == "baidu.com"
    assert timesync._vendor_key("https://baidu.com") == "baidu.com"
    assert timesync._vendor_key("HTTPS://WWW.BAIDU.COM/path?x=1") == "baidu.com"
    assert timesync._vendor_key("https://img1.taobao.com") == timesync._vendor_key(
        "https://img2.taobao.com"
    )
    assert timesync._vendor_key("ntp.aliyun.com") == "aliyun.com"
    assert timesync._vendor_key("https://www.qq.com") != timesync._vendor_key(
        "https://www.baidu.com"
    )
    assert timesync._vendor_key("") == ""
    assert timesync._vendor_key(None) == ""
    # IPv4 字面量没有"厂商"可读：整串当一家（本函数已知边界，模块 docstring 写明）。
    assert timesync._vendor_key("http://192.168.1.20/") == "192.168.1.20"


def test_disagreeing_pair_does_not_fabricate_consensus(caplog) -> None:
    """两家的读数彼此差两个量化步长 ⇒ 谁也没被证实，回退系统钟。"""
    clock = FakeClock(13_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {"https://www.baidu.com": 2.5, "https://www.qq.com": 4.5},
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None, "直径 2.0s > 1.0s 那道尺，不得成簇"
    assert not any("多源互证采纳" in r.message for r in caplog.records)


def test_cluster_diameter_is_enforced_not_anchor_radius(caplog) -> None:
    """直径口径（max−min）而非锚点半径：把判据换成锚点半径，本枚当场打红。

    三枚读数 2.5/3.5/4.5 分属三家（Date 只有整秒，可表读数落在 x.5 这一格）：
    - 锚点半径口径会把三枚连成一簇（各自离中位 3.5 都 ≤1.0）⇒ 采纳 3.5、
      而它自己印出来的"彼此离散"是 2.000s——等于把这条尺放宽一倍还自称 1s；
    - 直径口径只能取到 [2.5, 3.5]（或 [3.5, 4.5]）这一对 ⇒ 采纳 3.0、
      并如实印出 1.000s。
    两件事都钉：采纳值 3.0、日志里的离散恰为 1.000s。
    """
    clock = FakeClock(14_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com", "time.example.net")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {
                "https://www.baidu.com": 2.5,
                "https://www.qq.com": 3.5,
                "https://time.example.net": 4.5,
            },
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    line = [r.message for r in caplog.records if "多源互证采纳" in r.message]
    assert line, "两枚同族读数为真时本级该放行（别把判据写死成永拒）"
    assert "彼此离散 1.000s" in line[0], f"直径口径被写成锚点半径就会印 2.000s：{line[0]}"
    assert sync.offset_seconds == pytest.approx(3.0), (
        "采纳值必须来自直径 ≤1.0s 的那一簇（锚点半径口径会给出 3.5）"
    )


def test_latency_polluted_pair_is_not_allowed_to_corroborate(caplog) -> None:
    """建连耗时落在采样窗内：两枚一致但往返 3s 的读数没有互证资格。"""
    clock = FakeClock(15_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {"https://www.baidu.com": 2.0, "https://www.qq.com": 2.0},
            latency=3.0,  # DNS+TCP+TLS 建连 3s：分毫不差的钟也会被报成 +2.0
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None, (
        "往返 >0.5s 的读数已被建连污染，一致也不算互证（那是同一条慢链路，不是一口钟）"
    )
    assert not any("多源互证采纳" in r.message for r in caplog.records)


def test_consensus_refuses_correction_beyond_outer_bound(caplog) -> None:
    """外圈 60s：过了就不是钟漂而是系统级故障 ⇒ 拒收、回退、点名告警。"""
    clock = FakeClock(16_000_000.0)
    urls = _urls("www.baidu.com", "www.qq.com")
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {"https://www.baidu.com": 300.5, "https://www.qq.com": 301.5},
        ),
        http_urls=urls,
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None
    messages = [record.message for record in caplog.records]
    assert any("超过最大校正量" in m and "不做校正" in m for m in messages), messages
    assert not any("多源互证采纳" in m for m in messages), messages


def test_non_finite_offset_is_never_committed(caplog) -> None:
    """非有限数（NaN/±Inf）两处写腿都不许落库：NaN 尤其阴——钳制那道尺对它恒不成立。"""
    clock = FakeClock(17_000_000.0)
    sync, _log = _build_sync(clock, max_drift_ms=1500)
    rejects: list[timesync._Sample] = []
    for bogus in (float("nan"), float("inf"), float("-inf")):
        assert not sync._apply_offset(
            timesync._Sample(bogus, 0.1, "https://www.baidu.com", "HTTPS"), rejects
        ), bogus
    assert sync.offset_seconds is None, "NaN 不得被当成'在限内'成功提交"
    assert rejects == [], "垃圾读数不是'超限读数'，不许冒充互证的证据"

    # 互证腿同样不收：两枚 NaN 摆在一起也组不成簇。
    assert (
        sync._consensus_offset(
            [
                timesync._Sample(float("nan"), 0.1, "https://www.baidu.com", "HTTPS"),
                timesync._Sample(float("nan"), 0.1, "https://www.qq.com", "HTTPS"),
            ]
        )
        is None
    )

    # 端到端：把取数腿整个换成 NaN 读数，整轮必须落回系统钟而不是顶着一个坏偏移。
    sync._query_http = lambda _url: (float("nan"), 0.1)  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None
    assert any("非有限" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]


def test_fallback_warning_now_carries_the_rejected_readings(caplog) -> None:
    """回退行必须把本轮每枚被拒读数点名出来（"到底是谁在说谎"问得出来）。"""
    clock = FakeClock(18_000_000.0)
    sync, _log = _build_sync(
        clock,
        http_factory=_date_factory(
            clock,
            {"https://www.baidu.com": 3.5, "https://www.qq.com": -2.5},
        ),
        http_urls=_urls("www.baidu.com", "www.qq.com"),
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    fallback = [r.message for r in caplog.records if "回退系统钟" in r.message]
    assert fallback, [r.message for r in caplog.records]
    line = fallback[0]
    assert "https://www.baidu.com=+3.500s/0.000s" in line, line
    assert "https://www.qq.com=-2.500s/0.000s" in line, line


def test_consensus_fallback_when_every_source_is_unreachable(caplog) -> None:
    """没有任何读数时不许凭空造共识：回退行如实写"无一个源应答"。"""
    clock = FakeClock(19_000_000.0)

    def factory(_url: str, _timeout: float) -> tuple[int, str]:
        raise OSError("all blocked")

    sync, _log = _build_sync(
        clock,
        http_factory=factory,
        http_urls=_urls("www.baidu.com", "www.qq.com"),
        max_drift_ms=1500,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    assert sync.offset_seconds is None
    fallback = [r.message for r in caplog.records if "回退系统钟" in r.message]
    assert fallback and "<无一个源应答>" in fallback[0], fallback


def test_refresh_respects_the_single_flight_gate() -> None:
    """闸被占：``refresh()`` 与派发口都立刻返回，不发网络、不写状态、不吞闸位。"""
    clock = FakeClock(20_000_000.0)
    hits: list[int] = []

    sync, log = _build_sync(
        clock,
        http_factory=_counting_factory(clock, hits, {"https://a.example": 0.5}),
        max_drift_ms=1500,
    )
    assert sync._sync_in_flight.acquire(blocking=False), "闸应当初始可用"
    try:
        sync.refresh()
        sync._maybe_sync()
    finally:
        sync._sync_in_flight.release()
    assert hits == [], "闸被占时 HTTP 腿一次都不许被走"
    assert log.count(("spawn",)) == 0, "闸被占时派发口也不许派第二轮"
    assert sync.offset_seconds is None

    sync.refresh()
    assert hits, "闸空出来后正常那一轮要能跑"
    assert sync.offset_seconds == pytest.approx(0.5)
    assert not sync._sync_in_flight.locked(), "refresh 必须 try/finally 归还闸位"


def _counting_factory(
    clock: FakeClock, hits: list[int], wanted: dict[str, float]
) -> Callable[[str, float], tuple[int, str]]:
    inner = _date_factory(clock, wanted)

    def factory(url: str, timeout: float) -> tuple[int, str]:
        hits.append(1)
        return inner(url, timeout)

    return factory


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


def test_default_http_time_urls_are_two_distinct_vendors() -> None:
    """内置默认表真身：taobao 因 ``Date`` 自己错被移出，只剩两枚**不同供应商**。

    互证要的是"两家独立说同一件事"，不是"多堆端点"——同家两台一起错会伪造共识
    （见 ``test_same_vendor_two_hosts_cannot_corroborate``），所以这张表的判据是
    供应商数，端点数顶不了数。
    """
    raw = timesync.DEFAULT_HTTP_TIME_URLS_RAW
    assert raw == "https://www.baidu.com,https://www.qq.com"
    urls = [item.strip() for item in raw.split(",") if item.strip()]
    assert len({timesync._vendor_key(url) for url in urls}) == len(urls) == 2
    assert "taobao" not in raw
