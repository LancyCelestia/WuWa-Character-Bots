"""戳一戳**三线选路**（纯决策层，ITEM 14「完善戳一戳系统」，席 POKE 2026-09-29）。

臂本体（被戳之后能怎么表达、资源落空退到哪、贴纸臂为什么还没接线）的唯一真身是
``capabilities/poke.py`` 的行表 ``_POKE_REACTION_CELLS``；本件**不抄第二份臂池**，
只回答另一件事：**三条触发线各自该走哪一支、为什么、概率从哪来**。

三条线（用户 2026-09-25 裁定）：

======================  =========================================  ==================
线                      触发点                                     打扰级
======================  =========================================  ==================
``poked_bot``           有人戳了 bot                               被动回应
``peer_poke``           群里 A 戳了 B，bot 有概率跟戳              主动
``bot_spoke``           bot 回复完用户 / 主动发言后，有概率戳对方  主动
======================  =========================================  ==================

本件的存在理由（这些判据今天散在根装配文件的 if 链里，合起来无人对账）：

1. **单骰不双掷**——每条线只有一个骰主（``dice_owner``）：①线「要不要回、隔多久回」
   归 ``poke.PokeLimiter``；②③线「要不要主动打扰」归 ``meme/reactions/engine.py`` 的
   ``ProactiveGate``（五层门，commit 语义）。选路层**只**在臂之间取下标，绝不再对
   「发不发」掷第二次骰——两层各掷一次就是两个概率真身（台账 #53★ 时序族同型坑）。
2. **回落有序且必留痕**——任一臂不可用（能力没起、图库空、模型没答、平台不支持）
   都沿**表里写好的链**退到下一臂，``skipped`` 逐臂记否因；全链落空明确
   ``action=silent`` + ``reason=no_usable_arm``，绝不出现「什么都没发却带着一枚说它
   发了的标签」。
3. **主动打扰型落空就静默，绝不退成一条没被请求的话**——②③线只在 ``poke_back_api``
   通道里选臂；戳不出去就当这发没发生（退成文本等于凭空开口，那是比刷屏更重的错）。
4. **未证实即不放开**——SnowLuma **出站** poke 今天没有真机证据（取证见
   ``seat-POKE.md``：入站 ``notice.notify.poke`` 实测在册；出站 ``group_poke`` /
   ``friend_poke`` 零调用痕迹，验收手册 §6.6.7 仍挂「SnowLuma 不支持时静默」，
   HANDBOOK 把真实 poke/反戳列在 P2 待验收）。私聊尤其：先例是 QQ 无私聊表情回应
   通道（台账 #35★，协议端对非群消息抛 ``not supported on private messages``）。
   故②③线缺省只认群场合，群必须在 ``policy/gate`` 的四档名单里**表过态**
   （黑名单赢；没表态＝不主动打扰）；私聊要放开需「实机证据 + 调用方显式申报」两条。
5. **概率来源可点名**——每个决策带 ``probability_source``：①线点名池内哪一格权重
   （``poke.py`` 的 ``poke_mix_pool_weights``，由成员数派生、绝无手写小数），②③线
   点名是哪枚配置键（心情系数参与时会写在名字里）。

**纯函数纪律**（由 ``tests/test_poke_three_line_routing.py`` 钉死）：不读配置键
（``getattr(config, "bot_*")`` 零命中——配置登记总账的直读尺因此看不见幽灵读点；
取数一律在调用点按字面键名做完，再以 ``PokeRoutingKnobs`` 交进来，口径同
``poke.ProactiveActionKnobs``）；不写好感度（唯一入账口在根装配面，锁
``test_affinity_open_state_locks_s_memaff.py`` 要求全根对入账口的调用只有一枚）；
不用 ``random``（确定性＝SHA-256 摘要，同种子同判定，测试与真机都能复现）。

**决策件与活路径双轨，等价性由测试锁**（2026-10-03 互动面波注记）：本件建成但
**零生产接线**——生产 poke 链路今天跑的是根装配文件既有活路径（``PokeDispatcher``
选臂 / ``proactive_action_allowed`` 五层门 / M-17 中央名单门）。两轨的等价性由
``tests/test_decision_pieces_dualtrack_lock.py`` 现算锁住：同输入下选臂、回落链、
门判（开关/场合/名单表态/安静窗/blocked）逐格一致。已知口径差（锁里写明，接线时
以本件为准并同步翻活路径）：① mix 轮换两件各持确定性哈希，等价口径=同池同退路同
门判，**非逐臂同值**；② 群表态门的名单来源两件各异（本件按 ``policy/gate`` 四档
入参建模，活路径吃 ``content_route`` 的 M-17 中央名单），等价的是门槛语义
（黑名单赢/未表态拦/命中放行），不是名单字面源。
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .poke import (
    POKE_REACTION_MATRIX,
    poke_mix_pool_arms,
    poke_mix_pool_weights,
)

# --------------------------------------------------------------- 受控词表

#: 三条触发线（值即 ``trigger`` 入参，也进审计标签）。
TRIGGER_POKE_BOT = "poked_bot"
TRIGGER_PEER_POKE = "peer_poke"
TRIGGER_BOT_SPOKE = "bot_spoke"

DISTURBANCE_REACTIVE = "reactive"
DISTURBANCE_PROACTIVE = "proactive"
DISTURBANCE_LEVELS: tuple[str, ...] = (DISTURBANCE_REACTIVE, DISTURBANCE_PROACTIVE)

#: 骰主：概率的唯一归属层。
DICE_POKE_LIMITER = "poke_limiter"
DICE_PROACTIVE_GATE = "proactive_gate"
DICE_POKE_ROUTING = "poke_routing"
DICE_OWNERS: tuple[str, ...] = (DICE_POKE_LIMITER, DICE_PROACTIVE_GATE, DICE_POKE_ROUTING)

#: 「不发」这一终态（与臂表里的 ``silent`` 行同 id，不是第二枚词）。
ACTION_SILENT = "silent"

#: 臂池来源（引用 ``poke.py`` 的派生池，不复制成员）。
POOL_SOURCE_LEGACY = "poke_matrix:legacy_mix"
POOL_SOURCE_EXTENDED = "poke_matrix:extended_mix"
POOL_SOURCE_SINGLE_POKE = "single:poke_back"

#: 心情低落时先降下去的「吵闹臂」（图和语音都比一句话更打断别人）。
NOISE_SENSITIVE_ARMS: frozenset[str] = frozenset({"meme", "voice"})

#: 好感度事件源标签（入账动作在调用点；本件只申报「这一发该给谁记一笔、用什么口径」）。
AFFINITY_SOURCE_POKE = "poke"

#: 臂表里「调协议端戳人」那一格通道名（主动线只认这一种通道）。
_CHANNEL_POKE_API = "poke_back_api"


# --------------------------------------------------------------- 表：三线行
@dataclass(frozen=True)
class PokeTriggerRow:
    """一条触发线的全部事实。字段没有一个是装饰性的——每一枚都有测试取用。

    - ``trigger_id`` / ``label_zh``：线名与给人读的名字。
    - ``disturbance``：``reactive``（她被人戳）/ ``proactive``（她去戳人）。
      主动型的门链比被动型严：场合、名单、安静时间、好感地板、账本全要过。
    - ``dice_owner``：概率归属层（模块 docstring 判据 1）。
    - ``arm_pool_source``：臂候选从哪来（``poke.py`` 派生池 / 只有回戳一臂）。
    - ``explicit_honored``：管理员点名的 ``bot_poke_reply_mode`` 对本线是否生效
      （主动型不生效——那是「被戳怎么表达」的形态键，拿来决定跟戳形态是错用）。
    - ``requires_group`` / ``requires_group_consented``：主动打扰型的场合门。
    - ``allow_private_when_proven``：有无私聊 poke 的**实机证据口径**位。即便为真，
      仍要调用方另显式 ``allow_private_proactive``——「证实了也要她点头」两道闸。
    - ``affinity_principal``：这一发该给谁记正向互动（``poker``＝戳人的那位；空＝不记）。
    - ``probability_key`` / ``cooldown_key`` / ``hourly_key``：主动型三枚配置键的**字面名**
      （只进审计供点名；本件绝不自己去读它们）。
    """

    trigger_id: str
    label_zh: str
    disturbance: str
    dice_owner: str
    arm_pool_source: str
    explicit_honored: bool
    requires_group: bool
    requires_group_consented: bool
    allow_private_when_proven: bool
    affinity_principal: str
    probability_key: str = ""
    cooldown_key: str = ""
    hourly_key: str = ""

    def arm_ids(self) -> tuple[str, ...]:
        """本线可走的臂（含 ``silent`` 终态）；每个臂名都必须在 ``poke.py`` 臂表里。"""
        if self.arm_pool_source == POOL_SOURCE_SINGLE_POKE:
            return ("poke", ACTION_SILENT)
        extended = self.arm_pool_source == POOL_SOURCE_EXTENDED
        return (*poke_line_arm_pool(extended), ACTION_SILENT)


#: 行表本体。**只有三行**——多出第四行就意味着有人在这里另立了一份触发真身。
_POKE_TRIGGER_ROWS: tuple[PokeTriggerRow, ...] = (
    PokeTriggerRow(
        trigger_id=TRIGGER_POKE_BOT,
        label_zh="bot 被戳",
        disturbance=DISTURBANCE_REACTIVE,
        dice_owner=DICE_POKE_LIMITER,
        arm_pool_source=POOL_SOURCE_LEGACY,
        explicit_honored=True,
        requires_group=False,
        requires_group_consented=False,
        allow_private_when_proven=False,
        affinity_principal="poker",
    ),
    PokeTriggerRow(
        trigger_id=TRIGGER_PEER_POKE,
        label_zh="A 戳 B 跟戳",
        disturbance=DISTURBANCE_PROACTIVE,
        dice_owner=DICE_PROACTIVE_GATE,
        arm_pool_source=POOL_SOURCE_SINGLE_POKE,
        explicit_honored=False,
        requires_group=True,
        requires_group_consented=True,
        allow_private_when_proven=False,
        affinity_principal="",
        probability_key="bot_poke_follow_probability",
        cooldown_key="bot_poke_follow_cooldown_seconds",
        hourly_key="bot_poke_follow_max_per_hour",
    ),
    PokeTriggerRow(
        trigger_id=TRIGGER_BOT_SPOKE,
        label_zh="说完顺手戳一下",
        disturbance=DISTURBANCE_PROACTIVE,
        dice_owner=DICE_PROACTIVE_GATE,
        arm_pool_source=POOL_SOURCE_SINGLE_POKE,
        explicit_honored=False,
        requires_group=True,
        requires_group_consented=True,
        allow_private_when_proven=True,
        affinity_principal="",
        probability_key="bot_poke_after_reply_probability",
        cooldown_key="bot_poke_after_reply_cooldown_seconds",
        hourly_key="bot_poke_after_reply_max_per_hour",
    ),
)

#: ``trigger_id → 行``（只读投影；行表才是真身）。
POKE_TRIGGER_ROWS: dict[str, PokeTriggerRow] = {
    row.trigger_id: row for row in _POKE_TRIGGER_ROWS
}


# --------------------------------------------------------------- 输入 DTO
@dataclass(frozen=True)
class PokeCapabilities:
    """「这一刻这条臂真能送出去吗」的申报面（调用方现算，本件不猜、不探）。

    两枚 ``*_poke_supported`` 是**平台能力**而不是配置开关：缺省值按今天的取证写
    （群=通道名在册、执行面失败只报否不报错，按可用对待；私聊=零证据 ⇒ 否）。
    翻正私聊那枚的唯一正当来源是真机回执，见 ``seat-POKE.md``。
    """

    group_poke_supported: bool = True
    private_poke_supported: bool = False
    poke_back_switch: bool = True
    reply_enabled: bool = True
    llm_available: bool = True
    tts_available: bool = True
    meme_library_available: bool = True
    randpic_gallery_available: bool = True


@dataclass(frozen=True)
class PokeRoutingKnobs:
    """三线的门参数包（值由调用点按**字面键名**从配置取好再交进来）。

    每枚缺省都等于 ``config.py`` 里同名字段的缺省——由
    ``test_knob_defaults_match_registered_config_fields`` 两侧现读源码对账（零手抄）。
    尚未登记的键（``mood_quiet_valence`` / ``proactive_affinity_floor``）在登记当天
    自动纳管；``mood_quiet_valence`` 另由
    ``test_mood_quiet_band_default_matches_mood_module`` 对账 ``character/mood.py``
    的低落档阈值——本件不自造第二套心情分档。
    """

    reply_mode: str = "mix"
    extra_arms_enabled: bool = False
    follow_enabled: bool = False
    follow_probability: float = 0.2
    follow_cooldown_seconds: float = 120.0
    follow_max_per_hour: int = 4
    after_reply_enabled: bool = False
    after_reply_probability: float = 0.15
    after_reply_cooldown_seconds: float = 300.0
    after_reply_max_per_hour: int = 3
    mood_quiet_valence: float = -0.25
    proactive_affinity_floor: float = 0.0

    def line_enabled_for(self, row: PokeTriggerRow) -> bool:
        if row.trigger_id == TRIGGER_PEER_POKE:
            return bool(self.follow_enabled)
        if row.trigger_id == TRIGGER_BOT_SPOKE:
            return bool(self.after_reply_enabled)
        return True  # 被动线的总闸/冷却/概率归 PokeLimiter（骰主只有一个）。

    def probability_for(self, row: PokeTriggerRow) -> float:
        if row.trigger_id == TRIGGER_PEER_POKE:
            return float(self.follow_probability)
        if row.trigger_id == TRIGGER_BOT_SPOKE:
            return float(self.after_reply_probability)
        return 1.0

    def cooldown_for(self, row: PokeTriggerRow) -> float:
        if row.trigger_id == TRIGGER_PEER_POKE:
            return float(self.follow_cooldown_seconds)
        if row.trigger_id == TRIGGER_BOT_SPOKE:
            return float(self.after_reply_cooldown_seconds)
        return 0.0

    def hourly_cap_for(self, row: PokeTriggerRow) -> int:
        if row.trigger_id == TRIGGER_PEER_POKE:
            return int(self.follow_max_per_hour)
        if row.trigger_id == TRIGGER_BOT_SPOKE:
            return int(self.after_reply_max_per_hour)
        return 0


@dataclass(frozen=True)
class PokeRecentLedger:
    """近期已发账（**只读镜像**：账的真身在 ``ProactiveGate`` 内部状态里）。

    本件用它做「别再打扰」的预判，判了**不写**任何东西——五层门的 ``allow`` 才是
    commit 点（门过了才发觉不该发＝白烧额度，这条口径从 ``poke.py`` 继承）。
    按线分账（每线一枚键）：跟戳到顶不该吞掉发言后戳的额度，反之也一样。
    """

    last_action_at: Mapping[str, float] = field(default_factory=dict)
    actions_in_hour: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_gate(cls, gate: Any, session_key: str, *, now: float | None = None) -> PokeRecentLedger:
        """从五层门的内部状态现算镜像（读不到就当没发过＝保守方向不放大主动动作）。

        读的是 ``ProactiveGate`` 的 ``_last`` / ``_window``（同一会话一份门），所以本
        件产出的账**不是第二真身**，只是把门的世界态投影成决策层能吃的形状。
        """
        try:
            clock = getattr(gate, "clock", None)
            moment = float(now) if now is not None else (float(clock()) if callable(clock) else 0.0)
            last_raw = (getattr(gate, "_last", {}) or {}).get(str(session_key), -1e9)
            bucket = (getattr(gate, "_window", {}) or {}).get(str(session_key))
            stamps = [float(item) for item in (bucket or [])]
            fresh = len([item for item in stamps if moment - item <= 3600.0])
            return cls(
                last_action_at={"__session__": float(last_raw)},
                actions_in_hour={"__session__": fresh},
            )
        except Exception:  # noqa: BLE001 - 账本读不出就当零，主动型宁可不发。
            return cls()

    def last_seen(self, key: str) -> float:
        """本线最近一次动作时刻；本线没记过就退到「整个会话门」的账（同门同账）。"""
        value = self.last_action_at.get(key, self.last_action_at.get("__session__"))
        try:
            return float(value) if value is not None else -1e9
        except (TypeError, ValueError):
            return -1e9

    def count_in_hour(self, key: str) -> int:
        value = self.actions_in_hour.get(key, self.actions_in_hour.get("__session__", 0))
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


@dataclass(frozen=True)
class PokeRouteRequest:
    """一次选路的完整输入（缺任何一枚都走保守支，绝不把「未知」当「放行」）。"""

    trigger: str
    seed: str = ""
    is_group: bool = False
    group_id: str = ""
    poker_id: str = ""
    target_id: str = ""
    bot_id: str = ""
    now: float = 0.0
    bucket: int = 0
    spoke_purpose: str = "reply"
    mood_valence: float = 0.0
    mood_willingness: float = 1.0
    affinity_value: float | None = None
    quiet_hours_active: bool = False
    poker_blocked: bool = False
    target_blocked: bool = False
    allow_private_proactive: bool = False
    nominated_arm: str = ""
    group_black1: frozenset[str] = frozenset()
    group_black2: frozenset[str] = frozenset()
    group_white1: frozenset[str] = frozenset()
    group_white2: frozenset[str] = frozenset()
    capabilities: PokeCapabilities = field(default_factory=PokeCapabilities)
    knobs: PokeRoutingKnobs = field(default_factory=PokeRoutingKnobs)
    recent: PokeRecentLedger = field(default_factory=PokeRecentLedger)

    @property
    def subject_id(self) -> str:
        """这一发关系上的「对方」（被动线＝戳者；发言后线＝被回复的人）。"""
        return str(self.poker_id or self.target_id or "").strip()


# --------------------------------------------------------------- 输出 DTO
@dataclass(frozen=True)
class PokeRouteDecision:
    """选路结果：一支臂 + 为什么 + 概率从哪来 + 退路还剩什么。

    - ``action``：``poke`` / ``fixed`` / ``llm`` / ``meme`` / ``voice`` / ``randpic`` / ``silent``。
    - ``reason``：主判据码（审计与测试的抓手）；``reasons`` 是全链留痕。
    - ``committable``：调用方能否据此向五层门 commit（主动线过了预判才 True）。
    - ``rolled``：本层是否对「发不发」掷过骰（今天恒 False——骰主另有其人，判据 1）。
    - ``skipped``：``(臂, 否因)`` 有序表，每个被跳过的臂都要能被点名。
    - ``attempted``：已经试过且没送出去的臂（``advance_poke_route`` 用它防回环）。
    - ``fallback_chain``：本决策之后还剩哪些退路（有序；主动线为空＝落空即静默）。
    """

    trigger: str = ""
    action: str = ACTION_SILENT
    target_user_id: str = ""
    group_id: str = ""
    is_group: bool = False
    reason: str = ""
    reasons: tuple[str, ...] = ()
    disturbance: str = DISTURBANCE_REACTIVE
    dice_owner: str = DICE_POKE_LIMITER
    probability: float = 1.0
    probability_source: str = ""
    roll: float = 0.0
    rolled: bool = False
    arm_index: int = 0
    pool_id: str = ""
    pool_size: int = 0
    fallback_chain: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()
    attempted: tuple[str, ...] = ()
    committable: bool = False
    poke_back: bool = False
    reply_needed: bool = False
    audio_leg: bool = True
    secondary_actions: tuple[str, ...] = ()
    affinity_principal: str = ""
    affinity_source: str = ""
    cooldown_remaining_seconds: float = 0.0
    audit_tags: tuple[str, ...] = ()


# ------------------------------------------------------------------ 骰与池
def poke_roll(seed: str, *, salt: str = "") -> float:
    """确定性 [0,1) 取值（SHA-256 摘要，同种子同结果）。

    与 ``policy/gate.deterministic_group_reply_lottery``、``ProactiveGate`` 同族做法：
    **不用 ``random``** ⇒ 测试可复现、重放不摇摆、审计能反算。
    """
    digest = hashlib.sha256(f"poke-route:{salt}:{seed}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def poke_line_arm_pool(extended: bool) -> tuple[str, ...]:
    """被动线的臂池：**直接返回 ``poke.py`` 派生的同一枚元组**（禁第二真身）。"""
    return poke_mix_pool_arms("extended" if extended else "legacy")


def _resolve_pool(row: PokeTriggerRow, knobs: PokeRoutingKnobs) -> tuple[str, tuple[str, ...]]:
    if row.arm_pool_source == POOL_SOURCE_SINGLE_POKE:
        return "single", ("poke",)
    extended = bool(knobs.extra_arms_enabled) or row.arm_pool_source == POOL_SOURCE_EXTENDED
    return ("extended" if extended else "legacy"), poke_line_arm_pool(extended)


def _poke_channel_supported(request: PokeRouteRequest) -> bool:
    """会话场合 + 平台申报：这一发「戳」到底有没有出口。"""
    caps = request.capabilities
    if not bool(caps.poke_back_switch):
        return False
    if bool(str(request.group_id or "").strip()):
        return bool(caps.group_poke_supported)
    return bool(caps.private_poke_supported)


def _arm_gate(arm: str, request: PokeRouteRequest) -> tuple[bool, str]:
    """一臂此刻能不能真送出去（否因必须是给人读的短语，不是一枚布尔）。"""
    cell = POKE_REACTION_MATRIX.get(arm)
    if cell is None:
        return False, f"arm_unavailable:unknown_arm_{arm}"
    caps = request.capabilities
    if cell.channel == _CHANNEL_POKE_API:
        if not bool(caps.poke_back_switch):
            return False, "arm_unavailable:poke_switch_off"
        if not _poke_channel_supported(request):
            where = "group" if bool(str(request.group_id or "").strip()) else "private"
            return False, f"arm_unavailable:poke_channel_off:{where}"
        return True, ""
    resource = cell.resource_key
    if resource == "meme_path" and not bool(caps.meme_library_available):
        return False, "arm_unavailable:meme_library_empty"
    if resource == "randpic_path" and not bool(caps.randpic_gallery_available):
        return False, "arm_unavailable:randpic_gallery_empty"
    if arm == "voice":
        # 语音臂恒有文本腿（合成不可用只留文本＝既有降级口径）；两腿全无才不可用。
        if not bool(caps.tts_available) and not bool(caps.reply_enabled):
            return False, "arm_unavailable:voice_no_leg"
        return True, ""
    if resource == "llm_text" and not bool(caps.llm_available):
        return False, "arm_unavailable:llm_off"
    if cell.channel == "text" and not bool(caps.reply_enabled):
        return False, "arm_unavailable:reply_disabled"
    return True, ""


def _fallback_chain_for(arm: str) -> tuple[str, ...]:
    """沿臂表写好的退路往下走（transitive，带步数上限防自环）。"""
    chain: list[str] = []
    cursor = arm
    for _ in range(len(POKE_REACTION_MATRIX) + 1):
        cell = POKE_REACTION_MATRIX.get(cursor)
        if cell is None or not cell.fallback_arm:
            break
        nxt = cell.fallback_arm
        if nxt == arm or nxt in chain:
            break
        chain.append(nxt)
        cursor = nxt
    return tuple(chain)


def _pick_from_chain(
    chain: tuple[str, ...], request: PokeRouteRequest, attempted: tuple[str, ...]
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """按序取第一支「能送出去且没试过」的臂；每支被跳过的都要留下否因。"""
    skipped: list[tuple[str, str]] = []
    for arm in chain:
        if arm in attempted:
            skipped.append((arm, "arm_already_attempted"))
            continue
        usable, why = _arm_gate(arm, request)
        if usable:
            return arm, tuple(skipped)
        skipped.append((arm, why or "arm_unavailable"))
    return ACTION_SILENT, tuple(skipped)


def _resolve_target(request: PokeRouteRequest, row: PokeTriggerRow) -> tuple[str, tuple[str, ...]]:
    """这一发落到谁身上。跟戳线＝先被戳者 B、B 不可投才退 A（口径同
    ``poke.PokeFollowTarget.poke_candidates``，本件只做洁净过滤：空号、bot 自己、
    blocked 名单）。名单判定必须在门之前——门是 commit 语义，过了门才发现目标不该
    戳等于白烧一次冷却与每小时额度。"""
    bot = str(request.bot_id or "").strip()
    poker = str(request.poker_id or "").strip()
    peer = str(request.target_id or "").strip()
    if row.trigger_id == TRIGGER_PEER_POKE:
        candidates: tuple[tuple[str, bool], ...] = (
            (peer, bool(request.target_blocked)),
            (poker, bool(request.poker_blocked)),
        )
        tags: list[str] = []
        for index, (candidate, blocked) in enumerate(candidates):
            if not candidate or candidate == bot or blocked:
                continue
            if index == 1:
                tags.append("follow_candidate_fallback:poker")
            return candidate, tuple(tags)
        return "", tuple(tags)
    subject = poker or peer
    if subject and subject != bot:
        return subject, ()
    return "", ()


# ------------------------------------------------------------------- 判定
def decide_poke_route(request: PokeRouteRequest) -> PokeRouteDecision:
    """三线选路的唯一入口（纯函数：同输入必同输出，``==`` 可比）。"""
    row = POKE_TRIGGER_ROWS.get(str(request.trigger or ""))
    if row is None:
        return PokeRouteDecision(
            trigger=str(request.trigger or ""),
            reason="unknown_trigger",
            reasons=("unknown_trigger",),
            rolled=False,
            audit_tags=("poke_route", "unknown_trigger"),
        )
    trace: list[str] = []
    tags: list[str] = ["poke_route", f"trigger:{row.trigger_id}", f"line:{row.disturbance}"]
    roll = poke_roll(request.seed, salt=f"{row.trigger_id}:{request.bucket}")
    rolled = row.dice_owner == DICE_POKE_ROUTING

    # ---- 主动打扰型的硬门（顺序即语义：便宜且必须赢的门放最前）----
    if row.disturbance == DISTURBANCE_PROACTIVE:
        if not request.knobs.line_enabled_for(row):
            return _deny(request, row, "line_disabled", trace + ["line_disabled"], tags)
        group_id = str(request.group_id or "").strip()
        if group_id and not request.is_group:
            return _deny(request, row, "requires_group", trace + ["requires_group"], tags)
        if not group_id:
            if request.is_group:
                return _deny(request, row, "requires_group", trace + ["requires_group"], tags)
            if not row.allow_private_when_proven or not request.allow_private_proactive:
                return _deny(request, row, "requires_group", trace + ["requires_group"], tags)
            if not bool(request.capabilities.private_poke_supported):
                return _deny(
                    request,
                    row,
                    "poke_channel_unproven_private",
                    trace + ["poke_channel_unproven_private"],
                    [*tags, "poke_channel_unproven_private"],
                )
        if group_id and row.requires_group_consented:
            if group_id in frozenset(request.group_black1) or group_id in frozenset(
                request.group_black2
            ):
                return _deny(request, row, "group_blacklisted", trace + ["group_blacklisted"], tags)
            if group_id not in frozenset(request.group_white1) and group_id not in frozenset(
                request.group_white2
            ):
                return _deny(
                    request, row, "group_not_consented", trace + ["group_not_consented"], tags
                )
        if request.quiet_hours_active:
            return _deny(request, row, "quiet_hours", trace + ["quiet_hours"], tags)
        floor = float(request.knobs.proactive_affinity_floor or 0.0)
        if floor > 0.0:
            value = request.affinity_value
            if value is None or float(value) < floor:
                why = "affinity_floor"
                tags.append("affinity_floor_unread" if value is None else "affinity_floor_low")
                return _deny(request, row, why, trace + [why], tags)
        # 账本预判（不 commit）：冷却窗内、每小时到顶都不该再主动打扰。
        cooldown = float(request.knobs.cooldown_for(row))
        last = request.recent.last_seen(row.trigger_id)
        remaining = cooldown - (float(request.now) - last)
        if last > -1e8 and cooldown > 0.0 and remaining > 0.0:
            return _silent(
                request,
                row,
                "cooldown",
                trace + ["cooldown"],
                tags,
                cooldown_remaining_seconds=remaining,
            )
        cap = int(request.knobs.hourly_cap_for(row) or 0)
        if cap > 0 and int(request.recent.count_in_hour(row.trigger_id)) >= cap:
            return _silent(request, row, "hourly_cap", trace + ["hourly_cap"], tags)

    target, target_tags = _resolve_target(request, row)
    tags.extend(target_tags)
    if row.disturbance == DISTURBANCE_PROACTIVE and not target:
        return _silent(request, row, "no_candidate", trace + ["no_candidate"], tags)

    # ---- 候选臂与选臂 ----
    pool_id, raw_pool = _resolve_pool(row, request.knobs)
    pool = raw_pool
    if (
        row.disturbance == DISTURBANCE_REACTIVE
        and raw_pool
        and float(request.mood_valence) <= float(request.knobs.mood_quiet_valence)
    ):
        trimmed = tuple(arm for arm in raw_pool if arm not in NOISE_SENSITIVE_ARMS)
        if trimmed:  # 绝不清空：只剩一臂也照发，「她心情不好」不是不回的许可证。
            pool = trimmed
            tags.append(f"mood_quiet_pool_trim:{len(raw_pool)}>{len(trimmed)}")
            trace.append("mood_quiet_pool_trim")

    explicit = str(request.knobs.reply_mode or "").strip().lower()
    nominated = str(request.nominated_arm or "").strip().lower()
    chain: tuple[str, ...]
    arm_index = 0
    if nominated in POKE_REACTION_MATRIX and nominated != ACTION_SILENT:
        # 门的交接位：``PokeDispatcher`` 已经算出的那一支（含恰一臂与它的骰）。
        # 选路层**不重掷**，只检查「这支这会儿发得出去吗」，发不出去才沿退路链走
        # ——这样接线的 handler 既不改门的行为，也不出现两个臂真身。
        chain = (nominated, *_fallback_chain_for(nominated))
        tags.append(f"nominated:{nominated}")
        trace.append("dispatcher_nominated")
    elif row.explicit_honored and explicit in POKE_REACTION_MATRIX and explicit != ACTION_SILENT:
        chain = (explicit, *_fallback_chain_for(explicit))
        tags.append(f"poke_mode_named:{explicit}")
        trace.append("explicit_mode")
    else:
        if not pool:
            return _silent(request, row, "empty_pool", trace + ["empty_pool"], tags)
        arm_index = min(int(roll * len(pool)), len(pool) - 1)
        chosen = pool[arm_index]
        chain = (chosen, *(arm for arm in pool if arm != chosen), *_fallback_chain_for(chosen))
        tags.append(f"pool:{pool_id}")
        trace.append("pool_rotation")
    if row.disturbance == DISTURBANCE_PROACTIVE:
        # 判据 3：主动线只在「戳」这一种通道里选臂；退成话术＝凭空开口，比不发更错。
        chain = tuple(
            arm
            for arm in chain
            if (POKE_REACTION_MATRIX.get(arm) is not None and POKE_REACTION_MATRIX[arm].channel == _CHANNEL_POKE_API)
        )

    action, skipped = _pick_from_chain(chain, request, attempted=())
    if action == ACTION_SILENT:
        trace.append("no_usable_arm")
        return _silent(request, row, "no_usable_arm", trace, tags, skipped=skipped)
    if skipped:
        trace.append(f"fallback_to:{action}")

    # ---- 概率与它的字面来源 ----
    probability = 1.0
    probability_source = ""
    if row.disturbance == DISTURBANCE_PROACTIVE:
        base = float(request.knobs.probability_for(row))
        willingness = float(request.mood_willingness or 1.0)
        probability = max(0.0, min(1.0, round(base * willingness, 6)))
        probability_source = row.probability_key
        if willingness != 1.0:
            probability_source = f"{row.probability_key}×mood.willingness"
            tags.append(f"mood_willingness:{willingness:g}")
    else:
        weights = poke_mix_pool_weights(pool_id)
        probability = float(weights.get(action, 1.0 / max(1, len(pool))))
        if "dispatcher_nominated" in trace:
            #  provenance 老实在案：这一支是门（PokeDispatcher）交过来的，不是本层挑的。
            probability_source = f"poke_dispatcher.nominated_arm[{action}]"
        elif "explicit_mode" in trace:
            probability_source = f"bot_poke_reply_mode[{action}]"
        else:
            probability_source = f"poke_mix_pool_weights[{pool_id}]['{action}']"

    # ---- 臂的执行侧附注（不改判，只留痕）----
    audio_leg = bool(request.capabilities.tts_available)
    if action == "voice" and not audio_leg:
        tags.append("voice_audio_leg_off")
    for _arm, why in skipped:
        if "poke_channel_off" in why:
            tags.append("poke_channel_off:session")
        elif "poke_switch_off" in why:
            tags.append("poke_switch_off:session")

    reason = trace[-1] if trace else "routed"
    return PokeRouteDecision(
        trigger=row.trigger_id,
        action=action,
        target_user_id=target or request.subject_id,
        group_id=str(request.group_id or "").strip(),
        is_group=bool(request.is_group),
        reason=reason,
        reasons=tuple(trace),
        disturbance=row.disturbance,
        dice_owner=row.dice_owner,
        probability=probability,
        probability_source=probability_source,
        roll=roll,
        rolled=rolled,
        arm_index=arm_index,
        pool_id=pool_id,
        pool_size=len(pool),
        fallback_chain=tuple(arm for arm in chain if arm != action),
        skipped=skipped,
        committable=row.disturbance == DISTURBANCE_PROACTIVE,
        poke_back=action == "poke",
        reply_needed=action not in {"poke", ACTION_SILENT},
        audio_leg=audio_leg,
        secondary_actions=(),
        affinity_principal=(request.subject_id if row.affinity_principal == "poker" else ""),
        affinity_source=(AFFINITY_SOURCE_POKE if row.affinity_principal == "poker" and request.subject_id else ""),
        audit_tags=(*tags, f"arm:{action}", f"reason:{reason}"),
    )


def advance_poke_route(
    decision: PokeRouteDecision,
    *,
    failed_arm: str,
    capabilities: PokeCapabilities,
) -> PokeRouteDecision:
    """执行面回执「这一臂没送出去」⇒ 沿原决策登记的退路给下一臂。

    只走 ``fallback_chain``，**不重开轮换池**——重开池等于对同一事件第二次抽签
    （判据 1）。链走完就 ``silent``/``no_usable_arm``，调用方据此收尾并留痕，
    绝不允许「试了一圈什么都没发、日志上却是一片成功」。
    """
    attempted = tuple(dict.fromkeys(item for item in (*decision.attempted, str(failed_arm or "")) if item))
    request = PokeRouteRequest(
        trigger=decision.trigger,
        is_group=decision.is_group,
        group_id=decision.group_id,
        poker_id=decision.target_user_id,
        capabilities=capabilities,
    )
    row = POKE_TRIGGER_ROWS.get(request.trigger)
    disturbance = row.disturbance if row else DISTURBANCE_REACTIVE
    dice_owner = row.dice_owner if row else DICE_POKE_LIMITER
    candidates = tuple(arm for arm in decision.fallback_chain if arm not in attempted)
    if not candidates:
        candidates = tuple(arm for arm in _fallback_chain_for(str(failed_arm)) if arm not in attempted)
    if disturbance == DISTURBANCE_PROACTIVE:
        candidates = ()  # 主动线没有话术退路（判据 3）
    action, skipped = _pick_from_chain(candidates, request, attempted=attempted)
    if action == ACTION_SILENT:
        trace = (f"advance_from:{failed_arm}", "no_usable_arm")
    else:
        trace = (f"advance_from:{failed_arm}", "fallback_after_delivery_failure")
    return PokeRouteDecision(
        trigger=decision.trigger,
        action=action,
        target_user_id=decision.target_user_id,
        group_id=decision.group_id,
        is_group=decision.is_group,
        reason=trace[-1],
        reasons=trace,
        disturbance=disturbance,
        dice_owner=dice_owner,
        probability=decision.probability if action != ACTION_SILENT else 0.0,
        probability_source=decision.probability_source,
        roll=decision.roll,
        rolled=False,
        arm_index=decision.arm_index,
        pool_id=decision.pool_id,
        pool_size=decision.pool_size,
        fallback_chain=tuple(arm for arm in candidates if arm != action),
        skipped=skipped,
        attempted=attempted,
        committable=False,
        poke_back=action == "poke",
        reply_needed=action not in {"poke", ACTION_SILENT},
        audio_leg=bool(capabilities.tts_available),
        secondary_actions=(),
        affinity_principal=decision.affinity_principal,
        affinity_source=decision.affinity_source,
        audit_tags=(
            "poke_route_advance",
            f"failed:{failed_arm}",
            f"arm:{action}",
            f"reason:{trace[-1]}",
        ),
    )


# ------------------------------------------------------------------ 内部件
def _deny(
    request: PokeRouteRequest,
    row: PokeTriggerRow,
    reason: str,
    trace: list[str],
    tags: list[str],
) -> PokeRouteDecision:
    return _silent(request, row, reason, trace, tags)


def _silent(
    request: PokeRouteRequest,
    row: PokeTriggerRow,
    reason: str,
    trace: list[str],
    tags: list[str],
    *,
    skipped: tuple[tuple[str, str], ...] = (),
    cooldown_remaining_seconds: float = 0.0,
) -> PokeRouteDecision:
    """静默终态：门拦下（不发、也不留「我选择不回」的用户可见痕迹），但**账要留全**。"""
    return PokeRouteDecision(
        trigger=row.trigger_id,
        action=ACTION_SILENT,
        target_user_id="",
        group_id=str(request.group_id or "").strip(),
        is_group=bool(request.is_group),
        reason=reason,
        reasons=tuple(trace or [reason]),
        disturbance=row.disturbance,
        dice_owner=row.dice_owner,
        probability=0.0,
        probability_source=row.probability_key if row.disturbance == DISTURBANCE_PROACTIVE else "",
        roll=poke_roll(request.seed, salt=f"{row.trigger_id}:{request.bucket}"),
        rolled=False,
        arm_index=0,
        pool_id="",
        pool_size=0,
        fallback_chain=(),
        skipped=skipped,
        committable=False,
        poke_back=False,
        reply_needed=False,
        audio_leg=False,
        secondary_actions=(),
        affinity_principal="",
        affinity_source="",
        cooldown_remaining_seconds=cooldown_remaining_seconds,
        audit_tags=(*tags, f"arm:{ACTION_SILENT}", f"reason:{reason}"),
    )


# -------------------------------------------------------------- 表自检
def poke_routing_rows() -> tuple[PokeTriggerRow, ...]:
    """三线行表（只读拷贝，防调用方就地改表）。"""
    return _POKE_TRIGGER_ROWS


def poke_routing_row(trigger_id: str) -> PokeTriggerRow | None:
    """按线 id 取一行；不在表里回 None（数据面不抛）。"""
    return POKE_TRIGGER_ROWS.get(str(trigger_id or "").strip())


def validate_poke_routing_table() -> tuple[str, ...]:
    """行表自检：回问题清单，空元组=自洽。

    判据写在生产件里（口径同 ``poke.py`` 的 ``validate_poke_reaction_matrix``）：这张表
    的意义是「一处变更处处跟随」，只把尺留在测试里等于允许生产侧先出现一张自相
    矛盾的表、而只有跑测试的人知道。
    """
    problems: list[str] = []
    rows = _POKE_TRIGGER_ROWS
    seen: set[str] = set()
    declared = {TRIGGER_POKE_BOT, TRIGGER_PEER_POKE, TRIGGER_BOT_SPOKE}
    for row in rows:
        if not row.trigger_id:
            problems.append("存在 trigger_id 为空的行")
            continue
        if row.trigger_id in seen:
            problems.append(f"{row.trigger_id}: trigger_id 重复成行")
        seen.add(row.trigger_id)
        if not row.label_zh:
            problems.append(f"{row.trigger_id}: 缺中文标签（表要能给人读）")
        if row.disturbance not in DISTURBANCE_LEVELS:
            problems.append(f"{row.trigger_id}: 打扰级 {row.disturbance!r} 未登记")
        if row.dice_owner not in DICE_OWNERS:
            problems.append(f"{row.trigger_id}: 骰主 {row.dice_owner!r} 未登记")
        if row.arm_pool_source not in {POOL_SOURCE_LEGACY, POOL_SOURCE_EXTENDED, POOL_SOURCE_SINGLE_POKE}:
            problems.append(f"{row.trigger_id}: 臂池来源 {row.arm_pool_source!r} 未登记")
        if row.affinity_principal not in {"", "poker"}:
            problems.append(f"{row.trigger_id}: 好感归属 {row.affinity_principal!r} 未登记")
        for arm in row.arm_ids():
            if arm != ACTION_SILENT and arm not in POKE_REACTION_MATRIX:
                problems.append(f"{row.trigger_id}: 臂 {arm} 不在 poke.py 臂表里（禁第二真身）")
        if row.disturbance == DISTURBANCE_PROACTIVE:
            if not row.requires_group:
                problems.append(f"{row.trigger_id}: 主动打扰型必须只认群场合（私聊 poke 未证实）")
            if not row.requires_group_consented:
                problems.append(f"{row.trigger_id}: 主动打扰型必须过群名单表态门")
            if row.arm_pool_source != POOL_SOURCE_SINGLE_POKE:
                problems.append(f"{row.trigger_id}: 主动线不得轮换到话术臂（跟戳只会跟戳）")
            if row.explicit_honored:
                problems.append(
                    f"{row.trigger_id}: 主动线不该被 bot_poke_reply_mode 点名（那是被戳的形态键）"
                )
            for key_name in ("probability_key", "cooldown_key", "hourly_key"):
                value = str(getattr(row, key_name) or "")
                if not value.startswith("bot_"):
                    problems.append(
                        f"{row.trigger_id}: {key_name} 必须是 bot_* 配置键字面名（概率要能点名）"
                    )
        if row.disturbance == DISTURBANCE_REACTIVE and row.arm_pool_source == POOL_SOURCE_SINGLE_POKE:
            problems.append(f"{row.trigger_id}: 被动线必须走臂表派生池，不能只有一臂")
        if row.disturbance == DISTURBANCE_REACTIVE and row.affinity_principal != "poker":
            problems.append(f"{row.trigger_id}: 被戳这一发必须给戳者留结构化事件源")
        if row.allow_private_when_proven and not row.requires_group:
            problems.append(f"{row.trigger_id}: 允许私聊主动的前提是群门在册（否则无从收紧）")
    if seen != declared:
        problems.append(
            f"触发线集合不齐：缺 {sorted(declared - seen)} 多 {sorted(seen - declared)}"
        )
    for extended in (False, True):
        pool = poke_line_arm_pool(extended)
        if not pool:
            problems.append(f"臂池（extended={extended}）为空 ⇒ mix 无从选臂")
        for arm in pool:
            if arm not in POKE_REACTION_MATRIX:
                problems.append(f"臂池里出现不在臂表里的臂名：{arm}")
            cell = POKE_REACTION_MATRIX.get(arm)
            if cell is not None and cell.fallback_arm and cell.fallback_arm not in POKE_REACTION_MATRIX:
                problems.append(f"臂 {arm} 的退路 {cell.fallback_arm} 不在臂表里")
    return tuple(problems)


def describe_poke_route_for_audit(decision: PokeRouteDecision) -> str:
    """一行给人读的选路说明（日志/诊断卡用；**不进会话正文**——正文仍是守岸人话术）。"""
    skipped = "、".join(f"{arm}（{why}）" for arm, why in decision.skipped) or "无"
    return (
        f"线「{decision.trigger or '未名'}」走「{decision.action}」，"
        f"概率来自 {decision.probability_source or '未参与'}；"
        f"跳过：{skipped}；判据：{'/'.join(decision.reasons) or '—'}"
    )
