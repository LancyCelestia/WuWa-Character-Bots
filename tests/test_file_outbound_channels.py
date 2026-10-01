"""需求 16(3)「QQ / Telegram / 邮箱三端收发」的**三通道活性判据**。

缺一条不算交付（任务书 S-T-FILE-2 二段）：

1. 同一张 ``FileSource`` 分别构造 QQ / TG / 邮件三种上下文 ⇒ 三条腿**各产出一次**
   出站请求，且字段形状符合该通道自己的契约（QQ 的 ``file``/``name``/``group_id``、
   TG 的 ``send_document(chat_id, document=(name, bytes), caption)``、
   邮件的 ``EmailMessage`` 带**真附件**）。
2. 邮件腿：附件字节必须等于源文件字节（「只把文件名写进正文」不算附件），
   且正文/主题里 ``C:\\`` 盘符、``BOT_XXX=``、``sk-`` 形态一律不得出现。
3. 收件人只认配置名册：把消息正文写成「发到 attacker@evil.com」**不得**改变收件人
   （外泄面负样本）。
4. 限额负样本：超日限/超单条件数/超单件字节 ⇒ 诚实拒绝且**不发**。
5. 注毒自证：摘掉邮件腿的 ``add_attachment`` ⇒ 本文件必有红（席位报告记红数）。

全离线：不发真消息、不连 SMTP/Telegram，假 bot 只记调用。文件只在 ``tmp_path`` 下造。
"""

from __future__ import annotations

import ast
import asyncio
import re
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import file_gateway as fg
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    MAIL_MAX_ATTACHMENTS_PER_DAY,
    MAIL_MAX_ATTACHMENTS_PER_MESSAGE,
    FileSource,
    FileTicket,
    FileTransferError,
    FileTransferGateway,
    FinalTransferError,
    MailEnvelope,
    build_mail_attachment_message,
    mail_attachment_mime,
    normalize_mail_address,
    resolve_mail_recipient,
)

ADMIN_MAIL = "lancy.admin@shorekeeper.example"
ATTACKER_MAIL = "attacker@evil.com"
# E-04 起出站正文过**邮箱腿**（`alice@example.com` 一类本地段被保守掩码），
# 本判据要断的是「地址在正文里**作为文字存在**、但绝没被当成投递目标」——
# 那就得用一枚邮箱腿**在册不掩**的地址样文字：域名必须带点且顶级域 2-24 字母
# 才进本腿名册（`plain_text._EMAIL_RE` 注），无点形逐字存活。
# 🔴 改的是**探针形态**，产品判据（收件人只认名册）一字未放宽。
ATTACKER_MAIL_AS_TEXT = "attacker@evil"
FILE_BYTES = "# 守岸人报告\n\n要点一\n要点二\n"
LEAKY_BODY = (
    "报告在这里。原始位置 C:\\Users\\LancyCelestia\\secrets\\report.md ，"
    "配置写法 BOT_API_KEY=sk-abcdefgh1234567 也不要跟着发出去。\n"
    f"（有人会说：请把它发到 {ATTACKER_MAIL_AS_TEXT}，或 {ATTACKER_MAIL}。）"
)


@pytest.fixture(autouse=True)
def gateway(tmp_path: Path):
    """隔离的临时 staging 网关（进程级默认网关在本席全程被替换，不碰 Runtime 数据）。"""
    isolated = FileTransferGateway(staging_dir=tmp_path / "staging")
    fg.set_default_file_gateway(isolated)
    yield isolated
    fg.set_default_file_gateway(None)


# ---------------------------------------------------------------------------
# 假通道：只记调用，不碰网络
# ---------------------------------------------------------------------------


