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
import importlib.util
import logging
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from plugins.bot_unified_runtime.domains.core.safety_exec import trust
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
    # 归档类容器（docx/xlsx/pptx）解压前体检没过＝我方限额挡下的形态。既不是文件
    # 损坏（它可能完好），也不是环境缺件；说成"损坏"是把责任记到她身上（S-FILESAFE，
    # 需求 17 / AS-RESOURCE-ARCHIVE-BOMB）。
    "archive_expansion_limited": "文件解压后的体量超出安全上限，未解析（防解压炸弹）",
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
        "OCR 兜底今天不生效：本链路默认没把 OCR/VLM 腿接上（本机实缺哪样组件、"
        "装配点接没接，看这一行末尾的 ocr通路 代号——那是现算的，不在这里写死），"
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

# ---------------------------------------------------------------------------
# 容器魔数嗅探 · 本机能力现算 · 扫描件 OCR 装配点（S35，2026-10-08）
#
# 为什么要有这一节：旧 OLE2 那两条腿从前**只看后缀**就把归因说了出去（写死
# ``legacy .xls (OLE2)``）——把 ``.xlsx`` 改名成 ``.xls`` 的件会被说成「旧格式没适配器」，
# 而它按 OOXML 腿本可整篇读出；反过来真·OLE2 也只留下一句「无可用解析器」，说不清
# 「本机到底缺什么」。本节的四条规矩：
# ①**魔数说话**——后缀只决定先试哪条腿，内容决定最终归因（不猜）；
# ②「本机有没有通路」一律**现算**（HKCR COM 注册项 / PATH / 已装模块），绝不把探测
#   结论写死进措辞（规则 10——这类句子每改一次环境就过期一次）；
# ③探测结果只以**代号**进「技术事实（可核对）」行——那行有锁不许出现反斜杠与绝对
#   路径（``test_pdf_scan_honesty``），所以本口对外只吐名字，不吐路径；
# ④任一探测手段自己坏掉（PATH 含非法条目、``winreg`` 不可用、模块查规格抛错）一律
#   吞成「没探到」，绝不打断读取链（模块不变量①）。
#
# 零装包、零外发、零副作用：本节不 pip、不开 socket、不写盘、不启动 Office。
# ``pdftotext`` 那条腿只在「本机 PATH 里真有它」时才 spawn（argv 直传、无 shell、
# 超时、输出上限、钉死 encoding——台账 #47 的「subprocess.run 未钉 encoding 必崩」）。
# ---------------------------------------------------------------------------

_OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
_OOXML_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"

#: 文字层二次解码可用的外部工具（poppler；缺件机器上这枚恒为空 ⇒ 腿自动不接管）。
TEXT_LAYER_TOOL = "pdftotext"
#: 外部工具的等待上限（秒）与输出字符上限（超限当截断处理）。
TEXT_TOOL_TIMEOUT_SECONDS = 20
TEXT_TOOL_MAX_CHARS = 200000
#: 旧格式/扫描件的本机通路探测清单（只读探测，全代码名，不含路径）。
OFFICE_COM_APPIDS = ("Word.Application", "Excel.Application", "PowerPoint.Application")
OFFICE_CONVERTER_TOOLS = ("soffice", "libreoffice")
LEGACY_BINARY_TABLE_MODULES = ("xlrd", "olefile")
OCR_ENGINE_MODULES = ("pytesseract", "rapidocr_onnxruntime", "paddleocr", "easyocr")
PAGE_RASTERIZER_TOOLS = ("gswin64c", "gswin32c", "pdftoppm", "mutool")

#: 扫描件交给装配点前最多取几张内嵌图、翻几页、单图字节上限（防病态图把内存吃掉）。
OCR_MAX_IMAGES = 4
OCR_MAX_PAGES = 3
OCR_MAX_IMAGE_BYTES = 4 * 1024 * 1024

#: 后缀 → 「按内容改走哪条现代腿」与旧格式人话短语。
_LEGACY_OFFICE_EXTS: dict[str, tuple[str, str, str]] = {
    ".xls": ("spreadsheet", ".xlsx", "旧版 Excel 二进制"),
    ".ppt": ("presentation", ".pptx", "旧版 PowerPoint 二进制"),
    ".doc": ("document", ".docx", "旧版 Word 二进制"),
}


def sniff_container(source: Path) -> str:
    """只读文件头 8 字节判容器：``ole2`` / ``ooxml`` / ``pdf`` / ``unrecognized``。

    打不开返回 ``unreadable``（**不**在这里归因成「文件损坏」，交调用方按既有态说话）。
    """
    try:
        with source.open("rb") as stream:
            head = stream.read(8)
    except OSError:
        return "unreadable"
    if head.startswith(_OLE2_MAGIC):
        return "ole2"
    if head.startswith(_OOXML_MAGIC):
        return "ooxml"
    if head.startswith(_PDF_MAGIC):
        return "pdf"
    return "unrecognized"


