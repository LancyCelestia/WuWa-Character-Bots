"""统一错误报告卡（运行异常诊断卡，2026-09-13）。

能力执行异常（RuntimePipeline._internal_error 捕获点）时，向触发者回一张
统一诊断卡：人话区（守岸人口吻）/ 触发回显（≤80 字符脱敏）/ 栈摘录（末 N 帧
脱敏）/ 触发方法（capability_id+函数名+RouteKind）/ 脱敏配置快照（键名白名单：
与能力同前缀的 config 字段，密钥类一律 ***）/ 版本与构建 / 平台与协议 /
IDs 与时间 / 求助指引。控制台完整栈仍走既有 runtime/alerts 告警（本模块不改
告警语义，只做旁路补充）。

纪律：
- 全链 fail-open：本模块任何异常都不允许影响回执路径（pipeline 侧再包一层）。
- ``bot_error_card_enabled=false`` 时零动作（行为与现状字节级一致）。
- 防刷屏：同会话冷却 ``bot_error_card_cooldown_seconds``（进程内滑动窗）；
  冷却期内降级为一句守岸人口吻纯文本。
- LLM 超时类既有静默策略（capabilities/chat.py 话术池）保持不变——本模块只
  挂在能力异常 catch 点，不进 LLM 链路。

发送路径：诊断卡在 pipeline 层直接构造 SendRequest 提交 send_queue（与正常
回复同一下游），不经 __init__.py（该文件本批次禁止触碰）。

两段式异步化（2026-09-14 P0 修复，A-rec）：
- 异常回执路径即时返回：冷却闸通过后先提交「文本回执」（request_id 沿用
  原消息 id → matcher 侧 _find_sent_request 立即内联首投），毫秒级，零渲染
  阻塞；诊断卡渲染转本模块专用单线程渲染通道（渲染线程上无事件循环，
  Playwright 同步 API 的 Sync-inside-asyncio 守卫不再触发——错误卡渲染
  禁止在事件循环线程直接调 Playwright）。
- 渲染成功 → 后台提交图片卡（request_id=原 id + "-card"，dedupe_key ":card"
  后缀），经 send_queue worker 补发；渲染失败 → 补发全量诊断文本（诊断
  完整性不因渲染失败丢失）。fail-open：后台任务任何异常只 log，文本回执
  已先行，卡静默放弃。
- 门禁语义（by design）：错误卡只会在已通过 quiet_hours/限流门禁的同一
  对话回合内触发（门禁在 pipeline._prepare 先行），本模块有意不复查门禁
  （复查=同义反复，复查限流还会双扣预算）；防刷屏由会话冷却闸承担。
  审计标签 ``gate:bypass_by_design`` 把该取舍显式化。
"""

from __future__ import annotations

import atexit
import logging
import os
import random
import re
import subprocess
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    PrivacyLevel,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 进程启动单调时钟锚点：模块在插件加载（进程启动流程）时导入，差值即运行时长。
_PROCESS_START_MONOTONIC = time.monotonic()

# 人话区话术池：守岸人口吻——系统性坦诚（承认故障但保持角色），一句认错 +
# 一句指引，禁愧疚腔（红线：不攻击/不卖惨/不 AI 腔）。会话内轮换避免连发重复。
_HUMAN_TEXTS: tuple[str, ...] = (
    "这条指令处理的时候出了岔子（{exc}），细节都在卡上了。要重试就再发一次。",
    "处理到一半卡住了（{exc}）。诊断都在卡上，稍后重试就好。",
    "这次执行没走通（{exc}）。原因我记下了，卡上有完整线索。",
    "链路抖了一下没接稳（{exc}）。细节都在卡上，再发一次就行。",
)
_HUMAN_CURSOR_LOCK = threading.Lock()
_HUMAN_CURSOR: dict[str, int] = {}

# 冷却期降级纯文本（守岸人口吻，一句）。
_COOLDOWN_LINE = (
    "又有一条指令出了岔子（{exc}），刚才那张卡已经发过啦——细节还在上面，先看那张。"
)

_HELP_TEXT = "把这张卡截图发给创造者（澜汐/霞月）即可，信息已齐备且脱敏；控制台日志另有完整栈。"

