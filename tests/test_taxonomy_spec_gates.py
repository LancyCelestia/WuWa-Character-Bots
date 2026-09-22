"""规格统一常驻门 G-T1 / G-T4 / G-T5（席 T-GATES，2026-09-22 立）。

任务书（准绳一·第四步）五道门里，**G-T2 与 G-T3 按明令扩展在
`tests/test_board_taxonomy_gate.py` 的两个点名函数里**（不许另起平行门）；
本文件持有 G-T1/G-T4/G-T5，并与之共用同一支取数口
`scripts/spec_gates_census.py::compute()`（违规、总数、`--report` 三处同源）。

六件套骨架（照抄 `tests/test_physical_placement_gate.py`，未自创）：
① 单一取数口；② 上限=手写字面量 + AST 自锁（`Assign` 与 `AnnAssign` 双形态）；
③ `AUDIT_HISTORY` 方向锁；④ 扫描面地板（塌陷即红）；⑤ 反向自测全走内存/`tmp_path`
（**不往源码树写一个字**）；⑥ 正样控制（判据必须看得见合法件本身）。

判据一句话：
- **G-T1** 每张内容页必须有指向存在模板的 `template:` 头；生成物只按**写盘口现算**豁免
  （board_doc_sync `live_page_paths` / doc_sync `TARGET` / command_catalog `DOC` /
  doc_template_sync `TEMPLATE_DIR`），不写死文件清单。
- **G-T4** 模板 `@schema` 与实际渲染参数双向对齐：缺参红、多参红、死参红、未注册 provider 红。
- **G-T5** 无对应模板的内容类别数=0；类别集合与 `CENSUS.md` §一 **现算**一致；
  孤儿模板、未归类标签、声明却接不到页的类别同样红。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import board_doc_sync as bds
import doc_fact_discipline as dfd
import doc_template_sync as dts
import doc_templates as dt
import spec_gates_census as sc

# ---------------------------------------------------------------------------
# 手写字面量上限（只准降）。每行注释＝本席开工时刻现算命令与值。
# 复跑：PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report
# ---------------------------------------------------------------------------
#: G-T1 无模板头且非生成物 = 1047（2026-09-22 12:1x 本席现算；终态 0）。
T1_CEILING = 1047
#: G-T3 面 B（未迁移手写页，`.superpowers/**` 过程日志除外）= 335 **页**
#: （同上现算；页数单调——追加正文不新增页，故不会随机漂移。终态 0）。
T3_UNMOVED_CEILING = 335
#: G-T4 参数不对齐 = 硬零（模板体系新建，无存量债）。
T4_CEILING = 0
#: G-T5 无模板类别 = 18（现算：22 类里只有 seat-report 有模板、3 类归生成器；终态 0）。
T5_MISSING_TEMPLATE_CEILING = 18
#: —— 以下两枚＝席 S2 T-GATE-HARDEN 加严腿新账本（2026-09-22 13:2x 本席现算）。——
#: G-T1面B 类别↔模板错配页 = 0（现算 0：4 张已驱动页全与注册表一致；终态 0——
#: 复跑 `python scripts/spec_gates_census.py --report` 第 4 行）。
MISMATCH_CEILING = 0
#: G-T5 三角闭合断链 = 9 **类**（现算 9 类压 711 页：root-rules/root-report/handbook/
#: board-meta/design-spec/acceptance/doc-misc/persona-knowledge/sdd-ledger 的在册模板
#: 未建或装载失败；记账单位=类，页数在条目文案里。终态 0）。
T5_DEADCLASS_CEILING = 9

#: 扫描面地板（现算管辖内容页 1277 / 板块生成页 225 / 类别 22）——塌陷即红。
MIN_CONTENT_PAGES = 1200
MIN_BOARD_LIVE_PAGES = 220
MIN_CENSUS_CLASSES = 22
MIN_TEMPLATES = 1

AUDIT_HISTORY_T1: tuple[tuple[str, int], ...] = (("2026-09-22", 1047),)
AUDIT_HISTORY_T3B: tuple[tuple[str, int], ...] = (("2026-09-22", 335),)
AUDIT_HISTORY_T4: tuple[tuple[str, int], ...] = (("2026-09-22", 0),)
AUDIT_HISTORY_T5: tuple[tuple[str, int], ...] = (("2026-09-22", 18),)
AUDIT_HISTORY_MISMATCH: tuple[tuple[str, int], ...] = (("2026-09-22", 0),)
AUDIT_HISTORY_T5_DEADCLASS: tuple[tuple[str, int], ...] = (("2026-09-22", 9),)

_CEILING_NAMES = (
    "T1_CEILING",
    "T3_UNMOVED_CEILING",
    "T4_CEILING",
    "T5_MISSING_TEMPLATE_CEILING",
    "MISMATCH_CEILING",
    "T5_DEADCLASS_CEILING",
    "MIN_CONTENT_PAGES",
    "MIN_BOARD_LIVE_PAGES",
    "MIN_CENSUS_CLASSES",
    "MIN_TEMPLATES",
)
_HISTORY_NAMES = (
    "AUDIT_HISTORY_T1",
    "AUDIT_HISTORY_T3B",
    "AUDIT_HISTORY_T4",
    "AUDIT_HISTORY_T5",
    "AUDIT_HISTORY_MISMATCH",
    "AUDIT_HISTORY_T5_DEADCLASS",
)

_REAL = sc.compute()  # 全模块只现算一次：判据与 --report 同一支


# ---------------------------------------------------------------------------
# G-T1
# ---------------------------------------------------------------------------
def test_g_t1_every_content_page_declares_an_existing_template() -> None:
    viol = _REAL["t1"]
    assert len(viol) <= T1_CEILING, (
        f"无模板头且非生成物的内容页 {len(viol)} > 上限 {T1_CEILING}＝又长了不受模板管辖的新页。"
        f"修法：页首加 `---\\ntemplate: <id>\\nparams:...\\n---`（模板不存在就先建模板，"
        f"模板先行是准绳）；确属生成物则去写盘口登记，别在这里加豁免。"
        f"新增大户：{viol[-6:]}"
    )
    assert viol, "一条都没数到＝取数口瞎了（现网确有上千页未迁移），不是大家都合规"
    assert _REAL["page_total"] >= MIN_CONTENT_PAGES, (
        f"只扫到 {min(_REAL['page_total'], 999999)} 张内容页（地板 {MIN_CONTENT_PAGES}）＝扫描面塌陷，"
        "不是「大家都合规」"
    )


def test_g_t1_generated_exemption_names_its_producer_not_a_file_list() -> None:
    """生成物豁免必须点名取数口：四个写盘口各自现算、非空、且路径真存在。"""
    gen = _REAL["generated_map"]
    for key in (
        "scripts/board_doc_sync.py:live_page_paths",
        "scripts/doc_sync.py:TARGET",
        "scripts/command_catalog.py:DOC",
        "scripts/doc_template_sync.py:TEMPLATE_DIR",
    ):
        assert key in gen, f"生成物判据缺写盘口 {key}（豁免面缩水=未生成页被误判，或反之）"
        assert gen[key], f"{key} 现算为空＝该写盘口对门失明，豁免形同虚设"
        for rel in gen[key]:
            assert (REPO_ROOT / rel).is_file(), f"{key} 报了不存在的页 {rel}"
    boards = gen["scripts/board_doc_sync.py:live_page_paths"]
    assert len(boards) >= MIN_BOARD_LIVE_PAGES, f"板块生成页只剩 {len(boards)} 张＝板块面塌陷"
    assert "docs/boards/README.md" in boards, "live_page_paths 连总览页都没报出来＝取数口错位"


def test_g_t1_poison_bare_and_fake_template_pages_are_named(tmp_path: Path) -> None:
    """反向自测：裸页必被点名；「有头但头指向不存在的模板」同罪（防有头就算数）。
    正样页 fixture 由席 S2 移位（2026-09-22 加严腿 TEMPLATE_CATEGORY_MISMATCH 生效后，
    原先放在 docs/ 的「正样」本身成了 F-2 的套错帽子通道——类别 doc-misc 却声明
    seat-report——fixture 不再合法；断言方向一字未动，只是把正样挪到它真的合规处）。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / ".superpowers").mkdir(parents=True)
    bare = root / "docs" / "bare.md"
    bare.write_text("# 裸页\n\n正文若干。\n", encoding="utf-8")
    fake = root / "docs" / "fake.md"
    fake.write_text("---\ntemplate: no-such-tpl\n---\n\n# 假头\n", encoding="utf-8")
    good = root / ".superpowers" / "SEAT-GOOD.md"
    good.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-POISON\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    viol = set(res["t1"])
    assert "docs/bare.md" in viol, f"裸页没被抓：{sorted(viol)}"
    assert "docs/fake.md" in viol, "指向不存在模板的假头没被抓＝有头就算数"
    assert ".superpowers/SEAT-GOOD.md" not in viol, f"合规页被误杀：{sorted(viol)}"


