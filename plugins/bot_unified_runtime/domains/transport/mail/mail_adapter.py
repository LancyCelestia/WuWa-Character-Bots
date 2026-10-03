from __future__ import annotations

import asyncio
import re
import traceback
from collections.abc import Callable
from email.header import decode_header, make_header
from email.utils import getaddresses
from typing import Any

import aioimaplib
from nonebot.adapters.mail.adapter import Adapter as MailAdapter
from nonebot.adapters.mail.bot import Bot as MailBot
from nonebot.adapters.mail.config import BotInfo
from nonebot.adapters.mail.event import NewMailMessageEvent
from nonebot.adapters.mail.log import log as mail_log
from nonebot.adapters.mail.utils import parse_byte_mail
from nonebot.compat import model_dump
from nonebot.utils import escape_tag

from plugins.bot_unified_runtime.domains.transport.mail.mail_dns_policy import (
    guard_mail_hosts,
    mail_hosts_from_bot_infos,
)
from plugins.bot_unified_runtime.domains.transport.mail.mail_ingress_files import (
    build_attachment_context,
)

_RETRY_DELAYS = (3.0, 6.0, 12.0, 24.0, 48.0, 60.0)
# R2（2026-09-17 实弹）：``UNSEEN`` 搜索挂死（服务器/代理半开连接）不再无限
# 等——单次硬超时 + 同连接短退避重试一次；重试仍超时则抛回外层
# ``_check_mailbox`` 整链重连（重连路径 ``bot.mailbox = None`` 清早退缓存后
# 真发 SELECT，即 a3e78a3 的修复，保持生效）。连续超时的日志由外层既有
# 稀疏化（1,2,4,8...）承载，不刷屏。
_MAIL_SEARCH_TIMEOUT_SECONDS = 15.0
# IMAP 连接/命令等待地板（S-MAIL-IMAP-TIMEOUT）：不传就吃 aioimaplib 库内 10s 硬顶。
# 2026-09-28 订正归因：当时写的是"冷 DNS 首查 15–16s"，重测 DNS 只要 11ms，
# 那 12–16s 是 **IPv6 黑洞**（qq.com 的 AAAA 排在前且不可达）把连接拖出来的。
# 现在由 mail_dns_policy 把邮件主机限定成 IPv4，地板 30s 退成弱网余量、不再是成败判据。
# 详见 ``ResilientMailAdapter._new_imap_client`` 与 ``mail_dns_policy`` 的模块注释。
_MAIL_IMAP_TIMEOUT_SECONDS = 30.0
_MAIL_SEARCH_RETRY_DELAYS = (2.0,)


def mail_retry_delay(attempt: int) -> float:
    """Return a bounded delay before the next IMAP connection attempt."""
    index = max(0, int(attempt))
    return _RETRY_DELAYS[min(index, len(_RETRY_DELAYS) - 1)]


def describe_mail_error(exc: BaseException, limit: int = 160) -> str:
    """One-line, human-readable summary of an IMAP failure.

    只记 ``type(exc).__name__`` 会让线上故障无法定位——2026-09-14 实测的
    「worker error: Abort」就是一例：类名之外没有任何信息，既看不出是
    状态机非法命令、还是取信/标已读失败。摘要取首行并截断，避免把整封
    邮件内容带进日志。
    """
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    first = text.splitlines()[0].strip()
    return f"{type(exc).__name__}: {first[:limit]}"


async def mark_mail_seen(imap_client: Any, uid: str) -> None:
    """Mark one fetched IMAP UID as seen without exposing adapter internals.

    必须走 ``UID STORE``：``aioimaplib`` 的 ``store()`` 默认 ``by_uid=False``
    （``aioimaplib.py:540`` 与 ``:749``），会把 UID 当**序号**发给服务器——
    既可能标错邮件，也会在 UID 超出当前邮件数时报 "IMAP STORE Seen failed"。
    UID 命令要求连接处于 SELECTED 状态（``aioimaplib.py:93``）。
    """
    response = await imap_client.uid("STORE", str(uid), "+FLAGS", r"\Seen")
    if str(getattr(response, "result", "OK")).upper() != "OK":
        raise RuntimeError("IMAP UID STORE Seen failed")


