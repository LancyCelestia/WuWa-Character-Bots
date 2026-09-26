"""P2 收尾性能回归：affinity 持久连接、互动计数写盘节流、meme 入库线程池 offload。

全部离线。
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------- affinity 持久连接


def test_affinity_store_reuses_single_connection(tmp_path, monkeypatch):
    """observe/set_nickname/snapshot 各操作不得再每操作新开 SQLite 连接。"""
    import plugins.bot_unified_runtime.domains.chat_reply.character.affinity as affinity_module
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        DynamicAffinityStore,
    )

    connect_calls: list[str] = []
    real_connect = affinity_module.sqlite3.connect

    def counting_connect(path, **kwargs):
        connect_calls.append(str(path))
        return real_connect(path, **kwargs)

    monkeypatch.setattr(affinity_module.sqlite3, "connect", counting_connect)

    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3")
    store.observe("user-1", "太棒了，谢谢你！")
    store.set_nickname("user-1", "小明")
    snapshot = store.snapshot("user-1")

    assert snapshot["nickname"] == "小明"
    assert len(connect_calls) == 1, "同 store 的全部操作应复用同一连接"


def test_affinity_store_thread_agnostic(tmp_path):
    """check_same_thread=False：不同线程使用同一 store 实例不报错。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        DynamicAffinityStore,
    )

    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3")
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            store.observe(f"user-{index}", "内容")
            assert store.snapshot(f"user-{index}")["affinity"] >= 0.0
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


# ---------------------------------------------------------------- 互动计数节流


def test_interaction_increment_throttles_disk_writes(tmp_path, monkeypatch):
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        settings as settings_module,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )

    store = RuntimeSettingsStore(tmp_path / "s.json", instance="t-throttle")
    fake_clock = [1000.0]
    monkeypatch.setattr(
        settings_module, "time", SimpleNamespace(monotonic=lambda: fake_clock[0])
    )

    save_calls: list[int] = []
    real_save = store._save

    def counting_save() -> None:
        save_calls.append(1)
        real_save()

    monkeypatch.setattr(store, "_save", counting_save)

    store.interaction_increment("user-1")
    store.interaction_increment("user-1")
    store.interaction_increment("user-2")
    assert len(save_calls) == 1, "30s 窗口内重复 +1 不得反复全量写盘"
    assert store.interaction_count("user-1") == 2, "内存读取必须即时生效"

    fake_clock[0] = 1031.0
    store.interaction_increment("user-1")
    assert len(save_calls) == 2, "超过节流窗口应重新落盘"


def test_interaction_full_dump_includes_pending_counts(tmp_path):
    """其他 mutator 的全量 _save 会顺带把未落盘计数一并写掉。"""
    import json

    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )

    path = tmp_path / "s.json"
    store = RuntimeSettingsStore(path, instance="t-dump")
    store.interaction_increment("user-9")
    # 模拟另一 mutator 触发保存
    store._overrides["BOT_X"] = "1"
    store._save()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["interactions"]["user-9"] == 1


# ---------------------------------------------------------------- meme 入库 offload


@pytest.fixture()
def _fake_store():
    class FakeStore:
        def __init__(self) -> None:
            self.added: list[str] = []
            self.existing: set[str] = set()
            self.cleaned = False
            self.add_thread: int | None = None

        def exists(self, md5: str) -> bool:
            return md5 in self.existing

        def add(self, *, md5: str, path: str, ext: str, group_id: str | None) -> None:
            self.add_thread = threading.get_ident()
            self.added.append(md5)

        def cleanup(self, *, max_files: int, max_age_days: int) -> None:
            self.cleaned = True

    return FakeStore()


def _absorb_config(tmp_path):
    return SimpleNamespace(
        bot_meme_library_enabled=True,
        bot_meme_library_dir=str(tmp_path / "memes"),
        bot_meme_library_max_file_bytes=1048576,
        bot_meme_library_proxy="",
        bot_meme_library_vlm_enabled=False,
        bot_meme_library_max_files=0,
        bot_meme_library_max_age_days=0,
        bot_meme_library_group_allowlist=[],
        bot_meme_library_group_denylist=[],
    )


def _fake_group_event():
    return SimpleNamespace(
        get_session_id=lambda: "group_123",
        group_id="123",
        get_message=list,
    )


def test_absorb_event_images_offloads_persist(tmp_path, monkeypatch, _fake_store):
    import hashlib

    import plugins.bot_unified_runtime.domains.meme.sources.meme_library_listener as listener

    config = _absorb_config(tmp_path)
    payload = b"fake-png-bytes"

    async def fake_download(url, *, max_bytes, proxy):
        return (payload, "image/png")

    monkeypatch.setattr(listener, "_download_once", fake_download)
    monkeypatch.setattr(
        listener, "_segment_urls", lambda segments: ["https://example.com/a.png"]
    )

    result = asyncio.run(
        listener.absorb_event_images(object(), _fake_group_event(), config, _fake_store)
    )

    assert result["saved"] == 1
    assert _fake_store.added == [hashlib.md5(payload).hexdigest()]
    assert list((tmp_path / "memes").glob("*.png"))
    assert _fake_store.cleaned
    main_thread = threading.get_ident()
    assert _fake_store.add_thread != main_thread, "入库必须在事件循环之外的线程执行"


def test_absorb_event_images_skips_duplicates(tmp_path, monkeypatch, _fake_store):
    import hashlib

    import plugins.bot_unified_runtime.domains.meme.sources.meme_library_listener as listener

    config = _absorb_config(tmp_path)
    payload = b"dup-bytes"

    async def fake_download(url, *, max_bytes, proxy):
        return (payload, "image/png")

    monkeypatch.setattr(listener, "_download_once", fake_download)
    monkeypatch.setattr(
        listener, "_segment_urls", lambda segments: ["https://example.com/a.png"]
    )
    _fake_store.existing.add(hashlib.md5(payload).hexdigest())

    result = asyncio.run(
        listener.absorb_event_images(object(), _fake_group_event(), config, _fake_store)
    )

    assert result["saved"] == 0
    assert _fake_store.added == []
