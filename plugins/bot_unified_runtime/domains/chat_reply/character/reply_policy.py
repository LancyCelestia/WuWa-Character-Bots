"""永久性 per-user 回复策略（T7，2026-09-28 用户裁定）。

她要的原话是「对每个用户采取永久性的回复策略……假如用户说你字写得太多了，
短一点，那就采取永久性的策略：在跟这个用户沟通时，永久性地不要把话说多」。
本件就是那条策略的**存储 + 判定 + 呈现**的唯一真身，共三件事：

1. **存储**：SQLite 单表 ``user_reply_policy``，主键是「人」而不是「会话」
   （键构造一律走 :mod:`domains.core.session_keys`，手拼前缀＝台账 #33 那族事故）。
   选 person 作用域的理由由她给定：一个人不喜欢长文，与他此刻在群里还是私聊无关。
2. **判定双轨**：确定性谓词先判；谓词判不定才问一次 LLM；**只有 LLM 确认才落库**。
   落库即永久，直到同一人再次明示覆盖（含反悔，反悔走同一条写腿覆盖同一行）。
3. **呈现**：长度走既有档位真身（本件**不另立长度判据**，只产出一个
   ``chat`` 层已登记的详略模式名）；内容指令渲染成提示词行，且**不得**越过
   R-2 的动作/神态边界与 R-18 档——那些红线住在人格与内容政策层，本件只加
   「少写动作神态」这类**收窄**方向的提示，绝不写「可以放开」方向的任何东西。
   唯一受控例外（2026-09-28 用户裁定「文风得跟人走」）：``STYLE_CODES`` 那两枚
   放开的是**修辞层**（用词与句式），不是描写层——「动作/神态/心理能不能写」
   仍只由内容政策与场景档决定，本件永不授予。该边界由
   ``tests/test_reply_policy_permanent.py`` 的放开方向措辞黑名单执法，加锁自证。

安全面：``evidence`` 存的是用户原话摘要，属**不可信文本**，落库前必须过
既有两道咽喉（``security/injection.py::neutralize_internal_markers`` 与
``render/plain_text.py::redact_local_secrets``）——本件不写第三份消毒器。

库文件：``data/reply_policy.sqlite3``（经 runtime_paths 重映射到 Runtime 数据根）。
配置键真身＝``config.py`` 的 ``bot_reply_policy_enabled`` / ``bot_reply_policy_db_path``；
``docs/db-owners.md`` §二 已按 owner＝本模块登记。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    parse_session_key,
    private_session_key,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 一、受控词表
# ---------------------------------------------------------------------------

#: 长度策略五值。``auto`` = 本件不表态，交回既有题型判据（唯一真身在 chat 层）。
#: 其余四值都是 chat 层 ``REPLY_DETAIL_MODES`` 的**已登记模式名**——本件刻意
#: 不发明第二套长度词汇，策略值与配置档同名才能共用同一张分档表。
LENGTH_MODE_AUTO: Final[str] = "auto"
LENGTH_MODE_CONCISE: Final[str] = "concise"
LENGTH_MODE_NORMAL: Final[str] = "normal"
LENGTH_MODE_NARRATIVE: Final[str] = "narrative"
LENGTH_MODE_VERBOSE: Final[str] = "verbose"
LENGTH_MODES: Final[tuple[str, ...]] = (
    LENGTH_MODE_AUTO,
    LENGTH_MODE_CONCISE,
    LENGTH_MODE_NORMAL,
    LENGTH_MODE_NARRATIVE,
    LENGTH_MODE_VERBOSE,
)

#: 内容指令的受控枚举（只准往「更收」的方向走，见模块头红线说明）。
#: 自由短注另存 ``note`` 字段（消毒后 ≤ 80 字），不进本枚举、不进提示词的指令位。
CONTENT_DIRECTIVES: Final[tuple[str, ...]] = (
    "no_action_brackets",   # 别写动作神态
    "conclusion_first",     # 只要结论
    "break_down_everything",  # 掰碎了讲全过程
    "keep_it_factual",      # 只讲查得到的，别发挥
    "literary_prose",       # 修辞层：要文采、要画面
    "plain_online_speech",  # 修辞层：像平时打字那样说话
)

#: 文风两码（2026-09-28 用户裁定「文风得跟人走」）。这两枚是**修辞层**——
#: 改的是用词与句式，不是「能不能写动作神态」。描写维度的许可权归内容政策层
#: （R-2）与亲密档，本件永不授予；``_OPEN_UP_PHRASES`` 那把尺就在锁这条边界，
#: 执法见 ``tests/test_reply_policy_permanent.py``。
STYLE_CODES: Final[tuple[str, ...]] = ("literary_prose", "plain_online_speech")
_STYLE_LITERARY: Final[str] = "literary_prose"
_STYLE_PLAIN: Final[str] = "plain_online_speech"

#: 指令码 → 交给模型的中文行。措辞在这里，**不进**任何未命中/长度真身。
#: 文案红线：不带篇幅/字数口径（数值归 chat 的档位登记表）、不带放开描写的许可。
_DIRECTIVE_LINES: Final[dict[str, str]] = {
    "no_action_brackets": "对方不希望在回复里看到动作与神态描写，只用说话本身承载语气。",
    "conclusion_first": "对方要的是结论：先给答案，再按需补一句理由。",
    "break_down_everything": "对方喜欢被掰碎讲清：把来龙去脉、因果和边界一次讲全，不留半成品。",
    "keep_it_factual": "对方要的是稳当的说法：没核实到的就不讲，别补全、别推测。",
    "literary_prose": "对方喜欢你把话讲得有分量、有画面：用词讲究些，节奏和意象可以铺开。"
    "这只关乎怎么说，不关乎能写什么——动作与神态能不能写仍由当下的场景政策定。",
    "plain_online_speech": "对方要你像平时打字那样说话：短句、口语、不拽词、不掉书袋，"
    "别把聊天写成散文。",
}

SOURCE_EXPLICIT: Final[str] = "explicit"
SOURCE_INFERRED: Final[str] = "inferred"
POLICY_SOURCES: Final[tuple[str, ...]] = (SOURCE_EXPLICIT, SOURCE_INFERRED)

_EVIDENCE_MAX_CHARS: Final[int] = 200
_NOTE_MAX_CHARS: Final[int] = 80
_DIRECTIVE_ENCODE_MAX_CHARS: Final[int] = 320


def normalize_length_mode(value: object) -> str:
    """策略长度值归一：认不出的值一律回 ``auto``（绝不静默变成「详尽」）。"""
    mode = str(value or "").strip().lower()
    return mode if mode in LENGTH_MODES else LENGTH_MODE_AUTO


def _apply_style_mutex(codes: tuple[str, ...], preferred: str = "") -> tuple[str, ...]:
    """文风两码互斥的**唯一收口点**。

    同时在场时只留一枚：有方向（``preferred``＝本人这句刚点名的那枚）就听本人的；
    没方向（读到一个本来就同时躺着两枚的脏行）留 ``plain_online_speech``——
    拿不准就往更收的那一侧退，与本件的收窄默认立场同向。
    """
    if not (_STYLE_LITERARY in codes and _STYLE_PLAIN in codes):
        return codes
    keep = preferred if preferred in STYLE_CODES else _STYLE_PLAIN
    return tuple(code for code in codes if code not in STYLE_CODES or code == keep)


def normalize_content_directives(value: object) -> tuple[str, ...]:
    """内容指令解析（存的是 JSON 数组串，也接受序列）：未知码丢弃、保持登记序。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            decoded = json.loads(text)
        except (ValueError, TypeError):
            decoded = [part.strip() for part in text.replace("，", ",").split(",")]
        raw_items = decoded if isinstance(decoded, list) else []
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw_items = list(value)
    else:
        raw_items = []
    wanted = {str(item or "").strip().lower() for item in raw_items}
    return _apply_style_mutex(tuple(code for code in CONTENT_DIRECTIVES if code in wanted))


