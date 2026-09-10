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
import threading
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

# 审计 P2#20：/bot model probe 的重入防护——非阻塞锁充当「进行中」标志位，
# 探针线程结束时释放；进行中收到的新 probe 命令只回执提示，不再叠加探针。
_MODEL_PROBE_LOCK = threading.Lock()


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


def _channel_health_suffix(model_id: str) -> str:
    """渠道健康标注：暂不可用的条目在 list 里直接可见。"""
    try:
        from plugins.bot_unified_runtime.llm.channel_health import (
            get_channel_health_store,
        )

        snapshot = get_channel_health_store().snapshot(model_id)
        if snapshot and snapshot.get("state") == "temporarily_unavailable":
            return " ⛔暂时不可用（已移出故障转移队列，自动重探中）"
        if snapshot and snapshot.get("latency_ms"):
            return f" ⚡{snapshot['latency_ms']}ms"
    except Exception:  # noqa: S110, BLE001 - 健康层缺失不影响 list。
        pass
    return ""


def _probe_specs(store: RuntimeSettingsStore, config: object) -> dict[str, Any]:
    """巡检目标集合 = .env 注册表 ∪ 运行时注册表（合并视图，修 D7）。

    此前手动 /bot model probe 只探 build_model_registry（仅 .env），
    管理员用 add 新增的运行时渠道永远没有健康数据。取数路径与
    /bot model list 一致：_merge_registry_entries 合并后逐条解析成
    specs（env 派生条目内容以 .env 实时值为准并带上运行时覆盖字段）。
    """
    from plugins.bot_unified_runtime.llm.model_router import _spec_from_entry

    raw_env_registry = {
        str(key): dict(item)
        for key, item in (getattr(config, "bot_model_registry", {}) or {}).items()
        if isinstance(item, dict)
    }
    merged = _merge_registry_entries(raw_env_registry, store.list_model_registry())
    specs: dict[str, Any] = {}
    for model_id, entry in merged.items():
        spec = _spec_from_entry(str(model_id), entry, config)
        if spec is not None:
            specs[str(model_id)] = spec
    return specs


def _channel_price_text(entry: dict[str, Any]) -> str:
    pin = entry.get("price_in")
    pout = entry.get("price_out")
    if pin is None and pout is None:
        return ""
    try:
        pin_f = float(pin) if pin is not None else None
        pout_f = float(pout) if pout is not None else None
    except (TypeError, ValueError):
        return ""
    if pin_f is None and pout_f is None:
        return ""
    return f" ¥{pin_f if pin_f is not None else '?'}/{pout_f if pout_f is not None else '?'}"


