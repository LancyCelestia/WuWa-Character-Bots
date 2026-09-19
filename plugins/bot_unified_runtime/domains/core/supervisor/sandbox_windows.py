"""S1 Windows 强隔离编排层：Job Objects（必开）+ AppContainer（尽力而为）。

V2.1 §3 合同（docs/design/backend-v2-implementation-guide.md）：
- 所有业务插件最终 AppContainer + Job Objects 强隔离；普通同权限 subprocess
  不是合格替代；
- ``isolation_level="appcontainer"`` 而容器层不可用 → 抛 ``SandboxUnavailable``
  （error_code=``sandbox_unavailable``），**绝不降级**为普通进程；
- Job 挂载失败同理阻断；
- 监督器退出（contextmanager 退出）→ ``KILL_ON_JOB_CLOSE`` + 显式 TerminateJobObject
  双保险，Job 内全部进程回收，零残留。

用法::

    policy = SandboxPolicy(memory_limit_mb=256, active_process_limit=4)
    with spawn_isolated_worker([sys.executable, "-c", worker_code], policy) as worker:
        rc = worker.wait(timeout_s=30)
        print(worker.stdout_text())

本包零 bot 运行时依赖（不 import 本插件任何其余模块），可被任意脚本独立加载。
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator
from dataclasses import dataclass

from plugins.bot_unified_runtime.domains.core.supervisor.appcontainer_windows import (
    SandboxUnavailable,
    open_appcontainer_session,
    probe_appcontainer,
)
from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
    IS_WINDOWS,
    ChildProcess,
    JobLimits,
    JobObject,
    JobObjectError,
    current_process_in_job,
    probe_nested_job_support,
)

__all__ = [
    "IS_WINDOWS",
    "SANDBOX_UNAVAILABLE",
    "IsolatedWorker",
    "SandboxPolicy",
    "SandboxUnavailable",
    "probe_sandbox",
    "spawn_isolated_worker",
]

SANDBOX_UNAVAILABLE = "sandbox_unavailable"

CREATE_SUSPENDED = 0x0000_0004
CREATE_NO_WINDOW = 0x0800_0000


@dataclass(frozen=True)
class SandboxPolicy:
    """隔离策略声明。isolation_level: "job"（基线强隔离）| "appcontainer"（最终态）。"""

    memory_limit_mb: float | None = None
    job_memory_limit_mb: float | None = None
    active_process_limit: int | None = None
    per_process_user_time_sec: float | None = None
    cpu_rate_percent: int | None = None
    cpu_rate_weight: int | None = None
    cpu_hard_limit: bool = False
    isolation_level: str = "job"
    appcontainer_name: str | None = None
    appcontainer_display: str = "Shorekeeper Sandbox Worker"
    appcontainer_description: str = "V2.1 S1 plugin isolation container"


class IsolatedWorker:
    """隔离 worker 的控制面：wait / kill / stdout / Job 计量查询。"""

    def __init__(
        self,
        child: ChildProcess,
        job: JobObject,
        *,
        container_name: str | None = None,
        session=None,
    ):
        self._child = child
        self._job = job
        self._closed = False
        self.container_name = container_name
        self._session = session

    @property
    def pid(self) -> int:
        return self._child.pid

    @property
    def job(self) -> JobObject:
        return self._job

    def wait(self, timeout_s: float = 30.0) -> int | None:
        return self._child.wait(timeout_s)

    def kill(self, exit_code: int = 1) -> None:
        self._job.terminate(exit_code)
        self._child.terminate(exit_code)

    def exit_code(self) -> int | None:
        return self._child.exit_code()

    def stdout_text(self, timeout: float = 5.0) -> str:
        return self._child.stdout_text(timeout)

    def peak_process_memory_mb(self) -> float:
        return self._job.query_extended_limits().PeakProcessMemoryUsed / (1024 * 1024)

    def accounting(self) -> dict:
        acc = self._job.query_accounting()
        return {
            "total_user_time_sec": acc.TotalUserTime / 10_000_000,
            "total_kernel_time_sec": acc.TotalKernelTime / 10_000_000,
            "total_processes": acc.TotalProcesses,
            "active_processes": acc.ActiveProcesses,
            "terminated_processes": acc.TerminatedProcesses,
        }

    def process_ids(self) -> list[int]:
        return self._job.process_ids()

    def close(self) -> None:
        """监督器退出回收：显式终止 Job 全体 + 关句柄（KILL_ON_JOB_CLOSE 兜底）。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._job.terminate(1)
            self._child.wait(5.0)
        finally:
            self._child.terminate(1)
            self._child.close()
            self._job.close()
            if self._session is not None:
                self._session.close(delete_profile=True)
                self._session = None


