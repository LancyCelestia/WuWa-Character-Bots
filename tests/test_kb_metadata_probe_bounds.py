"""元数据闸探针的三条边界（2026-09-20 判据形态修复席，续 test_kb_metadata_probe_window）。

主件 `test_kb_metadata_probe_window.py` 钉的是「首行否决 → 窗口计数救回」与
「全无字段 → 诚实跳过」。本件钉三道容易长歪的边界：

1. **采样总体 = 被闸管的总体**：`refresh_kb_metadata` 按 ``bot_kb_wiki_topics``
   过滤，探针也必须只在授权域里取样——否则闸拿别的域的字段分布给本域背书，
   还是「不具代表性的样本替全体作保」那个形态，只是换了个头；
2. **有界性不退化**：授权域的行排在扫描上限之后时，探针停在预算内、如实报
   probed=0（方向是保守跳过，绝不是拿零样本硬刷全库），且绝不为凑样本去
   读 GB 级全表——每夜白付一遍全扫正是旧 docstring 拒绝的事；
3. **依据真的外流**：probed/with_time 进了 public_message 与落库摘要，读数
   的人不查代码也能看到「这一轮的判断建立在几行样本上」。

全离线：语料与台账都在 tmp_path，零网络，不碰 ChatBot_Runtime。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    SqliteVectorKnowledgeStore,
    probe_corpus_time_fields,
)

_TOPIC = "梗知识"
_OTHER_TOPIC = "别的域"
_WINDOW = kb_wiki._METADATA_PROBE_WINDOW_LINES
_SCAN_CAP = kb_wiki._METADATA_PROBE_MAX_SCAN_LINES


class _FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]


def _row(doc_id: str, index: int, *, enriched: bool, topic: str = _TOPIC) -> dict:
    text = f"探针边界正文 {index}。" * 8
    row = {
        "id": doc_id,
        "topic": topic,
        "source": "moegirl",
        "title": doc_id.rsplit("/", 1)[-1],
        "path": f"{doc_id}.md",
        "url": "",
        "text": text,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if enriched:
        row["updated_at"] = "2026-09-19T00:00:00Z"
        row["crawled_at"] = "2026-09-20T08:00:00Z"
    return row


def _write_kb(
    tmp_path: Path, rows: list[dict], *, updates: list[dict] | None = None
) -> Path:
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    with (kb_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (kb_dir / "updates.jsonl").open("w", encoding="utf-8") as handle:
        for row in updates or []:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (kb_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "generated_at": "2026-09-20T00:00:00Z",
                "documents": len(rows),
                "entries": {str(r["id"]): str(r["hash"]) for r in rows},
                "added": [],
                "changed": [],
                "removed": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return kb_dir


def _config(tmp_path: Path, topics: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        bot_kb_wiki_root=str(tmp_path),
        bot_kb_wiki_topics=topics,
        bot_kb_wiki_chunk_chars=800,
        bot_kb_wiki_embed_batch=128,
    )


def _store(tmp_path: Path, name: str) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / f"{name}.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake-embedder",
        auto_reset=True,
    )


def _kb_dir(tmp_path: Path) -> Path:
    return tmp_path / "crawl_output" / "knowledge_base"


def test_probe_samples_only_authorized_topics(tmp_path: Path) -> None:
    """闸采的样必须来自被闸管的总体：域外带字段不得替授权域背书。"""
    rows = [_row(f"{_OTHER_TOPIC}/moegirl/O{i}", i, enriched=True) for i in range(20)]
    rows += [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=False) for i in range(20)]
    _write_kb(tmp_path, rows)
    # 不分域看：域外的 20 行把窗口撑成"有字段"；授权域其实一行都没带。
    assert probe_corpus_time_fields(_kb_dir(tmp_path)) == {
        "probed": 40,
        "with_time": 20,
        "has_fields": True,
    }
    scoped = probe_corpus_time_fields(_kb_dir(tmp_path), topics=[_TOPIC])
    assert scoped == {"probed": 20, "with_time": 0, "has_fields": False}
    # 反向：授权域带字段、域外不带 → 授权域必须放行刷新。
    flipped = [
        _row(f"{_OTHER_TOPIC}/moegirl/O{i}", i, enriched=False) for i in range(20)
    ] + [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=True) for i in range(20)]
    _write_kb(tmp_path, flipped)
    assert probe_corpus_time_fields(_kb_dir(tmp_path), topics=[_TOPIC]) == {
        "probed": 20,
        "with_time": 20,
        "has_fields": True,
    }


def test_run_kb_sync_task_scopes_probe_to_configured_topics(
    tmp_path: Path,
) -> None:
    """端到端：授权域无字段时即便语料别处有字段也诚实跳过（不硬刷 NULL）。"""
    rows = [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=False) for i in range(10)]
    rows += [_row(f"{_OTHER_TOPIC}/moegirl/O{i}", i, enriched=True) for i in range(10)]
    _write_kb(tmp_path, rows, updates=rows[:10])
    store = _store(tmp_path, "scoped")
    first = kb_wiki.run_kb_sync_task(
        _config(tmp_path, topics=_TOPIC), store=store, embed=False
    )
    assert first["metadata_status"] == "skipped_corpus_without_time_fields"
    # 台账里只有授权域那 10 篇，且没被杂散 NULL 污染。
    assert store.documents_missing_metadata() == 10
    summary = kb_wiki.read_kb_sync_summary(store)
    assert summary["metadata_probed"] == 10
    assert summary["metadata_with_time"] == 0


def test_probe_stops_at_scan_cap_instead_of_full_scan(tmp_path: Path) -> None:
    """目标域的行全在扫描上限之后：停在预算内、如实报零样本，不退化成全表扫。"""
    rows = [_row(f"{_OTHER_TOPIC}/moegirl/O{i}", i, enriched=True) for i in range(_SCAN_CAP + 50)]
    rows += [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=True) for i in range(5)]
    _write_kb(tmp_path, rows)
    probe = probe_corpus_time_fields(_kb_dir(tmp_path), topics=[_TOPIC])
    # 凑不满窗口也不去无限扫：本窗一律无证据 → 保守跳过（绝不硬刷 7.5 万 NULL）。
    assert probe == {"probed": 0, "with_time": 0, "has_fields": False}


def test_probe_survives_corrupt_tail_without_overcounting(tmp_path: Path) -> None:
    """窗口外尾段是不可解码的脏字节：不把整次探测打挂，样本也绝不越窗。"""
    rows = [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=False) for i in range(_WINDOW)]
    kb_dir = _write_kb(tmp_path, rows)
    with (kb_dir / "documents.jsonl").open("ab") as handle:
        handle.write(b"\xff\xfe not json at all\n" * 50)
    probe = probe_corpus_time_fields(kb_dir)
    assert 0 < probe["probed"] <= _WINDOW
    assert probe["with_time"] == 0 and probe["has_fields"] is False
    # 窗口放宽到覆盖脏尾也一样：坏行既不进分子也不进分母。
    tail = probe_corpus_time_fields(kb_dir, window=_WINDOW + 60)
    assert tail["with_time"] == 0 and tail["probed"] <= _WINDOW


def test_probe_requests_only_its_window_of_lines(tmp_path: Path) -> None:
    """读预算硬锁：探针向文件索取的行数恰好等于窗口，多一行都没付。

    替身只包一层真句柄的 ``__next__`` 做计数（真实解析路径一字不动）；若实现
    改成 ``read_text()`` 之类一次性吞文件，或把窗口判定挪到循环体开头，这里的
    计数会立刻对不上——GB 级语料上「只付前 N 行」是这个闸成立的前提。
    """
    rows = [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=False) for i in range(_WINDOW + 500)]
    _write_kb(tmp_path, rows)
    requested: list[int] = []

    class _CountingHandle:
        def __init__(self, handle: object) -> None:
            self._handle = handle
            self._lines = iter(handle)  # type: ignore[call-overload]

        def __iter__(self):
            return self

        def __next__(self) -> str:
            line = next(self._lines)
            requested.append(1)
            return line

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            self._handle.close()  # type: ignore[attr-defined]
            return False

    class _CountingDir(Path):
        def open(self, mode: str = "r", *args: object, **kwargs: object):
            return _CountingHandle(Path.open(self, mode, encoding="utf-8"))

    probe = probe_corpus_time_fields(_CountingDir(_kb_dir(tmp_path)))
    assert probe["probed"] == _WINDOW
    assert len(requested) == _WINDOW, f"读了 {len(requested)} 行，窗口只有 {_WINDOW}"


def test_probe_basis_visible_in_public_message(tmp_path: Path) -> None:
    """判据依据外流到人读的那一行：skipped 与 ok 两路都带 probed/with_time。"""
    rows = [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=False) for i in range(12)]
    _write_kb(tmp_path, rows, updates=rows)
    config = _config(tmp_path)
    store = _store(tmp_path, "visible")
    skipped = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert "探针 12 行仅 0 行带时间字段" in skipped["public_message"]
    assert f"台账缺口 {skipped['metadata_gaps']}" in skipped["public_message"]

    _write_kb(tmp_path, [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=True) for i in range(12)])
    refreshed = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert refreshed["metadata_status"] == "ok"
    assert "时间元数据回填 24" in refreshed["public_message"]
    assert "探针 12 行、12 行带字段" in refreshed["public_message"]


def test_probe_rejects_non_object_json_lines(tmp_path: Path) -> None:
    """合法 JSON 但不是对象（数组/裸值）：同样不给样本背书。"""
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True)
    with (kb_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("[1, 2, 3]\n")
        handle.write("null\n")
        handle.write('"just a string"\n')
        handle.write(
            json.dumps(_row(f"{_TOPIC}/moegirl/A0", 0, enriched=True), ensure_ascii=False)
            + "\n"
        )
    assert probe_corpus_time_fields(kb_dir) == {
        "probed": 1,
        "with_time": 1,
        "has_fields": True,
    }


@pytest.mark.parametrize(
    ("window", "hits"), [(1, 1), (2, 1), (5, 1), (10, 1), (20, 2)]
)
def test_probe_threshold_is_min_one_hit_plus_ratio(
    tmp_path: Path, window: int, hits: int
) -> None:
    """阈值口径锁死：至少 1 行命中，且不低于窗口的 10%（含微型语料）。"""
    rows = [
        _row(f"{_TOPIC}/moegirl/A{i}", i, enriched=i < hits) for i in range(window)
    ]
    _write_kb(tmp_path, rows)
    probe = probe_corpus_time_fields(_kb_dir(tmp_path), window=window)
    assert probe == {
        "probed": window,
        "with_time": hits,
        "has_fields": True,
    }


def test_probe_threshold_rejects_sub_ratio_hits(tmp_path: Path) -> None:
    """20 行窗口里只 1 行带字段（5% < 10%）：判"没这字段"，不被孤例牵着刷。"""
    rows = [_row(f"{_TOPIC}/moegirl/A{i}", i, enriched=(i == 3)) for i in range(20)]
    _write_kb(tmp_path, rows)
    probe = probe_corpus_time_fields(_kb_dir(tmp_path), window=20)
    assert probe == {"probed": 20, "with_time": 1, "has_fields": False}
