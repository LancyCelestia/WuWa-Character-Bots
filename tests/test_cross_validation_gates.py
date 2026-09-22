"""交叉验证机制常驻门（哈希漂移 / 机器事实漂移）。

两个子机制：
- tests/verify_hashes.py --check：交付物 SHA-256 清单（DESIGN-SPEC.md §三）；
- scripts/doc_sync.py --check：docs/auto-facts.md 机器册与代码互证。

热路径性能门在 tests/test_perf_regression.py（pytest 直收集，独立文件）。
漂移处理约定：确认属预期改动后跑对应 --write，门即恢复绿——"有意识地改"。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_script(script: str, flag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), flag],
        capture_output=True,
        text=True,
        # 必须钉 encoding：本仓铁律要求子进程 PYTHONIOENCODING=utf-8，父进程若按
        # locale(GBK) 解码中日韩输出会当场 TypeError，把 stderr 打成 None——
        # 于是"哈希漂移/事实漂移"这类真红全被报成"can only concatenate str"，
        # 真因被吞（台账 #47 登记的 systemic 缺陷第 11 枚；模范写法见
        # tests/test_verify_hashes_coverage.py::_run_check）。
        encoding="utf-8",
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
