"""围栏盲区余下四处根修 + 写后校验的常驻门与注毒自证（席 TX171，2026-09-23）。

判据真身住 `scripts/doc_template_sync.py`：本席把「机器段判定」与「剥围栏」归并成
**一次行走**（`_human_body_position_view`），`extract_auto_zone` / `_apply_block` /
`_human_body` 三处同吃这一支尺（旧版三处按**裸子串**认段 ⇒ 写在围栏里的
`TEMPLATE-AUTO` 示例串会被当成真机器段：`--check` 拿示例比对渲染结果、`--write` 把示例
**就地撕掉改写**）；`write_page` 由「改完就走」升成「写后立即 `check_page`、新增违规即回滚
原字节并抛 `PageWriteRejected`」。

全部喂内存页 + `tmp_path`，零触真树。`_legacy_*` 三件是**旧实现的逐字复刻**，只用来证明
注毒有杀伤力（改前该红、改后不红），不参与任何判据。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_doc_template_fence_zone_tx171.py \\
      -p no:cacheprovider --basetemp=<私有> -q
"""

from __future__ import annotations

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

B, E, NOTE = dts.TPL_AUTO_BEGIN, dts.TPL_AUTO_END, dts.TPL_AUTO_NOTE
TPL = "tx171-tpl"
SCHEMAS = {TPL: dts.parse_schema_text(
    "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
    "- seat_id | text | literal | req | nonempty\n"
    "- cls | text | auto:seat_class | req | any\n"
    "@schema:END -->\n<!-- TEMPLATE-AUTO:BEGIN -->\n"
    "- {{fact:seat_id}} / {{fact:cls}}\n<!-- TEMPLATE-AUTO:END -->\n",
    TPL,
)}
FM = f"---\ntemplate: {TPL}\nparams:\n  seat_id: T-171\n  cls: auto:seat_class\n---\n"


# --------------------------------------------------------------------------- 旧实现复刻
def _legacy_human_body(text: str) -> str:
    """TX171 改动**之前**的 `_human_body`（机器段判定排在剥围栏之前）。"""
    lines = text.splitlines()
    body_from = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        body_from = end + 1 if end else 0
    out, infence, in_auto = [], False, False
    for ln in lines[body_from:]:
        if ln.strip() == B:
            in_auto = True
            continue
        if ln.strip() == E:
            in_auto = False
            continue
        if in_auto:
            continue
        if dts._FENCE_RE.match(ln):
            infence = not infence
            continue
        if not infence:
            out.append(ln)
    return "\n".join(out)


def _legacy_extract_auto_zone(text: str) -> str | None:
    if B not in text or E not in text:
        return None
    return text.split(B, 1)[1].split(E, 1)[0]


def _legacy_apply_block(text: str, block: str) -> str:
    if B in text and E in text:
        head, rest = text.split(B, 1)
        _, tail = rest.split(E, 1)
        return f"{head}{block}{tail}"
    raise AssertionError("旧实现的插入分支不在本件复刻范围内")


# --------------------------------------------------------------------------- 夹具
def _values() -> dict[str, str]:
    fm = dts.parse_front_matter(FM)
    assert fm is not None
    values, viol = dts.resolve_params(SCHEMAS[TPL], fm, dts.PageCtx(rel="t/SEAT-TX171FIX.md", body_no_fm=FM))
    assert not viol, viol
    return values


def _block() -> str:
    return dts.render_page_text(SCHEMAS[TPL], _values())


def _needle() -> str:
    """本次渲染落进机器段的**那一行**（不硬编码 provider 派生值，免夹具与真身脱钩）。"""
    v = _values()
    return f"- {v['seat_id']} / {v['cls']}"


def _fenced_region(text: str) -> str:
    """第一处 ``` 围栏的整块字节（含开闭行）——示例区的逐等性判据取这里。"""
    i = text.index("```text")
    j = text.index("```", i + len("```text"))
    return text[i:j + 3]


#: 围栏里的**成对**示例段（教程/配方页常见形状），后跟真机器段与两节人写正文。
EXAMPLE_LINES = [
    "写法示例（整块都是文档，不是机器段）：",
    "",
    "```text",
    B,
    NOTE,
    "",
    "- 示例行：改了也没人看",
    E,
    "```",
]

