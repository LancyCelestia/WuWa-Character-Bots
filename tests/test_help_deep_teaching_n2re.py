"""帮助深度教学化回归（task N2re）。

覆盖面：
1. 每模块条目存在性（含近期新增命令）；
2. 四要素（作用/参数/内容/意义）字段完整性——每条 detail 非空且含四要素；
3. 抽样参数范围与代码/配置校验一致（日志条数钳制、recent 上限、
   市场过滤词、记忆 sensitivity、会话身份标签数、群摘要推送键）；
4. 权限标注与 _PUBLIC_HELP_TOPICS / admin_only 一致。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _HELP_ALIAS_MAP,
    _HELP_CATEGORIES,
    _PUBLIC_HELP_TOPICS,
    HELP_ENTRIES,
    build_help_result,
    normalize_help_topic,
)

# 近期新增/改版模块：身份、怪癖、市场（B股/莫斯科）、新闻、占卜（藏干）、
# 随机图、提醒（列表/取消）、每日通讯总结推送开关。
_RECENT_TOPICS = ("身份", "怪癖", "行情", "快报", "占卜", "随机图", "提醒", "群摘要")
_ALL_TOPICS = tuple(entry["topic"] for entry in HELP_ENTRIES)


def _entry(topic: str):
    matches = [entry for entry in HELP_ENTRIES if entry["topic"] == topic]
    assert len(matches) == 1, f"topic {topic} 出现 {len(matches)} 次"
    return matches[0]


def _blob(topic: str) -> str:
    return str(_entry(topic))


def test_every_entry_structure_complete() -> None:
    for entry in HELP_ENTRIES:
        topic = entry["topic"]
        assert topic, "topic 为空"
        assert entry.get("aliases"), f"{topic} 缺 aliases"
        assert entry.get("index"), f"{topic} 缺 index"
        assert entry.get("title_line"), f"{topic} 缺 title_line"
        lines = entry.get("lines")
        assert isinstance(lines, list) and lines, f"{topic} lines 为空"
        assert all(str(line).strip() for line in lines), f"{topic} 有空行"
        assert str(entry.get("detail") or "").strip(), f"{topic} detail 为空"


def test_every_detail_covers_four_elements() -> None:
    for element in ("作用", "参数", "内容", "意义"):
        missing = [
            entry["topic"]
            for entry in HELP_ENTRIES
            if element not in str(entry.get("detail") or "")
        ]
        assert not missing, f"四要素缺「{element}」：{missing}"


def test_permission_annotations_match_visibility() -> None:
    for entry in HELP_ENTRIES:
        blob = str(entry)
        if entry.get("admin_only"):
            assert "仅管理员" in blob, f"{entry['topic']} 标注 admin_only 但未写 仅管理员"
            assert entry["topic"] not in _PUBLIC_HELP_TOPICS
        else:
            assert "全员" in blob or "任何人" in blob, f"{entry['topic']} 未标注 全员"
            assert entry["topic"] in _PUBLIC_HELP_TOPICS, (
                f"{entry['topic']} 无管理员门却不在公开帮助里"
            )


def test_all_topics_categorized_and_unique() -> None:
    categorized = {topic for _, topics in _HELP_CATEGORIES for topic in topics}
    assert categorized == set(_ALL_TOPICS), (
        f"孤儿/幽灵主题：{categorized.symmetric_difference(_ALL_TOPICS)}"
    )
    assert len(_ALL_TOPICS) == len(set(_ALL_TOPICS))


def test_recent_new_commands_covered() -> None:
    for topic in _RECENT_TOPICS:
        assert topic in _ALL_TOPICS
    identity = _blob("身份")
    for token in ("/bot identity show", "/bot identity set <昵称>", "/bot identity tag", "/bot identity clear"):
        assert token in identity
    quirk = _blob("怪癖")
    for token in ("/bot quirk list", "/bot quirk approve", "/bot quirk retire", "/bot quirk add", "待审"):
        assert token in quirk
    market = _blob("行情")
    for token in ("B股", "莫斯科", "俄罗斯"):
        assert token in market
    news = _blob("快报")
    for token in ("科技", "财经", "国际", "早报", "晚报"):
        assert token in news
    divination = _blob("占卜")
    assert "藏干" in divination
    randpic = _blob("随机图")
    assert "BOT_RANDPIC_DIRS" in randpic
    reminder = _blob("提醒")
    for token in ("提醒列表", "取消提醒"):
        assert token in reminder
    digest = _blob("群摘要")
    assert "BOT_GROUP_DIGEST_PUSH_ENABLED" in digest
    assert "BOT_GROUP_DIGEST_PUSH_TIME" in digest
    assert "21:30" in digest


def test_documented_hot_keys_match_settable_keys() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        SETTABLE_KEYS,
    )

    blob = str(HELP_ENTRIES)
    for key in (
        "BOT_QUIET_HOURS_ENABLED", "BOT_QUIET_HOURS_START", "BOT_QUIET_HOURS_END",
        "BOT_QUIET_HOURS_TIMEZONE", "BOT_QUIET_HOURS_SESSION_TYPES", "BOT_QUIET_HOURS_BYPASS_ROLES",
        "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR", "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE",
        "BOT_RATE_LIMIT_EMOTION_EXEMPT",
        "BOT_VISION_ENABLED", "BOT_VISION_MODE", "BOT_VIDEO_UNDERSTANDING_ENABLED",
    ):
        assert key in blob, f"{key} 未写进帮助"
        assert key in SETTABLE_KEYS, f"{key} 应可 /bot runtime set"
    # .env-only / 装配期冻结键：文档要写，但绝不能宣称可热改。每日推送两键与
    # AUTO_REPLY_ENABLED / SHARED_GROUP_CONTEXT_ENABLED 是审查 C-09 治理；抽签
    # 概率、合并转发阈值、群摘要名单三族是 2026-09-15 热改面审计新实锤的装配期
    # 快照死开关（写入成功但行为不变），已移出 SETTABLE_KEYS，runtime set 明确
    # 拒绝并提示重启。
    for key in (
        "BOT_GROUP_DIGEST_PUSH_ENABLED", "BOT_GROUP_DIGEST_PUSH_TIME",
        "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "BOT_SHARED_GROUP_CONTEXT_ENABLED",
        "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
        "BOT_RENDER_FORWARD_MIN_NODES", "BOT_RENDER_FORWARD_MIN_CHARS",
        "BOT_RENDER_FORWARD_MAX_NODES", "BOT_RENDER_FORWARD_NODE_CHARS",
        "BOT_GROUP_DIGEST_LIST_MODE",
        "BOT_GROUP_DIGEST_WHITELIST", "BOT_GROUP_DIGEST_BLACKLIST",
    ):
        assert key in blob, f"{key} 未写进帮助"
        assert key not in SETTABLE_KEYS, f"{key} 实为 .env+重启键（装配期冻结），不得宣称可热改"


def test_documented_ranges_match_code_clamps() -> None:
    class _FakeDiagnostics:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def list_recent(self, limit: int):
            self.calls.append(limit)
            return []

    class _FakeReceipts:
        def list_receipts(self):
            return []

    class _FakeAudits:
        def list_records(self):
            return []

    # /bot recent [数量]：文档宣称 1-20（默认 5）——用越界输入验证真实钳制。
    diagnostics = _FakeDiagnostics()
    from plugins.bot_unified_runtime.domains.ops.admin.debug import (
        build_recent_query_result,
    )

    build_recent_query_result(
        diagnostics,
        _FakeReceipts(),
        _FakeAudits(),
        request_id="n2re",
        actor_roles=["admin"],
        query="999",
    )
    assert diagnostics.calls == [20]

    class _FakeLog:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def read_recent(self, limit: int, min_level: str):
            self.calls.append(limit)
            return ["line"]

    # /bot logs [数量]：文档宣称 1-200——验证真实钳制。
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_logs import (
        build_logs_query_result,
    )

    log_store = _FakeLog()
    build_logs_query_result(log_store, request_id="n2re", actor_roles=["admin"], level="info", limit=500)
    assert log_store.calls == [200]
    assert "1-200" in _blob("日志")
    assert "1-20" in _blob("最近")


def test_documented_memory_sensitivity_matches_code() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
        MEMORY_SENSITIVITIES,
    )

    blob = _blob("记忆")
    for value in sorted(MEMORY_SENSITIVITIES):
        assert value in blob, f"sensitivity {value} 未写进记忆帮助"


def test_documented_identity_tag_limit_matches_store() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.session_identity import (
        _normalize_tags,
    )

    assert len(_normalize_tags("a,b,c,d,e,f,g,h,i,j")) == 8
    assert "8 个" in _blob("身份")


def test_documented_market_filters_match_registry() -> None:
    from plugins.bot_unified_runtime.capabilities.market import market_filter_secids

    b_shares = market_filter_secids("B股行情")
    moscow = market_filter_secids("莫斯科行情")
    assert b_shares, "B股过滤词失效"
    assert moscow, "莫斯科过滤词失效"
    assert any("IMOEX" in code for code in moscow)


def test_documented_divination_hidden_stems_callable() -> None:
    from plugins.bot_unified_runtime.capabilities.divination import hidden_stems_section

    assert callable(hidden_stems_section)
    assert "藏干" in _blob("占卜")


def test_documented_digest_push_defaults_match_config() -> None:
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    assert config.bot_group_digest_push_enabled is True
    assert config.bot_group_digest_push_time == "21:30"


@pytest.mark.parametrize("query", ["提醒", "行情", "随机图", "记忆", "路由", "搜图", "草稿"])
def test_public_deep_pages_render(query: str) -> None:
    result = build_help_result(request_id="n2re", query=query, is_admin=False)
    assert result.kind == "text"
    for element in ("作用", "参数", "内容", "意义"):
        assert element in result.body


def test_admin_gate_on_deep_pages_unchanged() -> None:
    public = build_help_result(request_id="n2re-a", query="identity", is_admin=False)
    assert "没有找到" in public.body
    admin = build_help_result(request_id="n2re-b", query="quirk", is_admin=True)
    assert "/bot quirk approve" in admin.body


def test_alias_map_still_collision_free() -> None:
    seen: set[str] = set()
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            lowered = alias.lower()
            assert lowered not in seen
            seen.add(lowered)
    # T5 结构修复（fix-trae2）：映射口径=aliases ∪ META 触发词（aliases 优先）。
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _HELP_ENTRY_META,
    )

    for entry in HELP_ENTRIES:
        meta = _HELP_ENTRY_META.get(entry["topic"], {})
        for field in ("triggers_nickname", "triggers_nl"):
            for word in meta.get(field) or ():
                seen.add(str(word).strip().lower())
    assert set(_HELP_ALIAS_MAP) == seen
    for topic in ("随机图", "提醒", "搜图", "群文件", "文件", "日志"):
        assert normalize_help_topic(topic) == topic


@pytest.mark.parametrize("query", ["功能管理", "feature"])
def test_feature_help_teaches_commands_and_preserves_admin_visibility(query: str) -> None:
    entry = _entry("功能管理")
    assert entry["admin_only"] is True
    assert "bot.runtime" in entry["capability"]
    detail = entry["detail"]
    admin_body = build_help_result(
        request_id="feature-help-admin", query=query, is_admin=True,
    ).body
    for command in (
        "/bot feature list", "/bot feature get <ID>",
        "/bot feature enable|disable|reset <ID>",
        "/bot feature preview <ID> on|off|reset",
    ):
        assert command in detail
        assert command in admin_body
    for text in ("作用", "参数", "内容", "意义", "仅管理员", "修改仅限超管", "预览仅限超管"):
        assert text in detail
        assert text in admin_body
    assert "没有找到" in build_help_result(
        request_id="feature-help-public", query=query, is_admin=False,
    ).body
