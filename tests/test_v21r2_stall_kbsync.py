"""R3 停摆批：kb-sync 任务治理回归（互斥 / 可取消 / 零变更夜跳过 ANN）。

全离线：store 用假替身（不触 SQLite/嵌入链/真实语料），``sync_kb_wiki``
monkeypatch 成委托 store.sync_documents（取消检查/进度回调语义保真）。
覆盖项：
- 任务互斥：已有同步在跑时第二路立即 busy 跳过（启动补同步 × 夜间同步撞车面）；
- 协作式取消：任务入口消费预置请求 / 批进度回调处穿透取消（同步批、嵌入批）、
  embed_provider 还原、取消状态出口消费不残留；
- 零变更夜（added/changed/removed=0 且无新嵌入）跳过 ANN 全量重建
  （实弹：23.8 万块零变更夜仍重建 8.5 分钟，占事件循环默认线程池）；
- 有新增/嵌入/索引缺失时仍重建（healing 语义保留）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

CONFIG = SimpleNamespace(bot_kb_wiki_chunk_chars=800, bot_kb_wiki_embed_batch=128)

_ZERO_SYNC_STATS = {
    "added": 0,
    "changed": 0,
    "removed": 0,
    "skipped": 0,
    "chunks": 0,
}


class FakeStore:
    """最小 store 替身：记录调用、按剧本吐统计。"""

    def __init__(
        self,
        *,
        sync_stats: dict | None = None,
        embed_result: tuple[int, int] = (0, 0),
        sync_progress: bool = False,
        embed_progress: bool = False,
        ann_files: bool = True,
    ) -> None:
        self.embed_provider = SimpleNamespace(name="normal-provider")
        # 默认 ANN 路径指向真实存在的文件（本测试文件自身），模拟"索引在位"；
        # ann_files=False 时换成必然不存在的路径 → 触发 healing 重建分支。
        self.ann_index_path = str(Path(__file__))
        self.ann_order_path = str(Path(__file__))
        self.sync_calls: list[dict] = []
        self.embed_calls: list[dict] = []
        self.build_ann_calls = 0
        self._sync_stats = dict(sync_stats or _ZERO_SYNC_STATS)
        self._embed_result = embed_result
        self._sync_progress = sync_progress
        self._embed_progress = embed_progress
        if not ann_files:
            self.ann_index_path = str(
                Path(__file__).parent / "_definitely_missing_ann.index"
            )
            self.ann_order_path = str(
                Path(__file__).parent / "_definitely_missing_ann.order.json"
            )

    def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
        self.sync_calls.append({"full": full})
        if self._sync_progress and on_progress is not None:
            on_progress(dict(self._sync_stats))
        return dict(self._sync_stats)

    def embed_pending(self, files, on_progress=None, *, batch_size=None):
        self.embed_calls.append({"batch_size": batch_size})
        done, pending = self._embed_result
        if self._embed_progress and on_progress is not None and pending:
            on_progress(done, pending)
        return done, pending

    def stats(self) -> dict[str, int]:
        return {"total": 238453, "embedded": 238453}

    def document_count(self) -> int:
        return 75683

    def build_ann_index(self, on_progress=None) -> dict:
        self.build_ann_calls += 1
        return {"built": True, "vectors": 238453, "reason": ""}


@pytest.fixture(autouse=True)
def _patched_env(monkeypatch):
    """隔离：sync_kb_wiki 委托 store.sync_documents（进度/取消语义保真）；
    收尾兜底清互斥闸与取消事件（防用例失败残留毒化其他测试）。"""
    monkeypatch.setattr(
        kb_wiki,
        "sync_kb_wiki",
        lambda store, config, *, full=False, on_progress=None: (
            store.sync_documents([], full=full, on_progress=on_progress)
        ),
    )
    yield
    if kb_wiki._SYNC_TASK_MUTEX.locked():
        kb_wiki._SYNC_TASK_MUTEX.release()
    kb_wiki._SYNC_CANCEL_EVENT.clear()


# ---------------------------------------------------------------- 任务互斥


def test_busy_mutex_skips_second_run() -> None:
    assert kb_wiki._SYNC_TASK_MUTEX.acquire(blocking=False)
    try:
        result = kb_wiki.run_kb_sync_task(CONFIG)
        assert result["error_kind"] == "busy"
        assert result["ok"] is False
        assert "互斥" in result["public_message"]
    finally:
        kb_wiki._SYNC_TASK_MUTEX.release()
    # 释放后可正常进入（走 config_missing 短路而非 busy）。
    result = kb_wiki.run_kb_sync_task(SimpleNamespace())
    assert result["error_kind"] == "config_missing"


# ---------------------------------------------------------------- 可取消


def test_cancel_before_start_consumed_at_entry() -> None:
    assert kb_wiki.cancel_kb_sync_task(reason="unit-test") is True
    store = FakeStore()
    result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    assert result["error_kind"] == "cancelled"
    assert "续传" in result["public_message"]
    assert store.sync_calls == [], "入口消费：同步一步都不该跑"
    # 出口已消费取消状态：下一轮应能正常跑完（不残留、不毒化夜间同步）。
    result2 = kb_wiki.run_kb_sync_task(CONFIG, store=FakeStore())
    assert result2["error_kind"] == "none"
    assert result2["ok"] is True


def test_cancel_fires_from_sync_progress_and_restores_provider() -> None:
    # 取消请求在任务启动后才出现：同步批进度回调处命中。
    store = FakeStore(sync_progress=True)
    normal_provider = store.embed_provider
    original = kb_wiki.sync_kb_wiki

    def patched(store_, config_, *, full=False, on_progress=None):
        kb_wiki.cancel_kb_sync_task(reason="mid-sync")  # 模拟外部在跑中请求取消。
        return original(store_, config_, full=full, on_progress=on_progress)

    kb_wiki.sync_kb_wiki = patched  # type: ignore[assignment]
    try:
        result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    finally:
        kb_wiki.sync_kb_wiki = original  # type: ignore[assignment]
    assert result["error_kind"] == "cancelled"
    # provider 已被同步期换上又由内层 finally 还原。
    assert store.embed_provider is normal_provider


def test_cancel_fires_from_embed_progress_batch_boundary() -> None:
    # 取消在同步完成后、嵌入进行中触发：嵌入批边界必须穿透。
    store = FakeStore(embed_result=(128, 256), embed_progress=True)
    normal_provider = store.embed_provider
    original = kb_wiki.sync_kb_wiki

    def patched(store_, config_, *, full=False, on_progress=None):
        stats = original(store_, config_, full=full, on_progress=on_progress)
        kb_wiki.cancel_kb_sync_task(reason="before-embed")  # 同步后、嵌入前置位。
        return stats

    kb_wiki.sync_kb_wiki = patched  # type: ignore[assignment]
    try:
        result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    finally:
        kb_wiki.sync_kb_wiki = original  # type: ignore[assignment]
    assert result["error_kind"] == "cancelled"
    assert store.embed_calls, "取消应发生在嵌入批边界（已进入嵌入阶段）"
    assert store.embed_provider is normal_provider


# ---------------------------------------------------------------- ANN 重建门


def test_unchanged_night_skips_ann_rebuild() -> None:
    store = FakeStore()
    result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    assert result["ok"] is True
    assert store.build_ann_calls == 0
    assert result["ann_reason"] == "unchanged_skip"
    assert result["ann_built"] is False


def test_ann_rebuilds_when_documents_changed() -> None:
    store = FakeStore(
        sync_stats={
            "added": 3,
            "changed": 1,
            "removed": 0,
            "skipped": 75679,
            "chunks": 12,
        }
    )
    result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    assert result["ok"] is True
    assert store.build_ann_calls == 1
    assert result["ann_built"] is True
    assert result["ann_vectors"] == 238453


def test_ann_rebuilds_when_new_vectors_embedded() -> None:
    store = FakeStore(embed_result=(5, 5))
    result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    assert result["ok"] is True
    assert store.build_ann_calls == 1


def test_ann_rebuilds_when_index_files_missing_healing() -> None:
    store = FakeStore(ann_files=False)
    result = kb_wiki.run_kb_sync_task(CONFIG, store=store)
    assert result["ok"] is True
    assert store.build_ann_calls == 1, "索引文件缺失时零变更夜也必须补建（healing）"
