"""表情贴纸回应（bot.reactions）：适配器中立的归一、缓冲、门控与编排。

职责（2026-09-14 批次，用户裁定需求：识别 + 理解 + 主动回应）：

1. 事件归一：QQ(SnowLuma) 的 ``group_msg_emoji_like`` 等贴纸回应 notice →
   :class:`ReactionEvent`；Telegram 侧留 :func:`normalize_telegram_reaction`
   接口（见下方平台能力实况）。
2. 会话级环形缓冲：每会话最近回应（默认 TTL 10 分钟、每会话上限 8 条），
   供人格上下文注入【表情回应】分区（空则整块不出现）。
3. 主动贴表情门控：开关 → 每消息去重 → 「本消息已骰」单次登记 →
   确定性概率 → 会话冷却 → 每小时滑窗限额，五层全过才贴
   （``set_msg_emoji_like``，失败静默）；同一消息跨触发只骰一次。

平台能力实况（2026-09-14 实查 venv 依赖版本，诚实记录）：

- QQ/NapCat 时期：群聊贴纸回应以 notice 事件 ``group_msg_emoji_like`` 上报
  （私聊等价形态按 OneBot notice 通用结构容错解析，生产实机待验证）；
  主动贴 = NapCat 时期扩展 API ``set_msg_emoji_like(message_id, emoji_id)``
  （现役同名 API 由 SnowLuma 提供，仅群消息可用；私聊派发前拒掉）。
- Telegram：nonebot-adapter-telegram **0.1.0b20** 的 model 层有
  ``MessageReactionUpdated`` 与 ``Update.message_reaction``，但
  ``event.py`` 的 ``event_map`` 没有 ``message_reaction`` 键——该 Update
  在事件转换时 KeyError 被丢弃，到不了 NoneBot handler。故 TG 识别侧
  只留本模块的归一接口（适配器升级支持后接一行 on_notice 即可），
  属诚实降级而非假实现。TG 主动贴 = Bot API 7.0+
  ``set_message_reaction``，仅当 bot 在该群为管理员时可用（私聊不可）；
  本仓库提供 wrapper 但**不接线**任何 TG 主动贴触发点。

本模块不导入 NoneBot，可离线单测。
"""
from __future__ import annotations

import hashlib
import logging
import time
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.control_plane.dispatcher import (
    OutboundSideEffectExecutor,
    ReactionService,
    build_interaction_dispatcher,
)
from plugins.bot_unified_runtime.domains.core.decision.outbound import (
    OutboundIntent,
    OutboundOperation,
    OutboundPart,
    OutboundTarget,
    derive_dedupe_key,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    is_group_session_key,
)

# --------------------------------------------------------------- 常量与映射

# QQ 系统小黄脸 QSid → 名称（NapCat/NTQQ 的表情 id 空间，非旧 PC 经典 CQ 表：
# 两套编号 0-15 段大多重合、16 起错位、41-43 完全不同、0/14 互换；QSid 无
# 17/40，缺号诚实留白，展示落「QQ表情#N」。事实源=NapCat face_config.json，
# 五源互证见 .superpowers/sdd/2026-09-13-six-domain-batch/faceid-verify-report.md）。
logger = logging.getLogger(__name__)

QSID_FACE_NAMES: dict[int, str] = {
    0: "惊讶", 1: "撇嘴", 2: "色", 3: "发呆", 4: "得意", 5: "流泪",
    6: "害羞", 7: "闭嘴", 8: "睡", 9: "大哭", 10: "尴尬", 11: "发怒",
    12: "调皮", 13: "呲牙", 14: "微笑", 15: "难过", 16: "酷", 18: "抓狂",
    19: "吐", 20: "偷笑", 21: "可爱", 22: "白眼", 23: "傲慢", 24: "饥饿",
    25: "困", 26: "惊恐", 27: "流汗", 28: "憨笑", 29: "悠闲", 30: "奋斗",
    31: "咒骂", 32: "疑问", 33: "嘘", 34: "晕", 35: "折磨", 36: "衰",
    37: "骷髅", 38: "敲打", 39: "再见", 41: "发抖", 42: "爱情", 43: "跳跳",
    76: "赞",  # 贴赞位（NapCat face_config 实名；意图「赞同」的落点）
}

