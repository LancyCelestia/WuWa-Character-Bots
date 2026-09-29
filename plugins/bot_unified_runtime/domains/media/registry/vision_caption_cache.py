"""VLM 图片描述缓存：同一张图第二次进来不再二次计费（席位 MM-VIS-1，2026-09-29）。

治的账（审计报告 缺陷 1）：``vision_describe`` 只有 ``_REMOTE_DATA_URL_CACHE``
那枚**字节**缓存（按 URL 键、进程内、上限 32）。它省的是下载，省不了推理——
同一张图被追问、被两个人分别发、或"直传/转译"两条分支各要一次时，
每一趟都是一次真实的 VLM 账单。本件把**描述文本**（而不是字节）按**内容身份**
落 SQLite，命中即零调用。

判据与口径（三条硬约束，都是仓库既有规矩）：

- **内容身份只走中央件**：键一律经 ``domains/media/digest.py::media_digest`` /
  ``media_digest_file`` 取 sha256，本件**不 import hashlib**。理由不是洁癖——
  ``tests/test_media_identity_single_source_ratchet.py`` 把"媒体字节→哈希"的第二份
  实现钉成棘轮红，手抄一枚当场红。
- **键是"这一组图"不是"这一张图"**：一次 VLM 请求可以带多张图（
  ``BOT_VISION_MAX_IMAGES``），描述是**整批**的产物。所以键＝按顺序把每张图的
  内容摘要拼起来再摘要一次；单图请求退化成"那张图的 sha256"（与审计简报口径一致，
  也仍可被人肉按 sha256 反查）。**少一张图就是另一个键**，绝不拿半批的描述冒充整批。
- **随图问题不进键**：VLM 的系统提示（``_VISION_SYSTEM_PROMPT``）把输出钉成
  角色/文字/画面 三行的固定契约，问题只影响措辞不影响事实。据此选择"按图复用"
  而不是"按图+问题复用"——后者几乎不命中，等于没缓存。代价诚实登记：
  换一种问法可能拿到一份不那么贴问法的描述；``model`` 列留住产出它的模型名，
  换模型后旧行由 TTL 自然淘汰（不假装能做模型间隔离）。

失败语义（与媒体档案库同一口径）：**缓存坏了绝不能拖垮识图**。任何 OSError /
sqlite3.Error / 解析异常都吞成"未命中/不写入"，只留 warning；读路径未命中返回
``None``，写路径返回 ``None``。缺库、只读目录、并发写冲突统统按"没有缓存"处理。
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from plugins.bot_unified_runtime.domains.media.digest import (
    media_digest,
    media_digest_file,
)

logger = logging.getLogger(__name__)

__all__ = [
    "VisionCaptionCache",
    "build_vision_caption_cache",
    "caption_key_for_image_refs",
    "image_ref_digest",
    "reset_vision_caption_cache_for_tests",
]

_DEFAULT_DB_PATH = "data/vision_caption_cache.sqlite3"
_DEFAULT_TTL_SECONDS = 86400.0
#: 每写这么多条顺带清一次过期行（避免只读路径永远碰不到清理）。
_DEFAULT_EVICT_EVERY_WRITES = 32
#: 描述文本落库硬顶：VLM 侧已有 ``BOT_VISION_MAX_CHARS``，这里再兜一层，
#: 防止某个模型抽风吐一篇长文把缓存库撑大。
_MAX_CAPTION_CHARS = 4000

_DATA_URL_PREFIX = "data:"
#: header 段（``mime/type;base64``，逗号已被 partition 切走）里的 base64 标记。
_BASE64_MARKER = ";base64"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_caption (
    sha256 TEXT PRIMARY KEY,
    caption TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vision_caption_created
    ON vision_caption (created_at);
"""


# ---------------------------------------------------------------------------
# 键推导（内容身份的唯一构造点）
# ---------------------------------------------------------------------------


