"""机器事实册自动同步（交叉验证机制·文档层，2026-09-13）。

`docs/auto-facts.md` 整册由本脚本从代码机械推导生成——**全册机器所有，
人工不要手改**（叙述类文档在 AGENTS/HANDBOOK，机器只管"数字和清单"类事实）。

用法：
    python scripts/doc_sync.py --write   # 从代码重生成整册
    python scripts/doc_sync.py --check   # 漂移检测（退出码非 0 = 不同步）
    python scripts/doc_sync.py           # 缺省 = --check

pytest 常驻门：tests/test_cross_validation_gates.py 以 subprocess --check 守门。
事实来源：RouteKind 注册表、帮助 topic 数、模板清单、测试文件数、
配置键数、哈希清单范围——全部可从代码/清单机械推导。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "auto-facts.md"

_HEAD = (
    "# 自动事实册（机器所有 · 勿手改）\n\n"
    "> 本册由 `python scripts/doc_sync.py --write` 从代码整册重生成；\n"
    "> `--check` 漂移即红（tests/test_cross_validation_gates.py 常驻）。\n"
    "> 生成时间字段不在册（保证字节确定性，避免无意义漂移）。\n"
)


def _tpl_list() -> list[str]:
    tpl_dir = ROOT / "plugins/bot_unified_runtime/output/card_render/templates"
    return sorted(p.name for p in tpl_dir.glob("*.html"))


def _route_kinds() -> list[str]:
    text = (
        ROOT / "plugins/bot_unified_runtime/runtime/base_router.py"
    ).read_text(encoding="utf-8")
    block = re.search(r"class RouteKind\(str, Enum\):(.*?)\n\n", text, re.DOTALL)
    assert block, "RouteKind 枚举找不到"
    return re.findall(r"^    ([A-Z_]+) = ", block.group(1), re.MULTILINE)


def _help_topics() -> list[str]:
    text = (
        ROOT / "plugins/bot_unified_runtime/capabilities/echo.py"
    ).read_text(encoding="utf-8")
    return re.findall(r'"topic":\s*[\'"]([^\'"]+)[\'"]', text)


def _test_file_count() -> int:
    return len(list((ROOT / "tests").glob("test_*.py")))


def _config_key_count() -> int:
    text = (ROOT / "plugins/bot_unified_runtime/config.py").read_text(encoding="utf-8")
    return len(re.findall(r"^    bot_[a-z0-9_]+:", text, re.MULTILINE))


def _tracked_files() -> list[str]:
    sys.path.insert(0, str(ROOT / "tests"))
    from verify_hashes import TRACKED_FILES

    return list(TRACKED_FILES)


def build_document() -> str:
    tpls = _tpl_list()
    kinds = _route_kinds()
    topics = _help_topics()
    tracked = _tracked_files()
    lines = [
        _HEAD,
        f"- 模板清单（{len(tpls)}）：{', '.join(tpls)}",
        "",
        f"- RouteKind（{len(kinds)}）：{', '.join(kinds)}",
        "",
        f"- 帮助 topic 数：{len(topics)}（重名 {len(topics) - len(set(topics))}）",
        f"- 测试文件数：{_test_file_count()}",
        f"- config.py bot_* 字段数：{_config_key_count()}",
        "",
        f"- 哈希清单范围（{len(tracked)}）：{', '.join(tracked)}",
        "",
    ]
    return "\n".join(lines)


def check() -> bool:
    current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
    expected = build_document()
    if current != expected:
        print(
            "doc_sync: docs/auto-facts.md 与代码推导结果不一致；"
            "跑 python scripts/doc_sync.py --write 重生成。",
            file=sys.stderr,
        )
        return False
    return True


def write() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(build_document(), encoding="utf-8")
    print(f"doc_sync: 已重生成 {TARGET.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="机器事实册同步门")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