def _format_channel_health_report(
    report: list[dict[str, Any]],
    *,
    slow_ema_ms: int = 15000,
) -> str:
    """渠道健康巡检报告：运维可读排版（状态分组+延迟+排查指引）。

    v2 动态检测：评级改用平滑延迟（EWMA，抗单次抖动），同时展示
    「最近一次」与「平滑」两个值；ema 超过 slow_ema_ms 阈值（config
    bot_channel_slow_ema_ms，默认 15000）的渠道把「快/正常」改标「偏慢」。
    """
    if not report:
        return (
            "渠道健康巡检还没有数据。" + '\n'
            + "· 现在就测一次：/bot model probe（约 1-2 分钟，全部渠道各发一条最小请求，费用极低）" + '\n'
            + "· 之后每小时自动巡检一次，再回来看本命令即可。"
        )
    ok_rows = [r for r in report if r["state"] == "ok"]
    bad_rows = [r for r in report if r["state"] != "ok"]
    never = [r for r in ok_rows if not r.get("latency_ms") and not r.get("ema_ms")]
    probed = [r for r in ok_rows if r.get("latency_ms") or r.get("ema_ms")]
    lines = [
        (
            f"【渠道健康巡检报告】 共 {len(report)} 个渠道："
            f"{len(probed)} 已实测可用，{len(never)} 待下一轮探测，{len(bad_rows)} 暂不可用"
        ),
        "",
    ]
    if probed:
        lines.append("■ 实测可用（按平滑响应速度排序）")

        def _basis_ms(row: dict[str, Any]) -> int:
            ema = row.get("ema_ms")
            return int(ema) if ema else int(row["latency_ms"] or 0)

        for row in sorted(probed, key=_basis_ms):
            latency = int(row["latency_ms"] or 0)
            ema = row.get("ema_ms")
            basis = int(ema) if ema else latency
            grade = "快" if basis < 5000 else ("正常" if basis < 10000 else "偏慢")
            if ema and int(ema) >= slow_ema_ms:
                grade = "偏慢"  # 慢渠道阈值（v2）：平滑值超阈即标偏慢
            detail = f"响应 {latency}ms" if latency else "响应 -"
            if ema:
                detail += f" · 平滑 {int(ema)}ms"
            lines.append(f"  ✅ {row['model_id']}  {detail}（{grade}）")
    if never:
        lines.append("■ 尚未实测（下一轮巡检覆盖，不影响使用）")
        for row in never:
            lines.append(f"  ⏳ {row['model_id']}")
    if bad_rows:
        lines.append("■ 暂不可用（已移出故障转移队列，每 30 分钟重探，恢复自动回队；不自动删除）")
        for row in bad_rows:
            err = (row["last_error"] or "原因未知")[:90]
            lines.append(f"  ⛔ {row['model_id']}  连续失败 {row['consecutive_fails']} 次：{err}")
    lines.append("")
    lines.append(
        "说明：聊天按上述顺序自动故障转移，暂不可用渠道会被跳过；"
        "手动重测 /bot model probe，单渠道验证 /bot model routes <模型名>。"
    )
    lines.append(
        "说明：同名模型多渠道聚合时，实测响应快的渠道优先（延迟择优，"
        "开关 BOT_CHANNEL_HEALTH_LATENCY_FIRST，默认开）。"
    )
    if bad_rows:
        lines.append("")
        lines.append("【需要你处理的】")
        for row in bad_rows:
            err = row["last_error"] or ""
            if "no_api_key" in err:
                lines.append(f"  → {row['model_id']}: key 没取到，检查 .env 的 BOT_API_KEY_*")
            elif "401" in err or "Invalid token" in err:
                lines.append(f'  → {row["model_id"]}: key 已失效，去供应商后台换新 key')
            elif "额度不足" in err:
                lines.append(f'  → {row["model_id"]}: 余额用完，去充值')
            elif "no access" in err:
                lines.append(f'  → {row["model_id"]}: 该 key 无此模型权限，需开通或换模型')
            elif "404" in err and "not supported" in err:
                lines.append(f'  → {row["model_id"]}: 渠道已下架该模型，确认后可 /bot model remove')
            elif "429" in err or "rate limit" in err.lower():
                lines.append(f'  → {row["model_id"]}: 临时限流，等自动重探即可')
            elif "503" in err or "No available channel" in err:
                lines.append(f'  → {row["model_id"]}: 渠道上游没货，联系供应商或等待')
            elif "Timeout" in err:
                lines.append(f'  → {row["model_id"]}: 响应超时，渠道太慢可考虑移除')
    return '\n'.join(lines)


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
    action0 = parts[0].lower() if parts else ""
    if action0 == "health":
        from plugins.bot_unified_runtime.llm.channel_health import (
            get_channel_health_store,
            resolve_slow_ema_ms,
        )

        return _format_channel_health_report(
            get_channel_health_store().report(),
            slow_ema_ms=resolve_slow_ema_ms(config),
        )
    if action0 == "probe":
        from plugins.bot_unified_runtime.config import Config as _Cfg
        from plugins.bot_unified_runtime.llm.channel_health import probe_in_flight

        # 审计 P2#20 + D5：连发 N 条只允许起 N=1 个探针，且与后台定时
        # 巡检共享互斥（probe_in_flight）；任一在飞都直接回执，不叠加
        # 多路全量真实调用打爆共享 key。
        if not _MODEL_PROBE_LOCK.acquire(blocking=False):
            return (
                "渠道巡检正在进行中（全部渠道一次最小调用），无需重复发起；"
                "稍后用 /bot model health 查看。"
            )
        if probe_in_flight():
            _MODEL_PROBE_LOCK.release()
            return (
                "渠道巡检正在进行中（后台自动巡检或上一轮巡检尚未结束），"
                "无需重复发起；稍后用 /bot model health 查看。"
            )

        def _run_probe() -> None:
            try:
                from plugins.bot_unified_runtime.llm.channel_health import (
                    get_channel_health_store,
                    probe_all,
                )

                probe_all(_Cfg() if not isinstance(config, _Cfg) else config,
                          _probe_specs(store, config),
                          get_channel_health_store(),
                          mode="manual")
            except Exception:  # noqa: S110, BLE001 - 后台巡检失败静默。
                pass
            finally:
                _MODEL_PROBE_LOCK.release()

        threading.Thread(target=_run_probe, name="model-health-probe", daemon=True).start()
        return "渠道巡检已启动（全部渠道一次最小调用，费用极低）：稍后用 /bot model health 查看。"
    if action0 == "routes" and len(parts) > 1:
        from plugins.bot_unified_runtime.llm.channel_health import (
            get_channel_health_store,
        )
        from plugins.bot_unified_runtime.llm.model_router import (
            build_model_router,
        )

        model_name = parts[1]
        router = build_model_router(config)
        channels = router.channels_for_model(model_name)
        if not channels:
            return f"没有渠道提供「{model_name}」。"
        store_h = get_channel_health_store()
        lines = [f"「{model_name}」可用渠道（按实测响应速度 快→慢，未实测按价格/优先级排后）："]
        for index, channel_id in enumerate(channels, start=1):
            spec = router._spec_for(channel_id)
            price = ""
            if spec is not None and (spec.price_in is not None or spec.price_out is not None):
                pin = spec.price_in if spec.price_in is not None else "?"
                pout = spec.price_out if spec.price_out is not None else "?"
                price = f" ¥{pin}/{pout}"
            snap = store_h.snapshot(channel_id)
            latency = ""
            if snap and snap.get("state") == "temporarily_unavailable":
                state = "⛔暂不可用"
            elif snap and snap.get("latency_ms"):
                state = "✅"
                latency = f" {snap['latency_ms']}ms"
            else:
                # 未实测渠道不再伪装成 ✅ 健康；实际排序时垫底。
                state = "⏳未实测"
            lines.append(f"{index}. {channel_id} @ {spec.base_url if spec else '?'}{price} {state}{latency}")
        lines.append("指定方式：/bot model set " + channels[0] + "；或 /bot model set " + model_name + "（自动选渠道）")
        return "\n".join(lines)
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
        # 审计 P1#1：env 派生条目展示时以 .env 实时内容为准（仅 priority/
        # 覆盖字段取运行时副本），与路由合并语义一致。
        effective_runtime = _merge_registry_entries(raw_env_registry, runtime_registry)
        for model_id, entry in runtime_registry.items():
            shown = dict(effective_runtime.get(model_id, entry))
            merged[model_id] = {
                "model": str(shown.get("model", "")),
                "base_url": str(shown.get("base_url", "")),
                "tags": shown.get("tags") or [],
                "priority": shown.get("priority", 100),
                "effort": str(shown.get("effort", "") or ""),
                "source": "env" if shown.get("source") == _ENV_DERIVED_SOURCE else "runtime",
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
            # 按模型族分区展示：同族连续，换族时插分隔行，避免 34 条平铺刷屏。
            def _family(entry: dict[str, Any]) -> str:
                model = str(entry.get("model", "")).lower()
                if "deepseek" in model:
                    return "DeepSeek 系"
                if "glm" in model:
                    return "GLM 系"
                if "gemini" in model:
                    return "Gemini 系"
                if "grok" in model:
                    return "Grok 系"
                if "gpt" in model or "astra" in model or "luna" in model or "sol" in model or "terra" in model:
                    return "GPT 系"
                if "kimi" in model:
                    return "Kimi"
                if "minimax" in model:
                    return "MiniMax"
                return "其他"

            _FAMILY_ORDER = {
                "Gemini 系": 0, "GPT 系": 1, "Grok 系": 2,
                "DeepSeek 系": 3, "GLM 系": 4, "Kimi": 5, "MiniMax": 6, "其他": 7,
            }

            def _family_order(entry: dict[str, Any]) -> int:
                return _FAMILY_ORDER.get(_family(entry), 7)

            # 族聚合重排（行首编号仍是全局故障转移顺序，仅展示分组）
            ordered.sort(key=lambda kv: (_family_order(kv[1]), int(kv[1]["priority"])))
            prev_family = ""
            for order, (model_id, entry) in enumerate(ordered, start=1):
                family = _family(entry)
                if family != prev_family:
                    if prev_family:
                        lines.append("")
                    lines.append(f"──── {family} ────")
                    prev_family = family
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
                health_suffix = _channel_health_suffix(str(model_id))
                price_text = _channel_price_text(entry)
                lines.append(
                    f"{order}. {model_id} = {entry['model']} @ {entry['base_url']}"
                    f" [{tag_text}] effort={effort_text or 'off'}{effort_suffix}"
                    f" priority={entry['priority']}{price_text}"
                    + ("（自定义）" if entry["source"] == "runtime" else "")
                    + health_suffix
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
        merged_view = _merge_registry_entries(raw_env_registry, runtime_registry)
        base_entry = merged_view.get(model_id)
        if base_entry is None:
            return f"不存在的模型 id：{model_id}。"
        entry = dict(base_entry)
        if value in {"default", "默认", "reset"}:
            entry.pop("effort", None)
            store.set_model_entry(
                model_id,
                _marked_for_store(model_id, entry, raw_env_registry, runtime_registry, {"effort"}),
            )
            return (
                f"已清除 {model_id} 的思考强度覆盖，回到家族默认"
                f"（{_family_default_effort(str(entry.get('model', ''))) or '不发送'}）。"
            )
        from plugins.bot_unified_runtime.llm.model_router import normalize_effort

        normalized = normalize_effort(value)
        if not normalized:
            return "effort 必须是 off/low/medium/high/xhigh/max/default。"
        entry["effort"] = normalized
        store.set_model_entry(
            model_id,
            _marked_for_store(model_id, entry, raw_env_registry, runtime_registry, {"effort"}),
        )
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
            # 审计 P2#21：list_recent(1000) 截断会少算账单；翻倍分页取到
            # 尽头（存储自身有上限时 len(batch) < page 自然终止）。
            records: list[Any] = []
            page = 1000
            while True:
                batch = list(diagnostics_store.list_recent(page))
                records = batch
                if len(batch) < page or page >= 1_000_000:
                    break
                page *= 2
            for record in records:
                created_at = getattr(record, "created_at", None)
                if created_at is not None:
                    # 审计 P2#21：naive created_at 不能按进程本地时区解释；
                    # 挂上 bot 时区再比较，跨时区部署不再错档。
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone)
                    if created_at.astimezone(timezone).date() != target_date:
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
        "health | probe | routes <模型名> | "
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


_ENV_DERIVED_SOURCE = "env"


def _merge_registry_entries(
    raw_env_registry: dict[str, dict[str, Any]],
    runtime_registry: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """合并 .env 注册表与运行时条目（审计 P1#1 的合并语义 + B-14 迁移）。

    - 凡 .env 仍存在同名条目的运行时副本：内容以当前 .env 实时值为准，
      仅 ``priority``（管理员重排序的结果）与 ``override_fields`` 列出的
      字段（管理员明确改过的字段）采用运行时副本。无 ``source`` 标记的
      旧快照（Task4 之前的烘焙副本）按同一语义自动迁移，不再整体遮蔽
      .env 后续修改。
    - .env 已删除的条目：镜像条目（``source == "env"``）直接失效，不再被
      旧运行时副本遮蔽；无标记条目按纯运行时条目原样保留。
    """
    merged = {key: dict(value) for key, value in raw_env_registry.items()}
    for key, entry in runtime_registry.items():
        entry = dict(entry)
        env_entry = raw_env_registry.get(key)
        if env_entry is None:
            if entry.get("source") == _ENV_DERIVED_SOURCE:
                continue
            merged[key] = entry
            continue
        effective = dict(env_entry)
        for field in entry.get("override_fields") or []:
            if field == "priority" or field not in entry:
                continue
            effective[field] = entry[field]
        effective["priority"] = entry.get(
            "priority", effective.get("priority", 100)
        )
        merged[key] = effective
    return merged


def _env_derived_persist_entry(
    entry: dict[str, Any], override_fields: set[str] | None
) -> dict[str, Any]:
    """把 env 来源条目包装成持久化副本（审计 P1#1 硬约束）。

    - ``source: "env"`` 标记：读取侧据此用 .env 实时内容重建条目；
    - ``override_fields`` 只记录管理员明确改过的内容字段（priority 天然
      归管理员所有，不列入）；
    - api_key 保留 .env 原文（``env:变量名`` 引用原样落盘），解析出的
      明文密钥永不进运行时 store。
    """
    marked = dict(entry)
    content_overrides = sorted(
        {field for field in (override_fields or set()) if field != "priority"}
    )
    if content_overrides:
        marked["override_fields"] = content_overrides
    else:
        marked.pop("override_fields", None)
    marked["source"] = _ENV_DERIVED_SOURCE
    return marked


def _marked_for_store(
    model_id: str,
    entry: dict[str, Any],
    raw_env_registry: dict[str, dict[str, Any]],
    runtime_registry: dict[str, dict[str, Any]],
    extra_overrides: set[str] | None = None,
) -> dict[str, Any]:
    """按条目来源决定持久化形态：env 来源打标记，纯运行时条目原样。"""
    if model_id not in raw_env_registry:
        return dict(entry)
    previous = set(
        runtime_registry.get(model_id, {}).get("override_fields") or []
    )
    return _env_derived_persist_entry(entry, previous | set(extra_overrides or ()))


def _supplied_canonical_fields(
    kv: dict[str, str], key_map: dict[str, str] | None = None
) -> set[str]:
    """管理员在命令里明确给出的字段（映射成条目字段名；priority 单独处理）。"""
    mapping = key_map or {}
    fields = {mapping.get(key, key) for key in kv}
    fields.discard("priority")
    return fields


def _persist_priority_move(
    store: RuntimeSettingsStore,
    entries: dict[str, dict[str, Any]],
    model_id: str,
    priority: int,
    *,
    vision: bool = False,
    env_registry: dict[str, dict[str, Any]] | None = None,
    authored_fields: dict[str, set[str]] | None = None,
) -> list[str]:
    """重排序并持久化（审计 P1#1）。

    此前这里把合并后的注册表整体写入运行时持久层，.env 来源条目（含
    解析后的密钥与内容快照）被永久烘焙，.env 后续改动全部被旧副本遮蔽。
    现在 env 来源条目一律打 ``source: "env"`` 标记：内容字段读取时以
    .env 实时值为准，持久副本只承载管理员拥有的 priority（及
    ``authored_fields`` 中明确改过的字段）；纯运行时条目原样保留。
    """
    from plugins.bot_unified_runtime.llm.model_router import reorder_priority_entries

    env_registry = env_registry or {}
    reordered = reorder_priority_entries(entries, model_id, priority)
    persistable: dict[str, dict[str, Any]] = {}
    for entry_id, entry in reordered.items():
        if entry_id in env_registry:
            persistable[entry_id] = _env_derived_persist_entry(
                entry, (authored_fields or {}).get(entry_id)
            )
        else:
            persistable[entry_id] = dict(entry)
    store.replace_registry_entries(persistable, vision=vision)
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
        if model_id in raw_env_registry:
            # 审计 P1#1：对 .env 已有条目 add，未明确给出的字段以 .env 为准。
            entry = {**dict(raw_env_registry[model_id]), **entry}
        entries[model_id] = entry
        _persist_priority_move(
            store,
            entries,
            model_id,
            int(entry.get("priority", old_position)),
            env_registry=raw_env_registry,
            authored_fields=(
                {
                    model_id: _supplied_canonical_fields(
                        kv,
                        {
                            "key": "api_key",
                            "api_key": "api_key",
                            "actual_model_id": "model",
                            "alias": "aliases",
                            "aliases": "aliases",
                        },
                    )
                }
                if model_id in raw_env_registry
                else None
            ),
        )
        # 审计 P3#24：actual_model_id 静默覆盖 model 时，回执回显实际生效值。
        actual_model = str(entry.get("model", "") or model)
        key_state = "密钥已存储（不会回显）" if entry["api_key"] else "未配置密钥（路由会跳过该模型，直到补充 key=）"
        return (
            f"已新增自定义模型 {model_id}（{actual_model} @ {base_url}，{key_state}）。"
            "立即生效，参与故障转移排序。启用它："
            f"/bot model set {model_id}；不启用则只在故障转移时使用。"
        )
    if action == "update":
        if len(parts) < 2:
            return "用法：/bot model update <id> model=... base_url=... key=... group=... tags=... effort=... priority=..."
        model_id = parts[0].strip()
        # 审计 P1#1：基准取合并视图——env 派生副本不再让 .env 改动被旧快照遮蔽。
        entries = _merge_registry_entries(raw_env_registry, runtime_registry)
        base_entry = entries.get(model_id)
        if base_entry is None:
            return (
                "不存在的模型 id："
                f"{model_id}。可用：{','.join(sorted(set(runtime_registry) | set(raw_env_registry)))}"
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
        old_position = entries.get(model_id, {}).get("priority", len(entries) + 1)
        entries[model_id] = entry
        _persist_priority_move(
            store,
            entries,
            model_id,
            int(entry.get("priority", old_position)),
            env_registry=raw_env_registry,
            authored_fields=(
                {
                    model_id: (
                        set(
                            runtime_registry.get(model_id, {}).get(
                                "override_fields"
                            )
                            or []
                        )
                        | _supplied_canonical_fields(kv, key_map)
                    )
                }
                if model_id in raw_env_registry
                else None
            ),
        )
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
            order = _persist_priority_move(
                store, entries, model_id, priority, env_registry=raw_env_registry
            )
        except ValueError as exc:
            return str(exc) if "不存在的模型" in str(exc) else "priority 必须是正整数。"
        position = order.index(model_id) + 1
        return f"已把 {model_id} 移到优先级槽位 {position}；其他模型已自动顺移。当前顺序：{' → '.join(order)}。"
    if action == "remove":
        if not parts:
            return "用法：/bot model remove <id>"
        model_id = parts[0].strip()
        if store.remove_model_entry(model_id):
            if runtime_registry.get(model_id, {}).get("source") == _ENV_DERIVED_SOURCE:
                return f"已清除 {model_id} 的运行时覆盖，该模型回到 .env 注册表配置。"
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

            merged = normalize_priority_entries(
                _merge_registry_entries(env_entries, runtime_registry)
            )
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
            # 审计 P3#24：vision add 的 effort 也要过 normalize_effort 校验。
            from plugins.bot_unified_runtime.llm.model_router import normalize_effort

            normalized = normalize_effort(kv["effort"])
            if not normalized:
                return "effort 必须是 off/low/medium/high/xhigh/max（default=省略）。"
            entry["effort"] = normalized
        if "alias" in kv or "aliases" in kv:
            entry["aliases"] = [item.strip() for item in kv.get("aliases", kv.get("alias", "")).split(",") if item.strip()]
        if "actual_model_id" in kv:
            entry["model"] = kv["actual_model_id"]
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = _merge_registry_entries(env_entries, runtime_registry)
        old_position = entries.get(entry_id, {}).get("priority", len(entries) + 1)
        if entry_id in env_entries:
            # 审计 P1#1：对 .env 已有条目 add，未明确给出的字段以 .env 为准。
            entry = {**dict(env_entries[entry_id]), **entry}
        entries[entry_id] = entry
        _persist_priority_move(
            store,
            entries,
            entry_id,
            int(entry.get("priority", old_position)),
            vision=True,
            env_registry=env_entries,
            authored_fields=(
                {
                    entry_id: _supplied_canonical_fields(
                        kv,
                        {
                            "key": "api_key",
                            "api_key": "api_key",
                            "actual_model_id": "model",
                            "alias": "aliases",
                            "aliases": "aliases",
                        },
                    )
                }
                if entry_id in env_entries
                else None
            ),
        )
        # 审计 P3#24：actual_model_id 静默覆盖 model 时，回执回显实际生效值。
        actual_model = str(entry.get("model", "") or model)
        return (
            f"已新增视觉模型 {entry_id}（{actual_model}）。立即生效，缺密钥的条目会被跳过；"
            "注册即参与识别轮询，无需 set 启用。"
        )
    if sub == "update":
        if len(rest) < 2:
            return "用法：/bot model vision update <id> model=... base_url=... key=... priority=..."
        entry_id = rest[0].strip()
        # 审计 P1#1：基准取合并视图——env 派生副本不再让 .env 改动被旧快照遮蔽。
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = _merge_registry_entries(env_entries, runtime_registry)
        base_entry = entries.get(entry_id)
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
        old_position = entries.get(entry_id, {}).get("priority", len(entries) + 1)
        entries[entry_id] = entry
        _persist_priority_move(
            store,
            entries,
            entry_id,
            int(entry.get("priority", old_position)),
            vision=True,
            env_registry=env_entries,
            authored_fields=(
                {
                    entry_id: (
                        set(
                            runtime_registry.get(entry_id, {}).get(
                                "override_fields"
                            )
                            or []
                        )
                        | _supplied_canonical_fields(kv, key_map)
                    )
                }
                if entry_id in env_entries
                else None
            ),
        )
        return f"已更新视觉模型 {entry_id}（立即生效；密钥不回显）。"
    if sub == "priority":
        if len(rest) < 2:
            return "用法：/bot model vision priority <id> <数字>"
        entry_id = rest[0].strip()
        env_entries = _flatten_vision_entries(getattr(config, "bot_vision_model_registry", {}))
        entries = _merge_registry_entries(env_entries, runtime_registry)
        try:
            priority = int(rest[1].strip())
            order = _persist_priority_move(
                store, entries, entry_id, priority, vision=True, env_registry=env_entries
            )
        except ValueError as exc:
            return str(exc) if "不存在的模型" in str(exc) else "priority 必须是正整数。"
        position = order.index(entry_id) + 1
        return f"已把视觉模型 {entry_id} 移到优先级槽位 {position}；其他模型已自动顺移。当前顺序：{' → '.join(order)}。"
    if sub == "remove":
        if not rest:
            return "用法：/bot model vision remove <id>"
        entry_id = rest[0].strip()
        if store.remove_vision_entry(entry_id):
            if runtime_registry.get(entry_id, {}).get("source") == _ENV_DERIVED_SOURCE:
                return f"已清除 {entry_id} 的运行时覆盖，该模型回到 .env 注册表配置。"
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


def build_quirk_admin_result(
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    command_text: str,
) -> CapabilityResult:
    """/bot quirk list|approve|retire|add —— L4 人格演化区审核（管理员专用）。

    审核制红线：propose 来源（反思回路等）只进 pending_review，绝不直接
    影响 prompt；仅 approve 后的 active 项由 providers 闭包渲染进上下文。
    """
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    from plugins.bot_unified_runtime.character.providers import build_runtime_data_path
    from plugins.bot_unified_runtime.character.quirks import QuirkStore

    parts = command_text.split()
    sub = parts[0].lower() if parts else "list"
    if not getattr(config, "bot_quirks_enabled", True):
        return _ok_result(request_id, "人格 quirk 演化区未启用（BOT_QUIRKS_ENABLED=false）。")
    db_path = build_runtime_data_path(
        config,
        str(getattr(config, "bot_quirks_db_path", "data/persona_quirks.sqlite3")),
    )
    store = QuirkStore(db_path)
    if sub == "list":
        status_filter = parts[1].lower() if len(parts) > 1 else None
        if status_filter not in (None, "pending", "active", "retired"):
            return _error_result(request_id, "用法：/bot quirk list [pending|active|retired]")
        normalized = "pending_review" if status_filter == "pending" else status_filter
        quirks = store.list(status=normalized, limit=20)
        if not quirks:
            return _ok_result(request_id, "（对应状态下暂无 quirk。）")
        label = {"pending_review": "待审", "active": "生效", "retired": "退役"}
        lines = [
            f"- {q.quirk_id[:8]} [{label.get(q.status, q.status)}] {q.quirk_text}（来源 {q.source or '未知'}）"
            for q in quirks
        ]
        return _ok_result(request_id, "\n".join(lines), capability_id="bot.quirk")
    if sub in ("approve", "retire"):
        if len(parts) < 2:
            return _error_result(
                request_id, f"用法：/bot quirk {sub} <id前缀>（先 /bot quirk list 查 id）"
            )
        prefix = parts[1].strip().lower()
        candidates = [q for q in store.list(limit=100) if q.quirk_id.startswith(prefix)]
        if len(candidates) != 1:
            return _error_result(
                request_id, f"id 前缀 {prefix} 命中 {len(candidates)} 条，需要唯一。"
            )
        target = candidates[0]
        changed = (
            store.approve(target.quirk_id) if sub == "approve" else store.retire(target.quirk_id)
        )
        if not changed:
            return _error_result(request_id, "状态流转不合法（approve 仅对待审项生效）。")
        verb = "通过" if sub == "approve" else "退役"
        return _ok_result(request_id, f"已{verb}：{target.quirk_text}", capability_id="bot.quirk")
    if sub == "add":
        text = command_text.removeprefix("add").strip()
        if not text:
            return _error_result(request_id, "用法：/bot quirk add <习惯描述>")
        quirk = store.add_direct(text, source="admin")
        return _ok_result(
            request_id, f"已直接生效：{quirk.quirk_text}", capability_id="bot.quirk"
        )
    return _error_result(
        request_id,
        "用法：/bot quirk list [pending|active|retired] | approve <id前缀> | retire <id前缀> | add <text>",
    )


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

