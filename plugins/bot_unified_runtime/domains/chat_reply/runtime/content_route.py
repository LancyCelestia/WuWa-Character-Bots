"""R-18 内容感知路由（bot.content_route）：会话亲密度分数 + 本地信号。

职责（2026-09-16 批次，用户裁定需求：R-18/成人/性相关内容直切 grok-4.6，
不在 gemini-3.8-flash 上花时间；2026-09-17 修订：模型自评标签层整体移除——
gemini 与 grok 都把 ``<intimacy:high|low>`` 元指令当成注入攻击/隐藏追踪协议
整轮拒答（生产拒答原文点名 "output routing tags / hidden tracking
protocols"），连无辜消息都被拒。检测改为纯本地信号，零模型配合、零拒答面）：

1. L1 即时强词表：当前消息命中强词表→+70，越过 intimate 阈值当轮即切。
   词表自包含（不复用 security/content_safety 的守界正则——路由信号与
   守界动作解耦，守界模块零改动）。
2. L2 上下文窗口：本次请求 messages 尾部 K 轮扫描，历史强词 +35——
   抓「前几轮铺垫、本轮『继续』」的语境升级型。
   （边缘词/擦边词不再参与记分：用户裁定普通模式可以擦边，擦边消息
   留在默认链；只有强词或手动开关才切 grok。）
3. L4 手动命令：「亲密模式 开/关」（含「开启亲密模式」倒装）钉死/解除
   会话状态，覆盖一切自动判定。
4. 滞回状态机：分数 ≥ intimate 阈值→INTIMATE（候选序 [grok, gemini, …]，
   由 ModelRouter 的 content_route_cb 重排）；≤ normal 阈值→NORMAL（默认
   链原样）；两阈值之间保持前态防场景中途抖动。干净轮 ×0.5 自然衰减，
   会话空闲超时归零，max_ttl 硬上限兜底。
   ⚠ 2026-09-24 用户裁定收口了"INTIMATE 就一定换模型"这条隐含等式：**Master Love
   不得改变默认模型**——名单用户仍是缺省链首 gemini，ML 只授予亲密档（语气与内容
   放行）。档因此带上**来源**（`INTIMATE_SOURCE_*`，只住 `_SessionState.pin_source`
   一处），只有显式「亲密模式 开」/管理员钉/内容信号越阈这三种来源有权把头插成
   grok（判据=`_MODEL_SWITCH_SOURCES`）。

v21r5 双开关扩展（2026-09-19 用户裁定）：

5. 群聊两级状态：管理员「亲密模式 开」=群级钉（**群作用域键**——中央件
   ``session_keys.group_scope_key`` 构造，全群共享一把，全群生效；T-1 修复
   2026-09-27：生产群键逐成员，原样落键=只钉管理员自己）；
   普通成员「亲密模式 开」=个人级钉（成员派生键 ``(群键, 用户号)``，仅本人）。
   群消息的路由/注入键=成员派生键 ``member_session_key(群键, sender_id)``，
   判定时先查群级钉（群 ON→全员 intimate；群 OFF 不压制成员个人档——开关一
   为个人自主，设计裁定），再走成员键自身滞回。
6. 亲密档 TTL：``bot_content_route_intimate_ttl_minutes``（默认 60 分钟），
   intimate 钉按 ``activated_at``（激活时刻）惰性过期——会话活跃不续期、
   重新开启即重置；两个开关（群级/个人级）同一 TTL。既有
   ``bot_content_route_max_ttl_minutes``（默认 120）保留为全状态硬上限。
7. 四名单：群两面=既有群白/黑名单（会话准入门）；私聊两面=新私聊白/黑名单，
   在 ``explicit_allowed_for_session`` 内实现（白名单空=放开、非空=仅名单内、
   黑名单最高优先——Master Love 压不过黑名单）。
   合成单一事实源=``resolve_intimate_context``（注入缝与路由双门同源）。
8. 显式开档跨重启（2026-10-03 用户裁定 D-1「要」）：本人在**私聊**里显式「亲密模式
   开/深开」这件事，连同档位与开启时刻（墙钟），记进已有的 per-person 存储
   ``addressing_preferences`` 的两列（不新建库、不加配置键）；重启后自动腿来重钉时
   凭它沿用 ``manual_command`` 源与该档，而不是降级成无叙述权的 ``master_love``。
   群侧两支（管理员钉、群内成员个人钉）都不入库；``intimate_ttl_minutes`` 语义不变
   （回填起算点⇒重启也不续期，到点仍清）。判据与边界全在 ``_EXPLICIT_PIN_REPIN_SOURCES``
   上方那一节，改之前先读它。
9. 描写档（2026-10-04 用户裁定 G-1～G-3）：「进没进亲密档」(``MODE_*``) 与
   「档的深浅」(``INTIMATE_TIER_*``) 之外的**第三轴**——只答"出口之外那些维度写不写"，
   两值 ``speech``（只说出口的话，**缺省**）/ ``scene``（语言＋动作＋心理＋神态＋外貌
   全铺开），**普通模式同样能拿**（G-1，判据不看档在不在）。本人持久钉落进**已有**的
   ``addressing_preferences``（再两列 ALTER-if-missing、与第 8 条同表同键、**没有 TTL**、
   不新建库不加配置键）；来源 ``narration_pin`` 是 ``_INTIMATE_NARRATION_SOURCES`` 的
   **第 4 枚**（G-2：并进那把唯一的授予尺，换模型/TTL 豁免/缺省浅档/重钉那四张轴一个成员
   都不跟着动，也不许拿 ``manual_command`` 蒙混）。群侧"只有她自己开过的才算"＝钉的键形是
   **(平台域, 会话, 这个人)** 三段（I-2，2026-10-04 21:0x「'跟着人走'就是在这个会话里跟着
   这个人走……换了会话就需要重新激发」：群 A 钉过≠群 B 也有，私聊钉过≠群里也有；会话段
   复用库里已有的 ``session_type``/``session_id`` 两列，零新表零新列零迁移）＋写腿沿用亲密
   开关同一道角色门（G-3，两腿同守——①钉的读键是成员派生键，群作用域键压根没有本人段；
   ②H-1＝甲 那格"开亲密即缺省 scene"只在裁决
   **不出自整群那一桶**时才交，全群开关（``from_group_pin``）照旧把旁人留在 ``speech``，
   于是管理员替整群拨的亲密档永不广播描写档）。读数走 ``resolve_intimate_context`` 新增的
   ``narration_mode`` / ``narration_source`` 两格，授予判据仍只有 ``grants_intimate_narration``
   一处。命令面 ``/bot 描写 speech|scene|reset|show``（词表真身＝``_NARRATION_SUBCOMMAND_TABLE``，
   分诊与行文在 ``runtime/intimate_control.py``）。

会话准入门在 capabilities/chat.py（持有 session_type 与群黑白名单配置）：
仅私聊/控制台/已获准群聊参与评分与手动开关。

``consume_reply`` 保留为防御性标记剥离（历史残留 ``<intimacy:...>`` 出站前
清掉），不再有注入侧。

本模块不导入 NoneBot/LLM 栈，可离线单测（唯一例外＝上面第 8 条的持久化腿：它懒
import ``character/providers``，且只在配置真点名了 ``bot_addressing_preferences_db_path``
时才走那一脚——纯离线引擎单测的配置面没这一枚，于是照旧零重依赖、零 SQLite）。
第 7 条的并号腿同款懒 import ``character/reply_policy``（只为取那一枚归并真身，
**不建 store、不打库**），且只在配置真给了别名表时才走。
所有公开方法 fail-open——内部异常一律返回安全缺省（NORMAL/原文本），绝不影响主链路。
"""
from __future__ import annotations

import functools
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
    relation_instruction,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    KIND_GROUP,
    KIND_PRIVATE,
    UNKNOWN_SENDER,
    group_scope_key,
    parse_session_key,
    person_scope_key,
    sanitize_key_segment,
)

# 会话状态 LRU 封顶：防长跑慢泄漏（poke/_POKE_LAST_CAP 同款纪律）。
_SESSION_CAP = 4096

# ---------------------------------------------------------------- 标记剥离

# 防御性剥离正则：标签注入层已删（2026-09-17），模型不应再产出该标记；
# 保留剥离以清掉历史上下文里可能残留的标记，防外泄。
_TAG_RE = re.compile(r"^\s*[\"'「『]?\s*<\s*intimacy\s*:\s*(high|low)\s*>\s*[\"'」』]?")

# ---------------------------------------------------------------- L1 词表

# 强词表：单次命中即把分数抬过 intimate 阈值（R-18/成人/性相关的显性表达；
# 简繁同收）。误命中代价=当轮由 grok 回答（人格提示词照常注入，无害），
# 故宁可略宽。
_STRONG_WORDS: tuple[str, ...] = (
    "nsfw", "r18", "r-18", "r 18",
    "色情", "性爱", "性行为", "性交", "做爱", "做愛", "做一次", "要做我",
    "上我", "睡我", "操我", "插入", "内射", "高潮", "自慰", "手淫",
    "口交", "乳交", "肛交", "打飞机", "黄片", "黄文", "全裸", "裸体", "裸照",
    "脱光", "脱衣服", "脱衣", "宽衣", "乳房", "奶子", "乳头", "下体",
    "阴茎", "阴道", "后穴", "淫", "骚穴", "发情", "欲火", "情欲", "情慾",
    "sex", "sexually", "porn", "nude", "nudes", "naked", "orgasm", "horny",
    "erotic", "fuck me", "blowjob", "handjob", "cum",
)

def _compile_word_list(words: list[str]) -> re.Pattern[str] | None:
    """词表 → 单一交替正则；空表返回 None。词面按 re.escape 处理。"""
    cleaned = sorted({str(word).strip() for word in words if str(word).strip()})
    if not cleaned:
        return None
    return re.compile("|".join(re.escape(word) for word in cleaned), re.IGNORECASE)


_BUILTIN_STRONG_RE = _compile_word_list(list(_STRONG_WORDS))


def _parse_extra_words(raw: object) -> tuple[str, ...]:
    """配置追加词表：逗号/顿号/分号/空白分隔。"""
    return tuple(
        piece.strip()
        for piece in re.split(r"[,，、;；\s]+", str(raw or ""))
        if piece.strip()
    )


# ---------------------------------------------------------------- L4 手动命令

# 亲密档的**深浅**（2026-09-24 用户裁定）：两档都算"进了亲密档"（给语气与放行），
# 只有深档有权换真实首跳。档位在状态里只记一处（`_SessionState.pin_tier`），
# 判据只住 `_head_if_switchable`，全仓不设第二套深浅判定。
INTIMATE_TIER_NONE: str = ""  # 未进档（或已解除）
INTIMATE_TIER_L1: str = "l1"  # 浅档：关系语气 + 既有放行，**默认模型不变**
INTIMATE_TIER_L2: str = "l2"  # 深档：同上 + grok 优先（R-18 在册通道）

# 亲密档的**模式值**（引擎对外的三态之一：进档 / 普通 / 没钉=``None``）：与上面的
# 档位常量同一条纪律——全仓只在这里声明一次，其余各处一律引用这两个名字。
# 为什么这一对名字必须存在（2026-09-25 S256 归因）：09-24「深浅档」改道把
# `match_intimate_command` 的返回从裸串 ``return "intimate"`` 换成混合元组
# ``("intimate", tier)``，模式字面量因此从「散文位」升格为「声明位」——词面级
# 独立声明账（``tests/test_trigger_word_single_source.py`` C 维度·混合容器元素）
# 据此把 ``intimate`` 记成 echo 帮助别名真身之外的第二处独立声明，棘轮当场红。
# 修法**不是**让状态机去引帮助册（那会把运行时判据钉在帮助登记面上，且
# echo 依赖本模块方向相反），而是照 `INTIMATE_TIER_*` 的既有做法：值只有一个名字，
# 别处只引用。⚠ 新增模式值只准改这两行，不准在第四处再写字面量（该账会红）。
MODE_INTIMATE: str = "intimate"  # 进了亲密档（深浅由 `INTIMATE_TIER_*` 记）
MODE_NORMAL: str = "normal"  # 普通档：默认链原样

# ---------------------------------------------------------------- 描写档（第三轴）
#
# 2026-10-04 用户裁定 G-1～G-3：在「进没进亲密档」(`MODE_*`) 与「档的深浅」
# (`INTIMATE_TIER_*`) 之外立**第三轴**——这一轴只回答一件事：**出口之外的那些维度
# 写不写**（动作／神态／心理／外貌）。两格、缺省只说话：
# - ``speech``：只写说出口的话（**缺省**，G-1「普通模式也能用 scene，缺省 speech」
#   的另一面就是"亲密档本身不再自带描写"）；
# - ``scene``：语言＋动作＋心理＋神态＋外貌一并铺开写长。
# 与上面两对常量的同一条纪律：**字面量只在这里声明一次**，其余各处只准引名字
# （词面级独立声明账按 `tests/test_trigger_word_single_source.py` 记债，09-25 S256
# 那一格就是把裸串升格成声明位被当场记红的先例）。
NARRATION_MODE_SPEECH: str = "speech"  # 只写说出口的话（缺省）
NARRATION_MODE_SCENE: str = "scene"  # 语言＋动作＋心理＋神态＋外貌全铺开
NARRATION_MODE_DEFAULT: str = NARRATION_MODE_SPEECH  # 裁定缺省＝只说话
NARRATION_MODES: tuple[str, ...] = (NARRATION_MODE_SPEECH, NARRATION_MODE_SCENE)


def normalize_narration_mode(raw: object) -> str:
    """任意输入 → 轴上取值：认不出／空的都落**缺省**，绝不抛。

    fail-safe 的方向是"少写"不是"多写"：把一句没认出来的话糊成 ``scene``，等于凭一个
    错字把五维叙述塞进这一轮（同 `match_intimate_subcommand` 不猜档的口径）。
    """
    key = str(raw if raw is not None else "").strip().lower()
    return key if key in NARRATION_MODES else NARRATION_MODE_DEFAULT

