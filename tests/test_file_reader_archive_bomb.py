"""归档类文件的解压前体检 + 文本腿的流式截断读（需求 17，席位 S-FILESAFE，2026-09-28）。

两件攻击面，都住在 ``domains/files/sources/file_reader.py``：

**① 解压炸弹（AS-RESOURCE-ARCHIVE-BOMB）**——``.docx/.xlsx/.pptx`` 全是 zip 容器，
解析器会**自行**把成员解出来。旧链只有出口侧的 ``max_chars``，而字符是解完之后
才截的：几十 KB 的容器声明解出几 GB，字节先进内存，那条截断永远轮不到说话。
本件锁的是「超限容器**一次都不碰解析器**」＋「归因不许说谎」（限额拦下的不能说成
文件损坏）。

**② 超大文本 OOM**——旧 ``_text`` 写的是 ``path.read_bytes()[:max_chars*4]``：
先把整份文件读进内存再切前缀。本件锁的是「读到的字节数与文件大小无关」，
用**记账包装 + 假尺寸**两种构造，不真造 5GB 文件（那是磁盘事故，不是测试）。

注毒自证（规则 11 的执法形态）在文末：把体检闸关掉，断言炸弹样本**必须**变红。
"""

from __future__ import annotations

import io
import types
import zipfile
from pathlib import Path
from typing import Self

import pytest

from plugins.bot_unified_runtime.domains.files.sources import file_reader
from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
    ARCHIVE_MAX_MEMBER_BYTES,
    ARCHIVE_MAX_MEMBER_COUNT,
    PARSE_STATUS_SENTENCES,
    read_supported_file,
)

# ==================== 构造样本 ====================


def _zip_with_members(entries: dict[str, bytes], *, compressed: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(
                name,
                payload,
                compress_type=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED,
            )
    return buffer.getvalue()


def _bomb_docx_bytes() -> bytes:
    """一枚**申报解压后尺寸超限**的 .docx：40MB 的零填充压成几十 KB。

    这就是 zip bomb 的真实形态——容器小、解出来大。
    """
    return _zip_with_members(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"\x00" * (ARCHIVE_MAX_MEMBER_BYTES + 8 * 1024 * 1024),
        }
    )


def _many_members_docx_bytes() -> bytes:
    """成员数超限（每枚都很小，超限的是**件数**）。"""
    entries = {f"word/part{i}.xml": b"<a/>" for i in range(ARCHIVE_MAX_MEMBER_COUNT + 5)}
    return _zip_with_members(entries)


def _entity_bomb_docx_bytes() -> bytes:
    """billion-laughs 形态：申报尺寸很小，展开后才吃内存——实体声明就在开头。"""
    payload = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE w:document [ <!ENTITY a "aaaaaaaaaa" >'
        b' <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;" > ]>\n'
        b"<w:document/>"
    )
    return _zip_with_members({"[Content_Types].xml": b"<Types/>", "word/document.xml": payload})


def _plain_zip_bytes() -> bytes:
    """合法 zip、但没有 OOXML 必需件（既有锁 ``test_valid_zip_without_opc_parts`` 的同款）。"""
    return _zip_with_members({"readme.txt": b"not an office document"})


def _tiny_docx_bytes() -> bytes:
    """合法尺寸的伪 docx（含 Content_Types 与不超限的 document.xml）。"""
    return _zip_with_members(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<w:document/>",
        }
    )


# ==================== ① 体检闸：拦得住、不误伤、不撒谎 ====================


@pytest.mark.parametrize(
    ("expect_code", "builder"),
    [
        ("member_bytes", _bomb_docx_bytes),
        ("member_count", _many_members_docx_bytes),
        ("internal_entity", _entity_bomb_docx_bytes),
    ],
)
def test_archive_bomb_is_refused_before_the_parser_runs(
    tmp_path: Path, expect_code: str, builder: object
) -> None:
    """样本走**构造函数**参数化，不把 bytes 塞进参数列：pytest 会把参数值写进
    ``PYTEST_CURRENT_TEST`` 环境变量，几十 MB 的炸弹样本直接把它撑爆（Windows 上限
    32767 字符 ⇒ ValueError），那是测试形态事故、不是被测件的问题。"""
    target = tmp_path / "big.docx"
    target.write_bytes(builder())  # type: ignore[operator]

    result = read_supported_file(target)

    assert result.kind == "document"
    assert result.text == ""
    metadata = result.metadata or {}
    assert metadata.get("status") == "archive_expansion_limited"
    assert metadata.get("code") == expect_code


