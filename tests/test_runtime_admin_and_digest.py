
from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    build_alert_check_result,
    build_runtime_admin_result,
)
from plugins.bot_unified_runtime.character.shared_export import (
    NullSharedConversationExportProvider,
    SQLiteSharedConversationExporter,
)
from plugins.bot_unified_runtime.character.shared_group import (
    SQLiteGroupDigestProvider,
    build_shared_group_context_provider,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.output.render_backends import (
    NullRenderBackend,
    build_render_backend,
)
from plugins.bot_unified_runtime.runtime.alerts import (
    AlertContent,
)
from plugins.bot_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    InstanceSettingsManager,
    RuntimeSettingsStore,
)


def test_settings_store_set_get_reset_persists(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    assert store.set_override("BOT_CHAT_TEMPERATURE", "0.4") == 0.4
    assert store.get_or("BOT_CHAT_TEMPERATURE", None) == 0.4
    assert store.list_overrides() == {"BOT_CHAT_TEMPERATURE": 0.4}

    reloaded = RuntimeSettingsStore(tmp_path / "settings.json")
    assert reloaded.get_or("BOT_CHAT_TEMPERATURE", None) == 0.4
    assert reloaded.reset_override() == 1
    assert reloaded.get_or("BOT_CHAT_TEMPERATURE", None) is None


def test_settings_store_rejects_unknown_and_invalid_values(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    try:
        store.set_override("BOT_CHAT_API_KEY", "sk-xxx")
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown key")

    try:
        store.set_override("BOT_CHAT_TEMPERATURE", "9.9")
    except ValueError as exc:
        assert "0.0-2.0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for invalid range")
    assert "BOT_CHAT_API_KEY" not in SETTABLE_KEYS


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


def test_settings_store_group_policy_lists_persist(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")

    # 逗号/分号/空格混合分隔，且 JSON 数组都能解析为群号列表。
    assert store.set_override("BOT_GROUP_BLACK1", "100;200, 300") == ["100", "200", "300"]
    assert store.set_override("BOT_GROUP_WHITE2", '["700","800"]') == ["700", "800"]

    reloaded = RuntimeSettingsStore(tmp_path / "settings.json")
    assert reloaded.get_or("BOT_GROUP_BLACK1", None) == ["100", "200", "300"]
    assert reloaded.get_or("BOT_GROUP_WHITE2", None) == ["700", "800"]

    # 非数字群号必须拒绝。
    try:
        store.set_override("BOT_GROUP_WHITE1", "abc")
    except ValueError as exc:
        assert "群号" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for non-numeric group id")

    # 空串 = 清空该档（仍持久化空列表，覆盖 .env 的静态配置）。
    assert store.set_override("BOT_GROUP_WHITE1", "") == []
    reloaded_again = RuntimeSettingsStore(tmp_path / "settings.json")
    assert reloaded_again.get_or("BOT_GROUP_WHITE1", None) == []


def test_normalize_group_policy_mode_aliases():
    from plugins.bot_unified_runtime.runtime.settings import normalize_group_policy_mode

    assert normalize_group_policy_mode("black1") == "BOT_GROUP_BLACK1"
    assert normalize_group_policy_mode("黑名单2") == "BOT_GROUP_BLACK2"
    assert normalize_group_policy_mode("黑名單一") == "BOT_GROUP_BLACK1"
    assert normalize_group_policy_mode("WHITE_2") == "BOT_GROUP_WHITE2"
    assert normalize_group_policy_mode("白1") == "BOT_GROUP_WHITE1"
    assert normalize_group_policy_mode("") is None
    assert normalize_group_policy_mode("unknown") is None
def test_runtime_admin_result_requires_admin(tmp_path):
    manager = InstanceSettingsManager(tmp_path)
    config = Config()

    denied = build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req_admin",
        actor_roles=["user"],
        command_text="list",
    )
    assert denied.audit_tags == ["runtime_admin", "permission_denied"]
    assert "管理员" in denied.body

    allowed = build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req_admin",
        actor_roles=["admin", "user"],
        command_text="set BOT_CHAT_TEMPERATURE 0.3",
    )
    assert "0.3" in allowed.body
    assert manager.get("default").get_or("BOT_CHAT_TEMPERATURE", None) == 0.3


def test_runtime_admin_targets_other_instance(tmp_path):
    manager = InstanceSettingsManager(tmp_path)
    config = Config()

    result = build_runtime_admin_result(
        manager,
        "shorekeeper",
        config,
        request_id="req_admin",
        actor_roles=["admin", "user"],
        command_text="nickname add 艾弥斯 --instance aimias",
    )
    assert "aimias" in result.body
    assert manager.get("aimias").list_nicknames() == ["艾弥斯"]
    assert manager.get("shorekeeper").list_nicknames() == []
    assert manager.list_instances() == ["aimias"]


