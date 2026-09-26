"""S-PDF-2 活性锁：真实入站路径上「没读到」必须两态分别产出，绝不静默。

为什么单独一件测试（2026-09-26，需求 16 续波）：上一波（S-PDF-1）把坏 PDF 与
缺 pypdf 在 ``read_supported_file`` 里分成了 ``parse_failed``/``parser_unavailable``
两态，但那套措辞当时**只住在中央 ``files.read.*`` handler 里，而该 handler 生产
零调用点**——真实入站归一（根 ``__init__.py::_incoming_from_nonebot_event``）只吃
``parsed_file.text``，两态到了用户面前都坍缩成同一件事：**静默**。闸建好了，
消息进不了这道闸。

本件钉三件事：
① 走**真实入站链**（``_incoming_from_nonebot_event`` + 真身 ``read_supported_file``，
   不 mock 解析器本体）投一发损坏 PDF 与一发「解析器不可用」，断言两态分别产出
   不同的人话、且都产出内容（非空消息，禁静默）；
② 中央 handler 与入站归一吃**同一张措辞表**（``PARSE_STATUS_SENTENCES`` 单一真身），
   断言 detail 里出现的句子逐字等于表值——把两态合并成一态，①②当场全红；
③ 注入行只带文件名/状态代号/归类短语，**不带绝对路径**（出站前还有
   ``redact_local_secrets``，本锁验的是构造侧就不上路径）。

全离线：临时文件写 ``tmp_path``，零网络、零消息发送；``sys.modules`` 注 None 模拟
「pypdf 未装」由 monkeypatch 自动还原。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.domains.files.sources import file_reader
from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
    PARSE_STATUS_SENTENCES,
    file_read_failure_note,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CapabilityRequest,
    InvocationStatus,
    default_invoker,
)

# 两态各自独有的判据词（并态即互含 ⇒ 红）。
_DAMAGE_MARKER = "损坏"
_NO_PARSER_MARKER = "无可用解析器"


def _corrupt_pdf(directory: Path) -> Path:
    """自造的损坏 PDF：只有头与 trailer，无页对象无 xref（几十字节垃圾）。"""
    target = directory / "broken-report.pdf"
    target.write_bytes(b"%PDF-1.4\ntrailer\n%%EOF\n")
    return target


class _FileEvent:
    """最小 NoneBot 事件替身（形态照抄 test_runtime_subfeatures 的入站 harness）。"""

    group_id = None
    message_id = "m-spdf2"
    sender = SimpleNamespace(nickname="tester")

    def __init__(self, text: str) -> None:
        self._text = text

    def get_plaintext(self) -> str:
        return self._text

    def get_session_id(self) -> str:
        return "private_u"

    def get_user_id(self) -> str:
        return "u"

    def is_tome(self) -> bool:
        return True


def _ingress_text(tmp_path: Path, target: Path, *, text: str = "这份文档讲了什么") -> str:
    """走**真实入站归一**：文件段 → read_supported_file 真身 → IncomingMessage。

    用户原话以 text 段入参：``get_plaintext()`` 会被段归一产出的 plain_text 顶掉
    （纯 file 段归一成 ``[文件]``），照真实事件形态带 text 段才是正形。
    """
    segments: list[dict[str, Any]] = []
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    segments.append({"type": "file", "data": {"file": str(target)}})
    message = _incoming_from_nonebot_event(
        _FileEvent(text),
        bot_id="b",
        segments=segments,
        reply_chain=[],
    )
    return str(message.plain_text)


def _request(capability_id: str, payload: dict[str, Any]) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        payload=payload,
        principal="tester",
        roles=("user",),
        context={},
    )


# ==================== ① 真实入站链：两态分别产出、都不许静默 ====================


def test_corrupt_pdf_inbound_says_damage_not_missing_parser(tmp_path: Path) -> None:
    """损坏 PDF 进真实入站链 → 对话面拿到「损坏」那句，且不带缺解析器归因。"""
    plain = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
    assert "[文件读取失败：broken-report.pdf]" in plain
    assert _DAMAGE_MARKER in plain
    assert "status=parse_failed" in plain
    # 互斥：损坏文件绝不能被归因成「环境没装东西」（那是让用户查一个不存在的洞）。
    assert _NO_PARSER_MARKER not in plain
    # 用户原话仍在（注入是追加，不是顶掉）。
    assert "这份文档讲了什么" in plain


def test_missing_parser_inbound_says_unavailable_not_damage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pypdf 导不进来（sys.modules 置 None 即 ImportError）→ 换另一句，且指到缺件。"""
    monkeypatch.setitem(sys.modules, "pypdf", None)  # type: ignore[arg-type]
    plain = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
    assert "[文件读取失败：broken-report.pdf]" in plain
    assert _NO_PARSER_MARKER in plain
    assert "pypdf" in plain  # 可核对技术事实：缺的就是这一枚
    assert "status=parser_unavailable" in plain
    # 互斥：环境缺件不能被说成「文件坏了」（用户会去重发同一份文件）。
    assert _DAMAGE_MARKER not in plain


