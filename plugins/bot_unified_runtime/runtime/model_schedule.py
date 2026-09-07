"""分时段自动切换模型预设。

``BOT_MODEL_SCHEDULE`` 是 JSON 对象：``{"HH:MM-HH:MM": "预设或注册表id"}``，
支持跨零点窗口（如 ``"23:00-07:00": "luna"``）。调度器每 30 秒检查一次：

- 命中窗口 → 把 ``BOT_CHAT_MODEL`` 运行时覆盖设为该时段的模型 id；
- 未命中任何窗口且上一次是调度器设置的 → 清除覆盖，回到自动选型；
- 窗口内管理员手动 ``/bot runtime model set`` 的选择会保留到下一个窗口边界。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_MODEL_SCHEDULE_JOB_ID = "bot_model_schedule_switch"


def parse_model_schedule(raw: object) -> dict[str, str]:
    """把配置值（dict 或 JSON 字符串）解析成 窗口 -> 模型id 表。"""
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        items = list(parsed.items()) if isinstance(parsed, dict) else []
    else:
        return {}
    schedule: dict[str, str] = {}
    for window, target in items:
        window_text = str(window).strip()
        target_text = str(target).strip()
        if window_text and target_text and _parse_window(window_text) is not None:
            schedule[window_text] = target_text
    return schedule


def _parse_window(window: str) -> tuple[dt_time, dt_time] | None:
    text = window.strip()
    if "-" not in text:
        return None
    start_text, _, end_text = text.partition("-")
    start = _parse_clock(start_text)
    end = _parse_clock(end_text)
    if start is None or end is None:
        return None
    return start, end


def _parse_clock(value: str) -> dt_time | None:
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


def resolve_scheduled_model(
    schedule: dict[str, str],
    now: dt_time,
) -> str:
    """返回当前时刻命中的模型 id；未命中任何窗口返回空字符串。"""
    for window, target in schedule.items():
        parsed = _parse_window(window)
        if parsed is None:
            continue
        start, end = parsed
        if start <= end:
            in_window = start <= now < end
        else:  # 跨零点窗口
            in_window = now >= start or now < end
        if in_window:
            return target
    return ""


def _register_model_schedule_scheduler(
    *,
    scheduler: Any,
    config: object,
    settings_store: Any,
) -> None:
    """注册每 30 秒一次的分时段切换任务；调度失败只记日志。"""

    from apscheduler.triggers.interval import IntervalTrigger

    timezone_name = str(getattr(config, "bot_timezone", "Asia/Hong_Kong") or "Asia/Hong_Kong")
    try:
        zone: Any = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - 时区配置错误时回退系统本地时区。
        zone = datetime.now().astimezone().tzinfo

    state = {"last_applied": ""}

    def _job() -> None:
        try:
            raw = settings_store.get_or(
                "BOT_MODEL_SCHEDULE",
                getattr(config, "bot_model_schedule", {}),
            )
            schedule = parse_model_schedule(raw)
            if not schedule:
                return
            now_local = datetime.now(zone).time()
            target = resolve_scheduled_model(schedule, now_local)
            if target == state["last_applied"]:
                return
            if target:
                settings_store.set_override("BOT_CHAT_MODEL", target)
                logger.info(
                    "model schedule switched override=%s window active", target
                )
            else:
                settings_store.reset_override("BOT_CHAT_MODEL")
                logger.info("model schedule cleared override (outside windows)")
            state["last_applied"] = target
        except Exception:  # 调度任务失败不影响主链路。
            logger.exception("model schedule job failed")

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(seconds=30),
        id=_MODEL_SCHEDULE_JOB_ID,
        replace_existing=True,
    )
