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
import hashlib
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

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
    sections: tuple[Section, ...] = ()
    params: list[Param] = []
    for raw in block.splitlines():
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
    return Schema(template_id, sections, tuple(params), zone.strip())


def extract_auto_zone(text: str) -> str | None:
    if TPL_AUTO_BEGIN not in text or TPL_AUTO_END not in text:
        return None
    return text.split(TPL_AUTO_BEGIN, 1)[1].split(TPL_AUTO_END, 1)[0]


def load_schemas() -> dict[str, Schema]:
    out: dict[str, Schema] = {}
    for path in sorted(TEMPLATE_DIR.glob("*.md")):
        out[path.stem] = parse_schema_text(
            path.read_text(encoding="utf-8", errors="replace"), path.stem
        )
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


PROVIDERS: dict[str, Callable[[str | None, PageCtx], str]] = {
    "seat_class": _provider_seat_class,
    "page_stat": _provider_page_stat,
}

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
def _match_slot(schema: Schema, heading: str) -> int | None:
    for i, sec in enumerate(schema.sections):
        if heading == sec.name or heading.startswith(
            (sec.name + "（", sec.name + "(")
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


def check_sections(schema: Schema, text: str) -> list[str]:
    viol: list[str] = []
    heads = [m.group(1) for m in _H2_RE.finditer(_human_body(text))]
    seen_idx: list[int] = []
    hit_slots: set[int] = set()
    for h in heads:
        i = _match_slot(schema, h)
        if i is None:
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

    深度口径按 CENSUS：`docs/boards/README.md` 与 `docs/boards/BNN/README.md`＝board-l1，
    `docs/boards/BNN/<l2>/README.md`＝board-l2，`docs/boards/BNN/<l2>/<l3>.md`＝board-l3。
    （2026-09-22 席 T-GATES 修正：本函数旧版把 l1 记成 l2、把 l2/l3 全塌成 l3，
    与 CENSUS 三本账 11/57/157 不符 ⇒ 板块页 canon 分派跟着错位。）
    """
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith(".superpowers/"):
        return "seat-report" if _SEAT_NAME_RE.search(name) else "sdd-ledger"
    if rel == "AGENTS.md":
        return "root-rules"
    if rel.startswith("docs/templates/"):
        return "template-source"
    if rel.startswith("docs/boards/"):
        if "_meta/" in rel or name == "_conventions.md":
            return "board-meta"
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
    if base == ROOT:  # 根散件只枚举字面（GATE-PLAN §三：根 md 枚举字面）
        surfaces += [
            p for p in (base / "AGENTS.md", base / "COMMANDS.md") if p.is_file()
        ]
        surfaces += sorted(base.glob("HANDOFF-*.md")) + sorted(base.glob("HANDOVER-*.md"))
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
            schemas[path.stem] = parse_schema_text(
                path.read_text(encoding="utf-8", errors="replace"), path.stem
            )
        except SchemaError as exc:
            schema_errors.append(f"SCHEMA_ERROR {exc}")
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
        changed = 0
        for p in driven:
            if write_page(p, schemas):
                changed += 1
        print(f"--write 完成：更新 {changed} 页；管辖页 {len(pages)}；违规 {len(bad)} 项")
        for b in bad:
            print(f"VIOLATION {b}", file=sys.stderr)
        return 1 if bad else 0

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
