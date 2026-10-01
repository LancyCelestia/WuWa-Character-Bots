"""群聊表情包库：SQLite 元数据 + 本地文件，按权重随机挑选。"""

from __future__ import annotations

import json
import logging
import random
import shutil
import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.media import path_gate
from plugins.bot_unified_runtime.domains.meme.sources import persona_review
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_WINDOW,
)

logger = logging.getLogger(__name__)


class MemeMediaPathError(ValueError):
    """库行 ``path`` 折算后落在表情库容器**之外**（S-MEME-CONTAIN，2026-09-29）。

    这不是「文件不见了」，而是「这条记录想让 bot 去容器外面删文件/发文件」——
    逃逸面与缺席面必须能被分开记账，所以它是独立异常而不是 ``OSError`` 的别名，
    也绝不在此悄悄退回容器内的某个替身路径（那等于把洞换个形状留下）。
    只携带路径字符串，不携带文件内容。
    """

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

# 表情册与审批两面的指令刻度：前缀太短＝整表扫，limit 没上界＝一次拉穿内存。
# 判不出就诚实缺席——这里没有任何「放宽成扫全库/扫别处」的口子。
# ``MD5_PREFIX_MIN_LENGTH`` 是**公开名**：命令面措辞回执要引用同一枚刻度，跨模块抓
# 下划线名不合规，而起别名＝两份数字迟早分叉（本项目两枚前缀查询口共读本函数）。
MD5_PREFIX_MIN_LENGTH = 4
_PREFIX_LIMIT_MAX = 200
_MISSING_LIMIT_MAX = 5000
#: 库内一次取的 DB 行数（失配判定要在 python 侧做，所以按窗推进、不是单条 SQL 筛）。
_MISSING_WINDOW = 500
#: ``LIKE ... ESCAPE ?`` 的转义符（绑定参数传入，SQL 文本里不拼值）。
_LIKE_ESCAPE_CHAR = "!"
_HEX_DIGITS = frozenset("0123456789abcdef")

# 前缀闸门的三种拒收原因（``''``＝放行）。**唯一一把尺**：两枚前缀查询口
# （``match_md5_prefix`` / ``match_review_key``）与命令面回执都读 :func:`md5_prefix_gate`，
# 第二处判据一律算违令——回执与查询长成两张脸，就是「库里没有」和「你没说清」
# 被混进同一句话的那类误导。
MD5_PREFIX_ACCEPTED = ""
MD5_PREFIX_EMPTY = "empty"
MD5_PREFIX_TOO_SHORT = "too_short"
MD5_PREFIX_NOT_HEX = "not_hex"
MD5_PREFIX_REJECTIONS: frozenset[str] = frozenset(
    {MD5_PREFIX_EMPTY, MD5_PREFIX_TOO_SHORT, MD5_PREFIX_NOT_HEX}
)

# 家规（先例=affinity 三列、emergency_subscriptions 坐标两列）：新增列一律
# ALTER-if-missing，不重建表、不动既有行。
#   sha256        = 内容身份（发送史与隔离墓碑的键；文件名会变，md5 行也会因
#                   重新入库换 ext，只有内容哈希能跨改名/跨库认出同一张图）
#   persona_owned = 本命贴纸（守岸人主体），豁免按龄裁剪，见 ``cleanup``
#   review_state  = 待审队列位（S-MEME2-REVIEW，2026-09-29，需求 12）：
#                   ``''``=无主张（含全部存量行，逐字节旧行为）/ ``pending``=
#                   只有一条证据、等管理员点头 / ``approved``=证据齐或人已批。
#                   判据本体在 ``persona_review``，这里只存它给出的字面值。
#   native_emoji_id / native_package_id = 入库时那条 QQ 表情段自带的协议端 id
#                   （S-MEME2-MFACE）：出站腿可以据此回原生 ``mface`` 段，
#                   不必把同一张图再当普通图片传一次；空值＝没有可信 id，
#                   出站侧必须诚实回落 image 段（绝不自拼，见 onebot._sticker_segment）。
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("sha256", "ALTER TABLE memes ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''"),
    ("persona_owned", "ALTER TABLE memes ADD COLUMN persona_owned INTEGER NOT NULL DEFAULT 0"),
    ("review_state", "ALTER TABLE memes ADD COLUMN review_state TEXT NOT NULL DEFAULT ''"),
    ("native_emoji_id", "ALTER TABLE memes ADD COLUMN native_emoji_id TEXT NOT NULL DEFAULT ''"),
    (
        "native_package_id",
        "ALTER TABLE memes ADD COLUMN native_package_id TEXT NOT NULL DEFAULT ''",
    ),
)

