"""提醒作用域归属锁（审计 SEAT-ATK-INGEST A-ING-3 + 测试盲区⑥）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_reminder_scope_session_keys.py -q

根 ``__init__.py`` ``_build_memory_writer`` 的提醒抽取腿旧实现用
``session_id.partition(":")`` 自拆键形判作用域，而**真实入站群键是下划线形**
``group_<gid>_<uid>``（``domains/core/session_keys.py`` 判据口径第 1 条）——
冒号段拆不出来 ⇒ 群提醒被错记到发送者私聊作用域（整群语义丢失）。
本锁走**真实消费者腿**（``_writer`` → ``store_extracted_reminders`` 入参捕获），
按三形态钉死归属：下划线群形 / 私聊形 / 「群号:qq」域条目形；另钉冒号群形
（历史/合成/出站命名空间，判据口径第 2 条）与空键 fail-closed。
修法唯一：作用域派生一律走中央 ``parse_session_key``，禁消费点自拆。
"""
from __future__ import annotations

import types

import pytest

import plugins.bot_unified_runtime as runtime_module


def _run_writer(monkeypatch, tmp_path, session_id: str, sender_id: str = "456") -> dict:
    """驱动真实 ``_writer`` 提醒腿，捕获 ``store_extracted_reminders`` 收到的归属入参。"""
    captured: dict = {}

    def fake_store(store, *, drafts, session_key, sender_id, target_scope, target_id,
                   adapter="", bot_id=""):
        captured.update(
            {
                "session_key": session_key,
                "sender_id": sender_id,
                "target_scope": target_scope,
                "target_id": target_id,
            }
        )
        return len(drafts)

    memory_extract = "plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract"
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.memory.SQLiteMemoryRepository",
        lambda path, **kw: object(),
    )
    monkeypatch.setattr(f"{memory_extract}.extract_memory_texts", lambda *a, **k: [])
    monkeypatch.setattr(
        f"{memory_extract}.extract_reminder_drafts",
        lambda *a, **k: [types.SimpleNamespace(remind_at=None, text="交周报")],
    )
    monkeypatch.setattr(f"{memory_extract}.store_extracted_reminders", fake_store)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.schedule.store.reminders.build_reminder_store",
        lambda cfg: object(),
    )
    config = _writer_config(tmp_path)
    writer = runtime_module._build_memory_writer(config, model_router=object())
    assert writer is not None, "提醒抽取开关已开、装配门必须放行"
    writer(
        user_text="明天下午三点提醒我交周报",
        reply_text="好的，明天下午三点提醒你。",
        sender_id=sender_id,
        session_id=session_id,
    )
    return captured


def _writer_config(tmp_path):
    from plugins.bot_unified_runtime.config import Config

    return Config(
        bot_memory_enabled=True,
        bot_memory_extract_enabled=True,
        bot_memory_db_path=str(tmp_path / "memory-unused.sqlite3"),
        bot_chat_provider="openai_compatible",
        bot_reminder_enabled=True,
        bot_reminder_llm_extract_enabled=True,
    )


def test_reminder_scope_underscore_group_key_is_group(monkeypatch, tmp_path) -> None:
    """群形（权威入站形态 ``group_<gid>_<uid>``）：必须记**整群**，不是发送者私聊。"""
    captured = _run_writer(monkeypatch, tmp_path, "group_123_456", sender_id="456")
    assert captured["target_scope"] == "group", (
        f"群提醒被错记作用域（partition(':') 误判回潮）：{captured}"
    )
    assert captured["target_id"] == "123", f"群作用域必须落群号：{captured}"
    assert captured["session_key"] == "group_123_456"


def test_reminder_scope_private_bare_uid_is_private(monkeypatch, tmp_path) -> None:
    """私聊形（OneBot 私聊 = 裸 uid）：私聊归属、target 为该用户。"""
    captured = _run_writer(monkeypatch, tmp_path, "456", sender_id="456")
    assert captured["target_scope"] == "private"
    assert captured["target_id"] == "456"


def test_reminder_scope_private_scheme_key(monkeypatch, tmp_path) -> None:
    """私聊形（Telegram ``private_<chat_id>``）：target 取键内 uid，不退错人。"""
    captured = _run_writer(monkeypatch, tmp_path, "private_789", sender_id="456")
    assert captured["target_scope"] == "private"
    assert captured["target_id"] == "789", (
        f"私聊键的 uid 段必须从键派生（中央件口径），不是 sender 兜底：{captured}"
    )


def test_reminder_scope_domain_entry_not_selfsplit(monkeypatch, tmp_path) -> None:
    """「群号:qq」域条目形：非群命名空间的冒号串**不得**被自拆成两段作用域。

    域条目形（如 master-love 名单「群号:QQ」）不是会话键真身；中央件对无群前缀
    的冒号串整串归私聊裸键（user_id=整串）。消费点若回到 ``partition(":")``，
    target 会被砍成半截（``10010``）——本断言即该回潮的形状锁。
    """
    captured = _run_writer(monkeypatch, tmp_path, "10086:10010", sender_id="456")
    assert captured["target_scope"] != "group", f"域条目冒号串不得判群：{captured}"
    assert captured["target_id"] == "10086:10010", (
        f"整串归属裸私聊键，禁自拆半截：{captured}"
    )


def test_reminder_scope_legacy_colon_group_is_group(monkeypatch, tmp_path) -> None:
    """冒号群形（历史/合成/出站命名空间）：判据口径第 2 条，按构造即整群。"""
    captured = _run_writer(monkeypatch, tmp_path, "group:123", sender_id="456")
    assert captured["target_scope"] == "group"
    assert captured["target_id"] == "123"


def test_reminder_scope_empty_key_fails_closed_to_sender(monkeypatch, tmp_path) -> None:
    """空键/脏键 fail-closed：回落私聊 + 发送者，绝不造出无主群作用域。"""
    captured = _run_writer(monkeypatch, tmp_path, "", sender_id="456")
    assert captured["target_scope"] == "private"
    assert captured["target_id"] == "456"


@pytest.mark.parametrize("forged", ["group_123_456", "GROUP_123_456"])
def test_reminder_scope_case_insensitive_group_recognition(forged, monkeypatch, tmp_path) -> None:
    """前缀识别大小写不敏感（中央件口径第 3 条），消费者不得再窄一档。"""
    captured = _run_writer(monkeypatch, tmp_path, forged, sender_id="456")
    assert captured["target_scope"] == "group", f"{forged} 应判群：{captured}"
    assert captured["target_id"] == "123"
