"""模板机制单一写盘口（席 T-TPL0，2026-09-22）。

设计契约见 `.superpowers/sdd/2026-09-22-taxonomy/GATE-PLAN.md` §一（模板机制唯一案）：

- 模板本体住 `docs/templates/<id>.md`（唯一模板源），头部 `@schema` HTML 注释块声明
  sections（竖线序列，尾缀 `?`＝可选）与 params（五列 `key | kind | source | req | domain`，
  在 GATE-PLAN 三列形状上补「必填/取值域」两列以承载任务书字段，块语法逐字一致）。
- 内容页 front-matter `template:`/`params:` 调用模板；有真身事实的参数必须写 `auto:`，
  值由本脚本 provider 表现算（人手不碰数）。
- 机器段 `<!-- TEMPLATE-AUTO:BEGIN/END -->` 内归本脚本、段外归人（镜像 board_doc_sync 的
  BOARD-AUTO 语义）；写盘一律 UTF-8 + LF，渲染区零时间戳，列表按 schema 声明序输出 ⇒
  同输入两次 `--write` 字节相等（常驻用例断言 sha256）。
- 类别注册表住 `scripts/doc_templates.py`（唯一真身；本席 T-TPL0 曾暂住本文件，
  2026-09-22 席 T-GATES 按 GATE-PLAN §二 搬迁完毕，本文件不再持有第二份注册表）。
- **明令不进 conftest autosync 链**（GATE-PLAN §五 C6：不扩「洗绿通道」），漂移靠常驻门红兜底：
  `tests/test_doc_template_pipeline.py`。

用法：
    python scripts/doc_template_sync.py --check    # 只体检（缺省即检）
    python scripts/doc_template_sync.py --write    # 重写模板驱动页的机器段（人写区永不覆盖）
    python scripts/doc_template_sync.py --report   # C2 三列表：各类件数/模板驱动/缺参/多参/异形

不 import 插件包；板块「生成页」身份复用 `scripts/board_doc_sync.py` 的 `live_page_paths`
（同一支取数口，禁第二支板块扫描器；该 import 失败时降级为路径形判据并在 --report 注明）。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "docs" / "templates"

SCHEMA_BEGIN = "<!-- @schema:BEGIN"
SCHEMA_END = "@schema:END -->"
TPL_AUTO_BEGIN = "<!-- TEMPLATE-AUTO:BEGIN -->"
TPL_AUTO_END = "<!-- TEMPLATE-AUTO:END -->"
TPL_AUTO_NOTE = (
    "<!-- 本段由 scripts/doc_template_sync.py 按 docs/templates/ 渲染，请勿手改 -->"
)

_PARAM_RE = re.compile(
    r"^-\s+(?P<key>[a-z][a-z0-9_]*)\s*\|\s*(?P<kind>[a-z]+)\s*\|\s*"
    r"(?P<source>literal|auto:[a-z0-9_]+(?::[A-Za-z0-9_]+)?)\s*\|\s*"
    r"(?P<req>req|opt)\s*\|\s*(?P<domain>[^|]+?)\s*$"
)
_PLACEHOLDER_RE = re.compile(r"\{\{fact:([a-z][a-z0-9_]*)\}\}")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_H2_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.MULTILINE)
# 席 S63（P-30）：模板 @schema 块内的节名别名行（数据源唯一）。
_ALIASES_RE = re.compile(r"^@aliases:\s*(?P<slot>[^=|]+?)\s*=\s*(?P<aliases>.+)$")


class SchemaError(ValueError):
    """@schema 块自身不合法（装载期即红，不带病渲染）。"""


@dataclass(frozen=True)
class Section:
    name: str
    optional: bool


@dataclass(frozen=True)
class Param:
    key: str
    kind: str
    source: str
    required: bool
    domain: str


@dataclass(frozen=True)
class Schema:
    template_id: str
    sections: tuple[Section, ...]
    params: tuple[Param, ...]
    render_zone: str
    #: 与 `sections` 逐位对齐的节名别名集（席 S63 / P-30）。数据源**只有**
    #: `docs/templates/**` 的 @schema 块内 `@aliases: 槽位名=别名1|别名2` 行，
    #: 代码里不许硬编码第二份别名清单；默认空＝该模板不声明别名（既有构造点零破坏）。
    slot_aliases: tuple[frozenset[str], ...] = ()
    #: 席 S153（第二十五批）：**可重复自由槽**开关。缺省 `False`＝今日行为逐字节不变。
    #: 唯一声明处＝本模板 @schema 块内的 `freeform: on` 一行（逐模板 opt-in、默认关）。
    #: 开动者只多一种表达力：在册骨架之外**未命中任何槽位的 H2 小节**不再判
    #: `SECTION_UNKNOWN`，而是作为该槽的第 n 枚实例被接受（同一节名重复出现亦合法——
    #: 施工日志/台账的真形就是「必选骨架＋可重复任意小节」）。它**不**放松：
    #: 必选槽、槽位顺序、槽位重复仍逐字校验；也不豁免裸事实（G-T3 面A 与节名同源取数）。
    #: 资格由既有判据单源执法（`spec_gates_census.freeform_allowed_template_ids`），
    #: 现役规格类启用 ⇒ 装载即红（`freeform_guard`）。
    freeform: bool = False

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(p.key for p in self.params)


@dataclass(frozen=True)
class PageCtx:
    rel: str
    body_no_fm: str


# ---------------------------------------------------------------------------
# @schema 解析（模板侧）
# ---------------------------------------------------------------------------
def parse_schema_text(text: str, template_id: str) -> Schema:
    if SCHEMA_BEGIN not in text or SCHEMA_END not in text:
        raise SchemaError(f"{template_id}: 缺 @schema 块（模板没有 schema=装载即红）")
    block = text.split(SCHEMA_BEGIN, 1)[1].split(SCHEMA_END, 1)[0]
    # @aliases 行报错要点名**模板文件里的行号**（席 S98）：块首行是 SCHEMA_BEGIN 那一行的残尾，
    # 故块内第 k 行 = 文件第 (块前换行数 + k) 行。真树核验：sdd-ledger 的「清单」两行报 10/15。
    block_line_offset = text[: text.index(SCHEMA_BEGIN) + len(SCHEMA_BEGIN)].count("\n")
    sections: tuple[Section, ...] = ()
    params: list[Param] = []
    alias_rows: dict[str, set[str]] = {}
    #: 席 S153：自由槽声明（唯一声明处＝本块内 `freeform: on|off` 一行，只准出现一次）
    freeform: bool | None = None
    #: 别名串 -> {槽位: 模板内首次出现行号}（席 S98／P-51 单射守卫的取数，与守卫同一处）
    alias_homes: dict[str, dict[str, int]] = {}
    for blk_lineno, raw in enumerate(block.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("sections:"):
            items = [s.strip() for s in line[len("sections:"):].split("|") if s.strip()]
            if not items:
                raise SchemaError(f"{template_id}: sections 行为空")
            sections = tuple(
                Section(s[:-1].strip(), s.endswith("?")) if s.endswith("?")
                else Section(s, False)
                for s in items
            )
        elif line.startswith("freeform:"):
            # 席 S153：可重复自由槽的**唯一**声明语法。只认 on/off 两值、只准声明一次；
            # 缺省（无此行）＝关，今日行为逐字节不变。
            if freeform is not None:
                raise SchemaError(
                    f"{template_id}: freeform 行重复声明（自由槽只有一处声明，别建第二本账）"
                )
            val = line[len("freeform:"):].strip()
            if val not in ("on", "off"):
                raise SchemaError(
                    f"{template_id}: freeform 只接受 on/off，实得 {val!r}"
                    "（自由槽是逐模板 opt-in，没有第三种写法）"
                )
            freeform = val == "on"
        elif line.startswith("@aliases:"):
            m = _ALIASES_RE.match(line)
            if not m:
                raise SchemaError(
                    f"{template_id}: @aliases 行不合「槽位名=别名1|别名2」语法：{line!r}"
                )
            aliases = [a.strip() for a in m.group("aliases").split("|")]
            if any(not a for a in aliases):
                raise SchemaError(
                    f"{template_id}: @aliases {m.group('slot')!r} 含空别名（连续/首尾竖线）"
                )
            slot = m.group("slot")
            alias_rows.setdefault(slot, set()).update(aliases)
            for a in aliases:
                alias_homes.setdefault(a, {}).setdefault(slot, block_line_offset + blk_lineno)
        elif line.startswith("-"):
            m = _PARAM_RE.match(line)
            if not m:
                raise SchemaError(f"{template_id}: params 行不合五列语法：{line!r}")
            params.append(
                Param(
                    key=m.group("key"),
                    kind=m.group("kind"),
                    source=m.group("source"),
                    required=m.group("req") == "req",
                    domain=m.group("domain"),
                )
            )
    if not sections:
        raise SchemaError(f"{template_id}: @schema 缺 sections 行")
    if not params:
        raise SchemaError(f"{template_id}: @schema 缺 params 行")
    if len({p.key for p in params}) != len(params):
        raise SchemaError(f"{template_id}: params 键重复")
    zone = extract_auto_zone(text)
    if zone is None:
        raise SchemaError(f"{template_id}: 模板缺 TEMPLATE-AUTO 渲染区")
    for key in _PLACEHOLDER_RE.findall(zone):
        if key not in {p.key for p in params}:
            raise SchemaError(
                f"{template_id}: 渲染区占位 {{{{fact:{key}}}}} 不在 params 声明内（规格外）"
            )
    # 别名必须指向在册槽位（加严：typo 别名不许静默成死数据，S63）
    slot_names = {s.name for s in sections}
    for slot in alias_rows:
        if slot not in slot_names:
            raise SchemaError(
                f"{template_id}: @aliases 指向未在册槽位 {slot!r}（槽位必须在 sections 行）"
            )
    # 单射守卫（席 S98／P-51，S81 现跑抓到的 Critical）：一枚别名串在同一模板内只准命中**一个**
    # 槽位。`_match_slot` 第三级按槽位声明序「先命中即返回」⇒ 跨槽别名等于让实现替内容择一，
    # 「同义不同写」这条边界就此失守：一页真·distinct 节会被静默记成另一槽（缩小扫描面同型）。
    # 报错点名两侧槽位与模板行号；合法修法只有两种——从其中一槽删掉该别名，或给两侧各起不同别名。
    for alias, homes in sorted(alias_homes.items()):
        if len(homes) > 1:
            detail = "、".join(
                f"{s}（第 {ln} 行）"
                for s, ln in sorted(homes.items(), key=lambda kv: kv[1])
            )
            raise SchemaError(
                f"{template_id}: @aliases 别名 {alias!r} 跨槽非单射 ⇒ 命中 {len(homes)} 槽：{detail}"
                "（一枚别名只准属一个槽位：从其中一槽删掉它，或给两侧各起不同别名）"
            )
    slot_aliases = tuple(
        frozenset((alias_rows.get(sec.name) or set()) - {sec.name}) for sec in sections
    )
    # 席 S153 反「万能吞」硬边界①：启用自由槽的模板**必须至少留一枚必选槽**。
    # 否则「骨架」可以整体清空、全类内容一律被自由槽吞下＝把尺子拆掉（§0 六禁的放宽判据）。
    if freeform and not any(not sec.optional for sec in sections):
        raise SchemaError(
            f"{template_id}: 声明 freeform 但骨架无一枚必选槽 ⇒ 自由槽成了万能吞"
            "（加自由槽是给「必选骨架＋任意小节」补表达力，不是取消骨架）"
        )
    return Schema(template_id, sections, tuple(params), zone.strip(), slot_aliases,
                  bool(freeform))


def extract_auto_zone(text: str) -> str | None:
    if TPL_AUTO_BEGIN not in text or TPL_AUTO_END not in text:
        return None
    return text.split(TPL_AUTO_BEGIN, 1)[1].split(TPL_AUTO_END, 1)[0]


#: 席 S153：自由槽资格的取数口（只点名符号，判据一份不抄）。
FREEFORM_ELIGIBILITY_SOURCE = "scripts/spec_gates_census.py:freeform_allowed_template_ids"


def _freeform_allowed_template_ids() -> frozenset[str]:
    """资格集合＝**既有分类判据**的投影（S78 的类别判定 ∪ S126 的内容重判腿落到的既有桶）。

    `spec_gates_census` 反向 import 本模块 ⇒ 惰性导入避免模块级环形
    （同 `main --write` 现调 `face_of_history_page` 的既有先例，席 S105 口径）。
    """
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import spec_gates_census as sgc

    return sgc.freeform_allowed_template_ids()


def freeform_guard(schemas: dict[str, Schema]) -> list[str]:
    """装载期资格执法（方向只准加严）：现役规格类启用自由槽 ⇒ 红。

    - 无模板声明自由槽 ⇒ 立刻返回空，**一个 import 都不触**（今日行为与依赖图逐字节不变）。
    - 有声明而资格取数口不可用 ⇒ fail-closed 判红，绝不静默放行。
    - 判据只有这一支；`load_schemas()`／`_collect()`／`spec_gates_census.compute()`
      三个装载点共用本函数（一处判、三处接，禁第二本账）。
    """
    on = sorted(tid for tid, sch in schemas.items() if sch.freeform)
    if not on:
        return []
    try:
        allowed = _freeform_allowed_template_ids()
    except (ImportError, OSError, ValueError, AttributeError, KeyError, TypeError) as exc:
        return [
            (
                "FREEFORM_GUARD_UNAVAILABLE 自由槽资格取数口不可用"
                f"（{type(exc).__name__}: {exc}）⇒ 已声明自由槽的 {on} 一律拒装载（fail-closed）"
            )
        ]
    return [
        f"FREEFORM_NOT_ELIGIBLE {tid}: 自由槽只对既有判据认定的「过程件/历史台账」类开放"
        f"（资格真身＝{FREEFORM_ELIGIBILITY_SOURCE}，现算在册资格模板={sorted(allowed)}）"
        "；现役规格类启用＝把一次性小节名吞进规格源，拒"
        for tid in on
        if tid not in allowed
    ]


def load_schemas() -> dict[str, Schema]:
    out: dict[str, Schema] = {}
    for path in sorted(TEMPLATE_DIR.glob("*.md")):
        sch = parse_schema_text(
            path.read_text(encoding="utf-8", errors="replace"), path.stem
        )
        errs = freeform_guard({path.stem: sch})
        if errs:
            raise SchemaError(errs[0])
        out[path.stem] = sch
    return out


# ---------------------------------------------------------------------------
# front-matter 解析（页侧，~40 行手写子集，禁嵌套；GATE-PLAN §一.3）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FrontMatter:
    template: str | None
    params: dict[str, str]
    extra_keys: tuple[str, ...]


def parse_front_matter(text: str) -> FrontMatter | None:
    """返回 None＝没有 front-matter（未迁移页）。首个 `---` 块含 template:/params: 才算。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None or end == 1:
        return None
    template: str | None = None
    params: dict[str, str] = {}
    extra: list[str] = []
    in_params = False
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m and not ln.startswith((" ", "\t")):
            key, val = m.group(1), m.group(2).strip()
            if key == "template":
                template = val or None
                in_params = False
            elif key == "params":
                in_params = True
            else:
                in_params = False
                extra.append(key)
        elif in_params and (m2 := re.match(r"^\s+([\w-]+):\s*(.*)$", ln)):
            params[m2.group(1)] = m2.group(2).strip()
        else:
            return None  # 不像本子集（嵌套/列表等）⇒ 不当前置元数据
    if template is None and not params:
        return None
    return FrontMatter(template=template, params=params, extra_keys=tuple(extra))