@contextlib.contextmanager
def spawn_isolated_worker(
    argv: list[str], policy: SandboxPolicy | None = None
) -> Iterator[IsolatedWorker]:
    """在强隔离边界内拉起 worker；退出本 context 即回收 Job 内全部进程。

    失败语义：Job 层或 AppContainer 层不可用 → SandboxUnavailable（明确阻断），
    不产生任何以普通同权限身份运行的降级进程；挂 Job 失败的挂起进程会被显式
    终止并回收句柄，绝不带病放行。
    """
    pol = policy or SandboxPolicy()
    if not IS_WINDOWS:
        raise SandboxUnavailable(
            layer="job", step="platform", message="非 Windows 平台，无可用强隔离原语"
        )
    worker: IsolatedWorker | None = None
    session = None
    child: ChildProcess | None = None
    job: JobObject | None = None
    try:
        try:
            job = JobObject(
                JobLimits(
                    process_memory_mb=pol.memory_limit_mb,
                    job_memory_mb=pol.job_memory_limit_mb,
                    active_process_limit=pol.active_process_limit,
                    per_process_user_time_sec=pol.per_process_user_time_sec,
                    cpu_rate_percent=pol.cpu_rate_percent,
                    cpu_rate_weight=pol.cpu_rate_weight,
                    cpu_hard_limit=pol.cpu_hard_limit,
                ),
                kill_on_job_close=True,  # 合同：监督器退出回收（句柄级兜底，常开）
            )
            if pol.isolation_level == "appcontainer":
                name = pol.appcontainer_name or "ShorekeeperS1Worker"
                session = open_appcontainer_session(
                    name, pol.appcontainer_display, pol.appcontainer_description
                )
                p_handle, t_handle, pid = _launch_appcontainer(session, argv)
                child = ChildProcess(
                    process_handle=p_handle, thread_handle=t_handle, pid=pid, stdout_read_handle=0
                )
            elif pol.isolation_level == "job":
                child = spawn_suspended_wrapped(argv)
            else:
                raise SandboxUnavailable(
                    layer="job", step="policy", message=f"未知 isolation_level={pol.isolation_level!r}"
                )
            # CREATE_SUSPENDED → Assign → Resume：先入边界，后给执行权
            try:
                job.assign(child.process_handle)
            except JobObjectError as exc:
                child.terminate(1)  # 未入边界的挂起进程必须显式终止（不得放行）
                child.close()
                child = None
                raise SandboxUnavailable(
                    layer="job",
                    step="AssignProcessToJobObject",
                    message=str(exc),
                    diagnostics=["worker 进程已在挂起态被终止，未降级放行"],
                ) from exc
            child.resume()
            worker = IsolatedWorker(child, job, container_name=None, session=session)
            if session is not None:
                worker.container_name = pol.appcontainer_name
            session = None  # 所有权移交 worker
            job = None  # 所有权移交 worker
            yield worker
        except SandboxUnavailable:
            raise
        except JobObjectError as exc:
            # 原语层失败 = 隔离不可用，按合同阻断（绝不降级）
            raise SandboxUnavailable(layer="job", step="job_primitive", message=str(exc)) from exc
    finally:
        if worker is not None:
            worker.close()
        else:
            if child is not None:
                child.terminate(1)
                child.close()
            if job is not None:
                job.close()
            if session is not None:
                session.close(delete_profile=True)


def spawn_suspended_wrapped(argv: list[str]) -> ChildProcess:
    from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
        spawn_suspended,
    )

    return spawn_suspended(argv)


def _launch_appcontainer(session, argv: list[str]):
    from plugins.bot_unified_runtime.domains.core.supervisor.appcontainer_windows import (
        launch_appcontainer_process,
    )

    return launch_appcontainer_process(session, argv)


def probe_sandbox(*, include_appcontainer: bool = False, container_name: str | None = None) -> dict:
    """能力探测（不抛异常，返回结构化结论 + 诊断）。

    include_appcontainer=True 时做端到端容器拉起探测（建档+lowbox+cmd /c exit+清理，
    约 1-3 秒，且会在用户 Packages 下短暂建档再删除）。
    """
    report: dict = {
        "platform": sys.platform,
        "current_process_in_job": current_process_in_job() if IS_WINDOWS else False,
        "job_objects": {"supported": False, "nested": None, "cpu_rate_control": None, "detail": ""},
        "appcontainer": {"available": False, "step": "platform", "os_code": 0, "message": "未探测"},
        "acl": {"supported": IS_WINDOWS},
    }
    if not IS_WINDOWS:
        report["job_objects"]["detail"] = "non-windows"
        return report
    try:
        job = JobObject(JobLimits(active_process_limit=8), kill_on_job_close=False)
        try:
            lim = job.query_extended_limits()
            cpu_ok = True
            cpu_detail = ""
            try:
                ctrl = job.query_cpu_rate_control()
                cpu_detail = f"flags={ctrl.ControlFlags:#x} cpi_rate={ctrl.CpuRate}"
            except JobObjectError as exc:
                cpu_ok = False
                cpu_detail = str(exc)
            report["job_objects"] = {
                "supported": bool(lim.BasicLimitInformation.LimitFlags & 0x8),
                "nested": None,
                "cpu_rate_control": cpu_ok,
                "detail": f"limit_flags={lim.BasicLimitInformation.LimitFlags:#x}; cpu_rate[{cpu_detail}]",
            }
        finally:
            job.close()
    except JobObjectError as exc:
        report["job_objects"]["detail"] = f"Job 原语不可用: {exc}"
        return report
    nested_ok, nested_detail = probe_nested_job_support()
    report["job_objects"]["nested"] = nested_ok
    report["job_objects"]["detail"] += f"; nested={nested_detail}"
    if include_appcontainer:
        report["appcontainer"] = probe_appcontainer(
            container_name or "ShorekeeperV1S1Probe", "Shorekeeper S1 Probe", "V2.1 S1 sandbox feasibility probe"
        )
    return report