@dataclass(frozen=True)
class ReplyPolicy:
    """一个人的永久回复策略（不可变值对象；改写用 :func:`replace`）。"""

    person_key: str
    length_mode: str = LENGTH_MODE_AUTO
    content_directives: tuple[str, ...] = ()
    note: str = ""
    source: str = SOURCE_EXPLICIT
    evidence: str = ""
    updated_at: str = ""

    def encoded_directives(self) -> str:
        return json.dumps(list(self.content_directives), ensure_ascii=False)

    def is_silent(self) -> bool:
        """策略上「一切都不表态」：既没钉长度也没钉内容 ⇒ 与无策略等价。"""
        return self.length_mode == LENGTH_MODE_AUTO and not self.content_directives


# ---------------------------------------------------------------------------
# 二、会话键：按人共享（跨群/私聊同一把键）
# ---------------------------------------------------------------------------


def person_reply_policy_key(*, sender_id: Any = "", session_id: Any = "") -> str:
    """策略主键＝「这个人」，与场景无关（她给的理由：不喜欢长文与在哪个群无关）。

    取 ``sender_id`` 的规范形（与中央件的私聊键构造器**同一个函数**，不手拼前缀）；
    ``sender_id`` 缺失时退回从会话键里解析出的发送者段。两者都拿不到 ⇒ 空串＝
    「无策略」，调用方据此走全局档，绝不退化成「拿整群/全表某一行当此人策略」。
    """
    sender = str(sender_id or "").strip()
    if sender:
        return private_session_key(sender)
    parsed = parse_session_key(session_id)
    if parsed.user_id:
        return private_session_key(parsed.user_id)
    return ""


# ---------------------------------------------------------------------------
# 三、消毒：只走既有咽喉，本件零自造正则
# ---------------------------------------------------------------------------


def sanitize_evidence(raw: object, *, limit: int = _EVIDENCE_MAX_CHARS) -> str:
    """用户原话摘要 → 可入库形态：剥内部标记 + 打码本机痕迹 + 限长 + 折行。

    顺序是刻意的：先 ``neutralize_internal_markers``（分区头/块闭合/指令行形态），
    再 ``redact_local_secrets``（盘符路径 / ``BOT_XXX=`` / ``sk-`` 形态），最后限长——
    限长放最后是因为截断可能恰好切出半个标记，前面两步做完剩下的才是安全字节。
    """
    text = neutralize_internal_markers(str(raw or ""))
    text = redact_local_secrets(text)
    text = " ".join(text.split())
    if limit > 0 and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text.strip()


def sanitize_note(raw: object) -> str:
    """自由短注：同一条消毒链，更短的窗（它会被读进提示词）。"""
    return sanitize_evidence(raw, limit=_NOTE_MAX_CHARS)


# ---------------------------------------------------------------------------
# 四、确定性谓词（第一轨）
# ---------------------------------------------------------------------------

#: 「说少了」侧触发词，**自证型**：这些词一出现就只能在提回复的长短，不需要额外线索。
_SHORTER_SELF_RE = re.compile(
    r"(字太多|字数太多|写太多|说太多|讲太多|回太多|打太多|"
    r"短一点|短一些|短点|短些|简短|精简|简洁|"
    r"别写这么|别回这么|不要写这么|不要回这么|不要这么长|不要这样长|"
    r"说重点|讲重点|捡重点|挑重点|抓重点|只要结论|只给结论|只说结论|"
    r"啰嗦|罗嗦|墨迹|磨叽|废话太多|"
    r"一句话|只回一句|就一句|一句说完|少打点字|少打几个字|字少一点|字少些|"
    r"不要这么多字|别这么多字)",
    re.IGNORECASE,
)
#: 「说少了」侧**通名型**触发词：「太长了」既能说 bot 的回复，也能说电影/会议/路。
#: 单独出现不作数，必须同句里有「回复」对象的线索才落库（宁可漏判去问 LLM）。
_SHORTER_CUE_RE = re.compile(r"(太长了|太长|这么长|那么长|这样长)")
#: 「说多了」侧自证型触发词（含她的原话「掰碎」）。
_LONGER_SELF_RE = re.compile(
    r"(详细点|详细一些|详细说|讲详细|细说|多说点|多说一些|多说些|多写点|多写一些|"
    r"写长点|长一点|长一些|字太少|字数太少|回得太短|说的太少|讲得太少|"
    r"讲清楚点|说清楚点|讲明白点|说明白点|掰碎|掰开揉碎|揉碎|展开讲|展开说|"
    r"详细展开|讲全|说全|讲透彻|讲到底|全部讲|都讲一下|再详细|更详细|长文本|写长文)",
    re.IGNORECASE,
)
#: 「说多了」侧通名型触发词（「太短了」也能形容裙子）。
_LONGER_CUE_RE = re.compile(r"(太短了|太短|太简短)")
#: 谈论对象必须是「回复」的线索词（只与通名型触发词配对使用）。
_REPLY_OBJECT_RE = re.compile(r"(你|您|回复|回答|回的|说的|讲的|写的|字|这段|那段|句子|话)")
#: 指向「别的东西」的线索：这些出现时那句话不是在提 bot 自己的回复长度。
_OTHER_OBJECT_RE = re.compile(r"(他们|她们|它这|这篇|那篇|这条|那段|对方|他发的|她发的|这部电影|那场)")
#: 确定性轨的句长上限：超长句往往是复合句／转述别人话，交给 LLM 判更稳。
_DETERMINISTIC_MAX_CHARS: Final[int] = 60

#: 谓词结果 → 策略长度值。
_SHORTER_MODE: Final[str] = LENGTH_MODE_CONCISE
_LONGER_MODE: Final[str] = LENGTH_MODE_VERBOSE


