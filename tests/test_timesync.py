"""联网授时（domains/schedule/timesync）回归：全离线 mock socket。

覆盖（用户裁定验收：成功/超时轮转/全败回退三例）：
- 同步成功：偏移被应用且进程内缓存（第二次读不再触发校时）；
- 超时轮转：首台超时后自动换下一台，取首个成功；
- 全失败：回退系统钟 + 告警（偏移清空）；
- 偏移可信度：超 max_drift 的应答拒收；禁用时零联网。
安全席小修包回归（2026-09-13，A12 收编）：
- M-2 病态时钟三级兜底不再上穿（fallback 自身再包一层 → 系统 datetime.now()）；
- M-3 畸形包 fuzz：1970 前编码/全零串时间戳拒收（挡在钳制之前）；
- M-4 max_drift_ms=0 = 取默认钳制，不是关掉不设防；
- M-8 mode=5 broadcast 默认拒收，测试替身须显式 allow_broadcast_mode。
P3-15 应答完整性回归（2026-09-14）：
- originate 不匹配的伪造/重放/串线应答拒收（全伪造=回退系统钟）；
- 合规 originate 回显照常接受 + 请求 transmit 已盖非零时刻（零变化锚点）；
- stratum 0（KOD，既有语义补锁）/stratum>15/LI=3/非 123 源端口拒收轮转。
TS-SOCKET 回归（2026-09-29，生产 NTP 腿结构性哑火那一案）：
- 默认套接字工厂**不注入任何替身**直接判型：必须是 ``SOCK_DGRAM``
  （``socket.socket()`` 缺省是 ``SOCK_STREAM``＝TCP，而 SNTP 在 UDP/123）；
- 用假 NTP 服务端工厂走**默认工厂**那寸代码，证明 NTP 腿真能把 48 字节包
  sendto 到 (host, 123) 并收得一帧应答——旧缺陷的全部要害是"每一枚单测都注入
  ``socket_factory`` 替身"，于是全树绿而生产从未校成过一次 NTP。
T2 回归（2026-09-29，调用线程零网络那一层）：
- ``now()`` 是纯内存读：只按节奏**派发**后台一轮，本线程一次网络都不碰；
- ``refresh()`` 才是在当前线程同步跑完整链（后台 worker 与测试都从这里进）；
- 单飞闸 ``_sync_in_flight``：闸被占时 ``refresh``/``_maybe_sync`` 都不双发，
  ``try/finally`` 释放——并发两轮曾把上一轮刚校好的偏移置空（一轮失败必清偏移，
  这是"宁可显式回退不静默用陈偏移"那条口径的副产物）；
- 起线程失败（RuntimeError/OSError）只 warning、照旧按系统钟走、并归还闸位；
- 真守护线程那一发：校时确实发生在**非调用线程**上。
"""

from __future__ import annotations

import logging
import pathlib
import socket
import struct
import threading
import time
from collections.abc import Callable
from datetime import datetime

import pytest

from plugins.bot_unified_runtime.domains.schedule.timesync import timesync

_NTP_DELTA = 2208988800
_LOGGER = "plugins.bot_unified_runtime.domains.schedule.timesync.timesync"
_MAIN_THREAD = threading.current_thread().name


class FakeClock:
    """可控 Unix 秒钟（recvfrom 前后由测试推进）。"""

    def __init__(self, start: float) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class Forged(bytes):
    """标记类：该应答跳过 FakeSocket 的合规 originate 回显（伪造剧本用）。"""


def timesync_ntp_response(server_time: float) -> bytes:
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


class FakeSocket:
    """按剧本逐台演：Exception=该台失败；bytes=该台应答。

    默认模拟合规服务器（RFC 4330）：把客户端请求的 transmit timestamp
    原样拷进应答 originate（P3-15 后这是被接受的前提）。伪造路径测试用
    ``Forged`` 标记的应答跳过回显、由剧本自造不匹配 originate。剧本动作
    亦可为 ``(payload, addr)`` 二元组，全操控应答（如测来源端口）。
    """

    def __init__(self, script: list, log: list, clock: FakeClock) -> None:
        self._script = script
        self._log = log
        self._clock = clock
        self.last_request: bytes | None = None
        self.addr: tuple[str, int] | None = None

    def settimeout(self, value: float) -> None:
        self._log.append(("timeout", value))

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self._log.append(("send", addr[0]))
        # 记下发起线程：T2 的判据是"校时不在调用线程上跑"，光看有没有发不够。
        self._log.append(("thread", threading.current_thread().name))
        assert len(data) == 48, "SNTP 请求必须是 48 字节"
        assert addr[1] == 123
        self.last_request = bytes(data)
        self.addr = addr

    def recvfrom(self, size: int) -> tuple[bytes, tuple]:
        action = self._script.pop(0)
        self._clock.advance(0.05)  # 网络往返 50ms。
        addr = self.addr or ("203.0.113.7", 123)
        if isinstance(action, Exception):
            raise action
        if callable(action):
            payload = action(self.addr)
        else:
            payload = action
        spoofed = isinstance(payload, Forged)
        if isinstance(payload, tuple):  # (payload, addr) 全操控剧本。
            payload, addr = payload
        if not spoofed and self.last_request is not None and len(payload) >= 48:
            patched = bytearray(payload)
            patched[24:32] = self.last_request[40:48]  # 合规回显。
            payload = bytes(patched)
        return payload, addr

    def close(self) -> None:
        self._log.append(("close",))


