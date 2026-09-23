"""S-W15 图类独立最小间隔（「图片 120 秒」）的落地锁。

本格修的是**在册未执法**：参数 ``group_vision_min_interval_seconds``（缺省 120）
此前只在 ``_rollback_group_pacing`` / ``_group_pacing_rollback_deletes`` 里被"退账"，
既没有判定点也没有提交点 ⇒ 她裁的"图 120 秒"一格都不生效。本文件钉死八件事：

1. 含图消息在 120 秒内被拦（reason 精确、retry_after 报真正卡住的那道）。
2. 出 120 秒后放行。
3. 非图消息不受这道门影响（图类那一格只认视觉段），且图片/表情包/动图/视频四类
   都必须被管住——漏一类＝裁定只做了一半。
4. 情绪/好感豁免**免**图类间隔，但**不免**分钟帽（2026-09-24 裁定 3 的覆盖面）。
5. 两把尺（InMemory / SQLite）同一条时间线给出**同一条 reason+retry 序列**。
6. 参数为 0 时整层惰性：谓词连被调用的机会都没有、桶也不建 ⇒ 逐字节回到本格落地前。
7. 拒绝时一格不写（B-1 幽灵扣减口径，黑盒验证：被拦那句不许把图类钟拨走）。
8. 判定复用门禁那枚单一真身谓词，限流器里不许有第二套段类型判据。

纪律：全离线、注入时钟、SQLite 走 tmp_path、零网络（视觉段一律 http URL，
``extract_image_urls`` 对 http 只做字符串透传，不读盘不发包）。
断言一律不手写"这条算不算图"——含图与否由生产谓词确认（见 ``_visual`` 前置断言）；
唯一例外是第 8 条那发**故意**打毒谓词的用例，它要的正是"现问门禁"这件事，
故其消息构造绕开前置自检（否则是测夹具不是测代码）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy import gate, rate_limit
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    PACING_SCOPE_VISION_LAST,
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
)

# 她 2026-09-24 裁定的两个数字，钉死在此（改缺省要走裁定，不许顺手）。
RULED_VISION_INTERVAL_SECONDS = 120
RULED_TEXT_INTERVAL_SECONDS = 20
SAD_TEXT = "我好难受，想哭"  # 既有规则情绪识别的 support_needed 触发句（见 test_group_rate_limit）


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def _segments(kind: str) -> list[dict[str, Any]]:
    """四种视觉形态各造一段（图片/表情包/动图/视频——她裁的"图"是这四类）。"""
    table = {
        "photo": ("image", "https://example.invalid/a.png"),
        "sticker": ("emoji", "https://example.invalid/b.png"),
        "animation": ("animation", "https://example.invalid/c.gif"),
        "video": ("video", "https://example.invalid/d.mp4"),
    }
    seg_type, url = table[kind]
    return [{"type": seg_type, "data": {"url": url}}]


def _message(text: str = "在吗", *, visual: str | None = None) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group_123456",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="123456",
        plain_text=text,
        raw_segments=_segments(visual) if visual else [],
    )


def _visual(kind: str = "photo", text: str = "看看这张") -> IncomingMessage:
    """含视觉段的消息——**前置条件由生产谓词确认**，测试不手写"这算图"。"""
    message = _message(text, visual=kind)
    assert gate.message_has_visual_content(message) is True, (
        f"夹具不成立：{kind} 段在谓词眼里不是视觉内容，本用例就是空跑"
    )
    return message


def _plain(text: str = "在吗") -> IncomingMessage:
    message = _message(text)
    assert gate.message_has_visual_content(message) is False, "夹具不成立：纯文本被判成含图"
    return message


def _settings(**overrides: Any) -> RateLimitSettings:
    base: dict[str, Any] = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
        # 令牌面抬到不构成约束（1 句/秒回血），本格只量间隔位。
        "group_pacing_tokens_per_hour": 3600,
        "group_pacing_burst_capacity": 5,
        "group_pacing_max_per_minute": 0,
        "group_pacing_min_interval_seconds": RULED_TEXT_INTERVAL_SECONDS,
        "group_vision_min_interval_seconds": RULED_VISION_INTERVAL_SECONDS,
    }
    base.update(overrides)
    return RateLimitSettings(**base)


@pytest.fixture
def both(tmp_path: Path):
    """两把尺各带自己的注入时钟，成对构造（同一条时间线由用例自己逐步推进两表）。"""

    def _make(**overrides: Any):
        memory_clock = _Clock()
        sqlite_clock = _Clock()
        return [
            (
                "InMemory",
                InMemoryRateLimiter(_settings(**overrides), clock=memory_clock),
                memory_clock,
            ),
            (
                "SQLite",
                SQLiteRateLimiter(
                    tmp_path / f"vision_{abs(hash(repr(sorted(overrides.items()))))}.db",
                    _settings(**overrides),
                    clock=sqlite_clock,
                ),
                sqlite_clock,
            ),
        ]

    return _make


# ------------------------------------------------- ① 含图被 120 秒拦住


def test_visual_message_is_blocked_inside_vision_interval(both) -> None:
    for name, limiter, clock in both():
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        clock.advance(seconds=30)  # 越过文字 20 秒，仍在图类 120 秒内
        blocked = limiter.check_and_record(_visual(), "bot.chat")
        assert (blocked.allowed, blocked.reason) == (
            False,
            "group_pacing_vision_min_interval",
        ), f"{name}: 图类间隔没拦住 → {blocked.allowed}/{blocked.reason}"
        # retry_after 必须是"真正卡住的那道"（120-30=90），不是文字那道的零头。
        assert blocked.retry_after_seconds == 90, (
            f"{name}: 预告失真 → {blocked.retry_after_seconds}"
        )


# ------------------------------------------------- ② 出 120 秒后放行


def test_visual_message_allowed_once_vision_interval_elapsed(both) -> None:
    for name, limiter, clock in both():
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        clock.advance(seconds=119)
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is False, (
            f"{name}: 119 秒就放行，120 秒的额度形同虚设"
        )
        clock.advance(seconds=2)  # 合计 121 秒
        after = limiter.check_and_record(_visual(), "bot.chat")
        assert after.allowed is True, f"{name}: 出窗后仍被拦 → {after.reason}"


# ------------------------------------------- ③ 非图不受这道门影响（含四种视觉形态）


def test_text_message_is_not_bound_by_vision_interval(both) -> None:
    for name, limiter, clock in both():
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        clock.advance(seconds=25)  # 文字间隔已过、图类间隔未过
        text = limiter.check_and_record(_plain(), "bot.chat")
        assert (text.allowed, text.reason) == (True, "allowed"), (
            f"{name}: 纯文字被图类间隔误伤 → {text.allowed}/{text.reason}"
        )


@pytest.mark.parametrize("kind", ["photo", "sticker", "animation", "video"])
def test_all_four_visual_shapes_are_governed(kind: str, tmp_path: Path) -> None:
    """图片/表情包/动图/视频四类都必须走这道门——漏一类＝裁定只做了一半。"""
    limiter = SQLiteRateLimiter(
        tmp_path / f"shapes_{kind}.db", _settings(), clock=_Clock()
    )
    assert limiter.check_and_record(_visual(kind), "bot.chat").allowed is True, kind
    second = limiter.check_and_record(_visual(kind), "bot.chat")
    assert second.reason == "group_pacing_vision_min_interval", (
        f"{kind} 段没被图类间隔管住 → {second.allowed}/{second.reason}"
    )


# ------------------------------------- ④ 豁免免图类间隔、但绝不免句数帽


def test_emotion_exemption_waives_the_vision_interval(both) -> None:
    """锁**判定**不锁标签：豁免必须真的把图类门免掉，两把尺都算数。

    三步式（ armed-gate 对照），避免"门本来就没 armed"造成的假绿：
    ①含图先放行 → ②同刻非豁免含图必被 120 秒拦下（证明门是活的）→
    ③同刻情绪低落含图放行（证明免的正是这道门）。
    标签的跨尺分歧见 §0-3，此处刻意不断言。
    """
    for name, limiter, _clock in both():
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        armed = limiter.check_and_record(_visual(), "bot.chat")
        assert (armed.allowed, armed.reason) == (
            False,
            "group_pacing_vision_min_interval",
        ), f"{name}: 对照步没建立图类门，第③步就成了空跑 → {armed.allowed}/{armed.reason}"
        exempt = limiter.check_and_record(_visual("photo", SAD_TEXT), "bot.chat")
        assert exempt.allowed is True, (
            f"{name}: 豁免没能免掉图类间隔 → {exempt.allowed}/{exempt.reason}"
        )


def test_emotion_exemption_never_waives_the_minute_cap(both) -> None:
    """裁定 3 的另一半：豁免只免间隔，句数帽照旧——否则一句难过话能连开整窗额度。"""
    for name, limiter, _clock in both(group_pacing_max_per_minute=1):
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        capped = limiter.check_and_record(_visual("photo", SAD_TEXT), "bot.chat")
        assert (capped.allowed, capped.reason) == (
            False,
            "group_pacing_minute_exceeded",
        ), f"{name}: 豁免越权免掉了分钟帽 → {capped.allowed}/{capped.reason}"


# ---------------------------------------------- ⑤ 两把尺同一条时间线同一序列


def test_both_rulers_give_the_identical_reason_sequence(both) -> None:
    """同一条时间线喂两把尺，逐格比对 (allowed, reason, retry_after)。

    序列本身也写死（只比对两把尺会双双错在同一处而不被发现——"两把尺互证"必须
    另有一把独立的尺）。第 6 格是豁免句：它**不免记**，因此把第 7 格的放行时刻
    推到 151 秒之后——这既是"宽者先判"的证据，也是"豁免只免判不免记账"的证据。
    """
    # (时刻, 视觉段类型或 None, 是否情绪低落)
    timeline: list[tuple[int, str | None, bool]] = [
        (0, "photo", False),
        (5, None, False),
        (25, "photo", False),
        (25, None, False),
        (30, "photo", False),
        (31, "photo", True),
        (155, "photo", False),
    ]
    expected: list[tuple[bool, str, int]] = [
        (True, "allowed", 0),
        (False, "group_pacing_min_interval", 15),
        (False, "group_pacing_vision_min_interval", 95),
        (True, "allowed", 0),
        (False, "group_pacing_vision_min_interval", 90),
        (True, "emotion_exempt", 0),
        (True, "allowed", 0),
    ]
    traces: dict[str, list[tuple[bool, str, int]]] = {}
    for name, limiter, clock in both():
        trace: list[tuple[bool, str, int]] = []
        previous = 0
        for moment, kind, distressed in timeline:
            clock.advance(seconds=moment - previous)
            previous = moment
            if kind:
                message = _visual(kind, SAD_TEXT if distressed else "看看这张")
            else:
                message = _plain()
            decision = limiter.check_and_record(message, "bot.chat")
            trace.append(
                (decision.allowed, decision.reason, decision.retry_after_seconds)
            )
        traces[name] = trace
    # ⚠ 已知的**跨尺标签分歧**（非本格引入，见 SEAT-W15 §0-3）：只开节奏层、不开
    # 群窗帽时，SQLite 侧的 exemption 在 `_evaluate_group_windows` 里算、该函数此时
    # 整体早退 ⇒ 放行 reason 落回 "allowed"，而 InMemory 在 check_and_record 里算、
    # 拿得到 "emotion_exempt"。**判定**（allowed 与否）两尺一致，**标签**不一致。
    # 本锁按"判定+算术必须同源"归一比较，绝不把错的标签写成期望值（那等于给缺陷背书）。
    def _normalized(trace: list[tuple[bool, str, int]]) -> list[tuple[bool, str, int]]:
        return [
            (allowed, "allowed" if reason == "emotion_exempt" else reason, retry)
            for allowed, reason, retry in trace
        ]

    assert _normalized(traces["InMemory"]) == _normalized(
        traces["SQLite"]
    ), f"两把尺漂了：{traces}"
    assert _normalized(traces["InMemory"]) == _normalized(expected), (
        f"两把尺一起错：{traces['InMemory']}"
    )
    # InMemory 侧的豁免标签照旧锁死（它是对的），SQLite 侧只锁判定。
    assert traces["InMemory"][5] == (True, "emotion_exempt", 0), traces["InMemory"][5]
    assert traces["SQLite"][5][0] is True, traces["SQLite"][5]


# ---------------------------------------------- ⑥ 参数为 0 ⇒ 整层惰性


def test_zero_vision_interval_is_inert_down_to_the_predicate(
    both, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_message: IncomingMessage) -> bool:
        raise AssertionError("参数为 0 时不许调用视觉谓词（惰性不彻底）")

    monkeypatch.setattr(rate_limit, "_message_is_visual", _boom)
    for name, limiter, clock in both(group_vision_min_interval_seconds=0):
        # 注意：本用例里 _visual/_plain 的前置自检会调用**门禁**谓词（未被替换），
        # 被替换的是限流器一侧的包装 ⇒ 自检照跑，惰性照验。
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        clock.advance(seconds=30)
        second = limiter.check_and_record(_visual(), "bot.chat")
        assert second.allowed is True, (
            f"{name}: 关掉参数却仍被图类门拦 → {second.reason}"
        )
    # 关掉时连"图类那一格"都不该存在（不建键 ⇒ 与本格落地前逐字节同形）。
    memory = InMemoryRateLimiter(
        _settings(group_vision_min_interval_seconds=0), clock=_Clock()
    )
    memory.check_and_record(_visual(), "bot.chat")
    assert not [
        key for key in memory._buckets if PACING_SCOPE_VISION_LAST in key
    ], "参数为 0 仍写了图类账本"


# ---------------------------------------- ⑦ 拒绝时一格不写（B-1 幽灵扣减）


def test_denied_message_does_not_move_the_vision_clock(both) -> None:
    """被拦下的那句不许把图类钟拨走：否则"拒绝也扣额度"会以另一种形式复活。"""
    for name, limiter, clock in both():
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is True, name
        clock.advance(seconds=30)
        assert limiter.check_and_record(_visual(), "bot.chat").allowed is False, name
        # 从**第一格**（@0）起算：125 秒该放行。若被拦那句偷偷记了一格（@30），
        # 125-30=95 < 120 ⇒ 这里会被误拦。
        clock.advance(seconds=95)
        after = limiter.check_and_record(_visual(), "bot.chat")
        assert after.allowed is True, f"{name}: 被拦的消息留下了幽灵账 → {after.reason}"


# ------------------------------------ ⑧ 判定复用门禁谓词，不留第二真身


def test_rate_limit_delegates_the_visual_call_to_the_gate_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """限流器必须现问门禁那枚单一真身；自己抄一份段类型判据＝本仓头号病。

    本例的消息构造**故意**不走 ``_visual`` 的前置自检：自检要调谓词，而这里正是
    要把谓词换成打毒桩，走了自检就成了测夹具。判定结果反而更硬——桩说"不含图"，
    图类门就必须整层消失。
    """
    calls: list[str] = []

    def _poisoned(_message: IncomingMessage) -> bool:
        calls.append("hit")
        return False

    monkeypatch.setattr(gate, "message_has_visual_content", _poisoned)
    clock = _Clock()
    limiter = InMemoryRateLimiter(_settings(), clock=clock)
    message = _message("看看这张", visual="photo")
    first = limiter.check_and_record(message, "bot.chat")
    assert calls, "限流器没问门禁的谓词（判定另有真身 ⇒ 第二副本）"
    assert first.allowed is True and first.reason == "allowed", first
    # 越过文字 20 秒但**留在**图类 120 秒内：桩说不含图 ⇒ 图类门必须整层不出现；
    # 若限流器读的是自己那份副本，段类型照样判"含图"，这一格就会被 120 秒拦下。
    clock.advance(seconds=25)
    second = limiter.check_and_record(message, "bot.chat")
    assert second.allowed is True, (
        f"打毒后图类门仍拦人 ⇒ 它读的不是这枚谓词：{second.reason}"
    )

    source = Path(rate_limit.__file__).read_text(encoding="utf-8")
    for copy_marker in ("_IMAGE_SEGMENT_TYPES", "_VIDEO_SEGMENT_TYPES", '"mface"'):
        assert copy_marker not in source, (
            f"rate_limit.py 里出现了段类型副本 {copy_marker}——段类型口径只准有一份"
        )


def test_ruled_defaults_are_pinned() -> None:
    """她裁的两个数字（文字 20 秒 / 图 120 秒）钉在缺省值上。"""
    settings = RateLimitSettings()
    assert settings.group_vision_min_interval_seconds == RULED_VISION_INTERVAL_SECONDS
    assert settings.group_pacing_min_interval_seconds == RULED_TEXT_INTERVAL_SECONDS
