"""联网授时（timesync）：纯 stdlib SNTP 客户端，为提醒链路提供校正时间。

设计（2026-09-13 六域批，用户裁定五点之一）：
- **纯 stdlib**：socket + struct 手搓 SNTPv4 客户端报文（48 字节，客户端
  模式），无任何第三方依赖、无子进程。
- **绝不改系统钟**：只算偏移量 ``offset``（服务器时刻 - 本地钟），``now()``
  返回 ``系统钟 + offset`` 的 aware 本地时间。系统时间永远原样。
- **服务器轮转**：列表来自 ``BOT_TIME_SYNC_SERVERS``（逗号分隔），每个
  2s 超时逐个试，取首个成功且偏移可信的；全失败 → 回退系统钟 + 告警。
- **HTTPS 时间源兜底（R3 停摆批 2026-09-17，链形 2026-09-29 更新）**：NTP 全败后
  改走 HTTPS ``Date`` 响应头（RFC 7231）估算偏移：HEAD 请求国内可达端点
  （默认表真身＝``DEFAULT_HTTP_TIME_URLS_RAW``，``BOT_TIME_SYNC_HTTP_URL`` 可换），
  θ = server − (t0+t3)/2（Date 只有 1 秒粒度，+0.5s 把量化误差居中）；
  **失败链现在是 NTP → HTTPS → 多源互证 → 回退系统钟**（互证那一级见 TS-CONSENSUS：
  ``±max_drift`` 只是**单源**上限，两家独立供应商彼此离散在一个量化步长内才允许突破它），
  每级一行日志、回退行带本轮各源读数。仅收 ``https://``（明文 http 时间可被中间人
  伪造，不作为授时源）。
  配置键 ``bot_time_sync_http_enabled``（默认开；**字段缺失**＝不启用，
  与 enabled 同款口径，保住离线测试零网络）。
- **偏移可信度**：``|offset|`` 超过 ``BOT_TIME_SYNC_MAX_DRIFT_MS`` 的服务器
  应答视为不可信（拒收该台，试下一台）；全部不可信同回退。RTT > 10s 的
  应答也拒收（链路质量差到偏移已无意义）。
- **应答完整性（P3-15 收口）**：请求 transmit timestamp 填本地当前时刻
  （t0），应答 originate timestamp 必须与之**逐字节一致**（RFC 4330
  客户端义务）——不匹配＝伪造/重放/串线应答，丢弃走轮转/回退链；另核
  来源端口（必须 123）、stratum（0=KOD 既有，>15=未同步新增拒收）、
  LI=3（告警态新增拒收）。mode=4-only 与 1970 解包门等既有回归锚点原样。
- **进程内缓存**：校准成功后 ``resync_seconds``（默认 10 分钟）内不再联网；
  失败后 ``retry_seconds``（默认 5 分钟）冷却，不逐消息重试打爆日志。
  缓存过期后重校失败 → 按"全失败"处理：丢弃旧偏移、回退系统钟并告警
  （诚实口径：宁可显式回退，不静默用越来越陈的偏移）。
- **默认离线**：未 ``configure_from(config)`` 绑定过真实配置的进程（单测、
  纯函数调用）一律禁用联网——``now()`` 就是系统钟，测试零网络、零等待。
  生产链路由 ``character/reminders.build_reminder_store`` 与能力构建处用
  真实 config 绑定（config.py 字段恒在 → 自然启用）。
- **UDP 套接字显式化（TS-SOCKET 2026-09-29 实测定位）**：默认套接字工厂必须
  ``socket(AF_INET, SOCK_DGRAM)``。``socket.socket()`` 的缺省型是 **SOCK_STREAM
  （TCP）**，而对未连接的 TCP 套接字 ``sendto(data, addr)`` 在本机实测是
  **在 ``sendto`` 自己那里阻塞满 2s 后抛 ``TimeoutError``**（回环与黑洞地址同形），
  ``recvfrom`` 根本到不了——于是 NTP 腿每台白等一个超时、轮轮换不到一帧应答，
  生产里**从未收到过一个 NTP 应答**。单测全绿是因为每一枚都注入 ``socket_factory``，
  量具把被测那段跳过去了（同族事故见台账 #61「证明缺席」那一型）。现网复核：
  UDP/123 **是通的**，历次"NTP 全败"的账记在本格，不记防火墙。
- **调用线程零网络（T2 2026-09-29）**：``now()`` 是**纯内存读**（系统钟 + 已校准
  的偏移），不再内联校时——旧形态把 NTP 3×2s + HTTPS 3×2s（最坏 ≈12s；09-29 复测：
  NTP 那 6s 当年是套接字错型造的，与防火墙无关，见 TS-SOCKET）串在每一条读"现在"
  的路径上（提醒 tick、【当前时间】分区、限流节流），等于让聊天链路替校时买单。
  现在缓存过期只**派发**一轮后台守护线程（:meth:`_request_background_sync`），
  同步链本体住 :meth:`refresh`（当前线程入口）与 :meth:`_sync_round`（worker 本体，
  跑完归还闸位——worker 目标写成 ``refresh`` 就是自己把自己挡在门外）；派发口与
  同步入口共用一把**单飞闸** ``_sync_in_flight``
  （``try/finally`` 释放）——早先的缺陷正是后台腿绕过了它，并发两轮把上一轮刚校好的
  偏移置成 None（一轮失败必清空偏移，这是"宁可显式回退不静默用陈偏移"的那条口径）。
- **单源钳制之外的一条互证口（TS-CONSENSUS 2026-09-29）**：``±max_drift_ms`` 的
  原意是"别信一个说谎的时间源"，但它同时把"本地钟本来就偏了 1.6s"钉成**永远修不好**
  ——需要校正的量超过上限时，唯一正确的读数也一定超限，每轮都以"回退系统钟"收场
  （实测：偏 1.4s 可校，偏 1.6s 起永久失败；生产日志 09-27 连续三轮 baidu +3.299s
  被拒即此形）。修法不是放宽上限（单源口径一字未动），而是加**多源互证**这一级：
  只有 ≥2 家**不同供应商**（端点名按 host 末两节折到厂商，见 :func:`_vendor_key`；同家
  两台一起错会伪造共识）、彼此离散 ≤1 个量化步长、且往返短到没被连接耗时污染的读数，
  才可以突破单源上限取中位数；再外套一道 60s 的**最大校正量**外圈（见
  ``_CONSENSUS_MAX_CORRECTION_SECONDS``）——过外圈已经不是钟漂而是系统级故障，
  bot 不自作主张改口径，照样回退并告警。
"""