def _spawn_recorder(
    log: list, *, run: bool = False
) -> Callable[[Callable[[], None]], None]:
    """``thread_starter`` 替身：记一笔"派了后台一轮"。

    默认**不跑** target——否则测试线程自己就成了那个"调用线程"，T2 的判据
    （now() 零网络）就被自家的替身演没了。不跑就要把闸位还回去：闸的语义是
    "有一轮在飞"，替身里并没有在飞的那一轮，不还就等于替身自己造出一枚死锁
    （第一版栽在这里：后续每一枚 ``now()`` 从此再也派不动）。
    ``run=True`` 的那一枚用来确定性验证"派出去的确实是完整一轮同步链"，
    它跑的是 worker 目标而不是 now() 的调用腿。
    """

    def start(target: Callable[[], None]) -> None:
        log.append(("spawn",))
        if run:
            target()
            return
        owner = getattr(target, "__self__", None)
        if owner is None:
            raise AssertionError(
                "派发替身拿不到 worker 归属实例：_spawn_sync_worker 的传参形态变了，"
                "闸位归还语义要重新对账（别让它安静地变成死锁）"
            )
        # 替身不跑 worker ⇒ 由替身归还派发时取得的那张闸位；对未持有的锁 release()
        # 会抛 RuntimeError，所以这里同时也是"派发确实取过闸"的反证。
        owner._sync_in_flight.release()

    return start


def _build(
    script: list,
    clock: FakeClock,
    *,
    thread_starter: Callable[[Callable[[], None]], None] | None | object = ...,
    **kwargs,
) -> tuple[timesync.TimeSync, list]:
    """默认注入"只记账不跑"的派发替身：凡读 ``now()`` 的用例都因此零网络。"""
    log: list = []
    if thread_starter is ...:
        kwargs["thread_starter"] = _spawn_recorder(log)
    elif thread_starter is not None:
        kwargs["thread_starter"] = thread_starter
    sync = timesync.TimeSync(
        ["a.example", "b.example", "c.example"],
        clock=clock,
        monotonic=clock,  # 复用一个假钟驱动缓存窗口。
        socket_factory=lambda: FakeSocket(script, log, clock),
        **kwargs,
    )
    return sync, log


def _sends(log: list) -> list:
    return [item for item in log if item[0] == "send"]


# ---------------------------------------------------------------- TS-SOCKET


class _FakeNtpSocket:
    """假 NTP 服务端套接字：按**要到的型**决定这一腿走不走得通。

    ``SOCK_DGRAM`` → 一次合规往返（应答回显 originate、源端口 123）。
    其它型（缺省 TCP）→ ``sendto`` 自己抛 ``TimeoutError``：这是本机 09-29 重测
    的实机形态（不是"静默丢包到 recvfrom"，那句措辞被复核席推翻过）。
    """

    def __init__(self, *, sock_type: int, server_time: float, timeout: float) -> None:
        self.type = sock_type
        self._server_time = server_time
        self._timeout = timeout
        self._request: bytes | None = None
        self._addr: tuple[str, int] = ("203.0.113.7", 123)
        self.sent: list[tuple[str, int]] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        self._timeout = value

    def sendto(self, data: bytes, addr: tuple[str, int]) -> int:
        if self.type != socket.SOCK_DGRAM:
            time.sleep(min(self._timeout, 0.01))  # 真机要满 2s，测试里不陪它等。
            raise TimeoutError("timed out")
        self.sent.append(addr)
        self._request = bytes(data)
        self._addr = (addr[0], 123)
        return len(data)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        assert self._request is not None, "请求还没发出就要应答：剧本没走到这一步"
        payload = bytearray(timesync_ntp_response(self._server_time))
        payload[24:32] = self._request[40:48]  # 合规服务器：originate 回显 transmit。
        return bytes(payload), self._addr

    def close(self) -> None:
        self.closed = True


class _FakeSocketNamespace:
    """顶替 ``timesync`` 模块里的 ``socket`` 名字——一整套假 NTP 服务端工厂。

    为什么顶模块里的名字而不是注入 ``socket_factory``：注入替身恰好把
    ``_udp_socket`` 那一段**跳过去**，而 TS-SOCKET 一案的全部要害就在这段。
    这里让默认工厂真被调用一次，工厂按请求参数造出上面那枚假套接字。
    """

    AF_INET = socket.AF_INET
    SOCK_DGRAM = socket.SOCK_DGRAM
    SOCK_STREAM = socket.SOCK_STREAM

    def __init__(self, *, server_time: float, force_stream: bool = False) -> None:
        self.server_time = server_time
        self.force_stream = force_stream
        self.created: list[tuple[int, int]] = []

    def socket(
        self,
        family: int = socket.AF_INET,
        type: int = socket.SOCK_STREAM,  # 与 stdlib 同签名：缺省型必须演得出来
        protocol: int = 0,
    ) -> _FakeNtpSocket:
        chosen = socket.SOCK_STREAM if self.force_stream else type
        self.created.append((family, chosen))
        return _FakeNtpSocket(sock_type=chosen, server_time=self.server_time, timeout=2.0)