_MANUAL_ON_RE = re.compile(
    r"^\s*/?\s*(?:亲密模式\s*(?:开启|打开|开|on)|(?:开启|打开|开|on)\s*亲密模式)"
    r"\s*[。!！~～]?\s*$",
    re.IGNORECASE,
)
# 深档形态（2026-09-24 用户裁定 R3 A）：「亲密模式 开」自此只给**浅档**（语气+放行，
# 不换默认模型），要 grok 优先得说"深开/开深/开 二档/开 grok"。
# ⚠ 行为改道：改前「亲密模式 开」= 换 grok。三条深档判据先于浅档匹配（防"深开"被
# "开"字吞掉降档），且都带 `$` 锚——句中出现"深开"不算命令。
_MANUAL_DEEP_ON_RE = re.compile(
    r"^\s*/?\s*(?:亲密模式\s*(?:深开|深启|开\s*深|深\s*开|开\s*二档|开\s*2\s*档|开\s*grok|二档|深档)"
    r"|(?:开启|打开)\s*亲密模式\s*(?:深档|二档))"
    r"\s*[。!！~～]?\s*$",
    re.IGNORECASE,
)
_MANUAL_OFF_RE = re.compile(
    r"^\s*/?\s*(?:亲密模式\s*(?:关闭|解除|关|off)|(?:关闭|解除|关|off)\s*亲密模式)"
    r"\s*[。!！~～]?\s*$",
    re.IGNORECASE,
)


