"""S345 #83 常驻门：静默消音面三把锁（J-1 共用判据一致性 / J-2 枚数棘轮 / J-3 skip 必带异常原文）。

背景（SILENT-EXCEPT-AUDIT-20260925.md，S335）：全树「宽口径 except ⇒ pytest.skip」handler 曾恰 10 枚，
其中渲染确定性那 3 枚把「包能导入而二进制坏了 / 参数写错 / 磁盘满」塌成一句 `Chromium 启动失败（类名）`
后静默 skip ⇒ 视觉确定性整面可在零红下永久停摆。本门把这件事钉成可机检的三把锁：

- **J-2**：枚数上限棘轮（手写字面量，只准降；零余量＝等于末次现算核账值；扫描面塌陷锁）。
- **J-3**：凡「宽 except＋体内 pytest.skip」，skip reason 必须携带 `str(exc)`（仅类名不合格）。
- **J-1**：三门与外层 skipif 共用**唯一**判据 `chromium_not_installed`；且存在一枚**永不 skip** 的
  launch 哨兵（无 skipif、体内无 pytest.skip、直连 launch）。二者不一致即红。

本门自身**不新增任何消音面**：读文件失败＝明红（不 skip）；仓内只扫、不改。
"""

from __future__ import annotations

import ast
from functools import cache, lru_cache
from pathlib import Path
from typing import Final

# ------------------------------------------------------------------ 扫描根与常量
REPO: Final[Path] = Path(__file__).resolve().parents[1]
SCAN_SUBTREES: Final[tuple[str, ...]] = ("tests", "scripts", "plugins")

#: J-2 手写**字面量**上限（零余量＝末次现算核账值），只准降。
# 2026-09-25 S345 首账：S335 定尺时现算 10；本席 J-1 把渲染那 3 枚消音塌进 1 枚共用
# `launch_chromium_or_skip`（其 skip 携带 str(exc)、被 J-3 放行）⇒ 现算 7＋1＝8，零余量钉死。
SILENT_SKIP_CEILING: Final[int] = 8

#: 逐次核账记录 (日期, 当时枚数)，必须单调不升，且末项＝当前上限（零余量锁）。
SILENT_SKIP_AUDIT_HISTORY: Final[tuple[tuple[str, int], ...]] = (
    ("2026-09-25", 10),  # S335 定尺现算（本席 s345-1-census.py 逐位复算=10）
    ("2026-09-25", 8),   # 本席 J-1 降账后现算（3→1 塌进共用 helper）
)

#: 扫描面地板：低于此＝有人改了 glob/排除（扫描面塌陷），不是「大家都干净了」。
MIN_SCANNED_FILES: Final[int] = 1000
#: 静默消音锚点地板：现算枚数低于此＝判据被改瞎（一条都没收到），不是「全树归一」。
MIN_SILENT_SKIP_FLOOR: Final[int] = 4
#: 已知锚点（这些文件必须至少被扫到一次，否则取数口坏）。
_ANCHOR_FILES: Final[tuple[str, ...]] = (
    "tests/test_creation_image_protocol.py",
    "tests/test_creation_tts_drift_gate.py",
    "tests/test_descriptor_wiredness_ledger.py",
    "tests/test_phase_determinism.py",
    "tests/test_phase_determinism_2.py",
)

_CRITERION_FN: Final[str] = "chromium_not_installed"
_LAUNCH_HELPER_FN: Final[str] = "launch_chromium_or_skip"
_CANARY_TEST: Final[str] = "test_playwright_chromium_launch_canary_is_never_silent"


# ------------------------------------------------------------------ 尺 A：宽 except + pytest.skip
def _broad_except(node: ast.ExceptHandler) -> bool:
    t = node.type
    if t is None:  # bare except
        return True
    names: list[str] = []
    if isinstance(t, ast.Name):
        names = [t.id]
    elif isinstance(t, ast.Attribute):
        names = [t.attr]
    elif isinstance(t, ast.Tuple):
        names = [
            e.id if isinstance(e, ast.Name) else getattr(e, "attr", "") for e in t.elts
        ]
    return any(n in ("Exception", "BaseException") for n in names)


