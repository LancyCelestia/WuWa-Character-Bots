"""表情贴纸回应（bot.reactions）：适配器中立的归一、缓冲、门控与编排。

职责（2026-09-14 批次，用户裁定需求：识别 + 理解 + 主动回应）：

1. 事件归一：QQ(NapCat) 的 ``group_msg_emoji_like`` 等贴纸回应 notice →
   :class:`ReactionEvent`；Telegram 侧留 :func:`normalize_telegram_reaction`
   接口（见下方平台能力实况）。
2. 会话级环形缓冲：每会话最近回应（默认 TTL 10 分钟、每会话上限 8 条），
   供人格上下文注入【表情回应】分区（空则整块不出现）。
3. 主动贴表情门控：开关 → 每消息去重 → 确定性概率 → 会话冷却 → 每小时
   滑窗限额，五层全过才贴（``set_msg_emoji_like``，失败静默）。

平台能力实况（2026-09-14 实查 venv 依赖版本，诚实记录）：

- QQ/NapCat：群聊贴纸回应以 notice 事件 ``group_msg_emoji_like`` 上报
  （私聊等价形态按 OneBot notice 通用结构容错解析，生产实机待验证）；
  主动贴 = NapCat 扩展 API ``set_msg_emoji_like(message_id, emoji_id)``。
- Telegram：nonebot-adapter-telegram **0.1.0b20** 的 model 层有
  ``MessageReactionUpdated`` 与 ``Update.message_reaction``，但
  ``event.py`` 的 ``event_map`` 没有 ``message_reaction`` 键——该 Update
  在事件转换时 KeyError 被丢弃，到不了 NoneBot handler。故 TG 识别侧
  只留本模块的归一接口（适配器升级支持后接一行 on_notice 即可），
  属诚实降级而非假实现。TG 主动贴 = Bot API 7.0+
  ``set_message_reaction``，仅当 bot 在该群为管理员时可用（私聊不可）；
  本仓库提供 wrapper 但**不接线**任何 TG 主动贴触发点。

本模块不导入 NoneBot，可离线单测。
"""
from __future__ import annotations

import hashlib
import time
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------- 常量与映射

# QQ 经典小黄脸 id → 名称（常用子集；映射不出的存原 id 诚实显示）。
QQ_CLASSIC_FACE_NAMES: dict[int, str] = {
    0: "微笑", 1: "撇嘴", 2: "色", 3: "发呆", 4: "得意", 5: "流泪",
    6: "害羞", 7: "闭嘴", 8: "睡", 9: "大哭", 10: "尴尬", 11: "发怒",
    12: "调皮", 13: "呲牙", 14: "惊讶", 15: "难过", 16: "囧", 17: "抓狂",
    18: "吐", 19: "偷笑", 20: "可爱", 21: "白眼", 22: "傲慢", 23: "饥饿",
    24: "困", 25: "惊恐", 26: "流汗", 27: "憨笑", 28: "悠闲", 29: "奋斗",
    30: "咒骂", 31: "疑问", 32: "嘘", 33: "晕", 34: "疯了", 35: "衰",
    36: "骷髅", 37: "敲打", 38: "再见", 39: "擦汗", 40: "抠鼻",
    41: "鼓掌", 42: "害羞", 43: "坏笑",
}

# QQ 新版贴表情系统的 emoji_id 通常是 unicode 码点十进制串（如 128077=👍）。
# 判定边界：<=400 视为经典小黄脸 id；>400 尝试按码点解出符号字符。
_CLASSIC_FACE_ID_MAX = 400


def emoji_display(emoji_id: str) -> str:
    """把平台 emoji_id 转成诚实可读的展示文本；映射不出保留原 id。"""
    text = str(emoji_id or "").strip()
    if not text:
        return ""
    try:
        code = int(text)
    except ValueError:
        return text  # 非数字（TG emoji 原字符/自定义 id 等）按原文展示。
    if 0 <= code <= _CLASSIC_FACE_ID_MAX:
        name = QQ_CLASSIC_FACE_NAMES.get(code)
        return f"「{name}」" if name else f"QQ表情#{text}"
    try:
        char = chr(code)
    except (ValueError, OverflowError):
        return f"表情#{text}"
    # 只认符号类字符，避免把大整数误渲成汉字/假名。
    if unicodedata.category(char).startswith("S"):
        return char
    return f"表情#{text}"


