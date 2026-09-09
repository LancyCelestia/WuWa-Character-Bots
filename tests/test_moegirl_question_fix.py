"""萌百问句路由修复回归：多候选降级聊天、本地知识库优先。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.moegirl import (
    _KB_PROVIDER_CACHE,
    local_kb_answer,
    question_lookup,
)


class _FakeProvider:
    def __init__(self, chunks: list[dict]) -> None:
        self._chunks = chunks

    def retrieve(self, query_text: str):
        return [
            SimpleNamespace(title=c["title"], content=c["content"])
            for c in self._chunks
        ]


def test_multi_candidate_degrades_to_chat(monkeypatch) -> None:
    """多候选无精确命中 → 降级聊天，不再发词条选择列表。"""
    def fake_search(query, **kw):
        return [
            SimpleNamespace(title="腾讯QQ", snippet="", url="", pageid=1),
            SimpleNamespace(title="QQ宠物", snippet="", url="", pageid=2),
        ]

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.moegirl.moegirl_search",
        fake_search,
    )
    outcome = question_lookup(
        "QQ用户是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=fake_search,
        page_fn=lambda title, **kw: None,
    )
    assert outcome.status == "degrade"


def test_exact_hit_still_answers(monkeypatch) -> None:
    """精确命中仍直接回答（知识类问题正常服务）。"""
    def fake_search(query, **kw):
        return [SimpleNamespace(title="初音未来", snippet="虚拟歌手", url="", pageid=3)]

    def fake_page(title, **kw):
        return SimpleNamespace(title="初音未来", summary="虚拟歌姬", snippet="", url="", pageid=3)

    outcome = question_lookup(
        "初音未来是谁",
        config=SimpleNamespace(bot_moegirl_api_base="", bot_moegirl_mirror_api_base=""),
        search_fn=fake_search,
        page_fn=fake_page,
    )
    assert outcome.status == "hit"
    assert "初音未来" in outcome.body


def test_local_kb_hit_returns_entry(monkeypatch) -> None:
    """本地知识库标题命中 → 返回本地条目（不外查萌百）。"""
    provider = _FakeProvider(
        [{"title": "守岸人", "content": "鸣潮中的漂泊者同伴，oro 码头的管理员。"}]
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.character.vector_knowledge.build_vector_knowledge_provider",
        lambda config: provider,
    )
    _KB_PROVIDER_CACHE.clear()
    body = local_kb_answer(object(), "守岸人")
    assert body is not None
    assert "守岸人" in body
    assert "鸣潮" in body


def test_local_kb_weak_relevance_returns_none(monkeypatch) -> None:
    """标题弱相关 → 返回 None（交给萌百/聊天），不强答。"""
    provider = _FakeProvider(
        [{"title": "完全无关的词条", "content": "不相关内容"}]
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.character.vector_knowledge.build_vector_knowledge_provider",
        lambda config: provider,
    )
    _KB_PROVIDER_CACHE.clear()
    assert local_kb_answer(object(), "守岸人") is None