def test_default_socket_factory_is_a_datagram_socket() -> None:
    """TS-SOCKET 主判据：**不注入任何替身**，直接判默认工厂造出的套接字型。

    ``socket.socket()`` 的缺省 ``type`` 是 ``SOCK_STREAM``（本机现算＝1），而 SNTP
    在 UDP/123。写成缺省形态时 NTP 腿结构性走不到、每轮白等一个超时，而每一枚
    注入 ``socket_factory`` 的单测都不会发现——全树绿、生产从未校成过一次 NTP。
    """
    sock = timesync._udp_socket()
    try:
        assert sock.type == socket.SOCK_DGRAM
        assert sock.family == socket.AF_INET
    finally:
        sock.close()


def test_ntp_leg_reaches_the_server_with_the_default_factory(monkeypatch) -> None:
    """默认工厂那一寸代码真能被走通：顶掉模块里的 ``socket``，不注入 socket_factory。

    正向＝默认工厂被要求 ``SOCK_DGRAM`` 且真收到一帧合规应答、偏移校上；
    反向＝同一个假服务端面对缺省型（TCP）时 ``sendto`` 就抛，偏移永远校不成
    （生产 09-29 之前每天就是这个样子）。
    """
    clock = FakeClock(1_700_000_000.0)
    fake_module = _FakeSocketNamespace(server_time=clock.value + 1.0)
    monkeypatch.setattr(timesync, "socket", fake_module)

    sync = timesync.TimeSync(
        ["ntp.fake.test"],
        clock=clock,
        monotonic=clock,
        max_drift_ms=1500,
        thread_starter=_spawn_recorder([]),
    )
    # 没有注入 socket_factory ⇒ 用的就是模块级默认工厂（案发点本身）。
    assert sync._socket_factory is timesync._udp_socket

    sync.refresh()

    assert fake_module.created == [(socket.AF_INET, socket.SOCK_DGRAM)], fake_module.created
    assert sync.offset_seconds is not None, "默认工厂下 NTP 腿必须校得成（旧缺陷＝永远校不成）"
    assert sync.offset_seconds == pytest.approx(1.0, abs=0.05)

    # 反向腿：把请求改回缺省型（TCP），同一套假服务端一帧也回不出来。
    stream_module = _FakeSocketNamespace(server_time=clock.value + 1.0, force_stream=True)
    monkeypatch.setattr(timesync, "socket", stream_module)
    tcp_sync = timesync.TimeSync(
        ["ntp.fake.test"],
        clock=clock,
        monotonic=clock,
        max_drift_ms=1500,
        thread_starter=_spawn_recorder([]),
    )
    tcp_sync.refresh()
    assert stream_module.created == [(socket.AF_INET, socket.SOCK_STREAM)]
    assert tcp_sync.offset_seconds is None, (
        "缺省 TCP 套接字那一形必须收不到任何 NTP 应答（生产当时的样子）"
    )


# ---------------------------------------------------------------- T2：调用线程零网络


def test_now_is_a_pure_memory_read_and_only_dispatches() -> None:
    """``now()`` 零网络：一次套接字都不碰，只留一条"该派一轮后台"的账。"""
    clock = FakeClock(1_800_000_000.0)
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 2.0)]
    sync, log = _build(script, clock, max_drift_ms=60_000)

    result = sync.now()

    assert _sends(log) == [], "调用线程一次网络都不许碰"
    assert ("spawn",) in log, "缓存过期了却什么都没派＝校时链今天不会跑"
    assert script, "派出去的轮次不许在测试线程里就地跑完"
    assert sync.offset_seconds is None, "尚未校准 ⇒ 读的是系统钟"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05


