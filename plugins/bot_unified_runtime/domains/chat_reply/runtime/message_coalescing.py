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

# ---------------------------------------------------------------------------
# 句子完结判定（需求 1，2026-09-29 用户裁定升级）。
#
# 旧判据只回答「这条本身像不像半句话」——用户把一句话按逗号/句号拆成几个短句气泡
# 时，凡自带句号的第一条都不开窗，照样逐条各回一次。新判据回答的是「这句话是不是
# 说完了」：一组**命名信号谓词**（每个都可独立单测、可点名解释），任一未完信号
# 命中就开窗，信号的**强度**同时决定等多久（越像半句等得越久，越像说完等得越短，
# 见 `effective_quiet_seconds` 与 MessageCoalescer._flush_deadline）。
# 刻意不是「一长串硬编码 if」：规则表 _COMPLETION_SIGNALS 加一条＝表里加一行。
# ---------------------------------------------------------------------------

# 句末终止语气：疑问/感叹这类收尾＝话说到头了，绝不为它开等待窗
# （普通一来一回的对话零额外延迟，是这条线的硬底线）。
_STRONG_TERMINAL_TONE = "？！!?～~…"
# 弱终止：句号系。带句号≠说完了——很短的一条更可能是「一句一气泡」连发中的一段。
_WEAK_TERMINAL = "。．."
# 很短的句号收尾按「连发中的一段」处理（短窗轻等）；超过这个长度就按说完了放行。
_BURST_FRAGMENT_CHARS = 12
# 弱信号只轻等：满窗 × 这个系数。12 字内的「今天天气不错。」实测连发间隔多 <1 秒，
# 0.45×3.0s≈1.35s 足够接住下一条，又不至于把正常单句拖成满窗。
_MILD_STRENGTH = 0.45
# 左引号/左括号收尾：引号没合口，后面必然还有内容。
_LEFT_QUOTES = "（(【[「『“‘《\"'"
# 破折号收尾：话说一半被「——」切断（QQ 长句连发的高频形状）。
_DASHES = "—－"
# 多字连接词收尾：「……因为」「……但是」这种句子挂在中途。
_CONNECTOR_WORDS = (
    "因为", "所以", "而且", "然后", "不过", "但是", "可是", "就是", "还有",
    "以及", "并且", "或者", "要么", "甚至", "虽然", "既然", "假如", "如果",
    "除了", "另外", "其实", "反正", "接着", "因而", "于是", "由于", "连同",
    "包括", "只是",
)
# 量词/数词收尾：「买三」「来两」「第一」——后面跟着的才是中心语。
_QUANTITY_TAIL = frozenset(
    "个只条张块件位次些双份种样番回一二两三四五六七八九十百千万几每"
)


@dataclass(frozen=True)
class CompletionVerdict:
    """一条消息的「说完没有」判定：可解释、带强度、信号点名。"""

    pending: bool
    strength: float
    signals: tuple[str, ...]


def _ends_hanging(text: str) -> bool:
    return bool(text) and text[-1] in HANGING_PUNCTUATION


def _ends_connector_word(text: str) -> bool:
    return any(text.endswith(word) for word in _CONNECTOR_WORDS)


def _ends_dash(text: str) -> bool:
    return bool(text) and text[-1] in _DASHES


def _ends_left_quote(text: str) -> bool:
    return bool(text) and text[-1] in _LEFT_QUOTES


def _ends_quantity(text: str) -> bool:
    return bool(text) and text[-1] in _QUANTITY_TAIL


def _starts_continuation(text: str) -> bool:
    if not text:
        return False
    if text[0] in "，,、;；:：":
        return True
    return any(text.startswith(word) for word in _CONNECTOR_WORDS)


def _no_terminal_short(text: str) -> bool:
    """没有任何句末收尾、又短：典型「被截断的前半句」（旧判据的短无标点腿）。"""
    if not text:
        return False
    tail = text[-1]
    if tail in _STRONG_TERMINAL_TONE or tail in _WEAK_TERMINAL:
        return False
    return len(text) <= _SHORT_UNFINISHED_CHARS


