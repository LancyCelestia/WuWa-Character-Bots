from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, field_validator


def translate_env_keys(values: dict[str, Any]) -> dict[str, Any]:
    """把通识化环境变量键（BOT_*）翻译回内部字段名（wuwa_*）。

    兼容旧的 WUWA_* 写法（translate 后两者等价）；Config 字段名保持
    内部命名，对外只暴露 BOT_*。
    """
    translated: dict[str, Any] = {}
    for key, value in values.items():
        lowered = str(key).lower()
        if lowered.startswith("bot_"):
            translated[f"wuwa_{lowered[4:]}"] = value
        else:
            translated[lowered] = value
    return translated


class Config(BaseModel):
    wuwa_runtime_enabled: bool = True
    wuwa_runtime_default_persona: str = "default"
    wuwa_runtime_group_command_prefix: str = "/bot"
    wuwa_runtime_admin_prefix: str = "/bot"
    wuwa_runtime_instance: str = "default"
    wuwa_runtime_persona_nickname: str = ""
    wuwa_runtime_persona_nicknames: list[str] = []
    wuwa_runtime_alias_enabled: bool = True
    wuwa_runtime_settings_file: str = "data/runtime_settings.json"
    wuwa_runtime_settings_dir: str = "data/settings"
    wuwa_shared_export_enabled: bool = False
    wuwa_shared_export_include_private: bool = False
    wuwa_shared_export_max_chars: int = 200
    wuwa_admin_user_ids: list[str] = []
    wuwa_enterprise_user_ids: list[str] = []
    wuwa_trusted_user_ids: list[str] = []
    wuwa_blocked_user_ids: list[str] = []
    wuwa_persona_profile_id: str = "default"
    wuwa_persona_display_name: str = "报存"
    wuwa_persona_version: str = "0"
    wuwa_persona_files: list[str] = []
    # 人格级昵称（本机器人的角色昵称，随人格走，不随平台走）。
    wuwa_persona_nicknames: list[str] = []
    # 备用人格：{"gentle": {"display_name": "...", "files": [...],
    #   "weight": 0.3, "emotions": ["support_needed", ...]}, ...}
    wuwa_persona_alt_profiles: dict[str, dict[str, Any]] = {}
    wuwa_knowledge_files: list[str] = []
    wuwa_knowledge_max_chunks: int = 4
    wuwa_knowledge_chunk_chars: int = 900
    wuwa_tone_mode: str = "private_chat"
    wuwa_tone_voice: str = "soft"
    wuwa_tone_warmth: float = 0.7
    wuwa_tone_directness: float = 0.5
    wuwa_tone_message_count_limit: int = 1
    wuwa_memory_enabled: bool = False
    wuwa_memory_db_path: str = ""
    wuwa_memory_max_items: int = 5
    wuwa_memory_max_chars: int = 1200
    wuwa_history_enabled: bool = False
    wuwa_history_db_path: str = ""
    wuwa_history_max_turns: int = 6
    wuwa_history_max_chars: int = 1600
    wuwa_history_max_items: int = 1000
    wuwa_diagnostics_enabled: bool = False
    wuwa_diagnostics_db_path: str = ""
    wuwa_diagnostics_max_items: int = 100
    wuwa_audit_enabled: bool = False
    wuwa_audit_db_path: str = ""
    wuwa_audit_max_items: int = 1000
    wuwa_receipts_enabled: bool = False
    wuwa_receipts_db_path: str = ""
    wuwa_receipts_max_items: int = 1000
    wuwa_send_queue_enabled: bool = False
    wuwa_send_queue_db_path: str = ""
    wuwa_send_queue_max_items: int = 1000
    wuwa_send_queue_max_attempts: int = 3
    wuwa_send_queue_retry_base_seconds: int = 30
    wuwa_send_queue_retry_max_seconds: int = 300
    wuwa_send_queue_worker_enabled: bool = False
    wuwa_send_queue_worker_interval_seconds: int = 30
    wuwa_send_queue_worker_batch_size: int = 20
    wuwa_emotion_enabled: bool = True
    wuwa_emotion_max_signals: int = 4
    wuwa_trend_enabled: bool = False
    wuwa_trend_files: list[str] = []
    wuwa_trend_max_notes: int = 5
    wuwa_trend_max_chars: int = 500
    wuwa_trend_max_age_days: int = 14
    wuwa_temporal_enabled: bool = True
    wuwa_timezone: str = "Asia/Hong_Kong"
    wuwa_weather_enabled: bool = False
    wuwa_weather_latitude: float = 0.0
    wuwa_weather_longitude: float = 0.0
    wuwa_weather_cache_seconds: int = 1800
    wuwa_weather_timeout_seconds: float = 8.0
    wuwa_holidays_file: str = ""
    wuwa_persona_action_brackets: bool = True
    wuwa_credentials_file: str = ""
    wuwa_credential_warn_days: int = 7
    wuwa_credential_probe_urls: dict[str, str] = {}
    wuwa_credential_probe_timeout_seconds: float = 8.0
    wuwa_credential_check_enabled: bool = False
    wuwa_credential_check_interval_hours: int = 6
    wuwa_glossary_files: list[str] = []
    wuwa_glossary_max_entries: int = 30
    wuwa_glossary_max_chars: int = 1500
    wuwa_user_profiles_file: str = ""
    wuwa_shared_group_context_enabled: bool = False
    wuwa_group_digest_enabled: bool = False
    wuwa_group_digest_max_turns: int = 150
    wuwa_group_digest_max_chars: int = 800
    wuwa_group_digest_llm_enabled: bool = False
    wuwa_group_digest_llm_ttl_seconds: int = 3600
    wuwa_meme_search_enabled: bool = False
    wuwa_meme_search_timeout_seconds: float = 8.0
    wuwa_meme_search_cache_seconds: int = 600
    wuwa_render_forward_min_chars: int = 1500
    wuwa_render_forward_max_nodes: int = 6
    wuwa_render_forward_node_chars: int = 900
    wuwa_audit_log_file: str = ""
    wuwa_audit_log_max_bytes: int = 2097152
    wuwa_chat_enabled: bool = True
    wuwa_chat_provider: str = "static"
    wuwa_chat_model: str = "static"
    wuwa_chat_api_key: str = ""
    wuwa_chat_base_url: str = "https://api.openai.com/v1"
    wuwa_chat_temperature: float = 0.7
    wuwa_chat_max_tokens: int = 512
    wuwa_chat_timeout_seconds: float = 30.0
    wuwa_reply_private_default_max_messages: int = 1
    wuwa_reply_private_support_max_messages: int = 2
    wuwa_reply_private_deep_help_max_messages: int = 3
    wuwa_reply_group_max_messages: int = 1
    wuwa_reply_risk_max_messages: int = 1
    wuwa_reply_max_chars_per_message: int = 1200
    wuwa_reply_default_context_budget: int = 2048
    wuwa_reply_support_context_budget: int = 2560
    wuwa_reply_deep_help_context_budget: int = 3072
    wuwa_reply_group_context_budget: int = 2048
    wuwa_rate_limit_enabled: bool = True
    wuwa_rate_limit_window_seconds: int = 60
    wuwa_rate_limit_chat_global_max_requests: int = 60
    wuwa_rate_limit_chat_session_max_requests: int = 6
    wuwa_rate_limit_chat_sender_max_requests: int = 4
    wuwa_rate_limit_target_min_interval_seconds: int = 0
    wuwa_rate_limit_bypass_roles: list[str] = ["admin"]
    wuwa_rate_limit_db_path: str = ""
    wuwa_quiet_hours_enabled: bool = False
    wuwa_quiet_hours_start: str = "23:00"
    wuwa_quiet_hours_end: str = "07:00"
    wuwa_quiet_hours_timezone: str = "Asia/Hong_Kong"
    wuwa_quiet_hours_session_types: list[str] = ["group"]
    wuwa_quiet_hours_bypass_roles: list[str] = ["admin"]

    @field_validator(
        "wuwa_persona_files",
        "wuwa_knowledge_files",
        "wuwa_trend_files",
        "wuwa_glossary_files",
        "wuwa_runtime_persona_nicknames",
        "wuwa_persona_nicknames",
        mode="before",
    )
    @classmethod
    def _parse_file_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("file list JSON must be an array")
                return [str(item) for item in parsed]
            return [item.strip() for item in stripped.split(";") if item.strip()]
        raise TypeError("file list must be a list, JSON array string, or semicolon string")

    @field_validator(
        "wuwa_admin_user_ids",
        "wuwa_enterprise_user_ids",
        "wuwa_trusted_user_ids",
        "wuwa_blocked_user_ids",
        mode="before",
    )
    @classmethod
    def _parse_id_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("id list JSON must be an array")
                return [str(item).strip() for item in parsed if str(item).strip()]
            normalized = stripped.replace(",", ";")
            return [item.strip() for item in normalized.split(";") if item.strip()]
        raise TypeError("id list must be a list, JSON array string, or delimiter string")

    @field_validator("wuwa_persona_alt_profiles", mode="before")
    @classmethod
    def _parse_alt_profiles(cls, value: Any) -> dict[str, dict[str, Any]]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {
                str(key): item if isinstance(item, dict) else {}
                for key, item in value.items()
            }
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return {}
            if isinstance(parsed, dict):
                return {
                    str(key): item if isinstance(item, dict) else {}
                    for key, item in parsed.items()
                }
        return {}

    @field_validator("wuwa_credential_probe_urls", mode="before")
    @classmethod
    def _parse_probe_urls(cls, value: Any) -> dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return {}
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        return {}

    @field_validator(
        "wuwa_rate_limit_bypass_roles",
        "wuwa_quiet_hours_session_types",
        "wuwa_quiet_hours_bypass_roles",
        mode="before",
    )
    @classmethod
    def _parse_role_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("role list JSON must be an array")
                return [str(item).strip() for item in parsed if str(item).strip()]
            normalized = stripped.replace(",", ";")
            return [item.strip() for item in normalized.split(";") if item.strip()]
        raise TypeError("role list must be a list, JSON array string, or delimiter string")
