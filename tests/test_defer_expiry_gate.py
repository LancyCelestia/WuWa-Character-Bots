r"""延账到期门：测试挂账（xfail / 裸 skip）必须带「到期日 + owner + 摘牌条件」三件。

## 这条门的存在理由（一句话）

全仓 68 枚停用/预期失败标记里，**需要日历的那 13 枚一枚都没写日子**（S381 与 S503 两把
独立现算尺枚级完全一致，差集为空）。"已过期 0 枚"从来不是债轻，而是**到期这件事在测试
挂账上不存在**——同一仓库里它已经被实现过三次（审批册 `scripts/shim_retirement_census.py`、
上限册 `tests/test_taxonomy_spec_gates.py`、出站闸 TTL `outbound_gate.effective_gate_enabled`），
唯独测试挂账这一族没人管。本件把那三枚已有口径推广过来，**不新增第四套解析**。

## 判据（钉死，逐条有锁）

1. **射程**＝`needs_calendar`：全部 `xfail`（装饰器 / `pytestmark` / 运行时 / `unittest.expectedFailure`）
   ＋ 裸 `@pytest.mark.skip` ＋ **无守卫**的运行时 `pytest.skip()`。
   `skipif` / `importorskip` / 守卫内（`if`/`except`）`skip` = 条件自解，**不要求日历**
   （活性实证见 `tests/test_outbound_gate.py::test_config_keys_keep_gate_off`：六枚键一落地它自己就不 skip 了）。
2. **三件只认枚自身字面量**：`expiry=` / `owner=` / `摘牌=`（允许 `到期日=`/`有效期至=`/`责任人=` 别名）。
   - **邻近注释里的日期一律不算**（否则"隔壁写个日子"就能糊门＝S307 §五-1 实测过的假阳型）；
   - **f-string 的常量段必须折进来**（否则 `f"expiry=…"` 是一条绕行道＝S381 §一 自曝的那枚尺洞）；
   - 具名标记变量（`bad = pytest.mark.xfail(...)` 再 `@bad`）⇒ **定义位判一次**，
     使用位只作可见性记录（否则一条变量声明能给任意多个用例发免罪金牌）。
3. **fail-closed**：`expiry` 缺失 / 空白 / 读不懂 ⇒ 一律按**已过期**处理（沿用三枚真身口径）。
   "没人写日子" 必须被读成 "它已经到期了"，绝不能被读成 "没有债到期"。
4. **两类红分开报**：`到期`（含缺日子）≠ `缺登记`（缺 owner / 缺摘牌）——前者是"到期未摘牌"，
   后者是"挂账没写清"，混在一起就分不清该找谁。
5. **owner 必须是能动手的人/席**（`SEAT-*`／姓名／`@工号`）；**工单号不是 owner**——
   `M-28`/`G-4`/`T-Spec`/`台账 #N` 只是指向 owner 的指针（「在册≠执法」同一把尺）。
6. **方向锁**：只有"到期即红"，**绝没有**"到期自动放宽/自动续期/自动摘标记"。
   续期只能改 reason 里那个日期，且改的人就是 owner 本人。
7. **时刻解析唯一真身**＝`domains/core/moment_parsing.parse_moment`。本件正文
   **不许出现 `fromisoformat`**（由 `test_defer_expiry_gate_uses_single_moment_parser` 执法）。

## 写法示例（改造前后）

```python
# 改造前（今树现状）：
@pytest.mark.xfail(reason="接缝锁·前提未落地：装配适配器席落地后删本标记转正。")
# 改造后（同一条 reason 内塞进三件，零新键、零新文件）：
@pytest.mark.xfail(reason="接缝锁·前提未落地：装配适配器席落地后删本标记转正。"
                   "〔expiry=2026-12-24 owner=SEAT-<席或人> 摘牌=适配器落地〕")
```
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import pytest

from plugins.bot_unified_runtime.domains.core.moment_parsing import (
    MomentParseError,
    parse_moment,
)

# --------------------------------------------------------------------------
# 取数面
# --------------------------------------------------------------------------

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
SCAN_ROOTS: Final[tuple[str, ...]] = ("tests", "plugins", "scripts")
SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git", "node_modules"}
)

MARK_ATTRS: Final[frozenset[str]] = frozenset({"xfail", "skip", "skipif"})
RUNTIME_ATTRS: Final[frozenset[str]] = frozenset({"skip", "xfail", "importorskip"})

# --------------------------------------------------------------------------
# 三件套的字面判据
# --------------------------------------------------------------------------

RE_EXPIRY: Final[re.Pattern[str]] = re.compile(
    r"(?:expiry|到期日|有效期至|截止日)\s*[=:：]\s*([0-9]{4}-[0-9]{2}(?:-[0-9]{2})?)", re.IGNORECASE
)
RE_OWNER: Final[re.Pattern[str]] = re.compile(
    r"(?:owner|责任人)\s*[=:：]\s*([^\s〕)\]，,；;]+)", re.IGNORECASE
)
#: 摘牌腿：**显式 `摘牌=` 键**，或本仓散文里已经在用的触发语（修复后/落地后/转绿/转 XPASS/
#: 自动生效/删除本/移除本/摘本/转正/退役）。放宽这一腿的理由＝本门的硬账是**日子**；把已经
#: 写清"怎么摘"的枚逼成再抄一遍 `摘牌=`，只会造出填表式合规（写关键词应付门，不改事实）。
#: ⚠ owner 腿**不放宽**（理由见下方 RE_TICKET_POINTER）：出处指针与归属声明是两回事。
RE_DROP: Final[re.Pattern[str]] = re.compile(
    r"摘牌\s*[=:：]|删除本|移除本|摘本|转正|退役|修复后|落地后|转绿|XPASS|自动生效"
)

#: 工单号形态＝指针，不是 owner。逐条对齐本仓实际在用的编号族，宁可窄不可宽
#: （宽了会把 "owner=待点名" 这类放行；窄了最多误伤一个真人名，而真人名不长这样）。
RE_TICKET_POINTER: Final[re.Pattern[str]] = re.compile(
    r"^(?:T-Spec|M-\d+|G-\d+|R-\d+|R-[A-Z]+-\d+|U-\d+|P-\d+|WP\d+|S\d{2,4}|CM-P-\d+|PX-\d+|台账#\d+)$",
    re.IGNORECASE,
)

#: 占位 owner 一律不算 owner。**这条是本席给自己下的补丁**：13 枚里有 11 枚查无归属证据，
#: 若门只要求"`owner=` 这一栏非空"，那么全场写一遍 `owner=待点名` 就能把门刷绿——
#: 那是**填表式合规**（关键词伺候门，事实一个字没变），比现状更糟：账看着齐了、主还是没有一个。
#: 占位形态按本仓实际会出现的写法列举，宁可窄（误伤真人名可改），判据面见
#: `test_poison_placeholder_owner_is_still_red`。
RE_OWNER_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(
    r"^(?:待点名|待定|待裁|待补|未知|无|none|None|N/?A|TODO|TBD|用户|她|待定席)$"
)


class Marker:
    """一枚停用/预期失败标记（本件的最小事实单元）。"""

    __slots__ = ("form", "guard", "host", "judged", "kind", "line", "reason", "reason_form", "rel")

    def __init__(self, rel: str, line: int, kind: str, form: str, guard: str, host: str,
                 reason: str, reason_form: str, judged: bool) -> None:
        self.rel = rel
        self.line = line
        self.kind = kind
        self.form = form
        self.guard = guard
        self.host = host
        self.reason = reason
        self.reason_form = reason_form
        self.judged = judged

    @property
    def at(self) -> str:
        return f"{self.rel}:{self.line}（{self.kind}/{self.form}，宿主 {self.host}）"

    @property
    def needs_calendar(self) -> bool:
        if not self.judged:
            return False
        if self.kind == "xfail":
            return True
        if self.kind == "skip" and self.guard == "none" and self.form in ("decorator", "decorator-bare", "pytestmark", "marker-variable"):
            return True
        return self.kind == "skip" and self.form == "runtime" and self.guard == "none"


# --------------------------------------------------------------------------
# AST 尺（唯一取数口）
# --------------------------------------------------------------------------


def _mark_target(node: ast.AST) -> tuple[str, str] | None:
    """`pytest.mark.xfail` / `mark.skip` / `unittest.expectedFailure` → (前缀, 末段)。"""
    if isinstance(node, ast.Attribute):
        inner = node.value
        if isinstance(inner, ast.Attribute):
            head = f"{getattr(inner.value, 'id', '')}.{inner.attr}"
        elif isinstance(inner, ast.Name):
            head = inner.id
        else:
            head = ""
        return (head, node.attr)
    if isinstance(node, ast.Name):
        return ("", node.id)
    if isinstance(node, ast.Call):
        return _mark_target(node.func)
    return None


def _looks_like_mark(target: tuple[str, str] | None, attrs: frozenset[str]) -> bool:
    if not target or target[1] not in attrs:
        return False
    head = target[0]
    return "mark" in head or head in ("", "pytest", "unittest")


def _reason_of(node: ast.AST | None) -> tuple[str, str]:
    """枚自身 reason 字面量（**f-string 常量段折叠**＝教义 2）＋取法形态。"""
    value: ast.AST | None = None
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "reason":
                value = kw.value
                break
        if value is None and node.args:
            value = node.args[0]
    if value is None:
        return ("", "none")
    return _fold(value)


def _fold(node: ast.AST | None) -> tuple[str, str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value, "literal")
    if isinstance(node, ast.JoinedStr):
        return ("".join(v.value for v in node.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)), "folded-fstring")
    if isinstance(node, ast.BinOp):
        left, lf = _fold(node.left)
        right, _ = _fold(node.right)
        return (left + right, "folded-concat" if lf == "literal" else lf)
    return ("", "dynamic")


def _host_of(path: tuple[ast.AST, ...]) -> str:
    for node in reversed(path):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
    return "<module>"


def _guard_of(path: tuple[ast.AST, ...]) -> str:
    for node in reversed(path):
        if isinstance(node, ast.If):
            return "if"
        if isinstance(node, ast.ExceptHandler):
            return "except"
    return "none"


def _walk(node: ast.AST, path: tuple[ast.AST, ...]):
    yield node, path
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, path + (child,))


def scan_source(text: str, rel: str) -> list[Marker]:
    """一个 .py → 该文件全部标记。语法坏 ⇒ 抛给调用方（响亮），**绝不静默跳过**。"""
    tree = ast.parse(text, filename=rel)
    out: list[Marker] = []

    # 装饰器位与标记变量定义位本身都是 ast.Call，不许再被运行时分支数第二遍。
    occupied: set[int] = set()
    marker_vars: dict[str, Marker] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                occupied.update(id(x) for x in ast.walk(dec))
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "pytestmark" in names:
                occupied.update(id(x) for x in ast.walk(node.value))
                continue
            if _looks_like_mark(_mark_target(node.value), MARK_ATTRS):
                reason, rf = _reason_of(node.value)
                var_name = next((n for n in names if n != "pytestmark"), "")
                if var_name:
                    marker_vars[var_name] = Marker(rel, node.value.lineno, _mark_target(node.value)[1],  # type: ignore[index]
                                                   "marker-variable", "none", "<module>", reason, rf, True)
                    occupied.update(id(x) for x in ast.walk(node.value))

    for _var_name, mk in sorted(marker_vars.items()):
        out.append(mk)

    for node, path in _walk(tree, ()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id in marker_vars:
                    var = marker_vars[dec.id]
                    out.append(Marker(rel, dec.lineno, var.kind, "named-decorator", "none",
                                      _host_of(path + (node,)), var.reason, var.reason_form, False))
                    continue
                if _looks_like_mark(_mark_target(dec), frozenset({"expectedFailure"})):
                    out.append(Marker(rel, dec.lineno, "xfail", "unittest-expectedFailure", "none",
                                      _host_of(path + (node,)), "", "none", True))
                    continue
                target = _mark_target(dec)
                if not _looks_like_mark(target, MARK_ATTRS):
                    continue
                assert target is not None
                reason, rf = _reason_of(dec)
                out.append(Marker(rel, dec.lineno, target[1],
                                  "decorator" if isinstance(dec, ast.Call) else "decorator-bare",
                                  "none", _host_of(path + (node,)), reason, rf, True))
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "pytestmark" not in names:
                continue
            items = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
            for item in items:
                if isinstance(item, ast.Name) and item.id in marker_vars:
                    var = marker_vars[item.id]
                    out.append(Marker(rel, item.lineno, var.kind, "pytestmark-named", "none",
                                      "<module>", var.reason, var.reason_form, False))
                    continue
                target = _mark_target(item)
                if not _looks_like_mark(target, MARK_ATTRS):
                    continue
                assert target is not None
                reason, rf = _reason_of(item)
                out.append(Marker(rel, item.lineno, target[1], "pytestmark", "none",
                                  "<module>", reason, rf, True))
        elif isinstance(node, ast.Call) and id(node) not in occupied:
            target = _mark_target(node.func)
            if not target or target[1] not in RUNTIME_ATTRS:
                continue
            head = target[0]
            if head and "pytest" not in head:
                continue
            reason, rf = _reason_of(node)
            out.append(Marker(rel, node.lineno, target[1], "runtime", _guard_of(path),
                              _host_of(path), reason, rf, True))
    return out


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------

CLASS_EXPIRED: Final[str] = "到期"
CLASS_INCOMPLETE: Final[str] = "缺登记"


def judge(marker: Marker, today: datetime) -> list[str]:
    """一枚标记 → 违规说明列表（空＝合规）。两类红分开拼，绝不合并计数。"""
    if not marker.needs_calendar:
        return []
    text = marker.reason
    problems: list[str] = []

    m_exp = RE_EXPIRY.search(text)
    raw = m_exp.group(1).strip() if m_exp else ""
    if not raw:
        problems.append(f"{CLASS_EXPIRED}：reason 里没有 `expiry=`（缺失按已过期处理＝fail-closed）")
    else:
        try:
            moment = parse_moment(raw, field="〔expiry=〕")
        except MomentParseError as exc:
            problems.append(f"{CLASS_EXPIRED}：`expiry={raw}` 读不懂（{exc}）——不可解析按已过期处理")
        else:
            if moment <= today:
                problems.append(f"{CLASS_EXPIRED}：`expiry={raw}` 已于 {moment:%Y-%m-%d} 到期未摘牌")

    m_own = RE_OWNER.search(text)
    own = m_own.group(1).strip() if m_own else ""
    # 第二道占位判据不只看锚定全等：补齐表本身写作 `owner=〔待她点名〕`，
    # 谁把它原样贴进 reason 就当场绿了——那正是本门要拦的形状。
    if not own:
        problems.append(f"{CLASS_INCOMPLETE}：reason 里没有 `owner=`")
    elif RE_OWNER_PLACEHOLDER.match(own) or "待" in own or "〔" in own:
        problems.append(f"{CLASS_INCOMPLETE}：`owner={own}` 是占位词/模板残留、不是归属（填表式合规＝本门拒收）")
    elif RE_TICKET_POINTER.match(own):
        problems.append(f"{CLASS_INCOMPLETE}：`owner={own}` 是工单指针、不是能动手的人/席（要写 SEAT-* 或姓名）")

    if not RE_DROP.search(text):
        problems.append(f"{CLASS_INCOMPLETE}：reason 里没有 `摘牌=`（写清什么落地了就删本标记）")
    return problems


def collect(root: Path) -> list[Marker]:
    """扫 SCAN_ROOTS，返回全部标记（逐文件即读即弃，不驻正文）。"""
    found: list[Marker] = []
    for sub in SCAN_ROOTS:
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if SKIP_DIR_NAMES & set(path.parts):
                continue
            rel = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:  # 读不到 ⇒ 响亮，不许静默漏面
                raise AssertionError(f"延账门读不到 {rel}：{exc}") from exc
            try:
                found.extend(scan_source(text, rel))
            except SyntaxError as exc:
                raise AssertionError(f"延账门在 {rel} 处语法坏（面不完整＝本门拒判）：{exc}") from exc
    return found


def report(markers: list[Marker], today: datetime) -> list[str]:
    """**一枚挂账恰好一行**（不是"一个问题一行"）。

    首版按问题拆行 ⇒ 13 枚报成 30 多行，"建门当天必红 13 行"当场对不上数。
    账的单位是标记、不是缺件：一枚一行才数得清"还剩几枚没摘"。
    """
    rows: list[str] = []
    for marker in markers:
        problems = judge(marker, today)
        if problems:
            rows.append(f"{marker.at} ⇒ " + "；".join(problems))
    return sorted(rows)


TODAY = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

#: 今天需要日历的枚数（现算锁的下界）。**这条不许往下调**：它存在的全部意义是
#: "尺还在数得到东西"——若哪天挂账清零，本锁随之作废，那时**删掉本锁与整件**，
#: 而不是把数字改成 0 让门继续空转（空转门＝本波反复点名的"在册不执法"）。
NEEDS_CALENDAR_FLOOR: Final[int] = 13


# --------------------------------------------------------------------------
# 主判据
# --------------------------------------------------------------------------


def test_every_deferred_marker_carries_expiry_owner_and_removal_condition() -> None:
    """主判据：需要日历的每一枚都必须带全三件，且日子还没过。"""
    offenders = report(collect(REPO_ROOT), TODAY)
    assert not offenders, (
        f"测试挂账到期门：{len(offenders)} 行违规。\n"
        + "\n".join(offenders)
        + "\n\n续期＝把 reason 里的 `expiry=` 改成新日子（改的人就是 owner）；"
          "摘牌＝前提落地后删掉本标记。本门**没有**自动放宽通道。"
    )


def test_the_ruler_actually_sees_the_deferred_population() -> None:
    """反空跑锁：射程内的枚数必须 ≥ 下界。

    没有这条，主判据可以靠"一枚都没扫到"而绿——那正是本波反复出现的
    "存在性糊过活性判据"（紧急域 `nmc:A1` 那枚 Critical 的同型）。
    """
    need = [m for m in collect(REPO_ROOT) if m.needs_calendar]
    assert len(need) >= NEEDS_CALENDAR_FLOOR, (
        f"延账门射程塌了：现算 {len(need)} 枚 < 下界 {NEEDS_CALENDAR_FLOOR} 枚 ⇒ "
        "要么尺瞎了（取数面被改动），要么挂账真的清零了——后者请连本件一起删除，"
        "不要放下界让门继续空转。"
    )


# --------------------------------------------------------------------------
# 正对照与注毒自证（全部建在 tmp_path，绝不碰仓库正文）
# --------------------------------------------------------------------------

_GOOD = '@pytest.mark.xfail(reason="缺口。〔expiry=2099-01-01 owner=SEAT-GATE-TEST 摘牌=落地后删〕")'
_BAD_EXPIRED = '@pytest.mark.xfail(reason="缺口。〔expiry=2000-01-01 owner=SEAT-GATE-TEST 摘牌=落地后删〕")'
_NO_EXPIRY = '@pytest.mark.xfail(reason="缺口，没写日子")'


def _write(tmp_path: Path, body: str) -> Path:
    """把一段用例文本落成 tmp 里的 `tests/` 件，返回**可交给 collect() 的 root**。"""
    tests = tmp_path / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "case_under_gate.py").write_text(
        "import pytest\n\n" + body + "\ndef test_x():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def test_positive_control_a_compliant_marker_is_green(tmp_path: Path) -> None:
    """正对照①：三件齐全且日子在未来 ⇒ 必须绿（门不许"顺手放行别的"，也不许诬它）。"""
    offenders = report(collect(_write(tmp_path, _GOOD)), TODAY)
    assert offenders == [], f"合规标记被诬：{offenders}"


def test_positive_control_b_missing_expiry_is_red(tmp_path: Path) -> None:
    """正对照②＝注毒一发：删掉 `expiry=` ⇒ 必红，且红在"到期"这一类。

    这条同时是"0 枚过期"这句话的**必然非空对照**：同一个判据在同一种数据上判得出红，
    所以真树那个 0 不可能是尺瞎。
    """
    offenders = report(collect(_write(tmp_path, _NO_EXPIRY)), TODAY)
    assert len(offenders) == 1, f"一枚挂账必须恰好一行，实得 {offenders}"
    assert CLASS_EXPIRED in offenders[0], offenders


def test_poison_expiry_date_in_the_past_is_red(tmp_path: Path) -> None:
    """注毒二发：日子写在过去 ⇒ 必红（"到期即红"是唯一的红法）。"""
    offenders = report(collect(_write(tmp_path, _BAD_EXPIRED)), TODAY)
    assert len(offenders) == 1 and CLASS_EXPIRED in offenders[0], offenders


def test_poison_date_only_in_a_comment_is_still_red(tmp_path: Path) -> None:
    """注毒三发：日期只写在上方注释里 ⇒ **仍须红**（防"隔壁注释糊门"）。"""
    body = '# 〔expiry=2099-01-01 owner=SEAT-GATE-TEST 摘牌=x〕\n' + _NO_EXPIRY
    offenders = report(collect(_write(tmp_path, body)), TODAY)
    assert len(offenders) == 1 and CLASS_EXPIRED in offenders[0], offenders
    assert "2099" not in offenders[0], f"邻近注释里的日子被当成本枚到期日（假阳）：{offenders[0]}"


def test_poison_ticket_number_is_not_an_owner(tmp_path: Path) -> None:
    """工单号不是 owner：`owner=M-28` 必红，且红在"缺登记"这一类、不在"到期"。"""
    body = '@pytest.mark.xfail(reason="缺口。〔expiry=2099-01-01 owner=M-28 摘牌=落地后删〕")'
    offenders = report(collect(_write(tmp_path, body)), TODAY)
    assert len(offenders) == 1, offenders
    assert CLASS_INCOMPLETE in offenders[0] and CLASS_EXPIRED not in offenders[0], offenders


def test_poison_placeholder_owner_is_still_red(tmp_path: Path) -> None:
    """注毒：`owner=待点名` 这种占位词**不许把门刷绿**。

    本席首版没有这一腿——那时 13 枚只要各自写一遍 `owner=待点名` 就当场"三件齐全"，
    门会绿、主还是一个都没有。占位词按非归属处理（与"工单指针"分开报，两者修法不同：
    前者要**点名到人**，后者要**补上人的名字**）。
    """
    for placeholder in ("待点名", "待裁", "TODO", "无", "〔待她点名〕", "待定席"):
        body = (
            '@pytest.mark.xfail(reason="缺口。〔expiry=2099-01-01 '
            f'owner={placeholder} 摘牌=落地后删〕")'
        )
        offenders = report(collect(_write(tmp_path, body)), TODAY)
        assert len(offenders) == 1 and CLASS_INCOMPLETE in offenders[0], (placeholder, offenders)
        assert "占位" in offenders[0], offenders

def test_poison_unparseable_date_fails_closed(tmp_path: Path) -> None:
    """日子写了但读不懂 ⇒ 按已过期处理（不许折成"没写＝没事"）。"""
    body = '@pytest.mark.xfail(reason="缺口。〔expiry=2099-13-45 owner=SEAT-GATE-TEST 摘牌=落地后删〕")'
    offenders = report(collect(_write(tmp_path, body)), TODAY)
    assert len(offenders) == 1 and CLASS_EXPIRED in offenders[0], offenders


def test_fstring_expiry_is_folded_and_honoured(tmp_path: Path) -> None:
    """绕行道反向锁：三件写在 f-string 里 ⇒ 必须**看得见**（未来日子 ⇒ 绿）。

    不折叠 f-string 的尺会把这枚判成"没写日子"而红——那是假红；
    反过来若门只认字面量，谁都可以用 `f"expiry=…"` 造一条看不见的路。
    """
    body = ('x = 1\n@pytest.mark.xfail(f"缺口 〔expiry=2099-01-01 owner=SEAT-GATE-TEST 摘牌=落地后删〕 {x}")')
    offenders = report(collect(_write(tmp_path, body)), TODAY)
    assert offenders == [], f"f-string 里的三件没被折出来：{offenders}"


def test_named_marker_variable_is_judged_once_at_its_definition(tmp_path: Path) -> None:
    """具名标记变量（`bad = pytest.mark.xfail(...)` + `@bad`）⇒ 只在定义位判一次。

    这一形是两把独立尺对账时抓出来的隐身道（S503 首版漏计、S381 只计定义位）：
    只数装饰器位的尺会**完全看不见**它，而一处定义可以给任意多个用例发免罪金牌。
    """
    body = (
        'bad = pytest.mark.xfail("缺口，没写日子")\n'
        "@bad\n"
        "def test_one(): ...\n"
        "@bad\n"
        "def test_two(): ...\n"
    )
    markers = collect(_write(tmp_path, body))
    judged = [m for m in markers if m.needs_calendar]
    assert len(judged) == 1, f"定义位应判一次，实得 {[(m.at) for m in judged]}"
    offenders = report(markers, TODAY)
    assert len(offenders) == 1, f"两处使用位不该各记一笔账：{offenders}"
    assert CLASS_EXPIRED in offenders[0], offenders


@pytest.mark.parametrize(
    "body",
    [
        'pytestmark = pytest.mark.skipif(True, reason="平台条件，自解")',
        '@pytest.mark.skipif(True, reason="缺 ffmpeg")',
        'def _f():\n    try:\n        import zzz\n    except ImportError:\n        pytest.skip("缺依赖")',
        'def _f():\n    if not hasattr(pytest, "zzz"):\n        pytest.skip("条件自解")',
    ],
    ids=["pytestmark-skipif", "decorator-skipif", "skip-in-except", "skip-in-if"],
)
def test_self_resolving_family_is_never_demanded(tmp_path: Path, body: str) -> None:
    """豁免面写死：条件自解族**不要求日历**，也不许因为"没写三件"被诬。

    反向半句（教义 1 的另一腿）：给自解族补上 `expiry=` 也不会让它变得"更合规才算有主"，
    本门对它们零要求 ⇒ 没人会被逼着给 55 枚自解标记灌水式补日子。
    """
    markers = collect(_write(tmp_path, body))
    assert [m for m in markers if m.needs_calendar] == [], "自解族被误纳入射程＝会把门刷成噪声"
    assert report(markers, TODAY) == []


def test_direction_lock_aging_today_turns_every_row_red(tmp_path: Path) -> None:
    """方向锁：把"今天"推到 2100 年 ⇒ 合规那枚必须变红（证明判据真的由日历驱动）。

    这条否掉的是"门只是检查有没有写 `expiry=` 这个 token"那种假牙写法——
    写了个过期日子必须打得过没写，否则到期这件事仍然不存在。
    """
    future_2100 = datetime(2100, 1, 1, tzinfo=timezone.utc)
    root = _write(tmp_path, _GOOD)
    assert report(collect(root), TODAY) == []
    offenders = report(collect(root), future_2100)
    assert len(offenders) == 1 and CLASS_EXPIRED in offenders[0], offenders


def test_defer_expiry_gate_uses_single_moment_parser() -> None:
    """本件自己不许造第二套时刻解析（教义 7）。

    判据扫的是 **AST 里被调用的属性名**，不是整篇正文——本席首版写成
    `"fromisoformat" not in source`，被自己 docstring 里"不许出现 fromisoformat"
    这几个字当场打红：**禁词有权出现在说明里，代码无权调用它**。
    同一枚锁再正向确认中央件真的被调用（只在 import 里挂个名＝在册不执法）。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    called_attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "fromisoformat" not in called_attrs, (
        "延账门自造时刻解析＝第二真身。唯一真身是 "
        "plugins/bot_unified_runtime/domains/core/moment_parsing.parse_moment"
    )
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "parse_moment" in called_names, "本件必须真的调用中央件，不许只 import 挂着"

