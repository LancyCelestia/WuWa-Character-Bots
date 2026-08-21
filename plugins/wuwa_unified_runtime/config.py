from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, field_validator


class Config(BaseModel):
    wuwa_runtime_enabled: bool = True
    wuwa_runtime_default_persona: str = "default"
    wuwa_runtime_group_command_prefix: str = "/wuwa"
    wuwa_runtime_persona_nickname: str = ""
    wuwa_runtime_alias_enabled: bool = True
    wuwa_admin_user_ids: list[str] = []
    wuwa_enterprise_user_ids: list[str] = []
    wuwa_trusted_user_ids: list[str] = []
    wuwa_blocked_user_ids: list[str] = []
    wuwa_persona_profile_id: str = "default"
    wuwa_persona_display_name: str = "报存"
    wuwa_persona_version: str = "0"
    wuwa_persona_files: list[str] = []
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