PAGE_WITH_REAL_ZONE = "\n".join(
    [FM, "# 夹具", ""]
    + EXAMPLE_LINES
    + ["", B, NOTE, "", "- T-OLD / report", E, "", "## 交付", "", "- 事件一", "",
       "## 自报", "", "- 收尾", ""]
)

PAGE_WITHOUT_REAL_ZONE = "\n".join(
    [FM, "# 夹具", ""] + EXAMPLE_LINES + ["", "## 交付", "", "- 事件一", "", "## 自报", "", "- 收尾", ""]
)


def _page(path: Path, text: str) -> dts.PageInfo:  # type: ignore[name-defined]
    path.write_text(text, encoding="utf-8", newline="\n")
    pg = dts.PageInfo(
        rel=".superpowers/sdd/2026-09-22-taxonomy/" + path.name,
        path=path, text=text, category="seat-report")
    pg.fm = dts.parse_front_matter(text)
    assert pg.fm is not None
    return pg


# --------------------------------------------------------------------------- ① 判据同尺
def test_fenced_example_is_not_mistaken_for_the_real_zone() -> None:
    """成对示例先于真段：`extract_auto_zone` 必须返回**真段**，不是示例。"""
    zone = dts.extract_auto_zone(PAGE_WITH_REAL_ZONE)
    assert zone is not None and "T-OLD" in zone, zone
    assert "示例行" not in zone, "围栏里的示例被当成机器段 ⇒ 判据被劫持"
    # 杀伤力自证：旧实现返回的正是示例段
    legacy = _legacy_extract_auto_zone(PAGE_WITH_REAL_ZONE)
    assert legacy is not None and "示例行" in legacy, legacy


def test_example_only_page_has_no_zone_and_is_not_rewritten() -> None:
    """只有围栏示例、没有真段的页：判据＝无机器段；`_apply_block` 走插入，示例逐字节不动。"""
    assert dts.extract_auto_zone(PAGE_WITHOUT_REAL_ZONE) is None
    out = dts._apply_block(PAGE_WITHOUT_REAL_ZONE, _block())
    assert _fenced_region(out) == _fenced_region(PAGE_WITHOUT_REAL_ZONE), "示例区字节变了"
    assert _needle() in out, "真机器段没注进去"
    # 杀伤力自证：旧实现把示例段整块 replace 成渲染结果＝破坏性改写文档
    torn = _legacy_apply_block(PAGE_WITHOUT_REAL_ZONE, _block())
    assert "示例行" not in torn, "旧通路没撕示例 ⇒ 本用例的杀伤力前提变了，须重找形态"


def test_fenced_lone_begin_no_longer_swallow_the_rest_of_the_page() -> None:
    """顺序盲区：围栏里一枚落单 BEGIN 旧版会把后文整篇吞出人写视图（`infence` 卡死）。"""
    text = FM + "# 夹具\n\n```text\n" + B + "\n- 示例\n```\n\n## 交付\n\n- 事件\n"
    assert "## 交付" in dts._human_body(text), "真小节被围栏内示例吃掉"
    assert "## 交付" not in _legacy_human_body(text), "杀伤力前提丢了：旧版本应吞掉"
    heads = [m.group(1) for m in dts._H2_RE.finditer(dts._human_body(text))]
    assert "交付" in heads


def test_real_zone_still_updates_in_place_without_touching_the_example() -> None:
    """真段在场 ⇒ 就地更新；示例字节零改动（不许把真段也当示例漏注入＝反方向失效）。"""
    out = dts._apply_block(PAGE_WITH_REAL_ZONE, _block())
    for ln in EXAMPLE_LINES:
        assert ln in out.splitlines(), f"示例被牵连：{ln!r}"
    assert "T-OLD" not in out, "真机器段没被更新"
    assert _needle() in out
    assert out.count(B) == 2 and out.count(E) == 2, "标记数变了＝示例与真段有一块被动过"
    assert _fenced_region(out) == _fenced_region(PAGE_WITH_REAL_ZONE), "示例区字节变了"