from __future__ import annotations

import http.client
import logging
import math
import socket
import statistics
import struct
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Final, NamedTuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# NTP 纪元（1900-01-01）与 Unix 纪元（1970-01-01）之间的秒差。
_NTP_DELTA_SECONDS = 2208988800
_NTP_PORT = 123
_PACKET_SIZE = 48
# 客户端请求：LI=0, VN=4, Mode=3(client) → 0b00100011 = 0x23。
_CLIENT_PACKET = bytes([0x23]) + bytes(_PACKET_SIZE - 1)
# 应答头：模式字段在首字节低 3 位，server = 4。
_SERVER_MODE = 4
_MAX_RTT_SECONDS = 10.0
# 合法服务器 stratum 上限（RFC 5905：1-15；0=KOD，16+=未同步态）。
_MAX_VALID_STRATUM = 15

#: 多源互证这一级的尺（判据只在这里写一次，``_consensus_offset`` 用它说话）。
#: 这一级是把"单源上限 ±max_drift"之外的读数**破例采纳**，所以每一道尺都在收紧，
#: 没有一道是"看情况"：
#: * ``_CONSENSUS_MIN_VENDORS``＝**独立供应商**数（不是端点数）。09-29 审查席实测：
#:   只数"名字不同"时，同一家两个子域（img1/img2）一起错＝伪造出共识，而那正是
#:   taobao 边缘缓存错值那一形；``BOT_TIME_SYNC_HTTP_URL`` 是管理员可配的，所以
#:   "默认表里只留两家"根本不是防线，判据必须自己数供应商。
#: * ``_CONSENSUS_TOLERANCE_SECONDS``＝1.0s＝HTTPS ``Date`` 的整秒量化步长，
#:   按**簇直径**（max−min）算而不是"各自离锚点多远"——锚点半径写法三枚读数
#:   3/4/5 能连成一簇而直径到 2s，等于把这条尺放宽一倍还自称 1s。
#: * ``_CONSENSUS_MAX_RTT_SECONDS``＝0.5s：往返超过这个数的读数已经被建连耗时抬高
#:   （实测 3s 建连把分毫不差的钟报成超限）。⚠ 它只是**上限**，不是"去污"：
#:   共同延迟（captive portal / 公司代理一条链同时喂两家）在数学上无法靠"两家一致"
#:   发现，所以本级的容忍度只剩最后那条——校正量本身必须小。
#: * ``_CONSENSUS_MAX_CORRECTION_SECONDS``＝60s：这是本级真正的气闸。需要偏过一分钟
#:   才能对上的钟不是"钟漂了一点"而是系统级故障（CMOS/虚拟化挂起/中间人打时间戳），
#:   让 bot 悄悄顶着一个大校正只会把提醒与日志口径一起带歪。09-27 生产那一形
#:   是 +3.2s，60s 足够救它；外圈写得越宽就不是安全边界而是攻击面，故只留 60s。
_CONSENSUS_MIN_VENDORS: Final[int] = 2
_CONSENSUS_TOLERANCE_SECONDS: Final[float] = 1.0
_CONSENSUS_MAX_RTT_SECONDS: Final[float] = 0.5
_CONSENSUS_MAX_CORRECTION_SECONDS: Final[float] = 60.0

DEFAULT_SERVERS_RAW = "ntp.aliyun.com,cn.ntp.org.cn,pool.ntp.org"
DEFAULT_MAX_DRIFT_MS = 1500
# HTTPS 时间源兜底（R3 停摆批）：NTP 全败时改用的国内可达默认端点
# （HEAD 响应都带 RFC 7231 Date 头；逗号分隔，BOT_TIME_SYNC_HTTP_URL 可换）。
# 2026-09-29 实测把 taobao 移出：它的 ``Date`` 头自己就是错的（同一秒并发实测
# -62.5s，生产日志 09-27 三读数 -64.2/-83.8/-88.9s——像边缘缓存值而不是钟），
# 而 baidu/qq 同窗实测 +0.42~+0.62s、与 NTP 的 +0.47s 同向。只留两枚**不同供应商**
# 而不是多堆端点：互证要的是"两家独立说同一件事"，同家两台一起错会伪造出共识。
DEFAULT_HTTP_TIME_URLS_RAW = "https://www.baidu.com,https://www.qq.com"


