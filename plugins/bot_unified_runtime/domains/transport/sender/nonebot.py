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
from urllib.parse import urlparse

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
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.domains.render.reviewer import explicit_output_spans
from plugins.bot_unified_runtime.domains.transport.sender.failure_class import (
    RETRY_SAFETY_UNCERTAIN,
    classify_send_failure,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    TELEGRAM_MAX_DOCUMENT_BYTES,
    FileSource,
    FileTransferError,
    FileTransferGateway,
    # FinalTransferError 不在此导入：它是 FileTransferError 的子类，本文件只按
    # ``exc.kind`` 归因，两型走同一条 except 分支（导入即 F401 未用）。
    MailEnvelope,
    get_default_file_gateway,
)
from plugins.bot_unified_runtime.domains.transport.sender.timeout import (
    resolve_transport_timeout,
)

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


# ---------------------------------------------------------------------------
# Telegram 视频 / 动图 / 贴纸三族出口（S33 波 · 此前这三族在 TG 腿上零 getattr）
# ---------------------------------------------------------------------------

#: 走 sendAnimation 的动图形态（Telegram 侧动画＝MPEG4/GIF；GIF 的正解是
#: sendAnimation 而不是 sendVideo，动图当视频发会在客户端退化成静态缩略图）。
_TG_ANIMATION_SUFFIXES = frozenset({".gif", ".mp4", ".m4v", ".webm", ".animate"})

#: 部件 type → 本函数认得的富媒体段（其余 type 各有真身腿，此处一律不碰）。
_TG_RICH_MEDIA_PART_TYPES = frozenset({"video", "animation", "gif", "sticker"})

#: API 名 → Telegram 的字节参数名（适配器 send 前处理 input file 时按这个键取，
#: 见 nonebot/adapters/telegram/adapter.py 里 api[4:].lower() 那一族）。
_TG_RICH_MEDIA_KWARGS = {
    "send_animation": "animation",
    "send_video": "video",
    "send_photo": "photo",
}


def plan_telegram_rich_media(part: dict[str, Any]) -> tuple[str, str, str]:
    """纯判定：这一段富媒体该走哪个出口、拿什么引用、字节由谁取。

    返回 ``(API 名, 引用, 来源形态)``，来源形态 ∈ {"", "local", "remote"}；
    无可发引用时返回空三元组（调用方按「未送达」处理，**绝不静默当成已发**）。

    为什么 sticker 不走 ``send_sticker``——这是 **Telegram 平台硬约束**，不是本仓偷懒：
    ``sendSticker`` 只收「已经属于某个 sticker set」的贴纸（``sticker`` 参数是
    file_id，须先经 ``createNewStickerSet`` / ``addStickerToSet`` 建册入册），
    **任意一张图片/动图当贴纸直发必被服务端拒**，而本仓没有贴纸册管理面
    （建册要机器人拥有该册）。故给**可用替代**：动图形态 → ``sendAnimation``，
    静图形态 → ``sendPhoto``，内容与出处都到位，只是消息形态不是「贴纸」。

    视频/动图的分流按 Telegram 自己的口径：``.gif`` 与明确声明动画的段走
    ``sendAnimation``（mp4/gif 皆可），其余走 ``sendVideo``。
    """
    part_type = str(part.get("type") or "").strip().lower()
    if part_type not in _TG_RICH_MEDIA_PART_TYPES:
        return "", "", ""
    raw = str(part.get("file") or part.get("url") or "").strip()
    if not raw:
        return "", "", ""
    is_remote = raw.startswith(("http://", "https://"))
    suffix = (
        Path(urlparse(raw).path).suffix
        if is_remote
        else Path(raw.split("?", 1)[0]).suffix
    ).lower()
    declared_animation = part_type in {"animation", "gif"} or str(
        part.get("kind") or ""
    ).strip().lower() in {"animation", "gif"}

    if part_type == "sticker":
        # 替代路径：动图形态保留动画，静图形态降级为图片；两者都不许静默丢。
        if suffix in _TG_ANIMATION_SUFFIXES or declared_animation:
            return "send_animation", raw, "remote" if is_remote else "local"
        return "send_photo", raw, "remote" if is_remote else "local"
    if suffix == ".gif" or declared_animation:
        return "send_animation", raw, "remote" if is_remote else "local"
    if suffix in {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".3gp"}:
        return "send_video", raw, "remote" if is_remote else "local"
    # 扩展名认不出（无后缀的直链、临时文件名）：视频段仍按视频发，
    # 动图段（animation/gif 已在上面命中）之外不猜形态。
    return "send_video", raw, "remote" if is_remote else "local"


