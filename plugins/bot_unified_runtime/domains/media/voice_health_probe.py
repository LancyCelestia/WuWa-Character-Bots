"""语音引擎只读健康探针（bot.tts，U-17=C 案，Wave G T79；蓝本=契约层 §4.2 落点）。

**地位**：引擎健康态的唯一只读探测口（T14 审计 P1-2 判定「全仓无任何 TTS 健康探测」
后的收口件）。宪法边界（progress.md G2-R2 用户裁定）：

- 引擎生命周期=**人工脚本唯一入口**：本模块**只读探测**——零常驻线程、零后台
  轮询、**绝不惰性拉起/代启动/重启引擎**；触发点=被调用才查（设计给
  ``/bot status`` 查询与退避窗进入两处接线，接线归 echo/收口席，见 report-T79）；
- 不可达 → 构造 ``OperationalIssue(kind="tts_service_unreachable", retryable=True)``
  （复用既有 kind，**禁新造**——契约层 S11 裁定），交给中央告警链
  （``alerts.notify_operational_issue``，缺省 300s 抑制）；本模块另有**同窗不重复
  构造**闸：``_ISSUE_COOLDOWN_SECONDS``（对齐中央 ``AdminAlertSuppression`` 缺省
  窗），同一冷却窗内重复探测不再造新 issue（防双保险变双刷屏）；
- 可达且上次不可达=**恢复沿**（``VoiceEngineHealth.recovered``，供状态行显示
  「已恢复」），恢复不构造 issue（好事不出告警）；
- **fail-open**：探针自身任何异常不冒泡（debug 日志留痕），返回 unknown 态——
  健康探测自身坏了不能把业务链路拖死。

线程纪律（与上游退避真闸 T57 同风格）：模块级锁只包内存态读写，**TCP 连接绝不
持锁**（探针最坏 2s，持锁会把并发状态查询串行化）。

纯库模块：不 import tts.py（退避态经 ``_tts_backoff_reason`` 惰性只读访问，
T75 若改名则优雅降级为空串——见 report-T79 访问器清单）；测试全桩零真实网络。
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from plugins.bot_unified_runtime.contracts import OperationalIssue, new_debug_id
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 探针短超时（简报硬规格：≤2s；入参越界一律钳回本域，防调用方把探针拖成慢请求）。
_PROBE_TIMEOUT_SECONDS = 2.0
_PROBE_TIMEOUT_MIN_SECONDS = 0.1
# 同窗不重复构造闸：对齐中央 AdminAlertSuppression 缺省窗（alerts.py:159 300.0）。
_ISSUE_COOLDOWN_SECONDS = 300.0
# 与 tts.py `_ISSUE_SUMMARY_MAX_CHARS` 同口径（issue 会进诊断卡与管理员私聊）。
_ISSUE_SUMMARY_MAX_CHARS = 200
# config 缺省与 config.py `bot_tts_api_url` 缺省一致（只读兜底，不替代 config）。
_DEFAULT_API_URL = "http://127.0.0.1:9880"

_STATE_REACHABLE = "reachable"
_STATE_UNREACHABLE = "unreachable"
_STATE_UNKNOWN = "unknown"

# 测试钟替换点（monkeypatch 本名即可控制冷却窗推进）。
_monotonic = time.monotonic


@dataclass(frozen=True)
class VoiceEngineHealth:
    """一次探测的结构化健康态。

    ``reachable`` 三态：True=可达 / False=不可达 / None=未知（地址坏、探针自身
    异常等 fail-open 形态）；``recovered``=本次可达且上次探测不可达（恢复沿）。
    """

    state: str
    reachable: bool | None
    latency_ms: float | None
    checked_at: float
    endpoint: str = ""
    detail: str = ""
    recovered: bool = False


# ---------------------------------------------------------------------------
# 模块态（进程内记忆：上次探测结论 + 冷却窗记账）。锁纪律见模块 docstring。
# ---------------------------------------------------------------------------

_PROBE_LOCK = threading.Lock()
_probe_flagged_unreachable: bool = False
_last_unreachable_at: float = 0.0  # ``_monotonic()`` 刻度
_last_failure_detail: str = ""
_last_issue: OperationalIssue | None = None


def _reset_state() -> None:
    """测试隔离口（惯例同 tts 族：进程内全局逐例清零，生产勿调）。"""
    global _probe_flagged_unreachable, _last_unreachable_at, _last_failure_detail
    global _last_issue
    with _PROBE_LOCK:
        _probe_flagged_unreachable = False
        _last_unreachable_at = 0.0
        _last_failure_detail = ""
        _last_issue = None


def last_operational_issue() -> OperationalIssue | None:
    """最近一次构造的不可达 issue（供异步侧投喂中央告警链，见 report-T79）。

    **唯一生产读者** = ``voice_health_alert.flush_probe_issue_to_alerts``（S-OBS 接线，
    全树只此一处，由 ``tests/test_voice_health_alert_sink.py`` 活性锁钉死）；除此之外
    生产不得再增第二读者（禁第二消费点=禁把同一 issue 分两路投喂）。
    """
    with _PROBE_LOCK:
        return _last_issue


def clear_operational_issue() -> None:
    """清空 pending issue（消费者投递成功后的 drain，恢复沿的自动清账共用此口）。

    与 ``last_operational_issue`` 配对：读→投→清，一条 issue 至多投一次；探针侧
    ``_ISSUE_COOLDOWN_SECONDS`` 与中央 ``AdminAlertSuppression`` 各自折叠重复，消费者
    本身**不再放第三把时间闸**（去重不自造节流）。
    """
    global _last_issue
    with _PROBE_LOCK:
        _last_issue = None


# ---------------------------------------------------------------------------
# 端点解析 + TCP 探测
# ---------------------------------------------------------------------------


def parse_engine_endpoint(api_url: str) -> tuple[str, int] | None:
    """``bot_tts_api_url`` → ``(host, port)``；空/不可解析返回 None（不猜）。"""
    raw = str(api_url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname
        if not host:
            return None
        port = parts.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return host, port


def _tcp_connect(host: str, port: int, timeout: float) -> Any:
    """唯一真实网络触点（测试 monkeypatch 本名即可全桩，零真实网络）。"""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.close()
        return sock


def _api_url_from_config(config: Any) -> str:
    return str(getattr(config, "bot_tts_api_url", "") or _DEFAULT_API_URL)


def _clamp_timeout(timeout_seconds: float) -> float:
    try:
        value = float(timeout_seconds)
    except (TypeError, ValueError):
        return _PROBE_TIMEOUT_SECONDS
    return min(max(value, _PROBE_TIMEOUT_MIN_SECONDS), _PROBE_TIMEOUT_SECONDS)


def _probe_once(api_url: str, timeout: float) -> VoiceEngineHealth:
    endpoint = parse_engine_endpoint(api_url)
    if endpoint is None:
        return VoiceEngineHealth(
            state=_STATE_UNKNOWN,
            reachable=None,
            latency_ms=None,
            checked_at=time.time(),
            detail="引擎地址未配置或无法解析",
        )
    host, port = endpoint
    started = _monotonic()
    try:
        _tcp_connect(host, port, timeout)
    except TimeoutError:  # py3.10+ 起 socket.timeout 即本类型（ruff UP041）
        detail = f"连接超时（>{timeout:.0f}s）"
    except ConnectionRefusedError:
        detail = "连接被拒绝"
    except OSError as exc:
        detail = f"连接失败：{type(exc).__name__}"
    else:
        latency_ms = (_monotonic() - started) * 1000.0
        return VoiceEngineHealth(
            state=_STATE_REACHABLE,
            reachable=True,
            latency_ms=latency_ms,
            checked_at=time.time(),
            endpoint=f"{host}:{port}",
        )
    return VoiceEngineHealth(
        state=_STATE_UNREACHABLE,
        reachable=False,
        latency_ms=None,
        checked_at=time.time(),
        endpoint=f"{host}:{port}",
        detail=detail,
    )


# ---------------------------------------------------------------------------
# 告警衔接（同窗不重复构造）+ 恢复沿
# ---------------------------------------------------------------------------


def _build_unreachable_issue(health: VoiceEngineHealth) -> OperationalIssue:
    raw = f"语音引擎不可达：{health.endpoint}，{health.detail}".rstrip("，, ")
    return OperationalIssue(
        stage="tts",
        # S11 裁定：复用既有 kind 不新造（退避/探针=可重试类不可达的子形态）。
        kind="tts_service_unreachable",
        retryable=True,
        debug_id=new_debug_id("tts_probe"),
        # 探针无消息上下文，debug_id 走惯例前缀生成；摘要必过打码（AGENTS 铁律 3）。
        safe_summary=redact_local_secrets(raw)[:_ISSUE_SUMMARY_MAX_CHARS].strip(),
    )


def _absorb(health: VoiceEngineHealth) -> VoiceEngineHealth:
    """把探测结论记入模块态；不可达时按冷却窗决定是否构造新 issue。

    临界区只有纯内存操作（issue 构造含打码正则，纯 CPU 不触网），HTTP 绝不持锁。
    """
    global _probe_flagged_unreachable, _last_unreachable_at, _last_failure_detail
    global _last_issue
    with _PROBE_LOCK:
        if health.state == _STATE_REACHABLE:
            recovered = _probe_flagged_unreachable
            _probe_flagged_unreachable = False
            _last_failure_detail = ""  # 恢复即清账：状态行不再背旧失败
            _last_issue = None  # S-OBS 陈旧不粘滞：引擎恢复=撤回未投的旧故障 issue，
            #   否则消费者会把「已恢复」的历史不可达再报给运维（T84 点名的失效形态）。
            if recovered:
                health = replace(health, recovered=True)
            return health
        if health.state != _STATE_UNREACHABLE:
            return health  # unknown 态不记账、不构造 issue（fail-open 语义）
        now = _monotonic()
        new_incident = (
            not _probe_flagged_unreachable
            or (now - _last_unreachable_at) >= _ISSUE_COOLDOWN_SECONDS
        )
        if new_incident:
            _last_issue = _build_unreachable_issue(health)
            _last_unreachable_at = now
        _probe_flagged_unreachable = True
        _last_failure_detail = health.detail
        return health


# ---------------------------------------------------------------------------
# 上游退避态只读集成（T57/T75 面）
# ---------------------------------------------------------------------------


def _tts_backoff_reason() -> str:
    """只读上游 tts 退避闸原因（``_backoff_reason``；T75 改名则优雅降级空串）。

    惰性导入：探针模块不与 tts.py 建立导入期硬依赖（T75 在飞，禁自改其面；
    公共访问器需求清单见 report-T79）。
    """
    try:
        from plugins.bot_unified_runtime.domains.media.capabilities import (
            tts as tts_mod,
        )
    except Exception:  # noqa: BLE001 - 集成面 fail-open，缺位不拖死探针
        return ""
    accessor = getattr(tts_mod, "_backoff_reason", None)
    if not callable(accessor):
        return ""
    try:
        return str(accessor() or "")
    except Exception:  # noqa: BLE001 - 同上
        return ""


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def probe_voice_engine(
    config: Any = None,
    *,
    api_url: str | None = None,
    timeout_seconds: float = _PROBE_TIMEOUT_SECONDS,
) -> VoiceEngineHealth:
    """只读探测语音引擎 TCP 连通性（惰性：被调用才查，零常驻零轮询）。

    - 地址来源：显式 ``api_url`` > ``config.bot_tts_api_url`` > 内置缺省；
    - 超时钳制 ≤2s；任何内部异常 fail-open 返回 unknown（debug 日志留痕）；
    - 不可达按冷却窗构造 ``tts_service_unreachable`` issue（同窗不重复）。
    """
    try:
        url = api_url if api_url is not None else _api_url_from_config(config)
        health = _probe_once(url, _clamp_timeout(timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - 探针绝不冒泡（U-17=C fail-open）
        logger.debug("voice health probe internal error: %s", exc)
        health = VoiceEngineHealth(
            state=_STATE_UNKNOWN,
            reachable=None,
            latency_ms=None,
            checked_at=time.time(),
            detail="探针内部异常（fail-open）",
        )
    return _absorb(health)


def voice_status_line(
    config: Any = None,
    *,
    health: VoiceEngineHealth | None = None,
) -> str:
    """/bot status 一行式语音摘要（接线归收口席，禁自改 echo.py）。

    - 开关关闭：``语音：disabled``——**绝不真探**（引擎根本不在配置面）；
    - 未传 ``health`` 时惰性触发一次探测（触发点 1：status 查询）；
    - 行内集成上游退避公共态（触发点 2 的态），原因串必过打码。
    """
    if config is not None and not bool(getattr(config, "bot_tts_enabled", False)):
        return "语音：disabled，engine=not_probed"
    if health is None:
        health = probe_voice_engine(config)
    endpoint = health.endpoint or "未知地址"
    if health.state == _STATE_REACHABLE:
        latency = (
            f"，{health.latency_ms:.0f}ms" if health.latency_ms is not None else ""
        )
        line = f"语音：enabled，engine=reachable（{endpoint}{latency}）"
        if health.recovered:
            line += "，note=已恢复"
    elif health.state == _STATE_UNREACHABLE:
        line = f"语音：enabled，engine=unreachable（{endpoint}，{health.detail}）"
    else:
        line = f"语音：enabled，engine=unknown（{health.detail or '状态未知'}）"
    backoff = _tts_backoff_reason()
    if backoff:
        line += f"，backoff={redact_local_secrets(backoff)}"
    return line
