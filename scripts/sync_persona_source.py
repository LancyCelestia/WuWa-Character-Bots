"""sync_persona_source — 守岸人「人格源 ↔ 运行时副本」一致性门（同步声明机制 v2）.

═══════════════════════════════════════════════════════════════════════════
 本门判什么（ISYNC 2026-09-21 根治后的确切语义，请如实转述、不要再宣称别的）
═══════════════════════════════════════════════════════════════════════════

测绘结论（2026-09-14 原始测绘 + 2026-09-21 ISYNC 只读复测）：
- 生产 BOT_PERSONA_FILES 指向 ChatBot_Runtime/data/persona/守岸人_核心人格.md
  （运行时副本，生产人格正文唯一来源）；
- 仓库 personas/shorekeeper/ 是 git 策展人格源；knowledge/ 下文件被
  BOT_KNOWLEDGE_FILES / glossary 种子回退生产直读（同一份文件，无副本分叉问题）；
- **副本与源是各自演化的独立文本，不是任何源的拷贝或可机械推导的投影**。
  ISYNC 只读实测（逐行精确重合）：identity.md 0.0%、核心知识.md 0.0%、
  表达规范.md 0.0%、worldview_glossary.md 0.0%（difflib ratio ≤0.183）。
  ⇒ 逐字节/逐行「源 == 副本」比对在结构上不可能成立，硬做只会得到一条
  永远红或永远假绿的门。

因此本门唯一能机械成立的关系是：

    **锚定 = 一次人工审阅的凭证，钉住 (源快照 S, 副本哈希 C) 这一对在时刻 T 已对齐。**

v1 的缺陷（ISYNC 复现坐实，见
.superpowers/sdd/2026-09-20-spec-audit/impl-ISYNC-log.md §1）：锚只钉了 C，
S 退化为信息性附注（源码原话「不影响红绿」），副本缺失还一律 SKIP。结果
「改 personas/ 源 → 门全绿 → 生产副本陈旧无人知」，属于机器门失效形态册
（项目记忆《机器门的九种「全绿但没执法」形态》）第 3 条「只比副本不比源」的原件。

v2 把 S 升格为与 C 同等地位的判定项，并补覆盖面自锁：

  红（exit 1）：
  - DRIFT                        副本被单方面改动（哈希 ≠ 锚定 C）
  - SOURCE_DRIFT                 **源侧演进（任一覆盖文件哈希 ≠ 锚定 S）** ← 本次根治
  - SOURCE_UNCOVERED_FILE        personas/shorekeeper 下有文件既不受门覆盖也不在显式豁免
  - SOURCE_UNCOVERED_AT_ANCHOR   覆盖集比锚定新（门升级/新增源文件）→ 需一次性补锚
  - COPY_MISSING_DECLARED        **本机 .env 显式声明了生产人格副本路径，而它不存在**
  - COPY_UNREADABLE / ANCHOR_MISSING  副本存在但读不到 / 锚定缺失或损坏
  跳过（exit 0）：
  - SKIP_COPY_MISSING            仅当副本路径来自约定回退（= 未部署 bot 的机器）

═══════════════════════════════════════════════════════════════════════════
 --adopt 的确切语义（不是同步、不是拷贝）
═══════════════════════════════════════════════════════════════════════════

``--adopt`` **只重录锚定文件，绝不改动 personas/ 源、绝不改动 Runtime 副本、
绝不向任何运行数据写入**。它表达的命题是：

    「我（人）已把 personas/shorekeeper 源的最新内容人工审阅并蒸馏进生产副本，
      这一对（S, C）现在是对齐的。」

不做自动拷贝的理由（论证全文见 ISYNC 日志 §2.2）：①无内容可拷（零行重合，
自动覆盖=破坏性覆写生产 prompt 正文）；②铁律 2 运行数据不可写，门路径不得
触碰 Runtime，而带拷贝的 adopt 等于开一条「一条命令覆写生产人格」的通道，与
已记录在案的「垫片覆写数据事故」同型；③铁律 8 话术须维持守岸人语气，蒸馏是
语言判断，机器不能代劳。
因此自 v2 起 ``--adopt`` **强制 --note**（无审阅说明不许重锚，杜绝「顺手 adopt 抹红」）。

用法：
  python scripts/sync_persona_source.py                 # --check（默认）：绿/跳过 0，红 1
  python scripts/sync_persona_source.py --check --require-copy      # CI/部署机：副本缺失一律红
  python scripts/sync_persona_source.py --check --allow-missing-copy # 维护窗口显式放行
  python scripts/sync_persona_source.py --adopt --note "…人工审阅说明…"

注：任务原设计把锚定放 personas/shorekeeper/SYNC.md；因「personas/ 只读」纪律
优先（人格资产目录不夹带工程元数据），锚定改放 scripts/persona_sync_anchor.json
（待追认项 docs/pending-decisions.md A4）。日后如需迁回，改 ANCHOR_PATH 并挪文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_PATH = Path(__file__).resolve().parent / "persona_sync_anchor.json"
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_COPY_FALLBACK = (
    REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "persona" / "守岸人_核心人格.md"
)

ANCHOR_SCHEMA = 2

# ── 人格参数化（S5c）─────────────────────────────────────────────────────────
# 缺省人格格＝主人格：**不传 --persona 时，本门的根、覆盖集、判据、输出文案与
# 参数化之前逐字一致**（现存门禁与 pre_restart_check.py 的调用面按这一格读）。
DEFAULT_PERSONA_ID: str = "shorekeeper"

#: 人格源根前缀。真身＝ ``personas/<id>``，与
#: domains/chat_reply/character/persona_profile.persona_asset_dir 同一根规；脚本侧不
#: import 插件（门要能在无 nonebot 依赖下跑），只共用「一条附属文件对应一格人格」家规。
PERSONA_SOURCE_ROOT_PREFIX: str = "personas"

#: **每格人格都该有**的人格侧附属文件（跟着人格走的文本腿，文件名里不含人名）。
#: 读点：aliases.txt→runtime/aliases.py、identity.md→人格正文源、
#: imagery_families.txt→character/imagery_roster.py。
PERSONA_ATTACHED_FILES: tuple[str, ...] = (
    "aliases.txt",
    "identity.md",
    "imagery_families.txt",
)

#: **主人格独有**的知识册文件名。人名写在文件名里 ⇒ 绝不摊给别的人格
#: （摊出去＝新人格凭空缺三枚文件，永远撞 SOURCE_UNCOVERED_AT_ANCHOR／锚拒录）。
MAIN_PERSONA_KNOWLEDGE_FILES: tuple[str, ...] = (
    "knowledge/守岸人_核心知识.md",
    "knowledge/守岸人_人格与表达规范.md",
    "knowledge/worldview_glossary.md",
)

#: 人格 id 形状闸（与 character/imagery_roster._PROFILE_ID_RE 同一判据）：档名来自
#: CLI，一旦被塞进 ``../..`` 或 NUL 就成了「拿别人的目录当人格根」的口子。
_PROFILE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _normalize_persona_id(persona_id: str) -> str:
    """CLI/调用方给的 id → 可信的 id；空＝缺省主人格，形状不可信＝抛（绝不猜根）。"""
    raw = str(persona_id or "").strip()
    if not raw:
        return DEFAULT_PERSONA_ID
    if not _PROFILE_ID_RE.fullmatch(raw):
        raise ValueError(f"人格 id 形状不可信（只认字母数字与 -_.）：{persona_id!r}")
    return raw


def persona_source_root(persona_id: str = DEFAULT_PERSONA_ID) -> str:
    """该人格源根的 POSIX 路径（仓库根相对，不含尾斜杠）。"""
    return f"{PERSONA_SOURCE_ROOT_PREFIX}/{_normalize_persona_id(persona_id)}"


#: 主人格源根（历史名；值与参数化之前逐字一致）。
PERSONA_SOURCE_ROOT: str = persona_source_root()


def source_snapshot_files(persona_id: str = DEFAULT_PERSONA_ID) -> tuple[str, ...]:
    """该人格**受门覆盖**的源文件清单（次序稳定；主人格＝参数化之前那枚元组）。

    别的人格＝附属三件 + 其 ``knowledge/`` 下实际存在的 ``*.md``。这样"新人格刚建档、
    知识册还没起名字"不会无故撞红，而该人格根里冒出的**其它**文件（含 knowledge/
    下的非 md、以及任何新目录）照样被 SOURCE_UNCOVERED_FILE 抓住——覆盖面自锁的牙
    一格都没松。
    """
    pid = _normalize_persona_id(persona_id)
    root = persona_source_root(pid)
    items = [f"{root}/{name}" for name in PERSONA_ATTACHED_FILES]
    if pid == DEFAULT_PERSONA_ID:
        items.extend(f"{root}/{name}" for name in MAIN_PERSONA_KNOWLEDGE_FILES)
        return tuple(items)
    knowledge_dir = REPO_ROOT / root / "knowledge"
    try:
        items.extend(
            sorted(
                path.relative_to(REPO_ROOT).as_posix()
                for path in knowledge_dir.glob("*.md")
                if path.is_file()
            )
        )
    except OSError:
        pass
    return tuple(items)


#: 主人格覆盖集（历史名＝门缺省读的那把尺；值与参数化之前逐字一致）。
SOURCE_SNAPSHOT_FILES: tuple[str, ...] = source_snapshot_files()

# 显式豁免表：人格源根下**不受门覆盖**的文件 → 非空理由。
# 豁免必须带理由且不得静默增长（tests/test_persona_source_sync.py 逐条校验）。
SOURCE_EXCLUDED: dict[str, str] = {}

# 豁免的目录名（这些目录下的文件不参与覆盖面枚举；本仓当前无此类目录，
# 保留显式表而非隐式规则，避免「猜哪些目录不算人格」）。
SOURCE_EXCLUDED_DIRS: dict[str, str] = {
    "__pycache__": "字节码缓存目录，非人格资产（源码树零缓存纪律下本不应存在）",
}

# check 状态码
OK = "OK"
DRIFT = "DRIFT"                                # 副本被单方面改动
SOURCE_DRIFT = "SOURCE_DRIFT"                  # 源侧演进、副本未跟进（本次根治的主洞）
SOURCE_UNCOVERED_FILE = "SOURCE_UNCOVERED_FILE"  # 人格源根里出现门覆盖不到的文件
PERSONA_NOT_ENROLLED = "PERSONA_NOT_ENROLLED"  # 该人格源根不存在＝没有可审阅的源（≠覆盖不到）
SOURCE_UNCOVERED_AT_ANCHOR = "SOURCE_UNCOVERED_AT_ANCHOR"  # 锚定缺覆盖文件的源哈希（一次性补锚）
COPY_MISSING_DECLARED = "COPY_MISSING_DECLARED"  # 声明过的生产副本不存在 → 红
SKIP_COPY_MISSING = "SKIP_COPY_MISSING"          # 跳过：仅未声明（约定回退）路径缺失
COPY_UNREADABLE = "COPY_UNREADABLE"
ANCHOR_MISSING = "ANCHOR_MISSING"

RED_STATUSES: frozenset[str] = frozenset(
    {
        DRIFT,
        SOURCE_DRIFT,
        SOURCE_UNCOVERED_FILE,
        PERSONA_NOT_ENROLLED,
        SOURCE_UNCOVERED_AT_ANCHOR,
        COPY_MISSING_DECLARED,
        COPY_UNREADABLE,
        ANCHOR_MISSING,
    }
)

_MISSING_SENTINEL = "<missing>"
ADOPT_CMD = "python scripts/sync_persona_source.py --adopt --note \"…人工审阅说明…\""


def adopt_cmd(persona_id: str = DEFAULT_PERSONA_ID) -> str:
    """回执里那条「怎么重锚」的命令——必须指回**同一格人格**。

    主人格＝参数化之前的原文逐字不变。别的人格带上 ``--persona/--copy``：只给
    ``--adopt --note`` 会重锚**主人格**的凭证，等于「报着新人格的红、递一把改别人格的
    钥匙」（台账 #66★「绝不端别人家的」同型）。
    """
    pid = _normalize_persona_id(persona_id)
    if pid == DEFAULT_PERSONA_ID:
        return ADOPT_CMD
    return (
        "python scripts/sync_persona_source.py --adopt"
        f" --persona {pid} --copy <{pid} 的生产人格副本路径> --note \"…人工审阅说明…\""
    )


def default_anchor_path(persona_id: str = DEFAULT_PERSONA_ID) -> Path:
    """锚定文件路径：一格一本，绝不共用同一份审阅凭证。"""
    pid = _normalize_persona_id(persona_id)
    if pid == DEFAULT_PERSONA_ID:
        return ANCHOR_PATH
    return ANCHOR_PATH.with_name(f"persona_sync_anchor_{pid}.json")


@dataclass(frozen=True)
class CheckResult:
    status: str
    message: str

    @property
    def is_red(self) -> bool:
        return self.status in RED_STATUSES

    @property
    def is_skip(self) -> bool:
        return self.status == SKIP_COPY_MISSING


@dataclass(frozen=True)
class CopyTarget:
    """生产人格副本路径 + **它是怎么被确定的**（声明 vs 约定回退，不靠猜）。"""

    path: Path
    declared: bool
    origin: str  # cli | env | dotenv | fallback


def persona_source_dir(persona_id: str = DEFAULT_PERSONA_ID) -> Path:
    """该人格的源根目录（缺省＝主人格那一格，值与参数化之前逐字一致）。"""
    return REPO_ROOT / persona_source_root(persona_id)


def persona_is_enrolled(persona_id: str = DEFAULT_PERSONA_ID) -> bool:
    """这一格到底有没有「可审阅的源」。

    缺席与「覆盖不到」是两件事：前者＝根压根不存在（新人格还没建档，没有源可审），
    后者＝根在而门看不见某个文件。把前者报成后者，会让人去加覆盖集/豁免表——
    等于把别人的目录认领成自己这一格的源（台账 #66★「绝不端别人家的」同型）。
    """
    return persona_source_dir(persona_id).is_dir()


def _parse_persona_files_value(raw: str) -> Path | None:
    """BOT_PERSONA_FILES 取值 → 首个非空路径；形态不可认时返回 None（不回退猜路径）。"""
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        candidate = raw.strip().strip('"').strip("'")
        return Path(candidate) if candidate else None
    if isinstance(items, list) and items and isinstance(items[0], str) and items[0].strip():
        return Path(items[0].strip())
    return None


def resolve_copy_path(cli_override: str | None = None) -> CopyTarget:
    """解析生产人格副本路径，并如实报告它来自哪一层声明。

    优先级：CLI ``--copy`` > 环境变量 BOT_PERSONA_FILES > 仓库 ``.env`` > 约定回退常量。
    前三层都是**这台机器/这次调用显式声明过**生产人格正文在哪（declared=True，
    路径缺失即红）；只有最后一层是「无声明时的惯例猜测」（declared=False，
    缺失才允许 skip）。
    """
    if cli_override:
        return CopyTarget(Path(cli_override), True, "cli")
    raw = os.environ.get("BOT_PERSONA_FILES")
    origin = "env"
    if not raw:
        raw = None
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("BOT_PERSONA_FILES="):
                    raw = line.split("=", 1)[1].strip()
                    break
        except OSError:
            raw = None
        origin = "dotenv"
    if raw:
        parsed = _parse_persona_files_value(raw)
        if parsed is not None:
            return CopyTarget(parsed, True, origin)
    return CopyTarget(DEFAULT_COPY_FALLBACK, False, "fallback")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_source_snapshot(persona_id: str = DEFAULT_PERSONA_ID) -> dict[str, str]:
    """覆盖集内每个源文件的当前 sha256；读不到记 ``<missing>``（锚定阶段会拒绝）。"""
    snap: dict[str, str] = {}
    for rel in source_snapshot_files(persona_id):
        try:
            snap[rel] = sha256_path(REPO_ROOT / rel)
        except OSError:
            snap[rel] = _MISSING_SENTINEL
    return snap


def _covered_relative_paths(persona_id: str = DEFAULT_PERSONA_ID) -> set[str]:
    """该人格覆盖集相对其源根的路径集合（覆盖面自锁的比较基准）。"""
    root_posix = persona_source_root(persona_id)
    covered: set[str] = set()
    for rel in source_snapshot_files(persona_id):
        full = PurePosixPath(rel)
        root = PurePosixPath(root_posix)
        if full.parts[: len(root.parts)] != root.parts:
            raise ValueError(f"覆盖集路径必须位于 {root_posix}/ 之下：{rel}")
        covered.add(PurePosixPath(*full.parts[len(root.parts) :]).as_posix())
    return covered


def source_coverage_errors(persona_id: str = DEFAULT_PERSONA_ID) -> list[str]:
    """覆盖面自锁：人格源目录里出现既不受覆盖也不在显式豁免的文件。"""
    errors: list[str] = []
    pid = _normalize_persona_id(persona_id)
    root_posix = persona_source_root(pid)
    root = persona_source_dir(pid)
    if not root.is_dir():
        return [f"人格源目录不存在：{root}"]
    covered = _covered_relative_paths(pid)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in covered or rel in SOURCE_EXCLUDED:
            continue
        if set(path.relative_to(root).parts[:-1]) & set(SOURCE_EXCLUDED_DIRS):
            continue
        errors.append(
            f"{root_posix}/{rel} 既不在 SOURCE_SNAPSHOT_FILES 也不在 SOURCE_EXCLUDED"
        )
    return errors


def source_drift_since(
    anchor: dict[str, object], persona_id: str = DEFAULT_PERSONA_ID
) -> list[str]:
    """锚定之后源侧演进的文件清单（v2 起为**判定项**，v1 里只是信息性附注）。"""
    old = anchor.get("source_snapshot")
    if not isinstance(old, dict):
        return []
    return [
        rel
        for rel, now_hash in current_source_snapshot(persona_id).items()
        if old.get(rel) != now_hash
    ]


def missing_source_entries(
    anchor: dict[str, object], persona_id: str = DEFAULT_PERSONA_ID
) -> list[str]:
    """锚定的源快照里缺（或记为 <missing>）覆盖集文件 → 需要一次性补锚。"""
    old = anchor.get("source_snapshot")
    if not isinstance(old, dict):
        return list(source_snapshot_files(persona_id))
    return [
        rel
        for rel in source_snapshot_files(persona_id)
        if not isinstance(old.get(rel), str)
        or len(str(old[rel])) != 64
        or old[rel] == _MISSING_SENTINEL
    ]


def build_anchor(
    copy_path: Path, note: str = "", persona_id: str = DEFAULT_PERSONA_ID
) -> dict[str, object]:
    pid = _normalize_persona_id(persona_id)
    snapshot = current_source_snapshot(pid)
    return {
        "schema": ANCHOR_SCHEMA,
        "persona_id": pid,
        "copy_path": str(copy_path),
        "copy_sha256": sha256_path(copy_path),
        "copy_size": copy_path.stat().st_size,
        "adopted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        # v2：source_snapshot 与 copy_sha256 同等地位，共同构成审阅凭证。
        "source_snapshot": snapshot,
        "source_snapshot_files": list(snapshot),
    }


def load_anchor(anchor_path: Path) -> dict[str, object] | None:
    """读锚定；缺失/损坏/缺关键字段一律返回 None（门按 ANCHOR_MISSING 红）."""
    try:
        data = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("copy_sha256"):
        return None
    return data


def write_anchor(anchor_path: Path, anchor: dict[str, object]) -> None:
    anchor_path.write_text(
        json.dumps(anchor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _anchor_note(anchor: dict[str, object]) -> str:
    return str(anchor.get("note", ""))[:120]


def check(
    copy_path: Path,
    anchor_path: Path,
    *,
    declared_copy: bool = True,
    require_copy: bool = False,
    allow_missing_copy: bool = False,
    persona_id: str = DEFAULT_PERSONA_ID,
) -> CheckResult:
    """门本体。缺省 **fail-closed**：未声明口径一律按「已声明」处理（副本缺失=红），
    只有显式 declared_copy=False 或 --allow-missing-copy 才允许跳过。

    ``persona_id`` 缺省＝主人格那一格：**不传时本门的判据与输出文案与参数化之前
    逐字一致**（现存门禁与 pre_restart_check.py 的调用面按这一格读）。
    """
    pid = _normalize_persona_id(persona_id)
    root_posix = persona_source_root(pid)
    remedy = adopt_cmd(pid)

    # --- 先判「这一格有没有源」：源根缺席时，报副本/覆盖面都是把人往别人的目录引 ---
    if not persona_is_enrolled(pid):
        return CheckResult(
            PERSONA_NOT_ENROLLED,
            f"[红] 人格源根不存在：{root_posix}/ ——这一格压根还没有可审阅的源"
            "（≠「有源而门看不见」的覆盖面问题）。\n"
            f"      处置：把 {', '.join(PERSONA_ATTACHED_FILES)} 备进 {root_posix}/"
            "本身（**绝不指到别的人格目录**，主人格独有的知识册也不摊给这一格），"
            f"再运行 {remedy} 建立这一格自己的审阅凭证。",
        )

    # --- 覆盖面自锁与锚定完整性先于副本读取：即使副本不在，源侧的洞也要报出来 ---
    anchor = load_anchor(anchor_path)

    if not copy_path.exists():
        force_red = require_copy or declared_copy
        if force_red and not (allow_missing_copy and not require_copy):
            why = (
                "本次调用显式 --require-copy"
                if require_copy
                else "BOT_PERSONA_FILES/.env 已显式声明该路径（=这台机器声明了生产人格正文在哪）"
            )
            hint = (
                "确属未部署/维护窗口再加 --allow-missing-copy 显式放行。"
                if declared_copy
                else "未部署机器无需处理；部署机请照声明配置 .env 或加 --require-copy 复检。"
            )
            return CheckResult(
                COPY_MISSING_DECLARED,
                f"[红] 生产人格副本不存在：{copy_path}\n"
                f"      判定为红而非跳过的依据：{why}。\n"
                f"      人格正文丢失=生产人格塌向兜底文案，请先从备份恢复副本"
                f"（同目录 *.bak-* 或 ChatBot_Archive），人工核对后如需重锚跑 {remedy}；"
                f"{hint}",
            )
        return CheckResult(
            SKIP_COPY_MISSING,
            f"[跳过] 副本不存在且已按显式出口放行（--allow-missing-copy）：{copy_path}\n"
            f"      未声明路径的常规 skip 只应发生在「本机从未声明过 BOT_PERSONA_FILES」"
            "的开发机；部署机请去掉 --allow-missing-copy 或改用 --require-copy 复检。",
        )

    try:
        actual = sha256_path(copy_path)
    except OSError as exc:
        return CheckResult(
            COPY_UNREADABLE,
            f"[红] 生产人格副本存在但不可读：{copy_path}（{exc}）",
        )

    if anchor is None:
        return CheckResult(
            ANCHOR_MISSING,
            f"[红] 锚定文件缺失或损坏：{anchor_path}。"
            f"副本当前 sha256={actual[:16]}…；人工审阅源↔副本对齐后运行 {remedy}。",
        )

    coverage = source_coverage_errors(pid)
    if coverage:
        return CheckResult(
            SOURCE_UNCOVERED_FILE,
            f"[红] 人格源覆盖面自锁：以下文件在 {root_posix}/ 里但门看不见它们——\n"
            + "\n".join(f"      - {line}" for line in coverage)
            + "\n      处置：判定它是否属于人格正文源。属于→加进 SOURCE_SNAPSHOT_FILES"
            "（随后需一次性 --adopt 补锚）；不属于→加进 SOURCE_EXCLUDED 并写明理由。"
            "不许为了放行而静默扩大盲区。",
        )

    unanchored = missing_source_entries(anchor, pid)
    if unanchored:
        return CheckResult(
            SOURCE_UNCOVERED_AT_ANCHOR,
            "[红] 锚定的源快照比覆盖集旧（门升级或源侧新增文件），审阅凭证不完整：\n"
            + "\n".join(f"      - {rel}" for rel in unanchored)
            + f"\n      人工核对这些源文件与生产副本已对齐后运行 {remedy} 补锚；"
            "不允许把它们当「没变化」放过。",
        )

    drifted = source_drift_since(anchor, pid)
    adopted = str(anchor.get("adopted_at", "?"))
    expected = str(anchor.get("copy_sha256", ""))

    if drifted:
        return CheckResult(
            SOURCE_DRIFT,
            f"[红] 人格源 {root_posix} 自锚定后已演进，而生产副本未经重新审阅——"
            "这正是「改一处、其余静默陈旧」的形态，故判红：\n"
            + "\n".join(f"      - {rel}" for rel in drifted)
            + f"\n      审阅凭证锚定于 {adopted}（note={_anchor_note(anchor)!r}）。"
            f"\n      处置：把源侧改动人工蒸馏进生产副本 {copy_path}"
            f"（本门与 --adopt 都不代劳拷贝，见模块文档），"
            f"确认二者已对齐后运行 {remedy} 重录凭证。",
        )

    snapshot_files = source_snapshot_files(pid)
    if actual == expected:
        return CheckResult(
            OK,
            f"[绿] 审阅凭证成立：副本 sha256={actual[:16]}… 与锚定一致，"
            f"且 {len(snapshot_files)} 个人格源文件自锚定后零演进"
            f"（锚定于 {adopted}，note={_anchor_note(anchor)!r}）",
        )
    return CheckResult(
        DRIFT,
        f"[红] 生产人格副本被单方面改动：现 sha256={actual[:16]}… ≠ 锚定 "
        f"{expected[:16]}…（锚定于 {adopted}，note={_anchor_note(anchor)!r}）。"
        f"人工审阅副本改动（或对照 {root_posix}/ 源）后运行 {remedy}；"
        "若属误改请先从备份恢复副本。",
    )


def adopt(
    copy_path: Path, anchor_path: Path, note: str = "", persona_id: str = DEFAULT_PERSONA_ID
) -> dict[str, object]:
    """重录**人工审阅凭证**（只写锚定文件；绝不拷贝、绝不改源、绝不写 Runtime）。

    拒绝条件（都在写盘之前）：副本缺失/不可读、覆盖集内有源文件读不到、
    人格源目录存在门覆盖不到的文件、--note 为空。
    """
    pid = _normalize_persona_id(persona_id)
    if not note.strip():
        raise SystemExit(
            "[abort] --adopt 必须带 --note 人工审阅说明（本命令只重录审阅凭证、"
            "不做任何拷贝；无说明的重锚等于「顺手抹红」，拒绝执行）。"
        )
    if not persona_is_enrolled(pid):
        raise SystemExit(
            f"[abort] 人格源根不存在：{persona_source_root(pid)}/ ——没有可审阅的源就"
            "没有可钉的凭证。先把这一格自己的附属文件备进它自己的目录"
            "（绝不指到别的人格目录），再锚定。"
        )
    if not copy_path.exists():
        raise SystemExit(f"[abort] 副本不存在，无法锚定：{copy_path}")
    coverage = source_coverage_errors(pid)
    if coverage:
        raise SystemExit(
            "[abort] 人格源覆盖面自锁未通过，先处置再锚定：\n  - " + "\n  - ".join(coverage)
        )
    snapshot = current_source_snapshot(pid)
    absent = [rel for rel, digest in snapshot.items() if digest == _MISSING_SENTINEL]
    if absent:
        raise SystemExit(
            "[abort] 覆盖集内的源文件读不到，拒绝把 <missing> 钉成审阅凭证："
            + "、".join(absent)
        )
    try:
        anchor = build_anchor(copy_path, note=note, persona_id=pid)
    except OSError as exc:
        raise SystemExit(f"[abort] 副本不可读，无法锚定：{copy_path}（{exc}）") from exc
    write_anchor(anchor_path, anchor)
    return anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "人格源-运行时副本一致性门（--check 校验审阅凭证 / --adopt 重录人工审阅锚定；"
            "本命令不做任何拷贝）"
        )
    )
    parser.add_argument(
        "--check", action="store_true", help="校验源快照+副本哈希==锚定（默认行为）"
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help=(
            "重录人工审阅锚定（只写 scripts/persona_sync_anchor.json；"
            "不拷贝、不改 personas/ 源、不写 Runtime）。必须带 --note。"
        ),
    )
    parser.add_argument(
        "--note", default="", help="--adopt 的人工审阅说明（v2 起必填）"
    )
    parser.add_argument(
        "--copy", default=None, help="覆盖副本路径（默认解析 BOT_PERSONA_FILES→.env）"
    )
    parser.add_argument(
        "--anchor",
        default=None,
        help="覆盖锚定文件路径（默认 scripts/persona_sync_anchor.json）",
    )
    parser.add_argument(
        "--persona",
        default=None,
        help=(
            f"校验/重锚哪一格人格源（缺省＝主人格 {DEFAULT_PERSONA_ID}；"
            "非主人格必须同批显式 --copy，绝不拿主人格声明的正文当这一格的副本判）"
        ),
    )
    parser.add_argument(
        "--require-copy",
        action="store_true",
        help="部署机/CI 用：副本缺失一律判红，压掉约定回退路径的 skip 出口",
    )
    parser.add_argument(
        "--allow-missing-copy",
        action="store_true",
        help="维护窗口显式放行：即使 .env 声明过路径，副本缺失也只跳过不判红",
    )
    args = parser.parse_args(argv)
    if args.require_copy and args.allow_missing_copy:
        parser.error("--require-copy 与 --allow-missing-copy 互斥（放行动作必须唯一确定）")

    try:
        pid = _normalize_persona_id(args.persona or DEFAULT_PERSONA_ID)
    except ValueError as exc:
        parser.error(str(exc))

    if pid != DEFAULT_PERSONA_ID and not args.copy:
        parser.error(
            f"--persona {pid} 必须同批显式 --copy <{pid} 的生产人格副本路径>"
            "（BOT_PERSONA_FILES/.env 声明的是主人格的正文，拿它判这一格＝端别人家的）"
        )

    target = resolve_copy_path(args.copy)
    anchor_path = (
        Path(args.anchor) if args.anchor else default_anchor_path(pid)
    )

    if args.adopt:
        anchor = adopt(target.path, anchor_path, note=args.note, persona_id=pid)
        print(f"[adopt] 已重录审阅凭证：{anchor_path}")
        if pid != DEFAULT_PERSONA_ID:
            print(f"        人格={pid}（一格一本锚定，绝不与主人格共用审阅凭证）")
        print(f"        副本 sha256={anchor['copy_sha256']}（副本内容未被本命令改动）")
        snap = anchor["source_snapshot"]
        assert isinstance(snap, dict)
        print(f"        源快照 {len(snap)} 个文件已钉入凭证（v2 起参与红绿判定）")
        return 0

    result = check(
        target.path,
        anchor_path,
        declared_copy=target.declared,
        require_copy=args.require_copy,
        allow_missing_copy=args.allow_missing_copy,
        persona_id=pid,
    )
    print(result.message)
    if result.is_skip:
        print(
            f"        （路径来源={target.origin}，declared={target.declared}；"
            "skip 不等于通过，部署机请 --require-copy 复检）"
        )
    return 1 if result.is_red else 0


if __name__ == "__main__":
    sys.exit(main())