def detect_length_change_request(text: object) -> dict[str, Any]:
    """确定性谓词：这句话有没有在**改自己的回复长度**。

    返回值三态，调用方据此决定要不要问 LLM：

    * ``{"decided": True, "length_mode": "concise"|"verbose"}``：谓词判定成立，
      **直接落库**（她的原话就是「用户说你字写得太多了，短一点」这类明示）；
    * ``{"decided": False, "ambiguous": True}``：两侧都命中，或只命中通名型触发词
      却没有「回复」对象线索／句子过长 ⇒ 需要 LLM 判一次；
    * ``{"decided": False, "ambiguous": False}``：明显与长度无关 ⇒ 连 LLM 都不用问。

    两档触发词的分工是判据本身：**自证型**（「短一点」「掰碎点说」——她点名的说法）
    不需要任何额外线索；**通名型**（「太长了」「太短了」）必须同句出现回复对象线索，
    否则「这电影太长了」会被铸成一个永久策略。宁可漏判交给 LLM，也不误判落库。
    """
    stripped = " ".join(str(text or "").split())
    if not stripped:
        return {"decided": False, "ambiguous": False, "reason": "empty"}
    has_reply_cue = bool(_REPLY_OBJECT_RE.search(stripped))
    shorter = bool(_SHORTER_SELF_RE.search(stripped)) or (
        has_reply_cue and bool(_SHORTER_CUE_RE.search(stripped))
    )
    longer = bool(_LONGER_SELF_RE.search(stripped)) or (
        has_reply_cue and bool(_LONGER_CUE_RE.search(stripped))
    )
    if not (shorter or longer):
        return {"decided": False, "ambiguous": False, "reason": "no_length_signal"}
    if shorter and longer:
        # 「别写这么长，详细点讲讲」这类自相矛盾的话只能问模型。
        return {"decided": False, "ambiguous": True, "reason": "both_directions"}
    if bool(_OTHER_OBJECT_RE.search(stripped)):
        return {"decided": False, "ambiguous": True, "reason": "object_unclear"}
    if len(stripped) > _DETERMINISTIC_MAX_CHARS:
        return {"decided": False, "ambiguous": True, "reason": "too_long_for_predicate"}
    return {
        "decided": True,
        "length_mode": _SHORTER_MODE if shorter else _LONGER_MODE,
        "reason": "shorter_predicate" if shorter else "longer_predicate",
    }


#: 反悔路径：「还是详细点吧」「算了，别说这么短」必须能把 concise 覆盖回去。
_REVERSAL_TO_VERBOSE_RE = re.compile(r"(还是|干脆|算了).{0,10}(详细|多说|长一点|掰碎|展开)")
_REVERSAL_TO_CONCISE_RE = re.compile(r"(还是|干脆|算了).{0,10}(短|简短|精简|一句)")


def detect_reversal_request(text: object) -> str:
    """反悔句的确定性识别：返回应改成的长度模式（空串＝不是反悔句）。

    反悔与「首次表态」走同一条写腿（同一 ``person_key`` 覆盖同一行），
    本函数只是为了让「还是详细点吧」这种没有直接触发词、却明确撤销旧策略的
    说法也能在第一轨定下来，不必动用 LLM。
    """
    stripped = " ".join(str(text or "").split())
    if not stripped:
        return ""
    if _REVERSAL_TO_VERBOSE_RE.search(stripped):
        return LENGTH_MODE_VERBOSE
    if _REVERSAL_TO_CONCISE_RE.search(stripped):
        return LENGTH_MODE_CONCISE
    return ""


# ---------------------------------------------------------------------------
# 四乙、内容指令的确定性谓词
# ---------------------------------------------------------------------------

#: 指令码 → 触发词。**全部是「往更收/更实」的方向**（模块头红线：策略只准收窄，
#: 不得覆盖 R-2 的动作/神态边界与 R-18 档）。要加放开方向的词，先过内容政策层。
_CONTENT_DIRECTIVE_RES: Final[dict[str, re.Pattern[str]]] = {
    "no_action_brackets": re.compile(
        r"(别|不要|不用|别再|不许|少)(写|加|来|用)?(动作|神态|表情|括号|星号|描写)|"
        r"别演|不要演|只说话|光说话",
        re.IGNORECASE,
    ),
    "conclusion_first": re.compile(
        r"(只要|只给|只说|直接给|直接说|先说|先给)(结论|答案|结果)|说重点|讲重点|捡重点|挑重点|抓重点",
        re.IGNORECASE,
    ),
    "break_down_everything": re.compile(
        r"(掰碎|掰开|揉碎|讲全|说全|讲透|展开讲|展开说|来龙去脉|前因后果|都讲|细节多)",
        re.IGNORECASE,
    ),
    "keep_it_factual": re.compile(
        r"(别|不要|不许|勿)(编|瞎说|乱说|猜|推测|发挥|脑补)|只讲查到的|只说确定的",
        re.IGNORECASE,
    ),
    # 文风两码（修辞层）。触发词刻意只收**说法本身**，不收「风格/语气」这类
    # 在日常里大量出现在别处（谈别人、谈第三条消息）的通名。
    "literary_prose": re.compile(
        r"(文学|文艺|文采|文笔|辞藻|诗意|意象|意境|散文|写得美|写得漂亮|画面感|有画面)",
        re.IGNORECASE,
    ),
    "plain_online_speech": re.compile(
        r"(说人话|讲人话|别拽词|不要拽词|不拽词|别掉书袋|不掉书袋|大白话"
        r"|像平时|平时说话|别文绉绉|随便说两句|口语一点)",
        re.IGNORECASE,
    ),
}

#: 否定式文学化说法：「别写得那么文艺」是在要口语，不是在要文学化——判反就等于
#: 替这个人铸一份**反向**的永久策略。命中它 ⇒ 文学码作废、改落口语码。
_STYLE_NEGATED_LITERARY_RE: Final[re.Pattern[str]] = re.compile(
    r"(别|不要|不许|不用|别再|少|不想|不喜欢)[^，。,.!！?？]{0,6}"
    r"(文学|文艺|文采|文笔|辞藻|诗意|散文)",
    re.IGNORECASE,
)


#: 文风词的**谈论对象**尺（2026-09-28 补）：「文学/文艺/口语」这类词大量出现在
#: 谈论文、谈电影、谈别人那句话的句子里（"这篇文献太文艺了"），当场落库就是铸一份
#: 反向永久策略。与长度族同一家规：**通名型线索必须有「在说 bot 怎么讲」的对象**
#: 才算确定性轨命中——判不定的交给线索门去问模型，宁可花一次调用也不误判落库。
_STYLE_OBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"(你|您|回复|回答|念给|讲给|说给|写得|说得|讲得|写的这|说的这|这段话|这句话"
    r"|给我|跟我|同我|和我|替我|帮我|为我)",
    re.IGNORECASE,
)


