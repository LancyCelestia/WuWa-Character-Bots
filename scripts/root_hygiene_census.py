"""仓根卫生尺：仓根**第一层**每一项的唯一分区真身（root hygiene census）。

立尺缘由（用户裁定 4 甲，2026-10-11）：「先立仓根卫生尺，再清根层」。在此之前
``scripts/pre_restart_check.py`` 的 structure_readiness「仓根卫生」那一格**按字面没有尺**，
恒 ``UNDECIDABLE(NO_RULER_ON_CALL:仓根卫生)``——本件就是那一格缺的那把尺。同一次裁定给的
诉求＝「根目录不得有分散文件、所有文件按一级/二级/三级功能物理归类」，所以 MUST-MOVE 桶
必须能**直接当"必移清单"用**：逐枚点名 + 建议落点，不给人一句"你自己找"。

四个桶（仓根第一层每一项**恰好落一桶**，落不进＝UNCLASSIFIED＝红，绝不静默放行）
------------------------------------------------------------------------------
``ALLOWED``      在册白名单。白名单**只住本文件这一枚常量** :data:`ROOT_WHITELIST`，逐枚带理由。
``MUST-MOVE``    该按功能归位的生产/文档件，输出建议落点（按现役板块与 ``domains/<域>`` 命名）。
``DEBRIS``       临时件与残骸：备份副本、tmp/temp 形态、抢救副本、会话规划散料、空壳目录。
``UNCLASSIFIED`` 三把尺都不认的形 ⇒ 当场红，逼人裁。

判据来源（🔴 禁第二真身，逐条点名）
-----------------------------------
* 分区口径＝ `docs/boards/_conventions.md` 的「根目录与 docs/ 只准保留现役权威件与生成物；
  波次过程件留在 .superpowers/」那条留档条款，落点层名表＝同文件的「代码同构」条款。
  本件只**指位置**、不抄正文，也不新建第二套板块树。
* 文件「归主／无主」**不由本件判**：那把尺是 `scripts/physical_placement_census.py` 的
  G-P2（它的扫描面含仓库根一层 ``*.py``）。本件只判"这一项该不该待在仓根第一层"，
  建议落点里的域清单复用 `physical_placement_census.registered_domain_roots()`（同一支）。
* 🔴 生成物残骸（``__pycache__``／``*.pyc``／``.pytest_cache``／``.ruff_cache``／
  ``.mypy_cache``／树内 venv／pytest basetemp／发行元数据壳）**已由
  `scripts/runtime_layout_smoke.py` 执法** ⇒ 本尺只做**引用式复核**：调它的公开判据
  ``scan_generated_residue()``，用它自己报的类别标签给仓根第一层打 DEBRIS
  （见 :func:`generated_residue_by_reference`），绝不另写一份重复规则。
* 🔴 **第二真身风险点名并保持不判**：源码树 ``data/``／``cache/``／``config/`` 三形的判据
  内联在 ``runtime_layout_smoke.main()`` 的字面量里，**没有可复用的公开符号** ⇒ 本尺不抄
  那三条（抄了就是第二真身）。根层若真出现这三形，它们只会落 UNCLASSIFIED（红），
  由 runtime-layout 门与人裁——见 :data:`NOT_ADJUDICATED_BY_THIS_RULER`。

只读纪律（验收的一部分）
------------------------
零写盘：只用 scandir/listdir/stat，不开任何写句柄、不建缓存目录。启动期在**第一个项目树
import 之前**钉 ``sys.dont_write_bytecode``——门自己长出 ``scripts/__pycache__`` 就会被自己
引用的那把尺记成红（S139 那一课的同一修法，真身在 runtime_layout_smoke 顶部注释）。
stdout/stderr 一律重钉 UTF-8：本机控制台默认 cp936，中文读数会 UnicodeEncodeError 把 rc
打成 1＝假红。判「目录是否空壳」只用文件系统宇宙，**绝不用** ``git check-ignore <dir>/``
的目录形态（它给合成输出 rc=0＋空 pattern，而空目录对全部 git 枚举尺隐形——台账 #68★ 同族坑）。

复跑
----
``PYTHONIOENCODING=utf-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0``
``../ChatBot_Runtime/venv/Scripts/python.exe scripts/root_hygiene_census.py --check``
rc：0＝零违规／1＝有违规（MUST-MOVE、DEBRIS、UNCLASSIFIED 都算违规）。argparse 用法错误是 2，
不在本尺的 rc 名册里（聚合器按"没有证据"处理，不当绿也不当红）。

执法锁（本件的自测腿，🔴 项目硬规禁新建 ``tests/test_*.py``，故追加在既有门里）
------------------------------------------------------------------------------
``tests/test_physical_placement_gate.py`` 的「锁⑦ 仓根卫生尺在盘 + 仓根第一层全覆盖分区」一节：
① 真 CLI 跑 ``--check``/``--json``；② 全覆盖分区（每项落桶、``UNCLASSIFIED`` 必空、
桶与总数逐枚对账）；③ 注毒腿（合成条目与 tmp_path 合成根，真树零接触）证明它会变红。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---- 守卫区（必须在任何项目树 import 之前，理由见模块 docstring）----
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

RULER_NAME = "root_hygiene_census"

# ---------------------------------------------------------------------------
# 桶名（词汇即契约：门、聚合器、人读报告共读这四个串，禁同义改名）
# ---------------------------------------------------------------------------
BUCKET_ALLOWED = "ALLOWED"
BUCKET_MUST_MOVE = "MUST-MOVE"
BUCKET_DEBRIS = "DEBRIS"
BUCKET_UNCLASSIFIED = "UNCLASSIFIED"

#: 名册顺序＝报告打印顺序；四桶全覆盖由这把名册长度与逐枚落桶共同自证。
BUCKETS: tuple[str, ...] = (BUCKET_ALLOWED, BUCKET_MUST_MOVE, BUCKET_DEBRIS, BUCKET_UNCLASSIFIED)

#: 违规桶：ALLOWED 之外的三桶都算「仓根第一层不该有这个」。
VIOLATION_BUCKETS: frozenset[str] = frozenset({BUCKET_MUST_MOVE, BUCKET_DEBRIS, BUCKET_UNCLASSIFIED})

#: 🔴 本尺**不判**、且写明为什么判不了（点名第二真身风险，禁止将来"顺手"在这里补一份规则）：
#: 这三形由 ``scripts/runtime_layout_smoke.py`` 的 runtime-layout 门执法，判据内联在它的
#: ``main()`` 字面量里、没有可复用公开符号 ⇒ 本尺读不到牙就不咬，宁可让它落 UNCLASSIFIED 变红。
NOT_ADJUDICATED_BY_THIS_RULER: tuple[str, ...] = ("data/", "cache/", "config/")

#: 引用式复核的对象（写死成可 grep 的两枚字面量，防止将来在本文件里长出第二份生成物判据）。
RESIDUE_REFERENCE_SCRIPT = "scripts/runtime_layout_smoke.py"
RESIDUE_REFERENCE_SYMBOL = "scan_generated_residue"

# ---------------------------------------------------------------------------
# 白名单：仓根第一层「就该在这儿」的件，逐枚带理由。**只住这一枚常量**。
# 键＝裸名（目录不带尾斜杠、不带路径），值＝为什么允许留在根层（出处写到能复核为止）。
# ---------------------------------------------------------------------------
ROOT_WHITELIST: dict[str, str] = {
    # ---- 入口与规范本体（AGENTS.md 第二部分目录地图在册）----
    "AGENTS.md": "工作区唯一入口＝规则/地图/索引本体；体积顶 30000/32768 由机器门 "
                 "test_entry_docs_within_size_ceiling 就地读它，只能在仓根",
    "COMMANDS.md": "命令手册人读版（与生成物 docs/command-catalog.md 成对，AGENTS 第四部分点名它作触发词入口之一）",
    "README.md": "人类门面；分类册 docs/boards/_meta/doc-classification-20260921.md §1 判「保留原地（门面）」",
    "bot.py": "NoneBot 启动入口 + 崩溃守卫（webhook 8080），AGENTS 第三部分消息主链路的顶层件",
    "DESIGN-SPEC.md": "根部视觉/质量入口，自述被 tests/verify_hashes.py 的 SHA-256 清单钉住 ⇒ 分类册判「禁移树」",
    "pyproject.toml": "项目元数据与 ruff/mypy 配置真身；工具从 cwd 向上找它，移走＝lint/typecheck 两道门失明",
    # ---- 凭据与 dotenv 面（AGENTS 规则 3；本尺只看落点，一个字节都不读）----
    ".env": "真实 key 的唯一落点（规则 3：配置里只写 env:变量名），gitignored",
    ".env.example": "幽灵字段「三面齐」之一（config.py + settings.py 热改态 + 本件，台账 #68★），缺一面必红",
    ".env.prod": "被 scripts/runtime_paths.py 的 _DOTENV_FILENAMES 逐字读取的第二个 dotenv 位（盘上声明优先于 env）",
    # ---- VCS 与工具忽略面：只有落在仓根第一层才生效，移走即失效 ----
    ".git": "版本库元数据目录（git 协议要求就在仓根；既不是本仓产物，也不是清理对象，本尺永不进它）",
    ".gitignore": "git 忽略规则本体（本尺多枚理由的出处就是它，但**不拿它当判据**：忽略≠该留）",
    ".gitattributes": "git 属性（换行/文本化）本体",
    ".zcodeignore": "本机工具忽略规则（tracked）；与 .gitignore 同理，只有仓根一层才生效",
    # ---- 目录地图（AGENTS 第二部分逐枚在册）----
    "docs": "文档树：单一活文档 HANDBOOK + design/ + boards/ + 机器册 auto-facts.md 的家",
    "plugins": "主包父目录（plugins/bot_unified_runtime 全仓唯一生产实现面）",
    "scripts": "工程件：dev.ps1 四道门入口 + 各把只读尺（本尺自己的家）",
    "tests": "回归树（全离线 mock；执法腿一律追加在既有门里，禁新建 test 件）",
    "personas": "人格源（AGENTS 规则 8：项目灵魂；改前读规则，Runtime 副本另有一把同步尺）",
    # ---- 在册工程位/证据位（各有引用者，逐枚点名）----
    "webui": "前端工程面（tracked；node_modules 与 dist 由 .gitignore 与 runtime-layout 门罩住，不在本尺面内）",
    "patches": "待审代码补丁位——AGENTS 常令「代码补丁待审不自动部署」的落盘处，台账 #71/#72 逐枚点名 patches/*.md",
    "pins": "完成审计板钉册（哈希锚的受追踪真身；scripts/pre_restart_check.py 与 tests/test_campus_digest.py 直读此路径）",
    ".superpowers": "SDD 波次过程件位（AGENTS 第六部分「SDD＝本机 .superpowers/sdd/…」；P-56 的 PARKED.md 仍 OPEN）",
    ".sdd-reports": "席位报告位（.gitignore 的否定组专门放行 seat-s84/s85＝嵌入吞吐与 ANN 重建成本实测账交付件）",
    # ---- 本机代理工具落点：外部工具自己的状态目录，不是仓库产物，移走＝工具瞎 ----
    ".qoder": "本机 IDE 工作区设置（tracked 的 settings.local.json 就在这儿）",
    ".claude": "本机代理工具配置位（.gitignore「Local agent tool configs」段在册）；⚠ 现算空壳，留删由用户裁",
    ".codex": "本机代理工具配置位（同段在册）；⚠ 现算空壳",
    ".grok": "本机代理工具配置位（同段在册）；⚠ 现算空壳",
    ".workbuddy": "本机代理工具记忆位（tracked，memory/*.md 在写）",
    ".workbuddy-ai": "本机代理工具记忆位（.gitignore 已列 .workbuddy-ai/）；本轮现算仍在写入＝在飞件",
    ".zcode": "本机代理工具计划位（.gitignore 已列 .zcode/）",
}

# ---------------------------------------------------------------------------
# 残骸形态（DEBRIS 的形状判据；名字里就写着出处，别处不得再抄一份）
# ---------------------------------------------------------------------------
#: 会话规划散料：`.gitignore` 的「根散料（会话规划件与截图）」段逐枚点名过的裸名（无锚＝只认这一层）。
SESSION_SCRATCH_NAMES: frozenset[str] = frozenset(
    {"findings.md", "progress.md", "task_plan.md", "COORDINATION.md"}
)

#: 名字形态 → 为什么算残骸。顺序即优先级（第一个命中定判据）。
_DEBRIS_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^%.*%$"), "字面 %…% 目录名＝把仓外暂存根写成了仓内目录（.gitignore「席位脚本与工具记忆」段自陈同形）"),
    (re.compile(r"(?:^|[._-])tmp(?:[._-]|$)", re.IGNORECASE), "名字含 tmp 段＝临时件"),
    (re.compile(r"(?:^|[._-])temp(?:[._-]|$)", re.IGNORECASE), "名字含 temp 段＝临时件"),
    (re.compile(r"bak(?:[._-]|$)", re.IGNORECASE), "备份副本形态；🔴 若它是 .env 的副本就连密钥一起复制（规则 3 绝不允许），本尺不读其内容、只点名"),
    (re.compile(r"\.(?:orig|rej|swp|swo|swn|save|bak|tmp)$", re.IGNORECASE), "编辑器/补丁残留后缀"),
    (re.compile(r"^[._]?rescue", re.IGNORECASE), "抢救副本**位**（名字以 rescue 起头；台账 #70 事故波的中转件，用完该走规则 9 归档）。波次交接档不在这一形里——它落 MUST-MOVE，别把文档当副本"),
    (re.compile(r"-page\.png$", re.IGNORECASE), "会话截图散料（.gitignore「根散料」段 /*-page.png 同形）"),
    (re.compile(r"(?:_probe|probe_)[-a-z0-9]*\.[a-z0-9]+$", re.IGNORECASE), "一次性探针/量具配置件（全仓零引用；留根层＝下一席当配置真身读）"),
    (re.compile(r"^(?:SEAT[-_]|report[-_])", re.IGNORECASE), "席位过程件（规范条款要求留在 .superpowers/，不在仓根）"),
    (re.compile(r"\.log$"), "源码树里的日志落点（规则 6：日志属仓外 Runtime；出现在根层＝相对路径没被重映射的足迹）"),
    (re.compile(r"^~|\.tmp\."), "临时落点形态"),
)

#: 空壳目录的证据文字（判据＝文件系统递归零内容；上限见 _EMPTY_PROBE_MAX_DIRS）。
EMPTY_SHELL_EVIDENCE = "空壳目录（os.scandir 宇宙递归到上限仍无一物）"

#: 同名人撞车位：仓根这枚 ``ChatBot_Runtime`` **不是**运行时根真身（真身＝仓外同级
#: ``../ChatBot_Runtime``，见 AGENTS 第一部分与 scripts/runtime_paths.py）。台账 HANDOFF-STRAY-DIRS-20261007
#: 记的根因＝席位手跑工具时把仓外相对深度多算一层。空壳可清，但**必须**带这句警示，
#: 免得下一席把它当成运行数据误删（规则 2）。
RUNTIME_NAME_LOOKALIKE = "ChatBot_Runtime"
RUNTIME_NAME_LOOKALIKE_WARNING = "⚠ 同名人撞车位：运行时根真身＝仓外同级 ../ChatBot_Runtime（规则 2 保护的是那一个）"

# ---------------------------------------------------------------------------
# 必移件（MUST-MOVE）的落点表：后缀 → 建议落点。生产面归主由物理归类尺判，本尺只给候选位。
# ---------------------------------------------------------------------------
MUST_MOVE_LANDING_BY_SUFFIX: dict[str, str] = {
    ".md": "docs/（文档树；波次过程件按规范条款应进 .superpowers/，历史证据件按规则 9 归档）",
    ".py": "scripts/（工程件）或 plugins/bot_unified_runtime/domains/<域>/<层>/（生产件；"
           "归主与否由 physical_placement_census 的 G-P2 判，本尺不判）",
    ".ps1": "scripts/（四道门入口与工具脚本的家）",
    ".json": "docs/ 或所属域的 data/ 层（配置类进 .env + config.py，不落裸 JSON）",
    ".yaml": "docs/ 或所属域的 data/ 层",
    ".toml": "pyproject.toml 同侧（工程元数据）；内容类请进 docs/",
    ".txt": "docs/（正文件）或 ChatBot_Runtime（运行数据，别放源码树）",
    ".html": "domains/render/card_render/templates/（模板真身在那儿，顶层 output/ 只是再导出垫片）",
    ".png": "docs/ 内随其正文页（本仓暂无 docs/assets/，要先按规范条款立位再放）",
    ".jpg": "docs/ 内随其正文页（同 .png）",
    # ↓ 常见形先给落点，UNCLASSIFIED 留给"真没人认得的怪名"——否则任何一枚 .ini 都把门打成红，
    #   红讯号就废了（AGENTS 规则 11 那条「判据要抓得住事故」同族的可用性考量）。
    ".ini": "scripts/（工具配置随工具走）；确属运行数据则进 ChatBot_Runtime",
    ".cfg": "scripts/（同 .ini）",
    ".conf": "scripts/（同 .ini）",
    ".csv": "domains/<域>/data/（数据表随域）或 ChatBot_Runtime（运行数据）",
    ".tsv": "domains/<域>/data/（同 .csv）",
    ".xml": "domains/<域>/data/（同 .csv）",
    ".jsonl": "ChatBot_Runtime（逐行数据＝运行面，不落源码树）",
    ".pkl": "ChatBot_Runtime（pickle＝运行数据，源码树里它不可再生也不该提交）",
    ".sqlite": "ChatBot_Runtime（规则 2：运行数据一律外置且不可删；搬前先停 bot 并连 -wal/-shm 一起看）",
    ".sqlite3": "ChatBot_Runtime（同 .sqlite）",
    ".db": "ChatBot_Runtime（同 .sqlite）",
    ".zip": "ChatBot_Archive/<日期>/（规则 9：压缩→验证 testzip→移出，并附 manifest）",
    ".tar": "ChatBot_Archive/<日期>/（同 .zip）",
    ".gz": "ChatBot_Archive/<日期>/（同 .zip）",
    ".tgz": "ChatBot_Archive/<日期>/（同 .zip）",
}

#: 目录形 MUST-MOVE 的落点提示（不给唯一答案，只把归位的判据位置指到）。
MUST_MOVE_DIR_LANDING = (
    "按 docs/boards/_conventions.md 的「代码同构」条款归位：生产→domains/<域>/<层>/、"
    "工程→scripts/、文档→docs/；现役域清单＝physical_placement_census.registered_domain_roots()"
)


@dataclass(frozen=True)
class FirstLayerEntry:
    """仓根第一层的一条**盘上事实**（不含任何判定；判定全在 classify_entries）。"""

    name: str
    kind: str  # "dir" / "file" / "other"
    size_bytes: int = 0
    has_content: bool | None = None  # 目录才有（True＝里面有东西，False＝空壳）；文件为 None

    @property
    def is_empty_shell(self) -> bool:
        return self.kind == "dir" and self.has_content is False


@dataclass(frozen=True)
class CensusRow:
    """一项的判决：桶名 + 为什么 + 该去哪 + 证据（JSON 与人读报告共用同一份，禁两套口径）。"""

    name: str
    kind: str
    bucket: str
    reason: str
    landing: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 纯判据（不吃盘：合成条目直接喂进来即可注毒）
# ---------------------------------------------------------------------------


def debris_reason(entry: FirstLayerEntry) -> str | None:
    """名字形态判残骸；不命中给 None（**不给默认桶**——默认桶是 UNCLASSIFIED 的活）。"""
    if entry.name in SESSION_SCRATCH_NAMES:
        return "会话规划散料（.gitignore「根散料」段逐枚点名过的裸名）"
    for pattern, reason in _DEBRIS_NAME_PATTERNS:
        if pattern.search(entry.name):
            return reason
    if entry.is_empty_shell:
        return EMPTY_SHELL_EVIDENCE
    return None


def must_move_reason_and_landing(entry: FirstLayerEntry) -> tuple[str, str] | None:
    """该归位的生产/文档件：HANDOFF 档、文档、脚本、按后缀查落点；查不到给 None。"""
    if entry.kind == "dir":
        return (
            "非白名单、非残骸形态的**目录**＝工程面一级分类，须按规范条款物理归位",
            MUST_MOVE_DIR_LANDING,
        )
    suffix = Path(entry.name).suffix.lower()
    if entry.name.lower().startswith("handoff-") or entry.name.lower().startswith("handover-"):
        return (
            "已结案波次交接档（规范条款：根目录只准留现役权威件；增量应直接更新 docs/HANDBOOK.md）",
            "docs/（移动须**同批**改 AGENTS.md 接手入口表的指针，否则文档链接门当场死项）",
        )
    landing = MUST_MOVE_LANDING_BY_SUFFIX.get(suffix)
    if landing is not None:
        return (f"带后缀 {suffix or '(无后缀)'} 的生产/文档件，仓根第一层不是它的分类位置", landing)
    return None


def classify_entries(
    entries: Iterable[FirstLayerEntry],
    *,
    residue_by_name: Mapping[str, Sequence[str]] | None = None,
    whitelist: Mapping[str, str] | None = None,
) -> list[CensusRow]:
    """给每条事实落**恰好一桶**；优先级＝引用式复核 > 白名单 > 残骸 > 必移 > UNCLASSIFIED。

    为什么这个顺序：生成物残骸由 runtime-layout 那把尺先判（它的类别标签就是判据本身）；
    在册白名单先于残骸形态，是因为「在册工具位今天恰好是空的」不等于它变成了垃圾——
    空壳信号仍然进 ``evidence``，人读报告逐枚看得见，不做静默放行。
    """
    residue = residue_by_name or {}
    allowed = ROOT_WHITELIST if whitelist is None else whitelist
    rows: list[CensusRow] = []
    for entry in entries:
        tags = list(residue.get(entry.name, ()))
        if tags:
            rows.append(
                CensusRow(
                    name=entry.name,
                    kind=entry.kind,
                    bucket=BUCKET_DEBRIS,
                    reason=f"生成物残骸——**引用式复核**：判据来自 {RESIDUE_REFERENCE_SCRIPT}::"
                           f"{RESIDUE_REFERENCE_SYMBOL}()，它自己报的类别＝{'、'.join(tags)}",
                    evidence=tuple(f"residue_class={tag}" for tag in tags),
                )
            )
            continue
        if entry.name in allowed:
            evidence: tuple[str, ...] = ()
            if entry.is_empty_shell:
                evidence = ("empty_shell=当前递归无一物（在册但空着，留删由用户裁）",)
            rows.append(
                CensusRow(
                    name=entry.name,
                    kind=entry.kind,
                    bucket=BUCKET_ALLOWED,
                    reason=allowed[entry.name],
                    evidence=evidence,
                )
            )
            continue
        reason = debris_reason(entry)
        if reason is not None:
            if entry.name == RUNTIME_NAME_LOOKALIKE:
                reason = f"{reason}｜{RUNTIME_NAME_LOOKALIKE_WARNING}"
            evidence = (f"size_bytes={entry.size_bytes}",) if entry.size_bytes else ()
            rows.append(
                CensusRow(
                    name=entry.name,
                    kind=entry.kind,
                    bucket=BUCKET_DEBRIS,
                    reason=reason,
                    evidence=evidence,
                )
            )
            continue
        moved = must_move_reason_and_landing(entry)
        if moved is not None:
            why, landing = moved
            rows.append(
                CensusRow(
                    name=entry.name,
                    kind=entry.kind,
                    bucket=BUCKET_MUST_MOVE,
                    reason=why,
                    landing=landing,
                    evidence=(f"size_bytes={entry.size_bytes}",) if entry.size_bytes else (),
                )
            )
            continue
        rows.append(
            CensusRow(
                name=entry.name,
                kind=entry.kind,
                bucket=BUCKET_UNCLASSIFIED,
                reason="白名单没有它、残骸形态不认、也没有可归位的后缀 ⇒ 不许静默放行，逼人裁",
            )
        )
    return rows


def partition_problems(rows: Sequence[CensusRow], entries: Sequence[FirstLayerEntry]) -> list[str]:
    """全覆盖分区的**形状体检**：每项恰一桶、桶名在册、无 UNCLASSIFIED、名字不重不漏。

    注毒腿与真树腿共读这一把（同一把尺），否则注毒证明的是测试自己的牙，不是门的牙。
    """
    problems: list[str] = []
    for row in rows:
        if row.bucket not in BUCKETS:
            problems.append(f"{row.name}：桶名 {row.bucket!r} 不在 BUCKETS 名册里")
        if row.bucket == BUCKET_UNCLASSIFIED:
            problems.append(f"{row.name}：UNCLASSIFIED（既不在册也非残骸也归不了位）")
        if row.bucket == BUCKET_MUST_MOVE and not row.landing:
            problems.append(f"{row.name}：MUST-MOVE 却没给建议落点＝清单不可执行")
    names = [row.name for row in rows]
    if len(names) != len(set(names)):
        problems.append("同名条目出现两次＝分区不互斥")
    missing = sorted({entry.name for entry in entries} - set(names))
    if missing:
        problems.append("这些第一层条目没落桶：" + "、".join(missing))
    extra = sorted(set(names) - {entry.name for entry in entries})
    if extra:
        problems.append("读数里有不在盘的第一层条目：" + "、".join(extra))
    return problems


# ---------------------------------------------------------------------------
# 取数（全部只读；判"空壳"只用文件系统宇宙）
# ---------------------------------------------------------------------------

#: 空壳探针的目录预算（命中一个文件就早退；到预算一律当"不是空壳"，宁可漏报残骸）。
_EMPTY_PROBE_MAX_DIRS = 4000


def has_any_file(directory: Path, *, max_dirs: int = _EMPTY_PROBE_MAX_DIRS) -> bool:
    """目录里到底有没有一个**非目录条目**（文件/链接/套接字都算内容）。

    只用 scandir 宇宙，且 `is_dir(follow_symlinks=False)`＝**永不跟随联接点**：
    Windows 的 junction 在 ``os.walk`` 眼里是普通目录，会一路钻进去（Runtime/缓存树一旦被
    联接回来就是拖慢与误判两连）。这里既不跟也不循环，代价是联接点本身被算作"有内容"——
    方向是安全的（不会把大树误报成空壳）。
    """
    stack: list[Path] = [directory]
    budget = max_dirs
    while stack:
        current = stack.pop()
        budget -= 1
        if budget <= 0:
            return True
        try:
            with os.scandir(current) as it:
                for child in it:
                    try:
                        if child.is_dir(follow_symlinks=False):
                            stack.append(Path(child.path))
                            continue
                    except OSError:
                        continue
                    return True
        except OSError:
            continue
    return False


def iter_first_layer(root: Path) -> list[FirstLayerEntry]:
    """仓根第一层全集（排序后返回；不筛、不排优先级，判据一概不在这里）。"""
    entries: list[FirstLayerEntry] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return entries
    for name in names:
        path = root / name
        is_dir = False
        try:
            is_dir = path.is_dir()
            size = 0 if is_dir else path.stat().st_size
        except OSError:
            size = 0
        if is_dir:
            entries.append(
                FirstLayerEntry(name=name, kind="dir", size_bytes=0, has_content=has_any_file(path))
            )
        elif path.is_file():
            entries.append(FirstLayerEntry(name=name, kind="file", size_bytes=size))
        else:
            entries.append(FirstLayerEntry(name=name, kind="other", size_bytes=size))
    return entries


def generated_residue_by_reference(root: Path) -> tuple[dict[str, list[str]], str]:
    """引用 runtime-layout 那把尺的**既有判据**（禁在本文件里另写生成物规则）。

    给不出读数时返回状态串（``REFERENCE_UNAVAILABLE`` / ``REFERENCE_SYMBOL_MISSING``），
    调用方照样**不判**那些类别：把"读不到别人的尺"折成"我这把尺自己算一份"＝第二真身，
    正是台账 #68★ 与 AGENTS 铁律反复拦的形态。
    """
    try:
        import runtime_layout_smoke as reference
    except (ImportError, SyntaxError, ValueError) as exc:
        return {}, f"REFERENCE_UNAVAILABLE:{type(exc).__name__}:{exc}"
    scan = getattr(reference, RESIDUE_REFERENCE_SYMBOL, None)
    if not callable(scan):
        return {}, f"REFERENCE_SYMBOL_MISSING:{RESIDUE_REFERENCE_SYMBOL}"
    try:
        findings = scan(root)
    except OSError as exc:
        return {}, f"REFERENCE_SCAN_FAILED:{type(exc).__name__}:{exc}"
    if not isinstance(findings, dict):
        return {}, f"REFERENCE_SHAPE_UNEXPECTED:{type(findings).__name__}"
    return {str(tag): [str(p) for p in paths] for tag, paths in findings.items()}, "OK"


def residue_top_segments(findings: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """把整树残骸读数**投影**到仓根第一层：只取每条路径的首段，类别标签原样带上。"""
    projected: dict[str, list[str]] = {}
    for tag, paths in findings.items():
        for raw in paths:
            head = raw.split("/", 1)[0].strip("/")
            if not head or head == ".":
                continue
            bucket = projected.setdefault(head, [])
            if tag not in bucket:
                bucket.append(tag)
    return projected


def census(root: Path) -> dict[str, Any]:
    """一把尺的完整现算读数（取数 + 判定 + 形状体检；零写盘，可反复跑，读数逐字等值）。"""
    entries = iter_first_layer(root)
    findings, reference_state = generated_residue_by_reference(root)
    rows = classify_entries(entries, residue_by_name=residue_top_segments(findings))
    counts = {bucket: sum(1 for row in rows if row.bucket == bucket) for bucket in BUCKETS}
    return {
        "ruler": RULER_NAME,
        "root": str(root),
        "root_is_repo_root": root.resolve() == REPO_ROOT.resolve(),
        "buckets": list(BUCKETS),
        "total_entries": len(rows),
        "counts": counts,
        "violations": sum(counts[bucket] for bucket in VIOLATION_BUCKETS),
        "whitelist_size": len(ROOT_WHITELIST),
        "residue_reference": reference_state,
        "residue_findings": findings,
        "not_adjudicated_by_this_ruler": list(NOT_ADJUDICATED_BY_THIS_RULER),
        "partition_problems": partition_problems(rows, entries),
        "must_move": [{"file": row.name, "name": row.name, "landing": row.landing} for row in rows
                      if row.bucket == BUCKET_MUST_MOVE],
        "debris": [{"file": row.name, "name": row.name, "reason": row.reason} for row in rows
                   if row.bucket == BUCKET_DEBRIS],
        "unclassified": [row.name for row in rows if row.bucket == BUCKET_UNCLASSIFIED],
        "rows": [row.as_json() for row in rows],
    }


# ---------------------------------------------------------------------------
# 人读面（与 --json 同源：都从 census() 那份读数渲染，禁两套口径）
# ---------------------------------------------------------------------------


def report_lines(data: Mapping[str, Any]) -> list[str]:
    counts: Mapping[str, int] = data["counts"]
    head = (
        f"仓根卫生尺 {data['ruler']} · 面＝{data['root']} 第一层 · "
        f"合计 {data['total_entries']} 项 · 生成物引用态＝{data['residue_reference']}"
    )
    partition = "分区：" + " / ".join(f"{bucket}={counts[bucket]}" for bucket in BUCKETS)
    lines = [head, partition]
    for bucket in (BUCKET_MUST_MOVE, BUCKET_DEBRIS, BUCKET_UNCLASSIFIED):
        rows = [row for row in data["rows"] if row["bucket"] == bucket]
        lines.append(f"[{bucket}] {len(rows)} 枚" + ("" if rows else "（零）"))
        for row in rows:
            marker = "/" if row["kind"] == "dir" else " "
            tail = f" → {row['landing']}" if row["landing"] else ""
            evidence = ""
            if row["evidence"]:
                evidence = " 〔" + "；".join(str(x) for x in row["evidence"]) + "〕"
            lines.append(f"  · {row['name']}{marker}{evidence}｜{row['reason']}{tail}")
    allowed = [row["name"] for row in data["rows"] if row["bucket"] == BUCKET_ALLOWED]
    lines.append(f"[ALLOWED] {len(allowed)} 枚在册（理由逐枚在 --json 里）：" + "、".join(allowed))
    lines.append(
        "🔴 本尺不判：源码树 " + "、".join(NOT_ADJUDICATED_BY_THIS_RULER) +
        f" 由 {RESIDUE_REFERENCE_SCRIPT} 执法（判据无可复用公开符号 ⇒ 引用不到就不另写一份）"
    )
    lines.append("只读声明：本尺零写盘；清理一律走规则 9（备份→验证→移出），本件不动手、也不动 git。")
    return lines


def main(argv: list[str] | None = None) -> int:
    _ensure_text_streams()
    parser = argparse.ArgumentParser(
        prog=f"{RULER_NAME}.py",
        description="仓根第一层卫生普查：ALLOWED / MUST-MOVE / DEBRIS / UNCLASSIFIED 四桶全覆盖。",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="执法口：有违规（MUST-MOVE/DEBRIS/UNCLASSIFIED）即 rc=1，零违规 rc=0（不传也是这套）。",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="只把结构化读数打到 stdout（单枚 JSON 对象）。")
    parser.add_argument("--root", default=str(REPO_ROOT), metavar="DIR", help="被检根，缺省＝本仓仓根（只读）。")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"仓根卫生：UNDECIDABLE（被检根不在盘：{root}）")
        return 2
    data = census(root)
    if args.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for line in report_lines(data):
            print(line)
    verdict = "FAIL" if data["violations"] else "PASS"
    if not args.as_json:
        print(f"仓根卫生：{verdict}（违规 {data['violations']} 枚 / 合计 {data['total_entries']} 项）")
    elif data["violations"]:
        # 机读那一支的末行走 stderr：stdout 必须是**单枚**可解析 JSON，掺行就打断聚合器读数。
        print(f"仓根卫生：FAIL（违规 {data['violations']} 枚）", file=sys.stderr)
    return 1 if data["violations"] else 0


def _ensure_text_streams() -> None:
    """把 stdout/stderr 钉成 UTF-8（cp936 控制台上中文读数会 UnicodeEncodeError＝假红）。

    pytest 捕获态下那两个对象可能没有 ``reconfigure``，或根流已被替换 ⇒ 静默跳过，
    绝不为"打字"这件事把尺自己弄崩。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