# --------------------------------------------------------------------------- ② 崩溃形
def test_misordered_markers_do_not_crash_the_write_path() -> None:
    """错序形（一枚独立 END 行在前、一枚独立 BEGIN 行在后）：旧实现 `split` 直接
    `ValueError: not enough values to unpack` —— 崩在写盘口内部。"""
    text = FM + "# 夹具\n\n" + E + "\n孤儿闭合行\n\n" + B + "\n孤儿开启行\n\n## 交付\n\n- 事件\n"
    with pytest.raises(ValueError):
        _legacy_apply_block(text, _block())
    out = dts._apply_block(text, _block())  # 不抛：无「B 在前 E 在后」的可见成对 ⇒ 走插入
    assert "孤儿闭合行" in out and "孤儿开启行" in out
    assert out.count(E) == 2 and _needle() in out  # 原两行保留 + 新段落尾的 END


# --------------------------------------------------------------------------- ③ 写后校验
def test_write_passes_after_check_and_is_idempotent(tmp_path: Path) -> None:
    pg = _page(tmp_path / "SEAT-TX171FIX.md", PAGE_WITHOUT_REAL_ZONE)
    assert dts.write_page(pg, SCHEMAS) is True
    first = (tmp_path / "SEAT-TX171FIX.md").read_bytes()
    assert "示例行" in first.decode("utf-8"), "写后示例没了＝破坏性改写没被拦住"
    again = _page(tmp_path / "SEAT-TX171FIX.md", first.decode("utf-8"))
    assert dts.write_page(again, SCHEMAS) is False
    assert (tmp_path / "SEAT-TX171FIX.md").read_bytes() == first


def test_write_after_check_failure_rolls_back_bytes_and_raises(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               ) -> None:
    """注毒：让写盘口产出一个「与渲染结果不一致」的机器段 ⇒ 写后体检新增 `AUTO_DRIFT`。

    毒下在 `_apply_block`（写盘口的**输入**，即"这次写进去什么"），`check_page`、回滚、
    抛错三件全走真码。判据：文件字节必须逐字节等于写前，且异常点名新增违规。
    """
    pg = _page(tmp_path / "SEAT-TX171FIX.md", PAGE_WITHOUT_REAL_ZONE)
    before = (tmp_path / "SEAT-TX171FIX.md").read_bytes()
    bad = _block().replace(_needle(), "- 被注毒的段")
    assert bad != _block(), "注毒没落到渲染行上 ⇒ 空跑"
    orig = dts._apply_block
    monkeypatch.setattr(dts, "_apply_block", lambda t, _b: orig(t, bad))
    with pytest.raises(dts.PageWriteRejected) as caught:
        dts.write_page(pg, SCHEMAS)
    assert (tmp_path / "SEAT-TX171FIX.md").read_bytes() == before, "拒写却没回滚"
    assert any(v.startswith("AUTO_DRIFT") for v in caught.value.introduced), \
        caught.value.introduced
    # 反向对照：同样的页、不经毒的写盘口 ⇒ 放行且新增违规为零、示例仍在
    monkeypatch.undo()
    assert dts.write_page(pg, SCHEMAS) is True
    assert "示例行" in (tmp_path / "SEAT-TX171FIX.md").read_text(encoding="utf-8")


def test_pre_existing_debt_is_not_charged_to_this_write(tmp_path: Path) -> None:
    """写前既有债不得被翻成本次写盘的错（那是缩面放水之外的另一头：罢工）。

    夹具带一枚规格外小节（写前即 SECTION_UNKNOWN）：写后该债原样在账，但**不得**因此拒写，
    也不得把 SECTION_UNKNOWN 记进 `introduced`。
    """
    text = PAGE_WITHOUT_REAL_ZONE + "\n## 规格外小节\n\n- 历史遗留\n"
    pg = _page(tmp_path / "SEAT-TX171DEBT.md", text)
    viol = dts.check_page(SCHEMAS[TPL], text, pg.fm, dts.PageCtx(rel=pg.rel, body_no_fm=text))
    assert any(v.startswith("SECTION_UNKNOWN") for v in viol), viol
    assert dts.write_page(pg, SCHEMAS) is True  # 既有债不重复计账 ⇒ 照常驱动
