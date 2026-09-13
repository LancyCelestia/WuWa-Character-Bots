"""帮助页补全回归：identity/quirk 管理命令条目与新配置键可发现性（Task 4）。"""

from __future__ import annotations

from plugins.bot_unified_runtime.capabilities.echo import (
    _HELP_CATEGORIES,
    _PUBLIC_HELP_TOPICS,
    HELP_ENTRIES,
    build_help_result,
    normalize_help_topic,
)

ADMIN_KEYS_QUIET_HOURS = (
    "BOT_QUIET_HOURS_ENABLED",
    "BOT_QUIET_HOURS_START",
    "BOT_QUIET_HOURS_END",
    "BOT_QUIET_HOURS_TIMEZONE",
    "BOT_QUIET_HOURS_SESSION_TYPES",
    "BOT_QUIET_HOURS_BYPASS_ROLES",
)
ADMIN_KEYS_GROUP_LIMITS = (
    "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR",
    "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE",
    "BOT_RATE_LIMIT_EMOTION_EXEMPT",
    "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED",
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
)
ADMIN_KEYS_FORWARD = (
    "BOT_RENDER_FORWARD_MIN_NODES",
    "BOT_RENDER_FORWARD_MIN_CHARS",
    "BOT_RENDER_FORWARD_MAX_NODES",
    "BOT_RENDER_FORWARD_NODE_CHARS",
)
ADMIN_KEYS_SWITCHES = (
    "BOT_SEND_QUEUE_ENABLED",
    "BOT_SEND_QUEUE_WORKER_ENABLED",
    "BOT_AUDIT_ENABLED",
    "BOT_RECEIPTS_ENABLED",
    "BOT_DIAGNOSTICS_ENABLED",
)
ADMIN_KEYS_VISION_VIDEO = (
    "BOT_VISION_ENABLED",
    "BOT_VISION_MODE",
    "BOT_VIDEO_UNDERSTANDING_ENABLED",
)
ADMIN_KEYS_DIGEST = (
    "BOT_SHARED_GROUP_CONTEXT_ENABLED",
    "BOT_GROUP_DIGEST_LIST_MODE",
    "BOT_GROUP_DIGEST_WHITELIST",
    "BOT_GROUP_DIGEST_BLACKLIST",
)


def _entry(topic: str):
    matches = [entry for entry in HELP_ENTRIES if entry["topic"] == topic]
    assert len(matches) == 1, f"topic {topic} 出现 {len(matches)} 次"
    return matches[0]


def test_identity_and_quirk_entries_exist_and_are_admin_only() -> None:
    for topic, alias in (("身份", "identity"), ("怪癖", "quirk")):
        entry = _entry(topic)
        assert entry["admin_only"] is True
        assert topic not in _PUBLIC_HELP_TOPICS
        assert normalize_help_topic(alias) == topic
        blob = str(entry)
        assert "仅管理员" in blob or "管理员" in blob
    assert "/bot identity set" in str(_entry("身份"))
    assert "/bot identity tag" in str(_entry("身份"))
    assert "/bot identity clear" in str(_entry("身份"))
    assert "/bot quirk approve" in str(_entry("怪癖"))
    assert "/bot quirk retire" in str(_entry("怪癖"))
    assert "pending_review" in str(_entry("怪癖")) or "待审" in str(_entry("怪癖"))


def test_identity_and_quirk_depth_page_and_public_gate() -> None:
    admin_page = build_help_result(request_id="t4-admin", query="identity", is_admin=True)
    assert admin_page.kind == "text"
    assert "/bot identity set <昵称>" in admin_page.body
    assert "防 OOC" in admin_page.body or "人格不变" in admin_page.body

    public_page = build_help_result(request_id="t4-public", query="identity", is_admin=False)
    assert "没有找到" in public_page.body


def test_new_config_keys_documented_and_settable() -> None:
    from plugins.bot_unified_runtime.runtime.settings import SETTABLE_KEYS

    blob = str(HELP_ENTRIES)
    hot_keys = (
        ADMIN_KEYS_QUIET_HOURS
        + ADMIN_KEYS_GROUP_LIMITS
        + ADMIN_KEYS_FORWARD
        + ADMIN_KEYS_VISION_VIDEO
        + ADMIN_KEYS_DIGEST
    )
    for key in hot_keys:
        assert key in blob, f"{key} 未写进帮助"
    for key in (
        ADMIN_KEYS_QUIET_HOURS
        + ADMIN_KEYS_GROUP_LIMITS
        + ADMIN_KEYS_FORWARD
        + ADMIN_KEYS_VISION_VIDEO
        + ADMIN_KEYS_DIGEST
    ):
        assert key in SETTABLE_KEYS, f"{key} 应可经 /bot runtime set 修改"
    for key in ADMIN_KEYS_SWITCHES:
        assert key in blob, f"{key} 未写进帮助"
        assert key not in SETTABLE_KEYS, f"{key} 实为 .env 键，不应宣称可热改"
    # 真实校验边界入文，防止"0=关闭"语义回退。
    assert "0=该帽不生效" in blob
    assert "whitelist|blacklist|off|all" in blob
    assert "relay|direct" in blob


def test_market_news_divination_entries_present() -> None:
    for topic in ("行情", "快报", "占卜"):
        _entry(topic)


def test_new_topics_categorized_as_admin() -> None:
    categories = {name: set(topics) for name, topics in _HELP_CATEGORIES}
    for topic in ("身份", "怪癖", "限流", "合并转发", "群摘要", "视频理解", "运行开关"):
        assert topic in categories["管理员专属"], f"{topic} 未归入管理员专属分类"
    topics = [entry["topic"] for entry in HELP_ENTRIES]
    assert len(topics) == len(set(topics)), "帮助主题出现重复"


def test_alias_map_stays_collision_free() -> None:
    from plugins.bot_unified_runtime.capabilities.echo import (
        _HELP_ALIAS_MAP,
        _HELP_ENTRY_META,
    )

    seen: dict[str, str] = {}
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            lowered = alias.lower()
            assert lowered not in seen, f"别名 {alias} 在 {seen[lowered]} 与 {entry['topic']} 间冲突"
            seen[lowered] = entry["topic"]
    # T5 结构修复（fix-trae2）：映射口径=aliases ∪ META 触发词（aliases 优先）。
    for entry in HELP_ENTRIES:
        meta = _HELP_ENTRY_META.get(entry["topic"], {})
        for field in ("triggers_nickname", "triggers_nl"):
            for word in meta.get(field) or ():
                seen.setdefault(str(word).strip().lower(), entry["topic"])
    assert set(_HELP_ALIAS_MAP) == set(seen)


def test_q1_dead_symbols_removed() -> None:
    """Q1 死代码清扫防复现：_help_index_line / route_bot_command 及其专属常量已删。"""
    import plugins.bot_unified_runtime.capabilities.echo as echo_mod

    for gone in ("_help_index_line", "route_bot_command", "_HELP_INDEX_COMMAND_TOPICS"):
        assert not hasattr(echo_mod, gone), f"已删除的死代码符号 {gone} 不得回归"
