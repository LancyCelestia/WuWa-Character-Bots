"""群信息能力（bot.group_info）：群资料/群主/人数/公告/精华，一问直答。

来源：审查 B-01/B-04——用户实测问「群主是谁/群人数/群公告」答不上，根因是
OneBot V11/SnowLuma 明明支持群 API（get_group_info / get_group_member_list /
get_group_notice / get_essence_msg_list）而全仓零调用。本能力补齐这条链路。

权限分级（复用媒体归档的 _role_atLeast 同款角色秩模式）：
- 群名/群主/人数/上限/管理员数：全员；
- 公告首段与精华条数：仅管理员（bot 侧角色门，协议侧再失败即如实降级）。

隐私与刷屏红线：成员名单**不整列**——只给统计数与群主/管理员数，
绝不输出逐个成员的名单。

**参与者这条腿（2026-09-26 S-T-GRP-2）走的是另一套依据**：用户裁定「参与者按记忆算」，
所以「这个会话里有谁」报的是**我记下说过话的人**（读 ``conversation_turns`` 的
``role='user'`` 行，取数件
``domains/chat_reply/runtime/participant_memory.py``），不是协议层成员名单——
既为隐私与防刷屏，也因为 QQ 侧逐成员状态在本协议端动作册里并不可靠。
回答里因此**必须自带两句**：依据句（按记录数的、不是名单）与缺口句（名单没整份读过）。
名字只从在册唯一记录位 ``group_affinity.display_name`` 取，取不到就说取不到，**绝不**
拿用户号顶上；展示有界截断并点名「另有 N 位未列出」。三态分立：记到人 / 没记下有人说话 /
**读不出**——最后一种绝不许被写成「这个群没有人」（本仓常驻禁令，commits cd0068c/21bdabf）。
这条腿不依赖名单，所以 Telegram 在这一项与 QQ **真同权**（Bot API 不开放名单，
但记忆是我的）；邮件侧则**结构性答不全**（看不见 To/Cc 全集），只声明缺口不假装同权。

诚实降级清单（拿不到就直说，不做不假装）：
- 群介绍（``group_memo``）与建群时间走 ``get_group_info`` 的返回字段：字段在就报，
  不在就如实说拿不到，不折算不猜；
- 「本群多大了」用的 ``group_create_time`` 不在 OneBot V11 规范文本里，但现役协议端
  SnowLuma 1.14.19 的动作册把它登记在 ``get_group_info`` 返回里（旧注释写作
  「NapCat 扩展」是退役期的历史口径，2026-09-25 按动作册更正）；
- **群文件已接（本地账本口径）**：``profile`` 全量档里追加「群文件概览」，数据来自
  协议端 ``group_upload`` notice 喂的 ``GroupFileStore``（见
  domains/files/capabilities/group_files.py）——报的是**我见过的上传**，不是群盘全量。
  未注入账本时这一段整段不出现（缺数=缺行）；协议端另有 ``get_group_root_files``
  可读全量群盘，动作名留待在线核验后再接，不拿未核的名字去猜然后谎报「接口没回应」；
- **协议端有登记、本能力尚未接**（不是「协议无 API」，别照旧注释再判一次死）：
  群链接 ``get_share_link``——接它要同步动帮助词表（触发词双向门），排在本能力下一批。
  （2026-09-25 二批：群相册 ``get_group_album_list``、群待办 ``get_group_todo_list``
  **已接**，各自独立意图与触发词；两者都按 ``_get_group_notice`` 的先例做「裸名 +
  下划线本名」两试，认不出的字段名退成「这条读不出」而不编造。）
- **结构性拿不到**（对 189 枚动作逐名核过的结论，不是没找）：幸运符号（无对应动作，
  最接近的 ``get_group_signed_list`` 是「今日打卡」）、他人电量（``battery_status``
  只在 ``set_online_status`` 的**入参**里出现，没有读的口）、网络制式（WiFi/5G 无字段）；
- API 失败/未接线/无权限：如实口语降级，不编数据、不静默吞掉。

缓存：群资料 600s/成员列表 900s/公告 600s/精华 600s/相册 600s/**待办 120s**/
**参与者 60s**（且只缓存「这次真读到人了」——空态与读不出落缓存会把刚开口的人挡在
TTL 外），见 runtime/group_cache.py（只缓存成功载荷）。

接线说明（主会话负责 __init__.py）：能力运行在管线 offload 线程池（同步
调用），而 bot.call_api 是协程——由 ``build_onebot_api_bridge`` 提供
run_coroutine_threadsafe 桥接，构建工厂时以 ``api=`` 注入；``api=None``
时所有查询走诚实降级（不炸、不装）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
    KIND_ALBUM,
    KIND_ESSENCE,
    KIND_MEMBER_COUNT,
    KIND_MEMBERS,
    KIND_NOTICE,
    KIND_PARTICIPANTS,
    KIND_PROFILE,
    KIND_SELF_MEMBER,
    KIND_TODO,
    GroupInfoCache,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.participant_memory import (
    STATE_EMPTY,
    STATE_OK,
    HistoryParticipantReader,
    build_participant_reader,
    group_participant_scope,
    session_participant_scope,
)
from plugins.bot_unified_runtime.domains.core.text_boundary import (
    PARTICLE_BOUNDARY_CHARS,
    is_trigger,
    matched_trigger_word,
)

# ---------------------------------------------------------------------------
# 触发词与意图（T-Spec 口径：CJK 复合词，词界天然安全；刻意不收英文裸词，
# 避免 group/notice 这类英文口语劫持；ASCII 词边界纪律因此不适用）
# ---------------------------------------------------------------------------

_INTENT_OWNER_WORDS: tuple[str, ...] = ("群主是谁", "谁是群主", "群主")
_INTENT_COUNT_WORDS: tuple[str, ...] = ("群人数", "本群人数", "本群多少人")
_INTENT_AGE_WORDS: tuple[str, ...] = ("本群多大了", "群多大了", "本群多大", "群多大")
_INTENT_NOTICE_WORDS: tuple[str, ...] = ("群公告", "本群公告")
_INTENT_ESSENCE_WORDS: tuple[str, ...] = ("群精华", "本群精华", "精华消息")
_INTENT_PROFILE_WORDS: tuple[str, ...] = ("群信息", "本群信息", "群资料", "本群资料")
# 相册/待办只收**带「群」前缀的复合词**：裸「相册」「待办」会劫持日常对话
# （「我相册里那张图」不该触发一次群务查询），与本文件既有的保守边界同口径。
_INTENT_ALBUM_WORDS: tuple[str, ...] = ("群相册", "本群相册", "群相册列表")
_INTENT_TODO_WORDS: tuple[str, ...] = ("群待办", "本群待办", "群待办列表")
# 参与者族（用户裁定「参与者按记忆算」）：群作用域词 + 会话作用域词**共用一个意图**，
# 渲染按会话形态分腿——同一份判据，不开两套答案。
# 刻意**不收**「群成员」「成员名单」：那是协议层名单的说法，本腿答的是记忆里的说话人，
# 用名单的词形去接会让人以为我读到了名单（而 `owner`/`profile` 腿早已声明不整列）。
_INTENT_WHO_WORDS: tuple[str, ...] = (
    "群里都有谁",
    "本群都有谁",
    "群里谁说过话",
    "本群谁说过话",
    "群参与者",
    "本群参与者",
    "都有谁说过话",
    "我都跟谁聊过",
    "跟谁聊过",
)

# 词 → 意图（插入序=分组序；sorted by len 保证最长词优先消歧）。
_INTENT_OF_WORD: dict[str, str] = {
    word: intent
    for intent, words in (
        ("profile", _INTENT_PROFILE_WORDS),
        ("owner", _INTENT_OWNER_WORDS),
        ("count", _INTENT_COUNT_WORDS),
        ("age", _INTENT_AGE_WORDS),
        ("notice", _INTENT_NOTICE_WORDS),
        ("essence", _INTENT_ESSENCE_WORDS),
        ("album", _INTENT_ALBUM_WORDS),
        ("todo", _INTENT_TODO_WORDS),
        ("who", _INTENT_WHO_WORDS),
    )
    for word in words
}

# 全部触发词（is_group_info_command 的判定面；触发体检从此函数字面提取）。
GROUP_INFO_TRIGGER_WORDS: tuple[str, ...] = tuple(_INTENT_OF_WORD)

# 词尾边界字（与 media_archive 同哲学的保守边界：触发词后只能跟标点/语气
# 助词/空白，防「群主管」「群信息表」类包含词误触发）。
# Wave G T66 收编：判定循环上收 domains/core/text_boundary.py，取值改由
# 「基段（标点+空白，= 权威集去 　\t）+ 中央 PARTICLE 登记全量」组合——
# 组合集与本文件原手抄串「，,。！？!?：:、 的了呢吗呀啊哈～~哦嘛咯哇」
# 逐字节等价；虚词集今后在中央登记处演化时本域自动跟随（加宽属行为变更，
# 另行评审）。
_BOUNDARY_BASE_CHARS = "，,。！？!?：:、 ～~"

_NOTICE_SNIPPET_CHARS = 100
#: 成员表 role 字段的中文身份（未知值一律降为「群成员」，不硬指认权限）。
_ROLE_LABELS = {"owner": "群主", "admin": "管理员", "member": "群成员"}
# 审查 Q-03 扩展：拒绝/指路类提示（私聊查群信息不受理）去拖尾语气符「～」，
# 句号收尾——温和但不拖尾音（同 meme_library 64efadf 口径）。
_PRIVATE_HINT = "群信息要在群里问才行哦，去群里喊我一声，我帮你看本群的资料。"
_UNAVAILABLE_LINE = "群资料接口这会儿没回应，这部分先不答啦——不瞎猜，过会儿再问一次试试？"


def is_group_info_command(text: str) -> bool:
    """触发词判定：整句等于触发词，或触发词后跟标点/语气边界（同媒体归档）。

    判定逻辑收编中央件（Wave G T66）：换行归一/裸词/最长词优先由
    ``is_trigger`` 承担；触发体检的字面提取面（词表 ``GROUP_INFO_TRIGGER_WORDS``）
    保持在本模块不变。
    """
    return is_trigger(
        text,
        GROUP_INFO_TRIGGER_WORDS,
        case_insensitive=False,
        bare_word=True,
        newline_as_space=True,
        boundary_chars=_BOUNDARY_BASE_CHARS,
        extra_boundary_chars=PARTICLE_BOUNDARY_CHARS,
    )


def detect_group_info_intents(text: str) -> frozenset[str]:
    """把触发文本解析成意图集（profile/owner/count/age/notice/essence）。

    命中多个词形时按最长词优先取其一（词形互斥设计，实际至多一个）；
    空集 = 未识别（调用方按全量档案处理或忽略）。命中判定收编中央件
    ``matched_trigger_word``（Wave G T66，返回命中的触发词本身）。
    """
    word = matched_trigger_word(
        text,
        GROUP_INFO_TRIGGER_WORDS,
        case_insensitive=False,
        newline_as_space=True,
        boundary_chars=_BOUNDARY_BASE_CHARS,
        extra_boundary_chars=PARTICLE_BOUNDARY_CHARS,
    )
    intent = _INTENT_OF_WORD.get(word)
    if not word or intent is None:
        return frozenset()
    return frozenset({intent})


def _role_at_least(sender_roles: list[str], min_role: str) -> bool:
    """角色秩判定（与 media_archive 同语义：max(角色) >= 所需档）。"""
    rank: dict[str, int] = {
        "user": 0,
        "trusted": 1,
        "enterprise": 2,
        "admin": 3,
        "super_admin": 4,
    }
    required = rank.get(str(min_role).strip().lower(), 4)
    return max((rank.get(role, -1) for role in sender_roles), default=-1) >= required


def build_onebot_api_bridge(
    bot: Any,
    loop: Any,
    timeout: float = 8.0,
) -> Callable[[str], Any]:
    """把异步 ``bot.call_api`` 桥接成能力线程可用的同步调用。

    能力在管线 offload 线程池执行，OneBot API 是事件循环上的协程；
    用 run_coroutine_threadsafe 跨线程投递并限时等结果（超时抛异常，
    由能力层按「接口没回应」诚实降级）。主会话在 __init__.py 装配：
    ``api=build_onebot_api_bridge(bot, asyncio.get_running_loop())``。
    """

    def call(action: str, **params: Any) -> Any:
        coro = bot.call_api(action, **params)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout)

    return call


def _first_paragraph(text: str, limit: int = _NOTICE_SNIPPET_CHARS) -> str:
    """取公告首段（首个非空行）并截断；超长以省略号收尾。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:limit] + ("…" if len(line) > limit else "")
    return ""


