"""席 DBT（2026-10-02 修复波下午窗）——SQLite 在线备份腿回归锁。

生产件＝ ``plugins/bot_unified_runtime/domains/ops/db_backup.py``（本日从 runtime/ 挪家，
``__file__`` 层级已同步 ``parents[4]``）。本文件重写自阵亡席 X1c 的半成品
（``.superpowers/sdd/2026-10-02-fixwave/half-done/test_db_backup.py.HALF-WRITTEN``，
死于 ``class TestHonestyAndFail Loud:`` 断行语法错 + 旧 import 路径），抢救/重写逐腿
判定见 ``patches/DBT-DBBACKUP-TESTS-20261002.md``。

工单六腿（每腿正/反向判据成对，至少②⑤另做注毒自证）：

① ``_copy_name``/``_safe_stem`` 形状与消毒（畸形库名消毒、时间戳 UTC 14 位）
② ``backup_one`` 对 tmp 库真的产出副本+manifest（UTC 瞬时 + 带偏移墙钟双时刻，台账 #6★）
③ 撕裂防护语义：WAL 源库未 checkpoint 的行进副本、裸拷拿不全（判据：副本行数 ≥ 裸拷行数）
④ ``_reject_production_target``：目标在数据根/源码树内必须抛，仓库外 tmp 放行
⑤ ``apply_retention``：只删白名单点名件、目录里陌生文件不动、不递归
⑥ 接线 AST：runtime_admin 的 import 指向 domains.ops 新路径；旧路径生产面零命中

纪律：所有写落点一律 tmp_path 替身 config（``bot_runtime_data_dir``/``bot_db_backup_dir``
都指向 tmp，``conftest`` 的 L1 缝只守源码树）；对源库只读语义用
``file:...?mode=ro`` 断言；绝不触生产 Runtime。静态尺用 AST 逐函数域判，
不碰行号（台账 #50★）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.ops import db_backup

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_FILE = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "ops" / "admin" / "runtime_admin.py"
)
PROD_SOURCE = Path(db_backup.__file__).read_text(encoding="utf-8")
FIXED_NOW = datetime(2026, 10, 2, 1, 2, 3, tzinfo=timezone.utc)
#: 旧家 import 形态（防回潮）：只扫生产面（plugins/scripts/bot.py），
#: ``.superpowers``/``docs`` 是非代码档案（X1c 遗骸合法含旧 import），不在扫面内。
_OLD_IMPORT_MARKERS = ("runtime import db_backup", "runtime.db_backup")
#: 撕裂防护的静态尺禁集（裸拷/递归删形态）。``Path.replace`` 不在禁集——运行日志轮转
#: 用的是重命名而非内容拷贝；``shutil.copy2`` 只允许出现在 restore_stage（口径 3：
#: staging 落点合法，写回生产路径才被禁），故静态尺按**函数域**判，不按全模块判。
_RAW_COPY_ATTRS = {"copy", "copy2", "copyfile", "copyfileobj", "copytree", "rmtree", "move"}


# ---------------------------------------------------------------------------
# 夹具与替身 config（落点全部指向 tmp）
# ---------------------------------------------------------------------------


class _Runtime:
    """临时「数据根 / 备份落点」两件套（全在 tmp_path 里，绝不指生产 Runtime）。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "data"
        self.backups = root / "backups" / "sqlite"
        self.data.mkdir(parents=True, exist_ok=True)


class _Config:
    """最小 config 替身：只带备份腿会读的键（``load_policy``/``_data_root`` 口径）。"""

    def __init__(self, runtime: _Runtime, **overrides: Any) -> None:
        values: dict[str, Any] = {
            "bot_runtime_data_dir": str(runtime.data),
            "bot_db_backup_enabled": True,
            "bot_db_backup_dir": str(runtime.backups),
            "bot_db_backup_keep_last": 3,
            "bot_db_backup_size_ceiling_bytes": 64 * 1024 * 1024,
            "bot_db_backup_max_footprint_bytes": 64 * 1024 * 1024,
            "bot_db_backup_min_free_bytes": 0,
            "bot_db_backup_stale_after_hours": 24,
            "bot_timezone": "Asia/Shanghai",
            "bot_affinity_db_path": str(runtime.data / "user_affinity.sqlite3"),
            "bot_reply_policy_db_path": "",
            "bot_send_queue_db_path": str(runtime.data / "wuwa_send_queue.sqlite3"),
            "bot_memory_db_path": str(runtime.data / "wuwa_memory.sqlite3"),
        }
        values.update(overrides)
        for name, value in values.items():
            setattr(self, name, value)