def _short_burst_fragment(text: str) -> bool:
    """自带句号但很短：更可能是「一句短句一个气泡」连发中的一段，轻等一下。"""
    if not text or text[-1] not in _WEAK_TERMINAL:
        return False
    return len(text) <= _BURST_FRAGMENT_CHARS


# (信号名, 谓词, 强度)——谓词一律 (raw, stripped) 可单参化，见 _signal_hit。
_COMPLETION_SIGNALS: tuple[tuple[str, Callable[[str], bool], float], ...] = (
    ("trailing_hanging_punctuation", _ends_hanging, 1.0),
    ("trailing_connector", _ends_connector_word, 1.0),
    ("trailing_dash", _ends_dash, 1.0),
    ("unclosed_left_quote", _ends_left_quote, 1.0),
    ("trailing_quantity", _ends_quantity, 1.0),
    ("leading_continuation", _starts_continuation, 1.0),
    ("no_terminal_short", _no_terminal_short, 1.0),
    ("short_burst_fragment", _short_burst_fragment, _MILD_STRENGTH),
)


def utterance_completion(text: str) -> CompletionVerdict:
    """这条消息「说完了吗」的可解释判定。

    返回 pending=要不要继续等下一条、strength=等多久（满窗的比例，0~1]、
    signals=命中的信号名（审计与测试都能点名，绝不黑箱）。
    """
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        return CompletionVerdict(pending=False, strength=0.0, signals=())
    # 换行收尾看原文，其余信号看剥离后。
    fired: list[str] = []
    if raw.endswith(("\n", "\r")):
        fired.append("line_split_continuation")
    strength = 0.0
    for name, predicate, weight in _COMPLETION_SIGNALS:
        if predicate(stripped):
            if name not in fired:
                fired.append(name)
            strength = max(strength, weight)
    if not fired:
        return CompletionVerdict(pending=False, strength=0.0, signals=())
    return CompletionVerdict(pending=True, strength=strength, signals=tuple(fired))


def looks_unfinished(text: str) -> bool:
    """这条消息是否需要继续等下一条（兼容旧签名：判据升级住在上面谓词组）。"""
    return utterance_completion(text).pending


def effective_quiet_seconds(settings: CoalescingSettings, strength: float) -> float:
    """自适应停口窗：满窗按「最像半句」的那条给，越像说完缩得越短。

    下限 0.35 秒是实打实的接住线：QQ 连发的气泡到达差再小也有一两百毫秒，
    缩到零等于不开窗；硬封顶（max_hold）在调用侧另管，这里只缩放「等下一条」。
    """
    scaled = float(settings.quiet_seconds) * max(0.0, min(1.0, float(strength)))
    return max(0.35, scaled)