def _segment_text(payload: Any) -> str:
    """从 get_group_notice 的 message 字段提取纯文本（dict/list 双形态兼容）。"""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            parts: list[str] = []
            for seg in text:
                if isinstance(seg, dict):
                    parts.append(str(seg.get("text") or ""))
                elif isinstance(seg, str):
                    parts.append(seg)
            return "".join(parts)
    return ""


# ---------------------------------------------------------------------------
# 相册 / 待办的读数（第 4 项二批）
# ---------------------------------------------------------------------------

#: 每个分节最多列几条。**超出必须显式说「另有 N 条未列出」**——静默截断等于谎报
#: 「本群就这些」（同诊断卡对长配置值的口径）。
_SECTION_LINE_LIMIT = 5
#: 相册/待办的字段名是**候选表**，不是断言协议真有这个键：现役协议端的这类扩展
#: 字段名在不同版本间漂过，认不出来就退成「只报条数 + 这条读不出」，
#: 绝不因为没认出来就编一个名字或一个数出来。
#: 现役协议端的**真回字段名**（2026-09-25 对 SnowLuma 1.14.19 自带包体现算：
#: ACTION_REGISTRY 的 ``get_group_album_list`` returnsSchema 与 index.mjs 的
#: ``toLegacyAlbum``——相册为 ``name``/``picNum``，待办为 ``text``；证据全文见
#: ``.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-ALBUMNUM.md``）。
#: 照片数这枚在修前**整表没有真名**：现网每条真实相册都渲染成「照片数这次没回」，
#: 而 echo.py 帮助承诺的是「哪个相册多少张」——承诺与行为相反。修法＝真名进
#: 候选表**首位**、旧猜名保留为兼容形；名字/待办两表各自的真名（``name``/
#: ``text``）本就在册且命中，逐字段核过后一字未动。
_ALBUM_NAME_KEYS = ("albumname", "album_name", "name", "title")
_ALBUM_PIC_COUNT_KEYS = ("picNum", "total_pic_count", "pic_count", "photo_count", "count")
_TODO_TITLE_KEYS = ("title", "content", "text", "todo_content", "description")


