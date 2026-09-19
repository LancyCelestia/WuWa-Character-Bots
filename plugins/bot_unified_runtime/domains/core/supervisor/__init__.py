"""S1 强隔离 Supervisor 包（后端 V2.1 规范 §3 / 验收矩阵 V21-ISO-001/002）。

双席位交付（2026-09-17）：
- **W4 席（插件面 API）**：:mod:`windows_sandbox` —— ``WindowsSandbox`` /
  ``SandboxLaunchSpec``（隔离键、内存/进程数/CPU 配额、AppContainer 属性表路线
  PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES、工作区 DACL 授权）+ :mod:`ipc`
  （长度前缀 JSON 帧协议）。
- **A7/S1 席（原语验证层）**：:mod:`sandbox_windows`（编排）+ :mod:`job_objects`
  （Job 原语：内存/用户态时间配额、CPU 速率、嵌套探测、计量/PID 查询、句柄数）
  + :mod:`appcontainer_windows`（NtCreateLowBoxToken 路线可行性 + sandbox_unavailable
  阻断路径）+ :mod:`acl_windows`（Deny-Write / Grant DACL 施加与快照恢复，
  icacls 交叉验证）。真机验证：tests/test_sandbox_windows.py +
  docs/design/v21-s1-sandbox-log.md。

共同合同：任一层不可用一律显式 ``sandbox_unavailable``（REST 503），绝不同权限
降级为普通 subprocess；监督器退出（句柄关闭）回收 Job 内全部进程。

隔离键 = ``(plugin_id, plugin_release, isolation_scope)``。
本包只依赖标准库，导入零副作用（不注册 matcher / 不读生产配置 / 不起线程）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.core.supervisor.acl_windows import (
    AclError,
    apply_deny_write,
    apply_grant_full_control,
    create_appcontainer_workspace,
    current_user_sid_string,
    icacls_dump,
    restore_dacl,
    snapshot_dacl,
)
from plugins.bot_unified_runtime.domains.core.supervisor.appcontainer_windows import (
    AppContainerSession,
    SandboxUnavailable,
    delete_app_container_profile,
    open_appcontainer_session,
    probe_appcontainer,
)
from plugins.bot_unified_runtime.domains.core.supervisor.ipc import (
    MAX_FRAME_BYTES,
    MAX_NESTING_DEPTH,
    PROTOCOL_VERSION,
    ProtocolViolation,
    decode_frame,
    encode_frame,
    make_envelope,
    recv_frame,
    send_frame,
    validate_envelope,
)
from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
    IS_WINDOWS,
    ChildProcess,
    JobLimits,
    JobObject,
    JobObjectError,
    current_process_handle_count,
    current_process_in_job,
    probe_nested_job_support,
    process_alive,
)
from plugins.bot_unified_runtime.domains.core.supervisor.sandbox_windows import (
    SANDBOX_UNAVAILABLE,
    IsolatedWorker,
    SandboxPolicy,
    probe_sandbox,
    spawn_isolated_worker,
)
from plugins.bot_unified_runtime.domains.core.supervisor.windows_sandbox import (
    AC_REQUIRED_ENV_KEYS,
    DEFAULT_ENV_WHITELIST,
    PLUGIN_MEMORY_LIMITS_BYTES,
    SandboxLaunchSpec,
    SandboxProcess,
    SandboxUnavailableError,
    WindowsSandbox,
)

__all__ = [
    "AC_REQUIRED_ENV_KEYS",
    "DEFAULT_ENV_WHITELIST",
    "IS_WINDOWS",
    "MAX_FRAME_BYTES",
    "MAX_NESTING_DEPTH",
    "PLUGIN_MEMORY_LIMITS_BYTES",
    "PROTOCOL_VERSION",
    "SANDBOX_UNAVAILABLE",
    "AclError",
    "AppContainerSession",
    "ChildProcess",
    "IsolatedWorker",
    "JobLimits",
    "JobObject",
    "JobObjectError",
    "ProtocolViolation",
    "SandboxLaunchSpec",
    "SandboxPolicy",
    "SandboxProcess",
    "SandboxUnavailable",
    "SandboxUnavailableError",
    "WindowsSandbox",
    "apply_deny_write",
    "apply_grant_full_control",
    "create_appcontainer_workspace",
    "current_process_handle_count",
    "current_process_in_job",
    "current_user_sid_string",
    "decode_frame",
    "delete_app_container_profile",
    "encode_frame",
    "icacls_dump",
    "make_envelope",
    "open_appcontainer_session",
    "probe_appcontainer",
    "probe_nested_job_support",
    "probe_sandbox",
    "process_alive",
    "recv_frame",
    "restore_dacl",
    "send_frame",
    "snapshot_dacl",
    "spawn_isolated_worker",
    "validate_envelope",
]
