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
默认思考强度 = 家族最高档；条目可用 ``effort`` 字段显式指定（含 off）。
请求时按 条目 effort > 全局 BOT_CHAT_REASONING_EFFORT > 家族默认最高档
发送 ``reasoning_effort``（接口不支持时自动去参重试）。
复杂任务（长文本/教程/排查/分析/写作类关键词）会把来自全局/家族默认的
档位临时升到该模型家族最高档。

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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins.bot_unified_runtime.llm import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
    should_failover,
)

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

# ==================== 思考强度档位 ====================
# 按模型名家族划分的思考强度档位；注册表 tags 直接使用这些档位字符串，
# 默认思考强度 = 家族最高档（元组最后一个元素）。
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


def model_family(model_name: str) -> str:
    """从模型名识别家族（deepseek/glm/kimi/gpt/grok/gemini/minimax）。"""
    lowered = (model_name or "").lower()
    for family in _FAMILY_MATCH_ORDER:
        if family in lowered:
            return family
    return ""


def default_effort(model_name: str) -> str:
    """模型家族的默认思考强度 = 家族最高档；未知家族返回空（不发送）。"""
    tiers = FAMILY_EFFORT_TIERS.get(model_family(model_name))
    return tiers[-1] if tiers else ""


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
    "windows": [["09:00","12:00"],["14:00","18:00"]], "order": [模型id...]}``。
    days 用 ISO 周编号（1=周一…7=周日），缺省 = 每天；windows 缺省 = 全天；
    days/windows 都缺省即为兜底组。命中判定按列表顺序取第一个满足的组。
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
    effort: str = ""  # 思考强度覆盖；空 = 家族默认最高档，off = 不发送
    # 渠道价格（每 1M tokens，币种随渠道报价）；按模型名聚合选渠道时用
    # (price_in+price_out) 均值升序，缺价渠道排在有价渠道之后。
    price_in: float | None = None
    price_out: float | None = None

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
    )


