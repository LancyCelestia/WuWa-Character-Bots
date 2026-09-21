"""进程级崩溃/击杀取证陷阱（v21r2 R8 席交付）。

背景（2026-09-17 23:24 生产闪退取证结论）：bot 进程在私聊回复发送成功
（wuwa_receipts 最后一条 23:24:32.603）后数秒内整个进程死亡，dev.ps1 报
``python.exe exited with code -1``（=0xFFFFFFFF），而 Windows 事件日志、
WER 报告、crash.log（excepthook）、faulthandler.log **四面全空**——这排除了
Python 未捕获异常与原生段错误/栈溢出/abort（它们必留痕），唯一自洽解释是
**外部 TerminateProcess(0xFFFFFFFF)**（.NET Process.Kill/Stop-Process 及部分
安全软件内核的经典签名）。这类死亡在进程内无任何 Python 钩子可拦截，
因此本模块不试图"防"，只保证**下次必留证据**：

1. **存活心跳**：daemon 线程每 ``beat_seconds`` 把单行时间戳覆写进
   ``crash_heartbeat_pid<pid>.log``（flush + fsync）。事后用文件内容即可把
   死亡时刻钉到 ±beat 秒；心跳戛然而止 = 非优雅死亡。
2. **退出标记**：``mark(stage)`` + atexit 钩子向 ``crash_markers.log`` 追加
   带时间戳的阶段行。优雅退出会留下 atexit 标记；崩溃/击杀则缺失。
   与 faulthandler（原生栈）/excepthook（Python 栈，bot.py 已装）互补，
   三者拼出完整的「死法判定面」。
3. **faulthandler 兜底**：宿主（bot.py `_install_crash_guards`）已启用则
   跳过，否则以 all_threads=True 启用写 ``faulthandler.log``。

设计约束：仅 stdlib；心跳为 daemon 线程，绝不阻塞退出；所有 IO 失败
静默降级（取证设施绝不反噬业务）；幂等安装（单例）。

用法（bot.py 装配坐标，R2b 落地）——在 ``bot.py:260``
``_install_crash_guards(...)`` 调用之后追加::

    from scripts.crash_trap import install as install_crash_trap
    install_crash_trap(getattr(_driver_config, "bot_runtime_data_dir", None))

放在 scripts/ 而非 plugins.bot_unified_runtime.runtime/：bot.py:260 早于
load_from_toml，import 插件包子模块会连带执行整个插件 __init__（重复
注册 matcher 等副作用）；scripts 已是 bot.py 既有导入域（runtime_paths、
telegram_resilience 先例）。
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_HEARTBEAT_PREFIX = "crash_heartbeat_pid"
_MARKERS_FILENAME = "crash_markers.log"
_FAULTHANDLER_FILENAME = "faulthandler.log"
_STALE_HEARTBEAT_SECONDS = 24 * 3600
_MAX_MARKER_BYTES = 512 * 1024


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _fsync_write(path: Path, text: str, *, append: bool) -> None:
    """写入并 fsync——掉电/击杀瞬间也要把这条证据留在盘上。"""
    try:
        with path.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass  # 取证设施绝不反噬业务。


class CrashTrap:
    """单例陷阱：心跳线程 + 标记通道。由 :func:`install` 创建。"""

    def __init__(
        self,
        data_dir: Path,
        *,
        beat_seconds: float,
        source: str,
    ) -> None:
        self._data_dir = data_dir
        self._beat_seconds = max(0.05, float(beat_seconds))
        self._source = source
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.heartbeat_path = data_dir / f"{_HEARTBEAT_PREFIX}{os.getpid()}.log"
        self.markers_path = data_dir / _MARKERS_FILENAME

    # ---- 心跳 ----------------------------------------------------------

    def _write_heartbeat(self) -> None:
        line = (
            f"hb ts={_now_iso()} mono={time.monotonic():.3f} "
            f"pid={os.getpid()} py={sys.version_info.major}.{sys.version_info.minor} "
            f"src={self._source}\n"
        )
        _fsync_write(self.heartbeat_path, line, append=False)

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self._beat_seconds):
            self._write_heartbeat()

    # ---- 标记 ----------------------------------------------------------

    def mark(self, stage: str) -> None:
        """追加一条阶段标记（优雅停机/关键节点调用，事后判定死法用）。"""
        if self.markers_path.exists() and self.markers_path.stat().st_size > _MAX_MARKER_BYTES:
            # 只保留尾部一半，防无限增长；证据价值随时间衰减，近期最重要。
            try:
                tail = self.markers_path.read_bytes()[-_MAX_MARKER_BYTES // 2 :]
                self.markers_path.write_bytes(tail)
            except OSError:
                pass
        _fsync_write(
            self.markers_path,
            f"mark ts={_now_iso()} mono={time.monotonic():.3f} "
            f"pid={os.getpid()} stage={stage}\n",
            append=True,
        )

    # ---- 生命周期 ------------------------------------------------------

    def stop(self) -> None:
        """停心跳线程（优雅停机路径调用；测试重装也靠它复位单例）。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        _ACTIVE = globals().get("_ACTIVE")
        if _ACTIVE is self:
            globals()["_ACTIVE"] = None
        self.mark("trap_stop")


