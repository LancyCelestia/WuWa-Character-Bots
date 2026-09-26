"""PDF「读到但没字」诚实锁（`file_reader` 模块不变量③，2026-09-26 S-FILESLAND-2 补册）。

**本件为什么存在**：`domains/files/sources/file_reader.py` 的模块 docstring 与
`SCAN_EMPTY_SENTENCES` 表注都写着「锁在 ``tests/test_pdf_scan_honesty.py``」，
而该件在盘上**不存在**（现算：`ls tests/test_pdf_scan_honesty.py` 无命中，
全测试树 grep `pdf_scan` / `SCAN_EMPTY_SENTENCES` / `DECODE_ACCEPT_RATIO` 也 0 命中）。
即 S-T-PDF-3 交付了判据代码、其锁件随该窗的硬断电一并丢了——留下一条
「在册符号指向不存在件」的死指针（正是 #49 立规点名的形态），后果是
**不变量③今天零执法**：谁把「图像型扫描件」并回「空白页」、或把口令保护重新吞成
「文件损坏」，全套件不会有任何一枚用例变红。

与同族另两格的分工（不重复覆盖）：

- ``tests/test_file_ingress_failure_feedback.py``＝第①格（``parse_failed`` /
  ``parser_unavailable`` 两态 + 两态互斥结构锁）；
- ``tests/test_files_domain_audit.py::test_unsupported_or_missing_file_still_gets_a_plain_sentence``
  ＝第③格（``kind`` 面 unknown / missing 沉默两态）；
- 本件＝第②格（PDF 扫描链的「读到但没字」四态 + 量化尺 + 页数/字符截断 +
  口令保护单独成句）。

全部离线：解析器由 ``pypdf`` 的**替身**交出（页文本 / 页错误 / 图像 XObject /
加密位全由用例点名），不造真 PDF、不碰网络、不读运行数据根。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.domains.files.sources import file_reader

_READ_PDF = file_reader._read_pdf  # 私有口的直调：本件锁的就是这一口的判据本身


# ---------------------------------------------------------------------------
# 替身：可控的 PdfReader（页文本 / 页错误 / 图像 / 加密位逐例点名）
# ---------------------------------------------------------------------------


class _ImageXObject(dict):
    """``/XObject`` 里的一枚图像资源：``get_object()`` 交回自己（含 /Subtype）。"""

    def get_object(self) -> _ImageXObject:
        return self


class _ImageDict(dict):
    def get_object(self) -> _ImageDict:
        return self


class _Indirect(dict):
    def get_object(self) -> _Indirect:
        return self


def _page(
    text: str | None,
    *,
    with_image: bool = False,
    boom: bool = False,
) -> Any:
    """一枚页替身：``extract_text`` 返文本 / 抛错；``/Resources`` 可挂图像 XObject。"""

    def _extract_text() -> str:
        if boom:
            raise ValueError("页对象内部错误")
        return text or ""

    resources: Any = None
    if with_image:
        resources = _Indirect(
            {
                "/XObject": _ImageDict(
                    {"Im0": _ImageXObject({"/Subtype": "/Image"})}
                )
            }
        )

    def _get(key: str) -> Any:
        return resources if key == "/Resources" else None

    return SimpleNamespace(extract_text=_extract_text, get=_get)


class _FakeReader:
    """``pypdf.PdfReader`` 替身。``pages`` 给页列表；``encrypted`` 控制口令分支。

    状态挂在**类属性**上（每条用例开头由 fixture 复位），因为 ``_read_pdf`` 自己
    ``PdfReader(str(source))`` 构造，用例拿不到实例、只换得到类。
    """

    pages: ClassVar[list[Any]] = []
    encrypted: ClassVar[bool] = False
    unlock_with_empty_password: ClassVar[bool] = False
    decrypt_error: ClassVar[type[BaseException] | None] = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    @property
    def is_encrypted(self) -> bool:
        return type(self).encrypted

    def decrypt(self, _password: str = "") -> bool:
        error = type(self).decrypt_error
        if error is not None:
            raise error("加密族不支持")
        return type(self).unlock_with_empty_password


@pytest.fixture
def reader_class(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeReader]]:
    """把 ``pypdf.PdfReader`` 换成替身（``_read_pdf`` 在函数体内 import ⇒ 换得到）。

    pypdf 未装的机器上本件仍然可跑：替身注入前先把 ``pypdf`` 与 ``pypdf.errors``
    两张假模块塞进 ``sys.modules``，判据 ``PyPdfError`` 用真异常类顶上。
    """
    import sys

    try:
        import pypdf  # type: ignore[import-not-found]

        monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)
    except ImportError:  # pragma: no cover - 生产 venv 装了 pypdf，此路为可移植兜底
        errors = SimpleNamespace(PyPdfError=RuntimeError)
        fake = SimpleNamespace(PdfReader=_FakeReader, errors=errors)
        monkeypatch.setitem(sys.modules, "pypdf", fake)
        monkeypatch.setitem(sys.modules, "pypdf.errors", errors)
    yield _FakeReader
    _FakeReader.pages = []
    _FakeReader.encrypted = False
    _FakeReader.unlock_with_empty_password = False
    _FakeReader.decrypt_error = None


def _scan_of(result: file_reader.FileReadResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    scan = metadata.get("pdf_scan")
    assert isinstance(scan, dict), f"缺 pdf_scan：{metadata!r}"
    return scan


# ---------------------------------------------------------------------------
# ① 结构锁：三张表互不越界（并表＝把「读不了」的三种归因洗成一种）
# ---------------------------------------------------------------------------


def test_scan_empty_table_is_exactly_the_four_states_and_mutually_distinct() -> None:
    """四态恰四枚、句子两两不同：任何两态并一＝对扫描件/空白页说谎。"""
    table = file_reader.SCAN_EMPTY_SENTENCES
    assert set(table) == {
        "scanned_no_text",
        "blank_pages",
        "no_pages",
        "page_errors",
    }, f"空态表不再是那四枚：{sorted(table)}"
    sentences = list(table.values())
    assert all(sentence.strip() for sentence in sentences), "有空句子＝那一态等于没说"
    assert len(set(sentences)) == len(sentences), "两态并成一句话说不出（互斥性破了）"
    # 「读不了 ≠ 没有内容」这一句教义必须留在扫描件那一格里（它最容易被写成「没有字」）。
    assert "不是「没有内容」" in table["scanned_no_text"]


def test_password_state_lives_its_own_table_never_merged_into_parse_failed() -> None:
    """口令保护单独成句：它既不是「损坏」也不是「缺解析器」，也不许并进那两张表。"""
    assert set(file_reader.NOTE_STATUS_SENTENCES) == {"password_protected"}
    password_line = file_reader.NOTE_STATUS_SENTENCES["password_protected"]
    assert "打开口令" in password_line
    # 明写「这不是文件损坏」是这一格的全部意义：旧链把 FileNotDecryptedError 吞进
    # parse_failed、报成「损坏或不是有效的 PDF」＝归因谎报。断言的是**否定式在场**，
    # 不是「损坏」二字不许出现（那两个字正是被否定对象）。
    assert "不是文件损坏" in password_line
    assert password_line != file_reader.PARSE_STATUS_SENTENCES["parse_failed"]
    overlap = set(file_reader.NOTE_STATUS_SENTENCES) & set(file_reader.PARSE_STATUS_SENTENCES)
    assert not overlap, f"三张表串了：{sorted(overlap)}"
    assert "password_protected" not in file_reader.SCAN_EMPTY_SENTENCES


def test_decode_accept_ratio_is_the_eighty_percent_line() -> None:
    """量化尺的达标线是钉死的 0.8（改它＝改判据，得连带改本锁与两处文案）。"""
    assert file_reader.DECODE_ACCEPT_RATIO == 0.8
    assert file_reader.PDF_SCAN_MAX_PAGES > 0


# ---------------------------------------------------------------------------
# ② 量化尺：None / 达标 / 不达标 三态可分（None 不是 0 也不是 1）
# ---------------------------------------------------------------------------


def test_cjk_ratio_sees_three_states_and_returns_none_when_not_applicable() -> None:
    assert file_reader.cjk_decode_ratio("pure latin text") is None, "无证据不猜"
    assert file_reader.cjk_decode_ratio("守岸人泰缇斯系统") == 1.0
    garbled = "守岸人" + "\ue000" * 20  # 私用区：缺 ToUnicode 的 CID 字体常见落点
    ratio = file_reader.cjk_decode_ratio(garbled)
    assert ratio is not None and ratio < file_reader.DECODE_ACCEPT_RATIO


@pytest.mark.parametrize(
    "sample",
    ["\ufffd\ufffd", "\ue000\ue001", "\x01\x02", "\x7f\x7f"],
)
def test_garbled_counter_covers_all_three_glyph_families(sample: str) -> None:
    """三类坏字形各算一次：替换符 / 私用区 / 非空白控制符（少一类尺就瞎一截）。"""
    assert file_reader.count_garbled_chars(sample) == 2
    assert file_reader.count_cjk_chars(sample) == 0


def test_plain_crlf_and_tab_are_not_counted_as_garbled() -> None:
    """反向锁：\\t\\n\\r 与空白不算乱码——否则每份换行文档都会被误警告。"""
    assert file_reader.count_garbled_chars("第一行\n第二行\t尾巴\r\n") == 0


# ---------------------------------------------------------------------------
# ③ 四态端到端：空文本必须落在正确的那一格
# ---------------------------------------------------------------------------


def test_zero_page_pdf_reads_as_no_pages_not_as_failure(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = []
    result = _READ_PDF(tmp_path / "empty.pdf", 1000, None)
    scan = _scan_of(result)
    assert scan["empty_reason"] == "no_pages"
    assert result.text == "", "零页文档不该有正文（有就是编的）"
    assert "status" not in (result.metadata or {}), "空态不许占 status（两态锁的边界）"
    note = file_reader.file_read_failure_note(result)
    assert note.startswith("[文件无文字：") and "没有声明任何可读页面" in note


def test_blank_pages_are_not_reported_as_scanned(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = [_page(""), _page("  \n ")]
    result = _READ_PDF(tmp_path / "blank.pdf", 1000, None)
    scan = _scan_of(result)
    assert scan["empty_reason"] == "blank_pages"
    assert scan["image_pages"] == 0 and scan["pages_total"] == 2
    assert "扫描件" not in result.text, "把空白页说成扫描件＝多告诉用户一个不存在的归因"


def test_image_only_pages_are_reported_as_scanned(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = [_page("", with_image=True), _page("")]
    result = _READ_PDF(tmp_path / "scan.pdf", 1000, None)
    scan = _scan_of(result)
    assert scan["empty_reason"] == "scanned_no_text"
    assert scan["image_pages"] == 1
    note = file_reader.file_read_failure_note(result)
    assert "OCR 兜底今天不生效" in note, "扫描件必须带上「读不了」的那半句"
    assert "不是「没有内容」" in note


def test_every_page_failing_reads_as_page_errors(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = [_page(None, boom=True), _page(None, boom=True)]
    result = _READ_PDF(tmp_path / "broken-page.pdf", 1000, None)
    scan = _scan_of(result)
    assert scan["empty_reason"] == "page_errors"
    assert scan["pages_failed"] == 2
    assert "没有读到" in result.text and "≠没有" in result.text


def test_partial_page_failure_does_not_kill_the_document(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    """一页坏掉只记一笔，其余照读——旧行为是一页抛错整档坠地。"""
    reader_class.pages = [_page("可读的一页"), _page(None, boom=True)]
    result = _READ_PDF(tmp_path / "half.pdf", 1000, None)
    scan = _scan_of(result)
    assert "empty_reason" not in scan, "读到了内容就不该有空态归因"
    assert scan["pages_failed"] == 1
    assert "可读的一页" in result.text
    assert "有 1 页因页对象内部错误没有读到" in result.text


# ---------------------------------------------------------------------------
# ④ 截断必须留行：页数与字符上限都不许被读成「后面没有」
# ---------------------------------------------------------------------------


def test_page_cap_truncation_is_announced(tmp_path: Path, reader_class: type[_FakeReader]) -> None:
    reader_class.pages = [_page(f"第{i}页内容") for i in range(5)]
    result = _READ_PDF(tmp_path / "long.pdf", 1000, 2)
    scan = _scan_of(result)
    assert scan == {**scan, "pages_total": 5, "pages_read": 2}
    assert "只读了前 2 页" in result.text
    assert "后面 3 页没有读" in result.text


def test_char_cap_truncation_is_announced(tmp_path: Path, reader_class: type[_FakeReader]) -> None:
    body = "甲" * 200
    reader_class.pages = [_page(body)]
    result = _READ_PDF(tmp_path / "wide.pdf", 50, None)
    assert "已达 50 字符读取上限" in result.text
    assert "另有 150 字未读" in result.text
    assert len(result.text) < 200 + 60, "正文本身没被截＝上限只是装饰"


def test_garbled_body_gets_a_warning_line_and_a_ratio_on_the_book(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = [_page("中文" + "\ue000" * 40)]
    result = _READ_PDF(tmp_path / "cid.pdf", 5000, None)
    scan = _scan_of(result)
    assert scan["decode_ratio"] < file_reader.DECODE_ACCEPT_RATIO
    assert "中文解码质量警告" in result.text
    assert "不是「原文里没有字」" in result.text


# ---------------------------------------------------------------------------
# ⑤ 口令保护：单独成句，且「空口令解得开」不算口令保护
# ---------------------------------------------------------------------------


def test_encrypted_pdf_is_named_as_password_protected(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.encrypted = True
    reader_class.unlock_with_empty_password = False
    result = _READ_PDF(tmp_path / "locked.pdf", 1000, None)
    assert (result.metadata or {})["status"] == "password_protected"
    note = file_reader.file_read_failure_note(result)
    assert "打开口令" in note and "这不是文件损坏" in note


def test_empty_password_unlockable_pdf_is_read_normally(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    """权限口令（空口令可解）照读：把它报成「要口令」是另一种谎报。"""
    reader_class.encrypted = True
    reader_class.unlock_with_empty_password = True
    reader_class.pages = [_page("解开了")]
    result = _READ_PDF(tmp_path / "perm.pdf", 1000, None)
    assert "status" not in (result.metadata or {})
    assert "解开了" in result.text


def test_decrypt_raising_a_declared_error_is_treated_as_unreadable(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    """``decrypt`` 抛「不支持的加密族」（pypdf 实抛 NotImplementedError）＝按读不出处理。"""
    reader_class.encrypted = True
    reader_class.decrypt_error = NotImplementedError
    result = _READ_PDF(tmp_path / "weird-enc.pdf", 1000, None)
    assert (result.metadata or {})["status"] == "password_protected"


#: S-16-PDF-EXC-SURFACE（2026-09-26 S-FILESLAND-2 登记 → 同日主代理按裁定「乙」修）。
#: 原判定：``_read_pdf`` 的三处捕获元组（构造 / ``decrypt`` / 逐页）**全是异常类的
#: 枚举**，而本模块 docstring 的不变量①写的是「对内容问题一律诚实降级，**绝不抛
#: 异常**」。实测：``decrypt`` 抛一枚不在元组里的 ``RuntimeError`` 时，异常从
#: ``_read_pdf`` → ``read_supported_file`` 一路逃出，而根入站归一只兜
#: ``(ImportError, OSError, ValueError, TypeError)`` ⇒ **一个畸形加密 PDF 足以打断
#: 消息入站链路**。
#: 落地的修法是乙：在**公共口** ``read_supported_file`` 外面包一层总兜底，把未枚举
#: 异常收敛成单列一态 ``internal_parse_error``（不并进 ``parse_failed``——把程序故障
#: 说成"文件损坏"是谎报归因），逐处枚举仍保留细归因。因此本格的锁点从「直调私有口」
#: 移到「走公共口」，并保留一条反向锁证明：**去掉这层包装，异常照样逃得出去**
#: （否则这条锁可能只是在量空气）。
def test_undeclassified_decrypt_crash_degrades_at_the_public_entry(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    """非枚举异常在公共口收敛成一态，且这一态有自己的一句人话。"""
    target = tmp_path / "crashy.pdf"
    target.write_bytes(b"%PDF-1.7 not really a pdf")
    reader_class.encrypted = True
    reader_class.decrypt_error = RuntimeError

    result = file_reader.read_supported_file(target)  # 今天：不抛

    meta = result.metadata or {}
    assert meta["status"] == "internal_parse_error", meta
    assert meta["exc"] == "RuntimeError", meta
    assert result.text == ""

    # 措辞必须真有一句话：表外状态返回空串＝静默吞（第①格立过的规矩）。
    sentence = file_reader.parse_status_sentence("internal_parse_error")
    assert sentence and "程序" in sentence
    # 不与"文件损坏"共用一句：两态混同＝把我们的错记到她的文件上。
    assert sentence != file_reader.parse_status_sentence("parse_failed")
    # 归因里不许出现绝对路径（``_degrade`` 的既有口径，异常原文常带路径）。
    note = file_reader.file_read_failure_note(result)
    assert str(tmp_path) not in note and ":" not in note.split("：")[0]


def test_the_catch_all_is_what_saves_the_entry_not_the_enum(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    """反向锁：绕开公共口直调实现体，同一枚异常**必须**还是抛出来。

    没有这一发，上一条锁可能只是在量空气——它证明"不抛"来自新加的那层总兜底，
    而不是逐处枚举今天恰好补全了。
    """
    target = tmp_path / "crashy-body.pdf"
    target.write_bytes(b"%PDF-1.7 not really a pdf")
    reader_class.encrypted = True
    reader_class.decrypt_error = RuntimeError

    with pytest.raises(RuntimeError):
        file_reader._read_supported_file_body(target)


# ---------------------------------------------------------------------------
# ⑥ 措辞出口：标签分家 + 不猜 + 不带绝对路径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    ["scanned_no_text", "blank_pages", "no_pages", "page_errors"],
)
def test_each_empty_reason_produces_its_own_line_under_a_no_text_label(
    reason: str,
) -> None:
    result = file_reader.FileReadResult(
        Path("doc.pdf"),
        "pdf",
        "",
        "doc.pdf",
        {"pdf_scan": {"empty_reason": reason, "pages_read": 1, "pages_total": 1, "image_pages": 0}},
    )
    note = file_reader.file_read_failure_note(result)
    assert note.startswith("[文件无文字：doc.pdf]"), "空文本族不许借用「读取失败」那顶帽子"
    assert file_reader.SCAN_EMPTY_SENTENCES[reason] in note
    assert f"empty_reason={reason}" in note, "技术事实行必须能核对到那一格归因代号"
    assert "页数=读了1/共1" in note and "含图页=" in note
    # 措辞面纪律：文件名可以出现，**绝对路径与盘符形态**不可以（解析器原文带路径）。
    assert "\\" not in note and "C:\\" not in note
    assert str(result.path.resolve()) not in note, "交回的是绝对路径而非 basename"


def test_unrecognised_empty_reason_stays_silent_instead_of_guessing() -> None:
    """认不出的归因代号＝不说。宁可少说一句，不许编一条归因（旧「不许瞎猜」初衷）。"""
    result = file_reader.FileReadResult(
        Path("doc.pdf"), "pdf", "", "doc.pdf", {"pdf_scan": {"empty_reason": "alien_state"}}
    )
    assert file_reader.file_read_failure_note(result) == ""


def test_a_pdf_that_actually_has_text_never_gets_a_failure_line(
    tmp_path: Path, reader_class: type[_FakeReader]
) -> None:
    reader_class.pages = [_page("这一页有字")]
    result = _READ_PDF(tmp_path / "ok.pdf", 1000, None)
    assert file_reader.file_read_failure_note(result) == ""


# ---------------------------------------------------------------------------
# ⑦ 注毒自证：证明上面那些尺真的在比句子，不是恒真
# ---------------------------------------------------------------------------


def test_poison_merging_two_states_is_caught_by_the_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒：把「扫描件」并成「空白页」（S-T-PDF-3 明令禁止的那种收敛）。

    摘掉守卫的方式＝就地改表，而不是改断言。两半都要断：
    ① ①里那枚「两两不同」的结构锁在中毒态下**必须失守**（否则它是恒真式）；
    ② 措辞面同样塌：人话主句那一段两态变得逐字相同——归因信息只剩技术行的代号，
       而那句话是要念进对话面给模型看的，「只有图像」与「确实空白」被洗成一格。
    还原后两半都复绿。
    """
    table = file_reader.SCAN_EMPTY_SENTENCES
    distinct_before = len({sentence for sentence in table.values()})
    assert distinct_before == 4, f"前提已破：现场只有 {distinct_before} 句不同的话"
    clause_before = (_plain_clause("scanned_no_text"), _plain_clause("blank_pages"))
    assert clause_before[0] != clause_before[1]

    monkeypatch.setitem(table, "scanned_no_text", table["blank_pages"])
    assert len({sentence for sentence in table.values()}) == 3, (
        "并了句子而结构锁仍数出四句＝①那把锁没在比句子，是恒真式"
    )
    assert _plain_clause("scanned_no_text") == _plain_clause("blank_pages"), (
        "两态的人话主句仍可分辨＝措辞出口没在吃这张表"
    )

    monkeypatch.undo()
    assert len({sentence for sentence in table.values()}) == 4
    assert _plain_clause("scanned_no_text") != _plain_clause("blank_pages")