# 扩展脸/超级表情名表（QSid 44+）：B 线 2026-09-16「理解意思」层。事实源=
# NapCat face_config.json sysface（faceid-verify-report 五源互证同源），
# 随包内嵌静态子集（287 条全量实名）；锚点 49=拥抱/76=赞/364=超级赞 已核。
# 取消贴/版本漂移风险与既有表同口径：展示不出名诚实落「QQ表情#N」。
QSID_EXTENDED_FACE_NAMES_RAW: dict[int, str] = {
    46: "猪头", 49: "拥抱", 53: "蛋糕", 55: "炸弹",
    56: "刀", 59: "便便", 60: "咖啡", 63: "玫瑰",
    64: "凋谢", 66: "爱心", 67: "心碎", 74: "太阳",
    75: "月亮", 76: "赞", 77: "踩", 78: "握手",
    79: "胜利", 85: "飞吻", 86: "怄火", 89: "西瓜",
    96: "冷汗", 97: "擦汗", 98: "抠鼻", 99: "鼓掌",
    100: "糗大了", 101: "坏笑", 102: "左哼哼", 103: "右哼哼",
    104: "哈欠", 105: "鄙视", 106: "委屈", 107: "快哭了",
    108: "阴险", 109: "左亲亲", 110: "吓", 111: "可怜",
    112: "菜刀", 114: "篮球", 116: "示爱", 118: "抱拳",
    119: "勾引", 120: "拳头", 121: "差劲", 122: "爱你",
    123: "NO", 124: "OK", 125: "转圈", 129: "挥手",
    137: "鞭炮", 144: "喝彩", 146: "爆筋", 147: "棒棒糖",
    148: "喝奶", 169: "手枪", 171: "茶", 172: "眨眼睛",
    173: "泪奔", 174: "无奈", 175: "卖萌", 176: "小纠结",
    177: "喷血", 178: "斜眼笑", 179: "doge", 180: "惊喜",
    181: "戳一戳", 182: "笑哭", 183: "我最美", 185: "羊驼",
    187: "幽灵", 193: "大笑", 194: "不开心", 198: "呃",
    200: "求求", 201: "点赞", 202: "无聊", 203: "托脸",
    204: "吃", 206: "害怕", 210: "飙泪", 211: "我不看",
    212: "托腮", 214: "啵啵", 215: "糊脸", 216: "拍头",
    217: "扯一扯", 218: "舔一舔", 219: "蹭一蹭", 221: "顶呱呱",
    222: "抱抱", 223: "暴击", 224: "开枪", 225: "撩一撩",
    226: "拍桌", 227: "拍手", 229: "干杯", 230: "嘲讽",
    231: "哼", 232: "佛系", 233: "掐一掐", 235: "颤抖",
    237: "偷看", 238: "扇脸", 239: "原谅", 240: "喷脸",
    241: "生日快乐", 243: "甩头", 244: "扔狗", 262: "脑阔疼",
    263: "沧桑", 264: "捂脸", 265: "辣眼睛", 266: "哦哟",
    267: "头秃", 268: "问号脸", 269: "暗中观察", 270: "emm",
    271: "吃瓜", 272: "呵呵哒", 273: "我酸了", 277: "汪汪",
    278: "汗", 281: "无眼笑", 282: "敬礼", 283: "狂笑",
    284: "面无表情", 285: "摸鱼", 286: "魔鬼笑", 287: "哦",
    288: "请", 289: "睁眼", 290: "敲开心", 292: "让我康康",
    293: "摸锦鲤", 294: "期待", 295: "拿到红包", 297: "拜谢",
    298: "元宝", 299: "牛啊", 300: "胖三斤", 301: "好闪",
    302: "左拜年", 303: "右拜年", 305: "右亲亲", 306: "牛气冲天",
    307: "喵喵", 311: "打call", 312: "变形", 314: "仔细分析",
    317: "菜汪", 318: "崇拜", 319: "比心", 320: "庆祝",
    322: "拒绝", 323: "嫌弃", 324: "吃糖", 325: "惊吓",
    326: "生气", 332: "举牌牌", 333: "烟花", 334: "虎虎生威",
    336: "豹富", 337: "花朵脸", 338: "我想开了", 339: "舔屏",
    341: "打招呼", 342: "酸Q", 343: "我方了", 344: "大怨种",
    345: "红包多多", 346: "你真棒棒", 347: "大展宏兔", 348: "福萝卜",
    349: "坚强", 350: "贴贴", 351: "敲敲", 352: "咦",
    353: "拜托", 354: "尊嘟假嘟", 355: "耶", 356: "666",
    357: "裂开", 358: "骰子", 359: "包剪锤", 360: "亲亲",
    361: "狗狗笑哭", 362: "好兄弟", 363: "狗狗可怜", 364: "超级赞",
    365: "狗狗生气", 366: "芒狗", 367: "狗狗疑问", 368: "奥特笑哭",
    369: "彩虹", 370: "祝贺", 371: "冒泡", 372: "气呼呼",
    373: "忙", 374: "波波流泪", 375: "超级鼓掌", 376: "跺脚",
    377: "嗨", 378: "企鹅笑哭", 379: "企鹅流泪", 380: "真棒",
    381: "路过", 382: "emo", 383: "企鹅爱心", 384: "晚安",
    385: "太气了", 386: "呜呜呜", 387: "太好笑", 388: "太头疼",
    389: "太赞了", 390: "太头秃", 391: "太沧桑", 392: "龙年快乐",
    393: "新年中龙", 394: "新年大龙", 395: "略略略", 396: "狼狗",
    397: "抛媚眼", 398: "超级ok", 399: "tui", 400: "快乐",
    401: "超级转圈", 402: "别说话", 403: "出去玩", 404: "闪亮登场",
    405: "好运来", 406: "姐是女王", 407: "我听听", 408: "臭美",
    409: "送你花花", 410: "么么哒", 411: "一起嗨", 412: "开心",
    413: "摇起来", 415: "划龙舟", 416: "中龙舟", 417: "大龙舟",
    419: "火车", 420: "中火车", 421: "大火车", 422: "粽于等到你",
    423: "复兴号", 424: "续标识", 425: "求放过", 426: "玩火",
    427: "偷感", 428: "收到", 429: "蛇年快乐", 430: "蛇身",
    431: "蛇尾", 432: "灵蛇献瑞", 450: "撇嘴", 451: "色",
    452: "微笑", 453: "发呆", 454: "得意", 455: "害羞",
    456: "闭嘴", 457: "睡", 458: "我吗", 459: "优雅",
    460: "硬撑", 461: "宕机", 462: "无语", 463: "新年快乐",
    464: "马上到", 465: "拆红包", 466: "羞羞哒", 467: "摇花手",
    468: "失眠", 469: "坚毅", 470: "马到成功", 472: "心动",
    474: "给你一拳", 475: "干饭", 476: "不是吧", 477: "你懂的",
    478: "对的对的", 479: "不对不对", 480: "散味儿", 481: "学习",
    482: "热化了", 483: "略", 484: "比爱心",
}
QSID_FACE_NAMES.update(QSID_EXTENDED_FACE_NAMES_RAW)

