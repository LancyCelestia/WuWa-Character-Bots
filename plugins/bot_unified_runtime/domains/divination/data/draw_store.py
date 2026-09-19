"""V2.1 S12 抽签存储与公平性服务（占卜/每日运势/塔罗）。

对应 backend-v2-product-extensions.md §3 合同的持久化与算法半边：

- ``DrawStore``：SQLite（路径注入，tmp_path 可测）。
  - ``daily_fortune`` 表：day_key（principal+bot+本地日期+rule_version 派生，
    **不含密钥**）唯一——同日重读/并发/重启/密钥轮换都命中既有行不重抽；
    审计保存 key_id 与种子摘要。
  - ``tarot_draws`` 表：draw_id 幂等（同 id 重试返回既有结果不重抽）；
    cards JSON（card_id/position_id/orientation）+ algorithm_revision +
    deck_revision + occurred_at；随机抽取的冷却/每日配额在 BEGIN IMMEDIATE
    写锁事务内判定（并发不超卖）。
- 公平性算法（合同 §3.1）：服务端 HMAC-SHA256 派生种子（key 注入可测）→
  可审计确定性 PRNG（counter 模式取 64bit 整数）→ 拒绝采样消除取模偏差 →
  按累计权重抽等级（大吉10/中吉25/小吉30/平25/小凶8/凶2，总 100）。
- 塔罗：固定 78 张唯一 card_id（读 sources/tarot.py 的 DECK，不重写牌数据）；
  Fisher-Yates 无放回抽 k；正逆位独立 Bernoulli(0.5)；阵型白名单
  single/past_present_future/celtic_cross，非法 → ``invalid_spread``。
- LLM 解读只消费持久化后的牌面：``build_interpretation_context`` 只吃
  DrawStore 行，持久行被篡改/牌数不符/牌库版本漂移 →
  ``deck_integrity_mismatch``（函数上不可能换牌）。

纯标准库 + sources/tarot.py，零网络零第三方。
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.divination.data.tarot import (
    DECK,
    DrawnCard,
    TarotCard,
)

__all__ = [
    "DECK_REVISION",
    "FORTUNE_GRADES_V1",
    "FORTUNE_RULE_VERSION",
    "DrawError",
    "DrawStore",
    "FortuneOutcome",
    "HmacPrng",
    "InterpretationContext",
    "SeededPrng",
    "build_card_index",
    "build_interpretation_context",
    "card_id_for",
    "daily_fortune_day_key",
    "draw_daily_fortune",
    "draw_tarot",
    "rebuild_drawn_cards",
    "validate_spread",
]

# ---------------------------------------------------------------------------
# 错误码（合同 §3.2：invalid_spread / deck_integrity_mismatch / rate_limited）。
# ---------------------------------------------------------------------------


class DrawError(Exception):
    """抽签域错误；``code`` 为合同注册的错误码。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


# ---------------------------------------------------------------------------
# 牌库索引：固定 78 张唯一 card_id（由 sources/tarot.py 的 DECK 确定性构建）。
# ---------------------------------------------------------------------------

_SUIT_IDS: dict[str, str] = {
    "权杖": "wands",
    "圣杯": "cups",
    "宝剑": "swords",
    "星币": "pentacles",
}


def build_card_index() -> dict[str, TarotCard]:
    """card_id → TarotCard 全量映射（78 张，唯一；每次构建确定性一致）。

    大阿卡纳 ``major-00``（愚者）… ``major-21``（世界）；小阿卡纳
    ``wands-01``…``pentacles-14``（花色内 Ace=1 … 国王=14，按 DECK 顺序）。
    """
    index: dict[str, TarotCard] = {}
    major_no = 0
    minor_seen: dict[str, int] = {}
    for card in DECK:
        if card.arcana == "大阿卡纳":
            card_id = f"major-{major_no:02d}"
            major_no += 1
        else:
            suit_id = _SUIT_IDS.get(card.arcana)
            if suit_id is None:  # pragma: no cover - 牌库结构守护
                raise DrawError("deck_integrity_mismatch", f"未知花色：{card.arcana}")
            minor_seen[suit_id] = minor_seen.get(suit_id, 0) + 1
            card_id = f"{suit_id}-{minor_seen[suit_id]:02d}"
        if card_id in index:  # pragma: no cover - 牌库结构守护
            raise DrawError("deck_integrity_mismatch", f"card_id 重复：{card_id}")
        index[card_id] = card
    return index


