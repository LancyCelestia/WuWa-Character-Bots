"""W5/W6（2026-10-14）：`VisualSpec` 的**布局存储与服务**（含修正批 §4 语义）。

用户需求（整批操作包 §B）：布局按 **platform / instance / group / card** 四元组
**整份** CAS/version 保存，**不按 persona**（persona 只管主题）；命中即用，
缺则**单跳**回退到平台默认面；预览与生产**同一 renderer**出 HTML。

## 修正批（§4，2026-10-14 二次）——四条硬语义
1. **跨对象鲜活**：进程内缓存不再是唯一判据。存储另记**全局单调 revision**，
   每次读都做一次轻量 revision 查询；revision 变了（**独立 panel 进程写过**）
   即重新装载 ⇒ 跨进程发布**立即可见**（另有 bounded TTL 作兜底上界）。
2. **缓存有界**：`OrderedDict` 上限 128（每 scope 一条单跳结果），LRU 淘汰，
   热请求不会把 key 空间撑成无界。
3. **reset 不 delete、版本单调（防 ABA）**：reset 写 **tombstone**（`is_reset=1`）
   并把版本 +1，**绝不回到 0**；旧客户端拿 `expected_version=0` 再来写必然 409。
   tombstone 语义＝「本 scope 显式无布局」，**阻断单跳回退**（与仓内
   `config_store` 的 tombstone 同口径）。
4. **CAS 只认 exact 行**：`save/reset` 的 `expected_version` 只与**本 scope 精确行**
   比；从平台默认面继承来的版本**不能**拿去写本 scope（`read` 因此分别给出
   `exact_version` / `inherited_version` / `next_version`）。

## 硬边界（不变）
- **存储路径必须显式**：本模块不提供生产缺省路径（生产落地另批）；只准临时/
  显式路径建新表（源码级 DDL，不对生产库自动执行）。
- **不 eval**：spec 只经 `visual_spec.normalize_visual_spec` 归一（白名单/转义）；
  绑定样本只覆盖预览输出，**不冻结**进存储。
- **预览不返回任意 HTML**：`preview()` 的 HTML 只来自 `visual_spec_render`
  的生产函数；**不读任何无 owner 路径**（零文件/网络 IO）。
- **scope 严格**：`LayoutScope` 是 `extra="forbid"` 的 pydantic 模型，四轴都是
  令牌形，空串＝「平台默认面」。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "FRAGMENT_KEYS",
    "GLOBAL_PLATFORM",
    "TRANSPORT_PLATFORM_AXES",
    "LayoutScope",
    "VisualLayoutError",
    "VisualLayoutRecord",
    "VisualLayoutResetPayload",
    "VisualLayoutSavePayload",
    "VisualLayoutService",
    "VisualLayoutStore",
    "VisualPreviewPayload",
    "VisualThemePayload",
    "VisualThemeRollbackPayload",
    "normalize_fragments",
]

#: 四轴作用域令牌（空串＝该轴不限定；平台默认面＝后三轴空）。
_SCOPE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_MAX_SPEC_BYTES = 256 * 1024

#: 全局面平台轴（W12 R3，2026-10-19 用户裁定 Q10(b)）。
#: 用户实测：生产读 ``('onebot','onebot.v11','g1','bot.weather')``，而编辑器缺省写
#: ``('qq','','','')`` ⇒ 两跳全落空、``source='none'``、布局永不生效；且 ``platform``
#: 为 ``min_length=1`` 必填 ⇒ **压根没有全局面**可存。``'*'`` 是回退链的最后一跳。
GLOBAL_PLATFORM = "*"

#: 摄取层真实平台轴（顺序仅用于稳定展示；值域由
#: ``tests/test_visual_layout_scope.py::test_platform_registry_matches_ingest_literals``
#: 拿 ``__init__.py`` 的 AST 现算值逐元素比对——手抄漂了这门必红）。
#: 出处：``IncomingMessage(platform=…)`` 与 ``platform = "…"`` 两类字面量。
TRANSPORT_PLATFORM_AXES: tuple[str, ...] = (
    "qq",
    "onebot",
    "nonebot",
    "telegram",
    "email",
)

#: 受限模板片段（W12 R4，用户裁定 A+B+C）：**只准**改标题/副标题/页脚文案，
#: 不准注入任意 HTML/CSS（``_FRAGMENT_FORBIDDEN`` 一票否决）。
FRAGMENT_KEYS: tuple[str, ...] = ("title", "subtitle", "footer")
FRAGMENT_LIMITS: dict[str, int] = {"title": 120, "subtitle": 200, "footer": 120}
_FRAGMENT_FORBIDDEN = re.compile(
    r"[<>{}]|url\s*\(|expression\s*\(|@import|javascript:|&#|\\u003c", re.IGNORECASE
)


def normalize_fragments(raw: Any, dropped: list[str] | None = None) -> dict[str, str]:
    """受限片段归一：只收三键纯文本，超长/含标记/未知键一律丢弃并留痕。

    纯函数、不抛：非法输入返回 ``{}``。**不接受**任何 HTML/CSS 形态——片段会直接
    拼进卡面文本位，注入面就在这里封死（渲染侧另有 ``_s()`` 转义，双保险）。
    """
    out: dict[str, str] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        if dropped is not None:
            dropped.append("fragments:非对象")
        return out
    for key in raw:
        if key not in FRAGMENT_KEYS and dropped is not None:
            dropped.append(f"fragments.{key}:未知字段")
    for key in FRAGMENT_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if len(text) > FRAGMENT_LIMITS[key]:
            if dropped is not None:
                dropped.append(f"fragments.{key}:超出 {FRAGMENT_LIMITS[key]} 字")
            continue
        if _FRAGMENT_FORBIDDEN.search(text):
            if dropped is not None:
                dropped.append(f"fragments.{key}:含标记/样式形态")
            continue
        out[key] = text
    return out



class VisualLayoutError(Exception):
    """布局业务错误：稳定错误码 + 状态码（禁回传底层异常/密钥）。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)


