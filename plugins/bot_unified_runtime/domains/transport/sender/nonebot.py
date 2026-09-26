from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr
from html import escape as _html_escape
from pathlib import Path
from typing import Any, Literal

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    new_debug_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
    DeadlineExceeded,
    apply_request_deadline,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FileSource,
    FileTransferError,
    # FinalTransferError 不在此导入：它是 FileTransferError 的子类，本文件只按
    # ``exc.kind`` 归因，两型走同一条 except 分支（导入即 F401 未用）。
    MailEnvelope,
    get_default_file_gateway,
)
from plugins.bot_unified_runtime.domains.transport.sender.timeout import (
    resolve_transport_timeout,
)
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# Telegram sendPhoto 上限 10MB；sendVoice/sendAudio 走分片上传留出安全余量。
_TG_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_TG_MAX_AUDIO_BYTES = 45 * 1024 * 1024
_TG_VOICE_CACHE_DIR = Path(tempfile.gettempdir()) / "bot_tg_voice"
# 转码缓存有界：按 mtime 只保留最新 N 个文件（.ogg 缓存 + .src 中间产物）。
_TG_VOICE_CACHE_MAX_FILES = 64


class _FinalSendError(Exception):
    """发送前已可判定不可重试的失败（如附件缺失）；对应 FAILED_FINAL。"""


# B-12（A9 残留）：bot_download_proxy 的运行时注入 getter（支持热更新）。
# sender 层拿不到插件运行时 Config 对象，显式注入优先于 bot.config→env 探测。
_download_proxy_provider: Callable[[], str] | None = None


def set_download_proxy_provider(provider: Callable[[], str] | None) -> None:
    global _download_proxy_provider
    _download_proxy_provider = provider


def _resolve_download_proxy(bot: Any) -> str:
    """解析 bot_download_proxy：注入 getter > driver config > 进程 env。

    都取不到时返回空串（直连），不阻断发送。
    """
    if _download_proxy_provider is not None:
        try:
            value = str(_download_proxy_provider() or "").strip()
        except (TypeError, ValueError, OSError, RuntimeError):
            value = ""
        if value:
            return value
    config = getattr(bot, "config", None)
    for attr in ("bot_download_proxy", "BOT_DOWNLOAD_PROXY"):
        value = str(getattr(config, attr, "") or "").strip()
        if value:
            return value
    return os.environ.get("BOT_DOWNLOAD_PROXY", "").strip()


def _telegram_media_parts(content_ref: Any) -> list[dict[str, Any]]:
    parts = content_ref.get("parts", []) if isinstance(content_ref, dict) else []
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict)]


def _telegram_photo_reference(parts: list[dict[str, Any]]) -> str:
    """选可发图源：远程直链优先，其次存在的本地渲染卡（适配器原生读本地转 multipart）。"""
    for part in parts:
        if part.get("type") != "image":
            continue
        candidate = str(part.get("file") or part.get("url") or "").strip()
        if not candidate:
            continue
        if candidate.startswith(("http://", "https://")):
            return candidate
        try:
            local = Path(candidate)
            if local.is_file() and 0 < local.stat().st_size <= _TG_MAX_UPLOAD_BYTES:
                return candidate
        except OSError:
            continue
    return ""


def _voice_cache_path(key: str) -> Path:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return _TG_VOICE_CACHE_DIR / f"{digest}.ogg"