def card_id_for(card: TarotCard) -> str:
    """TarotCard → card_id（反查；牌库中不存在则抛 deck_integrity_mismatch）。"""
    for card_id, indexed in build_card_index().items():
        if indexed is card or indexed == card:
            return card_id
    raise DrawError("deck_integrity_mismatch", "牌不在当前牌库中")


def _compute_deck_revision() -> str:
    """牌面内容摘要：牌组任何文案/结构变化都会换版本（审计与一致性门）。"""
    lines = [
        f"{card_id}|{card.name}|{card.upright_keywords}|{card.reversed_keywords}"
        for card_id, card in sorted(build_card_index().items())
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


DECK_REVISION: str = _compute_deck_revision()

# ---------------------------------------------------------------------------
# 阵型白名单（合同 §3.1：不接受任意 k 或未知位置名）。
# ---------------------------------------------------------------------------

_SPREADS: dict[str, tuple[int, tuple[str, ...]]] = {
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
_POSITION_LABELS: dict[str, dict[str, str]] = {
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
    """阵型白名单校验：返回 (张数, 位置 id 序列)；非法 → invalid_spread。"""
    spread = _SPREADS.get(str(spread_id or ""))
    if spread is None:
        raise DrawError("invalid_spread", f"不支持的牌阵：{spread_id!r}")
    return spread


# ---------------------------------------------------------------------------
# 可审计 PRNG：统一 64bit 流接口 + Lemire 式拒绝采样（消除取模偏差）。
# ---------------------------------------------------------------------------


class SeededPrng:
    """注入 seed 的确定性 PRNG（测试固定回归用；seed=None 接系统安全熵）。

    ``next_below`` 用拒绝采样把 64bit 均匀流无偏压到 [0, bound)；拒绝阈值
    = 2^64 - (2^64 mod bound)，落在拒绝区的值丢弃重取——对任意 bound 都
    无取模偏差（含 bound 为权重总和这类非 2 幂输入）。
    """

    def __init__(self, seed: int | None = 0) -> None:
        self._rng = random.Random(seed)

    def next_u64(self) -> int:
        return self._rng.getrandbits(64)

    def next_below(self, bound: int) -> int:
        """无偏返回 [0, bound)；bound<=0 视为非法牌库/权重（防御）。"""
        if bound <= 0:
            raise DrawError("invalid_spread", f"采样边界非法：{bound}")
        if bound == 1:
            return 0
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64() & ((1 << 64) - 1)
            if value < limit:
                return value % bound

    def next_bit(self) -> int:
        """无偏单比特（正逆位 Bernoulli(0.5) 用）。"""
        return self.next_below(2)


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


# ---------------------------------------------------------------------------
# 每日运势：day_key 派生 + HMAC 种子 + 累计权重抽等级。
# ---------------------------------------------------------------------------

FORTUNE_RULE_VERSION = "v1"

# 合同 §3.1 默认等级与整数权重（总 100）；权重允许版本化调整。
FORTUNE_GRADES_V1: tuple[tuple[str, int], ...] = (
    ("大吉", 10),
    ("中吉", 25),
    ("小吉", 30),
    ("平", 25),
    ("小凶", 8),
    ("凶", 2),
)


def daily_fortune_day_key(
    principal_id: str, bot_id: str, local_date: str, rule_version: str
) -> str:
    """每日运势唯一键：principal+bot+本地日期+rule_version 派生（不含密钥）。

    密钥轮换不改 day_key → 存储命中既有行 → 当天不重抽（合同硬要求）。
    """
    material = f"fortune-day|{principal_id}|{bot_id}|{local_date}|{rule_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class FortuneOutcome:
    """每日运势抽取结果（grade + 审计材料）。"""

    grade: str
    key_id: str
    seed_digest: str


def _key_id_of(key: bytes) -> str:
    return hashlib.sha256(bytes(key)).hexdigest()[:8]


def draw_daily_fortune(
    key: bytes,
    principal_id: str,
    bot_id: str,
    local_date: str,
    rule_version: str,
) -> FortuneOutcome:
    """确定性每日运势：同 (key, principal, bot, 日期, rule_version) 同结果。

    种子 = HMAC-SHA256(key, "fortune-seed|" + day_key)；抽取走 HmacPrng
    的拒绝采样累计权重，无取模偏差。key_id/seed_digest 供审计落库。
    """
    day_key = daily_fortune_day_key(principal_id, bot_id, local_date, rule_version)
    seed_block = hmac.new(
        bytes(key), f"fortune-seed|{day_key}".encode(), hashlib.sha256
    ).digest()
    seed_digest = hashlib.sha256(seed_block).hexdigest()[:16]
    prng = HmacPrng(key, f"fortune-draw|{day_key}")
    total = sum(weight for _, weight in FORTUNE_GRADES_V1)
    point = prng.next_below(total)
    grade = FORTUNE_GRADES_V1[-1][0]
    cumulative = 0
    for name, weight in FORTUNE_GRADES_V1:
        cumulative += weight
        if point < cumulative:
            grade = name
            break
    return FortuneOutcome(
        grade=grade, key_id=_key_id_of(key), seed_digest=seed_digest
    )


# ---------------------------------------------------------------------------
# 塔罗抽取：Fisher-Yates 无放回 + 正逆位独立 Bernoulli(0.5)。
# ---------------------------------------------------------------------------


def draw_tarot(spread_id: str, prng: SeededPrng) -> list[dict[str, str]]:
    """按白名单阵型无放回抽牌；返回合同形态 cards（card_id/position_id/orientation）。"""
    count, positions = validate_spread(spread_id)
    card_ids = sorted(build_card_index())  # 确定性池序
    if count > len(card_ids):  # pragma: no cover - 白名单阵型恒 <= 78
        raise DrawError("invalid_spread", "牌阵张数超出牌库")
    pool = list(card_ids)
    for i in range(count):
        j = i + prng.next_below(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    cards: list[dict[str, str]] = []
    for position_id, card_id in zip(positions, pool[:count]):
        orientation = "reversed" if prng.next_bit() else "upright"
        cards.append(
            {
                "card_id": card_id,
                "position_id": position_id,
                "orientation": orientation,
            }
        )
    return cards


# ---------------------------------------------------------------------------
# DrawStore：SQLite 持久化（路径注入；每操作独立连接，campus_store 同风格）。
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_fortune (
    day_key      TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    bot_id       TEXT NOT NULL,
    local_date   TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    grade        TEXT NOT NULL,
    key_id       TEXT NOT NULL,
    seed_digest  TEXT NOT NULL,
    occurred_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_fortune_date ON daily_fortune(local_date);
CREATE TABLE IF NOT EXISTS tarot_draws (
    draw_id            TEXT PRIMARY KEY,
    principal_id       TEXT NOT NULL,
    bot_id             TEXT NOT NULL,
    spread_id          TEXT NOT NULL,
    source             TEXT NOT NULL DEFAULT 'random',
    cards_json         TEXT NOT NULL,
    expected_count     INTEGER NOT NULL,
    algorithm_revision TEXT NOT NULL,
    deck_revision      TEXT NOT NULL,
    occurred_at        TEXT NOT NULL,
    local_day          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tarot_draws_subject
    ON tarot_draws(principal_id, bot_id, local_day, source);
"""

_TAROT_COLUMNS = (
    "draw_id, principal_id, bot_id, spread_id, source, cards_json, "
    "expected_count, algorithm_revision, deck_revision, occurred_at, local_day"
)


def _utc(dt: datetime) -> datetime:
    """统一 aware UTC（naive 视作 UTC），保证冷却时长比较不因时区漂移。"""
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


class DrawStore:
    """抽签库：每日运势 day_key 幂等 + 塔罗 draw_id 幂等 + 配额计数。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None（自动提交）：写路径显式 BEGIN IMMEDIATE 串行化，
        # 配额判定与插入在同一写锁事务内，并发不超卖；读路径免事务即时可见。
        connection = sqlite3.connect(
            str(self.db_path), timeout=10, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        return connection

    # ── 每日运势：day_key 唯一，幂等落库 ──

    def get_daily_fortune(self, day_key: str) -> sqlite3.Row | None:
        """按 day_key 读既有运势行；无则 None（当天未抽过）。"""
        with contextlib.closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM daily_fortune WHERE day_key = ?", (str(day_key),)
            ).fetchone()

    def get_or_save_daily_fortune(
        self,
        *,
        day_key: str,
        principal_id: str,
        bot_id: str,
        local_date: str,
        rule_version: str,
        key_id: str,
        seed_digest: str,
        grade: str,
        occurred_at: str,
    ) -> tuple[sqlite3.Row, bool]:
        """幂等写入：day_key 已存在（含并发/重启/密钥轮换）返回既有行。

        返回 (row, created)；created 表示本次调用是否真正写入。并发竞态下
        输者读到赢者的行（唯一约束兜底），全天结果恒一致。
        """
        with contextlib.closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT * FROM daily_fortune WHERE day_key = ?", (str(day_key),)
            ).fetchone()
            if existing is not None:
                return existing, False
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO daily_fortune (
                    day_key, principal_id, bot_id, local_date, rule_version,
                    grade, key_id, seed_digest, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(day_key),
                    str(principal_id),
                    str(bot_id),
                    str(local_date),
                    str(rule_version),
                    str(grade),
                    str(key_id),
                    str(seed_digest),
                    str(occurred_at),
                ),
            )
            created = cursor.rowcount > 0
            row = connection.execute(
                "SELECT * FROM daily_fortune WHERE day_key = ?", (str(day_key),)
            ).fetchone()
            return row, created

    # ── 塔罗抽取：draw_id 幂等 + 事务内配额 ──

    def get_tarot_draw(self, draw_id: str) -> sqlite3.Row | None:
        """按 draw_id 读既有抽取行；无则 None。"""
        with contextlib.closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM tarot_draws WHERE draw_id = ?", (str(draw_id),)
            ).fetchone()

    def record_tarot_draw(
        self,
        *,
        draw_id: str,
        principal_id: str,
        bot_id: str,
        spread_id: str,
        source: str,
        cards_json: str,
        expected_count: int,
        algorithm_revision: str,
        deck_revision: str,
        occurred_at: datetime,
        local_day: str,
        cooldown_seconds: int = 60,
        daily_limit: int = 20,
        enforce_rate: bool = True,
    ) -> tuple[sqlite3.Row, bool]:
        """幂等记录一次塔罗抽取；随机抽取在写锁事务内判冷却与每日配额。

        - 同 draw_id 重试：返回既有行（不重抽、不重复计数）。
        - ``source="random"`` 且 enforce_rate：同一主体当日超过 ``daily_limit``
          次、或距上次随机抽取不足 ``cooldown_seconds`` 秒 → rate_limited。
        - ``source="daily"``（每日一抽幂等重读）：不计入配额。
        """
        occurred_iso = _utc(occurred_at).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM tarot_draws WHERE draw_id = ?", (str(draw_id),)
            ).fetchone()
            if existing is not None:
                connection.execute("COMMIT")
                return existing, False
            if enforce_rate and source == "random":
                count_today = connection.execute(
                    """
                    SELECT COUNT(*) FROM tarot_draws
                    WHERE principal_id = ? AND bot_id = ?
                      AND local_day = ? AND source = 'random'
                    """,
                    (str(principal_id), str(bot_id), str(local_day)),
                ).fetchone()[0]
                if count_today >= max(0, int(daily_limit)):
                    connection.execute("ROLLBACK")
                    raise DrawError("rate_limited", "今日塔罗抽取次数已用完")
                last_iso = connection.execute(
                    """
                    SELECT MAX(occurred_at) FROM tarot_draws
                    WHERE principal_id = ? AND bot_id = ? AND source = 'random'
                    """,
                    (str(principal_id), str(bot_id)),
                ).fetchone()[0]
                if last_iso:
                    elapsed = (
                        _utc(occurred_at) - datetime.fromisoformat(last_iso)
                    ).total_seconds()
                    if elapsed < float(cooldown_seconds):
                        connection.execute("ROLLBACK")
                        raise DrawError("rate_limited", "塔罗抽取冷却中")
            connection.execute(
                f"INSERT INTO tarot_draws ({_TAROT_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(draw_id),
                    str(principal_id),
                    str(bot_id),
                    str(spread_id),
                    str(source),
                    str(cards_json),
                    int(expected_count),
                    str(algorithm_revision),
                    str(deck_revision),
                    occurred_iso,
                    str(local_day),
                ),
            )
            row = connection.execute(
                "SELECT * FROM tarot_draws WHERE draw_id = ?", (str(draw_id),)
            ).fetchone()
            connection.execute("COMMIT")
            return row, True
        except sqlite3.IntegrityError:
            # 并发下另一连接先插入同 draw_id：读回既有行（幂等语义）。
            try:
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError:  # pragma: no cover - 事务已结束
                pass
            row = connection.execute(
                "SELECT * FROM tarot_draws WHERE draw_id = ?", (str(draw_id),)
            ).fetchone()
            return row, False
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# 持久行 → 牌面重建（解读与渲染只消费持久行；篡改 → deck_integrity_mismatch）。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterpretationContext:
    """解读上下文：从持久行校验重建的合同形态牌面。"""

    draw_id: str
    spread_id: str
    cards: tuple[dict[str, str], ...]


def _validated_cards(row: Any) -> tuple[str, list[dict[str, str]]]:
    """校验持久行牌面：数量/位置/牌库存在性/朝向/牌库版本全部吻合才放行。

    任何不符（含 spread_id 被改、JSON 损坏）→ deck_integrity_mismatch。
    """
    spread_id = str(row["spread_id"])
    try:
        count, positions = validate_spread(spread_id)
    except DrawError as exc:
        raise DrawError("deck_integrity_mismatch", exc.args[0]) from exc
    if int(row["expected_count"]) != count:
        raise DrawError(
            "deck_integrity_mismatch", "expected_count 与牌阵定义不符"
        )
    if str(row["deck_revision"]) != DECK_REVISION:
        raise DrawError("deck_integrity_mismatch", "牌库版本与持久行不符")
    try:
        cards = json.loads(str(row["cards_json"]))
    except (TypeError, ValueError) as exc:
        raise DrawError("deck_integrity_mismatch", "牌面 JSON 损坏") from exc
    if not isinstance(cards, list) or len(cards) != count:
        raise DrawError("deck_integrity_mismatch", "牌数与牌阵定义不符")
    index = build_card_index()
    for item, position_id in zip(cards, positions):
        if not isinstance(item, dict):
            raise DrawError("deck_integrity_mismatch", "牌面结构非法")
        if item.get("position_id") != position_id:
            raise DrawError("deck_integrity_mismatch", "位置序列不符")
        if item.get("card_id") not in index:
            raise DrawError("deck_integrity_mismatch", "牌面含牌库之外的牌")
        if item.get("orientation") not in {"upright", "reversed"}:
            raise DrawError("deck_integrity_mismatch", "朝向字段非法")
    return spread_id, cards


def build_interpretation_context(row: Any) -> InterpretationContext:
    """持久行 → 解读上下文（LLM 解读唯一合法输入；函数上不可能换牌）。"""
    spread_id, cards = _validated_cards(row)
    return InterpretationContext(
        draw_id=str(row["draw_id"]), spread_id=spread_id, cards=tuple(cards)
    )


def rebuild_drawn_cards(row: Any) -> list[DrawnCard]:
    """持久行 → DrawnCard 列表（渲染复用既有 format_single/three_text 口径）。"""
    spread_id, cards = _validated_cards(row)
    index = build_card_index()
    labels = _POSITION_LABELS[spread_id]
    return [
        DrawnCard(
            card=index[item["card_id"]],
            is_reversed=item["orientation"] == "reversed",
            position=labels.get(item["position_id"], item["position_id"]),
        )
        for item in cards
    ]
