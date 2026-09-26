"""创造者双名注入回归（审查 G-05：单一事实源）。

覆盖四块：
1. addressing.py 常量与取用函数非空、取用函数读模块常量；
2. monkeypatch CREATOR_ALIASES 能改变称谓分区/管理团队规则/注入行的行为
   ——证明没有第二份硬编码的双名散落判断；
3. chat 人格上下文（普通对话）稳定含创造者事实一行（【创造者】分区）；
4. 注入文案为客观陈述：单行、简短、无感叹/疑问/第一人称口吻。

红线：澜汐=霞月（双名同一人），是守岸人的创造者与唤醒者、生产超管；
事实由代码结构化持有，不依赖人格文件。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_admin_roster_text,
    build_chat_prompt,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import addressing

# ---------------------------------------------------------------------------
# 1. 常量与取用函数非空
# ---------------------------------------------------------------------------


def test_constants_and_accessors_nonempty() -> None:
    aliases = addressing.CREATOR_ALIASES
    assert aliases, "CREATOR_ALIASES 不得为空（双名事实单一事实源）"
    assert all(str(alias).strip() for alias in aliases)
    assert addressing.CREATOR_NOTE.strip(), "CREATOR_NOTE 不得为空"
    # 取用函数必须读模块常量（monkeypatch 才能生效）。
    assert addressing.creator_aliases() == aliases
    assert addressing.creator_context_note() == addressing.CREATOR_NOTE


# ---------------------------------------------------------------------------
# 2. monkeypatch 行为随动 = 无第二份硬编码
# ---------------------------------------------------------------------------


def _master_ctx():
    return addressing.build_addressing_context(
        session_type="group",
        sender_display_name="管理员甲",
        sender_roles=["user", "super_admin"],
    )


def test_master_branch_follows_patched_aliases(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_ALIASES", ("阿澈", "小澄"))
    instruction = _master_ctx().instruction
    assert "阿澈" in instruction and "小澄" in instruction
    # 替换后旧双名字面必须整体消失：证明 master 分支没有第二份硬编码。
    assert "澜汐" not in instruction and "霞月" not in instruction


def test_master_branch_single_alias_wording(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_ALIASES", ("阿澈",))
    instruction = _master_ctx().instruction
    assert "超级管理员就是阿澈" in instruction
    assert "这个名字指同一位创造者与唤醒者" in instruction
    assert "阿澈是谁" in instruction


def test_master_branch_empty_aliases_omit_dual(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_ALIASES", ())
    instruction = _master_ctx().instruction
    assert "创造者与唤醒者" not in instruction
    # 头部称谓边界保留，仅双名段整块不出现。
    assert instruction.startswith("当前是群聊")


def test_admin_roster_rules_follow_patched_aliases(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_ALIASES", ("阿澈", "小澄"))
    config = SimpleNamespace(
        bot_super_admin_user_ids=["999"],
        bot_admin_profiles=[],
    )
    text = build_admin_roster_text(config)
    assert "阿澈、小澄是守岸人的创造者与唤醒者" in text
    assert "澜汐" not in text and "霞月" not in text


def test_note_accessor_follows_patched_note(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_NOTE", "测试事实行。")
    assert addressing.creator_context_note() == "测试事实行。"


# ---------------------------------------------------------------------------
# 3. chat 人格上下文普通对话含创造者事实一行
# ---------------------------------------------------------------------------

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"


def _context() -> ContextBundle:
    """最小 ContextBundle（样板：tests/test_persona_prompt_and_memory.py）。"""
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
        conversation_history=ConversationHistoryResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        current_message="你好",
        sender_id="user-1",
        session_id="private:user-1",
    )


def test_chat_context_contains_creator_note_partition() -> None:
    prompt = build_chat_prompt(_context())[0]["content"]
    # 普通对话稳定可见：不依赖管理配置，独立分区整行注入。
    assert "【创造者】" in prompt
    assert addressing.CREATOR_NOTE in prompt


def test_creator_partition_follows_patched_note(monkeypatch) -> None:
    monkeypatch.setattr(addressing, "CREATOR_NOTE", "测试：创造者是阿澈。")
    prompt = build_chat_prompt(_context())[0]["content"]
    assert "【创造者】" in prompt
    assert "测试：创造者是阿澈。" in prompt
    assert addressing.CREATOR_ALIASES[0] not in prompt


# ---------------------------------------------------------------------------
# 4. 注入文案为客观陈述
# ---------------------------------------------------------------------------


def test_note_is_single_objective_line() -> None:
    note = addressing.CREATOR_NOTE
    assert "\n" not in note, "预算一行：不得折行"
    assert len(note) <= 120, "措辞客观简短：超出一行预算"
    # 客观陈述：无感叹/疑问语气，无第一人称口吻。
    assert not any(ch in note for ch in "！？!?")
    assert "我" not in note
    # 事实三要素齐备：双名同一人/创造者身份/超管身份。
    for keyword in ("同一人", "创造者", "超级管理员"):
        assert keyword in note
