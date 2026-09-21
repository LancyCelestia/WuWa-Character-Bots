"""兼容再导出垫片：每日运势算法半边（真身见 ``data/deck_math.py``，WP9 收编）。

收编前本文件自带 ``SeededPrng`` / ``SystemPrng`` / ``HmacPrng`` /
``rejection_sample_below`` / ``bernoulli_bit`` / ``fortune_day_key`` /
``FORTUNE_GRADES_V1`` / ``FORTUNE_RULE_VERSION`` / ``FORTUNE_ALGORITHM_REVISION`` /
``derive_fortune_seed`` / ``draw_fortune_grade`` / ``local_date_for`` 的**第二份
拷贝**（与 ``data/draw_store.py`` 各一份，实测数值逐字节相同）。2026-09-21 按
用户裁定 11.C「算法真身取 data 侧」收进 ``data/deck_math.py`` 唯一一份，本模块
只保留历史导入面（``service/divination_service.py``、``api/facet.py``、
``tests/`` 既有消费方 import 路径逐字不变，同一对象非副本）。

退役条件：同 ``service/tarot_draw.py``——全域直连真身后由收尾波统一删除。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.divination.data.deck_math import (
    FORTUNE_ALGORITHM_REVISION,
    FORTUNE_GRADES_V1,
    FORTUNE_RULE_VERSION,
    AuditPrng,
    DrawError,
    FortuneSeed,
    HmacPrng,
    SeededPrng,
    SystemPrng,
    bernoulli_bit,
    derive_fortune_seed,
    draw_fortune_grade,
    fortune_day_key,
    fortune_rule_version_of,
    local_date_for,
    rejection_sample_below,
)

__all__ = [
    "FORTUNE_ALGORITHM_REVISION",
    "FORTUNE_GRADES_V1",
    "FORTUNE_RULE_VERSION",
    "AuditPrng",
    "DrawError",
    "FortuneSeed",
    "HmacPrng",
    "SeededPrng",
    "SystemPrng",
    "bernoulli_bit",
    "derive_fortune_seed",
    "draw_fortune_grade",
    "fortune_day_key",
    "fortune_rule_version_of",
    "local_date_for",
    "rejection_sample_below",
]
