"""百科通道关闭／零命中时，必须把"这轮没有资料"送到模型眼前，且禁式要覆盖存在性断言。

起因（实弹）：2026-09-25 17:29 澜汐问"你认识蓝毒吗"，bot 答"泰缇斯流转的漫长记录里，
并没有名为蓝毒的共鸣者"——而明日方舟 wiki 库里 `title like '%蓝毒%'` 实测 **103 行**。
根因两条（都在这份锁里钉）：
① `BOT_KB_WIKI_ENABLED=false` 时检索器返回 `_UnavailableVectorKnowledgeProvider` ⇒
   本轮零知识块 ⇒ `chat.py` 那句 `if context.knowledge_results.chunks:` 让【知识库】分区
   **整块不出现** ⇒ 模型完全不知道自己没资料，只能拿人格先验硬答；
② `_RUNTIME_CONTEXT_USAGE` 的"不要把没检索到写成不存在"只枚举**时效类**判断
   （发布/生效/赛事/价格/面世…），**"某角色/设定不存在"这类存在性断言不在射程内**。
"""
from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.runtime.prompt_preview import (
    build_prompt_preview,
)


def _config(tmp_path: Path, **overrides: object) -> Config:
    base: dict[str, object] = {
        "bot_chat_provider": "static",
        "bot_chat_model": "static",
        "bot_persona_files": [],
        "bot_knowledge_files": [],
        "bot_runtime_data_dir": str(tmp_path),
        "bot_prompt_audit_dir": "",
        # 复现现场：百科检索关闭（今天的生产实况就是这个态）。
        "bot_kb_wiki_enabled": False,
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


def _system_text(tmp_path: Path, question: str, **overrides: object) -> str:
    result = build_prompt_preview(question, config=_config(tmp_path, **overrides))
    assert result["ok"] is True and result["llm_called"] is False
    messages = result["messages"]
    assert messages and messages[0]["role"] == "system"
    return str(messages[0]["content"])


def test_zero_knowledge_still_declares_availability(tmp_path: Path) -> None:
    """本轮零知识块时，提示词里必须有一句"这轮没有资料"，且不能被读成"事物不存在"。"""
    text = _system_text(tmp_path, "你认识蓝毒吗")
    assert "【知识库】" in text, "零命中时分区整块消失＝模型不知道自己没资料（这条就是那条事故）"
    declaration = text.split("【知识库】", 1)[1][:400]
    assert ("没有" in declaration and "资料" in declaration) or "未启用" in declaration
    # 声明本身必须带"不等于不存在"这一半，否则只是换一句可被读成否定的话
    assert "不等于" in declaration or "不代表" in declaration


def test_availability_line_is_honest_in_both_states(tmp_path: Path) -> None:
    """通道开启却仍零命中时，同一句声明也要在场（不许只给"关闭态"补，留另一个洞）。"""
    text = _system_text(tmp_path, "蓝毒是谁", bot_kb_wiki_enabled=True)
    assert "【知识库】" in text
    declaration = text.split("【知识库】", 1)[1][:400]
    assert "不等于" in declaration or "不代表" in declaration


def test_forbidden_forms_cover_existence_claims(tmp_path: Path) -> None:
    """禁式必须点名「记录里没有这个人／这个设定不存在」这一族，且这条要真进生产提示词。

    为什么测在模块常量＋装配函数两层：`build_prompt_preview` 走的是 persona 字段重组路径，
    而 `_RUNTIME_CONTEXT_USAGE` 总说明只在**人设原文（verbatim）路径**里注入——生产用的是后者。
    只测常量＝钉住一句话；只测 preview＝测不到那条路径。两层各钉一遍才咬得住。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    #  distinctive 短语：只有存在性那一族禁式里才有（"不存在"三字在可用性声明里也出现，
    #  拿它当判据会自证通过，所以故意选一个别处不会有的说法）
    ban = "以世界观名义把它推到别的宇宙去"
    assert ban in chat._RUNTIME_CONTEXT_USAGE, "禁式段没点到存在性否定这一族"
    assert "资料没接到" in chat._RUNTIME_CONTEXT_USAGE

    prompt = chat._compose_persona_verbatim_prompt(
        raw_persona="你是守岸人。",
        reply_detail="brief",
        dynamic_parts=["", "【知识库】", chat._KB_UNAVAILABLE_LINE],
        context_budget=8000,
    )
    assert ban in prompt, "禁式在册却没进生产路径的提示词"


def test_availability_lock_is_data_driven_not_a_hardcoded_string(tmp_path: Path) -> None:
    """自证：上面的"分区必在场"不是把字符串写死——有知识块时分区里应是块内容。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
    from plugins.bot_unified_runtime.domains.core.contracts.character import (
        ContextBundle,
        KnowledgeChunk,
        MemoryRetrievalResult,
        PersonaProfile,
        RetrievalResult,
        ToneProfile,
    )

    with_chunk = RetrievalResult(
        request_id="t1",
        chunks=[
            KnowledgeChunk(
                chunk_id="c1",
                source_id="kb_wiki",
                title="蓝毒",
                content="明日方舟狙击干员，蓝毒是罗德岛的术师型狙击干员。",
            )
        ],
    )
    ctx = ContextBundle(
        request_id="t1",
        persona=PersonaProfile(
            profile_id="default", version="t", display_name="守岸人", identity="测试用"
        ),
        tone=ToneProfile(profile_id="default", mode="private_chat"),
        memory_results=MemoryRetrievalResult(request_id="t1"),
        knowledge_results=with_chunk,
        current_message="蓝毒是谁",
        sender_id="u1",
        session_id="group_1_1",
    )
    lines = chat._knowledge_lines(ctx)
    assert "蓝毒" in lines
    assert "本轮没有任何百科" not in lines, "有块时还塞可用性声明＝声明变成了噪声"
