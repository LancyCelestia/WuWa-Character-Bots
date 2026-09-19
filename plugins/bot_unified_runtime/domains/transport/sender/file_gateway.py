"""FileTransferGateway（B3）：发送层内的统一文件通道。

规格：docs/design/file-transfer-gateway.md §2.2。本模块是阶段 1（sender 层内
收敛、零行为变化）的落地：

- ``FileSource``：业务侧唯一允许声明的文件词汇（path/url/bytes 三选一）。
- ``FileTicket``：stage 之后的稳定凭据（落盘路径 + sha256 + 大小）。
- ``FileTransferReceipt``：文件维度回执（独立类型，不塞进 DeliveryReceipt）。
- ``FileTransferGateway``：既有 OneBot 上传与 Telegram 文档通道的**等价封装**——
  逐行搬自 ``sender/onebot.py:_send_file_parts`` 的上传内环与
  ``sender/nonebot.py`` 的 Telegram files 分支；上传参数、2MB 上限、caption
  截断、"有副作用绝不整体重投"的外层契约全部原样保留。

阶段 1 不实现（规格后续阶段/开放问题留待裁决）：URL 下载代理生产接线、
staging 配额（enforce_quota）、Mail 附件通道、FileTransferReceipt 落库、
bytes 内存上限策略、NapCat 频控/平台 file id 实测（Q1-Q7）。
``upload_group_file`` / ``upload_private_file`` / ``send_document`` 等平台
API 字样从此只允许出现在 ``sender/`` 目录内。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from plugins.bot_unified_runtime.contracts import (
    ReceiptState,
    SendRequest,
    SessionType,
    new_debug_id,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import StrictBaseModel

# 文件维度回执 transport 标记（与消息级 transport 命名区分）。
ONEBOT_FILE_TRANSPORT = "onebot.file"
TELEGRAM_DOCUMENT_TRANSPORT = "telegram.document"

# Telegram sendDocument 现行硬上限（2MB，与 sender/nonebot.py 同值；超限
# 策略属规格开放问题 Q1，本阶段保持"超限即拒绝"的既有行为不变）。
TELEGRAM_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

FileSourceKind = Literal["path", "url", "bytes"]

logger = logging.getLogger(__name__)


class FileTransferError(Exception):
    """文件通道失败，``kind`` 与既有失败分类字符串逐字对齐：

    missing_file / upload_rejected / upload_failed_or_unknown /
    unsupported_file_target / upload_api_unavailable / url_rejected /
    url_download_failed / url_download_unavailable / staging_unavailable /
    invalid_source。
    ``sender/onebot.py`` 的编排层负责把它翻回 ``_NonRetryableActionError``。
    """

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class FinalTransferError(FileTransferError):
    """发送前已可判定不可重试的文件失败（对应 Telegram 侧 ``_FinalSendError``）。"""


def coerce_onebot_id(value: str) -> int | str:
    """与 ``sender/onebot.py:_coerce_onebot_id`` 同源等价（避免循环导入）。"""
    stripped = value.strip()
    if stripped.isdecimal():
        return int(stripped)
    return stripped


def _extract_onebot_retcode(result: Any) -> int | None:
    # 等价复制自 sender/onebot.py（避免 onebot ↔ gateway 循环导入）。
    if isinstance(result, dict):
        raw_retcode = result.get("retcode")
    else:
        raw_retcode = getattr(result, "retcode", None)
    if isinstance(raw_retcode, int):
        return raw_retcode
    if isinstance(raw_retcode, str) and raw_retcode.strip().lstrip("-").isdigit():
        return int(raw_retcode)
    return None


def _extract_onebot_status(result: Any) -> str:
    if isinstance(result, dict):
        raw_status = result.get("status")
    else:
        raw_status = getattr(result, "status", None)
    if isinstance(raw_status, str):
        return raw_status.strip().lower()
    return str(raw_status).strip().lower() if raw_status is not None else ""


def onebot_result_is_success(result: Any) -> bool:
    # 等价复制自 sender/onebot.py:_onebot_result_is_success。
    status = _extract_onebot_status(result)
    retcode = _extract_onebot_retcode(result)
    if status in {"failed", "fail", "error"}:
        return False
    return retcode is None or retcode == 0


def extract_provider_message_id(result: Any) -> str | None:
    # 等价复制自 sender/nonebot.py:_provider_message_id。
    if isinstance(result, dict):
        value = result.get("message_id") or result.get("id")
    else:
        value = getattr(result, "message_id", None) or getattr(result, "id", None)
    return str(value) if value is not None else None


def sanitize_file_name(name: str) -> str:
    """文件名安全化：取 basename、剥路径分隔符与控制字符（规格 §2.6.2）。

    对不含分隔符/控制字符的普通文件名是恒等变换，既有通道的上传参数
    因此逐字节不变。
    """
    cleaned = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32 and ch != "\x7f")
    return cleaned.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FileSource:
    """业务侧文件声明（三选一，判别字段 source_kind；规格 §2.2）。"""

    source_kind: FileSourceKind
    path: str | None = None
    url: str | None = None
    data: bytes | None = None
    name: str = ""
    sha256: str = ""

    def __post_init__(self) -> None:
        if self.source_kind == "path" and not self.path:
            raise FileTransferError("invalid_source")
        if self.source_kind == "url" and not self.url:
            raise FileTransferError("invalid_source")
        if self.source_kind == "bytes" and self.data is None:
            raise FileTransferError("invalid_source")
        if self.source_kind not in {"path", "url", "bytes"}:
            raise FileTransferError("invalid_source")
        object.__setattr__(self, "name", sanitize_file_name(self.name))


@dataclass(frozen=True)
class FileTicket:
    """stage 产物：后续 deliver 只认 ticket，不接触来源侧词汇。"""

    ticket_id: str
    local_path: Path | None
    name: str
    size: int
    sha256: str
    source: str
    created_at: datetime = field(default_factory=_utc_now)


class FileTransferReceipt(StrictBaseModel):
    """文件维度回执（独立类型；落库形态归规格开放问题 Q4，本阶段不落库）。"""

    request_id: str
    ticket_id: str
    state: ReceiptState
    name: str
    size: int
    sha256: str
    part_index: int = 0
    provider_file_id: str | None = None
    transport: str
    debug_id: str = Field(default_factory=new_debug_id)
    # 平台原始返回值：供既有编排层（_send_file_parts / TG files 分支）维持
    # "最后一次 API 结果决定终态回执"的原语义；阶段 1 等价搬运所需。
    provider_result: Any = None


def build_file_dedupe_key(
    *,
    sha256: str,
    target_scope: SessionType | str,
    target_id: str,
    part_index: int = 0,
) -> str:
    """文件级幂等键（规格 §2.2）：与 SendRequest.dedupe_key 并存不互替。"""
    scope = target_scope.value if isinstance(target_scope, SessionType) else str(target_scope)
    return f"{sha256}:{scope}:{target_id}:{part_index}"


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileTransferGateway:
    """统一文件出站网关：stage（来源→票据）+ deliver（票据→平台通道）。"""

    def __init__(
        self,
        staging_dir: Path | None = None,
        *,
        url_downloader: Callable[[str, Path], Path] | None = None,
    ) -> None:
        # 阶段 1 默认 staging 目录不依赖插件配置（bot_download_dir 接线归阶段 3）。
        self.staging_dir = staging_dir or (Path(tempfile.gettempdir()) / "bot_file_staging")
        self._url_downloader = url_downloader

    # -------------------- stage --------------------

    def stage(self, src: FileSource, *, request_id: str = "") -> FileTicket:
        if src.source_kind == "path":
            return self._stage_path(src)
        if src.source_kind == "bytes":
            return self._stage_bytes(src)
        return self._stage_url(src)

    def _stage_path(self, src: FileSource) -> FileTicket:
        path = Path(str(src.path or ""))
        if not path.is_file():
            # 与既有 _send_file_parts / TG files 分支的缺失判定同语义。
            raise FileTransferError("missing_file")
        resolved = path.resolve()
        name = src.name or path.name
        return FileTicket(
            ticket_id=f"ft_{uuid.uuid4().hex[:12]}",
            local_path=resolved,
            name=name,
            size=resolved.stat().st_size,
            sha256=src.sha256 or _sha256_of_file(resolved),
            source="path",
        )

    def _stage_bytes(self, src: FileSource) -> FileTicket:
        data = src.data if src.data is not None else b""
        digest = hashlib.sha256(data).hexdigest()
        ticket_id = f"ft_{uuid.uuid4().hex[:12]}"
        name = src.name or f"{ticket_id}.bin"
        target = self._ensure_staging_dir() / f"{ticket_id}_{name}"
        target.write_bytes(data)
        return FileTicket(
            ticket_id=ticket_id,
            local_path=target,
            name=name,
            size=len(data),
            sha256=src.sha256 or digest,
            source="bytes",
        )

    def _stage_url(self, src: FileSource) -> FileTicket:
        url = str(src.url or "").strip()
        if not url:
            raise FileTransferError("invalid_source")
        fallback_name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "download"
        # SSRF 固定闸门（规格 §2.6.1）：复用 sources.downloader 的既有护栏。
        from plugins.bot_unified_runtime.sources.downloader import (
            RejectedUrlError,
            check_download_url,
        )

        try:
            check_download_url(url)
        except RejectedUrlError as exc:
            raise FileTransferError("url_rejected") from exc
        if self._url_downloader is None:
            # 生产下载代理接线归阶段 3；本阶段仅注入式可用（测试/显式装配）。
            raise FileTransferError("url_download_unavailable")
        ticket_id = f"ft_{uuid.uuid4().hex[:12]}"
        name = src.name or fallback_name
        target = self._ensure_staging_dir() / f"{ticket_id}_{name}"
        try:
            downloaded = Path(self._url_downloader(url, target))
        except FileTransferError:
            raise
        except Exception as exc:
            raise FileTransferError("url_download_failed") from exc
        if not downloaded.is_file():
            raise FileTransferError("url_download_failed")
        return FileTicket(
            ticket_id=ticket_id,
            local_path=downloaded,
            name=name,
            size=downloaded.stat().st_size,
            sha256=src.sha256 or _sha256_of_file(downloaded),
            source="url",
        )

    def _ensure_staging_dir(self) -> Path:
        try:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FileTransferError("staging_unavailable") from exc
        return self.staging_dir

    # -------------------- deliver --------------------

    async def deliver(
        self,
        bot: Any,
        ticket: FileTicket,
        *,
        target: SendRequest,
        transport: Literal["onebot", "telegram"] = "onebot",
        part_index: int = 0,
        budget: Any = None,
        caption: str = "",
    ) -> FileTransferReceipt:
        if transport == "telegram":
            return await self._deliver_telegram_document(
                bot, ticket, target=target, part_index=part_index, caption=caption
            )
        return await self._deliver_onebot(
            bot, ticket, target=target, part_index=part_index, budget=budget
        )

    def _resolve_call_timeout(self, budget: Any, calls: int = 1) -> float:
        # budget=_TimeoutBudget → 既有每段切片语义；None → 单调用标准超时；
        # 其他按秒数值处理。
        slice_for = getattr(budget, "slice_for", None)
        if callable(slice_for):
            return float(slice_for(calls))
        if budget is None:
            from plugins.bot_unified_runtime.sender.timeout import (
                resolve_transport_timeout,
            )

            return resolve_transport_timeout(None)
        return float(budget)

    async def _deliver_onebot(
        self,
        bot: Any,
        ticket: FileTicket,
        *,
        target: SendRequest,
        part_index: int,
        budget: Any,
    ) -> FileTransferReceipt:
        # 等价搬运自 sender/onebot.py:_send_file_parts 的上传内环：
        # 仅本地绝对路径；群走 upload_group_file、私聊走 upload_private_file；
        # 优先 getattr(bot, api)，退化 call_api；retcode 拒绝 → upload_rejected。
        path = ticket.local_path
        if path is None or not path.is_file():
            raise FileTransferError("missing_file")
        params: dict[str, Any] = {"file": str(path.resolve()), "name": ticket.name or path.name}
        if target.target_scope is SessionType.GROUP:
            api = "upload_group_file"
            params["group_id"] = coerce_onebot_id(target.target_id)
        elif target.target_scope is SessionType.PRIVATE:
            api = "upload_private_file"
            params["user_id"] = coerce_onebot_id(target.target_id)
        else:
            raise FileTransferError("unsupported_file_target")
        method = getattr(bot, api, None)
        timeout = self._resolve_call_timeout(budget)
        try:
            if callable(method):
                result = await asyncio.wait_for(method(**params), timeout=timeout)
            else:
                call_api = getattr(bot, "call_api", None)
                if not callable(call_api):
                    raise FileTransferError("upload_api_unavailable")
                result = await asyncio.wait_for(call_api(api, **params), timeout=timeout)
            if not onebot_result_is_success(result):
                raise FileTransferError("upload_rejected")
        except (FileTransferError, asyncio.TimeoutError):
            raise
        except Exception as exc:
            logger.warning(
                "onebot upload call failed type=%s detail=%s",
                type(exc).__name__,
                str(exc)[:120],
            )
            raise FileTransferError("upload_failed_or_unknown") from exc
        return FileTransferReceipt(
            request_id=target.request_id,
            ticket_id=ticket.ticket_id,
            state=ReceiptState.SENT,
            name=ticket.name,
            size=ticket.size,
            sha256=ticket.sha256,
            part_index=part_index,
            provider_file_id=extract_provider_message_id(result),
            transport=ONEBOT_FILE_TRANSPORT,
            provider_result=result,
        )

    async def _deliver_telegram_document(
        self,
        bot: Any,
        ticket: FileTicket,
        *,
        target: SendRequest,
        part_index: int,
        caption: str,
    ) -> FileTransferReceipt:
        # 等价搬运自 sender/nonebot.py Telegram files 分支：
        # 缺失/超 2MB 在发送前即可判定；caption 截 1000 字随件；读全量字节。
        path = ticket.local_path
        if (
            path is None
            or not path.is_file()
            or path.stat().st_size > TELEGRAM_MAX_DOCUMENT_BYTES
        ):
            raise FinalTransferError("invalid generated attachment")
        result = await bot.send_document(
            chat_id=target.target_id,
            document=(path.name, path.read_bytes()),
            caption=caption[:1000],
        )
        return FileTransferReceipt(
            request_id=target.request_id,
            ticket_id=ticket.ticket_id,
            state=ReceiptState.SENT,
            name=path.name,
            size=ticket.size,
            sha256=ticket.sha256,
            part_index=part_index,
            provider_file_id=extract_provider_message_id(result),
            transport=TELEGRAM_DOCUMENT_TRANSPORT,
            provider_result=result,
        )


_default_gateway: FileTransferGateway | None = None
_default_gateway_lock = threading.Lock()


def get_default_file_gateway() -> FileTransferGateway:
    """进程级默认网关（既有通道等价封装共用；测试可 set 覆写）。"""
    global _default_gateway
    gateway = _default_gateway
    if gateway is None:
        with _default_gateway_lock:
            gateway = _default_gateway = _default_gateway or FileTransferGateway()
    return gateway


def set_default_file_gateway(gateway: FileTransferGateway | None) -> None:
    global _default_gateway
    _default_gateway = gateway