# ==========================================================================
# 替代锁（用户裁定 R-250925-9 第 3 格 ＋ §2.③ 更正）——摘牌腿放宽的补偿
# ==========================================================================
#
# 被放宽的那条腿：本门对「摘牌」认**显式 `摘牌=` 键或 reason 散文里的触发语**二者之一
# （见 `RE_DROP`）。放宽的理由＝硬账是**日子**，把已经写清"怎么摘"的枚逼成再抄一遍
# `摘牌=` 只会造出填表式合规。
#
# 放宽丢掉判据的唯一一处：同一条 reason 串被复用到多枚标记上时，"这条摘牌条件挂在哪一枚"
# 就含糊了。本锁补的正是这一格——**每条写了日子的 reason，必须恰好锚定一枚标记
# （`file + line + kind` 三键唯一）；锚不定即红。**
#
# 🔴 **本锁禁删**（裁定原文：「这条要带"不许删"标记」）。"禁删"不靠散文生效：
#    `test_replacement_anchor_lock_is_wired_and_not_removable` 用 AST 现算执法——
#    改名、删函数、把生产判据里的调用摘掉、或换成自建第二把尺，都会当场红。
#
# ⚠ 判据对象＝**reason 全文**，不是 `expiry=` 之后的子句（§2.③ 更正，`probes/s538-anchorlock.py`
#   实跑证死）：按子句判 ⇒ §七 的统一模板（13 枚都写 `expiry=2026-12-24`）会把 13 枚**撞成
#   一组、门自己红成一片**。按全文判 ⇒ 今树与贴完之后都是 0 组冲突，今天不咬、将来真撞了才咬。