# QQ 新版贴表情系统的 emoji_id 通常是 unicode 码点十进制串（如 128077=👍）。
# 判定边界：<=484 视为 QSid 系统脸 id（face_config 的 QSid 上限=484；NapCat 时期
# emojiType=len>3?'2':'1'，4 位以上十进制才是 unicode 码点形态）。
_QSID_FACE_ID_MAX = 484


def emoji_display(emoji_id: str) -> str:
    """把平台 emoji_id 转成诚实可读的展示文本；映射不出保留原 id。"""
    text = str(emoji_id or "").strip()
    if not text:
        return ""
    try:
        code = int(text)
    except ValueError:
        return text  # 非数字（TG emoji 原字符/自定义 id 等）按原文展示。
    if 0 <= code <= _QSID_FACE_ID_MAX:
        name = QSID_FACE_NAMES.get(code)
        return f"「{name}」" if name else f"QQ表情#{text}"
    try:
        char = chr(code)
    except (ValueError, OverflowError):
        return f"表情#{text}"
    # 只认符号类字符，避免把大整数误渲成汉字/假名。
    if unicodedata.category(char).startswith("S"):
        return char
    return f"表情#{text}"


# 主动贴表情意图 → QSid 表情 id（守岸人语气适配：温和、不吵闹、无攻击性）。
# id 空间=NapCat/NTQQ QSid（非旧 PC 经典 CQ 表）：表 A 五处错位已按
# faceid-verify-report 改值（41=发抖/19=吐/14=微笑/29=悠闲/27=流汗 全避开）。
REACTION_INTENT_EMOJIS: dict[str, int] = {
    "赞同": 76,  # 赞（旧 41 在 QSid=发抖冷脸；QSid 实名 76=赞）
    "开心": 13,  # 呲牙
    "有趣": 20,  # 偷笑（旧 19 在 QSid=吐，嫌弃脸）
    "害羞": 6,   # 害羞
    "惊讶": 0,   # 惊讶（QSid 0=惊讶，与经典表 0=微笑/14=惊讶 互换）
    "安慰": 5,   # 流泪（共情同悲，审计 I1：可爱(20) 是卖萌不是共情；
    #            与「感动」同 id，语义随上下文；小黄脸段无可靠的摸头/亲亲）
    "感动": 5,   # 流泪
    "加油": 30,  # 奋斗（旧 29 在 QSid=悠闲躺平脸，读作嘲讽）
    "憨笑": 28,  # 憨笑（旧 27 在 QSid=流汗尴尬脸）
}
# 兜底池：意图映射不中时按确定性哈希从中挑一个。守岸人语域取中性温和三脸
# 赞76/惊讶0/害羞6（tone-audit M2「中性温和」口径的 QSid 平移）；偷笑/憨笑
# 等活泼脸保留给有内容依据的意图（人格规范：不使用活泼或夸张的表情）。
_REACTION_FALLBACK_INTENTS = ("赞同", "惊讶", "害羞")

# 情绪信号关键词（触发 B：用户消息命中即视为态度时刻；简繁都收）。
_SIGNAL_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("感动", ("谢谢", "多谢", "感谢", "辛苦", "帮大忙", "救星", "感謝", "多謝", "辛苦了", "謝謝")),
    ("赞同", ("厉害", "太棒", "好棒", "真棒", "厉害了", "優秀", "厲害", "太棒了", "說得對", "说得对")),
    ("害羞", ("可爱", "喜欢你", "想你", "最棒", "可愛", "喜歡你")),
    ("惊讶", ("居然", "不会吧", "真的假的", "震驚", "震惊")),
    ("加油", ("加油", "冲鸭", "沖鴨")),
    # I3：补简体「伤心」与繁体裸「難過」（原只有 傷心/好難過，最需共情的
    # 消息落不进安慰路径，恰好滑进 after_reply 笑脸兜底——缺口开在最险处）。
    ("安慰", ("难过", "难受", "伤心", "傷心", "難過")),
)


def infer_signal_intent(text: str) -> str | None:
    """用户消息命中情绪信号 → 返回意图；未命中返回 None（不贴）。"""
    stripped = str(text or "").strip()
    if not stripped:
        return None
    for intent, words in _SIGNAL_INTENT_KEYWORDS:
        for word in words:
            if word and word in stripped:
                return intent
    return None


# 悲伤/低落词族（审计 C1）：after_reply 兜底触发前先看消息情绪，命中即
# 整条不贴——安慰在言语与陪伴里，绝不对悲伤消息贴呲牙/偷笑/憨笑等笑脸。
# 简繁都收；误伤（如「积累经验」含「累」、「我先走了」的告别义）的代价
# 只是少贴一张随机脸，可忽略；漏放过的代价是给悲伤贴笑脸（红线级）。
_SAD_TONE_WORDS: tuple[str, ...] = (
    "累", "难过", "難過", "伤心", "傷心", "难受", "難受",
    "去世", "走了", "哭", "emo", "崩溃", "崩潰",
    "撑不", "撐不", "抑郁", "抑鬱", "低落",
)


def is_sad_message(text: str) -> bool:
    """消息是否命中悲伤/低落词族（C1 情绪门；lower() 兼容 EMO/Emo 大小写）。"""
    stripped = str(text or "").strip().lower()
    if not stripped:
        return False
    return any(word in stripped for word in _SAD_TONE_WORDS)


# ------------------------------------------------- 双层表情·第二层（表情包）

