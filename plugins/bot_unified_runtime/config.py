from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

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


# 群主动接话概率的唯一数值源（2026-09-24 用户裁定：图片/表情包/视频类与文字
# 接话同一个 4‰——「与文字接话同一个概率，禁两处各写一份数字」）。
# bot_group_chat_auto_reply_probability 与 bot_vision_reply_probability 的缺省
# 都取自这里；行为面上抽签只经 policy/gate.py::group_proactive_probability()
# 这一个读点取值（vision_reply_probability 字段已退役为判定输入）。
# 数值沿革：2026-09-12 实弹反馈把 5%/条 调到这里——"频繁主动接话并自我触发限流"。
GROUP_PROACTIVE_REPLY_PROBABILITY = 0.004


# 语音预设白名单（G-2 契约层）：=domains/media/tts_presets.py 的
# PRESET_REGISTRY 键集。此处用字面量而非 import，保持 config.py 零包内依赖
# （根 __init__ → config 装载顺序下 import domains 有初始化环风险）；
# 一致性漂移由 tests/test_tts_presets.py::test_config_preset_ids_stay_in_sync_with_registry 锁死。
TTS_PRESET_IDS: frozenset[str] = frozenset({"shorekeeper"})


# bot_tts_api_url 装载期 SSRF 闸的 loopback 白名单字面量（M-32 / T94）。
_TTS_API_URL_LOOPBACK_NAMES: frozenset[str] = frozenset({"localhost"})


def _tts_api_url_host_is_loopback(host: str) -> bool:
    """host 能否在装载期**无歧义证明**指向本机 loopback（fail-closed 白名单）。

    只认两类形态：①``localhost`` 字面量（大小写/结尾点归一后）；②
    ``ipaddress`` 可解析的 IP 字面量且落在 loopback（127.0.0.0/8、::1；
    IPv4-mapped 的 ::ffff:127.0.0.1 解包后判定，映射到内网/元数据的不算）。
    其余一律 False：十进制/十六进制/八进制整型 IP（2130706433/0x7f000001/
    017700000001）、缩写点分（127.1）、任何需要 DNS 的域名——装载期不做
    DNS，无法无歧义证明=拒绝（对齐 link_parse/parsers/ssrf_guard F-04
    「解析失败=拒绝」口径，黑名单网段参照 domains/files downloader）。
    """
    import ipaddress

    normalized = host.strip().casefold().rstrip(".")
    if normalized in _TTS_API_URL_LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


#: ``_resolve_runtime_data_paths`` 消费的标量路径字段名册（单一来源）。
#: A-8 席位（2026-09-27 裁定）把这条名册从 validator 局部提到模块级：常驻断言
#: 「生产配置值 ∈ 允许根」（tests/test_config_root_registration.py）要按**同一张**
#: 名册逐字段过 ``paths.check_registered_domain``，局部元组会逼测试抄一份口径
#: （第二真身）。列表路径字段（``PATH_LIST_REMAPPED_FIELDS``）逐条走同一 resolve。
#: 增删字段只改这里，validator 与断言两侧不再各自维护。
PATH_REMAPPED_FIELDS: Final[tuple[str, ...]] = (
    "bot_control_plane_config_db",
    "bot_control_plane_events_db",
    "bot_control_plane_workspaces_db",
    "bot_control_plane_features_db",
    "bot_control_plane_platform_db",
    "bot_control_plane_actions_db",
    "bot_control_plane_features_file",
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
    # 中央出站闸计数库（B4-spec §1.5）：缺 data/ 相对路径，必须经
    # runtime_paths 重映射到 ChatBot_Runtime（铁律 6）。
    "bot_outbound_gate_db_path",
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
    "bot_emergency_info_db_path",
    "bot_reactions_db_path",
    "bot_teaching_db_path",
    "bot_tts_output_dir",
    "bot_schedule_db_path",
    "bot_schedule_exceptions_path",
    # M-52（T125）：TTS 引擎目录键收口。语义=GPT-SoVITS 程序目录
    # （生产为 C:/Software 绝对路径）；本解析器对非 data/ 值（含绝对
    # 路径与空串）原样透传=既有行为零变化，入册仅防未来误配 data/
    # 相对值时被 tts._resolve_ref_path 按 CWD join 落源码树（铁律 6）。
    "bot_tts_gptsovits_dir",
)

#: 列表形态的路径字段（逐条 resolve，与标量名册同一把尺）。
PATH_LIST_REMAPPED_FIELDS: Final[tuple[str, ...]] = (
    "bot_persona_files",
    "bot_knowledge_files",
    "bot_trend_files",
    "bot_glossary_files",
    # 文件写盘口白名单根＝路径值，逐条走同一 resolve（铁律 6：源码树零
    # data/）；缺省空表 ⇒ resolve([])＝[]，装配层按「空＝回落 export」处理。
    "bot_files_write_allowed_dirs",
)