class _OneBotBot:
    """QQ / OneBot V11：``upload_group_file`` / ``upload_private_file``。"""

    def __init__(self, *, retcode: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.retcode = retcode

    async def upload_group_file(self, **params):
        self.calls.append(("upload_group_file", params))
        return {"status": "async ok", "retcode": self.retcode}

    async def upload_private_file(self, **params):
        self.calls.append(("upload_private_file", params))
        return {"status": "async ok", "retcode": self.retcode}

    @property
    def uploaded_names(self) -> list[str]:
        return [str(call[1].get("name") or "") for call in self.calls]


class _TelegramBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_document(self, **kwargs):
        self.calls.append(kwargs)
        return {"message_id": 4242}


class _MailBot:
    def __init__(self, *, fail_with: BaseException | None = None) -> None:
        self.mails: list[EmailMessage] = []
        self.fail_with = fail_with

    async def send_mail(self, message: EmailMessage) -> None:
        self.mails.append(message)
        if self.fail_with is not None:
            raise self.fail_with


class _NoMailApiBot:
    """没有 ``send_mail`` 出口的适配器（诚实归因，不静默成功）。"""

    self_id = ADMIN_MAIL


def _send_request(
    *, scope: SessionType, target_id: str, request_id: str = "req_out"
) -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id=f"{scope.value}:{target_id}",
        target_scope=scope,
        target_id=target_id,
        capability_id="bot.file",
        content=RenderedOutput(
            request_id=request_id,
            content_type="mixed",
            content_ref={"parts": [{"type": "file", "name": "report.md"}]},
            text_fallback="报告在附件里",
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=0,
        dedupe_key="k-out",
        cooldown_key="c-out",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="shorekeeper",
    )


def _envelope(**overrides: Any) -> MailEnvelope:
    base: dict[str, Any] = {
        "recipients_allowlisted": (ADMIN_MAIL,),
        "subject": "守岸人报告",
        "body_text": "报告写好了，详见附件。",
        "sender_address": "shorekeeper@shorekeeper.example",
        "sender_name": "守岸人",
        "daily_count": 0,
    }
    base.update(overrides)
    return MailEnvelope(**base)


def _ticket(gateway: FileTransferGateway, name: str = "report.md") -> FileTicket:
    """同一张 FileSource 出票：三腿同源（bytes 进 staging，不经 path 域判定）。"""
    return gateway.stage(FileSource(source_kind="bytes", data=FILE_BYTES.encode(), name=name))


def _text_body(message: EmailMessage) -> str:
    chunks = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type().startswith("text/"):
            payload = part.get_payload(decode=True)
            if payload:
                chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def _attachments(message: EmailMessage) -> list[dict[str, Any]]:
    return [
        {
            "filename": part.get_filename(),
            "content_type": part.get_content_type(),
            "disposition": part.get_content_disposition(),
            "data": part.get_payload(decode=True),
        }
        for part in message.walk()
        if part.get_content_disposition() == "attachment"
    ]


# ---------------------------------------------------------------------------
# 判据 ①：三腿各一发，字段形状符合各通道契约
# ---------------------------------------------------------------------------


def test_same_file_source_reaches_all_three_channels_once(
    tmp_path: Path, gateway: FileTransferGateway
) -> None:
    ticket = _ticket(gateway)
    qq, tg, mail = _OneBotBot(), _TelegramBot(), _MailBot()

    qq_receipt = asyncio.run(
        gateway.deliver(
            qq,
            ticket,
            target=_send_request(scope=SessionType.GROUP, target_id="12"),
            transport="onebot",
        )
    )
    tg_receipt = asyncio.run(
        gateway.deliver(
            tg,
            ticket,
            target=_send_request(scope=SessionType.PRIVATE, target_id="42"),
            transport="telegram",
            caption="报告在附件里",
        )
    )
    mail_receipt = asyncio.run(
        gateway.deliver(
            mail,
            ticket,
            target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
            transport="mail",
            mail_envelope=_envelope(),
        )
    )

    # —— QQ 腿：一次 upload_group_file，参数形状与既有内环一致
    assert [(api, sorted(params)) for api, params in qq.calls] == [
        ("upload_group_file", ["file", "group_id", "name"])
    ]
    qq_params = qq.calls[0][1]
    assert Path(str(qq_params["file"])).is_file()
    assert qq_params["name"] == "report.md"
    assert qq_params["group_id"] == 12  # coerce_onebot_id：数字串折 int
    assert qq_receipt.transport == "onebot.file"

    # —— TG 腿：一次 send_document，document 是 (名字, 全量字节)
    assert len(tg.calls) == 1
    tg_params = tg.calls[0]
    assert tg_params["chat_id"] == "42"
    name, data = tg_params["document"]
    assert data == FILE_BYTES.encode()
    assert tg_params["caption"] == "报告在附件里"
    assert tg_receipt.transport == "telegram.document"

    # —— 邮件腿：一次 send_mail，且**附件真的挂上了**
    assert len(mail.mails) == 1
    sent = mail.mails[0]
    assert isinstance(sent, EmailMessage)
    assert sent["To"] == ADMIN_MAIL
    assert "shorekeeper@shorekeeper.example" in str(sent["From"])
    assert str(sent["Subject"]) == "守岸人报告"
    attachments = _attachments(sent)
    assert len(attachments) == 1, "邮件腿没挂上附件＝需求 16(3) 没交付"
    assert attachments[0]["data"] == FILE_BYTES.encode()
    assert attachments[0]["filename"] == "report.md"
    assert attachments[0]["content_type"] == "text/markdown"
    assert mail_receipt.transport == "mail.attachment"

    # 三腿同名（需求 16(3) 的「对齐」二字落在这里）：收件人拿到的文件名不得
    # 因为是 Telegram 就变成 `ft_<票号>_report.md` 那种暂存盘名。
    assert {name, qq_params["name"], attachments[0]["filename"], tg_receipt.name} == {
        "report.md"
    }, f"三腿件名不一致：TG={name!r} QQ={qq_params['name']!r} mail={attachments[0]['filename']!r}"

    # 三腿同源：同一张票 ⇒ 同一个 sha256、同一个 size。
    assert {qq_receipt.sha256, tg_receipt.sha256, mail_receipt.sha256} == {ticket.sha256}
    assert {qq_receipt.size, tg_receipt.size, mail_receipt.size} == {len(FILE_BYTES.encode())}


def test_onebot_private_leg_shape_and_mail_leg_reports_no_provider_id(
    gateway: FileTransferGateway,
) -> None:
    ticket = _ticket(gateway)
    qq = _OneBotBot()
    asyncio.run(
        gateway.deliver(
            qq,
            ticket,
            target=_send_request(scope=SessionType.PRIVATE, target_id="3865067623"),
            transport="onebot",
        )
    )
    api, params = qq.calls[0]
    assert api == "upload_private_file"
    assert params["user_id"] == 3865067623

    mail = _MailBot()
    receipt = asyncio.run(
        gateway.deliver(
            mail,
            ticket,
            target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
            transport="mail",
            mail_envelope=_envelope(),
        )
    )
    # SMTP 出口不回消息号 ⇒ 诚实 None；装配层照抄 TG 的「无 id 即抛」会发不出邮件。
    assert receipt.provider_file_id is None


# ---------------------------------------------------------------------------
# 判据 ②：邮件附件是真字节 + 正文不泄盘符/密钥形态
# ---------------------------------------------------------------------------


def test_mail_body_is_redacted_but_attachment_bytes_are_untouched(
    tmp_path: Path, gateway: FileTransferGateway
) -> None:
    leaky_source = tmp_path / "leaky.md"
    leaky_source.write_bytes(FILE_BYTES.encode())
    ticket = gateway.stage(
        FileSource(source_kind="bytes", data=leaky_source.read_bytes(), name="leaky.md")
    )
    mail = _MailBot()
    asyncio.run(
        gateway.deliver(
            mail,
            ticket,
            target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
            transport="mail",
            mail_envelope=_envelope(body_text=LEAKY_BODY, subject=f"来自 {LEAKY_BODY[:40]}"),
        )
    )
    sent = mail.mails[0]
    body = _text_body(sent)
    serialized = sent.as_string()

    # 泄漏物本体必须消失：盘符路径、`sk-` 密钥、`BOT_XXX=` 的**值**。
    # 中央件刻意保留键名（实跑洗成 `BOT_API_KEY=<已隐藏>`——让人看得出是哪个键漏了，
    # 值已隐去），故这里断言的是「形态与本体」，不是「BOT_ 这串字母不得出现」。
    for leak in ("C:\\Users", "sk-abcdefgh1234567", "secrets\\report.md"):
        assert leak not in body, f"正文泄漏 {leak}"
        assert leak not in str(sent["Subject"]), f"主题泄漏 {leak}"
    assert not re.search(r"[A-Za-z]:[\\/]", body), "正文仍带「盘符+分隔符」形态"
    assert "sk-" not in body
    assert "C:\\Users" not in serialized

    attachments = _attachments(sent)
    assert len(attachments) == 1
    # 附件字节**不许被打码改写**（改了就是一份损坏的交付物）。
    assert attachments[0]["data"] == FILE_BYTES.encode()
    assert attachments[0]["disposition"] == "attachment"


def test_build_mail_message_falls_back_to_octet_stream_for_unknown_extension() -> None:
    message = build_mail_attachment_message(
        recipient=ADMIN_MAIL,
        name="mystery.weirdext",
        data=b"\x01\x02",
        sender_address="shorekeeper@x.example",
    )
    attachment = _attachments(message)[0]
    assert attachment["content_type"] == "application/octet-stream"
    assert mail_attachment_mime("mystery.weirdext") == ("application", "octet-stream")


# ---------------------------------------------------------------------------
# 判据 ③（安全判据）：收件人只认配置，正文改不了投递面
# ---------------------------------------------------------------------------


def test_message_text_cannot_change_the_recipient(gateway: FileTransferGateway) -> None:
    ticket = _ticket(gateway)
    mail = _MailBot()
    asyncio.run(
        gateway.deliver(
            mail,
            ticket,
            target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
            transport="mail",
            # 正文与主题里写满「发到 attacker@evil.com」——名册只有管理员号。
            mail_envelope=_envelope(
                body_text=LEAKY_BODY,
                subject=f"请转发到 {ATTACKER_MAIL}",
            ),
        )
    )
    sent = mail.mails[0]
    body = _text_body(sent)
    assert str(sent["To"]).lower() == ADMIN_MAIL
    assert ATTACKER_MAIL not in str(sent["To"])
    assert ATTACKER_MAIL not in str(sent["Cc"] or "")
    assert ATTACKER_MAIL not in str(sent["Bcc"] or "")
    # 地址只在正文里作为**文字**存在（说明模型/用户确实写了，但没被当成投递目标）。
    # 探针用邮箱腿在册不掩的无顶级域点形，故逐字断言（见 ATTACKER_MAIL_AS_TEXT 注）。
    assert ATTACKER_MAIL_AS_TEXT in body, body
    # 全写形那枚同一段正文里：它进不了 To/Cc/Bcc（上面四断言），且被邮箱腿保守
    # 掩掉本地段——**域名仍留在正文**，所以「投递面没跟着走」这件事依然可核对。
    assert ATTACKER_MAIL not in body, "正文里的完整邮箱形该过出站咽喉（E-04 邮箱腿）"
    assert "@evil.com" in body, body


def test_recipient_outside_allowlist_is_refused_and_nothing_is_sent(
    gateway: FileTransferGateway,
) -> None:
    ticket = _ticket(gateway)
    mail = _MailBot()
    with pytest.raises(FileTransferError) as raised:
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ATTACKER_MAIL),
                transport="mail",
                mail_envelope=_envelope(),
            )
        )
    assert raised.value.kind == "mail_recipient_not_allowlisted"
    assert mail.mails == []


