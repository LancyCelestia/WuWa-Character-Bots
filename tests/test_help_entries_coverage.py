"""帮助页补全回归：identity/quirk 管理命令条目、新配置键可发现性（Task 4）、
以及语音「自动配音」正文口径 vs 真身门链的三把跟随锁（S171，见文件末段）。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _HELP_CATEGORIES,
    _PUBLIC_HELP_TOPICS,
    HELP_ENTRIES,
    build_help_result,
    normalize_help_topic,
)

ADMIN_KEYS_QUIET_HOURS = (
    "BOT_QUIET_HOURS_ENABLED",
    "BOT_QUIET_HOURS_START",
    "BOT_QUIET_HOURS_END",
    "BOT_QUIET_HOURS_TIMEZONE",
    "BOT_QUIET_HOURS_SESSION_TYPES",
    "BOT_QUIET_HOURS_BYPASS_ROLES",
)
ADMIN_KEYS_GROUP_LIMITS = (
    "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR",
    "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE",
    "BOT_RATE_LIMIT_EMOTION_EXEMPT",
)
ADMIN_KEYS_FORWARD = (
    "BOT_RENDER_FORWARD_MIN_NODES",
    "BOT_RENDER_FORWARD_MIN_CHARS",
    "BOT_RENDER_FORWARD_MAX_NODES",
    "BOT_RENDER_FORWARD_NODE_CHARS",
)
ADMIN_KEYS_SWITCHES = (
    "BOT_SEND_QUEUE_ENABLED",
    "BOT_SEND_QUEUE_WORKER_ENABLED",
    "BOT_AUDIT_ENABLED",
    "BOT_RECEIPTS_ENABLED",
    "BOT_DIAGNOSTICS_ENABLED",
)
ADMIN_KEYS_VISION_VIDEO = (
    "BOT_VISION_ENABLED",
    "BOT_VISION_MODE",
    "BOT_VIDEO_UNDERSTANDING_ENABLED",
)
ADMIN_KEYS_DIGEST = (
    "BOT_GROUP_DIGEST_LIST_MODE",
    "BOT_GROUP_DIGEST_WHITELIST",
    "BOT_GROUP_DIGEST_BLACKLIST",
)
# 审查 C-09（死开关治理）+ 2026-09-15 热改面全量审计：以下键的消费点在装配期
# 冻结（写入成功但行为不变），已移出 SETTABLE_KEYS；帮助仍要写明键名，但口径
# 是「.env+重启」，runtime set 会明确拒绝——不得宣称可热改。
ADMIN_KEYS_ENV_ONLY_RESTART = (
    "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED",
    "BOT_SHARED_GROUP_CONTEXT_ENABLED",
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
    "BOT_GROUP_DIGEST_LIST_MODE",
    "BOT_GROUP_DIGEST_WHITELIST",
    "BOT_GROUP_DIGEST_BLACKLIST",
    "BOT_RENDER_FORWARD_MIN_NODES",
    "BOT_RENDER_FORWARD_MIN_CHARS",
    "BOT_RENDER_FORWARD_MAX_NODES",
    "BOT_RENDER_FORWARD_NODE_CHARS",
)


def _entry(topic: str):
    matches = [entry for entry in HELP_ENTRIES if entry["topic"] == topic]
    assert len(matches) == 1, f"topic {topic} 出现 {len(matches)} 次"
    return matches[0]


def test_identity_and_quirk_entries_exist_and_are_admin_only() -> None:
    for topic, alias in (("身份", "identity"), ("怪癖", "quirk")):
        entry = _entry(topic)
        assert entry["admin_only"] is True
        assert topic not in _PUBLIC_HELP_TOPICS
        assert normalize_help_topic(alias) == topic
        blob = str(entry)
        assert "仅管理员" in blob or "管理员" in blob
    assert "/bot identity set" in str(_entry("身份"))
    assert "/bot identity tag" in str(_entry("身份"))
    assert "/bot identity clear" in str(_entry("身份"))
    assert "/bot quirk approve" in str(_entry("怪癖"))
    assert "/bot quirk retire" in str(_entry("怪癖"))
    assert "pending_review" in str(_entry("怪癖")) or "待审" in str(_entry("怪癖"))


def test_identity_and_quirk_depth_page_and_public_gate() -> None:
    admin_page = build_help_result(request_id="t4-admin", query="identity", is_admin=True)
    assert admin_page.kind == "text"
    assert "/bot identity set <昵称>" in admin_page.body
    assert "防 OOC" in admin_page.body or "人格不变" in admin_page.body

    public_page = build_help_result(request_id="t4-public", query="identity", is_admin=False)
    assert "没有找到" in public_page.body


def test_new_config_keys_documented_and_settable() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        SETTABLE_KEYS,
    )

    blob = str(HELP_ENTRIES)
    hot_keys = (
        ADMIN_KEYS_QUIET_HOURS
        + ADMIN_KEYS_GROUP_LIMITS
        + ADMIN_KEYS_VISION_VIDEO
    )
    # 帮助必须写键名（可发现性），但只有真热改键才允许宣称可 set；
    # FORWARD/DIGEST 族经 2026-09-15 审计证实为装配期快照死开关，归入重启键。
    for key in hot_keys + ADMIN_KEYS_FORWARD + ADMIN_KEYS_DIGEST:
        assert key in blob, f"{key} 未写进帮助"
    for key in hot_keys:
        assert key in SETTABLE_KEYS, f"{key} 应可经 /bot runtime set 修改"
    for key in ADMIN_KEYS_FORWARD + ADMIN_KEYS_DIGEST:
        assert key not in SETTABLE_KEYS, (
            f"{key} 实为装配期冻结键（2026-09-15 审计），不应宣称可热改"
        )
    for key in ADMIN_KEYS_SWITCHES:
        assert key in blob, f"{key} 未写进帮助"
        assert key not in SETTABLE_KEYS, f"{key} 实为 .env 键，不应宣称可热改"
    for key in ADMIN_KEYS_ENV_ONLY_RESTART:
        assert key in blob, f"{key} 未写进帮助"
        assert key not in SETTABLE_KEYS, (
            f"{key} 实为 .env+重启键（审查 C-09 装配期冻结），不应宣称可热改"
        )
    # 真实校验边界入文，防止"0=关闭"语义回退。
    assert "0=该帽不生效" in blob
    assert "whitelist|blacklist|off|all" in blob
    assert "relay|direct" in blob


def test_market_news_divination_entries_present() -> None:
    for topic in ("行情", "快报", "占卜"):
        _entry(topic)


def test_new_topics_categorized_as_admin() -> None:
    categories = {name: set(topics) for name, topics in _HELP_CATEGORIES}
    for topic in ("身份", "怪癖", "限流", "合并转发", "群摘要", "视频理解", "运行开关"):
        assert topic in categories["管理员专属"], f"{topic} 未归入管理员专属分类"
    topics = [entry["topic"] for entry in HELP_ENTRIES]
    assert len(topics) == len(set(topics)), "帮助主题出现重复"


def test_alias_map_stays_collision_free() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _HELP_ALIAS_MAP,
        _HELP_ENTRY_META,
    )

    seen: dict[str, str] = {}
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            lowered = alias.lower()
            assert lowered not in seen, f"别名 {alias} 在 {seen[lowered]} 与 {entry['topic']} 间冲突"
            seen[lowered] = entry["topic"]
    # T5 结构修复（fix-trae2）：映射口径=aliases ∪ META 触发词（aliases 优先）。
    for entry in HELP_ENTRIES:
        meta = _HELP_ENTRY_META.get(entry["topic"], {})
        for field in ("triggers_nickname", "triggers_nl"):
            for word in meta.get(field) or ():
                seen.setdefault(str(word).strip().lower(), entry["topic"])
    assert set(_HELP_ALIAS_MAP) == set(seen)


def test_q1_dead_symbols_removed() -> None:
    """Q1 死代码清扫防复现：_help_index_line / route_bot_command 及其专属常量已删。"""
    import plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo as echo_mod

    for gone in ("_help_index_line", "route_bot_command", "_HELP_INDEX_COMMAND_TOPICS"):
        assert not hasattr(echo_mod, gone), f"已删除的死代码符号 {gone} 不得回归"


# ---------------------------------------------------------------------------
# G-5 增量（report-T86 §G-5.2，T89 席追加）：TTS「语音」帮助覆盖门。
# 对 echo.py（capabilities/echo.py 为 v21r2 垫片，真身=domains/chat_reply）
# 只读判定，禁碰生产文件。
# 交接注记：config_vars 覆盖断言原为 xfail(strict) 暂挂件（T84 在飞）；
# T84 于 2026-09-19 波内落地 G 波新键（echo.py config_vars 增
# BOT_TTS_PRESET/BOT_TTS_VOICE_HOOK_ENABLED），XPASS(strict) 如设计报红，
# 同日按摘除条件移除标记转常驻门。
# ---------------------------------------------------------------------------

VOICE_TOPIC = "语音"
# G 波新键（T84 语音条目 config_vars 预期覆盖面；T84 收口口径若不同，
# 以收口稿为准同步本常量）。
VOICE_NEW_CONFIG_VARS = ("BOT_TTS_PRESET", "BOT_TTS_VOICE_HOOK_ENABLED")


def test_voice_topic_registered_in_help_entries() -> None:
    """「语音」topic 必须恰在 _HELP_ENTRIES 且 tts 别名可解析（现状已绿）。"""
    entry = _entry(VOICE_TOPIC)
    assert "tts" in entry["aliases"]
    assert normalize_help_topic("tts") == VOICE_TOPIC
    assert "BOT_TTS_ENABLED" in str(entry), "开关键 BOT_TTS_ENABLED 未写进语音帮助"


def test_voice_entry_config_vars_cover_new_keys() -> None:
    """语音条目 config_vars 必须覆盖 G 波新键（BOT_TTS_PRESET/VOICE_HOOK）。"""
    entry = _entry(VOICE_TOPIC)
    covered = set(entry.get("config_vars") or ())
    not_covered = sorted(set(VOICE_NEW_CONFIG_VARS) - covered)
    assert not not_covered, f"语音帮助 config_vars 未覆盖 G 波新键：{not_covered}"


# ---------------------------------------------------------------------------
# S171（2026-09-24）· 自动配音「正文口径 = 真身门链」三把跟随锁
#
# 起因（SEAT-S163 §②）：语音条目的「对话自动配音」正文只点名
# BOT_TTS_AUTO_REPLY_ENABLED，而真身门链读的其余闸（含 BOT_TTS_VOICE_HOOK_ENABLED）
# 只活在 config_vars 机器面里 ⇒ 只读正文的人会以为「开了那一条就有配音」。
# 本组锁的键表**由 AST 从真身现算**，测试里不手抄键清单——手抄表等于把文案钉死在
# 夹具上：改代码不红、改文案才红，正是要避开的那种假安全感。
#
# 现算依据（写在源码里，非本席裁定）：
#   · 「该不该配」= tts.should_voice_reply（总闸 bot_tts_enabled ∧ 自动闸
#     bot_tts_auto_reply_enabled ∧ 未带音频 ∧ bot.chat ∧ 范围 auto_reply_scope_allows
#     ∧ 群面名单安全门 ∧ 概率/always）
#   · 「走哪条腿」= 根 __init__.py 装配门（键开→pipeline post-review enricher）
#     与 :5103 的互斥回退（键关→旧 _attach_voice_reply 包装）：两态**都会**配音，
#     差别只在「过审后正文才合成 + 失败挂运营故障」vs「失败静默放弃增益」
#     ⇒ bot_tts_voice_hook_enabled 是**选路键**，不是配音主闸。
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: 自动配音真身门：(相对仓根文件, 该文件里构成门链的函数名)
_AUTODUB_GATE_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "plugins/bot_unified_runtime/domains/media/capabilities/tts.py",
        ("should_voice_reply", "auto_reply_scope_allows"),
    ),
    ("plugins/bot_unified_runtime/domains/media/voice_enricher.py", ("enrich",)),
)

#: 给人读的正文面。**故意不含 aliases/config_vars**——SEAT-S163 那个洞的全部
#: 内容就是「config_vars 里有键、正文里没有键」，把机器面算进正文等于自缚。
_VOICE_BODY_FIELDS = ("index", "lines", "detail")

#: 「对话自动配音」那一句必须一起点名的串联两闸（总闸 + 自动配音闸）。
_AUTODUB_SERIAL_GATES = ("BOT_TTS_ENABLED", "BOT_TTS_AUTO_REPLY_ENABLED")

#: 选路键的真身名 + 「被误写成主闸/唯一开关」的句式（第三把锁的反面对象）。
_AUTODUB_PATH_SELECTOR_KEY = "BOT_TTS_VOICE_HOOK_ENABLED"
_SELECTOR_AS_MASTER_GATE_PATTERN = re.compile(r"主闸|须同时开|必须同时开|配音前提|只有开")


def _config_keys_read_by(*, file_rel: str, func_names: tuple[str, ...]) -> set[str]:
    """AST 取出指定函数体内对 ``config`` 的按键读取（``getattr(config,"x")`` / ``config.x``）。"""
    tree = ast.parse((_REPO_ROOT / file_rel).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in func_names:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "getattr"
                and len(inner.args) >= 2
                and isinstance(inner.args[0], ast.Name)
                and inner.args[0].id == "config"
                and isinstance(inner.args[1], ast.Constant)
                and isinstance(inner.args[1].value, str)
            ):
                found.add(str(inner.args[1].value))
            elif (
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "config"
            ):
                found.add(inner.attr)
    return {name for name in found if name.startswith("bot_tts_")}


def _voice_body_text() -> str:
    """语音条目的纯正文文本（index + lines + detail）。"""
    entry = _entry(VOICE_TOPIC)
    parts: list[str] = []
    for field in _VOICE_BODY_FIELDS:
        value = entry.get(field)
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return "\n".join(parts)


def _autodub_gate_keys() -> set[str]:
    keys: set[str] = set()
    for file_rel, func_names in _AUTODUB_GATE_SOURCES:
        keys |= _config_keys_read_by(file_rel=file_rel, func_names=func_names)
    assert keys, "自动配音门链真身一个 bot_tts_* 键都没读到——本组锁将空跑"
    return keys


def test_voice_autodub_gate_keys_are_named_in_help_body() -> None:
    """门链真身读的每一个 bot_tts_* 闸，语音正文（不含 config_vars）都必须点名。"""
    body = _voice_body_text()
    missing = sorted(key.upper() for key in _autodub_gate_keys() if key.upper() not in body)
    assert not missing, f"自动配音门链有闸未写进语音正文：{missing}"


def test_voice_autodub_gate_sentence_is_two_serial_gates() -> None:
    """「对话自动配音」那一句必须写成串联口径：总闸与自动配音闸同点名。"""
    anchor_lines = [
        line for line in _voice_body_text().splitlines() if "对话自动配音" in line
    ]
    assert anchor_lines, "语音正文里找不到「对话自动配音」那一句"
    joined = "".join(anchor_lines)
    missing = [key for key in _AUTODUB_SERIAL_GATES if key not in joined]
    assert not missing, f"自动配音那一句漏点名串联闸：{missing}"


def test_voice_hook_documented_as_path_selector_not_master_gate() -> None:
    """选路键必须在正文里，且不得被写成配音主闸（否则修一个失真又造一个新的）。"""
    body = _voice_body_text()
    assert _AUTODUB_PATH_SELECTOR_KEY in body, "语音正文未点名配音选路键"
    sentences = [
        sentence
        for sentence in re.split(r"[。\n]", body)
        if _AUTODUB_PATH_SELECTOR_KEY in sentence
    ]
    assert sentences, "选路键未落进任何一句正文"
    for sentence in sentences:
        matched = _SELECTOR_AS_MASTER_GATE_PATTERN.search(sentence)
        assert matched is None, (
            f"正文把 {_AUTODUB_PATH_SELECTOR_KEY} 说成了配音前提（命中「{matched.group(0)}」）："
            f"{sentence.strip()}"
        )
    assert "旧包装" in body, (
        "正文未说明键关态仍有旧包装路径在配音 ⇒ 选路语义缺失，读侧会当成总开关"
    )
