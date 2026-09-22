"""W3 批次A审计修复回归（离线）。

覆盖：
- 审计#14 输出预算：不限段时保留全部块、单条字符上限仍生效；限段路径不变
- 审计#15 失败话术游标：多线程并发 get/set/逐出零异常，dict 封顶 512
- 审计#16 自动发送：门控与 _COMMAND_RE 对齐；主题含「内容」时正文截取不错位
- 审计#33 Epic 免费游戏：缺 title 记录整行跳过，不 KeyError；正常记录不变
- 审计#35 搜图：引用回复无图给专用提示；无引用维持通用提示
"""

from __future__ import annotations

import threading

from plugins.bot_unified_runtime.capabilities.epic import _format_games
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _FAILURE_MESSAGE_CURSOR,
    _PERSONA_FAILURE_MESSAGES,
    OUTPUT_BUDGET_NOTICE,
    _apply_output_message_budget,
    persona_failure_message,
)
from plugins.bot_unified_runtime.domains.media.capabilities.image_search import (
    build_image_search_capability,
)
from plugins.bot_unified_runtime.domains.schedule.auto_send.parser import (
    is_auto_send_command_text,
    parse_auto_send_command,
)


def _blocks_text(blocks: list[str]) -> str:
    return "\n\n".join(blocks)


def _message(text: str, *, reply_to_text: str = "") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        reply_to_text=reply_to_text,
    )


# ---------------------------------------------------------------- 审计#14


def test_a14_unlimited_messages_multi_block_over_budget_trims_with_notice() -> None:
    # 不限段（max_messages=0）+ 多块 + 总长超单条上限：按单条预算裁剪并追加提示。
    text = _blocks_text(["甲" * 90, "乙" * 90, "丙" * 90])
    result, trimmed = _apply_output_message_budget(text, 0, 200)
    assert trimmed is True
    assert result.endswith(OUTPUT_BUDGET_NOTICE)
    # 裁剪自全部块的拼接结果，而非旧实现的「只看首块后整条原样返回」。
    assert "乙" in result
    assert len(result) == 200


def test_a14_unlimited_messages_multi_block_within_budget_returned_as_is() -> None:
    text = _blocks_text(["甲" * 50, "乙" * 50])
    result, trimmed = _apply_output_message_budget(text, 0, 200)
    assert trimmed is False
    assert result == text


def test_a14_limited_messages_path_unchanged() -> None:
    # 限段路径：块数超限砍尾块；字符未超预算时不二次裁剪。
    text = _blocks_text(["甲" * 40, "乙" * 40, "丙" * 40])
    result, trimmed = _apply_output_message_budget(text, 2, 200)
    assert trimmed is True
    assert result == "甲" * 40 + "\n\n" + "乙" * 40 + "\n\n" + OUTPUT_BUDGET_NOTICE
    assert "丙" not in result
    # 限段且完全在预算内：原样返回。
    result2, trimmed2 = _apply_output_message_budget("短回复", 3, 200)
    assert trimmed2 is False
    assert result2 == "短回复"


# ---------------------------------------------------------------- 审计#15


def test_a15_failure_cursor_concurrent_access_stays_consistent() -> None:
    errors: list[BaseException] = []
    results: list[str] = []
    guard = threading.Lock()

    def worker(worker_index: int) -> None:
        try:
            for index in range(500):
                message = persona_failure_message(f"a15:{worker_index}:{index}")
                with guard:
                    results.append(message)
        except Exception as exc:  # noqa: BLE001 - 收集到主线程断言，不在子线程静默吞掉
            with guard:
                errors.append(exc)

    try:
        threads = [
            threading.Thread(target=worker, args=(worker_index,))
            for worker_index in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert len(results) == 2000
        assert set(results) <= set(_PERSONA_FAILURE_MESSAGES)
        # 游标表封顶 512。
        assert len(_FAILURE_MESSAGE_CURSOR) <= 512
    finally:
        _FAILURE_MESSAGE_CURSOR.clear()


# ---------------------------------------------------------------- 审计#16


def test_a16_gate_accepts_no_space_form_and_rejects_plain_sentences() -> None:
    assert is_auto_send_command_text("报存给A发消息：内容：hi") is True
    assert is_auto_send_command_text("报存 给A发邮件") is True
    assert is_auto_send_command_text("报存给A发邮件，主题：周报，内容：正文") is True
    assert is_auto_send_command_text("报存了三块钱") is False
    assert is_auto_send_command_text("报存给了很多钱") is False


def test_a16_content_extraction_skips_content_word_inside_subject() -> None:
    intent = parse_auto_send_command(
        "报存给A发邮件，主题：周报内容整理，内容：正文 actual",
        actor_sender_id="u1",
        actor_session_id="private:u1",
        actor_session_type=SessionType.PRIVATE,
    )
    assert intent.subject_instruction == "周报内容整理"
    assert intent.content_instruction == "正文 actual"


# ---------------------------------------------------------------- 审计#33


def test_a33_epic_games_without_title_are_skipped() -> None:
    games = [
        {"source": "Epic", "end": "2026-09-18", "url": "https://example.test/epic"},
        {"source": "Steam", "title": "正常游戏", "end": "2026-09-18"},
    ]
    body = _format_games(games)
    assert body.startswith("本周免费游戏：")
    assert "正常游戏" in body
    assert "Epic" not in body


def test_a33_epic_games_normal_records_unchanged() -> None:
    body = _format_games(
        [
            {
                "source": "Steam",
                "title": "Demo",
                "end": "2026-09-18",
                "url": "https://store.steampowered.com/app/1",
            }
        ]
    )
    assert body == (
        "本周免费游戏：\n"
        "- [Steam] Demo（截止 2026-09-18）\n"
        "  https://store.steampowered.com/app/1"
    )


# ---------------------------------------------------------------- 审计#35


def test_a35_reply_without_image_gets_dedicated_hint() -> None:
    capability = build_image_search_capability(config=None)
    result = capability(_message("搜图", reply_to_text="看这张图"), None)
    assert (
        result.body
        == "引用消息里的原图链接拿不到，把图片和『搜图』发在同一条消息里再试一次。"
    )
    assert "image_search_reply_hint" in result.audit_tags


def test_a35_no_reply_no_image_keeps_generic_hint() -> None:
    capability = build_image_search_capability(config=None)
    result = capability(_message("搜图"), None)
    assert (
        result.body
        == "把要搜的图片和『搜图』发在同一条消息里，或直接发图后跟上搜图指令。"
    )
    assert "missing_image" in result.audit_tags
    assert "image_search_reply_hint" not in result.audit_tags