def _tools_present(names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for name in names:
        try:
            if shutil.which(name):
                found.append(name)
        except (OSError, ValueError):
            continue
    return found


def _modules_present(names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for name in names:
        try:
            if importlib.util.find_spec(name) is not None:
                found.append(name)
        except (ImportError, ValueError, OSError):
            continue
    return found


def _com_apps_present(names: tuple[str, ...]) -> list[str]:
    """HKCR 只读探测本机到底注册了哪些 Office COM 组件（没装就是查不到）。"""
    try:
        import winreg
    except ImportError:
        return []
    found: list[str] = []
    for name in names:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name):
                found.append(name)
        except OSError:
            continue
    return found


def local_capability_report() -> dict[str, Any]:
    """现算「旧格式 / 扫描件」在本机到底有没有通路（全只读、零装包、零外发）。

    键全是**代码名**（``Word.Application`` 这种），值里没有路径。
    """
    report: dict[str, Any] = {
        "office_com_apps": _com_apps_present(OFFICE_COM_APPIDS),
        "office_converter_tools": _tools_present(OFFICE_CONVERTER_TOOLS),
        "legacy_table_modules": _modules_present(LEGACY_BINARY_TABLE_MODULES),
        "ocr_engines": _modules_present(OCR_ENGINE_MODULES),
        "page_rasterizers": _tools_present(PAGE_RASTERIZER_TOOLS),
        "text_layer_tools": _tools_present((TEXT_LAYER_TOOL,)),
    }
    report["legacy_office_path"] = bool(
        report["office_com_apps"] or report["office_converter_tools"]
    )
    # 扫描件要有「引擎」还要有「把页变成图的东西」，缺一样都读不出字。
    report["scan_ocr_path"] = bool(
        report["ocr_engines"] and report["page_rasterizers"]
    )
    return report


def _named_pair(items: list[str], label: str) -> str:
    return f"{label}({'/'.join(items) if items else '无'})"


def legacy_office_capability_code() -> str:
    """旧 OLE2 件「本机为什么读不了」的一行代号（无路径、无冒号）。"""
    report = local_capability_report()
    parts = [
        _named_pair([str(app).split(".")[0] for app in report["office_com_apps"]], "OfficeCOM"),
        _named_pair(list(report["office_converter_tools"]), "LibreOffice"),
        _named_pair(list(report["legacy_table_modules"]), "旧表读取器"),
    ]
    if report["legacy_office_path"]:
        return "本机有转换通路但未接线（接线要授权）· " + "、".join(parts)
    return "本机无转换通路 · " + "、".join(parts)


def scan_ocr_capability_code() -> str:
    """扫描件 OCR 这条腿的状态代号：缺什么组件、装配点接没接（装配点=本文件唯一钩子）。"""
    report = local_capability_report()
    parts = [
        _named_pair(list(report["ocr_engines"]), "OCR引擎"),
        _named_pair(list(report["page_rasterizers"]), "页面栅格器"),
        "装配点(" + ("已接线" if _SCAN_OCR_HANDLER is not None else "空") + ")",
    ]
    return "、".join(parts)


#: 扫描件 OCR 兜底的**装配点**（S35 治的正是「无装配点」这一格，不是「无组件」那一格）。
#: 形态：收**页内嵌位图字节列表**（按页序）、回 OCR 文本；空串＝没读到。
#: 缺省 ``None`` ⇒ 本腿不接管，交既有诚实四态说「读不了」。装配方（根入站或中央
#: ``files.read.*`` handler）在本机确有 OCR/VLM 组件时把可调用体注进来；本文件因此
#: **不** import OCR 包、**不**碰网络，VLM 开关与配额的真身仍归
#: ``domains/media/ingest/vision_describe.py``（禁第二真身）。
_SCAN_OCR_HANDLER: Callable[[list[bytes]], str] | None = None


def set_scan_ocr_handler(handler: Callable[[list[bytes]], str] | None) -> None:
    """装配/卸下扫描件 OCR 钩子（传 ``None`` 即回到今天的缺省行为）。"""
    global _SCAN_OCR_HANDLER
    _SCAN_OCR_HANDLER = handler


def scan_ocr_handler() -> Callable[[list[bytes]], str] | None:
    return _SCAN_OCR_HANDLER


def _scan_page_image_blobs(reader: Any, pages_read: int) -> tuple[list[bytes], int]:
    """从图像型页里取**内嵌位图原始字节**（pypdf 的 ``page.images``，本机已装）。

    这是「把页变成图」那半步的本地通路——不需要栅格器就能拿到扫描件里那张整页图。
    限额：最多翻 ``OCR_MAX_PAGES`` 页、最多取 ``OCR_MAX_IMAGES`` 张、单张超
    ``OCR_MAX_IMAGE_BYTES`` 丢弃。取不到就交空列表（装配点自己按「没读到」处理）。
    """
    blobs: list[bytes] = []
    pages_tried = 0
    for index in range(min(pages_read, OCR_MAX_PAGES)):
        pages_tried += 1
        try:
            images = reader.pages[index].images
        except (
            AttributeError,
            IndexError,
            KeyError,
            NotImplementedError,
            OSError,
            TypeError,
            ValueError,
        ):
            continue
        for image in images:
            if len(blobs) >= OCR_MAX_IMAGES:
                return blobs, pages_tried
            try:
                data = bytes(image.data)
            except (
                AttributeError,
                NotImplementedError,
                OSError,
                TypeError,
                ValueError,
            ):
                continue
            if 0 < len(data) <= OCR_MAX_IMAGE_BYTES:
                blobs.append(data)
    return blobs, pages_tried


def locate_text_layer_tool() -> str:
    """本机 poppler 命令行件的可执行体路径；缺件机器返回空串（腿自动不接管）。"""
    try:
        return shutil.which(TEXT_LAYER_TOOL) or ""
    except (OSError, ValueError):
        return ""


def second_pass_pdf_text(source: Path, max_chars: int) -> str:
    """用本机 ``pdftotext`` 把文字层再解一遍（离线、只读这个文件、不写盘）。

    只在「第一遍解出乱码」时被调用。失败/缺件/超时/非零退出一律回空串——**空串
    不等于这页没字**，交调用方继续按既有诚实态说话（不变量③）。
    """
    tool = locate_text_layer_tool()
    if not tool:
        return ""
    budget = min(max(0, int(max_chars)), TEXT_TOOL_MAX_CHARS)
    if not budget:
        return ""
    try:
        completed = subprocess.run(  # 无 shell、argv 常量表、路径来自已判定文件、超时+输出上限
            [tool, "-q", "-enc", "UTF-8", str(source), "-"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEXT_TOOL_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if int(getattr(completed, "returncode", 1)) != 0:
        return ""
    text = str(getattr(completed, "stdout", "") or "")
    return text[:budget]


# ---------------------------------------------------------------------------
# 归档类（OOXML＝zip）解压前体检（需求 17 / AS-RESOURCE-ARCHIVE-BOMB，S-FILESAFE）
#
# 为什么必须先体检再交给解析器：``.docx/.xlsx/.pptx`` 都是 zip 容器，python-docx /
# openpyxl / python-pptx 会**自行**把成员解出来。旧链只有 ``max_chars`` 这道出口闸，
# 而字符是在解完之后才截的——几十 KB 的容器声明解出几 GB，字节先进内存，截断那条
# 永远轮不到说话（登记名册 AS-RESOURCE-ARCHIVE-BOMB 的失效形态）。本节的判据只看
# zip **中央目录**的申报值（不解压、成本与文件大小无关），超限当场点名降级。
# 申报值会说谎，所以另加一条「真读一段」的实体展开门：OOXML 的成员里出现内部
# DTD 实体声明（``<!ENTITY``）就不是合法 Office 文档（合法件里零出现），而
# billion-laughs 的定义正躲在文档开头——读每枚 XML 成员的开头一小段即可拦住，
# 读的是**截断后的真实字节**，不是申报值。
# 限额走本文件常量真身，不散抄进各分支；``character/documents.py`` 那条独立腿
# （F-D，S-FIX-PERSONA-R2）数值口径不同、各有其主，此处不复述也不去改它。
# ---------------------------------------------------------------------------

#: 单容器成员数上限（合法 Office 文档实测数十到数百枚；2000 已远超日常形态）。
ARCHIVE_MAX_MEMBER_COUNT = 2000
#: 单个成员**申报**的解压后字节上限。
ARCHIVE_MAX_MEMBER_BYTES = 32 * 1024 * 1024
#: 全容器**申报**的解压后字节合计上限。
ARCHIVE_MAX_TOTAL_BYTES = 64 * 1024 * 1024
#: 实体展开门：每枚 XML 成员只真读开头这么多字节（解出来的真实字节，非申报值）。
ARCHIVE_XML_HEAD_BYTES = 64 * 1024
#: 实体展开门最多真读多少成员（防病态容器把门本身跑成 IO 炸弹）。
ARCHIVE_MAX_SCANNED_MEMBERS = 64

_INTERNAL_ENTITY_MARKER = b"<!entity"


def archive_expansion_violation(source: Path) -> str:
    """归档类解析前的体检。返回 ``""``＝放行；否则点名超限代号。

    代号（进 ``metadata["format"]`` 短语，**不含冒号与路径**）：
    ``member_count`` / ``member_bytes`` / ``total_bytes`` / ``internal_entity``。
    容器根本打不开（非 zip / 中央目录损坏）**不在这里归因**——返回 ``""`` 交各分支
    既有捕获说「损坏或不是有效的 …」，本口不抢那句（S-PDF-1 的归因纪律）。
    """
    try:
        with ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > ARCHIVE_MAX_MEMBER_COUNT:
                return "member_count"
            total = 0
            for info in infos:
                declared = int(getattr(info, "file_size", 0) or 0)
                if declared > ARCHIVE_MAX_MEMBER_BYTES:
                    return "member_bytes"
                total += declared
                if total > ARCHIVE_MAX_TOTAL_BYTES:
                    return "total_bytes"
            scanned = 0
            for info in infos:
                if not str(info.filename).lower().endswith(".xml"):
                    continue
                scanned += 1
                if scanned > ARCHIVE_MAX_SCANNED_MEMBERS:
                    break
                try:
                    # 真读一小段：申报值会说谎，这里吃的是解压出来的实际字节。
                    with archive.open(info) as stream:
                        head = stream.read(ARCHIVE_XML_HEAD_BYTES)
                except (BadZipFile, OSError, ValueError):
                    # 单成员解不开＝坏容器，交各分支既有捕获归因，本口不猜。
                    continue
                if _INTERNAL_ENTITY_MARKER in head.lower():
                    return "internal_entity"
    except (BadZipFile, OSError, ValueError):
        return ""
    return ""


#: 违规代号 → 归类短语（``_degrade`` 的 ``label`` 位，只说形态、不带路径与冒号）。
ARCHIVE_VIOLATION_LABELS: dict[str, str] = {
    "member_count": f"容器成员数超上限（{ARCHIVE_MAX_MEMBER_COUNT} 枚）",
    "member_bytes": f"单成员解压后尺寸超上限（{ARCHIVE_MAX_MEMBER_BYTES} 字节）",
    "total_bytes": f"解压后合计尺寸超上限（{ARCHIVE_MAX_TOTAL_BYTES} 字节）",
    "internal_entity": "XML 成员含内部 DTD 实体声明（实体展开攻击形态）",
}


def _archive_guard(source: Path, kind: str) -> FileReadResult | None:
    """三条 OOXML 腿共用的体检闸；放行返回 ``None``，超限返回降级结果。"""
    violation = archive_expansion_violation(source)
    if not violation:
        return None
    label = ARCHIVE_VIOLATION_LABELS.get(violation, "解压前体检未放行")
    return FileReadResult(
        source,
        kind,
        "",
        source.name,
        {"status": "archive_expansion_limited", "format": label, "code": violation},
    )

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

    覆盖四族（S-T-PDF-3 扩两族；S-FILES-LAND 补第三格；S-FILESAFE 补归档体检态）：
    ① ``PARSE_STATUS_SENTENCES`` 那张表里的各枚诚实降级态（含归档体检那一枚）；
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
        ocr_path = str(scan.get("ocr_path") or "")
        return (
            f"[文件无文字：{name}] 这个文件我读到了，但没有可提取的文字：{sentence}。"
            f"技术事实（可核对）：文件名={name}，empty_reason={reason}，"
            f"页数=读了{scan.get('pages_read', 0)}/共{scan.get('pages_total', 0)}，"
            f"含图页={scan.get('image_pages', 0)}"
            + (f"，ocr通路={ocr_path}" if ocr_path else "")
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


def _text_prefix_bytes(max_chars: int) -> int:
    """文本腿最多**从盘上取**多少字节（UTF-8 单字最宽 4 字节，故 4×字符预算）。"""
    return max(0, int(max_chars)) * 4


def _text(path: Path, max_chars: int) -> str:
    """流式取**前缀**解码，绝不整档进内存（需求 17 / AS-RESOURCE-UNBOUNDED，S-FILESAFE）。

    旧写法是 ``path.read_bytes()[: max_chars * 4]``——先把整份文件读进内存再切前缀，
    一个 5GB 的 ``.txt``/``.log`` 就能把 bot 进程顶到 OOM（本仓 2026-09-26 已有两次
    OOM 前例，台账见 HANDBOOK）。现在只 ``read(budget)``：读到的字节数与文件大小无关。
    NUL 探测仍只看前 4096 字节（二进制判定口径不变）。
    """
    budget = _text_prefix_bytes(max_chars)
    try:
        with path.open("rb") as stream:
            raw = stream.read(budget) if budget else b""
    except OSError:
        return ""
    if b"\x00" in raw[:4096]:
        return ""
    return raw.decode("utf-8", errors="replace")[:max_chars]


def _text_truncation_note(path: Path, max_chars: int) -> str:
    """文本腿「只读了前一段」的显式说明（不变量③：没读不许写成没有）。

    只在盘上字节确实多于预算时开口；判据用 ``stat().st_size``，不再读第二遍。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    budget = _text_prefix_bytes(max_chars)
    if not budget or size <= budget:
        return ""
    return (
        f"[本次只读取了文件开头约 {max_chars} 字符（盘上共 {size} 字节，"
        f"读取预算 {budget} 字节）。后面的内容没有读，没读不等于没有内容。]"
    )


def _degrade(source: Path, kind: str, label: str, *, status: str) -> FileReadResult:
    """诚实降级的统一出口。

    ``label`` 只准是归类短语（「损坏或不是有效的 PDF」这类），**不得**放解析器抛出的
    原文——那些字符串里带绝对路径，会随 ``CapabilityResult`` 与诊断卡出站。
    """
    return FileReadResult(
        source, kind, "", source.name, {"status": status, "format": label}
    )


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 文件正文进上下文的**唯一打标咽喉**（需求 17 漏口①，S-SEC-NARROW 2026-09-28）
#
# 为什么这一对在 file_reader、而不是让每个消费方各自去 import trust：
# ①``read_supported_file`` 的公开面是「文件正文」这个**产物**，产物离开解析出口时
#   应当已经带上「谁说的」这一句结构化事实——这正是登记件 ``trust`` 教义的落点
#   （正文恒 T2，超管亲手上传也不升档）；
# ②消费方散在根 ``__init__.py``（禁写）、``runtime/capability_protocols.py``（禁写）、
#   控制面（禁写）与邮件腿（本席可写）。真身放在出口，等 hub 落下补丁时那几腿
#   **只是换一行调用**，不需要各自重写判据；本席先把邮件腿这条能接的接上；
# ③判据零副本：本文件不 import re、不自己拼前导行、不自己定档——定档与检测全在
#   ``trust.label_file_body`` 背后（它再下游调 ``check_prompt_injection``）。
# 空正文（读不出、降级、只读到 0 字）**不打标**：那种形态要说的是「我没读到」，
# 措辞唯一真身是 ``file_read_failure_note``；给一句不存在的外部资料加来源行，
# 等于把「没读」写成「读到了」，违反不变量③。
# ---------------------------------------------------------------------------


def labelled_text(
    result: FileReadResult,
    *,
    display_name: str = "",
    request_id: str = "",
    origin: trust.ContentOrigin | str = trust.ContentOrigin.FILE_BODY,
) -> str:
    """已读出的 ``FileReadResult`` → 带 T2 来源前导行的上下文文本。

    ``display_name`` 是**给人看的那个名字**（邮件附件名、用户上传名）：解析出口拿到
    的往往是临时件名，调用方手上有真名就该传进来，否则来源行会写成临时文件名——
    那不是谎报，但是句没人能对得上的废话。
    ``origin`` 让调用方**申报来源种类**（文件正文／邮件附件同族都写 ``file_body``；
    申报不出的一律由 ``trust`` 收敛成 UNKNOWN ⇒ T3，fail-closed，不默认升级）。
    空正文返回空串（调用方据此走降级措辞）。
    """
    body = str(getattr(result, "text", "") or "")
    if not body.strip():
        return ""
    name = str(display_name or result.title or result.path.name or "")
    if origin == trust.ContentOrigin.FILE_BODY:
        # 文件正文这一族走它自己的命名口（也是邮件腿那枚注毒锁钉的调用面）。
        return trust.label_file_body(name, body, request_id=request_id)
    return trust.label_ingress_content(
        body=body, origin=origin, source_name=name, request_id=request_id
    )


def read_file_for_context(
    path: str | Path,
    *,
    display_name: str = "",
    request_id: str = "",
    max_chars: int = 120000,
    scan_max_pages: int | None = None,
) -> str:
    """「读文件并把正文交进上下文」的一行式口：读 + 逐份 T2 打标，一次调用完成。

    读不出/没字 → 返回空串，**降级措辞仍由调用方走** ``file_read_failure_note``
    （两态措辞唯一真身，本口不复制、不并态）。根 ``__init__.py`` 附件腿与中央
    ``files.read.*`` handler 的替换形态就是这一枚函数（见席位报告 hub 补丁申请）。
    """
    result = read_supported_file(
        path, max_chars=max_chars, scan_max_pages=scan_max_pages
    )
    return labelled_text(result, display_name=display_name, request_id=request_id)


#: ``FileReadResult.kind`` 的人话标签（kind 字符串本文件自产，标签与它同住一处，
#: 不建第二账）。表外 kind 原样上注记——翻译不出就出示原文，不编类型名。
_FILE_KIND_LABELS: dict[str, str] = {
    "text": "文本",
    "code": "代码",
    "document": "文档",
    "pdf": "PDF 文档",
    "spreadsheet": "表格",
    "presentation": "演示文稿",
}

#: 上下文注记的缺省收录预算。注记进的是**对话上下文**（每轮都占窗），不是控制面
#: 全文读取口——缺省远小于 ``read_supported_file`` 的 120000；调用方要放宽显式传。
CONTEXT_NOTE_DEFAULT_MAX_CHARS = 1200


def build_incoming_file_context_note(
    path: str | Path,
    *,
    original_name: str = "",
    max_chars: int = CONTEXT_NOTE_DEFAULT_MAX_CHARS,
) -> str:
    """入站文件 → T2 打标的上下文注记（文件名/类型/可读性/限长正文）。

    文件链路波的供件：notice 腿把文件落盘到 ``incoming/`` 后，注入侧拿落盘路径
    调本口，把返回文本注进对话上下文——判据零副本：

    - 读取只走 ``read_supported_file``（不变量①：内容问题诚实降级、绝不抛）；
    - T2 打标只走 ``labelled_text`` 咽喉（文件正文恒 T2，超管上传也不升档）；
    - 读不动时的措辞只交 ``file_read_failure_note`` 唯一真身（S-PDF-2：不复制、
      不并态）——「没读」绝不写成「没有」（不变量③）。

    ``original_name`` 是**给人看的原始文件名**（落盘件名是 ``<时间戳>_原名`` 形态，
    不该出现在注记里）；不传则退回解析出口的件名。空正文但读取成功（空文件/
    非文字形态）由本口出一句可核对的事实，不猜内容。本函数整体 fail-honest：
    任何意外折成一句「没读到」的程序侧说明并记 WARNING，绝不打断入站链路。
    """
    try:
        result = read_supported_file(path, max_chars=max_chars)
        name = (
            str(original_name or "").strip()
            or str(result.title or "").strip()
            or Path(path).name
            or "未命名文件"
        )
        body = labelled_text(result, display_name=name)
        if not body.strip():
            failure = file_read_failure_note(result)
            if failure:
                # 措辞真身逐字交出（S-PDF-2：不复制、不并态、不替换其中的名字）；
                # ``file_read_failure_note`` 不收 display_name，落盘件名与用户可见名
                # 不一致时只在外面补一行头，让注记对得上人手里的文件。
                shown = str(result.title or result.path.name or "")
                if name and name != shown:
                    return f"[入站文件：{name}]\n{failure}"
                return failure
            return (
                f"[入站文件：{name}] 文件在，但没有读出任何文字内容"
                "（可能是空文件，或内容不是文字形态）。"
            )
        kind = str(result.kind or "")
        kind_label = _FILE_KIND_LABELS.get(kind) or kind or "未知类型"
        header = (
            f"[入站文件：{name}｜类型：{kind_label}｜"
            f"已读取正文（本注记最多收录约 {max(0, int(max_chars))} 字符）]"
        )
        return f"{header}\n{body}"
    except Exception as exc:  # noqa: BLE001 - 供件自身绝不让异常逃出入站链路
        try:
            shown_name = Path(path).name
        except (OSError, TypeError, ValueError):
            shown_name = "?"
        logger.warning(
            "incoming file context note failed: file=%s error=%s",
            shown_name,
            type(exc).__name__,
        )
        return (
            "这次没能生成入站文件的上下文注记（程序侧异常，不是文件损坏，"
            "内容没有读）。"
        )


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


def _read_legacy_office(
    source: Path,
    ext: str,
    *,
    max_chars: int,
    scan_max_pages: int | None,
) -> FileReadResult:
    """旧格式族（``.xls`` / ``.ppt`` / ``.doc``）——魔数说话，能读真读，读不了说清为什么。

    V2.1 风险 8 的归因纪律**一字未改**：真 OLE2 仍 ``parser_unavailable`` 诚实降级，
    绝不塞给 OOXML 解析器抛包级异常撞穿入站链路（那三条锁 ``test_v21_risk_red_tz_and_files``
    / ``test_v21_s10_protocols`` / ``test_file_reader_parse_safety`` 钉的就是这一格）。
    S35 新增的只有两样：

    ①**内容改道**——后缀写着旧格式、文件头却是 OOXML（zip）的件，从前一律被判
      「旧格式无适配器」＝把能读的判成读不了（与【知识库】空分区那类「没查到就说不存在」
      同型），现在按内容再走一次现代腿，真读出来；
    ②**本机现算的缺件代号**——「无可用解析器」这句口号后面，补上本机到底有没有
      Office COM / LibreOffice / 旧表读取器（全只读探测，无路径）。
    """
    kind, modern_ext, label = _LEGACY_OFFICE_EXTS[ext]
    magic = sniff_container(source)
    if magic == "ooxml":
        attempt = _read_supported_file_body(
            source,
            max_chars=max_chars,
            scan_max_pages=scan_max_pages,
            forced_ext=modern_ext,
        )
        if attempt.text.strip() or not (attempt.metadata or {}).get("status"):
            return attempt
        # 改道没读出来（本机实测：``openpyxl`` 会按**后缀**拒收 ``.xls``，而
        # python-docx / python-pptx 不看后缀，所以 ``.doc``/``.ppt`` 这类改名件能真读）。
        # 这一格的归因必须说「内容实为 OOXML、按现代腿读过、没读出来」，
        # 不许再沿用从前那句「旧格式（OLE2）无适配器」——那是把没读成写成没得读。
        metadata = dict(attempt.metadata or {})
        metadata["format"] = (
            f"后缀是 {ext} 而内容实为 OOXML 容器（按 {modern_ext} 腿改道读过、"
            f"没读出来）· 原归因={metadata.get('format') or '无'}"
        )
        return FileReadResult(source, attempt.kind, attempt.text, source.name, metadata)
    if magic == "ole2":
        return FileReadResult(
            source,
            kind,
            "",
            source.name,
            {
                "status": "parser_unavailable",
                "format": f"{label}（OLE2 复合文档）· {legacy_office_capability_code()}",
            },
        )
    # 既非 OLE2 也非 OOXML（含 0 字节件、文件打不开）：态与今天一致（不新增归因），
    # 但把「魔数不匹配、我不猜里面写了什么」写进去——把没查到说成不存在是谎报，
    # 把没认出的容器说成 OLE2 同样也是。
    return FileReadResult(
        source,
        kind,
        "",
        source.name,
        {
            "status": "parser_unavailable",
            "format": (
                f"后缀是 {ext} 而文件头既非 OLE2 也非 OOXML（容器代号={magic}"
                f"，不猜内容）· 本链路无该容器适配器"
                f" · {legacy_office_capability_code()}"
            ),
        },
    )


def _read_supported_file_body(
    path: str | Path,
    *,
    max_chars: int = 120000,
    scan_max_pages: int | None = None,
    forced_ext: str = "",
) -> FileReadResult:
    """读取一个受支持的文件；对内容问题一律诚实降级（模块不变量①）。

    ``scan_max_pages`` 只对 PDF 生效（缺省 ``PDF_SCAN_MAX_PAGES``）：到顶会在正文里
    明写「共 N 页只读了前 M 页」，绝不把没读当成没有（不变量③）。装配点将来接
    配置键时把值传进来即可，本函数缺省行为即现状。

    ``forced_ext`` 只由旧格式腿的**魔数改道**使用（S35）：后缀写着 ``.xls`` 而内容实为
    OOXML 容器时，按内容再走一次现代腿。递归深度恒为 1（改道的目标必是现代后缀分支），
    缺省空串＝按盘上后缀走（既有行为一字未变）。
    """
    source = Path(path).expanduser()
    if not source.is_file():
        return FileReadResult(source, "missing", "")
    ext = forced_ext or source.suffix.lower()
    if ext in _TEXT_EXTS:
        body = _text(source, max_chars)
        note = _text_truncation_note(source, max_chars)
        if not note:
            return FileReadResult(
                source,
                "code" if ext in _CODE_EXTS else "text",
                body,
                source.name,
            )
        # 截断如实说明（既有行为是静默切前缀）：正文加一行、metadata 另留可核对尺寸，
        # 控制面/卡片侧要判「读全了没」只看 metadata 就够。
        return FileReadResult(
            source,
            "code" if ext in _CODE_EXTS else "text",
            (body + "\n" + note) if body else note,
            source.name,
            {"text_truncated": True, "read_bytes_budget": _text_prefix_bytes(max_chars)},
        )
    if ext == ".docx":
        guarded = _archive_guard(source, "document")
        if guarded is not None:
            return guarded
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
        return _read_legacy_office(
            source, ext, max_chars=max_chars, scan_max_pages=scan_max_pages
        )
    if ext == ".xlsx":
        guarded = _archive_guard(source, "spreadsheet")
        if guarded is not None:
            return guarded
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
        return _read_legacy_office(
            source, ext, max_chars=max_chars, scan_max_pages=scan_max_pages
        )
    if ext == ".doc":
        # Word 97-2003 与 .xls/.ppt 同族（OLE2）。从前它落到最末的 ``unknown`` 分支，
        # 话是诚实的（「这个类型我没有读取通道」）但没说**为什么**、也没查过本机
        # 到底有没有通路；本席把它并进同一把尺（S35）。
        return _read_legacy_office(
            source, ext, max_chars=max_chars, scan_max_pages=scan_max_pages
        )
    if ext == ".pptx":
        guarded = _archive_guard(source, "presentation")
        if guarded is not None:
            return guarded
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
    first_pass_ratio = ratio
    scan["text_source"] = "pypdf"
    if ratio is not None and ratio < DECODE_ACCEPT_RATIO:
        # 乱码（多为缺 ToUnicode 的 CID 字体）时，本机若真有第二家文字层解码器，
        # 就换一家再解一遍（S35 真做腿：poppler ``pdftotext``，离线、只读这个件、
        # 不写盘、零装包）。采用判据仍是**同一把量化尺**，不是「哪家看起来更强」：
        # 只有第二遍到达标线才换，否则退回第一遍那份并如实说明换过、没换出结果。
        alt = second_pass_pdf_text(source, max_chars)
        alt_ratio = cjk_decode_ratio(alt)
        scan["second_pass_ratio"] = None if alt_ratio is None else round(alt_ratio, 4)
        if alt.strip() and alt_ratio is not None and alt_ratio >= DECODE_ACCEPT_RATIO:
            body = alt
            ratio = alt_ratio
            scan["text_source"] = TEXT_LAYER_TOOL
        elif alt.strip():
            notes.append(
                f"[换本机 {TEXT_LAYER_TOOL} 做第二遍文字层解码没有更好结果"
                f"（第二遍中文占比={alt_ratio}，第一遍={round(first_pass_ratio, 4) if first_pass_ratio is not None else None}），"
                f"仍按第一遍如实说明——两遍都是「没解码出来」，不是「原文里没有字」。]"
            )
    if ratio is not None:
        scan["decode_ratio"] = round(ratio, 4)
        if first_pass_ratio is not None and first_pass_ratio < DECODE_ACCEPT_RATIO:
            if scan["text_source"] == TEXT_LAYER_TOOL:
                notes.append(
                    f"[中文解码质量警告：第一遍解码已解出中文字形占"
                    f" {first_pass_ratio:.0%}（乱码疑似缺 ToUnicode），"
                    f"换本机 {TEXT_LAYER_TOOL} 第二遍后为 {ratio:.0%}"
                    f"（达标线 {DECODE_ACCEPT_RATIO:.0%}），本次采用后者。]"
                )
            else:
                notes.append(
                    f"[中文解码质量警告：本文档文字层里已解码中文字形占"
                    f" {first_pass_ratio:.0%}（达标线 {DECODE_ACCEPT_RATIO:.0%}），"
                    f"其余疑似乱码——通常是 PDF 缺 ToUnicode 映射表。"
                    f"乱码是「没解码出来」，不是「原文里没有字」。]"
                )
                if not locate_text_layer_tool():
                    notes.append(
                        f"[本机没有第二家文字层解码器（{TEXT_LAYER_TOOL} 不在 PATH），"
                        f"这条腿没有备用来源——「试不出」不等于「试不出来的东西不存在」。]"
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

    # 扫描件 OCR 兜底的**装配点**（S35 治的就是「无装配点」这一格，不是「无组件」）。
    # 缺省钩子为 ``None`` ⇒ 本腿不接管、上面的 empty_reason 保持 scanned_no_text，
    # 由 ``file_read_failure_note`` 把「读不了」说清（行为与接线前一字不差）。
    # 钩子接上后才动手，而且**取图与调钩子都在受保护区内**：外部 OCR/VLM 腿出任何
    # 错都不许打断入站（不变量①），也不许把「钩子没读出字」写成「图像里没有字」。
    if scan.get("empty_reason") == "scanned_no_text":
        scan["ocr_path"] = scan_ocr_capability_code()
        handler = scan_ocr_handler()
        if handler is not None:
            blobs, pages_tried = _scan_page_image_blobs(reader, pages_read)
            scan["ocr_pages_tried"] = pages_tried
            scan["ocr_images"] = len(blobs)
            ocr_text = ""
            if blobs:
                try:
                    ocr_text = str(handler(blobs) or "")
                except Exception as exc:  # noqa: BLE001 - 装配方的错不许撞穿入站链路
                    logger.warning(
                        "scan ocr handler raised: file=%s error=%s",
                        source.name,
                        type(exc).__name__,
                    )
                    scan["ocr_error"] = type(exc).__name__
            if ocr_text.strip():
                dropped = max(0, len(ocr_text) - max_chars)
                body = ocr_text.strip()[:max_chars]
                del scan["empty_reason"]
                scan["ocr"] = "handler_text"
                note = (
                    f"[扫描件经装配点 OCR 读出 {len(body)} 字"
                    f"（试了 {pages_tried} 页、取到 {len(blobs)} 张内嵌图）。"
                )
                note += (
                    f"另有 {dropped} 字未读，未读不等于没有内容。]"
                    if dropped
                    else "]"
                )
                notes.append(note)
            else:
                scan["ocr"] = "no_images_taken" if not blobs else "handler_no_text"
                notes.append(
                    f"[装配点已接线但没把字读回来（取到 {len(blobs)} 张内嵌图、"
                    f"试了 {pages_tried} 页，状态={scan['ocr']}）。"
                    f"没读回来不等于图像里没有字。]"
                )
    text = body
    if notes:
        text = (body + "\n" if body else "") + "\n".join(notes)
    return FileReadResult(source, "pdf", text, source.name, {"pdf_scan": scan})


#: 语言名 → 扩展名：全仓唯一一张表（名词候选与 ext 取值都读它，禁第二张）。
_ARTIFACT_LANGUAGES = {
    "python": "py",
    "c++": "cpp",
    "c#": "cs",
    "java": "java",
    "javascript": "js",
    "typescript": "ts",
    "powershell": "ps1",
    "bash": "sh",
}

#: 交付宣告＝自毒环：出附件时那句「我已经把内容整理成附件：<文件名>」字面自带
#: 「整理成 … 附件」（且文件名里还有 code/txt），谁引用它谁再被判成要文件。
#: 匹配前先剥**只这一形**（剥到句末或行末）。通用消毒口
#: `security/injection.guard_secondhand_text` 是「不可信包裹」不是判据预处理，
#: 口径不同 ⇒ 这里不复用它、也不起第二把尺。
_ARTIFACT_DELIVERY_DECLARATION = re.compile(r"我已经把内容整理成附件[^。\n]*")

#: 动词必须**管着**名词：同句、邻近（≤12 字，不许跨过句末标点）才算文件意图。
#: 旧形状＝「动词 anywhere ∩ 名词 anywhere」⇒ 实算反例「我保存了一份简历 txt」
#: 「文件还没保存，帮我看看」两枚陈述句都被判成"她要生成文件"（回复被劫持成附件）。
#: 「保存/写入」裸形不在册：只有「保存成/保存为/存成/存为」这类**产出为文件**的讲法
#: 才带生成语义；generate/write/save 译不成这套动词，故不再单列英文裸形。
_ARTIFACT_VERBS = "生成|导出|保存成|保存为|存成|存为|创建|制作|整理成|写成|发我|给我"
_ARTIFACT_GAP = r"[^。！？；\n]{0,12}?"
#: 拉丁短词挂 `(?<![a-z])`：「一个txt文档」仍命中（前一字非 a-z），
#: 而 copy / profile 一类不再误命中 py / file。
_ARTIFACT_LATIN_NOUNS = (
    "txt",
    "md",
    "markdown",
    "py",
    "java",
    "json",
    "csv",
    "docx",
    "xlsx",
    "pptx",
    "pdf",
    "code",
    "script",
    "file",
    "document",
)


def _artifact_nouns() -> str:
    """名词候选：固定词形 + 语言表键（长键在前，`javascript` 不被 `java` 截走）。"""
    parts = ["文件", "文档", "附件", "表格", "文本", "代码", "脚本", "提示词", "人设"]
    parts += [f"(?<![a-z]){t}" for t in _ARTIFACT_LATIN_NOUNS]
    parts += [
        f"(?<![a-z]){re.escape(key)}"
        for key in sorted(
            (k for k in _ARTIFACT_LANGUAGES if k[:1].isalpha()), key=len, reverse=True
        )
    ]
    return "|".join(parts)


def artifact_request(user_text: str) -> tuple[str, str] | None:
    text = _ARTIFACT_DELIVERY_DECLARATION.sub(" ", (user_text or "").lower())
    if not re.search(rf"({_ARTIFACT_VERBS}){_ARTIFACT_GAP}({_artifact_nouns()})", text):
        return None
    languages = _ARTIFACT_LANGUAGES
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
    if re.search(r"文件|文档|附件|表格|txt|文本|document|file|提示词|人设", text):
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
