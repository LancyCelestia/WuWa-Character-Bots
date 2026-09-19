"""S-08/Wave H 摘要层 S4（T123）：dedupe_key 内容维度 d 段 + ``-textfb`` 归位。

施工图=docs/design/media-digest-layer.md §3.2/§3.3/§5/§7-S4 + report-T120.md §五
移交清单。三层锁：

1. **pipeline d 段**（键=消息身份 ∧ 段类型 ∧ 内容摘要）：
   - 带 digest 的 rendered → ``dedupe_key`` 尾拼 ``:d=<16hex>``（对「record 部件
     digest 截短[:16] 有序拼接」再 sha256[:16]，防拼接歧义）；
   - 无 audio / 部件缺坏 digest 的请求 → 键与旧三元组**逐字节一致**（兼容硬锁；
     空串/占位伪造 digest 均禁，任一 record 部件缺 digest ⇒ 整段缺省）。
2. **part 载荷摘要内容维度**（S3 已落地，此处回归锁）：同路径不同 digest 的
   两 part → ``_payload_digest(_mixed_part_identity(part))`` 不同；同 part 重算
   恒等（幂等键前提）。
3. **``-textfb`` 归位**（worker）：子请求键 ``f"{原key}:textfb:{文本摘要[:16]}"``
   （「同父+同降级文本」内容寻址幂等）+ ``audit_tags`` 追加
   ``textfb_parent=<原行 record digest 截短[:16] 或 "-">``（台账归位，游离面闭合）。

全部离线（零网络零墙钟），管线侧惯例同 tests/test_a19_group_failure_notice.py、
worker 侧惯例同 tests/test_h_voice_delivery.py（R5 形态：retcode 白名单终态 +
W1 恰一次文本降级）。

离线运行：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_h_dedupe_content_key.py -q -p no:cacheprovider \\
      --basetemp="../ChatBot_Runtime/cache/t123"
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import pytest
from helpers.voice_queue_sim import (
    build_mixed_request,
    build_sqlite_queue,
    freeze_inline_retries,
    run_queue_rounds,
    sim_utc_now,
)

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    InMemorySendQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    _mixed_part_identity,
    _payload_digest,
)

# 全部用例共享的显式 now 基点（C4：禁止依赖墙钟，模块导入时固定一次）。
_BASE: datetime = sim_utc_now()

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_TEXT = "守岸人准备好了。"


def _d16(digests: list[str]) -> str:
    """d 段期望值（与 pipeline 侧同一算式：截短[:16] 有序拼接再 sha256[:16]）。"""
    return hashlib.sha256(
        "".join(digest[:16] for digest in digests).encode("utf-8")
    ).hexdigest()[:16]


def _text16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ==================== 管线侧：d 段组装 ====================


def _message(message_id: str = "msg-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id="private:user-1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        message_id=message_id,
        plain_text="说句话",
        mentions_bot=True,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _static_capability(result: CapabilityResult):
    def _run(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return result

    return _run


def _audio_result(message: IncomingMessage, audio: list[dict[str, Any]]) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="tts",
        body="守岸人准备好了。",
        send_policy=SendPolicy.IMMEDIATE,
        privacy_level=PrivacyLevel.PERSONAL,
        audio=audio,
    )


def _submit(pipeline: RuntimePipeline, message: IncomingMessage, result: CapabilityResult):
    pipeline.handle(message, _static_capability(result), "bot.chat")


def test_dedupe_key_gains_d_segment_when_record_has_digest() -> None:
    """带 digest 的 rendered → dedupe_key 尾拼 ``:d=<16hex>``（RED：现树无 d 段）。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    message = _message()

    _submit(pipeline, message, _audio_result(message, [
        {"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_A},
    ]))

    assert len(queue.sent_requests) == 1
    request = queue.sent_requests[0]
    assert request.dedupe_key == (
        f"bot.chat:private:user-1:msg-1:d={_d16([_DIGEST_A])}"
    )


def test_dedupe_key_multi_record_parts_redigest_ordered_list() -> None:
    """多 record 部件：对「digest 有序列表」再摘要（防拼接歧义）。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    message = _message()

    _submit(pipeline, message, _audio_result(message, [
        {"type": "record", "file": "tts-a.wav", "content_sha256": _DIGEST_A},
        {"type": "record", "file": "tts-b.wav", "content_sha256": _DIGEST_B},
    ]))

    request = queue.sent_requests[0]
    assert request.dedupe_key == (
        f"bot.chat:private:user-1:msg-1:d={_d16([_DIGEST_A, _DIGEST_B])}"
    )


def test_dedupe_key_byte_identical_without_audio() -> None:
    """无 audio 请求 → 键与旧三元组逐字节一致（兼容硬锁）。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    message = _message()

    _submit(pipeline, message, _audio_result(message, []))

    request = queue.sent_requests[0]
    assert request.dedupe_key == "bot.chat:private:user-1:msg-1"


def test_dedupe_key_byte_identical_when_record_lacks_digest() -> None:
    """record 部件缺 digest（含经 canonicalize 剥离的非法值）→ 键逐字节不变。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    # 逐消息区分 message_id：同键第二发会被队列 dedupe 吞（幂等语义本身正确）。
    message_a = _message("msg-1")
    message_b = _message("msg-2")

    # 非法 digest：canonicalize 剥离留痕、部件保命（恰两键）→ 等价缺 digest。
    _submit(pipeline, message_a, _audio_result(message_a, [
        {"type": "record", "file": "tts-x.wav", "content_sha256": "Z" * 64},
    ]))
    _submit(pipeline, message_b, _audio_result(message_b, [
        {"type": "record", "file": "tts-x.wav"},
    ]))

    assert len(queue.sent_requests) == 2
    assert queue.sent_requests[0].dedupe_key == "bot.chat:private:user-1:msg-1"
    assert queue.sent_requests[1].dedupe_key == "bot.chat:private:user-1:msg-2"


def test_dedupe_key_music_part_does_not_block_d_segment() -> None:
    """music/file 族无 digest 是设计事实（非「缺 digest」）：不阻断 record 的 d 段。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    message = _message()

    _submit(pipeline, message, _audio_result(message, [
        {"type": "music", "music_type": "netease", "music_id": "1"},
        {"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_A},
    ]))

    request = queue.sent_requests[0]
    assert request.dedupe_key == (
        f"bot.chat:private:user-1:msg-1:d={_d16([_DIGEST_A])}"
    )


def test_content_dedupe_suffix_all_or_nothing_over_record_parts() -> None:
    """任一 record 部件缺/坏 digest ⇒ 整段缺省（占位伪造禁）；非 record 不参与。"""
    # 函数内导入（RED 期该符号尚不存在，不拖垮同文件其余兼容锁的取证）。
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
        _content_dedupe_suffix,
    )

    def _rendered(parts: list[dict[str, Any]]) -> RenderedOutput:
        return RenderedOutput(
            request_id="r",
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback="",
        )

    # 缺 digest 与有 digest 混排 → 全有全无，键退化。
    assert _content_dedupe_suffix(_rendered([
        {"type": "record", "file": "a.wav"},
        {"type": "record", "file": "b.wav", "content_sha256": _DIGEST_A},
    ])) == ""
    # 非法值（非 64 hex 小写）同待遇。
    assert _content_dedupe_suffix(_rendered([
        {"type": "record", "file": "a.wav", "content_sha256": "A" * 64},
    ])) == ""
    # 无 record 部件 / 非 parts 形态 → 空串（forward/messages 等）。
    assert _content_dedupe_suffix(_rendered([
        {"type": "text", "text": "hi"},
    ])) == ""
    assert _content_dedupe_suffix(RenderedOutput(
        request_id="r",
        content_type="forward",
        content_ref={"messages": []},
        text_fallback="",
    )) == ""
    # 纯 record 全带合法 digest → d 段。
    assert _content_dedupe_suffix(_rendered([
        {"type": "record", "file": "a.wav", "content_sha256": _DIGEST_A},
    ])) == f":d={_d16([_DIGEST_A])}"


# ==================== part 载荷摘要内容维度（S3 回归锁） ====================


def test_part_payload_digest_separates_same_path_different_bytes() -> None:
    """同路径不同 digest 两 part → payload digest 不同（S4 验收②；S3 后应绿）。"""
    part_old = {"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_A}
    part_new = {"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_B}
    digest_old = _payload_digest(_mixed_part_identity(part_old))
    digest_new = _payload_digest(_mixed_part_identity(part_new))
    assert digest_old != digest_new
    # 幂等键前提：同一 part 重复计划恒同摘要。
    assert digest_old == _payload_digest(_mixed_part_identity(dict(part_old)))


# ==================== worker 侧：-textfb 归位 ====================


async def _run_textfb_case(
    tmp_path,
    monkeypatch,
    *,
    record_part: dict[str, Any],
    parent_key: str,
) -> list[Any]:
    """R5 形态（retcode 白名单终态 + W1 恰一次文本降级），记录全部途经请求。

    recording_transport 包住真身 ``send_onebot_v11``：台账记 SendRequest 本体
    （fb 子请求的 dedupe_key/audit_tags 只在请求对象上可见，bot API 台账看不到）。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        send_onebot_v11,
    )

    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    seen: list[Any] = []
    bot = _Bot()

    async def recording_transport(send_request):
        seen.append(send_request)
        return await send_onebot_v11(bot, send_request, timeout_seconds=0.3)

    request = build_mixed_request(
        "tx1",
        text=_TEXT,
        parts=[
            {"type": "text", "text": _TEXT},
            record_part,
        ],
        dedupe_key=parent_key,
    )
    queue.submit(request, now=_BASE)
    await run_queue_rounds(queue, recording_transport, rounds=3, base_now=_BASE)
    return seen


class _Bot:
    """最小 OneBot 桩：恒以 retcode 100 明确拒绝（SnowLuma failed dict 形态）。"""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def send_private_msg(self, *, user_id, message):
        self.calls.append(message)
        return {
            "status": "failed",
            "retcode": 100,
            "data": None,
            "wording": "simulated rejection 100",
        }

    async def send_group_msg(self, *, group_id, message):
        return await self.send_private_msg(user_id=group_id, message=message)


@pytest.mark.asyncio
async def test_textfb_key_content_addressed_and_parent_tag_with_digest(
    tmp_path, monkeypatch
) -> None:
    """带 digest 原行：fb 键=``{原key}:textfb:{文本摘要16}`` + tag=textfb_parent。"""
    seen = await _run_textfb_case(
        tmp_path,
        monkeypatch,
        record_part={"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_A},
        parent_key=f"cap:session:msg:d={_d16([_DIGEST_A])}",
    )
    fallbacks = [r for r in seen if r.request_id == "tx1-textfb"]
    assert len(fallbacks) == 1
    fb = fallbacks[0]
    assert fb.dedupe_key == (
        f"cap:session:msg:d={_d16([_DIGEST_A])}"
        f":textfb:{_text16(_TEXT)}"
    )
    assert f"textfb_parent={_DIGEST_A[:16]}" in fb.audit_tags


@pytest.mark.asyncio
async def test_textfb_key_and_parent_dash_without_digest(
    tmp_path, monkeypatch
) -> None:
    """无 digest 原行：fb 键仍内容寻址；tag 诚实落 "-"（不伪造）。"""
    seen = await _run_textfb_case(
        tmp_path,
        monkeypatch,
        record_part={"type": "record", "file": "tts-x.wav"},
        parent_key="cap:session:msg",
    )
    fallbacks = [r for r in seen if r.request_id == "tx1-textfb"]
    assert len(fallbacks) == 1
    fb = fallbacks[0]
    assert fb.dedupe_key == f"cap:session:msg:textfb:{_text16(_TEXT)}"
    assert "textfb_parent=-" in fb.audit_tags


@pytest.mark.asyncio
async def test_textfb_fires_exactly_once_and_record_not_redispatched(
    tmp_path, monkeypatch
) -> None:
    """恰一次语义保持：1 条 fatal 整发 + 1 条 fb 尝试；record 零重投（R5 判据）。"""
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = _Bot()
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        send_onebot_v11,
    )

    async def transport(send_request):
        return await send_onebot_v11(bot, send_request, timeout_seconds=0.3)

    request = build_mixed_request(
        "tx1",
        text=_TEXT,
        parts=[
            {"type": "text", "text": _TEXT},
            {"type": "record", "file": "tts-x.wav", "content_sha256": _DIGEST_A},
        ],
        dedupe_key="cap:session:msg",
    )
    queue.submit(request, now=_BASE)
    await run_queue_rounds(queue, transport, rounds=3, base_now=_BASE)

    assert len(bot.calls) == 2
    # 唯一 record 段只随首轮整发出现一次（fb 是纯文本，零 record 段）。
    record_segments = [
        seg
        for call in bot.calls
        for seg in call
        if str(seg.get("type")) == "record"
    ]
    assert len(record_segments) == 1
