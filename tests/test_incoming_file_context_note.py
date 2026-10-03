"""``build_incoming_file_context_note``（文件链路波供件）的回归锁。

锁五件事：

① 成功路：注记 = 元数据头（文件名/类型/可读性）+ ``labelled_text`` 咽喉产出的
   T2 打标正文——「外部资料」前导行必须在场（证明正文过了打标咽喉，不是裸文）；
② ``original_name`` 是给人看的名字：落盘临时件名不得出现在注记里；
③ 读不动 = 诚实句：措辞逐字来自 ``file_read_failure_note`` 唯一真身
   （PARSE_STATUS_SENTENCES / KIND_SILENCE_SENTENCES 同族），且**不许**出现
   T2 正文前导行（给一句没读到的东西打来源标 = 把「没读」写成「读到了」）；
④ 读到了但没字（空文件）＝可核对的事实句，不猜内容；
⑤ 供件自身 fail-honest：目录路径/不存在路径都拿得到句子，绝不抛。

全部离线：样本用 ``tmp_path`` 现造，不依赖任何 fixture 文件。
"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
    build_incoming_file_context_note,
)

_T2_LEAD_MARK = "外部资料"


def test_supported_text_file_gets_t2_labelled_note(tmp_path: Path):
    file = tmp_path / "1700000000000_笔记.txt"
    file.write_text("第一行内容\n第二行内容\n", encoding="utf-8")
    note = build_incoming_file_context_note(file, original_name="笔记.txt")
    assert note.startswith("[入站文件：笔记.txt")
    assert "类型：文本" in note
    assert "已读取正文" in note
    assert "第一行内容" in note
    assert _T2_LEAD_MARK in note, "正文没过 T2 打标咽喉（缺「外部资料」前导行）"


def test_original_name_wins_over_temp_file_name(tmp_path: Path):
    file = tmp_path / "1700000000001_tmpfile.md"
    file.write_text("# 标题\n", encoding="utf-8")
    note = build_incoming_file_context_note(file, original_name="真名.md")
    assert "真名.md" in note
    assert "tmpfile.md" not in note, "落盘临时件名漏进了注记"


def test_missing_file_gets_honest_sentence_without_t2_lead(tmp_path: Path):
    note = build_incoming_file_context_note(
        tmp_path / "nope.txt", original_name="失踪.txt"
    )
    assert "失踪.txt" in note
    assert "文件已不在原处" in note
    assert _T2_LEAD_MARK not in note, "没读到的东西不该有正文来源标注"


def test_unsupported_extension_gets_no_channel_sentence(tmp_path: Path):
    file = tmp_path / "1700000000002_程序.exe"
    file.write_bytes(b"MZ\x90\x00")
    note = build_incoming_file_context_note(file, original_name="程序.exe")
    assert "没有读取通道" in note
    assert _T2_LEAD_MARK not in note


def test_corrupt_docx_gets_parse_failed_sentence(tmp_path: Path):
    file = tmp_path / "1700000000003_伪.docx"
    file.write_bytes(b"this is not a zip container at all........")
    note = build_incoming_file_context_note(file, original_name="伪.docx")
    assert "文件损坏或格式与后缀不符" in note
    assert _T2_LEAD_MARK not in note


def test_legacy_xls_gets_parser_unavailable_sentence(tmp_path: Path):
    file = tmp_path / "1700000000004_旧表.xls"
    file.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    note = build_incoming_file_context_note(file, original_name="旧表.xls")
    assert "无可用解析器" in note
    assert _T2_LEAD_MARK not in note


def test_blank_text_file_states_the_fact_without_guessing(tmp_path: Path):
    file = tmp_path / "1700000000005_空.txt"
    file.write_text("", encoding="utf-8")
    note = build_incoming_file_context_note(file, original_name="空.txt")
    assert "没有读出任何文字内容" in note
    assert _T2_LEAD_MARK not in note, "零字正文不该打正文标注"


def test_truncation_is_declared_not_silent(tmp_path: Path):
    file = tmp_path / "1700000000006_长文.txt"
    file.write_text("字" * 5000, encoding="utf-8")
    note = build_incoming_file_context_note(
        file, original_name="长文.txt", max_chars=200
    )
    assert "只读取了文件开头约 200 字符" in note, "截断不许静默（不变量③）"
    assert "已读取正文（本注记最多收录约 200 字符）" in note


def test_directory_path_never_raises(tmp_path: Path):
    note = build_incoming_file_context_note(tmp_path, original_name="目录.txt")
    assert isinstance(note, str) and note.strip()
    assert "文件已不在原处" in note


def test_never_raises_on_null_bytes_binary_txt(tmp_path: Path):
    file = tmp_path / "1700000000007_二进制.txt"
    file.write_bytes(b"\x00\x01\x02\x00" * 64)
    note = build_incoming_file_context_note(file, original_name="二进制.txt")
    assert isinstance(note, str) and note.strip()
    assert "没有读出任何文字内容" in note
