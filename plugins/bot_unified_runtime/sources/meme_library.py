"""群聊表情包库：SQLite 元数据 + 本地文件，按权重随机挑选。"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# 权重偏好：守岸人最高，其次鸣潮/战双/库洛，再次 ACG，最后普通。
_PRIORITY_HINTS = [
    (("守岸人", "岸宝"), 8.0),
    (("鸣潮", "战双帕弥什", "库洛", "库街区"), 4.0),
    (("二次元", "动漫", "游戏", "角色", "同人", "手办", "cos"), 1.5),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memes (
    md5 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    ext TEXT NOT NULL,
    group_id TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_meme INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    emotion_tags TEXT NOT NULL DEFAULT '[]',
    scene_tags TEXT NOT NULL DEFAULT '[]',
    persona_hint TEXT NOT NULL DEFAULT 'common',
    nsfw_score REAL NOT NULL DEFAULT 0.0,
    weight REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_memes_weight ON memes(weight DESC);
CREATE INDEX IF NOT EXISTS idx_memes_added_at ON memes(added_at);
"""


def _now() -> float:
    return time.time()


class MemeLibraryStore:
    """表情库：文件由调用方写入，这里只记元数据与权重。"""

    def __init__(self, db_path: str | Path, *, prefer: list[str] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.prefer = [str(item).strip() for item in (prefer or []) if str(item).strip()]
        self._lock = threading.Lock()
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _resolve_media_path(self, value: str | Path) -> Path:
        """Resolve current and legacy meme paths from the external Runtime.

        Older records stored paths such as ``data/meme_library/<file>`` relative
        to the source CWD. The database now lives in Runtime/data, so resolve
        those records relative to the database's data directory instead of the
        caller's working directory.
        """
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        normalized = str(path).replace("\\", "/")
        if normalized == "data":
            return self.db_path.parent
        if normalized.startswith("data/"):
            return self.db_path.parent / normalized[5:]
        return self.db_path.parent / path

    def exists(self, md5: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT 1 FROM memes WHERE md5=?", (md5,)).fetchone()
        return row is not None

    def add(
        self,
        *,
        md5: str,
        path: str,
        ext: str,
        group_id: str = "",
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO memes
                (md5, path, ext, group_id, added_at, weight)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (md5, str(path), str(ext).lower().lstrip("."), str(group_id), _now(), 1.0),
            )
            inserted = cursor.rowcount > 0
        return {"md5": md5, "inserted": inserted}

    def apply_tags(
        self,
        md5: str,
        *,
        is_meme: bool = True,
        description: str = "",
        emotion_tags: list[str] | None = None,
        scene_tags: list[str] | None = None,
        persona_hint: str = "common",
        nsfw_score: float = 0.0,
    ) -> None:
        emotion = json.dumps(emotion_tags or [], ensure_ascii=False)
        scene = json.dumps(scene_tags or [], ensure_ascii=False)
        text = " ".join(
            [
                description,
                * (emotion_tags or []),
                * (scene_tags or []),
                persona_hint,
            ]
        )
        weight = self._score_weight(is_meme=is_meme, nsfw_score=nsfw_score, text=text)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE memes SET is_meme=?, description=?, emotion_tags=?, scene_tags=?,
                    persona_hint=?, nsfw_score=?, weight=?
                WHERE md5=?
                """,
                (
                    1 if is_meme else 0,
                    description,
                    emotion,
                    scene,
                    persona_hint,
                    float(nsfw_score),
                    weight,
                    md5,
                ),
            )

    def _score_weight(self, *, is_meme: bool, nsfw_score: float, text: str) -> float:
        if float(nsfw_score) >= 0.8:
            return 0.0  # 高危图绝不发送
        weight = 1.0 if is_meme else 0.25
        lowered = text.lower()
        for hints, multiplier in _PRIORITY_HINTS:
            if any(hint.lower() in lowered for hint in hints):
                weight *= multiplier
        for term in self.prefer:
            if term and term.lower() in lowered:
                weight *= 2.0
        if float(nsfw_score) >= 0.2:
            weight *= 0.3
        return round(weight, 6)

    def remove(self, md5: str) -> bool:
        """删除记录与文件（NSFW 等场景）；返回是否真的删掉了文件。"""
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT path FROM memes WHERE md5=?", (md5,)).fetchone()
            if row is not None:
                try:
                    self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
                connection.execute("DELETE FROM memes WHERE md5=?", (md5,))
        return row is not None

    def mark_used(self, md5: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE memes SET used_count = used_count + 1 WHERE md5=?", (md5,)
            )

    def weighted_pick(self, *, keyword: str = "", nsfw_max: float = 0.2) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT md5, path, ext, description, emotion_tags, scene_tags, weight, nsfw_score
                FROM memes WHERE weight > 0
                ORDER BY added_at DESC
                """
            ).fetchall()
        candidates: list[dict[str, Any]] = []
        keyword = (keyword or "").strip().lower()
        for row in rows:
            row_dict = dict(row)
            tags_text = " ".join(
                [
                    row_dict.get("description", ""),
                    str(row_dict.get("emotion_tags", "")),
                    str(row_dict.get("scene_tags", "")),
                ]
            ).lower()
            if keyword and keyword not in tags_text:
                continue
            if float(row_dict.get("nsfw_score", 0.0) or 0.0) > nsfw_max:
                continue
            media_path = self._resolve_media_path(row_dict["path"])
            if not media_path.exists():
                continue
            row_dict["path"] = str(media_path)
            candidates.append(row_dict)
        if not candidates:
            return None
        weights = [max(float(item.get("weight", 1.0)), 1e-6) for item in candidates]
        picked = random.choices(candidates, weights=weights, k=1)[0]
        self.mark_used(str(picked["md5"]))
        return picked

    def stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) AS c FROM memes").fetchone()["c"]
            used = connection.execute("SELECT COALESCE(SUM(used_count),0) AS c FROM memes").fetchone()["c"]
            flagged = connection.execute("SELECT COUNT(*) AS c FROM memes WHERE nsfw_score >= 0.8").fetchone()["c"]
        return {"total": int(total), "used_total": int(used), "nsfw_blocked": int(flagged)}

    def cleanup(self, *, max_files: int = 20000, max_age_days: int = 30) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            removed = 0
            if max_age_days > 0:
                cutoff = _now() - max_age_days * 86400
                rows = connection.execute(
                    "SELECT md5, path FROM memes WHERE added_at < ?", (cutoff,)
                ).fetchall()
                for row in rows:
                    try:
                        self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
                    connection.execute("DELETE FROM memes WHERE md5=?", (row["md5"],))
                    removed += 1
            if max_files > 0:
                overflow = connection.execute("SELECT COUNT(*) AS c FROM memes").fetchone()["c"] - max_files
                if overflow > 0:
                    rows = connection.execute(
                        "SELECT md5, path FROM memes ORDER BY added_at ASC LIMIT ?",
                        (overflow,),
                    ).fetchall()
                    for row in rows:
                        try:
                            self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                        except OSError:
                            pass
                        connection.execute("DELETE FROM memes WHERE md5=?", (row["md5"],))
                        removed += 1
        return {"removed": removed}
