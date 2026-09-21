"""V21-AFFINITY-002 历史误扣重放报告脚本（只读生产库；无 --apply）。

用法：
    python scripts/affinity_replay_report.py                # 默认：只读生产库 →
                                                            #   报告写 docs/design/v21r2-aff-replay-report.md
                                                            #   + 提案指纹登记表（幂等去重）
    python scripts/affinity_replay_report.py --stdout       # 只打印，不落任何盘
    python scripts/affinity_replay_report.py --db PATH      # 指定别的好感度库（同样只读）
    python scripts/affinity_replay_report.py --dry          # 显式声明 dry（本脚本唯一模式）

**不存在 --apply**：补偿落库属管理员手工操作（报告 §四 写明步骤），
本脚本任何路径都不写好感度库——引擎以 SQLite ``mode=ro`` 打开，写必被拒。

重复运行幂等：提案按事件集指纹（SHA-256）登记于
``docs/design/v21r2-aff-compensation-registry.json``，指纹已存在的提案
标记「已提案过，不重复计」，不会重复出现在补偿总量里。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_paths import runtime_path

from plugins.bot_unified_runtime.domains.chat_reply import (
    affinity_replay as ar,
)

DEFAULT_DB_RELATIVE = "data/user_affinity.sqlite3"
DEFAULT_OUT = ROOT / "docs" / "design" / "v21r2-aff-replay-report.md"
DEFAULT_REGISTRY = ROOT / "docs" / "design" / "v21r2-aff-compensation-registry.json"


def _load_registry(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"[warn] 指纹登记表不可读（{exc}），按空表继续（可能重复提案）", file=sys.stderr)
        return []
    if isinstance(data, dict):
        entries = data.get("entries", [])
    else:
        entries = data
    return [entry for entry in entries if isinstance(entry, dict)]


def _append_registry(path: Path, entries: list[dict[str, object]]) -> None:
    """原子追加登记表（temp+replace；只写 docs/ 登记表，绝不碰好感度库）。"""
    payload = {"entries": entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{int(time.time())}")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="V21-AFFINITY-002 历史误扣重放与具名补偿提案（只读；无 --apply）",
        epilog=(
            "补偿落库是管理员手工操作：见报告「手工补偿规程」一节。"
            "本脚本只读好感度库（mode=ro）并产出待审报告。"
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        help=f"好感度 SQLite 路径（默认 runtime_path 解析 {DEFAULT_DB_RELATIVE}）",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="显式声明 dry（本脚本唯一模式；不存在 --apply）",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="只打印报告到 stdout，不写报告文件、不更新指纹登记表",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="报告输出路径")
    parser.add_argument(
        "--registry", default=str(DEFAULT_REGISTRY), help="提案指纹登记表路径"
    )
    parser.add_argument(
        "--max-events", type=int, default=2000, help="逐事件清单最多列出的行数"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db) if args.db else Path(runtime_path(DEFAULT_DB_RELATIVE))
    if not db_path.exists():
        print(f"[error] 好感度库不存在：{db_path}", file=sys.stderr)
        return 2
    try:
        connection = ar.open_readonly_connection(db_path)
    except sqlite3.Error as exc:
        print(f"[error] 只读打开失败：{exc}", file=sys.stderr)
        return 2
    try:
        result = ar.run_replay(connection, limit=args.max_events)
    except ar.LedgerSchemaError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    finally:
        connection.close()

    known = frozenset(ar.parse_known_fingerprints(_load_registry(Path(args.registry))))
    proposals, duplicates = ar.build_compensation_proposals(
        result.verdicts, known_fingerprints=known
    )
    report = ar.build_text_report(
        result,
        db_label=str(db_path),
        proposals=proposals,
        duplicates=duplicates,
        max_event_lines=max(0, args.max_events),
    )

    counts = result.verdict_counts()
    invariant = counts.get(ar.VERDICT_POLICY_INVARIANT, 0)
    over = counts.get(ar.VERDICT_OVER_DEDUCTED, 0)
    unknown = counts.get(ar.VERDICT_UNKNOWN, 0)
    print(
        f"[replay] 事件 {len(result.events)} 条：零差额 {invariant} / "
        f"已证多扣 {over} / 无证据 unknown {unknown}；"
        f"新提案 {len(proposals)} 项、重复 {len(duplicates)} 项"
    )

    if args.stdout:
        print(report)
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[report] 已写入 {out_path}")

    if proposals:
        entries = _load_registry(Path(args.registry))
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for proposal in proposals:
            entries.append(proposal.to_registry_entry(generated_at=generated_at))
        _append_registry(Path(args.registry), entries)
        print(
            f"[registry] 新指纹 {len(proposals)} 条已登记 → {args.registry}"
            "（重复提案不会重复计）"
        )
    else:
        print("[registry] 无新提案，登记表未变动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
