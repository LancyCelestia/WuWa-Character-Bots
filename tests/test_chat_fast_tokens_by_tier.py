"""fast 档 token 压顶按档放宽（聊天体验波 2026-10-02）。

fast 模式的输出顶（``BOT_CHAT_FAST_MAX_TOKENS``）是把双刃剑：救首字延迟，
但把「详尽档」也一并砍到快顶，题型的长度分档就空转了。这里锁：

- 生效回复档为 detail（timely_retrieval/knowledge_qa/narrative 在 auto 列都进
  详尽）时，fast 腿**不**压快顶、保留常规顶（``BOT_CHAT_MAX_TOKENS`` 那条链
  已算好的值）；
- standard/concise 档保持快顶原样。

判据共读 ``resolve_reply_length_tier`` 一处真身（与提示词渲染那一条腿同源）。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    StaticLLMProvider,
)


def _capability(
    monkeypatch: pytest.MonkeyPatch,
    captured: list,
    *,
    fast_max_tokens: int = 1200,
    max_tokens: int = 65538,
) -> Callable:
    def result(**kwargs: object) -> CapabilityResult:
        captured.append(kwargs)
        message = kwargs["message"]
        return CapabilityResult(
            request_id=getattr(message, "request_id", ""), kind="text", body="ok"
        )

    monkeypatch.setattr(chat, "build_chat_result", result)
    return chat.build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(),
        reply_detail="auto",
        fast_mode=True,
        fast_max_tokens=fast_max_tokens,
        max_tokens=max_tokens,
    )


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="b",
        session_id="private_u",
        sender_id="u",
        session_type=SessionType.PRIVATE,
        plain_text=text,
        mentions_bot=True,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=12000,
        decision_reason="test",
    )


def test_detail_tier_turn_keeps_the_normal_token_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 档的知识问答 ⇒ 生效档 detail ⇒ fast 腿不压 1200，保留常规顶。"""
    captured: list = []
    capability = _capability(monkeypatch, captured)
    message = _message("守岸人与黑海岸是什么关系")
    capability(message, _decision(message))
    assert captured, "能力没有走到生成交"
    assert captured[0]["max_tokens"] == 65538


