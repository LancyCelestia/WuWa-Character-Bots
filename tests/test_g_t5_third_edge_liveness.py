"""G-T5「三角第三边」活性门（席 S161，2026-09-22，第二十五批）。

一句话：补上「**页落在无模板类别 ⇒ 必须记进三角断链**」这条边——门本体
`tests/test_taxonomy_spec_gates.py` 里那枚红名（`test_g_t5_poison_triangle_third_edge_is_named`）
的前提「用 tmp 副本让 `guide` 未落地」其实永不成立（`compute(root)` 的 schemas 恒从真身
`doc_template_sync.TEMPLATE_DIR` 装载、与 root 无关），所以那枚红与「第三边不执法」是两回事；
它属禁写面，本席一字不碰。§7「新建可以」⇒ 本文件新建一枚门，把真正的缺口执法起来。

**缺口精确定位（复用同一取数口 `spec_gates_census.compute()` 现算，零复制逻辑、零第二本账）**：
`compute()` 的死类循环（`spec_gates_census.py` 约 905–915 行）只在此条件下记红——
`want = registered_template(p.category); want is not None and want not in schemas`。
即「类别**有**一个在册模板 id、但该模板装载失败」。而「类别在册、该桶**压根没有**模板
（`c.template is None`）」这一形状：`registered_template()` 对 md 且非生成器所有的类返回
`c.template`＝`None` ⇒ `want is not None` 短路 ⇒ 该页**永不进** `pages_unreachable`。
这类页今日只被 `missing_template`（按**类别**记「无对应模板」）抓到，从没被**按页**的三角闭合腿
（页→类别→模板）抓到。本门就把这条按页活性执法起来。

三本账分工（互不重复，本门只消费 `pages_unreachable`）：
- `t5.pages_unreachable`（本门）——**按页**：某类下有多少页落进接不到模板的类别（三角第三边·活性）。
- `t5.missing_template`（席 S2 原始账）——**按类别**：某类无对应模板文件 / 生成口解析不到。
- `t5.templates_without_pages`（席 S119 孤儿账）——**按模板**：在册模板驱动 0 页。
- 交付口径（席 S116 `content_census.py`/`CENSUS.md`）——记「交付用哪本数」，不是第四条判据。

六件套骨架照抄常驻门（未自创）：单一取数口、正样控制（判据必须看得见合法件）、反向自测全走
内存 / `tmp_path`（**不往源码树写一个字**）、fail-closed 自锁（形状异常判红，防「空集合恒真」）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doc_template_sync as dts
import doc_templates as dt
import spec_gates_census as sc

#: 本门专攻「在册 md 类但该桶无模板」这一形状，借 `doc-misc`（md、非生成器所有）当载体。
#: `classify("docs/orphan.md") == "doc-misc"` 由真 `classify` 现算，不写死。
_PROBE_CID = "doc-misc"
_PROBE_REL = "docs/orphan.md"


# ---------------------------------------------------------------------------
# 造形与读口（内存 / tmp 副本，注毒不落源码树）
# ---------------------------------------------------------------------------
def _docmisc_with_template(monkeypatch: pytest.MonkeyPatch, template: str | None) -> None:
    """把在册类 `doc-misc` 的模板改成 `template`（`None`＝该桶无模板）。

    两份注册表视图（`CONTENT_CATEGORIES` 与 `CATEGORIES_BY_ID`）同步改，teardown 自动还原。
    这是构造「类别在册但该桶无模板」的**唯一手段**：不改 `scripts/**`、不落盘、不新建第二套分类表。
    """
    rows: list[dt.CategoryDef] = []
    for c in dt.CONTENT_CATEGORIES:
        if c.cid == _PROBE_CID:
            c = dt.CategoryDef(
                cid=c.cid, template=template, surface=c.surface, owner_board=c.owner_board,
                generated_by=c.generated_by, code_home=c.code_home, reason=c.reason,
            )
        rows.append(c)
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", tuple(rows))
    monkeypatch.setattr(dt, "CATEGORIES_BY_ID", {c.cid: c for c in rows})


def _orphan_page_root(tmp_path: Path) -> Path:
    """在临时副本里放一张无头页，落到 `doc-misc` 桶；返回 root（供 `compute(root)` 现算）。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "orphan.md").write_text("# 无头页\n\n正文。\n", encoding="utf-8")
    assert dts.classify(_PROBE_REL) == _PROBE_CID, "取数口改版：该页不再落到 doc-misc，注毒前提塌"
    return root