def _first_str(item: Any, keys: tuple[str, ...]) -> str:
    """按候选键序取第一个非空字符串；全部落空回空串（调用方负责诚实降级）。"""
    body = _as_mapping(item)
    for key in keys:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_int(item: Any, keys: tuple[str, ...]) -> int | None:
    body = _as_mapping(item)
    for key in keys:
        value = body.get(key)
        if isinstance(value, bool):  # bool 是 int 的子类，但「True 张」不是数量。
            continue
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _album_lines(albums: list[Any]) -> list[str]:
    """相册概览：只到**相册**这一层，不列单张照片（隐私红线同成员名单）。"""
    lines = [f"群相册：{len(albums)} 个相册"]
    for album in albums[:_SECTION_LINE_LIMIT]:
        name = _first_str(album, _ALBUM_NAME_KEYS) or "（这个相册名字段读不出）"
        pics = _first_int(album, _ALBUM_PIC_COUNT_KEYS)
        lines.append(
            f"　· {name}：{pics} 张" if pics is not None else f"　· {name}：照片数这次没回"
        )
    if len(albums) > _SECTION_LINE_LIMIT:
        lines.append(f"　……另有 {len(albums) - _SECTION_LINE_LIMIT} 个相册未列出。")
    return lines


def _todo_lines(todos: list[Any]) -> list[str]:
    lines = [f"群待办：{len(todos)} 条"]
    for item in todos[:_SECTION_LINE_LIMIT]:
        title = _first_str(item, _TODO_TITLE_KEYS)
        if title:
            shown = title if len(title) <= 60 else title[:60] + "…"
            lines.append(f"　· {shown}")
        else:
            lines.append("　· （这条待办的标题字段读不出，只能报它还在）")
    if len(todos) > _SECTION_LINE_LIMIT:
        lines.append(f"　……另有 {len(todos) - _SECTION_LINE_LIMIT} 条未列出。")
    return lines


