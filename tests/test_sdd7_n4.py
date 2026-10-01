"""SDD7 N4 回归：八项小改动（W4 六项 + 提醒进阶轨 + parked minor）。

逐项独立：心情档偷表情 / 主动搭话亲和门 / 反思事实→quirk 提案 / Atom 源 /
群聊事实按 sender 归属 / 八字藏干 / 提醒轮末抽取 / effort 展示口径。
全部打桩（心情/好感/LLM 均 mock），无网络、无外部数据。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
    extract_reminder_drafts,
    store_extracted_reminders,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import QuirkStore
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    FactDraft,
    HeuristicSummarizer,
    ReflectionStore,
    Turn,
    build_reflection_quirk_proposer,
    quirk_proposal_texts,
    run_reflection,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    baseline_effort,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy import gate as gate_module
from plugins.bot_unified_runtime.domains.chat_reply.policy.gate import (
    PolicySettings,
    configure_proactive_affinity_gate,
    evaluate_policy,
)
from plugins.bot_unified_runtime.domains.divination.capabilities.divination import (
    build_divination_capability,
    hidden_stems_for_branch,
    hidden_stems_section,
)
from plugins.bot_unified_runtime.domains.divination.data.ganzhi import CST, bazi_chart
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    build_meme_library_capability,
)
from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
    _family_baseline_effort,
)
from plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds import (
    _FEEDS,
    parse_feed,
)

# ---------------------------------------------------------------------------
# 打桩工具。
# ---------------------------------------------------------------------------


class _StubConfig:
    """proposer 相关开关的最小配置桩。"""

    bot_quirks_enabled = True
    bot_reflection_quirks_propose_enabled = True
    bot_reflection_quirks_min_confidence = 0.5
    bot_quirks_db_path = "data/persona_quirks.sqlite3"


def _group_message(
    text: str,
    *,
    sender_id: str = "user-1",
    group_id: str = "group-1",
    mentions_bot: bool = False,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions_bot,
        message_id="message-1",
    )


def _private_message(text: str, *, sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        timestamp=datetime(2026, 9, 12, 13, 51, tzinfo=timezone.utc),
    )


class _ScriptedPickStore:
    """weighted_pick 按脚本顺序返回；耗尽后重复最后一个。"""

    def __init__(self, picks: list[dict[str, object]]) -> None:
        self._picks = picks or [{"path": "x.png", "weight": 1.0}]
        self._index = -1
        self.pick_calls = 0

    def weighted_pick(self, *, keyword: str = "", nsfw_max: float = 0.2):
        self.pick_calls += 1
        if self._index < len(self._picks) - 1:
            self._index += 1
        return self._picks[self._index]


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def generate(self, messages, **options):
        self.calls += 1
        return self


class _RecordingReminderStore:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.added: list[dict[str, object]] = []
        self._fail_on = fail_on or set()

    def add(self, **kwargs):
        if kwargs.get("text") in self._fail_on:
            raise RuntimeError("boom")
        self.added.append(kwargs)


# ---------------------------------------------------------------------------
# 项8：runtime_admin effort 展示口径对齐 baseline。
# ---------------------------------------------------------------------------


def test_n4_effort_display_reads_family_baseline() -> None:
    assert _family_baseline_effort("deepseek-v4-pro") == "low"
    assert _family_baseline_effort("gpt-5.6-terra") == baseline_effort("gpt-5.6-terra")
    assert _family_baseline_effort("totally-unknown-model") == ""
    # 旧 helper（家族最高档标「默认」）应已被替换，不存在双口径。
    import plugins.bot_unified_runtime.domains.ops.admin.runtime_admin as mod

    assert not hasattr(mod, "_family_default_effort")


# ---------------------------------------------------------------------------
# 项6：八字藏干与权重展示。
# ---------------------------------------------------------------------------


def test_n4_hidden_stems_table_weights_sum_to_100() -> None:
    for branch_index in range(12):
        stems = hidden_stems_for_branch(branch_index)
        assert stems, f"branch {branch_index} 缺藏干"
        assert sum(weight for _, weight in stems) == 100
    assert hidden_stems_for_branch(0) == (("癸", 100),)
    assert hidden_stems_for_branch(2) == (("甲", 60), ("丙", 30), ("戊", 10))


def test_n4_hidden_stems_section_renders_pillars_and_weighted_summary() -> None:
    chart = bazi_chart(datetime(1998, 3, 2, 7, 0, tzinfo=CST))
    section = hidden_stems_section(chart)
    assert section.startswith("藏干：")
    for label in ("年柱", "月柱", "日柱", "时柱"):
        assert label in section
    assert "藏干五行（加权）" in section
    # 锚点日柱 1998-03-02 = 戊申：申藏庚60壬30戊10。
    assert "日柱申 庚60壬30戊10" in section


def test_n4_bazi_capability_output_contains_hidden_stems_and_keeps_disclaimer_last() -> None:
    capability = build_divination_capability(None)
    result = capability(_private_message("八字 1998年3月2日早上7点"), None)
    assert "藏干：" in result.body
    assert "藏干五行（加权）" in result.body
    assert result.body.rstrip().endswith("（仅供娱乐，人生靠自己书写～）")


# ---------------------------------------------------------------------------
# 项4：Atom 真源（离线解析 + 源注册）。
# ---------------------------------------------------------------------------

_ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>测试Atom</title>
  <id>urn:test</id>
  <updated>2026-09-12T00:00:00Z</updated>
  <entry>
    <title>条目一</title>
    <link rel="alternate" type="text/html" href="https://e.example/1"/>
    <id>urn:1</id>
    <updated>2026-09-11T10:00:00Z</updated>
  </entry>
  <entry>
    <title>条目二</title>
    <link href="https://e.example/2"/>
    <id>urn:2</id>
  </entry>
</feed>
"""