# ---------------------------------------------------------------------------
# G-T1面B 类别↔模板一致性（席 S2 加严腿，攻击依据 SEAT-T-ACCUSE F-2）
# ---------------------------------------------------------------------------
def test_g_t1b_class_template_mismatch_never_grows() -> None:
    viol = _REAL["mismatch"]
    assert len(viol) <= MISMATCH_CEILING, (
        f"套了「不是它这一类」的在册模板的页 {len(viol)} > 上限 {MISMATCH_CEILING}"
        "（现值 0＝该类假合规一条都不该有）。修法：改页 front-matter 的 template: 为"
        "注册表（doc_templates.py）给它那类的模板，或按升级流程改注册表；"
        "别在门里另写类别表。大户：" + " | ".join(viol[:4])
    )


def test_g_t1b_poison_wrong_template_stays_in_t1_and_is_named(tmp_path: Path) -> None:
    """反向自测（内存）：doc-misc 页随手套 `seat-report` ——F-2 的通道必须两头红：
    ① G-T1 不销籍（仍记债）② TEMPLATE_CATEGORY_MISMATCH 点名（走 compute 记账腿）。
    正样控制：类别↔模板一致的 SEAT 页两头都不红。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "t").mkdir(parents=True)
    wrong = root / "docs" / "wrong.md"
    wrong.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-X\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )
    good = root / ".superpowers" / "sdd" / "t" / "SEAT-GOOD.md"
    good.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-GOOD\n  wave: w\n"
        "  status: DONE\n  role: gate\n  report_class: auto:seat_class\n"
        "  ledger_events: auto:page_stat:ledger\n---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )
    res = sc.compute(root)
    assert "docs/wrong.md" in set(res["t1"]), "套错模板仍从 G-T1 销籍＝F-2 通道没堵"
    named = [m for m in res["mismatch"] if m.startswith("TEMPLATE_CATEGORY_MISMATCH docs/wrong.md")]
    assert named, f"类别↔模板错配没被点名：{res['mismatch']}"
    assert "doc-misc" in named[0] and "guide" in named[0], f"罪状没走注册表口径：{named[0]}"
    assert not any("SEAT-GOOD.md" in m for m in res["mismatch"]), "合规页被误杀（正样控制失败）"
    assert ".superpowers/sdd/t/SEAT-GOOD.md" not in set(res["t1"])


# ---------------------------------------------------------------------------
# G-T5 第三边：类别 ↔ 模板 ↔ 页 三角闭合（席 S2 加严腿）
# ---------------------------------------------------------------------------
def test_g_t5_triangle_closure_pages_never_land_in_unreachable_class() -> None:
    rows = _REAL["t5"]["pages_unreachable"]
    assert len(rows) <= T5_DEADCLASS_CEILING, (
        f"有 {len(rows)} 类（记账单位=类别，页数在文案里）页落到接不到在册模板的类别，"
        f"超上限 {T5_DEADCLASS_CEILING}。修法：为该类别在 docs/templates/ 建模板"
        "（G-T5 另一本账 missing_template 同步销债）。现况：" + " | ".join(rows[:6])
    )
    # 正样控制：seat-report 类在册模板存在且已装载，合法驱动页所在的类不许出现在这条腿上
    assert not any(r.startswith("seat-report:") for r in rows), (
        f"接得到模板的类别被误记三角断链：{rows}"
    )


def test_g_t5_poison_triangle_third_edge_is_named(tmp_path: Path) -> None:
    """反向自测（内存）：doc-misc 的在册模板 `guide` 未落地 ⇒ 压在该类下的每一页
    都必须经第三边记红（G-T5 现只查两角的缺口）。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "orphan.md").write_text("# 无头页\n\n正文。\n", encoding="utf-8")
    res = sc.compute(root)
    rows = res["t5"]["pages_unreachable"]
    assert any(r.startswith("doc-misc:") for r in rows), (
        f"页落在无模板类别却没记三角断链：{rows}"
    )
    assert "1 页" in next(r for r in rows if r.startswith("doc-misc:"))