# 主动贴表情意图 → QQ 经典表情 id（守岸人语气适配：温和、不吵闹、无攻击性）。
REACTION_INTENT_EMOJIS: dict[str, int] = {
    "赞同": 41,  # 鼓掌
    "开心": 13,  # 呲牙
    "有趣": 19,  # 偷笑
    "害羞": 6,   # 害羞
    "惊讶": 14,  # 惊讶
    "安慰": 20,  # 可爱
    "感动": 5,   # 流泪
    "加油": 29,  # 奋斗
    "憨笑": 27,  # 憨笑
}
# 兜底池：意图映射不中时按确定性哈希从中挑一个。
_REACTION_FALLBACK_INTENTS = ("开心", "赞同", "有趣", "憨笑")

# 情绪信号关键词（触发 B：用户消息命中即视为态度时刻；简繁都收）。
_SIGNAL_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("感动", ("谢谢", "多谢", "感谢", "辛苦", "帮大忙", "救星", "感謝", "多謝", "辛苦了")),
    ("赞同", ("厉害", "太棒", "好棒", "真棒", "厉害了", "優秀", "厲害", "太棒了", "說得對", "说得对")),
    ("害羞", ("可爱", "喜欢你", "想你", "最棒", "可愛", "喜歡你")),
    ("惊讶", ("居然", "不会吧", "真的假的", "震驚", "震惊")),
    ("加油", ("加油", "冲鸭", "沖鴨")),
    ("安慰", ("难过", "难受", "傷心", "好難過")),
)


def infer_signal_intent(text: str) -> str | None:
    """用户消息命中情绪信号 → 返回意图；未命中返回 None（不贴）。"""
    stripped = str(text or "").strip()
    if not stripped:
        return None
    for intent, words in _SIGNAL_INTENT_KEYWORDS:
        for word in words:
            if word and word in stripped:
                return intent
    return None


def select_reaction_emoji(intent: str, seed: str) -> int:
    """意图 → QQ 表情 id；映射不中按确定性哈希从兜底池挑（同 seed 同结果）。"""
    emoji_id = REACTION_INTENT_EMOJIS.get(str(intent or "").strip())
    if emoji_id is not None:
        return emoji_id
    digest = hashlib.sha256(f"reaction:{seed}".encode()).hexdigest()[:8]
    index = int(digest, 16) % len(_REACTION_FALLBACK_INTENTS)
    return REACTION_INTENT_EMOJIS[_REACTION_FALLBACK_INTENTS[index]]


# --------------------------------------------------------------- 事件归一

# NapCat 已知形态 + 私聊等价形态 + 容错别名。
_EMOJI_LIKE_NOTICE_TYPES = frozenset(
    {"group_msg_emoji_like", "private_msg_emoji_like", "msg_emoji_like"}
)


@dataclass(frozen=True)
class ReactionEvent:
    """归一后的贴纸回应事件（适配器中立，各适配器字段同名即可复用）。"""

    platform: str  # "qq" | "telegram"
    session_key: str  # 与聊天链路 session_id 同构：group_<gid>_<uid> / <uid>
    user_id: str
    message_id: str  # 被贴的那条消息
    emoji_id: str
    emoji_text: str  # 映射后的展示文本；映射不出=原 id
    count: int = 1
    ts: float = 0.0  # 信息性时间戳（epoch 秒）；TTL 由缓冲的 monotonic 时钟管


def session_key_from_ids(group_id: Any, user_id: Any) -> str:
    """镜像 OneBot V11 ``get_session_id``：群=f"group_<gid>_<uid>"，私聊=<uid>。"""
    group = str(group_id or "").strip()
    user = str(user_id or "").strip()
    if group:
        return f"group_{group}_{user or 'unknown'}"
    return user or "unknown"


def _likes_entries(event: Any) -> list[dict[str, Any]]:
    """NapCat 形态优先（``likes`` 列表）；退化到平铺 emoji_id/count 字段。"""
    likes = getattr(event, "likes", None)
    if isinstance(likes, list) and likes:
        return [entry for entry in likes if isinstance(entry, dict)] or []
    emoji_id = str(getattr(event, "emoji_id", "") or "").strip()
    if emoji_id:
        count_raw = getattr(event, "count", 1)
        try:
            count = max(1, int(count_raw))
        except (TypeError, ValueError):
            count = 1
        return [{"emoji_id": emoji_id, "count": count}]
    return []


