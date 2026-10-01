"""媒体归档存储层（bot.media_archive）：sha256 去重 + 类别×IP 目录 + JSON 旁车。

设计（照抄表情库/eat 先例）：
- 目录布局：``<root>/<类别>/<IP>/<yyyymmdd_HHMMSS>_<sha8>.<ext>``，类别与 IP
  由 VLM 判定或指令指定，全部经 ``sanitize_dirname`` 清洗（防路径穿越）。
- 文件是事实来源，SQLite 只做索引（eat 先例）；旁车 ``<同名>.json`` 存完整
  元数据（来源会话/发送者/VLM 标签/NSFW 分），人可读可迁移。
- 归档是**永久保存**（用户自己的档案库），不做 TTL 清理——与表情库的
  FIFO+TTL 相反，这里没有 cleanup。
- 落盘根目录必须经 config.py ``path_fields`` 重映射到 Runtime（漏登会写进
  源码树，DATAFIX 教训）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..digest import media_digest

# 内容类别固定集（VLM 从中选；降级路径按媒体类型映射到这里）。
CATEGORIES: tuple[str, ...] = (
    "cosplay",
    "二次元插图",
    "表情包",
    "截图",
    "照片",
    "风景",
    "人物",
    "动图",
    "视频",
    "聊天记录",
)
FALLBACK_CATEGORY_BY_TYPE: dict[str, str] = {
    "image": "照片",
    "gif": "动图",
    "video": "视频",
    "chat": "聊天记录",
}
UNKNOWN_IP = "未识别"

# 目录名清洗：路径分隔符与 Windows 非法字符一律替换；控制字符同杀。
_ILLEGAL_DIRNAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_DIRNAME_LEN = 40
# 保留设备名判定（攻击审计 A-1 收编）：本文件不再自持保留名集合——「点号前
# 首段」判定的唯一真身在 domains/files/sender/restricted_runner.py，旧的全名
# 比对（_WIN_RESERVED_NAMES）放行 nul.txt/con.md 形态，属并存的第二弱真身，
# 已删除；sanitize_dirname 改为调用中央判据（只调用、不修改中央件）。


class ArchiveReservedNameError(ValueError):
    """目录段名撞 Win32 保留设备名：拒绝，理由出自中央人话表 DENY_PLAIN_TEXT。

    旧行为是给保留名加 ``_`` 前缀（静默近似值）或放任 mkdir 抛误导性 OSError；
    两者都改为走调用方的既有失败面（恒收紧，同 A-3 口径）。继承 ValueError
    以便未点名本型的调用点按既有 ``except (ValueError, OSError)`` 兜底。
    """

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),  # RIFF....WEBP，配合偏移二次确认
    (b"BM", "bmp"),
    (b"ftyp", "mp4"),  # ISO BMFF，偏移 4
    (b"\x1a\x45\xdf\xa3", "mkv"),
)


def sanitize_dirname(value: str, *, fallback: str = "未命名") -> str:
    """目录名消毒：非法字符/路径穿越片段全部替换，空值回落，保留设备名拒绝。

    保留名判定经局部导入走中央真身（``restricted_runner._is_reserved_device_name``，
    点号前首段 casefold 比对——公开别名待中央件席登记）：``nul`` 与 ``nul.txt``/
    ``con.md`` 同一格拒绝，绝不在此复刻点号切分；命中即抛
    :class:`ArchiveReservedNameError`（人话理由出自中央单表 DENY_PLAIN_TEXT），
    不再洗名加前缀。
    """
    text = _ILLEGAL_DIRNAME_RE.sub("_", str(value or "").strip())
    text = text.replace("..", "_").strip(" ._")
    if not text:
        return fallback
    from plugins.bot_unified_runtime.domains.files.sender import restricted_runner

    if restricted_runner._is_reserved_device_name(text):
        raise ArchiveReservedNameError(
            restricted_runner.plain_reason(restricted_runner.DenyCode.RESERVED_NAME)
        )
    return text[:_MAX_DIRNAME_LEN]


def display_label(value: object) -> str:
    """归档**显示名**消毒（ANTIATTACK P2-d）：IP / 角色名 / 原始文件名的肉眼形态腿。

    与 :func:`sanitize_dirname` 的分工写死，两枚不可互相替代：
    - `sanitize_dirname` 管「盘上这一段能不能建」——路径穿越、非法字符、
      Win32 保留设备名；它的字符表只覆盖控制区，**RLO / ZWSP / 同形异码一律
      原样放行**，所以段名干净不等于显示干净；
    - 本口管「人眼看到的形态与真实码点是否一致」——把带反向覆写的 IP 名洗成
      可见部分、把全角/西里尔近似形冒充的英文名整格屏蔽。

    判据零副本：真身住 `core/safety_exec/attack_surface`，处置口住
    `chat_reply/security/injection::render_safe_display_name`。局部导入避开环
    （本件是 media 域，不新增对 chat_reply 的模块级依赖）。
    空进空出：调用方据此决定「这一格没有名字」，不虚构占位；合法名逐字节不变
    （只改显示形态，不改可信级）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        render_safe_display_name,
    )

    return render_safe_display_name(str(value or ""))