def decode_rfc2047_display_name(raw: str) -> str:
    """RFC2047 编码字显示名 → 人话；无编码字/解不动 ⇒ 原值原样回（席9R）。

    库侧 ``parse_byte_mail``（mailparser）对 B/Q/折叠/贴地址等**规范编码字**实测
    能解，但对畸形编码字会留原串、对裸非 ASCII 显示名则 name 落空串（整串被塞进
    ``sender.id``）。摄取链在此统一兜一道：``decode_header``+``make_header`` 是
    幂等 pass——已解名逐字节不变；未知字符集（LookupError）/畸形串抛错 ⇒ 按档
    回退原值。只动显示名；本函数自身对地址（``sender.id``）一字不改（裸名族
    地址侧恢复另见 ``restore_mail_sender_address``，席35）；内部吞异常，绝不打断收信。
    """
    text = str(raw or "").strip()
    if not text:
        return text
    try:
        return str(make_header(decode_header(text)))
    except Exception:  # noqa: BLE001 - 解码失败按档回退原值，不区分异常族。
        return text


#: 单枚完整编码字（含可选折叠空白）：裸名族垃圾 id 的形态签名。
_MAIL_ENCODED_WORD_ONLY_RE = re.compile(
    r"^=\?[^?\s]{2,}\?[bBqQ]\?[\w+/=\-\s]*\?=$", re.ASCII
)


def restore_mail_sender_address(sender_name: str, sender_id: str) -> tuple[str, str]:
    """裸名族地址侧恢复（席35，2026-10-03 用户授权）：mailparser 塞错的 id 拆回「名+址」。

    实测（``parse_byte_mail``，2026-10-03）：``From: 阿澜 <lan@example.com>``
    （显示名未按 RFC2047 编码，国内客户端常见）⇒ ``sender.name=''``、
    ``sender.id``＝**整条 From 值重打的 base64 编码字垃圾**
    （``'=?utf-8?b?…?='``）。会话身份/防冒名面（roles/affinity/memory 裸键）
    吃的就是这段垃圾。这里只恢复**地址判定依据**：

    - 介入签名＝name 为空且 id 是单枚完整编码字（正常解析一律不进本腿）；
    - 编码字解出「显示名 <地址>」且地址带 ``@`` ⇒ ``(显示名, 真实地址)``；
    - 任何一步解不动／无地址形（含纯名无址、裸 token 无 @）⇒ 原值原样回，
      保持现行为，绝不炸摄取链；
    - 正常 ``name <addr>``／裸地址／多址解析一字不动（多址取首个带 @ 的作者，
      RFC 5322 首作者语义；``parseaddr`` 拒吃逗号列表 ⇒ 用 ``getaddresses``）。
    """
    name = str(sender_name or "").strip()
    raw_id = str(sender_id or "").strip()
    if name or not raw_id or not _MAIL_ENCODED_WORD_ONLY_RE.match(raw_id):
        return name, raw_id
    try:
        decoded = str(make_header(decode_header(raw_id)))
    except Exception:  # noqa: BLE001 - 解不动保持现行为（与显示名腿同口径）。
        return name, raw_id
    if decoded == raw_id or "<" not in decoded or ">" not in decoded:
        return name, raw_id
    for display, address in getaddresses([decoded]):
        address = address.strip()
        if address and "@" in address:
            return display.strip(), address
    return name, raw_id


