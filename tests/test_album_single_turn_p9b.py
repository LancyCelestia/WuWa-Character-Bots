"""席位 P9b：TG 拼格「同册只回一次」判据的锁（全离线，零真实外发，零管道调用）。

判据真身＝``ingest/message_context.telegram_album_turn_decision``（席位 P9 写于 2026-10-02，
本席只出锁与接线补丁，**不改判据**）。本锁只断言**返回值**（``merged`` / ``reason`` /
``arrival`` / ``owner_message_id``），不断言管道副作用黑箱——"不触发第二次能力调用"这件事
由调用方拿到 ``merged=True`` 就返回来兑现，接线见 ``p9b-init-wiring.patch``。

六腿口径（与判据注释块一一对应）：
① 同册第二张纯媒体成员 ⇒ ``merged=True reason=merged``；
② 反证腿：三枚**不同** ``media_group_id`` 各自都 ``reason=owner``——证明判的是"册"，
   不是"上一条消息"（若实现退化成"上一条"，本腿必红）；
③ 配文腿：成员带用户正文 ⇒ ``reason=caption_member`` 且 ``merged=False``
   （宁多回一句，绝不吞正文）；
④ 同轮重投腿：同 ``message_id`` 重放 ⇒ ``reason=same_turn`` 且 ``merged=False``（台账 #65）；
⑤ 平台腿：非 telegram 适配器 ⇒ ``reason=not_album``，且**登记簿一个字节都不写**
   （QQ 零扰动＝行为不变 + 状态不变两条都判）；
⑥ 过期腿：窗口外重新认册主（有界性——不开等待窗、不 await，最坏只多回一句）。

窗口真身复用 ``runtime/message_merge.MERGE_WINDOW_SECONDS``（用户 2026-09-27 裁定的 3s
折句窗），**不是**本件的 ``ALBUM_BUCKET_TTL_SECONDS``（120s 计数桶）——⑥ 腿把这两者的
语义差也钉住。

注毒自证（「禁放宽守卫」口径，台账 #66★／#67★）：三枚 poison 腿各自把一个 fail-open 闸
摘掉，断言对应的正腿**必红**、撤销补丁后**复绿**；只摘一处、其余不动，避免"全红＝没信息"。

与既有 ``tests/test_telegram_album_and_topic_ingest.py`` 互不重叠：那件锁文本面聚合与门票，
本件锁调用次数判据。两件各自 reset，互不串状态。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.domains.chat_reply.runtime import message_merge
from plugins.bot_unified_runtime.domains.chat_reply.ingest import message_context
from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    ALBUM_TURN_CAPTION,
    ALBUM_TURN_MERGED,
    ALBUM_TURN_NOT_ALBUM,
    ALBUM_TURN_OWNER,
    ALBUM_TURN_SAME_TURN,
    album_turn_state,
    reset_telegram_album_state,
    telegram_album_context,
    telegram_album_turn_decision,
)

_GROUP_A = "MG-aaaa11"
_GROUP_B = "MG-bbbb22"
_GROUP_C = "MG-cccc33"
_SESSION = "channel_30"


@pytest.fixture(autouse=True)
def _isolate_album_state() -> Any:
    """两本账都清：计数桶（文本面）与同册开门登记（调用次数面）。"""
    reset_telegram_album_state()
    yield
    reset_telegram_album_state()


class _TelegramEvent:
    """最小假 TG 事件：``__module__`` 是摄取判适配器的唯一依据；``message_id`` 逐条不同。"""

    __module__ = "nonebot.adapters.telegram.event"

    def __init__(
        self,
        *,
        message_id: int,
        text: str = "",
        media_group_id: str | None = None,
        session_id: str = _SESSION,
    ) -> None:
        self._text = text
        self._session_id = session_id
        self.message_id = message_id
        self.chat = SimpleNamespace(id=30)
        if media_group_id is not None:
            self.media_group_id = media_group_id

    def get_plaintext(self) -> str:
        return self._text

    def get_session_id(self) -> str:
        return self._session_id

    def get_user_id(self) -> str:
        return "1001"

    def is_tome(self) -> bool:
        return False


class _OnebotEvent:
    """最小假 OneBot 事件（QQ 平台腿载体）。"""

    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, *, message_id: int = 7, media_group_id: str | None = None) -> None:
        self._session_id = "group_1_123"
        self.message_id = message_id
        self.group_id = 1
        self.sender = SimpleNamespace(
            user_id=123, card="", nickname="小明", level="", role="", title=""
        )
        if media_group_id is not None:
            self.media_group_id = media_group_id

    def get_plaintext(self) -> str:
        return ""

    def get_session_id(self) -> str:
        return self._session_id

    def get_user_id(self) -> str:
        return "123"

    def is_tome(self) -> bool:
        return False


def _photo_segment(*, media_group_id: str | None = None, index: int = 1) -> dict[str, Any]:
    """一条媒体段——专辑号一律由摄取盖章，夹具不手抄（真链路形状）。"""
    data: dict[str, Any] = {"file": f"/tmp/tg_{index}.jpg"}
    if media_group_id is not None:
        data["media_group_id"] = media_group_id
    return {"type": "photo", "data": data}


def _tg_album_message(
    message_id: int,
    group_id: str,
    *,
    caption: str = "",
    session_id: str = _SESSION,
) -> Any:
    """走真摄取链路的 TG 拼格成员消息（纯媒体时 ``plain_text`` 只剩 ``[相册 共N图]`` 标签）。"""
    event = _TelegramEvent(message_id=message_id, text=caption, media_group_id=group_id, session_id=session_id)
    segments = [_photo_segment(index=message_id)]
    if caption:
        segments.append({"type": "text", "data": {"text": caption}})
    return _incoming_from_nonebot_event(event, bot_id="bot-1", segments=segments)


# ---------------------------------------------------------------------------
# ① 同册第二张纯媒体成员 ⇒ 折进册主那一轮
# ---------------------------------------------------------------------------


def test_second_pure_media_member_of_same_album_folds_into_owner_turn() -> None:
    owner = telegram_album_turn_decision(_tg_album_message(101, _GROUP_A), now=1_000.0)
    second = telegram_album_turn_decision(_tg_album_message(102, _GROUP_A), now=1_002.5)

    assert (owner.merged, owner.reason, owner.arrival) == (False, ALBUM_TURN_OWNER, 1)
    assert owner.owner_message_id == "101"
    # 🔴 本腿就是"不触发第二次能力调用"的语义载体：merged=True ⇒ 调用方必须就此返回。
    assert second.merged is True
    assert second.reason == ALBUM_TURN_MERGED
    assert (second.arrival, second.media_group_id) == (2, _GROUP_A)
    # 归属不许漂移：折叠记的还是册主那一轮，不是"上一条"。
    assert second.owner_message_id == "101"

    third = telegram_album_turn_decision(_tg_album_message(103, _GROUP_A), now=1_002.9)
    assert (third.merged, third.reason, third.arrival) == (True, ALBUM_TURN_MERGED, 3)


# ---------------------------------------------------------------------------
# ② 反证：判的是册，不是"上一条消息"
# ---------------------------------------------------------------------------


def test_three_different_album_groups_are_each_an_owner() -> None:
    decisions = [
        telegram_album_turn_decision(_tg_album_message(200 + index, group_id), now=2_000.0)
        for index, group_id in enumerate((_GROUP_A, _GROUP_B, _GROUP_C))
    ]

    assert [(d.merged, d.reason) for d in decisions] == [
        (False, ALBUM_TURN_OWNER)
    ] * 3
    assert [d.media_group_id for d in decisions] == [_GROUP_A, _GROUP_B, _GROUP_C]
    # 三本账各归各的册主——若实现只看"上一条"，这里会并成一枚键。
    assert sorted(album_turn_state()) == [
        f"{_SESSION}|{_GROUP_A}",
        f"{_SESSION}|{_GROUP_B}",
        f"{_SESSION}|{_GROUP_C}",
    ]


def test_same_album_group_in_another_session_is_a_different_album() -> None:
    """会话隔离：同一专辑号在别的会话重新认册主（防跨会话串册）。"""
    telegram_album_turn_decision(_tg_album_message(301, _GROUP_A), now=3_000.0)
    elsewhere = telegram_album_turn_decision(
        _tg_album_message(302, _GROUP_A, session_id="channel_99"), now=3_001.0
    )

    assert (elsewhere.merged, elsewhere.reason) == (False, ALBUM_TURN_OWNER)


# ---------------------------------------------------------------------------
# ③ 配文腿：带用户正文的成员绝不折（宁多回一句，不吞正文）
# ---------------------------------------------------------------------------


def test_member_with_user_caption_is_never_folded() -> None:
    telegram_album_turn_decision(_tg_album_message(401, _GROUP_A), now=4_000.0)
    captioned = telegram_album_turn_decision(
        _tg_album_message(402, _GROUP_A, caption="这张图好看"), now=4_001.0
    )

    assert captioned.merged is False
    assert captioned.reason == ALBUM_TURN_CAPTION
    assert captioned.owner_message_id == "401"
    # 正文原样还在（判据只读不删）。
    assert "这张图好看" in _tg_album_message(403, _GROUP_A, caption="这张图好看").plain_text


# ---------------------------------------------------------------------------
# ④ 同轮重投腿：同 message_id 重放不得被当"册内第二张"静默吞（台账 #65）
# ---------------------------------------------------------------------------


def test_same_message_id_replay_is_reported_not_swallowed() -> None:
    owner = telegram_album_turn_decision(_tg_album_message(501, _GROUP_A), now=5_000.0)
    replay = telegram_album_turn_decision(_tg_album_message(501, _GROUP_A), now=5_001.0)

    assert (owner.reason, replay.merged, replay.reason) == (ALBUM_TURN_OWNER, False, ALBUM_TURN_SAME_TURN)
    assert replay.owner_message_id == "501"
    # 同轮重投不推进"已到达张数"，也不改册主登记（幂等腿另有其账，本判据不越权）。
    assert album_turn_state()[f"{_SESSION}|{_GROUP_A}"][1] == 1


# ---------------------------------------------------------------------------
# ⑤ 平台腿：非 telegram 适配器逐字节不变，且状态零写入
# ---------------------------------------------------------------------------


def _hand_stamped_qq_message() -> SimpleNamespace:
    """QQ 消息**手工带上**合法专辑号与段面章：考验的正是适配器门，不是"章没盖上"。"""
    return SimpleNamespace(
        adapter="nonebot",
        platform="qq",
        session_id="group_1_123",
        message_id="7",
        plain_text="[图片]",
        raw_segments=[_photo_segment(media_group_id=_GROUP_A)],
    )


def test_qq_album_member_with_stamped_group_stays_untouched() -> None:
    decision = telegram_album_turn_decision(_hand_stamped_qq_message(), now=6_000.0)

    assert (decision.merged, decision.reason, decision.arrival) == (False, ALBUM_TURN_NOT_ALBUM, 0)
    assert decision.media_group_id == _GROUP_A  # 读得到，只是不据它以 QQ 名义折叠
    # 🔴 QQ 零扰动的第二条：判定不写登记簿（否则 QQ 也在长账）。
    assert album_turn_state() == {}


def test_qq_event_shape_and_text_are_byte_identical_after_the_judgement() -> None:
    """QQ 事件带 media_group_id 也不被当专辑；判据吃它之后文本面形态一字不变。"""
    incoming = _incoming_from_nonebot_event(
        _OnebotEvent(media_group_id=_GROUP_A),
        bot_id="bot-1",
        segments=[_photo_segment(index=1), _photo_segment(index=2)],
    )

    assert incoming.plain_text == "[图片] [图片]"
    assert "[相册" not in incoming.plain_text
    decision = telegram_album_turn_decision(incoming, now=6_500.0)
    assert (decision.merged, decision.reason) == (False, ALBUM_TURN_NOT_ALBUM)
    assert incoming.plain_text == "[图片] [图片]"  # 判定是纯读，不返工本文
    assert album_turn_state() == {}


@pytest.mark.parametrize("adapter,platform", [("mail", "email"), ("nonebot", "qq"), ("", "")])
def test_non_telegram_adapters_all_take_the_not_album_branch(adapter: str, platform: str) -> None:
    message = SimpleNamespace(
        adapter=adapter,
        platform=platform,
        session_id="s-1",
        message_id="9",
        plain_text="[相册 共2图]",
        raw_segments=[_photo_segment(media_group_id=_GROUP_C)],
    )

    assert telegram_album_turn_decision(message, now=7_000.0).reason == ALBUM_TURN_NOT_ALBUM
    assert album_turn_state() == {}


# ---------------------------------------------------------------------------
# ⑥ 过期腿：窗口外重新认册主（有界性由结构保证，最坏只多回一句）
# ---------------------------------------------------------------------------


def test_claim_expiry_reopens_ownership_instead_of_hanging_the_round() -> None:
    window = message_merge.MERGE_WINDOW_SECONDS
    assert window == 3.0  # 窗口真身＝折句窗，绝不与计数桶 TTL 混用
    assert window != message_context.ALBUM_BUCKET_TTL_SECONDS

    telegram_album_turn_decision(_tg_album_message(801, _GROUP_A), now=8_000.0)
    in_window = telegram_album_turn_decision(_tg_album_message(802, _GROUP_A), now=8_000.0 + window)
    late = telegram_album_turn_decision(_tg_album_message(803, _GROUP_A), now=8_000.0 + window + 0.5)

    assert (in_window.merged, in_window.reason) == (True, ALBUM_TURN_MERGED)  # 边界含等号
    assert (late.merged, late.reason, late.arrival) == (False, ALBUM_TURN_OWNER, 1)
    assert late.owner_message_id == "803"  # 迟到的那张自成一册主，绝不"永远没人回"
    # 重新开门后窗口照旧生效。
    after = telegram_album_turn_decision(_tg_album_message(804, _GROUP_A), now=8_003.0)
    assert (after.merged, after.reason) == (True, ALBUM_TURN_MERGED)


def test_reset_clears_both_ledgers() -> None:
    telegram_album_context(
        SimpleNamespace(media_group_id=_GROUP_A),
        [_photo_segment(index=1)],
        "telegram",
        session_id=_SESSION,
    )
    telegram_album_turn_decision(_tg_album_message(901, _GROUP_A), now=9_000.0)
    assert message_context._ALBUM_BUCKETS and album_turn_state()  # 两本账都长过

    reset_telegram_album_state()

    assert message_context._ALBUM_BUCKETS == {}
    assert album_turn_state() == {}
    # 清完重新认册主（证明本件用例之间不串状态）。
    assert telegram_album_turn_decision(_tg_album_message(902, _GROUP_A), now=9_001.0).reason == ALBUM_TURN_OWNER


# ---------------------------------------------------------------------------
# 注毒自证：摘掉一条闸 ⇒ 对应的正腿必红；撤销 ⇒ 复绿
# ---------------------------------------------------------------------------


def _leg1_second_decision(now: float = 10_001.0) -> Any:
    telegram_album_turn_decision(_tg_album_message(1001, _GROUP_A), now=10_000.0)
    return telegram_album_turn_decision(_tg_album_message(1002, _GROUP_A), now=now)


def test_poison_neutering_the_merge_window_makes_leg1_red_and_restore_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把 ``merged`` 判定摘掉（窗口收成永不命中）⇒ 腿 ① 的红绿两态都实测一遍。"""
    monkeypatch.setattr(message_merge, "MERGE_WINDOW_SECONDS", -1.0)
    poisoned = _leg1_second_decision()
    assert (poisoned.merged, poisoned.reason) == (False, ALBUM_TURN_OWNER)  # 腿①在此为红

    monkeypatch.undo()
    reset_telegram_album_state()  # 被摘掉判定的那一趟已把登记写成"1002 是册主"，不清会串态
    restored = _leg1_second_decision()
    assert (restored.merged, restored.reason) == (True, ALBUM_TURN_MERGED)  # 腿①复绿


