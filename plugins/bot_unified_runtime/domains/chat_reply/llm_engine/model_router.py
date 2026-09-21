"""模型路由：多模型注册、规则自动选型、手动覆盖、失败自动切换。

支持的模型由 ``BOT_MODEL_REGISTRY`` 注册（OpenAI 兼容接口），例如
gpt-5.6-terra/luna/sol、deepseek-v4-pro、kimi-k3。每个条目：

    {
      "id": "qian-terra",
      "model": "gpt-5.6-terra",
      "base_url": "https://newapi.qianqianye.com/v1",
      "api_key": "env:BOT_API_KEY_QIANQIANYE",
      "group": "qian",
      "tags": ["fast", "strong"],
      "priority": 1                            # 越小越先选
    }

``api_key`` 也支持列表；同模型可按列表顺序做多密钥故障转移。
不同令牌分组应使用不同 ``env:BOT_API_KEY_*`` 槽位。

标签即思考强度档位（2026-09 改版）：deepseek/glm/kimi/minimax =
low,high,max；gpt/grok = low,medium,high,xhigh；gemini = low,medium,high。
普通任务默认思考强度 = 家族基线（baseline_effort，家族最低档）；
条目可用 ``effort`` 字段显式指定（含 off）。
请求时按 条目 effort > 全局 BOT_CHAT_REASONING_EFFORT > 家族基线档
发送 ``reasoning_effort``（接口不支持时自动去参重试）。
复杂任务（长文本/教程/排查/分析/写作类关键词）会把来自全局/家族基线的
档位临时升到该模型家族最高档（default_effort，上限语义保留）。

自动选型（纯规则，不烧钱）：

1. 管理员手动指定（``/bot model set <id>``）→ 只用该模型，
   失败时按优先级转移到其他模型。
2. ``BOT_MODEL_PRIORITY_GROUPS`` 时段分组命中 → 按组内 order 顺序。
3. 未命中分组 → 按 priority 顺序（越小越先）。
4. 候选失败 → 按顺序转移下一个。

密钥建议用 ``env:变量名`` 引用环境变量，避免写进配置。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
    should_failover,
)

logger = logging.getLogger(__name__)

# 管线检视 #2：渠道 4xx 的拒绝措辞不可枚举（中文措辞、字段名漂移、上下文
# 超限），请求携带 reasoning_effort 时先在同一渠道去参重试一次再进入故障
# 转移——避免中转站措辞一变就把首选渠道打成单点。
_PARAM_STRIP_RETRY_KINDS = frozenset(
    {"unsupported_parameter", "bad_request", "invalid_request"}
)

# v21r5 链级 fail-fast（治「全网故障烧满 BOT_CHAT_FAILOVER_MAX_SECONDS=300s
# 预算才给降级回复」——09-19 实警 15:02 chain=15 跳全败 kind=network，每跳
# ~20s 读超时串行，用户感知回复超时）：同一次 generate() 调用链内连续
# ≥ _FAILFAST_CONSECUTIVE_NETWORK 跳网络类失败（connect/timeout 类，见下）
# → 判定大概率全网性故障，立即中止剩余候选链，走既有失败面（私聊五池
# 守岸人话术 / 群聊 A-19 降级池），路由侧 raise last_error 即可让能力层
# 产出用户可见回复。计数语义：
#   - 只计 ``network``（connect 类归此，providers.py:561/611/618/620）与
#     ``timeout``；4xx/auth/server/rate_limited 均为「服务端可达」证据，
#     出现即打断连续计数；``provider_error``（未分类异常包装）按保守原则
#     打断计数（宁可少触发，不误杀单渠道抖动）。
#   - ``config_missing`` 中性（既不计数也不打断——它根本没碰网络）。
#   - 成功即返回，计数随请求结束销毁（无跨请求状态）。
# 不引入 config 键：固定常量，改行为需改代码（用户裁定 300s 预算不动）。
_FAILFAST_CONSECUTIVE_NETWORK = 5
_NETWORK_FAILFAST_KINDS = frozenset({"network", "timeout"})

# v21r5 config_missing 重复冷却：同渠道 config_missing 进程生命周期内累计
# ≥ _CONFIG_MISSING_COOLDOWN_THRESHOLD 次 → 按既有 cooldown 机制降速，冷却
# 时长 = _CONFIG_MISSING_COOLDOWN_MULTIPLIER × bot_chat_channel_cooldown_seconds
# （缺省 10×90s=900s）。前两次不冷却（保留「配置问题≠渠道不可用」语义——
# 动态注册表改 key 后一跳即愈）；第 3 次起每次出现都顺延冷却（滚动窗口，
# 渠道修复（成功调用）后不再有 config_missing 事件，冷却自然过期恢复）。
# 计数器本体在 ChannelHealthStore.record_config_missing（内存态、进程生命
# 周期），此处只定阈值与倍率。
_CONFIG_MISSING_COOLDOWN_THRESHOLD = 3
_CONFIG_MISSING_COOLDOWN_MULTIPLIER = 10


# 复杂任务信号：命中即路由到 strong 档。
_COMPLEX_KEYWORDS = (
    "教程",
    "一步步",
    "逐步",
    "详细",
    "排查",
    "分析",
    "解释一下",
    "帮我写",
    "写一篇",
    "翻译",
    "总结",
    "比较",
    "推导",
    "证明",
    "代码",
    "配置",
    "部署",
)
_COMPLEX_MIN_CHARS = 300


# 上下文钳制全局缺省（2026-09-17 用户裁定：输入 128K / 输出 64K，日常对话足够）。
DEFAULT_MAX_INPUT_TOKENS = 131072
DEFAULT_MAX_OUTPUT_TOKENS = 65536


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """粗估 prompt token 数：CJK ≈1 token/字、其余 ≈4 chars/token，每条 +8 开销。

    只做文本估算（图片由 vision 路径单独计），用于 128K 输入钳制的保守护栏。
    """
    total = 0
    for item in messages:
        content = str(item.get("content") or "")
        if not content:
            total += 8
            continue
        cjk = sum(1 for ch in content if ord(ch) > 0x2E80)
        total += cjk + (len(content) - cjk) // 4 + 8
    return total


def _enforce_context_caps(
    messages: list[dict[str, str]],
    options: dict[str, object],
    max_input_tokens: int,
    max_output_tokens: int,
) -> list[dict[str, str]]:
    """请求级上下文钳制：输出 max_tokens 只封顶不托底；输入超限从最旧非 system 丢起。

    未设 max_tokens 保持「模型自行决定」既有契约（providers 语义）；仅当调用方
    显式设置且超过上限时压到上限。返回（可能裁剪后的）messages；options 原地修改。
    """
    current = options.get("max_tokens")
    if (
        isinstance(current, (int, float))
        and int(current) > 0
        and int(current) > max_output_tokens
    ):
        options["max_tokens"] = max_output_tokens
    if max_input_tokens > 0 and _estimate_messages_tokens(messages) > max_input_tokens:
        trimmed = list(messages)
        while len(trimmed) > 1 and _estimate_messages_tokens(trimmed) > max_input_tokens:
            for idx, item in enumerate(trimmed):
                if item.get("role") != "system":
                    del trimmed[idx]
                    break
            else:
                break
        return trimmed
    return messages


def _intimate_mode_for_session(router: ModelRouter, session_id: str, text: str) -> bool:
    """会话是否处于 INTIMATE（内容路由）态；fail-open False。

    供 effort 升档抑制用（2026-09-17 成本裁定）：亲密 RP 长文本极易误触发
    复杂判据（≥300 字/关键词）把 grok 顶到家族最高档白烧推理 token，
    INTIMATE 会话一律维持基线/全局档。
    """
    try:
        cb = getattr(router, "_content_route_cb", None)
        if cb is None or not str(session_id or "").strip():
            return False
        verdict = cb(str(session_id), text)
        return isinstance(verdict, dict) and verdict.get("mode") == "intimate"
    except Exception:  # noqa: BLE001 - fail-open：判不了按非亲密处理。
        return False

# ==================== 思考强度档位 ====================
# 按模型名家族划分的思考强度档位；注册表 tags 直接使用这些档位字符串。
# baseline_effort = 家族基线档（元组第一个元素，普通任务默认）；
# default_effort = 家族最高档（元组最后一个元素，复杂任务升档上限）。
FAMILY_EFFORT_TIERS: dict[str, tuple[str, ...]] = {
    "deepseek": ("low", "high", "max"),
    "glm": ("low", "high", "max"),
    "kimi": ("low", "high", "max"),
    "minimax": ("low", "high", "max"),
    "gpt": ("low", "medium", "high", "xhigh"),
    "grok": ("low", "medium", "high", "xhigh"),
    "gemini": ("low", "medium", "high"),
}
# 顺序决定 family 匹配优先级（"c-gemini"、"deepseek" 等长名先判）。
_FAMILY_MATCH_ORDER = ("deepseek", "gemini", "minimax", "grok", "glm", "kimi", "gpt")
# 条目/全局 effort 字段的全部合法值（off = 不发送 reasoning_effort）。
ALL_EFFORT_VALUES: tuple[str, ...] = ("off", "low", "medium", "high", "xhigh", "max")

# 运行时注册表里 .env 来源条目的镜像标记（与 capabilities.runtime_admin
# 的 _ENV_DERIVED_SOURCE 同值；llm 层不反向依赖 capabilities 层，故本地
# 重复常量字面量，改值时两处需同步）。
_ENV_DERIVED_SOURCE = "env"

# 自适应超时（v2 无损切换）：已知渠道 EWMA 时单次尝试超时收紧为
# min(原值, max(下限秒, ema_ms*倍率/1000))，挂死渠道快速失败转移。
_ADAPTIVE_TIMEOUT_FLOOR_S = 8.0
_ADAPTIVE_TIMEOUT_EMA_MULTIPLE = 3.0
# 链预算止损缺省（秒，v21r2 R1）：故障转移链上除首个真实尝试外，剩余预算
# 低于该值时不再发起新跳（残秒尝试注定超时，只会白烧一跳污染告警轨迹）。
# config bot_chat_failover_min_hop_seconds / env BOT_CHAT_FAILOVER_MIN_HOP_SECONDS 可覆盖。
_DEFAULT_FAILOVER_MIN_HOP_SECONDS = 3.0


def model_family(model_name: str) -> str:
    """从模型名识别家族（deepseek/glm/kimi/gpt/grok/gemini/minimax）。"""
    lowered = (model_name or "").lower()
    for family in _FAMILY_MATCH_ORDER:
        if family in lowered:
            return family
    return ""


def default_effort(model_name: str) -> str:
    """模型家族的最高思考强度（上限语义，复杂任务升档目标）；未知家族返回空。"""
    tiers = FAMILY_EFFORT_TIERS.get(model_family(model_name))
    return tiers[-1] if tiers else ""


def baseline_effort(model_name: str) -> str:
    """模型家族的基线思考强度 = 家族最低档（普通任务默认）；未知家族返回空。"""
    tiers = FAMILY_EFFORT_TIERS.get(model_family(model_name))
    return tiers[0] if tiers else ""


def normalize_effort(value: object) -> str:
    """规范化 effort 取值；非法值返回空串（等于未设置）。"""
    text = str(value or "").strip().lower()
    return text if text in ALL_EFFORT_VALUES else ""


# ==================== 时段优先级分组 ====================
def _parse_hhmm(value: str) -> dt_time | None:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt_time(hour=hour, minute=minute)


def parse_priority_groups(raw: object) -> list[dict[str, Any]]:
    """解析 BOT_MODEL_PRIORITY_GROUPS（JSON 数组字符串或 list[dict]）。

    每组形如 ``{"name": "工作日高峰", "days": [1,2,3,4,5],
    "windows": [["09:00","12:00"],["14:00","18:00"]], "order": [渠道id或模型名/别名...]}``。
    days 用 ISO 周编号（1=周一…7=周日），缺省 = 每天；windows 缺省 = 全天；
    days/windows 都缺省即为兜底组。命中判定按列表顺序取第一个满足的组。
    order 条目按模型名/别名匹配时展开为该模型全部渠道（v21r2 R1，R7 移交①：
    生产 .env 写真模型名，旧实现只认渠道 id 恒 no-op）；展开序沿注册表
    (priority, model_id)——分组重排模型先后，渠道序仍归注册表优先级。
    """
    if isinstance(raw, str):
        if not raw.strip():
            return []
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    groups: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        order = [
            str(model_id).strip()
            for model_id in (item.get("order") or [])
            if str(model_id).strip()
        ]
        if not order:
            continue
        days: set[int] = set()
        days_raw = item.get("days")
        if isinstance(days_raw, (list, tuple)):
            for day in days_raw:
                try:
                    day_number = int(day)
                except (TypeError, ValueError):
                    continue
                if 1 <= day_number <= 7:
                    days.add(day_number)
        windows: list[tuple[dt_time, dt_time]] = []
        windows_raw = item.get("windows")
        if isinstance(windows_raw, (list, tuple)):
            for window in windows_raw:
                if not isinstance(window, (list, tuple)) or len(window) != 2:
                    continue
                start = _parse_hhmm(str(window[0]))
                end = _parse_hhmm(str(window[1]))
                if start is not None and end is not None:
                    windows.append((start, end))
        groups.append(
            {
                "name": str(item.get("name", "")).strip(),
                "days": days,
                "windows": windows,
                "order": order,
            }
        )
    return groups


def resolve_active_priority_group(
    groups: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any] | None:
    """返回 now 时刻命中的第一个分组；没有任何分组命中返回 None。"""
    weekday = now.isoweekday()  # 1=周一 … 7=周日
    now_time = now.time()
    for group in groups:
        days: set[int] = group["days"]
        if days and weekday not in days:
            continue
        windows: list[tuple[dt_time, dt_time]] = group["windows"]
        if windows:
            in_window = False
            for start, end in windows:
                if start <= end:
                    in_window = start <= now_time < end
                else:  # 跨零点窗口
                    in_window = now_time >= start or now_time < end
                if in_window:
                    break
            if not in_window:
                continue
        return group
    return None

DEFAULT_REGISTRY: dict[str, dict[str, Any]] = {
    "flash": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "tags": ["fast"],
        "priority": 1,
    },
    "pro": {
        "model": "deepseek-v4-pro",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "tags": ["strong"],
        "priority": 2,
    },
    "terra": {
        "model": "gpt-5.6-terra",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "tags": ["strong"],
        "priority": 3,
    },
    "sol": {
        "model": "gpt-5.6-sol",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "tags": ["strong"],
        "priority": 4,
    },
    "gemini-flash": {
        "model": "gemini-3.7-flash",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "tags": ["fast"],
        "priority": 5,
    },
}

_AUTO = "auto"

# 模型级兜底价（元/1M tokens；2026-09-18 账单未计价根修）。
# 背景：链收敛后渠道选择全权归 axonhub，bot 侧 spec 常缺价——部分渠道条目
# 残留 axonhub /v1/models 的 0.0 价（记 ¥0 假账）或无价（记未计价）。这里按
# **模型名**给兜底价（口径=恒星纪元实付价，出自 scripts/import_model_prices.py
# 2026-09-17 用户实付表）；spec 价缺失或 ≤0 时回退本表，config
# ``bot_llm_model_price_overrides``（模型名→价字段 dict）可逐模型覆盖。
_MODEL_PRICE_FALLBACKS: dict[str, dict[str, float | None]] = {
    "gemini-3.8-flash": {
        "price_in": 0.1875,
        "price_out": 0.9375,
        "price_cache_read": 0.01041625,
        "price_cache_creation": None,
    },
    "gemini-3.8-flash-high": {
        "price_in": 0.45,
        "price_out": 2.25,
        "price_cache_read": None,
        "price_cache_creation": None,
    },
    "gpt-5.6-terra": {
        "price_in": 0.29,
        "price_out": 1.74,
        "price_cache_read": 0.029,
        "price_cache_creation": 0.3625,
    },
    "gpt-5.6-luna": {
        "price_in": 0.116,
        "price_out": 0.522,
        "price_cache_read": 0.0087,
        "price_cache_creation": 0.10875,
    },
    "grok-4.6": {
        "price_in": 0.6,
        "price_out": 1.8,
        "price_cache_read": 0.15,
        "price_cache_creation": None,
    },
    "deepseek-v4.1-flash": {
        "price_in": 1.0,
        "price_out": 4.0,
        "price_cache_read": 0.02,
        "price_cache_creation": None,
    },
}


def _apply_model_price_fallback(spec: ModelSpec, config: object | None = None) -> ModelSpec:
    """spec 价缺失或 ≤0（axonhub 全 0 遗留）→ 按模型名回退兜底价。

    dataclass frozen：返回补价后的新 spec；已有效计价的 spec 原样返回。
    """
    prices = _MODEL_PRICE_FALLBACKS.get((spec.model or "").strip().lower())
    if prices is None:
        return spec
    overrides = {}
    if config is not None:
        raw = getattr(config, "bot_llm_model_price_overrides", None) or {}
        if isinstance(raw, dict):
            entry = raw.get(spec.model) or raw.get(spec.model.lower())
            if isinstance(entry, dict):
                overrides = entry
    needs = any(
        getattr(spec, field) is None or (isinstance(getattr(spec, field), (int, float)) and getattr(spec, field) <= 0)
        for field in ("price_in", "price_out")
        if prices.get(field) is not None or overrides.get(field) is not None
    )
    if not needs:
        return spec
    updates: dict[str, float | None] = {}
    for price_field in ("price_in", "price_out", "price_cache_read", "price_cache_creation", "price_per_call"):
        current = getattr(spec, price_field, None)
        if current is None or (isinstance(current, (int, float)) and current <= 0):
            override = overrides.get(price_field)
            fallback = prices.get(price_field)  # 提局部变量让 mypy 窄化：守卫后必非 None（字面量常量字典，无中途改写）
            if override is not None:
                updates[price_field] = float(override)
            elif fallback is not None:
                updates[price_field] = float(fallback)
    if not updates:
        return spec
    return spec.__class__(**{**spec.__dict__, **updates})


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model: str
    base_url: str
    api_key: str
    api_keys: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    priority: int = 100
    routing_group: str = ""
    effort: str = ""  # 思考强度覆盖；空 = 家族基线（最低档），off = 不发送
    # 渠道价格（每 1M tokens，币种随渠道报价）；按模型名聚合选渠道时用
    # (price_in+price_out) 均值升序，缺价渠道排在有价渠道之后。
    # cache_read/cache_creation 价缺省回退 price_in（账本计价侧处理）。
    price_in: float | None = None
    price_out: float | None = None
    price_cache_read: float | None = None
    price_cache_creation: float | None = None
    # 按次计费渠道（元/请求，如 0.18/次）：与 token 价并存时叠加进账单总额。
    price_per_call: float | None = None

    def all_api_keys(self) -> tuple[str, ...]:
        """全部可用密钥（按顺序故障转移）；未配置 api_keys 时退回单密钥。"""
        if self.api_keys:
            return self.api_keys
        return (self.api_key,) if self.api_key else ()


def _resolve_api_key(value: str, config: object | None = None) -> str:
    from os import environ

    if value.startswith("env:"):
        env_name = value.removeprefix("env:").strip()
        # NoneBot 的 dotenv 配置会进入 driver.config，但不一定写入 os.environ。
        # 先保留进程环境的旧优先级，再从 Config 字段回退，保证真实运行态与 smoke 一致。
        return environ.get(env_name) or str(
            getattr(config, env_name.lower(), "") or ""
        )
    return value


def _resolve_api_keys(
    value: object,
    config: object | None = None,
) -> tuple[str, ...]:
    """解析单密钥或密钥列表（均可写 env:变量名或明文），去掉空值。"""
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        items = [str(value)]
    return tuple(
        key
        for key in (_resolve_api_key(item, config).strip() for item in items)
        if key
    )


def _spec_from_entry(
    model_id: str,
    item: dict[str, Any],
    config: object | None = None,
) -> ModelSpec | None:
    """把单个注册表条目解析成 ModelSpec；缺 model 字段时忽略该条目。"""
    model = str(item.get("model", "")).strip()
    if not model:
        return None
    tags = item.get("tags")
    if isinstance(tags, list):
        tag_tuple = tuple(str(tag) for tag in tags)
    elif isinstance(tags, str):
        tag_tuple = tuple(tag.strip() for tag in tags.split(",") if tag.strip())
    else:
        tag_tuple = ("fast",)
    aliases = item.get("aliases", item.get("alias", ()))
    if isinstance(aliases, str):
        alias_tuple = tuple(item.strip() for item in aliases.split(",") if item.strip())
    elif isinstance(aliases, (list, tuple)):
        alias_tuple = tuple(str(item).strip() for item in aliases if str(item).strip())
    else:
        alias_tuple = ()
    priority = item.get("priority", 100)
    if not isinstance(priority, int):
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 100
    resolved_keys = _resolve_api_keys(item.get("api_key", ""), config)
    return ModelSpec(
        model_id=str(model_id),
        model=model,
        base_url=str(item.get("base_url", "")).strip(),
        api_key=resolved_keys[0] if resolved_keys else "",
        api_keys=resolved_keys,
        tags=tag_tuple,
        aliases=alias_tuple,
        priority=priority,
        routing_group=str(item.get("group", "") or "").strip(),
        effort=normalize_effort(item.get("effort", "")),
        price_in=_optional_price(item.get("price_in")),
        price_out=_optional_price(item.get("price_out")),
        price_cache_read=_optional_price(item.get("price_cache_read")),
        price_cache_creation=_optional_price(item.get("price_cache_creation")),
        price_per_call=_optional_price(item.get("price_per_call")),
    )


def _health_filter_candidates(model_ids: list[str], config: object | None = None) -> list[str]:
    """从候选队列剔除「暂时不可用」渠道；全部不可用时放行原列表。

    开关与巡检侧同源：channel_health.channel_health_enabled(config)
    （Config 字段 → os.environ → 默认），不再只读 os.environ——生产
    .env-only 部署下 NoneBot 只把配置写进 Config，旧实现会让健康门整体
    空转而巡检照常运行。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            filter_healthy_candidates,
            get_channel_health_store,
        )

        if not channel_health_enabled(config):
            return model_ids
        return filter_healthy_candidates(model_ids, get_channel_health_store())
    except Exception:  # noqa: BLE001 - 健康层故障不阻塞路由。
        return model_ids


