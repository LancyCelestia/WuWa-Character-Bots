"""AppContainer（低完整性容器）ctypes 尽力而为实现 + SandboxUnavailable 阻断路径。

纯 Python 路线（无第三方依赖，全部 Win32/ntdll 直调）：
  1. userenv.CreateAppContainerProfile               注册容器档案（%LOCALAPPDATA%\\Packages\\<name>）
  2. userenv.DeriveAppContainerSidFromAppContainerName → 推导容器 SID
  3. advapi32.OpenProcessToken                        取自身主令牌
  4. ntdll.NtCreateLowBoxToken                        派生 lowbox 主令牌
     （capability 列表为空 ⇒ 无 internet / 无 privateNetwork / 无任何资源声明）
  5. userenv.CreateEnvironmentBlock                   构造子进程环境块
  6. kernel32.CreateProcessAsUserW(CREATE_SUSPENDED)   挂起拉起（交调用方挂 Job 后恢复）

失败语义（V2.1 §3 合同）：任意一步失败 → ``SandboxUnavailable``（error_code=
``sandbox_unavailable``）带步骤级诊断；**绝不降级**为普通同权限 subprocess。
容器档案是用户级状态（HKCU + %LOCALAPPDATA%），用 ``delete_appcontainer_profile``
回收；删除失败会如实记入诊断（残留清单），不假称清理成功。
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

__all__ = [
    "AppContainerSession",
    "SandboxUnavailable",
    "create_ac_pipe",
    "create_app_container_profile",
    "delete_app_container_profile",
    "derive_app_container_sid",
    "launch_appcontainer_process",
    "probe_appcontainer",
]

IS_WINDOWS = sys.platform == "win32"

_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9.]{3,64}$")


class SandboxUnavailable(RuntimeError):
    """强隔离层不可用——调用方必须显式阻断，不得同权限降级（V2.1 §3）。

    error_code 固定为 ``sandbox_unavailable``（§错误码表，REST 映射 503）；
    layer/step/os_code/diagnostics 提供步骤级可审计证据。
    """

    error_code = "sandbox_unavailable"

    def __init__(
        self,
        layer: str,
        step: str,
        message: str = "",
        os_code: int = 0,
        diagnostics: list[str] | None = None,
    ):
        self.layer = layer
        self.step = step
        self.message = message
        self.os_code = os_code
        self.diagnostics = list(diagnostics or [])
        super().__init__(f"[{self.error_code}] layer={layer} step={step} os_code={os_code:#x} {message}")

    def as_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "layer": self.layer,
            "step": self.step,
            "os_code": self.os_code,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


@dataclass
class AppContainerSession:
    """一次成功创建的 AppContainer 会话资源（全部句柄，用完 close）。"""

    name: str
    sid: int                      # PSID（LocalFree 归属本对象）
    token: int                    # lowbox 前的源令牌
    lowbox_token: int             # lowbox 主令牌
    environment: int              # 环境块指针
    profile_created_here: bool = True
    notes: list[str] = field(default_factory=list)

    def close(self, *, delete_profile: bool = True) -> list[str]:
        """释放全部资源；返回清理过程备注（含失败项，绝不静默）。"""
        notes = list(self.notes)
        userenv = _userenv()
        if self.lowbox_token:
            _kernel32().CloseHandle(self.lowbox_token)
            self.lowbox_token = 0
        if self.environment:
            if not userenv.DestroyEnvironmentBlock(self.environment):
                notes.append(f"DestroyEnvironmentBlock failed: WinError {ctypes.get_last_error()}")
            self.environment = 0
        if self.token:
            _kernel32().CloseHandle(self.token)
            self.token = 0
        if self.sid:
            _kernel32().LocalFree(ctypes.c_void_p(self.sid))
            self.sid = 0
        if delete_profile and self.profile_created_here:
            err = delete_app_container_profile(self.name)
            if err != 0:
                notes.append(f"DeleteAppContainerProfile({self.name}) -> HRESULT {err:#x}（残留未清，需人工复核）")
        return notes


if IS_WINDOWS:

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class SECURITY_ATTRIBUTES_AND_INHERIT(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", wintypes.LPVOID),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_QUERY = 0x0008
    _TOKEN_ADJUST_DEFAULT = 0x0080
    _TOKEN_ADJUST_SESSIONID = 0x0100
    _SOURCE_TOKEN_ACCESS = (
        _TOKEN_ASSIGN_PRIMARY | _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT | _TOKEN_ADJUST_SESSIONID
    )
    _TOKEN_ALL_ACCESS = 0xF01FF


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.LocalFree.argtypes = [wintypes.HLOCAL]
    k.LocalFree.restype = wintypes.HLOCAL
    return k


def _userenv():
    u = ctypes.WinDLL("userenv", use_last_error=True)
    u.CreateAppContainerProfile.restype = ctypes.HRESULT
    u.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(SID_AND_ATTRIBUTES),
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    u.DeriveAppContainerSidFromAppContainerName.restype = ctypes.HRESULT
    u.DeriveAppContainerSidFromAppContainerName.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    u.DeleteAppContainerProfile.restype = ctypes.HRESULT
    u.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    u.CreateEnvironmentBlock.restype = wintypes.BOOL
    u.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL]
    u.DestroyEnvironmentBlock.restype = wintypes.BOOL
    u.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    return u


def _advapi32():
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.OpenProcessToken.restype = wintypes.BOOL
    a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    return a


def _check_hresult(hresult: int, api: str, diagnostics: list[str]) -> None:
    if hresult != 0:
        raise SandboxUnavailable(
            layer="appcontainer",
            step=api,
            message=f"{api} -> HRESULT {hresult:#010x}",
            os_code=hresult,
            diagnostics=diagnostics,
        )


def create_app_container_profile(name: str, display: str, description: str, diagnostics: list[str]) -> int:
    """创建容器档案，返回 PSID（所有权归调用方）。失败抛 SandboxUnavailable。"""
    if not _CONTAINER_NAME_RE.match(name):
        raise SandboxUnavailable(
            layer="appcontainer",
            step="validate_container_name",
            message=f"invalid container name {name!r}（3-64 位字母数字句点）",
            diagnostics=diagnostics,
        )
    u = _userenv()
    sid = ctypes.c_void_p()
    hr = u.CreateAppContainerProfile(name, display, description, None, 0, ctypes.byref(sid))
    _check_hresult(hr, "CreateAppContainerProfile", diagnostics)
    diagnostics.append(f"CreateAppContainerProfile({name}) OK sid@{sid.value:#x}")
    return int(sid.value or 0)


def derive_app_container_sid(name: str, diagnostics: list[str]) -> int:
    u = _userenv()
    sid = ctypes.c_void_p()
    hr = u.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    _check_hresult(hr, "DeriveAppContainerSidFromAppContainerName", diagnostics)
    diagnostics.append(f"DeriveAppContainerSidFromAppContainerName({name}) OK sid@{sid.value:#x}")
    return int(sid.value or 0)


def delete_app_container_profile(name: str) -> int:
    """删除容器档案，返回 HRESULT（0=成功）。"""
    return int(_userenv().DeleteAppContainerProfile(name))


def open_lowbox_token(name: str, app_sid: int, diagnostics: list[str]) -> tuple[int, int]:
    """由自身主令牌派生 lowbox 主令牌（空 capability ⇒ 无网络无资源声明）。

    返回 (源令牌 handle, lowbox 令牌 handle)；两者都归调用方关闭。
    """
    a = _advapi32()
    k = _kernel32()
    token = wintypes.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), _SOURCE_TOKEN_ACCESS, ctypes.byref(token)):
        raise SandboxUnavailable(
            layer="appcontainer",
            step="OpenProcessToken",
            message=f"OpenProcessToken failed: WinError {ctypes.get_last_error()}",
            os_code=ctypes.get_last_error(),
            diagnostics=diagnostics,
        )
    diagnostics.append(f"OpenProcessToken OK handle={token.value:#x}")
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtCreateLowBoxToken.restype = ctypes.c_long  # NTSTATUS
    ntdll.NtCreateLowBoxToken.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),   # TokenHandle
        wintypes.HANDLE,                   # ExistingTokenHandle
        wintypes.DWORD,                    # DesiredAccess
        ctypes.POINTER(OBJECT_ATTRIBUTES), # ObjectAttributes
        ctypes.c_void_p,                   # AppContainerSid
        wintypes.ULONG,                    # CapabilityCount
        ctypes.POINTER(SID_AND_ATTRIBUTES),  # Capabilities
        wintypes.ULONG,                    # HandleCount
        ctypes.POINTER(wintypes.HANDLE),   # Handles
    ]
    out = wintypes.HANDLE()
    # 先试 NULL ObjectAttributes；被拒（INVALID_PARAMETER）再补一个空结构体。
    status = ntdll.NtCreateLowBoxToken(
        ctypes.byref(out), token, _TOKEN_ALL_ACCESS, None, ctypes.c_void_p(app_sid), 0, None, 0, None
    )
    if status != 0:
        oa = OBJECT_ATTRIBUTES()
        oa.Length = ctypes.sizeof(oa)
        oa.Attributes = 0
        status2 = ntdll.NtCreateLowBoxToken(
            ctypes.byref(out), token, _TOKEN_ALL_ACCESS, ctypes.byref(oa), ctypes.c_void_p(app_sid), 0, None, 0, None
        )
        if status2 != 0:
            raise SandboxUnavailable(
                layer="appcontainer",
                step="NtCreateLowBoxToken",
                message=f"NtCreateLowBoxToken -> NTSTATUS {status:#010x} / retry {status2:#010x}",
                os_code=status2,
                diagnostics=diagnostics,
            )
        status = 0
    diagnostics.append(f"NtCreateLowBoxToken OK NTSTATUS={status:#x} lowbox={out.value:#x}")
    return int(token.value or 0), int(out.value or 0)


def create_appcontainer_environment(lowbox_token: int, diagnostics: list[str]) -> int:
    u = _userenv()
    env = ctypes.c_void_p()
    if not u.CreateEnvironmentBlock(ctypes.byref(env), lowbox_token, False):
        raise SandboxUnavailable(
            layer="appcontainer",
            step="CreateEnvironmentBlock",
            message=f"CreateEnvironmentBlock failed: WinError {ctypes.get_last_error()}",
            os_code=ctypes.get_last_error(),
            diagnostics=diagnostics,
        )
    diagnostics.append(f"CreateEnvironmentBlock OK env@{env.value:#x}")
    return int(env.value or 0)


def create_ac_pipe(ac_sid_string: str, user_sid_string: str | None = None) -> tuple[int, int]:
    """创建一根 AppContainer 进程可写、父进程可读的匿名管道，返回 (read_end, write_end)。

    管道 SD：当前用户 + 容器 SID 双 GRANT(FA) + ``Low`` 强制完整性标签——容器
    （Low IL）对 Medium 管道写不进（no-write-up），必须创建时带标签（免特权）。
    两端都可继承：write_end 经 STARTUPINFO.hStdOutput 传入子进程（带
    STARTF_USESTDHANDLES 的句柄必须可继承，否则子进程拿到无效句柄会挂起）。
    """
    if not IS_WINDOWS:
        raise SandboxUnavailable(layer="appcontainer", step="create_ac_pipe", message="仅 Windows")
    if user_sid_string is None:
        from plugins.bot_unified_runtime.domains.core.supervisor.acl_windows import (
            current_user_sid_string,
        )

        user_sid_string = current_user_sid_string()
    sddl = (
        f"D:(A;OICI;FA;;;{user_sid_string})(A;OICI;FA;;;{ac_sid_string})"
        "S:(ML;;NW;;;LW)"
    )
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG),
    ]
    k = _kernel32()
    sd = wintypes.LPVOID()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise SandboxUnavailable(
            layer="appcontainer",
            step="create_ac_pipe",
            message=f"ConvertStringSecurityDescriptor failed: WinError {ctypes.get_last_error()}",
        )
    try:
        sa = SECURITY_ATTRIBUTES_AND_INHERIT()
        sa.nLength = ctypes.sizeof(sa)
        sa.lpSecurityDescriptor = sd.value
        sa.bInheritHandle = True
        k.CreatePipe.restype = wintypes.BOOL
        k.CreatePipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(SECURITY_ATTRIBUTES_AND_INHERIT), wintypes.DWORD,
        ]
        read_end = wintypes.HANDLE()
        write_end = wintypes.HANDLE()
        if not k.CreatePipe(ctypes.byref(read_end), ctypes.byref(write_end), ctypes.byref(sa), 0):
            raise SandboxUnavailable(
                layer="appcontainer",
                step="create_ac_pipe",
                message=f"CreatePipe failed: WinError {ctypes.get_last_error()}",
            )
        return int(read_end.value or 0), int(write_end.value or 0)
    finally:
        k.LocalFree(sd)


def launch_appcontainer_process(
    session: AppContainerSession,
    argv: list[str],
    *,
    working_directory: str | None = None,
    creation_flags: int = 0x00000004 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW
    std_handles: tuple[int, int, int] | None = None,
):
    """在 AppContainer 内 CREATE_SUSPENDED 拉起进程；返回 (process_handle, thread_handle, pid)。

    令牌为 lowbox（无 capability），进程默认还需挂 Job（调用方负责）后再 resume。
    std_handles=(stdin, stdout, stderr) 时以 STARTF_USESTDHANDLES 传入（句柄必须
    可继承）——容器无任何可写文件系统位置，stdout 只能经 AC 授权管道带出。
    失败抛 SandboxUnavailable，不产生半启动进程外泄。
    纪律：传入 std_handles 管道写端时，调用方必须在 wait 退出前**并发排水**
    （参照 job_objects.ChildProcess.start_stdout_drain）——输出超过管道缓冲
    （~4KB）而父侧不读，子进程会永久阻塞在 WriteFile（管道背压死锁）。
    """
    import subprocess  # 局部引用：仅用 list2cmdline

    # 延迟导入避免与 job_objects 循环依赖；结构体在同包内共享
    from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
        PROCESS_INFORMATION,
        STARTUPINFOW,
    )

    k = _kernel32()
    diagnostics = session.notes
    if working_directory is None:
        working_directory = r"C:\Windows\System32"
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    if std_handles is not None:
        si.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        si.hStdInput, si.hStdOutput, si.hStdError = (wintypes.HANDLE(h) for h in std_handles)
    pi = PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    # 完整函数原型：environment/sid 等句柄都是大地址值，无 argtypes 时 ctypes
    # 默认按 c_int 传参会在 64 位下抛 OverflowError（2026-09-17 真机实证）。
    k.CreateProcessAsUserW.restype = wintypes.BOOL
    k.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,                    # hToken
        wintypes.LPCWSTR,                   # lpApplicationName
        wintypes.LPWSTR,                    # lpCommandLine
        wintypes.LPVOID,                    # lpProcessAttributes
        wintypes.LPVOID,                    # lpThreadAttributes
        wintypes.BOOL,                      # bInheritHandles
        wintypes.DWORD,                     # dwCreationFlags
        wintypes.LPVOID,                    # lpEnvironment
        wintypes.LPCWSTR,                   # lpCurrentDirectory
        ctypes.POINTER(STARTUPINFOW),       # lpStartupInfo
        ctypes.POINTER(PROCESS_INFORMATION),  # lpProcessInformation
    ]
    try:
        ok = k.CreateProcessAsUserW(
            session.lowbox_token,
            None,
            cmdline,
            None,
            None,
            True,  # bInheritHandles：管道句柄走继承传递（继承不重做 DACL 检查）
            creation_flags | 0x400,  # CREATE_UNICODE_ENVIRONMENT
            session.environment,
            working_directory,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
    except ctypes.ArgumentError as exc:
        raise SandboxUnavailable(
            layer="appcontainer",
            step="CreateProcessAsUserW",
            message=f"CreateProcessAsUserW 参数封送失败: {exc}",
            diagnostics=diagnostics,
        ) from exc
    if not ok:
        raise SandboxUnavailable(
            layer="appcontainer",
            step="CreateProcessAsUserW",
            message=f"CreateProcessAsUserW failed: WinError {ctypes.get_last_error()}",
            os_code=ctypes.get_last_error(),
            diagnostics=diagnostics,
        )
    diagnostics.append(f"CreateProcessAsUserW OK pid={pi.dwProcessId}")
    return int(pi.hProcess), int(pi.hThread), int(pi.dwProcessId)


def open_appcontainer_session(name: str, display: str, description: str) -> AppContainerSession:
    """完整走通 1-5 步（建档→SID→lowbox→环境块），返回可复用的会话。

    任何一步失败 → SandboxUnavailable（已建资源在异常前尽力回收）。
    """
    diagnostics: list[str] = []
    sid = 0
    src_token = 0
    lowbox = 0
    env = 0
    try:
        sid = create_app_container_profile(name, display, description, diagnostics)
        derived = derive_app_container_sid(name, diagnostics)
        # 注意：两次调用返回的是两份 SID 拷贝，裸指针必然不同；必须按字符串内容比对
        derived_s = _sid_to_string(derived)
        profile_s = _sid_to_string(sid)
        if derived_s != profile_s:
            diagnostics.append(
                f"WARN: profile sid {profile_s} != derived sid {derived_s}（不一致，以 profile 为准）"
            )
        src_token, lowbox = open_lowbox_token(name, sid, diagnostics)
        env = create_appcontainer_environment(lowbox, diagnostics)
    except SandboxUnavailable:
        # 已建资源回收后再抛
        s = AppContainerSession(
            name=name, sid=sid, token=src_token, lowbox_token=lowbox, environment=env,
            profile_created_here=bool(sid), notes=diagnostics,
        )
        s.close(delete_profile=bool(sid))
        raise
    return AppContainerSession(
        name=name, sid=sid, token=src_token, lowbox_token=lowbox, environment=env,
        profile_created_here=True, notes=diagnostics,
    )


def probe_appcontainer(name: str, display: str, description: str) -> dict:
    """端到端可行性探测：建档→lowbox→CreateProcessAsUserW 拉起 cmd /c exit。

    返回 {"available": bool, "step": str, "os_code": int, "message": str,
          "diagnostics": [...], "sid_string": str|None}。探测自身零残留（档案删除）。
    """
    if not IS_WINDOWS:
        return {"available": False, "step": "platform", "os_code": 0,
                "message": "非 Windows 平台，AppContainer 不可用", "diagnostics": [], "sid_string": None}
    session: AppContainerSession | None = None
    try:
        session = open_appcontainer_session(name, display, description)
        from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
            ChildProcess,  # 复用挂起+回收基础设施
        )

        p_handle, t_handle, pid = launch_appcontainer_process(session, ["cmd.exe", "/d", "/c", "exit 0"])
        child = ChildProcess(process_handle=p_handle, thread_handle=t_handle, pid=pid, stdout_read_handle=0)
        try:
            child.resume()
            rc = child.wait(30.0)
            ok = rc == 0
        finally:
            child.terminate(1)
            child.close()
        sid_string = _sid_to_string(session.sid)
        return {
            "available": ok,
            "step": "CreateProcessAsUserW" if not ok else "complete",
            "os_code": 0 if ok else -1,
            "message": "AppContainer 端到端拉起成功（cmd /c exit 0）" if ok else f"容器内进程退出码异常 {rc}",
            "diagnostics": list(session.notes),
            "sid_string": sid_string,
        }
    except SandboxUnavailable as exc:
        return {
            "available": False,
            "step": exc.step,
            "os_code": exc.os_code,
            "message": exc.message,
            "diagnostics": exc.diagnostics,
            "sid_string": None,
        }
    finally:
        if session is not None:
            session.close(delete_profile=True)


def _sid_to_string(sid: int) -> str | None:
    if not sid:
        return None
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    k = _kernel32()
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    out = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(out)):
        return None
    try:
        # LPWSTR.value 在 ctypes 中已自动转为 str（无需 wstring_at 解引用）
        return out.value
    finally:
        k.LocalFree(out)