def test_archive_bomb_never_opens_the_document_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判据不止是"结果对"：解析器**一次都不许被叫起来**（炸弹的代价在解压那一刻）。

    两枚假解析器：装了真库也不许被调用；没装真库时它们就是"被调用＝当场炸"的探针。
    """
    sys = __import__("sys")

    def _trip(*_a: object, **_k: object) -> None:
        raise AssertionError("体检超限之后不该再走解析器")

    fake_docx = types.ModuleType("docx")
    fake_docx.Document = _trip  # type: ignore[attr-defined]
    docx_opc = types.ModuleType("docx.opc")
    docx_exc = types.ModuleType("docx.opc.exceptions")

    class _OpcError(Exception):
        pass

    docx_exc.OpcError = _OpcError  # type: ignore[attr-defined]
    docx_opc.exceptions = docx_exc  # type: ignore[attr-defined]
    fake_docx.opc = docx_opc  # type: ignore[attr-defined]

    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = _trip  # type: ignore[attr-defined]
    fake_utils = types.ModuleType("openpyxl.utils")
    fake_utils_exc = types.ModuleType("openpyxl.utils.exceptions")

    class _InvalidFileException(Exception):
        pass

    fake_utils_exc.InvalidFileException = _InvalidFileException  # type: ignore[attr-defined]
    fake_utils.exceptions = fake_utils_exc  # type: ignore[attr-defined]
    fake_openpyxl.utils = fake_utils  # type: ignore[attr-defined]

    fake_pptx = types.ModuleType("pptx")
    fake_pptx.Presentation = _trip  # type: ignore[attr-defined]
    fake_pptx_exc = types.ModuleType("pptx.exc")

    class _PackageNotFoundError(Exception):
        pass

    fake_pptx_exc.PackageNotFoundError = _PackageNotFoundError  # type: ignore[attr-defined]
    fake_pptx.exc = fake_pptx_exc  # type: ignore[attr-defined]

    for name, module in (
        ("docx", fake_docx),
        ("docx.opc", docx_opc),
        ("docx.opc.exceptions", docx_exc),
        ("openpyxl", fake_openpyxl),
        ("openpyxl.utils", fake_utils),
        ("openpyxl.utils.exceptions", fake_utils_exc),
        ("pptx", fake_pptx),
        ("pptx.exc", fake_pptx_exc),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    for filename in ("big.docx", "big.xlsx", "big.pptx"):
        target = tmp_path / filename
        target.write_bytes(_bomb_docx_bytes())
        result = read_supported_file(target)
        assert (result.metadata or {}).get("status") == "archive_expansion_limited", filename


def test_archive_limit_says_limit_not_corruption(tmp_path: Path) -> None:
    """归因纪律：限额拦下的不许说成「你的文件损坏」（PARSE_STATUS_SENTENCES 一态一因）。"""
    target = tmp_path / "big.docx"
    target.write_bytes(_bomb_docx_bytes())

    result = read_supported_file(target)
    note = file_reader.file_read_failure_note(result)

    assert "archive_expansion_limited" in note
    assert PARSE_STATUS_SENTENCES["archive_expansion_limited"] in note
    assert "防解压炸弹" in note
    assert "损坏" not in note


@pytest.mark.parametrize("filename", ["ok.docx", "ok.xlsx", "ok.pptx"])
def test_small_containers_pass_the_gate(tmp_path: Path, filename: str) -> None:
    """不误伤：合法尺寸的容器**照旧**走到各自分支（这里只验体检闸放行）。"""
    target = tmp_path / filename
    target.write_bytes(_tiny_docx_bytes())

    assert file_reader.archive_expansion_violation(target) == ""


def test_non_zip_still_reported_as_damage_by_existing_branches(tmp_path: Path) -> None:
    """体检闸不许抢「根本不是 zip」那句归因：超限代号只留给真超限。"""
    target = tmp_path / "fake.docx"
    target.write_bytes("这就是一段普通文本，只是后缀改成了办公格式。".encode())

    assert file_reader.archive_expansion_violation(target) == ""
    result = read_supported_file(target)
    assert (result.metadata or {}).get("status") == "parse_failed"


def test_existing_opc_less_zip_lock_untouched(tmp_path: Path) -> None:
    """既有锁的形态不许被本席改动：合法 zip 缺必需件＝parse_failed，不是超限。"""
    target = tmp_path / "bare.docx"
    target.write_bytes(_plain_zip_bytes())

    result = read_supported_file(target)
    assert (result.metadata or {}).get("status") == "parse_failed"


def test_real_docx_still_parses_after_the_gate(tmp_path: Path) -> None:
    """正腿（装了 python-docx 才跑）：体检之后真文档仍要读得出字。"""
    docx_module = pytest.importorskip("docx")
    target = tmp_path / "notes.docx"
    document = docx_module.Document()
    document.add_paragraph("泰缇斯系统第二实例")
    document.save(str(target))

    result = read_supported_file(target)
    assert "泰缇斯系统第二实例" in result.text
    assert (result.metadata or {}).get("status") is None


# ==================== ② 文本腿：只读前缀，读多少与文件大小无关 ====================


class _CountingReader:
    """包一层真文件句柄，记下每一次 ``read()`` 的请求量（不改变内容）。"""

    def __init__(self, stream: object) -> None:
        self._stream = stream
        self.requested: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested.append(int(size))
        return self._stream.read(size)  # type: ignore[attr-defined]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._stream.close()  # type: ignore[attr-defined]


def test_text_leg_never_reads_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 MiB 的文本 + max_chars=100 ⇒ 只许按 4×预算请求字节，且一次都不许 read_bytes()。"""
    target = tmp_path / "huge.txt"
    target.write_bytes(b"a" * (1024 * 1024))

    seen: list[_CountingReader] = []
    real_open = Path.open

    def _counting_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
        handle = real_open(self, mode, *args, **kwargs)  # type: ignore[arg-type]
        if "b" in mode:
            wrapper = _CountingReader(handle)
            seen.append(wrapper)
            return wrapper
        return handle

    def _no_whole_read(self: Path) -> bytes:
        raise AssertionError("超大文本腿不许再整档 read_bytes()（OOM 面）")

    monkeypatch.setattr(Path, "open", _counting_open)
    monkeypatch.setattr(Path, "read_bytes", _no_whole_read)

    out = file_reader._text(target, 100)

    assert len(out) == 100
    assert seen and seen[0].requested == [400]  # max_chars * 4，与文件 1 MiB 无关