# ---------------------------------------------------------------------------
# G-T2（判据腿在此锁死；记账在板块门 `test_generated_pages_have_full_skeleton`）
# ---------------------------------------------------------------------------
def test_g_t2_section_ruler_sees_three_poison_shapes() -> None:
    """反向自测（内存）：改名 / 换序 / 塞野节各点名；正样控制＝真骨架原文喂判据必零偏离。"""
    canon = sc.L2_CANON
    ok = ["这个功能解决什么", "处理流程", "测试与验收"]
    assert sc.section_findings(ok, canon) == [], f"合法件被误杀：{sc.section_findings(ok, canon)}"
    renamed = sc.section_findings(["这个功能做什么", "处理流程", "测试与验收"], canon)
    assert any("SECTION_UNKNOWN" in v for v in renamed), "改节名没被抓"
    swapped = sc.section_findings(["处理流程", "这个功能解决什么", "测试与验收"], canon)
    assert any("SECTION_ORDER" in v for v in swapped), "换序没被抓"
    extra = sc.section_findings(ok + ["现役进度"], canon)
    assert any("SECTION_UNKNOWN" in v for v in extra), "塞野节没被抓"
    missing = sc.section_findings(["这个功能解决什么", "处理流程"], canon)
    assert any("SECTION_MISSING" in v and "测试与验收" in v for v in missing), "缺必选节没被抓"
    # 正样控制二：三份真骨架原文喂各自 canon 必须零偏离（判据看不见标准件＝空跑）
    for body, lc in ((bds.L1_BODY, sc.L1_CANON), (bds.L2_BODY, sc.L2_CANON), (bds.L3_BODY, sc.L3_CANON)):
        assert sc.section_findings(sc.headings(body), lc) == [], f"{lc[:1]} 自骨架喂自判据不合规"


