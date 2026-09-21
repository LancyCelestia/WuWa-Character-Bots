"""v21r2 R5 热区回归：两餐开场 6 变体确定性轮换（R6 草案落地，C② 收编）。

改前：`_build_meal_push_text` 单句 f-string（无变体无轮换），R6 席按文件域
互斥纪律登记坐标待接手席落地。改后：`_MEAL_OPENERS` 6 变体池 + 复用
`domains/assistant/daily/store/daily_assist.pick_variant` 游标机制（同池连发不重复、确定性循环）。

锁死行为（全离线）：
- 一整轮 6 次调用零重复（池规模=6 且全部命中）；
- 第二轮逐字复现第一轮（游标确定性，无随机）；
- 食物名与括号注记（suffix）逐字保留；开场池只动措辞，不改信息面。

复跑：
  PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_v21r2_hotzone_meal_variants.py -q \
      --basetemp=$TEMP/v21r2-r5c -p no:cacheprovider
"""
from __future__ import annotations

from plugins.bot_unified_runtime import _MEAL_OPENERS, _build_meal_push_text
from plugins.bot_unified_runtime.character.daily_assist import meal_display_name


def test_meal_push_text_rotates_through_all_six_variants_without_repeat() -> None:
    first_cycle = [
        _build_meal_push_text("番茄炒蛋") for _ in range(len(_MEAL_OPENERS))
    ]
    assert len(_MEAL_OPENERS) == 6
    assert len(set(first_cycle)) == len(_MEAL_OPENERS)


def test_meal_push_text_rotation_is_deterministic_across_cycles() -> None:
    first_cycle = [
        _build_meal_push_text("番茄炒蛋") for _ in range(len(_MEAL_OPENERS))
    ]
    second_cycle = [
        _build_meal_push_text("番茄炒蛋") for _ in range(len(_MEAL_OPENERS))
    ]
    assert second_cycle == first_cycle


def test_meal_push_text_keeps_name_and_suffix_intact() -> None:
    item = "红烧肉（大份）"
    name = meal_display_name(item)
    suffix = item[len(name):].strip()
    text = _build_meal_push_text(item)
    assert name == "红烧肉"
    assert suffix == "（大份）"
    assert text.endswith(f"{name}{suffix}")


def test_every_pool_variant_carries_food_name_slot() -> None:
    for template in _MEAL_OPENERS:
        rendered = template.format(name="番茄炒蛋", suffix="")
        assert "番茄炒蛋" in rendered
