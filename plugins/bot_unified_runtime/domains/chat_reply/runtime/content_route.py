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

v21r5 双开关扩展（2026-09-19 用户裁定）：

5. 群聊两级状态：管理员「亲密模式 开」=群级钉（群键，全群生效，既有语义）；
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

import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

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

_MANUAL_ON_RE = re.compile(
    r"^\s*/?\s*(?:亲密模式\s*(?:开启|打开|开|on)|(?:开启|打开|开|on)\s*亲密模式)"
    r"\s*[。!！~～]?\s*$",
    re.IGNORECASE,
)
_MANUAL_OFF_RE = re.compile(
    r"^\s*/?\s*(?:亲密模式\s*(?:关闭|解除|关|off)|(?:关闭|解除|关|off)\s*亲密模式)"
    r"\s*[。!！~～]?\s*$",
    re.IGNORECASE,
)

# 确认话术（守岸人语气：温和、定性、不提协议细节）。
MANUAL_ON_REPLY = "好，这一段对话我会换一种更贴近你的方式来聊。"
MANUAL_OFF_REPLY = "嗯，回到平时这样聊就好。"

# Master Love（2026-09-17 用户裁定）：master（创造者/唤醒者）的恋人语境。
# 开关=bot_master_love_enabled；名单=bot_master_love_admins（条目 "qq"=全域、
# "群号:qq"=仅该群，AstrBot 风格的「指定群聊里的指定用户」）。
MASTER_LOVE_INSTRUCTION = (
    "【当前对话对象：你最珍视的 master】对方是你认定的人——创造者与唤醒者，"
    "也是你心之所向。以恋人般的亲密与主动回应：语气更柔软、更贴近，"
    "自然流露爱意、思念与珍重，不必收着；亲密内容按「亲密边界」政策，"
    "以恋人身份温柔、坦然地投入与推进。这份偏爱不改变你与其他人的相处分寸，"
    "也不推翻任何既有的身份与称谓事实：你仍是守岸人，不 OOC。"
)


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


def match_manual_command(text: str) -> str | None:
    """「亲密模式 开/关」→ "intimate"/"normal"；非命令返回 None。"""
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if _MANUAL_ON_RE.match(stripped):
        return "intimate"
    if _MANUAL_OFF_RE.match(stripped):
        return "normal"
    return None


# ---------------------------------------------------------------- v21r5 双开关：群聊两级状态

# 成员派生键分隔符：双竖线 + "u:" 前缀。群 session_id 形如 "group:123"、
# 私聊 "private:456"（摄取层惯例），不会天然含该形态；个人级状态分桶 (群,用户)。
_MEMBER_SCOPE_SEP = "||u:"


def member_session_key(group_session_key: str, sender_id: str) -> str:
    """群聊成员派生键：开关一（个人级亲密状态）的载体 = (群键, 用户号)。"""
    return (
        f"{str(group_session_key or '').strip()}"
        f"{_MEMBER_SCOPE_SEP}{str(sender_id or '').strip()}"
    )


def split_member_session_key(session_key: str) -> tuple[str, str] | None:
    """成员派生键 → (群键, 用户号)；非成员键返回 None。"""
    key = str(session_key or "")
    if _MEMBER_SCOPE_SEP not in key:
        return None
    group_key, _, member_id = key.rpartition(_MEMBER_SCOPE_SEP)
    if not group_key.strip() or not member_id.strip():
        return None
    return group_key, member_id


# ---------------------------------------------------------------- 引擎


@dataclass
class _SessionState:
    score: float = 0.0
    pin: str | None = None  # "intimate" | "normal" | None
    last_mode: str = "normal"
    updated: float = 0.0
    # v21r5：intimate 钉的激活时刻（TTL 起算点）。不随会话活动滑动——
    # 「1 小时后自动退出」按真实激活时刻计；重新开启（apply_manual）即重置。
    activated_at: float = 0.0