def _sweep_stale_heartbeats(data_dir: Path) -> None:
    """清理 24h 前的旧心跳文件（进程尸体早已不存在，文件无证据价值）。"""
    now = time.time()
    try:
        for candidate in data_dir.glob(f"{_HEARTBEAT_PREFIX}*.log"):
            try:
                if now - candidate.stat().st_mtime > _STALE_HEARTBEAT_SECONDS:
                    candidate.unlink()
            except OSError:
                continue
    except OSError:
        pass


def install(
    runtime_data_dir: str | Path | None = None,
    *,
    beat_seconds: float = 5.0,
    source: str = "bot",
) -> CrashTrap:
    """装配崩溃陷阱（幂等；重复调用返回既有单例）。

    ``runtime_data_dir`` 缺省走 ``scripts.runtime_paths.runtime_data_dir()``，
    与 supervisor.log/faulthandler.log 同处运行数据目录；相对路径按仓库根
    解析（与 bot.py ``_install_crash_guards`` 同口径）。
    """
    global _ACTIVE
    active = _ACTIVE
    if active is not None:
        return active

    if runtime_data_dir is not None:
        data_dir = Path(runtime_data_dir).expanduser()
        if not data_dir.is_absolute():
            data_dir = Path(__file__).resolve().parents[1] / data_dir
    else:
        from scripts import runtime_paths as _runtime_paths

        data_dir = _runtime_paths.runtime_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    trap = CrashTrap(data_dir, beat_seconds=beat_seconds, source=source)

    # 1) faulthandler 兜底（bot.py 已启用则跳过，避免换文件丢旧句柄）。
    if not faulthandler.is_enabled():
        try:
            fault_log = open(  # noqa: SIM115 - faulthandler 需长期持有追加句柄
                data_dir / _FAULTHANDLER_FILENAME, "a", encoding="utf-8", buffering=1
            )
            faulthandler.enable(fault_log, all_threads=True)
        except OSError:
            pass

    # 2) 存活心跳（daemon：解释器退出不等它）。
    _sweep_stale_heartbeats(data_dir)
    trap._write_heartbeat()
    thread = threading.Thread(
        target=trap._heartbeat_loop, name="crash-trap-heartbeat", daemon=True
    )
    trap._thread = thread
    thread.start()

    # 3) 退出标记：走到这里 = 优雅退出（外部击杀/硬崩溃不会执行 atexit）。
    atexit.register(trap.mark, "atexit_interpreter_shutdown")

    # 4) unraisable 补漏：GC 期 __del__ 异常默认只打 stderr 且常被吞。
    _previous_unraisable = sys.unraisablehook

    def _unraisable_hook(unraisable) -> None:  # type: ignore[no-untyped-def]
        exc = getattr(unraisable, "exc_value", None)
        trap.mark(f"unraisable: {type(exc).__name__ if exc else 'unknown'}: {exc}")
        _previous_unraisable(unraisable)

    sys.unraisablehook = _unraisable_hook

    trap.mark(f"install source={source} beat={trap._beat_seconds:g}s")
    _ACTIVE = trap
    return trap


_ACTIVE: CrashTrap | None = None
