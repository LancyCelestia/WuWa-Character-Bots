"""连发点名消息不得被限流静默吞掉——**活性面**的回归锁。

`tests/test_throttle_redrive_and_adaptive_ack.py` 锁的是「该不该补」的三道门；
本件锁的是「补回到底补不补得回来」。两条真实吞消息的路径都在那里被演出来：

A. 最小间隔报的解禁秒数偏短（`int()` 向下截断）⇒ 按报的值睡完仍 `< 间隔` ⇒
   当场再被拦一次，而这条消息的补回额度（缺省 1 次）恰好用光 ⇒ 静默丢弃。
B. 同人连发的多条补回约在同一刻醒来 ⇒ 头一条通过后把冷却钟重新拨走，
   其余在同一瞬间全部再被拦 ⇒ 同样的「一次额度」集体陪葬。

判据来自用户 2026-09-25 第 2 项裁定：连发 5 条 @bot 的消息，每一条都要得到回复
（可以延后，不可以丢弃）。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
      -m pytest tests/test_policy_queue_not_drop.py -q -p no:cacheprovider \
      --basetemp=<仓库外私有目录>
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    RedriveSettings,
    SQLiteRateLimiter,
    build_rate_limiter,
    redrive_wait_seconds,
)

_INTERVAL = 45
_SENDER = "u1"


class _Clock:
    """注入给限流器的假墙钟（与生产 `datetime.now(utc)` 同型）。"""

    def __init__(self) -> None:
        self.origin = datetime(2026, 9, 26, 9, 0, 0, tzinfo=timezone.utc)
        self.now = self.origin

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def set_to(self, seconds: float) -> None:
        """把假钟指到「开工起算第 seconds 秒」——补回模拟按绝对时刻走。"""
        self.now = self.origin + timedelta(seconds=seconds)

    @property
    def epoch(self) -> float:
        return self.now.timestamp()


def _message(text: str, *, redrive_count: int = 0, sender_id: str = _SENDER) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=f"group_10_{sender_id}",
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id="10",
        plain_text=text,
        mentions_bot=True,
        redrive_count=redrive_count,
    )


def _caps() -> dict:
    """把三道滑动窗帽抬到不参与判定，聚焦「强制冷却」这一道（同 test_policy_sender_interval）。"""
    return {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
        "chat_sender_min_interval_seconds": _INTERVAL,
    }


def _memory_limiter(clock: _Clock) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(RateLimitSettings(**_caps()), clock=clock)  # type: ignore[arg-type]


def _sqlite_limiter(clock: _Clock, tmp_path: Path) -> SQLiteRateLimiter:
    return SQLiteRateLimiter(
        tmp_path / "rate_limit_queue.db",
        RateLimitSettings(**_caps()),  # type: ignore[arg-type]
        clock=clock,
    )


@pytest.fixture(autouse=True)
def _fresh_redrive_ledger():
    """补回排队账本住模块级（同折句器 `_SHARED` 的先例），用例之间必须各起一本。"""
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.policy import redrive_ledger
    except ImportError:  # RED 阶段：账本件尚未落地，没有可复位的对象
        yield
        return
    redrive_ledger.reset_redrive_ledger()
    yield
    redrive_ledger.reset_redrive_ledger()


# ---------------------------------------------------------------------------
# A. 报出去的秒数必须真的能把门打开（两把尺同一算式）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("elapsed", [0.0, 0.4, 10.9, 30.5, 44.6])
def test_reported_wait_is_never_shorter_than_the_true_remaining(
    kind: str, elapsed: float, tmp_path: Path
) -> None:
    """`int(45 - elapsed)` 向下截断 ⇒ 报的值最多比解禁点短 1 秒 ⇒ 补回必再撞。"""
    clock = _Clock()
    limiter = _memory_limiter(clock) if kind == "memory" else _sqlite_limiter(clock, tmp_path)
    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    clock.advance(elapsed)

    denied = limiter.check_and_record(_message("第二句"), "bot.chat", interactive=True)
    assert denied.allowed is False
    assert denied.reason == "sender_min_interval"
    assert denied.retry_after_seconds >= math.ceil(_INTERVAL - elapsed), (
        f"elapsed={elapsed} 报 {denied.retry_after_seconds} 秒，等完仍不到解禁点"
    )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("elapsed", [0.0, 0.4, 10.9, 30.5, 44.6])
def test_waiting_the_reported_seconds_actually_clears_the_gate(
    kind: str, elapsed: float, tmp_path: Path
) -> None:
    """这就是"消息被吞"的最小可复现单元：pipeline 只睡 `retry_after_seconds`
    （`pipeline.py:1316→1346`），睡完再判一次；判还拦 ⇒ `max_attempts=1` 已耗尽 ⇒ 丢。
    """
    clock = _Clock()
    limiter = _memory_limiter(clock) if kind == "memory" else _sqlite_limiter(clock, tmp_path)
    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    clock.advance(elapsed)
    denied = limiter.check_and_record(_message("第二句"), "bot.chat", interactive=True)
    assert denied.allowed is False

    clock.advance(float(denied.retry_after_seconds))
    # 补回那一轮带的是 redrive_count=1（`pipeline.py:1320-1322`），额度只有 1 次。
    redriven = limiter.check_and_record(
        _message("第二句", redrive_count=1), "bot.chat", interactive=True
    )
    assert redriven.allowed is True, (
        f"按报的 {denied.retry_after_seconds} 秒等完仍被拦 ⇒ 唯一一次补回当场作废（静默丢）"
    )


# ---------------------------------------------------------------------------
# B. 连发的补回不得约在同一刻醒来互撞
# ---------------------------------------------------------------------------


def _drain_burst(
    limiter,
    clock: _Clock,
    redrive: RedriveSettings,
    texts: list[str],
    *,
    gap: float = 0.4,
    horizon: float = 3_000.0,
) -> tuple[list[tuple[float, str]], list[tuple[float, str, str]]]:
    """按 pipeline 的补回语义在假钟上把一批连发演到底。

    与生产同形的三件事：群点名传 ``interactive=True``（``pipeline.py:812-825``）、
    拦下后用 ``redrive_wait_seconds`` 决定等多久（``pipeline.py:1316``）、
    重投时 ``redrive_count`` +1（``pipeline.py:1320-1322``）。
    刻意不把 pipeline 拉进来：这里要锁的是策略层的排队算术，不是事件循环。
    """
    pending: list[tuple[float, IncomingMessage]] = [
        (index * gap, _message(text)) for index, text in enumerate(texts)
    ]
    answered: list[tuple[float, str]] = []
    dropped: list[tuple[float, str, str]] = []
    steps = 0
    while pending:
        steps += 1
        assert steps <= 40, "补回在假钟上打转（不该出现重放循环）"
        pending.sort(key=lambda item: item[0])
        fire_at, message = pending.pop(0)
        clock.set_to(fire_at)  # type: ignore[attr-defined]
        decision = limiter.check_and_record(message, "bot.chat", interactive=True)
        if decision.allowed:
            answered.append((fire_at, message.plain_text))
            continue
        wait = redrive_wait_seconds(redrive, message, "bot.chat", decision)
        if wait is None or fire_at + wait > horizon:
            dropped.append((fire_at, message.plain_text, decision.reason))
            continue
        pending.append(
            (
                fire_at + wait,
                message.model_copy(
                    update={"redrive_count": int(message.redrive_count or 0) + 1}
                ),
            )
        )
    return answered, dropped


def test_five_burst_group_mentions_are_each_scheduled_into_their_own_slot() -> None:
    """连发 5 条、一条都不许丢：等位必须彼此隔开至少一个最小间隔。

    `max_wait_seconds` 这里给到 600 是为了把「互撞」与「上限」两件事分开锁
    （上限容不容得下整轮属另一条用例，见 test_default_max_wait_now_answers_the_whole_burst）。
    """
    clock = _Clock()
    limiter = _memory_limiter(clock)
    answered, dropped = _drain_burst(
        limiter,
        clock,
        RedriveSettings(max_wait_seconds=600.0, max_attempts=1),
        ["第一句", "第二句", "第三句", "第四句", "第五句"],
    )
    assert dropped == [], f"仍被丢弃：{dropped}"
    assert len(answered) == 5, f"只回了 {len(answered)} 条：{answered}"
    times = [at for at, _ in answered]
    assert times == sorted(times)
    for earlier, later in pairwise(times):
        assert later - earlier >= _INTERVAL - 1e-6, "两条回复挤在同一间隔内＝R3 语义被排挤掉"


def test_a_lone_blocked_message_is_not_pushed_out_by_the_queue() -> None:
    """缺省保守：同人这一轮只有一条要补时，报的必须还是解禁点本身，不因排队而变长。"""
    clock = _Clock()
    limiter = _memory_limiter(clock)
    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    clock.advance(10.0)
    denied = limiter.check_and_record(_message("第二句"), "bot.chat", interactive=True)
    assert denied.allowed is False
    wait = redrive_wait_seconds(RedriveSettings(), _message("第二句"), "bot.chat", denied)
    assert wait == float(math.ceil(_INTERVAL - 10.0))


def test_stale_slot_never_inflates_a_later_question() -> None:
    """补回位一旦过期就不该继续推后面的人：幽灵槽会让新问也等超上限而被丢。"""
    clock = _Clock()
    limiter = _memory_limiter(clock)
    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    clock.advance(0.4)
    first = limiter.check_and_record(_message("第二句"), "bot.chat", interactive=True)
    assert first.allowed is False
    assert redrive_wait_seconds(
        RedriveSettings(max_wait_seconds=600.0), _message("第二句"), "bot.chat", first
    ) == 45.0  # 回位排在 t=45

    # 第二句补回成功（把冷却钟拨到 45），此后已过 45 秒——排队账本必须已清空。
    clock.advance(44.6)
    assert limiter.check_and_record(
        _message("第二句", redrive_count=1), "bot.chat", interactive=True
    ).allowed
    clock.advance(_INTERVAL + 0.2)
    denied = limiter.check_and_record(_message("第三句"), "bot.chat", interactive=True)
    assert denied.allowed is False
    wait = redrive_wait_seconds(
        RedriveSettings(max_wait_seconds=600.0), _message("第三句"), "bot.chat", denied
    )
    assert wait == float(denied.retry_after_seconds), f"被过期幽灵槽推出去了：{wait}"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_two_siblings_are_spaced_apart_not_scheduled_together(
    kind: str, tmp_path: Path
) -> None:
    """同轮两条待补：第二条的回位必须至少隔一个最小间隔，否则它必死。"""
    clock = _Clock()
    limiter = _memory_limiter(clock) if kind == "memory" else _sqlite_limiter(clock, tmp_path)
    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    waits: list[float] = []
    for index, text in enumerate(("第二句", "第三句"), start=1):
        clock.advance(0.2 * index)
        denied = limiter.check_and_record(_message(text), "bot.chat", interactive=True)
        assert denied.allowed is False
        wait = redrive_wait_seconds(
            RedriveSettings(max_wait_seconds=600.0), _message(text), "bot.chat", denied
        )
        assert wait is not None
        waits.append(wait)
    assert waits[1] - waits[0] >= _INTERVAL - 1e-6, f"两条挤在同一刻：{waits}"


def test_default_max_wait_now_answers_the_whole_burst() -> None:
    """生产缺省 `RedriveSettings()`（max_wait 180 = 4×间隔缺省 45）必须容下连发 5 条。

    这枚 180 是 2026-09-25 补上的：旧缺省 90 秒只容 2 个回位，排队账本修好互撞
    之后第 3 条起仍被上限丢——「可以延后，不可以丢弃」（她第 2 项裁定）要求
    整轮排得下。本用例同时是新的 tripwire：谁把
    `config.py` 的 `bot_chat_rate_limit_redrive_max_wait_seconds` 缺省降回
    <4×间隔、或把间隔缺省抬大写爆 180 的账，这里必红，届时按新缺省改期望值
    ——别让它无声地把"第三条起仍被丢"读成"已经全修好了"。
    """
    clock = _Clock()
    limiter = _memory_limiter(clock)
    answered, dropped = _drain_burst(
        limiter,
        clock,
        RedriveSettings(),  # 生产缺省：max_wait 180 / attempts 1
        ["第一句", "第二句", "第三句", "第四句", "第五句"],
    )
    assert dropped == [], f"缺省上限下仍被丢弃：{dropped}"
    assert len(answered) == 5, f"缺省上限下实际回了 {len(answered)} 条：{answered}"


# ---------------------------------------------------------------------------
# C. SQLite 那把尺必须也能热改（AGENTS 台账 #3 的限流面）
# ---------------------------------------------------------------------------


class _DbConfig:
    """带 `bot_rate_limit_db_path` 的 Config 替身：走 SQLite 那一支装配口。"""

    def __init__(self, db_path: str) -> None:
        self.bot_rate_limit_db_path = db_path
        for key, value in _caps().items():
            setattr(self, f"bot_rate_limit_{key}", value)
        self.bot_rate_limit_group_max_per_hour = 0
        self.bot_rate_limit_group_max_per_minute = 0
        self.bot_rate_limit_emotion_exempt = True
        self.bot_rate_limit_bypass_roles = ["admin"]
        self.bot_rate_limit_target_min_interval_seconds = 0
        self.bot_group_proactive_max_replies_per_hour = 6
        self.bot_group_proactive_cooldown_seconds = 90


def test_sqlite_limiter_reads_settings_hot_from_the_provider(tmp_path: Path) -> None:
    """装配口旧代码把 callable 当场烘成静态快照交给 SQLite ⇒ `/bot runtime set`
    改的冷却窗口在重启前到不了它。这里锁"每轮现读"。

    （2026-09-26 S-POLICY-QND 夹具补针：本用例旧写法只给 provider、不给假钟，
    而装配口当时不转发 clock ⇒ limiter 吃真实墙钟、假钟的 6 秒从未到达被测面，
    无论实现怎么写都恒红（坏夹具）。补 clock 后语义不变且仍可注毒：把
    build_rate_limiter 还原成"烘快照"，即便假钟在场第三句也照样按旧 45 秒拦、
    本用例必红——杀伤力实录见日志。）
    """
    clock = _Clock()
    current = _INTERVAL
    limiter = build_rate_limiter(
        _DbConfig(str(tmp_path / "hot.db")),
        settings_provider=lambda: RateLimitSettings(
            **{**_caps(), "chat_sender_min_interval_seconds": current}
        ),  # type: ignore[arg-type]
        clock=clock,
    )
    assert isinstance(limiter, SQLiteRateLimiter)

    assert limiter.check_and_record(_message("第一句"), "bot.chat", interactive=True).allowed
    clock.advance(3.0)
    assert limiter.check_and_record(_message("第二句"), "bot.chat", interactive=True).allowed is False

    current = 2  # 管理员把冷却窗口调小（热改）
    clock.advance(3.0)
    hot = limiter.check_and_record(_message("第三句"), "bot.chat", interactive=True)
    assert hot.allowed is True, "热改的冷却窗口没到 SQLite 限流器：仍按旧的 45 秒拦人"


# ---------------------------------------------------------------------------
# D. 同源锁：两把尺不得各留一份截断算式
# ---------------------------------------------------------------------------


def test_interval_arithmetic_has_a_single_truth_source() -> None:
    """`int(间隔 - elapsed)` 这种向下截断的写法一次都不许留下，两把尺共读同一算式。"""
    from pathlib import Path as _Path

    from plugins.bot_unified_runtime.domains.chat_reply.policy import rate_limit

    source = _Path(rate_limit.__file__).read_text(encoding="utf-8")
    assert "int(self.settings.chat_sender_min_interval_seconds -" not in source
    assert "int(\n                            self.settings.chat_sender_min_interval_seconds -" not in source
    assert source.count("interval_wait_seconds(") >= 2, "两把尺至少共读同一枚间隔算式"