def detect_content_directives(text: object) -> tuple[str, ...]:
    """这句话里明确提出的内容偏好（受控枚举，登记序去重；没有则空元组）。

    文风两枚额外过 :data:`_STYLE_OBJECT_RE` 这道对象尺；其余指令码（别写动作、
    只要结论…）本身就是**只在提 bot 怎么讲时才成立**的说法，不需对象线索。
    """
    stripped = " ".join(str(text or "").split())
    if not stripped:
        return ()
    hits: list[str] = []
    positions: dict[str, int] = {}
    for code in CONTENT_DIRECTIVES:
        match = _CONTENT_DIRECTIVE_RES[code].search(stripped)
        if match:
            hits.append(code)
            positions[code] = match.start()
    if _STYLE_NEGATED_LITERARY_RE.search(stripped) and _STYLE_LITERARY in hits:
        hits.remove(_STYLE_LITERARY)
        if _STYLE_PLAIN not in hits:
            hits.append(_STYLE_PLAIN)
            positions[_STYLE_PLAIN] = len(stripped)
    if _STYLE_LITERARY in hits and _STYLE_PLAIN in hits:
        keep = (
            _STYLE_LITERARY
            if positions[_STYLE_LITERARY] > positions[_STYLE_PLAIN]
            else _STYLE_PLAIN
        )
        hits = [code for code in hits if code not in STYLE_CODES or code == keep]
    # 对象尺只管**文学化**那一侧：它的词（文学/文艺/诗意/意象/画面感）既能形容
    # bot 的回复，也能形容一部电影、一篇论文 ⇒ 没有「在说 bot 怎么讲」的对象就当不成
    # 确定性命中。口语侧的词（说人话/别拽词/大白话/像平时）本身就是**祈使**，
    # 不存在"他真会说人话"式误伤（会把这类词说成通名的，都是通名化的「口语/通俗」，
    # 那些已从本表摘掉、只留在线索门里交给模型判）。
    if _STYLE_LITERARY in hits and not _STYLE_OBJECT_RE.search(stripped):
        hits = [code for code in hits if code != _STYLE_LITERARY]
    return tuple(code for code in CONTENT_DIRECTIVES if code in hits)


def merge_content_directives(
    existing: tuple[str, ...] | list[str] | None, added: tuple[str, ...] | list[str] | None
) -> tuple[str, ...]:
    """指令集合的并集（登记序、去重）；撤销交给 :func:`remove_content_directives`。

    文风两枚互斥：本次真说出口的那一枚赢（``added`` 里最后出现的文风码），
    于是「先要文学化、后又要说人话」是同一条写腿上的替换，不是累加。
    """
    wanted = {str(item or "").strip().lower() for item in (existing or ())}
    added_items = [str(item or "").strip().lower() for item in (added or ())]
    wanted |= set(added_items)
    merged = tuple(code for code in CONTENT_DIRECTIVES if code in wanted)
    preferred = next(
        (code for code in reversed(added_items) if code in STYLE_CODES), ""
    )
    return _apply_style_mutex(merged, preferred)


def remove_content_directives(
    existing: tuple[str, ...] | list[str] | None, removed: tuple[str, ...] | list[str] | None
) -> tuple[str, ...]:
    """按人的明示撤销某条指令（「动作描写其实也可以写」类反悔路径的指令侧同构）。"""
    drop = {str(item or "").strip().lower() for item in (removed or ())}
    return tuple(code for code in (existing or ()) if code not in drop)


