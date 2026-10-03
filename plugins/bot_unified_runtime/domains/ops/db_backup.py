"""SQLite 在线备份腿（席 X1b · P4.1 保命件，2026-10-02）。

为什么必须有这条腿：本仓跑着好感度／回复风格／订阅／日程／笔记／称谓偏好这类
**删了不可再生**的用户数据（名册见 ``docs/db-owners.md``），而代码级备份此前为零
（工单 ① 段带 file:line 取证）。本模块只做一件事：把 Runtime 数据根里的每一枚
``*.sqlite3`` 用 **sqlite3 在线备份 API** 打成一致快照，落**仓库外**，并给每份副本
配一枚可校验的旁车 manifest。

三条不可让的口径（写死在这里，别让后来人重新发明）：

1. **只准 ``Connection.backup()``，裸拷文件在 WAL 下会拿到撕裂副本。**
   本席实测（2026-10-02，``ChatBot_Runtime`` 同构复现）：源库 WAL 里躺着未 checkpoint
   的一行时，字节级裸拷只读出旧行、在线备份拿到全部行——这不是理论，是真盘会踩的账。
2. **对生产库一律 read-only**（``file:...?mode=ro``）。禁 ``VACUUM``、禁改
   ``journal_mode``、禁 checkpoint 截断；源连接上任何写都会当场抛
   ``OperationalError: attempt to write a readonly database``（同批实测）。
3. **覆盖动作绝不自动发生。** 本模块提供的是「校验 + 落 staging」，
   写回生产路径一律拒绝（``_reject_production_target``），
   删旧副本必须「先出清单、再逐枚点名批准」，且不递归、只认白名单文件名。

时间口径（台账 #6★：cron 走系统本地时区、与 ``bot_timezone`` 混过一次账）：
manifest 同时记 ① UTC 瞬时（带 ``+00:00``）② ``bot_timezone`` 本地墙钟（带偏移，如
``+08:00``）③ 该偏移的分钟数与 tz 名。任何一侧被改写都能被 ``verify_backup`` 抓到。

阈值不是拍脑袋（AGENTS 规则 10 + 本波判据纪律：数字要来自真实分布分档）：
基线＝2026-10-01T17:00Z 只读普查 42 枚库、共 19.65 GB，其中
``kb_wiki_embeddings`` 17.4 GB、``knowledge_embeddings`` 908 MB（两枚向量库可由源文档
重建，见 db-owners），**其余 40 枚合计约 19 MB**、单枚最大 5.7 MB；同卷剩余 111 GB。
于是缺省线落在真空档里：尺寸上界 64 MiB（5.7 MB 与 908 MB 之间，跨 150 倍真空）、
每库保留 7 枚（内容库全量 ×7 ≈ 133 MB）、备份区总量上界 4 GiB、开跑前剩余下限 20 GiB。
复跑口径见工单 ①。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

__all__ = [
    "COPY_NAME_RE",
    "DB_SUFFIX",
    "MANIFEST_SUFFIX",
    "STALE_UNKNOWN",
    "BackupError",
    "BackupPolicy",
    "apply_retention",
    "backup_all",
    "backup_one",
    "discover_databases",
    "format_reply",
    "list_backups",
    "load_policy",
    "manifest_in_root",
    "plan_restore",
    "plan_retention",
    "read_manifest",
    "resolve_backup_root",
    "restore_stage",
    "status_report",
    "verify_backup",
    "verify_backups",
    "write_run_log",
]

DB_SUFFIX = ".sqlite3"
MANIFEST_SUFFIX = ".manifest.json"
#: 副本文件名 = ``<库名去后缀>_<UTC 14 位时间戳>_<来源相对路径 sha8>.sqlite3``。
#: 时间戳只认 UTC（可排序、无偏移歧义），带偏移的墙钟只进 manifest（台账 #6★）。
COPY_NAME_RE = re.compile(
    r"^(?P<stem>[A-Za-z0-9_\-\.]+)_(?P<stamp>\d{14})_(?P<tag>[0-9a-f]{8})\."
    + re.escape(DB_SUFFIX.lstrip("."))
    + r"$"
)
_STATUS_OK = "ok"
_STATUS_FAILED = "failed"
_STATUS_SKIPPED = "skipped"

#: 计数护栏：超过这个表数就只做抽样（scope 会写进 manifest，不许冒充全量）。
_MAX_CENSUS_TABLES = 200
#: 单枚表名列表在 manifest 里的上限（超限库只登记名字，不逐表计数）。
_MAX_NAME_LIST = 400

_SWEEP_LOCK = threading.Lock()
STALE_UNKNOWN = -1.0


class BackupError(ValueError):
    """备份腿的判定失败（越界落点、批准名不在清单、副本不匹配 manifest…）。

    住 ``ValueError`` 族：接线面（``domains/ops/admin/runtime_admin.py``）的
    ``except (ValueError, TypeError)`` 会把它转成人话结果，而不是把栈抛穿聊天链路。
    """


@dataclass(frozen=True)
class BackupPolicy:
    """一次备份轮次的全部可调项（缺省值来自本席现算的真实分布，见模块 docstring）。"""

    enabled: bool = False
    backup_dir_text: str = ""
    keep_last: int = 7
    size_ceiling_bytes: int = 64 * 1024 * 1024
    max_footprint_bytes: int = 4 * 1024 * 1024 * 1024
    min_free_bytes: int = 20 * 1024 * 1024 * 1024
    stale_after_hours: int = 24
    timezone_name: str = "UTC"

    def local_tzinfo(self) -> Any:
        """本地墙钟的 tzinfo：``bot_timezone`` 优先，tzdata 缺席时退系统偏移。

        两条腿**都带偏移**——台账 #6★ 的账就输在 naive：Windows 上 ``zoneinfo`` 没有
        系统 tzdata 时 ``ZoneInfo(...)`` 直接抛，若为此退回 ``datetime.now()`` 就写不出
        ``+08:00``，manifest 的时刻重新变成猜的。
        """
        if self.timezone_name:
            try:
                return ZoneInfo(self.timezone_name)
            except Exception:  # noqa: BLE001,S110 - tz 名/tzdata 任一不合都算降级，绝不退 naive；吞异常是刻意的 fail-open
                pass
        return datetime.now(timezone.utc).astimezone().tzinfo


@dataclass(frozen=True)
class DbCandidate:
    """一枚待备份的库：路径 + 相对名 + 尺寸（读盘现算，不缓存）。"""

    name: str
    path: Path
    rel: str
    size_bytes: int


@dataclass
class BackupOutcome:
    """一轮 sweep 的结构化读数（运维命令与巡检都吃这一枚，别在别处再算一遍）。"""

    policy: BackupPolicy
    backup_root: Path
    considered: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> list[dict[str, Any]]:
        return [row for row in self.outcomes if row["status"] == _STATUS_OK]

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [row for row in self.outcomes if row["status"] == _STATUS_FAILED]

    @property
    def skipped(self) -> list[dict[str, Any]]:
        return [row for row in self.outcomes if row["status"] == _STATUS_SKIPPED]

    def to_dict(self) -> dict[str, Any]:
        """读数 → 可 JSON 化的字典（运维命令与运行日志共用这一份，别各算一套）。"""
        return {
            "enabled": self.policy.enabled,
            "backup_root": str(self.backup_root),
            "considered": self.considered,
            "ok": len(self.succeeded),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "notes": self.notes,
            "outcomes": self.outcomes,
        }


# ---------------------------------------------------------------------------
# 配置读数：本席禁改 ``config.py``，所以一律 getattr + 缺省，并把精确需求登记进
# patches/X1b-CONFIG-REQUEST.md（台账 #68★：只补一面必红另一面，故四面交主会话同批落）。
# ---------------------------------------------------------------------------


def _read_int(config: Any, name: str, default: int, *, minimum: int, maximum: int) -> int:
    """取一枚整数策略值并**夹到区间内**：越界取值不许把上界撑开或压成零。"""
    raw = getattr(config, name, None)
    try:
        value = default if raw is None else int(str(raw).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def load_policy(config: Any) -> BackupPolicy:
    """把 config 上的 ``bot_db_backup_*`` 读成一枚 :class:`BackupPolicy`。

    缺省 ``enabled=False``＝现网哑面（本席无权改 ``config.py``/``.env``）。
    开关语义：关掉只影响「会不会自动跑」，``status``/``verify`` 两条读腿永远可用。
    """
    flag = getattr(config, "bot_db_backup_enabled", None)
    if flag is None:
        flag = os.environ.get("BOT_DB_BACKUP_ENABLED", "")
    enabled = str(flag).strip().lower() in {"1", "true", "yes", "on"}
    tz_name = str(getattr(config, "bot_timezone", "UTC") or "UTC").strip() or "UTC"
    return BackupPolicy(
        enabled=enabled,
        backup_dir_text=str(getattr(config, "bot_db_backup_dir", "") or "").strip(),
        keep_last=_read_int(config, "bot_db_backup_keep_last", 7, minimum=1, maximum=64),
        size_ceiling_bytes=_read_int(
            config, "bot_db_backup_size_ceiling_bytes", 64 * 1024 * 1024,
            minimum=1024, maximum=2 * 1024 * 1024 * 1024,
        ),
        max_footprint_bytes=_read_int(
            config, "bot_db_backup_max_footprint_bytes", 4 * 1024 * 1024 * 1024,
            minimum=1024 * 1024, maximum=512 * 1024 * 1024 * 1024,
        ),
        min_free_bytes=_read_int(
            config, "bot_db_backup_min_free_bytes", 20 * 1024 * 1024 * 1024,
            minimum=0, maximum=1024 * 1024 * 1024 * 1024,
        ),
        stale_after_hours=_read_int(
            config, "bot_db_backup_stale_after_hours", 24, minimum=1, maximum=24 * 30
        ),
        timezone_name=tz_name,
    )


def _data_root(config: Any) -> Path:
    """Runtime 数据根（生产＝``ChatBot_Runtime/data``）。两口径同源，config 优先。"""
    text = str(getattr(config, "bot_runtime_data_dir", "") or "").strip()
    if text:
        path = Path(text).expanduser()
        if not path.is_absolute():
            from scripts.runtime_paths import PROJECT_ROOT

            path = PROJECT_ROOT / path
        return path.resolve()
    from scripts.runtime_paths import runtime_data_dir

    return runtime_data_dir()


def resolve_backup_root(config: Any, policy: BackupPolicy | None = None) -> Path:
    """备份落点（**必须仓库外**）：config 指定 → 否则 ``<Runtime 根>/backups/sqlite``。

    缺省落点刻意放在**数据根之外、Runtime 之下**（``ChatBot_Runtime/backups/sqlite``）：
    本席烟雾实测踩过——落点住进 ``ChatBot_Runtime/data`` 里，``_reject_production_target``
    会把「暂存到落点内的 staging」一起判成还原进生产，还原校验腿当场变成走不通的假门；
    而且副本混在活库名册里，全靠发现环节排除，多一处少一处就看运气。

    两道人质：① 落点在源码树内＝当场抛（规则 1/6：工作区不放运行数据）；
    ② 落点落进数据根时仍然允许（运维把 ``bot_db_backup_dir`` 写成 ``data/…`` 很自然），
    但发现环节整片排除它，免得把上一轮的副本当库再备一遍。
    """
    active = policy or load_policy(config)
    repo_root = Path(__file__).resolve().parents[4]
    if active.backup_dir_text:
        raw = Path(active.backup_dir_text).expanduser()
        root = raw if raw.is_absolute() else _data_root(config).parent / raw
        root = root.resolve()
    else:
        root = (_data_root(config).parent / "backups" / "sqlite").resolve()
    try:
        root.relative_to(repo_root)
    except ValueError:
        return root
    raise BackupError(f"备份落点必须在仓库外（现算={root}，仓库根={repo_root}）")


# ---------------------------------------------------------------------------
# 发现：名册现算，不抄清单（规则 10）
# ---------------------------------------------------------------------------


def _config_declared_db_paths(config: Any) -> list[Path]:
    """config 上声明过的 ``*_db``/``*_db_path`` 路径字段（只认 ``.sqlite3`` 结尾）。

    真实 ``Config`` 已在 ``_resolve_runtime_data_paths`` 里把 ``data/...`` 解析成绝对路
    径；这里再兜一层 ``runtime_path``，是为了让「没跑过校验器的替身 config」（测试里
    常见）也得到同一个落点，而不是按进程 CWD 猜（台账 #50★：行号与形态都会漂）。
    """
    found: list[Path] = []
    declared: Any = getattr(type(config), "model_fields", None)
    names = list(declared or {}) or [key for key in vars(config)]
    for name in names:
        if not name.endswith(("_db", "_db_path")):
            continue
        value = getattr(config, name, None)
        if not (isinstance(value, str) and value.strip().lower().endswith(DB_SUFFIX)):
            continue
        text = value.strip()
        path = Path(text).expanduser()
        if not path.is_absolute():
            from scripts.runtime_paths import runtime_path

            path = runtime_path(text)
        found.append(path.resolve())
    return found


def discover_databases(config: Any, policy: BackupPolicy | None = None) -> list[DbCandidate]:
    """盘上扫 + config 声明，两路并集（去重、跳过 -wal/-shm、跳过备份落点内部）。

    为什么两路：台账 #68★ 的幽灵字段教训——盘上有而名册没有、或名册有而盘上没落盘，
    任一单独口径都会漏库。漏的那枚恰好是没在写的那枚，正是最需要备份的。
    """
    active = policy or load_policy(config)
    root = _data_root(config)
    backup_root = resolve_backup_root(config, active)
    candidates: dict[Path, str] = {}
    if root.is_dir():
        for path in sorted(root.rglob(f"*{DB_SUFFIX}")):
            if not path.is_file():
                continue
            _add_candidate(candidates, path, root, backup_root)
    for path in _config_declared_db_paths(config):
        if path.is_file():
            _add_candidate(candidates, path, root, backup_root)
    return [
        DbCandidate(name=path.name, path=path, rel=rel,
                    size_bytes=path.stat().st_size if path.is_file() else 0)
        for path, rel in sorted(candidates.items(), key=lambda kv: kv[1].lower())
    ]


def _add_candidate(store: dict[Path, str], path: Path, data_root: Path, backup_root: Path) -> None:
    """登记一枚候选库；WAL/SHM 伴生件与**备份落点内部**的副本一律不进名册。

    排除落点内部这一条是人质：上一轮的副本就住在数据根的兄弟目录里，一旦有人把
    落点配成 ``data/db_backups``，不排除就会拿副本再备一份、副本吃副本（自我增殖）。
    """
    if path.name.endswith(("-wal", "-shm")):
        return
    if path == backup_root or _is_under(path, backup_root):
        return
    try:
        rel = path.relative_to(data_root).as_posix()
    except ValueError:
        rel = path.name
    store.setdefault(path.resolve(), rel)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# 时间戳（台账 #6★）
# ---------------------------------------------------------------------------


def _now_pair(policy: BackupPolicy, now: datetime | None) -> tuple[datetime, datetime]:
    """返回 (UTC 瞬时, 本地墙钟)，两者都带偏移——naive datetime 在本模块不存在。"""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise BackupError("备份腿拒绝 naive datetime（台账 #6★：时区混用踩过 cron 账）")
    utc = instant.astimezone(timezone.utc)
    return utc, utc.astimezone(policy.local_tzinfo())


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 只读打开 + 计数
# ---------------------------------------------------------------------------


def _open_ro(path: Path) -> sqlite3.Connection:
    """read-only URI 连接（``mode=ro``）：对生产库唯一允许的打开方式。"""
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _census(conn: sqlite3.Connection) -> dict[str, Any]:
    """表数 + 行数抽样。超过 ``_MAX_CENSUS_TABLES`` 只做抽样并**如实标注 scope**。

    单表计数失败（缺权限/虚表/坏对象）不许吃掉整枚库：该表记 ``-1`` 并把异常原文
    放进 ``row_count_errors``，scope 降成 ``partial``——manifest 里诚实的半本账
    比假装全绿的整本账有用（``verify_backup`` 会照 scope 判）。
    """
    names = _table_names(conn)
    scope = "full" if len(names) <= _MAX_CENSUS_TABLES else "sampled"
    listed = names if len(names) <= _MAX_CENSUS_TABLES else names[:_MAX_CENSUS_TABLES]
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for name in listed:
        try:
            counts[name] = int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        except sqlite3.Error as exc:
            counts[name] = -1
            errors[name] = _error_text(exc)
            scope = "partial"
    return {
        "table_count": len(names),
        "table_names": names[:_MAX_NAME_LIST],
        "row_counts": counts,
        "row_count_errors": errors,
        "row_count_scope": scope,
        "total_rows": sum(v for v in counts.values() if v > 0),
    }


def _error_text(exc: BaseException) -> str:
    """异常原文（不哑，台账 #71★）；盘符路径交给出站闸 ``redact_local_secrets`` 打码。"""
    return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 副本命名
