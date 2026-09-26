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
- **写盘口 fail-closed 契约（席 TX181 立，判据真身＝`write_page`；席 TX241 补 CAS 与条件回滚）**：
  写前重读盘上真实态——`before` 体检、`new` 基底与渲染用 `PageCtx.body_no_fm` 一律取自盘上态，
  **任何情况下不用调用方传入的内存副本**；盘上态≠内存态 ⇒ 抛 `PageConcurrentMutation`（点名页与两态
  sha256[:16]），一个字都不写；**紧邻落盘之前**再读一次盘上态、与本轮起点的 `_integrity_token`
  比对（TX241 L1）⇒ 不等即**弃写**并用重读到的那份盘上态**重跑渲染**（有界 `_CAS_ATTEMPTS` 次，
  超限抛 `PageConcurrentMutation`，绝不拿陈旧派生值顶掉他席提交）；写后从盘上重读再 `check_page`，
  **双向**差分——新增违规 ⇒ 回滚（TX171），违规凭空消失且可见标记份数变化不可解释 ⇒ 同样回滚
  （TX179 T4 洗白形）。**三条回滚腿一律先重读**（TX241 L0）：盘上仍是本席刚写的那份才抬回写前态，
  已是他人提交的字节 ⇒ **只放弃、不回滚**（旧写法把别人提交一起吃掉）。落盘与回滚都走
  `_atomic_write_bytes`（临时名 + `os.replace`，读者永不见半档）。
  ⚠ **残余窗口（必须与"已修"同段读）**：CAS 仍是 check-then-act——窗口从「整段渲染」缩到
  「最后一次 `read_bytes` → `os.replace`」两发系统调用之间，**①型丢更新的概率降到极低但不为零**。
  要严格归零只有 L2（**所有**写者同一把持仓锁跨读→改→写全段；现算本仓页面写者 ≥3 枚、无一持锁），
  本波未装 ⇒ 见 `SEAT-TX241.md` §5 施工单，账面不得叙述为"锁已落"。
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
import os
import re
import sys
import time
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
    """本页**真**机器段的段内文本；无成对可见标记 ⇒ None。

    TX171 根修（同族盲区之一）：旧版按裸子串 `TPL_AUTO_BEGIN in text` 认段，写在围栏里的
    示例串（教程/配方页常见）会被当成本页的机器段拿去比对 ⇒ `AUTO_DRIFT`，且当示例串先于
    真段时还会把真段整个看漏。判据改走 `_human_body_position_view` —— 与 `_human_body`
    （即 `check_sections` 那把尺）**同一次行走**，围栏外的独立标记行对才算数。
    """
    view = _human_body_position_view(text)
    if view.zone is None:
        return None
    begin, end = view.zone
    return text[begin.end:end.start]


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
# 席 TX151（2026-09-23）：seat_id 取数口扩到「与 `_provider_seat_class`/`classify`
# 完全同族」的机械可判形态——`_provider_seat_class`（:344）认四形（SEAT-/report-/
# progress- 前缀 + -log.md 后缀）即判 seat-report 类，那么这四形页都该派生得出席位号；
# 旧口只认 `^SEAT-(.+)\.md$` ⇒ 同族 report-/progress-/*-log.md 过程件全被 `no_ground_source`
# 拒挂（现算 227 枚）。**不许改页名**（重命名＝毁归属链），只放宽取数口到整族、
# 仍是「一条正则、不逐页手抄」。空主干/占位符形在 provider 层照旧抛（见下方守卫）。
_SEAT_ID_RE = re.compile(r"^(?:(?:SEAT|report|progress)-(.+)|(.+)-log)\.md$")
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
    name = _stem(ctx.rel)
    m = _SEAT_ID_RE.match(name)
    if not m:
        raise ValueError(
            "文件名不合席位族 "
            "^(?:SEAT|report|progress)-(.+)\\.md$ 或 ^(.+)-log\\.md$，"
            f"无法派生席位号：{name}"
        )
    # 前缀形命中 group(1)、-log 后缀形命中 group(2)；二者互斥（正则只走一支）。
    seat = (m.group(1) or m.group(2)).strip()
    # 席 TX151 约束②：空主干/占位符形照旧抛（不因放宽取数口而放行垃圾）——
    # 与 `_provider_filename_stem` 同一套占位符集合、判定口径一致。
    if not seat:
        raise ValueError(f"席位主干为空，无法派生席位号：{name}")
    if seat.lower() in _PLACEHOLDER_STEMS or seat in _PLACEHOLDER_STEMS_CN:
        raise ValueError(f"席位主干是占位符形 {seat!r}，拒绝用作席位号：{name}")
    return seat


def _provider_body_status(arg: str | None, ctx: PageCtx) -> str:
    m = _STATUS_LINE_RE.search(ctx.body_no_fm)
    if not m:
        raise ValueError("页体无 `Status: (STARTED|RUNNING|BLOCKED|DONE)` 行，无法派生 status")
    return m.group(1)


#: 占位符形的"作用域名"一律拒收（席 TX45 ③注毒实证：真身 `_PLACEHOLDER_LITERALS`
#: 今日不含 `"0"`，若 provider 返回 `"0"` 会绿着过 G-T4 —— 反面先例＝`ledger_events`
#: 用 `"0"` 掩盖 572 枚"压根没记账目"的页）。
_PLACEHOLDER_STEMS = frozenset({"0", "na", "n/a", "none", "null", "tbd", "todo", "-"})
#: 中文占位形（小写集合不上，单独一枚集合；真身 `_PLACEHOLDER_LITERALS` 有 `待填`
#: 但那在下游 PROVIDER_EMPTY 腿，provider 层不拦＝"0" 同款绿洞，席 TX76②点名）。
_PLACEHOLDER_STEMS_CN = frozenset({"待填", "待定", "未填", "占位", "示例"})