def _validate_axis(value: str) -> str:
    token = str(value or "").strip()
    if token == GLOBAL_PLATFORM:
        return token
    if token and not _SCOPE_TOKEN_RE.match(token):
        raise ValueError("scope 轴只接受令牌形（字母数字起头，≤64）")
    return token


class LayoutScope(BaseModel):
    """布局作用域四元组（`extra="forbid"`：多一轴即 422，不静默吞字段）。

    ``platform='*'`` 是**全局面**（回退链最后一跳）；``platform=''`` 仍然非法
    （空串会被读成「随便哪个平台」，语义不成立）。
    """

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(strict=True, min_length=1, max_length=64)
    instance: str = Field(default="", strict=True, max_length=64)
    group: str = Field(default="", strict=True, max_length=64)
    card: str = Field(default="", strict=True, max_length=64)

    @field_validator("platform", "instance", "group", "card")
    @classmethod
    def _check_axis(cls, value: str) -> str:
        return _validate_axis(value)

    def as_key(self) -> tuple[str, str, str, str]:
        return (self.platform, self.instance, self.group, self.card)

    def platform_default(self) -> LayoutScope:
        """平台默认面（回退链第二跳；后三轴空）。"""
        return LayoutScope(platform=self.platform)

    def global_default(self) -> LayoutScope:
        """全局面（回退链最后一跳；``platform='*'`` 且后三轴空）。"""
        return LayoutScope(platform=GLOBAL_PLATFORM)

    def is_platform_default(self) -> bool:
        return not (self.instance or self.group or self.card)

    def is_global_default(self) -> bool:
        return self.platform == GLOBAL_PLATFORM and self.is_platform_default()


@dataclass(frozen=True)
class VisualLayoutRecord:
    """一条 scope 的精确行（tombstone 时 `spec is None` 且 `is_reset=True`）。

    `fragments` 是 W12 R4 的**受限模板片段**（标题/副标题/页脚纯文本），与 spec
    同一条版本轴（同一次 CAS 写、同一次 reset 清空），不另造第二本账。
    """

    scope: LayoutScope
    version: int
    spec: dict[str, Any] | None
    is_reset: bool = False
    updated_at: str = ""
    fragments: dict[str, str] = field(default_factory=dict)