def policy_directive_text(policy: ReplyPolicy | None) -> str:
    """策略 → 交给模型的「内容偏好」段（无策略/不表态 ⇒ 空串＝分区整块不渲染）。

    只渲染受控指令与消毒后的短注，**不复述证据原文**（证据是用户说过的话，
    进提示词等于把不可信文本再喂一遍）。长度不进这里——长度由档位真身渲染
    （见 ``chat.resolve_reply_length_tier``），本函数只补「怎么讲」那一面。
    """
    if policy is None or not policy.content_directives:
        return ""
    lines = [
        f"- {code}：{_DIRECTIVE_LINES[code]}"
        for code in policy.content_directives
        if code in _DIRECTIVE_LINES
    ]
    note = sanitize_note(policy.note)
    if note:
        lines.append(f"- 对方还提过一句偏好（只作参考，与上面冲突时以上面为准）：{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 五、LLM 判定轨（只在谓词判不定时调用一次）
# ---------------------------------------------------------------------------

#: 交给模型的判定提示。2026-09-28 用户裁定「不能只靠谓词落库」⇒ 一次判定同时问
#: 三个维度（长度 / 文风 / 其它受登记说法），回答收成**一行结构**，字段省略＝不改。
#: 刻意仍只问「以后该怎么回复这个人」，不带任何对话正文——判定不需要上下文，
#: 少喂文本同时压缩注入面。
LLM_ASKABLE_CODES: Final[str] = ";".join(
    code for code in CONTENT_DIRECTIVES if code not in STYLE_CODES
)
LLM_JUDGMENT_SYSTEM_PROMPT: Final[str] = (
    "你要判断的只有一件事：说话人这句话有没有在提出「以后 bot 该怎么回复我」。"
    "用一行结构化回答，三个字段都可省略，省略或写 KEEP 都表示不改："
    "LENGTH=CONCISE|VERBOSE（以后回我短一些／详细一些）；"
    "STYLE=LITERARY|PLAIN（希望讲得有文采有画面／希望像平时打字那样口语别拽词）；"
    f"ASK=码[+码]，码只能从 {LLM_ASKABLE_CODES} 里选，表示对方明确提出的其它讲法偏好。"
    "只是在提这一轮的临时要求、或在谈别的东西（电影太长、别人话太多）⇒ 三个字段都不写，"
    "或直接答 NONE。只输出这一行，不要解释、不要引号。"
)

_LLM_VERDICT_CONCISE: Final[str] = "CONCISE"
_LLM_VERDICT_VERBOSE: Final[str] = "VERBOSE"
_LLM_VERDICT_NONE: Final[str] = "NONE"
_LLM_VERDICT_TO_MODE: Final[dict[str, str]] = {
    _LLM_VERDICT_CONCISE: LENGTH_MODE_CONCISE,
    _LLM_VERDICT_VERBOSE: LENGTH_MODE_VERBOSE,
}
#: 文风维度的模型侧简写 → 受登记指令码（只这两枚，认不出即不改）。
_LLM_VERDICT_TO_STYLE: Final[dict[str, str]] = {
    "LITERARY": _STYLE_LITERARY,
    "PLAIN": _STYLE_PLAIN,
}
#: 结构化回答三个字段的名字（正则口径只在这里写一次）。
_LLM_VERDICT_FIELD_RES: Final[dict[str, re.Pattern[str]]] = {
    "length_mode": re.compile(r"LENGTH\s*=\s*([A-Z_]+)"),
    "style_code": re.compile(r"STYLE\s*=\s*([A-Z_]+)"),
    "ask": re.compile(r"ASK\s*=\s*([A-Z_;,+ ]+)"),
}

#: 用户那段话进判定请求前的窗口：判定不需要全文，短窗同时压缩注入面。
_LLM_JUDGMENT_TEXT_MAX_CHARS: Final[int] = 200


def build_policy_judgment_messages(text: object) -> list[dict[str, str]]:
    """判定请求的 messages（用户原话先消毒再截窗——它是不可信输入）。"""
    safe_text = sanitize_evidence(text, limit=_LLM_JUDGMENT_TEXT_MAX_CHARS)
    return [
        {"role": "system", "content": LLM_JUDGMENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"说话人这一句：「{safe_text}」"},
    ]


def parse_policy_verdict_fields(raw: object) -> dict[str, Any]:
    """模型回答 → 三个维度的裁决；**认不出的一律「不改」**，绝不落库。

    同时接受两种形状：新的一行结构（``LENGTH=…; STYLE=…; ASK=…``）与旧裸词
    （``CONCISE``／``VERBOSE``／``NONE``）。旧形状必须继续可解析——既有测试、
    线上历史回答与「模型只肯吐一个词」的降级路径都走它，打断旧腿就是回归。
    """
    text = str(raw or "").strip().strip("。.！!，,、\"'`“”").upper()
    verdict: dict[str, Any] = {"length_mode": "", "style_code": "", "content_directives": ()}
    if not text:
        return verdict
    length_match = _LLM_VERDICT_FIELD_RES["length_mode"].search(text)
    if length_match:
        verdict["length_mode"] = _LLM_VERDICT_TO_MODE.get(length_match.group(1), "")
    style_match = _LLM_VERDICT_FIELD_RES["style_code"].search(text)
    if style_match:
        verdict["style_code"] = _LLM_VERDICT_TO_STYLE.get(style_match.group(1), "")
    ask_match = _LLM_VERDICT_FIELD_RES["ask"].search(text)
    if ask_match:
        verdict["content_directives"] = normalize_content_directives(
            [part for part in re.split(r"[;,+]", ask_match.group(1)) if part.strip()]
        )
    if not any((length_match, style_match, ask_match)):
        # 旧裸词形：只答一个词，按 startswith 判，与改前逐字同形。
        for answer, mode in _LLM_VERDICT_TO_MODE.items():
            if text.startswith(answer):
                verdict["length_mode"] = mode
                break
    return verdict


def parse_policy_verdict(raw: object) -> str:
    """模型回答 → 长度模式（三维裁决的长度侧投影，签名与改前一致）。"""
    return str(parse_policy_verdict_fields(raw)["length_mode"] or "")


# ---------------------------------------------------------------------------
# 五乙、要不要花这次判定（廉价线索门）
# ---------------------------------------------------------------------------

#: 在提「怎么讲」的线索（**讲法族**：文风与修辞）。只收说法本身，不收「风格/语气」
#: 这类在日常里大量出现在别处（谈别人、谈第三条消息）的通名。
_STYLE_CUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(文学|文艺|文采|文笔|辞藻|诗意|意象|散文|画面|意境|拽词|掉书袋|文绉绉|口语"
    r"|大白话|通俗|接地气|像平时|平时说话|随便说两句|腔调|文风|说人话)",
    re.IGNORECASE,
)
#: 在提「讲多少」的线索（**长短族**，2026-09-28 她原话补上的那一族）：她的
#: 「以后回复我的时候详细一点，带点画面感」两族各中一枚，只认讲法族就会整句漏判。
#: 刻意**不**收确定性谓词（那是「直接落库」用的，宁可窄）——本表只决定要不要
#: 花一次判定调用，落不落库由模型点头说了算。
_LENGTH_CUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(详细|详尽|具体|细说|细讲|细一点|展开|多说|少说|多写|少写|讲清|说明白|说清楚"
    r"|讲透|来龙去脉|前因后果|重点|结论|一句|两句话|字太|太长|太短|简短|简洁|精简"
    r"|篇幅|长一点|短一点|说全|讲全)",
    re.IGNORECASE,
)
#: 长期性线索（「以后」「每次都」）：与偏好线索同时出现时这次判定几乎一定有产出。
_LONG_TERM_CUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(以后|今后|从今以后|从现在开始|记住|每次|总是|一直|永远|长期|别再|别总是)"
)
#: 请求/评价句式的弱线索：没有它，「有点文学味儿」这类不成词说法就判不出来。
_REQUEST_CUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(能不能|可不可以|能否|还是|太|一点|一些|些|吧)"
)


def wants_policy_judgment(text: object) -> bool:
    """这句话值不值得花一次 LLM 判定（**只判值不值得，不判内容**）。

    四条任一成立即问：① 长度谓词自己判不定（既有歧义轨，一条都不许瞎）；
    ② 提了讲法或长短，且带长期性线索；③ 提了讲法或长短，且是请求/评价句式；
    ④ 讲法族本身就足够少见（「文学味儿」这种词很少出现在别的话题里）。
    两条线索族是**门票不是判据**：门可以放宽，因为落不落库仍由模型明确点头决定，
    误判的代价从「铸成一份反向永久策略」降为「多问一次」。明显无关的句子一次
    都不问——判定腿是花钱的，挂在每条消息上既拖慢每一轮，也让注入面每轮多开一次口。
    """
    stripped = " ".join(str(text or "").split())
    if not stripped:
        return False
    if detect_length_change_request(stripped).get("ambiguous"):
        return True
    if not (_STYLE_CUE_RE.search(stripped) or _LENGTH_CUE_RE.search(stripped)):
        return False
    if _STYLE_CUE_RE.search(stripped) and not _LENGTH_CUE_RE.search(stripped):
        return True
    return bool(_LONG_TERM_CUE_RE.search(stripped) or _REQUEST_CUE_RE.search(stripped))


# ---------------------------------------------------------------------------
# 六乙、按人预设口（/bot reply set|show|clear，2026-09-28 用户裁定 Q3「甲+乙」的甲半边）
# ---------------------------------------------------------------------------

#: 能力号沿用既有 `/bot reply`（同一命令面，只是多两个作用域：按人 vs 全局）。
PRESET_CAPABILITY_ID: Final[str] = "bot.reply"
PRESET_USAGE_TEXT: Final[str] = (
    "用法：/bot reply set <QQ号> <默认|简洁|适中|讲全|详尽> [文学化|说人话]\n"
    "复查：/bot reply show <QQ号>　撤销：/bot reply clear <QQ号>\n"
    "（不带 set/show/clear 的那条老写法改的是**全局档**，与本件按人策略分开。）"
)

