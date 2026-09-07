"""管理员运行时指令：/bot runtime ... 与 /bot alert check。

在 QQ 对话里直接说命令即可执行，走统一流水线，仅管理员可用：

- ``/bot runtime set <KEY> <VALUE> [--instance <名称>]``  调整运行时参数
- ``/bot runtime get <KEY> [--instance <名称>]``
- ``/bot runtime list [--instance <名称>]``
- ``/bot runtime reset [KEY] [--instance <名称>]``
- ``/bot runtime nickname add|remove|list <昵称> [--instance <名称>]``
- ``/bot runtime instance list``  列出已创建的实例设置文件
- ``/bot alert check [--probe]``  手动执行凭据健康检查

``--instance`` 定位目标机器人实例（守岸人 / 艾弥斯等），缺省为本
进程实例；每个实例的设置、昵称、互动计数彼此隔离。非管理员查询/
执行一律拒绝，且不透露任何内部状态。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    InstanceSettingsManager,
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.sources.credential_health import (
    check_credentials_and_report,
)


def _admin_only_result(request_id: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.runtime",
        kind="text",
        title="权限不足",
        body="该命令只允许管理员使用。",
        confidence=1.0,
        risk_level=RiskLevel.MEDIUM,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", "permission_denied"],
    )


def _ok_result(request_id: str, body: str, capability_id: str = "bot.runtime") -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id=capability_id,
        kind="text",
        title="运行时设置",
        body=body,
        confidence=1.0,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", capability_id],
    )


def _error_result(request_id: str, message: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.runtime",
        kind="text",
        title="运行时设置失败",
        body=message,
        confidence=1.0,
        risk_level=RiskLevel.MEDIUM,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", "runtime_admin_error"],
    )


def _extract_instance(parts: list[str]) -> tuple[list[str], str]:
    """从命令片段中提取 --instance <名称>；返回 (剩余片段, 实例名)。"""
    instance = ""
    remaining: list[str] = []
    index = 0
    while index < len(parts):
        if parts[index] == "--instance" and index + 1 < len(parts):
            instance = parts[index + 1]
            index += 2
            continue
        remaining.append(parts[index])
        index += 1
    return remaining, instance


def _handle_runtime_command(
    manager: InstanceSettingsManager,
    default_instance: str,
    config: object,
    command_text: str,
    *,
    diagnostics_store: Any | None = None,
    usage_store: Any | None = None,
) -> str:
    parts = command_text.split()
    if not parts:
        return "用法：/bot runtime set|get|list|reset|nickname|instance ..."
    action = parts[0].lower()
    if action == "instance" and len(parts) > 1 and parts[1].lower() == "list":
        instances = manager.list_instances()
        return (
            f"已有实例设置：{','.join(instances)}"
            if instances
            else "还没有任何实例设置文件（首次运行时自动创建）。"
        )
    remaining, instance = _extract_instance(parts[1:])
    store = manager.get(instance or default_instance)
    instance_label = f"[实例 {store.instance}] "
    if action == "set":
        if len(remaining) < 2:
            return "用法：/bot runtime set <KEY> <VALUE> [--instance <名称>]"
        key, value = remaining[0], " ".join(remaining[1:])
        converted = store.set_override(key, value)
        return f"{instance_label}已设置 {key.upper()} = {converted}（已持久化，目标实例会自动刷新）。"
    if action == "get":
        if len(remaining) < 1:
            return "用法：/bot runtime get <KEY> [--instance <名称>]"
        key = remaining[0].upper()
        if key not in SETTABLE_KEYS:
            return f"不支持查询的键：{key}。可用键：{','.join(sorted(SETTABLE_KEYS))}"
        value = store.get(key, config)
        suffix = "（覆盖值）" if key in store.list_overrides() else "（.env 默认值）"
        return f"{instance_label}{key} = {value}{suffix}"
    if action == "list":
        overrides = store.list_overrides()
        if not overrides:
            return f"{instance_label}当前没有运行时覆盖，全部使用 .env 配置。"
        return "\n".join(
            f"{instance_label}{key} = {value}" for key, value in sorted(overrides.items())
        )
    if action == "reset":
        reset_key = remaining[0] if remaining else None
        count = store.reset_override(reset_key)
        return f"{instance_label}已清除 {count} 项运行时覆盖。"
    if action == "nickname":
        return f"{instance_label}{_handle_nickname_command(store, remaining)}"
    if action == "persona":
        return f"{instance_label}{_handle_persona_command(store, config, remaining)}"
    if action == "model":
        return f"{instance_label}{_handle_model_command(store, config, remaining, diagnostics_store=diagnostics_store, usage_store=usage_store)}"
    return (
        "用法：/bot runtime set <KEY> <VALUE> | get <KEY> | list | "
        "reset [KEY] | nickname add/remove/list <昵称> | persona list|switch|probability "
        "| model list|set|reset | instance list（均可加 --instance <名称> 定位实例）"
    )


def _family_default_effort(model_name: str) -> str:
    from plugins.bot_unified_runtime.llm.model_router import default_effort

    return default_effort(model_name)


def _active_priority_group(
    store: RuntimeSettingsStore,
    config: object,
) -> tuple[str, list[str]]:
    """当前命中的时段优先级分组 (name, order)；未配置/未命中返回 ("", [])。"""
    from datetime import datetime as _dt

    from plugins.bot_unified_runtime.llm.model_router import (
        parse_priority_groups,
        resolve_active_priority_group,
    )

    raw = store.get_or(
        "BOT_MODEL_PRIORITY_GROUPS",
        getattr(config, "bot_model_priority_groups", []) or [],
    )
    groups = parse_priority_groups(raw)
    if not groups:
        return "", []
    timezone_name = str(
        getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong"
    )
    try:
        zone: Any = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")
    active = resolve_active_priority_group(groups, _dt.now(zone))
    if active is None:
        return "", []
    return str(active.get("name", "")), list(active.get("order", []))


def _handle_model_command(
    store: RuntimeSettingsStore,
    config: object,
    parts: list[str],
    *,
    diagnostics_store: Any | None = None,
    usage_store: Any | None = None,
) -> str:
    from plugins.bot_unified_runtime.llm.model_router import build_model_registry

    registry = build_model_registry(config)
    runtime_registry = store.list_model_registry()
    raw_env_registry = {
        str(key): dict(item)
        for key, item in (getattr(config, "bot_model_registry", {}) or {}).items()
        if isinstance(item, dict)
    }
    presets = dict(getattr(config, "bot_model_presets", {}) or {})
    default_model = str(getattr(config, "bot_chat_model", ""))
    auto_route = bool(getattr(config, "bot_model_auto_route", True))
    if not parts or parts[0].lower() == "list":
        current = store.get_or("BOT_CHAT_MODEL", "")
        lines = [
            "当前模型："
            + (current if current else f"自动路由（{default_model} 兜底）")
        ]
        group_name, _group_order = _active_priority_group(store, config)
        if group_name:
            lines.append(f"当前时段分组：{group_name}（按组内 order 排序）")
        else:
            lines.append("当前时段分组：未命中（按注册表 priority 顺序）")
        merged: dict[str, dict[str, Any]] = {}
        for model_id, spec in registry.items():
            merged[model_id] = {
                "model": spec.model,
                "base_url": spec.base_url,
                "tags": list(spec.tags),
                "priority": spec.priority,
                "effort": spec.effort,
                "source": "env",
            }
        for model_id, entry in runtime_registry.items():
            merged[model_id] = {
                "model": str(entry.get("model", "")),
                "base_url": str(entry.get("base_url", "")),
                "tags": entry.get("tags") or [],
                "priority": entry.get("priority", 100),
                "effort": str(entry.get("effort", "") or ""),
                "source": "runtime",
            }
        if merged:
            from plugins.bot_unified_runtime.llm.model_router import (
                normalize_priority_entries,
            )

            merged = normalize_priority_entries(merged)
            lines.append("── 注册的模型（故障转移顺序：唯一 priority 槽位，1 为首选）──")
            ordered = sorted(
                merged.items(), key=lambda kv: (int(kv[1]["priority"]), kv[0])
            )
            for order, (model_id, entry) in enumerate(ordered, start=1):
                tags = entry["tags"]
                tag_text = (
                    ",".join(tags) if isinstance(tags, (list, tuple)) else str(tags)
                )
                effort_text = str(entry.get("effort", "") or "") or _family_default_effort(
                    str(entry.get("model", ""))
                )
                effort_suffix = (
                    "" if entry.get("effort") else "（默认）"
                )
                lines.append(
                    f"{order}. {model_id} = {entry['model']} @ {entry['base_url']}"
                    f" [{tag_text}] effort={effort_text or 'off'}{effort_suffix}"
                    f" priority={entry['priority']}"
                    + ("（自定义）" if entry["source"] == "runtime" else "")
                )
        else:
            lines.append("── 还没有注册任何模型（用 add 注册，见下方第 ③ 步）──")
        if presets:
            lines.append("── 预设 ──")
            lines.append("，".join(f"{k}={v}" for k, v in presets.items()))
        lines.append("── 怎么用 ──")
        lines.append(
            "① 启用某个模型：/bot model set <id>（例：/bot model set "
            + (ordered[0][0] if merged else "myapi")
            + "）"
        )
        lines.append(
            "② 回到自动选型：/bot model set auto"
            + ("（按时段分组/priority 顺序自动选型，失败自动转移）" if auto_route else "")
        )
        lines.append(
            "③ 注册新供应商：/bot model add <id> model=<模型名> base_url=<接口> "
            "key=<密钥> tags=<思考强度档位> effort=<档位> priority=<n>"
        )
        lines.append("④ 图片识别模型：/bot model vision list；模式：vision mode relay|direct")
        lines.append("⑤ 强度/推理/价格/用量：/bot model effort|think|price|usage")
        return "\n".join(lines)
    action = parts[0].lower()
    if action in {"set", "切换"}:
        if len(parts) < 2:
            return "用法：/bot model set <id|auto>"
        name = parts[1].strip()
        if name.lower() == "auto":
            store.reset_override("BOT_CHAT_MODEL")
            return "已切换为自动选型（按时段分组/priority 顺序，失败自动转移；思考强度按档位体系）。"
        known_ids = set(registry) | set(runtime_registry)
        if known_ids and name in known_ids:
            store.set_override("BOT_CHAT_MODEL", name)
            label = runtime_registry.get(name, {}).get("model", "") or (
                registry[name].model if name in registry else ""
            )
            return f"已手动指定模型：{name}（{label}）。失败时自动转移其他模型。"
        if name in presets:
            model = presets[name]
            store.set_override("BOT_CHAT_MODEL", name)
            return f"已手动指定模型：{name}（{model}）。"
        # 允许直接给完整模型名（兼容旧用法；无注册表时走主 provider）。
        store.set_override("BOT_CHAT_MODEL", name)
        return f"已手动指定模型：{name}。"
    if action == "reset":
        store.reset_override("BOT_CHAT_MODEL")
        return f"已恢复自动选型（默认兜底 {default_model}）。"
    if action in {"think", "思考", "reasoning"}:
        if len(parts) < 2:
            return "用法：/bot model think <off|low|medium|high|xhigh|max>"
        try:
            effort = SETTABLE_KEYS["BOT_CHAT_REASONING_EFFORT"](parts[1])
        except (KeyError, ValueError) as exc:
            return str(exc)
        store.set_override("BOT_CHAT_REASONING_EFFORT", effort)
        if effort == "off":
            return "reasoning_effort 已设为 off：不发送思考强度字段。"
        if not effort:
            return "reasoning_effort 已清空：各模型回到家族默认最高档。"
        return f"reasoning_effort（推理思考强度）已设为：{effort}。"
    if action in {"effort", "强度", "思考强度"}:
        if len(parts) < 3:
            return (
                "用法：/bot model effort <id> <off|low|medium|high|xhigh|max|default>；"
                "default=清除覆盖回到家族默认最高档"
            )
        model_id = parts[1].strip()
        value = parts[2].strip().lower()
        base_entry = runtime_registry.get(model_id) or raw_env_registry.get(model_id)
        if base_entry is None:
            return f"不存在的模型 id：{model_id}。"
        entry = dict(base_entry)
        if value in {"default", "默认", "reset"}:
            entry.pop("effort", None)
            store.set_model_entry(model_id, entry)
            return (
                f"已清除 {model_id} 的思考强度覆盖，回到家族默认"
                f"（{_family_default_effort(str(entry.get('model', ''))) or '不发送'}）。"
            )
        from plugins.bot_unified_runtime.llm.model_router import normalize_effort

        normalized = normalize_effort(value)
        if not normalized:
            return "effort 必须是 off/low/medium/high/xhigh/max/default。"
        entry["effort"] = normalized
        store.set_model_entry(model_id, entry)
        if normalized == "off":
            return f"模型 {model_id} 的思考强度已设为 off（不发送 reasoning_effort）。"
        return f"模型 {model_id} 的思考强度已设为 {normalized}（存为运行时覆盖）。"
    if action in {"price", "价格", "计价"}:
        if len(parts) < 2:
            return (
                "用法：/bot model price <模型名> input=<元/1M输入> output=<元/1M输出>；"
                "例：/bot model price deepseek-v4-pro input=4 output=16"
            )
        model_name = parts[1].strip()
        try:
            kv = _parse_kv_pairs(parts[2:])
        except ValueError as exc:
            return str(exc)
        if not model_name:
            return "模型名不能为空。"
        raw_prices = store.get_or(
            "BOT_MODEL_PRICES", getattr(config, "bot_model_prices", {}) or {}
        )
        from plugins.bot_unified_runtime.runtime.pricing import parse_model_prices

        prices = parse_model_prices(raw_prices)
        if not kv:
            # 不带价格参数 = 清除该模型价格，回到未计价。
            prices.pop(model_name, None)
            store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False))
            return f"已清除 {model_name} 的价格（该模型回到未计价）。"
        entry_prices = dict(prices.get(model_name, {}))
        for key in ("input", "output"):
            if key in kv:
                try:
                    number = float(kv[key])
                except ValueError:
                    return f"{key} 必须是数字（元/每百万 token）。"
                if number < 0:
                    return f"{key} 不能为负数。"
                entry_prices[key] = number
        if not entry_prices:
            prices.pop(model_name, None)
            store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False))
            return f"已清除 {model_name} 的价格（该模型回到未计价）。"
        prices[model_name] = entry_prices
        store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False))
        return (
            f"已设置 {model_name} 价格：输入 {entry_prices.get('input', 0.0):g} 元/1M，"
            f"输出 {entry_prices.get('output', 0.0):g} 元/1M。之后的调用按新价格记账。"
        )
    if action in {"search", "搜索", "联网"}:
        if len(parts) < 2:
            return "用法：/bot model search <on|off>"
        try:
            enabled = SETTABLE_KEYS["BOT_WEB_SEARCH_ENABLED"](parts[1])
        except (KeyError, ValueError) as exc:
            return str(exc)
        store.set_override("BOT_WEB_SEARCH_ENABLED", parts[1])
        return f"web_search（联网搜索）已{'开启' if enabled else '关闭'}。"
    if action in {"usage", "用量", "token", "账单"}:
        if diagnostics_store is None and usage_store is None:
            return "暂无可用的模型用量统计。"
        timezone_name = str(getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong")
        try:
            timezone = ZoneInfo(timezone_name)
        except (KeyError, ValueError):
            timezone = ZoneInfo("UTC")
        target_date = datetime.now(timezone).date()
        if len(parts) > 1 and parts[1].lower() not in {"today", "今天"}:
            try:
                target_date = date.fromisoformat(parts[1])
            except ValueError:
                return "用法：/bot model usage [today|YYYY-MM-DD]"
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_milli": 0,
            "calls": 0,
        }
        by_model: dict[str, int] = {}
        by_prompt: dict[str, int] = {}
        by_completion: dict[str, int] = {}
        by_cost: dict[str, int] = {}
        unpriced_calls = 0
        if usage_store is not None and callable(
            getattr(usage_store, "aggregate_llm_usage_range", None)
        ):
            usage = usage_store.aggregate_llm_usage_range(
                target_date.isoformat(), target_date.isoformat()
            )
            for key in totals:
                totals[key] = int(usage.get(key, 0) or 0)
            by_model = {
                str(name): int(count)
                for name, count in dict(usage.get("by_model", {})).items()
            }
            by_prompt = dict(usage.get("by_model_prompt", {}) or {})
            by_completion = dict(usage.get("by_model_completion", {}) or {})
            by_cost = dict(usage.get("by_model_cost_milli", {}) or {})
            unpriced_calls = int(usage.get("unpriced_calls", 0) or 0)
        elif diagnostics_store is not None:
            from plugins.bot_unified_runtime.runtime.pricing import (
                model_call_cost_milli,
                parse_model_prices,
            )

            prices = parse_model_prices(
                store.get_or(
                    "BOT_MODEL_PRICES",
                    getattr(config, "bot_model_prices", {}) or {},
                )
            )
            for record in diagnostics_store.list_recent(1000):
                created_at = getattr(record, "created_at", None)
                if created_at is not None and created_at.astimezone(timezone).date() != target_date:
                    continue
                values = (
                    int(getattr(record, "llm_usage_prompt_tokens", 0) or 0),
                    int(getattr(record, "llm_usage_completion_tokens", 0) or 0),
                    int(getattr(record, "llm_usage_total_tokens", 0) or 0),
                )
                if values[2] <= 0:
                    continue
                totals["prompt_tokens"] += values[0]
                totals["completion_tokens"] += values[1]
                totals["total_tokens"] += values[2]
                totals["calls"] += 1
                model_name = str(getattr(record, "llm_model", "unknown") or "unknown")
                by_model[model_name] = by_model.get(model_name, 0) + values[2]
                by_prompt[model_name] = by_prompt.get(model_name, 0) + values[0]
                by_completion[model_name] = (
                    by_completion.get(model_name, 0) + values[1]
                )
                cost_milli, priced = model_call_cost_milli(
                    model_name, values[0], values[1], prices
                )
                if priced:
                    totals["cost_milli"] += cost_milli
                    by_cost[model_name] = by_cost.get(model_name, 0) + cost_milli
                else:
                    unpriced_calls += 1
        from plugins.bot_unified_runtime.runtime.pricing import format_milli_yuan

        lines = [
            f"{target_date.isoformat()} 模型用量账单",
            (
                f"输入 {totals['prompt_tokens']:,}，输出 {totals['completion_tokens']:,}，"
                f"总计 {totals['total_tokens']:,} token，调用 {totals['calls']:,} 次"
            ),
            (
                f"缓存：命中 {totals['cache_read_tokens']:,}，创建 {totals['cache_write_tokens']:,}"
            ),
            f"账单：{format_milli_yuan(totals['cost_milli'])} 元",
            "── 按模型 ──",
        ]
        models_sorted = sorted(
            by_model,
            key=lambda name: (-int(by_cost.get(name, 0) or 0), -by_model[name], name),
        )
        if not models_sorted:
            lines.append("（当日还没有成功调用记录）")
        for name in models_sorted:
            cost_milli = int(by_cost.get(name, 0) or 0)
            lines.append(
                f"- {name}：入 {int(by_prompt.get(name, 0) or 0):,}"
                f" / 出 {int(by_completion.get(name, 0) or 0):,}"
                f" / 共 {by_model[name]:,}"
                f" / 费 {format_milli_yuan(cost_milli)} 元"
            )
        if unpriced_calls:
            lines.append(f"（{unpriced_calls} 次调用未配置价格，未计入账单；用 /bot model price 维护）")
        return "\n".join(lines)
    if action in {"add", "update", "remove", "priority"}:
        return _handle_model_registry_command(
            store,
            raw_env_registry,
            runtime_registry,
            action,
            parts[1:],
        )
    if action == "vision":
        return _handle_vision_command(store, config, parts[1:])
    return (
        "用法：/bot model set <id|auto> | list | add | update | "
        "priority | remove | effort | think | price | search | usage | "
        "vision <list|add|update|priority|remove|mode> | reset"
        "（/bot runtime model 同义）"
    )


def _parse_kv_pairs(parts: list[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            raise ValueError(f"参数格式应为 键=值：{part}")
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if not key:
            raise ValueError("参数键不能为空")
        entries[key] = value.strip()
    return entries


def _merge_registry_entries(
    raw_env_registry: dict[str, dict[str, Any]],
    runtime_registry: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {key: dict(value) for key, value in raw_env_registry.items()}
    merged.update({key: dict(value) for key, value in runtime_registry.items()})
    return merged


def _persist_priority_move(
    store: RuntimeSettingsStore,
    entries: dict[str, dict[str, Any]],
    model_id: str,
    priority: int,
    *,
    vision: bool = False,
) -> list[str]:
    from plugins.bot_unified_runtime.llm.model_router import reorder_priority_entries

    reordered = reorder_priority_entries(entries, model_id, priority)
    store.replace_registry_entries(reordered, vision=vision)
    return [
        entry_id
        for entry_id, _entry in sorted(
            reordered.items(), key=lambda item: item[1]["priority"]
        )
    ]


def _handle_model_registry_command(
    store: RuntimeSettingsStore,
    raw_env_registry: dict[str, dict[str, Any]],
    runtime_registry: dict[str, dict[str, Any]],
    action: str,
    parts: list[str],
) -> str:
    usage = (
        "用法：/bot model add <id> model=<模型名> base_url=<接口地址> "
        "key=<密钥或env:变量名> [group=<分组>] [tags=<思考强度档位，逗号分隔>] "
        "[effort=<off|low|medium|high|xhigh|max>] [alias=<简称>] [actual_model_id=<实际ID>] [priority=<槽位>]"
    )
    if action == "add":
        if not parts:
            return usage
        model_id = parts[0].strip()
        try:
            kv = _parse_kv_pairs(parts[1:])
        except ValueError as exc:
            return str(exc)
        model = kv.get("model", "")
        base_url = kv.get("base_url", "")
        if not model or not base_url:
            return "add 需要 model= 与 base_url= 两个必填参数。"
        entry: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            "api_key": kv.get("key", kv.get("api_key", "")),
        }
        if "group" in kv:
            entry["group"] = kv["group"]
        if "tags" in kv:
            entry["tags"] = [
                tag.strip() for tag in kv["tags"].split(",") if tag.strip()
            ]
        if "effort" in kv:
            from plugins.bot_unified_runtime.llm.model_router import normalize_effort

            normalized = normalize_effort(kv["effort"])
            if not normalized:
                return "effort 必须是 off/low/medium/high/xhigh/max（default=省略）。"
            entry["effort"] = normalized
        if "priority" in kv:
            try:
                entry["priority"] = int(kv["priority"])
            except ValueError:
                return "priority 必须是正整数（1 为首选）。"
        if "alias" in kv or "aliases" in kv:
            entry["aliases"] = [item.strip() for item in kv.get("aliases", kv.get("alias", "")).split(",") if item.strip()]
        if "actual_model_id" in kv:
            entry["model"] = kv["actual_model_id"]
        entries = _merge_registry_entries(raw_env_registry, runtime_registry)
        old_position = entries.get(model_id, {}).get("priority", len(entries) + 1)
        entries[model_id] = entry
        _persist_priority_move(store, entries, model_id, int(entry.get("priority", old_position)))
        key_state = "密钥已存储（不会回显）" if entry["api_key"] else "未配置密钥（路由会跳过该模型，直到补充 key=）"
        return (
            f"已新增自定义模型 {model_id}（{model} @ {base_url}，{key_state}）。"
            "立即生效，参与故障转移排序。启用它："
            f"/bot model set {model_id}；不启用则只在故障转移时使用。"
        )
    if action == "update":
        if len(parts) < 2:
            return "用法：/bot model update <id> model=... base_url=... key=... group=... tags=... effort=... priority=..."
        model_id = parts[0].strip()
        base_entry = runtime_registry.get(model_id) or raw_env_registry.get(model_id)
        if base_entry is None:
            return (
                f"不存在的模型 id：{model_id}。可用："
                + f"{','.join(sorted(set(runtime_registry) | set(raw_env_registry)))}"
            )
        try:
            kv = _parse_kv_pairs(parts[1:])
        except ValueError as exc:
            return str(exc)
        entry = dict(base_entry)
        key_map = {
            "model": "model",
            "actual_model_id": "model",
            "base_url": "base_url",
            "key": "api_key",
            "api_key": "api_key",
            "alias": "aliases",
            "aliases": "aliases",
            "effort": "effort",
            "group": "group",
        }
        for key, value in kv.items():
            if key == "tags":
                entry["tags"] = [
                    tag.strip() for tag in value.split(",") if tag.strip()
                ]
            elif key == "effort":
                from plugins.bot_unified_runtime.llm.model_router import (
                    normalize_effort,
                )

                normalized = normalize_effort(value)
                if not normalized:
                    if value.strip().lower() in {"default", "默认", "reset"}:
                        entry.pop("effort", None)
                        continue
                    return "effort 必须是 off/low/medium/high/xhigh/max/default。"
                entry["effort"] = normalized
            elif key == "priority":
                try:
                    entry["priority"] = int(value)
                except ValueError:
                    return "priority 必须是正整数（1 为首选）。"
            elif key in key_map:
                target_key = key_map[key]
                if target_key == "aliases":
                    entry[target_key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    entry[target_key] = value
            else:
                return f"不支持的字段：{key}。可用：model actual_model_id base_url key group tags effort alias aliases priority"
        entries = _merge_registry_entries(raw_env_registry, runtime_registry)
        old_position = entries.get(model_id, {}).get("priority", len(entries) + 1)
        entries[model_id] = entry
        _persist_priority_move(store, entries, model_id, int(entry.get("priority", old_position)))
        return (
            f"已更新模型 {model_id}（改动存为运行时覆盖，优先于 .env 同名条目）。"
            "密钥不会回显。"
        )
    if action == "priority":
        if len(parts) < 2:
            return "用法：/bot model priority <id> <数字>"
        model_id = parts[0].strip()
        entries = _merge_registry_entries(raw_env_registry, runtime_registry)
        try:
            priority = int(parts[1].strip())
            order = _persist_priority_move(store, entries, model_id, priority)
        except ValueError as exc:
            return str(exc) if "不存在的模型" in str(exc) else "priority 必须是正整数。"
        position = order.index(model_id) + 1
        return f"已把 {model_id} 移到优先级槽位 {position}；其他模型已自动顺移。当前顺序：{' → '.join(order)}。"
    if action == "remove":
        if not parts:
            return "用法：/bot model remove <id>"
        model_id = parts[0].strip()
        if store.remove_model_entry(model_id):
            return f"已删除自定义模型 {model_id}。"
        if model_id in raw_env_registry:
            return (
                f"{model_id} 来自 .env 的 BOT_MODEL_REGISTRY，无法用指令删除；"
                "可用 update 覆盖其参数，或在 .env 中修改后重启。"
            )
        return f"不存在的模型 id：{model_id}。"
    return usage


def _handle_vision_command(
    store: RuntimeSettingsStore,
    config: object,
    parts: list[str],
) -> str:
    """视觉识别模型管理：/bot model vision <list|add|update|priority|remove>。"""
    from plugins.bot_unified_runtime.sources.vision_describe import (
        _flatten_vision_entries,
    )

    runtime_registry = store.list_vision_registry()
    enabled = store.get_or(
        "BOT_VISION_ENABLED",
        bool(getattr(config, "bot_vision_enabled", False)),
    )
    usage = (
        "用法：/bot model vision list | add <id> model=<视觉模型> base_url=<接口> "
        "key=<密钥或env:变量> [alias=<简称>] [actual_model_id=<真实ID>] "
        "[effort=<档位>] [priority=<唯一槽位>] | update <id> <键=值...> | "
        "priority <id> <槽位> | remove <id> | mode <relay|direct>"
    )
    if not parts or parts[0].lower() == "list":
        lines = [
            "视觉识别开关："
            + ("开" if enabled else "关（/bot runtime set BOT_VISION_ENABLED true）")
        ]
        env_entries = _flatten_vision_entries(
            getattr(config, "bot_vision_model_registry", {})
        )
        if runtime_registry:
            lines.append(
                f"运行时自定义条目：{len(runtime_registry)} 个（优先于 .env 同名条目）"
            )
        if not env_entries and not runtime_registry:
            lines.append("注册表为空，图片识别不会运行。")
        else:
            from plugins.bot_unified_runtime.llm.model_router import (
                normalize_priority_entries,
            )

            merged = normalize_priority_entries({key: dict(value) for key, value in {**env_entries, **runtime_registry}.items()})
            lines.append("识别候选（唯一 priority 槽位，1 为首选；每次最多尝试 3 个）：")
            ordered = sorted(merged.items(), key=lambda kv: (int(kv[1]["priority"]), kv[0]))
            for display_position, (entry_id, display_entry) in enumerate(ordered, start=1):
                key_state = (
                    "已配密钥" if str(display_entry.get("api_key", "")).strip() else "缺密钥（跳过）"
                )
                source = "自定义" if entry_id in runtime_registry else "env"
                lines.append(
                    f"{display_position}. {entry_id} = {display_entry.get('model', '')}"
                    f" @ {display_entry.get('base_url', '')}"
                    f" priority={display_entry.get('priority', 100)}（{key_state}，{source}）"
                )
        lines.append(usage)
        return "\n".join(lines)
    sub = parts[0].lower()
    rest = parts[1:]
    if sub == "mode":
        if not rest:
            current = store.get_or(
                "BOT_VISION_MODE",
                str(getattr(config, "bot_vision_mode", "relay") or "relay"),
            )
            return f"当前视觉模式：{current}。用法：/bot model vision mode <relay|direct>"
        try:
            mode = SETTABLE_KEYS["BOT_VISION_MODE"](rest[0])
        except (KeyError, ValueError) as exc:
            return str(exc)
        store.set_override("BOT_VISION_MODE", mode)
        return f"视觉模式已设为 {mode}。"

    def _env_or_runtime_entry(target: str) -> dict[str, Any] | None:
        env_entries = _flatten_vision_entries(
            getattr(config, "bot_vision_model_registry", {})
        )
        return runtime_registry.get(target) or env_entries.get(target)

    if sub == "add":
        if not rest:
            return usage
        entry_id = rest[0].strip()
        try:
            kv = _parse_kv_pairs(rest[1:])
        except ValueError as exc:
            return str(exc)
        model = kv.get("model", "")
        base_url = kv.get("base_url", "")
        if not model or not base_url:
            return "add 需要 model= 与 base_url= 两个必填参数。"
        entry: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            "api_key": kv.get("key", kv.get("api_key", "")),
        }
        if "priority" in kv:
            try:
                entry["priority"] = int(kv["priority"])
            except ValueError:
                return "priority 必须是正整数（1 为首选）。"
        if "effort" in kv:
            entry["effort"] = kv["effort"].strip().lower()
        if "alias" in kv or "aliases" in kv:
            entry["aliases"] = [item.strip() for item in kv.get("aliases", kv.get("alias", "")).split(",") if item.strip()]
        if "actual_model_id" in kv:
            entry["model"] = kv["actual_model_id"]
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = _merge_registry_entries(env_entries, runtime_registry)
        old_position = entries.get(entry_id, {}).get("priority", len(entries) + 1)
        entries[entry_id] = entry
        _persist_priority_move(store, entries, entry_id, int(entry.get("priority", old_position)), vision=True)
        return (
            f"已新增视觉模型 {entry_id}（{model}）。立即生效，缺密钥的条目会被跳过；"
            "注册即参与识别轮询，无需 set 启用。"
        )
    if sub == "update":
        if len(rest) < 2:
            return "用法：/bot model vision update <id> model=... base_url=... key=... priority=..."
        entry_id = rest[0].strip()
        base_entry = _env_or_runtime_entry(entry_id)
        if base_entry is None:
            return f"不存在的视觉模型 id：{entry_id}。"
        try:
            kv = _parse_kv_pairs(rest[1:])
        except ValueError as exc:
            return str(exc)
        entry = dict(base_entry)
        key_map = {
            "model": "model",
            "actual_model_id": "model",
            "base_url": "base_url",
            "key": "api_key",
            "api_key": "api_key",
            "alias": "aliases",
            "aliases": "aliases",
            "effort": "effort",
        }
        for key, value in kv.items():
            if key in key_map:
                entry[key_map[key]] = value
            elif key == "priority":
                try:
                    entry["priority"] = int(value)
                except ValueError:
                    return "priority 必须是整数。"
            else:
                return f"不支持的字段：{key}。可用：model actual_model_id base_url key alias aliases effort priority"
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = _merge_registry_entries(env_entries, runtime_registry)
        old_position = entries.get(entry_id, {}).get("priority", len(entries) + 1)
        entries[entry_id] = entry
        _persist_priority_move(store, entries, entry_id, int(entry.get("priority", old_position)), vision=True)
        return f"已更新视觉模型 {entry_id}（立即生效；密钥不回显）。"
    if sub == "priority":
        if len(rest) < 2:
            return "用法：/bot model vision priority <id> <数字>"
        entry_id = rest[0].strip()
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = {key: dict(value) for key, value in {**env_entries, **runtime_registry}.items()}
        try:
            priority = int(rest[1].strip())
            order = _persist_priority_move(store, entries, entry_id, priority, vision=True)
        except ValueError as exc:
            return str(exc) if "不存在的模型" in str(exc) else "priority 必须是正整数。"
        position = order.index(entry_id) + 1
        return f"已把视觉模型 {entry_id} 移到优先级槽位 {position}；其他模型已自动顺移。当前顺序：{' → '.join(order)}。"
    if sub == "remove":
        if not rest:
            return "用法：/bot model vision remove <id>"
        entry_id = rest[0].strip()
        if store.remove_vision_entry(entry_id):
            return f"已删除视觉模型 {entry_id}。"
        env_entries = _flatten_vision_entries(
            getattr(config, "bot_vision_model_registry", {})
        )
        if entry_id in env_entries:
            return (
                f"{entry_id} 来自 .env 的 BOT_VISION_MODEL_REGISTRY，无法用指令删除；"
                "可用 update 覆盖其参数。"
            )
        return f"不存在的视觉模型 id：{entry_id}。"
    return usage


def _handle_persona_command(
    store: RuntimeSettingsStore,
    config: object,
    parts: list[str],
) -> str:
    from plugins.bot_unified_runtime.character.persona_set import build_alt_personas

    alt_personas = build_alt_personas(config)
    if not parts:
        return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"
    action = parts[0].lower()
    if action == "list":
        lines = [
            (
                f"主人格(A)：{getattr(config, 'bot_persona_profile_id', 'default')}"
                f"（{getattr(config, 'bot_persona_display_name', '')}）"
            )
        ]
        for spec_id, spec in alt_personas.items():
            lines.append(
                f"备用人格：{spec_id}（{spec.display_name}）"
                f" weight={spec.weight} emotions={','.join(spec.emotions) or '-'}"
            )
        override = store.get_persona_override()
        weights = store.get_persona_weights()
        lines.append(
            "当前覆盖："
            + (override if override else "自动（情绪触发 → 概率 → 主人格）")
        )
        if weights:
            lines.append(
                "概率覆盖："
                + ",".join(f"{k}={v}" for k, v in sorted(weights.items()))
            )
        return "\n".join(lines)
    if action == "switch":
        if len(parts) < 2:
            return "用法：/bot runtime persona switch <id|default>"
        target = parts[1].strip()
        if target != "default" and target not in alt_personas:
            return f"不存在的人格：{target}。可用：default,{','.join(alt_personas)}"
        store.set_persona_override("" if target == "default" else target)
        return (
            f"已强制切换人格：{target}（持续到下一次 switch default）。"
            if target != "default"
            else "已回到自动模式（情绪触发 → 概率 → 主人格）。"
        )
    if action in {"auto", "概率", "probability"}:
        if action == "auto" or len(parts) < 3:
            store.set_persona_override("")
            return "已回到自动模式。"
        spec_id = parts[1].strip()
        if spec_id not in alt_personas:
            return f"不存在的人格：{spec_id}。可用：{','.join(alt_personas)}"
        try:
            weight = float(parts[2])
        except ValueError:
            return "概率必须是 0-1 之间的数字。"
        store.set_persona_weight(spec_id, weight)
        return f"已设置 {spec_id} 的切换概率为 {max(0.0, min(1.0, weight))}。"
    return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"


def _handle_nickname_command(store: RuntimeSettingsStore, parts: list[str]) -> str:
    if not parts:
        return "用法：/bot runtime nickname add <昵称> | remove <昵称> | list"
    action = parts[0].lower()
    if action == "add":
        if len(parts) < 2:
            return "用法：/bot runtime nickname add <昵称>"
        added = store.add_nickname(parts[1])
        return (
            f"已添加昵称：{parts[1]}。当前昵称：{','.join(store.list_nicknames())}"
            if added
            else f"昵称 {parts[1]} 已存在。当前昵称：{','.join(store.list_nicknames())}"
        )
    if action == "remove":
        if len(parts) < 2:
            return "用法：/bot runtime nickname remove <昵称>"
        removed = store.remove_nickname(parts[1])
        return (
            f"已删除昵称：{parts[1]}。当前昵称：{','.join(store.list_nicknames())}"
            if removed
            else f"昵称 {parts[1]} 不存在。当前昵称：{','.join(store.list_nicknames())}"
        )
    if action == "list":
        nicknames = store.list_nicknames()
        return (
            f"当前昵称：{','.join(nicknames)}"
            if nicknames
            else "当前没有动态昵称（使用 .env 的 BOT_RUNTIME_PERSONA_NICKNAMES）。"
        )
    return "用法：/bot runtime nickname add <昵称> | remove <昵称> | list"


def build_runtime_admin_result(
    manager: InstanceSettingsManager,
    default_instance: str,
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    command_text: str,
    diagnostics_store: Any | None = None,
    usage_store: Any | None = None,
) -> CapabilityResult:
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    try:
        body = _handle_runtime_command(
            manager,
            default_instance,
            config,
            command_text,
            diagnostics_store=diagnostics_store,
            usage_store=usage_store,
        )
    except (ValueError, TypeError) as exc:
        return _error_result(request_id, str(exc))
    return _ok_result(request_id, body)


def build_alert_check_result(
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    probe: bool = False,
) -> CapabilityResult:
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    try:
        reports = check_credentials_and_report(config, probe=probe)
    except Exception as exc:  # noqa: BLE001 - 检查失败转成安全结果。
        return _error_result(request_id, f"凭据健康检查执行失败：{type(exc).__name__}")
    if not reports:
        return _ok_result(
            request_id,
            "未配置任何凭据引用，无需检查。",
            capability_id="bot.alert",
        )
    lines = []
    for report in reports:
        lines.append(
            f"{report.ref_id}：{report.state}"
            + ("（需要重新登录）" if report.needs_reauth else "")
            + f" - {report.detail}"
        )
    return _ok_result(
        request_id,
        "\n".join(lines),
        capability_id="bot.alert",
    )