def _plain_clause(reason: str) -> str:
    """取措辞出口里**给人看**的那半句（剥掉可核对技术行，技术行永远带代号）。"""
    note = file_reader.file_read_failure_note(_scan_result(reason))
    return note.split("技术事实（可核对）")[0]


def test_poison_dropping_the_page_count_line_is_caught(
    tmp_path: Path, reader_class: type[_FakeReader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒：把「共 N 页只读前 M 页」那行的触发条件改成立即返回。

    ④ 那把锁读的是 result.text；本发证明「这一行确实由这段代码产生」——把
    ``scan_max_pages`` 的解析改成「不设上限」，句子就消失，④当场会红。
    """
    reader_class.pages = [_page(f"第{i}页") for i in range(4)]
    normal = _READ_PDF(tmp_path / "cap.pdf", 1000, 2)
    assert "只读了前 2 页" in normal.text

    monkeypatch.setattr(file_reader, "PDF_SCAN_MAX_PAGES", 10_000)
    uncapped = _READ_PDF(tmp_path / "cap2.pdf", 1000, 0)  # 0＝非法值⇒回落缺省（现被顶高）
    assert "只读了前" not in uncapped.text, "顶高缺省后仍截断＝这一行不是由那枚常量决定的"
    assert _scan_of(uncapped)["pages_read"] == 4


def _scan_result(reason: str) -> file_reader.FileReadResult:
    return file_reader.FileReadResult(
        Path("doc.pdf"),
        "pdf",
        "",
        "doc.pdf",
        {
            "pdf_scan": {
                "empty_reason": reason,
                "pages_read": 3,
                "pages_total": 3,
                "image_pages": 1 if reason == "scanned_no_text" else 0,
            }
        },
    )
