"""群聊内容面「降级而非整条吃掉」回归锁（`domains/render/reviewer.py`，席 grpfix 2026-10-04）。

改前实测形态：群作用域里 `_PUBLIC_OUTPUT_UNSAFE` 任一枚词面命中 ⇒ `approved=False`
＋ `ReviewAction.BLOCK` ⇒ `domains/chat_reply/runtime/pipeline.py:1363` 那一支直接
返回 `ReceiptState.BLOCKED`，正文、`text_parts`、`prefix_parts`、媒体部件**一并丢掉**，
群里只剩 `_review_block_public_message` 那句与人格无关的兜底文案。审计量到的两类误伤：
①中文词界碰撞（两个不相干的词恰好拼出词面）、②`‹pattern-1›` 的字母数字枚还会撞上
楼栋编号/表格号/英文月日。后果＝一条完全清白的长回复静默消失。
用户 2026-10-04 的硬要求＝群里那种**长、多段、具体**的回复必须真的出得来，
所以「别往群里写」不算修法。

⚠ ②那一类误伤已于 2026-10-06 的 F-12 从根上治掉（给那枚字母数字形状加了左右词界，
见 `tests/test_redline_word_boundary.py`）⇒ 本文件的英文月日段落**不再被涂销**，出站
字节基线随之重录（现算，非放宽判据：保住的内容变多了）。①那一类（中文词界碰撞）
不在 F-12 裁定面内，仍然照咬照涂销，本文件正是靠它驱动降级腿。

本文件锁五件事：
①命中面只落在**可改字节的文字载体**（正文 / `text_parts` / `prefix_parts`）时：
  那一处词面被中和、**其余内容照发**、部件与媒体不丢、审计留一行降级记号；
②中和后**没剩下要说的话** ⇒ 照旧整条 BLOCK（判据一律不放宽）；
③词面落在**媒体载荷**（图/音/视频/文件/动作）时照旧 BLOCK——那里的字节改不掉；
④私聊那一支本来就不跑内容面 ⇒ **逐字节不变**，正文一个字都不许被动；
⑤内部错误 fail-open：本可出门的干净消息绝不因新腿被吃掉；命中消息退回调前形态
  （改前它本来也不出门 ⇒ 不新增删除，也不新增泄露）。
⑦（用户 2026-10-06 裁「telegram 频道＝群侧」）**公共空间归侧**：出站内容闸的作用域
  判据只转述中央那把尺 `content_route.is_public_space_session`，`channel` 与 `group`
  同侧一样涂销；私聊／控制台／邮件三面一字不改。本文件末尾一节钉这一格。

全离线，零网络零落盘。**本文件不抄录词面清单**：需要命中串时一律拿
`_PUBLIC_OUTPUT_UNSAFE` 自己 `search` 现取，条目在注释里只以 `‹pattern-N›` 叙述。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReceiptState,
    ReviewAction,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.render import reviewer as reviewer_module
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

_REQUEST_ID = "req-grpfix-1"

# 一条「长、多段、具体」的群回复。第二段落是中文词界碰撞（`‹pattern-1›`）＝本轮唯一
# 真命中；第三段落里的英文月日是 F-12 之前的字母数字误伤，加了词界之后它**应当原样
# 出门**（下面 `_UNTOUCHED_FRAGMENTS` 把它也钉住）。
_PARA_HEADLINE = "先说结论：傍晚从那头走过去最舒服，二十分钟内能到地铁口。"
_PARA_COLLISION_CN = "这条支线对女性交通便利，晚归也不用绕路。"
_PARA_COLLISION_DATE = "值班表我核过了：November 18 那一格还空着，月底那周反而排满了。"
_PARA_TAIL = "另外记得带伞，午后有阵雨，潮汐窗口在四点前后。"
_PARAGRAPHS = (_PARA_HEADLINE, _PARA_COLLISION_CN, _PARA_COLLISION_DATE, _PARA_TAIL)
_BODY = "\n\n".join(_PARAGRAPHS)

_UNTOUCHED_FRAGMENTS = (
    "先说结论：傍晚从那头走过去最舒服",
    "晚归也不用绕路",
    "November 18 那一格还空着",  # F-12（2026-10-06）：词界加完，这一枚不再被当成违规洗掉
    "月底那周反而排满了",
    "另外记得带伞，午后有阵雨，潮汐窗口在四点前后",
)


def _hits(text: str) -> list[tuple[str, object]]:
    """按模块自己的清单现取命中面（不抄词面）。"""
    return [
        (label, pattern)
        for label, pattern in reviewer_module._PUBLIC_OUTPUT_UNSAFE
        if pattern.search(text)
    ]


def _matched_span(text: str) -> str:
    """从**模块的词面**里取一枚真实命中串，供「整条都是违规」那一例用。"""
    for _label, pattern in reviewer_module._PUBLIC_OUTPUT_UNSAFE:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return ""


def _result(**overrides: object) -> CapabilityResult:
    base: dict = {
        "request_id": _REQUEST_ID,
        "capability_id": "bot.chat",
        "kind": "text",
        "title": "守岸人的回复",
        "body": _BODY,
        "privacy_level": PrivacyLevel.GROUP,
    }
    base.update(overrides)
    return CapabilityResult(**base)  # type: ignore[arg-type]


def _decision(scope: SessionType = SessionType.GROUP) -> BotDecision:
    return BotDecision(
        request_id=_REQUEST_ID,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=scope,
        decision_reason="test",
    )


def _colliding_result() -> CapabilityResult:
    """群作用域 + 多部件 + 一枚清白媒体部件：命中面只在文字载体里。"""
    return _result(
        kind="mixed",
        text_parts=[_PARA_HEADLINE, _PARA_COLLISION_CN],
        prefix_parts=[{"type": "text", "text": _PARA_COLLISION_DATE}],
        images=[{"file": "tide.png", "caption": _PARA_TAIL}],
    )


# ============================================================= ① 命中＝中和那一处，其余照发


def test_group_collision_is_neutralised_not_wholesale_discarded() -> None:
    result = _result()
    assert _hits(_BODY), "夹具本身必须真的命中一枚词面，否则本例是空跑"

    review = review_capability_result(result, _decision(SessionType.GROUP))

    assert review.approved is True, review.reasons
    assert review.action is ReviewAction.REWRITE
    assert not _hits(review.safe_text), "命中面必须被中和掉"
    for fragment in _UNTOUCHED_FRAGMENTS:
        assert fragment in review.safe_text, f"清白的其余内容被一起吃掉了：{fragment}"
    assert review.safe_text != _BODY


def test_downgrade_records_an_audit_marker_of_what_happened() -> None:
    review = review_capability_result(_result(), _decision(SessionType.GROUP))

    assert any(
        "public output span neutralised" in reason for reason in review.reasons
    ), review.reasons
    # 事件名 `review.action.value` 进审计行这件事由 ⑥ 那一腿**跑真管线**当场证，
    # 本例只判单元面给出的记号与事件名（⑥：test_group_downgrade_writes_a_review_audit_row）。
    assert review.action.value == "rewrite"


def test_parts_survive_and_are_scrubbed_in_place() -> None:
    result = _colliding_result()
    review = review_capability_result(result, _decision(SessionType.GROUP))

    assert review.approved is True, review.reasons
    parts = result.text_parts or []
    assert len(parts) == 2, "部件数量不得因降级而减少"
    assert parts[0] == _PARA_HEADLINE, "清白的部件被改了"
    assert parts[1].strip(), "部件被中和成了空串（会被 renderer 丢掉）"
    assert not any(_hits(part) for part in parts)

    prefixes = result.prefix_parts or []
    assert len(prefixes) == 1
    assert not _hits(str(prefixes[0].get("text") or ""))


def test_media_on_the_result_is_not_lost() -> None:
    result = _colliding_result()
    review = review_capability_result(result, _decision(SessionType.GROUP))

    assert review.approved is True, review.reasons
    assert result.images == [{"file": "tide.png", "caption": _PARA_TAIL}]

    rendered = render_reviewed_output(result, review)
    assert "tide.png" in str(rendered.content_ref), rendered.content_ref
    assert "午后有阵雨" in rendered.text_fallback


def test_neutral_marker_is_still_visible_after_the_outbound_humanizer() -> None:
    """占位符写法锁（现算踩到的坑）：`plain_text` 的 `_QUOTES` 会把 `‹›「」《》`
    一类装饰括号当排版符号**删掉**。记号被吃掉＝词面消失又不留痕，群里读出来是
    两个硬拼在一起的半词（`对女已略通便利`），比降级更难查。"""
    result = _result()
    review = review_capability_result(result, _decision(SessionType.GROUP))
    rendered = render_reviewed_output(result, review)

    marker = reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER
    assert marker in review.safe_text
    assert marker in rendered.text_fallback, rendered.text_fallback
    assert not _hits(rendered.text_fallback), "中和后的文本再过一道出站腿，词面不许回来"


# ================================================== ② 中和后无话可说＝照旧整条 BLOCK


def test_message_that_is_only_the_offending_span_still_blocks() -> None:
    span = _matched_span(_BODY)
    assert span, "取不到命中词面 ⇒ 本例失效"

    review = review_capability_result(_result(body=span), _decision(SessionType.GROUP))

    assert review.approved is False, "整条都是违规内容时不许放行（判据被放宽了）"
    assert review.action is ReviewAction.BLOCK


# ============================================ ③ 词面在媒体载荷里＝改不掉，照旧 BLOCK


def test_span_carried_by_media_payload_still_blocks() -> None:
    for field in ("images", "audio", "video", "files", "actions"):
        result = _result(
            body="潮汐窗口在四点前后。",
            kind="mixed",
            **{field: [{"file": "payload.bin", "caption": _PARA_COLLISION_CN}]},
        )
        review = review_capability_result(result, _decision(SessionType.GROUP))
        assert review.approved is False, f"{field} 载荷里的命中面被放行了（字节改不掉）"
        assert review.action is ReviewAction.BLOCK
        assert result.body == "潮汐窗口在四点前后。", "BLOCK 那一支不许动 result"


# ==================================================== ④ 私聊面逐字节不变（本来就不筛）


def test_private_scope_output_is_byte_identical() -> None:
    result = _colliding_result()
    review = review_capability_result(result, _decision(SessionType.PRIVATE))

    assert review.approved is True, review.reasons
    assert review.reasons == []
    assert review.action is ReviewAction.ALLOW
    assert review.safe_text == _BODY, "私聊正文被改了一个字都不算「不变」"
    assert result.text_parts == [_PARA_HEADLINE, _PARA_COLLISION_CN]
    assert _hits(review.safe_text), "私聊若被中和＝给本来不筛的那一支加了道闸"


def test_clean_group_output_is_untouched_and_carries_no_marker() -> None:
    clean_body = "潮汐窗口在四点前后，记得带伞。"
    assert not _hits(clean_body)
    result = _result(body=clean_body, text_parts=None, prefix_parts=[], images=[])

    review = review_capability_result(result, _decision(SessionType.GROUP))

    assert review.approved is True
    assert review.action is ReviewAction.ALLOW
    assert review.reasons == []
    assert review.safe_text == clean_body


# ================================= ⑤ fail-open：新腿炸了不许吃掉本来出得了门的消息


def test_internal_error_in_new_leg_does_not_eat_a_clean_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("新腿内部错误")

    monkeypatch.setattr(reviewer_module, "_neutralise_public_spans", _boom)
    clean_body = "潮汐窗口在四点前后，记得带伞。"

    review = review_capability_result(
        _result(body=clean_body, text_parts=None, prefix_parts=[], images=[]),
        _decision(SessionType.GROUP),
    )
    assert review.approved is True, "干净消息被新腿的异常吃掉了＝fail-open 破了"
    assert review.safe_text == clean_body


def test_internal_error_in_new_leg_falls_back_to_the_pre_change_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("新腿内部错误")

    monkeypatch.setattr(reviewer_module, "_neutralise_public_spans", _boom)

    review = review_capability_result(_result(), _decision(SessionType.GROUP))

    # 改前形态＝整条 BLOCK；异常时退回它，既不多删一条消息，也不放行未中和的文本。
    assert review.approved is False
    assert review.action is ReviewAction.BLOCK
    assert _hits(review.safe_text) or review.safe_text == _BODY


# ============================================ 注毒自证：摘掉中和动作，①那一腿必须变红


def test_lock_has_teeth_if_the_neutralisation_leg_is_emptied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reviewer_module, "_neutralise_public_spans", lambda text, _hits: text
    )

    review = review_capability_result(_result(), _decision(SessionType.GROUP))

    # 摘掉中和＝命中面原样留在外发正文里，①的「词面必须被中和」那条断言当场红。
    assert _hits(review.safe_text), "摘掉降级腿后正文竟然也干净＝本锁在空跑"
    with pytest.raises(AssertionError):
        assert not _hits(review.safe_text)


# ================================================== ⑥ 降级一律进审计行（跑真管线）
#
# 2026-10-04 复核（席 auditrow）：上面那句注释曾经只是**愿望**。管线里唯一一枚
# `stage="review"` 的审计记录坐在 `if not review.approved:` 那一支里，而降级腿只在
# `approved` 为真时才走 ⇒ 事件名 `rewrite` 从未落进审计（现算证据＝本函数改前必红，
# 以及探针 `probe_baseline.json` 里 S1 的 `review_rows: []`）。本节的判据取**审计
# 后端实际收到的东西**，不取散文：`RuntimePipeline` 的 `audit_logger` 是构造参数，
# 所以传一枚内存录制桩即可把进程级真审计库整条绕开（生产库一个字节都没落）。


_AUDIT_STAGE = "review"
_MARKER_PREFIX = "public output span neutralised"
_SENDER_ID = "u-auditrow-1"
_GROUP_ID = "g-auditrow-1"
# TG 频道侧的夹具会话号（⑦ 那一节用；负数是 Telegram 超级群/频道的常规形态）。
_CHANNEL_ID = "-1001234567890"
# 出站字节基线：F-12 之前实测＝`32fd522029e8`（英文月日那半段也被涂掉），
# F-12 之后现算复录＝下面这枚（只有中文词界碰撞那一处被涂）。复录命令＝本文件的
# `test_downgrade_outbound_bytes_are_the_measured_baseline` 跑一遍取断言里的实得值。
_BODY_SHA_BASELINE = "748478a0a76d"


class _RecordingAudit:
    """内存审计桩：只记账，不落盘。"""

    def __init__(self) -> None:
        self.rows: list[object] = []

    def append(self, record: object) -> None:
        self.rows.append(record)

    def review_rows(self) -> list[object]:
        return [row for row in self.rows if getattr(row, "stage", "") == _AUDIT_STAGE]


def _message(scope: SessionType) -> IncomingMessage:
    if scope is SessionType.GROUP:
        return IncomingMessage(
            platform="qq", adapter="onebot", bot_id="10000",
            session_id=f"group:{_GROUP_ID}", session_type=SessionType.GROUP,
            sender_id=_SENDER_ID, group_id=_GROUP_ID,
            plain_text="你好", mentions_bot=True,
        )
    if scope is SessionType.CHANNEL:
        # TG 频道那一侧的会话形态（用户 2026-10-06 裁「频道＝群侧」）：`channel_<chat.id>`
        # 键形、无 group_id。键形只当夹具数据用，判据一律走契约字段 `session_type`。
        return IncomingMessage(
            platform="telegram", adapter="onebot", bot_id="10000",
            session_id=f"channel:{_CHANNEL_ID}", session_type=SessionType.CHANNEL,
            sender_id=_SENDER_ID, plain_text="你好", mentions_bot=True,
        )
    return IncomingMessage(
        platform="qq", adapter="onebot", bot_id="10000",
        session_id=f"private:{_SENDER_ID}", session_type=SessionType.PRIVATE,
        sender_id=_SENDER_ID, plain_text="你好",
    )


def _drive_pipeline(result: CapabilityResult, scope: SessionType) -> tuple[object, _RecordingAudit, InMemorySendQueue]:
    """把 `result` 走一遍**真管线**（`handle_async` → `_complete` → review）。"""

    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)

    async def _capability(*_args: object) -> CapabilityResult:
        return result

    receipt = asyncio.run(pipeline.handle_async(_message(scope), _capability, "bot.chat"))
    return receipt, audit, queue


def _outbound_text(queue: InMemorySendQueue) -> str:
    return "".join(str(getattr(r.content, "text_fallback", "")) for r in queue.sent_requests)


def _span() -> str:
    """命中那一段（运行时从模块自己的词面取，本文件不抄清单）。"""
    return _matched_span(_BODY)


def test_group_downgrade_writes_a_review_audit_row() -> None:
    receipt, audit, queue = _drive_pipeline(_colliding_result(), SessionType.GROUP)

    assert receipt.state is ReceiptState.SENT, receipt.state
    rows = audit.review_rows()
    assert len(rows) == 1, f"降级没进审计行：全部行={[(r.stage, r.event) for r in audit.rows]}"
    row = rows[0]
    assert row.event == "rewrite"
    assert _MARKER_PREFIX in row.private_debug, row.private_debug
    for label, _pattern in _hits(_BODY):
        assert label in row.private_debug, f"规则名 {label} 没进审计行"
    assert queue.sent_requests, "降级消息本身也得真出门"


def test_downgrade_audit_row_is_structural_not_reply_text() -> None:
    receipt, audit, _queue = _drive_pipeline(_colliding_result(), SessionType.GROUP)

    row = audit.review_rows()[0]
    detail = f"{row.private_debug}|{row.public_message}"
    span = _span()
    assert span, "取不到命中词面 ⇒ 本例空跑"
    assert span not in detail, "命中的那一段是回复原文，审计行不许落它"
    assert reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER not in detail
    assert _SENDER_ID not in detail and _GROUP_ID not in detail
    assert row.public_message == "", "降级正文不外传：出门的是消息本身，不是审计行"
    # 计数进了审计行（结构化事实之一）；改名会让它静吃 ⇒ 当场判数。
    match = re.search(r"neutralised=(\d+)", row.private_debug)
    assert match, row.private_debug
    assert int(match.group(1)) == len(_hits(_BODY)), row.private_debug
    assert "scope=group" in row.private_debug, row.private_debug
    assert receipt.state is ReceiptState.SENT


def test_private_scope_still_writes_no_review_row_and_keeps_every_byte() -> None:
    """私聊那一支本来就不跑内容面 ⇒ 新行一条不许多，正文一字不许改。"""
    result = _colliding_result()
    _receipt, audit, queue = _drive_pipeline(result, SessionType.PRIVATE)

    assert audit.review_rows() == [], "给本来不筛的私聊面加了审计行＝改了行为"
    outbound = _outbound_text(queue)
    assert _hits(outbound), "私聊正文被中和了＝字节不许动"
    assert reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER not in outbound
    assert result.body == _BODY
    assert result.text_parts == [_PARA_HEADLINE, _PARA_COLLISION_CN]


def test_group_clean_output_writes_no_review_row() -> None:
    """没命中就不许有行：新腿只在真降级时出声。"""
    clean_body = "潮汐窗口在四点前后，记得带伞。"
    assert not _hits(clean_body)
    _receipt, audit, _queue = _drive_pipeline(
        _result(body=clean_body, text_parts=None, prefix_parts=[], images=[]),
        SessionType.GROUP,
    )

    assert audit.review_rows() == []


@pytest.mark.parametrize("field", ("images", "audio", "video", "files", "actions"))
def test_media_carrier_block_disposition_is_unchanged(field: str) -> None:
    """③那一手的管线面：BLOCK 的**处置与审计行**一字不变（只多不许换、只一行为准）。"""
    body = "潮汐窗口在四点前后。"
    result = _result(
        body=body,
        kind="mixed",
        text_parts=None,
        prefix_parts=[],
        **{field: [{"file": "payload.bin", "caption": _PARA_COLLISION_CN}]},
    )
    receipt, audit, queue = _drive_pipeline(result, SessionType.GROUP)

    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "reviewer"
    assert queue.sent_requests == [], "BLOCK 却被提交了"
    assert result.body == body, "BLOCK 那一支不许动 result"

    rows = audit.review_rows()
    assert len(rows) == 1, [(r.stage, r.event) for r in audit.rows]
    row = rows[0]
    assert row.event == "block"
    assert row.public_message == receipt.public_message
    labels = [label for label, _pattern in _hits(_PARA_COLLISION_CN)]
    assert row.private_debug == "; ".join(labels), row.private_debug
    assert _MARKER_PREFIX not in row.private_debug
    assert _span() not in row.private_debug


def test_span_only_message_block_disposition_is_unchanged() -> None:
    """②那一手的管线面：整条就是违规内容 ⇒ 照旧 BLOCK，审计行形态一字不变。"""
    span = _span()
    assert span, "取不到命中词面 ⇒ 本例空跑"
    receipt, audit, queue = _drive_pipeline(
        _result(body=span, text_parts=None, prefix_parts=[], images=[]),
        SessionType.GROUP,
    )

    assert receipt.state is ReceiptState.BLOCKED
    assert queue.sent_requests == []
    rows = audit.review_rows()
    assert len(rows) == 1, [(r.stage, r.event) for r in audit.rows]
    assert rows[0].event == "block"
    assert rows[0].private_debug == "; ".join(label for label, _ in _hits(span))
    assert "neutralised=" not in rows[0].private_debug


def test_downgrade_outbound_bytes_are_the_measured_baseline() -> None:
    _receipt, _audit, queue = _drive_pipeline(_colliding_result(), SessionType.GROUP)
    outbound = _outbound_text(queue)

    assert hashlib.sha256(outbound.encode("utf-8")).hexdigest()[:12] == _BODY_SHA_BASELINE
    for fragment in _UNTOUCHED_FRAGMENTS:
        assert fragment in outbound


def test_privacy_override_after_downgrade_still_yields_exactly_one_row() -> None:
    """降级后又撞上隐私面（PERSONAL/CREDENTIALED 进群）⇒ 事件名被改写成
    `move_private`、`approved` 转假 ⇒ 只准有**一枚** review 行：新行按
    `approved 且 action is REWRITE` 让路，绝不与 BLOCK 那一支双记。"""
    result = _colliding_result().model_copy(update={"privacy_level": PrivacyLevel.PERSONAL})
    receipt, audit, _queue = _drive_pipeline(result, SessionType.GROUP)

    rows = audit.review_rows()
    assert len(rows) == 1, [(r.stage, r.event) for r in audit.rows]
    assert rows[0].event == "move_private", rows[0].event
    assert "neutralised=" not in rows[0].private_debug
    assert receipt.state is ReceiptState.BLOCKED


# ================================================== ⑦ 公共空间归侧：频道与群同侧（2026-10-06 裁定）
#
# 改前实测：出站内容闸的作用域判据是 `target_scope is SessionType.GROUP` **单值**，
# `channel` 落不进那一支 ⇒ 频道轮里 `_PUBLIC_OUTPUT_UNSAFE` 命中面**一个字都不涂**、
# 原样出门（现算证据＝下面 `test_a_channel_turn_is_scrubbed…` 改前必红）。
# 用户 2026-10-06 的裁定＝Telegram 频道（`channel`）与群（`group`）**同侧**：都是
# 「旁人也在看」的公共空间。这一格已在轴心落地
# （`domains/chat_reply/runtime/content_route.py` 的 `PUBLIC_SPACE_SESSION_TYPES` /
# `is_public_space_session`，管着描写档写腿角色门、描写钉会话分桶、样式表选表三处），
# 本节把它接进出站涂销那条腿。
#
# 🔴 方向只有**变严**：本节的私聊／控制台／邮件三面断言钉的是「一字不改」，
# 频道那一面钉的是「和群一样涂销」。词面清单、命中判据、BLOCK 的两种退回情形
# 一枚都没动——动的是「哪些会话过这道闸」。
# 🔴 判据只准转述中央那把尺；在 reviewer 里再写一份 `in {"group", "channel"}` ＝
# 第二把尺（形状锁 `test_the_scrub_gate_transcribes_the_one_public_space_ruler` 拦它）。

#: 中央判据的名字（唯一出处＝`content_route.is_public_space_session`）。本节只按名字
#: 断言「转述了它」，**不抄它的成员表**——抄成员表就是本波要防的那第二把尺。
_PUBLIC_RULER = "is_public_space_session"
_REVIEWER_SRC = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "render"
    / "reviewer.py"
)


def test_a_channel_turn_is_scrubbed_the_same_way_a_group_turn_is() -> None:
    """核心 RED：频道轮 + 群侧会涂销的那一类句子 ⇒ 那一处必须被涂掉、其余照发。"""
    result = _result()
    assert _hits(_BODY), "夹具本身必须真的命中一枚词面，否则本例是空跑"

    review = review_capability_result(result, _decision(SessionType.CHANNEL))

    assert review.approved is True, "频道命中被整条吃掉了：改法应当是逐段涂销，不是拦死"
    assert review.action is ReviewAction.REWRITE, (
        f"频道轮没进公共空间那一支（action={review.action.value}）＝频道仍不过这道闸"
    )
    assert not _hits(review.safe_text), "频道正文里的命中面原样出门了"
    for fragment in _UNTOUCHED_FRAGMENTS:
        assert fragment in review.safe_text, f"清白的其余内容被一起吃掉了：{fragment}"
    assert reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER in review.safe_text
    assert any(
        "public output span neutralised" in reason for reason in review.reasons
    ), review.reasons


def test_channel_parts_and_media_disposition_mirror_the_group_leg() -> None:
    """频道那一侧的**部件面与媒体面**也要和群一致：文字部件就地涂销、清白媒体不丢、
    命中落在改不掉的媒体载荷里时退回 BLOCK（两种退回情形一条都没放宽）。"""
    parts_result = _colliding_result()
    review = review_capability_result(parts_result, _decision(SessionType.CHANNEL))

    assert review.approved is True, review.reasons
    parts = parts_result.text_parts or []
    assert len(parts) == 2, "部件数量不得因涂销而减少"
    assert parts[0] == _PARA_HEADLINE, "清白的部件被改了"
    assert not any(_hits(part) for part in parts)
    prefixes = parts_result.prefix_parts or []
    assert len(prefixes) == 1
    assert not _hits(str(prefixes[0].get("text") or ""))
    assert parts_result.images == [{"file": "tide.png", "caption": _PARA_TAIL}]

    span = _matched_span(_BODY)
    assert span, "取不到命中词面 ⇒ 本例空跑"
    blocked = review_capability_result(
        _result(body=span, text_parts=None, prefix_parts=[], images=[]),
        _decision(SessionType.CHANNEL),
    )
    assert blocked.approved is False, "整条就是违规内容时频道不许放行（判据被放宽了）"
    assert blocked.action is ReviewAction.BLOCK

    for field in ("images", "audio", "video", "files", "actions"):
        media_result = _result(
            body="潮汐窗口在四点前后。",
            kind="mixed",
            **{field: [{"file": "payload.bin", "caption": _PARA_COLLISION_CN}]},
        )
        media_review = review_capability_result(media_result, _decision(SessionType.CHANNEL))
        assert media_review.approved is False, f"{field} 载荷里的命中面在频道被放行了"
        assert media_review.action is ReviewAction.BLOCK


@pytest.mark.parametrize("scope", [SessionType.GROUP, SessionType.CHANNEL])
def test_both_public_space_scopes_run_the_same_gate(scope: SessionType) -> None:
    """同侧＝**同一个动作同一个记号**，不是各写一套：两面的处置逐项相等。"""
    review = review_capability_result(_result(), _decision(scope))

    assert review.approved is True, review.reasons
    assert review.action is ReviewAction.REWRITE
    assert not _hits(review.safe_text)
    assert reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER in review.safe_text
    assert [r for r in review.reasons if "neutralised" in r], review.reasons


@pytest.mark.parametrize(
    "scope",
    [SessionType.PRIVATE, SessionType.CONSOLE, SessionType.EMAIL],
)
def test_non_public_space_scopes_still_keep_every_byte(scope: SessionType) -> None:
    """私聊／控制台／邮件三面**一字不改**：归侧只把频道拉进群那一侧，绝不把其它面推进涂销。"""
    result = _colliding_result()
    review = review_capability_result(result, _decision(scope))

    assert review.approved is True, review.reasons
    assert review.action is ReviewAction.ALLOW
    assert review.reasons == []
    assert review.safe_text == _BODY, "非公共空间正文被改了一个字都不算「不变」"
    assert result.text_parts == [_PARA_HEADLINE, _PARA_COLLISION_CN]
    assert _hits(review.safe_text), f"{scope.value} 被涂销＝给本来不筛的那一支加了道闸"


def test_channel_downgrade_writes_the_same_review_audit_row() -> None:
    """管线面（跑真 `_complete`）：频道降级落在与群**同一条**审计通道里，
    `scope=` 那一枚如实报 `channel`（结构化事实，不是散文）。"""
    receipt, audit, queue = _drive_pipeline(_colliding_result(), SessionType.CHANNEL)

    assert receipt.state is ReceiptState.SENT, receipt.state
    rows = audit.review_rows()
    assert len(rows) == 1, f"频道降级没进审计行：全部行={[(r.stage, r.event) for r in audit.rows]}"
    assert rows[0].event == "rewrite"
    assert _MARKER_PREFIX in rows[0].private_debug, rows[0].private_debug
    assert "scope=channel" in rows[0].private_debug, rows[0].private_debug
    assert _span() not in rows[0].private_debug, "命中的那一段是回复原文，审计行不许落它"
    outbound = _outbound_text(queue)
    assert queue.sent_requests, "频道降级消息本身也得真出门"
    assert not _hits(outbound), "频道出站正文里命中面没被涂销"
    assert reviewer_module._PUBLIC_OUTPUT_SPAN_PLACEHOLDER in outbound


def test_the_scrub_gate_transcribes_the_one_public_space_ruler() -> None:
    """形状锁：出站涂销那道闸只准**转述**中央判据，不许在 reviewer 里再长一把尺。

    抄一份 `{"group", "channel"}` ＝第二把尺（本仓的门与裁定都不认）；自己 `def`
    一枚同名判据＝第二真身。三面都钉：引到了、没另立、没重抄成员表。
    """
    src = _REVIEWER_SRC.read_text(encoding="utf-8")

    assert f"{_PUBLIC_RULER}(" in src, f"reviewer 没调用中央那把尺 `{_PUBLIC_RULER}`"
    assert "content_route" in src, (
        f"reviewer 里的 `{_PUBLIC_RULER}` 不是从轴心 `content_route` 取的那一把"
    )
    assert f"def {_PUBLIC_RULER}" not in src, "reviewer 里自己造了一枚同名判据＝第二真身"
    assert '{"group", "channel"}' not in src, "reviewer 里重抄了公共空间的成员表＝第二把尺"
    assert "PUBLIC_SPACE_SESSION_TYPES" not in src, "reviewer 直接读中央的成员表而不是问判据"