def _health_record_success(model_id: str, latency_ms: int, config: object | None = None) -> None:
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            get_channel_health_store,
        )

        if not channel_health_enabled(config):
            return
        get_channel_health_store().record_success(model_id, latency_ms)
    except Exception:  # noqa: BLE001 - 健康记录失败静默，不影响主链路。
        return


def _health_record_failure(model_id: str, error_kind: str, config: object | None = None) -> None:
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            get_channel_health_store,
            resolve_channel_cooldown_seconds,
        )

        if not channel_health_enabled(config):
            return
        # auth/config 类失败不计渠道健康（是配置问题，不是渠道不可用）。
        # v21r5 例外：config_missing 的「重复冷却」改由 _health_record_config_missing
        # 计数决策（前两次放行，累计 ≥3 次按加长冷却降速），本函数保持跳过。
        if error_kind in {"auth", "config_missing"}:
            return
        # v21r2 R1：失败同时写近期冷却（缺省 90s），路由侧把该渠道降级到队尾。
        get_channel_health_store().record_failure(
            model_id,
            f"kind={error_kind}",
            cooldown_seconds=resolve_channel_cooldown_seconds(config),
        )
    except Exception:  # noqa: BLE001 - 健康记录失败静默，不影响主链路。
        return


def _health_record_config_missing(model_id: str, config: object | None = None) -> None:
    """config_missing 重复冷却（v21r5）：进程生命周期累计 ≥3 次按加长冷却降速。

    设计动机（09-19 实警 14:06 chain=2 last=potccv-gpt-56-terra:config_missing）：
    缺配置的渠道原本零冷却、每个候选链都当首发白跳一次（虽然无网络成本，
    但会把链止损预算/诊断注意力耗在注定失败的渠道上）。语义：
    - 前 2 次不冷却（保留既有「配置问题≠渠道不可用」——动态改 key 后一跳即愈）；
    - 进程生命周期累计 ≥ _CONFIG_MISSING_COOLDOWN_THRESHOLD（3）次 → 调既有
      record_failure 写 cooldown_until = _CONFIG_MISSING_COOLDOWN_MULTIPLIER（10）×
      bot_chat_channel_cooldown_seconds（缺省 90s → 900s），路由侧把该渠道
      降级到队尾（不剔除，冷却过期后仍会给修复机会）；
    - 计数进程生命周期累计不清零（ChannelHealthStore 内存态，重启清零）；
    - 健康层关闭（channel_health_enabled=False）时整体空转，与既有健康面同开关。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            get_channel_health_store,
            resolve_channel_cooldown_seconds,
        )

        if not channel_health_enabled(config):
            return
        store = get_channel_health_store()
        count = store.record_config_missing(model_id)
        if count < _CONFIG_MISSING_COOLDOWN_THRESHOLD:
            return
        cooldown_seconds = (
            resolve_channel_cooldown_seconds(config) * _CONFIG_MISSING_COOLDOWN_MULTIPLIER
        )
        store.record_failure(
            model_id,
            f"kind=config_missing_repeated count={count}",
            cooldown_seconds=cooldown_seconds,
        )
        logger.warning(
            "llm channel config_missing repeated cooldown model=%s count=%d "
            "cooldown_seconds=%.0f",
            model_id,
            count,
            cooldown_seconds,
        )
    except Exception:  # noqa: BLE001 - 健康记录失败静默，不影响主链路。
        return


def _strict_priority_enabled(config: object | None = None) -> bool:
    """严格注册表优先级开关（v21r2 R1）：Config 字段 → os.environ → 默认开。

    2026-09-17 用户裁定「永远按注册表优先级处理」：同名模型渠道聚合排序以
    注册表 priority 为主键，价格/EWMA 只作同级 tiebreak，低优先级渠道永远
    不得反超（治「浅夜の梦抢恒星纪元-Gemini」）。false = 旧行为（价格均值
    优先；latency_first 开时 EWMA 整体重排）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            _flag_value,
        )

        for raw in (
            getattr(config, "bot_chat_strict_priority", None),
            os.environ.get("BOT_CHAT_STRICT_PRIORITY"),
        ):
            value = _flag_value(raw)
            if value is not None:
                return value
    except Exception:  # noqa: BLE001 - 开关读取失败按默认（开）处理。
        return True
    return True


