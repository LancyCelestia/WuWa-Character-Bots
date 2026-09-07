"""文件收发能力：受限 debug 运行器 + Markdown 多格式导出。"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.capabilities.file_exchange import (
    export_document,
    parse_file_export_command,
    parse_markdown_blocks,
    run_code_debug,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_run_code_debug_reports_syntax_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    report = run_code_debug(path)
    assert "语法错误" in report


def test_run_code_debug_runs_and_reports_traceback(tmp_path: Path) -> None:
    good = _write(tmp_path, "ok.py", "print('hello')\n")
    assert "运行成功" in run_code_debug(good)
    failing = _write(tmp_path, "fail.py", "raise ValueError('boom')\n")
    report = run_code_debug(failing)
    assert "运行失败" in report
    assert "ValueError" in report


def test_run_code_debug_reports_text_files(tmp_path: Path) -> None:
    path = _write(tmp_path, "note.md", "# 标题\n内容\n")
    report = run_code_debug(path)
    assert "已接收" in report


def test_markdown_block_parser() -> None:
    markdown = (
        "# 标题\n\n- 要点一\n- 要点二\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "正文段落\n```py\nprint(1)\n```\n"
    )
    blocks = parse_markdown_blocks(markdown)
    kinds = [block.kind for block in blocks]
    assert kinds == ["heading", "bullet", "bullet", "table", "para", "code"]
    assert blocks[3].rows == [["a", "b"], ["1", "2"]]


def test_export_all_formats(tmp_path: Path) -> None:
    markdown = (
        "# 报告\n\n## 数据\n\n| 名称 | 值 |\n|---|---|\n| x | 1 |\n\n- 要点\n\n正文。\n"
    )
    for fmt in ("md", "docx", "xlsx", "pptx", "pdf"):
        path, error = export_document(markdown, fmt, tmp_path, title="测试报告")
        assert error == "", f"{fmt}: {error}"
        assert path.exists() and path.stat().st_size > 0


def test_export_command_parsing() -> None:
    assert parse_file_export_command("/bot 文件 docx 项目周报：含表格") == (
        "docx",
        "项目周报：含表格",
    )
    assert parse_file_export_command("文件 md 主题") == ("md", "主题")
    assert parse_file_export_command("文件 markdown 主题") == ("md", "主题")
    assert parse_file_export_command("文件 docx") is None
    assert parse_file_export_command("文件 exe 主题") is None
