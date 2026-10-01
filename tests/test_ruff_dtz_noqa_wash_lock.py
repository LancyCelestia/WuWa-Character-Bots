"""DTZ001「拿 noqa 换绿」洗绿锁（S-FIX-LINT-PIN，2026-09-29）。

对应记忆里两条实锤：
1. lint 尺此前没钉配置（无 [tool.ruff.lint]），命中数随 ruff 版本漂；
   现已把 413 条有效规则显式写进 select（见 pyproject.toml）。
2. schedule_board 里 4 枚承载日内时刻的 1970 锚曾被 `# noqa: DTZ001` 洗绿，
   而 naive 锚照旧（真缺陷，落在台账 #29★「提醒 UTC 混用老坑」同一域）。

这把尺判两件事，缺一不可：
- 结构腿（本模块主判据，不依赖 ruff）：schedule_board 里 datetime(1970, 1, 1, …)
  这种 1970 日内锚必须带 tzinfo、且不得再靠 `# noqa: DTZ001` 换绿——
  改回 naive（带不带 noqa 都算）＝FAILED。
- 活规则腿：ruff 真把 DTZ001 当回事（无 noqa 的 naive 锚必被 ruff 报出），
  证明这把尺不是空转。

判据按结构（AST）找锚点，不按行号/枚数写死（行号会漂，枚数随注册表长＝铁律 10 病）。

依赖缺席即红、绝不 collection ERROR：本模块**绝不 import ruff、绝不 import 插件**，
ruff 只经 `sys.executable -m ruff` 子进程调用；解释器没装 ruff 时相关测试出 FAILED，
而不是把门瞎成「收集期崩」或静默 skip（记忆 210 号失效形态）。全离线：只读源码文本 +
子进程，不碰网络、不碰真库。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TARGET = (
    _REPO_ROOT
    / "plugins/bot_unified_runtime/domains/schedule/capabilities/schedule_board.py"
)

# 承载日内时刻的 1970 锚点构造器：date 三枚固定 (1970, 1, 1)，只带日内时/分。
_SENTINEL_DATE = (1970, 1, 1)
_DTZ_NOQA = "# noqa: DTZ001"


def _compact_noqa(line: str) -> str:
    return line.replace(" ", "").lower()


def _line_has_dtz_noqa(line: str) -> bool:
    return _DTZ_NOQA in line or "#noqa:dtz001" in _compact_noqa(line)


def _is_int_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, int)


def _sentinel_calls(source_path: Path) -> list[tuple[int, ast.Call]]:
    """AST 里定位 datetime(1970, 1, 1, …) 构造调用（返回 (行号, 节点) 列表）。"""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found: list[tuple[int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name != "datetime" or len(node.args) < 3:
            continue
        if not all(_is_int_const(a) for a in node.args[:3]):
            continue
        head = tuple(a.value for a in node.args[:3])  # type: ignore[attr-defined]
        if head == _SENTINEL_DATE:
            found.append((node.lineno, node))
    return found


def _offenders(source_path: Path) -> list[tuple[int, str]]:
    """返回「naive 或靠 noqa 洗绿的 1970 锚」清单：(行号, 该锚原始行)。

    判红条件（任一）：调用没带 tzinfo，或所在物理行挂着 `# noqa: DTZ001`。
    这样既拦 naive+noqa（换绿），也拦裸 naive（回归）。
    """
    lines = source_path.read_text(encoding="utf-8").splitlines()
    bad: list[tuple[int, str]] = []
    for lineno, call in _sentinel_calls(source_path):
        has_tz = any(kw.arg == "tzinfo" for kw in call.keywords)
        src_line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if (not has_tz) or _line_has_dtz_noqa(src_line):
            bad.append((lineno, src_line.strip()))
    return bad


def _run_ruff_dtz001(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "DTZ001",
            "--output-format",
            "concise",
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_ruler_is_not_blind_on_target() -> None:
    """先验锚点：尺必须能在真身里找到 1970 日内锚，否则「全绿」是假绿（尺瞎）。"""
    assert _sentinel_calls(_TARGET), (
        "在 schedule_board 里没定位到任何 datetime(1970, 1, 1, …) 日内锚——"
        "锚点结构变了要先改这把尺，别对着空气签绿。"
    )


def test_intraday_sentinels_are_aware_and_not_noqa_washed() -> None:
    """结构腿：1970 日内锚必须 aware，且不得再靠 `# noqa: DTZ001` 换绿。

    这是「把锚点改回 naive（哪怕重新挂上 noqa）⇒ 门必须红」的主判据。
    """
    offenders = _offenders(_TARGET)
    assert not offenders, (
        "发现 naive / 靠 noqa 洗绿的 1970 日内锚（真缺陷：naive 锚交给 "
        "_next_weekday_datetime 与 (end - anchor) 求差，naive 会按本机 UTC 偏移静默漂移，"
        "见台账 #29★/#6★）：\n" + "\n".join(f"  L{n}: {t}" for n, t in offenders)
    )


def test_ruff_treats_dtz001_as_a_live_rule(tmp_path: Path) -> None:
    """活规则腿：无 noqa 的裸 naive 锚必被 ruff 报出，证明 DTZ001 不是空转。"""
    naive = tmp_path / "naive_probe.py"
    naive.write_text(
        "from datetime import datetime\n"
        "anchor = datetime(1970, 1, 1, 8, 0)\n",
        encoding="utf-8",
    )
    proc = _run_ruff_dtz001(naive)
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "No module named ruff" not in combined, (
        "本锁活规则腿依赖 ruff，但当前解释器没装 ruff：尺缺席必须红，不得装绿（记忆 210）。"
        f" stderr={proc.stderr.strip()[:200]}"
    )
    assert proc.returncode != 0 and "DTZ001" in (proc.stdout or ""), (
        f"DTZ001 没咬住裸 naive 锚（尺空转？读数：\n{combined.strip()[:600]}）"
    )


def test_poison_proves_the_lock_bites_naive_plus_noqa(tmp_path: Path) -> None:
    """注毒自证：复刻当年「naive + # noqa: DTZ001」洗绿形，结构探测器必须咬住。

    注毒只写 tmp_path（绝不碰真身件），try/finally 复原并逐字节比对真身未动。
    """
    original_bytes = _TARGET.read_bytes()
    poisoned = tmp_path / "sentinel_probe.py"
    poisoned.write_text(
        "from datetime import datetime\n"
        "anchor = datetime(1970, 1, 1, 8, 0)  # noqa: DTZ001\n",
        encoding="utf-8",
    )
    try:
        # 真身此刻不得被写毒——逐字节复核。
        assert _TARGET.read_bytes() == original_bytes, "注毒台误写真身！"
        # 换绿形必须被结构腿咬住（naive+noqa → offender）。
        assert _offenders(poisoned), "注毒（naive+noqa）没被咬住＝这把尺瞎"
        # 反面对照：把毒改成 aware 且摘掉 noqa，结构腿应放行（证明它只咬真缺陷）。
        fixed = tmp_path / "sentinel_fixed_probe.py"
        fixed.write_text(
            "from datetime import datetime\n"
            "anchor = datetime(1970, 1, 1, 8, 0, tzinfo=UTC)\n",
            encoding="utf-8",
        )
        assert _offenders(fixed) == [], "对照件（aware 无 noqa）被误判＝尺过宽"
    finally:
        assert _TARGET.read_bytes() == original_bytes, "收尾复核：真身字节被改动"
