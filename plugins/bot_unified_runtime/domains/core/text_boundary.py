"""触发词边界中央谓词（Wave G G-2a/T59 落地，S-07 六副本收编的唯一边界件）。

规格蓝本：``docs/design/tts-contract-layer.md`` §6（T54 G-1 规格）。收编蓝图：

- ``TRIGGER_BOUNDARY_CHARS``：全仓唯一权威取值 = ``domains/media/capabilities/
  tts.py`` 的收紧集（d3a53ea 剔除「了的呢吗呀啊哈」虚词后的现行值）。历史教训：
  边界集合混入虚词后，312 句日常中文 68.1% 被 bot.tts 劫持（M-01），故权威集
  **只放真分隔符**（标点与空白），一个词字符都不能进——棘轮锁见
  ``tests/test_text_boundary_central.py`` 与 ``tests/test_tts_hijack_guard.py``。
- ``match_trigger``：casefold 语义**逐字上收** tts.py ``extract_tts_text``
  现行实现（b13913d 的 M-16 修法，含 fold 长度错位回退逐字精确匹配——
  casefold 改变长度的极端字符（如 ß→ss）会让「折叠串偏移」与「原串偏移」
  错位，那种输入退回逐字精确匹配：宁可不触发，也不切错正文或误触发）。
- 繁簡口径（M-16 后半）：**词表登记解决，不做 s2t 转换器**（§6 明文）——
  繁體命中靠把繁體条目（說/語音/朗讀/唸）登记进调用方词表；casefold 只做
  大小写折叠，不做繁→简映射（引擎 lang 维度是另一件事，勿混淆，T53）。

六副本收编形态（接线归 G-2 正席，本件只供件不对表外文件做任何改动）：

============  ====================================  ============================
副本          现行语义（保持）                      本件替换形态
============  ====================================  ============================
tts.py        casefold、裸词=空串、权威集           ``match_trigger``（缺省形态）
randpic.py    大小写敏感、裸词命中、虚词边界        ``is_trigger(case_insensitive=False, bare_word=True, extra_boundary_chars=PARTICLE_BOUNDARY_CHARS)``
media_archive 大小写敏感、换行归一、``=`` 参数边界  ``is_trigger(..., newline_as_space=True, extra_boundary_chars=PARTICLE_BOUNDARY_CHARS + "=")``
group_info    大小写敏感、换行归一、虚词扩展        ``is_trigger(..., newline_as_space=True, extra_boundary_chars=PARTICLE_BOUNDARY_CHARS)``（意图分派加 ``matched_trigger_word``）
              含 哦嘛咯哇
mentions      称呼/时间/请求词扩展集                字符集核心取 ``TRIGGER_BOUNDARY_CHARS`` 组合（判定语义不同，只收编取值）
base_router   昵称剥离（语义不同）                  只引用字符集子集（``strip_boundary(charset=...)``）
============  ====================================  ============================

全件零 I/O、零网络、零 config 依赖：纯函数，可被路由层/能力层任意离线复用。
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# 字符集唯一权威（取值归一的三段登记处）
# ---------------------------------------------------------------------------

# 权威边界集：触发词与正文之间允许的分隔字符（= tts.py 收紧集，逐字钉死）。
# ⚠️ 只能放真分隔符（标点与空白），一个词字符都不能进——见模块 docstring 的
# M-01 劫持教训；「了/的/呢/吗/呀/啊/哈」等虚词一律走下面的扩展登记处。
TRIGGER_BOUNDARY_CHARS: Final[str] = "，,。！？!?：:、 　\t～~"

# 虚词/语气助词扩展（六副本历史取值的并集登记处）：randpic/media_archive/
# group_info 的现行「语气助词也算边界」语义保持时，经
# ``extra_boundary_chars=PARTICLE_BOUNDARY_CHARS`` 显式组合，不再各自手抄字符串。
# 注意：这些字符**不属于**权威集——tts 形态（缺省）永远不含它们。
PARTICLE_BOUNDARY_CHARS: Final[str] = "的了呢吗呀啊哈哦嘛咯哇"

# 称呼/时间/请求词扩展（mentions.py 独有段登记处）：「守岸人明天」「岸宝帮我」
# 这类称呼后紧跟请求词首字的边界语义。
ADDRESS_BOUNDARY_CHARS: Final[str] = "今明天现在请帮我你请问呼"

_TRIGGER_BOUNDARY_SET: Final[frozenset[str]] = frozenset(TRIGGER_BOUNDARY_CHARS)


def is_boundary_char(ch: str, *, charset: frozenset[str] = _TRIGGER_BOUNDARY_SET) -> bool:
    """单字符是否属于边界集（缺省=权威集）。"""
    return bool(ch) and ch in charset


def strip_boundary(tail: str, *, charset: str = TRIGGER_BOUNDARY_CHARS) -> str:
    """剥掉命中后尾巴上开头的边界字符与两端空白，得到正文。

    ``charset`` 供 base_router 昵称剥离等「子集引用」形态传入自己的取值；
    缺省即权威集，与 tts 现行 ``tail.lstrip(_TEXT_BOUNDARY_CHARS).strip()`` 同一。
    """
    return tail.lstrip(charset).strip()


def _compose_charset(boundary_chars: str, extra_boundary_chars: str) -> str:
    """组合边界集（去重保序）：基础集在前、域专属扩展在后。"""
    if not extra_boundary_chars:
        return boundary_chars
    seen: set[str] = set(boundary_chars)
    merged = [boundary_chars]
    for ch in extra_boundary_chars:
        if ch not in seen:
            seen.add(ch)
            merged.append(ch)
    return "".join(merged)


def _fold_target(stripped: str, case_insensitive: bool) -> tuple[str, bool]:
    """折叠归一的唯一入口（三函数共用，防再出「三处手抄两处坏」）。

    返回 ``(target, foldable)``：``case_insensitive=False`` 时原样返回
    ``(stripped, False)``；开启折叠且 casefold 不改变长度时返回
    ``(folded, True)``——casefold 改变长度的极端字符（如 ß→ss）会让「折叠串
    偏移」与「原串偏移」错位，那种输入退回逐字精确匹配（foldable=False）：
    宁可不触发，也不切错正文或误触发。（b13913d M-16 修法，逐字上收。）
    """
    if not case_insensitive:
        return stripped, False
    folded = stripped.casefold()
    if len(folded) == len(stripped):
        return folded, True
    return stripped, False


def match_trigger(
    text: str,
    words: list[str] | tuple[str, ...] | None,
    *,
    case_insensitive: bool = True,
    boundary_chars: str = TRIGGER_BOUNDARY_CHARS,
    extra_boundary_chars: str = "",
    newline_as_space: bool = False,
) -> str:
    """触发词命中判定 + 命中后正文切片提取（六副本共用的唯一判定件）。

    返回命中后的正文（已剥边界字符与两端空白）；以下情形返回空串：
    - 未命中任何触发词（含包含关系词：「说话要注意分寸」不得因「说」命中）；
    - 裸触发词/纯边界尾巴（没有正文可取）——bool 形态的裸词命中语义归
      ``is_trigger``/``matched_trigger_word``，取正文形态永远空串。

    语义细节（逐字上收 tts.py 现行实现）：
    - 最长触发词优先匹配，避免短词截断长词（``语音合成`` 之于 ``语音``）；
    - ``case_insensitive=True``（tts 形态，缺省）时英文大小写不敏感
      （``SAY``/``TTS`` 是真命令，M-16），正文一律取原串切片，绝不返回折叠后
      的大小写；casefold 改变长度的极端字符（如 ß→ss）回退**逐字精确匹配**；
    - ``case_insensitive=False``（randpic/media_archive/group_info/mentions
      现行形态）时保持大小写敏感，行为与各副本现状逐字节一致；
    - ``newline_as_space=True``（media_archive/group_info 现行形态）时换行先
      归一为空格（「收藏\\n分类=x」多行输入形态，评审 I-3）；
    - 触发词后必须紧跟边界字符（``boundary_chars`` ∪ ``extra_boundary_chars``）
      或正文为空才算命中，「语音消息」「随机图片库」类包含词不误触发。
    """
    stripped = (text or "").strip()
    if newline_as_space:
        stripped = stripped.replace("\r", " ").replace("\n", " ")
    if not stripped:
        return ""
    target, foldable = _fold_target(stripped, case_insensitive)
    charset = _compose_charset(boundary_chars, extra_boundary_chars)
    for word in sorted({str(w).strip() for w in (words or ()) if str(w).strip()}, key=len, reverse=True):
        needle = word.casefold() if foldable else word
        if target == needle or stripped == word:
            # 只发了触发词、没带正文：由调用方给引导文案（既有口径不动）。
            return ""
        if not target.startswith(needle):
            continue
        tail = stripped[len(needle):]
        if not tail or tail[0] not in charset:
            continue
        return tail.lstrip(charset).strip()
    return ""


def is_trigger(
    text: str,
    words: list[str] | tuple[str, ...] | None,
    *,
    case_insensitive: bool = False,
    bare_word: bool = True,
    boundary_chars: str = TRIGGER_BOUNDARY_CHARS,
    extra_boundary_chars: str = "",
    newline_as_space: bool = False,
) -> bool:
    """bool 形态的触发词判定（randpic/media_archive/group_info 现行调用形状）。

    缺省参数对齐该族现状：大小写敏感、裸触发词即命中；tts 形态请用
    ``bool(match_trigger(...))``（casefold 开、裸词不算命中）。
    ``bare_word=True`` 时裸触发词/纯边界尾巴都算命中（委托
    ``matched_trigger_word``，折叠语义单一来源）；``False`` 时只有
    「触发词+边界+正文」形态算命中（与 ``match_trigger`` 同判）。
    """
    if bare_word:
        return bool(
            matched_trigger_word(
                text,
                words,
                case_insensitive=case_insensitive,
                boundary_chars=boundary_chars,
                extra_boundary_chars=extra_boundary_chars,
                newline_as_space=newline_as_space,
            )
        )
    return bool(
        match_trigger(
            text,
            words,
            case_insensitive=case_insensitive,
            boundary_chars=boundary_chars,
            extra_boundary_chars=extra_boundary_chars,
            newline_as_space=newline_as_space,
        )
    )


def matched_trigger_word(
    text: str,
    words: list[str] | tuple[str, ...] | None,
    *,
    case_insensitive: bool = False,
    boundary_chars: str = TRIGGER_BOUNDARY_CHARS,
    extra_boundary_chars: str = "",
    newline_as_space: bool = False,
) -> str:
    """返回命中的触发词本身（group_info 意图分派形态），未命中返回空串。

    ``detect_group_info_intents`` 类调用方需要「命中了哪个词」而非正文；
    词形互斥设计下实际至多一个。裸触发词与边界命中都算命中。
    """
    stripped = (text or "").strip()
    if newline_as_space:
        stripped = stripped.replace("\r", " ").replace("\n", " ")
    if not stripped:
        return ""
    target, foldable = _fold_target(stripped, case_insensitive)
    charset = _compose_charset(boundary_chars, extra_boundary_chars)
    for word in sorted({str(w).strip() for w in (words or ()) if str(w).strip()}, key=len, reverse=True):
        needle = word.casefold() if foldable else word
        if target == needle or stripped == word:
            return word
        if not target.startswith(needle):
            continue
        tail = stripped[len(needle):]
        if not tail or tail[0] not in charset:
            continue
        return word
    return ""