def test_truncation_is_declared_not_silent(tmp_path: Path) -> None:
    """读不完要明说（模块不变量③）：正文里出现「后面的内容没有读」。"""
    target = tmp_path / "long.log"
    target.write_bytes(("甲" * 5000).encode("utf-8"))

    result = read_supported_file(target, max_chars=100)

    assert "后面的内容没有读" in result.text
    assert (result.metadata or {}).get("text_truncated") is True


def test_small_text_file_gets_no_truncation_noise(tmp_path: Path) -> None:
    """反向锁：读全了不许补一句「没读完」（过度修正同样是谎）。"""
    target = tmp_path / "short.txt"
    target.write_bytes("很短的一段".encode())

    result = read_supported_file(target, max_chars=100)

    assert result.text == "很短的一段"
    assert (result.metadata or {}).get("text_truncated") is None


def test_giant_declared_size_note_uses_fake_size_not_disk(tmp_path: Path) -> None:
    """假尺寸构造（不真造 5GB）：预算 400 字节 vs 5GiB 申报，句子要说明白。"""
    fake = types.SimpleNamespace(
        stat=lambda: types.SimpleNamespace(st_size=5 * 1024 * 1024 * 1024)
    )

    note = file_reader._text_truncation_note(fake, 100)  # type: ignore[arg-type]

    assert "5368709120" in note
    assert "没读不等于没有内容" in note


# ==================== 注毒自证（规则 11：闸坏了必须红） ====================


def test_poison_self_check_removing_the_gate_turns_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒自证：把体检闸接成恒放行（＝本席没做的形态），本文件必须红。

    这条锁证明「超限当场降级」确实由**这道闸**产出，而不是解析器自己运气好——
    摘闸之后炸弹样本的归因若还写着 ``archive_expansion_limited``，说明状态码是别处
    硬编码的假账，当场失败。
    """
    target = tmp_path / "poison.docx"
    target.write_bytes(_bomb_docx_bytes())
    guarded = (read_supported_file(target).metadata or {}).get("status")
    assert guarded == "archive_expansion_limited"

    monkeypatch.setattr(file_reader, "archive_expansion_violation", lambda source: "")
    unguarded = (read_supported_file(target).metadata or {}).get("status")
    assert unguarded != "archive_expansion_limited", (
        "注毒生效：体检闸被摘掉，超限容器仍被记成「超限」＝状态码来自假账"
    )
