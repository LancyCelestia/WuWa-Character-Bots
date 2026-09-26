"""群聊表情包库：SQLite 元数据 + 本地文件，按权重随机挑选。"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_WINDOW,
)

# 权重偏好：守岸人最高，其次鸣潮/战双/库洛，再次 ACG，最后普通。
_PRIORITY_HINTS = [
    (("守岸人", "岸宝"), 8.0),
    (("鸣潮", "战双帕弥什", "库洛", "库街区"), 4.0),
    (("二次元", "动漫", "游戏", "角色", "同人", "手办", "cos"), 1.5),
]
#: 上表的词展平视图：选图侧（``meme_selection.default_vocabulary``）拿它当主题词表，
#: 只读派生、不另立一份名单——「哪算本命/哪算同好」这张表的本体仍是 ``_PRIORITY_HINTS``。
PRIORITY_HINT_TERMS: tuple[str, ...] = tuple(
    term for hints, _multiplier in _PRIORITY_HINTS for term in hints
)

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

# 单次随机挑选最多回读的候选行数（按 added_at 取最新）。库上限 2 万行时
# 全表回读 + 逐行 stat() 会拖慢 /偷表情 命令；有界扫描把最坏成本封顶。
_PICK_SCAN_LIMIT = 1000
# 一次挑选最多补算多少张图的内容哈希（见 ``ensure_content_sha``）：哈希一次
# 落库永久复用，所以这条上限只在「旧库首次过筛」时生效，之后为 0 成本。
_SHA_FILL_LIMIT = 64

# 家规（先例=affinity 三列、emergency_subscriptions 坐标两列）：新增列一律
# ALTER-if-missing，不重建表、不动既有行。
#   sha256        = 内容身份（发送史与隔离墓碑的键；文件名会变，md5 行也会因
#                   重新入库换 ext，只有内容哈希能跨改名/跨库认出同一张图）
#   persona_owned = 本命贴纸（守岸人主体），豁免按龄裁剪，见 ``cleanup``
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("sha256", "ALTER TABLE memes ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''"),
    ("persona_owned", "ALTER TABLE memes ADD COLUMN persona_owned INTEGER NOT NULL DEFAULT 0"),
)


def _now() -> float:
    return time.time()


class MemeLibraryStore:
    """表情库：文件由调用方写入，这里只记元数据与权重。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        prefer: list[str] | None = None,
        history: Any | None = None,
        no_repeat: bool = True,
        history_window: int = DEFAULT_WINDOW,
        history_retention_days: int = DEFAULT_RETENTION_DAYS,
        default_scope: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.prefer = [str(item).strip() for item in (prefer or []) if str(item).strip()]
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(memes)")
            }
            for name, statement in _MIGRATIONS:
                if name not in columns:
                    connection.execute(statement)
        # ---- 反重复：本文件是三条发送腿的共同咽喉，账本就挂在这里 ----
        # ``no_repeat=False`` 或账本构造失败 ⇒ 逐字节退回旧行为（宁可可能重发，
        # 也不因为一个新挂载点把表情功能整个打死）。生产缺省开。
        self.no_repeat = bool(no_repeat)
        self.default_scope = default_scope
        self._history_window = int(history_window)
        self._history_retention_days = int(history_retention_days)
        self._history_explicit = history
        self._history: Any | None = history if history is not None else None
        self._history_attempted = history is not None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    # -------------------------------------------------------------- 反重复账本

    @property
    def history(self) -> Any | None:
        """惰性构造的发送史（缺省落在库文件旁边，一起被 runtime_paths 重映射）。

        根装配文件构造本类时不传 ``history``（它只给 ``db_path`` 与 ``prefer``），
        而反重复必须是「不改调用点也生效」的硬机制 ⇒ 缺省路径由本库自身派生：
        ``<表情库目录>/meme_send_history.sqlite3``。``BOT_RUNTIME_DATA_DIR`` 的重映射
        发生在 Config 里，所以本目录已经指向 ChatBot_Runtime，源码树零写入。
        """
        if not self.no_repeat:
            return None
        # S-RANDPIC-LEDGER2（2026-09-26，贴纸族并发验证抓到的真竞态）：「置 attempted」
        # 与「构造完成」原来不在同一把锁里——A 线程刚置 True、store 还没建好时，
        # B 线程从这里领走一个 None，整条咽喉退回「无账本」旧行为，同贴库并发
        # 实测双发（tests/test_randpic_no_repeat_ledger.py E 组锁）。锁内建一次，
        # 旁观者只会等锁、不会再领半件。所有 self.history 调用点都在方法入口、
        # 不在本类 _lock 块内，此处加锁无重入死锁面。
        with self._lock:
            if self._history_attempted:
                return self._history
            self._history_attempted = True
            try:
                from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
                    MemeSendHistoryStore,
                )

                self._history = MemeSendHistoryStore(
                    self.db_path.parent / "meme_send_history.sqlite3",
                    window=self._history_window,
                    retention_days=self._history_retention_days,
                )
            except Exception:  # noqa: BLE001 - 账本打不开只是失去反重复，不带走选图。
                self._history = None
            return self._history

    def set_history(self, history: Any | None) -> None:
        """注入/关闭账本（测试与装配层用；传 ``None`` 即禁用反重复）。"""
        with self._lock:
            self._history = history
            self._history_attempted = True

    def ensure_content_sha(self, md5: str, *, path: str | Path) -> str:
        """补算并回写某一行的内容哈希；已有则直接返回（一次算，永久复用）。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sha256, path FROM memes WHERE md5=?", (str(md5),)
            ).fetchone()
        if row is None:
            return ""
        known = str(row["sha256"] or "").strip().lower()
        if known:
            return known
        target = self._resolve_media_path(str(path or row["path"] or ""))
        from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
            content_sha256_of_path,
        )

        digest = content_sha256_of_path(target) or ""
        if digest:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "UPDATE memes SET sha256=? WHERE md5=? AND IFNULL(sha256,'')=''",
                    (digest, str(md5)),
                )
        return digest

    def live_content_hashes(self) -> set[str]:
        """库内现存的全部内容哈希（发送史 ``prune(live_hashes=…)`` 的真相源）。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT sha256 FROM memes WHERE IFNULL(sha256,'') <> ''"
            ).fetchall()
        return {str(row["sha256"]).strip().lower() for row in rows if str(row["sha256"]).strip()}

    def sent_content_hashes(self, *, scope: str | None = None) -> frozenset[str]:
        history = self.history
        if history is None:
            return frozenset()
        return history.sent_hashes(scope=scope or self.default_scope)

    def recent_sticker_sends(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """最近发出的贴纸 + **为什么发它**（归因串），按时间倒序。

        S-STICKER-FINAL 的查询面：她事后问「你刚为什么发这张」，管理员侧
        从这里读（sha → 库行 md5/description + 账本 reason）。不含文件路径与
        用户原文；``history`` 未启用（``no_repeat=False`` 旧行为档）时返回空表，
        诚实反映「这一档不记账」。
        """
        history = self.history
        if history is None:
            return []
        try:
            rows = history.recent_sends(limit=max(1, int(limit)))
        except Exception:  # noqa: BLE001 - 查询面失败回空表，绝不影响主链路。
            return []
        by_sha: dict[str, dict[str, Any]] = {}
        if rows:
            for lib_row in self.live_rows_with_sha():
                key = str(lib_row.get("sha256", "") or "").strip().lower()
                if key:
                    by_sha.setdefault(key, lib_row)
        out: list[dict[str, Any]] = []
        for row in rows:
            sha = str(row.get("content_sha256", ""))
            lib = by_sha.get(sha) or {}
            out.append(
                {
                    "content_sha256": sha,
                    "md5": str(lib.get("md5", "") or ""),
                    "description": str(lib.get("description", "") or ""),
                    "reason": str(row.get("reason", "") or ""),
                    "sent_at": float(row.get("sent_at", 0.0) or 0.0),
                }
            )
        return out

    def live_rows_with_sha(self) -> list[dict[str, Any]]:
        """全部带内容哈希的库行（md5/description/sha256），查询面用。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT md5, description, sha256 FROM memes WHERE IFNULL(sha256,'') <> ''"
            ).fetchall()
        return [dict(row) for row in rows]

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
        content_sha256: str = "",
        persona_owned: bool = False,
    ) -> dict[str, Any]:
        sha = str(content_sha256 or "").strip().lower()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO memes
                (md5, path, ext, group_id, added_at, weight, sha256, persona_owned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    md5,
                    str(path),
                    str(ext).lower().lstrip("."),
                    str(group_id),
                    _now(),
                    1.0,
                    sha,
                    1 if persona_owned else 0,
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted and sha:
                # 同一内容换 md5/换 ext 再入库时，把哈希认领到旧行以外的新行即可；
                # 反向（旧行没哈希）由 ensure_content_sha 懒补。
                pass
        return {"md5": md5, "inserted": inserted}

    def mark_persona_owned(self, md5: str, *, owned: bool = True) -> None:
        """标记/取消「本命贴纸」（主体是守岸人）：豁免按龄裁剪，见 ``cleanup``。"""
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE memes SET persona_owned=? WHERE md5=?",
                (1 if owned else 0, str(md5)),
            )

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

    def remove(self, md5: str, *, tombstone_reason: str = "") -> bool:
        """删除记录与文件（NSFW 等场景）；返回是否真的删掉了文件。

        ``tombstone_reason`` 非空时同时立**内容级墓碑**：只删行删文件的话，
        同一张图再被发一次会原样复活（重新入库、重新打标、重新可发送）——
        这是旧实现的真实漏口。墓碑写失败不改删除结果（文件照删，证据另有 WARNING）。
        """
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT path, sha256 FROM memes WHERE md5=?", (md5,)).fetchone()
        sha = ""
        if row is not None and str(tombstone_reason or "").strip():
            sha = str(row["sha256"] or "").strip().lower()
            if not sha:
                # 必须在删文件**之前**算：文件一 unlink 就再也拿不到内容身份了。
                from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
                    content_sha256_of_path,
                )

                sha = content_sha256_of_path(self._resolve_media_path(str(row["path"]))) or ""
        with self._lock, self._connect() as connection:
            if row is not None:
                try:
                    self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
                connection.execute("DELETE FROM memes WHERE md5=?", (md5,))
        if row is not None and sha and str(tombstone_reason or "").strip():
            try:
                from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
                    MemeQuarantineLedger,
                )

                MemeQuarantineLedger(self.db_path.parent / "meme_send_history.sqlite3").add(
                    sha, reason=str(tombstone_reason)[:120]
                )
            except Exception:  # noqa: BLE001, S110 - 立碑失败不许影响删除本身。
                pass
        return row is not None

    def mark_used(self, md5: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE memes SET used_count = used_count + 1 WHERE md5=?", (md5,)
            )

    def weighted_pick(
        self,
        *,
        keyword: str = "",
        nsfw_max: float = 0.2,
        scope: str | None = None,
        context: Any | None = None,
        min_relevance: float | None = None,
        persona_terms: Sequence[str] = (),
    ) -> dict[str, Any] | None:
        """挑一张**没发过**的表情；没有合格候选就返回 ``None``（绝不重发）。

        三条腿（``/偷表情``、回复后情绪表情包、戳一戳表情包形态）都汇到这里，
        所以「同一张贴纸绝不发第二次」这一条硬约束做在本函数，不改任何调用点
        即生效。新增形参全部可选：

        * ``scope``：会话/群作用域。判定取「该作用域 ∪ 全局保留作用域」并集，
          因此缺省（``None``→全局）就是最严口径「本机发过就不再发」。
        * ``context``：:class:`~meme_selection.StickerContext`。给了就走
          **确定性**打分（分数降序、同分按内容哈希升序取第一张可占坑者）；
          不给则保持旧的加权随机，只是在随机池上先剔掉发过的。
        * ``min_relevance``：相关性地板（只有给了 ``context`` 才有意义）。

        ``None`` 的两种含义都由调用方现有的「没有表情」分支承接：库空/全部发过/
        全部不合格。任何一条都不回退成「挑一张发过的发出去」。
        """
        history = self.history
        scan_limit = _PICK_SCAN_LIMIT
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT md5, path, ext, description, emotion_tags, scene_tags,
                       weight, nsfw_score, sha256
                FROM memes WHERE weight > 0
                ORDER BY added_at DESC
                LIMIT ?
                """,
                (scan_limit,),
            ).fetchall()
        candidates: list[dict[str, Any]] = []
        keyword_text = (keyword or "").strip().lower()
        sha_fill_budget = _SHA_FILL_LIMIT if history is not None else 0
        for row in rows:
            row_dict = dict(row)
            tags_text = " ".join(
                [
                    row_dict.get("description", ""),
                    str(row_dict.get("emotion_tags", "")),
                    str(row_dict.get("scene_tags", "")),
                ]
            ).lower()
            if keyword_text and keyword_text not in tags_text:
                continue
            if float(row_dict.get("nsfw_score", 0.0) or 0.0) > nsfw_max:
                continue
            media_path = self._resolve_media_path(row_dict["path"])
            if not media_path.exists():
                continue
            row_dict["path"] = str(media_path)
            sha = str(row_dict.get("sha256", "") or "").strip().lower()
            if not sha and sha_fill_budget > 0:
                sha = self.ensure_content_sha(str(row_dict["md5"]), path=media_path)
                sha_fill_budget -= 1
            row_dict["content_sha256"] = sha
            if history is not None and not sha:
                # 身份算不出来（文件读不到/哈希被关掉）= 无法保证不重发 ⇒ 不参选。
                continue
            candidates.append(row_dict)
        if history is not None:
            already = history.sent_hashes(scope=scope or self.default_scope)
            if already:
                candidates = [
                    item
                    for item in candidates
                    if str(item.get("content_sha256", "")) not in already
                ]
        if not candidates:
            return None
        from plugins.bot_unified_runtime.domains.meme.sources import meme_selection

        if context is None:
            # 旧口径：合格池内加权随机（同图不再被抽中的保证来自上面的过滤）。
            # 归因（S-STICKER-FINAL）：这条腿没有四因打分，账本如实记 random
            # （外加关键词是否给了的**形态**代号——不存用户输入的关键词原文）。
            weights = [max(float(item.get("weight", 1.0)), 1e-6) for item in candidates]
            random_reason = "why=random|kw=" + ("given" if keyword_text else "none")
            for _attempt in range(len(candidates)):
                picked = random.choices(candidates, weights=weights, k=1)[0]
                if history is None or meme_selection.claim_for_send(
                    history,
                    str(picked["content_sha256"]),
                    scope or self.default_scope,
                    random_reason,
                ):
                    self.mark_used(str(picked["md5"]))
                    picked["sticker_reason"] = random_reason
                    return picked
                weights = [
                    1e-6 if item is picked else max(float(item.get("weight", 1.0)), 1e-6)
                    for item in candidates
                ]
            return None
        floor = (
            float(min_relevance)
            if min_relevance is not None
            else float(meme_selection.NEUTRAL_RELEVANCE)
        )
        chosen = meme_selection.select_sticker(
            candidates,
            context,
            history=history,
            scope=scope or self.default_scope,
            persona_terms=persona_terms,
            min_relevance=floor,
        )
        if chosen is None:
            return None
        self.mark_used(str(chosen.candidate["md5"]))
        result = dict(chosen.candidate)
        result["sticker_reason"] = meme_selection.attribution_for(chosen, context)
        return result

    def eligible_count(
        self, *, keyword: str = "", nsfw_max: float = 0.2, scope: str | None = None
    ) -> int:
        """还有多少张没发过的可选（``/偷表情`` 空手时该说「都发过了」的依据）。"""
        history = self.history
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT md5, path, ext, description, emotion_tags, scene_tags, nsfw_score, sha256
                FROM memes WHERE weight > 0
                ORDER BY added_at DESC
                LIMIT ?
                """,
                (_PICK_SCAN_LIMIT,),
            ).fetchall()
        keyword_text = (keyword or "").strip().lower()
        already = history.sent_hashes(scope=scope or self.default_scope) if history else frozenset()
        count = 0
        for row in rows:
            row_dict = dict(row)
            tags_text = " ".join(
                [
                    row_dict.get("description", ""),
                    str(row_dict.get("emotion_tags", "")),
                    str(row_dict.get("scene_tags", "")),
                ]
            ).lower()
            if keyword_text and keyword_text not in tags_text:
                continue
            if float(row_dict.get("nsfw_score", 0.0) or 0.0) > nsfw_max:
                continue
            if not self._resolve_media_path(str(row_dict["path"])).exists():
                continue
            sha = str(row_dict.get("sha256", "") or "").strip().lower()
            if already and sha and sha in already:
                continue
            count += 1
        return count

    def list_untagged(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """未打标图片（description 为空），启动补标队列用；md5+path。"""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT md5, path FROM memes
                WHERE IFNULL(description, '') = ''
                ORDER BY added_at ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {"md5": str(row["md5"]), "path": str(row["path"])} for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) AS c FROM memes").fetchone()["c"]
            used = connection.execute("SELECT COALESCE(SUM(used_count),0) AS c FROM memes").fetchone()["c"]
            flagged = connection.execute("SELECT COUNT(*) AS c FROM memes WHERE nsfw_score >= 0.8").fetchone()["c"]
            persona = connection.execute(
                "SELECT COUNT(*) AS c FROM memes WHERE persona_owned = 1"
            ).fetchone()["c"]
        out: dict[str, Any] = {
            "total": int(total),
            "used_total": int(used),
            "nsfw_blocked": int(flagged),
            "persona_owned": int(persona),
        }
        history = self.history
        if history is not None:
            try:
                out["already_sent"] = int(history.stats(scope=self.default_scope)["global_sent"])
                out["remaining"] = max(0, int(total) - out["already_sent"])
            except Exception:  # noqa: BLE001 - 账本读不到不影响统计面其余三项。
                out["already_sent"] = -1
        return out

    def cleanup(
        self,
        *,
        max_files: int = 20000,
        max_age_days: int = 30,
        protect_persona: bool = True,
    ) -> dict[str, Any]:
        """按龄/按量裁剪；``protect_persona=True`` 时**本命贴纸豁免按龄裁剪**。

        豁免只针对「按天」这一刀（守岸人本体的图是收藏，不是流水）；按量上限
        仍然生效，否则「全部标成本命」就能让库无界增长。``max_files`` 那一刀
        仍从最旧的非本命开始裁，本命只在溢出无可裁时才动。
        """
        persona_guard = " AND persona_owned = 0" if protect_persona else ""
        with self._lock, self._connect() as connection:
            removed = 0
            if max_age_days > 0:
                cutoff = _now() - max_age_days * 86400
                rows = connection.execute(
                    f"SELECT md5, path FROM memes WHERE added_at < ?{persona_guard}",
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    try:
                        self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
                    connection.execute("DELETE FROM memes WHERE md5=?", (row["md5"],))
                    removed += 1
            if max_files > 0:
                live = connection.execute("SELECT COUNT(*) AS c FROM memes").fetchone()["c"]
                overflow = live - max_files
                if overflow > 0:
                    # 按量上限**不被本命豁免**（否则「全标本命」就能让库无界增长）；
                    # 豁免只体现在淘汰次序：先裁非本命、由旧到新，本命排在最后。
                    guard = " WHERE persona_owned = 0" if protect_persona else ""
                    rows = connection.execute(
                        f"""
                        SELECT md5, path FROM memes{guard}
                        ORDER BY persona_owned ASC, added_at ASC LIMIT ?
                        """,
                        (overflow,),
                    ).fetchall()
                    if protect_persona and len(rows) < overflow:
                        # 非本命已经裁光还是超：此时连本命一起裁（上限优先于豁免）。
                        extra = connection.execute(
                            """
                            SELECT md5, path FROM memes WHERE persona_owned = 1
                            ORDER BY added_at ASC LIMIT ?
                            """,
                            (overflow - len(rows),),
                        ).fetchall()
                        rows = list(rows) + list(extra)
                    for row in rows:
                        try:
                            self._resolve_media_path(row["path"]).unlink(missing_ok=True)
                        except OSError:
                            pass
                        connection.execute("DELETE FROM memes WHERE md5=?", (row["md5"],))
                        removed += 1
        return {"removed": removed}
