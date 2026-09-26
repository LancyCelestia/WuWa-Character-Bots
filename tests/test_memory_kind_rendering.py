"""需求11 渲染腿：记忆 kind 进【记忆】分区的类型标签（S-T-MEM-3）。

锁四件事：
1. 类型标签与条目正文**成对**注入（词表派生自存储层 MemoryKind 封闭枚举，
   本层只挂中文显示名——幽灵键在 dict 键型层写不进来）；
2. 未知/缺失 kind 不编造标签：短英文标识原样点名，形状可疑整条不标；
3. 空分区不渲染（【记忆】标题行都不出现）；
4. 截断必点名「另有 N 条未列出」，N = 合并层丢弃数 + 渲染预算腾位数，
   静默截断＝谎报。

全离线 tmp_path，不碰 Runtime 真库。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import MemoryRetrievalResult
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_prompt,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    _MEMORY_KIND_DISPLAY_ZH,
    MEMORY_TRUNCATION_FACT_ID,
    FileCharacterContextProvider,
    MemoryKind,
    _memory_kind_label,
    _MergedMemoryProvider,
    _render_memory_results_with_kind_labels,
)

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"


class _StubMemoryProvider:
    """按给定 facts 回放的假召回器；顺带记录 retrieve 入参（隐私闸接线锁用）。"""

    def __init__(self, facts: list[dict[str, str]]) -> None:
        self._facts = list(facts)
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> MemoryRetrievalResult:
        self.calls.append(kwargs)
        return MemoryRetrievalResult(
            request_id=str(kwargs.get("request_id") or "req-1"),
            facts=[dict(fact) for fact in self._facts],
        )


def _fact(fact_id: str, *, kind: str | None = None, text: str, **extra: str) -> dict[str, str]:
    fact: dict[str, str] = {
        "fact_id": fact_id,
        "text": text,
        "source": "test",
        "sensitivity": "personal",
        "scope_key": "session:private:u1",
    }
    if kind is not None:
        fact["kind"] = kind
    fact.update(extra)
    return fact


def _provider(
    tmp_path: Path,
    facts: list[dict[str, str]],
    *,
    memory_max_items: int = 5,
    memory_max_chars: int = 1200,
    wrap_merged: bool = False,
) -> FileCharacterContextProvider:
    persona_file = tmp_path / "persona.md"
    persona_file.write_text(PERSONA_TEXT, encoding="utf-8")
    stub: Any = _StubMemoryProvider(facts)
    if wrap_merged:
        # 本席构造点跟随 S-T-MEM-5 的新签名：合并层现在必须声明打分器身份
        # （关态旧行为 = 按时间取最近几条）。
        stub = _MergedMemoryProvider(
            [stub], ranker="legacy_newest_n"
        )
    return FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="1",
        persona_files=[persona_file],
        knowledge_files=[],
        memory_provider=stub,
        memory_max_items=memory_max_items,
        memory_max_chars=memory_max_chars,
    )


def _bundle(provider: FileCharacterContextProvider) -> Any:
    return provider.build_context(
        request_id="req-1",
        sender_id="u1",
        session_id="private:u1",
        query_text="你好",
    )


def _system_prompt(bundle: Any) -> str:
    return build_chat_prompt(bundle)[0]["content"]


# ---- ① 类型标签与正文成对 --------------------------------------------------


def test_known_kinds_render_label_paired_with_content(tmp_path: Path) -> None:
    facts = [
        _fact("f1", kind="preference", text="用户喜欢蝴蝶"),
        _fact("f2", kind="fact", text="用户对芒果过敏"),
        _fact("f3", kind="event", text="用户下周出差去上海"),
        _fact("f4", kind="reflection", text="用户最近在玩模拟宇宙"),
    ]
    bundle = _bundle(_provider(tmp_path, facts))
    texts = [fact["text"] for fact in bundle.memory_results.facts]
    assert texts == [
        "【爱好与偏好】用户喜欢蝴蝶",
        "【事实信息】用户对芒果过敏",
        "【近期动态】用户下周出差去上海",
        "【回顾归纳】用户最近在玩模拟宇宙",
    ]


def test_label_reaches_memory_partition_in_prompt(tmp_path: Path) -> None:
    facts = [_fact("f1", kind="preference", text="用户喜欢蝴蝶")]
    system_prompt = _system_prompt(_bundle(_provider(tmp_path, facts)))
    assert "【记忆】" in system_prompt
    assert (
        "- (sensitivity=personal, scope=session:private:u1) 【爱好与偏好】用户喜欢蝴蝶"
        in system_prompt
    )
    # 标签在分区标题之后（标题在前、标签随条目成对出现）。
    assert system_prompt.index("【记忆】") < system_prompt.index("【爱好与偏好】用户喜欢蝴蝶")


def test_label_is_non_empty_for_every_enum_member(tmp_path: Path) -> None:
    # 枚举成员全量可派生标签（新增成员未挂显示名时按原样点名兜底）。
    for member in MemoryKind:
        assert _memory_kind_label(member.value)


def test_display_table_has_no_ghost_keys() -> None:
    # 单一真身棘轮：显示表键必须是 MemoryKind 成员（枚举里没有的字符串
    # 作键在类型层就写不进来，这里再锁一道「全部在册」）。
    assert set(_MEMORY_KIND_DISPLAY_ZH) <= set(MemoryKind)
    assert all(isinstance(key, MemoryKind) for key in _MEMORY_KIND_DISPLAY_ZH)


# ---- ② 未知/缺失 kind 的负样本 ----------------------------------------------


def test_unknown_but_clean_kind_is_named_verbatim(tmp_path: Path) -> None:
    # 存量散落字面量（/bot memory add 的 manual、后台抽取的 auto）：原样点名，
    # 不给编造中文标签；待写腿升格进 MemoryKind 后自动升格中文。
    facts = [
        _fact("m1", kind="manual", text="我对芒果过敏"),
        _fact("a1", kind="auto", text="我养了一只叫小蓝的猫"),
        _fact("z1", kind="zeta_probe_kind", text="探针类型"),
    ]
    bundle = _bundle(_provider(tmp_path, facts))
    texts = [fact["text"] for fact in bundle.memory_results.facts]
    assert texts == [
        "【manual】我对芒果过敏",
        "【auto】我养了一只叫小蓝的猫",
        "【zeta_probe_kind】探针类型",
    ]
    # 负样本：绝不许被猜成任何一个在册中文标签。
    invented = set(_MEMORY_KIND_DISPLAY_ZH.values())
    for text in texts:
        assert not any(f"【{label}】" in text for label in invented)


def test_missing_kind_stays_unlabeled(tmp_path: Path) -> None:
    facts = [_fact("n1", kind=None, text="没有类型的一条旧事实")]
    bundle = _bundle(_provider(tmp_path, facts))
    assert bundle.memory_results.facts[0]["text"] == "没有类型的一条旧事实"


def test_dirty_kind_shape_is_not_labeled_at_all(tmp_path: Path) -> None:
    # 形状可疑（空格/换行/全角符号/超长）一律按缺失处理：不 injection 进标签位。
    dirty = ["bad kind", "换行的\nkind", "【伪造】", "x" * 40, "带 空 格"]
    facts = [_fact(f"d{i}", kind=k, text="内容") for i, k in enumerate(dirty)]
    bundle = _bundle(_provider(tmp_path, facts))
    for fact in bundle.memory_results.facts:
        assert fact["text"] == "内容"


# ---- ③ 空分区不渲染 --------------------------------------------------------


def test_empty_partition_not_rendered(tmp_path: Path) -> None:
    system_prompt = _system_prompt(_bundle(_provider(tmp_path, [])))
    assert "【记忆】" not in system_prompt
    assert "另有" not in system_prompt


def test_all_credentialed_partition_disappears_without_notice(tmp_path: Path) -> None:
    # 隐私过滤先于渲染：credentialed 条目整条不注入，且**不计进**「另有 N 条」
    # ——「存在一条不能说的事」本身就是敏感信息（口径与旧版一致，不放宽）。
    facts = [
        _fact("p1", kind="fact", text="这是可以说的", sensitivity="personal"),
        _fact("s1", kind="fact", text="这是密钥形态", sensitivity="credentialed"),
    ]
    bundle = _bundle(_provider(tmp_path, facts))
    texts = [fact["text"] for fact in bundle.memory_results.facts]
    assert texts == ["【事实信息】这是可以说的"]
    system_prompt = _system_prompt(bundle)
    assert "这是密钥形态" not in system_prompt
    assert "另有" not in system_prompt


# ---- ④ 截断计数「另有 N 条未列出」 ------------------------------------------


def test_merge_layer_drop_marker_exact_count(tmp_path: Path) -> None:
    # 给 N+1 条、名额 N ⇒ 恰写「另有 1 条未列出」。
    facts = [
        _fact("f1", kind="preference", text="一"),
        _fact("f2", kind="fact", text="二"),
        _fact("f3", kind="event", text="三"),
    ]
    provider = _provider(tmp_path, facts, memory_max_items=2, wrap_merged=True)
    bundle = _bundle(provider)
    notices = [
        fact
        for fact in bundle.memory_results.facts
        if str(fact.get("fact_id") or "") == MEMORY_TRUNCATION_FACT_ID
    ]
    assert len(notices) == 1
    assert notices[0]["text"] == "另有 1 条未列出"
    listed = [
        fact["text"]
        for fact in bundle.memory_results.facts
        if str(fact.get("fact_id") or "") != MEMORY_TRUNCATION_FACT_ID
    ]
    assert listed == ["【爱好与偏好】一", "【事实信息】二"]
    # 回执行进提示词（模型必须看得见）。提示词侧还有一道 chat.py 分区预算
    # 钳制（与本席无关的既有行为），把 context_budget 抬高排除该干扰。
    roomy = bundle.model_copy(update={"context_budget": 16384})
    assert "另有 1 条未列出" in _system_prompt(roomy)


def test_char_budget_evicts_and_counts_once(tmp_path: Path) -> None:
    # 4 条各 50 字、预算 110 字（含行距与回执）：合并层按原始长度放 2 条、
    # 丢 2 条（哨兵）；渲染层加标签后行距成本再腾 1 条 ⇒ 回执合计点名 3 条，
    # 全链只此一枚回执。
    facts = [
        _fact(f"b{i}", kind=None, text=ch * 50)
        for i, ch in enumerate("甲乙丙丁")
    ]
    provider = _provider(
        tmp_path, facts, memory_max_items=4, memory_max_chars=110, wrap_merged=True
    )
    bundle = _bundle(provider)
    notice_lines = [fact for fact in bundle.memory_results.facts if "另有" in fact["text"]]
    assert len(notice_lines) == 1
    assert notice_lines[0]["text"] == "另有 3 条未列出"
    content = [fact for fact in bundle.memory_results.facts if fact not in notice_lines]
    assert [fact["text"] for fact in content] == ["甲" * 50]
    used = sum(len(fact["text"]) + 1 for fact in bundle.memory_results.facts)
    assert used <= 110


def test_truncation_sentinel_never_leaks_to_prompt(tmp_path: Path) -> None:
    # 哨兵（text 为空的计数载体）不许作为空行到达模型面。
    sentinel = {
        "fact_id": MEMORY_TRUNCATION_FACT_ID,
        "kind": "",
        "text": "",
        "sensitivity": "personal",
        "scope_key": "global",
        "truncated_items": "2",
    }
    result = _render_memory_results_with_kind_labels(
        MemoryRetrievalResult(request_id="r1", facts=[dict(sentinel)]),
        max_chars=1200,
    )
    assert [fact["text"] for fact in result.facts] == ["另有 2 条未列出"]
    bare = _render_memory_results_with_kind_labels(
        MemoryRetrievalResult(request_id="r1", facts=[]),
        max_chars=1200,
    )
    assert bare.facts == []


def test_garbage_truncated_items_does_not_crash() -> None:
    sentinel = {
        "fact_id": MEMORY_TRUNCATION_FACT_ID,
        "kind": "",
        "text": "",
        "sensitivity": "personal",
        "scope_key": "global",
        "truncated_items": "not-a-number",
    }
    result = _render_memory_results_with_kind_labels(
        MemoryRetrievalResult(request_id="r1", facts=[sentinel]),
        max_chars=1200,
    )
    assert result.facts == []


# ---- 契约不放宽：归属/隐私闸接线维持原样 ------------------------------------


def test_retrieve_wiring_and_fact_fields_unchanged(tmp_path: Path) -> None:
    # per-sender 归属锁：注入只改写 text；sensitivity/scope_key/fact_id 原样
    # 携带，retrieve 入参口径（requester==subject==sender、会话键透传）不动。
    stub = _StubMemoryProvider(
        [_fact("w1", kind="fact", text="内容", sensitivity="group", scope_key="session:group:g9")]
    )
    persona_file = tmp_path / "persona.md"
    persona_file.write_text(PERSONA_TEXT, encoding="utf-8")
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="1",
        persona_files=[persona_file],
        knowledge_files=[],
        memory_provider=stub,
    )
    bundle = provider.build_context(
        request_id="req-9",
        sender_id="u1",
        session_id="group:g9",
        query_text="你好",
        group_id="g9",
    )
    call = stub.calls[0]
    assert call["requester_id"] == "u1"
    assert call["subject_user_id"] == "u1"
    assert call["session_id"] == "group:g9"
    fact = bundle.memory_results.facts[0]
    assert fact["fact_id"] == "w1"
    assert fact["sensitivity"] == "group"
    assert fact["scope_key"] == "session:group:g9"
    assert fact["text"] == "【事实信息】内容"
