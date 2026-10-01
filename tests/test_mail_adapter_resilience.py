from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from email.mime.text import MIMEText
from email.utils import formatdate
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nonebot.adapters.mail.bot import Bot as MailBot
from nonebot.adapters.mail.config import BotInfo

from plugins.bot_unified_runtime.domains.transport.mail import mail_adapter
from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    QuietMailMessageEvent,
    ResilientMailAdapter,
    mail_retry_delay,
    mark_mail_seen,
)


class _Response:
    def __init__(self, result: str = "OK", lines: list[bytes] | None = None) -> None:
        self.result = result
        self.lines = lines if lines is not None else []


class _FakeIMAP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.uid_calls: list[tuple[str, ...]] = []

    async def store(self, *criteria: str) -> _Response:
        self.calls.append(criteria)
        return _Response()

    async def uid(self, command: str, *criteria: str) -> _Response:
        self.uid_calls.append((command, *criteria))
        return _Response()


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 3.0), (1, 6.0), (2, 12.0), (3, 24.0), (4, 48.0), (5, 60.0), (99, 60.0)],
)
def test_mail_retry_delay_is_bounded_exponential(attempt: int, expected: float) -> None:
    assert mail_retry_delay(attempt) == expected


@pytest.mark.asyncio
async def test_mark_mail_seen_uses_uid_store_not_sequence_store() -> None:
    """标已读必须走 ``UID STORE``，不得回退到 ``store()``。

    aioimaplib 的 ``IMAP4.store()`` 默认 ``by_uid=False``
    （aioimaplib.py:540 与 :749），会把 UID 当**序号**发给服务器：
    UID 与序号一旦错位就会标错邮件，UID 超出当前邮件数时直接失败。
    """
    imap = _FakeIMAP()

    await mark_mail_seen(imap, "42")

    assert imap.uid_calls == [("STORE", "42", "+FLAGS", "\\Seen")]
    assert imap.calls == [], "标已读不得走按序号寻址的 store()"


def test_quiet_mail_event_description_excludes_body() -> None:
    event = QuietMailMessageEvent(
        id="<mail@example.com>",
        sender={"id": "sender@example.com", "name": "Sender"},
        subject="测试主题",
        recipients_to=[],
        recipients_cc=[],
        recipients_bcc=[],
        date=None,
        timezone=None,
        message={"type": "text", "data": {"text": "secret body"}},
        original_message={"type": "text", "data": {"text": "secret body"}},
    )

    description = event.get_event_description()
    assert "测试主题" in description
    assert "secret body" not in description
    assert QuietMailMessageEvent.__module__ == "nonebot.adapters.mail.event"


# ---------------------------------------------------------------------------
# 离线假件：adapter 绕过 __init__（需真实 Driver/Config），只补齐被测路径
# 触达的属性；IMAP 行为用脚本化假客户端全离线模拟。
# ---------------------------------------------------------------------------


def _raw_mail(uid: str) -> bytes:
    mail = MIMEText("正文占位", "plain", "utf-8")
    mail["Subject"] = f"主题 {uid}"
    mail["From"] = "Sender <sender@example.com>"
    mail["To"] = "Shorekeeper <bot@example.com>"
    mail["Message-ID"] = f"<{uid}@example.com>"
    mail["Date"] = formatdate(localtime=False)
    return mail.as_bytes()


class _FakeDriver:
    """nonebot BaseAdapter 的 bot_connect/bot_disconnect 只触达这两个钩子。"""

    def _bot_connect(self, bot: Any) -> None:
        return None

    def _bot_disconnect(self, bot: Any) -> None:
        return None


