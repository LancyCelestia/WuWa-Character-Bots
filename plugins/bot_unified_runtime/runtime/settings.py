"""运行时设置存储：管理员在对话里可调整的参数与昵称。

- 覆盖项只支持白名单键（防止任意配置注入），存 ``data/runtime_settings.json``
  （git 忽略），重启后保留。
- 昵称列表（多昵称）同样存这里，供命令别名解析器读取。
- 互动计数按 sender_id 累计，供关系层级自动升级使用。
- 线程安全（锁）；文件损坏时安全降级为空存储。

管理员专属指令走统一流水线（`bot.runtime` 能力），只允许
``BOT_ADMIN_USER_IDS`` 中的管理员执行。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

# 互动次数 -> 自动关系层级（档案未显式指定 familiarity 时生效）。
FAMILIAR_INTERACTION_THRESHOLD = 8
CLOSE_INTERACTION_THRESHOLD = 30


def _temperature_converter(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 2.0:
        raise ValueError("BOT_CHAT_TEMPERATURE 必须在 0.0-2.0 之间")
    return parsed


def _max_tokens_converter(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError("BOT_CHAT_MAX_TOKENS 必须 >= 0（0 = 不设上限）")
    return parsed


def _model_converter(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 64:
        raise ValueError("BOT_CHAT_MODEL 不能为空且长度不超过 64 个字符")
    return cleaned


def _reply_chars_converter(value: str) -> int:
    parsed = int(value)
    if parsed < 200:
        raise ValueError("BOT_REPLY_MAX_CHARS_PER_MESSAGE 必须 >= 200")
    return parsed


_MUSIC_MODE_ALIASES = {
    "audio": "audio",
    "file": "audio",
    "音频": "audio",
    "音频文件": "audio",
    "voice": "voice",
    "语音": "voice",
    "link": "link",
    "链接": "link",
    "card": "card",
    "卡片": "card",
    "default": "card",
    "默认": "card",
}


def _reply_detail_converter(value: str) -> str:
    normalized = (value or "").strip().lower()
    aliases = {
        "详细": "detail", "科普": "detail", "详尽": "detail", "detail": "detail",
        "精简": "concise", "简洁": "concise", "brief": "concise", "concise": "concise",
        "默认": "auto", "自动": "auto", "auto": "auto",
    }
    if normalized not in aliases:
        raise ValueError("BOT_REPLY_DETAIL 必须是 详细/精简/默认")
    return aliases[normalized]


def _music_mode_converter(value: str) -> str:
    normalized = _MUSIC_MODE_ALIASES.get((value or "").strip().lower())
    if normalized is None:
        raise ValueError("BOT_MUSIC_MODE 必须是 音频/语音/链接/卡片")
    return normalized


def _bool_converter(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on", "开", "是"}:
        return True
    if normalized in {"false", "0", "no", "off", "关", "否"}:
        return False
    raise ValueError("布尔值必须是 true/false（或 开/关）")


# 白名单键 -> 转换函数；转换失败抛 ValueError，不会写入。
SETTABLE_KEYS: dict[str, Callable[[str], Any]] = {
    "BOT_CHAT_TEMPERATURE": _temperature_converter,
    "BOT_CHAT_MAX_TOKENS": _max_tokens_converter,
    "BOT_CHAT_MODEL": _model_converter,
    "BOT_REPLY_MAX_CHARS_PER_MESSAGE": _reply_chars_converter,
    "BOT_MEME_SEARCH_ENABLED": _bool_converter,
    "BOT_PERSONA_ACTION_BRACKETS": _bool_converter,
    "BOT_MUSIC_MODE": _music_mode_converter,
    "BOT_REPLY_DETAIL": _reply_detail_converter,
}


class RuntimeSettingsStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        instance: str = "default",
    ) -> None:
        self.instance = instance
        self.path = Path(path).expanduser() if path else None
        self._lock = threading.Lock()
        self._overrides: dict[str, Any] = {}
        self._nicknames: list[str] = []
        self._interactions: dict[str, int] = {}
        self._persona_override: str = ""
        self._persona_weights: dict[str, float] = {}
        self._mtime: float = 0.0
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            self._mtime = self.path.stat().st_mtime
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
        persona_override = payload.get("persona_override")
        if isinstance(persona_override, str):
            self._persona_override = persona_override.strip()
        persona_weights = payload.get("persona_weights")
        if isinstance(persona_weights, dict):
            self._persona_weights = {
                str(key): float(value)
                for key, value in persona_weights.items()
                if isinstance(value, (int, float))
            }

    def _reload_if_changed(self) -> None:
        """文件被其他进程（例如管理员命令）修改后，本进程读时自动刷新。"""
        if not self.path or not self.path.exists():
            return
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return
        if mtime != self._mtime:
            self._load()

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
                        "persona_override": self._persona_override,
                        "persona_weights": self._persona_weights,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._mtime = self.path.stat().st_mtime
        except OSError:
            return

    # ---- 参数覆盖 ----

    def list_overrides(self) -> dict[str, Any]:
        with self._lock:
            self._reload_if_changed()
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
            self._reload_if_changed()
            self._overrides[normalized_key] = converted
            self._save()
        return converted

    def reset_override(self, key: str | None = None) -> int:
        with self._lock:
            self._reload_if_changed()
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
            self._reload_if_changed()
            if normalized_key in self._overrides:
                return self._overrides[normalized_key]
        return getattr(config, normalized_key.lower(), None)

    def get_or(self, key: str, default: Any) -> Any:
        normalized_key = key.strip().upper()
        with self._lock:
            self._reload_if_changed()
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
            self._reload_if_changed()
            return list(self._nicknames)

    def add_nickname(self, nickname: str) -> bool:
        cleaned = nickname.strip()
        if not cleaned or len(cleaned) > 12:
            raise ValueError("昵称不能为空且长度不超过 12 个字符")
        with self._lock:
            self._reload_if_changed()
            if cleaned in self._nicknames:
                return False
            self._nicknames.append(cleaned)
            self._save()
        return True

    def remove_nickname(self, nickname: str) -> bool:
        cleaned = nickname.strip()
        with self._lock:
            self._reload_if_changed()
            if cleaned not in self._nicknames:
                return False
            self._nicknames.remove(cleaned)
            self._save()
        return True

    # ---- 互动计数 ----

    def interaction_increment(self, sender_id: str) -> int:
        with self._lock:
            self._reload_if_changed()
            count = self._interactions.get(sender_id, 0) + 1
            self._interactions[sender_id] = count
            self._save()
        return count

    def interaction_count(self, sender_id: str) -> int:
        with self._lock:
            self._reload_if_changed()
            return self._interactions.get(sender_id, 0)

    def list_interaction_senders(self) -> list[str]:
        with self._lock:
            self._reload_if_changed()
            return list(self._interactions.keys())

    # ---- 人格切换 ----

    def get_persona_override(self) -> str:
        with self._lock:
            self._reload_if_changed()
            return self._persona_override

    def set_persona_override(self, profile_id: str) -> None:
        with self._lock:
            self._reload_if_changed()
            self._persona_override = (profile_id or "").strip()
            self._save()

    def get_persona_weights(self) -> dict[str, float]:
        with self._lock:
            self._reload_if_changed()
            return dict(self._persona_weights)

    def set_persona_weight(self, profile_id: str, weight: float) -> None:
        cleaned = (profile_id or "").strip()
        if not cleaned:
            raise ValueError("人格 id 不能为空")
        normalized = max(0.0, min(1.0, float(weight)))
        with self._lock:
            self._reload_if_changed()
            self._persona_weights[cleaned] = normalized
            self._save()


class InstanceSettingsManager:
    """多实例设置管理：每个机器人实例一个设置文件，彼此隔离。

    管理员命令可以通过 ``--instance <名称>`` 定位到其他实例；
    被修改实例的进程会在下次读取时自动刷新（mtime 检测）。
    """

    def __init__(self, settings_dir: str | Path) -> None:
        self.settings_dir = Path(settings_dir).expanduser()
        self._stores: dict[str, RuntimeSettingsStore] = {}
        self._lock = threading.Lock()

    def _path_for(self, instance: str) -> Path:
        safe_instance = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", instance) or "default"
        return self.settings_dir / f"runtime_settings_{safe_instance}.json"

    def get(self, instance: str) -> RuntimeSettingsStore:
        with self._lock:
            if instance not in self._stores:
                self._stores[instance] = RuntimeSettingsStore(
                    self._path_for(instance),
                    instance=instance,
                )
            return self._stores[instance]

    def list_instances(self) -> list[str]:
        if not self.settings_dir.exists():
            return []
        return sorted(
            path.stem.removeprefix("runtime_settings_")
            for path in self.settings_dir.glob("runtime_settings_*.json")
        )


def effective_instance(config: object) -> str:
    """实例自举：未显式配置实例时自动取人格 id（守岸人 → shorekeeper）。"""
    instance = str(getattr(config, "bot_runtime_instance", "")).strip()
    if instance:
        return instance
    persona = str(getattr(config, "bot_persona_profile_id", "default")).strip()
    return persona or "default"


def build_runtime_settings_store(config: object) -> RuntimeSettingsStore:
    manager = InstanceSettingsManager(
        str(getattr(config, "bot_runtime_settings_dir", "data/settings")).strip()
        or "data/settings"
    )
    return manager.get(effective_instance(config))


def build_instance_settings_manager(config: object) -> InstanceSettingsManager:
    return InstanceSettingsManager(
        str(getattr(config, "bot_runtime_settings_dir", "data/settings")).strip()
        or "data/settings"
    )
