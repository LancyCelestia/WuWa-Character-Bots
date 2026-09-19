"""V2.1 S12 每日运势算法半边：HMAC 种子派生 + 可审计 PRNG + 累计权重抽取。

合同来源：docs/design/backend-v2-product-extensions.md §3（V21-DIVINATION-002）。

- 等级与整数权重（总 100）：大吉10 / 中吉25 / 小吉30 / 平25 / 小凶8 / 凶2；
  权重允许版本化调整（换 ``FORTUNE_RULE_VERSION``），但禁止按用户付费/好感
  秘密改变概率——抽取输入只有 (密钥, principal, bot, 本地日期, rule_version)。
- 种子 = 服务端 HMAC-SHA256（密钥由核心注入，不暴露给插件/客户端）；
  day_key 派生**不含密钥** → 密钥轮换不换 day_key → 存储命中既有行，
  当天不重抽（合同硬要求）。审计保存 key_id（密钥摘要前 8 位）与
  seed_digest（种子摘要前 16 位）；不宣称用户可独立验证未公开种子的公平性。
- 可审计 PRNG：``next_u64`` 统一 64bit 流；``rejection_sample_below`` 用
  拒绝采样把流无偏压到 [0, bound)——拒绝阈值 = 2^64 - (2^64 mod bound)，
  对任意 bound（含权重总和这类非 2 幂输入）零取模偏差。
- 随机源：生产 = ``SystemPrng``（secrets 系统安全随机）；测试/审计重放 =
  ``SeededPrng``（random.Random(int) 跨进程稳定，绝不使用 Python hash）
  或 ``HmacPrng``（同 key 同 material 必然同序列）。
- 纯标准库，零网络零第三方。
"""

from __future__ import annotations

import hashlib
import hmac
import random
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = [
    "FORTUNE_ALGORITHM_REVISION",
    "FORTUNE_GRADES_V1",
    "FORTUNE_RULE_VERSION",
    "AuditPrng",
    "FortuneSeed",
    "HmacPrng",
    "SeededPrng",
    "SystemPrng",
    "bernoulli_bit",
    "derive_fortune_seed",
    "draw_fortune_grade",
    "fortune_day_key",
    "rejection_sample_below",
]

# ---------------------------------------------------------------------------
# 等级与权重（合同 §3.1 默认表，总 100；版本化调整只改这里 + rule_version）。
# ---------------------------------------------------------------------------

FORTUNE_RULE_VERSION = "v1"

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


# ---------------------------------------------------------------------------
# 可审计 PRNG 协议与实现。
# ---------------------------------------------------------------------------


@runtime_checkable
class AuditPrng(Protocol):
    """可审计随机流：唯一原语是均匀 64bit 整数（重放/审计的最小接口）。"""

    def next_u64(self) -> int: ...


class SeededPrng:
    """注入 seed 的确定性 PRNG（测试固定回归用）。

    ``random.Random(int)`` 的 Mersenne Twister 跨进程/跨版本稳定，绝不经过
    Python ``hash()``（受 PYTHONHASHSEED 影响不可重放）。
    """

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def next_u64(self) -> int:
        return self._rng.getrandbits(64)


class SystemPrng:
    """生产随机源：操作系统安全熵（secrets），不可重放、不落盘。"""

    def next_u64(self) -> int:
        return secrets.randbits(64)


class HmacPrng:
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

    拒绝区 = [2^64 - (2^64 mod bound), 2^64)；落在拒绝区的值丢弃重取。
    bound <= 0 视为非法权重/牌库（防御，映射 invalid_spread 由服务层翻译）。
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
# day_key 派生 + 种子材料。
# ---------------------------------------------------------------------------


def fortune_day_key(
    principal_id: str, bot_id: str, local_date: str, rule_version: str
) -> str:
    """每日运势唯一键：principal+bot+本地日期+rule_version（**不含密钥**）。

    密钥轮换不改 day_key → 存储命中既有行 → 当天不重抽。
    """
    material = f"fortune-day|{principal_id}|{bot_id}|{local_date}|{rule_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class FortuneSeed:
    """一次运势抽取的种子材料（抽取 + 审计三件套）。"""

    prng: HmacPrng
    day_key: str
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
    """HMAC-SHA256 派生种子：同 (密钥, 主体, 日期, 规则版本) 同结果。

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


def local_date_for(moment: datetime, timezone_id: str) -> str:
    """可信时刻 → 指定时区的本地日期（YYYY-MM-DD；日期来源只信 context）。"""
    return moment.astimezone(_zone(timezone_id)).date().isoformat()


def _zone(timezone_id: str):  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    return ZoneInfo(timezone_id)
