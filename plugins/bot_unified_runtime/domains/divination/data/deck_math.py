"""占卜域算法唯一真身（WP9 收编，2026-09-21）。

用户裁定 11.C 的条件句判定（``docs/design/divination-consolidation-20260921.md``）
是「两套各自缺半边、按面各取一边」：**算法面取 ``data/`` 侧**（收编前它是唯一
同时具备牌库登记/反查/版本/可复现 PRNG/日程键的一侧），本模块把它升格为全域
唯一实现，其余三处旧入口（``data/draw_store.py``、``service/tarot_draw.py``、
``service/fortune.py``）改为**再导出垫片**，不再各存一份。

## 为什么落在 ``data/`` 而不是 ``service/``

收编前的依赖方向是 ``service/tarot_draw`` → ``data/tarot``（牌库本体）、
``service/divination_service`` → ``store/draw_store``（存储）：``data/`` 是叶子层、
``service/`` 是消费层。真身若落 ``service/``，``data/draw_store`` 就得反向 import
``service/``（层次倒置）；落 ``data/deck_math`` 则三条消费边全部顺方向：

    data/deck_math  ← data/draw_store      （聊天侧兼容名）
                    ← service/tarot_draw   （REST 侧兼容名）
                    ← service/fortune      （REST 侧兼容名）
                    ← service/divination_service ← store/draw_store

``store/draw_store.py`` 保持零域内依赖（只依赖标准库），避免存储层反调算法层。

## 收编前后逐字节等值（回归锁见 tests/test_divination_consolidation_wp9.py）

合并前实测两套副本**数值完全相同**，本模块取的是「同一答案的第二份拷贝删掉」，
不是「换算法」：``DECK_REVISION``（sha256 前 16 位）、``fortune_day_key``、
运势等级、seed 42 的三张牌面全部原样保持。牌库构成守护（78 张 / 22 大 /
每花色 14）取 ``service/`` 那份**更严**的形态——它对既有 ``data/`` 消费方是
纯增量校验（DECK 是模块常量、恰 78 张），不改变任何可达结果。

## 内容分区

1. 牌库登记：``SUIT_IDS`` / ``build_card_index`` / ``card_id_for`` /
   ``_compute_deck_revision`` / ``DECK_REVISION``。
2. 阵型白名单：``SPREADS`` / ``POSITION_LABELS`` / ``validate_spread``。
3. 可审计随机源：``AuditPrng`` 协议 + ``SeededPrng`` / ``SystemPrng`` /
   ``HmacPrng`` + ``rejection_sample_below`` / ``bernoulli_bit``（拒绝采样消取模偏差）。
4. 发牌：``draw_tarot_cards``（Fisher-Yates 无放回 + 独立正逆位）与聊天侧
   ``list`` 形态兼容名 ``draw_tarot``（同一实现、同一池序）。
5. 每日运势：等级权重表 / ``fortune_day_key``（**不含密钥**，故密钥轮换不重抽）/
   ``derive_fortune_seed`` / ``draw_fortune_grade`` / ``draw_daily_fortune``
   （= 前两者的组合，聊天侧一步式兼容名）/ ``fortune_rule_version_of``。
6. 牌面完整性门：``validated_tarot_cards`` —— 聊天渲染与 REST 解读**共用同一颗**
   （篡改 spread_id/牌数/牌序/牌库外牌/朝向/版本漂移一律 ``deck_integrity_mismatch``）。

纯标准库 + ``data/tarot.py``，零网络、零第三方、零 IO。
"""

from __future__ import annotations

import hashlib
import hmac
import random
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from plugins.bot_unified_runtime.domains.divination.data.tarot import DECK, TarotCard
from plugins.bot_unified_runtime.domains.divination.store.draw_store import DrawError

__all__ = [
    "DECK_REVISION",
    "FORTUNE_ALGORITHM_REVISION",
    "FORTUNE_GRADES_V1",
    "FORTUNE_RULE_VERSION",
    "POSITION_LABELS",
    "SPREADS",
    "SUIT_IDS",
    "TAROT_ALGORITHM_REVISION",
    "TAROT_DAILY_ALGORITHM_REVISION",
    "AuditPrng",
    "DrawError",
    "DrawnFortune",
    "FortuneSeed",
    "HmacPrng",
    "SeededPrng",
    "SystemPrng",
    "bernoulli_bit",
    "build_card_index",
    "card_id_for",
    "derive_fortune_seed",
    "draw_daily_fortune",
    "draw_fortune_grade",
    "draw_tarot_cards",
    "fortune_day_key",
    "fortune_rule_version_of",
    "local_date_for",
    "rejection_sample_below",
    "validate_spread",
    "validated_tarot_cards",
]