# ---------------------------------------------------------------------------
# provider 表（auto: 值的现算真身；人手不碰数）
# ---------------------------------------------------------------------------
def _provider_seat_class(arg: str | None, ctx: PageCtx) -> str:
    name = ctx.rel.rsplit("/", 1)[-1]
    if name.startswith("SEAT-"):
        return "SEAT"
    if name.startswith("report-"):
        return "report"
    if name.startswith("progress-"):
        return "progress"
    if name.endswith("-log.md"):
        return "log"
    raise ValueError(f"文件名不合 seat-report 族判据：{name}")


def _section_bullet_count(body: str, slot: str) -> int:
    """`## <slot>（任意后缀）` 小节的 `- ` 流水条数（围栏块内不计）。"""
    lines = body.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if _H2_RE.match(ln):
            t = _H2_RE.match(ln).group(1)  # type: ignore[union-attr]
            if t == slot or t.startswith((slot + "（", slot + "(")):
                idx = i
                break
    if idx is None:
        return 0
    count = 0
    infence = False
    for ln in lines[idx + 1:]:
        if _FENCE_RE.match(ln):
            infence = not infence
            continue
        if _H2_RE.match(ln):
            break
        if not infence and ln.startswith("- "):
            count += 1
    return count


def _provider_page_stat(arg: str | None, ctx: PageCtx) -> str:
    if arg == "ledger":
        return str(_section_bullet_count(ctx.body_no_fm, "账目"))
    raise ValueError(f"未知 page_stat 指标：{arg!r}（在册只有 ledger）")


# ---------------------------------------------------------------------------
# 席 S114（2026-09-22，解阻断 C）：按 S102《K0 三态表》A 表逐枚落 provider。
# 每条铁律：一个来源一个函数、单一取数口、读不到 ⇒ 抛 ValueError（→ resolve_params
# 的 `PROVIDER_FAIL` 点名），**绝不返回空串/占位符糊过**（那既有 `PROVIDER_EMPTY`
# 活性腿兜，也违 §0 六禁的「发明数据源」）。派生式必须能在一枚真页上现算出非空值，
# 否则该参按 `no_source` 处置（不落 provider，只列工单）。
# ---------------------------------------------------------------------------
_SDD_WAVE_RE = re.compile(r"\.superpowers/sdd/([^/]+)/")
_HANDOFF_DATE_RE = re.compile(r"^HANDOFF-.+-(\d{8})\.md$")
_SEAT_ID_RE = re.compile(r"^SEAT-(.+)\.md$")
_STATUS_LINE_RE = re.compile(
    r"^Status:[ \t]*(STARTED|RUNNING|BLOCKED|DONE)\b", re.MULTILINE
)
_PERSONA_DIR_RE = re.compile(r"(?:^|/)personas/([^/]+)/")


