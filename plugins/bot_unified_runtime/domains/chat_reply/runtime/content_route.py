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

会话准入门在 capabilities/chat.py（持有 session_type 与群黑白名单配置）：
仅私聊/控制台/已获准群聊参与评分与手动开关。

``consume_reply`` 保留为防御性标记剥离（历史残留 ``<intimacy:...>`` 出站前
清掉），不再有注入侧。

本模块不导入 NoneBot/LLM 栈，可离线单测；所有公开方法 fail-open——
内部异常一律返回安全缺省（NORMAL/原文本），绝不影响主链路。
"""
from __future__ import annotations

import functools
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
    relation_instruction,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    group_scope_key,
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

    档位的**深浅**只有这一个解析口：``("intimate", L1)`` 浅档（不换模型）、
    ``("intimate", L2)`` 深档（grok 优先）、``("normal", "")`` 两档一起解除。
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


def _tier_for_source(source: str) -> str:
    """未记档位时的缺省档（唯一派生处，`apply_manual`/`route_verdict` 共用）。"""
    return INTIMATE_TIER_L1 if source in _SHALLOW_DEFAULT_SOURCES else INTIMATE_TIER_L2


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

    def __init__(self, clock: Any = None) -> None:
        self.clock = clock or time.monotonic
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
            }
        except Exception:  # noqa: BLE001 - fail-open。
            return {
                "mode": MODE_NORMAL,
                "head_models": [],
                "source": INTIMATE_SOURCE_NONE,
                "tier": INTIMATE_TIER_NONE,
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
            state.pin = mode
            state.last_mode = mode
            state.score = 100.0 if mode == MODE_INTIMATE else 0.0
            state.updated = now
            state.activated_at = now if mode == MODE_INTIMATE else 0.0
            state.pin_source = (
                str(source or "").strip() if mode == MODE_INTIMATE else INTIMATE_SOURCE_NONE
            )
            state.pin_tier = (
                str(tier or "").strip() if mode == MODE_INTIMATE else INTIMATE_TIER_NONE
            )
            return True
        except Exception:  # noqa: BLE001 - fail-open。
            return False


def explicit_allowed_for_session(
    session_type: str, group_id: str, config: Any, sender_id: str = ""
) -> bool:
    """露骨内容放行判定（chat 主链与被动好感感知共用的单一事实源）。

    v21r5 四名单（2026-09-19 用户裁定）：
    - 群聊=白名单命中且不在黑名单（黑名单优先，白名单空=整体关闭），不变；
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
            wl = {
                str(item).strip()
                for item in getattr(config, "bot_content_route_group_whitelist", []) or []
                if str(item).strip()
            }
            bl = {
                str(item).strip()
                for item in getattr(config, "bot_content_route_group_blacklist", []) or []
                if str(item).strip()
            }
            return str(group_id or "").strip() in (wl - bl)
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
) -> dict[str, Any]:
    """v21r5 亲密上下文合成单一事实源（裁定：双开关 + 1h TTL + 四名单）。

    注入缝（chat.py）经此读取；路由侧经 build_router_cb→route_verdict 消费
    同一键、同一判定函数——双门同源。分层合成：
      外门 = explicit_allowed_for_session（名单门内含，黑名单永远赢）
      ∧ 用户级状态（群级钉→全员 / 成员键个人钉与滞回 / TTL 惰性过期）。

    返回 {"eligible": bool, "route_key": str, "mode": "intimate"|"normal",
    "source": str}；``route_key``=群聊且 per_user 开启时的成员派生键（个人级状态载体），
    否则原会话键。``source`` 回答"为什么亲密"（`INTIMATE_SOURCE_*`，未进档=空串）——
    2026-09-24 用户裁定 Master Love 只给档、不改默认模型，判据就是这个字段，
    而它的真身只有引擎里 `_SessionState.pin_source` 一处（本函数只转述、不再判一次）。
    fail-open：异常时 eligible=False、键回退原会话键、mode=normal、source=""
    （安全侧，绝不因合成失败放大亲密面）。
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
        if eligible:
            verdict = engine.route_verdict(route_key, config)
            mode = str(verdict.get("mode", MODE_NORMAL))
            source = str(verdict.get("source", INTIMATE_SOURCE_NONE) or INTIMATE_SOURCE_NONE)
            tier = str(verdict.get("tier", INTIMATE_TIER_NONE) or INTIMATE_TIER_NONE)
        return {
            "eligible": eligible,
            "route_key": route_key,
            "mode": mode,
            "source": source,
            "tier": tier,
        }
    except Exception:  # noqa: BLE001 - fail-open：安全侧收口。
        return {
            "eligible": False,
            "route_key": base_key,
            "mode": MODE_NORMAL,
            "source": INTIMATE_SOURCE_NONE,
            "tier": INTIMATE_TIER_NONE,
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
