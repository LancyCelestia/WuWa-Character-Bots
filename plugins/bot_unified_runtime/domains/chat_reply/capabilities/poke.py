"""统一戳一戳（poke）reaction 分发；适配器中立，独立实现。

所有适配器（OneBot / 未来 mail、telegram 等）把各自的通知事件归一成
``PokeEvent``（或任意带同名属性的普通对象）后，统一调
``PokeDispatcher.build_poke_reaction`` 拿到 ``PokeReaction``：

- 回戳（``bot_poke_poke_back``，须配 ``BOT_POKE_REPLY_MODE=poke`` 或开扩臂档
  才会被选中）：由适配器按平台 API 执行，分发器只给出意图；
- 话术（``bot_poke_group_text`` / ``bot_poke_private_text``，空=内置默认）；
- 冷却/概率/开关（既有 bot_poke_* 配置，语义不变）。

**恰一臂（2026-09-25 用户裁定 ITEM 14(a)）**：一次被戳只出**一种**表达。
回戳意图因此与形态互斥——只有选中的形态就是 ``poke`` 时 ``poke_back`` 才成立。
旧行为是「回戳与话术同时成立」，那在同一发被戳里算两臂（现网
``bot_poke_poke_back`` 缺省 True ⇒ 每戳必双发），按裁定收掉。

臂（arm）矩阵（P14 波，2026-09-25 用户裁定「完善戳一戳系统」）：被戳后的
表达在六臂里确定性选一并**只出一个**——``fixed`` 固定话术 / ``llm`` 自然语言
回复 / ``meme`` 表情包 / ``voice`` 语音+文本 / ``randpic`` 随机图 / ``poke``
只回戳。``BOT_POKE_REPLY_MODE`` 显式指名任一臂恒可用；``mix`` 轮换池由
``bot_poke_extra_arms_enabled`` 决定是旧三臂（缺省，逐字节旧行为）还是六臂。

**矩阵成表（P14 二批，2026-09-25 ITEM 14/15）**：上述臂/池/退路的唯一行表是
:data:`_POKE_REACTION_CELLS`，``_POKE_MODES`` 与两枚 mix 池都**由它派生**；
逐行不变量由 :func:`validate_poke_reaction_matrix` 现算。表里另有
``sticker_reaction`` / ``silent`` 两枚**池外行**，分别如实记着「被戳贴表情这条路
今天没接线」与「静默由门产生、权重不在池里」——详见该段注释。

本件同时是「社交主动接触」那一类动作（跟戳 / 回复后戳人 / 主动发言后戳人 /
回复后随机发图）的**唯一门身**：安静时间与 blocked 名单判定都收在这里，
调用方（根装配文件）不再各写一份判据。

分发器不导入 NoneBot，可离线单测。
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# 戳一戳冷却登记 LRU 上限：防群/会话数增长导致 _last 慢泄漏（审计 #30）。
_POKE_LAST_CAP = 4096


@dataclass
class PokeLimiter:
    clock: Callable[[], float]
    _last: OrderedDict[tuple[str, str], float] = field(default_factory=OrderedDict)
    def accept(self, event: Any, bot_id: str, enabled: bool, cooldown: float, group_cooldown: float, probability: float = 1.0) -> bool:
        if not enabled or str(getattr(event, "target_id", "")) != str(bot_id): return False
        group = str(getattr(event, "group_id", "") or "private")
        sender = str(getattr(event, "user_id", "") or "unknown")
        now = self.clock()
        if now - self._last.get((group, sender), -1e9) < max(0.0, cooldown): return False
        if now - self._last.get((group, "*"), -1e9) < max(0.0, group_cooldown): return False
        if probability < 1.0:
            digest = int(hashlib.sha256(f"{group}:{sender}:{int(now // max(1.0, group_cooldown))}".encode()).hexdigest()[:8],16) / 0xFFFFFFFF
            if digest > probability: return False
        for key in ((group, sender), (group, "*")):
            self._last[key] = now
            self._last.move_to_end(key)
        while len(self._last) > _POKE_LAST_CAP:
            self._last.popitem(last=False)
        return True


def build_poke_text(*, group: bool, nickname: str = "") -> str:
    if group:
        return f"{nickname}，我收到你的轻轻一碰了。岸边的潮声还在，不必一直戳我。"
    return "我收到你的轻轻一碰了。嗯，我在这里。"


# ------------------------------------------------------------- 统一分发入口


@dataclass(frozen=True)
class PokeEvent:
    """适配器中立的通知事件：各适配器把自己的 notice 归一成它。"""

    target_id: str = ""
    user_id: str = ""
    group_id: str = ""  # 空=私聊
    sub_type: str = "poke"

    @classmethod
    def from_notice(cls, event: Any, bot_id: str = "") -> PokeEvent | None:
        """把 OneBot 风格 notice 事件归一成 PokeEvent；非 poke 通知返回 None。

        接受任意带同名属性的对象（NoneBot Event、SimpleNamespace 均可），
        便于未来其他适配器零成本复用。
        """
        notice_type = str(getattr(event, "notice_type", "") or "")
        sub_type = str(getattr(event, "sub_type", "") or "")
        if notice_type and (notice_type != "notify" or sub_type != "poke"):
            return None
        if not notice_type and sub_type != "poke":
            return None
        target = str(getattr(event, "target_id", "") or "")
        user = str(getattr(event, "user_id", "") or "")
        group = str(getattr(event, "group_id", "") or "")
        if not target and bot_id:
            target = bot_id  # 私聊戳一戳部分协议端不带 target_id。
        return cls(target_id=target, user_id=user, group_id=group, sub_type=sub_type or "poke")


@dataclass(frozen=True)
class PokeReaction:
    """分发决定：适配器按字段执行（发话术 / 回戳）。

    ``mode``（poke v2，2026-09-16 用户裁定五件套；P14 波扩到六臂）：回复表达
    形态——``fixed``=内置/配置固定话术；``llm``=LLM 生成话术（失败回退 fixed）；
    ``meme``=表情包图片（库空回退 fixed）；``voice``=语音+文本（合成不可用
    时只留文本腿）；``randpic``=随机图（图库空回退 fixed）；``poke``=只回戳
    （回戳不可用时回退 fixed）。``reply`` 恒为 fixed 文本，供回退与
    text_fallback 使用；实际表达由调用方按 mode 组装。

    ``poke_back`` 与 ``mode`` **互斥**（恰一臂）：只在 ``mode == "poke"`` 时才
    可能为真，所以调用方按 ``mode`` 派发正文不会和回戳叠成两臂。
    """

    reply: str = ""
    poke_back: bool = False
    group: bool = False
    mode: str = "fixed"
    audit_tags: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.reply) or self.poke_back


# =============================================== 戳一戳反应矩阵（P14 二批，ITEM 14/15）
#
# 「被戳之后 bot 到底做什么」这件事在 2026-09-25 之前**没有表**：臂名手抄在
# ``_POKE_MODES``、池子手抄在两枚元组、退路写在 ``resolve_poke_reply`` 的 if 链里、
# 「回戳不可用退固定话术」又写在分发器里。四处各自正确、合起来无人对账——加一臂只改
# 一处就能静默漏掉另外三处。本段把那四处收成**一张行表** ``_POKE_REACTION_CELLS``，
# 并且让下面三枚旧常量**由表派生**（``_POKE_MODES`` / 两枚 mix 池都是推导出来的，
# 不是抄回来的）⇒ 表就是选臂的真身之一，改表即改行为，改不到第二份。
#
# 行表覆盖八行：六臂（真在池里/可点名）+ ``sticker_reaction`` + ``silent``。后两行
# 是**如实登记的洞**，不是愿望清单：
#
# - ``sticker_reaction``（贴纸回应）今天**不是** poke 的一条臂——全仓
#   ``maybe_react_on_message`` 只有两个调用点（根 ``__init__.py:8356`` / ``:8717``），
#   都在 chat 链路（情绪信号 / 回复后），poke 的 notice handler 一次都没调它；
#   它也不是 ``BOT_POKE_REPLY_MODE`` 的合法值。要接它得改根装配文件（禁直改面），
#   故此处以 ``wired_in_poke_path=False`` + 非空理由挂账，并由测试锁住
#   「未接线 ⇒ 永不被选臂取到」，不许有人把表改绿而行为没变。
# - ``silent``（静默）今天**可达但不是臂**：它由门产生（总闸 / 冷却 / 概率，见
#   ``PokeLimiter.accept``），不在任何轮换池里 ⇒ 概率表里它是 0，「静默」这件事
#   的权重归配置（``bot_poke_probability``）而不归矩阵。这条口径必须显式写着，
#   否则读表的人会以为调池子权重就能调出静默。
#
# 概率口径：**池内均匀**（``int(digest[:8], 16) % len(pool)``）⇒ 每臂权重由
# ``poke_mix_pool_weights`` 按「成员数」现算，**没有任何一处手写过 1/3 或 0.33**。
# 于是「每池概率和=1」是可证的（``sum`` 在 IEEE 下≈1，判据用近似比较），
# 且与代码取的模同一个池、不可能各说各话。

#: 通道受控词表：一行的「怎么表达」只能取这些值（写错字当场在自检里点名）。
REACTION_CHANNELS: tuple[str, ...] = (
    "text",               # 会话正文文本
    "image",              # 会话正文图片（图本身即表达，不叠字）
    "audio_text",         # 语音 + 文本（语音由调用方附加，文本腿恒在）
    "poke_back_api",      # 不发正文，调协议端回戳
    "emoji_reaction_api",  # 不发正文，给那条消息贴表情（**poke 路径未接线**）
    "none",               # 什么都不发（静默）
)
#: 轮换池标识受控词表。
MIX_POOL_IDS: tuple[str, ...] = ("legacy", "extended")
#: 降级发生地受控词表：资源落空在哪一层被兜住。
DEGRADE_SITES: tuple[str, ...] = ("resolve_poke_reply", "dispatcher", "none")
#: ``resolve_poke_reply`` 的资源形参名（受控词表；空=本臂不吃外部资源）。
REACTION_RESOURCE_KEYS: tuple[str, ...] = ("", "llm_text", "meme_path", "randpic_path")


@dataclass(frozen=True)
class PokeReactionCell:
    """反应矩阵的一行：一种「被戳之后的表达」的完整事实。

    字段语义（每一枚都有测试逐行取用，不存在「在册不检查」）：

    - ``arm_id``：臂 id，也是 ``BOT_POKE_REPLY_MODE`` 的可点名片段。
    - ``channel``：真送出去的是什么（受控词表 :data:`REACTION_CHANNELS`）。
    - ``mix_pools``：出现在哪些确定性轮换池（``legacy`` / ``extended``）。
    - ``explicit_nameable``：管理员能否在 ``BOT_POKE_REPLY_MODE`` 里点名它。
    - ``resource_key``：本臂成功表达所需的外部资源形参（空=不需要）。
    - ``fallback_arm``：``resource_key`` 落空时改走的臂（空=本身即终态/整体不发）。
    - ``degrade_site``：那条退路写在哪个函数里。
    - ``wired_in_poke_path``：这条臂**今天是否真能被被戳事件选到**。测试拿根装配
      文件的 AST 现算反查它（handler 里到底调没调那个引擎入口），接了线不改表就红
      ——「一处变更处处跟随」，不是挂着一条没人看的注释。
    - ``not_wired_reason``：仅 ``wired_in_poke_path=False`` 时必填，写明缺在哪、
      要接得动哪个文件——防止一行「看起来已交付」的表骗过读者。
    """

    arm_id: str
    label_zh: str
    channel: str
    mix_pools: tuple[str, ...]
    explicit_nameable: bool
    resource_key: str
    fallback_arm: str
    degrade_site: str
    wired_in_poke_path: bool
    not_wired_reason: str = ""


#: 行表本体。**声明序=派生池的取模序**，改序即改行为（测试拿字面元组钉死旧序）。
_POKE_REACTION_CELLS: tuple[PokeReactionCell, ...] = (
    PokeReactionCell(
        arm_id="fixed",
        label_zh="固定话术",
        channel="text",
        mix_pools=("legacy", "extended"),
        explicit_nameable=True,
        resource_key="",
        fallback_arm="",
        degrade_site="none",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="llm",
        label_zh="LLM 话术",
        channel="text",
        mix_pools=("legacy", "extended"),
        explicit_nameable=True,
        resource_key="llm_text",
        fallback_arm="fixed",
        degrade_site="resolve_poke_reply",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="meme",
        label_zh="表情包",
        channel="image",
        mix_pools=("legacy", "extended"),
        explicit_nameable=True,
        resource_key="meme_path",
        fallback_arm="fixed",
        degrade_site="resolve_poke_reply",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="voice",
        label_zh="语音+文本",
        channel="audio_text",
        mix_pools=("extended",),
        explicit_nameable=True,
        resource_key="llm_text",
        fallback_arm="fixed",
        # voice 的文本腿在 resolve 层就自兜（``llm_text or fixed_text``），
        # 「语音合成失败只留文本」那条退路在调用方，不在本表管辖内。
        degrade_site="resolve_poke_reply",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="randpic",
        label_zh="随机图",
        channel="image",
        mix_pools=("extended",),
        explicit_nameable=True,
        resource_key="randpic_path",
        fallback_arm="fixed",
        degrade_site="resolve_poke_reply",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="poke",
        label_zh="只回戳",
        channel="poke_back_api",
        mix_pools=("extended",),
        explicit_nameable=True,
        resource_key="",
        fallback_arm="fixed",
        # 退路不在 resolve（那一层返回「两腿都不发」），在分发器：协议端不支持
        # 或子功能开关关时，选臂当场改判 fixed，绝不静默空回。
        degrade_site="dispatcher",
        wired_in_poke_path=True,
    ),
    PokeReactionCell(
        arm_id="sticker_reaction",
        label_zh="贴纸回应",
        channel="emoji_reaction_api",
        mix_pools=(),
        explicit_nameable=False,
        resource_key="",
        fallback_arm="",
        degrade_site="none",
        wired_in_poke_path=False,
        not_wired_reason=(
            "poke 的 notice handler 从不调 maybe_react_on_message（全仓两个调用点"
            "都在 chat 链路：根 __init__.py:8356/:8717）⇒ 通道本体活着、被戳这一"
            "触发点不存在。接线点在根装配文件（禁直改面），且必须只认群消息——"
            "QQ 侧无私聊表情回应通道，SnowLuma 对非群消息直接抛 not supported "
            "on private messages（实测 36 次），守卫真身 "
            "domains/meme/reactions/engine.py 的 _is_group_session。"
        ),
    ),
    PokeReactionCell(
        arm_id="silent",
        label_zh="静默",
        channel="none",
        mix_pools=(),
        explicit_nameable=False,
        resource_key="",
        fallback_arm="",
        degrade_site="none",
        wired_in_poke_path=True,
    ),
)

#: ``arm_id → 行``（只读投影；行表才是真身）。
POKE_REACTION_MATRIX: dict[str, PokeReactionCell] = {
    cell.arm_id: cell for cell in _POKE_REACTION_CELLS
}

#: 显式可指名的臂全集（``BOT_POKE_REPLY_MODE`` 合法值；旧名 ``_POKE_MODES``
#: 保留=校验集，任何既有 import 语义不变）。**由行表派生**，声明序即池序。
_POKE_MODES = tuple(cell.arm_id for cell in _POKE_REACTION_CELLS if cell.explicit_nameable)
#: ``mix`` 轮换池·缺省档：与 P14 波之前逐字节同形（三臂、同一取模序）。
_POKE_MIX_POOL_LEGACY = tuple(
    cell.arm_id for cell in _POKE_REACTION_CELLS if "legacy" in cell.mix_pools
)
#: ``mix`` 轮换池·扩臂档（``bot_poke_extra_arms_enabled=True``）：旧三臂在前，
#: 新增三臂续后 ⇒ 开臂瞬间同 (会话, 戳者, 时间桶) 的旧三臂判定值不变。
_POKE_MIX_POOL_EXTENDED = tuple(
    cell.arm_id for cell in _POKE_REACTION_CELLS if "extended" in cell.mix_pools
)

#: 池标识 → 真身池元组（唯一映射处；``resolve_poke_reply_mode`` 与权重派生共用它）。
_POKE_MIX_POOLS: dict[str, tuple[str, ...]] = {
    "legacy": _POKE_MIX_POOL_LEGACY,
    "extended": _POKE_MIX_POOL_EXTENDED,
}

#: ``BOT_POKE_REPLY_MODE`` 里表示「不点名、按池轮换」的关键字。除此之外的一切取值
#: 都必须落在可点名臂里，否则就是管理员把臂名写错了。
POKE_MIX_KEYWORD = "mix"


def poke_mode_is_recognized(configured: Any) -> bool:
    """显式取值会不会被 :func:`resolve_poke_reply_mode` **认下来**。

    认下来的三种形态：空（走缺省 ``mix``）、``mix`` 关键字、``_POKE_MODES`` 里的
    某一臂名。其余一律 False——注意 ``resolve_poke_reply_mode`` 对不认识的取值
    **不报错也不改判**，而是照 ``mix`` 轮换（不擅自替管理员决定另一件事），
    所以「写了 ``voice`` 的近义词、实际在轮换六臂」这件事今天只能靠本谓词发现。
    可点名集合由行表派生 ⇒ 加一臂不改这里。
    """
    mode = str(configured or "").strip().lower()
    return not mode or mode == POKE_MIX_KEYWORD or mode in _POKE_MODES


def poke_mode_label_for_audit(configured: Any, *, limit: int = 32) -> str:
    """把管理员写的原始取值洗成一枚可入 ``audit_tags`` 的短标签后缀。

    标签会随 ``audit_tags`` 进日志与诊断卡，所以只留 ASCII 字母数字与 ``_-``，
    超长直接截断且**不补省略号**（全空时由调用方给 ``unprintable``）。口径同
    ``runtime/progress_ack`` 的「阶段名只收 ``[a-z][a-z0-9_]{0,31}``」：管理员写
    的字可以点名，但不能变成任意形态的标签名。
    """
    raw = str(configured or "").strip().lower()
    washed = "".join(
        ch for ch in raw if ch.isascii() and (ch.isalnum() or ch in "_-")
    )
    return washed[: max(1, int(limit))]


def poke_reaction_cells() -> tuple[PokeReactionCell, ...]:
    """反应矩阵全表（只读拷贝，防调用方就地改表）。"""
    return _POKE_REACTION_CELLS


def poke_reaction_cell(arm_id: str) -> PokeReactionCell | None:
    """按臂 id 取一行；不在表里回 None（不抛——表是数据面，不是校验层）。"""
    return POKE_REACTION_MATRIX.get(str(arm_id or "").strip())


def poke_mix_pool_arms(pool: str) -> tuple[str, ...]:
    """某池的成员序（与 ``resolve_poke_reply_mode`` 用的是同一枚元组）。"""
    return _POKE_MIX_POOLS.get(str(pool or "").strip(), ())


def poke_mix_pool_weights(pool: str) -> dict[str, float]:
    """某池的逐臂权重：**池内均匀 ⇒ 成员数派生**，绝不手写小数。

    选臂是 ``digest % len(pool)``，所以每臂权重恒为 ``1/len(pool)``。本函数是
    「概率和=1」这条判据的唯一算法出口——测试与任何调用方都从这里取数，
    表上不会出现第二份权重。
    """
    arms = poke_mix_pool_arms(pool)
    if not arms:
        return {}
    weight = 1.0 / len(arms)
    return {arm: weight for arm in arms}


def validate_poke_reaction_matrix() -> tuple[str, ...]:
    """行表自检：回问题清单，空元组=矩阵自洽。**判据全在这里，测试只断言结果为空。**

    为什么自检写在生产件里：这张表的用途是「一处变更处处跟随」，把判据写在测试里
    等于允许生产侧先出现一张自相矛盾的表而只有跑测试的人知道。写在这里，任何
    消费方（含未来的装配层校验）都能现算一次。
    """
    problems: list[str] = []
    cells = _POKE_REACTION_CELLS
    seen: set[str] = set()
    for cell in cells:
        arm = cell.arm_id
        if not arm:
            problems.append("存在 arm_id 为空的行")
            continue
        if arm in seen:
            problems.append(f"{arm}: arm_id 重复成行")
        seen.add(arm)
        if not cell.label_zh:
            problems.append(f"{arm}: 缺中文标签（表要能直接给人读）")
        if cell.channel not in REACTION_CHANNELS:
            problems.append(f"{arm}: 通道 {cell.channel!r} 不在受控词表 {REACTION_CHANNELS}")
        if cell.resource_key not in REACTION_RESOURCE_KEYS:
            problems.append(f"{arm}: 资源形参 {cell.resource_key!r} 未登记")
        unknown_pools = [p for p in cell.mix_pools if p not in MIX_POOL_IDS]
        if unknown_pools:
            problems.append(f"{arm}: 池标识 {unknown_pools} 未登记")
        if len(set(cell.mix_pools)) != len(cell.mix_pools):
            problems.append(f"{arm}: 池标识重复")
        if cell.degrade_site not in DEGRADE_SITES:
            problems.append(f"{arm}: 降级地 {cell.degrade_site!r} 不在受控词表")
        # 成员必可点名：进了池却不能点名 = 管理员想关它时关不掉。
        if cell.mix_pools and not cell.explicit_nameable:
            problems.append(f"{arm}: 在池 {list(cell.mix_pools)} 内却不可点名")
        # 资源与退路互相锁定：有资源就必须写明退到哪，退到的那行自己不能再要资源。
        if cell.resource_key and not cell.fallback_arm:
            problems.append(f"{arm}: 需要资源 {cell.resource_key} 却没写退路")
        if cell.fallback_arm and cell.degrade_site == "none":
            problems.append(f"{arm}: 声明了退路却标 degrade_site=none（退路没人执行）")
        if cell.fallback_arm:
            if cell.fallback_arm == arm:
                problems.append(f"{arm}: 退路指向自己")
            target = POKE_REACTION_MATRIX.get(cell.fallback_arm)
            if target is None:
                problems.append(f"{arm}: 退路 {cell.fallback_arm} 不在表里")
            elif target.resource_key:
                problems.append(
                    f"{arm}: 退路 {cell.fallback_arm} 自己也要资源"
                    f" {target.resource_key} ⇒ 落空后仍可能静默"
                )
        if not cell.wired_in_poke_path:
            if cell.mix_pools:
                problems.append(f"{arm}: 未接线却进了轮换池 {list(cell.mix_pools)}")
            if cell.explicit_nameable:
                problems.append(f"{arm}: 未接线却被列为可点名臂")
            if not cell.not_wired_reason.strip():
                problems.append(f"{arm}: 未接线必须写明理由与接线坐标")
        elif cell.not_wired_reason.strip():
            problems.append(f"{arm}: 已接线却带着未接线理由（表自相矛盾）")
    # 派生一致性：三枚旧常量必须由表算出，且与 resolve_poke_reply_mode 实际用的元组同源。
    if set(_POKE_MODES) != {cell.arm_id for cell in cells if cell.explicit_nameable}:
        problems.append("_POKE_MODES 与表的可点名行不一致")
    for pool_id, pool_tuple in _POKE_MIX_POOLS.items():
        declared = {cell.arm_id for cell in cells if pool_id in cell.mix_pools}
        if set(pool_tuple) != declared:
            problems.append(f"池 {pool_id} 成员与表不一致")
        if not pool_tuple:
            problems.append(f"池 {pool_id} 为空 ⇒ mix 无从选臂")
    return tuple(problems)


def resolve_poke_reply_mode(
    *,
    configured: str,
    group: str,
    sender: str,
    bucket: int,
    extra_arms_enabled: bool = False,
) -> str:
    """回复形态决策：显式配置直用；mix=确定性哈希轮换（同戳同果）。

    确定性来自 SHA-256 摘要取模（与 ``policy/gate.py`` 的
    ``deterministic_group_reply_lottery``、``media/capabilities/tts.py`` 的
    ``should_voice_reply`` 同一族做法），**不用** ``random`` ⇒ 测试与审计可复现。
    轮换池由 ``extra_arms_enabled`` 决定：关=旧三臂（缺省，行为逐字节不变），
    开=六臂。显式指名任一臂不受该档影响（管理员意图优先）。
    """
    mode = str(configured or "mix").strip().lower()
    if mode in _POKE_MODES:
        return mode
    pool = _POKE_MIX_POOL_EXTENDED if extra_arms_enabled else _POKE_MIX_POOL_LEGACY
    digest = hashlib.sha256(f"poke-mode:{group}:{sender}:{bucket}".encode()).hexdigest()
    return pool[int(digest[:8], 16) % len(pool)]


def resolve_poke_reply(
    mode: str,
    *,
    fixed_text: str,
    llm_text: str | None = None,
    meme_path: str | None = None,
    randpic_path: str | None = None,
) -> tuple[str, str | None]:
    """按形态组装最终回复 → (文本, 图片路径|None)。

    回退链（用户裁定：回复只回一个，任何失败回退固定话术）：
    llm 生成失败/为空 → fixed；表情库/图库选不出 → fixed。
    meme / randpic 模式成功时返回纯图（图本身即表达，不叠文字）。
    ``voice`` 只交回文本腿（语音由调用方经语音能力附加；语音失败时该腿照发，
    与「合成不可用只留文本」的既有降级口径同形）。``poke`` 两腿都不发
    （回戳即表达），调用方按 mode 自行派发回戳。
    """
    if mode == "llm" and str(llm_text or "").strip():
        return str(llm_text).strip(), None
    if mode == "voice":
        return str(llm_text or "").strip() or str(fixed_text or ""), None
    if mode == "poke":
        return "", None
    if mode == "meme" and str(meme_path or "").strip():
        return "", str(meme_path)
    if mode == "randpic" and str(randpic_path or "").strip():
        return "", str(randpic_path)
    return str(fixed_text or ""), None


# --------------------------------------------------------- 社交主动接触公共门
#
# 这一族判定（安静时间 / blocked 名单 / 五层防刷屏门）被四类动作共用：跟戳、
# 回复后戳人、主动发言后戳人、回复后随机发图。收在件里=只有一份真身；
# 根装配文件只负责拿事件字段调它。


def quiet_hours_active(
    config: Any,
    *,
    session_scope: str = "group",
    now: datetime | None = None,
) -> bool:
    """当前是否处在安静时间窗内（该会话类型是否受安静时间约束一并判定）。

    唯一事实源=``policy/quiet_hours.py``（时刻串解析走它的 ``_parse_hhmm``，
    窗比较式与 ``QuietHoursChecker._is_in_quiet_hours`` /
    ``outbound_gate._quiet_verdict`` 同一形状，本件不自造第三套解析）。
    与那两处的差别是**刻意的**：戳人/发图这类主动接触没有「点名了就放行」这条
    后门——用户点名也已经有正常回复链路，这里的窗只用于拦额外主动动作。
    设置读不到时按「不在窗内」放行（与 quiet_hours 求值失败同口径：不误拦）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
        _parse_hhmm,
        build_quiet_hours_settings,
    )

    try:
        settings: QuietHoursSettings = build_quiet_hours_settings(config)
    except Exception:  # noqa: BLE001 - 坏配置（非法时刻/时区）不误拦主动动作。
        return False
    if not settings.enabled:
        return False
    if str(session_scope or "").strip().lower() not in {
        str(value).strip().lower() for value in settings.session_types
    }:
        return False
    try:
        from zoneinfo import ZoneInfo

        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local_time = moment.astimezone(ZoneInfo(settings.timezone_name)).time()
        start = _parse_hhmm(settings.start_time)
        end = _parse_hhmm(settings.end_time)
    except Exception:  # noqa: BLE001 - 同上：判不出就当不在窗内。
        return False
    if start == end:
        return True
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def is_blocked_target(config: Any, user_id: str) -> bool:
    """目标用户是否在 blocked 名单（名单真身=``policy/roles.py`` 同源字段）。"""
    target = str(user_id or "").strip()
    if not target:
        return False
    blocked = getattr(config, "bot_blocked_user_ids", []) or []
    return any(str(item).strip() == target for item in blocked)