class _ScriptedIMAP(_FakeIMAP):
    """按 uid 脚本化取信行为并记录 select/uid/裸 fetch 调用的假 IMAP 客户端。"""

    def __init__(
        self,
        *,
        on_search: Callable[[], Any] | None = None,
        login_error: str | None = None,
    ) -> None:
        super().__init__()
        self.select_calls = 0
        self.plain_fetch_calls: list[tuple[str, ...]] = []
        self.fetch_behaviors: dict[str, Any] = {}
        self._on_search = on_search
        self._login_error = login_error
        self.timeout = 1.0
        self.protocol = SimpleNamespace(new_tag=lambda: "TAG1", execute=self._execute)

    async def _execute(self, command: Any) -> _Response:
        return _Response()

    async def wait_hello_from_server(self) -> None:
        return None

    async def login(self, user: str, password: str) -> _Response:
        if self._login_error is not None:
            raise RuntimeError(self._login_error)
        self.calls.append(("login", user))
        return _Response()

    async def select(self, mailbox: str) -> _Response:
        self.select_calls += 1
        return _Response(lines=[bytearray(b"1 EXISTS")])

    async def search(self, criteria: str) -> Any:
        self.calls.append(("search", criteria))
        if self._on_search is not None:
            outcome = self._on_search()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return _Response()

    async def fetch(self, *criteria: str) -> _Response:
        self.plain_fetch_calls.append(criteria)
        return _Response()

    async def uid(self, command: str, *criteria: str) -> Any:
        self.uid_calls.append((command, *criteria))
        if command == "FETCH":
            uid = str(criteria[0])
            behavior = self.fetch_behaviors.get(uid)
            if isinstance(behavior, Exception):
                raise behavior
            if behavior is not None:
                return behavior
            return _Response(lines=[bytearray(b"* 1 FETCH (RFC822 {n}"), _raw_mail(uid)])
        return _Response()

    async def logout(self) -> _Response:
        return _Response()


def _make_adapter() -> ResilientMailAdapter:
    adapter = ResilientMailAdapter.__new__(ResilientMailAdapter)
    adapter.driver = cast(Any, _FakeDriver())
    adapter.bots = {}
    adapter.tasks = set()
    # F2 在飞门真身（MAILINGRESS-F2 格 A 落进 `__init__`）；本 harness 走 `__new__`
    # 绕开构造器，配对格 D 显式补这枚属性。
    adapter._inflight_uids = set()
    return adapter


def _make_bot_info() -> BotInfo:
    return BotInfo.model_validate(
        {
            "id": "bot@example.com",
            "name": "守岸人",
            "password": "secret",
            "subject": "守岸人测试",
            "imap": {"host": "imap.example.com", "port": 993, "tls": True},
            "smtp": {"host": "smtp.example.com", "port": 465, "tls": True},
        }
    )


def _connect_bot(adapter: Any, imap: Any) -> MailBot:
    bot = MailBot(adapter, "bot@example.com", _make_bot_info())
    bot.imap_client = imap
    bot.mailbox = "INBOX"
    bot.readonly = False
    return bot


def _record_events_into(bot: MailBot, handled: list[Any]) -> None:
    async def _record(event: Any) -> None:
        handled.append(event.id)

    bot.handle_event = _record  # type: ignore[assignment]


async def _drain_tracked_tasks(adapter: ResilientMailAdapter) -> None:
    pending = [task for task in list(adapter.tasks) if not task.done()]
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_check_mailbox_reselects_after_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """断线重连后必须对新连接重新发 SELECT（锁死适配器早退缓存回归）。

    适配器 ``Bot.select_mailbox`` 在 ``self.mailbox == mailbox`` 时早退
    True、不发 SELECT（venv nonebot/adapters/mail/bot.py:363），而
    ``_check_mailbox`` 每轮重连新建 IMAP 连接却复用同一 MailBot——不重置
    缓存的话，新连接停在 AUTH 态，SEARCH 报
    "Abort: command SEARCH illegal in state AUTH"。
    """
    monkeypatch.setattr(mail_adapter, "mail_retry_delay", lambda attempt: 0.01)
    adapter = _make_adapter()

    client1 = _ScriptedIMAP(on_search=lambda: RuntimeError("IMAP dropped"))
    client2 = _ScriptedIMAP(on_search=lambda: RuntimeError("IMAP dropped again"))
    second_selected = asyncio.Event()
    _select2 = client2.select

    async def _counting_select2(mailbox: str) -> _Response:
        response = await _select2(mailbox)
        second_selected.set()
        return response

    client2.select = _counting_select2  # type: ignore[assignment]

    # 备胎连接：login 即拒，任由 worker 退避循环直到测试收尾取消。
    standby = _ScriptedIMAP(login_error="server refused")
    clients: deque[_ScriptedIMAP] = deque([client1, client2, standby])

    def _factory(bot_info: BotInfo) -> Any:
        return clients.popleft() if clients else standby

    monkeypatch.setattr(adapter, "_new_imap_client", _factory)

    bot = MailBot(adapter, "bot@example.com", _make_bot_info())
    worker = asyncio.create_task(adapter._check_mailbox(bot))
    try:
        await asyncio.wait_for(second_selected.wait(), timeout=5.0)
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    assert client1.select_calls == 1, "首连应真发一次 SELECT"
    assert client2.select_calls == 1, "重连后的新连接必须重新 SELECT，不得吃缓存早退"