def test_dispatched_round_is_the_whole_sync_chain() -> None:
    """派出去的那一轮就是完整同步链（跑完偏移进内存，之后每一读都带着校正）。"""
    clock = FakeClock(1_900_000_000.0)
    true_offset = 2.0
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + true_offset)]
    log: list = []
    sync = timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=lambda: FakeSocket(script, log, clock),
        max_drift_ms=60_000,
        thread_starter=_spawn_recorder(log, run=True),
    )
    corrected = sync.now()  # 替身就地跑 worker 目标：证"派的是完整一轮"
    assert sync.offset_seconds == pytest.approx(true_offset, abs=0.2)
    assert _sends(log) == [("send", "a.example")]
    expected = datetime.fromtimestamp(clock.value + sync.offset_seconds or 0.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.05
    log.clear()
    sync.now()
    assert log == [], "校准成功后缓存窗口内既不发网络也不派第二轮"


def test_a_real_daemon_worker_completes_the_round_off_the_calling_thread() -> None:
    """真守护线程那一发：调用线程不等网络，校时发生在**别的**线程上。"""
    clock = FakeClock(2_000_000_000.0)
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 1.5)]
    log: list = []
    sync = timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=lambda: FakeSocket(script, log, clock),
        max_drift_ms=60_000,
        # 不注入 thread_starter ⇒ 走生产默认的 _start_daemon_worker。
    )
    started = time.monotonic()
    sync.now()  # 只派发
    assert time.monotonic() - started < 0.5, "now() 绝不该等网络（旧形态最坏 ≈12s）"

    deadline = time.monotonic() + 5.0
    while sync.offset_seconds is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sync.offset_seconds is not None, "守护线程那一轮必须真把偏移写进内存"
    threads = [item[1] for item in log if item[0] == "thread"]
    assert threads, " worker 没跑到 sendto：派发没落地"
    assert threads[0] != _MAIN_THREAD, "校时不得发生在调用线程上"
    assert "timesync-resync" in threads[0]


def test_worker_start_failure_warns_and_keeps_the_system_clock(caplog) -> None:
    """起线程失败（``RuntimeError``）：只 warning、按系统钟走、并把单飞闸还回来。"""
    clock = FakeClock(1_410_000_000.0)
    log: list = []

    def _boom(_target: Callable[[], None]) -> None:
        log.append(("spawn-failed",))
        raise RuntimeError("can't start new thread")

    sync = timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=lambda: FakeSocket([], log, clock),
        thread_starter=_boom,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = sync.now()
    assert ("spawn-failed",) in log
    assert _sends(log) == []
    assert sync.offset_seconds is None, "起线程失败不等于校时成功，偏移必须仍是空"
    assert isinstance(result, datetime)
    assert any("后台校时线程没起来" in record.message for record in caplog.records), caplog.text
    assert not sync._sync_in_flight.locked(), "派发失败必须归还单飞闸（否则永远不再校时）"


def test_gate_release_survives_a_raising_sync_round() -> None:
    """闸的释放靠 ``try/finally``：同步链自己抛也得不留死锁。"""
    clock = FakeClock(1_415_000_000.0)
    sync, _log = _build([], clock)

    def _explode(_moment: float) -> None:
        raise ValueError("同步链炸了")

    sync._sync_now = _explode  # type: ignore[method-assign]
    sync.refresh()
    assert not sync._sync_in_flight.locked(), "抛异常也要归还闸位"
    # 还回来了 ⇒ 之后正常一轮能跑（不是整进程永久哑火）。
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 1.0)]
    healthy, _log2 = _build(script, clock, max_drift_ms=60_000)
    healthy.refresh()
    assert healthy.offset_seconds is not None


def test_refresh_respects_the_single_flight_gate() -> None:
    """闸被占时 ``refresh()`` 与派发口一律立刻返回：不发网络、不写状态、不死锁。"""
    clock = FakeClock(1_420_000_000.0)
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 1.0)]
    sync, log = _build(script, clock, max_drift_ms=60_000)

    assert sync._sync_in_flight.acquire(blocking=False), "闸应当初始可用"
    try:
        sync.refresh()
        sync._maybe_sync()
    finally:
        sync._sync_in_flight.release()
    assert _sends(log) == [] and log.count(("spawn",)) == 0, (
        "闸被占：refresh/_maybe_sync 一律不许动网络或派线程"
    )
    sync.refresh()
    assert _sends(log), "闸空出来后正常那一轮要能跑"
    assert not sync._sync_in_flight.locked(), "refresh 必须 try/finally 归还闸位"


def test_concurrent_rounds_cannot_clobber_a_good_offset() -> None:
    """并发两轮的杀伤力：第二环绕过闸就会把刚校好的偏移清成 None。

    剧本是"第一环成功、第二环全败"（一轮失败按诚实口径必清偏移）。有闸在，
    第二环连网络都碰不到 ⇒ 好偏移活着；把闸摘掉这一枚当场打红。
    """
    clock = FakeClock(1_430_000_000.0)
    gate = threading.Event()
    calls: list[int] = []

    class _SlowSocket:
        def __init__(self) -> None:
            self._request: bytes = b""
            self._addr: tuple[str, int] = ("203.0.113.7", 123)

        def settimeout(self, _value: float) -> None:
            return None

        def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
            calls.append(1)
            self._request = bytes(data)
            self._addr = (addr[0], 123)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            assert gate.wait(5.0), "测试看护：闸门没开"
            clock.advance(0.05)
            if len(calls) == 1:
                payload = bytearray(timesync_ntp_response(clock.value - 0.025 + 1.0))
                payload[24:32] = self._request[40:48]
                return bytes(payload), self._addr
            raise TimeoutError("第二环全败")

        def close(self) -> None:
            return None

    sync = timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=_SlowSocket,
        max_drift_ms=60_000,
    )
    first = threading.Thread(target=sync.refresh, name="round-a")
    first.start()
    deadline = time.monotonic() + 5.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.005)
    assert calls, "第一环应已发出请求"

    second = threading.Thread(target=sync.refresh, name="round-b")
    second.start()
    second.join(5.0)
    assert not second.is_alive(), "第二环该被闸挡下并立刻返回"
    assert len(calls) == 1, "闸被占时第二环不许发出第二个请求"

    gate.set()
    first.join(5.0)
    assert not first.is_alive()
    assert sync.offset_seconds is not None, (
        "并发两轮不得把上一轮刚校好的偏移置空（单飞闸存在的理由）"
    )


