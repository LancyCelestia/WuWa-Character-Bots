r"""席 N1 · P3.10：NoticeEvent 族与合成轮的入站幂等**兜底键**（旧语义＝无 message_id
即整条去重关闭，戳一戳/表情回应/群增减/管理员变动重放无人拦）。

三档形制的账在 `event_idempotency.py` 模块头注，本件只执法四条红线：

1. **正身键逐字节不动**（QQ/OneBot 现役形态）＋ **段必合法**：分隔符 `|` 不是段内合法
   字符，不洗则 `bot_id="a"`+`message_id="b|c"` 与 `bot_id="a|b"`+`message_id="c"` 拼出
   同一枚键＝两条不同事件共用一个幂等桶（静默吞第二条）。判据一律回喂中央
   `dedupe.py:is_legal_segment`，本文件不抄第二份字符集。
2. **兜底键只在事实齐时建**：缺一枚身份事实就返回空串——宁可不拦，绝不拿半截身份把
   别人的事件并进同一个桶。
3. **不误伤**：兜底桶宽＝`bot_poke_private_cooldown_seconds` 缺省值（同一执行点在
   `capabilities/poke.py:57` 已吃掉「同人 30 秒内第二发」），因此这条键不比既有冷却更
   凶；跨桶的两次真事件必须各放行一次。有正文而无 message_id 的合成轮**不建入站键**
   （其幂等真身＝出站 `SendRequest.dedupe_key` + 队列 `ON CONFLICT`，台账 #46）。
4. **接在真咽喉上**：兜底键必须被 `RuntimePipeline._claim_event` 实际吃到（行为锁跑真
   pipeline，不接受"只测纯函数"的孤儿件）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    event_idempotency as eid,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.event_idempotency import (
    FALLBACK_BUCKET_SECONDS,
    EventIdempotencyTable,
    build_event_dedupe_key,
    build_notice_fallback_key,
    event_dedupe_gap_reason,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    is_legal_segment,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

_SEG_SPLIT = "|"
_MOMENT = datetime(2026, 10, 2, 3, 4, 5, tzinfo=timezone.utc)


def _notice_message(**overrides: object) -> IncomingMessage:
    """戳一戳形态的入站轮：NoticeEvent 族没有 message_id、也没有正文。

    私聊会话（`_handle_poke_notice` 的私聊臂同形）——群聊空文本会被搭话好感门先拦下，
    那与本题无关，会掩盖要测的那一门。
    """
    base: dict[str, object] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "10000",
        "session_id": "private_2002",
        "session_type": SessionType.PRIVATE,
        "sender_id": "2002",
        "plain_text": "",
        "message_id": None,
        "timestamp": _MOMENT,
    }
    base.update(overrides)
    return IncomingMessage(**base)  # type: ignore[arg-type]


def _every_segment_is_legal(key: str) -> bool:
    return bool(key) and all(
        is_legal_segment(part) for part in key.split(_SEG_SPLIT)
    )


# ---------------------------------------------------------------------------
# ① 正身键：现役形制不动 + 段必合法（洗段不复制第二套正则）
# ---------------------------------------------------------------------------


def test_clean_qq_primary_key_is_byte_identical() -> None:
    """不误伤腿：OneBot 纯数字 id 洗完逐字节不变 ⇒ 生产已入库的键零迁移。"""
    message = _notice_message(message_id="m-9", plain_text="你好")
    assert build_event_dedupe_key(message) == "onebot|10000|m-9"


def test_separator_in_inbound_id_cannot_fold_two_events_into_one_bucket() -> None:
    """注毒腿：mail/TG 侧的标识由外部决定，含 `|` 时必须被洗开。

    旧实现直拼 f-string ⇒ 这两枚不同事件的键**逐字节相等**（`a|b` 落在 message_id 位
    与落在 bot_id 位拼得出同一串），第二条被当重复吞掉。现在两枚键互异且逐段合法。
    """
    left = _notice_message(bot_id="onebot|x", message_id="y", plain_text="hi")
    right = _notice_message(bot_id="onebot", message_id="x|y", plain_text="hi")
    left_key = build_event_dedupe_key(left)
    right_key = build_event_dedupe_key(right)
    assert left_key and right_key
    assert left_key != right_key, (left_key, right_key)
    assert _every_segment_is_legal(left_key) and _every_segment_is_legal(right_key)
    # 同输入恒同输出（幂等保住在），不同输入靠摘要分开。
    assert build_event_dedupe_key(left) == left_key


def test_mail_style_angle_bracket_id_still_builds_legal_segments() -> None:
    """mail 的 Message-ID `<…@…>` 是可控文本：洗完必须仍是合法段且可寻址。"""
    message = _notice_message(
        adapter="mail",
        bot_id="shorekeeper@foxmail.com",
        sender_id="visitor@example.com",
        plain_text="来信",
        message_id="<orig-9@example.com>",
    )
    key = build_event_dedupe_key(message)
    assert _every_segment_is_legal(key), key
    assert key.split(_SEG_SPLIT)[0] == "mail"
    other = build_event_dedupe_key(
        message.model_copy(update={"message_id": "<other-9@example.com>"})
    )
    assert other != key


def test_key_builder_declares_no_second_segment_regex() -> None:
    """反第二真身：本件只委托中央洗段口，自己不写字符集正则。"""
    text = Path(eid.__file__).read_text(encoding="utf-8")
    assert "active_push_key_segment" in text, "不再委托中央洗段＝自立第二套键规范"
    assert "is_legal_segment" in text, "构造侧不自检段合法性"
    assert "re.compile" not in text, "本件里出现自带正则＝第二把尺"


# ---------------------------------------------------------------------------
# ② 兜底键：NoticeEvent 族今天终于有一把幂等尺
# ---------------------------------------------------------------------------


def test_notice_without_message_id_gets_fallback_key_and_blocks_replay() -> None:
    key = build_event_dedupe_key(_notice_message())
    assert key, "NoticeEvent 族仍建不出兜底键＝重复投递面未闭"
    assert _every_segment_is_legal(key)
    assert key.split(_SEG_SPLIT)[0] == eid._FALLBACK_NAMESPACE

    table = EventIdempotencyTable()
    assert table.claim(key, capability_id="bot.poke") is True
    assert table.claim(key, capability_id="bot.poke") is False


def test_fallback_key_requires_every_identity_fact() -> None:
    """注毒腿：缺一枚身份事实就不许建键——否则键退化成「按会话合并」，吞别人的事件。"""
    for missing in ("adapter", "bot_id", "session_id", "sender_id"):
        message = _notice_message(**{missing: ""})
        assert build_event_dedupe_key(message) == "", f"{missing} 缺席却仍建了键"
        assert event_dedupe_gap_reason(message) == f"missing_{missing}"


def test_fallback_key_without_timestamp_fact_is_not_fabricated() -> None:
    """时间事实取不到 ⇒ 不建键（宁可不拦），并把缺口点名出来而不是静默放行。

    用裸对象模拟「契约里没有可用 timestamp」的形态（摄取层之外的构造点确实可能这样）。
    """

    class _Bare:
        adapter = "onebot"
        bot_id = "10000"
        session_id = "group_123"
        sender_id = "2002"
        plain_text = ""
        message_id = None
        timestamp = None

    assert build_notice_fallback_key(_Bare()) == ""
    assert event_dedupe_gap_reason(_Bare()) == "missing_event_timestamp"


def test_two_real_pokes_across_buckets_are_both_allowed() -> None:
    """不误伤腿：跨桶的两次真戳各放行一次（同人连戳不误吞）。"""
    first = build_event_dedupe_key(_notice_message())
    later = build_event_dedupe_key(
        _notice_message(
            timestamp=datetime.fromtimestamp(
                _MOMENT.timestamp() + FALLBACK_BUCKET_SECONDS + 1.0, tz=timezone.utc
            )
        )
    )
    assert first and later and first != later

    different_poker = build_event_dedupe_key(_notice_message(sender_id="3003"))
    assert different_poker != first, "同会话不同人必须各占一桶"


def test_fallback_bucket_width_is_not_an_invented_number() -> None:
    """阈值真身：桶宽等值 `bot_poke_private_cooldown_seconds` 缺省（poke.py:57 那条冷却）。

    等值一破，兜底键就会比既有防刷屏门更凶（「连戳两下只回一下」），所以两处不许各自
    漂移——漂移即此格翻红，逼改动一起发生。
    """
    from plugins.bot_unified_runtime.config import Config

    declared = Config.model_fields["bot_poke_private_cooldown_seconds"].default
    assert float(declared) == FALLBACK_BUCKET_SECONDS, (declared, FALLBACK_BUCKET_SECONDS)


# ---------------------------------------------------------------------------
# ③ 合成轮：不建入站键（幂等真身在出站队列），但缺口必须可问
# ---------------------------------------------------------------------------


def test_synthetic_turn_is_not_deduped_inbound_and_names_the_reason() -> None:
    """有正文而无 message_id＝订阅推送/历史上的今天/控制台轮。

    这里**故意**不建键：入站按「同会话同文本」拦＝把用户连发的同一句话吞掉。
    本锁执法的是「它既不建键、又把自己的形态说清楚」，不是"建不出就算过"。
    """
    message = _notice_message(plain_text="历史上的今天")
    assert build_event_dedupe_key(message) == ""
    assert event_dedupe_gap_reason(message) == "synthetic_turn_without_message_id"
    assert event_dedupe_gap_reason(_notice_message(message_id="m-1")) == "none"


# ---------------------------------------------------------------------------
# ④ 接线锁：兜底键真被管线咽喉吃到（孤儿件不算完成）
# ---------------------------------------------------------------------------


def _pipeline_with(table: EventIdempotencyTable | None) -> RuntimePipeline:
    audit = InMemoryAuditLogger()
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit),
        audit_logger=audit,
        idempotency_table=table,
    )


def _capability(request_id: str):
    def _run(message: IncomingMessage, _decision: object) -> CapabilityResult:
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.poke",
            kind="text",
            body="回一句",
            send_policy=SendPolicy.SILENT_AUDIT,
        )

    return _run


def test_pipeline_blocks_replayed_notice_event_via_fallback_key() -> None:
    """注毒腿：把兜底腿摘掉（`build_event_dedupe_key` 退回「无 message_id 即空串」）
    这一格必红——证明拦重复的是兜底键，不是别的什么。"""
    pipeline = _pipeline_with(EventIdempotencyTable())
    replay = _notice_message(request_id="r-1")
    twin = _notice_message(request_id="r-2")

    first = pipeline.handle(replay, _capability("r-1"), "bot.poke")
    second = pipeline.handle(twin, _capability("r-2"), "bot.poke")

    assert first.state.value != "blocked", first.public_message
    assert second.state.value == "blocked", (
        "重放的 notice 未被兜底键拦下＝重复投递面仍在"
    )
    assert "重复" in (second.public_message or "")


def test_pipeline_without_table_still_processes_notice_event() -> None:
    """反向不误伤腿：幂等表关闭（生产缺省 `enabled=False`）时兜底键不改变任何投递。"""
    pipeline = _pipeline_with(None)
    receipt = pipeline.handle(_notice_message(request_id="r-3"), _capability("r-3"), "bot.poke")
    assert receipt.state.value != "blocked"
