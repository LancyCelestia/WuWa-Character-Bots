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
- 渲染成功 → 后台提交图片卡（E-12：request_id 复用原 id——与文本回执同一
  回执寻址路径，``find_request(原 id)`` 可寻；dedupe_key 保留 ":card" 后缀
  防撞既有去重，队列 dedupe 只认 dedupe_key，复用 id 不会被拒收），经
  send_queue worker 补发；渲染失败 → 补发全量诊断文本（诊断
  完整性不因渲染失败丢失）。fail-open：后台任务任何异常只 log，文本回执
  已先行，卡静默放弃。
- 门禁语义（by design）：错误卡只会在已通过 quiet_hours/限流门禁的同一
  对话回合内触发（门禁在 pipeline._prepare 先行），本模块有意不复查门禁
  （复查=同义反复，复查限流还会双扣预算）；防刷屏由会话冷却闸承担。
  审计标签 ``gate:bypass_by_design`` 把该取舍显式化。
"""

from __future__ import annotations

import atexit
import inspect
import logging
import os
import platform
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
from datetime import datetime, timedelta, timezone
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

# E-11（2026-09-14）：求助指引如实口径——卡上的图是自动生成的诊断卡（非控制台
# 截图；playwright 不可用时甚至无图退纯文本），完整栈不在卡上，管理员查
# runtime 事件日志。同时点名今日已入库字段族（版本/系统/配置快照/IDs），
# 守岸人口吻。仅用于卡片页脚；纯文本形态用 _FALLBACK_HELP_TEXT（无图场景
# 「这张图」会悬空，两处分开表述）。
_HELP_TEXT = (
    "这张图是我自动生成的诊断卡（不是控制台截图），版本、系统、配置快照和"
    " IDs 都在卡上且已脱敏，转给创造者就好；完整栈在 runtime 事件日志里，"
    "管理员可以查到。"
)
_FALLBACK_HELP_TEXT = (
    "这条是自动生成的文字版诊断（本次没带图），版本、系统、配置快照和 IDs "
    "都在上面、同样脱敏，转给创造者就好；完整栈在 runtime 事件日志里，"
    "管理员可以查到。"
)

# 文本回执尾注：告知诊断卡随后补发（两段式，2026-09-14 P0 修复）。
_ACK_FOLLOWUP_HINT = "详细诊断卡随后补发。"

# A-plus（2026-09-14）：补发请求的 deliver_after 延迟（秒）。后台补发无内联
# 首投，覆盖队列内联宽限后，卡从提交到 worker 认领 ≈ 3s + 0~30s 扫描抖动
# ≈ 3–33s（原基线 60–92s=内联宽限 60s + 扫描抖动）。3s 下限保证卡排到即时
# 文本回执之后，顺序不倒挂。
_CARD_DELIVER_DELAY_SECONDS = 3.0

# 触发回显上限（用户裁定 ≤80 字符，脱敏后截断）。
_TRIGGER_ECHO_MAX_CHARS = 80

# 栈摘录帧数钳位与单帧源码行截断。
_STACK_FRAMES_MIN = 1
_STACK_FRAMES_MAX = 30
_FRAME_LINE_MAX_CHARS = 160

# 配置快照：键名白名单 = 与能力同前缀（bot_<模块>_）的 Config 字段；
# 命中密钥类命名的一律 ***（值不看内容直接掩码，双保险）。
# 审查 F-02（2026-09-14）：词表补 sendkey/credential/proxy/webhook/auth——
# bot_disconnect_notice_serverchan_sendkey、bot_download_proxy、
# bot_credentials_file 等真实字段此前能进白名单但值打不掉。auth 用字母级
# 环视当"词边界"（不能用 \b：snake_case 里 auth 前面是 _，\b 永不成立）：
# author/authorization 等**字母延展**词干不掩码（作者类字段、Authorization
# 头字段名不误杀，后者的值仍由出站脱敏管线兜底），裸 auth / auth_xxx
# （下划线续接）仍掩码（测试锁死双向）。
_SECRET_KEY_RE = re.compile(
    r"(token|secret|api_key|apikey|password|passwd|cookie|sendkey"
    r"|credential|proxy|webhook|(?<![A-Za-z])auth(?![A-Za-z]))",
    re.IGNORECASE,
)
_CONFIG_SNAPSHOT_MAX_ROWS = 12
# E-10：能力同前缀字段不足时补的全局兜底键（横切运行相关的布尔与阈值，
# 非密钥命名；bot.status 等无同前缀字段的能力配置区不再恒空）。值仍走既有
# 脱敏管线（密钥正则 *** → redact_local_secrets），白名单机制不变。
_CONFIG_GLOBAL_FALLBACK_KEYS: tuple[str, ...] = (
    "bot_error_card_enabled",
    "bot_error_card_cooldown_seconds",
    "bot_quiet_hours_enabled",
    "bot_reminder_enabled",
)
_CONFIG_SNAPSHOT_MIN_PREFIX_ROWS = 3

# 适配器 → 协议展示名（E-04：标注协议实现名，OneBot 的生产实现 = NapCat；
# mail/telegram/console 同口径补实现名）。
# E-05：本表同时是协议判定的唯一事实源——只做键的精确匹配（含生产实际写入
# 的 "onebot.v11" 点分变体），不再做子串模糊匹配（"onebot" in "nonebot" 的
# 巧合曾把兜底 adapter 名 "nonebot" 误判成 OneBot V11）；查不到回退 unknown。
_ADAPTER_PROTOCOLS: dict[str, str] = {
    "onebot": "OneBot V11（NapCat）",
    "onebot.v11": "OneBot V11（NapCat）",
    "onebot_v11": "OneBot V11（NapCat）",
    "napcat": "OneBot V11（NapCat）",
    "onebot_v12": "OneBot V12",
    "onebot.v12": "OneBot V12",
    "telegram": "Telegram Bot API",
    "mail": "IMAP/SMTP",
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

    def _append_row(name: str) -> None:
        if _SECRET_KEY_RE.search(name):
            value = "***"
        else:
            raw = config_getter(name)
            if raw is None:
                return
            value = redact_local_secrets(str(raw))
        rows.append({"label": name, "value": value})

    for name in sorted(candidates):
        _append_row(name)
        if len(rows) >= _CONFIG_SNAPSHOT_MAX_ROWS:
            break
    # E-10：前缀命中（getter 有值的行）不足 _CONFIG_SNAPSHOT_MIN_PREFIX_ROWS
    # 条时，补一组全局运行键兜底；已出现的前缀键不重复补，行数上限照旧钳制。
    if len(rows) < _CONFIG_SNAPSHOT_MIN_PREFIX_ROWS:
        seen = {row["label"] for row in rows}
        for name in _CONFIG_GLOBAL_FALLBACK_KEYS:
            if len(rows) >= _CONFIG_SNAPSHOT_MAX_ROWS:
                break
            if name not in seen:
                _append_row(name)
                seen.add(name)
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


def _plugin_version() -> str:
    """插件包版本：本项目以源码形态运行、从不 pip 安装——``metadata.version``
    对任何发行名都查不到（venv 实证），唯一事实源是仓库 pyproject.toml 的
    ``[project].version``；读不到再退 metadata，最终 unknown（fail-open）。
    """
    version = _dist_version(("bot-character-bots", "bot_character_bots"))
    if version != "unknown":
        return version
    try:
        import tomllib

        repo_root = Path(__file__).resolve().parents[3]
        with (repo_root / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)
        value = str(data.get("project", {}).get("version", "") or "").strip()
        return value or "unknown"
    except Exception:  # noqa: BLE001 - 版本信息缺失不阻塞诊断卡。
        return "unknown"


def _python_version() -> str:
    """E-03：Python 解释器版本（platform 读取失败退 unknown，fail-open）。"""
    try:
        return platform.python_version() or "unknown"
    except Exception:  # noqa: BLE001 - 元数据缺失不阻塞诊断卡。
        return "unknown"


def _os_label() -> str:
    """E-03：操作系统「系统名 版本号」（读不到退 unknown，fail-open）。"""
    try:
        label = f"{platform.system()} {platform.release()}".strip()
        return label or "unknown"
    except Exception:  # noqa: BLE001 - 同上，缺失不阻塞诊断卡。
        return "unknown"


_ADAPTER_DISTS_CACHE: str | None = None


def _adapter_dists_cache_clear() -> None:
    """测试与环境钩子：强制下一次调用重新扫描发行版（生产进程内无需调用）。"""
    global _ADAPTER_DISTS_CACHE
    _ADAPTER_DISTS_CACHE = None


def _adapter_dists_label() -> str:
    """E-03：已安装 nonebot-adapter* 发行版全景「名字 版本」（顿号合并）。

    ``_dist_version`` 只能点名查一个发行版，这里要的是全景（实际装了哪些
    协议实现）；单个损坏发行版跳过，枚举整体失败或一个都没有 → unknown
    （fail-open：清单缺席绝不让诊断卡构建抛错）。键名白名单脱敏机制不涉及
    此段（发行名/版本号无密钥形态）。

    进程级缓存（2026-09-15 ack 阻塞根因修复）：``metadata.distributions()``
    全盘扫描在本机实测 ~0.9s/次（326 个发行版 METADATA 全量 email 解析），
    出现在同步回执路径会把「毫秒级回执」契约打穿；环境盘点进程内不变
    （装/卸适配器本就要求重启），unknown 也一并缓存。
    """
    global _ADAPTER_DISTS_CACHE
    if _ADAPTER_DISTS_CACHE is not None:
        return _ADAPTER_DISTS_CACHE
    entries: list[str] = []
    try:
        for dist in metadata.distributions():
            try:
                name = str(dist.metadata.get("Name") or "").strip()
                version = str(dist.version or "").strip()
            except Exception:  # noqa: BLE001, S112 - 损坏发行版换下一个。
                continue
            if name.lower().startswith("nonebot-adapter"):
                entries.append(f"{name} {version or 'unknown'}")
    except Exception:  # noqa: BLE001 - 枚举本身失败整体降级 unknown。
        _ADAPTER_DISTS_CACHE = "unknown"
        return _ADAPTER_DISTS_CACHE
    _ADAPTER_DISTS_CACHE = "、".join(sorted(entries)) or "unknown"
    return _ADAPTER_DISTS_CACHE


def format_uptime(now_monotonic: float | None = None) -> str:
    """进程运行时长：「X 小时 Y 分」/「Y 分钟」。"""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    seconds = max(0, int(now - _PROCESS_START_MONOTONIC))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分钟"


# E-05：OneBot 族名单直接从协议表派生（label 以 OneBot 开头的键），非 OneBot
# 适配器的通信方式显式映射——两处都不再靠子串匹配。
_ONEBOT_ADAPTER_NAMES: frozenset[str] = frozenset(
    name
    for name, label in _ADAPTER_PROTOCOLS.items()
    if label.startswith("OneBot")
)
_CONNECTION_MODES: dict[str, str] = {
    "telegram": "Bot API 轮询",
    "mail": "SMTP",
    "console": "本地",
}


def _connection_mode(adapter: str) -> str:
    """通信方式：OneBot 族按 onebot_ws_urls 配置判正向 WS，否则 webhook；
    其他适配器显式映射直述（E-05：精确匹配，查不到回退 unknown）。"""
    normalized = (adapter or "").strip().lower()
    if normalized in _ONEBOT_ADAPTER_NAMES:
        try:
            import nonebot

            urls = getattr(
                nonebot.get_driver().config, "onebot_ws_urls", None
            ) or []
            return "正向 WS" if urls else "webhook"
        except Exception:  # noqa: BLE001 - 非生产环境降级 unknown。
            return "unknown"
    return _CONNECTION_MODES.get(normalized, "unknown")


def _protocol_label(adapter: str) -> str:
    """E-05：协议判定只做显式映射的精确查表，查不到回退 unknown——
    不再做子串模糊匹配（消除 "onebot" in "nonebot" 误判）。"""
    normalized = (adapter or "").strip().lower()
    return _ADAPTER_PROTOCOLS.get(normalized, "unknown")


def _session_label(message: IncomingMessage) -> str:
    if message.session_type is SessionType.GROUP:
        return f"群聊 {message.group_id or '未知群'}"
    if message.session_type is SessionType.CHANNEL:
        return f"频道 {message.group_id or '未知频道'}"
    return "私聊"


def _trigger_time_label(message: IncomingMessage) -> str:
    """触发时刻（E-07）：优先 message.timestamp（摄取时刻），缺失/解析失败
    退当前时刻——离线补投、链路延迟时 ``datetime.now()`` 会把触发时间说谎。
    timestamp 契约是 datetime（摄取层 default_factory 当前时刻），这里仍按
    fail-open 兜字符串解析与类型异常；统一本地时区、秒精度 ISO。"""
    moment: datetime | None = None
    raw = getattr(message, "timestamp", None)
    if isinstance(raw, datetime):
        moment = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            moment = datetime.fromisoformat(raw.strip())
        except ValueError:
            moment = None
    if moment is None:
        moment = datetime.now().astimezone()  # 展示口径=本地时刻（astimezone 免 DTZ005）。
    try:
        return moment.astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001 - 时区归一失败退裸 ISO（fail-open）。
        return moment.isoformat(timespec="seconds")


def build_error_report(
    message: IncomingMessage,
    capability_id: str,
    exc: Exception,
    *,
    stack_frames: int = 8,
    config_getter: Callable[[str], object] | None = None,
    include_env: bool = True,
) -> dict[str, Any]:
    """汇总诊断卡 payload（全字段脱敏；任何子块失败降级空块，不抛异常）。

    ``include_env=False`` 为轻量模式（2026-09-15 ack 阻塞根因修复）：跳过
    version_pairs 环境盘点（适配器全景/构建/git subprocess），供同步回执
    路径（文本回执先行）使用——回执只需要 human_text/exc_type/触发回显，
    毫秒级契约不能被秒级环境扫描阻塞；全量报告由渲染线程重建（两段式
    设计的本意）。轻量与全量在这些共用字段上字节级一致。
    """
    getter = config_getter or _default_config_getter
    exc_type = type(exc).__name__ or "Exception"
    exc_message = redact_local_secrets(str(exc)[:300])
    stack_lines = _stack_excerpt(exc, stack_frames)
    # E-07：触发时刻优先消息时间戳；E-06：sender/bot/群号有则显示、无则省略行。
    id_pairs: list[dict[str, str]] = [
        {"label": "触发时刻", "value": _trigger_time_label(message)},
        {"label": "message_id", "value": message.message_id or "—"},
        {"label": "session_id", "value": message.session_id or "—"},
    ]
    for label, value in (
        ("sender_id", message.sender_id),
        ("bot_id", message.bot_id),
        ("group_id", message.group_id),
    ):
        if value:
            id_pairs.append({"label": label, "value": value})
    id_pairs.append({"label": "request_id", "value": message.request_id or "—"})
    id_pairs.append({"label": "告警关联", "value": message.debug_id or "—"})
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
        "version_pairs": (
            [
                {"label": "NoneBot", "value": _dist_version(("nonebot2", "nonebot"))},
                {
                    "label": "OneBot 适配器",
                    "value": _dist_version(
                        ("nonebot-adapter-onebot", "nonebot_adapter_onebot")
                    ),
                },
                # E-03：补运行时事实三件——解释器版本/操作系统/适配器实现全景。
                {"label": "Python", "value": _python_version()},
                {"label": "系统", "value": _os_label()},
                {"label": "适配器", "value": _adapter_dists_label()},
                {"label": "插件包", "value": _plugin_version()},
                {"label": "构建", "value": _git_build_info()},
                {"label": "运行时长", "value": format_uptime()},
            ]
            if include_env
            else []
        ),
        "env_pairs": [
            {"label": "平台", "value": message.platform or "unknown"},
            {"label": "协议", "value": _protocol_label(message.adapter)},
            {"label": "通信", "value": _connection_mode(message.adapter)},
            {"label": "会话", "value": _session_label(message)},
        ],
        "id_pairs": id_pairs,
        "help_text": _HELP_TEXT,
        "fallback_help_text": _FALLBACK_HELP_TEXT,
        "bot_name": "守岸人",
        "bot_avatar_url": "",
    }


def build_text_fallback(report: dict[str, Any]) -> str:
    """纯文本兜底（渲染失败/冷却降级共用文本口径）：栈摘录 + IDs。

    E-11：结尾口径说明用 `_FALLBACK_HELP_TEXT`（文字版如实说明「本次没带图」），
    不复用卡片 `_HELP_TEXT` 的「这张图」口径——纯文本场景无图可指。
    """
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
        ("config_pairs", "配置快照"),
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
    lines.append(str(report.get("fallback_help_text") or _FALLBACK_HELP_TEXT))
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
# 审查 L-12：atexit 注册只许一次（模块级布尔防 shutdown 后重建池导致的重复
# 注册堆积；钩子读全局，一次注册覆盖此后所有池实例）。
_RENDER_POOL_ATEXIT_REGISTERED = False
_PENDING_CARD_FUTURES: set[Future[None]] = set()
_PENDING_CARD_LOCK = threading.Lock()


def _get_render_pool() -> ThreadPoolExecutor:
    global _RENDER_POOL, _RENDER_POOL_ATEXIT_REGISTERED
    with _RENDER_POOL_LOCK:
        if _RENDER_POOL is None:
            _RENDER_POOL = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="error-card-render",
            )
            if not _RENDER_POOL_ATEXIT_REGISTERED:
                atexit.register(_shutdown_render_pool)
                _RENDER_POOL_ATEXIT_REGISTERED = True
        return _RENDER_POOL


def _shutdown_render_pool() -> None:
    """模块级关闭钩子（与 pipeline._shutdown_chat_pool 同模式）。

    审查 L-12：wait=True 且不取消排队任务（cancel_futures=False），已提交的
    诊断卡渲染在进程退出前渲染完再收线程——worker 非守护态本就会被解释器
    隐式 join，显式回收只是把时序摆上台面。文本回执仍永远先行（ack 路径
    不等本钩子），A-rec 取舍不受影响。"""
    global _RENDER_POOL
    with _RENDER_POOL_LOCK:
        pool, _RENDER_POOL = _RENDER_POOL, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=False)


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


def _submit_error_request(
    pipeline: Any,
    send_request: SendRequest,
    *,
    deliver_after: datetime | None = None,
) -> None:
    if deliver_after is None:
        pipeline.send_queue.submit(send_request)
        return
    # deliver_after 只有 SQLiteSendRequestQueue 支持（InMemory 队列是即时
    # 语义，无延迟概念）；与 worker._call_queue_state_method 同款内省：
    # 不支持时按现状立即提交，绝不让延迟参数把卡吞掉（fail-open）。
    submit = pipeline.send_queue.submit
    try:
        parameters = inspect.signature(submit).parameters
        supported = "deliver_after" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        supported = False
    if supported:
        submit(send_request, deliver_after=deliver_after)
    else:
        submit(send_request)


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
        # 轻量报告（毫秒级）：同步路径只回执，不碰秒级环境盘点——全量报告
        # 由渲染线程经 report_builder 重建（两段式契约：回执零阻塞）。
        report = build_error_report(
            message,
            capability_id,
            exc,
            stack_frames=resolved.stack_frames,
            include_env=False,
        )

        def _full_report_builder() -> dict[str, Any]:
            return build_error_report(
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
            report_builder=_full_report_builder,
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
    report_builder: Callable[[], dict[str, Any]] | None = None,
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
            report_builder=report_builder,
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
    report_builder: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """渲染线程任务：成功→图片卡补发；失败→全量诊断文本补发；异常只 log。

    A-plus：补发请求带 ``deliver_after=now+3s``（覆盖队列内联宽限），投递
    等待从 60–92s 压到 ≈3–33s；两分支（卡/降级文本）同延迟同语义。
    2026-09-15 ack 阻塞根因修复：入参 ``report`` 是同步路径的轻量报告；
    环境盘点（version_pairs）在渲染线程经 ``report_builder`` 重建全量，
    秒级扫描不再占用回执线程；builder 缺席或失败回退轻量报告（fail-open，
    卡面少环境段但照常出卡）。
    """
    if report_builder is not None:
        try:
            report = report_builder()
        except Exception:
            logger.warning(
                "error card full report build failed; using light report",
                exc_info=True,
            )
    try:
        png_path = render_error_card_png(
            report, backend=backend, card_dir=card_dir
        )
        # 必须是 aware UTC：队列行以 ISO 字符串做 SQL 比较，worker 以
        # datetime.now(timezone.utc).isoformat() 生成比较基准，混入本地
        # 时区（astimezone()）会让字符串序错乱。
        deliver_after = datetime.now(timezone.utc) + timedelta(
            seconds=_CARD_DELIVER_DELAY_SECONDS
        )
        # 审查 E-12（2026-09-14）：卡请求复用原 request_id，不再派生
        # ``原 id + "-card"``。机制依据（sender/queue.py 实读）：
        # - 队列 dedupe 只认 dedupe_key（InMemory `_dedupe_keys` 集合 /
        #   SQLite `ON CONFLICT(dedupe_key) DO NOTHING`），request_id 不参与
        #   去重 → 复用不会被拒收；
        # - dedupe_key 保留 ":card" 后缀：与文本回执的 ":ack"、冷却降级文本
        #   （无后缀）三态互斥，同一回合三条请求互不吞并；
        # - 复用后卡与文本回执走同一回执寻址路径（find_request(原 id) 可寻，
        #   SQLite 取同 id 最新行），独立派生 id 则任何回执查询都够不到卡。
        # 投递本身：默认配置 worker 关闭时行留在队列（与派生 id 时代一致）；
        # worker 开启（生产 .env 已启用）按 deliver_after=+3s 认领补发，
        # A-plus 顺序保证（卡排在文本回执之后）不变。
        if png_path:
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    message.request_id,
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
                deliver_after=deliver_after,
            )
        else:
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    message.request_id,
                    content_type="text",
                    content_ref={"text": build_text_fallback(report)},
                    text_fallback=build_text_fallback(report),
                    dedupe_key=f"{base_dedupe}:card",
                    audit_tags=[*base_tags, "text_only"],
                ),
                deliver_after=deliver_after,
            )
    except Exception:
        # fail-open：文本回执已先行，卡静默放弃；告警链留全栈（既有
        # internal_error 告警未动，这里只是补充痕）。
        logger.warning("error card background render failed", exc_info=True)