def test_cooldown_and_cache_rhythm_drive_the_dispatch() -> None:
    """节奏三格：缓存新鲜不派、失败冷却不派、跳出冷却才补派（判的全是内存读数）。"""
    clock = FakeClock(1_440_000_000.0)
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 1.0)]
    sync, log = _build(
        script, clock, resync_seconds=600.0, retry_seconds=300.0, max_drift_ms=60_000
    )
    sync.refresh()
    assert sync.offset_seconds is not None
    assert _sends(log) == [("send", "a.example")]

    clock.advance(120.0)  # 缓存窗口内
    sync.now()
    assert log.count(("spawn",)) == 0, "缓存新鲜时不该再派"

    clock.advance(600.0)  # 越过 resync_seconds
    sync.now()
    assert log.count(("spawn",)) == 1, "缓存过期该派一轮"

    # 失败态：偏移被清、刚试过一轮 ⇒ 冷却内不逐消息重试。
    sync._offset_seconds = None
    sync._last_attempt_monotonic = clock.value
    sync._last_success_monotonic = float("-inf")
    log.clear()
    clock.advance(10.0)
    sync.now()
    assert log.count(("spawn",)) == 0, "失败冷却内不逐消息重试"
    clock.advance(400.0)
    sync.now()
    assert log.count(("spawn",)) == 1, "冷却结束才补派"


# ---------------------------------------------------------------- 既有行为锁


def test_sync_success_applies_offset_and_caches() -> None:
    clock = FakeClock(1_000_000.0)
    true_offset = 30.0  # 本地钟慢 30 秒。

    def response(_addr):
        # t3 = t0 + 0.05（FakeSocket.advance）；取客户端中点 = t3 - 0.025。
        return timesync_ntp_response(clock.value - 0.025 + true_offset)

    script: list = [response]
    # 大偏移（30s）是本例主角：钳制上限必须放大到放行（默认 1.5s 会拒收）。
    sync, log = _build(script, clock, resync_seconds=600.0, max_drift_ms=60_000)
    sync.refresh()  # T2：驱动同步用 refresh，不再靠 now() 内联联网。
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + true_offset).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    assert ("send", "a.example") in log
    assert script == [], "成功后剧本应耗尽"
    # 缓存生效：第二次 now() 不再联网、也不再派轮（剧本已空，再联网会 IndexError→按失败计）。
    clock.advance(60.0)
    again = sync.now()
    assert log.count(("spawn",)) == 0
    assert abs((again - corrected).total_seconds() - 60.0) < 0.2
    assert sync.offset_seconds is not None and abs(sync.offset_seconds - true_offset) < 0.2


def test_timeout_rotates_to_next_server() -> None:
    clock = FakeClock(2_000_000.0)
    true_offset = -5.0  # 本地钟快 5 秒。

    def response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + true_offset)

    script: list = [TimeoutError("timed out"), response]
    sync, log = _build(script, clock, max_drift_ms=60_000)  # 偏移 -5s 需放大钳制。
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + true_offset).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "首台超时应轮转到第二台"


def test_all_servers_fail_falls_back_to_system_clock(caplog) -> None:
    clock = FakeClock(3_000_000.0)
    script: list = [
        TimeoutError("a"),
        TimeoutError("b"),
        OSError("network unreachable"),
    ]
    sync, log = _build(script, clock, retry_seconds=300.0)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        sync.refresh()
    result = sync.now()
    assert sync.offset_seconds is None, "全失败必须回退系统钟（不留陈旧偏移）"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    assert any("回退系统钟" in record.message for record in caplog.records)
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example", "c.example"]
    # 失败冷却：冷却期内不再逐消息重试（不再发起新请求、也不再派线程）。
    clock.advance(60.0)
    sync.now()
    assert [item[1] for item in _sends(log)] == sent_servers
    assert log.count(("spawn",)) == 0, "失败冷却内 now() 不该派第二轮"


def test_oversized_drift_response_rejected() -> None:
    clock = FakeClock(4_000_000.0)

    def bad_response(_addr):
        return timesync_ntp_response(clock.value + 7200.0)  # 偏移 2 小时：不可信。

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    script: list = [bad_response, good_response]
    sync, log = _build(script, clock, max_drift_ms=1500)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "超漂移应答应被拒收并换台"


def test_disabled_never_touches_network() -> None:
    clock = FakeClock(5_000_000.0)
    sync, log = _build([], clock, enabled=False)
    result = sync.now()
    assert log == [], "禁用态必须零联网、零派发"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05


