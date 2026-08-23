"""智能回复切分 v2：每 3 段一条消息、段数不设上限、省略号/破折号/emoji 安全。"""

from plugins.bot_unified_runtime.runtime.smart_split import (
    _is_safe_cut,
    split_reply_messages,
)


def test_short_text_stays_single():
    assert split_reply_messages("我在这里。") == ["我在这里。"]


def test_six_paragraphs_become_two_messages_of_three():
    text = "\n\n".join(
        [
            "第一段内容写得足够长一点，方便测试平衡切分成两条消息。",
            "第二段内容写得足够长一点，方便测试平衡切分成两条消息。",
            "第三段内容写得足够长一点，方便测试平衡切分成两条消息。",
            "第四段内容写得足够长一点，方便测试平衡切分成两条消息。",
            "第五段内容写得足够长一点，方便测试平衡切分成两条消息。",
            "第六段内容写得足够长一点，方便测试平衡切分成两条消息。",
        ]
    )
    parts = split_reply_messages(text, units_per_message=3, target_chars=160, min_chars=15)
    assert len(parts) == 2, parts
    assert all(part.count("\n\n") == 2 for part in parts)


def test_nine_paragraphs_become_three_messages():
    text = "\n\n".join(
        [f"第{i}段内容写得足够长，方便打包成三条消息测试。" for i in range(1, 10)]
    )
    parts = split_reply_messages(text, units_per_message=3, target_chars=180, min_chars=15)
    assert len(parts) == 3, parts


def test_ellipsis_and_dash_stay_at_previous_end():
    text = "守岸人望着海面……\n\n" + "风从很远的地方吹来——\n\n" + "她轻轻应了一声。"
    parts = split_reply_messages(text, units_per_message=3, target_chars=10, min_chars=5)
    assert parts
    for part in parts:
        assert not part.startswith(("……", "——"))


def test_no_split_inside_emoji_continuation():
    text = ("守岸人站在那里（≧▽≦）声音很轻。" * 6) + "然后是💙💙💙的星光。"
    parts = split_reply_messages(text, units_per_message=3, target_chars=100, min_chars=40, hard_max=120)
    for part in parts:
        assert not part.startswith(("\u200d", "\ufe0f", "\ufe0e"))


def test_safe_cut_rejects_emoji_continuation():
    zwj = "\U0001f499\u200d\U0001f499"
    assert _is_safe_cut(zwj, 1) is False
    assert _is_safe_cut("abc\U0001f600def", 3) is True