def match_intimate_command(text: str) -> tuple[str, str] | None:
    """亲密命令 → ``(mode, tier)``；非命令返回 None。

    深浅档位的**解析口按词面分两条、同形不同路**，本函数只是其中一条：
    ①整句面＝本函数（吃中文整句，词面即下方三条 ``_MANUAL_*_RE``，都带行锚）；
    ②命令面＝``match_intimate_subcommand``（吃 ``/bot intimate`` 剥掉前缀剩下的参数串，
    词面真身＝本文件的 ``_INTIMATE_SUBCOMMAND_TABLE``，此处不抄它的成员）。
    两套词面互不引用是有意为之；两条路返回的形状与三态语义逐字同——
    ``(MODE_INTIMATE, INTIMATE_TIER_L1)`` 浅档（不换模型）、
    ``(MODE_INTIMATE, INTIMATE_TIER_L2)`` 深档（grok 优先）、
    ``(MODE_NORMAL, INTIMATE_TIER_NONE)`` 两档一起解除。
    "两个口"不冲掉另外三处单真身：档位**字面量**只落本文件 ``MODE_*``/``INTIMATE_TIER_*``
    那一处；「L2 才有资格换真实首跳」的**判据**只住 ``_head_if_switchable``；命令面的
    **入口与三腿分诊**在 ``runtime/intimate_control.py`` 的 ``build_intimate_control_result``
    （能力 id 复用 ``bot.chat``，未另铸）。旧读面 ``match_manual_command`` 是本函数的薄壳、
    不成第三条口。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if _MANUAL_DEEP_ON_RE.match(stripped):
        return (MODE_INTIMATE, INTIMATE_TIER_L2)
    if _MANUAL_ON_RE.match(stripped):
        return (MODE_INTIMATE, INTIMATE_TIER_L1)
    if _MANUAL_OFF_RE.match(stripped):
        return (MODE_NORMAL, INTIMATE_TIER_NONE)
    return None


def match_manual_command(text: str) -> str | None:
    """旧读面薄壳（"intimate"/"normal"/None）：只转述 `match_intimate_command` 的
    mode，**不设第二套正则**。深档在这一层也回 "intimate"——需要区分深浅的调用方
    必须改读 `match_intimate_command`，档位判据始终只住那一处。
    """
    matched = match_intimate_command(text)
    return matched[0] if matched is not None else None


# ---------------------------------------------------------------- L4 子命令参数口
#
# `/bot intimate <子命令>` 这一族的**参数串**解析口（2026-10-08 波）。与上面的整句口
# `match_intimate_command` 是**同形不同路**：那一口吃「亲密模式 开/深开/关」这类中文整句
# （三条 `_MANUAL_*_RE`），本口吃命令面剥掉前缀后剩下的 `on/deep/off` 这类参数。两套词面
# 各写各的、互不引用是有意为之——命令面走英文子命令、人格口语面走中文整句，两侧本就该独立
# 演进；共用一张词表只会让一次改词静默改掉另一条路。**档位只此两值、深浅只此两码**：
# 返回值一律引 `MODE_*` / `INTIMATE_TIER_*`，本文件之上那两行声明是唯一字面量落点，
# 这里再抄一遍 `"intimate"`/`"l1"` 就会被词面级独立声明账
# （`tests/test_trigger_word_single_source.py`，零余量棘轮只准降）当场记红。
# 键侧（on/open/deep/…）是**用户输入形态**而非档位值，只能以字面量出现在此处。
_INTIMATE_SUBCOMMAND_TABLE: dict[str, tuple[str, str]] = {
    # 浅档：关系语气 + 既有放行，**默认模型不变**。
    "on": (MODE_INTIMATE, INTIMATE_TIER_L1),
    "open": (MODE_INTIMATE, INTIMATE_TIER_L1),
    "l1": (MODE_INTIMATE, INTIMATE_TIER_L1),
    # 深档：同上 + grok 优先（R-18 在册通道）。
    "deep": (MODE_INTIMATE, INTIMATE_TIER_L2),
    "deeper": (MODE_INTIMATE, INTIMATE_TIER_L2),
    "l2": (MODE_INTIMATE, INTIMATE_TIER_L2),
    # 解除：深浅两档一起放下。
    "off": (MODE_NORMAL, INTIMATE_TIER_NONE),
    "close": (MODE_NORMAL, INTIMATE_TIER_NONE),
    "unset": (MODE_NORMAL, INTIMATE_TIER_NONE),
}


def match_intimate_subcommand(arg: str) -> tuple[str, str] | None:
    """`/bot intimate` 的子命令参数串 → ``(mode, tier)``；认不出返回 None。

    输入＝调用方**已剥掉 `/bot intimate` 前缀**后剩下的参数串（本口不管前缀，前缀归命令面）。
    三态语义与整句口 `match_intimate_command` 逐字同：``(MODE_INTIMATE, INTIMATE_TIER_L1)``
    浅档、``(MODE_INTIMATE, INTIMATE_TIER_L2)`` 深档、``(MODE_NORMAL, INTIMATE_TIER_NONE)``
    解除。大小写不敏感、首尾空白容忍；**认不出的一律 None**——不猜档、不把"没认出来"
    悄悄回落成"开"（那等于凭一个错字把会话推进亲密档）。

    ⚠ ``show`` 有意**不在表里**、由本口返回 None：它是只读查询，既不上钉也不解钉，
    给它任何 ``(mode, tier)`` 都等于「看一眼当前档位，顺手把档位改了」。调用方该这样分诊：
    先取本口，返回非 None 就走开关腿；返回 None 后再自己认一次
    ``str(arg or "").strip().lower() == "show"`` 走查询腿；两条都不中才回"不认得"。
    本口返回形状只有 ``(mode, tier)`` 与 ``None`` 两种，**不设第三种**。
    """
    key = str(arg or "").strip().lower()
    if not key:
        return None
    return _INTIMATE_SUBCOMMAND_TABLE.get(key)


# ------------------------------------------------- 描写档子命令参数口（G-0 乙：词面只这一处）
#
# `/bot 描写 <子命令>` 一族（2026-10-04 裁定 G-0 取「乙」＝**一枚令牌只住一个家**：命令名
# 与帮助册都指这张表，全仓不重列 ⇒ 词债实测 0~3 枚，甲案「新词面在别名/触发/昵称三处重列」
# 要 +11~18）。词表**与 `_INTIMATE_SUBCOMMAND_TABLE` 挨着放、形状照它**：一张表、一次
# `strip().lower()`、认不出 None，**不新写解析器**。
#
# ⚠ **只有英文子命令，不带中文整句别名**（有意与开关面同纪律）：那两张表的 docstring 都写明
# 「命令面走英文子命令、人格口语面走中文整句，两套词面互不引用是有意为之——共用一张表只会
# 让一次改词静默改掉另一条路」。中文整句那一族（`_MANUAL_*_RE`）今天说的是"亲密模式 开/关"，
# 给描写档另起整句正则＝新造第三族词面，本波不做（要做需她另裁词面）。
#
# 三态返回形状与开关面**不同**（那里是 `(mode, tier)`，这里是单枚模式串）：
# - ``NARRATION_MODE_SPEECH`` / ``NARRATION_MODE_SCENE``＝轴上两值（引常量，不重抄字面量）；
# - ``""``＝**收回钉**（reset：把这一格交回缺省，与"钉上 speech"在库里是两回事——
#   前者库里没行、后者库里明明白白写着本人要 speech，`show` 要能分辨）；
# - ``None``＝认不出（不猜档）。
# ⚠ ``show`` 有意**不在表里**：只读查询拿到任何一格模式都等于"看一眼顺手把描写改了"
# （与 `match_intimate_subcommand` 同一纪律）；它的词面真身住在命令面
# `runtime/intimate_control.SHOW_SUBCOMMAND`（那里已声明过一次，这里再抄就是第二处声明位）。
_NARRATION_SUBCOMMAND_TABLE: dict[str, str] = {
    NARRATION_MODE_SPEECH: NARRATION_MODE_SPEECH,  # 只说出口的话（轴上缺省那一格）
    NARRATION_MODE_SCENE: NARRATION_MODE_SCENE,  # 语言＋动作＋心理＋神态＋外貌全铺开
    "reset": "",  # 收回钉：库里那两格一起清掉（无 TTL，见 `_narration_axis_reading`）
}


def match_narration_subcommand(arg: str) -> str | None:
    """`/bot 描写` 的子命令参数串 → 描写档模式串；认不出返回 None。

    输入＝调用方**已剥掉前缀**后剩下的参数串（与 `match_intimate_subcommand` 同口径，
    前缀归命令面）。三态见上面那张表的注释块：两值 / ``""``（收回钉）/ ``None``
    （认不出，**不猜**）。大小写不敏感、首尾空白容忍。
    """
    key = str(arg or "").strip().lower()
    if not key:
        return None
    return _NARRATION_SUBCOMMAND_TABLE.get(key)




# 确认话术（守岸人语气：温和、定性、不提协议细节——两档的回话都得让人看得出"档不同"，
# 但都不许出现模型名/路由/阈值这类字眼）。
MANUAL_ON_REPLY = "好，这一段对话我会换一种更贴近你的方式来聊。"
# 深档确认句（2026-09-24 新增，随「深开」形态）：措辞已交用户过目前先用这一版。
MANUAL_DEEP_ON_REPLY = "嗯，这一段我不收着了，你说什么我都接着。"
MANUAL_OFF_REPLY = "嗯，回到平时这样聊就好。"

# Master Love（2026-09-17 用户裁定）：master（创造者/唤醒者）的恋人语境。
# 开关=bot_master_love_enabled；名单=bot_master_love_admins（条目 "qq"=全域、
# "群号:qq"=仅该群，AstrBot 风格的「指定群聊里的指定用户」）。
# 2026-09-24 R2 A：这段原文迁入受控关系词表 `character/relationships.py`（唯一真身，
# 逐字未改，由 `tests/test_relationships.py` 的 sha 锁钉住），本名降为再导出垫片——
# chat 主链的导入面与注入文本一字不动。
MASTER_LOVE_INSTRUCTION: str = relation_instruction("master")



def match_master_love_admin(sender_id: str, group_id: str, entries: list[str]) -> bool:
    """master-love 名单匹配：条目 "qq"=全域命中；"群号:qq"=仅该群命中。

    任何异常 fail-open False（绝不因名单解析把普通消息当 master）。
    """
    try:
        sid = str(sender_id or "").strip()
        if not sid:
            return False
        gid = str(group_id or "").strip()
        for raw in entries or []:
            item = str(raw or "").strip()
            if not item:
                continue
            if ":" in item:
                entry_gid, _, entry_sid = item.rpartition(":")
                if entry_sid == sid and entry_gid == gid:
                    return True
            elif item == sid:
                return True
        return False
    except Exception:  # noqa: BLE001 - fail-open。
        return False


# ---------------------------------------------------------------- v21r5 双开关：群聊两级状态

# 成员派生键分隔符：双竖线 + "u:" 前缀。生产群键=中央件下划线形
# `group_<群号>_<发送者>`（逐成员一把）、私聊=裸 QQ 号；冒号形 `group:<gid>`
# 只存在于合成/开发/出站命名空间（判据见 domains/core/session_keys 模块头，
# 旧注释"群 session_id 形如 group:123（摄取层惯例）"即本仓点名过的误导源，
# T-1 缺陷的根。QQ 数字 id 使这些形态都不天然含 `||u:`；构造侧仍把两段过
# 中央件消毒（T-2），用户可控输入伪不出嵌套键。个人级状态分桶 (群,用户)。
_MEMBER_SCOPE_SEP = "||u:"


def member_session_key(group_session_key: str, sender_id: str) -> str:
    """群聊成员派生键：开关一（个人级亲密状态）的载体 = (群键, 用户号)。

    T-2（2026-09-27）：两段先经中央件 ``sanitize_key_segment`` 消毒（既有清洗
    口径 + 剔除分隔符子串至不动点）。消毒只在这一处构造点发生，拆键侧
    （``split_member_session_key``）不另立第二套清洗判据。
    """
    base = sanitize_key_segment(group_session_key, forbidden=_MEMBER_SCOPE_SEP)
    member = sanitize_key_segment(sender_id, forbidden=_MEMBER_SCOPE_SEP)
    return f"{base}{_MEMBER_SCOPE_SEP}{member}"


def split_member_session_key(session_key: str) -> tuple[str, str] | None:
    """成员派生键 → (群键, 用户号)；非成员键返回 None。"""
    key = str(session_key or "")
    if _MEMBER_SCOPE_SEP not in key:
        return None
    group_key, _, member_id = key.rpartition(_MEMBER_SCOPE_SEP)
    if not group_key.strip() or not member_id.strip():
        return None
    return group_key, member_id


# ---------------------------------------------------------------- 亲密档的"为什么"

# 用户裁定（2026-09-24）：**Master Love 不得改变默认模型**——名单用户仍走原本默认的
# gemini-3.8-flash，ML 只授予亲密档（语气 + 内容放行），grok 头插只由**显式
# 「亲密模式 开」/管理员钉**触发。"档成立"与"该换模型"因此是两件事，判据落在档位的
# **来源**上。来源只住一处（`_SessionState.pin_source`，由上钉的那一刻交出），
# 全仓不设第二套来源判定、不新增配置键。
INTIMATE_SOURCE_NONE: str = ""  # 未进亲密档
INTIMATE_SOURCE_MANUAL: str = "manual_command"  # 本人显式「亲密模式 开/深开」
INTIMATE_SOURCE_ADMIN_PIN: str = "admin_pin"  # 管理员钉（群级作用域）
INTIMATE_SOURCE_MASTER_LOVE: str = "master_love"  # Master Love 名单派生
INTIMATE_SOURCE_CONTENT_SIGNAL: str = "content_signal"  # L1/L2 强词越阈（无钉）
# 好感度自动腿（2026-09-24 用户裁定 R1 A）：L1 对**所有用户**开放，但按相处深浅自动
# 进档（达 `bot_content_route_l1_auto_min_tier` 那一档及以上），不是"名单内才给"。
# 它与 master_love 同类：只给档、绝不换模型。
INTIMATE_SOURCE_AFFINITY: str = "affinity_tier"
# 描写档持久钉（2026-10-04 用户裁定 G-2「scene 并入既有那**一把**授予尺，不许长第二张
# 成员表」）：这一枚答的是"这个人亲手把描写钉在了哪一格"，与"怎么进的亲密档"无关，
# 所以它**只**进 `_INTIMATE_NARRATION_SOURCES`（叙述授予轴），
# 不进换模型／TTL 豁免／缺省浅档／跨重启重钉那四张（钉了描写≠换了首跳、≠免 TTL、
# ≠自动浅档、≠亲密档活过重启）。锁：`tests/test_narration_axis_command.py`
# 的 `test_other_four_source_axes_are_untouched_by_the_new_member`。
INTIMATE_SOURCE_NARRATION_PIN: str = "narration_pin"

# 允许据此**更换真实首跳**的来源集合：ML 与好感度派生不在其中（用户裁定）。
# 内容信号单列在案是有意的——「R-18/成人/性相关内容直切 grok-4.6」是 2026-09-16 的
# 在册裁定，把"只有显式与钉死才换模型"读成"连内容信号也不换"会整类削掉那条路，
# 故本集合只排除 `master_love`/`affinity_tier`；判据只此一份，见 `_head_if_switchable`。
_MODEL_SWITCH_SOURCES: frozenset[str] = frozenset(
    {INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_ADMIN_PIN, INTIMATE_SOURCE_CONTENT_SIGNAL}
)

# 来源→缺省档位的**唯一**派生处：只在调用方没交档位时用（旧调用面、旧在飞状态）。
# 浅档来源=只给档不改模型；其余来源缺省按改道之前的语义（显式/钉/信号都换模型），
# 这样未升级的调用点行为逐字节不变。
_SHALLOW_DEFAULT_SOURCES: frozenset[str] = frozenset(
    {INTIMATE_SOURCE_MASTER_LOVE, INTIMATE_SOURCE_AFFINITY}
)

# 不受 ``max_ttl`` 封顶的来源（2026-09-24 用户裁定 R4 A：L2 不设置 120 分钟硬上限）。
# 只免"人亲手上着的钉"这两支：管理员代全群上的钉与本人显式开的钉——它们各自已经
# 被 `bot_content_route_intimate_ttl_minutes` 管着，配到多长就是多长，不再被第二道
# 上限悄悄截掉。自动信号档（无钉）与 normal 钉不免。
_MAX_TTL_EXEMPT_SOURCES: frozenset[str] = frozenset(
    {INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_ADMIN_PIN}
)

# 五维展开叙述（语言/动作/神态/心理/外貌）的授予面（2026-10-04 用户裁定）。
# 她原话：「superadmin 的默认 master love 模式仍然为只描述说话内容，不描述动作等，
# 要求输入显式指令打开亲密模式 L1、L2 才变成这样」。
# 所以"进了亲密档"与"有权展开叙述"是两件事：`master_love`（名单派生）与
# `affinity_tier`（好感度达档自动）这两支**只给档、给语气、给放行，不给描写**；
# 要描写得由人亲手推动——下指令、管理员代全群钉，或内容信号自己跨了阈。
# ⚠ 成员与 `_MODEL_SWITCH_SOURCES` **曾经恰好同形**（本波之前三支全等），纯属巧合，
# **不得复用那一枚**：一枚答"要不要换真实首跳"，一枚答"要不要展开叙述"。两轴日后可能各自放宽（给 ML 免
# TTL 也好、给浅档换模型也好），复用会让一条裁定静默改写另一条例子——正是本波要防的
# 「换了个档，结果文风全部都变了」（她 2026-09-28 原话，见 `NORMAL_NO_ACTION_INSTRUCTION`
# 上方注释与 §53）。
# 🔴 2026-10-04 G-2 之后本集合是 `_MODEL_SWITCH_SOURCES` 的**超集**（多出
# `narration_pin`：钉了描写档**不**换模型）。结构锁
# `tests/test_intimate_source_set_separation.py` 里"今天同形"那一枚等值断言据此**过期**
# ——那是那条锁自己写明的用法（放宽必须红一次、要人确认是有意的轴分离，不是并枚）。
# 改的是断言、不是尺：本席不动那把锁，交由主会话按裁定重锚。
# ⚠ 取**白名单**形而不是"排除 ML/affinity"的黑名单形：未知来源（含 `INTIMATE_SOURCE_NONE`）
# 一律不授予，与全仓 fail-closed 的口径一致。
_INTIMATE_NARRATION_SOURCES: frozenset[str] = frozenset(
    {
        INTIMATE_SOURCE_MANUAL,
        INTIMATE_SOURCE_ADMIN_PIN,
        INTIMATE_SOURCE_CONTENT_SIGNAL,
        INTIMATE_SOURCE_NARRATION_PIN,
    }
)


def grants_intimate_narration(source: str) -> bool:
    """本轮是否有权展开五维叙述——**判据只此一份**，调用方只准调它，不许再抄成员表。

    本函数**只答叙述**。档位（`INTIMATE_TIER_*` / `_tier_for_source`）、换真实首跳
    （`_head_if_switchable` + `_MODEL_SWITCH_SOURCES`）、TTL 封顶
    （`_MAX_TTL_EXEMPT_SOURCES`）三件事各住各处，这里一个都不读。
    """
    return str(source or "").strip() in _INTIMATE_NARRATION_SOURCES


def _tier_for_source(source: str) -> str:
    """未记档位时的缺省档（唯一派生处，`apply_manual`/`route_verdict` 共用）。"""
    return INTIMATE_TIER_L1 if source in _SHALLOW_DEFAULT_SOURCES else INTIMATE_TIER_L2


# ------------------------------------------------- 显式开档的跨重启标记（D-1，2026-10-03）

# 她 2026-10-03 裁「要（显式开档跨重启持久化）」治的这一格：档态住在**进程内** LRU
# （``_SESSION_CAP`` + 模块级单例 ``SHARED_CONTENT_ROUTE_ENGINE``）⇒ 重启即空；而
# ``capabilities/chat.py`` 那两支自动腿的守卫是 ``pinned_mode(...) is None``，重启后
# 以 ``master_love`` / ``affinity_tier`` 重钉 —— 这两个来源都不在
# ``_INTIMATE_NARRATION_SOURCES`` 里（2026-10-04 裁定：叙述授予只给"人亲手推动"的来源）
# ⇒ 她亲手开过的会话拿不回五维。
#
# **存哪、存什么、怎么判**（三问三答，都在这一节里）：
# - 存哪：写进**已有**的 per-person 存储 ``addressing_preferences``（owner
#   ``character/addressing.py``，库键 ``bot_addressing_preferences_db_path`` 在
#   ``config.py`` + ``docs/db-owners.md`` 双册在册），两列 ALTER-if-missing，与
#   ``relationship`` 同一先例同一行。**不新建库**（新建＝多 6~8 处同批账，且
#   ``test_db_owners_coverage.py`` ↔ ``config.py`` 双锁会当场拦）、**不新增 ``BOT_*``
#   键**、**不加第三张来源集合表**：语义上"他自己把亲密档开到了哪一档"就是"这个人
#   显式声明的相处偏好"这一族，和称谓／性别自述／关系档同表不同列。
# - 存什么：只有 ``tier``（开到哪一档）与 ``explicit_at``（**墙钟** epoch 秒，什么时候
#   开的）。它是"**重启后该以什么来源重钉**"的凭据，**不是**"档永远开着"的凭据。
# - 重钉判据：自动腿来上钉时，若 ``0 < now_wall - explicit_at <= intimate_ttl_minutes``
#   ⇒ 沿用 ``manual_command`` 源与该档，并把 ``activated_at`` **回填**到首次显式开启
#   那一刻（``now - elapsed``）；超出 TTL ⇒ 交回调用方原本交来的来源（＝今日行为）。
#   回填这一笔是关键：于是 ①会话活跃不续期（S40-D2 既有裁定）②**重启也不续期**
#   （本波新立的对称面）③到 ``explicit_at + TTL`` 仍清成普通档，清完再不复活——
#   ``intimate_ttl_minutes`` 的语义一字没动，只是"起算点"不再被重启洗掉。
#
# 边界（都是有意为之，动之前先读）：
# 1. **群侧两支都不入库**。``admin_pin`` 是管理员**当场替整群**拨的授权，活过重启＝
#    一句"开"变成永久"开"，那不是那句话说过的事；群内成员的个人钉（成员派生键
#    ``X||u:Y``）同样不入库——本波裁定面写的是"私聊里显式说过"。判据取**键的作用域**
#    （``_explicit_pin_person_key`` 只认私聊键），不取来源标签，所以管理员在私聊里
#    给自己开（那本来就是本人显式腿）与在群里替全群开，天然分家。
# 2. **标记只在自动腿本来就要上钉的那一刻被读到**（``_EXPLICIT_PIN_REPIN_SOURCES``）。
#    本件不新增任何"凭空进档"的路：ML 名单外、好感度也未达档的人重启后照旧普通档
#    ——要她先说话把自动腿叫醒，才有"沿用"这回事。
# 3. **读写全 fail-open，且各自独立包 ``except``**：库坏掉时钉照旧上、回执照旧发。
#    ``apply_manual`` 返回 False 会让 ``apply_intimate_switch`` 的短路失效、把开关
#    指令当成普通聊天去回答——"记不住"绝不能升级成"这一轮炸掉"。
# 4. **配置没点名这本库 ⇒ 整条持久化腿不存在**（逐字节回到今天）：真 ``Config`` 恒有
#    该字段故生产恒开；纯离线引擎单测的 SimpleNamespace 没这一枚，于是不 import
#    providers、不碰 sqlite，``本模块不导入 NoneBot/LLM 栈`` 的模块承诺照旧成立。
# 5. **线程口径**：本模块全部公开方法由 ``pipeline.offload_capability`` 送进有界线程池
#    （``run_in_executor``）执行，不在事件循环上；且每次触碰都是按主键的单行 SELECT /
#    UPSERT，读只在"自动腿要上钉"那一刻发生（同一人每小时至多一次），写只在开关命令
#    上发生 ⇒ 不构成事件循环线程上的重 IO，也不为此另起 executor。
# 6. **同一进程内不沿用**（``_MARKS_WRITTEN_BY_THIS_PROCESS``）：本进程亲手写过的标记
#    不再被"沿用"第二遍。这条不是省事——它把这条腿的权威范围钉死在**跨进程**＝用户
#    裁定的原话"活过重启"上：同一进程里内存那枚钉才是权威，凭库里的旧格子在同一进程内
#    二次放行，等于把"到点自动退出"改成"进程内永生"，也会让任何新建引擎实例的场合
#    （测试、将来的第二具路由器）读到别人在飞的标记。锁 ``tests/test_intimate_pin_persistence.py``
#    的 ``test_same_process_never_re_honors_a_mark_it_wrote``。
# 7. **并号已接（E-1，2026-10-03 裁定「要」）**：她 `.env` 里那枚在册别名表
#    （``BOT_REPLY_POLICY_PERSON_ALIASES``，左号**并入**右号）接到标记这一侧 ⇒ 同一个人
#    换个号说话不必重开一次档。🔴 **归并算法不抄第二份**：判据仍只住本件，但真正跑的那段
#    是 ``character/reply_policy.py`` 里唯一的真身 ``ReplyPolicyStore.canonical_person_key``
#    （非绑定调用 + ``object.__new__`` 出来的**无连接**替身）⇒ 零 ``reply_policy.sqlite3``
#    连接、零 ``bot_reply_policy_enabled`` 总闸依赖、不新建库、不新增配置键。
#    方向性照既有语义：A→B 把 A 并进 B，B 是定点 ⇒ 「A 开、B 恢复」与「B 开、A 恢复」
#    两侧同键；链式 A→B→C、自吞与环保护全由真身一处给（⇒ 规范化幂等，不造第三种键形）。
#    认不出别名／表写坏／任何异常 ⇒ **原样用**（fail-open 回今日行为）。读写两侧都只经
#    ``_explicit_pin_person_key`` 这一口取键 ⇒ 不会"写在 A 键、读在 B 键"（台账 #33★／T-1
#    那族"两形永不相交"老坑）。脏归并目标（空／``unknown``）当"没并"处理：宁可不并，
#    也绝不把两个陌生人抬进同一只桶。🔴 **权限面一律不读本表**（并号只并"标记存到哪一行"，
#    不并权限主体；口径锁 ``test_person_aliases_never_leak_into_privilege``）。

# 哪些来源在**重钉**那一刻要查一次持久化标记：只有两支自动腿。显式腿自己就是标记的
# 生产者（不查、只写），``admin_pin`` 的键是群作用域键（被上面第 1 条的键门挡掉）。
# 这是第四张来源集合，与 `_MODEL_SWITCH_SOURCES` / `_MAX_TTL_EXEMPT_SOURCES` /
# `_INTIMATE_NARRATION_SOURCES` 同族不同轴——**不许互相复用**（复用＝一条裁定静默
# 改写另一条，09-28 她立过的那条「换了个档结果文风全变了」）。
_EXPLICIT_PIN_REPIN_SOURCES: frozenset[str] = frozenset(
    {INTIMATE_SOURCE_MASTER_LOVE, INTIMATE_SOURCE_AFFINITY}
)

# 标记行的作用域三元组里那两个固定段：只持久化私聊，故 session_type 恒为 ``private``、
# session_id 恒为空串——与 ``/bot identity`` 私聊写入侧的键位逐字相同（那里也是
# 「群=群号、私聊=空」），所以同一个人的显式声明落在同一行上。
_EXPLICIT_PIN_SESSION_TYPE: str = "private"
_EXPLICIT_PIN_SESSION_ID: str = ""

# **本进程**写过哪些人的标记（模块级＝跨引擎实例共享；上限沿用 ``_SESSION_CAP`` 的
# 同款防泄漏纪律）。它回答的是"这枚标记是不是上一个进程留下的"：
# 标记的唯一权威是**跨重启**——同一进程内她亲手写过一次，内存里那枚钉就是权威，
# 不该再拿库里的凭据去"沿用"第二遍（那会把"到点自动退出"变成进程内永生，也会让
# 任何新建引擎实例的场合读到别人的在飞标记）。所以写记一笔、读先问一句。
_MARKS_WRITTEN_BY_THIS_PROCESS: OrderedDict[str, None] = OrderedDict()
_MARKS_WRITTEN_LOCK = threading.Lock()


def _note_mark_written(person_key: str) -> None:
    with _MARKS_WRITTEN_LOCK:
        _MARKS_WRITTEN_BY_THIS_PROCESS[person_key] = None
        _MARKS_WRITTEN_BY_THIS_PROCESS.move_to_end(person_key)
        while len(_MARKS_WRITTEN_BY_THIS_PROCESS) > _SESSION_CAP:
            _MARKS_WRITTEN_BY_THIS_PROCESS.popitem(last=False)


def _mark_written_by_this_process(person_key: str) -> bool:
    with _MARKS_WRITTEN_LOCK:
        return person_key in _MARKS_WRITTEN_BY_THIS_PROCESS


def _canonical_person_key(person_key: str, config: Any) -> str:
    """把一个人的多个号并成同一把键（**归并算法零第二份真身**，见本节边界第 7 条）。

    这里只做两件事：把 Config 那枚**已在册**的别名字段交出去、把归并结果收回来。
    链式／自吞／环保护一律由 ``ReplyPolicyStore.canonical_person_key``（全仓唯一真身）判：

    - 非绑定调用 + ``object.__new__`` 出来的替身 ⇒ 跳过 ``__post_init__``，于是
      **不打 ``reply_policy.sqlite3``、不吃 ``bot_reply_policy_enabled`` 总闸**
      （为了取一枚纯字符串函数去开另一本库的连接，是本案付不起的代价）；
    - 懒 import：``character/reply_policy`` 牵进策略栈，只在配置真给了别名表时才要它
      （文件头那句模块承诺照旧成立）；
    - 认不出／表写坏／任何异常 ⇒ 原样返回＝逐字节回到并号之前的行为（fail-open）。
    """
    raw = str(person_key or "")
    if not raw.strip():
        return raw
    try:
        aliases = getattr(config, "bot_reply_policy_person_aliases", None) or {}
        if not isinstance(aliases, Mapping):
            return raw  # 表不是映射（配置写坏）＝不并号。
        table = {str(k).strip(): v for k, v in aliases.items() if str(k or "").strip()}
        if not table:
            return raw
        from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
            ReplyPolicyStore,
        )

        view: Any = object.__new__(ReplyPolicyStore)
        view.person_aliases = table
        resolved = str(ReplyPolicyStore.canonical_person_key(view, raw) or "")
    except Exception:  # noqa: BLE001 - fail-open：并不上号就用回原键，绝不影响本轮钉。
        return raw
    if resolved == raw:
        return raw
    # 中央件把"空／脏标识符"兜底成 ``unknown``：那种目标当没并（否则两个都配上脏别名的人
    # 会被抬进同一只桶＝串档，比不并号严重得多）。
    if not resolved or resolved == UNKNOWN_SENDER:
        return raw
    return resolved


def _explicit_pin_person_key(session_key: str, config: Any = None) -> str:
    """会话键 → 可持久化标记的本人键；不属本波面（群键/成员键/空键）一律回空串。

    ⚠ 交出的是**会话键本身**（``parse_session_key`` 的归一形，QQ 私聊即裸 uid），
    不重拼、不反解出 ``user_id`` 段再走一遍 ``private_session_key``：内存里的钉就住
    这把桶，重启后要回到同一只桶才叫"沿用"。反解会把 TG 的 ``private_<chat.id>`` 与
    QQ 的裸 ``<uid>`` 折成同一段（跨平台同号互串），那既不是中央件的口径也不是本波要
    修的事。群作用域键（``group:<gid>``）与成员派生键（含 ``||u:``）在 ``KIND_PRIVATE``
    这一门外侧就被挡掉，判据只住中央件 ``parse_session_key`` 一处。

    末了一道**并号**（``config`` 缺席＝不并，逐字节回到旧行为）：同一个人的多个号收成
    同一把键，读写都从这里出 ⇒ 标记只可能有一行。
    """
    parsed = parse_session_key(session_key)
    if parsed.kind != KIND_PRIVATE or not parsed.user_id:
        return ""
    if _MEMBER_SCOPE_SEP in parsed.normalized:
        return ""
    return _canonical_person_key(parsed.normalized, config)


#: 称谓偏好库那枚配置键的**键名**（真身＝``config.py`` 字段声明与 ``PATH_REMAPPED_FIELDS``
#: 名册；本文件只拿它去问中央解析口，**不落任何路径值**，路径缺省只住 config 一处）。
#: 与 ``character/providers.py`` 用的是同一个键名——两处都只认名字、不认落点。
_ADDRESSING_PREFERENCES_FIELD = "bot_addressing_preferences_db_path"


def _explicit_pin_store(config: Any) -> Any:
    """标记所在的 per-person store（**复用进程级共享实例**，零第二连接、零第二把锁）。

    懒 import：``providers`` 会牵进 NoneBot/LLM 栈，只在配置真点名了这本库时才要它
    （见上面边界第 4 条）。任何失败回 None＝这条腿本轮不存在。

    取径那几枚（席 remapseam，台账 P1 H-1／F-10）：判"这枚配置点没点这本库"**不再**用裸
    ``getattr`` 拿字段原值，改问 ``config.resolve_runtime_data_field`` 那一处中央解析口
    ——与 ``character/providers`` 的 store 取径同一把尺（两处各写一份时，"字段在册就安全"
    这种假设一旦不成立，源码树就会在全量测试期间长出运行库＝10-02/10-04/10-05 三次现场）。
    """
    from plugins.bot_unified_runtime.config import resolve_runtime_data_field
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        build_addressing_preference_store,
    )

    if not resolve_runtime_data_field(config, _ADDRESSING_PREFERENCES_FIELD):
        return None
    return build_addressing_preference_store(config)


# ---------------------------------------------------------------- 描写档的钉（G-1～G-3）
#
# 裁定：描写档是**每人的持久钉**，缺省 ``speech``，``scene`` 走 G-2 那把唯一的授予尺。
# 本节只做四件事，全都不长新账：
#
# - **存哪**：与 D-1 显式开档标记**同一行**（``addressing_preferences`` 的
#   ``_EXPLICIT_PIN_SESSION_TYPE`` / ``_EXPLICIT_PIN_SESSION_ID`` 那一把三元组，
#   owner `character/addressing.py`，两列 ALTER-if-missing）——同一个"他自己声明过的
#   相处面"，不新建库、不加 ``BOT_*`` 键、不加第三张来源集合表。取 store 只经既有
#   `_explicit_pin_store` 这一口（进程级共享、零第二连接）。
# - **按谁**：`_narration_person_key` 是全仓唯一的取键口（读写同口 ⇒ 不会"写在 A 读在 B"，
#   #33★/#68★ 那族"两形永不相交"的老坑）。键形**只准**出自中央件
#   `session_keys.person_scope_key(平台域, 用户号)`（T-1 那条裁定的构造侧真身），平台写法
#   归一只准用 `policy/roles.platform_domain_of`（本文件不写第四张别名表）；本人段先取
#   `sender_id`，缺席才**拆**既有成员段（`split_member_session_key`／中央件
#   `parse_session_key` 的 user_id 段）——**绝不**把拆出来的段经 `private_session_key`
#   重拼成裸号（席 na-review B-1 的成因：TG 群键 `group_-1001_<uid>` 与 QQ 私聊裸键
#   `<uid>` 会折成同一段＝两个平台上同号的陌生人共用一枚钉、谁也清不掉自己那枚）。
#   平台事实**拿不到**时 fail-closed：只认 D-1 那一口（私聊会话键本身），群侧/成员键一律
#   回空串＝这条腿本轮不存在，绝不把"未知平台"当通配去同时匹配两侧。
#   并号仍走 `_canonical_person_key` 那一枚真身。⇒ **钉按人不按群**（G-3 的实现面：
#   群作用域键 `group:<gid>` 压根没有本人段，读不出任何钉，所以管理员替整群拨的亲密档
#   绝不广播描写档）。⚠ 但"按人"**不等于**"全局跟人走"：完整键形还有会话那一段
#   （`_narration_store_scope`，I-2 裁定「换了会话就需要重新激发」）——人是这把锁的第二齿，
#   不是唯一一齿。
# - **谁能写**：`narration_write_allowed`——判据只这一枚（命令面只调它、不抄角色集合）。
#   群侧要 admin/super_admin（与 `_manual_command_scope_key` 的管理员分支同一个角色面：
#   群里"只有她自己开的"才算，普通成员恒 ``speech``）；非群侧本人自助，不吃角色门
#   （G-3 收的是群侧，不是将整条命令关在管理员屋里；口径同 #66「自助偏好仅本人」）。
# - **怎么判**：`_narration_axis_reading` 交出 ``(mode, source)`` 两格，优先级
#   ①本轮明示 → ②本人持久钉（钉 speech 也算表态）→ ③亲密缺省（H-1＝甲，2026-10-04 晚
#   「开'亲密'的话，就给 scene 场景」）→ ④缺省 ``speech``。**授予判据仍只在
#   `grants_intimate_narration` 那一处**——本节一次都不调它，调用方拿
#   ``grants_intimate_narration(narration_source)`` 就是唯一那一条路（无第二把尺）；
#   ③只**选缺省**、不放宽授予：自动腿那两支（`master_love`／`affinity_tier`）交不进来源。
#   ⚠ 模式必须**编码进来源**：``scene`` 交出授予集里那枚**新**来源
#   （①②都记 `narration_pin`，绝不借用 `manual_command`——那枚是"亲密档
#   怎么进来的"，借它等于没裁定就放宽授予，见 `_narration_axis_reading`）；③交出的是
#   **她那一句"开亲密"自己的来源**（她的裁定把那句的效果定义成"同时给 scene"，
#   如实记下≠借光；①②那条负面清单管的是"本轮说了描写"那一格），
#   ``speech`` 交出 `INTIMATE_SOURCE_NONE`。
#   反过来说＝"来源同一枚、授予却看模式"就是长了第二把尺，正是要防的那件事。
# - **没有 TTL**（与紧挨着它的亲密档标记**不同**）：描写档钉一直活到本人 ``reset``，
#   因为它是文风偏好而不是放行授权；`intimate_ttl_minutes` 管不到它，也不该管它。
# - **全腿 fail-open**：读不到＝当没钉（落缺省 ``speech``＝少写，不是多写）；
#   写失败**不改变本轮判定**（落库坏掉时那句明示照样生效，下一轮照旧回到钉的原值）。
# - **线程口径**：与上面 D-1 那一节同——公开入口都在 `pipeline.offload_capability`
#   的线程池里跑，每次触碰都是按主键的单行 SELECT/UPSERT；读发生在每轮合成
#   `resolve_intimate_context` 时（一人一轮一行），写只发生在命令面上。


def _narration_platform_domain(platform: Any) -> str:
    """平台写法 → 平台域（唯一归一器＝`policy/roles.platform_domain_of`，本文件不另立表）。

    认不出／拿不到／任何异常 ⇒ ``""``＝**fail-closed**：未知平台不继承任何已知平台的归属
    数据（在册口径 `project-platform-scoped-privilege-judgment`，与 `resolve_roles` 同一把尺）。
    懒 import：`policy/roles` 牵进 config/contracts 栈，只在真要取键时才要它（本模块
    "不导入 NoneBot/LLM 栈"的头部承诺照旧成立），口径同 `narration_write_allowed`。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
            platform_domain_of,
        )

        return platform_domain_of(platform)
    except Exception:  # noqa: BLE001 - 认不出平台域＝不放开（宁可读不到钉）。
        return ""