# 依赖 ``_MIGRATIONS`` 才补齐的列（``review_state``）的索引：必须**列已齐后**再建。
# 家规＝ALTER-if-missing 先行、索引后建（先例 character/affinity.py、addressing.py）。
# 放进 ``_SCHEMA`` 会让任何全新空库在建表阶段当场抛
# ``sqlite3.OperationalError: no such column: memes.review_state``（列尚未 ALTER 出来），
# 生产老库若该列也缺席则在下次重启时同样炸——所以这枚索引绝不能与建表脚本同批执行。
# 幂等：``IF NOT EXISTS``，重复启动零副作用。
_POST_MIGRATION_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_memes_review ON memes(review_state)",
)


def _now() -> float:
    return time.time()


def _like_prefix_pattern(key: str) -> str:
    """md5 前缀 → LIKE 模式：转义符、``%``、``_`` 一律按字面化。

    进来之前先过 :func:`md5_prefix_gate`（十六进制之外的字符一个不放），所以正常
    路径下这里等于恒等。**但闸门不是它的替身**：这一枚是把「通配符放大命中集」在
    形态上焊死的第二道防线，谁哪天把闸门挪走或放宽，这道还在（``ESCAPE`` 的锁见
    ``tests/test_meme_album_commands.py``：SQL 文本里 ``ESCAPE`` 必在、绑定第二元必是
    本转义符、且 ``LIKE`` 必在 ``LIMIT`` 之前）。
    """
    escaped = key.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, _LIKE_ESCAPE_CHAR + wildcard)
    return escaped + "%"


def md5_prefix_gate(key: Any) -> str:
    """表情编号前缀的形状闸门：合格 ⇒ ``''``，否则点名原因码（**不查库**那一格）。

    清洗口径（``strip`` + ``lower``）写在这里、只写一份，两枚查询口各自先过这一句
    再拿同一串去查，回执与查询不会两张脸。三格判据：

    - 空 / 纯空白 ⇒ :data:`MD5_PREFIX_EMPTY`（调用方另有「没说编号」那一支）。
    - 短于 ``MD5_PREFIX_MIN_LENGTH`` ⇒ :data:`MD5_PREFIX_TOO_SHORT`。太短＝整表撞号，
      拒得对，但**回执不许说成「库里没有」**：那是把「你没说清」伪装成「没图可批」。
    - 十六进制之外还有一个字符 ⇒ :data:`MD5_PREFIX_NOT_HEX`。这一格把 ``%``/``_``
      与转义符 ``!`` 全部挡在 SQL 之前，:func:`_like_prefix_pattern` 由此从
      「唯一防线」降格成「第二道防线」。

    曾有过的一段假账：``match_review_key`` 的 docstring 写着「上游已只放行十六进制」，
    而审批腿的 ``key`` 是指令面**原样透传**（实测单字符前缀最大组 207 行）——一句
    没发生的事。今天这句归本函数自己执法，不再依赖调用方自觉。
    """
    prefix = str(key or "").strip().lower()
    if not prefix:
        return MD5_PREFIX_EMPTY
    if len(prefix) < MD5_PREFIX_MIN_LENGTH:
        return MD5_PREFIX_TOO_SHORT
    if not all(char in _HEX_DIGITS for char in prefix):
        return MD5_PREFIX_NOT_HEX
    return MD5_PREFIX_ACCEPTED


