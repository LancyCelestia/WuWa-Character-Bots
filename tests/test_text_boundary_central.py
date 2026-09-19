"""触发词边界中央谓词（Wave G G-2a/T59）：唯一触发词边界件的行为锁。

规格蓝本：``docs/design/tts-contract-layer.md`` §6（T54 G-1 规格）——
- ``TRIGGER_BOUNDARY_CHARS``：以 ``domains/media/capabilities/tts.py`` 收紧集
  （d3a53ea 剔除「了的呢吗呀啊哈」后的现行值）为全仓唯一权威取值；
- ``match_trigger``：casefold 语义**逐字上收** tts.py ``extract_tts_text``
  现行实现（b13913d 的 M-16 修法，含 fold 长度错位回退逐字精确匹配）；
- 繁簡口径：**词表登记解决，不做 s2t 转换器**（§6 明文）——繁體词命中靠把
  繁體条目（說/語音/朗讀/唸）登记进词表，归一不做字符映射；
- 六副本兼容：randpic/media_archive/group_info/mentions/base_router 各域
  语义保持、取值归一（本文件「六副本形态」一节逐形态钉住）。

本测试件**独立成件**（不 import tts.py / base_router.py）：词表为
``DEFAULT_TRIGGER_WORDS`` 的内联副本，防止与 T57 独占面耦合。全离线零网络。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.text_boundary import (
    ADDRESS_BOUNDARY_CHARS,
    PARTICLE_BOUNDARY_CHARS,
    TRIGGER_BOUNDARY_CHARS,
    is_boundary_char,
    is_trigger,
    match_trigger,
    matched_trigger_word,
    strip_boundary,
)

# tts.DEFAULT_TRIGGER_WORDS 的内联副本（11 词，独立成件不 import T57 独占面）。
WORDS: tuple[str, ...] = (
    "语音合成", "朗读", "语音", "念", "说",
    "tts", "say", "shuo", "yuyin", "nian", "langdu",
)

# 曾被劫持的日常句（对齐 tests/test_tts_hijack_guard.py 现行语料的内联副本）：
# 逐条要求——不命中（match_trigger 得空串、is_trigger 为 False）。
_HIJACK_SAMPLES: list[str] = [
    "说了再见",
    "说的对",
    "说的没错",
    "说了吧",
    "说了一半就停了",
    "语音哈喽",
    "语音了呢",
    "念了一遍就放下",
    "念的和写的不一样",
    "说的什么呀",
    "语音吗这个",
    "说是说了，可我忘了",
    "朗读的话其实不必",
    "说真的，我有点担心你",
]

# 真命令（含标点/空白分隔的各种写法）必须原样取得正文，不能被收编顺手砍掉。
_REAL_COMMANDS: list[tuple[str, str]] = [
    ("说 今天的潮汐很安静", "今天的潮汐很安静"),
    ("说，今天的潮汐很安静", "今天的潮汐很安静"),
    ("说：今天很安静", "今天很安静"),
    ("念 一段静夜思", "一段静夜思"),
    ("语音 你好呀", "你好呀"),
    ("语音合成，今天天气不错", "今天天气不错"),
    ("朗读  海风很温柔", "海风很温柔"),
    ("tts hello shorekeeper", "hello shorekeeper"),
    ("say 今天很安静", "今天很安静"),
    ("说。安静一点", "安静一点"),
]

# 反样本（包含关系词不误触发）——对齐既有守卫件的 5 条。
_SUBSTRING_SAMPLES: list[str] = [
    "说话要注意分寸",
    "念书的时候我喜欢靠窗",
    "语音消息我没听到",
    "说好的呢",
    "明天下雨吗",
]


# --- 1. 劫持负样本（14）-------------------------------------------------------


@pytest.mark.parametrize("text", _HIJACK_SAMPLES)
def test_function_words_do_not_hijack_chat(text: str) -> None:
    assert match_trigger(text, WORDS) == "", f"{text} 不该被当成合成命令"
    assert not is_trigger(text, WORDS), f"{text} 不该占触发路由"


@pytest.mark.parametrize("text", _HIJACK_SAMPLES)
def test_hijack_samples_stay_negative_even_with_bare_word_allowed(text: str) -> None:
    """bare_word 放宽只影响「裸触发词」形态，不复活虚词劫持。"""
    assert not is_trigger(text, WORDS, bare_word=True)


# --- 2. 真命令（10）-----------------------------------------------------------


@pytest.mark.parametrize("text,expected", _REAL_COMMANDS)
def test_real_commands_still_extract(text: str, expected: str) -> None:
    assert match_trigger(text, WORDS) == expected
    assert is_trigger(text, WORDS)


def test_longest_trigger_word_wins() -> None:
    """最长触发词优先：短词不得截断长词。"""
    assert match_trigger("语音合成，今天天气不错", ("语音", "语音合成")) == "今天天气不错"
    assert matched_trigger_word("语音合成，今天天气不错", ("语音", "语音合成")) == "语音合成"


def test_english_case_insensitive_m16() -> None:
    """英文大小写不敏感（M-16：SAY/TTS 是真命令），正文取原串切片。"""
    assert match_trigger("SAY hello", WORDS) == "hello"
    assert match_trigger("TTS 你好", WORDS) == "你好"
    assert match_trigger("Say：今天很安静", WORDS) == "今天很安静"


# --- 3. 反样本（5，包含关系词）-------------------------------------------------


@pytest.mark.parametrize("text", _SUBSTRING_SAMPLES)
def test_substring_words_still_not_triggered(text: str) -> None:
    assert match_trigger(text, WORDS) == ""
    assert not is_trigger(text, WORDS)


# --- 4. 繁體口径：词表登记解决，不做 s2t 转换器（§6 明文）-----------------------


def test_traditional_not_matched_without_registration() -> None:
    """无 s2t 转换：繁體文本对着简中词表不命中（登记前现状=诚实缺口）。"""
    assert match_trigger("語音 你好", WORDS) == ""
    assert match_trigger("說 你好", WORDS) == ""


def test_traditional_registered_words_match() -> None:
    """繁體条目（說/語音/朗讀/唸）登记进词表后即命中——归一走登记不走转换。"""
    words_t = (*WORDS, "說", "語音", "朗讀", "唸")
    assert match_trigger("說 你好", words_t) == "你好"
    assert match_trigger("朗讀，海風很温柔", words_t) == "海風很温柔"
    assert match_trigger("唸 一段靜夜思", words_t) == "一段靜夜思"
    assert match_trigger("語音：今天很安靜", words_t) == "今天很安靜"
    # 简中词与繁體词并表后互不干扰。
    assert match_trigger("说 你好", words_t) == "你好"


def test_casefold_does_not_map_traditional_to_simplified() -> None:
    """casefold 只做大小写折叠，不做繁→简映射（两套口径不混淆，T53 同课）。"""
    words_t = (*WORDS, "說")
    assert match_trigger("說 你好", words_t) == "你好"
    # 词表只有简中「说」时，繁體「說」不因 casefold 而命中。
    assert match_trigger("說 你好", WORDS) == ""


# --- 5. casefold 变长字符：fold 长度错位回退逐字精确匹配（b13913d 语义）---------


def test_casefold_length_mismatch_falls_back_verbatim() -> None:
    """ß→ss 改变长度：整串回退逐字精确匹配，宁可不触发也不切错正文。"""
    # 文本含 ß（fold 后变长）→ 逐字模式，逐字「ß」仍能命中并正确取正文。
    assert match_trigger("ß 你好", ("ß",)) == "你好"
    # 逐字模式下「ss」不得匹配「ß」开头文本（避免切错）。
    assert match_trigger("ß 你好", ("ss",)) == ""


def test_casefold_normal_ascii_path_unchanged() -> None:
    """常规 ASCII：折叠模式大小写不敏感照常。"""
    assert match_trigger("TTS hello", ("tts",)) == "hello"
    assert match_trigger("tts HELLO", ("tts",)) == "HELLO"


def test_casefold_lifted_semantics_folded_needle() -> None:
    """逐字上收语义钉档：文本可折叠时 needle 也折叠（ß 词可命中 SS 前缀文本）。

    这是 tts.py:175-202 现行实现的**原样行为**（foldable 以文本判定、needle 取
    word.casefold()）——上收件与被收编件在此逐字节一致，将来若要改此怪点必须
    显式翻本锁（改动=全仓六副本同步语义变更）。
    """
    assert match_trigger("SS 你好", ("ß",)) == "你好"


# --- 6. 空串/纯符号/裸触发词边界------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "   ", "，。！", "说，。！", "　", "\t", "，，说"],
)
def test_empty_and_symbol_only_inputs_return_empty(text: str) -> None:
    assert match_trigger(text, WORDS) == ""


def test_bare_trigger_word_semantics_split() -> None:
    """裸触发词双形态：tts 形态（取正文）得空串；bool 形态 bare_word=True 算命中。"""
    assert match_trigger("说", WORDS) == ""
    assert not is_trigger("说", WORDS, bare_word=False)
    assert is_trigger("说", WORDS, bare_word=True)
    # 纯边界尾巴剥空后同裸触发词口径（tts 形态返回空串不占路由）。
    assert match_trigger("说，。！", WORDS) == ""
    assert is_trigger("说，。！", WORDS, bare_word=True)


# --- 7. 字符集唯一权威（棘轮）--------------------------------------------------


def test_canonical_charset_pins_spec_value() -> None:
    """唯一权威取值 = tts.py 收紧集（d3a53ea 后现行值）逐字钉死。"""
    assert TRIGGER_BOUNDARY_CHARS == "，,。！？!?：:、 　\t～~"


def test_canonical_charset_contains_no_word_characters() -> None:
    """棘轮（独立副本）：分隔符集合里不得出现任何汉字/假名——劫持根因。"""

    def _is_cjk(char: str) -> bool:
        return "㐀" <= char <= "鿿" or "぀" <= char <= "ヿ"

    offenders = [c for c in TRIGGER_BOUNDARY_CHARS if _is_cjk(c)]
    assert offenders == [], f"边界集合混入词字符：{offenders}"
    assert set(PARTICLE_BOUNDARY_CHARS) >= set("了的呢吗呀啊哈")


def test_extension_charsets_pin_legacy_values() -> None:
    """扩展集钉档：虚词扩展=六副本历史取值并集；称呼扩展=mentions 独有段。"""
    assert set(PARTICLE_BOUNDARY_CHARS) == set("了的呢吗呀啊哈哦嘛咯哇")
    assert set(ADDRESS_BOUNDARY_CHARS) == set("今明天现在请帮我你请问呼")


# --- 8. 辅助函数----------------------------------------------------------------


def test_is_boundary_char() -> None:
    assert is_boundary_char("，")
    assert is_boundary_char(" ")
    assert is_boundary_char("　")
    assert is_boundary_char("\t")
    assert is_boundary_char("~")
    assert not is_boundary_char("了")
    assert not is_boundary_char("说")
    assert not is_boundary_char("")


def test_strip_boundary() -> None:
    assert strip_boundary("，。！ 你好 ") == "你好"
    assert strip_boundary("  tts 正文") == "tts 正文"
    assert strip_boundary("") == ""
    assert strip_boundary("了你好") == "了你好"  # 虚词不在权威集：不被剥（收紧语义）
    assert strip_boundary("，的说", charset="，,。！？!?：: 的") == "说"


# --- 9. 六副本形态兼容（各域语义保持、取值归一；接线归 G-2）----------------------
#
# 每一形态 = 对应副本现行语义的最小复刻，证明中央件签名能被直接替换。


def _legacy_charset(extra: str = "") -> str:
    """六副本历史取值的组合口径：权威集 ∪ 虚词扩展 ∪ 域专属。"""
    return TRIGGER_BOUNDARY_CHARS + PARTICLE_BOUNDARY_CHARS + extra


def test_randpic_shape() -> None:
    """randpic.py:59 形态：大小写敏感、裸词命中、虚词边界保留。"""
    words = ("随机图", "sjt")
    kwargs: dict[str, Any] = {
        "case_insensitive": False,
        "bare_word": True,
        "extra_boundary_chars": PARTICLE_BOUNDARY_CHARS,
    }
    assert is_trigger("随机图 来一张", words, **kwargs)
    assert is_trigger("随机图了来一张", words, **kwargs)  # 虚词边界（域语义保持）
    assert is_trigger("随机图", words, **kwargs)  # 裸词命中
    assert not is_trigger("随机图片库", words, **kwargs)  # 包含词不触发
    assert not is_trigger("SJT 来一张", words, **kwargs)  # 大小写敏感（现状语义）
    assert is_trigger("SJT 来一张", words, case_insensitive=True)  # 收编可选升级


def test_media_archive_shape() -> None:
    """media_archive.py:114 形态：换行归一空格、`=` 参数边界、裸词命中。"""
    words = ("收藏",)
    kwargs: dict[str, Any] = {
        "case_insensitive": False,
        "bare_word": True,
        "newline_as_space": True,
        "extra_boundary_chars": PARTICLE_BOUNDARY_CHARS + "=",
    }
    assert is_trigger("收藏", words, **kwargs)
    assert is_trigger("收藏\n分类=cos", words, **kwargs)  # 多行输入形态
    assert is_trigger("收藏=x", words, **kwargs)  # `=` 参数边界（域专属）
    assert not is_trigger("收藏=x", words, bare_word=True, newline_as_space=True)  # 无 `=` 扩展时不命中
    assert not is_trigger("收藏夹", words, **kwargs)


def test_group_info_shape() -> None:
    """group_info.py:79 形态：换行归一、虚词扩展集含 哦嘛咯哇。"""
    words = ("群主",)
    kwargs: dict[str, Any] = {
        "case_insensitive": False,
        "bare_word": True,
        "newline_as_space": True,
        "extra_boundary_chars": PARTICLE_BOUNDARY_CHARS,
    }
    assert is_trigger("群主", words, **kwargs)
    assert is_trigger("群主呢", words, **kwargs)  # 语气助词边界（域语义保持）
    assert is_trigger("群主哇", words, **kwargs)
    assert not is_trigger("群主管", words, **kwargs)  # 包含词不触发
    # 意图分派形态（matched_trigger_word 无 bare_word 参数：裸词/边界命中都返回词本身）。
    assert matched_trigger_word(
        "群主 资料呢",
        words,
        case_insensitive=False,
        newline_as_space=True,
        extra_boundary_chars=PARTICLE_BOUNDARY_CHARS,
    ) == "群主"


def test_mentions_charset_composition() -> None:
    """mentions.py:21 形态：字符集核心收编（称呼/时间/请求词扩展单列）。"""
    legacy = set("，,。！？!?：:、 的了呢吗呀啊哈今明天现在请帮我你请问呼")
    composed = (
        set(TRIGGER_BOUNDARY_CHARS) | set(PARTICLE_BOUNDARY_CHARS) | set(ADDRESS_BOUNDARY_CHARS)
    )
    assert legacy <= composed  # 历史取值是组合的真子集（～~/　/tab 为收编后显式加宽）
    assert is_trigger(
        "岸宝，帮我查天气", ("岸宝",), case_insensitive=False, bare_word=True,
        extra_boundary_chars=PARTICLE_BOUNDARY_CHARS + ADDRESS_BOUNDARY_CHARS,
    )
    assert not is_trigger(
        "岸宝贝", ("岸宝",), case_insensitive=False, bare_word=True,
        extra_boundary_chars=PARTICLE_BOUNDARY_CHARS + ADDRESS_BOUNDARY_CHARS,
    )


def test_base_router_nickname_strip_shape() -> None:
    """base_router.py:474 形态：昵称剥离只取字符集子集（语义不同不收编判定）。"""
    nick_charset = "，,。！？!?：: 的"
    assert set(nick_charset) <= set(_legacy_charset())
    assert strip_boundary("， 的 昵称", charset=nick_charset) == "昵称"
    assert strip_boundary("昵称", charset=nick_charset) == "昵称"


def test_tts_shape_is_the_canonical_default() -> None:
    """tts 形态=缺省形态：casefold 开、裸词空串、权威字符集、不归一换行。"""
    assert match_trigger("说\n你好", WORDS) == ""  # 换行不是权威边界（与 media_archive 差异保持）
    assert match_trigger("说 你好", WORDS) == "你好"


# --- 10. 繁體词表登记（M-16 后半收口，T92）：登记态全表经中央件的行为锁----------
#
# tts.py 的 DEFAULT_TRIGGER_WORDS 自 T92 起为 16 词（11 简中/英文/拼音 + 5 繁體）。
# 本文件独立成件不 import tts.py（文件头约定），此处内联镜像登记后全表，钉
# 「繁體词经中央件 match_trigger 的登记态行为」；上方 11 词内联副本 WORDS 保持
# 原样不动（历史锁与 RED 语义都靠它）。口径=§6 明文：登记解决、不做 s2t、
# casefold 不做繁→简映射。

TRADITIONAL_WORDS: tuple[str, ...] = ("語音合成", "朗讀", "語音", "唸", "說")
REGISTERED_WORDS: tuple[str, ...] = (*WORDS, *TRADITIONAL_WORDS)

# 繁體真命令（正文保持繁體原样——match_trigger 取原串切片，不改写用户用字）。
_REGISTERED_TRADITIONAL_REAL_COMMANDS: list[tuple[str, str]] = [
    ("說 你好", "你好"),
    ("說，今天的潮汐很安靜", "今天的潮汐很安靜"),
    ("語音 你好呀", "你好呀"),
    ("語音：今天很安靜", "今天很安靜"),
    ("唸 一段靜夜思", "一段靜夜思"),
    ("朗讀  海風很温柔", "海風很温柔"),
    ("語音合成，今天天氣不錯", "今天天氣不錯"),
]

# 繁體日常句（登记态也不得劫持——繁體「的/了」与简中同规格，不是边界）。
_REGISTERED_TRADITIONAL_HIJACK_SAMPLES: list[str] = [
    "說的是",
    "說了再見",
    "說真的，我有點擔心你",
    "語音消息我沒聽到",
    "唸書的時候我喜歡靠窗",
    "朗讀的話其實不必",
]


@pytest.mark.parametrize("text,expected", _REGISTERED_TRADITIONAL_REAL_COMMANDS)
def test_registered_traditional_commands_match(text: str, expected: str) -> None:
    """繁體命令在登记态全表下真命中并取得正文（tts 形态：casefold 开、取正文）。"""
    assert match_trigger(text, REGISTERED_WORDS) == expected
    assert matched_trigger_word(text, REGISTERED_WORDS) in {w for w in TRADITIONAL_WORDS}


def test_registered_traditional_longest_word_wins() -> None:
    """最长触发词优先在繁體面同样成立：語音合成 不得被 語音 截断。"""
    assert matched_trigger_word("語音合成，今天天氣不錯", REGISTERED_WORDS) == "語音合成"


def test_registered_traditional_bare_and_hijack_stay_negative() -> None:
    """登记态：繁體裸触发词空串、繁體日常句零劫持（与简中同规格）。"""
    assert match_trigger("說", REGISTERED_WORDS) == ""
    assert match_trigger("朗讀，。！", REGISTERED_WORDS) == ""
    for text in _REGISTERED_TRADITIONAL_HIJACK_SAMPLES:
        assert match_trigger(text, REGISTERED_WORDS) == "", f"{text} 不该被当成合成命令"
        assert not is_trigger(text, REGISTERED_WORDS, bare_word=False)


def test_registered_table_keeps_simplified_english_behavior() -> None:
    """并表零回归：简中词/英文 casefold/包含词反样本在 16 词全表下逐字不变。"""
    assert match_trigger("说 你好", REGISTERED_WORDS) == "你好"
    assert match_trigger("SAY hello", REGISTERED_WORDS) == "hello"
    for text in _SUBSTRING_SAMPLES:
        assert match_trigger(text, REGISTERED_WORDS) == ""


def test_traditional_hits_come_from_registration_not_folding() -> None:
    """繁體命中唯一来源=登记：从 16 词表删掉繁體条目，繁體文本立即失配。"""
    assert match_trigger("說 你好", WORDS) == ""
    assert match_trigger("說 你好", REGISTERED_WORDS) == "你好"