class _Sample(NamedTuple):
    """一次成功取到的候选读数：偏移秒、往返秒、来源名、来源类别（NTP/HTTPS）。"""

    offset: float
    round_trip: float
    name: str
    source: str


def _vendor_key(name: object) -> str:
    """端点名 → **供应商** key（host 末两节）；URL 先剥掉 scheme/path。

    互证那一级的判据是"几家独立供应商"，不是"几个端点名"——只数端点会被三种
    形态伪造出共识（09-29 复核席实测）：①同一家两个子域（``img1``/``img2``，
    taobao 边缘缓存错值正是这一形）；②管理员把 ``BOT_TIME_SYNC_HTTP_URL`` 配成
    同家两台；③一个 TLS 拦截代理给两名盖同一个 ``Date``。前两种靠"折到厂商"
    挡住；第三种挡住不了（host 名没变），所以本级还留了最大校正量那道外圈。
    ⚠ IPv4 字面量没有"厂商"可读（末两节纯属巧合），这里退化成"整串地址当一家"，
    本机/同箱两个 IP 会被算成两家——这是本函数已知的边界，不外宣它能防住什么。
    """
    text = str(name or "").strip().lower()
    if not text:
        return ""
    host = urlsplit(text).hostname or "" if "://" in text else text
    host = host.strip("[]")  # IPv6 字面量的方括号。
    host = host.split("%", 1)[0].rstrip(".")  # zone id / 根点。
    labels = [item for item in host.split(".") if item]
    if len(labels) >= 2 and all(item.isdigit() for item in labels) and len(labels) == 4:
        return host  # IPv4 字面量：折末两节没有意义，整串当一家。
    if len(labels) < 2:
        return host
    return ".".join(labels[-2:])