class VisualLayoutStore:
    """显式路径 SQLite 布局存储（整份 CAS ＋ 全局 revision ＋ tombstone 版本）。"""

    def __init__(self, path: str | Path) -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("布局存储需要显式文件路径（生产落地另批）")
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS visual_layouts (
                    platform TEXT NOT NULL,
                    instance TEXT NOT NULL,
                    "group" TEXT NOT NULL,
                    card TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    spec_json TEXT,
                    is_reset INTEGER NOT NULL DEFAULT 0 CHECK(is_reset IN (0, 1)),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(platform, instance, "group", card))"""
            )
            # 旧库（本波之前的临时库）补列：ALTER-if-missing，幂等。
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(visual_layouts)")
            }
            if "is_reset" not in columns:
                conn.execute(
                    "ALTER TABLE visual_layouts ADD COLUMN is_reset INTEGER NOT NULL DEFAULT 0"
                )
            # W12 R4：受限模板片段与 spec 同表同版本轴（不另造第二本账）。
            if "fragments_json" not in columns:
                conn.execute(
                    "ALTER TABLE visual_layouts ADD COLUMN fragments_json TEXT"
                )
            # 全局单调 revision：跨对象（panel 进程写、bot 进程读）鲜活的唯一判据。
            conn.execute(
                """CREATE TABLE IF NOT EXISTS visual_layout_revision (
                    id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL)"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO visual_layout_revision(id, revision) VALUES (1, 0)"
            )
            # W12 R4：全局视觉覆盖（主色/圆角/字体）——单行当前态 + 只增不减的审计册。
            conn.execute(
                """CREATE TABLE IF NOT EXISTS visual_theme (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    version INTEGER NOT NULL,
                    overrides_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO visual_theme(id, version, overrides_json) "
                "VALUES (1, 0, '{}')"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS visual_theme_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    overrides_json TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"""
            )

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _fetch(conn: sqlite3.Connection, scope: LayoutScope) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT version, spec_json, is_reset, updated_at, fragments_json "
            "FROM visual_layouts "
            'WHERE platform=? AND instance=? AND "group"=? AND card=?',
            scope.as_key(),
        ).fetchone()

    @staticmethod
    def _row(scope: LayoutScope, row: sqlite3.Row | None) -> VisualLayoutRecord | None:
        if row is None:
            return None
        is_reset = bool(int(row["is_reset"]))
        keys = row.keys()
        fragments_raw = row["fragments_json"] if "fragments_json" in keys else None
        return VisualLayoutRecord(
            scope=scope,
            version=int(row["version"]),
            spec=None if is_reset else json.loads(row["spec_json"]),
            is_reset=is_reset,
            updated_at=str(row["updated_at"]),
            fragments={} if is_reset or not fragments_raw else json.loads(fragments_raw),
        )

    def revision(self) -> int:
        """全局单调 revision（一次单行 SELECT；读路径的跨对象鲜活判据）。"""
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT revision FROM visual_layout_revision WHERE id = 1"
            ).fetchone()
        return int(row["revision"]) if row is not None else 0

    def _bump_revision(self, conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE visual_layout_revision SET revision = revision + 1 WHERE id = 1")

    def get(self, scope: LayoutScope) -> VisualLayoutRecord | None:
        """**精确**行（含 tombstone）；该 scope 从未写过返回 None。"""
        with self._transaction() as conn:
            row = self._fetch(conn, scope)
        return self._row(scope, row)

    def _write(
        self,
        scope: LayoutScope,
        *,
        expected_version: int,
        spec_json: str | None,
        is_reset: bool,
        fragments_json: str | None = None,
    ) -> VisualLayoutRecord:
        if type(expected_version) is not int or expected_version < 0:
            raise VisualLayoutError(
                "invalid_version", "必须提供非负整数 expected_version。", 422
            )
        with self._lock, self._transaction(write=True) as conn:
            row = self._fetch(conn, scope)
            current = int(row["version"]) if row is not None else 0
            if current != expected_version:
                raise VisualLayoutError(
                    "version_conflict", "布局已变化，请刷新后重试。", 409
                )
            new_version = current + 1
            conn.execute(
                'INSERT INTO visual_layouts(platform, instance, "group", card, version, '
                "spec_json, is_reset, fragments_json, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?, strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                'ON CONFLICT(platform, instance, "group", card) DO UPDATE SET '
                "version=excluded.version, spec_json=excluded.spec_json, "
                "is_reset=excluded.is_reset, fragments_json=excluded.fragments_json, "
                "updated_at=excluded.updated_at",
                (
                    *scope.as_key(),
                    new_version,
                    spec_json,
                    1 if is_reset else 0,
                    fragments_json,
                ),
            )
            self._bump_revision(conn)
            saved = self._fetch(conn, scope)
        record = self._row(scope, saved)
        assert record is not None
        return record

    def save(
        self,
        scope: LayoutScope,
        spec: dict[str, Any],
        *,
        expected_version: int,
        fragments: dict[str, str] | None = None,
    ) -> VisualLayoutRecord:
        payload = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        if len(payload.encode("utf-8")) > _MAX_SPEC_BYTES:
            raise VisualLayoutError("spec_too_large", "布局内容超出大小上限。", 413)
        fragments_json = (
            json.dumps(dict(fragments), ensure_ascii=False, sort_keys=True)
            if fragments
            else None
        )
        return self._write(
            scope,
            expected_version=expected_version,
            spec_json=payload,
            is_reset=False,
            fragments_json=fragments_json,
        )

    def reset(self, scope: LayoutScope, *, expected_version: int) -> VisualLayoutRecord:
        """写 **tombstone**（版本 +1，绝不 delete/回 0）——防「reset 后旧版本可重用」。"""
        return self._write(
            scope, expected_version=expected_version, spec_json=None, is_reset=True
        )

    # ---- 全局视觉覆盖（W12 R4）：单行当前态 + 只增不减的审计册 -----------------
    def theme_read(self) -> dict[str, Any]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT version, overrides_json, updated_at FROM visual_theme WHERE id = 1"
            ).fetchone()
        if row is None:
            return {"version": 0, "overrides": {}, "updated_at": ""}
        return {
            "version": int(row["version"]),
            "overrides": json.loads(row["overrides_json"]),
            "updated_at": str(row["updated_at"]),
        }

    def theme_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """审计册（新→旧）：每次写/回滚一行，含主体与版本。"""
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT version, action, overrides_json, actor, created_at "
                "FROM visual_theme_history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {
                "version": int(row["version"]),
                "action": str(row["action"]),
                "overrides": json.loads(row["overrides_json"]),
                "actor": str(row["actor"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def theme_write(
        self,
        overrides: dict[str, Any],
        *,
        expected_version: int,
        actor: str,
        action: str = "save",
    ) -> dict[str, Any]:
        """CAS 写全局覆盖：版本只增、每次落一行审计、返回新版本与生效映射。

        **回滚也走这里**（``action='rollback'``）——版本号绝不回退，防 ABA。
        """
        if type(expected_version) is not int or expected_version < 0:
            raise VisualLayoutError(
                "invalid_version", "必须提供非负整数 expected_version。", 422
            )
        payload = json.dumps(dict(overrides), ensure_ascii=False, sort_keys=True)
        with self._lock, self._transaction(write=True) as conn:
            row = conn.execute(
                "SELECT version FROM visual_theme WHERE id = 1"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current != expected_version:
                raise VisualLayoutError(
                    "version_conflict", "视觉全局设置已变化，请刷新后重试。", 409
                )
            new_version = current + 1
            conn.execute(
                "INSERT INTO visual_theme(id, version, overrides_json, updated_at) "
                "VALUES (1, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version, "
                "overrides_json=excluded.overrides_json, updated_at=excluded.updated_at",
                (new_version, payload),
            )
            conn.execute(
                "INSERT INTO visual_theme_history(version, action, overrides_json, actor) "
                "VALUES (?,?,?,?)",
                (new_version, str(action), payload, str(actor or "")),
            )
            self._bump_revision(conn)
        return {
            "version": new_version,
            "next_version": new_version,
            "overrides": dict(overrides),
            "action": str(action),
            "actor": str(actor or ""),
        }

    def theme_previous(self) -> dict[str, Any]:
        """上一版覆盖（回滚目标）与它自己的版本号（无上一版时回落全空）。"""
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT version, overrides_json FROM visual_theme_history "
                "ORDER BY id DESC LIMIT 2"
            ).fetchall()
        if len(rows) < 2:
            return {"version": 0, "overrides": {}}
        return {
            "version": int(rows[0]["version"]),
            "overrides": json.loads(rows[1]["overrides_json"]),
        }


class VisualLayoutService:
    """布局读/写/预览；缓存**有界**且以存储 revision 判鲜活（跨进程可见）。"""

    #: 进程内缓存条数上限（每 scope 一条单跳结果；LRU 淘汰）。
    CACHE_MAX = 128
    #: 缓存条目最长存活秒数（revision 已保证鲜活；TTL 是兜底上界）。
    CACHE_TTL_SECONDS = 5.0

    def __init__(
        self, store: VisualLayoutStore, *, cache_ttl: float | None = None
    ) -> None:
        self._store = store
        # key → (spec, source, version, fallback_scope, exact_version, revision, ts)
        self._cache: OrderedDict[tuple[str, str, str, str], tuple[Any, ...]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._ttl = self.CACHE_TTL_SECONDS if cache_ttl is None else float(cache_ttl)

    # ---- 目录（登记面只读投影）------------------------------------------
    def catalog(self) -> dict[str, Any]:
        from plugins.bot_unified_runtime.domains.render.card_render import theme_tokens
        from plugins.bot_unified_runtime.domains.render.visual_spec import (
            ALLOWED_KINDS,
            BINDING_PATHS,
            STYLE_COLORS,
            STYLE_SIZES,
            STYLE_SPACING,
            STYLE_WEIGHTS,
            VISUAL_SPEC_VERSION,
        )

        return {
            "spec_version": VISUAL_SPEC_VERSION,
            "kinds": sorted(ALLOWED_KINDS),
            "style": {
                "sizes": sorted(STYLE_SIZES),
                "spacing": sorted(STYLE_SPACING),
                "weights": sorted(STYLE_WEIGHTS),
                "colors": sorted(STYLE_COLORS),
            },
            "binding_paths": dict(sorted(BINDING_PATHS.items())),
            # W12 R3(a)：编辑器默认值必须从**后端**拉真实平台清单——手抄 'qq'
            # 与生产 'onebot' 对不上，就是用户实测的那个「保存了永不生效」。
            "platforms": [*TRANSPORT_PLATFORM_AXES, GLOBAL_PLATFORM],
            "global_platform": GLOBAL_PLATFORM,
            # W12 R4：受限片段可改面 + 全局 token 可改面（值域一并给出，前端不手抄）。
            "fragments": list(FRAGMENT_KEYS),
            "fragment_limits": dict(FRAGMENT_LIMITS),
            "theme_keys": list(theme_tokens.THEME_OVERRIDE_KEYS),
            "theme_choices": {
                "shell_radius": sorted(theme_tokens.SHELL_RADIUS_CHOICES),
                "font_family": sorted(theme_tokens.FONT_FAMILY_CHOICES),
            },
        }

    def cache_size(self) -> int:
        with self._cache_lock:
            return len(self._cache)

    # ---- 读（exact → 平台默认 → '*' 全局 → none，命中即停）----------------
    def _load(self, scope: LayoutScope) -> tuple[Any, ...]:
        """从存储现取（不经缓存）：(spec, source, version, fallback, exact_version, fragments)。

        回退链（W12 R3(b)，用户裁定）：``exact → platform → '*' → none``。
        任一层 tombstone 即**阻断**（显式「本层无布局」），不再往更低一层找。
        """
        exact = self._store.get(scope)
        if exact is not None:
            if exact.is_reset:
                return (None, "none", exact.version, None, exact.version, {})
            return (
                exact.spec,
                "exact",
                exact.version,
                scope,
                exact.version,
                exact.fragments,
            )
        for label, hop in (
            ("platform", scope.platform_default()),
            ("global", scope.global_default()),
        ):
            if hop.as_key() == scope.as_key():
                continue  # 本层就是请求的那一层：已在上面的 exact 分支判过
            row = self._store.get(hop)
            if row is None:
                continue
            if row.is_reset:
                # 显式「本层无布局」⇒ 阻断更低一跳（与既有 tombstone 同口径）。
                return (None, "none", row.version, None, 0, {})
            return (row.spec, label, row.version, hop, 0, row.fragments)
        return (None, "none", 0, None, 0, {})

    def _resolve(self, scope: LayoutScope) -> tuple[Any, ...]:
        key = scope.as_key()
        revision = self._store.revision()  # 轻量单行读：跨对象写立即可见
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                cached_rev = entry[5]
                cached_ts = entry[6]
                if cached_rev == revision and (now - cached_ts) <= self._ttl:
                    self._cache.move_to_end(key)
                    return self._unpack(entry)
        resolved = self._load(scope)
        with self._cache_lock:
            existing = self._cache.get(key)
            if existing is not None and existing[5] > revision:
                # 已有**更新**（revision 更大）的条目：旧装载不得回填覆盖它
                # （否则并发下「旧 callback 回填」会把新值挤掉）。
                self._cache.move_to_end(key)
                return self._unpack(existing)
            # 元组排布：`resolved[:5]` 五项 + revision + 时刻 + 片段（见 `_unpack`）。
            self._cache[key] = (*resolved[:5], revision, now, *resolved[5:])
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_MAX:  # 有界：LRU 淘汰
                self._cache.popitem(last=False)
        return resolved

    #: 缓存元组布局：`[0:5]` ＝ `_load()` 前五项（spec/source/version/fallback/
    #: exact_version），`[5]` ＝ revision、`[6]` ＝ 装载时刻、`[7]` ＝ 受限片段。
    #: **`[5]` 必须是 revision**：既有并发门
    #: `test_rendering_contract.py::test_stale_load_never_overwrites_fresher_entry`
    #: 直接按该下标注入「更新条目」，挪位会让那道门静默失效。
    @staticmethod
    def _unpack(entry: tuple[Any, ...]) -> tuple[Any, ...]:
        """缓存元组 → `_load()` 同形六元组（片段缺席时给空映射）。"""
        return (*entry[:5], entry[7] if len(entry) > 7 else {})

    def _invalidate(self, scope: LayoutScope) -> None:
        """本进程写后定向失效（跨进程由 revision 判据兜住）。

        写**平台默认面** ⇒ 该平台所有派生作用域失效；写**全局面** ⇒ 整张表失效
        （全局面是任何作用域都可能命中的最后一跳，漏一个 key 就是「改了看不到」）。
        """
        with self._cache_lock:
            self._cache.pop(scope.as_key(), None)
            if scope.is_global_default():
                self._cache.clear()
                return
            if scope.is_platform_default():
                for key in [k for k in self._cache if k[0] == scope.platform]:
                    self._cache.pop(key, None)
                # 平台默认面本身可能是从全局面继承来的 ⇒ 让全局 key 也失效。
                self._cache.pop(scope.global_default().as_key(), None)
            else:
                self._cache.pop(scope.platform_default().as_key(), None)
                self._cache.pop(scope.global_default().as_key(), None)

    def read(self, scope: LayoutScope) -> dict[str, Any]:
        spec, source, version, fallback, exact_version, fragments = self._resolve(scope)
        return {
            "scope": scope.model_dump(),
            "source": source,
            "version": version,
            "spec": spec,
            # W12 R4：受限模板片段与 spec 同一次读返回（同一版本轴）。
            "fragments": dict(fragments or {}),
            # 🔴 CAS 只认 exact 行：写本 scope 必须用 exact_version；
            # inherited_version 只是「当前生效值来自哪一层」的读数，不可拿来写。
            "exact_version": exact_version,
            "inherited_version": version if source in {"platform", "global"} else None,
            "next_version": exact_version,
            "fallback_scope": fallback.model_dump() if fallback is not None else None,
        }

    # ---- 写（整份 CAS）--------------------------------------------------
    def save(
        self,
        scope: LayoutScope,
        spec: Any,
        *,
        expected_version: int,
        actor: str = "",
        fragments: Any = None,
    ) -> dict[str, Any]:
        from plugins.bot_unified_runtime.domains.render.visual_spec import (
            normalize_visual_spec,
        )

        normalized = normalize_visual_spec(spec)
        dropped = list(normalized.dropped)
        clean_fragments = normalize_fragments(fragments, dropped)
        if fragments and not clean_fragments:
            # 全被拒 ⇒ 不是「静默存了个空」，是这次写不成立（调用方拿着 reaons 修）。
            raise VisualLayoutError(
                "invalid_fragment", "受限片段只接受标题/副标题/页脚的纯文本。", 422
            )
        record = self._store.save(
            scope,
            normalized.to_dict(),
            expected_version=expected_version,
            fragments=clean_fragments,
        )
        self._invalidate(scope)
        return {
            "scope": scope.model_dump(),
            "version": record.version,
            "next_version": record.version,
            "spec": record.spec,
            "fragments": dict(record.fragments),
            "degraded": dropped,
            "actor": str(actor or ""),
        }

    def reset(
        self, scope: LayoutScope, *, expected_version: int, actor: str = ""
    ) -> dict[str, Any]:
        record = self._store.reset(scope, expected_version=expected_version)
        self._invalidate(scope)
        return {
            "scope": scope.model_dump(),
            "version": record.version,
            "next_version": record.version,
            "spec": None,
            "fragments": {},
            "tombstone": True,
            "actor": str(actor or ""),
        }

    # ---- 全局视觉覆盖（W12 R4）------------------------------------------
    def theme_read(self) -> dict[str, Any]:
        state = self._store.theme_read()
        return {
            "version": state["version"],
            "next_version": state["version"],
            "overrides": state["overrides"],
            "updated_at": state["updated_at"],
        }

    def theme_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._store.theme_history(limit)

    def theme_save(
        self, overrides: Any, *, expected_version: int, actor: str = ""
    ) -> dict[str, Any]:
        from plugins.bot_unified_runtime.domains.render.card_render import (
            theme_tokens,
        )

        dropped: list[str] = []
        clean = theme_tokens.normalize_theme_overrides(overrides, dropped)
        if dropped:
            raise VisualLayoutError(
                "invalid_override",
                "全局视觉只接受登记值域（主色 #RRGGBB / 圆角登记档 / sans|mono）。",
                422,
            )
        out = self._store.theme_write(
            clean, expected_version=expected_version, actor=actor, action="save"
        )
        theme_tokens.set_theme_overrides(clean)
        out["degraded"] = []
        return out

    def theme_rollback(self, *, expected_version: int, actor: str = "") -> dict[str, Any]:
        """回滚到上一版（**写一个新版本**，版本号绝不回退）。"""
        from plugins.bot_unified_runtime.domains.render.card_render import (
            theme_tokens,
        )

        previous = self._store.theme_previous()
        clean = theme_tokens.normalize_theme_overrides(previous["overrides"])
        out = self._store.theme_write(
            clean, expected_version=expected_version, actor=actor, action="rollback"
        )
        theme_tokens.set_theme_overrides(clean)
        return out

    # ---- 预览（生产 renderer 同函数出 HTML；不落库）---------------------
    def preview(
        self, spec: Any, sample: Any = None, fragments: Any = None
    ) -> dict[str, Any]:
        from plugins.bot_unified_runtime.domains.render.visual_spec import (
            apply_binding_samples,
            normalize_visual_spec,
        )
        from plugins.bot_unified_runtime.domains.render.visual_spec_render import (
            render_visual_spec_html,
        )

        dropped: list[str] = []
        clean_fragments = normalize_fragments(fragments, dropped)
        payload = apply_binding_samples(spec, sample)
        normalized = normalize_visual_spec(payload)
        html_text = render_visual_spec_html(normalized, fragments=clean_fragments)
        return {
            "html": html_text,
            "spec": normalized.to_dict(),
            "fragments": clean_fragments,
            "degraded": [*normalized.dropped, *dropped],
        }


def hydrate_theme_overrides_from_store(store_or_source: Any) -> dict[str, Any]:
    """把**库里那一版**全局视觉覆盖回灌到本进程的渲染态；返回已应用的映射。

    🔴 为什么必须有这个入口（W12-REVIEW 席实测的 P1-1，2026-10-19）：

    `theme_save` / `theme_rollback` 只改**自己进程**的
    ``theme_tokens.set_theme_overrides(...)``（模块全局）。而控制面默认以
    ``standalone`` 模式跑在**独立进程**，渲染在 bot 进程 ⇒ 面板改出来的覆盖
    只活在面板进程里，bot 进程的 ``active_theme_overrides()`` 永远为空。
    实测：面板改 `#ff0000` 后模拟重启，accent 回到默认 `#318ce7`。

    本函数是「另一个进程把同一份库读回来」的那条腿。装配层在启动期调一次即可。

    ``store_or_source`` 必须**显式**给出：`VisualLayoutStore`，或带 ``path`` 的
    配置后端。本模块按硬边界**不提供生产缺省路径**（见模块 docstring「存储路径
    必须显式」），所以这里也不猜——传 None 直接返回 ``{}`` 并记一条 debug。

    **fail-safe 方向**：任何读取失败（库损坏/表没建/JSON 坏）一律当作"没有覆盖"
    并返回 ``{}``——绝不抛异常把启动拖下水。值域外的键逐个丢弃并留一条可诊断
    痕迹（不因为一部分坏就全丢），与 `theme_save` 的 422 口径**不同**是**有意**的：
    写入要严格拒绝，读回要尽量兼容。
    """
    from plugins.bot_unified_runtime.domains.render.card_render import theme_tokens

    logger = logging.getLogger(__name__)
    if store_or_source is None:
        logger.debug("theme hydration skipped: no explicit store")
        return {}
    try:
        if isinstance(store_or_source, VisualLayoutStore):
            store = store_or_source
        elif isinstance(store_or_source, (str, Path)):
            # 路径也算显式来源：装配层最自然的传法就是「那个 sqlite 文件在哪」。
            store = VisualLayoutStore(store_or_source)
        else:
            path = getattr(store_or_source, "path", None)
            if path is None:
                logger.debug("theme hydration skipped: source has no path")
                return {}
            store = VisualLayoutStore(path)
        state = store.theme_read()
        raw = state.get("overrides") or {}
        if not raw:
            return {}
        dropped: list[str] = []
        clean = theme_tokens.normalize_theme_overrides(raw, dropped)
        if dropped:
            logger.warning(
                "theme hydration dropped %d out-of-domain override(s): %s",
                len(dropped),
                ",".join(sorted(dropped)[:8]),
            )
        theme_tokens.set_theme_overrides(clean)
        return clean
    except Exception as exc:  # noqa: BLE001 - 回灌是旁路，绝不能反噬启动
        logger.debug("theme hydration failed: %s", exc)
        return {}


# ---- API 载荷（strict：`extra="forbid"`；写腿只带 CAS 版本）--------------


class VisualLayoutSavePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: LayoutScope
    expected_version: int = Field(strict=True, ge=0)
    spec: dict[str, Any]
    #: W12 R4：受限模板片段（标题/副标题/页脚纯文本）。缺省不动既有片段。
    fragments: dict[str, Any] | None = None


class VisualLayoutResetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: LayoutScope
    expected_version: int = Field(strict=True, ge=0)


class VisualPreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]
    #: 登记路径 → 样本值（只覆盖预览输出；未登记路径忽略）。
    sample: dict[str, Any] | None = None
    #: W12 R4：预览时可临时套用受限片段（不落库）。
    fragments: dict[str, Any] | None = None


class VisualThemePayload(BaseModel):
    """全局视觉覆盖写（W12 R4）：主色 / 圆角 / 字体，登记值域内。"""

    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, Any]
    expected_version: int = Field(strict=True, ge=0)


class VisualThemeRollbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(strict=True, ge=0)
