import json

from plugins.wuwa_unified_runtime.capabilities.runtime_admin import (
    build_alert_check_result,
    build_runtime_admin_result,
)
from plugins.wuwa_unified_runtime.character.shared_group import (
    SQLiteGroupDigestProvider,
    build_shared_group_context_provider,
)
from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.output.render_backends import (
    NullRenderBackend,
    build_render_backend,
)
from plugins.wuwa_unified_runtime.runtime.alerts import (
    AlertContent,
    send_admin_alert,
)
from plugins.wuwa_unified_runtime.runtime.settings import (
    RuntimeSettingsStore,
    SETTABLE_KEYS,
)


def test_settings_store_set_get_reset_persists(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    assert store.set_override("WUWA_CHAT_TEMPERATURE", "0.4") == 0.4
    assert store.get_or("WUWA_CHAT_TEMPERATURE", None) == 0.4
    assert store.list_overrides() == {"WUWA_CHAT_TEMPERATURE": 0.4}

    reloaded = RuntimeSettingsStore(tmp_path / "settings.json")
    assert reloaded.get_or("WUWA_CHAT_TEMPERATURE", None) == 0.4
    assert reloaded.reset_override() == 1
    assert reloaded.get_or("WUWA_CHAT_TEMPERATURE", None) is None


def test_settings_store_rejects_unknown_and_invalid_values(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    try:
        store.set_override("WUWA_CHAT_API_KEY", "sk-xxx")
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown key")

    try:
        store.set_override("WUWA_CHAT_TEMPERATURE", "9.9")
    except ValueError as exc:
        assert "0.0-2.0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for invalid range")
    assert "WUWA_CHAT_API_KEY" not in SETTABLE_KEYS


def test_settings_store_nicknames_and_interactions(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    assert store.add_nickname("岸宝") is True
    assert store.add_nickname("岸宝") is False
    assert store.add_nickname("守岸人") is True
    assert store.list_nicknames() == ["岸宝", "守岸人"]
    assert store.remove_nickname("岸宝") is True

    assert store.interaction_increment("42") == 1
    assert store.interaction_count("42") == 1
    assert store.list_interaction_senders() == ["42"]

    reloaded = RuntimeSettingsStore(tmp_path / "settings.json")
    assert reloaded.list_nicknames() == ["守岸人"]
    assert reloaded.interaction_count("42") == 1


def test_runtime_admin_result_requires_admin(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    config = Config()

    denied = build_runtime_admin_result(
        store,
        config,
        request_id="req_admin",
        actor_roles=["user"],
        command_text="list",
    )
    assert denied.audit_tags == ["runtime_admin", "permission_denied"]
    assert "管理员" in denied.body

    allowed = build_runtime_admin_result(
        store,
        config,
        request_id="req_admin",
        actor_roles=["admin", "user"],
        command_text="set WUWA_CHAT_TEMPERATURE 0.3",
    )
    assert "0.3" in allowed.body
    assert store.get_or("WUWA_CHAT_TEMPERATURE", None) == 0.3


def test_alert_content_has_five_elements():
    alert = AlertContent(
        title="测试预警",
        what_happened="cookie 过期",
        impact="来源抓取会失败",
        fix_suggestion="重新登录",
        location="wuwa.credential_check",
        occurred_at="2026-07-20 10:00:00 UTC",
    )

    message = alert.format_message()
    assert "时间：2026-07-20 10:00:00 UTC" in message
    assert "位置：wuwa.credential_check" in message
    assert "发生了什么：cookie 过期" in message
    assert "影响：来源抓取会失败" in message
    assert "建议处理：重新登录" in message


def test_alert_check_result_requires_admin():
    result = build_alert_check_result(
        Config(),
        request_id="req_alert",
        actor_roles=["user"],
    )
    assert result.audit_tags == ["runtime_admin", "permission_denied"]


def test_null_render_backend():
    backend = build_render_backend("")
    assert isinstance(backend, NullRenderBackend)
    assert backend.available is False
    assert backend.render_card({"html": "<p>x</p>"}) is None


def test_group_digest_provider_reads_group_scope(tmp_path):
    import sqlite3

    db_path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE conversation_turns ("
        "request_id TEXT, platform TEXT, adapter TEXT, bot_id TEXT, "
        "session_id TEXT, sender_id TEXT, role TEXT, text TEXT, created_at TEXT)"
    )
    rows = [
        ("req1", "onebot", "v11", "bot", "group:10001", "a", "user", "群里的话题一", "2026-07-20T10:00:00+00:00"),
        ("req2", "onebot", "v11", "bot", "group:10001", "b", "user", "群里的话题二", "2026-07-20T10:01:00+00:00"),
        ("req3", "onebot", "v11", "bot", "private:42", "a", "user", "私聊内容不应出现", "2026-07-20T10:02:00+00:00"),
    ]
    connection.executemany(
        "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()

    provider = SQLiteGroupDigestProvider(db_path, max_turns=10, max_chars=500)
    context = provider.load("req_digest", "10001", "a")

    assert context.enabled is True
    assert "群里的话题一" in context.summary
    assert "群里的话题二" in context.summary
    assert "私聊内容不应出现" not in context.summary


def test_build_shared_group_provider_defaults_off():
    provider = build_shared_group_context_provider(Config())

    context = provider.load("req_shared", "1", "42")
    assert context.enabled is False
