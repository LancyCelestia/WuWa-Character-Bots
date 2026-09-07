from __future__ import annotations

import asyncio
from typing import Any

import aioimaplib
from nonebot.adapters.mail.adapter import Adapter as MailAdapter
from nonebot.adapters.mail.bot import Bot as MailBot
from nonebot.adapters.mail.config import BotInfo
from nonebot.adapters.mail.event import NewMailMessageEvent
from nonebot.adapters.mail.log import log as mail_log
from nonebot.compat import model_dump
from nonebot.utils import escape_tag

_RETRY_DELAYS = (3.0, 6.0, 12.0, 24.0, 48.0, 60.0)


def mail_retry_delay(attempt: int) -> float:
    """Return a bounded delay before the next IMAP connection attempt."""
    index = max(0, int(attempt))
    return _RETRY_DELAYS[min(index, len(_RETRY_DELAYS) - 1)]


async def mark_mail_seen(imap_client: Any, uid: str) -> None:
    """Mark one fetched IMAP UID as seen without exposing adapter internals."""
    response = await imap_client.store(str(uid), "+FLAGS", r"\Seen")
    if str(getattr(response, "result", "OK")).upper() != "OK":
        raise RuntimeError("IMAP STORE Seen failed")


class QuietMailMessageEvent(NewMailMessageEvent):
    """Mail event whose adapter log description never includes message content."""

    def get_event_description(self) -> str:
        sender = getattr(self.sender, "id", "unknown")
        return escape_tag(f"Message {self.id} from {sender}: subject={self.subject}")


QuietMailMessageEvent.__module__ = NewMailMessageEvent.__module__


def _task_done(task: asyncio.Task[Any], *, label: str) -> None:
    if task.cancelled():
        return
    try:
        exception = task.exception()
    except Exception as exc:  # noqa: BLE001 - task inspection must never escape.
        mail_log("ERROR", f"Mail {label} task inspection failed: {type(exc).__name__}")
        return
    if exception is not None:
        mail_log("ERROR", f"Mail {label} task failed: {type(exception).__name__}")


class ResilientMailAdapter(MailAdapter):
    """Mail adapter with reconnecting IMAP workers and explicit Seen flags."""

    def _track_task(self, coroutine: Any, *, label: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def done_callback(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            _task_done(done, label=label)

        task.add_done_callback(done_callback)
        return task

    async def startup(self) -> None:
        for bot_info in self.mail_config.mail_bots:
            self._track_task(self.run_bot(bot_info), label=str(bot_info.id))

    async def run_bot(self, bot_info: BotInfo) -> None:
        bot = MailBot(self, bot_info.id, bot_info)
        await self._check_mailbox(bot)

    async def shutdown(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _new_imap_client(self, bot_info: BotInfo) -> Any:
        if bot_info.imap.tls:
            return aioimaplib.IMAP4_SSL(
                host=bot_info.imap.host,
                port=bot_info.imap.port,
            )
        return aioimaplib.IMAP4(
            host=bot_info.imap.host,
            port=bot_info.imap.port,
        )

    async def _close_mailbox(self, bot: MailBot) -> None:
        client = getattr(bot, "imap_client", None)
        bot.imap_client = None
        if client is None:
            return
        try:
            await client.logout()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the worker error.
            mail_log("DEBUG", f"Mail cleanup logout skipped: {type(exc).__name__}")
        protocol = getattr(client, "protocol", None)
        close = getattr(protocol, "close", None)
        if callable(close):
            try:
                await close()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask worker errors.
                mail_log("DEBUG", f"Mail cleanup close skipped: {type(exc).__name__}")

    async def _check_mailbox(self, bot: MailBot) -> None:
        bot_info = bot.bot_info
        attempt = 0
        connected = False
        while True:
            try:
                bot.imap_client = self._new_imap_client(bot_info)
                if not await bot.login():
                    raise RuntimeError("IMAP authentication rejected")
                if not await bot.select_mailbox():
                    raise RuntimeError("IMAP mailbox selection failed")
                self.bot_connect(bot)
                connected = True
                attempt = 0
                while True:
                    await self._fetch_new_mail(bot)
                    await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep worker alive and logs concise.
                delay = mail_retry_delay(attempt)
                mail_log(
                    "ERROR",
                    f"Mail {bot.self_id} worker error: {type(exc).__name__}; retry_in={delay:g}s",
                )
                attempt += 1
            finally:
                if connected:
                    try:
                        self.bot_disconnect(bot)
                    except Exception as exc:  # noqa: BLE001 - cleanup must not mask worker errors.
                        mail_log("DEBUG", f"Mail bot disconnect skipped: {type(exc).__name__}")
                    connected = False
                await self._close_mailbox(bot)
            await asyncio.sleep(mail_retry_delay(attempt - 1))

    async def _fetch_new_mail(self, bot: MailBot) -> None:
        if bot.mailbox != "INBOX" or bot.readonly or bot.imap_client is None:
            return
        response = await bot.imap_client.search("UNSEEN")
        if response.result != "OK":
            raise RuntimeError("IMAP UNSEEN search failed")
        if not response.lines or not response.lines[0]:
            return
        uids = response.lines[0].decode().split()
        for uid in uids:
            mail = await bot.fetch_mail_of_uid(uid)
            if mail is None:
                continue
            await mark_mail_seen(bot.imap_client, uid)
            event = QuietMailMessageEvent(**model_dump(mail))
            self._track_task(bot.handle_event(event), label=f"{bot.self_id} event")