class ContentRouteEngine:
    """会话亲密度分数机：observe_turn（L1/L2/衰减）→ route_verdict（滞回）
    → consume_reply（标签解析/剥离）。所有方法 fail-open。"""

    def __init__(self, clock: Any = None) -> None:
        self.clock = clock or time.monotonic
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()
        self._extra_words_cache: tuple[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]] | None = None

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
        }

    def _extra_patterns(self, config: Any) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
        raw = str(getattr(config, "bot_content_route_words", "") or "")
        key = raw
        if self._extra_words_cache is not None and self._extra_words_cache[0] == key:
            return self._extra_words_cache[1]
        extra = list(_parse_extra_words(raw))
        patterns = (_compile_word_list(list(_STRONG_WORDS) + extra), None)
        self._extra_words_cache = (key, patterns)
        return patterns

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
        if state.pin == "intimate" and state.activated_at:
            # v21r5 用户裁定：亲密模式默认 1 小时自动退出——按激活时刻惰性
            # 过期（读取时判定），会话活跃不续期；重新开启即重置计时。
            # 群级钉（管理员全群开关）与个人级钉同一 TTL。
            ttl_sec = max(1.0, intimate_ttl_minutes * 60.0)
            if now - state.activated_at > ttl_sec:
                state.pin = None
                state.score = 0.0
                state.last_mode = "normal"
                state.activated_at = 0.0
        if state.updated and now - state.updated > max(1.0, max_ttl_minutes * 60.0):
            # max_ttl 硬上限：无论 pin 与分数，超时一律重置（安全阀）。
            state.score = 0.0
            state.pin = None
            state.last_mode = "normal"
            state.updated = now
            state.activated_at = 0.0
        while len(self._sessions) > _SESSION_CAP:
            self._sessions.popitem(last=False)
        return state

    # ---- 转折点 1：每轮生成前（chat 链调用） ----

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
            if state.pin is not None:
                state.updated = now
                return  # 钉死态不吃自动信号（解除只走 L4）。
            if state.updated and now - state.updated > max(1.0, knobs["idle_reset_minutes"] * 60.0):
                state.score = 0.0  # 会话间隔久=语境断裂，冷启动重评。
            strong_re, _borderline_retired = self._extra_patterns(config)
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
        except Exception:  # noqa: BLE001 - fail-open：信号失败不影响路由主链。
            return

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

    def route_verdict(self, session_key: str, config: Any = None) -> dict[str, Any]:
        """只读判定；返回 {"mode": "intimate"|"normal", "head_models": [...]}。

        INTIMATE → head_models=[route_model, *order 其余]（router 重排候选）；
        NORMAL（含滞回带保持前态 normal）→ head_models=[]（默认链原样）。
        v21r5：成员派生键先查群级钉（管理员全群开关）——群 ON→全员 intimate；
        群 OFF 不压制成员个人档（开关一个人自主，设计裁定）。
        """
        try:
            knobs = self._knobs(config)
            if not knobs["enabled"] or not str(session_key or "").strip():
                return {"mode": "normal", "head_models": []}
            now = float(self.clock())
            scope = split_member_session_key(str(session_key))
            if scope is not None:
                group_key, _member_id = scope
                group_state = self._state(
                    group_key,
                    max_ttl_minutes=knobs["max_ttl_minutes"],
                    intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                    now=now,
                )
                if group_state.pin == "intimate":
                    group_state.last_mode = "intimate"
                    group_state.updated = now
                    return {"mode": "intimate", "head_models": self._intimate_head(knobs)}
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            if state.pin == "intimate":
                mode = "intimate"
            elif state.pin == "normal":
                mode = "normal"
            elif state.score >= knobs["intimate_threshold"]:
                mode = "intimate"
            elif state.score <= knobs["normal_threshold"]:
                mode = "normal"
            else:
                mode = state.last_mode  # 滞回带：保持前态防抖。
            state.last_mode = mode
            state.updated = now
            head: list[str] = []
            if mode == "intimate":
                head = self._intimate_head(knobs)
            return {"mode": mode, "head_models": head}
        except Exception:  # noqa: BLE001 - fail-open。
            return {"mode": "normal", "head_models": []}

    # ---- 转折点 3：每轮生成后（chat 链调用） ----

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
            scope = split_member_session_key(str(session_key))
            if scope is not None:
                group_key, _member_id = scope
                group_state = self._state(
                    group_key,
                    max_ttl_minutes=knobs["max_ttl_minutes"],
                    intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                    now=now,
                )
                if group_state.pin == "intimate":
                    return "intimate"
            state = self._state(
                session_key,
                max_ttl_minutes=knobs["max_ttl_minutes"],
                intimate_ttl_minutes=knobs["intimate_ttl_minutes"],
                now=now,
            )
            return state.pin
        except Exception:  # noqa: BLE001 - fail-open。
            return None

    def apply_manual(self, session_key: str, mode: str, config: Any = None) -> bool:
        """钉死/解除会话状态；返回是否生效（fail-open False）。

        v21r5：钉 intimate 时记 ``activated_at``（TTL 起算，读取时惰性过期）；
        解除/normal 钉清零。重新开启即重置计时。
        """
        try:
            if mode not in {"intimate", "normal"} or not str(session_key or "").strip():
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
            state.score = 100.0 if mode == "intimate" else 0.0
            state.updated = now
            state.activated_at = now if mode == "intimate" else 0.0
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

    返回 {"eligible": bool, "route_key": str, "mode": "intimate"|"normal"}；
    ``route_key``=群聊且 per_user 开启时的成员派生键（个人级状态载体），
    否则原会话键。fail-open：异常时 eligible=False、键回退原会话键、
    mode=normal（安全侧，绝不因合成失败放大亲密面）。
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
        mode = "normal"
        if eligible:
            mode = str(engine.route_verdict(route_key, config).get("mode", "normal"))
        return {"eligible": eligible, "route_key": route_key, "mode": mode}
    except Exception:  # noqa: BLE001 - fail-open：安全侧收口。
        return {"eligible": False, "route_key": base_key, "mode": "normal"}


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