# ---------------------------------------------------------------------------
# G-T4
# ---------------------------------------------------------------------------
def test_g_t4_schema_and_render_params_stay_aligned() -> None:
    viol = _REAL["t4"]
    assert len(viol) <= T4_CEILING, (
        f"@schema 与实际渲染参数不对齐 {len(viol)} 项（上限 {T4_CEILING}，模板体系无存量债）：\n"
        + "\n".join(viol[:12])
    )
    assert len(_REAL["schemas"]) >= MIN_TEMPLATES, "模板面为空＝G-T4 变成空门"


def test_g_t4_poisons_missing_extra_dead_param_and_bad_provider() -> None:
    """反向自测（全内存 fixture，不碰 docs/templates）：缺参/多参/死参/未注册 provider/
    规格外占位各红；真模板零违规作正样控制（判据看不见合法件＝空跑）。"""
    real = dts.parse_schema_text(
        (REPO_ROOT / "docs" / "templates" / "seat-report.md").read_text(encoding="utf-8"),
        "seat-report",
    )
    assert sc.template_side_t4({"seat-report": real}) == [], "真模板被判死参＝正样控制失败"

    def synth(extra_decl: str, zone: str) -> dts.Schema:
        return dts.parse_schema_text(
            "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
            "- seat_id | text | literal | req | nonempty\n" + extra_decl +
            "@schema:END -->\n"
            "<!-- TEMPLATE-AUTO:BEGIN -->\n" + zone + "\n<!-- TEMPLATE-AUTO:END -->\n",
            "poison",
        )

    # ① 死参：声明了却没被渲染区消费
    rows = sc.template_side_t4({"poison": synth("- loner | text | literal | opt | any\n", "- {{fact:seat_id}}")})
    assert any(v.startswith("DEAD_PARAM") and "loner" in v for v in rows), f"死参没被抓：{rows}"
    # ② auto 指向未注册 provider
    rows = sc.template_side_t4({"poison": synth("- cls | text | auto:nope | req | any\n", "- {{fact:seat_id}}{{fact:cls}}")})
    assert any(v.startswith("PROVIDER_MISSING") and "nope" in v for v in rows), f"未注册 provider 没被抓：{rows}"
    # ③ 渲染区写了 params 里没有的占位（规格外）
    with pytest.raises(dts.SchemaError, match="占位"):
        synth("", "- {{fact:seat_id}}{{fact:ghost}}")

    # ④ 页侧：多参与缺参同时点名
    _vals, viol = dts.resolve_params(
        real,
        dts.FrontMatter(template="seat-report", params={"nope": "x"}, extra_keys=("junk",)),
        dts.PageCtx(rel="x/SEAT-A.md", body_no_fm=""),
    )
    codes = " ".join(viol)
    assert "EXTRA_PARAM" in codes and "nope" in codes, f"多参没被抓：{codes}"
    assert "MISSING_PARAM" in codes, f"缺必填参没被抓：{codes}"
    page_viol = dts.check_page(
        real, "", dts.FrontMatter(template="seat-report", params={}, extra_keys=("junk",)),
        dts.PageCtx(rel="x/SEAT-A.md", body_no_fm="## 交付\n"),
    )
    assert "FM_EXTRA_KEY" in " ".join(page_viol), f"front-matter 规格外键没被抓：{page_viol}"
    assert any(v.startswith("MISSING_PARAM") for v in page_viol), f"空 params 页没被抓：{page_viol}"


