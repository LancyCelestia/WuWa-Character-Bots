"""Windows 强隔离沙盒（后端 V2.1 规范 §3 / 验收矩阵 V21-ISO-001/002）。

三层真实机制（全部经 ctypes 直调 Win32，不借助任何第三方库）：

1. **Job Objects（硬底线，必须完整可用）**
   - ``CreateJobObjectW`` 创建作业；
   - ``SetInformationJobObject``（JobObjectExtendedLimitInformation）配置：
     ``JobMemoryLimit``/``ProcessMemoryLimit``（内存硬限）、
     ``ActiveProcessLimit``（进程数配额）、``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``
     （监督器退出/句柄关闭 → 作业内全部进程回收）；
   - 可选 CPU 速率硬顶（JobObjectCpuRateControlInformation，CpuRate=百分比×100）；
   - ``AssignProcessToJobObject`` 挂入作业（子进程以 CREATE_SUSPENDED 创建，
     挂作业后再恢复线程，消除"子进程先跑后挂"的逃逸窗口）；
   - ``TerminateJobObject`` 主动终止；``CloseHandle`` 关闭句柄触发 KILL_ON_JOB_CLOSE 回收。
2. **AppContainer（尽力真实；任一步不可行 → 显式 ``sandbox_unavailable``，绝不降级）**
   - ``CreateAppContainerProfile``（userenv）创建独立 AC profile（派生 SID，无 capability）；
   - ``DeriveAppContainerSidFromAppContainerName`` 取 SID；
   - ``STARTUPINFOEX`` + ``InitializeProcThreadAttributeList`` +
     ``UpdateProcThreadAttribute``(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
     capability 计数=0) + ``CreateProcessW``(EXTENDED_STARTUPINFO_PRESENT) 启动；
     无任何网络 capability → 禁网（含 loopback）。
   - 工作区目录以 ``SetNamedSecurityInfoW`` 写保护 DACL 授权 AC SID（生成物隔离）；
     其他用户文件（无 ALL APPLICATION PACKAGES / AC SID ACE）天然拒读。
3. **生成物与环境隔离**
   - 子进程 cwd = 调用方给的私有工作区目录；
   - 环境变量白名单：只注入显式允许键（``None`` 用内置最小安全集），
     ``TEMP``/``TMP`` 一律钉到工作区内 ``tmp/``；
   - 句柄默认不继承（Job 路径 ``close_fds=True``；AC 路径 ``bInheritHandles=FALSE``）。

隔离键 = ``(plugin_id, plugin_release, isolation_scope)``（规范 §3，不同私有
作用域不复用带状态进程）。

诚实边界（真机实测结论，见 tests/test_supervisor_isolation.py）：
- venv/python 所在用户目录默认 ACL **没有** "ALL APPLICATION PACKAGES" ACE，
  AppContainer 子进程不可执行 ChatBot_Runtime 里的解释器（且该目录为本项目禁区，
  不得改其 ACL）。这与规范 §3「只读固定 Python 与插件发布包」一致：正式插件
  运行时必须发布到带 ALL APPLICATION PACKAGES(读/执行) ACE 的只读目录。
  因此 AC 用例子进程选用 ``C:\\Windows\\System32`` 下（默认带该 ACE）的
  curl.exe / cmd.exe 做真实行为验证；沙盒 API 本身对 executable 无白名单假设。
- 非 Windows 平台 / 任一 Win32 步骤失败 → ``SandboxUnavailableError``
  （reason_code=``sandbox_unavailable``），调用方必须拒绝执行，不得同权限降级。

本模块只依赖标准库；导入零网络/线程/配置副作用。
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import subprocess
import sys
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from typing import Self

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量与错误
# ---------------------------------------------------------------------------

#: 无隔离环境时的显式原因码（规范 §3：不得同权限降级）
SANDBOX_UNAVAILABLE = "sandbox_unavailable"

#: §4 资源初值：普通/媒体/渲染插件内存预算（字节）
PLUGIN_MEMORY_LIMITS_BYTES: dict[str, int] = {
    "plugin": 256 * 1024 * 1024,
    "media": 768 * 1024 * 1024,
    "render": 1024 * 1024 * 1024,
}

#: 环境白名单缺省值（env_whitelist=None 时使用）：只放行子进程存活必需的系统键
DEFAULT_ENV_WHITELIST = frozenset(
    {
        "SystemRoot",
        "SystemDrive",
        "windir",
        "COMSPEC",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
    }
)

#: AppContainer 路径的平台必需键（真机实测：环境块缺 LOCALAPPDATA 时
#: CreateProcessW 必失败 ERROR_ENVVAR_NOT_FOUND=203——系统要为 AC 定位
#: %LOCALAPPDATA%\Packages\<容器>AC 的私有存储）。这几个键是标准用户档案
#: 路径、非机密；除本集合外 AC 环境仍严格白名单。
AC_REQUIRED_ENV_KEYS = frozenset({"LOCALAPPDATA"})

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
else:  # 非 Windows：任何沙盒操作都会先撞 _require_windows 显式报 sandbox_unavailable
    _kernel32 = None  # type: ignore[assignment]
    _userenv = None  # type: ignore[assignment]
    _advapi32 = None  # type: ignore[assignment]

# Job Object 信息类
_JobObjectExtendedLimitInformation = 9
_JobObjectCpuRateControlInformation = 21
# JOBOBJECT_BASIC_LIMIT_INFORMATION.LimitFlags
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# JOBOBJECT_CPU_RATE_CONTROL_INFORMATION.ControlFlags
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000002

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400  # CreateProcessW 环境块按宽字符解析的必带旗标
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_STILL_ACTIVE = 259
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_TOKEN_QUERY = 0x0008
_TokenUser = 1
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SDDL_REVISION_1 = 1


class SandboxUnavailableError(RuntimeError):
    """沙盒不可用：规范 §3 要求显式失败、绝不静默降级为普通 subprocess。

    :param step: 失败步骤名（如 create_appcontainer_profile / assign_job_object）
    :param win32_error: Win32/HRESULT 错误码（如可得）
    :param detail: 补充上下文
    """

    def __init__(self, step: str, win32_error: int | None = None, detail: str = "") -> None:
        self.step = step
        self.win32_error = win32_error
        self.reason_code = SANDBOX_UNAVAILABLE
        code = "" if win32_error is None else f" win32_error=0x{win32_error & 0xFFFFFFFF:08X}"
        super().__init__(f"{SANDBOX_UNAVAILABLE}: step={step}{code} detail={detail}")


# ---------------------------------------------------------------------------
# Win32 结构体
# ---------------------------------------------------------------------------

if _IS_WINDOWS:

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        """JobObjectExtendedLimitInformation（内存/进程数/回收旗标）。"""

        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        """JobObjectCpuRateControlInformation（CpuRate 单位=百分比×100）。"""

        _fields_ = [
            ("ControlFlags", wintypes.DWORD),
            ("CpuRate", wintypes.DWORD),
        ]

    class _SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", wintypes.LPVOID),
            ("Capabilities", wintypes.LPVOID),
            ("CapabilityCount", wintypes.DWORD),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        """Python 3.12+ 的 ctypes.wintypes 已裁掉 STARTUPINFOW，本地补齐。"""

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
            ("lpReserved2", wintypes.LPBYTE),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        """扩展启动信息（承载 AC SECURITY_CAPABILITIES 属性表）。"""

        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    class _TOKEN_USER(ctypes.Structure):
        _fields_ = [
            ("Sid", wintypes.LPVOID),
            ("Attributes", wintypes.DWORD),
        ]

    # 关键函数原型
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.Thread32First.restype = wintypes.BOOL
    _kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32Next.restype = wintypes.BOOL
    _kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.OpenThread.restype = wintypes.HANDLE
    _kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _kernel32.OpenProcessToken.restype = wintypes.BOOL
    _kernel32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.LocalFree.restype = wintypes.LPVOID
    _kernel32.LocalFree.argtypes = [wintypes.LPVOID]

    _userenv.CreateAppContainerProfile.restype = ctypes.HRESULT
    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.HRESULT
    _userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.DeleteAppContainerProfile.restype = ctypes.HRESULT
    _userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]

    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    ]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    _advapi32.GetSecurityDescriptorDacl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.BOOL),
    ]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]


def _require_windows() -> None:
    if not _IS_WINDOWS or _kernel32 is None or _userenv is None or _advapi32 is None:
        raise SandboxUnavailableError("platform", detail="非 Windows 平台，无 OS 级强隔离")


# ---------------------------------------------------------------------------
# 启动参数 / 进程句柄
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxLaunchSpec:
    """沙盒启动参数（规范 §3/§4 接口预留：隔离键 + 资源限额）。

    后续席位（资源池调度/Broker）按此 dataclass 装配；本席只负责真实执行。
    """

    plugin_id: str
    plugin_release: str
    isolation_scope: str
    executable: str
    argv: tuple[str, ...] = ()
    workspace_dir: str = ""
    #: 环境变量白名单；None = 内置最小安全集（DEFAULT_ENV_WHITELIST）
    env_whitelist: frozenset[str] | None = None
    #: 作业内存硬限（JobMemoryLimit=ProcessMemoryLimit），§4 普通插件初值 256MiB
    memory_limit_bytes: int = PLUGIN_MEMORY_LIMITS_BYTES["plugin"]
    #: 作业内最大进程数（含子进程自身；1=禁止再孙进程）
    active_process_limit: int = 1
    #: 可选 CPU 速率硬顶（百分比 1-100；None=不设）
    cpu_rate_percent: int | None = None
    #: 是否走 AppContainer（独立 SID、无 capability 禁网、工作区 ACL 授权）
    use_appcontainer: bool = False


class SandboxProcess:
    """沙盒子进程句柄（统一 Job 路径与 AppContainer 路径的最小观测面）。"""

    def __init__(
        self,
        pid: int,
        *,
        popen: subprocess.Popen[bytes] | None = None,
        process_handle: int | None = None,
    ) -> None:
        self.pid = pid
        self._popen = popen
        self._process_handle = process_handle
        self._returncode: int | None = None

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode if self._popen is not None else self._returncode

    def poll(self) -> int | None:
        if self._popen is not None:
            return self._popen.poll()
        if self._returncode is not None:
            return self._returncode
        assert _kernel32 is not None
        code = wintypes.DWORD(0)
        if _kernel32.GetExitCodeProcess(
            self._process_handle, ctypes.byref(code)
        ) and code.value != _STILL_ACTIVE:
            self._returncode = code.value
            return self._returncode
        return None

    def wait(self, timeout: float | None = None) -> int:
        if self._popen is not None:
            return self._popen.wait(timeout)
        assert _kernel32 is not None
        if self._returncode is not None:
            return self._returncode
        ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        status = _kernel32.WaitForSingleObject(self._process_handle, ms)
        if status == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(
                str(self.pid), float(timeout) if timeout is not None else -1.0
            )
        if status != _WAIT_OBJECT_0:
            raise OSError(f"WaitForSingleObject 失败：{ctypes.get_last_error()}")
        code = wintypes.DWORD(0)
        if not _kernel32.GetExitCodeProcess(self._process_handle, ctypes.byref(code)):
            raise OSError(f"GetExitCodeProcess 失败：{ctypes.get_last_error()}")
        self._returncode = code.value
        return self._returncode

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        if self._popen is None:
            raise RuntimeError(
                "AppContainer 路径句柄不继承（bInheritHandles=FALSE），无管道；"
                "输出请通过已授权工作区文件交换"
            )
        return self._popen.communicate(timeout=timeout)  # type: ignore[return-value]

    def _close_handle(self) -> None:
        if self._process_handle is not None and _kernel32 is not None:
            _kernel32.CloseHandle(self._process_handle)
            self._process_handle = None


# ---------------------------------------------------------------------------
# 沙盒本体
# ---------------------------------------------------------------------------


class WindowsSandbox:
    """一个隔离键对应一个沙盒实例：Job 硬限 +（可选）AppContainer。

    用法：``with WindowsSandbox(spec) as sb: proc = sb.launch()``。
    ``close()`` 幂等；关 Job 句柄即触发 KILL_ON_JOB_CLOSE 全体回收，
    随后删除本实例创建的 AppContainer profile（监督器退出不残留）。
    """

    def __init__(self, spec: SandboxLaunchSpec) -> None:
        _require_windows()
        assert _kernel32 is not None and _userenv is not None and _advapi32 is not None
        if not spec.plugin_id or not spec.plugin_release or not spec.isolation_scope:
            raise ValueError("隔离键三要素（plugin_id/plugin_release/isolation_scope）不得为空")
        if spec.memory_limit_bytes <= 0:
            raise ValueError("memory_limit_bytes 必须为正")
        if spec.active_process_limit < 1:
            raise ValueError("active_process_limit 至少为 1")
        if spec.cpu_rate_percent is not None and not 1 <= spec.cpu_rate_percent <= 100:
            raise ValueError("cpu_rate_percent 必须在 1-100 之间")
        self._spec = spec
        self._h_job: int | None = None
        self._ac_sid: int | None = None
        self._ac_profile_name: str | None = None
        self._last_process: SandboxProcess | None = None
        self._workspace = os.path.abspath(spec.workspace_dir) if spec.workspace_dir else None

        assert _kernel32 is not None
        try:
            self._h_job = self._create_job()
            if self._workspace:
                os.makedirs(self._workspace, exist_ok=True)
                os.makedirs(os.path.join(self._workspace, "tmp"), exist_ok=True)
            if spec.use_appcontainer:
                self._setup_appcontainer()
        except BaseException:
            self.close()
            raise

    # -- 资源与标识 ---------------------------------------------------------

    @staticmethod
    def available() -> bool:
        """当前平台是否具备 OS 级沙盒能力（非 win32 恒 False → sandbox_unavailable）。"""
        return _IS_WINDOWS

    @property
    def isolation_key(self) -> tuple[str, str, str]:
        """规范 §3 隔离键：不同私有作用域不复用带状态进程。"""
        return (self._spec.plugin_id, self._spec.plugin_release, self._spec.isolation_scope)

    @property
    def workspace_dir(self) -> str | None:
        return self._workspace

    def _create_job(self) -> int:
        assert _kernel32 is not None
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise SandboxUnavailableError(
                "create_job_object", win32_error=ctypes.get_last_error()
            )
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
            | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
        limits.BasicLimitInformation.ActiveProcessLimit = self._spec.active_process_limit
        limits.ProcessMemoryLimit = self._spec.memory_limit_bytes
        limits.JobMemoryLimit = self._spec.memory_limit_bytes
        if not _kernel32.SetInformationJobObject(
            handle,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(handle)
            raise SandboxUnavailableError("set_job_limits", win32_error=err)

        if self._spec.cpu_rate_percent is not None:
            ctrl = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
            ctrl.ControlFlags = (
                _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            )
            ctrl.CpuRate = self._spec.cpu_rate_percent * 100  # 单位=百分比×100
            if not _kernel32.SetInformationJobObject(
                handle,
                _JobObjectCpuRateControlInformation,
                ctypes.byref(ctrl),
                ctypes.sizeof(ctrl),
            ):
                err = ctypes.get_last_error()
                _kernel32.CloseHandle(handle)
                raise SandboxUnavailableError("set_cpu_rate", win32_error=err)
        return handle

    # -- AppContainer -------------------------------------------------------

    def _setup_appcontainer(self) -> None:
        assert self._workspace is not None and _advapi32 is not None
        profile_name = _appcontainer_profile_name(
            self._spec.plugin_id, self._spec.plugin_release, self._spec.isolation_scope
        )
        try:
            self._ac_sid = _ensure_appcontainer_sid(profile_name)
            # create 成功才登记 profile（close 时删除；失败无残留可清）
            self._ac_profile_name = profile_name
            _grant_workspace_to_sid(self._workspace, self._ac_sid)
        except SandboxUnavailableError:
            raise
        except OSError as exc:
            raise SandboxUnavailableError(
                "appcontainer_setup", detail=f"{type(exc).__name__}: {exc}"
            ) from exc

    # -- 启动 ---------------------------------------------------------------

    def launch(self) -> SandboxProcess:
        """启动子进程（CREATE_SUSPENDED → 挂 Job → 恢复线程；AC 路径同序）。"""
        _require_windows()
        if self._h_job is None:
            raise RuntimeError("沙盒已关闭，不可再 launch")
        proc = self._launch_appcontainer() if self._spec.use_appcontainer else self._launch_job()
        self._last_process = proc
        return proc

    def _child_env(self) -> dict[str, str]:
        """环境白名单过滤：只传显式允许键；TEMP/TMP 钉进私有工作区。"""
        whitelist = (
            self._spec.env_whitelist
            if self._spec.env_whitelist is not None
            else DEFAULT_ENV_WHITELIST
        )
        env = {key: os.environ[key] for key in whitelist if key in os.environ}
        if self._workspace is not None:
            tmp_dir = os.path.join(self._workspace, "tmp")
            env["TEMP"] = tmp_dir
            env["TMP"] = tmp_dir
        return env

    def _launch_job(self) -> SandboxProcess:
        """Job 隔离路径：venv 同解释器/任意可执行文件，管道可用，句柄不继承。"""
        assert self._h_job is not None and self._workspace is not None
        popen = subprocess.Popen(
            [self._spec.executable, *self._spec.argv],
            cwd=self._workspace,
            env=self._child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,  # 默认不继承句柄
            creationflags=_CREATE_SUSPENDED,  # 挂起创建，先挂 Job 再放行（subprocess 未暴露此旗标）
        )
        try:
            _assign_process_to_job(self._h_job, popen.pid)
            _resume_process_threads(popen.pid)
        except SandboxUnavailableError:
            popen.kill()
            popen.wait(timeout=10)
            raise
        return SandboxProcess(popen.pid, popen=popen)

    def _launch_appcontainer(self) -> SandboxProcess:
        """AppContainer 路径：SECURITY_CAPABILITIES（0 capability）+ STARTUPINFOEX。"""
        assert _kernel32 is not None and self._h_job is not None
        assert self._ac_sid is not None and self._workspace is not None
        env = self._child_env()
        # 平台硬约束：AC 子进程环境块必须带 LOCALAPPDATA（见 AC_REQUIRED_ENV_KEYS 注释）
        for key in AC_REQUIRED_ENV_KEYS:
            if key not in env:
                if key not in os.environ:
                    raise SandboxUnavailableError(
                        "appcontainer_env",
                        detail=f"父环境缺少平台必需键 {key}，无法构建 AppContainer 环境块",
                    )
                env[key] = os.environ[key]
        env_block = ctypes.create_unicode_buffer(
            "".join(f"{key}={value}\0" for key, value in sorted(env.items())) + "\0"
        )

        # 属性表：1 个条目（SECURITY_CAPABILITIES，capability=0 → 无网络等一切能力）
        attr_size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
        attr_buf = ctypes.create_string_buffer(attr_size.value)
        attr_list = ctypes.cast(attr_buf, wintypes.LPVOID)
        attr_initialized = False
        sec_caps = _SECURITY_CAPABILITIES(
            AppContainerSid=self._ac_sid, Capabilities=None, CapabilityCount=0
        )
        try:
            if not _kernel32.InitializeProcThreadAttributeList(
                attr_list, 1, 0, ctypes.byref(attr_size)
            ):
                raise SandboxUnavailableError(
                    "init_proc_thread_attribute_list", win32_error=ctypes.get_last_error()
                )
            attr_initialized = True
            if not _kernel32.UpdateProcThreadAttribute(
                attr_list,
                0,
                _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(sec_caps),
                ctypes.sizeof(sec_caps),
                None,
                None,
            ):
                raise SandboxUnavailableError(
                    "update_proc_thread_attribute", win32_error=ctypes.get_last_error()
                )

            si_ex = STARTUPINFOEXW()
            si_ex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            si_ex.lpAttributeList = attr_list
            pi = _PROCESS_INFORMATION()
            # AC 路径 argv 逐字拼接（不经 shell、不做转义重写；调用方自备引号）
            command_line = ctypes.c_wchar_p(
                f'"{self._spec.executable}"' + (f" {' '.join(self._spec.argv)}" if self._spec.argv else "")
            )
            ok = _kernel32.CreateProcessW(
                self._spec.executable,
                command_line,
                None,
                None,
                False,  # bInheritHandles=FALSE：默认不继承句柄
                _CREATE_SUSPENDED
                | _CREATE_UNICODE_ENVIRONMENT  # 环境块是宽字符，缺此旗标会按 ANSI 误解析
                | _EXTENDED_STARTUPINFO_PRESENT,
                ctypes.byref(env_block),
                self._workspace,
                ctypes.byref(si_ex),
                ctypes.byref(pi),
            )
            if not ok:
                raise SandboxUnavailableError(
                    "create_process_appcontainer", win32_error=ctypes.get_last_error()
                )
        finally:
            if attr_initialized:
                _kernel32.DeleteProcThreadAttributeList(attr_list)

        try:
            if not _kernel32.AssignProcessToJobObject(self._h_job, pi.hProcess):
                raise SandboxUnavailableError(
                    "assign_job_object", win32_error=ctypes.get_last_error()
                )
            _kernel32.ResumeThread(pi.hThread)
        finally:
            _kernel32.CloseHandle(pi.hThread)
        return SandboxProcess(pi.dwProcessId, process_handle=pi.hProcess)

    # -- 终止与回收 ---------------------------------------------------------

    def terminate(self, exit_code: int = 1) -> None:
        """TerminateJobObject：立即终止作业内全部进程（句柄保留）。"""
        assert _kernel32 is not None
        if self._h_job is not None:
            _kernel32.TerminateJobObject(self._h_job, exit_code)

    def close(self) -> None:
        """回收：关 Job 句柄（KILL_ON_JOB_CLOSE 杀全体）→ 释放 SID → 删 AC profile。

        幂等；监督器正常退出与异常路径都必须走到这里（不残留进程/profile）。
        """
        if not _IS_WINDOWS or _kernel32 is None or _userenv is None:
            return
        if self._h_job is not None:
            _kernel32.CloseHandle(self._h_job)  # KILL_ON_JOB_CLOSE → 全体进程回收
            self._h_job = None
        if self._last_process is not None:
            self._last_process._close_handle()
            self._last_process = None
        if self._ac_sid is not None:
            _kernel32.LocalFree(wintypes.LPVOID(self._ac_sid))
            self._ac_sid = None
        if self._ac_profile_name is not None:
            hr = _userenv.DeleteAppContainerProfile(self._ac_profile_name)
            if hr != 0:
                logger.warning("删除 AppContainer profile 失败：%s hr=0x%08X", self._ac_profile_name, hr & 0xFFFFFFFF)
            self._ac_profile_name = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:  # 析构期尽力回收，不掩盖原异常
            logger.debug("WindowsSandbox.__del__ 回收失败", exc_info=True)


# ---------------------------------------------------------------------------
# Win32 原子操作（模块级，供沙盒与测试 monkeypatch 复用）
# ---------------------------------------------------------------------------


def _assign_process_to_job(h_job: int, pid: int) -> None:
    assert _kernel32 is not None
    handle = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not handle:
        raise SandboxUnavailableError(
            "assign_job_object", win32_error=ctypes.get_last_error(), detail=f"OpenProcess pid={pid}"
        )
    try:
        if not _kernel32.AssignProcessToJobObject(h_job, handle):
            raise SandboxUnavailableError(
                "assign_job_object",
                win32_error=ctypes.get_last_error(),
                detail=f"pid={pid}",
            )
    finally:
        _kernel32.CloseHandle(handle)


def _resume_process_threads(pid: int) -> None:
    """恢复目标进程全部线程（CREATE_SUSPENDED 启动后用；Toolhelp 枚举公开 API）。"""
    assert _kernel32 is not None
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        raise SandboxUnavailableError(
            "resume_thread", win32_error=ctypes.get_last_error(), detail=f"pid={pid}"
        )
    resumed = 0
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        ok = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                )
                if thread:
                    _kernel32.ResumeThread(thread)
                    _kernel32.CloseHandle(thread)
                    resumed += 1
            ok = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    if resumed == 0:
        raise SandboxUnavailableError("resume_thread", detail=f"pid={pid} 无可恢复线程")


def _appcontainer_profile_name(plugin_id: str, plugin_release: str, scope: str) -> str:
    """AC profile 名：仅字母数字、≤64 字符、含内容哈希与随机后缀保证唯一。"""
    digest = hashlib.sha1(f"{plugin_id}|{plugin_release}|{scope}".encode()).hexdigest()[:10]
    return f"shorekeeper{digest}{uuid.uuid4().hex[:8]}"


def _userenv_create_app_container_profile_raw(name: str, display_name: str, description: str) -> int:
    """CreateAppContainerProfile 原始封装：返回 HRESULT（0=成功）。

    单点失败注入面：测试 monkeypatch 本函数模拟 AC 不可用（无提权/策略拒绝）。
    """
    assert _userenv is not None and _kernel32 is not None
    sid_out = wintypes.LPVOID()
    hr = _userenv.CreateAppContainerProfile(
        name, display_name, description, None, 0, ctypes.byref(sid_out)
    )
    if sid_out:  # 成功路径也统一走 derive 取 SID，这里先释放创建返回的副本
        _kernel32.LocalFree(sid_out)
    return hr


def _derive_appcontainer_sid(name: str) -> int:
    """DeriveAppContainerSidFromAppContainerName：失败抛 SandboxUnavailableError。"""
    assert _userenv is not None
    sid_out = wintypes.LPVOID()
    hr = _userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid_out))
    if hr != 0:
        raise SandboxUnavailableError(
            "derive_appcontainer_sid", win32_error=hr, detail=f"name={name}"
        )
    return sid_out.value or 0


def _ensure_appcontainer_sid(profile_name: str) -> int:
    """建 AC profile（无 capability）→ 派生 SID。

    注意（真机实证）：``DeriveAppContainerSidFromAppContainerName`` 是纯算法派生，
    对不存在的 profile 也返回成功——因此 create 失败不能靠 derive"兜底"：
    那会得到一个无 profile 存储的半装配 AC。规范 §3 要求显式不可用，故
    create 任一失败（权限/策略拒绝）一律 ``sandbox_unavailable``，绝不同权限降级。
    """
    display = "守岸人插件沙盒"
    description = "shorekeeper bot plugin AppContainer（无 capability，禁网）"
    hr = _userenv_create_app_container_profile_raw(profile_name, display, description)
    if hr != 0:
        raise SandboxUnavailableError(
            "create_appcontainer_profile", win32_error=hr, detail=f"name={profile_name}"
        )
    return _derive_appcontainer_sid(profile_name)


def _sid_to_string(sid: int) -> str:
    assert _advapi32 is not None and _kernel32 is not None
    out = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(wintypes.LPVOID(sid), ctypes.byref(out)):
        raise SandboxUnavailableError("convert_sid_to_string", win32_error=ctypes.get_last_error())
    text = out.value or ""
    _kernel32.LocalFree(out)
    return text


def _current_user_sid_string() -> str:
    """当前进程用户 SID（SDDL 授权 DACL 时保住用户自身访问权）。"""
    assert _advapi32 is not None and _kernel32 is not None
    token = wintypes.HANDLE()
    if not _kernel32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise SandboxUnavailableError("open_process_token", win32_error=ctypes.get_last_error())
    try:
        needed = wintypes.DWORD(0)
        _advapi32.GetTokenInformation(token, _TokenUser, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not _advapi32.GetTokenInformation(
            token, _TokenUser, buf, needed.value, ctypes.byref(needed)
        ):
            raise SandboxUnavailableError(
                "get_token_information", win32_error=ctypes.get_last_error()
            )
        token_user = ctypes.cast(buf, ctypes.POINTER(_TOKEN_USER)).contents
        return _sid_to_string(token_user.Sid)
    finally:
        _kernel32.CloseHandle(token)


def _grant_workspace_to_sid(workspace: str, sid: int) -> None:
    """给工作区目录写保护 DACL：SY/BA/当前用户/AC SID 四 ACE（生成物隔离）。

    用 SDDL 整体替换并 PROTECTED（目录是一次性私有工作区，不依赖父目录继承）。
    失败即显式不可用：没有可写工作区的 AppContainer 不满足生成物隔离要求。
    """
    assert _advapi32 is not None and _kernel32 is not None
    ac_sid_str = _sid_to_string(sid)
    user_sid_str = _current_user_sid_string()
    sddl = (
        f"D:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        f"(A;OICI;FA;;;{user_sid_str})(A;OICI;FA;;;{ac_sid_str})"
    )
    sec_desc = wintypes.LPVOID()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, _SDDL_REVISION_1, ctypes.byref(sec_desc), None
    ):
        raise SandboxUnavailableError(
            "workspace_acl_grant", win32_error=ctypes.get_last_error(), detail=f"sddl={sddl}"
        )
    try:
        dacl_present = wintypes.BOOL()
        dacl = wintypes.LPVOID()
        dacl_defaulted = wintypes.BOOL()
        if not _advapi32.GetSecurityDescriptorDacl(
            sec_desc, ctypes.byref(dacl_present), ctypes.byref(dacl), ctypes.byref(dacl_defaulted)
        ):
            raise SandboxUnavailableError(
                "workspace_acl_grant", win32_error=ctypes.get_last_error()
            )
        # 返回 0=成功（Win32 ERROR）
        ret = _advapi32.SetNamedSecurityInfoW(
            workspace,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl if dacl_present else None,
            None,
        )
        if ret != 0:
            raise SandboxUnavailableError(
                "workspace_acl_grant", win32_error=ret, detail=f"path={workspace}"
            )
    finally:
        _kernel32.LocalFree(sec_desc)
