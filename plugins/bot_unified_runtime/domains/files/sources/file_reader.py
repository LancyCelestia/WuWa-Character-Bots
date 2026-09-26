"""Safe, non-executing readers and generated-file helpers.

不变量（2026-09-25 S-PDF-1 立，锁在 ``tests/test_file_reader_parse_safety.py``）：
``read_supported_file`` 对**内容问题**一律诚实降级，绝不抛异常。理由：它的三个消费方
里只有根 ``__init__.py`` 的入站归一带一层窄捕获（``ImportError/OSError/ValueError/
TypeError``），控制面 ``POST /files/read`` 完全没有 try。历史上 V2.1 风险 8 只补了
旧 OLE2 分支（.xls/.ppt），**现代格式分支一直留着同一个洞**——pypdf 未装时 PDF 恒走
ImportError 被顺带兜住，装上 pypdf 后立刻变活：群里任何人发一个坏 PDF，或把任意 zip
改名成 .docx/.xlsx/.pptx，异常就从这里逃出、撞穿消息入站链路。

第二不变量（2026-09-26 S-PDF-2 立，锁在 ``tests/test_file_ingress_failure_feedback.py``）：
两态降级必须被**消费**、不许静默——``PARSE_STATUS_SENTENCES`` /
``file_read_failure_note`` 是「没读到」措辞的唯一真身，消费方（根入站归一与中央
``files.read.*`` handler）不得各存一份文案，两态不许并成一态。

第三不变量（2026-09-26 S-T-PDF-3 立，锁在 ``tests/test_pdf_scan_honesty.py``）：
PDF 扫描链**「没读」永远不许写成「没有」**——页数截断、字符截断、页级错误、口令
保护、空文本（扫描/空白/无页三态）与低中文解码质量各自显式说明；量化验收尺
``cjk_decode_ratio`` 达标线 ``DECODE_ACCEPT_RATIO``（已解码 CJK / (已解码 CJK+疑似
乱码字形) ≥ 0.8），这条尺是现算出来的，不是「哪个包看起来更强」的印象分。
"""

from __future__ import annotations

import ast
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from plugins.bot_unified_runtime.domains.files.sender.restricted_runner import (
    WriteLimits,
    create_bytes,
    plain_reason,
    policy_for_roots,
)

_TEXT_EXTS = {
    ".txt",
    ".log",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".cs",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".php",
    ".sh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".xml",
    # LaTeX 源=纯文本（S10 协议面 files.read.latex 的诚实文本路；不编译不执行）。
    ".tex",
}
_CODE_EXTS = {
    ".py",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".cs",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".php",
    ".sh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
}


@dataclass(frozen=True)
class FileReadResult:
    path: Path
    kind: str
    text: str
    title: str = ""
    metadata: dict[str, Any] | None = None


#: 「没读到」两态措辞的**唯一真身**（2026-09-26 S-PDF-2，锁在
#: ``tests/test_file_ingress_failure_feedback.py``）。
#:
#: 历史：这张表 2026-09-25 只活在中央 ``files.read.*`` handler 里（S-PDF-1），
#: 而该 handler 在生产**零调用点**——真实入站路径上坏文件与缺解析器都表现为
#: ``text=""`` 被静默吞掉。本波把它提为模块级单一来源，handler 与根入站归一
#: （``__init__.py::_incoming_from_nonebot_event``）共用，措辞只此一份。
#: 两态合并成一态 = 注毒必红（test_file_ingress_failure_feedback）。
PARSE_STATUS_SENTENCES: dict[str, str] = {
    # 文件本身坏了 / 内容与后缀不符（伪 OOXML、垃圾字节、缺 zip 成员）。
    "parse_failed": "文件损坏或格式与后缀不符，未读到内容",
    # 环境缺件：未装解析器，或旧 OLE2 格式本链路无适配器。
    "parser_unavailable": "无可用解析器，不冒充解析成功",
    # 解析器抛出了逐处枚举没写到的那一类异常＝我们或某个库自己出的错。
    # 单列一态而不是并进 parse_failed：把程序故障说成"你的文件坏了"是谎报，
    # 说成"没这个问题"更是——它只保证不再打断消息入站（S-16-PDF-EXC-SURFACE）。
    "internal_parse_error": "解析这个文件时程序自己出了错，没读出内容（不是你的文件损坏）",
}