def _narration_person_uid(session_key: str, sender_id: str = "") -> str:
    """本人段（**拆**而不**拼**）：先 `sender_id`，缺席才拆成员段／中央件 user_id 段。

    ``||u:`` 段若不去掉，中央件会把"456||u:456"整个当 user_id 交回来，所以成员派生键先过
    `split_member_session_key`。``unknown`` 兜底段一律当"没有这个人"，绝不把两个陌生人
    抬进同一只桶。群作用域键（``group:<gid>``）没有本人段 ⇒ 空串，这正是 G-3 的落点。
    """
    uid = str(sender_id or "").strip()
    if not uid:
        split = split_member_session_key(session_key)
        uid = split[1] if split is not None else parse_session_key(session_key).user_id
    if not uid or uid == UNKNOWN_SENDER:
        return ""
    return uid


def _narration_person_key(
    session_key: str,
    sender_id: str = "",
    config: Any = None,
    *,
    platform: Any = "",
) -> str:
    """会话键（＋发送者号＋**平台事实**）→ 描写档钉的本人键；拿不到本人段一律回空串。

    两支，次序是刻意的：

    ① **平台域认得出来**（接线面交了 `message.platform`）⇒ 键形只出自中央件
    `person_scope_key(域, 用户号)`：私聊与群侧因此折进**同一个人**那一格（B-2 的推论——
    她在 TG 私聊钉的档，她自己在 TG 群里也读得到），而 QQ 的同号者落在另一只桶
    （B-1 就此闭合：跨平台同号既互不可见，也各自 reset 得掉自己的）。
    ② **平台域认不出来**（缺省调用面／合成消息／未接线的读点）⇒ 绝不反解：回落到 D-1
    那一口 `_explicit_pin_person_key`，只认私聊会话键本身，群侧/成员键一律空串。
    🔴 这里**不许**用空域段兜底（`person_scope_key("", uid)` 会把两个都拿不到平台事实的
    陌生人重新折进同一只 ``":<uid>"`` 桶＝换个姿势复发 B-1），也不许让"未知"当通配。

    末了一道**并号**（`config` 缺席＝不并）：同一个人的多个号收成同一把键，读写都从这里出。
    """
    uid = _narration_person_uid(session_key, sender_id)
    domain = _narration_platform_domain(platform)
    if domain:
        if not uid:
            return ""
        return _canonical_person_key(person_scope_key(domain, uid), config)
    return _explicit_pin_person_key(session_key, config)


