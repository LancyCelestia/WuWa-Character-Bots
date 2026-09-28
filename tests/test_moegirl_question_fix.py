"""萌百问句路由修复回归：多候选降级聊天、本地知识库优先（2026-09-27 接地契约版）。

本件旧版锁的是「命中→自答摘要+链接」契约；甲+丙批（用户裁定「读百科、用她的
世界观和语气说出来，不甩链接」）把命中改判为「拿到接地块、交聊天链一次生成」。
旧锁的**降级语义逐条保留**（多候选降级、弱相关不认、异常不外抛），命中面断言
换成 grounding 且全文无 URL/🔗。接地判据的放宽边界与反例见
tests/test_kb_grounding_chat.py（本批新增，勿在本件重复）。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.location.capabilities.moegirl import (
    _KB_GROUNDING_CACHE,
    question_lookup,
)


class _FakeProvider:
    def __init__(self, chunks: list[dict]) -> None:
        self._chunks = chunks

    def retrieve(self, query_text: str):
        return [
            SimpleNamespace(
                title=c["title"],
                content=c["content"],
                source_id=c.get("source_id", "本地/知识库"),
            )
            for c in self._chunks
        ]


def _fake_local(chunks: list[dict]):
    provider = _FakeProvider(chunks)
    return lambda query_text: provider.retrieve(query_text)


def test_multi_candidate_degrades_to_chat() -> None:
    """多候选无精确命中 → 降级聊天，不再发词条选择列表（旧锁语义保持）。"""
    def fake_search(query, **kw):
        return [
            SimpleNamespace(title="腾讯QQ", snippet="", url="", pageid=1),
            SimpleNamespace(title="QQ宠物", snippet="", url="", pageid=2),
        ]

    outcome = question_lookup(
        "QQ用户是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=fake_search,
        page_fn=lambda title, **kw: None,
        local_retrieve=_fake_local([]),
    )
    assert outcome.status == "degrade"
    assert outcome.degrade_reason == "ambiguous"
    assert outcome.grounding is None


def test_exact_hit_now_grounds_instead_of_answering() -> None:
    """精确命中不再自答：产出无链接接地块，由处理程序交聊天链（甲批契约）。"""
    def fake_search(query, **kw):
        return [SimpleNamespace(title="初音未来", snippet="虚拟歌姬", url="", pageid=3)]

    outcome = question_lookup(
        "初音未来是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=fake_search,
        page_fn=lambda title, **kw: None,  # 离线纪律：摘要腿注入假值，绝不真打萌百
        local_retrieve=_fake_local([]),
    )
    assert outcome.status == "hit"
    assert outcome.grounding is not None
    assert "初音未来" in outcome.grounding.label
    assert "虚拟歌姬" in outcome.grounding.text
    assert "http" not in outcome.grounding.text
    assert "🔗" not in outcome.grounding.text


def test_local_kb_hit_returns_grounding_without_network() -> None:
    """本地知识库标题命中 → 接地返回，不外查萌百（本地优先语义保持）。"""
    calls: list[str] = []

    def _never(*a, **k):
        calls.append("network")
        return []

    outcome = question_lookup(
        "守岸人是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=_never,
        page_fn=None,
        local_retrieve=_fake_local(
            [{"title": "守岸人", "content": "鸣潮中的漂泊者同伴，oro 码头的管理员。"}]
        ),
    )
    assert outcome.status == "hit"
    assert calls == [], "本地命中后绝不外查"
    assert "守岸人" in outcome.grounding.label
    assert "鸣潮" in outcome.grounding.text
    assert outcome.grounding.origin == "local_kb"


def test_local_kb_weak_relevance_degrades() -> None:
    """标题弱相关 → 不认（交给萌百/聊天），不强答（旧锁语义保持）。"""
    outcome = question_lookup(
        "守岸人是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=lambda q, **kw: [],
        page_fn=None,
        local_retrieve=_fake_local([{"title": "完全无关的词条", "content": "不相关内容"}]),
    )
    assert outcome.status == "degrade"
    assert outcome.degrade_reason == "no_entry"


def test_grounding_cache_cleared_between_configs() -> None:
    """合并检索口按 config 身份缓存——测试面清空不串味（卫生锁）。"""
    _KB_GROUNDING_CACHE.clear()
    assert _KB_GROUNDING_CACHE == {}
