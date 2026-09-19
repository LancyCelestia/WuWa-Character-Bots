"""Windows DACL 操作原语：Deny-Write ACL 施加 / 快照恢复（ctypes + icacls 交叉验证）。

V2.1 S1 的 ACL 席位（尽力而为层，合同标注为 best-effort）：
- 主机制：advapi32 ``GetNamedSecurityInfoW`` → ``SetEntriesInAclW``（追加 DENY ACE）
  → ``SetNamedSecurityInfoW``；快照与恢复用同一 ctypes 链路，保证可逆。
- 辅助验证：``icacls``（本机工具，无网络）dump 输出作为独立证据源。
- 施加对象刻意使用**临时 scratch 路径**（tmp_path），不动真实工作区/Runtime——
  对生产路径做 Deny ACL 属高危变更，S4 Supervisor 接入时应另走用户审批。

Deny 掩码 = 具体权利 FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|DELETE
（目录语境下 FILE_WRITE_DATA=FILE_ADD_FILE、FILE_APPEND_DATA=FILE_ADD_SUBDIRECTORY：
目录内新建/改写全部拒绝）。**禁止使用 GENERIC_WRITE 等泛型位**（2026-09-17 真机事故
实证）：泛型位经 generic mapping 展开后包含 READ_CONTROL（STANDARD_RIGHTS_WRITE），一旦
DENY 即连安全描述符都不可读，所有者连 icacls / SetNamedSecurityInfoW 恢复通道都被锁死，
产生无提权不可回收的孤儿目录。本掩码刻意不 deny READ_CONTROL / WRITE_DAC / WRITE_OWNER，
恢复通道恒在；不 deny FILE_READ_DATA，只读语义可见。
诚实边界：DELETE deny 位**不阻断 owner 删除**（Windows 经 OWNER RIGHTS(F)/父目录
删除旁路绕开，真机 D1-D3/E1 对照实验实证）——删除防护归 Job 层，非 ACL 尽力而为层。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

__all__ = [
    "AclError",
    "apply_deny_write",
    "apply_grant_full_control",
    "create_appcontainer_workspace",
    "current_user_sid_string",
    "icacls_dump",
    "restore_dacl",
    "snapshot_dacl",
]

IS_WINDOWS = sys.platform == "win32"

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x0000_0004
GRANT_ACCESS = 1
DENY_ACCESS = 3
TRUSTEE_IS_SID = 0
TRUSTEE_IS_USER = 1
#: 强制完整性标签：Low + no-write-up（AppContainer 进程=Low IL，Medium 完整性对象
#: 的 no-write-up 强制策略会拦掉一切写入——仅 DACL 授权形同虚设，2026-09-17 真机实证）。
#: 写既有对象的 SACL 需要 SeSecurityPrivilege（非提权令牌没有），但**创建时**在
#: SECURITY_ATTRIBUTES 的 SD 里携带标签不需要特权——故 AC 工作区必须走
#: create_appcontainer_workspace（创建即授权）。
SDDL_LOW_LABEL_NW = "S:(ML;;NW;;;LW)"
#: 目录内新建（FILE_ADD_FILE）
FILE_WRITE_DATA = 0x0000_0002
#: 目录内新建子目录（FILE_ADD_SUBDIRECTORY）
FILE_APPEND_DATA = 0x0000_0004
FILE_WRITE_EA = 0x0000_0010
FILE_WRITE_ATTRIBUTES = 0x0000_0100
DELETE_RIGHT = 0x0001_0000
#: 拒写=具体权利位集合（绝不含泛型位/GENERIC_*，理由见模块 docstring）
DENY_WRITE_MASK = (
    FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA | FILE_WRITE_ATTRIBUTES | DELETE_RIGHT
)
NO_INHERITANCE = 0x0
#: OBJECT_INHERIT_ACE（文件继承）
OBJECT_INHERIT_ACE = 0x1
#: CONTAINER_INHERIT_ACE（容器继承）
CONTAINER_INHERIT_ACE = 0x2
#: 子容器与对象都继承（0x3）。注意 2026-09-17 真机实证：误设 0x2（仅容器）时
#: deny/grant ACE 永不下传到目录内既有与新建的**文件**，拒写验证形同虚设。
SUB_CONTAINERS_AND_OBJECTS_INHERIT = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE


class AclError(RuntimeError):
    """ACL 原语失败（带 WinError 码）。"""


if IS_WINDOWS:

    class TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", wintypes.LPVOID),
            ("MultipleTrusteeOperation", wintypes.DWORD),
            ("TrusteeForm", wintypes.DWORD),
            ("TrusteeType", wintypes.DWORD),
            ("ptstrName", wintypes.LPVOID),
        ]

    class EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", wintypes.DWORD),
            ("grfAccessMode", wintypes.DWORD),
            ("grfInheritance", wintypes.DWORD),
            ("Trustee", TRUSTEE_W),
        ]


def _advapi():
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.GetNamedSecurityInfoW.restype = wintypes.DWORD
    a.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    a.SetNamedSecurityInfoW.restype = wintypes.DWORD
    a.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID,
    ]
    a.SetEntriesInAclW.restype = wintypes.DWORD
    a.SetEntriesInAclW.argtypes = [
        wintypes.ULONG, ctypes.POINTER(EXPLICIT_ACCESS_W), wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    a.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    a.GetSecurityDescriptorDacl.argtypes = [
        wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.BOOL),
    ]
    a.ConvertStringSidToSidW.restype = wintypes.BOOL
    a.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    a.GetTokenInformation.restype = wintypes.BOOL
    a.GetTokenInformation.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    a.ConvertSidToStringSidW.restype = wintypes.BOOL
    a.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    return a


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = ctypes.c_void_p  # 伪句柄 -1 以无符号回传，避免 OverflowError
    k.GetCurrentProcess.argtypes = []
    k.LocalFree.restype = wintypes.HLOCAL
    k.LocalFree.argtypes = [wintypes.HLOCAL]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


if IS_WINDOWS:

    class SECURITY_ATTRIBUTES_DESC(ctypes.Structure):
        """CreateDirectoryW/CreateFileW 的 SECURITY_ATTRIBUTES（携带显式 SD）。"""

        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]


def current_user_sid_string() -> str:
    """当前进程令牌的 TokenUser SID 字符串（S-1-5-21-... 形态）。"""
    if not IS_WINDOWS:
        raise AclError("ACL 原语仅在 Windows 可用")
    a = _advapi()
    k = _kernel32()
    TokenUser = 1
    token = wintypes.HANDLE()
    if not a.OpenProcessToken(
        ctypes.c_void_p(k.GetCurrentProcess()), 0x0008, ctypes.byref(token)  # TOKEN_QUERY
    ):
        raise AclError(f"OpenProcessToken failed: WinError {ctypes.get_last_error()}")
    try:
        need = wintypes.DWORD(0)
        a.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(need.value)
        if not a.GetTokenInformation(token, TokenUser, buf, need.value, ctypes.byref(need)):
            raise AclError(f"GetTokenInformation failed: WinError {ctypes.get_last_error()}")
        sid_ptr = wintypes.LPVOID.from_buffer_copy(buf).value
        out = wintypes.LPWSTR()
        if not a.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
            raise AclError(f"ConvertSidToStringSidW failed: WinError {ctypes.get_last_error()}")
        try:
            # LPWSTR.value 在 ctypes 中已自动转为 str（无需 wstring_at 解引用）
            return out.value or ""
        finally:
            k.LocalFree(out)
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(token)


def snapshot_dacl(path: str) -> int:
    """取路径 DACL 快照（PSECURITY_DESCRIPTOR 裸地址），用于恢复。

    返回底层 PSECURITY_DESCRIPTOR 指针值（int）；恢复期间必须保持有效，
    restore_dacl 之后由调用方 LocalFree（或用 release_dacl_snapshot）。
    """
    if not IS_WINDOWS:
        raise AclError("ACL 原语仅在 Windows 可用")
    a = _advapi()
    owner = wintypes.LPVOID()
    group = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    sacl = wintypes.LPVOID()
    psd = wintypes.LPVOID()
    rc = a.GetNamedSecurityInfoW(
        str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(psd),
    )
    if rc != 0:
        raise AclError(f"GetNamedSecurityInfoW failed: {rc:#x}")
    return int(psd.value or 0)


def release_dacl_snapshot(psd: int) -> None:
    if psd:
        _kernel32().LocalFree(ctypes.c_void_p(psd))


def restore_dacl(path: str, psd: int) -> None:
    """用快照 SD 内的 DACL 覆写回目标路径（ctypes 原路恢复）。"""
    a = _advapi()
    present = wintypes.BOOL()
    dacl = wintypes.LPVOID()
    defaulted = wintypes.BOOL()
    if not a.GetSecurityDescriptorDacl(ctypes.c_void_p(psd), ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise AclError(f"GetSecurityDescriptorDacl failed: WinError {ctypes.get_last_error()}")
    if not present.value or not dacl.value:
        raise AclError("快照 SD 中无 DACL（异常状态，拒绝盲恢复）")
    rc = a.SetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, dacl.value, None)
    if rc != 0:
        raise AclError(f"SetNamedSecurityInfoW(restore) failed: {rc:#x}")


def apply_deny_write(path: str, sid_string: str, *, inherit: bool = True) -> str:
    """对路径追加 DENY(GENERIC_WRITE|DELETE) ACE（对指定 SID），返回可读证据串。

    失败抛 AclError；不改变 DACL 其余条目（在既有 DACL 基础上追加）。
    """
    if not IS_WINDOWS:
        raise AclError("ACL 原语仅在 Windows 可用")
    a = _advapi()
    owner = wintypes.LPVOID()
    group = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    sacl = wintypes.LPVOID()
    psd = wintypes.LPVOID()
    rc = a.GetNamedSecurityInfoW(
        str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(psd),
    )
    if rc != 0:
        raise AclError(f"GetNamedSecurityInfoW failed: {rc:#x}")
    try:
        sid = wintypes.LPVOID()
        if not a.ConvertStringSidToSidW(str(sid_string), ctypes.byref(sid)):
            raise AclError(f"ConvertStringSidToSidW failed: WinError {ctypes.get_last_error()}")
        try:
            ea = EXPLICIT_ACCESS_W()
            ea.grfAccessPermissions = DENY_WRITE_MASK
            ea.grfAccessMode = DENY_ACCESS
            ea.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT if inherit else NO_INHERITANCE
            ea.Trustee.pMultipleTrustee = None
            ea.Trustee.MultipleTrusteeOperation = 0
            ea.Trustee.TrusteeForm = TRUSTEE_IS_SID
            ea.Trustee.TrusteeType = TRUSTEE_IS_USER
            ea.Trustee.ptstrName = sid.value
            new_dacl = wintypes.LPVOID()
            rc2 = a.SetEntriesInAclW(1, ctypes.byref(ea), dacl.value, ctypes.byref(new_dacl))
            if rc2 != 0:
                raise AclError(f"SetEntriesInAclW failed: {rc2:#x}")
            try:
                rc3 = a.SetNamedSecurityInfoW(
                    str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, new_dacl.value, None
                )
                if rc3 != 0:
                    raise AclError(f"SetNamedSecurityInfoW(apply) failed: {rc3:#x}")
            finally:
                _kernel32().LocalFree(ctypes.c_void_p(new_dacl.value))
        finally:
            _kernel32().LocalFree(sid)
    finally:
        _kernel32().LocalFree(ctypes.c_void_p(psd.value))
    return f"DENY write/delete(specific rights {DENY_WRITE_MASK:#010x}) -> {sid_string} on {path}"


def apply_grant_full_control(path: str, sid_string: str, *, inherit: bool = True) -> str:
    """给指定 SID 追加 Full Control 允许 ACE（DACL 追加，不整体替换）。

    注意：这只解决 DACL 授权。AppContainer 进程跑在 Low 完整性，对 Medium 完整性
    的既有目录，强制策略 no-write-up 会拦掉一切写入——**对既有目录补授不足以让 AC
    写入**（真机实证）。AppContainer 工作区必须用 :func:`create_appcontainer_workspace`
    （创建即授权+Low 标签，免 SeSecurityPrivilege）。
    """
    if not IS_WINDOWS:
        raise AclError("ACL 原语仅在 Windows 可用")
    a = _advapi()
    owner = wintypes.LPVOID()
    group = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    sacl = wintypes.LPVOID()
    psd = wintypes.LPVOID()
    rc = a.GetNamedSecurityInfoW(
        str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(psd),
    )
    if rc != 0:
        raise AclError(f"GetNamedSecurityInfoW failed: {rc:#x}")
    try:
        sid = wintypes.LPVOID()
        if not a.ConvertStringSidToSidW(str(sid_string), ctypes.byref(sid)):
            raise AclError(f"ConvertStringSidToSidW failed: WinError {ctypes.get_last_error()}")
        try:
            ea = EXPLICIT_ACCESS_W()
            ea.grfAccessPermissions = 0x1F01FF  # GENERIC_ALL 的文件映射（FILE_ALL_ACCESS|）
            ea.grfAccessMode = GRANT_ACCESS
            ea.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT if inherit else NO_INHERITANCE
            ea.Trustee.pMultipleTrustee = None
            ea.Trustee.MultipleTrusteeOperation = 0
            ea.Trustee.TrusteeForm = TRUSTEE_IS_SID
            ea.Trustee.TrusteeType = TRUSTEE_IS_USER
            ea.Trustee.ptstrName = sid.value
            new_dacl = wintypes.LPVOID()
            rc2 = a.SetEntriesInAclW(1, ctypes.byref(ea), dacl.value, ctypes.byref(new_dacl))
            if rc2 != 0:
                raise AclError(f"SetEntriesInAclW failed: {rc2:#x}")
            try:
                rc3 = a.SetNamedSecurityInfoW(
                    str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, new_dacl.value, None
                )
                if rc3 != 0:
                    raise AclError(f"SetNamedSecurityInfoW(grant) failed: {rc3:#x}")
            finally:
                _kernel32().LocalFree(ctypes.c_void_p(new_dacl.value))
        finally:
            _kernel32().LocalFree(sid)
    finally:
        _kernel32().LocalFree(ctypes.c_void_p(psd.value))
    return f"GRANT FULL_CONTROL -> {sid_string} on {path}"


def create_appcontainer_workspace(path: str, ac_sid_string: str) -> str:
    """一次性创建 AppContainer 私有工作区目录（DACL 授权 + Low 强制完整性标签）。

    创建时在 SECURITY_ATTRIBUTES 的 SD 里同时携带 DACL 与 SACL 标签——
    标签**创建时**赋值不需要 SeSecurityPrivilege（写既有对象 SACL 才需要；
    非提权令牌没有该特权，2026-09-17 真机实证）。
    DACL：SYSTEM/Administrators/当前用户/AC SID 四个 Full Control ACE（保证
    调用方与 pytest 清理不受阻），AC SID ACE 让容器内进程可写生成物。
    SACL：``Low`` + no-write-up，容器（Low IL）可写；更高完整性进程写下行不受限。

    **链路前提（2026-09-17 真机实证）**：AppContainer 访问检查作用于路径上**每一级**
    目录——本机 C:\\Users 以下没有任何 package SID / ALL APPLICATION PACKAGES ACE，
    故把工作区放在 %TEMP%/%LOCALAPPDATA% 下时本原语给足授权也到不了（遍历即拒）。
    S4 接入时工作区必须布置在自根而下逐级带 package 遍历授权的专用前缀下（§3
    "插件发布目录带 ALL APPLICATION PACKAGES ACE" 的写侧等价物）。
    目录必须不存在（一次性新建），已存在即 AclError。
    """
    if not IS_WINDOWS:
        raise AclError("ACL 原语仅在 Windows 可用")
    user_sid = current_user_sid_string()
    sddl = (
        f"D:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{user_sid})"
        f"(A;OICI;FA;;;{ac_sid_string}){SDDL_LOW_LABEL_NW}"
    )
    a = _advapi()
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG),
    ]
    sd = wintypes.LPVOID()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise AclError(f"ConvertStringSecurityDescriptor failed: WinError {ctypes.get_last_error()} (sddl={sddl})")
    try:
        sa = SECURITY_ATTRIBUTES_DESC()
        sa.nLength = ctypes.sizeof(sa)
        sa.lpSecurityDescriptor = sd.value
        sa.bInheritHandle = False
        k = _kernel32()
        k.CreateDirectoryW.restype = wintypes.BOOL
        k.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SECURITY_ATTRIBUTES_DESC)]
        if not k.CreateDirectoryW(str(path), ctypes.byref(sa)):
            err = ctypes.get_last_error()
            raise AclError(f"CreateDirectoryW({path}) failed: WinError {err}（183=目录已存在，需一次性新路径）")
    finally:
        _kernel32().LocalFree(sd)
    return f"CREATE {path} with GRANT(FA) SY/BA/{user_sid}/{ac_sid_string} + Low(IL,NW)"


def icacls_dump(path: str) -> str:
    """icacls 只读输出（辅助验证证据源；本机工具，无网络）。

    字节捕获 + errors="replace" 解码：icacls 输出走本地控制台码页（中文系统为
    GBK），text=True 在 PYTHONUTF8=1 下会按 UTF-8 严格解码并炸掉读线程；本函数
    只依赖 ASCII 形态的 ACE 标记（DENY 等），replace 容错不影响判定。
    """
    proc = subprocess.run(
        ["icacls", str(path)], capture_output=True, timeout=30, shell=False, check=False
    )
    if proc.returncode != 0:
        raise AclError(f"icacls failed rc={proc.returncode}: {proc.stderr!r}")
    return proc.stdout.decode("utf-8", errors="replace")
