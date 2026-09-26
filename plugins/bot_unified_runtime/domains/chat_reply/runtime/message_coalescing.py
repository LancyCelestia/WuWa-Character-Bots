"""把同一个人连发的多条短句折成一轮，让一句话只回一次。

用户口径（2026-09-25）：QQ 上很多人把一句话按逗号拆成两三条发，bot 逐条
各回一次——既刷屏，又白烧算力与回复次数；而且同一次连发还会撞上「同人
45 秒最小间隔」被静默吞掉，越说越没人理。折成一轮之后，一句话只过一次
门禁、只跑一次能力、只回一句。

本模块只回答两件事：这条消息该不该等下一条、等到什么时候算一句说完。
怎么回复仍由既有链路负责——这里不长出第二条通路。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# 句末标点：以此收尾说明这句话说完了，不必再等下一条。
TERMINAL_PUNCTUATION = "。！？!?…～~＂\"’’』】）)"
# 明显挂着的收尾：逗号/顿号/冒号/连接词，以这些收尾极可能还有下一条。
HANGING_PUNCTUATION = "，,、;；:：+＋和与而就也还太更把被给让"
# 没有句末标点、又短成这样一条，多半是被截断的前半句。
_SHORT_UNFINISHED_CHARS = 24
# 合并时不再补分隔符的收尾集合：句末标点 + 分句标点都在内。
# 只数 TERMINAL 会拼出「守岸人，，在吗」这种双逗号——本仓第一轮测试就踩到了。
_SEPARATORS = TERMINAL_PUNCTUATION + HANGING_PUNCTUATION
# reply_chain 合并后的层数上限（摄取层本就限深 5，这里只防多轮叠加撑爆预算）。
_MAX_MERGED_REPLY_CHAIN = 8


@dataclass(frozen=True)
class CoalescingSettings:
    """折句窗口参数。全默认=保守，关掉即逐字节回到旧行为。"""

    enabled: bool = True
    # 停口这么久就算「这句话说完了」——决定额外延迟的下限。
    quiet_seconds: float = 1.8
    # 再怎么连着发也封顶，防止有人逐字蹦时 bot 永远不回。
    max_hold_seconds: float = 8.0
    # 折到这么多条立即放行（长串连发不该等到封顶）。
    max_messages: int = 6
    # 合并后正文的字符上限：再折会把上下文预算撑爆。
    max_chars: int = 1500


def looks_unfinished(text: str) -> bool:
    """这条消息本身是否像「半句话」——决定是否值得为它开等待窗口。

    判否（正常完整句子）时窗口根本不开，普通对话零额外延迟。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return False
    tail = stripped[-1]
    if tail in HANGING_PUNCTUATION:
        return True
    if tail in TERMINAL_PUNCTUATION:
        return False
    # 无句末标点：短的那条更像被截断的前半句。
    return len(stripped) <= _SHORT_UNFINISHED_CHARS


def join_utterance(texts: Iterable[str]) -> str:
    """把折在一起的短句拼回一句话。

    刻意不无脑加分隔符：上一条已经带标点（句末的。！？或分句用的，、）就直接连，
    只有裸收尾才补一枚中文逗号——「我今天去了」+「超市买东西」读回
    「我今天去了，超市买东西」；而「守岸人，」+「在吗」不得变成「守岸人，，在吗」。
    """
    parts = [str(text or "").strip() for text in texts]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    merged = parts[0]
    for part in parts[1:]:
        if merged[-1] in _SEPARATORS:
            merged = f"{merged}{part}"
        else:
            merged = f"{merged}，{part}"
    return merged


def message_turn_id(message: Any) -> str:
    """这条消息的对外身份：优先 message_id，缺则退 request_id（两者都可能为空）。"""
    return str(
        getattr(message, "message_id", "") or getattr(message, "request_id", "") or ""
    )


def utterance_turn_key(message: Any) -> str:
    """折句的分键：同一会话、同一发送者才算「同一个人说完一句话」。"""
    return (
        f"{getattr(message, 'session_id', '') or ''}"
        f":{getattr(message, 'sender_id', '') or ''}"
    )


