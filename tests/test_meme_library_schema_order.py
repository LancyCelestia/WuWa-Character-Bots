"""表情库建表序锁（席位 S-MEME-SCHEMA，2026-09-29）。

钉死一枚会炸空库的回归：``domains/meme/sources/meme_library.py`` 把依赖
``review_state`` 列的索引 ``idx_memes_review`` 写进了 ``_SCHEMA``，而该列要到
``_MIGRATIONS`` 的 ``ALTER TABLE`` 才补齐 ⇒ **任何全新空库在建表阶段当场抛**
``sqlite3.OperationalError: no such column: memes.review_state``。

判据（家规＝ALTER-if-missing 先行、索引后建，先例 character/affinity.py、
character/addressing.py）：
1. 空库走完整建表入口**不抛**；
2. ``review_state`` 列在册；
3. ``idx_memes_review`` 索引在册；
4. 幂等：同一库文件再开一次，索引仍只有一枚、不重复；
5. **注毒自证**：把索引还原进迁移之前的建表脚本（``_SCHEMA``）并清空迁移后
   索引，同一条入口必须红——证明这把尺咬的是建表序，不是空跑。

全部离线：``tmp_path`` 裸建空库，绝不落 ChatBot_Runtime、绝不写源码树 ``data/``；
store 用 ``no_repeat=False`` 关闭发送史，不碰任何进程级 store 工厂。
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "meme"
    / "sources"
    / "meme_library.py"
)


def _load_module():
    """按文件路径加载 store 模块（与 scripts/import_meme_packs._load_store 同法），
    避开包 ``__init__`` 的 NoneBot 依赖。"""
    spec = importlib.util.spec_from_file_location("_meme_library_schema_lock", str(_SOURCE))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = _load_module()


def _columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return {str(row["name"]) for row in conn.execute("PRAGMA table_info(memes)")}
    finally:
        conn.close()


def _index_rows(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [str(row[1]) for row in conn.execute("PRAGMA index_list(memes)")]
    finally:
        conn.close()


def _build(db_path: Path) -> object:
    """走模块的真身建表入口（__init__ 的 executescript + 迁移 + 迁移后索引）。"""
    return module.MemeLibraryStore(str(db_path), prefer=[], no_repeat=False)


def test_fresh_empty_db_build_does_not_raise(tmp_path: Path) -> None:
    db_path = tmp_path / "brand_new_meme_library.sqlite3"
    assert not db_path.exists()
    _build(db_path)  # 修复前：这一行直接抛 OperationalError


def test_review_state_column_is_present_after_build(tmp_path: Path) -> None:
    db_path = tmp_path / "brand_new_meme_library.sqlite3"
    _build(db_path)
    columns = _columns(db_path)
    assert "review_state" in columns, "review_state 列缺席＝迁移没跑齐"
    # 其余迁移列一并核（它们与 review_state 同族，防有人再挪建表序挪出新坑）。
    for expected in ("sha256", "persona_owned", "native_emoji_id", "native_package_id"):
        assert expected in columns, f"{expected} 列缺席"


def test_review_index_is_present_after_build(tmp_path: Path) -> None:
    db_path = tmp_path / "brand_new_meme_library.sqlite3"
    _build(db_path)
    indexes = _index_rows(db_path)
    assert "idx_memes_review" in indexes, "依赖新列的索引未在列齐后补上"
    assert "idx_memes_weight" in indexes and "idx_memes_added_at" in indexes


def test_build_entry_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "brand_new_meme_library.sqlite3"
    _build(db_path)
    _build(db_path)  # 同文件再开一次：ALTER 缺席跳过、索引 IF NOT EXISTS 不重复
    indexes = _index_rows(db_path)
    assert indexes.count("idx_memes_review") == 1, "重复建库长出第二枚同名索引＝非幂等"


def test_poison_original_order_is_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒自证：把 review 索引还原到迁移之前的建表脚本里，入口必须炸。

    这不是在测「改坏的代码会坏」，而是证明上面几条断言真咬建表序——若尺是空跑，
    还原成旧顺序也不会红，那四条绿就毫无价值。
    """
    poisoned_schema = (
        module._SCHEMA.rstrip()
        + "\nCREATE INDEX IF NOT EXISTS idx_memes_review ON memes(review_state);\n"
    )
    monkeypatch.setattr(module, "_SCHEMA", poisoned_schema)
    monkeypatch.setattr(module, "_POST_MIGRATION_INDEXES", ())
    db_path = tmp_path / "poisoned_meme_library.sqlite3"
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        _build(db_path)
