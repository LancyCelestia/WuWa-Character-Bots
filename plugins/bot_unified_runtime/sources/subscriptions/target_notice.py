"""订阅目标解析的「显式平台提示」异常（审查 J-01/J-06 接线）。

语义：平台**认得**这个目标（URL/冒号形态命中），但当前不可用
（已摘除/缺凭证/未接通）——区别于「不是我家的」泛化 ValueError。
解析循环（capabilities/subscribe_v2.py）遇到本类型时优先作为
用户可见原因出面，不被其它平台的「无法识别」泛化提示覆盖。
"""

from __future__ import annotations

__all__ = ["SubscriptionTargetNotice"]


class SubscriptionTargetNotice(ValueError):
    """平台可识别但暂不可用的显式提示；消息即用户可见文案。"""