def md5_prefix_is_accepted(key: Any) -> bool:
    """闸门放行与否（命令面判「该不该开口要长一点的编号」用，别手抄判据）。"""
    return md5_prefix_gate(key) == MD5_PREFIX_ACCEPTED


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
        library_dir: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 容器门收窄（B3，2026-09-30）：给了库目录 ⇒ 容器=库目录本身（而非 db 的
        # 父目录=整个 data 根）。库行指向 `data/downloads` 等库外子目录的旧/污染行
        # 从此进不了发送面。``None``＝旧语义（测试桩与历史构造形逐字兼容）。
        # 空串/纯空白与 ``None`` 同义（旧语义），所以先判在场再判读数非空。
        self._library_dir: Path | None = None
        if library_dir is not None and str(library_dir).strip():
            self._library_dir = Path(library_dir)
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
            # 列齐之后再补依赖新列的索引（见 ``_POST_MIGRATION_INDEXES`` 注释）。
            for statement in _POST_MIGRATION_INDEXES:
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
        target = self.media_path_for_row(str(path or row["path"] or ""), where="ensure_content_sha")
        if target is None:
            return ""
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

    def media_container(self) -> Path:
        """贴纸文件的**容器根**（S-MEME-CONTAIN，2026-09-29 用户点名的 CRITICAL 洞）。

        收窄（B3，2026-09-30）：构造时给了 ``library_dir`` ⇒ 容器=库目录本身；
        否则退 ``db_path.parent``（旧语义：历史构造形与测试桩逐字兼容）。库行里
        既存过 ``data/meme_library/x.png``（相对源 CWD 的旧口径），也存过绝对路径，
        两者都落在同一个 Runtime 数据根下；容器收窄后，指向库外（``data/downloads``
        等别处落点）的旧行/污染行**进不了发送面**。``.resolve()`` 先把 ``..``、重复
        分隔符、符号链接/junction 折算掉，之后只问一句「解析完还在不在容器里」。
        """
        if self._library_dir is not None:
            try:
                return self._library_dir.resolve()
            except OSError:  # 解析失败也不放宽门：退回未解析的库目录。
                return self._library_dir
        try:
            return self.db_path.parent.resolve()
        except OSError:  # 解析失败也不放宽门：退回未解析的父目录。
            return self.db_path.parent

    def confine_media_path(self, candidate: Path) -> Path:
        """把已解析的路径按容器门收口；越界 ⇒ :class:`MemeMediaPathError`。

        单点判据（全仓只有这一处「库行 path → 磁盘真身」的裁决）：等于容器根本身
        也算越界——那是目录，``unlink()`` 会炸、``read_bytes()`` 会把别人的目录当图发。
        """
        resolved = candidate.resolve()
        container = self.media_container()
        if resolved == container or not resolved.is_relative_to(container):
            raise MemeMediaPathError(str(resolved))
        return resolved

    def _resolve_media_path(self, value: str | Path) -> Path:
        """Resolve current and legacy meme paths from the external Runtime.

        Older records stored paths such as ``data/meme_library/<file>`` relative
        to the source CWD. The database now lives in Runtime/data, so resolve
        those records relative to the database's data directory instead of the
        caller's working directory.

        **容器门（S-MEME-CONTAIN）**：旧实现把绝对路径**原样返回**，而本类的
        ``remove``/``cleanup`` 直接对返回值 ``unlink()``、``weighted_pick`` 直接把它
        当发送源 ⇒ 一条被污染的库行就等于「任意路径删文件 / 任意路径发图」。现在
        无论绝对还是相对，一律折算后过 :meth:`confine_media_path`；越界不静默降级
        （静默＝把逃逸藏成"这张图没了"），而是抛 :class:`MemeMediaPathError`，由各
        IO 点按各自语义处置。
        """
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            candidate = path
        else:
            normalized = str(path).replace("\\", "/")
            if normalized == "data":
                candidate = self.db_path.parent
            elif normalized.startswith("data/"):
                candidate = self.db_path.parent / normalized[5:]
            else:
                candidate = self.db_path.parent / path
        return self.confine_media_path(candidate)

    def media_path_for_row(self, value: Any, *, where: str) -> Path | None:
        """``_resolve_media_path`` 的观测包装：越界/解不开 ⇒ ``None`` + 一行 WARNING。

        只判越界与留痕，**不代做决定**——各 IO 点的正确降级不一样（选图要跳候选、
        清理要删行但不删容器外文件、补标要记 skip），把决定权留在调用点，才不会
        在这里长出第二套语义。日志只记调用点标签，不记路径（路径可能含用户目录名）。
        """
        try:
            return self._resolve_media_path(value)
        except MemeMediaPathError:
            logger.warning("meme media path outside container where=%s", where)
        except OSError:
            logger.warning("meme media path unresolvable where=%s", where)
        return None

    # ---------------------------------------------------- 表情册指令面（S-STICKER-ALBUM）

    def match_md5_prefix(self, key: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """按 md5 前缀取命中行（任意 ``review_state`` 都算；只读反查，不加锁）。

        返回形与 :meth:`missing_path_rows` **同构**：每枚是 ``{md5, path, persona_hint,
        ext}`` 的行字典。只交回裸 md5 的话，命令面就永远读不到行上的 ``persona_hint``
        （F2，2026-09-30）——「目标册＝该行提示」这条路径会退化成「一律落现役人格册」，
        还会顺手把行上原有的提示覆写掉，所以这一枚交回整行。

        空 / 短于 ``MD5_PREFIX_MIN_LENGTH`` / 非十六进制 ⇒ 直接 ``[]`` 且不查库（判据真身＝
        :func:`md5_prefix_gate`，与 :meth:`match_review_key` 同一把尺）。前缀里的
        ``%`` 与 ``_`` 按字面处理（``ESCAPE`` 绑定传入），通配符不得放大命中集。
        """
        prefix = str(key or "").strip().lower()
        if md5_prefix_gate(prefix):
            return []
        bounded = max(1, min(int(limit), _PREFIX_LIMIT_MAX))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT md5, path, persona_hint, ext FROM memes"
                " WHERE md5 LIKE ? ESCAPE ?"
                " ORDER BY added_at DESC LIMIT ?",
                (_like_prefix_pattern(prefix), _LIKE_ESCAPE_CHAR, bounded),
            ).fetchall()
        return [
            {
                "md5": str(row["md5"]),
                "path": str(row["path"] or ""),
                "persona_hint": str(row["persona_hint"] or ""),
                "ext": str(row["ext"] or ""),
            }
            for row in rows
        ]

    def relink_path(
        self,
        md5: str,
        new_path: str,
        *,
        persona_hint: str = "",
        persona_owned: bool = True,
    ) -> bool:
        """把某行的 ``path`` 改指到 ``new_path``；越界一律拒收，绝不写越界路径。

        尺只有 :meth:`media_path_for_row` 一把（其本体即 :meth:`confine_media_path`，
        越界时已经留过一行 WARNING），这里只把「判不出」翻译成 ``False``。路径串
        **照调用方给的原样入库**（口径同 :meth:`add`，读取时再折算）。
        ``persona_hint`` 空串＝不改这一列（``COALESCE(NULLIF(?, ''), 原值)``）。
        """
        if self.media_path_for_row(new_path, where="relink_path") is None:
            return False
        hint = str(persona_hint or "").strip()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memes
                   SET path=?, persona_owned=?,
                       persona_hint=COALESCE(NULLIF(?, ''), persona_hint)
                 WHERE md5=?
                """,
                (str(new_path), 1 if persona_owned else 0, hint, str(md5)),
            )
            linked = cursor.rowcount > 0
        return linked

    def missing_path_rows(self, limit: int = 500) -> list[dict[str, Any]]:
        """列出「库里有记录、盘上够不着」的行——**只报不删**，删与改道归命令面裁。

        判失配的尺同 :meth:`media_path_for_row`：越界、解不开、或解析后不是文件，
        都算失配。不因此新增任何回落基根或去别处找的通道。

        ``limit`` 数的是**报出来的失配行数**，不是库里的行数（这一点曾只在门面注释里
        写着、这里其实是裸 ``LIMIT``＝最老那批永远对不完，2026-10-01 现算纠正）：内部按
        ``_MISSING_WINDOW`` 一格一格往下翻，翻到凑够 ``limit`` 条失配或库里没有行为止。
        翻页次序是 ``added_at DESC, md5 ASC`` 的稳定全序，所以同一轮里既不重也不漏。
        """
        bounded = max(1, min(int(limit), _MISSING_LIMIT_MAX))
        out: list[dict[str, Any]] = []
        offset = 0
        while len(out) < bounded:
            window = min(_MISSING_WINDOW, bounded)
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT md5, path, persona_hint, ext, review_state FROM memes"
                    " ORDER BY added_at DESC, md5 ASC LIMIT ? OFFSET ?",
                    (window, offset),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                target = self.media_path_for_row(row["path"], where="missing_path_rows")
                if target is not None and target.is_file():
                    continue
                out.append(
                    {
                        "md5": str(row["md5"]),
                        "path": str(row["path"]),
                        "persona_hint": str(row["persona_hint"] or ""),
                        "ext": str(row["ext"] or ""),
                        "review_state": str(row["review_state"] or ""),
                    }
                )
                if len(out) >= bounded:
                    break
            offset += len(rows)
            if len(rows) < window:
                break  # 库已见底
        return out

    def admit_into_album(self, md5: str, album_dir: str | Path, *, persona_hint: str = "") -> str:
        """把贴纸文件搬进 ``album_dir`` 并让库行改道跟过去。

        返回只取七个字面：``moved`` / ``no_row`` / ``no_file`` / ``escape`` /
        ``duplicate_name`` / ``not_admitted`` / ``error``。其中 ``not_admitted``＝该行
        还没过审（出处门，见下）。目标越界判定复用 :mod:`domains.media.path_gate`
        的 :func:`~plugins.bot_unified_runtime.domains.media.path_gate.contain_within`
        （两侧都折算），**判定先于 mkdir**，不自写第二把 resolve 比较尺。
        旧行越界与旧文件缺席同落 ``no_file``：没有任何东西被搬动，库行原样不动。
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path, ext, group_id, review_state FROM memes WHERE md5=?",
                (str(md5),)
            ).fetchone()
        if row is None:
            return "no_row"
        # 入册＝把这张图交给别的会话看，所以只准已过审的行进册。群聊收来的图
        # （`review_state` 为 ''/pending）一律拒：贴纸腿是纯文件遍历、不过 DB 判据，
        # 一张图一旦进了人格册就等着被主动发出去。
        if str(row["review_state"] or "").strip() != persona_review.ADMIT:
            return "not_admitted"
        source = self.media_path_for_row(row["path"], where="admit_into_album")
        if source is None or not source.is_file():
            return "no_file"
        try:
            target = path_gate.contain_within(
                Path(str(album_dir or "")).expanduser() / source.name,
                [self.media_container()],
                base=self.db_path.parent,
            )
        except path_gate.PathEscapeError:
            return "escape"
        if target.exists():
            return "duplicate_name"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except (OSError, shutil.Error):
            logger.warning("meme album move failed md5=%s", md5)
            return "error"
        hint = str(persona_hint or "").strip()
        try:
            with self._lock, self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE memes
                       SET path=?, persona_owned=?,
                           persona_hint=COALESCE(NULLIF(?, ''), persona_hint)
                     WHERE md5=?
                    """,
                    (str(target), 1, hint, str(md5)),
                )
            # 文件已经搬走而行没被改（0 行）＝账实分家，不能宣成 ``moved``：
            # 报错并回滚，让「盘上有、账上没有」这一格永远不成立。
            if int(getattr(cursor, "rowcount", 0) or 0) != 1:
                raise sqlite3.Error("album admit updated no row")
        except sqlite3.Error:
            logger.warning("meme album relink failed md5=%s", md5)
            try:
                shutil.move(str(target), str(source))
            except (OSError, shutil.Error):
                # 回滚也没成：文件在册目录、库行仍指旧位置——下一轮
                # ``missing_path_rows`` 会把它报出来，``relink_path`` 能收；这里绝不删行。
                logger.error("meme album rollback failed md5=%s 需人工收", md5)
            return "error"
        return "moved"

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
        native_emoji_id: str = "",
        native_package_id: str = "",
    ) -> dict[str, Any]:
        sha = str(content_sha256 or "").strip().lower()
        # id 一律照原样存（不筛形态）：能不能出 mface 段由出站腿那把唯一硬尺判
        # 硬门判（``transport.sender.onebot._sticker_segment``），这里筛形态＝第二判据。
        emoji_id = str(native_emoji_id or "").strip()[:64]
        package_id = str(native_package_id or "").strip()[:64]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO memes
                (md5, path, ext, group_id, added_at, weight, sha256, persona_owned,
                 native_emoji_id, native_package_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    emoji_id,
                    package_id,
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

    def _score_weight(
        self, *, is_meme: bool, nsfw_score: float, text: str, persona_credit: bool = True
    ) -> float:
        """权重真身（唯一算分处）。

        ``persona_credit=False`` 只停**本命那一档**（``_PRIORITY_HINTS`` 首档 8.0），
        其余折扣逐字不变——这是 S-MEME2-REVIEW 的落点：待审图的「她」是未经确认的
        模型主张，不配顶到选图前排，但它仍然是张合法梗图（普通 prefer/ACG 档照吃）。
        缺省 ``True``＝旧行为，存量行一律不变。
        """
        if float(nsfw_score) >= 0.8:
            return 0.0  # 高危图绝不发送
        weight = 1.0 if is_meme else 0.25
        lowered = text.lower()
        tiers = _PRIORITY_HINTS if persona_credit else _PRIORITY_HINTS[1:]
        for hints, multiplier in tiers:
            if any(hint.lower() in lowered for hint in hints):
                weight *= multiplier
        for term in self.prefer:
            if term and term.lower() in lowered:
                weight *= 2.0
        if float(nsfw_score) >= 0.2:
            weight *= 0.3
        return round(weight, 6)

    # ------------------------------------------------------------ 待审队列

    @staticmethod
    def _row_tag_text(row: Any) -> str:
        """从库行重建成 ``apply_tags`` 当年喂给权重函数的那段文本（同一把尺）。"""
        parts: list[str] = [str(row["description"] or "")]
        for column in ("emotion_tags", "scene_tags"):
            raw = str(row[column] or "")
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                parts.extend(str(item) for item in parsed)
            else:
                parts.append(raw)
        parts.append(str(row["persona_hint"] or ""))
        return " ".join(parts)

    def set_review_state(self, md5: str, state: str) -> bool:
        """写队列位并**按状态重算权重**（S-MEME2-REVIEW 的执法点）。

        ``approved`` ⇒ 标本命 + 本命加权复档；``pending`` ⇒ 不标本命 + 停本命档；
        ``''`` ⇒ 无主张（只清队列位，权重按旧口径复算，存量行零位移）。
        返回该行是否存在——不存在就是不存在，绝不静默建行（去重/墓碑的账还在别处）。
        """
        safe_state = str(state or "").strip()
        if safe_state not in ("", persona_review.PENDING, persona_review.ADMIT):
            raise ValueError(f"unknown review state: {safe_state!r}")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT description, emotion_tags, scene_tags, persona_hint, is_meme,"
                " nsfw_score FROM memes WHERE md5=?",
                (str(md5),),
            ).fetchone()
            if row is None:
                return False
            weight = self._score_weight(
                is_meme=bool(row["is_meme"]),
                nsfw_score=float(row["nsfw_score"] or 0.0),
                text=self._row_tag_text(row),
                persona_credit=(safe_state != persona_review.PENDING),
            )
            connection.execute(
                "UPDATE memes SET review_state=?, weight=?, persona_owned=? WHERE md5=?",
                (
                    safe_state,
                    weight,
                    1 if safe_state == persona_review.ADMIT else 0,
                    str(md5),
                ),
            )
        return True

    def reject_review(self, md5: str, *, ledger: Any = None, reason: str = "manual_review_reject") -> bool:
        """人审拒绝 ⇒ 删行删文件 + 内容级墓碑（同图重发不复活，口径同 NSFW 删除）。

        注入 ``ledger`` 时同时记到该账本（测试/外部账）；库自己的默认墓碑账本由
        :meth:`remove` 负责，两条路都不许留「删了但没立碑」的半截状态。
        """
        sha = ""
        with self._connect() as connection:
            row = connection.execute("SELECT sha256, path FROM memes WHERE md5=?", (str(md5),)).fetchone()
        if row is not None:
            sha = str(row["sha256"] or "").strip().lower()
            if not sha:
                target = self.media_path_for_row(row["path"], where="reject_review")
                if target is not None:
                    from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
                        content_sha256_of_path,
                    )

                    sha = content_sha256_of_path(target) or ""
        removed = bool(self.remove(str(md5), tombstone_reason=reason))
        if ledger is not None and sha:
            try:
                ledger.add(sha, reason=reason[:120])
            except Exception:  # noqa: BLE001 - 外部账本写不进去不许改删除结果。
                logger.warning("meme review reject ledger add failed md5=%s", md5)
        return removed

    def list_review(self, state: str = persona_review.PENDING, *, limit: int = 20) -> list[dict[str, Any]]:
        """队列查询面：按状态列行（md5/描述/权重/路径），供审批与统计用。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT md5, description, weight, path, review_state FROM memes"
                " WHERE review_state=? ORDER BY added_at DESC LIMIT ?",
                (str(state or ""), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def match_review_key(
        self, key: str, *, state: str | None = persona_review.PENDING, limit: int = 50
    ) -> list[dict[str, Any]]:
        """管理员给的短前缀 → 匹配到的行（0/1/N 三种都由调用方分辨）。

        本件**不**替调用方决定「不唯一怎么办」——列出来交给命令面说破，比在这里
        悄悄挑一张诚实（猜＝替管理员签了他没写的字）。

        **形状闸门在本函数自己这儿**（:func:`md5_prefix_gate`，与
        :meth:`match_md5_prefix` 同一把尺）：空 / 短于 ``MD5_PREFIX_MIN_LENGTH`` /
        十六进制之外还有一个字符 ⇒ ``[]`` 且**一次 SQL 都不发**。旧 docstring 把这
        件事记成「上游已只放行十六进制」，而审批腿的 ``key`` 是指令面原样透传——那句
        当时没发生。命令面要先问同一枚闸门再措辞回执：「前缀太短」不能说成「没图可批」。

        ``state`` 这一维只有一处可动：``None`` ⇒ **不按队列位设限**（只给「审批落子」
        那条腿用）。存量行的 ``review_state`` 是空串而不是 ``pending``，把可批集合焊死
        在 ``pending`` 上＝那批行在结构上永远批不动，而回执却指着管理员「先去审批」——
        断头路。非 ``None``（拒绝那条腿）照旧带 ``review_state=?``：**可删集合宽度一寸
        不放宽**（删行删文件加立墓碑＝不可逆，「空串行要不要也拒得动」另立一票）。

        两条腿共用一条 SQL 骨架，前缀收窄**永远发生在** ``LIMIT`` **之前**（SQL 侧
        ``md5 LIKE ? ESCAPE ?``，值走绑定参数）。曾经的写法是「设限那一支先 ``LIMIT``
        截断、再在 python 侧筛前缀」⇒ 那一支只对最新 N 行有效：实测 60 枚新 pending
        把 1 枚老 pending 挤出窗口，拒绝落 ``not_found`` 而行仍在——把洞换个尺寸留下。
        """
        needle = str(key or "").strip().lower()
        if md5_prefix_gate(needle):
            return []
        conditions = ["md5 LIKE ? ESCAPE ?"]
        params: list[Any] = [_like_prefix_pattern(needle), _LIKE_ESCAPE_CHAR]
        if state is not None:
            conditions.append("review_state=?")
            params.append(str(state or ""))
        sql = (
            "SELECT md5, description, path, review_state FROM memes"
            " WHERE " + " AND ".join(conditions) + " ORDER BY added_at DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def remove(self, md5: str, *, tombstone_reason: str = "") -> bool:
        """删除记录与文件（NSFW 等场景）；返回是否真的删掉了文件。

        ``tombstone_reason`` 非空时同时立**内容级墓碑**：只删行删文件的话，
        同一张图再被发一次会原样复活（重新入库、重新打标、重新可发送）——
        这是旧实现的真实漏口。墓碑写失败不改删除结果（文件照删，证据另有 WARNING）。
        """
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT path, sha256 FROM memes WHERE md5=?", (md5,)).fetchone()
        sha = ""
        media_target = self.media_path_for_row(row["path"], where="remove") if row is not None else None
        if row is not None and str(tombstone_reason or "").strip():
            sha = str(row["sha256"] or "").strip().lower()
            if not sha:
                # 必须在删文件**之前**算：文件一 unlink 就再也拿不到内容身份了。
                from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
                    content_sha256_of_path,
                )

                sha = (
                    content_sha256_of_path(media_target)
                    if media_target is not None
                    else ""
                ) or ""
        with self._lock, self._connect() as connection:
            if row is not None:
                if media_target is not None:
                    # 越界 path 的文件**一个字节都不碰**：行照删（账本要干净），
                    # 盘上那个容器外的东西不归本库处置（那正是逃逸要保住的现场）。
                    try:
                        media_target.unlink(missing_ok=True)
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
                       weight, nsfw_score, sha256, review_state,
                       native_emoji_id, native_package_id
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
            media_path = self.media_path_for_row(row_dict["path"], where="weighted_pick")
            if media_path is None or not media_path.exists():
                # 越界行不参选（否则就是把容器外的文件当贴纸发出去，还可能发给第三者）。
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
            media_path = self.media_path_for_row(row_dict["path"], where="count_sendable")
            if media_path is None or not media_path.exists():
                continue
            sha = str(row_dict.get("sha256", "") or "").strip().lower()
            if already and sha and sha in already:
                continue
            count += 1
        return count

    def list_untagged(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """未打标图片（description 为空），启动补标队列用；md5+path+来源位。

        ``group_id`` 一并给出：它同时是**来源线索**（离线导入写成 ``pack:<包名>``），
        补标腿要靠它凑齐本命准入的第二条证据（判据见 ``persona_review``）。
        """
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT md5, path, group_id FROM memes
                WHERE IFNULL(description, '') = ''
                ORDER BY added_at ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {"md5": str(row["md5"]), "path": str(row["path"]), "group_id": str(row["group_id"] or "")}
            for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) AS c FROM memes").fetchone()["c"]
            used = connection.execute("SELECT COALESCE(SUM(used_count),0) AS c FROM memes").fetchone()["c"]
            flagged = connection.execute("SELECT COUNT(*) AS c FROM memes WHERE nsfw_score >= 0.8").fetchone()["c"]
            persona = connection.execute(
                "SELECT COUNT(*) AS c FROM memes WHERE persona_owned = 1"
            ).fetchone()["c"]
            # 待审队列（S-MEME2-REVIEW）：证据不齐的图**有专门的队列位**，不再拿
            # 「描述句为空」当替身——旧替身把「从没打过标」和「打过标但没认出主角」
            # 混成一个数，管理员看到的就是假数。两个数分开报，各说各的事。
            pending = connection.execute(
                "SELECT COUNT(*) AS c FROM memes WHERE review_state = ?",
                (persona_review.PENDING,),
            ).fetchone()["c"]
            untagged = connection.execute(
                "SELECT COUNT(*) AS c FROM memes WHERE IFNULL(description, '') = ''"
            ).fetchone()["c"]
        out: dict[str, Any] = {
            "total": int(total),
            "used_total": int(used),
            "nsfw_blocked": int(flagged),
            "persona_owned": int(persona),
            "pending_review": int(pending),
            "untagged": int(untagged),
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
                    # 越界行：删行、不删容器外的文件（同 remove 的口径）。
                    media_target = self.media_path_for_row(row["path"], where="cleanup_age")
                    if media_target is not None:
                        try:
                            media_target.unlink(missing_ok=True)
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
                        media_target = self.media_path_for_row(row["path"], where="cleanup_cap")
                        if media_target is not None:
                            try:
                                media_target.unlink(missing_ok=True)
                            except OSError:
                                pass
                        connection.execute("DELETE FROM memes WHERE md5=?", (row["md5"],))
                        removed += 1
        return {"removed": removed}