async def send_telegram_rich_media(
    bot: Any,
    part: dict[str, Any],
    *,
    request_id: str,
    chat_id: str,
    caption: str,
    gateway: FileTransferGateway,
) -> Any:
    """发一段视频/动图/贴纸替代件，返回出口结果（失败一律抛出，不返回「假成功」）。

    **判定门不许绕过**：本地件先过 ``FileTransferGateway.stage``——那一步是全通道
    唯一的取字节前判定（``check_sendable``：路径域 + 禁触名册，密钥/库/日志/.env
    一类当场拒），随后按 ``TELEGRAM_MAX_DOCUMENT_BYTES``（2MiB，与附件腿**同一枚
    常量对象**）拒超限件，超限/不在场/域判定拒绝都收在 ``FileTransferError`` 里。
    远程直链本机零读字节（由 Telegram 服务端取），沿用图片腿既有语义原样交出，
    不经路径域判定（那条判定管的是「本机文件能不能读出去」，这里没有本机读取）。
    """
    api, reference, source_kind = plan_telegram_rich_media(part)
    if not api:
        raise _FinalSendError("telegram_rich_media_unsendable")
    # 可执行/脚本形态永远不许出站。名册真身＝``restricted_runner.DENIED_EXTENSIONS``
    # （落盘口那一份，:218 起）——本处只引用、不另抄第二张表（仓规「禁第二份名册」）；
    # 局部导入防装配环，与 ``_download_voice_source`` 里 downloader 的同口径先例一致。
    from plugins.bot_unified_runtime.domains.files.sender.restricted_runner import (
        DENIED_EXTENSIONS,
        DenyCode,
    )

    if Path(urlparse(reference).path).suffix.lower() in DENIED_EXTENSIONS:
        raise _FinalSendError(DenyCode.EXECUTABLE_DENIED)
    kwarg = _TG_RICH_MEDIA_KWARGS[api]
    if source_kind == "local":
        try:
            ticket = gateway.stage(
                FileSource(
                    source_kind="path",
                    path=reference,
                    name=str(part.get("name") or ""),
                ),
                request_id=request_id,
            )
        except FileTransferError as exc:
            raise _FinalSendError(str(exc.kind)) from exc
        if ticket.local_path is None or not ticket.local_path.is_file():
            raise _FinalSendError("missing_file")
        if ticket.size > TELEGRAM_MAX_DOCUMENT_BYTES:
            # 与附件腿同宽：超限在发送前即可判定 ⇒ 终态，绝不重投（重投也只烧预算）。
            raise _FinalSendError("telegram_media_too_large")
        # 件名取票据名（与 S-T-FILE-2 的三通道对齐修正同口径），不取盘上落盘名。
        payload: str | tuple[str, bytes] = (
            ticket.name or ticket.local_path.name,
            ticket.local_path.read_bytes(),
        )
    elif source_kind == "remote":
        payload = reference
    else:  # pragma: no cover - plan 已挡空引用
        raise _FinalSendError("telegram_rich_media_unsendable")

    method = getattr(bot, api, None)
    if not callable(method):
        # 适配器没有这一枚出口 ⇒ 诚实点名，不假装发过（历史上这三族正是静默无通路）。
        raise _FinalSendError(f"telegram_api_unavailable:{api}")
    return await method(
        chat_id=chat_id,
        **{kwarg: payload},
        caption=caption or None,
        # 媒体 caption 遮罩（§76.21 残余）：命中才出原生 caption_entities，
        # 没命中回空 dict ⇒ 与改前逐字节相同（罩只加元数据、正文不改写）。
        **_telegram_caption_entities_kwargs(caption),
    )


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
    # SEAT-ATK-VISION F-V-2（网络卫生波 S-FIX-NETHYG）：本腿曾是出站取字节里唯一
    # 不过中央 SSRF 咽喉的一条（入站 vision/transcribe/downloader 全闸）。与
    # transcribe._download_audio 同款接法：入口先过 check_download_url（拒→None，
    # 降级直链 audio 但绝不出站），逐跳落点复查经 httpx request 事件钩在**每一跳
    # 建连前**再过同一咽喉——公网入口 302→内网/元数据落点时那一跳绝不发出。
    # 局部导入防装配环（与 transcribe 先例同口径）；钩内 RejectedUrlError 由下方
    # 既有 except Exception 兜底吞成 None（丢源不泄露，与下载失败同降级面）。
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    try:
        check_download_url(url)
    except RejectedUrlError:
        return None

    def _guard_hop(request: Any) -> None:
        check_download_url(str(request.url))

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(20.0),
        "follow_redirects": True,
        "event_hooks": {"request": [_guard_hop]},
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