def test_g_t4_poison_req_param_must_actually_come_from_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反向自测（席 S2 活性腿，全走 compute **记账腿**，不是只喂正则）：
    ① `req`+`auto:` 参数字面量冒充 ⇒ AUTO_SOURCE_MISMATCH 进 t4；
    ② 该参数整个缺掉 ⇒ MISSING_PARAM 进 t4；
    ③ provider 跑通却交空值 ⇒ PROVIDER_EMPTY 进 t4；
    正样控制＝三项都写对的页在 t4 里零罪状。"""
    root = tmp_path / "repo"
    pkg = root / ".superpowers" / "sdd" / "t"
    pkg.mkdir(parents=True)

    def page(name: str, report_class: str, ledger: str) -> str:
        (pkg / name).write_text(
            "---\ntemplate: seat-report\nparams:\n"
            f"  seat_id: T-{name[:5]}\n  wave: w\n  status: DONE\n  role: gate\n"
            f"  report_class: {report_class}\n  ledger_events: {ledger}\n"
            "---\n\n## 交付\n\n正文。\n",
            encoding="utf-8",
        )
        return f".superpowers/sdd/t/{name}"

    fake = page("SEAT-FAKE.md", "SEAT", "auto:page_stat:ledger")  # ① 字面量冒充现算值
    missing = pkg / "SEAT-MISS.md"
    missing.write_text(
        "---\ntemplate: seat-report\nparams:\n  seat_id: T-M\n  wave: w\n"
        "  status: DONE\n  role: gate\n  ledger_events: auto:page_stat:ledger\n"
        "---\n\n## 交付\n\n正文。\n",
        encoding="utf-8",
    )  # ② 必填 auto 参数整个缺掉
    good = page("SEAT-OK.md", "auto:seat_class", "auto:page_stat:ledger")

    res = sc.compute(root)
    t4 = " \n".join(res["t4"])
    assert fake in t4 and "AUTO_SOURCE_MISMATCH" in t4 and "report_class" in t4, (
        f"字面量冒充没进记账腿：{res['t4']}"
    )
    assert ".superpowers/sdd/t/SEAT-MISS.md" in t4 and "MISSING_PARAM" in t4, (
        f"缺必填 auto 参没进记账腿：{res['t4']}"
    )
    assert not any(good in v for v in res["t4"]), f"合规页被误杀（正样控制失败）：{res['t4']}"

    # ③ provider 现算空值：摘掉 page_stat 真身、换上交白卷的假 provider，再走一遍记账
    monkeypatch.setitem(dts.PROVIDERS, "page_stat", lambda arg, ctx: "")
    res2 = sc.compute(root)
    assert any(
        "SEAT-OK.md" in v and "PROVIDER_EMPTY" in v for v in res2["t4"]
    ), f"provider 空值冒充现算没被抓：{res2['t4']}"
    monkeypatch.setitem(dts.PROVIDERS, "page_stat", lambda arg, ctx: "（未填）")
    res3 = sc.compute(root)
    assert any(
        "SEAT-OK.md" in v and "PROVIDER_EMPTY" in v for v in res3["t4"]
    ), f"占位符冒充现算值没被抓：{res3['t4']}"


# ---------------------------------------------------------------------------
# G-T5
# ---------------------------------------------------------------------------
def test_g_t5_category_set_equals_census_section_one() -> None:
    t5 = _REAL["t5"]
    assert t5["census_count"] >= MIN_CENSUS_CLASSES, (
        f"只从 CENSUS §一 解析出 {t5['census_count']} 个类别名＝判据源改版或表格变形，门必须复核"
    )
    assert t5["cid_set_matches_census"], (
        "类别集合与 CENSUS §一 不一致："
        f"仅在册 {t5['registry_only']} / 仅 CENSUS {t5['census_only']}"
    )
    assert not t5["unknown_labels"], f"出现未在册的类别标签（自由发挥类）：{t5['unknown_labels']}"
    assert not t5["orphan_templates"], f"孤儿模板（无类别引用）：{t5['orphan_templates']}"
    assert not t5["declared_no_page"], (
        f"在册却一张页也接不到的文档类（死类别＝假在册）：{t5['declared_no_page']}"
    )


def test_g_t5_no_class_without_a_template() -> None:
    missing = _REAL["t5"]["missing_template"]
    assert len(missing) <= T5_MISSING_TEMPLATE_CEILING, (
        f"无对应模板的内容类别 {len(missing)} > 上限 {T5_MISSING_TEMPLATE_CEILING}。"
        f"每类一份模板是准绳；修法=为该类别建 docs/templates/<id>.md（含 @schema），"
        f"或在注册表把它并入已有类别。欠款大户：{missing[:8]}"
    )
    assert missing, "一条都没数到＝注册表与模板目录对不上眼时门会空跑"


def test_g_t5_registry_has_a_single_home() -> None:
    """结构锁：`CONTENT_CATEGORIES` 字面量只准住 `scripts/doc_templates.py`。"""
    homes: list[str] = []
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "tests", REPO_ROOT / "plugins"]
    for base in roots:
        for py in base.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                if any(isinstance(t, ast.Name) and t.id == "CONTENT_CATEGORIES" for t in targets):
                    homes.append(py.relative_to(REPO_ROOT).as_posix())
    assert homes == ["scripts/doc_templates.py"], (
        f"类别注册表出现第二真身 {homes}——G-T5 会各按一套账，必须合并到注册表"
    )


def test_g_t5_poison_class_without_template_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向自测（内存摘模板）：把在册类别的模板摘掉，门当场点名该类别。"""
    rows = list(dt.CONTENT_CATEGORIES)
    for i, c in enumerate(rows):
        if c.cid == "handbook":
            rows[i] = dt.CategoryDef(
                cid=c.cid, template=None, surface=c.surface, owner_board=c.owner_board,
                reason=c.reason,
            )
    monkeypatch.setattr(dt, "CONTENT_CATEGORIES", tuple(rows))
    res = sc.compute()
    named = [m for m in res["t5"]["missing_template"] if m.startswith("handbook:")]
    assert named, "摘掉模板的类别没被抓＝G-T5 对『无模板类别』失明"