def _skip_calls_in_handler(body: list[ast.stmt]) -> list[ast.Call]:
    """handler 直属体内（进 if/try 分支，但不进嵌套 def/class）找 pytest.skip/skip 调用。"""
    out: list[ast.Call] = []
    for st in body:
        if isinstance(
            st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for sub in ast.walk(st):
            if isinstance(sub, ast.Call):
                f = sub.func
                dn = (
                    f"{getattr(f.value, 'id', '')}.{f.attr}"
                    if isinstance(f, ast.Attribute)
                    else (f.id if isinstance(f, ast.Name) else None)
                )
                if dn in ("pytest.skip", "skip"):
                    out.append(sub)
    return out


def _carries_str_exc(call: ast.Call, bound: str | None) -> bool:
    """严格判 skip reason 是否携带异常字符串形态（仅类名不算）。

    命中：`{exc}`/`{exc!r}`/`{exc!s}`（FormattedValue.value 即裸 Name(exc)）、
    `str(exc)`/`repr(exc)`、`exc.__str__()`。仅 `{exc.__class__.__name__}` 不算。
    """
    if bound is None:
        return False
    for node in ast.walk(call):
        if (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id == bound
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("str", "repr")
            and any(isinstance(a, ast.Name) and a.id == bound for a in ast.walk(node))
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__str__"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == bound
        ):
            return True
    return False


class SilentSkip:
    __slots__ = ("bound", "carries", "file", "lineno", "skips")

    def __init__(
        self,
        file: str,
        lineno: int,
        bound: str | None,
        skips: list[ast.Call],
        carries: bool,
    ) -> None:
        self.file = file
        self.lineno = lineno
        self.bound = bound
        self.skips = skips
        self.carries = carries


def _parse(rel: str) -> ast.Module:
    text = (REPO / rel).read_text(encoding="utf-8")
    return ast.parse(text, filename=rel)


@lru_cache(maxsize=1)
def scan_silent_skips() -> tuple[int, tuple[SilentSkip, ...]]:
    """返回 (扫到的 py 文件数, 静默消音 handler 清单)。一次全树扫、多测共用（树在跑测期不变）。
    读/解析失败即抛（不 skip）。"""
    files = 0
    found: list[SilentSkip] = []
    for sub in SCAN_SUBTREES:
        root = REPO / sub
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            tree = _parse(rel)
            files += 1
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and _broad_except(node):
                    skips = _skip_calls_in_handler(node.body)
                    if not skips:
                        continue
                    bound = node.name
                    carries = all(_carries_str_exc(c, bound) for c in skips)
                    found.append(SilentSkip(rel, node.lineno, bound, skips, carries))
    return files, tuple(found)


# ------------------------------------------------------------------ J-2 棘轮自锁
def test_silent_skip_count_within_ceiling() -> None:
    _files, found = scan_silent_skips()
    assert len(found) <= SILENT_SKIP_CEILING, (
        f"宽 except＋pytest.skip 的静默消音面 {len(found)} > 上限 {SILENT_SKIP_CEILING}＝又长新消音点。"
        f"逐枚：{[(s.file, s.lineno) for s in found]}。修法：让失败显形（上抛/明红），"
        f"或把可诚实 skip 的收进唯一共用判据，而非各处新写 except→skip。"
    )


def test_zero_slack_ceiling_equals_latest_audit() -> None:
    """零余量锁（字面量对字面量，与仓内 ratchet 同尺）：上限必须恰等于末次核账值。

    刻意**不**断言「现算枚数 == 上限」——那样会把别人合法降账（现算<上限）误判成红；
    「只准降」由 `count <= ceiling`＋`audit never rises`＋`ceiling==末次审计` 三把共同兜住。
    """
    assert SILENT_SKIP_CEILING == SILENT_SKIP_AUDIT_HISTORY[-1][1], (
        "上限≠最近核账值＝偷偷留了余量或抬了上限（想调上限必须同批改历史，且历史只准降）"
    )


def test_ceiling_is_hand_written_literal() -> None:
    """结构锁：上限与核账历史必须是本文件里的手写字面量，不许与被检对象联动。"""
    assigned: dict[str, ast.expr | None] = {}
    self_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(self_tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            assigned[node.target.id] = node.value
    ceiling = assigned.get("SILENT_SKIP_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "SILENT_SKIP_CEILING 被改成派生表达式＝账跟着被检对象一起动，本门结构性失效"
    )
    history = assigned.get("SILENT_SKIP_AUDIT_HISTORY")
    assert isinstance(history, (ast.Tuple, ast.List)) and len(history.elts) >= 1, (
        "SILENT_SKIP_AUDIT_HISTORY 必须留在本文件且非空——它是「只准降」的对账凭据"
    )


def test_audit_history_never_rises() -> None:
    counts = [c for _, c in SILENT_SKIP_AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), (
        f"核账记录出现回升（方向锁）：{SILENT_SKIP_AUDIT_HISTORY}"
    )
    assert SILENT_SKIP_CEILING <= counts[0], "上限超过首届核账值＝调大换绿，本门不允许"


def test_scan_scope_did_not_collapse() -> None:
    """塌陷锁：扫描面、锚点、账本非空——三把攥住才许谈绿。"""
    files, found = scan_silent_skips()
    assert files >= MIN_SCANNED_FILES, (
        f"只扫到 {files} 个 py 文件（地板 {MIN_SCANNED_FILES}）＝扫描面塌陷"
    )
    assert len(found) >= MIN_SILENT_SKIP_FLOOR, (
        f"只收到 {len(found)} 枚静默消音候选（地板 {MIN_SILENT_SKIP_FLOOR}）＝判据被改瞎，不是全树归一"
    )
    seen = {s.file for s in found}
    assert seen, "一条静默消音候选都没收到＝取数口坏了"
    # 锚点：这些已知含宽 except+skip 的文件必须仍被扫到（取数口没瞎挑）
    anchors_present = [a for a in _ANCHOR_FILES if a in seen]
    assert len(anchors_present) >= 3, (
        f"锚点文件识别塌陷：只认出 {anchors_present}（应≥3），取数口可能改瞎"
    )


# ------------------------------------------------------------------ J-3 腿：skip 必带 str(exc)
def test_every_silent_skip_carries_exception_text() -> None:
    """凡「宽 except＋体内 pytest.skip」，reason 必须携带 str(exc)；仅类名不合格。"""
    _files, found = scan_silent_skips()
    bad = [
        f"{s.file}:{s.lineno} bound={s.bound}"
        for s in found
        if not s.carries
    ]
    assert not bad, (
        "以下静默消音点的 skip reason 丢异常原文（只类名/固定串）＝把'没装'与'坏了'塌成一个词："
        + "; ".join(bad)
        + "。修法：reason 里带 str(exc)（如 f'...{{type(exc).__name__}}: {{exc}}'）。"
    )


# ------------------------------------------------------------------ J-1 腿：共用判据 + 永不 skip 哨兵
def test_chromium_launch_criterion_is_single_sourced() -> None:
    """`chromium_not_installed` 在 tests/ 里只准定义一次（禁三份副本）。"""
    defs = _count_top_level_func_defs("chromium_not_installed")
    assert defs == 1, (
        f"判据 chromium_not_installed 被定义 {defs} 次（应=1）＝又起副本，三门可能各判各的"
    )
    helper_defs = _count_top_level_func_defs("launch_chromium_or_skip")
    assert helper_defs == 1, (
        f"唯一 launch 出口 launch_chromium_or_skip 被定义 {helper_defs} 次（应=1）"
    )


def test_render_launch_guards_share_single_criterion_and_canary_is_loud() -> None:
    """三门都过共用出口、canary 永不 skip，且共用出口内部调用判据——不一致即红。"""
    rel1 = "tests/test_phase_determinism.py"
    rel2 = "tests/test_phase_determinism_2.py"
    t1 = _parse(rel1)
    t2 = _parse(rel2)

    # (a) 共用出口 helper 内部确实调用判据 chromium_not_installed
    helper = _find_func(t1, _LAUNCH_HELPER_FN)
    assert helper is not None, "launch_chromium_or_skip 必须住在 test_phase_determinism.py"
    called = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None))
        for n in ast.walk(helper)
        if isinstance(n, ast.Call)
    }
    assert _CRITERION_FN in called, (
        "唯一 launch 出口没调用共用判据 chromium_not_installed＝判据形同虚设"
    )

    # (b) 两文件里对 launch_chromium_or_skip 的调用合计 >= 3（三门都走它）
    n_calls = _count_name_calls(t1, _LAUNCH_HELPER_FN) + _count_name_calls(
        t2, _LAUNCH_HELPER_FN
    )
    assert n_calls >= 3, (
        f"三门应有>=3 处经 launch_chromium_or_skip，实得 {n_calls}＝有消音点绕过共用出口"
    )

    # (c) canary：无 skipif 装饰、体内无 pytest.skip、且直连 .launch(
    canary = _find_func(t1, _CANARY_TEST) or _find_func(t2, _CANARY_TEST)
    assert canary is not None, f"缺少永不 skip 的 launch 哨兵 {_CANARY_TEST}"
    for dec in canary.decorator_list:
        dname = ast.dump(dec)
        assert "skipif" not in dname, "launch 哨兵不得带 skipif（那样又会被静默跳过）"
    has_skip = any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == "skip")
            or (isinstance(n.func, ast.Name) and n.func.id == "skip")
        )
        for n in ast.walk(canary)
    )
    assert not has_skip, "launch 哨兵体内出现 pytest.skip＝它不再是'永不 skip'的显形哨兵"
    launched = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "launch"
        for n in ast.walk(canary)
    )
    assert launched, "launch 哨兵必须真起一次 Chromium（直连 .launch）"


@cache
def _count_top_level_func_defs(name: str) -> int:
    total = 0
    for sub in SCAN_SUBTREES:
        root = REPO / sub
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            try:
                tree = _parse(rel)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:  # 只数顶层，避免把内层同名闭算进副本
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    total += 1
    return total


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _count_name_calls(tree: ast.Module, name: str) -> int:
    return sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    )
