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

from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    SETTABLE_KEYS,
    InstanceSettingsManager,
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.domains.core.channel_capability_tags import (
    preserve_capability_tags,
)
from plugins.bot_unified_runtime.domains.core.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.credentials.credential_health import (
    check_credentials_and_report,
)

# 审计 P2#20：/bot model probe 的重入防护——非阻塞锁充当「进行中」标志位，
# 探针线程结束时释放；进行中收到的新 probe 命令只回执提示，不再叠加探针。
_MODEL_PROBE_LOCK = threading.Lock()

# F-A 单一真身：persona 命令面**会改运行时状态**的动作形全集。super_admin 门与处理腿
# 同读这一枚（禁第二本账）——门曾只枚举英文三形、腿实收 ``auto`` 与中文 ``概率``，
# 普通 admin 因此能清切换态、改切换权重（取证见
# .superpowers/sdd/2026-09-27-fullload/patches/S-RECON-PADMIN-20260929.md §③）。
# ``list`` 是只读形，绝不混进来（那会把 admin 的查看权一并锁死）。
_PERSONA_WRITE_ACTIONS: frozenset[str] = frozenset({"switch", "auto", "reset", "probability", "概率"})

# 席 X1b（P4.1 备份腿）：backup 命令面**会动盘**的动作形全集——起备份、按名删旧副本、
# 把副本暂存出去。读面（status/list/verify/prune-plan/restore-plan）留在 admin，
# 因为「有没有备份」这件事必须让普通管理员一句话就能问出来。
# 与门同读这一枚（禁第二本账，同 _PERSONA_WRITE_ACTIONS 的教训）。
_BACKUP_WRITE_ACTIONS: frozenset[str] = frozenset({"run", "prune", "restore-stage"})


