"""Windows Job Objects 强隔离原语（kernel32/ctypes，纯 Python 标准库）。

V2.1 §3 合同落点（docs/design/backend-v2-implementation-guide.md）：
- ``JOB_OBJECT_LIMIT_PROCESS_MEMORY`` / ``JOB_MEMORY``：内存配额；
- ``JOB_OBJECT_CPU_RATE_CONTROL``：CPU 速率控制（weight / hard limit）；
- ``JOB_OBJECT_LIMIT_ACTIVE_PROCESS``：进程数上限（Job 内含子进程一并计数）；
- ``JOB_OBJECT_LIMIT_PROCESS_TIME``：单进程用户态时间配额（超限系统终止）；
- ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``：监督器句柄关闭即回收 Job 内全部进程；
- CREATE_SUSPENDED → AssignProcessToJobObject → ResumeThread：消除"先运行后挂 Job"
  的逃逸竞态窗口（子进程在可执行任何指令之前已被纳入配额边界）。

纪律：本模块只含原语，不 import 本插件任何其余模块（可独立导入，零 bot 运行时依赖）；
所有句柄路径 fail-closed，挂 Job 失败由上层转 ``SandboxUnavailable``，绝不静默降级为
普通同权限 subprocess。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Self

__all__ = [
    "IS_WINDOWS",
    "ChildProcess",
    "JobLimits",
    "JobObject",
    "JobObjectError",
    "current_process_handle_count",
    "current_process_in_job",
    "probe_nested_job_support",
    "process_alive",
    "spawn_suspended",
]

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:  # pragma: no branch - Windows 真机路径
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ---- 常量（winnt.h / winbase.h）----
    JOB_OBJECT_LIMIT_PROCESS_TIME = 0x0000_0002
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0000_0008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0000_0100
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x0000_0200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x0000_2000

    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x0000_0001
    JOB_OBJECT_CPU_RATE_CONTROL_WEIGHT_BASED = 0x0000_0002
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_LIMIT = 0x0000_0004

    JobObjectExtendedLimitInformation = 9
    JobObjectBasicAccountingInformation = 1
    JobObjectBasicProcessIdList = 3
    JobObjectCpuRateControlInformation = 15

    CREATE_SUSPENDED = 0x0000_0004
    CREATE_NO_WINDOW = 0x0800_0000
    CREATE_UNICODE_ENVIRONMENT = 0x0000_0400
    STARTF_USESTDHANDLES = 0x0000_0100
    HANDLE_FLAG_INHERIT = 0x0000_0001
    GENERIC_READ = 0x8000_0000
    GENERIC_WRITE = 0x4000_0000
    FILE_SHARE_READWRITE = 0x0000_0001 | 0x0000_0002
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value or -1
    WAIT_OBJECT_0 = 0x0000_0000
    WAIT_TIMEOUT = 0x0000_0102
    SYNCHRONIZE = 0x0010_0000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE_RIGHT = 0x0001
    STILL_ACTIVE = 259

    # ---- 结构体 ----
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TerminatedProcesses", wintypes.DWORD),
            ("IoInfo", IO_COUNTERS),
        ]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("CpuRate", wintypes.DWORD), ("Weight", wintypes.DWORD)]

        _anonymous_ = ("u",)
        _fields_ = [("ControlFlags", wintypes.DWORD), ("u", _U)]

    class JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInList", wintypes.DWORD),
            ("ProcessIdList", ctypes.c_uint64 * 1),
        ]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    # ---- 函数签名 ----
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.IsProcessInJob.restype = wintypes.BOOL
    _kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        wintypes.DWORD,
    ]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    _kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetCurrentProcess.restype = ctypes.c_void_p  # 伪句柄 -1 以无符号回传，避免 OverflowError
    _kernel32.GetCurrentProcess.argtypes = []


def _current_process() -> ctypes.c_void_p:
    """当前进程伪句柄（c_void_p 包装，兼容 -1）。"""
    return ctypes.c_void_p(_kernel32.GetCurrentProcess())


class JobObjectError(RuntimeError):
    """Job 原语调用失败（带 GetLastError 码）。"""


@dataclass(frozen=True)
class JobLimits:
    """Job 配额声明；None = 不设该项。

    cpu_rate_percent：硬限百分比 1..100（内部 ×100，win32 语义 CpuRate）。
    cpu_rate_weight：权重 1..9（与硬限二选一，weight 优先级低于显式硬限）。
    """

    process_memory_mb: float | None = None
    job_memory_mb: float | None = None
    active_process_limit: int | None = None
    per_process_user_time_sec: float | None = None
    cpu_rate_percent: int | None = None
    cpu_rate_weight: int | None = None
    cpu_hard_limit: bool = False


_MB = 1024 * 1024


class JobObject:
    """一个 kernel32 Job 的句柄包装（可查询/终止/关闭，支持 with）。"""

    def __init__(self, limits: JobLimits | None = None, *, kill_on_job_close: bool = True):
        if not IS_WINDOWS:
            raise JobObjectError("Job Objects 仅在 Windows 可用")
        self._limits = limits or JobLimits()
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise JobObjectError(f"CreateJobObjectW failed: WinError {ctypes.get_last_error()}")
        self._handle = handle
        self._closed = False
        self._apply_limits(kill_on_job_close=kill_on_job_close)

    # ---- 配置 ----
    def _apply_limits(self, *, kill_on_job_close: bool) -> None:
        lim = self._limits
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = 0
        if kill_on_job_close:
            flags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if lim.per_process_user_time_sec is not None:
            flags |= JOB_OBJECT_LIMIT_PROCESS_TIME
            info.BasicLimitInformation.PerProcessUserTimeLimit = int(
                lim.per_process_user_time_sec * 10_000_000
            )
        if lim.active_process_limit is not None:
            flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = int(lim.active_process_limit)
        if lim.process_memory_mb is not None:
            flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = int(lim.process_memory_mb * _MB)
        if lim.job_memory_mb is not None:
            flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = int(lim.job_memory_mb * _MB)
        info.BasicLimitInformation.LimitFlags = flags
        if not _kernel32.SetInformationJobObject(
            self._handle, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise JobObjectError(f"SetInformationJobObject(extended) failed: WinError {ctypes.get_last_error()}")
        if lim.cpu_rate_percent is not None or lim.cpu_rate_weight is not None:
            self._set_cpu_rate_control(lim)

    def _set_cpu_rate_control(self, lim: JobLimits) -> None:
        ctrl = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        flags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
        if lim.cpu_rate_percent is not None and lim.cpu_hard_limit:
            flags |= JOB_OBJECT_CPU_RATE_CONTROL_HARD_LIMIT
            ctrl.CpuRate = int(lim.cpu_rate_percent) * 100
        elif lim.cpu_rate_weight is not None:
            flags |= JOB_OBJECT_CPU_RATE_CONTROL_WEIGHT_BASED
            ctrl.Weight = int(lim.cpu_rate_weight)
        elif lim.cpu_rate_percent is not None:
            # 无 hard flag 的纯 rate 配置在语义上仍是硬限（win32 不存在软 rate），按硬限处理
            flags |= JOB_OBJECT_CPU_RATE_CONTROL_HARD_LIMIT
            ctrl.CpuRate = int(lim.cpu_rate_percent) * 100
        else:
            return
        ctrl.ControlFlags = flags
        if not _kernel32.SetInformationJobObject(
            self._handle,
            JobObjectCpuRateControlInformation,
            ctypes.byref(ctrl),
            ctypes.sizeof(ctrl),
        ):
            raise JobObjectError(
                f"SetInformationJobObject(cpu_rate) failed: WinError {ctypes.get_last_error()}"
            )

    # ---- 进程管理 ----
    def assign(self, process_handle: int) -> None:
        if not _kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise JobObjectError(
                f"AssignProcessToJobObject failed: WinError {ctypes.get_last_error()}"
            )

    def terminate(self, exit_code: int = 1) -> None:
        if self._closed or not self._handle:
            return
        if not _kernel32.TerminateJobObject(self._handle, exit_code):
            # Job 已空/已关闭时终止失败可容忍（幂等回收语义）
            ctypes.get_last_error()

    # ---- 查询 ----
    def query_extended_limits(self) -> JOBOBJECT_EXTENDED_LIMIT_INFORMATION:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not _kernel32.QueryInformationJobObject(
            self._handle, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            raise JobObjectError(f"QueryInformationJobObject(extended) failed: WinError {ctypes.get_last_error()}")
        return info

    def query_accounting(self) -> JOBOBJECT_BASIC_ACCOUNTING_INFORMATION:
        info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not _kernel32.QueryInformationJobObject(
            self._handle,
            JobObjectBasicAccountingInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise JobObjectError(f"QueryInformationJobObject(accounting) failed: WinError {ctypes.get_last_error()}")
        return info

    def query_cpu_rate_control(self) -> JOBOBJECT_CPU_RATE_CONTROL_INFORMATION:
        ctrl = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        if not _kernel32.QueryInformationJobObject(
            self._handle,
            JobObjectCpuRateControlInformation,
            ctypes.byref(ctrl),
            ctypes.sizeof(ctrl),
            None,
        ):
            raise JobObjectError(f"QueryInformationJobObject(cpu_rate) failed: WinError {ctypes.get_last_error()}")
        return ctrl

    def process_ids(self) -> list[int]:
        """Job 内进程 PID 列表（先探大小再取）。"""
        got = JOBOBJECT_BASIC_PROCESS_ID_LIST()
        ret = wintypes.DWORD(0)
        if _kernel32.QueryInformationJobObject(
            self._handle, JobObjectBasicProcessIdList, ctypes.byref(got), ctypes.sizeof(got), ctypes.byref(ret)
        ):
            return [int(got.ProcessIdList[i]) for i in range(got.NumberOfProcessIdsInList)]
        need = max(got.NumberOfAssignedProcesses, 1)
        buf = ctypes.create_string_buffer(ctypes.sizeof(wintypes.DWORD) * 2 + 8 * need)
        if not _kernel32.QueryInformationJobObject(
            self._handle, JobObjectBasicProcessIdList, buf, len(buf), ctypes.byref(ret)
        ):
            raise JobObjectError(f"QueryInformationJobObject(pidlist) failed: WinError {ctypes.get_last_error()}")
        raw = buf.raw
        n = wintypes.DWORD.from_buffer_copy(raw[4:8]).value
        pids: list[int] = []
        for i in range(n):
            pids.append(int.from_bytes(raw[8 + i * 8 : 16 + i * 8], "little"))
        return pids

    # ---- 生命周期 ----
    def close(self) -> None:
        if not self._closed and self._handle:
            _kernel32.CloseHandle(self._handle)
        self._closed = True
        self._handle = None

    @property
    def handle(self) -> int | None:
        return self._handle

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class ChildProcess:
    """由 spawn_suspended 创建的挂起子进程句柄集。"""

    process_handle: int
    thread_handle: int
    pid: int
    stdout_read_handle: int  # 父侧读端（子进程写端已移交）

    _stdout_buf: bytearray | None = None
    _stdout_thread: threading.Thread | None = None
    _reaped: bool = False

    def resume(self) -> None:
        """恢复主线程（挂 Job 之后调用，保证零逃逸窗口）。"""
        if self.thread_handle:
            _kernel32.ResumeThread(self.thread_handle)

    def start_stdout_drain(self) -> None:
        if self._stdout_thread is not None:
            return
        buf = bytearray()
        self._stdout_buf = buf

        def _run() -> None:
            chunk = ctypes.create_string_buffer(65536)
            n = wintypes.DWORD()
            h = wintypes.HANDLE(self.stdout_read_handle)
            while True:
                if not _kernel32.ReadFile(h, chunk, len(chunk), ctypes.byref(n), None):
                    break  # ERROR_BROKEN_PIPE → 对端关闭 = EOF
                if n.value == 0:
                    break
                buf.extend(chunk.raw[: n.value])

        self._stdout_thread = threading.Thread(target=_run, daemon=True, name="s1-sandbox-stdout")
        self._stdout_thread.start()

    def stdout_text(self, timeout: float = 5.0) -> str:
        if self._stdout_thread is not None:
            self._stdout_thread.join(timeout)
        raw = bytes(self._stdout_buf or b"")
        return raw.decode("utf-8", errors="replace")

    def wait(self, timeout_s: float = 30.0) -> int | None:
        """等待退出并返回 exit code；超时返回 None（进程仍存活）。"""
        code = wintypes.DWORD(STILL_ACTIVE)
        status = _kernel32.WaitForSingleObject(self.process_handle, int(timeout_s * 1000))
        if status != WAIT_OBJECT_0:
            return None
        if not _kernel32.GetExitCodeProcess(self.process_handle, ctypes.byref(code)):
            raise JobObjectError(f"GetExitCodeProcess failed: WinError {ctypes.get_last_error()}")
        self._reaped = True
        return int(code.value)

    def exit_code(self) -> int | None:
        code = wintypes.DWORD(STILL_ACTIVE)
        if not _kernel32.GetExitCodeProcess(self.process_handle, ctypes.byref(code)):
            raise JobObjectError(f"GetExitCodeProcess failed: WinError {ctypes.get_last_error()}")
        value = int(code.value)
        return None if value == STILL_ACTIVE and not self._reaped else value

    def is_alive(self) -> bool:
        return self.exit_code() is None

    def terminate(self, exit_code: int = 1) -> None:
        if self.process_handle:
            _kernel32.TerminateProcess(self.process_handle, exit_code)

    def close(self) -> None:
        for attr in ("thread_handle", "stdout_read_handle", "process_handle"):
            h = getattr(self, attr)
            if h:
                _kernel32.CloseHandle(h)
                setattr(self, attr, 0)


def spawn_suspended(argv: list[str]) -> ChildProcess:
    """CREATE_SUSPENDED 拉起子进程（stdout/stderr 合并进匿名管道），不恢复运行。

    纪律：调用方必须先 AssignProcessToJobObject 再 resume()，否则存在逃逸窗口。
    """
    if not IS_WINDOWS:
        raise JobObjectError("spawn_suspended 仅在 Windows 可用")
    sa_inherit = SECURITY_ATTRIBUTES()
    sa_inherit.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa_inherit.bInheritHandle = True

    out_r = wintypes.HANDLE()
    out_w = wintypes.HANDLE()
    if not _kernel32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), ctypes.byref(sa_inherit), 0):
        raise JobObjectError(f"CreatePipe failed: WinError {ctypes.get_last_error()}")
    # NUL 设备作为子进程 stdin
    nul = _kernel32.CreateFileW(
        "NUL", GENERIC_READ, FILE_SHARE_READWRITE, ctypes.byref(sa_inherit), OPEN_EXISTING, 0, None
    )
    if nul == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        _kernel32.CloseHandle(out_r)
        _kernel32.CloseHandle(out_w)
        raise JobObjectError(f"CreateFileW(NUL) failed: WinError {err}")

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput = nul
    si.hStdOutput = out_w
    si.hStdError = out_w
    pi = PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    ok = _kernel32.CreateProcessW(
        None, cmdline, None, None, True, CREATE_SUSPENDED | CREATE_NO_WINDOW, None, None, ctypes.byref(si), ctypes.byref(pi)
    )
    # 父侧多余的继承位清理：子进程已拿到自己的拷贝
    _kernel32.SetHandleInformation(out_w, HANDLE_FLAG_INHERIT, 0)
    _kernel32.SetHandleInformation(nul, HANDLE_FLAG_INHERIT, 0)
    if not ok:
        err = ctypes.get_last_error()
        _kernel32.CloseHandle(out_r)
        _kernel32.CloseHandle(out_w)
        _kernel32.CloseHandle(nul)
        raise JobObjectError(f"CreateProcessW failed: WinError {err}")
    _kernel32.CloseHandle(out_w)
    _kernel32.CloseHandle(nul)
    child = ChildProcess(
        process_handle=int(pi.hProcess or 0),
        thread_handle=int(pi.hThread or 0),
        pid=int(pi.dwProcessId),
        stdout_read_handle=int(out_r.value or 0),
    )
    child.start_stdout_drain()
    return child


def probe_nested_job_support(timeout_s: float = 20.0) -> tuple[bool, str]:
    """探测本机 Job 嵌套能力：同一进程能否同时挂在两个 Job 上（Win8+ 特性）。

    返回 (supported, detail)。探测全程用无 KILL_ON_JOB_CLOSE 的 Job + 显式终止，
    收尾零残留。
    """
    if not IS_WINDOWS:
        return False, "non-windows"
    child = spawn_suspended([sys.executable, "-c", "import time; time.sleep(30)"])
    job1 = JobObject(JobLimits(), kill_on_job_close=False)
    job2 = JobObject(JobLimits(), kill_on_job_close=False)
    try:
        job1.assign(child.process_handle)
        child.resume()
        try:
            job2.assign(child.process_handle)
            return True, "nested-assign-ok (Win8+ nested jobs supported)"
        except JobObjectError as exc:
            return False, f"second assign rejected: {exc}"
    finally:
        job1.terminate(1)
        job2.terminate(1)
        child.terminate(1)
        child.wait(max(timeout_s / 2, 5.0))
        job1.close()
        job2.close()
        child.close()


def current_process_in_job() -> bool:
    if not IS_WINDOWS:
        return False
    result = wintypes.BOOL(False)
    if not _kernel32.IsProcessInJob(_current_process(), None, ctypes.byref(result)):
        return False
    return bool(result.value)


def process_alive(pid: int) -> bool:
    """PID 是否对应存活进程（ACCESS_DENIED 保守视为存活）。"""
    if not IS_WINDOWS:
        return False
    h = _kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED → 存在但无权（保守=存活）
    try:
        return _kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(h)


def current_process_handle_count() -> int:
    count = wintypes.DWORD(0)
    if not _kernel32.GetProcessHandleCount(_current_process(), ctypes.byref(count)):
        raise JobObjectError(f"GetProcessHandleCount failed: WinError {ctypes.get_last_error()}")
    return int(count.value)
