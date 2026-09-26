"""S-W12 清扫节流可越缝 + 公开入口活性锁（PARKED-FOR-REVIEW **PX-9** 的收口）。

要锁的缺陷形态不是"这行写错了"，而是**有一整段代码在离线套件里从来没被执行过**：
``InMemoryRateLimiter._maybe_sweep`` 的节流判据是真实 ``time.monotonic()``，
而 ``_last_sweep`` 在**构造时**就置为当下 ⇒ 600 秒的阈在测试进程里根本跨不过去，
清扫体永不进树。2026-09-24 落地时该体内有一枚未定义名（``pacing``，应为 ``settings``），
**25 条节奏测试全绿**，而生产在"重启约 10 分钟后的第一条群消息"上抛 NameError。
ruff F821 与 mypy name-defined 当时都抓得到，测试抓不到 —— 静态门与活性门各缺一块。

本文件补的是**活性**那一块，与既有 ``test_rate_limit_pacing_coherence.py`` 的分工：
那把锁手拨 ``_last_sweep`` 再**直调私有方法** ``_maybe_sweep``，量的是"函数体本身能跑"；
本格量的是"**生产实际走的那条公开路径**（``check_and_record`` / SQLite 的检查链）
能不能跑到清扫体"。差别不是风格：将来任何人新增一条不经过清扫的公开入口，
直调锁照样绿，而生产照样在 600 秒后炸。

缝的选型（两案自选，本席取"注入单调钟"）：
- 被否的案乙′＝把节流改成吃 ``self.clock``（墙钟）。本仓有 NTP 授时
  （``runtime/timesync.py``：重启后 ~65s 起每 10 分钟校时），节流吃墙钟等于让
  一次向后的校时跳变把清扫无限推后（键集合无界增长）——为了可测性把生产语义改差。
- 采纳＝给**单调钟本身**开一枚构造参数 ``monotonic``，缺省 ``time.monotonic``
  ⇒ 不注入时与历史形态逐字节相同（``test_default_monotonic_source_is_time_monotonic``
  锁住这一点），而 **600 / 300 两枚业务值一字未动**
  （``test_sweep_and_cleanup_business_values_are_unchanged`` 锁住）。

纪律：全离线、注入时钟、SQLite 走 tmp_path、零网络、零磁盘注毒（注毒一律 ``monkeypatch``）。
"""

from __future__ import annotations

import builtins
import sqlite3
import time
import types
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
)

# 墙钟推进量：必须同时越过 idle_cap（3600×B/x = 3600×5/30 = 600 秒）与分钟窗，
# 这样"清扫真的执行过"才有可观测的指纹（A 组的令牌状态该被扔掉）。
WALL_ADVANCE_SECONDS = 700
SWEEP_INTERVAL = InMemoryRateLimiter._SWEEP_INTERVAL_SECONDS
SQLITE_CLEANUP_INTERVAL = SQLiteRateLimiter._CLEANUP_INTERVAL_SECONDS


class _Clock:
    """可拨的墙钟（aware UTC datetime），与生产缺省同形。"""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _Monotonic:
    """可拨的单调钟——本席开的那枚缝。"""

    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _settings(**overrides: Any) -> RateLimitSettings:
    base: dict[str, Any] = {
        # 三道通用窗抬到不会成为约束，只留节奏层这一道，免得判定被别的帽干扰。
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
        "group_pacing_tokens_per_hour": 30,
        "group_pacing_burst_capacity": 5,
        "group_pacing_max_per_minute": 3,
        "group_pacing_min_interval_seconds": 20,
    }
    base.update(overrides)
    return RateLimitSettings(**base)


def _group_message(group_id: str, text: str = "在吗") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"group_{group_id}",
        session_type=SessionType.GROUP,
        sender_id=f"u{group_id}",
        group_id=group_id,
        plain_text=text,
        raw_segments=[],
    )


def _memory_pair(**overrides: Any) -> tuple[InMemoryRateLimiter, _Clock, _Monotonic]:
    clock = _Clock()
    monotonic = _Monotonic()
    limiter = InMemoryRateLimiter(_settings(**overrides), clock=clock, monotonic=monotonic)
    return limiter, clock, monotonic