@pytest.fixture()
def runtime(tmp_path: Path) -> _Runtime:
    return _Runtime(tmp_path / "runtime")


@pytest.fixture()
def config(runtime: _Runtime) -> _Config:
    return _Config(runtime)


def _db(path: Path, *, wal: bool = False, rows: int = 3, table: str = "t") -> None:
    """建一枚测试库（可 WAL）写 ``rows`` 行；WAL 不显式 checkpoint（撕裂腿自己控）。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, v TEXT)")
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executemany(
            f"INSERT INTO {table} (v) VALUES (?)",
            [(f"row{index}",) for index in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


def _ro(path: Path) -> sqlite3.Connection:
    """生产库唯一合法打开方式（口径 2）：``file:...?mode=ro``。"""
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _rows(db_file: Path, *, frozen: bool = False, table: str = "t") -> int:
    """只读数行。``frozen=True``（裸拷字节快照）加 ``immutable=1``：裸拷没有 -wal/-shm，
    主文件页头却是 WAL 形态，immutable 让 SQLite 只读主文件页——正好是「裸拷能看到什么」。"""
    uri = f"{db_file.as_uri()}?mode=ro" + ("&immutable=1" if frozen else "")
    conn = sqlite3.connect(uri, uri=True)
    try:
        return int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
    finally:
        conn.close()


def _manifests(root: Path) -> list[Path]:
    return sorted(root.glob(f"*{db_backup.MANIFEST_SUFFIX}"))


def _copies(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.is_file() and db_backup.COPY_NAME_RE.match(p.name)
    )


def _seed(config: _Config, *names: str, **kwargs: Any) -> None:
    for name in names:
        _db(Path(config.bot_runtime_data_dir) / name, **kwargs)


def _candidate(config: _Config, name: str) -> db_backup.DbCandidate:
    path = Path(config.bot_runtime_data_dir) / name
    return db_backup.DbCandidate(name=name, path=path, rel=name, size_bytes=path.stat().st_size)


def _sweep(config: _Config, **kwargs: Any) -> db_backup.BackupOutcome:
    return db_backup.backup_all(config, **kwargs)


def _module_fn(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _called_attrs(node: ast.AST) -> set[str]:
    """收集语法树里全部方法/属性调用名（按 AST 判，不碰行号，也不被 docstring 字样误伤）。"""
    return {
        n.func.attr for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


def _raw_copy_hits(fn: ast.FunctionDef) -> list[str]:
    return sorted(_called_attrs(fn) & _RAW_COPY_ATTRS)


def _old_path_hits(pairs: list[tuple[Path, str]]) -> list[str]:
    hits: list[str] = []
    for path, text in pairs:
        for marker in _OLD_IMPORT_MARKERS:
            if marker in text:
                hits.append(f"{path}: {marker}")
    return hits


def _production_py_files() -> list[Path]:
    files = [REPO_ROOT / "bot.py"]
    for folder in ("plugins", "scripts"):
        files.extend(
            p for p in (REPO_ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts
        )
    return sorted(files)


# ---------------------------------------------------------------------------
# 腿①：_copy_name / _safe_stem 形状与消毒
# ---------------------------------------------------------------------------


class TestLeg1CopyNamingAndSanitization:
    def test_safe_stem_strips_suffix_and_sanitizes(self) -> None:
        assert db_backup._safe_stem("user_affinity.sqlite3") == "user_affinity"
        assert db_backup._safe_stem("foo bar!.sqlite3") == "foo_bar_"
        # 空格/中文/符号全消毒成 "_"，且消毒后的词干必须还能拼出在册副本名（反向保证）
        poison = "库名:混 合*?.sqlite3"
        stem = db_backup._safe_stem(poison)
        assert set(stem) <= set("_-.") and stem
        assert stem == "_" * len("库名:混 合*?")
        composed = f"{stem}_20261002010203_abcd1234{db_backup.DB_SUFFIX}"
        assert db_backup.COPY_NAME_RE.match(composed) is not None, composed
        # 全消毒后为空 ⇒ 回落 "db"，绝不出空文件名
        assert db_backup._safe_stem(".sqlite3") == "db"

    def test_copy_name_shape_utc_stamp_and_rel_tag(self) -> None:
        candidate = db_backup.DbCandidate(
            name="user_affinity.sqlite3",
            path=Path("data/user_affinity.sqlite3"),
            rel="nested/user_affinity.sqlite3",
            size_bytes=10,
        )
        name = db_backup._copy_name(candidate, FIXED_NOW)
        match = db_backup.COPY_NAME_RE.match(name)
        assert match is not None, name
        assert match.group("stem") == "user_affinity"
        assert match.group("stamp") == "20261002010203"  # UTC 14 位，不是墙钟
        assert len(match.group("stamp")) == 14
        assert match.group("tag") == hashlib.sha256(
            candidate.rel.encode("utf-8")
        ).hexdigest()[:8]
        assert name.endswith(db_backup.DB_SUFFIX)

    def test_copy_name_regex_rejects_malformed(self) -> None:
        bad = [
            "no_stamp.sqlite3",
            "db_202610020102_abbbaaab.sqlite3",  # 12 位
            "db_2026100201020_abbbaaab.sqlite3",  # 13 位
            "db_20261002010203_ZZZZZZZZ.sqlite3",  # tag 非 hex
            "db_20261002010203_abbbaaab.txt",  # 后缀不对
        ]
        for name in bad:
            assert db_backup.COPY_NAME_RE.match(name) is None, name

    def test_non_utc_instant_is_normalized_before_stamping(self, config: _Config) -> None:
        """台账 #6★：时间戳只认 UTC——+08:00 墙钟 08:00 进来，落名的必须是 00:00Z。"""
        policy = db_backup.load_policy(config)
        wall = datetime(2026, 10, 2, 8, 0, tzinfo=timezone(timedelta(hours=8)))
        utc, local = db_backup._now_pair(policy, wall)
        assert utc.strftime("%Y%m%d%H%M%S") == "20261002000000"
        assert local.utcoffset() == timedelta(hours=8)
        candidate = db_backup.DbCandidate(
            name="x.sqlite3", path=Path("data/x.sqlite3"), rel="x.sqlite3", size_bytes=1
        )
        name = db_backup._copy_name(candidate, utc)
        assert "20261002000000" in name
        assert "20261002080000" not in name


