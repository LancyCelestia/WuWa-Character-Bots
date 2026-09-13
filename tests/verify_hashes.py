"""交付物 SHA-256 清单（交叉验证机制·哈希层，2026-09-13）。

用法：
    python tests/verify_hashes.py --write   # 记录/重录基线（有意识地改）
    python tests/verify_hashes.py --check   # 校验漂移（退出码非 0 = 有未记录变更）
    python tests/verify_hashes.py           # 缺省 = --check

pytest 常驻门：tests/test_cross_validation_gates.py 以 subprocess --check
方式守门——清单内任何文件出现未记录的字节变更，全量测试直接红，
强制走一次「有意识 --write」，改了 A 忘了 B 的事在门禁处现形。

清单范围（视觉与规范交付物，对齐 DESIGN-SPEC.md §三）：
6 张 Jinja 模板 + theme_tokens.py + docs/rendering-contract.md + DESIGN-SPEC.md。
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
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