#: 本锁的键面沿用门件自己的 `RE_EXPIRY`（不新建第二份键表）——裁定原文写的是"含 `expiry=` 的
#: reason"，本锁取**不窄于该口径**的一档：凡本门认得的到期键族（`expiry`/`到期日`/`有效期至`/
#: `截止日`）写了日子的挂账都进锚定面。放宽一处键写法的同时把补偿面收窄，会留一条绕行道。


def reason_groups_needing_anchor(markers: list[Marker]) -> dict[str, list[tuple[str, int, str]]]:
    """按 **reason 全文** 归组，只收「射程内（needs_calendar）且写了日子」的挂账。

    射程判据直接取 `Marker.needs_calendar`（与主判据同一把尺、同一个口径）：
    具名标记变量的**使用位** `judged=False` ⇒ 天然不进本锁，不会把"一处定义、多处使用"
    误报成"一条 reason 挂两枚"。
    """
    groups: dict[str, list[tuple[str, int, str]]] = {}
    for marker in markers:
        if not marker.needs_calendar:
            continue
        if not RE_EXPIRY.search(marker.reason):
            continue
        groups.setdefault(marker.reason, []).append((marker.rel, marker.line, marker.kind))
    return groups


def anchor_conflict_rows(markers: list[Marker]) -> list[str]:
    """写了日子的 reason 里，锚不定到恰好一枚标记的那些组 ⇒ 每人一行说明。"""
    rows: list[str] = []
    for reason, triples in reason_groups_needing_anchor(markers).items():
        unique = sorted(set(triples))
        if len(unique) > 1:
            where = "、".join(f"{rel}:{line}（{kind}）" for rel, line, kind in unique)
            rows.append(f"同一条 reason 挂了 {len(unique)} 枚标记 ⇒ 摘牌归属锚不定：{where}"
                        f"｜reason 全文＝{reason[:72]!r}")
    return sorted(rows)