def sniff_extension(data: bytes) -> str | None:
    """magic bytes → 扩展名；未知返回 None（伪装文件拒收，eat 先例）。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) > 4 and data[4:8] == b"ftyp":
        return "mp4"
    for magic, ext in _MAGIC_SIGNATURES:
        if magic == b"RIFF" or magic == b"ftyp":
            continue
        if data.startswith(magic):
            return ext
    return None


@dataclass(frozen=True)
class ArchiveRecord:
    """一条归档索引记录（SQLite 行 + JSON 旁车的共同形态）。"""

    sha256: str
    rel_path: str
    category: str
    ip_source: str
    character_name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    nsfw_score: float = 0.0
    media_type: str = "image"
    original_name: str = ""
    platform: str = ""
    session_id: str = ""
    sender_id: str = ""
    created_at: str = ""

    def to_json(self) -> str:
        """旁车 JSON：人读可迁移的档案面。

        P2-d：三个**名字字段**（IP / 角色 / 原始文件名）过 `display_label`——
        旁车与回执是给人眼看的，显示伪装在这里骗的就是「谁在看这份档案」。
        其余字段（`rel_path`/`category` 已走 `sanitize_dirname`，
        `sha256`/时间戳是代码生成的定形串）不重复过，禁双过变三处。
        """
        return json.dumps(
            {
                "sha256": self.sha256,
                "path": self.rel_path,
                "category": self.category,
                "ip_source": display_label(self.ip_source),
                "character": display_label(self.character_name),
                "description": self.description,
                "tags": self.tags,
                "nsfw_score": self.nsfw_score,
                "media_type": self.media_type,
                "original_name": display_label(self.original_name),
                "platform": self.platform,
                "session_id": self.session_id,
                "sender_id": self.sender_id,
                "created_at": self.created_at,
            },
            ensure_ascii=False,
            indent=2,
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_archive (
    sha256 TEXT PRIMARY KEY,
    rel_path TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    ip_source TEXT NOT NULL DEFAULT '',
    character_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    nsfw_score REAL NOT NULL DEFAULT 0.0,
    media_type TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    sender_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
)
"""


