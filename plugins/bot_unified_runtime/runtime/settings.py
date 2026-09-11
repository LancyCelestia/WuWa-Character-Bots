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
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

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


def _non_negative_int_converter(value: str) -> int:
    number = int(str(value).strip() or "0")
    if number < 0:
        raise ValueError("该参数不能为负数")
    return number


def _clock_converter(value: str) -> str:
    """HH:MM 时刻（安静时间窗口端点）。"""
    raw = str(value).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", raw):
        raise ValueError("时间格式必须是 HH:MM，例如 00:00 或 07:00")
    hour, minute = (int(part) for part in raw.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间超出范围（小时 0-23、分钟 0-59）")
    return f"{hour:02d}:{minute:02d}"


def _timezone_converter(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError("时区不能为空，例如 Asia/Hong_Kong")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(raw)
    except Exception as exc:
        raise ValueError(f"无效时区：{raw}") from exc
    return raw


def _session_types_converter(value: str) -> list[str]:
    items = [item.strip().lower() for item in re.split(r"[,\s;]+", str(value)) if item.strip()]
    allowed = {"group", "private", "email"}
    invalid = [item for item in items if item not in allowed]
    if invalid:
        raise ValueError(f"会话类型只能是 {sorted(allowed)}，收到 {invalid}")
    return items


def _role_list_converter(value: str) -> list[str]:
    return [item.strip().lower() for item in re.split(r"[,\s;]+", str(value)) if item.strip()]


def _digest_list_mode_converter(value: str) -> str:
    raw = str(value).strip().lower()
    if raw not in {"whitelist", "blacklist", "off", "all"}:
        raise ValueError("群摘要名单模式只能是 whitelist|blacklist|off|all")
    return raw


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
    "BOT_ASR_ENABLED": _bool_converter,
    "BOT_VIDEO_UNDERSTANDING_ENABLED": _bool_converter,
    "BOT_VIDEO_MAX_FRAMES": lambda value: max(1, int(str(value).strip() or "1")),
    "BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE": _bool_converter,
    "BOT_VIDEO_PROGRESS_ACK_ENABLED": _bool_converter,
    "BOT_VIDEO_FUZZY_FOLLOWUP": _bool_converter,
    "BOT_VIDEO_DEEP_ENABLED": _bool_converter,
    "BOT_VIDEO_NATIVE_INPUT": _bool_converter,
    "BOT_CONTENT_VIDEO_AUTO_SEND": _bool_converter,
    "BOT_POKE_ENABLED": _bool_converter,
    "BOT_POKE_PRIVATE_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_POKE_GROUP_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_POKE_PROBABILITY": _probability_converter,
    # B10 统一戳一戳分发：回戳/话术开关与文案（消费点 capabilities.poke.PokeDispatcher）。
    "BOT_POKE_REPLY_ENABLED": _bool_converter,
    "BOT_POKE_POKE_BACK": _bool_converter,
    "BOT_POKE_GROUP_TEXT": lambda value: str(value),
    "BOT_POKE_PRIVATE_TEXT": lambda value: str(value),
    "BOT_GROUP_BLACK1": _group_list_converter,
    "BOT_GROUP_BLACK2": _group_list_converter,
    "BOT_GROUP_WHITE1": _group_list_converter,
    "BOT_GROUP_WHITE2": _group_list_converter,
    # ---- 本轮新增：这些键此前只能写 .env，改一次就要动整个 .env，且极易与
    # 实际生效值漂移（用户实测反馈：.env 写 gpt-5.6-terra、实际跑的是
    # qian-night-gemini；群名单两处不一致）。纳入运行时 store 后，
    # /bot runtime set 即可热改，且只有一处真相。
    "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED": _bool_converter,
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY": _probability_converter,
    "BOT_QUIET_HOURS_ENABLED": _bool_converter,
    "BOT_QUIET_HOURS_START": _clock_converter,
    "BOT_QUIET_HOURS_END": _clock_converter,
    "BOT_QUIET_HOURS_TIMEZONE": _timezone_converter,
    "BOT_QUIET_HOURS_SESSION_TYPES": _session_types_converter,
    "BOT_QUIET_HOURS_BYPASS_ROLES": _role_list_converter,
    "BOT_SHARED_GROUP_CONTEXT_ENABLED": _bool_converter,
    "BOT_GROUP_DIGEST_LIST_MODE": _digest_list_mode_converter,
    "BOT_GROUP_DIGEST_WHITELIST": _group_list_converter,
    "BOT_GROUP_DIGEST_BLACKLIST": _group_list_converter,
    "BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS": _memory_duration_converter,
    "BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR": lambda value: max(
        0, int(str(value).strip() or "0")
    ),
    "BOT_RENDER_FORWARD_MIN_NODES": lambda value: max(0, int(str(value).strip() or "0")),
    "BOT_RENDER_FORWARD_MIN_CHARS": lambda value: max(0, int(str(value).strip() or "0")),
    "BOT_RENDER_FORWARD_MAX_NODES": lambda value: max(0, int(str(value).strip() or "0")),
    "BOT_RENDER_FORWARD_NODE_CHARS": lambda value: max(200, int(str(value).strip() or "900")),
    "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR": _non_negative_int_converter,
    "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE": _non_negative_int_converter,
    "BOT_RATE_LIMIT_EMOTION_EXEMPT": _bool_converter,
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
        # RLock：mutator 持锁调用 _save，_save 内通知监听时需再次判锁。
        self._lock = threading.RLock()
        self._change_listeners: list[Callable[[], None]] = []
        self._overrides: dict[str, Any] = {}
        self._nicknames: list[str] = []
        self._interactions: dict[str, int] = {}
        self._persona_override: str = ""
        self._persona_weights: dict[str, float] = {}
        self._model_registry: dict[str, dict[str, Any]] = {}
        self._vision_registry: dict[str, dict[str, Any]] = {}
        self._mtime: float = 0.0
        # 互动计数写盘节流：每条聊天回复都会 +1，若每次都全量重写整个
        # settings JSON，纯属性能摩擦。内存即时生效，落盘按最小间隔节流；
        # 其他 mutator 的 _save 是全量转储，顺带把未落盘的计数一并写掉。
        # 代价：进程崩溃最多丢最近 30 秒的互动计数（纯统计，可接受）。
        self._last_interaction_save = 0.0
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            self._mtime = self.path.stat().st_mtime
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            payload = json.loads(raw_text)
        except ValueError as exc:
            # 文件损坏（截断/写坏）时保留现场并改名，绝不让下次 _save
            # 把损坏内容静默覆盖成空态（否则历史覆盖项/计数被永久清零）。
            _logger.warning(
                "runtime settings file is corrupt; preserving as *.corrupt: %s (%s)",
                self.path.name,
                exc,
            )
            self._quarantine_corrupt_file()
            self._mtime = 0.0
            return
        if not isinstance(payload, dict):
            _logger.warning(
                "runtime settings file is not a JSON object; preserving as *.corrupt: %s",
                self.path.name,
            )
            self._quarantine_corrupt_file()
            self._mtime = 0.0
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
            # 按键 max 合并：本进程可能有未落盘的新计数（写盘节流 30s），
            # 外部修改触发的重载不能把内存计数整体替换掉。
            for key, value in interactions.items():
                if isinstance(value, int) and value > 0:
                    normalized_key = str(key)
                    self._interactions[normalized_key] = max(
                        self._interactions.get(normalized_key, 0), value
                    )
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

    def _quarantine_corrupt_file(self) -> None:
        """把损坏的设置文件改名保留（.corrupt-<时间戳>）；失败则原地不动。"""
        if self.path is None:
            return
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            quarantined = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            os.replace(self.path, quarantined)
        except OSError:
            return

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

    def register_change_listener(self, callback: Callable[[], None]) -> None:
        """注册设置变更监听（持久化保存时触发；路由缓存等用）。"""
        with self._lock:
            self._change_listeners.append(callback)

    def _save(self) -> None:
        # 通知放在持久化之前：即使写盘失败（OSError 提前返回），
        # 内存中的覆盖也已生效，监听方（路由缓存）必须失效。
        with self._lock:
            listeners = list(self._change_listeners)
        for callback in listeners:
            try:
                callback()
            except Exception:  # noqa: BLE001, S110 - 监听失败不影响设置保存。
                pass
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 临时文件 + os.replace 原子落盘：进程中途被杀/磁盘满时不会留下
            # 半截 JSON（写坏一次会让下次 _load 走空态，历史设置被清零）。
            temp_path = self.path.with_name(f"{self.path.name}.tmp")
            temp_path.write_text(
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
            os.replace(temp_path, self.path)
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
            now = time.monotonic()
            if now - self._last_interaction_save >= 30.0:
                self._last_interaction_save = now
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
        return self.settings_dir / f"runtime_settings_{self._safe_name(instance)}.json"

    @staticmethod
    def _safe_name(instance: str) -> str:
        return re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", instance) or "default"

    def get(self, instance: str) -> RuntimeSettingsStore:
        # 缓存键必须用清洗后的名字：原名 "a/b" 与 "a b" 会映射到同一个
        # 设置文件，若按原名缓存会出现两个互不知晓的 store 共写同一文件
        # （内存计数互相覆盖、变更监听各自为政）。
        safe_instance = self._safe_name(instance)
        with self._lock:
            if safe_instance not in self._stores:
                self._stores[safe_instance] = RuntimeSettingsStore(
                    self._path_for(safe_instance),
                    instance=instance,
                )
            return self._stores[safe_instance]

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
    return build_instance_settings_manager(config).get(effective_instance(config))


# 进程级缓存：同一 settings_dir 共享同一 manager/store。此前每次调用新建
# store，同一设置文件在进程内出现多个互不知晓的实例（变更监听、内存中的
# interactions 计数各自为政）；共享后「保存→监听（路由缓存失效）」链路才
# 对所有调用方一致生效。
_MANAGER_CACHE: dict[str, InstanceSettingsManager] = {}
_MANAGER_CACHE_LOCK = threading.Lock()


def build_instance_settings_manager(config: object) -> InstanceSettingsManager:
    settings_dir = (
        str(getattr(config, "bot_runtime_settings_dir", "data/settings")).strip()
        or "data/settings"
    )
    with _MANAGER_CACHE_LOCK:
        manager = _MANAGER_CACHE.get(settings_dir)
        if manager is None:
            manager = InstanceSettingsManager(settings_dir)
            _MANAGER_CACHE[settings_dir] = manager
        return manager
