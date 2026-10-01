"""受限写盘运行器（需求 16(2)）：文件与文档「创建 / 修改」的唯一落盘口。

**为什么要有这一件**：本波之前，落盘动作散在两处——能力层
``file_exchange.export_document`` 自己 ``mkdir`` + 拼目标路径 + ``write_text``，
四个转换库又各拿这个路径 ``save()``；装配层（根 ``__init__.py``）另有一处
``target.write_bytes`` 把上传文件直接写进 ``incoming/``。两处都没有白名单、
没有大小与件数限额、没有扩展名与字节指纹的双查。任何一处被喂进脏输入，写的
就是 bot 进程权限内的任意路径。本件把这两个动词收成一个口，判据只在这一处
生效，能力层降为「声明要写什么」的一方。

**四条教义**（都有对应锁，见 ``tests/test_file_exchange_restricted_runner.py``）：

1. **fail-closed**：拿不到白名单根＝一律不写。缺省策略 ``allowed_roots=()``
   即「什么都不许写」，装配层必须显式给根。绝不「先让它跑起来再说」。
2. **验收全过才碰目标**：白名单 → 段名消毒（含拒 Win32 保留设备名） → 扩展名 →
   限额 → 字节指纹 → 越界复核 → 外部名册注入缝 → **禁触名册直判** → 动词语义 →
   配额，逐条判完才第一次触碰目的目录。
   超限/指纹不符的样本，目的目录里**连临时件都不会出现**（不是「写完再删」）。
3. **不建第二张名册**（AGENTS「禁第二真身」+ ``domains/core/safety_exec/paths.py``
   的自述约束）：本件只做写盘方向必需的四件事——剥分隔符、拒 ``..``、
   拒保留设备名、``resolve()`` 后 containment。「哪些目录/文件类别绝对禁触」那张
   名册的唯一真身是 ``paths.py``；本件留 ``external_verdict`` 注入缝接它，
   **不在这里抄第二份**。
   ⚠ 名册的接入分两层，别混：**禁触那一族是缺省就执法的**（``_publish_staged``
   第 ⑤b 步与 ``resolve_existing`` 各问 ``paths`` 一次，只认 ``domain==forbidden``，
   故白名单根被配歪到人格库/设置目录时仍拦得住，回读口同理）；**正向注册名册**
   （``outside_allowed_roots`` / ``needs_review``）**仍走注入缝**、缺省不接——它的
   根由装配层登记，写侧根是调用方逐次注入的（含测试 ``tmp_path``），拿它拦写会把
   合法落点全拦死。
   ⚠ 复核实测（2026-09-26，S-T-RUNNER-FIX；活性锁见 ``tests/test_restricted_runner_live.py``）：
   旧句「``paths.check_sendable()`` 今天每次调用都抛 ``TypeError``」已失效——真身签名
   现为 ``(candidate, *, policy=None)``（``paths.py`` 的 ``policy`` 参数已被并发波补上缺省），
   单位置参数调用返回 ``PathDecision``，不抛。但缺省仍**不接**，换两条**真的**理由：
   ① 契约是 ``Callable[[str], str]`` 而它返回对象，直插＝ ``str(PathDecision)`` 恒真 ⇒
   合法写也全被拦（症状与旧句同、机理不同，「接了当场失败」这半句仍然成立）；
   ② 它按 ``paths.py`` 登记的根判定，写侧白名单根是调用方逐次注入的，注册面之外
   一律 ``outside_allowed_roots``（连暂存 ``tmp_path`` 都拒）。接法唯一正门＝本件
   ``sendable_verdict`` 适配器（只放 ``allowed`` 判定，其余与异常一律拦）；是否在装配
   层接上属装配线决定，本件不越权改缺省。
4. **只写不跑**：本件不得出现 ``subprocess`` / ``exec`` / ``eval`` / ``compile`` /
   ``__import__`` / ``os.system`` 任何一枚。代码文件的「创建」与「执行」是两条
   独立开关：``file_exchange._CODE_EXECUTION_ENABLED=False`` 关的是后者，前者照常
   可用——这条由锁钉住，不靠注释。

内容摘要一律走中央件 ``domains/media/digest.py``（``media_digest``），不在这里
手抄 ``hashlib.sha256``——全树由 ``tests/test_media_identity_single_source_ratchet.py``
执法。

**三通道对齐**（需求 16(3)）不在本件：一条 ``FileSource`` → 一张 ``FileTicket`` →
QQ / Telegram / 邮件三条腿的同源投递，其唯一真身在 ``domains/transport``
（``file_gateway`` 三条腿 + ``sender/nonebot.py`` 装配口）。本件曾长着的对齐助手
``build_aligned_file_outbound`` 一族已按「删优于接」出账（2026-09-26 S-FILES-LAND，
墓碑见文末；防回潮锁见 ``tests/test_file_outbound_channels.py``）。
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.media.digest import media_digest
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    sanitize_file_name,
)

#: 本件的口径版本（进审计行；改判据语义要升版）。
RUNNER_ID: Final[str] = "files.restricted-runner/1"

# ---------------------------------------------------------------------------
# 动词与拒绝代号（稳定标识，进审计与回执；改名要同步测试）
# ---------------------------------------------------------------------------

VERB_CREATE: Final[str] = "create"
VERB_REPLACE: Final[str] = "replace"
MODE_CREATE: Final[str] = "create"
MODE_REPLACE: Final[str] = "replace"
MODE_CREATE_OR_REPLACE: Final[str] = "create_or_replace"
WRITE_MODES: Final[frozenset[str]] = frozenset(
    {MODE_CREATE, MODE_REPLACE, MODE_CREATE_OR_REPLACE}
)


class DenyCode:
    """一码一因，禁止全部塌成一枚兜底码（``paths.DenyReason`` 同一家规）。"""

    NO_WHITELIST: Final[str] = "no_whitelist"
    BAD_NAME: Final[str] = "bad_name"
    TRAVERSAL_DENIED: Final[str] = "traversal_denied"
    EXECUTABLE_DENIED: Final[str] = "executable_denied"
    EXTENSION_DENIED: Final[str] = "extension_denied"
    EMPTY_PAYLOAD: Final[str] = "empty_payload"
    TOO_LARGE: Final[str] = "too_large"
    MAGIC_MISMATCH: Final[str] = "magic_mismatch"
    OUTSIDE_WHITELIST: Final[str] = "outside_whitelist"
    EXTERNAL_GUARD_DENIED: Final[str] = "external_guard_denied"
    FORBIDDEN_DESTINATION: Final[str] = "forbidden_destination"
    TRANSFORM_FAILED: Final[str] = "transform_failed"
    ALREADY_EXISTS: Final[str] = "already_exists"
    TARGET_MISSING: Final[str] = "target_missing"
    RESERVED_NAME: Final[str] = "reserved_name"
    DAILY_QUOTA: Final[str] = "daily_quota"
    STAGING_UNAVAILABLE: Final[str] = "staging_unavailable"
    IO_ERROR: Final[str] = "io_error"


DENY_CODES: Final[frozenset[str]] = frozenset(
    {
        DenyCode.NO_WHITELIST,
        DenyCode.BAD_NAME,
        DenyCode.TRAVERSAL_DENIED,
        DenyCode.EXECUTABLE_DENIED,
        DenyCode.EXTENSION_DENIED,
        DenyCode.EMPTY_PAYLOAD,
        DenyCode.TOO_LARGE,
        DenyCode.MAGIC_MISMATCH,
        DenyCode.OUTSIDE_WHITELIST,
        DenyCode.EXTERNAL_GUARD_DENIED,
        DenyCode.FORBIDDEN_DESTINATION,
        DenyCode.TRANSFORM_FAILED,
        DenyCode.ALREADY_EXISTS,
        DenyCode.TARGET_MISSING,
        DenyCode.RESERVED_NAME,
        DenyCode.DAILY_QUOTA,
        DenyCode.STAGING_UNAVAILABLE,
        DenyCode.IO_ERROR,
    }
)

#: 人话说明（给会话面）。刻意**不含任何路径明文**：被拒的落点原文本身就是本机
#: 路径形态，回显它等于泄漏。要给人看细节只回显 ``reason_code``。
DENY_PLAIN_TEXT: Final[dict[str, str]] = {
    DenyCode.NO_WHITELIST: "没有登记可写目录，按最保守口径一律不落盘",
    DenyCode.BAD_NAME: "文件名消毒后什么都不剩，不写",
    DenyCode.TRAVERSAL_DENIED: "文件名含上级目录跳转写法，不写",
    DenyCode.EXECUTABLE_DENIED: "可执行/脚本类扩展名，写盘口也不收",
    DenyCode.EXTENSION_DENIED: "该扩展名不在本次可写白名单里",
    DenyCode.EMPTY_PAYLOAD: "空内容不落盘（宁可不写，也不留一个假的成功）",
    DenyCode.TOO_LARGE: "超出单文件字节限额，未写",
    DenyCode.MAGIC_MISMATCH: "字节指纹与扩展名不符（文本装不出二进制，反之也不行）",
    DenyCode.OUTSIDE_WHITELIST: "规范化后的落点在白名单之外",
    DenyCode.EXTERNAL_GUARD_DENIED: "外部路径判定（禁触名册）拦下",
    DenyCode.FORBIDDEN_DESTINATION: "落点命中禁触名册（配置/凭据/人格库/数据库一族），不写",
    DenyCode.TRANSFORM_FAILED: "改写函数没有产出可用内容（抛错或返回了非字节/非文本）",
    DenyCode.ALREADY_EXISTS: "同名文件已在，创建动词不覆盖",
    DenyCode.TARGET_MISSING: "目标不存在，修改动词不新建",
    DenyCode.RESERVED_NAME: (
        "文件名撞上 Windows 保留设备名（nul/con/aux/com0-9/lpt0-9/clock$ 一族）。"
        "这类名字写出去后，常规工具打不开也删不掉，落盘口与受限回读都不收。"
    ),
    DenyCode.DAILY_QUOTA: "今日件数配额已用满",
    DenyCode.STAGING_UNAVAILABLE: "暂存目录不可用，未写",
    DenyCode.IO_ERROR: "落盘失败（文件系统或权限）",
}


def plain_reason(code: str) -> str:
    """代号 → 人话。认不出只点名代号，绝不编解释。"""
    text = DENY_PLAIN_TEXT.get(code)
    if text:
        return text
    return f"未登记的写盘拒绝代号 {code}" if code else "未给出拒绝代号"


# ---------------------------------------------------------------------------
# 扩展名 / 字节指纹 / 媒体类型（一处登记，三处消费：写盘、邮件附件、审计）
# ---------------------------------------------------------------------------

#: 文本类：无固定魔数，但必须是合法 UTF-8、不含 NUL，也不得以二进制签名开头。
TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".csv",
        ".tsv",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".py",
    }
)

#: 二进制类：扩展名 → 可接受的起始签名字节集（不符即 ``magic_mismatch``）。
#: docx/xlsx/pptx 都是 OOXML 容器＝zip，故只认 ``PK\x03\x04``。
MAGIC_SIGNATURES: Final[dict[str, tuple[bytes, ...]]] = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".webp": (b"RIFF",),
    ".wav": (b"RIFF",),
}

#: 全部已知二进制签名（后置用：文本扩展名不得以其中任一枚开头）。
_BINARY_SIGNATURES: Final[tuple[bytes, ...]] = tuple(
    sorted({sign for signs in MAGIC_SIGNATURES.values() for sign in signs})
)

#: 可执行/脚本形态：在扩展名白名单**之前**先拦一层。即便某个策略把
#: ``allowed_extensions`` 放宽成 ``*``，这几枚也永远写不进去——落盘口不该是投递口。
DENIED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".exe",
        ".dll",
        ".ocx",
        ".sys",
        ".msi",
        ".bat",
        ".cmd",
        ".com",
        ".ps1",
        ".psm1",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".scr",
        ".lnk",
        ".reg",
        ".apk",
        ".jar",
        ".hta",
        ".cpl",
        ".msc",
    }
)

#: 本域默认「可写扩展名」＝导出文档 + 文本 + 代码文件（创建不执行，见教义 4）。
#: 图片/音频类不在缺省内：它们的落盘归媒体归档与渲染侧，不是文档写盘口。
DEFAULT_ALLOWED_EXTENSIONS: Final[frozenset[str]] = (
    (frozenset(MAGIC_SIGNATURES) | TEXT_EXTENSIONS)
    - frozenset({".zip", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".wav"})
)

# （扩展名→媒体类型那张表与「三通道对齐出站」一族已删优于接出账，2026-09-26
#  S-FILES-LAND：三腿投递唯一真身在 domains/transport（file_gateway 三条腿 +
#  sender/nonebot.py 装配口），本口只写不投（教义 4 的 AST 锁原样在）。防回潮锁在
#  tests/test_file_outbound_channels.py::test_runner_keeps_no_second_media_type_table；
#  回滚点＝%TEMP% 备份，位置见席位日志 S-FILES-LAND.md §伍。）

# ---------------------------------------------------------------------------
# 限额（缺省值建议；本席不落 ``config.py``，键名建议见交接日志 §伍.3）
# ---------------------------------------------------------------------------

DEFAULT_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_DAILY_CREATE_LIMIT: Final[int] = 60
DEFAULT_DAILY_REPLACE_LIMIT: Final[int] = 120

_SEGMENT_MAX_LEN: Final[int] = 120
#: Win32 保留设备名（basename 点号前那一段，不区分大小写；带任何扩展名同样命中）。
#: 这不是「第二张禁触名册」——禁触名册判的是**落点域**（哪些目录/文件类别禁触，
#: 唯一真身 ``safety_exec/paths.py``），本表判的是**段名形态**，与
#: ``_LEGAL_SEGMENT_RE`` 同族：同一个名字在别的 API 里是设备不是文件，落盘口收它
#: 只会产出一枚常规工具打不开也删不掉的挂件（实测 ``os.replace`` 能把
#: ``nul.txt`` 造进目录并回报成功，而 cmd 的 ``del nul.txt`` 把删除动作送进了空设备）。
#: 名册按微软「Naming Files, Paths, and Namespaces」保留名全集收齐（2026-09-27
#: 攻击审计 F-G2 补全）：COM0–COM9 / LPT0–LPT9 含 0 号（09-26 首版按「设备号从 1
#: 起」收窄了一格），另补历史/控制台边角 ``CLOCK$`` / ``CONIN$`` / ``CONOUT$``；
#: COM10/LPT10 不在保留集（现算负样本锁在 tests/test_seat_fix_rnames.py）。
_RESERVED_WIN32_BASENAMES: Final[frozenset[str]] = frozenset(
    {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    | {f"com{i}" for i in range(10)}
    | {f"lpt{i}" for i in range(10)}
)


def _is_reserved_device_name(segment: str) -> bool:
    """段名是否命中 Win32 保留设备名（点号前的首段、casefold 比对）。"""
    head = str(segment or "").split(".", 1)[0].casefold()
    return head in _RESERVED_WIN32_BASENAMES


#: 段名允许形态（消毒之后再判一次）：字母/数字/下划线/点/连字符/空格 + CJK/假名/谚文。
#: 刻意不含 ``:``（盘符与 NTFS ADS）与 ``\ /``（分隔符）——那两层在剥离段已拦。
_LEGAL_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9._\-\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af ]{1,120}$"
)


def _utc_date_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 策略与结论
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteLimits:
    """单文件字节上限 + 每日件数配额（配额按「白名单根 × 日期 × 动词」记）。

    ``limit < 0`` 视为不记配额（保留给「装配层今天不想限件数」的显式写法）。
    """

    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    daily_create_limit: int = DEFAULT_DAILY_CREATE_LIMIT
    daily_replace_limit: int = DEFAULT_DAILY_REPLACE_LIMIT

    def limit_for(self, verb: str) -> int:
        return self.daily_create_limit if verb == VERB_CREATE else self.daily_replace_limit


@dataclass(frozen=True)
class WritePolicy:
    """一次写盘的完整判据输入。

    ``allowed_roots`` 为空 ⇒ 什么都不许写（教义 1）。根目录**按真身注入**：生产由
    装配层给 ``bot_download_dir/export`` 一类，测试给 ``tmp_path``；本件不猜目录、
    不读 ``config``（避开「装配期快照看着能热改」那类坑）。

    ``external_verdict``＝禁触名册的注入口（教义 3）。约定：收规范化后的落点字符串，
    返回空串放行、返回非空拦下；**抛异常按拦下处理**（不猜）。缺省 ``None``＝不接，
    理由见模块 docstring。
    """

    allowed_roots: tuple[Path, ...] = ()
    allowed_extensions: frozenset[str] = DEFAULT_ALLOWED_EXTENSIONS
    denied_extensions: frozenset[str] = DENIED_EXTENSIONS
    limits: WriteLimits = field(default_factory=WriteLimits)
    external_verdict: Callable[[str], str] | None = None

    @property
    def has_whitelist(self) -> bool:
        return bool(self.allowed_roots)


@dataclass(frozen=True)
class WriteOutcome:
    """一次写盘的结论（成功也带身份三元组，供审计与三通道复用）。"""

    ok: bool
    reason_code: str
    detail: str
    path: Path | None
    verb: str
    name: str
    written_bytes: int
    sha256: str
    root_label: str

    @property
    def denied(self) -> bool:
        return not self.ok

    def error_message(self) -> str:
        """人话失败说明（无路径明文）。成功时返回空串。"""
        if self.ok:
            return ""
        return self.detail or plain_reason(self.reason_code)


def _deny(code: str, *, verb: str = "", name: str = "", detail: str = "") -> WriteOutcome:
    return WriteOutcome(
        ok=False,
        reason_code=code,
        detail=detail,
        path=None,
        verb=verb,
        name=name,
        written_bytes=0,
        sha256="",
        root_label="",
    )


def normalized_extension(name: str) -> str:
    """小写扩展名（无点则空串）。判定只看这一个口径。"""
    suffix = Path(str(name or "")).suffix.lower()
    return suffix if len(suffix) > 1 else ""


# ---------------------------------------------------------------------------
# 每日配额账（进程内计数；跨重启不持久——如实标注，见交接日志「诚实缺口」）
# ---------------------------------------------------------------------------


class DailyQuotaLedger:
    """线程安全的按日配额账。键 = ``(根标识, 日期, 动词)``。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, str], int] = {}

    @staticmethod
    def _key(root_label: str, date_key: str, verb: str) -> tuple[str, str, str]:
        return (root_label.casefold(), date_key, verb)

    def used(self, root_label: str, date_key: str, verb: str) -> int:
        with self._lock:
            return self._counts.get(self._key(root_label, date_key, verb), 0)

    def bump(self, root_label: str, date_key: str, verb: str) -> int:
        with self._lock:
            key = self._key(root_label, date_key, verb)
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