def test_each_dated_reason_anchors_exactly_one_marker() -> None:
    """生产判据：全树每一组"写了日子的 reason"都必须恰好锚定一枚标记。**本锁禁删。**"""
    conflicts = anchor_conflict_rows(collect(REPO_ROOT))
    assert not conflicts, (
        f"摘牌归属锚定门（放宽摘牌腿的替代锁）：{len(conflicts)} 组冲突。\n"
        + "\n".join(conflicts)
        + "\n\n修法＝给每一枚各自写清它自己的 reason（日子可以同一天，**全文不许雷同**）；"
          "本锁没有豁免通道，也**不许删本锁换绿**。"
    )


def _anchor_fixture(tmp_path: Path, body: str) -> list[Marker]:
    """把一段用例文本落成 tmp 里的 `tests/` 件并返回其标记（与 `_write` 同一走法）。"""
    return collect(_write(tmp_path, body))


def test_replacement_lock_bites_when_one_reason_anchors_two_markers(tmp_path: Path) -> None:
    """注毒：两枚挂账共用**同一条写了日子的** reason ⇒ 本锁必须报 1 组冲突并点名两枚位置。

    这一发就是"放宽摘牌腿"唯一丢掉的判据；报不出来 ⇒ 放宽是白放宽（本锁成了空转）。
    """
    body = (
        '@pytest.mark.xfail(reason="同一句话挂两枚。〔expiry=2099-01-01 owner=SEAT-GATE-TEST 摘牌=落地后删〕")\n'
        "def test_a():\n    assert True\n\n"
        '@pytest.mark.xfail(reason="同一句话挂两枚。〔expiry=2099-01-01 owner=SEAT-GATE-TEST 摘牌=落地后删〕")\n'
        "def test_b():\n    assert True\n"
    )
    rows = anchor_conflict_rows(_anchor_fixture(tmp_path, body))
    assert len(rows) == 1, f"一条 reason 挂两枚必须恰好报一组，实得 {rows}"
    assert "case_under_gate.py" in rows[0], rows
    assert rows[0].count("case_under_gate.py") == 2, f"两枚位置都要点名：{rows[0]}"
    assert "摘牌归属锚不定" in rows[0], rows