# 情绪意图 → 表情库 VLM 标签检索词（emotion_tags/scene_tags 命中即候选）。
# 与 REACTION_INTENT_EMOJIS 的意图名同源；词面按表情库打标口径取常用词。
_REACTION_MEME_INTENT_TERMS: dict[str, tuple[str, ...]] = {
    "赞同": ("赞", "认可", "厉害"),
    "开心": ("开心", "高兴", "快乐"),
    "有趣": ("搞笑", "有趣", "玩梗"),
    "害羞": ("害羞", "脸红", "可爱"),
    "惊讶": ("惊讶", "震惊", "吃惊"),
    "加油": ("加油", "奋斗", "打气"),
    "感动": ("感动", "暖心", "泪目"),
    "安慰": ("安慰", "抱抱", "暖心", "治愈"),
}


def reaction_meme_search_terms(intent: str) -> tuple[str, ...]:
    """情绪意图 → 表情库检索词序列（意图映射不中返回空）。"""
    return _REACTION_MEME_INTENT_TERMS.get(str(intent or "").strip(), ())


def reaction_meme_intent_vocabulary() -> tuple[str, ...]:
    """意图词表展平视图（**只读派生**）：选图打分件借它当主题词表的一部分。

    存在理由：``meme_selection.default_vocabulary`` 需要「情绪词」这一族，而那族
    词的本体是这张意图表。给它一个函数而不是让它复制一份常量元组——
    否则就是「哪算情绪词」出现第二真身（AGENTS 禁第二真身）。
    """
    return tuple(dict.fromkeys(term for terms in _REACTION_MEME_INTENT_TERMS.values() for term in terms))


def pick_reaction_meme(
    store: Any, *, intent: str, nsfw_max: float = 0.2, scope: str | None = None
) -> str | None:
    """按意图检索词序加权抽一张表情包；全部落空退无关键词兜底；库空 None。

    检索/选取任何异常逐词吞掉（fail-open）——表情包层绝不影响聊天链路。

    反重复**不需要**本函数配合：它落在 ``store.weighted_pick`` 里（三条腿的共同
    咽喉）。``scope`` 只是把去重面从「全局发过即不再发」细化到「该会话/群 + 全局」，
    传不传都仍在防重复；旧桩不认识这个形参时自动退回旧调用（见 ``_pick_kwargs``）。
    """
    if store is None:
        return None

    def _pick(**extra: Any) -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {"nsfw_max": nsfw_max, **extra}
        if scope is None:
            return store.weighted_pick(**kwargs)
        try:
            return store.weighted_pick(scope=scope, **kwargs)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return store.weighted_pick(**kwargs)

    for term in reaction_meme_search_terms(intent):
        if not term:
            continue
        try:
            picked = _pick(keyword=term)
        except Exception as exc:  # noqa: BLE001 - 单词检索失败记日志继续下一词。
            logger.debug("reaction meme keyword pick failed term=%s error=%s", term, type(exc).__name__)
            continue
        if picked and str(picked.get("path") or "").strip():
            return str(picked["path"])
    try:
        picked = _pick(keyword="")
    except Exception:  # noqa: BLE001 - 兜底失败诚实放弃。
        return None
    if picked and str(picked.get("path") or "").strip():
        return str(picked["path"])
    return None


def _is_group_session(session_key: str) -> bool:
    """会话键是否群聊形态——判据单一事实源在 ``domains/core/session_keys.py``。

    FIX5 收编：本函数与 ``chat_reply/capabilities/memory.py`` 曾各持一份**判据相反**
    的同名本地谓词（这里认 ``group_`` 、那里认 ``group:``），键形与判据错配即静默
    False。现两处统一消费中央件；对真实输入（摄取层 ``get_session_id()`` 的
    ``group_<gid>_<uid>`` / 私聊裸 uid）行为**逐字节等价**。
    """
    return is_group_session_key(session_key)


def select_reaction_emoji(intent: str, seed: str) -> int:
    """意图 → QQ 表情 id；映射不中按确定性哈希从兜底池挑（同 seed 同结果）。"""
    emoji_id = REACTION_INTENT_EMOJIS.get(str(intent or "").strip())
    if emoji_id is not None:
        return emoji_id
    digest = hashlib.sha256(f"reaction:{seed}".encode()).hexdigest()[:8]
    index = int(digest, 16) % len(_REACTION_FALLBACK_INTENTS)
    return REACTION_INTENT_EMOJIS[_REACTION_FALLBACK_INTENTS[index]]


# --------------------------------------------------------------- 事件归一

# NapCat 时期已知形态 + 私聊等价形态 + 容错别名。
_EMOJI_LIKE_NOTICE_TYPES = frozenset(
    {"group_msg_emoji_like", "private_msg_emoji_like", "msg_emoji_like"}
)


@dataclass(frozen=True)
class ReactionEvent:
    """归一后的贴纸回应事件（适配器中立，各适配器字段同名即可复用）。"""

    platform: str  # "qq" | "telegram"
    session_key: str  # 与聊天链路 session_id 同构：group_<gid>_<uid> / <uid>
    user_id: str
    message_id: str  # 被贴的那条消息
    emoji_id: str
    emoji_text: str  # 映射后的展示文本；映射不出=原 id
    count: int = 1
    ts: float = 0.0  # 信息性时间戳（epoch 秒）；TTL 由缓冲的 monotonic 时钟管


def session_key_from_ids(group_id: Any, user_id: Any) -> str:
    """镜像 OneBot V11 ``get_session_id``：群=f"group_<gid>_<uid>"，私聊=<uid>。

    FIX5 起构造逻辑单一事实源在 ``domains/core/session_keys.build_session_key``
    （本函数保留原导出名与逐字返回值，读侧 ``shared_group._group_prefix`` 与
    ``tests/test_shared_group_key_alignment.py`` 的跨件一致性锚不受影响）。
    """
    return build_session_key(group_id, user_id)