_DEFAULT_LEDGER = DailyQuotaLedger()


def default_quota_ledger() -> DailyQuotaLedger:
    """进程级缺省配额账（装配层若要接 SQLite 版，注入给自己的策略即可）。"""
    return _DEFAULT_LEDGER


# ---------------------------------------------------------------------------
# 段名消毒与 containment（教义 3：只做写盘必需的这三件，不建名册）
# ---------------------------------------------------------------------------


class _Rejected(Exception):
    """内部：携带拒绝代号，供发布流程统一转成 ``WriteOutcome``。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def sanitize_write_segments(ref: str | os.PathLike[str]) -> tuple[str, ...]:
    """把「相对落点」拆成安全段序列。

    单段剥离复用 ``file_gateway.sanitize_file_name``（basename + 控制字符），本函数
    只加写盘方向必需的两件事：**逐段拒 ``..``**、**段形态复查**。抛 ``_Rejected``
    （代号 ``bad_name`` / ``traversal_denied``）。
    """
    raw = str(ref or "").strip()
    if not raw:
        raise _Rejected(DenyCode.BAD_NAME)
    forward = raw.replace("\\", "/")
    if forward.startswith("/"):
        # 绝对写法（含 UNC 余形）不属于「相对落点」词汇。
        raise _Rejected(DenyCode.TRAVERSAL_DENIED)
    segments: list[str] = []
    for chunk in forward.split("/"):
        if chunk in {"", "."}:
            continue
        if chunk == "..":
            raise _Rejected(DenyCode.TRAVERSAL_DENIED)
        cleaned = sanitize_file_name(chunk)
        if cleaned in {"", ".", ".."}:
            raise _Rejected(DenyCode.BAD_NAME)
        if ".." in cleaned or ":" in cleaned:
            raise _Rejected(DenyCode.TRAVERSAL_DENIED)
        if not _LEGAL_SEGMENT_RE.match(cleaned):
            raise _Rejected(DenyCode.BAD_NAME)
        if _is_reserved_device_name(cleaned):
            # 排在段形态复查之后：形态先归位，再判设备名——「nul」与「nul.md」
            # 走同一格拒绝，不给「换个扩展名」留绕行面。
            raise _Rejected(DenyCode.RESERVED_NAME)
        segments.append(cleaned)
    if not segments:
        raise _Rejected(DenyCode.BAD_NAME)
    return tuple(segments)


def _norm_key(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in map(str, path.parts))


def _is_within(candidate: Path, root: Path | None) -> bool:
    if root is None:
        return False
    left, right = _norm_key(candidate), _norm_key(root)
    if not left or not right:
        return False
    return left == right or left[: len(right)] == right


def _resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _match_root(
    segments: Sequence[str], policy: WritePolicy
) -> tuple[str, Path, Path] | WriteOutcome:
    """段序列对每个白名单根做 resolve 后 containment。返回 ``(根标识, 根, 落点)``。"""
    for index, root in enumerate(policy.allowed_roots):
        resolved_root = _resolve(Path(str(root)))
        if resolved_root is None:
            continue
        candidate = resolved_root.joinpath(*segments)
        resolved_candidate = _resolve(candidate)
        if resolved_candidate is None or not _is_within(resolved_candidate, resolved_root):
            # 这一根不认（含链接外指、解析失败）：试下一根，全不中才拒。
            continue
        label = resolved_root.name or f"root{index}"
        return (label, resolved_root, resolved_candidate)
    return _deny(DenyCode.OUTSIDE_WHITELIST)


# ---------------------------------------------------------------------------
# 内容验收（字节指纹 / 文本性）
# ---------------------------------------------------------------------------


def inspect_payload(ext: str, data: bytes) -> str:
    """字节指纹与扩展名的相符性判定。

    返回 ``""``（相符/无从判定）或 ``magic_mismatch``。

    - ``MAGIC_SIGNATURES`` 登记的扩展名：必须命中其中一枚起始签名；
    - ``TEXT_EXTENSIONS`` 登记的扩展名：必须能按 UTF-8 解码、前 64 字节不含 NUL、
      且**不得**以任何已知二进制签名开头（一份 PNG 改名成 ``.md`` 要拒）；
    - 本表未登记而策略放行的扩展名：不猜，只看是否空件（配额与限额仍生效）。
    """
    if ext in MAGIC_SIGNATURES:
        signatures = MAGIC_SIGNATURES[ext]
        if any(data.startswith(sign) for sign in signatures):
            return ""
        return DenyCode.MAGIC_MISMATCH
    if ext in TEXT_EXTENSIONS:
        if b"\x00" in data[:64]:
            return DenyCode.MAGIC_MISMATCH
        if any(data.startswith(sign) for sign in _BINARY_SIGNATURES):
            return DenyCode.MAGIC_MISMATCH
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return DenyCode.MAGIC_MISMATCH
        return ""
    return ""


# ---------------------------------------------------------------------------
# 暂存 → 验收 → 原子发布
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagedWrite:
    """运行器签发的暂存位。转换库只管往 ``path`` 写，**发布权在运行器**。"""

    ref: str
    name: str
    extension: str
    path: Path
    staging_dir: Path

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            # 暂存清理失败不改写判定结论（Windows 上孙进程锁文件的既有先例同口径）。
            pass

    def accept_text(self, text: str) -> None:
        """把产物交给暂存位（UTF-8 + 平台换行，与旧 ``write_text`` 字节一致）。

        刻意不叫 ``write_text``：能力层里出现那个名字就该被 AST 锁拦下，
        「写盘原语只准在运行器一侧」必须是可机检的、而不是靠约定读代码。
        """
        self.path.write_text(str(text or ""), encoding="utf-8")

    def accept_bytes(self, data: bytes) -> None:
        self.path.write_bytes(bytes(data or b""))

    def publish(
        self,
        policy: WritePolicy,
        *,
        mode: str = MODE_CREATE,
        ledger: DailyQuotaLedger | None = None,
        date_key: Callable[[], str] | None = None,
    ) -> WriteOutcome:
        return _publish(self, policy, mode=mode, ledger=ledger, date_key=date_key)


def stage_write(
    ref: str | os.PathLike[str],
    *,
    staging_dir: str | os.PathLike[str] | None = None,
) -> StagedWrite | WriteOutcome:
    """签发暂存位。

    此阶段只判「名字与扩展名能不能要、暂存目录开不开得出来」；目的地的全部判据在
    ``publish`` 里，所以拿不到白名单根时这里仍会成功发号、而发布必拒（fail-closed
    发生在落点侧，不留半成品）。
    """
    try:
        segments = sanitize_write_segments(ref)
    except _Rejected as exc:
        return _deny(exc.code, detail=exc.detail, name=str(ref)[:_SEGMENT_MAX_LEN])
    name = segments[-1]
    ext = normalized_extension(name)
    if ext in DENIED_EXTENSIONS:
        return _deny(DenyCode.EXECUTABLE_DENIED, name=name)
    base = Path(str(staging_dir)) if staging_dir else (
        Path(tempfile.gettempdir()) / "bot_restricted_staging"
    )
    target = base / f"{uuid.uuid4().hex[:12]}_{name}"
    # A-8 裁定（2026-09-27）「暂存腿同理补守卫」：签发暂存位之前，先问唯一真身
    # ``paths.check_staged_target``——target 规范化后必须仍在本次暂存根内（两侧先
    # resolve()，8.3 短名不除外；判定排在 mkdir 之前，守卫不落盘）。名字这一层
    # ``sanitize_write_segments`` 已经拦下 ``..``/盘符/设备名，本判定是纵深防御：
    # 正常流恒 allowed ⇒ 行为零变化，异常拼装从「照发号」变成 STAGING_UNAVAILABLE。
    staged = paths.check_staged_target(target, base)
    if staged.denied:
        return _deny(
            DenyCode.STAGING_UNAVAILABLE, name=name, detail=staged.reason_code
        )
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _deny(DenyCode.STAGING_UNAVAILABLE, name=name)
    return StagedWrite(
        ref="/".join(segments),
        name=name,
        extension=ext,
        path=target,
        staging_dir=base,
    )


def _publish(
    staged: StagedWrite,
    policy: WritePolicy,
    *,
    mode: str,
    ledger: DailyQuotaLedger | None,
    date_key: Callable[[], str] | None,
) -> WriteOutcome:
    try:
        return _publish_staged(
            staged, policy, mode=mode, ledger=ledger, date_key=date_key
        )
    finally:
        # 暂存位由发布这一步回收：不管验收过没过，签发出去的位子都不留残件。
        staged.cleanup()


def _forbidden_destination_reason(target: Path) -> str:
    """问唯一真身 ``paths.py``：这个落点是不是禁触名册里的东西。

    口径：**只认 ``DOMAIN_FORBIDDEN`` 这一族**。``paths.check_sendable`` 还兼任「正
    向注册名册」判定（``outside_allowed_roots`` / ``needs_review``），那一张脸的根由
    装配层登记，写侧白名单根是调用方逐次注入的（含测试的 ``tmp_path``），拿它来拦写
    会把合法落点全拦死——所以这里只借「哪儿绝对禁触」这半张脸，正向放行判定留给
    ``external_verdict`` 注入缝（教义 3）。判定本身零副本：不比对目录名、不比对后缀，
    全交给 ``paths.py`` 说话，本件只读它返回的 domain。
    失败：判定件**抛异常＝拦下**（与本件 ``external_verdict`` 同一条纪律，不猜）；
    取不到 domain 或 domain 是 undetermined/outside/runtime ⇒ 不由这一腿表态。
    """
    try:
        decision = paths.check_sendable(str(target))
    except Exception:  # noqa: BLE001 - 判定件坏了＝不放行，不猜它能写什么
        return "forbidden_guard_unavailable"
    if str(getattr(decision, "domain", "") or "") != paths.DOMAIN_FORBIDDEN:
        return ""
    reason = str(getattr(decision, "reason_code", "") or "")
    return f"forbidden:{reason}" if reason else "forbidden"


def _publish_staged(
    staged: StagedWrite,
    policy: WritePolicy,
    *,
    mode: str,
    ledger: DailyQuotaLedger | None,
    date_key: Callable[[], str] | None,
) -> WriteOutcome:
    verb = VERB_REPLACE if mode == MODE_REPLACE else VERB_CREATE
    if mode not in WRITE_MODES:
        return _deny(DenyCode.BAD_NAME, verb=verb, name=staged.name, detail="未知的写盘模式")
    # ① 白名单在场（fail-closed）。
    if not policy.has_whitelist:
        return _deny(DenyCode.NO_WHITELIST, verb=verb, name=staged.name)
    # ② 扩展名：先拦可执行形态，再查白名单。
    ext = staged.extension
    if ext in policy.denied_extensions:
        return _deny(DenyCode.EXECUTABLE_DENIED, verb=verb, name=staged.name)
    if "*" not in policy.allowed_extensions and ext not in policy.allowed_extensions:
        return _deny(DenyCode.EXTENSION_DENIED, verb=verb, name=staged.name)
    # ③ 暂存件读入 + 限额 + 字节指纹（全在碰目标之前）。
    try:
        if not staged.path.is_file():
            return _deny(DenyCode.EMPTY_PAYLOAD, verb=verb, name=staged.name)
        size = staged.path.stat().st_size
    except OSError:
        return _deny(DenyCode.EMPTY_PAYLOAD, verb=verb, name=staged.name)
    if size <= 0:
        return _deny(DenyCode.EMPTY_PAYLOAD, verb=verb, name=staged.name)
    if size > policy.limits.max_file_bytes:
        return _deny(DenyCode.TOO_LARGE, verb=verb, name=staged.name)
    try:
        data = staged.path.read_bytes()
    except OSError:
        return _deny(DenyCode.IO_ERROR, verb=verb, name=staged.name)
    mismatch = inspect_payload(ext, data)
    if mismatch:
        return _deny(mismatch, verb=verb, name=staged.name)
    # ④ containment（只对规范化结果执法）。
    matched = _match_root(tuple(staged.ref.split("/")), policy)
    if isinstance(matched, WriteOutcome):
        return _deny(matched.reason_code, verb=verb, name=staged.name)
    root_label, _root, target = matched
    # ⑤ 外部禁触名册（注入缝）。异常＝拦下；**不把返回原文带上**——那是路径明文。
    if policy.external_verdict is not None:
        try:
            verdict = str(policy.external_verdict(str(target)) or "")
        except Exception:  # noqa: BLE001 - 判定件抛错＝不放行（不猜、不放行）
            verdict = "external_verdict_raised"
        if verdict:
            return _deny(DenyCode.EXTERNAL_GUARD_DENIED, verb=verb, name=staged.name)
    # ⑤b 禁触名册直判（**不依赖调用方注入**，排在注入缝之后＝调用方的判定先说话，
    #     它没接时才由本口兜底：缺省策略今天不带 ``external_verdict``，少这一腿就等于
    #     「咽喉只认调用方给的根」——把 BOT_DOWNLOAD_DIR 指到人格库/设置目录就能写。
    #     判定真身仍是 paths.py，本件不抄第二张名册。）
    if _forbidden_destination_reason(target):
        return _deny(DenyCode.FORBIDDEN_DESTINATION, verb=verb, name=staged.name)
    # ⑥ 动词语义。
    exists = target.exists()
    if mode == MODE_CREATE and exists:
        return _deny(DenyCode.ALREADY_EXISTS, verb=verb, name=staged.name)
    if mode == MODE_REPLACE and not exists:
        return _deny(DenyCode.TARGET_MISSING, verb=verb, name=staged.name)
    published_verb = VERB_REPLACE if exists else VERB_CREATE
    # ⑦ 每日配额（判据全过、**写成功之后**才记一次账）。
    active_ledger = ledger if ledger is not None else _DEFAULT_LEDGER
    day_key = (date_key or _utc_date_key)()
    limit = policy.limits.limit_for(published_verb)
    if limit >= 0 and active_ledger.used(root_label, day_key, published_verb) >= limit:
        return _deny(DenyCode.DAILY_QUOTA, verb=published_verb, name=staged.name)
    # ⑧ 原子落盘：同目录临时件 + ``os.replace``。前面任一判据不过都到不了这里，
    #    所以「超限/指纹不符」时目标目录连临时件都不会出现。
    digest = media_digest(data)
    tmp = target.parent / f".{target.name}.{uuid.uuid4().hex[:8]}.part"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return _deny(DenyCode.IO_ERROR, verb=published_verb, name=staged.name)
    active_ledger.bump(root_label, day_key, published_verb)
    return WriteOutcome(
        ok=True,
        reason_code="",
        detail="",
        path=target,
        verb=published_verb,
        name=target.name,
        written_bytes=len(data),
        sha256=digest,
        root_label=root_label,
    )


def _write_bytes(
    ref: str | os.PathLike[str],
    data: bytes,
    *,
    policy: WritePolicy,
    mode: str,
    ledger: DailyQuotaLedger | None,
    date_key: Callable[[], str] | None,
    staging_dir: str | os.PathLike[str] | None,
) -> WriteOutcome:
    payload = bytes(data or b"")
    if mode not in WRITE_MODES:
        return _deny(DenyCode.BAD_NAME, detail="未知的写盘模式")
    if len(payload) > policy.limits.max_file_bytes:
        # 超限载荷连暂存都不进：不制造「先写满盘再判超限」的自伤面。
        return _deny(DenyCode.TOO_LARGE)
    if not payload:
        return _deny(DenyCode.EMPTY_PAYLOAD)
    staged = stage_write(ref, staging_dir=staging_dir)
    if isinstance(staged, WriteOutcome):
        return staged
    try:
        staged.path.write_bytes(payload)
        return staged.publish(
            policy, mode=mode, ledger=ledger, date_key=date_key
        )
    finally:
        staged.cleanup()


def create_bytes(
    ref: str | os.PathLike[str],
    data: bytes,
    *,
    policy: WritePolicy,
    ledger: DailyQuotaLedger | None = None,
    date_key: Callable[[], str] | None = None,
    staging_dir: str | os.PathLike[str] | None = None,
) -> WriteOutcome:
    """创建（绝不覆盖）。``policy.allowed_roots`` 为空 ⇒ 不写。"""
    return _write_bytes(
        ref,
        data,
        policy=policy,
        mode=MODE_CREATE,
        ledger=ledger,
        date_key=date_key,
        staging_dir=staging_dir,
    )


def replace_bytes(
    ref: str | os.PathLike[str],
    data: bytes,
    *,
    policy: WritePolicy,
    ledger: DailyQuotaLedger | None = None,
    date_key: Callable[[], str] | None = None,
    staging_dir: str | os.PathLike[str] | None = None,
) -> WriteOutcome:
    """修改（绝不新建）。目标不存在即 ``target_missing``。"""
    return _write_bytes(
        ref,
        data,
        policy=policy,
        mode=MODE_REPLACE,
        ledger=ledger,
        date_key=date_key,
        staging_dir=staging_dir,
    )


def write_document(
    ref: str | os.PathLike[str],
    data: bytes,
    *,
    policy: WritePolicy,
    mode: str = MODE_CREATE_OR_REPLACE,
    ledger: DailyQuotaLedger | None = None,
    date_key: Callable[[], str] | None = None,
    staging_dir: str | os.PathLike[str] | None = None,
) -> WriteOutcome:
    """「创建或修改」单口（同主题重导即更新；动词由运行器判，不留静默覆盖）。"""
    return _write_bytes(
        ref,
        data,
        policy=policy,
        mode=mode,
        ledger=ledger,
        date_key=date_key,
        staging_dir=staging_dir,
    )


def resolve_existing(
    ref: str | os.PathLike[str], *, policy: WritePolicy
) -> Path | WriteOutcome:
    """在**写侧白名单之内**定位一个已存在的文件（「修改已有文件」腿的寻址口）。

    口径：判据与 ``publish`` 用的是同一套件（``sanitize_write_segments`` +
    ``_match_root`` + 禁触名册直判 + ``denied_extensions``），绝不因为「只是读一下」
    就少走路——回读口若自成一套，绕过咽喉的第二条路就从这里长出来。
    失败：白名单不在场→``no_whitelist``；段名不合法/穿越→``bad_name``/
    ``traversal_denied``；落点不在任一白名单根内→``outside_whitelist``；命中禁触
    名册→``forbidden_destination``；文件不存在（或是目录）→``target_missing``。
    配置：不读 config——根与限额都由调用方经 ``WritePolicy`` 交进来。
    """
    name_hint = str(ref)[:_SEGMENT_MAX_LEN]
    if not policy.has_whitelist:
        return _deny(DenyCode.NO_WHITELIST, name=name_hint)
    try:
        segments = sanitize_write_segments(ref)
    except _Rejected as exc:
        return _deny(exc.code, detail=exc.detail, name=name_hint)
    name = segments[-1]
    if normalized_extension(name) in policy.denied_extensions:
        return _deny(DenyCode.EXECUTABLE_DENIED, name=name)
    matched = _match_root(segments, policy)
    if isinstance(matched, WriteOutcome):
        return _deny(matched.reason_code, name=name)
    _label, _root, target = matched
    if _forbidden_destination_reason(target):
        return _deny(DenyCode.FORBIDDEN_DESTINATION, name=name)
    if not target.is_file():
        return _deny(DenyCode.TARGET_MISSING, name=name)
    return target


def _read_confined_target(
    target: Path, policy: WritePolicy
) -> tuple[bytes, str] | WriteOutcome:
    """已定位落点的受限回读：限额 + 读全量 + 中央摘要，一次做完。"""
    try:
        size = target.stat().st_size
    except OSError:
        return _deny(DenyCode.TARGET_MISSING, name=target.name)
    if size > policy.limits.max_file_bytes:
        # 超限一律不回读：回读本身就是「把整份文件吃进内存」的动作，
        # 拿它绕过 ``max_file_bytes`` 等于给限额开了个只读后门。
        return _deny(DenyCode.TOO_LARGE, name=target.name)
    try:
        data = target.read_bytes()
    except OSError:
        return _deny(DenyCode.IO_ERROR, name=target.name)
    return data, media_digest(data)


def read_confined_bytes(
    ref: str | os.PathLike[str], *, policy: WritePolicy
) -> tuple[bytes, str] | WriteOutcome:
    """读回一份**本口写得着**的文件，返回 ``(字节, sha256)``。

    口径：这是「修改」腿的回读半边——只准读白名单根内、且不在禁触名册里的东西。
    全仓没有别的受限回读口，故能力层若要实现读-改-写，必须走这里，不许自己
    ``Path.read_bytes()``（那会把咽喉的 containment 判据复制成第二份）。
    失败：与 ``resolve_existing`` 同一族代号，外加 ``too_large``（超单文件限额）
    与 ``io_error``。被拒结论里的 ``detail`` 不含路径明文。
    """
    located = resolve_existing(ref, policy=policy)
    if isinstance(located, WriteOutcome):
        return located
    return _read_confined_target(located, policy)


def revise_in_place(
    ref: str | os.PathLike[str],
    #: 返回型写 ``object`` 是刻意的：本口**允许**改写函数返回别的形状，
    #: 然后按 ``transform_failed`` 拒掉——把签名写成 ``bytes | str`` 会让
    #: 「它返回了 None」这一格只能靠 mypy 之外的运行时兜底，判据反而含糊。
    transform: Callable[[bytes], object],
    *,
    policy: WritePolicy,
    ledger: DailyQuotaLedger | None = None,
    date_key: Callable[[], str] | None = None,
    staging_dir: str | os.PathLike[str] | None = None,
) -> WriteOutcome:
    """读-改-写单口：回读 → 交给纯函数改写 → 以 **replace** 动词原子发布。

    口径：「修改已有文件」的四条教义在这一处凑齐——**目标必须在**（``mode`` 走
    ``MODE_REPLACE``，缺文件即 ``target_missing``，绝不借改之名新建）、**判据不复制**
    （回读用同一套白名单+禁触名册判据，发布再走 ``publish`` 的全套验收）、
    **改写函数拿不到写权限**（它只收字节、返字节或文本，不碰文件也不碰路径）、
    **没变化就不写**（同字节回写会白烧一格日配额并刷新 mtime，那是对「改了什么」
    说谎）。内容整体替换用 ``replace_bytes``，逐字节变换用本函数——两者是同一颗
    咽喉的两个入口，不是两条通路。
    失败：回读族的代号原样返回（判定发生在暂存之前，目的地不留残件）；
    ``transform`` 抛异常或返回非 ``bytes``/``str`` → ``transform_failed``，
    ``detail`` 只带异常类型名，不回显文件内容也不带路径。
    配置：限额与配额沿用 ``policy.limits``；本函数不读 config。
    """
    located = resolve_existing(ref, policy=policy)
    if isinstance(located, WriteOutcome):
        return located
    target = located
    read_back = _read_confined_target(target, policy)
    if isinstance(read_back, WriteOutcome):
        return read_back
    original, original_digest = read_back
    try:
        produced = transform(original)
    except Exception as exc:  # noqa: BLE001 - 改写函数抛错＝不写，只点名类型
        return _deny(
            DenyCode.TRANSFORM_FAILED,
            verb=VERB_REPLACE,
            name=target.name,
            detail=f"改写函数抛出 {type(exc).__name__}，原文件未改动。",
        )
    if isinstance(produced, str):
        payload = produced.encode("utf-8")
    elif isinstance(produced, (bytes, bytearray)):
        payload = bytes(produced)
    else:
        return _deny(
            DenyCode.TRANSFORM_FAILED,
            verb=VERB_REPLACE,
            name=target.name,
            detail="改写函数要返回字节或文本，本次未写盘。",
        )
    if payload == original:
        return WriteOutcome(
            ok=True,
            reason_code="",
            detail="内容未变化，未写盘",
            path=target,
            verb=VERB_REPLACE,
            name=target.name,
            written_bytes=0,
            sha256=original_digest,
            root_label="",
        )
    if not payload:
        # 空产物单独说：``transform`` 把整份文件抹空与「读出来就是空的」不是一回事，
        # 而写盘口对空件一律不收（EMPTY_PAYLOAD 的口径在 publish 一侧同样成立）。
        return _deny(
            DenyCode.TRANSFORM_FAILED,
            verb=VERB_REPLACE,
            name=target.name,
            detail="改写函数返回空内容，不写（原文件未改动）。",
        )
    return replace_bytes(
        ref,
        payload,
        policy=policy,
        ledger=ledger,
        date_key=date_key,
        staging_dir=staging_dir,
    )


def policy_for_roots(
    roots: Iterable[str | os.PathLike[str]],
    *,
    allowed_extensions: frozenset[str] | None = None,
    limits: WriteLimits | None = None,
    external_verdict: Callable[[str], str] | None = None,
) -> WritePolicy:
    """装配层便捷口：给根列表造策略。空根列表 ⇒ 空策略 ⇒ 什么都不许写。"""
    materialized = tuple(Path(str(item)) for item in roots if str(item or "").strip())
    return WritePolicy(
        allowed_roots=materialized,
        allowed_extensions=(
            DEFAULT_ALLOWED_EXTENSIONS if allowed_extensions is None else allowed_extensions
        ),
        limits=limits or WriteLimits(),
        external_verdict=external_verdict,
    )


def sendable_verdict(candidate: str) -> str:
    """禁触名册 → ``external_verdict`` 契约的**唯一**适配器（教义 3 的正门）。

    真身 ``paths.check_sendable()`` 返回 ``PathDecision``，而注入缝的契约是
    ``Callable[[str], str]``（空串＝放行）——直插真身会让 ``str(decision)`` 恒真、
    把所有合法写一并拦死（模块 docstring 教义 3 记的正是这个坑的旧误判）。本函数
    把两侧翻译一次，判据本身零副本：

    - 判定 **恰为** ``allowed`` ⇒ 返回空串（放行）。``needs_review`` **不放行**：
      那是为读/出站口设计的「记账放行」档，写盘口没有同意回路，按 fail-closed 拦；
    - ``denied`` / ``needs_review`` / 认不出的判定 / 判定件抛异常 ⇒ 返回稳定代号
      （只含 ``reason_code`` 级信息，**绝不回传决策对象原文**——那里可能带路径形态）；
    - 缺依赖/判定件不可用：明说 ``sendable_guard_unavailable``，不静默放行。

    用法（装配层，非本件缺省）：``policy_for_roots([...], external_verdict=sendable_verdict)``。
    """
    try:
        decision = paths.check_sendable(candidate)
    except Exception:  # noqa: BLE001 - 判定件抛错＝拦下（不猜、不放行）
        return "sendable_guard_unavailable"
    verdict = str(getattr(decision, "verdict", "") or "")
    if verdict == paths.VERDICT_ALLOWED:
        return ""
    reason = str(getattr(decision, "reason_code", "") or "")
    return f"sendable_denied:{reason}" if reason else "sendable_denied"


# ---------------------------------------------------------------------------
# （尾节已出账）三通道对齐出站族：删优于接（2026-09-26 S-FILES-LAND）
#
# ``build_aligned_file_outbound`` / ``AlignedFileOutbound`` / ``AttachmentPart`` /
# ``MEDIA_TYPES_BY_EXTENSION`` / ``attachment_media_type`` / ``split_media_type`` /
# ``plain_outbound_body`` / ``contains_local_path_shape`` 全仓零生产调用点，且
# 与 domains/transport 的三腿真身重复（QQ upload_group_file/upload_private_file、
# TG send_document、邮件 add_attachment——都带限额与打码，见 file_gateway.py 与
# sender/nonebot.py:420-470）。本口依教义 4「只写不投」，投递判据不留第二家。
# 防回潮锁：tests/test_file_outbound_channels.py::test_runner_keeps_no_second_media_type_table
# 与 tests/test_files_domain_audit.py::test_aligned_outbound_helper_is_wired_or_gone。
# 回滚点：%TEMP% 备份（S-FILES-LAND.md §伍记位置与 sha256 前 16 位）。
# ---------------------------------------------------------------------------