async def fetch_mail_by_uid(imap_client: Any, uid: str) -> Any | None:
    """Fetch one mail strictly by UID (``UID FETCH``).

    适配器的 ``Bot.fetch_mail_of_uid`` 走 ``imap_client.fetch(uid, "(RFC822)")``，
    而 ``aioimaplib.IMAP4.fetch`` 默认 ``by_uid=False``
    （``nonebot/adapters/mail/bot.py:411`` + ``aioimaplib.py:758``）→ 实际发出的是
    普通 ``FETCH <uid>``，把 UID 当序号用。UID 与序号一旦错位（删信、移动、
    服务器重排后必然错位），就会取错信或整封取不到。这里改用 UID 变体。
    """
    response = await imap_client.uid("FETCH", str(uid), "(RFC822)")
    if str(getattr(response, "result", "")).upper() != "OK":
        raise RuntimeError("IMAP UID FETCH failed")
    lines = getattr(response, "lines", None) or []
    if len(lines) < 2:
        return None
    mail = parse_byte_mail(lines[1])
    # 席9R（2026-10-03）：库侧只解部分形制的 RFC2047（畸形编码字留原串）⇒ 摄取点
    # 统一兜底解显示名。席35（同日用户授权）补地址侧：裸非 ASCII 显示名的整串
    # 编码字垃圾 id 拆回「名+址」。两腿解不动都回原值、绝不打断收信（与头块腿
    # 同口径）；先算后赋，任何半途异常都不会把 sender 留在半改状态。
    try:
        sender = getattr(mail, "sender", None)
        if sender is not None:
            raw_name = str(getattr(sender, "name", "") or "")
            raw_id = str(getattr(sender, "id", "") or "")
            split_name, split_id = restore_mail_sender_address(raw_name, raw_id)
            restored_name = decode_rfc2047_display_name(split_name)
            if restored_name != raw_name or split_id != raw_id:
                sender.name = restored_name
                sender.id = split_id
    except Exception as exc:  # noqa: BLE001 - 咽喉处只记录、绝不丢信。
        mail_log(
            "DEBUG",
            f"Mail sender identity decode skipped uid={uid}: {describe_mail_error(exc)}",
        )
    return mail