def test_n4_atom_feed_parses_via_generic_branch() -> None:
    items = parse_feed(_ATOM_FEED, source="测试Atom", category="tech")
    assert [item.title for item in items] == ["条目一", "条目二"]
    assert items[0].url == "https://e.example/1"
    assert items[0].published_at is not None
    assert items[1].published_at is None


def test_n4_atom_source_registered_for_tech() -> None:
    assert any(
        "v2ex.com/index.xml" in url and source == "V2EX" and category == "tech"
        for url, source, category in _FEEDS
    )


# ---------------------------------------------------------------------------
# 项5：反思群聊事实按 sender 归属。
# ---------------------------------------------------------------------------


def _reflection_turns() -> list[Turn]:
    return [
        Turn(role="user", text="我很喜欢弹吉他", created_at="2026-09-12T01:00:00Z", sender_id="alice"),
        Turn(role="assistant", text="真好呀", created_at="2026-09-12T01:00:05Z", sender_id=""),
        Turn(role="user", text="我住在上海", created_at="2026-09-12T01:01:00Z", sender_id="bob"),
        Turn(role="user", text="我要学Python", created_at="2026-09-12T01:02:00Z", sender_id=""),
    ]


def test_n5_group_facts_attributed_per_sender(tmp_path) -> None:
    store = ReflectionStore(tmp_path / "reflection.sqlite3")
    report = run_reflection(
        store,
        {"qq:g1": _reflection_turns()},
        summarizer=HeuristicSummarizer(),
        scope_date="2026-09-12",
    )
    assert report.facts_saved == 3
    alice = " ".join(fact.fact_text for fact in store.facts_for("alice"))
    bob = " ".join(fact.fact_text for fact in store.facts_for("bob"))
    assert "吉他" in alice and "上海" not in alice
    assert "上海" in bob and "吉他" not in bob
    # 无 sender 的历史轮次回退主 sender（并列发言数取字典序最小 = alice）。
    assert "Python" in alice


# ---------------------------------------------------------------------------
# 项3：反思事实 → persona_quirks 待审提案。
# ---------------------------------------------------------------------------


def test_n3_quirk_proposal_whitelist_rules() -> None:
    facts = [
        FactDraft(text="我很喜欢弹吉他", category="preference", confidence=0.5),
        FactDraft(text="我最近在学画画", category="activity", confidence=0.5),
        FactDraft(text="整点别的", category="weird", confidence=0.9),
        FactDraft(text="我住在上海", category="", confidence=0.6),
        FactDraft(text="上海今天下雨", category="", confidence=0.9),
        FactDraft(text="我想养猫", category="", confidence=0.59),
    ]
    texts = quirk_proposal_texts(facts, min_confidence=0.5)
    assert texts == ["我很喜欢弹吉他", "我最近在学画画", "我住在上海"]


