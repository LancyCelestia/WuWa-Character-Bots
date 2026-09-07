"""每模型价格表解析与调用成本核算。

- 价格单位：元（CNY）/ 每百万 token；分别配置 input 与 output。
- 成本按**调用时刻**的价格记账（记录为整数毫厘 cost_milli），价格表后续
  调整不影响历史账单；峰谷差价因此天然正确。
- 未配置价格的模型不产生费用记录（调用标记 unpriced）。
"""

from __future__ import annotations

import json


def parse_model_prices(raw: object) -> dict[str, dict[str, float]]:
    """解析价格表：dict 或 JSON 字符串 -> {模型名: {"input": 元/1M, "output": 元/1M}}。

    非法条目静默跳过；input/output 允许 0（免费），负数视为未配置。
    """
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    prices: dict[str, dict[str, float]] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        parsed: dict[str, float] = {}
        for key in ("input", "output"):
            value = entry.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if number < 0:
                continue
            parsed[key] = number
        if parsed:
            prices[str(name).strip()] = parsed
    return prices


def model_call_cost_milli(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    prices: dict[str, dict[str, float]],
) -> tuple[int, bool]:
    """单次调用成本（毫厘，1 元 = 1000 毫厘）；未配置价格返回 (0, False)。"""
    entry = prices.get(str(model_name or "").strip())
    if not entry:
        return 0, False
    input_price = float(entry.get("input", 0.0))
    output_price = float(entry.get("output", 0.0))
    cost = (
        max(0, int(prompt_tokens)) / 1_000_000 * input_price
        + max(0, int(completion_tokens)) / 1_000_000 * output_price
    )
    return round(cost * 1000), True


def format_milli_yuan(cost_milli: int) -> str:
    """毫厘 -> 人民币文本（保留两位小数）。"""
    return f"{max(0, int(cost_milli)) / 1000:.2f}"


__all__ = [
    "format_milli_yuan",
    "model_call_cost_milli",
    "parse_model_prices",
]
