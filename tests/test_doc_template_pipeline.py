"""模板机制常驻门（席 T-TPL0，2026-09-22）。

判据真身住 `scripts/doc_template_sync.py`（模板机制单一写盘口）；本文件是它的常驻门 +
反向自证：五发注毒（缺必填参 / 多未声明参 / 章节顺序偏离 / 模板不存在 / front-matter 缺
`template:`）外加取值域、auto 手填、占位泄漏、生成页带 front-matter、schema 自身畸形各一，
每发都断言「门会红」。全部喂纯函数/内存页，唯一触真树的是终账用例（真模板可解析、
试点页 --check 零违规、扫描面地板）。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_doc_template_pipeline.py \
      -p no:cacheprovider --basetemp=<私有> -q
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "doc_template_sync", ROOT / "scripts" / "doc_template_sync.py"
)
assert SPEC and SPEC.loader
dts = importlib.util.module_from_spec(SPEC)
sys.modules["doc_template_sync"] = dts  # dataclasses 解注解需要模块在 sys.modules 内
SPEC.loader.exec_module(dts)  # type: ignore[attr-defined]

VALID_PARAMS = (
    "  seat_id: T-FIX\n"
    "  wave: 2026-09-22-taxonomy\n"
    "  status: DONE\n"
    "  role: measurement\n"
    "  report_class: auto:seat_class\n"
    "  ledger_events: auto:page_stat:ledger\n"
)


def _schema() -> dts.Schema:
    text = (ROOT / "docs" / "templates" / "seat-report.md").read_text(encoding="utf-8")
    return dts.parse_schema_text(text, "seat-report")


def _page(params_block: str, sections: list[str], tail: str = "") -> str:
    body = "---\ntemplate: seat-report\nparams:\n" + params_block + "---\n\n# Fixture\n\n"
    for s in sections:
        body += f"## {s}\n\n- 事件一\n- 事件二\n\n"
    return body + tail


def _check(page_text: str) -> list[str]:
    fm = dts.parse_front_matter(page_text)
    assert fm is not None
    ctx = dts.PageCtx(rel="sdd-fix/SEAT-FIX.md", body_no_fm=page_text)
    return dts.check_page(_schema(), page_text, fm, ctx)


def _clean_page() -> str:
    """无机器段的合规页（机器段由 --write 注入，注毒测试只判参数/章节类违规码）。"""
    return _page(VALID_PARAMS, ["交付", "自报"])


# ---------------------------------------------------------------------------
# schema 解析与自锁
# ---------------------------------------------------------------------------
def test_real_template_schema_fields() -> None:
    s = _schema()
    assert [x.name for x in s.sections] == ["任务书", "账目", "交付", "发现", "自报"]
    assert [x.name for x in s.sections if not x.optional] == ["交付", "自报"]
    keys = [p.key for p in s.params]
    assert keys == ["seat_id", "wave", "status", "role", "report_class", "ledger_events"]
    by_key = {p.key: p for p in s.params}
    assert by_key["status"].domain.startswith("enum:")
    assert by_key["report_class"].source == "auto:seat_class"
    assert "{{fact:seat_id}}" in s.render_zone


def test_schema_block_missing_is_red() -> None:
    with pytest.raises(dts.SchemaError):
        dts.parse_schema_text("# 没有 @schema 的模板\n", "ghost")


def test_schema_param_row_syntax_is_tight() -> None:
    bad = (
        "<!-- @schema:BEGIN\nsections: 交付\nparams:\n- key | text | literal\n"
        "@schema:END -->\n<!-- TEMPLATE-AUTO:BEGIN -->\nx\n<!-- TEMPLATE-AUTO:END -->\n"
    )
    with pytest.raises(dts.SchemaError):
        dts.parse_schema_text(bad, "badrow")


def test_schema_unknown_placeholder_is_red() -> None:
    bad = (
        "<!-- @schema:BEGIN\nsections: 交付\nparams:\n"
        "- seat_id | text | literal | req | nonempty\n@schema:END -->\n"
        "<!-- TEMPLATE-AUTO:BEGIN -->\n- {{fact:nope}}\n<!-- TEMPLATE-AUTO:END -->\n"
    )
    with pytest.raises(dts.SchemaError):
        dts.parse_schema_text(bad, "poisonzone")


# ---------------------------------------------------------------------------
# 五发必红注毒（任务书点名）+ 加固发
# ---------------------------------------------------------------------------
def test_poison_missing_required_param() -> None:
    page = _clean_page().replace("  status: DONE\n", "")
    codes = " ".join(_check(page))
    assert "MISSING_PARAM" in codes and "status" in codes


def test_poison_extra_undeclared_param() -> None:
    page = _page(VALID_PARAMS + "  mood: happy\n", ["交付"])
    codes = " ".join(_check(page))
    assert "EXTRA_PARAM" in codes and "mood" in codes
    assert "EXTRA_PARAM" not in " ".join(_check(_clean_page()))


def test_poison_section_order_deviation() -> None:
    # 交付(槽2) 写在 账目(槽1) 之前 ⇒ 出现顺序偏离模板声明序
    codes = " ".join(_check(_page(VALID_PARAMS, ["交付", "账目"])))
    assert "SECTION_ORDER" in codes


def test_poison_unknown_section_is_out_of_spec() -> None:
    codes = " ".join(_check(_page(VALID_PARAMS, ["交付", "关键发现"])))
    assert "SECTION_UNKNOWN" in codes
    assert "规格外" in codes


def test_poison_template_not_found() -> None:
    page = _clean_page().replace("template: seat-report", "template: no-such-template")
    pg = dts.PageInfo(rel="SEAT-X.md", path=Path("SEAT-X.md"), text=page,
                      category="seat-report")
    out = dts.annotate([pg], {"seat-report": _schema()})
    assert out[0].violations and out[0].violations[0].startswith("TEMPLATE_MISSING")


def test_poison_frontmatter_without_template_key() -> None:
    page = ("---\nparams:\n  seat_id: T-FIX\n---\n\n# X\n\n## 交付\n")
    pg = dts.PageInfo(rel="SEAT-Y.md", path=Path("SEAT-Y.md"), text=page,
                      category="seat-report")
    out = dts.annotate([pg], {"seat-report": _schema()})
    assert any(v.startswith("NO_TEMPLATE_KEY") for v in out[0].violations)


def test_poison_domain_out_of_range() -> None:
    page = _page(VALID_PARAMS.replace("status: DONE", "status: PURPLE"), ["交付"])
    assert "DOMAIN_FAIL" in " ".join(_check(page))


def test_poison_handwritten_auto_value_rejected() -> None:
    page = _page(VALID_PARAMS.replace(
        "report_class: auto:seat_class", "report_class: SEAT"), ["交付"])
    codes = " ".join(_check(page))
    assert "AUTO_SOURCE_MISMATCH" in codes


def test_poison_fact_leak_in_human_zone() -> None:
    page = _page(VALID_PARAMS, ["交付"], tail="顺手写了 {{fact:seat_id}} 在人写区\n")
    assert "FACT_LEAK" in " ".join(_check(page))


def test_generated_board_page_forbids_frontmatter() -> None:
    pg = dts.PageInfo(rel="docs/boards/B01-x/README.md", path=Path("p"),
                      text=_clean_page(), category="board-l1")
    out = dts.annotate([pg], {"seat-report": _schema()})
    assert any(v.startswith("GENERATED_WITH_FM") for v in out[0].violations)


def test_leading_thematic_break_is_not_frontmatter() -> None:
    assert dts.parse_front_matter("---\n- 列表\n- 项\n") is None
    assert dts.parse_front_matter("# 普通页\n\n---\n\n正文") is None


# ---------------------------------------------------------------------------
# 渲染字节确定性 + 写盘幂等
# ---------------------------------------------------------------------------
def test_render_is_byte_deterministic() -> None:
    s = _schema()
    fm = dts.parse_front_matter(_clean_page())
    assert fm is not None
    ctx = dts.PageCtx(rel="d/SEAT-FIX.md", body_no_fm=_clean_page())
    v1, viol = dts.resolve_params(s, fm, ctx)
    v2, _ = dts.resolve_params(s, fm, ctx)
    assert not viol
    assert v1 == v2
    h = [dts.block_sha256(s, v1), dts.block_sha256(s, v2)]
    assert h[0] == h[1]
    assert "\r" not in dts.render_page_text(s, v1)


def test_write_injects_block_and_is_idempotent(tmp_path: Path) -> None:
    page = _clean_page()
    f = tmp_path / "SEAT-FIX.md"
    f.write_text(page, encoding="utf-8", newline="\n")
    s = {"seat-report": _schema()}
    pg = dts.PageInfo(rel="SEAT-FIX.md", path=f, text=page, category="seat-report")
    pg.fm = dts.parse_front_matter(page)
    assert dts.write_page(pg, s) is True
    first = f.read_bytes()
    again = dts.PageInfo(rel="SEAT-FIX.md", path=f,
                        text=first.decode("utf-8"), category="seat-report")
    again.fm = dts.parse_front_matter(first.decode("utf-8"))
    assert dts.write_page(again, s) is False  # 幂等：第二次零改动
    assert f.read_bytes() == first
    assert b"\r\n" not in first
    # 注入后再走全判据应清零（含机器段一致性）
    assert _check(first.decode("utf-8")) == []


def test_write_keeps_human_zone_untouched(tmp_path: Path) -> None:
    page = _clean_page() + "\n人写尾注：不得被覆盖\n"
    f = tmp_path / "SEAT-K.md"
    f.write_text(page, encoding="utf-8", newline="\n")
    s = {"seat-report": _schema()}
    pg = dts.PageInfo(rel="SEAT-K.md", path=f, text=page, category="seat-report")
    pg.fm = dts.parse_front_matter(page)
    dts.write_page(pg, s)
    after = f.read_text(encoding="utf-8")
    assert "人写尾注：不得被覆盖" in after
    assert after.index("## 交付") < after.index("人写尾注")


# ---------------------------------------------------------------------------
# 真树终账（常驻门本体；试点页转换完成后必须全绿）
# ---------------------------------------------------------------------------
def test_live_tree_check_is_clean_and_surface_has_floor() -> None:
    pages, schema_errors, schemas = dts._collect()
    assert not schema_errors
    assert "seat-report" in schemas
    seat_pages = [p for p in pages if p.category == "seat-report"]
    assert len(seat_pages) >= 300, "seat-report 扫描面塌陷（CENSUS 现值 314，地板 300）"
    driven = [p for p in pages if p.fm is not None and p.fm.template in schemas]
    assert len(driven) >= 3, "试点页未接入（端到端样例丢失）"
    bad = [f"{p.rel}: {v}" for p in pages for v in p.violations]
    assert not bad, "模板体检红：\n" + "\n".join(bad)
    for p in driven:
        blob = p.path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# 席 S63（P-30）：@aliases 节名别名 + 前缀编号剥形 —— 新增用例（只加严，
# 上方既有用例与断言一字未动）。旧严判必须原样保留：真缺节/真多节/真换序/
# 同义写法伪装重复 ⇒ 一律仍红；剥形只影响认名，不触节数与节序。
# ---------------------------------------------------------------------------
def _section_codes(page: str) -> str:
    return " ".join(v for v in _check(page) if v.startswith("SECTION_"))


def test_strip_prefix_shapes_unit() -> None:
    """剥形单元账：S6 实证的六族前缀全剥、负样本一律不动、纯前缀回退原串。"""
    strip = dts._strip_section_prefix
    assert strip("一、交付") == "交付"
    assert strip("贰、纪律") == "纪律"
    assert strip("0. 五问") == "五问"
    assert strip("3.6 验收") == "验收"
    assert strip("§0 一页速览") == "一页速览"
    assert strip("（三）计划") == "计划"
    assert strip("第肆部分：落点") == "落点"
    assert strip("一、") == "一、"          # 纯前缀节名不许剥成空
    assert strip("三思而后行") == "三思而后行"  # 「三」后无分隔符不剥
    assert strip("2.5D 模型") == "2.5D 模型"   # 数字带点紧跟字母不误伤


def test_alias_slot_data_loads_from_live_tree() -> None:
    """别名数据源＝docs/templates/**：真树 seat-report 装载后逐位对齐且可回读。"""
    s = _schema()
    assert len(s.slot_aliases) == len(s.sections)
    names = [x.name for x in s.sections]
    assert "产出" in s.slot_aliases[names.index("交付")]
    assert "教训" in s.slot_aliases[names.index("自报")]
    # 别名列表外槽位 = SchemaError（typo 不许静默成死数据）
    bad = (
        "<!-- @schema:BEGIN\nsections: 交付\nparams:\n"
        "- seat_id | text | literal | req | nonempty\n"
        "@aliases: 不存在槽=甲|乙\n@schema:END -->\n"
        "<!-- TEMPLATE-AUTO:BEGIN -->\n- 壳\n<!-- TEMPLATE-AUTO:END -->\n"
    )
    with pytest.raises(dts.SchemaError):
        dts.parse_schema_text(bad, "badalias")
    # 语法畸形（缺 `=`）同样装载即红
    bad2 = bad.replace("@aliases: 不存在槽=甲|乙", "@aliases: 缺等号行")
    with pytest.raises(dts.SchemaError):
        dts.parse_schema_text(bad2, "badalias2")


def test_strip_and_alias_positive_matches() -> None:
    """正向：剥形/别名命中槽位后，节集合判定不再报表外/缺节。"""
    assert not _section_codes(_page(VALID_PARAMS, ["三、交付", "4. 自报"]))
    assert not _section_codes(_page(VALID_PARAMS, ["产出", "教训"]))
    assert not _section_codes(_page(VALID_PARAMS, ["§6 交付", "自报（收尾）"]))


def test_poison_strip_does_not_waive_missing_required() -> None:
    """真缺一节仍红：证据(6)+发现(7) 顺序合法，但必选「交付」缺席 ⇒ MISSING。"""
    codes = _section_codes(_page(VALID_PARAMS, ["一、证据", "贰、发现"]))
    assert "SECTION_MISSING" in codes and "交付" in codes


def test_poison_extra_section_still_unknown_after_strip() -> None:
    """真多一节仍红：剥形/别名都不认识「玄学环节」。"""
    codes = _section_codes(_page(VALID_PARAMS, ["交付", "自报", "玄学环节"]))
    assert "SECTION_UNKNOWN" in codes and "玄学环节" in codes


def test_poison_order_deviation_survives_alias_and_strip() -> None:
    """真换序仍红：自报(9) 写在 交付(5) 之前，无论用正名、别名还是带编号。"""
    assert "SECTION_ORDER" in _section_codes(_page(VALID_PARAMS, ["教训", "产出"]))
    assert "SECTION_ORDER" in _section_codes(_page(VALID_PARAMS, ["贰、自报", "壹、交付"]))


def test_poison_alias_disguise_duplicate_still_red() -> None:
    """同义写法伪装成「多一节」仍红：交付+产出 同槽 ⇒ DUPLICATE，一类内容一份骨架。"""
    codes = _section_codes(_page(VALID_PARAMS, ["交付", "产出", "自报"]))
    assert "SECTION_DUPLICATE" in codes
    codes2 = _section_codes(_page(VALID_PARAMS, ["1. 交付", "三、交付"]))
    assert "SECTION_DUPLICATE" in codes2


# ---------------------------------------------------------------------------
# 席 S83（2026-09-22，《S83》＋《S39》）新增用例——一件三债：board-index 类同源、
# declared_no_page 四类原子批、`--write` 前置 fail-closed。**既有断言一字未改，以下只增。**
# ---------------------------------------------------------------------------
_BOARD_INDEX_REL = "docs/boards/README.md"
_CENSUS_REL = ".superpowers/sdd/2026-09-22-taxonomy/CENSUS.md"
_RETURNED_CIDS = ("persona-inject-data", "persona-numbered", "persona-provenance", "sdd-brief")


def test_board_index_is_its_own_class_not_board_l1() -> None:
    """《S39》反向自测①：索引页被误判成 `board-l1` ⇒ 本用例红（S35 取证＝G-T2 唯一偏离件）。"""
    assert dts.classify(_BOARD_INDEX_REL) == "board-index"
    assert dts.classify("docs/boards/B10-engineering-governance/README.md") == "board-l1"
    assert dts.classify("docs/boards/B10-engineering-governance/test-gates/README.md") == "board-l2"
    assert dts.classify("docs/boards/B10-engineering-governance/test-gates/x.md") == "board-l3"
    reg = (ROOT / "scripts" / "doc_templates.py").read_text(encoding="utf-8")
    assert 'cid="board-index"' in reg, "类别未进注册表＝G-T5 会把它当自由发挥标签"
    assert 'generated_by="scripts/board_doc_sync.py:INDEX_BODY"' in reg
    # 骨架只准一个真身：另建 docs/templates/board-index.md＝第二真身＋孤儿模板双红
    assert not (ROOT / "docs" / "templates" / "board-index.md").exists()


def test_board_index_canon_is_same_source_as_generator() -> None:
    """**同源且活性**：索引页人写区的 H2 序列必须等于生成器骨架 `INDEX_BODY` 的 H2 序列。

    这条用例把「新类别 ⇒ G-T2 不再比对它」的挪账空间堵死：页侧一旦多出/改掉一节就红，
    与 `board-l1/l2/l3` 由 `L1_BODY/L2_BODY/L3_BODY` 派生 canon 完全同型（席 S78 面接
    `BOARD_CANON["board-index"] = canon_of_skeleton(bds.INDEX_BODY)` 后自动同权）。
    """
    gen = (ROOT / "scripts" / "board_doc_sync.py").read_text(encoding="utf-8")
    assert "INDEX_BODY = " in gen, "骨架常量被改名或删除＝注册表 generated_by 悬空"
    body = gen.split('INDEX_BODY = """', 1)[1].split('"""', 1)[0]
    canon = [ln[3:].strip() for ln in body.splitlines() if ln.startswith("## ")]
    page = (ROOT / _BOARD_INDEX_REL).read_text(encoding="utf-8")
    auto_end = "<!-- BOARD-AUTO:END -->"
    human = page.split(auto_end, 1)[1] if auto_end in page else page
    heads = [ln[3:].strip() for ln in human.splitlines() if ln.startswith("## ")]
    assert heads == canon, f"索引页真形与骨架分家：页={heads} 骨架={canon}"
    assert heads == ["怎么读这套文档"], "骨架被改写＝偏离页只是换了一种藏法"


def test_sdd_brief_family_is_classified_by_name() -> None:
    """任务书族落 `sdd-brief`（S73 交回的四枚之一），且席位报告/普通台账不被它抢走。"""
    assert dts.classify(".superpowers/sdd/2026-09-22-taxonomy/BRIEFS.md") == "sdd-brief"
    assert dts.classify(".superpowers/sdd/x/PLAN.md") == "sdd-brief"
    assert dts.classify(".superpowers/sdd/x/adopt-package/README.md") == "sdd-brief"
    assert dts.classify(".superpowers/sdd/x/briefs/B11-brief.md") == "sdd-brief"
    assert dts.classify(".superpowers/sdd/x/master-plan.md") == "sdd-ledger"
    assert dts.classify(".superpowers/sdd/x/SEAT-S83.md") == "seat-report"


def test_four_returned_classes_each_reach_real_pages() -> None:
    """四类**一并**落地（禁止只补几枚＝`:375` 绿 `:381` 红的挪账假推进）。"""
    cats = {p.category for p in dts.walk_content_pages()}
    missing = [cid for cid in _RETURNED_CIDS if cid not in cats]
    assert not missing, f"这几类仍接不到任何一张页：{missing}"


def test_registry_classes_are_all_projected_into_census_section_one() -> None:
    """《S39》反向自测③的席侧腿：注册表每一类都要在 `CENSUS §一` 有自己的行（原子批）。"""
    text = (ROOT / _CENSUS_REL).read_text(encoding="utf-8", errors="replace")
    sec1 = text.split("## 一、", 1)[1].split("## 二、", 1)[0]
    reg = (ROOT / "scripts" / "doc_templates.py").read_text(encoding="utf-8")
    cids = [
        ln.split('cid="', 1)[1].split('"', 1)[0]
        for ln in reg.splitlines()
        if 'cid="' in ln
    ]
    assert "board-index" in cids
    ghost = [c for c in cids if f"| {c} " not in sec1]
    assert not ghost, f"只在注册表、没进 CENSUS §一 的类（册面未同步）：{ghost}"


def test_persona_classes_classify_without_driving_r17() -> None:
    """R-17 相容：人格面**只归类、不挂机器段**——任何 persona 页出现 front-matter 即红。"""
    pages = [p for p in dts.walk_content_pages() if p.category.startswith("persona-")]
    assert len(pages) >= 4, f"人格面扫描塌陷（现算 {len(pages)} 页）"
    for p in pages:
        assert p.fm is None, f"R-17 禁人格正文注机器段：{p.rel} 不得挂 front-matter"
        assert dts.parse_front_matter(p.text) is None, f"{p.rel} 真出现模板头＝越界"
    assert {p.category for p in pages} >= set(_RETURNED_CIDS[:3]) | {"persona-knowledge"}


def test_prewrite_refuses_all_pages_when_fact_vocab_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """《S83》反向自测 b：词表读不到 ⇒ `--write` 判红拒写（旧版 `except: return set()` 静默放行）。"""
    driven = [p for p in dts.walk_content_pages() if dts.parse_front_matter(p.text) is not None]
    assert driven, "树里没有已挂头的页＝本用例空跑"
    monkeypatch.setattr(dts, "_load_fact_vocab", lambda: set())
    rc = dts.main(["--write"])
    err = capsys.readouterr().err
    assert rc != 0, "词表失能仍返回 0＝前置假绿（P-S70-2）"
    assert err.count("FACT_VOCAB_UNAVAILABLE") >= len(driven), "拒写没有逐页点名"


def test_prewrite_counts_bare_facts_hidden_inside_auto_zone() -> None:
    """《S83》反向自测 c：人写区为空、裸计数全藏在 AUTO 段 ⇒ 前置**不得**判 0 放行。"""
    vocab = dts._load_fact_vocab()
    assert vocab, "真词表取不到（本用例需要它）"
    auto = (
        f"{dts.TPL_AUTO_BEGIN}\n{dts.TPL_AUTO_NOTE}\n\n"
        "统计口径：本轮实测 812 项、上限 226 行\n"
        f"{dts.TPL_AUTO_END}\n"
    )
    fm = "---\ntemplate: seat-report\nparams:\n  seat_id: S99\n---\n\n# 标题\n\n"
    text = fm + auto
    schemas = dts.load_schemas()
    pg = dts.PageInfo(
        rel=".superpowers/sdd/x/SEAT-S99.md", path=ROOT, text=text,
        fm=dts.parse_front_matter(text),
    )
    assert not dts.naked_fact_findings(fm, vocab, page=pg, schemas=schemas), "对照：无人写事实"
    hits = dts.naked_fact_findings(text, vocab, page=pg, schemas=schemas)
    assert hits, "机器段内裸事实被判 0＝一对注释买断前置（本席根修的那一半）"


# ---------------------------------------------------------------------------
# 席 S98（2026-09-22，《S98》／P-51）：`@aliases` 装载期**单射守卫** —— 只新增用例，
# 上方既有断言一字未动。守卫点：一枚别名串在同一模板内命中 >1 槽位 ⇒ SchemaError，
# 报错点名两侧槽位与模板行号（与 S63「别名指向未在册槽位即红」同一处、同一条码路）。
# 危害形态：`_match_slot` 第三级按声明序「先命中即返回」⇒ 跨槽别名＝实现替内容择一，
# 一页真·distinct 节被静默记成另一槽（＝缩小扫描面同型，S81 现跑抓到）。
# ---------------------------------------------------------------------------
def _alias_schema_text(rows: list[str], sections: str = "账目 | 卫生?") -> str:
    """内存模板（不落源码树）：块首行即 `@schema:BEGIN` ⇒ 别名行号 = 5 起。"""
    return (
        "<!-- @schema:BEGIN\n"
        f"sections: {sections}\n"
        "params:\n"
        "- seat_id | text | literal | req | nonempty\n"
        + "".join(f"{r}\n" for r in rows)
        + "@schema:END -->\n"
        "<!-- TEMPLATE-AUTO:BEGIN -->\n- 壳\n<!-- TEMPLATE-AUTO:END -->\n"
    )


def test_live_tree_alias_tables_are_injective() -> None:
    """现状账：真树每份模板的别名集必须两两不相交（守卫落地后由装载期兜住，此处再立一枚独立锁）。"""
    schemas = dts.load_schemas()
    assert schemas, "真树模板取不到＝空跑"
    for tid, sch in sorted(schemas.items()):
        pairs = [
            (a.name, b.name)
            for i, a in enumerate(sch.sections)
            for j, b in enumerate(sch.sections)
            if i < j and sch.slot_aliases[i] & sch.slot_aliases[j]
        ]
        assert not pairs, f"{tid}: @aliases 跨槽非单射，冲突槽位对 {pairs}"


def test_poison_cross_slot_alias_is_red_and_names_both_slots_and_lines() -> None:
    """注毒①：新造一枚跨槽别名 ⇒ 装载必红，且点名两个槽位与两处模板行号。"""
    bad = _alias_schema_text(["@aliases: 账目=账目|清单", "@aliases: 卫生=卫生|清单"])
    with pytest.raises(dts.SchemaError) as exc:
        dts.parse_schema_text(bad, "poisontpl")
    msg = str(exc.value)
    assert "清单" in msg and "账目" in msg and "卫生" in msg, f"报错未点名冲突双方：{msg}"
    assert "第 5 行" in msg and "第 6 行" in msg, f"报错未点名模板行号：{msg}"


def test_poison_ambiguous_page_is_green_before_and_red_after() -> None:
    """主证据（S81 危害样本）：同一枚页，改前判绿（假绿实锤）／消歧到另一侧后判红。

    页 `## 清单` 的真实语义是「卫生自查清单」，它**没有**必填的账目节。
    - 改前形态＝今天的有效行为（`_match_slot` 先命中即返回，`清单` 实际被记成 账目）⇒ 全绿；
    - 装载守卫：歧义两侧同写 `清单` ⇒ 当场 SchemaError（见上一枚）；
    - 消歧为「`清单` 只属 卫生」⇒ 该页不再被白记一个账目节 ⇒ SECTION_MISSING 账目 判红。
    """
    pre = dts.parse_schema_text(
        _alias_schema_text(["@aliases: 账目=账目|清单"]), "amb-pre"
    )
    post = dts.parse_schema_text(
        _alias_schema_text(["@aliases: 卫生=卫生|清单"]), "amb-post"
    )
    page = "# 台账\n\n## 清单\n\n- 卫生自查：源码树缓存 0 枚\n"
    assert dts.check_sections(pre, page) == [], "改前对照：这枚页今天在真机制下就是绿"
    codes = " ".join(dts.check_sections(post, page))
    assert "SECTION_MISSING" in codes and "账目" in codes, f"消歧后未抓到被吞掉的 distinct 节：{codes}"


def test_single_slot_alias_still_loads_and_matches() -> None:
    """正向对照（还原必绿）：别名只挂一槽时装载正常、认名照常命中，守卫不误伤既有形状。"""
    ok = dts.parse_schema_text(
        _alias_schema_text(
            ["@aliases: 账目=账目|流水|清单", "@aliases: 卫生=卫生|树卫生自查"]
        ),
        "oktpl",
    )
    assert dts._match_slot(ok, "清单") == 0
    assert dts._match_slot(ok, "一、树卫生自查") == 1
    # 别名等于**本槽**正名（`账目=账目|...`）是既有合法形状，不得被判跨槽
    assert dts._match_slot(ok, "账目") == 0


# ---------------------------------------------------------------------------
# 席 S105（2026-09-22，《S105》／收口 S78 交回的 P-S78-1）：`--write` 前置从「页级裸事实
# 一律拒驱动」改成**按类别判**——复用 `spec_gates_census.face_of_history_page` 这一支分流
# （驱动后其裸事实会不会顶进行级面 A）：现役规格/板块人工区（`line`）照旧要求「裸事实=0 才准
# 驱动」，历史台账/过程件类（`page`/`skip`）其账恒不落面 A ⇒ 放行挂驱动。**既有断言一字未改，
# 以下只增。** 四发注毒全部走内存页 + tmp_path 落点（`--write` 只写临时副本，绝不碰真树）。
# ---------------------------------------------------------------------------
_MINI_SCHEMA_TEXT = (
    "<!-- @schema:BEGIN\nsections: 正文\nparams:\n"
    "- title | text | literal | req | nonempty\n"
    "@schema:END -->\n"
    "<!-- TEMPLATE-AUTO:BEGIN -->\n标题：{{fact:title}}\n<!-- TEMPLATE-AUTO:END -->\n"
)


def _sgc():  # 门那一支分流函数（判据同源，禁第二套分类）
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import spec_gates_census

    return spec_gates_census


def _mini_schema() -> dts.Schema:
    return dts.parse_schema_text(_MINI_SCHEMA_TEXT, "mini")


def _fact_page_body() -> str:
    # 人写区含一枚裸事实（"本轮实测 812 项"），与既有 auto-zone 注毒用例同形
    return (
        "---\ntemplate: mini\nparams:\n  title: T\n---\n\n# T\n\n"
        "## 正文\n\n本轮实测 812 项\n"
    )


def _drive_page(tmp_path: Path, rel: str, category: str):
    body = _fact_page_body()
    f = tmp_path / Path(rel).name
    f.write_text(body, encoding="utf-8", newline="\n")
    pg = dts.PageInfo(rel=rel, path=f, text=body, category=category)
    pg.fm = dts.parse_front_matter(body)
    return pg, f


def test_write_poison_active_spec_bare_fact_still_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """注毒 a：现役规格页留一行裸事实 ⇒ `--write` 必拒、机器段不注入（`line` 面一行不放过）。"""
    pg, f = _drive_page(tmp_path, "docs/design/thing.md", "design-spec")
    sch = _mini_schema()
    monkeypatch.setattr(dts, "_collect", lambda root=None: ([pg], [], {"mini": sch}))
    monkeypatch.setattr(dts, "_load_fact_vocab", lambda: {"聊天"})
    rc = dts.main(["--write"])
    err = capsys.readouterr().err
    assert _sgc().face_of_history_page(pg, driven_non_generated=True) == "line"
    assert rc != 0, "现役规格页带裸事实仍返回 0＝前置被绕过"
    assert "PREWRITE_NAKED_FACT" in err and pg.rel in err
    assert dts.TPL_AUTO_BEGIN not in f.read_text(encoding="utf-8"), "被拒页却写进了机器段"


def test_write_historical_ledger_bare_fact_is_driven(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """注毒 b：历史台账页同样一行裸事实 ⇒ 放行挂驱动（机器段注入），其账记面 B 不落面 A。"""
    pg, f = _drive_page(tmp_path, "docs/HANDBOOK.md", "handbook")
    sch = _mini_schema()
    monkeypatch.setattr(dts, "_collect", lambda root=None: ([pg], [], {"mini": sch}))
    monkeypatch.setattr(dts, "_load_fact_vocab", lambda: {"聊天"})
    rc = dts.main(["--write"])
    err = capsys.readouterr().err
    sgc = _sgc()
    assert sgc.is_ledger_category("handbook") is True
    assert sgc.face_of_history_page(pg, driven_non_generated=True) == "page"  # 记面 B
    assert "PREWRITE_NAKED_FACT" not in err, "历史台账页仍被一刀切拒驱动＝本席根修未生效"
    assert dts.TPL_AUTO_BEGIN in f.read_text(encoding="utf-8"), "放行后机器段未注入"
    assert rc == 0
    # 裸事实未被清零、也没被塞进面 A：账仍在（不降判据、不发明数据）
    assert dts.naked_fact_findings(
        f.read_text(encoding="utf-8"), {"聊天"}, page=None, schemas={"mini": sch}
    )


def test_relabelling_active_page_as_history_is_caught_by_crosscheck() -> None:
    """注毒 c：把现役页改标成历史台账以躲尺 ⇒ 前置会放行，但分类↔front-matter 交叉核验必红。

    复用的是 S78 那支 `category_mismatch`（页声明的 `template` 必须等于其**路径派生类别**的
    在册模板）：类别只由 `classify(path)` 决定、front-matter 改不动它，硬把现役 design-spec 页
    挪到 root-handoff 路径 ⇒ `face` 变 `page`（躲过裸事实前置），但 `registered_template` 对不上
    ⇒ `TEMPLATE_CATEGORY_MISMATCH` 红。证明「放行」这条路没有可被 front-matter 拨动的分类旋钮。
    """
    sgc = _sgc()
    schemas = dts.load_schemas()  # 真册：design-spec→template 'design-spec'，root-handoff→'handoff'
    assert "design-spec" in schemas, "真模板缺失＝本用例空跑"
    spoof = dts.PageInfo(
        rel="HANDOFF-fake.md", path=ROOT, text="# x", category="root-handoff",
        fm=dts.FrontMatter(template="design-spec", params={}, extra_keys=()),
    )
    # ① 前置侧：改标后其 face 落到非 line（这正是攻击者想躲的东西）——本席放行分支
    assert sgc.face_of_history_page(spoof, driven_non_generated=True) != "line"
    # ② 交叉核验侧：路径类别 ≠ 声明模板 ⇒ 必红（S78 判据，非第二套）
    msg = sgc.category_mismatch(spoof, schemas)
    assert msg is not None and "TEMPLATE_CATEGORY_MISMATCH" in msg, "改标躲尺未被交叉核验抓到"
    # ③ 对照：现役页正位（design-spec 路径 + design-spec 模板）不误伤
    legit = dts.PageInfo(
        rel="docs/design/ok.md", path=ROOT, text="# x", category="design-spec",
        fm=dts.FrontMatter(template="design-spec", params={}, extra_keys=()),
    )
    assert sgc.category_mismatch(legit, schemas) is None


def test_write_historical_still_refused_when_vocab_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """注毒 d：词表取不到 ⇒ **整轮拒写**（含历史台账类）——S83 既有 fail-closed 腿不回归。

    本席新加的「历史类放行」分支只在词表可用时才走；词表失能必须在外层腿先行拒写，
    否则等于给「裸事实=0 才准驱动」开了第二条静默通道（P-S70-2 同型）。
    """
    pg, f = _drive_page(tmp_path, "docs/HANDBOOK.md", "handbook")
    sch = _mini_schema()
    monkeypatch.setattr(dts, "_collect", lambda root=None: ([pg], [], {"mini": sch}))
    monkeypatch.setattr(dts, "_load_fact_vocab", lambda: set())
    rc = dts.main(["--write"])
    err = capsys.readouterr().err
    assert rc != 0, "词表失能仍驱动历史页＝前置假绿"
    assert "FACT_VOCAB_UNAVAILABLE" in err
    assert dts.TPL_AUTO_BEGIN not in f.read_text(encoding="utf-8"), "词表失能却写了机器段"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