def supports_coalescing(message: Any) -> bool:
    """这条消息能不能折。邮件面一律不折——一封邮件就是一个会话线程，
    把两封折成一封会让回信接错原信，比多回一句更糟。
    """
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    session_id = str(getattr(message, "session_id", "") or "")
    return not (platform == "mail" or session_id.startswith("email:"))


def build_coalescing_settings(config: Any) -> CoalescingSettings:
    """从 Config 装配折句参数。读不到的替身一律回落到保守缺省。"""
    defaults = CoalescingSettings()
    return CoalescingSettings(
        enabled=bool(getattr(config, "bot_chat_message_coalescing_enabled", True)),
        quiet_seconds=float(
            getattr(config, "bot_chat_message_coalescing_quiet_seconds", defaults.quiet_seconds)
        ),
        max_hold_seconds=float(
            getattr(config, "bot_chat_message_coalescing_max_hold_seconds", defaults.max_hold_seconds)
        ),
        max_messages=int(
            getattr(config, "bot_chat_message_coalescing_max_messages", defaults.max_messages)
        ),
        max_chars=int(
            getattr(config, "bot_chat_message_coalescing_max_chars", defaults.max_chars)
        ),
    )


# 进程内唯一折句器：窗口状态必须跨事件共享（每条消息一个新实例就永远折不住），
# 但配置每次实时重读，好让 /bot runtime set 改了立刻生效。
# 状态住在本模块而不是插件根文件——根文件里加模块级变量会把 campus matcher 的
# 登记行号往上顶（outbound_registry 那条活体坐标棘轮盯着它）。
_SHARED: MessageCoalescer | None = None
_SHARED_LOCK = threading.Lock()


def shared_coalescer(settings: CoalescingSettings) -> MessageCoalescer:
    """拿到跨事件共享的折句器，并把本轮配置换进去。"""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = MessageCoalescer(settings)
        else:
            _SHARED.settings = settings
        return _SHARED


@dataclass
class CoalescedTurn:
    """一次「折好的一轮」。

    ``owned`` 为真表示本条消息是这个窗口的开门者，由它负责真正回一句；
    为假表示它已被折进别人那一轮，调用方必须就此返回、不要再回一句。
    """

    owned: bool
    message: Any
    folded_message_ids: list[str] = field(default_factory=list)
    folded_count: int = 1


@dataclass
class _Window:
    first_at: float
    last_at: float
    messages: list[Any] = field(default_factory=list)
    flush_event: asyncio.Event | None = None