def _third_edge_rows(res: dict[str, object]) -> list[str]:
    """fail-closed 读第三边（自锁 ③）。

    形状不符——缺 `t5` / 缺 `pages_unreachable` / 非 `list` / 元素非 `str`——一律判红，
    绝不把「读不出来」当成「无违规」的空集合放行（本项目已记 45 形态假绿，含「空集合恒真」）。
    """
    t5 = res.get("t5")
    assert isinstance(t5, dict), f"取数口缺 t5 或类型异常（{type(t5)}）＝读口失明，判红不判绿"
    rows = t5.get("pages_unreachable")
    assert isinstance(rows, list), f"pages_unreachable 不是 list（{type(rows)}）＝取数口改版"
    assert all(isinstance(r, str) for r in rows), "三角断链元素非字符串＝取数口返回类型异常"
    return rows


# ---------------------------------------------------------------------------
# ① 单一取数口自证 + 正样控制：可达类别不许进这条边（判据不是一把全判死的尺）
# ---------------------------------------------------------------------------
def test_third_edge_port_reachable_category_stays_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正样控制：`doc-misc` 的在册模板 `guide` 可装载 ⇒ 压在该类下的页**不该**被记三角断链。

    这条绿证本门不是一把「凡有页就判红」的钝尺——它必须看得见「合法件本身」（六件套骨架第⑥条）。
    """
    _docmisc_with_template(monkeypatch, "guide")
    rows = _third_edge_rows(sc.compute(_orphan_page_root(tmp_path)))
    assert not any(r.startswith(f"{_PROBE_CID}:") for r in rows), (
        f"模板可达的类别被误记三角断链（钝尺误杀，正样控制失败）：{rows}"
    )


# ---------------------------------------------------------------------------
# ② 反向自测（已执法的半边）：在册模板装载失败 ⇒ 必被记（证取数口有牙，非空集合恒真）
# ---------------------------------------------------------------------------
def test_third_edge_port_fires_when_registered_template_unloadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对照半边：类有在册模板 id、但那个模板装载不了 ⇒ 死类循环**今天就能**抓到（绿）。

    这条的存在是为了证明 `pages_unreachable` 不是「恒返回 `[]`」的假口——若它被改坏成永远空，
    本条当场红。真正的缺口在下一条（无模板类别）：本条绿、下一条红，恰好把「已执法半边」与
    「未执法半边」的分界钉死，防止把整条腿误判成「反正都红」。
    """
    _docmisc_with_template(monkeypatch, "s161-ghost-not-a-real-template")
    rows = _third_edge_rows(sc.compute(_orphan_page_root(tmp_path)))
    assert any(r.startswith(f"{_PROBE_CID}:") for r in rows), (
        f"在册模板装载失败却没记三角断链＝取数口有洞或恒空（假绿）：{rows}"
    )
    assert any("1 页" in r for r in rows if r.startswith(f"{_PROBE_CID}:")), (
        f"断链按页计数没落进文案（记账单位异常）：{rows}"
    )