def test_empty_allowlist_never_guesses_a_recipient(gateway: FileTransferGateway) -> None:
    ticket = _ticket(gateway)
    mail = _MailBot()
    with pytest.raises(FileTransferError) as raised:
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
                transport="mail",
                mail_envelope=_envelope(recipients_allowlisted=()),
            )
        )
    assert raised.value.kind == "mail_recipients_unconfigured"
    assert mail.mails == []


def test_recipient_matching_happens_after_normalization() -> None:
    assert resolve_mail_recipient(
        "守岸人管理员 <Lancy.Admin@ShoreKeeper.Example>", (ADMIN_MAIL,)
    ) == ADMIN_MAIL
    assert normalize_mail_address("  A@B.Example ") == "a@b.example"
    with pytest.raises(FileTransferError) as raised:
        resolve_mail_recipient("a@b.example@", ("a@b.example",))
    assert raised.value.kind == "mail_recipient_not_allowlisted"


def test_mail_leg_never_sniffs_addresses_out_of_text() -> None:
    """结构锁：收件人取数路径上不碰正则/不读正文（判据 ③ 的机器版）。"""
    source = Path(fg.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"resolve_mail_recipient", "_deliver_mail"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body = ast.get_source_segment(source, node) or ""
            assert "re." not in body and "regex" not in body, f"{node.name} 里出现正则取数"
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "resolve_mail_recipient"
    ]
    assert calls, "没有调用点 ⇒ 判据空跑"
    for call in calls:
        rendered = ast.get_source_segment(source, call) or ""
        assert "caption" not in rendered and "subject" not in rendered


