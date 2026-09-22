"""席 S116 新增用例（**全部为新增断言，未回改任何既有测试与基线**）。

覆盖两件交付：
① 两本账唯一名 + 换算式（消灭「G-T1 一名两义」，席 S111 的 C-2）——真树对账 + 注毒必红；
② 代码件五族管辖面三数腿（席 S111 的 C-3 / 总账 #22「代码内五类纳入管辖面」）——
   只加数不缩面 + 三数闭合 + 两腿不串 + 存量缺陷（`#原因` 尾注双计）回归锁。

席 S127（2026-09-22）**追加**（未回改上方任何既有用例）：§4③ 形态(b)「生成脚本可复现字节」
接入代码面后的通道登记锁、三腿实证、五发反向注毒（不幂等／无锚点／无源族硬走 (b)／
生成口抛异常／产物过期）、甲账不变自证、册面文本锁。

跑：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_content_census_s116.py -q
    -p no:cacheprovider --basetemp="$TEMP/S116-1"`
"""

from __future__ import annotations

import dataclasses
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import content_census as cc
import doc_templates as dt

_CENSUS_MD = ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy" / "CENSUS.md"


def _page(rel: str, template: str | None = None) -> types.SimpleNamespace:
    """最小 `PageInfo` 替身：本文件只消费 `rel` 与 `fm.template` 两个面。"""
    fm = types.SimpleNamespace(template=template, params={}) if template else None
    return types.SimpleNamespace(rel=rel, fm=fm)