def _sweep_voice_cache() -> None:
    """转码缓存有界清扫：按 mtime 保留最新 N 个文件，超出即删。"""
    try:
        entries = [p for p in _TG_VOICE_CACHE_DIR.iterdir() if p.is_file()]
    except OSError:
        return

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    entries.sort(key=_mtime, reverse=True)
    for path in entries[_TG_VOICE_CACHE_MAX_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def _convert_audio_to_ogg(source: Path, target: Path) -> bool:
    """sendVoice 仅接受 OGG/OPUS，mp3/flac 直发会被 Telegram 拒收，须 ffmpeg 转码。

    ffmpeg 先写 ``.part`` 临时文件再 os.replace 原子落位：并发转码同一目标
    时不会交错出损坏的 .ogg；结束后做一次有界缓存清扫。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tmp_target = target.with_name(target.name + ".part")
    try:
        # 本地语音源路径此前从不预建缓存目录，ffmpeg 会因目录缺失直接失败。
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                str(tmp_target),
            ],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        _sweep_voice_cache()
        return False
    ok = completed.returncode == 0 and tmp_target.is_file() and tmp_target.stat().st_size > 0
    if ok:
        try:
            os.replace(tmp_target, target)
        except OSError:
            ok = False
    if not ok:
        try:
            tmp_target.unlink()
        except OSError:
            pass
    _sweep_voice_cache()
    return ok


async def _download_voice_source(url: str, target: Path, *, proxy: str = "") -> Path | None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx 随 nonebot 必装
        return None
    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(20.0),
        "follow_redirects": True,
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    try:
        # 边下边限流：整包 response.content 会先把 45MB+ 全量吃进内存才判超限。
        async with httpx.AsyncClient(**client_kwargs) as client, client.stream(
            "GET", url
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > _TG_MAX_AUDIO_BYTES:
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > _TG_MAX_AUDIO_BYTES:
                    return None
                chunks.append(chunk)
        if not chunks:
            return None
        _TG_VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"".join(chunks))
        return target
    except Exception:  # noqa: BLE001 - 下载失败时降级为直链 audio，不阻断发送
        return None


def _cleanup_voice_source(raw_ref: str) -> None:
    """发送成功后删除本次下载的 .src 中间产物（.ogg 转码结果保留作缓存）。"""
    ref = (raw_ref or "").strip()
    if not ref:
        return
    try:
        _voice_cache_path(f"{ref}.src").unlink(missing_ok=True)
    except OSError:
        pass


async def _prepare_telegram_voice(
    raw_ref: str,
    *,
    proxy: str = "",
) -> tuple[str, str]:
    """归一化语音源，返回 (引用, 模式)；模式 ∈ {"voice", "audio", "none"}。

    不合规源先经 ffmpeg 落地转 OGG/OPUS；转换不可用时降级 sendAudio
    （mp3 附件仍可直接播放），保证点歌语音在 Telegram 上必有出口。
    """
    ref = (raw_ref or "").strip()
    if not ref:
        return "", "none"
    if ref.startswith(("http://", "https://")):
        if ref.lower().split("?", 1)[0].endswith((".ogg", ".oga")):
            return ref, "voice"
        source = await _download_voice_source(
            ref, _voice_cache_path(f"{ref}.src"), proxy=proxy
        )
        if source is None:
            return ref, "audio"
        target = _voice_cache_path(ref)
        if target.is_file() and target.stat().st_size > 0:
            return str(target), "voice"
        converted = await asyncio.to_thread(_convert_audio_to_ogg, source, target)
        return (str(target), "voice") if converted else (ref, "audio")
    try:
        local = Path(ref)
        if not local.is_file() or not 0 < local.stat().st_size <= _TG_MAX_AUDIO_BYTES:
            return "", "none"
    except OSError:
        return "", "none"
    if local.suffix.lower() in {".ogg", ".oga"}:
        return ref, "voice"
    target = _voice_cache_path(ref)
    if target.is_file() and target.stat().st_size > 0:
        return str(target), "voice"
    converted = await asyncio.to_thread(_convert_audio_to_ogg, local, target)
    return (str(target), "voice") if converted else (ref, "audio")


def _adapter_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    get_name = getattr(adapter, "get_name", None)
    if callable(get_name):
        return str(get_name())
    return str(getattr(adapter, "name", ""))


def _provider_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        value = result.get("message_id") or result.get("id")
    else:
        value = getattr(result, "message_id", None) or getattr(result, "id", None)
    return str(value) if value is not None else None


def _mail_html_body(text: str) -> str:
    """把回复正文包装成邮件 HTML 正文（守岸人配色，内联样式）。

    邮件客户端会剥离 ``<style>`` 块与外链资源，所以这里只用手写内联样式
    与系统字体栈；正文转义后按行转 ``<br>``，保留原排版。纯文本版本由
    ``set_content`` 一并保留，形成 ``multipart/alternative``——不支持 HTML
    的客户端仍能正常阅读。
    """
    body = _html_escape(text).replace("\n", "<br>")
    return (
        "<div style=\"margin:0;padding:18px 20px;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
        "'Microsoft YaHei',sans-serif;"
        "font-size:15px;line-height:1.75;color:#2b2f38;"
        "background:#f4f5f6;border:1px solid #d9e0e7;border-radius:14px;\">"
        f"{body}</div>"
    )


def _build_mail_reply_message(bot: Any, event: Any, text: str) -> EmailMessage:
    bot_info = getattr(bot, "bot_info", None)
    sender_id = str(getattr(bot_info, "id", "") or getattr(bot, "self_id", "")).strip()
    sender_name = str(getattr(bot_info, "name", "") or "").strip()
    recipient = str(getattr(getattr(event, "sender", None), "id", "")).strip()
    subject = str(getattr(event, "subject", "") or "").strip()
    message_id = str(getattr(event, "id", "") or "").strip()
    if not sender_id or not recipient:
        raise ValueError("mail reply requires sender and recipient addresses")
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender_id)) if sender_name else sender_id
    message["To"] = recipient
    message["Subject"] = f"Re: {subject}" if subject else "Re:"
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id
    message.set_content(text)
    message.add_alternative(_mail_html_body(text), subtype="html")
    return message


def _build_mail_attachment_envelope(
    bot: Any, event: Any, body_text: str
) -> MailEnvelope:
    """邮件附件腿的信封（需求 16(3) 三端对齐 · S-T-TGSEND）。

    全部字段只从**事件与 bot 身份**取，没有一枚从会话正文或主题里扫出来——
    与正文腿 ``_build_mail_reply_message`` 取的是同一个地址事实
    （``event.sender.id``），因此附件的可达面**不超过**纯文本回复的可达面：
    只能把附件回给写过信给我们的那个人，会话里写「顺便发到 attacker@…」
    改不了投递面。

    ``recipients_allowlisted`` 只有这一枚事件来源的地址，而不是配置名册：
    名册需要 ``config.py`` 新键（本席禁写面），上交主会话，见席位报告 §伍。
    在那之前，``FileTransferGateway._deliver_mail`` 的
    ``resolve_mail_recipient`` 仍然真执法——它拿 ``send_request.target_id``
    与本名册比对，两者不一致（管线把请求路由到了别处）就整件拒发，
    **绝不静默改投**。

    ``daily_count`` 留 ``None``：日限执法要跨进程计数状态，真身归装配层。
    网关在 ``None`` 时放行但记一行日志，绝不把「没接计数器」读成「额度还剩」。
    """
    bot_info = getattr(bot, "bot_info", None)
    sender_address = str(
        getattr(bot_info, "id", "") or getattr(bot, "self_id", "") or ""
    ).strip()
    sender_name = str(getattr(bot_info, "name", "") or "").strip()
    recipient = str(getattr(getattr(event, "sender", None), "id", "") or "").strip()
    subject = str(getattr(event, "subject", "") or "").strip()
    return MailEnvelope(
        recipients_allowlisted=(recipient,) if recipient else (),
        subject=f"Re: {subject}" if subject else "",
        body_text=body_text,
        sender_address=sender_address,
        sender_name=sender_name,
        daily_count=None,
    )


async def send_nonebot_message(
    bot: Any,
    event: Any,
    send_request: SendRequest,
    *,
    timeout_seconds: float | None = None,
) -> DeliveryReceipt:
    """Send a rendered text response through Telegram or Mail safely.

    Rich OneBot output keeps using its dedicated sender. Telegram uses the
    adapter-native ``Bot.send`` API; Mail builds a standards-compliant reply
    message directly because the adapter's default From header is rejected by
    some SMTP servers.
    """

    adapter_name = _adapter_name(bot).strip().lower()
    if adapter_name == "telegram":
        transport = "telegram"
        kwargs: dict[str, object] = {}
    elif adapter_name == "mail":
        transport = "mail.smtp"
        kwargs = {"reply": True}
    elif adapter_name == "console":
        transport = "console"
        kwargs = {}
    else:
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=adapter_name or "nonebot",
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage="runtime",
                kind="unsupported_adapter",
                retryable=False,
                safe_summary="unsupported_adapter",
                debug_id=debug_id,
            ),
        )

    text = str(send_request.content.text_fallback or "").strip()
    media_parts = _telegram_media_parts(send_request.content.content_ref)
    has_tg_media = adapter_name == "telegram" and any(
        part.get("type") in {"image", "record", "voice", "file", "video"}
        for part in media_parts
    )
    # 无正文只带附件的邮件请求不得被当成空内容跳过（S-T-TGSEND · 需求 16(3)）：
    # 旧判据只认 Telegram 有媒体，于是「只发一个文件到邮箱」当场 SKIPPED、
    # 回执 SENT 语义皆无，附件无声消失。邮件侧只有**附件**这一条媒体腿
    # （图片/语音/视频在邮件上没有真身），故这里只放宽 file 一族，
    # 不顺手把邮件的图/音/视频也宣称为可发。
    has_mail_file = adapter_name == "mail" and any(
        part.get("type") == "file" for part in media_parts
    )
    if not text and not has_tg_media and not has_mail_file:
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.SKIPPED,
            transport=transport,
            public_message="",
        )

    # 部件级进度：已成功发出的媒体部件数。>0 时异常按结果未知终态处理，
    # 上游不再整体重试（否则会把已送达图片/文件重发一遍）。
    delivered_parts = 0
    download_proxy = _resolve_download_proxy(bot)

    async def _send() -> Any:
        nonlocal delivered_parts
        parts = media_parts
        # remaining 取代闭包 text：caption 随图发出后置空，避免同一段正文重复发送。
        remaining = text
        files = [part for part in parts if part.get("type") == "file"]
        if files:
            if adapter_name not in {"telegram", "mail"}:
                # 附件只有 Telegram 文档腿与邮件附件腿两条真身（file_gateway
                # ._deliver_telegram_document / ._deliver_mail）。第三条通道必须
                # 终态失败：旧写法抛 RuntimeError 落进通用 except ⇒
                # FAILED_RETRYABLE，队列把一条**永远发不出去**的消息反复重投到
                # 预算耗尽才记 result_unknown——用户等满超时、日志只有一行
                # ``send_failed``（台账 #29⑪ 同口径的「失败被压成一行」）。
                raise _FinalSendError("file_unsupported_adapter")
            transport_name: Literal["telegram", "mail"] = (
                "telegram" if adapter_name == "telegram" else "mail"
            )
            envelope = (
                _build_mail_attachment_envelope(bot, event, remaining)
                if transport_name == "mail"
                else None
            )
            result: Any = None
            # B3 阶段 1：附件统一经 FileTransferGateway 投递；缺失/超 2MB 的
            # 不可重试判定、caption 截 1000 字、读全量字节、回执缺失按失败
            # 的语义逐行等价搬运（见 file_gateway._deliver_telegram_document）。
            gateway = get_default_file_gateway()
            for part_index, part in enumerate(files):
                try:
                    ticket = gateway.stage(
                        FileSource(
                            source_kind="path",
                            path=str(part.get("file") or ""),
                            name=str(part.get("name") or ""),
                        ),
                        request_id=send_request.request_id,
                    )
                    file_receipt = await gateway.deliver(
                        bot,
                        ticket,
                        target=send_request,
                        transport=transport_name,
                        part_index=part_index,
                        caption=remaining[:1000],
                        mail_envelope=envelope,
                    )
                except FileTransferError as exc:
                    # 逐因归因（S-T-TGSEND · 台账 #29⑪ 同口径）：旧写法在这里
                    # 把网关的全部失败分类压成一枚定串 "invalid generated
                    # attachment"，于是「路径域判定拒绝」（path_domain_denied）与
                    # 「文件真的不在了」（missing_file）在管理员告警与诊断卡上
                    # 长得一模一样，用户端也只看到一句含糊的「附件无效」。
                    # 完整分类清单的真身＝``FileTransferError`` 自己的 docstring
                    # （file_gateway.py:89-101，本处刻意不抄枚数——抄一次就过期一次）。
                    # QQ 腿从来就是这样（sender/onebot.py:599 用 ``str(exc.kind)``）
                    # ⇒ 同一条铁律两腿一执行一没执行，属实现漂移而非设计。
                    # 行为影响面如实：``FinalTransferError`` 是子类、kind 同字段，
                    # 故 _deliver_telegram_document 自抛的那枚串逐字不变；
                    # **变掉的是 stage 阶段**——「文件不在场」从定串改为
                    # "missing_file"，tests/test_file_gateway_phase1.py:525 的
                    # 断言随之改判（黄金语义 failed_final ∧ 绝不发出未放宽）。
                    raise _FinalSendError(str(exc.kind)) from exc
                result = file_receipt.provider_result
                delivered_parts += 1
                if transport_name == "telegram" and not file_receipt.provider_file_id:
                    raise RuntimeError("telegram attachment receipt missing")
                # 邮件腿**不得**照抄上一条：SMTP 出口本就不回消息号
                # （适配器 ``send_mail`` 返回 None），拿「无 provider_file_id」
                # 判失败会让邮件附件一次都发不出去（file_gateway:770 已点名）。
            # 附件与随件正文已在这一条消息里一并投递，正文不得再单独发一轮。
            return result
        result = None
        if adapter_name == "telegram":
            # 图文同发：远程直链或本地渲染卡均可作 photo（适配器原生 multipart）。
            photo_ref = _telegram_photo_reference(parts)
            send_photo = getattr(bot, "send_photo", None)
            if photo_ref and callable(send_photo):
                try:
                    if len(remaining) <= 1024:
                        result = await send_photo(
                            chat_id=send_request.target_id,
                            photo=photo_ref,
                            caption=remaining or None,
                        )
                        remaining = ""
                    else:
                        # 超长正文塞 caption 会被 Telegram 截断：图先发，文字单独成条。
                        await send_photo(
                            chat_id=send_request.target_id, photo=photo_ref
                        )
                    delivered_parts += 1
                except Exception:  # noqa: BLE001 - 图片失败降级为纯文本，避免重试重发已成功内容
                    logger.warning(
                        "telegram photo send failed request_id=%s",
                        send_request.request_id,
                    )
            # 语音/音频：sendVoice 仅认 OGG/OPUS，其余经 ffmpeg 转换或降级 audio。
            for part in parts:
                if part.get("type") not in {"record", "voice"}:
                    continue
                raw_voice_ref = str(part.get("file") or part.get("url") or "")
                voice_ref, voice_mode = await _prepare_telegram_voice(
                    raw_voice_ref, proxy=download_proxy
                )
                if voice_mode == "voice":
                    send_voice = getattr(bot, "send_voice", None)
                    if callable(send_voice):
                        result = await send_voice(
                            chat_id=send_request.target_id, voice=voice_ref
                        )
                        delivered_parts += 1
                        _cleanup_voice_source(raw_voice_ref)
                elif voice_mode == "audio":
                    send_audio = getattr(bot, "send_audio", None)
                    if callable(send_audio):
                        result = await send_audio(
                            chat_id=send_request.target_id, audio=voice_ref
                        )
                        delivered_parts += 1
                        _cleanup_voice_source(raw_voice_ref)
            if result is not None and not remaining:
                return result
            if result is None and not remaining and parts:
                raise ValueError("telegram media part is not sendable")
        if event is None:
            send_to = getattr(bot, "send_to", None)
            if not callable(send_to):
                raise RuntimeError("adapter does not expose send_to")
            return await send_to(send_request.target_id, remaining)
        if adapter_name == "mail":
            send_mail = getattr(bot, "send_mail", None)
            if not callable(send_mail):
                raise RuntimeError("mail adapter does not expose send_mail")
            return await send_mail(_build_mail_reply_message(bot, event, remaining))
        return await bot.send(event, remaining, **kwargs)

    timeout = resolve_transport_timeout(timeout_seconds)
    try:
        timeout = apply_request_deadline(
            timeout, getattr(send_request, "deadline_monotonic", None)
        )
    except DeadlineExceeded:
        debug_id = new_debug_id()
        deadline_stage = transport.split(".", 1)[0]
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=deadline_stage
                if deadline_stage in {"telegram", "mail"}
                else "runtime",
                kind="deadline_exceeded",
                retryable=False,
                safe_summary="deadline_exceeded",
                debug_id=debug_id,
            ),
        )
    try:
        result = await asyncio.wait_for(_send(), timeout=timeout)
    except asyncio.TimeoutError:
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=transport.split(".", 1)[0]
                if transport.split(".", 1)[0] in {"telegram", "mail"}
                else "runtime",
                kind="result_unknown",
                retryable=False,
                safe_summary="result_unknown",
                debug_id=debug_id,
            ),
        )
    except _FinalSendError as exc:
        debug_id = new_debug_id()
        # 审查 F-03（收窄口径）：_FinalSendError 文本（源自 file_gateway 的
        # FileTransferError 串等）会进 OperationalIssue 的 kind/safe_summary，
        # 随后内插进管理员告警等系统通知文本，出站前统一打码（可能夹带内网
        # URL/键值形态）；聊天回复链不经此分支，零改动。本地日志保留原文供诊断。
        final_detail = redact_local_secrets(str(exc)[:48]) or "send_failed_final"
        logger.warning(
            "nonebot send not retryable kind=%s request_id=%s transport=%s",
            str(exc),
            send_request.request_id,
            transport,
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=transport.split(".", 1)[0]
                if transport.split(".", 1)[0] in {"telegram", "mail"}
                else "runtime",
                kind=final_detail,
                retryable=False,
                safe_summary=final_detail,
                debug_id=debug_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - adapter errors become typed receipts.
        logger.warning(
            "nonebot transport send failed type=%s request_id=%s transport=%s",
            type(exc).__name__,
            send_request.request_id,
            transport,
        )
        debug_id = new_debug_id()
        stage = transport.split(".", 1)[0]
        if delivered_parts > 0:
            # 部分媒体已送达：整体重试会重发已投递部件，只能按结果未知终态处理。
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=transport,
                public_message="",
                debug_id=debug_id,
                operational_issue=OperationalIssue(
                    stage=stage if stage in {"telegram", "mail"} else "runtime",
                    kind="result_unknown",
                    retryable=False,
                    safe_summary="result_unknown",
                    debug_id=debug_id,
                ),
            )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=stage if stage in {"telegram", "mail"} else "runtime",
                kind="send_exception",
                retryable=True,
                safe_summary="send_exception",
                debug_id=debug_id,
            ),
        )

    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport=transport,
        provider_message_id=_provider_message_id(result),
        public_message="sent",
    )
