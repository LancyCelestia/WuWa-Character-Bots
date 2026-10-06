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
staging 配额（enforce_quota）、FileTransferReceipt 落库、
bytes 内存上限策略、NapCat 频控/平台 file id 实测（Q1-Q7）。
**Mail 附件通道已于 2026-09-25 由 S-T-FILE-2 二段落地**（需求 16(3) 三端对齐的
最后一端）：见本文件 ``MailEnvelope`` / ``build_mail_attachment_message`` /
``FileTransferGateway._deliver_mail``；装配接线点归 ``sender/nonebot.py``（本席禁写面，
坐标见席位报告 §伍）。
``upload_group_file`` / ``upload_private_file`` / ``send_document`` / ``send_mail`` 等平台
API 字样从此只允许出现在 ``sender/`` 目录内。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
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
from plugins.bot_unified_runtime.domains.core.safety_exec.attack_surface import (
    find_visual_spoof_controls,
    fold_name_disguise,
    strip_display_controls,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.paths import (
    VERDICT_NEEDS_REVIEW,
    check_sendable,
    check_staged_target,
)
from plugins.bot_unified_runtime.domains.media.digest import (
    media_digest,
    media_digest_file,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

# 文件维度回执 transport 标记（与消息级 transport 命名区分）。
ONEBOT_FILE_TRANSPORT = "onebot.file"
TELEGRAM_DOCUMENT_TRANSPORT = "telegram.document"
MAIL_ATTACHMENT_TRANSPORT = "mail.attachment"

# Telegram sendDocument 现行硬上限（2MB，与 sender/nonebot.py 同值；超限
# 策略属规格开放问题 Q1，本阶段保持"超限即拒绝"的既有行为不变）。
TELEGRAM_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

# ---------------------------------------------------------------------------
# 邮件附件腿（需求 16(3)「QQ / Telegram / 邮箱三端收发」缺的那一端 · S-T-FILE-2 二段）
# ---------------------------------------------------------------------------

# 单件字节上限：**直接引用 Telegram 那一枚的同一个常量对象**，不是抄数值。
# 「新增腿不得宽于既有腿」由这条引用保证——日后收紧一处即两腿同宽。
MAIL_MAX_ATTACHMENT_BYTES = TELEGRAM_MAX_DOCUMENT_BYTES
# 单条件数 / 每日件数上限：取值**不宽于**归档侧既有缺省
# （`config.py:854-856` `bot_media_archive_per_message_limit=4`、
# `bot_media_archive_daily_limit=50`；那一枚单文件 100MB 宽于 2MiB，故本腿用更严的
# 2MiB）。本席不新建配置键（`config.py` 属禁写面），专用出站键作为建议上交，
# 见 `.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-FILE-2.md` §陆。
MAIL_MAX_ATTACHMENTS_PER_MESSAGE = 4
MAIL_MAX_ATTACHMENTS_PER_DAY = 50

FileSourceKind = Literal["path", "url", "bytes"]

logger = logging.getLogger(__name__)


class FileTransferError(Exception):
    """文件通道失败，``kind`` 与既有失败分类字符串逐字对齐：

    missing_file / upload_rejected / upload_failed_or_unknown /
    unsupported_file_target / upload_api_unavailable / url_rejected /
    url_download_failed / url_download_unavailable / staging_unavailable /
    staging_target_denied / path_domain_denied / invalid_source。

    邮件附件腿新增（一因一码，绝不塌成一枚兜底串）：
    mail_envelope_missing / mail_recipients_unconfigured /
    mail_recipient_not_allowlisted / mail_attachment_too_large /
    mail_attachment_count_exceeded / mail_daily_quota_exceeded /
    mail_send_api_unavailable / mail_send_timeout / mail_send_failed_or_unknown。
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
    """文件名安全化：取 basename、剥路径分隔符与控制字符（规格 §2.6.2），
    再剥**显示伪装**的不可见字符并折掉**冒充 ASCII 英文名**的同形异码
    （AS-VISUAL-SPOOF，2026-09-28 S-FILESAFE 接不可见腿；2026-09-28 S-SEC-NARROW 接同形腿）。

    两层判据各归其主：路径形态住本函数，不可见码点与同形折叠那一族的清单唯一真身在
    ``domains/core/safety_exec/attack_surface``（``strip_display_controls`` /
    ``fold_name_disguise``，本处只调用，不抄第二份表）。
    同形腿为什么**现在**折、S-FILESAFE 那一席为什么不折：当时只有「折出来像角色词」
    才报（``аdmin``），门窄到吃不到用户点名的形态——``report.ｅxe``、全角/西里尔近似形
    冒充普通英文名整族漏网。本席把判据换成「折叠后成纯 ASCII 且原串非 ASCII」，
    于是**只有冒充英文名的**才会被改写：纯西里尔真词（``администратор.txt``）、
    汉字夹全角字母（``报告Ａ.docx``）、纯 ASCII 名一律逐字节不变，
    「替别人改名 / 撞名」的旧顾虑只在伪装为真时才发生，而那一刻原名字本就是假的。
    只折**字母数字**、绝不折 `．`/`／` 一类标点：消毒口不许凭空制造扩展名分界或路径分隔符。
    对不含分隔符/控制字符/不可见码点/伪装的普通文件名仍是恒等变换，
    既有通道的上传参数因此逐字节不变。
    """
    cleaned = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32 and ch != "\x7f")
    cleaned = strip_display_controls(cleaned)
    cleaned = fold_name_disguise(cleaned)
    return cleaned.strip()


def name_visual_spoof_tags(name: str) -> tuple[str, ...]:
    """文件名/出站名的**显示伪装信号**（调用真身谓词，本处零判据）。

    与 :func:`sanitize_file_name` 的分工：消毒负责「落盘/出站名长什么样」，
    本口负责「这个名字有没有骗眼肉」——不可见伪装被消毒抹掉后信号即消失，
    同形伪装会留下 ``ascii_disguise`` / ``homoglyph_*`` 代号供审计与回执点名。
    出站侧（``FileSource`` 构造即消毒）与落盘侧（``restricted_runner`` 逐段消毒）
    都必经上面那枚消毒口，所以本口是**旁路取证**，不是第二道闸。
    """
    return find_visual_spoof_controls(str(name or ""))


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
    # 算法/流式实现收编中央件（媒体摘要层 S5，T121）：1MB chunk 同构，
    # 成功路径逐字节等价。中央件契约 OSError→None；本网关既有语义不吞错
    # （ticket.sha256 契约为 str），读不到时照旧向上抛 OSError——仅可达于
    # is_file()/stat() 已过后的竞态或权限窗口（:249 path stage 与 :303 url
    # stage 两调用点均有前置存在性检查）。
    digest = media_digest_file(path)
    if digest is None:
        raise OSError(f"sha256: unreadable file: {path}")
    return digest


# ---------------------------------------------------------------------------
# 邮件附件腿的取数与组装（真身仅此一处；装配层只递数据，不再自己拼 MIME）
# ---------------------------------------------------------------------------

#: 本能力会产出的文件族 → MIME。**表外一律 `application/octet-stream`，绝不猜一个
#: 像样的类型**（猜错=收件端按错类型打开＝谎报）。刻意不走 `mimetypes.guess_type`
#: 兜底：Windows 上它读注册表，同一份文件在两台机器上可能拿到不同媒体类型＝不确定行为。
#: 2026-09-26 跟随更新（S-FILESLAND-2）：能力层曾有第二张同义表
#: ``domains/files/sender/restricted_runner.py::MEDIA_TYPES_BY_EXTENSION``（2026-09-25
#: 同号两席并行撞出的），现已连同其消费方 ``build_aligned_file_outbound`` 一族整体
#: 出账（零生产调用点，判为删优于接）⇒ 媒体类型的唯一真身就是下面这一张。
#: 防回潮锁也随之从旧的「两表逐名对表」换成「第二张不许再长」＝
#: `tests/test_file_outbound_channels.py::test_runner_keeps_no_second_media_type_table`
#: （旧文案点名的那枚对表锁已随被删的表一起不存在了）。
_MAIL_ATTACHMENT_MIME: dict[str, tuple[str, str]] = {
    ".md": ("text", "markdown"),
    ".markdown": ("text", "markdown"),
    ".txt": ("text", "plain"),
    ".csv": ("text", "csv"),
    ".tsv": ("text", "tab-separated-values"),
    ".json": ("application", "json"),
    ".yaml": ("application", "yaml"),
    ".yml": ("application", "yaml"),
    ".toml": ("application", "toml"),
    ".py": ("text", "x-python"),
    ".pdf": ("application", "pdf"),
    ".docx": (
        "application",
        "vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xlsx": (
        "application",
        "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".pptx": (
        "application",
        "vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ".zip": ("application", "zip"),
    ".png": ("image", "png"),
    ".jpg": ("image", "jpeg"),
    ".jpeg": ("image", "jpeg"),
    ".gif": ("image", "gif"),
    ".bmp": ("image", "bmp"),
    ".webp": ("image", "webp"),
    ".wav": ("audio", "wav"),
}


def mail_attachment_mime(name: str) -> tuple[str, str]:
    """文件名 → (maintype, subtype)；表外不猜，落 octet-stream。"""
    suffix = Path(str(name or "")).suffix.lower()
    known = _MAIL_ATTACHMENT_MIME.get(suffix)
    if known is not None:
        return known
    return ("application", "octet-stream")


def normalize_mail_address(value: object) -> str:
    """地址归一（**只为名册比对**，不产用户可见文案）。

    与 `domains/transport/mail/mail_bridge.py::_email_address` 的分工是刻意的：
    那一枚负责「校验 + 抛中文报错」，输入必须是裸地址；本枚负责把任意形态
    （`名字 <a@b>` / 大小写混写 / 带空格）折成可比较的小写地址，不抛异常。
    两枚合并为单一真身待裁（席位报告 §陆），此处**不复制它的校验语义**。
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""
    _display, address = parseaddr(raw)
    candidate = (address or raw).strip()
    return candidate.lower()


def resolve_mail_recipient(target_id: str, allowed_recipients: Sequence[object]) -> str:
    """邮件收件人**只认配置名册**（需求 16(3) 的安全半边：外泄面收口）。

    三条不变式：

    1. 名册空 ⇒ 拒（`mail_recipients_unconfigured`）——绝不猜人，与校园/紧急域
       「白名单为空=整链关闭」同一口径。
    2. 目标不在名册 ⇒ 拒（`mail_recipient_not_allowlisted`）。会话正文里写
       「发到 attacker@evil.com」改不了投递面：本函数的入参只有
       `target_id`（装配层从配置/事件里的**地址事实**取）与名册，
       **从不扫正文、从不扫主题**。
    3. 比对在归一之后做（大小写/显示名不参与），避免「换个写法就出了名册」。
    """
    allowlist = {
        normalized
        for normalized in (
            normalize_mail_address(item) for item in allowed_recipients or ()
        )
        if normalized
    }
    if not allowlist:
        raise FileTransferError("mail_recipients_unconfigured")
    wanted = normalize_mail_address(target_id)
    if not wanted or wanted not in allowlist:
        raise FileTransferError("mail_recipient_not_allowlisted")
    return wanted


@dataclass(frozen=True)
class MailEnvelope:
    """邮件附件腿的信封：每枚字段都由**装配层/配置面**交进来，没有一枚从会话正文取。

    `daily_count` 是当日已投件数的读值（计数器真身在装配层：日限执法需要跨进程状态，
    本席不建第二本账）。传 `None` = 尚未接线 ⇒ 本腿放行但**记一行日志**，
    绝不把「没接计数器」读成「今天还剩 50 件」。
    """

    recipients_allowlisted: tuple[str, ...] = ()
    subject: str = ""
    body_text: str = ""
    sender_address: str = ""
    sender_name: str = ""
    daily_count: int | None = None


def attach_bytes_to_mail_message(
    message: EmailMessage, *, name: str, data: bytes
) -> tuple[str, str]:
    """把文件字节**真挂上**邮件（`multipart/mixed` + `Content-Disposition: attachment`）。

    返回实际使用的 (maintype, subtype)，供调用方/测试断言 MIME 形状。
    `filename` 走 `sanitize_file_name` 已经剥过分隔符的票据名，不回本地目录。
    """
    maintype, subtype = mail_attachment_mime(name)
    message.add_attachment(
        data, maintype=maintype, subtype=subtype, filename=name or "file"
    )
    return (maintype, subtype)


def build_mail_attachment_message(
    *,
    recipient: str,
    name: str,
    data: bytes,
    subject: str = "",
    body_text: str = "",
    sender_address: str = "",
    sender_name: str = "",
) -> EmailMessage:
    """组装「正文 + 一个附件」的邮件（正文过打码，附件字节**不打码**）。

    两条刻意的不对称：

    - 主题与正文先过 `redact_local_secrets`——盘符路径 / `BOT_XXX=` / `sk-` 形态
      一律不得出现在会话外发的**文字**里（铁律 3：不绕过出站打码）。
    - 附件字节原样：文件内容被"打码"就是损坏的交付物，宁可整件不发（由限额与
      路径域判定在挂载前拦）。
    """
    message = EmailMessage()
    display = str(sender_name or "").strip()
    if display:
        message["From"] = formataddr((display, sender_address))
    else:
        message["From"] = sender_address
    message["To"] = recipient
    message["Subject"] = redact_local_secrets(str(subject or "").strip() or name)
    message.set_content(
        redact_local_secrets(str(body_text or "")) or "文件见附件。"
    )
    attach_bytes_to_mail_message(message, name=name, data=data)
    return message


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
        # atkfix R2：邮件附件**当日已投件数**的权威计数册。全部邮件附件都经本
        # 网关的 ``_deliver_mail`` 这一条喉道投递，故计数与执法同处一地＝单一
        # 事实源（不另建第二本账）；跨进程如需共享再落持久层，本席先在喉道上
        # 把「在册未执法」的日限接活。按 UTC 日翻篇，只在**确认 SENT** 时自增。
        self._mail_daily_lock = threading.Lock()
        self._mail_day = ""
        self._mail_count_today = 0

    # -------------------- mail 日计数（atkfix R2） --------------------

    def mail_attachment_count_today(self) -> int:
        """当日（UTC）已确认投出的邮件附件件数——供装配层读入信封的 ``daily_count``。

        翻篇即时归零：跨日第一次读值即把计数复位，绝不把昨天的份数算进今天。
        """
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._mail_daily_lock:
            if day != self._mail_day:
                self._mail_day = day
                self._mail_count_today = 0
            return self._mail_count_today

    def _record_mail_attachment_sent(self) -> None:
        """仅在附件**确认 SENT** 后自增；超时/未知失败不计数（保守，绝不高估已投）。"""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._mail_daily_lock:
            if day != self._mail_day:
                self._mail_day = day
                self._mail_count_today = 0
            self._mail_count_today += 1

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
        # 路径域判定（SAFE-EXEC Wave 1 · 规格 §3 硬规则 1）：本行是**全通道唯一的
        # 取字节前判定**。此前只判 is_file() ⇒ 任何在允许名单里的能力给一个绝对
        # 路径（`C:\Windows\win.ini`）或 `..\..\` 穿越，就能把本机任意文件发给
        # QQ 对面的人。判定真身在 domains/core/safety_exec/paths.py，禁第二副本。
        decision = check_sendable(path)
        if decision.denied:
            # 拒绝原因进日志（打码形态，无盘符明文）供审计/诊断卡消费；对外只给
            # 稳定分类串，不把本地路径结构回给会话侧。
            logger.warning("file stage denied request path_domain %s", decision.audit_line())
            raise FileTransferError("path_domain_denied")
        if decision.verdict == VERDICT_NEEDS_REVIEW:
            # Wave 1 无同意回路（consent 归 S-T-CONS-1）⇒ 记账放行，留待收紧；
            # 这不是"没问题"，是"有账可查的已知面"。
            logger.warning("file stage needs_review %s", decision.audit_line())
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
        digest = media_digest(data)  # 中央件收编（S5，T121）：算法恒等。
        ticket_id = f"ft_{uuid.uuid4().hex[:12]}"
        name = src.name or f"{ticket_id}.bin"
        # A-8 裁定（2026-09-27）「守卫补到通道上」：bytes 腿历史上直写 %TEMP% 暂存、
        # 不过任何落点判定。补最小暂存守卫——target 规范化后必须仍在**本网关自己的**
        # staging_dir 内（两侧先 resolve()，防 8.3 短名把前缀守卫打穿）；判定排在
        # mkdir/写字节之前。正常流 target 恒在根内 ⇒ 行为零变化，只有异常拼装
        # （ticket_id/name 里混入越界写法）从「照写不误」变成拒发。
        target = self.staging_dir / f"{ticket_id}_{name}"
        staged = check_staged_target(target, self.staging_dir)
        if staged.denied:
            logger.warning("file stage bytes staging denied %s", staged.audit_line())
            raise FileTransferError("staging_target_denied")
        self._ensure_staging_dir()
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
        from plugins.bot_unified_runtime.domains.files.sources.downloader import (
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
        # 同 _stage_bytes：url 腿补暂存守卫（A-8 裁定 2026-09-27）。判两次——
        # ① 交给下载器之前：target 必须落在本网关暂存根内（不等到写完才发现写歪）；
        # ② 下载器回执之后：注入式实现若把件落到别处（或给相对名），票据不认。
        target = self.staging_dir / f"{ticket_id}_{name}"
        staged = check_staged_target(target, self.staging_dir)
        if staged.denied:
            logger.warning("file stage url staging denied %s", staged.audit_line())
            raise FileTransferError("staging_target_denied")
        self._ensure_staging_dir()
        try:
            downloaded = Path(self._url_downloader(url, target))
        except FileTransferError:
            raise
        except Exception as exc:
            raise FileTransferError("url_download_failed") from exc
        if not downloaded.is_file():
            raise FileTransferError("url_download_failed")
        landed = check_staged_target(downloaded, self.staging_dir)
        if landed.denied:
            logger.warning("file stage url landing denied %s", landed.audit_line())
            raise FileTransferError("staging_target_denied")
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
        transport: Literal["onebot", "telegram", "mail"] = "onebot",
        part_index: int = 0,
        budget: Any = None,
        caption: str = "",
        mail_envelope: MailEnvelope | None = None,
    ) -> FileTransferReceipt:
        if transport == "telegram":
            return await self._deliver_telegram_document(
                bot, ticket, target=target, part_index=part_index, caption=caption
            )
        if transport == "mail":
            return await self._deliver_mail(
                bot,
                ticket,
                target=target,
                part_index=part_index,
                caption=caption,
                envelope=mail_envelope,
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
            from plugins.bot_unified_runtime.domains.transport.sender.timeout import (
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
        # 三通道对齐修正（S-T-FILE-2 二段 · 需求 16(3)）：件名取**票据名**，
        # 不取暂存盘上的落盘名。`bytes` 来源的文件在 staging 里叫
        # `ft_<票号>_<名>`，旧写法让 Telegram 端看到的文件名与 QQ / 邮件两端不一致
        # （收件人拿到 `ft_ef2f84_report.md`）。`path` 来源两值本就相同 ⇒ 既有
        # golden 锁（tests/test_file_gateway_phase1.py:386-395、:505）逐字仍绿。
        delivered_name = ticket.name or path.name
        # §76.21 残余：文件 caption 也走 Telegram 原生 caption_entities（只在命中
        # 露骨词面时加，正文一字不改）。局部导入避开顶层循环（sender/nonebot.py 顶
        # 层就 import 本模块），偏移仍交适配器 Entity.build_telegram_entities 现算。
        # 遮罩只加在 Telegram 这一支；QQ(_deliver_onebot)/邮件(_deliver_mail) 不经此函数。
        from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
            _telegram_caption_entities_kwargs,
        )

        sent_caption = caption[:1000]
        result = await bot.send_document(
            chat_id=target.target_id,
            document=(delivered_name, path.read_bytes()),
            caption=sent_caption,
            **_telegram_caption_entities_kwargs(sent_caption),
        )
        return FileTransferReceipt(
            request_id=target.request_id,
            ticket_id=ticket.ticket_id,
            state=ReceiptState.SENT,
            name=delivered_name,
            size=ticket.size,
            sha256=ticket.sha256,
            part_index=part_index,
            provider_file_id=extract_provider_message_id(result),
            transport=TELEGRAM_DOCUMENT_TRANSPORT,
            provider_result=result,
        )

    async def _deliver_mail(
        self,
        bot: Any,
        ticket: FileTicket,
        *,
        target: SendRequest,
        part_index: int,
        caption: str,
        envelope: MailEnvelope | None,
    ) -> FileTransferReceipt:
        """邮件附件腿：与 QQ / Telegram 同权、同限额、**逐因可归因**。

        门序（每一步失败都有自己的 kind，绝不塌成一枚 broad except）：
        信封在场 → 收件人过配置名册 → 单条件数 → 每日件数 → 文件在场 → 单件字节
        → 挂载与组装 → 适配器出口 → 发送失败分类。
        """
        if envelope is None:
            raise FileTransferError("mail_envelope_missing")
        # ① 收件人只来自配置名册：名册空 / 不在册一律拒（详见 resolve_mail_recipient）。
        recipient = resolve_mail_recipient(
            target.target_id, envelope.recipients_allowlisted
        )
        # ② 单条件数：与归档侧既有缺省同值，不放宽；超限在发送前即可判定 ⇒ Final。
        if part_index >= MAIL_MAX_ATTACHMENTS_PER_MESSAGE:
            raise FinalTransferError("mail_attachment_count_exceeded")
        # ③ 每日件数：计数器归装配层（本席不建第二本账）。None = 未接线 ⇒
        #    放行但记一行，绝不把「没计数器」读成「额度还剩」。
        if envelope.daily_count is None:
            logger.warning(
                "mail attachment daily quota not wired: limit %s unenforced",
                MAIL_MAX_ATTACHMENTS_PER_DAY,
            )
        elif envelope.daily_count >= MAIL_MAX_ATTACHMENTS_PER_DAY:
            raise FinalTransferError("mail_daily_quota_exceeded")
        path = ticket.local_path
        if path is None or not path.is_file():
            raise FileTransferError("missing_file")
        # ④ 单件上限：引用 Telegram 同一枚常量（宽严一致），stat 先拒、读后复核，
        #    防 stat 与 read 之间文件被换大（TOCTOU 面最小化）。
        if ticket.size > MAIL_MAX_ATTACHMENT_BYTES:
            raise FinalTransferError("mail_attachment_too_large")
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning(
                "mail attachment read failed type=%s detail=%s",
                type(exc).__name__,
                str(exc)[:120],
            )
            raise FileTransferError("missing_file") from exc
        if len(data) > MAIL_MAX_ATTACHMENT_BYTES:
            raise FinalTransferError("mail_attachment_too_large")
        sender = str(envelope.sender_address or "").strip() or str(
            getattr(bot, "self_id", "") or ""
        ).strip()
        if not sender:
            raise FileTransferError("mail_envelope_missing")
        message = build_mail_attachment_message(
            recipient=recipient,
            name=ticket.name or path.name,
            data=data,
            subject=envelope.subject,
            body_text=envelope.body_text or caption,
            sender_address=sender,
            sender_name=envelope.sender_name,
        )
        send_mail = getattr(bot, "send_mail", None)
        if not callable(send_mail):
            raise FileTransferError("mail_send_api_unavailable")
        try:
            result = await send_mail(message)
        except FileTransferError:
            raise
        except asyncio.TimeoutError:
            # SMTP 侧超时：件**可能已发出**，故上层不得整体重投（与既有
            # 「有副作用绝不整体重投」外层契约同语义）。
            raise FileTransferError("mail_send_timeout") from None
        except Exception as exc:  # 分类为未知失败，不外泄适配器异常原文。
            logger.warning(
                "mail send call failed type=%s detail=%s",
                type(exc).__name__,
                str(exc)[:120],
            )
            raise FileTransferError("mail_send_failed_or_unknown") from exc
        # atkfix R2：确认出口回执在场（非超时/非未知失败）方计入当日已投件数，
        # 让下一次 ``_build_mail_attachment_envelope`` 读到真实递增后的日计数。
        self._record_mail_attachment_sent()
        return FileTransferReceipt(
            request_id=target.request_id,
            ticket_id=ticket.ticket_id,
            state=ReceiptState.SENT,
            name=ticket.name or path.name,
            size=len(data),
            sha256=ticket.sha256,
            part_index=part_index,
            # SMTP 出口不回消息号（适配器 `send_mail` 返回 None）⇒ 诚实留 None。
            # 装配层**不得**照抄 Telegram 那段「无 provider_file_id 即抛」的检查，
            # 否则邮件腿一次都发不出去（席位报告 §伍 已点名）。
            provider_file_id=None,
            transport=MAIL_ATTACHMENT_TRANSPORT,
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