#: 人话 → 受登记长度模式。**刻意不复用 chat 的档名拼音**：这一面只服务命令文案，
#: 认完立刻折算成 LENGTH_MODES 里的在册值，库里永远只住规范形。
_PRESET_LENGTH_WORDS: Final[dict[str, str]] = {
    "默认": LENGTH_MODE_AUTO,
    "auto": LENGTH_MODE_AUTO,
    "简洁": LENGTH_MODE_CONCISE,
    "简短": LENGTH_MODE_CONCISE,
    "精简": LENGTH_MODE_CONCISE,
    "一句话": LENGTH_MODE_CONCISE,
    "适中": LENGTH_MODE_NORMAL,
    "正常": LENGTH_MODE_NORMAL,
    "像平时": LENGTH_MODE_NORMAL,
    "讲全": LENGTH_MODE_NARRATIVE,
    "展开": LENGTH_MODE_NARRATIVE,
    "说清": LENGTH_MODE_NARRATIVE,
    "详尽": LENGTH_MODE_VERBOSE,
    "详细": LENGTH_MODE_VERBOSE,
    "掰碎": LENGTH_MODE_VERBOSE,
    "长文本": LENGTH_MODE_VERBOSE,
}
_PRESET_STYLE_WORDS: Final[dict[str, str]] = {
    "文学化": _STYLE_LITERARY,
    "文学": _STYLE_LITERARY,
    "文艺": _STYLE_LITERARY,
    "文采": _STYLE_LITERARY,
    "说人话": _STYLE_PLAIN,
    "口语": _STYLE_PLAIN,
    "大白话": _STYLE_PLAIN,
    "接地气": _STYLE_PLAIN,
}
#: 长度模式的**人话名**，只用于回读与证据文案（不参与判据，判据认的是在册规范值）。
_PRESET_LENGTH_LABELS: Final[dict[str, str]] = {
    LENGTH_MODE_AUTO: "默认（不表态，交回全局档与题型）",
    LENGTH_MODE_CONCISE: "简洁",
    LENGTH_MODE_NORMAL: "适中",
    LENGTH_MODE_NARRATIVE: "讲全",
    LENGTH_MODE_VERBOSE: "详尽",
}
_PRESET_STYLE_LABELS: Final[dict[str, str]] = {
    _STYLE_LITERARY: "文学化",
    _STYLE_PLAIN: "说人话",
}


def _preset_result(
    request_id: str, body: str, *, tags: tuple[str, ...] = (), ok: bool = True
) -> Any:
    from plugins.bot_unified_runtime.contracts import CapabilityResult

    return CapabilityResult(
        request_id=request_id,
        capability_id=PRESET_CAPABILITY_ID,
        kind="text" if ok else "error",
        body=body,
        audit_tags=["reply_preset", *tags],
    )


def _match_preset_word(token: str) -> tuple[str, str]:
    """命令词 → ``(维度, 规范值)``；前缀匹配（``文学化[/TRUSTED_SYSTEM]`` 也认得出
    文学化，而尾部脏文本**不进**任何字段），认不出回 ``("","")``。"""
    for word, mode in _PRESET_LENGTH_WORDS.items():
        if token.startswith(word):
            return "length", mode
    for word, code in _PRESET_STYLE_WORDS.items():
        if token.startswith(word):
            return "style", code
    return "", ""


def build_reply_policy_preset_result(
    config: object,
    *,
    request_id: str,
    sender_id: str,
    actor_roles: Any = (),
    command_text: str = "",
) -> Any:
    """/bot reply set|show|clear —— 管理员**按人**钉、查、撤回复策略。

    与既有 `/bot reply <详细|精简|默认>` 的分工：那条改的是全局 `BOT_REPLY_DETAIL`
    （影响所有人），本件改的是 `user_reply_policy` 里**那个人**的一行（跨群跨私聊、
    跨人格都跟着人走）。两者共用同一张长度表，所以不会长成第二套长度判据。

    三条纪律：
    1. **权限**：管理员才能动别人；被设目标是超管时，只有超管能设（提权面不许横向）。
    2. **证据只写「谁给谁设了什么」**，绝不把命令原文存进 ``evidence``——那是可控文本，
       将来会被读进提示词（同 :func:`policy_directive_text` 不复述证据的理由）。
    3. **未知词不落库**：认不出就回用法，误敲一次不该变成一份永久策略。
    """
    parts = str(command_text or "").split()
    if not parts:
        return _preset_result(request_id, PRESET_USAGE_TEXT, tags=("empty",))
    action = parts[0].strip().lower()
    if action not in {"set", "show", "clear"}:
        return _preset_result(
            request_id, f"未知的子命令：{action}。\n{PRESET_USAGE_TEXT}", tags=("bad_action",)
        )
    roles = {str(role).lower() for role in (actor_roles or ())}
    if "admin" not in roles and "super" not in roles:
        return _preset_result(
            request_id, "只有管理员才能替别人设定回复策略。", tags=("denied",)
        )
    if len(parts) < 2:
        return _preset_result(request_id, PRESET_USAGE_TEXT, tags=("no_target",))
    target = parts[1].strip()
    person_key = person_reply_policy_key(sender_id=target)
    if not person_key:
        return _preset_result(
            request_id, f"认不出这个 QQ 号：{target}。\n{PRESET_USAGE_TEXT}", tags=("bad_target",)
        )

    super_ids = {str(item).strip() for item in (getattr(config, "bot_super_admin_user_ids", []) or [])}
    actor_is_super = "super" in roles or str(sender_id).strip() in super_ids
    if target in super_ids and not actor_is_super:
        return _preset_result(
            request_id,
            "那个号是超管，只有超管能改它的口径（普通管理员无权横跨提权面）。",
            tags=("denied_super_target",),
        )

    store = shared_reply_policy_store(config)
    if store is None:
        return _preset_result(
            request_id, "回复策略存储不可用，本轮没改动任何东西。", ok=False, tags=("store_unavailable",)
        )
    try:
        current = store.get(person_key)
    except Exception:  # noqa: BLE001 - 读失败按无既有策略处理，不阻断命令回话。
        current = None

    if action == "show":
        if current is None:
            return _preset_result(
                request_id, f"{target} 目前没有设定过回复策略（走全局档）。", tags=("show: none",)
            )
        bits = [f"长度＝{_PRESET_LENGTH_LABELS.get(current.length_mode, current.length_mode)}"]
        styles = [
            _PRESET_STYLE_LABELS.get(code, code) for code in current.content_directives
        ]
        bits.append("文风／讲法＝" + ("、".join(styles) if styles else "未设"))
        bits.append(f"最近一次变更＝{current.updated_at or '未知时间'}（来源 {current.source}）")
        return _preset_result(request_id, f"{target} 的回复策略：" + "；".join(bits), tags=("show",))

    if action == "clear":
        if current is None:
            return _preset_result(
                request_id, f"{target} 本来就没有策略，无需撤销。", tags=("clear:noop",)
            )
        store.clear(person_key)
        return _preset_result(request_id, f"已撤销 {target} 的回复策略，回到全局档。", tags=("clear",))

    length_mode = ""
    wanted_styles: list[str] = []
    for token in parts[2:]:
        dimension, value = _match_preset_word(token.strip())
        if not dimension:
            return _preset_result(
                request_id,
                f"未知的回复档位或文风：{token.split('[')[0][:16]}。\n{PRESET_USAGE_TEXT}",
                tags=("bad_word",),
            )
        if dimension == "length":
            length_mode = value
        elif value not in wanted_styles:
            wanted_styles.append(value)
    if not length_mode and not wanted_styles:
        return _preset_result(request_id, PRESET_USAGE_TEXT, tags=("nothing_to_set",))

    existing = tuple(current.content_directives) if current else ()
    updated = ReplyPolicy(
        person_key=person_key,
        length_mode=normalize_length_mode(length_mode)
        if length_mode
        else (current.length_mode if current else LENGTH_MODE_AUTO),
        content_directives=merge_content_directives(existing, tuple(wanted_styles)),
        note=(current.note if current else ""),
        source=SOURCE_EXPLICIT,
        evidence=sanitize_evidence(
            f"管理员 {sender_id} 为 {target} 设定："
            f"{_PRESET_LENGTH_LABELS.get(length_mode, '')}".strip(),
            limit=_EVIDENCE_MAX_CHARS,
        ),
        updated_at="",
    )
    if not store.put(updated):
        return _preset_result(
            request_id, "写库失败，本轮没有改动任何策略。", ok=False, tags=("persist_failed",)
        )
    shown = _PRESET_LENGTH_LABELS.get(updated.length_mode, updated.length_mode)
    style_shown = "、".join(_PRESET_STYLE_LABELS.get(code, code) for code in updated.content_directives)
    return _preset_result(
        request_id,
        f"已为 {target} 设定：长度＝{shown}" + (f"；讲法＝{style_shown}" if style_shown else "") + "。跨群跨私聊、换人格都跟着这个人走。",
        tags=("set", f"length:{updated.length_mode}"),
    )