def _stem(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


def _categories_by_id() -> dict[str, Any]:
    """类别注册表唯一真身＝`scripts/doc_templates.py`（本席只读复用，禁第二份表）。"""
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import doc_templates as dt

    return {c.cid: c for c in dt.CONTENT_CATEGORIES}


def _read_script(rel_posix: str) -> str:
    """按脚本目录内正相对路径读源（取数口唯一；读不到即抛，fail-closed）。"""
    p = ROOT / rel_posix
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"取数源不可读：{rel_posix}（{exc}）") from exc


def _candidate(arg: str | None, ctx: PageCtx) -> str:
    """code 面 id 的候选值：优先取 `auto:<provider>:<候选>` 的 arg（S116 的管辖面腿传入），
    缺省回落到页文件名 stem（去 `.md`）。**本函数只供候选，不判真伪**——真伪在各自
    provider 里对着真身枚举集校验，不在册即抛（发明值＝§0 六禁）。
    """
    if arg:
        return arg
    return _stem(ctx.rel).removesuffix(".md")


# —— 历史波／路径·正文派生类（S102：derivable 8 行中的 4 枚派生式）——————
def _provider_path_wave(arg: str | None, ctx: PageCtx) -> str:
    """波次 id：`.superpowers/sdd/<wave>/` 段名优先；根层件退化到文件名 8 位日期段。"""
    m = _SDD_WAVE_RE.search(ctx.rel)
    if m:
        return m.group(1)
    md = _HANDOFF_DATE_RE.match(_stem(ctx.rel))
    if md:
        return md.group(1)
    raise ValueError(f"路径无 sdd 波次段且文件名无 HANDOFF 日期段，无法派生 wave：{ctx.rel}")


def _provider_filename_date(arg: str | None, ctx: PageCtx) -> str:
    md = _HANDOFF_DATE_RE.match(_stem(ctx.rel))
    if not md:
        raise ValueError(f"文件名不合 ^HANDOFF-.+-(\\d{{8}})\\.md$，无法派生日期：{_stem(ctx.rel)}")
    return md.group(1)


def _provider_seat_id_from_name(arg: str | None, ctx: PageCtx) -> str:
    m = _SEAT_ID_RE.match(_stem(ctx.rel))
    if not m:
        raise ValueError(f"文件名不合 ^SEAT-(.+)\\.md$，无法派生席位号：{_stem(ctx.rel)}")
    return m.group(1)


def _provider_body_status(arg: str | None, ctx: PageCtx) -> str:
    m = _STATUS_LINE_RE.search(ctx.body_no_fm)
    if not m:
        raise ValueError("页体无 `Status: (STARTED|RUNNING|BLOCKED|DONE)` 行，无法派生 status")
    return m.group(1)


# —— 板块归属／代码家目录（桶级常量，注册表在册）——————
def _provider_category_owner_board(arg: str | None, ctx: PageCtx) -> str:
    cat = _categories_by_id().get(classify(ctx.rel))
    if cat is None or not getattr(cat, "owner_board", ""):
        raise ValueError(f"类别 {classify(ctx.rel)!r} 不在册或无 owner_board")
    return cat.owner_board


def _provider_category_code_home(arg: str | None, ctx: PageCtx) -> str:
    cat = _categories_by_id().get(classify(ctx.rel))
    if cat is None or not getattr(cat, "code_home", ""):
        raise ValueError(f"类别 {classify(ctx.rel)!r} 无在册 code_home")
    return cat.code_home


# —— code 面枚举校验类（真身＝单一取数口；候选∈真身集才返回，否则抛＝不发明）——
def _provider_card_list_id(arg: str | None, ctx: PageCtx) -> str:
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import doc_sync

    pool = set(doc_sync._tpl_list())
    cand = _candidate(arg, ctx)
    if cand not in pool:
        raise ValueError(f"卡 id {cand!r} 不在 doc_sync._tpl_list() 枚举集（{len(pool)} 枚）")
    return cand


def _provider_help_topic_id(arg: str | None, ctx: PageCtx) -> str:
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import doc_sync

    pool = set(doc_sync._help_topics())
    cand = _candidate(arg, ctx)
    if cand not in pool:
        raise ValueError(f"帮助主题 {cand!r} 不在 doc_sync._help_topics() 枚举集（{len(pool)} 枚）")
    return cand


_CONFIG_FIELD_RE = re.compile(r"^    (bot_[a-z0-9_]+):", re.MULTILINE)


def _provider_config_field_key(arg: str | None, ctx: PageCtx) -> str:
    pool = set(_CONFIG_FIELD_RE.findall(_read_script("plugins/bot_unified_runtime/config.py")))
    cand = _candidate(arg, ctx)
    if cand not in pool:
        raise ValueError(f"配置字段 {cand!r} 不在 config.py:Config 的 bot_* 注解字段集（{len(pool)} 枚）")
    return cand


_MICA_BUILDER_RE = re.compile(r'^\s+"([a-z0-9_]+)":', re.MULTILINE)


def _provider_mica_builder_id(arg: str | None, ctx: PageCtx) -> str:
    text = _read_script("tests/test_mica_builders_contract.py")
    block = text.split("_BUILDERS", 1)[1].split("}", 1)[0] if "_BUILDERS" in text else ""
    pool = set(_MICA_BUILDER_RE.findall(block))
    cand = _candidate(arg, ctx)
    if cand not in pool:
        raise ValueError(f"builder id {cand!r} 不在 _BUILDERS 键集（{len(pool)} 枚）")
    return cand


_COPY_POOL_RE = re.compile(r"^([A-Z][A-Z0-9_]*_TEMPLATES)\b", re.MULTILINE)


def _provider_copy_pool_id(arg: str | None, ctx: PageCtx) -> str:
    pool = set(_COPY_POOL_RE.findall(_read_script(
        "plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py")))
    cand = _candidate(arg, ctx)
    if cand not in pool:
        raise ValueError(f"文案池 id {cand!r} 不在 user_copy.py 的 *_TEMPLATES 常量名集（{len(pool)} 枚）")
    return cand


# —— 人格／渲染后端（桶级）——————
def _provider_persona_dir_id(arg: str | None, ctx: PageCtx) -> str:
    m = _PERSONA_DIR_RE.search(ctx.rel)
    if not m:
        raise ValueError(f"路径无 personas/<id>/ 段，无法派生 persona_id：{ctx.rel}")
    return m.group(1)


_RENDER_BACKEND_REL = "plugins/bot_unified_runtime/domains/render/render_backends.py"


def _provider_render_backend_home(arg: str | None, ctx: PageCtx) -> str:
    """渲染后端真身＝桶级常量（jinja-template 类唯一后端）；文件不存在即抛。"""
    if not (ROOT / _RENDER_BACKEND_REL).exists():
        raise ValueError(f"渲染后端真身缺失：{_RENDER_BACKEND_REL}")
    return _RENDER_BACKEND_REL


PROVIDERS: dict[str, Callable[[str | None, PageCtx], str]] = {
    "seat_class": _provider_seat_class,
    "page_stat": _provider_page_stat,
    # —— 席 S114：S102 A 表逐枚落地（历史波派生 6 + 板块归属 2 + code 枚举 5 + 人格/渲染 2）——
    "path_wave": _provider_path_wave,
    "filename_date": _provider_filename_date,
    "seat_id_from_name": _provider_seat_id_from_name,
    "body_status": _provider_body_status,
    "category_owner_board": _provider_category_owner_board,
    "category_code_home": _provider_category_code_home,
    "card_list_id": _provider_card_list_id,
    "help_topic_id": _provider_help_topic_id,
    "config_field_key": _provider_config_field_key,
    "mica_builder_id": _provider_mica_builder_id,
    "copy_pool_id": _provider_copy_pool_id,
    "persona_dir_id": _provider_persona_dir_id,
    "render_backend_home": _provider_render_backend_home,
}

#: 席 S114：每个 provider **必须**在此申报其真身来源（S102 注毒 b「改掉 @schema 的
#: source 即可畅通」的守卫数据源）。形状：`"page:<说明>"` ＝值由页自身路径/正文派生
#: （无外部文件可核验，其活性由 PROVIDER_FAIL/PROVIDER_EMPTY 腿兜）；其余
#: `"相对路径:符号"` 或 `"相对路径"` ＝文件支撑来源，装载守卫用 `Path.exists` +
#: 符号存在核验，解析不了即 fail-closed 判红（见 `_source_ref_resolves`）。
#: 申报来源刻意只准指「页派生」或「真实存在的文件」——把某文件改名 ⇒ 守卫必红点名。
#: 符号段两种形状（席 S134）：裸 `Symbol` ＝文本内出现即算（既有）；`Class.member`
#: ＝ AST 核验宿主类真实存在且该成员在其类体内声明（dataclass 字段即此形，不追基类）。
PROVIDER_SOURCES: dict[str, str] = {
    "seat_class": "page:文件名族（SEAT-/report-/progress-/*-log.md）",
    "page_stat": "page:页体 `## 账目` 节 `- ` 条数",
    "path_wave": "page:路径 sdd 波次段／HANDOFF 文件名日期段",
    "filename_date": "page:文件名 ^HANDOFF-.+-(\\d{8})\\.md$",
    "seat_id_from_name": "page:文件名 ^SEAT-(.+)\\.md$",
    "body_status": "page:页体 ^Status: 行",
    "category_owner_board": "scripts/doc_templates.py:CategoryDef.owner_board",
    "category_code_home": "scripts/doc_templates.py:CategoryDef.code_home",
    "card_list_id": "scripts/doc_sync.py:_tpl_list",
    "help_topic_id": "scripts/doc_sync.py:_help_topics",
    "config_field_key": "plugins/bot_unified_runtime/config.py:Config",
    "mica_builder_id": "tests/test_mica_builders_contract.py:_BUILDERS",
    "copy_pool_id": "plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py:_TEMPLATES",
    "persona_dir_id": "scripts/persona_sync_anchor.json:personas",
    "render_backend_home": _RENDER_BACKEND_REL,
}