async def search_unseen_with_backoff(
    imap_client: Any,
    *,
    attempts: int = 2,
    timeout_seconds: float = _MAIL_SEARCH_TIMEOUT_SECONDS,
    retry_delays: tuple[float, ...] = _MAIL_SEARCH_RETRY_DELAYS,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> Any:
    """带超时与退避的 ``UNSEEN`` 搜索（R2，治 mail_adapter.py:223 TimeoutError 挂死）。

    单次搜索套 ``asyncio.wait_for`` 硬超时；超时/失败按 ``retry_delays``
    退避后在同连接重试（IMAP 命令带 tag，迟到响应不会错配后续命令）。
    重试预算耗尽仍失败则原样抛出——由外层 ``_check_mailbox`` 走整链重连，
    重连即强制重新 ``select_mailbox``（且重连路径先清 ``bot.mailbox`` 早退
    缓存，a3e78a3 修复语义不变）。
    """
    safe_attempts = max(1, int(attempts))
    last_exc: BaseException | None = None
    for attempt in range(safe_attempts):
        try:
            return await asyncio.wait_for(
                imap_client.search("UNSEEN"), timeout=timeout_seconds
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 超时/连接态异常统一走退避。
            last_exc = exc
            mail_log(
                "DEBUG",
                f"Mail UNSEEN search attempt {attempt + 1}/{safe_attempts} failed: "
                f"{describe_mail_error(exc)}",
            )
            if attempt >= safe_attempts - 1:
                break
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            await sleep(float(delay))
    assert last_exc is not None
    raise last_exc


class QuietMailMessageEvent(NewMailMessageEvent):
    """Mail event whose adapter log description never includes message content."""

    def get_event_description(self) -> str:
        sender = getattr(self.sender, "id", "unknown")
        return escape_tag(f"Message {self.id} from {sender}: subject={self.subject}")


QuietMailMessageEvent.__module__ = NewMailMessageEvent.__module__


#: 信头文本块的长度帽：显示名/地址表再长也只带这么多进会话（有界注入）。
_MAIL_HEADER_BLOCK_CHARS = 400


def _mail_header_address(user: Any) -> str:
    """适配器 User（对象或 model_dump 后的 dict）→ 裸地址；读不出给空串。

    To/Cc 刻意**只报地址、不带名字**：名字是第三方自填串（可伪装面），而这一块
    的用途是「这封信还发给了谁」——地址已足够，暴露面收窄一格。
    """
    if isinstance(user, dict):
        return str(user.get("id") or "").strip()
    return str(getattr(user, "id", "") or "").strip()


def build_mail_header_block(mail: Any) -> str:
    """一封邮件 → 信头元数据文本块（From 显示名 / To / Cc）；无内容回空串。

    票 **T-META-INGEST-1**（2026-10-03 检索与知识波）的摄取侧落点：这些字段
    适配器逐封解得出，但 ``IncomingMessage`` 的契约位没带（契约面本席禁写），
    所以以**随信文本块**进会话——根侧一行不改，模型看信即见。
    消毒口径：From 显示名是**对方自填串**（RTL/零宽/同形可伪装），进块前过
    ``sanitize_display_name``（消毒唯一真身；惰性导入避开环，group_info 的
    display_guard 同一先例）；To/Cc 只带 RFC 解析产物地址。
    本块是信件自身的头部元数据，**不是文件正文**，不走 T2 ``label_file_body``
    ——T2 打标口径不变。任何单字段读不出就跳过该字段，绝不抛出。
    """
    parts: list[str] = []
    raw_name = str(getattr(getattr(mail, "sender", None), "name", "") or "").strip()
    if raw_name:
        from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
            sanitize_display_name,
        )

        display = sanitize_display_name(raw_name, surface="mail_header_block")
        if display:
            parts.append(f"发件人显示名：{display}")
    for attr, label in (("recipients_to", "收件人（To）"), ("recipients_cc", "抄送（Cc）")):
        rows = getattr(mail, attr, None)
        addresses = [
            item
            for item in (
                _mail_header_address(row)
                for row in (rows if isinstance(rows, (list, tuple)) else ())
            )
            if item
        ]
        if addresses:
            parts.append(f"{label}：{'、'.join(addresses)}")
    if not parts:
        return ""
    block = "[邮件信头] " + "；".join(parts)
    if len(block) > _MAIL_HEADER_BLOCK_CHARS:
        block = block[:_MAIL_HEADER_BLOCK_CHARS] + "…"
    return block


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

    def __init__(self, driver: Any) -> None:
        super().__init__(driver)
        # F2 在飞门名册：(bot.self_id, uid) → 已派发未回执的邮件。
        # 只拒绝同一封的并发重复派发（\Seen 后置后 UNSEEN 可见窗变宽），
        # 不作去重账——去重真身＝中央事件幂等表 + MailBridgeState（SEAT-MAILINGRESS F6）。
        self._inflight_uids: set[tuple[str, str]] = set()

    def _track_task(self, coroutine: Any, *, label: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def done_callback(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            _task_done(done, label=label)

        task.add_done_callback(done_callback)
        return task

    async def startup(self) -> None:
        # 收/发两条腿都要在**建连接之前**拿到 IPv4 护栏：发信侧的 ``aiosmtplib.send()``
        # 是上游适配器内部造的（nonebot/adapters/mail/bot.py:226），本仓没有建造点，
        # 只在 ``_new_imap_client`` 补就漏掉发信那一腿。护栏按主机名生效，非邮件主机透传。
        guard_mail_hosts(mail_hosts_from_bot_infos(self.mail_config.mail_bots))
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
        # S-MAIL-IMAP-TIMEOUT（2026-09-28 二次现算，订正归因）：这两支此前不传 timeout
        # ⇒ 吃 ``aioimaplib`` 库内 ``TIMEOUT_SECONDS = 10.0`` 硬顶，问候语等待直接
        # ``TimeoutError``。当时的注释写成"冷 DNS 首查 15–16s"，那是**误判**：
        # 本机重测 ``getaddrinfo("imap.qq.com")`` 首次 11ms、缓存后 0ms，DNS 不慢。
        # 慢的是 IPv6 黑洞 —— ``imap.qq.com`` 有 AAAA 且排在前面，v6 连接要等满超时
        # 才回退 v4（强制 v6 = TimeoutError 6.0s；强制 v4 = 150ms，TLS 全程 <0.5s）。
        # 正解是把邮件主机限定成 IPv4（``mail_dns_policy``，收/发两腿在 startup 已装）；
        # 这里再兜一次是幂等的，防的是"没走 startup 直接造客户端"的测试与降级路径。
        # 地板留 30s 不再参与决定成败，只当弱网余量。
        guard_mail_hosts({bot_info.imap.host, bot_info.smtp.host})
        if bot_info.imap.tls:
            return aioimaplib.IMAP4_SSL(
                host=bot_info.imap.host,
                port=bot_info.imap.port,
                timeout=_MAIL_IMAP_TIMEOUT_SECONDS,
            )
        return aioimaplib.IMAP4(
            host=bot_info.imap.host,
            port=bot_info.imap.port,
            timeout=_MAIL_IMAP_TIMEOUT_SECONDS,
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
        # S-MAIL-IMAP-TIMEOUT 后半段（2026-09-28）：光记 TimeoutError 答不出「卡在哪一段」。
        # 上游实测健康（imap.qq.com:993 空闲时 0.17s 回 * OK），而本机冷 DNS 首查要 15–16s，
        # 两者都会在同一个 except 里长成同一句「worker error: TimeoutError」。这里逐段记名，
        # 下次再抖就能一眼分清是连接/问候、登录、选箱还是收信阶段——不用再来一轮猜。
        while True:
            stage = "connect"  # 每轮重试都重新归位：否则第二轮的登录超时会挂着上一轮的 stage=fetch
            try:
                bot.imap_client = self._new_imap_client(bot_info)
                stage = "login"
                if not await bot.login():
                    raise RuntimeError("IMAP authentication rejected")
                stage = "select"
                # 适配器 select_mailbox 带跨连接早退缓存（venv nonebot/adapters/mail/
                # bot.py:363）：self.mailbox 与 readonly 均未变就直接返回 True、不发
                # SELECT。mailbox 在 __init__ 置 None（bot.py:65），真选箱成功后才写
                # "INBOX"（bot.py:392）。本循环每轮重连都新建 IMAP 连接但复用同一
                # MailBot，残留缓存会让新连接跳过 SELECT 停在 AUTH 态，SEARCH 即报
                # "Abort: command SEARCH illegal in state AUTH"（2026-09-14 线上实测，
                # 每 3s 死循环）。清缓存强制每次新连接真发一次 SELECT。
                bot.mailbox = None
                bot.readonly = False
                if not await bot.select_mailbox():
                    raise RuntimeError("IMAP mailbox selection failed")
                self.bot_connect(bot)
                connected = True
                attempt = 0
                stage = "fetch"
                while True:
                    await self._fetch_new_mail(bot)
                    await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep worker alive and logs concise.
                delay = mail_retry_delay(attempt)
                detail = describe_mail_error(exc)
                # 断网期重试可能持续数十次：日志按 1,2,4,8... 稀疏化，其余 DEBUG，
                # 避免每次退避都刷一条 ERROR（状态并未变化）。
                # 首次失败额外附完整栈——只记异常类名的日志无法定位，2026-09-14
                # 线上「worker error: Abort」就是这么卡住的。
                if attempt == 0:
                    mail_log(
                        "ERROR",
                        f"Mail {bot.self_id} worker error: {detail}; retry_in={delay:g}s; stage={stage}\n"
                        + traceback.format_exc(),
                    )
                elif attempt <= 1 or (attempt & (attempt - 1)) == 0:
                    mail_log(
                        "ERROR",
                        f"Mail {bot.self_id} worker error: {detail}; retry_in={delay:g}s; stage={stage}",
                    )
                else:
                    mail_log(
                        "DEBUG",
                        f"Mail {bot.self_id} retry x{attempt + 1}: {detail}; retry_in={delay:g}s; stage={stage}",
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
        # R2：UNSEEN 搜索带超时+退避；重试耗尽仍超时即抛出，外层
        # _check_mailbox 整链重连并强制重新 select_mailbox（见 helper 注释）。
        response = await search_unseen_with_backoff(
            bot.imap_client,
            attempts=1 + len(_MAIL_SEARCH_RETRY_DELAYS),
            timeout_seconds=_MAIL_SEARCH_TIMEOUT_SECONDS,
            retry_delays=_MAIL_SEARCH_RETRY_DELAYS,
        )
        if response.result != "OK":
            raise RuntimeError("IMAP UNSEEN search failed")
        if not response.lines or not response.lines[0]:
            return
        uids = response.lines[0].decode().split()
        for uid in uids:
            inflight_key = (str(bot.self_id), str(uid))
            try:
                if inflight_key in self._inflight_uids:
                    # F2 在飞门：\Seen 后置后，派发未完成的邮件仍是 UNSEEN、会被
                    # 下一轮 poll 再搜到——同一封的并发重复派发在这里拒绝。中央事件
                    # 幂等表（mail|bot|Message-ID）仍是第二层，本处不另建去重账。
                    continue
                # 必须走 UID FETCH：适配器 fetch_mail_of_uid 是按序号寻址的普通
                # FETCH，错位即取错信/取不到（详见 fetch_mail_by_uid 文档）。
                mail = await fetch_mail_by_uid(bot.imap_client, uid)
                if mail is None:
                    continue
                payload = model_dump(mail)
                # T-META-INGEST-1（2026-10-03 检索与知识波）：From 显示名/To/Cc 以
                # 信头文本块随信进会话（契约位不变、根侧零改动）。T2 打标口径不变：
                # 这一块是信件自身的头部元数据、不是文件正文，不进 label_file_body；
                # 显示名在 build_mail_header_block 内过 sanitize_display_name。
                # 任何失败只丢这一块，绝不打断收信（与附件腿同一口径）。
                try:
                    header_block = build_mail_header_block(mail)
                except Exception as exc:  # noqa: BLE001 - 头块坏了也不丢邮件
                    mail_log(
                        "WARNING",
                        f"Mail {bot.self_id} header block skipped uid={uid}: "
                        f"{describe_mail_error(exc)}",
                    )
                    header_block = ""
                if header_block and isinstance(payload.get("message"), list):
                    payload["message"].insert(
                        0, {"type": "text", "data": {"text": header_block}}
                    )
                # 需求 16②：附件字节在这一刻还在手上（model_dump 之后段还是段），
                # 就在这颗咽喉取文 + 逐份 T2 打标，取到什么一律并成 text 段交下游，
                # 根侧一行不必改。任何失败只让这一段变成一句人话，绝不打断收信。
                try:
                    blocks = await asyncio.to_thread(
                        build_attachment_context,
                        mail.message,
                        request_id=str(getattr(mail, "id", "") or ""),
                    )
                except Exception as exc:  # noqa: BLE001 - 取文机制坏了也不丢邮件
                    mail_log(
                        "WARNING",
                        f"Mail {bot.self_id} attachment leg skipped uid={uid}: "
                        f"{describe_mail_error(exc)}",
                    )
                    blocks = []
                if blocks and isinstance(payload.get("message"), list):
                    payload["message"].append(
                        {"type": "text", "data": {"text": "\n".join(blocks)}}
                    )
                event = QuietMailMessageEvent(**payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad mail must not kill the connection.
                # F2 修复腿①：构造/取文炸 ⇒ **不标 \Seen**，本封下一轮重投（旧形制
                # \Seen 先落定＝永久静默丢信）。告警走本文件既有咽喉 mail_log＋
                # describe_mail_error（首行截断、可读、零正文、非裸 print）。
                mail_log(
                    "ERROR",
                    f"Mail {bot.self_id} prepare uid={uid} failed, will retry: "
                    f"{describe_mail_error(exc)}",
                )
                continue
            self._inflight_uids.add(inflight_key)
            # F2 修复腿②：派发成功（handle_event 正常返回）后才回执 \Seen，
            # 见 _dispatch_and_ack_seen；并发面不变——派发仍是 tracked task。
            self._track_task(
                self._dispatch_and_ack_seen(bot, uid, event, inflight_key),
                label=f"{bot.self_id} event",
            )

    async def _dispatch_and_ack_seen(
        self,
        bot: MailBot,
        uid: str,
        event: QuietMailMessageEvent,
        inflight_key: tuple[str, str],
    ) -> None:
        r"""派发先落定、`\Seen` 后回执（F2：at-most-once → at-least-once）。

        `handle_event` 抛错 ⇒ 不标已读，本封下轮 poll 重投；重投的重复副作用由
        双层幂等挡（中央事件幂等表 + MailBridgeState 持久 claim，SEAT-MAILINGRESS
        F6 在册——这条安全网正是为今日翻序预铺的）。回执 `\Seen` 失败只出声不阻断
        （文本已投出，重投同样被幂等表去重）。任何失败路径都留 mail_log ERROR
        可读告警；finally 清在飞门，异常不 escaping（tracked task 炸＝worker 杀）。
        """
        try:
            try:
                await bot.handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单封派发失败不杀 worker。
                mail_log(
                    "ERROR",
                    f"Mail {bot.self_id} dispatch uid={uid} failed, will retry: "
                    f"{describe_mail_error(exc)}",
                )
                return
            try:
                await mark_mail_seen(bot.imap_client, uid)
            except Exception as exc:  # noqa: BLE001 - 已投递，回执失败只出声。
                mail_log(
                    "ERROR",
                    f"Mail {bot.self_id} seen-ack uid={uid} failed: "
                    f"{describe_mail_error(exc)}",
                )
        finally:
            self._inflight_uids.discard(inflight_key)