def _local_path_from_value(value: str) -> Path | None:
    """``file://`` / 绝对路径 / 相对路径 → 存在的本地文件；否则 None。

    与 ``vision_describe._local_path_from_value`` 同一判据（不复制它的表），
    只问一件事"这个指针对不对得上一个真文件"——对不上就没有内容身份可用。
    """
    raw = str(value or "").strip()
    if not raw or raw.startswith(_DATA_URL_PREFIX) or raw.startswith("http"):
        return None
    if raw.startswith("file:"):
        raw = unquote(urlparse(raw).path)
        if raw.startswith("/") and len(raw) > 3 and raw[2] == ":":
            raw = raw[1:]
    try:
        path = Path(raw)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def image_ref_digest(ref: str) -> str:
    """单张图片指针 → 内容 sha256；取不到字节就返回空串（绝不拿 URL 冒充内容身份）。

    三种形态各有出处：
    - ``data:image/...;base64,xxx`` → 解码字节后过 ``media_digest``；
    - 本地路径 / ``file://`` → 过 ``media_digest_file``（流式，O(1) 内存）；
    - ``http(s)`` URL → **空串**。依据：URL 会过期、签名串会变、同一张图两个
      地址；拿 URL 摘要当内容身份正是旧 ``_REMOTE_DATA_URL_CACHE`` 只省下载不省
      推理的根因。识图主链在调用 provider 前已把 http 转成 data URL
      （``prepare_vision_image_urls``），所以真图极少走到这一支。
    """
    raw = str(ref or "").strip()
    if not raw:
        return ""
    if raw.startswith(_DATA_URL_PREFIX):
        _, _, tail = raw.partition(":")
        header, _, body = tail.partition(",")
        if not body or _BASE64_MARKER not in header:
            return ""
        try:
            payload = base64.b64decode(body, validate=False)
        except (ValueError, TypeError):
            return ""
        if not payload:
            return ""
        return media_digest(payload)
    path = _local_path_from_value(raw)
    if path is None:
        return ""
    return media_digest_file(path) or ""


def caption_key_for_image_refs(refs: Sequence[str]) -> str:
    """一组图片指针 → 这批图的内容键；任何一张取不到身份 ⇒ 整批不缓存（空串）。

    刻意"一票否决"：部分可哈希时若照样建键，键里就掺进了"这张没算进去"的不确定，
    下一次带同一张可哈希图配另一张不可哈希图时会撞出错误命中。宁可少命中。
    """
    digests: list[str] = []
    for ref in refs or ():
        digest = image_ref_digest(str(ref))
        if not digest:
            return ""
        digests.append(digest)
    if not digests:
        return ""
    return media_digest("|".join(digests).encode("utf-8"))


def caption_key_for_messages(messages: Iterable[dict[str, Any]] | None) -> str:
    """从聊天消息体里收集 ``image_url`` 部件并成键（顺序即请求顺序）。

    文本部件一律忽略——理由见模块头「随图问题不进键」。
    """
    refs: list[str] = []
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
                if url:
                    refs.append(url)
    return caption_key_for_image_refs(refs)


# ---------------------------------------------------------------------------
# SQLite 存储
# ---------------------------------------------------------------------------


