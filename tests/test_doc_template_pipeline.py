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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
