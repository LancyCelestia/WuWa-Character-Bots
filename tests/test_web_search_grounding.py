"""S-W6 · 联网/时效接地披露回归门（本席新建、独占，未跟踪件）。

验收线三件事（对齐简报 S-W6 Step 1）：
  (a) 本轮走了检索却没结果（``web_search_context`` 非 None 但 ``hits`` 空）⇒ 交给模型的
      system prompt 必须出现「本轮未联网」披露，且出现「训练知识有截止日期、无检索块时
      不得断言某事物尚未发生」性质的约束。
  (b) 已检索（``hits`` 非空）⇒ 【联网检索】块逐字节不变（等于 ``_web_search_lines`` 原样
      输出），且绝不掺入「未检索」噪声。
  (c) 非时效闲聊（``web_search_context is None``）⇒ 不得多出「未联网」披露、不出【联网检索】块
      （但知识截止属常驻总说明、闲聊也在，那是 topic-independent 诚实底线，不算噪声）。

现状预判：(a) 因披露不可达 + 无截止声明而 FAIL；(c) 因无截止声明而 FAIL；(b) 已 PASS。
全离线：不联网、不写源码树、不起进程、不 import 被测模块的副作用面（只调纯函数）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
    WebSearchContext,
    WebSearchHit,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _web_search_lines,
    build_chat_prompt,
)

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"

# 本席在 chat.py 落的字面量锚，测试与实现同源（改措辞要同步改这里，是刻意的摩擦）。
NOT_SEARCHED_DISCLOSURE = "未按需联网检索现实时效信息"
CUTOFF_ANCHOR = "训练截止日期"
CUTOFF_ASSERT_ANCHOR = "不要把「没检索到」当成「现实中没发生」"
WEB_BLOCK_LABEL = "【联网检索】"


def _context(
    *,
    web_search_context: WebSearchContext | None = None,
    current_message: str = "你好呀，随便聊聊",
) -> ContextBundle:
    # context_budget 给足，避免测试被预算裁剪误伤（本席测的是可达性，不是截断）。
    return ContextBundle(
        request_id="req-1",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text=PERSONA_TEXT,
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        current_message=current_message,
        sender_id="user-1",
        session_id="private:user-1",
        web_search_context=web_search_context,
        context_budget=8192,
    )


def _system_prompt(context: ContextBundle) -> str:
    return build_chat_prompt(context)[0]["content"]


def test_a_empty_hits_turn_discloses_not_online_and_knowledge_cutoff() -> None:
    """(a) 走了检索却零结果：未联网披露 + 知识截止约束都必须到模型眼前。"""
    context = _context(
        web_search_context=WebSearchContext(
            request_id="req-1", query="英伟达最新财报", hits=[]
        ),
        current_message="英伟达最新财报怎么样",
    )
    prompt = _system_prompt(context)
    assert NOT_SEARCHED_DISCLOSURE in prompt, "零结果轮未把『本轮未联网』披露送进 prompt"
    assert WEB_BLOCK_LABEL in prompt, "零结果轮未渲染【联网检索】块"
    assert CUTOFF_ANCHOR in prompt, "缺少训练知识截止声明"
    assert CUTOFF_ASSERT_ANCHOR in prompt, "缺少『无检索块不得断言尚未发生』约束"


def test_b_hits_block_byte_identical_and_no_disclosure() -> None:
    """(b) 命中结果：块内容逐字节 = 函数原样输出，且不掺『未检索』噪声。"""
    context = _context(
        web_search_context=WebSearchContext(
            request_id="req-1",
            query="新版本更新了什么",
            hits=[
                WebSearchHit(
                    title="新版本攻略",
                    snippet="新增追忆祝福",
                    url="https://example.com/read/1",
                    source_domain="example.com",
                )
            ],
        ),
        current_message="这个游戏新版本更新了什么",
    )
    prompt = _system_prompt(context)
    expected_block = _web_search_lines(context, 10_000)
    assert expected_block in prompt, "命中块内容与 _web_search_lines 输出不再逐字节一致"
    assert WEB_BLOCK_LABEL in prompt
    assert NOT_SEARCHED_DISCLOSURE not in prompt, "有结果时不应掺入『未检索』披露"


def test_c_idle_chat_has_no_per_turn_disclosure() -> None:
    """(c) 闲聊（未走检索）：不得多出『未联网』披露、不出块；但知识截止常驻。"""
    context = _context(web_search_context=None, current_message="今天天气不错，随便聊聊")
    prompt = _system_prompt(context)
    assert NOT_SEARCHED_DISCLOSURE not in prompt, "闲聊轮不应常驻『未联网』披露（噪声）"
    assert WEB_BLOCK_LABEL not in prompt, "闲聊轮不应出现【联网检索】块"
    # 知识截止是 topic-independent 的诚实底线，闲聊也在，且它不进 per-turn 披露面。
    assert CUTOFF_ANCHOR in prompt, "知识截止声明应常驻总说明"
    assert CUTOFF_ASSERT_ANCHOR in prompt