def test_poison_trusting_the_adapter_makes_the_qq_leg_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """摘掉平台闸（一律当 TG）⇒ 腿 ⑤ 的 QQ 消息会被折、登记会长账，两态实测。"""
    monkeypatch.setattr(message_context, "_telegram_adapter_of", lambda message: True)
    qq = _hand_stamped_qq_message()
    poisoned = telegram_album_turn_decision(qq, now=11_000.0)
    assert poisoned.reason == ALBUM_TURN_OWNER  # 不是 not_album＝腿⑤在此为红
    assert album_turn_state() != {}  # QQ 侧长出了账＝扰动已发生

    monkeypatch.undo()
    assert telegram_album_turn_decision(_hand_stamped_qq_message(), now=11_000.0).reason == ALBUM_TURN_NOT_ALBUM


def test_poison_dropping_the_caption_gate_would_swallow_user_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘掉正文闸 ⇒ 腿 ③ 变红（配文被折掉＝吞正文），撤销后复绿。"""
    monkeypatch.setattr(message_context, "_message_carries_user_text", lambda message: False)
    telegram_album_turn_decision(_tg_album_message(1201, _GROUP_A), now=12_000.0)
    poisoned = telegram_album_turn_decision(
        _tg_album_message(1202, _GROUP_A, caption="这张图好看"), now=12_001.0
    )
    assert (poisoned.merged, poisoned.reason) == (True, ALBUM_TURN_MERGED)  # 腿③在此为红

    monkeypatch.undo()
    reset_telegram_album_state()
    telegram_album_turn_decision(_tg_album_message(1203, _GROUP_A), now=12_000.0)
    restored = telegram_album_turn_decision(
        _tg_album_message(1204, _GROUP_A, caption="这张图好看"), now=12_001.0
    )
    assert (restored.merged, restored.reason) == (False, ALBUM_TURN_CAPTION)  # 腿③复绿