def _telegram_spoiler_segments(text: str) -> list[Any]:
    """把命中露骨词面的文本切成适配器 `Entity` 段（命中段包 `spoiler`、其余原样 `text`）。

    没命中返回 **空列表**（调用方据此保持裸 `str` / 原 `caption` 逐字节不变）。
    判据复用 `reviewer.explicit_output_spans` 那一枚真身（与群侧涂销同一清单，
    禁第二份词表）；偏移**不在这里数**——`Entity` 段的 UTF-16 偏移由适配器
    `Entity.build_telegram_entities` 现算，量具与被包件不同源。
    延迟导入：本模块要在 console/mail 也在场时工作，适配器缺席不该拖垮出站腿。
    符号从 `.message` 取——`nonebot.adapters.telegram` 的 `__init__` 只再导出
    Bot/Event/Adapter/Message/MessageSegment，`Entity` 不在门面上（实跑 ImportError）。
    """
    spans = explicit_output_spans(text)
    if not spans:
        return []
    from nonebot.adapters.telegram.message import Entity

    segments: list[Any] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            segments.append(Entity.text(text[cursor:start]))
        segments.append(Entity.spoiler(text[start:end]))
        cursor = end
    if cursor < len(text):
        segments.append(Entity.text(text[cursor:]))
    return segments


def _telegram_masked_payload(text: str) -> Any:
    """Telegram 遮罩（用户 2026-10-06 裁「色情、敏感内容在 tg 加遮罩，QQ 不拦也不做措施」）。

    命中露骨词面的那几段包成官方 `spoiler` 实体（点一下才显示），**其余一字不动**：
    - 判据转述 `reviewer.explicit_output_spans` 那一枚真身（与群侧涂销同一清单，
      禁第二份词表）；没命中就原样交裸 `str`，§10「TG 不设 parse_mode 的纯文本契约」
      与改前逐字节相同。
    - 走适配器**已有的 `Entity` 消息段**而不是新开格式化通道：`str(Message)` 仍是原文，
      偏移由适配器按 UTF-16 自己算（见 `_telegram_spoiler_segments`，本函数不数）。
    - 射程＝已经允许出门的文本。罩 ≠ 放行：六条硬线在 reviewer/内容政策那一层照旧拦，
      到不了这里；群侧/频道侧的涂销也先本腿生效（公共面命中已被换成记号），所以本函数
      实际只在 **TG 私聊**那一面咬得住。
    - 通路保证「QQ 不做措施」：QQ 走 `send_onebot_v11`，结构上到不了这一支。
    """
    segments = _telegram_spoiler_segments(text)
    if not segments:
        return text
    from nonebot.adapters.telegram.message import Message

    return Message(segments)


