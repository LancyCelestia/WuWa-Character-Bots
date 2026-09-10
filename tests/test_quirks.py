"""persona_quirks（L4 小习惯评审区）回归测试：生命周期/去重/封顶/渲染/持久化/并发。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.quirks import QuirkStore


class _StepClock:
    """可注入时钟：每次调用前进 1 秒，保证 created_at/reviewed_at 严格递增。"""

    def __init__(self) -> None:
        self._moment = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self._moment
        self._moment += timedelta(seconds=1)
        return current


def _make_store(tmp_path: Path, name: str = "persona_quirks.sqlite3") -> QuirkStore:
    return QuirkStore(tmp_path / name, clock=_StepClock())


def test_propose_goes_to_pending_without_prompt_effect(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    quirk = store.propose("会在句尾悄悄加上波浪号", "reflection:2026-09-11")
    assert quirk.status == "pending_review"
    assert quirk.reviewed_at is None
    assert quirk.source == "reflection:2026-09-11"
    # pending 在批准前对 prompt 零影响。
    assert store.render_prompt_section() == ""
    assert store.counts() == {"pending_review": 1, "active": 0, "retired": 0}
    with pytest.raises(ValueError):
        store.propose("   ")


def test_dedupe_ignores_whitespace_and_case(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    first = store.propose("Say  Hi 每天清晨问安", "reflection:day1")
    second = store.propose("  SAY HI  每天清晨问安 ", "reflection:day2")
    assert second.quirk_id == first.quirk_id
    # 命中已有 pending → 原样返回，不新建、不改来源。
    assert second.status == "pending_review"
    assert second.created_at == first.created_at
    assert second.source == "reflection:day1"
    assert store.counts()["pending_review"] == 1


def test_approve_makes_active_and_renders_newest_first(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    earlier = store.propose("说话时爱用海与星辰打比方", "reflection:day1")
    later = store.propose("开心时会哼两句跑调的歌", "reflection:day2")
    assert store.approve(earlier.quirk_id) is True
    assert store.approve(later.quirk_id) is True
    section = store.render_prompt_section()
    assert "海与星辰" in section
    assert "跑调的歌" in section
    # 最近过审的排前面。
    assert section.index("跑调的歌") < section.index("海与星辰")
    assert store.approve(earlier.quirk_id) is False  # 已 active，非 pending 转换


def test_retire_removes_from_render(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    quirk = store.add_direct("睡前会检查星星有没有归位", "admin")
    assert "星星" in store.render_prompt_section()
    assert store.retire(quirk.quirk_id) is True
    assert store.render_prompt_section() == ""
    assert store.retire(quirk.quirk_id) is False  # 重复退役无效
    assert store.counts() == {"pending_review": 0, "active": 0, "retired": 1}


def test_pending_cap_evicts_oldest(tmp_path: Path) -> None:
    store = _make_store(tmp_path)  # 默认 max_pending=20
    ids = [
        store.propose(f"待审习惯第{index}条", f"reflection:day{index}").quirk_id
        for index in range(21)
    ]
    assert store.counts()["pending_review"] == 20
    pending_ids = {q.quirk_id for q in store.list(status="pending_review", limit=100)}
    assert ids[0] not in pending_ids  # 最旧的被逐出队列
    assert ids[1] in pending_ids
    assert ids[-1] in pending_ids  # 最新提案保留


def test_add_direct_is_active_immediately(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    quirk = store.add_direct("下雨天想把伞让给别人", "admin")
    assert quirk.status == "active"
    assert quirk.reviewed_at is not None
    assert "让给别人" in store.render_prompt_section()
    # add_direct 命中同文本 pending：视为当场转正。
    pending = store.propose("独一无二的新习惯", "reflection:day9")
    direct = store.add_direct("  独一无二的新习惯  ", "admin")
    assert direct.quirk_id == pending.quirk_id
    assert direct.status == "active"
    assert store.counts()["pending_review"] == 0


def test_render_format_leaks_no_bookkeeping(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    first = store.add_direct("听见琴声会不自觉放慢脚步", "admin")
    second = store.add_direct("会把重要的事折成小小的纸船", "admin")
    third = store.add_direct("第三条习惯用于验证截断", "admin")
    section = store.render_prompt_section(max_active=6)
    lines = section.splitlines()
    assert lines[0] == "最近养成的小习惯（可自然运用，不要刻意罗列）："
    for line in lines[1:]:
        assert line.startswith("- ")
        assert not line.startswith("- 1")  # 不带编号
    for quirk in (first, second, third):
        assert quirk.quirk_id not in section
        assert quirk.created_at not in section
        assert quirk.source not in section
    for token in ("active", "pending_review", "retired"):
        assert token not in section
    # 超出 max_active 的最旧条目不渲染（最近过审在前）。
    small = store.render_prompt_section(max_active=2)
    assert "纸船" in small and "放慢脚步" not in small
    assert store.render_prompt_section(max_active=0) == ""


def test_counts_reflect_all_statuses(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    approved = store.propose("习惯甲", "reflection:day1")
    store.propose("习惯乙", "reflection:day2")
    retired = store.add_direct("习惯丙", "admin")
    assert store.approve(approved.quirk_id) is True
    assert store.retire(retired.quirk_id) is True
    assert store.counts() == {"pending_review": 1, "active": 1, "retired": 1}


def test_persistence_roundtrip_close_reopen(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.sqlite3"
    store = QuirkStore(path, clock=_StepClock())
    active = store.add_direct("茶要放凉一点才喝", "admin")
    store.propose("待审的小习惯", "reflection:day3")
    store.close()

    reopened = QuirkStore(path, clock=_StepClock())
    assert [q.quirk_text for q in reopened.list_active(limit=10)] == [
        "茶要放凉一点才喝"
    ]
    assert reopened.counts() == {"pending_review": 1, "active": 1, "retired": 0}
    pending = reopened.list(status="pending_review", limit=10)[0]
    assert reopened.approve(pending.quirk_id) is True
    assert active.quirk_id in {q.quirk_id for q in reopened.list_active(limit=10)}
    reopened.close()


def test_eight_thread_propose_and_approve_smoke(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    seed = store.propose("种子习惯", "reflection:seed")
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            store.propose(f"并发习惯第{index}号", f"reflection:thread{index}")
            store.approve(seed.quirk_id)
        except BaseException as exc:  # noqa: BLE001 - 冒烟测试收集一切异常
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    counts = store.counts()
    assert counts == {"pending_review": 8, "active": 1, "retired": 0}
    assert len(store.list(status="pending_review", limit=100)) == 8