def parse_status_sentence(status: str) -> str:
    """状态代号 → 人话主句；表外状态返回空串（绝不猜一条归因）。"""
    return PARSE_STATUS_SENTENCES.get(status, "")


#: 「读到但没字」四态措辞（2026-09-26 S-T-PDF-3，锁在 ``tests/test_pdf_scan_honesty.py``）。
#: 与 ``PARSE_STATUS_SENTENCES`` 分表是刻意的：那枚「恰两态」结构锁
#: （test_file_ingress_failure_feedback::test_sentence_table_is_exactly_the_two_states）
#: 钉的是「环境缺件 vs 文件损坏」；本表钉的是「解析成功之后为什么没有字」，
#: 四态互斥，任何两态并一（把扫描件说成空白页 = 谎报）必红。
#: 这些态**不占 status 字段**（存量锁 ``test_blank_pdf_reads_as_empty_not_as_failure``
#: 钉住空白 PDF ``status is None``），走 ``metadata["pdf_scan"]["empty_reason"]``。
SCAN_EMPTY_SENTENCES: dict[str, str] = {
    "scanned_no_text": (
        "解析成功，但所读页里没有文字层、只有图像（图像型/扫描件）。"
        "OCR 兜底今天不生效：全树没有 OCR 组件、没有配置开关、也没有装配点，"
        "图像里的字我读不出来——这是「读不了」，不是「没有内容」"
    ),
    "blank_pages": "解析成功，但所读的每一页确实都没有文字（空白页）",
    "no_pages": "这份 PDF 没有声明任何可读页面",
    "page_errors": "所读页面全部因页对象内部错误没读到（没读到不等于没有内容）",
}

#: 「没读到」家族里的新态（S-T-PDF-3）：口令保护的 PDF 既不是损坏、也不是缺解析器。
#: 旧链把 FileNotDecryptedError（⊂PdfReadError⊂PyPdfError，生产 venv 实测）吞进
#: parse_failed，报成「损坏或不是有效的 PDF」=归因谎报；本态单独成句。
#: 不并入 PARSE_STATUS_SENTENCES 同一理由：那枚恰两态结构锁。
NOTE_STATUS_SENTENCES: dict[str, str] = {
    "password_protected": "文件设有打开口令（口令保护），没有口令读不出来——这不是文件损坏",
}

#: 沉默两态（``kind`` 面）措辞唯一真身（2026-09-26 S-FILES-LAND，需求 16(1) 第三格）。
#: 历史：这两态在入站时长期**一字不说**（``text=""`` 且 note 返空 ⇒ 会话面无反馈），
#: 与 S-T-PDF-3 已修的「status 族」「pdf 空字族」并成读诚实化三格；主裁定「读不了要
#: 说读不了+为什么」。句子只声明可核对事实（没有读取通道 / 文件不在原处），
#: **不猜内容**——这正是旧锁「归因不许瞎猜」的初衷，不是它的反面。
#: 锁在 ``tests/test_files_domain_audit.py::test_unsupported_or_missing_file_still_gets_a_plain_sentence``。
KIND_SILENCE_SENTENCES: dict[str, str] = {
    "unknown": "这个类型我没有读取通道（不猜它里面写了什么）",
    "missing": "文件已不在原处或平台没把内容交回来（没读到不等于没有内容）",
}

