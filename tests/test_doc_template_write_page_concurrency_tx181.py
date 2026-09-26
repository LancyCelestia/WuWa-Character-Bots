"""`write_page` fail-closed 写盘口的回归锁（席 TX181，2026-09-23）。

判据真身住 `scripts/doc_template_sync.py::write_page`。TX179 实测（快照 sha
`ec4edc9729189f4f`）：旧版 `new` 与 `before` 都取自**内存陈旧态**、落盘直盖盘上真实态
⇒ 并发写者刚写的字节被静默吃掉而写后 `check_page` 照绿（其 T5：返回 True、他席正文没了、
违规码空）；且写后差分**单向**，让违规「消失」的写永远放行（其 T4：`AUTO_MISSING` 被洗成
全绿、`BEGIN` 裸计数 1→2）。全仓对这条腿**零锁**（TX179 §4.4：删掉守卫六行套件照绿）。

本件四发注毒（简报《TX181》④，全部 `tmp_path`，**源码树零写入**）：
①陈旧态覆盖必抛（盘上被他席改过 ⇒ `PageConcurrentMutation`、他席字节原样保留）；
②盘上一致才写（等值页照常驱动；采集快照一旦被自家写盘作废后复用 ⇒ 同口径拒写）；
③写后读回不等即回滚（读回被竞写污染 ⇒ 字节等值腿独立击杀，违规差分两方向全绿也拒收）；
④「违规消失形」必被拦（可见孤儿标记页上再叠一段、差分为负 ⇒ `MARKER_LAUNDERING` 回滚）。

判据口径照实写死一处（本席与简报的差，详见 SEAT-TX181.md §4）：第④腿的「标记份数」按
**围栏外可见**标记计（与判据/注入口同尺 `_human_body_position_view`）——T4 真页
`HEADER-RECIPE-OTHERS.md` 的成对示例在围栏内，裸计数 1→2 的首注入正是批 55
`test_doc_template_fence_zone_tx171.py::test_write_passes_after_check_and_is_idempotent`
钉为合法的正解，按裸计数执法会当场打红那条在册锁并永拒教程页挂驱动；可见形
（孤儿/双真段上叠段）才是「凭空洗白」的真身，用例⑤把这个边界本身钉住。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_doc_template_write_page_concurrency_tx181.py \\
      -p no:cacheprovider --basetemp=<私有> -q
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Callable
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

B = dts.TPL_AUTO_BEGIN
TPL = "tx181-tpl"
SCHEMAS = {TPL: dts.parse_schema_text(
    "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
    "- note | text | literal | req | nonempty\n"
    "@schema:END -->\n<!-- TEMPLATE-AUTO:BEGIN -->\n"
    "- {{fact:note}}\n<!-- TEMPLATE-AUTO:END -->\n",
    TPL,
)}
FM = "---\ntemplate: tx181-tpl\nparams:\n  note: N-181\n---\n"
NEEDLE = "- N-181"
#: 无任何机器段标记的合规页（首注入的干净形状）。
PAGE_PLAIN = FM + "\n# 夹具\n\n## 交付\n\n- 事件一\n\n## 自报\n\n- 收尾\n"


def _page(tmp_path: Path, name: str, mem_text: str) -> tuple[dts.PageInfo, Path]:  # type: ignore[name-defined]
    """把 `mem_text` 落盘并造一个「内存态=盘上态」的采集快照（正常采集形状）。"""
    f = tmp_path / name
    f.write_text(mem_text, encoding="utf-8", newline="\n")
    pg = dts.PageInfo(
        rel=f".superpowers/sdd/2026-09-22-taxonomy/{name}",
        path=f, text=mem_text, category="seat-report",
    )
    pg.fm = dts.parse_front_matter(mem_text)
    assert pg.fm is not None
    return pg, f


# ---------------------------------------------------------- ① 陈旧态覆盖必抛（T5 病根）
def test_stale_memory_refuses_write_and_preserves_concurrent_author_bytes(
    tmp_path: Path,
) -> None:
    """采集后他席改了盘上态 ⇒ 拒写点名两态 sha，**他席字节一个都不许丢**（旧版在此覆盖并返回 True）。"""
    pg, f = _page(tmp_path, "SEAT-TX181A.md", PAGE_PLAIN)
    concurrent = PAGE_PLAIN + "\n他席正文：这一行绝不该被陈旧快照吃掉\n"
    f.write_text(concurrent, encoding="utf-8", newline="\n")  # 模拟采集后竞写
    before_bytes = f.read_bytes()
    with pytest.raises(dts.PageConcurrentMutation) as caught:
        dts.write_page(pg, SCHEMAS)
    assert f.read_bytes() == before_bytes, "拒写却没保住盘上态"
    assert "他席正文" in f.read_text(encoding="utf-8"), "T5 同型：并发写者字节被吃"
    assert dts.TPL_AUTO_BEGIN not in f.read_text(encoding="utf-8"), "拒写页却被注了机器段"
    msg = str(caught.value)
    assert "SEAT-TX181A.md" in msg, "未点名页"
    shas = re.findall(r"\b[0-9a-f]{16}\b", msg)
    assert len(shas) >= 2, f"未点名两态 sha256[:16]：{msg}"
    assert caught.value.rel.endswith("SEAT-TX181A.md")


# ---------------------------------------------------------- ② 盘上一致才写 + 快照作废
def test_disk_consistent_page_writes_normally_and_reused_snapshot_is_refused(
    tmp_path: Path,
) -> None:
    """盘=内存 ⇒ 正常驱动；驱动成功后**旧 PageInfo 的内存快照即作废**，复用同一快照再驱动 ⇒ 拒写。"""
    pg, f = _page(tmp_path, "SEAT-TX181B.md", PAGE_PLAIN)
    assert dts.write_page(pg, SCHEMAS) is True
    after = f.read_bytes()
    assert NEEDLE.encode("utf-8") in after and B.encode("utf-8") in after
    disk_text = after.decode("utf-8")
    fm = dts.parse_front_matter(disk_text)
    assert fm is not None
    assert dts.check_page(
        SCHEMAS[TPL], disk_text, fm, dts.PageCtx(rel=pg.rel, body_no_fm=disk_text)
    ) == [], "写后盘上态应全绿"
    with pytest.raises(dts.PageConcurrentMutation):
        dts.write_page(pg, SCHEMAS)  # pg.text 还是写前快照 ⇒ 陈旧，必抛（不许拿内存副本凑）
    assert f.read_bytes() == after, "复用陈旧快照那次写动了盘上字节"


# ---------------------------------------------------------- ③ 写后读回不等 ⇒ 回滚
def test_readback_mismatch_rolls_back_even_when_violation_diff_would_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """写后读回被竞写污染（污染体**违规差分全绿**）⇒ 只有字节等值腿能杀——独立击杀力锁。

    若只留 check_page 差分：读回内容把一行正文换了字，codes 与写入体完全同集
    （introduced 空、vanished 空、标记份数不变）⇒ 三腿全瞎、返回 True 谎称内容在盘。
    """
    pg, f = _page(tmp_path, "SEAT-TX181C.md", PAGE_PLAIN)
    original = f.read_bytes()
    real_rb: Callable[[Path], bytes] = Path.read_bytes
    state = {"reads": 0}

    def fake_rb(self: Path) -> bytes:
        data = real_rb(self)
        state["reads"] += 1
        if state["reads"] >= 2:  # 写后读回那次：他席竞写形覆盖
            return data.replace("收尾".encode(), "尾收".encode())
        return data

    monkeypatch.setattr(Path, "read_bytes", fake_rb)
    with pytest.raises(dts.PageConcurrentMutation) as caught:
        dts.write_page(pg, SCHEMAS)
    assert "写后读回" in caught.value.phase
    monkeypatch.undo()
    assert f.read_bytes() == original, "读回不等却没回滚到写前盘上态"
    assert NEEDLE.encode("utf-8") not in original, "夹具前提变了：写前盘上不该已有机器段"


# ---------------------------------------------------------- ④ 违规消失形必被拦（T4 族）
def test_vanishing_violation_with_visible_marker_stacking_rolls_back(
    tmp_path: Path,
) -> None:
    """盘上已有一枚**可见**落单 BEGIN（无配对）时再注入一段 ⇒ 差分为负 + 标记份数不可解释变化
    ⇒ `MARKER_LAUNDERING` 回滚。夹具保证新增腿与洗白腿彼此独立：写后 zone 配对干净、
    `introduced` 必为空，能拦的只有本腿（旧版单向差分在此返回 True）。
    """
    text = FM + "\n# 夹具\n\n## 交付\n\n- 事件一\n" + B + "\n孤儿开启行\n\n## 自报\n\n- 收尾\n"
    pg, f = _page(tmp_path, "SEAT-TX181D.md", text)
    before = f.read_bytes()
    assert any(v.startswith("AUTO_MISSING") for v in dts.check_page(
        SCHEMAS[TPL], text, pg.fm, dts.PageCtx(rel=pg.rel, body_no_fm=text),
    )), "夹具前提：该页写前应带 AUTO_MISSING"
    with pytest.raises(dts.PageWriteRejected) as caught:
        dts.write_page(pg, SCHEMAS)
    items = caught.value.introduced
    assert any(v.startswith("MARKER_LAUNDERING") for v in items), items
    assert not any(v.startswith(("AUTO_DRIFT", "SECTION_", "AUTO_MISSING")) for v in items), \
        f"本腿不得替正向差分背锅：{items}"
    assert f.read_bytes() == before, "拒写却没回滚"
    assert "孤儿开启行" in f.read_text(encoding="utf-8"), "盘上原字被动"


# ---------------------------------------------------------- 边界正锁：围栏示例≠洗白
def test_fenced_example_first_injection_stays_drivable_under_two_way_ruler(
    tmp_path: Path,
) -> None:
    """**可见**标记 0→1 的首注入是唯一可解释形：裸计数 1→2（成对示例在围栏里）不得误杀。

    这正是 TX171 钉过的 `HEADER-RECIPE` 同型页。若把④腿按裸计数执法，本用例红、
    `test_doc_template_fence_zone_tx171.py::test_write_passes_after_check_and_is_idempotent`
    也红——教程/配方页就此永不可挂驱动（缩面罢工的另一头）。边界在此钉成用例。
    """
    example = "```text\n" + B + "\n" + dts.TPL_AUTO_NOTE + "\n\n- 示例行：改了也没人看\n" \
              + dts.TPL_AUTO_END + "\n```\n"
    text = FM + "\n# 夹具\n\n写法示例（整块是文档）：\n\n" + example \
             + "\n## 交付\n\n- 事件一\n\n## 自报\n\n- 收尾\n"
    assert text.count(B) == 1 and dts._visible_marker_counts(text) == (0, 0), \
        "夹具前提：裸标记 1 枚、可见 0 枚"
    pg, f = _page(tmp_path, "SEAT-TX181E.md", text)
    assert dts.write_page(pg, SCHEMAS) is True
    after = f.read_text(encoding="utf-8")
    assert "示例行" in after, "示例字节被动了＝破坏性改写没拦住"
    assert after.count(B) == 2, "机器段没注入（裸计数应 1→2）"
    assert dts._visible_marker_counts(after) == (1, 1), "可见标记应恰一对"
    fm = dts.parse_front_matter(after)
    assert fm is not None
    assert dts.check_page(
        SCHEMAS[TPL], after, fm, dts.PageCtx(rel=pg.rel, body_no_fm=after)
    ) == []


# ---------------------------------------------------------- CLI 记账（_drive 接线）
def test_main_write_accounts_concurrent_rejection_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--write` 撞 `PageConcurrentMutation` ⇒ 该页盘上态原样、stderr 点名、退出非零（绝不当已更新）。"""
    pg, f = _page(tmp_path, "SEAT-TX181F.md", PAGE_PLAIN)
    f.write_text(PAGE_PLAIN + "\n他席追加段\n", encoding="utf-8", newline="\n")
    before = f.read_bytes()
    # 历史台账类：前置不分流（face=page），直达 _drive；rel 用串名、path 落 tmp——真树零写入。
    pg.rel = "docs/HANDBOOK.md"
    pg.category = "handbook"
    monkeypatch.setattr(dts, "_collect", lambda root=None: ([pg], [], SCHEMAS))
    monkeypatch.setattr(dts, "_load_fact_vocab", lambda: {"聊天"})
    rc = dts.main(["--write"])
    err = capsys.readouterr().err
    assert rc != 0, "并发拒写仍返回 0＝记账假绿"
    # 点名以 PageInfo.rel 为准（本用例把 rel 改挂历史类以走直通分流），tmp 文件名另证零写入。
    assert "CONCURRENT_MUTATION" in err and "docs/HANDBOOK.md" in err, err
    assert "sha256[:16]=" in err, "未点名两态指纹"
    assert f.read_bytes() == before, "CLI 一轮后盘上态被动过"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
