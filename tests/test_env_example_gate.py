"""`.env.example` ↔ `config.py` 字段双向差集常驻门（ISYNC 任务 B，2026-09-21）.

背景（两条独立印证）：
- SA1 席实测 `.env.example` 缺 110/633 字段，且**全仓无任何比对门**
  （`docs/config-catalog-full.md` 有覆盖门 `test_doc_sync_gates.test_config_catalog_covers_config_fields`，
  但那份文档与 `.env.example` 是两条独立链路，后者一直是手改孤岛）；
- SYNC1 席记为 C 档「改一处静默漏同步」；`.env.example` 头部第 2 行还写着
  "every active Config field is explicit" —— 宣称与实况相反。

本门做**双向**差集，全部走 AST/文本静态解析（不 import 插件包、不读 .env、零网络）：

方向一（字段 → 文档）：`config.py` 的 `Config` 字段全集，必须在 `.env.example`
  有同名激活键行（``KEY=``，**注释形态不算**，理由见 `_documented_keys` 文档串）。
  存量缺口 114 项走 ``UNDOCUMENTED_FIELD_LEDGER`` 挂账，门只拦**新增**缺失。
方向二（文档 → 字段）：`.env.example` 的激活键必须能对上 `Config` 字段；
  适配器/第三方组件自读的 12 个非 ``BOT_`` 环境变量走 ``EXTERNAL_ENV_KEYS`` 显式豁免
  （每条带理由），且**禁止 ``BOT_*`` 借道该表**（防止幻影 BOT_ 键被当成"外部键"藏起来）。

棘轮纪律（三条，防「白名单变成垃圾桶」）：
1. 台账长度 ``<= LEDGER_BASELINE``（只减不增）；
2. 已补录进 `.env.example` 的键**必须同时从台账摘除**，否则红；
3. 豁免表条目若在 `.env.example` 里已不存在，或理由为空，红。

变异/负样本自检见文件末尾 `test_gate_*_has_teeth_*`：内嵌伪字段/伪键必须被抓红，
防「集合恒空/恒全」的空转门（项目失效形态册第 2、3 条）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "plugins" / "bot_unified_runtime" / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"

# ---------------------------------------------------------------------------
# 方向一：存量缺口挂账台账（2026-09-21 ISYNC 实跑清点所得，共 114 项）
# ---------------------------------------------------------------------------
#
# 这些 config.py 字段**从未**在 .env.example 出现（既无激活键、也不在外部键表）。
# 本席只加门、不为凑绿乱改 `.env.example` 的值，故按仓内既有「增量有门、存量挂账」
# 口径（见 test_doc_sync_gates.py 的 KNOWN_MISSING 先例，三期清零）整批登记。
# 补录任一项后**必须把它从本台账摘掉**（否则 test_documented_keys_must_leave_ledger 红）。
LEDGER_BASELINE = 114

UNDOCUMENTED_FIELD_LEDGER: frozenset[str] = frozenset(
    {
        "bot_affinity_db_path", "bot_affinity_enabled", "bot_api_key_aiprc_gemini",
        "bot_api_key_aiprc_grok", "bot_api_key_axonhub", "bot_api_key_qianqianye_night",
        "bot_api_key_starapi", "bot_api_key_toolcode_gemini", "bot_api_key_toolcode_gpt",
        "bot_api_key_toolcode_grok", "bot_api_key_umi_claude", "bot_api_key_umi_group3",
        "bot_campus_db_path", "bot_campus_enabled", "bot_campus_group_whitelist",
        "bot_campus_notify_qq", "bot_campus_push_bot_id", "bot_campus_self_ids",
        "bot_channel_adaptive_timeout", "bot_channel_probe_jitter_seconds", "bot_channel_probe_manual_threads",
        "bot_channel_probe_threads", "bot_channel_slow_ema_ms", "bot_chat_hedge_delay_seconds",
        "bot_chat_hedge_max_candidates", "bot_control_plane_actions_db", "bot_control_plane_platform_db",
        "bot_cookie_expiry_reminder_via_queue", "bot_cookie_qr_via_queue", "bot_daily_assist_enabled",
        "bot_decision_engine_mode", "bot_dirty_guard_delete", "bot_dirty_guard_enabled",
        "bot_divination_enabled", "bot_eat_enabled", "bot_file_export_via_queue",
        "bot_group_digest_blacklist", "bot_group_digest_list_mode", "bot_group_digest_push_enabled",
        "bot_group_digest_push_time", "bot_group_digest_whitelist", "bot_group_welcome_enabled",
        "bot_group_welcome_via_queue", "bot_master_love_admins", "bot_master_love_enabled",
        "bot_media_archive_db_path", "bot_media_archive_dir", "bot_media_archive_max_file_mb",
        "bot_media_archive_per_message_limit", "bot_media_archive_summary_enabled", "bot_media_archive_video_frames",
        "bot_moegirl_max_candidates", "bot_moegirl_summary_max_chars", "bot_mood_baseline_arousal",
        "bot_mood_db_path", "bot_mood_enabled", "bot_mood_half_life_minutes",
        "bot_mood_rate_cap_per_hour", "bot_music_analytics_db_path", "bot_music_analytics_enabled",
        "bot_music_analytics_retention_days", "bot_music_default_mode", "bot_music_dir",
        "bot_news_cache_seconds", "bot_news_enabled", "bot_news_max_items",
        "bot_news_timeout_seconds", "bot_notes_db_path", "bot_parrot_cooldown_seconds",
        "bot_parrot_threshold", "bot_parrot_window_seconds", "bot_pipeline_max_workers",
        "bot_poke_admin_bypass", "bot_poke_enabled", "bot_poke_group_cooldown_seconds",
        "bot_poke_group_text", "bot_poke_private_cooldown_seconds", "bot_poke_private_text",
        "bot_poke_probability", "bot_poke_reply_enabled", "bot_proactive_affinity_gate_enabled",
        "bot_quirks_db_path", "bot_quirks_enabled", "bot_quirks_max_active",
        "bot_randpic_dirs", "bot_randpic_enabled", "bot_randpic_max_file_mb",
        "bot_randpic_trigger_words", "bot_rate_limit_emotion_exempt", "bot_rate_limit_group_max_per_hour",
        "bot_rate_limit_group_max_per_minute", "bot_reflection_db_path", "bot_reflection_enabled",
        "bot_reflection_hour", "bot_reflection_llm_enabled", "bot_reflection_max_sessions",
        "bot_reflection_minute", "bot_reflection_quirks_min_confidence", "bot_reflection_quirks_propose_enabled",
        "bot_reminder_db_path", "bot_reminder_enabled", "bot_reminder_llm_extract_enabled",
        "bot_render_forward_min_nodes", "bot_saucenao_api_key", "bot_send_bot_unavailable_max_age_seconds",
        "bot_subscribe_global_concurrency", "bot_subscribe_jitter_ratio", "bot_subscribe_lease_seconds",
        "bot_subscribe_min_interval_seconds", "bot_subscribe_outbox_interval_seconds", "bot_subscribe_platform_concurrency",
        "bot_subscribe_retry_base_seconds", "bot_subscribe_retry_cap_seconds", "bot_vision_reply_probability",
    }
)

# ---------------------------------------------------------------------------
# 方向二：非 Config 字段的外部环境变量显式豁免表（键 → 理由）
# ---------------------------------------------------------------------------
#
# 这些键由 NoneBot 适配器/第三方组件自行读取，不经 translate_env_keys 进 Config，
# 因此**结构上不可能**有对应 config.py 字段。只允许非 BOT_ 前缀（见
# test_external_allowlist_must_not_harbour_bot_keys）。
EXTERNAL_ENV_KEYS: dict[str, str] = {
    "TELEGRAM_BOTS": "nonebot-adapter-telegram 自行读取（Bot(token=...) 直取环境），非 Config 字段",
    "TELEGRAM_PROXY": "nonebot-adapter-telegram 代理设置，适配器直读",
    "TELEGRAM_WEBHOOK_URL": "nonebot-adapter-telegram webhook 模式回呼地址，适配器直读",
    "MAIL_BOTS": "nonebot-adapter-mail 自行读取的 SMTP 账号列表，非 Config 字段",
    "MCP_SERVERS": "MCP 客户端组件直读的服务端清单，不经 Config",
    "MCP_CACHE_TTL": "MCP 客户端工具缓存 TTL，组件直读",
    "MCP_TOOL_TIMEOUT": "MCP 单次工具调用超时，组件直读",
    "SQLALCHEMY_DATABASE_URL": "SQLAlchemy/第三方库约定连接串，组件直读",
    "LOCALSTORE_USE_CWD": "nonebot2 内置 localstore 插件的官方环境变量",
    "LOCALSTORE_CACHE_DIR": "nonebot2 localstore 缓存目录",
    "LOCALSTORE_CONFIG_DIR": "nonebot2 localstore 配置目录",
    "LOCALSTORE_DATA_DIR": "nonebot2 localstore 数据目录",
}
EXTERNAL_ENV_KEYS_BASELINE = 12

# ---------------------------------------------------------------------------
# 同一键在 .env.example 里出现多次（后写覆盖前写=实际生效值是**最后一个**）
# ---------------------------------------------------------------------------
#
# ISYNC 只加门不改值：这两行的**取舍**属配置裁定（5 还是 6），留给主会话/用户裁决，
# 裁决后删掉多余一行并从本表摘除。本表只保证「重复不会继续静默增加」。
DUPLICATE_KEY_LEDGER: dict[str, str] = {
    "BOT_MUSIC_CANDIDATES_LIMIT": "现网 :400=5 与 :744=6 两行并存，dotenv 后写覆盖前写（实际生效 6）；"
    "取值裁定待主会话/用户决定后二选一",
}

# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

_ACTIVE_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=", re.M)


def _config_field_names() -> set[str]:
    """config.py 各 ClassDef 内的注解字段全集（小写），与 translate_env_keys 同口径。"""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id.lower())
    return names


def _documented_keys() -> set[str]:
    """`.env.example` 里**真正生效**的键行（列 0 的 ``KEY=``，去掉行尾 ``\\r``）。

    刻意不认注释形态（``# KEY=``）：实测该形态会被 `# tags = …`、`# white1=…`、
    `# search_depth=…` 这类散文注释命中，等于给「写行注释就算已同步」开门——
    正是项目失效形态册第 2 条「文本匹配冒充结构断言」的成因。注释仍保留其
    说明价值，只是不作为本门的同步证据。
    """
    return {m.group(1).lower() for m in _ACTIVE_KEY_RE.finditer(_env_text())}


def _env_text() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def _raw_active_keys() -> list[str]:
    return [m.group(1) for m in _ACTIVE_KEY_RE.finditer(_env_text())]


# ---------------------------------------------------------------------------
# 方向一：config.py 字段 → .env.example 必须声明
# ---------------------------------------------------------------------------


def test_env_example_declares_all_config_fields() -> None:
    fields = _config_field_names()
    assert len(fields) >= 600, f"config.py 字段提取异常（仅 {len(fields)} 个）——先修解析器再谈门"
    documented = _documented_keys()
    assert len(documented) >= 400, f".env.example 键解析异常（仅 {len(documented)} 个）"

    missing = sorted(fields - documented - UNDOCUMENTED_FIELD_LEDGER)
    assert not missing, (
        "config.py 新增字段未在 .env.example 声明，且不在存量挂账台账内"
        "（新字段必须补一行 ``BOT_XXX=`` 示例键；确需豁免须经评审进台账，"
        "台账只减不增、当前上限 "
        f"{LEDGER_BASELINE}）：\n- " + "\n- ".join(missing)
    )


def test_ledger_ratchet_only_shrinks() -> None:
    assert len(UNDOCUMENTED_FIELD_LEDGER) <= LEDGER_BASELINE, (
        f"存量缺口台账从 {LEDGER_BASELINE} 涨到 {len(UNDOCUMENTED_FIELD_LEDGER)}——"
        "棘轮只减不增：新字段请补进 .env.example，不要往台账里塞"
    )


def test_ledger_entries_are_still_undocumented() -> None:
    """台账不得成为过期坟场：条目要么仍真缺，要么已消失，要么已补录（须摘除）。"""
    fields = _config_field_names()
    documented = _documented_keys()
    gone = sorted(UNDOCUMENTED_FIELD_LEDGER - fields)
    assert not gone, (
        "台账里有 config.py 已不存在的字段（该字段被删/改名，请摘除条目）：\n- "
        + "\n- ".join(gone)
    )
    documented_but_listed = sorted(UNDOCUMENTED_FIELD_LEDGER & documented)
    assert not documented_but_listed, (
        "这些键已补录进 .env.example，必须同时从 UNDOCUMENTED_FIELD_LEDGER 摘除"
        "（否则台账会虚报规模、掩盖真实缺口）：\n- " + "\n- ".join(documented_but_listed)
    )


# ---------------------------------------------------------------------------
# 方向二：.env.example 声明 → 必须有落点
# ---------------------------------------------------------------------------


def test_env_example_has_no_phantom_keys() -> None:
    fields = _config_field_names()
    documented = _documented_keys()
    phantom = sorted(documented - fields - {k.lower() for k in EXTERNAL_ENV_KEYS})
    assert not phantom, (
        ".env.example 声明了 config.py 里没有的键，也没登记为外部组件键"
        "（幻影键=写了不生效、读的人以为生效；改名/删字段后必须同步）：\n- "
        + "\n- ".join(phantom)
    )


def test_external_allowlist_has_no_bot_keys_and_stays_bounded() -> None:
    bot_borrowers = sorted(k for k in EXTERNAL_ENV_KEYS if k.upper().startswith("BOT_"))
    assert not bot_borrowers, (
        "BOT_ 前缀键必须由 config.py 字段解释，禁止借道外部豁免表藏成幻影键："
        f"{bot_borrowers}"
    )
    assert len(EXTERNAL_ENV_KEYS) <= EXTERNAL_ENV_KEYS_BASELINE, (
        f"外部键豁免表从 {EXTERNAL_ENV_KEYS_BASELINE} 涨到 {len(EXTERNAL_ENV_KEYS)}——"
        "新增条目须经评审并写明理由"
    )
    documented = _documented_keys()
    for key, reason in EXTERNAL_ENV_KEYS.items():
        assert reason.strip(), f"豁免键 {key} 缺理由"
        assert key.lower() in documented, (
            f"豁免键 {key} 已不在 .env.example 里，请从 EXTERNAL_ENV_KEYS 摘除"
        )


def test_duplicate_keys_are_accounted_for() -> None:
    """同键多行=后写覆盖前写，属「改一处另一处静默不一致」，必须挂账不得新增。"""
    counts: dict[str, int] = {}
    for key in _raw_active_keys():
        counts[key] = counts.get(key, 0) + 1
    dupes = {k for k, n in counts.items() if n > 1}
    unaccounted = sorted(dupes - set(DUPLICATE_KEY_LEDGER))
    assert not unaccounted, (
        ".env.example 出现未挂账的重复键行（保留哪一行的值？请去重后复跑）："
        f"{unaccounted}"
    )
    for key, reason in DUPLICATE_KEY_LEDGER.items():
        assert reason.strip(), f"重复键 {key} 的挂账缺理由"
        assert key in dupes, f"重复键 {key} 已去重，请从 DUPLICATE_KEY_LEDGER 摘除"


def test_env_example_key_syntax_is_conventional() -> None:
    bad = [k for k in _raw_active_keys() if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k)]
    assert not bad, f".env.example 存在不符合全大写约定的键名（translate_env_keys 依赖它）：{bad}"
    lower_fields = [f for f in _config_field_names() if not f.startswith("bot_")]
    assert not lower_fields, (
        f"config.py 出现非 bot_ 前缀字段，BOT_→bot_ 一一映射前提被破坏，本门口径需重审：{lower_fields}"
    )


# ---------------------------------------------------------------------------
# 负样本自检：防恒绿空转门
# ---------------------------------------------------------------------------


def test_missing_direction_gate_has_teeth() -> None:
    """伪字段注入后必须被「缺文档」计算抓红（解析器空转/集合恒空时先红在这里）。"""
    fake = "bot_isync_negative_probe_not_a_real_field"
    fields = _config_field_names()
    documented = _documented_keys()
    assert fake not in fields and fake not in documented and fake not in UNDOCUMENTED_FIELD_LEDGER
    assert sorted(({fake} | fields) - documented - UNDOCUMENTED_FIELD_LEDGER) == [fake]


def test_phantom_direction_gate_has_teeth() -> None:
    fake = "BOT_ISYNC_NEGATIVE_PROBE_PHANTOM_KEY"
    fields = _config_field_names()
    documented = _documented_keys()
    externals = {k.lower() for k in EXTERNAL_ENV_KEYS}
    assert fake.lower() not in fields and fake.lower() not in documented
    assert sorted(({fake.lower()} | documented) - fields - externals) == [fake.lower()]


def test_ledger_is_not_self_satisfying() -> None:
    """台账不能靠「键名对不上」蒙绿：每条都必须真对应一个在场字段、且真缺声明。"""
    fields = _config_field_names()
    documented = _documented_keys()
    assert UNDOCUMENTED_FIELD_LEDGER <= fields, (
        f"台账含非 config.py 字段（写法漂移）：{sorted(UNDOCUMENTED_FIELD_LEDGER - fields)}"
    )
    assert not (UNDOCUMENTED_FIELD_LEDGER & documented), "台账与 .env.example 声明集重叠，见上条提示"
    assert len(UNDOCUMENTED_FIELD_LEDGER) == LEDGER_BASELINE, (
        f"存量缺口实际 {len(UNDOCUMENTED_FIELD_LEDGER)} 项，"
        "台账规模已变化（补齐后请同步下调 LEDGER_BASELINE，只减不增）"
    )