class MediaArchiveStore:
    """归档索引：文件落盘 + sha256 去重 + 当日额度计数。线程内串行使用。"""

    def __init__(self, db_path: str | Path, root_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def exists(self, sha256: str) -> tuple[bool, str]:
        """是否已归档；已归档返回 (True, 相对路径)。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rel_path FROM media_archive WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return (True, str(row[0])) if row else (False, "")

    def count_today(self, *, now: datetime | None = None) -> int:
        day_prefix = (now or datetime.now().astimezone()).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM media_archive WHERE created_at LIKE ?",
                (f"{day_prefix}%",),
            ).fetchone()
        return int(row[0]) if row else 0

    def save(
        self,
        data: bytes,
        *,
        media_type: str,
        category: str,
        ip_source: str,
        subpath: str = "",
        record_kwargs: dict | None = None,
        clock: datetime | None = None,
    ) -> tuple[ArchiveRecord, Path, bool]:
        """落盘 + 入索引；重复 sha256 幂等返回已有记录（duplicated=True）。

        目录 = root/类别/IP[/管理员子路径]；文件名 = yyyymmdd_HHMMSS_<sha8>.<ext>；
        同名 .json 旁车携带全部元数据。写盘与入库全程持锁（并发归档防交错）。
        """
        # 归档去重哈希唯一真身=中央媒体摘要件（S5 收编，蓝图 §3.1 单一入口）。
        sha256 = media_digest(data)
        with self._lock:
            hit, existing_rel = self.exists(sha256)
            if hit:
                return (
                    self._load_record(sha256),
                    self.root / existing_rel,
                    True,
                )
            ext = sniff_extension(data)
            if ext is None:
                raise ValueError("unsupported_media_type")
            now = clock or datetime.now().astimezone()
            category_dir = sanitize_dirname(category, fallback="照片")
            ip_dir = sanitize_dirname(ip_source, fallback=UNKNOWN_IP)
            # 子路径消毒收敛在 store 边界（评审 M-4）：调用方给什么都不逃出根。
            clean_subpath = sanitize_dirname(subpath, fallback="") if subpath else ""
            target_dir = self.root / category_dir / ip_dir
            if clean_subpath:
                target_dir = target_dir / clean_subpath
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256[:8]}.{ext}"
            target = target_dir / filename
            target.write_bytes(data)
            rel_path = target.relative_to(self.root).as_posix()
            kwargs = dict(record_kwargs or {})
            record = ArchiveRecord(
                sha256=sha256,
                rel_path=rel_path,
                category=category_dir,
                ip_source=ip_dir,
                media_type=media_type,
                created_at=now.isoformat(timespec="seconds"),
                **kwargs,
            )
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO media_archive (sha256, rel_path, category, ip_source,"
                        " character_name, description, tags, nsfw_score, media_type,"
                        " original_name, platform, session_id, sender_id, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            record.sha256,
                            record.rel_path,
                            record.category,
                            record.ip_source,
                            record.character_name,
                            record.description,
                            json.dumps(record.tags, ensure_ascii=False),
                            record.nsfw_score,
                            record.media_type,
                            record.original_name,
                            record.platform,
                            record.session_id,
                            record.sender_id,
                            record.created_at,
                        ),
                    )
            except sqlite3.IntegrityError:
                # 并发竞态（评审 I-4）：同 sha256 被并发请求抢先入库——清掉本实例
                # 刚写的文件与旁车，按幂等重复返回既有记录，不产生孤儿文件。
                target.unlink(missing_ok=True)
                target.with_suffix(".json").unlink(missing_ok=True)
                _hit, existing = self.exists(sha256)
                return (
                    self._load_record(sha256),
                    self.root / (existing or rel_path),
                    True,
                )
            sidecar = target.with_suffix(".json")
            sidecar.write_text(record.to_json(), encoding="utf-8")
            return record, target, False

    def save_text(
        self,
        text: str,
        *,
        category: str = "聊天记录",
        ip_source: str = UNKNOWN_IP,
        record_kwargs: dict | None = None,
        clock: datetime | None = None,
    ) -> tuple[ArchiveRecord, Path, bool]:
        """聊天记录归档：Markdown 文本直落（无 magic bytes，走 sha256 去重）。"""
        now = clock or datetime.now().astimezone()
        payload = text.encode("utf-8")
        sha256 = media_digest(payload)
        with self._lock:
            hit, existing_rel = self.exists(sha256)
            if hit:
                return self._load_record(sha256), self.root / existing_rel, True
            category_dir = sanitize_dirname(category, fallback="聊天记录")
            ip_dir = sanitize_dirname(ip_source, fallback=UNKNOWN_IP)
            target_dir = self.root / category_dir / ip_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256[:8]}.md"
            target = target_dir / filename
            target.write_text(text, encoding="utf-8")
            rel_path = target.relative_to(self.root).as_posix()
            kwargs = dict(record_kwargs or {})
            record = ArchiveRecord(
                sha256=sha256,
                rel_path=rel_path,
                category=category_dir,
                ip_source=ip_dir,
                media_type="chat",
                created_at=now.isoformat(timespec="seconds"),
                **kwargs,
            )
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO media_archive (sha256, rel_path, category, ip_source,"
                    " media_type, description, platform, session_id, sender_id, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.sha256,
                        record.rel_path,
                        record.category,
                        record.ip_source,
                        record.media_type,
                        record.description,
                        record.platform,
                        record.session_id,
                        record.sender_id,
                        record.created_at,
                    ),
                )
            return record, target, False

    def _load_record(self, sha256: str) -> ArchiveRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sha256, rel_path, category, ip_source, character_name,"
                " description, tags, nsfw_score, media_type, original_name, platform,"
                " session_id, sender_id, created_at FROM media_archive WHERE sha256 = ?",
                (sha256,),
            ).fetchone()
        if not row:
            return ArchiveRecord(sha256=sha256, rel_path="", category="", ip_source="")
        return ArchiveRecord(
            sha256=row[0],
            rel_path=row[1],
            category=row[2],
            ip_source=row[3],
            character_name=row[4],
            description=row[5],
            tags=json.loads(row[6] or "[]"),
            nsfw_score=float(row[7] or 0.0),
            media_type=row[8],
            original_name=row[9],
            platform=row[10],
            session_id=row[11],
            sender_id=row[12],
            created_at=row[13],
        )