def test_disabled_refresh_is_a_no_op() -> None:
    """禁用态连 ``refresh()`` 都不碰网络（缺省离线是这模块的立身之本）。"""
    clock = FakeClock(5_500_000.0)
    sync, log = _build([], clock, enabled=False)
    sync.refresh()
    assert log == []
    assert sync.offset_seconds is None


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


def test_module_level_now_on_unbound_process_lands_a_disabled_shared() -> None:
    """未绑定配置的进程：模块级 ``now()`` 落一枚 ``enabled=False`` 的默认实例。

    本函数体内有 ``_SHARED`` 赋值 ⇒ **必须** ``global _SHARED, _SHARED_SIGNATURE``，
    漏声明就是首读 ``UnboundLocalError``，毒化 base_router 的 import 链
    （reminders → timesync 经能力层被路由注册表引用）——并行席实跑抓到的真事故。
    """
    import inspect

    timesync.reset_shared_for_tests()
    try:
        assert timesync._SHARED is None
        result = timesync.now()  # 不该抛，也不该联网
        assert isinstance(result, datetime)
        assert timesync._SHARED is not None and timesync._SHARED.enabled is False
        for name in ("now", "configure_from", "reset_shared_for_tests"):
            source = inspect.getsource(getattr(timesync, name))
            assert "global _SHARED, _SHARED_SIGNATURE" in source, name
    finally:
        timesync.reset_shared_for_tests()


def test_module_level_now_never_blocks_the_caller(monkeypatch) -> None:
    """模块级 ``now()``（提醒 tick 与【当前时间】分区走的那一口）同样零网络。"""
    from types import SimpleNamespace

    timesync.reset_shared_for_tests()
    dispatched: list[Callable[[], None]] = []

    def _capture(target: Callable[[], None]) -> None:
        dispatched.append(target)  # 收下但不跑：测试线程绝不联网。

    monkeypatch.setattr(timesync, "_start_daemon_worker", _capture)
    try:
        timesync.configure_from(
            SimpleNamespace(
                bot_time_sync_enabled=True,
                bot_time_sync_servers="ntp.fake.test",
                bot_time_sync_max_drift_ms=1500,
                bot_time_sync_http_enabled=False,
            )
        )
        started = time.monotonic()
        first = timesync.now()
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, f"调用线程等了 {elapsed:.3f}s——T2 之后 now() 不许等网络"
        assert len(dispatched) == 1, "缓存过期时该派一轮后台"
        timesync.now()
        assert len(dispatched) == 1, "在飞/冷却内不双发"
        assert first.tzinfo is not None
    finally:
        timesync.reset_shared_for_tests()


# ---------- 安全席小修包回归（2026-09-13 A12 收编） ----------


