"""模型用量监控与定时账单报告。

数据源：运行事件日志（runtime_event_log）中成功调用的 transport_receipt
事件行——输入/输出/缓存命中/缓存创建 token 与按调用时刻价格记账的
``cost_milli``。

- 实时阈值（每 60 秒巡检当日聚合；每项每天只提醒一次）：
  * 单模型当日输出 token > ``BOT_USAGE_ALERT_OUTPUT_TOKENS``（默认 500 万）；
  * 单模型当日输入 token > ``BOT_USAGE_ALERT_INPUT_TOKENS``（默认 5000 万）；
  * 当日实际账单 > ``BOT_USAGE_ALERT_DAILY_COST_YUAN``（默认 10 元）→
    立即发送报告卡 + 提醒（含各模型金额明细）。
- 定时报告（北京时间 ``BOT_USAGE_REPORT_HOURS``，默认 13/18/23 点整）：
  统计自上个报告时间点至今的金额与 token；13:00 报告额外附过去 24 小时
  总花费。报告时间点写 ``BOT_USAGE_REPORT_STATE_FILE``，重启不丢。

推送走 runtime/alerts 管理员预警管线（QQ 管理员私聊），渲染可用时附带
Mica 云母质感报告卡图片，失败自动回退纯文本。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.runtime.alerts import (
    AlertContent,
    send_admin_alert_requests,
)
from plugins.bot_unified_runtime.runtime.pricing import format_milli_yuan

logger = logging.getLogger(__name__)

_THRESHOLD_JOB_ID = "bot_usage_threshold_alerts"
_REPORT_JOB_ID = "bot_usage_scheduled_report"


# ==================== 阈值判定（纯函数） ====================
def threshold_alert_items(
    aggregate: dict[str, Any],
    *,
    output_limit: int = 5_000_000,
    input_limit: int = 50_000_000,
    cost_limit_milli: int = 10_000,
) -> list[dict[str, Any]]:
    """按阈值返回当日需要提醒的条目（不含去重）。"""
    items: list[dict[str, Any]] = []
    by_completion = aggregate.get("by_model_completion") or {}
    if isinstance(by_completion, dict) and output_limit > 0:
        for model, tokens in sorted(by_completion.items()):
            if int(tokens or 0) > output_limit:
                items.append(
                    {
                        "key": f"out:{model}",
                        "kind": "output",
                        "model": str(model),
                        "value": int(tokens or 0),
                        "limit": output_limit,
                    }
                )
    by_prompt = aggregate.get("by_model_prompt") or {}
    if isinstance(by_prompt, dict) and input_limit > 0:
        for model, tokens in sorted(by_prompt.items()):
            if int(tokens or 0) > input_limit:
                items.append(
                    {
                        "key": f"in:{model}",
                        "kind": "input",
                        "model": str(model),
                        "value": int(tokens or 0),
                        "limit": input_limit,
                    }
                )
    cost_milli = int(aggregate.get("cost_milli", 0) or 0)
    if cost_limit_milli > 0 and cost_milli > cost_limit_milli:
        items.append(
            {
                "key": "cost",
                "kind": "cost",
                "model": "",
                "value": cost_milli,
                "limit": cost_limit_milli,
            }
        )
    return items


def build_threshold_alert(
    item: dict[str, Any],
    *,
    occurred_at: str = "",
) -> AlertContent:
    """单条阈值提醒 -> 五要素 AlertContent。"""
    kind = item.get("kind")
    if kind == "cost":
        what = (
            f"当日实际账单已达 {format_milli_yuan(int(item['value']))} 元，"
            f"超过提醒阈值 {format_milli_yuan(int(item['limit']))} 元。"
        )
        impact = "继续调用会持续产生费用；如非预期请检查是否被滥用或模型选择过贵。"
        fix = "用 /bot model usage 查看各模型花费明细；必要时调整分组顺序或给贵模型打 manual 标签。"
        title = "当日模型账单超限提醒"
        location = "usage_monitor/cost"
    else:
        label = "输出" if kind == "output" else "输入"
        what = (
            f"模型 {item['model']} 当日{label} Token 已达 "
            f"{int(item['value']):,}，超过提醒阈值 {int(item['limit']):,}。"
        )
        impact = "该模型今日消耗异常偏高，可能存在循环调用或大上下文放大。"
        fix = "用 /bot model usage 查看明细；确认业务后考虑调低该模型优先级或限制调用。"
        title = f"模型{label}Token 超限提醒"
        location = f"usage_monitor/{label}_tokens"
    return AlertContent(
        title=title,
        what_happened=what,
        impact=impact,
        fix_suggestion=fix,
        location=location,
        level="warning",
        occurred_at=occurred_at,
    )


# ==================== 报告内容（纯函数） ====================
def build_model_rows(aggregate: dict[str, Any]) -> list[dict[str, Any]]:
    """把聚合结果转成报告卡行（按费用降序，未计价的排后面）。"""
    by_model = aggregate.get("by_model") or {}
    rows: list[dict[str, Any]] = []
    for model in by_model:
        prompt = int((aggregate.get("by_model_prompt") or {}).get(model, 0) or 0)
        cache_read = int((aggregate.get("by_model_cache_read") or {}).get(model, 0) or 0)
        cache_write = int((aggregate.get("by_model_cache_write") or {}).get(model, 0) or 0)
        completion = int((aggregate.get("by_model_completion") or {}).get(model, 0) or 0)
        cost_milli = int((aggregate.get("by_model_cost_milli") or {}).get(model, 0) or 0)
        rows.append(
            {
                "model": model,
                "prompt": prompt,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "completion": completion,
                "cost_milli": cost_milli,
                "cost_text": format_milli_yuan(cost_milli),
                "priced": True,
            }
        )
    rows.sort(key=lambda row: (-row["cost_milli"], row["model"]))
    return rows


def build_report_text(
    aggregate: dict[str, Any],
    *,
    window_label: str,
) -> str:
    """定时报告的纯文本版本（渲染失败/控制台回退）。"""
    lines = [
        f"[用量报告] {window_label}",
        (
            f"总计：输入 {int(aggregate.get('prompt_tokens', 0)):,}，"
            f"输出 {int(aggregate.get('completion_tokens', 0)):,}，"
            f"共 {int(aggregate.get('total_tokens', 0)):,} token，"
            f"调用 {int(aggregate.get('calls', 0)):,} 次，"
            f"账单 {format_milli_yuan(int(aggregate.get('cost_milli', 0) or 0))} 元"
        ),
    ]
    cache_read = int(aggregate.get("cache_read_tokens", 0) or 0)
    cache_write = int(aggregate.get("cache_write_tokens", 0) or 0)
    if cache_read or cache_write:
        lines.append(f"缓存：命中 {cache_read:,}，创建 {cache_write:,}")
    for row in build_model_rows(aggregate):
        lines.append(
            f"- {row['model']}：入 {row['prompt']:,} / 出 {row['completion']:,}"
            f" / 费 {row['cost_text']} 元"
        )
    unpriced = int(aggregate.get("unpriced_calls", 0) or 0)
    if unpriced:
        lines.append(f"（{unpriced} 次调用未配置价格，未计入账单）")
    return "\n".join(lines)


def build_report_alert(
    aggregate: dict[str, Any],
    *,
    window_label: str,
    extra_24h: dict[str, Any] | None = None,
) -> AlertContent:
    """定时报告 -> 五要素 AlertContent（info 级）。"""
    what = build_report_text(aggregate, window_label=window_label)
    if extra_24h is not None:
        what += "\n\n过去 24 小时总花费：\n" + build_report_text(
            extra_24h, window_label="过去 24 小时"
        )
    return AlertContent(
        title=f"模型用量账单报告 · {window_label}",
        what_happened=what or "统计窗口内没有新的调用。",
        impact="数据仅供费用观察，不影响任何自动行为。",
        fix_suggestion="需要明细卡图片可在 QQ 内发送 /bot model usage；价格用 /bot model price 维护。",
        location="usage_monitor/scheduled_report",
        level="info",
    )


# ==================== 状态持久化 ====================
def _read_state(path: Path) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = ""
    if isinstance(payload, dict):
        raw = str(payload.get("last_report_at", "") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _write_state(path: Path, moment: datetime) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"last_report_at": moment.isoformat(timespec="seconds")},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("usage report state write failed: %s", path)


# ==================== 调度注册 ====================
def _aggregate_since(
    usage_log: Any,
    *,
    since: datetime,
    now: datetime,
) -> dict[str, Any]:
    return usage_log.aggregate_llm_usage_range(
        since.date().isoformat(),
        now.date().isoformat(),
        since=since,
    )


def register_usage_monitor_scheduler(
    *,
    scheduler: Any,
    config: object,
    pipeline: Any,
    usage_log: Any,
    admin_ids: list[str],
    settings_store: Any | None = None,
    render_backend: Any | None = None,
    card_dir: str = "data/cards",
) -> None:
    """注册阈值巡检（60 秒）与 13/18/23 点定时报告；失败只记日志。"""
    if not bool(getattr(config, "bot_usage_monitor_enabled", True)):
        return
    if not admin_ids:
        logger.info("usage monitor disabled: no admin ids configured")
        return
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from plugins.bot_unified_runtime.output.card_render.usage_cards import (
        render_usage_card_png,
        usage_report_mica_html,
    )

    timezone_name = str(
        getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong"
    )
    try:
        zone: Any = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - 时区配置错误回退系统本地时区。
        zone = datetime.now().astimezone().tzinfo
    state_path = Path(
        str(getattr(config, "bot_usage_report_state_file", "data/usage_report_state.json"))
    ).expanduser()
    output_limit = max(0, int(getattr(config, "bot_usage_alert_output_tokens", 5_000_000) or 0))
    input_limit = max(0, int(getattr(config, "bot_usage_alert_input_tokens", 50_000_000) or 0))
    daily_cost_yuan = max(0.0, float(getattr(config, "bot_usage_alert_daily_cost_yuan", 10.0) or 0.0))
    cost_limit_milli = round(daily_cost_yuan * 1000)
    fired: dict[str, str] = {}

    def _dispatch(alert: AlertContent, *, image_path: str = "") -> None:
        try:
            send_admin_alert_requests(
                pipeline,
                list(admin_ids),
                alert,
                image_path=image_path,
            )
        except Exception:
            logger.exception("usage monitor alert dispatch failed")

    def _render_report_card(
        aggregate: dict[str, Any],
        *,
        kicker: str,
        title: str,
        status_label: str,
        status_kind: str,
        window_label: str,
        request_id: str,
    ) -> str:
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        html_text = usage_report_mica_html(
            config,
            kicker=kicker,
            title=title,
            status_label=status_label,
            status_kind=status_kind,
            window_label=window_label,
            generated_at=datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S"),
            totals={
                **aggregate,
                "cost_text": format_milli_yuan(int(aggregate.get("cost_milli", 0) or 0)),
            },
            model_rows=build_model_rows(aggregate),
        )
        return render_usage_card_png(
            render_backend,
            html_text,
            card_dir=card_dir,
            request_id=request_id,
            prefix="usage_report",
        )

    def _threshold_job() -> None:
        try:
            now = datetime.now(zone)
            today = now.date().isoformat()
            aggregate = usage_log.aggregate_llm_usage(today)
            items = threshold_alert_items(
                aggregate,
                output_limit=output_limit,
                input_limit=input_limit,
                cost_limit_milli=cost_limit_milli,
            )
            for item in items:
                if fired.get(item["key"]) == today:
                    continue
                fired[item["key"]] = today
                alert = build_threshold_alert(
                    item, occurred_at=now.strftime("%Y-%m-%d %H:%M:%S")
                )
                image_path = ""
                if item["kind"] == "cost":
                    # 账单超限：立即发送报告卡 + 提醒。
                    image_path = _render_report_card(
                        aggregate,
                        kicker="管理员预警 · 用量监控",
                        title="当日账单超限报告",
                        status_label=f"今日账单 {format_milli_yuan(int(aggregate.get('cost_milli', 0) or 0))} 元",
                        status_kind="warn",
                        window_label=f"{today} 00:00 至今",
                        request_id=f"cost-alert-{today}",
                    )
                _dispatch(alert, image_path=image_path)
        except Exception:
            logger.exception("usage threshold job failed")

    def _run_report() -> None:
        try:
            now = datetime.now(zone)
            last = _read_state(state_path)
            since = last if last is not None else now - timedelta(hours=24)
            if since >= now:
                since = now - timedelta(hours=24)
            window_label = (
                f"{since.strftime('%m-%d %H:%M')} 至 {now.strftime('%m-%d %H:%M')}"
            )
            aggregate = _aggregate_since(usage_log, since=since, now=now)
            extra_24h = None
            if now.hour == 13:
                extra_24h = _aggregate_since(
                    usage_log, since=now - timedelta(hours=24), now=now
                )
            image_path = _render_report_card(
                aggregate,
                kicker="定时报告 · 模型用量",
                title="模型用量账单报告",
                status_label=f"账单 {format_milli_yuan(int(aggregate.get('cost_milli', 0) or 0))} 元",
                status_kind="ok",
                window_label=window_label,
                request_id=f"report-{now.strftime('%Y%m%d%H%M')}",
            )
            _dispatch(
                build_report_alert(
                    aggregate, window_label=window_label, extra_24h=extra_24h
                ),
                image_path=image_path,
            )
            _write_state(state_path, now)
        except Exception:
            logger.exception("usage scheduled report failed")

    scheduler.add_job(
        _threshold_job,
        trigger=IntervalTrigger(seconds=60),
        id=_THRESHOLD_JOB_ID,
        replace_existing=True,
    )
    hours_raw = str(getattr(config, "bot_usage_report_hours", "13,18,23") or "")
    hours: list[int] = []
    for part in hours_raw.replace("，", ",").split(","):
        try:
            hour = int(part.strip())
        except ValueError:
            continue
        if 0 <= hour <= 23 and hour not in hours:
            hours.append(hour)
    if hours:
        scheduler.add_job(
            _run_report,
            trigger=CronTrigger(
                minute=0, hour=",".join(str(hour) for hour in hours), timezone=zone
            ),
            id=_REPORT_JOB_ID,
            replace_existing=True,
        )


__all__ = [
    "build_model_rows",
    "build_report_alert",
    "build_report_text",
    "build_threshold_alert",
    "register_usage_monitor_scheduler",
    "threshold_alert_items",
]