def _likes_entries(event: Any) -> list[dict[str, Any]]:
    """NapCat 时期形态优先（``likes`` 列表）；退化到平铺 emoji_id/count 字段。"""
    likes = getattr(event, "likes", None)
    if isinstance(likes, list) and likes:
        return [entry for entry in likes if isinstance(entry, dict)] or []
    emoji_id = str(getattr(event, "emoji_id", "") or "").strip()
    if emoji_id:
        count_raw = getattr(event, "count", 1)
        try:
            count = max(1, int(count_raw))
        except (TypeError, ValueError):
            count = 1
        return [{"emoji_id": emoji_id, "count": count}]
    return []


def normalize_onebot_emoji_like(
    event: Any,
    *,
    bot_id: str = "",
    now: float | None = None,
) -> list[ReactionEvent]:
    """OneBot/SnowLuma 贴纸回应 notice → ReactionEvent 列表（容错解析）。

    已知 NapCat 时期形态：``notice_type=group_msg_emoji_like``，字段
    ``group_id/user_id/message_id/likes:[{emoji_id, count}]``；私聊等价
    形态无实机样本，按同构字段容错（``private_msg_emoji_like`` /
    ``msg_emoji_like`` / 平铺 emoji_id）。字段缺失的条目跳过；非本类
    事件返回空列表。**生产实机待验证**。
    """
    notice_type = str(getattr(event, "notice_type", "") or "").strip()
    if notice_type not in _EMOJI_LIKE_NOTICE_TYPES:
        return []
    # is_add 处理（faceid 报告 §五 unknown 清账，B 线 2026-09-16）：NapCat 时期
    # 对「取消贴表情」也上报本事件；is_add=False 是撤销动作，不记正向回应。
    # 字段缺失（None/无属性）按旧语义照记——诚实容错，不赌协议端实现。
    is_add = getattr(event, "is_add", None)
    if is_add is False:
        return []
    user_id = str(getattr(event, "user_id", "") or "").strip()
    message_id = str(getattr(event, "message_id", "") or "").strip()
    group_id = getattr(event, "group_id", None)
    session_key = session_key_from_ids(group_id, user_id)
    ts = time.time() if now is None else float(now)
    events: list[ReactionEvent] = []
    for entry in _likes_entries(event):
        emoji_id = str(entry.get("emoji_id", "") or "").strip()
        if not emoji_id:
            continue
        try:
            count = max(1, int(entry.get("count", 1)))
        except (TypeError, ValueError):
            count = 1
        entry_user = str(entry.get("user_id", "") or "").strip() or user_id
        events.append(
            ReactionEvent(
                platform="qq",
                session_key=session_key,
                user_id=entry_user,
                message_id=message_id,
                emoji_id=emoji_id,
                emoji_text=emoji_display(emoji_id),
                count=count,
                ts=ts,
            )
        )
    _ = bot_id  # 预留：识别"贴的是不是 bot 的消息"需对照 bot 自身 id。
    return events


def normalize_telegram_reaction(
    *,
    chat_id: Any,
    message_id: Any,
    new_reaction: list[dict[str, Any]] | None,
    old_reaction: list[dict[str, Any]] | None = None,
    user_id: Any = "",
    ts: float = 0.0,
) -> ReactionEvent | None:
    """Telegram ``MessageReactionUpdated`` → ReactionEvent（**当前不可达**）。

    适配器 0.1.0b20 不投递 message_reaction Update（见模块 docstring）。
    本接口给未来版本接线用：只对"新增"的贴纸出事件（纯移除→None）；
    ``ReactionTypeEmoji`` 取 emoji 原字符，``custom_emoji`` 存原 id 诚实
    展示。离线可测，字段以 Bot API 官方模型为准。
    """
    new_list = [
        entry for entry in (new_reaction or []) if isinstance(entry, dict)
    ]
    if not new_list:
        return None
    old_keys = {
        str(entry.get("emoji") or entry.get("custom_emoji_id") or "")
        for entry in (old_reaction or [])
        if isinstance(entry, dict)
    }
    added: dict[str, Any] | None = None
    for entry in new_list:
        key = str(entry.get("emoji") or entry.get("custom_emoji_id") or "")
        if key and key not in old_keys:
            added = entry
            break
    if added is None:
        return None
    if str(added.get("type", "")) == "custom_emoji" or added.get("custom_emoji_id"):
        emoji_id = str(added.get("custom_emoji_id", "") or "")
        emoji_text = f"自定义表情#{emoji_id}" if emoji_id else ""
    else:
        emoji_id = str(added.get("emoji", "") or "")
        emoji_text = emoji_id
    if not emoji_id:
        return None
    return ReactionEvent(
        platform="telegram",
        session_key=str(chat_id or "").strip() or "unknown",
        user_id=str(user_id or "").strip(),
        message_id=str(message_id or "").strip(),
        emoji_id=emoji_id,
        emoji_text=emoji_text,
        count=1,
        ts=float(ts) if ts else time.time(),
    )


# --------------------------------------------------------------- 环形缓冲

_REACTION_BUFFER_TTL_SECONDS = 600.0  # 10 分钟
_REACTION_BUFFER_MAX_PER_CHAT = 8
_REACTION_BUFFER_MAX_CHATS = 256
_BOT_MESSAGE_TTL_SECONDS = 600.0
_BOT_MESSAGE_MAX = 32