def test_standard_tier_turn_still_uses_the_fast_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 档的寒暄 ⇒ 生效档 standard ⇒ 快顶 1200 原样保持（不为它放开）。"""
    captured: list = []
    capability = _capability(monkeypatch, captured)
    message = _message("你好")
    capability(message, _decision(message))
    assert captured, "能力没有走到生成交"
    assert captured[0]["max_tokens"] == 1200


# ===================== 放宽判据必须跟登记表秩走（2026-10-04 第四档回归） =====================
#
# 上面两枚锁只量到「详尽 = 当时表里最长的一档」。表里长出第四档「铺写」之后，
# 生产那一句 `if fast_cap_tier == REPLY_TIER_DETAIL_ID:` 仍在**点旧顶格的名**：
# 于是最长的档反而拿不到放宽，快顶会把要铺 600-1200 字的场景描写截在半路——
# 正是本文件开头那句「详尽档等于空转」要避免的事，只是换了个受害者。
# 下面两枚锁的写法刻意**不出现任何档名字面量、不出现任何字符数**：
# 顶格档、档位秩、放宽阈值全部从 ``REPLY_LENGTH_TIERS`` / ``_REPLY_TIER_RANK`` 现取，
# 表里再加第五档时它们自动量到，不必回来改第三次。
# token 面用 512 / 32000 这两枚与登记表无关的数字，免得把「字符数」误当成「token 数」。

_FAST_TOKEN_CAP = 512
_NORMAL_TOKEN_CAP = 32000
#: 与生产选档链同源的一条真实问题（知识问答，auto 列本会进详尽档）。
_PROBE_TEXT = "守岸人与黑海岸是什么关系"


def _matrix_pointed_at(tier_id: str) -> dict[str, dict[str, str]]:
    """把选档表每一格都指向同一档（只在内存里，monkeypatch 自动还原）。

    登记表里没有任何一格指向铺写档（那是授予腿专用档，锁在
    ``test_scene_tier_is_only_reachable_through_the_narration_grant``），所以这里
    用**测试侧改表**来模拟「新档接进全局选档」的那一天——改的是判据的输入，
    不是判据本身：放宽与否仍由生产那一句分支决定。
    """
    return {
        question_type: {mode: tier_id for mode in row}
        for question_type, row in chat.REPLY_TIER_MATRIX.items()
    }


def _fast_leg_max_tokens(monkeypatch: pytest.MonkeyPatch, tier_id: str) -> object:
    """把生效档钉成 ``tier_id`` 走一遍生产 fast 腿，返回它交给生成口的 max_tokens。"""
    captured: list = []
    with monkeypatch.context() as patched:
        patched.setattr(chat, "REPLY_TIER_MATRIX", _matrix_pointed_at(tier_id))
        # 前置确认：生产判据（不是本文件抄的那份）确实选中了目标档，否则下面的
        # 断言是在空跑——本仓栽过「断言写成恒真」两次，这里把它堵在起跑线。
        assert chat.resolve_reply_length_tier("auto", _PROBE_TEXT) == tier_id
        capability = _capability(
            monkeypatch,
            captured,
            fast_max_tokens=_FAST_TOKEN_CAP,
            max_tokens=_NORMAL_TOKEN_CAP,
        )
        message = _message(_PROBE_TEXT)
        capability(message, _decision(message))
    assert captured, "能力没有走到生成交 ⇒ 本件是空跑"
    assert captured[0]["fast_mode"] is True, "fast 腿没开 ⇒ 量不到快顶"
    return captured[0]["max_tokens"]


def test_registry_top_tier_gets_the_same_relief_the_detail_tier_already_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """登记表顶格档（现＝铺写）在 fast 腿拿到的放宽，必须与详尽档同一待遇。"""
    top_tier = chat._REPLY_TIER_TOP_ID  # 派生自登记表，不写死档名
    assert top_tier != chat.REPLY_TIER_DETAIL_ID, (
        "登记表里详尽就是顶格 ⇒ 本件量不到『按名点名会漏新档』这一维，"
        "表上再加一档时本断言会自动放开"
    )
    detail_max_tokens = _fast_leg_max_tokens(monkeypatch, chat.REPLY_TIER_DETAIL_ID)
    top_max_tokens = _fast_leg_max_tokens(monkeypatch, top_tier)
    assert detail_max_tokens == _NORMAL_TOKEN_CAP, "详尽档的放宽也坏了 ⇒ 另起根因"
    assert top_max_tokens == _NORMAL_TOKEN_CAP, (
        f"顶格档 {top_tier} 被压到快顶 {_FAST_TOKEN_CAP}：按档名点名的放宽漏掉了它，"
        "最长的那一档反被截在半路"
    )


@pytest.mark.parametrize(
    "tier_id",
    sorted(chat.REPLY_LENGTH_TIERS, key=lambda tid: chat._REPLY_TIER_RANK[tid]),
)
def test_fast_cap_relief_follows_the_registry_rank(
    monkeypatch: pytest.MonkeyPatch, tier_id: str
) -> None:
    """整表穷尽：秩 ≥ 详尽的档一律放宽，秩在它以下的仍压快顶（阈值也取自登记表）。"""
    at_or_above_detail = (
        chat._REPLY_TIER_RANK[tier_id] >= chat._REPLY_TIER_RANK[chat.REPLY_TIER_DETAIL_ID]
    )
    got = _fast_leg_max_tokens(monkeypatch, tier_id)
    if at_or_above_detail:
        assert got == _NORMAL_TOKEN_CAP, f"{tier_id} 档长到详尽那一级却没拿到放宽"
    else:
        assert got == _FAST_TOKEN_CAP, f"{tier_id} 档短于详尽却放开了快顶 ⇒ 成本门失守"