#: 中文解码质量量化尺（S-T-PDF-3 采纳并落码；09-26 在真实中文 PDF 上实测校准：
#: pypdf 6.19.0 明文路 129309/129309 CJK、乱码 0，ratio=1.0；0.8 线同时拦得住
#: 无 ToUnicode 的 CID 字体乱码形——那类文档 ratio 远低于线）。
DECODE_ACCEPT_RATIO = 0.8

#: PDF 扫描缺省页数上限：装配点（根入站）要按配置调时传 ``scan_max_pages`` 形参，
#: 键位开通前不猜数（本席禁改 config.py，见 S-T-PDF-3 日志 §5）。
PDF_SCAN_MAX_PAGES = 60

_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2EBEF),
)
#: 「疑似乱码」三类：U+FFFD 替换符、私用区（缺 ToUnicode 的 CID 字体常见落点）、
#: 非空白的 C0 控制符（Identity-H 无 ToUnicode 时 pypdf 实测吐 \x01\x02 这一族）。
_GARBLED_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def _in_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> int:
    return sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in ranges))


def count_cjk_chars(text: str) -> int:
    """CJK（含扩展 A/B、兼容表意）字符数——量化尺的分子。"""
    return _in_ranges(text, _CJK_RANGES)


def count_garbled_chars(text: str) -> int:
    """疑似乱码字形数：替换符 + 私用区 + 非空白 C0 控制符——量化尺的坏项。"""
    return (
        text.count("\ufffd")
        + _in_ranges(text, _GARBLED_RANGES)
        + sum(
            1
            for ch in text
            if ord(ch) < 0x20 and ch not in "\t\n\r" or ord(ch) == 0x7F
        )
    )


def cjk_decode_ratio(text: str) -> float | None:
    """已解码 CJK / (已解码 CJK + 疑似乱码)。无 CJK 也无乱码证据 → None（不猜）。

    None 表示「本尺不适用」（纯英文文档），**不是** 0 也不是 1。
    """
    cjk = count_cjk_chars(text)
    garbled = count_garbled_chars(text)
    if cjk + garbled == 0:
        return None
    return cjk / (cjk + garbled)