#: 公共空间会话面（用户 2026-10-06 裁「telegram：群侧」）：`channel`（Telegram 频道/超级组，
#: 键形 `channel_<chat.id>`；QQ 频道另形 `guild_<g>_channel_<c>_<u>`）与 `group` **同侧**。
#: 判据只这一枚，三处共用：写腿角色门、I-2 的会话齿、I-3 的"群里不落笔身形衣着"界线——
#: 各写一份就是第二把尺。取值只认契约字段 `IncomingMessage.session_type` 的规范形
#: （`contracts/runtime.py:SessionType.CHANNEL="channel"`），**不靠会话键前缀猜**
#: （中央件 docstring 第 4 条：`guild_/friend_/console_` 诸形一律不判，字符串前缀不是判据）。
PUBLIC_SPACE_SESSION_TYPES: Final[frozenset[str]] = frozenset({"group", "channel"})


def is_public_space_session(session_type: Any) -> bool:
    """这一轮是不是"旁人也在看"的公共空间会话（群侧的统一判据，唯一出处）。"""
    return str(session_type or "").strip().lower() in PUBLIC_SPACE_SESSION_TYPES


def narration_write_allowed(*, session_type: str, sender_roles: Any) -> bool:
    """描写档**写腿**的作用域门（唯一判据处；命令面只准调它，不许自己抄角色集合）。

    群侧（含 2026-10-06 归进来的 `channel`）要 admin/super_admin；私聊/控制台本人自助。
    """
    if not is_public_space_session(session_type):
        return True  # 非公共空间＝本人自助（G-3 只收群侧）
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
            ROLE_ADMIN,
            ROLE_SUPER_ADMIN,
        )

        roles = {str(role).strip().lower() for role in (sender_roles or [])}
    except Exception:  # noqa: BLE001 - 认不出角色面＝不放开（宁缺毋滥）
        return False
    return bool(roles & {ROLE_ADMIN, ROLE_SUPER_ADMIN})


def _narration_store_scope(session_key: str, session_type: str = "") -> tuple[str, str]:
    """描写钉三元组里的**会话段** `(session_type, session_id)`（I-2，2026-10-04 21:0x 裁定）。

    她原话：「'跟着人走'的意思就是，在这个会话里面跟着这个人走……换了会话就需要重新激发。
    比如在群 A 用户 A 说'开场景模式'；到了群 B，用户 A 就还得再问一次、再开一次。」
    ⇒ 钉的完整键形＝**(平台域, 会话, 这个人)**：人那一条腿住 `_narration_person_key`，
    会话这一条腿就是本函数，两腿缺一即"开一次处处跟随"或"同群两人同等待遇"。
    落点选库里**已有的** `(session_type, session_id)` 两列（表的主键本来就是这三段），
    零新表零新列；键形只准出自中央件：成员派生键先 `split_member_session_key` **拆**出基键
    （读点交进来的是 `route_key`），再 `parse_session_key` 认形，禁自拼第四形。

    - 群 ⇒ ``("group", 群号)``：同一个人换群＝换桶（她要的"重开一次"）。
    - 频道 ⇒ ``("channel", 该频道会话键)``（用户 2026-10-06 裁「telegram：群侧」）：
      一个频道一把桶，频道之间、频道与私聊之间**都不同桶**。认形以契约字段
      `session_type` 为正解（中央件对 `channel_/guild_` 诸形明写"不判"，见
      `session_keys` docstring 第 4 条）；只有拿不到契约字段时才退到**前缀 fallback**——
      那一退的方向是 fail-closed（宁可多分一刀桶，也绝不把公共空间的钉折进私聊那一格）。
    - 私聊／控制台／认不出 ⇒ 沿用 ``("private", "")`` 那一格：私聊这一路"会话"就是这个人，
      键形不必变 ⇒ **她私聊里已有的钉原地不动，零迁移**。
    """
    key = str(session_key or "")
    split = split_member_session_key(key)
    if split is not None:
        key = split[0]
    st = str(session_type or "").strip().lower()
    parsed = parse_session_key(key)
    if parsed.kind == KIND_GROUP and parsed.group_id:
        return "group", str(parsed.group_id)
    if st == "channel" or (not st and key.lower().startswith("channel_")):
        return "channel", sanitize_key_segment(key, forbidden=_MEMBER_SCOPE_SEP)[:128]
    return _EXPLICIT_PIN_SESSION_TYPE, _EXPLICIT_PIN_SESSION_ID


def read_narration_pin(
    session_key: str,
    *,
    sender_id: str = "",
    config: Any = None,
    platform: Any = "",
    conversation_type: str = "",
) -> str:
    """库里有哪枚描写档钉（``""``＝没钉过／读不出／没配这本库）；原样交回、不猜档。

    合法性由调用方在**读出来之后**再认一次（`NARRATION_MODES` 那一处词表），与
    `get_intimate_pin` 同一口径 ⇒ 存储层不含判据。`platform`＝平台事实（缺席＝取键口
    fail-closed，见 `_narration_person_key`）。
    """
    try:
        person_key = _narration_person_key(session_key, sender_id, config, platform=platform)
        if not person_key:
            return ""
        store = _explicit_pin_store(config)
        if store is None:
            return ""
        session_type, session_id = _narration_store_scope(session_key, conversation_type)
        mode, _updated_at = store.get_narration_pin(
            session_type=session_type,
            session_id=session_id,
            sender_id=person_key,
        )
    except Exception:  # noqa: BLE001 - 读不到＝当没钉，落缺省。
        return ""
    return mode


def write_narration_pin(
    session_key: str,
    *,
    mode: str,
    sender_id: str = "",
    config: Any = None,
    platform: Any = "",
    conversation_type: str = "",
) -> bool:
    """钉下「此人要 ``mode`` 这一格描写」（覆盖旧值；时刻取墙钟）。轴外的值拒收。

    键**恒随"那个会话里的那个人"**走（会话段＝`_narration_store_scope`，人段＝
    `sender_id`／会话键的本人段），不随调用方是谁——所以"管理员替旁人钉"落的是旁人
    在**该会话**里的那一格，绝不会像 T-1 那样悄悄落回操作者自己名下。
    """
    if mode not in NARRATION_MODES:
        return False
    try:
        person_key = _narration_person_key(session_key, sender_id, config, platform=platform)
        if not person_key:
            return False
        store = _explicit_pin_store(config)
        if store is None:
            return False
        session_type, session_id = _narration_store_scope(session_key, conversation_type)
        store.set_narration_pin(
            session_type=session_type,
            session_id=session_id,
            sender_id=person_key,
            mode=mode,
            updated_at=float(time.time()),
        )
    except Exception:  # noqa: BLE001 - 记不住也不影响本轮已定的判定。
        return False
    return True


def clear_narration_pin(
    session_key: str,
    *,
    sender_id: str = "",
    config: Any = None,
    platform: Any = "",
    conversation_type: str = "",
) -> bool:
    """收回钉（``reset``）：只清那两格，**不删整行**（称谓／性别自述／关系档不是这条指令说过的话）。

    会话段与写腿**同轴**（`_narration_store_scope`）：不同轴的话，"在群 B reset"会去清
    私聊那一格、群里她那句「别铺开了」当场失效＝写了收不掉的一族（I-2 同批）。
    """
    try:
        person_key = _narration_person_key(session_key, sender_id, config, platform=platform)
        if not person_key:
            return False
        store = _explicit_pin_store(config)
        if store is None:
            return False
        session_type, session_id = _narration_store_scope(session_key, conversation_type)
        store.clear_narration_pin(
            session_type=session_type,
            session_id=session_id,
            sender_id=person_key,
        )
    except Exception:  # noqa: BLE001 - fail-open。
        return False
    return True


def _narration_axis_reading(
    *,
    session_key: str,
    sender_id: str = "",
    config: Any = None,
    turn_narration_mode: Any = "",
    platform: Any = "",
    intimate_scene_source: str = "",
    session_type: str = "",
) -> tuple[str, str]:
    """优先级四格 → ``(narration_mode, narration_source)``；授予与否由调用方问唯一那把尺。

    ①本轮明示（调用方刚认下来的那句，走开关面同一条"本轮"路径）；②本人持久钉（**两格都
    算表态**：钉 scene 交出 scene，钉 speech 交出 speech——H-1＝甲 之后"没表态"与"表态
    只说话"必须分得开，否则她那句 `/bot 描写 speech` 会被下面的亲密缺省顶掉）；
    ③亲密缺省（H-1＝甲，2026-10-04 晚裁定「开'亲密'的话，就给 scene 场景」：亲手把亲密档
    推上去的那一轮，没在描写轴上说过话也拿到 ``scene``）；④缺省 ``speech``。
    四格都只**转述**，本节一次都不调授予尺。
    🔴 ``scene`` 交出的来源必须在授予面上：①②两格交 `INTIMATE_SOURCE_NARRATION_PIN`，
    ③交调用方送来的**那一支亲密来源串本身**（`intimate_scene_source`，空串＝这一格不存在）。
    不许拿 `manual_command` **蒙混①②那一格**（2026-10-04 裁定 G-2 的负面清单，席 narrlock
    点名过的"假保证"）：本轮那句**说的是描写**，把它记成"她开了亲密"就把两件事混成一件事了；
    而③这一格答的**本来就不是描写**——她说的是"开亲密"，而她的裁定把这一句的效果定义成
    "同时给 scene"，所以这里交出她那句亲密的来源是**如实记录**，不是借光。
    🔴 ③**不放宽授予面**：那一格只在这份来源串已经在 `_INTIMATE_NARRATION_SOURCES` 里时
    才由调用方交进来（Master Love 名单派生／好感度达档自动都不在，故自动腿的亲密照旧
    只说话），而**最终授权仍只由唯一那把尺**在调用方判一次：`grants_intimate_narration(
    narration_source)`。本节读那张表**只为选缺省**，不产第二个"能不能写"的答案——
    尺若日后收紧，③交出的 scene 会在注入缝（`chat.py:resolve_narration_axis`）当场收回
    ``speech``＝fail-closed，不会长出第二通路。
    ``speech`` 交出 `INTIMATE_SOURCE_NONE`（白名单外＝不授予），于是"模式编码进来源"
    始终成立：**要问能不能铺开写，只准 `grants_intimate_narration(narration_source)`**，
    全仓不设第二条判据。
    本轮那一格**认不出＝不表态**（`normalize_narration_mode` 会落缺省，这里偏偏不能用
    它：拿缺省当"本轮说了"会把持久钉静默顶掉），所以直接对 `NARRATION_MODES` 判成员。
    """
    raw_turn = str(turn_narration_mode if turn_narration_mode is not None else "").strip().lower()
    if raw_turn in NARRATION_MODES:
        return (
            (raw_turn, INTIMATE_SOURCE_NARRATION_PIN)
            if raw_turn == NARRATION_MODE_SCENE
            else (raw_turn, INTIMATE_SOURCE_NONE)
        )
    pinned = read_narration_pin(
        session_key,
        sender_id=sender_id,
        config=config,
        platform=platform,
        conversation_type=session_type,
    )
    if pinned == NARRATION_MODE_SCENE:
        return NARRATION_MODE_SCENE, INTIMATE_SOURCE_NARRATION_PIN
    if pinned in NARRATION_MODES:
        # 钉过 speech＝她表过态（收回路），压过③那一格；库里漂出轴外的值不算表态。
        return NARRATION_MODE_SPEECH, INTIMATE_SOURCE_NONE
    if str(intimate_scene_source or "").strip():
        return NARRATION_MODE_SCENE, str(intimate_scene_source).strip()
    return NARRATION_MODE_DEFAULT, INTIMATE_SOURCE_NONE



# ---------------------------------------------------------------- 引擎


@dataclass
class _SessionState:
    score: float = 0.0
    pin: str | None = None  # MODE_INTIMATE | MODE_NORMAL | None
    last_mode: str = MODE_NORMAL
    updated: float = 0.0
    # v21r5：intimate 钉的激活时刻（TTL 起算点）。不随会话活动滑动——
    # 「1 小时后自动退出」按真实激活时刻计；重新开启（apply_manual）即重置。
    activated_at: float = 0.0
    # 2026-09-24 裁定：钉是**谁**上的（"为什么亲密"的唯一记录处）。
    # 只在 `apply_manual` 那一刻由调用方交出，此后无人再判一次。
    pin_source: str = INTIMATE_SOURCE_NONE
    # 同日裁定 R3：档还分**深浅**（`INTIMATE_TIER_*`）。空串=没记档，按来源派生
    # （`_tier_for_source`），保证未升级的调用点与旧在飞状态行为逐字节不变。
    pin_tier: str = INTIMATE_TIER_NONE