def _admin_only_result(request_id: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.runtime",
        kind="text",
        title="权限不足",
        body="这个命令只允许管理员用。",
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
    actor_id: str = "runtime-admin",
    actor_roles: list[str] | None = None,
    request_id: str = "",
    session_key: str = "",
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
    if store.config_backend is not None and action in {"set", "get", "list", "reset"}:
        from plugins.bot_unified_runtime.control_plane.config_service import (
            ConfigControlService,
        )

        service = ConfigControlService(config, store.config_backend, runtime_settings=store)
        if action == "list":
            return instance_label + "\n".join(f"{item['key']} = {item['value']}" for item in service.list())
        if action == "get" and remaining:
            row = service.get(remaining[0])
            return f"{instance_label}{row['key']} = {row['value']}（版本 {row['version']}）"
        # 第 18 项收编（S-THROAT，2026-09-26）：本分支只留**读面**（上面 list/get 与
        # 下面的回显取数）。写面一律落到咽喉 `store.set_override/reset_override`——
        # 它在门内转发同一个 `backend.set_override`（CAS/审计/变更监听逐字节同形），
        # 而 `ConfigControlService._write` 直连裸 SQL、一行不沾 `_throat_guard`；
        # 旧形态在这里直写 ⇒ `/bot runtime set` 改 R1/R2 键无声落库（§⑨-B 旁路）。
        if action == "set" and len(remaining) >= 2:
            store.set_override(
                remaining[0], " ".join(remaining[1:]),
                actor=actor_id, request_id=request_id, session_key=session_key,
            )
            changed = service.get(remaining[0])
            return f"{instance_label}已保存 {changed['key']} = {changed['value']}（版本 {changed['version']}）；动态消费者下次读取生效。"
        if action == "reset":
            store.reset_override(
                remaining[0] if remaining else None,
                actor=actor_id, request_id=request_id, session_key=session_key,
            )
            return f"{instance_label}已恢复默认覆盖（版本 {store.config_backend.snapshot().version}）。"
        return "用法：/bot runtime set <KEY> <VALUE> | get <KEY> | list | reset [KEY]"
    if action == "set":
        if len(remaining) < 2:
            return "用法：/bot runtime set <KEY> <VALUE> [--instance <名称>]"
        key, value = remaining[0], " ".join(remaining[1:])
        converted = store.set_override(key, value, actor=actor_id, session_key=session_key)
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
        count = store.reset_override(reset_key, actor=actor_id, session_key=session_key)
        return f"{instance_label}已清除 {count} 项运行时覆盖。"
    if action == "nickname":
        return f"{instance_label}{_handle_nickname_command(store, remaining)}"
    if action == "persona":
        return f"{instance_label}{_handle_persona_command(store, config, remaining)}"
    if action == "model":
        return f"{instance_label}{_handle_model_command(store, config, remaining, diagnostics_store=diagnostics_store, usage_store=usage_store, actor_id=actor_id, session_key=session_key)}"
    # 席 X1b 接线点（P4.1 备份腿的**唯一现役调用面**）：``/bot runtime backup …``。
    # 为什么接在这里而不是新建一条调度：本席禁改 ``__init__.py``（调度注册真身），
    # 而这枚 handler 已被 ``build_runtime_admin_result`` 之上的 ``/bot runtime`` 分支
    # 逐字调用（装配侧 ``plugins/bot_unified_runtime/__init__.py`` 的 runtime 分支），
    # 孤儿件按未完成记账（SEAT-RULES），所以只接真实存在的入口。
    if action == "backup":
        return _handle_backup_command(config, remaining)
    return (
        "用法：/bot runtime set <KEY> <VALUE> | get <KEY> | list | "
        "reset [KEY] | nickname add/remove/list <昵称> | persona list|switch|probability "
        "| model list|set|reset | backup status|list|verify|run|prune-plan|prune|restore-plan "
        "| instance list（均可加 --instance <名称> 定位实例）"
    )


def _handle_backup_command(config: object, parts: list[str]) -> str:
    """``/bot runtime backup …``：SQLite 在线备份腿的运维命令面（席 X1b）。

    动词表（读面 admin 可用，写面 ``run``/``prune``/``restore-stage`` 由
    ``_BACKUP_WRITE_ACTIONS`` 抬到 super_admin）：

    * ``status``：现算体检（库里名册、在册副本、过期/超上界/孤儿各一本账）。
    * ``list [库名]``：在册副本清单。
    * ``verify [库名|副本文件名]``：旁车 ↔ 副本对账（sha256/integrity/表数/行数）。
    * ``run [库名…]``：起一轮在线备份（无参数＝全量，点名＝只备这几枚）。
    * ``prune-plan``：只出保留清单，**不删**。
    * ``prune <副本名> …``：按名点名删（名字必须逐字命中清单，严禁递归删）。
    * ``restore-plan <旁车名>``：校验 + 给出人工还原步骤。
    * ``restore-stage <旁车名> [子目录名]``：把校验通过的副本暂存到落点外的 staging。

    覆盖生产库这条腿**故意不存在**（``db_backup._reject_production_target``），
    移回原位由人执行；命令面任何一次调用都不会改动 ``ChatBot_Runtime/data`` 里的库。
    """
    from plugins.bot_unified_runtime.domains.ops import db_backup

    action = parts[0].lower() if parts else ""
    args = parts[1:]
    try:
        if action == "status":
            return db_backup.format_reply(db_backup.status_report(config), title="数据库备份体检")
        if action == "list":
            return db_backup.format_reply(
                db_backup.list_backups(config, db=args[0] if args else ""), title="在册副本"
            )
        if action == "verify":
            keyword = args[0] if args else ""
            verdicts = db_backup.verify_backups(
                config, copy=keyword if keyword.endswith(".sqlite3") else "", db=keyword
            )
            return db_backup.format_reply(verdicts, title="副本校验")
        if action == "run":
            report = db_backup.backup_all(config, only=list(args) or None)
            return db_backup.format_reply(report.to_dict(), title="备份轮次")
        if action == "prune-plan":
            return db_backup.format_reply(db_backup.plan_retention(config), title="保留清单（未删）")
        if action == "prune":
            if not args:
                return "prune 需要逐枚点名副本名（先跑 prune-plan 拿清单），本次零删除。"
            return db_backup.format_reply(
                db_backup.apply_retention(config, list(args)), title="按名删旧副本"
            )
        if action == "restore-plan":
            if not args:
                return "用法：/bot runtime backup restore-plan <旁车名.manifest.json>"
            manifest = db_backup.manifest_in_root(config, args[0])
            return db_backup.format_reply(db_backup.plan_restore(manifest, config), title="还原前置校验")
        if action == "restore-stage":
            if not args:
                return "用法：/bot runtime backup restore-stage <旁车名> [暂存子目录名]"
            manifest = db_backup.manifest_in_root(config, args[0])
            staging = db_backup.staging_dir(config, args[1] if len(args) > 1 else "")
            return db_backup.format_reply(
                db_backup.restore_stage(manifest, config, staging), title="副本已暂存（未覆盖生产）"
            )
    except db_backup.BackupError as exc:
        return f"备份操作未完成：{exc}"
    except OSError as exc:
        # 只报异常族名，不把栈帧与盘上路径直发聊天（错误卡受众分级门同口径）。
        return f"备份操作未完成：{type(exc).__name__}"
    return (
        "用法：/bot runtime backup status | list [库名] | verify [库名|副本名] | run [库名…] "
        "| prune-plan | prune <副本名>… | restore-plan <旁车名> | restore-stage <旁车名> [子目录]"
    )


def _family_baseline_effort(model_name: str) -> str:
    """家族基线档（普通任务实际默认发送的 reasoning_effort）。

    展示口径对齐 model_router：请求按 条目 effort > 全局覆盖 > 家族基线
    发送；家族最高档（default_effort）只是复杂任务的升档上限，不再
    标注为「默认」。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        baseline_effort,
    )

    return baseline_effort(model_name)


def _active_priority_group(
    store: RuntimeSettingsStore,
    config: object,
) -> tuple[str, list[str]]:
    """当前命中的时段优先级分组 (name, order)；未配置/未命中返回 ("", [])。"""
    from datetime import datetime as _dt

    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
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
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
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
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        _spec_from_entry,
    )

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


def _usage_channel_stats(
    config: object,
    target_date: date,
) -> dict[str, dict[str, dict[str, int]]] | None:
    """账本开时读当日 (实际模型, 渠道) 聚合并折叠到家族键；关/失败 = None。

    数据源复用 llm/ledger.aggregate_channel_usage（只读 SQL，不重复造聚合），
    家族折叠口径与 usage_monitor._channel_stats_for 一致；输出直接喂
    build_model_rows(channel_stats=...) 的渠道子行（账本关返回 None，
    build_model_rows 行为与旧版完全一致）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
            aggregate_channel_usage,
            ledger_enabled,
            resolve_default_db_path,
        )

        if not ledger_enabled(config):
            return None
        raw = aggregate_channel_usage(
            resolve_default_db_path(),
            start_day=target_date.isoformat(),
            end_day=target_date.isoformat(),
        )
    except Exception:  # noqa: BLE001 - 渠道明细读不到只影响子行，不阻塞账单。
        return None
    if not raw:
        return None
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
        model_family_key,
    )

    stats: dict[str, dict[str, dict[str, int]]] = {}
    for (actual_model, channel_id), bucket in raw.items():
        family = model_family_key(actual_model) or actual_model
        channels = stats.setdefault(family, {})
        target = channels.setdefault(channel_id, {"calls": 0, "cost_milli": 0})
        target["calls"] += int((bucket or {}).get("calls", 0) or 0)
        target["cost_milli"] += int((bucket or {}).get("cost_milli", 0) or 0)
    return stats or None


