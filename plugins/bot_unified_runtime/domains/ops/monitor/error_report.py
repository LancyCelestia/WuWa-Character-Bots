"""统一错误报告卡（运行异常诊断卡，2026-09-13）。

能力执行异常（RuntimePipeline._internal_error 捕获点）时，向触发者回一张
统一诊断卡：人话区（守岸人口吻）/ 触发回显（≤80 字符脱敏）/ 栈摘录（末 N 帧
脱敏）/ 触发方法（capability_id+函数名+RouteKind）/ 脱敏配置快照（键名白名单：
与能力同前缀的 config 字段，密钥类一律 ***）/ 版本与构建 / 平台与协议 /
IDs 与时间（2026-09-25 起卡面与纯文本两面统一作「标识与时间」）/ 求助指引。控制台完整栈仍走既有 runtime/alerts 告警（本模块不改
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
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts import (
    IncomingMessage,
    OperationalIssue,
    PrivacyLevel,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

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

# 冷却期降级纯文本池（守岸人口吻；P2-4 同规则扩容 2026-09-15：1→12）。
# 语义红线不变：每句都指回「刚才那张卡」（冷却期内不重复发卡，细节在卡上），
# 都带 {exc}（异常类型名，自家错误非防御焦点，保留）。
_COOLDOWN_LINES: tuple[str, ...] = (
    "又一条指令出了岔子（{exc}）。细节都在刚才那张卡上……先看那张，我盯着重试。",
    "（{exc}）又出现了。诊断我早已写在刚才那张卡里……不必重复，先看它。",
    "同一个地方，又磕了一下（{exc}）。那张卡是完整的记录……稍等，我会把它理顺。",
    "（{exc}）还在。刚才那张卡，就是此刻的全部答案……先按它看看，我继续盯着。",
    "这一条，停在了（{exc}）。不必担心……卡上的细节，我一遍遍核对过。",
    "（{exc}）仍未退去。诊断卡已经在你那里了……我等的，是它彻底平静。",
    "又是它（{exc}）。有些错误需要一点时间才能退潮……卡在上方，稍安。",
    "（{exc}）像反复的潮。刚才那张卡记录了它的样子……按图索骥，很快。",
    "这条又停在了（{exc}）。细节我不再重复……都在刚才那张卡里。",
    "（{exc}）的影子还在。我看得到它……你也能，在那张卡上。",
    "又一次（{exc}）。先看那张卡……我负责把这片海面抚平。",
    "（{exc}）仍未平息。卡已经发过……等潮水退去，一切会重新可用。",
)

# E-11（2026-09-14）：求助指引如实口径——卡上的图是自动生成的诊断卡（非控制台
# 截图；playwright 不可用时甚至无图退纯文本），完整栈不在卡上，管理员查
# runtime 事件日志。同时点名今日已入库字段族（版本/系统/配置快照/IDs），
# 守岸人口吻。仅用于卡片页脚；纯文本形态用 _FALLBACK_HELP_TEXT（无图场景
# 「这张图」会悬空，两处分开表述）。
#: 头像内联上限（诊断卡本身要经 base64 进 HTML，超过就不给内联、回落圆点）。
_AVATAR_INLINE_MAX_BYTES = 256 * 1024

#: 尾注不能再声称"版本、系统、配置快照和 IDs 都在卡上"——卡是按数据显隐的，
#: 空节整节消失，声称了却没内容是无效引导（2026-09-25 菲比/霞月真卡评审）。
#: 完整栈与全量配置快照的**真落点**是 runtime 事件日志，就写那里。
_HELP_TEXT = (
    "这张卡是我自动生成的，不是控制台截图。卡上的内容都已脱敏，"
    "直接转给创造者就能定位问题。完整调用栈和全量配置在 runtime 事件日志里。"
)
_FALLBACK_HELP_TEXT = (
    "这条是文字版诊断，图这次没能出。内容同样脱敏，"
    "转给创造者就行。完整调用栈和全量配置在 runtime 事件日志里。"
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
#: 单条配置值上卡的长度上限，超出即显式截断并标出未显示字数（见 `_append_row`）。
_CONFIG_VALUE_MAX_CHARS = 96
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

# 适配器 → 协议展示名（E-04：标注协议实现名，OneBot 的生产实现 = SnowLuma；
# mail/telegram/console 同口径补实现名）。历史键 "napcat" 保留（旧事件与旧
# 适配器名仍会落库），只是展示名指向现役实现。
# E-05：本表同时是协议判定的唯一事实源——只做键的精确匹配（含生产实际写入
# 的 "onebot.v11" 点分变体），不再做子串模糊匹配（"onebot" in "nonebot" 的
# 巧合曾把兜底 adapter 名 "nonebot" 误判成 OneBot V11）；查不到回退 unknown。
_ADAPTER_PROTOCOLS: dict[str, str] = {
    "onebot": "OneBot V11（SnowLuma）",
    "onebot.v11": "OneBot V11（SnowLuma）",
    "onebot_v11": "OneBot V11（SnowLuma）",
    "napcat": "OneBot V11（SnowLuma）",
    "onebot_v12": "OneBot V12",
    "onebot.v12": "OneBot V12",
    "telegram": "Telegram Bot API",
    "mail": "IMAP/SMTP",
    "console": "本地控制台",
    # 探针/装配期告警没有协议端可指（根 `__init__.py` 的 tts 探针口传的就是它），
    # 不补这一格卡面就直出 unknown。
    "runtime": "进程内（无协议端）",
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
                from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
                    ROUTE_RULES,
                )

                for rule in ROUTE_RULES:
                    mapping.setdefault(rule.capability_id, rule.kind.name)
            except Exception:  # noqa: BLE001 - 路由反查失败降级 unknown。
                mapping = {}
            _ROUTE_KIND_CACHE = mapping
    kind = _ROUTE_KIND_CACHE.get(capability_id)
    return f"RouteKind.{kind}" if kind else "unknown"


def _innermost_frame_name(
    stack_lines: list[str], *, empty_label: str = "unknown"
) -> str:
    """取栈摘录最内帧函数名（格式 ``  file:line in name: src``）。"""
    if not stack_lines:
        return empty_label
    last = stack_lines[-1]
    marker = " in "
    if marker in last:
        tail = last.rsplit(marker, 1)[1]
        return tail.split(":", 1)[0].strip() or empty_label
    return empty_label


def _default_config_getter(name: str) -> object:
    """生产配置读取：nonebot driver config（bot_* 键挂在 driver config 上）。"""
    try:
        import nonebot

        return getattr(nonebot.get_driver().config, name, None)
    except Exception:  # noqa: BLE001 - 非生产环境快照为空。
        return None


def _persona_signature(getter: Callable[[str], object]) -> tuple[str, str]:
    """卡面署名 ``(中文名, 英文名)`` 跟**生效人格**走（2026-09-28 用户裁定）。

    中文名走 ``persona_profile.current_bot_nickname``——那是 /bot status、卡片页脚、
    人格自称共用的唯一读法（先查人格册，再回落兼容显示名），**绝不读
    ``get_login_info``**（其自身身份缓存改后不刷新，台账 #60★）。英文名由人格册的
    ``persona_id``（拉丁 slug）经 ``theme_tokens.brand_name_en_for`` 派生。
    取不到就交空串给渲染侧统一回落品牌形态（``BRAND_THEME.display_name`` /
    ``BRAND_NAME_EN``），卡面既不许出现空署名、也不许在这里再抄一份回落规则。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        current_bot_nickname,
    )
    from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
        brand_name_en_for,
    )

    persona_id = str(getter("bot_persona_profile_id") or "").strip()
    name = current_bot_nickname(persona_id) or str(
        getter("bot_persona_display_name") or ""
    ).strip()
    return name, brand_name_en_for(persona_id)


