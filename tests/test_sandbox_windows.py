"""S1 Windows 强隔离原语真机验证（V2.1 §3 验收矩阵 V21-ISO-001/002）。

全部离线本机实跑（spawns 真实子进程，无网络出站；127.0.0.1 监听仅作禁网对照）。
合同（backend-v2-implementation-guide.md §3/§88）：敏感文件拒读、跨 workspace 拒读、
禁公网/localhost、进程隔离、CPU/内存/子进程配额、句柄不泄漏、监督器退出不残留；
做不到的不许 skip——AppContainer 不可用分支必须断言 ``sandbox_unavailable`` 明确阻断。

覆盖映射：
- test_job_memory_limit_blocks_allocation      → 内存配额（分配被拒 + 峰值封顶）
- test_active_process_limit_blocks_grandchild  → 子进程数配额（超额创建失败）
- test_per_process_cpu_time_terminates         → CPU 配额（超时系统终止）
- test_cpu_rate_control_config_roundtrip       → CPU 速率控制（配置回读）
- test_kill_on_job_close_reaps_worker_and_grandchild → 监督器退出回收（含孙进程）
- test_handle_count_no_leak_across_cycles      → 句柄不泄漏
- test_nested_job_support                      → 嵌套 Job 行为探测
- test_acl_deny_write_blocks_and_restores      → Deny-Write ACL 施加/恢复（icacls 交叉验证）
- test_appcontainer_strong_isolation_or_explicit_block → 敏感文件拒读 + 跨 workspace 拒读
  + 禁网（可用分支）；sandbox_unavailable 明确阻断（不可用分支）
- test_explicit_block_invalid_container_name   → sandbox_unavailable 错误码路径（不降级）
"""

from __future__ import annotations

import ctypes
import socket
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.supervisor import (
    IS_WINDOWS,
    SANDBOX_UNAVAILABLE,
    SandboxPolicy,
    SandboxUnavailable,
    apply_deny_write,
    current_process_handle_count,
    current_user_sid_string,
    icacls_dump,
    probe_nested_job_support,
    probe_sandbox,
    process_alive,
    restore_dacl,
    snapshot_dacl,
    spawn_isolated_worker,
)

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="Windows 专属原语（非 Windows 平台由 sandbox_unavailable 合同覆盖）")

# venv 的 Scripts\python.exe 在 Windows 上是 venvlauncher 存根：CreateProcess 返回的
# pid 只是启动器，真实解释器是其子进程（真机实证：worker 报告的 getpid 与句柄 pid
# 不一致；ActiveProcessLimit 计数翻倍）。Job 配额语义必须按"单进程=单解释器"计算，
# 因此 worker 一律用 sys.base_prefix 下的真实解释器拉起（venv 内直跑 pytest 时
# base_prefix 指向基础安装）。
_BASE_PY = Path(sys.base_prefix) / "python.exe"
PY = str(_BASE_PY) if _BASE_PY.is_file() else sys.executable
CMD = r"C:\Windows\System32\cmd.exe"
CURL = r"C:\Windows\System32\curl.exe"
SECRET_MARKER = "S1-PROBE-SECRET-9f3a"

MEMORY_WORKER = """
import sys
try:
    b = bytearray(256 * 1024 * 1024)
except MemoryError:
    sys.stdout.write("MEMORY_LIMIT_HIT\\n")
    sys.stdout.flush()
    sys.exit(3)
sys.stdout.write("ALLOC_OK\\n")
sys.exit(0)
"""

ACTIVE_LIMIT_WORKER = """
import subprocess, sys, time
res = sys.argv[1]
lines = []
g1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
lines.append("G1_OK:%d" % g1.pid)
try:
    g2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    time.sleep(0.5)
    if g2.poll() is not None:
        lines.append("G2_DIED:rc=%s" % g2.returncode)
    else:
        lines.append("G2_ALIVE")
    g2.kill(); g2.wait()
except OSError as exc:
    lines.append("G2_BLOCKED:winerror=%s" % getattr(exc, "winerror", -1))
g1.kill(); g1.wait()
with open(res, "w", encoding="utf-8") as fh:
    fh.write("\\n".join(lines))
sys.exit(0)
"""

CPU_BUSY_WORKER = """
import sys, time
t = time.perf_counter()
while time.perf_counter() - t < 120:
    pass
sys.exit(0)
"""

REAP_WORKER = """
import os, subprocess, sys, time
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(40)"])
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    fh.write("%d %d" % (os.getpid(), g.pid))
time.sleep(30)
sys.exit(0)
"""