# 口径注记文案（同一句话只有一个真身，回落两腿共用，别在分支里各写一遍）。
_LEDGER_UNREADABLE_NOTE = (
    "口径注记：账本这一轮没读到（库不可达或窗口参数不合），账单这一行仍按事件侧的毫厘记账。"
)
_LEDGER_EMPTY_WINDOW_NOTE = (
    "口径注记：账本当日窗口里没有行，账单这一行仍按事件侧的毫厘记账。"
)
# 账本家族列 → 该列在表头对应的计数（补齐行时一起补，屏幕才加得平）。
_LEDGER_FAMILY_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("by_model", "total_tokens"),
    ("by_model_prompt", "prompt_tokens"),
    ("by_model_completion", "completion_tokens"),
    ("by_model_cache_read", "cache_read_tokens"),
    ("by_model_cache_write", "cache_write_tokens"),
    ("by_model_calls", "calls"),
    ("by_model_unpriced", "unpriced_calls"),
)


def _brief_names(names: list[str], *, limit: int = 4) -> str:
    """名字列表短写（注记行要说清是哪几个家族，又不许把屏幕占满）。"""
    ordered = sorted(names)
    if len(ordered) <= limit:
        return "、".join(ordered)
    return "、".join(ordered[:limit]) + " 等"