def _health_filter_candidates(model_ids: list[str], config: object | None = None) -> list[str]:
    """从候选队列剔除「暂时不可用」渠道；全部不可用时放行原列表。

    开关与巡检侧同源：channel_health.channel_health_enabled(config)
    （Config 字段 → os.environ → 默认），不再只读 os.environ——生产
    .env-only 部署下 NoneBot 只把配置写进 Config，旧实现会让健康门整体
    空转而巡检照常运行。
    """
    try:
        from plugins.bot_unified_runtime.llm.channel_health import (
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
        from plugins.bot_unified_runtime.llm.channel_health import (
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
        from plugins.bot_unified_runtime.llm.channel_health import (
            channel_health_enabled,
            get_channel_health_store,
        )

        if not channel_health_enabled(config):
            return
        # auth/config 类失败不计渠道健康（是配置问题，不是渠道不可用）。
        if error_kind in {"auth", "config_missing"}:
            return
        get_channel_health_store().record_failure(model_id, f"kind={error_kind}")
    except Exception:  # noqa: BLE001 - 健康记录失败静默，不影响主链路。
        return


def _health_ema_latencies(config: object | None = None) -> dict[str, int] | None:
    """EWMA 平滑延迟表（v2 动态切换）；健康层关闭/故障时返回 None（回落价格序）。

    双开关与巡检侧同源解析（channel_health_latency_first /
    channel_health_enabled）：Config 字段 → os.environ → 默认（延迟择优
    默认开，健康层默认关）。
    """
    try:
        from plugins.bot_unified_runtime.llm.channel_health import (
            channel_health_enabled,
            channel_health_latency_first,
            get_channel_health_store,
        )

        if not channel_health_latency_first(config):
            return None
        if not channel_health_enabled(config):
            return None
        return get_channel_health_store().ema_latencies()
    except Exception:  # noqa: BLE001 - 健康层故障不阻塞路由。
        return None


def _health_latencies(config: object | None = None) -> dict[str, int] | None:
    """实测延迟表（B-1 延迟择优）；健康层关闭/故障时返回 None（回落价格序）。

    与 _health_ema_latencies 同一套开关来源；保留原始实测表给
    channels_for_model 的既有排序语义。
    """
    try:
        from plugins.bot_unified_runtime.llm.channel_health import (
            channel_health_enabled,
            channel_health_latency_first,
            get_channel_health_store,
        )

        if not channel_health_latency_first(config):
            return None
        if not channel_health_enabled(config):
            return None
        return get_channel_health_store().latencies()
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
    return ModelSpec(
        model_id="default",
        model=model,
        base_url=str(getattr(config, "bot_chat_base_url", "")).strip(),
        api_key=str(getattr(config, "bot_chat_api_key", "")),
        tags=("strong",),
        priority=1,
        routing_group="default",
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
    ) -> None:
        self._credential_config = credential_config
        self._timezone_name = timezone_name
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
        """运行时条目 → ModelSpec；env 镜像条目的内容字段以 .env 为新鲜值。

        Task4 之后 runtime store 里 .env 来源条目带 ``source: "env"`` 镜像
        标记。若按镜像快照整体重建，.env 后续编辑（换模型/换地址/换 key）
        会被运行时旧副本遮蔽。因此对镜像条目：内容字段取 ``_base_specs``
        （.env 注册表的最新解析视图）重建，仅 runtime 侧拥有的 priority 与
        ``override_fields`` 里管理员明确改过的字段生效；.env 已删除的条目
        不再被旧镜像复活。纯运行时条目（管理员 add 的自定义模型）整体
        生效，行为不变。
        """
        if item.get("source") != _ENV_DERIVED_SOURCE:
            return _spec_from_entry(model_id, item, self._credential_config)
        base = self._base_specs.get(model_id)
        if base is None:
            return None
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
            return spec
        if self._fallback_spec is None:
            return None
        if model_id == self._fallback_spec.model_id:
            return self._fallback_spec
        return ModelSpec(
            model_id=model_id,
            model=model_id,
            base_url=self._fallback_spec.base_url,
            api_key=self._fallback_spec.api_key,
            tags=self._fallback_spec.tags,
            priority=100,
        )

    def provider_for(self, model_id: str, api_key: str | None = None) -> Any:
        spec = self._spec_for(model_id)
        if spec is None:
            raise KeyError(f"unknown model id: {model_id}")
        cache_key: Any = model_id
        provider_spec = spec
        if api_key is not None and api_key != spec.api_key:
            cache_key = (model_id, api_key)
            provider_spec = replace(spec, api_key=api_key)
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
        """按实际模型名聚合全部渠道（v2 动态切换：EWMA 延迟择优）。

        延迟择优开启且健康库有数据：已实测渠道按平滑延迟（EWMA）升序在前
        （同 ema 按价格/优先级），未实测渠道保价格/优先级序垫底；
        关闭或健康层不可用：价格均值升序 → priority 升序（原行为）。
        作用域仅限同名模型聚合；``_auto_route_ids`` 全局候选队列保持
        人工策展的 priority 顺序，不做延迟重排（默认模型永远是 Gemini，
        用户裁定，不得被延迟排序推翻）。
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
        ema_map = _health_ema_latencies(getattr(self, "_credential_config", None))
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

    # ==================== v2：自适应超时与影子并发 ====================

    @staticmethod
    def _resolve_effort(spec: ModelSpec, global_effort: str, complex_task: bool) -> str:
        """思考强度：条目显式设置（含 off）> 全局 > 家族默认最高档。

        复杂任务把来自全局/家族默认的档位升到家族最高档（串行/影子两路共用）。
        """
        if spec.effort:
            return spec.effort
        if global_effort:
            family_default = default_effort(spec.model)
            return family_default if complex_task and family_default else global_effort
        return default_effort(spec.model)

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
                if remaining <= 0:
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
                    exc.error_kind == "unsupported_parameter"
                    and "reasoning_effort" in options
                ):
                    retry_options = dict(options)
                    retry_options.pop("reasoning_effort", None)
                    try:
                        reply = provider.generate(messages, **retry_options)
                    except LLMProviderError as retry_exc:
                        exc = retry_exc
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

    def route_ids(self, *, message_text: str, override: str) -> list[str]:
        """返回按优先级排列的候选模型 id 列表。

        override 既可以是注册条目 id，也可以是实际模型名（如
        ``gemini-3.8-flash-high``）：后者自动聚合该模型的全部渠道，
        按价格/优先级排序走故障转移。

        解析顺序（修 D2：旧实现以 ``_spec_for(override) is None`` 为聚合
        前置，但 _spec_for 对未知 id 恒合成 fallback spec，聚合分支生产
        不可达）：注册条目 id 精确命中 → 单渠道路由；未命中但能按模型名/
        别名聚合出 ≥1 渠道 → channels_for_model 聚合；再未命中才按完整
        模型名合成 fallback spec（旧版「直接给模型名」兼容）。
        """
        override = (override or "").strip()
        if override and override != _AUTO:
            if override in self.specs or (
                self._fallback_spec is not None
                and override == self._fallback_spec.model_id
            ):
                # 管理员给的注册条目 id：单渠道优先，失败按序转移。
                return [override, *self._auto_route_ids(message_text, exclude=override)]
            channels = self.channels_for_model(override)
            if channels:
                return [*channels, *self._auto_route_ids(message_text, exclude=channels[0])]
            if self._fallback_spec is not None:
                # 完全未知的 id：当作完整模型名走主配置的接口/密钥（旧版兼容）。
                return [override, *self._auto_route_ids(message_text, exclude=override)]
            # 无兜底配置：退回自动路由。
            return self._auto_route_ids(message_text)
        return self._auto_route_ids(message_text)

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

    def _auto_route_ids(self, message_text: str, exclude: str = "") -> list[str]:
        """自动候选顺序：时段分组命中 → 组内 order；否则注册表 priority。

        ``message_text`` 不再参与排序（思考强度交给 effort 体系），保留参数
        是为了兼容 route_ids/supports_vision 的调用形状。
        """
        del message_text
        ordered = sorted(
            (spec for spec in self.specs.values() if "manual" not in spec.tags),
            key=lambda spec: (spec.priority, spec.model_id),
        )
        ids = [spec.model_id for spec in ordered]
        _, group_order = self._active_group_order()
        if group_order:
            known = {spec.model_id for spec in ordered}
            head = [model_id for model_id in group_order if model_id in known]
            head_set = set(head)
            ids = [*head, *(model_id for model_id in ids if model_id not in head_set)]
        if exclude:
            ids = [model_id for model_id in ids if model_id != exclude]
        return ids

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
        全部失败抛出最后一个错误。"""
        self._refresh_dynamic_registry()
        require_vision = bool(kwargs.pop("require_vision", False))
        # 全局思考强度（/bot model think 或 .env 默认）：off = 明确不发送。
        global_effort = normalize_effort(kwargs.pop("reasoning_effort", ""))
        effective_text = message_text or messages[-1].get("content", "")
        complex_task = len(effective_text) >= _COMPLEX_MIN_CHARS or any(
            keyword in effective_text for keyword in _COMPLEX_KEYWORDS
        )
        candidate_ids = self.route_ids(
            message_text=effective_text,
            override=override,
        )
        candidate_ids = _health_filter_candidates(candidate_ids, self._credential_config)
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
            and len(candidate_ids) >= 2
            and hedge_max_candidates >= 2
        )
        # 自适应超时的 ema 表每次调用只读一次（健康层关闭时为 None=空转）。
        adaptive_ema_map = (
            _health_ema_latencies(getattr(self, "_credential_config", None))
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
        for model_id in candidate_ids:
            remaining = (
                failover_deadline - time.monotonic()
                if failover_deadline is not None
                else 0.0
            )
            if failover_deadline is not None and remaining <= 0:
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
                continue
            for key_index, api_key in enumerate(api_keys):
                attempt_options = dict(kwargs)
                # 思考强度：条目显式设置（含 off）> 全局 > 家族默认最高档；
                # 复杂任务把来自全局/家族默认的档位升到家族最高档
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
                    reply = provider.generate(messages, **attempt_options)
                except LLMProviderError as exc:
                    if (
                        exc.error_kind == "unsupported_parameter"
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
                            reply.attempts = list(attempts)
                            self.last_attempts = attempts
                            return reply
                    last_error = exc
                    attempts.append(f"{model_id}:{exc.error_kind}")
                    _health_record_failure(model_id, exc.error_kind, self._credential_config)
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
        self.last_attempts = attempts
        if last_error is not None:
            last_error.attempts = list(attempts)
            raise last_error
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
    return ModelRouter(
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
        credential_config=config,
        timezone_name=str(
            getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong"
        ),
    )
