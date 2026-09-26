"""文件读取链的崩溃安全性：坏内容只能诚实降级，绝不让异常逃出读取入口。

为什么单独一件测试（2026-09-25 需求 16(1) + 需求 17）：
`.xls`/`.ppt` 那族「包级异常不在捕获元组内 → 崩读取链」的缺陷（V2.1 风险 8）当年
只补了旧格式分支，**现代格式分支一直留着同一个洞**——只是 pypdf 未装时 PDF 恒走
ImportError 而被顺带兜住。装上 pypdf 后这条洞立刻变成活的：群里任何人发一个坏
PDF、或把任意 zip 改名成 .docx/.xlsx/.pptx，异常就从
``read_supported_file`` 逃出，撞进三个消费方——

* 根 ``__init__.py`` 入站归一（只捕 ImportError/OSError/ValueError/TypeError）
* 控制面 ``POST /files/read``（完全没有 try → 500）
* 中央 ``files.read.*`` 协议

本件锁的是「读取入口对**内容**问题绝不抛」这一条不变量，不是某个解析器的返回值。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
    read_supported_file,
)

# ==================== 构造样本（不依赖外部 fixture 文件） ====================


def _minimal_text_pdf(text: str = "Shorekeeper log") -> bytes:
    """手搓一份 xref 偏移正确的合法 PDF（含可读文本）。

    刻意不用第三方 writer 造文本层：pypdf 的 ``PdfWriter`` 加不了带字形的内容流，
    reportlab 也不在她的 venv 里（P-6 裁定只装 pypdf）。偏移由代码算，不手数。
    """
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_at)
    )
    return bytes(out)


def _zip_without_opc_parts(*, prefix: str = "") -> bytes:
    """一个**合法 zip**但没有 OOXML 必需件——python-docx/openpyxl/pptx 都在此抛包级异常。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(prefix + "readme.txt", "not an office document")
    return buffer.getvalue()


# ==================== 可用路径：装了就真能读出来 ====================


def test_valid_pdf_text_is_actually_extracted(tmp_path: Path) -> None:
    """需求 16(1) 的正腿：pypdf 在册后 PDF 必须真出字，不能一路「诚实降级」糊过去。"""
    pypdf = pytest.importorskip("pypdf")
    del pypdf  # 只用于「环境已装」这道 skip 门；字节自己搓，见 _minimal_text_pdf
    target = tmp_path / "note.pdf"
    target.write_bytes(_minimal_text_pdf())

    result = read_supported_file(target)

    assert result.kind == "pdf"
    assert result.title == "note.pdf"
    assert "Shorekeeper log" in result.text
    assert (result.metadata or {}).get("status") is None


def test_blank_pdf_reads_as_empty_not_as_failure(tmp_path: Path) -> None:
    """空白页 PDF 是「读到了但没字」，不能被标成解析器不可用（那是另一回事）。"""
    pypdf = pytest.importorskip("pypdf")
    target = tmp_path / "scan.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with target.open("wb") as stream:
        writer.write(stream)

    result = read_supported_file(target)

    assert result.kind == "pdf"
    assert result.text == ""
    assert (result.metadata or {}).get("status") is None


# ==================== 崩溃安全：坏内容绝不抛 ====================

_MALFORMED_PDF = {
    "缺 startxref": b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
    "只有头没有体": b"%PDF-1.4\ntrailer\n%%EOF\n",
    "根本不是 PDF": b"NOT-A-PDF-AT-ALL",
    "半截文件": b"%PDF-1.7\n1 0 obj\n<< /Type /Pages /Kids [2 0 R] /Count 1 >>\n",
    "伪装头 + 垃圾": b"%PDF-1.4\n" + b"\x00" * 4096,
}


