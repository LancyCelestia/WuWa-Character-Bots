"""点名/昵称检测测试。"""

from plugins.bot_unified_runtime.runtime.mentions import detect_name_mention

TERMS = ["岸宝", "守岸人"]


def test_leading_name_with_separator_counts_as_mention():
    assert detect_name_mention("岸宝，帮我查天气", TERMS) is True
    assert detect_name_mention("守岸人 今天天气怎么样", TERMS) is True


def test_exact_name_counts_as_mention():
    assert detect_name_mention("守岸人", TERMS) is True


def test_call_verb_before_name_counts_as_mention():
    assert detect_name_mention("呼叫守岸人", TERMS) is True
    assert detect_name_mention("@守岸人", TERMS) is True


def test_name_in_middle_with_punctuation_counts_as_mention():
    assert detect_name_mention("大家晚上好，守岸人，在吗？", TERMS) is True


def test_name_prefix_with_time_word_counts_as_mention():
    assert detect_name_mention("守岸人今天好可爱", TERMS) is True


def test_infix_word_containing_name_does_not_count():
    assert detect_name_mention("岸宝贝 在哪", TERMS) is False


def test_plain_chat_without_name_does_not_count():
    assert detect_name_mention("随便聊聊天气", TERMS) is False
    assert detect_name_mention("", TERMS) is False