# 文本回执尾注：告知诊断卡随后补发（两段式，2026-09-14 P0 修复）。
_ACK_FOLLOWUP_HINT = "详细诊断卡随后补发。"

# 触发回显上限（用户裁定 ≤80 字符，脱敏后截断）。
_TRIGGER_ECHO_MAX_CHARS = 80

# 栈摘录帧数钳位与单帧源码行截断。
_STACK_FRAMES_MIN = 1
_STACK_FRAMES_MAX = 30
_FRAME_LINE_MAX_CHARS = 160

# 配置快照：键名白名单 = 与能力同前缀（bot_<模块>_）的 Config 字段；
# 命中密钥类命名的一律 ***（值不看内容直接掩码，双保险）。
_SECRET_KEY_RE = re.compile(r"(token|secret|api_key|apikey|password|passwd|cookie)", re.IGNORECASE)
_CONFIG_SNAPSHOT_MAX_ROWS = 12

# 适配器 → 协议标准展示名（未知回退原值）。
_ADAPTER_PROTOCOLS: dict[str, str] = {
    "onebot": "OneBot V11",
    "onebot_v11": "OneBot V11",
    "onebot_v12": "OneBot V12",
    "telegram": "Telegram Bot API",
    "mail": "SMTP/IMAP",
    "console": "本地控制台",
}


# ==================== 设置解析（driver config → env → 默认） ====================
@dataclass(frozen=True)
class ErrorCardSettings:
    """错误卡三开关（config.py 已预置三键，getattr 缺省使用）。"""

    enabled: bool = True
    cooldown_seconds: int = 60
    stack_frames: int = 8


_BOOL_TRUE = frozenset({"1", "true", "yes", "on"})
_BOOL_FALSE = frozenset({"0", "false", "no", "off"})


def _parse_bool(raw: str) -> bool | None:
    value = (raw or "").strip().lower()
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    return None


def _resolve_settings() -> ErrorCardSettings:
    """三键解析链：nonebot driver config → 环境变量 → 缺省。

    与 pipeline._resolve_chat_pool_workers 同源模式：单元测试/裸脚本场景
    nonebot 未初始化时自动短路落到 env/缺省。仅在异常路径调用，无热路径成本。
    """
    raw_values: dict[str, list[object]] = {
        "enabled": [],
        "cooldown": [],
        "frames": [],
    }
    try:
        import nonebot

        driver_config = nonebot.get_driver().config
        raw_values["enabled"].append(
            getattr(driver_config, "bot_error_card_enabled", None)
        )
        raw_values["cooldown"].append(
            getattr(driver_config, "bot_error_card_cooldown_seconds", None)
        )
        raw_values["frames"].append(
            getattr(driver_config, "bot_error_card_stack_frames", None)
        )
    except Exception:  # noqa: BLE001, S110 - 非生产运行环境，落到下一级。
        pass
    raw_values["enabled"].append(os.environ.get("BOT_ERROR_CARD_ENABLED"))
    raw_values["cooldown"].append(os.environ.get("BOT_ERROR_CARD_COOLDOWN_SECONDS"))
    raw_values["frames"].append(os.environ.get("BOT_ERROR_CARD_STACK_FRAMES"))

    enabled = True
    for raw in raw_values["enabled"]:
        if isinstance(raw, bool):
            enabled = raw
            break
        if isinstance(raw, str):
            parsed = _parse_bool(raw)
            if parsed is not None:
                enabled = parsed
                break

    def _int_of(values: list[object], default: int) -> int:
        for raw in values:
            if raw is None or isinstance(raw, bool):
                continue
            try:
                return int(str(raw).strip())
            except (TypeError, ValueError):
                continue
        return default

    cooldown = _int_of(raw_values["cooldown"], 60)
    frames = _int_of(raw_values["frames"], 8)
    return ErrorCardSettings(
        enabled=enabled,
        cooldown_seconds=max(0, cooldown),
        stack_frames=max(
            _STACK_FRAMES_MIN, min(_STACK_FRAMES_MAX, frames)
        ),
    )


