"""第 9 项「表情回应看情况静默」——静默码受控词表观测锁（S-IMPL-ITEM9）。

口径：每个静默决策点必须落一行可 grep 的观测记录（受控原因码，参照
``skip_reserved_name_*`` 审计码先例），「为什么这条消息没得到表情」不许靠猜。
本文件三把锁：

1. 名册双向锁：发射的 reason 码全在 ``REACTION_SKIP_REASONS`` 册内；
   册内每枚码都有真实发射点（在册必执法——没发射点的码不许挂账）。
2. 逐路行为锁：引擎前置六路 + 五层门拒因各触发对应码（caplog 实测）。
3. 门语义锁：``allow`` 是 ``verdict`` 的纯布尔壳，判定与 commit 语义逐字节不变。

静默判据本体（裸表情/看情况规则）在 message_merge.py，其锁在
test_message_merge_9.py——本文件不重做第二真身，只管观测面。
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.meme.reactions import engine
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    REACTION_SKIP_REASONS,
    ProactiveGate,
    maybe_react_on_message,
)

ENGINE_SRC = Path(engine.__file__).read_text(encoding="utf-8")


class _Cfg:
    bot_reactions_enabled = True
    bot_reactions_probability = 1.0
    bot_reactions_cooldown_seconds = 0
    bot_reactions_max_per_hour = 20


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))


def _group_kwargs(**over):
    kw = {
        "session_key": "group_1_1",
        "user_message_id": 9001,
        "text": "谢谢你呀，帮大忙了",
        "config": _Cfg(),
        "trigger": "emotion_signal",
        "bot_related": True,
        "gate": ProactiveGate(),
    }
    kw.update(over)
    return kw


def _skip_reason(caplog) -> str | None:
    for record in caplog.records:
        msg = record.getMessage()
        if msg.startswith("reaction skip: reason="):
            token = next(t for t in msg.split() if t.startswith("reason="))
            return token[len("reason="):]
    return None


# ------------------------------------------------------------- 名册双向锁


def _emitted_reason_literals() -> set[str]:
    """现算引擎源码里所有静默发射点的 reason 字面量。"""
    literals = set(re.findall(r'_skip\("([a-z_]+)"\)', ENGINE_SRC))
    # 门内拒因：return False, "gate_..."
    literals |= set(re.findall(r'return False, "(gate_[a-z_]+)"', ENGINE_SRC))
    # 兜底哨兵：_skip(gate_reason or "gate_unknown")
    literals |= set(re.findall(r'_skip\([a-z_]+ or "(gate_[a-z_]+)"\)', ENGINE_SRC))
    return literals


def test_every_emitted_reason_is_in_roster():
    emitted = _emitted_reason_literals()
    assert emitted, "引擎里一枚静默发射点都没抓到 ⇒ 锁本身失效"
    stray = emitted - set(REACTION_SKIP_REASONS)
    assert not stray, f"发射了未入册原因码 {stray} ⇒ 受控词表被绕开"


def test_every_roster_code_has_emit_site():
    """在册必执法：没长发射点的码不许占名册。"""
    emitted = _emitted_reason_literals()
    unenforced = set(REACTION_SKIP_REASONS) - emitted
    assert not unenforced, f"名册码无发射点（在册未执法）: {unenforced}"


def test_skip_log_is_single_greppable_choke():
    """所有前置/门拒因都经 _skip 单喉发射——观测面格式只此一处。"""
    assert ENGINE_SRC.count('"reaction skip: reason=%s') == 1


# --------------------------------------------------------------- 逐路行为锁


def test_skip_disabled_emits_code(caplog):
    caplog.set_level(logging.INFO)
    cfg = SimpleNamespace(bot_reactions_enabled=False)
    assert asyncio.run(maybe_react_on_message(_FakeBot(), **_group_kwargs(config=cfg))) is False
    assert _skip_reason(caplog) == "disabled"


def test_skip_no_message_id(caplog):
    caplog.set_level(logging.INFO)
    got = asyncio.run(
        maybe_react_on_message(_FakeBot(), **_group_kwargs(user_message_id=""))
    )
    assert got is False
    assert _skip_reason(caplog) == "no_message_id"


def test_skip_private_session(caplog):
    caplog.set_level(logging.INFO)
    got = asyncio.run(
        maybe_react_on_message(_FakeBot(), **_group_kwargs(session_key="88888"))
    )
    assert got is False
    assert _skip_reason(caplog) == "private_session"


def test_skip_third_party_chat(caplog):
    caplog.set_level(logging.INFO)
    got = asyncio.run(
        maybe_react_on_message(_FakeBot(), **_group_kwargs(bot_related=None))
    )
    assert got is False
    assert _skip_reason(caplog) == "third_party_chat"


def test_skip_no_emotion_signal(caplog):
    caplog.set_level(logging.INFO)
    got = asyncio.run(
        maybe_react_on_message(
            _FakeBot(), **_group_kwargs(text="今天天气不错", bot_related=True)
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "no_emotion_signal"


def test_skip_sad_message(caplog):
    caplog.set_level(logging.INFO)
    got = asyncio.run(
        maybe_react_on_message(
            _FakeBot(), **_group_kwargs(text="我今天好难过", trigger="after_reply")
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "sad_message"


def test_skip_gate_probability_then_already_rolled(caplog):
    """概率未中→gate_probability；同消息换触发再进来→gate_already_rolled。"""
    caplog.set_level(logging.INFO)
    cfg = SimpleNamespace(
        bot_reactions_enabled=True,
        bot_reactions_probability=0.0,
        bot_reactions_cooldown_seconds=0,
        bot_reactions_max_per_hour=20,
    )
    shared_gate = ProactiveGate()
    got = asyncio.run(
        maybe_react_on_message(
            _FakeBot(), **_group_kwargs(config=cfg, gate=shared_gate)
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "gate_probability"
    caplog.clear()
    got = asyncio.run(
        maybe_react_on_message(
            _FakeBot(),
            **_group_kwargs(config=cfg, gate=shared_gate, trigger="after_reply",
                            text="随便什么"),
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "gate_already_rolled"


def test_skip_gate_cooldown(caplog):
    caplog.set_level(logging.INFO)
    cfg = SimpleNamespace(
        bot_reactions_enabled=True,
        bot_reactions_probability=1.0,
        bot_reactions_cooldown_seconds=30,
        bot_reactions_max_per_hour=20,
    )
    gate = ProactiveGate(clock=lambda: 1000.0)
    bot = _FakeBot()
    assert asyncio.run(
        maybe_react_on_message(bot, **_group_kwargs(config=cfg, gate=gate))
    ) is True
    caplog.clear()
    got = asyncio.run(
        maybe_react_on_message(
            bot, **_group_kwargs(config=cfg, gate=gate, user_message_id=9002)
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "gate_cooldown"


def test_skip_gate_hourly_cap(caplog):
    caplog.set_level(logging.INFO)
    cfg = SimpleNamespace(
        bot_reactions_enabled=True,
        bot_reactions_probability=1.0,
        bot_reactions_cooldown_seconds=0,
        bot_reactions_max_per_hour=1,
    )
    gate = ProactiveGate()
    bot = _FakeBot()
    assert asyncio.run(
        maybe_react_on_message(bot, **_group_kwargs(config=cfg, gate=gate))
    ) is True
    caplog.clear()
    got = asyncio.run(
        maybe_react_on_message(
            bot, **_group_kwargs(config=cfg, gate=gate, user_message_id=9003)
        )
    )
    assert got is False
    assert _skip_reason(caplog) == "gate_hourly_cap"


def test_skip_gate_already_reacted(caplog):
    caplog.set_level(logging.INFO)
    bot = _FakeBot()
    gate = ProactiveGate()
    assert asyncio.run(maybe_react_on_message(bot, **_group_kwargs(gate=gate))) is True
    caplog.clear()
    got = asyncio.run(maybe_react_on_message(bot, **_group_kwargs(gate=gate)))
    assert got is False
    assert _skip_reason(caplog) == "gate_already_reacted"


def test_success_path_logs_no_skip(caplog):
    caplog.set_level(logging.INFO)
    bot = _FakeBot()
    assert asyncio.run(maybe_react_on_message(bot, **_group_kwargs(gate=ProactiveGate()))) is True
    assert _skip_reason(caplog) is None
    assert len(bot.calls) == 1


# ----------------------------------------------------------------- 门语义锁


_GATE_KW = {
    "enabled": True, "probability": 1.0, "cooldown_seconds": 0.0, "max_per_hour": 100
}


def test_allow_is_pure_bool_shell_of_verdict():
    """allow 与 verdict 同一真身：两台同初值门走同序列，逐调用布尔完全一致。"""
    gate_a = ProactiveGate()
    gate_b = ProactiveGate()
    seq = [
        ("s", "m1"), ("s", "m1"), ("s", "m2"), ("", "m3"), ("s4", ""),
    ]
    for sk, mk in seq:
        allowed, reason = gate_a.verdict(sk, mk, **_GATE_KW)
        assert gate_b.allow(sk, mk, **_GATE_KW) is allowed
        assert allowed == (reason == "")
        if not allowed:
            assert reason in REACTION_SKIP_REASONS


def test_verdict_gate_disabled_and_unknown_paths_in_roster():
    gate = ProactiveGate()
    allowed, reason = gate.verdict(
        "s", "m",
        enabled=False, probability=1.0, cooldown_seconds=0.0, max_per_hour=100,
    )
    assert (allowed, reason) == (False, "gate_disabled")
    # 全拒因码 ∈ 名册（含 invalid_key）
    _, r2 = gate.verdict("", "m", **_GATE_KW)
    assert r2 == "gate_invalid_key"
