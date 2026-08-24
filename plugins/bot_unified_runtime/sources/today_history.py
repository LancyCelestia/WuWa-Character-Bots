"""「历史上的今天」数据源（适配自 nonebot-plugin-today-in-history）。

数据源：百度百科公开接口 https://baike.baidu.com/cms/home/eventsOnHistory/{MM}.json
- 每天缓存一次到 data/today_history_cache.json（git 忽略）。
- 返回当月 JSON 里的 (year, title) 列表。
- 解析逻辑沿用原插件的 HTML 清理思路（同步化，urllib 实现）。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
)


@dataclass(frozen=True)
class HistoryEvent:
    year: str
    title: str


def _parse_history_json(text: str) -> Any:
    """解析百度百科接口 JSON（标题/简介里可能带 HTML 标签）。

    优先直接解析；失败时回退为去掉 HTML 标签再解析。
    """
    try:
        return json.loads(text)
    except ValueError:
        cleaned = text.replace("</a>", "").replace("\\/a>", "")
        cleaned = re.sub(r"<a[^>]*>", "", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = cleaned.replace('\\"', '"')
        return json.loads(cleaned)


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def fetch_today_history(*, proxy: str = "", timeout: float = 10.0) -> list[HistoryEvent]:
    """拉取今天的「历史上的今天」条目（失败抛 ParseHttpError）。"""
    now = datetime.now()  # noqa: DTZ005 - 本地时间有意 naive。
    month = now.strftime("%m")
    day = now.strftime("%d")
    url = f"https://baike.baidu.com/cms/home/eventsOnHistory/{month}.json"
    _, raw = http_get_text(url, timeout=timeout, proxy=proxy)
    data = _parse_history_json(raw)
    items = ((data or {}).get(month) or {}).get(month + day) or []
    return [
        HistoryEvent(
            year=str(item.get("year") or ""),
            title=_strip_html(str(item.get("title") or "")),
        )
        for item in items
        if item.get("year") is not None
    ]


class TodayHistoryProvider:
    """带每日缓存的提供方（进程内锁 + 文件缓存）。"""

    def __init__(
        self,
        *,
        cache_file: str = "data/today_history_cache.json",
        proxy: str = "",
    ) -> None:
        self.cache_file = Path(cache_file)
        self.proxy = str(proxy or "")
        self._lock = threading.Lock()

    def _read_cache(self) -> dict[str, Any]:
        try:
            if self.cache_file.exists():
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def get_events(self, *, force: bool = False) -> list[HistoryEvent]:
        today = datetime.now().strftime("%Y%m%d")  # noqa: DTZ005 - 本地时间有意 naive。
        with self._lock:
            if not force:
                cached = self._read_cache()
                if cached.get("date") == today and cached.get("events") is not None:
                    return [
                        HistoryEvent(year=str(item["year"]), title=str(item["title"]))
                        for item in cached["events"]
                    ]
            try:
                events = fetch_today_history(proxy=self.proxy)
            except ParseHttpError:
                # 拉取失败时退回旧缓存（哪怕过期），保证可用。
                cached = self._read_cache()
                if cached.get("events") is not None:
                    return [
                        HistoryEvent(year=str(item["year"]), title=str(item["title"]))
                        for item in cached["events"]
                    ]
                return []
            if events:
                self._write_cache(
                    {
                        "date": today,
                        "events": [
                            {"year": event.year, "title": event.title}
                            for event in events
                        ],
                    }
                )
            return events


def format_history_text(events: list[HistoryEvent]) -> str:
    now = datetime.now()  # noqa: DTZ005 - 本地时间有意 naive。
    lines = [f"历史上的今天 {now.strftime('%m%d')}"]
    for event in events:
        lines.append(f"{event.year} {event.title}")
    return "\n".join(lines)
