"""交叉验证机制常驻门（哈希漂移 / 机器事实漂移 / 热路径性能）。

三个子机制：
- tests/verify_hashes.py --check：交付物 SHA-256 清单（DESIGN-SPEC.md §三）；
- scripts/doc_sync.py --check：docs/auto-facts.md 机器册与代码互证；
- tests/perf_regression.py：热路径数量级守卫（函数经本模块再导出给 pytest 收集）。

漂移处理约定：确认属预期改动后跑对应 --write，门即恢复绿——"有意识地改"。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

import perf_regression

# 性能门再导出（pytest 按函数名收集；标记随函数对象保留）。
test_route_classify_throughput_stays_order_of_magnitude = (
    perf_regression.test_route_classify_throughput_stays_order_of_magnitude
)
test_core_modules_import_under_budget = perf_regression.test_core_modules_import_under_budget
test_render_and_data_modules_import_cleanly = (
    perf_regression.test_render_and_data_modules_import_cleanly
)


def _run_script(script: str, flag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), flag],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
        check=False,
    )


def test_verify_hashes_manifest_clean() -> None:
    result = _run_script("tests/verify_hashes.py", "--check")
    assert result.returncode == 0, (
        "交付物哈希漂移：\n"
        + result.stderr
        + "确认属预期改动后执行 python tests/verify_hashes.py --write 重录。"
    )


def test_doc_sync_auto_facts_in_sync() -> None:
    result = _run_script("scripts/doc_sync.py", "--check")
    assert result.returncode == 0, (
        "机器事实册漂移：\n"
        + result.stderr
        + "确认属预期改动后执行 python scripts/doc_sync.py --write 重生成。"
    )
