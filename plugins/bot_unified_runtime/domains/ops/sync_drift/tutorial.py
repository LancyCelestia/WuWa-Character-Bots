"""漂移修法教程的**现场生成**（IALERT 席，2026-09-20 用户规格「教程要细致入微」）。

设计硬约束（用户裁定的架构第 3 条）：教程正文**不落一份手写副本**——手写副本
本身会变成新的漏同步点。因此本模块只做两件事：

1. 从**同一真相源**现取数：
   - 命令/触发词面 → ``scripts/command_catalog.merged_entries()`` / ``render()``
     （``_HELP_ENTRIES`` 的 AST 静态提取 + manifest 合并，与 ``docs/command-catalog.md``
     生成时用的是同一个函数，故教程里出现的 topic/别名必然与注册表同源）；
   - 机器事实面 → ``scripts/doc_sync.build_document()``（``docs/auto-facts.md`` 的生成函数）；
   - 配置面 → ``Config.model_fields``（``config.py`` 字段即权威，含默认值）。
   **只 import，不改这两个脚本**（本席文件白名单之外）。
2. 把 ``registry.DriftCheck`` 的 ``truth_source`` / ``copies`` / ``recompute_command`` /
   ``verification_gate`` **插值进编号步骤**，所以「教程里的复算命令」与「登记表」天然是
   同一个字符串，可被测试断言一致（见
   ``tests/test_sync_drift_activation.py::test_tutorial_body_reuses_registry_command_verbatim``）。

任何取数失败都只降级为「教程取数失败，请手工核验」一行（fail-open），绝不抛出。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

GENERIC_STEP = "先跑复算命令拿到本机实况，再按下面步骤逐项对齐；改完必须跑门禁项收尾。"


def _load_merged_entries() -> list[dict[str, object]]:
    """取 ``_HELP_ENTRIES`` 合并视图（与 command-catalog 生成同一入口）。"""
    from scripts.command_catalog import (
        merged_entries,
    )

    return list(merged_entries())


def _entry_field(entry: dict[str, object], key: str) -> list[str]:
    value = entry.get(key)
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _trigger_words_of(entry: dict[str, object]) -> list[str]:
    """一个 topic 的全部触发面：注册表字段 ``aliases``（与 command-catalog 同源）。"""
    words: list[str] = []
    for key in ("aliases",):
        words.extend(_entry_field(entry, key))
    return list(dict.fromkeys(words))


def _config_default(config: Any, name: str) -> Any:
    """配置默认值优先取运行期实例，取不到再回落 ``Config.model_fields``。

    返回 ``Any`` 是有意的：这里取的是任意字段（bool/int/list/str 都可能），调用方各自
    按面判型（如 ``steps_tts_numbers`` 把字节数送进 ``int()``，失败即降级为提示文案）。
    """
    value = getattr(config, name, None) if config is not None else None
    if value not in (None, "", [], {}):
        return value
    try:
        from plugins.bot_unified_runtime.config import Config

        field = Config.model_fields.get(name)
        return getattr(field, "default", None)
    except Exception:  # noqa: BLE001 - 教程取数失败只降级，不影响告警主链。
        return None


# ---------------------------------------------------------------------------
# 各面教程生成器：入参 (root, evidence)，出参 = 编号步骤文案元组
# ---------------------------------------------------------------------------


def steps_persona(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """人格源 → Runtime 生产副本（SYNC1 缺口8）。"""
    source_dir = root / "personas" / "shorekeeper"
    return (
        (f"确认源侧改动是有意为之：{source_dir} 下被改的文件见本条告警「漂移证据」段"
        "（mtime 比较口径：源文件时间戳晚于生产副本即报，跨机器拷贝/批量 checkout "
        "会造成假阳性，假阳性时用下一条的命令重刷副本时间戳即可消警）。"),
        ("把源文手工对齐进生产副本——本项目人格**不是**逐字节拷贝（源与副本各自演化，"
        "见 scripts/sync_persona_source.py 头注），所以必须由人决定保留哪些措辞；"
        "对照命令："
        f"`python -c \"from pathlib import Path;"
        f"print((Path(r'{source_dir}') / 'identity.md').read_text(encoding='utf-8')[:400])\"`"),
        ("改文案时守守岸人语气（去 AI 味，参照 .agents/skills/shuorenhua），"
        "红线内容一律以 domains/chat_reply/character/affinity.py 的态度文本为准，"
        "不得在副本里放宽（铁律 8）。"),
        ("副本落盘后重锚哈希："
        "`python scripts/sync_persona_source.py --adopt`，再复跑 "
        "`python scripts/sync_persona_source.py --check` 应为 OK。"),
        "人格改动**必须重启 bot 才生效**（铁律 1），重启前生产读到的仍是旧副本。",
        ("门禁项：跑本条告警的复算命令应输出「已同步」；"
        "另跑 `powershell -NoProfile -ExecutionPolicy Bypass -Command "
        "& '.\\scripts\\dev.ps1' -Task test` 中 persona 源-副本一致性门应绿。"),
    )


def steps_env_example(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """.env.example ↔ config.py 字段差集（SYNC1 缺口3）。"""
    sample = _sample_env_line(config, evidence)
    return (
        ("看清单：本条告警「漂移证据」段列出的键，是在 config.py 有字段、"
        f"但 .env.example 未声明的差集（真相源={root / 'plugins' / 'bot_unified_runtime' / 'config.py'}）。"),
        ("逐键决定归类：**该给样例** 的补进 .env.example；**刻意不给样例** 的"
        "（内部键/试验键）在 docs/config-catalog-full.md 的说明列写明理由，"
        "并在巡检里接受该面长期常亮，或按 §遗留 讨论豁免机制。"),
        ("补录格式照仓内惯例：一行注释（这键干什么、缺省含义）+ 一行 `BOT_XXX=`"
        "（**只写键名、值留空或写 env:变量名 引用**，真实密钥绝不入 .env.example，铁律 3）。"
        f"可直接抄的样板：{sample}"),
        ("同步登记 docs/config-catalog-full.md（A26 增量区），否则常驻门会红："
        "`python -m pytest tests/test_doc_sync_gates.py -q -p no:cacheprovider` 四列全绿为准。"),
        ("机器事实册若因键数变化而红，按仓内规矩重录："
        "`python scripts/doc_sync.py --write`（本告警只 --check 不改生成物，"
        "故 auto-facts 的 --write 留给改动者/合流席执行）。"),
        "门禁项：复跑本条复算命令应输出「已同步」。",
    )


def _sample_env_line(config: Any, evidence: Sequence[str]) -> str:
    """给一条**可抄**的样例行（键名 + 代码默认，零手写文案）。"""
    name = ""
    for line in evidence:
        stripped = line.strip()
        if stripped:
            name = stripped.split()[0]
            break
    if not name:
        return "`BOT_新键名=`（值留空，或写 `env:变量名` 引用 .env 里的真实值）"
    default = _config_default(config, name)
    rendered = "" if default in (None, "") else str(default)
    return f"`{name.upper()}={rendered}`（默认值即 config.py 里的 {name}={rendered or '空'}）"


def steps_commands_md(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """COMMANDS.md 逐条正文 ↔ _HELP_ENTRIES（SYNC1 缺口1）。"""
    missing = [line.split()[0] for line in evidence if line.strip()]
    try:
        entries = {str(item.get("topic", "")): item for item in _load_merged_entries()}
    except Exception:  # noqa: BLE001 - 取数失败降级为通用步骤，绝不抛给告警链。
        return (GENERIC_STEP,)
    blocks: list[str] = [
        "COMMANDS.md 是人读命令手册，真相源是 echo.py 的 `_HELP_ENTRIES`"
        "（运行期 /bot help 与 docs/command-catalog.md 都读同一份）。"
        f"下面 {len(missing)} 个 topic 在手册里查不到："
        + "、".join(missing[:20]),
        "取权威口径（现取现用，别照抄任何文档）："
        "`python -c \"from scripts.command_catalog import merged_entries;"
        "print([(e['topic'], e.get('aliases'))) for e in merged_entries() if e['topic'] in "
        "{" + ", ".join(repr(m) for m in missing[:20]) + "}]\"`",
    ]
    for topic in missing[:6]:
        entry = entries.get(topic) or {}
        aliases = _trigger_words_of(entry)
        blocks.append(
            f"补 `{topic}` 一节：标题行写 topic；"
            f"触发词按注册表逐条列全={('、'.join(aliases) if aliases else '（注册表无别名，仅主命令）')}；"
            "再把用法/参数/示例照 `docs/command-catalog.md` 同 topic 段抄齐"
            "（该文档是 A 档生成物，与注册表恒等，可当权威底稿）。"
        )
    blocks.append(
        "手册正文与 /bot help 同口径后，跑门禁项；"
        "若新增/改动了注册表本身，先 `python scripts/command_catalog.py --write` 重生生成物。"
    )
    return tuple(blocks)


def steps_db_owners(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """docs/db-owners.md ↔ config 实际落盘库清单（SYNC1 缺口11）。"""
    missing = [line.split()[0] for line in evidence if line.strip()]
    return (
        "docs/db-owners.md 是本仓 SQLite 库清单的**唯一清单**（AGENTS.md 第二部分），"
        f"下面 {len(missing)} 个库在 config.py 有路径字段、但清单里没有："
        + "、".join(missing[:20]),
        "确认库真身与 owner："
        "`python -c \"from plugins.bot_unified_runtime.config import Config;"
        "print([ (n, Config.model_fields[n].default) for n in "
        + repr(missing[:20])
        + "])\"` —— 第二列就是它落在 `BOT_RUNTIME_DATA_DIR` 下的真实相对路径。",
        ("补登记行：库文件名 / 建表处（模块:行）/ owner 域 / 内容与可删性 / 清理策略。"
        "**运行数据不可删**（铁律 2），拿不准就在清理策略列写「不清理」。"),
        ("若该库由 runtime_paths 重映射，确认它已在 config.py 的 `path_fields` 里"
        "（源码树零 data/ 铁律 6，先例 tests/test_datafix_runtime_paths.py）。"),
        ("门禁项：复跑本条复算命令应输出「已同步」；"
        "`powershell -NoProfile -ExecutionPolicy Bypass -Command \"& '.\\scripts\\dev.ps1' -Task runtime-layout\"` 应绿。"),
    )


def steps_triggers_vs_route_matrix(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """触发词集合 ↔ docs/route-matrix.md 触发词列（SYNC1 缺口7）。"""
    rows = [line for line in evidence if line.strip()]
    return (
        (f"route-matrix 的触发词列与注册表触发面差 {len(rows)} 处（逐条见「漂移证据」段）。"
        "真相源=echo.py `_HELP_ENTRIES` 的 aliases/triggers_*；现门 "
        "`tests/test_doc_sync_gates.py::test_route_matrix_rows_match_base_router` "
        "只比 kind/priority/cap，**不比触发词集合**，所以这一面漂了不会红。"),
        ("取权威集合："
        "`python -c \"from scripts.command_catalog import merged_entries;"
        "print({e['topic']: (e.get('aliases'), e.get('triggers_prefix'), e.get('triggers_contains')) "
        "for e in merged_entries()})\"`"),
        ("二选一并对齐：**该词确实该路由** → 补进 route-matrix 对应行的触发词列，"
        "并确认根 __init__.py 的 matcher 已注册（漏注册=命令上线即坠 /bot help，"
        "历史上「语音 help-路由缺口」就是这么补的）；**该词不该路由** → 从注册表摘掉，"
        "再 `python scripts/command_catalog.py --write`。"),
        ("注意历史裁定（台账 #27）：zb/bz/sz/sm 一类真冲突缩写是**有意永不启用**，"
        "巡检报出来说明有人把它们加回了触发面，要先判是不是误加。"),
        ("门禁项：`python -m pytest tests/test_doc_sync_gates.py tests/test_documentation_consistency.py "
        "-q -p no:cacheprovider` 应绿；再复跑本条复算命令应输出「已同步」。"),
    )


def steps_tts_numbers(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """TTS 规格数值 ↔ 代码常量（SYNC1 缺口9/10a/10b）。"""
    audio_bytes = _config_default(config, "bot_tts_max_audio_bytes")
    max_chars = _config_default(config, "bot_tts_max_chars")
    try:
        audio_mib = f"{int(audio_bytes) / 1024 / 1024:g} MiB"
    except (TypeError, ValueError):
        audio_mib = "（默认值取数失败，请以 config.py 现值为准）"
    return (
        ("数值权威只有一个：`plugins/bot_unified_runtime/config.py` 的 "
        f"`bot_tts_max_audio_bytes`（现值 {audio_bytes} 字节 = {audio_mib}）与 "
        f"`bot_tts_max_chars`（现值 {max_chars}）；兜底常量在 "
        "`domains/media/tts_presets.py` 的 MAX_AUDIO_BYTES_FALLBACK / HARD_MAX_CHARS_FALLBACK"
        "（两者相等由 test_tts_presets.py 的门锁死）。"),
        ("差集见「漂移证据」段。改的**只能是副本**，不许为了让文档变绿去改权威值，"
        "除非这是用户裁定过的规格变更（历史先例：G2-R3 裁 8 MiB 后忘了回写文档）。"),
        ("文档侧：`docs/design/tts-contract-layer.md` 是自述的「规格件」，"
        "本仓规矩是规格件先成文后实现，但**数值以代码为准**——请在文件头注补一行"
        "「快照非活镜像，数值权威=config.py/tts_presets.py」，并把正文数值改成现值。"),
        ("帮助文案侧：echo.py「语音」条目的 detail 是手写字符串（`_HELP_ENTRY_META` 的 "
        "config_vars 只登记键名、不核对数值串），改数时要一并把 detail 里的 "
        f"{max_chars} 字 / {audio_mib} 写对；"
        "改完 `python scripts/command_catalog.py --write` 重生 command-catalog.md。"),
        ("引擎参数域侧：`domains/media/tts_presets.py` 的 ENGINE_PARAM_DOMAINS 与 config.py "
        "各字段的 `Field(ge/le)` 边界目前无一致门（G-4 §10④ 停在建议），改任一侧要手校另一侧。"),
        ("门禁项：`python -m pytest tests/test_tts_presets.py -q -p no:cacheprovider` 应绿，"
        "随后复跑本条复算命令应输出「已同步」。"),
    )


def steps_generic(root: Path, evidence: Sequence[str], config: Any) -> tuple[str, ...]:
    """未登记教程生成器的面（新面接入前的兜底）。"""
    return (GENERIC_STEP, *(f"证据：{line}" for line in list(evidence)[:10]))


TUTORIAL_BUILDERS: dict[str, Callable[[Path, Sequence[str], Any], tuple[str, ...]]] = {
    "persona_source_vs_runtime_copy": steps_persona,
    "env_example_vs_config_fields": steps_env_example,
    "commands_md_vs_help_entries": steps_commands_md,
    "db_owners_vs_config_dbs": steps_db_owners,
    "trigger_words_vs_route_matrix": steps_triggers_vs_route_matrix,
    "tts_spec_numbers_vs_code": steps_tts_numbers,
}


def build_fix_steps(
    surface: str,
    root: Path,
    evidence: Sequence[str],
    config: Any = None,
) -> tuple[str, ...]:
    """按面名取教程生成器；未知面或生成异常一律兜底，绝不抛出。"""
    builder = TUTORIAL_BUILDERS.get(surface, steps_generic)
    try:
        steps = tuple(builder(root, evidence, config))
    except Exception:  # noqa: BLE001 - 教程是告警的附属品，坏了不能拖垮投递。
        steps = (GENERIC_STEP,)
    return steps or (GENERIC_STEP,)
