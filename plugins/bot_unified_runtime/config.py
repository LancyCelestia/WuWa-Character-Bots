from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


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
    # 运行数据与源码工作区分离：生产环境可把 data/ 放到工作区外，
    # 其余配置仍可继续使用 data/... 的相对写法，由下方校验器统一解析。
    bot_runtime_data_dir: str = "data"
    bot_runtime_enabled: bool = True
    # 入站事件幂等表（P0.4）：重连重放的同事件对同一能力只处理一次；默认关闭，
    # 建议真实 NapCat 验收期间保持关闭，验收通过后再启用。
    bot_event_idempotency_enabled: bool = False
    bot_event_idempotency_ttl_seconds: float = 3600.0
    bot_event_idempotency_max_entries: int = 4096
    # 非空时用 SQLite 持久化幂等表（跨重启拦截重放）；留空用进程内表。
    bot_event_idempotency_db_path: str = ""
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
    bot_telegram_admin_user_ids: list[str] = []
    bot_telegram_admin_chat_ids: list[str] = []
    bot_mail_bridge_enabled: bool = False
    bot_mail_auto_reply_enabled: bool = False
    bot_mail_notify_telegram_enabled: bool = True
    bot_mail_bridge_state_file: str = "data/mail_bridge_state.json"
    bot_mail_sender_aliases: dict[str, str] = {}
    bot_mail_notify_preview_chars: int = 280
    # 掉线管理员通知：掉线时 QQ 通道不可用，改走仍在线的 Telegram/邮件适配器；
    # 默认关闭，收件人必须显式配置，避免误发外部消息。
    bot_disconnect_notice_enabled: bool = False
    bot_disconnect_notice_cooldown_seconds: float = 600.0
    bot_disconnect_notice_mail_account: str = ""
    bot_disconnect_notice_mail_recipients: list[str] = []
    bot_disconnect_notice_telegram_chat_ids: list[str] = []
    # Server酱/PushPlus HTTP 推送（掉线时 QQ 不可用，走外部推送兜底）。
    # SauceNAO 反搜图（对标 YetAnotherPicSearch）：key 也可用 env:SAUCENAO_API_KEY。
    bot_saucenao_api_key: str = "env:SAUCENAO_API_KEY"
    # 逆天发言自动撤回（防御强化，默认关；仅机器人有群管理员权限时才可能生效）。
    bot_dirty_guard_enabled: bool = False
    bot_dirty_guard_delete: bool = False
    bot_disconnect_notice_serverchan_sendkey: str = ""
    bot_disconnect_notice_pushplus_token: str = ""
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
    # Crawl Wiki 外部知识库（只读语料 → 独立向量库，hash 幂等增量同步；
    # 协议见 D:\Coding\Crawl Wiki\docs\KB_HANDOFF.md）。
    # 独立 db_path 是刻意的：人格知识库 sync_chunks 以文件清单为全集删除，
    # 与 7.5 万文档级 wiki 库不能共用一张表。
    bot_kb_wiki_enabled: bool = False
    bot_kb_wiki_root: str = ""
    bot_kb_wiki_db_path: str = "data/kb_wiki_embeddings.sqlite3"
    # topic 白名单（逗号分隔，如 "梗知识,鸣潮"）；空 = 全部 topic。
    bot_kb_wiki_topics: str = ""
    bot_kb_wiki_top_k: int = 4
    bot_kb_wiki_chunk_chars: int = 800
    # 每批嵌入行数：本地 Ollama 实测 128 最快（约为批 10 的 6 倍吞吐）；
    # 本地不可用回落远程链时，远程单批限额(≤10)会拒绝大批并中止同步
    # （断点续跑、无损坏），恢复本地后重跑即可。
    bot_kb_wiki_embed_batch: int = 128
    # 每日增量同步时刻（Crawl Wiki 每日 23:00 导出之后）。
    bot_kb_wiki_sync_hour: int = 23
    bot_kb_wiki_sync_minute: int = 40
    bot_kb_wiki_sync_on_startup: bool = True
    bot_tone_mode: str = "private_chat"
    bot_tone_voice: str = "soft"
    bot_tone_warmth: float = 0.7
    bot_tone_directness: float = 0.5
    bot_tone_message_count_limit: int = 0
    bot_memory_enabled: bool = False
    bot_memory_db_path: str = ""
    bot_memory_max_items: int = 5
    bot_memory_max_chars: int = 1200
    # 回复后自动从对话抽取记忆写入记忆库；依赖 bot_memory_enabled。
    bot_memory_extract_enabled: bool = True
    bot_memory_extract_timeout_seconds: float = 15.0
    bot_memory_extract_max_tokens: int = 200
    bot_memory_extract_error_cooldown_seconds: float = 300.0
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
    # 发送层单次请求硬超时（秒）：OneBot/Telegram/Mail 发送共用；0 或非法值在运行时回退 15。
    bot_transport_timeout_seconds: float = 15.0
    # 请求级总预算（秒）：单次聊天从 LLM/工具循环到发送共用一个单调 deadline；范围 (0,600]。
    bot_request_budget_seconds: float = 150.0
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
    # 群聊回复策略（群号列表）：
    # black1=完全静默只接收不发送；black2=只回“@它且带指令”的消息；
    # white1=正常回复并可按主动接话开关抽签；white2=只回“@它”或显式命令。
    bot_group_black1: list[str] = []
    bot_group_black2: list[str] = []
    bot_group_white1: list[str] = []
    bot_group_white2: list[str] = []
    bot_meme_search_enabled: bool = False
    bot_meme_search_timeout_seconds: float = 8.0
    bot_meme_search_cache_seconds: int = 600
    # 现实时效问题按需联网检索：默认关闭；开启后仅在强信号（新闻/价格/汇率等）触发，
    # 世界观问题永远只走本地知识库，不联网。
    bot_web_search_enabled: bool = False
    bot_web_search_timeout_seconds: float = 3.0
    # 联网检索条数上限；0=不限制（内部有安全上限，避免无限等待）。
    bot_web_search_max_results: int = 20
    # Search API chain: Tavily primary, You/LangSearch fallback; TinyFish can fetch正文.
    bot_web_search_provider: str = "tavily"
    bot_web_search_fallback_providers: list[str] = ["you", "langsearch"]
    bot_web_search_provider_options: dict[str, dict[str, Any]] = {}
    # Separate aliases keep env:BOT_SEARCH_* references resolvable after NoneBot dotenv loading.
    bot_search_tavily_api_key: str = ""
    bot_search_you_api_key: str = ""
    bot_search_tinyfish_api_key: str = ""
    bot_search_langsearch_api_key: str = ""
    bot_web_search_tavily_api_key: str = ""
    bot_web_search_you_api_key: str = ""
    bot_web_search_tinyfish_api_key: str = ""
    bot_web_search_langsearch_api_key: str = ""
    bot_web_search_tavily_endpoint: str = "https://api.tavily.com/search"
    # Tavily 一级参数：留空则不随请求发送；也可经 provider_options 覆盖同名键。
    bot_web_search_tavily_search_depth: str = ""
    bot_web_search_tavily_time_range: str = ""
    # 正文抓取回退：TinyFish 优先，可再用 Tavily extract 兜底（默认关闭，避免额外额度消耗）。
    bot_web_search_tavily_extract_enabled: bool = False
    bot_web_search_tavily_extract_endpoint: str = "https://api.tavily.com/extract"
    bot_web_search_you_endpoint: str = "https://api.you.com/v1/search"
    bot_web_search_tinyfish_endpoint: str = "https://api.search.tinyfish.ai/search"
    bot_web_search_tinyfish_fetch_endpoint: str = "https://api.fetch.tinyfish.ai"
    bot_web_search_langsearch_endpoint: str = "https://api.langsearch.com/v1/web-search"
    bot_web_search_fetch_timeout_seconds: float = 15.0
    bot_web_search_fetch_max_chars: int = 3000
    # 管理员私聊可选显示联网检索提示；仅有真实结果链接时才追加。
    bot_web_search_admin_notice: bool = False
    # 联网分类遥测：只记录查询哈希、决策、置信度和命中统计，不记录原文。
    bot_web_intent_telemetry_enabled: bool = False
    bot_web_intent_telemetry_db_path: str = "data/web_intent_telemetry.sqlite3"
    bot_web_intent_telemetry_max_items: int = 10000
    # 开启后同时记录旧版分类标签，用于影子对比；不改变新算法线上决策。
    bot_web_classifier_shadow_enabled: bool = False

    # 表情包生成能力（bot.meme）：对接本地 meme-generator-rs HTTP API。
    # 命令开关：/表情 列表、/表情 <key> <文字>、/meme help（大小写均可）。
    bot_meme_command_enabled: bool = True
    # 动态好感度与印象标签（批次 C）：按用户行为自动增减，差异化态度；
    # 管理员可直接改 data/user_affinity.sqlite3 调整个别用户。
    bot_affinity_enabled: bool = True
    # 群聊复读检测：窗口内 ≥N 个不同用户发同一文本则吐槽一次（"怎么一个个都当复读机"）。
    bot_parrot_threshold: int = 3
    bot_parrot_window_seconds: float = 60.0
    bot_parrot_cooldown_seconds: float = 300.0
    bot_affinity_db_path: str = "data/user_affinity.sqlite3"
    bot_meme_api_enabled: bool = False
    # 多候选点歌（借鉴 multincm 编号选择交互）：同名歧义返回编号列表让用户回复编号选择；
    # 默认关闭保持"第一命中直接播放"的既有行为。
    # 点歌默认输出模式：card+voice+link（卡片/封面 + 语音试听 + 链接）。
    # 运行时 BOT_MUSIC_MODE 覆盖此处。
    bot_parse_subtitle_summary: bool = False
    bot_eat_enabled: bool = True
    bot_channel_health_enabled: bool = True
    bot_channel_health_interval_seconds: float = 3600.0
    # 巡检并发/错峰参数（B-2）：background 巡检并发、手动 probe 并发、
    # background 提交错峰间隔；钳位线程 1..16、jitter 0..5.0。
    bot_channel_probe_threads: int = 3            # background 巡检并发
    bot_channel_probe_manual_threads: int = 8     # 手动 /bot model probe 并发
    bot_channel_probe_jitter_seconds: float = 0.4 # background 提交错峰间隔
    bot_music_default_mode: str = "card+voice+link"
    bot_music_candidates_enabled: bool = False
    bot_music_candidates_ttl_seconds: float = 300.0
    bot_music_candidates_limit: int = 5
    # 外挂表情包生成插件 nonebot-plugin-memes（能力空白补齐）；
    # 默认关闭：加载后其 matcher 独立于统一管线直接响应。
    bot_memes_plugin_enabled: bool = False
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
    bot_vision_model_registry: dict[str, Any] = {}
    # 聊天图片/表情包识别开关：启用且注册表里有可用模型时才会调用 VLM。
    bot_vision_enabled: bool = False
    # direct=主模型直接收图（多模态）；relay=VLM 转译中间层。
    # 主模型均 multimodal，direct 效果更好且省一层调用。
    bot_vision_mode: str = "direct"
    bot_vision_timeout_seconds: float = 20.0
    bot_vision_max_images: int = 2
    bot_vision_max_chars: int = 500
    # 视频识别抽帧数：ffmpeg 均匀抽帧后单次 VLM 摘要；0 视同 1。
    bot_vision_video_frames: int = 4
    # 白名单1 群里图片/表情包的回复概率：1.0=发图即识别回应；0=仅 @ 时看图。
    bot_vision_reply_probability: float = 1.0
    # 语音转写（record 段）：OpenAI 兼容 /audio/transcriptions 接口，
    # registry 格式与 vision 相同（id -> 条目或条目列表，支持 env: 引用 key）。
    bot_asr_model_registry: dict[str, Any] = {}
    bot_asr_enabled: bool = False
    bot_asr_timeout_seconds: float = 20.0
    bot_asr_max_chars: int = 300
    # NSFW 直接删除阈值（淫秽色情不存储）：>= 该分数删除文件与记录。
    bot_meme_library_nsfw_delete: float = 0.8
    # 群图下载代理（默认直连 QQ 多媒体源；外网源可走 7890）。
    bot_meme_library_proxy: str = ""
    # 自然语言命令层（基层路由优先级 45）：“帮我查天气”等归一化执行。
    bot_natural_command_enabled: bool = True
    # 群聊自动接话：enabled=true 时按 probability 对未点名的群消息
    # 抽签回复（确定性哈希，不是随机数）；默认关闭，点名/命令不受影响。
    bot_group_chat_auto_reply_enabled: bool = False
    bot_group_chat_auto_reply_probability: float = 0.05
    bot_group_proactive_max_replies_per_hour: int = 6
    bot_group_proactive_cooldown_seconds: int = 90
    bot_poke_enabled: bool = True
    bot_poke_private_cooldown_seconds: float = 30.0
    bot_poke_group_cooldown_seconds: float = 10.0
    bot_poke_probability: float = 1.0
    bot_poke_admin_bypass: bool = False
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
    # 点歌行为分析（只记录成功的 bot.music 结果，不记录原始查询词）。
    bot_music_analytics_enabled: bool = True
    bot_music_analytics_db_path: str = "data/music_analytics.sqlite3"
    bot_music_analytics_retention_days: int = 365
    # 解析/点歌请求的统一超时（秒）。
    bot_fetch_timeout_seconds: float = 10.0
    # 含合并转发的消息抓取转发正文超时（秒）；仅影响带 forward 段的消息。
    bot_forward_fetch_timeout_seconds: float = 5.0
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
    # 解析结果视频直发：解析器给出视频直链（小红书 sns-video/Telegram 等）时
    # 自动下载并以视频段随卡片发送；失败/超限静默降级为「下载：」提示。
    bot_content_video_auto_send: bool = True
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
    # 外置卡片 SVG 资源目录；留空时由 bridge 自动发现同级 ChatBot_Runtime。
    bot_card_asset_dir: str = ""
    # 信息卡整体 UI 缩放（1.0=100%，1.25=125%）；viewport 随之等比放大。
    bot_card_ui_scale: float = 1.25
    # 帮助页卡片主色（十六进制）；留空 = 中性灰，tint 一律由主色派生，不写死品牌色。
    bot_help_card_color: str = ""
    # 「历史上的今天」：查询 + 每日定时推送（数据源：百度百科公开接口，每日缓存）。
    bot_today_history_enabled: bool = True
    bot_today_history_push_file: str = "data/today_history_push.json"
    bot_today_history_cache_file: str = "data/today_history_cache.json"
    # 维基百科查询（bot.wiki）：`维基 <词条>`，MediaWiki 公开 API，免 key。
    bot_wiki_enabled: bool = True
    bot_wiki_lang: str = "zh"
    # Candidate index pages only; extraction still requires an exact entry match.
    bot_wiki_entry_pages: list[str] = ["鳴潮角色列表"]
    # 萌娘百科查询（bot.moegirl）：`萌娘百科 <词条>` 显式指令 + 二次元问句
    # （「初音未来是谁？」）自动查询；问句未命中/网络失败时无感降级 AI 聊天。
    # 公开 MediaWiki API 免 key；镜像仅作回退；总耗时受 timeout 预算硬约束。
    bot_moegirl_enabled: bool = True
    # 问句自动触发独立开关（关闭后仅保留显式指令；群聊不 @ 本就不触发）。
    bot_moegirl_question_enabled: bool = True
    bot_moegirl_api_base: str = "https://zh.moegirl.org.cn/api.php"
    bot_moegirl_mirror_api_base: str = "https://mzh.moegirl.org.cn/api.php"
    # 单请求超时；问句路径整体预算 ≈ 2×该值（主站+镜像各一份份额）。
    bot_moegirl_timeout_seconds: float = 5.0
    bot_moegirl_max_candidates: int = 5
    bot_moegirl_summary_max_chars: int = 300
    # Epic 每周免费游戏（bot.epic）：`epic`，Epic 公开接口，免 key。
    bot_epic_enabled: bool = True
    # 中文天气查询（bot.weather）：`天气 <城市>`，中国气象局 NMC 免 key。
    bot_weather_query_enabled: bool = True
    bot_render_forward_min_chars: int = 1500
    bot_render_forward_max_nodes: int = 0
    bot_render_forward_node_chars: int = 900
    bot_audit_log_file: str = ""
    bot_audit_log_max_bytes: int = 2097152
    bot_prompt_audit_enabled: bool = True
    bot_prompt_audit_dir: str = "data/prompt_audit"
    bot_prompt_audit_include_messages: bool = True
    bot_prompt_audit_include_untrusted_context: bool = True
    bot_prompt_audit_max_chars: int = 12000
    bot_prompt_execution_mode: str = "execute"
    bot_prompt_approval_digest: str = ""
    bot_prompt_audit_retention_days: int = 14
    bot_chat_enabled: bool = True
    bot_chat_provider: str = "static"
    bot_chat_model: str = "static"
    bot_chat_api_key: str = ""
    # 注册表中 ``env:BOT_API_KEY_*`` 引用的凭据字段。
    # NoneBot dotenv 会把它们放进 driver.config，必须在这里保留，
    # 否则 Config.model_validate 会丢弃字段，真实运行态路由会拿到空 key。
    bot_api_key_qianqianye: str = ""
    bot_api_key_qianqianye_night: str = ""
    bot_api_key_deepseek_qian: str = ""
    bot_api_key_aiprc: str = ""
    bot_api_key_aiprc_gemini: str = ""
    bot_api_key_aiprc_grok: str = ""
    bot_api_key_umi_group1: str = ""
    bot_api_key_umi_group2: str = ""
    bot_api_key_hcn: str = ""
    bot_api_key_zhipu: str = ""
    bot_api_key_toolcode_gpt: str = ""
    bot_api_key_toolcode_gemini: str = ""
    bot_api_key_toolcode_grok: str = ""
    bot_api_key_starapi: str = ""
    bot_api_key_umi_group3: str = ""
    bot_api_key_umi_claude: str = ""
    bot_chat_base_url: str = "https://api.openai.com/v1"
    bot_chat_temperature: float = 0.7
    bot_chat_reasoning_effort: str = ""
    bot_chat_max_tokens: int = 65538
    bot_chat_timeout_seconds: float = 90.0
    # QQ/群聊快速响应模式：限制上下文、输出和联网前置工作，优先首字响应速度。
    bot_chat_fast_mode: bool = True
    bot_chat_fast_max_tokens: int = 65538
    bot_chat_fast_max_candidates: int = 0
    bot_chat_fast_timeout_seconds: float = 90.0
    bot_chat_fast_context_budget: int = 9600
    bot_chat_fast_web_max_queries: int = 3
    # 故障转移总时限（秒）：候选模型连续失败时的整体预算，防止响应被拖到分钟级；0=不限。
    bot_chat_failover_max_seconds: float = 120.0
    bot_chat_fast_embedding_timeout_seconds: float = 3.0
    bot_chat_fast_skip_web_pages: bool = True
    bot_chat_fast_disable_vector_knowledge: bool = False
    # 模型预设：{"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro", ...}
    bot_model_presets: dict[str, str] = {}
    # 模型注册表（自动路由 + 失败转移）：id -> {model, base_url, api_key, tags, priority}
    bot_model_registry: dict[str, dict[str, Any]] = {}
    # 分时段自动切换模型：{"HH:MM-HH:MM": "预设或注册表id"}；跨零点窗口如 "23:00-07:00"。
    bot_model_schedule: dict[str, str] = {}
    # 时段优先级分组（峰谷顺序）：[{"name":"工作日高峰","days":[1,2,3,4,5],
    # "windows":[["09:00","12:00"],["14:00","18:00"]],"order":[模型id...]}]；
    # days 用 ISO 周编号(1=周一…7=周日)，缺省=每天；windows 缺省=全天；
    # days/windows 都缺省 = 兜底组；按列表顺序取第一个命中的组。
    bot_model_priority_groups: list[dict[str, Any]] = []
    # 每模型价格（元/每百万 token）：{"deepseek-v4-pro": {"input": 4.0, "output": 16.0}}；
    # 按调用时刻的价格记账成本，未配置价格的模型不计费。
    bot_model_prices: dict[str, dict[str, Any]] = {}
    # 用量监控：阈值提醒 + 定时报告（推送管理员，走 runtime/alerts 管线）。
    bot_usage_monitor_enabled: bool = True
    bot_usage_alert_output_tokens: int = 5_000_000
    bot_usage_alert_input_tokens: int = 50_000_000
    bot_usage_alert_daily_cost_yuan: float = 10.0
    # 定时报告时间点（北京时间，整点，逗号分隔）；报告窗口 = 自上个报告点至今。
    bot_usage_report_hours: str = "13,18,23"
    bot_usage_report_state_file: str = "data/usage_report_state.json"
    # 自动选型开关：默认开启（复杂任务→strong 档，普通→fast 档）。
    bot_model_auto_route: bool = True
    bot_reply_private_default_max_messages: int = 0
    bot_reply_private_support_max_messages: int = 0
    bot_reply_private_deep_help_max_messages: int = 0
    bot_reply_group_max_messages: int = 0
    bot_reply_risk_max_messages: int = 0
    bot_reply_max_chars_per_message: int = 0
    # 回复详略：auto=科普/知识类自动详尽，detail=全部详尽(2000~4000字)，concise=精炼。
    bot_reply_detail: str = "auto"
    bot_generated_files_dir: str = "data/generated_files"
    bot_file_read_max_chars: int = 120000
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
    bot_quiet_hours_enabled: bool = True
    bot_quiet_hours_start: str = "00:00"
    bot_quiet_hours_end: str = "06:00"
    bot_quiet_hours_timezone: str = "Asia/Hong_Kong"
    bot_quiet_hours_session_types: list[str] = ["group"]
    bot_quiet_hours_bypass_roles: list[str] = ["admin"]
    # 订阅系统基础框架（bot.subscribe）：定时拉取平台新内容并私聊/群聊推送。
    bot_subscribe_enabled: bool = True
    bot_subscribe_db_path: str = "data/subscriptions.sqlite3"
    bot_subscribe_poll_interval_seconds: int = 300
    bot_subscribe_max_items_per_tick: int = 20
    bot_subscribe_jitter_ratio: float = 0.20
    bot_subscribe_global_concurrency: int = 3
    bot_subscribe_platform_concurrency: int = 1
    bot_subscribe_min_interval_seconds: float = 1.0
    bot_subscribe_lease_seconds: int = 120
    bot_subscribe_retry_base_seconds: int = 60
    bot_subscribe_retry_cap_seconds: int = 1800
    bot_subscribe_outbox_interval_seconds: int = 15
    # 订阅即时推送附带解析卡片图（kind="mixed"），渲染失败自动回退纯文本。
    bot_subscribe_card_enabled: bool = True
    bot_fetch_playwright_enabled: bool = True
    bot_runtime_log_file: str = "data/runtime_events.log"
    bot_runtime_log_max_bytes: int = 2097152
    bot_runtime_log_level: str = "INFO"

    @field_validator("bot_memory_extract_timeout_seconds", "bot_memory_extract_error_cooldown_seconds")
    @classmethod
    def _positive_memory_duration(cls, value: float) -> float:
        if not math.isfinite(value) or not 0 < value <= 3600:
            raise ValueError("memory duration must be finite and in (0,3600]")
        return value

    @field_validator("bot_chat_max_tokens", "bot_chat_fast_max_tokens")
    @classmethod
    def _validate_chat_output_tokens(cls, value: int) -> int:
        if value < 0 or value > 65538:
            raise ValueError("chat output token limit must be between 0 and 65538")
        return value

    @field_validator("bot_memory_extract_max_tokens")
    @classmethod
    def _memory_token_limit(cls, value: int) -> int:
        if not 1 <= value <= 4096:
            raise ValueError("memory extraction max tokens must be in [1,4096]")
        return value

    @field_validator("bot_web_search_fallback_providers", mode="before")
    @classmethod
    def _parse_web_search_provider_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return ["you", "langsearch"]
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("BOT_WEB_SEARCH_FALLBACK_PROVIDERS must be a JSON array")
                value = parsed
            else:
                value = [item for item in raw.replace(";", ",").split(",") if item.strip()]
        if not isinstance(value, list):
            raise TypeError("BOT_WEB_SEARCH_FALLBACK_PROVIDERS must be a list")
        return [str(item).strip().lower() for item in value if str(item).strip()]

    @field_validator("bot_web_search_provider_options", mode="before")
    @classmethod
    def _parse_web_search_provider_options(cls, value: Any) -> dict[str, dict[str, Any]]:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise TypeError("BOT_WEB_SEARCH_PROVIDER_OPTIONS must be a JSON object")
        return {
            str(name).strip().lower(): dict(options)
            for name, options in value.items()
            if isinstance(options, dict)
        }
    @model_validator(mode="after")
    def _resolve_runtime_data_paths(self) -> Config:
        """将 data/... 路径统一解析到 BOT_RUNTIME_DATA_DIR。"""
        raw_root = str(self.bot_runtime_data_dir or "").strip() or "data"
        data_root = Path(raw_root).expanduser()
        if not data_root.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            data_root = project_root / data_root

        def resolve(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            text = value.strip()
            normalized = text.replace("\\", "/")
            if normalized == "data":
                return str(data_root)
            if normalized.startswith("data/"):
                return str(data_root / normalized[5:])
            return value

        path_fields = (
            "bot_runtime_settings_file",
            "bot_runtime_settings_dir",
            "bot_mail_bridge_state_file",
            "bot_event_idempotency_db_path",
            "bot_knowledge_db_path",
            "bot_kb_wiki_db_path",
            "bot_memory_db_path",
            "bot_history_db_path",
            "bot_diagnostics_db_path",
            "bot_audit_db_path",
            "bot_receipts_db_path",
            "bot_send_queue_db_path",
            "bot_web_intent_telemetry_db_path",
            "bot_meme_api_output_dir",
            "bot_meme_library_dir",
            "bot_meme_library_db_path",
            "bot_parse_history_db_path",
            "bot_music_analytics_db_path",
            "bot_download_dir",
            "bot_card_render_dir",
            "bot_generated_files_dir",
            "bot_today_history_push_file",
            "bot_today_history_cache_file",
            "bot_audit_log_file",
            "bot_prompt_audit_dir",
            "bot_rate_limit_db_path",
            "bot_subscribe_db_path",
            "bot_runtime_log_file",
            "bot_cookies_file",
        )
        for name in path_fields:
            setattr(self, name, resolve(getattr(self, name)))

        for name in (
            "bot_persona_files",
            "bot_knowledge_files",
            "bot_trend_files",
            "bot_glossary_files",
        ):
            setattr(self, name, [resolve(item) for item in getattr(self, name)])
        return self

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
        "bot_telegram_admin_user_ids",
        "bot_telegram_admin_chat_ids",
        "bot_enterprise_user_ids",
        "bot_trusted_user_ids",
        "bot_blocked_user_ids",
        "bot_share_groups",
        "bot_group_black1",
        "bot_group_black2",
        "bot_group_white1",
        "bot_group_white2",
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
        "bot_model_schedule",
        "bot_model_prices",
        "bot_mail_sender_aliases",
        "bot_vision_model_registry",
        "bot_asr_model_registry",
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

    @field_validator("bot_model_priority_groups", mode="before")
    @classmethod
    def _parse_model_priority_groups(cls, value: Any) -> list[dict[str, Any]]:
        """BOT_MODEL_PRIORITY_GROUPS：接受 JSON 数组字符串或 list[dict]。"""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return []
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        return []

    @field_validator("bot_transport_timeout_seconds", mode="before")
    @classmethod
    def _validate_transport_timeout_seconds(cls, value: Any) -> float:
        """拒绝负数/NaN/Infinity/超大值；合法范围 (0, 600] 秒。"""
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 必须是数字（秒）") from exc
        if math.isnan(number) or number <= 0 or number > 600:
            raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 必须在 0-600 秒之间")
        return number

    @field_validator("bot_request_budget_seconds", mode="before")
    @classmethod
    def _validate_request_budget_seconds(cls, value: Any) -> float:
        """拒绝负数/NaN/Infinity/超大值；合法范围 (0, 600] 秒。"""
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("BOT_REQUEST_BUDGET_SECONDS 必须是数字（秒）") from exc
        if math.isnan(number) or number <= 0 or number > 600:
            raise ValueError("BOT_REQUEST_BUDGET_SECONDS 必须在 0-600 秒之间")
        return number

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
