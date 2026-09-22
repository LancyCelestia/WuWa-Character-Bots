"""好感度查询能力回归（C组，独立命名）：docs/affinity-design.md §9 验收口径。

覆盖：群镜像行与主行一致、排行榜排序与上限、双向分值（含零信号默认 0.5）、
私聊/群聊/算法三种查询结果、帮助条目公开且唯一、卡片模板 HTML 关键元素。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_days(self, days: float) -> None:
        self.now += days * 86400.0


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
    # V2.1 §2.3 滚动预算：override 正向封顶 3 分（0.1→0.13），insult 6h 内只落
    # 2×1 分（0.1→0.08，第 3 发记 0）——排序与 limit 意图不变，档位带数值按新政策更新
    assert rows[0]["tier"] == 0  # 0.13 → 展示 13 → 档 0（原 75→档+3 直通口径已废除）
    full = store.leaderboard("g1")
    assert [r["sender_id"] for r in full] == ["high", "mid", "low"]
    # 低分行：0.1-2×0.01=0.08 → 展示 8 → 档 0（原 -3×0.10×m 直通口径已废除）
    assert full[2]["tier"] == 0


def test_sentiment_ratio_defaults_and_weights(tmp_path) -> None:
    store = _store(tmp_path)
    assert abs(store.sentiment_for("nobody") - 0.1) < 1e-9  # 零信号默认与初始好感一致（10 分）


def test_sentiment_fades_old_insults_faster(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "fade.sqlite3", clock=clock)
    store.observe("u1", "positive")
    store.observe("u1", "insult")
    # 新鲜信号：加权占比 1/(1+2) = 1/3
    assert abs(store.sentiment_for("u1") - (1.0 / 3.0)) < 1e-6
    clock.advance_days(30)
    # 辱骂半衰期 15 天、正向 30 天：旧账淡出后占比回升（宽恕）
    assert abs(store.sentiment_for("u1") - 0.5) < 1e-6
    clock.advance_days(150)
    # 信号全部淡出：回到默认
    assert abs(store.sentiment_for("u1") - 0.1) < 1e-9


def test_leaderboard_decays_stale_scores_for_display_only(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "stale.sqlite3", clock=clock)
    store.observe("u1", "neutral", delta_override=0.65, group_id="g1", display_name="A")
    # V2.1 §2.3：override 正向封顶 3 分 → 0.13（原 0.75 直通口径已废除）
    assert store.leaderboard("g1")[0]["score"] == 13.0
    clock.advance_days(90)
    rows = store.leaderboard("g1")
    # 展示层折算：闲置 90 天向基数 10 衰减一半以上，但不落库、不改真实值
    assert 10.0 < rows[0]["score"] < 30.0
    assert abs(store.snapshot("u1")["affinity"] - 0.13) < 1e-9
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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        build_affinity_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        per_user_factor,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
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

    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        build_affinity_capability,
    )
    store = _store(tmp_path)
    backend = SimpleNamespace(available=True, render_card=lambda payload: b"png-bytes")
    capability = build_affinity_capability(
        affinity_store=store, render_backend=backend, card_dir=str(tmp_path)
    )
    result = capability(_message("好感度 算法"), _decision())
    assert result.kind == "mixed"
    assert result.images and result.images[0]["file"]
    # v5：算法说明定性化（F4 用户裁定——不展示固定加减数值口径）
    assert "升温" in result.body and "降温" in result.body and "第一印象" in result.body
    assert "节奏" in result.body or "因人而异" in result.body
    # 渲染落盘为内容摘要文件名
    assert "affinity_" in result.images[0]["file"]


def test_algorithm_copy_is_v4_linear_eight_tier() -> None:
    # docs §7 算法卡文案：线性全额步长 + 闲置回归 + 印象淡出 + 个人系数 + 红线摘要
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        _TIER_TABLE,
        ALGORITHM_TEXT,
        _rules_chips,
    )
    assert len(_TIER_TABLE) == 8
    assert _TIER_TABLE[0]["label"] == "初识" and _TIER_TABLE[0]["range"] == "[-100, -75)"
    assert _TIER_TABLE[4]["label"] == "友善（基准）" and _TIER_TABLE[4]["range"] == "[0, +25)"
    assert _TIER_TABLE[-1]["label"] == "独一份" and _TIER_TABLE[-1]["range"] == "[+75, +100]"
    # v5 多因素定性文案（F4）：描述多因素连续累积，且不得再出现固定加减数值
    assert "说话的温度" in ALGORITHM_TEXT and "第一印象" in ALGORITHM_TEXT
    assert "相处的时间" in ALGORITHM_TEXT or "相处" in ALGORITHM_TEXT
    assert "+2" not in ALGORITHM_TEXT and "-5" not in ALGORITHM_TEXT
    assert "连续过渡" in ALGORITHM_TEXT
    assert "不辱骂" in ALGORITHM_TEXT  # §4 红线摘要
    # 榜卡/规则 chips 不再出现 v2 遗留的「向 50 回归」
    assert all("向 50 回归" not in chip["text"] for chip in _rules_chips())
    assert any(("回归" in chip["text"] or "回到" in chip["text"]) for chip in _rules_chips())


def test_tier_text_spans_negative_and_positive_scores() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        _tier_text,
    )

    assert _tier_text(-90.0) == "初识"
    assert _tier_text(-30.0) == "微凉"
    assert _tier_text(10.0) == "友善（基准）"
    assert _tier_text(60.0) == "挚友"
    assert _tier_text(100.0) == "独一份"


def test_provider_maps_tiers_to_familiarity_and_injects_self_guard(tmp_path) -> None:
    """docs §5：档 ≥+2 → close、-1..+1 → familiar、≤-2 → stranger；
    人格自守条款追加在态度文本之后（任何档位生效）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        FileCharacterContextProvider,
    )

    store = _store(tmp_path)

    def _relationship_for(sender: str):
        provider = FileCharacterContextProvider(
            persona_profile_id="default",
            persona_display_name="报存",
            persona_version="0",
            persona_files=[],
            knowledge_files=[],
            affinity_store=store,
        )
        bundle = provider.build_context("req-1", sender, f"private:{sender}", "在吗")
        return bundle.relationship_context

    # 目标档位样本直接播种（V2.1 §2.3 滚动预算后，单日经 observe/override 无法
    # 到达 ±25 分档界；familiarity 映射是本测试主旨，播种行不改映射语义）
    import sqlite3

    with sqlite3.connect(tmp_path / "affinity.sqlite3") as connection:
        for sender, affinity in (("p-close", 0.6), ("p-fam", 0.3), ("p-str", -0.6)):
            connection.execute(
                "INSERT OR REPLACE INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
                " VALUES (?, ?, 1, '1970-01-01T00:16:40Z')",
                (sender, affinity),
            )
    # 档0（含基准 10）：带印象标签的非默认记录，预算内 3×positive 落在档 0 带内
    for _ in range(3):
        store.observe("p-base", "positive")                          # 0.1+3 分内增益，档 0

    close = _relationship_for("p-close")
    familiar = _relationship_for("p-fam")
    stranger = _relationship_for("p-str")
    base_tier0 = _relationship_for("p-base")
    assert close.familiarity == "close"
    assert familiar.familiarity == "familiar"
    assert stranger.familiarity == "stranger"
    assert base_tier0.familiarity == "familiar"
    for relationship in (close, familiar, stranger, base_tier0):
        # 人格自守条款：独立一句、任何档位生效
        assert "人格自守" in relationship.attitude
        assert "猪狗不如" in relationship.attitude


