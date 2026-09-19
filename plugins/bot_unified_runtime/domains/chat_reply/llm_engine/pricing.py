"""每模型价格表解析与调用成本核算。

- 价格单位：元（CNY）/ 每百万 token；分别配置 input 与 output。
- 成本按**调用时刻**的价格记账（记录为整数毫厘 cost_milli），价格表后续
  调整不影响历史账单；峰谷差价因此天然正确。
- 未配置价格的模型不产生费用记录（调用标记 unpriced）。
"""

from __future__ import annotations

import json

# 推理强度档位后缀：同一家族不同档位（gemini-3.8-flash-high 等）共享一份价格，
# 归一化时从名称尾部剥掉（反复剥，容忍组合后缀），全模型通用。
_EFFORT_SUFFIXES = frozenset({"high", "xhigh", "max", "medium", "low"})


def model_family_key(model_name: str) -> str:
    """模型名 -> 家族键（casefold + 去推理强度后缀），用量合并/价格匹配共用。

    例：Gemini-3.8-Flash / gemini-3.8-flash / gemini-3.8-flash-high
    都归一到 ``gemini-3.8-flash``。纯大小写差异天然合并；-high/-low/-medium/
    -xhigh/-max 尾段被视为档位而非型号（至少保留一段，避免剥成空串）。
    """
    text = str(model_name or "").strip().casefold()
    if not text:
        return ""
    parts = text.split("-")
    while len(parts) > 1 and parts[-1] in _EFFORT_SUFFIXES:
        parts.pop()
    return "-".join(parts)


def lookup_model_price(
    model_name: str,
    prices: dict[str, dict[str, float]],
) -> dict[str, float] | None:
    """价格表查找：精确 → casefold → 家族键。查无返回 None（未配置）。"""
    if not prices:
        return None
    key = str(model_name or "").strip()
    entry = prices.get(key)
    if entry:
        return entry
    folded = key.casefold()
    for name, candidate in prices.items():
        if name.strip().casefold() == folded:
            return candidate
    family = model_family_key(key)
    if not family:
        return None
    for name, candidate in prices.items():
        if model_family_key(name) == family:
            return candidate
    return None


def parse_model_prices(raw: object) -> dict[str, dict[str, float]]:
    """解析价格表：dict 或 JSON 字符串 -> {模型名: {价键: 元/1M}}。

    价键：``input``/``output`` 必填口径，``cache_read``/``cache_creation``
    （缓存读/缓存创建，2026-09-18 补）、``per_call``（按次计费，元/请求）。
    **只在来源条目里确实出现时写键**——缺键 ≠ 0 元，避免把"未配置缓存价"
    静默读成"缓存免费"。

    非法条目静默跳过；各价键允许 0（免费），负数视为未配置。
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
        for key in ("input", "output", "cache_read", "cache_creation", "per_call"):
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


def registry_model_prices(
    registry: object,
) -> dict[str, dict[str, float]]:
    """模型注册表 -> 价格表（2026-09-18 价格单源化）。

    背景：注册表条目（``runtime_settings_<profile>.json`` 的 ``price_in``/
    ``price_out``/``price_cache_read``/``price_cache_creation``/``price_per_call``）
    此前只喂 V2.1 计费链路，遗留报表/记账链路读的是另一份 ``BOT_MODEL_PRICES``，
    于是"导入了价目表但账单仍显示未计价"。此函数把注册表投影成
    ``parse_model_prices`` 同一口径，供装配期/报表合并。

    键用条目里的 ``model``（真模型名）而非 model_id（渠道 id）：同一模型多个
    渠道条目并存时，取**首个有效价**，后续同模型条目只补空缺价键——渠道价差
    由 V2.1 计费链路按渠道精确处理，遗留链路按模型级口径足够。
    """
    if not isinstance(registry, dict):
        return {}
    prices: dict[str, dict[str, float]] = {}
    for entry in registry.values():
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model") or "").strip()
        if not model:
            continue
        target = prices.setdefault(model, {})
        for source_key, price_key in (
            ("price_in", "input"),
            ("price_out", "output"),
            ("price_cache_read", "cache_read"),
            ("price_cache_creation", "cache_creation"),
            ("price_per_call", "per_call"),
        ):
            if price_key in target:
                continue
            value = entry.get(source_key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if number < 0:
                continue
            target[price_key] = number
        if not target:
            prices.pop(model, None)
    return prices


def merge_model_prices(
    *sources: object,
) -> dict[str, dict[str, float]]:
    """多份价格表按序合并：后者只覆盖/补齐同名模型的同名价键。

    用于「注册表（基准）→ BOT_MODEL_PRICES（用户手工覆盖）→ 内置兜底」的
    优先级链；空/非法来源自动跳过，调用方不必逐个判空。
    """
    merged: dict[str, dict[str, float]] = {}
    for source in sources:
        parsed = parse_model_prices(source)
        for model, entry in parsed.items():
            merged.setdefault(model, {}).update(entry)
    return merged


def model_call_cost_milli(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    prices: dict[str, dict[str, float]],
    *,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> tuple[int, bool]:
    """单次调用成本（毫厘，1 元 = 1000 毫厘）；未配置价格返回 (0, False)。

    查找走 精确 → casefold → 家族键 归一化链（lookup_model_price）：
    供应商回报 ``Gemini-3.8-Flash``/``gemini-3.8-flash-high`` 也能命中
    价格表里的 ``gemini-3.8-flash``，不再静默记 0。

    缓存计价（2026-09-18 补；语义与 ``billing_pricing.SCHEMA_SEMANTICS`` 的
    ``openai_chat_v1`` 一致）：

        ordinary_input = prompt − cache_read
        cost = ordinary_input×in + cache_read×read价
             + cache_creation×create价 + completion×out

    - ``prompt_tokens`` 视为**已含**缓存读取（OpenAI/DeepSeek 口径）；
      缓存创建量按"不含于 prompt"处理（Anthropic 口径），二者不重复扣减。
    - 缺缓存价键时回退普通输入价——**这是有意的**：多数渠道缓存读与输入同价
      或更便宜，宁可略高估也不记 0；要精确请在价目表里写 ``cache_read``/
      ``cache_creation``（``/bot model price <名> cache_read=…``）。
    - ``ordinary_input`` 负值（上游把缓存量报得比 prompt 还大）夹到 0，不报负价。
    """
    entry = lookup_model_price(model_name, prices)
    if not entry:
        return 0, False
    input_price = float(entry.get("input", 0.0))
    output_price = float(entry.get("output", 0.0))
    read_price = float(entry.get("cache_read", input_price))
    create_price = float(entry.get("cache_creation", input_price))
    read_tokens = max(0, int(cache_read_tokens))
    create_tokens = max(0, int(cache_creation_tokens))
    ordinary_tokens = max(0, int(prompt_tokens) - read_tokens)
    cost = (
        ordinary_tokens / 1_000_000 * input_price
        + read_tokens / 1_000_000 * read_price
        + create_tokens / 1_000_000 * create_price
        + max(0, int(completion_tokens)) / 1_000_000 * output_price
    )
    return round(cost * 1000), True


def format_milli_yuan(cost_milli: int) -> str:
    """毫厘 -> 人民币文本（保留两位小数）。"""
    return f"{max(0, int(cost_milli)) / 1000:.2f}"


__all__ = [
    "format_milli_yuan",
    "lookup_model_price",
    "merge_model_prices",
    "model_call_cost_milli",
    "model_family_key",
    "parse_model_prices",
    "registry_model_prices",
]