# ---------------------------------------------------------------------------


def _safe_stem(db_name: str) -> str:
    """库名 → 副本文件名词干（只留文件名安全字符）。

    两处调用共用这一把尺：``_copy_name`` 用它写文件名、``status_report`` 用它回推
    「这枚库有没有在册副本」。写成两份迟早漂移，那时体检会把「明明备过」读成
    ``never_backed_up``（台账 #68★ 的「盘上字段≠运行时状态」同族坑）。
    """
    stem = db_name.removesuffix(DB_SUFFIX)
    return re.sub(r"[^A-Za-z0-9_\-\.]", "_", stem) or "db"


def _copy_name(candidate: DbCandidate, stamp_utc: datetime) -> str:
    tag = hashlib.sha256(candidate.rel.encode("utf-8")).hexdigest()[:8]
    return f"{_safe_stem(candidate.name)}_{stamp_utc.strftime('%Y%m%d%H%M%S')}_{tag}{DB_SUFFIX}"


def _manifest_path(copy_path: Path) -> Path:
    return copy_path.with_name(copy_path.name + MANIFEST_SUFFIX)


def read_manifest(path: Path) -> dict[str, Any]:
    """读旁车 manifest（utf-8 strict：坏字节当场抛，不许静默吞成半本账）。"""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 备份：唯一写动作，且只写备份落点
