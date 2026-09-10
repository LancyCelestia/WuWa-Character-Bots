"""小名自学提取回归：否定语境排除 + 语气词不粘名（handoff C-1）。

extract_learned_nickname 是被动感知的纯函数部分；停用词/长度/与当前名去重
等守卫在 __init__ 调用点，不在本文件范围。
"""

from plugins.bot_unified_runtime.character.affinity import extract_learned_nickname


def test_positive_nickname_learned_without_particle() -> None:
    assert extract_learned_nickname("以后叫我小岸吧") == "小岸"
    assert extract_learned_nickname("你可以叫我阿月哦") == "阿月"
    assert extract_learned_nickname("叫我小岸就好") == "小岸"
    assert extract_learned_nickname("就叫我阿月") == "阿月"
    assert extract_learned_nickname("以后喊我小岸呀~") == "小岸"


def test_adjacent_negation_not_learned() -> None:
    for text in (
        "别叫我小岸",
        "不要喊我小岸",
        "不许叫我小岸",
        "不准喊我小岸",
        "千万别叫我小岸",
        "千万别喊我小岸",
        "都别喊我小岸",
        "谁都不要喊我小岸",
    ):
        assert extract_learned_nickname(text) is None, text


def test_separated_negation_not_learned() -> None:
    for text in (
        "谁叫我小岸",
        "谁能喊我小岸吗",
        "千万、叫我小岸哦",
        "别、叫我小岸吧",
    ):
        assert extract_learned_nickname(text) is None, text


def test_negation_elsewhere_still_learns() -> None:
    assert extract_learned_nickname("别理他们，以后叫我小岸") == "小岸"
    assert extract_learned_nickname("那个谁，以后叫我小岸吧") == "小岸"
    assert extract_learned_nickname("谁都别欺负他，以后叫我小岸") == "小岸"


def test_no_trigger_returns_none() -> None:
    assert extract_learned_nickname("今天天气不错") is None
    assert extract_learned_nickname("") is None
