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
import math
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    if parsed < 0 or parsed > 65538:
        raise ValueError("BOT_CHAT_MAX_TOKENS 必须在 0..65538（0 = 不设上限）")
    return parsed


def _transport_timeout_converter(value: str) -> float:
    """发送层硬超时（秒）：拒绝负数/NaN/Infinity/超大值，合法范围 (0, 600]。"""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 不能为空")
    try:
        number = float(raw)
    except ValueError as exc:
        raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 必须是数字（秒）") from exc
    if math.isnan(number) or math.isinf(number) or number <= 0 or number > 600:
        raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 必须在 0-600 秒之间")
    return number



def _probability_converter(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("概率必须在 0..1 之间")
    return number

def _model_converter(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 64:
        raise ValueError("BOT_CHAT_MODEL 不能为空且长度不超过 64 个字符")
    return cleaned


def _reasoning_effort_converter(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in {"", "off", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError(
            "BOT_CHAT_REASONING_EFFORT 必须是 off/low/medium/high/xhigh/max，留空=各模型家族默认档"
        )
    return normalized


def _model_priority_groups_converter(value: str) -> str:
    """时段优先级分组：接受 JSON 数组字符串；原样存规范化 JSON，路由器负责解析。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            'BOT_MODEL_PRIORITY_GROUPS 必须是 JSON 数组，如 '
            '[{"name":"工作日高峰","days":[1,2,3,4,5],'
            '"windows":[["09:00","12:00"],["14:00","18:00"]],'
            '"order":["aiprc-terra","aiprc-sol"]}]'
        ) from exc
    if not isinstance(parsed, list):
        raise TypeError("BOT_MODEL_PRIORITY_GROUPS 必须是 JSON 数组")
    return json.dumps(parsed, ensure_ascii=False)


def _model_prices_converter(value: str) -> str:
    """每模型价格表：接受 JSON 对象字符串；单位=元/每百万 token。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            'BOT_MODEL_PRICES 必须是 JSON 对象，如 '
            '{"deepseek-v4-pro":{"input":4.0,"output":16.0}}'
        ) from exc
    if not isinstance(parsed, dict):
        raise TypeError("BOT_MODEL_PRICES 必须是 JSON 对象")
    return json.dumps(parsed, ensure_ascii=False)


def _vision_mode_converter(value: str) -> str:
    normalized = (value or "relay").strip().lower()
    if normalized not in {"relay", "direct"}:
        raise ValueError("BOT_VISION_MODE 必须是 relay/direct")
    return normalized


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


# 群聊回复策略四档键：运行时热改项（覆盖值存 list[str]）。
GROUP_POLICY_KEYS = frozenset({
    "BOT_GROUP_BLACK1",
    "BOT_GROUP_BLACK2",
    "BOT_GROUP_WHITE1",
    "BOT_GROUP_WHITE2",
})

# 档位别名（英文大小写不敏感 + 简繁中文 + 编号变体） -> 规范键名。
GROUP_POLICY_MODE_ALIASES = {
    "black1": "BOT_GROUP_BLACK1",
    "black_1": "BOT_GROUP_BLACK1",
    "blacklist1": "BOT_GROUP_BLACK1",
    "黑1": "BOT_GROUP_BLACK1",
    "黑一": "BOT_GROUP_BLACK1",
    "黑名单1": "BOT_GROUP_BLACK1",
    "黑名单一": "BOT_GROUP_BLACK1",
    "黑名單1": "BOT_GROUP_BLACK1",
    "黑名單一": "BOT_GROUP_BLACK1",
    "black2": "BOT_GROUP_BLACK2",
    "black_2": "BOT_GROUP_BLACK2",
    "blacklist2": "BOT_GROUP_BLACK2",
    "黑2": "BOT_GROUP_BLACK2",
    "黑二": "BOT_GROUP_BLACK2",
    "黑名单2": "BOT_GROUP_BLACK2",
    "黑名单二": "BOT_GROUP_BLACK2",
    "黑名單2": "BOT_GROUP_BLACK2",
    "黑名單二": "BOT_GROUP_BLACK2",
    "white1": "BOT_GROUP_WHITE1",
    "white_1": "BOT_GROUP_WHITE1",
    "whitelist1": "BOT_GROUP_WHITE1",
    "白1": "BOT_GROUP_WHITE1",
    "白一": "BOT_GROUP_WHITE1",
    "白名单1": "BOT_GROUP_WHITE1",
    "白名单一": "BOT_GROUP_WHITE1",
    "白名單1": "BOT_GROUP_WHITE1",
    "白名單一": "BOT_GROUP_WHITE1",
    "white2": "BOT_GROUP_WHITE2",
    "white_2": "BOT_GROUP_WHITE2",
    "whitelist2": "BOT_GROUP_WHITE2",
    "白2": "BOT_GROUP_WHITE2",
    "白二": "BOT_GROUP_WHITE2",
    "白名单2": "BOT_GROUP_WHITE2",
    "白名单二": "BOT_GROUP_WHITE2",
    "白名單2": "BOT_GROUP_WHITE2",
    "白名單二": "BOT_GROUP_WHITE2",
}


def normalize_group_policy_mode(raw: str) -> str | None:
    """把用户输入的档位别名归一化成规范键名；无法识别返回 None。"""
    normalized = (raw or "").strip().lower()
    return GROUP_POLICY_MODE_ALIASES.get(normalized)


def _group_list_converter(value: str) -> list[str]:
    """群号列表转换：逗号/分号/顿号/空白分隔或 JSON 数组；仅接受数字群号。"""
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise ValueError("群号列表 JSON 解析失败") from exc
        if not isinstance(parsed, list):
            raise ValueError("群号列表 JSON 必须是数组")
        items = [str(item).strip() for item in parsed]
    else:
        items = [part.strip() for part in re.split(r"[;,，、\s]+", raw) if part.strip()]
    cleaned: list[str] = []
    for item in items:
        if not item.isdigit():
            raise ValueError(f"群号必须是数字：{item!r}")
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def _model_schedule_converter(value: str) -> str:
    """分时段模型切换表：接受 JSON 对象字符串或空值；原样存字符串，调度器负责解析。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            'BOT_MODEL_SCHEDULE 必须是 JSON 对象，如 {"23:00-07:00":"luna"}'
        ) from exc
    if not isinstance(parsed, dict):
        raise TypeError("BOT_MODEL_SCHEDULE 必须是 JSON 对象")
    return raw


def _memory_duration_converter(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 3600:
        raise ValueError("记忆抽取时限/冷却必须在 (0,3600] 秒内")
    return number


def _memory_tokens_converter(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 4096:
        raise ValueError("记忆抽取输出上限必须在 1..4096 内")
    return number


# 白名单键 -> 转换函数；转换失败抛 ValueError，不会写入。
SETTABLE_KEYS: dict[str, Callable[[str], Any]] = {
    "BOT_CHAT_TEMPERATURE": _temperature_converter,
    "BOT_CHAT_MAX_TOKENS": _max_tokens_converter,
    "BOT_CHAT_FAST_MODE": _bool_converter,
    "BOT_CHAT_FAST_MAX_TOKENS": _max_tokens_converter,
    "BOT_MEMORY_EXTRACT_ENABLED": _bool_converter,
    "BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS": _memory_duration_converter,
    "BOT_MEMORY_EXTRACT_MAX_TOKENS": _memory_tokens_converter,
    "BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_CHAT_MODEL": _model_converter,
    "BOT_CHAT_REASONING_EFFORT": _reasoning_effort_converter,
    "BOT_TRANSPORT_TIMEOUT_SECONDS": _transport_timeout_converter,
    "BOT_MODEL_SCHEDULE": _model_schedule_converter,
    "BOT_MODEL_PRIORITY_GROUPS": _model_priority_groups_converter,
    "BOT_MODEL_PRICES": _model_prices_converter,
    "BOT_REPLY_MAX_CHARS_PER_MESSAGE": _reply_chars_converter,
    "BOT_MEME_SEARCH_ENABLED": _bool_converter,
    "BOT_WEB_SEARCH_ENABLED": _bool_converter,
    "BOT_WEB_SEARCH_PROVIDER": lambda value: str(value).strip().lower(),
    "BOT_WEB_SEARCH_FALLBACK_PROVIDERS": lambda value: [item.strip().lower() for item in str(value).replace(";", ",").split(",") if item.strip()],

    "BOT_WEB_SEARCH_ADMIN_NOTICE": _bool_converter,
    "BOT_PERSONA_ACTION_BRACKETS": _bool_converter,
    "BOT_MUSIC_MODE": _music_mode_converter,
    "BOT_REPLY_DETAIL": _reply_detail_converter,
    "BOT_VISION_ENABLED": _bool_converter,
    "BOT_VISION_MODE": _vision_mode_converter,
    "BOT_CONTENT_VIDEO_AUTO_SEND": _bool_converter,
    "BOT_POKE_ENABLED": _bool_converter,
    "BOT_POKE_PRIVATE_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_POKE_GROUP_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_POKE_PROBABILITY": _probability_converter,
    "BOT_GROUP_BLACK1": _group_list_converter,
    "BOT_GROUP_BLACK2": _group_list_converter,
    "BOT_GROUP_WHITE1": _group_list_converter,
    "BOT_GROUP_WHITE2": _group_list_converter,
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
        self._model_registry: dict[str, dict[str, Any]] = {}
        self._vision_registry: dict[str, dict[str, Any]] = {}
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
                if key not in SETTABLE_KEYS:
                    continue
                if key in GROUP_POLICY_KEYS and isinstance(value, list):
                    self._overrides[key] = [
                        str(item).strip()
                        for item in value
                        if str(item).strip()
                    ]
                elif isinstance(value, (str, int, float, bool)):
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
        model_registry = payload.get("model_registry")
        if isinstance(model_registry, dict):
            self._model_registry = {
                str(key): dict(item)
                for key, item in model_registry.items()
                if isinstance(item, dict)
            }
        vision_registry = payload.get("vision_registry")
        if isinstance(vision_registry, dict):
            self._vision_registry = {
                str(key): dict(item)
                for key, item in vision_registry.items()
                if isinstance(item, dict)
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
                        "model_registry": self._model_registry,
                        "vision_registry": self._vision_registry,
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

    # ---- 运行时模型注册表（聊天指令自定义供应商/模型/故障转移顺序） ----

    def replace_registry_entries(self, entries: dict[str, dict[str, Any]], *, vision: bool = False) -> None:
        """Publish a full ordering under one lock and persist once."""
        copied = {key: dict(value) for key, value in entries.items()}
        with self._lock:
            self._reload_if_changed()
            if vision:
                self._vision_registry = copied
            else:
                self._model_registry = copied
            self._save()

    def list_model_registry(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._reload_if_changed()
            return {key: dict(item) for key, item in self._model_registry.items()}

    def set_model_entry(self, model_id: str, entry: dict[str, Any]) -> None:
        cleaned = (model_id or "").strip()
        if not cleaned:
            raise ValueError("模型 id 不能为空")
        if not isinstance(entry, dict):
            raise TypeError("模型条目必须是对象")
        with self._lock:
            self._reload_if_changed()
            self._model_registry[cleaned] = dict(entry)
            self._save()

    def remove_model_entry(self, model_id: str) -> bool:
        cleaned = (model_id or "").strip()
        with self._lock:
            self._reload_if_changed()
            if cleaned not in self._model_registry:
                return False
            del self._model_registry[cleaned]
            self._save()
            return True

    # ---- 运行时视觉模型注册表（图片识别供应商） ----

    def list_vision_registry(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._reload_if_changed()
            return {key: dict(item) for key, item in self._vision_registry.items()}

    def set_vision_entry(self, model_id: str, entry: dict[str, Any]) -> None:
        cleaned = (model_id or "").strip()
        if not cleaned:
            raise ValueError("视觉模型 id 不能为空")
        if not isinstance(entry, dict):
            raise TypeError("视觉模型条目必须是对象")
        with self._lock:
            self._reload_if_changed()
            self._vision_registry[cleaned] = dict(entry)
            self._save()

    def remove_vision_entry(self, model_id: str) -> bool:
        cleaned = (model_id or "").strip()
        with self._lock:
            self._reload_if_changed()
            if cleaned not in self._vision_registry:
                return False
            del self._vision_registry[cleaned]
            self._save()
            return True


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
