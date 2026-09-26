"""批量 front-matter 挂头脚本（席 S256，2026-09-23，规格统一波第卅八批）。

一句话：给「无头内容页」按在册模板挂 `template:`/`params:` 头 + 注入 `TEMPLATE-AUTO`
机器段，但**挂头前逐枚过真身判据演算**——净效应若会把 G-T1 的红搬成 G-T4（参数）
或 G-T2（章节）的红，**拒绝写入并点名**（简报硬闸：防「移红」被静默接受）。

口径纪律（禁第二把尺）：
- 分类/模板映射/装载 = `doc_template_sync.classify/load_schemas` 与
  `spec_gates_census.registered_template`（注册表唯一真身，见 `doc_templates.py`）。
- 参数求解与取值域 = `doc_template_sync.resolve_params`（G-T4 判据同一入口）。
- 章节形状 = `doc_template_sync.check_sections`（G-T2 对模板页执法的同一支函数）。
- 机器段注入 = 注入形走 `doc_template_sync._apply_block` + `render_page_text`
  （唯一写盘口形状）；**放置决策**（TX163 根修）经 `_apply_machine_zone` 包一层：
  围栏/行内码里的 TEMPLATE-AUTO 示例串按 `_human_body` 同一支尺剥除后再判「真机器段在场」，
  劫持形态下机器段只落在首个示例串之前——判据仍零自造，镜像带运行时逐字节自证。
- 挂头后的整页自检 = `doc_template_sync.check_page`（与常驻门逐码同源）。
- literal 参的「页面派生」只复用真身 page-provider 的同一支正则族
  （`_provider_seat_id_from_name/_provider_path_wave/_provider_body_status`），
  派生不出来 ⇒ 判「不可转」，**绝不发明值**；recipe 常量（如 `role=report`）由
  `--set key=value` 显式传入，来源在调用命令里可见可审。

用法（`--plan` 缺省即只读；批量执行权在主会话）：
    python scripts/batch_frontmatter_convert.py --plan  [--root DIR] [--only GLOB]... [--limit N] [--set k=v]...
    python scripts/batch_frontmatter_convert.py --dry-run ...   # 全判据演算，仍零写入
    python scripts/batch_frontmatter_convert.py --execute --confirm-execute [--verify-after] ...

`--verify-after`：`--execute` 完成后现算 `spec_gates_census.compute(root)` 的 `t1`，
报挂头前/后 Δ 与逐枚销籍确认。硬闸语义：任一目标挂头后 G-T4/G-T2 新增违规 ⇒
该枚拒写点名；其余文件不受牵连（逐枚独立判定）。

本席（S256）留痕：只实跑 `--plan` 与 ≤10 枚 `--dry-run`；`--execute` 的仓库面写入
未在本波发生（须待 S254/S255 判「可批量」后由主会话执行）；注毒反证只在
`%TEMP%/S256/fixture/` 合成根上跑（不触仓库）。

TX233（批 59《TX233》）留痕：`--plan`/`--dry-run` 的 REFUSE 行尾加一列**只读诊断**
（` 诊断=缺参:role`／`缺参:status`／`两者皆缺`／`缺参:a,b`），逐枚点名「本页必填字面量参缺哪几枚」。
取值走 `_derive_literal_raw`——与 `_param_lines` **同一个取值口、同一支尺**；诊断**不改判**
（桶分类只看 `evaluate` 的返回路径），`--execute` 输出与桶计数一字不变，也不借这列给 `role`
塞缺省值（派生不出仍判 `no_ground_source`）。`--dry-run` 桶计数不变 ⇒ 全量 `--plan --full` 即
给《TX223》「每页缺哪枚参」的机器输出（缺项集与桶的不变量：诊断非空 ⟺ 桶==no_ground_source）。

TX241（批 60《TX241》L0+L1）留痕：**本文件的 `--execute` 是一枚页面写口，旧形有三处洞**——
① 判据与 `final_text` 全部派生自 `evaluate` 的采集期快照，整批采集与逐页写盘之间零判据
（TX213 case1 同型：他席在窗口内提交 ⇒ 被陈旧派生值整页顶回，TX226 §3 已实跑复现）；
② 旧 `:369` 那次「写前重读」两侧不同源（比的是采集期派生文本 vs 现读）⇒ **永真**，
是「门的外观、空位的实质」；③ `Path.write_text` 是 truncate+write 非原子 ⇒ 读者可见半档。
现在：每枚走 `_commit_page`（现读→取凭据→**同一份字节上**现判现渲染→写前 CAS 重读比对凭据→
`os.replace` 原子写→读回核对→必要时条件回滚），凭据/原子写/条件回滚三件套**一律复用**
`doc_template_sync`（其真身又复用 `shim_retirement_census._integrity_token`，禁第二把尺）；
落盘前被否决的页进 `stale_refused` 并非零退出（不静默、不把红搬账）。
残余窗口（不写＝按未修记账）：CAS 仍是 check-then-act，窗口＝「最后一次 `read_bytes` →
`os.replace`」两发系统调用之间 ⇒ ①型丢更新概率极低但不为零；归零只有 L2（所有页面写者
同一把持仓锁），本波不自装、方案交回主会话（`SEAT-TX241.md` §5）。
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_template_sync as dts  # 真身判据，只 import 不修改
import spec_gates_census as sgc  # 同上；T4_CODES/registered_template/compute 同源复用

#: literal 参的页面派生表：**只包装真身 page-provider**（同一支正则、同一个抛错语义）。
_DERIVE_LITERAL: dict[str, str] = {
    "seat_id": "seat_id_from_name",
    "wave": "path_wave",
    "wave_id": "path_wave",
    "status": "body_status",
}


@dataclass
class Decision:
    rel: str
    bucket: str
    detail: str = ""
    template: str = ""
    header: str = ""
    final_text: str = ""
    #: 只读诊断列（TX233 批 59《TX233》）：本页「必填 literal 参中取不到值」的键，
    #: 由 `_format_missing` 归一成形（`缺参:role`／`缺参:status`／`两者皆缺`／`缺参:a,b`）。
    #: **纯加法、不进任何判定**——桶分类只看 `bucket`，本字段仅供 `--plan`/`--dry-run` 打印，
    #: 让 TX223 拿到「每页缺哪枚参」的机器输出（`_param_lines` 只在首个缺项早退，看不全）。
    diagnostic: str = ""
    #: 采集期那份字节的完整性凭据 `(长度, sha256[:16])`（TX241 L1）。
    #: **与 `final_text` 同源同读**——旧版的毛病正是「重读只做簿记、两侧不同源故永真」，
    #: 看着像并发门、实为空位（TX226 §3）。本字段让 `--execute` 能判「我手里这份还是不是盘上那份」。
    source_token: tuple[int, str] | None = None


def _load_schemas() -> tuple[dict[str, dts.Schema], list[str]]:
    """与 `compute()` 同一装载形状（含 freeform 资格执法），装载失败者不入表。"""
    schemas: dict[str, dts.Schema] = {}
    errs: list[str] = []
    for path in sorted(dts.TEMPLATE_DIR.glob("*.md")):
        try:
            sch = dts.parse_schema_text(
                path.read_text(encoding="utf-8", errors="replace"), path.stem
            )
        except dts.SchemaError as exc:
            errs.append(f"SCHEMA_ERROR {exc}")
            continue
        guard = dts.freeform_guard({path.stem: sch})
        if guard:
            errs.extend(guard)
            continue
        schemas[path.stem] = sch
    return schemas, errs


def _derive_literal_raw(p: dts.Param, ctx: dts.PageCtx,
                        overrides: dict[str, str]) -> tuple[str | None, str | None]:
    """单个 literal 参取值的**唯一入口**：`--set` 覆盖 ＞ 页面派生（真身 page-provider）。

    返回 `(值或 None, 派生抛错原文或 None)`；派生不出来即 `(None, 原因)` 或 `(None, None)`，
    **绝不发明值**（不给 role 兜底、不造缺省）。TX233 抽出此口只为让 `_param_lines`
    与只读诊断共用同一支尺——两处判定逐字同源，杜绝第二把尺。
    """
    raw = overrides.get(p.key)
    err: str | None = None
    if raw is None and p.key in _DERIVE_LITERAL:
        provider = dts.PROVIDERS[_DERIVE_LITERAL[p.key]]
        try:
            raw = provider(None, ctx)
        except ValueError as exc:
            err = str(exc)
    return raw, err


def _param_lines(
    schema: dts.Schema, rel: str, text: str, overrides: dict[str, str]
) -> tuple[list[str] | None, str, str]:
    """为一页规划 front-matter 参数行；返回 (行列表|None, 拒因桶, 细节)。

    - `auto:` 参：必写、且值必须逐字等于 source（`AUTO_SOURCE_MISMATCH` 的对称面）。
    - literal 参：`--set` 显式覆盖 ＞ 页面派生（真身 page-provider）；都没有 ⇒ 不可转。
    - opt 参（三枚过程件模板今日没有）：只带 `--set` 的进头，auto 型 opt 留给
      `resolve_params` 现场裁决，本席不猜。

    TX233：literal 取值改走 `_derive_literal_raw`（与只读诊断同一取值口）；本函数的
    **返回值/桶分类/逐条 detail 文案逐字不变**——只把「能否取值」的判断收成一个共用原语，
    判定与桶集合零改动（`--dry-run`/`--plan` 桶计数一字不变）。
    """
    ctx = dts.PageCtx(rel=rel, body_no_fm=text)
    lines: list[str] = []
    for p in schema.params:
        if p.source.startswith("auto:"):
            if p.required:
                lines.append(f"  {p.key}: {p.source}")
            elif p.key in overrides:
                lines.append(f"  {p.key}: {overrides[p.key]}")
            continue
        # literal：值是人手/派生给定的字面量——派生不出来就是「无真身来源」，拒。
        raw, err = _derive_literal_raw(p, ctx, overrides)
        if err is not None:  # 页面派生抛错（真身 provider 拒绝发明）
            if p.required:
                return None, "no_ground_source", f"{p.key}: {err}"
            continue
        if raw is None or raw == "":
            if p.required:
                return None, "no_ground_source", f"{p.key}（literal，无 --set 且页面派生不出）"
            continue
        lines.append(f"  {p.key}: {raw}")
    return lines, "", ""


def _missing_required_literals(
    schema: dts.Schema, rel: str, text: str, overrides: dict[str, str]
) -> list[str]:
    """只读诊断（TX233）：枚举本页「必填 literal 参中取不到值」的键，**按 schema 声明序**。

    与 `_param_lines` 共用 `_derive_literal_raw`（同一支尺），但**不在首个缺项早退**、
    **不返回 None、不改判、不给 role 塞缺省值**——只是把「每页到底缺哪几枚参」如实点数出来，
    供 `--plan`/`--dry-run` 打印（`_param_lines` 只看第一个缺项，TX223 拿不全）。
    auto 参与非必填 literal 参不在本诊断面（前者由 resolve 现场裁、后者缺了不算债）。
    """
    ctx = dts.PageCtx(rel=rel, body_no_fm=text)
    missing: list[str] = []
    for p in schema.params:
        if p.source.startswith("auto:") or not p.required:
            continue
        raw, _err = _derive_literal_raw(p, ctx, overrides)
        if raw is None or raw == "":
            missing.append(p.key)
    return missing


def _format_missing(missing: list[str]) -> str:
    """把缺项列表归一成诊断标签。三枚常用形按简报点名逐字给，其余组合如实列键（不臆造尺）。"""
    if not missing:
        return ""
    s = set(missing)
    if s == {"role"}:
        return "缺参:role"
    if s == {"status"}:
        return "缺参:status"
    if s == {"role", "status"}:
        return "两者皆缺"
    return "缺参:" + ",".join(missing)


#: TX163（批 54《TX163》）：注入口剥围栏的**唯一尺**＝ `dts._human_body`。
#: 真身 `_apply_block`/`extract_auto_zone` 按**裸子串**认机器段标记——写在围栏里的示例串、
#: 甚至散文行内码里的字面量 `<!-- TEMPLATE-AUTO:BEGIN -->` 都会被当成"已存在机器段"：
#: 示例串含成对标记时 replace 分支当场把示例撕掉；示例串先于落点时真身 `check_page`
#: 的 `extract_auto_zone` 又拿示例当段比对 ⇒ `AUTO_DRIFT`（TX154 对 HEADER-RECIPE.md 实证）。
#: `_human_body`（剥 front-matter/机器段/围栏）是判据侧唯一承认的人写视图——`check_sections`
#: 就是靠它才"看不见"这些示例串。本注入函数把**同一支尺**接到注入口，且自带运行时自证：
#: 位置镜像的保留行必须逐字节等于 `dts._human_body(text)` 的输出，不等 ⇒ 本函数失效、
#: 调用方回退旧通路——镜像绝不允许长成第二把尺。


def _human_body_position_view(text: str) -> tuple[str, list[tuple[int, str]], int, int] | None:
    """`dts._human_body` 的**带位置**镜像。返回 (保留行全文, 尺外独立标记行表 [(行号,"B"|"E")],
    首个裸子串标记所在行号, 该行所属围栏的开启行号（不在围栏内则 −1）)；
    保留行与 `dts._human_body(text)` 逐字节不等 ⇒ None（尺漂移即弃用，绝不带病裁决）。

    逐行拾取规则与 `_human_body` 一比一同序（fm 界、auto 转移、围栏翻转的先后都不改），
    只多记位置账——`_human_body` 只给人写视图，本函数回答"哪一行才算数"。
    """
    lines = text.splitlines()
    body_from = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        body_from = end + 1 if end else 0
    out: list[str] = []
    markers: list[tuple[int, str]] = []
    first_raw = min(
        x for x in (text.find(dts.TPL_AUTO_BEGIN), text.find(dts.TPL_AUTO_END)) if x != -1
    ) if (dts.TPL_AUTO_BEGIN in text or dts.TPL_AUTO_END in text) else -1
    first_raw_line = text.count("\n", 0, first_raw) if first_raw != -1 else -1
    infence = False
    in_auto = False
    fence_open = -1
    first_line_fence_open = -1
    for idx in range(body_from, len(lines)):
        ln = lines[idx]
        # ↓ 三段判定与 _human_body 逐字同序：先 auto 转移、再 in_auto 吞行、再围栏翻转。
        if ln.strip() == dts.TPL_AUTO_BEGIN:
            if not infence:
                markers.append((idx, "B"))
            if idx == first_raw_line:
                first_line_fence_open = fence_open if infence else -1
            in_auto = True
            continue
        if ln.strip() == dts.TPL_AUTO_END:
            if not infence:
                markers.append((idx, "E"))
            if idx == first_raw_line:
                first_line_fence_open = fence_open if infence else -1
            in_auto = False
            continue
        if in_auto:
            continue
        if dts._FENCE_RE.match(ln):
            if idx == first_raw_line:
                first_line_fence_open = fence_open if infence else -1
            if not infence:
                fence_open = idx
            infence = not infence
            continue
        if idx == first_raw_line:
            first_line_fence_open = fence_open if infence else -1
        if not infence:
            out.append(ln)
    kept = "\n".join(out)
    if kept != dts._human_body(text):  # 运行时自证：镜像与唯一尺必须逐字节一致
        return None
    return kept, markers, first_raw_line, first_line_fence_open


def _apply_machine_zone(text: str, block: str) -> str:
    """挂头净效应演算的注入口（TX163 根修）。放置决策见模块注记；判据零自造。

    保证的**结构不变量**：返回文本里，裸子串视图看到的第一对
    `TPL_AUTO_BEGIN … TPL_AUTO_END` 就是本次注入/更新的机器段本身——
    否则真身 `check_page` 会拿示例串当段（AUTO_DRIFT）或把示例撕掉（destructive）。
    """
    if dts.TPL_AUTO_BEGIN not in text and dts.TPL_AUTO_END not in text:
        return dts._apply_block(text, block)  # ① 裸视图零标记 ⇒ 与旧通路逐字节同形
    view = _human_body_position_view(text)
    if view is None:
        return dts._apply_block(text, block)  # ② 尺自证不过 ⇒ 退回旧通路（宁可保守不误伤）
    _kept, markers, first_line, fence_open = view
    # 「真机器段在场」＝尺外存在 独立 BEGIN 行 + 其后独立 END 行（`_human_body` 只把独立行
    # 的 TPL_AUTO_BEGIN 认作段界）。在 ⇒ 真身 replace 落的就是它，旧通路逐字节同形。
    # 「真段在场且示例串**先**于真段」的病态页属旧通路既有残余，本席只登记不扩权（报告§残余）。
    has_real_zone = False
    seen_b = False
    for _idx, kind in markers:
        if kind == "B":
            seen_b = True
        elif seen_b:
            has_real_zone = True
            break
    if has_real_zone:
        return dts._apply_block(text, block)  # ③ 真段在场 ⇒ 旧通路（replace 就地更新，不回归）
    # ④ 标记全部"尺不可见"＝围栏内示例串/行内码字面量 ⇒ 禁走裸通路（它要么撕示例、要么被
    #    示例劫持）：在切点之前注入机器段、切点之后原样回接——head 内零标记 ⇒ `_apply_block`
    #    只能走 append 分支、落点仍由真身自定；页字节零改动，纯加法。
    #    首个裸标记若在围栏内，切点提到围栏开启行，整块示例原样进 tail。
    cut = fence_open if fence_open != -1 else first_line
    keepends = text.splitlines(keepends=True)
    head = "".join(keepends[:cut])
    tail = "".join(keepends[cut:])
    return dts._apply_block(head, block) + tail


def _decode_universal_newlines(raw: bytes) -> str:
    """`path.read_text(encoding="utf-8")` 的逐字等价解码——**真身不在此，指针在此**。

    读法一改，`final_text` 就改、挂头就不再是纯加法，故本口与另两枚页面写口共用同一支
    `doc_template_sync._decode_universal_newlines`（严格 UTF-8 + 通用换行；坏字节照旧抛
    ⇒ 同一个 `not_utf8` 桶）。批 57/58 在册那条「本口写盘会整篇翻行尾」的坑照旧存在、
    照旧只登记不扩权。
    """
    return dts._decode_universal_newlines(raw)


def evaluate(rel: str, path: Path, schemas: dict[str, dts.Schema],
             overrides: dict[str, str], *, raw: bytes | None = None) -> Decision:
    """单页「挂头净效应」演算：一切判定走真身函数，本函数零自造尺。

    TX241 L1：允许调用方把**已经读到手的那份字节**交进来（`raw=`），此时判据与渲染全部
    从这份字节派生、并把它的完整性凭据记进 `Decision.source_token`——一次读、一个结论、
    一枚凭据，杜绝旧通路「`:238` 采集派生 ⇒ `:369` 另读一次只做簿记」那种两读不同源的假门。
    不交 `raw` 时行为与旧版逐字一致（自己读一次、零凭据可记）。
    """
    try:
        if raw is None:
            raw = path.read_bytes()
        text = _decode_universal_newlines(raw)
    except UnicodeDecodeError as exc:
        return Decision(rel, "not_utf8", str(exc))
    except OSError as exc:
        return Decision(rel, "read_error", str(exc))
    if dts.parse_front_matter(text) is not None:
        return Decision(rel, "already_has_header", "只挂无头页，有头页本席不碰")
    category = dts.classify(rel)
    template = sgc.registered_template(category)
    if not template:
        return Decision(rel, "category_unmapped", f"类别 {category!r} 无在册模板/不归属本腿")
    schema = schemas.get(template)
    if schema is None:
        return Decision(rel, "template_schema_load_failed", template)
    # TX233 只读诊断：走同一取值口枚举「本页必填字面量参缺哪几枚」，不参与下面的任何判定，
    # 仅挂在 Decision 上供 --plan/--dry-run 打印（convertible 者此处必为空 ⇒ 结构性同源于判定）。
    diag = _format_missing(_missing_required_literals(schema, rel, text, overrides))
    lines, bucket, detail = _param_lines(schema, rel, text, overrides)
    if lines is None:
        return Decision(rel, bucket, f"{template}: {detail}", diagnostic=diag)
    header = "---\ntemplate: " + template + "\n"
    if lines:
        header += "params:\n" + "\n".join(lines) + "\n"
    header += "---\n"
    cand = header + text
    fm = dts.parse_front_matter(cand)
    if fm is None:  # 生成物不被真身解析器认可 ⇒ 内部缺陷，绝不带病出仓
        return Decision(rel, "internal_header_unparsable", template, diagnostic=diag)
    ctx = dts.PageCtx(rel=rel, body_no_fm=cand)
    values, viol = dts.resolve_params(schema, fm, ctx)
    if viol:  # 参数面先闸（这些码全在 T4_CODES 内）
        codes = "; ".join(v.split(" ", 1)[0] for v in viol)
        return Decision(rel, "new_G-T4", f"{template}: {codes} :: " + " | ".join(viol),
                        diagnostic=diag)
    final = _apply_machine_zone(cand, dts.render_page_text(schema, values))
    fm2 = dts.parse_front_matter(final)
    full = dts.check_page(schema, final, fm2, dts.PageCtx(rel=rel, body_no_fm=final))
    t2 = [v for v in full if v.startswith("SECTION_")]
    if t2:  # 章节面后闸：挂头会把该页从「G-T2 免检」搬进「按 @schema 执法」——净新增即拒
        codes = "; ".join(v.split(" ", 1)[0] for v in t2)
        return Decision(rel, "new_G-T2", f"{template}: {codes} :: " + " | ".join(t2),
                        diagnostic=diag)
    t4 = [v for v in full if v.split(" ", 1)[0] in sgc.T4_CODES]
    if t4:
        return Decision(rel, "new_G-T4", " | ".join(t4), diagnostic=diag)
    other = [v for v in full if not v.startswith("SECTION_")]
    if other:
        # AUTO_*/FACT_LEAK 在成品页上出现 = 注入形状与写盘口不同源，按内部缺陷拒。
        return Decision(rel, "internal_post_render", " | ".join(other), diagnostic=diag)
    return Decision(rel, "convertible", category, template, header, final, diagnostic=diag,
                    source_token=dts._integrity_token_of(raw))


def collect(root: Path, scope: str, only: list[str],
            limit: int | None) -> tuple[list[tuple[str, Path]], int]:
    pages = [p for p in dts.walk_content_pages(root) if p.rel.startswith(scope)]
    out: list[tuple[str, Path]] = []
    for p in pages:
        if p.rel.startswith("docs/templates/"):
            continue  # 模板源非内容页（真身 annotate 同口径跳过）
        if only and not any(fnmatch.fnmatch(p.rel, g) for g in only):
            continue
        out.append((p.rel, p.path))
    total = len(out)
    if limit is not None:
        out = out[:limit]
    return sorted(out, key=lambda t: t[0]), total


#: CAS 弃写后重跑渲染的上限：**不另立第二本账**，真身＝`doc_template_sync._CAS_ATTEMPTS`。
_CAS_ATTEMPTS = dts._CAS_ATTEMPTS


def _commit_page(root: Path, rel: str, schemas: dict[str, dts.Schema],
                 overrides: dict[str, str]) -> tuple[str, str]:
    """挂头口的唯一提交序列（TX241 L1·第二写口）。

    形＝**现读 → 取凭据 → 就在这一份字节上判据与渲染 → 写前再读比对凭据 → 原子写 → 读回核对
    →（必要时）条件回滚**。旧通路是三处都缺的：`:238` 采集期派生 `final_text`、`:369` 那次重读
    只当「要不要记 written」的簿记（两侧不同源 ⇒ 永真＝门的外观、空位的实质）、`write_text`
    非原子（TX226 §3 与其实跑 `LOST-UPDATE-REPRODUCED`）。

    三支尺子一律复用 `doc_template_sync`（本模块本就 import 它，禁第二把尺）：
    凭据 `_integrity_token_of`（真身＝`shim_retirement_census._integrity_token`）、
    原子写 `_atomic_write_bytes`（临时名 + `os.replace`）、条件回滚 `_rollback_or_abandon`
    （先重读，盘上已是他人提交 ⇒ 只放弃、不回滚别人的合法提交）。

    **残余窗口（不写＝按未修记账）**：写前 CAS 到 `os.replace` 之间仍是 check-then-act，
    ①型丢更新概率极低但不为零；归零只有 L2「所有页面写者同一把持仓锁」，本波不自装。

    返回 `(结局, 说明)`：
    - `written`        落盘成功且读回等值；
    - `unchanged`      盘上已是目标文本（幂等命中，零写入）；
    - `refuse:<桶>`    重跑判据后本页今日不可转（典型＝他席已挂好头 ⇒ `already_has_header`）：
                       这是合法的无事可做，但**绝不静默**——点名回 `main` 计入 `stale_refused` 并非零退出；
    - `cas-conflict`   写前 CAS 或写后读回不等、重跑已耗尽 ⇒ 盘上留他席那份，本席陈旧派生值不落地；
    - `unreadable`     重读失败（被删/被占），不猜盘上态。
    """
    path = root / rel
    last_note = ""
    for _attempt in range(1, _CAS_ATTEMPTS + 1):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return "unreadable", f"写前重读失败 {type(exc).__name__}: {exc}"
        # TX261 ②：「第二输入」逐页现读——模板名由 rel 的类别**确定性派生**（不读文件），
        # 拿到名字后现读模板字节 + 解析：本轮判据/渲染/写后体检全用这份现读 schema，
        # 合成凭据把它的字节也罩进去（旧形吃 `main` 批级装载一份 schemas 写到批尾＝
        # TX252 E1-2 那支真丢更新在挂头口同样成立）。读不到/失格 ⇒ 现判拒写、不静默。
        tpl = sgc.registered_template(dts.classify(rel))
        tpl_src: bytes | None = None
        schemas_page = schemas
        if tpl:
            tpl_src, sch_fresh, why = dts.fresh_template_source(tpl)
            if sch_fresh is None and tpl_src is None and why.startswith("missing:"):
                pass  # 在册夹具形：声明输入归批级 schemas（TX241 语义），指纹半尺＝空字节
            elif sch_fresh is None or tpl_src is None:
                return "refuse:schema_fresh_load", why
            else:
                schemas_page = {**schemas, tpl: sch_fresh}
        # 三件套之一（凭据）仍经 `_integrity_token_of` 敲钟——在册 AST 锁
        # `test_later_ports_reuse_the_central_write_primitives` 点名它；TX261 ② 的合成尺
        # `_render_inputs_token` 在这一半之上再罩模板源字节。两笔调用同源同刻、尺子唯一真身。
        page_token = dts._integrity_token_of(raw)
        token = dts._render_inputs_token(raw, tpl_src if tpl_src is not None else b"")
        decision = evaluate(rel, path, schemas_page, overrides, raw=raw)
        if decision.bucket != "convertible" or decision.final_text == "":
            return f"refuse:{decision.bucket}", decision.detail
        if decision.final_text == _decode_universal_newlines(raw):
            return "unchanged", "盘上已是目标文本（幂等命中，本轮零写入）"
        try:
            current = path.read_bytes()
        except OSError as exc:
            return "unreadable", f"写前 CAS 重读失败 {type(exc).__name__}: {exc}"
        _src2, _s2, why2 = dts.fresh_template_source(tpl) if tpl else (None, None, "")
        if tpl and _src2 is None and not why2.startswith("missing:"):
            return "cas-conflict", "写前 CAS 处模板失守（第二输入不可得）⇒ 弃写不落地"
        tpl_src2 = _src2 if _src2 is not None else b""
        if dts._render_inputs_token(current, tpl_src2 if tpl_src2 is not None else b"") != token:
            last_note = (
                f"写前 CAS 不等：本轮起点凭据 页={page_token[1]} 模板={token[1][1]}"
                f" ≠ 盘上现值（页面或模板任一换版 ⇒ 他席已提交，弃写、按其字节重跑渲染）"
            )
            continue
        # TX261 ③：payload 行尾形随盘上原页（挂头是纯加法，绝不允许顺手把 CRLF 页整篇翻成 LF）。
        payload = dts._encode_preserving_newlines(decision.final_text, raw)
        dts._atomic_write_bytes(path, payload)
        back = path.read_bytes()
        if back != payload:
            # 读回腿（TX261 ①分开定性）：此刻盘上那份不是本席写的 ⇒ `_rollback_or_abandon`
            # 只在重读证明盘上仍是本席写值时才抬；真被他席占据 ⇒ 只放弃+点名、不抬。
            preserved = dts._rollback_or_abandon(path, raw, payload)
            return "cas-conflict", f"写后读回字节≠本席落盘字节；{preserved}"
        return "written", ""
    return "cas-conflict", f"重跑 {_CAS_ATTEMPTS} 次仍未决；{last_note}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="只打印将改什么（缺省，零写入）")
    mode.add_argument("--dry-run", action="store_true", help="全判据演算含硬闸，仍零写入")
    mode.add_argument("--execute", action="store_true", help="真实写入（本波仓库面未授权，见模块注记）")
    ap.add_argument("--confirm-execute", action="store_true", help="--execute 的显式防呆开关")
    ap.add_argument("--verify-after", action="store_true", help="写入后现算 compute() 报 t1 Δ")
    ap.add_argument("--root", default=str(ROOT), help="目标树根（注毒反证用 %%TEMP%% 合成根）")
    ap.add_argument("--scope", default=".superpowers/", help="管辖面前缀（真身 rel 口径）")
    ap.add_argument("--only", action="append", default=[], metavar="GLOB", help="按相对路径 glob 过滤，可多次")
    ap.add_argument("--limit", type=int, default=None, metavar="N", help="只处理前 N 枚（过滤后序）")
    ap.add_argument("--set", dest="overrides", action="append", default=[], metavar="K=V",
                    help="literal 参的 recipe 常量（可多次；进命令行、可审计）")
    ap.add_argument("--full", action="store_true", help="打印全部拒因明细（缺省每桶 3 例）")
    args = ap.parse_args(argv)
    if not (args.plan or args.dry_run or args.execute):
        args.plan = True  # 缺省即 --plan（零写入安全向）

    overrides: dict[str, str] = {}
    for item in args.overrides:
        key, _, val = item.partition("=")
        if not val:
            print(f"BAD --set {item!r}（需 key=value）", file=sys.stderr)
            return 2
        overrides[key] = val

    if args.execute and not args.confirm_execute:
        print("--execute 必须同时给 --confirm-execute（防呆：批量执行权在主会话，"
              "且须 S254/S255 判「可批量」）", file=sys.stderr)
        return 2
    if args.verify_after and not args.execute:
        print("--verify-after 只在 --execute 后有定义（无写入即无前后 Δ），忽略", file=sys.stderr)

    root = Path(args.root).resolve()
    schemas, errs = _load_schemas()
    for e in errs:
        print(f"SCHEMA-LOAD {e}")  # 与门同源的装载红，如实透传，不改判
    files, surface_total = collect(root, args.scope, args.only, args.limit)

    t1_before: list[str] = []
    if args.execute and args.verify_after:
        t1_before = [str(r) for r in sgc.compute(root)["t1"]]

    decisions = [evaluate(rel, path, schemas, overrides) for rel, path in files]
    ok = [d for d in decisions if d.bucket == "convertible"]
    bad = [d for d in decisions if d.bucket != "convertible"]

    show_headers = args.plan or args.dry_run
    for d in ok:
        print(f"CONVERTIBLE {d.rel} template={d.template}")
        if show_headers:
            for ln in d.header.rstrip("\n").splitlines():
                print(f"    | {ln}")
    buckets: dict[str, list[Decision]] = {}
    for d in bad:
        buckets.setdefault(d.bucket, []).append(d)
    show_diag = args.plan or args.dry_run  # TX233：只读诊断列仅在两种只读模式打印，--execute 零改
    for bucket in sorted(buckets):
        rows = buckets[bucket]
        print(f"REFUSE-BUCKET {bucket} × {len(rows)}")
        shown = rows if args.full else rows[:3]
        for d in shown:
            diag = f" 诊断={d.diagnostic}" if show_diag and d.diagnostic else ""
            print(f"    - {d.rel} :: {d.detail}{diag}")

    written: list[str] = []
    stale_refused: list[str] = []
    if args.execute:
        # TX241 L1：旧通路在此处「拿采集期的 `final_text` 直盖盘上态」，`:369` 那次重读只做
        # written 簿记（两侧不同源 ⇒ 永真），既没否决写入也没点名陈旧。现在每枚都走
        # `_commit_page` 的现读→现判→CAS→原子写，结局逐枚点名；**任何**没落盘的 convertible
        # 页都不静默（记进 `stale_refused`、stderr 点名、退出非零＝不搬红也不藏红）。
        for d in ok:
            outcome, note = _commit_page(root, d.rel, schemas, overrides)
            if outcome == "written":
                written.append(d.rel)
            elif outcome == "unchanged":
                continue  # 幂等命中（盘上已是目标文本）：合法零写入，不进拒因账
            else:
                stale_refused.append(f"{d.rel}：{outcome}｜{note}")

    for r in stale_refused:
        print("STALE-REFUSED 采集后可转、落盘前被 CAS/现判否决（盘上态归他席，本席不写）：" + r,
              file=sys.stderr)
    print(
        f"SUMMARY root={root} scope={args.scope} surface={surface_total} "
        f"selected={len(files)} convertible={len(ok)} refused={len(bad)} "
        f"written={len(written) if args.execute else 0} "
        f"stale_refused={len(stale_refused)} buckets="
        + str({b: len(v) for b, v in sorted(buckets.items())})
    )

    if args.execute and args.verify_after:
        t1_after = [str(r) for r in sgc.compute(root)["t1"]]
        print(f"VERIFY-AFTER t1: before={len(t1_before)} after={len(t1_after)} "
              f"delta={len(t1_after) - len(t1_before)}")
        after_rels = {r.split("#", 1)[0] for r in t1_after}
        still = sorted(rel for rel in written if rel in after_rels)
        if still:
            print("VERIFY-AFTER 未销籍（异常，须点名）:", *still, sep="\n  ")
            return 1
        print(f"VERIFY-AFTER 逐枚销籍确认：写入 {len(written)} 枚全部离开 t1（无残留）")
    # 采集期判「可转」、落盘前被现判或 CAS 否决的页 ⇒ 硬失败非零（静默跳过＝把红搬进
    # 「这页怎么没更新」这本账，撞变绿六禁第⑥条；TX226 §4.2 L2 同口径）。
    return 1 if stale_refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
