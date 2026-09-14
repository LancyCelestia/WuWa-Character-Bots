"""交付物 SHA-256 清单（交叉验证机制·哈希层，2026-09-13）。

用法：
    python tests/verify_hashes.py --write   # 记录/重录基线（有意识地改）
    python tests/verify_hashes.py --check   # 校验漂移（退出码非 0 = 有未记录变更）
    python tests/verify_hashes.py           # 缺省 = --check

pytest 常驻门：tests/test_cross_validation_gates.py 以 subprocess --check
方式守门——清单内任何文件出现未记录的**内容**变更，全量测试直接红，
强制走一次「有意识 --write」，改了 A 忘了 B 的事在门禁处现形。

哈希口径：换行统一为 LF 后再算（见 ``sha256_of``），因此哈希锚定的是
「提交内容」而非「工作区行尾状态」——主仓、linked worktree、CI 干净克隆
三种检出环境必须得出一致结果。

清单范围（视觉与规范交付物，对齐 DESIGN-SPEC.md §三）：
7 张 Jinja 模板 + theme_tokens.py + docs/rendering-contract.md + DESIGN-SPEC.md
+ docs/design/ 三份规格 + 6 个卡片 builder 源文件（审查 K-06 扩面，2026-09-14：
bridge/renderer/templates + echo/debug/usage_cards——模板只是壳，改 builder 的
f-string 文案同样改变出卡内容，不进清单就绕过了哈希门），共 19 项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("render_hashes.json")

TRACKED_FILES: tuple[str, ...] = (
    "plugins/bot_unified_runtime/output/card_render/templates/universal_card.html",
    "plugins/bot_unified_runtime/output/card_render/templates/affinity_card.html",
    "plugins/bot_unified_runtime/output/card_render/templates/finance_card.html",
    "plugins/bot_unified_runtime/output/card_render/templates/market_card.html",
    "plugins/bot_unified_runtime/output/card_render/templates/mermaid_card.html",
    "plugins/bot_unified_runtime/output/card_render/templates/song_candidates.html",
    "plugins/bot_unified_runtime/output/card_render/templates/error_card.html",
    "plugins/bot_unified_runtime/output/card_render/theme_tokens.py",
    "docs/rendering-contract.md",
    "DESIGN-SPEC.md",
    "docs/design/fstring-card-dom-spec.md",
    "docs/design/render-pipeline-optimization-spec.md",
    "docs/design/visual-effects-catalog.md",
    # --- 卡片 builder 源文件（审查 K-06 扩面，2026-09-14）---
    # 约束：这 6 个文件产出/装配模板 HTML（4 处 f-string 直拼卡见
    # tests/test_mica_builders_contract.py 的统一对象清单），改文案不改模板
    # 也必须过哈希门，否则「改 builder 绕过 --write」成为系统性漏洞。
    "plugins/bot_unified_runtime/output/card_render/bridge.py",
    "plugins/bot_unified_runtime/capabilities/debug.py",
    "plugins/bot_unified_runtime/capabilities/echo.py",
    "plugins/bot_unified_runtime/output/card_render/usage_cards.py",
    "plugins/bot_unified_runtime/output/renderer.py",
    "plugins/bot_unified_runtime/output/templates.py",
)


def sha256_of(path: Path) -> str:
    """交付物内容哈希：换行统一为 LF 后再算。

    哈希必须锚定「提交内容」，不能锚定「工作区行尾状态」——Windows 上
    ``core.autocrlf`` 会把检出转成 CRLF，而 ``.gitattributes`` 又要求
    ``*.md/*.py/*.json`` 为 LF。若直接哈希原始字节，同一个 commit 在主仓、
    linked worktree、CI 干净克隆上会得出不同结果，哈希门随之失真
    （2026-09-14 审查实证：干净检出误报 4 项漂移）。
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def build_manifest() -> dict[str, str]:
    return {name: sha256_of(ROOT / name) for name in TRACKED_FILES}


def check(quiet: bool = False) -> list[str]:
    """返回漂移报告（空列表 = 干净）。缺文件/新文件未登记/字节变更都算。"""
    problems: list[str] = []
    recorded: dict[str, str] = {}
    if MANIFEST.is_file():
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in TRACKED_FILES:
        path = ROOT / name
        if not path.is_file():
            problems.append(f"MISSING  {name}（清单在册但文件不存在）")
            continue
        current = sha256_of(path)
        if name not in recorded:
            problems.append(f"NEW      {name}（未登记的新交付物——确认后 --write）")
        elif recorded[name] != current:
            problems.append(f"DRIFT    {name}（字节变更未记录——确认后 --write）")
    for name in recorded:
        if name not in TRACKED_FILES:
            problems.append(f"STALE    {name}（清单已登记但不在跟踪集——清理后 --write）")
    if problems and not quiet:
        for line in problems:
            print(line, file=sys.stderr)
        print(
            f"verify_hashes: {len(problems)} 项漂移；"
            "确认属预期改动后执行 python tests/verify_hashes.py --write 重录。",
            file=sys.stderr,
        )
    return problems


def write() -> None:
    MANIFEST.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"verify_hashes: 已记录 {len(TRACKED_FILES)} 个交付物 -> {MANIFEST.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交付物 SHA-256 漂移门")
    parser.add_argument("--write", action="store_true", help="记录/重录基线")
    parser.add_argument("--check", action="store_true", help="校验漂移（缺省行为）")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    return 1 if check() else 0


if __name__ == "__main__":
    raise SystemExit(main())