def _assign_targets(node: ast.AST) -> list[ast.expr]:
    """赋值类语句的「被赋值目标」列表（三种赋值形状归一，席 S134）。"""
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def _flat_names(target: ast.expr) -> list[str]:
    """赋值目标里的裸名字（`x = …`、`(a, b) = …`）；属性/下标形不在此列。"""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for element in target.elts:
            out.extend(_flat_names(element))
        return out
    return []


def _self_attributes(node: ast.AST) -> set[str]:
    """类体内（含其方法体）出现的 `self.<attr> = …` 属性名＝实例属性；
    遇嵌套 `class` 即停步——那属嵌套类自己的成员，不计进宿主类（防越记越宽）。
    """
    out: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            continue
        for target in _assign_targets(child):
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                out.add(target.attr)
        out |= _self_attributes(child)
    return out


def _class_member_names(cls: ast.ClassDef) -> set[str]:
    """一个 `ClassDef` 的在册成员名（AST 静态核，非文本子串）：类级赋值/注解赋值目标
    （含 dataclass 字段）、类级 `def`/`async def`/嵌套类名、以及类体内的 `self.x =` 实例属性。
    **刻意不追基类**：继承来的成员判「不在册」⇒ fail-closed 可见红；
    反过来若为放行继承而放宽核验，才是不可见的「放过真死引用」。
    """
    members: set[str] = set()
    for stmt in cls.body:
        for target in _assign_targets(stmt):
            members.update(_flat_names(target))
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            members.add(stmt.name)
    members |= _self_attributes(cls)
    return members


def _class_field_resolves(py_path: Path, dotted: str) -> tuple[bool, str]:
    """`<Class>.<member>` 形状核验：宿主类必须**真实存在**于该 .py，且成员在类体内**真实声明**。
    返回 (是否可解析, 失败原因)。解析不了＝判不可解析（fail-closed），绝不静默放行。
    """
    class_name, _dot, member = dotted.partition(".")
    if not class_name or not member or "." in member:
        return False, f"点号形申报需为单层 `类.成员`（现为 {dotted!r}）"
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8", errors="replace"), filename=str(py_path))
    except (OSError, SyntaxError, RecursionError, ValueError) as exc:
        return False, f"宿主文件无法静态解析：{py_path.relative_to(ROOT)}（{type(exc).__name__}: {exc}）"
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        members = _class_member_names(node)
        if member in members:
            return True, ""
        return False, (
            f"类 {class_name} 在册，但成员 {member!r} 不在其类级字段/方法/实例属性之内"
            f"（现算在册成员 {len(members)} 枚，样例 {sorted(members)[:6]}）"
        )
    return False, f"宿主文件内找不到类 {class_name!r}（点号形要求宿主类真实存在，且不追基类）"


def _path_casing_matches(rel_posix: str) -> tuple[bool, str]:
    """路径段逐段与**磁盘真名**比对（席 S134）。Windows 文件系统大小写不敏感 ⇒
    `Scripts/…` 这类宿主目录笔误在 `Path.is_file()` 上看不出来（旧腿既存盲区，非本次引入）；
    本腿把它判红并点名磁盘上的真名。列目录失败 ⇒ 判不可解析（fail-closed，与整支核验同口径）。
    """
    current = ROOT
    for part in PurePosixPath(rel_posix).parts:
        try:
            on_disk = {entry.name for entry in current.iterdir()}
        except OSError as exc:
            return False, f"无法列目录核验路径大小写：{current}（{exc}）"
        if part in on_disk:
            current = current / part
            continue
        near = sorted(n for n in on_disk if n.lower() == part.lower())
        return False, (
            f"路径段 {part!r} 与磁盘真名不符（大小写笔误；本文件系统不区分大小写，"
            f"`is_file` 看不出来）。磁盘上与之同名的真目录/文件={near or sorted(on_disk)[:5]}"
        )
    return True, ""


def _source_ref_resolves(ref: str) -> tuple[bool, str]:
    """申报来源可解析性核验（装载守卫的取数腿）。返回 (是否可解析, 失败原因)。
    - `page:...` → 值由页派生，无外部文件；可解析（真活性在 resolve_params 侧）。
    - `<path>` → 文件存在即可。
    - `<path>:<Symbol>` → `Path.exists` 必真；带符号则符号必出现在文件文本内（既有形状，逐字未动）。
    - `<path>:<Class>.<member>` → 宿主类成员核验（席 S134，AST 静态解析）：类必在、成员必在册；
      宿主非 `.py` ⇒ 判不可解析（点号形只承诺 Python 类成员这一语义，不为 JSON 另发明键路径形状）。
    任何异常（不可读/畸形/语法错）一律判「不可解析」＝fail-closed。
    """
    if ref.startswith("page:"):
        return True, ""
    path_str, _sep, sym = ref.partition(":")
    path_str = path_str.strip()
    if not path_str:
        return False, "来源声明缺文件路径"
    try:
        p = ROOT / path_str
        if not p.is_file():
            return False, f"来源文件不存在：{path_str}"
        casing_ok, casing_why = _path_casing_matches(path_str)
        if not casing_ok:
            return False, casing_why
        if sym and "." in sym:
            if p.suffix != ".py":
                return False, f"点号形（宿主类.成员）申报只支持 .py 宿主：{path_str}"
            return _class_field_resolves(p, sym)
        if sym and sym not in p.read_text(encoding="utf-8", errors="replace"):
            return False, f"符号 {sym!r} 不在 {path_str}"
    except OSError as exc:
        return False, f"来源不可读：{path_str}（{exc}）"
    return True, ""


def _provider_source_guard(schemas: dict[str, Schema]) -> list[str]:
    """「来源在册守卫」：任一被某桶 `@schema` 以 `auto:<name>` 引用的 provider，
    必须①已注册 ②在 `PROVIDER_SOURCES` 申报了来源 ③来源可解析，否则装载红。
    另加防御腿：任一**已注册** provider 未申报来源即红（防「加了函数忘了登记来源」＝
    可被 @schema 指向而无人核验＝发明值通道）。判据不可解析 ⇒ fail-closed。
    """
    viol: list[str] = []
    referrers: dict[str, set[str]] = {}
    for tid, sch in schemas.items():
        for p in sch.params:
            if p.source.startswith("auto:"):
                referrers.setdefault(p.source.split(":")[1], set()).add(tid)
    for name in sorted(referrers):
        where = "/".join(sorted(referrers[name]))
        if name not in PROVIDERS:
            viol.append(
                f"PROVIDER_NOT_REGISTERED {name!r}: 桶 {where} 的 @schema 声明 auto:{name}"
                " 但 PROVIDERS 未注册"
            )
            continue
        if name not in PROVIDER_SOURCES:
            viol.append(
                f"PROVIDER_SOURCE_UNDECLARED {name!r}: 桶 {where} 引用、已注册但未在"
                " PROVIDER_SOURCES 申报真身来源（守卫不可解析 ⇒ fail-closed）"
            )
            continue
        ok, why = _source_ref_resolves(PROVIDER_SOURCES[name])
        if not ok:
            viol.append(
                f"PROVIDER_SOURCE_UNRESOLVED {name!r}（桶 {where}）: 申报来源"
                f" {PROVIDER_SOURCES[name]!r} 不可解析（{why}）⇒ fail-closed 装载红"
            )
    for name in sorted(PROVIDERS):
        if name not in PROVIDER_SOURCES:
            viol.append(
                f"PROVIDER_SOURCE_UNDECLARED {name!r}: 已注册 provider 未申报真身来源（发明值通道）"
            )
    return viol

#: 现算值里出现这些字面量＝占位符冒充「真来自 provider」（席 S2 T-GATE-HARDEN 活性腿，
#: 2026-09-22；攻击依据 SEAT-T-ACCUSE F-2 附带面）。只加严、不新增任何豁免。
_PLACEHOLDER_LITERALS = frozenset(
    {"（未填）", "(未填)", "待填", "待定", "TBD", "TODO", "xxx", "XXX", "N/A", "n/a"}
)