def _failover_min_hop_seconds(config: object | None = None) -> float:
    """链预算止损最小跳预算（秒）：Config 字段 → os.environ → 缺省 3.0；负值按 0。

    故障转移链上除首个真实尝试外，剩余预算低于该值时不再发起新跳；0=关闭。
    """
    for raw in (
        getattr(config, "bot_chat_failover_min_hop_seconds", None),
        os.environ.get("BOT_CHAT_FAILOVER_MIN_HOP_SECONDS"),
    ):
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        return max(0.0, value)
    return _DEFAULT_FAILOVER_MIN_HOP_SECONDS


def _demote_cooling_candidates(
    model_ids: list[str], config: object | None = None
) -> tuple[list[str], list[str]]:
    """近期失败冷却降级（v21r2 R1）：冷却中的渠道稳定移到候选队尾（不剔除）。

    返回 (降级后队列, 被降级的渠道 id 列表)；健康层关闭/故障时原样放行。
    与 _health_filter_candidates 同一开关源（channel_health_enabled）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            demote_cooling_candidates,
            get_channel_health_store,
        )

        if not channel_health_enabled(config) or len(model_ids) < 2:
            return model_ids, []
        ordered, demoted = demote_cooling_candidates(model_ids, get_channel_health_store())
        return ordered, demoted
    except Exception:  # noqa: BLE001 - 冷却层故障不阻塞路由。
        return model_ids, []


def _health_ema_latencies(
    config: object | None = None, *, require_latency_first: bool = True
) -> dict[str, int] | None:
    """EWMA 平滑延迟表（v2 动态切换）；健康层关闭/故障时返回 None（回落价格序）。

    双开关与巡检侧同源解析（channel_health_latency_first /
    channel_health_enabled）：Config 字段 → os.environ → 默认（延迟择优
    v21r2 R1 起默认关=严格注册表优先级，健康层默认关）。
    ``require_latency_first=False`` 供自适应超时等**非排序**消费方：EMA 数据
    读取不应被排序开关连带关闭（latency_first 只管「排序」，不管「快失败」；
    否则用户关延迟择优会把挂死渠道快速止损一并关掉——回归护栏
    test_channel_health_v2.py::test_adaptive_timeout_tightens_by_ema）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            channel_health_enabled,
            channel_health_latency_first,
            get_channel_health_store,
        )

        if require_latency_first and not channel_health_latency_first(config):
            return None
        if not channel_health_enabled(config):
            return None
        return get_channel_health_store().ema_latencies()
    except Exception:  # noqa: BLE001 - 健康层故障不阻塞路由。
        return None


def _optional_price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


@dataclass
class _HedgeOutcome:
    """影子并发阶段的结果：赢家的回复、待抛错误与 last_attempts 记号。"""

    reply: Any = None
    error: LLMProviderError | None = None
    attempt_marks: list[str] = field(default_factory=list)


class _HedgeRace:
    """影子并发（hedged request）竞速共享状态。

    Condition 保护 winner/完成计数/失败表；worker 线程只写状态并 notify。
    ``last_attempts`` 记号由主线程在竞速结束后统一追加——worker 绝不触碰
    它，避免主请求已返回后仍与调用方产生数据竞争。
    """

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.winner_id = ""
        self.winner_reply: Any = None
        # 成功但落选（另一路先回）的候选：其健康记账已在 worker 内完成。
        self.losers: list[str] = []
        self.failures: dict[str, LLMProviderError] = {}
        # 非故障转移类错误（invalid_request/unsupported_parameter 等）：
        # 影子全败时优先抛出，贴近串行路径的立即中断语义。
        self.terminal_error: LLMProviderError | None = None
        self.finished = 0


def _price_rank(spec: ModelSpec) -> float:
    """渠道性价比排序键：输入/输出均价；缺价排最后。"""
    if spec.price_in is None and spec.price_out is None:
        return float("inf")
    parts = [v for v in (spec.price_in, spec.price_out) if v is not None]
    return sum(parts) / len(parts)


def _priority_value(entry: dict[str, Any]) -> int:
    try:
        value = int(entry.get("priority", 10**9))
    except (TypeError, ValueError):
        return 10**9
    return value if value > 0 else 10**9