# ---------------------------------------------------------------------------
# Telegram 侧读数（第 4 项二批：「QQ、telegram、mail 都同理」）
# ---------------------------------------------------------------------------

#: ChatMember.status 的中文身份；词表照 Bot API 枚举，未知值一律降为「成员」，
#: 绝不因为没认出来就指认成管理员/群主。
_TG_STATUS_LABELS = {
    "creator": "群主",
    "administrator": "管理员",
    "member": "成员",
    "restricted": "受限成员",
    "left": "已离开",
    "kicked": "已被移出",
}
_TG_NO_ROSTER_LINE = "群主与管理员名单：Telegram 的 Bot API 不开放成员名单，这一项答不了，不猜。"
_TG_NO_SECTION_LINE = (
    "精华 / 群文件 / 相册 / 待办：Telegram 的 Bot API 没有对应接口，"
    "答不了（不是我没去查）。"
)


def _is_group_scoped_id(value: str) -> bool:
    """会话号形态：数字串，**允许前导负号**。

    Telegram 超级群/频道的 ``chat.id`` 是负数；旧判定 ``str.isdigit()`` 会让这条
    能力在 TG 上永远走到「没拿到群号」分支——开关是开的、路由是通的、路走不到。
    """
    digits = (value or "").strip().lstrip("-")
    return bool(digits) and digits.isdigit()


def _as_mapping(payload: Any) -> dict[str, Any]:
    """载荷形态归一：适配器可能回 dict，也可能回带 model_dump 的模型对象。"""
    if isinstance(payload, dict):
        return payload
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            body = dump()
        except Exception:  # noqa: BLE001 - 形态看不懂就当没有，不带着半截数据往下走。
            return {}
        if isinstance(body, dict):
            return body
    return {}


def _telegram_readout(
    fetch: Callable[..., tuple[bool, Any]],
    message: IncomingMessage,
    group_id: str,
    intents: frozenset[str],
) -> tuple[list[str], list[str]]:
    """Telegram 群资料读数；缺的口逐条直说。

    与 QQ 侧的三处**协议层真实差异**（不是漏接）：成员名单不开放（因此没有
    群主/管理员统计、没有精华名单）、公告的唯一形态是置顶消息、头衔来自
    ``get_chat_member.custom_title``。人数走 ``get_chat_member_count``。
    """
    lines = [f"群号：{group_id}"]
    audit = ["telegram"]
    chat_id = int(group_id)

    if {"profile", "age", "notice"} & intents:
        ok, raw_chat = fetch(KIND_PROFILE, group_id, "get_chat", chat_id=chat_id)
        chat = _as_mapping(raw_chat)
        if ok and chat:
            title = str(chat.get("title") or "").strip()
            if title:
                lines.append(f"群名：{title}")
            about = str(chat.get("description") or "").strip()
            if about:
                lines.append(f"群介绍：{about}")
            pinned = _as_mapping(chat.get("pinned_message")).get("text")
            if pinned:
                lines.append("置顶（本群公告位）：" + _first_paragraph(str(pinned)))
            elif "pinned_message" in chat:
                lines.append("置顶：这个群现在没有置顶消息。")
        elif ok:
            audit.append("api_shape_chat")
        else:
            lines.append(_UNAVAILABLE_LINE)

    if {"profile", "count"} & intents:
        ok, raw_count = fetch(
            KIND_MEMBER_COUNT, group_id, "get_chat_member_count", chat_id=chat_id
        )
        count = raw_count.get("result") if isinstance(raw_count, dict) else raw_count
        if ok and isinstance(count, int):
            lines.append(f"人数：{count}")
        elif ok:
            audit.append("api_shape_count")

    sender_id = str(message.sender_id or "").strip()
    if "profile" in intents and sender_id.isdigit():
        ok, raw_me = fetch(
            KIND_SELF_MEMBER, group_id, "get_chat_member", chat_id=chat_id, user_id=int(sender_id)
        )
        me = _as_mapping(raw_me)
        if ok and me:
            label = _TG_STATUS_LABELS.get(str(me.get("status") or "").strip().lower(), "成员")
            nick = str(_as_mapping(me.get("user")).get("first_name") or "").strip()
            lines.append(
                f"你在这里：{nick}（{label}）" if nick else f"你在这里的身份：{label}"
            )
            custom = str(me.get("custom_title") or "").strip()
            if custom:
                lines.append(f"群头衔：{custom}")
        elif ok:
            audit.append("api_shape_member")

    if {"profile", "owner"} & intents:
        lines.append(_TG_NO_ROSTER_LINE)
    if {"profile", "essence", "album", "todo"} & intents:
        lines.append(_TG_NO_SECTION_LINE)
    return lines, audit


