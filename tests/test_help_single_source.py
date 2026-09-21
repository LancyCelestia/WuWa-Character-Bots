"""HELP-1 帮助文案单一事实源锁（2026-09-20）。

钉死的事实：
1. `lines[]` 是命令行文案的唯一事实源，`detail` 的【指令与参数】段**逐字等于**由 lines 派生的结果；
2. 派生是真派生（负向锁：改 lines，派生段随之变；叙述小节不受影响）；
3. `detail` 字面量里**不许再有手写**的【指令与参数】段（AST 直读源码，防"派生其实写死"）；
4. `/bot help <模块>` 深页只印 lines 这一份（旧缺陷=同一命令讲两遍且两份已漂移，
   见 docs/design/link-unification-audit-20260920.md §B-1）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.echo import (
    HELP_ENTRIES,
    _derive_help_command_section,
    _strip_help_command_section,
    build_help_result,
    normalize_help_topic,
)

ECHO_SOURCE = Path("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py")
SECTION_RE = re.compile(r"【指令与参数】\n.*?(?=^【|\Z)", re.MULTILINE | re.DOTALL)


def _lines_of(entry: Any) -> list[str]:
    return [str(line) for line in entry.get("lines", [])]


def _source_entry_literals() -> list[Any]:
    """AST 静态读 _HELP_ENTRIES 字面量（与 scripts/command_catalog.py 同口径，不取运行期合并结果）。"""
    tree = ast.parse(ECHO_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_HELP_ENTRIES":
                value = ast.literal_eval(node.value)
                assert isinstance(value, list)
                return value
    raise AssertionError("_HELP_ENTRIES 未找到")


def test_command_section_equals_lines_derivation() -> None:
    """锁 1：detail 的【指令与参数】段 == 由 lines[] 派生的结果（逐主题、逐字节）。"""
    for entry in HELP_ENTRIES:
        detail = str(entry.get("detail") or "")
        match = SECTION_RE.search(detail)
        assert match is not None, f"{entry['topic']} 的 detail 缺【指令与参数】段"
        assert match.group(0) == _derive_help_command_section(_lines_of(entry)), (
            f"{entry['topic']}：detail 命令行段与 lines 派生结果不一致"
        )


def test_derivation_really_tracks_lines() -> None:
    """锁 2（负向）：往 lines 注入一行，派生段随之变化，叙述小节分毫不动。"""
    probe = "/bot __help_probe__：作用=探针；参数=无；内容=无；意义=防写死。"
    for entry in HELP_ENTRIES:
        detail = str(entry.get("detail") or "")
        narrative = _strip_help_command_section(detail)
        base = _derive_help_command_section(_lines_of(entry))
        varied = _derive_help_command_section([*_lines_of(entry), probe])
        assert probe in varied and probe not in base, f"{entry['topic']}：派生未跟随 lines"
        assert varied != base, f"{entry['topic']}：派生结果恒定，疑似写死"
        assert "【指令与参数】" not in narrative, f"{entry['topic']}：叙述小节里仍有手写指令段"


def test_no_handwritten_command_section_in_source() -> None:
    """锁 3：源码字面量里不存在手写【指令与参数】段（结构层面钉死，防有人又手写回去）。"""
    literals = _source_entry_literals()
    assert literals, "源码字面量为空"
    for entry in literals:
        literal_detail = str(entry.get("detail") or "")
        assert "【指令与参数】" not in literal_detail, (
            f"{entry['topic']}：detail 字面量又手写了【指令与参数】，单一事实源被破坏"
        )
    for entry in HELP_ENTRIES:
        assert str(entry.get("detail") or "").count("【指令与参数】") == 1, (
            f"{entry['topic']}：派生段数量异常"
        )


def test_narrative_sections_survive_composition() -> None:
    """归一不许删信息：叙述小节（板块介绍/取值范围/权限与效果/示例）仍逐主题在场。"""
    for entry in HELP_ENTRIES:
        narrative = _strip_help_command_section(str(entry.get("detail") or ""))
        assert "【权限与效果】" in narrative, f"{entry['topic']}：权限与效果小节丢失"
        assert narrative.strip(), f"{entry['topic']}：叙述小节被清空"
        assert str(entry.get("index") or "").strip() and _lines_of(entry), f"{entry['topic']}：主干字段被啃掉"


@pytest.mark.parametrize("topic", [str(entry["topic"]) for entry in HELP_ENTRIES])
def test_deep_page_prints_lines_once(topic: str) -> None:
    """锁 4（面客面）：深页只印 lines 这一份，派生段不再被追加。"""
    if normalize_help_topic(topic) != topic:
        # 主题名被更靠前的分类/别名截获（如 媒体归档），走的是分类页；本锁只钉深页。
        pytest.skip(f"{topic} 的规范查询名不等于主题名，非深页路径")
    body = build_help_result(request_id="help-1", query=topic, is_admin=True).body
    assert "【指令与参数】" not in body, f"{topic}：派生段又被追加进深页（等于把同一命令讲两遍）"
    # 标题行与四要素的深页面已由 tests/test_help_deep_teaching_n2re.py:40/:53/:234 常驻钉住，
    # 本锁只管"不多印一份"，避免与既有门重复计账。
    assert body.strip(), f"{topic}：深页空输出"


@pytest.mark.parametrize(
    ("topic", "kept", "absent"),
    [
        # 审计 §B-1 点名的三处漂移：归一后深页只说采择的那一份。
        ("状态", "内容=软暂停状态", "多行状态清单（详见下方效果）"),
        ("功能管理", "修改仅限超管", "意义=受控调整功能，已运行任务不强杀。"),
        ("回执", "可从 /bot recent 的输出里取", "内容=回执状态与关键时间点"),
    ],
)
def test_documented_drift_cases_carry_one_copy_only(topic: str, kept: str, absent: str) -> None:
    """锁 4b：三处实证漂移在深页里只剩一份，且是采 lines（并按代码折并）的那份。"""
    body = build_help_result(request_id="help-1", query=topic, is_admin=True).body
    assert kept in body, f"{topic}：采择说法未进深页"
    assert absent not in body, f"{topic}：被弃说法仍在深页（两份并存）"
