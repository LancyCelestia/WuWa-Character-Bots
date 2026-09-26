"""文件收发能力：受限 debug 运行器 + Markdown 多格式导出。"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.domains.files.capabilities.file_exchange import (
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


def test_run_code_debug_does_not_execute_by_default(tmp_path: Path) -> None:
    """缺省不跑——止血锁（SAFE-EXEC Wave 1·P-1 甲）。

    副作用探针：脚本自己写一个标记文件。缺省调用后标记**不得出现**，
    报告里必须是静态摘要 + 明说本轮未执行。
    """
    marker = tmp_path / "did_run.marker"
    source = f"open(r'{marker}', 'w').write('ran')\nprint('hello')\n"
    path = _write(tmp_path, "ok.py", source)
    report = run_code_debug(path)
    assert not marker.exists(), "缺省路径仍然执行了上传代码"
    assert "语法检查通过" in report and "本轮未执行" in report
    assert "运行成功" not in report


def test_run_code_debug_structure_summary_names_defs_and_imports(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "shape.py",
        "import json\nfrom pathlib import Path\n\n"
        "def load(p):\n    return json.loads(Path(p).read_text())\n\n\nclass Box: pass\n",
    )
    report = run_code_debug(path)
    assert "函数 load" in report and "类 Box" in report
    assert "json" in report and "pathlib" in report


def test_run_code_debug_can_execute_when_explicitly_allowed(tmp_path: Path) -> None:
    """执行能力没被删掉，只是不再默认开——Wave 2 由统一引擎在拿到书面同意后显式放行。"""
    good = _write(tmp_path, "ok.py", "print('hello')\n")
    assert "运行成功" in run_code_debug(good, execute=True)
    failing = _write(tmp_path, "fail.py", "raise ValueError('boom')\n")
    report = run_code_debug(failing, execute=True)
    assert "运行失败" in report and "ValueError" in report


def test_production_call_site_never_passes_execute_true() -> None:
    """装配面（根 __init__.py）只准走缺省；谁把它写成 execute=True 谁就得先过规格评审。"""
    import ast

    root = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/__init__.py"
    )
    tree = ast.parse(root.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "run_code_debug":
                continue
            for keyword in node.keywords:
                if keyword.arg == "execute" and getattr(keyword.value, "value", None) is True:
                    offenders.append(node.lineno)
    assert not offenders, f"根文件里出现显式放行执行：行 {offenders}"


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
