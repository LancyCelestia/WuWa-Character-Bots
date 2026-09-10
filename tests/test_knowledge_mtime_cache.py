"""知识文件 (mtime,size) 签名缓存回归：签名未变的文件不重复读盘分块（管线检视 #9 / handoff C-5）。"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from plugins.bot_unified_runtime.character import vector_knowledge as vk
from plugins.bot_unified_runtime.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)


class _FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        digest = hashlib.sha1("".join(texts).encode("utf-8")).digest()
        return [[byte / 255.0 for byte in digest[:8]]] * len(texts)


def _store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / "knowledge_embeddings.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake-embedder",
        auto_reset=True,
    )


def test_sync_chunks_skips_reread_when_signature_unchanged(tmp_path, monkeypatch) -> None:
    knowledge_file = tmp_path / "notes.md"
    knowledge_file.write_text("守岸人知识条目：泰提斯系统。\n" * 20, encoding="utf-8")
    store = _store(tmp_path)

    calls = {"load": 0}
    real_load = vk.load_character_document

    def counting_load(path):
        calls["load"] += 1
        return real_load(path)

    monkeypatch.setattr(vk, "load_character_document", counting_load)

    store.sync_chunks([knowledge_file])
    first_count = calls["load"]
    assert first_count == 1

    # 同一文件反复同步（retrieve 每条消息都会触发）：签名未变不得再读盘。
    for _ in range(3):
        store.sync_chunks([knowledge_file])
    assert calls["load"] == first_count


def test_sync_chunks_rereads_after_file_change(tmp_path, monkeypatch) -> None:
    knowledge_file = tmp_path / "notes.md"
    knowledge_file.write_text("守岸人知识条目：泰提斯系统。\n" * 20, encoding="utf-8")
    store = _store(tmp_path)

    calls = {"load": 0}
    real_load = vk.load_character_document

    def counting_load(path):
        calls["load"] += 1
        return real_load(path)

    monkeypatch.setattr(vk, "load_character_document", counting_load)
    store.sync_chunks([knowledge_file])
    assert calls["load"] == 1

    # 内容变化（mtime/size 变）后必须重读并反映新内容。
    time.sleep(0.01)
    knowledge_file.write_text("守岸人新知识：乐土的回忆。\n" * 20, encoding="utf-8")
    store.sync_chunks([knowledge_file])
    assert calls["load"] == 2

    with store._connect() as connection:
        contents = {
            str(row["content"])
            for row in connection.execute("SELECT content FROM knowledge_chunks")
        }
    assert any("乐土的回忆" in text for text in contents)


def test_sync_chunks_prunes_signature_for_removed_files(tmp_path) -> None:
    keep = tmp_path / "keep.md"
    drop = tmp_path / "drop.md"
    keep.write_text("保留的知识。\n" * 10, encoding="utf-8")
    drop.write_text("将被移除的知识。\n" * 10, encoding="utf-8")
    store = _store(tmp_path)

    store.sync_chunks([keep, drop])
    assert keep in store._synced_signatures
    assert drop in store._synced_signatures

    store.sync_chunks([keep])
    assert keep in store._synced_signatures
    assert drop not in store._synced_signatures