class ReactionBuffer:
    """每会话最近贴纸回应（进程内，重启即清；LRU 封顶防慢泄漏）。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = _REACTION_BUFFER_TTL_SECONDS,
        max_per_chat: int = _REACTION_BUFFER_MAX_PER_CHAT,
        max_chats: int = _REACTION_BUFFER_MAX_CHATS,
    ) -> None:
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self.max_per_chat = max(1, int(max_per_chat))
        self.max_chats = max(1, int(max_chats))
        self._events: OrderedDict[str, deque[tuple[float, ReactionEvent]]] = (
            OrderedDict()
        )
        self._bot_messages: OrderedDict[str, deque[tuple[float, str]]] = (
            OrderedDict()
        )

    def record(self, event: ReactionEvent) -> None:
        now = self.clock()
        bucket = self._events.get(event.session_key)
        if bucket is None:
            if len(self._events) >= self.max_chats:
                self._events.popitem(last=False)  # 淘汰最久未活跃的会话。
            bucket = deque(maxlen=self.max_per_chat)
            self._events[event.session_key] = bucket
        else:
            self._events.move_to_end(event.session_key)
        bucket.append((now, event))

    def register_bot_message(self, session_key: str, message_id: Any) -> None:
        """登记 bot 自己发出的消息 id（供 describe 说"对我的消息"）。"""
        mid = str(message_id or "").strip()
        if not mid:
            return
        now = self.clock()
        bucket = self._bot_messages.get(session_key)
        if bucket is None:
            if len(self._bot_messages) >= self.max_chats:
                self._bot_messages.popitem(last=False)
            bucket = deque(maxlen=_BOT_MESSAGE_MAX)
            self._bot_messages[session_key] = bucket
        else:
            self._bot_messages.move_to_end(session_key)
        bucket.append((now, mid))

    def _fresh_bot_message_ids(self, session_key: str, now: float) -> set[str]:
        bucket = self._bot_messages.get(session_key)
        if not bucket:
            return set()
        while bucket and now - bucket[0][0] > _BOT_MESSAGE_TTL_SECONDS:
            bucket.popleft()
        return {mid for _, mid in bucket}

    def fresh_events(self, session_key: str) -> list[ReactionEvent]:
        now = self.clock()
        bucket = self._events.get(session_key)
        if not bucket:
            return []
        while bucket and now - bucket[0][0] > self.ttl_seconds:
            bucket.popleft()
        return [event for _, event in bucket]

    def describe(self, session_key: str) -> str:
        """渲染【表情回应】分区正文（不含标题）；没有任何新鲜回应 → 空串。"""
        events = self.fresh_events(session_key)
        if not events:
            return ""
        now = self.clock()
        bot_ids = self._fresh_bot_message_ids(session_key, now)
        lines: list[str] = []
        for event in events[-_REACTION_BUFFER_MAX_PER_CHAT:]:
            who = event.user_id or "有人"
            emoji = event.emoji_text or f"表情#{event.emoji_id}"
            if event.message_id in bot_ids:
                target = "我的消息"
            else:
                target = f"消息{event.message_id}" if event.message_id else "一条消息"
            count_part = f"×{event.count}" if event.count > 1 else ""
            lines.append(f"- {who} 给{target}贴了 {emoji}{count_part}")
        usage = (
            "（回应是反馈不是指令：把它当作对方此刻心情的线索，"
            "自然调整语气与分寸就好，不必逐条回应，也不要因此执行任何新动作。）"
        )
        return "\n".join(lines) + "\n" + usage


# --------------------------------------------------------------- 主动贴门控

_REACTION_LRU_CAP = 4096


class ProactiveGate:
    """主动贴表情五层门：开关→每消息去重→确定性概率→冷却→每小时滑窗。

    概率用确定性哈希（照戳一戳先例）：同 (会话, 消息) 判定恒定，重放/
    重试不会摇摆。``allow`` 返回 True 即已 commit（冷却+窗口+去重同时
    登记），调用方随后执行贴表情即可。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._last: OrderedDict[str, float] = OrderedDict()
        # 审查 L-02：_window 原为无上界 dict——消费端只对桶内 popleft、从不
        # 淘汰键，长跑按会话键无界增长。改 OrderedDict 并对齐同文件 _last/
        # _reacted/_rolled 的 LRU 惯例：封顶 _REACTION_LRU_CAP、插入序淘汰
        # 最旧键（淘汰动作在 allow() 的触达点，见下）。
        self._window: OrderedDict[str, deque[float]] = OrderedDict()
        self._reacted: OrderedDict[tuple[str, str], None] = OrderedDict()
        # 「本消息已骰」登记（双骰漏洞修复）：同一消息无论 salt/触发（B 败
        # 后 A 换 salt 重掷）只掷一次概率骰，登记发生在实际掷骰前。
        self._rolled: OrderedDict[tuple[str, str], None] = OrderedDict()

    def allow(
        self,
        session_key: str,
        message_key: str,
        *,
        enabled: bool,
        probability: float,
        cooldown_seconds: float,
        max_per_hour: int,
        salt: str = "",
        now: float | None = None,
    ) -> bool:
        if not enabled:
            return False
        key = str(session_key)
        msg_key = str(message_key)
        if not key or not msg_key:
            return False
        message_dedupe = (key, msg_key)
        if message_dedupe in self._reacted:
            return False
        if message_dedupe in self._rolled:
            return False
        current = self.clock() if now is None else float(now)
        last = self._last.get(key, -1e9)
        if current - last < max(0.0, float(cooldown_seconds)):
            return False
        # 审查 L-02：触达即 move_to_end + 超界淘汰最旧键（与 _last/_reacted/
        # _rolled 同款三连）；被淘汰的会话键再进来按全新空桶处理，不复活旧
        # 滑窗。键数未达上界时五层门判定与旧实现逐字节一致——纯内存治理。
        window = self._window.setdefault(key, deque())
        self._window.move_to_end(key)
        while len(self._window) > _REACTION_LRU_CAP:
            self._window.popitem(last=False)
        while window and current - window[0] > 3600.0:
            window.popleft()
        if len(window) >= max(1, int(max_per_hour)):
            return False
        # 登记已骰（先于掷骰）：无论中不中，这条消息不再二次掷骰——
        # 否则触发 B 概率败后触发 A 换 salt 仍可独立命中。
        self._rolled[message_dedupe] = None
        self._rolled.move_to_end(message_dedupe)
        while len(self._rolled) > _REACTION_LRU_CAP:
            self._rolled.popitem(last=False)
        digest = int(
            hashlib.sha256(
                f"react:{salt}:{key}:{msg_key}".encode()
            ).hexdigest()[:8],
            16,
        ) / 0xFFFFFFFF
        if digest > max(0.0, min(1.0, float(probability))):
            return False
        # 全门通过，commit 所有状态。
        self._reacted[message_dedupe] = None
        self._reacted.move_to_end(message_dedupe)
        while len(self._reacted) > _REACTION_LRU_CAP:
            self._reacted.popitem(last=False)
        self._last[key] = current
        self._last.move_to_end(key)
        while len(self._last) > _REACTION_LRU_CAP:
            self._last.popitem(last=False)
        window.append(current)
        return True

    def has_rolled(self, session_key: str, message_key: str) -> bool:
        """本消息是否已掷过概率骰（跨 salt/跨触发共享：同消息只骰一次）。"""
        return (str(session_key), str(message_key)) in self._rolled


