"""兼容再导出垫片 + 聊天侧读面助手（V2.1 S12 抽签，WP9 收编 2026-09-21）。

收编前这里是「占卜存储的第二套实现」：自带 ``DrawError``、``DrawStore``（另开一
个库文件、另建两张表）、以及算法半边 ``build_card_index``/``card_id_for``/
``DECK_REVISION``/``SeededPrng``/``HmacPrng``/``validate_spread``/``daily_fortune_day_key``
的第二份拷贝，结果同一次抽牌在聊天侧与控制面 REST 侧各落一处、互相看不见。

按用户裁定 11.C「两套各自缺半边 ⇒ 按面各取一边」收编：

- **算法真身** → ``data/deck_math.py``（本文件只再导出，不实现）；
- **存储真身** → ``store/draw_store.py`` 的 ``DrawStore``/``DrawRecord``/``QuotaPolicy``
  （``draws`` 表 + ``idempotency_key`` UNIQUE + ``(kind, dedupe_key)`` 部分唯一索引
  + 写锁事务内配额 + ``algorithm_revision``/``deck_revision``/``key_id``/``seed_digest``
  版本列），本文件**不再开库、不再建表、不再持有连接**；
- **异常只留一颗** → ``store`` 的 ``DrawError``（旧 ``data`` 那颗删除，它连
  ``.message`` 都没有，喂给 REST 投影层会 ``AttributeError``）。

## 旧表里的历史数据怎么办（铁律 2）

``daily_fortune`` / ``tarot_draws`` 两张表**不 DROP、不清空、不改语义**：本文件不
再触碰它们，任何既有库文件里的表与行原样留在盘上。收编取证的构造点普查与运行
数据只读探针都证明**本部署里这两张表从来没有存在过**（聊天能力从未被注入过存储
实例、``.env``/``config`` 从无指向它们的键、Runtime 数据根 39 个 SQLite 零命中），
因此本波**没有数据搬运**，也就不需要备份；若日后在任何库文件里发现历史行，按
``docs/design/divination-consolidation-20260921.md`` §二-3 走「双读影子 + 人数/
条数/按 day_key 分组数三项守恒断言 + 迁移前 %TEMP% 备份」，搬运脚本归主会话。
守恒与「新代码不建旧表」的锁见 ``tests/test_divination_consolidation_wp9.py``。

纯标准库 + 域内真身，零网络、零 IO。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.divination.data import deck_math
from plugins.bot_unified_runtime.domains.divination.data.tarot import DrawnCard
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DEFAULT_TAROT_COOLDOWN_SECONDS,
    DEFAULT_TAROT_DAILY_LIMIT,
    DrawError,
    DrawRecord,
    DrawStore,
    QuotaPolicy,
)

__all__ = [
    "DECK_REVISION",
    "DEFAULT_TAROT_COOLDOWN_SECONDS",
    "DEFAULT_TAROT_DAILY_LIMIT",
    "FORTUNE_ALGORITHM_REVISION",
    "FORTUNE_GRADES_V1",
    "FORTUNE_RULE_VERSION",
    "TAROT_ALGORITHM_REVISION",
    "TAROT_DAILY_ALGORITHM_REVISION",
    "DrawError",
    "DrawRecord",
    "DrawStore",
    "DrawnFortune",
    "FortuneOutcome",
    "HmacPrng",
    "QuotaPolicy",
    "SeededPrng",
    "SystemPrng",
    "build_card_index",
    "card_id_for",
    "daily_fortune_day_key",
    "draw_daily_fortune",
    "draw_tarot",
    "fortune_day_key",
    "rebuild_drawn_cards",
    "validate_spread",
]

# ── 算法真身再导出（同一对象，不是副本）──
DECK_REVISION = deck_math.DECK_REVISION
FORTUNE_GRADES_V1 = deck_math.FORTUNE_GRADES_V1
FORTUNE_RULE_VERSION = deck_math.FORTUNE_RULE_VERSION
FORTUNE_ALGORITHM_REVISION = deck_math.FORTUNE_ALGORITHM_REVISION
TAROT_ALGORITHM_REVISION = deck_math.TAROT_ALGORITHM_REVISION
TAROT_DAILY_ALGORITHM_REVISION = deck_math.TAROT_DAILY_ALGORITHM_REVISION
build_card_index = deck_math.build_card_index
card_id_for = deck_math.card_id_for
validate_spread = deck_math.validate_spread
SeededPrng = deck_math.SeededPrng
HmacPrng = deck_math.HmacPrng
SystemPrng = deck_math.SystemPrng

# 日程键：聊天侧旧名 → 真身唯一实现（同函数同对象，值逐字节不变）。
daily_fortune_day_key = deck_math.fortune_day_key
fortune_day_key = deck_math.fortune_day_key

# 等级抽取结果：旧 ``FortuneOutcome`` 与真身 ``DrawnFortune`` 是同一个东西的两个名字。
DrawnFortune = deck_math.DrawnFortune
FortuneOutcome = deck_math.DrawnFortune
draw_daily_fortune = deck_math.draw_daily_fortune


def draw_tarot(spread_id: str, prng: deck_math.AuditPrng) -> list[dict[str, str]]:
    """聊天侧旧调用形态（``list``）→ 真身发牌（``tuple``）；值逐字节不变。"""
    return list(deck_math.draw_tarot_cards(spread_id, prng))


def rebuild_drawn_cards(record: Any) -> list[DrawnCard]:
    """持久行（``DrawRecord``）→ ``DrawnCard`` 列表，供既有文本渲染口径复用。

    牌面先过全域唯一的完整性门 ``deck_math.validated_tarot_cards``：篡改阵型/
    牌数/牌序/牌库外牌/朝向/牌库版本一律 ``deck_integrity_mismatch``——聊天正文
    与控制面解读看到的是同一份校验结果，不存在第二道门。
    """
    spread_id, cards = deck_math.validated_tarot_cards(record)
    index = deck_math.build_card_index()
    labels = deck_math.POSITION_LABELS[spread_id]
    return [
        DrawnCard(
            card=index[item["card_id"]],
            is_reversed=item["orientation"] == "reversed",
            position=labels.get(item["position_id"], item["position_id"]),
        )
        for item in cards
    ]
