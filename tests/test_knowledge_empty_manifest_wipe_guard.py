"""空清单不得当作「语料为空」：sync_chunks / retrieve 删除侧守卫回归（全离线夹具）。

夹具只在 tmp_path 下造假库假文件，绝不打开、绝不写生产运行数据。

事故根因：一次性脚本调 store.retrieve(query, None) -> retrieve 内
self.sync_chunks(list(files) if files else []) -> manifest_stems 空集 ->
ledger - manifest_stems = 台账内全部源 -> 逐源 DELETE FROM knowledge_chunks，
整库清零且不报错。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

_GUARD_TOKEN = "knowledge_sync_wipe_guard"


class _FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        digest = hashlib.sha1("".join(texts).encode("utf-8")).digest()
        return [[byte / 255.0 for byte in digest[:8]]] * len(texts)


def _store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / "fixture-kb.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=200,
        top_k=4,
        signature="test|wipe-guard",
        auto_reset=True,
    )


def _make_files(base: Path, count: int, *, subdir: str = "") -> list[Path]:
    root = base / subdir if subdir else base
    root.mkdir(parents=True, exist_ok=True)
    stem = subdir or "kb"
    paths: list[Path] = []
    for index in range(count):
        path = root / f"{stem}-{index:02d}.md"
        path.write_text(
            f"守岸人知识条目 {stem} {index}：泰缇斯系统第二实例。\n" * 30,
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _rows(store: SqliteVectorKnowledgeStore) -> int:
    with store._connect() as connection:  # noqa: SLF001
        return int(
            connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        )


def _sources(store: SqliteVectorKnowledgeStore) -> set[str]:
    with store._connect() as connection:  # noqa: SLF001
        return {
            str(row["source_id"])
            for row in connection.execute(
                "SELECT DISTINCT source_id FROM knowledge_chunks"
            )
        }


def _ledger(store: SqliteVectorKnowledgeStore) -> set[str]:
    with store._connect() as connection:  # noqa: SLF001
        prefix = vk._SOURCE_SIG_KEY_PREFIX  # noqa: SLF001
        return {
            str(row["key"])[len(prefix) :]
            for row in connection.execute(
                "SELECT key FROM knowledge_meta WHERE key LIKE ?", (prefix + "%",)
            )
        }


def _install_spy(store: SqliteVectorKnowledgeStore) -> list[list[Path]]:
    """夹具内记录 sync_chunks 的入参，用于断言读路径不带同步动作。"""
    calls: list[list[Path]] = []
    original_sync = store.sync_chunks

    def spy(paths: list[Path]) -> None:
        calls.append(list(paths))
        original_sync(list(paths))

    store.sync_chunks = spy  # type: ignore[method-assign]
    return calls


def test_retrieve_without_file_list_skips_sync(tmp_path: Path) -> None:
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)
    kept = _rows(store)
    calls = _install_spy(store)

    store.retrieve("检索词", None)
    store.retrieve("检索词", [])

    assert calls == [], "files 为 None/空时 retrieve 不应进入同步入口"
    assert _rows(store) == kept


def test_retrieve_with_file_list_still_syncs(tmp_path: Path) -> None:
    """防过修：给出真实清单时 retrieve 的增量同步语义保持原样。"""
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    calls = _install_spy(store)

    store.retrieve("检索词", files)

    assert calls == [files]


def test_search_scored_without_file_list_skips_sync(tmp_path: Path) -> None:
    """同形态入口的第二处（search_scored）也应跳过空清单同步。"""
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)
    kept = _rows(store)
    calls = _install_spy(store)

    store.search_scored("检索词", None)

    assert calls == []
    assert _rows(store) == kept


# ------------------------------------------------- 1 空清单守卫（本席主用例）
def test_empty_manifest_sync_keeps_all_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """夹具库 5 源在手，空清单同步应保持零删除并给出结构化告警。

    未加守卫时的同一夹具：manifest_stems 为空集 -> 台账 5 源全部落入 stale
    集合 -> 逐源 DELETE -> _rows 归 0（这就是主会话那场事故的夹具复现）。
    """
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)

    kept = _rows(store)
    assert kept > 0, "夹具必须真的写进行，否则本用例证明不了任何东西"
    assert _ledger(store) == {path.stem for path in files}

    with caplog.at_level(logging.WARNING):
        store.sync_chunks([])

    assert _rows(store) == kept
    assert _sources(store) == {path.stem for path in files}
    assert _ledger(store) == {path.stem for path in files}
    assert _GUARD_TOKEN in caplog.text, "拒绝删除要留下可观测的结构化告警"
    guard = store.last_sync_guard
    assert guard is not None and guard["reason"] == "empty_manifest"
    # planned_sources=5：告警里摊开「本来会摘掉几个源」，不是一句笼统拒绝。
    assert guard["planned_sources"] == 5 and guard["ledger_sources"] == 5


def test_all_paths_missing_keeps_all_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """清单路径全部指向不存在的文件（配置漂移形态）：同样不当作语料为空。"""
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)
    kept = _rows(store)

    ghost = [tmp_path / "gone" / f"kb-{index:02d}.md" for index in range(5)]
    with caplog.at_level(logging.WARNING):
        store.sync_chunks(ghost)

    assert _rows(store) == kept
    assert _GUARD_TOKEN in caplog.text
    assert store.last_sync_guard["reason"] == "all_paths_missing"


# ------------------------------------------------- 3 正常同步语义保持不变
def test_normal_pruning_semantics_preserved(tmp_path: Path) -> None:
    """传真实清单时的增量同步与按源精确删除逐字段照旧（现网靠它同步语料）。"""
    files = _make_files(tmp_path, 5)
    extra = _make_files(tmp_path, 1, subdir="extra")
    store = _store(tmp_path)
    store.sync_chunks(files + extra)
    assert _sources(store) == {path.stem for path in files} | {extra[0].stem}
    with_extra = _rows(store)

    # 单源移出清单：台账有记录 -> 只摘它自己，其余保留。
    store.sync_chunks(files)
    assert extra[0].stem not in _sources(store)
    assert {path.stem for path in files} <= _sources(store)
    assert _ledger(store) == {path.stem for path in files}
    assert _rows(store) < with_extra
    assert store.last_sync_guard is None

    # 清单外其它写入方的块不得被本次清单带走（既有精确删除语义）。
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "INSERT INTO knowledge_chunks (chunk_id, source_id, title, content,"
            " content_hash) VALUES ('new1', 'outsider', 'outsider', 'new', 'h')"
        )
    store.sync_chunks(files)
    assert "outsider" in _sources(store)

    # 单个文件真的从盘上消失（路径仍在清单里）：该源清理照常生效。
    gone = _make_files(tmp_path, 1, subdir="solo")[0]
    store.sync_chunks(files + [gone])
    assert gone.stem in _sources(store)
    gone.unlink()
    store.sync_chunks(files + [gone])
    assert gone.stem not in _sources(store)
    assert store.last_sync_guard is None


# ------------------------------------------------- 4 绝对量闸
def test_majority_removal_refused_by_gate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """单轮要摘掉超过台账一半的源：拒删 + 告警，但新增照常落库。"""
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)
    kept = _rows(store)

    with caplog.at_level(logging.WARNING):
        store.sync_chunks(files[:1])  # 台账 5 源里一次要摘 4 个

    assert _sources(store) == {path.stem for path in files}
    assert _rows(store) == kept
    assert _GUARD_TOKEN in caplog.text
    guard = store.last_sync_guard
    assert guard["reason"] == "mass_delete_gate"
    assert guard["planned_sources"] == 4 and guard["ledger_sources"] == 5

    fresh = _make_files(tmp_path, 1, subdir="fresh")
    store.sync_chunks(fresh)
    assert fresh[0].stem in _sources(store), "守卫只该冻结删除侧"


def test_minority_removal_still_prunes(tmp_path: Path) -> None:
    """闸不得把日常单源摘除一起焊死：少数派删除照常生效。"""
    files = _make_files(tmp_path, 5)
    store = _store(tmp_path)
    store.sync_chunks(files)
    assert store.last_sync_guard is None

    store.sync_chunks(files[:4])
    assert files[4].stem not in _sources(store)
    assert store.last_sync_guard is None