def _telegram_caption_entities_kwargs(caption: str) -> dict[str, Any]:
    """媒体 caption 的官方遮罩 kwargs（§76.21 残余 · 图片/视频/文件的说明文字那一路）。

    命中露骨词面才回 `{"caption_entities": [...]}`；没命中回 **空 dict** ⇒ 调用方以
    `**` 展开后与改前**逐字节相同**（缺省不变量、§10 纯文本契约）。caption 正文一个字
    都不改：遮罩是**元数据**（`spoiler` 实体），不是把词面涂成星号——与文本腿同一口径。

    偏移为何仍交适配器算：`Entity.build_telegram_entities` 正是 `Bot.send_to` 图文同发
    分支组装 `caption_entities` 用的同一枚函数（nonebot/adapters/telegram/bot.py:247、:266），
    它按每段 `_length`（UTF-16 单位）累加偏移；本函数只切段、不自己数坐标。
    罩 ≠ 放行：不改任何准入/拦截判据、不新增配置键、不动 `content_safety`。
    """
    segments = _telegram_spoiler_segments(caption)
    if not segments:
        return {}
    from nonebot.adapters.telegram.message import Entity

    entities = Entity.build_telegram_entities(segments)
    if not entities:  # pragma: no cover - 有命中必出 spoiler 实体，防御性收口
        return {}
    return {"caption_entities": entities}


def _provider_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        value = result.get("message_id") or result.get("id")
    else:
        value = getattr(result, "message_id", None) or getattr(result, "id", None)
    return str(value) if value is not None else None


def _send_failure_summary(kind: str, exc: BaseException) -> str:
    """atkfix M-2（收窄裁定口径）：失败回执 safe_summary 携带异常**类型**。

    kind 是 worker 判据与幂等去重逐字消费的承重串（``worker.py`` 按
    ``issue.kind`` 判定确认/终局），一个字节都不许变。既有裁决锁
    （tests/test_operational_failures.py:368-373）钉死**异常消息文本**绝不
    进回执 JSON——回执要落库，消息原文只准进本地日志（_FinalSendError 分支
    同口径先例）。故 safe_summary 富化只取类型名（非敏感分类词，ValueError
    与 OSError 的分野已是诊断价值），消息原文一个字符不带；原因全文见本
    函数调用方所在分支的 warning 日志（detail=%s）。
    """
    return f"{kind} {type(exc).__name__}"[:96]


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


def _mail_message_id(salt: str, sender_id: str, recipient: str, subject: str, text: str) -> str:
    """由「邮件身份 + 队列请求号」确定性派生 Message-ID（atkfix R3）。

    旧写法每装配一次就 ``make_msgid()`` 盖一个随机新号：SMTP 在 DATA 之后断连
    会归 ``FAILED_RETRYABLE``（:702-747）⇒ 队列重投 ⇒ 每重投一次换一个号 ⇒
    收件人收到多封「同文不同号」的重复邮件。这里改成**同一封信重投必得同一个号**：
    输入取队列稳定身份 ``salt``（= request_id，重投期间逐字不变）叠加发件/收件/
    主题/正文——这些在重投间同样稳定。不同邮件（不同 request_id 或不同正文）
    ⇒ 不同号，故**不破**按部件幂等的既有契约；同号让收件端/我方出口都能按
    RFC 5322 的 Message-ID 去重。domain 仍取发件地址域，无 @ 落 localhost 兜底。
    """
    domain = sender_id.partition("@")[2] if "@" in sender_id else "localhost"
    raw = f"{salt}\x00{sender_id}\x00{recipient}\x00{subject}\x00{text}"
    local = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"<{local}@{domain}>"


def _build_mail_reply_message(
    bot: Any, event: Any, text: str, *, message_salt: str
) -> EmailMessage:
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
    # atkfix M-4：stdlib smtplib.send_message 不自动盖 Message-ID，nonebot 邮件
    # 适配器也不盖 ⇒ 旧写法出站邮件**没有消息号**，对方客户端引用回复时
    # In-Reply-To 无物可指，会话线程自源头断裂。装配层自盖（域取发件地址域，
    # 无 @ 则落 localhost 兜底）。atkfix R3：号由「邮件身份 + 队列请求号」
    # 确定性派生（见 ``_mail_message_id``），不再每装配一次盖一个随机新号——
    # 重投同一封 ⇒ 同一个号，收件端可据 Message-ID 去重，杜绝重复投递。
    message["Message-ID"] = _mail_message_id(
        message_salt, sender_id, recipient, subject, text
    )
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id
    message.set_content(text)
    message.add_alternative(_mail_html_body(text), subtype="html")
    return message