class Config(BaseModel):
    # 运行数据与源码工作区分离：生产环境可把 data/ 放到工作区外，
    # 其余配置仍可继续使用 data/... 的相对写法，由下方校验器统一解析。
    bot_runtime_data_dir: str = "data"
    bot_runtime_enabled: bool = True
    # 入站事件幂等表（P0.4）：重连重放的同事件对同一能力只处理一次；默认关闭，
    # 建议真实 SnowLuma 验收期间保持关闭，验收通过后再启用。
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
    bot_control_plane_enabled: bool = False
    bot_control_plane_host: str = "127.0.0.1"
    bot_control_plane_port: int = Field(default=8742, ge=1, le=65535)
    bot_control_plane_token_sha256: str = ""
    bot_control_plane_host_allowlist: list[str] | str = ""
    bot_control_plane_config_db: str = "data/control_plane_config.sqlite3"
    bot_control_plane_events_db: str = "data/control_plane_events.sqlite3"
    bot_control_plane_workspaces_db: str = "data/control_plane_workspaces.sqlite3"
    bot_control_plane_features_db: str = "data/control_plane_features.sqlite3"
    bot_control_plane_platform_db: str = "data/control_plane_platform.sqlite3"
    bot_control_plane_actions_db: str = "data/control_plane_actions.sqlite3"
    bot_control_plane_features_file: str = "data/control_plane_features.json"
    bot_control_plane_super_admin_token_sha256: str = ""
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
    # 每批嵌入行数：本地 Ollama 实测 128 最快（约为批 10 的 6 倍吞吐）。
    # 批大小与嵌入超时是配比：装不下时嵌入侧按批折半自调（下限 10，恰好也是
    # 远程单批上限），所以超时偏短或回落远程链只降吞吐，不再整轮中止。
    bot_kb_wiki_embed_batch: int = 128
    # 每日增量同步时刻（Crawl Wiki 每日 23:00 导出之后）。
    bot_kb_wiki_sync_hour: int = 23
    bot_kb_wiki_sync_minute: int = 40
    bot_kb_wiki_sync_on_startup: bool = True
    # —— V2.1 S8：教导知识库与数据库安全查询代理（V21-TEACH-001 /
    # V21-DB-001；装配见 domains/chat_reply/runtime/service_wiring.py，受下方主门缺省关约束）——
    # 教导知识库：用户提议→管理员审核→生效为「背景知识」注入（仅供理解、
    # 禁止复述；结构上不可达人格/权限/路由面）。
    bot_teaching_enabled: bool = True
    bot_teaching_db_path: str = "data/teaching_knowledge.sqlite3"
    # 数据库安全查询代理：仅注册 query_id 的参数化只读查询（白名单
    # registry + 参数 schema + 2s 超时 + 200 行限额；禁任意表/排序/SQL）。
    bot_database_broker_enabled: bool = True
    # —— V2.1 B2① 服务装配组主门（V21-WORLD-001/V21-KB-001/V21-DB-001/
    # V21-TEACH-001；domains/chat_reply/runtime/service_wiring.py 装配+注册表）——缺省关=零装配
    # 零副作用，不改变现网行为；开启后仍受各分门（上方 teaching/broker 既有
    # 键与下方 worldbook/knowledge 两键）约束。L41 memory 待用户裁决不接。
    bot_v21_service_wiring_enabled: bool = False
    # 世界书服务分门（worldbook_service.py：悬空/循环引用+Token 预算+草稿隔离）。
    bot_worldbook_enabled: bool = False
    # 知识检索服务分门（knowledge_service.py：FTS/向量/RRF 三通道+原子重建）。
    bot_knowledge_service_enabled: bool = False
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
    # ---- 记忆/反思 v2 总线（WP6，规格 docs/design/memory-reflection-v2-design.md）----
    # 九键缺省保守＝整体关闭：`bus_enabled=False` 时读写全走旧路径（灰度期可一键回退）。
    # 热改面本轮**不登记** `SETTABLE_KEYS`：登记而不接 `_RUNTIME_HOT_OVERRIDE_FIELDS`
    # 合并层=假热改（本仓已定罪的形态），收尾证明读路径逐调用现读后再裁。
    bot_memory_bus_enabled: bool = False
    # bus=反思结果写新总线；legacy=只写旧 reflection_facts（回退位）。
    bot_memory_reflected_write_target: str = "legacy"
    bot_memory_strength_k: float = 3.0
    bot_memory_tau_stable_days: int = 180
    bot_memory_tau_seasonal_days: int = 45
    bot_memory_tau_episodic_days: int = 14
    # 召回打分权重 JSON 文本（w_rel/w_str/w_rec/w_red）；空串或非法 JSON=按代码缺省，
    # 并在首次解析失败时点名一次告警（不静默猜权重）。
    bot_memory_relevance_weights: str = ""
    bot_memory_per_category_max: int = 1
    bot_memory_semantic_recall_enabled: bool = True
    # ---- 好感度 v7（WP7，规格 docs/design/affinity-v7-design.md）----
    # 关闭时逐字节保持 v5/v6 现行为；开启后分数由潜变量 z 经 tanh 映射（结构上不可触顶）。
    bot_affinity_v7_enabled: bool = False
    bot_affinity_base_step: float = 0.10
    # 跨日新鲜度 EMA 比率与半衰光晕天数（治「连发敷衍短句也涨分」）。
    bot_affinity_novelty_ratio: float = 0.90
    bot_affinity_novelty_halo_days: int = 21
    # 按人活跃归一的参考轮次（治「话痨增速碾压轻度用户」）。
    bot_affinity_rhythm_reference_turns: int = 8
    # 单事件 |Δz| 上限（键名历史只钳负向，2026-09-26 A-1 裁定起正负同帽）、
    # 总位移上限（窗形=滚动 24h，旧「本地自然日」窗作废）、熔断事件数
    # （护栏，不可被设定架空）。
    bot_affinity_negative_event_cap_z: float = 0.10
    bot_affinity_daily_move_cap_z: float = 0.12
    bot_affinity_fuse_daily_events: int = 25
    bot_affinity_repair_gain: float = 1.4
    # tanh 饱和域硬边界（score 永不触 ±100）。
    bot_affinity_z_hard_bound: float = 0.985
    # 质量分五子权重与衰减时间常数：JSON 文本，空/非法=按代码缺省并点名一次。
    bot_affinity_quality_weights: str = ""
    bot_affinity_decay_tau_days: str = ""
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
    # SnowLuma 断线不可投才置 FAILED_FINAL（防非终态行无限堆积）；缺字段 =
    # env 键被 pydantic 丢弃、旋钮恒默认（§14.4.2：env 键须有同名小写字段）。
    bot_send_bot_unavailable_max_age_seconds: float = 1800.0
    # 中央出站防风暴闸（B4-spec §1；真身
    # domains/transport/sender/outbound_gate.py）：聚合域（紧急信息等）**一切主动投递**
    # 触达 SendQueue.submit 的唯一入口，按序过三道门——静默顺延 / 每主体 60s·3600s
    # 双滑窗限流 / dedupe 键规范核验。缺省=关闭：闸的唯一入口直通裸 submit，
    # 现役 6 族与消息流回复零改动（规格 §1.5 唯一硬约束=enabled 缺省 False）。
    # 窗上限 0=该窗不生效（与 bot_rate_limit_group_max_per_* 同口径，缺省绝不拦死投递）。
    # db_path 必须进 path_fields 重映射（铁律 6：源码树零 data/，先例 bot_campus_db_path）。
    bot_outbound_gate_enabled: bool = False
    bot_outbound_gate_quiet_defer_enabled: bool = True
    bot_outbound_gate_urgent_severities: list[str] = ["P0", "P1"]
    bot_outbound_gate_max_per_target_per_minute: int = 2
    bot_outbound_gate_max_per_target_per_hour: int = 6
    bot_outbound_gate_db_path: str = "data/outbound_gate.sqlite3"
    # TTL（开闸 A 案第二腿，用户 2026-09-25 裁定「开，A+B」）：闸的**自动到期时刻**，
    # ISO-8601 字面量。到期即等同 enabled=False 并响亮留痕，不需要谁记得回来手工关掉
    # ——「临时停用要自动到期、不留人工回滚债」。缺省空串=**无到期**，此时有效开启
    # 逐字节等于 `bot_outbound_gate_enabled` 本身 ⇒ 新键落地不改变任何现网读数。
    # 判据唯一真身 outbound_gate.py::effective_gate_enabled（读不到/解不出=宁关不猜）；
    # 解析真身 domains/core/moment_parsing.py::parse_moment。热改档位=需重启（本族键
    # 不在 _RUNTIME_HOT_OVERRIDE_FIELDS 里，登记见 runtime/settings.py RESTART_REQUIRED_KEYS）。
    bot_outbound_gate_enabled_until: str = ""
    # 送达核验总开关（B4-spec §3.2 Tier1-a）：开启时 OneBot 本地摘段会给回执挂
    # OperationalIssue(kind=segment_dropped_local)——治「谎报送达」。消费方在
    # domains/transport/sender/onebot.py（B4b 席独占面），SnowLuma 侧未取证前生产不开；
    # 缺省 False=现状字节级不动。config.py 本波唯一登记人=B4a，故该键在此落账。
    bot_outbound_verify_enabled: bool = False
    # SAFE-EXEC 裁定第 18 项（2026-09-26）：书面同意执法门总闸（唯一读点
    # =domains/core/safety_exec/consent.py::ConsentPolicy.from_config 装配期快照，
    # 装载链 runtime/settings.py::configure_safety_gate）。缺省 True＝执法开——
    # 她要的是真门不是货架（「危险的参数设置需要经过超级管理员的书面同意」）；
    # 关它必须改 .env + 重启（本键在 RESTART_REQUIRED_KEYS，护栏不可被一条命令热关）。
    bot_safetyexec_enabled: bool = True
    # 发送层单次请求硬超时（秒）：OneBot/Telegram/Mail 发送共用；
    # 合法范围 (0, 600]，0/负数/NaN/Infinity/超大值在启动校验时直接报错
    # （与 _validate_transport_timeout_seconds 一致，无"回退 15"的隐式兜底）。
    bot_transport_timeout_seconds: float = 15.0
    # 请求级总预算（秒）：单次聊天从 LLM/工具循环到发送共用一个单调 deadline；范围 (0,600]。
    # 生产实弹（2026-09-15）：正常单渠道生成实测 ~54s，五渠道链在 150s 内
    # 必然烧穿尾巴（告警 last=failover:deadline 实锤）——提到 300s 给慢渠道
    # 真实完成机会；校验器上限 600s 不变。
    bot_request_budget_seconds: float = 300.0
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
    # 商品/债券/北向路由开关：base_router:364/378/388 一直在 getattr 读这三个键，
    # 但 Config 里没有 ⇒ 这三路 .env 永远关不掉（2026-09-21 S-W3D 实测、主会话补键）。
    # 缺省 True＝与补键前逐字节同行为（getattr 旧缺省就是 True）。
    bot_commodities_enabled: bool = True
    bot_bond_enabled: bool = True
    bot_northbound_enabled: bool = True
    # 东财空响应受控重试（G2）：限流时 HTTP 200 但业务体为空（空 JSON/缺行），
    # 三源数据层至多重试 1 次（退避 0.6s）；关闭后行为与无重试逐字节一致。
    bot_market_retry_on_empty: bool = True
    bot_market_timeout_seconds: float = 6.0
    bot_market_cache_seconds: float = 60.0
    # 随机图片（bot.randpic）：只读取用户自定义文件夹随机发图，绝不自建目录。
    bot_randpic_enabled: bool = True
    bot_randpic_dirs: list[str] = []
    bot_randpic_trigger_words: list[str] = []
    bot_randpic_max_file_mb: int = 25
    # ---- 随机图池子的内容双下限（B1 波 2026-09-28 建 → 2026-09-29 用户裁定关掉）----
    # 0=关；保留键只为未来想给用户加下限；当前不硬筛 Picture 目录，用户手动管图库。
    # ⚠ 耦合口径（判据真身 = ``domains/meme/capabilities/randpic.py::_scan_dir``）：
    # 文件头魔数验真与图头短边读数都挂在 ``guard_enabled``（任一键 > 0）这枚短路上，
    # 两键同 0 ⇒ 魔数验真一并不参与，扫描行为与 B1 之前逐字节同形；旧缺省 100 KB +
    # 400 px 出自 2026-09-28 现网 Picture 普查，本裁定把它归零。
    # 两键归零后**仍无条件生效**的四层：子目录剪枝 ``_should_prune_dir``、
    # 0 字节空件拒收（``images_empty``）、重解析点不进树（PIC 容器面）、
    # 单张体积上限 ``bot_randpic_max_file_mb``；出口另有登记面收口
    # （``domains/media/path_gate.py``）与出站死引用闸
    # （``domains/transport/sender/onebot.py::_image_segment``）两把。
    # ⚠ 2026-09-29 去重（任务 D1）：这两枚键曾在类体里被**重复声明**过（300 与 400
    # 并存、后者覆盖前者），本块是那一处的唯一残留真身；
    # 行为锁 tests/test_config_fields_no_duplicate.py 禁止第二份定义回流。
    bot_randpic_min_file_kb: int = 0
    bot_randpic_min_side: int = 0
    # ---- 随机发图派发（P14 波，2026-09-25「回复完用户消息 / 用户戳 bot /
    # 特定指令」三触发）。指令触发一直是既有那条；本批加的是「回复完主动发图」
    # 一条（戳 bot 那条走 BOT_POKE_REPLY_MODE=randpic 臂，同一取图口同一本窗账）。
    # 缺省全关=只在用户开口要图时发；开态也过安静时间/blocked 两道硬门。
    bot_randpic_dispatch_enabled: bool = False
    bot_randpic_dispatch_probability: float = 0.1
    bot_randpic_dispatch_cooldown_seconds: float = 600.0
    bot_randpic_dispatch_max_per_hour: int = 2
    # 窗内不重发同一张（按会话记账）。0=关=旧行为逐字节同形（纯随机、可重样）。
    bot_randpic_no_repeat_window_seconds: float = 0.0
    # 语音合成（bot.tts）：对接本机 GPT-SoVITS v2ProPlus 的 api_v2.py HTTP 接口，
    # 把文本合成为守岸人音色的语音消息。缺省全关——语音服务需先单独启动，
    # 未启动时开了也只会得到一句降级文案，故不默认占用。
    # G-2 契约层：合成参数缺省源=中央预设表（domains/media/tts_presets.py），
    # 本节数值键保留为管理员覆盖（env 显式值 > preset；v1 预设值=此处缺省值，
    # 零行为变更）。域值=引擎 WebUI 滑杆（report-T53.md），越界值装载期即拒（M-35）。
    bot_tts_enabled: bool = False
    bot_tts_api_url: str = "http://127.0.0.1:9880"
    # 参考音频基准目录（GPT-SoVITS 程序目录）；BOT_TTS_REF_AUDIOS 里的相对
    # 路径以它为基准解析。
    bot_tts_gptsovits_dir: str = ""
    # 参考音频列表：每项 "路径|参考文本|语种"（后两段可省；文本留空=无参考
    # 文本模式）。硬性要求 3~10 秒干声，多项时随机轮换以贴合不同语气。
    bot_tts_ref_audios: list[str] = []
    bot_tts_trigger_words: list[str] = []
    bot_tts_output_dir: str = "data/tts_output"
    # 语音预设选择（G-2 唯一新选择键）：枚举成员=TTS_PRESET_IDS 白名单
    # （=tts_presets.PRESET_REGISTRY 键集，一致性由 tests/test_tts_presets.py 锁）。
    bot_tts_preset: str = "shorekeeper"
    # 单次合成文本上限；**0=不限（不按字数截断）**——「不限≠无界」，必过
    # bot_tts_hard_max_chars 中央硬顶（M-35 语义反转修死 + G2-R3 硬顶）。
    bot_tts_max_chars: int = Field(default=200, ge=0)
    # 文本硬顶（字）：超顶=拒绝合成+OperationalIssue 留痕，不静默不拆条；
    # 0=禁配无界（取内置常量 2000）。
    bot_tts_hard_max_chars: int = Field(default=2000, ge=0)
    # 产物字节硬顶：v2ProPlus=32000Hz/16bit/单声道 ⇒ 64,000 B/s 恒定，
    # 8 MiB≈131s（G2-R3）；超顶=体检闸拒（tts_bad_audio 族）不入缓存不出站；
    # 0=禁配无界（取内置常量 8 MiB）。换 media_type/采样率须重裁此值。
    bot_tts_max_audio_bytes: int = Field(default=8 * 1024 * 1024, ge=0)
    bot_tts_timeout_seconds: float = Field(default=60.0, ge=1.0)
    bot_tts_speed_factor: float = Field(default=0.85, ge=0.6, le=1.65)
    bot_tts_temperature: float = Field(default=0.9, ge=0.0, le=1.0)
    bot_tts_top_k: int = Field(default=15, ge=1, le=100)
    bot_tts_top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    bot_tts_text_lang: str = "zh"
    bot_tts_text_split_method: str = "cut5"
    bot_tts_cache_enabled: bool = True
    # 产物目录磁盘配额（U-04：data/tts_output 定性=缓存，接中央
    # cache_policy.enforce_quota「最旧先删」）；**缺省 0/0=不限制（字节级行为
    # 不变）**。换缓存键空间产生的旧 wav 孤儿靠它回收（M-27 顺接）。
    bot_tts_cache_max_bytes: int = Field(default=0, ge=0)
    bot_tts_cache_max_age_days: int = Field(default=0, ge=0)
    # 对话自动配音（默认关）：人格回复正文一并合成为语音随消息发出。
    # scope 取 private（仅私聊）/ group（仅群聊）/ all。
    bot_tts_auto_reply_enabled: bool = False
    bot_tts_auto_reply_scope: str = "private"
    # 自动配音文本上限；**0=不限**（同 max_chars 语义，过硬顶）。
    bot_tts_auto_reply_max_chars: int = Field(default=120, ge=0)
    # 长回复拆条的每段音频文本上限（0=不拆条=缺省逐字节现状）：超过此值的
    # 可朗读文本按句末标点切成多块、逐块合成、多段音频随同一条回复发出。
    # 60 秒 ≈ 150~180 字（守岸人语速偏慢，speed 0.85，2026-09-23 按听感校准）。
    bot_tts_auto_reply_split_max_chars: int = Field(default=0, ge=0)
    # 配音概率门：每条符合条件的回复按此概率决定是否配音（默认 10%，
    # 2026-09-25 用户裁定第 8 项由 5% 上调）。
    # 用确定性哈希实现（seed = session_id:message_id），同一条消息结果恒定，
    # 可复现可审计；置 1.0 等价于全量配音。always 置真则直接跳过概率门，
    # 供调试/真机验收时逐条听音。
    # ⚠ 改这里只动「没写这一行时」的缺省：生产 `.env` 显式写着
    # BOT_TTS_AUTO_REPLY_PROBABILITY=0.05，那一行不改则线上仍是 5%。
    bot_tts_auto_reply_probability: float = Field(default=0.10, ge=0.0, le=1.0)
    bot_tts_auto_reply_always: bool = False
    # G-3 配音出站路径开关（M-10/M-13 根修，T54 规格 §4.2）：true=自动配音走
    # pipeline post-review hook（review 批准后的正文才合成；合成失败挂
    # OperationalIssue 走中央告警链）；false=旧能力包装路径（字节级现状）。
    # 双态互斥；装配期冻结（/bot runtime set 不可热改），改后需重启生效。
    bot_tts_voice_hook_enabled: bool = False
    # creation 对接点的 provider 选择器（中央调度收编波 P5/S09 §7 待登记清单）：
    # 空串=未配 ⇒ 域内 `reserved_provider.provider_configured` 判 False ⇒ 诚实 UNAVAILABLE。
    # ⚠ 落地这两键只是把"根本没这个键"改成"有键、待填、待接工厂"：**不**等于绘画可用——
    # provider 适配器工厂尚未存在（填了值也仍诚实 UNAVAILABLE，探测面转为 DEGRADED）。
    # 装配期快照（描述符/探针读点在建表时），故两键登记进 RESTART_REQUIRED_KEYS，不做"看着能热改"。
    bot_creation_image_provider: str = ""
    bot_creation_tts_provider: str = ""
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
    # V21-PERSONA-001：人格核心注入走版本库（draft→publish→activate，带
    # version+sha256 溯源；任何故障 fail-open 回退文件直读路径）。默认 False
    # 保守灰度=旧路径逐字节不变；True 才启用。库=data/persona_versions.sqlite3。
    bot_persona_versioned_injection: bool = False
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
    # 校园自动转发（campus v1）：监听学校 QQ 账号（SnowLuma 第二实例）所在
    # 群的文本消息，实时私聊转发给主人。纯监听，绝不向学校群发送任何消息。
    # 三重门：enabled ∧ self_ids ∧ group_whitelist 任一为空即整链路关闭
    # （绝不猜账号/猜群）；白名单支持 "*" 显式放行学校号全部群。
    bot_campus_enabled: bool = False
    bot_campus_self_ids: list[str] = []
    bot_campus_group_whitelist: list[str] = []
    bot_campus_notify_qq: str = ""
    bot_campus_push_bot_id: str = ""
    bot_campus_db_path: str = "data/campus.sqlite3"
    # 外部紧急信息聚合（bot.emergency_info）：采集→定级→去重→审核→经中央闸按订阅投递。
    # 装配门两腿：总闸 ∧ 有源（2026-09-20 裁定 3.B 覆盖旧「三重来源门」的第三腿）——
    # 投递条件改由群内「紧急信息 订阅 …」现场设立、每轮现读，不再要求 .env 预填群/人。
    # 绝不猜群/绝不猜人一寸没松：订阅表里没有行=零目标=零投递，行只能由群主/管理员写下。
    # 审核名单空=审核面关闭（缺省拒绝而非放行）。
    # 热改口径（WIRE-R2 AST 自验，与 docs/config-catalog-full.md 同档）：**十键全部 ❌无热改面**——
    # SETTABLE_KEYS=41 / RESTART_REQUIRED_KEYS=54 / 交集 ∅，本族十键两者皆不登记；
    # _poll_interval 装配期钉进 APScheduler interval job（无 reschedule 面）、
    # _min_level 注册期一次解算成闭包常量 ⇒ 改这两键同样要重启才生效（同台账 #3 口径）。
    # min_level 值域=EmergencyLevel 字面（P0..P3），非法值按缺省（D-3 不建第二枚举）。
    # auto_approve_sources=D-8(a) 裁定：名单内权威源入库自动过审，其余 pending 走人工审核；空名单=整机制关闭。
    # ⚠ 名单值必须逐字等于源侧 SOURCE_ID 真身，本域现有四个：
    #   `nmc`（sources/nmc_alarm.py:56）、`gdacs`（sources/gdacs.py:43）、
    #   `icl` 与 `usgs`（sources/open_data_quakes.py:52-53）。
    #   写成 `nmc_alarm` 之类模块名不会报错——它会静默不命中，等于该源没过审（fail-closed 的同义副作用）。
    bot_emergency_info_enabled: bool = False
    bot_emergency_info_sources: list[str] = []
    bot_emergency_info_auto_approve_sources: list[str] = []
    bot_emergency_info_poll_interval_seconds: int = 300
    bot_emergency_info_min_level: str = "P2"
    # 这两键自 2026-09-20 起是**可选硬推腿**（不参与装配门）：名单里的目标每轮收全部
    # 已过 min_level 地板的条目，**不受订阅条件约束**。日常按群/按条件推送请用
    # 「紧急信息 订阅 …」（群里设、当轮生效），不必动这里。缺省空=这条腿不存在。
    bot_emergency_info_push_group_whitelist: list[str] = []
    bot_emergency_info_push_user_ids: list[str] = []
    bot_emergency_info_reviewer_ids: list[str] = []
    bot_emergency_info_keep_days: int = 90
    bot_emergency_info_db_path: str = "data/emergency_info.sqlite3"
    # 一致性漂移巡检（domains/ops/sync_drift，S12 救活波）：定期复算「文档/配置/触发词
    # 与代码真身是否还相等」，漂移则三通道报超管。⚠ `alert_enabled` 只在**装配期**读一次
    # （闸不过=连 job 都不注册），改它必须重启；`surfaces`/`max_evidence_lines`/
    # `suppression_seconds` 每轮巡检现读，热改当轮生效。缺省全关=零开销、零告警。
    bot_sync_drift_alert_enabled: bool = False
    # 面名必须逐字等于 registry 登记表里的 `surface` 真身（列表面由
    # `sync_drift.registered_surfaces()` 给）；写错的名字不报错——它静默不在扫描集里。
    # 空表 = 扫全部已登记面。
    bot_sync_drift_surfaces: list[str] = []
    bot_sync_drift_interval_minutes: int = 60
    bot_sync_drift_startup_delay_seconds: int = 65
    # 同（面, 严重度）在此窗口内只报一次，抑制计数如实带在结果里；默认 6 小时。
    bot_sync_drift_suppression_seconds: int = 21600
    # QQ 投递走既有 alerts 中央件的内容 sink；空串=sink 缺省 "queued-onebot"。
    bot_sync_drift_qq_bot_id: str = ""
    bot_sync_drift_max_evidence_lines: int = 12
    # 本族七键与紧急信息十键同口径：既不登记 SETTABLE_KEYS 也不登记 RESTART_REQUIRED_KEYS
    # （运维开关，走 .env；不开放 /bot runtime set，免得给出「热改」的假承诺）。
    # 全场景日程（V2.1 §4，domains/schedule 服务面）：LLM 草稿解析/课表识别/
    # 到点投递三服务与既有 schedule 引擎（schedule_service 族）共库。未接线前
    # 各开关缺省关（不装配=零开销）；投递只到 SendQueue 提交面，真实出站端口
    # 未授权前 request_builder 不注入（诚实不伪装发送）。
    # 2026-09-26 第 20 项波实况：enabled/db_path 两键已被日程板能力真读
    # （domains/schedule/capabilities/schedule_board.py，REMINDER 车道）；
    # llm_draft/timetable/delivery 三键仍是「在册未接线」的原样（诚实挂账）。
    bot_schedule_enabled: bool = False
    bot_schedule_db_path: str = "data/schedules_v21.sqlite3"
    bot_schedule_llm_draft_enabled: bool = False
    bot_schedule_timetable_enabled: bool = False
    bot_schedule_delivery_enabled: bool = False
    bot_schedule_delivery_max_retries: int = 3
    bot_schedule_exceptions_path: str = "data/schedule_exceptions.json"
    # 第 20 项新增两枚：读点在能力/路由侧现读装配期快照 config（getattr 字面名），
    # 未进运行时覆盖合并表 ⇒ 热 set 不可达，已登记 settings.py 的
    # RESTART_REQUIRED_KEYS（改 .env + 重启生效；不做「看着能热改」的假承诺）：
    # 代答腿总闸——关着时「她在干嘛」一类问句完全不进日程路由，零行为变更；
    # 开着也只按分级表投影公开条目（隐私判定在出站前，不靠模型自觉）。
    bot_schedule_status_reply_enabled: bool = False
    # 宽口径自然捕捉闸——关着只认「日程/课表」显式命令与导入；开着才把
    # 「明天8点有课」这类带时间+活动词的短句顺手记进她的日程板（缺省隐私）。
    bot_schedule_natural_capture_enabled: bool = False
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
    # 链尾免 key 兜底（DuckDuckGo → Bing）：有 key 的供应商全部失败/未配置时接管，
    # 永不抢在前面。缺省关——开启会让检索面依赖公开搜索引擎 HTML，结果质量与配额不可控。
    # 只在装配期读一次（链构造即固化），改动需重启。
    bot_web_search_keyfree_fallback_enabled: bool = False
    # ACG 专项竖源检索（v21r2 SEARCH 席）：Bangumi(bgm.tv 无 key)/萌娘百科/B站公开搜索。
    # 总开关默认关（对齐 bot_web_search_enabled 保守缺省）；开启后仅当查询命中二次元意图
    # （番剧/漫画/B站梗/二次元游戏）且未触发安全红线（显式不联网/闲聊/创作等）时并发查竖源，
    # 结果按意图时效档（latest=带日期加权 / background=权威度优先）加权后并入【联网检索】；
    # 单源失败诚实降级为空，不阻断主链路。
    bot_search_acg_enabled: bool = False
    bot_search_acg_bangumi_enabled: bool = True
    bot_search_acg_moegirl_enabled: bool = True
    bot_search_acg_bilibili_enabled: bool = True
    bot_search_acg_timeout_seconds: float = 4.0
    bot_search_acg_max_per_source: int = 3
    # 联网分类遥测：只记录查询哈希、决策、置信度和命中统计，不记录原文。
    bot_web_intent_telemetry_enabled: bool = False
    bot_web_intent_telemetry_db_path: str = "data/web_intent_telemetry.sqlite3"
    bot_web_intent_telemetry_max_items: int = 10000
    # 开启后同时记录旧版分类标签，用于影子对比；不改变新算法线上决策。
    bot_web_classifier_shadow_enabled: bool = False
    # ↓ 以下是「行为」阈值，直接左右是否联网检索（区别于上方只记录不决策的遥测）。
    # 总闸仍是 bot_web_search_enabled；这两个键只在联网已开时决定 FALLBACK（本地
    # 世界观优先）一类问题是否补搜：置信度 = 查询主题词被知识库覆盖的比例（S13 真身）。
    # knowledge_threshold：本地知识可答的门槛，低于它才补搜；默认 0.60 偏高但配合真实
    # 置信度不再压制搜索，须用遥测影子期数据校准。
    bot_web_search_knowledge_threshold: float = 0.60
    # confidence_floor：硬底线安全阀，本地知识近乎空白时无条件补搜一次，独立于可被
    # 调高的 knowledge_threshold，防止误判成「不用搜」。
    bot_web_search_confidence_floor: float = 0.20

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
    # 运势 HTTP 面的签名密钥：读点 facet.py:333 / draw_store.py:481 一直在 getattr 读本键，
    # 而 Config 没有 ⇒ 恒 '' ⇒ fortune_ready 恒 False（运势永久不启用）。缺省 '' = 与补键前同。
    bot_divination_fortune_secret: str = ""
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
    # ---- goal-12 表情包子系统波（2026-09-25）：打标取数 / 本命吸收 / 选图口径 ----
    # 预设名落空时退到注册表里真实存在的第一组。现网实况：.env 把
    # BOT_MEME_LIBRARY_VLM_PRESET 写成空串、注册表里只有 myvlm 一组，旧实现两侧
    # 都取不到 ⇒ 打标静默不跑 ⇒ 库里的图全没标签（表现是「选图像随机」）。
    # 关掉本键即逐字节回到旧行为。注册表真为空时两档都不打标（不猜端点）。
    bot_meme_library_vlm_fallback_first_preset: bool = True
    # 自动吸收「主体是守岸人」的贴纸：VLM 主体判定命中中央别名（personas/
    # shorekeeper/aliases.txt）⇒ 标本命、吃本命加权、默认豁免按龄裁剪。
    # 不放宽任何收库门（群黑白名单与总闸照旧在调用方）。
    bot_meme_shorekeeper_absorb_enabled: bool = True
    # 本命贴纸豁免「按天」裁剪（bot_meme_library_max_age_days 那一刀）；
    # 按量上限（max_files）仍然生效，否则全标本命就能让库无界增长。
    bot_meme_shorekeeper_protect_from_prune: bool = True
    # 相关性地板：比的是**合格分**（库权重 × 主题相关度），不是排序分。
    # 所以被地板拦下的只有两类：库自己判「不算表情/高危」的（权重 0.25/0.0）与
    # 离题且不熟的（相关度 0.0）；心情降权、口味与本命加成只影响先后顺序，
    # **不参与地板**——否则「低落 × 中性档」=0.175 会被吃掉，软偏置就成了硬开关
    # （旧能力层「全部吵闹也照发」的语义会被本轮悄悄改掉）。
    # 0.35 落在中性档 0.5 之下、非表情 0.25 之下。
    bot_meme_relevance_min: float = 0.35
    # 反重复的作用域口径：global=本机发过即不再发（缺省，钉「同一张绝不发两次」）；
    # session=同时再按会话/群各记一本账（并集判定，比 global 更严，不会更松）。
    bot_meme_sticker_scope_mode: str = "global"
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
    # 白名单1 群里图片/表情包/视频的回复概率：**2026-09-24 用户裁定并入文字
    # 接话同一个概率**——门禁抽签实际只读 `group_proactive_probability()`
    # （policy/gate.py 唯一读点），本键自 此 不 再 参 与 判定，仅为兼容 .env
    # 旧行保留（生产 .env 仍写着 1.0，现已失效，建议用户删除该行）。
    # 缺省与文字同源（GROUP_PROACTIVE_REPLY_PROBABILITY），禁两处各写一份数字。
    bot_vision_reply_probability: float = GROUP_PROACTIVE_REPLY_PROBABILITY
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
    # 视频深挖冷却窗（chat.py:447 getattr 读此键；同族的 enabled/fuzzy_followup 都在册，唯此键漏声明）。
    bot_video_deep_cooldown_seconds: int = 300
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
    # HTTPS 授时兜底（R3 停摆批 2026-09-17）：UDP 123 被墙时 NTP 全败转
    # HTTPS Date 头（RFC 7231）估偏移；失败链 NTP→HTTPS→系统钟，复用
    # ±1.5s 钳制；仅收 https:// 端点，url 留空=内置 baidu/taobao/qq。
    bot_time_sync_http_enabled: bool = True
    bot_time_sync_http_url: str = ""
    # 统一错误报告卡（bot.error_card）：能力异常时向触发者回云母诊断卡
    # （方法名/栈摘录/脱敏配置/版本/平台协议/IDs/运行时长+求助指引）。
    bot_error_card_enabled: bool = True
    bot_error_card_cooldown_seconds: int = 60
    bot_error_card_stack_frames: int = 8
    # 渲染 Phase 2（perf-optimization-plan §三）：并发上限与单卡等待预算，
    # 缺省=字节级现状（并发 1/预算 0=不生效）；解锁值经 .env 或 driver config。
    bot_render_max_concurrency: int = 1
    bot_render_wait_budget_ms: int = 0
    # 表情回应（bot.reactions）：识别 QQ(SnowLuma)/TG 消息贴纸回应并注入人格
    # 上下文；bot 按心情/好感/概率主动给消息贴表情（SnowLuma set_msg_emoji_like）。
    bot_reactions_enabled: bool = True
    bot_reactions_probability: float = 0.2
    bot_reactions_cooldown_seconds: int = 30
    bot_reactions_max_per_hour: int = 20
    # 贴纸回应持久化（B 线 2026-09-16：把所有表情贴纸存下来）：识别事件双写
    # 落库 + 按 emoji 聚合统计；保留期裁剪防无界增长。
    bot_reactions_db_path: str = "data/reactions.sqlite3"
    bot_reactions_store_days: int = 90
    # 双层表情·第二层（情绪时刻发表情包）：从表情库按 VLM 情绪标签加权抽图
    # 发送；与第一层贴小表情互斥（同消息先贴后包）；C1 悲伤词族整条不贴。
    bot_reactions_meme_enabled: bool = True
    bot_reactions_meme_probability: float = 0.15
    bot_reactions_meme_cooldown_seconds: int = 120
    bot_reactions_meme_daily_max: int = 6
    # NSFW 直接删除阈值（淫秽色情不存储）：>= 该分数删除文件与记录。
    bot_meme_library_nsfw_delete: float = 0.8
    # 群图下载代理（默认直连 QQ 多媒体源；外网源可走 7890）。
    bot_meme_library_proxy: str = ""
    # 自然语言命令层（基层路由优先级 45）：“帮我查天气”等归一化执行。
    bot_natural_command_enabled: bool = True
    # 群聊自动接话：enabled=true 时按 probability 对未点名的群消息
    # 抽签回复（确定性哈希，不是随机数）；默认关闭，点名/命令不受影响。
    bot_group_chat_auto_reply_enabled: bool = False
    # 数值唯一真身在模块头 GROUP_PROACTIVE_REPLY_PROBABILITY（图片类同源同值）。
    bot_group_chat_auto_reply_probability: float = GROUP_PROACTIVE_REPLY_PROBABILITY
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
    # 用户裁定（2026-09-16）：回戳进五件套，缺省开（NapCat 时期不支持时静默）。
    bot_poke_poke_back: bool = True
    bot_poke_group_text: str = ""
    bot_poke_private_text: str = ""
    # 戳一戳回复形态（poke v2）：mix=固定话术/LLM 话术/表情包 三选一确定性
    # 轮换；fixed=固定话术；llm=LLM 话术（失败回退固定）；meme=表情包
    # （库空回退固定）。群聊回复自动 @戳者。
    bot_poke_reply_mode: str = "mix"
    # 戳一戳好感度：门控放行后记一笔小额正向互动（V2.1 §2.2 经 observe_points
    # 唯一适配器按「分」口径入账）；poke_gain_points=0.1 分/戳、
    # poke_gain_24h=0.5 分（来源专项 24h 滚动预算，全局增益预算另兜底）；
    # daily_max=0 表示不记好感。
    bot_poke_affinity_enabled: bool = True
    bot_poke_affinity_delta: float = 0.1
    bot_poke_affinity_daily_max: float = 0.5
    # ---- 戳一戳臂矩阵扩臂（P14 波，2026-09-25 用户裁定「被戳→反戳/自然语言/
    # 语音+文本/表情包/随机图 任意一个」）。缺省 False=mix 轮换池停在旧三臂
    # （fixed/llm/meme）⇒ 与 P14 之前逐字节同形；True=池扩到六臂（多
    # voice/randpic/poke 三臂）。BOT_POKE_REPLY_MODE 显式指名任一臂不受本档影响。
    bot_poke_extra_arms_enabled: bool = False
    # ---- 跟戳：用户 A 在群里戳用户 B 时 bot 有概率跟着戳 B（P14）。缺省关；
    # 独立冷却/每小时上限（QQ 戳很便宜但极刷屏，故与回戳分账，不共用门）。
    bot_poke_follow_enabled: bool = False
    bot_poke_follow_probability: float = 0.2
    bot_poke_follow_cooldown_seconds: float = 120.0
    bot_poke_follow_max_per_hour: int = 4
    # ---- 回复后/主动发言后戳人（P14）：bot 把话说完（含群内主动接话、入群
    # 欢迎这类「bot 先开口」）后按概率戳一下对方。缺省关；两触发共用本族旋钮、
    # 各自独立掷骰。安静时间与 blocked 名单是硬门，拨开开关也越不过。
    bot_poke_after_reply_enabled: bool = False
    bot_poke_after_reply_probability: float = 0.15
    bot_poke_after_reply_cooldown_seconds: float = 300.0
    bot_poke_after_reply_max_per_hour: int = 3
    # R-18 内容感知路由（runtime/content_route.py）：本地信号 L1 强词表 +
    # L2 上下文累积 + L4「亲密模式 开/关」手动钉死（2026-09-17：模型自评
    # 标签层移除——gemini/grok 都把它当注入攻击整轮拒答）；INTIMATE 时自动
    # 候选序=order 配置（grok-4.6 → gemini-3.8-flash，用户裁定 gemini 第二位）
    # 并跳过影子并发。
    bot_content_route_enabled: bool = True
    bot_content_route_model: str = "grok-4.6"
    # INTIMATE 态候选头顺序（逗号分隔模型名；首位=主目标，其余跟后）。
    bot_content_route_order: str = "grok-4.6,gemini-3.8-flash"
    # 追加强词表（逗号/顿号/空白分隔，并入内置表）。
    bot_content_route_words: str = ""
    # 滞回阈值：分数 ≥ intimate → 切 grok；≤ normal → 回默认链；中间保持前态。
    bot_content_route_intimate_threshold: float = 60.0
    bot_content_route_normal_threshold: float = 25.0
    # L2 上下文扫描轮数（本次请求 messages 尾部；0=关）。
    bot_content_route_context_turns: int = 4
    # 会话状态硬上限与空闲归零（分钟）：防长跑会话钉死在 INTIMATE。
    bot_content_route_max_ttl_minutes: int = 120
    bot_content_route_idle_reset_minutes: int = 10
    # 上下文钳制全局缺省（2026-09-17 用户裁定：输入 128K / 输出 64K，日常对话
    # 足够）：输出=请求 max_tokens 封顶；输入=估算超限时从最旧非 system 丢起。
    bot_chat_max_input_tokens: int = 131072
    bot_chat_max_output_tokens: int = 65536
    # 群聊亲密面黑白名单（2026-09-17 用户裁定）：白名单命中且不在黑名单的群
    # 才允许亲密模式/露骨内容（群内手动开关仅管理员可拨）；黑名单优先；
    # 白名单为空=群聊亲密面整体关闭，绝不猜群（campus 白名单同款纪律）。
    bot_content_route_group_whitelist: list[str] = []
    bot_content_route_group_blacklist: list[str] = []
    # v21r5 四名单之私聊两面（2026-09-19 用户裁定）：黑名单最高优先（Master
    # Love 压不过黑名单）；白名单【空=私聊亲密面默认放开】（沿用既有私聊放开
    # 裁定）、非空=仅名单内 QQ——与群白名单「空=关闭」语义刻意不对称，登记处
    # 必须写明。console 为运营者本地面，不参与私聊名单门。
    bot_content_route_private_whitelist: list[str] = []
    bot_content_route_private_blacklist: list[str] = []
    # v21r5 双开关 TTL（两个开关同一时长）：亲密模式（手动钉死，群级/个人级
    # 同一 TTL）默认 60 分钟自动退出——按激活时刻起算、会话活跃不续期、重新
    # 开启即重置；既有 max_ttl（120）保留为全状态硬上限。
    bot_content_route_intimate_ttl_minutes: int = 60
    # v21r5 个人级开关总闸：群成员能否对自己拨「亲密模式 开」（开关一）。
    # False=群聊仅管理员全群开关（开关二）有效，成员指令不受理。
    bot_content_route_group_per_user_enabled: bool = True
    # 亲密档浅档（L1）自动腿总闸（2026-09-24 用户裁定 R1 A）：好感度达标的用户
    # 自动进浅档——只给关系语气，**绝不换模型**（换模型只由显式开/管理员钉/
    # 内容信号触发，判据唯一住 content_route._MODEL_SWITCH_SOURCES）。
    # 消费点=runtime/content_route.py 的 _knobs()（每次判定现读传入的 config）。
    bot_content_route_l1_auto_enabled: bool = True
    # 自动腿门槛：好感度**档号**（tier id）达到该档及以上才自动进浅档。档号真身
    # 住 character/affinity.py 的 ``_ATTITUDE_TIERS``（取数口 attitude_tiers()），
    # 本仓不在此抄一份档位表；缺省对应「亲近」那一档（id=+1），调高=更严、
    # 调到最低档号=对全体建档用户开放、负得离谱等于关（另有上一行的总闸）。
    # ⚠ 热改档位=需重启：这两枚不在根 __init__.py 的 _RUNTIME_HOT_OVERRIDE_FIELDS
    # 合并表里，`/bot runtime set` 写了也进不了判定用的 config ⇒ 已在
    # settings.RESTART_REQUIRED_KEYS 登记，改 .env 后重启生效（不做成"看着能热改"）。
    bot_content_route_l1_auto_min_tier: int = 1
    # Master Love（2026-09-17 用户裁定）：master 恋人语境——名单内用户的会话
    # 自动进入亲密档（无需手动拨「亲密模式」），并注入恋人语气指令；群聊同样
    # 受亲密面准入门约束（普通群不生效）。条目格式："qq"=全域 / "群号:qq"=仅该群
    # （AstrBot 风格「指定群聊里的指定用户」）。名单用户同时拥有群聊亲密开关权限。
    bot_master_love_enabled: bool = True
    bot_master_love_admins: list[str] = []
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
    # S0 直连收编配置门（v21r4-b2-direct-collect-plan §3.1/§3.3）：缺省 False=
    # 旧直连路径逐字节等价；True=走统一出站路径。
    # 凭证过期每日提醒总开关：job 侧 getattr 读本键而 Config 无 ⇒ 提醒永远注册、.env 关不掉。
    # 缺省 True = 与补键前逐字节同行为（旧 getattr 缺省就是 True）。
    bot_cookie_expiry_reminder_enabled: bool = True
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
    # POTCCV 渠道（gpt-56-luna / gpt-56-terra）的凭据槽。注册表里引用写作
    # `env:BOT_POTCCV_API_KEY`（注意词序与上面 `BOT_API_KEY_*` 一族相反）。
    # `_resolve_api_key`（model_router.py:503-513）用 `getattr(config, env_name.lower())`
    # 回退取值，且生产 os.environ 不含 BOT_*（NoneBot dotenv 只把「已声明字段」经
    # translate_env_keys→Config.model_validate 落进 Config，未声明的键被 pydantic
    # extra=ignore 静默丢弃）。故字段名**必须严格等于 `bot_potccv_api_key`**（=
    # `BOT_POTCCV_API_KEY`.lower()）——命名不能套 `bot_api_key_*` 前缀，否则取不到值。
    # unify-U6 曾建议改名 `bot_api_key_potccv`，按上述 getattr 契约取不到值、必再踩空，
    # 已否决。这是「registry 引用 env:X 但小同名字段缺失→恒判 config_missing」
    # （H3 家族，09-09「五连发全失败」同类事故）的第四次复发，本次坐实。
    bot_potccv_api_key: str = ""
    bot_chat_base_url: str = "https://api.openai.com/v1"
    bot_chat_temperature: float = 0.7
    bot_chat_reasoning_effort: str = ""
    bot_chat_max_tokens: int = 65538
    # 每跳超时（不是整条回复的预算）：链上每一跳共用这一个钳制值，换渠道不会更快。
    # 20s 一档是**必然失败**而非「响应慢」——思考型模型光首字就要 20 秒以上，2026-09-27 实弹
    # `route_attempts=axon-gemini-38-flash:timeout|axon-grok-46:timeout error_kind=timeout
    # duration_ms=69436.9` 两跳同死，全链败后弹失败话术。地板由 tests/test_chat_timeout_floor.py 执法；
    # 整条回复的天花板另有 bot_request_budget_seconds（缺省 300s）与 bot_chat_failover_max_seconds 管。
    bot_chat_timeout_seconds: float = 40.0
    # QQ/群聊快速响应模式：限制上下文、输出和联网前置工作，优先首字响应速度。
    bot_chat_fast_mode: bool = True
    bot_chat_fast_max_tokens: int = 65538
    bot_chat_fast_max_candidates: int = 0
    # 与上面同档：快速模式装配走 `min(normal, fast)`，只抬一枚等于没抬。
    bot_chat_fast_timeout_seconds: float = 40.0
    bot_chat_fast_context_budget: int = 9600
    bot_chat_fast_web_max_queries: int = 3
    # 故障转移总时限（秒）：候选模型连续失败时的整体预算，防止响应被拖到分钟级；0=不限。
    bot_chat_failover_max_seconds: float = 120.0
    # 严格注册表优先级（v21r2 R1，2026-09-17 用户裁定「永远按注册表优先级处理」）：
    # 同名模型渠道聚合排序以注册表 priority 为主键，价格/EWMA 只作同级 tiebreak；
    # false=旧行为（价格均值优先；latency_first 开时 EWMA 整体重排）。
    bot_chat_strict_priority: bool = True
    # 渠道失败冷却（秒，v21r2 R1）：真实调用失败的渠道在候选队列降级到队尾的
    # 时长（不剔除；全部冷却时原序放行）；与 channel_health 的 30 分钟重探互补。
    bot_chat_channel_cooldown_seconds: float = 90.0
    # 链预算止损（秒，v21r2 R1）：故障转移链上除首个真实尝试外，剩余预算低于
    # 该值时不再发起新跳（残秒尝试注定超时）；0=关闭止损。
    bot_chat_failover_min_hop_seconds: float = 3.0
    # ---- LLM 计费账本 + 网关归因（B5 M1 / B1，2026-09-25）----
    # 账本总开关。此前只以 `_ENABLED_CONFIG_KEY` 常量名住在 ledger.py 里、Config 上
    # 没有这枚字段 ⇒ `extra="ignore"` 会把 .env 里的 BOT_LLM_BILLING_ENABLED 静默丢掉，
    # 「写在 .env 却永远关不上/打不开」（读点幽灵登记项，本次销账）。
    # 缺省 False = 与历史行为逐字节一致（不建库、不写行）。
    bot_llm_billing_enabled: bool = False
    # 网关归因（B1）：bot 侧注册表只指向 AxonHub，看不见网关内部实际选了哪条上游
    # 渠道，也拿不到缓存创建 token 与四项分项价。开启后由**账本写线程**按响应体 id
    # （== requests.external_id，实测关联键）去网关库只读反查并回填。
    # 刻意放在写线程而非回复路径：那条查询要等网络，挂在回复前面就是拿延迟换报表。
    bot_axonhub_attribution_enabled: bool = False
    # 只读账号连接面。真实口令只在 .env（铁律 3），代码零硬编码；host/user 任一为空
    # ⇒ from_config 直接返回 None（fail-closed），不存在"看着开了其实没连"。
    # 必须用只读角色（本机已建 axonhub_ro，仅五张表 SELECT）：账本侧对网关库
    # 没有任何写需求，给写权限等于把故障半径扩到她的生产网关。
    bot_axonhub_db_host: str = ""
    bot_axonhub_db_port: int = 5432
    bot_axonhub_db_database: str = "axonhub"
    bot_axonhub_db_user: str = ""
    bot_axonhub_db_password: str = ""
    # 单批反查超时（秒）：到点就放弃这一批、标 unavailable，绝不拖慢落库。
    bot_axonhub_attribution_timeout_seconds: float = 3.0
    # 协议端（SnowLuma）安装目录：诊断卡要素⑤「协议端版本」读它自己的
    # package.json 的 version 字段（OneBot V11 的 get_version 本仓从未调用过，
    # 而卡片在渲染线程里同步组装，不能为一个版本号往主循环发异步 RPC）。
    # 缺省空＝走内置探测路径（见 error_report._protocol_client_version_label）；
    # 读不到就在卡上写「未取到」，绝不拿 nonebot-adapter-onebot 的版本顶替。
    bot_protocol_client_dir: str = ""
    # 慢回复先行回执（选项 C，2026-09-23 用户裁定）：真回复仍在跑，先补一句守岸人
    # 口吻的等待短句。缺省关；开启与否按会话走四名单（见下方两对键）。
    # 装配期读一次，热改当轮不生效——与调度器族同口径（台账 #3 P3），不做成"看起来能热改"。
    bot_chat_progress_ack_enabled: bool = False
    # 判定"慢"的阈值（秒）：能力在此时间内出结果就什么都不发，不发第二条、也不撤回。
    # 缺省 15.0 —— 2026-09-23 用户裁定「15 秒内出结果时不发」。
    bot_chat_progress_ack_delay_seconds: float = 15.0
    # 同一会话两次回执的最小间隔（秒），防刷屏；只在回执真发成功时占用额度。
    bot_chat_progress_ack_cooldown_seconds: float = 60.0
    # 群聊名单：白名单为空 = 群聊整面关闭（绝不猜群）；黑名单永远赢。
    bot_chat_progress_ack_group_whitelist: list[str] = []
    bot_chat_progress_ack_group_blacklist: list[str] = []
    # 私聊名单：白名单为空 = 私聊放开（刻意不对称，同 bot_content_route_*）。
    bot_chat_progress_ack_private_whitelist: list[str] = []
    bot_chat_progress_ack_private_blacklist: list[str] = []
    # 回执阈值随网关当下快慢浮动（2026-09-25 用户裁定：中转站一慢就必触发，误报太多）。
    # 开时按「链上各跳 EWMA 延迟 × 倍率」抬高质量阈值，并夹在 floor~cap 之间；
    # 关时逐字节回到上面那枚固定的 delay_seconds。
    bot_chat_progress_ack_adaptive_enabled: bool = True
    # 自适应的下限（秒）：网关很快时也不早于此值发回执。2026-09-26 由 15 抬到 30——
    # 15 秒实测「每一轮都发」（34 条里 19 条），地板低于本轮耗时常态时它就退化成
    # 每条先开口；缺省值唯一真身在 progress_ack.DEFAULT_ACK_DELAY_FLOOR_SECONDS，
    # 这枚字段由 tests/test_progress_ack_thresholds.py 的 AST parity 锁现算比对。
    bot_chat_progress_ack_delay_floor_seconds: float = 30.0
    # 自适应的上限（秒）：网关再慢也不能让用户无限期等不到一句提示。
    bot_chat_progress_ack_delay_cap_seconds: float = 90.0
    # 倍率：阈值 = 链上最慢一跳的 EWMA × 此倍率。取「最慢一跳」而不是「当值那一跳」，
    # 理由是回执压的是整轮（检索+联网+LLM），任何一条路慢都可能是本轮走的那条。
    # 现网实测（gemini ema 4.5s / grok ema 13.7s、grok 单跳最大 19.9s）下
    # 2.0 把阈值从 15s 抬到约 27s——仍在「真等久了」的量级，不再一抖就报。
    bot_chat_progress_ack_latency_multiplier: float = 2.0
    # 折句窗口（2026-09-25 用户裁定）：一句话按逗号拆成两三条发时合成一轮、只回一次。
    # 只有「本身像半句话」的消息才会等下一条，完整句子零额外延迟。
    bot_chat_message_coalescing_enabled: bool = True
    # 停口多久算这句话说完了（秒）——这是分句发送者唯一付出的额外延迟。
    bot_chat_message_coalescing_quiet_seconds: float = 1.8
    # 封顶等待（秒）：有人逐字蹦也必须在这时开口，绝不允许一直不回。
    bot_chat_message_coalescing_max_hold_seconds: float = 8.0
    bot_chat_message_coalescing_max_messages: int = 6
    bot_chat_message_coalescing_max_chars: int = 1500
    # 被限流挡下的「明确找我说话」的消息改为期后补回，不再静默吞掉
    # （2026-09-25 用户裁定第 2 项：冷却与条数帽把消息吃掉了）。
    bot_chat_rate_limit_redrive_enabled: bool = True
    # 最多延后多久补回（秒）；还要等更久的不补（避免隔半小时突然冒一句）。
    # 180 = 4×点名间隔缺省 45：连发 5 条 @bot 排队补回装得下整轮
    # （2026-09-25 用户裁定第 2 项「可以延后，不可以丢弃」；
    # `policy/redrive_ledger.py` 给同人多条被拦消息排开回位后，
    # 上一档 90 秒只容 2 个回位、第 3 条起仍被丢）。
    bot_chat_rate_limit_redrive_max_wait_seconds: float = 180.0
    # 一条消息最多补回几次，防重放循环。
    bot_chat_rate_limit_redrive_max_attempts: int = 1
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
    # ---- 文件写盘口（需求 16(2)，2026-09-26 S-FILES-LAND 收编波）----
    # 六枚缺省值**逐字节等于** restricted_runner 内建缺省（8MiB/60/120、白名单回落
    # bot_download_dir/export、总闸今日在岗）⇒ 现网零变更；「保守」体现在口本身：
    # 白名单空＝什么都不许写（fail-closed），可执行扩展名永远拦。
    # 读点唯一住 domains/files/capabilities/file_exchange.py 的装配函数；根 matcher
    # 交装配期快照 config、六枚未进运行时覆盖合并表 ⇒ 全进 RESTART_REQUIRED_KEYS，
    # 不做「看着能热改」（C-09 形态）。缺省常量与运行器同名常量的等值由
    # tests/test_files_write_side_assembly.py 现场对账（改其一必看到另一处红）。
    bot_files_write_enabled: bool = True
    bot_files_write_allowed_dirs: list[str] = []
    bot_files_write_max_bytes: int = 8 * 1024 * 1024
    bot_files_write_daily_create: int = 60
    bot_files_write_daily_replace: int = 120
    bot_files_read_confined_max_bytes: int = 8 * 1024 * 1024
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
    # 2026-09-24 裁定：群小时额度 60 上线（缺省 0→60）；**仅群聊生效**，
    # 私聊不设小时额度（"有问必回"教义不变，反向锁见
    # tests/test_rate_limit_pacing.py::test_group_hour_cap_never_reaches_private_chat）。
    bot_rate_limit_group_max_per_hour: int = 60
    bot_rate_limit_group_max_per_minute: int = 0
    # ---- 群聊节奏层（2026-09-24 T7，采纳 T6 令牌桶主干；根治"开局瞬间打光后
    # 整段静默"：旧滑动小时窗 2 分钟打光 30 句、随后静默 58 分钟，节奏层把最坏
    # 静默压到 3600/x 秒）。消费点 policy/rate_limit.py，经装配期 settings_provider
    # 每轮现读**本 Config 的值**；但 .env 只在进程启动时装载，且这五枚键未登记进
    # 热改合并层（根 __init__ 冻结、禁插行），改这些键 = 改 .env + 重启（需重启）。
    # 每小时补充令牌 x 句（0 = 整个节奏层不生效，含分钟帽与最小间隔）。
    bot_rate_limit_group_pacing_tokens_per_hour: int = 60
    # 桶容量 B = 开局可连发句数（"绝不瞬间打光"的红线；T6 建议值 5 起步）。
    bot_rate_limit_group_pacing_burst_capacity: int = 5
    # 节奏层分钟外骨架（她自己的口径"每分钟 3 句"）。0 = 不设。
    bot_rate_limit_group_pacing_max_per_minute: int = 3
    # 群非点名两句之间的最小间隔（秒）。0 = 不设。情绪/好感豁免只免这类间隔。
    bot_rate_limit_group_pacing_min_interval_seconds: int = 20
    # 图片/表情包/视频类**自己的**独立最小间隔（秒）：与文字并入同一个桶，
    # 另加这道更宽的间隔（120s，2026-09-24 裁定采纳）。0 = 不设。
    bot_rate_limit_group_vision_min_interval_seconds: int = 120
    # 用户情绪低落时的限流豁免：**2026-09-24 裁定收窄**——只免最小间隔
    # （节奏层间隔/图类间隔/target 间隔），**不免任何句数额度**（小时帽、
    # 分钟帽、令牌桶、session/sender/global 照常且照常记账）——否则一条
    # 难过消息能连开整点额度。覆盖面仍是群聊非点名流量，不扩大。
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
    # outbox/seen 保留期与重试（subscription_store_v2.py:104/109/114/119 四枚 getattr 读点，
    # 键此前均不存在）：读点是 `or` 链 ⇒ 0 恒回退模块常量，补键缺省 0 = 零行为变更、旋钮变真。
    bot_subscription_outbox_sent_retention_days: int = 0
    bot_subscription_seen_retention_days: int = 0
    bot_subscription_outbox_max_attempts: int = 0
    bot_subscription_outbox_sending_stale_seconds: float = 0
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

    # ---- bot.tts（G-2 契约层，M-35：枚举族装载期即拒，越界值不再出门）----

    @field_validator("bot_tts_preset")
    @classmethod
    def _validate_tts_preset(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if normalized not in TTS_PRESET_IDS:
            raise ValueError(f"bot_tts_preset must be one of {sorted(TTS_PRESET_IDS)}")
        return normalized

    @field_validator("bot_tts_text_lang")
    @classmethod
    def _validate_tts_text_lang(cls, value: str) -> str:
        # 引擎合法域 11 值（T53 §6）；bot 出门前一律 casefold——POST 入口引擎
        # 用原值断言，"ZH" 必 400，故装载期即归一。
        from plugins.bot_unified_runtime.domains.media.tts_presets import (
            TEXT_LANG_VALUES,
        )

        normalized = str(value or "").strip().casefold()
        if normalized not in TEXT_LANG_VALUES:
            raise ValueError(f"bot_tts_text_lang must be one of {sorted(TEXT_LANG_VALUES)}")
        return normalized

    @field_validator("bot_tts_text_split_method")
    @classmethod
    def _validate_tts_text_split_method(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if normalized not in {"cut0", "cut1", "cut2", "cut3", "cut4", "cut5"}:
            raise ValueError("bot_tts_text_split_method must be cut0..cut5")
        return normalized

    @field_validator("bot_tts_auto_reply_scope")
    @classmethod
    def _validate_tts_auto_reply_scope(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if normalized not in {"private", "group", "all"}:
            raise ValueError("bot_tts_auto_reply_scope must be private/group/all")
        return normalized

    @field_validator("bot_tts_api_url")
    @classmethod
    def _validate_tts_api_url(cls, value: str) -> str:
        # M-32 / T94：装载期 SSRF 闸（U-17=C 宪条：语音引擎必须本机）。
        # fail-closed 白名单：scheme 必须 http/https，host 必须可无歧义证明为
        # loopback（127.0.0.1 / ::1 / localhost）；生产缺省 127.0.0.1:9880 原样
        # 通过（零影响）。空值=未配置，回落缺省不触发闸。畸形端口/整型 IP/
        # 内网段/云元数据/任意域名一律装载期即拒——远程引擎需显式改闸
        # （见 .superpowers/sdd/2026-09-19-unify-audit/report-T94.md 披露）。
        from urllib.parse import urlsplit

        text = str(value or "").strip()
        if not text:
            return "http://127.0.0.1:9880"
        try:
            parts = urlsplit(text)
            _port_probe = parts.port  # 访问即校验：非法端口抛 ValueError（F-04 同款）
        except ValueError as exc:
            raise ValueError(f"bot_tts_api_url 无法解析（端口或 URL 形态非法）：{exc}") from exc
        scheme = (parts.scheme or "").casefold()
        if scheme not in {"http", "https"}:
            raise ValueError(
                f"bot_tts_api_url 只支持 http/https 协议（收到 {scheme or '空协议'}）"
            )
        host = (parts.hostname or "").strip()
        if not host or not _tts_api_url_host_is_loopback(host):
            raise ValueError(
                "bot_tts_api_url 必须指向本机（http(s)://127.0.0.1 或 ::1 或 "
                "localhost）——语音引擎必须本机部署，不接受远程/内网地址"
                f"（收到 host={host!r}）"
            )
        return text


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

        # 名册单一来源 = 模块级 PATH_REMAPPED_FIELDS（A-8 席位 2026-09-27 上提，
        # 供「生产配置值 ∈ 允许根」常驻断言按同一张名册逐字段过登记闸）。
        for name in PATH_REMAPPED_FIELDS:
            setattr(self, name, resolve(getattr(self, name)))

        for name in PATH_LIST_REMAPPED_FIELDS:
            setattr(self, name, [resolve(item) for item in getattr(self, name)])
        return self

    @field_validator(
        "bot_persona_files",
        "bot_knowledge_files",
        "bot_trend_files",
        "bot_glossary_files",
        "bot_runtime_persona_nicknames",
        "bot_persona_nicknames",
        # 参考音频项含 "|" 与可能的中文逗号，故走 file_list 解析（只按 ";" 与
        # JSON 数组切分），不能走 id_list（那边会 replace 逗号导致正文被切断）。
        "bot_tts_ref_audios",
        # 写盘白名单根＝路径值，目录名可能含逗号，同样只按 ";" / JSON 数组切；
        # 绝不走 id_list（那会把带逗号的目录名切开）。
        "bot_files_write_allowed_dirs",
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
        "bot_tts_trigger_words",
        "bot_campus_self_ids",
        "bot_campus_group_whitelist",
        "bot_emergency_info_sources",
        "bot_emergency_info_auto_approve_sources",
        "bot_emergency_info_push_group_whitelist",
        "bot_emergency_info_push_user_ids",
        "bot_emergency_info_reviewer_ids",
        "bot_content_route_group_whitelist",
        "bot_content_route_group_blacklist",
        "bot_content_route_private_whitelist",
        "bot_content_route_private_blacklist",
        "bot_chat_progress_ack_group_whitelist",
        "bot_chat_progress_ack_group_blacklist",
        "bot_chat_progress_ack_private_whitelist",
        "bot_chat_progress_ack_private_blacklist",
        "bot_master_love_admins",
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
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # 裸标量宽容装载（与下方 _coerce_scalar_id_to_str 同一口径）：dotenv/JSON
            # 装载会把不带引号的 3865067623 解成 int（2026-09-21 生产 .env 的
            # bot_emergency_info_* 三枚键即此形态），strict 校验在此抛 TypeError 会让
            # 整份 Config 装载失败、Bot 重启起不来。单元素 id 语义无歧义；
            # bool 显式排除（防 True→"True"），其余类型原样交末尾报错口径。
            return [str(value)]
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