def _raw_packet(seconds: int, fraction: int = 0, *, mode: int = 4, stratum: int = 2) -> bytes:
    """手搓原始应答包（绕过 timesync_ntp_response 的正常时间编码）。"""
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
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    script: list = [
        _raw_packet(_NTP_DELTA - 3600),  # 1969-12-31T23:00:00Z：贴 NTP 纪元。
        good_response,
    ]
    sync, log = _build(script, clock, max_drift_ms=3_000_000_000_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "1970 前编码应答应在解包门被拒"


def test_malformed_exact_1970_timestamp_rejected() -> None:
    """畸形包 fuzz①b：恰好 1970-01-01 整编码（unix=0）在解包门被拒（M-3）。"""
    clock = FakeClock(6_500_000.0)
    script: list = [_raw_packet(_NTP_DELTA)]
    sync, log = _build(script, clock)
    sync.refresh()
    result = sync.now()
    assert sync.offset_seconds is None, "1970 整点编码不得产生任何偏移"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers and sent_servers[0] == "a.example", (
        "拒收发生在首台应答侧；后续台只是轮转（剧本空=按失败计）"
    )


def test_malformed_zero_string_timestamp_rejected() -> None:
    """畸形包 fuzz②：时间戳字段全零串拒收，不落成巨大偏移（M-3）。"""
    clock = FakeClock(7_000_000.0)
    script: list = [_raw_packet(0, 0)]
    sync, log = _build(script, clock)
    sync.refresh()
    result = sync.now()
    assert sync.offset_seconds is None
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    assert _sends(log), "请求确实发出过（拒收发生在应答侧）"


def test_broadcast_mode5_rejected_by_default_flag_admits() -> None:
    """畸形包 fuzz③：mode=5 broadcast 默认拒收（M-8）；显式开关才放开。"""
    clock = FakeClock(8_000_000.0)

    def mode5_response(_addr):
        packet = bytearray(timesync_ntp_response(clock.value - 0.025 + 1.0))
        packet[0] = (packet[0] & 0xF8) | 0x05  # 模式位改 5（broadcast）。
        return bytes(packet)

    sync, _log = _build([mode5_response], clock, max_drift_ms=60_000)
    sync.refresh()
    assert sync.offset_seconds is None, "生产默认必须拒收 broadcast 应答"

    # 测试替身路径：显式 allow_broadcast_mode=True 才收 mode=5。
    clock.advance(3600.0)  # 跳出失败冷却。
    sync2, _log2 = _build(
        [mode5_response], clock, max_drift_ms=60_000, allow_broadcast_mode=True
    )
    sync2.refresh()
    assert sync2.offset_seconds is not None, "显式开关应放行 mode=5"


def test_now_survives_pathological_clock() -> None:
    """M-2：坏 clock（恒负，Windows fromtimestamp 抛 OSError）不炸 now()。"""
    clock = FakeClock(-1e11)
    sync, log = _build([], clock, enabled=False)
    result = sync.now()
    assert isinstance(result, datetime)
    assert log == [], "禁用态零联网"
    assert abs((result - datetime.now().astimezone()).total_seconds()) < 60, (
        "三级兜底全失效时应落到系统 datetime.now()"
    )


def test_now_survives_clock_that_raises_oserror() -> None:
    """M-2 第二级兜底：注入 clock 直接抛 ``OSError`` ⇒ 仍落到系统 ``datetime.now()``。

    取数与换算必须在同一层 try 里——旧写法把 ``self._clock()`` 放在 try 之外，
    "病态钟"只兜住了换算那一半，clock 自己抛就当场穿到调用方（提醒链）。
    """

    def _hostile_clock() -> float:
        raise OSError("clock backend is gone")

    sync = timesync.TimeSync(
        ["a.example"], enabled=False, clock=_hostile_clock, monotonic=_hostile_clock
    )
    assert isinstance(sync.now(), datetime)


def test_zero_max_drift_means_default_clamp_not_off() -> None:
    """M-4：max_drift_ms=0 = 取默认钳制（1.5s），不是关掉不设防。"""
    clock = FakeClock(9_000_000.0)

    def bad_response(_addr):
        return timesync_ntp_response(clock.value + 7200.0)  # 2 小时偏移。

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    script: list = [bad_response, good_response]
    sync, log = _build(script, clock, max_drift_ms=0)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "0 必须落回默认钳制"


# ---------- P3-15 应答完整性回归（originate 校验 + 源标识） ----------


def _forged_response(server_time: float, *, originate: bytes) -> Forged:
    """伪造应答：时间戳看似合规，但 originate 由攻击者指定且不回显请求。"""
    packet = bytearray(timesync_ntp_response(server_time))
    packet[24:32] = originate
    return Forged(bytes(packet))


def test_forged_originate_mismatch_rejected_and_rotates() -> None:
    """伪造应答①：originate 与请求 transmit 不匹配（伪造/重放/串线）拒收。

    两枚 Forged 应答（错值 originate / 全零 originate）都不得产生偏移，
    必须轮转到第三台取真应答（合规回显）。
    """
    clock = FakeClock(10_000_000.0)

    def forged_offset_shift(_addr):
        # 攻击意图：谎报本地钟慢 30 秒（offset 注入尝试）。
        return _forged_response(
            clock.value - 0.025 + 30.0, originate=b"\xde\xad\xbe\xef" * 2
        )

    def forged_zero_originate(_addr):
        # 旧式不合规服务器/陈旧重放：originate 全零。
        return _forged_response(clock.value - 0.025 + 30.0, originate=bytes(8))

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    script: list = [forged_offset_shift, forged_zero_originate, good_response]
    sync, log = _build(script, clock, max_drift_ms=60_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example", "c.example"], (
        "两枚伪造应答应被逐台拒收并轮转到第三台"
    )
    assert sync.offset_seconds is not None and abs(sync.offset_seconds - 1.0) < 0.2


def test_all_forged_originate_responses_fall_back_to_system_clock() -> None:
    """伪造应答②：三台全伪造（带漂移注入 + 不匹配 originate）= 全失败回退。"""
    clock = FakeClock(10_500_000.0)

    def forged(_addr):
        return _forged_response(
            clock.value + 3600.0, originate=b"\x01\x02\x03\x04\x05\x06\x07\x08"
        )

    sync, log = _build([forged, forged, forged], clock, retry_seconds=300.0)
    sync.refresh()
    result = sync.now()
    assert sync.offset_seconds is None, "全伪造应答不得产生任何偏移"
    expected = datetime.fromtimestamp(clock.value).astimezone()
    assert abs((result - expected).total_seconds()) < 0.05
    assert [item[1] for item in _sends(log)] == ["a.example", "b.example", "c.example"]


def test_compliant_originate_echo_accepted_and_request_stamped() -> None:
    """合规应答锚点（行为零变化）：originate=请求 transmit 回显 → 照常接受。

    同时锁请求报文新语义：transmit 字段（40:48）必须已填非零 NTP 时刻——
    这是 originate 校验能成立的前提（固定全零请求无法与伪造应答区分）。
    """
    clock = FakeClock(11_000_000.0)
    log: list = []
    script: list = [lambda _addr: timesync_ntp_response(clock.value - 0.025 + 1.0)]
    fake = FakeSocket(script, log, clock)  # 默认模拟合规服务器（回显 originate）。
    sync = timesync.TimeSync(
        ["a.example"],
        clock=clock,
        monotonic=clock,
        socket_factory=lambda: fake,
        max_drift_ms=60_000,
        thread_starter=_spawn_recorder(log),
    )
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    assert sync.offset_seconds is not None and abs(sync.offset_seconds - 1.0) < 0.2
    request = fake.last_request
    assert request is not None, "请求确实发出过"
    assert request[40:48] != bytes(8), "请求 transmit 必须已填非零时刻（校验锚点）"


def test_kiss_of_death_stratum0_rejected_and_rotates() -> None:
    """stratum=0（KOD）拒收：既有语义（timesync 侧原有分支），补回归锁。"""
    clock = FakeClock(11_500_000.0)
    kod = _raw_packet(_NTP_DELTA + int(clock.value) + 1, 0, stratum=0)

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    sync, log = _build([kod, good_response], clock, max_drift_ms=60_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "KOD 应答应在 stratum 门拒收并轮转"


def test_stratum16_unsynchronized_rejected_and_rotates() -> None:
    """stratum=16+（RFC 5905 未同步态）拒收：P3-15 新增分支。"""
    clock = FakeClock(12_000_000.0)
    bad = _raw_packet(_NTP_DELTA + int(clock.value) + 1, 0, stratum=16)

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    sync, log = _build([bad, good_response], clock, max_drift_ms=60_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "stratum>15 应答必须拒收并轮转"


def test_leap_alarm_li3_rejected_and_rotates() -> None:
    """LI=3（服务器自报闰秒告警/未同步态）拒收：其余字段合规也不收。"""
    clock = FakeClock(12_500_000.0)

    def li3_response(_addr):
        packet = bytearray(timesync_ntp_response(clock.value - 0.025 + 1.0))
        packet[0] = packet[0] | 0xC0  # LI=3。
        return bytes(packet)

    def good_response(_addr):
        return timesync_ntp_response(clock.value - 0.025 + 1.0)

    sync, log = _build([li3_response, good_response], clock, max_drift_ms=60_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "LI=3 应答应在告警门拒收并轮转"


def test_response_from_wrong_source_port_rejected() -> None:
    """来源端口非 123 的应答拒收：源标识核验（伪造/串线常见特征）。"""
    clock = FakeClock(13_000_000.0)
    good_packet = timesync_ntp_response(clock.value - 0.025 + 1.0)
    # 应答内容合规，但"来自"非常规端口 45123 → 不可信来源。
    script: list = [(good_packet, ("198.51.100.9", 45123)), good_packet]
    sync, log = _build(script, clock, max_drift_ms=60_000)
    sync.refresh()
    corrected = sync.now()
    expected = datetime.fromtimestamp(clock.value + 1.0).astimezone()
    assert abs((corrected - expected).total_seconds()) < 0.2
    sent_servers = [item[1] for item in _sends(log)]
    assert sent_servers == ["a.example", "b.example"], "非 123 源端口应答应拒收并轮转"


# ---------------------------------------------------------------- 文档卫生锁


def _module_source(module) -> str:
    path = getattr(module, "__file__", "") or ""
    if not path:
        return ""
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_module_doc_carries_current_criteria_and_no_stale_wording() -> None:
    """模块头注释是本件判据的唯一落点：过期数字与已被推翻的措辞一律算回潮。

    钉四件（都是这案子里被推翻或写错过的原话）：
    - 不许留 ``900s``：外圈真身是 60s，写 900s 等于把攻击面写成安全边界；
    - 不许写 ``≥2 个不同来源``：真身是 **≥2 家不同供应商**（同家两子域能伪造共识）；
    - 不许留"TCP 套接字静默丢包到 recvfrom"那句：本机重测实为 ``sendto`` 自己
      阻塞满超时抛 ``TimeoutError``（复核席推翻过一次，别再抄回来）；
    - 不许有逐字重复的注释行（重放残缺曾造出一行散文逐字出现两次）。
    """
    source = timesync.__doc__ or ""
    file_text = _module_source(timesync)
    assert file_text, "取不到模块源码：这枚锁就成了空跑"
    assert "900s" not in file_text, "900s 是被推翻的外圈旧值，不许以任何形式留在本件"
    assert "≥2 个不同来源" not in file_text
    assert "不同供应商" in source and "SOCK_DGRAM" in source
    assert "TimeoutError" in source, "sendto 自己抛 TimeoutError 是复核席更正后的措辞"
    assert "静默到超时" not in source and "不报错" not in source, (
        "『TCP 套接字 sendto 静默丢包、recvfrom 一路静默到超时』已被本机重测推翻"
    )
    comment_lines = [
        line.strip()
        for line in file_text.splitlines()
        if line.strip().startswith("#") and len(line.strip().lstrip("#").strip()) > 3
    ]
    # 分节横线（# ------- 与 # --- 同步 -------）是排版件，不是散文，不参与复读判据。
    prose_lines = [
        line
        for line in comment_lines
        if set(line.lstrip("#").strip()) - {"-", "=", " "} != set()
    ]
    duplicated = sorted({line for line in prose_lines if prose_lines.count(line) > 1})
    assert not duplicated, f"注释里有逐字重复行：{duplicated}"