# ---------------------------------------------------------------------------
# 腿②：backup_one 真的产出副本 + 成对 manifest（双时刻）
# ---------------------------------------------------------------------------


class TestLeg2BackupOneProductAndManifest:
    def test_backup_one_makes_copy_and_paired_manifest(self, config: _Config) -> None:
        _seed(config, "user_affinity.sqlite3")
        outcome = db_backup.backup_one(
            _candidate(config, "user_affinity.sqlite3"), config, now=FIXED_NOW
        )
        assert outcome["status"] == "ok", outcome
        root = db_backup.resolve_backup_root(config)
        copies = _copies(root)
        assert len(copies) == 1, "副本没落到备份落点"
        copy = copies[0]
        manifest_path = root / (copy.name + db_backup.MANIFEST_SUFFIX)
        assert manifest_path.is_file(), "旁车 manifest 没成对落盘"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["db"] == "user_affinity.sqlite3"
        assert data["copy"] == copy.name
        assert data["size_bytes"] == copy.stat().st_size > 0
        assert data["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
        assert data["table_count"] >= 1
        assert data["row_counts"].get("t") == 3
        assert data["row_count_scope"] == "full"
        assert data["integrity_check"] == "ok"
        assert data["copy_journal_mode_after_backup"] == "delete"
        assert data["copy_is_single_file"] is True
        # 双时刻（台账 #6★）：UTC 瞬时 + 带偏移墙钟，任何一侧都不许是 naive
        assert data["created_at_utc"] == "2026-10-02T01:02:03+00:00"
        local = datetime.fromisoformat(data["created_at_local"])
        assert local.tzinfo is not None and local.utcoffset() is not None
        assert local.utcoffset() == timedelta(hours=8)
        assert data["created_utc_offset_minutes"] == 480
        assert data["timezone_name"] == "Asia/Shanghai"

    def test_utc_policy_records_zero_offset(self, runtime: _Runtime) -> None:
        config = _Config(runtime, bot_timezone="UTC")
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        data = json.loads(
            _manifests(db_backup.resolve_backup_root(config))[0].read_text("utf-8")
        )
        assert data["created_at_local"] == data["created_at_utc"]
        assert data["created_utc_offset_minutes"] == 0

    def test_unknown_timezone_still_never_naive(self, runtime: _Runtime) -> None:
        """tz 名不认识 ⇒ 退系统偏移，绝不退 naive（Windows 缺 tzdata 是真形态）。"""
        config = _Config(runtime, bot_timezone="Nowhere/Nonexistent")
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        data = json.loads(
            _manifests(db_backup.resolve_backup_root(config))[0].read_text("utf-8")
        )
        local = datetime.fromisoformat(data["created_at_local"])
        assert local.tzinfo is not None and local.utcoffset() is not None

    def test_naive_now_is_rejected(self, config: _Config) -> None:
        """注毒自证（②腿·时刻面）：naive 时刻进腿必须当场抛，绝不写进 manifest。"""
        _seed(config, "user_affinity.sqlite3")
        with pytest.raises(db_backup.BackupError):
            _sweep(config, now=datetime(2026, 10, 2, 1, 2, 3))  # noqa: DTZ001 - 有意 naive

    def test_oversize_source_is_skipped_without_product(self, runtime: _Runtime) -> None:
        """反向：超尺寸上界的源不产出任何副本（skip 是如实登记，不是失败）。"""
        config = _Config(runtime, bot_db_backup_size_ceiling_bytes=1024)
        _seed(config, "user_affinity.sqlite3")
        outcome = db_backup.backup_one(
            _candidate(config, "user_affinity.sqlite3"), config, now=FIXED_NOW
        )
        assert outcome["status"] == "skipped"
        assert outcome["reason"] == "over_size_ceiling"
        assert not _copies(db_backup.resolve_backup_root(config))

    def test_verify_backup_catches_bit_flip(self, config: _Config) -> None:
        """注毒自证（②腿·manifest 面）：改副本一枚字节 ⇒ 对账必须红（尺不是空转）。"""
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        root = db_backup.resolve_backup_root(config)
        copy = _copies(root)[0]
        payload = bytearray(copy.read_bytes())
        payload[100] ^= 0xFF
        copy.write_bytes(bytes(payload))
        verdict = db_backup.verify_backup(root / (copy.name + db_backup.MANIFEST_SUFFIX))
        assert verdict["ok"] is False
        assert any("sha256" in problem for problem in verdict["problems"]), verdict


# ---------------------------------------------------------------------------
# 腿③：撕裂防护——WAL 未 checkpoint 的行进副本，裸拷拿不全
# ---------------------------------------------------------------------------


class TestLeg3WalTearProtection:
    def test_uncheckpointed_wal_row_reaches_copy_but_not_naive_copy(
        self, tmp_path: Path
    ) -> None:
        """生产 docstring 口径 1 的可复现实证：判据＝副本行数 ≥ 裸拷行数，且裸拷缺 WAL 行。"""
        data = tmp_path / "runtime" / "data"
        data.mkdir(parents=True)
        source = data / "user_affinity.sqlite3"
        _db(source, rows=2)
        holder = sqlite3.connect(str(source))
        try:
            holder.execute("PRAGMA journal_mode=WAL")
            holder.execute("INSERT INTO t (v) VALUES ('row-in-wal')")
            holder.commit()  # 这一行只活在 -wal 里（连接不关就不 checkpoint）
            naive = data / "naive_copy.sqlite3"
            naive.write_bytes(source.read_bytes())  # 字节级裸拷主文件
            naive_rows = _rows(naive, frozen=True)
            naive.unlink()

            config = _Config(_Runtime(tmp_path / "runtime"))
            outcome = db_backup.backup_one(
                db_backup.DbCandidate(
                    name=source.name, path=source, rel=source.name,
                    size_bytes=source.stat().st_size,
                ),
                config,
                now=FIXED_NOW,
            )
            assert outcome["status"] == "ok", outcome
            root = db_backup.resolve_backup_root(config)
            copy = _copies(root)[0]
            copy_rows = _rows(copy)
            assert copy_rows >= naive_rows, "在线备份不得比裸拷更少（撕裂防护语义）"
            assert copy_rows == 3, f"WAL 里未 checkpoint 的行没进副本：{copy_rows}"
            assert naive_rows == 2, f"裸拷应当拿不全（拿到 {naive_rows}）"
        finally:
            holder.close()

    def test_backup_one_uses_connection_backup_api_only(self) -> None:
        """静态尺（函数域）：backup_one 必须走 Connection.backup，禁裸拷第二通路。"""
        tree = ast.parse(PROD_SOURCE)
        fn = _module_fn(tree, "backup_one")
        assert "backup" in _called_attrs(fn), "备份腿必须用 Connection.backup()"
        assert _raw_copy_hits(fn) == [], _raw_copy_hits(fn)
        assert "read_bytes" not in _called_attrs(fn), "backup_one 里不许出现字节级读拷形态"

    def test_retention_and_restore_never_bulk_delete(self) -> None:
        """静态尺（AST 调用面）：apply_retention 无批量删/搬形态；全模块零 rmtree。"""
        tree = ast.parse(PROD_SOURCE)
        assert _raw_copy_hits(_module_fn(tree, "apply_retention")) == []
        assert "rmtree" not in _called_attrs(tree), "全模块禁 rmtree 调用"

    def test_static_ruler_flags_poisoned_source(self) -> None:
        """注毒自证（③腿静态尺）：喂含 shutil.copy2 的假 backup_one 必须红（尺不空转）。"""
        poisoned = ast.parse("def backup_one():\n    shutil.copy2('a', 'b')\n")
        assert _raw_copy_hits(_module_fn(poisoned, "backup_one")) == ["copy2"]


# ---------------------------------------------------------------------------
# 腿④：_reject_production_target——数据根/源码树内必拒，仓库外放行
# ---------------------------------------------------------------------------


class TestLeg4RejectProductionTarget:
    def test_targets_inside_data_root_or_repo_raise(self, config: _Config) -> None:
        data_root = Path(config.bot_runtime_data_dir)
        blocked = [
            data_root,
            data_root / "user_affinity.sqlite3",
            data_root / "nested" / "x.sqlite3",
            REPO_ROOT,
            REPO_ROOT / "data" / "x.sqlite3",
            REPO_ROOT / "restore_attempt",
        ]
        for target in blocked:
            with pytest.raises(db_backup.BackupError):
                db_backup._reject_production_target(target, config)

    def test_repo_outside_tmp_target_passes(self, config: _Config, tmp_path: Path) -> None:
        """反向不误伤：仓库外 tmp 放行（不抛即过）。"""
        db_backup._reject_production_target(tmp_path / "staging", config)

    def test_backup_root_inside_repo_is_refused(self, tmp_path: Path) -> None:
        """抢救腿（X1c）：备份落点本身配进仓库内 ⇒ 当场抛，且不落任何产物。"""
        runtime = _Runtime(tmp_path / "runtime")
        with pytest.raises(db_backup.BackupError):
            db_backup.resolve_backup_root(_Config(runtime, bot_db_backup_dir=str(REPO_ROOT)))
        with pytest.raises(db_backup.BackupError):
            db_backup.resolve_backup_root(
                _Config(runtime, bot_db_backup_dir=str(REPO_ROOT / "runtime_backups"))
            )
        assert not (REPO_ROOT / "runtime_backups").exists()

    def test_restore_stage_refuses_production_and_repo_targets(
        self, config: _Config
    ) -> None:
        """公开面同尺：restore_stage 走同一枚人质门，且拒绝发生在任何写盘之前。"""
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        manifest = _manifests(db_backup.resolve_backup_root(config))[0]
        with pytest.raises(db_backup.BackupError):
            db_backup.restore_stage(manifest, config, Path(config.bot_runtime_data_dir))
        with pytest.raises(db_backup.BackupError):
            db_backup.restore_stage(manifest, config, REPO_ROOT / "restore_attempt")
        assert not (REPO_ROOT / "restore_attempt").exists()

    def test_restore_stage_positive_and_refuses_overwrite(
        self, config: _Config, tmp_path: Path
    ) -> None:
        """正向：仓库外 staging 可落；同名件已在 ⇒ 拒覆盖（口径 3：覆盖绝不自动）。"""
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        manifest = _manifests(db_backup.resolve_backup_root(config))[0]
        staging = tmp_path / "staging"
        first = db_backup.restore_stage(manifest, config, staging)
        assert Path(first["staged"]).is_file()
        with pytest.raises(db_backup.BackupError):
            db_backup.restore_stage(manifest, config, staging)


# ---------------------------------------------------------------------------
# 腿⑤：apply_retention——只删白名单点名件、陌生文件不动、不递归
# ---------------------------------------------------------------------------


class TestLeg5RetentionNamedOnly:
    def test_plan_lists_then_named_apply_deletes_exactly_the_victims(
        self, config: _Config
    ) -> None:
        config.bot_db_backup_keep_last = 64  # sweep 期不自动剪，victim 由本腿亲手点名
        _seed(config, "user_affinity.sqlite3")
        root = db_backup.resolve_backup_root(config)
        root.mkdir(parents=True, exist_ok=True)
        decoy = root / "keepme.txt"
        subdir = root / "sub"
        subdir.mkdir(parents=True, exist_ok=True)
        nested = subdir / "nested.sqlite3"
        decoy.write_text("decoy", encoding="utf-8")
        nested.write_text("x", encoding="utf-8")
        for hour in range(3):
            _sweep(config, now=FIXED_NOW + timedelta(hours=hour))
        assert len(_copies(root)) == 3
        config.bot_db_backup_keep_last = 1
        plan = db_backup.plan_retention(config)
        victims = [item["name"] for item in plan["candidates"]]
        assert len(victims) == 2, plan
        outcome = db_backup.apply_retention(config, victims)
        assert outcome["deleted"] == 2 and outcome["refused"] == 0, outcome
        assert set(outcome["deleted_names"]) == set(victims)
        remaining = {p.name for p in _copies(root)}
        assert len(remaining) == 1 and remaining.isdisjoint(victims)
        for name in remaining:  # 留下的必须副本↔旁车成对
            assert (root / (name + db_backup.MANIFEST_SUFFIX)).is_file()
        for name in victims:  # 删的是副本+旁车成对走
            assert not (root / name).exists()
            assert not (root / (name + db_backup.MANIFEST_SUFFIX)).exists()
        assert decoy.is_file() and subdir.is_dir() and nested.is_file(), "陌生文件被误动"

    def test_refuses_unlisted_traversal_and_directory_names(self, config: _Config) -> None:
        """注毒自证（⑤腿）：不在清单里的名字（含在册副本名/越界/目录/陌生件）全拒。"""
        config.bot_db_backup_keep_last = 64
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        root = db_backup.resolve_backup_root(config)
        decoy = root / "keepme.txt"
        subdir = root / "sub"
        subdir.mkdir(parents=True, exist_ok=True)
        nested = subdir / "nested.sqlite3"
        decoy.write_text("decoy", encoding="utf-8")
        nested.write_text("x", encoding="utf-8")
        copy_name = _copies(root)[0].name
        poison = [
            copy_name,  # 在册形态但不在本轮清单（keep_last 没超）
            "../keepme.txt",  # 越界形态
            str(decoy),  # 绝对路径
            "sub",  # 目录
            "keepme.txt",  # 落点里的陌生文件
            "sub/nested.sqlite3",  # 子目录内的东西（不递归）
        ]
        outcome = db_backup.apply_retention(config, poison)
        assert outcome["deleted"] == 0, outcome
        assert outcome["refused"] == len(poison)
        assert set(outcome["refused_names"]) == set(poison)
        assert decoy.is_file() and subdir.is_dir() and nested.is_file()
        assert _copies(root), "在册副本被误删"

    def test_empty_approval_deletes_nothing(self, config: _Config) -> None:
        _seed(config, "user_affinity.sqlite3")
        _sweep(config, now=FIXED_NOW)
        root = db_backup.resolve_backup_root(config)
        before = sorted(p.name for p in root.iterdir())
        outcome = db_backup.apply_retention(config, [])
        assert outcome["deleted"] == 0
        assert sorted(p.name for p in root.iterdir()) == before

    def test_module_has_no_recursive_or_bulk_delete_shape(self) -> None:
        """静态尺（AST 调用面）：全模块零 rmtree/move 调用；unlink 只点名；删前名字门在场。"""
        tree = ast.parse(PROD_SOURCE)
        called = _called_attrs(tree)
        assert "rmtree" not in called and "move" not in called, sorted(
            called & {"rmtree", "move"}
        )
        unlinks = [
            ast.unparse(node.func.value) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "unlink"
        ]
        assert unlinks, "点名删的腿不见了"
        for text in unlinks:
            assert "*" not in text and "rmdir" not in text, f"疑似批量/递归删：{text}"
        assert "COPY_NAME_RE.match(name)" in PROD_SOURCE, "删前名字门不在场"


# ---------------------------------------------------------------------------
# 腿⑥：接线 AST——import 指向 domains.ops 新路径；旧路径生产面零命中
# ---------------------------------------------------------------------------


class TestLeg6WiringAst:
    def test_admin_import_points_to_domains_ops(self) -> None:
        """runtime_admin 的 db_backup import 必须住在 _handle_backup_command 里且指向新家。"""
        tree = ast.parse(ADMIN_FILE.read_text(encoding="utf-8"))
        handler = _module_fn(tree, "_handle_backup_command")
        inner = [
            node for node in ast.walk(handler)
            if isinstance(node, ast.ImportFrom) and node.module
            and "db_backup" in {alias.name for alias in node.names}
        ]
        assert inner, "_handle_backup_command 里没有 db_backup import"
        assert all(
            node.module == "plugins.bot_unified_runtime.domains.ops" for node in inner
        ), [str(node.module) for node in inner]

    def test_old_runtime_path_has_zero_hits_in_production_tree(self) -> None:
        """防回潮：旧家 import 形态在 plugins/scripts/bot.py 全生产面零命中。"""
        pairs = [(path, path.read_text(encoding="utf-8")) for path in _production_py_files()]
        assert _old_path_hits(pairs) == []

    def test_old_path_scanner_is_not_vacuous(self) -> None:
        """注毒自证（⑥腿）：喂一段旧家 import 必须被抓（扫尺不空转）。"""
        poisoned = "from plugins.bot_unified_runtime.runtime import db_backup\n"
        hits = _old_path_hits([(Path("fake.py"), poisoned)])
        assert hits, "旧路径扫尺漏报"


# ---------------------------------------------------------------------------
# 腿④附：源库只读机制自证（docstring 口径 2 的兜底）
# ---------------------------------------------------------------------------


class TestReadOnlyOnSources:
    def test_ro_connection_rejects_writes(self, config: _Config) -> None:
        _seed(config, "user_affinity.sqlite3")
        path = Path(config.bot_runtime_data_dir) / "user_affinity.sqlite3"
        conn = _ro(path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO t (v) VALUES ('nope')")
        finally:
            conn.close()
        assert _rows(path) == 3

    def test_sweep_leaves_source_files_byte_identical(self, config: _Config) -> None:
        """正向不误伤：整轮跑完，源库字节、journal_mode、行数一字未动（含 WAL 源）。"""
        _seed(config, "user_affinity.sqlite3", wal=True)
        _seed(config, "wuwa_memory.sqlite3")
        data_root = Path(config.bot_runtime_data_dir)

        def snapshot() -> dict[str, bytes]:
            return {p.name: p.read_bytes() for p in sorted(data_root.glob("*.sqlite3*"))}

        def journal_modes() -> dict[str, str]:
            modes: dict[str, str] = {}
            for name in ("user_affinity.sqlite3", "wuwa_memory.sqlite3"):
                conn = _ro(data_root / name)
                try:
                    modes[name] = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
                finally:
                    conn.close()
            return modes

        rows_before = _rows(data_root / "user_affinity.sqlite3")
        bytes_before = snapshot()
        modes_before = journal_modes()
        _sweep(config, now=FIXED_NOW)
        assert snapshot() == bytes_before, "源文件字节被动过"
        assert journal_modes() == modes_before, "journal_mode 被改＝越界（口径 2）"
        assert _rows(data_root / "user_affinity.sqlite3") == rows_before