@dataclass(frozen=True)
class CoalescingSettings:
    """折句窗口参数。全默认=保守，关掉即逐字节回到旧行为。"""

    enabled: bool = True
    # 停口这么久就算「这句话说完了」——决定额外延迟的下限。
    # 2026-09-27 乙案：Config 键 bot_chat_message_coalescing_quiet_seconds 已退役，
    # 窗口唯一真身是 message_merge.MERGE_WINDOW_SECONDS（用户裁定 3s，装配层每轮
    # apply 权威值）；本缺省与之对齐（1.8→3.0），等值由
    # tests/test_inbound_merge_preserves_ids.py 的缺省↔常量锁钉死。
    quiet_seconds: float = 3.0
    # 再怎么连着发也封顶，防止有人逐字蹦时 bot 永远不回。
    max_hold_seconds: float = 8.0
    # 折到这么多条立即放行（长串连发不该等到封顶）。
    max_messages: int = 6
    # 合并后正文的字符上限：再折会把上下文预算撑爆。
    max_chars: int = 1500


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
    命令形状（"/…" 起手，含 "/bot" 族）一律不折：命令要立刻执行，
    不进任何等待窗（需求 1 之 5；正常链路里命令 matcher 先于 chat matcher
    拦截、根本到不了这里，本判据是第二道闸，防装配顺序被改动时静默吞命令）。
    """
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    session_id = str(getattr(message, "session_id", "") or "")
    if platform == "mail" or session_id.startswith("email:"):
        return False
    command_like = str(
        getattr(message, "command_text", "") or getattr(message, "plain_text", "") or ""
    ).lstrip()
    return not command_like.startswith("/")


def build_coalescing_settings(config: Any) -> CoalescingSettings:
    """从 Config 装配折句参数。读不到的替身一律回落到保守缺省。

    2026-09-27 乙案：等待窗（quiet_seconds）不再从 Config 读——Config 键已退役，
    唯一真身是 message_merge.MERGE_WINDOW_SECONDS，由装配层每轮
    apply_merge_window_seconds 权威写入；这里只留 dataclass 缺省作回落形态。
    """
    defaults = CoalescingSettings()
    return CoalescingSettings(
        enabled=bool(getattr(config, "bot_chat_message_coalescing_enabled", True)),
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


# 进程内唯一折句器：窗口状态必须跨事件共享（每条消息一个新实例就永远折不住）。
# 配置每轮从 Config 快照现读（enabled/max_hold_seconds/max_messages/max_chars 四键），
# 但四键属重启档（settings.py RESTART_REQUIRED_KEYS 在册），/bot runtime set 热改覆盖
# 不可达，故不说"改了立刻生效"；等待窗 quiet_seconds 乙案后已不再读 Config——
# 唯一真身是 message_merge.MERGE_WINDOW_SECONDS，由装配层每轮 apply_merge_window_seconds 覆盖。
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
    # 窗内「最像半句」那条的强度（0~1]：自适应停口窗的缩放尺（需求 1 之 2）。
    strength: float = 1.0


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

    def _worth_waiting(self, message: Any) -> CompletionVerdict:
        """这条消息值不值得为它等下一条、以及该等多久（强度）。

        判据真身＝`utterance_completion` 的命名信号组（需求 1 升级）：不止
        「这条本身像半句话」，短句带句号、连接词/量词/破折号/左引号收尾、
        被逗号/换行切断的同一句延续都算未完。曾经还想加「此人最近在连发就也等」，
        判掉的理由：那条判据会让正常一来一回的对话每条都白白多等一个停口窗；
        自适应短窗（`effective_quiet_seconds`）已经接住了真连发，不需要它。
        """
        if not self.settings.enabled:
            return CompletionVerdict(pending=False, strength=0.0, signals=())
        return utterance_completion(getattr(message, "plain_text", ""))

    def _flush_deadline(self, window: _Window) -> float:
        settings = self.settings
        return min(
            window.first_at + settings.max_hold_seconds,
            window.last_at + effective_quiet_seconds(settings, window.strength),
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
            # 新到的一条更像半句 ⇒ 整轮往后顺延得更久（自适应取窗内最大强度）。
            window.strength = max(
                window.strength,
                utterance_completion(getattr(message, "plain_text", "")).strength,
            )
            if self._is_complete(window):
                self._release(turn_key, window)
            return CoalescedTurn(
                owned=False,
                message=message,
                folded_message_ids=[message_turn_id(message)],
            )

        verdict = self._worth_waiting(message)
        if not verdict.pending:
            return CoalescedTurn(owned=True, message=message)

        window = _Window(
            first_at=now,
            last_at=now,
            messages=[message],
            flush_event=asyncio.Event(),
            strength=verdict.strength,
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


# ---------------------------------------------------------------------------
# 折句的唯一入口（需求 1，2026-09-29 用户裁定：**实现暂缓，接口必须留干净**）。
#
# 用户口径是「暂时保持用户一个气泡、bot 回一个」——生产开关
# `.env: BOT_CHAT_MESSAGE_COALESCING_ENABLED=false` 原样不动，本波不改任何行为。
# 这一节只做两件事：① 把原先散在根 `__init__.py` 里的调用点收敛成**一个**显式入口
# （禁第二通路）；② 把契约写死在真身旁边，将来启用不必重新考古。没有新抽象层：
# 窗口、判据、合并全都还是本模块原有的件，这里只是接缝整形。
#
# 契约（每条都有行为锁；锁住在 tests/test_coalescing_wiring_lock.py、
# tests/test_coalescing_sentence_completion.py、tests/test_inbound_merge_preserves_ids.py）：
# - 边界：输入 N 条气泡（同会话同人）→ 输出**一个**待处理单元，或**原样透传**。
#   本层只回答「这条要不要等下一条」，怎么回复仍由既有链路负责。
# - 一翻键即启用：`enabled` 为假时 `offer()` 第一行就返回
#   `CoalescedTurn(owned=True, message=<同一条对象>)`——不开窗、不改写、不留状态，
#   关闭态与「折句功能不存在」逐字节等价（锁名见 test_disabled_seam_is_byte_identical_passthrough）。
# - 折句后保留全部原始 message_id：`CoalescedTurn.folded_message_ids` 与合并轮身上的
#   `IncomingMessage.folded_message_ids` 同源；幂等/回执/补投按头 id 走，逐条对账看这本账。
# - 引用链与段类型不丢：`merge_turn` 按到达顺序并 `raw_segments` / `reply_chain`，
#   图片+文字串行不吞图。
# - 命令族气泡不进等待窗：`supports_coalescing()` 认 `/` 起手一律拒折；正常链路里命令
#   matcher（priority≤43、block=True）先于 chat matcher（priority=50）拦截，根本到不了
#   本入口——那道判据是第二道闸，防装配顺序被改动时静默吞命令。
#
# 将来要启用，只动这三处（除此之外不必碰任何文件）：
#   1. `.env` 的 `BOT_CHAT_MESSAGE_COALESCING_ENABLED=false` → `true`：装配期快照
#      （台账 #3），且该键登记在 `runtime/settings.py` 的「覆盖册不可达」表里 ⇒ 必须重启；
#   2. 等待窗真身 `message_merge.MERGE_WINDOW_SECONDS`：2026-09-27 乙案后 Config 的
#      `_quiet_seconds` 键已退役，窗口只有这一处真身，装配层每轮 apply 权威值；
#   3. 判据表 `_COMPLETION_SIGNALS`（经 `utterance_completion`）：决定哪类气泡开窗、
#      开多久（强度→`effective_quiet_seconds`）。
#
# 已知两个判据短板（启用前须知情，别当成「开了就一定折得住」）：
#   a. **各自带句号的两条**：短句式收尾只按 `_MILD_STRENGTH`（0.45）轻等 ≈1.35 秒，
#      到达差超过这个轻等窗就折不住；超过约 `_BURST_FRAGMENT_CHARS`（12 字）的带句号
#      那条干脆不开窗。
#   b. **判据只看单条像不像半句话**：刻意没有「此人最近在连发就也等」这类跨条判据
#      （评估过并判掉：那会让正常一来一回的对话每条白等一个停口窗）。两条各自完整、
#      间隔稍长的连发仍会各回一次。
# ---------------------------------------------------------------------------


async def fold_inbound_turn(config: Any, message: Any) -> CoalescedTurn:
    """根装配层唯一可调的折句入口：这一轮归谁、要不要就此返回。

    返回 ``owned=False`` ⇒ 本条已被折进别人那一轮，调用方必须直接返回、不再回第二句
    （省下的正是多出来的那次回复与算力）；返回 ``owned=True`` ⇒ 拿着 ``message``
    （可能是合并轮，也可能是原样透传的原条）继续走既有链路。
    折句开关、窗口权威值、分键、单例获取都只在这里收口——第二处调用点即第二通路。
    """
    if not supports_coalescing(message):
        return CoalescedTurn(owned=True, message=message)
    # 函数体内 import：message_merge 只在 TYPE_CHECKING 下反向引用本件，运行期不绕圈；
    # 同时保住「不在本件顶部加依赖行」这条既有口径。
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        message_merge as _message_merge,
    )

    coalescer = shared_coalescer(build_coalescing_settings(config))
    # 等待窗以模块常量为权威（乙案），只换 quiet_seconds；
    # 封顶/条数/字数仍从 Config 现读 ⇒ 护栏语义不变。
    coalescer.settings = _message_merge.apply_merge_window_seconds(coalescer.settings)
    return await coalescer.offer(utterance_turn_key(message), message)


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
        # 逐条原始 message_id 账（需求 1 之 3）：幂等/回执/补投要用，全部随合并轮
        # 走完全链路（承载位＝IncomingMessage.folded_message_ids，缺省空表）。
        "folded_message_ids": [message_turn_id(m) for m in items],
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
