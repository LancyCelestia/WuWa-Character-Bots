"""命令目录生成器 **CLI 只读校验模式**的常驻执法门（席位 S277，2026-09-25）。

病灶（「机制存在但不执法」那一型，mandate 见 ``BRIEFS-250925-R.md`` §S277）：
``scripts/command_catalog.py`` 的只读校验模式今天没有任何 pytest 级常驻门执行它。
现算的三条在册事实（本席 2026-09-24T21:43Z 自己跑出来的，不沿用简报数字）：

1. ``conftest.py`` 的 autosync 钩子与 ``dev.ps1 -Task sync`` 只跑 ``--write``
   ——**写不等于检查**，漂移在写的那一刻被吸收成新基线；
2. ``tests/test_cross_validation_gates.py`` 对 ``verify_hashes.py`` 与
   ``doc_sync.py`` 各跑一次 ``--check``，**唯独没有 command_catalog 这一件**
   （该文件是 S246R 在飞写面，本席只读不动它）；
3. ``tests/test_documentation_consistency.py::test_catalog_document_matches_registry``
   比的是**库内** ``render(merged_entries())`` 与盘面对照（内容层，不经 ``main()``），
   所以「CLI 的判定与退出码」「校验模式真的不写盘」「失败时说得出哪几行漂了」
   这三件事至今无人执法。

本件只补那三件，不复制第 3 条已有的内容层对照（禁造重叠尺）。

关于 ``--check`` 这个旗标的实况（写在这里以免后人误读）：该生成器**没有** argparse，
``main()`` 只判 ``"--write" in sys.argv[1:]``，其余任何参数（含 ``--check``）都被当作
「不带 --write」即校验模式放过。⇒ 本门不依赖那个旗标的"存在"，而是钉死它的
**行为**：旗标态与裸调用态判定必等、且两态都不得改盘一个字节
（见 ``test_bare_invocation_and_check_flag_agree``）。

纪律（AGENTS 规则 10）：本件**故意不断言** topic / 别名 / 行数这类会随代码漂移的计数，
现值一律以生成物与机器册 ``docs/auto-facts.md`` 为准。
纪律（造绿六禁）：本件禁 xfail / skip / 放宽判据 / 「漂移就自动重录放行」，
并由 ``test_this_file_carries_no_escape_hatch`` 用 AST 逐条执法（删测试、加出口、
在本文件里调 ``--write``、在 ``test_*`` 里写 ``except`` 吞红因，都会当场红）。
"""

from __future__ import annotations

import ast
import difflib
import filecmp
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# 只借生成器自己的取数口与渲染口来**格式化诊断差异**；判定权全在 CLI 退出码。
# 不在本件重抄任何渲染逻辑（那才是第二事实源）。
import command_catalog as cc  # 纯 stdlib，不 import 插件包

CATALOG_SCRIPT = ROOT / "scripts" / "command_catalog.py"
ARTIFACT = ROOT / "docs" / "command-catalog.md"

#: 生成器自己的只读校验旗标（无 argparse，见模块 docstring 的实况说明）。
CHECK_FLAG = "--check"
#: 生成器的**唯一**写盘旗标。本件任何一处把它送进子进程都属越权重录，
#: 由 ``test_this_file_carries_no_escape_hatch`` 结构性禁止。
WRITE_FLAG = "--write"
#: ``WRITE_FLAG`` 的**变量名**。本件只允许两处提到它：它自己的赋值、以及反自豁免那发门。
#: 想在别处拿它去调子进程（＝把校验门改成自动重录）会当场红。
WRITE_FLAG_NAME = "WRITE_FLAG"

_TIMEOUT_SECONDS = 180
#: 失败报告里最多展示多少行差异。这只是**展示上限**，不影响判定，
#: 且未展示的行数会明确写出来（不静默截断）。
_MAX_DIFF_LINES = 80

#: 本件必须存在的执法测试名。少任何一个（被删、被改名）＝门自残，先红。
REQUIRED_TESTS: tuple[str, ...] = (
    "test_gate_and_generator_point_at_the_same_artifact",
    "test_catalog_check_writes_nothing",
    "test_bare_invocation_and_check_flag_agree",
    "test_catalog_check_exits_zero",
    "test_failure_report_lists_diff_lines",
    "test_poison_one_byte_turns_the_gate_red_and_restore_returns_verdict",
    "test_this_file_carries_no_escape_hatch",
)

