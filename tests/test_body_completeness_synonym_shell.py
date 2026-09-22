"""席 S204（2026-09-22，第廿九批）：G-B1 同义措辞**空壳**判据（封闭同义族）。

一句话：G-B1（`spec_gates_census.board_body_completeness`）今日判「必选节**有**正文」。
老形态是写一句自指导词（"详见上文""如题""见报告正文""见上""略"）就当交差——有字 ≠ 有内容。
本文件把这一族变成一把**可执法、只准收紧**的锁，**不改判据真身**（真身在
`scripts/spec_gates_census.py`，主会话单点改），只在测试侧建判据 + 六件套。

为什么"封闭同义族"不是"我手编的一张表"（这是任务书①的红线）：
  派生脚本 `%TEMP%/s204_derive.py` 走真身函数（`sc.compute` / `sc.BOARD_CANON` /
  `sc.slot_bodies` / `sc._human_area`）枚举全树必选节正文、按短行词频统计，实跑结论：
    · board 页 228、必选节实例 986、非空 body 950（扫描面地板基准）。
    · 高频短行 Top 全是 `|---|---|---|`（表格分隔）与
      `本功能没有专属配置键前缀登记在声明源里。`（合法事实）——**没有一个**是空壳。
    · mandate 点名的老形态 5 句在全树频次=0。
  ⇒ 纯词频**无法**定义空壳族（会把表格行、`不编历史。`这类合法短句误收）。族必须是
  「语义=自指导词 ∧ 全节正文恰等于该词」，长度阈值只作副闸。族的成员由**任务书背景段**
  点名（非本席发明），本席另用注毒自证其边界：真·短句不得被误杀、纯长度判据必过拦。

与 S152 对账（任务书③）：S152 无"同义空壳"档，其「完整」档吞掉此类页；本判据今日在真树
命中 **0**（空壳尚未扩散），差集=∅。这是一枚**启用前置**预防锁（同 S196 哲学），用注毒
证明它有牙：造一页让 S152 判「完整」而本锁判「空壳」，两判据在同一页上分道即证缺口闭合。

诚实边界（任务书④/⑤）：exact-match 判据抓不到"嵌在略长散文里的自指导词"
（如"此处内容详见上文所述，不再赘述。"）。这不是本锁的失败而是它的定义域——把阈值一降
去够它会过拦真实短句（`不编历史。`=5 字合法），二者不可两全，本席选"宁缺毋滥 + 如实声明"。

六件套（照抄 `tests/test_taxonomy_spec_gates.py`，未自创）：
① 单一取数口（`_shell_hits`，只经真身函数）；② 上限=手写字面量 + AST 双形态自锁；
③ `AUDIT` 方向锁（只准降）；④ 扫描面地板（塌陷即红）；⑤ 反向自测全走内存 PageInfo
（不往源码树写一个字）；⑥ 正样控制（真·合法短句不得被记）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doc_template_sync as dts  # PageInfo 真身
import spec_gates_census as sc  # 判据真身，只 import 不改

_REAL = sc.compute()  # 全模块只现算一次，判据与 --report 同源

# ---------------------------------------------------------------------------
# 封闭同义族（成员由任务书背景段点名，非本席发明；见文件头「为什么不是手编表」段）
# ---------------------------------------------------------------------------
#: 归一时剥除的标点/空白（含中英标点），使 "见上。" 与 "「见上」" 同形。
_SHELL_STRIP_CHARS = "。. ，,、；;：:！!？?~～ 　\"'“”‘’「」『』()（）[]【】\n\r\t"

#: 归一后的封闭同义空壳集。原始名（任务书点名的 5 枚）+ 其常规同义变体。
SYNONYM_SHELL_PHRASES_RAW: tuple[str, ...] = (
    "详见上文",
    "见上文",
    "如题",
    "见报告正文",
    "见上",
    "见下",
    "略",
    "同上",
    "参见上文",
    "详见正文",
    "如前所述",
    "见前文",
    "此处从略",
    "不再赘述",
)

#: 任务书背景段点名的核心 5 枚——必须始终在族里（防未来被悄悄摘掉变成空锁）。
_SHELL_MANDATE_CORE: tuple[str, ...] = ("详见上文", "如题", "见报告正文", "见上", "略")

#: 副闸：整节正文（strip 后原长）超过此字符数即视为"有可称量的内容"，不当空壳。
#: 证据（①派生）：核心 5 枚最长 `见报告正文`=5 字；族内最长 `此处从略`/`详见正文`=4、`不再赘述`=4，
#: 全 ≤ 5；故阈值取 8 覆盖"壳+标点/换行"余量，又远低于合法整节正文（真树非空必选节正文最短
#: 合法句 `不编历史。`=5 字但语义自足）。长度是**必要非充分**副闸，充分判据恒为"恰等于族成员"。
_SHELL_MAX_BODY_CHARS = 8

#: 扫描面地板（①现算：必选节实例 986 / 非空 950）——塌陷即红，防"集合为空恒真"假绿。
_MIN_EXAMINED_REQUIRED_SECTIONS = 500

#: 本席现算命中数（真树今日 0）→ 手写字面量上限（只准降，不许升）。
#: 复跑：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
#:   ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_body_completeness_synonym_shell.py -q
SYNONYM_SHELL_CEILING = 0

#: 方向锁历史（开工时刻现算值）；后续核账只准≤上一项。
SYNONYM_SHELL_AUDIT: tuple[tuple[str, int], ...] = (("2026-09-22", 0),)


def _normalize_shell(text: str) -> str:
    s = text.strip()
    while s[:1] in ("-", "*", ">", "+", "·"):
        s = s[1:].strip()
    return "".join(ch for ch in s if ch not in _SHELL_STRIP_CHARS).lower()


_SHELL_FAMILY_FOLDED = frozenset(_normalize_shell(x) for x in SYNONYM_SHELL_PHRASES_RAW)


def is_synonym_shell_body(body: str) -> bool:
    """一节正文是否为「封闭同义空壳」：恰等于族成员（长度作副闸）。

    空 body 不在此档（归 S152 的骨架残留/纯指针/机器整册管）——本判据只管「有字但字是空壳」。
    """
    raw = body.strip()
    if not raw:
        return False
    if len(raw) > _SHELL_MAX_BODY_CHARS:
        return False
    return _normalize_shell(raw) in _SHELL_FAMILY_FOLDED


def _board_pages(pages: list[dts.PageInfo]) -> list[dts.PageInfo]:
    return [p for p in pages if p.rel.startswith("docs/boards/")]


def _required_pairs(pages: list[dts.PageInfo]) -> list[tuple[str, str]]:
    """(rel, 必选节名) 全集——单一取数口，走真身 canon/slot_bodies/_human_area。"""
    pairs: list[tuple[str, str]] = []
    for p in _board_pages(pages):
        canon = sc.BOARD_CANON.get(p.category)
        if canon is None:
            continue
        for name, optional in canon:
            if not optional:
                pairs.append((p.rel, name))
    return pairs


def _shell_hits(pages: list[dts.PageInfo]) -> list[tuple[str, str, str]]:
    """命中清单（单一取数口）：逐必选节取 body、判空壳。返回 (rel, 节名, 正文)。"""
    hits: list[tuple[str, str, str]] = []
    for p in _board_pages(pages):
        canon = sc.BOARD_CANON.get(p.category)
        if canon is None:
            continue
        bodies = sc.slot_bodies(sc._human_area(p.text or ""))  # 与真身 board_body_completeness_row 同取法
        for name, optional in canon:
            if optional:
                continue
            body = bodies.get(name, "")
            if is_synonym_shell_body(body):
                hits.append((p.rel, name, body.strip()))
    return hits


# ---------------------------------------------------------------------------
# ④ 扫描面地板 + ⑥ 正样控制
# ---------------------------------------------------------------------------
def test_scan_surface_has_a_floor_not_vacuously_green() -> None:
    """必选节扫描面非空（塌陷即红）：命中 0 必须来自"扫了很多、确实无空壳"，
    而不是"什么都没扫到所以恒真"。"""
    pairs = _required_pairs(_REAL["pages"])
    assert len(pairs) >= _MIN_EXAMINED_REQUIRED_SECTIONS, (
        f"只扫到 {len(pairs)} 枚必选节（地板 {_MIN_EXAMINED_REQUIRED_SECTIONS}）＝扫描面塌陷，"
        "命中=0 不可信（假绿：集合为空恒真）"
    )
    # 正样控制：真树确有必选节正文非空（否则整把尺都在空跑）
    nonempty = 0
    for p in _board_pages(_REAL["pages"]):
        canon = sc.BOARD_CANON.get(p.category)
        if canon is None:
            continue
        bodies = sc.slot_bodies(sc._human_area(p.text or ""))
        for name, optional in canon:
            if not optional and bodies.get(name, "").strip():
                nonempty += 1
    assert nonempty >= _MIN_EXAMINED_REQUIRED_SECTIONS, (
        f"真树非空必选节正文仅 {nonempty} 枚＝取数口或页集改版，本锁失明"
    )


# ---------------------------------------------------------------------------
# ② 上限 + 现算命中对账
# ---------------------------------------------------------------------------
def test_real_tree_hits_within_hand_literal_ceiling() -> None:
    hits = _shell_hits(_REAL["pages"])
    assert len(hits) <= SYNONYM_SHELL_CEILING, (
        f"真树必选节同义空壳 {len(hits)} > 上限 {SYNONYM_SHELL_CEILING}："
        f"有人交了一批只写『见上/如题/略』的必选节 → {hits[:6]}"
    )
    assert len(hits) == 0, (
        f"上限策略与现算脱节（应=0，实={len(hits)}）＝树已长空壳而基线未核账：{hits[:6]}"
    )


def test_ceiling_direction_lock_only_down() -> None:
    assert SYNONYM_SHELL_AUDIT, "方向锁历史为空＝无锚"
    prev = SYNONYM_SHELL_AUDIT[0][1]
    for day, val in SYNONYM_SHELL_AUDIT:  # 单调不增
        assert val <= prev, f"同义空壳账本回升 {prev}->{val} @ {day}（只准降）"
        prev = val
    current = len(_shell_hits(_REAL["pages"]))
    assert current <= SYNONYM_SHELL_AUDIT[0][1], (
        f"今日现算 {current} > 首届核账 {SYNONYM_SHELL_AUDIT[0][1]}＝新增空壳未核账"
    )


def test_ceiling_is_hand_written_int_literal_ast_lock() -> None:
    """结构锁：上限必须是手写字面整数（`Assign` 与 `AnnAssign` 双形态都查），
    不许被换成 len(...)/sum(...) 之类派生式（派生式错值比手写更危险，S164 教训）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        value: ast.expr | None = None
        name: str | None = None
        if isinstance(node, ast.Assign):
            value = node.value
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            name = next((n for n in names if n == "SYNONYM_SHELL_CEILING"), None)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "SYNONYM_SHELL_CEILING":
                value, name = node.value, node.target.id
        if name == "SYNONYM_SHELL_CEILING":
            found = True
            assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
                "SYNONYM_SHELL_CEILING 不再是字面整数（被改成派生式？）"
            )
    assert found, "SYNONYM_SHELL_CEILING 赋值消失（本锁失去上限锚）"
    # 禁线自证：判据真身里不许出现本席账本的 CEILING/BASELINE（转正权在该门 owner，非本席）
    sc_tree = ast.parse((REPO_ROOT / "scripts" / "spec_gates_census.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(sc_tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                up = tgt.id.upper()
                if ("SHELL" in up or "SYNONYM" in up) and ("CEILING" in up or "BASELINE" in up):
                    offenders.append(tgt.id)
    assert offenders == [], f"同义空壳上限被写进了判据真身（本应只住测试侧，待 owner 转正）：{offenders}"


# ---------------------------------------------------------------------------
# ⑤ 内存注毒（全走 PageInfo，不落源码树一个字）
# ---------------------------------------------------------------------------
_DEFAULT_FILLER = "本入口收上行事件、产出卡片载荷，生效需总闸开且会话准入通过。"


def _synth_page_text(shell_section: str | None = None, *, filler: str = _DEFAULT_FILLER) -> str:
    """造一页 board-l3：全部必选节填 `filler`，仅指定节（若给）填 `shell_section`。"""
    names = [n for n, opt in sc.BOARD_CANON["board-l3"] if not opt]
    assert names, "前提塌：board-l3 无必选节，注毒样本无从构造"
    parts: list[str] = []
    for n in names:
        body = shell_section if (shell_section is not None and n == names[0]) else filler
        parts.append(f"## {n}\n{body}")
    return "\n".join(parts)


def _synth_page(text: str) -> dts.PageInfo:
    return dts.PageInfo(
        rel="docs/boards/B99-s204/s204/l3.md",
        path=REPO_ROOT / "docs" / "boards" / "B99-s204" / "s204" / "l3.md",
        text=text,
        fm=None,
        category="board-l3",
        violations=(),
    )


@pytest.mark.parametrize("shell", _SHELL_MANDATE_CORE)
def test_inject_each_mandate_shell_is_caught(shell: str) -> None:
    """④a：注入任务书点名的每一枚核心空壳 ⇒ 必被记（族核心逐个有牙，不是一枚代表全场）。"""
    page = _synth_page(_synth_page_text(shell))
    hits = _shell_hits([page])
    assert hits, f"注入核心空壳 {shell!r} 未被记＝该枚是假绿（探针恒假）"
    assert any(h[2] == shell for h in hits), f"记到的不是注入那枚：{hits}"


def test_injected_shell_page_is_complete_under_s152_but_flagged_here() -> None:
    """缺口闭合自证（③对账的硬证）：同一页，S152 判「完整」（吞掉空壳），
    本锁判「空壳」。两判据在同页分道 ⇒ 本席确实在补 G-B1 的洞，不是复读现值。"""
    page = _synth_page(_synth_page_text("见上"))
    row = sc.board_body_completeness_row(
        page, b_ok=set(), canon=sc.BOARD_CANON["board-l3"]
    )
    assert row["tier"] == "完整", (
        f"前提塌：注入『见上』页在 S152 下不是『完整』（{row['tier']}）⇒ 缺口不存在，注毒无效"
    )
    assert _shell_hits([page]), "S152 判完整而本锁也判无违规＝本锁对该洞失明"


def test_inject_short_effective_body_is_not_caught() -> None:
    """④b（防过拦，最易忽略）：真·短但语义自足的正文 ⇒ 必不被记。
    `不编历史。`(5 字) 是合法事实陈述，纯长度判据会误杀它；本锁靠"恰等于族成员"放行。"""
    for legit in ("不编历史。", "档位语气表。", "本功能没有专属配置键前缀登记在声明源里。"):
        page = _synth_page(_synth_page_text(None, filler=legit))
        assert not _shell_hits([page]), f"合法短句被误判为空壳（过拦）：{legit!r}"


def test_inject_punctuated_shell_still_caught() -> None:
    """归一自证：带中英标点/引号的同形壳须被抓（证明 _normalize_shell 真在起作用）。"""
    page = _synth_page(_synth_page_text("「见上」。"))
    assert _shell_hits([page]), "加了标点引号的空壳漏判＝归一尺没接上"


def test_overlong_embedded_shell_is_honest_boundary() -> None:
    """④c（诚实边界，不许吹）：嵌在略长散文里的自指导词，本 exact-match 判据**抓不到**。
    如实断言"抓不到"，坐定其定义域；降阈值去够它会过拦真实短句，二者不可两全。"""
    page = _synth_page(_synth_page_text("此处内容详见上文所述，不再赘述。"))
    assert not _shell_hits([page]), (
        "本席宣称抓不到长散文内嵌壳，却抓到了＝诚实边界陈述与判据不符（或过拦）"
    )


def test_blinding_the_ruler_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """④反向自证（F-15 教训：注毒须走记账腿非只喂正则）：把判据蒙成恒 False ⇒
    注入页在 _shell_hits 下查不到命中，而真判据查得到 ⇒ 证本锁非恒假。"""
    real = sc.__dict__.get  # noqa: F841  (仅占位，避免 lint 误报未用)
    page = _synth_page(_synth_page_text("如题"))
    assert _shell_hits([page]), "前提塌：真判据下注入页都记不到，注毒无从证伪"
    monkeypatch.setattr(sys.modules[__name__], "is_synonym_shell_body", lambda body: False)
    assert _shell_hits([page]) == [], "把判据蒙成恒 False 后仍报命中＝记账腿与判据不同源（假锁）"


def test_mandate_core_never_dropped_from_family() -> None:
    """族核心锁：任务书点名的 5 枚必须始终在归一族里（防未来有人悄悄摘核心变空锁）。"""
    for shell in _SHELL_MANDATE_CORE:
        assert _normalize_shell(shell) in _SHELL_FAMILY_FOLDED, f"核心空壳 {shell!r} 被摘出族＝判据被架空"