def test_replacement_lock_still_reports_the_missing_drop_leg(tmp_path: Path) -> None:
    """注毒反向半句：只写日子、**不写 `摘牌=` 也没有散文触发语**的两枚复用同一串 ⇒
    本锁与"缺摘牌"那条腿各报各的，本锁不许因为摘牌腿已红就沉默。"""
    body = (
        '@pytest.mark.xfail(reason="缺口两句一样。〔expiry=2099-01-01 owner=SEAT-GATE-TEST〕")\n'
        "def test_a():\n    assert True\n\n"
        '@pytest.mark.xfail(reason="缺口两句一样。〔expiry=2099-01-01 owner=SEAT-GATE-TEST〕")\n'
        "def test_b():\n    assert True\n"
    )
    markers = _anchor_fixture(tmp_path, body)
    assert len(anchor_conflict_rows(markers)) == 1, anchor_conflict_rows(markers)
    dropped = report(markers, TODAY)
    assert len(dropped) == 2 and all(CLASS_INCOMPLETE in row for row in dropped), dropped


def test_replacement_lock_full_text_key_never_punishes_a_shared_date(tmp_path: Path) -> None:
    """§2.③ 更正的正对照：三枚**日子同一天、全文各不相同** ⇒ 本锁必须 0 组。

    按 `expiry=` 子句判的话这一形必撞（§七 统一模板就是这个形状）。今天不咬、将来真撞才咬。
    """
    body = "\n\n".join(
        f'@pytest.mark.xfail(reason="缺口 {i} 号，各自的摘牌线索。'
        f'〔expiry=2026-12-24 owner=SEAT-GATE-TEST 摘牌=第 {i} 号前提落地后删〕")\n'
        f"def test_{name}():\n    assert True"
        for i, name in ((1, "one"), (2, "two"), (3, "three"))
    )
    rows = anchor_conflict_rows(_anchor_fixture(tmp_path, body))
    assert rows == [], f"同一天的日子被判成撞锁＝按子句判了（本锁禁这种判法）：{rows}"