def file_read_failure_note(result: FileReadResult) -> str:
    """入站归一注入对话面的一行：中文主句 + 可核对技术事实。

    覆盖四族（S-T-PDF-3 扩两族；S-FILES-LAND 补第三格）：
    ① ``parse_failed`` / ``parser_unavailable`` 两枚诚实降级态（``PARSE_STATUS_SENTENCES``）；
    ② ``password_protected``（``NOTE_STATUS_SENTENCES``）——同挂「读取失败」标签但句子
       明说口令、不说损坏；
    ③ PDF「读到但没字」四态（``SCAN_EMPTY_SENTENCES``，经 ``metadata["pdf_scan"]``）
       ——换「文件无文字」标签与「读到了，但没有可提取的文字」主句，
       因为对它说「读不出来」本身就是谎报；
    ④ ``kind`` 为 ``unknown`` / ``missing`` 的沉默两态（``KIND_SILENCE_SENTENCES``）——
       旧行为是一字不说（会话面把「发错了文件」整口吞掉），2026-09-26 主裁定改为
       「读不了要说读不了+为什么」；句子只陈述 kind 这个已在结果对象上的事实，不猜内容。
    读取成功、以及受支持类型「读到但空」仍返回空串（不许对读到了的东西说读不了）。
    内容只含文件名、措辞与状态代号——解析器异常原文带绝对路径，绝不上卡面/对话面
    （对齐 ``_degrade`` 的约定；出站前另有 ``redact_local_secrets`` 打码，本函数不
    绕过它、也不如它）。
    """
    metadata = result.metadata or {}
    status = str(metadata.get("status") or "")
    name = str(result.title or result.path.name or "未命名文件")
    if status:
        sentence = parse_status_sentence(status) or NOTE_STATUS_SENTENCES.get(status, "")
        if not sentence:
            return ""
        fmt = str(metadata.get("format") or "")
        return (
            f"[文件读取失败：{name}] 这个文件我读不出来：{sentence}。"
            f"技术事实（可核对）：文件名={name}，status={status}，归类={fmt}"
        )
    scan = metadata.get("pdf_scan")
    if isinstance(scan, dict):
        reason = str(scan.get("empty_reason") or "")
        sentence = SCAN_EMPTY_SENTENCES.get(reason, "")
        if not sentence:
            return ""
        return (
            f"[文件无文字：{name}] 这个文件我读到了，但没有可提取的文字：{sentence}。"
            f"技术事实（可核对）：文件名={name}，empty_reason={reason}，"
            f"页数=读了{scan.get('pages_read', 0)}/共{scan.get('pages_total', 0)}，"
            f"含图页={scan.get('image_pages', 0)}"
        )
    # 第三格（S-16-READ-HONESTY，2026-09-26 S-FILES-LAND）：unsupported（kind=unknown）
    # 与消失（kind=missing）不再一字不说。只在「无 status、无 pdf_scan、正文空」三者
    # 同时成立时开口——受支持类型读到但为空仍交调用方按空正文处理，这里绝不把「读到了
    # 空东西」谎报成「读不了」，也不给已成功的读取补一句失败。句子只陈述 kind 这个已在
    # 结果对象上的事实（没有读取通道 / 文件不在原处），不猜内容（对齐旧锁「归因不许瞎猜」）。
    kind = str(result.kind or "")
    if kind in KIND_SILENCE_SENTENCES and not str(result.text or "").strip():
        suffix = result.path.suffix.lower() or "（无扩展名）"
        return (
            f"[文件读不了：{name}] 这个文件我读不出来：{KIND_SILENCE_SENTENCES[kind]}。"
            f"技术事实（可核对）：文件名={name}，kind={kind}，后缀={suffix}"
        )
    return ""


@dataclass(frozen=True)
class GeneratedFile:
    path: Path
    kind: str


def _text(path: Path, max_chars: int) -> str:
    raw = path.read_bytes()[: max_chars * 4]
    if b"\x00" in raw[:4096]:
        return ""
    return raw.decode("utf-8", errors="replace")[:max_chars]


def _degrade(source: Path, kind: str, label: str, *, status: str) -> FileReadResult:
    """诚实降级的统一出口。

    ``label`` 只准是归类短语（「损坏或不是有效的 PDF」这类），**不得**放解析器抛出的
    原文——那些字符串里带绝对路径，会随 ``CapabilityResult`` 与诊断卡出站。
    """
    return FileReadResult(
        source, kind, "", source.name, {"status": status, "format": label}
    )


logger = logging.getLogger(__name__)


def read_supported_file(
    path: str | Path,
    *,
    max_chars: int = 120000,
    scan_max_pages: int | None = None,
) -> FileReadResult:
    """公共口：不变量①（"对内容问题一律诚实降级、绝不抛异常"）的**结构性**保证。

    逐处 ``except`` 的异常类枚举保留细归因（口令保护/内容损坏/缺解析器各有各的
    说法，那些措辞是给她看的），这一层只兜「枚举没写到的那一类」。光靠枚举在结构上
    就不成立：一枚畸形加密 PDF 让 ``decrypt`` 抛出不在元组里的 ``RuntimeError``，
    便能一路逃到消息入站归一（根件只兜 ImportError/OSError/ValueError/TypeError），
    后果是**一个坏文件打断整条入站链路**（登记名 S-16-PDF-EXC-SURFACE）。

    收敛成 ``internal_parse_error`` 而不是并进 ``parse_failed``：把程序故障说成
    "文件损坏"是谎报归因。异常类名进 ``metadata['exc']`` 与一行 WARNING，
    只留文件名、不留绝对路径（措辞出口口径同 ``_degrade``）。
    """
    source = Path(path).expanduser()
    try:
        return _read_supported_file_body(
            path, max_chars=max_chars, scan_max_pages=scan_max_pages
        )
    except Exception as exc:  # noqa: BLE001 - 入站咽喉必须兜全部，归因写"程序出错"而非猜文件坏了
        logger.warning(
            "file read raised an unclassified error: file=%s error=%s",
            source.name,
            type(exc).__name__,
        )
        return FileReadResult(
            source,
            "document",
            "",
            source.name,
            {"status": "internal_parse_error", "exc": type(exc).__name__},
        )


