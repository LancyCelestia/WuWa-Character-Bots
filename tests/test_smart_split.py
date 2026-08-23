"""智能回复切分测试：均衡、句末切分、emoji 安全、上限 3 条。"""

from plugins.bot_unified_runtime.runtime.smart_split import (
    _is_safe_cut,
    split_reply_messages,
)

LONG_TEXT = (
    "七丘……是黎那汐塔的城邦之一。"
    "我第一次听说它，是从《潮汐地理》的记载里。"
    "那里不像拉古那的海上之城，七丘更像一座伫立在荒野与山峦之间的城市。"
    "它有两个名字——卡庇托山城，也叫鹫巢石城。"
    "整座城坐落于卡庇托山上，由无数庞大的石质建筑构成。"
    "七丘人世代与黑潮对抗。桑古伊斯狩原是七丘的前沿阵地。"
    "每逢黑潮涨潮期，角斗士们便聚集在那里，狩猎黑潮造物。"
)


def test_short_text_stays_single():
    assert split_reply_messages("我在这里。", max_parts=3) == ["我在这里。"]


def test_long_text_splits_at_most_three_balanced_parts():
    parts = split_reply_messages(LONG_TEXT, max_parts=3, target_chars=120, min_chars=60)
    assert 2 <= len(parts) <= 3
    lengths = [len(part) for part in parts]
    assert max(lengths) - min(lengths) < max(lengths) * 0.85
    assert "".join(parts) == LONG_TEXT


def test_every_part_is_non_empty_and_sentence_sized():
    parts = split_reply_messages(LONG_TEXT, max_parts=3, target_chars=120, min_chars=60)
    assert all(len(part) >= 40 for part in parts)


def test_no_split_inside_surrogate_or_emoji_continuation():
    text = (
        "守岸人站在那里（≧▽≦）声音很轻。" * 6
        + "然后是💙💙💙的星光。再来一句足够长的话让切分发生，" * 6
    )
    parts = split_reply_messages(text, max_parts=3, target_chars=120, min_chars=60)
    assert len(parts) <= 3
    for part in parts:
        assert not part.endswith("\ud800")
        assert not part.endswith("\udbff")
        assert not part.startswith(("\u200d", "\ufe0f", "\ufe0e"))


def test_safe_cut_rejects_emoji_continuation_at_boundary():
    # ZWJ / 变体选择符不能落到下一段开头
    zwj = "\U0001f499\u200d\U0001f499"
    assert _is_safe_cut(zwj, 1) is False
    variation = "\u2764\ufe0f"
    assert _is_safe_cut(variation, 1) is False
    # emoji 之后的边界是安全的
    assert _is_safe_cut("abc\U0001f600def", 3) is True