def _card_avatar_uri(getter: Callable[[str], object], bot_id: str = "") -> str:
    """卡面头像：先按**实际发送方**取 `data/avatar/bot_<qq>.png`，取不到再退到
    `render.bot_avatar.bot_avatar_uri` 的单实例口径，最后内联成 data URI。

    为什么要按 bot_id 取（2026-09-25 澜汐点名「缺少 bot 的平台的头像」）：本机是
    多 bot 实例（主号 / 校园号 / 推送号），单实例入口只会给"最近落盘的那张"或
    进程内缓存，卡上就可能发的是推送号、画的是别人的脸，或干脆空白。AVT1 的
    注册表语义本就按 `avatar/bot_<qq>.png` 逐实例隔离，这里跟它同源。

    为什么还要内联：渲染后端用 `set_content` 装页，页面 origin 不是 file:，
    Chromium 拒收 `file://` 子资源 ⇒ 直接给路径就是一个碎图图标（样张实锤）。
    任何失败回空串（模板回落「守」字圆点），绝不抛——缺头像只影响观感。
    """
    try:
        from types import SimpleNamespace

        from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

        data_root = str(getter("bot_runtime_data_dir") or "").strip()
        qq = str(bot_id or "").strip()
        if data_root and qq.isdecimal():
            per_instance = _inline_avatar(Path(data_root) / "avatar" / f"bot_{qq}.png")
            if per_instance:
                return per_instance
        cfg = SimpleNamespace(
            bot_persona_avatar_url=str(getter("bot_persona_avatar_url") or ""),
            bot_runtime_data_dir=data_root,
        )
        return _inline_avatar(bot_avatar_uri(cfg)) or ""
    except Exception:  # noqa: BLE001 - 观感件 fail-open
        return ""


def _inline_avatar(source: object) -> str:
    """读成 data URI——实现已收编到 ``render.bot_avatar.inline_avatar_uri``。

    本名保留为**再导出**：诊断卡这条链与它的既有用例都吃这个名字，而内联这件事
    的正当性（Chromium 在 ``set_content`` 下拒收 ``file://`` 子资源）与所有卡片
    同源，不该在 ops 侧再养一份实现。help 卡今天漏内联出碎图，就是因为两处各写各的。
    """
    from plugins.bot_unified_runtime.domains.render.bot_avatar import inline_avatar_uri

    return inline_avatar_uri(source)



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
            # 长值显式截断并标出原长：`bot_tts_ref_audios` 这类键存的是整段参考
            # 语料（真卡实测 600+ 字），不钳住会把一张卡撑成一屏正文——
            # 而"截了"必须让人看出来，静默截断等于谎报配置值。
            if len(value) > _CONFIG_VALUE_MAX_CHARS:
                omitted = len(value) - _CONFIG_VALUE_MAX_CHARS
                value = f"{value[:_CONFIG_VALUE_MAX_CHARS]}…（另有 {omitted} 字未显示）"
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
            # v21r2 迁移后深度：monitor→ops→domains→bot_unified_runtime→plugins→仓库根。
            repo_root = Path(__file__).resolve().parents[5]
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

        # v21r2 迁移后深度：monitor→ops→domains→bot_unified_runtime→plugins→仓库根。
        repo_root = Path(__file__).resolve().parents[5]
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


def _adapter_dist_pairs() -> list[tuple[str, str]]:
    """适配器全景按「一行一个」展开（2026-09-25 澜汐点名）。

    与 `_adapter_dists_label()` 同一份枚举、同一个进程级缓存口径，不重扫
    `metadata.distributions()`（本机实测一次全扫 ~0.9s）。名字去掉
    `nonebot-adapter-` 前缀只留协议短名，版本进值轨，左对齐可读。
    """
    label = _adapter_dists_label()
    if label == "unknown":
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in label.split("、"):
        name, _, version = chunk.strip().rpartition(" ")
        if not name:
            continue
        pairs.append((name.replace("nonebot-adapter-", "适配器 · "), version or "unknown"))
    return sorted(pairs)


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
    "runtime": "进程内（不经网络）",
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


def _session_label_for(session_type: object, group_id: str = "") -> str:
    """会话形态的中文标注（单一真身：异常卡与告警卡共用这一个判据）。

    按 ``.value`` 归一而不是 ``is`` 比较：告警侧的 session_type 有从契约枚举
    来的、也有从队列行/请求上读到的裸串，用 ``is`` 会把裸串读成「私聊」。
    """
    value = getattr(session_type, "value", session_type)
    text = str(value or "").strip().lower()
    # 拿不到群号时只写形态，不再补「未知群」——评审：那是占位，不是信息。
    if text == SessionType.GROUP.value:
        return f"群聊 {group_id}".strip()
    if text == SessionType.CHANNEL.value:
        return f"频道 {group_id}".strip()
    if text == SessionType.EMAIL.value:
        return "邮件"
    if text == SessionType.CONSOLE.value:
        return "控制台"
    if text == SessionType.PRIVATE.value:
        return "私聊"
    return f"未登记会话（{text or 'unknown'}）"