# ---------------------------------------------------------------------------
# 参数求解 + 校验（G-T4 判据的单一入口；门与渲染共用）
# ---------------------------------------------------------------------------
def _validate_domain(p: Param, value: str) -> str | None:
    d = p.domain.strip()
    if p.kind == "number" and not re.fullmatch(r"-?\d+", value):
        return f"非整数：{value!r}"
    if d == "any":
        return None
    if d == "nonempty":
        return None if value.strip() else "值为空"
    if d.startswith("enum:"):
        members = [m.strip() for m in d[len("enum:"):].split(",")]
        return None if value in members else f"不在取值域 {members}"
    if d.startswith("int:"):
        lo_s, hi_s = d[len("int:"):].split("..", 1)
        lo, hi = int(lo_s), int(hi_s)
        try:
            v = int(value)
        except ValueError:
            return f"非整数：{value!r}"
        return None if lo <= v <= hi else f"越出 {lo}..{hi}"
    return f"未知取值域语法：{d!r}"


def resolve_params(
    schema: Schema, fm: FrontMatter, ctx: PageCtx
) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    viol: list[str] = []
    declared = schema.keys
    for key in fm.params:
        if key not in declared:
            viol.append(
                f"EXTRA_PARAM 规格外参数 {key!r}：不在 @schema params 内——"
                "删掉它或按模板升级流程改 @schema"
            )
    for p in schema.params:
        raw = fm.params.get(p.key)
        if p.source.startswith("auto:"):
            parts = p.source.split(":")
            provider_name = parts[1]
            arg = parts[2] if len(parts) > 2 else None
            if raw is None:
                if p.required:
                    viol.append(
                        f"MISSING_PARAM 缺必填参 {p.key!r}：必须写 {p.source!r}（现算）"
                    )
                continue
            if raw != p.source:
                viol.append(
                    f"AUTO_SOURCE_MISMATCH 参数 {p.key!r} 有真身事实却手填 {raw!r}"
                    f"：值必须逐字写 {p.source!r}，由渲染器现算"
                )
                continue
            provider = PROVIDERS.get(provider_name)
            if provider is None:
                viol.append(
                    f"PROVIDER_MISSING auto 提供器 {provider_name!r} 未注册"
                    "（PROVIDERS 表加一行或改 source）"
                )
                continue
            try:
                val = provider(arg, ctx)
            except ValueError as exc:
                viol.append(f"PROVIDER_FAIL {p.key!r}: {exc}")
                continue
            # —— S2 参数语义活性腿：@schema 声明为 req 且 source 指向真身 provider 的参数，
            # 值必须真来自 provider 现算。字面量冒充=上方 AUTO_SOURCE_MISMATCH、缺参=上方
            # MISSING_PARAM 已拦；这里补最后一种：provider 跑通了却交出空值/占位符。
            if p.required and (
                not val.strip()
                or "{{fact:" in val
                or val.strip() in _PLACEHOLDER_LITERALS
            ):
                viol.append(
                    f"PROVIDER_EMPTY {p.key!r}: req 且 source={p.source!r} 的参数，"
                    f"provider 现算值不可用（空值/占位符冒充）：{val!r}"
                    "——有真身事实的参数必须由现算给出非空真值"
                )
                continue
            if (bad := _validate_domain(p, val)) is not None:
                viol.append(f"DOMAIN_FAIL 现算值 {p.key!r}={val!r}：{bad}")
            values[p.key] = val
        else:  # literal
            if raw is None or raw == "":
                if p.required:
                    viol.append(f"MISSING_PARAM 缺必填参 {p.key!r}（literal）")
                continue
            if (bad := _validate_domain(p, raw)) is not None:
                viol.append(f"DOMAIN_FAIL 参数 {p.key!r}={raw!r}：{bad}")
            values[p.key] = raw
    return values, viol


# ---------------------------------------------------------------------------
# 渲染（字节确定性：只依赖 schema 声明序 + 现算/字面值，零时间戳）
# ---------------------------------------------------------------------------
def render_block(schema: Schema, values: dict[str, str]) -> str:
    def _sub(m: re.Match[str]) -> str:
        return values.get(m.group(1), "（未填）")

    return _PLACEHOLDER_RE.sub(_sub, schema.render_zone)


def render_page_text(schema: Schema, values: dict[str, str]) -> str:
    return (
        f"{TPL_AUTO_BEGIN}\n{TPL_AUTO_NOTE}\n\n"
        f"{render_block(schema, values).rstrip()}\n{TPL_AUTO_END}"
    )


def block_sha256(schema: Schema, values: dict[str, str]) -> str:
    return hashlib.sha256(
        render_page_text(schema, values).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# 章节形状（G-T2 判据：必选集合精确 + 顺序为子序列 + 表外节=规格外）
# ---------------------------------------------------------------------------
# 席 S63（P-30）「认名」两级放宽 = 剥形 + 别名，**只影响节名到槽位的映射**，
# 不影响节数（SECTION_MISSING / SECTION_UNKNOWN）与节序（SECTION_ORDER）判定：
# 真缺一节 / 真多一节 / 真换序 / 用同义写法伪装重复 ⇒ 一律仍红（反向自测见
# tests/test_doc_template_pipeline.py 末段）。不变量（S20 缺口二同源）：
# 「裸事实=0 才准驱动」的前置在 --write 侧，与本函数无关。
_CN_NUM = "〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟"
# 语料实证的前缀族（S6/S21R 点名：「一、」「0. 五问」「§0 一页速览」「贰、」「3.6」「（三）」「第肆部分：」）
_PREFIX_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        rf"§\s*(?:[{_CN_NUM}\d]+(?:[.．]\d+)*|[①-⑳])?\s*[、.．:：]?\s*",
        rf"第[{_CN_NUM}\d]+(?:部分|章|节|篇|讲|幕|回)[部]?[：:、.．]?\s*",
        rf"[（(]\s*(?:[{_CN_NUM}]+|\d+(?:[.．]\d+)*)\s*[）)][：:、.．]?\s*",
        rf"[{_CN_NUM}]+[、.．。:：]\s*",
        # 数字系列：分隔符后不许紧跟数字（防「3.6」被回溯剥成「6」），
        # 纯点分形（3.6）不许紧跟字母（防「2.5D」被剥成「D」）——两形互补、各带负向前查
        r"\d+(?:[.．,]\d+)*[、.．。:：](?!\d)\s*",
        r"\d+(?:[.．,]\d+)+(?![0-9A-Za-z])\s*",
        r"[①-⑳]\s*",
    )
)


def _strip_section_prefix(heading: str) -> str:
    """剥节名**前缀**编号/符号/空白（不动词尾、不动正文），循环至不动点。

    纯前缀节名（如「一、」本身）剥为空 ⇒ 回退原串，绝不产出空名。
    该函数只服务认名；比对失败仍按原逻辑记 SECTION_UNKNOWN。
    """
    h = heading.strip()
    while True:
        for pat in _PREFIX_STRIP_PATTERNS:
            m = pat.match(h)
            if not m:
                continue
            cand = h[m.end():].strip()
            if cand:
                h = cand
                break
        else:
            return h


def _name_hit(h: str, name: str) -> bool:
    """既有的严判形状：逐字相等，或「名称（/（后缀」限定形（S20 前的原始语义）。"""
    return h == name or h.startswith((name + "（", name + "("))


def _match_slot(schema: Schema, heading: str) -> int | None:
    # 第一级：逐字严判——旧逻辑一字不动地保留，命中序=槽位声明序
    h = heading.strip()
    for i, sec in enumerate(schema.sections):
        if _name_hit(h, sec.name):
            return i
    # 第二级：剥形后逐字（只影响认名；缺节/多节/换序判定在 check_sections 不动）
    hn = _strip_section_prefix(h)
    if hn != h:
        for i, sec in enumerate(schema.sections):
            if _name_hit(hn, sec.name):
                return i
    # 第三级：@aliases 同义集（数据只来自 docs/templates/**，禁止代码内第二份清单）
    for i, al in enumerate(schema.slot_aliases):
        if any(_name_hit(h, a) for a in al) or (
            hn != h and any(_name_hit(hn, a) for a in al)
        ):
            return i
    return None


def _human_body(text: str) -> str:
    """剥 front-matter、剥机器段、（标题抽取侧）剥围栏——与 SHAPE-STATS 测量纪律同口径。"""
    lines = text.splitlines()
    body_from = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        body_from = end + 1 if end else 0
    out: list[str] = []
    infence = False
    in_auto = False
    for ln in lines[body_from:]:
        if ln.strip() == TPL_AUTO_BEGIN:
            in_auto = True
            continue
        if ln.strip() == TPL_AUTO_END:
            in_auto = False
            continue
        if in_auto:
            continue
        if _FENCE_RE.match(ln):
            infence = not infence
            continue
        if not infence:
            out.append(ln)
    return "\n".join(out)


#: 席 S153 反「万能吞」硬边界②：自由槽的标题长度上限（语料实测 H2 名 ≤ 40 字符，
#: 取 60 留余量；正文整段塞进一行标题＝把散文伪装成小节，拒）。
_FREEFORM_MAX_NAME = 60