def _usage_money_from_ledger(
    config: object,
    target_date: date,
    aggregate: dict[str, Any],
) -> str:
    """把账单的钱换成账本口径（与渠道子行同源），必要时给出「口径注记」行。

    原地改写 ``aggregate``：主行 ``cost_milli`` 与 ``by_model_cost_milli`` 换源到
    账本，账本独有的家族整列补齐；返回需要补的注记文案（不需注记＝空串）。

    为什么必须换源（SEAT-ATK-BILLING F-1）：事件侧的 ``cost_milli`` 是**逐行**
    整数毫厘，亚毫厘单价（实测一发 0.000219 元 = 0.219 毫厘）每行取整成 0，一天
    加下来主账单塌向 0.00，而渠道子行走账本微元聚合、如实报 0.22——同一屏两套钱，
    自己打自己脸。``aggregate_usage_totals`` 与 ``_usage_channel_stats`` 读同一张
    ``llm_call_records``、同一窗口，取整只在聚合末端做一次
    （台账 #54★「成本原语走微元、取整只在聚合」）。

    自洽构造：主行金额一律取 ``sum(by_model_cost_milli.values())``，也就是屏幕上
    按模型各行之和——账要能自己加得平（与 ``aggregate_usage_totals`` 自带的总计
    独立取整最多差每家族 1 毫厘＝0.001 元，低于本屏的分精度，换不来「加不平」）。

    与镜像面的分工（同一枚原语，两处消费腿）：定时报告面走
    ``usage_monitor._apply_ledger_main_row``，账本有行时整段聚合（含 token 列）
    都换成账本口径；命令面这里只换**钱**，token/次数仍取事件侧的完整记录，
    并且事件侧本已计价、账本当日没有行的家族不被丢掉——它被点名。两屏都遵守
    同一条铁律：回落与换源都不许静默。差异已写进报告，合并成一处真身归报告面。

    诚实边界（绝不静默换源）：
    - 账本关（缺省）⇒ 一个字节都不动，也绝不解析库路径。
    - 账本开但读不到 / 窗口无行 ⇒ 沿用事件毫厘**并注记口径**（两种成因分开说）。
    - 两侧覆盖的家族不重合 ⇒ 注记哪几行各按哪本的账，不做第二套算法。
    - 账本有行却没有价格 ⇒ 笔数写进注记，账单上的 0 不许静默地 0（屏幕上那句
      「N 次调用未计价」吃的是事件侧计数，账本侧的笔数由注记自己报）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
            aggregate_usage_totals,
            ledger_enabled,
            resolve_default_db_path,
        )
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
            model_family_key,
        )

        if not ledger_enabled(config):
            return ""
        day = target_date.isoformat()
        agg = aggregate_usage_totals(
            resolve_default_db_path(), start_day=day, end_day=day
        )

        def _family(name: object) -> str:
            text = str(name or "")
            return model_family_key(text) or text
    except Exception:  # noqa: BLE001 - 账本读不动只降级注记，绝不炸掉整张账单。
        return _LEDGER_UNREADABLE_NOTE

    if agg is None:
        return _LEDGER_UNREADABLE_NOTE
    ledger_cost = {
        str(name): int(milli or 0)
        for name, milli in dict(agg.get("by_model_cost_milli") or {}).items()
    }
    ledger_families = {_family(name) for name in ledger_cost}
    if not ledger_families and not int(agg.get("calls", 0) or 0):
        return _LEDGER_EMPTY_WINDOW_NOTE

    by_cost = aggregate["by_model_cost_milli"]
    # 账本覆盖到的家族：钱整段换成账本口径（同一家族只留账本那一笔，
    # 绝不与事件侧的毫厘相加——那是把两套钱拧成第三套）。
    for name in [key for key in by_cost if _family(key) in ledger_families]:
        by_cost.pop(name, None)
    key_by_family: dict[str, str] = {}
    for name in aggregate["by_model"]:
        key_by_family.setdefault(_family(name), str(name))
    ledger_only: list[str] = []
    for name, milli in ledger_cost.items():
        family = _family(name)
        key = key_by_family.get(family)
        if key is None:
            # 事件侧没有这一家、账本有行：整列取自账本，行与钱同进同出，
            # 不许只把钱记上却不出现这一行（那样屏幕上就加不平了）。
            key = str(name)
            key_by_family[family] = key
            ledger_only.append(key)
            for column, header in _LEDGER_FAMILY_COLUMNS:
                value = int(dict(agg.get(column) or {}).get(name, 0) or 0)
                aggregate[column][key] = int(aggregate[column].get(key, 0) or 0) + value
                if header is not None:
                    aggregate[header] = int(aggregate.get(header, 0) or 0) + value
        by_cost[key] = int(by_cost.get(key, 0) or 0) + milli
    aggregate["cost_milli"] = sum(int(milli or 0) for milli in by_cost.values())

    residual = [
        str(name)
        for name, milli in by_cost.items()
        if int(milli or 0) > 0 and _family(name) not in ledger_families
    ]
    # 账本里有行、却没有价格的那些次：账单按 0 记是真的，但 0 不许静默——
    # 落进注记里说明「有几笔没有价格」，免得屏幕上只剩一个像样的 0.00。
    ledger_unpriced = int(agg.get("unpriced_calls", 0) or 0)
    legs: list[str] = []
    if residual:
        legs.append(
            f"{len(residual)} 个家族（{_brief_names(residual)}）的钱仍按事件侧毫厘记账"
        )
    if ledger_only:
        legs.append(
            f"{len(ledger_only)} 个家族（{_brief_names(ledger_only)}）只有账本有行，整行取自账本"
        )
    if ledger_unpriced:
        legs.append(f"{ledger_unpriced} 次调用账本里没有价格，按 0 计入账单")
    if legs:
        return "口径注记：" + "；".join(legs) + "。"
    return ""


def _usage_ledger_health(config: object) -> str:
    """账本健康尾行：丢行 / 写失败 / 归因故障 / 归因让路，任一非零才出声。

    数据源 = ``peek_ledger_service()``（只读探测进程单例，绝不按需建库、绝不起
    写线程——为看健康而造出副作用是把告警面变成事故源）。队列满丢掉的账行
    以前只有一行不带身份的日志，管理员面上根本看不见（F-3）。计数全零 ⇒ 空串，
    不给健康期加噪声。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
            ledger_enabled,
            peek_ledger_service,
        )

        if not ledger_enabled(config):
            return ""
        service = peek_ledger_service()
        if service is None:
            return ""
        dropped = int(getattr(service, "dropped_count", 0) or 0)
        write_errors = int(getattr(service, "write_error_count", 0) or 0)
        attribution_errors = int(getattr(service, "attribution_error_count", 0) or 0)
        attribution_skipped = int(getattr(service, "attribution_skipped_count", 0) or 0)
    except Exception:  # noqa: BLE001 - 健康行读不到只少一行说明，不阻塞账单。
        return ""
    if not (dropped or write_errors or attribution_errors or attribution_skipped):
        return ""
    return (
        f"账本健康：丢行 {dropped}，写失败 {write_errors}，"
        f"归因故障 {attribution_errors}，归因让路 {attribution_skipped}"
    )