def _read_supported_file_body(
    path: str | Path,
    *,
    max_chars: int = 120000,
    scan_max_pages: int | None = None,
) -> FileReadResult:
    """读取一个受支持的文件；对内容问题一律诚实降级（模块不变量①）。

    ``scan_max_pages`` 只对 PDF 生效（缺省 ``PDF_SCAN_MAX_PAGES``）：到顶会在正文里
    明写「共 N 页只读了前 M 页」，绝不把没读当成没有（不变量③）。装配点将来接
    配置键时把值传进来即可，本函数缺省行为即现状。
    """
    source = Path(path).expanduser()
    if not source.is_file():
        return FileReadResult(source, "missing", "")
    ext = source.suffix.lower()
    if ext in _TEXT_EXTS:
        return FileReadResult(
            source,
            "code" if ext in _CODE_EXTS else "text",
            _text(source, max_chars),
            source.name,
        )
    if ext == ".docx":
        try:
            from docx import Document
            from docx.opc.exceptions import OpcError
        except ImportError:
            return _degrade(
                source, "document", "未安装 python-docx", status="parser_unavailable"
            )
        try:
            text = "\n".join(p.text for p in Document(str(source)).paragraphs)
            return FileReadResult(source, "document", text[:max_chars], source.name)
        # ``KeyError`` 这一枚最容易漏：合法 zip 但缺 ``[Content_Types].xml``（把任意
        # zip 改名成 .docx 就是这个形态）从 zipfile 索引里抛 KeyError，而 KeyError
        # 既不是 OSError 也不是 ValueError——旧捕获元组拦不住它。
        except (OSError, ValueError, TypeError, KeyError, BadZipFile, OpcError):
            return _degrade(
                source, "document", "损坏或不是有效的 Word 文档", status="parse_failed"
            )
    if ext == ".pdf":
        return _read_pdf(source, max_chars, scan_max_pages)
    if ext == ".xls":
        # V2.1 风险 8（2026-09-17）：旧版 OLE2 二进制不是 OOXML。本链路无
        # .xls 适配器（xlrd 未引入），塞给 openpyxl 只会抛 InvalidFileException
        # /BadZipFile（不在捕获元组内）→ 读取链崩溃、/files/read 500。诚实
        # 降级并标注 parser_unavailable（对齐 .pdf 分支先例），绝不伪装解析。
        return FileReadResult(
            source,
            "spreadsheet",
            "",
            source.name,
            {"status": "parser_unavailable", "format": "legacy .xls (OLE2)"},
        )
    if ext == ".xlsx":
        try:
            import openpyxl
            from openpyxl.utils.exceptions import InvalidFileException
        except ImportError:
            return _degrade(
                source, "spreadsheet", "未安装 openpyxl", status="parser_unavailable"
            )
        try:
            book = openpyxl.load_workbook(source, read_only=True, data_only=True)
            rows = []
            for sheet in book.worksheets:
                rows.append(f"[工作表：{sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    rows.append(" | ".join("" if v is None else str(v) for v in row))
            return FileReadResult(
                source, "spreadsheet", "\n".join(rows)[:max_chars], source.name
            )
        # BadZipFile：损坏/被改名的伪 OOXML（OLE 魔数）也会走到这里，一并
        # 诚实降级，不再让包级异常逃出读取链（V2.1 风险 8 同族）。
        # KeyError：缺 ``[Content_Types].xml`` 的裸 zip（同 .docx 那一枚漏口）。
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            InvalidFileException,
            BadZipFile,
        ):
            return _degrade(
                source, "spreadsheet", "损坏或不是有效的 Excel 表格", status="parse_failed"
            )
    if ext == ".ppt":
        # V2.1 风险 8：同 .xls——python-pptx 对 OLE2 抛 PackageNotFoundError
        # 不在捕获元组内；旧格式无适配器，诚实降级不伪装。
        return FileReadResult(
            source,
            "presentation",
            "",
            source.name,
            {"status": "parser_unavailable", "format": "legacy .ppt (OLE2)"},
        )
    if ext == ".pptx":
        try:
            from pptx import Presentation
            from pptx.exc import PackageNotFoundError
        except ImportError:
            return _degrade(
                source, "presentation", "未安装 python-pptx", status="parser_unavailable"
            )
        try:
            lines = []
            for index, slide in enumerate(Presentation(str(source)).slides, 1):
                lines.append(f"[幻灯片 {index}]")
                lines.extend(
                    shape.text for shape in slide.shapes if hasattr(shape, "text")
                )
            return FileReadResult(
                source, "presentation", "\n".join(lines)[:max_chars], source.name
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            PackageNotFoundError,
            BadZipFile,
        ):
            return _degrade(
                source, "presentation", "损坏或不是有效的 PPT 演示文稿", status="parse_failed"
            )
    return FileReadResult(source, "unknown", "")