# --------------------------------------------------------------- 动作包装

# V21-DISPATCH-001（风险 5 收口）：贴表情等平台副作用改走统一出站面——
# OutboundIntent（严格 DTO）→ 准入复验 → 许可租约线性化 → Transport 固定
# 映射（绝不拼 API 名）→ bot.call_api 通道本体（与 SendQueue worker 同通道，
# 非第二出站通道）。参数 coercion 与失败静默语义和旧直连逐字节一致；
# 永久幂等仍归 ProactiveGate（每消息去重）所有，执行器只做在途线性化。
_REACTION_OUTBOUND_EXECUTOR = OutboundSideEffectExecutor()


def _build_qq_reaction_intent(payload: dict[str, Any]) -> OutboundIntent:
    """QQ 贴表情载荷 → OutboundIntent（message_id int / emoji_id str 与旧直连一致）。"""
    message_id = str(payload.get("message_id") or "").strip()
    emoji_id = int(payload.get("emoji_id") or 0)
    dedupe_key = derive_dedupe_key(
        "qq", f"reaction.{message_id}.{emoji_id}", "direct",
    )
    return OutboundIntent(
        operation=OutboundOperation.REACTION,
        target=OutboundTarget(
            platform="qq",
            session_type="group",
            target_id=message_id,
            bot_id=str(payload.get("bot_id") or ""),
            adapter="onebot",
        ),
        parts=[
            OutboundPart(
                part_id=f"reaction:{dedupe_key}",
                kind="sticker",
                content_ref={
                    "api_params": {
                        "message_id": int(message_id),
                        "emoji_id": str(emoji_id),
                    }
                },
            )
        ],
        feature_id="bot.plugin.chat.reactions.post",
        policy_revision="legacy-reactions-v2",
        dedupe_key=dedupe_key,
        trace_id=f"reaction-{time.time_ns()}",
    )


def _build_telegram_reaction_intent(payload: dict[str, Any]) -> OutboundIntent:
    """TG reaction 载荷 → OutboundIntent（Bot API 7.0+ 形态与旧直连一致）。"""
    chat_id = payload.get("chat_id")
    message_id = int(str(payload.get("message_id")))
    emoji = str(payload.get("emoji") or "👍")
    dedupe_key = derive_dedupe_key(
        "telegram", f"reaction.{chat_id}.{message_id}.{emoji}", "direct",
    )
    return OutboundIntent(
        operation=OutboundOperation.REACTION,
        target=OutboundTarget(
            platform="telegram",
            session_type="group",
            target_id=str(chat_id),
            bot_id=str(payload.get("bot_id") or ""),
            adapter="telegram",
        ),
        parts=[
            OutboundPart(
                part_id=f"reaction:{dedupe_key}",
                kind="sticker",
                content_ref={
                    "api_params": {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reaction": [{"type": "emoji", "emoji": emoji}],
                        "is_big": bool(payload.get("is_big", False)),
                    }
                },
            )
        ],
        feature_id="bot.plugin.chat.reactions.post",
        policy_revision="legacy-reactions-v2",
        dedupe_key=dedupe_key,
        trace_id=f"reaction-{time.time_ns()}",
    )


def _build_reaction_intent(payload: dict[str, Any]) -> OutboundIntent:
    if str(payload.get("platform")) == "telegram":
        return _build_telegram_reaction_intent(payload)
    return _build_qq_reaction_intent(payload)


_REACTION_OUTBOUND_SERVICE = ReactionService(
    dispatch=build_interaction_dispatcher(
        _REACTION_OUTBOUND_EXECUTOR,
        route_intent=_build_reaction_intent,
    )
)


async def react_to_message(bot: Any, *, message_id: Any, emoji_id: int) -> bool:
    """SnowLuma 扩展 API：给群消息贴表情（统一出站面）。

    群消息专用——私聊会被协议端拒（见 ``maybe_react_on_message`` 的硬限制），
    调用方须在派发前挡住。失败记日志（诊断「总贴同一张脸」）。
    """
    mid = str(message_id or "").strip()
    if not mid:
        return False
    try:
        result = await _REACTION_OUTBOUND_SERVICE.handle(
            {
                "platform": "qq",
                "bot": bot,
                "bot_id": str(getattr(bot, "self_id", "") or ""),
                "message_id": mid,
                "emoji_id": int(emoji_id),
            }
        )
    except Exception as exc:  # noqa: BLE001 - 贴表情失败绝不影响主链路，但要留痕。
        logger.info(
            "reaction post failed: mid=%s emoji=%s error=%s",
            mid, emoji_id, type(exc).__name__,
        )
        return False
    if result.status == "delivered":
        logger.info("reaction posted: mid=%s emoji=%s", mid, emoji_id)
        return True
    logger.info(
        "reaction post failed: mid=%s emoji=%s error=%s",
        mid, emoji_id, result.status,
    )
    return False


