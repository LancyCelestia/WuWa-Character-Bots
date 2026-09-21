"""笔记能力回归（2026-09-13 六域批）：存储/展示/指令面/图片落盘/路由触发。

全离线：SQLite 走 tmp_path；图片根目录 monkeypatch 到 tmp；不触网。
"""

from __future__ import annotations

from types import SimpleNamespace

import plugins.bot_unified_runtime.domains.notes.capabilities.notes as notes_mod
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.notes.capabilities.notes import (
    build_notes_capability,
    is_notes_command,
    note_display_text,
    note_image_files,
)
from plugins.bot_unified_runtime.domains.notes.store import (
    notes_store as notes_store_mod,
)
from plugins.bot_unified_runtime.domains.notes.store.notes_store import (
    NotesStore,
    detect_note_kind,
    reset_stores_for_tests,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"rest-of-fake-image"


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_notes_db_path=str(tmp_path / "n.sqlite3"),
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
    )


def _message(text: str, *, segments: list | None = None) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1",
        raw_segments=segments or [],
    )


def _setup(tmp_path, monkeypatch) -> None:
    reset_stores_for_tests()
    monkeypatch.setattr(notes_mod, "_images_root", lambda _config: tmp_path / "imgs")


# ---------- 存储层 ----------

def test_store_add_list_get_roundtrip(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u1", chat_id="group:1", content_md="# 标题\n正文第一行")
    assert note is not None and note.note_id == 1 and note.kind == "note"
    todo = store.add(user_id="u1", chat_id="group:1", content_md="- [ ] 买牛奶")
    assert todo is not None and todo.kind == "todo" and todo.todo_state == "open"
    assert detect_note_kind("- [ ] 买牛奶") == ("todo", "open")
    assert detect_note_kind("普通笔记") == ("note", "")
    listed = store.list_notes("group:1")
    assert [item.note_id for item in listed] == [1, 2]
    assert store.get(2, "group:1").content_md == "- [ ] 买牛奶"
    # 会话隔离：别的会话看不到。
    assert store.list_notes("group:2") == []
    assert store.get(2, "group:2") is None
    # 待办清单只给开着的。
    assert [item.note_id for item in store.list_open_todos("group:1")] == [2]


def test_store_limit_refuses_when_full(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3", max_notes_per_chat=2)
    assert store.add(user_id="u", chat_id="c", content_md="一") is not None
    assert store.add(user_id="u", chat_id="c", content_md="二") is not None
    assert store.add(user_id="u", chat_id="c", content_md="三") is None, "超上限必须拒绝"
    assert store.count_chat("c") == 2


def test_store_mark_done_and_delete(tmp_path) -> None:
    store = NotesStore(tmp_path / "n.sqlite3")
    note = store.add(user_id="u", chat_id="c", content_md="- [ ] 写周报")
    done = store.mark_done(note.note_id, "c")
    assert done.todo_state == "done" and done.done_at
    again = store.mark_done(note.note_id, "c")
    assert again.done_at == done.done_at, "重复勾选不刷新 done_at"
    # 普通笔记不受 done 语义影响。
    plain = store.add(user_id="u", chat_id="c", content_md="随手记")
    assert store.mark_done(plain.note_id, "c").todo_state == ""
    deleted = store.delete(note.note_id, "c")
    assert deleted.note_id == note.note_id
    assert store.get(note.note_id, "c") is None
    assert store.delete(99, "c") is None


# ---------- 展示（Markdown → 纯文本） ----------

def test_display_text_keeps_headings_and_marks_images() -> None:
    content = "# 周三计划\n## 上午\n- [ ] 写总结\n![图片1](abc.png)\n普通**加粗**一行"
    text = note_display_text(content)
    assert "# 周三计划" in text and "## 上午" in text  # 标题保留 #。
    assert "[图片1]" in text and "abc.png" not in text  # 图片行只留占位。
    assert "普通加粗一行" in text and "**" not in text


def test_image_files_resolve_within_chat_dir(tmp_path) -> None:
    from hashlib import sha1

    # 会话目录 = images_root / sha1(chat_id)[:12]（实现口径，测试不猜哈希）。
    chat_dir = tmp_path / "imgs" / sha1(b"chat-x").hexdigest()[:12]
    chat_dir.mkdir(parents=True)
    target = chat_dir / "img1.png"
    target.write_bytes(PNG_MAGIC)
    content = "![图片1](img1.png)"
    found = note_image_files(content, tmp_path / "imgs", "chat-x")
    assert found == [target]
    # 会话隔离：别的会话名下看不见这张图。
    assert note_image_files(content, tmp_path / "imgs", "chat-other") == []
    # 穿越尝试：basename 化后不存在 → 空。
    assert note_image_files("![图片1](../../secret.png)", tmp_path / "imgs", "chat-x") == []


# ---------- 能力指令面 ----------

def test_capability_add_list_view_done_delete(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    capability = build_notes_capability(_config(tmp_path))
    added = capability(_message("笔记 记 周三要交总结\n- [ ] 写初稿"), object())
    assert "第 1 条" in added.body and "记下了" in added.body
    listed = capability(_message("笔记列表"), object())
    assert "1 □ 周三要交总结" in listed.body and "待办还开着 1 件" in listed.body
    viewed = capability(_message("笔记 看 1"), object())
    assert "周三要交总结" in viewed.body and "（待办，还没完成）" in viewed.body
    done = capability(_message("做完1"), object())
    assert "完成了" in done.body and "周三要交总结" in done.body
    repeat = capability(_message("做完1"), object())
    assert "已经完成过了" in repeat.body
    plain = capability(_message("笔记 记 随手一句话"), object())
    assert "第 2 条" in plain.body
    not_todo = capability(_message("做完2"), object())
    assert "不是待办" in not_todo.body
    deleted = capability(_message("删笔记 2"), object())
    assert "放下了" in deleted.body  # 文案审计②：与提醒域统一用词「放下」。
    miss = capability(_message("删笔记 2"), object())
    assert "没有找到第 2 条" in miss.body


def test_capability_usage_on_bare_trigger(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(_message("笔记"), object())
    assert "笔记 记" in result.body and "笔记列表" in result.body
    empty = capability(_message("笔记列表"), object())
    assert "还没有为你记下过笔记" in empty.body


def test_capability_limit_message(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config.bot_notes_max_per_chat = 1
    capability = build_notes_capability(config)
    first = capability(_message("笔记 记 第一条"), object())
    assert "第 1 条" in first.body
    second = capability(_message("笔记 记 第二条"), object())
    assert "收满 1 条" in second.body and "删笔记" in second.body


def test_capability_saves_message_images(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    source = tmp_path / "raw.png"
    source.write_bytes(PNG_MAGIC)
    segments = [{"type": "image", "data": {"file": str(source), "url": ""}}]
    capability = build_notes_capability(_config(tmp_path))
    result = capability(_message("笔记 记 看这张图", segments=segments), object())
    assert "第 1 条" in result.body and "附图 1 张" in result.body
    store = notes_store_mod.build_notes_store(_config(tmp_path))
    note = store.get(1, "group:1")
    assert "![图片1](" in note.content_md
    saved = note_image_files(note.content_md, tmp_path / "imgs", "group:1")
    assert len(saved) == 1 and saved[0].read_bytes() == PNG_MAGIC
    # 看笔记补发图。
    view = capability(_message("笔记 看 1"), object())
    assert view.images and str(view.images[0]["file"]) == str(saved[0])
    # 删除笔记连带清图。
    capability(_message("删笔记 1"), object())
    assert not saved[0].exists()


# ---------- 触发判定与路由 ----------

def test_is_notes_command_matrix() -> None:
    assert is_notes_command("笔记")
    assert is_notes_command("笔记列表")
    assert is_notes_command("笔记 记 买牛奶")
    assert is_notes_command("筆記 記 買牛奶")
    assert is_notes_command("笔记 看 3")
    assert is_notes_command("看笔记 3")
    assert is_notes_command("做完3")
    assert is_notes_command("删笔记 3")
    assert is_notes_command("biji")
    assert is_notes_command("bijiliebiao")
    assert is_notes_command("bjlb")
    assert is_notes_command("shanbiji 3")
    assert not is_notes_command("看这个笔记了吗")
    assert not is_notes_command("读书笔记真好看")  # 非命令形态不抢路由。
    # ASCII 词边界（T-Spec 棘轮，2026-09-13 收口）：粘连词不得成为命令。
    assert not is_notes_command("bijiqq")
    assert not is_notes_command("bijiliebiaoqq")
    assert not is_notes_command("noteqq")
    assert not is_notes_command("notesqq")
    # ASCII 分支分隔形态仍可用。
    assert is_notes_command("biji 记 买牛奶")
    assert is_notes_command("note 买牛奶")


def test_notes_route_through_base_router() -> None:
    config = SimpleNamespace()  # 开关字段缺省=启用（与生产默认一致）。
    clear_route_decision_cache()
    for text in ("笔记列表", "做完1", "笔记 记 买牛奶", "笔记"):
        decision = classify_message_route(text, config=config)
        assert decision.kind is RouteKind.REMINDER, text
    decision = classify_message_route("做完了", config=config)
    assert decision.kind is not RouteKind.REMINDER, "光杆勾选让位聊天"
    decision = classify_message_route("提醒列表", config=config)
    assert decision.kind is RouteKind.REMINDER, "既有提醒触发不受影响"
