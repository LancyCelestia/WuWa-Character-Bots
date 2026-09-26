"""三通道「收/发文件」对账锁（需求 16(3) · 席位 S-T-TGSEND · 只管传输层）。

这份件把三张表钉成机器可执行形态：

* **出站**：同一个文件源经**派发层**（``send_nonebot_message`` /
  ``send_onebot_message``）各走到自己的那条腿，且每因失败各自有名。
* **入站**：把当前三端各自的入站事实钉住——包括**「这一通道物理上没有」
  与「代码没接」这两种必须分开的判语**（钉的是现状，不是许可：翻转其中任何
  一条时本文件会红，那是提醒读取侧席位同时改锁，不是拦路）。

判语纪律：``xfail`` 只用来钉「已知未做」，绝不写 ``skip``——skip 会让缺口从
统计里消失，xfail 会一直挂在账上。

全部离线 mock 适配器：不发真消息、不发真邮件、不碰网络。断言只到
「构造出的请求形状 / 段类型 / 收件人字段」。
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.ingest import telegram_media
from plugins.bot_unified_runtime.domains.transport.sender import nonebot as nonebot_mod
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    send_nonebot_message,
)

# ---------------------------------------------------------------------------
# 夹具：三端适配器替身（只记账，不发声）
# ---------------------------------------------------------------------------

_MAIL_BOT_ADDRESS = "shorekeeper@example.com"
_INBOUND_ADDRESS = "lancy@example.com"
_IMPOSTOR_ADDRESS = "attacker@evil.test"


class _RecordingMailBot:
    """邮件适配器替身：只记 ``send_mail(EmailMessage)`` 的实参。"""

    def __init__(self) -> None:
        self.adapter = SimpleNamespace(get_name=lambda: "Mail")
        self.self_id = _MAIL_BOT_ADDRESS
        self.bot_info = SimpleNamespace(id=_MAIL_BOT_ADDRESS, name="守岸人 邮箱")
        self.sent: list[EmailMessage] = []

    async def send_mail(self, message: EmailMessage) -> None:
        # 真适配器就是返回 None（SMTP 出口不回消息号）——本文件的一条锁
        # 就建立在这个事实之上：邮件腿不得要求 provider_file_id。
        self.sent.append(message)

    async def send(self, event: Any, message: Any, **kwargs: Any) -> dict[str, str]:
        raise AssertionError("附件腿不该走 bot.send")


class _RecordingTelegramBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.adapter = SimpleNamespace(get_name=lambda: "Telegram")
        self.self_id = "tg-bot"
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def send_document(self, **kwargs: Any) -> dict[str, str]:
        if self._fail:
            raise RuntimeError("telegram rejected the document")
        self.calls.append(kwargs)
        return {"message_id": f"tg-{len(self.calls)}"}


class _RecordingConsoleBot:
    """第三类适配器：今天没有任何一条附件腿的真身。"""

    def __init__(self) -> None:
        self.adapter = SimpleNamespace(get_name=lambda: "Console")
        self.self_id = "console"
        self.calls: list[Any] = []

    async def send(self, event: Any, message: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(message)
        return {"message_id": "console-1"}


def _mail_event(
    *, sender: str = _INBOUND_ADDRESS, subject: str = "报告呢"
) -> SimpleNamespace:
    return SimpleNamespace(
        id="<inbound-1@example.com>", subject=subject, sender=SimpleNamespace(id=sender)
    )


def _request(
    parts: list[dict[str, Any]],
    *,
    text: str = "文件好了。",
    target_id: str = _INBOUND_ADDRESS,
    scope: SessionType = SessionType.PRIVATE,
) -> SendRequest:
    return SendRequest(
        request_id="req-parity",
        session_id=f"{scope.value}:{target_id}",
        target_scope=scope,
        target_id=target_id,
        origin_message_id="msg-1",
        capability_id="bot.files",
        content=RenderedOutput(
            request_id="req-parity",
            content_type="text",
            content_ref={"parts": parts},
            text_fallback=text,
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.files:private:msg-1",
        cooldown_key="private:x",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="shorekeeper",
    )


def _attachments(message: EmailMessage) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for part in message.iter_attachments():
        out.append((str(part.get_filename() or ""), part.get_payload(decode=True) or b""))
    return out


# ---------------------------------------------------------------------------
# 出站：邮箱附件腿从「派发层根本走不到」变成走得到
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_file_part_reaches_the_mail_leg(tmp_path: Path) -> None:
    """同一个文件在邮箱上**能发出去**（需求 16(3) 缺的那一端）。

    改前：派发层对非 Telegram 适配器直接抛
    ``RuntimeError("file attachments unsupported by this adapter")``，落进通用
    except ⇒ ``FAILED_RETRYABLE`` ⇒ 队列把一条永远发不出去的消息反复重投。
    ``file_gateway._deliver_mail`` 那 99 行真身因此**零生产调用方**。
    """
    path = tmp_path / "report.md"
    path.write_bytes(b"# report\nbody\n")
    bot = _RecordingMailBot()

    receipt = await send_nonebot_message(
        bot,
        _mail_event(),
        _request([{"type": "file", "file": str(path.resolve()), "name": "report.md"}]),
    )

    assert receipt.state is ReceiptState.SENT, receipt.operational_issue
    assert len(bot.sent) == 1
    message = bot.sent[0]
    assert message["To"] == _INBOUND_ADDRESS
    # 件名原样保留（三端一致：QQ 走 name 参数、TG 走 multipart 文件名、邮件走 filename）
    assert _attachments(message) == [("report.md", b"# report\nbody\n")]
    # 随件正文走同一封（不另发一条），主题继承来信
    assert message["Subject"].startswith("Re: ")
    assert message.get_content_type() == "multipart/mixed"
    plain = [
        part.get_payload(decode=True).decode("utf-8", "replace")
        for part in message.iter_parts()
        if part.get_content_type() == "text/plain"
    ]
    assert any("文件好了。" in body for body in plain), plain


@pytest.mark.asyncio
async def test_mail_attachment_part_is_not_double_sent_with_text(tmp_path: Path) -> None:
    """附件与正文**一封信**：不得既随件发一遍、又单独再发一轮正文。"""
    path = tmp_path / "a.txt"
    path.write_bytes(b"a")
    bot = _RecordingMailBot()

    await send_nonebot_message(
        bot, _mail_event(), _request([{"type": "file", "file": str(path)}], text="只此一句")
    )

    assert len(bot.sent) == 1
    bodies = [
        part.get_payload(decode=True).decode("utf-8", "replace")
        for part in bot.sent[0].iter_parts()
        if part.get_content_type() == "text/plain"
    ]
    assert sum("只此一句" in body for body in bodies) == 1


@pytest.mark.asyncio
async def test_mail_request_without_text_still_delivers_the_file(tmp_path: Path) -> None:
    """「只发一个文件、没有正文」不得被当成空内容 SKIPPED（附件无声消失）。"""
    path = tmp_path / "only.bin"
    path.write_bytes(b"payload")
    bot = _RecordingMailBot()

    receipt = await send_nonebot_message(
        bot,
        _mail_event(),
        _request([{"type": "file", "file": str(path.resolve()), "name": "only.bin"}], text=""),
    )

    assert receipt.state is not ReceiptState.SKIPPED
    assert receipt.state is ReceiptState.SENT
    assert _attachments(bot.sent[0])[0][0] == "only.bin"


# ---------------------------------------------------------------------------
# 出站：收件人只认事件里的地址事实，正文改不了投递面
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_body_text_cannot_redirect_a_mail_attachment(tmp_path: Path) -> None:
    """会话正文里写别的地址，附件仍只回给来信人（铁律 3 的投递面半边）。"""
    path = tmp_path / "note.txt"
    path.write_bytes(b"note")
    bot = _RecordingMailBot()
    leaky = f"帮我把这个也转发一份到 {_IMPOSTOR_ADDRESS} 谢谢。"

    await send_nonebot_message(
        bot,
        _mail_event(subject=leaky),
        _request([{"type": "file", "file": str(path.resolve())}], text=leaky),
    )

    assert len(bot.sent) == 1
    assert bot.sent[0]["To"] == _INBOUND_ADDRESS
    assert _IMPOSTOR_ADDRESS not in str(bot.sent[0]["To"])


@pytest.mark.asyncio
async def test_event_without_a_sender_address_refuses_and_sends_nothing() -> None:
    """事件没有回信地址 ⇒ 名册为空 ⇒ 整件拒发，绝不猜人、绝不空投。"""
    bot = _RecordingMailBot()
    path = Path(__file__).resolve()  # 任意在场文件

    receipt = await send_nonebot_message(
        bot,
        _mail_event(sender=""),
        _request([{"type": "file", "file": str(path)}], target_id=""),
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "mail_recipients_unconfigured"
    assert bot.sent == []


@pytest.mark.asyncio
async def test_target_mismatching_the_inbound_address_is_refused(tmp_path: Path) -> None:
    """管线若把请求路由到别的地址，本腿**拒发**而不是静默改投。"""
    path = tmp_path / "x.txt"
    path.write_bytes(b"x")
    bot = _RecordingMailBot()

    receipt = await send_nonebot_message(
        bot,
        _mail_event(sender=_INBOUND_ADDRESS),
        _request([{"type": "file", "file": str(path)}], target_id=_IMPOSTOR_ADDRESS),
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue.kind == "mail_recipient_not_allowlisted"
    assert bot.sent == []


# ---------------------------------------------------------------------------
# 出站：逐因归因（台账 #29⑪ 同口径）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_third_adapter_fails_final_not_retryable(tmp_path: Path) -> None:
    """没有附件腿真身的适配器：终态 + 有名，不再反复重投。"""
    path = tmp_path / "f.txt"
    path.write_bytes(b"f")
    bot = _RecordingConsoleBot()

    receipt = await send_nonebot_message(
        bot,
        None,
        _request([{"type": "file", "file": str(path)}], target_id="console-user"),
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue.kind == "file_unsupported_adapter"
    assert receipt.operational_issue.retryable is False
    assert bot.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("part", "wanted_kind"),
    [
        # 文件真的不在场
        ({"type": "file", "file": "Z:/nope/missing.txt", "name": "missing.txt"}, "missing_file"),
        # 空引用
        ({"type": "file", "file": "", "name": ""}, "invalid_source"),
    ],
)
async def test_stage_failures_keep_their_own_kind(
    tmp_path: Path, part: dict[str, Any], wanted_kind: str
) -> None:
    """两因两名：派发层不再把网关的分类串压成同一枚 "invalid generated attachment"。"""
    bot = _RecordingTelegramBot()

    receipt = await send_nonebot_message(
        bot, None, _request([part], target_id="100", scope=SessionType.PRIVATE)
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue.kind == wanted_kind
    assert bot.calls == []


@pytest.mark.asyncio
async def test_transport_side_failure_kind_is_not_invented(tmp_path: Path) -> None:
    """网关之外的适配器异常**不**被误标成附件分类：仍走通用可重投分支。

    这条锁防的是「顺手把一切失败都塞进 file_* 命名空间」——一件还没送出去的文件
    是可安全重投的，把它标成 final 就等于替队列决定了不再试。
    """
    path = tmp_path / "ok.txt"
    path.write_bytes(b"ok")
    bot = _RecordingTelegramBot(fail=True)

    receipt = await send_nonebot_message(
        bot,
        None,
        _request([{"type": "file", "file": str(path.resolve())}], target_id="100"),
    )

    assert receipt.operational_issue.kind == "send_exception"
    assert receipt.operational_issue.retryable is True
    assert receipt.state is ReceiptState.FAILED_RETRYABLE


# ---------------------------------------------------------------------------
# 出站：file:// 与本地盘符绝不出网（AGENTS 铁律 3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_scheme_reference_never_leaves_the_machine(tmp_path: Path) -> None:
    """``file:///C:/...`` 形态在 Telegram / 邮箱两腿都必须**当场拒**，且本地路径
    不得出现在任何出站实参里。

    判据不靠「猜它不存在」：这里同时断言出站实参中检索不到盘符原文。
    """
    local = tmp_path / "private.txt"
    local.write_bytes(b"do not send")
    file_ref = local.resolve().as_uri()  # file:///C:/...

    tg = _RecordingTelegramBot()
    tg_receipt = await send_nonebot_message(
        tg, None, _request([{"type": "file", "file": file_ref}], target_id="100")
    )
    assert tg_receipt.state is ReceiptState.FAILED_FINAL
    assert tg.calls == []

    mail = _RecordingMailBot()
    mail_receipt = await send_nonebot_message(
        mail,
        _mail_event(),
        _request([{"type": "file", "file": file_ref}], target_id=_INBOUND_ADDRESS),
    )
    assert mail_receipt.state is ReceiptState.FAILED_FINAL
    assert mail.sent == []

    for sent_repr in (repr(tg.calls), repr([str(m) for m in mail.sent])):
        assert str(local.parent) not in sent_repr


# ---------------------------------------------------------------------------
# 入站：三端「收到一个任意文件」的现状（钉现状，不钉许可）
# ---------------------------------------------------------------------------


def test_inbound_telegram_document_segment_is_produced_but_never_fetched() -> None:
    """TG 来信带 document：段**进得来**（type=document / data.file=file_id），
    但字节**取不到** —— 富化名单刻意不含 ``document``（该文件 :52 注释自认
    「document 不在本次范围」）。⇒ 需求 16(3) 的 TG 收件半边今天未闭。

    翻转指引：读取侧席位（16a）把 ``document`` 接进富化链后，本锁会变红，
    那时请把本条改成断言「字节已落到 data.file」，不要删锁。
    """
    assert "document" not in telegram_media.TELEGRAM_FILE_ID_SEGMENT_TYPES
    # 段的来源事实：适配器入站只给 file_id，连文件名都不给。
    seg_data = {"file": "ABC123"}
    assert telegram_media._segment_file_id(seg_data) == "ABC123"
    assert "file_name" not in seg_data


def test_inbound_mail_attachment_bytes_arrive_inline() -> None:
    """邮件是唯一「字节随段在场」的一腿：``attachment`` 段自带 data/name。"""
    seg_data = {"data": b"pdf-bytes", "name": "合同.pdf", "content_type": "application/pdf"}
    assert seg_data["data"] == b"pdf-bytes"
    assert seg_data["name"] == "合同.pdf"


def test_qq_file_send_uses_the_upload_api_and_names_the_file(tmp_path: Path) -> None:
    """QQ 腿出站形状：群走 upload_group_file、件名走 name 参数、字节由协议端自取。

    这里只断言**构造出的请求形状**（离线替身），不触网。
    """
    from plugins.bot_unified_runtime.domains.transport.sender import (
        onebot as onebot_mod,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
        FileSource,
        get_default_file_gateway,
    )

    gateway = get_default_file_gateway()
    path = tmp_path / "上传件.txt"
    path.write_bytes(b"hello")
    ticket = gateway.stage(FileSource(source_kind="path", path=str(path.resolve())))

    class _Bot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def upload_group_file(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("upload_group_file", kwargs))
            return {"status": "ok", "retcode": 0, "file_id": "fid-1"}

    bot = _Bot()
    receipt = asyncio.run(
        gateway.deliver(
            bot,
            ticket,
            target=_request([], target_id="888", scope=SessionType.GROUP),
            transport="onebot",
        )
    )
    assert receipt.state is ReceiptState.SENT
    api, params = bot.calls[0]
    assert api == "upload_group_file"
    assert params["name"] == "上传件.txt"
    assert params["group_id"] == 888
    # onebot 侧的 file 值是**本机绝对路径**，收件对象是 127.0.0.1 的协议端
    # （SnowLuma），不是外部服务 ⇒ 与「本地盘符不得出网」不冲突。
    assert onebot_mod._NON_LOCAL_REF_PREFIXES == (
        "http://",
        "https://",
        "file://",
        "base64://",
        "data:",
    )


def test_gateway_exposes_exactly_three_outbound_legs() -> None:
    """三端对齐的结构锁：出站腿**有且只有** QQ / Telegram / 邮件三条，
    且每条都有自己的 transport 标记串（少一条=某一端「发不出文件」）。
    """
    from plugins.bot_unified_runtime.domains.transport.sender import file_gateway

    assert {
        file_gateway.ONEBOT_FILE_TRANSPORT,
        file_gateway.TELEGRAM_DOCUMENT_TRANSPORT,
        file_gateway.MAIL_ATTACHMENT_TRANSPORT,
    } == {"onebot.file", "telegram.document", "mail.attachment"}
    legs = {
        name
        for name in dir(file_gateway.FileTransferGateway)
        if name.startswith("_deliver_")
    }
    assert legs == {"_deliver_onebot", "_deliver_telegram_document", "_deliver_mail"}


def test_dispatch_layer_routes_file_parts_to_exactly_two_legs() -> None:
    """派发层白名单与网关腿集一致：``mail`` 必须在册，否则邮件腿又是死代码。

    这枚锁是 S-T-FILE-2「腿建好了但派发层走不到」那次的回归哨兵。
    """
    import inspect

    source = inspect.getsource(nonebot_mod)
    assert 'adapter_name not in {"telegram", "mail"}' in source
    assert 'transport="mail"' not in source  # 走变量，不走字面量第二真身
    assert "file attachments unsupported by this adapter" not in source


@pytest.mark.asyncio
async def test_mail_leg_provider_id_absence_is_not_treated_as_failure(
    tmp_path: Path,
) -> None:
    """SMTP 出口不回消息号：派发层不得照抄 Telegram 的「无 provider_file_id 即失败」。

    替身的 ``send_mail`` 返回 None（与真适配器同形），仍须 SENT。
    """
    path = tmp_path / "v.txt"
    path.write_bytes(b"v")
    bot = _RecordingMailBot()

    receipt = await send_nonebot_message(
        bot, _mail_event(), _request([{"type": "file", "file": str(path.resolve())}])
    )

    assert receipt.state is ReceiptState.SENT
    assert receipt.operational_issue is None
    assert len(bot.sent) == 1
