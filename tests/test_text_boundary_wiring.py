"""Wave G G-2/T66：五处触发词边界手抄副本 → 中央件 text_boundary 的委托锁。

锁两层：
1. **委托锁**（RED 先行）：randpic/media_archive/group_info 的触发判定、
   group_info 意图分派、base_router 昵称剥离必须经中央件
   ``domains/core/text_boundary`` 的谓词——monkeypatch 消费模块命名空间上的
   中央件名字返回哨兵值即可观测；现状（各文件自持手抄循环）下这些名字
   不存在，跑红即 RED 证据，换线后转绿。
2. **字节现状锁**（改造前后都必须绿）：五处现行字符集/语义逐字节保持——
   含 group_info 的 newline_as_space=True 形态、mentions 的昵称边界形态；
   randpic/media_archive **不含** 哦嘛咯哇与 　/tab、mentions **不含** ～/~
   （T59 的 PARTICLE 全并集形态会使边界加宽=行为变更，本波不采用，见
   report-T66 披露表）。mentions 是「只收编取值」的消费者（判定语义不同，
   不走中央谓词），其锁=字符集值必须由核心字面量 ∪ 中央 ADDRESS 登记组成。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    group_info as group_info_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    base_router,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    mentions as mentions_mod,
)
from plugins.bot_unified_runtime.domains.core import text_boundary
from plugins.bot_unified_runtime.domains.media.capabilities import (
    media_archive as media_archive_mod,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic as randpic_mod

# 改造前各文件手抄串原文（字节现状锁的真值来源）。
_RANDPIC_LEGACY = "，,。！？!?：:、 的了呢吗呀啊哈～~"
_GROUP_INFO_LEGACY = "，,。！？!?：:、 的了呢吗呀啊哈～~哦嘛咯哇"
_MENTIONS_LEGACY = "，,。！？!?：:、 的了呢吗呀啊哈今明天现在请帮我你请问呼"
_NICK_BOUNDARY_LEGACY = "，,。！？!?：: 的"
_NICK_STRIP_LEGACY = "，,。！？!?：: "


def _natural_command_matcher() -> Any:
    """取 natural_command 规则的 matcher（断言非 None，mypy 收窄）。"""
    rule = next(
        r for r in base_router.ROUTE_RULES if r.capability_id == "bot.natural_command"
    )
    matcher = rule.matcher
    assert matcher is not None
    return matcher


# ---------------------------------------------------------------------------
# 委托锁（换线前 RED：消费模块命名空间无中央件名字 → AttributeError）
# ---------------------------------------------------------------------------


def test_randpic_delegates_to_central_is_trigger(monkeypatch) -> None:
    """randpic.is_randpic_command 必须经中央件 is_trigger 且带现行字符集。"""
    captured: dict[str, Any] = {}

    def spy(text: str, words: Any, **kwargs: Any) -> bool:
        captured["text"] = text
        captured["words"] = tuple(words)
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(randpic_mod, "is_trigger", spy)
    assert randpic_mod.is_randpic_command("随机图 来一张") is True
    assert captured["text"] == "随机图 来一张"
    assert captured["words"] == randpic_mod.DEFAULT_TRIGGER_WORDS
    kwargs = captured["kwargs"]
    assert kwargs["case_insensitive"] is False  # 大小写敏感（现状）
    assert kwargs["bare_word"] is True  # 裸词命中（现状）
    assert kwargs["newline_as_space"] is False  # 不归一换行（现状）
    assert kwargs["boundary_chars"] == _RANDPIC_LEGACY  # 字节现状
    assert kwargs["extra_boundary_chars"] == ""  # 无扩展（≠PARTICLE 全并集）


def test_media_archive_delegates_with_newline_and_eq_boundary(monkeypatch) -> None:
    """media_archive.is_media_archive_command：换行归一 + 「=」参数边界经中央件。"""
    captured: dict[str, Any] = {}

    def spy(text: str, words: Any, **kwargs: Any) -> bool:
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(media_archive_mod, "is_trigger", spy)
    assert media_archive_mod.is_media_archive_command("收藏\n分类=cos") is True
    kwargs = captured["kwargs"]
    assert kwargs["case_insensitive"] is False
    assert kwargs["bare_word"] is True
    assert kwargs["newline_as_space"] is True  # 评审 I-3 多行形态（现状）
    assert kwargs["boundary_chars"] == _RANDPIC_LEGACY  # 与 randpic 同核心串
    assert kwargs["extra_boundary_chars"] == "="  # 参数边界单列（域专属）


def test_group_info_command_delegates_with_particle_extension(monkeypatch) -> None:
    """group_info.is_group_info_command：newline_as_space + PARTICLE 全量经中央件。"""
    captured: dict[str, Any] = {}

    def spy(text: str, words: Any, **kwargs: Any) -> bool:
        captured["words"] = tuple(words)
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(group_info_mod, "is_trigger", spy)
    assert group_info_mod.is_group_info_command("群主是谁") is True
    assert captured["words"] == group_info_mod.GROUP_INFO_TRIGGER_WORDS
    kwargs = captured["kwargs"]
    assert kwargs["case_insensitive"] is False
    assert kwargs["bare_word"] is True
    assert kwargs["newline_as_space"] is True
    assert kwargs["extra_boundary_chars"] == text_boundary.PARTICLE_BOUNDARY_CHARS
    # 组合集与原手抄串逐字节等价（基段不含 　/tab，由字节现状锁钉住）。
    assert set(kwargs["boundary_chars"]) | set(kwargs["extra_boundary_chars"]) == set(
        _GROUP_INFO_LEGACY
    )


def test_group_info_intent_dispatch_delegates_to_matched_trigger_word(monkeypatch) -> None:
    """detect_group_info_intents 必须经中央件 matched_trigger_word 取命中词。"""
    captured: dict[str, Any] = {}

    def spy(text: str, words: Any, **kwargs: Any) -> str:
        captured["kwargs"] = kwargs
        return "群主是谁"

    monkeypatch.setattr(group_info_mod, "matched_trigger_word", spy)
    assert group_info_mod.detect_group_info_intents("群主是谁") == frozenset({"owner"})
    kwargs = captured["kwargs"]
    assert kwargs["case_insensitive"] is False
    assert kwargs["newline_as_space"] is True
    assert kwargs["extra_boundary_chars"] == text_boundary.PARTICLE_BOUNDARY_CHARS

    monkeypatch.setattr(
        group_info_mod, "matched_trigger_word", lambda text, words, **kw: ""
    )
    assert group_info_mod.detect_group_info_intents("今天天气怎么样") == frozenset()


def test_base_router_nickname_strip_goes_through_central(monkeypatch) -> None:
    """natural_match 昵称剥离：查界/剥尾两步都经中央件且取值=现行子集。"""
    boundary_calls: list[frozenset[str]] = []
    strip_calls: list[str] = []
    real_strip = text_boundary.strip_boundary

    def boundary_spy(ch: str, *, charset: frozenset[str]) -> bool:
        boundary_calls.append(charset)
        return ch in charset

    def strip_spy(tail: str, *, charset: str) -> str:
        strip_calls.append(charset)
        return real_strip(tail, charset=charset)

    monkeypatch.setattr(base_router, "is_boundary_char", boundary_spy)
    monkeypatch.setattr(base_router, "strip_boundary", strip_spy)

    matcher = _natural_command_matcher()
    config = SimpleNamespace(bot_natural_command_enabled=True)
    resolver = SimpleNamespace(nicknames=["守岸人", "岸宝"])
    decision = matcher("守岸人，把识图关掉", config, resolver)
    assert decision is not None
    assert decision.kind == base_router.RouteKind.NATURAL_COMMAND
    assert decision.normalized_text == "/bot runtime set BOT_VISION_ENABLED false"
    assert boundary_calls and set(_NICK_BOUNDARY_LEGACY) <= boundary_calls[0]
    assert strip_calls == [_NICK_STRIP_LEGACY]


# ---------------------------------------------------------------------------
# mentions：只收编取值（判定语义不同不走中央谓词）——值构成与行为锁
# ---------------------------------------------------------------------------


def test_mentions_charset_registered_from_central_address_group() -> None:
    """mentions 边界集 = 核心段（字节现状）∪ 中央 ADDRESS 登记全量。"""
    assert mentions_mod.ADDRESS_BOUNDARY_CHARS == text_boundary.ADDRESS_BOUNDARY_CHARS
    assert set(mentions_mod._ADDRESS_BOUNDARY_CHARS) == set(_MENTIONS_LEGACY)
    assert set(_MENTIONS_LEGACY) == (
        set("，,。！？!?：:、 的了呢吗呀啊哈") | set(text_boundary.ADDRESS_BOUNDARY_CHARS)
    )
    # 字节现状：mentions 不含 哦嘛咯哇，也不含 ～/~/　/tab（≠PARTICLE/权威集）。
    assert not set("哦嘛咯哇～~　\t") & set(mentions_mod._ADDRESS_BOUNDARY_CHARS)


def test_mentions_boundary_behavior_unchanged() -> None:
    """称呼边界行为抽查：时间/请求词命中；「哦」「～」不构成边界（现状）。"""
    terms = ("守岸人",)
    assert mentions_mod.detect_name_mention("守岸人今天天气怎么样", terms) is True
    assert mentions_mod.detect_name_mention("守岸人帮我查天气", terms) is True
    assert mentions_mod.detect_name_mention("守岸人，在吗", terms) is True
    assert mentions_mod.detect_name_mention("守岸人哦", terms) is False
    assert mentions_mod.detect_name_mention("守岸人～在吗", terms) is False
    assert mentions_mod.detect_name_mention("守岸宝贝", terms) is False
    assert mentions_mod.starts_with_name_mention("守岸人现在方便吗", terms) is True


# ---------------------------------------------------------------------------
# 字节现状锁（改造前后都必须绿：五处现行语义逐字节保持）
# ---------------------------------------------------------------------------


def test_randpic_byte_exact_semantics_preserved() -> None:
    f = randpic_mod.is_randpic_command
    assert f("随机图") is True  # 裸词命中
    assert f("随机图 来一张") is True
    assert f("随机图了来一张") is True  # 虚词边界（现行七虚词）
    assert f("来张图，好看吗") is True
    assert f("sjt") is True
    assert f("随机图片库") is False  # 包含词不触发
    assert f("SJT 来一张") is False  # 大小写敏感（现状）
    assert f("随机图　来一张") is False  # 全角空格非现行边界（≠中央权威集）
    assert f("随机图\t来一张") is False  # tab 非现行边界
    assert f("随机图哦来一张") is False  # 「哦」不在现行集（≠PARTICLE 全并集）
    assert f("") is False
    assert f("随机图", ("天气",)) is False  # 词表可传入覆盖


def test_media_archive_byte_exact_semantics_preserved() -> None:
    f = media_archive_mod.is_media_archive_command
    assert f("收藏") is True
    assert f("收藏\n分类=cos") is True  # 换行归一空格（评审 I-3）
    assert f("收藏=cos") is True  # 「=」参数边界
    assert f("存聊天记录 分类=x") is True
    assert f("archive") is True
    assert f("收藏夹") is False
    assert f("ARCHIVE 数据") is False  # 大小写敏感（现状）
    assert f("收藏　分类=x") is False  # 全角空格非现行边界
    assert f("收藏哦") is False  # 「哦」不在现行集（≠PARTICLE 全并集）


def test_group_info_byte_exact_semantics_preserved() -> None:
    f = group_info_mod.is_group_info_command
    assert f("群主是谁") is True
    assert f("群主") is True  # 裸词
    assert f("群主呢") is True
    assert f("群主哇") is True  # 哦嘛咯哇在 group_info 现行集
    assert f("群主管") is False  # 包含词不触发
    assert f("群主　是谁") is False  # 全角空格非现行边界
    detect = group_info_mod.detect_group_info_intents
    assert detect("群主 资料呢") == frozenset({"owner"})
    assert detect("群人数") == frozenset({"count"})
    assert detect("本群多大了") == frozenset({"age"})
    assert detect("群公告") == frozenset({"notice"})
    assert detect("群精华") == frozenset({"essence"})
    assert detect("群信息") == frozenset({"profile"})
    assert detect("今天天气怎么样") == frozenset()


def test_base_router_nickname_strip_behavior_unchanged() -> None:
    matcher = _natural_command_matcher()
    config = SimpleNamespace(bot_natural_command_enabled=True)
    resolver = SimpleNamespace(nicknames=["守岸人", "岸宝"])
    # 无昵称解析器：剥离分支整体跳过，判定照常。
    plain = matcher("把识图关掉", config, None)
    assert plain is not None
    assert plain.normalized_text == "/bot runtime set BOT_VISION_ENABLED false"
    # 昵称+边界：剥离后命中。
    stripped = matcher("岸宝，把识图关掉", config, resolver)
    assert stripped is not None
    assert stripped.normalized_text == "/bot runtime set BOT_VISION_ENABLED false"
    # 昵称后非边界（包含词）：不剥离、不命中自然语言路由。
    assert matcher("守岸人宝贝把识图关掉", config, resolver) is None
