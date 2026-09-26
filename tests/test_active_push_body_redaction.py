"""S-OUTBOUND-SCRUB-EXT：主动投递唯一出口的统一正文打码（AGENTS 铁律 3 的主动投递腿）。

为什么要有这个件（第 17 项现算坐实的漏口）：`domains/render/renderer.py` 的出站
咽喉只罩能力回复路（生产调用点 pipeline.py 两处）；提醒 / cookie 到期 / 群摘要 /
日常助理 / 等待回执 / 紧急信息六族在能力层各自拼好正文、直接进
`submit_active_push`，**不经 renderer** ⇒ 打码散点、缺省无罩。本件钉五条：

① 脏正文（盘符路径 / `BOT_XXX=` / `sk-`）过出口必被洗，其余文字逐字节保留；
② 洗的行动作**就地**改写（队列捕获 `is` 调用方对象）——提醒族的 `or request`
   兜底与回执族的内联投递继续用调用方引用发正文，只换副本这两条腿永远漏洗；
③ 零命中 ⇒ 一字段不动、一赋值不发（`content_ref` dict 同一对象 ⇒ 现役行为与
   既有测试逐字节同形）；
④ 幂等：洗两次与洗一次逐字节相等（尺 `redact_local_secrets` 自身幂等）；
⑤ 只洗文本键：`file` / `url` 媒体定位符逐字节不动，mixed 形态构出的图片/语音段
   在传输层仍可达（`_segments_from_rendered_output` 实走一遍）。

另钉「一把尺」结构锁：monkeypatch 本模块 import 进来的 `redact_local_secrets`
名字即改变出口行为 ⇒ 证明出口用的是真身那把尺，不是自抄的第二把。

全离线：假队列 + 注入时钟 + tmp_path（不落任何真实队列文件）；零网络。

    BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=<仓库外> \\
        python -m pytest tests/test_active_push_body_redaction.py \\
        -p no:cacheprovider --basetemp=<仓库外> -q
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

# 脏样本：三种形态各带独立前后缀，「其余文字逐字节保留」按字面判。
DIRTY_PATH_TEXT = "提醒：下午三点开会。详见 C:\\Users\\x\\桌面\\纪要.txt，别迟到"
DIRTY_SECRET_TEXT = "配置 BOT_TOKEN=abcd1234efgh 后即可，备用 sk-abcdefghijkl"
CLEAN_TEXT = "到点啦，今天也记得喝水。"


class CapturingQueue:
    """假队列：记录抵达的那只对象本体（身份可判）并回 QUEUED 回执。"""

    def __init__(self) -> None:
        self.requests: list[SendRequest] = []

    def submit(self, send_request: SendRequest, **kwargs: Any) -> DeliveryReceipt:
        assert not kwargs, "关闭态必须裸 submit（与现役同形），不得带关键字"
        self.requests.append(send_request)
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.QUEUED,
            transport="memory",
            public_message="queued",
        )


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[tuple[str, datetime]] = []

    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        del subject_key, since_utc
        return 0

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        self.rows.append((subject_key, now_utc))

    def prune(self, *, before_utc: datetime) -> int:
        del before_utc
        return 0


def _request(
    *,
    text_fallback: str,
    content_ref: dict[str, Any],
    content_type: str = "text",
    capability_id: str = "bot.reminder",
    request_id: str = "req-scrub-1",
    dedupe_key: str = "emg:qq:scrub-1:g-1:2026-09-26",
) -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id="group:g-1",
        target_scope=SessionType.GROUP,
        target_id="g-1",
        capability_id=capability_id,
        content=RenderedOutput(
            request_id=request_id,
            content_type=content_type,
            content_ref=content_ref,
            text_fallback=text_fallback,
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy=SendPolicy.QUEUED,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"scrub:{capability_id}:g-1",
        privacy_level=PrivacyLevel.PUBLIC,
        persona_profile_id="default",
    )


def _gate(*, enabled: bool = False):
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(
        OutboundGateSettings(enabled=enabled),
        quiet_settings=QuietHoursSettings(
            enabled=False,
            start_time="00:00",
            end_time="06:00",
            timezone_name="UTC",
            session_types=["group", "private"],
        ),
        store=FakeStore(),
        clock=lambda: FIXED_NOW,
        audit_logger=InMemoryAuditLogger(),
    )


def _push(request: SendRequest, queue: CapturingQueue, gate: Any = None) -> Any:
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        submit_active_push,
    )

    return submit_active_push(queue, request, gate or _gate(), now=FIXED_NOW)


# ------------------------------------------------------------------------ 锁①
def test_reminder_family_body_scrubbed_rest_survives() -> None:
    """提醒形（正文只在 text_fallback，content_ref={}）：盘符必洗、其余逐字节保留。"""
    queue = CapturingQueue()
    request = _request(text_fallback=DIRTY_PATH_TEXT, content_ref={})

    outcome = _push(request, queue)

    assert outcome.verdict.action == "allow"
    assert len(queue.requests) == 1
    shipped = queue.requests[0].content.text_fallback
    assert "C:\\Users" not in shipped and "盘符" not in shipped
    # 其余文字逐字节：期望值独立用真身尺复算（不 import 出口内部实现算期望）。
    assert shipped == redact_local_secrets(DIRTY_PATH_TEXT)
    assert shipped.startswith("提醒：下午三点开会。详见 ")
    assert shipped.endswith("，别迟到")
    # content_ref={} 零命中 ⇒ 同一只 dict，一字节没动。
    assert queue.requests[0].content.content_ref == {}


def test_secret_forms_scrubbed_in_text_key_and_fallback() -> None:
    """紧急/回执形（text 与 text_fallback 同串）：BOT_XXX= 与 sk- 两形态同洗。"""
    queue = CapturingQueue()
    request = _request(
        text_fallback=DIRTY_SECRET_TEXT,
        content_ref={"text": DIRTY_SECRET_TEXT},
        capability_id="bot.emergency_info",
    )

    _push(request, queue)

    content = queue.requests[0].content
    expected = redact_local_secrets(DIRTY_SECRET_TEXT)
    assert content.content_ref["text"] == expected
    assert content.text_fallback == expected
    assert "abcd1234efgh" not in content.text_fallback
    assert "BOT_TOKEN=<" in content.text_fallback  # 键名保留、值成占位（尺的现役语义）


# ------------------------------------------------------------------------ 锁②
def test_scrub_is_in_place_for_inline_delivery_legs() -> None:
    """就地改写：队列捕获 `is` 调用方对象 ⇒ 提醒 `or request` 兜底与回执内联
    投递此后发的正文与队列落库行是同一份洗过的文本（副本设计在这两条腿必漏）。"""
    queue = CapturingQueue()
    request = _request(text_fallback=DIRTY_PATH_TEXT, content_ref={})

    _push(request, queue)

    assert queue.requests[0] is request
    assert request.content.text_fallback == redact_local_secrets(DIRTY_PATH_TEXT)


# ------------------------------------------------------------------------ 锁③
def test_clean_text_returns_untouched_objects() -> None:
    """零命中 ⇒ 不复制、不赋值：出口过完后 content_ref 仍是**同一只 dict**。

    身份基线取「模型构造完之后」落在字段上的那只（pydantic 构造期自带一次
    copy，那是 contracts 的既有语义，与本席无关；本席判的是出口有没有再动）。
    """
    queue = CapturingQueue()
    request = _request(text_fallback=CLEAN_TEXT, content_ref={"text": CLEAN_TEXT})
    ref_before = request.content.content_ref
    fallback_before = request.content.text_fallback

    _push(request, queue)

    assert queue.requests[0] is request
    # 没有任何 model_copy / dict 重建 / 字段赋值：两只容器对象都是原对象。
    assert request.content.content_ref is ref_before
    assert request.content.text_fallback is fallback_before
    assert request.content.content_ref["text"] == CLEAN_TEXT


# ------------------------------------------------------------------------ 锁④
def test_scrub_idempotent_second_pass_changes_nothing() -> None:
    """洗两次与洗一次逐字节相等（尺自身幂等 ⇒ 出口可安全重过）。"""
    queue = CapturingQueue()
    request = _request(
        text_fallback=DIRTY_PATH_TEXT,
        content_ref={"text": DIRTY_PATH_TEXT, "chunks": [DIRTY_SECRET_TEXT]},
    )

    _push(request, queue)
    first_fallback = request.content.text_fallback
    first_ref = dict(request.content.content_ref)
    first_chunks = list(first_ref["chunks"])

    outcome2 = _push(request, queue)  # 同键第二次：队列幂等由生产侧管，这里只看正文
    assert outcome2.verdict.action == "allow"
    assert request.content.text_fallback == first_fallback
    assert request.content.content_ref == first_ref
    assert request.content.content_ref["chunks"] == first_chunks


# ------------------------------------------------------------------------ 锁⑤
def test_media_locators_survive_and_segments_stay_reachable(tmp_path) -> None:
    """parts 形：`file`/`url` 定位符逐字节不动，构段实走一遍证明图片/语音仍可达；
    部件的人读文本键（text/caption）照洗。

    语音部件给**真实存在的 tmp_path 文件**：record/video/file 三面在构段期有
    M-38 死引用闸（`_resolve_local_file_ref` 对不存在的绝对路径直接摘段），
    拿假路径断「可达」会撞上与本席无关的另一道门。image 面维持既有透传
    （onebot.py `_image_segment` 注释），死引用也构得出段。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        _segments_from_rendered_output,
    )

    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"RIFF" + b"\0" * 44)  # 非空文件即算「存活」，不需真 WAV。
    image_ref = "file:///C:/Users/Public/pic.png"
    record_ref = str(voice)
    dirty_caption = f"配文见 {image_ref} 与 C:\\a\\b.txt"
    queue = CapturingQueue()
    image_part: dict[str, Any] = {"type": "image", "file": image_ref}
    record_part: dict[str, Any] = {"type": "record", "file": record_ref}
    text_part: dict[str, Any] = {"type": "text", "text": dirty_caption}
    parts_before = [image_part, record_part, text_part]
    request = _request(
        text_fallback="回退文本 C:\\a\\b.txt",
        content_ref={"parts": parts_before},
        content_type="mixed",
        capability_id="bot.randpic",
    )

    _push(request, queue)

    shipped_parts = request.content.content_ref["parts"]
    # 未命中的部件保持**原对象**（零扰动）；命中的只重建那一只 dict。
    assert shipped_parts[0] is image_part
    assert shipped_parts[1] is record_part
    assert shipped_parts[0]["file"] == image_ref
    assert shipped_parts[1]["file"] == record_ref
    assert shipped_parts[2]["text"] == redact_local_secrets(dirty_caption)
    assert "C:\\a\\b.txt" not in shipped_parts[2]["text"]
    # 传输层实走：图片/语音段仍按原定位符构出（可达），文本段发的是洗过的文。
    segments = _segments_from_rendered_output(
        content_type="mixed",
        content_ref=request.content.content_ref,
        text_fallback=request.content.text_fallback,
        request_id=request.request_id,
    )
    types = [str(seg.get("type")) for seg in segments]
    assert "image" in types and "record" in types
    image_seg = next(seg for seg in segments if str(seg.get("type")) == "image")
    assert image_seg["data"]["file"] == image_ref