def _freeform_reject_reason(heading: str) -> str | None:
    """自由槽只接受 **H2 标题形**的名字，拒绝任意文本（简报②(d)）。

    返回 `None`＝合格；否则给拒因（该节仍按 `SECTION_UNKNOWN` 记账，**不新增码名**，
    故 G-T2 的记账单位与既有码表一字不动）。候选集本身就来自 `_H2_RE`——散文行、
    H1/H3+ 标题、围栏内的 `## ...` 压根不是候选，进不到这里（边界的第一层由取数口给出）。
    """
    n = heading.strip()
    if not n or not _strip_section_prefix(n):
        return "剥编号前缀后为空名"
    if "|" in n:
        return "含骨架声明分隔符 `|`（进骨架必歧义）"
    if "```" in n or "~~~" in n:
        return "含围栏标记"
    if "{{fact:" in n:
        return "含 {{fact:}} 占位（假指针）"
    if "\n" in n:
        return "含换行（多行伪装成一行标题）"
    if len(n) > _FREEFORM_MAX_NAME:
        return f"标题长度 {len(n)} 超上限 {_FREEFORM_MAX_NAME}（正文塞进标题形）"
    return None


def freeform_instances(schema: Schema, text: str) -> list[str]:
    """该页被自由槽接管的 H2 小节（按出现序；同一节名可重复出现）。

    观测用取数口（判据仍只有 `check_sections` 一处）：未启用自由槽 ⇒ 恒 `[]`。
    """
    if not schema.freeform:
        return []
    out: list[str] = []
    for h in (m.group(1) for m in _H2_RE.finditer(_human_body(text))):
        if _match_slot(schema, h) is None and _freeform_reject_reason(h) is None:
            out.append(h.strip())
    return out


def check_sections(schema: Schema, text: str) -> list[str]:
    viol: list[str] = []
    heads = [m.group(1) for m in _H2_RE.finditer(_human_body(text))]
    seen_idx: list[int] = []
    hit_slots: set[int] = set()
    for h in heads:
        i = _match_slot(schema, h)
        if i is None:
            if schema.freeform:
                # 席 S153：可重复自由槽——未命中任何在册槽位的 H2 小节按该槽的第 n 枚实例
                # 接受（重复节名亦合法）。**只此一处放行**，且必选槽/顺序/槽位重复判定在上
                # 面与下面照常逐字执行：自由槽永远不能顶替一枚必选槽（它进不了 hit_slots）。
                reason = _freeform_reject_reason(h)
                if reason is None:
                    continue
                viol.append(
                    f"SECTION_UNKNOWN 规格外小节 {h!r}：{reason} ⇒ 不合自由槽的 H2 标题形边界"
                )
                continue
            viol.append(
                f"SECTION_UNKNOWN 规格外小节 {h!r}：模板 sections 只认 "
                f"{[s.name for s in schema.sections]}（改名或走模板升级）"
            )
            continue
        if i in hit_slots:
            viol.append(f"SECTION_DUPLICATE 小节 {h!r} 重复出现：一类内容一份骨架")
            continue
        hit_slots.add(i)
        seen_idx.append(i)
    for i, sec in enumerate(schema.sections):
        if not sec.optional and i not in hit_slots:
            viol.append(f"SECTION_MISSING 缺必选节 {sec.name!r}")
    if seen_idx != sorted(seen_idx):
        viol.append(
            f"SECTION_ORDER 章节顺序 {seen_idx} 偏离模板声明序（须为其子序列）"
        )
    return viol


# ---------------------------------------------------------------------------
# 单页体检（判据纯函数，喂真页与注毒同一支）
# ---------------------------------------------------------------------------
def check_page(
    schema: Schema, text: str, fm: FrontMatter, ctx: PageCtx
) -> list[str]:
    viol: list[str] = [
        f"FM_EXTRA_KEY 规格外 front-matter 键 {k!r}：只认 template:/params:"
        for k in fm.extra_keys
    ]
    values, v1 = resolve_params(schema, fm, ctx)
    viol += v1
    zone = extract_auto_zone(text)
    if zone is None:
        viol.append(
            f"AUTO_MISSING 缺 {TPL_AUTO_BEGIN} 机器段（跑 python scripts/"
            "doc_template_sync.py --write 注入）"
        )
    elif zone.replace(TPL_AUTO_NOTE + "\n\n", "", 1).strip() != render_block(
        schema, values
    ).strip():
        viol.append(
            "AUTO_DRIFT 机器段与模板渲染结果不逐字节一致（跑 --write；勿手改段内）"
        )
    if "{{fact:" in _human_body(text):
        viol.append("FACT_LEAK 人写区残留 {{fact:KEY}} 占位：事实要么进机器段，要么删")
    viol += check_sections(schema, text)
    return viol


# ---------------------------------------------------------------------------
# 管辖面（单一取数口；计数与违规共用）
# ---------------------------------------------------------------------------
@dataclass
class PageInfo:
    rel: str
    path: Path
    text: str
    fm: FrontMatter | None = None
    category: str = ""
    violations: list[str] = field(default_factory=list)


_SEAT_NAME_RE = re.compile(r"^(SEAT-|report-|progress-)|-log\.md$")
#: 席 S83（《S39》＋S73 交回的四枚 `declared_no_page`）：`sdd-brief` 簇的**路径形**判据。
#: 注册表旧 reason 写「无 H2 的任务书/README/PLAN」，实测该簇多数成员**有** 3–17 枚 H2
#: （`BRIEFS.md` 本身就有），"无 H2" 是 S21R 的分簇口径而非可执行判据 ⇒ 落地为文件名族：
#: `BRIEF(S).md / PLAN.md / README.md` 与任意 `*-brief*.md`（`.superpowers/` 面内）。
_SDD_BRIEF_NAME_RE = re.compile(r"^(?:briefs?|plan|readme)\.md$|brief", re.IGNORECASE)
#: 人格三簇的派生判据（席 S62 分簇、席 S83 接线）：**按文件名派生、不建第二真身**；
#: 不匹配任何一簇的人格件留在 `persona-knowledge`（残差类，注册表在册模板＝`persona`）。
#: R-17 裁定「人格正文禁注机器段」⇒ 这五类（含残差）**只做归类、永不挂 front-matter**，
#: 其在册模板是「骨架契约」（供人对照书写），不是驱动口（G-T1 债面继续按未迁移页记账）。
_PERSONA_CLUSTERS: tuple[tuple[str, str], ...] = (
    ("identity.md", "persona-numbered"),
    ("worldview_glossary.md", "persona-inject-data"),
    ("核心知识", "persona-provenance"),
)
_BOARD_INDEX_REL = "docs/boards/README.md"
_BOARD_LIVE: set[Path] | None = None
_BOARD_LIVE_SOURCE = "uninitialized"


def _board_live_paths() -> tuple[set[Path], str]:
    """复用 board_doc_sync 的权威取数口（禁第二支板块扫描器）；失败降级路径形判据。"""
    global _BOARD_LIVE, _BOARD_LIVE_SOURCE
    if _BOARD_LIVE is not None:
        return _BOARD_LIVE, _BOARD_LIVE_SOURCE
    try:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import board_doc_sync as bds

        boards, problems = bds.build_tree()
        _BOARD_LIVE = bds.live_page_paths(boards) if not problems else set()
        _BOARD_LIVE_SOURCE = "live_page_paths"
    except Exception:  # noqa: BLE001 —— 降级面只影响 --report 分类注记，不影响判红
        _BOARD_LIVE = set()
        _BOARD_LIVE_SOURCE = "path-fallback"
    return _BOARD_LIVE, _BOARD_LIVE_SOURCE


def classify(rel: str) -> str:
    """页 → 内容类别。**类别名与判据与 CENSUS §一 一字不差**（G-T5 据此对账）。

    深度口径按 CENSUS：索引页 `docs/boards/README.md`＝`board-index`（席 S83《S39》，骨架真身
    `board_doc_sync.py:INDEX_BODY`），单板块页 `docs/boards/BNN/README.md`＝board-l1，
    `docs/boards/BNN/<l2>/README.md`＝board-l2，`docs/boards/BNN/<l2>/<l3>.md`＝board-l3。
    （2026-09-22 席 T-GATES 修正：本函数旧版把 l1 记成 l2、把 l2/l3 全塌成 l3，
    与 CENSUS 三本账 11/57/157 不符 ⇒ 板块页 canon 分派跟着错位。）
    """
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith(".superpowers/"):
        if _SEAT_NAME_RE.search(name):
            return "seat-report"
        return "sdd-brief" if _SDD_BRIEF_NAME_RE.search(name) else "sdd-ledger"
    if rel == "AGENTS.md":
        return "root-rules"
    if rel.startswith("docs/templates/"):
        return "template-source"
    if rel.startswith("docs/boards/"):
        if "_meta/" in rel or name == "_conventions.md":
            return "board-meta"
        if rel == _BOARD_INDEX_REL:
            # 席 S83（《S39》）：板块树索引页自成一类，骨架真身＝`board_doc_sync.py:INDEX_BODY`。
            # 它旧版与单板块页同判 `board-l1` ⇒ G-T2 唯一偏离件（S35 取证：硬改索引页凑
            # L1 骨架＝假绿）。正解＝另立一类，canon 取该页现状真形，转换后天然绿。
            return "board-index"
        seg = rel.split("/")
        if name == "README.md" and len(seg) <= 4:
            return "board-l1"
        if name == "README.md" and len(seg) == 5:
            return "board-l2"
        return "board-l3"
    if rel == "docs/HANDBOOK.md":
        return "handbook"
    if rel == "docs/acceptance-manual.md":
        return "acceptance"
    if rel == "docs/route-matrix.md":
        return "route-matrix"
    if rel.count("/") == 1 and ("catalog" in name or name == "db-owners.md"):
        return "catalog"
    if rel.startswith("docs/design/"):
        return "design-spec"
    if rel.startswith("docs/"):
        return "doc-misc"
    if rel.startswith("personas/"):
        for needle, cid in _PERSONA_CLUSTERS:
            if needle in name:
                return cid
        return "persona-knowledge"
    if name.startswith(("HANDOFF-", "HANDOVER-")):
        return "root-handoff"
    return "root-report"


