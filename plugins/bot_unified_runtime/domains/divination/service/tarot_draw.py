"""V2.1 S12 塔罗抽取算法半边：78 张唯一 card_id + Fisher-Yates 无放回。

合同来源：docs/design/backend-v2-product-extensions.md §3（V21-DIVINATION-002）。

- 牌数据**只读复用** ``sources/tarot.py`` 的 DECK（22 大 + 56 小韦特牌堆），
  不重写牌面；本模块只负责 card_id 登记（major-00…21 / wands-01…14 /
  cups / swords / pentacles）与 ``DECK_REVISION`` 内容摘要（牌面任何文案/
  结构变化都会换版本，作为审计与一致性门）。
- 抽取：Fisher-Yates 部分洗牌（无放回抽 k 张），正逆位独立 Bernoulli(0.5)
  （``fortune.bernoulli_bit`` 拒绝采样实现，无取模偏差）。
- 阵型白名单：single(1) / past_present_future(3) / celtic_cross(10)，
  不接受任意 k 或未知位置名 → ``invalid_spread``（已注册错误码）。
- 牌库完整性守护：DECK 必须恰为 78 张（22 大 + 每花色 14 小），否则
  ``deck_integrity_mismatch``——登记与抽取在导入期即失败，不拿坏牌占卜。
- 纯计算零副作用；随机源经 ``AuditPrng`` 注入（生产 SystemPrng / 测试 seed）。
"""

from __future__ import annotations

import hashlib

from plugins.bot_unified_runtime.domains.divination.data.tarot import DECK, TarotCard
from plugins.bot_unified_runtime.domains.divination.service.fortune import (
    AuditPrng,
    bernoulli_bit,
    rejection_sample_below,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import DrawError

__all__ = [
    "DECK_REVISION",
    "POSITION_LABELS",
    "SPREADS",
    "TAROT_ALGORITHM_REVISION",
    "build_card_index",
    "card_id_for",
    "draw_tarot_cards",
    "validate_spread",
]

TAROT_ALGORITHM_REVISION = "tarot-fisher-yates-v1"

_SUIT_IDS: dict[str, str] = {
    "权杖": "wands",
    "圣杯": "cups",
    "宝剑": "swords",
    "星币": "pentacles",
}


def build_card_index() -> dict[str, TarotCard]:
    """card_id → TarotCard 全量映射（78 张，唯一；确定性构建）。

    大阿卡纳 ``major-00``（愚者）… ``major-21``（世界）；小阿卡纳
    ``<suit>-01``…``<suit>-14``（花色内 Ace=1 … 国王=14，按 DECK 顺序）。
    牌库结构不符（≠78 张 / 22 大 / 每花色 14）→ ``deck_integrity_mismatch``。
    """
    if len(DECK) != 78:
        raise DrawError("deck_integrity_mismatch", f"牌库张数异常：{len(DECK)}")
    index: dict[str, TarotCard] = {}
    major_no = 0
    minor_seen: dict[str, int] = {}
    for card in DECK:
        if card.arcana == "大阿卡纳":
            card_id = f"major-{major_no:02d}"
            major_no += 1
        else:
            suit_id = _SUIT_IDS.get(card.arcana)
            if suit_id is None:
                raise DrawError(
                    "deck_integrity_mismatch", f"未知花色：{card.arcana}"
                )
            minor_seen[suit_id] = minor_seen.get(suit_id, 0) + 1
            card_id = f"{suit_id}-{minor_seen[suit_id]:02d}"
        if card_id in index:
            raise DrawError("deck_integrity_mismatch", f"card_id 重复：{card_id}")
        index[card_id] = card
    if major_no != 22 or any(count != 14 for count in minor_seen.values()):
        raise DrawError(
            "deck_integrity_mismatch",
            f"牌库构成异常：大阿卡纳 {major_no}/22，小阿卡纳 {minor_seen}",
        )
    return index


def card_id_for(card: TarotCard) -> str:
    """TarotCard → card_id 反查；牌不在当前牌库 → ``deck_integrity_mismatch``。"""
    for card_id, indexed in build_card_index().items():
        if indexed == card:
            return card_id
    raise DrawError("deck_integrity_mismatch", "牌不在当前牌库中")


def _compute_deck_revision() -> str:
    """牌面内容摘要（sha256 前 16 位）：登记用，牌面变化即换版本。"""
    lines = [
        f"{card_id}|{card.name}|{card.upright_keywords}|{card.reversed_keywords}"
        for card_id, card in sorted(build_card_index().items())
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


DECK_REVISION: str = _compute_deck_revision()

# ---------------------------------------------------------------------------
# 阵型白名单（合同 §3.1：不接受任意 k 或未知位置名）。
# ---------------------------------------------------------------------------

SPREADS: dict[str, tuple[int, tuple[str, ...]]] = {
    "single": (1, ("",)),
    "past_present_future": (3, ("past", "present", "future")),
    "celtic_cross": (
        10,
        (
            "situation",
            "challenge",
            "foundation",
            "recent_past",
            "goal",
            "near_future",
            "self",
            "environment",
            "hopes_fears",
            "outcome",
        ),
    ),
}

# 本地解读用中文位置标签；single 保持空串（与既有 format_single_text 口径一致）。
POSITION_LABELS: dict[str, dict[str, str]] = {
    "single": {"": ""},
    "past_present_future": {
        "past": "过去",
        "present": "现在",
        "future": "未来",
    },
    "celtic_cross": {
        "situation": "现状",
        "challenge": "障碍",
        "foundation": "根基",
        "recent_past": "近因",
        "goal": "目标",
        "near_future": "近未来",
        "self": "自我",
        "environment": "环境",
        "hopes_fears": "希望与恐惧",
        "outcome": "结局",
    },
}


def validate_spread(spread_id: str) -> tuple[int, tuple[str, ...]]:
    """阵型白名单校验：返回 (张数, 位置 id 序列)；非法 → ``invalid_spread``。"""
    spread = SPREADS.get(str(spread_id or ""))
    if spread is None:
        raise DrawError("invalid_spread", f"不支持的牌阵：{spread_id!r}")
    return spread


def draw_tarot_cards(
    spread_id: str, prng: AuditPrng
) -> tuple[dict[str, str], ...]:
    """按白名单阵型无放回抽牌（Fisher-Yates）+ 独立正逆位 Bernoulli(0.5)。

    返回合同形态 cards 元组：每张含 card_id/position_id/orientation 三键。
    """
    count, positions = validate_spread(spread_id)
    index = build_card_index()
    pool = sorted(index)  # 确定性池序
    for i in range(count):
        j = i + rejection_sample_below(prng, len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    return tuple(
        {
            "card_id": card_id,
            "position_id": position_id,
            "orientation": "reversed" if bernoulli_bit(prng) else "upright",
        }
        for position_id, card_id in zip(positions, pool[:count])
    )