def normalize_onebot_emoji_like(
    event: Any,
    *,
    bot_id: str = "",
    now: float | None = None,
) -> list[ReactionEvent]:
    """OneBot/NapCat 贴纸回应 notice → ReactionEvent 列表（容错解析）。

    已知 NapCat 形态：``notice_type=group_msg_emoji_like``，字段
    ``group_id/user_id/message_id/likes:[{emoji_id, count}]``；私聊等价
    形态无实机样本，按同构字段容错（``private_msg_emoji_like`` /
    ``msg_emoji_like`` / 平铺 emoji_id）。字段缺失的条目跳过；非本类
    事件返回空列表。**生产实机待验证**。
    """
    notice_type = str(getattr(event, "notice_type", "") or "").strip()
    if notice_type not in _EMOJI_LIKE_NOTICE_TYPES:
        return []
    user_id = str(getattr(event, "user_id", "") or "").strip()
    message_id = str(getattr(event, "message_id", "") or "").strip()
    group_id = getattr(event, "group_id", None)
    session_key = session_key_from_ids(group_id, user_id)
    ts = time.time() if now is None else float(now)
    events: list[ReactionEvent] = []
    for entry in _likes_entries(event):
        emoji_id = str(entry.get("emoji_id", "") or "").strip()
        if not emoji_id:
            continue
        try:
            count = max(1, int(entry.get("count", 1)))
        except (TypeError, ValueError):
            count = 1
        entry_user = str(entry.get("user_id", "") or "").strip() or user_id
        events.append(
            ReactionEvent(
                platform="qq",
                session_key=session_key,
                user_id=entry_user,
                message_id=message_id,
                emoji_id=emoji_id,
                emoji_text=emoji_display(emoji_id),
                count=count,
                ts=ts,
            )
        )
    _ = bot_id  # 预留：识别"贴的是不是 bot 的消息"需对照 bot 自身 id。
    return events


def normalize_telegram_reaction(
    *,
    chat_id: Any,
    message_id: Any,
    new_reaction: list[dict[str, Any]] | None,
    old_reaction: list[dict[str, Any]] | None = None,
    user_id: Any = "",
    ts: float = 0.0,
) -> ReactionEvent | None:
    """Telegram ``MessageReactionUpdated`` → ReactionEvent（**当前不可达**）。

    适配器 0.1.0b20 不投递 message_reaction Update（见模块 docstring）。
    本接口给未来版本接线用：只对"新增"的贴纸出事件（纯移除→None）；
    ``ReactionTypeEmoji`` 取 emoji 原字符，``custom_emoji`` 存原 id 诚实
    展示。离线可测，字段以 Bot API 官方模型为准。
    """
    new_list = [
        entry for entry in (new_reaction or []) if isinstance(entry, dict)
    ]
    if not new_list:
        return None
    old_keys = {
        str(entry.get("emoji") or entry.get("custom_emoji_id") or "")
        for entry in (old_reaction or [])
        if isinstance(entry, dict)
    }
    added: dict[str, Any] | None = None
    for entry in new_list:
        key = str(entry.get("emoji") or entry.get("custom_emoji_id") or "")
        if key and key not in old_keys:
            added = entry
            break
    if added is None:
        return None
    if str(added.get("type", "")) == "custom_emoji" or added.get("custom_emoji_id"):
        emoji_id = str(added.get("custom_emoji_id", "") or "")
        emoji_text = f"自定义表情#{emoji_id}" if emoji_id else ""
    else:
        emoji_id = str(added.get("emoji", "") or "")
        emoji_text = emoji_id
    if not emoji_id:
        return None
    return ReactionEvent(
        platform="telegram",
        session_key=str(chat_id or "").strip() or "unknown",
        user_id=str(user_id or "").strip(),
        message_id=str(message_id or "").strip(),
        emoji_id=emoji_id,
        emoji_text=emoji_text,
        count=1,
        ts=float(ts) if ts else time.time(),
    )


# --------------------------------------------------------------- 环形缓冲

_REACTION_BUFFER_TTL_SECONDS = 600.0  # 10 分钟
_REACTION_BUFFER_MAX_PER_CHAT = 8
_REACTION_BUFFER_MAX_CHATS = 256
_BOT_MESSAGE_TTL_SECONDS = 600.0
_BOT_MESSAGE_MAX = 32