def _build_mail_attachment_envelope(
    bot: Any, event: Any, body_text: str, *, daily_count: int | None
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

    ``daily_count``＝**当日已投件数的 live 读值**（atkfix R2）：调用方从投递喉道
    ``FileTransferGateway.mail_attachment_count_today()`` 取，逐件刷新后交进来。
    计数真身住在网关这条唯一喉道上（唯一事实源，装配层不另建第二本账）；这里
    只做注入。仍保留 ``None`` 通道：直接构造信封的历史/测试调用若显式传 None，
    网关照旧「放行但记日志」，绝不把「没接计数器」读成「今天还剩 50 件」。
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
        daily_count=daily_count,
    )


class _MailRedriveEvent:
    """认领重投腿（event=None）的邮件「事件事实替身」（F3，S-FIX-MAILINGRESS-R）。

    队列请求已带齐投递所需的全部地址事实：``target_id``（管线回填的原发件人，
    与内联腿 ``event.sender.id`` 同一信任面——都来自会话路由决策，绝不从正文扫）
    与 ``origin_message_id``（来件 Message-ID，线程头唯一可用真身）。替身只做
    「形状适配」：把请求侧事实重组为 ``_build_mail_reply_message`` /
    ``_build_mail_attachment_envelope`` 既有的事件接口，让重投腿与内联腿复用
    **同一个报文构造器**＝不写第二套装配（装配唯一性同 atkfix R3/M-4 口径）。

    残余降级（如实登记）：原主题未持久化在 SendRequest ⇒ 重投主题回填 ``Re:``
    （内联腿空主题同形）；origin 为空时线程头照旧缺省跳过（构造器自 semantics）。
    """

    __slots__ = ("id", "sender", "subject")

    class _Sender:
        __slots__ = ("id",)

        def __init__(self, address: str) -> None:
            self.id = address

    def __init__(self, send_request: SendRequest) -> None:
        self.id = str(send_request.origin_message_id or "")
        self.subject = ""
        self.sender = self._Sender(str(send_request.target_id or "").strip())


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

    # F3：mail 认领重投腿（root transport 闭包与连接期补发臂均传 event=None）不再
    # 降级 send_to——先用请求侧事实立事件替身，下面文本腿走 send_mail（线程头＋
    # 确定性 Message-ID 齐），附件腿名册=target_id（与内联同一地址事实，
    # FileTransferGateway 比对不再恒空）。其余 adapter 的 event=None 兜底形制
    # 逐字节不变。
    if adapter_name == "mail" and event is None:
        event = _MailRedriveEvent(send_request)

    text = str(send_request.content.text_fallback or "").strip()
    media_parts = _telegram_media_parts(send_request.content.content_ref)
    has_tg_media = adapter_name == "telegram" and any(
        part.get("type") in {"image", "record", "voice", "file"}
        or part.get("type") in _TG_RICH_MEDIA_PART_TYPES
        for part in media_parts
    )
    # S33 波补的正是右半边：``video`` 旧册里虽有名字却零 getattr（发了个寂寞、
    # 无正文时当场 ValueError），``sticker`` 更连名字都没有 ⇒ 只带贴纸的请求
    # 直接落进 SKIPPED（静默丢，用户端表现为「她回了但什么都没到」）。
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
    # atkfix M-3：已送达部件中最后一枚**被出口确认**的消息号（只从成功返回的
    # 发送腿取）。结果未知回执携带它：管理员与队列至少有一枚可指认的把手。
    delivered_message_id: str | None = None
    # atkfix M-4：邮件文本腿出站报文的自盖 Message-ID。仅供 SENT 回执兜底；
    # 失败/结果未知回执绝不携带（未经出口证明的号不算送达证据）。
    outbound_message_id: str | None = None
    download_proxy = _resolve_download_proxy(bot)

    async def _send() -> Any:
        nonlocal delivered_parts, delivered_message_id, outbound_message_id
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
            result: Any = None
            # B3 阶段 1：附件统一经 FileTransferGateway 投递；缺失/超 2MB 的
            # 不可重试判定、caption 截 1000 字、读全量字节、回执缺失按失败
            # 的语义逐行等价搬运（见 file_gateway._deliver_telegram_document）。
            gateway = get_default_file_gateway()
            for part_index, part in enumerate(files):
                # atkfix R2：邮件附件信封逐件构造，daily_count 现读喉道当日已投件数
                # （gateway 是唯一投递喉道＝计数真身，装配层不另建账），使多部件
                # 请求内的第 2..N 件也吃到前件成功后的实时递增，杜绝一次性快照低估。
                envelope = (
                    _build_mail_attachment_envelope(
                        bot,
                        event,
                        remaining,
                        daily_count=(
                            gateway.mail_attachment_count_today()
                            if transport_name == "mail"
                            else None
                        ),
                    )
                    if transport_name == "mail"
                    else None
                )
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
                # atkfix M-3：附件腿同样登记已证明号（TG 文档取出口回号；邮件
                # 附件出口不回号，provider_file_id 诚实为 None ⇒ 不登记）。
                delivered_message_id = (
                    _provider_message_id(result)
                    or file_receipt.provider_file_id
                    or delivered_message_id
                )
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
                            # §76.21 残余：图片 caption 同样只在命中露骨词面时出
                            # caption_entities，没命中回空 dict（逐字节同改前）。
                            **_telegram_caption_entities_kwargs(remaining),
                        )
                        remaining = ""
                    else:
                        # 超长正文塞 caption 会被 Telegram 截断：图先发，文字单独成条。
                        # atkfix M-3：返回的 Message 不再丢弃——图已送达，号是把手。
                        result = await send_photo(
                            chat_id=send_request.target_id, photo=photo_ref
                        )
                    delivered_parts += 1
                    delivered_message_id = (
                        _provider_message_id(result) or delivered_message_id
                    )
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
                        delivered_message_id = (
                            _provider_message_id(result) or delivered_message_id
                        )
                        _cleanup_voice_source(raw_voice_ref)
                elif voice_mode == "audio":
                    send_audio = getattr(bot, "send_audio", None)
                    if callable(send_audio):
                        result = await send_audio(
                            chat_id=send_request.target_id, audio=voice_ref
                        )
                        delivered_parts += 1
                        delivered_message_id = (
                            _provider_message_id(result) or delivered_message_id
                        )
                        _cleanup_voice_source(raw_voice_ref)
            # 视频 / 动图 / 贴纸（S33 波）：这三族此前在 TG 腿上零 getattr ⇒
            # 结构性无通路（无正文时下面那枚 ValueError 把请求打成可重试失败，
            # 队列烧满预算才收口；贴纸段更连 has_tg_media 都不认，直接 SKIPPED
            # 静默消失）。判定门与限额走附件腿同一条（见 send_telegram_rich_media）。
            rich_media = [
                part
                for part in parts
                if str(part.get("type") or "").strip().lower()
                in _TG_RICH_MEDIA_PART_TYPES
            ]
            if rich_media:
                media_gateway = get_default_file_gateway()
                for part in rich_media:
                    part_caption = remaining if len(remaining) <= 1024 else ""
                    rich_result = await send_telegram_rich_media(
                        bot,
                        part,
                        request_id=send_request.request_id,
                        chat_id=send_request.target_id,
                        caption=part_caption,
                        gateway=media_gateway,
                    )
                    if rich_result is not None:
                        result = rich_result
                        delivered_parts += 1
                        delivered_message_id = (
                            _provider_message_id(rich_result) or delivered_message_id
                        )
                        if part_caption:
                            remaining = ""
            if result is not None and not remaining:
                return result
            if result is None and not remaining and parts:
                raise ValueError("telegram media part is not sendable")
        # 遮罩只在这一处挂（两枚出口共用同一枚 payload）：mail/console 逐字节走原值。
        payload = (
            _telegram_masked_payload(remaining) if adapter_name == "telegram" else remaining
        )
        if event is None:
            send_to = getattr(bot, "send_to", None)
            if not callable(send_to):
                raise RuntimeError("adapter does not expose send_to")
            return await send_to(send_request.target_id, payload)
        if adapter_name == "mail":
            send_mail = getattr(bot, "send_mail", None)
            if not callable(send_mail):
                raise RuntimeError("mail adapter does not expose send_mail")
            reply_message = _build_mail_reply_message(
                bot, event, remaining, message_salt=send_request.request_id
            )
            # atkfix M-4：记下本腿自盖 Message-ID（仅 SENT 回执兜底消费；
            # send_mail 抛错/超时路径绝不引用未经出口证明的号）。
            outbound_message_id = str(reply_message["Message-ID"])
            return await send_mail(reply_message)
        return await bot.send(event, payload, **kwargs)

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
            # atkfix M-3：超时前已确认送达的部件号是真实把手，随回执出站。
            provider_message_id=delivered_message_id,
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
                # 连接期修复波打标：外层 wait_for 超时＝请求早已写出、结果未知
                # ⇒ 不确定档（worker/告警重投臂据此**绝不**放行重投）。
                retry_safety=RETRY_SAFETY_UNCERTAIN,
            ),
        )
    except _FinalSendError as exc:
        debug_id = new_debug_id()
        # 审查 F-03（收窄口径）：_FinalSendError 文本（源自 file_gateway 的
        # FileTransferError 串等）会进 OperationalIssue 的 kind/safe_summary，
        # 随后内插进管理员告警等系统通知文本，出站前统一打码（可能夹带内网
        # URL/键值形态）；聊天回复链不经此分支，零改动。本地日志保留原文供诊断。
        # atkfix M-1（S-ATKFIX-OUTB 同口径补正）：**先洗后截**——旧写法
        # redact(str(exc)[:48]) 属先截后洗，截断窗口恰好切开密钥形态时
        # （如 "sk-" 连段被截成残段）打码腿因残缺不命中，残段原样出站。
        final_detail = redact_local_secrets(str(exc))[:48] or "send_failed_final"
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
        # atkfix M-2：本地日志补 detail=%s——回执带不走的异常原文（裁决锁
        # :368-373）在这里留全量，诊断卡/告警消费 safe_summary 里的类型词。
        logger.warning(
            "nonebot transport send failed type=%s detail=%s request_id=%s transport=%s",
            type(exc).__name__,
            str(exc),
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
                # atkfix M-3：已证明送达的部件号随结果未知回执出站。
                provider_message_id=delivered_message_id,
                public_message="",
                debug_id=debug_id,
                operational_issue=OperationalIssue(
                    stage=stage if stage in {"telegram", "mail"} else "runtime",
                    # kind 是 worker 判据承重串，逐字不动；safe_summary 补异常类型（atkfix M-2）。
                    kind="result_unknown",
                    retryable=False,
                    safe_summary=_send_failure_summary("result_unknown", exc),
                    debug_id=debug_id,
                    # 已有部件送达 ⇒ 整体重试必重发已投递内容：无论异常长什么
                    # 形状都按不确定收口（连接期修复波的打标在此只能收紧、
                    # 绝不放宽——M-63 红线优先于分类）。
                    retry_safety=RETRY_SAFETY_UNCERTAIN,
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
                # 同上：kind 逐字承重，safe_summary 只补类型词、不带消息原文（atkfix M-2）。
                kind="send_exception",
                retryable=True,
                safe_summary=_send_failure_summary("send_exception", exc),
                debug_id=debug_id,
                # 连接期修复波（2026-09-28）：零字节出网的连接失败（代理拒连/
                # DNS 解析失败）打 connect_phase，放行 worker mixed 重投臂与
                # 告警文本腿的一次补发；其余形态按 uncertain 收口＝既有
                # UNKNOWN/停放语义逐字节不变。异常消息原文仍只进上面的日志。
                retry_safety=classify_send_failure(exc),
            ),
        )

    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport=transport,
        # atkfix M-3/M-4：出口回号 > 已证明部件号 > 邮件文本腿自盖号。
        provider_message_id=(
            _provider_message_id(result) or delivered_message_id or outbound_message_id
        ),
        public_message="sent",
    )
