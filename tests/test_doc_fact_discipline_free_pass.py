"""席 S106（2026-09-22）：`{{fact:KEY}}` 免检摘除洞——有条件摘除 + `UNKNOWN_FACT_KEY`。

**只新增用例**：G-T3 既有断言（`tests/test_taxonomy_spec_gates.py`、
`tests/test_board_taxonomy_gate.py`）一字未动；`fact_findings` 的旧调用形态（不传
`known_fact_keys`）逐字保持旧行为，`test_legacy_call_shape_keeps_old_behavior` 即为此锁。
判据尺子只住 `scripts/doc_fact_discipline.py`，本件只喂样本行与内存副本（不落源码树）。

三发反向自测对应简报 §必做③：a) 全树不存在的占位符必红并点名；b) 在册 KEY 放行；
c) 把在册 KEY 从模板删掉（内存副本）⇒ 同一写法重新判红（证在数真在册，非常数放行）。
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doc_fact_discipline as dfd
import doc_template_sync as dts


def _unknown(hits: list[str]) -> list[str]:
    return [h for h in hits if h.startswith(dfd.UNKNOWN_FACT_KEY)]


def _annotated_pages(schemas: dict[str, dts.Schema]) -> list[dts.PageInfo]:
    """与门同口径的页集：`spec_gates_census.py:431` 就是 `annotate(walk_content_pages())`，
    裸 walk 的 `PageInfo.fm` 恒 None（在册数会假零）。"""
    return list(dts.annotate(dts.walk_content_pages(), schemas))


def _first_driven_page(schemas: dict[str, dts.Schema]) -> tuple[dts.PageInfo, str]:
    """真树里第一枚「front-matter 声明了在册模板」的页（只读遍历，不落盘）。"""
    for p in _annotated_pages(schemas):
        if p.fm is not None and p.fm.template in schemas:
            return p, str(p.fm.template)
    raise AssertionError("真树找不到已声明在册模板的页 ⇒ 遍历口径失效，本批失去意义")



def test_poison_a_unknown_key_named_and_line_still_judged() -> None:
    """注毒 a：正文写一个全树不存在的 `{{fact:ZZZ_NOPE}}` ⇒ 必红并点名。

    同行残余同时照常被裸计数尺记账——旧口径这一行只有一条裸计数（占位符那截被无条件
    摘掉）；现口径不摘不在册者，且另记一条独立 finding。
    """
    hits = dfd.fact_findings(
        ["入口数量看 {{fact:ZZZ_NOPE}} 条，另外 47 个能力。"],
        vocab=set(),
        known_fact_keys=frozenset({"count"}),
    )
    named = _unknown(hits)
    assert len(named) == 1, hits
    assert "ZZZ_NOPE" in named[0], named
    assert any(h.startswith("裸计数") for h in hits), hits


def test_poison_b_registered_key_passes_clean() -> None:
    """注毒 b：写在册 KEY ⇒ 放行（不记 `UNKNOWN_FACT_KEY`、也不记任何裸事实）。"""
    line = "入口数量 {{fact:count}} 条，以生成物为准。"
    hits = dfd.fact_findings([line], vocab=set(), known_fact_keys=frozenset({"count"}))
    assert hits == [], hits
    # 同一行、同一支尺，只换成不在册集合 ⇒ 立刻红（b 与 c 的对照，防「常数放行」）
    red = dfd.fact_findings([line], vocab=set(), known_fact_keys=frozenset())
    assert len(_unknown(red)) == 1 and "count" in _unknown(red)[0], red


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("看 {{fact:FOO}} 条。", "FOO"),
        ("看 {{ fact:count }} 条。", "count"),
        ("看 {{fact:}} 条。", ""),
    ],
)
def test_non_canonical_placeholder_shapes_are_named(line: str, key: str) -> None:
    """洞的第二半（本席现算新发现，简报未点名）：非规范形占位符既不匹配
    `PLACEHOLDER_RE`、也不被渲染器消费（`doc_template_sync._PLACEHOLDER_RE` 同认规范形）
    ⇒ 旧口径既不摘除也不报。现一律点名。
    """
    hits = dfd.fact_findings([line], vocab=set(), known_fact_keys=frozenset({"count"}))
    named = _unknown(hits)
    assert len(named) == 1, (line, hits)
    assert f"{{{{fact:{key}}}}}" in named[0], (line, named)


def test_legacy_call_shape_keeps_old_behavior() -> None:
    """既有调用点（`spec_gates_census.py:514`、`doc_template_sync.py:833/842`）逐字不变。

    加严要在门里生效，需那两处改传页级在册参数——两文件都在本席禁线内（门本体 /
    S105 在飞），故成交回工单；本例把「未接线时旧行为原样保留」钉成锁，
    免得后来人误以为改了判据就等于门已执法。
    """
    assert dfd.fact_findings(["入口数量 {{fact:count}} 条。"], vocab=set()) == []
    assert dfd.fact_findings(["看 {{fact:ZZZ_NOPE}}。"], vocab=set()) == []


def test_declared_keys_come_from_the_real_schema_source() -> None:
    """在册参数确实来自 `docs/templates/**` 的 `@schema`（唯一取数口，非本模块自造表）。"""
    schemas = dts.load_schemas()
    assert schemas, "模板装载为空 ⇒ 取数口失效"
    page, tpl = _first_driven_page(schemas)
    raw = page.path.read_text(encoding="utf-8", errors="replace")
    by_front_matter = dfd.declared_fact_keys(raw, schemas=schemas)
    by_template = dfd.declared_fact_keys(page.text, template=tpl, schemas=schemas)
    assert by_front_matter == {q.key for q in schemas[tpl].params}, tpl
    assert by_template == by_front_matter, "两条取数路不同源（正文态 vs 模板 id 态）"
    assert by_template, f"{tpl}: params 解析为空 ⇒ 取数口变形，本例失去意义"


def test_poison_c_dropping_a_key_from_the_template_turns_page_red() -> None:
    """注毒 c：把一枚在册键从模板里删掉（内存副本，不改 `docs/templates/**`）
    ⇒ 该键立刻不再「在册」⇒ 同一写法重新判红；还原 ⇒ 必绿。
    """
    schemas = dts.load_schemas()
    page, tpl = _first_driven_page(schemas)
    keys = dfd.declared_fact_keys(page.text, template=tpl, schemas=schemas)
    victim = next(
        (k for k in sorted(keys) if dfd.PLACEHOLDER_RE.fullmatch("{{fact:" + k + "}}")),
        None,
    )
    assert victim is not None, f"{tpl}: 无可用的规范形在册键"

    slim = dataclasses.replace(
        schemas[tpl],
        params=tuple(q for q in schemas[tpl].params if q.key != victim),
    )
    slim_keys = frozenset(
        dfd.declared_fact_keys(page.text, template=tpl, schemas={tpl: slim})
    )
    assert victim not in slim_keys, "删键后仍算在册 ⇒ 取数口在数常数，不是数真在册"

    line = "数量看 {{fact:" + victim + "}}。"
    red = dfd.fact_findings([line], vocab=set(), known_fact_keys=slim_keys)
    assert len(_unknown(red)) == 1 and victim in _unknown(red)[0], (victim, red)
    green = dfd.fact_findings([line], vocab=set(), known_fact_keys=keys)
    assert green == [], (victim, green)


def test_body_only_text_without_template_fails_strict_not_loose() -> None:
    """取数口取不到模板身份 ⇒ 空集（占位符一律点名），绝不静默回退成「无条件摘除放行」。"""
    schemas = dts.load_schemas()
    page, tpl = _first_driven_page(schemas)
    # 喂**去 front-matter 的正文**（门的四把尺子实际看到的就是这形态）且不给 template
    body = "\n".join(dfd.human_lines(page.text))
    assert dfd.declared_fact_keys(body, schemas=schemas) == set()
    assert dfd.declared_fact_keys(page.text, template="", schemas=schemas) == set()
    # 该页正文里若出现占位符，此形态下必被点名（空集 ⇒ 无在册依据）
    probes = [f"数量看 {{{{fact:{q.key}}}}}。" for q in schemas[tpl].params[:1]]
    assert probes and _unknown(
        dfd.fact_findings(probes, vocab=set(), known_fact_keys=frozenset())
    ), probes




def test_page_fact_findings_only_adds_never_removes_on_real_pages() -> None:
    """真树逐页（读盘、不落盘）：加严只准「多记」，残余裸事实条数不得因传在册参数而减少。"""
    schemas = dts.load_schemas()
    checked = 0
    for p in _annotated_pages(schemas):
        lines = dfd.human_lines(p.text)

        if not lines:
            continue
        tid = None if p.fm is None else p.fm.template
        page_hits = dfd.page_fact_findings(
            p.text, vocab=set(), template=tid, schemas=schemas
        )
        line_hits = dfd.fact_findings(lines, vocab=set())
        extra = [h for h in page_hits if h.startswith(dfd.UNKNOWN_FACT_KEY)]
        assert len(page_hits) - len(extra) >= len(line_hits), (p.rel, line_hits, page_hits)
        checked += 1
        if checked >= 80:
            break
    assert checked > 0, "真树找不到任何有人写正文的页 ⇒ 遍历口径失效"
