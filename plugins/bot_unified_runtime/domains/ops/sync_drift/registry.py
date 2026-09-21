"""一致性漂移**登记表**（IALERT 席，中央件）。

一句话：这里登记「哪些真相源 ↔ 哪些下游副本」需要运行期巡检，每条自带
① 比对方法（``detector``）② 复算命令（``recompute_command``）
③ 修法教程的生成器入口（``fix_steps_builder``，见同目录 ``tutorial.py``）。

三条硬规矩（用户裁定的架构第 3/4 条落地）：
1. **只读**：任何 detector 都不写盘、不改文件、不发网络；巡检一轮的成本是若干次
   本地文件读 + 一次注册表 AST 提取。
2. **诚实三态**：detector 返回证据行列表；空表=同步；行首为 ``UNVERIFIABLE_PREFIX``
   =这一面**本机无法核验**（缺文件/取数异常），按日志处理、**不算漂移也不谎报绿**。
3. **零教程副本**：修法步骤一律现场生成，登记表里不存任何手写教程正文。

首批接入 SYNC-1 审计席证实的 C 档缺口（.superpowers/sdd/2026-09-20-spec-audit/
audit-SYNC1-log.md 缺口 1/3/7/8/11/10a-b）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tutorial import build_fix_steps

UNVERIFIABLE_PREFIX = "无法核验："
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_RECOMPUTE_BASE = "PYTHONDONTWRITEBYTECODE=1 python -c \"from plugins.bot_unified_runtime." \
    "domains.ops.sync_drift import scan_surface; print(scan_surface({name!r}))\""

Evidence = Sequence[str]
Detector = Callable[[Path, Any], list[str]]


@dataclass(frozen=True)
class DriftCheck:
    """一条巡检登记项：真相源 ↔ 下游副本 ↔ 修法教程生成器入口。"""

    surface: str
    title: str
    truth_source: str
    copies: tuple[str, ...]
    severity: str
    consequence: str
    detector: Detector
    recompute_command: str = ""
    verification_gate: str = "复跑本条复算命令应输出「已同步」"
    fix_steps_builder: Callable[[str, Path, Evidence, Any], tuple[str, ...]] = build_fix_steps
    extra: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.recompute_command:
            object.__setattr__(
                self, "recompute_command", _RECOMPUTE_BASE.format(name=self.surface)
            )

    def fix_steps(self, root: Path, evidence: Evidence, config: Any = None) -> tuple[str, ...]:
        return self.fix_steps_builder(self.surface, root, evidence, config)

    def is_verifiable(self, evidence: Evidence) -> bool:
        return not any(str(line).startswith(UNVERIFIABLE_PREFIX) for line in evidence)


@dataclass(frozen=True)
class DriftFinding:
    """一面巡检的结论三态：同步 / 漂移（带证据）/ 本机无法核验。"""

    STATUS_SYNC = "sync"
    STATUS_DRIFT = "drift"
    STATUS_UNKNOWN = "unknown"

    check: DriftCheck
    status: str
    evidence: tuple[str, ...] = ()


def _unverifiable(reason: str) -> list[str]:
    return [f"{UNVERIFIABLE_PREFIX}{reason}"]


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _config_field_names() -> set[str]:
    from plugins.bot_unified_runtime.config import Config

    return {str(name) for name in Config.model_fields}


def _config_default(config: Any, name: str, default: Any = None) -> Any:
    value = getattr(config, name, None) if config is not None else None
    if value in (None, ""):
        return default
    return value


def _relative_display(raw_path: str) -> str:
    """把配置里的绝对路径显示成相对仓根形态。

    只做路径整形、**不读 .env**（副本路径来自已装载的 config 实例）；出站前还要
    过 ``redact_local_secrets`` 打码盘符（铁律 3），所以这里不需要自行脱敏。
    """
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text:
        return ""
    try:
        return os.path.relpath(text).replace("\\", "/")
    except (ValueError, OSError):  # pragma: no cover - 跨盘符 relpath 在 Windows 会抛
        return text


# ---------------------------------------------------------------------------
# 面 1：人格源 → Runtime 生产副本（SYNC1 缺口8，最危险：源对了生产照样错且无人知晓）
# ---------------------------------------------------------------------------

_PERSONA_SOURCE_DIR = "personas/shorekeeper"
_PERSONA_MTIME_TOLERANCE_SECONDS = 2.0


def detect_persona_source_vs_runtime_copy(root: Path, config: Any) -> list[str]:
    """源侧最新 mtime 晚于生产副本 mtime ⇒ 「源已改、副本未跟着改」。

    只读 mtime，不写锚、不改 scripts/sync_persona_source.py（ISYNC 在飞）。
    已知假阳性口径已写进教程第 1 步（批量 checkout/跨机拷贝会刷时间戳）。
    """
    source_dir = root / _PERSONA_SOURCE_DIR
    if not source_dir.is_dir():
        return _unverifiable(f"人格源目录不存在（{_PERSONA_SOURCE_DIR}）")
    persona_files = [str(item).strip() for item in (_config_default(config, "bot_persona_files", []) or [])]
    if not persona_files:
        return _unverifiable("config.bot_persona_files 为空，取不到生产副本路径")
    copy_path = Path(persona_files[0])
    if not copy_path.is_absolute():
        copy_path = root / copy_path
    if not copy_path.is_file():
        return _unverifiable(
            f"生产人格副本不存在（{_relative_display(str(copy_path))}，bot 可能未部署该副本）"
        )
    try:
        copy_mtime = copy_path.stat().st_mtime
    except OSError:
        return _unverifiable("生产人格副本可读性异常")
    stale: list[str] = []
    for candidate in sorted(source_dir.rglob("*")):
        if not candidate.is_file() or candidate.suffix not in {".md", ".txt"}:
            continue
        try:
            source_mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if source_mtime > copy_mtime + _PERSONA_MTIME_TOLERANCE_SECONDS:
            try:
                shown = candidate.relative_to(root).as_posix()
            except ValueError:
                shown = candidate.name
            stale.append(f"{shown}（晚 {int(source_mtime - copy_mtime)}s）")
    if stale:
        stale.append(f"生产副本={_relative_display(str(copy_path))}")
    return stale


# ----------------------------------------------------------------------------
# 面 2：.env.example ↔ config.py 字段差集（SYNC1 缺口3）
# ---------------------------------------------------------------------------

_ENV_KEY_RE = re.compile(r"^\s*(BOT_[A-Z][A-Z0-9_]*)\s*=")


def detect_env_example_vs_config_fields(root: Path, config: Any) -> list[str]:
    text = _read(root, ".env.example")
    if text is None:
        return _unverifiable(".env.example 读不到")
    declared: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _ENV_KEY_RE.match(line)
        if match:
            declared.add(match.group(1).lower())
    missing = sorted(name for name in _config_field_names() if name not in declared)
    return [f"{name}（config.py 有字段、.env.example 未声明）" for name in missing]


# ---------------------------------------------------------------------------
# 面 3：COMMANDS.md 逐条正文 ↔ _HELP_ENTRIES（SYNC1 缺口1）
# ---------------------------------------------------------------------------


def detect_commands_md_vs_help_entries(root: Path, config: Any) -> list[str]:
    text = _read(root, "COMMANDS.md")
    if text is None:
        return _unverifiable("COMMANDS.md 读不到")
    try:
        from scripts.command_catalog import (
            merged_entries,
        )

        topics = [str(entry.get("topic", "")).strip() for entry in merged_entries()]
    except Exception:  # noqa: BLE001 - 注册表取数失败=无法核验，不谎报
        return _unverifiable("_HELP_ENTRIES 取数失败（scripts/command_catalog 不可用）")
    known = set(re.findall(r"`([^`]+)`", text)) | set(re.findall(r"^#+\s*(.+?)\s*$", text, re.MULTILINE))
    known |= {line.strip() for line in text.splitlines()}
    missing = [topic for topic in dict.fromkeys(topics) if topic and topic not in known]
    return [f"{topic}（注册表有 topic、COMMANDS.md 正文查不到）" for topic in missing]


# ---------------------------------------------------------------------------
# 面 4：docs/db-owners.md ↔ config 实际 SQLite 库清单（SYNC1 缺口11）
# ---------------------------------------------------------------------------

_PATH_FIELDS_RE = re.compile(r"path_fields\s*=\s*\(([^)]*)\)", re.DOTALL)
_FIELD_NAME_RE = re.compile(r"\"([a-z0-9_]+)\"")


def _config_sqlite_fields(root: Path) -> list[str] | None:
    """从 config.py 源码里取 ``path_fields`` 元组，留下默认值是 *.sqlite3 的字段。

    ``path_fields`` 是 model_validator 内的局部变量、运行期不可读，故用与
    scripts/doc_sync.py 同思路的静态提取（本席不改那两个脚本，只自读源码）。
    """
    source = _read(root, "plugins/bot_unified_runtime/config.py")
    if source is None:
        return None
    match = _PATH_FIELDS_RE.search(source)
    if match is None:
        return None
    names = _FIELD_NAME_RE.findall(match.group(1))
    try:
        fields = _config_field_names()
    except Exception:  # noqa: BLE001 - Config 装载失败=无法核验
        return None
    return [name for name in dict.fromkeys(names) if name in fields]


def detect_db_owners_vs_config_dbs(root: Path, config: Any) -> list[str]:
    doc = _read(root, "docs/db-owners.md")
    if doc is None:
        return _unverifiable("docs/db-owners.md 读不到")
    names = _config_sqlite_fields(root)
    if names is None:
        return _unverifiable("config.py path_fields 静态提取失败")
    from plugins.bot_unified_runtime.config import Config

    listed = set(re.findall(r"([a-z0-9_]+\.sqlite3)", doc))
    missing: list[str] = []
    for name in names:
        default = getattr(config, name, None) or getattr(Config.model_fields.get(name), "default", None)
        text = str(default or "").strip().replace("\\", "/")
        if not text.endswith(".sqlite3"):
            continue
        basename = text.rsplit("/", 1)[-1]
        if basename not in listed:
            missing.append(f"{name} → {basename}（config.py 有库路径、db-owners.md 未登记）")
    return missing


# ---------------------------------------------------------------------------
# 面 5：触发词集合 ↔ docs/route-matrix.md 触发词列（SYNC1 缺口7）
# ---------------------------------------------------------------------------


def detect_trigger_words_vs_route_matrix(root: Path, config: Any) -> list[str]:
    """注册表触发面 ↔ route-matrix 触发词列（SYNC1 缺口7：这一面漂了不红）。

    口径收窄为**行内比对**：只判「route-matrix 里已经有这个 topic 的行、但行内
    查不到该触发面」。topic 整行缺失属结构落点问题，由既有门
    ``test_help_topics_have_route_layer_landing`` 负责，不在本面重复报（否则一轮
    就能刷出数百条噪声，告警反而没人看）。
    """
    doc = _read(root, "docs/route-matrix.md")
    if doc is None:
        return _unverifiable("docs/route-matrix.md 读不到")
    try:
        from scripts.command_catalog import (
            merged_entries,
        )

        entries = list(merged_entries())
    except Exception:  # noqa: BLE001 - 注册表取数失败=无法核验
        return _unverifiable("_HELP_ENTRIES 取数失败（scripts/command_catalog 不可用）")
    rows = {
        str(entry.get("topic", "")).strip(): line
        for entry in entries
        for line in doc.splitlines()
        if line.startswith("|") and str(entry.get("topic", "")).strip() in line
    }
    doc_words = set(re.findall(r"`([^`]+)`", doc))
    missing: list[str] = []
    for entry in entries:
        topic = str(entry.get("topic", "")).strip()
        row = rows.get(topic)
        if not topic or row is None:
            continue
        row_words = set(re.findall(r"`([^`]+)`", row)) | {row}
        for word in _entry_trigger_words(entry):
            if len(word) < 2 or word in doc_words or word in row_words or any(word in cell for cell in row_words):
                continue
            missing.append(f"{word}（topic={topic}，注册表有该触发面、route-matrix 该行触发词列查不到）")
    return list(dict.fromkeys(missing))


def _entry_trigger_words(entry: dict[str, Any]) -> list[str]:
    """注册表侧的触发面 = ``_HELP_ENTRIES`` 的 ``aliases``（与 command-catalog 同源）。"""
    words: list[str] = []
    value = entry.get("aliases")
    if isinstance(value, (list, tuple)):
        words.extend(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, str) and value.strip():
        words.append(value.strip())
    return list(dict.fromkeys(words))


# ---------------------------------------------------------------------------
# 面 6：TTS 规格数值 ↔ 代码常量（SYNC1 缺口9/10a/10b，实证已漂移）
# ---------------------------------------------------------------------------

_MIB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MiB")


def detect_tts_spec_numbers_vs_code(root: Path, config: Any) -> list[str]:
    """权威 = config.py 的 bot_tts_max_audio_bytes / bot_tts_max_chars。

    副本 = docs/design/tts-contract-layer.md 正文里的 MiB 数值（文档自称「规格件」，
    但数值漂移无门：G2-R3 裁 8 MiB 后文档仍写 4 MiB 就是本面要抓的活样本）。
    """
    doc = _read(root, "docs/design/tts-contract-layer.md")
    if doc is None:
        return _unverifiable("docs/design/tts-contract-layer.md 读不到")
    authority_bytes = _config_default(config, "bot_tts_max_audio_bytes", None)
    if authority_bytes is None:
        return _unverifiable("bot_tts_max_audio_bytes 取不到（Config 未装载）")
    try:
        authority_mib = int(authority_bytes) / 1024 / 1024
    except (TypeError, ValueError):
        return _unverifiable("bot_tts_max_audio_bytes 非整数值")
    drift: list[str] = []
    for line_no, line in enumerate(doc.splitlines(), start=1):
        if "音频" not in line and "audio" not in line.lower() and "上限" not in line:
            continue
        for text in set(_MIB_RE.findall(line)):
            if abs(float(text) - authority_mib) > 1e-9:
                drift.append(
                    f"docs/design/tts-contract-layer.md:{line_no} 写 {text} MiB，"
                    f"代码权威 {authority_mib:g} MiB（bot_tts_max_audio_bytes={authority_bytes}）"
                )
    return list(dict.fromkeys(drift))


# ---------------------------------------------------------------------------
# 登记集
# ---------------------------------------------------------------------------

DRIFT_CHECKS: tuple[DriftCheck, ...] = (
    DriftCheck(
        surface="persona_source_vs_runtime_copy",
        title="人格源改过、生产 Runtime 副本没跟着改",
        truth_source="personas/shorekeeper/（源）",
        copies=("config.bot_persona_files[0] 指向的生产人格副本（ChatBot_Runtime/data/persona/…）",),
        severity=SEVERITY_CRITICAL,
        consequence="生产继续用旧人格说话；人格是项目灵魂（铁律 8），这是唯一「源对了、生产照样错、且无人知晓」的一面。",
        detector=detect_persona_source_vs_runtime_copy,
        verification_gate="python scripts/sync_persona_source.py --check 为 OK，且本面复算输出「已同步」",
    ),
    DriftCheck(
        surface="env_example_vs_config_fields",
        title=".env.example 缺 config.py 已有字段的键",
        truth_source="plugins/bot_unified_runtime/config.py（字段全集）",
        copies=(".env.example", "docs/config-catalog-full.md（同批需登记）"),
        severity=SEVERITY_WARNING,
        consequence="新用户/新机器照 .env.example 复制 .env，缺的键静默按代码默认，与样例意图不一致；部署正确性风险。",
        detector=detect_env_example_vs_config_fields,
        verification_gate="python -m pytest tests/test_doc_sync_gates.py -q -p no:cacheprovider 全绿，且本面复算输出「已同步」",
    ),
    DriftCheck(
        surface="commands_md_vs_help_entries",
        title="人读命令手册 COMMANDS.md 落后于帮助注册表",
        truth_source="plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py 的 _HELP_ENTRIES",
        copies=("COMMANDS.md",),
        severity=SEVERITY_WARNING,
        consequence="手册静默过期：注册表加了 topic/别名，COMMANDS.md 不更新也不会红（现门只管硬编码总数），人照着手册敲命令会坠 /bot help。",
        detector=detect_commands_md_vs_help_entries,
        verification_gate="python -m pytest tests/test_documentation_consistency.py -q -p no:cacheprovider 全绿，且本面复算输出「已同步」",
    ),
    DriftCheck(
        surface="db_owners_vs_config_dbs",
        title="SQLite 库清单 docs/db-owners.md 落后于 config 实际库路径",
        truth_source="plugins/bot_unified_runtime/config.py 的 path_fields + 各字段默认值",
        copies=("docs/db-owners.md",),
        severity=SEVERITY_WARNING,
        consequence="db-owners 是全仓唯一的库清单（AGENTS 第二部分），漂移后清理/迁移/备份会漏库；运行数据不可删（铁律 2），漏登记的库既没人备份也没人清理。",
        detector=detect_db_owners_vs_config_dbs,
        verification_gate="python -m pytest tests/test_datafix_runtime_paths.py -q -p no:cacheprovider 全绿，且本面复算输出「已同步」",
    ),
    DriftCheck(
        surface="trigger_words_vs_route_matrix",
        title="注册表触发面在路由矩阵里查不到（可能压根没接线）",
        truth_source="plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py 的 _HELP_ENTRIES（aliases/triggers_*）",
        copies=("docs/route-matrix.md 触发词列", "根 __init__.py 的生产 matcher 注册（人工确认项）"),
        severity=SEVERITY_WARNING,
        consequence="现门只比 kind/priority/cap，不比触发词集合：改了触发词而 matcher 漏注册，命令上线即静默不响应，只能靠人肉或 e2e 撞见。",
        detector=detect_trigger_words_vs_route_matrix,
        verification_gate="python -m pytest tests/test_doc_sync_gates.py tests/test_documentation_consistency.py -q -p no:cacheprovider 全绿，且本面复算输出「已同步」",
    ),
    DriftCheck(
        surface="tts_spec_numbers_vs_code",
        title="TTS 规格文档数值与代码常量不一致",
        truth_source="plugins/bot_unified_runtime/config.py 的 bot_tts_max_audio_bytes / bot_tts_max_chars（兜底常量 domains/media/tts_presets.py）",
        copies=("docs/design/tts-contract-layer.md", "echo.py「语音」条目 detail 手写数值（人工确认项）"),
        severity=SEVERITY_INFO,
        consequence="文档与帮助文案误导用户和后续施工席（现状活样本：文档仍写 4 MiB、代码与 help 全是 8 MiB）；不影响运行，影响判断。",
        detector=detect_tts_spec_numbers_vs_code,
        verification_gate="python -m pytest tests/test_tts_presets.py -q -p no:cacheprovider 全绿，且本面复算输出「已同步」",
    ),
)


DRIFT_CHECKS_BY_SURFACE: dict[str, DriftCheck] = {check.surface: check for check in DRIFT_CHECKS}


def checks_for(names: Sequence[str] | None = None) -> tuple[DriftCheck, ...]:
    """按面名取登记项；空/None = 全量。未知面名直接忽略（fail-open，不抛）。"""
    if not names:
        return DRIFT_CHECKS
    wanted = [str(name).strip() for name in names if str(name).strip()]
    return tuple(DRIFT_CHECKS_BY_SURFACE[name] for name in wanted if name in DRIFT_CHECKS_BY_SURFACE)
