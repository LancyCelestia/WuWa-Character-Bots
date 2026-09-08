"""记忆库清洗（防御强化）：把 NSFW/血腥暴力/侮辱/恶心外号等内容从长时记忆中清除。

用户明确授权清除；为可审计不清空证据，匹配行先复制进 ``memory_quarantine``
隔离表（含命中类别与时间），再从 ``memory_facts`` 删除。支持 dry-run 只报告不删。

用法：
    python -m plugins.bot_unified_runtime.security.memory_sanitize --dry-run
    python -m plugins.bot_unified_runtime.security.memory_sanitize --apply
入口也可走 dev.ps1 -Task memory-sanitize。
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 与 content_safety 同源的类别词表；记忆清洗比公开内容更严格——
# 出现在长期记忆里的越界内容即使只是引用也会持续污染人格，故全部清除。
_SANITIZE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nsfw", re.compile(r"(nsfw|r[- ]?18|色情|性爱|性行为|露骨|裸体|性交|黄片|情色)", re.IGNORECASE)),
    ("graphic_violence", re.compile(r"(血腥|肢解|虐杀|酷刑|极端暴力)", re.IGNORECASE)),
    ("insult", re.compile(r"(废物|傻逼|弱智|脑残|畜生|贱人|婊|滚蛋|去死)", re.IGNORECASE)),
    ("petplay", re.compile(r"(汪汪叫|当狗|像狗一样|趴好|拴住|项圈调教)", re.IGNORECASE)),
    ("forced_persona", re.compile(r"(叫我妈妈|喊我爸爸|必须爱上我|和我结婚|嫁给我|当猫娘)", re.IGNORECASE)),
)


@dataclass(frozen=True)
class SanitizeReport:
    scanned: int
    quarantined: int
    by_category: dict[str, int]

    def render(self, *, applied: bool) -> str:
        head = "记忆清洗（已执行）" if applied else "记忆清洗（dry-run 预览）"
        lines = [f"{head}：扫描 {self.scanned} 条，命中 {self.quarantined} 条"]
        for category, count in sorted(self.by_category.items()):
            lines.append(f"  - {category}: {count}")
        if self.quarantined == 0:
            lines.append("记忆库干净，无需处理。")
        return "\n".join(lines)


def _match_category(text: str) -> str | None:
    for category, pattern in _SANITIZE_PATTERNS:
        if pattern.search(text or ""):
            return category
    return None


def _ensure_quarantine_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_quarantine (
            fact_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            memory_kind TEXT NOT NULL,
            text TEXT NOT NULL,
            category TEXT NOT NULL,
            quarantined_at TEXT NOT NULL,
            PRIMARY KEY (fact_id, quarantined_at)
        )
        """
    )


def sanitize_memory_db(
    db_path: str | Path,
    *,
    apply: bool = False,
) -> SanitizeReport:
    """扫描 memory_facts；apply=True 时先隔离再删除命中行。"""
    path = Path(db_path)
    if not path.exists():
        return SanitizeReport(scanned=0, quarantined=0, by_category={})
    by_category: dict[str, int] = {}
    scanned = 0
    now_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT fact_id, subject_user_id, session_id, memory_kind, text FROM memory_facts"
        ).fetchall()
        flagged: list[sqlite3.Row] = []
        for row in rows:
            scanned += 1
            category = _match_category(str(row["text"] or ""))
            if category is None:
                continue
            by_category[category] = by_category.get(category, 0) + 1
            flagged.append(row)
        if flagged and apply:
            _ensure_quarantine_schema(connection)
            for row in flagged:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_quarantine
                        (fact_id, subject_user_id, session_id, memory_kind, text, category, quarantined_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row["fact_id"]),
                        str(row["subject_user_id"]),
                        str(row["session_id"]),
                        str(row["memory_kind"]),
                        str(row["text"]),
                        _match_category(str(row["text"] or "")) or "unknown",
                        now_text,
                    ),
                )
            for row in flagged:
                connection.execute(
                    "DELETE FROM memory_facts WHERE fact_id = ?",
                    (str(row["fact_id"]),),
                )
            connection.commit()
    finally:
        connection.close()
    return SanitizeReport(scanned=scanned, quarantined=len(flagged), by_category=by_category)


def resolve_memory_db_path(config: object) -> Path | None:
    raw = str(getattr(config, "bot_memory_db_path", "") or "").strip()
    if not raw:
        return None
    from plugins.bot_unified_runtime.sources.parsers.cookies import (
        _resolve_relative_cookie_path,
    )

    # data/ 前缀 → Runtime 数据根（与 cookie 文件同一套映射规则）。
    return _resolve_relative_cookie_path(Path(raw))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sanitize long-term memory DB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只报告命中，不删除")
    group.add_argument("--apply", action="store_true", help="隔离并删除命中记忆")
    parser.add_argument("--db", default="", help="覆盖记忆库路径（默认读 BOT_MEMORY_DB_PATH）")
    args = parser.parse_args(argv)

    if args.db:
        db_path: Path | str = args.db
    else:
        from plugins.bot_unified_runtime.smoke import load_smoke_config

        resolved = resolve_memory_db_path(load_smoke_config())
        if resolved is None:
            print("未配置 BOT_MEMORY_DB_PATH，无事可做。")
            return 2
        db_path = resolved
    report = sanitize_memory_db(db_path, apply=args.apply)
    print(report.render(applied=args.apply))
    print(f"数据库：{db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