# ---------------------------------------------------------------------------
# 七、存储
# ---------------------------------------------------------------------------


_SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS user_reply_policy (
        person_key TEXT NOT NULL PRIMARY KEY,
        length_mode TEXT NOT NULL DEFAULT 'auto',
        content_directives TEXT NOT NULL DEFAULT '[]',
        note TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'explicit',
        evidence TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    )
    """,
)


@dataclass
class ReplyPolicyStore:
    """``user_reply_policy`` 的唯一读写口（单连接 + 锁 + WAL，同称谓偏好 store 家规）。

    一切外部输入在这里归一/消毒/限长 ⇒ 「脏输入不崩库」是存储层的责任，不是调用方的。
    任何 SQLite 故障只降级为「本轮没有策略」，绝不让一条聊天消息因此炸掉。

    ``person_aliases``（2026-09-28 用户裁定「3865067623 + 1722380002 并成一个键」）
    是**号 → 该号并入的号**映射，归并只发生在这里：键的构造仍走
    :func:`domains.core.session_keys.private_session_key` 这一条中央口，本件不手拼前缀；
    而权限/角色/同意判定**一律不读这张表**（有锁钉死，见
    ``tests/test_reply_policy_permanent.py::test_person_aliases_never_leak_into_privilege``）——
    并号只并"偏好存到哪个键"，不把两个号并成同一个权限主体。
    """

    path: Path
    person_aliases: Mapping[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        normalized: dict[str, str] = {}
        try:
            for raw_key, raw_target in dict(self.person_aliases or {}).items():
                key = str(raw_key or "").strip()
                target = str(raw_target or "").strip()
                if key and target:
                    normalized[key] = target
        except Exception:  # noqa: BLE001 - 配置写坏＝不并号，绝不让策略整链塌掉。
            logger.warning("reply policy aliases ignored type=%s", "Unparseable")
            normalized = {}
        self.person_aliases = normalized
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), check_same_thread=False)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=3000")
            self._conn = connection
            self._ensure_schema()
        except Exception as exc:  # noqa: BLE001 - 建库失败只降级，不抛给聊天主链路。
            logger.warning("reply policy store unavailable path=%s type=%s", self.path, type(exc).__name__)
            self._conn = None

    # ---- 并号：别名→主键，只在这一处发生 ----------------------------------

    def canonical_person_key(self, person_key: Any) -> str:
        """把一个号归并成它该落到的那把键（无映射的号**逐字节原样**返回）。

        链式映射（A→B→C）走到底，带**环保护**：A→A 不自吞、A→B→A 不无限绕。
        """
        key = str(person_key or "").strip()
        if not key or not self.person_aliases:
            return key
        seen: set[str] = {key}
        current = key
        while True:
            target = str(self.person_aliases.get(current, "") or "").strip()
            if not target or target in seen:
                break
            seen.add(target)
            current = target
        if current == key:
            return key
        return private_session_key(current)

    def _legacy_keys_of(self, canonical: str) -> list[str]:
        """哪些旧键归并后就等于 ``canonical``（用于把并键前写下的行前移过来）。"""
        if not self.person_aliases:
            return []
        legacy: list[str] = []
        for alias in self.person_aliases:
            if self.canonical_person_key(alias) == canonical and canonical != str(alias).strip():
                legacy.append(str(alias).strip())
        return legacy

    def _ensure_schema(self) -> None:
        if self._conn is None:
            return
        with self._lock, self._conn:
            for statement in _SCHEMA_STATEMENTS:
                self._conn.execute(statement)
            existing = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(user_reply_policy)")
            }
            # 旧库补列走 ALTER-if-missing（家规＝affinity / addressing 同族），不要求人工迁移。
            for column, ddl in (
                ("note", "ALTER TABLE user_reply_policy ADD COLUMN note TEXT NOT NULL DEFAULT ''"),
                (
                    "source",
                    "ALTER TABLE user_reply_policy ADD COLUMN source TEXT NOT NULL DEFAULT 'explicit'",
                ),
                (
                    "evidence",
                    "ALTER TABLE user_reply_policy ADD COLUMN evidence TEXT NOT NULL DEFAULT ''",
                ),
            ):
                if column not in existing:
                    self._conn.execute(ddl)

    def _read_row(self, key: str) -> ReplyPolicy | None:
        if self._conn is None or not key:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT person_key, length_mode, content_directives, note,"
                    " source, evidence, updated_at"
                    " FROM user_reply_policy WHERE person_key = ?",
                    (key,),
                ).fetchone()
        except Exception as exc:  # noqa: BLE001 - 读失败＝本轮无策略。
            logger.warning("reply policy read failed type=%s", type(exc).__name__)
            return None
        if not row:
            return None
        return ReplyPolicy(
            person_key=str(row[0]),
            length_mode=normalize_length_mode(row[1]),
            content_directives=normalize_content_directives(row[2]),
            note=str(row[3] or ""),
            source=str(row[4] or SOURCE_EXPLICIT),
            evidence=str(row[5] or ""),
            updated_at=str(row[6] or ""),
        )

    # ---- 读 ---------------------------------------------------------------

    def get(self, person_key: str) -> ReplyPolicy | None:
        key = self.canonical_person_key(person_key)
        if not key:
            return None
        policy = self._read_row(key)
        if policy is None:
            # 并键之前写下的行还挂在旧号上 ⇒ **前移一次**（复制成主键行后删旧行，
            # 不留第二份真身；她后来改口径只会改到一处）。判据不能是"输入键≠主键"——
            # 她那行今天正是写在侧号上、而下一轮从**主号**来读，那样恰好漏掉。
            for legacy in self._legacy_keys_of(key):
                moved = self._read_row(legacy)
                if moved is None:
                    continue
                if self.put(replace(moved, person_key=key, updated_at="")):
                    self._delete_key(legacy)
                    logger.info("reply policy alias row moved %s -> %s", legacy, key)
                return self._read_row(key)
        return policy

    # ---- 写（同键覆盖＝反悔天然生效）--------------------------------------

    def put(self, policy: ReplyPolicy) -> bool:
        """永久落库：同一 ``person_key`` 覆盖同一行。返回是否真的写成。

        写入一律落在**归并后的主键**上（并号 ⇒ 一个人一行），行里的 ``person_key``
        也就是主键，读回来不再换形状。
        """
        key = self.canonical_person_key(policy.person_key)
        if not key or self._conn is None:
            return False
        payload = (
            key,
            normalize_length_mode(policy.length_mode),
            policy.encoded_directives()[:_DIRECTIVE_ENCODE_MAX_CHARS],
            sanitize_note(policy.note),
            policy.source if policy.source in POLICY_SOURCES else SOURCE_EXPLICIT,
            sanitize_evidence(policy.evidence),
            policy.updated_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO user_reply_policy"
                    " (person_key, length_mode, content_directives, note, source,"
                    "  evidence, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(person_key) DO UPDATE SET"
                    "  length_mode = excluded.length_mode,"
                    "  content_directives = excluded.content_directives,"
                    "  note = excluded.note,"
                    "  source = excluded.source,"
                    "  evidence = excluded.evidence,"
                    "  updated_at = excluded.updated_at",
                    payload,
                )
            return True
        except Exception as exc:  # noqa: BLE001 - 写失败只留痕，绝不让聊天炸。
            logger.warning("reply policy write failed type=%s", type(exc).__name__)
            return False

    def _delete_key(self, key: str) -> bool:
        if self._conn is None or not key:
            return False
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "DELETE FROM user_reply_policy WHERE person_key = ?", (key,)
                )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("reply policy delete failed type=%s", type(exc).__name__)
            return False

    def clear(self, person_key: str) -> bool:
        """撤销这个人的策略：主键行 + 并键前留在各别号上的旧行**一起清**。

        只清主键会留一条"看不见但仍会被前移回来"的旧行 ⇒ 撤销不干净，
        下一轮读到旧号行就等于「她说撤了，它又回来了」。
        """
        key = self.canonical_person_key(person_key)
        if not key or self._conn is None:
            return False
        cleared = self._delete_key(key)
        for legacy in self._legacy_keys_of(key):
            self._delete_key(legacy)
        return cleared


_STORES: dict[str, ReplyPolicyStore] = {}
_STORES_LOCK = threading.Lock()

REPLY_POLICY_DB_FALLBACK_PATH: Final[str] = "data/reply_policy.sqlite3"


def shared_reply_policy_store(config: object) -> ReplyPolicyStore | None:
    """进程级共享 store（懒建、按解析后的路径缓存；任何失败返回 None 不阻断对话）。"""
    if not bool(getattr(config, "bot_reply_policy_enabled", True)):
        # 总闸关＝整条永久策略腿不存在（读与写都不发生），与"该人从没说过"逐字节同形；
        # 她是按"随时能一键退回今天之前"的要求要这枚键的，所以闸门必须在这张口上、
        # 而不是散在调用方——调用方拿不到 store 就是唯一形态。
        return None
    raw_path = str(
        getattr(config, "bot_reply_policy_db_path", REPLY_POLICY_DB_FALLBACK_PATH)
        or REPLY_POLICY_DB_FALLBACK_PATH
    )
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
            build_runtime_data_path,
        )

        path = Path(build_runtime_data_path(config, raw_path))
    except Exception:  # noqa: BLE001 - 解析不出来＝本轮没有策略，不猜路径
        logger.warning("reply policy path unresolved; policy leg off this process")
        return None
    # 解析器按环境变量的运行时数据根走；没配（测试环境就是如此）会退回**源码树里的
    # data/**。规则 2/6：源码树零 `data/` 残余——本席实跑就被卫生门抓过一次
    # （test_search_acg_switch_leg 里凭空写出 reply_policy.sqlite3/-wal/-shm）。
    # 所以这里宁可整条腿不建库，也绝不往树里落文件；生产配了 BOT_RUNTIME_DATA_DIR
    # （绝对路径）时这条判据天然不触发。
    repo_root = Path(__file__).resolve().parents[5]
    try:
        lands_in_tree = path.resolve().is_relative_to(repo_root / "data")
    except (OSError, ValueError):  # pragma: no cover - 解析异常按落树处理（保守拒绝）
        lands_in_tree = True
    if lands_in_tree:
        logger.warning("reply policy path inside source tree; policy leg off")
        return None
    cache_key = f"{path}|{sorted(dict(getattr(config, 'bot_reply_policy_person_aliases', {}) or {}).items())}"
    with _STORES_LOCK:
        store = _STORES.get(cache_key)
        if store is None:
            store = ReplyPolicyStore(
                path,
                person_aliases=dict(
                    getattr(config, "bot_reply_policy_person_aliases", {}) or {}
                ),
            )
            _STORES[cache_key] = store
        return store


__all__ = [
    "CONTENT_DIRECTIVES",
    "LENGTH_MODES",
    "LLM_ASKABLE_CODES",
    "LLM_JUDGMENT_SYSTEM_PROMPT",
    "REPLY_POLICY_DB_FALLBACK_PATH",
    "SOURCE_EXPLICIT",
    "SOURCE_INFERRED",
    "STYLE_CODES",
    "ReplyPolicy",
    "ReplyPolicyStore",
    "build_policy_judgment_messages",
    "detect_content_directives",
    "detect_length_change_request",
    "detect_reversal_request",
    "merge_content_directives",
    "normalize_content_directives",
    "normalize_length_mode",
    "parse_policy_verdict",
    "parse_policy_verdict_fields",
    "person_reply_policy_key",
    "policy_directive_text",
    "remove_content_directives",
    "sanitize_evidence",
    "sanitize_note",
    "shared_reply_policy_store",
    "wants_policy_judgment",
]
