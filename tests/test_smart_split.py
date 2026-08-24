"""智能回复切分 v3 测试：最多 3 条、优先 1 条、均衡、符号/emoji 安全。"""

from plugins.bot_unified_runtime.runtime.smart_split import (
    _is_safe_cut,
    split_reply_messages,
)


def test_short_text_stays_single():
    assert split_reply_messages("我在这里。") == ["我在这里。"]


def test_moderately_long_text_prefers_one_message():
    text = (
        "第一段内容写得足够长一点，方便测试平衡切分成两条消息。\n\n"
        "第二段内容写得足够长一点，方便测试平衡切分成两条消息。\n\n"
        "第三段内容写得足够长一点，方便测试平衡切分成两条消息。\n\n"
        "第四段内容写得足够长一点，方便测试平衡切分成两条消息。\n\n"
        "第五段内容写得足够长一点，方便测试平衡切分成两条消息。\n\n"
        "第六段内容写得足够长一点，方便测试平衡切分成两条消息。"
    )
    parts = split_reply_messages(text, max_parts=3, target_chars=520, min_chars=220)
    assert len(parts) == 1


def test_long_text_splits_balanced_and_at_most_three():
    text = ("守岸人望着远处的海面，声音像被风吹散了一样。" * 30) + "\n\n" + (
        "漂泊者沿着石阶走上来，衣摆沾着盐雾。" * 30
    ) + "\n\n" + ("她轻轻应了一声，把话藏在潮声里。" * 30)
    parts = split_reply_messages(text, max_parts=3, target_chars=520, min_chars=220, hard_max=900)
    assert 2 <= len(parts) <= 3, len(parts)
    lengths = [len(part) for part in parts]
    assert max(lengths) - min(lengths) < 350
    assert "\n\n".join(parts) == text


def test_prefers_single_message_for_moderate_length():
    text = "守岸人望着远处的海面，声音像被风吹散了一样。" * 36
    parts = split_reply_messages(text, max_parts=3, target_chars=520, min_chars=220, hard_max=900)
    assert len(parts) == 1


def test_ellipsis_and_dash_stay_at_previous_end():
    text = "守岸人望着海面……\n\n风从很远的地方吹来——\n\n她轻轻应了一声。"
    parts = split_reply_messages(text, max_parts=3, target_chars=10, min_chars=5)
    for part in parts:
        assert not part.startswith(("……", "——"))


def test_no_split_inside_emoji_continuation():
    text = ("守岸人站在那里（≧▽≦）声音很轻。" * 6) + "然后是💙💙💙的星光。"
    parts = split_reply_messages(text, max_parts=3, target_chars=100, min_chars=40, hard_max=120)
    for part in parts:
        assert not part.startswith(("\u200d", "\ufe0f", "\ufe0e"))


def test_safe_cut_rejects_emoji_continuation():
    zwj = "\U0001f499\u200d\U0001f499"
    assert _is_safe_cut(zwj, 1) is False
    assert _is_safe_cut("abc\U0001f600def", 3) is True