def normalize_priority_entries(
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Normalize registry priorities to unique dense slots without changing ids."""
    ordered = sorted(
        entries.items(),
        key=lambda item: (_priority_value(item[1]), item[0]),
    )
    return {
        model_id: {**entry, "priority": index}
        for index, (model_id, entry) in enumerate(ordered, start=1)
    }


def reorder_priority_entries(
    entries: dict[str, dict[str, Any]],
    model_id: str,
    priority: int,
) -> dict[str, dict[str, Any]]:
    """Move one registry entry to a one-based slot and shift all other entries."""
    if model_id not in entries:
        raise ValueError(f"不存在的模型 id：{model_id}")
    normalized = normalize_priority_entries(entries)
    ordered_ids = [
        key
        for key, _entry in sorted(
            normalized.items(), key=lambda item: item[1]["priority"]
        )
    ]
    ordered_ids.remove(model_id)
    slot = max(1, min(int(priority), len(ordered_ids) + 1))
    ordered_ids.insert(slot - 1, model_id)
    return {
        key: {**normalized[key], "priority": index}
        for index, key in enumerate(ordered_ids, start=1)
    }


def build_model_registry(config: object) -> dict[str, ModelSpec]:
    raw = getattr(config, "bot_model_registry", None) or {}
    if not isinstance(raw, dict) or not raw:
        # 未配置注册表时，用主模型配置生成单模型注册表，行为等价旧版。
        return {}
    normalized_raw = normalize_priority_entries(
        {
            str(model_id): dict(item)
            for model_id, item in raw.items()
            if isinstance(item, dict)
        }
    )
    specs: dict[str, ModelSpec] = {}
    for model_id, item in normalized_raw.items():
        spec = _spec_from_entry(str(model_id), item, config)
        if spec is not None:
            specs[str(model_id)] = spec
    return specs


def _main_fallback_spec(config: object) -> ModelSpec | None:
    """主 BOT_CHAT_* 配置的兜底模型（注册表为空时即旧版单模型行为）。"""
    model = str(getattr(config, "bot_chat_model", "")).strip()
    if not model:
        return None
    return _apply_model_price_fallback(
        ModelSpec(
            model_id="default",
            model=model,
            base_url=str(getattr(config, "bot_chat_base_url", "")).strip(),
            api_key=str(getattr(config, "bot_chat_api_key", "")),
            tags=("strong",),
            priority=1,
            routing_group="default",
        ),
        config,
    )


def _preset_specs(config: object, *, priority_offset: int = 1000) -> dict[str, ModelSpec]:
    """把 BOT_MODEL_PRESETS 的预设名转成可路由的模型条目。

    预设只应被手动指定选中，因此打 ``manual`` 标签且优先级垫底，
    不会在自动选型中抢走主模型/注册表模型的位置。
    """
    presets = getattr(config, "bot_model_presets", {}) or {}
    if not isinstance(presets, dict):
        return {}
    main = _main_fallback_spec(config)
    base_url = main.base_url if main is not None else ""
    api_key = main.api_key if main is not None else ""
    specs: dict[str, ModelSpec] = {}
    for index, (name, model) in enumerate(presets.items()):
        model = str(model).strip()
        if not model:
            continue
        specs[str(name)] = ModelSpec(
            model_id=str(name),
            model=model,
            base_url=base_url,
            api_key=api_key,
            tags=("manual",),
            priority=priority_offset + index,
            routing_group="manual",
        )
    return specs


class ModelRouter:
    # 上下文钳制全局缺省（build_model_router 按 config 覆写；2026-09-17 裁定）。
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    # 类级默认（__init__ 会覆写为实例属性）：以 ModelRouter.__new__ 构造的最小
    # 实例（测试手法，见 tests/test_auditfix_llm_route.py::_bare_router）也能安全
    # 读到 None；否则 _spec_for 等处的裸访问会抛 AttributeError（2026-09-18 修复）。
    _credential_config: object | None = None

    def __init__(
        self,
        specs: dict[str, ModelSpec],
        *,
        provider_factory: Callable[[ModelSpec], Any] | None = None,
        fallback_spec: ModelSpec | None = None,
        proxy: str = "",
        timeout_seconds: float = 30.0,
        dynamic_registry: Callable[[], dict[str, dict[str, Any]]] | None = None,
        max_failover_seconds: float = 0.0,
        priority_groups: Callable[[], Any] | None = None,
        timezone_name: str = "Asia/Hong_Kong",
        credential_config: object | None = None,
        call_record_sink: Any = None,
        content_route_cb: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self._credential_config = credential_config
        # R-18 内容感知路由（runtime/content_route.py）：None=未注入，路由
        # 行为与旧版逐字节一致；注入后仅在自动路由分支按 verdict 重排候选，
        # 管理员显式 override 分支不受影响。
        self._content_route_cb = content_route_cb
        self._timezone_name = timezone_name
        # B5 M1 计费账本 sink（CallRecordSink Protocol，见 llm/ledger.py）：
        # None = 未注入，出口按账本开关（默认关）解析，行为回到现状。
        self._call_record_sink = call_record_sink
        self._custom_factory = provider_factory
        self.specs = dict(specs)
        self._base_specs = dict(specs)
        self._dynamic_registry = dynamic_registry
        self._dynamic_snapshot: dict[str, dict[str, Any]] | None = None
        self._priority_groups_cb = priority_groups
        try:
            self._zone: Any = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            self._zone = datetime.now().astimezone().tzinfo
        # 故障转移总时限：候选连续失败时的整体预算，防止超时串成分钟级等待；0=不限。
        self.max_failover_seconds = max(0.0, float(max_failover_seconds))
        # 兜底模板：未知覆盖 id 时当作完整模型名，走主配置的接口/密钥
        # （兼容旧版「直接给模型名」的用法）。
        self._fallback_spec = fallback_spec
        self.proxy = str(proxy or "").strip()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._providers: dict[str, Any] = {}
        self._factory = provider_factory or self._default_provider
        # 仅保存模型 id 与错误类别，不保存 API key 或异常原文。
        self.last_attempts: list[str] = []

    def fork(self) -> ModelRouter:
        """Reuse routing policy and secret references, not mutable per-call state."""
        return ModelRouter(
            self._base_specs, provider_factory=self._custom_factory,
            fallback_spec=self._fallback_spec, proxy=self.proxy,
            timeout_seconds=self.timeout_seconds, dynamic_registry=self._dynamic_registry,
            max_failover_seconds=self.max_failover_seconds,
            priority_groups=self._priority_groups_cb, timezone_name=self._timezone_name,
            credential_config=self._credential_config,
            call_record_sink=self._call_record_sink,
            # v21r2 R1：fork 必须继承内容路由回调（__init__.py:408 摄取侧
            # fork 后照常走 INTIMATE grok 钉第一；旧实现丢失=分叉路由退化默认链）。
            content_route_cb=self._content_route_cb,
        )

    def _refresh_dynamic_registry(self) -> None:
        """合并运行时注册表（聊天指令新增/修改的供应商），改动即生效。

        以 _base_specs（.env 注册表）为底座整体换入动态条目；条目变更或
        删除时同步丢弃对应 provider 缓存。specs 以整体替换方式更新，
        并发读取只会看到完整的新旧字典之一。
        """
        if self._dynamic_registry is None:
            return
        try:
            dynamic = self._dynamic_registry() or {}
        except Exception:  # noqa: BLE001 - 动态注册表读取失败沿用上次快照。
            return
        if not isinstance(dynamic, dict):
            return
        if dynamic == self._dynamic_snapshot:
            return
        new_specs = dict(self._base_specs)
        for model_id, item in dynamic.items():
            if not isinstance(item, dict):
                continue
            spec = self._spec_from_dynamic_entry(str(model_id), item)
            if spec is not None:
                new_specs[str(model_id)] = spec
        for cached_id in list(self._providers):
            base_id = cached_id[0] if isinstance(cached_id, tuple) else cached_id
            if (
                base_id not in new_specs
                or new_specs.get(base_id) != self.specs.get(base_id)
            ):
                self._providers.pop(cached_id, None)
        # Reassign only the ordering field: never drop alternate keys or metadata.
        ordered = sorted((spec for spec in new_specs.values() if "manual" not in spec.tags),
                         key=lambda spec: (spec.priority, spec.model_id))
        for rank, spec in enumerate(ordered, 1):
            new_specs[spec.model_id] = replace(spec, priority=rank)
        self.specs = new_specs
        self._dynamic_snapshot = {
            str(key): dict(value) for key, value in dynamic.items() if isinstance(value, dict)
        }

    def _spec_from_dynamic_entry(self, model_id: str, item: dict[str, Any]) -> ModelSpec | None:
        """运行时条目 → ModelSpec；.env 同名条目的内容字段以 .env 为新鲜值。

        Task4 之后 runtime store 里 .env 来源条目带 ``source: "env"`` 镜像
        标记。若按镜像快照整体重建，.env 后续编辑（换模型/换地址/换 key）
        会被运行时旧副本遮蔽。因此凡 .env 仍存在同名条目的运行时副本，内容
        字段一律取 ``_base_specs``（.env 注册表的最新解析视图）重建，仅
        runtime 侧拥有的 priority 与 ``override_fields`` 里管理员明确改过的
        字段生效。
        旧快照自动迁移（B-14，handoff §13.10）：Task4 之前写入的存量条目
        没有 ``source`` 标记，内容字段是写入当时的 .env 烘焙副本，会永久
        遮蔽 .env 后续修改。读取侧对这类条目按镜像语义处理（内容取 .env
        实时值、priority 保留快照值），无需管理员逐条重新 update。
        .env 已删除的条目：镜像条目不再被旧副本复活；无标记条目按纯运行时
        条目（管理员 add 的自定义模型）原样生效，行为不变。
        """
        base = self._base_specs.get(model_id)
        if base is None:
            if item.get("source") == _ENV_DERIVED_SOURCE:
                return None
            return _spec_from_entry(model_id, item, self._credential_config)
        effective = dict(item)
        effective.update(
            {
                "model": base.model,
                "base_url": base.base_url,
                # 密钥用 .env 解析结果重建（含多密钥列表）；运行时 store 里
                # 本就不落明文 key，这里仅内存视图，绝不写回。
                "api_key": list(base.api_keys) or base.api_key,
                "tags": list(base.tags),
                "aliases": list(base.aliases),
                "group": base.routing_group,
                "effort": base.effort,
                "price_in": base.price_in,
                "price_out": base.price_out,
            }
        )
        if item.get("source") != _ENV_DERIVED_SOURCE:
            effective["source"] = _ENV_DERIVED_SOURCE
        for override_field in item.get("override_fields") or []:
            if override_field == "priority" or override_field not in item:
                continue
            effective[override_field] = item[override_field]
        return _spec_from_entry(model_id, effective, self._credential_config)

    def _default_provider(self, spec: ModelSpec) -> Any:
        return OpenAICompatibleLLMProvider(
            api_key=spec.api_key,
            model=spec.model,
            base_url=spec.base_url,
            proxy=self.proxy,
            timeout_seconds=self.timeout_seconds,
        )

    def _spec_for(self, model_id: str) -> ModelSpec | None:
        spec = self.specs.get(model_id)
        if spec is not None:
            return _apply_model_price_fallback(spec, self._credential_config)
        if self._fallback_spec is None:
            return None
        if model_id == self._fallback_spec.model_id:
            return self._fallback_spec
        return _apply_model_price_fallback(
            ModelSpec(
                model_id=model_id,
                model=model_id,
                base_url=self._fallback_spec.base_url,
                api_key=self._fallback_spec.api_key,
                tags=self._fallback_spec.tags,
                priority=100,
            ),
            self._credential_config,
        )

    def provider_for(self, model_id: str, api_key: str | None = None) -> Any:
        spec = self._spec_for(model_id)
        if spec is None:
            raise KeyError(f"unknown model id: {model_id}")
        # 未知 id 的合成 spec（幻觉模型名兜底）不缓存：否则每个噪声 id 都在
        # _providers 里永久驻一个带 key 的 provider，长驻进程无界增长。
        ephemeral = (
            model_id not in self.specs
            and (
                self._fallback_spec is None
                or model_id != self._fallback_spec.model_id
            )
        )
        cache_key: Any = model_id
        provider_spec = spec
        if api_key is not None and api_key != spec.api_key:
            cache_key = (model_id, api_key)
            provider_spec = replace(spec, api_key=api_key)
        if ephemeral:
            return self._factory(provider_spec)
        if cache_key not in self._providers:
            self._providers[cache_key] = self._factory(provider_spec)
        return self._providers[cache_key]

    def model_ids(self) -> list[str]:
        return list(self.specs.keys())

    def supports_vision(self, *, message_text: str = "", override: str = "") -> bool:
        """Whether the first routed candidate can take images directly.

        当前接入的渠道均为多模态模型（用户确认），默认全部支持直传图片；
        将来接入纯文本渠道时在 tags 里标 ``text-only`` 显式排除。
        """
        self._refresh_dynamic_registry()
        candidate_ids = self.route_ids(message_text=message_text, override=override)
        if not candidate_ids:
            return False
        spec = self._spec_for(candidate_ids[0])
        if spec is None:
            return False
        return "text-only" not in {tag.lower() for tag in spec.tags}

    def channels_for_model(self, model_name: str) -> list[str]:
        """按实际模型名聚合全部渠道（v21r2 R1：严格注册表优先级）。

        ``bot_chat_strict_priority``（缺省开，2026-09-17 用户裁定「永远按
        注册表优先级处理」）：注册表 priority 主键——EWMA 延迟（仅当
        latency_first 显式开）与价格只作**同级 tiebreak**，低优先级渠道永不
        反超（治「浅夜の梦抢恒星纪元-Gemini」）；无 EWMA 时 = priority → 价格。
        关（false）= 旧行为：latency_first 开时已实测渠道按 EWMA 升序在前
        （同 ema 按价格/优先级）、未实测垫底；否则价格均值升序 → priority。
        作用域仅限同名模型聚合；``_auto_route_ids`` 全局候选队列保持人工策展
        的 priority 顺序，不做延迟重排（默认模型永远是 Gemini，用户裁定，
        不得被延迟排序推翻）。
        """
        name = (model_name or "").strip().lower()
        if not name:
            return []
        matched = [
            spec
            for spec in self.specs.values()
            if spec.model.lower() == name
            or any(alias.lower() == name for alias in spec.aliases)
        ]
        credential_config = getattr(self, "_credential_config", None)
        ema_map = _health_ema_latencies(credential_config)
        if not _strict_priority_enabled(credential_config):
            # 旧行为（bot_chat_strict_priority=false）：价格序 / EWMA 延迟序。
            if ema_map is None:
                matched.sort(key=lambda spec: (_price_rank(spec), spec.priority))
                return [spec.model_id for spec in matched]
            measured = {
                spec.model_id: ema_map[spec.model_id]
                for spec in matched
                if spec.model_id in ema_map
            }
            if not measured:
                matched.sort(key=lambda spec: (_price_rank(spec), spec.priority))
                return [spec.model_id for spec in matched]
            matched.sort(
                key=lambda spec: (
                    (0, measured[spec.model_id], _price_rank(spec), spec.priority)
                    if spec.model_id in measured
                    else (1, 0, _price_rank(spec), spec.priority)
                )
            )
            return [spec.model_id for spec in matched]
        # 严格注册表优先级（缺省）：priority 主键；EWMA（latency_first 显式
        # 开时）与价格降为同级 tiebreak。
        if ema_map is None:
            matched.sort(key=lambda spec: (spec.priority, _price_rank(spec)))
            return [spec.model_id for spec in matched]
        measured = {
            spec.model_id: ema_map[spec.model_id]
            for spec in matched
            if spec.model_id in ema_map
        }
        if not measured:
            matched.sort(key=lambda spec: (spec.priority, _price_rank(spec)))
            return [spec.model_id for spec in matched]
        matched.sort(
            key=lambda spec: (
                spec.priority,
                0 if spec.model_id in measured else 1,
                measured.get(spec.model_id, 0),
                _price_rank(spec),
            )
        )
        return [spec.model_id for spec in matched]

    # ==================== v2：自适应超时与影子并发 ====================

    @staticmethod
    def _resolve_effort(spec: ModelSpec, global_effort: str, complex_task: bool) -> str:
        """思考强度：条目显式设置（含 off）> 全局 > 家族基线（最低档）。

        复杂任务把来自全局/家族基线的档位升到家族最高档（串行/影子两路共用）。
        """
        if spec.effort:
            return spec.effort
        if global_effort:
            family_default = default_effort(spec.model)
            return family_default if complex_task and family_default else global_effort
        baseline = baseline_effort(spec.model)
        return default_effort(spec.model) if complex_task else baseline

    @staticmethod
    def _tighten_timeout(
        model_id: str, base_timeout: float, ema_map: dict[str, int] | None
    ) -> float:
        """自适应超时：已知渠道 EWMA 时收紧为 min(原值, max(8s, ema*3))。

        ema 未知（未实测/健康层关闭）→ 原值不动；挂死渠道快速失败转移。
        """
        if ema_map is None:
            return base_timeout
        ema_ms = ema_map.get(model_id)
        if not ema_ms or ema_ms <= 0:
            return base_timeout
        return min(
            base_timeout,
            max(
                _ADAPTIVE_TIMEOUT_FLOOR_S,
                ema_ms * _ADAPTIVE_TIMEOUT_EMA_MULTIPLE / 1000.0,
            ),
        )

    def _adaptive_timeout_enabled(self) -> bool:
        """开关：config bot_channel_adaptive_timeout（缺省 True；无 ema 时天然空转）。"""
        return bool(
            getattr(
                getattr(self, "_credential_config", None),
                "bot_channel_adaptive_timeout",
                True,
            )
        )

    def _hedge_settings(self) -> tuple[int, float]:
        """影子并发参数：(最多并发候选数(>=2), 首选未回时发起次候选的延迟秒)。

        路由器未接 config（测试桩）时返回 (2, 6.0)——调用方仍须以
        ``bot_chat_hedged_requests_enabled`` 显式开启才会走影子路径。
        """
        cfg = getattr(self, "_credential_config", None)
        try:
            max_candidates = int(getattr(cfg, "bot_chat_hedge_max_candidates", 2))
        except (TypeError, ValueError):
            max_candidates = 2
        try:
            delay = float(getattr(cfg, "bot_chat_hedge_delay_seconds", 6.0))
        except (TypeError, ValueError):
            delay = 6.0
        return max(2, max_candidates), max(0.0, delay)

    def _generate_hedged(
        self,
        messages: list[dict[str, str]],
        candidate_ids: list[str],
        *,
        global_effort: str,
        complex_task: bool,
        base_options: dict[str, object],
        failover_deadline: float | None,
        hedge_delay: float,
        adaptive_ema_map: dict[str, int] | None,
    ) -> _HedgeOutcome:
        """影子并发竞速：先到先得，失败者照常记账，全败落回正常转移。

        候选① 立即在 worker 线程发起；``hedge_delay`` 秒仍未完成则发起
        候选②；① 提前失败则不等 delay 立即转移次候选（快速失败语义与
        串行路径一致）。任一成功即认领 winner 返回；落选 worker daemon 化
        不阻塞返回，其健康记账在 worker 内完成（成功→ema 更新，失败→计
        fail），数据不浪费。返回的 reply/error 尚未携带 attempts，由调用方
        统一发布（D6：attempts 归调用私有）。
        """
        race = _HedgeRace()
        launched = 0
        launched_ids: list[str] = []

        def _launch(model_id: str) -> None:
            nonlocal launched
            launched += 1
            launched_ids.append(model_id)
            threading.Thread(
                target=self._hedge_attempt,
                kwargs={
                    "race": race,
                    "model_id": model_id,
                    "messages": messages,
                    "global_effort": global_effort,
                    "complex_task": complex_task,
                    "base_options": base_options,
                    "ema_map": adaptive_ema_map,
                    "failover_deadline": failover_deadline,
                },
                name=f"hedged-request:{model_id}",
                daemon=True,
            ).start()

        _launch(candidate_ids[0])
        next_index = 1
        # 次候选最迟发起时刻；① 提前失败时下一轮循环立即发起。
        next_fire = time.monotonic() + hedge_delay
        while True:
            with race.cond:
                if race.winner_reply is not None:
                    break
                if race.finished >= launched:
                    if next_index < len(candidate_ids):
                        _launch(candidate_ids[next_index])
                        next_index += 1
                        next_fire = time.monotonic() + hedge_delay
                        continue
                    break  # 影子候选全部失败 → 落回正常故障转移循环
                now = time.monotonic()
                budget_left = (
                    failover_deadline - now if failover_deadline is not None else None
                )
                if budget_left is not None and budget_left <= 0:
                    break  # 预算耗尽：正常循环接管（追加 failover:deadline 记号）
                waits = []
                if next_index < len(candidate_ids):
                    waits.append(next_fire - now)
                if budget_left is not None:
                    waits.append(budget_left)
                wait_for = min(waits) if waits else None
                if wait_for is not None and wait_for <= 0:
                    _launch(candidate_ids[next_index])
                    next_index += 1
                    next_fire = time.monotonic() + hedge_delay
                    continue
                race.cond.wait(wait_for)  # None = 等 worker 通知

        marks: list[str] = []
        with race.cond:
            if race.winner_reply is not None:
                marks.append(f"hedged:{race.winner_id}:winner")
                # 全部已发起的非赢家（含仍在飞的落选线程，其健康记账由
                # daemon 线程事后落地）都记 loser，主线程此刻统一发布。
                marks.extend(
                    f"hedged:{model_id}:loser"
                    for model_id in launched_ids
                    if model_id != race.winner_id
                )
                return _HedgeOutcome(reply=race.winner_reply, attempt_marks=marks)
            # 影子全败/预算耗尽：终结性错误优先抛，否则按候选顺序取首个失败。
            error = race.terminal_error
            if error is None:
                for model_id in candidate_ids:
                    if model_id in race.failures:
                        error = race.failures[model_id]
                        break
            marks.extend(f"hedged:{model_id}:loser" for model_id in launched_ids)
        return _HedgeOutcome(error=error, attempt_marks=marks)

    def _hedge_attempt(
        self,
        race: _HedgeRace,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        global_effort: str,
        complex_task: bool,
        base_options: dict[str, object],
        ema_map: dict[str, int] | None,
        failover_deadline: float | None,
    ) -> None:
        """影子候选 worker：与串行路径同语义的单候选尝试（密钥序列+记账）。

        线程安全说明：OpenAICompatibleLLMProvider 仅持有不可变配置与
        urlopen，每次 generate 发起独立 HTTP 请求、无共享可变状态，并行
        请求线程安全；ChannelHealthStore 自带锁。影子线程数天然
        ≤ hedge_max_candidates（每次调用临时 daemon 线程，无需新池）。
        本函数绝不触碰 self.last_attempts / attempts（主线程独占——D6：
        主请求可能已带着诊断快照返回，worker 事后追加会与调用方串号）。
        """
        credential_config = getattr(self, "_credential_config", None)
        spec = self._spec_for(model_id)
        if spec is None:
            self._hedge_record_failure(
                race,
                model_id,
                LLMProviderError(
                    f"unknown model id: {model_id}",
                    error_kind="provider_not_configured",
                ),
            )
            return
        if not spec.all_api_keys():
            # v21r5：影子路径同样计入 config_missing 重复冷却（与串行路径同语义）。
            _health_record_config_missing(model_id, credential_config)
            self._hedge_record_failure(
                race,
                model_id,
                LLMProviderError(
                    f"model {model_id} api key is empty",
                    error_kind="config_missing",
                ),
            )
            return
        effort = self._resolve_effort(spec, global_effort, complex_task)
        api_keys = spec.all_api_keys()
        for key_index, api_key in enumerate(api_keys):
            options = dict(base_options)
            if effort and effort != "off":
                options["reasoning_effort"] = effort
            else:
                options.pop("reasoning_effort", None)
            configured = base_options.get("timeout_seconds")
            base_timeout = (
                float(configured)
                if isinstance(configured, (int, float)) and float(configured) > 0
                else self.timeout_seconds
            )
            timeout_seconds = self._tighten_timeout(model_id, base_timeout, ema_map)
            if failover_deadline is not None:
                remaining = failover_deadline - time.monotonic()
                if self.max_failover_seconds > 0:
                    remaining = min(remaining, self.max_failover_seconds)
                # 影子 worker 同款止损（v21r2 R1）：同一候选换 key 续跳时，
                # 剩余预算不足一跳不再做残秒尝试；首跳豁免（与串行路径一致）。
                min_hop = _failover_min_hop_seconds(credential_config)
                if remaining <= 0 or (
                    key_index > 0 and min_hop > 0 and remaining < min_hop
                ):
                    error = LLMProviderError(
                        f"model {model_id} failover deadline exceeded",
                        error_kind="timeout",
                    )
                    break
                timeout_seconds = min(timeout_seconds, remaining)
            options["timeout_seconds"] = timeout_seconds
            attempt_started = time.monotonic()
            try:
                provider = self.provider_for(model_id, api_key)
                reply = provider.generate(messages, **options)
            except LLMProviderError as exc:
                if (
                    exc.error_kind in _PARAM_STRIP_RETRY_KINDS
                    and "reasoning_effort" in options
                ):
                    retry_options = dict(options)
                    retry_options.pop("reasoning_effort", None)
                    try:
                        reply = provider.generate(messages, **retry_options)
                    except LLMProviderError as retry_exc:
                        exc = retry_exc
                    except Exception as retry_exc:  # noqa: BLE001 - 影子线程二次异常不得炸线程：炸了等待方永远等不到 settle。
                        exc = LLMProviderError(
                            f"model {model_id} failed: {type(retry_exc).__name__}",
                            error_kind="provider_error",
                        )
                    else:
                        _health_record_success(
                            model_id,
                            int((time.monotonic() - attempt_started) * 1000),
                            credential_config,
                        )
                        self._hedge_settle(race, model_id, reply)
                        return
                error = exc
                _health_record_failure(model_id, exc.error_kind, credential_config)
                # 被拒密钥可用同模型下一把显式密钥顶替；绝不重试同一坏 key。
                if exc.error_kind == "auth" and key_index + 1 < len(api_keys):
                    continue
                break
            except Exception as exc:  # noqa: BLE001 - 工厂/供应商异常统一为可转移错误。
                error = LLMProviderError(
                    f"model {model_id} failed: {type(exc).__name__}",
                    error_kind="provider_error",
                )
                _health_record_failure(model_id, "provider_error", credential_config)
                break
            _health_record_success(
                model_id,
                int((time.monotonic() - attempt_started) * 1000),
                credential_config,
            )
            self._hedge_settle(race, model_id, reply)
            return
        if error is None:
            error = LLMProviderError(
                f"model {model_id} failed", error_kind="provider_error"
            )
        self._hedge_record_failure(race, model_id, error)

    @staticmethod
    def _hedge_record_failure(
        race: _HedgeRace, model_id: str, error: LLMProviderError
    ) -> None:
        with race.cond:
            race.failures[model_id] = error
            if not should_failover(error.error_kind):
                race.terminal_error = error
            race.finished += 1
            race.cond.notify_all()

    @staticmethod
    def _hedge_settle(race: _HedgeRace, model_id: str, reply: object) -> None:
        """worker 完成（成功）：先到者认领 winner，后到者记为落选者。"""
        with race.cond:
            if race.winner_reply is None:
                race.winner_id = model_id
                race.winner_reply = reply
            else:
                race.losers.append(model_id)
            race.finished += 1
            race.cond.notify_all()

    def _sibling_channel_ids(self, spec: ModelSpec, *, exclude: str) -> list[str]:
        """同一实际模型名的兄弟渠道（价格/EWMA 序），exclude 自己。

        「单个渠道入口」与「模型 ID 入口」连通（2026-09-13 用户裁定）：
        管理员指定注册条目 id 时，服务同一模型名的其余渠道自动进入候选集，
        首选渠道失败即同模型内拨转，用户无感。
        """
        try:
            channels = self.channels_for_model(spec.model)
        except Exception:  # noqa: BLE001 - 聚合失败退回单渠道，不阻塞路由。
            return []
        return [model_id for model_id in channels if model_id != exclude]

    def route_ids(
        self, *, message_text: str, override: str, session_key: str = ""
    ) -> list[str]:
        """返回按优先级排列的候选模型 id 列表。

        override 既可以是注册条目 id，也可以是实际模型名（如
        ``gemini-3.8-flash-high``）：后者自动聚合该模型的全部渠道，
        按价格/优先级排序走故障转移。

        解析顺序（修 D2：旧实现以 ``_spec_for(override) is None`` 为聚合
        前置，但 _spec_for 对未知 id 恒合成 fallback spec，聚合分支生产
        不可达）：注册条目 id 精确命中 → 单渠道路由；未命中但能按模型名/
        别名聚合出 ≥1 渠道 → channels_for_model 聚合；再未命中才按完整
        模型名合成 fallback spec（旧版「直接给模型名」兼容）。

        同模型多渠道连通（2026-09-13）：注册条目 id 精确命中时，该 id 排
        首位，同模型名的兄弟渠道紧随其后（价格/EWMA 序），再接其余模型；
        模型名聚合分支同样去重——已进候选集的渠道不再重复出现在尾部自动
        队列里（旧实现兄弟渠道会被尝试两次）。
        """
        override = (override or "").strip()
        if override and override != _AUTO:
            if override in self.specs or (
                self._fallback_spec is not None
                and override == self._fallback_spec.model_id
            ):
                # 管理员给的注册条目 id：该渠道优先，同模型兄弟渠道紧随
                # （首选失败 → 同模型下一渠道，计费归因实际服务渠道），
                # 最后按序转移其他模型。
                spec = self._spec_for(override)
                siblings = (
                    self._sibling_channel_ids(spec, exclude=override)
                    if spec is not None
                    else []
                )
                head = [override, *siblings]
                taken = set(head)
                tail = [
                    model_id
                    for model_id in self._auto_route_ids(message_text, session_key="")
                    if model_id not in taken
                ]
                return [*head, *tail]
            channels = self.channels_for_model(override)
            if channels:
                taken = set(channels)
                tail = [
                    model_id
                    for model_id in self._auto_route_ids(message_text, session_key="")
                    if model_id not in taken
                ]
                return [*channels, *tail]
            if self._fallback_spec is not None:
                # 完全未知的 id：当作完整模型名走主配置的接口/密钥（旧版兼容）。
                return [override, *self._auto_route_ids(message_text, exclude=override, session_key="")]
            # 无兜底配置：退回自动路由。
            return self._auto_route_ids(message_text)
        # 纯自动路由：内容感知路由仅在此分支生效（管理员 override 分支以上
        # 均不传 session_key，语义=显式指定不受内容路由摆布）。
        return self._auto_route_ids(message_text, session_key=session_key)

    def _active_group_order(self, *, now: datetime | None = None) -> tuple[str, list[str]]:
        """返回 (当前命中分组名, 组内模型顺序)；未配置/未命中返回 ("", [])。

        每次选型实时计算，不需要后台定时器；分组配置热更后立即生效。
        """
        if self._priority_groups_cb is None:
            return "", []
        try:
            raw = self._priority_groups_cb()
        except Exception:  # noqa: BLE001 - 分组读取失败时回退注册表 priority 顺序。
            return "", []
        groups = parse_priority_groups(raw)
        if not groups:
            return "", []
        moment = now if now is not None else datetime.now(self._zone)
        active = resolve_active_priority_group(groups, moment)
        if active is None:
            return "", []
        return str(active.get("name", "")), list(active["order"])

    def _auto_route_ids(
        self, message_text: str, exclude: str = "", session_key: str = ""
    ) -> list[str]:
        """自动候选顺序：时段分组命中 → 组内 order；否则注册表 priority。

        ``message_text`` 供内容感知路由回调（R-18 判定读请求文本；本函数
        不再参与排序，思考强度交给 effort 体系）。
        """
        ordered = sorted(
            (spec for spec in self.specs.values() if "manual" not in spec.tags),
            key=lambda spec: (spec.priority, spec.model_id),
        )
        ids = [spec.model_id for spec in ordered]
        _, group_order = self._active_group_order()
        if group_order:
            # v21r2 R1（R7 移交①核实属实+修复）：组内 order 条目既收渠道 id
            # 也收模型名/别名。生产 .env 用真模型名（gemini-3.8-flash→…）而
            # 注册表 id 形如 axon-gemini-38f——旧实现只按渠道 id 匹配恒 no-op
            # （BOT_MODEL_PRIORITY_GROUPS 从未生效过）。名称条目展开为该模型
            # 全部渠道，沿用 ordered 的注册表 (priority, model_id) 序：分组
            # 只重排**模型先后**，渠道选择仍严格归注册表优先级（用户令）。
            known = {spec.model_id for spec in ordered}
            by_name: dict[str, list[str]] = {}
            for spec in ordered:
                by_name.setdefault(spec.model.strip().lower(), []).append(spec.model_id)
                for alias in spec.aliases:
                    by_name.setdefault(str(alias).strip().lower(), []).append(spec.model_id)
            head: list[str] = []
            head_set: set[str] = set()
            for entry in group_order:
                entry_key = str(entry).strip().lower()
                matches = by_name.get(entry_key) or (
                    [entry_key] if entry_key in known else []
                )
                for model_id in matches:
                    if model_id not in head_set:
                        head_set.add(model_id)
                        head.append(model_id)
            if head:
                ids = [*head, *(model_id for model_id in ids if model_id not in head_set)]
        if exclude:
            ids = [model_id for model_id in ids if model_id != exclude]
        # getattr 兼容测试的 __new__ 裸构造（绕过 __init__ 手工装配属性）。
        content_cb = getattr(self, "_content_route_cb", None)
        if content_cb is not None and session_key and not exclude and ids:
            # R-18 内容感知路由：verdict=INTIMATE 时把 head 模型（grok →
            # gemini，配置序）提到候选最前。回调内部 fail-open；任何异常
            # 或 verdict 非 intimate 都原样返回默认队列。
            try:
                verdict = content_cb(session_key, message_text)
            except Exception:  # noqa: BLE001 - 内容路由失败不影响默认路由。
                verdict = None
            if isinstance(verdict, dict) and verdict.get("mode") == "intimate":
                # 用户裁定（2026-09-16）：内容路由的候选头插必须永远遵循注册表
                # 故障转移优先级，绝不做 EWMA 延迟重排（此前用 channels_for_model
                # 会把慢但优先级低的渠道顶到前面——浅夜の梦抢恒星纪元即此因）。
                # 语义：head_models 顺序=模型组先后（grok 组整体在 gemini 组前）；
                # 组内多渠道按注册表 (priority, model_id) 排。
                priority_order = sorted(
                    self.specs.values(),
                    key=lambda spec: (spec.priority, spec.model_id),
                )
                content_head: list[str] = []
                for name in verdict.get("head_models") or []:
                    model_name = str(name).strip().lower()
                    if not model_name:
                        continue
                    content_head.extend(
                        spec.model_id
                        for spec in priority_order
                        if spec.model.lower() == model_name
                        or any(alias.lower() == model_name for alias in spec.aliases)
                    )
                if content_head:
                    head_set = set(content_head)
                    ids = [
                        *content_head,
                        *(model_id for model_id in ids if model_id not in head_set),
                    ]
        return ids

    # ==================== B5 M1：出口记账（唯一挂钩点） ====================

    def _call_recording_enabled(self) -> bool:
        """是否需要在 generate 出口记账：显式注入 sink 或账本开关打开。

        开关解析在 llm/ledger.ledger_enabled（Config bot_llm_billing_enabled
        → os.environ BOT_LLM_BILLING_ENABLED → 默认关）。惰性导入：开关
        关闭时不引入任何 ledger 符号路径，行为与现状完全一致。
        """
        if getattr(self, "_call_record_sink", None) is not None:
            return True
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
                ledger_enabled,
            )

            return ledger_enabled(getattr(self, "_credential_config", None))
        except Exception:  # noqa: BLE001 - 开关读取失败按关处理。
            return False

    @staticmethod
    def _last_channel_id(attempts: list[str]) -> str:
        """从 attempts 轨迹解析最后触达的渠道 id（记账投影用）。

        记号格式：``{model_id}:{error_kind|success|config_missing}``、
        ``failover:deadline``、``hedged:{model_id}:winner|loser``。
        ``failover:`` 非渠道路径标记，跳过；``hedged:`` 记号里只有
        ``:winner`` 代表实际服务的渠道（影子竞速赢家）——计费归因必须落
        在赢家上（2026-09-13 修复：旧实现跳过全部 hedged 记号，影子并发
        成功时渠道/价格归因双双落空）；``:loser`` 落选未服务，跳过。
        全是 loser 记号时返回空串（attempts_json 里保留完整轨迹可溯）。
        """
        for mark in reversed(attempts):
            if mark.startswith("hedged:"):
                parts = mark[len("hedged:") :].rsplit(":", 1)
                if (
                    len(parts) == 2
                    and parts[1] == "winner"
                    and parts[0].strip()
                ):
                    return parts[0].strip()
                continue
            if mark.startswith("failover:"):
                continue
            model_id = mark.split(":", 1)[0].strip()
            if model_id:
                return model_id
        return ""

    def _emit_call_record(
        self,
        *,
        request_id: str,
        call_seq: int,
        session_id: str,
        capability: str,
        started_at: str,
        started_mono: float,
        reply: LLMReply | None,
        error: LLMProviderError | None,
        global_effort: str,
        complex_task: bool,
    ) -> None:
        """出口记账：组装一条 LLMCallDraft 交给 sink；吞掉一切异常。

        与 D6 语义对齐：attempts 从 reply.attempts / exc.attempts（出口
        已整体发布）读取，不触碰 self.last_attempts。status 映射：成功 =
        success；失败轨迹含 ``failover:deadline`` = deadline；其余 =
        provider_failed。M1 无 PricingService：cost 全 NULL、unpriced 按
        token 消耗标记（见 llm/ledger.build_call_draft）。
        """
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
                build_call_draft,
                emit_call_record,
            )

            if reply is not None:
                attempts = list(reply.attempts)
                status = "success"
                error_kind = ""
                error_summary = ""
            else:
                attempts = list(
                    getattr(error, "attempts", None)
                    or getattr(self, "last_attempts", [])
                    or []
                )
                error_kind = str(getattr(error, "error_kind", "") or "")
                status = (
                    "deadline" if "failover:deadline" in attempts else "provider_failed"
                )
                error_summary = str(error) if error is not None else ""
            winner_id = self._last_channel_id(attempts)
            spec = self._spec_for(winner_id) if winner_id else None
            usage = dict(reply.raw_usage) if reply is not None else {}
            draft = build_call_draft(
                request_id=request_id,
                call_seq=call_seq,
                session_id=session_id,
                capability=capability,
                started_at=started_at,
                completed_at=datetime.now(self._zone).isoformat(timespec="milliseconds"),
                duration_ms=int((time.monotonic() - started_mono) * 1000),
                provider_id=spec.model_id if spec is not None else winner_id,
                model_id=spec.model_id if spec is not None else winner_id,
                actual_model=(
                    reply.model
                    if reply is not None
                    else (spec.model if spec is not None else "")
                ),
                effort=(
                    self._resolve_effort(spec, global_effort, complex_task)
                    if spec is not None
                    else ""
                ),
                routing_group=spec.routing_group if spec is not None else "",
                usage=usage,
                attempts=attempts,
                finish_reason=str(usage.get("finish_reason", "") or ""),
                status=status,
                error_kind=error_kind,
                error_summary=error_summary,
                # 渠道价随调用透传账本（元/1M tokens）；缺价保持 NULL/unpriced。
                price_in=spec.price_in if spec is not None else None,
                price_out=spec.price_out if spec is not None else None,
                price_cache_read=(
                    spec.price_cache_read if spec is not None else None
                ),
                price_cache_creation=(
                    spec.price_cache_creation if spec is not None else None
                ),
                price_per_call=spec.price_per_call if spec is not None else None,
            )
            emit_call_record(
                sink=getattr(self, "_call_record_sink", None),
                config=getattr(self, "_credential_config", None),
                draft=draft,
            )
        except Exception:  # noqa: BLE001 - 计费故障绝不影响聊天（§4.1.2）。
            return

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        message_text: str = "",
        override: str = "",
        fast_mode: bool = False,
        fast_max_candidates: int = 2,
        deadline_monotonic: float | None = None,
        **kwargs: object,
    ) -> LLMReply:
        """按路由顺序生成；每个候选的每个密钥失败后自动切换下一个。

        尝试顺序：候选模型 × 该模型的密钥列表（api_keys 顺序），
        全部失败抛出最后一个错误。

        B5 M1 出口记账：本方法只是薄包装——真实路由逻辑在
        ``_generate_impl``；成功与最终异常两分支在此统一组装
        ``LLMCallDraft`` 交给注入的 sink（llm/ledger），失败绝不阻塞聊天。
        调用方可选传入账本作用域 kwargs：``request_id`` / ``call_seq`` /
        ``session_id`` / ``capability``（进入路由前剥离，绝不透传给
        provider）。未注入 sink 且账本开关关闭时零开销直通。
        """
        request_id = str(kwargs.pop("request_id", "") or "")
        # 不 pop：session_id 继续流入 _generate_impl，供内容感知路由作会话键
        # （账本与路由共用同一作用域字段，旧调用方零感知）。
        session_id = str(kwargs.get("session_id", "") or "")
        capability = str(kwargs.pop("capability", "") or "")
        raw_call_seq = kwargs.pop("call_seq", 1)
        try:
            call_seq = max(1, int(raw_call_seq))  # type: ignore[call-overload]
        except (TypeError, ValueError):
            call_seq = 1
        impl_kwargs: dict[str, object] = dict(kwargs)
        if not self._call_recording_enabled():
            return self._generate_impl(
                messages,
                message_text=message_text,
                override=override,
                fast_mode=fast_mode,
                fast_max_candidates=fast_max_candidates,
                deadline_monotonic=deadline_monotonic,
                **impl_kwargs,
            )
        started_mono = time.monotonic()
        started_at = datetime.now(self._zone).isoformat(timespec="milliseconds")
        global_effort = normalize_effort(impl_kwargs.get("reasoning_effort", ""))
        effective_text = str(
            message_text or (messages[-1].get("content", "") if messages else "")
        )
        complex_task = len(effective_text) >= _COMPLEX_MIN_CHARS or any(
            keyword in effective_text for keyword in _COMPLEX_KEYWORDS
        )
        if complex_task and _intimate_mode_for_session(self, session_id or "", effective_text):
            # 亲密会话不升档（2026-09-17 成本裁定）：RP 文本易误触发复杂判据，
            # INTIMATE 态维持基线/全局档，不顶到家族最高档。
            complex_task = False
        try:
            reply = self._generate_impl(
                messages,
                message_text=message_text,
                override=override,
                fast_mode=fast_mode,
                fast_max_candidates=fast_max_candidates,
                deadline_monotonic=deadline_monotonic,
                **impl_kwargs,
            )
        except LLMProviderError as exc:
            self._emit_call_record(
                reply=None,
                error=exc,
                request_id=request_id,
                call_seq=call_seq,
                session_id=session_id,
                capability=capability,
                started_at=started_at,
                started_mono=started_mono,
                global_effort=global_effort,
                complex_task=complex_task,
            )
            raise
        except Exception as exc:
            synthesized = LLMProviderError(
                f"model router failed: {type(exc).__name__}",
                error_kind="provider_error",
            )
            synthesized.attempts = list(getattr(self, "last_attempts", []) or [])
            self._emit_call_record(
                reply=None,
                error=synthesized,
                request_id=request_id,
                call_seq=call_seq,
                session_id=session_id,
                capability=capability,
                started_at=started_at,
                started_mono=started_mono,
                global_effort=global_effort,
                complex_task=complex_task,
            )
            raise
        self._emit_call_record(
            reply=reply,
            error=None,
            request_id=request_id,
            call_seq=call_seq,
            session_id=session_id,
            capability=capability,
            started_at=started_at,
            started_mono=started_mono,
            global_effort=global_effort,
            complex_task=complex_task,
        )
        return reply

    def _intimate_session(self, session_key: str, message_text: str, override: str) -> bool:
        """会话是否处于内容路由 INTIMATE 态（仅纯自动路由消费；fail-open False）。

        管理员 override 分支不受内容路由摆布（route_ids 同语义）；回调异常
        一律按非亲密处理。每次 generate 只调用一次（冷却降级守卫与影子跳过
        共用同一判定，避免前后不一致）。
        """
        if not str(session_key or "").strip():
            return False
        if override and override != _AUTO:
            return False
        cb = getattr(self, "_content_route_cb", None)
        if cb is None:
            return False
        try:
            verdict = cb(str(session_key), str(message_text or ""))
        except Exception:  # noqa: BLE001 - fail-open：判读失败按常规路径。
            return False
        return isinstance(verdict, dict) and verdict.get("mode") == "intimate"

    def _generate_impl(
        self,
        messages: list[dict[str, str]],
        *,
        message_text: str = "",
        override: str = "",
        fast_mode: bool = False,
        fast_max_candidates: int = 2,
        deadline_monotonic: float | None = None,
        **kwargs: object,
    ) -> LLMReply:
        """原 generate() 路由主体（签名与语义不变，见薄包装 docstring）。"""
        self._refresh_dynamic_registry()
        require_vision = bool(kwargs.pop("require_vision", False))
        # 全局思考强度（/bot model think 或 .env 默认）：off = 明确不发送。
        global_effort = normalize_effort(kwargs.pop("reasoning_effort", ""))
        session_key = str(kwargs.pop("session_id", "") or "")
        effective_text = message_text or messages[-1].get("content", "")
        # 上下文钳制（2026-09-17 用户裁定全局默认：输入 128K / 输出 64K）。
        messages = _enforce_context_caps(
            messages,
            kwargs,
            int(getattr(self, "max_input_tokens", DEFAULT_MAX_INPUT_TOKENS) or DEFAULT_MAX_INPUT_TOKENS),
            int(getattr(self, "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS) or DEFAULT_MAX_OUTPUT_TOKENS),
        )
        complex_task = len(effective_text) >= _COMPLEX_MIN_CHARS or any(
            keyword in effective_text for keyword in _COMPLEX_KEYWORDS
        )
        if complex_task and _intimate_mode_for_session(self, session_key, str(effective_text)):
            # 亲密会话不升档（2026-09-17 成本裁定），与薄包装层同语义双保险。
            complex_task = False
        routed_ids = self.route_ids(
            message_text=effective_text,
            override=override,
            session_key=session_key,
        )
        # 内容路由 INTIMATE 判定提前（v21r2 R1）：冷却降级守卫与影子跳过共用
        # 同一判定，保证前后一致；回调只打一次。
        content_intimate = self._intimate_session(session_key, effective_text, override)
        candidate_ids = _health_filter_candidates(routed_ids, self._credential_config)
        # 健康过滤实际剔除的渠道（unavailable 且未到重探时间）；供 INTIMATE
        # grok 回落日志定位死因（冷却降级与健康不可用分开呈现）。
        health_filtered_ids = [
            model_id for model_id in routed_ids if model_id not in set(candidate_ids)
        ]
        # v21r2 R1 近期失败冷却降级：冷却中的渠道稳定移队尾（不剔除）——
        # 治「同一坏渠道每轮都当首发烧满读超时」。
        candidate_ids, demoted_ids = _demote_cooling_candidates(
            candidate_ids, self._credential_config
        )
        if demoted_ids:
            logger.info(
                "llm route cooldown demote count=%d ids=%s",
                len(demoted_ids),
                ",".join(demoted_ids[:8]),
            )
        if content_intimate and candidate_ids:
            # INTIMATE grok 钉第一守卫（用户令 2026-09-17）：任何重排（EWMA/
            # 熔断/优先级）都不得把 grok 挤下第一——除非 grok 渠道自身熔断
            # 冷却中或健康不可用；此时放行临时回落，但必须留下可辨日志。
            grok_ids = {
                model_id
                for model_id in routed_ids
                if (grok_spec := self._spec_for(model_id)) is not None
                and model_family(grok_spec.model) == "grok"
            }
            if grok_ids and candidate_ids[0] not in grok_ids:
                logger.warning(
                    "llm intimate grok fallback: grok 熔断冷却/不可用中，临时回落 "
                    "head=%s demoted=%s health_filtered=%s",
                    candidate_ids[0],
                    ",".join(demoted_ids[:8]) or "-",
                    ",".join(health_filtered_ids[:8]) or "-",
                )
        if require_vision:
            # 视觉双门槛与 supports_vision 对齐（管线检视 #3）：当前接入渠道
            # 默认全部多模态，这里仅排除显式 text-only 标签，不再要求正向
            # vision/multimodal/vlm 标签——否则新渠道忘打标、时段分组只含
            # 无标渠道或健康层拉黑全部带标渠道时，候选集被清空 → 图片消息
            # provider_not_configured 硬失败。
            candidate_ids = [
                model_id
                for model_id in candidate_ids
                if (
                    (spec := self._spec_for(model_id)) is not None
                    and "text-only" not in {tag.lower() for tag in spec.tags}
                )
            ]
        if fast_mode:
            candidate_limit = max(0, int(fast_max_candidates))
            if candidate_limit > 0:
                candidate_ids = candidate_ids[:candidate_limit]
        # 修 D6：attempts 归本次调用私有，只在出口整体发布到
        # self.last_attempts（诊断快照）；审计消费点改读
        # reply.attempts / exc.attempts，并发调用不再互相清空/串号。
        attempts: list[str] = []
        last_error: LLMProviderError | None = None
        # 故障转移窗口 = 自身配置预算与外部请求 deadline（请求级总预算）中更早者。
        failover_deadline: float | None = None
        if self.max_failover_seconds > 0:
            failover_deadline = time.monotonic() + self.max_failover_seconds
        if deadline_monotonic is not None:
            external_deadline = float(deadline_monotonic)
            if external_deadline > 0:
                failover_deadline = (
                    min(failover_deadline, external_deadline)
                    if failover_deadline is not None
                    else external_deadline
                )
        # v2 无损无感切换：影子并发（hedged request）。作用域约束（用户裁定）：
        # auto-route 全局队列仍按策展 priority（默认模型永远 Gemini），
        # 影子并发只影响健康过滤后候选队列内的转移时序。
        # R-18 内容感知路由命中 INTIMATE 时跳过影子：影子候选（grok 之后
        # 的渠道）对此类内容大概率是软化/无效回复，白花一次请求（用户裁定
        # 「不要再 gemini 上花时间」）。content_intimate 已在候选装配段统一
        # 判定（v21r2 R1：与冷却降级守卫共用同一回调结果）。
        hedge_max_candidates, hedge_delay = self._hedge_settings()
        hedged = (
            bool(
                getattr(
                    getattr(self, "_credential_config", None),
                    "bot_chat_hedged_requests_enabled",
                    False,
                )
            )
            and not fast_mode
            and not content_intimate
            and len(candidate_ids) >= 2
            and hedge_max_candidates >= 2
        )
        # 自适应超时的 ema 表每次调用只读一次（健康层关闭时为 None=空转）。
        # require_latency_first=False：EMA 只供快失败钳超时，不参与排序——
        # latency_first 关（v21r2 R1 严格优先级缺省）不得连带关闭自适应超时。
        adaptive_ema_map = (
            _health_ema_latencies(
                getattr(self, "_credential_config", None), require_latency_first=False
            )
            if self._adaptive_timeout_enabled()
            else None
        )
        if hedged:
            hedge_count = min(hedge_max_candidates, len(candidate_ids))
            outcome = self._generate_hedged(
                messages,
                candidate_ids[:hedge_count],
                global_effort=global_effort,
                complex_task=complex_task,
                base_options=dict(kwargs),
                failover_deadline=failover_deadline,
                hedge_delay=hedge_delay,
                adaptive_ema_map=adaptive_ema_map,
            )
            attempts.extend(outcome.attempt_marks)
            if outcome.reply is not None:
                outcome.reply.attempts = list(attempts)
                self.last_attempts = attempts
                return outcome.reply
            remaining_candidates = candidate_ids[hedge_count:]
            if outcome.error is not None:
                last_error = outcome.error
            elif not remaining_candidates:
                # 预算耗尽且影子尚无结果可抛，又没有剩余候选转移：
                # 补 failover:deadline 记号（有剩余候选时由正常循环补，避免重复）。
                attempts.append("failover:deadline")
            # 影子候选全部失败 → 剩余候选继续走下方正常故障转移循环。
            candidate_ids = remaining_candidates
        min_hop_seconds = _failover_min_hop_seconds(self._credential_config)
        provider_attempts = 0  # 已发起的真实 provider 尝试数（config_missing 不计）
        # v21r5 链级 fail-fast 状态：连续网络类失败计数（只计 network/timeout）
        # 与中止旗标。作用域=本次调用链，无跨请求状态。
        consecutive_network_failures = 0
        failfast_abort = False
        for _chain_pos, model_id in enumerate(candidate_ids):
            remaining = (
                failover_deadline - time.monotonic()
                if failover_deadline is not None
                else 0.0
            )
            if failover_deadline is not None and remaining <= 0:
                attempts.append("failover:deadline")
                self.last_attempts = attempts
                break
            if (
                failover_deadline is not None
                and min_hop_seconds > 0
                and provider_attempts >= 1
                and remaining < min_hop_seconds
            ):
                # 链预算止损（v21r2 R1）：已有真实尝试在前且剩余预算不足一跳
                # （缺省 <3s）→ 不再做注定超时的残秒尝试，提前认输止损。
                attempts.append("failover:deadline")
                self.last_attempts = attempts
                break
            spec = self._spec_for(model_id)
            if spec is None:
                continue
            api_keys = spec.all_api_keys()
            if not api_keys:
                # 缺少当前候选的 key 不应构造 provider；如果还有已配置候选，继续走下一个。
                last_error = LLMProviderError(
                    f"model {model_id} api key is empty",
                    error_kind="config_missing",
                )
                attempts.append(f"{model_id}:config_missing")
                # v21r5：config_missing 重复冷却计数（前 2 次放行，进程生命周期
                # 累计 ≥3 次按 10× 常规冷却降速）。中性于链级 fail-fast 计数
                # （未碰网络：既不累加也不打断连续网络失败计数）。
                _health_record_config_missing(model_id, self._credential_config)
                continue
            for key_index, api_key in enumerate(api_keys):
                attempt_options = dict(kwargs)
                # 思考强度：条目显式设置（含 off）> 全局 > 家族基线最低档；
                # 复杂任务把来自全局/家族基线的档位升到家族最高档
                # （与影子并发 worker 共用同一解析）。
                effort = self._resolve_effort(spec, global_effort, complex_task)
                if effort and effort != "off":
                    attempt_options["reasoning_effort"] = effort
                else:
                    attempt_options.pop("reasoning_effort", None)
                # 自适应超时（v2）：已知渠道 EWMA 时收紧单次尝试预算
                # （min(原值, max(8s, ema*3))），再与剩余 failover 预算取小。
                configured_timeout = attempt_options.get("timeout_seconds")
                base_timeout = (
                    float(configured_timeout)
                    if isinstance(configured_timeout, (int, float))
                    and float(configured_timeout) > 0
                    else self.timeout_seconds
                )
                timeout_seconds = self._tighten_timeout(
                    model_id, base_timeout, adaptive_ema_map
                )
                if failover_deadline is not None:
                    remaining = failover_deadline - time.monotonic()
                    # 绝对时钟相减存在 ulp 级舍入，钳回配置窗口上限，保证不超预算。
                    if self.max_failover_seconds > 0:
                        remaining = min(remaining, self.max_failover_seconds)
                    if remaining <= 0:
                        attempts.append("failover:deadline")
                        self.last_attempts = attempts
                        break
                    timeout_seconds = min(timeout_seconds, remaining)
                if failover_deadline is not None or timeout_seconds != base_timeout:
                    attempt_options["timeout_seconds"] = timeout_seconds
                attempt_started = time.monotonic()
                try:
                    provider = self.provider_for(model_id, api_key)
                    # 真实 provider 尝试计数（止损判据）；provider_for 失败
                    # （工厂/配置洞）零网络成本不计。
                    provider_attempts += 1
                    reply = provider.generate(messages, **attempt_options)
                except LLMProviderError as exc:
                    if (
                        exc.error_kind in _PARAM_STRIP_RETRY_KINDS
                        and "reasoning_effort" in attempt_options
                    ):
                        retry_options = dict(attempt_options)
                        retry_options.pop("reasoning_effort", None)
                        try:
                            reply = provider.generate(messages, **retry_options)
                        except LLMProviderError as retry_exc:
                            exc = retry_exc
                        else:
                            attempts.append(
                                f"{model_id}:success_without_reasoning"
                            )
                            # 去参重试成功也必须记健康样本：恒拒 reasoning_effort
                            # 的渠道若只记失败，EWMA 会把它永久饿死并误判超时拉黑。
                            _health_record_success(
                                model_id,
                                int((time.monotonic() - attempt_started) * 1000),
                                self._credential_config,
                            )
                            reply.attempts = list(attempts)
                            self.last_attempts = attempts
                            return reply
                    last_error = exc
                    attempts.append(f"{model_id}:{exc.error_kind}")
                    _health_record_failure(model_id, exc.error_kind, self._credential_config)
                    # 逐跳失败日志（v21r2 R1，治「日志不可辨」）：渠道/死因/
                    # 耗时/生效超时/亲密态一行的诚实记录；grok 家族带 family
                    # 标记，20s 被掐（axonhub 上游挂起）时可 grep family=grok。
                    logger.warning(
                        "llm route hop failed model=%s family=%s kind=%s "
                        "elapsed_ms=%d timeout=%s intimate=%s",
                        model_id,
                        model_family(spec.model),
                        exc.error_kind,
                        int((time.monotonic() - attempt_started) * 1000),
                        attempt_options.get("timeout_seconds"),
                        content_intimate,
                    )
                    # v21r5 链级 fail-fast：连续网络类失败计数（只计 network/
                    # timeout；4xx/auth/server/rate_limited/provider_error 等
                    # 其余结局均打断计数，config_missing 中性不走此分支）。
                    if exc.error_kind in _NETWORK_FAILFAST_KINDS:
                        consecutive_network_failures += 1
                    else:
                        consecutive_network_failures = 0
                    if consecutive_network_failures >= _FAILFAST_CONSECUTIVE_NETWORK:
                        # 大概率全网性故障：立即中止剩余候选链，不再逐渠道烧
                        # ~20s 读超时（实警 15:02 chain=15 跳烧满 300s 预算）。
                        # 走既有链尾失败面：raise last_error → 能力层产出用户
                        # 可见降级回复（私聊五池话术 / 群聊 A-19 降级池）。
                        attempts.append("failover:failfast_network")
                        logger.warning(
                            "llm failfast network abort consecutive=%d kind=%s "
                            "elapsed_ms=%d remaining_candidates=%d",
                            consecutive_network_failures,
                            exc.error_kind,
                            int((time.monotonic() - attempt_started) * 1000),
                            len(candidate_ids) - _chain_pos - 1,
                        )
                        failfast_abort = True
                        break
                    # A rejected key may be replaced by another explicitly configured
                    # credential for the same model. Never retry the same bad key.
                    if exc.error_kind == "auth" and key_index + 1 < len(api_keys):
                        continue
                    if not should_failover(exc.error_kind):
                        exc.attempts = list(attempts)
                        self.last_attempts = attempts
                        raise
                    continue
                except Exception as exc:  # noqa: BLE001 - factory/供应商异常统一为可转移错误。
                    last_error = LLMProviderError(
                        f"model {model_id} failed: {type(exc).__name__}",
                        error_kind="provider_error",
                    )
                    attempts.append(f"{model_id}:provider_error")
                    # 评审探针 P2（v21r5 CRIT-FIX-3）：provider_error 与上方分类
                    # 分支同语义——打断连续网络失败计数（原始异常包装=非网络类
                    # 结局），否则与「provider_error 打断计数」口径相悖，后续
                    # 健康渠道被 fail-fast 误跳过。
                    consecutive_network_failures = 0
                    logger.warning(
                        "llm route hop failed model=%s family=%s kind=provider_error "
                        "elapsed_ms=%d intimate=%s",
                        model_id,
                        model_family(spec.model),
                        int((time.monotonic() - attempt_started) * 1000),
                        content_intimate,
                    )
                    continue
                attempts.append(f"{model_id}:success")
                _health_record_success(
                    model_id,
                    int((time.monotonic() - attempt_started) * 1000),
                    self._credential_config,
                )
                reply.attempts = list(attempts)
                self.last_attempts = attempts
                return reply
            if failfast_abort:
                # v21r5 链级 fail-fast：连续网络类失败达阈值，中止剩余候选链
                # （此处承接内层 key 循环的 break，跳出外层候选循环）。
                break
        self.last_attempts = attempts
        if last_error is not None:
            last_error.attempts = list(attempts)
            raise last_error
        if "failover:deadline" in attempts:
            # 预算耗尽不是"未配置供应商"：没有任何候选来得及给出真错误时
            # 保留 timeout 语义，别把诊断引去查配置。
            budget_error = LLMProviderError(
                "LLM failover budget exhausted before any candidate answered",
                error_kind="timeout",
            )
            budget_error.attempts = list(attempts)
            raise budget_error
        no_model_error = LLMProviderError(
            "no model available",
            error_kind="provider_not_configured",
        )
        no_model_error.attempts = list(attempts)
        raise no_model_error


def build_model_router(
    config: object,
    *,
    provider_factory: Callable[[ModelSpec], Any] | None = None,
    dynamic_registry: Callable[[], dict[str, dict[str, Any]]] | None = None,
    priority_groups: Callable[[], Any] | None = None,
    content_route_cb: Callable[[str, str], dict[str, Any]] | None = None,
) -> ModelRouter:
    """组装项目自己的 OpenAI-compatible 直连模型路由。

    注册表中的每个条目可以指向不同的第三方兼容接口；路由器按 tags/priority
    自动选型，并在请求失败后按优先级转移到下一个已配置模型。

    注册表优先，预设名与主配置模型一并可解析。

    - 注册表（BOT_MODEL_REGISTRY）条目按各自 tags/priority 参与自动选型；
    - 预设（BOT_MODEL_PRESETS）只接受手动指定（``/bot runtime model set <预设名>``），
      不会在自动选型中抢占注册表/主模型；
    - 主配置模型（BOT_CHAT_MODEL）在注册表为空时充当默认模型（旧版行为），
      注册表存在时退居兜底；
    - 手动覆盖给出注册表/预设之外的名称时，按完整模型名用主配置接口调用；
    - dynamic_registry 提供运行时注册表（聊天指令维护），每次生成前合并，
      新增/修改/删除即时生效。
    """
    registry = build_model_registry(config)
    main_spec = _main_fallback_spec(config)
    has_registry = bool(registry)

    specs: dict[str, ModelSpec] = dict(registry)
    for name, spec in _preset_specs(config).items():
        specs.setdefault(name, spec)
    if main_spec is not None:
        if has_registry:
            # 注册表在场时主配置模型退居兜底，不参与自动选型抢位。
            main_spec = ModelSpec(
                model_id=main_spec.model_id,
                model=main_spec.model,
                base_url=main_spec.base_url,
                api_key=main_spec.api_key,
                tags=("manual",),
                priority=2000,
            )
        specs.setdefault(main_spec.model_id, main_spec)
    fast_mode = bool(getattr(config, "bot_chat_fast_mode", False))
    normal_timeout = float(getattr(config, "bot_chat_timeout_seconds", 30.0) or 30.0)
    fast_timeout = float(getattr(config, "bot_chat_fast_timeout_seconds", 12.0) or 12.0)
    router = ModelRouter(
        specs,
        provider_factory=provider_factory,
        fallback_spec=main_spec,
        proxy=str(getattr(config, "bot_download_proxy", "") or ""),
        timeout_seconds=min(normal_timeout, fast_timeout) if fast_mode else normal_timeout,
        dynamic_registry=dynamic_registry,
        max_failover_seconds=float(
            getattr(config, "bot_chat_failover_max_seconds", 0.0) or 0.0
        ),
        priority_groups=priority_groups,
        content_route_cb=content_route_cb,
        credential_config=config,
        timezone_name=str(
            getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong"
        ),
    )
    # 上下文钳制全局缺省（2026-09-17 用户裁定：输入 128K / 输出 64K）。
    router.max_input_tokens = int(
        getattr(config, "bot_chat_max_input_tokens", DEFAULT_MAX_INPUT_TOKENS)
        or DEFAULT_MAX_INPUT_TOKENS
    )
    router.max_output_tokens = int(
        getattr(config, "bot_chat_max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        or DEFAULT_MAX_OUTPUT_TOKENS
    )
    return router
