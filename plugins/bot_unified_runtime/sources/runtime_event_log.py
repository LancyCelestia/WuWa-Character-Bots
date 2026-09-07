"""运行时事件日志：毫秒时间戳 + INFO/WARNING/ERROR 分级 + 查询。

单文件纯文本（每行一条事件），自动轮转保留最近两代；线程安全。
同时提供 logging 桥，把 NoneBot 自身日志（含 NapCat/OneBot 适配器
连接事件）按同一格式写进事件文件。

配置：`BOT_RUNTIME_LOG_FILE`（默认 data/runtime_events.log）、
`BOT_RUNTIME_LOG_MAX_BYTES`（默认 2MB）、`BOT_RUNTIME_LOG_LEVEL`。
所有字段只写安全短文本，不写密钥/cookie/正文。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.audit import redact_private_debug

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def _normalize_level(level: str) -> str:
    key = str(level or "INFO").strip().upper()
    return key if key in _LEVEL_ORDER else "INFO"


class _LogBridge(logging.Handler):
    """把 Python logging 记录转发到 RuntimeEventLog。"""

    def __init__(self, target: RuntimeEventLog) -> None:
        super().__init__()
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._target.emit(
                _normalize_level(record.levelname),
                "logger",
                logger=record.name,
                message=redact_private_debug(self.format(record))[:500],
            )
        except Exception:  # noqa: BLE001, S110 - 日志桥失败不影响业务。
            pass


class RuntimeEventLog:
    """按毫秒时间戳写分级事件，支持最近 N 条按级别过滤查询。"""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = 2 * 1024 * 1024,
        min_level: str = "INFO",
    ) -> None:
        self.path = Path(path).expanduser()
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.min_level = _normalize_level(min_level)
        self._lock = threading.Lock()

    def _ts(self) -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def emit(self, level: str, event: str, **fields: Any) -> None:
        level = _normalize_level(level)
        if _LEVEL_ORDER[level] < _LEVEL_ORDER[self.min_level]:
            return
        parts = [f"{self._ts()} [{level}] event={event}"]
        for key, value in fields.items():
            if value is None:
                continue
            text = str(value).replace("\n", " ").replace("\r", " ")
            parts.append(f"{key}={text[:300]}")
        line = " ".join(parts)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    old_path = self.path.with_suffix(self.path.suffix + ".old")
                    try:
                        old_path.unlink()
                    except OSError:
                        pass
                    self.path.rename(old_path)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.write("\n")
        except OSError:
            return

    def info(self, event: str, **fields: Any) -> None:
        self.emit("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self.emit("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.emit("ERROR", event, **fields)

    def debug(self, event: str, **fields: Any) -> None:
        self.emit("DEBUG", event, **fields)

    def read_recent(self, limit: int = 50, min_level: str = "INFO") -> list[str]:
        min_level = _normalize_level(min_level)
        threshold = _LEVEL_ORDER[min_level]
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        filtered: list[str] = []
        for line in lines:
            for level_name, level_value in _LEVEL_ORDER.items():
                if f"[{level_name}]" in line and level_value >= threshold:
                    filtered.append(line)
                    break
        return filtered[-max(1, int(limit)):]

    def aggregate_llm_usage(self, date_text: str) -> dict[str, Any]:
        """Aggregate safe token counters from successful transport events for one local date."""
        return self.aggregate_llm_usage_range(date_text, date_text)

    def aggregate_llm_usage_range(
        self,
        start_date_text: str,
        end_date_text: str,
        *,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """按本地日期闭区间聚合成功调用的 token/费用计数（含按模型分组）。

        ``since`` 给定时（aware datetime），只统计该时间点之后的调用
        （事件行以本地时间戳开头），供定时报告做"自上个报告点至今"窗口。
        """
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
        by_model_prompt: dict[str, int] = {}
        by_model_completion: dict[str, int] = {}
        by_model_cache_read: dict[str, int] = {}
        by_model_cache_write: dict[str, int] = {}
        by_model_cost_milli: dict[str, int] = {}
        unpriced_calls: int = 0
        seen_requests: set[str] = set()
        lines: list[str] = []
        for path in (self.path.with_suffix(self.path.suffix + ".old"), self.path):
            try:
                lines.extend(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                continue
        for line in lines:
            if not line.startswith(start_date_text) and not line.startswith(
                end_date_text
            ):
                continue
            date_prefix = line[:10]
            if date_prefix < start_date_text or date_prefix > end_date_text:
                continue
            if "event=transport_receipt" not in line:
                continue
            if since is not None:
                try:
                    line_ts = datetime.strptime(
                        line[:19], "%Y-%m-%d %H:%M:%S"
                    ).astimezone()
                except ValueError:
                    line_ts = None
                if line_ts is not None and line_ts < since:
                    continue
            fields = {
                key: value
                for token in line.split()
                if "=" in token
                for key, value in [token.split("=", 1)]
            }
            request_id = fields.get("request_id", "")
            if not request_id or request_id in seen_requests:
                continue
            total = fields.get("total_tokens", "0")
            if not total.isdecimal() or int(total) <= 0:
                continue
            seen_requests.add(request_id)
            prompt_raw = fields.get("prompt_tokens", "0")
            completion_raw = fields.get("completion_tokens", "0")
            prompt_value = int(prompt_raw) if prompt_raw.isdecimal() else 0
            completion_value = int(completion_raw) if completion_raw.isdecimal() else 0
            totals["prompt_tokens"] += prompt_value
            totals["completion_tokens"] += completion_value
            totals["total_tokens"] += int(total)
            model = fields.get("model", "unknown") or "unknown"
            by_model[model] = by_model.get(model, 0) + int(total)
            by_model_prompt[model] = by_model_prompt.get(model, 0) + prompt_value
            by_model_completion[model] = (
                by_model_completion.get(model, 0) + completion_value
            )
            for key, target in (
                ("cache_read_tokens", by_model_cache_read),
                ("cache_write_tokens", by_model_cache_write),
            ):
                raw_value = fields.get(key, "0")
                if raw_value.isdecimal() and int(raw_value) > 0:
                    value = int(raw_value)
                    totals[key] += value
                    target[model] = target.get(model, 0) + value
            cost_raw = fields.get("cost_milli", "")
            if cost_raw.lstrip("-").isdecimal():
                cost_value = int(cost_raw)
                totals["cost_milli"] += cost_value
                by_model_cost_milli[model] = (
                    by_model_cost_milli.get(model, 0) + cost_value
                )
            elif "cost_unpriced=1" in line:
                unpriced_calls += 1
        totals["calls"] = len(seen_requests)
        return {
            **totals,
            "by_model": by_model,
            "by_model_prompt": by_model_prompt,
            "by_model_completion": by_model_completion,
            "by_model_cache_read": by_model_cache_read,
            "by_model_cache_write": by_model_cache_write,
            "by_model_cost_milli": by_model_cost_milli,
            "unpriced_calls": unpriced_calls,
        }

    def attach_to_logging(self, logger_name: str = "nonebot") -> _LogBridge:
        """把指定 logger（默认 nonebot 及其子 logger）接到事件文件。"""
        logger = logging.getLogger(logger_name)
        bridge = _LogBridge(self)
        bridge.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(bridge)
        return bridge
