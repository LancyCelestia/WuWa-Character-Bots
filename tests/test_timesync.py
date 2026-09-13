"""联网授时（runtime/timesync）回归：全离线 mock socket。

覆盖（用户裁定验收：成功/超时轮转/全败回退三例）：
- 同步成功：偏移被应用且进程内缓存（第二次 now() 不再联网）；
- 超时轮转：首台超时后自动换下一台，取首个成功；
- 全失败：回退系统钟 + 告警（偏移清空）；
- 偏移可信度：超 max_drift 的应答拒收；禁用时零联网。
安全席小修包回归（2026-09-13，A12 收编）：
- M-2 病态时钟兜底不再上穿（fallback 自身再包一层 → 系统 datetime.now()）；
- M-3 畸形包 fuzz：1970 前编码/全零串时间戳拒收（挡在钳制之前）；
- M-4 max_drift_ms=0 = 取默认钳制，不是关掉不设防；
- M-8 mode=5 broadcast 默认拒收，测试替身须显式 allow_broadcast_mode。
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime

from plugins.bot_unified_runtime.runtime import timesync

_NTP_DELTA = 2208988800


class FakeClock:
    """可控 Unix 秒钟（recvfrom 前后由测试推进）。"""

    def __init__(self, start: float) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSocket:
    """按剧本逐台演：Exception=该台失败；bytes=该台应答。"""

    def __init__(self, script: list, log: list, clock: FakeClock) -> None:
        self._script = script
        self._log = log
        self._clock = clock
        self.addr: tuple[str, int] | None = None

    def settimeout(self, value: float) -> None:
        self._log.append(("timeout", value))

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self._log.append(("send", addr[0]))
        assert len(data) == 48, "SNTP 请求必须是 48 字节"
        assert addr[1] == 123
        self.addr = addr

    def recvfrom(self, size: int) -> tuple[bytes, tuple]:
        action = self._script.pop(0)
        self._clock.advance(0.05)  # 网络往返 50ms。
        if isinstance(action, Exception):
            raise action
        if callable(action):
            return action(self.addr), self.addr or ("203.0.113.7", 123)
        return action, self.addr or ("203.0.113.7", 123)

    def close(self) -> None:
        self._log.append(("close",))


def ntp_response(server_time: float) -> bytes:
    """构造服务端应答（t1=t2=server_time；stratum=2；mode=4）。"""
    packet = bytearray(48)
    packet[0] = 0x24  # LI=0, VN=4, Mode=4(server)
    packet[1] = 2  # stratum
    def _pack(value: float) -> bytes:
        seconds = int(value) + _NTP_DELTA
        fraction = int((value - int(value)) * 2**32)
        return struct.pack("!II", seconds, fraction)
    packet[32:40] = _pack(server_time)
    packet[40:48] = _pack(server_time)
    return bytes(packet)


def _build(script: list, clock: FakeClock, **kwargs) -> tuple[timesync.TimeSync, list]:
    log: list = []
    sync = timesync.TimeSync(
        ["a.example", "b.example", "c.example"],
        clock=clock,
        monotonic=clock,  # 复用一个假钟驱动缓存窗口。
        socket_factory=lambda: FakeSocket(script, log, clock),
        **kwargs,
    )
    return sync, log


def test_sync_success_applies_offset_and_caches() -> None:
    clock = FakeClock(1_000_000.0)
    true_offset = 30.0  # 本地钟慢 30 秒。

    def response(_addr):
        # t3 = t0 + 0.05（FakeSocket.advance）；取客户端中点 = t3 - 0.025。
        return ntp_response(clock.value - 0.025 + true_offset)

    script: list = [response]
    # 大偏移（30s）是本例主角：钳制上限必须放大到放行（默认 1.5s 会拒收）。
    sync, log = _build(script, clock, resync_seconds=600.0, max_drift_ms=60_000)
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + true_offset).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    assert ("send", "a.example") in log
    assert script == [], "成功后剧本应耗尽"
    # 缓存生效：第二次 now() 不再联网（剧本已空，再联网会抛 IndexError→按失败计）。
    clock.advance(60.0)
    again = sync.now()
    assert abs((again - corrected).total_seconds() - 60.0) < 0.2
    assert sync.offset_seconds is not None and abs(sync.offset_seconds - true_offset) < 0.2


def test_timeout_rotates_to_next_server() -> None:
    clock = FakeClock(2_000_000.0)
    true_offset = -5.0  # 本地钟快 5 秒。

    def response(_addr):
        return ntp_response(clock.value - 0.025 + true_offset)

    script: list = [TimeoutError("timed out"), response]
    sync, log = _build(script, clock, max_drift_ms=60_000)  # 偏移 -5s 需放大钳制。
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + true_offset).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers == ["a.example", "b.example"], "首台超时应轮转到第二台"


def test_all_servers_fail_falls_back_to_system_clock(caplog) -> None:
    clock = FakeClock(3_000_000.0)
    script: list = [
        TimeoutError("a"),
        TimeoutError("b"),
        OSError("network unreachable"),
    ]
    sync, log = _build(script, clock, retry_seconds=300.0)
    with caplog.at_level(logging.WARNING, logger="plugins.bot_unified_runtime.runtime.timesync"):
        result = sync.now()
    assert sync.offset_seconds is None, "全失败必须回退系统钟（不留陈旧偏移）"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    assert any("回退系统钟" in record.message for record in caplog.records)
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers == ["a.example", "b.example", "c.example"]
    # 失败冷却：冷却期内不再逐消息重试（不再发起新请求）。
    clock.advance(60.0)
    sync.now()
    sent_after = [item[1] for item in log if item[0] == "send"]
    assert sent_after == sent_servers


def test_oversized_drift_response_rejected() -> None:
    clock = FakeClock(4_000_000.0)

    def bad_response(_addr):
        return ntp_response(clock.value + 7200.0)  # 偏移 2 小时：不可信。

    def good_response(_addr):
        return ntp_response(clock.value - 0.025 + 1.0)

    script: list = [bad_response, good_response]
    sync, log = _build(script, clock, max_drift_ms=1500)
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers == ["a.example", "b.example"], "超漂移应答应被拒收并换台"


def test_disabled_never_touches_network() -> None:
    clock = FakeClock(5_000_000.0)
    sync, log = _build([], clock, enabled=False)
    result = sync.now()
    assert log == [], "禁用态必须零联网"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05


def test_configure_from_gate_and_shared_now() -> None:
    """缺字段的测试 config = 禁用（零联网）；显式字段才启用。"""
    from types import SimpleNamespace

    timesync.reset_shared_for_tests()
    try:
        offline_config = SimpleNamespace(bot_notes_db_path="x")  # 无 time_sync 字段。
        shared = timesync.configure_from(offline_config)
        assert shared.enabled is False
        before = datetime.now().astimezone()
        result = timesync.now()
        assert abs((result - before).total_seconds()) < 5

        online_config = SimpleNamespace(
            bot_time_sync_enabled=True,
            bot_time_sync_servers="a.example,b.example",
            bot_time_sync_max_drift_ms=1500,
        )
        shared = timesync.configure_from(online_config)
        assert shared.enabled is True
        # 签名不变复用同一实例。
        assert timesync.configure_from(online_config) is shared
    finally:
        timesync.reset_shared_for_tests()


# ---------- 安全席小修包回归（2026-09-13 A12 收编） ----------


def _raw_packet(seconds: int, fraction: int = 0, *, mode: int = 4, stratum: int = 2) -> bytes:
    """手搓原始应答包（绕过 ntp_response 的正常时间编码）。"""
    packet = bytearray(48)
    packet[0] = (0x20 | mode) if mode <= 7 else 0x24  # LI=0, VN=4, mode 位。
    packet[1] = stratum
    raw = struct.pack("!II", seconds, fraction)
    packet[32:40] = raw
    packet[40:48] = raw
    return bytes(packet)


def test_malformed_pre_1970_timestamp_rejected_before_clamp() -> None:
    """畸形包 fuzz①a：1970 前（seconds < _NTP_DELTA）直接拒收（M-3）。

    钳制上限刻意放到天文级（3e9 秒），证明拒收是 M-3 的解包门干的、
    不是漂移钳制兜的底——否则回归锁不住修的点。
    """
    clock = FakeClock(6_000_000.0)

    def good_response(_addr):
        return ntp_response(clock.value - 0.025 + 1.0)

    script: list = [
        _raw_packet(_NTP_DELTA - 3600),  # 1969-12-31T23:00:00Z：贴 NTP 纪元。
        good_response,
    ]
    sync, log = _build(script, clock, max_drift_ms=3_000_000_000_000)
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers == ["a.example", "b.example"], "1970 前编码应答应在解包门被拒"


def test_malformed_exact_1970_timestamp_rejected() -> None:
    """畸形包 fuzz①b：恰好 1970-01-01 整编码（unix=0）在解包门被拒（M-3）。"""
    clock = FakeClock(6_500_000.0)
    script: list = [_raw_packet(_NTP_DELTA)]
    sync, log = _build(script, clock)
    result = sync.now()
    assert sync.offset_seconds is None, "1970 整点编码不得产生任何偏移"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers and sent_servers[0] == "a.example", (
        "拒收发生在首台应答侧；后续台只是轮转（剧本空=按失败计）"
    )


def test_malformed_zero_string_timestamp_rejected() -> None:
    """畸形包 fuzz②：时间戳字段全零串拒收，不落成巨大偏移（M-3）。"""
    clock = FakeClock(7_000_000.0)
    script: list = [_raw_packet(0, 0)]
    sync, log = _build(script, clock)
    result = sync.now()
    assert sync.offset_seconds is None
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    assert any(item[0] == "send" for item in log), "请求确实发出过（拒收发生在应答侧）"


def test_broadcast_mode5_rejected_by_default_flag_admits() -> None:
    """畸形包 fuzz③：mode=5 broadcast 默认拒收（M-8）；显式开关才放开。"""
    clock = FakeClock(8_000_000.0)

    def mode5_response(_addr):
        packet = bytearray(ntp_response(clock.value - 0.025 + 1.0))
        packet[0] = (packet[0] & 0xF8) | 0x05  # 模式位改 5（broadcast）。
        return bytes(packet)

    sync, _log = _build([mode5_response], clock, max_drift_ms=60_000)
    sync.now()
    assert sync.offset_seconds is None, "生产默认必须拒收 broadcast 应答"

    # 测试替身路径：显式 allow_broadcast_mode=True 才收 mode=5。
    clock.advance(3600.0)  # 跳出失败冷却。
    sync2, _log2 = _build(
        [mode5_response], clock, max_drift_ms=60_000, allow_broadcast_mode=True
    )
    sync2.now()
    assert sync2.offset_seconds is not None, "显式开关应放行 mode=5"


def test_now_survives_pathological_clock() -> None:
    """M-2：坏 clock（恒负，Windows fromtimestamp 抛 OSError）不炸 now()。"""
    clock = FakeClock(-1e11)
    sync, log = _build([], clock, enabled=False)
    result = sync.now()
    assert isinstance(result, datetime)
    assert log == [], "禁用态零联网"
    assert abs((result - datetime.now().astimezone()).total_seconds()) < 60, (
        "两级兜底全失效时应落到系统 datetime.now()"
    )


def test_zero_max_drift_means_default_clamp_not_off() -> None:
    """M-4：max_drift_ms=0 = 取默认钳制（1.5s），不是关掉不设防。"""
    clock = FakeClock(9_000_000.0)

    def bad_response(_addr):
        return ntp_response(clock.value + 7200.0)  # 2 小时偏移。

    def good_response(_addr):
        return ntp_response(clock.value - 0.025 + 1.0)

    script: list = [bad_response, good_response]
    sync, log = _build(script, clock, max_drift_ms=0)
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in log if item[0] == "send"]
    assert sent_servers == ["a.example", "b.example"], "0 必须落回默认钳制"