def _handle_model_command(
    store: RuntimeSettingsStore,
    config: object,
    parts: list[str],
    *,
    diagnostics_store: Any | None = None,
    usage_store: Any | None = None,
    actor_id: str = "runtime-admin",
    session_key: str = "",
) -> str:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        build_model_registry,
    )

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
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            get_channel_health_store,
            resolve_slow_ema_ms,
        )

        return _format_channel_health_report(
            get_channel_health_store().report(),
            slow_ema_ms=resolve_slow_ema_ms(config),
        )
    if action0 == "probe":
        from plugins.bot_unified_runtime.config import Config as _Cfg
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            probe_in_flight,
        )

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
                from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
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
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            get_channel_health_store,
        )
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
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
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
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
                effort_text = str(entry.get("effort", "") or "") or _family_baseline_effort(
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
            store.reset_override("BOT_CHAT_MODEL", actor=actor_id, session_key=session_key)
            return "已切换为自动选型（按时段分组/priority 顺序，失败自动转移；思考强度按档位体系）。"
        known_ids = set(registry) | set(runtime_registry)
        if known_ids and name in known_ids:
            store.set_override("BOT_CHAT_MODEL", name, actor=actor_id, session_key=session_key)
            label = runtime_registry.get(name, {}).get("model", "") or (
                registry[name].model if name in registry else ""
            )
            return f"已手动指定模型：{name}（{label}）。失败时自动转移其他模型。"
        if name in presets:
            model = presets[name]
            store.set_override("BOT_CHAT_MODEL", name, actor=actor_id, session_key=session_key)
            return f"已手动指定模型：{name}（{model}）。"
        # 允许直接给完整模型名（兼容旧用法；无注册表时走主 provider）。
        store.set_override("BOT_CHAT_MODEL", name, actor=actor_id, session_key=session_key)
        return f"已手动指定模型：{name}。"
    if action == "reset":
        store.reset_override("BOT_CHAT_MODEL", actor=actor_id, session_key=session_key)
        return f"已恢复自动选型（默认兜底 {default_model}）。"
    if action in {"think", "思考", "reasoning"}:
        if len(parts) < 2:
            return "用法：/bot model think <off|low|medium|high|xhigh|max>"
        try:
            effort = SETTABLE_KEYS["BOT_CHAT_REASONING_EFFORT"](parts[1])
        except (KeyError, ValueError) as exc:
            return str(exc)
        store.set_override("BOT_CHAT_REASONING_EFFORT", effort, actor=actor_id, session_key=session_key)
        if effort == "off":
            return "reasoning_effort 已设为 off：不发送思考强度字段。"
        if not effort:
            return "reasoning_effort 已清空：各模型回到家族基线档（复杂任务自动升到家族最高档）。"
        return f"reasoning_effort（推理思考强度）已设为：{effort}。"
    if action in {"effort", "强度", "思考强度"}:
        if len(parts) < 3:
            return (
                "用法：/bot model effort <id> <off|low|medium|high|xhigh|max|default>；"
                "default=清除覆盖回到家族基线档（普通任务默认，复杂任务自动升档）"
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
                f"（{_family_baseline_effort(str(entry.get('model', ''))) or '不发送'}）。"
            )
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
            normalize_effort,
        )

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
                "用法：/bot model price <模型名> input=<元/1M输入> output=<元/1M输出> "
                "[cache_read=<元/1M缓存读>] [cache_creation=<元/1M缓存创建>] "
                "[per_call=<元/请求>]；"
                "例：/bot model price deepseek-v4-pro input=4 output=16 cache_read=0.10"
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
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
            parse_model_prices,
        )

        prices = parse_model_prices(raw_prices)
        if not kv:
            # 不带价格参数 = 清除该模型价格，回到未计价。
            prices.pop(model_name, None)
            store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False), actor=actor_id, session_key=session_key)
            return f"已清除 {model_name} 的价格（该模型回到未计价）。"
        entry_prices = dict(prices.get(model_name, {}))
        # 2026-09-18：缓存读/缓存创建/按次计费三键可写——此前只收 input/output，
        # 缓存价永远配不进去，账单只能按全输入价高估。
        for key, unit in (
            ("input", "元/每百万 token"),
            ("output", "元/每百万 token"),
            ("cache_read", "元/每百万缓存读 token"),
            ("cache_creation", "元/每百万缓存创建 token"),
            ("per_call", "元/请求"),
        ):
            if key in kv:
                try:
                    number = float(kv[key])
                except ValueError:
                    return f"{key} 必须是数字（{unit}）。"
                if number < 0:
                    return f"{key} 不能为负数。"
                entry_prices[key] = number
        if not entry_prices:
            prices.pop(model_name, None)
            store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False), actor=actor_id, session_key=session_key)
            return f"已清除 {model_name} 的价格（该模型回到未计价）。"
        prices[model_name] = entry_prices
        store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False), actor=actor_id, session_key=session_key)
        segments = [
            f"{label} {entry_prices[key]:g} {unit}"
            for key, label, unit in (
                ("input", "输入", "元/1M"),
                ("output", "输出", "元/1M"),
                ("cache_read", "缓存读", "元/1M"),
                ("cache_creation", "缓存创建", "元/1M"),
                ("per_call", "按次", "元/请求"),
            )
            if key in entry_prices
        ]
        return (
            f"已设置 {model_name} 价格：" + "，".join(segments) + "。之后的调用按新价格记账。"
        )
    if action in {"search", "搜索", "联网"}:
        if len(parts) < 2:
            return "用法：/bot model search <on|off>"
        try:
            enabled = SETTABLE_KEYS["BOT_WEB_SEARCH_ENABLED"](parts[1])
        except (KeyError, ValueError) as exc:
            return str(exc)
        store.set_override("BOT_WEB_SEARCH_ENABLED", parts[1], actor=actor_id, session_key=session_key)
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
        by_cache_read: dict[str, int] = {}
        by_cache_write: dict[str, int] = {}
        by_cost: dict[str, int] = {}
        by_calls: dict[str, int] = {}
        by_unpriced: dict[str, int] = {}
        unpriced_calls = 0
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
            merge_model_prices,
        )
        from plugins.bot_unified_runtime.domains.ops.monitor.usage_monitor import (
            build_model_rows,
            format_cache_summary,
            format_channel_subrow,
            format_model_row_line,
        )

        # 2026-09-18 价格单源化：注册表（价目表导入的落点）为基准，settings
        # 覆盖（/bot model price）优先——此前只读 BOT_MODEL_PRICES，导入了
        # 价目表仍显示未计价。
        registry_prices: object = {}
        if callable(getattr(store, "list_model_registry", None)):
            try:
                registry_prices = store.list_model_registry() or {}
            except Exception:  # noqa: BLE001 - 注册表读不到只影响注记。
                registry_prices = {}
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
            registry_model_prices,
        )

        prices = merge_model_prices(
            registry_model_prices(registry_prices),
            store.get_or(
                "BOT_MODEL_PRICES",
                getattr(config, "bot_model_prices", {}) or {},
            ),
        )
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
            by_cache_read = dict(usage.get("by_model_cache_read", {}) or {})
            by_cache_write = dict(usage.get("by_model_cache_write", {}) or {})
            by_cost = dict(usage.get("by_model_cost_milli", {}) or {})
            by_calls = dict(usage.get("by_model_calls", {}) or {})
            by_unpriced = dict(usage.get("by_model_unpriced", {}) or {})
            unpriced_calls = int(usage.get("unpriced_calls", 0) or 0)
        elif diagnostics_store is not None:
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
                model_call_cost_milli,
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
                cache_read = int(
                    getattr(record, "llm_usage_cache_read_tokens", 0) or 0
                )
                cache_write = int(
                    getattr(record, "llm_usage_cache_write_tokens", 0) or 0
                )
                totals["prompt_tokens"] += values[0]
                totals["completion_tokens"] += values[1]
                totals["total_tokens"] += values[2]
                totals["cache_read_tokens"] += cache_read
                totals["cache_write_tokens"] += cache_write
                totals["calls"] += 1
                model_name = str(getattr(record, "llm_model", "unknown") or "unknown")
                by_model[model_name] = by_model.get(model_name, 0) + values[2]
                by_calls[model_name] = by_calls.get(model_name, 0) + 1
                by_prompt[model_name] = by_prompt.get(model_name, 0) + values[0]
                by_completion[model_name] = (
                    by_completion.get(model_name, 0) + values[1]
                )
                if cache_read:
                    by_cache_read[model_name] = (
                        by_cache_read.get(model_name, 0) + cache_read
                    )
                if cache_write:
                    by_cache_write[model_name] = (
                        by_cache_write.get(model_name, 0) + cache_write
                    )
                cost_milli, priced = model_call_cost_milli(
                    model_name,
                    values[0],
                    values[1],
                    prices,
                    cache_read_tokens=cache_read,
                    cache_creation_tokens=cache_write,
                )
                if priced:
                    totals["cost_milli"] += cost_milli
                    by_cost[model_name] = by_cost.get(model_name, 0) + cost_milli
                else:
                    unpriced_calls += 1
                    by_unpriced[model_name] = by_unpriced.get(model_name, 0) + 1
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
            format_milli_yuan,
        )

        aggregate: dict[str, Any] = {
            **totals,
            "by_model": by_model,
            "by_model_prompt": by_prompt,
            "by_model_completion": by_completion,
            "by_model_cache_read": by_cache_read,
            "by_model_cache_write": by_cache_write,
            "by_model_cost_milli": by_cost,
            "by_model_calls": by_calls,
            "by_model_unpriced": by_unpriced,
            "unpriced_calls": unpriced_calls,
        }
        # 钱换源到账本口径（与渠道子行同源，取整只在聚合末端）；回落或混口径时注记。
        caliber_note = _usage_money_from_ledger(config, target_date, aggregate)
        lines = [
            f"{target_date.isoformat()} 模型用量账单",
            (
                f"输入 {aggregate['prompt_tokens']:,}，输出 {aggregate['completion_tokens']:,}，"
                f"总计 {aggregate['total_tokens']:,} token，调用 {aggregate['calls']:,} 次"
            ),
            format_cache_summary(
                aggregate["cache_read_tokens"],
                aggregate["cache_write_tokens"],
                aggregate["prompt_tokens"],
            ),
            f"账单：{format_milli_yuan(aggregate['cost_milli'])} 元",
        ]
        if caliber_note:
            lines.append(caliber_note)
        lines.append("── 按模型 ──")
        rows = build_model_rows(
            aggregate,
            prices=prices,
            channel_stats=_usage_channel_stats(config, target_date),
        )
        if not rows:
            lines.append("（当日还没有成功调用记录）")
        for row in rows:
            lines.append(format_model_row_line(row, with_total=True))
            # 渠道子行（账本开时）：与定时报告 build_report_text 同款缩进风格。
            for sub in row.get("channels") or []:
                lines.append(format_channel_subrow(sub))
        residual_unpriced = int(aggregate.get("unpriced_calls", 0) or 0)
        if residual_unpriced:
            lines.append(
                f"（{residual_unpriced} 次调用未计价：价格未配置，未计入账单；用 /bot model price 维护）"
            )
        health_note = _usage_ledger_health(config)
        if health_note:
            lines.append(health_note)
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
        return _handle_vision_command(
            store, config, parts[1:], actor_id=actor_id, session_key=session_key
        )
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
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        reorder_priority_entries,
    )

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
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
                normalize_effort,
            )

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
        # 能力标签守卫（T4 路②）：`tags=` 是**整表替换**，管理员改档位时最容易
        # 顺手把 `native-audio`/`native-video`/`native-animation` 一起带走，而带走
        # 之后不报错、不写日志——音视频/动图只是静默退回 ASR/抽帧/拼静态条。
        # 分治口径：档位与模态标签（low/high/max/vision/text-only/manual…）照旧
        # 整表替换；`native-*` 从旧值自动保留，管理员自己写的能力标签原样生效
        # （所以"加一枚"这条路完全通）。要**摘**一枚声明，走唯一在册真身
        # `domains/core/channel_capability_tags.py`，不在这条命令里顺手做。
        preserved_capability_tags: list[str] = []
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
                authored = [tag.strip() for tag in value.split(",") if tag.strip()]
                merged, carried = preserve_capability_tags(
                    authored, base_entry.get("tags") or []
                )
                entry["tags"] = merged
                preserved_capability_tags.extend(carried)
            elif key == "effort":
                from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
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
        note = ""
        if preserved_capability_tags:
            note = (
                " 能力标签 "
                + "、".join(preserved_capability_tags)
                + " 已自动保留（tags= 只整表替换档位标签；摘能力声明要改唯一在册真身"
                " domains/core/channel_capability_tags.py）。"
            )
        return (
            f"已更新模型 {model_id}（改动存为运行时覆盖，优先于 .env 同名条目）。"
            "密钥不会回显。" + note
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
    *,
    actor_id: str = "runtime-admin",
    session_key: str = "",
) -> str:
    """视觉识别模型管理：/bot model vision <list|add|update|priority|remove>。"""
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
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
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
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
        store.set_override("BOT_VISION_MODE", mode, actor=actor_id, session_key=session_key)
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
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
                normalize_effort,
            )

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
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        active_persona_id,
        build_effective_alt_personas,
        current_bot_nickname,
    )

    # 名册读法与装配层同一真身（`providers.py` 备用人格视图吃的就是这一枚）：先人格册、
    # 未入册才回落 `.env` 兼容位。此前只读 `persona_set.build_alt_personas`（兼容位）
    # ⇒ 在册人格在命令面「不存在的人格」，§49「切人格要带 QQ 外观一起跟切」在命令面断掉
    # （取证 S-RECON-PADMIN-20260929.md §⑥）。
    alt_personas = build_effective_alt_personas(config)
    if not parts:
        return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"
    action = parts[0].lower()
    if action == "list":
        # 主人格中文名走自称唯一读法（P-G3 第二波）：override 用本命令手边这枚
        # store（＝切换态真身），册里没有才回落兼容显示名。此前直读
        # ``config.bot_persona_display_name`` ⇒ 切完人格这行还报旧名，与「当前覆盖」
        # 自相矛盾。绝不读 get_login_info（台账 #60★）。
        main_persona_name = current_bot_nickname(
            active_persona_id(config, override_provider=store.get_persona_override),
            config=config,
        )
        lines = [
            (
                f"主人格(A)：{getattr(config, 'bot_persona_profile_id', 'default')}"
                f"（{main_persona_name}）"
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
    # 门与实收同一本账（F-A 同型病的结构锁）：不在改状态名册里的形一律回用法、零写。
    if action not in _PERSONA_WRITE_ACTIONS:
        return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"
    if action == "switch":
        if len(parts) < 2:
            return "用法：/bot runtime persona switch <id|default>"
        target = parts[1].strip()
        if target != "default" and target not in alt_personas:
            return f"不存在的人格：{target}。可用：default,{','.join(alt_personas)}"
        if target == "default":
            store.set_persona_override("")
            return (
                "已回到自动模式（情绪触发 → 概率 → 主人格），"
                "外观是否恢复跟随，同样以逐项回执为准。"
            )
        store.set_persona_override(target)
        # 受理≠宣告（ATK 票③-3）：外观/人格文本/知识清单是否跟随由逐项回执判，
        # 本行只报「已受理」，绝不替它们宣告完成。
        return (
            f"人格切换指令已受理：{target}（持续到下一次 switch default）；"
            "QQ 外观/人格文本/知识清单是否跟随，以逐项回执为准。"
        )
    # auto / reset 同义＝清强制切换回自动；probability/概率 缺参形沿用旧 auto 回执。
    if action == "auto" or action == "reset" or len(parts) < 3:
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


def build_session_identity_admin_result(
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    session_key: str,
    command_text: str,
    sender_id: str = "",
    group_id: str = "",
) -> CapabilityResult:
    """/bot identity set|tag|show|clear —— 会话级身份记忆（管理员专用）。

    在哪个群/私聊里执行，就设置哪个会话的身份。防 OOC：渲染层内建护栏，
    会话身份只调整称呼与语气，永远不推翻守岸人核心人格。
    例外（Task 2 用户自助，无需管理员）：set-name/set-gender/unset-name/
    unset-gender 四个子命令在管理员门**之前**拦截，转交
    capabilities/echo.build_identity_preference_result 处理发送者本人的
    称谓偏好（AddressingPreferenceStore）。
    """
    parts = command_text.split()
    sub = parts[0].lower() if parts else ""
    if sub in {"set-name", "set-gender", "unset-name", "unset-gender"}:
        from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
            build_identity_preference_result,
        )

        return build_identity_preference_result(
            config,
            request_id=request_id,
            sender_id=sender_id,
            group_id=group_id,
            command_text=command_text,
        )
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        build_runtime_data_path,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.session_identity import (
        SessionIdentityStore,
    )

    if not session_key.strip():
        return _error_result(request_id, "无法确定当前会话（仅在群聊/私聊内可用）。")
    parts = command_text.split()
    sub = parts[0].lower() if parts else "show"
    db_path = build_runtime_data_path(
        config,
        str(getattr(config, "bot_session_identity_db_path", "data/session_identity.sqlite3")),
    )
    store = SessionIdentityStore(db_path)
    if sub == "show":
        identity = store.get(session_key)
        if identity is None or (not identity.nickname and not identity.tags):
            return _ok_result(
                request_id, "本会话还没有身份设定（/bot identity set <昵称> 开始）。"
            )
        lines = [f"本会话身份：称呼「{identity.nickname or '（未设）'}」"]
        if identity.tags:
            lines.append(f"标签：{'、'.join(identity.tags)}")
        lines.append(f"设置人：{identity.set_by or '未知'}；更新于 {identity.updated_at}")
        return _ok_result(request_id, "\n".join(lines), capability_id="bot.identity")
    if sub == "set":
        nickname = command_text.removeprefix("set").strip()
        if not nickname:
            return _error_result(request_id, "用法：/bot identity set <昵称>（如 set 岸宝）")
        identity = store.set(session_key, nickname=nickname, set_by="admin")
        return _ok_result(
            request_id,
            f"已设定：本会话称呼你为「{identity.nickname}」。（只影响称呼与语气，人格不变）",
            capability_id="bot.identity",
        )
    if sub == "tag":
        raw = command_text.removeprefix("tag").strip()
        if not raw:
            return _error_result(request_id, "用法：/bot identity tag <标签1,标签2>（最多 8 个）")
        identity = store.set(session_key, tags=raw, set_by="admin")
        return _ok_result(
            request_id,
            "已设定标签：" + ("、".join(identity.tags) if identity.tags else "（空）"),
            capability_id="bot.identity",
        )
    if sub == "clear":
        removed = store.clear(session_key)
        return _ok_result(
            request_id,
            "已清除本会话身份设定。" if removed else "本会话本就没有身份设定。",
            capability_id="bot.identity",
        )
    return _error_result(
        request_id,
        "用法：/bot identity show | set <昵称> | tag <标签1,标签2> | clear（在本会话内执行即对本会话生效）",
    )


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
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        build_runtime_data_path,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import (
        QuirkStore,
    )

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
        # G-07：范围标注让审核者看得见这条怪癖会渲染给谁（global/用户名）。
        from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import (
            format_scope_label,
        )

        lines = [
            f"- {q.quirk_id[:8]} [{label.get(q.status, q.status)}] {q.quirk_text}"
            f"（来源 {q.source or '未知'}；范围 {format_scope_label(q)}）"
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
    actor_id: str = "runtime-admin",
    diagnostics_store: Any | None = None,
    usage_store: Any | None = None,
    session_key: str = "",
) -> CapabilityResult:
    from plugins.bot_unified_runtime.control_plane.services import ControlServiceError

    if not set(actor_roles) & {"admin", "super_admin"}:
        return _admin_only_result(request_id)
    command_parts = command_text.strip().lower().split()
    # 门判的必须是**处理腿真正执行的那条命令**。腿在 `_handle_runtime_command` 里先
    # `_extract_instance(parts[1:])` 摘掉 `--instance <名称>` 才按位置取动作，门若按裸
    # token 位置判，`persona --instance second switch <id>` 就靠插位躲开[:2]比较、照样落写
    # （F-A 第二洞；nickname/model 同病——取证 S-RECON-PADMIN-20260929.md §③）。
    # 归一化一次、门与腿同尺，就不存在「门看 A 串、腿执行 B 串」这种缝隙。
    gate_parts, _gate_instance = _extract_instance(command_parts)
    command_action = gate_parts[0] if gate_parts else ""
    core_persona_write = (
        command_action == "persona"
        and len(gate_parts) > 1
        and gate_parts[1] in _PERSONA_WRITE_ACTIONS
    )
    model_write = (
        command_action == "model"
        and len(gate_parts) > 1
        and gate_parts[1] not in {"list", "show", "status", "routes", "prices", "help", "health"}
    )
    nickname_write = gate_parts[:2] in (["nickname", "add"], ["nickname", "remove"])
    # 备份腿的写面（起备份 / 按名删旧副本 / 把副本暂存出去）与上面同尺判：门与腿都读
    # ``_BACKUP_WRITE_ACTIONS``，禁第二本账。读面（status/list/verify/prune-plan/
    # restore-plan）留在 admin——「到底有没有备份」必须一句话问得出来。
    backup_write = (
        command_action == "backup"
        and len(gate_parts) > 1
        and gate_parts[1] in _BACKUP_WRITE_ACTIONS
    )
    if (command_action in {"set", "reset"} or core_persona_write or model_write or nickname_write or backup_write) and "super_admin" not in actor_roles:
        return _error_result(request_id, "修改运行时参数需要 super_admin 权限。")
    try:
        body = _handle_runtime_command(
            manager,
            default_instance,
            config,
            command_text,
            diagnostics_store=diagnostics_store,
            usage_store=usage_store,
            actor_id=actor_id, actor_roles=actor_roles, request_id=request_id,
            session_key=session_key,
        )
    except ControlServiceError as exc:
        return _error_result(request_id, exc.message)
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

