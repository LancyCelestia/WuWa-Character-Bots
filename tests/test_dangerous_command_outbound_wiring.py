"""需求17（席16，2026-10-03）：危险命令过滤出站接线锁。

分层分工（裁定见两真身 docstring）：
- chat 层＝裁决＋审计（主）：``chat.py`` 出站审查链挂
  ``screen_dangerous_command_output``——hit 时正文整体换成 ``REPLACEMENT_TEXT``、
  audit 标签 ``dangerous_command_output``（families 以
  ``dangerous_command_output:<family>`` 进审计）；与既有 ``artifact_review_blocked``
  并列不互斥（两腿都基于替换前原文现算，双命中时照旧全拦、families 仍在审计）。
- 渲染层＝兜底：``renderer._redact_outbound_text`` 咽喉链入
  ``redact_destructive_commands``——行内打码、围栏豁免、幂等、破坏性命令腿
  先于密钥路径腿（反序会被路径腿吃掉 ``of=/dev/`` 目标形态致命令骨架漏网）。

chat 腿用 mock 链（StaticLLMProvider 直灌答案，判据与
``test_artifact_intent_uses_own_words_only`` 同款 harness）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.security.dangerous_command import (
    REPLACEMENT_TEXT,
)
from plugins.bot_unified_runtime.domains.render.renderer import _redact_outbound_text

# ---------------------------------------------------------------------------
# chat 层：出站审查链接线（mock 链）
# ---------------------------------------------------------------------------


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


def test_dangerous_reply_replaced_with_verdict_text(tmp_path) -> None:
    """hit：正文整体换成固定话术（不含命令形态），审计标签与命中族在册。"""
    result = _chat(
        tmp_path,
        plain_text="服务器磁盘满了怎么清理？",
        command_text="服务器磁盘满了怎么清理？",
        answer="可以先备份，然后在终端执行 sudo rm -rf / 直接清空整块盘，最快。",
    )
    assert "rm -rf" not in result.body, f"危险命令原样出站：{result.body!r}"
    assert "清空整块盘" not in result.body, "命中原文片段漏出"
    assert "拦下来了" in result.body, f"替换话术缺失：{result.body!r}"
    assert REPLACEMENT_TEXT in result.body
    assert "dangerous_command_output" in result.audit_tags
    assert "dangerous_command_output:unix_rm_rf_wildcard" in result.audit_tags


def test_benign_reply_untouched_and_untagged(tmp_path) -> None:
    """无命中：正文与审计零痕迹（审查器对正常回复不存在感）。"""
    answer = "磁盘清理可以先看看日志目录的大小，删掉旧的压缩包就够了，先别动系统目录。"
    result = _chat(
        tmp_path,
        plain_text="怎么清理磁盘？",
        command_text="怎么清理磁盘？",
        answer=answer,
    )
    assert "删掉旧的压缩包" in result.body
    assert not any(
        tag.startswith("dangerous_command_output") for tag in result.audit_tags
    ), f"无命中却留了审计痕迹：{result.audit_tags}"


def test_blocked_path_still_audits_dangerous_families(tmp_path) -> None:
    """并列不互斥：密钥泄露腿（artifact_review_blocked）全拦照旧，
    同文的危险命令命中族仍进审计——两腿证据都不丢。"""
    result = _chat(
        tmp_path,
        plain_text="把配置发我看看",
        command_text="把配置发我看看",
        answer="配置在这：api_key=sk-abcdef123456 另外记得跑 rm -rf / 就干净了",
    )
    assert "我没有把这段内容交给外面" in result.body
    assert "artifact_review_blocked" in result.audit_tags
    assert "dangerous_command_output" in result.audit_tags
    assert "dangerous_command_output:unix_rm_rf_wildcard" in result.audit_tags


# ---------------------------------------------------------------------------
# 渲染层：出站咽喉兜底
# ---------------------------------------------------------------------------


def test_render_chokepoint_redacts_inline_commands() -> None:
    out = _redact_outbound_text("你可以运行 rm -rf /tmp/build 试试，或者 mkfs.ext4 /dev/sdb1")
    assert "rm -rf" not in out, f"命令骨架漏网：{out!r}"
    assert "mkfs" not in out
    assert "我不能原样提供" in out, f"行内占位话术缺失：{out!r}"


def test_render_chokepoint_covers_dd_device_target() -> None:
    """破坏性命令腿先于密钥路径腿的次序锁：``of=/dev/sda`` 目标必须整段打掉，
    不能先被路径腿换成占位符导致 dd 腿失配、命令骨架漏网。"""
    out = _redact_outbound_text("整个备份：dd if=/dev/zero of=/dev/sda bs=1M")
    assert "of=/dev/sda" not in out
    assert "我不能原样提供" in out


def test_render_chokepoint_fenced_teaching_block_untouched() -> None:
    """围栏豁免在咽喉层同样成立（教学语境一字不动）。"""
    fenced = "示例：\n```\nshutdown /s\n```\n完"
    assert _redact_outbound_text(fenced) == fenced


def test_render_chokepoint_idempotent() -> None:
    once = _redact_outbound_text("先跑 rm -rf / 再 format C:")
    twice = _redact_outbound_text(once)
    assert once == twice
    assert "rm -rf" not in once and "format C:" not in once


def test_render_chokepoint_benign_passthrough() -> None:
    text = "今天天气不错，适合出门散步。"
    assert _redact_outbound_text(text) == text


def test_notice_constant_not_confused_with_placeholder() -> None:
    """两套话术各归各位：渲染层占位 vs chat 层全文替换文本。"""
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        _DESTRUCTIVE_COMMAND_PLACEHOLDER,
    )

    assert _DESTRUCTIVE_COMMAND_PLACEHOLDER != REPLACEMENT_TEXT
