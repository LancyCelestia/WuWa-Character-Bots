from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, field_validator


def translate_env_keys(values: dict[str, Any]) -> dict[str, Any]:
    """把环境变量键规范化成内部字段名。

    BOT_* 与内部字段一一对应；历史上曾兼容 BOT_* -> bot_* 双写，
    现在两者一致，本函数保持幂等并统一小写，便于直接
    ``Config.model_validate``。
    """
    translated: dict[str, Any] = {}
    for key, value in values.items():
        lowered = str(key).lower()
        if lowered.startswith("bot_"):
            translated[f"bot_{lowered[4:]}"] = value
        else:
            translated[lowered] = value
    return translated


class Config(BaseModel):
    bot_runtime_enabled: bool = True
    bot_runtime_default_persona: str = "default"
    bot_runtime_group_command_prefix: str = "/bot"
    bot_runtime_admin_prefix: str = "/bot"
    bot_runtime_instance: str = "default"
    bot_runtime_persona_nickname: str = ""
    bot_runtime_persona_nicknames: list[str] = []
    bot_runtime_alias_enabled: bool = True
    bot_runtime_settings_file: str = "data/runtime_settings.json"
    bot_runtime_settings_dir: str = "data/settings"
    bot_shared_export_enabled: bool = False
    bot_shared_export_include_private: bool = False
    bot_shared_export_max_chars: int = 200
    bot_gscore_enabled: bool = False
    bot_gscore_host: str = "127.0.0.1"
    bot_gscore_port: int = 8765
    bot_gscore_ws_token: str = ""
    bot_gscore_max_retry: int = 5
    bot_gscore_bot_id: str = "NoneBot2"
    bot_gscore_bot_self_id: str = ""
    bot_admin_user_ids: list[str] = []
    bot_enterprise_user_ids: list[str] = []
    bot_trusted_user_ids: list[str] = []
    bot_blocked_user_ids: list[str] = []
    bot_persona_profile_id: str = "default"
    bot_persona_display_name: str = "报存"
    bot_persona_version: str = "0"
    bot_persona_files: list[str] = []
    # 人格级昵称（本机器人的角色昵称，随人格走，不随平台走）。
    bot_persona_nicknames: list[str] = []
    # 备用人格：{"gentle": {"display_name": "...", "files": [...],
    #   "weight": 0.3, "emotions": ["support_needed", ...]}, ...}
    bot_persona_alt_profiles: dict[str, dict[str, Any]] = {}
    bot_knowledge_files: list[str] = []
    bot_knowledge_max_chunks: int = 4
    bot_knowledge_chunk_chars: int = 900
    bot_tone_mode: str = "private_chat"
    bot_tone_voice: str = "soft"
    bot_tone_warmth: float = 0.7
    bot_tone_directness: float = 0.5
    bot_tone_message_count_limit: int = 1
    bot_memory_enabled: bool = False
    bot_memory_db_path: str = ""
    bot_memory_max_items: int = 5
    bot_memory_max_chars: int = 1200
    bot_history_enabled: bool = False
    bot_history_db_path: str = ""
    bot_history_max_turns: int = 6
    bot_history_max_chars: int = 1600
    bot_history_max_items: int = 1000
    bot_diagnostics_enabled: bool = False
    bot_diagnostics_db_path: str = ""
    bot_diagnostics_max_items: int = 100
    bot_audit_enabled: bool = False
    bot_audit_db_path: str = ""
    bot_audit_max_items: int = 1000
    bot_receipts_enabled: bool = False
    bot_receipts_db_path: str = ""
    bot_receipts_max_items: int = 1000
    bot_send_queue_enabled: bool = False
    bot_send_queue_db_path: str = ""
    bot_send_queue_max_items: int = 1000
    bot_send_queue_max_attempts: int = 3
    bot_send_queue_retry_base_seconds: int = 30
    bot_send_queue_retry_max_seconds: int = 300
    bot_send_queue_worker_enabled: bool = False
    bot_send_queue_worker_interval_seconds: int = 30
    bot_send_queue_worker_batch_size: int = 20
    bot_emotion_enabled: bool = True
    bot_emotion_max_signals: int = 4
    bot_trend_enabled: bool = False
    bot_trend_files: list[str] = []
    bot_trend_max_notes: int = 5
    bot_trend_max_chars: int = 500
    bot_trend_max_age_days: int = 14
    bot_temporal_enabled: bool = True
    bot_timezone: str = "Asia/Hong_Kong"
    bot_weather_enabled: bool = False
    bot_weather_latitude: float = 0.0
    bot_weather_longitude: float = 0.0
    bot_weather_cache_seconds: int = 1800
    bot_weather_timeout_seconds: float = 8.0
    bot_holidays_file: str = ""
    bot_persona_action_brackets: bool = True
    bot_credentials_file: str = ""
    bot_credential_warn_days: int = 7
    bot_credential_probe_urls: dict[str, str] = {}
    bot_credential_probe_timeout_seconds: float = 8.0
    bot_credential_check_enabled: bool = False
    bot_credential_check_interval_hours: int = 6
    bot_glossary_files: list[str] = []
    bot_glossary_max_entries: int = 30
    bot_glossary_max_chars: int = 1500
    bot_user_profiles_file: str = ""
    bot_shared_group_context_enabled: bool = False
    bot_group_digest_enabled: bool = False
    bot_group_digest_max_turns: int = 150
    bot_group_digest_max_chars: int = 800
    bot_group_digest_llm_enabled: bool = False
    bot_group_digest_llm_ttl_seconds: int = 3600
    bot_meme_search_enabled: bool = False
    bot_meme_search_timeout_seconds: float = 8.0
    bot_meme_search_cache_seconds: int = 600
    # 链接解析能力（bot.content）：识别消息里的平台链接 → 解析 → 信息卡。
    bot_content_parse_enabled: bool = True
    # 平台白名单（空=全部）：bilibili, douyin, xiaohongshu, youtube,
    # twitter, xiaoheihe, miyoushe, skland, kurobbs, netease_music,
    # qqmusic, kuwo, kugou, apple_music, spotify
    bot_content_parse_platforms: list[str] = []
    # 点歌能力（bot.music）：『点歌 <关键词>』。
    bot_music_enabled: bool = True
    # 点歌搜索顺序白名单（空=默认顺序：网易云 → Apple → 酷狗 → QQ → 酷我 → Spotify）。
    bot_music_platforms: list[str] = []
    # 解析/点歌请求的统一超时（秒）。
    bot_fetch_timeout_seconds: float = 10.0
    # 平台 Cookie 文件（Netscape 格式，浏览器导出）：给 B站/小红书/抖音/
    # QQ音乐/网易云/推特等解析与点歌加登录态。留空 = 匿名解析。
    bot_cookies_file: str = ""
    # 链接解析历史：默认开启并落盘（data/ 已被 git 忽略）。
    bot_parse_history_enabled: bool = True
    bot_parse_history_db_path: str = "data/parse_history.sqlite3"
    bot_parse_history_max_items: int = 2000
    # 视频下载与媒体分析（yt-dlp）：
    # 解析视频链接时自动附加分辨率/时长/HDR/音频分析；下载走 /bot download。
    bot_media_analyze_enabled: bool = True
    bot_download_dir: str = "data/downloads"
    bot_download_max_bytes: int = 209715200
    bot_download_max_height: int = 1080
    bot_download_timeout_seconds: int = 300
    # 代理（大陆拉油管等需要）：http://127.0.0.1:7890 形式，留空 = 直连。
    bot_download_proxy: str = ""
    # HTML 信息卡渲染：解析结果渲染成 PNG 图片一起发送（playwright/null）。
    bot_card_render_enabled: bool = True
    bot_card_render_backend: str = "playwright"
    bot_card_render_dir: str = "data/cards"
    bot_render_forward_min_chars: int = 1500
    bot_render_forward_max_nodes: int = 6
    bot_render_forward_node_chars: int = 900
    bot_audit_log_file: str = ""
    bot_audit_log_max_bytes: int = 2097152
    bot_chat_enabled: bool = True
    bot_chat_provider: str = "static"
    bot_chat_model: str = "static"
    bot_chat_api_key: str = ""
    bot_chat_base_url: str = "https://api.openai.com/v1"
    bot_chat_temperature: float = 0.7
    bot_chat_max_tokens: int = 0
    bot_chat_timeout_seconds: float = 30.0
    # 模型预设：{"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro", ...}
    bot_model_presets: dict[str, str] = {}
    # 模型注册表（自动路由 + 失败转移）：id -> {model, base_url, api_key, tags, priority}
    bot_model_registry: dict[str, dict[str, Any]] = {}
    # 自动选型开关：默认开启（复杂任务→strong 档，普通→fast 档）。
    bot_model_auto_route: bool = True
    bot_reply_private_default_max_messages: int = 1
    bot_reply_private_support_max_messages: int = 2
    bot_reply_private_deep_help_max_messages: int = 3
    bot_reply_group_max_messages: int = 1
    bot_reply_risk_max_messages: int = 1
    bot_reply_max_chars_per_message: int = 1200
    bot_reply_default_context_budget: int = 2048
    bot_reply_support_context_budget: int = 2560
    bot_reply_deep_help_context_budget: int = 3072
    bot_reply_group_context_budget: int = 2048
    bot_rate_limit_enabled: bool = True
    bot_rate_limit_window_seconds: int = 60
    bot_rate_limit_chat_global_max_requests: int = 60
    bot_rate_limit_chat_session_max_requests: int = 6
    bot_rate_limit_chat_sender_max_requests: int = 4
    bot_rate_limit_target_min_interval_seconds: int = 0
    bot_rate_limit_bypass_roles: list[str] = ["admin"]
    bot_rate_limit_db_path: str = ""
    bot_quiet_hours_enabled: bool = False
    bot_quiet_hours_start: str = "23:00"
    bot_quiet_hours_end: str = "07:00"
    bot_quiet_hours_timezone: str = "Asia/Hong_Kong"
    bot_quiet_hours_session_types: list[str] = ["group"]
    bot_quiet_hours_bypass_roles: list[str] = ["admin"]

    @field_validator(
        "bot_persona_files",
        "bot_knowledge_files",
        "bot_trend_files",
        "bot_glossary_files",
        "bot_runtime_persona_nicknames",
        "bot_persona_nicknames",
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
        "bot_admin_user_ids",
        "bot_enterprise_user_ids",
        "bot_trusted_user_ids",
        "bot_blocked_user_ids",
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

    @field_validator("bot_persona_alt_profiles", mode="before")
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

    @field_validator("bot_model_presets", "bot_model_registry", mode="before")
    @classmethod
    def _parse_model_dicts(cls, value: Any) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return {}
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        return {}

    @field_validator("bot_credential_probe_urls", mode="before")
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
        "bot_rate_limit_bypass_roles",
        "bot_quiet_hours_session_types",
        "bot_quiet_hours_bypass_roles",
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

    @field_validator(
        "bot_content_parse_platforms",
        "bot_music_platforms",
        mode="before",
    )
    @classmethod
    def _parse_platform_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("platform list JSON must be an array")
                return [str(item).strip().lower() for item in parsed if str(item).strip()]
            normalized = stripped.replace(",", ";")
            return [item.strip().lower() for item in normalized.split(";") if item.strip()]
        raise TypeError("platform list must be a list, JSON array string, or delimiter string")
