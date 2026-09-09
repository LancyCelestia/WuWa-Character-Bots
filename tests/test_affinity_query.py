"""好感度查询能力回归（C组，独立命名）：docs/affinity-design.md §9 验收口径。

覆盖：群镜像行与主行一致、排行榜排序与上限、双向分值（含零信号默认 0.5）、
私聊/群聊/算法三种查询结果、帮助条目公开且唯一、卡片模板 HTML 关键元素。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import DynamicAffinityStore
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _store(tmp_path):
    return DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_Clock())


# ---------------------------------------------------------------------------
# store 层：群镜像 / 排行榜 / 表达倾向
# ---------------------------------------------------------------------------

def test_observe_mirrors_group_rows_in_sync(tmp_path) -> None:
    store = _store(tmp_path)
    store.observe("u1", "positive", group_id="g1", display_name="阿澄")
    store.observe("u1", "insult", group_id="g1", display_name="阿澄")
    rows = store.leaderboard("g1")
    assert len(rows) == 1
    row = rows[0]
    assert row["sender_id"] == "u1"
    assert row["display_name"] == "阿澄"
    assert abs(row["affinity"] - store.snapshot("u1")["affinity"]) < 1e-9
    # 未带 group_id 的 observe 也应同步进已镜像的群
    store.observe("u1", "positive")
    assert abs(store.leaderboard("g1")[0]["affinity"] - store.snapshot("u1")["affinity"]) < 1e-9


def test_leaderboard_orders_desc_and_respects_limit(tmp_path) -> None:
    store = _store(tmp_path)
    store.observe("high", "neutral", delta_override=0.65, group_id="g1", display_name="高分")
    store.observe("low", "insult", group_id="g1", display_name="低分")
    store.observe("low", "insult", group_id="g1", display_name="低分")
    store.observe("low", "insult", group_id="g1", display_name="低分")
    store.observe("mid", "neutral", group_id="g1", display_name="中分")
    rows = store.leaderboard("g1", limit=2)
    assert [r["sender_id"] for r in rows] == ["high", "mid"]
    assert rows[0]["score"] >= rows[1]["score"]
    assert rows[0]["tier"] == "close"
    full = store.leaderboard("g1")
    assert [r["sender_id"] for r in full] == ["high", "mid", "low"]
    assert full[2]["tier"] == "distant"


def test_sentiment_ratio_defaults_and_weights(tmp_path) -> None:
    store = _store(tmp_path)
    assert abs(store.sentiment_for("nobody") - 0.1) < 1e-9  # 零信号默认与初始好感一致（10 分）
    for _ in range(3):
        store.observe("u1", "positive")
    assert abs(store.sentiment_for("u1") - 1.0) < 1e-9
    store.observe("u2", "positive")
    store.observe("u2", "insult")  # 权重 2
    # pos / (pos + neg + 2*insult) = 1 / 3
    assert abs(store.sentiment_for("u2") - (1.0 / 3.0)) < 1e-9


# ---------------------------------------------------------------------------
# capability 层：命令识别与三种结果
# ---------------------------------------------------------------------------

def _message(text: str, *, group_id: str | None = None) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"group:{group_id}" if group_id else "private:u1",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id="u1",
        sender_display_name="阿澄",
        group_id=group_id,
        plain_text=text,
    )


def test_affinity_command_detection() -> None:
    from plugins.bot_unified_runtime.capabilities.affinity import (
        is_affinity_command,
        parse_affinity_query,
    )

    assert is_affinity_command("好感度")
    assert is_affinity_command("好感查看")
    assert is_affinity_command("/bot 好感度 我") or is_affinity_command("好感度 我")
    assert is_affinity_command("好感度 算法")
    assert not is_affinity_command("好感消失了")
    assert not is_affinity_command("今天天气好不好")
    assert parse_affinity_query("好感度 我") == "我"
    assert parse_affinity_query("好感度 算法") == "算法"
    assert parse_affinity_query("好感度") == ""


def test_private_result_shows_both_directions(tmp_path) -> None:
    from plugins.bot_unified_runtime.capabilities.affinity import (
        build_affinity_capability,
    )
    from plugins.bot_unified_runtime.character.affinity import per_user_factor

    store = _store(tmp_path)
    store.observe("u1", "positive")
    capability = build_affinity_capability(affinity_store=store)
    result = capability(_message("好感度"), _decision())
    assert result.capability_id == "bot.affinity"
    # 双方向：机器人对用户 + 用户对机器人，且都有具体数值
    assert "守岸人对你" in result.body
    assert "你对守岸人" in result.body
    bot_score = round((0.1 + 0.02 * per_user_factor("u1")) * 100, 1)
    assert f"{bot_score:.1f}" in result.body
    assert "100.0" in result.body
    assert "算法" in result.body


def test_group_result_lists_impressed_members_and_highlights_me(tmp_path) -> None:
    from plugins.bot_unified_runtime.capabilities.affinity import (
        build_affinity_capability,
    )

    store = _store(tmp_path)
    store.observe("u1", "positive", group_id="g1", display_name="阿澄")
    store.observe("u2", "insult", group_id="g1", display_name="低分侠")
    capability = build_affinity_capability(affinity_store=store)
    result = capability(_message("好感度", group_id="g1"), _decision())
    assert "好感榜" in result.body
    assert "阿澄" in result.body
    assert "低分侠" in result.body
    assert result.privacy_level is not None


def test_algorithm_query_returns_dynamic_personal_rules(tmp_path) -> None:
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.capabilities.affinity import (
        build_affinity_capability,
    )
    from plugins.bot_unified_runtime.character.affinity import per_user_factor

    store = _store(tmp_path)
    backend = SimpleNamespace(available=True, render_card=lambda payload: b"png-bytes")
    capability = build_affinity_capability(
        affinity_store=store, render_backend=backend, card_dir=str(tmp_path)
    )
    result = capability(_message("好感度 算法"), _decision())
    assert result.kind == "mixed"
    assert result.images and result.images[0]["file"]
    assert "加分" in result.body and "波动" in result.body and "扣分" in result.body
    assert "因人而异" in result.body
    # 个人精确步长：按当前分（初始 10）与个人系数给出
    m = per_user_factor("u1")
    assert f"+{2 * m:.2f}" in result.body
    # 渲染落盘为内容摘要文件名
    assert "affinity_" in result.images[0]["file"]


def _decision():
    from plugins.bot_unified_runtime.contracts import BotDecision, SessionType

    return BotDecision(
        request_id="req-test",
        should_respond=True,
        mode="command",
        trigger="好感度",
        capability_id="bot.affinity",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


# ---------------------------------------------------------------------------
# 帮助条目与模板
# ---------------------------------------------------------------------------

def test_base_router_routes_affinity_commands() -> None:
    from plugins.bot_unified_runtime.runtime.base_router import ROUTE_RULES

    def route(text: str):
        for rule in ROUTE_RULES:
            decision = rule.matcher(text, None, None) if rule.matcher else None
            if decision is not None:
                return decision
        return None

    for text in ("好感度", "好感查看", "查询好感", "好感度 我", "好感度 算法"):
        decision = route(text)
        assert decision is not None, text
        assert decision.capability_id == "bot.affinity"
    stray = route("好感消失了")
    assert stray is None or stray.capability_id != "bot.affinity"


def test_help_entry_exists_public_and_unique() -> None:
    from plugins.bot_unified_runtime.capabilities.echo import (
        _HELP_ENTRIES,
        _PUBLIC_HELP_TOPICS,
    )

    topics = [entry["topic"] for entry in _HELP_ENTRIES]
    assert topics.count("好感度") == 1
    entry = next(item for item in _HELP_ENTRIES if item["topic"] == "好感度")
    assert "好感度" in _PUBLIC_HELP_TOPICS
    assert "算法" in entry["detail"]
    assert any("好感度 我" in line for line in entry["lines"])
    # 既有可见性缺陷修复：admin_only=False 的条目必须对普通用户可见
    assert "吃什么" in _PUBLIC_HELP_TOPICS
    assert "偷表情" in _PUBLIC_HELP_TOPICS


def test_template_renders_scores_and_highlights() -> None:
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        render_affinity_card_html,
    )

    group_payload = {
        "pc": "#607080",
        "title": "好感度",
        "subtitle": "测试群 · 有印象 3 人",
        "mode": "group",
        "me_id": "u1",
        "rows": [
            {"sender_id": "u1", "display_name": "阿澄", "score": 88.0, "tier": "亲近"},
            {"sender_id": "u2", "display_name": "中", "score": 50.0, "tier": "友善"},
            {"sender_id": "u3", "display_name": "冷", "score": 12.5, "tier": "疏离"},
        ],
    }
    html = render_affinity_card_html(group_payload)
    assert "88.0" in html and "12.5" in html
    assert "hot" in html and "cold" in html
    assert "me" in html
    assert "var(--pc)" in html

    private_payload = {
        "pc": "#607080",
        "title": "好感度",
        "subtitle": "私聊",
        "mode": "private",
        "bot_to_user": {"score": 52.0, "tier": "友善", "bar": 52.0},
        "user_to_bot": {"score": 100.0, "tier": "热情", "bar": 100.0},
        "rules": ["+ 感谢夸奖问候 +2", "± 玩笑闲置 波动", "- 抱怨辱骂 扣分"],
    }
    html2 = render_affinity_card_html(private_payload)
    assert "守岸人对你" in html2
    assert "你对守岸人" in html2
    assert "52.0" in html2
