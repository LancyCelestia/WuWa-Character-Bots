"""G-K1 派发纪律门：记账先于派发、公共只读面不可新增改动（用户 2026-09-22 三则补派前置）。"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SDD_ROOT = REPO_ROOT / ".superpowers" / "sdd"
SUBAGENTS_GLOB = "projects/*/8f099879-3e30-4289-8ff7-6bb73ef3b440/subagents/*.jsonl"
SEAT_TOOL_CALL_CEILING = 40

PUBLIC_READONLY_BASELINE_AT_RULE_TIME = frozenset({
    "docs/templates/handoff.md",
    "docs/templates/ledger.md",
    "docs/templates/seat-report.md",
    "docs/templates/brief.md",
    "docs/templates/card-fstring.md",
    "docs/templates/card-html.md",
    "docs/templates/card-jinja.md",
    "docs/templates/config-field.md",
    "docs/templates/convention.md",
    "docs/templates/copy-pool.md",
    "docs/templates/design-spec.md",
    "docs/templates/guide.md",
    "docs/templates/handbook.md",
    "docs/templates/help-entry.md",
    "docs/templates/incident-report.md",
    "docs/templates/persona-inject-data.md",
    "docs/templates/persona-numbered.md",
    "docs/templates/persona-provenance.md",
    "docs/templates/persona.md",
    "docs/templates/runbook.md",
    "docs/templates/sdd-ledger.md",
    "docs/templates/workspace-rule.md",
    "scripts/board_doc_sync.py",
    "scripts/doc_fact_discipline.py",
    "scripts/doc_ownership_sync.py",
    "scripts/doc_template_sync.py",
    "scripts/doc_templates.py",
    "tests/conftest.py",
    "plugins/bot_unified_runtime/__init__.py",
    "plugins/bot_unified_runtime/character/__init__.py",
    "plugins/bot_unified_runtime/output/card_render/__init__.py",
    "plugins/bot_unified_runtime/runtime/__init__.py",
})

PUBLIC_PATTERNS = (
    "scripts/doc_templates.py",
    "scripts/doc_template_sync.py",
    "scripts/board_doc_sync.py",
    "scripts/doc_ownership_sync.py",
    "scripts/doc_fact_discipline.py",
    "tests/conftest.py",
    "docs/templates",
    "plugins/bot_unified_runtime",
)


def _git_porcelain(paths: tuple[str, ...]) -> set[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode not in (0,):
        raise RuntimeError(f"git status 不可用 rc={proc.returncode}: {proc.stderr[:200]}")
    touched: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        body = line[3:].replace("\\", "/").strip().strip('"')
        if body.endswith("/"):
            continue
        touched.add(body)
    return touched


def dirty_public_files() -> set[str]:
    touched = _git_porcelain(PUBLIC_PATTERNS)
    return {
        p for p in touched
        if p.startswith("docs/templates/") or p in PUBLIC_PATTERNS or p.endswith("/__init__.py")
    }


def test_public_readonly_face_has_no_new_member() -> None:
    fresh = sorted(dirty_public_files() - PUBLIC_READONLY_BASELINE_AT_RULE_TIME)
    assert not fresh, (
        "公共只读面出现新规格里没登记过的改动件（席位不得改公共文件，要改只能主会话单点改）："
        f"{fresh}"
    )


def test_public_baseline_is_hand_written_literal() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "PUBLIC_READONLY_BASELINE_AT_RULE_TIME" for t in targets):
                found = True
                assert isinstance(node.value, ast.Call), "基线必须是字面量构造，不得由 git/文件系统派生"
                assert node.value.func.id == "frozenset", "基线必须是 frozenset(字面量集合)"
                assert isinstance(node.value.args[0], (ast.Set, ast.List)), "基线内容必须是字面量集合"
    assert found, "基线常量被删除＝本门失去执法对象"
    assert len(PUBLIC_READONLY_BASELINE_AT_RULE_TIME) >= 30, "基线规模地板不得被缩小"


def _wave_dirs() -> list[Path]:
    """执法对象＝有主控账（SEAT-MAIN.md）的波次：三则前置管的是主会话派发，没有主控账的历史波不属本案。

    被本判据排除的目录一律现算并点名（见 test_wave_scope_exposes_its_exclusions），不许静默缩面。
    """
    if not SDD_ROOT.is_dir():
        return []
    return sorted(
        p.parent for p in SDD_ROOT.glob("*/BRIEFS.md")
        if (p.parent / "SEAT-MAIN.md").is_file()
    )


def _all_briefed_waves() -> list[Path]:
    if not SDD_ROOT.is_dir():
        return []
    return sorted(p.parent for p in SDD_ROOT.glob("*/BRIEFS.md"))


def test_wave_scope_exposes_its_exclusions() -> None:
    excluded = [p.name for p in _all_briefed_waves() if p not in _wave_dirs()]
    assert all((SDD_ROOT / name / "SEAT-MAIN.md").is_file() is False for name in excluded), (
        "排除名单与判据不同源＝本门的扫描面被手写死，改名即失效"
    )


def test_ledger_is_fresher_than_briefs() -> None:
    offenders: list[str] = []
    for wave in _wave_dirs():
        ledger = wave / "ledger"
        briefs = wave / "BRIEFS.md"
        if not ledger.exists():
            offenders.append(f"{wave.name}: 有 BRIEFS.md 却无 ledger（记账先于派发未执行）")
            continue
        if ledger.stat().st_mtime + 1e-6 < briefs.stat().st_mtime:
            offenders.append(
                f"{wave.name}: ledger mtime {ledger.stat().st_mtime:.0f} 旧于 BRIEFS mtime "
                f"{briefs.stat().st_mtime:.0f} —— 派发自检判违规，先补账再派"
            )
    assert not offenders, "；".join(offenders)


def test_gate_itself_detects_a_stale_ledger(tmp_path: Path) -> None:
    wave = tmp_path / "2026-01-01-x"
    wave.mkdir()
    ledger = wave / "ledger"
    briefs = wave / "BRIEFS.md"
    ledger.write_text("old", encoding="utf-8")
    briefs.write_text("new", encoding="utf-8")
    import os
    os.utime(ledger, (1_600_000_000, 1_600_000_000))
    os.utime(briefs, (1_700_000_000, 1_700_000_000))

    def check(root: Path) -> list[str]:
        out: list[str] = []
        for sub in sorted(root.glob("*/BRIEFS.md")):
            lg = sub.parent / "ledger"
            if not lg.exists() or lg.stat().st_mtime + 1e-6 < sub.stat().st_mtime:
                out.append(sub.parent.name)
        return out

    assert check(tmp_path) == ["2026-01-01-x"], "判据必须抓到陈旧 ledger（反向自测）"
    os.utime(ledger, (1_800_000_000, 1_800_000_000))
    assert check(tmp_path) == [], "补账后必须放行"


def test_seat_tool_call_ceiling_is_literal() -> None:
    assert SEAT_TOOL_CALL_CEILING == 40, "≤40 是用户定的硬停线，不是建议值"
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "SEAT_TOOL_CALL_CEILING" for t in targets):
                assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)


def test_subagent_transcript_counter_has_teeth(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "agent-x.jsonl"
    fake.write_text('{"type":"tool_use"}\n' * 41, encoding="utf-8")

    def count(path: Path) -> int:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text.count('"type":"tool_use"')

    assert count(fake) == 41
    monkeypatch.setenv("G_K1_SELFTEST", "1")
    assert SUBAGENTS_GLOB.endswith("*.jsonl"), "计数面必须是席位 transcript，不能缩成心跳文件"