# 算法版本标识（写进持久行的 algorithm_revision 列，全域唯一一份）。
TAROT_ALGORITHM_REVISION = "tarot-fisher-yates-v1"
# 聊天侧「每日一抽」走的是 data/tarot.daily_card 的日期哈希确定性牌（与
# Fisher-Yates 随机抽取不同的算法），因此独立一档版本名（值沿用收编前）。
TAROT_DAILY_ALGORITHM_REVISION = "tarot-daily-v1"

# ---------------------------------------------------------------------------
# 1. 牌库登记
# ---------------------------------------------------------------------------

SUIT_IDS: dict[str, str] = {
    "权杖": "wands",
    "圣杯": "cups",
    "宝剑": "swords",
    "星币": "pentacles",
}


def build_card_index() -> dict[str, TarotCard]:
    """card_id → TarotCard 全量映射（78 张唯一；每次构建确定性一致）。

    大阿卡纳 ``major-00``（愚者）… ``major-21``（世界）；小阿卡纳
    ``<suit>-01``…``<suit>-14``（花色内 Ace=1 … 国王=14，按 DECK 顺序）。
    牌库结构不符（张数 ≠78 / 大阿卡纳 ≠22 / 每花色 ≠14 / 未知花色 / card_id
    重复）→ ``deck_integrity_mismatch``：不拿坏牌占卜。
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
            suit_id = SUIT_IDS.get(card.arcana)
            if suit_id is None:  # pragma: no cover - 牌库结构守护
                raise DrawError("deck_integrity_mismatch", f"未知花色：{card.arcana}")
            minor_seen[suit_id] = minor_seen.get(suit_id, 0) + 1
            card_id = f"{suit_id}-{minor_seen[suit_id]:02d}"
        if card_id in index:  # pragma: no cover - 牌库结构守护
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
        if indexed is card or indexed == card:
            return card_id
    raise DrawError("deck_integrity_mismatch", "牌不在当前牌库中")


def _compute_deck_revision() -> str:
    """牌面内容摘要（sha256 前 16 位）：任何文案/结构变化都换版本。"""
    lines = [
        f"{card_id}|{card.name}|{card.upright_keywords}|{card.reversed_keywords}"
        for card_id, card in sorted(build_card_index().items())
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


DECK_REVISION: str = _compute_deck_revision()

# ---------------------------------------------------------------------------
# 2. 阵型白名单（合同 §3.1：不接受任意 k 或未知位置名）
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

# 渲染用中文位置标签：single 保持空串（与既有 format_single_text 口径逐字一致）。
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


# ---------------------------------------------------------------------------
# 3. 可审计随机源（统一 64bit 流 + Lemire 式拒绝采样）
# ---------------------------------------------------------------------------


@runtime_checkable
class AuditPrng(Protocol):
    """可审计随机流：唯一原语是均匀 64bit 整数（重放/审计的最小接口）。"""

    def next_u64(self) -> int: ...


class SeededPrng:
    """注入 seed 的确定性 PRNG（固定回归与审计重放用）。

    ``random.Random(int)`` 的 Mersenne Twister 跨进程/跨版本稳定，绝不经过
    Python ``hash()``（受 PYTHONHASHSEED 影响不可重放）。``seed=None`` 是聊天侧
    旧用法的宽容形态（转交系统安全熵），生产随机源仍以 ``SystemPrng`` 为准。

    ``next_below``/``next_bit`` 是 ``rejection_sample_below``/``bernoulli_bit``
    的方法形态（同一算法、同一拒绝阈值），供流式调用方直接取用。
    """

    def __init__(self, seed: int | None = 0) -> None:
        self._rng = random.Random(seed)

    def next_u64(self) -> int:
        return self._rng.getrandbits(64)

    def next_below(self, bound: int) -> int:
        """无偏返回 [0, bound)；bound<=0 视为非法牌库/权重（抛 invalid_spread）。"""
        if bound <= 0:
            raise DrawError("invalid_spread", f"采样边界非法：{bound}")
        return rejection_sample_below(self, bound)

    def next_bit(self) -> int:
        """无偏单比特（正逆位 Bernoulli(0.5) 用）。"""
        return bernoulli_bit(self)


class SystemPrng:
    """生产随机源：操作系统安全熵（secrets），不可重放、不落盘。"""

    def next_u64(self) -> int:
        return secrets.randbits(64)


class HmacPrng(SeededPrng):
    """服务端 HMAC-SHA256 派生的确定性 PRNG（可审计重放）。

    counter 模式：第 n 块 = HMAC-SHA256(key, material|n)[:8] 解释为 64bit
    大端整数。同 key 同 material 必然同序列；不同 material/key 序列独立。
    """

    def __init__(self, key: bytes, material: str) -> None:
        self._key = bytes(key)
        self._base = str(material).encode("utf-8")
        self._counter = 0

    def next_u64(self) -> int:
        message = self._base + b"|" + str(self._counter).encode("ascii")
        block = hmac.new(self._key, message, hashlib.sha256).digest()
        self._counter += 1
        return int.from_bytes(block[:8], "big")


def rejection_sample_below(prng: AuditPrng, bound: int) -> int:
    """拒绝采样：无偏返回 [0, bound)（消除取模偏差，合同 §3.1）。

    拒绝区 = [2^64 - (2^64 mod bound), 2^64)；落在拒绝区的值丢弃重取——对任意
    bound（含权重总和这类非 2 幂输入）零偏差。bound <= 0 是调用方 bug：抛
    ``ValueError``（域内错误码翻译由上层负责，与聊天侧方法形态的 ``DrawError``
    区分开，两套语义各自保持收编前口径）。
    """
    if bound <= 0:
        raise ValueError(f"采样边界非法：{bound}")
    if bound == 1:
        return 0
    limit = (1 << 64) - ((1 << 64) % bound)
    while True:
        value = prng.next_u64() & ((1 << 64) - 1)
        if value < limit:
            return value % bound


def bernoulli_bit(prng: AuditPrng) -> int:
    """无偏单比特（正逆位 Bernoulli(0.5) 用）。"""
    return rejection_sample_below(prng, 2)


# ---------------------------------------------------------------------------
# 4. 发牌（Fisher-Yates 无放回 + 独立正逆位）
# ---------------------------------------------------------------------------


def draw_tarot_cards(spread_id: str, prng: AuditPrng) -> tuple[dict[str, str], ...]:
    """按白名单阵型无放回抽牌；返回合同形态 cards（card_id/position_id/orientation）。

    池序 = ``sorted(build_card_index())``（确定性），Fisher-Yates 部分洗牌抽 k 张，
    每张独立 ``bernoulli_bit`` 决定正/逆位。非法阵型 → ``invalid_spread``。
    """
    count, positions = validate_spread(spread_id)
    pool = sorted(build_card_index())  # 确定性池序
    if count > len(pool):  # pragma: no cover - 白名单阵型恒 <= 78
        raise DrawError("invalid_spread", "牌阵张数超出牌库")
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


# ---------------------------------------------------------------------------
# 5. 每日运势（HMAC 种子派生 + 累计权重抽取）
# ---------------------------------------------------------------------------

FORTUNE_RULE_VERSION = "v1"

# 合同 §3.1 默认等级与整数权重（总 100）；权重允许版本化调整（改这张表 +
# FORTUNE_RULE_VERSION），但禁止按付费/好感秘密改变概率。
FORTUNE_GRADES_V1: tuple[tuple[str, int], ...] = (
    ("大吉", 10),
    ("中吉", 25),
    ("小吉", 30),
    ("平", 25),
    ("小凶", 8),
    ("凶", 2),
)

FORTUNE_ALGORITHM_REVISION = f"fortune-rules-{FORTUNE_RULE_VERSION}"

assert sum(weight for _, weight in FORTUNE_GRADES_V1) == 100, (
    "每日运势默认权重总和必须为 100"
)


def fortune_day_key(
    principal_id: str, bot_id: str, local_date: str, rule_version: str
) -> str:
    """每日运势唯一键：principal+bot+本地日期+rule_version 派生（**不含密钥**）。

    密钥轮换不改 day_key → 存储命中既有行 → 当天不重抽（合同硬要求）。
    """
    material = f"fortune-day|{principal_id}|{bot_id}|{local_date}|{rule_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def fortune_rule_version_of(algorithm_revision: str) -> str:
    """持久行 algorithm_revision → rule_version（旧 ``rule_version`` 列的复原口径）。

    收编前聊天侧把 rule_version 单独成列；合并进 ``draws`` 后它是
    ``FORTUNE_ALGORITHM_REVISION`` 的组成部分，这里给出唯一反解口，
    不认前缀时原样返回（诚实暴露，绝不猜一个缺省版本）。
    """
    prefix = "fortune-rules-"
    value = str(algorithm_revision or "")
    stripped = value.removeprefix(prefix)
    return stripped if stripped != value else value


@dataclass(frozen=True)
class FortuneSeed:
    """一次运势抽取的种子材料（抽取流 + 审计三件套）。"""

    prng: HmacPrng
    day_key: str
    key_id: str
    seed_digest: str


@dataclass(frozen=True)
class DrawnFortune:
    """每日运势抽取结果（等级 + 审计材料），聊天侧一步式入口的返回值。"""

    grade: str
    key_id: str
    seed_digest: str


def _key_id_of(key: bytes) -> str:
    return hashlib.sha256(bytes(key)).hexdigest()[:8]


def derive_fortune_seed(
    secret: bytes,
    principal_id: str,
    bot_id: str,
    local_date: str,
    rule_version: str = FORTUNE_RULE_VERSION,
) -> FortuneSeed:
    """HMAC-SHA256 派生种子：同 (密钥, 主体, bot, 日期, 规则版本) 同结果。

    - 种子块 = HMAC-SHA256(secret, "fortune-seed|" + day_key)；
    - 抽取流 = HmacPrng(secret, "fortune-draw|" + day_key)；
    - key_id/seed_digest 供审计落库（均为主摘要前缀，不泄露原值）。
    """
    day_key = fortune_day_key(principal_id, bot_id, local_date, rule_version)
    seed_block = hmac.new(
        bytes(secret), f"fortune-seed|{day_key}".encode(), hashlib.sha256
    ).digest()
    return FortuneSeed(
        prng=HmacPrng(secret, f"fortune-draw|{day_key}"),
        day_key=day_key,
        key_id=_key_id_of(secret),
        seed_digest=hashlib.sha256(seed_block).hexdigest()[:16],
    )


def draw_fortune_grade(prng: AuditPrng) -> str:
    """按累计权重抽一个等级（权重和为分母，拒绝采样消偏差）。"""
    total = sum(weight for _, weight in FORTUNE_GRADES_V1)
    point = rejection_sample_below(prng, total)
    cumulative = 0
    for name, weight in FORTUNE_GRADES_V1:
        cumulative += weight
        if point < cumulative:
            return name
    return FORTUNE_GRADES_V1[-1][0]  # pragma: no cover - 累计覆盖全值域


def draw_daily_fortune(
    key: bytes,
    principal_id: str,
    bot_id: str,
    local_date: str,
    rule_version: str,
) -> DrawnFortune:
    """确定性每日运势一步式入口（= ``derive_fortune_seed`` + ``draw_fortune_grade``）。

    保留这个形状只为服务聊天侧「拿等级 + 审计材料」的调用点；等级数学与
    REST 服务半边同源于本模块，不存在第二份实现。
    """
    seed = derive_fortune_seed(key, principal_id, bot_id, local_date, rule_version)
    return DrawnFortune(
        grade=draw_fortune_grade(seed.prng),
        key_id=seed.key_id,
        seed_digest=seed.seed_digest,
    )


def local_date_for(moment: datetime, timezone_id: str) -> str:
    """可信时刻 → 指定时区的本地日期（YYYY-MM-DD；日期来源只信 context）。"""
    from zoneinfo import ZoneInfo

    return moment.astimezone(ZoneInfo(timezone_id)).date().isoformat()


# ---------------------------------------------------------------------------
# 6. 牌面完整性门（聊天渲染与 REST 解读共用的一颗）
# ---------------------------------------------------------------------------


def validated_tarot_cards(record: Any) -> tuple[str, list[dict[str, str]]]:
    """持久行 → 校验后的 ``(spread_id, cards)``；任何不符 → ``deck_integrity_mismatch``。

    入参是 ``store.DrawRecord``（或任何带 spread_id / cards / deck_revision 三属性的
    持久行投影）。校验项：阵型在白名单内（**持久行的 spread_id 被改属篡改，
    故归 deck_integrity_mismatch，不洗成 422 invalid_spread**）、张数与阵型定义
    相符、牌库版本未漂移、每张牌 position_id 依序、card_id 在库内、朝向合法。
    函数上不可能换牌 / 换朝向 / 伪造第 79 张。
    """
    spread_id = str(record.spread_id)
    try:
        count, positions = validate_spread(spread_id)
    except DrawError as exc:
        raise DrawError("deck_integrity_mismatch", str(exc.args[0] or exc.code)) from exc
    cards: list[dict[str, str]] = [dict(card) for card in (record.cards or ())]
    if len(cards) != count:
        raise DrawError("deck_integrity_mismatch", "牌数与牌阵定义不符")
    if str(record.deck_revision) != DECK_REVISION:
        raise DrawError("deck_integrity_mismatch", "牌库版本与持久行不符")
    index = build_card_index()
    for item, position_id in zip(cards, positions):
        if item.get("position_id") != position_id:
            raise DrawError("deck_integrity_mismatch", "位置序列不符")
        if item.get("card_id") not in index:
            raise DrawError("deck_integrity_mismatch", "牌面含牌库之外的牌")
        if item.get("orientation") not in {"upright", "reversed"}:
            raise DrawError("deck_integrity_mismatch", "朝向字段非法")
    return spread_id, cards
