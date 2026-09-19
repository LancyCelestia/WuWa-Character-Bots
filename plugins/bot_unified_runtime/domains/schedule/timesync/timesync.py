"""联网授时（timesync）：纯 stdlib SNTP 客户端，为提醒链路提供校正时间。

设计（2026-09-13 六域批，用户裁定五点之一）：
- **纯 stdlib**：socket + struct 手搓 SNTPv4 客户端报文（48 字节，客户端
  模式），无任何第三方依赖、无子进程。
- **绝不改系统钟**：只算偏移量 ``offset``（服务器时刻 - 本地钟），``now()``
  返回 ``系统钟 + offset`` 的 aware 本地时间。系统时间永远原样。
- **服务器轮转**：列表来自 ``BOT_TIME_SYNC_SERVERS``（逗号分隔），每个
  2s 超时逐个试，取首个成功且偏移可信的；全失败 → 回退系统钟 + 告警。
- **HTTPS 时间源兜底（R3 停摆批 2026-09-17）**：生产 UDP 123 被墙时
  （``全部 NTP 服务器不可达``告警实弹），NTP 全败后改走 HTTPS ``Date``
  响应头（RFC 7231）估算偏移：HEAD 请求国内可达端点（默认
  baidu/taobao/qq，``BOT_TIME_SYNC_HTTP_URL`` 可换），θ = server −
  (t0+t3)/2（Date 只有 1 秒粒度，+0.5s 把量化误差居中）；失败链
  NTP → HTTPS → 系统钟，每级一行日志，复用既有 ±1.5s 偏移钳制与 RTT
  上限。仅收 ``https://``（明文 http 时间可被中间人伪造，不作为授时源）。
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
"""

from __future__ import annotations

import http.client
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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

DEFAULT_SERVERS_RAW = "ntp.aliyun.com,cn.ntp.org.cn,pool.ntp.org"
DEFAULT_MAX_DRIFT_MS = 1500
# HTTPS 时间源兜底（R3 停摆批）：UDP 123 被墙时的国内可达默认端点
# （HEAD 响应都带 RFC 7231 Date 头；逗号分隔，BOT_TIME_SYNC_HTTP_URL 可换）。
DEFAULT_HTTP_TIME_URLS_RAW = (
    "https://www.baidu.com,https://www.taobao.com,https://www.qq.com"
)


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
        self._socket_factory = socket_factory or socket.socket
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

    # -- 查询面 ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def offset_seconds(self) -> float | None:
        with self._lock:
            return self._offset_seconds

    def now(self) -> datetime:
        """校正后的 aware 本地时间；未启用/未校准/同步失败 = 系统钟。"""
        self._maybe_sync()
        with self._lock:
            offset = self._offset_seconds
        base = self._clock() + (offset or 0.0)
        try:
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

    # -- 同步 -----------------------------------------------------------------

    def _maybe_sync(self) -> None:
        """按缓存/冷却节奏决定是否联网重校（每次 now() 都过这里，须快）。"""
        if not self._enabled:
            return
        moment = self._monotonic()
        with self._lock:
            has_offset = self._offset_seconds is not None
            last_attempt = self._last_attempt_monotonic
            last_success = self._last_success_monotonic
        if has_offset and moment - last_success < self._resync_seconds:
            return  # 缓存新鲜。
        if not has_offset and moment - last_attempt < self._retry_seconds:
            return  # 失败冷却中，不逐消息重试。
        self._sync_now(moment)

    def _sync_now(self, moment: float) -> None:
        """强制同步一轮：NTP 轮转 → HTTPS Date 兜底 → 回退系统钟。

        失败链每级一行日志（NTP 全败一行 info 转 HTTPS、HTTPS 端点成功
        一行 info/失败 debug、整体回退一行 warning），钳制口径与 NTP 一致。
        """
        with self._lock:
            self._last_attempt_monotonic = moment
        for server in self._servers:
            offset = self._query_server(server)
            if offset is None:
                continue
            if self._apply_offset(server, offset, source="NTP"):
                return
        if self._http_enabled and self._http_urls:
            logger.info(
                "timesync: NTP 全部不可达或偏移不可信（%d 台），转 HTTPS 时间源（%d 个）",
                len(self._servers),
                len(self._http_urls),
            )
            for url in self._http_urls:
                offset = self._query_http(url)
                if offset is None:
                    continue
                if self._apply_offset(url, offset, source="HTTPS"):
                    return
        # 全失败（不可达/超时/全部偏移不可信）：回退系统钟。
        with self._lock:
            self._offset_seconds = None
        logger.warning(
            "timesync: 全部时间源不可达或偏移不可信（servers=%s; http=%s），回退系统钟",
            ",".join(self._servers) or "<empty>",
            ",".join(self._http_urls) if self._http_enabled else "<disabled>",
        )

    def _apply_offset(self, name: str, offset: float, *, source: str) -> bool:
        """偏移钳制 + 入账 + 成功日志；超限拒收记 warning 返回 False。"""
        if self._max_drift_seconds > 0 and abs(offset) > self._max_drift_seconds:
            logger.warning(
                "timesync: %s（%s）应答偏移 %+.3fs 超过可信上限 %+.3fs，拒收",
                name,
                source,
                offset,
                self._max_drift_seconds,
            )
            return False
        with self._lock:
            self._offset_seconds = offset
            self._last_success_monotonic = self._monotonic()
        logger.info(
            "timesync: 与 %s（%s）校准成功，本地钟偏移 %+.3fs（缓存 %ss）",
            name,
            source,
            offset,
            self._resync_seconds,
        )
        return True

    def _query_server(self, server: str) -> float | None:
        """对单台服务器发一次 SNTP 请求，返回偏移秒数；失败返回 None。

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
        return ((server_received - t0) + (server_transmitted - t3)) / 2.0

    def _query_http(self, url: str) -> float | None:
        """HTTPS Date 头估偏移 θ = server − (t0+t3)/2；失败返回 None。

        前提假设：服务器在收到请求的时刻附近生成 Date（生成点近似取
        RTT 中点）。Date 只有 1 秒粒度且按截断下发，+0.5s 把量化误差
        居中到 ±0.5s——加上 RTT 项后整体精度仍在 ±1.5s 钳制口径内。
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
        return server_epoch + 0.5 - (t0 + t3) / 2.0


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