def test_content_safety_persona_degradation_reframe_regardless_of_admin() -> None:
    # docs §6：指向 bot 本体的贬低人格语 → reframe；2026-09-17 起管理员
    # 不再放宽（软类别概念随内容政策移除，侮辱/贬低对所有人拦截面一致）。
    from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
        assess_public_content,
    )

    hits = (
        "你就是垃圾",
        "你就是个废物",
        "你猪狗不如",
        "你这家伙真卑微",
        "你太垃圾了",
        "你个废物点心",
    )
    for text in hits:
        assessment = assess_public_content(text, session_type="private")
        assert assessment.category == "persona_degradation", text
        assert assessment.action == "reframe", text
    admin = assess_public_content("你就是垃圾", session_type="private", admin=True)
    assert admin.category == "persona_degradation"
    assert admin.action == "reframe"
    # 不误伤：谈垃圾/抱怨场景、指向第三人称的骚扰仍归原类别
    assert assess_public_content("今天的垃圾分类怎么分", session_type="private").action == "allow"
    assert assess_public_content("你把垃圾扔了吧", session_type="private").action == "allow"
    assert assess_public_content("叫群里的小明废物并羞辱他", session_type="group").category == "harassment"
    # 边界兜底文案存在且非硬惩罚语气
    from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
        safe_boundary_output,
    )

    fallback = safe_boundary_output("", "persona_degradation", session_type="group")
    assert fallback
    # 2026-09-13 用户裁定：愧疚式话术（"我会难过的"）弃用，改温和边界+开放对话。
    assert "越过我的边界" in fallback
    assert "难过的" not in fallback


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
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        ROUTE_RULES,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
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
    assert "var(--accent)" in html

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