def test_replacement_lock_scope_is_dated_markers_only(tmp_path: Path) -> None:
    """口径锁：没写日子的挂账**不进**本锁（裁定原文＝"每条含 `expiry=` 的 reason"）。

    反向确认它们没因此逃掉执法：同一批标记在主判据下仍是"到期＋缺登记"红——
    本锁只管归属含糊，不管缺日子（那是 `到期` 那一类的账）。
    """
    body = (
        '@pytest.mark.xfail(reason="完全相同的一句，谁都没写日子")\n'
        "def test_a():\n    assert True\n\n"
        '@pytest.mark.xfail(reason="完全相同的一句，谁都没写日子")\n'
        "def test_b():\n    assert True\n"
    )
    markers = _anchor_fixture(tmp_path, body)
    assert anchor_conflict_rows(markers) == [], "未写日子的挂账被纳进本锁＝越出裁定口径"
    offenders = report(markers, TODAY)
    assert len(offenders) == 2 and all(CLASS_EXPIRED in row for row in offenders), offenders


def test_replacement_lock_is_self_resolving_family_out_of_scope(tmp_path: Path) -> None:
    """豁免面同款：`skipif` 等条件自解族即使共用一条带日子的 reason 也不进本锁
    （教义 1：本门对它们零要求）。这一发防的是"放宽面与豁免面被本锁悄悄改宽"。"""
    body = (
        '@pytest.mark.skipif(True, reason="平台都缺这个。〔expiry=2099-01-01〕")\n'
        "def test_a():\n    assert True\n\n"
        '@pytest.mark.skipif(True, reason="平台都缺这个。〔expiry=2099-01-01〕")\n'
        "def test_b():\n    assert True\n"
    )
    markers = _anchor_fixture(tmp_path, body)
    assert [m for m in markers if m.needs_calendar] == [], "自解族被拉进射程"
    assert anchor_conflict_rows(markers) == [], anchor_conflict_rows(markers)