def test_alert_content_has_five_elements():
    alert = AlertContent(
        title="测试预警",
        what_happened="cookie 过期",
        impact="来源抓取会失败",
        fix_suggestion="重新登录",
        location="bot.credential_check",
        occurred_at="2026-07-20 10:00:00 UTC",
    )

    message = alert.format_message()
    assert "时间：2026-07-20 10:00:00 UTC" in message
    assert "位置：bot.credential_check" in message
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


def test_group_digest_excludes_command_replies(tmp_path):
    import sqlite3

    db_path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE conversation_turns ("
        "request_id TEXT, platform TEXT, adapter TEXT, bot_id TEXT, "
        "session_id TEXT, sender_id TEXT, role TEXT, text TEXT, "
        "created_at TEXT, kind TEXT)"
    )
    rows = [
        ("req1", "onebot", "v11", "bot", "group:10001", "a", "user", "群里的话题", "2026-07-20T10:00:00+00:00", "chat"),
        ("req2", "onebot", "v11", "bot", "group:10001", "bot", "assistant", "人格化回复内容", "2026-07-20T10:01:00+00:00", "chat"),
        ("req3", "onebot", "v11", "bot", "group:10001", "bot", "assistant", "今天天气 30°C 多云", "2026-07-20T10:02:00+00:00", "command"),
        ("req4", "onebot", "v11", "bot", "group:10001", "bot", "assistant", "运行时状态：enabled", "2026-07-20T10:03:00+00:00", "command"),
    ]
    connection.executemany(
        "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()

    provider = SQLiteGroupDigestProvider(db_path, max_turns=20, max_chars=600)
    context = provider.load("req_digest", "10001", "a")

    assert context.enabled is True
    assert "群里的话题" in context.summary
    assert "人格化回复内容" in context.summary
    assert "今天天气" not in context.summary
    assert "运行时状态" not in context.summary


def test_shared_export_redacts_and_filters(tmp_path):
    import sqlite3

    db_path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE conversation_turns ("
        "request_id TEXT, platform TEXT, adapter TEXT, bot_id TEXT, "
        "session_id TEXT, sender_id TEXT, role TEXT, text TEXT, "
        "created_at TEXT, kind TEXT)"
    )
    rows = [
        ("req1", "onebot", "v11", "bot", "group:10001", "a", "user", "群聊内容 api_key=secret", "2026-07-20T10:00:00+00:00", "chat"),
        ("req2", "onebot", "v11", "bot", "group:10001", "bot", "assistant", "群聊回复", "2026-07-20T10:01:00+00:00", "chat"),
        ("req3", "onebot", "v11", "bot", "private:42", "a", "user", "私聊内容不应导出", "2026-07-20T10:02:00+00:00", "chat"),
        ("req4", "onebot", "v11", "bot", "group:10001", "bot", "assistant", "天气查询结果", "2026-07-20T10:03:00+00:00", "command"),
    ]
    connection.executemany(
        "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()

    exporter = SQLiteSharedConversationExporter(db_path)
    records = exporter.export(limit=20)

    assert len(records) == 2
    assert all(record.session_kind == "group" for record in records)
    assert "secret" not in records[0].redacted_text
    texts = " ".join(record.redacted_text for record in records)
    assert "私聊内容不应导出" not in texts
    assert "天气查询结果" not in texts

    # 增量游标：用最新一条的 record_id 继续拉，应拿到更早的那条。
    newest_id = records[0].record_id
    older = exporter.export(limit=20, after_record_id=newest_id)
    assert older and all(record.record_id != newest_id for record in older)

    null_provider = NullSharedConversationExportProvider()
    assert null_provider.export() == []


def test_admin_model_command_switches_preset(tmp_path):
    manager = InstanceSettingsManager(tmp_path)
    config = Config(
        bot_chat_model="default-model",
        bot_model_presets={"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"},
    )

    result = build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req_model",
        actor_roles=["admin", "user"],
        command_text="model set flash",
    )
    assert "deepseek-v4-flash" in result.body
    # 新语义：覆盖值存预设 id；真正解析成完整模型名由 ModelRouter 完成。
    assert manager.get("default").get_or("BOT_CHAT_MODEL", None) == "flash"

    listing = build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req_model",
        actor_roles=["admin", "user"],
        command_text="model list",
    )
    assert "deepseek-v4-flash" in listing.body
    assert "deepseek-v4-pro" in listing.body

    reset = build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id="req_model",
        actor_roles=["admin", "user"],
        command_text="model reset",
    )
    assert "default-model" in reset.body
    assert manager.get("default").get_or("BOT_CHAT_MODEL", None) is None