def test_two_states_produce_different_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一份坏字节，两态必须给出**不同**的一行；两态合并即红。"""
    damaged = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
    monkeypatch.setitem(sys.modules, "pypdf", None)  # type: ignore[arg-type]
    unavailable = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
    assert damaged != unavailable
    assert _DAMAGE_MARKER in damaged and _NO_PARSER_MARKER not in damaged
    assert _NO_PARSER_MARKER in unavailable and _DAMAGE_MARKER not in unavailable


def test_degraded_file_alone_is_never_an_empty_message(tmp_path: Path) -> None:
    """只发文件不发话，也不能拿到空消息——「静默」就是本波立项的那条缺陷。"""
    plain = _ingress_text(tmp_path, _corrupt_pdf(tmp_path), text="")
    assert plain.strip()
    assert "[文件读取失败" in plain
    # 也不许被顶成图片/语音那族占位文案（文件段不是视觉/音频段）。
    assert "用户发送了" not in plain


def test_valid_file_inbound_reads_content_and_stays_silent_about_failure(
    tmp_path: Path,
) -> None:
    """正腿防过度修正：读成功必须走 [文件内容]，不得混进失败行。"""
    docx_module = pytest.importorskip("docx")
    target = tmp_path / "notes.docx"
    document = docx_module.Document()
    document.add_paragraph("泰缇斯系统第二实例")
    document.save(str(target))
    plain = _ingress_text(tmp_path, target)
    assert "[文件内容：notes.docx]" in plain
    assert "泰缇斯系统第二实例" in plain
    assert "[文件读取失败" not in plain


# ==================== ② 单一真身：入站与中央 handler 吃同一张表 ====================


def test_sentence_table_is_exactly_the_two_states() -> None:
    """措辞表就是这套状态码的**契约**：每态一句、彼此不同、不许有空串。

    2026-09-26 追加第三态 ``internal_parse_error``（S-16-PDF-EXC-SURFACE 修法乙：
    未枚举异常在公共口收敛成一态）。它是"我们的程序出错"这一归因，**不许**并进
    ``parse_failed``（那等于把责任记到她的文件上），也不许并进
    ``parser_unavailable``（那等于谎称环境缺件）。本锁的原意——"两态合并成一态
    必红"——在扩表后同样成立，故判据从"两态互不相等"升为"全表逐对不相等 +
    每态都真有一句话"，比旧写更严。
    """
    assert set(PARSE_STATUS_SENTENCES) == {
        "parse_failed",
        "parser_unavailable",
        "internal_parse_error",
    }
    sentences = list(PARSE_STATUS_SENTENCES.values())
    assert len(set(sentences)) == len(sentences), "两态共用一句＝归因被洗掉了"
    for status, sentence in PARSE_STATUS_SENTENCES.items():
        assert sentence.strip(), f"{status} 没有句子（表外返回空串＝静默吞）"
        assert file_reader.parse_status_sentence(status) == sentence, "取句口与表不同源"


def test_inbound_note_lines_quote_the_shared_table_verbatim(tmp_path: Path) -> None:
    """入站注入行必须**逐字**含表值——handler 与入站各写一套文案即两真身，必拆。"""
    damaged = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
    assert PARSE_STATUS_SENTENCES["parse_failed"] in damaged


def test_central_handler_detail_quotes_the_shared_table(
    tmp_path: Path,
) -> None:
    """中央 files.read.pdf（协议面）的降级 detail 同样只准引用这张表。"""
    result = default_invoker().invoke(
        _request("files.read.pdf", {"path": str(_corrupt_pdf(tmp_path))})
    )
    assert result.status is InvocationStatus.DEGRADED
    assert PARSE_STATUS_SENTENCES["parse_failed"] in result.detail
    assert "parse_failed" in result.detail


def test_central_handler_unavailable_quotes_the_shared_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)  # type: ignore[arg-type]
    result = default_invoker().invoke(
        _request("files.read.pdf", {"path": str(_corrupt_pdf(tmp_path))})
    )
    assert result.status is InvocationStatus.DEGRADED
    assert PARSE_STATUS_SENTENCES["parser_unavailable"] in result.detail
    assert "parser_unavailable" in result.detail
    assert PARSE_STATUS_SENTENCES["parse_failed"] not in result.detail


# ==================== ③ 卫生：注入行不带绝对路径，可核对事实齐全 ====================


def test_failure_note_carries_no_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for unavailable in (False, True):
        if unavailable:
            monkeypatch.setitem(sys.modules, "pypdf", None)  # type: ignore[arg-type]
        plain = _ingress_text(tmp_path, _corrupt_pdf(tmp_path))
        assert str(tmp_path) not in plain
        assert not re.search(r"[A-Za-z]:[\\/]", plain), plain
        assert "\\" not in plain  # Windows 分隔符根本不该出现（只上文件名）
        assert "broken-report.pdf" in plain


def test_note_helper_returns_empty_for_non_degraded_results(tmp_path: Path) -> None:
    """受支持类型「读到但空/读到有内容」不产失败行——归因不许瞎猜。

    ⚠ 2026-09-26 S-FILES-LAND（需求 16(1) 读诚实化第三格，主裁定）把原判定里
    ``missing`` / 不支持扩展名（落 ``kind="unknown"``）两半**改判**成要开口：沉默
    ＝会话面一个字都不说，用户不知道文件被吞了。原判定理由留档（回滚点＝把下方
    两条非空断言改回 == "" 并同步 file_read_failure_note 的 kind 分支）：
    「missing/unknown/读成功（含『读到但没字』）都不产失败行——归因不许瞎猜」。
    新措辞不猜内容，只陈述 kind 这个已在结果对象上的事实（没有读取通道 / 文件
    不在原处），与「不许瞎猜」初衷不相违背；锁在
    ``tests/test_files_domain_audit.py::test_unsupported_or_missing_file_still_gets_a_plain_sentence``。
    """
    # 消失的文件：现在要说「读不了 + 为什么」（旧断言 == ""，已按主裁定改判）。
    missing = file_reader.read_supported_file(tmp_path / "nope.pdf")
    assert file_read_failure_note(missing)
    # 不支持的扩展名（.bin 落 kind=unknown）：同族改判（旧断言 == ""）。
    blank = tmp_path / "empty.bin"
    blank.write_bytes(b"\x00\x01\x02")
    assert file_read_failure_note(file_reader.read_supported_file(blank))
    # 真正「读到了东西」的成功路径保持沉默——这一半是原判定没被推翻的那条腿。
    txt = tmp_path / "a.txt"
    txt.write_text("hello", encoding="utf-8")
    assert file_read_failure_note(file_reader.read_supported_file(txt)) == ""