def _session_label(message: IncomingMessage) -> str:
    return _session_label_for(message.session_type, message.group_id or "")


def format_clock_label(moment: datetime | None = None) -> str:
    """全卡/全告警**唯一**的时刻格式：``2026-09-25 11:32:13 UTC+08:00``。

    一张卡上顶行用「空格+时区」、底行用 ISO 8601 的 `T`/`+08:00`，同一件事两种
    写法会被读成两个时刻（2026-09-25 真卡评审第③条）。缺省取当前时刻，本地时区。
    """
    instant = (moment or datetime.now(timezone.utc)).astimezone()
    offset = instant.utcoffset()
    if offset is None:  # 裸 naive 钟：不假装知道时区，直说本地。
        return instant.strftime("%Y-%m-%d %H:%M:%S 本地时区")
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 3600)
    return f"{instant.strftime('%Y-%m-%d %H:%M:%S')} UTC{sign}{hours:02d}:{minutes // 60:02d}"


#: 「拿不到」的几种写法。真卡评审（2026-09-25 菲比/霞月）：函数/路由/归属/协议/
#: 通信整整五行挂着 unknown，占掉视觉重心却零信息量——**没拿到的就整行不出**，
#: 节内全空则整节消失（模板本来就按数据显隐）。
_PLACEHOLDER_VALUES = frozenset(
    {"", "unknown", "未记名", "未归属", "未配置", "—", "-", "none", "null"}
)


def _kv(label: str, value: object) -> dict[str, str]:
    """一条 label/value；空值与占位值一律不成行（返回空 dict，由 `_rows` 剔掉）。"""
    text = str(value or "").strip()
    if not text or text.lower() in _PLACEHOLDER_VALUES:
        return {}
    return {"label": label, "value": text}


def _rows(pairs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """剔掉空 dict 与值为占位的行——渲染端与文本兜底共用同一份判据。"""
    return [
        row
        for row in pairs
        if row and str(row.get("value", "")).strip()
        and str(row.get("value", "")).strip().lower() not in _PLACEHOLDER_VALUES
    ]


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
    return format_clock_label(moment)


# ------------------------------------------------------------- 自我审查与建议
#
# 澜汐要的 14 项里，「bot 自我审查大概原因」与「debug 建议」今天**根本不存在**
# （全仓 `self_review` / `debug_advice` 零命中）。这两格刻意不写成结论：
# 规则只根据异常类型与栈里出现过的字样给**倾向**，句子必须带「推测」二字。
# 把没核过的归因写成断言，正是本仓反复记过的失效形态（也是 #51 那条
# 「无检索结果不得断言未发生」的同一课）。
_SELF_REVIEW_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("TimeoutError", "ReadTimeout", "ConnectTimeout", "timeout"),
        "像是对端太慢或这条链路被拖长，不像是我算错了",
        "先看是不是多跳串联把时间用光；网关侧渠道健康与单跳超时是两处独立嫌疑",
    ),
    (
        ("Retcode", "retcode", "FailedToGetBot"),
        "像是协议端此刻不在线或拒了这个动作，不像是消息本身有问题",
        "确认 SnowLuma 在跑、账号已登录；同一动作手发一次看它回什么码",
    ),
    (
        ("KeyError", "AttributeError", "TypeError", "IndexError", "ValueError"),
        "像是我内部代码这次走进了没预料到的形态",
        "看栈顶帧与触发请求的形态，能定位到功能就能修；复现一次比猜有用",
    ),
    (
        ("ValidationError", "schema"),
        "像是上游回来的东西不合我的契约",
        "把这次的原始返回留档，别只凭摘要猜它长什么样",
    ),
    (
        ("HTTPError", "ProviderError", "provider_error", "502", "503"),
        "像是上游服务自己在报错或限流",
        "换一个模型试同一句话；仍失败就去网关看实际渠道与错误原文",
    ),
    (
        ("MemoryError", "RecursionError"),
        "像是我把内存或递归用穿了",
        "这条请求的体量（长度/媒体数量）是首要嫌疑",
    ),
)

_SELF_REVIEW_DEFAULT: tuple[str, str] = (
    "暂无命中的推测规则（不猜）",
    "看上面「阶段/代号」与详情；同一个代号反复出现，就照它立一条归因规则",
)

#: 告警面没有栈摘录节（issue 不带 traceback），默认建议不能指着一节不存在的东西让她看。
_ISSUE_SELF_REVIEW_DEFAULT: tuple[str, str] = (
    "暂无命中的推测规则（不猜）",
    (
        "看上面「阶段/代号」与详情那两行，再按这个代号立一条归因规则；"
        "同一代号反复出现就是结构性问题，不是偶发"
    ),
)