#: 类别注册表真身已搬至 `scripts/doc_templates.py::CONTENT_CATEGORIES`（G-T5 唯一据此判）。

#: 板块生成页（含 l1/l2/l3）禁带 front-matter；docs/boards 下非 _meta/_conventions 页。
def _is_board_generated(rel: str) -> bool:
    return rel.startswith("docs/boards/") and "/_meta/" not in rel and not rel.endswith(
        "_conventions.md"
    )


def walk_content_pages(root: Path | None = None) -> Iterable[PageInfo]:
    base = root or ROOT
    surfaces: list[Path] = []
    if (base / "docs").is_dir():
        surfaces += [p for p in (base / "docs").rglob("*.md")]
    if (base / ".superpowers").is_dir():
        surfaces += [
            p for p in (base / ".superpowers").rglob("*.md")
            if "__pycache__" not in p.parts
        ]
    if (base / "personas").is_dir():  # 2026-09-22 席 T-GATES 补：persona-knowledge 是 CENSUS 在册类
        surfaces += [p for p in (base / "personas").rglob("*.md")]
    if base == ROOT:
        # 席 S20 K-2（2026-09-22，加严）：旧白名单只枚 AGENTS/COMMANDS/HANDOFF-*/HANDOVER-*，
        # ⇒ `classify()` 的 `root-report` 分支永不触发、根层 ~13 枚 md 永久免检
        #   （S10 反证：CENSUS 记 root-report=13、门现算=1）。改为穷举根层全部 `*.md`
        #   （Windows 保留名 `nul` 无扩展名本就不匹配 `*.md`，仍显式排掉以防万一），
        #   分类一律交给 `classify()` 真跑；G-T1 会因此上升，如实报（不改基线）。
        surfaces += [p for p in base.glob("*.md") if p.name != "nul"]
    for p in sorted(set(surfaces), key=lambda x: x.relative_to(base).as_posix()):
        rel = p.relative_to(base).as_posix()
        if "__pycache__" in Path(rel).parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        yield PageInfo(rel=rel, path=p, text=text, category=classify(rel))


def annotate(pages: Iterable[PageInfo], schemas: dict[str, Schema]) -> list[PageInfo]:
    out: list[PageInfo] = []
    for pg in pages:
        if pg.category == "template-source":
            out.append(pg)  # 模板源自己不是内容页，schema 装载错误在 _collect 侧点名
            continue
        pg.fm = parse_front_matter(pg.text)
        if pg.fm is None:
            out.append(pg)
            continue
        if _is_board_generated(pg.rel):
            pg.violations = ["GENERATED_WITH_FM 板块生成页禁 front-matter（归板生成器拥有）"]
            out.append(pg)
            continue
        if not pg.fm.template:
            pg.violations = ["NO_TEMPLATE_KEY front-matter 缺 template:（只有 params 不成页籍）"]
            out.append(pg)
            continue
        schema = schemas.get(pg.fm.template)
        if schema is None:
            pg.violations = [
                f"TEMPLATE_MISSING 模板 {pg.fm.template!r} 不存在于 docs/templates/（先建模板再调用）"
            ]
            out.append(pg)
            continue
        ctx = PageCtx(rel=pg.rel, body_no_fm=pg.text)
        pg.violations = check_page(schema, pg.text, pg.fm, ctx)
        out.append(pg)
    return out


# ---------------------------------------------------------------------------
# 写盘（人写区永不覆盖；镜像 board_doc_sync._merge 的段替换语义）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 缺口二·前置校验取数腿（席 S20，2026-09-22）：判据调 `doc_fact_discipline`，与 G-T3 同源。
# ---------------------------------------------------------------------------
class FactVocabUnavailable(RuntimeError):
    """G-T3 同源词表读不到／为空 ⇒ 枚举那把尺子会静默失效，`--write` 必须判红拒写
    （席 S83 收口 S70 的 P-S70-2 第二半：旧写法 `except: return set()` ＋ `vocab or None`
    让前置在退化路径上把「枚举-only 页」数成 0 行，等于给「裸事实=0 才准驱动」开了后门）。"""


def _load_fact_vocab() -> set[str] | None:
    """G-T3 同源词表（与 `spec_gates_census.compute()` 同一支取数口，不复制第二套）。

    **席 S83 加严**：取不到、或取到空集，一律返回 `None`（旧版返回 `set()` ⇒ 调用方
    `vocab or None` 把枚举尺子静默关掉）。是否拒写由调用方判（fail-closed）。
    """
    try:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import board_doc_sync as bds

        vocab = set(bds.load_help_topics()) | {str(k) for k in bds.load_route_kind_members()}
    except Exception:  # noqa: BLE001 —— 不吞成「空集放行」，交调用方判红
        return None
    return vocab or None


def _zone_matches_render(pg: PageInfo, inner: str, schemas: dict[str, Schema]) -> bool:
    """该 `TEMPLATE-AUTO` 段是否**已逐字节等于**本模板对本页的渲染结果（机器所有的判据）。

    与 G-T3 的 `_auto_zone_verified` 同哲学：只有当场可复现的机器段才算「不是人写的」；
    漂移段、板块 `BOARD-AUTO` 段、参数不合法页的段——一律不免责（里面的人话照常计数）。
    """
    if pg.fm is None or not pg.fm.template or pg.fm.template not in schemas:
        return False
    schema = schemas[pg.fm.template]
    values, viol = resolve_params(schema, pg.fm, PageCtx(rel=pg.rel, body_no_fm=pg.text))
    if viol:
        return False
    return (
        inner.replace(TPL_AUTO_NOTE + "\n\n", "", 1).strip()
        == render_block(schema, values).strip()
    )


def naked_fact_findings(
    text: str,
    vocab: set[str] | None = None,
    *,
    page: PageInfo | None = None,
    schemas: dict[str, Schema] | None = None,
) -> list[str]:
    """该页裸一次性事实清单（喂 `--write` 前置校验；只读不写树）。

    **与门同一支取数口径（席 S83＝P-S70-2 根修）**：人写区（`human_lines`）之外，
    还数 `auto_zone_contents` 那些**未被当场复现**的机器段——旧版只数人写区，
    「事实藏进 AUTO 段」在前置里被数成 0 行即放行（一对注释买断前置，与 G-T3 面 K-1
    抓的同一类洗白）。词表 None／空 ⇒ 抛 `FactVocabUnavailable`（前置拒写，不静默降级）。
    单参调用（只给 `text`）与旧版同形，既有消费方（`tests/test_taxonomy_spec_gates.py`）零破坏。
    """
    import doc_fact_discipline as dfd

    if vocab is None:
        vocab = _load_fact_vocab()
    if not vocab:
        raise FactVocabUnavailable(
            "G-T3 同源词表读不到或为空：枚举那把尺子会在前置里静默失效 ⇒ 拒绝驱动"
        )
    # 席 S106 交回的 C-1（本席 ③）：把 `known_fact_keys` **真传下去**，否则 S106 的
    # 「占位符按在册参数有条件摘除」加严只活在测试里、门/前置两侧零效果。
    # 在册参数取数口唯一＝`dfd.declared_fact_keys`（只复用 @schema 解析，禁第二套表）：
    # 页带 front-matter 模板身份时直接喂 template，否则从整页原文现读；未声明/不在册
    # ⇒ 空集（正文任何占位符都按假指针点名，绝不静默退回旧无条件摘除口径）。
    template = page.fm.template if (page is not None and page.fm is not None) else None
    known_fact_keys = dfd.declared_fact_keys(text, template=template, schemas=schemas)
    hits = list(
        dfd.fact_findings(dfd.human_lines(text), vocab=vocab,
                          known_fact_keys=known_fact_keys)
    )
    for begin, inner in dfd.auto_zone_contents(text):
        if (
            begin == TPL_AUTO_BEGIN
            and page is not None
            and schemas is not None
            and _zone_matches_render(page, inner, schemas)
        ):
            continue  # 真由本写盘口生成、当场复现 ⇒ 机器所有，不计人写裸事实
        hits += dfd.fact_findings(dfd.human_lines(inner), vocab=vocab,
                                  known_fact_keys=known_fact_keys)
    return hits


