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
    # 多实例共享：bot_share_groups 用 "A and B"、"A and B and C" 这类名字。
    bot_share_enabled: bool = False
    bot_share_groups: list[str] = []
    bot_share_read_only: bool = False
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
    # 卡片页脚机器人头像（可选 URL/本地路径；空则用名字首字圆点）。
    bot_persona_avatar_url: str = ""
    # 备用人格：{"gentle": {"display_name": "...", "files": [...],
    #   "weight": 0.3, "emotions": ["support_needed", ...]}, ...}
    bot_persona_alt_profiles: dict[str, dict[str, Any]] = {}
    bot_knowledge_files: list[str] = []
    bot_knowledge_max_chunks: int = 4
    bot_knowledge_chunk_chars: int = 900
    # 向量知识库：启用后按查询语义检索，嵌入失败自动回退顺序取块。
    bot_embedding_enabled: bool = False
    bot_embedding_model: str = ""
    bot_embedding_base_url: str = ""
    bot_embedding_api_key: str = ""
    bot_embedding_timeout_seconds: float = 15.0
    bot_embedding_dimensions: int = 1024
    # 本地优先：Ollama（OpenAI 兼容端点），失败自动回退远程付费模型。
    bot_embedding_local_enabled: bool = True
    bot_embedding_local_base_url: str = "http://127.0.0.1:11434/v1"
    bot_embedding_local_models: str = "bge-m3"
    bot_embedding_local_api_key: str = ""
    bot_embedding_local_timeout_seconds: float = 60.0
    bot_knowledge_top_k: int = 4
    bot_knowledge_db_path: str = "data/knowledge_embeddings.sqlite3"
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
    # 现实时效问题按需联网检索：默认关闭；开启后仅在强信号（新闻/价格/汇率等）触发，
    # 世界观问题永远只走本地知识库，不联网。
    bot_web_search_enabled: bool = False
    bot_web_search_timeout_seconds: float = 3.0
    # 联网检索条数上限；0=不限制（内部有安全上限，避免无限等待）。
    bot_web_search_max_results: int = 12

    # 表情包生成能力（bot.meme）：对接本地 meme-generator-rs HTTP API。
    # 命令开关：/表情 列表、/表情 <key> <文字>、/meme help（大小写均可）。
    bot_meme_command_enabled: bool = True
    bot_meme_api_enabled: bool = False
    bot_meme_api_base_url: str = "http://127.0.0.1:2233"
    bot_meme_api_timeout_seconds: float = 15.0
    bot_meme_api_output_dir: str = "data/memes"
    # 群聊表情包机器人（bot.meme_library）：监听群图片→异步下载→MD5 去重入库，
    # /偷表情 按权重随机发送；优先守岸人/鸣潮/战双/库洛，NSFW 与普通图片降权。
    bot_meme_library_enabled: bool = False
    bot_meme_library_dir: str = "data/meme_library"
    bot_meme_library_db_path: str = "data/meme_library.sqlite3"
    bot_meme_library_max_file_bytes: int = 5242880
    bot_meme_library_max_files: int = 20000
    bot_meme_library_max_age_days: int = 30
    bot_meme_library_cooldown_seconds: int = 20
    bot_meme_library_group_allowlist: list[str] = []
    bot_meme_library_group_denylist: list[str] = []
    bot_meme_library_nsfw_max: float = 0.2
    bot_meme_library_prefer: list[str] = ["守岸人", "岸宝", "鸣潮", "战双帕弥什", "库洛"]
    # VLM 打标（可选，默认关）：OpenAI-compatible 视觉模型给图片打标签与 NSFW 评分。
    bot_meme_library_vlm_enabled: bool = False
    bot_meme_library_vlm_model: str = ""
    bot_meme_library_vlm_base_url: str = ""
    bot_meme_library_vlm_api_key: str = ""
    bot_meme_library_vlm_timeout_seconds: float = 20.0
    # 识图模型预制接口：预设名 + 注册表，未来换新模型只需加一条 preset。
    bot_meme_library_vlm_preset: str = "deepseek-vision"
    bot_vision_model_registry: dict[str, dict[str, Any]] = {
        "deepseek-vision": {
            "model": "deepseek-v4-flash-vision-exp",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "env:BOT_API_KEY_DEEPSEEK",
        }
    }
    # NSFW 直接删除阈值（淫秽色情不存储）：>= 该分数删除文件与记录。
    bot_meme_library_nsfw_delete: float = 0.8
    # 群图下载代理（默认直连 QQ 多媒体源；外网源可走 7890）。
    bot_meme_library_proxy: str = ""
    # 自然语言命令层（基层路由优先级 45）：“帮我查天气”等归一化执行。
    bot_natural_command_enabled: bool = True
    # 群聊自动接话：enabled=true 时按 probability 对未点名的群消息
    # 抽签回复（确定性哈希，不是随机数）；默认关闭，点名/命令不受影响。
    bot_group_chat_auto_reply_enabled: bool = False
    bot_group_chat_auto_reply_probability: float = 0.0
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
    bot_download_max_bytes: int = 1073741824
    bot_download_max_height: int = 0
    bot_download_timeout_seconds: int = 600
    # 缓存配额：下载目录/点歌缓存/卡片缓存按最旧优先清理，防占满硬盘。
    bot_download_cache_max_bytes: int = 2147483648
    bot_download_cache_max_age_days: int = 7
    bot_music_cache_max_bytes: int = 536870912
    bot_card_cache_max_bytes: int = 268435456
    bot_meme_cache_max_bytes: int = 268435456
    # 代理（大陆拉油管等需要）：http://127.0.0.1:7890 形式，留空 = 直连。
    bot_download_proxy: str = ""
    # HTML 信息卡渲染：解析结果渲染成 PNG 图片一起发送（playwright/null）。
    bot_card_render_enabled: bool = True
    bot_card_render_backend: str = "playwright"
    bot_card_render_dir: str = "data/cards"
    # 「历史上的今天」：查询 + 每日定时推送（数据源：百度百科公开接口，每日缓存）。
    bot_today_history_enabled: bool = True
    bot_today_history_push_file: str = "data/today_history_push.json"
    # 维基百科查询（bot.wiki）：`维基 <词条>`，MediaWiki 公开 API，免 key。
    bot_wiki_enabled: bool = True
    bot_wiki_lang: str = "zh"
    # Epic 每周免费游戏（bot.epic）：`epic`，Epic 公开接口，免 key。
    bot_epic_enabled: bool = True
    # 中文天气查询（bot.weather）：`天气 <城市>`，中国气象局 NMC 免 key。
    bot_weather_query_enabled: bool = True
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
    # 回复详略：auto=科普/知识类自动详尽，detail=全部详尽(2000~4000字)，concise=精炼。
    bot_reply_detail: str = "auto"
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
    # 订阅系统基础框架（bot.subscribe）：定时拉取平台新内容并私聊/群聊推送。
    bot_subscribe_enabled: bool = True
    bot_subscribe_db_path: str = "data/subscriptions.sqlite3"
    bot_subscribe_poll_interval_seconds: int = 300
    bot_subscribe_live_poll_seconds: int = 60
    bot_subscribe_digest_hour: int = 20
    bot_subscribe_digest_minute: int = 0
    bot_subscribe_max_items_per_tick: int = 20
    bot_subscribe_playwright_poll_seconds: int = 1800
    bot_fetch_playwright_enabled: bool = True
    bot_runtime_log_file: str = "data/runtime_events.log"
    bot_runtime_log_max_bytes: int = 2097152
    bot_runtime_log_level: str = "INFO"

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
        "bot_share_groups",
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

    @field_validator(
        "bot_model_presets",
        "bot_model_registry",
        "bot_vision_model_registry",
        mode="before",
    )
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
        "bot_meme_library_group_allowlist",
        "bot_meme_library_group_denylist",
        "bot_meme_library_prefer",
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