# 运行时告警面（OperationalIssue）的归因规则（2026-09-25 澜汐裁定「任何报错都要
# 给我完整的诊断卡」）。异常名匹配对 issue 面天生失灵——issue 的 exc_type 是
# ``stage/kind`` 这种代号串，命中不了上面那套按异常名写的规则，于是每张告警卡
# 都落「我不猜」。这里按 kind 补一小段，句子一律带「推测」二字（同上面纪律：
# 只给倾向，不冒充确诊）。认不出来的 kind 仍走原路径 → _SELF_REVIEW_DEFAULT。
_ISSUE_SELF_REVIEW_RULES: dict[str, tuple[str, str]] = {
    "timeout": (
        "推测是对端回话太慢、或这一跳被拖长了，不像是我算错了",
        "先看链路上跑了几跳（多跳串联会把时间用光），再看网关侧渠道健康——两处独立嫌疑",
    ),
    "retcode_failure": (
        "推测是协议端此刻拒了这个动作（它回了失败码），不像是消息本身有问题",
        "确认协议端在跑、账号已登录；同一动作手发一次，看它回的是哪个 retcode",
    ),
    "config_missing": (
        "推测是少了一项配置（键没填或填错），这条功能今天没能起来",
        "按告警行点名的键名核对 .env 与运行时设置；填完必须重启才生效（铁律：改代码/配置都要重启）",
    ),
    "network": (
        "推测是出网这一路不通（DNS、代理或对端拒连），不像是代码算错",
        "跨域名同时红＝本机出口链路问题；只有单个域名红＝对端问题。换个时间点再试一次",
    ),
    "bot_unavailable": (
        "推测是此刻没有在线的发送账号，消息留在队列里等账号回来",
        "看协议端连接状态与登录回执；这类通常是断线窗口，不必改代码",
    ),
    "result_unknown": (
        "推测是发出去了但没读到回执，不代表对方没收到",
        "按 request_id 在 runtime 事件日志里对账；反复出现再查传输超时预算",
    ),
    "deadline_exceeded": (
        "推测是整条故障转移链的时限用完了，每一跳都没能在预算内回来",
        "看 detail 里的 chain 跳数与实际渠道；链太长或某一跳挂起都会烧穿预算",
    ),
    "provider_error": (
        "推测是上游服务自己在报错（限流/欠费/下架都在这一类）",
        "换一个模型试同一句话；仍失败就去网关看实际渠道与错误原文",
    ),
}


def _self_review(
    exc_type: str,
    stack_lines: list[str],
    *,
    issue_kind: str = "",
) -> tuple[str, str]:
    """返回 (大概原因, debug 建议)。命中依据是异常名与栈文本里的字样。

    ``issue_kind`` 非空＝运行时告警面：先查按 kind 写的规则表，查不到再落
    原有的异常名规则（同一张表，不另起第二套判定）。
    """
    kind = str(issue_kind or "").strip().lower()
    if kind:
        hit = _ISSUE_SELF_REVIEW_RULES.get(kind)
        if hit is not None:
            return hit
    haystack = f"{exc_type} {' '.join(stack_lines)}"
    for tokens, review, advice in _SELF_REVIEW_RULES:
        if any(token and token in haystack for token in tokens):
            return review, advice
    return _ISSUE_SELF_REVIEW_DEFAULT if kind else _SELF_REVIEW_DEFAULT


# 告警面（issue kind）的「报错原因」归类：异常名表对 ``stage/kind`` 代号串失灵
# （"Retcode" 匹配不上 "retcode_failure"），所以 kind 先查这张表，查不到再退回
# 按异常名的既有归类。认不出仍然明说「未归类」，不硬编一个。
_ISSUE_REASON_LABELS: dict[str, str] = {
    "timeout": "超时：等对端回话等过头",
    "deadline_exceeded": "整条链路时限用完",
    "retcode_failure": "协议端返回失败",
    "config_missing": "缺少配置项",
    "network": "连不上对方服务",
    "bot_unavailable": "没有在线的发送账号",
    "result_unknown": "已投递但回执未确认",
    "provider_error": "上游服务报错",
    "schema": "返回内容不合契约",
    "empty_response": "对方回了空内容",
    "internal_error": "内部抛异常",
    "pipeline_busy": "队列排满，这条挤不进去",
}


def _reason_label(exc_type: str, exc_message: str, *, issue_kind: str = "") -> str:
    """⑨「报错原因」= 异常类型（或告警 kind）的中文归类。认不出就明说未归类。"""
    kind = str(issue_kind or "").strip().lower()
    if kind:
        label = _ISSUE_REASON_LABELS.get(kind)
        if label:
            return label
    table = (
        (("TimeoutError", "ReadTimeout", "ConnectTimeout"), "超时：等对端回话等过头"),
        (("Retcode", "OneBot", "FailedToGetBot"), "协议端返回失败"),
        (("ValidationError",), "返回内容不合契约"),
        (("HTTPError", "ProviderError"), "上游服务报错"),
        (("MemoryError",), "内存耗尽"),
        (("RecursionError",), "递归太深"),
        (("LookupError", "KeyError", "IndexError"), "取到了不该取的空位"),
        (("AttributeError", "TypeError", "ValueError"), "内部类型/取值不匹配"),
    )
    for tokens, label in table:
        if any(token == exc_type or token in exc_type for token in tokens):
            return label
    if exc_message.strip().lower().startswith("all connected bots"):
        return "没有在线的发送账号"
    return f"未归类（{exc_type}）"


#: 严重度的人话档：键由 ``RiskLevel`` 枚举派生（不手抄枚举名，加一档忘填当场红），
#: 卡上不许直出 `medium` 这类英文 token（澜汐 2026-09-25 硬约束：报错提示用人话）。
_SEVERITY_PLAIN: dict[str, str] = {
    level.value: label
    for level, label in (
        (RiskLevel.LOW, "低：不影响你收消息"),
        (RiskLevel.MEDIUM, "中：就这一条没办好"),
        (RiskLevel.HIGH, "高：有一段时间会不正常"),
        (RiskLevel.CRITICAL, "严重：整条链路不正常"),
    )
}