@pytest.mark.asyncio
async def test_fetch_new_mail_fetches_by_uid_and_never_plain_fetch() -> None:
    """取信必须走 ``uid("FETCH", <uid>, "(RFC822)")``，不得调用裸 ``fetch(``。

    适配器 ``fetch_mail_of_uid`` 走普通 FETCH（按序号寻址），UID 与序号
    错位即取错信/取不到；回归锁死 ``_fetch_new_mail`` 的取信通道。
    """
    adapter = _make_adapter()
    fake = _ScriptedIMAP(on_search=lambda: _Response(lines=[bytearray(b"7 9")]))
    bot = _connect_bot(adapter, fake)
    handled: list[Any] = []
    _record_events_into(bot, handled)

    await adapter._fetch_new_mail(bot)
    await _drain_tracked_tasks(adapter)

    # 格 D（MAILINGRESS-F2 配对锁）：旧断言钉的是「FETCH 7, STORE 7, FETCH 9, STORE 9」
    # 这条 \Seen 前置的严格全序；\Seen 后置到派发成功之后，跨封交错变成
    # FETCH/FETCH/handle/handle/STORE/STORE 一类形态，全序断言会误伤。
    # 拆成分组断言后仍锁住两件事：① 两封都先取（FETCH 先行、无裸 fetch）；
    # ② 两封各自回执（STORE 恰好 7/9 各一次）。「handle 先于 STORE」由
    # tests/test_mail_ingress_locks.py::test_f2_seen_committed_only_after_successful_dispatch
    # 的顺序锁执法，本处不重复钉第二把尺。
    fetches = [call[1] for call in fake.uid_calls if call[0] == "FETCH"]
    stores = [call[1] for call in fake.uid_calls if call[0] == "STORE"]
    assert fetches == ["7", "9"]
    assert stores == ["7", "9"], (
        "F2 翻序后：两封先取、后各自在派发任务的 handle 成功回执里 STORE"
    )
    assert fake.plain_fetch_calls == [], "取信不得走按序号寻址的裸 fetch()"
    assert handled == ["<7@example.com>", "<9@example.com>"]


@pytest.mark.asyncio
async def test_fetch_new_mail_isolates_single_bad_mail() -> None:
    """单封取信抛错只跳过该封（WARNING 后 continue），其余 uid 仍被处理。"""
    adapter = _make_adapter()
    fake = _ScriptedIMAP(on_search=lambda: _Response(lines=[bytearray(b"1 2 3")]))
    fake.fetch_behaviors["2"] = RuntimeError("malformed RFC822")
    bot = _connect_bot(adapter, fake)
    handled: list[Any] = []
    _record_events_into(bot, handled)

    await adapter._fetch_new_mail(bot)
    await _drain_tracked_tasks(adapter)

    assert handled == ["<1@example.com>", "<3@example.com>"]
    stores = [call for call in fake.uid_calls if call[0] == "STORE"]
    assert stores == [
        ("STORE", "1", "+FLAGS", "\\Seen"),
        ("STORE", "3", "+FLAGS", "\\Seen"),
    ]