# ==================== 冷却闸（进程内滑动窗） ====================
class ErrorCardGate:
    """同会话冷却闸：allow() 通过并记账；窗口内拒绝（降级纯文本）。

    纯 threading.Lock 计数，无事件循环绑定原语（跨 loop 与测试安全）；
    会话表有界（512），淘汰最旧会话防长期运行内存膨胀。
    """

    _MAX_SESSIONS = 512

    def __init__(
        self,
        cooldown_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._last_emit: dict[str, float] = {}
        self._order: deque[str] = deque()

    def allow(self, session_id: str) -> bool:
        now = self._clock()
        with self._lock:
            if (
                session_id in self._last_emit
                and (now - self._last_emit[session_id]) < self._cooldown
            ):
                return False
            if session_id not in self._last_emit:
                self._order.append(session_id)
                while len(self._order) > self._MAX_SESSIONS:
                    evicted = self._order.popleft()
                    self._last_emit.pop(evicted, None)
            self._last_emit[session_id] = now
            return True

    @property
    def cooldown_seconds(self) -> float:
        return self._cooldown

    def seconds_remaining(self, session_id: str) -> float:
        now = self._clock()
        with self._lock:
            last = self._last_emit.get(session_id)
        if last is None:
            return 0.0
        return max(0.0, self._cooldown - (now - last))


_MODULE_GATE_LOCK = threading.Lock()
_MODULE_GATE: ErrorCardGate | None = None


def _module_gate(cooldown_seconds: float) -> ErrorCardGate:
    """进程级共享闸（冷却秒数变化时重建——热改 config 需重启，此为兜底）。"""
    global _MODULE_GATE
    with _MODULE_GATE_LOCK:
        if (
            _MODULE_GATE is None
            or _MODULE_GATE.cooldown_seconds != float(cooldown_seconds)
        ):
            _MODULE_GATE = ErrorCardGate(cooldown_seconds)
        return _MODULE_GATE


# ==================== 诊断收集 ====================
def _persona_text(session_id: str, exc_type: str) -> str:
    """人话区：会话内轮换（无会话回退随机），同会话连发不重复。"""
    count = len(_HUMAN_TEXTS)
    if not session_id:
        template = _HUMAN_TEXTS[random.randrange(count)]
        return template.format(exc=exc_type)
    with _HUMAN_CURSOR_LOCK:
        offset = _HUMAN_CURSOR.get(session_id, 0)
        _HUMAN_CURSOR[session_id] = (offset + 1) % count
        while len(_HUMAN_CURSOR) > 512:
            _HUMAN_CURSOR.pop(next(iter(_HUMAN_CURSOR)), None)
    return _HUMAN_TEXTS[offset % count].format(exc=exc_type)


def _trigger_echo(message: IncomingMessage) -> str:
    raw = re.sub(r"\s+", " ", (message.plain_text or "")).strip()
    redacted = redact_local_secrets(raw)
    if len(redacted) > _TRIGGER_ECHO_MAX_CHARS:
        redacted = redacted[: _TRIGGER_ECHO_MAX_CHARS - 1] + "…"
    return redacted


def _stack_excerpt(exc: Exception, frames_n: int) -> list[str]:
    """末 N 帧摘录（文件名:行号 in 函数: 源码行），逐行过 redact_local_secrets。"""
    tb = exc.__traceback__
    if tb is None:
        return []
    try:
        extracted = traceback.extract_tb(tb)
    except Exception:  # noqa: BLE001 - 栈提取失败降级为空摘录。
        return []
    lines: list[str] = []
    for frame in extracted[-frames_n:]:
        source = (frame.line or "").strip()
        if len(source) > _FRAME_LINE_MAX_CHARS:
            source = source[: _FRAME_LINE_MAX_CHARS - 1] + "…"
        raw = f"  {Path(frame.filename).name}:{frame.lineno} in {frame.name}: {source}"
        lines.append(redact_local_secrets(raw))
    return lines


_ROUTE_KIND_CACHE: dict[str, str] | None = None
_ROUTE_KIND_LOCK = threading.Lock()


def _route_kind_label(capability_id: str) -> str:
    """capability_id → RouteKind 展示名（base_router 注册表反查，失败 unknown）。"""
    global _ROUTE_KIND_CACHE
    with _ROUTE_KIND_LOCK:
        if _ROUTE_KIND_CACHE is None:
            mapping: dict[str, str] = {}
            try:
                from plugins.bot_unified_runtime.runtime.base_router import (
                    ROUTE_RULES,
                )

                for rule in ROUTE_RULES:
                    mapping.setdefault(rule.capability_id, rule.kind.name)
            except Exception:  # noqa: BLE001 - 路由反查失败降级 unknown。
                mapping = {}
            _ROUTE_KIND_CACHE = mapping
    kind = _ROUTE_KIND_CACHE.get(capability_id)
    return f"RouteKind.{kind}" if kind else "unknown"


def _innermost_frame_name(stack_lines: list[str]) -> str:
    """取栈摘录最内帧函数名（格式 ``  file:line in name: src``）。"""
    if not stack_lines:
        return "unknown"
    last = stack_lines[-1]
    marker = " in "
    if marker in last:
        tail = last.rsplit(marker, 1)[1]
        return tail.split(":", 1)[0].strip() or "unknown"
    return "unknown"


def _default_config_getter(name: str) -> object:
    """生产配置读取：nonebot driver config（bot_* 键挂在 driver config 上）。"""
    try:
        import nonebot

        return getattr(nonebot.get_driver().config, name, None)
    except Exception:  # noqa: BLE001 - 非生产环境快照为空。
        return None


def _config_snapshot(
    capability_id: str,
    config_getter: Callable[[str], object],
) -> list[dict[str, str]]:
    """同前缀白名单配置快照：bot.<module> → bot_<module>_；密钥类一律 ***。"""
    module = capability_id.removeprefix("bot.").replace(".", "_")
    prefix = f"bot_{module}_"
    try:
        from plugins.bot_unified_runtime.config import Config

        candidates = [
            name for name in Config.model_fields if name.startswith(prefix)
        ]
    except Exception:  # noqa: BLE001 - 配置模型不可用时快照为空。
        candidates = []
    rows: list[dict[str, str]] = []
    for name in sorted(candidates):
        if _SECRET_KEY_RE.search(name):
            value = "***"
        else:
            raw = config_getter(name)
            if raw is None:
                continue
            value = redact_local_secrets(str(raw))
        rows.append({"label": name, "value": value})
        if len(rows) >= _CONFIG_SNAPSHOT_MAX_ROWS:
            break
    return rows


_GIT_CACHE: str | None = None
_GIT_LOCK = threading.Lock()


def _git_build_info() -> str:
    """构建信息 = git 短哈希 + 提交日期（启动后首次调用缓存一次，取不到 unknown）。"""
    global _GIT_CACHE
    with _GIT_LOCK:
        if _GIT_CACHE is not None:
            return _GIT_CACHE
        info = "unknown"
        try:
            repo_root = Path(__file__).resolve().parents[3]
            if (repo_root / ".git").exists():
                head = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                date = subprocess.run(
                    ["git", "log", "-1", "--format=%cd", "--date=short"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                commit = (head.stdout or "").strip()
                commit_date = (date.stdout or "").strip()
                if commit:
                    info = f"{commit} ({commit_date or 'date unknown'})"
        except Exception:  # noqa: BLE001 - git 不可用降级 unknown。
            info = "unknown"
        _GIT_CACHE = info
        return _GIT_CACHE


def _dist_version(dist_names: tuple[str, ...]) -> str:
    for name in dist_names:
        try:
            return metadata.version(name)
        except Exception:  # noqa: BLE001, S112 - 换下一个候选名。
            continue
    return "unknown"


def format_uptime(now_monotonic: float | None = None) -> str:
    """进程运行时长：「X 小时 Y 分」/「Y 分钟」。"""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    seconds = max(0, int(now - _PROCESS_START_MONOTONIC))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分钟"


def _connection_mode(adapter: str) -> str:
    """通信方式：onebot 按 onebot_ws_urls 配置判正向 WS，否则 webhook；其他适配器直述。"""
    normalized = (adapter or "").strip().lower()
    if "onebot" in normalized:
        try:
            import nonebot

            urls = getattr(
                nonebot.get_driver().config, "onebot_ws_urls", None
            ) or []
            return "正向 WS" if urls else "webhook"
        except Exception:  # noqa: BLE001 - 非生产环境降级 unknown。
            return "unknown"
    if "telegram" in normalized:
        return "Bot API 轮询"
    if "mail" in normalized:
        return "SMTP"
    if "console" in normalized:
        return "本地"
    return "unknown"


def _protocol_label(adapter: str) -> str:
    normalized = (adapter or "").strip().lower()
    if normalized in _ADAPTER_PROTOCOLS:
        return _ADAPTER_PROTOCOLS[normalized]
    for key, label in _ADAPTER_PROTOCOLS.items():
        if key in normalized:
            return label
    return normalized or "unknown"


def _session_label(message: IncomingMessage) -> str:
    if message.session_type is SessionType.GROUP:
        return f"群聊 {message.group_id or '未知群'}"
    if message.session_type is SessionType.CHANNEL:
        return f"频道 {message.group_id or '未知频道'}"
    return "私聊"


def build_error_report(
    message: IncomingMessage,
    capability_id: str,
    exc: Exception,
    *,
    stack_frames: int = 8,
    config_getter: Callable[[str], object] | None = None,
) -> dict[str, Any]:
    """汇总诊断卡 payload（全字段脱敏；任何子块失败降级空块，不抛异常）。"""
    getter = config_getter or _default_config_getter
    exc_type = type(exc).__name__ or "Exception"
    exc_message = redact_local_secrets(str(exc)[:300])
    stack_lines = _stack_excerpt(exc, stack_frames)
    return {
        "card_title": "运行异常",
        "exc_type": exc_type,
        "exc_message": exc_message,
        "human_text": _persona_text(message.session_id, exc_type),
        "trigger_echo": _trigger_echo(message),
        "stack_lines": stack_lines,
        "method_pairs": [
            {"label": "能力", "value": capability_id},
            {"label": "函数", "value": _innermost_frame_name(stack_lines)},
            {"label": "路由", "value": _route_kind_label(capability_id)},
        ],
        "config_pairs": _config_snapshot(capability_id, getter),
        "version_pairs": [
            {"label": "NoneBot", "value": _dist_version(("nonebot2", "nonebot"))},
            {
                "label": "OneBot 适配器",
                "value": _dist_version(
                    ("nonebot-adapter-onebot", "nonebot_adapter_onebot")
                ),
            },
            {
                "label": "插件包",
                "value": _dist_version(
                    ("bot-unified-runtime", "bot_unified_runtime")
                ),
            },
            {"label": "构建", "value": _git_build_info()},
            {"label": "运行时长", "value": format_uptime()},
        ],
        "env_pairs": [
            {"label": "平台", "value": message.platform or "unknown"},
            {"label": "协议", "value": _protocol_label(message.adapter)},
            {"label": "通信", "value": _connection_mode(message.adapter)},
            {"label": "会话", "value": _session_label(message)},
        ],
        "id_pairs": [
            {
                "label": "触发时间",
                "value": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            {"label": "message_id", "value": message.message_id or "—"},
            {"label": "session_id", "value": message.session_id or "—"},
            {"label": "request_id", "value": message.request_id or "—"},
            {
                "label": "告警关联",
                "value": message.debug_id or "—",
            },
        ],
        "help_text": _HELP_TEXT,
        "bot_name": "守岸人",
        "bot_avatar_url": "",
    }


def build_text_fallback(report: dict[str, Any]) -> str:
    """纯文本兜底（渲染失败/冷却降级共用文本口径）：栈摘录 + IDs。"""
    lines = [
        "[运行异常] {exc_type}: {exc_message}".format(
            exc_type=report.get("exc_type") or "Exception",
            exc_message=report.get("exc_message") or "",
        )
    ]
    stack_lines = [str(line) for line in (report.get("stack_lines") or [])]
    if stack_lines:
        lines.append("栈摘录：")
        lines.extend(stack_lines)
    for section, title in (
        ("method_pairs", "触发方法"),
        ("version_pairs", "版本与构建"),
        ("env_pairs", "平台与协议"),
        ("id_pairs", "IDs 与时间"),
    ):
        rows = report.get(section) or []
        if rows:
            lines.append(
                f"{title}：" + "；".join(
                    f"{row.get('label', '')}={row.get('value', '')}"
                    for row in rows
                    if isinstance(row, dict)
                )
            )
    lines.append(str(report.get("help_text") or _HELP_TEXT))
    return "\n".join(line for line in lines if line)


# ==================== 渲染（失败回空串 → 纯文本兜底） ====================
_BACKEND: Any = None
_BACKEND_READY = False
_BACKEND_LOCK = threading.Lock()


def _get_render_backend() -> Any:
    """懒初始化并缓存渲染后端（与能力层共用 build_render_backend 语义）。

    后端名缺省 playwright（与 config.bot_card_render_backend 缺省一致）；
    非生产环境（nonebot 未初始化）同样落到该缺省，不产生 Null 静默降级。
    """
    global _BACKEND, _BACKEND_READY
    with _BACKEND_LOCK:
        if _BACKEND_READY:
            return _BACKEND
        try:
            name = "playwright"
            try:
                import nonebot

                name = (
                    str(
                        getattr(
                            nonebot.get_driver().config,
                            "bot_card_render_backend",
                            "playwright",
                        )
                    )
                    or "playwright"
                )
            except Exception:  # noqa: BLE001 - 非生产环境用默认名。
                name = "playwright"
            from plugins.bot_unified_runtime.output.render_backends import (
                build_render_backend,
            )

            _BACKEND = build_render_backend(name)
        except Exception:  # noqa: BLE001 - 后端构建失败→纯文本兜底。
            _BACKEND = None
        _BACKEND_READY = True
        return _BACKEND


def render_error_card_png(
    report: dict[str, Any],
    *,
    backend: Any = None,
    card_dir: str | None = None,
) -> str:
    """诊断卡出图：成功返回本地 PNG 路径，失败返回空串（调用方降级纯文本）。

    ``card_dir`` 缺省走 driver config ``bot_card_render_dir``（默认 data/cards，
    经 runtime_paths 重映射）；测试注入 tmp 目录，避免源码树 data/ 残留。
    """
    try:
        from plugins.bot_unified_runtime.output.card_render.bridge import (
            render_error_card_html,
        )
        from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

        html = render_error_card_html(report)
        renderer = backend if backend is not None else _get_render_backend()
        if renderer is None:
            return ""
        png = renderer.render_card(
            {
                "html": html,
                "viewport": {"width": 1160, "height": 1800},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        resolved_dir = card_dir
        if not resolved_dir:
            try:
                import nonebot

                resolved_dir = str(
                    getattr(
                        nonebot.get_driver().config,
                        "bot_card_render_dir",
                        "data/cards",
                    )
                    or "data/cards"
                )
            except Exception:  # noqa: BLE001 - 非生产环境用默认目录。
                resolved_dir = "data/cards"
        target = Path(resolved_dir)
        target.mkdir(parents=True, exist_ok=True)
        digest = _stable_report_digest(report)
        path = target / f"error_{digest}.png"
        path.write_bytes(png)
        try:
            prune_prefixed(target, "error", keep=120)
        except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
            pass
        return str(path)
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本契约。
        return ""


def _stable_report_digest(report: dict[str, Any]) -> str:
    import hashlib

    material = "|".join(
        str(report.get(key) or "")
        for key in ("exc_type", "exc_message", "trigger_echo")
    )
    return hashlib.sha1(material.encode("utf-8", "ignore")).hexdigest()[:12]


# ==================== 专用单线程渲染通道（P0 修复，2026-09-14） ====================
# 错误卡渲染禁止在事件循环线程直接调 Playwright 同步 API（Sync-inside-asyncio
# 守卫必触发 → 图片恒败 + 每次 ~0.5s loop 阻塞）。专用单线程与 chat-pool 同模式：
# 工作线程上无运行 loop，thread-local 常驻 browser 语义正常；单线程天然串行化
# 卡片渲染；不复用 chat-pool（避免错误风暴时挤占能力执行位）。
_RENDER_POOL: ThreadPoolExecutor | None = None
_RENDER_POOL_LOCK = threading.Lock()
_PENDING_CARD_FUTURES: set[Future[None]] = set()
_PENDING_CARD_LOCK = threading.Lock()


def _get_render_pool() -> ThreadPoolExecutor:
    global _RENDER_POOL
    with _RENDER_POOL_LOCK:
        if _RENDER_POOL is None:
            _RENDER_POOL = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="error-card-render",
            )
            atexit.register(_shutdown_render_pool)
        return _RENDER_POOL


def _shutdown_render_pool() -> None:
    """模块级关闭钩子（与 pipeline._shutdown_chat_pool 同模式）：不等待不取消，
    已在跑的渲染随进程退出丢弃——文本回执已先行，丢卡可接受（A-rec 取舍）。"""
    global _RENDER_POOL
    with _RENDER_POOL_LOCK:
        pool, _RENDER_POOL = _RENDER_POOL, None
    if pool is not None:
        pool.shutdown(wait=False)


def flush_pending_card_renders(timeout: float = 10.0) -> None:
    """等待在途诊断卡渲染全部完成（测试与受控退出的排空钩子；生产热路径不调用）。"""
    with _PENDING_CARD_LOCK:
        pending = list(_PENDING_CARD_FUTURES)
    deadline = time.monotonic() + max(0.0, timeout)
    for future in pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            future.result(timeout=remaining)
        except Exception:  # noqa: S110, BLE001 - 后台任务异常已在任务体内消化，排空钩子无需再报。
            pass


# ==================== 发送编排（pipeline 层入口） ====================
def cooldown_line(exc_type: str) -> str:
    """冷却期降级纯文本（守岸人口吻，一句）。"""
    return _COOLDOWN_LINE.format(exc=exc_type)


_GATE_BYPASS_TAG = "gate:bypass_by_design"


def _build_error_send_request(
    message: IncomingMessage,
    request_id: str,
    *,
    content_type: str,
    content_ref: dict[str, Any],
    text_fallback: str,
    dedupe_key: str,
    audit_tags: list[str],
) -> SendRequest:
    """诊断旁路消息统一构造（文本回执/图片卡/降级文本共用）。"""
    return SendRequest(
        request_id=request_id,
        session_id=message.session_id,
        target_scope=message.session_type,
        target_id=message.group_id or message.sender_id,
        origin_message_id=message.message_id,
        capability_id="bot.error_report",
        content=RenderedOutput(
            request_id=request_id,
            content_type=content_type,
            content_ref=content_ref,
            text_fallback=text_fallback,
            risk_level=RiskLevel.MEDIUM,
            privacy_level=(
                PrivacyLevel.GROUP
                if message.session_type is SessionType.GROUP
                else PrivacyLevel.PERSONAL
            ),
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"error_report:{message.session_id}",
        expires_at=None,
        privacy_level=(
            PrivacyLevel.GROUP
            if message.session_type is SessionType.GROUP
            else PrivacyLevel.PERSONAL
        ),
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter=message.adapter,
        bot_id=message.bot_id,
        audit_tags=audit_tags,
    )


def _submit_error_request(pipeline: Any, send_request: SendRequest) -> None:
    pipeline.send_queue.submit(send_request)


def maybe_submit_error_card(
    pipeline: Any,
    message: IncomingMessage,
    capability_id: str,
    exc: Exception,
    *,
    settings: ErrorCardSettings | None = None,
    gate: ErrorCardGate | None = None,
    backend: Any = None,
    card_dir: str | None = None,
    render_pool: ThreadPoolExecutor | None = None,
) -> None:
    """能力异常统一入口（两段式，A-rec）：开关关→零动作；全程 fail-open。

    第一段（本线程内联，毫秒级）：冷却闸通过 → 即时提交文本回执（渲染零
    参与，事件循环线程不碰 Playwright）；冷却期内 → 一句守岸人纯文本（现状）。
    第二段（专用渲染线程）：渲染诊断卡 → 成功提交图片卡 / 失败补发全量
    诊断文本，由 send_queue worker 补发。

    本函数自身不抛异常（调用方 pipeline 还有第二层兜底）。
    """
    try:
        resolved = settings or _resolve_settings()
        if not resolved.enabled:
            return
        session_gate = gate or _module_gate(resolved.cooldown_seconds)
        report = build_error_report(
            message,
            capability_id,
            exc,
            stack_frames=resolved.stack_frames,
        )
        exc_type = str(report.get("exc_type") or "Exception")
        base_dedupe = (
            f"error_report:{capability_id}:{message.session_id}:"
            f"{message.message_id or message.request_id}"
        )
        base_tags = [
            "error_report:v1",
            f"source:{capability_id}",
            f"exc:{exc_type}",
            _GATE_BYPASS_TAG,
        ]
        emitted = session_gate.allow(message.session_id)
        if not emitted:
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    message.request_id,
                    content_type="text",
                    content_ref={"text": cooldown_line(exc_type)},
                    text_fallback=cooldown_line(exc_type),
                    dedupe_key=base_dedupe,
                    audit_tags=[*base_tags, "text_only"],
                ),
            )
            return
        # 第一段：即时文本回执（request_id 沿用原 id → matcher 内联首投）。
        ack_text = (
            f"{report.get('human_text') or ''!s} {_ACK_FOLLOWUP_HINT}".strip()
        )
        _submit_error_request(
            pipeline,
            _build_error_send_request(
                message,
                message.request_id,
                content_type="text",
                content_ref={"text": ack_text},
                text_fallback=ack_text,
                dedupe_key=f"{base_dedupe}:ack",
                audit_tags=[*base_tags, "ack"],
            ),
        )
        # 第二段：诊断卡渲染转专用渲染线程（loop 线程禁入）。
        _schedule_card_render(
            pipeline,
            message,
            report,
            base_dedupe=base_dedupe,
            base_tags=base_tags,
            backend=backend,
            card_dir=card_dir,
            pool=render_pool,
        )
    except Exception:
        logger.warning("error report card submission failed", exc_info=True)


def _schedule_card_render(
    pipeline: Any,
    message: IncomingMessage,
    report: dict[str, Any],
    *,
    base_dedupe: str,
    base_tags: list[str],
    backend: Any,
    card_dir: str | None,
    pool: ThreadPoolExecutor | None,
) -> None:
    """把渲染+补发排入专用单线程通道；排程失败只 log（文本回执已先行）。"""
    try:
        executor = pool or _get_render_pool()
        future = executor.submit(
            _render_and_submit_card,
            pipeline,
            message,
            report,
            base_dedupe=base_dedupe,
            base_tags=base_tags,
            backend=backend,
            card_dir=card_dir,
        )
    except Exception:
        logger.warning("error card render scheduling failed", exc_info=True)
        return
    with _PENDING_CARD_LOCK:
        _PENDING_CARD_FUTURES.add(future)
    future.add_done_callback(
        lambda _done: _PENDING_CARD_FUTURES.discard(future)
    )


def _render_and_submit_card(
    pipeline: Any,
    message: IncomingMessage,
    report: dict[str, Any],
    *,
    base_dedupe: str,
    base_tags: list[str],
    backend: Any,
    card_dir: str | None,
) -> None:
    """渲染线程任务：成功→图片卡补发；失败→全量诊断文本补发；异常只 log。"""
    try:
        png_path = render_error_card_png(
            report, backend=backend, card_dir=card_dir
        )
        card_request_id = f"{message.request_id}-card"
        if png_path:
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    card_request_id,
                    content_type="mixed",
                    content_ref={
                        "parts": [
                            {"type": "image", "file": png_path},
                            {
                                "type": "text",
                                "text": str(report.get("human_text") or ""),
                            },
                        ]
                    },
                    text_fallback=build_text_fallback(report),
                    dedupe_key=f"{base_dedupe}:card",
                    audit_tags=[*base_tags, "card"],
                ),
            )
        else:
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    card_request_id,
                    content_type="text",
                    content_ref={"text": build_text_fallback(report)},
                    text_fallback=build_text_fallback(report),
                    dedupe_key=f"{base_dedupe}:card",
                    audit_tags=[*base_tags, "text_only"],
                ),
            )
    except Exception:
        # fail-open：文本回执已先行，卡静默放弃；告警链留全栈（既有
        # internal_error 告警未动，这里只是补充痕）。
        logger.warning("error card background render failed", exc_info=True)