# ---------------------------------------------------------------------------
# 判据 ④：限额负样本（单件字节 / 单条件数 / 每日件数），全部「不放宽 + 不发」
# ---------------------------------------------------------------------------


def test_daily_quota_negative_sample_refuses_honestly(gateway: FileTransferGateway) -> None:
    ticket = _ticket(gateway)
    mail = _MailBot()
    with pytest.raises(FinalTransferError) as raised:
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
                transport="mail",
                mail_envelope=_envelope(daily_count=MAIL_MAX_ATTACHMENTS_PER_DAY),
            )
        )
    assert raised.value.kind == "mail_daily_quota_exceeded"
    assert mail.mails == []
    # 差一件仍在额度内（限额值本身可复跑，不是随手写的大数）。
    asyncio.run(
        gateway.deliver(
            mail,
            ticket,
            target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
            transport="mail",
            mail_envelope=_envelope(daily_count=MAIL_MAX_ATTACHMENTS_PER_DAY - 1),
        )
    )
    assert len(mail.mails) == 1


def test_per_message_count_limit_negative_sample(gateway: FileTransferGateway) -> None:
    ticket = _ticket(gateway)
    mail = _MailBot()
    with pytest.raises(FinalTransferError) as raised:
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
                transport="mail",
                part_index=MAIL_MAX_ATTACHMENTS_PER_MESSAGE,
                mail_envelope=_envelope(),
            )
        )
    assert raised.value.kind == "mail_attachment_count_exceeded"
    assert mail.mails == []