def _pin_source(state: _SessionState) -> str:
    """ intimate 钉的来源读数（唯一取数口）。

    未记来源的 intimate 钉按 ``manual_command`` 处理=本裁定之前的行为逐字节一致：
    只有**新的** ML 自动钉会被交上 `master_love` 标签（chat 主链那唯一一处上钉点），
    任何第三方/旧状态都不会因为"来源不明"而被削掉在册的头插。
    """
    return state.pin_source or INTIMATE_SOURCE_MANUAL


def _pin_tier(state: _SessionState) -> str:
    """ intimate 钉的档位读数（唯一取数口）：没记档就按来源派生缺省档。"""
    return state.pin_tier or _tier_for_source(_pin_source(state))


def _is_whole_group_bucket(key: Any) -> bool:
    """这把键**自己就是**整群共享桶吗（一把桶对全群所有人，不区分发言者）。

    构造只准经中央件 ``session_keys.group_scope_key``——与写侧（管理员上钉）和
    查钉侧（``_group_pin_state``）同一个真身，判"是不是全群那一桶"不许长第二形。
    🔴 但**必须先认成员段**：``group_scope_key`` 对 ``group:<gid>||u:a`` 是原样回吐
    （它把 ``||u:`` 之后的整段当成群号，拆不出第二层），只比"收拢后等不等自己"会把
    **本人那一桶**误判成全群桶（实测：`test_group_member_command_scopes_to_self` 因此
    把亲手说了「亲密模式 开」的 A 自己关回 speech＝少写她要点的那一格）。判据两句：
    带 ``_MEMBER_SCOPE_SEP`` ⇒ 那是"这个人"的桶；其余形态收拢后与自身相等 ⇒ 全群桶
    （``group:<gid>``、per_user 关闭时路由直接读的那把键）；逐成员下划线形 ``group_<gid>_<uid>``
    与私聊/控制台键一律判否。
    """
    text = str(key or "")
    if not text or _MEMBER_SCOPE_SEP in text:
        return False
    scoped = group_scope_key(text)
    return bool(scoped) and scoped == text


def _synchronized(method: Any) -> Any:
    """把公开方法的「读态→改态→写回」整段钉在同一把可重入锁内（D1-7）。

    用装饰器而非逐方法 ``with`` 包裹：零重排缩进＝diff 最小，且新增公开方法时
    只需加一行标记，不会漏掉某条路径。可重入（``RLock``）是因为这些方法内部
    会再调 ``_state``，而 ``_state`` 是唯一真正触碰 ``_sessions`` 结构的地方。
    """

    @functools.wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    # 标记挂在 Any 别名上：给 functools 包出来的函数对象直接设属性，mypy 会按
    # _Wrapped 的推断判「该类型无此属性」（attr-defined），而这里确实在设、也确实要它留着。
    marked: Any = wrapped
    marked.__content_route_locked__ = True  # 回归锁据此判定「是否真上了锁」
    return wrapped


