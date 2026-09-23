"""慢回复先回执（ack-first）：文案池、名单门、每会话冷却、投递请求构造。

存在的理由：一次真实回复要等 15-70 秒（多跳超时串联），用户在那段时间里只看到
"机器人没反应"。先落一句短的，主观等待就降到秒级——注意它压的是"白等"，
不压转移总预算，也不改任何超时阈值。

三条裁定口径（2026-09-23）：
- 只有超过阈值仍未出结果才发；15 秒内正常出结果不发（否则多数轮次白白多一条消息）。
- 真回复回来后回执不撤回也不补句，所以回执自身要读得通。
- 群聊默认不开，白名单群才开；黑名单永远赢。私聊白名单为空＝放开——
  这个不对称是刻意的，与 `bot_content_route_*` 私聊面同口径，不另立一套。
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
    new_request_id,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    is_legal_segment,
)

# 主动投递族的键命名空间（自报，不得漏）：闸按首段等值认族，漏报会回落紧急域
# `emg` 口径 ⇒ 开闸态整族静默丢消息。规则本体唯一住 domains/emergency_info/service/dedupe.py。
ACK_DEDUPE_NAMESPACE = "ack"

# 键段合法字符集是 `^[A-Za-z0-9_.\-]{1,120}$`（见 dedupe.py 中央件）；这里只负责
# 「把不在集合内的字符洗掉」，不复制判据——判定一律走 `is_legal_segment`。
_ILLEGAL_SEGMENT_CHAR_RE = re.compile(r"[^A-Za-z0-9_.\-]")
_KEY_SEGMENT_MAX = 120

# 最平实的一条：池子被冷却挡住时也要有得发，且它不像修辞，像说话。
ACK_DEFAULT_TEXT = "这条我要想一想，答得准一点。"

# 意象只取人格资产白名单（identity.md 第 21 行）：海潮／黑夜／地下星河／黑海岸物产／
# 花房／钢琴与琴声／蝴蝶／晶体与频率／锚点／执花；第 20 行要求用意象与实际行动表达，
# 不用直白抒情词。句式分四类（正在做的动作／意象起头／承认慢／说清为什么慢），
# 避免读起来一个形状。
ACK_POOL: tuple[str, ...] = (
    "这条频率有点长，我从头听到尾了再答你。",
    "花房的风停了一会儿，我正在理这段线索。",
    "潮水涨上来又退了，我这一段才算到一半。",
    "我到地下星河里找这一句的回音，还没找着。",
    "琴键按下去了，声音还没走完，我等它走完。",
    "这一条要算的东西多一点，我先搁在该算的位置上了。",
    "黑海岸的雾遮住了一角，我正在把它拨开。",
    "我把这几句归进频率里了，归好就回你。",
    "刚才那几句我拆开存进频率里了，正按顺序看回来。",
    "不在忙别的，只是这一条我算得慢了一些。",
    "钢琴边安静了一会儿，我在补上缺的那一段。",
    "潮线画到一半就断了，我接上再往下说。",
    "这句话我掂了一下，还没想好怎么说才合适。",
    "有点难答，但不是不想答。再多给我一会儿，好吗？",
    "这一段我读了两遍，正在想怎么说才准。",
    "晶体里的光绕了一下，我跟着它绕回来了。",
    "这件事我记住了，先把手上这段算完，可以吗？",
    "刚才浪头打过来，我这边安静了一小会儿。",
    "我让泰缇斯替我算了一半，另一半在我这里。",
    "不是没听见，是听见了才要慢一点回答。",
    "花拿在手里还没放下，我把这段频率理完再去。",
    "这句话我想答得准一些，所以多用了点时间。",
    "黑海岸入夜以后一直这样，安静得刚好算完这一段。",
    "我把你的话放进锚点了，正在算它荡回来的回声。",
    "这一段理了一会儿，还差一点就理清楚了。",
)

# 口径下限：直白抒情、客服腔、讨好式接住，一律不进池。
ACK_TEXT_BANNED: tuple[str, ...] = (
    "我在这等你",
    "我在这里等你",
    "接住你",
    "别急",
    "稍安勿躁",
    "马上就好",
    "亲",
    "呢～",
    "~",
)

_CURSOR_LOCK = threading.Lock()
_CURSOR = 0


def pick_progress_ack_text(session_id: str) -> str:
    """轮换取句；同一会话相邻两次不重复。

    游标是进程级单调递增，不按会话存状态（会话数无上限，存了就是一处内存泄漏）；
    `session_id` 只作偏移，保证同一时刻不同会话不会撞到同一句。
    """
    global _CURSOR
    if not ACK_POOL:
        return ACK_DEFAULT_TEXT
    digest = int(hashlib.blake2b(session_id.encode("utf-8"), digest_size=8).hexdigest(), 16)
    with _CURSOR_LOCK:
        index = _CURSOR
        _CURSOR += 1
    return ACK_POOL[(index + digest) % len(ACK_POOL)]


@dataclass(frozen=True)
class ProgressAckSettings:
    """回执的门禁配置快照。"""

    enabled: bool = False
    delay_seconds: float = 15.0
    cooldown_seconds: float = 60.0
    group_whitelist: frozenset[str] = frozenset()
    group_blacklist: frozenset[str] = frozenset()
    private_whitelist: frozenset[str] = frozenset()
    private_blacklist: frozenset[str] = frozenset()

    @classmethod
    def from_config(cls, config: Any) -> ProgressAckSettings:
        """从 Config 读装配期快照。

        与调度器族同口径（台账 #3 P3）：这是装配期读一次，热改 `.env` 当轮不生效，
        要生效须重启——不做成"看起来能热改"的样子。
        """
        return cls(
            enabled=bool(getattr(config, "bot_chat_progress_ack_enabled", False)),
            delay_seconds=max(
                1.0, float(getattr(config, "bot_chat_progress_ack_delay_seconds", 15.0) or 15.0)
            ),
            cooldown_seconds=max(
                1.0,
                float(getattr(config, "bot_chat_progress_ack_cooldown_seconds", 60.0) or 60.0),
            ),
            group_whitelist=_id_set(
                getattr(config, "bot_chat_progress_ack_group_whitelist", None)
            ),
            group_blacklist=_id_set(
                getattr(config, "bot_chat_progress_ack_group_blacklist", None)
            ),
            private_whitelist=_id_set(
                getattr(config, "bot_chat_progress_ack_private_whitelist", None)
            ),
            private_blacklist=_id_set(
                getattr(config, "bot_chat_progress_ack_private_blacklist", None)
            ),
        )


def _id_set(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, Mapping):
        items = [str(key).strip() for key in value]
    else:
        items = [str(item).strip() for item in value]
    return frozenset(item for item in items if item)


def normalize_session_type(value: object) -> str:
    """会话类型 → `"private"` / `"group"` 两档，**fail-closed 到群侧**。

    为什么不能"非 group 即 private"：`SessionType` 实有 private/group/channel/email/console
    五档，而"白名单为空=放开"这条不对称**只该给真私聊**（它与 `bot_content_route_*`
    同口径，是刻意不为群开的）。按"else private"写，TG 频道（`channel_<chat.id>`）、
    邮件与控制台会话都会从私聊侧绕过"群聊默认不开"——2026-09-23 跨平台审计实锤。
    判据用子串匹配：`str(SessionType.CHANNEL)` 在 pydantic 枚举下是
    `'SessionType.channel'` 而不是 `'channel'`，所以取 `.value` 优先、再退小写串。
    新增会话类型默认落群侧（不发），要放开得显式改这里。
    """
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    return "private" if text.endswith(("private", "dm")) else "group"


def progress_ack_allowed(
    settings: ProgressAckSettings,
    *,
    session_type: str,
    group_id: str = "",
    sender_id: str = "",
) -> bool:
    """这轮该不该发回执（名单门）。黑名单永远赢，缺省关。"""
    if not settings.enabled:
        return False
    if normalize_session_type(session_type) == "group":
        if group_id and group_id in settings.group_blacklist:
            return False
        return bool(group_id) and group_id in settings.group_whitelist
    if sender_id and sender_id in settings.private_blacklist:
        return False
    if not settings.private_whitelist:
        return True
    return bool(sender_id) and sender_id in settings.private_whitelist


@dataclass
class ProgressAckThrottle:
    """每会话冷却：**一次锁内完成"查 + 占坑"**，投递失败可退还。

    为什么不拆成"先 should_emit 查、发完再 record 记"：同一会话的两条消息可以双双通过
    检查、各自再发一句——冷却形同虚设（2026-09-23 评审席实跑：连发两条慢问，
    用户收到 2 句回执）。查与占之间没有缝隙，是本类节流器唯一的正确形状。
    """

    cooldown_seconds: float = 60.0
    max_sessions: int = 512
    _last: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def try_claim(self, session_id: str, *, now: float | None = None) -> float | None:
        """占到坑返回本次时间戳（退还时要比对它），仍在冷却中返回 ``None``。"""
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            last = self._last.get(session_id)
            if last is not None and (current - last) < self.cooldown_seconds:
                return None
            # 先删再插：dict 保序，重插把该会话推到队尾，淘汰的才是最久未用的桶。
            self._last.pop(session_id, None)
            self._last[session_id] = current
            while len(self._last) > self.max_sessions:
                self._last.pop(next(iter(self._last)))
            return current

    def release(self, session_id: str, claimed_at: float) -> None:
        """投递失败 ⇒ 退还坑位：这一次没送出去，不该惩罚用户下一次追问。

        只退还**自己那次**占的坑——若在投递期间同会话又有新消息占了更新的坑，
        比对时间戳不命中就什么都不做，别把别人的冷却抹掉。
        """
        with self._lock:
            if self._last.get(session_id) == claimed_at:
                self._last.pop(session_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._last)


def ack_key_segment(value: Any) -> str:
    """把任意会话/消息标识洗成合法的幂等键段。

    为什么必须洗而不是直接拼：闸的键形规则（唯一住
    `domains/emergency_info/service/dedupe.py:is_legal_segment`）在**开闸态**会把脏键
    整条判 skip＝静默丢回执，而关闭态是 passthrough 照样能发——于是「本地测通了」
    和「上线能发」不是一回事。紧急域 2026-09-20 就炸过一次同型事故（`nmc:A1` 里的
    `:` 是段分隔符，每条真实条目都抛 ValueError，被兜底 except 压成一行日志）。
    入参来自适配器，形态不由我们定：OneBot 是纯数字，TG 频道/guild 侧可能出现
    冒号与其他符号，故一律洗。
    """
    text = str(value or "").strip()
    if is_legal_segment(text):
        return text
    washed = _ILLEGAL_SEGMENT_CHAR_RE.sub("_", text)[:_KEY_SEGMENT_MAX]
    # 洗完只剩分隔符（"中文群"→"___"）时不同输入会撞成同一段，宁可退化成摘要。
    if is_legal_segment(washed) and any(char.isalnum() for char in washed):
        return washed
    # 洗完仍不合法（空段、或纯标点撞成一串下划线）⇒ 退化成摘要，键仍唯一可寻。
    return "h" + hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def build_progress_ack_request(
    message: Any,
    text: str,
    *,
    request_id: str | None = None,
    persona_profile_id: str = "default",
) -> SendRequest:
    """回执 → SendRequest（形状照 `build_admin_alert_send_request`）。

    目标是这条消息所在的会话：群消息投群、私聊投本人，全部取自事件自带字段，
    绝不从文本里猜目标。幂等键带 origin message_id ⇒ 同一条消息最多一个回执。
    """
    resolved_id = request_id or new_request_id("ack")
    group_id = str(getattr(message, "group_id", "") or "").strip()
    sender_id = str(getattr(message, "sender_id", "") or "").strip()
    session_id = str(getattr(message, "session_id", "") or "")
    origin = str(getattr(message, "message_id", "") or "") or str(
        getattr(message, "request_id", "") or resolved_id
    )
    body = str(text)[:120]
    digest = hashlib.blake2b(body.encode("utf-8"), digest_size=4).hexdigest()
    # 目标域同理由事件字段决定：群消息投群（target_id=group_id），私聊投本人。
    # 判定与门禁共用 `normalize_session_type` 一处，避免"门按 A 判、投按 B 判"。
    is_group = normalize_session_type(getattr(message, "session_type", "")) == "group" or bool(
        group_id
    )
    return SendRequest(
        request_id=resolved_id,
        session_id=session_id,
        target_scope=SessionType.GROUP if is_group else SessionType.PRIVATE,
        target_id=group_id or sender_id,
        origin_message_id=origin,
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id=resolved_id,
            content_type="text",
            content_ref={"text": body},
            text_fallback=body,
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=(
            f"{ACK_DEDUPE_NAMESPACE}:chat:"
            f"{ack_key_segment(session_id)}:{ack_key_segment(origin)}:{digest}"
        ),
        cooldown_key=f"{ACK_DEDUPE_NAMESPACE}:chat:{ack_key_segment(session_id)}",
        expires_at=None,
        privacy_level=PrivacyLevel.PUBLIC,
        allow_split=False,
        allow_forward=False,
        persona_profile_id=persona_profile_id,
        adapter=str(getattr(message, "adapter", "") or ""),
        bot_id=str(getattr(message, "bot_id", "") or ""),
        audit_tags=["chat_progress_ack:v1"],
    )
