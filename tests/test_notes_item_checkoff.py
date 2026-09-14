"""笔记待办逐条勾选回归（审查 A-06：勾一条只动一条，不再整篇置完成）。

旧缺陷：mark_done 一条 UPDATE 把整篇置 done，content_md 里的 ``- [ ]``
从不回写 ``[x]``——勾「买牛奶」连「买面包」一起消失且不可再勾。
本文件锁新契约：
- store 层 mark_item_done：按稳定条目号改写单行 [x]；全勾完才整篇 done；
  幂等无写入；越界返回 None；并发勾两条不死锁不互吞。
- 能力层「做完 N」：一次勾掉第一个未勾条目，有剩报「还剩几件」。
全离线：SQLite 走 tmp_path，不触网。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import plugins.bot_unified_runtime.capabilities.notes as notes_mod
from plugins.bot_unified_runtime.capabilities.notes import build_notes_capability
from plugins.bot_unified_runtime.character import notes_store as notes_store_mod
from plugins.bot_unified_runtime.character.notes_store import (
    NotesStore,
    reset_stores_for_tests,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

# 三条待办（第三条带缩进，锁「缩进原样保留」契约）。
MULTI_MD = "# 采购\n- [ ] 买牛奶\n- [ ] 买面包\n  - [ ] 顺手拿鸡蛋"


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1",
        raw_segments=[],
    )


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_notes_db_path=str(tmp_path / "n.sqlite3"),
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
    )


def _setup(tmp_path, monkeypatch) -> None:
    reset_stores_for_tests()
    monkeypatch.setattr(notes_mod, "_images_root", lambda _config: tmp_path / "imgs")


# ---------- store 层：mark_item_done ----------

def test_store_item_done_rewrites_only_target_line(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    updated = store.mark_item_done(note.note_id, "c", 0)
    assert updated is not None
    # 只有第 0 条改 [x]，其余行（含缩进第三条）逐字节原样。
    assert updated.content_md == (
        "# 采购\n- [x] 买牛奶\n- [ ] 买面包\n  - [ ] 顺手拿鸡蛋"
    )
    # 还有未勾条目：整篇不算完成。
    assert updated.todo_state == "open" and updated.done_at == ""


def test_store_item_done_marks_done_only_when_all_checked(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    assert store.mark_item_done(note.note_id, "c", 0).todo_state == "open"
    second = store.mark_item_done(note.note_id, "c", 1)
    assert second.todo_state == "open" and second.done_at == ""
    final = store.mark_item_done(note.note_id, "c", 2)
    assert final.todo_state == "done" and final.done_at, "全勾完才整篇 done"
    assert "[ ]" not in final.content_md
    assert store.list_open_todos("c") == []


def test_store_item_done_idempotent_no_write_on_recheck(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    first = store.mark_item_done(note.note_id, "c", 0)
    # 已勾行重复勾选：幂等——无写入（updated_at 也不动），不报错。
    again = store.mark_item_done(note.note_id, "c", 0)
    assert again.content_md == first.content_md
    assert again.updated_at == first.updated_at
    assert again.todo_state == "open"
    # 全勾完后再碰任意勾选框行：done_at 不刷新。
    store.mark_item_done(note.note_id, "c", 1)
    done = store.mark_item_done(note.note_id, "c", 2)
    touched = store.mark_item_done(note.note_id, "c", 0)
    assert touched.todo_state == "done" and touched.done_at == done.done_at


def test_store_item_done_out_of_range_returns_none(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    assert store.mark_item_done(note.note_id, "c", -1) is None
    assert store.mark_item_done(note.note_id, "c", 3) is None
    assert store.mark_item_done(note.note_id, "c", 999) is None
    # 越界零写入：内容与状态原样。
    unchanged = store.get(note.note_id, "c")
    assert unchanged.content_md == MULTI_MD and unchanged.todo_state == "open"
    # 非待办笔记与不存在的笔记：同样 None。
    plain = store.add(user_id="u", chat_id="c", content_md="随手记")
    assert store.mark_item_done(plain.note_id, "c", 0) is None
    assert store.mark_item_done(4242, "c", 0) is None


def test_store_item_index_is_stable_across_calls(tmp_path) -> None:
    """条目号=勾选框行的文档行序（含已勾行一起编号）。

    若只对未勾行编号，勾掉一条会让其余编号整体前移、并发下指错行——
    稳定编号是逐条勾选的定位基础（契约钉死）。
    """
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    assert [index for index, _text in note.todo_open_items()] == [0, 1, 2]
    store.mark_item_done(note.note_id, "c", 0)
    fresh = store.get(note.note_id, "c")
    # 勾掉第 0 条后，剩余候选的条目号不前移。
    assert [index for index, _text in fresh.todo_open_items()] == [1, 2]
    updated = store.mark_item_done(note.note_id, "c", 2)
    assert "  - [x] 顺手拿鸡蛋" in updated.content_md, "2 号仍指第三行"
    assert "- [ ] 买面包" in updated.content_md, "1 号（买面包）不受影响"


def test_store_item_done_survives_concurrent_two_items(tmp_path) -> None:
    """并发勾两条：不死锁（join 能返回）、不互吞（两行都 [x]）。

    锁纪律（2026-09-13 实测教训）：UPDATE 与 get() 必须分两段取锁；
    并发改写同一篇时靠 content_md 守护+有限重试收敛。
    """
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md="- [ ] 甲\n- [ ] 乙")
    barrier = threading.Barrier(2)
    results: list[str] = []

    def _check(item_index: int) -> None:
        barrier.wait()
        updated = store.mark_item_done(note.note_id, "c", item_index)
        if updated is not None:
            results.append(updated.content_md)

    threads = [threading.Thread(target=_check, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "持锁调 get() 类死锁会让 join 挂死"
    final = store.get(note.note_id, "c")
    assert "- [x] 甲" in final.content_md and "- [x] 乙" in final.content_md
    assert final.todo_state == "done"


def test_store_legacy_mark_done_kept_as_compat_path(tmp_path) -> None:
    """旧整篇 mark_done 保留（兼容 reminder 关键词流等既有调用方）。

    语义原样：整篇置 done、已 done 不刷新 done_at；但 content_md 不回写
    ——这正是 A-06 缺陷本体，仅限非条目类待办/兼容路径使用。
    """
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md=MULTI_MD)
    done = store.mark_done(note.note_id, "c")
    assert done.todo_state == "done" and done.done_at
    assert done.content_md == MULTI_MD, "兼容路径不改写行内勾选框"
    again = store.mark_done(note.note_id, "c")
    assert again.done_at == done.done_at


# ---------- 能力层：「做完 N」按条目推进 ----------

def test_capability_done_n_checks_one_item_and_reports_remaining(
    tmp_path, monkeypatch
) -> None:
    _setup(tmp_path, monkeypatch)
    capability = build_notes_capability(_config(tmp_path))
    capability(_message("笔记 记 采购单\n- [ ] 买牛奶\n- [ ] 买面包"), object())
    first = capability(_message("做完1"), object())
    assert "勾掉" in first.body and "买牛奶" in first.body, "报勾掉的是哪一条"
    assert "还剩 1 件" in first.body, "有剩余要提还剩几件"
    store = notes_store_mod.build_notes_store(_config(tmp_path))
    mid = store.get(1, "group:1")
    assert "- [x] 买牛奶" in mid.content_md and "- [ ] 买面包" in mid.content_md
    assert mid.todo_state == "open", "勾一条不等于整篇完成"
    # 再勾一次（剩最后一件）→ 整篇完成，观感与旧版一致。
    second = capability(_message("做完1"), object())
    assert "完成了" in second.body
    final = store.get(1, "group:1")
    assert final.todo_state == "done" and "- [x] 买面包" in final.content_md
    # 完成后再勾：旧口径的「已经完成过了」。
    repeat = capability(_message("做完1"), object())
    assert "已经完成过了" in repeat.body


def test_capability_done_n_single_item_matches_old_shape(tmp_path, monkeypatch) -> None:
    """单待办笔记：一次勾完 → 整篇完成，观感同旧版；行内 [x] 同步回写。"""
    _setup(tmp_path, monkeypatch)
    capability = build_notes_capability(_config(tmp_path))
    capability(_message("笔记 记 周三计划\n- [ ] 写周报"), object())
    done = capability(_message("做完1"), object())
    assert "完成了" in done.body and "周三计划" in done.body
    store = notes_store_mod.build_notes_store(_config(tmp_path))
    note = store.get(1, "group:1")
    assert note.todo_state == "done"
    assert "- [x] 写周报" in note.content_md, "勾选痕迹要留在正文里"