def _prime_group_a(limiter: InMemoryRateLimiter) -> set[str]:
    """给 A 组发一句 ⇒ 建起节奏桶；返回当时 ``_pacing_tokens`` 的键集合。"""
    assert limiter.check_and_record(_group_message("111"), "bot.chat").allowed is True
    keys = set(limiter._pacing_tokens)
    assert keys, "前置条件不成立：节奏层没建桶，后面所有断言都是空跑"
    return keys


# --------------------------------------------------------------- ① 跨阈后的公开入口


def test_first_group_message_past_sweep_threshold_is_allowed_and_sweep_ran() -> None:
    """**PX-9 的正锁**：越过节流阈后的第一条群消息，走公开入口，不抛异常且判定正常。

    生产形态就是"重启约 10 分钟后的那一条"。这里刻意用**另一个群**（B 组）来触发
    那一条：A 组遗留的过期令牌状态被清掉，才是"清扫体真跑了"的指纹——B 组自己的
    桶刚建，用"字典变空"当判据既不可能也测不到东西。
    """
    limiter, clock, monotonic = _memory_pair()
    a_keys = _prime_group_a(limiter)

    clock.advance(WALL_ADVANCE_SECONDS)  # A 组那格过期（idle_cap = 600 秒）
    monotonic.advance(SWEEP_INTERVAL + 1.0)  # 跨过节流阈

    decision = limiter.check_and_record(_group_message("222", "第二句"), "bot.chat")
    # 旧形态在这一行抛 NameError（未定义名 pacing），而 25 条节奏测试全绿。
    assert decision.allowed is True, decision
    assert set(limiter._pacing_tokens).isdisjoint(a_keys), (
        "清扫未执行：A 组过期的令牌状态仍在（键集合无界增长）"
    )
    assert set(limiter._pacing_tokens), "B 组该建新桶，否则本用例没经过节奏层"


def test_proactive_entry_past_threshold_also_reaches_sweep_without_raising() -> None:
    """第二个调用点：``_check_proactive`` 也调 ``_maybe_sweep``（生产共两处）。

    只锁 chat 那条的话，另一条公开路径依然无人质询。
    """
    limiter, clock, monotonic = _memory_pair()
    a_keys = _prime_group_a(limiter)
    clock.advance(WALL_ADVANCE_SECONDS)
    monotonic.advance(SWEEP_INTERVAL + 1.0)
    decision = limiter.check_and_record(_group_message("222"), "bot.chat", proactive=True)
    assert isinstance(decision.allowed, bool)  # 不抛异常即达标，判定值不作强断言
    assert set(limiter._pacing_tokens).isdisjoint(a_keys), "主动搭话这条路径没扫"


# ------------------------------------------------------------- ② 缝不是"恒清扫"


def test_sweep_throttle_still_gates_below_threshold_then_fires_past_it() -> None:
    """反向锁：阈**以下**清扫不得执行，否则①的两条用例是空跑。

    没有这一条，"把缝写成每次都清扫"也能让①全绿——那正是本仓最常见的假绿形状。
    """
    limiter, clock, monotonic = _memory_pair()
    a_keys = _prime_group_a(limiter)

    clock.advance(WALL_ADVANCE_SECONDS)
    monotonic.advance(SWEEP_INTERVAL - 1.0)  # 还差 1 秒
    assert limiter.check_and_record(_group_message("222"), "bot.chat").allowed is True
    assert a_keys <= set(limiter._pacing_tokens), "节流被旁路：还没跨阈就把 A 组的桶清了"

    monotonic.advance(2.0)  # 现在跨过了
    assert limiter.check_and_record(_group_message("333"), "bot.chat").allowed is True
    assert set(limiter._pacing_tokens).isdisjoint(a_keys), "跨阈后仍不清扫"


def test_default_monotonic_source_is_time_monotonic() -> None:
    """不注入 ⇒ 生产形态逐字节不变（缺省就是 ``time.monotonic``，不是假钟）。"""
    limiter = InMemoryRateLimiter(_settings())
    assert limiter._monotonic is time.monotonic
    assert abs(limiter._last_sweep - time.monotonic()) < 5.0
    # 真实单调钟下，构造后立刻判定绝不跨阈（今天的形态）。
    assert limiter.check_and_record(_group_message("444"), "bot.chat").allowed is True
    assert limiter._pacing_tokens, "不该有任何清扫发生"


