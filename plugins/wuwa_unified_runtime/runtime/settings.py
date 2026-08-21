"""运行时设置存储：管理员在对话里可调整的参数与昵称。

- 覆盖项只支持白名单键（防止任意配置注入），存 ``data/runtime_settings.json``
  （git 忽略），重启后保留。
- 昵称列表（多昵称）同样存这里，供命令别名解析器读取。
- 互动计数按 sender_id 累计，供关系层级自动升级使用。
- 线程安全（锁）；文件损坏时安全降级为空存储。

管理员专属指令走统一流水线（`wuwa.runtime` 能力），只允许
``WUWA_ADMIN_USER_IDS`` 中的管理员执行。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

# 互动次数 -> 自动关系层级（档案未显式指定 familiarity 时生效）。
FAMILIAR_INTERACTION_THRESHOLD = 8
CLOSE_INTERACTION_THRESHOLD = 30


def _temperature_converter(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 2.0:
        raise ValueError("WUWA_CHAT_TEMPERATURE 必须在 0.0-2.0 之间")
    return parsed


def _max_tokens_converter(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError("WUWA_CHAT_MAX_TOKENS 必须 >= 1")
    return parsed


def _reply_chars_converter(value: str) -> int:
    parsed = int(value)
    if parsed < 200:
        raise ValueError("WUWA_REPLY_MAX_CHARS_PER_MESSAGE 必须 >= 200")
    return parsed


def _bool_converter(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on", "开", "是"}:
        return True
    if normalized in {"false", "0", "no", "off", "关", "否"}:
        return False
    raise ValueError("布尔值必须是 true/false（或 开/关）")


# 白名单键 -> 转换函数；转换失败抛 ValueError，不会写入。
SETTABLE_KEYS: dict[str, Callable[[str], Any]] = {
    "WUWA_CHAT_TEMPERATURE": _temperature_converter,
    "WUWA_CHAT_MAX_TOKENS": _max_tokens_converter,
    "WUWA_REPLY_MAX_CHARS_PER_MESSAGE": _reply_chars_converter,
    "WUWA_MEME_SEARCH_ENABLED": _bool_converter,
    "WUWA_PERSONA_ACTION_BRACKETS": _bool_converter,
}


class RuntimeSettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else None
        self._lock = threading.Lock()
        self._overrides: dict[str, Any] = {}
        self._nicknames: list[str] = []
        self._interactions: dict[str, int] = {}
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        overrides = payload.get("overrides")
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if key in SETTABLE_KEYS and isinstance(value, (str, int, float, bool)):
                    self._overrides[key] = value
        nicknames = payload.get("nicknames")
        if isinstance(nicknames, list):
            self._nicknames = [
                str(item).strip()
                for item in nicknames
                if str(item).strip()
            ]
        interactions = payload.get("interactions")
        if isinstance(interactions, dict):
            self._interactions = {
                str(key): int(value)
                for key, value in interactions.items()
                if isinstance(value, int) and value > 0
            }

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "overrides": self._overrides,
                        "nicknames": self._nicknames,
                        "interactions": self._interactions,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    # ---- 参数覆盖 ----

    def list_overrides(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._overrides)

    def set_override(self, key: str, value: str) -> Any:
        normalized_key = key.strip().upper()
        if normalized_key not in SETTABLE_KEYS:
            raise ValueError(
                f"不支持运行时修改的键：{normalized_key}。"
                f"可用键：{','.join(sorted(SETTABLE_KEYS))}"
            )
        converted = SETTABLE_KEYS[normalized_key](value.strip())
        with self._lock:
            self._overrides[normalized_key] = converted
            self._save()
        return converted

    def reset_override(self, key: str | None = None) -> int:
        with self._lock:
            if key is None:
                count = len(self._overrides)
                self._overrides = {}
                self._save()
                return count
            normalized_key = key.strip().upper()
            if normalized_key in self._overrides:
                del self._overrides[normalized_key]
                self._save()
                return 1
            return 0

    def get(self, key: str, config: object) -> Any:
        normalized_key = key.strip().upper()
        with self._lock:
            if normalized_key in self._overrides:
                return self._overrides[normalized_key]
        return getattr(config, normalized_key.lower(), None)

    def get_or(self, key: str, default: Any) -> Any:
        normalized_key = key.strip().upper()
        with self._lock:
            if normalized_key in self._overrides:
                return self._overrides[normalized_key]
        return default

    def get_bool(self, key: str, config: object, default: bool = False) -> bool:
        value = self.get(key, config)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return _bool_converter(value)
            except ValueError:
                return default
        return bool(value)

    # ---- 昵称 ----

    def list_nicknames(self) -> list[str]:
        with self._lock:
            return list(self._nicknames)

    def add_nickname(self, nickname: str) -> bool:
        cleaned = nickname.strip()
        if not cleaned or len(cleaned) > 12:
            raise ValueError("昵称不能为空且长度不超过 12 个字符")
        with self._lock:
            if cleaned in self._nicknames:
                return False
            self._nicknames.append(cleaned)
            self._save()
        return True

    def remove_nickname(self, nickname: str) -> bool:
        cleaned = nickname.strip()
        with self._lock:
            if cleaned not in self._nicknames:
                return False
            self._nicknames.remove(cleaned)
            self._save()
        return True

    # ---- 互动计数 ----

    def interaction_increment(self, sender_id: str) -> int:
        with self._lock:
            count = self._interactions.get(sender_id, 0) + 1
            self._interactions[sender_id] = count
            self._save()
        return count

    def interaction_count(self, sender_id: str) -> int:
        with self._lock:
            return self._interactions.get(sender_id, 0)

    def list_interaction_senders(self) -> list[str]:
        with self._lock:
            return list(self._interactions.keys())


def build_runtime_settings_store(config: object) -> RuntimeSettingsStore:
    path = str(getattr(config, "wuwa_runtime_settings_file", "")).strip()
    return RuntimeSettingsStore(path or None)