#: 反自豁免那发门自己的名字（引用面判据要用它划出"允许区"）。
SELF_LOCK_NAME = "test_this_file_carries_no_escape_hatch"

#: 出口形态黑名单：属性名/装饰器名命中即红。
_FORBIDDEN_EXIT_NAMES: frozenset[str] = frozenset(
    {
        "skip",
        "skipif",
        "skipIf",
        "skipUnless",
        "xfail",
        "importorskip",
        "fail",  # pytest.fail 用来绕过判定同样是不执法
    }
)


# ---------------------------------------------------------------------------
# 子进程：encoding / cwd / env 三样必须钉死（本仓有 GBK 崩的前例）
# ---------------------------------------------------------------------------


def _child_env() -> dict[str, str]:
    """构造钉死的子进程环境。

    - ``PYTHONIOENCODING=utf-8`` + ``-X utf8``：子进程**写出**侧不按 locale(GBK) 编；
    - ``PYTHONDONTWRITEBYTECODE`` / ``PYTHONPYCACHEPREFIX``：绕开 dev.ps1 直跑时
      不把 ``__pycache__`` 落进源码树（AGENTS 规则 6）；
    - ``BOT_AUTOSYNC=0``：绝不让任何自动重录被本门顺带触发。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = env.get("PYTHONPYCACHEPREFIX") or str(
        Path(tempfile.gettempdir()) / "chatbot-s277-pycache"
    )
    env["BOT_AUTOSYNC"] = "0"
    return env


def _run_catalog_cli(flag: str | None = None) -> subprocess.CompletedProcess[str]:
    """跑生成器本体。``flag=None`` 为裸调用（同为校验模式）。

    ``encoding`` 与 ``errors`` 两端都钉：父进程若按 locale 解码中日韩输出，会在 reader
    线程抛 UnicodeDecodeError ⇒ ``stderr`` 变 ``None`` ⇒ 真红被报成"只能拼接 str"
    （台账 #47 登记的 systemic 缺陷族；模范写法 ``tests/test_verify_hashes_coverage.py``）。
    """
    argv = [sys.executable, "-X", "utf8", str(CATALOG_SCRIPT)]
    if flag is not None:
        argv.append(flag)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_SECONDS,
        cwd=str(ROOT),
        env=_child_env(),
        check=False,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _read_artifact_bytes() -> bytes:
    return ARTIFACT.read_bytes() if ARTIFACT.exists() else b""


# ---------------------------------------------------------------------------
# 差异格式化（纯函数，零写盘；判定权不在此处）
# ---------------------------------------------------------------------------


def _diff_lines(expected_text: str, actual_text: str) -> list[str]:
    """期望（生成器会写成的样子）vs 现状（盘上）的逐行差异。"""
    return list(
        difflib.unified_diff(
            expected_text.splitlines(),
            actual_text.splitlines(),
            fromfile="生成器期望（--write 会写成这样）",
            tofile="盘上现状",
            lineterm="",
            n=2,
        )
    )


def _expected_text_or_marker() -> str:
    """进程内取期望文本；取不到时返回可诊断的占位，**绝不因此改判**。

    这里唯一的 ``except`` 在失败报告路径上：它不可能把红洗成绿（判定来自 CLI 退出码），
    只是防「并发席正写到一半 ⇒ 报告自身炸掉、真因被异常盖住」。
    """
    try:
        return cc.render(cc.merged_entries())
    except Exception as exc:  # noqa: BLE001  报告路径专用；见 AST 自锁的豁免说明
        return f"<<<进程内取期望文本失败：{type(exc).__name__}: {exc}>>>"


def _failure_report(result: subprocess.CompletedProcess[str], *, artifact_bytes: int) -> str:
    """失败时的完整人话报告：退出码 + 子进程原话 + 逐行差异，不许只给一个 EXIT=1。"""
    head = [
        f"scripts/command_catalog.py {CHECK_FLAG} 只读校验未通过。",
        f"- 退出码：{result.returncode}",
        "- 权威判据：CLI 自己的返回码（本报告的差异仅供定位，不参与判定）",
        f"- cwd={ROOT}",
        f"- 子进程编码：两端钉 utf-8（stdout={len(result.stdout or '')}B / stderr={len(result.stderr or '')}B）",
        f"- 生成物：{ARTIFACT.relative_to(ROOT).as_posix()}（{artifact_bytes} 字节）",
        f"- stdout：{(result.stdout or '').strip() or '（空）'}",
        f"- stderr：{(result.stderr or '').strip() or '（空）'}",
    ]
    actual = ARTIFACT.read_text(encoding="utf-8", errors="replace") if ARTIFACT.exists() else ""
    diff = _diff_lines(_expected_text_or_marker(), actual)
    if not diff:
        head.append(
            "- 逐行差异：**零行**。CLI 判过期、进程内渲染却逐行相同 ⇒ 两把尺分叉，"
            "或差异只落在行尾/编码这类 splitlines 看不见的层。"
            "请用 --write 到临时副本后按字节对照，别当误报放过。"
        )
        return "\n".join(head)
    shown = diff[:_MAX_DIFF_LINES]
    head.append(f"- 逐行差异（unified，共 {len(diff)} 行，以下列出前 {len(shown)} 行）：")
    head.extend(f"    {line}" for line in shown)
    if len(diff) > len(shown):
        head.append(f"    …另有 {len(diff) - len(shown)} 行差异未展示（展示上限 {_MAX_DIFF_LINES} 行）")
    head.append(
        "处置：先归因谁在飞的哪件没重录。**确认属预期改动**后才由该面 owner 跑 "
        "``python scripts/command_catalog.py --write`` 重录；本门自己永不写盘。"
    )
    return "\n".join(head)


def _assert_decoded_and_clean(result: subprocess.CompletedProcess[str]) -> None:
    """encoding 钉死的三条可机检后果：不是 None、不是乱码、没有 traceback。"""
    label = f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout is not None and result.stderr is not None, (
        f"子进程输出未被解码（None＝父进程按 locale 解码炸了，真因被吞）：{label}"
    )
    assert "\ufffd" not in result.stdout and "\ufffd" not in result.stderr, (
        f"输出含 U+FFFD 替换符＝编码两端没钉住，报告里的中文已不可信：{label}"
    )
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"生成器在校验模式下抛异常（崩溃被兜成退出码＝红因被掩盖）：{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 执法
# ---------------------------------------------------------------------------


def test_gate_and_generator_point_at_the_same_artifact() -> None:
    """防幻影尺：本门盯的生成物，必须就是生成器自己声明要写的那个文件。"""
    assert CATALOG_SCRIPT.is_file(), f"生成器不在这：{CATALOG_SCRIPT}"
    assert Path(cc.__file__).resolve() == CATALOG_SCRIPT.resolve(), (
        f"本门 import 的 command_catalog 与子进程跑的不是同一件："
        f"{Path(cc.__file__).resolve()} vs {CATALOG_SCRIPT.resolve()}"
    )
    assert Path(cc.DOC).resolve() == ARTIFACT.resolve(), (
        f"生成器写盘目标 {cc.DOC} ≠ 本门校验目标 {ARTIFACT} ⇒ 注毒打不到真身，全部判定作废"
    )
    assert ARTIFACT.is_file(), f"受管生成物不在盘上：{ARTIFACT}"


def test_catalog_check_writes_nothing() -> None:
    """只读校验模式**一个字节都不许改**（防「check 顺手 --write」把漂移洗绿）。"""
    before = _read_artifact_bytes()
    result = _run_catalog_cli(CHECK_FLAG)
    after = _read_artifact_bytes()
    _assert_decoded_and_clean(result)
    assert _sha256(before) == _sha256(after), (
        f"{CHECK_FLAG} 模式改动了受管生成物（sha {_sha256(before)} → {_sha256(after)}，"
        f"{len(before)}B → {len(after)}B）⇒ 它不是只读模式，漂移会被自动吸收"
    )


def test_bare_invocation_and_check_flag_agree() -> None:
    """旗标态与裸调用态必等。

    该生成器没有 argparse、``--check`` 并非在册旗标（只判 ``--write``），所以本门钉的是
    **行为等值**而不是旗标存在：任何人把默认模式改成写盘、或让 ``--check`` 变成空转必过，
    这条与注毒那一发会当场红。
    """
    flagged = _run_catalog_cli(CHECK_FLAG)
    bytes_after_flagged = _read_artifact_bytes()
    bare = _run_catalog_cli(None)
    _assert_decoded_and_clean(flagged)
    _assert_decoded_and_clean(bare)
    assert flagged.returncode == bare.returncode, (
        f"{CHECK_FLAG} 与裸调用判定不等（{flagged.returncode} vs {bare.returncode}）："
        f"两态 stdout={flagged.stdout!r} / {bare.stdout!r}"
    )
    assert bytes_after_flagged == _read_artifact_bytes(), (
        "裸调用改动了受管生成物 ⇒ 默认模式不再是校验模式，"
        "「写」与「检查」将再也分不开（漂移会被静默吸收成新基线）"
    )


def test_catalog_check_exits_zero() -> None:
    """常驻判决：生成物与注册表一致 ⇒ 退出码 0；红了就把差异逐行打出来。"""
    artifact_bytes = len(_read_artifact_bytes())
    result = _run_catalog_cli(CHECK_FLAG)
    _assert_decoded_and_clean(result)
    assert result.returncode == 0, _failure_report(result, artifact_bytes=artifact_bytes)


def test_failure_report_lists_diff_lines() -> None:
    """判据②的独立牙：失败报告必须给出 +/- 行，不许只有一句 EXIT=1。

    用纯函数的差异格式化，零子进程、零写盘 ⇒ 本发与树上手不红无关。
    """
    expected = "标题\n\n- 甲\n- 乙\n- 丙\n"
    actual = "标题\n\n- 甲\n- 改了\n- 丙\n- 多出\n"
    diff = _diff_lines(expected, actual)
    assert any(line.startswith("-") and not line.startswith("---") for line in diff), diff
    assert any(line.startswith("+") and not line.startswith("+++") for line in diff), diff
    assert any("改了" in line for line in diff), f"差异报告里找不到真正漂了的那一行：{diff}"
    assert any("多出" in line for line in diff), f"新增行未进差异报告：{diff}"
    # 反向：完全一致时必须**不**造差异（否则"零差异却报漂移"会把归因带偏）。
    assert _diff_lines(expected, expected) == []


def test_poison_one_byte_turns_the_gate_red_and_restore_returns_verdict() -> None:
    """注毒一发（mandate ③）：改受管生成物一字节 ⇒ 本门必红；还原 ⇒ 判定回到改前。

    还原判据**不比"全树绿"**，只比"漂移面回到改前"——基线里若另有他件未重录
    （并发波常态），"全树绿"会把一次彻底还原误报成污染（同
    ``tests/test_verify_hashes_coverage.py`` 立的规矩）。
    字节等值用 ``filecmp.cmp(shallow=False)`` 证（= ``cmp``），不看 mtime。
    """
    original = _read_artifact_bytes()
    assert original, "受管生成物为空，注毒没有落点"
    with tempfile.TemporaryDirectory(prefix="s277-restore-") as tmp:
        pristine = Path(tmp) / "command-catalog.pristine"
        pristine.write_bytes(original)

        baseline = _run_catalog_cli(CHECK_FLAG)
        _assert_decoded_and_clean(baseline)
        assert baseline.returncode == 0, (
            f"演练起点不干净：受管生成物**在注毒之前**就已经漂了，本发注毒无法证牙"
            f"（红→红＝空跑）。先按下面这份报告归因是哪一格的漂移、由该面 owner 重录，"
            f"再复跑本门：\n{_failure_report(baseline, artifact_bytes=len(original))}"
        )

        try:
            # 一个字节：追加一枚换行。内容必变（判定必翻），语义零影响，还原无痕。
            ARTIFACT.write_bytes(original + b"\n")
            poisoned = _run_catalog_cli(CHECK_FLAG)
            _assert_decoded_and_clean(poisoned)
            assert poisoned.returncode != 0, (
                "往受管生成物改了一个字节，CLI 只读校验却仍然返回 0 ⇒ 本门没有牙"
                f"（生成器不再按内容判定？stdout={poisoned.stdout!r}）"
            )
            report = _failure_report(poisoned, artifact_bytes=len(original) + 1)
            assert any(
                line.lstrip().startswith("+") and not line.lstrip().startswith("+++")
                for line in report.splitlines()
            ), f"注毒态的失败报告里没有逐行差异，只有退出码：\n{report}"
        finally:
            # 并发写窗守卫：若这一瞬另有席位写了该件，**绝不覆盖它的内容**。
            current = _read_artifact_bytes()
            if current == original + b"\n":
                ARTIFACT.write_bytes(original)
            else:
                report_violation = (
                    "注毒窗口内另有写者动过受管生成物（现字节既非改前也非注毒态）"
                    "⇒ 本席**不回滚**以免吞掉它的内容；请人工核对该文件后复跑本门。"
                )
                raise AssertionError(report_violation)

        assert filecmp.cmp(str(ARTIFACT), str(pristine), shallow=False), (
            "还原后与改前**字节不等值**（cmp 判据）⇒ 演练污染了受管生成物"
        )
        assert _sha256(_read_artifact_bytes()) == _sha256(original), "还原后 sha 不等"
        restored = _run_catalog_cli(CHECK_FLAG)
        _assert_decoded_and_clean(restored)
        assert restored.returncode == baseline.returncode, (
            f"还原后判定没回到改前（{baseline.returncode} → {restored.returncode}）："
            f"\n{_failure_report(restored, artifact_bytes=len(_read_artifact_bytes()))}"
        )


# ---------------------------------------------------------------------------
# 反自豁免：本文件自己的出口一堵墙
# ---------------------------------------------------------------------------


def _this_tree() -> ast.Module:
    return ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"), filename=str(__file__))


def _subprocess_call_sources(tree: ast.Module) -> list[str]:
    """所有 subprocess 调用点的源码片段（查 argv 里有没有被塞进写盘旗标）。"""
    chunks: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = ast.unparse(node.func)
        if callee.startswith("subprocess.") or callee in {"run", "check_output", "check_call"}:
            chunks.append(ast.unparse(node))
    return chunks


def _write_flag_reference_lines(tree: ast.Module) -> list[int]:
    """文件内一切提到写盘旗标常量名的行号（合法用处只有两处，见调用侧）。"""
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == WRITE_FLAG_NAME]


def _test_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def test_this_file_carries_no_escape_hatch() -> None:
    """本门的出口一堵墙（禁 xfail/skip/自动放行/吞红因/删测试）。

    执法的是**形态**，不看当下有没有人用：以后有人加 skip、把判定改成自动重录、
    或干脆删掉某发执法测试，这条都会先红。
    """
    tree = _this_tree()
    problems: list[str] = []

    defined = {node.name for node in _test_functions(tree)}
    missing = [name for name in REQUIRED_TESTS if name not in defined]
    if missing:
        problems.append(f"执法测试被删或改名：{missing}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_EXIT_NAMES:
            problems.append(f"L{node.lineno} 出现出口形态 `.{node.attr}`")
        if isinstance(node, ast.ClassDef):  # 本件不需要类；出现即可疑（防打包出口）
            problems.append(f"L{node.lineno} 本门不该有类定义 {node.name}")

    for func in tree.body:
        if isinstance(func, ast.FunctionDef) and func.decorator_list:
            problems.append(
                f"L{func.lineno} {func.name} 带装饰器 "
                f"{[ast.unparse(d) for d in func.decorator_list]}"
                "＝本件零装饰器约定被破（任何 mark 都可能变成出口）"
            )

    for func in _test_functions(tree):
        for node in ast.walk(func):
            if isinstance(node, ast.ExceptHandler):
                problems.append(
                    f"{func.name} L{node.lineno} 用 except 兜住红因"
                    "（判定路径上的异常必须冒出来，只准放在 _failure_report）"
                )
        if not any(isinstance(node, ast.Assert) for node in ast.walk(func)):
            problems.append(f"{func.name} 里没有 assert＝不执法")

    for chunk in _subprocess_call_sources(tree):
        if WRITE_FLAG in chunk:
            problems.append(f"子进程调用里出现写盘旗标：{chunk}")

    # 写盘旗标常量的引用面：只准出现在「它自己的赋值」与「本发门」两处。
    self_lock = next((f for f in _test_functions(tree) if f.name == SELF_LOCK_NAME), None)
    allowed: set[int] = set()
    if self_lock is not None:
        allowed.update(n.lineno for n in ast.walk(self_lock) if hasattr(n, "lineno"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == WRITE_FLAG_NAME for t in node.targets
        ):
            allowed.add(node.lineno)
    stray = sorted(set(_write_flag_reference_lines(tree)) - allowed)
    if stray:
        problems.append(
            f"写盘旗标常量 {WRITE_FLAG_NAME} 在不该出现的行被引用：{stray}"
            f"（合法用处仅它自己的赋值处与反自豁免那发门）"
        )

    assert not problems, "本门被装了出口／被削了牙：\n  " + "\n  ".join(sorted(set(problems)))