def test_sweep_and_cleanup_business_values_are_unchanged() -> None:
    """两枚业务间隔值不得为了"方便测试"被改小（简报明令）。"""
    assert SWEEP_INTERVAL == 600.0, SWEEP_INTERVAL
    assert SQLITE_CLEANUP_INTERVAL == 300.0, SQLITE_CLEANUP_INTERVAL


# ----------------------------------------------------------- ③ SQLite 那把尺同缝


def test_sqlite_full_table_cleanup_runs_and_prunes_via_public_entry(
    tmp_path: Path,
) -> None:
    """SQLite 侧的同类盲区：``_cleanup_expired`` 也被单调钟节流（300 秒）。

    它今天靠 ``_last_cleanup = 0.0`` "首访即清"侥幸可达 —— 那是**机器开机时长**
    的函数（uptime < 300s 时首访不清）。本用例注入假单调钟，把两向都钉成确定量，
    顺带证明清理体本身不抛异常（与 InMemory 同一段历史教训）。
    """
    clock = _Clock()
    monotonic = _Monotonic(start=1_000.0)
    db_path = tmp_path / "sweep_throttle_sqlite.db"
    limiter = SQLiteRateLimiter(
        db_path,
        # 关掉间隔门与分钟帽，只留令牌桶：同一个群连发两句否则会被 20 秒最小间隔
        # 拦下，那不是本格要量的东西（本用例的断言只反映"全表清理跑没跑"）。
        _settings(group_pacing_min_interval_seconds=0, group_pacing_max_per_minute=0),
        clock=clock,
        monotonic=monotonic,
    )
    assert limiter.check_and_record(_group_message("555"), "bot.chat").allowed is True

    def _insert_stale(marker: str, age_seconds: float) -> None:
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO rate_limit_events (bucket_key, created_at) VALUES (?, ?)",
                (marker, clock().timestamp() - age_seconds),
            )

    def _count(marker: str) -> int:
        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM rate_limit_events WHERE bucket_key = ?",
                (marker,),
            ).fetchone()
        return int(row[0])

    # ① 跨阈 ⇒ 过期行真被删，且不抛异常。
    _insert_stale("stale-a", SQLITE_CLEANUP_INTERVAL + 10_000.0)
    monotonic.advance(SQLITE_CLEANUP_INTERVAL + 1.0)
    assert limiter.check_and_record(_group_message("555"), "bot.chat").allowed is True
    assert _count("stale-a") == 0, "清理体未执行：过期事件行仍在（全表越来越慢）"

    # ② 阈以下 ⇒ 不得清理（证明 ① 不是因为"恒清理"而绿）。
    _insert_stale("stale-b", SQLITE_CLEANUP_INTERVAL + 10_000.0)
    assert limiter.check_and_record(_group_message("555"), "bot.chat").allowed is True
    assert _count("stale-b") == 1, "节流被旁路：还没跨阈就删了行"


# ------------------------------------------------------------------- ④ 注毒自证

# 逐字复刻 2026-09-24 落地时的那一体：**裸的未定义名** ``pacing``。
_POISON_SOURCE = """def sweep(self, now):
    if self._monotonic() - self._last_sweep < self._SWEEP_INTERVAL_SECONDS:
        return
    self._last_sweep = self._monotonic()
    idle_cap_seconds = (
        3600.0 * max(1, pacing.group_pacing_burst_capacity)
        / max(1, pacing.group_pacing_tokens_per_hour)
    )
    if idle_cap_seconds > 0:
        for key in list(self._pacing_tokens.keys()):
            del self._pacing_tokens[key]
"""


def _historical_sweep_poison() -> Callable[[Any, Any], None]:
    """造出当年那枚真 NameError，但**不在本测试件的源码里留下可扫到的裸未定义名**。

    为什么绕这一层：把 ``pacing`` 直接写进源码，ruff 当场判 F821 —— 实测两发写法都
    拦不住（裸写一发、闭包+``del`` 一发，后者运行时确实是 NameError 但仍被记 F821×2）。
    那意味着**本格自己会变成下一枚静态门红**："测试件里有未定义名"和"生产件里有
    未定义名"在静态门眼里是同一种形状。``exec`` / ``eval`` 被本仓 ruff 的 S102 挡着，
    ``# noqa`` 属"变绿手段六禁"在册禁法 ⇒ 三条出路里只剩 ``compile`` + ``FunctionType``：
    它不执行任何模块级代码，只把编译好的函数码包成可调用对象，而**抛点、异常类型、
    消息文本三者与当年完全一致**（``NameError: name 'pacing' is not defined``），
    一分钱不打折。
    """
    module_code = compile(_POISON_SOURCE, "<poison:PX-9-逐字复刻>", "exec")
    sweep_code = next(
        item for item in module_code.co_consts if isinstance(item, types.CodeType)
    )
    # 全局表只给 builtins：``pacing`` 这枚名字**故意不在**里面。
    poison: Callable[[Any, Any], None] = types.FunctionType(
        sweep_code, {"__builtins__": builtins}
    )
    return poison


