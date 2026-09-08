"""群文件整理（批次 D）：上传事件记录 + 统计指令数据源。

OneBot V11 notice_type=group_upload 事件 → SQLite 记录（按群/文件名/大小/时间）；
`/bot 群文件 <群号|当前>` 输出最近上传与扩展名分布，给管理员整理建议。
OneBot 不提供移动文件夹 API，因此"整理"落地为记录+统计+提醒，不假装能移动。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

_CATEGORY_BY_EXT: dict[str, str] = {
    "pdf": "文档", "doc": "文档", "docx": "文档", "txt": "文档", "md": "文档",
    "ppt": "文档", "pptx": "文档", "xls": "文档", "xlsx": "文档",
    "zip": "压缩包", "rar": "压缩包", "7z": "压缩包",
    "png": "图片", "jpg": "图片", "jpeg": "图片", "gif": "图片", "webp": "图片",
    "mp4": "视频", "mkv": "视频", "mov": "视频",
    "mp3": "音频", "flac": "音频", "wav": "音频",
}


def category_for_filename(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _CATEGORY_BY_EXT.get(ext, "其他")


class GroupFileStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS group_files (
                    group_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    uploaded_at TEXT NOT NULL,
                    uploader_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (group_id, file_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, *, group_id: str, file_id: str, name: str, size: int, uploader_id: str = "") -> None:
        with self._lock, self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO group_files (group_id, file_id, name, size, uploaded_at, uploader_id)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (group_id, file_id, name, int(size), time.strftime("%Y-%m-%d %H:%M:%S"), uploader_id),
                )

    def summary(self, group_id: str, *, limit: int = 10) -> str:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT name, size, uploaded_at FROM group_files WHERE group_id = ?"
                " ORDER BY uploaded_at DESC LIMIT ?",
                (group_id, max(1, int(limit))),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM group_files WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
        if not rows:
            return "这个群还没有记录到文件上传。"
        categories = Counter(category_for_filename(str(r["name"])) for r in rows)
        cat_line = "、".join(f"{k}×{v}" for k, v in categories.most_common())
        lines = [f"群文件概览（共记录 {total} 个，最近 {len(rows)} 个）｜类型分布：{cat_line}"]
        for r in rows:
            size_kb = max(1, int(r["size"] or 0) // 1024)
            lines.append(f"· {r['name']}（{size_kb}KB，{r['uploaded_at']}）")
        lines.append("建议：压缩包/文档类可归档到同名文件夹；重复大文件提醒成员自查。")
        return chr(10).join(lines)


class DirtyGuard:
    """逆天发言检测（学 nodirtymsg 思路，自研实现）：词表分级，不复制其代码。

    - severe：直接命中硬词 → 可撤回（bot 有群管理员权限时 delete_msg）；
    - warn：轻度 → 仅记录不动作。
    默认整体关闭（BOT_DIRTY_GUARD_ENABLED=false），开启也只在机器人有权限的群生效。
    """

    _SEVERE = ("港独", "台独", "藏独", "东突", "法轮", "邪教", "炸药制作", "制毒", "枪支买卖")
    _WARN = ("智障", "脑瘫", "废物", "傻逼", "去死", "狗东西")

    def __init__(self, *, delete_enabled: bool = False) -> None:
        self.delete_enabled = bool(delete_enabled)

    def assess(self, text: str) -> str:
        value = (text or "").strip()
        if not value:
            return "clean"
        if any(word in value for word in self._SEVERE):
            return "severe"
        if any(word in value for word in self._WARN):
            return "warn"
        return "clean"
