"""双引擎交叉验证执行器（2026-09-13）。

同一份测试套在两种隔离口径下各跑一遍，结果必须互证一致：
- 引擎 A（默认）：dev.ps1 同口径——venv pytest + 独立 basetemp + `-p no:cacheprovider`
  （源码树零缓存铁律：缓存/临时物一律落 %TEMP%，.pytest_cache 不落源码树根）；
- 引擎 B（隔离）：在 A 之上再加 PYTHONDONTWRITEBYTECODE=1（.pyc 亦不落盘）。

不一致（同提交一绿一红）= 环境耦合缺陷，当场暴露。全量两遍约 5–6 分钟，
用于提交前/大改后；不进 pytest 常驻门（避免每次全量翻倍）。

用法：python tests/cross_validate.py [--sample tests/test_rendering_contract.py]
退出码：0=两引擎一致且绿；1=存在失败；2=两引擎结果不一致。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / "ChatBot_Runtime" / "venv" / "Scripts" / "python.exe"
if not VENV_PY.is_file():
    VENV_PY = Path(sys.executable)


def _run_engine(engine: str, sample: str) -> tuple[int, str]:
    env = dict(os.environ)
    basetemp = Path(tempfile.gettempdir()) / f"crossval-{engine}"
    cmd = [
        str(VENV_PY),
        "-m",
        "pytest",
        sample,
        "--basetemp",
        str(basetemp),
        "-p",
        "no:cacheprovider",
        "-q",
    ]
    if engine == "isolated":
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=1800, env=env,
        check=False,
    )
    tail = "\n".join((result.stdout or "").strip().splitlines()[-3:])
    return result.returncode, tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="双引擎交叉验证")
    parser.add_argument(
        "--sample",
        default="tests/test_rendering_contract.py tests/test_route_order_semantics.py",
        help="验证样本（缺省两条快族；全量传 'tests'）",
    )
    args = parser.parse_args(argv)

    code_a, tail_a = _run_engine("default", args.sample)
    code_b, tail_b = _run_engine("isolated", args.sample)
    print(f"[default ] exit={code_a} :: {tail_a.splitlines()[-1] if tail_a else ''}")
    print(f"[isolated] exit={code_b} :: {tail_b.splitlines()[-1] if tail_b else ''}")

    if code_a != code_b:
        print("cross_validate: 两引擎结果不一致——存在环境耦合缺陷。", file=sys.stderr)
        return 2
    if code_a != 0:
        print("cross_validate: 两引擎一致地红——先修失败再谈交叉验证。", file=sys.stderr)
        return 1
    print("cross_validate: 双引擎一致全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