#: 告警面「哪个模块的哪个功能」的兜底尺：告警常常没有能力 id（`stage` 才有），
#: 这时按阶段落到子系统，不再整卡 unknown。键集必须与 `alerts._STAGE_PLAIN` 同域
#: （一张管人话主句、一张管归属，两把尺不许各自漂——由
#: `test_issue_stage_ownership_keys_track_alert_stage_plain` 执法）。
_ISSUE_STAGE_OWNERSHIP: dict[str, str] = {
    "llm": "chat_reply 域 / llm_engine（模型一跳）",
    "router": "chat_reply 域 / llm_engine（选模）",
    "context": "chat_reply 域 / character（上下文拼装）",
    "context_diagnostic": "chat_reply 域 / character（上下文自检）",
    "onebot": "transport 域 / sender（OneBot 出站）",
    "transport": "transport 域 / sender",
    "sender": "transport 域 / sender",
    "queue": "transport 域 / send_queue",
    "receipt": "transport 域 / 回执确认",
    "tts": "media 域 / tts",
    "mail_bridge": "mail 域 / bridge",
    "capability_invoke": "core 域 / 能力调度",
    "policy": "chat_reply 域 / policy（发送策略）",
    "review": "render 域 / reviewer（内容审核）",
    "audience_gate": "chat_reply 域 / policy（受众门）",
    "mute_gate": "chat_reply 域 / policy（静音门）",
    # 以下 13 档是 2026-09-25 按 `alerts._STAGE_PLAIN` 反向差集补齐的——缺哪档，
    # 那张卡的「归属」就回落成未归属（真卡样张实例：creation 那张）。
    "action_resolver": "core 域 / 动作解析",
    "campus": "assistant 域 / campus（校园转发）",
    "creation": "creation 域 / 生成预留面",
    "generation": "creation 域 / 生成执行",
    "history": "chat_reply 域 / character（对话历史）",
    "idempotency_gate": "transport 域 / 幂等门",
    "nonebot_handlers": "core 域 / 装配（nonebot 处理器）",
    "notice_gate": "chat_reply 域 / policy（通知门）",
    "quiet_hours": "chat_reply 域 / policy（安静时间）",
    "runtime": "core 域 / 运行时（进程内）",
    "scheduler": "schedule 域 / 调度器",
    "startup": "core 域 / 启动装配",
    "tools": "core 域 / 工具与 MCP",
}


def _module_ownership(capability_id: str, *, stage: str = "") -> str:
    """报错定位到「哪个域的功能」：优先能力 id 的域段，退到路由 kind，再退到阶段。"""
    text = str(capability_id or "").strip()
    if text.startswith("bot.") or "." in text:
        parts = [p for p in text.replace("bot.", "").split(".") if p]
        if len(parts) >= 2:
            return f"{parts[0]} 域 / {parts[1]}"
        if parts:
            return f"{parts[0]} 域"
    kind = _route_kind_label(text) if text else ""
    if kind and kind != "unknown":
        return kind
    return _ISSUE_STAGE_OWNERSHIP.get(str(stage or "").strip(), "未归属")