def _wait_for_file(path: Path, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            time.sleep(0.1)
            return True
        time.sleep(0.1)
    return False


def _wait_dead(pid: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.1)
    return not process_alive(pid)


# ---------------------------------------------------------------------------
# Job Objects：内存 / 进程数 / CPU 配额
# ---------------------------------------------------------------------------


def test_job_memory_limit_blocks_allocation(tmp_path: Path) -> None:
    """256MB 分配请求在 64MB Job 硬限内必须失败；峰值内存被封顶。"""
    policy = SandboxPolicy(memory_limit_mb=64)
    with spawn_isolated_worker([PY, "-c", MEMORY_WORKER], policy) as worker:
        rc = worker.wait(timeout_s=45)
        out = worker.stdout_text(5.0)
        peak_mb = worker.peak_process_memory_mb()
    assert rc == 3, f"worker 应以 MemoryError 退出(3)，实际 rc={rc} out={out!r}"
    assert "MEMORY_LIMIT_HIT" in out
    assert peak_mb <= 64 * 1.15 + 2, f"峰值内存 {peak_mb:.1f}MB 未被封顶在 64MB 配额附近"


def test_active_process_limit_blocks_grandchild(tmp_path: Path) -> None:
    """active_process_limit=2（worker+1 孙）：第二个孙进程创建必须失败。"""
    result_file = tmp_path / "active_limit_result.txt"
    policy = SandboxPolicy(active_process_limit=2)
    with spawn_isolated_worker([PY, "-c", ACTIVE_LIMIT_WORKER, str(result_file)], policy) as worker:
        rc = worker.wait(timeout_s=45)
    assert rc == 0, f"worker 异常退出 rc={rc}"
    assert result_file.exists(), "worker 未产出结果文件"
    content = result_file.read_text(encoding="utf-8")
    assert "G1_OK" in content, f"第一个孙进程应成功：{content!r}"
    assert "G2_ALIVE" not in content, f"第二个孙进程不应存活（超额未拦截）：{content!r}"
    assert ("G2_BLOCKED" in content) or ("G2_DIED" in content), f"第二个孙进程未按配额被拒/被终止：{content!r}"


def test_per_process_cpu_time_terminates_busy_worker(tmp_path: Path) -> None:
    """用户态时间配额 1s：120s 忙循环 worker 必须被系统终止。"""
    started = time.monotonic()
    policy = SandboxPolicy(per_process_user_time_sec=1.0)
    with spawn_isolated_worker([PY, "-c", CPU_BUSY_WORKER], policy) as worker:
        rc = worker.wait(timeout_s=60)
    elapsed = time.monotonic() - started
    assert rc is not None, "worker 60s 内未退出（CPU 时间配额未生效）"
    assert rc != 0 and rc != 259, f"worker 应被终止而非正常完成，rc={rc}"
    assert elapsed < 55, f"终止耗时 {elapsed:.1f}s，配额终止不生效"


def test_cpu_rate_control_config_roundtrip() -> None:
    """CPU 速率硬限 30%：Set 后 Query 必须回读同值（配置级验证）。"""
    from plugins.bot_unified_runtime.domains.core.supervisor import JobLimits, JobObject

    with JobObject(JobLimits(cpu_rate_percent=30, cpu_hard_limit=True), kill_on_job_close=False) as job:
        ctrl = job.query_cpu_rate_control()
        assert ctrl.ControlFlags & 0x1, f"ENABLE 旗标缺失 flags={ctrl.ControlFlags:#x}"
        assert ctrl.ControlFlags & 0x4, f"HARD_LIMIT 旗标缺失 flags={ctrl.ControlFlags:#x}"
        assert ctrl.CpuRate == 3000, f"CpuRate 应为 3000（30%×100），实际 {ctrl.CpuRate}"


# ---------------------------------------------------------------------------
# 监督器退出回收 / 句柄不泄漏 / 嵌套 Job
# ---------------------------------------------------------------------------


def test_kill_on_job_close_reaps_worker_and_grandchild(tmp_path: Path) -> None:
    """监督器（contextmanager）退出：worker 与其孙进程必须全部回收，零残留。"""
    result_file = tmp_path / "reap_result.txt"
    policy = SandboxPolicy()
    with spawn_isolated_worker([PY, "-c", REAP_WORKER, str(result_file)], policy) as worker:
        worker_pid = worker.pid
        assert _wait_for_file(result_file, 20), "worker 未在 20s 内产出 PID 清单"
        worker_pid_s, grandchild_pid_s = result_file.read_text(encoding="utf-8").split()
        grandchild_pid = int(grandchild_pid_s)
        assert int(worker_pid_s) == worker_pid
        assert process_alive(grandchild_pid), "孙进程应存活（等待回收阶段）"
        job_pids = worker.process_ids()
    # ---- 离开 context = 监督器退出 ----
    assert _wait_dead(worker_pid), f"worker(pid={worker_pid}) 未在监督器退出后被回收"
    assert _wait_dead(grandchild_pid), f"孙进程(pid={grandchild_pid}) 未随 Job 回收（泄漏）"
    assert not process_alive(worker_pid) and not process_alive(grandchild_pid)
    assert job_pids, "Job 进程清单查询异常"


def test_handle_count_no_leak_across_cycles() -> None:
    """多轮 spawn/回收后本进程句柄数零增长（Job/管道/线程句柄全数关闭）。"""
    trivial = [PY, "-c", "pass"]
    policy = SandboxPolicy()
    # 预热一轮（排除首次惰性加载的常驻句柄）
    with spawn_isolated_worker(trivial, policy) as w:
        w.wait(timeout_s=30)
    before = current_process_handle_count()
    for _ in range(3):
        with spawn_isolated_worker(trivial, policy) as w:
            assert w.wait(timeout_s=30) == 0
    after = current_process_handle_count()
    assert after == before, f"句柄泄漏：{before} -> {after}（3 轮 spawn/回收后增长 {after - before}）"


def test_nested_job_support() -> None:
    """Win8+ 嵌套 Job：同一进程可同时挂在两个 Job 上（挂载/回收零残留）。"""
    supported, detail = probe_nested_job_support()
    assert supported, f"本机应支持嵌套 Job（Win11 26200）：{detail}"


# ---------------------------------------------------------------------------
# ACL：Deny-Write 施加 / 恢复（icacls 交叉验证）
# ---------------------------------------------------------------------------


def test_acl_deny_write_blocks_and_restores(tmp_path: Path) -> None:
    """Deny-Write（具体权利 DE,WD,AD,WEA,WA）后：新建/改写全拒；恢复后全部解封。"""
    from plugins.bot_unified_runtime.domains.core.supervisor.acl_windows import (
        release_dacl_snapshot,
    )

    target = tmp_path / "deny_dir"
    target.mkdir()
    victim = target / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    user_sid = current_user_sid_string()
    snap = snapshot_dacl(str(target))
    denied = False
    try:
        apply_deny_write(str(target), user_sid)
        denied = True
        dump = icacls_dump(str(target))
        assert "DENY" in dump.upper(), f"icacls 未显示 DENY ACE：{dump!r}"
        # 新建被拒
        with pytest.raises(PermissionError):
            (target / "new.txt").write_text("x", encoding="utf-8")
        # 改写被拒
        with pytest.raises(PermissionError):
            victim.write_text("tampered", encoding="utf-8")
        # 对照：目录外写入不受影响
        outside = tmp_path / "outside.txt"
        outside.write_text("ok", encoding="utf-8")
        assert outside.exists()
    finally:
        restore_dacl(str(target), snap)
        release_dacl_snapshot(snap)
    assert denied, "Deny-Write 未实际施加（测试自证失败）"
    # 恢复后解封
    (target / "new2.txt").write_text("ok", encoding="utf-8")
    assert (target / "new2.txt").read_text(encoding="utf-8") == "ok"
    victim.unlink()
    assert not victim.exists()
    # 删除防护边界（真机实证，2026-09-17）：%TEMP% 继承链上的 OWNER RIGHTS(F) 使
    # owner 经父目录删除旁路绕开子文件/父目录的 DENY(DE)——DACL deny-delete 对
    # owner 不可依赖（D1-D3/E1 对照实验见 v21-s1-sandbox-log.md）。V2.1 §3 的删除
    # 防护由 Job 层（KILL_ON_JOB_CLOSE/TerminateJobObject）兜底，不在 ACL 尽力而为层。
    # 因此本测试只断言契约要求的"拒写或只读"（新建/改写全拒）+ ACL 可逆。


# ---------------------------------------------------------------------------
# AppContainer：强隔离实测 或 sandbox_unavailable 明确阻断（双分支均断言）
# ---------------------------------------------------------------------------


def test_explicit_block_invalid_container_name(tmp_path: Path) -> None:
    """隔离层请求失败必须显式 sandbox_unavailable，绝不产出同权限降级进程。"""
    policy = SandboxPolicy(
        isolation_level="appcontainer",
        appcontainer_name="a",  # 非法容器名（<3 字符）
    )
    with pytest.raises(SandboxUnavailable) as excinfo, spawn_isolated_worker([PY, "-c", "pass"], policy):
        pass  # 不应到达
    exc = excinfo.value
    assert exc.error_code == SANDBOX_UNAVAILABLE
    assert exc.layer == "appcontainer"
    assert exc.step  # 有步骤级诊断


def test_appcontainer_strong_isolation_or_explicit_block(tmp_path: Path) -> None:
    """可用分支：实测敏感文件拒读 + 跨 workspace 拒读 + 禁网；
    不可用分支：断言 sandbox_unavailable 明确阻断（含诊断），并如实记录 blocked。"""
    container_name = f"ShorekeeperA7{uuid.uuid4().hex[:10]}"
    info = probe_sandbox(include_appcontainer=True, container_name=container_name)
    ac = info["appcontainer"]
    assert isinstance(ac, dict) and "available" in ac
    if not ac["available"]:
        # ---- 不可用分支：阻断路径必须正确 ----
        policy = SandboxPolicy(
            isolation_level="appcontainer", appcontainer_name=f"ShorekeeperA7{uuid.uuid4().hex[:10]}"
        )
        with pytest.raises(SandboxUnavailable) as excinfo, spawn_isolated_worker([PY, "-c", "pass"], policy):
            pass
        exc = excinfo.value
        assert exc.error_code == SANDBOX_UNAVAILABLE
        assert exc.diagnostics or exc.message, "阻断必须携带诊断信息"
        return  # blocked 证据由 probe_sandbox 返回值 + 断言消息记录

    # ---- 可用分支：真实强隔离行为实测（AC 授权管道 stdout + 退出码探针）----
    # 机器现实（2026-09-17 真机实证）：
    # a) C:\Users 与 %LOCALAPPDATA% 链上没有任何 package SID / ALL APPLICATION
    #    PACKAGES ACE（仅 C:\Windows 树带只读），非提权进程无法布置可写工作区，
    #    CreateAppContainerProfile 成功也不落地 Packages\<name>AC 文件夹；
    # b) 容器的控制台/NUL 写均被强制策略吞掉，stdout 只能经 AC 授权管道带出
    #    （管道 SD = user+package 双 GRANT + Low 完整性标签，两端须可继承）。
    # 行为断言 = 退出码 + 管道内容（拒绝文案）+ 跨 workspace 物证；公共可读文件
    # 作为活性对照，防"全拒=假通过"。探针路径禁用内层引号（嵌套引号会坏 cmd 解析）。
    import threading

    from plugins.bot_unified_runtime.domains.core.supervisor import (
        appcontainer_windows as acw,
    )
    from plugins.bot_unified_runtime.domains.core.supervisor.job_objects import (
        ChildProcess,
        JobLimits,
        JobObject,
    )

    k32 = ctypes.WinDLL("kernel32")

    def _ac_probe(inner: str) -> tuple[int, str]:
        """拉起一次 AC 容器执行 inner（路径不得含空格/引号），返回 (exit_code, stdout)。"""
        name = f"ShorekeeperA7{uuid.uuid4().hex[:10]}"
        diags2: list[str] = []
        ac_sid = acw.derive_app_container_sid(name, diags2)
        ac_sid_str = acw._sid_to_string(ac_sid)
        acw._kernel32().LocalFree(ctypes.c_void_p(ac_sid))
        read_end, write_end = acw.create_ac_pipe(ac_sid_str)
        session = acw.open_appcontainer_session(name, "S1 verify", "V2.1 S1 AC verify")
        job = JobObject(JobLimits(), kill_on_job_close=True)
        p_handle, t_handle, pid = acw.launch_appcontainer_process(
            session, [CMD, "/d", "/c", inner], std_handles=(read_end, write_end, write_end)
        )
        child = ChildProcess(process_handle=p_handle, thread_handle=t_handle, pid=pid, stdout_read_handle=0)
        # 排水线程必须与 wait 并发（与 job_objects.spawn_suspended 的 start_stdout_drain
        # 同一模式）：活性探针 `type notepad.exe` 输出 360,448 字节，远超匿名管道默认
        # 缓冲（~4KB）——先 wait 后读会让子进程永久阻塞在 WriteFile（管道背压死锁，
        # 2026-09-17 真机实证：AC worker 45s 未退出的根因），与隔离能力无关。
        drained = bytearray()

        def _drain() -> None:
            chunk = ctypes.create_string_buffer(65536)
            n = wintypes.DWORD()
            while k32.ReadFile(ctypes.c_void_p(read_end), chunk, 65536, ctypes.byref(n), None) and n.value:
                drained.extend(chunk.raw[: n.value])

        drain_thread = threading.Thread(target=_drain, daemon=True, name="s1-ac-probe-stdout")
        drain_thread.start()
        try:
            job.assign(child.process_handle)
            child.resume()
            rc = child.wait(45.0)
            assert rc is not None, "AC worker 45s 未退出"
        finally:
            child.terminate(1)
            child.close()
            job.close()
            session.close(delete_profile=True)
            # 子进程已退出（写端无持有者）；父侧关写端 → 排水线程读到 EOF 收尾
            k32.CloseHandle(ctypes.c_void_p(write_end))
            drain_thread.join(10.0)
            k32.CloseHandle(ctypes.c_void_p(read_end))
        return int(rc or 0), bytes(drained).decode("utf-8", errors="replace")

    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET_MARKER, encoding="utf-8")
    other_ws = tmp_path / "other_workspace"
    other_ws.mkdir()

    # 禁网对照：本机监听端口回 HTTP 200，无沙盒 curl 必须 rc=0（实验有效性前提）
    accepted = threading.Event()

    def _serve_once(sock: socket.socket) -> None:
        sock.settimeout(10)
        conn, _addr = sock.accept()
        accepted.set()
        try:
            conn.recv(4096)
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        finally:
            conn.close()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        server = threading.Thread(target=_serve_once, args=(listener,), daemon=True)
        server.start()
        control = subprocess.run(
            [CURL, "-s", "-m", "3", f"http://127.0.0.1:{port}/"],
            capture_output=True, timeout=15, check=False,
        )
        assert control.returncode == 0, (
            f"对照失败：无沙盒 curl 连不上本机监听端口 rc={control.returncode}，禁网实验无效"
        )

        # 公共可读文件活性对照：容器必须能读到带 ALL APPLICATION PACKAGES(RX) 的系统文件
        rc, out = _ac_probe(r"type C:\Windows\System32\notepad.exe & exit 10")
        assert rc == 10 and len(out) > 0, f"容器活性对照失败 rc={rc} out={out!r}"
        # 敏感文件拒读：读成功会把 SECRET_MARKER 带进管道（即泄漏），必须只有拒绝文案
        rc, out = _ac_probe(f"type {secret} & exit 30")
        assert rc == 30, f"secret 探针 rc={rc}"
        assert SECRET_MARKER not in out, f"敏感文件内容泄漏进容器：{out!r}"
        assert len(out) > 0, "容器对 secret 应产生拒绝文案（管道为空=探针异常）"
        # 跨 workspace 拒写：写成功即越界；物证=other_workspace 不得出现新文件
        rc, _out = _ac_probe(f"echo x > {other_ws / 'should_not_exist.txt'} & exit 50")
        assert rc == 50, f"跨 workspace 探针 rc={rc}"
        assert not (other_ws / "should_not_exist.txt").exists(), "跨 workspace 写入未被拒绝"
        # 禁网（localhost）：无 capability 容器连本机监听端口必须失败（错误文案入管道）
        # 布线修正（2026-09-17）：控制组对照连接已消费第一次 accept 并置位 accepted——
        # 必须清零并重开一支服务线程守 AC 阶段，否则断言永假（置位残留）且即便真连上
        # 也探测不到（accept 无人收）。真机实证：零 capability 容器 curl loopback 被
        # WFP 拒绝（12s 零 accept，"拒绝访问"入管道），隔离机制本身有效。
        accepted.clear()
        server2 = threading.Thread(target=_serve_once, args=(listener,), daemon=True)
        server2.start()
        rc, out = _ac_probe(f"{CURL} -s -m 5 http://127.0.0.1:{port}/ & exit 25")
        assert rc == 25, f"localhost 访问未被拒绝：rc={rc} out={out!r}"
        assert not accepted.is_set(), "禁网失败：容器 curl 连上了监听端口"
    finally:
        listener.close()


# ---------------------------------------------------------------------------
# 探测面形状
# ---------------------------------------------------------------------------


def test_probe_sandbox_shape() -> None:
    """probe_sandbox 结构与 Job 能力结论（AppContainer 不在此处探测，成本高）。"""
    info = probe_sandbox()
    assert info["platform"] == "win32"
    assert info["job_objects"]["supported"] is True
    assert info["job_objects"]["nested"] is True
    assert isinstance(info["appcontainer"], dict)
    assert isinstance(info["current_process_in_job"], bool)
    assert info["acl"]["supported"] is True