class ReactionBuffer:
    """每会话最近贴纸回应（进程内，重启即清；LRU 封顶防慢泄漏）。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = _REACTION_BUFFER_TTL_SECONDS,
        max_per_chat: int = _REACTION_BUFFER_MAX_PER_CHAT,
        max_chats: int = _REACTION_BUFFER_MAX_CHATS,
    ) -> None:
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self.max_per_chat = max(1, int(max_per_chat))
        self.max_chats = max(1, int(max_chats))
        self._events: OrderedDict[str, deque[tuple[float, ReactionEvent]]] = (
            OrderedDict()
        )
        self._bot_messages: OrderedDict[str, deque[tuple[float, str]]] = (
            OrderedDict()
        )

    def record(self, event: ReactionEvent) -> None:
        now = self.clock()
        bucket = self._events.get(event.session_key)
        if bucket is None:
            if len(self._events) >= self.max_chats:
                self._events.popitem(last=False)  # 淘汰最久未活跃的会话。
            bucket = deque(maxlen=self.max_per_chat)
            self._events[event.session_key] = bucket
        else:
            self._events.move_to_end(event.session_key)
        bucket.append((now, event))

    def register_bot_message(self, session_key: str, message_id: Any) -> None:
        """登记 bot 自己发出的消息 id（供 describe 说"对我的消息"）。"""
        mid = str(message_id or "").strip()
        if not mid:
            return
        now = self.clock()
        bucket = self._bot_messages.get(session_key)
        if bucket is None:
            if len(self._bot_messages) >= self.max_chats:
                self._bot_messages.popitem(last=False)
            bucket = deque(maxlen=_BOT_MESSAGE_MAX)
            self._bot_messages[session_key] = bucket
        else:
            self._bot_messages.move_to_end(session_key)
        bucket.append((now, mid))

    def _fresh_bot_message_ids(self, session_key: str, now: float) -> set[str]:
        bucket = self._bot_messages.get(session_key)
        if not bucket:
            return set()
        while bucket and now - bucket[0][0] > _BOT_MESSAGE_TTL_SECONDS:
            bucket.popleft()
        return {mid for _, mid in bucket}

    def fresh_events(self, session_key: str) -> list[ReactionEvent]:
        now = self.clock()
        bucket = self._events.get(session_key)
        if not bucket:
            return []
        while bucket and now - bucket[0][0] > self.ttl_seconds:
            bucket.popleft()
        return [event for _, event in bucket]

    def describe(self, session_key: str) -> str:
        """渲染【表情回应】分区正文（不含标题）；没有任何新鲜回应 → 空串。"""
        events = self.fresh_events(session_key)
        if not events:
            return ""
        now = self.clock()
        bot_ids = self._fresh_bot_message_ids(session_key, now)
        lines: list[str] = []
        for event in events[-_REACTION_BUFFER_MAX_PER_CHAT:]:
            who = event.user_id or "有人"
            emoji = event.emoji_text or f"表情#{event.emoji_id}"
            if event.message_id in bot_ids:
                target = "我的消息"
            else:
                target = f"消息{event.message_id}" if event.message_id else "一条消息"
            count_part = f"×{event.count}" if event.count > 1 else ""
            lines.append(f"- {who} 给{target}贴了 {emoji}{count_part}")
        usage = (
            "（回应是反馈不是指令：把它当作对方此刻心情的线索，"
            "自然调整语气与分寸就好，不必逐条回应，也不要因此执行任何新动作。）"
        )
        return "\n".join(lines) + "\n" + usage


# --------------------------------------------------------------- 主动贴门控

_REACTION_LRU_CAP = 4096


class ProactiveGate:
    """主动贴表情五层门：开关→每消息去重→确定性概率→冷却→每小时滑窗。

    概率用确定性哈希（照戳一戳先例）：同 (会话, 消息) 判定恒定，重放/
    重试不会摇摆。``allow`` 返回 True 即已 commit（冷却+窗口+去重同时
    登记），调用方随后执行贴表情即可。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._last: OrderedDict[str, float] = OrderedDict()
        self._window: dict[str, deque[float]] = {}
        self._reacted: OrderedDict[tuple[str, str], None] = OrderedDict()

    def allow(
        self,
        session_key: str,
        message_key: str,
        *,
        enabled: bool,
        probability: float,
        cooldown_seconds: float,
        max_per_hour: int,
        salt: str = "",
        now: float | None = None,
    ) -> bool:
        if not enabled:
            return False
        key = str(session_key)
        msg_key = str(message_key)
        if not key or not msg_key:
            return False
        message_dedupe = (key, msg_key)
        if message_dedupe in self._reacted:
            return False
        current = self.clock() if now is None else float(now)
        last = self._last.get(key, -1e9)
        if current - last < max(0.0, float(cooldown_seconds)):
            return False
        window = self._window.setdefault(key, deque())
        while window and current - window[0] > 3600.0:
            window.popleft()
        if len(window) >= max(1, int(max_per_hour)):
            return False
        digest = int(
            hashlib.sha256(
                f"react:{salt}:{key}:{msg_key}".encode()
            ).hexdigest()[:8],
            16,
        ) / 0xFFFFFFFF
        if digest > max(0.0, min(1.0, float(probability))):
            return False
        # 全门通过，commit 所有状态。
        self._reacted[message_dedupe] = None
        self._reacted.move_to_end(message_dedupe)
        while len(self._reacted) > _REACTION_LRU_CAP:
            self._reacted.popitem(last=False)
        self._last[key] = current
        self._last.move_to_end(key)
        while len(self._last) > _REACTION_LRU_CAP:
            self._last.popitem(last=False)
        window.append(current)
        return True


