"""兼容再导出垫片：塔罗抽取算法半边（真身见 ``data/deck_math.py``，WP9 收编）。

收编前本文件自带 ``build_card_index`` / ``card_id_for`` / ``_compute_deck_revision``
/ ``DECK_REVISION`` / ``SPREADS`` / ``POSITION_LABELS`` / ``validate_spread`` /
``draw_tarot_cards`` 的**第二份拷贝**（与 ``data/draw_store.py`` 各一份，实测数值
逐字节相同）。2026-09-21 按用户裁定 11.C「算法真身取 data 侧」把实现收进
``domains/divination/data/deck_math.py`` 唯一一份，本模块只保留历史导入面：
``service/divination_service.py``、``api/facet.py``、``tests/test_divination_service_v21.py``
等既有消费方的 import 路径逐字不变（同一对象，非副本）。

退役条件：全域改用 ``data.deck_math`` 直连后本文件可删（需同步改测试导入面，
由主会话在生成物收敛的收尾波集中做）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.divination.data.deck_math import (
    DECK_REVISION,
    POSITION_LABELS,
    SPREADS,
    TAROT_ALGORITHM_REVISION,
    TAROT_DAILY_ALGORITHM_REVISION,
    AuditPrng,
    DrawError,
    SeededPrng,
    _compute_deck_revision,
    bernoulli_bit,
    build_card_index,
    card_id_for,
    draw_tarot_cards,
    rejection_sample_below,
    validate_spread,
    validated_tarot_cards,
)

__all__ = [
    "DECK_REVISION",
    "POSITION_LABELS",
    "SPREADS",
    "TAROT_ALGORITHM_REVISION",
    "TAROT_DAILY_ALGORITHM_REVISION",
    "AuditPrng",
    "DrawError",
    "SeededPrng",
    "_compute_deck_revision",
    "bernoulli_bit",
    "build_card_index",
    "card_id_for",
    "draw_tarot_cards",
    "rejection_sample_below",
    "validate_spread",
    "validated_tarot_cards",
]