@pytest.mark.parametrize(("label", "payload"), list(_MALFORMED_PDF.items()))
def test_malformed_pdf_degrades_instead_of_raising(
    tmp_path: Path, label: str, payload: bytes
) -> None:
    del label  # 只进参数 id，便于失败时一眼看出是哪一枚
    target = tmp_path / "broken.pdf"
    target.write_bytes(payload)

    result = read_supported_file(target)  # 修复前：pypdf.errors.PdfReadError 直接逃出

    assert result.kind == "pdf"
    assert result.text == ""
    assert (result.metadata or {}).get("status") == "parse_failed"


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("fake.docx", "document"),
        ("fake.xlsx", "spreadsheet"),
        ("fake.pptx", "presentation"),
    ],
)
def test_plain_text_masquerading_as_office_degrades(
    tmp_path: Path, filename: str, kind: str
) -> None:
    """改名骗过后缀的纯文本：python-docx 抛 PackageNotFoundError，另两家各抛自己的。"""
    target = tmp_path / filename
    target.write_bytes("这就是一段普通文本，只是把后缀改成了办公格式。".encode())

    result = read_supported_file(target)

    assert result.kind == kind
    assert result.text == ""
    assert (result.metadata or {}).get("status") == "parse_failed"


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("bare.docx", "document"),
        ("bare.xlsx", "spreadsheet"),
        ("bare.pptx", "presentation"),
    ],
)
def test_valid_zip_without_opc_parts_degrades(
    tmp_path: Path, filename: str, kind: str
) -> None:
    """合法 zip 但缺 ``[Content_Types].xml``：三家都从 zipfile 索引里抛 KeyError。

    KeyError 不在任何一家旧捕获元组里，是这三条分支最省事的一发攻击。
    """
    target = tmp_path / filename
    target.write_bytes(_zip_without_opc_parts())

    result = read_supported_file(target)

    assert result.kind == kind
    assert result.text == ""
    assert (result.metadata or {}).get("status") == "parse_failed"


def test_truncated_docx_degrades(tmp_path: Path) -> None:
    payload = _zip_without_opc_parts()[:18]
    target = tmp_path / "half.docx"
    target.write_bytes(payload)

    result = read_supported_file(target)

    assert result.kind == "document"
    assert (result.metadata or {}).get("status") == "parse_failed"


def test_degrade_carries_title_so_callers_can_name_the_file(tmp_path: Path) -> None:
    """降级也要带回文件名：否则控制面与回执只能显示空标题，报不了「哪一个坏了」。"""
    target = tmp_path / "报告.pdf"
    target.write_bytes(b"%PDF-1.4\nnonsense\n")

    result = read_supported_file(target)

    assert result.title == "报告.pdf"


def test_reason_does_not_echo_raw_exception_text(tmp_path: Path) -> None:
    """降级说明只准给归类短语，不得把解析器原文（含绝对路径）塞进 metadata。

    绝对路径会随 ``CapabilityResult`` 出站，``redact_local_secrets`` 之外的面不兜。
    """
    target = tmp_path / "leak.pdf"
    target.write_bytes(b"%PDF-1.4\ntrailer\n%%EOF\n")

    metadata = read_supported_file(target).metadata or {}

    joined = " ".join(str(v) for v in metadata.values())
    assert ":" not in joined.replace("parse_failed", "")  # 盘符/端口形态都不该出现
    assert str(tmp_path) not in joined
    assert metadata.get("status") == "parse_failed"


# ==================== 协议面：不许把「坏了」说成「旧格式没适配器」 ====================


def _make_request(capability_id: str, payload: dict[str, Any]) -> Any:
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    return CapabilityRequest(
        capability_id=capability_id,
        payload=payload,
        principal="seat-pdf-1",
        roles=("super_admin",),
        context={},
    )


def test_protocol_calls_corrupt_file_damage_not_legacy_format(tmp_path: Path) -> None:
    """人话判据：损坏就说损坏，不给她一条查不到人的「旧格式无真实适配器」。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationStatus,
        default_invoker,
    )

    target = tmp_path / "broken.pdf"
    target.write_bytes(b"%PDF-1.4\ntrailer\n%%EOF\n")

    result = default_invoker().invoke(
        _make_request("files.read.pdf", {"path": str(target)})
    )

    assert result.status is InvocationStatus.DEGRADED
    assert "损坏" in result.detail or "无法解析" in result.detail
    assert "旧格式" not in result.detail


def test_protocol_still_names_legacy_format_as_unavailable(tmp_path: Path) -> None:
    """反向锁：旧 OLE2 那族**仍**是「无适配器」，不能被新归类一起改口。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationStatus,
        default_invoker,
    )

    target = tmp_path / "old.xls"
    target.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512)

    result = default_invoker().invoke(
        _make_request("files.read.excel", {"path": str(target)})
    )

    assert result.status is InvocationStatus.DEGRADED
    assert "parser_unavailable" in result.detail