# ---------------------------------------------------------------------------


def _drop_copy_sidecars(copy_path: Path) -> list[str]:
    dropped: list[str] = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = copy_path.with_name(copy_path.name + suffix)
        if sidecar.is_file():
            sidecar.unlink()
            dropped.append(sidecar.name)
    return dropped


def backup_one(
    candidate: DbCandidate,
    config: Any,
    policy: BackupPolicy | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """对一枚库做在线备份 + 旁车 manifest，返回结构化读数（永不抛穿，失败如实登记）。

    成功路径：ro 开源 → ``src.backup(dst)`` → 提交并关闭 → 副本自检（integrity +
    结构 + 计数）→ 尺寸/摘要现算 → manifest 落盘（同目录、``.sqlite3.manifest.json``）。
    """
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    utc, local = _now_pair(active, now)
    row: dict[str, Any] = {
        "db": candidate.name,
        "rel": candidate.rel,
        "source_size_bytes": candidate.size_bytes,
        "status": _STATUS_FAILED,
    }
    if candidate.size_bytes > active.size_ceiling_bytes:
        row["status"] = _STATUS_SKIPPED
        row["reason"] = "over_size_ceiling"
        row["detail"] = (
            f"{candidate.size_bytes}B > 上界 {active.size_ceiling_bytes}B"
            "（可重建的大体积向量库，默认不备；点名要备就显式传 candidate）"
        )
        return row
    try:
        root.mkdir(parents=True, exist_ok=True)
        # 剩余空间守卫走已登记真身（host_metrics.free_bytes_for）＝single-entry 门
        # gate2 的「调真身、不添第三读者」口径；本文件自此不再自带 shutil.disk_usage 直调。
        from plugins.bot_unified_runtime.domains.ops import host_metrics

        free = host_metrics.free_bytes_for(root)
        if free < active.min_free_bytes:
            row["reason"] = "low_disk"
            row["detail"] = f"剩余 {free}B < 下限 {active.min_free_bytes}B"
            return row
        copy_path = root / _copy_name(candidate, utc)
        row["copy"] = copy_path.name
        source = _open_ro(candidate.path)
        try:
            source_mode = source.execute("PRAGMA journal_mode").fetchone()[0]
            target = sqlite3.connect(str(copy_path))
            try:
                source.backup(target)
                target.commit()
                # 副本必须收成**单文件**：``backup()`` 连页头一起搬，源库的 WAL 声明
                # 也进了副本，一开就拖出 ``-wal``/``-shm``。生产库那侧禁改这个（会动到
                # 活库），但副本是**我们自己落点的产物**，切回 rollback journal 才拿得准
                # 「一枚文件就是整份备份」——否则裁副本时伴生件变孤儿，还原时按
                # db-owners 的「删库连带伴生」规矩一清，等于把最后一帧数据也清了。
                copy_mode = str(target.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
                target.commit()
            finally:
                target.close()
        finally:
            source.close()
        row["sidecars_dropped"] = _drop_copy_sidecars(copy_path)
        # 副本自检：断言副本可读、结构自洽、行数与源侧同尺（源侧此刻仍是 ro）
        copy_probe = _open_ro(copy_path)
        try:
            integrity = copy_probe.execute("PRAGMA integrity_check").fetchone()[0]
            copy_census = _census(copy_probe)
            probed_mode = str(copy_probe.execute("PRAGMA journal_mode").fetchone()[0])
        finally:
            copy_probe.close()
        source_probe = _open_ro(candidate.path)
        try:
            source_census = _census(source_probe)
        finally:
            source_probe.close()
        size = copy_path.stat().st_size
        digest = _sha256(copy_path)
        manifest = {
            "schema": 1,
            "db": candidate.name,
            "rel": candidate.rel,
            "source_path": str(candidate.path),
            "copy": copy_path.name,
            "size_bytes": size,
            "sha256": digest,
            "source_size_bytes": candidate.size_bytes,
            "source_journal_mode": str(source_mode),
            "copy_journal_mode": probed_mode,
            "copy_journal_mode_after_backup": copy_mode,
            "copy_sidecars_dropped": row["sidecars_dropped"],
            "copy_is_single_file": not any(
                (root / (copy_path.name + suffix)).exists() for suffix in ("-wal", "-shm")
            ),
            "source_table_count": source_census["table_count"],
            "source_row_counts": source_census["row_counts"],
            "source_row_count_scope": source_census["row_count_scope"],
            "table_count": copy_census["table_count"],
            "table_names": copy_census["table_names"],
            "row_counts": copy_census["row_counts"],
            "row_count_errors": copy_census["row_count_errors"],
            "row_count_scope": copy_census["row_count_scope"],
            "total_rows": copy_census["total_rows"],
            "integrity_check": str(integrity),
            "sqlite_version": sqlite3.sqlite_version,
            "created_at_utc": _iso(utc),
            "created_at_local": _iso(local),
            "created_utc_offset_minutes": int(offset.total_seconds() // 60)
            if (offset := local.utcoffset()) is not None
            else 0,
            "timezone_name": active.timezone_name,
            "source_mtime_utc": _iso(
                datetime.fromtimestamp(candidate.path.stat().st_mtime, timezone.utc)
            ),
            "policy": {
                "keep_last": active.keep_last,
                "size_ceiling_bytes": active.size_ceiling_bytes,
                "max_footprint_bytes": active.max_footprint_bytes,
                "min_free_bytes": active.min_free_bytes,
            },
        }
        _manifest_path(copy_path).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        row.update(
            {
                "status": _STATUS_OK if str(integrity) == "ok" else _STATUS_FAILED,
                "size_bytes": size,
                "sha256_12": digest[:12],
                "table_count": manifest["table_count"],
                "total_rows": manifest["total_rows"],
                "integrity_check": manifest["integrity_check"],
                "created_at_utc": manifest["created_at_utc"],
                "created_at_local": manifest["created_at_local"],
                "manifest": _manifest_path(copy_path).name,
            }
        )
        if row["status"] == _STATUS_FAILED:
            row["detail"] = f"副本自检非 ok：{integrity}"
    except (sqlite3.Error, OSError, BackupError) as exc:
        row["status"] = _STATUS_FAILED
        row["detail"] = _error_text(exc)
    return row


def backup_all(
    config: Any,
    policy: BackupPolicy | None = None,
    *,
    now: datetime | None = None,
    only: list[str] | None = None,
    include_regenerable: bool = False,
) -> BackupOutcome:
    """全轮次：发现 → 逐枚在线备份 → 保留策略出清单并按名删（同一次批准）。

    ``only``＝点名库名（运维命令用，绝不放开成前缀猜）；
    ``include_regenerable``＝把超上界的可重建大库也纳入（显式才生效）。
    并发保护＝非阻塞锁：抢不到就直接如实报「另一轮在跑」，不起第二本账。
    """
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    report = BackupOutcome(policy=active, backup_root=root)
    if not active.enabled:
        report.notes.append("开关未开（bot_db_backup_enabled 缺省 False），本轮零写入")
        return report
    if not _SWEEP_LOCK.acquire(blocking=False):
        report.notes.append("另一轮备份在跑，本轮退出（不并行写同一落点）")
        return report
    # 显式点名要备大库时，把上界抬到「本轮之内」而不是改全局策略：
    # 宣称与实装必须同尺——旧写法只压掉了那句提示、``backup_one`` 里照样跳过，
    # 等于命令说「已纳入」而盘上什么都没发生。
    working = active
    if include_regenerable:
        working = replace(active, size_ceiling_bytes=2**62)
    try:
        candidates = discover_databases(config, active)
        if only:
            wanted = {item.strip().lower() for item in only if item.strip()}
            candidates = [c for c in candidates if c.name.lower() in wanted]
        over = [c for c in candidates if c.size_bytes > active.size_ceiling_bytes]
        report.considered = len(candidates)
        for candidate in candidates:
            report.outcomes.append(backup_one(candidate, config, working, now=now))
        if over and not include_regenerable:
            report.notes.append(
                f"{len(over)} 枚超尺寸上界未备（{', '.join(c.name for c in over[:5])}"
                + ("…）" if len(over) > 5 else "）")
            )
        plan = plan_retention(config, active, root=root)
        approved = [item["name"] for item in plan["candidates"]]
        if approved:
            prune = apply_retention(config, approved, policy=active, plan=plan, root=root)
            report.notes.append(
                f"保留策略按名删 {prune['deleted']} 枚（清单 {len(approved)} 枚，"
                f"拒绝 {prune['refused']}；点名={', '.join(prune['deleted_names'][:5])}）"
            )
    finally:
        _SWEEP_LOCK.release()
    write_run_log(config, report, root=root)
    return report


# ---------------------------------------------------------------------------
# 保留策略：先出清单，删只能按名点名
# ---------------------------------------------------------------------------


def _copy_rows(root: Path) -> list[dict[str, Any]]:
    """备份落点里的**在册副本**（文件名必须过 ``COPY_NAME_RE``，目录一律不碰）。"""
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        match = COPY_NAME_RE.match(entry.name)
        if not match:
            continue
        manifest = _manifest_path(entry)
        info: dict[str, Any] = {
            "name": entry.name,
            "path": entry,
            "stem": match.group("stem"),
            "stamp": match.group("stamp"),
            "size_bytes": entry.stat().st_size,
            "manifest": manifest.name if manifest.is_file() else "",
        }
        if manifest.is_file():
            try:
                data = read_manifest(manifest)
                info["created_at_utc"] = str(data.get("created_at_utc", ""))
                info["size_bytes"] = int(data.get("size_bytes", info["size_bytes"]))
            except (OSError, ValueError) as exc:
                info["manifest_error"] = _error_text(exc)
        rows.append(info)
    return rows


def plan_retention(
    config: Any, policy: BackupPolicy | None = None, *, root: Path | None = None
) -> dict[str, Any]:
    """算出「该淘汰哪些」清单（**只算不删**）：每库留 keep_last 枚，再压总量上界。

    排序＝``created_at_utc`` 优先（manifest 真身），缺失回落文件名字面时间戳，
    再缺失按最旧处理（宁可多留不误删新副本——排序里排最后＝先被删的是它自己）。
    """
    active = policy or load_policy(config)
    root = root or resolve_backup_root(config, active)
    rows = _copy_rows(root)
    by_db: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("manifest_error"):
            continue
        by_db.setdefault(row["stem"], []).append(row)
    candidates: list[dict[str, Any]] = []
    for stem, group in sorted(by_db.items()):
        ordered = sorted(group, key=lambda r: r.get("created_at_utc") or r["stamp"], reverse=True)
        for index, row in enumerate(ordered):
            if index >= active.keep_last:
                candidates.append({"name": row["name"], "reason": f"over_keep_last:{stem}"})
    survivors = {row["name"] for row in rows} - {item["name"] for item in candidates}
    footprint = sum(row["size_bytes"] for row in rows if row["name"] in survivors)
    for row in sorted(rows, key=lambda r: r.get("created_at_utc") or r["stamp"]):
        if footprint <= active.max_footprint_bytes:
            break
        if row["name"] in survivors:
            candidates.append({"name": row["name"], "reason": "over_footprint"})
            footprint -= row["size_bytes"]
    return {
        "backup_root": str(root),
        "copies_total": len(rows),
        "footprint_bytes": sum(row["size_bytes"] for row in rows),
        "keep_last": active.keep_last,
        "max_footprint_bytes": active.max_footprint_bytes,
        "candidates": candidates,
        "orphans": _orphan_report(root, rows),
    }


def _orphan_report(root: Path, copies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """落点里的**孤儿形态**登记（只报不删；删要人点名，别让尺自己动刀）。

    三类都要看见，因为每一类都对应一种"账对不上"：
    ① 有旁车没副本＝副本被别处删了、账还在；② 有副本没旁车＝来路不明（不是本模块
    产出的就别当备份用）；③ 副本名下的 ``-wal``/``-shm`` 残留＝WAL 没收干净，
    按 db-owners 的「删库连带伴生」规矩处理时容易把最后一帧数据一起清掉。
    """
    known = {row["manifest"] for row in copies if row.get("manifest")}
    copy_names = {row["name"] for row in copies}
    orphans: list[dict[str, Any]] = []
    if not root.is_dir():
        return orphans
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.endswith(MANIFEST_SUFFIX) and entry.name not in known:
            orphans.append({"name": entry.name, "reason": "manifest_without_copy"})
            continue
        if entry.name.endswith(("-wal", "-shm", "-journal")):
            owner = entry.name.rsplit("-", 1)[0]
            orphans.append({
                "name": entry.name,
                "reason": "copy_sidecar_residue" if owner in copy_names else "sidecar_without_copy",
            })
    for row in copies:
        if not row.get("manifest"):
            orphans.append({"name": row["name"], "reason": "copy_without_manifest"})
    return orphans


def apply_retention(
    config: Any,
    approved_names: list[str],
    policy: BackupPolicy | None = None,
    *,
    plan: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """**按名点名删**：批准名单必须逐枚命中清单，且只删落点直下的在册文件。

    四道人质（09-30 两次整片灭失的教训写死在这里）：
    ① 名单为空 ⇒ 零删除；② 名字不在本轮清单 ⇒ 拒；③ 名字含路径分隔符或不是
    ``COPY_NAME_RE`` 在册副本 ⇒ 拒；④ 解析后父目录不等于落点 ⇒ 拒。
    没有任何一条腿会 ``rmtree``／``glob("*)``／按前缀猜。
    """
    active = policy or load_policy(config)
    root = (root or resolve_backup_root(config, active)).resolve()
    result: dict[str, Any] = {"deleted": 0, "refused": 0, "deleted_names": [], "refused_names": []}
    if not approved_names:
        return result
    allowed = {item["name"] for item in (plan or plan_retention(config, active, root=root))["candidates"]}
    for raw in approved_names:
        name = str(raw)
        target = (root / name).resolve()
        checks_ok = (
            name in allowed
            and COPY_NAME_RE.match(name) is not None
            and target.parent == root
            and target.is_file()
        )
        if not checks_ok:
            result["refused"] += 1
            result["refused_names"].append(name)
            continue
        manifest = _manifest_path(target)
        target.unlink()
        if manifest.is_file():
            manifest.unlink()
        result["deleted"] += 1
        result["deleted_names"].append(name)
    return result


# ---------------------------------------------------------------------------
# 校验与还原（覆盖绝不自动发生）
# ---------------------------------------------------------------------------


def verify_backup(manifest_path: Path) -> dict[str, Any]:
    """旁车 ↔ 副本 一致性校验：摘要、尺寸、integrity、表数、行数逐条对账。

    这是「还原前唯一可信的读数」：任何一条不匹配都 ``ok=False`` 并列出原因。
    """
    verdict: dict[str, Any] = {"manifest": manifest_path.name, "ok": False, "problems": []}
    try:
        data = read_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        verdict["problems"].append(_error_text(exc))
        return verdict
    copy_path = manifest_path.with_name(manifest_path.name[: -len(MANIFEST_SUFFIX)])
    verdict["db"] = str(data.get("db", ""))
    verdict["created_at_utc"] = str(data.get("created_at_utc", ""))
    verdict["created_at_local"] = str(data.get("created_at_local", ""))
    if not copy_path.is_file():
        verdict["problems"].append("副本文件缺席")
        return verdict
    if COPY_NAME_RE.match(copy_path.name) is None:
        verdict["problems"].append("副本文件名不在册（不是本模块产出的形态）")
    size = copy_path.stat().st_size
    if size != int(data.get("size_bytes", -1)):
        verdict["problems"].append(f"尺寸不符：盘上 {size} != 旁车 {data.get('size_bytes')}")
    digest = _sha256(copy_path)
    verdict["sha256_12"] = digest[:12]
    if digest != str(data.get("sha256", "")):
        verdict["problems"].append("sha256 不符（副本被改写或位腐）")
    try:
        conn = _open_ro(copy_path)
        try:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            census = _census(conn)
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        verdict["problems"].append(f"副本打不开：{_error_text(exc)}")
        return verdict
    verdict["integrity_check"] = integrity
    recorded_integrity = str(data.get("integrity_check", "ok"))
    if integrity != "ok" or recorded_integrity != "ok":
        verdict["problems"].append(
            f"integrity_check=副本 {integrity} / 旁车 {recorded_integrity}"
        )
    verdict["table_count"] = census["table_count"]
    verdict["row_counts"] = census["row_counts"]
    if census["table_count"] != int(data.get("table_count", -1)):
        verdict["problems"].append(
            f"表数不符：副本 {census['table_count']} != 旁车 {data.get('table_count')}"
        )
    recorded = data.get("row_counts") or {}
    if census["row_count_scope"] == data.get("row_count_scope"):
        drift = [
            f"{name}: 副本 {rows} != 旁车 {recorded.get(name)}"
            for name, rows in sorted(census["row_counts"].items())
            if recorded.get(name) != rows
        ]
        if drift:
            verdict["problems"].extend(drift[:8])
    else:
        # 计数口径变了＝这本账不可比。宁可标「未对账」，不许默默当通过。
        verdict.setdefault("notes", []).append(
            f"行数口径变化（旁车 {data.get('row_count_scope')} → 副本 {census['row_count_scope']}），行数未对账"
        )
    verdict["row_count_scope"] = census["row_count_scope"]
    verdict["ok"] = not verdict["problems"]
    return verdict


def list_backups(
    config: Any, policy: BackupPolicy | None = None, *, db: str = ""
) -> list[dict[str, Any]]:
    """在册副本清单（只读，按库名过滤）：运维命令的「有哪些可验/可还原」腿。"""
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    wanted = db.strip().lower()
    rows: list[dict[str, Any]] = []
    for row in _copy_rows(root):
        if wanted and wanted not in (row["stem"].lower(), row.get("db", "").lower()):
            continue
        rows.append({
            "copy": row["name"],
            "stem": row["stem"],
            "db": row.get("db", row["stem"] + DB_SUFFIX),
            "manifest": row.get("manifest", ""),
            "created_at_utc": row.get("created_at_utc", ""),
            "size_bytes": row["size_bytes"],
            "manifest_error": row.get("manifest_error", ""),
        })
    return rows


def verify_backups(
    config: Any,
    policy: BackupPolicy | None = None,
    *,
    db: str = "",
    copy: str = "",
    newest_only: bool = True,
) -> list[dict[str, Any]]:
    """逐枚校验在册副本；缺省每库只验最新一枚（全验是运维显式点名才做）。

    ``copy``＝点名某一枚副本（烟雾实测踩过：只按库名过滤再取「最新一枚」，
    注毒的那枚被最新的好副本绕过 ⇒ 校验腿看着红过、其实没咬到东西）。
    """
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    rows = _copy_rows(root)
    if copy.strip():
        rows = [row for row in rows if row["name"] == copy.strip()]
    elif db.strip():
        wanted = db.strip().lower()
        rows = [row for row in rows if row["stem"].lower() == wanted]
    picked: list[dict[str, Any]] = []
    if newest_only and not copy.strip():
        newest: dict[str, dict[str, Any]] = {}
        for row in rows:
            current = newest.get(row["stem"])
            if current is None or (row.get("created_at_utc") or row["stamp"]) > (
                current.get("created_at_utc") or current["stamp"]
            ):
                newest[row["stem"]] = row
        picked = list(newest.values())
    else:
        picked = rows
    verdicts: list[dict[str, Any]] = []
    for row in picked:
        manifest = _manifest_path(row["path"])
        if not manifest.is_file():
            verdicts.append({
                "copy": row["name"],
                "ok": False,
                "problems": ["旁车 manifest 缺席（无从对账）"],
            })
            continue
        verdict = verify_backup(manifest)
        verdict["copy"] = row["name"]
        verdicts.append(verdict)
    return verdicts


def manifest_in_root(config: Any, name: str, policy: BackupPolicy | None = None) -> Path:
    """把运维命令传来的旁车**文件名**认成落点内的一枚 manifest。

    命令面收到的字符串属不可信输入：只认 basename、必须匹配在册形态、解析后必须
    仍直躺在备份落点下。任何一条不过就抛——否则 ``../../`` 一枚字符串就能把校验腿
    指到仓库外随便什么文件上去。
    """
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    text = str(name or "").strip()
    if not text or text != Path(text).name or "\\" in text or "/" in text:
        raise BackupError(f"旁车名不合法（只收文件名，不收路径）：{text!r}")
    if not text.endswith(MANIFEST_SUFFIX):
        text += MANIFEST_SUFFIX
    if COPY_NAME_RE.match(text[: -len(MANIFEST_SUFFIX)]) is None:
        raise BackupError(f"旁车名不在册（不是本模块产出形态）：{text}")
    target = (root / text).resolve()
    if target.parent != root or not target.is_file():
        raise BackupError(f"旁车不在备份落点内或不存在：{text}")
    return target


def staging_dir(config: Any, subdir: str = "", policy: BackupPolicy | None = None) -> Path:
    """还原暂存目录：``<备份落点>/staging[/<子目录名>]``。

    命令面只允许传**子目录名**（basename），整条路径不由聊天拼——否则一枚
    ``..\\..\\`` 就把「暂存」变成「写到任何想去的地方」。落点本身已在仓库外，
    且不落在数据根内（见 ``resolve_backup_root``），所以这里既不碰生产也不碰工作树。
    """
    root = resolve_backup_root(config, policy or load_policy(config))
    base = root / "staging"
    text = str(subdir or "").strip()
    if not text:
        return base
    if text != Path(text).name or "\\" in text or "/" in text:
        raise BackupError(f"暂存子目录名不合法（只收名字，不收路径）：{text!r}")
    return base / re.sub(r"[^A-Za-z0-9_\-\.]", "_", text)


def _reject_production_target(path: Path, config: Any) -> None:
    """还原落点人质：Runtime 数据根（含源码树 data/）之内一律拒绝。"""
    data_root = _data_root(config)
    repo_root = Path(__file__).resolve().parents[4]
    for blocked, label in ((data_root, "Runtime 数据根"), (repo_root, "源码树")):
        if path == blocked or _is_under(path, blocked):
            raise BackupError(
                f"还原不许自动覆盖任何生产路径（目标={path} 命中{label}）。"
                "覆盖动作必须由人显式执行：先停 bot（WAL 伴生 -wal/-shm 未合并会丢数据），"
                "再把 staging 副本移入并成对处理伴生文件——见 docs/db-owners.md 清理规程。"
            )


def plan_restore(manifest_path: Path, config: Any) -> dict[str, Any]:
    """还原前置：先过 ``verify_backup``，不过就绝不允许进入 staging。"""
    verdict = verify_backup(manifest_path)
    copy_path = manifest_path.with_name(manifest_path.name[: -len(MANIFEST_SUFFIX)])
    return {
        "verified": bool(verdict["ok"]),
        "copy": str(copy_path),
        "db": verdict.get("db", ""),
        "verify": verdict,
        "steps": [
            "1) 停 bot（不停就是往活库里覆盖）",
            "2) 人工核对 staging 副本与目标库名一致",
            "3) 移入时连带处理 -wal/-shm 伴生文件（旧伴生必须一起清）",
            "4) 起 bot 后只读复查关键表行数",
        ],
    }


def restore_stage(manifest_path: Path, config: Any, staging_dir: Path) -> dict[str, Any]:
    """把校验通过的副本**暂存**到 staging（绝不写回生产路径，绝不改名冒充原库）。"""
    plan = plan_restore(manifest_path, config)
    if not plan["verified"]:
        raise BackupError(f"副本未通过校验，拒绝进入还原流程：{plan['verify']['problems']}")
    staging = Path(staging_dir).expanduser().resolve()
    _reject_production_target(staging, config)
    staging.mkdir(parents=True, exist_ok=True)
    source = Path(plan["copy"])
    target = staging / source.name
    if target.exists():
        raise BackupError(f"staging 已存在同名件，拒绝覆盖：{target}")
    shutil.copy2(source, target)
    return {
        "staged": str(target),
        "sha256_12": _sha256(target)[:12],
        "db": plan["db"],
        "note": "仅暂存；落回生产路径的动作由人执行（本模块不提供覆盖腿）",
    }


# ---------------------------------------------------------------------------
# 状态读数与出站文本
# ---------------------------------------------------------------------------


def status_report(config: Any, policy: BackupPolicy | None = None) -> dict[str, Any]:
    """只读体检：该备的库有几枚在册、最新一枚隔了多久、缺旁车/超上界各是谁。

    ``over_ceiling`` 与 ``stale`` 分两本账记——合成一本就会把「按策略不备」和「该备
    却没备」混成同一个绿，而后者才是要叫人的那一枚（AGENTS 规则 11 的「失败面不哑」、
    台账 #71★ 同口径）。
    """
    active = policy or load_policy(config)
    root = resolve_backup_root(config, active)
    rows = _copy_rows(root)
    utc, _local = _now_pair(active, None)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = latest.get(row["stem"])
        if current is None or (row.get("created_at_utc") or row["stamp"]) > (
            current.get("created_at_utc") or current["stamp"]
        ):
            latest[row["stem"]] = row
    stale: list[dict[str, Any]] = []
    over_ceiling: list[dict[str, Any]] = []
    candidates = discover_databases(config, active)
    for candidate in candidates:
        if candidate.size_bytes > active.size_ceiling_bytes:
            over_ceiling.append({
                "db": candidate.name,
                "size_bytes": candidate.size_bytes,
                "state": "not_covered_by_policy",
            })
            continue
        entry = latest.get(_safe_stem(candidate.name))
        hours = STALE_UNKNOWN
        if entry is not None:
            stamp = entry.get("created_at_utc")
            if stamp:
                try:
                    hours = (utc - datetime.fromisoformat(str(stamp))).total_seconds() / 3600
                except ValueError:
                    hours = STALE_UNKNOWN
        if entry is None or hours > active.stale_after_hours:
            stale.append({
                "db": candidate.name,
                "age_hours": round(hours, 2) if hours != STALE_UNKNOWN else None,
                "state": "never_backed_up" if entry is None else "stale",
            })
    plan = plan_retention(config, active, root=root)
    return {
        "enabled": active.enabled,
        "backup_root": str(root),
        "outside_repo": not _is_under(root, Path(__file__).resolve().parents[4]),
        "outside_data_root": not _is_under(root, _data_root(config)),
        "databases_found": len(candidates),
        "databases_in_scope": len(candidates) - len(over_ceiling),
        "copies_on_disk": len(rows),
        "footprint_bytes": plan["footprint_bytes"],
        "max_footprint_bytes": active.max_footprint_bytes,
        "keep_last": active.keep_last,
        "size_ceiling_bytes": active.size_ceiling_bytes,
        "stale_after_hours": active.stale_after_hours,
        "retention_candidates": plan["candidates"],
        "orphans": plan["orphans"],
        "stale": stale,
        "over_ceiling": over_ceiling,
        "timezone_name": active.timezone_name,
    }


def write_run_log(config: Any, report: BackupOutcome, *, root: Path | None = None) -> None:
    """每轮追加一行运行日志（fail-open：日志写不进不许拖垮备份轮次，但会叫出来）。"""
    active = report.policy
    root = root or resolve_backup_root(config, active)
    utc, local = _now_pair(active, None)
    line = {
        "at_utc": _iso(utc),
        "at_local": _iso(local),
        "considered": report.considered,
        "ok": len(report.succeeded),
        "failed": len(report.failed),
        "skipped": len(report.skipped),
        "notes": report.notes,
        "failures": [
            {"db": row["db"], "detail": row.get("detail", row.get("reason", ""))}
            for row in report.failed[:20]
        ],
    }
    log_path = root / "backup_runs.jsonl"
    try:
        root.mkdir(parents=True, exist_ok=True)
        if log_path.is_file() and log_path.stat().st_size > 2 * 1024 * 1024:
            log_path.replace(log_path.with_name("backup_runs.jsonl.1"))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        report.notes.append(f"运行日志写入失败：{_error_text(exc)}")


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


_REPLY_KEY_ORDER: tuple[str, ...] = (
    "enabled", "outside_repo", "outside_data_root", "databases_found", "databases_in_scope",
    "copies_on_disk", "footprint_bytes", "max_footprint_bytes", "keep_last",
    "size_ceiling_bytes", "stale_after_hours", "considered", "ok", "failed", "skipped",
    "retention_candidates", "orphans", "stale", "over_ceiling", "verified",
    "copy", "staged", "db", "backup_root", "timezone_name", "notes", "steps", "problems",
)
_REPLY_LIST_LIMIT = 8
_REPLY_CHAR_LIMIT = 1500


def format_reply(payload: dict[str, Any] | list[Any], title: str = "数据库备份") -> str:
    """读数 → 出站文本。三条硬口径：

    ① **脱敏只在出站这一层做**（``redact_local_secrets`` 是唯一一把尺，别处不另装
    打码器）：盘符路径、``BOT_XXX=`` 形态在聊天里必须看不见，manifest 原文仍留在盘上。
    ② **不认的键也要说话**：只按白名单挑键渲染＝新增读数被静默吃掉（台账 #68★
    「策略段曾被尾裁静吃」同族），所以白名单之后再把余下键按序打出来。
    ③ 长度有顶：QQ 一条消息吃不下整本账，超出就明确写「还有 N 项未列」，
    绝不静默截半行（截半行的读数比少几条更害人）。
    """
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )

    lines: list[str] = [f"【{title}】"]
    items: list[tuple[str, Any]] = []
    if isinstance(payload, dict):
        ordered = [key for key in _REPLY_KEY_ORDER if key in payload]
        rest = sorted(key for key in payload if key not in _REPLY_KEY_ORDER)
        items = [(key, payload[key]) for key in ordered + rest]
    else:
        items = [(f"[{index}]", item) for index, item in enumerate(list(payload)[: _REPLY_LIST_LIMIT])]
    omitted = 0
    for key, value in items:
        if isinstance(value, list):
            lines.append(f"{key}={len(value)}")
            for item in value[:_REPLY_LIST_LIMIT]:
                lines.append(f"  - {json.dumps(item, ensure_ascii=False, default=str)}")
            omitted += max(0, len(value) - _REPLY_LIST_LIMIT)
        elif isinstance(value, (dict, tuple, set)):
            lines.append(f"{key}={json.dumps(list(value) if isinstance(value, set) else value, ensure_ascii=False, default=str)}")
        elif key.endswith("_bytes"):
            lines.append(f"{key}={_human_bytes(int(value))}")
        else:
            lines.append(f"{key}={value}")
    if omitted:
        lines.append(f"（另有 {omitted} 项未列出，全文见落点内的 manifest 与 backup_runs.jsonl）")
    text = "\n".join(lines)
    if len(text) > _REPLY_CHAR_LIMIT:
        cut = text.rfind("\n", 0, _REPLY_CHAR_LIMIT)
        text = f"{text[: cut if cut > 0 else _REPLY_CHAR_LIMIT]}\n（读数过长已按整行截断，完整账在盘上）"
    return redact_local_secrets(text)
