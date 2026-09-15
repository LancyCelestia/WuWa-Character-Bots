from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator, model_validator

_logger = logging.getLogger(__name__)


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
    # 超级管理员（R1 2026-09-12）：权威高于 admin，人格层有专属保护规则；
    # 超管自动具备全部 admin 权限。管理员档案见 bot_admin_profiles。
    bot_super_admin_user_ids: list[str] = []
    # 管理团队身份档案（人格层注入）：[{qq,name,nicknames,role,note}, ...]。
    # qq=QQ号；name=显示名；nicknames=别名（分隔符任意的单字符串）；
    # role=super/admin；note=补充（如「与某某为同一人」）。
    bot_admin_profiles: list[dict[str, str]] = []
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
    # B-4：bot_unavailable 挂起的绝对年龄上限（秒）——入队超过该时长仍因
    # NapCat 断线不可投才置 FAILED_FINAL（防非终态行无限堆积）；缺字段 =
    # env 键被 pydantic 丢弃、旋钮恒默认（§14.4.2：env 键须有同名小写字段）。
    bot_send_bot_unavailable_max_age_seconds: float = 1800.0
    # 发送层单次请求硬超时（秒）：OneBot/Telegram/Mail 发送共用；
    # 合法范围 (0, 600]，0/负数/NaN/Infinity/超大值在启动校验时直接报错
    # （与 _validate_transport_timeout_seconds 一致，无"回退 15"的隐式兜底）。
    bot_transport_timeout_seconds: float = 15.0
    # 请求级总预算（秒）：单次聊天从 LLM/工具循环到发送共用一个单调 deadline；范围 (0,600]。
    bot_request_budget_seconds: float = 150.0
    # 聊天管线专用线程池 worker 数（管线检视 #4）：与默认线程池隔离，
    # 避免长任务挤占语音转码/kb 拉取等 to_thread；在途上限为 2 倍（含排队），
    # 超限快败记 pipeline_busy 审计。钳位 1..64；env 兜底 BOT_PIPELINE_MAX_WORKERS。
    bot_pipeline_max_workers: int = 8
    # B2 中央决策引擎迁移模式（阶段 0）：legacy_only（默认，引擎不参与）/
    # shadow（引擎只算 plan 写 decision_trace，绝不发送）/ engine_only
    # （随迁移阶段 1+ 启用）。非法值在运行时一律回落 legacy_only（fail-closed）。
    bot_decision_engine_mode: str = "legacy_only"
    bot_emotion_enabled: bool = True
    bot_emotion_max_signals: int = 4
    # 机器人自身心情（L1，character/mood.py）：分钟-小时尺度连续情绪，事件驱动、
    # 按半衰期指数回归基线；与好感度（天-周尺度）时间尺度分离。
    bot_mood_enabled: bool = True
    bot_mood_db_path: str = "data/bot_mood.sqlite3"
    bot_mood_half_life_minutes: float = 120.0
    bot_mood_baseline_arousal: float = 0.3
    bot_mood_rate_cap_per_hour: float = 0.5
    # L4 人格演化区（审核制）：核心人格文件永不自动改；习惯沉淀在此，管理员审核后才生效。
    bot_quirks_enabled: bool = True
    bot_quirks_db_path: str = "data/persona_quirks.sqlite3"
    bot_quirks_max_active: int = 6
    # 反思回路（character/reflection.py）：夜间把当天对话沉淀为高层事实 + 会话摘要，
    # 提供跨会话的"非线性记忆"召回；LLM 归纳默认关（用确定性启发式）。
    bot_reflection_enabled: bool = True
    bot_reflection_db_path: str = "data/reflection.sqlite3"
    bot_reflection_hour: int = 4
    bot_reflection_minute: int = 30
    bot_reflection_max_sessions: int = 50
    bot_reflection_llm_enabled: bool = False
    # N4：夜间反思高置信用户事实 → persona_quirks 待审提案（白名单过滤，
    # 只进 pending_review 队列，仍需管理员审核，不直接生效）。
    bot_reflection_quirks_propose_enabled: bool = True
    bot_reflection_quirks_min_confidence: float = 0.5
    # 会话级身份记忆（管理员设置）：每群/每私聊独立的 bot 称呼与身份标签。
    bot_session_identity_db_path: str = "data/session_identity.sqlite3"
    # 用户称谓/性别偏好持久化（用户显式设置或纠正；优先于一切推断）。
    bot_addressing_preferences_db_path: str = "data/addressing_preferences.sqlite3"
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
    # 全球股指行情（bot.market）：东方财富 push2 免费接口，免 key，进程内 TTL 缓存。
    bot_market_enabled: bool = True
    # 个股行情/汇率路由开关（base_router getattr 读取；无此字段时 .env 无法关闭）。
    bot_stocks_enabled: bool = True
    bot_fx_enabled: bool = True
    # 东财空响应受控重试（G2）：限流时 HTTP 200 但业务体为空（空 JSON/缺行），
    # 三源数据层至多重试 1 次（退避 0.6s）；关闭后行为与无重试逐字节一致。
    bot_market_retry_on_empty: bool = True
    bot_market_timeout_seconds: float = 6.0
    bot_market_cache_seconds: float = 60.0
    # 随机图片（bot.randpic）：只读取用户自定义文件夹随机发图，绝不自建目录。
    bot_randpic_enabled: bool = True
    bot_randpic_dirs: list[str] = []
    bot_randpic_trigger_words: list[str] = []
    bot_randpic_max_file_mb: int = 20
    # 时间点提醒（bot.reminder）：记住"几点要做什么"，到点主动督促。
    bot_reminder_enabled: bool = True
    bot_reminder_db_path: str = "data/reminders.sqlite3"
    # R-进阶轨（默认关）：LLM 轮末抽取无「提醒」词的时间陈述为提醒（如
    # 「中午12点要写作业」）；复用 memory_extract 同款后台机制，失败静默。
    bot_reminder_llm_extract_enabled: bool = False
    # 今日快报（bot.news）：国内可达 RSS 聚合，进程内 TTL 缓存（按类目分桶）。
    bot_news_enabled: bool = True
    bot_news_timeout_seconds: float = 6.0
    bot_news_cache_seconds: float = 600.0
    bot_news_max_items: int = 20
    bot_download_concurrency: int = 8
    # 装有 aria2c 时自动委托多连接下载（-x16 免预分配）；False 强制 yt-dlp 原生并发。
    bot_download_aria2_enabled: bool = True
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
    # H4：此处原有 `bot_group_digest_enabled` 字段，全库**零读取**（死字段），
    # 而真正生效的总开关是上面的 `bot_shared_group_context_enabled`
    # （唯一读取点 character/shared_group.py）。手册一度把死字段当作
    # "用户操作项 BOT_GROUP_DIGEST_ENABLED=true 即时生效"来指导用户，照做无效，
    # 故删除死字段以消除这个陷阱。
    bot_group_digest_max_turns: int = 150
    bot_group_digest_max_chars: int = 800
    bot_group_digest_llm_enabled: bool = False
    bot_group_digest_llm_ttl_seconds: int = 3600
    # 群摘要白/黑名单（消费点 character/shared_group.py）：名单键已在
    # 运行时 store SETTABLE_KEYS 注册（/bot runtime set 可热改）。
    # list_mode=whitelist 仅名单内群参与摘要注入；blacklist 名单内群排除；
    # 空/off/all/未知不过滤（向后兼容）。全局开关关闭时名单无意义。
    bot_group_digest_list_mode: str = ""
    bot_group_digest_whitelist: list[str] = []
    bot_group_digest_blacklist: list[str] = []
    # 夜间每日通讯总结主动推送（G-DIGEST）：每日 cron 把当日群摘要向
    # 白名单群各推一遍；list_mode 非 whitelist 时不推送任何群（绝不猜群）。
    bot_group_digest_push_enabled: bool = True
    bot_group_digest_push_time: str = "21:30"
    # 日常助理（bot.daily_assist）：收件箱速记 + 定时吃什么推荐 + 早晚简报。
    # 收件箱/菜单/任务清单都是 bot_daily_assist_dir 下的纯文本文件
    # （inbox.md/food.md/tasks.md，手机或 ZCode 可直接编辑）；定时推送目标
    # 只取 push_user_ids 显式名单，名单为空则只记不推（绝不猜人）。
    bot_daily_assist_enabled: bool = True
    bot_daily_assist_dir: str = "data/daily_assist"
    bot_daily_assist_push_user_ids: list[str] = []
    bot_daily_assist_meal_times: list[str] = ["11:15", "17:15"]
    bot_daily_assist_morning_time: str = "09:00"
    bot_daily_assist_evening_time: str = "21:00"
    # 校园自动转发（campus v1）：监听学校 QQ 账号（NapCat 第二实例）所在
    # 群的文本消息，实时私聊转发给主人。纯监听，绝不向学校群发送任何消息。
    # 三重门：enabled ∧ self_ids ∧ group_whitelist 任一为空即整链路关闭
    # （绝不猜账号/猜群）；白名单支持 "*" 显式放行学校号全部群。
    bot_campus_enabled: bool = False
    bot_campus_self_ids: list[str] = []
    bot_campus_group_whitelist: list[str] = []
    bot_campus_notify_qq: str = ""
    bot_campus_push_bot_id: str = ""
    bot_campus_db_path: str = "data/campus.sqlite3"
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
    # 占卜娱乐套件（bot.divination）：八字排盘/塔罗牌/金钱卦，纯本地计算、零网络。
    bot_divination_enabled: bool = True
    bot_channel_health_enabled: bool = True
    bot_channel_health_interval_seconds: float = 3600.0
    # 巡检并发/错峰参数（B-2）：background 巡检并发、手动 probe 并发、
    # background 提交错峰间隔；钳位线程 1..16、jitter 0..5.0。
    bot_channel_probe_threads: int = 3            # background 巡检并发
    bot_channel_probe_manual_threads: int = 8     # 手动 /bot model probe 并发
    bot_channel_probe_jitter_seconds: float = 0.4 # background 提交错峰间隔
    # 慢渠道识别（v2 动态检测）：平滑延迟（EWMA）超过该阈值（毫秒）时，
    # 巡检报告对该渠道的「快/正常」评级改标「偏慢」。
    bot_channel_slow_ema_ms: int = 15000
    # 自适应超时（v2 无损切换）：已知渠道 EWMA 时，单次尝试超时收紧为
    # min(原值, max(8s, ema*3))，挂死渠道快速失败转移，不再烧满超时窗口。
    bot_channel_adaptive_timeout: bool = True
    # 影子并发（hedged request，v2 无损无感切换）：健康过滤后候选 ≥2 且非
    # fast_mode 时，首候选发出 hedge_delay 秒仍未回则并发发起次候选，
    # 先到先得；落选请求仍会飞完并正常计费 token（成本换尾延迟）。
    bot_chat_hedged_requests_enabled: bool = True
    bot_chat_hedge_delay_seconds: float = 2.0
    bot_chat_hedge_max_candidates: int = 2
    bot_music_default_mode: str = "card+voice+link"
    # F20（2026-09-12 实弹反馈⑳）：候选选择窗默认开启——同名歌必须先问再播，
    # 不经询问直接播首选曾被用户实弹否决。
    bot_music_candidates_enabled: bool = True
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
    # 视频理解（媒体档案库 + 抽帧/音轨/字幕 → 人格化追问）：
    # 总开关。关闭时完全走旧的 describe_video 抽帧摘要行为，零额外开销。
    bot_video_understanding_enabled: bool = False
    # 媒体档案库：message_id ↔ 视频文件 ↔ 字幕 ↔ 简报 的 SQLite 关联存储。
    bot_media_registry_path: str = "data/media_registry.sqlite3"
    # 档案（含感知简报）保留天数：过期自动剪枝，追问会重新分析；文本量级
    # 上限另受 5000 行 FIFO 约束，不会无限增长。视频文件本身仍由下载缓存
    # 配额（bot_download_cache_max_bytes / max_age_days）单独清理。
    bot_media_registry_ttl_days: int = 7
    # 抽帧数（单次 VLM 调用内的图片预算）与简报硬预算：到点用已完成的信号合成。
    bot_video_max_frames: int = 6
    bot_video_brief_deadline_seconds: float = 75.0
    bot_video_brief_max_chars: int = 1200
    # 音轨转写：已有平台 CC 字幕时默认跳过 ASR（字幕已含语言信息，ASR 是纯增量成本）。
    # 默认分析前 600 秒（10 分钟）；ASR 超时随上限缩放（上限的 25%，封顶 150s）。
    bot_video_asr_max_seconds: int = 600
    bot_video_skip_asr_with_subtitle: bool = True
    # 原生视频直传（video_url content part，仅部分供应商支持）：默认关，失败自动回退抽帧。
    bot_video_native_input: bool = False
    bot_video_native_max_mb: int = 20
    # 进度提示（"视频我看一下，稍等…"）与同会话节流。
    bot_video_progress_ack_enabled: bool = True
    bot_video_progress_ack_cooldown_seconds: int = 60
    # 模糊追问（无回复引用、文本提到"视频/刚才那个"等指代时用会话内最近档案）：
    # 默认开——口语指代（"刚才那个讲了什么"）不再需要 @ 或回复。
    bot_video_fuzzy_followup: bool = True
    # 自然语言深挖（"再仔细看看/没看懂"命中时重新分析）：更多帧 + 音频放宽 + 强制 ASR。
    bot_video_deep_enabled: bool = True
    bot_video_deep_frames: int = 16
    bot_video_deep_asr_max_seconds: int = 1800
    bot_video_deep_deadline_seconds: float = 150.0
    # 媒体归档（bot.media_archive）：用户发媒体+指令（收藏/归档/archive）→
    # VLM 分析内容 → 类别×IP（作品来源）双层目录落盘（cosplay/二次元插图等），
    # sha256 去重 + JSON 旁车元数据；聊天记录走 get_forward_msg 展开归 Markdown。
    bot_media_archive_enabled: bool = True
    bot_media_archive_dir: str = "data/media_archive"
    bot_media_archive_db_path: str = "data/media_archive.sqlite3"
    # 触发角色门槛（user<trusted<enterprise<admin<super_admin）：默认仅超管
    # （归档落本机磁盘）；放开全员改 user，配额与冷却照常生效。
    bot_media_archive_min_role: str = "super_admin"
    bot_media_archive_max_file_mb: int = 100
    bot_media_archive_daily_limit: int = 50
    bot_media_archive_per_message_limit: int = 4
    # 聊天记录归档附一句 VLM 摘要（复用识图 registry；关闭则纯文本归档）。
    bot_media_archive_summary_enabled: bool = True
    bot_media_archive_video_frames: int = 5
    # 笔记/备忘录（bot.notes）：Markdown 笔记+待办勾选+图片收纳；
    # 「做完了/完成了」自然语言勾选对应事项，展示与提醒语气分型人格化。
    bot_notes_enabled: bool = True
    bot_notes_db_path: str = "data/notes.sqlite3"
    bot_notes_max_per_chat: int = 200
    # 联网授时（bot.timesync）：NTP 校准提醒/调度的时间基准（不改系统钟，
    # 只提供校正后的 now；全部服务器超时则回退系统钟并记告警）。
    bot_time_sync_enabled: bool = True
    bot_time_sync_servers: str = "ntp.aliyun.com,cn.ntp.org.cn,pool.ntp.org"
    bot_time_sync_max_drift_ms: int = 1500
    # 统一错误报告卡（bot.error_card）：能力异常时向触发者回云母诊断卡
    # （方法名/栈摘录/脱敏配置/版本/平台协议/IDs/运行时长+求助指引）。
    bot_error_card_enabled: bool = True
    bot_error_card_cooldown_seconds: int = 60
    bot_error_card_stack_frames: int = 8
    # 渲染 Phase 2（perf-optimization-plan §三）：并发上限与单卡等待预算，
    # 缺省=字节级现状（并发 1/预算 0=不生效）；解锁值经 .env 或 driver config。
    bot_render_max_concurrency: int = 1
    bot_render_wait_budget_ms: int = 0
    # 表情回应（bot.reactions）：识别 QQ(NapCat)/TG 消息贴纸回应并注入人格
    # 上下文；bot 按心情/好感/概率主动给消息贴表情（NapCat set_msg_emoji_like）。
    bot_reactions_enabled: bool = True
    bot_reactions_probability: float = 0.2
    bot_reactions_cooldown_seconds: int = 30
    bot_reactions_max_per_hour: int = 20
    # NSFW 直接删除阈值（淫秽色情不存储）：>= 该分数删除文件与记录。
    bot_meme_library_nsfw_delete: float = 0.8
    # 群图下载代理（默认直连 QQ 多媒体源；外网源可走 7890）。
    bot_meme_library_proxy: str = ""
    # 自然语言命令层（基层路由优先级 45）：“帮我查天气”等归一化执行。
    bot_natural_command_enabled: bool = True
    # 群聊自动接话：enabled=true 时按 probability 对未点名的群消息
    # 抽签回复（确定性哈希，不是随机数）；默认关闭，点名/命令不受影响。
    bot_group_chat_auto_reply_enabled: bool = False
    bot_group_chat_auto_reply_probability: float = 0.004  # 2026-09-12 实弹反馈调低：5%/条 会频繁主动接话并自我触发限流
    bot_group_welcome_enabled: bool = True  # 审查 B-05：入群欢迎语（退群/管理变更只记事件不发言）
    bot_group_proactive_max_replies_per_hour: int = 6
    bot_group_proactive_cooldown_seconds: int = 90
    # N4：主动搭话亲和门——群聊抽签主动接话只对好感档 ≥ 亲近（close）的用户
    # 触发；会话冷却与每小时频控沿用上面两项（rate_limit 层已实现）。
    bot_proactive_affinity_gate_enabled: bool = True
    bot_poke_enabled: bool = True
    bot_poke_private_cooldown_seconds: float = 30.0
    bot_poke_group_cooldown_seconds: float = 10.0
    bot_poke_probability: float = 1.0
    bot_poke_admin_bypass: bool = False
    # 统一戳一戳分发（capabilities.poke.PokeDispatcher）：回戳与话术可配。
    bot_poke_reply_enabled: bool = True
    bot_poke_poke_back: bool = False
    bot_poke_group_text: str = ""
    bot_poke_private_text: str = ""
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
    # 试听音频下载目录（capabilities/music.py）。此前无此字段，消费点
    # getattr 兜底 "data/music" 是纯 CWD 相对路径，独立入口会把音频
    # 写进源码树；收口为正式字段并纳入下方 data/ 重映射。
    bot_music_dir: str = "data/music"
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
    # 按**条数**触发合并转发：切分后条数达到该值即合并（用户口径"超过 3 条就
    # 合并"→ 4）。0=关闭该规则，只看 min_chars。
    bot_render_forward_min_nodes: int = 4
    bot_render_forward_max_nodes: int = 0
    bot_render_forward_node_chars: int = 900
    bot_audit_log_file: str = ""
    bot_audit_log_max_bytes: int = 2097152
    # prompt audit 配置组：当前仅 prompt_preview CLI 使用（bot_prompt_audit_dir /
    # bot_prompt_audit_max_chars），主链路不读取；保留字段供 CLI 与未来扩展。
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
    # H3：registry 里 ds-official-flash / -flash-vision / -pro 三条目都引用
    # `env:BOT_API_KEY_DEEPSEEK_OFFICIAL`，但字段长期缺失 → `_resolve_api_key`
    # 的 Config 回退取不到值，即使 .env 填了 key 也恒判 config_missing
    # （09-09「五连发全失败」同类事故的第三次）。字段必须与 .env 同名小写。
    bot_api_key_deepseek_official: str = ""
    # axonhub 统一网关的 key 槽位（本地 OpenAI 兼容端点，默认模型与故障转移
    # 都挂在它上面）。同样必须存在，否则 registry 里的 env: 引用解析为空。
    bot_api_key_axonhub: str = ""
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
    bot_chat_timeout_seconds: float = 20.0
    # QQ/群聊快速响应模式：限制上下文、输出和联网前置工作，优先首字响应速度。
    bot_chat_fast_mode: bool = True
    bot_chat_fast_max_tokens: int = 65538
    bot_chat_fast_max_candidates: int = 0
    bot_chat_fast_timeout_seconds: float = 20.0
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
    # R3 防刷屏：同一发送者两次 bot.chat 回复最小间隔（秒），0=关闭。
    bot_rate_limit_chat_sender_min_interval_seconds: int = 45
    bot_rate_limit_target_min_interval_seconds: int = 0
    # 群聊专属句数帽（用户口径：每小时 60 句、每分钟 3 句）。0 = 该帽不生效。
    bot_rate_limit_group_max_per_hour: int = 0
    bot_rate_limit_group_max_per_minute: int = 0
    # 用户情绪低落时的限流豁免：安抚不该被句数帽挡住。
    bot_rate_limit_emotion_exempt: bool = True
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
    # 审查 J-02（用户「所有子模块可开关」硬要求）：订阅 per-platform 开关。
    # 键名与 sources/subscriptions V2 注册表 resolve 出的 target.platform
    # 标识逐字对齐（xiaohongshu 即小红书/xhs；music 平台的实际标识是
    # netease——MusicSubscriptionAdapterV2 以 provider 名落 platform 字段）。
    # twitter 已在 J-01 摘除（add 即无凭证人话拒绝），不设键。
    # 叠加语义：bot_subscribe_enabled 总开关（路由层拦截整个订阅系统）关=
    # 一切订阅不可用；平台开关关=仅该平台 add 显式拒绝、轮询跳过，既有
    # 订阅行保留（重开自动恢复），其余平台不受影响。默认全开=现状零变化。
    # config 实例进程启动时固定（调度器装配期快照，同台账 #3 口径），
    # 改键需重启生效，不做热改。
    bot_subscribe_platform_bilibili: bool = True
    bot_subscribe_platform_xiaohongshu: bool = True
    bot_subscribe_platform_youtube: bool = True
    bot_subscribe_platform_telegram: bool = True
    bot_subscribe_platform_pixiv: bool = True
    bot_subscribe_platform_weibo: bool = True
    bot_subscribe_platform_netease: bool = True
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

    @field_validator("bot_decision_engine_mode")
    @classmethod
    def _normalize_decision_engine_mode(cls, value: str) -> str:
        # fail-closed：非法值一律回落 legacy_only（引擎骨架阶段零行为变化）。
        normalized = str(value or "").strip().lower()
        if normalized in {"legacy_only", "shadow", "engine_only"}:
            return normalized
        return "legacy_only"

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
            # 与 scripts/runtime_paths.py 对齐：剥 ./ 前缀并对 data/ 前缀
            # 大小写不敏感重映射，两侧对 "./DATA/x" 得到同一结果。
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized.lower() == "data":
                return str(data_root)
            if normalized.lower().startswith("data/"):
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
            "bot_reflection_db_path",
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
            # DATAFIX（2026-09-12）：以下字段此前遗漏在重映射之外，默认值
            # 保持 data/ 相对路径，getattr 兜底消费点按 CWD 解析会把运行时
            # 数据写进源码树（实际泄漏：usage_report_state.json）。其余
            # mood/quirks 等 CursorStore 字段虽在调用点二次兜底，仍统一
            # 收口到本解析器，保证任何入口拿到绝对路径。
            "bot_usage_report_state_file",
            "bot_media_registry_path",
            "bot_music_dir",
            "bot_mood_db_path",
            "bot_quirks_db_path",
            "bot_session_identity_db_path",
            "bot_addressing_preferences_db_path",
            "bot_reminder_db_path",
            "bot_affinity_db_path",
            "bot_media_archive_dir",
            "bot_media_archive_db_path",
            "bot_notes_db_path",
            "bot_campus_db_path",
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
        "bot_super_admin_user_ids",
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
        "bot_group_digest_whitelist",
        "bot_group_digest_blacklist",
        "bot_randpic_dirs",
        "bot_randpic_trigger_words",
        "bot_campus_self_ids",
        "bot_campus_group_whitelist",
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
        "bot_campus_notify_qq",
        "bot_campus_push_bot_id",
        "bot_gscore_bot_self_id",
        mode="before",
    )
    @classmethod
    def _coerce_scalar_id_to_str(cls, value: Any) -> Any:
        """QQ 号标量键宽容装载：nonebot dotenv 会把不带引号的 3865067623
        解析成 int（生产 .env 实弹 2026-09-15 启动崩溃实锤），strict str
        校验直接拒收整插件。标量 id 语义无歧义，int→str 收编（bool 显式
        排除防 True→"True"）；其余类型原样交既有校验保持报错口径。
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        return value

    @field_validator(
        "bot_admin_profiles",
        "bot_disconnect_notice_mail_recipients",
        "bot_disconnect_notice_telegram_chat_ids",
        "bot_wiki_entry_pages",
        mode="before",
    )
    @classmethod
    def _decode_json_collection_strings(cls, value: Any) -> Any:
        """裸 JSON 串兜底（旁路装载路径）：list/dict 字段收到以 {/[ 开头的
        字符串且 json.loads 合法时解码；其余输入原样返回，交给既有校验，
        错误信息保持不变。与 nonebot dotenv 用户键解析同语义（生产主链路
        靠它在 driver config 里已完成解码，此处补齐非 smoke 旁路）。
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped or stripped[0] not in "{[":
            return value
        try:
            return json.loads(stripped)
        except ValueError:
            return value

    @field_validator("bot_group_digest_push_time")
    @classmethod
    def _validate_digest_push_clock(cls, value: str) -> str:
        # 与安静时间键（policy/quiet_hours.QuietHoursSettings.validate_clock_time）
        # 同款 HH:MM 校验风格：两段数字、时 0-23、分 0-59，返回去空白形式。
        text = str(value or "").strip()
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("bot_group_digest_push_time must use HH:MM")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError(
                "bot_group_digest_push_time must use numeric HH:MM"
            ) from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("bot_group_digest_push_time is out of range")
        return text

    @field_validator("bot_persona_alt_profiles", mode="before")
    @classmethod
    def _parse_alt_profiles(cls, value: Any, info: ValidationInfo) -> dict[str, dict[str, Any]]:
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
            except ValueError as exc:
                # 解析失败只报键名与异常摘要（禁止打出配置内容防密钥泄漏），
                # 保持返回空值的既有降级行为，不做启动硬失败。
                _logger.error(
                    "配置项 %s JSON 解析失败，按空值降级（%s: %s）",
                    info.field_name,
                    type(exc).__name__,
                    exc,
                )
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
    def _parse_model_dicts(cls, value: Any, info: ValidationInfo) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                # 例：BOT_MODEL_REGISTRY 少一个引号会让全部渠道无声降级为单
                # 模型；至少要 ERROR 级别可见（只报键名，不打出配置内容）。
                _logger.error(
                    "配置项 %s JSON 解析失败，按空值降级（%s: %s）",
                    info.field_name,
                    type(exc).__name__,
                    exc,
                )
                return {}
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        return {}

    @field_validator("bot_model_priority_groups", mode="before")
    @classmethod
    def _parse_model_priority_groups(cls, value: Any, info: ValidationInfo) -> list[dict[str, Any]]:
        """BOT_MODEL_PRIORITY_GROUPS：接受 JSON 数组字符串或 list[dict]。"""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                _logger.error(
                    "配置项 %s JSON 解析失败，按空值降级（%s: %s）",
                    info.field_name,
                    type(exc).__name__,
                    exc,
                )
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
            raise ValueError("BOT_TRANSPORT_TIMEOUT_SECONDS 必须在 (0, 600] 秒之间（0 不合法）")
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
    def _parse_probe_urls(cls, value: Any, info: ValidationInfo) -> dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                _logger.error(
                    "配置项 %s JSON 解析失败，按空值降级（%s: %s）",
                    info.field_name,
                    type(exc).__name__,
                    exc,
                )
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
