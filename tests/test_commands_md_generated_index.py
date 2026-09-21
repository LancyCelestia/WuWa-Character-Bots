"""IGEN2-①：COMMANDS.md「模块索引」段自动生成投影 + 内容覆盖门（全离线）。

背景（spec-audit SA2-01 / SA2-06 / SA8-09、SYNC1 缺口1）：
- ``_HELP_ENTRIES`` → ``docs/command-catalog.md`` 已由 ``scripts/command_catalog.py`` 生成、
  ``--check`` 恒绿；``/bot help`` 运行态直接读同一注册表（D 档）；三面里唯一会漂移的
  腿是**人读版** ``COMMANDS.md``——既有门
  ``test_documentation_consistency.py::test_commands_md_defers_counts_to_generated_catalog``
  只断言「含 catalog 指针 + 不手写会过期的总数」，**不核对逐条命令**，SA2 实测 10 个
  topic 全文零出现（商品行情/国债收益率/北向资金/媒体归档/群信息/笔记/收件箱/戳一戳/
  表情收库/忽略），「与 /bot help 同口径」的宣称被静默击穿。

落地形态（取舍见 impl-IGEN2-log.md）：**半生成**——COMMANDS.md 的策展表格/叙述段
是人写编辑价值（按管理员/子功能/运行开关分组、逐条关键参数），整表全量生成会牺牲
人读质量、且会把 command-catalog.md 的明细复制成第二事实源（正是 HELP-1 归一在治的
病，越界）。故只把**逐 topic 覆盖**这一机械可生成部分做成 marker 括起的自动生成投影块
（topic + 权限 + 能力入口，零参数明细），本门把该块与 ``_HELP_ENTRIES`` 的投影做**字节
级双向比对**：块内容 ≠ 投影即红；新增/改名 topic 若不同步 COMMANDS.md，投影与文件块立刻
不匹配（覆盖漂移从「静默」变「必红」）。

同源纪律：只 ``import`` ``command_catalog.merged_entries`` 这一个取数函数（合并 echo
``_HELP_ENTRIES`` × META × EXTRA 的唯一投影入口），**不改那个脚本、不 import 插件包**
（离线、与脚本同口径）。投影行格式若被改，本文件与 COMMANDS.md 内的块必须同步重录
（否则门红），杜绝生成器与文件各持一套渲染。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.command_catalog import merged_entries  # 只取数，不改脚本。

COMMANDS_MD = PROJECT_ROOT / "COMMANDS.md"

BEGIN_MARKER = (
    "<!-- BEGIN AUTO:COMMANDS-MODULE-INDEX generated-from=_HELP_ENTRIES "
    "by tests/test_commands_md_generated_index.py; 请勿手改本块 -->"
)
END_MARKER = "<!-- END AUTO:COMMANDS-MODULE-INDEX -->"

# COMMANDS.md 里 marker 括起块的渲染真源——改这里即须同步重录文件内块（门红逼同步）。
_INDEX_HEADING = "## 模块索引（自动生成 · 逐 topic 覆盖）"
_INDEX_NOTE = (
    "> 本节由 `tests/test_commands_md_generated_index.py` 从 `echo.py` 的 `_HELP_ENTRIES` 自动投影，",
    "> 逐模块列出 topic 与权限，机械保证 COMMANDS.md 覆盖帮助注册表全部主题；",
    "> 参数、别名与触发词明细以 [docs/command-catalog.md](docs/command-catalog.md) 与 `/bot help <模块>` 为准，不在此手写。",
)


def _topic_line(entry: dict[str, object]) -> str:
    topic = str(entry.get("topic") or "")
    access = "仅管理员" if entry.get("admin_only") else "普通用户可用"
    capability = str(entry.get("capability") or "").strip()
    line = f"- {topic}（{access}）"
    if capability:
        line += f"：{capability}"
    return line


def render_index_lines(entries: list[dict[str, object]]) -> list[str]:
    """从投影后的 ``_HELP_ENTRIES`` 生成索引块的**内容行**（去首尾空行的规范化形态）。"""
    out: list[str] = [_INDEX_HEADING, ""]
    out.extend(_INDEX_NOTE)
    out.append("")
    out.extend(_topic_line(entry) for entry in entries)
    return out


def extract_index_block(text: str) -> list[str]:
    """取 COMMANDS.md 中 BEGIN/END marker 之间的内容行（剥离首尾空行，规范化比对）。"""
    if BEGIN_MARKER not in text or END_MARKER not in text:
        raise AssertionError(
            "COMMANDS.md 缺自动生成的模块索引 marker 块"
            f"（应含 {BEGIN_MARKER[:32]}… 与 {END_MARKER}）——本门失效即红，"
            "须由维护者重录投影块，不得删块凑绿。"
        )
    head, sep, tail = text.partition(BEGIN_MARKER)
    if not sep:
        raise AssertionError("marker 起始后无内容")
    body, end_sep, _rest = tail.partition(END_MARKER)
    if not end_sep:
        raise AssertionError("marker 块未闭合（缺 END）")
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _diff(expected: list[str], actual: list[str]) -> list[str]:
    problems: list[str] = []
    if len(expected) != len(actual):
        problems.append(f"行数不同：投影 {len(expected)} vs 文件 {len(actual)}")
    for index in range(min(len(expected), len(actual))):
        if expected[index] != actual[index]:
            problems.append(
                f"第 {index} 行不一致：投影={expected[index]!r} 文件={actual[index]!r}"
            )
            if len(problems) >= 8:
                break
    return problems


def test_commands_md_index_matches_help_entries_projection() -> None:
    """主断言：COMMANDS.md 索引块必须逐字节等于 ``_HELP_ENTRIES`` 投影（漂移→红）。"""
    text = COMMANDS_MD.read_text(encoding="utf-8")
    expected = render_index_lines(merged_entries())
    actual = extract_index_block(text)
    problems = _diff(expected, actual)
    assert not problems, (
        "COMMANDS.md 自动索引块与 _HELP_ENTRIES 投影漂移（改帮助注册表未同步 COMMANDS.md）："
        + "；".join(problems)
    )


def test_generated_index_covers_every_help_topic() -> None:
    """弱命题兜底：每个 _HELP topic 至少各出现一次（独立于字节相等的第二重覆盖锁）。"""
    text = COMMANDS_MD.read_text(encoding="utf-8")
    actual = extract_index_block(text)
    body = "\n".join(actual)
    missing = [
        str(entry.get("topic"))
        for entry in merged_entries()
        if entry.get("topic")
        and f"- {entry.get('topic')}（" not in body
    ]
    assert not missing, f"COMMANDS.md 索引块漏 topic：{missing}"


def test_generated_index_has_no_hardcoded_counts() -> None:
    """保护兄弟门不变量：索引块内不得出现会过期的「N个模块/N别名」计数。"""
    text = COMMANDS_MD.read_text(encoding="utf-8")
    body = "\n".join(extract_index_block(text))
    hits = re.findall(r"\d+\s*(?:个)?(?:模块|别名)", body)
    assert not hits, f"自动索引块手写了会过期的总数：{hits}"


# ---------------------------------------------------------------------------
# 可红性（变异测试）：把真相源/文件改坏 → 门必须红（内存内，绝不写盘）。
# ---------------------------------------------------------------------------


def test_mutation_dropping_topic_from_registry_breaks_match() -> None:
    """真相源少一条 topic（模拟「新能力未同步进 COMMANDS.md」）→ 字节比对必须红。"""
    entries = merged_entries()
    mutated = [e for e in entries if str(e.get("topic")) != "随机图"]
    assert len(mutated) == len(entries) - 1, "变异前提失效：随机图 本不在注册表"
    text = COMMANDS_MD.read_text(encoding="utf-8")
    actual = extract_index_block(text)
    problems = _diff(render_index_lines(mutated), actual)
    assert problems, "门失效：注册表少一条 topic 却仍判定 COMMANDS.md 索引块一致（永真摆设）"


def test_mutation_stale_index_line_is_detected() -> None:
    """COMMANDS.md 块与投影不一致（模拟人改坏块内一行）→ 比对必须红。

    在内存内取真实块、把「Epic」那行的权限注记改错，验证 _diff 抓到漂移；
    不写回文件、不改动真实 COMMANDS.md。
    """
    text = COMMANDS_MD.read_text(encoding="utf-8")
    lines = extract_index_block(text)
    stale = [ln for ln in lines if ln.startswith("- Epic")]
    assert stale, "变异前提失效：Epic topic 不在块内"
    tampered = [ln.replace("（普通用户可用）", "（仅管理员）") for ln in lines]
    assert tampered != lines
    problems = _diff(render_index_lines(merged_entries()), tampered)
    assert problems, "门失效：块内容被改坏却未报漂移（永真摆设）"


def test_missing_marker_block_is_fatal() -> None:
    """marker 块整段缺失 → extract 直接抛错（门不许被「删块」静默绕过）。"""
    with pytest.raises(AssertionError):
        extract_index_block("# 无索引块的文件\n\n正文\n")