class MessageCoalescer:
    """按 (会话, 发送者) 缓冲连发消息，等一句话说完再放行一条。

    单事件循环内使用：状态变更都在协程的同步段里完成，不加线程锁。
    计时只认注入的 ``clock``（缺省 ``time.monotonic``），全程不与
    ``loop.time()`` 混用——两者虽同源，混用会让「注入假钟」的测试失真。
    """

    def __init__(
        self,
        settings: CoalescingSettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or CoalescingSettings()
        self._clock = clock
        self._windows: dict[str, _Window] = {}

    @property
    def pending_keys(self) -> tuple[str, ...]:
        """当前有几个人正把一句话拆着发（供 /bot status 与巡检观测）。"""
        return tuple(self._windows.keys())

    def reset(self) -> None:
        self._windows.clear()

    def _worth_waiting(self, message: Any) -> bool:
        """这条消息值不值得为它等下一条。

        只认「这条本身像半句话」这一个判据。曾经还想加「此人最近在连发就也等」，
        判掉的理由：那条判据会让正常一来一回的对话每条都白白多等一个停口窗，
        而真正的分句发送在一两秒内就到齐、已经被 quiet 窗接住了。
        """
        return bool(
            self.settings.enabled
            and looks_unfinished(getattr(message, "plain_text", ""))
        )

    def _flush_deadline(self, window: _Window) -> float:
        settings = self.settings
        return min(
            window.first_at + settings.max_hold_seconds,
            window.last_at + settings.quiet_seconds,
        )

    def _is_complete(self, window: _Window) -> bool:
        """已经够一轮的量：条数或字数封顶，不必再等。"""
        settings = self.settings
        if len(window.messages) >= max(1, settings.max_messages):
            return True
        total = sum(
            len(str(getattr(message, "plain_text", "") or ""))
            for message in window.messages
        )
        return total >= max(1, settings.max_chars)

    def _release(self, turn_key: str, window: _Window) -> None:
        """摘走窗口并唤醒开门者：封顶到了，不用再等停口。"""
        if self._windows.get(turn_key) is window:
            self._windows.pop(turn_key, None)
        if window.flush_event is not None:
            window.flush_event.set()

    async def offer(self, turn_key: str, message: Any) -> CoalescedTurn:
        """折入这条消息；拿到 ``owned=True`` 的那一路才负责回复。

        开门者就地等窗口收口，等到后返回合并轮；后来者折进同一窗口并返回
        ``owned=False``，因此一句话只会有一次回复。
        """
        if not self.settings.enabled:
            return CoalescedTurn(owned=True, message=message)

        now = self._clock()
        window = self._windows.get(turn_key)

        if window is not None:
            window.messages.append(message)
            window.last_at = now
            if self._is_complete(window):
                self._release(turn_key, window)
            return CoalescedTurn(
                owned=False,
                message=message,
                folded_message_ids=[message_turn_id(message)],
            )

        if not self._worth_waiting(message):
            return CoalescedTurn(owned=True, message=message)

        window = _Window(
            first_at=now,
            last_at=now,
            messages=[message],
            flush_event=asyncio.Event(),
        )
        self._windows[turn_key] = window
        try:
            await self._await_flush(turn_key, window)
        finally:
            if self._windows.get(turn_key) is window:
                self._windows.pop(turn_key, None)
        merged = merge_turn(window.messages)
        return CoalescedTurn(
            owned=True,
            message=merged,
            folded_message_ids=[message_turn_id(item) for item in window.messages],
            folded_count=len(window.messages),
        )

    async def _await_flush(self, turn_key: str, window: _Window) -> None:
        """等到「停口够久」或「封顶」为止；期间有新消息就顺延。

        新到达只会把 ``last_at`` 往后推 ⇒ 截止时间单调变晚，所以按当下剩余
        去等不会提前放行；条数/字数封顶由到达方 ``_release`` 唤醒开门者。
        """
        flush_event = window.flush_event
        assert flush_event is not None
        while True:
            if self._windows.get(turn_key) is not window:
                return  # 已被封顶摘走
            remaining = self._flush_deadline(window) - self._clock()
            if remaining <= 0:
                return
            # 不用 shield：这里等的只是 Event.wait()，超时取消它没有任何副作用。
            # 套 shield 反而会让每轮超时都留下一个永不结束的等待任务。
            try:
                await asyncio.wait_for(flush_event.wait(), remaining)
            except TimeoutError:
                pass
            if self._windows.get(turn_key) is not window:
                return
            if self._is_complete(window):
                return


def merge_turn(messages: Sequence[Any]) -> Any:
    """把折在一起的多条消息合成一条「一轮」。

    身份事实取开门者那条（回复要落在原会话与原请求上），文本与媒体段按到达
    顺序合并，点名/软点名/引用等按「有过就算有」归并——不新开字段、不造第二
    份消息模型，消费方读到的仍是同一个 IncomingMessage。
    """
    items = [message for message in messages if message is not None]
    if not items:
        raise ValueError("merge_turn 需要至少一条消息")
    head = items[0]
    if len(items) == 1:
        return head

    segments: list[dict[str, Any]] = []
    chains: list[Any] = []
    for message in items:
        segments.extend(list(getattr(message, "raw_segments", None) or []))
        chains.extend(list(getattr(message, "reply_chain", None) or []))

    updates: dict[str, Any] = {
        "plain_text": join_utterance(getattr(m, "plain_text", "") for m in items),
        "raw_segments": segments,
        "mentions_bot": any(getattr(m, "mentions_bot", False) for m in items),
        "name_mention_only": all(getattr(m, "name_mention_only", False) for m in items),
        "soft_persona_mention": any(
            getattr(m, "soft_persona_mention", False) for m in items
        ),
        "reply_chain": chains[:_MAX_MERGED_REPLY_CHAIN],
    }
    for name in (
        "command_text",
        "reply_to_message_id",
        "reply_to_text",
        "reply_video_path",
        "reply_media_segments",
        "chat_record_text",
    ):
        if updates.get(name):
            continue
        for message in items:
            value = getattr(message, name, None)
            if value:
                updates[name] = value
                break
    return head.model_copy(update=updates)