class ContentRouteEngine:
    """会话亲密度分数机：observe_turn（L1/L2/衰减）→ route_verdict（滞回）
    → consume_reply（标签解析/剥离）。所有方法 fail-open。

    线程口径（2026-09-21 深读波 D1-7）：本类的进程级单例
    ``SHARED_CONTENT_ROUTE_ENGINE`` 被 chat 能力在**线程池**里并发触碰
    （``pipeline.offload_capability`` 用有界 ``ThreadPoolExecutor``，且同文件
    pipeline 自陈「管线能力跑在线程池，读写必须持锁」）。``_state`` 会对同一
    ``OrderedDict`` 做插入 / ``move_to_end`` / ``popitem`` 三类结构变更，公开方法
    还要「取态→改分数→写回」，全部无锁即与同层三处共享态的既有纪律不一致
    （``base_router._ROUTE_CACHE`` 带 ``_ROUTE_CACHE_LOCK``、group_cache、parrot
    各持一把锁）。``fail_open`` 会把竞态炸出的 ``RuntimeError`` 吞成「静默漏判
    亲密路由」，比崩溃更难发现 ⇒ 公开方法整段上同一把可重入锁。
    """

    def __init__(self, clock: Any = None, *, wall_clock: Any = None) -> None:
        self.clock = clock or time.monotonic
        # 跨重启标记专用的**墙钟**缝（epoch 秒）。不能复用 ``self.clock``：
        # ``time.monotonic`` 跨进程不可比，而那正是这块格子的唯一用途。
        # 测试从这里注入"距首次显式开启多久"，不靠 sleep。
        self.wall_clock = wall_clock or time.time
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()
        # v21r5 MINOR-SWEEP（终审 B-Minor-3）：擦边词槽位退役后缓存收为一元。
        self._extra_words_cache: tuple[str, re.Pattern[str] | None] | None = None

    # ---- 配置读取（reaction_knobs 惯例：getattr 缺省，兼容热覆盖视图） ----

    def _knobs(self, config: Any) -> dict[str, Any]:
        return {
            "enabled": bool(getattr(config, "bot_content_route_enabled", True)),
            "model": str(getattr(config, "bot_content_route_model", "") or "grok-4.6").strip(),
            "order": [
                piece.strip()
                for piece in str(getattr(config, "bot_content_route_order", "") or "").split(",")
                if piece.strip()
            ],
            "intimate_threshold": float(getattr(config, "bot_content_route_intimate_threshold", 60.0)),
            "normal_threshold": float(getattr(config, "bot_content_route_normal_threshold", 25.0)),
            "context_turns": max(1, int(getattr(config, "bot_content_route_context_turns", 4))),
            "max_ttl_minutes": float(getattr(config, "bot_content_route_max_ttl_minutes", 120)),
            "intimate_ttl_minutes": float(
                getattr(config, "bot_content_route_intimate_ttl_minutes", 60)
            ),
            "idle_reset_minutes": float(getattr(config, "bot_content_route_idle_reset_minutes", 10)),
            # L1 自动腿（R1 A）：好感度达该档号及以上 ⇒ 自动进浅档。八档 id 是 -4..+3
            # （真身 `character/affinity.py` 的 ``_ATTITUDE_TIERS``），缺省 +1「亲近」。
            "l1_auto_enabled": bool(
                getattr(config, "bot_content_route_l1_auto_enabled", True)
            ),
            "l1_auto_min_tier": int(
                getattr(config, "bot_content_route_l1_auto_min_tier", 1)
            ),
        }

    def _extra_patterns(self, config: Any) -> re.Pattern[str] | None:
        """强词正则（L1 词表+配置追加词）。v21r5 MINOR-SWEEP（终审 B-Minor-3）：
        擦边词槽位已退役（_borderline_retired 第二元恒 None），返回收为一元。"""
        raw = str(getattr(config, "bot_content_route_words", "") or "")
        key = raw
        if self._extra_words_cache is not None and self._extra_words_cache[0] == key:
            return self._extra_words_cache[1]
        extra = list(_parse_extra_words(raw))
        strong_re = _compile_word_list(list(_STRONG_WORDS) + extra)
        self._extra_words_cache = (key, strong_re)
        return strong_re

    # ---- 状态存取 ----

    def _state(
        self,
        session_key: str,
        *,
        max_ttl_minutes: float,
        now: float,
        intimate_ttl_minutes: float = 60.0,
    ) -> _SessionState:
        state = self._sessions.get(session_key)
        if state is None:
            state = _SessionState(updated=now)
            self._sessions[session_key] = state
        else:
            self._sessions.move_to_end(session_key)
        if state.pin == MODE_INTIMATE and state.activated_at:
            # v21r5 用户裁定：亲密模式默认 1 小时自动退出——按激活时刻惰性
            # 过期（读取时判定），会话活跃不续期；重新开启即重置计时。
            # 群级钉（管理员全群开关）与个人级钉同一 TTL。
            ttl_sec = max(1.0, intimate_ttl_minutes * 60.0)
            if now - state.activated_at > ttl_sec:
                state.pin = None
                state.score = 0.0
                state.last_mode = MODE_NORMAL
                state.activated_at = 0.0
                # 来源随钉一起清：过期后的档是"没有档"，不得留下"曾经为什么亲密"的残影
                # （否则下一轮的观测面会读到上一个钉的来源）。
                state.pin_source = INTIMATE_SOURCE_NONE
        if (
            state.updated
            and now - state.updated > max(1.0, max_ttl_minutes * 60.0)
            and not (
                state.pin == MODE_INTIMATE and _pin_source(state) in _MAX_TTL_EXEMPT_SOURCES
            )
        ):
            # max_ttl 硬上限：无论 pin 与分数，超时一律重置（安全阀）。
            # 2026-09-24 R4 A 的唯一豁免面：显式开/管理员钉着的深档不受此封顶——
            # 它们由 `intimate_ttl_minutes` 自己管到多久就多久，不再被第二道上限
            # 悄悄截掉（改前把 TTL 配到 4 小时也会在第 120 分钟被清成普通档）。
            state.score = 0.0
            state.pin = None
            state.last_mode = MODE_NORMAL
            state.updated = now
            state.activated_at = 0.0
            state.pin_source = INTIMATE_SOURCE_NONE
        while len(self._sessions) > _SESSION_CAP:
            self._sessions.popitem(last=False)
        return state

    # ---- 转折点 1：每轮生成前（chat 链调用） ----

    @_synchronized
    def observe_turn(
        self,
        session_key: str,
        *,
        message_text: str,
        context_text: str = "",
        config: Any = None,
    ) -> None:
        """L1/L2 信号与干净轮衰减；无返回值，状态变化只体现在 verdict。"""
        try:
            knobs = self._knobs(config)
            if not knobs["enabled"] or not str(session_key or "").strip():
                return
            now = float(self.clock())
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            self._apply_signals(
                state,
                message_text=message_text,
                context_text=context_text,
                knobs=knobs,
                strong_re=self._extra_patterns(config),
                now=now,
            )
        except Exception:  # noqa: BLE001 - fail-open：信号失败不影响路由主链。
            return

    @staticmethod
    def _apply_signals(
        state: _SessionState,
        *,
        message_text: str,
        context_text: str,
        knobs: dict[str, Any],
        strong_re: re.Pattern[str] | None,
        now: float,
    ) -> None:
        """本轮信号如何改动分数——**记账与预览共用这一处**（`observe_turn` 真改，
        `verdict_with_pending_turn` 改在副本上）。判据不许有第二份。"""
        if state.pin is not None:
            state.updated = now
            return  # 钉死态不吃自动信号（解除只走 L4）。
        if state.updated and now - state.updated > max(1.0, knobs["idle_reset_minutes"] * 60.0):
            state.score = 0.0  # 会话间隔久=语境断裂，冷启动重评。
        text = str(message_text or "")
        delta = 0.0
        if strong_re is not None and strong_re.search(text):
            delta += 70.0
        if knobs["context_turns"] > 0 and str(context_text or "").strip():
            turns = [
                piece
                for piece in str(context_text).split("\n")
                if piece.strip()
            ][-knobs["context_turns"] * 2 :]
            context_blob = "\n".join(turns)
            if strong_re is not None and strong_re.search(context_blob):
                delta += 35.0
        if delta > 0.0:
            state.score = min(100.0, state.score + delta)
        else:
            state.score = max(0.0, state.score * 0.5)  # 干净轮自然衰减。
        state.updated = now

    @staticmethod
    def _decide(state: _SessionState, knobs: dict[str, Any]) -> tuple[str, str, str]:
        """滞回判定 → ``(mode, source, tier)``。钉→来源/档位读状态；无钉→分数。
        只读状态、不写（写回由调用方负责），这样预览可以在副本上用。"""
        if state.pin == MODE_INTIMATE:
            return MODE_INTIMATE, _pin_source(state), _pin_tier(state)
        if state.pin == MODE_NORMAL:
            return MODE_NORMAL, INTIMATE_SOURCE_NONE, INTIMATE_TIER_NONE
        if state.score >= knobs["intimate_threshold"]:
            # 自动信号档=R-18 在册通道（深档）：直切 grok，不在浅档面里。
            return MODE_INTIMATE, INTIMATE_SOURCE_CONTENT_SIGNAL, INTIMATE_TIER_L2
        if state.score <= knobs["normal_threshold"]:
            return MODE_NORMAL, INTIMATE_SOURCE_NONE, INTIMATE_TIER_NONE
        # 滞回带：保持前态防抖。前态是亲密而当前无钉 ⇒ 只能是更早的内容信号
        # 抬上去的档（钉死态在上面两支已被拦下），来源与档位随内容信号记。
        mode = state.last_mode
        if mode == MODE_INTIMATE:
            return MODE_INTIMATE, INTIMATE_SOURCE_CONTENT_SIGNAL, INTIMATE_TIER_L2
        return MODE_NORMAL, INTIMATE_SOURCE_NONE, INTIMATE_TIER_NONE


    # ---- 转折点 2：路由器读判定（ModelRouter content_route_cb 消费） ----

    @staticmethod
    def _intimate_head(knobs: dict[str, Any]) -> list[str]:
        """INTIMATE 候选头：route_model 首位 + order 其余（按注册表优先级，
        由 router 重排；绝不做 EWMA 延迟重置——回归锁见 test_content_route）。"""
        order = [knobs["model"], *[n for n in knobs["order"] if n != knobs["model"]]]
        seen: set[str] = set()
        head: list[str] = []
        for name in order:
            if name and name not in seen:
                seen.add(name)
                head.append(name)
        return head

    # ---- 群作用域钉（读侧唯一入口，T-1 修复 2026-09-27） ----

    def _group_pin_state(
        self, session_key: str, *, knobs: dict[str, Any], now: float
    ) -> _SessionState | None:
        """任意形态群键 → 已钉 intimate 的群作用域状态；无群钉返回 None。

        作用域键的构造只准经中央件 ``group_scope_key``——与写侧
        （``chat.py:_manual_command_scope_key`` 管理员分支）同一真身，读写
        从构造上不可能分叉。覆盖三种来键：

        - 成员派生键 ``X||u:Y`` → 拆出群键段 X 再收拢；
        - 逐成员下划线原始键 ``group_<gid>_<uid>`` → 直接收拢（per_user 关闭
          时路由读的就是这把键）；
        - 请求键本身就是整群作用域键（合成/开发态冒号形）→ 返回 None，
          交给个人档路径（那把键的 state 与自己同一桶，不重复查）。

        fail-safe：作用域键拆不出生成（非群形态）或消毒前遗留的嵌套形态
        （含分隔符）一律不查，宁少不增多。
        """
        key = str(session_key or "")
        scope = split_member_session_key(key)
        base = scope[0] if scope is not None else key
        pin_key = group_scope_key(base)
        if not pin_key or pin_key == key or _MEMBER_SCOPE_SEP in pin_key:
            return None
        state = self._state(
            pin_key,
            max_ttl_minutes=knobs["max_ttl_minutes"],
            intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
            now=now,
        )
        return state if state.pin == MODE_INTIMATE else None

    @_synchronized
    def route_verdict(self, session_key: str, config: Any = None) -> dict[str, Any]:
        """只读判定；返回 {"mode", "head_models", "source", "tier"}。

        mode="intimate" 且 **tier=L2** 且 ``source`` ∈ ``_MODEL_SWITCH_SOURCES`` →
        head_models=[route_model, *order 其余]（router 据此重排候选）；
        其余一切（normal 档、浅档 L1 的关系钉与好感度/ML 自动档）→ head_models=[]
        （默认链原样）。2026-09-24 两条裁定在这一个判据里合流：
        ①「Master Love 不得改变默认模型」⇒ 看 ``source``；
        ②「亲密模式分深浅，「开」只给浅档」⇒ 看 ``tier``。
        v21r5：成员派生键先查群级钉（管理员全群开关）——群 ON→全员 intimate；
        群 OFF 不压制成员个人档（开关一个人自主，设计裁定）。
        ``from_group_pin``：这一轮的亲密裁决**出自整群那一桶**（全群开关，或 per_user
        关闭时路由直接读的那把群键）。存在只为一条边界——描写轴③格「开亲密即给 scene」
        **不跟着广播**（G-3，2026-10-04 晚「别人找你依旧是 speech」）：本引擎只如实报
        "答案从哪把桶取的"，判不判广播住在 ``resolve_intimate_context``，此处不产第二个"能不能写"。
        """
        try:
            knobs = self._knobs(config)
            if not knobs["enabled"] or not str(session_key or "").strip():
                return {
                    "mode": MODE_NORMAL,
                    "head_models": [],
                    "source": INTIMATE_SOURCE_NONE,
                    "tier": INTIMATE_TIER_NONE,
                    "from_group_pin": False,
                }
            now = float(self.clock())
            group_state = self._group_pin_state(session_key, knobs=knobs, now=now)
            if group_state is not None:
                group_state.last_mode = MODE_INTIMATE
                group_state.updated = now
                group_source = _pin_source(group_state)
                group_tier = _pin_tier(group_state)
                return {
                    "mode": MODE_INTIMATE,
                    "head_models": self._head_if_switchable(
                        knobs, group_source, group_tier
                    ),
                    "source": group_source,
                    "tier": group_tier,
                    "from_group_pin": True,
                }
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            mode, source, tier = self._decide(state, knobs)
            state.last_mode = mode
            state.updated = now
            return {
                "mode": mode,
                "head_models": (
                    self._head_if_switchable(knobs, source, tier)
                    if mode == MODE_INTIMATE
                    else []
                ),
                "source": source,
                "tier": tier,
                "from_group_pin": _is_whole_group_bucket(session_key),
            }
        except Exception:  # noqa: BLE001 - fail-open。
            return {
                "mode": MODE_NORMAL,
                "head_models": [],
                "source": INTIMATE_SOURCE_NONE,
                "tier": INTIMATE_TIER_NONE,
                "from_group_pin": False,
            }

    @_synchronized
    def verdict_with_pending_turn(
        self,
        session_key: str,
        *,
        message_text: str,
        context_text: str = "",
        config: Any = None,
    ) -> dict[str, Any]:
        """**装配期**用的只读预览：把"本轮信号记完之后"的判定先给出来，但不落账。

        为什么需要它（2026-09-24 用户裁定 R6 A，闭那扇时序泄露窗）：媒体要不要转译
        在 `chat.py` 的装配段就定了，而真实记账/判定发生在之后的生成前段 ⇒
        "本轮强词刚跨过阈值 + 这条消息带语音/视频"那一窗里，装配按默认链首（gemini，
        有原生声明）挂了原生件，真实首跳却换成了 grok（零声明）⇒ 模型回了 200 却
        什么都没看见。预览让装配看得见自己即将面对的那一跳。

        只读承诺：信号与滞回走的是与 `observe_turn`/`route_verdict` **同一批助手**
        （`_apply_signals`/`_decide`），改的是 `dataclasses.replace` 出来的副本，
        真实状态一个字段都不动 ⇒ 等值锁见 `tests/test_intimate_tiers_v4.py`。
        """
        try:
            knobs = self._knobs(config)
            if not knobs["enabled"] or not str(session_key or "").strip():
                return {
                    "mode": MODE_NORMAL,
                    "head_models": [],
                    "source": INTIMATE_SOURCE_NONE,
                    "tier": INTIMATE_TIER_NONE,
                }
            now = float(self.clock())
            group_state = self._group_pin_state(session_key, knobs=knobs, now=now)
            if group_state is not None:
                # 群级钉短路：与 `route_verdict` 同一助手、同一构造，逐字段一致
                # （预览不许在"群钉在场"这一格与真实判定分叉）。预览只不记账：
                # 不动 last_mode/updated（`_group_pin_state` 内的 `_state` 惰性
                # 过期与既有预览对个人键的 `_state` 同一量级，非新增副作用种类）。
                group_source = _pin_source(group_state)
                group_tier = _pin_tier(group_state)
                return {
                    "mode": MODE_INTIMATE,
                    "head_models": self._head_if_switchable(
                        knobs, group_source, group_tier
                    ),
                    "source": group_source,
                    "tier": group_tier,
                }
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            probe = replace(state)
            self._apply_signals(
                probe,
                message_text=message_text,
                context_text=context_text,
                knobs=knobs,
                strong_re=self._extra_patterns(config),
                now=now,
            )
            mode, source, tier = self._decide(probe, knobs)
            probe.last_mode = mode  # 只改副本：滞回带的"前态"不被预览污染
            return {
                "mode": mode,
                "head_models": (
                    self._head_if_switchable(knobs, source, tier)
                    if mode == MODE_INTIMATE
                    else []
                ),
                "source": source,
                "tier": tier,
            }
        except Exception:  # noqa: BLE001 - fail-open：预览失败按普通档（保守侧）。
            return {
                "mode": MODE_NORMAL,
                "head_models": [],
                "source": INTIMATE_SOURCE_NONE,
                "tier": INTIMATE_TIER_NONE,
            }


    @classmethod
    def _head_if_switchable(
        cls, knobs: dict[str, Any], source: str, tier: str
    ) -> list[str]:
        """亲密档是否**有权换掉真实首跳**：判据只此一份（深浅 × 来源，两问同一处答）。"""
        if tier != INTIMATE_TIER_L2 or source not in _MODEL_SWITCH_SOURCES:
            return []
        return cls._intimate_head(knobs)


    # ---- 转折点 3：每轮生成后（chat 链调用） ----

    @_synchronized
    def consume_reply(self, session_key: str, reply_text: str, config: Any = None) -> tuple[str, str]:
        """解析并剥离回复开头的 <intimacy:high|low> 标记；返回 (干净文本, tag)。

        tag="high"→分数置满；"low"→×0.4 加速衰减；""（无标记）→不动作
        （observe_turn 的干净轮衰减已在生成前记账）。
        剥离后为空文本时保守返回原文（防把纯标记回复变成 empty_response）。
        """
        try:
            text = str(reply_text or "")
            match = _TAG_RE.match(text)
            if match is None:
                return text, ""
            tag = match.group(1)
            clean = text[match.end() :].lstrip()
            knobs = self._knobs(config)
            if str(session_key or "").strip():
                now = float(self.clock())
                state = self._state(
                    session_key,
                    max_ttl_minutes=knobs["max_ttl_minutes"],
                    intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                    now=now,
                )
                if state.pin is None:
                    if tag == "high":
                        state.score = 100.0
                        state.updated = now
                    elif tag == "low":
                        state.score = max(0.0, state.score * 0.4)
                        state.updated = now
            if not clean.strip():
                return text, ""  # 纯标记回复：保原文防误判空回复，不当信号。
            return clean, tag
        except Exception:  # noqa: BLE001 - fail-open。
            return str(reply_text or ""), ""

    # ---- L4 手动命令 ----

    @_synchronized
    def pinned_mode(self, session_key: str, config: Any = None) -> str | None:
        """只读窥探会话钉死态（"intimate"/"normal"/None）；fail-open None。

        Master Love 自动钉死用：显式「亲密模式 关」的 normal 钉不被覆盖。
        v21r5：成员键先查群级钉——群 ON→"intimate"（全员亲密）；群 OFF
        不压制成员个人钉（开关一个人自主，设计裁定）。
        """
        try:
            knobs = self._knobs(config)
            if not knobs["enabled"] or not str(session_key or "").strip():
                return None
            now = float(self.clock())
            if self._group_pin_state(session_key, knobs=knobs, now=now) is not None:
                return MODE_INTIMATE
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            return state.pin
        except Exception:  # noqa: BLE001 - fail-open。
            return None

    # ---- 显式开档标记的三条腿（读写判据只住本件，store 只当格子）----

    def _honored_explicit_pin(
        self,
        *,
        person_key: str,
        config: Any,
        knobs: dict[str, Any],
        now: float,
    ) -> tuple[str, str, float] | None:
        """自动腿重钉前查一次标记：该沿用则交出 ``(source, tier, activated_at)``。

        交出 ``None``＝今日行为照旧（没配置这本库 / 读不到 / 没标记 / 标记已过 TTL /
        这枚标记就是**本进程**刚写下的——那说明内存态才是权威，跨不了进程谈不上"沿用"）。
        回传的 ``activated_at`` 是**回填**值：新进程里的这枚钉只剩"首次显式开启起算的
        剩余窗口"，重启不再白送一整段 TTL（详见本节头边界段）。
        """
        if _mark_written_by_this_process(person_key):
            return None
        try:
            store = _explicit_pin_store(config)
            if store is None:
                return None
            stored_tier, explicit_at = store.get_intimate_pin(
                session_type=_EXPLICIT_PIN_SESSION_TYPE,
                session_id=_EXPLICIT_PIN_SESSION_ID,
                sender_id=person_key,
            )
        except Exception:  # noqa: BLE001 - fail-open：读不到＝没标记。
            return None
        if stored_tier not in {INTIMATE_TIER_L1, INTIMATE_TIER_L2}:
            return None  # 词表外的格子（脏值/旧版本写的）一律当没有，不猜档。
        if explicit_at <= 0.0:
            return None
        # 墙钟被往回调过（NTP/手工）⇒ 差值为负：按"刚开的"处理，不因此判死。
        elapsed = max(0.0, float(self.wall_clock()) - float(explicit_at))
        ttl_sec = max(1.0, float(knobs["intimate_ttl_minutes"]) * 60.0)
        if elapsed > ttl_sec:
            return None  # TTL 到了仍要清：标记不复活档，只回答"该以什么来源重钉"。
        # ⚠ 下限 1e-6 不是装饰：`_state` 的惰性过期那道门写的是
        # `if state.pin == MODE_INTIMATE and state.activated_at:`（0.0＝"没记激活时刻"），
        # 回填恰好落到 0.0 时整条 TTL 判据会被这个假值跳过 ⇒ 钉永不过期。
        return INTIMATE_SOURCE_MANUAL, stored_tier, max(now - elapsed, 1e-6)

    def _record_explicit_pin(self, *, person_key: str, config: Any, tier: str) -> None:
        """记下"本人亲手把亲密档开到 ``tier``"（覆盖旧值；时刻取墙钟）。"""
        try:
            store = _explicit_pin_store(config)
            if store is None:
                return
            store.set_intimate_pin(
                session_type=_EXPLICIT_PIN_SESSION_TYPE,
                session_id=_EXPLICIT_PIN_SESSION_ID,
                sender_id=person_key,
                tier=tier,
                explicit_at=float(self.wall_clock()),
            )
            # 落盘成功才记"本进程写过"：写失败时不该顺手把跨重启沿用也关掉。
            _note_mark_written(person_key)
        except Exception:  # noqa: BLE001 - fail-open：记不住也不影响本轮已生效的钉。
            return

    def _retract_explicit_pin(self, *, person_key: str, config: Any) -> None:
        """收回标记（本人显式「亲密模式 关」）。

        这一腿与记账腿**同批**才闭合：只清内存不清库的话，重启后自动腿会凭旧标记
        把她刚关掉的档再"沿用"回来——那等于把她的"关"字吃了。清的是那两格，
        **不删整行**（称谓／性别自述／关系档不是这条指令说过的东西）。
        """
        try:
            store = _explicit_pin_store(config)
            if store is None:
                return
            store.clear_intimate_pin(
                session_type=_EXPLICIT_PIN_SESSION_TYPE,
                session_id=_EXPLICIT_PIN_SESSION_ID,
                sender_id=person_key,
            )
        except Exception:  # noqa: BLE001 - fail-open。
            return

    @_synchronized
    def apply_manual(
        self,
        session_key: str,
        mode: str,
        config: Any = None,
        *,
        source: str = INTIMATE_SOURCE_MANUAL,
        tier: str = INTIMATE_TIER_NONE,
    ) -> bool:
        """钉死/解除会话状态；返回是否生效（fail-open False）。

        v21r5：钉 intimate 时记 ``activated_at``（TTL 起算，读取时惰性过期）；
        解除/normal 钉清零。重新开启即重置计时。
        2026-09-24 裁定：钉 intimate 时同时记**是谁上的钉**（``source``，见
        `INTIMATE_SOURCE_*`）与**上的是哪一档**（``tier``，见 `INTIMATE_TIER_*`）——
        档成立与"有权换默认模型"由此分开判。缺省 ``manual_command`` + 空档位
        让既有调用面（含"本人显式开"改道之前的语义）逐字节不变：档位没交时
        按来源派生（`_tier_for_source`），ML/好感度自动钉=浅档，其余=深档。
        normal 钉与解除都不留来源与档位（没有档就没有"为什么亲密、多亲密"）。

        2026-10-03 裁定 D-1（跨重启）在本方法里加了三件事，都只在**本人私聊键**上发生
        （键门＝`_explicit_pin_person_key`，群作用域键与成员派生键一律不进这条腿）：
        ①本人显式开档 ⇒ 落标记（档位取**生效档**，没交档位的老调用面按来源派生后落）；
        ②本人显式解除 ⇒ 收回标记；
        ③自动腿（ML／好感度）来重钉 ⇒ 先查标记，没过 TTL 就把来源与档位换成"她亲手
        开的那一次"并回填 TTL 起算点。三条全 fail-open，**不改变本方法的返回值语义**。
        """
        try:
            if mode not in {MODE_INTIMATE, MODE_NORMAL} or not str(session_key or "").strip():
                return False
            knobs = self._knobs(config)
            if not knobs["enabled"]:
                return False
            now = float(self.clock())
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            requested_source = str(source or "").strip()
            pin_source = requested_source if mode == MODE_INTIMATE else INTIMATE_SOURCE_NONE
            pin_tier = str(tier or "").strip() if mode == MODE_INTIMATE else INTIMATE_TIER_NONE
            activated_at = now if mode == MODE_INTIMATE else 0.0
            person_key = _explicit_pin_person_key(session_key, config)
            if (
                person_key
                and mode == MODE_INTIMATE
                and pin_source in _EXPLICIT_PIN_REPIN_SOURCES
            ):
                honored = self._honored_explicit_pin(
                    person_key=person_key, config=config, knobs=knobs, now=now
                )
                if honored is not None:
                    pin_source, pin_tier, activated_at = honored
            state.pin = mode
            state.last_mode = mode
            state.score = 100.0 if mode == MODE_INTIMATE else 0.0
            state.updated = now
            state.activated_at = activated_at
            state.pin_source = pin_source
            state.pin_tier = pin_tier
            # 写库放在状态改完之后：钉已上、判定已定，库那边坏不坏都不回头改本轮结果。
            if person_key and mode == MODE_NORMAL:
                self._retract_explicit_pin(person_key=person_key, config=config)
            elif person_key and requested_source == INTIMATE_SOURCE_MANUAL:
                self._record_explicit_pin(
                    person_key=person_key,
                    config=config,
                    tier=pin_tier or _tier_for_source(INTIMATE_SOURCE_MANUAL),
                )
            return True
        except Exception:  # noqa: BLE001 - fail-open。
            return False