def _page_has_image(page: Any) -> bool:
    """页 /Resources/XObject 里是否挂有 /Image（扫描件判据，不依赖 PIL 解码）。

    只查字典形态，不解码像素；资源树畸形一律按「没有图」保守回答——
    误判成 scanned 和误判成 blank 都是谎报，宁可让页级错误计数去说话。
    """
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            return False
        for key in xobjects.get_object():
            try:
                if xobjects.get_object()[key].get_object().get("/Subtype") == "/Image":
                    return True
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    return False


def _read_pdf(
    source: Path, max_chars: int, scan_max_pages: int | None
) -> FileReadResult:
    """PDF 诚实扫描链（S-T-PDF-3，模块不变量③的全部执法点）。

    与旧三行链的差别逐条对应「把没读写成没有」的谎报形态：
    ①口令保护不再被 ``FileNotDecryptedError`` 吞成「损坏」（它 ⊂ PyPdfError，旧捕获
      元组拦得住异常、拦不住归因）；②页数到顶显式说明；③字符到顶显式说明；
    ④单页抛错不再拖垮整档（页级计数 + 明写）；⑤空文本四态经
      ``metadata["pdf_scan"]["empty_reason"]`` 可区分；⑥中文解码质量低于
      ``DECODE_ACCEPT_RATIO`` 时警告行进正文（乱码是「没解码」不是「不存在」）。
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        return _degrade(source, "pdf", "未安装 pypdf", status="parser_unavailable")
    # ``PyPdfError`` 是 pypdf 全部解析异常的基类（PdfReadError / PdfStreamError /
    # FileNotDecryptedError 都在其下，无更窄公共祖先）。装 pypdf 前是死键、装完
    # 立刻是活洞：坏 PDF 从这里抛出会撞穿入站链路（S-PDF-1 不变量①）。
    try:
        reader = PdfReader(str(source))
    except (OSError, ValueError, TypeError, PyPdfError):
        return _degrade(source, "pdf", "损坏或不是有效的 PDF", status="parse_failed")
    try:
        if reader.is_encrypted:
            # 空口令能解开＝导出工具只设了权限口令，这类文件照读；解不开才是
            # 真「口令保护」。decrypt 对不支持的加密族可能抛异常，同按读不出处理。
            try:
                unlocked = bool(reader.decrypt(""))
            except (PyPdfError, NotImplementedError, ValueError):
                unlocked = False
            if not unlocked:
                return _degrade(
                    source, "pdf", "口令保护 PDF", status="password_protected"
                )
        pages_total = len(reader.pages)
    except (OSError, ValueError, TypeError, PyPdfError):
        return _degrade(source, "pdf", "损坏或不是有效的 PDF", status="parse_failed")

    cap = scan_max_pages if (scan_max_pages and scan_max_pages > 0) else PDF_SCAN_MAX_PAGES
    pages_read = min(pages_total, cap)
    texts: list[str] = []
    pages_failed = 0
    image_pages = 0
    for index in range(pages_read):
        try:
            page = reader.pages[index]
            text = page.extract_text() or ""
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            PyPdfError,
        ):
            pages_failed += 1
            texts.append("")
            continue
        texts.append(text)
        if _page_has_image(page):
            image_pages += 1

    scan: dict[str, Any] = {
        "pages_total": pages_total,
        "pages_read": pages_read,
        "pages_failed": pages_failed,
        "image_pages": image_pages,
    }
    body = "\n".join(texts)
    notes: list[str] = []

    ratio = cjk_decode_ratio(body)
    if ratio is not None:
        scan["decode_ratio"] = round(ratio, 4)
        if ratio < DECODE_ACCEPT_RATIO:
            notes.append(
                f"[中文解码质量警告：本文档文字层里已解码中文字形占 {ratio:.0%}"
                f"（达标线 {DECODE_ACCEPT_RATIO:.0%}），其余疑似乱码——通常是 PDF 缺"
                f" ToUnicode 映射表。乱码是「没解码出来」，不是「原文里没有字」。]"
            )
    if pages_failed:
        notes.append(
            f"[有 {pages_failed} 页因页对象内部错误没有读到（没读≠没有内容）。]"
        )
    if pages_total > pages_read:
        notes.append(
            f"[本 PDF 共 {pages_total} 页，本次按扫描上限只读了前 {pages_read} 页"
            f"（scan_max_pages={cap}）。后面 {pages_total - pages_read} 页没有读，"
            f"没读不等于没有内容——需要请点名页码范围。]"
        )
    if not body.strip():
        if pages_total == 0:
            scan["empty_reason"] = "no_pages"
        elif pages_failed >= pages_read:
            scan["empty_reason"] = "page_errors"
        elif image_pages > 0:
            scan["empty_reason"] = "scanned_no_text"
        else:
            scan["empty_reason"] = "blank_pages"
    elif len(body) > max_chars:
        dropped = len(body) - max_chars
        body = body[:max_chars]
        notes.append(
            f"[已达 {max_chars} 字符读取上限，另有 {dropped} 字未读；"
            f"未读不等于没有内容。]"
        )
    text = body
    if notes:
        text = (body + "\n" if body else "") + "\n".join(notes)
    return FileReadResult(source, "pdf", text, source.name, {"pdf_scan": scan})


def artifact_request(user_text: str) -> tuple[str, str] | None:
    text = (user_text or "").lower()
    if not re.search(
        r"生成|写入|保存|导出|创建|制作|generate|write|save|export|create", text
    ):
        return None
    languages = {
        "python": "py",
        "c++": "cpp",
        "c#": "cs",
        "java": "java",
        "javascript": "js",
        "typescript": "ts",
        "powershell": "ps1",
        "bash": "sh",
    }
    if re.search(r"代码|脚本|code|script", text) or any(k in text for k in languages):
        ext = next(
            (
                v
                for k, v in sorted(languages.items(), key=lambda kv: -len(kv[0]))
                if k in text
            ),
            "txt",
        )
        return "code", ext
    if re.search(r"文件|文档|txt|文本|document|file|提示词|人设", text):
        ext = "txt" if "txt" in text or "文本" in text else "md"
        if re.search(r"\b(docx|xlsx|pptx|pdf)\b|word|excel|powerpoint", text):
            return "unsupported", "txt"
        return "document", ext
    return None


def build_generated_file(
    user_text: str, reply_text: str, output_dir: str | Path
) -> GeneratedFile | None:
    """Consume raw model output, not presentation text. Write once with unique names."""
    intent = artifact_request(user_text)
    if intent is None:
        return None
    kind, ext = intent
    if kind == "unsupported":
        raise ValueError(
            "此入口目前支持 TXT、Markdown 和代码文件；不能把纯文本冒充 Office/PDF。"
        )
    blocks = list(
        re.finditer(
            r"```([A-Za-z0-9+#-]*)[^\S\n]*\n(.*?)```", reply_text or "", re.DOTALL
        )
    )
    if kind == "code":
        if not blocks:
            # Bare Python is accepted only if syntactically complete; never strip quotes.
            if ext != "py":
                raise ValueError("模型没有提供完整代码块，本次没有生成文件。")
            content = reply_text
        elif len(blocks) != 1:
            raise ValueError("模型返回多个代码块，请要求生成单个完整文件。")
        else:
            content = blocks[0][2]
            if ext == "txt":
                ext = {
                    "python": "py",
                    "cpp": "cpp",
                    "c++": "cpp",
                    "c#": "cs",
                    "javascript": "js",
                    "java": "java",
                }.get(blocks[0][1].lower(), "txt")
        if ext == "py":
            try:
                ast.parse(content)
            except SyntaxError as exc:
                raise ValueError(
                    "模型代码未通过 Python 语法检查，本次没有生成文件。"
                ) from exc
    else:
        content = blocks[0][2] if len(blocks) == 1 else reply_text
    if not content.strip():
        raise ValueError("模型返回空文件内容。")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("生成内容超过 2 MiB 文件限制。")
    # W3 收编（需求 16(2)，2026-09-26 S-FILES-LAND）：旧写法是 ``directory.mkdir`` +
    # ``path.open("x")`` **直写**调用方给的 output_dir——不过白名单 containment、
    # 不吃禁触名册、不看字节指纹，扩展名还直接取自模型输出的语言标签。现在字节
    # 交唯一咽喉 ``restricted_runner`` 验收发布：文件名词形不变（generated_…），
    # 单文件 2MiB 旧上限保持；``allowed_extensions={"*"}`` 只是把「语言标签五花八门」
    # 这一现实交给运行器判——可执行/脚本形态（.js/.ps1/.bat 一族 24 枚）在运行器里
    # 排在扩展名白名单**之前**先拦，放宽这一步救不回它们（那正是教义：落盘口不是
    # 投递口，这类产物今天起诚实不出件，chat 侧走既有 ValueError「静默跳附件」分支，
    # 文本回复不缩水）。缺省**不带** external_verdict——正向注册名册缺省不接是运行器
    # docstring 写死的口径（注册根外的合法暂存会被它整片拦死），禁触那一族由运行器
    # 缺省直判兜底。配额这本账今日在聊天附件腿没有定义，刻意不新烧（-1＝不记）。
    name = f"generated_{kind}_{uuid.uuid4().hex[:12]}.{ext}"
    payload = (content.rstrip("\r\n") + "\n").encode("utf-8")
    artifact_policy = policy_for_roots(
        [output_dir],
        allowed_extensions=frozenset({"*"}),
        limits=WriteLimits(
            max_file_bytes=2 * 1024 * 1024,
            daily_create_limit=-1,
            daily_replace_limit=-1,
        ),
    )
    outcome = create_bytes(name, payload, policy=artifact_policy)
    if outcome.denied or outcome.path is None:
        raise ValueError(
            "生成文件未通过落盘口验收，本次没有附件："
            f"{outcome.reason_code or 'io_error'}｜{plain_reason(outcome.reason_code)}"
        )
    return GeneratedFile(outcome.path, kind)
