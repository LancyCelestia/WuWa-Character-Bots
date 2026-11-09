#!/usr/bin/env python
"""红归属量具：把失败集与「某一波的改动面」对上，判「本波造成 / 既存债」。

为什么要有这把尺（真实痛点）：
  任何一波改完跑全量，总会看到若干红。人工判断「这条红是不是我弄的」既慢又
  容易自我说服（"应该本来就有吧"）。本尺把判据机械化：**失败节点 × 改动面**
  三向比对（① 测试文件本身是改动面；② 节点名提到改动面的模块/符号；
  ③ 失败体引用了改动面文件），命中即「可能本波造成」，其余归「既存债」。

口径（写死，避免每次重新解释）：
  - 「改动面」默认取 `git log --name-only <base>..HEAD`（base 缺省＝上一个
    里程碑提交，可用 --base 覆盖）；工作树若另有脏件，用 `--dirty` 一并计入。
  - 判据**只判归属、不判对错**：命中的红未必是本波 bug（可能是它暴露的旧洞），
    未命中的红也未必安全（可能是本波改的共享件引起的间接红）——本尺的作用是
    **把"该查哪些"缩到最小**，最终定性仍需人/席去看失败体。
  - **恒不修改任何文件**；只读 + 打印。

用法：
    python scripts/failure_attribution_census.py --fails <失败集文本> [--base <提交>] [--dirty]
    # 失败集文本格式：pytest -rf 的输出（含 `FAILED path::node` 行）

退出码：0 = 无「本波造成」嫌疑；1 = 有嫌疑（须人工定性）；2 = 输入不可读。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
_FAILED_RE = re.compile(r"^FAILED (\S+)", flags=re.MULTILINE)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(_REPO), capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def changed_files(base: str, *, dirty: bool = False) -> list[str]:
    """改动面：base..HEAD 的文件 + （可选）工作树脏件。"""
    raw = _git("log", "--name-only", "--pretty=format:", f"{base}..HEAD")
    files = {line.strip() for line in raw.splitlines() if line.strip()}
    if dirty:
        for line in _git("status", "--porcelain").splitlines():
            if len(line) > 3:
                files.add(line[3:].strip())
    return sorted(files)


def failed_nodes(text: str) -> list[str]:
    return sorted(set(_FAILED_RE.findall(text)))


def attribute(
    fails: list[str], surface: list[str], *, full_text: str = ""
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """→ (嫌疑集[(节点, 理由)], 无交集集)。纯函数，便于测试。"""
    surface_set = set(surface)
    suspect: list[tuple[str, list[str]]] = []
    clean: list[str] = []
    for node in fails:
        reasons: list[str] = []
        test_file = node.split("::", 1)[0]
        if test_file in surface_set:
            reasons.append("测试文件本身在改动面")
        for path in surface:
            stem = path.rsplit("/", 1)[-1].removesuffix(".py")
            if stem and stem in node:
                reasons.append(f"节点名提到 {path.rsplit('/', 1)[-1]}")
        if full_text and test_file and test_file in surface_set:
            reasons.append("失败体与改动面同文件")
        if reasons:
            suspect.append((node, sorted(set(reasons))))
        else:
            clean.append(node)
    return suspect, clean


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="失败归属量具（只读）")
    parser.add_argument("--fails", required=True, help="pytest -rf 输出文本路径")
    parser.add_argument(
        "--base",
        default="",
        help="改动面起点提交；缺省取 HEAD~1（单笔）——多笔波次请显式给起点",
    )
    parser.add_argument("--dirty", action="store_true", help="把工作树脏件计入改动面")
    args = parser.parse_args(argv)

    src = pathlib.Path(args.fails)
    if not src.exists():
        print(f"失败集文本不可读：{src}", file=sys.stderr)
        return 2
    text = src.read_text(encoding="utf-8", errors="replace")
    base = args.base or "HEAD~1"
    surface = changed_files(base, dirty=args.dirty)
    fails = failed_nodes(text)

    print(f"改动面（{base}..HEAD{'+dirty' if args.dirty else ''}）：{len(surface)} 个文件")
    for path in surface:
        print(f"   {path}")
    print(f"\n失败集：{len(fails)} 条")
    if not fails:
        print("（无失败行；失败集可能为空或格式不符 `FAILED path::node`）")
        return 0

    suspect, clean = attribute(fails, surface, full_text=text)
    print(f"\n=== 判定：可能本波造成 {len(suspect)} 条 ===")
    for node, reasons in suspect:
        print(f"   ⚠ {node}")
        for reason in reasons:
            print(f"      ← {reason}")
    print(f"\n=== 与改动面无交集（视为既存债）{len(clean)} 条 ===")
    for node in clean:
        print(f"   ✓ {node}")
    print(
        "\n提示：命中只表示「该先看这些」；间接红（共享件改动引发）可能落在无交集集里。"
    )
    return 1 if suspect else 0


if __name__ == "__main__":
    raise SystemExit(main())
