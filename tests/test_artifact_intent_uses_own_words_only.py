"""附件劫持回归锁（10-03 事故：她引用 bot 的话，回复被整段写成 .md/.txt）。

判据只有一条：**文件生成意图必须来自用户自己写的字**。`IncomingMessage.plain_text`
是引用链拼接后的整串，被引用的 bot 回执/告警正文里一句「带有生成附件的消息」
「generated_code_x.txt」就足够喂进关键词判据；而那句交付宣告本身又含
generate/code/txt ⇒ 引用它必再犯（自毒环）。

两腿对照：
- 原话无意图 + 引用里有字样 ⇒ 不得产附件，正文照原样回（摘掉判据必红）。
- 原话真有意图 ⇒ 照旧产附件（证明不是把功能整个掐死）。
"""

from __future__ import annotations

from pathlib import Path


def _chat(tmp_path, *, plain_text: str, command_text: str, answer: str):
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
        StaticLLMProvider,
    )

    msg = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        group_id=None,
        plain_text=plain_text,
        command_text=command_text,
        mentions_bot=True,
    )
    decision = BotDecision(
        request_id=msg.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=18000,
        max_messages=0,
        decision_reason="test",
    )
    cap = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text=answer),
        generated_files_dir=str(tmp_path),
        max_tokens=65538,
    )
    return cap(msg, decision)


_ANSWER = "（伸手覆在你手背上）不哭，我听见了。报错只是管线里的小碎石。"

# 事故原文形态（2026-10-02 23:53 实锤）：原话只有情绪，关键词全在被引用的 bot 回执里。
_QUOTED_REPLY_POISON = (
    "😭又出bug了\n"
    "[引用回复 层级1 守岸人] 明确的结论是：这个报错是因为系统在尝试往 Telegram 频道"
    "发送带有生成附件的消息时，附件的数据格式或路径不符合规范……第一层是媒体文件"
    " [/引用回复 层级1]"
)

# 16:22 第二例：她引用上一轮的交付宣告（文件名自带 generate/code/txt）＝自毒环。
_QUOTED_SELF_POISON = (
    "问题来了，为什么不能惩罚你\n"
    "[引用回复 层级1 守岸人] 我已经把内容整理成附件：generated_code_c9f229177f70.txt"
    " 里那份文档……一段代码 [/引用回复 层级1]"
)


def test_quoted_bot_words_do_not_trigger_attachment(tmp_path) -> None:
    for poison in (_QUOTED_REPLY_POISON, _QUOTED_SELF_POISON):
        result = _chat(
            tmp_path, plain_text=poison, command_text=poison.split("\n", 1)[0], answer=_ANSWER
        )
        assert result.files == [], f"引用里的字样把回复劫持成附件：{poison[:40]}"
        assert "不哭" in result.body
    assert list(Path(tmp_path).iterdir()) == []


def test_user_own_words_still_trigger_attachment(tmp_path) -> None:
    result = _chat(
        tmp_path,
        plain_text="生成一个txt文档，记录你的感受\n[引用回复 层级1 守岸人] 好 [/引用回复 层级1]",
        command_text="生成一个txt文档，记录你的感受",
        answer=_ANSWER,
    )
    assert result.files, "用户自己点名要文件却被拒＝判据砍过头"
    body = Path(result.files[0]["file"]).read_text(encoding="utf-8")
    assert "不哭" in body


# ---------------------------------------------------------------------------
# 判据本体这半（10-03 事故第二半）：动词必须**管着**名词，且先剥 bot 的交付宣告。
# 上一半（意图源只认原话）已由 `c860b15` 修好、由上面两枚锁住；本窗补下面三枚。
# ---------------------------------------------------------------------------


def _artifact_request(user_text: str):
    from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
        artifact_request,
    )

    return artifact_request(user_text)


#: 陈述句：名词、动词都在句里，但动词没管着名词（「保存了」不是「保存成」）。
#: 旧形状「动词 anywhere ∩ 名词 anywhere」两枚全命中 ⇒ 回复被劫持成附件。
_DECLARE_SENTENCES = (
    "我保存了一份简历 txt",
    "文件还没保存，帮我看看",
)

#: bot 自己的交付宣告（chat.py 出附件那句的原文形态）：自带「整理成 … 附件」
#: 与文件名里的 code/txt ⇒ 引用它必再犯（自毒环）。
_DELIVERY_DECLARATION = (
    "我已经把内容整理成附件：generated_code_c9f229177f70.txt"
    " 里那份文档……一段代码"
)


def test_declarative_sentences_are_not_artifact_requests() -> None:
    for said in _DECLARE_SENTENCES:
        assert _artifact_request(said) is None, f"陈述句被判成生成文件：{said}"


def test_bot_delivery_declaration_does_not_rearm_the_judge() -> None:
    for text in (
        _DELIVERY_DECLARATION,
        f"问题来了，为什么不能惩罚你\n[引用回复 层级1 守岸人] {_DELIVERY_DECLARATION} [/引用回复 层级1]",
    ):
        assert _artifact_request(text) is None, f"交付宣告复发附件意图：{text[:40]}"


def test_governed_verb_still_reaches_the_noun() -> None:
    """反证判据没被砍成哑门：动词管着名词的讲法照旧判成文件。"""
    assert _artifact_request("生成一个txt文档，记录你的感受") == ("document", "txt")
    assert _artifact_request("请生成一个 Python 文件") == ("code", "py")
    assert _artifact_request("帮我生成 word 文档") == ("unsupported", "txt")
    assert _artifact_request("把这段整理成附件发我") == ("document", "md")