def explicit_allowed_for_session(
    session_type: str, group_id: str, config: Any, sender_id: str = ""
) -> bool:
    """露骨内容放行判定（chat 主链与被动好感感知共用的单一事实源）。

    v21r5 四名单（2026-09-19 用户裁定）：
    - 群聊=白名单命中且不在黑名单（黑名单优先，白名单空=整体关闭）；2026-10-02
      用户裁定增补人腿：``sender_id`` 命中私聊白名单且不在私聊黑名单 ⇒ 任何群
      放行（私聊白名单空=人腿整体关闭，私聊"空=默认放开"语义不带入群侧；
      群黑名单压过人腿；空 ``sender_id`` 缺省调用面行为与旧版逐字节一致）；
    - 私聊=黑名单最高优先；白名单空=默认放开（沿用既有私聊放开裁定）、
      非空=仅名单内 QQ。``sender_id`` 缺省（被动好感感知旧调用面）不启用
      私聊名单门，行为与旧版逐字节一致；console 为运营者本地面，不参与
      私聊名单门（设计裁定）。
    其余会话类型（TG 频道/邮件等公开面）不放行。fail-open False。
    """
    try:
        st = str(session_type or "")
        if st == "console":
            return True
        if st == "private":
            sid = str(sender_id or "").strip()
            if sid:
                bl = {
                    str(item).strip()
                    for item in getattr(config, "bot_content_route_private_blacklist", []) or []
                    if str(item).strip()
                }
                if sid in bl:
                    return False  # 黑名单永远赢（Master Love 也压不过）。
                wl = {
                    str(item).strip()
                    for item in getattr(config, "bot_content_route_private_whitelist", []) or []
                    if str(item).strip()
                }
                if wl and sid not in wl:
                    return False
            return True
        if st == "group":
            # 判定顺序即裁定（2026-10-02 用户裁定「人在白名单 ⇒ 任何群都能开」）：
            # ① 群黑名单永远赢 → ② 群白名单命中即放行（既有行为一字不动）
            # → ③ 人腿 → ④ 其余不放行。
            bl = {
                str(item).strip()
                for item in getattr(config, "bot_content_route_group_blacklist", []) or []
                if str(item).strip()
            }
            gid = str(group_id or "").strip()
            if gid in bl:
                return False
            wl = {
                str(item).strip()
                for item in getattr(config, "bot_content_route_group_whitelist", []) or []
                if str(item).strip()
            }
            if gid in wl:
                return True
            # ③ 人腿：人在私聊白名单 ⇒ 任何群都能开。三条硬边界：
            # 私聊白名单空=人腿整体关闭（私聊"空=默认放开"绝不带入群侧）；
            # 私聊黑名单只关人腿、不撤销②的既有放行（顺序已保证）；
            # 空 sender_id（缺省调用面）不匹配任何名单、行为与旧版逐字节一致。
            sid = str(sender_id or "").strip()
            if sid:
                pbl = {
                    str(item).strip()
                    for item in getattr(config, "bot_content_route_private_blacklist", []) or []
                    if str(item).strip()
                }
                pwl = {
                    str(item).strip()
                    for item in getattr(config, "bot_content_route_private_whitelist", []) or []
                    if str(item).strip()
                }
                if pwl and sid in pwl and sid not in pbl:
                    return True
            return False
        return False
    except Exception:  # noqa: BLE001 - fail-open：判不了按不放行。
        return False


def resolve_intimate_context(
    engine: ContentRouteEngine,
    *,
    session_type: str,
    group_id: str = "",
    sender_id: str = "",
    session_key: str = "",
    config: Any = None,
    turn_narration_mode: str = "",
    platform: Any = "",
) -> dict[str, Any]:
    """v21r5 亲密上下文合成单一事实源（裁定：双开关 + 1h TTL + 四名单）。

    注入缝（chat.py）经此读取；路由侧经 build_router_cb→route_verdict 消费
    同一键、同一判定函数——双门同源。分层合成：
      外门 = explicit_allowed_for_session（名单门内含，黑名单永远赢）
      ∧ 用户级状态（群级钉→全员 / 成员键个人钉与滞回 / TTL 惰性过期）。

    返回 {"eligible": bool, "route_key": str, "mode": "intimate"|"normal",
    "source": str, "tier": str, "narration_mode": str, "narration_source": str}；
    ``route_key``=群聊且 per_user 开启时的成员派生键（个人级状态载体），
    否则原会话键。``source`` 回答"为什么亲密"（`INTIMATE_SOURCE_*`，未进档=空串）——
    2026-09-24 用户裁定 Master Love 只给档、不改默认模型，判据就是这个字段，
    而它的真身只有引擎里 `_SessionState.pin_source` 一处（本函数只转述、不再判一次）。

    🔴 2026-10-04 G-1～G-3 加的**两格描写档**（`narration_mode` / `narration_source`）
    与上面那些字段**不同轴**，读法要分清：
    - 它们**不看 `eligible`**，①②两格也**不看 `mode`**：描写档是文风偏好，普通模式同样能拿
      ``scene``（G-1），所以这一轴独立合成、永远在场（缺省 ``speech``）；只有③那一格
      读 `mode`（H-1＝甲，见下面优先级那一行）；
    - ``narration_source`` 是**交给唯一那把尺的来源串**——要"能不能铺开写"只准
      问 `grants_intimate_narration(ctx["narration_source"])`，全仓不设第二条判据
      （`source`／`tier` 那一族回答的是"怎么进的亲密档／多深／换不换首跳"，
      与这一格无关，别拿它们当尺）。
    - ``turn_narration_mode``＝**本轮明示**（调用方刚在命令面认下来的那一句，可缺省
      空串＝本轮没说）。优先级＝本轮 > 本人持久钉 > **亲密缺省**（H-1＝甲：亲手推上亲密档
      且那一支来源在授予面上 ⇒ 没表态也拿到 ``scene``）> 缺省 ``speech``，详见
      `_narration_axis_reading` 那一节。
    - ``platform``＝**平台事实**（``message.platform``，qq/telegram/…；可缺省空＝拿不到）。
      描写档的钉按 (平台域, 用户号) 归属 ⇒ 这一枚**决定读得到读不到**：缺席时取键口
      fail-closed（只认私聊会话键本身，群侧读不出钉），🔴 读写两面必须**同一批**接同一个
      平台事实，否则"写在 ``qq:<uid>``、读在 ``<uid>``"＝#33★ 那族两形永不相交（宁缺毋串，
      方向上是少写、不是串档）。

    fail-open：异常时 eligible=False、键回退原会话键、mode=normal、source=""、
    narration_mode=缺省 speech、narration_source=""（安全侧，绝不因合成失败放大亲密面
    或放大描写面）。
    """
    base_key = str(session_key or "").strip()
    try:
        per_user = bool(
            getattr(config, "bot_content_route_group_per_user_enabled", True)
        )
        route_key = base_key
        if (
            str(session_type or "") == "group"
            and str(sender_id or "").strip()
            and per_user
        ):
            route_key = member_session_key(base_key, sender_id)
        eligible = explicit_allowed_for_session(
            str(session_type or ""),
            str(group_id or ""),
            config,
            sender_id=str(sender_id or ""),
        )
        mode = MODE_NORMAL
        source = INTIMATE_SOURCE_NONE
        tier = INTIMATE_TIER_NONE
        from_group_pin = False
        if eligible:
            verdict = engine.route_verdict(route_key, config)
            mode = str(verdict.get("mode", MODE_NORMAL))
            source = str(verdict.get("source", INTIMATE_SOURCE_NONE) or INTIMATE_SOURCE_NONE)
            tier = str(verdict.get("tier", INTIMATE_TIER_NONE) or INTIMATE_TIER_NONE)
            from_group_pin = bool(verdict.get("from_group_pin"))
        # 描写档那一轴自成一体：键取**合成后的作用域键**（群侧才是"这个人"的那把桶），
        # 但不吃 `eligible`——文风门与内容准入门是两件事（G-1 要的就是普通模式也写得开）。
        # 🔴 唯一一处**读表**（不是第二把尺）：H-1＝甲（2026-10-04 晚「开'亲密'的话，就
        # 给 scene 场景」）要的是"亲手推上亲密档的那一轮，描写轴的缺省跟着走"，所以这里
        # 把"这一支亲密来源是不是人亲手推动的那几支"算成一枚**缺省选择器**送给轴心。
        # 判据仍只有 `_INTIMATE_NARRATION_SOURCES` 那一张表（本模块就是它的家），而
        # **能不能真的铺开写**照旧只在调用方问一次 `grants_intimate_narration(narration_source)`
        # ⇒ 自动腿（`master_love`／`affinity_tier`，表外）交空串＝缺省仍是 speech，
        # 尺日后收紧时③那一格当场收回（详见 `_narration_axis_reading` 的 docstring）。
        # 🔴 **`from_group_pin` 那一路必须交空串**（G-3 同批的第二句「别人找你依旧是 speech」）：
        # 管理员/超管拨的是"开关二＝全群生效"那把群级钉时，裁决出自整群那一桶，桶里没有
        # "本人"这一段——③ 若照发，就等于把描写档**广播**给全群每个没开过口的人。描写档
        # 按人（钉按人、缺省也按人）：她自己在群里/私聊里那句「开亲密」落的是本人键
        # （来源 `manual_command`，见 chat 侧 `_manual_pin_source` 与 `_is_group_scoped_manual_key`），
        # 那一支照旧吃到 scene。收口＝宁少不增多：少了她补一句 `/bot 描写 scene`，多了替旁人做主。
        intimate_scene_source = (
            source
            if (
                mode == MODE_INTIMATE
                and not from_group_pin
                and source in _INTIMATE_NARRATION_SOURCES
            )
            else INTIMATE_SOURCE_NONE
        )
        narration_mode, narration_source = _narration_axis_reading(
            session_key=route_key or base_key,
            sender_id=str(sender_id or ""),
            config=config,
            turn_narration_mode=turn_narration_mode,
            platform=platform,
            intimate_scene_source=intimate_scene_source,
            session_type=session_type,
        )
        return {
            "eligible": eligible,
            "route_key": route_key,
            "mode": mode,
            "source": source,
            "tier": tier,
            "narration_mode": narration_mode,
            "narration_source": narration_source,
        }
    except Exception:  # noqa: BLE001 - fail-open：安全侧收口。
        return {
            "eligible": False,
            "route_key": base_key,
            "mode": MODE_NORMAL,
            "source": INTIMATE_SOURCE_NONE,
            "tier": INTIMATE_TIER_NONE,
            "narration_mode": NARRATION_MODE_DEFAULT,
            "narration_source": INTIMATE_SOURCE_NONE,
        }


# 进程级共享实例（SHARED_REACTION_BUFFER 同款惯例）。
SHARED_CONTENT_ROUTE_ENGINE = ContentRouteEngine()


def build_router_cb(engine: ContentRouteEngine, config_provider: Any) -> Any:
    """ModelRouter content_route_cb 适配：(session_key, message_text) → verdict。

    ``config_provider`` 为零参 callable（装配期闭包返回热覆盖合并视图），
    保证 /bot runtime set 热改对路由判定即时生效。
    """

    def _cb(session_key: str, _message_text: str) -> dict[str, Any]:
        return engine.route_verdict(session_key, config_provider())

    return _cb