# ---------------------------------------------------------------------------
# 参与者（用户裁定「参与者按记忆算」，2026-09-26 S-T-GRP-2）
# ---------------------------------------------------------------------------

#: 这条腿的**口径本身**要写在回答里：报的是我记下说过话的人，不是协议层群成员名单。
#: 两句都是判据，不是客套——少了第一句，读者会以为我读过名单；少了第二句，
#: 「7 位」会被当成全量人数（本能力早已声明成员名单不整列，见模块头红线）。
_PARTICIPANT_BASIS_LINE = (
    "参与者我是按聊过天的记录数的，不是群成员名单——名单我没整份读过。"
)
#: 记忆为空与记忆读不出是**两个态**，各自一句，绝不合并：
#: 把「我不知道」说成「它没有」是本仓的常驻禁令（commits cd0068c / 21bdabf）。
_PARTICIPANT_EMPTY_LINE = (
    "我这儿还没有人说过话的记录——这不等于这屋里没人说过话，只是我这边没记下。"
)
_PARTICIPANT_UNREADABLE_LINE = (
    "参与者这份记录这会儿读不出来（记忆没开，或账本一时打不开）——"
    "读不出不等于没人说话，我不拿它当「没有」。"
)
#: 邮件侧的**结构性**缺口：机器人看不见 To/Cc 全集，只知道回信人是谁。
#: 这一句是本腿唯一的「平台答不全」声明——不假装和 QQ/TG 同权。
_MAIL_PARTIAL_LINE = (
    "邮件这边我只看得见回信人是谁：一封邮件还发给了谁、抄送了谁，"
    "我读不到 To/Cc 全集，所以「这封里有谁」答不全——不猜。"
)
#: 名字取不到时的占位。**绝不**拿用户号顶上（群里贴一串 QQ 号既没用又伤人隐私）。
_PARTICIPANT_UNNAMED = "没记下名字的一位"
#: 只扫了有界窗口时的诚实声明（数字由读数件实算，不是这里写死的）。
_PARTICIPANT_WINDOW_LINE = "（只翻了最近 {limit} 条记录，更早的可能没算进来。）"


def _participant_person_label(record: Any, own_display_name: str = "") -> str:
    """一个人的展示名：只有在册的那一个源，取不到就照实说取不到。

    源优先级 = ``ParticipantRecord.display_name``（群作用域下来自
    ``group_affinity.display_name``，那是「本群这人叫什么」的唯一在册记录位）
    → 调用方手上当场事实（私聊用摄取层的 ``sender_display_name``）。
    两处都空 ⇒ ``_PARTICIPANT_UNNAMED``，**不回落用户号**。
    """
    for candidate in (
        str(getattr(record, "display_name", "") or "").strip(),
        (own_display_name or "").strip(),
    ):
        if candidate:
            return candidate
    return _PARTICIPANT_UNNAMED


def _participant_lines(
    memory: Any,
    *,
    subject: str,
    own_display_name: str = "",
    limit: int = _SECTION_LINE_LIMIT,
) -> list[str]:
    """参与者正文（群/TG 群用）。

    展示受 ``limit`` 截断，**截断必须点名**：列了几位、另有几位没列，两者相加恒等于
    实算总人数（静默截断＝谎报「就这些人」，与本文件相册/待办同一口径）。
    """
    records = list(getattr(memory, "records", ()) or ())
    total = int(getattr(memory, "total_speakers", len(records)) or 0)
    lines = [f"{subject}（按记忆算）：记到说过话的 {total} 位"]
    listed = records[:limit]
    for record in listed:
        turns = getattr(record, "turns", 0)
        lines.append(f"　· {_participant_person_label(record, own_display_name)}（说过 {turns} 句）")
    omitted = max(0, total - len(listed))
    if omitted:
        lines.append(f"　……另有 {omitted} 位未列出。")
    if bool(getattr(memory, "window_exhausted", False)):
        lines.append(_PARTICIPANT_WINDOW_LINE.format(limit=getattr(memory, "row_window", 0)))
    return lines


# 进程内共享缓存（同群反复被问不重复打协议；测试注入独立实例）。
_SHARED_CACHE = GroupInfoCache()