# ---------------------------------------------------------------------------
# ③ fail-closed 自锁：取数口形状异常一律判红，绝不静默退化成「无违规」
# ---------------------------------------------------------------------------
def test_third_edge_read_fails_closed_on_malformed_shape() -> None:
    """喂畸形返回：缺 t5 / 缺键 / 非 list / 元素非 str ⇒ `_third_edge_rows` 一律抛（判红）。

    防的正是「空集合恒真」那一族假绿：一旦有人把取数口改成返回 `{}` 或把违规悄悄塞成 `[]`，
    读口必须炸、不得把「读不到」当「合规」。
    """
    malformed: tuple[dict[str, object], ...] = (
        {},
        {"t5": "not-a-dict"},
        {"t5": {}},
        {"t5": {"pages_unreachable": "oops-not-list"}},
        {"t5": {"pages_unreachable": [1, 2]}},
    )
    for bad in malformed:
        with pytest.raises(AssertionError):
            _third_edge_rows(bad)


# ---------------------------------------------------------------------------
# ④ 三本账不建重复账：本门只消费 pages_unreachable，与 missing_template / 孤儿账形状互斥
# ---------------------------------------------------------------------------
def test_three_ledgers_are_distinct_and_poison_leaves_no_disk_trace(tmp_path: Path) -> None:
    """结构性分工锁（不随未来修复而翻红）：三本账是不同键、不同记账单位，本门不越界消费。

    `missing_template`（按类别）/ `templates_without_pages`（按模板·S119 分桶 dict）/
    `pages_unreachable`（按页·本门）三者形状互斥；注毒只走 `tmp_path` 副本，源码树零落盘。
    """
    res = sc.compute()  # 真树现算，只为拿形状，不作数值断言
    t5 = res["t5"]
    assert isinstance(t5, dict)
    assert isinstance(t5["missing_template"], list), "missing_template 应按类别列条目"
    assert isinstance(t5["pages_unreachable"], list), "pages_unreachable 应按页列条目（本门消费面）"
    assert isinstance(t5["templates_without_pages"], dict), (
        "templates_without_pages（S119 孤儿账）按模板分桶＝dict，与本门 list 形状天然不同源，"
        "证明三本账不是同一本换了皮"
    )
    # 注毒不落盘：真源码树里绝不能因为本席跑过 tmp 测试就冒出 orphan.md。
    assert not (REPO_ROOT / _PROBE_REL).exists(), f"注毒泄漏到源码树：{REPO_ROOT / _PROBE_REL}"


# ---------------------------------------------------------------------------
# ⑤ 活性执法腿（本席的门今日**如实红着**）：无模板类别下的页必须进三角断链
# ---------------------------------------------------------------------------
def test_g_t5_third_edge_liveness_no_template_bucket_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺口本体：类在册、但该桶**没有**模板（`c.template is None`）⇒ 其页**必须**被记进
    `pages_unreachable`。门本体的死类循环 `want is not None and want not in schemas` 对
    `want is None` 短路，故这条边今日**不执法**、本断言如实红。

    §7「新建可以、事后回改不行」＋ `scripts/**` 是本席禁写面 ⇒ 我**不改门本体**，只把这条
    执法需求钉成一枚会红的门（可执行规格）。该腿要变绿须改 `compute()` 死类循环一处，
    最小 diff 与该改由谁做，见报告 SEAT-S161.md 的 PARKED 段。
    """
    _docmisc_with_template(monkeypatch, None)  # 类别在册但该桶无模板
    root = _orphan_page_root(tmp_path)
    res = sc.compute(root)
    rows = _third_edge_rows(res)
    t5 = res["t5"]
    assert isinstance(t5, dict)
    in_missing = any(m.startswith(f"{_PROBE_CID}:") for m in t5["missing_template"])
    assert any(r.startswith(f"{_PROBE_CID}:") for r in rows), (
        f"页落在「在册但无模板」的类别却没记三角断链＝第三边不执法（本席钉的可执行规格，"
        f"须改门本体死类循环一处方能转绿，见 SEAT-S161 PARKED 最小 diff）。"
        f"对照：同一页今日被 missing_template 按类别抓到没有＝{in_missing}"
        f"（该页只落类别账、不落按页三角账，正是缺口）。"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