def _provider_filename_stem(arg: str | None, ctx: PageCtx) -> str:
    """页面作用域名：文件名主干（保大小写、不折叠分隔符）。

    一次解锁 `ledger_scope`/`brief_scope`/`guide_scope`/`convention_scope`/
    `handbook_scope`/`runbook_scope`/`spec_id` 七枚同构必填参的**来源**问题（席 TX17、
    TX19、TX20、TX13、TX21 四席独立复算同判：文件名是它们唯一 100% 可派生的真身来源）。
    ⚠ 「可派生」不等于「类内单射」——席 TX76 现算推翻本函数旧注释的那句断言：
    `ledger_scope` 池 5 键撞 23 页、`brief_scope` 池 2 键撞 4 页，且真身 G-T4 没有
    跨页唯一性腿（TX45①／TX74④）⇒ 单射问题另案（PARKED P-80），本函数不假称已解决。

    形态口径（席 TX74②/TX76①/TX88 三席独立实算同一结论：首版在此写错）：真身
    `_stem()` 返回**带 `.md`** 的文件名，而在册 60 枚已驱动页的 `*_scope` 值全部
    **去扩展名**（60/60 不等）⇒ 必须先 strip 再判，否则翻 `auto:` 当场 60 枚 `AUTO_DRIFT`。
    占位符判定同样要在 strip 之后做：`_PLACEHOLDER_STEMS` 存的是无扩展名 token，
    旧写法对任何 `X.md` 永不命中＝死代码（TX76②注毒实跑）。

    派生不出即抛 `PROVIDER_FAIL`，绝不发明值；`"0"`/`待填`/`TBD` 等占位形在 provider
    层即抛（TX45③：真身 `_PLACEHOLDER_LITERALS` 今日不含 `"0"`，不自己拦就会绿着过）。
    """
    name = _stem(ctx.rel)
    for suffix in (".md", ".markdown"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    stripped = name.strip()
    if not stripped:
        raise ValueError(f"文件名主干为空，无法派生作用域名：{ctx.rel}")
    if stripped.lower() in _PLACEHOLDER_STEMS or stripped in _PLACEHOLDER_STEMS_CN:
        raise ValueError(f"文件名主干是占位符形 {stripped!r}，拒绝用作作用域名：{ctx.rel}")
    return name


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
    # 席 TX17/TX19/TX20/TX13/TX21 四定案 → 主会话单点落地：七枚同构 `*_scope`/
    # `spec_id` 必填参的真身来源（此前 1252 枚页因无 provider 只能瞎填或不挂头）。
    "filename_stem": _provider_filename_stem,
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
    "seat_id_from_name": "page:文件名族 ^(?:SEAT|report|progress)-(.+)\\.md$ 或 ^(.+)-log\\.md$（与 seat_class 同族；空主干/占位符形必抛）",
    "body_status": "page:页体 ^Status: 行",
    "filename_stem": "page:文件名主干（_stem，保大小写；空主干与占位符形必抛）",
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


@dataclass(frozen=True)
class _ZoneMark:
    """一条**围栏外、独立成行**的机器段标记行，及其在全文里的字符区间。"""

    line: int  # `splitlines()` 口径的行号（0 起）
    start: int  # 标记文本在 `text` 中的起始偏移（不含行首空白）
    end: int  # 标记文本在 `text` 中的结束偏移（不含行尾空白）
    kind: str  # "B" = BEGIN / "E" = END


@dataclass(frozen=True)
class PositionView:
    """`_human_body` 的**带位置**形态——同一支尺，多记「哪一行才算数」的账。

    TX171 立此件的目的只有一个：机器段的「判定」与「剥除」必须出自**同一次行走**，
    否则 `extract_auto_zone`／`_apply_block` 按裸子串认段、`check_sections` 按剥围栏认段，
    写在围栏里的 `TEMPLATE-AUTO` 示例串就会被当成真段（TX163 对该页实证过 `AUTO_DRIFT`
    与「示例被 replace 撕掉」两种破坏形）。

    - `kept` 逐字节等于 `_human_body(text)`（两者由本函数同一次行走产出，长不歪）。
    - `marks` 只收**围栏外**的独立标记行；围栏内的 `TEMPLATE-AUTO` 字面量是**示例**，
      永不是段界（TX163 教义：尺外成对独立标记行才算真机器段）。
    - `zone` = 首个可见 BEGIN 与其后首个可见 END；无成对 ⇒ `None`。
    - `raw_first_line`／`raw_first_fence_open`：全文**首个裸子串标记**所在行号，与该行所属
      围栏的开启行号（不在围栏内 = −1）。这两个数只服务注入口「把示例整块留在 tail」的切点
      选择（`batch_frontmatter_convert._apply_machine_zone`），不参与任何判据。
    """

    kept: str
    marks: tuple[_ZoneMark, ...]
    zone: tuple[_ZoneMark, _ZoneMark] | None
    raw_first_line: int
    raw_first_fence_open: int


def _line_starts(text: str, lines: list[str]) -> list[int]:
    """每行首字符在全文中的偏移（`splitlines()` 丢掉行尾 `\n`，故每行 +1 还原）。"""
    starts: list[int] = []
    pos = 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    return starts


def _fence_open_of_line(lines: list[str]) -> list[int]:
    """每行所属围栏的**开启行号**（不在围栏内 = −1）。只认 `_FENCE_RE` 的开/闭交替。

    围栏开启行本身按 −1（它不是被围内容）；闭合行按其所闭合围栏的开启行号——与 TX163
    镜像在同一位置取样时的口径一致（切点要提到「整块示例」之前，就得知道那块示例从哪开）。
    """
    out: list[int] = []
    infence = False
    fence_open = -1
    for idx, ln in enumerate(lines):
        if _FENCE_RE.match(ln):
            out.append(fence_open if infence else -1)
            if infence:
                infence = False
                fence_open = -1
            else:
                infence = True
                fence_open = idx
        else:
            out.append(fence_open if infence else -1)
    return out


def _human_body_position_view(text: str) -> PositionView:
    """机器段与围栏的**唯一**一次行走（判据侧与注入口共用，禁第二把尺）。

    与 TX163 之前的 `_human_body` 相比只改一件事、且是**顺序**：先判围栏、再判段界。
    旧版把「机器段判定」排在「剥围栏」之前 ⇒ 围栏里一枚落单/成对的 `BEGIN` 字面量会把
    `in_auto` 拨起来，随后**围栏闭合行被 `in_auto` 吞掉**，`infence` 就此卡在 True，
    该示例之后的整篇人写正文从视图里消失（少几枚 H2 ⇒ 门与注入口都看不见真内容）。
    """
    lines = text.splitlines()
    starts = _line_starts(text, lines)
    body_from = 0
    if lines and lines[0].strip() == "---":
        fm_end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        body_from = fm_end + 1 if fm_end else 0
    raw = min(
        (x for x in (text.find(TPL_AUTO_BEGIN), text.find(TPL_AUTO_END)) if x != -1),
        default=-1,
    )
    raw_first_line = text.count("\n", 0, raw) if raw != -1 else -1
    fence_of = _fence_open_of_line(lines)
    kept: list[str] = []
    marks: list[_ZoneMark] = []
    infence = False
    in_auto = False
    for idx in range(body_from, len(lines)):
        ln = lines[idx]
        # ① 围栏优先（TX171 根修点）。机器段内部的围栏行不翻转视图状态——段内一切皆产物。
        if _FENCE_RE.match(ln):
            if not in_auto:
                infence = not infence
            continue
        stripped = ln.strip()
        marker = (
            TPL_AUTO_BEGIN if stripped == TPL_AUTO_BEGIN
            else (TPL_AUTO_END if stripped == TPL_AUTO_END else None)
        )
        # ② 只有**围栏外**的独立标记行才算段界；围栏内的字面量是示例文本，随 infence 一起丢弃。
        if marker is not None and not infence:
            lead = len(ln) - len(ln.lstrip())
            m_start = starts[idx] + lead
            marks.append(
                _ZoneMark(idx, m_start, m_start + len(marker),
                          "B" if marker == TPL_AUTO_BEGIN else "E")
            )
            in_auto = marker == TPL_AUTO_BEGIN
            continue
        if in_auto or infence:
            continue
        kept.append(ln)
    zone: tuple[_ZoneMark, _ZoneMark] | None = None
    begin = next((m for m in marks if m.kind == "B"), None)
    if begin is not None:
        closer = next((m for m in marks if m.kind == "E" and m.line > begin.line), None)
        if closer is not None:
            zone = (begin, closer)
    return PositionView(
        kept="\n".join(kept),
        marks=tuple(marks),
        zone=zone,
        raw_first_line=raw_first_line,
        raw_first_fence_open=fence_of[raw_first_line] if raw_first_line != -1 else -1,
    )


def _human_body(text: str) -> str:
    """剥 front-matter、剥机器段、剥围栏——与 SHAPE-STATS 测量纪律同口径。

    TX171：本函数降为 `_human_body_position_view` 的投影（一次行走、零第二尺），
    并随之修掉「机器段判定排在剥围栏之前」的顺序盲区。
    """
    return _human_body_position_view(text).kept


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
    """就地更新 / 首次注入机器段。**只认围栏外的成对可见标记**（TX171 根修）。

    旧版判据是裸子串 `TPL_AUTO_BEGIN in text and TPL_AUTO_END in text`，两处病：
    ① 围栏里的示例串（教程/配方页成对写出 `TEMPLATE-AUTO`）会被当成本页机器段，
      `split` 一撕就把**示例字节改写成渲染结果**（`--write` 对 `HEADER-RECIPE.md`
      这类页是破坏性改写，且示例先于真段时真段被看漏）；
    ② 只出现 END 在其前、BEGIN 在其后（错序形）时 `rest.split(END,1)` 直接
      `ValueError: not enough values to unpack` —— 崩在写盘口里。
    现在二者都由 `_human_body_position_view` 的 `zone` 决定：有成对可见段 ⇒ 按其字符区间
    精确替换（与旧版在合法页上逐字节同形）；无 ⇒ 走下面的插入分支。
    """
    zone = _human_body_position_view(text).zone
    if zone is not None:
        begin, end = zone
        return text[:begin.start] + block + text[end.end:]
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


class PageWriteRejected(RuntimeError):
    """写后体检不通过 ⇒ 本席已把文件回滚到写前盘上字节并拒写（TX171 fail-closed，TX181 升为双向）。

    登记成 `main --write` 的 `refused` 之外的一枚**硬失败**：`--write` 撞到它应当停手，
    而不是把被撕坏的示例正文留在树上（旧版写后零校验 ⇒ 破坏性改写只在下次 `--check` 才现形，
    而 `HEADER-RECIPE.md` 那类页的示例串已被改写字节、`AUTO_DRIFT` 只是它的影子）。

    TX181 起本异常覆盖**两条**写后拒写腿（`introduced` 装逐枚因由原文）：
    ① 新增违规（既有）；② 「违规凭空消失 + 可见标记份数变化」的洗白形（TX179 T4 一族）——
    后者在 `write_page` 里合成 `MARKER_LAUNDERING` 因由入册，不新增判据码表。

    TX241 L0：本异常不再自陈「一定已回滚」——回滚腿先重读，盘上已是他人提交时本席**只放弃不回滚**
    （抬回写前态等于吃掉别人的合法提交）。`preserved` 装的就是这一轮的真实处置，进消息原文。
    """

    def __init__(self, rel: str, introduced: list[str], *, preserved: str) -> None:
        super().__init__(
            f"WRITE_AFTER_CHECK_FAILED {rel}：写后体检不通过（{len(introduced)} 项因由），"
            f"{preserved} —— " + " | ".join(introduced)
        )
        self.rel = rel
        self.introduced = introduced
        self.preserved = preserved


class PageConcurrentMutation(RuntimeError):
    """盘上真实态与本席内存态不一致 ⇒ **不覆盖**、保留盘上态并点名两态指纹（TX181 立，A 案）。

    病根（TX179 T5 实测）：旧 `write_page` 的 `new` 与 `before` 都取自采集期的内存副本、
    落盘直盖盘上真实态 ⇒ 采集之后任何并发写者刚写的字节被静默吃掉，而写后 `check_page`
    照绿——这是数据丢失，不是误报；且与 `PageWriteRejected`/`_drive` 自陈的
    「页字节零改动可复核」正相反。

    本异常在三处抛出（TX241 起）：
    ① 写前重读盘上态 ≠ 调用方传入的内存态（页面在采集后被改动）⇒ 一个字都不写；
    ② **紧邻写入前**的 CAS 重读与本轮起点凭据不等，且重跑渲染已耗尽 ⇒ 弃写、盘上态原样；
    ③ 写后读回字节 ≠ 本席刚落盘的字节（写入窗口内被并发竞写）⇒ 走 L0 条件回滚
      （盘上仍是本席写值才回滚，否则只放弃）。
    消息点名页与两态的 `sha256[:16]`；**不**自动合并、**不**静默以内存态为准。
    CLI 侧由 `_drive()` 记成 `concurrent_rejected` + 非零退出。
    """

    def __init__(
        self, rel: str, memory_sha16: str, disk_sha16: str, *, phase: str,
        preserved: str = "拒写，盘上态原样保留",
    ) -> None:
        super().__init__(
            f"CONCURRENT_MUTATION {rel}：{phase}"
            f"（内存态 sha256[:16]={memory_sha16} ≠ 盘上态 sha256[:16]={disk_sha16}）"
            f" ⇒ {preserved}"
        )
        self.rel = rel
        self.memory_sha16 = memory_sha16
        self.disk_sha16 = disk_sha16
        self.phase = phase
        self.preserved = preserved


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


#: CAS 弃写后「用重读到的盘上态重跑渲染」的有界次数（TX241 L1 · 照 `render_ledger` 案 A 口径：
#: 不等 ⇒ 弃写重跑、超限非零退出保留盘上态）。缺省 2＝一轮真并发里最多让一次路，不空转。
_CAS_ATTEMPTS = 2


def _integrity_token_of(raw: bytes) -> tuple[int, str]:
    """盘上字节 → 完整性凭据 `(长度, sha256[:16])`——**尺子不自造**。

    唯一来源＝`scripts/shim_retirement_census.py::_integrity_token`（在册那支，与撕裂判据同源；
    TX226 §4.2 L1 明令「禁另造第二把尺」）。延迟 import 是为避开
    `shim_retirement_census → physical_placement_census → board_doc_sync` 与本模块的导入环；
    导不到 ⇒ 直接抛（fail-closed），**绝不**退化成"没有凭据也照写"。
    """
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    from shim_retirement_census import _integrity_token

    return _integrity_token(raw)


def _render_inputs_token(
    page_bytes: bytes, template_src: bytes
) -> tuple[tuple[int, str], tuple[int, str]]:
    """渲染输入的**合成凭据**：`(页面字节凭据, 模板源字节凭据)` 双联（TX261 ②·TX252 硬约束1）。

    只比页面字节挡不住「第二输入换版」（TX252 E1-2：模板在采集与落盘之间被他席改走 ⇒
    页面 CAS 全绿、盘上却是按旧模板烤的页＝真丢更新，且写后 `check_page` 吃同一份陈旧
    schema＝自洽失明）。每半尺仍走 `_integrity_token_of`（唯一真身＝
    `shim_retirement_census._integrity_token`，TX241 用例的注毒口旁路它一枚即整闸失效）。
    覆盖范围如实：本尺是「渲染的两枚直接输入」；page-provider 在渲染期旁读的文件
    （`_read_script` 等）不在本尺内——那是残余窗口的一部分，写进 `write_page` 诚实边界。
    """
    return (_integrity_token_of(page_bytes), _integrity_token_of(template_src))


def _encode_preserving_newlines(text: str, original: bytes | None) -> bytes:
    """渲染文本 → 落盘字节，**保持盘上原行尾形**（TX261 ③·TX252 硬约束2/3）。

    读侧尺子（`_page_text_from_bytes`）把 CRLF/CR 折成 LF；写侧若无条件发 LF 字节，一轮驱动
    就把一枚在盘 CRLF 页**整篇静默翻行尾**（TX252 E3-4 实测：台账那支 `_atomic_write_text`
    默认 `newline=None` 把 `a\\nb` 落成 `a\\r\\nb`；`docs/**` 抽样 200 枚里 31 枚含 CRLF）——
    内部判据全绿而哈希册／普查／纯加法自证三处同炸。契约＝「不改行尾」：
    原页含 CRLF ⇒ 发 CRLF；新建页／纯 LF 页 ⇒ 发 LF。单 `\\r` 老 Mac 形不还原（本仓无此形，
    出现再议——如实登记于此）。
    """
    if original is not None and b"\r\n" in original:
        return text.replace("\n", "\r\n").encode("utf-8")
    return text.encode("utf-8")


def fresh_template_source(template_id: str) -> tuple[bytes | None, Schema | None, str]:
    """**逐页现读**一枚模板：返回 `(源字节, 解析 Schema, 失败因由)`（TX261 ②）。

    读法与守卫和 `_collect()` 同一支尺（`errors="replace"` + 通用换行 + `parse_schema_text` +
    单模板 `freeform_guard`），不建第二装载真身。分工：`_collect()` 的批级装载继续服务采集/
    记红/报告（只读路无竞态问题）；**写侧**每轮渲染前经本函数拿盘上现值——旧形整批装载一份
    schemas 后写完全部页面都不再看模板一眼（TX252 E1-4 实锤），本函数就是那一「眼」。
    源字节交调用方进 `_render_inputs_token`。读不到／解析失败／失格 ⇒ `(bytes|None, None, 因由)`，
    调用方 fail-closed 拒写，**绝不**退回批级陈旧份。**唯一例外**（在册夹具形）：因由以
    `missing:` 起头＝该模板本无盘上件（测试合成 schema 由调用方声明交入），此时调用方以手里
    `schemas` 那份为声明输入、指纹半尺取空字节——TX241 语义逐字保持，不是旁路。
    """
    path = TEMPLATE_DIR / f"{template_id}.md"
    try:
        src = path.read_bytes()
    except FileNotFoundError:
        return None, None, f"missing:{template_id}（无盘上模板，声明输入归调用方）"
    except OSError as exc:
        return None, None, f"模板现读失败 {type(exc).__name__}: {exc}"
    try:
        sch = parse_schema_text(
            _normalize_newlines(src.decode("utf-8", errors="replace")), path.stem
        )
    except SchemaError as exc:
        return src, None, f"SCHEMA_ERROR {exc}"
    guard = freeform_guard({path.stem: sch})
    if guard:
        return src, None, "; ".join(guard)
    return src, sch, ""


#: 落盘临时件的**固定名后缀**（TX261 ④·TX252 硬约束4）：`mkstemp` 随机名在「`mkstemp` 之后、
#: `os.replace` 之前被硬杀」的崩溃路径下每轮泄一枚、且 `rglob("*.md")` 两把尺全盲（TX252 E3-3
#: 实测两枚不同名残留）。固定名 ⇒ 每个目标至多泄一枚**可预期**的 `.tx-write.tmp`，
#: 下一次写同一目标时进门口先扫走（自我回收，不需要额外清洁席认账）。
_TMP_SUFFIX = ".tx-write.tmp"
#: `os.replace` 撞「目标正被并发读者占用」时的短重试上限：Windows 上目标被以非 delete-share
#: 打开时顶替返回 `PermissionError`（TX241 自建用例实测必现，200KB 页 + 常驻读者）。读者都是
#: 毫秒级短打开，10×20ms 足够覆盖；仍失败就照抛、**绝不**降级回 truncate+write（那等于把刚
#: 堵上的半档洞重新打开）。上限本身＝TX252 硬约束④「重试设上限」，取值沿用 TX241。
_REPLACE_RETRIES = 10
_REPLACE_RETRY_SECONDS = 0.02


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """字节级原子写（TX241 L1 第三发注毒：非原子写不留半档；TX261 ④：固定临时名 + 陈旧清扫）。

    固定临时名 `<目标名>.tx-write.tmp`（同目录）→ 进门口先 `unlink(missing_ok=True)` 回收
    上一轮崩溃/被杀留下的同名陈旧件 → 写字节 + `flush` + `os.fsync` → `os.replace` 顶替。
    **按字节写**、不经过任何文本模式换行翻译（E3-4 那形翻行尾在此闸外，行尾契约见
    `_encode_preserving_newlines`）。任一步失败 ⇒ 删临时名后原样上抛，目标文件逐字节保持旧值。
    买到的是**可见性原子**（读者永不见 truncate 之后的半档）；**买不到序原子**（不丢更新），
    那一半靠 `_render_inputs_token` 的 CAS（页面+模板双凭据），两轴正交（TX226 §4.1）。
    ⚠ Windows 特有的两发残余（TX241 实测，非推测）：
    ① 顶替**进行中**，并发读者的 `open()` 可能瞬态返回 `PermissionError [Errno 13]`（内容永远
      是完整旧版或完整新版、绝不半档，但那一发 open 会失败）；读者侧要免疫须自带短重试
      （本仓门与现算都是短读，实测未受影响）；
    ② 反方向也成立：**占空比 100% 的热循环读者**（一刻不停地 open 同一页）能把 `os.replace`
      饿死到重试预算用尽 ⇒ 本口抛错、临时名回收、目标逐字节不变。勿把"原子写"叙述成无条件成功。
    ③（TX261 新增如实账）固定名让**同目标并发写者**共享一枚临时件：截断互踩的后果是
      顶替上去的字节可能混拼 ⇒ 必被写后读回腿（第五道）抓到 ⇒ 拒写/放弃，**响而不静默**；
      彻底闭窗只有 L2 共锁（本波不自装，见 `write_page` 诚实边界）。
    """
    tmp = path.parent / (path.name + _TMP_SUFFIX)
    try:
        tmp.unlink(missing_ok=True)  # 陈旧回收（TX252 E3-3 泄漏族的自我闭环）；被持有则不强拆
    except OSError:
        pass
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt + 1 == _REPLACE_RETRIES:
                    raise
                time.sleep(_REPLACE_RETRY_SECONDS)  # 让短读者先散场，再抢这一次顶替
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # 临时名已被 replace 收走或本就被删：不掩盖原始异常
        raise


def _rollback_or_abandon(path: Path, original: bytes, written: bytes) -> str:
    """L0 条件回滚（TX241；TX261 ① 把三条腿的定性**分开写明**，TX252 硬约束5）。

    旧三条回滚腿一律 `write_bytes(original)`：窗口内他席的合法提交会被整个抬回去，
    而异常文案还写着「盘上态原样保留」——在该序下为假。现在回滚前先重读盘上态：

    - 盘上 **== 本席刚落盘的字节** ⇒ 无人中途提交 ⇒ 原子回滚到写前盘上态；
    - 盘上 **!= 本席写值** ⇒ **他人已提交，本席无权覆写别人的提交** ⇒ 只放弃、不回滚，
      残页留在盘上由写后差分的下一轮 / 常驻门现形（绝不静默）。
    - 重读失败（文件被删/不可读）⇒ 同样只放弃，不猜。

    三腿分开定性（判据成立即刻的盘上态各不相同，故本函数在不同腿上的语义不同）：
    - **正向差分腿 / 反向差分腿**：判据成立即刻盘上**仍是**本席写值（读回等值在前）——
      坏页是我烤的 ⇒ 本函数重读多半等值 ⇒ 抬回写前态＝清理自己，安全（该回滚）。
    - **第五道读回腿**：判据成立即刻盘上**已不是**本席写值——那份不是我写的 ⇒
      本函数重读若仍非本席写值即只放弃+点名、**不抬**（TX242 §4.2 `rollback_clobbers`
      形由此闭合）；仅当重读证明盘上又回到本席写值（竞写为瞬态假象／同字节 ABA）才抬回
      ——该形态由在册锁 `test_readback_mismatch_rolls_back_even_when_violation_diff_would_pass`
      钉着（纯「永不回滚」会翻掉该既有断言＝动主会话独占面，故采「判据＝盘上真值」的现行形）。

    返回人话一句，进异常消息与 CLI 点名（本函数**不**抛，抛由调用方按各自判据决定）。
    """
    try:
        current = path.read_bytes()
    except OSError as exc:
        return f"未回滚（写后重读失败 {type(exc).__name__}），盘上态与本席写值已不可比"
    if current != written:
        return (
            "未回滚（盘上已是他席提交：本席若抬回写前态等于吃掉别人的合法提交，"
            "故只放弃；残页由下一轮现算与常驻门点名）"
        )
    _atomic_write_bytes(path, original)
    return "已回滚到写前盘上态"


def _normalize_newlines(text: str) -> str:
    """通用换行归一（`\\r\\n` 与单 `\\r` 都折成 `\\n`），即 `read_text(newline=None)` 的那一半。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _page_text_from_bytes(raw: bytes) -> str:
    """盘上字节 → 字符串，与 `walk_content_pages` **同一支尺**：utf-8 + errors=replace +
    通用换行归一。不同尺的比对会把手写 CRLF 的合法页误判成「盘内存不一致」而拒写。

    ⚠ 只收 bytes（TX261 ⑥）：TX253 实咬形态＝str 喂进来当场
    `AttributeError: 'str' object has no attribute 'decode'`、一次带走 12 枚写口测试；
    从此死在门口、死成点名 `TypeError`（类型一致性锁见
    `tests/test_doc_template_write_port_cas_tx261.py`）。
    """
    if isinstance(raw, str):
        raise TypeError(
            "_page_text_from_bytes 只收 bytes（盘上真实态）；str 请直走文本尺——"
            "TX253 那形 AttributeError 从此改名点名"
        )
    return _normalize_newlines(raw.decode("utf-8", errors="replace"))


def _decode_universal_newlines(raw: bytes) -> str:
    """字节 → 文本，与 `Path.read_text(encoding="utf-8")` **逐字等价**（严格 UTF-8 + 通用换行）。

    写侧（三处写口）必须用这支、而不是上面那支：坏字节要**照旧抛** `UnicodeDecodeError`
    （挂头口有 `not_utf8` 这个在册拒因桶），而采集侧的 `errors="replace"` 是有意的宽容。
    两支尺的差别只在坏字节，正常页面上逐字相同——行尾归一这一半两边共用，禁三处写口各抄一份。
    只收 bytes 的理由与 TX253 注毒同（TX261 ⑥）。
    """
    if isinstance(raw, str):
        raise TypeError(
            "_decode_universal_newlines 只收 bytes（盘上真实态）——写侧判据的输入必须是字节"
        )
    return _normalize_newlines(raw.decode("utf-8"))


def tail_append(path: Path, lines: list[str]) -> str:
    """台账尾附口的 CAS 真身（TX261 ⑦）：`OWNERSHIP.md` 那类共享尾附面的唯一正确写法。

    旧形＝各席手抄的「读 → 拼 → 整册写」（TX242 §8.4 实测它自己就是丢更新族：一次窗口内
    他席整册重写把本席尾附抹掉、且 crlf 0→2 带出整册重写痕迹）。先例取
    `dispatch_gate_ticket.append_ticket`（整册重写 + `os.replace` 原子替换）再补一条
    「写前重读比凭据」成 CAS——本函数**不重排不改写既有行**：payload＝原字节原样 + 追加块，
    非目标字节零改动（行尾形随文件现值：末行 CRLF ⇒ 追加 CRLF；LF/空文件 ⇒ LF）。

    防重（批 61 前言第 5 条「按行首 `| TX<号> |` 防重」）：行首格＝`|...|` 的第一格（非表格行
    取整行），任一重复 ⇒ **全有或全无、一枚都不写**。

    返回人话结局（`appended` / `duplicate:...` / `cas-conflict(...)` / `unreadable(...)`），
    由 CLI 点名进退出码；本波各席尾附请改走
    `python scripts/doc_template_sync.py --tail-append <路径> --append-line '<行>'`。
    """
    for _attempt in range(1, _CAS_ATTEMPTS + 1):
        try:
            raw = path.read_bytes() if path.exists() else b""
        except OSError as exc:
            return f"unreadable（尾附重读失败 {type(exc).__name__}: {exc}）"
        token = _integrity_token_of(raw)
        head_cells: list[str] = []
        for ln in _normalize_newlines(raw.decode("utf-8", errors="replace")).splitlines():
            head_cells.append(ln.split("|")[1].strip() if ln.startswith("|") and ln.count("|") >= 2 else ln)
        seen: list[str] = []
        for ln in lines:
            cell = ln.split("|")[1].strip() if ln.startswith("|") and ln.count("|") >= 2 else ln
            if cell in head_cells or cell in seen:
                return f"duplicate:行首格 {cell!r} 已在册或本批重复 ⇒ 全批一枚不写（防重＝批61前言第5条）"
            seen.append(cell)
        pad = b"" if (not raw or raw.endswith(b"\n")) else (b"\r\n" if raw.endswith(b"\r") else b"\n")
        eol = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
        payload = raw + pad + eol.join(ln.encode("utf-8") for ln in lines) + eol
        try:
            if _integrity_token_of(path.read_bytes() if path.exists() else b"") != token:
                continue  # 拼接期间有人动过整册 ⇒ 拿新那份重拼，绝不盲写
        except OSError as exc:
            return f"unreadable（尾附 CAS 重读失败 {type(exc).__name__}: {exc}）"
        _atomic_write_bytes(path, payload)
        try:
            if path.read_bytes() == payload:
                return "appended"
        except OSError:
            pass
        # 读回不等＝第五道同定性（TX261 ①）：盘上那份不是我写的 ⇒ 只放弃+点名、不回滚不覆写。
        return "cas-conflict（写后读回≠拼接结果；盘上已是他席整册 ⇒ 只放弃，不抬不回写）"
    return f"cas-conflict（重跑 {_CAS_ATTEMPTS} 次仍有他席抢先提交，本席尾附不落地）"


def _visible_marker_counts(text: str) -> tuple[int, int]:
    """**围栏外可见**的 `TEMPLATE-AUTO` BEGIN/END 独立标记行数——与判据/注入口同尺
    （`_human_body_position_view`，禁第二把尺）。写后差分只认这支：围栏里的示例字面量
    是文档不是机器段，注入使**裸**计数 1→2 属合法首挂（TX171 的 `HEADER-RECIPE` 同型正解），
    而盘上本有可见标记又叠一段＝洗白形（TX179 T4/孤儿竞写族）⇒ 必拦。"""
    marks = _human_body_position_view(text).marks
    return (
        sum(1 for m in marks if m.kind == "B"),
        sum(1 for m in marks if m.kind == "E"),
    )


def _marker_transition_explained(
    before: tuple[int, int], after: tuple[int, int]
) -> bool:
    """标记份数变化的「可解释」白名单，只有两种：
    ① 不变（就地替换机器段，或本就没动标记）；
    ② `(0,0) -> (1,1)`——**无可见标记**的页首次注入机器段（恰一枚成对标记）。
    其余一切变化（含在有可见孤儿/成对标记的页上再叠一段）都不可解释。"""
    return before == after or (before == (0, 0) and after == (1, 1))


def _introduced_by_write(before: set[str], after: set[str]) -> list[str]:
    """本次写盘**新增**的违规（写前既有债不重复计账，故判据是集合差而非"after 为空"）。

    为什么不是「after 非空即拒」：真树在册 17 项违规全挂在别席在飞的过程页上（`--check` 现值），
    那些页的 SECTION_* 债与本次注入的机器段无关；按"非空即拒"会让 `--write` 对整批在飞页
    一律罢工＝把破坏性改写换成拒绝服务，既不清债也不加判据（简报判据＝写后体检不过即回滚抛错，
    取"这次写不得让页面变差"这一支，方向只准加严、不借道缩面）。

    ⚠ 单向差分只是**下界**：它永远放行让违规「消失」的写（TX179 §4.2），故 `write_page`
    另有反向腿（vanished + 标记份数不可解释变化 ⇒ 同样回滚），两条腿合起来才是双向。
    """
    return sorted(after - before)


class _CasDiscard(Exception):
    """内部信号：CAS 重读凭据 ≠ 本轮起点凭据 ⇒ **弃写**，用重读到的盘上态重跑渲染。

    只在 `write_page` 的重试环内部流转，绝不出仓（出仓即等于把"该重试"这件事甩给调用方）。
    """

    def __init__(self, disk_sha16: str) -> None:
        super().__init__(disk_sha16)
        self.disk_sha16 = disk_sha16


def write_page(pg: PageInfo, schemas: dict[str, Schema]) -> bool:
    """驱动一页机器段，写盘口整体 fail-closed（TX181 根修 + TX241 补 CAS 与条件回滚）。

    一轮尝试（`_write_page_once`）的四道契约，全部以**盘上真实态**为唯一输入：
    ① 写前重读盘上字节、并**逐页现读本页模板**（`fresh_template_source`，TX261 ②——旧形吃
       `_collect()` 批级一份 schemas 写完全部页）取**合成完整性凭据**
       （`_render_inputs_token(页面字节, 模板源字节)`）：`before` 体检、渲染所需的
       `PageCtx.body_no_fm`、`new` 的基底与所用 schema 一律取自本轮现读，任何情况下不用
       调用方传入的内存副本（`pg.text` 只当「采集期快照」用于②的比对）；
    ② 盘上态 ≠ 内存态 ⇒ 抛 `PageConcurrentMutation`（点名页与两态 sha256[:16]），
       一个字都不写，盘上态原样保留——他席在采集后改的字节绝不许被陈旧快照吃掉（T5 病根）；
    ③ **CAS（TX241 L1·TX261 ②扩面）**：渲染做完、**紧邻落盘之前**页面与模板**各再读一次**
       并与①的合成凭据比对（每半尺的唯一真身＝`shim_retirement_census._integrity_token`）；
       任一输入不等 ⇒ 本席手里那份已经不是盘上态 ⇒ **弃写**（连临时名都不落）⇒ 本函数用
       重读到的盘上态与模板**重跑整轮渲染**，至多 `_CAS_ATTEMPTS` 次；仍不等 ⇒ 抛
       `PageConcurrentMutation`（phase 点名「CAS 弃写重跑」），盘上态是**最后那位提交者**的、
       不是本席的陈旧派生值。这一腿正是 TX213 case1（双方四道门全过、双双 `return True`）
       与 TX252 E1-2（页面 ABA + 模板换版那支**真丢更新**）的共同闭合处。
    ④ 写后校验从**盘上重读**再 `check_page`（不比内存串；所用 schema＝①现读那份，与渲染
       同刻同源，治「体检吃陈旧 schema＝自洽失明」），且**双向**差分：
       新增违规 ⇒ 回滚（TX171 既有）；违规凭空消失且可见标记份数变化不落在白名单
       {不变／(0,0)→(1,1) 首注入} ⇒ 同样回滚并合成 `MARKER_LAUNDERING` 因由（T4 病根：
       旧版单向差分让「把证据改成绿」的写永远放行）。
    另有第五道（同属④的读回腿）：写后读回字节 ≠ 本席刚落盘的字节 ⇒ `PageConcurrentMutation`。

    三处回滚腿**分开定性**（TX261 ①，判据成立即刻的盘上态不同）：
    - ④的正向/反向**差分两腿**：坏页是本席刚烤的（读回等值在前）⇒ `_rollback_or_abandon`
      抬回写前态＝清理自己，该回滚；
    - 第五道**读回腿**：判据成立即刻盘上那份**不是**本席写的 ⇒ 只放弃+点名+**不抬**，
      仅当函数内重读证明盘上又回到本席写值（瞬态假象/同字节 ABA）才抬回——该形态由在册
      tx181 锁③钉住，纯「永不回滚」会翻掉那条既有断言（断言面＝主会话独占），
      故判据取「盘上真值」这一支，语义已在 `_rollback_or_abandon` docstring 逐腿写明。
    落盘与回滚都走 `_atomic_write_bytes`（固定临时名 + `os.replace`，读者永不见半档）；
    payload 经 `_encode_preserving_newlines`——**不改行尾**是契约（TX261 ③）。

    诚实边界（不写＝按未修记账，TX226 §4.2 L1 原话）：
    - ③的 CAS 仍是 check-then-act——窗口从「整段渲染」**缩到「最后一发页面 `read_bytes` +
      一发模板现读 → `os.replace`」几发系统调用之间**，①型丢更新的概率极低但**不为零**；
      一句话口径（TX252 硬约束6，可 grep）：**比对-写入之间无持仓锁，本件只保证「不丢晚到的
      提交」，不保证「不丢早到的提交」；后者需所有写者同一把锁（现算 ≥3 枚裸写口）**；
    - 合成凭据覆盖「渲染两枚直接输入」；page-provider 在渲染期旁读的文件（`_read_script`
      等）与事实册**不在本尺内**——那一族换版仍按陈旧旁读输入烤页，残余如实登记（交回 L2 面）；
    - 页面+模板**双双**回到同字节的 ABA 判不出（TX252 E1-1：净字节差 0＝无内容可丢，放行
      是设计语义），本闸**不是**活性锁；④写后读回窗口内，「本席写值原样躺在盘上」这一判据由
      `_rollback_or_abandon` 的重读兜住，它防的是"吃掉别人"，不防"别人把本席的顶掉"
      （那一发由④的差分与下一轮现算显形）；
    - 真正把它归零只有 L2：**所有**页面写者共用一把持仓锁、持锁区间覆盖读→改→写→读回→差分→
      回滚全段。现算本仓页面写者 ≥3 枚（本件 `write_page` / `batch_frontmatter_convert` /
      `board_doc_sync`）无一持锁 ⇒ 只在本件加锁等于装饰品，故本波**不自装**，方案与写者名册
      不变量交回主会话（`SEAT-TX241.md` §5 + `SEAT-TX261.md`）。
    """
    if pg.fm is None or not pg.fm.template or pg.fm.template not in schemas:
        return False
    last_conflict: str | None = None
    for attempt in range(1, _CAS_ATTEMPTS + 1):
        try:
            return _write_page_once(pg, schemas, attempt=attempt)
        except _CasDiscard as exc:
            last_conflict = exc.disk_sha16
    raise PageConcurrentMutation(
        pg.rel,
        _sha16(pg.text.encode("utf-8")),
        last_conflict or "unreadable",
        phase=(
            f"CAS 弃写重跑渲染 {_CAS_ATTEMPTS} 次仍有其他写者抢先落盘"
            "（本席手里那份已不是盘上态 ⇒ 拒写，盘上留最后那位提交者的字节）"
        ),
    )


def _write_page_once(pg: PageInfo, schemas: dict[str, Schema], *, attempt: int) -> bool:
    """`write_page` 的**单轮**尝试：读→判据→渲染→CAS→原子写→读回→双向差分（可弃写重跑）。"""
    assert pg.fm is not None and pg.fm.template in schemas  # 调用方 write_page 已判，此处非缺省守卫
    # TX261 ②：模板「第二输入」**逐页现读**（旧形吃 `_collect()` 批级一份陈旧 schemas 写完全部页）。
    # 现读失败/失格＝批内模板被动过 ⇒ 按并发同闸弃写重跑，绝不退回批级陈旧份渲染。
    tpl_src, schema, why = fresh_template_source(pg.fm.template)
    if schema is None or tpl_src is None:
        if why.startswith("missing:") and pg.fm.template in schemas:
            # 无盘上模板的在册夹具形：声明输入＝调用方交来的那份（TX241 语义），指纹半尺＝空字节。
            schema, tpl_src = schemas[pg.fm.template], b""
        else:
            raise _CasDiscard(f"template-unreadable:{why}")
    try:
        original = pg.path.read_bytes()
    except OSError as exc:
        # 采集后页面被删/不可读：盘上态已不是那份内存副本能对上的东西 ⇒ 同②拒写口径。
        raise PageConcurrentMutation(
            pg.rel,
            _sha16(pg.text.encode("utf-8")),
            "unreadable",
            phase=f"写前重读失败（{type(exc).__name__}: {exc}）",
        ) from exc
    # TX261 ②：本轮起点凭据＝合成凭据（页面字节 + 模板源字节），尺子仍逐半走唯一真身。
    token = _render_inputs_token(original, tpl_src)
    disk_text = _page_text_from_bytes(original)
    if disk_text != pg.text:
        raise PageConcurrentMutation(
            pg.rel,
            _sha16(pg.text.encode("utf-8")),
            _sha16(original),
            phase=(
                "页面在采集后被其他写者改动（盘上态≠本席内存态）"
                + (
                    f"；本轮此前已因写前 CAS 弃写 {attempt - 1} 次 ⇒ 与写后读回不等同属"
                    "「窗口内被并发竞写」一族，两发窗口拦的是同一件事，一律拒写、不碰盘"
                    if attempt > 1
                    else ""
                )
            ),
        )
    fm = parse_front_matter(disk_text)
    if fm is None or not fm.template or fm.template not in schemas:
        return False  # 双保险：等值门前这不可达；真不可达了也绝不带病渲染
    ctx = PageCtx(rel=pg.rel, body_no_fm=disk_text)
    values, viol = resolve_params(schema, fm, ctx)
    if viol:
        return False  # 参数不合法=不许带病渲染（缺参页机器段保持原样）
    new = _apply_block(disk_text, render_page_text(schema, values))
    if new == disk_text:
        return False
    # ---- TX241 L1 + TX261 ②：紧邻写入前的 CAS 重读——**页面与模板各现读一次、比对合成凭据**
    #      （窗口＝这一发页面 read_bytes + 一发模板现读 → 下面那一发 os.replace；
    #      「第二输入换版」＝TX252 E1-2 真丢更新那形，从此在 CAS 上必拦）
    try:
        pre_write = pg.path.read_bytes()
    except OSError as exc:
        raise PageConcurrentMutation(
            pg.rel,
            _sha16(pg.text.encode("utf-8")),
            "unreadable",
            phase=f"CAS 写前重读失败（{type(exc).__name__}: {exc}）",
        ) from exc
    tpl_src2, _schema2, why2 = fresh_template_source(pg.fm.template)
    if tpl_src2 is None and not why2.startswith("missing:"):
        raise _CasDiscard(_sha16(pre_write))  # 「第二输入」中途失守＝输入不齐 ⇒ 弃写重跑，不带病落盘
    if _render_inputs_token(
        pre_write, tpl_src2 if tpl_src2 is not None else b""
    ) != token:
        raise _CasDiscard(_sha16(pre_write))
    before = set(check_page(schema, disk_text, fm, ctx))
    before_marks = _visible_marker_counts(disk_text)
    # TX261 ③：payload 行尾形随盘上原页（CRLF 页不被一轮驱动整篇翻成 LF；契约见
    # `_encode_preserving_newlines` docstring）。
    written = _encode_preserving_newlines(new, original)
    _atomic_write_bytes(pg.path, written)
    after_bytes = pg.path.read_bytes()
    if after_bytes != written:
        # 第五道·读回腿（TX261 ①分开定性）：此刻盘上≠本席写值——那份不是我写的 ⇒
        # `_rollback_or_abandon` 只在重读证明盘上**又**回到本席写值（瞬态/同字节 ABA）时才抬回，
        # 真被他席占据 ⇒ 只放弃+点名、不抬（TX242 §4.2 `rollback_clobbers` 形的闭合点）。
        preserved = _rollback_or_abandon(pg.path, original, written)
        raise PageConcurrentMutation(
            pg.rel,
            _sha16(written),
            _sha16(after_bytes),
            phase=f"写后读回字节≠本席落盘字节（写入窗口内被并发竞写；{preserved}）",
            preserved=preserved,
        )
    after_text = _page_text_from_bytes(after_bytes)
    fm_after = parse_front_matter(after_text)
    if fm_after is None:
        after = {"HEADER_UNPARABLE 写后 front-matter 不被真身解析器认可"}
    else:
        after = set(
            check_page(
                schema, after_text, fm_after,
                PageCtx(rel=pg.rel, body_no_fm=after_text),
            )
        )
    introduced = _introduced_by_write(before, after)
    if introduced:
        preserved = _rollback_or_abandon(pg.path, original, written)  # L0 条件回滚（正向腿）
        raise PageWriteRejected(pg.rel, introduced, preserved=preserved)
    vanished = sorted(before - after)
    after_marks = _visible_marker_counts(after_text)
    if vanished and not _marker_transition_explained(before_marks, after_marks):
        # 反向腿：让违规「消失」的写只有标记结构可解释时才可信。
        preserved = _rollback_or_abandon(pg.path, original, written)  # L0 条件回滚（反向腿）
        raise PageWriteRejected(
            pg.rel,
            [
                (
                    f"MARKER_LAUNDERING 违规凭空消失且可见标记份数变化："
                    f"消失={vanished} 标记(B,E) {before_marks}->{after_marks}"
                    "（唯一可解释形态：标记结构不变，或无标记页首注入 (0,0)->(1,1)）"
                )
            ],
            preserved=preserved,
        )
    return True


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
    flag_group.add_argument("--tail-append", metavar="PATH",
                            help="台账尾附口（TX261 ⑦·CAS+原子+防重），与 --append-line 连用")
    parser.add_argument("--append-line", action="append", default=[], metavar="LINE",
                        help="要尾附的行（可多次）；仅与 --tail-append 连用")
    args = parser.parse_args(argv)

    if args.tail_append:
        # 纯尾附路：不采集、不驱动，写面只有那一个台账文件（OWNERSHIP 那类共享尾附的在册正解）。
        if not args.append_line:
            print("TAIL-APPEND 需要至少一枚 --append-line", file=sys.stderr)
            return 2
        outcome = tail_append(Path(args.tail_append), list(args.append_line))
        print(f"TAIL-APPEND {args.tail_append}: {outcome}")
        return 0 if outcome == "appended" else 1

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
        rolled_back: list[str] = []  # 写后体检拒写（TX171；TX261 ①）：抬回写前态还是只放弃，
        #                             由 `_rollback_or_abandon` 的回滚前重读定夺、逐页进点名原文
        concurrent_rejected: list[str] = []  # 并发拒写（TX181）：盘上态从未被本席触碰、或按腿处置

        def _drive(p: PageInfo) -> bool:
            """`write_page` 的 CLI 包装：拒写异常 ⇒ 记账 + 非零退出，绝不当已更新。

            不吞判据：`write_page` 的两类拒写都保证「本轮不得把陈旧派生值留在盘上」——
            `PageConcurrentMutation`（TX181/TX241）要么一个字都没写、要么走 L0 条件回滚；
            `PageWriteRejected`（TX171）同理。**回滚是有条件的**（TX241 L0）：盘上仍是本席
            写值才抬回写前态，已被他席提交 ⇒ 只放弃不回滚，具体处置在 `exc.preserved` 里
            逐页点名并跟着 stderr 一起出（旧文案一律自称「已回滚」，在他席提交的序下为假）。
            本处只把「抛错」翻成 stderr 点名 + `EXIT 1`（`rolled_back` /
            `concurrent_rejected` 计入返回值判据）。
            """
            try:
                return write_page(p, schemas)
            except PageWriteRejected as exc:
                rolled_back.append(f"{exc.rel}：{exc.introduced}｜{exc.preserved}")
                return False
            except PageConcurrentMutation as exc:
                concurrent_rejected.append(str(exc))
                return False
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
                # 席 S201（裁定 3.A）：这里问的是「**假如**挂上驱动，这页该按哪面清零」——
                # 记账判据 `face_of_history_page` 已改为只看路径/登记，不再接受「驱动与否」当输入，
                # 故前置换用同一支桶表派生的 `face_if_migrated`（现役对外类别⇒恒 line：
                # 挂驱动前必须先把裸事实清到零，S105/S78 原语义一字不松）。
                if sgc.face_if_migrated(p) != "line":
                    # 历史台账/过程件类：驱动不顶行级面 A ⇒ 放行挂驱动（其行级账按 S78 口径走）。
                    if _drive(p):
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
                if _drive(p):
                    changed += 1
        print(
            f"--write 完成：更新 {changed} 页；拒绝驱动 {len(refused)} 页（现役规格裸事实未清）；"
            f"写后体检拒写 {len(rolled_back)} 页（回滚或只放弃，逐页点名见 stderr——TX261 ① 不写「已回滚」）；"
            f"并发拒写 {len(concurrent_rejected)} 页（盘上态保留/按腿处置）；"
            f"管辖页 {len(pages)}；违规 {len(bad)} 项"
        )
        for r in refused:
            print(
                "PREWRITE_NAKED_FACT 拒绝挂模板驱动（现役规格页：先清裸事实再挂驱动）：" + r,
                file=sys.stderr,
            )
        for r in rolled_back:
            print("WRITE_AFTER_CHECK_FAILED 写后体检不通过、拒写（回滚与否逐页点名）：" + r,
                  file=sys.stderr)
        for r in concurrent_rejected:
            print("CONCURRENT_MUTATION 盘上态与本席内存态不一致、拒写保盘：" + r,
                  file=sys.stderr)
        for b in bad:
            print(f"VIOLATION {b}", file=sys.stderr)
        return 1 if (bad or refused or rolled_back or concurrent_rejected) else 0

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