def build_group_info_capability(
    config: Any | None = None,
    *,
    api: Callable[[str], Any] | None = None,
    cache: GroupInfoCache | None = None,
    group_file_store: Any | None = None,
    participant_reader: HistoryParticipantReader | None = None,
) -> Callable[[IncomingMessage, Any], CapabilityResult]:
    """构建群信息能力。

    ``api``：同步群 API 调用器 ``api(action, **params) -> payload``（由
    build_onebot_api_bridge 桥接注入；None=未接线，全部诚实降级）。
    ``cache``：TTL 缓存（None=进程内共享实例；测试注入独立实例）。
    ``group_file_store``：群文件账本（``GroupFileStore``，由协议端
    ``group_upload`` notice 喂数据）。None=这一段整段不出现——群文件是
    「我见过的上传」这一本地口径，缺了不编数，也不换协议端接口名去猜。
    ``participant_reader``：参与者读数件（按记忆算那条腿）。None 且 ``config``
    给得出历史库路径时**由本工厂自构造**——装配点
    （``__init__.py:9081``）早就把 ``config`` 按位置传进来了，所以这条腿不需要
    再动根文件就能上线；两个都拿不到 ⇒ 参与者这一腿走「读不出」诚实降级，
    **不**是把别的腿一起废掉。
    ``config``：只被 ``participant_reader`` 的缺省构造用到（``bot_history_enabled``
    ∧ ``bot_history_db_path`` ∧ ``bot_affinity_db_path``，与写侧同源的门）。
    """
    store = cache or _SHARED_CACHE
    reader = participant_reader
    if reader is None and config is not None:
        try:
            reader = build_participant_reader(config)
        except Exception:  # noqa: BLE001 - 读数件构造失败只影响这一腿，不拖垮群资料。
            reader = None

    def _call(action: str, **params: Any) -> Any:
        if api is None:
            return None
        try:
            return api(action, **params)
        except Exception:  # noqa: BLE001 - 协议失败一律降级，不编造。
            return None

    def _fetch(
        kind: str, group_id: str, action: str, **api_params: Any
    ) -> tuple[bool, Any]:
        """缓存穿透读取；只缓存成功载荷（None=失败，不落缓存可重试）。

        ``api_params`` 缺省按 OneBot V11 的 ``group_id`` 形参；Telegram 侧调用点
        显式给 ``chat_id``/``user_id``（同一座桥，动作名与形参各自跟随协议端）。
        """
        hit, value = store.get(kind, group_id)
        if hit:
            return True, value
        payload = _call(action, **(api_params or {"group_id": int(group_id)}))
        if payload is None:
            return False, None
        store.put(kind, group_id, payload)
        return True, payload

    def _participants_block(
        message: IncomingMessage, *, is_group: bool, scope_label: str
    ) -> tuple[list[str], list[str]]:
        """参与者一腿（按记忆算）。读不出只影响这一腿，不带走群资料其它腿。

        群作用域走**中央件**构造的群前缀（``group_<gid>_``，绝不手拼键串）；
        私聊/邮件/控制台走**会话键等值**——这里刻意不放宽成前缀：私聊键是裸用户号，
        前缀匹配会把 ``386506762`` 的会话和 ``3865067623`` 的算成同一间屋子，
        那是把别人的私聊并进来的隐私事故。
        """
        scope = (
            group_participant_scope(message.group_id)
            if is_group
            else session_participant_scope(message.session_id)
        )
        if reader is None or scope is None:
            return [_PARTICIPANT_UNREADABLE_LINE], ["participants", "reader_absent"]

        hit, cached = store.get(KIND_PARTICIPANTS, scope.key)
        memory = cached if hit else reader.read(scope)
        if not hit and memory is not None and memory.state == STATE_OK:
            # 只缓存「这次真读到人了」。empty=还没记到、unavailable=读不出，
            # 两者落缓存都会让刚开口的第一个人被挡在 TTL 外——那正是这条腿最怕的漏报。
            store.put(KIND_PARTICIPANTS, scope.key, memory)

        state = getattr(memory, "state", "")
        audit = ["participants", state or "unknown"]
        if state == STATE_OK:
            own_name = ""
            if not is_group:
                # 私聊里「这人叫什么」的当场事实＝摄取层那唯一一枚字段，不另开名字账。
                own_name = str(message.sender_display_name or "").strip()
            lines = [
                _PARTICIPANT_BASIS_LINE,
                *_participant_lines(
                    memory,
                    subject=scope_label,
                    own_display_name=own_name,
                    limit=_SECTION_LINE_LIMIT,
                ),
            ]
            if not is_group and memory.total_speakers == 1:
                lines.append("（按记忆，这个会话里说过话的就你一位——我回的都不算。）")
            return lines, audit
        if state == STATE_EMPTY:
            return [_PARTICIPANT_BASIS_LINE, _PARTICIPANT_EMPTY_LINE], audit
        # 三态之外的任何形态都按「读不出」处理：宁可少答，不可把没读到写成没有。
        return [_PARTICIPANT_UNREADABLE_LINE], [
            *audit,
            str(getattr(memory, "reason", "") or "unknown"),
        ]

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = message.plain_text or ""

        def _result(
            body: str, *, audit: list[str], title: str = "群信息"
        ) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.group_info",
                kind="text",
                title=title,
                body=body,
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=audit,
            )

        if not is_group_info_command(text):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.group_info",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["group_info", "skip_no_trigger"],
            )

        intents = detect_group_info_intents(text)
        wants_participants = "who" in intents

        # 私聊/邮件/控制台：群 API 无对象可查，其余腿回守岸人口语提示（不做不假装）。
        # **唯独参与者这条腿在私聊答得上**——它读我自己的会话记忆，不需要协议层名单，
        # 所以不能一律拿「去群里问我」挡回去（那会把一条本来有答案的路堵死）。
        if message.session_type.value != "group":
            if not wants_participants:
                return _result(_PRIVATE_HINT, audit=["group_info", "private_hint"])
            participant_body, participant_audit = _participants_block(
                message, is_group=False, scope_label="本会话"
            )
            if message.session_type.value == "email":
                # 邮件的结构性缺口单独声明：只看得见回信人，看不见 To/Cc 全集。
                participant_body.insert(0, _MAIL_PARTIAL_LINE)
            return _result(
                "\n".join(participant_body),
                audit=["group_info", "conversation_participants", *participant_audit],
            )

        group_id = str(message.group_id or "").strip()
        if not _is_group_scoped_id(group_id):
            if not wants_participants:
                return _result(
                    "这条消息里没拿到群号，本群资料暂时查不了啦。",
                    audit=["group_info", "no_group_id"],
                )
            # 群号拿不到只关掉**协议**那几条腿；按记忆的参与者用的是事件自带的会话键，
            # 不需要群号也能答——一并把「查不了」宣出去就是拿别人的缺数冒充全体的缺数。
            participant_body, participant_audit = _participants_block(
                message, is_group=False, scope_label="本会话"
            )
            return _result(
                "\n".join(participant_body),
                audit=["group_info", "no_group_id", "conversation_participants", *participant_audit],
            )

        if not intents:
            intents = frozenset({"profile"})
        audit = ["group_info"]

        # Telegram 走自己那一套动作名与形参（同一座桥，收件事件决定用哪个 Bot 实例）。
        if str(message.platform or "").strip().lower() == "telegram":
            tg_lines, tg_audit = _telegram_readout(_fetch, message, group_id, intents)
            if wants_participants:
                # TG 的成员名单 Bot API 本就不开放（`_TG_NO_ROSTER_LINE`），而这条腿
                # 恰恰**不依赖名单**——按记忆算让 TG 与 QQ 在这一项上真同权，
                # 不是我把 QQ 的答案抄给 TG。
                participant_lines, participant_audit = _participants_block(
                    message, is_group=True, scope_label="本群"
                )
                tg_lines.extend(participant_lines)
                tg_audit.extend(participant_audit)
            return _result("\n".join(tg_lines), audit=[*audit, *tg_audit])

        # 权限门：公告与精华仅管理员（全员问资料/人数不设门）。
        wants_privileged = bool({"notice", "essence"} & intents)
        is_admin = _role_at_least(list(message.sender_roles), "admin")
        if wants_privileged and not is_admin:
            return _result(
                "公告和精华只有管理员能看哦，先不给你翻这份啦。",
                audit=[*audit, "denied_role"],
            )

        profile: dict[str, Any] | None = None
        members: list[dict[str, Any]] | None = None
        notices: list[dict[str, Any]] | None = None
        essence: list[dict[str, Any]] | None = None
        albums: list[Any] | None = None
        todos: list[Any] | None = None

        if "count" in intents or "profile" in intents or "age" in intents:
            ok, payload = _fetch(KIND_PROFILE, group_id, "get_group_info")
            profile = payload if ok and isinstance(payload, dict) else None
            if ok and not isinstance(payload, dict):
                audit.append("api_shape_profile")
        if "owner" in intents or "profile" in intents:
            ok, payload = _fetch(KIND_MEMBERS, group_id, "get_group_member_list")
            members = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_members")
        if "notice" in intents or ("profile" in intents and is_admin):
            # SnowLuma 1.14.19 的动作册里这条叫 `_get_group_notice`，V11 常见名
            # `get_group_notice` **没有注册**——照旧名直译过去每问必失败，再被下面
            # 的诚实分支兜成「接口这会儿没回应」（2026-09-25 对 ACTION_REGISTRY
            # 189 枚逐名核过）。先试本端真名，失败再退回 V11 常见名，别的协议端
            # 因此不受影响；``_fetch`` 只缓存成功载荷，所以这一发重试不落脏缓存。
            ok, payload = _fetch(KIND_NOTICE, group_id, "_get_group_notice")
            if not ok:
                ok, payload = _fetch(KIND_NOTICE, group_id, "get_group_notice")
            notices = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_notice")
        if "essence" in intents or ("profile" in intents and is_admin):
            ok, payload = _fetch(KIND_ESSENCE, group_id, "get_essence_msg_list")
            essence = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_essence")
        # ---- 群相册 / 群待办（第 4 项二批：动作在册，此前一直没接）----
        # 每个动作都试两种名形：SnowLuma 的动作册里既有裸名也有带下划线本名
        # （`_get_group_notice` 那次教训＝只试一个名字，每问必失败、再被诚实分支
        # 兜成「接口这会儿没回应」，用户看到的是一句假托词）。``_fetch`` 只缓存成功
        # 载荷，所以这一发重试不会落脏缓存。
        if "album" in intents:
            ok, payload = _fetch(KIND_ALBUM, group_id, "get_group_album_list")
            if not ok:
                ok, payload = _fetch(KIND_ALBUM, group_id, "_get_group_album_list")
            albums = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_album")
        if "todo" in intents:
            ok, payload = _fetch(KIND_TODO, group_id, "get_group_todo_list")
            if not ok:
                ok, payload = _fetch(KIND_TODO, group_id, "_get_group_todo_list")
            todos = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_todo")

        lines: list[str] = []
        # 群号取的是事件自带的本群号，不是接口回显：协议端一次没答上也照样能报，
        # 用户问「群号多少」不该因为一次 API 抖动就装不知道自己此刻在哪。
        lines.append(f"群号：{group_id}")

        # ---- 群名 / 人数 / 上限（profile/age/count 共用）----
        if profile is not None:
            name = str(profile.get("group_name") or "").strip()
            if name:
                lines.append(f"群名：{name}")
            memo = str(profile.get("group_memo") or "").strip()
            if memo:
                lines.append(f"群介绍：{memo}")
            count = profile.get("member_count")
            cap = profile.get("max_member_count")
            if isinstance(count, int) and isinstance(cap, int):
                lines.append(f"人数：{count}/{cap}")
            elif isinstance(count, int):
                lines.append(f"人数：{count}")
        elif {"profile", "count", "age"} & intents:
            lines.append(_UNAVAILABLE_LINE)

        # ---- 群主 / 管理员数（成员列表统计，名单绝不整列）----
        if "owner" in intents or "profile" in intents:
            if members is None:
                lines.append("群主：成员名单这会儿拿不到，先不猜是谁啦。")
            else:
                owners = [
                    item
                    for item in members
                    if isinstance(item, dict) and str(item.get("role") or "") == "owner"
                ]
                admins = sum(
                    1
                    for item in members
                    if isinstance(item, dict) and str(item.get("role") or "") == "admin"
                )
                if owners:
                    owner = owners[0]
                    display = str(owner.get("card") or owner.get("nickname") or "").strip()
                    uid = str(owner.get("user_id") or "").strip()
                    label = display or "群主"
                    lines.append(f"群主：{label}" + (f"（{uid}）" if uid else ""))
                else:
                    lines.append("群主：名单里没有 role=owner 的成员，先不硬指认啦。")
                if admins and "profile" in intents:
                    lines.append(f"管理员：{admins} 人")

        # ---- 问话人在本群的身份（群昵称/群头衔/身份，纯成员表字段，零新接口）----
        if "profile" in intents and members:
            sender_id = str(message.sender_id or "").strip()
            me = next(
                (
                    item
                    for item in members
                    if isinstance(item, dict) and str(item.get("user_id") or "").strip() == sender_id
                ),
                None,
            )
            if me is not None:
                identity = _ROLE_LABELS.get(str(me.get("role") or "").strip().lower(), "群成员")
                card = str(me.get("card") or "").strip()
                title = str(me.get("title") or "").strip()
                shown = card or str(me.get("nickname") or "").strip()
                if shown:
                    lines.append(f"你在这里：{shown}（{identity}）")
                else:
                    lines.append(f"你在这里的身份：{identity}")
                if title:
                    lines.append(f"群头衔：{title}")
                elif card:
                    # 头衔字段没回：说「没看到」而不是「没有」——协议回空与未回是两件事。
                    lines.append("群头衔：这次接口没回这个字段，不替你下结论。")

        # ---- 群文件（本地账本口径：只记协议端推过的 group_upload）----
        if "profile" in intents and group_file_store is not None:
            try:
                summary = str(group_file_store.summary(group_id, limit=5) or "").strip()
            except Exception:  # noqa: BLE001 - 账本读不动只丢这一段，不拖垮整份群资料。
                summary = ""
            if summary:
                lines.append(summary)
            else:
                lines.append("群文件：账本读不出内容，这一段先空着。")

        # ---- 建群时长（NapCat 扩展字段，非 V11 标准；不在就诚实说）----
        if "age" in intents and profile is not None:
            create_ts = profile.get("group_create_time")
            if isinstance(create_ts, (int, float)) and create_ts > 0:
                days = max(0, int((message.timestamp.timestamp() - create_ts) // 86400))
                lines.append(f"建群：约 {days} 天啦")
            else:
                lines.append("建群时间：协议里没给这个字段，答不了，不瞎猜哦。")

        # ---- 公告首段 / 精华条数（仅管理员可见；失败与为空分开说）----
        if wants_privileged or ("profile" in intents and is_admin):
            if notices is None:
                lines.append("公告：接口这会儿没回应，拿不到（可能需要我有管理员身份）。")
            else:
                snippet = _first_paragraph(_segment_text(notices[0])) if notices else ""
                lines.append("公告：" + (snippet or "群里现在还没有公告。"))
            if essence is None:
                lines.append("精华：接口这会儿没回应，拿不到（可能需要我有管理员身份）。")
            else:
                lines.append(f"精华：一共收了 {len(essence)} 条。")

        # ---- 群相册 / 群待办（失败与为空分开说；名单只到相册层，不落单张照片）----
        if "album" in intents:
            if albums is None:
                lines.append(
                    "群相册：协议端这次没答上，拿不到（不是本群没有相册，"
                    "是我没读到，别让我替它下结论）。"
                )
            elif not albums:
                lines.append("群相册：这个群目前没有相册。")
            else:
                lines.extend(_album_lines(albums))
        if "todo" in intents:
            if todos is None:
                lines.append(
                    "群待办：协议端这次没答上，拿不到（不等于没人设过待办）。"
                )
            elif not todos:
                lines.append("群待办：现在没有挂着的待办。")
            else:
                lines.extend(_todo_lines(todos))

        # ---- 参与者（按记忆算，不碰成员名单）----
        if wants_participants:
            participant_lines, participant_audit = _participants_block(
                message, is_group=True, scope_label="本群"
            )
            lines.extend(participant_lines)
            audit.extend(participant_audit)

        return _result("\n".join(lines), audit=audit)

    return capability