@dataclass(frozen=True)
class ProactiveActionKnobs:
    """主动动作的四枚门参数（开关 / 概率 / 会话冷却 / 每小时上限）。

    为什么要一个显式的参数包、而不是在本件里 ``getattr(config, f"{prefix}probability")``：
    动态键名让**配置登记总账的直读尺结构性看不见这些键**（读点桶 1 认属性式与
    字面量 ``getattr``，不认算出来的名字），于是 poke/randpic 两族 11 枚键被记成
    「登记了却零读点」＝静默失效预备役（`tests/test_config_key_registration_ledger.py`
    硬死桶逐枚点名过）。值路径本来就活着，缺的只是**可归枚的字面读点**。
    把取值挪到调用点（根装配文件按字面键名读）一举两得：账能对上，且键名拼错不再是
    「静默取到 0.0 = 永远不发」，而是当场在调用点暴露。
    """

    enabled: bool
    probability: float
    cooldown_seconds: float
    max_per_hour: int


def proactive_action_allowed(
    config: Any,
    *,
    prefix: str,
    gate: Any,
    session_key: str,
    message_key: str,
    group_id: str = "",
    user_id: str = "",
    salt: str = "",
    require_group: bool = False,
    knobs: ProactiveActionKnobs | None = None,
) -> bool:
    """主动社交动作的统一门链：开关 → 有目标 →（场合）→ blocked → 安静时间 → 五层门。

    配置值由调用点按**字面键名**取好、以 ``knobs`` 交进来（理由见
    :class:`ProactiveActionKnobs`）。``knobs=None`` 时退回到本波之前的形态：按
    ``prefix`` 动态取数（``{prefix}enabled`` / ``{prefix}probability`` /
    ``{prefix}cooldown_seconds`` / ``{prefix}max_per_hour``）——该兜底只为兼容
    旧调用点，新调用点一律显式传参。

    顺序即语义：**安静时间与名单判定必须在 ``gate.allow`` 之前**——``allow``
    一旦返回 True 就同时登记冷却/滑窗/去重（commit 语义），把「被安静窗拦下」
    记进冷却等于让拦不住的门反咬后续动作。五层门本体复用
    ``domains/meme/reactions/engine.py`` 的 ``ProactiveGate``（确定性概率+
    会话冷却+每小时滑窗+每消息去重），本件不重写第二份。

    ``require_group=True``：只在群消息里成立。主动**戳人**这一族要用它——
    先例是主动贴表情（AGENTS 台账 #35：QQ 侧没有私聊表情回应通道，协议端对非
    群消息直接抛 ``not supported on private messages``，实测 36 次）。QQ 私聊
    poke 的通道名虽在 ``outbound_registry`` 登记为 ``friend_poke``，但
    「名称在册」≠「SnowLuma 实装」，本波离线拿不到真机证据，故按
    「未证实即不放开」收在群内；拿到实测证据后再把这条判据放宽（一处真身，
    放宽只需改这里一个参数值）。发图那一族不需要它（``friend_poke`` 之外，
    私聊发图与既有 ``随机图`` 指令同口径，两栖本来就被支持）。
    """
    resolved = knobs or ProactiveActionKnobs(
        enabled=bool(getattr(config, f"{prefix}enabled", False)),
        probability=float(getattr(config, f"{prefix}probability", 0.0) or 0.0),
        cooldown_seconds=float(
            getattr(config, f"{prefix}cooldown_seconds", 3600.0) or 3600.0
        ),
        max_per_hour=int(getattr(config, f"{prefix}max_per_hour", 1) or 1),
    )
    if not resolved.enabled:
        return False
    if require_group and not str(group_id or "").strip():
        return False
    if not str(user_id or "").strip():
        return False
    if is_blocked_target(config, user_id):
        return False
    if quiet_hours_active(config, session_scope="group" if group_id else "private"):
        return False
    return bool(
        gate.allow(
            session_key,
            message_key,
            enabled=True,
            probability=resolved.probability,
            cooldown_seconds=resolved.cooldown_seconds,
            max_per_hour=resolved.max_per_hour,
            salt=salt or prefix,
        )
    )