def test_chunks_scrubbed_per_chunk_and_fallback_follows() -> None:
    """chunks 形（渲染层混排回落同款）：逐条洗、text_fallback 同洗。"""
    dirty_a = "第一段 C:\\Users\\secret\\a.md 结束"
    dirty_b = "第二段 sk-abcdefgh1234567 结束"
    queue = CapturingQueue()
    request = _request(
        text_fallback=f"{dirty_a}\n\n{dirty_b}",
        content_ref={"chunks": [CLEAN_TEXT, dirty_a, dirty_b]},
        content_type="chunks",
    )

    _push(request, queue)

    chunks = request.content.content_ref["chunks"]
    assert chunks[0] == CLEAN_TEXT
    assert chunks[1] == redact_local_secrets(dirty_a)
    assert chunks[2] == redact_local_secrets(dirty_b)
    assert request.content.text_fallback == redact_local_secrets(
        f"{dirty_a}\n\n{dirty_b}"
    )


def test_open_gate_allow_path_scrubs_once() -> None:
    """开闸态（allow + store 记账）同样先洗再过门：打码不是闸的管辖、两态都在。"""
    queue = CapturingQueue()
    gate = _gate(enabled=True)
    request = _request(text_fallback=DIRTY_PATH_TEXT, content_ref={})

    outcome = _push(request, queue, gate=gate)

    assert outcome.verdict.action == "allow"
    assert request.content.text_fallback == redact_local_secrets(DIRTY_PATH_TEXT)
    assert len(queue.requests) == 1


def test_exit_uses_the_single_shared_ruler(monkeypatch) -> None:
    """一把尺结构锁：monkeypatch 本模块 import 进来的 `redact_local_secrets`
    名字即改变出口行为 ⇒ 出口没有第二把自己抄的尺。"""
    import plugins.bot_unified_runtime.domains.transport.sender.outbound_gate as og

    calls: list[str] = []

    def _marker(text: str) -> str:
        calls.append(text)
        return "<尺被走过>"

    monkeypatch.setattr(og, "redact_local_secrets", _marker)
    queue = CapturingQueue()
    request = _request(text_fallback=DIRTY_PATH_TEXT, content_ref={"text": DIRTY_PATH_TEXT})

    _push(request, queue)

    assert calls, "出口根本没经过那把尺＝第二把尺或散点复辟"
    assert request.content.text_fallback == "<尺被走过>"
    assert request.content.content_ref["text"] == "<尺被走过>"