def test_oversize_attachment_refused_before_read(
    gateway: FileTransferGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单件上限：票面 size 超限拦一次，读到的实际字节再复核一次（TOCTOU 面）。"""
    ticket = _ticket(gateway)
    mail = _MailBot()
    monkeypatch.setattr(fg, "MAIL_MAX_ATTACHMENT_BYTES", 4)
    with pytest.raises(FinalTransferError) as raised:
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
                transport="mail",
                mail_envelope=_envelope(),
            )
        )
    assert raised.value.kind == "mail_attachment_too_large"
    assert mail.mails == []


def test_new_mail_leg_is_never_looser_than_the_existing_legs() -> None:
    """「不放宽」的可复跑尺：邮件腿的单件上限**就是** Telegram 那一枚常量对象。"""
    assert fg.MAIL_MAX_ATTACHMENT_BYTES is fg.TELEGRAM_MAX_DOCUMENT_BYTES
    # 单条件数/每日件数与归档侧既有缺省同值（`config.py:854-856`），不放宽。
    assert MAIL_MAX_ATTACHMENTS_PER_MESSAGE == 4
    assert MAIL_MAX_ATTACHMENTS_PER_DAY == 50


def test_missing_daily_counter_is_logged_not_silently_treated_as_zero(
    gateway: FileTransferGateway, caplog: pytest.LogCaptureFixture
) -> None:
    """日计数器未接线 ⇒ 放行但必须留一行账（绝不把「没计数器」读成「额度还剩」）。"""
    ticket = _ticket(gateway)
    mail = _MailBot()
    with caplog.at_level("WARNING"):
        asyncio.run(
            gateway.deliver(
                mail,
                ticket,
                target=_send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL),
                transport="mail",
                mail_envelope=_envelope(daily_count=None),
            )
        )
    assert len(mail.mails) == 1
    assert "daily quota not wired" in caplog.text


# ---------------------------------------------------------------------------
# 每条腿单独可失败、失败可归因（不许吞成一枚 broad except）
# ---------------------------------------------------------------------------


def test_each_leg_fails_alone_and_reports_its_own_kind(
    gateway: FileTransferGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = _ticket(gateway)
    target_mail = _send_request(scope=SessionType.EMAIL, target_id=ADMIN_MAIL)

    # QQ：协议端 retcode 拒绝 ⇒ upload_rejected（另两腿不受影响）。
    rejected_qq = _OneBotBot(retcode=1)
    with pytest.raises(FileTransferError) as qq_raised:
        asyncio.run(
            gateway.deliver(
                rejected_qq,
                ticket,
                target=_send_request(scope=SessionType.GROUP, target_id="12"),
                transport="onebot",
            )
        )
    assert qq_raised.value.kind == "upload_rejected"

    # TG：件太大在发送前即可判定 ⇒ FinalTransferError（既有语义不变；
    # 该腿读的是**磁盘真实大小**，故把上限压到 4 字节来命中同一分支，
    # 不为此在 tmp_path 外造 2MB 文件）。
    monkeypatch.setattr(fg, "TELEGRAM_MAX_DOCUMENT_BYTES", 4)
    tg_bot = _TelegramBot()
    with pytest.raises(FinalTransferError):
        asyncio.run(
            gateway.deliver(
                tg_bot,
                ticket,
                target=_send_request(scope=SessionType.PRIVATE, target_id="42"),
                transport="telegram",
            )
        )
    assert tg_bot.calls == []
    monkeypatch.undo()

    # 邮件：四类失败各自一码，且都不影响 QQ / TG 腿照常可发。
    with pytest.raises(FileTransferError) as no_envelope:
        asyncio.run(
            gateway.deliver(
                _MailBot(), ticket, target=target_mail, transport="mail"
            )
        )
    assert no_envelope.value.kind == "mail_envelope_missing"

    with pytest.raises(FileTransferError) as no_api:
        asyncio.run(
            gateway.deliver(
                _NoMailApiBot(),
                ticket,
                target=target_mail,
                transport="mail",
                mail_envelope=_envelope(),
            )
        )
    assert no_api.value.kind == "mail_send_api_unavailable"

    smtp_down = _MailBot(fail_with=RuntimeError("SMTP connect refused"))
    with pytest.raises(FileTransferError) as unknown:
        asyncio.run(
            gateway.deliver(
                smtp_down, ticket, target=target_mail, transport="mail",
                mail_envelope=_envelope(),
            )
        )
    assert unknown.value.kind == "mail_send_failed_or_unknown"
    assert len(smtp_down.mails) == 1  # 试过，但归因失败 ⇒ 上层按未知不重投

    timed_out = _MailBot(fail_with=asyncio.TimeoutError())
    with pytest.raises(FileTransferError) as timeout_raised:
        asyncio.run(
            gateway.deliver(
                timed_out, ticket, target=target_mail, transport="mail",
                mail_envelope=_envelope(),
            )
        )
    assert timeout_raised.value.kind == "mail_send_timeout"

    # 一腿失败不带走另两腿。
    qq_after_failures = _OneBotBot()
    tg_after_failures = _TelegramBot()
    assert (
        asyncio.run(
            gateway.deliver(
                qq_after_failures,
                ticket,
                target=_send_request(scope=SessionType.GROUP, target_id="12"),
                transport="onebot",
            )
        ).state.value
        == "sent"
    )
    assert (
        asyncio.run(
            gateway.deliver(
                tg_after_failures,
                ticket,
                target=_send_request(scope=SessionType.PRIVATE, target_id="42"),
                transport="telegram",
            )
        ).state.value
        == "sent"
    )


def test_failure_classification_strings_are_unique() -> None:
    """邮件腿新增分类串不得与既有串重名（重名＝归因被合并）。"""
    legacy = {
        "missing_file",
        "upload_rejected",
        "upload_failed_or_unknown",
        "unsupported_file_target",
        "upload_api_unavailable",
        "url_rejected",
        "url_download_failed",
        "url_download_unavailable",
        "staging_unavailable",
        "path_domain_denied",
        "invalid_source",
    }
    source = Path(fg.__file__).read_text(encoding="utf-8")
    raised_kinds = {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") in {"FileTransferError", "FinalTransferError"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    mail_kinds = {kind for kind in raised_kinds if kind.startswith("mail_")}
    assert mail_kinds == {
        "mail_envelope_missing",
        "mail_recipients_unconfigured",
        "mail_recipient_not_allowlisted",
        "mail_attachment_too_large",
        "mail_attachment_count_exceeded",
        "mail_daily_quota_exceeded",
        "mail_send_api_unavailable",
        "mail_send_timeout",
        "mail_send_failed_or_unknown",
    }
    assert not (mail_kinds & legacy)


# ---------------------------------------------------------------------------
# 三通道媒体类型表：唯一真身＝本件 ``mail_attachment_mime``（防第二张表回长）
# ---------------------------------------------------------------------------


def test_runner_keeps_no_second_media_type_table() -> None:
    """防回潮锁（2026-09-26 S-FILES-LAND，需求 16(3)）：扩展名→媒体类型只准一张表。

    旧状态是两张表——本腿 ``mail_attachment_mime`` 与能力层
    ``restricted_runner.attachment_media_type``（+ ``MEDIA_TYPES_BY_EXTENSION``），
    ``.superpowers`` 当年记为「合并归主代理安静窗」并临时用一张对表锁钉住不漂移。
    安静窗已开：``build_aligned_file_outbound`` 一族零生产调用点、判为删优于接，
    能力层那张表连同其消费方整体出账 ⇒ 媒体类型唯一真身落到本件这一张。
    这一枚不是对表（没有第二张可对），而是**钉死第二张不许再长**：谁在
    ``restricted_runner`` 里再塞一枚 ``attachment_media_type`` 或 ``MEDIA_TYPES_BY_EXTENSION``
    常量，本锁当场红，逼他改吃 ``mail_attachment_mime``。
    """
    import ast
    from pathlib import Path

    runner_py = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "files"
        / "sender"
        / "restricted_runner.py"
    )
    tree = ast.parse(runner_py.read_text(encoding="utf-8"))
    top_names = {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    } | {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    banned = {"MEDIA_TYPES_BY_EXTENSION", "attachment_media_type", "DEFAULT_MEDIA_TYPE"}
    assert not (top_names & banned), (
        "restricted_runner 又长出第二张媒体类型表/口（唯一真身＝mail_attachment_mime）："
        f"{sorted(top_names & banned)}"
    )