def test_n3_proposer_feeds_pending_review_only(tmp_path, monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    monkeypatch.setattr(
        providers,
        "build_runtime_data_path",
        lambda config, value: tmp_path / value,
    )
    proposer = build_reflection_quirk_proposer(_StubConfig())
    assert proposer is not None
    assert proposer([FactDraft(text="我很喜欢弹吉他", category="preference", confidence=0.5)]) == 1

    store = QuirkStore(tmp_path / "data/persona_quirks.sqlite3")
    pending = store.list(status="pending_review")
    assert len(pending) == 1
    assert pending[0].source == "reflection"
    # 未过审对 prompt 零影响。
    assert store.render_prompt_section() == ""

    disabled = _StubConfig()
    disabled.bot_reflection_quirks_propose_enabled = False
    assert build_reflection_quirk_proposer(disabled) is None


def test_n3_run_reflection_invokes_collector_for_fact_sessions(tmp_path) -> None:
    collected: list[FactDraft] = []
    store = ReflectionStore(tmp_path / "reflection.sqlite3")
    run_reflection(
        store,
        {"qq:g1": _reflection_turns()},
        summarizer=HeuristicSummarizer(),
        scope_date="2026-09-12",
        quirk_collector=collected.extend,
    )
    assert len(collected) == 3


# ---------------------------------------------------------------------------
# 项1：表情包情绪档（心情低落少推吵闹梗）。
# ---------------------------------------------------------------------------

_NOISY = {"description": "搞笑沙雕图", "emotion_tags": "[]", "scene_tags": "[]", "path": "noisy.png", "weight": 2.0}
_CALM = {"description": "猫咪睡觉", "emotion_tags": "[]", "scene_tags": "[]", "path": "calm.png", "weight": 1.0}


def _run_meme_pick(store, valences: list[float]) -> tuple[object, object]:
    valence_iter = iter(valences)
    capability = build_meme_library_capability(
        store, None, mood_valence_fn=lambda: next(valence_iter, 0.0)
    )
    result = capability(_group_message("偷表情"), None)
    return result, store


def test_n1_low_mood_avoids_noisy_meme() -> None:
    store = _ScriptedPickStore([dict(_NOISY), dict(_CALM)])
    result, store = _run_meme_pick(store, [-0.5])
    assert "calm.png" in str(result.images)
    assert "mood_muted" in result.audit_tags
    assert store.pick_calls == 2


def test_n1_low_mood_all_noisy_still_sends() -> None:
    store = _ScriptedPickStore([dict(_NOISY), dict(_NOISY), dict(_NOISY)])
    result, _ = _run_meme_pick(store, [-0.5])
    assert "noisy.png" in str(result.images)  # 软偏置：全部吵闹也照发。


def test_n1_normal_mood_keeps_single_pick() -> None:
    store = _ScriptedPickStore([dict(_NOISY), dict(_CALM)])
    result, store = _run_meme_pick(store, [0.4])
    assert "noisy.png" in str(result.images)
    assert "mood_muted" not in result.audit_tags
    assert store.pick_calls == 1


def test_n1_broken_mood_fn_behaves_neutral() -> None:
    capability = build_meme_library_capability(
        _ScriptedPickStore([dict(_NOISY)]),
        None,
        mood_valence_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = capability(_group_message("偷表情"), None)
    assert "noisy.png" in str(result.images)
    assert "mood_muted" not in result.audit_tags


# ---------------------------------------------------------------------------
# 项2：主动搭话亲和门（好感档 ≥ 亲近才主动接话）。
# ---------------------------------------------------------------------------


def _proactive_settings() -> PolicySettings:
    return PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=True,
        group_auto_reply_probability=1.0,  # 抽签必中，聚焦测门本身。
    )


@pytest.fixture()
def _reset_proactive_gate():
    yield
    configure_proactive_affinity_gate(None)


def test_n2_gate_blocks_non_close_sender(_reset_proactive_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: sender == "vip")
    decision = evaluate_policy(_group_message("今天天气不错"), "bot.chat", _proactive_settings())
    assert decision.allowed is False
    assert decision.reason == "proactive_affinity_gate"


def test_n2_gate_allows_close_sender(_reset_proactive_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: sender == "user-1")
    decision = evaluate_policy(_group_message("今天天气不错"), "bot.chat", _proactive_settings())
    assert decision.allowed is True
    assert decision.reason == "proactive_reply_selected"


def test_n2_gate_checker_failure_fails_closed(_reset_proactive_gate) -> None:
    def _boom(sender: str) -> bool:
        raise RuntimeError("affinity store down")

    configure_proactive_affinity_gate(_boom)
    decision = evaluate_policy(_group_message("今天天气不错"), "bot.chat", _proactive_settings())
    assert decision.allowed is False


def test_n2_gate_unconfigured_keeps_legacy_behavior() -> None:
    assert gate_module._proactive_affinity_checker is None
    decision = evaluate_policy(_group_message("今天天气不错"), "bot.chat", _proactive_settings())
    assert decision.allowed is True


def test_n2_triggered_messages_skip_affinity_gate(_reset_proactive_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: False)
    decision = evaluate_policy(
        _group_message("在吗", mentions_bot=True), "bot.chat", _proactive_settings()
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# 项7：提醒轮末抽取（默认关的进阶轨）。
# ---------------------------------------------------------------------------

# 本地时区 08:00（与解析器同口径的 naive→本地处理，跨时区机器都成立）。
_R_NOW = datetime(2026, 9, 12, 8, 0).astimezone()


def test_n7_reminder_extraction_parses_and_validates_window() -> None:
    llm = _FakeLLM(
        "2026-09-12 14:00 写作业\n"
        "2026-09-13 09:30 开会\n"
        "2026-09-12 06:00 早起跑步\n"  # 已过点 → 丢
        "2026-10-01 10:00 交报告\n"  # 超出 7 天视野 → 丢
        "这是一句没有格式的话\n"  # 格式不符 → 丢
    )
    drafts = extract_reminder_drafts(llm, user_text="中午12点要写作业", now=_R_NOW)
    assert [(d.remind_at.month, d.remind_at.day, d.remind_at.hour, d.text) for d in drafts] == [
        (9, 12, 14, "写作业"),
        (9, 13, 9, "开会"),
    ]


def test_n7_reminder_extraction_none_and_dedup() -> None:
    assert extract_reminder_drafts(_FakeLLM("无"), user_text="随便聊聊", now=_R_NOW) == []
    llm = _FakeLLM("2026-09-12 14:00 写作业\n2026-09-12 14:00 写作业\n")
    drafts = extract_reminder_drafts(llm, user_text="…", now=_R_NOW)
    assert len(drafts) == 1


def test_n7_reminder_store_path_tolerates_single_failure() -> None:
    store = _RecordingReminderStore(fail_on={"开会"})
    drafts = extract_reminder_drafts(
        _FakeLLM("2026-09-12 14:00 写作业\n2026-09-13 09:30 开会"), user_text="…", now=_R_NOW
    )
    stored = store_extracted_reminders(
        store,
        drafts=drafts,
        session_key="group:g1",
        sender_id="u1",
        target_scope="group",
        target_id="g1",
    )
    assert stored == 1
    assert len(store.added) == 1
    assert store.added[0]["remind_at"].hour == 14


def test_n7_reminder_llm_extract_defaults_off() -> None:
    from plugins.bot_unified_runtime.config import Config

    assert Config.model_fields["bot_reminder_llm_extract_enabled"].default is False
    # 项2/项3 的开关默认值。
    assert Config.model_fields["bot_proactive_affinity_gate_enabled"].default is True
    assert Config.model_fields["bot_reflection_quirks_propose_enabled"].default is True


# ---------------------------------------------------------------------------
# 2026-09-18 实弹反馈：群里其他 AI 机器人发的催缴广告被抽成提醒。
# 广告文本（"【套餐】尊敬的用户您好 截至9月17日12时 … 请及时缴费50元"）同时
# 满足旧 prompt 的"明确时间点 + 事项"，被照抽不误，且在多个群重复入库、同一
# 时刻齐发（用户实测"12:00 五条齐炸"）。记忆路径早有同款确定性闸
# （_TRIVIAL_FACT_RE，F16），提醒路径此前完全没有——本组用例锁定补齐后的行为。
# ---------------------------------------------------------------------------

_PROMO_TEXT = (
    "【套餐 】尊敬的用户您好 截至9月17日12时 您的token账户已不足支付本群的"
    "AI好友聊天 为了不影响您正常调用AI好友的聊天功能 请及时缴费50元"
)


def test_n7_reminder_extract_skips_promo_text_without_llm_call() -> None:
    """广告/催缴文本在**输入侧**即被拦下，连 LLM 都不调用（省一次调用）。"""
    llm = _FakeLLM("2026-09-18 12:00 缴费50元")
    assert extract_reminder_drafts(llm, user_text=_PROMO_TEXT, now=_R_NOW) == []
    assert llm.calls == 0


def test_n7_reminder_extract_drops_promo_entries_from_output() -> None:
    """即便 LLM 仍抽出广告条目，输出侧确定性闸也必须丢弃。"""
    llm = _FakeLLM("2026-09-18 12:00 【套餐】请及时缴费50元")
    assert extract_reminder_drafts(llm, user_text="随便聊聊", now=_R_NOW) == []
    assert llm.calls == 1


def test_n7_reminder_extract_keeps_genuine_user_intent() -> None:
    """闸门不得误伤正常用户意图（回归保护）。"""
    llm = _FakeLLM("2026-09-12 14:00 写作业")
    drafts = extract_reminder_drafts(llm, user_text="中午12点要写作业", now=_R_NOW)
    assert [draft.text for draft in drafts] == ["写作业"]
