"""bot.py 进程守护（supervisor，审查 A-21）离线回归。

为什么不能 ``import bot``：bot.py 模块级会执行 nonebot.init + 全插件加载
（重、带生产副作用，且并行批次仍在改插件域文件）。这里用 AST 把 bot.py 的
顶层 import 与三个守护函数摘到独立命名空间执行，只测守护逻辑本身；子进程
用 ``python -c`` 可编程退出序列（tmp_path 里的 JSON 序列文件），全部真实
spawn/wait——测的是真退出码语义，不发网络、不碰源码树 data/（G1 守卫）。

覆盖：
① 子进程非零退出 → 注入短退避后按序重启（可编程退出序列）；
② 滑窗内连续崩溃达阈值 → 熔断停拉并写含最后退出码的摘要；
③ 子进程退出码 0 → 不重启，守护以 0 结束；
④ 默认模式（BOT_SUPERVISE 未设/为 0）不进守护分支，入口代码与现状一致；
⑤ Ctrl+C（KeyboardInterrupt）→ 不吞信号：不再重启、等子进程后随同退出；
⑥ _run_supervised 装配：子进程命令=同一解释器+bot.py、剥离 BOT_SUPERVISE、
   日志落 runtime_data_dir()/supervisor.log。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.runtime_paths import runtime_data_dir

BOT_PATH = PROJECT_ROOT / "bot.py"
_SUPERVISOR_FUNCS = ("_supervision_requested", "_supervise_loop", "_run_supervised")


def _load_supervisor_namespace() -> dict:
    """AST 摘取：bot.py 全部顶层 import + 守护函数 → 独立命名空间。

    顶层 import 均为无副作用导入（stdlib/nonebot 适配器类定义），摘取后
    守护函数需要的 os/sys/Path 等名字即可用；函数体内的 subprocess/time/
    runtime_paths 由函数自行导入。守护函数若新增模块级依赖，本加载器会在
    NameError 处暴露，测试即失败——这是有意的结构约束。
    """
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SUPERVISOR_FUNCS)
    ]
    found = {n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert found == set(_SUPERVISOR_FUNCS), f"bot.py 守护函数缺失/改名: {found}"
    namespace: dict = {"__file__": str(BOT_PATH), "__name__": "bot_supervisor_under_test"}
    # exec 仅用于摘取 bot.py 顶部的守护函数（入口脚本模块级有 nonebot.init
    # 副作用，不能正常 import）；执行的是本仓库自有源码的函数定义，非外部输入。
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BOT_PATH), "exec"), namespace)  # noqa: S102
    return namespace


# 可编程退出序列子进程：逐次弹出 JSON 序列里的退出码，弹尽后默认退出 1
# （保证「永远崩溃」型用例不受序列长度限制）。
_CHILD_SCRIPT = """\
import json, sys
from pathlib import Path
seq_file = Path(sys.argv[1])
codes = json.loads(seq_file.read_text(encoding="utf-8"))
code = codes.pop(0) if codes else 1
seq_file.write_text(json.dumps(codes), encoding="utf-8")
sys.exit(int(code))
"""


def _child_command(seq_file: Path) -> list[str]:
    return [sys.executable, "-c", _CHILD_SCRIPT, str(seq_file)]


def _write_sequence(tmp_path: Path, codes: list[int]) -> Path:
    seq_file = tmp_path / "exit_codes.json"
    seq_file.write_text(json.dumps(codes), encoding="utf-8")
    return seq_file


def _read_log(log_path: Path) -> str:
    return log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ① 非零退出 → 注入短退避，按可编程退出序列逐次重启，直到退出码 0
# ---------------------------------------------------------------------------
def test_supervisor_restarts_on_nonzero_exit_then_stops_on_zero(tmp_path: Path) -> None:
    ns = _load_supervisor_namespace()
    seq_file = _write_sequence(tmp_path, [3, 7, 0])
    log_path = tmp_path / "supervisor.log"

    rc = ns["_supervise_loop"](
        _child_command(seq_file),
        backoff_schedule=(0.01, 0.02, 0.04),  # 注入短退避：测试不等待真实 5/15/60s
        crash_threshold=10,
        log_path=log_path,
    )

    assert rc == 0
    # 序列被精确消费 3 次：3(崩) → 重启 → 7(崩) → 重启 → 0(停)
    assert json.loads(seq_file.read_text(encoding="utf-8")) == []
    log = _read_log(log_path)
    assert "第 1 次拉起子进程" in log
    assert "第 2 次拉起（上次退出码 3，退避 0.01s 后重启）" in log
    assert "第 3 次拉起（上次退出码 7，退避 0.02s 后重启）" in log
    assert "子进程退出码 0（正常停止）" in log
    assert "崩溃熔断" not in log


# ---------------------------------------------------------------------------
# ② 滑窗内连续崩溃达阈值 → 熔断停拉 + 含最后退出码的摘要，supervisor 非零退出
# ---------------------------------------------------------------------------
def test_supervisor_fuses_after_crash_threshold(tmp_path: Path) -> None:
    ns = _load_supervisor_namespace()
    seq_file = _write_sequence(tmp_path, [10, 20, 30, 40, 50])
    log_path = tmp_path / "supervisor.log"

    rc = ns["_supervise_loop"](
        _child_command(seq_file),
        backoff_schedule=(0.01, 0.01),
        crash_window_seconds=600.0,
        crash_threshold=3,
        log_path=log_path,
    )

    assert rc != 0
    # 恰好拉起 3 次（阈值 3）即熔断：序列文件应剩下两个未被消费的退出码
    assert json.loads(seq_file.read_text(encoding="utf-8")) == [40, 50]
    log = _read_log(log_path)
    assert "崩溃熔断：600s 内连续崩溃 3 次（阈值 3），停止拉起防 crash-loop；最后退出码 30" in log
    # 熔断后不得再出现第 4 次拉起
    assert "第 4 次拉起" not in log


# ---------------------------------------------------------------------------
# ②b 窗口外的旧崩溃被剪枝：长期不稳定的旧账不触发熔断
# ---------------------------------------------------------------------------
def test_supervisor_prunes_crashes_outside_window(tmp_path: Path) -> None:
    ns = _load_supervisor_namespace()
    seq_file = _write_sequence(tmp_path, [1, 2, 0])
    log_path = tmp_path / "supervisor.log"

    rc = ns["_supervise_loop"](
        _child_command(seq_file),
        backoff_schedule=(0.01, 0.01),
        crash_window_seconds=0.0,  # 注入零窗口：每次崩溃在计数前即被剪掉
        crash_threshold=2,
        log_path=log_path,
    )

    # 两次崩溃都被剪枝 → 未熔断 → 继续拉起到退出码 0
    assert rc == 0
    assert json.loads(seq_file.read_text(encoding="utf-8")) == []
    assert "崩溃熔断" not in _read_log(log_path)


# ---------------------------------------------------------------------------
# ③ 退出码 0 → 不重启
# ---------------------------------------------------------------------------
def test_supervisor_does_not_restart_on_zero_exit(tmp_path: Path) -> None:
    ns = _load_supervisor_namespace()
    seq_file = _write_sequence(tmp_path, [0])
    log_path = tmp_path / "supervisor.log"

    rc = ns["_supervise_loop"](
        _child_command(seq_file),
        backoff_schedule=(0.01,),
        log_path=log_path,
    )

    assert rc == 0
    log = _read_log(log_path)
    assert "第 1 次拉起子进程" in log
    assert "第 2 次拉起" not in log  # 退出码 0 绝不重启
    assert "正常停止" in log


# ---------------------------------------------------------------------------
# ④ 默认模式：BOT_SUPERVISE 未设/为 0 → 不进守护分支；入口结构与现状一致
# ---------------------------------------------------------------------------
def test_default_mode_gate_and_entry_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = _load_supervisor_namespace()
    gate = ns["_supervision_requested"]

    monkeypatch.delenv("BOT_SUPERVISE", raising=False)
    assert gate() is False  # 未设 = 现状行为
    monkeypatch.setenv("BOT_SUPERVISE", "0")
    assert gate() is False
    monkeypatch.setenv("BOT_SUPERVISE", "false")
    assert gate() is False
    monkeypatch.setenv("BOT_SUPERVISE", "1")
    assert gate() is True
    monkeypatch.setenv("BOT_SUPERVISE", "TRUE")
    assert gate() is True

    source = BOT_PATH.read_text(encoding="utf-8")
    guard = 'if __name__ == "__main__" and _supervision_requested():'
    assert guard in source, "守护入口门缺失"
    # 守护门必须在 nonebot.init 之前分叉：启用守护时父进程不加载配置/插件
    assert source.index(guard) < source.index("nonebot.init(")
    # 现有入口逻辑原样保留：默认路径仍是 nonebot.run()
    assert "nonebot.run()" in source


# ---------------------------------------------------------------------------
# ⑤ Ctrl+C：supervisor 不吞信号——不再重启，等子进程退出后随同结束
# ---------------------------------------------------------------------------
def test_supervisor_stops_on_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess

    ns = _load_supervisor_namespace()

    class _KiThenZeroProc:
        def __init__(self) -> None:
            self.terminated = False
            self._wait_calls = 0

        def wait(self, timeout=None):
            self._wait_calls += 1
            if self._wait_calls == 1:
                raise KeyboardInterrupt  # 主 wait 收到控制台 Ctrl+C
            return 0  # 优雅停机确认

        def terminate(self) -> None:
            self.terminated = True

    spawned: list[_KiThenZeroProc] = []

    def fake_popen(*args: object, **kwargs: object) -> _KiThenZeroProc:
        proc = _KiThenZeroProc()
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    log_path = tmp_path / "supervisor.log"

    rc = ns["_supervise_loop"](
        [sys.executable, "-c", "pass"],
        backoff_schedule=(0.01,),
        log_path=log_path,
    )

    assert rc == 0
    assert len(spawned) == 1  # Ctrl+C 后绝不重启
    assert spawned[0].terminated is False  # 子进程已在优雅退出，无需强杀
    log = _read_log(log_path)
    assert "收到 Ctrl+C，停止拉起，等待子进程退出" in log
    assert "第 2 次拉起" not in log


# ---------------------------------------------------------------------------
# ⑥ _run_supervised 装配：同解释器+bot.py、剥离 BOT_SUPERVISE、日志入 Runtime
# ---------------------------------------------------------------------------
def test_run_supervised_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = _load_supervisor_namespace()
    captured: dict = {}

    def fake_loop(child_command: list[str], **kwargs: object) -> int:
        captured["cmd"] = child_command
        captured.update(kwargs)
        return 7

    ns["_supervise_loop"] = fake_loop
    monkeypatch.setenv("BOT_SUPERVISE", "1")

    rc = ns["_run_supervised"]()

    assert rc == 7  # 透传守护循环退出码
    assert captured["cmd"] == [sys.executable, str(BOT_PATH)]
    # 子进程环境必须剥离开关，否则子进程再进守护分支无限套娃
    assert "BOT_SUPERVISE" not in captured["child_env"]
    assert os.environ.get("BOT_SUPERVISE") == "1"  # 父进程环境不受影响
    # 日志通道与崩溃守卫同处：运行数据目录（源码树 data/ 绝不被写，G1）
    log_path = captured["log_path"]
    assert log_path.name == "supervisor.log"
    assert log_path.parent == runtime_data_dir()


def test_entry_suppresses_source_tree_bytecode() -> None:
    """铁律 6（源码树零缓存）的**启动侧兜底**必须有牙。

    为什么门会被自家进程判红：`scripts/dev.ps1` 自己置了 `PYTHONDONTWRITEBYTECODE`，
    但现网常按 `python bot.py` 直起 ⇒ 那条环境变量压根没进进程，而 bot 正是从**源码树**
    import `plugins/bot_unified_runtime/*` 的，Python 一加载就往同目录吐 `.pyc`。
    手工清完下一轮启动立刻再生，于是 runtime-layout 的 `python_bytecode=absent` 长期红着，
    而红的是"谁来启动"而不是"代码坏了"。

    判两件事，缺一即红：
    ① 两行兜底都在**模块顶层**（塞进函数体＝要到那条分支跑到才生效，等于没兜底）；
    ② 都在 `import nonebot` **之前**——nonebot 本体住 venv 不污染源码树，插件是
       `nonebot.init` 之后才导入的，故锚在它之前即罩住全部项目代码；
    ③ `os.environ` 那枚也必须落在顶层：supervisor 分叉的子进程靠继承环境变量才轮得到。
    """
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))

    def top_level_assignment_targets() -> list[tuple[int, ast.expr]]:
        return [
            (node.lineno, target)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
        ]

    dont_write = [
        lineno
        for lineno, target in top_level_assignment_targets()
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "sys"
        and target.attr == "dont_write_bytecode"
    ]
    env_guard = [
        lineno
        for lineno, target in top_level_assignment_targets()
        if isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Attribute)
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "os"
        and target.value.attr == "environ"
    ]
    nonebot_import = next(
        (
            node.lineno
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(
                ((a.name if isinstance(node, ast.Import) else (node.module or "")).split(".")[0]
                 == "nonebot")
                for a in node.names
            )
        ),
        None,
    )

    assert nonebot_import is not None, "bot.py 顶层不再 import nonebot？本腿失去锚点"
    assert dont_write, "bot.py 顶层缺 `sys.dont_write_bytecode = True`（源码树会再长 .pyc）"
    assert env_guard, "bot.py 顶层缺 `os.environ[\"PYTHONDONTWRITEBYTECODE\"]`（子进程不受兜底罩）"
    assert dont_write[0] < nonebot_import, "字节码兜底被挪到 nonebot 之后＝插件导入已先吐过 .pyc"
    assert env_guard[0] < nonebot_import, "环境变量兜底被挪到 nonebot 之后＝子进程继承不到"