class PokeDispatcher:
    """统一入口：开关/目标/冷却/概率门控 + 话术与回戳意图组装。"""

    def __init__(self, clock: Callable[[], float], limiter: PokeLimiter | None = None) -> None:
        self.clock = clock
        self.limiter = limiter if limiter is not None else PokeLimiter(clock=clock)

    @staticmethod
    def _knobs(config: Any) -> dict[str, Any]:
        """读 poke 的十枚配置键。

        **每枚兜底值都必须等于 ``config.py`` 里该字段的缺省**——本方法对
        ``config=None`` 或鸭子类型配置（缺属性）真的会用到这些字面量，写歪一枚就是
        「配置面开着、这里读成关」的第二真身。由
        ``tests/test_poke_five_way_matrix.py::test_dispatcher_knob_fallbacks_match_config_defaults``
        用 AST 现读 ``config.py`` 逐枚对账（数字不抄进测试，测试只读两处真身）。
        """
        return {
            "enabled": bool(getattr(config, "bot_poke_enabled", True)),
            "private_cooldown": float(getattr(config, "bot_poke_private_cooldown_seconds", 30.0)),
            "group_cooldown": float(getattr(config, "bot_poke_group_cooldown_seconds", 10.0)),
            "probability": float(getattr(config, "bot_poke_probability", 1.0)),
            "reply_enabled": bool(getattr(config, "bot_poke_reply_enabled", True)),
            # 缺省开（用户裁定 2026-09-16「回戳进五件套，缺省开」，config.py 同值）。
            # 本枚此前写成 False，与真身缺省相反：config 缺该属性时「只回戳」这条臂
            # 会在分发器当场被改判成固定话术，而配置面上它明明是开的。
            "poke_back": bool(getattr(config, "bot_poke_poke_back", True)),
            "group_text": str(getattr(config, "bot_poke_group_text", "") or ""),
            "private_text": str(getattr(config, "bot_poke_private_text", "") or ""),
            "reply_mode": str(getattr(config, "bot_poke_reply_mode", "mix") or "mix"),
            "extra_arms": bool(getattr(config, "bot_poke_extra_arms_enabled", False)),
        }

    def build_poke_reaction(
        self,
        event: Any,
        *,
        bot_id: str,
        config: Any | None = None,
        poke_back_available: bool = True,
    ) -> PokeReaction | None:
        """唯一分发点。被抑制（关/非戳我/冷却/概率未中）返回 None。

        ``event`` 接受已归一的 ``PokeEvent``，也接受原始 OneBot notice
        对象（内部先 ``PokeEvent.from_notice`` 兜底归一）。

        ``poke_back_available``：调用方申报「本会话真能执行回戳」（子功能开关
        +平台支持）。``poke`` 臂在它否时温和回退固定话术——绝不允许
        「选了回戳结果什么都没发」这种静默空回。
        """
        poke = event if isinstance(event, PokeEvent) else PokeEvent.from_notice(event, bot_id=str(bot_id))
        if poke is None:
            return None
        knobs = self._knobs(config)
        passthrough = SimplePokeView(poke)
        if not self.limiter.accept(
            passthrough,
            str(bot_id),
            knobs["enabled"],
            knobs["private_cooldown"],
            knobs["group_cooldown"],
            knobs["probability"],
        ):
            return None
        group = bool(poke.group_id)
        tags = ["poke", "poke_group" if group else "poke_private"]
        if not poke_mode_is_recognized(knobs["reply_mode"]):
            # 管理员想钉某一臂、但名字写错了 ⇒ 实际仍在按池轮换。**不改判**（那等于
            # 替她决定另一件事），但必须留名：这类「配置写了却没人执行、且零痕迹」
            # 是本仓最高频的失效形态，只靠人肉读 .env 永远发现不了。
            label = poke_mode_label_for_audit(knobs["reply_mode"])
            tags.append(f"poke_mode_unrecognized:{label or 'unprintable'}")
        # 恰一臂：回戳只是「mode 恰好等于 poke」时那一臂的执行手段，绝不叠加在
        # 话术/表情包/图/语音之上（旧写法把 can_poke_back 与 mode 正交计算，
        # 而 bot_poke_poke_back 缺省 True ⇒ 现网每一发被戳都双臂同出）。
        back_possible = knobs["poke_back"] and bool(poke_back_available)
        mode = resolve_poke_reply_mode(
            configured=knobs["reply_mode"],
            group=str(poke.group_id or "private"),
            sender=str(poke.user_id),
            # 时间桶=群冷却窗：同窗内同戳者形态恒定，冷却翻转再轮换。
            bucket=int(self.clock() // max(1.0, knobs["group_cooldown"])),
            extra_arms_enabled=knobs["extra_arms"],
        )
        can_poke_back = back_possible and mode == "poke"
        if can_poke_back:
            tags.append("poke_back")
        if mode == "poke" and not back_possible:
            # 回戳不可用 ⇒ 只回戳这条臂落空，退固定话术（不静默空回）。
            mode = "fixed"
            tags.append("poke_arm_fallback_no_poke_back")
        tags.append(f"poke_mode:{mode}")
        reply = ""
        if knobs["reply_enabled"]:
            reply = (knobs["group_text"] if group else knobs["private_text"]) or build_poke_text(
                group=group
            )
        return PokeReaction(
            reply=reply,
            poke_back=can_poke_back,
            group=group,
            mode=mode,
            audit_tags=tuple(tags),
        )


# --------------------------------------------------------------- 跟戳（A 戳 B）


@dataclass(frozen=True)
class PokeFollowTarget:
    """「A 戳了 B」这一事件里可跟戳的目标事实（B 才是被戳者，A 只作审计）。"""

    group_id: str
    poker_id: str
    target_id: str

    def poke_candidates(self, *, bot_id: str = "") -> tuple[str, ...]:
        """可戳候选序：先 B（被戳者），B 不可用时退 A（戳者）。

        候选表就是「跟戳只可能落到谁」的唯一答案，剔掉三类不该落到的对象：
        空号、机器人自己（否则 bot 戳 bot）、以及重复项（A==B 时只留一个）。
        调用方按序试投、**第一发真送出就停**，所以这里只保证「序」与「洁净」，
        不做投递、不判概率（概率/冷却归 ``proactive_action_allowed`` 那五层门）。
        """
        bot = str(bot_id or "").strip()
        out: list[str] = []
        for candidate in (self.target_id, self.poker_id):
            value = str(candidate or "").strip()
            if not value or value == bot or value in out:
                continue
            out.append(value)
        return tuple(out)


def proactive_poke_candidates(
    config: Any, target: PokeFollowTarget, *, bot_id: str = ""
) -> tuple[str, ...]:
    """跟戳可投候选（已过 blocked 名单）：先 B、B 不可用时才退 A。

    blocked 判定必须在**进门之前**做完：``ProactiveGate.allow`` 是 commit 语义，
    门过了才发觉目标在黑名单，等于白烧一次冷却与每小时额度（与
    ``proactive_action_allowed`` 里「安静窗不许烧冷却」同一条理由）。
    """
    return tuple(
        item
        for item in target.poke_candidates(bot_id=bot_id)
        if not is_blocked_target(config, item)
    )


def resolve_poke_follow_target(event: Any, *, bot_id: str) -> PokeFollowTarget | None:
    """从 poke notice 里认「别人戳别人」：群内 + 目标非空 + 目标不是机器人自己。

    机器人被戳那一发归 ``PokeDispatcher`` 管（两路互斥：本函数对戳自己的
    事件恒回 None），所以调用方先走原路、原路判否再走这里不会重复计账。
    私聊里的「戳别人」没有可跟的公开场合，一律不认。

    **禁「戳由戳起」（ITEM 14 安全栏）**：戳者若就是机器人自己，恒回 None。
    bot 的跟戳/主动戳在协议端被回声成一条 notice（user_id=bot、target=对方）
    时，没有这条判据就会被本函数认成「A 戳了 B」再跟一发 ⇒ 自激循环，
    而五层冷却只是把它变慢、并不阻止它成环。判据在**认事件**这一步，
    不在投递那一步，所以换任何投递面都拦得住。
    """
    poke = event if isinstance(event, PokeEvent) else PokeEvent.from_notice(event, bot_id=str(bot_id))
    if poke is None:
        return None
    group_id = str(poke.group_id or "").strip()
    target_id = str(poke.target_id or "").strip()
    if not group_id or not target_id:
        return None
    bot = str(bot_id or "").strip()
    if target_id == bot:
        return None
    if str(poke.user_id or "").strip() == bot:
        # 回声/自激形态：这一发本来就是 bot 戳出去的动作，绝不再跟。
        return None
    return PokeFollowTarget(
        group_id=group_id, poker_id=str(poke.user_id or "").strip(), target_id=target_id
    )


class SimplePokeView:
    """PokeEvent → PokeLimiter.accept 需要的属性视图（零拷贝）。"""

    __slots__ = ("group_id", "target_id", "user_id")

    def __init__(self, poke: PokeEvent) -> None:
        self.target_id = poke.target_id
        self.user_id = poke.user_id
        self.group_id = poke.group_id