# ---------------------------------------------------------------------------
# G-T3 面 B（未迁移页；面 A 在板块门 `test_board_docs_do_not_handwrite_volatile_counts`）
# ---------------------------------------------------------------------------
def test_g_t3_unmoved_face_debt_never_grows() -> None:
    hits = _REAL["t3_unmoved"]
    assert len(hits) <= T3_UNMOVED_CEILING, (
        f"未迁移页含裸写一次性事实 {len(hits)} 页 > 上限 {T3_UNMOVED_CEILING}＝又添了新的未受管页面。"
        f"修法：该页迁移到模板（页首 front-matter + 事实走 `auto:`/`{{fact:KEY}}` 引用），"
        f"或写成「以真身/生成物为准」的指针句；大户：{hits[-6:]}"
    )
    assert hits, "一条都没数到＝词表或取数口失效（未迁移页必有多次性事实）"


def test_g_t3_fact_ruler_sees_four_poison_shapes_and_passes_pointers() -> None:
    """反向自测：裸计数/裸阈值/裸路径/裸枚举各红；带指针与粘连负样本放行。"""
    vocab = {"天气", "股票", "笔记", "提醒", "占卜", "行情", "快报", "随机图"}
    cases = {
        "裸计数": "本板块共 47 个能力入口。",
        "裸阈值": "单文件上限 100MB，超时 30 秒。",
        "裸路径": "归档落在 data/media_archive/ 与 C:/Users/x/Runtime/ 下。",
        "裸枚举": "支持 天气、股票、笔记、提醒、占卜、行情、快报、随机图 八类。",
    }
    for want, line in cases.items():
        hits = dfd.fact_findings([line], vocab=vocab)
        assert hits and want.rstrip("数") in hits[0] or hits, f"{want} 未被识别：{line}"
    for ok in (
        "字段数以机器册 docs/auto-facts.md 为准。",
        "{{fact:count}} 条入口（渲染期现算）。",
        "§9 字段级契约与 v21r2 主题、zhconv 1.4.3 版本无关。",
    ):
        assert dfd.fact_findings([ok], vocab=vocab) == [], f"合法句被误杀：{ok}"
    # 围栏与机器段不算人写正文
    fenced = dfd.human_lines("正文\n\n```text\n共 47 个能力\n```\n")
    assert dfd.fact_findings(fenced, vocab=vocab) == [], "围栏代码块内的示例被误判"
    autoed = dfd.human_lines(
        "<!-- BOARD-AUTO:BEGIN -->\n共 47 个能力\n<!-- BOARD-AUTO:END -->\n人写行\n"
    )
    assert not any("47" in x for x in autoed), "机器段没被剥掉＝生成物被误记在作者头上"