async def react_telegram_message(
    bot: Any,
    *,
    chat_id: Any,
    message_id: Any,
    emoji: str = "👍",
    is_big: bool = False,
) -> bool:
    """Bot API 7.0+ ``set_message_reaction``（**本仓库未接线触发点**）。

    平台限制（诚实标注）：仅当 bot 在该群聊为管理员时可用；私聊 bot
    不能贴回应。保留给未来识别链路打通后的可选接线。出站经统一出站面
    （V21-DISPATCH-001：Transport 固定映射解析方法名，非直连字面量）。
    """
    try:
        result = await _REACTION_OUTBOUND_SERVICE.handle(
            {
                "platform": "telegram",
                "bot": bot,
                "bot_id": str(getattr(bot, "self_id", "") or ""),
                "chat_id": chat_id,
                "message_id": str(message_id),
                "emoji": emoji,
                "is_big": bool(is_big),
            }
        )
    except Exception:  # noqa: BLE001 - 平台拒绝/不支持时静默。
        return False
    return result.status == "delivered"


def reaction_knobs(config: Any) -> dict[str, Any]:
    """读 bot_reactions_* 配置（getattr 缺省，兼容热覆盖合并后的视图）。"""
    return {
        "enabled": bool(getattr(config, "bot_reactions_enabled", True)),
        "probability": float(getattr(config, "bot_reactions_probability", 0.2)),
        "cooldown_seconds": float(
            getattr(config, "bot_reactions_cooldown_seconds", 30)
        ),
        "max_per_hour": int(getattr(config, "bot_reactions_max_per_hour", 20)),
    }


async def maybe_react_on_message(
    bot: Any,
    *,
    session_key: str,
    user_message_id: Any,
    text: str,
    config: Any,
    trigger: str,
    gate: ProactiveGate | None = None,
    now: float | None = None,
    bot_related: bool | None = None,
) -> bool:
    """主动贴表情编排：门控全过 → 给用户这条消息贴一个表情。

    **主动贴表情只支持群消息**（实测报错 36 次），私聊一律不派发。QQ 侧本就不存在
    私聊表情回应通道（OIDB ``0x9082`` 只有群消息形态），**不是换协议端造成的退化**；
    SnowLuma 对非群消息直接抛 ``emoji reactions are not supported on private
    messages``。修法=不发：私聊在进入五层门**之前**按 ``_is_group_session``
    （委托 ``domains/core/session_keys.py``，真实摄取键为 ``group_<gid>_<uid>``）
    拒掉，绝不出 ``set_msg_emoji_like``，也就不占每消息
    去重登记、不刷失败日志。锁死用例：
    ``tests/test_reactions.py::test_private_session_never_calls_set_msg_emoji_like``。

    trigger：
    - ``emotion_signal``：文本须命中情绪信号关键词（命中决定意图）；
      群聊内仅在与 bot 相关的对话贴（审计 I2）——``bot_related=True`` 由调用方按
      mentions_bot/回复 bot 消息/含 bot 昵称口径判定后传入，未判定（``None``）
      一律不介入第三方对话。
    - ``after_reply``：bot 刚回复完，意图按确定性哈希从温和池里挑；
      消息命中悲伤/低落词族时整条不贴（审计 C1：刚安慰完转头贴笑脸
      等同嘲讽），呲牙/偷笑/憨笑等笑脸族因此到不了悲伤场景。

    bot_related 仅约束触发 B（after_reply 时 bot 已参与对话，天然相关）。
    """
    knobs = reaction_knobs(config)
    mid = str(user_message_id or "").strip()
    if not knobs["enabled"] or not mid:
        return False
    if not _is_group_session(session_key):
        return False
    if trigger == "emotion_signal":
        if bot_related is not True:
            return False
        intent = infer_signal_intent(text)
        if intent is None:
            return False
        salt = f"signal:{intent}"
    else:
        if is_sad_message(text):
            return False
        intent = ""
        salt = "reply"
    active_gate = gate if gate is not None else SHARED_PROACTIVE_GATE
    if not active_gate.allow(
        session_key,
        mid,
        enabled=True,  # 开关已在上面判过；这里保持门内状态一致。
        probability=knobs["probability"],
        cooldown_seconds=knobs["cooldown_seconds"],
        max_per_hour=knobs["max_per_hour"],
        salt=salt,
        now=now,
    ):
        return False
    emoji_id = select_reaction_emoji(intent, f"{session_key}:{mid}")
    logger.info(
        "reaction select: trigger=%s intent=%s emoji=%s session=%s",
        trigger, intent or "(兜底池)", emoji_id, session_key,
    )
    return await react_to_message(bot, message_id=mid, emoji_id=emoji_id)


# ------------------------------------------------------- 进程级共享实例

SHARED_REACTION_BUFFER = ReactionBuffer()
SHARED_PROACTIVE_GATE = ProactiveGate()


def describe_chat_reactions(session_key: str) -> str:
    """人格上下文注入用：读共享缓冲渲染【表情回应】正文（空=整块不出现）。"""
    return SHARED_REACTION_BUFFER.describe(session_key)
