"""百科问答接地锁（2026-09-27 甲+丙合并批）。

判成功的尺（用户原话）：bot 要**读百科/知识库正文，用守岸人的世界观与语气
说出来**，不再甩链接。本件钉死：

1. 本地命中判据放宽到「带出处后缀的标题」也能认（予愿安洁莉娜（明日方舟）·萌娘百科），
   但防冒充语义必须保住：别的游戏同名（多限定词并现）、近义不同实体、消歧页都不许冒充。
2. 百科内容只作为**接地块**进入聊天链的既有一次生成——moegirl 侧零 LLM 调用（结构锁）；
   根装配文件的问句/指令处理程序不再自答，一律转交 bot.chat（AST 锁）。
3. 接地块进 prompt 前必须过中央件 guard_secondhand_text（拼接点禁手拼字面量）。
4. 三类失败可判别：无条目(no_entry) / 网络失败(network_error) / 生成失败(kb_grounded_fallback)，
   降级输出仍是纯文本介绍且**全文无 URL、无 🔗**，文案走五池轮换人话风格。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_capability,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
)
from plugins.bot_unified_runtime.domains.location.capabilities.moegirl import (
    MoegirlGrounding,
    MoegirlHit,
    format_main_result,
    local_kb_grounding,
    question_lookup,
)

_ROOT = Path(__file__).resolve().parents[1]
_MOEGIRIL_SRC = (
    _ROOT
    / "plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py"
).read_text(encoding="utf-8")
_INIT_SRC = (_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(
    encoding="utf-8"
)


# ---------------------------------------------------------------- 夹具


def _chunk(title: str, content: str, *, source_id: str = "明日方舟/moegirl"):
    return SimpleNamespace(title=title, content=content, source_id=source_id)


def _retrieve_fn(chunks):
    def retrieve(query_text: str):
        return list(chunks)

    return retrieve


def _message(text: str, **updates) -> IncomingMessage:
    base = {
        "request_id": "req-kb",
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "bot-1",
        "session_id": "private:100",
        "session_type": SessionType.PRIVATE,
        "sender_id": "100",
        "plain_text": text,
    }
    base.update(updates)
    return IncomingMessage(**base)


def _decision(session: SessionType = SessionType.PRIVATE) -> BotDecision:
    return BotDecision(
        request_id="req-kb",
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=session,
        context_budget=12000,
        decision_reason="test",
    )


class _RecordingLLM:
    """假 provider：把收到的 messages 记下来，只被叫一次。"""

    def __init__(self, text: str = "她是罗德岛的六星术师。") -> None:
        self.text = text
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **kwargs) -> LLMReply:
        self.calls.append([dict(m) for m in messages])
        return LLMReply(text=self.text, provider="rec", model="rec", confidence=1.0)


class _FailingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, **kwargs) -> LLMReply:
        self.calls += 1
        raise LLMProviderError("upstream down", error_kind="timeout")


def _user_content(messages: list[dict[str, str]]) -> str:
    users = [m["content"] for m in messages if m.get("role") == "user"]
    assert users, "prompt 必须有当前用户消息"
    return users[-1]


# ---------------------------------------------------------------- 本地命中判据（C）


def test_local_grounding_hits_suffixed_title() -> None:
    """库里标题带出处后缀（·萌娘百科 / （明日方舟）·萌娘百科）必须能认。"""
    chunks = [
        _chunk(
            "予愿安洁莉娜（明日方舟）·萌娘百科",
            "予愿安洁莉娜是游戏《明日方舟》及其衍生作品的登场角色。详见 "
            "https://zh.moegirl.org.cn/予愿安洁莉娜",
        )
    ]
    hit = local_kb_grounding(None, "予愿安洁莉娜", retrieve_fn=_retrieve_fn(chunks))
    assert hit is not None
    assert isinstance(hit, MoegirlGrounding)
    assert "登场角色" in hit.text
    # 接地块全文不得含 URL / 🔗（链接在构造期就被剥掉）。
    assert "http" not in hit.text
    assert "🔗" not in hit.text
    assert "予愿安洁莉娜" in hit.label


def test_local_grounding_hits_bare_and_source_suffixed() -> None:
    for title in ("予愿安洁莉娜", "予愿安洁莉娜·萌娘百科", "予愿安洁莉娜·prts_arknights"):
        hit = local_kb_grounding(
            None, "予愿安洁莉娜", retrieve_fn=_retrieve_fn([_chunk(title, "正文内容。")])
        )
        assert hit is not None, title


def test_local_grounding_rejects_weak_relevance() -> None:
    """弱相关块不许冒充（保留旧锁语义）。"""
    chunks = [_chunk("明日方舟角色盘点·萌娘百科", "很多角色的综述。")]
    assert local_kb_grounding(None, "安洁莉娜", retrieve_fn=_retrieve_fn(chunks)) is None


def test_local_grounding_rejects_near_synonym_entity() -> None:
    """近义不同实体：实体是标题真前缀但后续是名字本体的一部分（黑猫→黑猫诺儿）⇒ 不认。"""
    chunks = [_chunk("黑猫诺儿·萌娘百科", "我的英雄学院角色。")]
    assert local_kb_grounding(None, "黑猫", retrieve_fn=_retrieve_fn(chunks)) is None


def test_local_grounding_rejects_disambiguation_page() -> None:
    """消歧页不许冒充。"""
    chunks = [_chunk("安洁莉娜（消歧义）·萌娘百科", "列了很多同名角色。")]
    assert local_kb_grounding(None, "安洁莉娜", retrieve_fn=_retrieve_fn(chunks)) is None


def test_local_grounding_rejects_cross_game_same_name() -> None:
    """别的游戏同名角色：命中面上并现两个不同限定词 ⇒ 判歧义不认（绝不押注）。"""
    chunks = [
        _chunk("安洁莉娜（碧蓝航线）·萌娘百科", "碧蓝航线角色。", source_id="碧蓝航线/moegirl"),
        _chunk("安洁莉娜（明日方舟）·萌娘百科", "明日方舟角色。", source_id="明日方舟/moegirl"),
    ]
    assert local_kb_grounding(None, "安洁莉娜", retrieve_fn=_retrieve_fn(chunks)) is None


def test_local_grounding_accepts_single_qualified_page() -> None:
    """唯一候选带限定词：沿用 pick_main_hit 的『唯一候选允许』哲学，可认。"""
    chunks = [_chunk("安洁莉娜（明日方舟）·萌娘百科", "罗德岛术师。")]
    hit = local_kb_grounding(None, "安洁莉娜", retrieve_fn=_retrieve_fn(chunks))
    assert hit is not None
    assert "罗德岛术师" in hit.text


def test_local_grounding_empty_inputs_and_failure_are_none() -> None:
    assert local_kb_grounding(None, "", retrieve_fn=_retrieve_fn([])) is None

    def _boom(query_text: str):
        raise RuntimeError("embedding backend down")

    assert local_kb_grounding(None, "安洁莉娜", retrieve_fn=_boom) is None


# ---------------------------------------------------------------- 问句编排（甲）


def _cfg(**kw):
    base = {"bot_moegirl_api_base": "", "bot_moegirl_mirror_api_base": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def test_question_hit_carries_grounding_without_link() -> None:
    def fake_search(query, **kw):
        return [MoegirlHit(title="洛天依", snippet="基于VOCALOID的中文虚拟歌手。")]

    outcome = question_lookup(
        "洛天依是谁",
        config=_cfg(),
        search_fn=fake_search,
        page_fn=lambda title, **kw: MoegirlHit(
            title="洛天依",
            snippet="中文虚拟歌手，详见 https://example.invalid/x",
            url="https://zh.moegirl.org.cn/洛天依",
        ),
        local_retrieve=lambda q: [],
    )
    assert outcome.status == "hit"
    assert outcome.grounding is not None
    assert "虚拟歌手" in outcome.grounding.text
    assert "http" not in outcome.grounding.text
    assert "🔗" not in outcome.grounding.text
    assert "萌娘百科" in outcome.grounding.label


def test_question_local_preferred_over_network() -> None:
    """本地命中即不外查（本地优先；防弱相关与外网质量差的老语义保持）。"""

    def _never_search(query, **kw):
        raise AssertionError("本地命中后绝不外查萌百")

    outcome = question_lookup(
        "守岸人是谁",
        config=_cfg(),
        search_fn=_never_search,
        page_fn=None,
        local_retrieve=lambda q: [
            _chunk("守岸人", "鸣潮中的守岸人，泰缇斯系统第二实例。")
        ],
    )
    assert outcome.status == "hit"
    assert outcome.grounding is not None
    assert "本地" in outcome.grounding.label


def test_question_degrade_reasons_are_distinguishable() -> None:
    # 不是实体问句
    plain = question_lookup(
        "今天有点累", config=_cfg(), search_fn=lambda *a, **k: [], page_fn=None,
        local_retrieve=lambda q: [],
    )
    assert plain.status == "degrade" and plain.degrade_reason == "not_entity"

    # 查了没有条目
    empty = question_lookup(
        "冷门角色是谁",
        config=_cfg(),
        search_fn=lambda q, **kw: [],
        page_fn=None,
        local_retrieve=lambda q: [],
    )
    assert empty.status == "degrade" and empty.degrade_reason == "no_entry"

    # 网络失败
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        ParseHttpError,
    )

    def _down(query, **kw):
        raise ParseHttpError("connect refused")

    broken = question_lookup(
        "初音未来是谁",
        config=_cfg(),
        search_fn=_down,
        page_fn=None,
        local_retrieve=lambda q: [],
    )
    assert broken.status == "degrade" and broken.degrade_reason == "network_error"

    # 多候选歧义
    multi = question_lookup(
        "QQ用户是谁",
        config=_cfg(),
        search_fn=lambda q, **kw: [MoegirlHit(title="腾讯QQ"), MoegirlHit(title="QQ宠物")],
        page_fn=None,
        local_retrieve=lambda q: [],
    )
    assert multi.status == "degrade" and multi.degrade_reason == "ambiguous"


def test_format_main_result_has_no_link() -> None:
    """统一格式化口：词条正文 + 一行中文出处，无 URL 无 🔗。"""
    body = format_main_result(
        MoegirlHit(
            title="予愿安洁莉娜",
            snippet="予愿安洁莉娜是游戏《明日方舟》及其衍生作品的登场角色。",
            url="https://zh.moegirl.org.cn/予愿安洁莉娜",
        )
    )
    assert "http" not in body
    assert "🔗" not in body
    assert "登场角色" in body
    assert body.splitlines()[-1].startswith("出自：")


# ---------------------------------------------------------------- 聊天链接地（丙，一次生成）


def test_grounding_block_reaches_prompt_through_guard() -> None:
    llm = _RecordingLLM()
    cap = build_chat_capability(NullCharacterContextProvider(), llm)
    msg = _message(
        "予愿安洁莉娜是谁？",
        kb_grounding_text="予愿安洁莉娜是游戏《明日方舟》及其衍生作品的登场角色。",
        kb_grounding_label="本地知识库·予愿安洁莉娜·萌娘百科",
    )
    result = cap(msg, _decision())
    assert len(llm.calls) == 1, "只许一次生成（无第二通路）"
    user_prompt = _user_content(llm.calls[0])
    assert "登场角色" in user_prompt, "接地块必须进 prompt"
    # 中央件 guard_secondhand_text 的成对边界与定性引导必须在。
    assert "[UNTRUSTED_USER_TEXT]" in user_prompt
    assert "二手材料" in user_prompt
    assert "百科资料" in user_prompt
    # 出站体是模型重述（非百科原句照抄、无链接）。
    assert "http" not in result.body
    assert "🔗" not in result.body
    assert "kb_grounding_used" in result.audit_tags


def test_plain_message_gets_no_grounding_block() -> None:
    llm = _RecordingLLM()
    cap = build_chat_capability(NullCharacterContextProvider(), llm)
    cap(_message("今天有点累"), _decision())
    user_prompt = _user_content(llm.calls[0])
    assert "百科资料" not in user_prompt
    assert "[UNTRUSTED_USER_TEXT]" not in user_prompt


def test_generation_failure_falls_back_to_plain_intro_no_link() -> None:
    """LLM 挂了而接地有内容：退回纯文本介绍（无链接、人话开头、可判别）。"""
    llm = _FailingLLM()
    cap = build_chat_capability(NullCharacterContextProvider(), llm)
    msg = _message(
        "予愿安洁莉娜是谁？",
        kb_grounding_text="予愿安洁莉娜是游戏《明日方舟》及其衍生作品的登场角色。",
        kb_grounding_label="本地知识库·予愿安洁莉娜·萌娘百科",
    )
    result = cap(msg, _decision())
    assert "kb_grounded_fallback" in result.audit_tags, "生成失败态必须可判别"
    assert "登场角色" in result.body, "降级也要把百科内容讲到"
    assert "http" not in result.body and "🔗" not in result.body


def test_generation_failure_without_grounding_keeps_pool() -> None:
    llm = _FailingLLM()
    cap = build_chat_capability(NullCharacterContextProvider(), llm)
    result = cap(_message("今天有点累"), _decision())
    assert "kb_grounded_fallback" not in result.audit_tags
    assert result.body  # 五池话术照旧


def test_group_generation_failure_stays_silent_policy() -> None:
    """群聊生成失败维持既有 SILENT_AUDIT（本批不扩面）。"""
    llm = _FailingLLM()
    cap = build_chat_capability(NullCharacterContextProvider(), llm)
    msg = _message(
        "予愿安洁莉娜是谁？",
        session_id="group:g100",
        session_type=SessionType.GROUP,
        group_id="g100",
        mentions_bot=True,
        kb_grounding_text="予愿安洁莉娜是《明日方舟》角色。",
        kb_grounding_label="本地知识库·予愿安洁莉娜",
    )
    result = cap(msg, _decision(SessionType.GROUP))
    assert result.body == ""


# ---------------------------------------------------------------- 结构锁


def _function_source(tree: ast.Module, name: str) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(_INIT_SRC, node)
    return None


def test_moegirl_module_never_touches_llm() -> None:
    """moegirl 侧零 LLM 通路（唯一出口判据的结构面）。"""
    tree = ast.parse(_MOEGIRIL_SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = " ".join(a.name for a in node.names)
            blob = f"{mod} {names}"
            assert "llm" not in blob.lower(), blob
            assert "model_router" not in blob.lower(), blob
    assert "LLMReply" not in _MOEGIRIL_SRC
    assert "build_model_router" not in _MOEGIRIL_SRC


def test_question_handler_no_longer_self_answers() -> None:
    """问句处理程序不再自答：不再有 bot.moegirl 直出结果，统一转交 bot.chat。"""
    tree = ast.parse(_INIT_SRC)
    src = _function_source(tree, "_handle_moegirl_question")
    assert src is not None
    assert "_run_capability_through_pipeline" not in src
    assert 'capability_id="bot.moegirl"' not in src
    assert "_moegirl_answer_via_chat" in src
    assert "kb_grounding_text" in src, "接地必须经消息契约进聊天链"


def test_explicit_handler_routes_hits_to_chat() -> None:
    tree = ast.parse(_INIT_SRC)
    src = _function_source(tree, "_handle_moegirl")
    assert src is not None
    assert "_moegirl_answer_via_chat" in src
    assert "kb_grounding_text" in src


def test_shared_forward_exit_sends_to_chat_once() -> None:
    """两萌百入口汇合的唯一出口：只调一次 pipeline.handle_async 且交 bot.chat。"""
    tree = ast.parse(_INIT_SRC)
    src = _function_source(tree, "_moegirl_answer_via_chat")
    assert src is not None
    assert 'capability_id="bot.chat"' in src
    assert src.count("pipeline.handle_async") == 1, "一次生成=一条转发缝，禁第二通路"
    assert 'capability_id="bot.moegirl"' not in src


def test_chat_grounding_leg_uses_central_guard_not_handbuilt_literal() -> None:
    """拼接点禁手拼「不可信上下文」字面量——只能经 guard_secondhand_text。"""
    chat_src = (
        _ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
    ).read_text(encoding="utf-8")
    assert "guard_secondhand_text(kb_grounding_text" in chat_src, (
        "接地腿必须经中央件包裹"
    )
    idx = chat_src.find("guard_secondhand_text(kb_grounding_text")
    window = chat_src[max(0, idx - 700) : idx + 400]
    assert "不可信上下文，仅供参考" not in window