# ---------------------------------------------------------------------------
# 上限字面量 + 方向锁 + 单一取数口自证
# ---------------------------------------------------------------------------
def test_ceilings_are_hand_written_literals() -> None:
    """结构锁：上限必须是字面整数，不许 len(...)/sum(...) 派生（`Assign` 与 `AnnAssign` 双形态）。

    两块账本一起锁：本文件（G-T1/T3面B/T4/T5）与板块门文件里被扩展的 G-T2/T3面A。
    """
    wanted = {
        Path(__file__): _CEILING_NAMES + _HISTORY_NAMES,
        REPO_ROOT / "tests" / "test_board_taxonomy_gate.py": (
            "T2_CEILING",
            "T3_MANAGED_CEILING",
            "MIN_T2_PAGES",
            "AUDIT_HISTORY_T2",
            "AUDIT_HISTORY_T3_MANAGED",
        ),
    }
    for path, names in wanted.items():
        assigned: dict[str, ast.expr | None] = {}
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
        for name in names:
            value = assigned.get(name)
            if name.startswith("AUDIT_HISTORY"):
                assert isinstance(value, ast.Tuple) and value.elts, (
                    f"{path.name}::{name} 必须留在该文件且非空（只降的对账凭据）"
                )
                continue
            assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
                f"{path.name}::{name} 被改成派生表达式＝上限跟着被检对象一起动，本门结构性失效"
            )


def test_audit_histories_never_rise() -> None:
    pairs = (
        (AUDIT_HISTORY_T1, T1_CEILING, len(_REAL["t1"])),
        (AUDIT_HISTORY_T3B, T3_UNMOVED_CEILING, len(_REAL["t3_unmoved"])),
        (AUDIT_HISTORY_T4, T4_CEILING, len(_REAL["t4"])),
        (AUDIT_HISTORY_T5, T5_MISSING_TEMPLATE_CEILING, len(_REAL["t5"]["missing_template"])),
        (AUDIT_HISTORY_MISMATCH, MISMATCH_CEILING, len(_REAL["mismatch"])),
        (
            AUDIT_HISTORY_T5_DEADCLASS,
            T5_DEADCLASS_CEILING,
            len(_REAL["t5"]["pages_unreachable"]),
        ),
    )
    for history, ceiling, current in pairs:
        counts = [n for _d, n in history]
        assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{history}"
        assert ceiling <= counts[0], f"上限 {ceiling} 超过首届核账值 {counts[0]}＝调大换绿"
        assert current <= ceiling, f"现算值 {current} 已超上限 {ceiling}"


def test_report_and_gate_read_the_same_numbers() -> None:
    """单一取数口自证：`--report` 打印的每个数＝本门判据用的同一个现算值。"""
    lines = "\n".join(sc.report_lines(_REAL))
    assert f"G-T1 无模板头且非生成物 = {len(_REAL['t1'])}" in lines
    assert (
        f"G-T1面B 类别↔模板错配页（TEMPLATE_CATEGORY_MISMATCH）= {len(_REAL['mismatch'])}"
        in lines
    )
    assert f"G-T2 小节偏离页 = {len(_REAL['t2'])}" in lines
    assert (
        f"面 A 管辖 {len(_REAL['t3_managed'])} 行 / 面 B 未迁移 {len(_REAL['t3_unmoved'])} 页"
        in lines
    )
    assert f"G-T4 参数不对齐 = {len(_REAL['t4'])}" in lines
    assert f"G-T5 无模板类别 = {len(_REAL['t5']['missing_template'])}" in lines
    assert f"三角闭合断链 {len(_REAL['t5']['pages_unreachable'])} 类" in lines


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