def _apply_block(text: str, block: str) -> str:
    if TPL_AUTO_BEGIN in text and TPL_AUTO_END in text:
        head, rest = text.split(TPL_AUTO_BEGIN, 1)
        _, tail = rest.split(TPL_AUTO_END, 1)
        return f"{head}{block}{tail}"
    lines = text.splitlines(keepends=True)
    insert_at = len(lines)
    seen_h1 = False
    infence = False
    fm_end = 0
    if lines and lines[0].strip() == "---":
        fm_end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
    for i in range(fm_end + 1, len(lines)):
        ln = lines[i]
        if _FENCE_RE.match(ln):
            infence = not infence
        if infence:
            continue
        if ln.startswith("# "):
            seen_h1 = True
        elif i > fm_end + 1 and ln.startswith("## "):
            insert_at = i
            break
    if not seen_h1 and fm_end == 0:
        insert_at = 0
    pre = "".join(lines[:insert_at])
    if pre and not pre.endswith("\n\n"):
        pre = pre.rstrip("\n") + "\n\n" if pre.strip() else pre
        if not pre.endswith("\n\n") and pre.strip():
            pre = pre.rstrip("\n") + "\n\n"
    return pre + block + "\n\n" + "".join(lines[insert_at:])


def write_page(pg: PageInfo, schemas: dict[str, Schema]) -> bool:
    if pg.fm is None or not pg.fm.template or pg.fm.template not in schemas:
        return False
    schema = schemas[pg.fm.template]
    ctx = PageCtx(rel=pg.rel, body_no_fm=pg.text)
    values, viol = resolve_params(schema, pg.fm, ctx)
    if viol:
        return False  # 参数不合法=不许带病渲染（缺参页机器段保持原样）
    new = _apply_block(pg.text, render_page_text(schema, values))
    if new != pg.text:
        pg.path.write_text(new, encoding="utf-8", newline="\n")
        return True
    return False


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------
def _collect(root: Path | None = None) -> tuple[list[PageInfo], list[str], dict[str, Schema]]:
    schema_errors: list[str] = []
    schemas: dict[str, Schema] = {}
    for path in sorted(TEMPLATE_DIR.glob("*.md")):
        try:
            sch = parse_schema_text(
                path.read_text(encoding="utf-8", errors="replace"), path.stem
            )
        except SchemaError as exc:
            schema_errors.append(f"SCHEMA_ERROR {exc}")
            continue
        # 席 S153：自由槽资格在装载期执法（与 `load_schemas()` 同一支判据，不建第二本账）。
        # 不合格 ⇒ 记红**并且不装入**该模板：宁可让引用它的页吃 TEMPLATE_MISSING（更严），
        # 也不带着「现役规格类开自由槽」这个失格形状继续渲染/记账。
        guard = freeform_guard({path.stem: sch})
        if guard:
            schema_errors.extend(guard)
            continue
        schemas[path.stem] = sch
    # 席 S114 ④：来源在册守卫（装载期即红，不带病渲染/记账）。判据不可解析 ⇒ fail-closed。
    schema_errors.extend(_provider_source_guard(schemas))
    pages = annotate(walk_content_pages(root), schemas)
    return pages, schema_errors, schemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    flag_group = parser.add_mutually_exclusive_group()
    flag_group.add_argument("--check", action="store_true")
    flag_group.add_argument("--write", action="store_true")
    flag_group.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    pages, schema_errors, schemas = _collect()
    driven = [p for p in pages if p.fm is not None]

    if args.report:
        _, live_source = _board_live_paths()
        print(f"templates: {sorted(schemas)}（schema 错误 {len(schema_errors)}）")
        ff = sorted(t for t, s in schemas.items() if s.freeform)
        print(f"自由槽（可重复小节）已启用: {ff if ff else '无'}")
        print(f"board 生成页取数口: {live_source}")
        cats: dict[str, list[PageInfo]] = {}
        for p in pages:
            cats.setdefault(p.category, []).append(p)
        print("| 类别 | 件数 | 模板驱动 | 缺参 | 多参 | 异形 |")
        print("|---|---|---|---|---|---|")
        for cat in sorted(cats):
            rows = cats[cat]
            d = [p for p in rows if p.fm is not None and p.fm.template in schemas]
            miss = sum("MISSING_PARAM" in v for p in d for v in p.violations)
            extra = sum(
                ("EXTRA_PARAM" in v or "FM_EXTRA_KEY" in v) for p in d for v in p.violations
            )
            shape = sum(v.startswith("SECTION_") for p in d for v in p.violations)
            print(
                f"| {cat} | {len(rows)} | {len(d)} | {miss} | {extra} | {shape} |"
            )
        tot = len(pages)
        dtot = sum(1 for p in driven if p.fm and p.fm.template in schemas)
        print(f"合计: pages={tot} template-driven={dtot} 未模板驱动={tot - dtot}")
        for e in schema_errors:
            print(e)
        return 1 if schema_errors else 0

    bad = list(schema_errors)
    for p in pages:
        bad += [f"{p.rel}: {v}" for v in p.violations]

    if args.write:
        # 全轮顺序性不变量（机制注释仅此一处，别处不重复）：`compute` 的 G-T3 分流把一页裸事实
        # 记进哪一面，只由 `spec_gates_census.face_of_history_page` 一处判（席 S78 P-39：按**内容
        # 类别**、驱动与否同权，禁路径前缀码路）。一旦 --write 认下一页驱动，**只有会被分流成
        # 行级面 A（`line`）的页**——现役规格页与板块人工区——其正文裸事实才从「面 B 记 1 页」
        # 升格为「面 A 记 N 行」，会在事实清扫席（S22/S23/S24/S25）做完前顶爆面 A。故这类页挂
        # 驱动前跑「该页裸事实=0」前置（判据调 doc_fact_discipline、与 G-T3 同源）：仍有裸事实就
        # 拒绝驱动、机器段保持原样、stderr 点名页与行数。历史台账/过程件页（分流为 `page`/`skip`）
        # 其行级账恒不落面 A（S78 口径，落面 B 或只记 G-T1），历史数字不可清 ⇒ 放行挂驱动，不再
        # 套用「裸事实=0」前置（席 S105 收口 S78 交回的 P-S78-1：把页级一刀切改成按类别判）。
        # 不改面 A 上限、不删正文充数、不加豁免、不建第二套分类表（判据只复用 S78 那一支函数）。
        changed = 0
        refused: list[str] = []
        vocab = _load_fact_vocab()
        if not vocab:
            # 席 S83（P-S70-2）：词表读不到＝枚举尺子失能，**整轮拒写**（旧版静默降级继续驱动）。
            refused = [
                f"{p.rel}：FACT_VOCAB_UNAVAILABLE（G-T3 同源词表读不到或为空，前置无法判枚举）"
                for p in driven
            ]
        else:
            # 取数口唯一：分流判据直接调门那一支 `face_of_history_page`（内部即 `is_ledger_category`
            # 的同一类别集合），禁复制逻辑、禁路径前缀码路。`spec_gates_census` 反向 import 本模块，
            # 故惰性导入避免模块级环形；`face_of_history_page` 只读 `.category`/`.rel`（脚本以
            # __main__ 运行时两份模块对象的 PageInfo 不同名也不影响属性读取）。
            if str(ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(ROOT / "scripts"))
            import spec_gates_census as sgc

            for p in driven:
                # driven_non_generated=True：模拟「本页驱动后」的分流落点（我们正是在决定是否驱动）。
                if sgc.face_of_history_page(p, driven_non_generated=True) != "line":
                    # 历史台账/过程件类：驱动不顶行级面 A ⇒ 放行挂驱动（其行级账按 S78 口径走）。
                    if write_page(p, schemas):
                        changed += 1
                    continue
                # 现役规格 / 板块人工区类：照旧要求「裸事实=0 才准驱动」，一行都不放过。
                try:
                    facts = naked_fact_findings(p.text, vocab, page=p, schemas=schemas)
                except FactVocabUnavailable as exc:
                    refused.append(f"{p.rel}：{exc}")
                    continue
                if facts:
                    refused.append(f"{p.rel}：裸事实 {len(facts)} 行")
                    continue
                if write_page(p, schemas):
                    changed += 1
        print(
            f"--write 完成：更新 {changed} 页；拒绝驱动 {len(refused)} 页（现役规格裸事实未清）；"
            f"管辖页 {len(pages)}；违规 {len(bad)} 项"
        )
        for r in refused:
            print(
                "PREWRITE_NAKED_FACT 拒绝挂模板驱动（现役规格页：先清裸事实再挂驱动）：" + r,
                file=sys.stderr,
            )
        for b in bad:
            print(f"VIOLATION {b}", file=sys.stderr)
        return 1 if (bad or refused) else 0

    # 缺省与 --check 同义
    if bad:
        for b in bad:
            print(f"VIOLATION {b}", file=sys.stderr)
        print(
            f"模板体检未过：{len(bad)} 项（可修的用 python scripts/doc_template_sync.py"
            " --write；参数类须改页 front-matter）",
            file=sys.stderr,
        )
        return 1
    dtot = sum(1 for p in pages if p.fm and p.fm.template in schemas)
    print(
        f"模板机制同步正常：templates={len(schemas)}，管辖页 {len(pages)}，模板驱动 {dtot}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