# --------------------------------------------------------------- 动作包装

async def react_to_message(bot: Any, *, message_id: Any, emoji_id: int) -> bool:
    """NapCat 扩展 API：给消息贴表情。失败静默（无权限/平台不支持等）。"""
    mid = str(message_id or "").strip()
    if not mid:
        return False
    try:
        await bot.call_api(
            "set_msg_emoji_like",
            message_id=int(mid),
            emoji_id=str(int(emoji_id)),
        )
        return True
    except Exception:  # noqa: BLE001 - 贴表情失败绝不影响主链路。
        return False


async def react_telegram_message(
    bot: Any,
    *,
    chat_id: Any,
    message_id: Any,
    emoji: str = "👍",
    is_big: bool = False,
) -> bool:
    """Bot API 7.0+ ``set_message_reaction``（**本仓库未接线触发点**）。

    平台限制（诚实标注）：仅当 bot 在该群聊为管理员时可用；私聊 bot
    不能贴回应。保留给未来识别链路打通后的可选接线。
    """
    try:
        await bot.call_api(
            "set_message_reaction",
            chat_id=chat_id,
            message_id=int(str(message_id)),
            reaction=[{"type": "emoji", "emoji": emoji}],
            is_big=bool(is_big),
        )
        return True
    except Exception:  # noqa: BLE001 - 平台拒绝/不支持时静默。
        return False


def reaction_knobs(config: Any) -> dict[str, Any]:
    """读 bot_reactions_* 配置（getattr 缺省，兼容热覆盖合并后的视图）。"""
    return {
        "enabled": bool(getattr(config, "bot_reactions_enabled", True)),
        "probability": float(getattr(config, "bot_reactions_probability", 0.2)),
        "cooldown_seconds": float(
            getattr(config, "bot_reactions_cooldown_seconds", 30)
        ),
        "max_per_hour": int(getattr(config, "bot_reactions_max_per_hour", 20)),
    }


async def maybe_react_on_message(
    bot: Any,
    *,
    session_key: str,
    user_message_id: Any,
    text: str,
    config: Any,
    trigger: str,
    gate: ProactiveGate | None = None,
    now: float | None = None,
) -> bool:
    """主动贴表情编排：门控全过 → 给用户这条消息贴一个表情。

    trigger：
    - ``emotion_signal``：文本须命中情绪信号关键词（命中决定意图）；
    - ``after_reply``：bot 刚回复完，意图按确定性哈希从温和池里挑。
    """
    knobs = reaction_knobs(config)
    mid = str(user_message_id or "").strip()
    if not knobs["enabled"] or not mid:
        return False
    if trigger == "emotion_signal":
        intent = infer_signal_intent(text)
        if intent is None:
            return False
        salt = f"signal:{intent}"
    else:
        intent = ""
        salt = "reply"
    active_gate = gate if gate is not None else SHARED_PROACTIVE_GATE
    if not active_gate.allow(
        session_key,
        mid,
        enabled=True,  # 开关已在上面判过；这里保持门内状态一致。
        probability=knobs["probability"],
        cooldown_seconds=knobs["cooldown_seconds"],
        max_per_hour=knobs["max_per_hour"],
        salt=salt,
        now=now,
    ):
        return False
    emoji_id = select_reaction_emoji(intent, f"{session_key}:{mid}")
    return await react_to_message(bot, message_id=mid, emoji_id=emoji_id)


# ------------------------------------------------------- 进程级共享实例

SHARED_REACTION_BUFFER = ReactionBuffer()
SHARED_PROACTIVE_GATE = ProactiveGate()


def describe_chat_reactions(session_key: str) -> str:
    """人格上下文注入用：读共享缓冲渲染【表情回应】正文（空=整块不出现）。"""
    return SHARED_REACTION_BUFFER.describe(session_key)