def test_poison_missing_name_in_sweep_body_breaks_the_public_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """杀伤力证明：把清扫体里的名字换回当年的 ``pacing`` ⇒ 公开入口当场抛。

    这一条同时是**可达性**的证据：只有"公开路径真的执行了清扫体"，毒才咬得动。
    当年 25 条绿测试看不见这枚雷，缺的正是这一条。
    """
    monkeypatch.setattr(
        InMemoryRateLimiter, "_maybe_sweep", _historical_sweep_poison()
    )
    limiter, clock, monotonic = _memory_pair()
    _prime_group_a(limiter)
    clock.advance(WALL_ADVANCE_SECONDS)
    monotonic.advance(SWEEP_INTERVAL + 1.0)
    with pytest.raises(NameError, match="name 'pacing' is not defined"):
        limiter.check_and_record(_group_message("222", "第二句"), "bot.chat")


def test_poison_noop_sweep_keeps_expired_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第二发毒：清扫换成空转 ⇒ ①里"真清了"那条断言必红（不是只测不抛）。"""

    def _noop(self: Any, now: Any) -> None:
        return None

    monkeypatch.setattr(InMemoryRateLimiter, "_maybe_sweep", _noop)
    limiter, clock, monotonic = _memory_pair()
    a_keys = _prime_group_a(limiter)
    clock.advance(WALL_ADVANCE_SECONDS)
    monotonic.advance(SWEEP_INTERVAL + 1.0)
    limiter.check_and_record(_group_message("222", "第二句"), "bot.chat")
    assert not set(limiter._pacing_tokens).isdisjoint(a_keys), (
        "毒没咬住：空转的清扫也被判成执行过了"
    )


def test_poison_raised_threshold_disables_sweep_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第三发毒：把节流阈改大（缝被绕开）⇒ 跨阈后仍不清扫。

    证明本件的判据确实吃这枚值，而不是吃"每次调用都扫"的巧合。
    """
    monkeypatch.setattr(InMemoryRateLimiter, "_SWEEP_INTERVAL_SECONDS", 10**9)
    limiter, clock, monotonic = _memory_pair()
    a_keys = _prime_group_a(limiter)
    clock.advance(WALL_ADVANCE_SECONDS)
    monotonic.advance(SWEEP_INTERVAL + 1.0)
    limiter.check_and_record(_group_message("222", "第二句"), "bot.chat")
    assert a_keys <= set(limiter._pacing_tokens)


def test_poison_sqlite_cleanup_noop_keeps_stale_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """第四发毒（SQLite 那把尺）：清理换成空转 ⇒ ③里"真删了"那条断言必红。"""

    def _noop(self: Any, connection: Any, now_epoch: float) -> None:
        return None

    monkeypatch.setattr(SQLiteRateLimiter, "_cleanup_expired", _noop)
    clock = _Clock()
    monotonic = _Monotonic(start=1_000.0)
    db_path = tmp_path / "sweep_throttle_poison.db"
    limiter = SQLiteRateLimiter(
        db_path,
        _settings(group_pacing_min_interval_seconds=0, group_pacing_max_per_minute=0),
        clock=clock,
        monotonic=monotonic,
    )
    limiter.check_and_record(_group_message("555"), "bot.chat")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO rate_limit_events (bucket_key, created_at) VALUES (?, ?)",
            ("stale-poison", clock().timestamp() - 10_000.0),
        )
    monotonic.advance(SQLITE_CLEANUP_INTERVAL + 1.0)
    limiter.check_and_record(_group_message("555"), "bot.chat")
    with sqlite3.connect(db_path) as connection:
        left = connection.execute(
            "SELECT COUNT(*) FROM rate_limit_events WHERE bucket_key = ?",
            ("stale-poison",),
        ).fetchone()[0]
    assert left == 1, "毒没咬住：空转的清理也被判成执行过了"