def _stub_res(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "pages": [_page("docs/a.md", "guide"), _page("plugins/x.py")],
        "t1": ["plugins/x.py"],
        "b_ok": [],
        "generated_all": [],
        "mismatch": [],
        "t1_by_cat": {},
        "schemas": {},
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- 两本账
def test_books_are_two_distinct_named_accounts() -> None:
    """两本账各起唯一名，且**不是同一个数**（旧册散文把它们当同一数＝本席更正的错账）。"""
    assert cc.BOOK_CENSUS == "G-T1" and cc.BOOK_WRITER == "WRITER-UND"
    assert cc.BOOK_CENSUS != cc.BOOK_WRITER
    assert cc.BOOK_CONVERSION == f"{cc.BOOK_WRITER} = {cc.BOOK_CENSUS} + MECH_B + TEMPLATE_SRC"


def test_census_book_is_bitwise_equal_to_gate_t1_entries() -> None:
    """甲账与门 G-T1 **逐位相等**：条数取门原值，不重复计带因条目、也不漏计。"""
    res = _stub_res(t1=["plugins/x.py", "docs/gen.md#生成物未当场复现字节等值"])
    b = cc.books(res)
    assert b[cc.BOOK_CENSUS] == 2 == len(res["t1"])
    assert b["t1_rels"] == 2  # 剥注后仍两枚 ⇒ 尾注不会把一条拆成两条


def test_mech_b_excludes_pages_already_counted_in_t1() -> None:
    """`MECH_B` 只数「生成物且当场复现」者；已进甲账的带因页不得再进换算式（否则虚报对平）。"""
    res = _stub_res(
        pages=[_page("docs/gen.md"), _page("docs/undriven.md")],
        t1=["docs/gen.md#生成物未当场复现字节等值"],
        b_ok=["docs/gen.md"],
        generated_all=["docs/gen.md"],
    )
    b = cc.books(res)
    assert b["MECH_B"] == 0, "在册未复现页被同时记进甲账与 MECH_B ⇒ 双重计账"


def test_conversion_holds_on_real_tree() -> None:
    """**真树现算**：换算式成立且残差为 0（席 S111 记的 249 构成即此式的当时读数）。"""
    import spec_gates_census as sgc

    b = cc.books(sgc.compute())
    ok, msg = cc.reconcile_books(b)
    assert ok, msg
    assert b["MECH_B"] + b["TEMPLATE_SRC"] - b["MISMATCH"] == b[cc.BOOK_WRITER] - b[cc.BOOK_CENSUS]
    assert b["TEMPLATE_SRC"] > 0 and b["MECH_B"] > 0, "换算项塌成 0 ⇒ 两本账会被误当成同一数"


def test_poison_c_conversion_broken_makes_the_ledger_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒①（简报 ④c）：故意让两本账换算式不成立 ⇒ 对账断言必红，且 `render()` 拒绝生成册。"""
    bad = {cc.BOOK_CENSUS: 10, cc.BOOK_WRITER: 999, "MECH_B": 0, "TEMPLATE_SRC": 0, "MISMATCH": 0}
    ok, msg = cc.reconcile_books(bad)
    assert not ok and "换算式不成立" in msg and "差 989 枚" in msg

    monkeypatch.setattr(cc.sgc, "compute", lambda *a, **k: _stub_res(t1=["plugins/x.py"]))
    monkeypatch.setattr(
        cc, "writer_book", lambda: {"pages": 0, "driven": 0, cc.BOOK_WRITER: 999, "schema_errors": 0}
    )
    with pytest.raises(AssertionError, match="换算式不成立"):
        cc.render()


def test_census_md_renames_both_books_and_states_the_formula() -> None:
    """盘上册必须带两本账新名、换算式与「交付值取甲账」——防散文回退成一名两义。"""
    text = _CENSUS_MD.read_text(encoding="utf-8")
    assert cc.BOOK_CENSUS in text and cc.BOOK_WRITER in text
    assert "MECH_B" in text and "TEMPLATE_SRC" in text
    # 只禁**旧句原形**（旧册把它当事实陈述）；本席的更正句里引用该短语作被驳对象，不算回潮。
    assert "只可能是取数时刻之差，不可能是口径之差" not in text, "旧「不可能是口径之差」断言原样回潮"
    assert "席 S116 更正旧断言" in text, "页首未注明这是更正（散文被后人当门错、可能被改回去）"
    assert "交付值取甲账" in text


# --------------------------------------------------------------------------- 代码面三数腿
def test_ledger_covers_every_code_surface_class_and_persona_family() -> None:
    """**不缩扫描面**：注册表里每一枚 `surface=="code"` 的类别、以及 `persona*` 全族都在账上。"""
    rows = cc.code_face_ledger(_stub_res(), {}, {cid: ([], "stub") for cid in cc.CARD_CODE_CIDS})
    cids = {r.cid for r in rows}
    assert {c.cid for c in dt.CONTENT_CATEGORIES if c.surface == "code"} <= cids
    assert {c.cid for c in dt.CONTENT_CATEGORIES if (c.template or "").startswith("persona")} <= cids
    fams = {r.family for r in rows}
    assert {"card-*", "config-field", "help-entry", "copy-pool", "persona-*"} <= fams


def test_poison_a_new_undriven_code_item_is_counted() -> None:
    """注毒②（简报 ④a）：造一枚未驱动代码件 ⇒ 必被计进在册与未驱动两列。"""
    items = {cid: ([], "stub") for cid in cc.CARD_CODE_CIDS}
    base = cc.code_face_ledger(_stub_res(), {}, items)
    row0 = next(r for r in base if r.cid == "jinja-template")
    assert (row0.registered, row0.driven, row0.undriven) == (0, 0, 0)

    injected = dict(items)
    injected["jinja-template"] = (["plugins/whatever/templates/new_card.html"], "stub")
    row1 = next(r for r in cc.code_face_ledger(_stub_res(), {}, injected) if r.cid == "jinja-template")
    assert (row1.registered, row1.driven, row1.undriven) == (1, 0, 1)
    assert "须换机制" in row1.verdict


def test_code_driven_predicate_is_real_not_constant() -> None:
    """`已驱动` 判据有牙：给管辖页里塞一枚**非 md 且挂在册模板头**的件 ⇒ 该类 `已驱动` 立即非 0。

    这条用例是本腿「不是写死的 0」的自证——判据真身＝`code_driver_records()`。"""
    items = {cid: ([], "stub") for cid in cc.CARD_CODE_CIDS}
    items["jinja-template"] = (["plugins/bot_unified_runtime/render_card.py"], "stub")
    res = _stub_res(pages=[_page("plugins/bot_unified_runtime/render_card.py", "card-jinja")], t1=[])
    assert cc.code_driver_records(res) == {"plugins/bot_unified_runtime/render_card.py"}
    row = next(r for r in cc.code_face_ledger(res, {}, items) if r.cid == "jinja-template")
    assert (row.registered, row.driven, row.undriven) == (1, 1, 0)
    assert "已有驱动通道" in row.verdict


def test_poison_b_md_change_does_not_move_code_leg() -> None:
    """注毒③（简报 ④b）：改一枚既有 md（`per_cat_md` 的 persona 数变）⇒ **代码面三数纹丝不动**（两腿不串）。"""
    items = {cid: (["plugins/a/templates/x.html"], "stub") for cid in cc.CARD_CODE_CIDS}
    md_quiet = {"persona-knowledge": {"件数": 1, "已驱动": 0, "未驱动": 1}}
    md_moved = {"persona-knowledge": {"件数": 9, "已驱动": 5, "未驱动": 4}}
    code_of = lambda per: {r.cid: (r.registered, r.driven, r.undriven)
                           for r in cc.code_face_ledger(_stub_res(), per, items) if r.surface == "code"}
    assert code_of(md_quiet) == code_of(md_moved)
    per_rows = cc.code_face_ledger(_stub_res(), md_moved, items)
    pk = next(r for r in per_rows if r.cid == "persona-knowledge")
    assert (pk.registered, pk.driven, pk.undriven) == (9, 5, 4), "persona 族没吃 §二 同一支数 ⇒ 另算了第二本账"


def test_three_numbers_always_close() -> None:
    """三数闭合：每一行 `在册 == 已驱动 + 未驱动`（`render()` 里同一判据是硬断言）。"""
    items = {cid: ([f"plugins/a/templates/{cid}.html"], "stub") for cid in cc.CARD_CODE_CIDS}
    for row in cc.code_face_ledger(_stub_res(), {}, items):
        assert row.registered == row.driven + row.undriven, row.cid
    fams = cc.family_rollup(cc.code_face_ledger(_stub_res(), {}, items))
    assert all(v[0] == v[1] + v[2] for v in fams.values()), "族汇总与行不闭合"
    assert sum(v[0] for v in fams.values()) == sum(
        r.registered for r in cc.code_face_ledger(_stub_res(), {}, items)
    ), "族汇总重复计件（一类被算进两个族）"


def test_takeoff_keys_are_complete_and_ast_readers_stay_silent() -> None:
    """取数口面完整（六类一枚不少）＋ AST 读口对不存在文件/非字面量返回空表而非抛（不执行模块）。"""
    items = cc.code_surface_items()
    assert set(items) == set(cc.CARD_CODE_CIDS), "取数口漏类别＝代码面账本少一行（缩扫描面）"
    assert cc._ast_mapping_keys(Path(str(ROOT / "definitely_missing_file.py")), "_BUILDERS") == []
    assert cc._ast_copy_pool_entries(None) == []
    assert cc.rel_of("docs/x.md#生成物未当场复现字节等值") == "docs/x.md"


def test_real_tree_code_ledger_has_first_time_numbers() -> None:
    """真树现算：五族三数第一次成账，且**代码面在册件 > 0**（旧册对 fstring/copy-pool 报 0 件＝空账）。"""
    import spec_gates_census as sgc

    per_cat = {
        c.cid: {"件数": 0, "生成物": 0, "已驱动": 0, "未驱动": 0, "参数不齐": 0} for c in dt.CONTENT_CATEGORIES
    }
    rows = cc.code_face_ledger(sgc.compute(), per_cat, cc.code_surface_items())
    by_cid = {r.cid: r for r in rows}
    assert by_cid["fstring-card"].registered > 0, "fstring 名册取数口又哑了（literal_eval 抛 ValueError 的旧形态）"
    assert by_cid["incode-copy-pool"].registered > 0, "copy-pool 取数口回退成「现役取数口缺」空账"
    code_rows = [r for r in rows if r.surface == "code"]
    assert sum(r.registered for r in code_rows) > 0 and sum(r.driven for r in code_rows) == 0
    assert all(r.undriven == r.registered for r in code_rows), "代码面未驱动数≠在册数 ⇒ 驱动通道凭空出现，须复核"


# ===========================================================================
# 席 S127（2026-09-22）新增用例 —— §4③ **形态(b)**「生成脚本可复现字节」接入代码面。
# 全部为**新增**，未回改上方任何既有用例与断言（含 `test_real_tree_code_ledger_has_first_time_numbers`
# 那条「已驱动恒 0」快照——它是 S116 时代的真值，本席建通道后被合法击穿，
# 改不改由该锁的 owner/主代理裁定，见 SEAT-S127.md §冲突账）。
# 跑：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
#     ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_content_census_s116.py -q \
#     -p no:cacheprovider --basetemp="$TEMP/S127-2"
# ===========================================================================

def _all_stub_items(extra: dict[str, list[str]] | None = None) -> dict[str, tuple[list[str], str]]:
    items: dict[str, tuple[list[str], str]] = {cid: ([], "stub") for cid in cc.CARD_CODE_CIDS}
    for cid, its in (extra or {}).items():
        items[cid] = (its, "stub")
    return items


# ------------------------------------------------------------------ ① 通道登记与三腿实证
def test_b_channel_registry_contains_only_real_generators() -> None:
    """通道表**只收真有生成脚本的类**：现算盘上写方＝`command_catalog.py` 一条，别的类一概无源。

    这条是本席的正面锁：谁把 `copy-pool`/`config-field` 塞进 `CODE_B_CHANNELS` 而无生成口，它就红。"""
    assert set(cc.CODE_B_BY_CID) == {"help-topic"}, (
        f"形态(b) 通道表扩张到 {sorted(cc.CODE_B_BY_CID)}——须先证该族盘上有写其内容字节的脚本，"
        "否则＝把无源的说成有源（§0 六禁之发明数据源）"
    )
    for ch in cc.CODE_B_CHANNELS:
        assert (ROOT / ch.artifact).is_file(), f"通道 {ch.cid} 的生成物 {ch.artifact} 不在盘上"
        assert ch.command.startswith("python scripts/"), f"通道 {ch.cid} 未给唯一生成命令"


def test_b_channel_classes_without_generator_say_so_and_give_work_order() -> None:
    """无通道类：判「只能走形态(a)」＋**逐类有工单**（准绳一：绝不判「不适合模板化」）。"""
    items = cc.code_surface_items()
    no_channel = [cid for cid in items if cid not in cc.CODE_B_BY_CID]
    assert no_channel, "全类都有通道＝判据被放宽到无源，须复核"
    for cid in no_channel:
        v = cc.code_b_verdict(cid, items[cid][0])
        assert not v.channel and not v.driven and v.covered == 0, cid
        assert "只能走形态(a)" in v.reason and "不适合模板化" not in v.reason, (cid, v.reason)
        assert cid in cc.B_WORK_ORDERS, f"{cid} 无通道又无工单（欠 §必做④）"
        assert "provider" in cc.B_WORK_ORDERS[cid], f"{cid} 的工单没写谁提供"
    assert "不适合模板化" not in "".join(cc.B_WORK_ORDERS.values())


def test_real_tree_help_entry_passes_all_three_legs() -> None:
    """真树三腿实证：`help-topic` 的 (b) 判决逐腿为真、**逐件**全覆盖（78/78 由现算得来，不写死）。"""
    its, _src = cc.code_surface_items()["help-topic"]
    assert its, "在册件取数口哑了（本用例的前提）"
    v = cc.code_b_verdict("help-topic", its)
    assert v.idempotent, v.reason
    assert v.disk_equal, v.reason
    assert v.covered == v.total == len(its) and v.driven == frozenset(its), f"{v.covered}/{v.total} {v.reason}"


def test_real_tree_b_leg_merges_into_three_numbers_and_closes() -> None:
    """合并点唯一：真树 `code_face_ledger` 里 help-entry 三数由 `0 → 全驱动`，且每行仍闭合。"""
    import spec_gates_census as sgc

    per_cat = {
        c.cid: {"件数": 0, "生成物": 0, "已驱动": 0, "未驱动": 0, "参数不齐": 0} for c in dt.CONTENT_CATEGORIES
    }
    rows = cc.code_face_ledger(sgc.compute(), per_cat, cc.code_surface_items())
    by_cid = {r.cid: r for r in rows}
    ht = by_cid["help-topic"]
    assert (ht.registered, ht.driven, ht.undriven) == (ht.registered, ht.registered, 0), "help-entry 未走 (b)"
    assert (ht.driven_a, ht.driven_b) == (0, ht.registered), "(b) 被记成了 (a) 腿 ⇒ 两腿混淆"
    for r in rows:
        assert r.registered == r.driven + r.undriven, r.cid
        assert r.driven == r.driven_a + r.driven_b, r.cid
    zeroed = {cid: r for cid, r in by_cid.items() if cid != "help-topic"}
    assert all(r.driven_b == 0 for r in zeroed.values()), "无通道类凭空长出 (b) 驱动"


# ------------------------------------------------------------------ ② 两腿不串：甲账大小不动
def test_b_leg_never_moves_the_md_books() -> None:
    """**甲账不变自证**（简报②）：把 (b) 通道清空 vs 全开，两本账与换算式各项**逐键相等**。"""
    import spec_gates_census as sgc

    res = sgc.compute()
    with_ch = cc.books(res)
    saved = cc.CODE_B_BY_CID
    try:
        cc.CODE_B_BY_CID = {}
        without_ch = cc.books(res)
    finally:
        cc.CODE_B_BY_CID = saved
    assert with_ch == without_ch, "形态(b) 腿串进了 md 面两本账（两把尺互相污染）"
    ok, msg = cc.reconcile_books(with_ch)
    assert ok, msg


def test_poison_b2_md_face_numbers_ignore_code_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（沿用 S116 注毒 b 的形状）：给 md 腿换个数 ⇒ 代码面三数与 (b) 判决纹丝不动。"""
    items = _all_stub_items({"help-topic": ["plugins/e.py::_HELP_ENTRIES::聊天"]})
    code_only = lambda per: {
        r.cid: (r.registered, r.driven, r.driven_b)
        for r in cc.code_face_ledger(_stub_res(), per, items)
        if r.surface == "code"
    }
    before = code_only({})
    md_moved = {"persona-knowledge": {"件数": 9, "已驱动": 5, "未驱动": 4}}
    after = code_only(md_moved)
    assert before == after, "md 腿一动就污染代码腿 ⇒ 两本账判据不同源"
    monkeypatch.setitem(cc.CODE_B_BY_CID, "incode-copy-pool", cc.CODE_B_BY_CID["help-topic"])
    assert "incode-copy-pool" in cc.CODE_B_BY_CID, "注毒未生效（monkeypatch 打空）"


# ------------------------------------------------------------------ ③ 三发反向注毒
def test_poison_a_non_idempotent_generator_is_undriven() -> None:
    """注毒 a（简报③a）：让该族生成口**产出不幂等** ⇒ 判未驱动（且点名原因）。"""
    its, _src = cc.code_surface_items()["help-topic"]
    ch = cc.CODE_B_BY_CID["help-topic"]
    fake = dataclasses.replace(ch, produce=lambda: ("## 聊天\nv1\n", "## 聊天\nv2\n"))
    try:
        cc.CODE_B_BY_CID["help-topic"] = fake
        v = cc.code_b_verdict("help-topic", its)
        rows = cc.code_face_ledger(_stub_res(), {}, _all_stub_items({"help-topic": its}))
        assert not v.idempotent and not v.driven and "不幂等" in v.reason, v.reason
        assert next(r for r in rows if r.cid == "help-topic").undriven == len(its)
    finally:
        cc.CODE_B_BY_CID["help-topic"] = ch


def test_poison_b_item_without_anchor_goes_to_undriven_book() -> None:
    """注毒 b（简报③b）：造一枚**不在生成物里成节**的代码件 ⇒ 必进未驱动账（逐件，不按族蒙）。"""
    its, _src = cc.code_surface_items()["help-topic"]
    ghost = f"{cc.ECHO_PY}::_HELP_ENTRIES::幽灵主题ZZZ"
    v = cc.code_b_verdict("help-topic", [*its, ghost])
    assert ghost not in v.driven and v.covered == len(its) and v.total == len(its) + 1, v.reason
    assert "无锚点" in v.reason
    rows = cc.code_face_ledger(_stub_res(), {}, _all_stub_items({"help-topic": [*its, ghost]}))
    ht = next(r for r in rows if r.cid == "help-topic")
    assert (ht.registered, ht.driven, ht.undriven) == (len(its) + 1, len(its), 1), "无锚件被算成已驱动"


def test_poison_c_channel_less_family_cannot_be_forced_into_b() -> None:
    """注毒 c（简报③c，**本席最重要一发**）：把一枚通道硬挂到**没有生成脚本**的族 ⇒ 必红。

    两形各注一发：c1 借用 help-topic 的产物（锚点与该族件名毫不相干）；
    c2 指向盘上根本不存在产物的假通道（取数失败 fail-closed）。"""
    pool, _src = cc.code_surface_items()["incode-copy-pool"]
    assert pool, "copy-pool 取数口哑了（本发前提）"
    real = cc.CODE_B_BY_CID["help-topic"]
    saved = dict(cc.CODE_B_BY_CID)
    try:
        cc.CODE_B_BY_CID["incode-copy-pool"] = real
        v1 = cc.code_b_verdict("incode-copy-pool", pool)
        assert not v1.driven and v1.covered == 0, f"无源族被 (b) 认账了：{v1.reason}"
        assert "无锚点" in v1.reason, v1.reason

        cc.CODE_B_BY_CID["incode-copy-pool"] = dataclasses.replace(
            real, artifact="definitely/not/a/real/artifact.md"
        )
        v2 = cc.code_b_verdict("incode-copy-pool", pool)
        assert not v2.driven and not v2.disk_equal and "不可读" in v2.reason, v2.reason
    finally:
        cc.CODE_B_BY_CID.clear()
        cc.CODE_B_BY_CID.update(saved)
    assert set(cc.CODE_B_BY_CID) == set(saved), "注毒后通道表没还原（污染真树判决）"
    assert not cc.code_b_verdict("incode-copy-pool", pool).driven, "还原后仍被认账"


def test_poison_d_generator_exception_fails_closed() -> None:
    """注毒 d（加发）：生成口抛异常 ⇒ fail-closed 判未驱动并点名，绝不退化成旧免检行为。"""
    its, _src = cc.code_surface_items()["help-topic"]
    ch = cc.CODE_B_BY_CID["help-topic"]

    def boom() -> tuple[str, str]:
        raise RuntimeError("生成口挂了")

    try:
        cc.CODE_B_BY_CID["help-topic"] = dataclasses.replace(ch, produce=boom)
        v = cc.code_b_verdict("help-topic", its)
        assert not v.driven and "生成口不可用" in v.reason and "RuntimeError" in v.reason, v.reason
    finally:
        cc.CODE_B_BY_CID["help-topic"] = ch
    assert cc.code_b_verdict("help-topic", its).driven, "还原后判决没恢复"


def test_poison_e_stale_artifact_is_not_driven() -> None:
    """注毒 e（加发）：盘上产物**过期**（与生成字节不等）⇒ 判未驱动，与 md 面同形同判。"""
    its, _src = cc.code_surface_items()["help-topic"]
    ch = cc.CODE_B_BY_CID["help-topic"]
    stale = dataclasses.replace(ch, artifact="docs/README.md")
    cc.CODE_B_BY_CID["help-topic"] = stale
    try:
        v = cc.code_b_verdict("help-topic", its)
        assert v.idempotent and not v.disk_equal and not v.driven, v.reason
        assert "未当场复现" in v.reason, v.reason
    finally:
        cc.CODE_B_BY_CID["help-topic"] = ch


# ------------------------------------------------------------------ ④ 册面文本锁
def test_census_md_carries_b_channel_evidence_and_work_orders() -> None:
    """盘上册必须带 §二之三（通道表＋工单表）与两形态分解——防散文回退成「只有 (a) 一条道」。"""
    text = _CENSUS_MD.read_text(encoding="utf-8")
    assert "### 二之三、代码件形态(b) 通道与幂等实证" in text
    assert "(b) 达标：两次生成字节等值 · 盘上当场复现 · 逐件锚点全命中" in text
    assert "无生成通道 ⇒ 该类只能走形态(a)" in text
    assert "最小改造工单" in text and "provider" in text
    assert "其中(a)" in text and "其中(b)" in text, "三数表未分解两形态 ⇒ 看不出驱动从哪来"
    assert "绝不判「不适合模板化」" in text and "只判「须换机制」" in text, "准绳一的禁令从册上消失了"
    # 逐行判据不许出现被禁的判决（整册散文里那句是**禁令本身**，不能拿全文包含当违规）
    for fr in cc.code_face_ledger(
        _stub_res(), {}, {cid: ([f"plugins/a::{cid}"], "stub") for cid in cc.CARD_CODE_CIDS}
    ):
        assert "不适合模板化" not in fr.verdict, (fr.cid, fr.verdict)
    assert cc.BOOK_CENSUS in text and cc.BOOK_WRITER in text, "甲乙两账名被改掉了（S116 的锁不许回潮）"


# ===========================================================================
# 席 S156（2026-09-22）**追加**用例 —— 全量清点重生成 + 交付口径钉成文字 + 两条 fail-closed 腿。
# 全部为新增：上方 S116/S127 的既有用例与断言**一字未改**（含钉 `BOOK_CONVERSION` 简式的那枚锁）。
# 跑：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
#     ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_content_census_s116.py -q \
#     -p no:cacheprovider --basetemp="$TEMP/S156-1"
# ===========================================================================

def _zero_writer() -> dict[str, int]:
    return {"pages": 0, "driven": 0, cc.BOOK_WRITER: 0, "schema_errors": 0}


def test_s156_full_conversion_formula_is_the_one_enforced() -> None:
    """**简式与全式的对齐锁**：`reconcile_books()` 执法的是含 `- MISMATCH` 的全式；
    `MISMATCH≠0` 时简式会冒充对平 ⇒ 本席新增的 `BOOK_CONVERSION_FULL` 必须与执法式同项。"""
    assert cc.BOOK_CONVERSION_FULL.endswith("- MISMATCH")
    assert cc.BOOK_CONVERSION == f"{cc.BOOK_WRITER} = {cc.BOOK_CENSUS} + MECH_B + TEMPLATE_SRC"
    base = {
        cc.BOOK_CENSUS: 10, cc.BOOK_WRITER: 32, "MECH_B": 0, "TEMPLATE_SRC": 22, "MISMATCH": 0,
    }
    ok, msg = cc.reconcile_books(base)
    assert ok and "MISMATCH=0" in msg, msg
    shifted = dict(base, **{cc.BOOK_WRITER: 31, "MISMATCH": 1})
    ok2, msg2 = cc.reconcile_books(shifted)
    assert ok2, msg2  # 31 == 10 + 0 + 22 - 1
    assert not cc.reconcile_books(dict(base, **{cc.BOOK_WRITER: 31}))[0], "少减 MISMATCH 也算对平 ⇒ 全式没在执法"


@pytest.mark.parametrize("key", ["t1", "b_ok", "mismatch", "pages"])
def test_s156_missing_component_fails_closed(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """注毒（简报 ④a／必做③）：换算式任一分量**缺键** ⇒ `books()` 必抛（旧形态静默折成 0 冒充对平）。"""
    monkeypatch.setattr(cc, "writer_book", _zero_writer)
    res = _stub_res()
    del res[key]
    with pytest.raises(LookupError, match=key):
        cc.books(res)


def test_s156_generated_all_is_required_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """`generated_all` 同权：取数口少这一键 ⇒ 代码面 (a) 腿不再拿"空集合"当"没有生成物"。"""
    monkeypatch.setattr(cc, "writer_book", _zero_writer)
    res = _stub_res()
    del res["generated_all"]
    with pytest.raises(LookupError, match="generated_all"):
        cc.code_driver_records(res)


def test_s156_contemporaneity_separates_drift_from_caliber() -> None:
    """同刻性与换算式**分开点名**：页数对不上＝「取数时刻之差」（本席实跑撞见的差 1 那族），
    只有它俩都过才是可交付快照；口径差不能被同刻性掩盖。"""
    drift = {
        cc.BOOK_CENSUS: 10, cc.BOOK_WRITER: 33, "MECH_B": 0, "TEMPLATE_SRC": 22, "MISMATCH": 0,
        "census_pages": 100, "writer_pages": 123,
    }
    same, smsg = cc.contemporaneity(drift)
    assert not same and "不同刻" in smsg, smsg
    assert not cc.reconcile_books(drift)[0], "差 1 枚的采样被当成对平"
    coherent = dict(drift, **{cc.BOOK_WRITER: 32, "writer_pages": 122})
    assert cc.contemporaneity(coherent)[0] and cc.reconcile_books(coherent)[0]


def test_s156_snapshot_refuses_after_bounded_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（简报 ④b）：换算式恒不成立 ⇒ `snapshot()` 有限次重采后**抛**、`render()` 随之拒生成。"""
    monkeypatch.setattr(cc.sgc, "compute", lambda *a, **k: _stub_res())
    monkeypatch.setattr(
        cc, "writer_book", lambda: {"pages": 999, "driven": 0, cc.BOOK_WRITER: 999, "schema_errors": 0}
    )
    assert cc.SNAPSHOT_ATTEMPTS == 3, "重采上限被改 ⇒ 本用例的判据要跟着复核"
    with pytest.raises(AssertionError) as ei:
        cc.snapshot()
    msg = str(ei.value)
    assert "拒绝生成册" in msg and "换算式不成立" in msg and "不同刻" in msg, msg
    with pytest.raises(AssertionError, match="换算式不成立"):
        cc.render()


def test_s156_snapshot_accepts_a_later_coherent_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向自证「重采不是重试到绿」：第 1 次采样两腿都不成立 ⇒ 弃；第 2 次成立 ⇒ 收，并报出第几次。"""
    import doc_template_sync as dts

    tpl = len(list(dts.TEMPLATE_DIR.glob("*.md")))
    res = _stub_res(t1=[])
    state = {"n": 0}

    def fake_writer() -> dict[str, int]:
        state["n"] += 1
        extra = 1 if state["n"] == 1 else 0  # 第 1 次：乙账多看到一枚 ⇒ 不同刻
        pages = len(res["pages"]) + tpl + extra
        driven = len(res["pages"]) - len(res["t1"])
        return {"pages": pages, "driven": driven, cc.BOOK_WRITER: pages - driven, "schema_errors": 0}

    monkeypatch.setattr(cc.sgc, "compute", lambda *a, **k: res)
    monkeypatch.setattr(cc, "writer_book", fake_writer)
    assert cc.SNAPSHOT_ATTEMPTS >= 2
    _res, bk, msg = cc.snapshot()
    assert state["n"] == 2, f"没有走到第 2 次采样（实际 {state['n']}）⇒ 第 1 次就被放行了"
    assert bk[cc.BOOK_WRITER] == bk[cc.BOOK_CENSUS] + bk["MECH_B"] + bk["TEMPLATE_SRC"] - bk["MISMATCH"]
    assert "第 2/3 次采样" in msg, msg


def test_s156_real_tree_snapshot_is_coherent() -> None:
    """真树现算：一次自洽快照 ⇒ 同刻性＋换算式同时成立，且甲账与门 G-T1 逐位相等（C2＝C4 的正面锁）。"""
    res, bk, msg = cc.snapshot()
    assert cc.contemporaneity(bk)[0] and cc.reconcile_books(bk)[0], msg
    assert bk[cc.BOOK_CENSUS] == len(res["t1"]) == len(cc._res_names(res, "t1"))
    assert bk["MECH_B"] > 0 and bk["TEMPLATE_SRC"] > 0, "换算项塌成 0 ⇒ 两本账会被误当成同一数"


def test_s156_census_md_pins_delivery_caliber() -> None:
    """盘上册把「交付用哪个数」钉成文字：C2/C4 各一行、乙账明写不作交付值、三个分量逐枚带现值。"""
    text = _CENSUS_MD.read_text(encoding="utf-8")
    assert "## 〇、交付口径" in text, "交付口径又变回散文里一句顺带话（S156 的锁不许回潮）"
    head = text.split("## 一、口径")[0]
    assert "**C2** G-T1 未模板驱动" in head and "**C4** CENSUS 未模板驱动" in head
    assert "**不作交付值**" in head, "乙账被写成可交付 ⇒ 双重计账回潮"
    assert cc.BOOK_CONVERSION_FULL in head and cc.BOOK_CONVERSION in head
    for term in ("MECH_B=", "TEMPLATE_SRC=", "MISMATCH="):
        assert term in head, f"分量 {term} 未在册面给出"
    assert "缺键即抛" in head and "同刻性自证" in head, "两条 fail-closed 腿从册面消失"
    assert "简式与全式的对齐" in head and "一律以全式为准" in head, "两名两式的对齐句丢了"


# ===========================================================================
# 席 S169（2026-09-22）**追加**用例 —— `config-field`/`incode-copy-pool` 两族真身判据 + 三发注毒。
# 全部为新增：上方 S116/S127/S156 的既有用例与断言一字未改。
# 判决结论（与席 S127 同向、按现算复核）：两族今日**无可复现字节的生成通道**——
#   · config-field：键名/类型/缺省可由 `config.py` 派生，但逐键说明是人写散文
#     （`config.py` 现算 `description=` 0 命中；catalog 两枚机器段标记现算 0 命中）；
#   · incode-copy-pool：成员原文可由 AST 派生，但盘上无 md 产物、无唯一写命令、无登记表。
# ⇒ 判「只能走形态(a)」，工单已按现算坐标更新；本组用例把「硬走 (b) 必红」的三发钉死。
# 跑：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
#     ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_content_census_s116.py -q \
#     -p no:cacheprovider --basetemp="$TEMP/S169-1"
# ===========================================================================

def _s169_fake_channel(cid: str, artifact: str, produce, anchor) -> cc.ByteChannel:
    return cc.ByteChannel(
        cid=cid,
        command="python scripts/does_not_exist.py --check（注毒假通道，盘上无此写方）",
        artifact=artifact,
        produce=produce,
        anchor=anchor,
        param_source="s169-poison",
    )


def test_s169_config_field_true_body_is_config_py_fields_not_catalog_lines() -> None:
    """必做①（可复算判据）：config-field 在册件全部出自 `board_doc_sync.load_config_fields()`
    （＝`config.py` 的 pydantic 字段正则），逐件形如 `config.py::bot_*`、去重且排序——
    真身是**字段全集**，不是 catalog 行。取下界 400 与登记门同形，防取数口哑成空账。"""
    import board_doc_sync as bds

    its, source = cc.code_surface_items()["config-field"]
    assert source == "board_doc_sync.load_config_fields()"
    fields = bds.load_config_fields()
    assert its == [f"{cc.CONFIG_PY}::{f}" for f in fields], "在册件与取数口现算不再逐位同源 ⇒ 两本账"
    assert len(fields) == len(set(fields)) == len(its) >= 400
    assert all(i.split("::", 1)[1].startswith("bot_") for i in its)
    assert fields == sorted(fields)


def test_s169_copy_pool_true_body_lives_in_ast_read_of_code_home() -> None:
    """必做③（池子真身）：在册件＝注册 `code_home`（user_copy.py）模块级容器的字符串成员，
    取数口＝`_ast_copy_pool_entries()`（AST 读、不执行模块）；`code_home` 之外的池散布是
    **注册表（公共只读面）事项**，已列工单与本席报告 §公共件交回，本锁只钉现判据口径。"""
    cat = dt.CATEGORIES_BY_ID["incode-copy-pool"]
    its, _src = cc.code_surface_items()["incode-copy-pool"]
    assert its, "copy-pool 取数口哑了（本席判决的前提）"
    assert all(i.startswith(f"{cat.code_home}::") for i in its)
    assert cat.code_home.endswith("user_copy.py")
    # 登记表之问：模块里没有任何「变量名→用途」的结构化登记 ⇒ 只能整枚挂未驱动，不许蒙。
    assert "无独立登记表" in cc.B_WORK_ORDERS["incode-copy-pool"]


def test_s169_no_channel_for_both_families_and_verdict_says_form_a() -> None:
    """方向自查（必做④的前半）：两族今日不在 `CODE_B_CHANNELS`，判决逐枚「只能走形态(a)」——
    这条是「本席没有偷偷开通道」的正面锁。"""
    items = cc.code_surface_items()
    for cid in ("config-field", "incode-copy-pool"):
        assert cid not in cc.CODE_B_BY_CID, f"{cid} 被无源登记进 (b) 通道表（§0 六禁·发明数据源）"
        v = cc.code_b_verdict(cid, items[cid][0])
        assert not v.channel and not v.driven and "只能走形态(a)" in v.reason, (cid, v.reason)
        assert items[cid][0], cid  # 前提：两族都有真件在账，不是空跑


def test_s169_poison_a_non_idempotent_channel_undrives_whole_family() -> None:
    """注毒 a（必做⑤a）：给 config-field 硬挂一枚**不幂等**通道 ⇒ 判「不幂等」、全族进未驱动，
    三数仍闭合。幂等证明是 (b) 的第一条腿，对无源族同样有牙。"""
    its, _src = cc.code_surface_items()["config-field"]
    fake = _s169_fake_channel(
        "config-field",
        "docs/config-catalog-full.md",
        lambda: ("BOT_X v1\n", "BOT_Y v2\n"),
        lambda item: f"| `{item.split('::', 1)[1].upper()}`",
    )
    saved = dict(cc.CODE_B_BY_CID)
    try:
        cc.CODE_B_BY_CID["config-field"] = fake
        v = cc.code_b_verdict("config-field", its)
        assert not v.idempotent and not v.driven and "不幂等" in v.reason, v.reason
        rows = cc.code_face_ledger(_stub_res(), {}, _all_stub_items({"config-field": its}))
        row = next(r for r in rows if r.cid == "config-field")
        assert (row.registered, row.driven, row.undriven) == (len(its), 0, len(its))
        assert row.registered == row.driven + row.undriven
    finally:
        cc.CODE_B_BY_CID.clear()
        cc.CODE_B_BY_CID.update(saved)
    assert "config-field" not in cc.CODE_B_BY_CID, "注毒后通道表没还原"


def test_s169_poison_b_derivable_skeleton_is_not_the_artifact() -> None:
    """注毒 b（必做⑤b，S127 那发的同型续作·**最重要一发**）：给 config-field 挂一枚
    「可由 config.py 派生骨架」的通道（键名/类型/缺省全机械可产），产物指真 catalog
    ⇒ 骨架字节与盘上人写散文永不相等 ⇒ 判「未当场复现」、全件仍挂未驱动。
    **拿不到可复现通道就判只能走 (a)**——这条锁保证「派生得出清单」冒充不了「复现得出产物」。"""
    import board_doc_sync as bds

    its, _src = cc.code_surface_items()["config-field"]
    skeleton = "\n".join(f"| {f.upper()} | 派生骨架列 |" for f in bds.load_config_fields()) + "\n"
    fake = _s169_fake_channel(
        "config-field",
        "docs/config-catalog-full.md",
        lambda: (skeleton, skeleton),
        lambda item: f"| {item.split('::', 1)[1].upper()} | 派生骨架列 |",
    )
    saved = dict(cc.CODE_B_BY_CID)
    try:
        cc.CODE_B_BY_CID["config-field"] = fake
        v = cc.code_b_verdict("config-field", its)
        assert v.idempotent, "骨架通道连跑都不等值？先查 produce 实现"
        assert not v.disk_equal and not v.driven, f"派生骨架冒充了人写产物：{v.reason}"
        assert "未当场复现" in v.reason, v.reason
    finally:
        cc.CODE_B_BY_CID.clear()
        cc.CODE_B_BY_CID.update(saved)
    base = cc.code_b_verdict("config-field", its)
    assert not base.channel and not base.driven, "还原后 baseline 判决没恢复"


def test_s169_poison_c_stale_pool_artifact_undriven_at_once() -> None:
    """注毒 c（必做⑤c）：假想 copy-pool 的「池→md」生成口已存在、连跑等值，但盘上产物过期
    （指向一枚内容不等的在册文件来同形复现「过期」形状）⇒ 当场判未驱动；还原后回到无通道判决。"""
    its, _src = cc.code_surface_items()["incode-copy-pool"]
    fresh = "\n".join(f"## {i.rsplit('::', 1)[-1]} 段（注毒形状）" for i in its) + "\n"
    fake = _s169_fake_channel(
        "incode-copy-pool",
        "docs/README.md",
        lambda: (fresh, fresh),
        lambda item: f"## {item.rsplit('::', 1)[-1]} 段（注毒形状）",
    )
    saved = dict(cc.CODE_B_BY_CID)
    try:
        cc.CODE_B_BY_CID["incode-copy-pool"] = fake
        v = cc.code_b_verdict("incode-copy-pool", its)
        assert v.idempotent and not v.disk_equal and not v.driven, v.reason
        assert "未当场复现" in v.reason, v.reason
    finally:
        cc.CODE_B_BY_CID.clear()
        cc.CODE_B_BY_CID.update(saved)
    assert not cc.code_b_verdict("incode-copy-pool", its).driven


def test_s169_work_orders_point_at_file_symbol_coordinates() -> None:
    """必做②末段：两族工单必须点到**现算核实过的 `文件:符号`**，判 (a) 才不糊——
    config-field 点名取数口 / `Field(description=` / settings 两表 / 机器段；
    copy-pool 点名 user_copy.py / AST 取数口 / 交回公共面的注册表工单 + provider。"""
    cf = cc.B_WORK_ORDERS["config-field"]
    for token in (
        "board_doc_sync.load_config_fields",
        "Field(description=",
        "SETTABLE_KEYS",
        "RESTART_REQUIRED_KEYS",
        "机器段",
        "KNOWN_MISSING",
        "provider",
    ):
        assert token in cf, (token, cf[:120])
    cp = cc.B_WORK_ORDERS["incode-copy-pool"]
    for token in ("user_copy.py", "_ast_copy_pool_entries", "doc_templates.py", "provider"):
        assert token in cp, (token, cp[:120])
    for text in (cf, cp):
        assert "不适合模板化" not in text, "工单文案回潮了被禁的判决（准绳一）"