class VisionCaptionCache:
    """图片描述缓存：进程内单实例，持久连接 + 线程锁（识图跑在线程池里）。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        evict_every_writes: int = _DEFAULT_EVICT_EVERY_WRITES,
    ) -> None:
        self.db_path = Path(str(db_path or "").strip() or _DEFAULT_DB_PATH)
        self.ttl_seconds = max(0.0, float(ttl_seconds or 0.0))
        self.evict_every_writes = max(1, int(evict_every_writes or 1))
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._writes_since_evict = 0

    # ---- 连接 ----

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    logger.debug("vision caption cache close ignored", exc_info=True)
                self._conn = None

    # ---- 对外三件套 ----

    def lookup(self, image_sha256: str) -> str | None:
        """命中且未过期 → 描述文本；其余一律 None（含一切异常）。"""
        key = str(image_sha256 or "").strip()
        if not key or self.ttl_seconds <= 0.0:
            return None
        now = time.time()
        with self._lock:
            try:
                conn = self._connection()
                row = conn.execute(
                    "SELECT caption, created_at FROM vision_caption "
                    "WHERE sha256 = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                created_at = float(row["created_at"] or 0.0)
                if now - created_at > self.ttl_seconds:
                    # 过期行就地删掉，别等清理轮次。
                    conn.execute(
                        "DELETE FROM vision_caption WHERE sha256 = ?", (key,)
                    )
                    conn.commit()
                    logger.info("vision_caption_expired=1")
                    return None
                caption = str(row["caption"] or "").strip()
                if not caption:
                    return None
                conn.execute(
                    "UPDATE vision_caption SET hits = hits + 1 WHERE sha256 = ?",
                    (key,),
                )
                conn.commit()
                return caption
            except (sqlite3.Error, OSError, ValueError, TypeError):
                logger.warning("vision caption lookup failed", exc_info=True)
                self._conn = None
                return None

    def put(self, image_sha256: str, caption: str, model: str = "") -> None:
        """写一条描述；空键/空文本报废写入，任何失败都只是"没缓存成"。"""
        key = str(image_sha256 or "").strip()
        text = str(caption or "").strip()
        if not key or not text or self.ttl_seconds <= 0.0:
            return
        if len(text) > _MAX_CAPTION_CHARS:
            text = text[: _MAX_CAPTION_CHARS - 1] + "…"
        now = time.time()
        with self._lock:
            try:
                conn = self._connection()
                conn.execute(
                    "INSERT INTO vision_caption (sha256, caption, model, created_at, hits) "
                    "VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT(sha256) DO UPDATE SET "
                    "caption = excluded.caption, model = excluded.model, "
                    "created_at = excluded.created_at",
                    (key, text, str(model or "")[:120], now),
                )
                self._writes_since_evict += 1
                if self._writes_since_evict >= self.evict_every_writes:
                    self._writes_since_evict = 0
                    self.evict_expired()
                conn.commit()
            except (sqlite3.Error, OSError, ValueError, TypeError):
                logger.warning("vision caption put failed", exc_info=True)
                self._conn = None

    def evict_expired(self) -> int:
        """删掉超过 TTL 的行，返回删除数；失败返回 0（清理从不阻塞主链）。"""
        if self.ttl_seconds <= 0.0:
            return 0
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            try:
                conn = self._connection()
                cursor = conn.execute(
                    "DELETE FROM vision_caption WHERE created_at < ?", (cutoff,)
                )
                conn.commit()
                removed = int(cursor.rowcount or 0)
                if removed:
                    logger.info("vision_caption_evicted=%s", removed)
                return removed
            except (sqlite3.Error, OSError, ValueError, TypeError):
                logger.warning("vision caption evict failed", exc_info=True)
                self._conn = None
                return 0


# ---------------------------------------------------------------------------
# 装配口（按 config 取实例；同一路径复用同一个连接对象）
# ---------------------------------------------------------------------------

_INSTANCES: dict[str, VisionCaptionCache] = {}
_INSTANCES_LOCK = threading.Lock()


def reset_vision_caption_cache_for_tests() -> None:
    """丢掉进程内实例表（测试隔离用；生产不调）。"""
    global _INSTANCES
    with _INSTANCES_LOCK:
        for instance in _INSTANCES.values():
            instance.close()
        _INSTANCES = {}


def build_vision_caption_cache(config: Any) -> VisionCaptionCache | None:
    """按 Config 取缓存实例；未配置/关闭返回 None（调用方按"没有缓存"走）。

    只认两枚键：``bot_vision_caption_cache_db``（空串＝整件关闭）与
    ``bot_vision_caption_cache_ttl_seconds``（≤0＝关闭）。同一路径**复用同一实例**
    （连接与锁不翻倍）；不同路径各开一份，落点已由 ``config.PATH_REMAPPED_FIELDS``
    统一重映射到运行数据根（铁律 6：源码树不落生成物）。
    """
    db_path = str(getattr(config, "bot_vision_caption_cache_db", "") or "").strip()
    if not db_path:
        return None
    ttl_seconds = float(
        getattr(config, "bot_vision_caption_cache_ttl_seconds", _DEFAULT_TTL_SECONDS)
        or 0.0
    )
    if ttl_seconds <= 0.0:
        return None
    with _INSTANCES_LOCK:
        existing = _INSTANCES.get(db_path)
        if existing is not None:
            return existing
        try:
            instance = VisionCaptionCache(db_path, ttl_seconds=ttl_seconds)
        except (OSError, sqlite3.Error, ValueError):
            logger.warning("vision caption cache unavailable", exc_info=True)
            return None
        _INSTANCES[db_path] = instance
        instance.evict_expired()
        return instance