def _as_id_list(raw: object) -> list[str]:
    """把 id 名单读成列表：list / JSON 串 / 逗号分号串三种形态都吃。

    这枚键在生产里经由 dotenv→pydantic 才是 list，但卡片可能在任何形态的
    config_getter 下组装（测试、控制面投影、垫片）；读法容错，取不到就空。
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set, frozenset)):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith(("[", "{")):
        try:
            import json

            data = json.loads(text)
            if isinstance(data, dict):
                data = list(data.keys())
            return _as_id_list(data)
        except Exception:  # 非法 JSON 退回分隔串切分（静默吞会读成"名单是空的"）。
            logger.debug("admin id-list json parse failed; falling back to separators", exc_info=True)
    return [p.strip() for p in re.split(r"[,;、\s]+", text) if p.strip()]


def _admin_contact_pairs(
    getter: Callable[[str], object], *, group_facing: bool = False
) -> list[dict[str, str]]:
    """超管联系方式：只列在册超管账号，绝不外扩到普通管理员/群成员。

    真身是 `bot_super_admin_user_ids`（roles.py:58 同源）；`bot_admin_profiles`
    给名字，有名字就一并显示。取不到时明确写「未配置」而不是留空行——
    这张卡的用途就是「出事了找谁」，空值会被读成"没有超管"。

    ``group_facing=True``＝这张卡要发进群/频道（旁观者看得见）：异常卡的投递
    目标就是事发会话本体，把真名+QQ 印上去等于向全群广播管理端联系方式，违反
    既有隐私契约 A69-C1（创造者真名不得入卡）。这一格退成「几位、请私聊任一
    管理员」，要素⑬仍在，只是不公开号码。告警卡走管理员私聊，永远 False。
    """
    try:
        raw = getter("bot_super_admin_user_ids")
    except Exception:  # noqa: BLE001 - 联系面取不到不能拖垮整张卡
        raw = None
    ids = _as_id_list(raw)
    try:
        profiles = getter("bot_admin_profiles") or {}
    except Exception:  # noqa: BLE001
        profiles = {}
    if isinstance(profiles, str):
        # 这枚键的实际形态随装载路径而变（.env 里是一串 / JSON 字符串 / dict 都有人用）。
        # 之前直接 .items() 会在这张卡里抛 AttributeError——诊断卡自己崩掉是最难发现的一类故障。
        text = profiles.strip()
        try:
            import json

            profiles = json.loads(text) if text.startswith(("{", "[")) else {}
        except Exception:  # noqa: BLE001
            profiles = {}
    if not isinstance(profiles, dict):
        profiles = {}
    named = {
        str(k).strip(): str(v).strip()
        for k, v in profiles.items()
        if str(k).strip() and str(v).strip()
    }
    if not ids:
        return [{"label": "超管联系方式", "value": "未配置（BOT_SUPER_ADMIN_USER_IDS 为空）"}]
    # 评审（2026-09-25 菲比）：两行「超管」各占一格不直观——并成一条，用顿号分隔，
    # 每条都带昵称/备注，联系谁一眼可辨。
    people = [
        f"{named.get(user_id, '未署名')}（QQ {user_id}）" if named.get(user_id) else f"QQ {user_id}"
        for user_id in ids[:6]
    ]
    if group_facing:
        return [
            {
                "label": f"超管 {len(people)} 位",
                "value": "名单与号码不在群内公开，请私聊任一管理员并把本卡发过去",
            }
        ]
    return [{"label": f"超管 {len(people)} 位", "value": "、".join(people)}]


def _protocol_client_version_label(getter: Callable[[str], object]) -> str:
    """协议端（SnowLuma）版本：读它自己 package.json 的 version 字段。

    为什么不是运行期问它：OneBot V11 有 `get_version`，但本仓从未调用过，
    而卡片在渲染线程里同步组装，不能为了一个版本号去主循环里发一次异步 RPC。
    读实物文件是确定的、可复核的；读不到就写「未取到」，绝不拿适配器包的
    版本号顶替（那是 nonebot-adapter-onebot，不是协议端）。
    """
    configured = ""
    try:
        configured = str(getter("bot_protocol_client_dir") or "").strip()
    except Exception:  # noqa: BLE001 - 读不到配置就走缺省探测
        configured = ""
    candidates = [configured] if configured else []
    candidates += ["C:/Software/SnowLuma", "C:/Software/snowluma"]
    for root in candidates:
        if not root:
            continue
        try:
            import json
            import pathlib

            manifest = pathlib.Path(root) / "package.json"
            if not manifest.is_file():
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            version = str(data.get("version") or "").strip()
            if version:
                name = str(data.get("name") or "protocol client").strip()
                return f"{name} {version}"
        except Exception:  # 任何读取失败都退回诚实值（换下一个候选目录前留一痕）。
            logger.debug("protocol client package.json unreadable; trying next candidate", exc_info=True)
            continue
    return "未取到"


def _version_pairs(getter: Callable[[str], object]) -> list[dict[str, str]]:
    """版本与构建段（⑤⑥⑦要素）：异常卡与告警卡共用同一份，不各写一遍。

    ⑥「适配器版本」由「适配器」那一行给（全景列表本就含 nonebot-adapter-onebot
    的版本号）——2026-09-25 真卡评审：单列一行 OneBot 适配器，又跟下面整排
    适配器列表撞车，属纯冗余。
    """
    return _rows(
        [
            _kv("NoneBot", _dist_version(("nonebot2", "nonebot"))),
            # E-03：补运行时事实三件——解释器版本/操作系统/适配器实现全景。
            _kv("Python", _python_version()),
            _kv("系统", _os_label()),
            # 适配器一行一个（2026-09-25 点名：顿号串一长条读不动）。
            *[_kv(name, version) for name, version in _adapter_dist_pairs()],
            # ⑤协议端版本：这是 SnowLuma 自己的版本，与上一行「适配器」
            # （nonebot-adapter-onebot，Python 侧封装）不是一回事，必须分行。
            _kv("协议端", _protocol_client_version_label(getter)),
            _kv("插件包", _plugin_version()),
            _kv("构建", _git_build_info()),
            _kv("运行时长", format_uptime()),
        ]
    )


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
    review, advice = _self_review(exc_type, stack_lines)
    # E-07：触发时刻优先消息时间戳；E-06：sender/bot/群号有则显示、**无则整行不出**
    # （评审：拿不到的数据挂一排 unknown/— 占版面，零信息量）。
    id_pairs: list[dict[str, str]] = _rows(
        [
            _kv("触发时刻", _trigger_time_label(message)),
            _kv("message_id", message.message_id),
            # ②哪个会话：形态与会话键并成一条，别在别处再写一遍形态。
            _kv(
                "会话",
                " ".join(
                    part
                    for part in (_session_label(message), str(message.session_id or ""))
                    if part
                ),
            ),
            _kv("sender_id", message.sender_id),
            _kv("bot_id", message.bot_id),
            _kv("group_id", message.group_id),
            _kv("request_id", message.request_id),
            _kv("告警关联", message.debug_id),
        ]
    )
    signature = _persona_signature(getter)
    return {
        "card_variant": "error",
        "card_title": "运行异常",
        "exc_type": exc_type,
        "exc_message": exc_message,
        "human_text": _persona_text(message.session_id, exc_type),
        "trigger_echo": _trigger_echo(message),
        "stack_lines": stack_lines,
        "method_pairs": _rows(
            [
                _kv("能力", capability_id),
                _kv("函数", _innermost_frame_name(stack_lines)),
                _kv("路由", _route_kind_label(capability_id)),
                # ⑩「哪个模块的哪个功能」：能力 id 只给到 bot.xxx，域归属另给一行。
                _kv("归属", _module_ownership(capability_id)),
                # ⑨报错原因按异常类型给一句中文归类；「未归类」是把异常名换个
                # 说法再念一遍，没有增量（评审：与代号撞车），整行不出。
                _kv(
                    "原因",
                    ""
                    if _reason_label(exc_type, exc_message).startswith("未归类")
                    else _reason_label(exc_type, exc_message),
                ),
            ]
        ),
        # ⑪自我审查 + ⑫debug 建议：句子必须带「推测」，不许冒充确诊。
        "self_review_pairs": _rows(
            [
                _kv("大概原因", review),
                _kv("建议", advice),
            ]
        ),
        # ⑬联系方式按收件人分级：群/频道态不公开真名与号码（A69-C1 同域）。
        "contact_pairs": _admin_contact_pairs(
            getter,
            group_facing=str(getattr(message.session_type, "value", message.session_type) or "")
            in {SessionType.GROUP.value, SessionType.CHANNEL.value},
        ),
        "config_pairs": _config_snapshot(capability_id, getter),
        "version_pairs": _version_pairs(getter) if include_env else [],
        # 「会话」只在 IDs 那一节留一处（评审：卡上同一件事写了三遍）。
        "env_pairs": _rows(
            [
                _kv("平台", message.platform),
                _kv("协议", _protocol_label(message.adapter)),
                _kv("通信", _connection_mode(message.adapter)),
            ]
        ),
        "id_pairs": id_pairs,
        "help_text": _HELP_TEXT,
        "fallback_help_text": _FALLBACK_HELP_TEXT,
        "bot_name": signature[0],
        "bot_name_en": signature[1],
        "bot_avatar_url": _card_avatar_uri(getter),
    }


def _issue_time_label() -> str:
    """告警卡时刻：告警在事发当轮即组装，取当前时刻（本地时区、秒精度 ISO）。

    异常卡的 `_trigger_time_label` 优先读 message.timestamp（可能离线补投），
    告警面没有消息对象，也没有比"现在"更诚实的值——写更早的时间才是编。
    """
    return format_clock_label()


def _issue_code(raw: object, *, limit: int = 40) -> str:
    """stage/kind 代号上卡面前先按字符白名单洗一遍。

    与 alerts._alert_token 同一动机：代号是代码给的标识符，但队列行/上游原文
    可能被拼进 kind（`blocked_<transport>` 一族就是运行期拼出来的），带出去之前
    宁可让它显示成被裁过的样子。这里不 import alerts 的那枚私名尺（monitor 内的
    两个方向都保持"alerts → error_report"单向依赖，不留反向 import 边）。
    """
    text = re.sub(r"[^A-Za-z0-9_.:\-]", "", str(raw or "").strip())
    text = re.sub(r"[A-Za-z]{1,6}-[A-Za-z0-9]{20,}", "‹已隐藏›", text)
    if not text:
        return "未记名"
    return text if len(text) <= limit else text[:limit] + "…"


def build_issue_report(
    issue: OperationalIssue,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    headline: str = "",
    capability_id: str = "",
    session_id: str = "",
    group_id: str = "",
    request_id: str = "",
    config_getter: Callable[[str], object] | None = None,
    stack_lines: list[str] | None = None,
    include_env: bool = True,
) -> dict[str, Any]:
    """运行时告警（``OperationalIssue``）→ 诊断卡 payload（2026-09-25）。

    存在的理由：告警今天只发一行文本，澜汐裁定「任何报错出来都需要给我完整的
    诊断卡」。卡载荷的**唯一**组装口在本件（本函数与 `build_error_report` 产出
    同一套键、共用同一批取值 helper），调用方只许传事实、不许手搓 dict。

    与异常卡的三点差异（都是"告警面没有的东西"，不是另立口径）：
    - ``exc_type`` = ``stage/kind`` 代号串（异常面是异常类名，这里没有异常对象）；
    - ``human_text`` 由调用方（alerts 的人话主句）递进来，本件不重算第二套；
    - ``trigger_echo`` 恒空——告警没有"触发它的那句用户话"可回显，栈摘录也给不
      出（issue 不带 traceback），两者允许为空，渲染端与文本兜底都已容忍空值。
    """
    getter = config_getter or _default_config_getter
    stage = _issue_code(issue.stage)
    kind = _issue_code(issue.kind)
    exc_type = f"{stage}/{kind}"
    exc_message = redact_local_secrets(str(issue.safe_summary or "")[:400]).strip()
    frames = [redact_local_secrets(str(line)) for line in (stack_lines or []) if str(line)]
    review, advice = _self_review(exc_type, frames, issue_kind=str(issue.kind))
    human_text = redact_local_secrets(str(headline or "").strip()) or _persona_text(
        "", exc_type
    )
    id_pairs: list[dict[str, str]] = _rows(
        [
            _kv("告警时刻", _issue_time_label()),
            _kv("debug_id", issue.debug_id),
            # 会话只留这一处（评审：卡上「私聊」出现三次）。形态 + 群号 + 会话键
            # 并成一条，拿不到的部分不占行。
            _kv(
                "会话",
                " ".join(
                    part
                    for part in (
                        _session_label_for(session_type, group_id),
                        str(session_id or "").strip(),
                    )
                    if part and part != "未知群"
                ),
            ),
            _kv("request_id", request_id),
            _kv("发出账号", source_bot),
            _kv("重试", "可重试" if issue.retryable else "不可重试"),
            # attempts==1 是常态，写出来零信息量（评审：与「不可重试」同属复读）。
            _kv("尝试次数", "" if int(issue.attempts or 1) <= 1 else str(issue.attempts)),
            _kv(
                "严重度",
                _SEVERITY_PLAIN.get(
                    str(getattr(issue.severity, "value", issue.severity) or "")
                    .strip()
                    .lower(),
                    "未定级",
                ),
            ),
            _kv(
                "耗时(ms)",
                "" if issue.elapsed_ms is None else f"{float(issue.elapsed_ms):.1f}",
            ),
        ]
    )
    signature = _persona_signature(getter)
    return {
        "card_variant": "alert",
        "card_title": "运行时告警",
        "exc_type": exc_type,
        "exc_message": exc_message,
        "human_text": human_text,
        "trigger_echo": "",
        "stack_lines": frames,
        "method_pairs": _rows(
            [
                # 阶段/代号/能力并成一条（评审：三行本质只说了同一个"未配置"）。
                # 能力有名才附在括号里——无名时它只会重复「未记名」。
                _kv(
                    "阶段/代号",
                    f"{stage} / {kind}"
                    + (f"（能力 {capability_id}）" if capability_id.strip() else ""),
                ),
                # ⑧报错内容的落点：详情文字在模板里由「报错详情」节带出（无栈时
                # 不再挂空标题），这里**不再重复一行**——两头都补会出现两遍。
                _kv("函数", _innermost_frame_name(frames)),
                _kv("路由", _route_kind_label(capability_id) if capability_id else ""),
                _kv("归属", _module_ownership(capability_id, stage=stage)),
                # 「未归类（xxx）」只是把代号换个说法再念一遍，没有增量；真归类上
                # 了才值得占一行。
                _kv(
                    "原因",
                    ""
                    if _reason_label(exc_type, exc_message, issue_kind=kind).startswith(
                        "未归类"
                    )
                    else _reason_label(exc_type, exc_message, issue_kind=kind),
                ),
            ]
        ),
        "self_review_pairs": _rows(
            [
                _kv("大概原因", review),
                _kv("建议", advice),
            ]
        ),
        "contact_pairs": _admin_contact_pairs(getter),
        "config_pairs": _config_snapshot(capability_id or "bot.admin_alert", getter),
        "version_pairs": _version_pairs(getter) if include_env else [],
        "env_pairs": _rows(
            [
                _kv("协议", _protocol_label(source_adapter)),
                _kv("通信", _connection_mode(source_adapter)),
            ]
        ),
        "id_pairs": id_pairs,
        "help_text": _HELP_TEXT,
        "fallback_help_text": _FALLBACK_HELP_TEXT,
        "bot_name": signature[0],
        "bot_name_en": signature[1],
        "bot_avatar_url": _card_avatar_uri(getter, source_bot)
    }


def build_text_fallback(report: dict[str, Any]) -> str:
    """纯文本兜底（渲染失败/冷却降级共用文本口径）：栈摘录 + IDs。

    E-11：结尾口径说明用 `_FALLBACK_HELP_TEXT`（文字版如实说明「本次没带图」），
    不复用卡片 `_HELP_TEXT` 的「这张图」口径——纯文本场景无图可指。
    """
    lines = [
        "[{title}] {exc_type}: {exc_message}".format(
            title=report.get("card_title") or "运行异常",
            exc_type=report.get("exc_type") or "Exception",
            exc_message=report.get("exc_message") or "",
        )
    ]
    stack_lines = [str(line) for line in (report.get("stack_lines") or [])]
    if stack_lines:
        lines.append("栈摘录：")
        lines.extend(stack_lines)
    for section, title in (
        ("method_pairs", "定位与原因"),
        ("version_pairs", "版本与构建"),
        ("config_pairs", "配置快照"),
        ("env_pairs", "平台与协议"),
        ("id_pairs", "标识与时间"),
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
    # 自查/建议与联系方式是整句中文，压成一行"；"串会重新变成读不懂的东西——
    # 这两段逐行给，卡渲不出来时文本里也还得看得懂。
    for section, title in (
        ("self_review_pairs", "我自查的大概原因（推测）与建议"),
        ("contact_pairs", "可以找谁"),
    ):
        for row in (report.get(section) or []):
            if isinstance(row, dict) and (row.get("label") or row.get("value")):
                lines.append(
                    f"{title}｜{row.get('label', '')}：{row.get('value', '')}"
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
            from plugins.bot_unified_runtime.domains.render.render_backends import (
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
        from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
            render_error_card_html,
        )

        html = render_error_card_html(report)
        digest = _stable_report_digest(report)
        return render_html_card(
            html,
            stem="error",
            digest=digest,
            backend=backend,
            card_dir=card_dir,
        )
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本契约。
        return ""


def render_html_card(
    html: str,
    *,
    stem: str,
    digest: str,
    backend: Any = None,
    card_dir: str | None = None,
    keep: int = 120,
    viewport: tuple[int, int] = (1160, 1800),
) -> str:
    """把一页卡片 HTML 出成 PNG 文件：成功回路径，任何失败回空串。

    诊断卡与宿主机状态卡共用这一条落盘路（2026-09-25 第 5 项接线时抽出——
    此前这段「后端取图→runtime_path 落盘→按前缀配额清理」只住在诊断卡里，
    再抄一份就是第二真身）。``keep`` 是同前缀保留数，走
    ``cache_policy.prune_prefixed``；清理失败不影响本次出图。
    """
    renderer = backend if backend is not None else _get_render_backend()
    if renderer is None:
        return ""
    png = renderer.render_card(
        {
            "html": html,
            "viewport": {"width": viewport[0], "height": viewport[1]},
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
    from scripts.runtime_paths import runtime_path

    target = runtime_path(resolved_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{stem}_{digest}.png"
    path.write_bytes(png)
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
            prune_prefixed,
        )

        prune_prefixed(target, stem, keep=keep)
    except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
        pass
    return str(path)


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
    """冷却期降级纯文本（守岸人口吻，池内随机一句；语义契约见池注释）。"""
    import random

    return random.choice(_COOLDOWN_LINES).format(exc=exc_type)


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
            reply_text = cooldown_line(exc_type)
            _submit_error_request(
                pipeline,
                _build_error_send_request(
                    message,
                    message.request_id,
                    content_type="text",
                    content_ref={"text": reply_text},
                    text_fallback=reply_text,
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


def _submit_tracked(
    executor: Any,
    task: Callable[..., None],
    *args: Any,
    **kwargs: Any,
) -> None:
    """提交渲染任务并登记在途集合（异常向上抛，由调用方决定降级）。

    抽出来的理由：在途登记（持引用 + done 回调清理）少写一次就是「后台任务被
    GC 掉、卡静默消失」那一类缺陷；两处共用一份，不再各抄一遍配对。
    """
    future = executor.submit(task, *args, **kwargs)
    with _PENDING_CARD_LOCK:
        _PENDING_CARD_FUTURES.add(future)
    future.add_done_callback(lambda _done: _PENDING_CARD_FUTURES.discard(future))


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
        _submit_tracked(
            executor,
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


def _render_and_submit_issue_card(
    report: dict[str, Any],
    *,
    pipeline: Any,
    build_request: Callable[[str, dict[str, Any]], SendRequest | None],
    backend: Any,
    card_dir: str | None,
) -> None:
    """渲染线程任务（告警面）：出图 → 交回调用方造请求 → 入队补发。

    ``build_request(png_path, report)`` 由调用方给（管理员目标只有 alerts 认识），
    本件不回碰它：卡载荷与渲染/入队口径留在这里，请求的目标语义留在那里。
    png_path 为空串＝渲染失败，此时由 build_request 决定给什么（alerts 给全量
    诊断文本请求）；返回 None＝这一态什么都不投（fail-open，不吞文本告警）。
    """
    try:
        png_path = render_error_card_png(report, backend=backend, card_dir=card_dir)
        request = build_request(png_path, report)
        if request is None:
            return
        # 与异常卡同口径：aware UTC + 同一 3s 下限，保证卡排在已发文本之后。
        deliver_after = datetime.now(timezone.utc) + timedelta(
            seconds=_CARD_DELIVER_DELAY_SECONDS
        )
        _submit_error_request(pipeline, request, deliver_after=deliver_after)
    except Exception:
        # 纯文本告警此刻已在路上：卡失败只留痕，绝不回抛（回抛＝把文本一起带走）。
        logger.warning("alert issue card render/submit failed", exc_info=True)


def schedule_issue_card(
    report: dict[str, Any],
    *,
    pipeline: Any,
    build_request: Callable[[str, dict[str, Any]], SendRequest | None],
    render_pool: ThreadPoolExecutor | None = None,
    backend: Any = None,
    card_dir: str | None = None,
) -> bool:
    """把告警诊断卡的「渲染 + 入队」排进专用渲染通道（返回是否成功排程）。

    为什么不就地渲染：Playwright 的同步 API 在事件循环线程里必触发 Sync-inside-
    asyncio 守卫（图片恒败 + 每次约 0.5s 阻塞 loop）——这是异常卡那条链上已经
    付过学费的 P0（见模块 docstring 两段式），告警卡同病同药，共用同一个通道。

    全程 fail-open：排程失败只 log 并回 False，调用方的文本告警不受任何影响。
    """
    try:
        executor = render_pool or _get_render_pool()
        _submit_tracked(
            executor,
            _render_and_submit_issue_card,
            report,
            pipeline=pipeline,
            build_request=build_request,
            backend=backend,
            card_dir=card_dir,
        )
    except Exception:
        logger.warning("alert issue card render scheduling failed", exc_info=True)
        return False
    return True