def test_replacement_anchor_lock_is_wired_and_not_removable() -> None:
    """"禁删"这一句的执法腿（AST 现算，不靠散文承诺）。

    本仓反复出现的失效形态是**在册不执法**：锁写在文件里、生产判据却没接上它，
    或被人改名/摘调用后只剩一个空函数。本锁把三件事钉在一起查：
    ①生产判据函数在场且真的调用归属谓词；②归属谓词真的用门件自己那把尺取数
    （`collect`）+ 自己的键表（`RE_EXPIRY`）+ 自己的射程判据（`needs_calendar`），
    **不许自建第二把尺**；③判据按 reason **全文**归组，且文件里**不存在按子句切串的写法**
    （§2.③ 更正否掉的就是那一形）。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for required in (
        "test_each_dated_reason_anchors_exactly_one_marker",
        "reason_groups_needing_anchor",
        "anchor_conflict_rows",
    ):
        assert required in funcs, f"替代锁被删或改名（本锁禁删）：缺 {required}"

    def call_targets(node: ast.AST) -> set[str]:
        out: set[str] = set()
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            if isinstance(call.func, ast.Name):
                out.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                out.add(call.func.attr)
        return out

    def attributes(node: ast.AST) -> set[str]:
        return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}

    def loaded_names(node: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    prod = funcs["test_each_dated_reason_anchors_exactly_one_marker"]
    assert "anchor_conflict_rows" in call_targets(prod), "生产判据没真的调用归属谓词＝在册不执法"
    assert "collect" in call_targets(prod), "生产判据必须走门件唯一取数口 collect()"

    ruler = funcs["reason_groups_needing_anchor"]
    assert "search" in call_targets(ruler) and "RE_EXPIRY" in loaded_names(ruler), (
        "归属面换成了第二份到期键表＝第二真身（唯一真身是本件的 RE_EXPIRY）"
    )
    assert "needs_calendar" in attributes(ruler), "归属面没走主判据同一个射程判据"
    assert "reason" in attributes(ruler), "归组键必须是 reason 全文"
    # 反向半句：一旦有人改回"按 expiry= 子句判"，这两形必然出现在取数面里。
    sliced_reason = [
        n for n in ast.walk(ruler)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Attribute)
        and n.value.attr == "reason"
    ]
    assert not sliced_reason, "归组函数里出现对 reason 的切片＝按子句判（§2.③ 已否掉的写法）"
    assert "index" not in call_targets(ruler), "归组函数里出现 str.index 定位＝按子句判"