def _udp_socket() -> socket.socket:
    """默认套接字工厂：**必须**显式给 SOCK_DGRAM，理由见模块头 TS-SOCKET 段。

    ``socket.socket()`` 缺省是 TCP。对未连接的 TCP 套接字 ``sendto(data, addr)``
    在本机实测**不静默**——它阻塞满 2s 后抛 ``TimeoutError``（回环与黑洞地址一样），
    于是每台都白等一整个超时、NTP 腿一帧应答也没收到过；后果与"静默丢包"相同，
    机制别写成假的（09-29 复核席按本机重测更正措辞）。单测全绿是因为每一枚都
    注入 ``socket_factory`` 替身，正好把这段跳过去。
    """
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _parse_http_date(value: object) -> float | None:
    """RFC 7231 Date 头 → Unix 秒；畸形/缺失返回 None。

    ``email.utils.parsedate_to_datetime`` 同时吃 IMF-fixdate（首选）与
    RFC 850 / asctime 旧格式；后两者 naive → 按 GMT 口径补 UTC（两种旧
    格式规范都定义在 GMT）。1970 前时间戳在 Windows 上 ``timestamp()``
    抛 OSError，一并按失败处理。
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        unix = parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return None
    return unix if unix > 0 else None


def _https_head_factory(url: str, timeout: float) -> tuple[int, str]:
    """对 HTTPS 端点发 HEAD，返回 (状态码, Date 头原文)；stdlib 实现。

    仅收 ``https://``（明文 http 时间可被中间人伪造，绝不作为授时源）。
    Connection: close → 每次全新连接，不复用可能陈旧的 TLS 会话。
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"非 HTTPS 时间源被拒绝: {url}")
    connection = http.client.HTTPSConnection(
        parts.hostname, parts.port or 443, timeout=timeout
    )
    try:
        connection.request(
            "HEAD",
            parts.path or "/",
            headers={
                "User-Agent": "shorekeeper-timesync/1.0",
                "Accept": "*/*",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        status = int(response.status)
        date_value = str(response.headers.get("Date", "") or "")
        response.read()
        return status, date_value
    finally:
        try:
            connection.close()
        except Exception:
            logger.debug(
                "timesync: HTTPS 连接关闭失败（不影响授时链）", exc_info=True
            )


def _unpack_ntp_timestamp(raw: bytes) -> float | None:
    """NTP 64 位时间戳（秒+小数）→ Unix 秒；零值（未置位）返回 None。"""
    if len(raw) != 8:
        return None
    seconds, fraction = struct.unpack("!II", raw)
    # 1970-01-01 之前（含全零串、贴着 NTP 纪元的应答）一律拒收：畸形/
    # 伪造包可造出 ±1e9 秒量级的偏移，必须挡在漂移钳制之前（安全席 M-3）。
    if seconds < _NTP_DELTA_SECONDS:
        return None
    total = seconds + fraction / 2**32
    unix = total - _NTP_DELTA_SECONDS
    if unix <= 0:  # 恰好 1970 整编码（unix=0）同样不算可信时刻。
        return None
    return unix


def _pack_ntp_timestamp(unix_seconds: float) -> bytes | None:
    """Unix 秒 → NTP 64 位时间戳（秒+小数）；编码不出可信时刻返回 None。

    与解包门同口径：≤1970（含 NaN/负钟）的本地时刻不配当请求 transmit
    timestamp——此时按单台失败处理，轮转/回退链兜底（fail-open 不变）。
    """
    total = unix_seconds + _NTP_DELTA_SECONDS
    if not total > _NTP_DELTA_SECONDS:  # NaN 也一并落网。
        return None
    seconds = int(total)
    fraction = int((total - seconds) * 2**32)
    return struct.pack("!II", seconds, fraction)


def _start_daemon_worker(target: Callable[[], None]) -> None:
    """默认后台起跑器：守护线程，随进程退出，绝不拦主链路。

    ``threading.Thread.start()`` 起不来时抛 ``RuntimeError``（"can't start new
    thread"）——调用方 :meth:`TimeSync._request_background_sync` 接住它、退回
    系统钟并留一行 warning；校时永远不是把聊天或提醒拖死的那一枚。
    """
    threading.Thread(target=target, name="timesync-resync", daemon=True).start()


class TimeSync:
    """可注入时钟与套接字的 SNTP 校时器（进程内共享一把）。"""

    def __init__(
        self,
        servers: list[str],
        *,
        enabled: bool = True,
        timeout: float = 2.0,
        resync_seconds: float = 600.0,
        retry_seconds: float = 300.0,
        max_drift_ms: int = DEFAULT_MAX_DRIFT_MS,
        allow_broadcast_mode: bool = False,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        socket_factory: Callable[[], socket.socket] | None = None,
        http_enabled: bool = False,
        http_urls: list[str] | None = None,
        http_factory: Callable[[str, float], tuple[int, str]] | None = None,
        thread_starter: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._servers = [str(item).strip() for item in servers if str(item).strip()]
        self._enabled = bool(enabled)
        self._timeout = max(0.1, float(timeout))
        self._resync_seconds = max(1.0, float(resync_seconds))
        self._retry_seconds = max(1.0, float(retry_seconds))
        # 0/负值＝整体关掉偏移钳制（=不设防），视作取默认值，不许绕过
        # 可信上限（安全席 M-4）。
        drift_ms = int(max_drift_ms)
        if drift_ms <= 0:
            drift_ms = DEFAULT_MAX_DRIFT_MS
        self._max_drift_seconds = drift_ms / 1000.0
        # 生产路径只收 mode=4(server) 应答；mode=5(broadcast) 仅测试替身
        # 经显式开关放开（安全席 M-8）。
        self._allowed_modes = (4, 5) if allow_broadcast_mode else (4,)
        self._clock = clock
        self._monotonic = monotonic
        self._socket_factory = socket_factory or _udp_socket
        # HTTPS 时间源兜底（R3 停摆批）：默认关（纯函数/离线测试零网络），
        # 由 configure_from 按真实配置启用；仅收 https:// 端点。
        self._http_enabled = bool(http_enabled)
        self._http_urls = [
            item.strip() for item in (http_urls or []) if str(item).strip()
        ]
        self._http_factory = http_factory or _https_head_factory
        # 校准状态（锁保护；now() 读多写少）。
        self._lock = threading.Lock()
        self._offset_seconds: float | None = None
        self._last_success_monotonic = float("-inf")
        self._last_attempt_monotonic = float("-inf")
        # 后台派发用的起跑器（测试注入替身，真机走守护线程）。
        self._thread_starter = thread_starter or _start_daemon_worker
        # 单飞闸：**同时只许一轮校时在飞**（try/finally 释放，见 refresh /
        # _request_background_sync）。绕过它 = 并发两轮，一轮失败会把另一轮
        # 刚校好的 offset 置空（09-29 实跑的缺陷）。非重入，故绝不嵌套持有。
        self._sync_in_flight = threading.Lock()

    # -- 查询面 ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def offset_seconds(self) -> float | None:
        with self._lock:
            return self._offset_seconds

    def now(self) -> datetime:
        """校正后的 aware 本地时间；未启用/未校准/同步失败 = 系统钟。

        **纯内存读**（T2）：本方法只在调用线程里读一把带锁的偏移，然后按节奏
        *派发* 一轮后台校时；网络 I/O 一律发生在守护线程里，调用线程零网络。
        病态钟三级兜底：``fromtimestamp(base)`` → ``fromtimestamp(self._clock())``
        → ``datetime.now().astimezone()``，绝不让 ``OSError`` 上穿炸提醒链路。
        """
        self._maybe_sync()
        with self._lock:
            offset = self._offset_seconds
        try:
            # 取数与换算放在**同一层** try 里：注入的 clock 自己抛（时间库被劫、
            # 沙箱里 time.time 不可用）也是"病态钟"，同一把尺一起兜到第三级。
            base = self._clock() + (offset or 0.0)
            return datetime.fromtimestamp(base).astimezone()
        except (OSError, OverflowError, ValueError):
            # 病态时钟（如负时间戳，Windows 不支持）：先试退回系统钟；
            # fallback 自身可能再次踩到同一坏 clock（注入 clock 恒抛/恒负
            # 时 fromtimestamp 一样炸），最终兜底系统 datetime.now()——
            # 绝不让 OSError 上穿炸提醒链路（安全席 M-2）。
            try:
                return datetime.fromtimestamp(self._clock()).astimezone()
            except (OSError, OverflowError, ValueError):
                return datetime.now().astimezone()

    # -- 同步节奏（调用线程零网络）与同步入口 ---------------------------------

    def _sync_due(self, moment: float) -> bool:
        """按缓存/冷却判断"这一轮该不该跑"（纯内存判，绝不联网）。"""
        with self._lock:
            has_offset = self._offset_seconds is not None
            last_attempt = self._last_attempt_monotonic
            last_success = self._last_success_monotonic
        if has_offset:
            # 有偏移 ⇒ 只看缓存窗口（陈旧了才补派）。
            return moment - last_success >= self._resync_seconds
        # 没偏移 ⇒ 看失败冷却，别逐消息重试打爆日志。
        return moment - last_attempt >= self._retry_seconds

    def _maybe_sync(self) -> None:
        """``now()`` 的入口：只判节奏 + 派后台，本线程一次网络都不碰。"""
        if not self._enabled:
            return
        if not self._sync_due(self._monotonic()):
            return
        self._request_background_sync()

    def _request_background_sync(self) -> None:
        """把整条同步链丢进守护线程；起不来就照旧按系统钟走并留一行 warning。

        槽位在这里取得，由 worker（:meth:`_sync_round`）的 ``finally`` 归还——
        这就是单飞闸：派发时若已有一轮在飞，直接安静返回，不双发第二轮。
        """
        if not self._enabled:
            return
        if not self._sync_in_flight.acquire(blocking=False):
            return
        try:
            self._spawn_sync_worker()
        except (RuntimeError, OSError) as exc:
            self._sync_in_flight.release()
            logger.warning(
                "timesync: 后台校时线程没起来（%s: %s），本轮按系统钟走（不拖调用线程）",
                type(exc).__name__,
                exc,
            )

    def _spawn_sync_worker(self) -> None:
        """起跑一轮后台校时。

        ⚠ worker 目标是 :meth:`_sync_round` 而不是 :meth:`refresh`：槽位已由派发方
        取得，worker 再取一次就是自己把自己挡在门外（写成 ``refresh`` 时表现＝
        派发一条不落、偏移永远为 None，而每一枚单测看着都"合理"）。
        """
        self._thread_starter(self._sync_round)

    def _sync_round(self) -> None:
        """跑一轮并**归还手中这张闸位**（worker 本体；异常一律咽下并留痕）。"""
        try:
            self._sync_now(self._monotonic())
        except Exception as exc:  # noqa: BLE001 - 校时绝不带走调用方（含守护线程）。
            logger.warning(
                "timesync: 校时轮异常退出（%s: %s），按系统钟走", type(exc).__name__, exc
            )
        finally:
            self._sync_in_flight.release()

    def refresh(self) -> None:
        """**当前线程**同步跑一轮校时（后台 worker 与测试都从这里进）。

        过单飞闸：已有校时在飞时立刻返回、不并发第二轮——一轮失败按口径要把
        偏移清成 None（宁可显式回退也不静默用陈偏移），并发两轮就会把上一轮刚
        校好的读数抹掉。闸用 ``try/finally`` 释放，中途抛出也不留死锁。
        """
        if not self._enabled:
            return
        if not self._sync_in_flight.acquire(blocking=False):
            return
        self._sync_round()

    def _sync_now(self, moment: float) -> None:
        """在**当前线程**跑完整一轮：NTP 轮转 → HTTPS Date 兜底 → **多源互证** → 回退系统钟。

        只有两条路进得来这里：守护线程（``refresh``）与测试/后台显式 ``refresh``——
        ``now()`` 永不直调（T2：调用线程零网络）。闸的释放由 ``refresh`` 的
        ``finally`` 负责，本方法不碰闸。

        失败链每级一行日志（NTP 全败一行 info 转 HTTPS、HTTPS 端点成功
        一行 info/失败 debug、互证采纳一行 warning、整体回退一行 warning 且
        **带上本轮全部超限读数**——回退行原来只报"都不可信"却不报各家说了多少秒，
        于是"到底是谁在说谎"这件事在生产日志里问不出来，2026-09-29 排查就是卡在这）。
        """
        with self._lock:
            self._last_attempt_monotonic = moment
        rejects: list[_Sample] = []
        for server in self._servers:
            measured = self._query_server(server)
            if measured is None:
                continue
            offset, round_trip = measured
            if self._apply_offset(_Sample(offset, round_trip, server, "NTP"), rejects):
                return
        if self._http_enabled and self._http_urls:
            logger.info(
                "timesync: NTP 全部不可达或偏移不可信（%d 台），转 HTTPS 时间源（%d 个）",
                len(self._servers),
                len(self._http_urls),
            )
            for url in self._http_urls:
                measured = self._query_http(url)
                if measured is None:
                    continue
                offset, round_trip = measured
                if self._apply_offset(_Sample(offset, round_trip, url, "HTTPS"), rejects):
                    return
        agreed = self._consensus_offset(rejects)
        if agreed is not None:
            self._commit_consensus(agreed)
            return
        # 全失败（不可达/超时/偏移不可信且互证不够格）：回退系统钟。
        with self._lock:
            self._offset_seconds = None
        logger.warning(
            "timesync: 全部时间源不可达或偏移不可信（servers=%s; http=%s），回退系统钟；"
            "本轮超限读数=%s",
            ",".join(self._servers) or "<empty>",
            ",".join(self._http_urls) if self._http_enabled else "<disabled>",
            "; ".join(f"{item.name}={item.offset:+.3f}s/{item.round_trip:.3f}s"
                      for item in rejects) or "<无一个源应答>",
        )

    def _apply_offset(
        self, sample: _Sample, rejects: list[_Sample] | None = None
    ) -> bool:
        """非有限数门 + 偏移钳制 + 入账 + 成功日志；拒收记 warning 返回 False。

        拒收的读数同时登记进 ``rejects``（本轮调用方给的账本）——单源钳制只说明
        "这一家的话我不敢独自采纳"，并不说明它错；互证那一级要用的正是这些读数。
        ⚠ 非有限数（NaN/±Inf）走**另一道**门、且**不进** ``rejects``：它不是"偏太多
        的读数"而是垃圾。NaN 尤其阴——``abs(nan) > limit`` 恒为 False，只靠钳制那道
        尺会把 NaN 当"可信"直接落库，``now()`` 从此每次都算出同一个坏时刻。
        """
        if not (math.isfinite(sample.offset) and math.isfinite(sample.round_trip)):
            logger.warning(
                "timesync: %s（%s）读数非有限（offset=%r, rtt=%r），按垃圾拒收，不落库",
                sample.name,
                sample.source,
                sample.offset,
                sample.round_trip,
            )
            return False
        if self._max_drift_seconds > 0 and abs(sample.offset) > self._max_drift_seconds:
            logger.warning(
                "timesync: %s（%s）应答偏移 %+.3fs 超过可信上限 %+.3fs，拒收",
                sample.name,
                sample.source,
                sample.offset,
                self._max_drift_seconds,
            )
            if rejects is not None:
                rejects.append(sample)
            return False
        with self._lock:
            self._offset_seconds = sample.offset
            self._last_success_monotonic = self._monotonic()
        logger.info(
            "timesync: 与 %s（%s）校准成功，本地钟偏移 %+.3fs（缓存 %ss）",
            sample.name,
            sample.source,
            sample.offset,
            self._resync_seconds,
        )
        return True

    def _consensus_offset(self, rejects: list[_Sample]) -> list[_Sample] | None:
        """在**被单源钳制拒收**的读数里找互证；够格就返回背书的那一簇，否则 None。

        每一道资格尺（都在模块头 ``_CONSENSUS_*``，没有一道是"看情况"）：读数与往返
        都是有限数、往返短到没被建连耗时抬高、**簇直径**（不是各自离锚点的距离）不超过
        一个量化步长、簇里 :func:`_vendor_key` 折出来至少 ``_CONSENSUS_MIN_VENDORS``
        个**独立供应商**、中位数不超过最大校正量。
        任一条不成立就不校正——宁可回退系统钟，也不拿一家之言、两个同族子域
        或一条同时喂两家的中间人链路改口径。本方法**只读不写**。
        """
        usable = [
            item
            for item in rejects
            if math.isfinite(item.offset)
            and math.isfinite(item.round_trip)
            and item.round_trip <= _CONSENSUS_MAX_RTT_SECONDS
        ]
        best: list[_Sample] = []
        ordered = sorted(usable, key=lambda item: item.offset)
        for index, anchor in enumerate(ordered):
            # 直径口径：窗口从 anchor 向右收，max-min 就是首尾差——锚点半径写法会让
            # 3/4/5 三枚连成一簇（直径 2s）却自称过了 1s 那道尺。
            window = [
                other
                for other in ordered[index:]
                if other.offset - anchor.offset <= _CONSENSUS_TOLERANCE_SECONDS
            ]
            if len(window) > len(best):
                best = window
        if len({_vendor_key(item.name) for item in best}) < _CONSENSUS_MIN_VENDORS:
            return None
        median = statistics.median([item.offset for item in best])
        if not math.isfinite(median) or abs(median) > _CONSENSUS_MAX_CORRECTION_SECONDS:
            logger.warning(
                "timesync: 互证中位偏移 %+.3fs 超过最大校正量 %.0fs（或不可用），"
                "判为系统级时间故障而非钟漂，不做校正",
                median,
                _CONSENSUS_MAX_CORRECTION_SECONDS,
            )
            return None
        return best

    def _commit_consensus(self, cluster: list[_Sample]) -> None:
        """采纳互证中位数并**用 warning 说话**：这是一条异常出口，必须让人看见。"""
        offset = statistics.median([item.offset for item in cluster])
        with self._lock:
            self._offset_seconds = offset
            self._last_success_monotonic = self._monotonic()
        logger.warning(
            "timesync: 无单一时间源落在可信上限 %+.3fs 内，改用多源互证采纳 %+.3fs"
            "（背书来源 %s；彼此离散 %.3fs；缓存 %ss）——本机系统钟确实偏了这么多，"
            "建议把系统时间同步打开，别让校正在链上长期顶着",
            self._max_drift_seconds,
            offset,
            ",".join(sorted({item.name for item in cluster})),
            max(item.offset for item in cluster) - min(item.offset for item in cluster),
            self._resync_seconds,
        )

    def _query_server(self, server: str) -> tuple[float, float] | None:
        """对单台服务器发一次 SNTP 请求，返回 ``(偏移秒, 往返秒)``；失败返回 None。

        偏移 θ = ((t1 - t0) + (t2 - t3)) / 2，其中 t0=请求发出、t1=服务器
        收到、t2=服务器应答、t3=客户端收到（均为 Unix 秒）。

        应答完整性（P3-15）：请求 transmit timestamp 填 t0，合规服务器会
        把它原样拷回应答 originate（RFC 4330 §4/§5 客户端义务），逐字节
        不匹配即伪造/重放/串线应答，丢弃；来源端口非 123、stratum 0（KOD）
        或 >15（未同步）、LI=3（告警态）同样拒收，均走轮转/回退链。
        """
        sock = None
        try:
            t0 = self._clock()
            transmit = _pack_ntp_timestamp(t0)
            if transmit is None:
                logger.debug("timesync: 本地钟 %r 编码不出可信 NTP 时刻，跳过", t0)
                return None
            request = bytearray(_CLIENT_PACKET)
            request[40:48] = transmit
            sock = self._socket_factory()
            sock.settimeout(self._timeout)
            sock.sendto(bytes(request), (server, _NTP_PORT))
            payload, addr = sock.recvfrom(_PACKET_SIZE * 2)
            t3 = self._clock()
        except OSError as exc:
            logger.debug("timesync: %s 请求失败：%s", server, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - 单台故障不拖垮轮转。
            logger.debug("timesync: %s 请求异常：%s", server, exc)
            return None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if len(payload) < _PACKET_SIZE:
            logger.debug("timesync: %s 应答过短（%d 字节）", server, len(payload))
            return None
        if addr is None or addr[1] != _NTP_PORT:
            logger.debug("timesync: %s 应答来源不可核实（%r），丢弃", server, addr)
            return None
        mode = payload[0] & 0x07
        stratum = payload[1]
        if stratum == 0:
            logger.debug("timesync: %s 返回 kiss-of-death（stratum=0）", server)
            return None
        if stratum > _MAX_VALID_STRATUM:
            logger.debug(
                "timesync: %s 应答 stratum=%d 异常（>15 未同步态），拒收（来源 %s）",
                server, stratum, addr,
            )
            return None
        if payload[0] >> 6 == 3:  # LI=3：服务器自报闰秒告警/未同步。
            logger.debug("timesync: %s 应答 LI=3（告警未同步态），拒收", server)
            return None
        if mode not in self._allowed_modes:  # 默认仅 server(4)；5 需显式开关。
            logger.debug("timesync: %s 应答模式异常（mode=%d）", server, mode)
            return None
        if payload[24:32] != request[40:48]:
            logger.debug(
                "timesync: %s 应答 originate 与请求 transmit 不匹配（来源 %s），"
                "按伪造/重放/串线丢弃",
                server, addr,
            )
            return None
        server_received = _unpack_ntp_timestamp(payload[32:40])
        server_transmitted = _unpack_ntp_timestamp(payload[40:48])
        if server_received is None or server_transmitted is None:
            logger.debug("timesync: %s 应答时间戳未置位", server)
            return None
        round_trip = t3 - t0
        if round_trip < 0 or round_trip > _MAX_RTT_SECONDS:
            logger.debug("timesync: %s 往返 %.3fs 异常，弃用", server, round_trip)
            return None
        return ((server_received - t0) + (server_transmitted - t3)) / 2.0, round_trip

    def _query_http(self, url: str) -> tuple[float, float] | None:
        """HTTPS Date 头估偏移 θ = server − (t0+t3)/2，返回 ``(偏移秒, 往返秒)``；失败 None。

        前提假设：服务器在收到请求的时刻附近生成 Date（生成点近似取
        RTT 中点）。Date 只有 1 秒粒度且按截断下发，+0.5s 把量化误差
        居中到 ±0.5s。⚠ 2026-09-29 实测**改口**：旧文案说"加上 RTT 项后整体
        精度仍在 ±1.5s 钳制口径内"——不成立。``t0`` 取自工厂调用之前，DNS+TCP+TLS
        建连整段都落在采样窗里，而建连是**单向**发生的：慢链路会把一个分毫不差的
        钟虚报成偏移（实测 3s 建连即把 skew=0 的本机报成超限并被拒收）。所以本级的
        读数只在"往返短"时才有资格：``_CONSENSUS_MAX_RTT_SECONDS`` 那道尺就是为此
        立的，单源放行仍受 ±max_drift 钳制，互证只收干净样本。
        状态码收 2xx/3xx（大站根路径 HEAD 常见 301/302 也带真 Date）。
        """
        try:
            t0 = self._clock()
            status, date_value = self._http_factory(url, self._timeout)
            t3 = self._clock()
        except OSError as exc:
            logger.debug("timesync: HTTPS 时间源 %s 请求失败：%s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - 单端点故障不拖垮兜底链。
            logger.debug("timesync: HTTPS 时间源 %s 请求异常：%s", url, exc)
            return None
        if not 200 <= status <= 399:
            logger.debug(
                "timesync: HTTPS 时间源 %s 状态码 %d，弃用", url, status
            )
            return None
        round_trip = t3 - t0
        if round_trip < 0 or round_trip > _MAX_RTT_SECONDS:
            logger.debug(
                "timesync: HTTPS 时间源 %s 往返 %.3fs 异常，弃用", url, round_trip
            )
            return None
        server_epoch = _parse_http_date(date_value)
        if server_epoch is None:
            logger.debug(
                "timesync: HTTPS 时间源 %s 无可解析 Date 头（%r）", url, date_value
            )
            return None
        return server_epoch + 0.5 - (t0 + t3) / 2.0, round_trip


# ---------------------------------------------------------------------------
# 进程级共享实例：默认禁用（纯系统钟、零网络）；由真实 config 绑定后启用。
# ---------------------------------------------------------------------------

_SHARED: TimeSync | None = None
# 签名五元组：(enabled, servers, max_drift_ms, http_enabled, http_urls)。
_SHARED_SIGNATURE: tuple[bool, str, int, bool, str] | None = None
_SHARED_LOCK = threading.Lock()


def configure_from(config: object) -> TimeSync:
    """用运行时配置绑定/更新共享校时器（幂等；签名不变则复用）。

    ``bot_time_sync_enabled`` 字段**缺失**（测试用局部 SimpleNamespace）视作
    禁用——显式配置才是启用信号，保证既有离线测试零网络零等待。
    """
    global _SHARED, _SHARED_SIGNATURE
    enabled_attr = getattr(config, "bot_time_sync_enabled", None)
    enabled = bool(enabled_attr)
    servers_raw = str(
        getattr(config, "bot_time_sync_servers", "") or DEFAULT_SERVERS_RAW
    )
    try:
        max_drift_ms = int(
            getattr(config, "bot_time_sync_max_drift_ms", DEFAULT_MAX_DRIFT_MS)
        )
    except (TypeError, ValueError):
        max_drift_ms = DEFAULT_MAX_DRIFT_MS
    # HTTPS 兜底（R3 停摆批）：字段**缺失**（旧测试局部 SimpleNamespace）
    # 视作不启用——与 enabled 同款口径，保住既有离线测试零网络零等待。
    http_enabled = bool(getattr(config, "bot_time_sync_http_enabled", None))
    http_urls_raw = str(
        getattr(config, "bot_time_sync_http_url", "") or DEFAULT_HTTP_TIME_URLS_RAW
    )
    signature = (enabled, servers_raw, max_drift_ms, http_enabled, http_urls_raw)
    with _SHARED_LOCK:
        if _SHARED is not None and _SHARED_SIGNATURE == signature:
            return _SHARED
        servers = [item.strip() for item in servers_raw.split(",") if item.strip()]
        http_urls = [item.strip() for item in http_urls_raw.split(",") if item.strip()]
        _SHARED = TimeSync(
            servers,
            enabled=enabled,
            max_drift_ms=max_drift_ms,
            http_enabled=http_enabled,
            http_urls=http_urls,
        )
        _SHARED_SIGNATURE = signature
        return _SHARED


def now() -> datetime:
    """共享校时器的"现在"（未绑定配置时 = 系统钟，禁联网）。

    修复记录（并行视觉席实跑定位）：本函数体内对 ``_SHARED`` 有赋值分支，
    必须声明 ``global``——否则首读即 UnboundLocalError，毒化 base_router
    的 import 链（reminders → timesync 经能力层被路由注册表引用）。
    """
    global _SHARED, _SHARED_SIGNATURE
    with _SHARED_LOCK:
        shared = _SHARED
    if shared is None:
        # 尚无配置绑定：落一个禁用态默认实例（签名不同会被 configure_from 换掉）。
        with _SHARED_LOCK:
            if _SHARED is None:
                _SHARED = TimeSync(
                    [item.strip() for item in DEFAULT_SERVERS_RAW.split(",")],
                    enabled=False,
                )
                _SHARED_SIGNATURE = (
                    False,
                    DEFAULT_SERVERS_RAW,
                    DEFAULT_MAX_DRIFT_MS,
                    False,
                    DEFAULT_HTTP_TIME_URLS_RAW,
                )
            shared = _SHARED
    return shared.now()


def reset_shared_for_tests() -> None:
    """测试专用：清空共享实例（各用例互不串状态）。"""
    global _SHARED, _SHARED_SIGNATURE
    with _SHARED_LOCK:
        _SHARED = None
        _SHARED_SIGNATURE = None


__all__ = [
    "DEFAULT_HTTP_TIME_URLS_RAW",
    "DEFAULT_MAX_DRIFT_MS",
    "DEFAULT_SERVERS_RAW",
    "TimeSync",
    "configure_from",
    "now",
    "reset_shared_for_tests",
]
