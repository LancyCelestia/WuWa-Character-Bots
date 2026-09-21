"""W4 席（S1 Windows 强隔离 Supervisor）真机验收测试。

对应后端 V2.1 验收矩阵 V21-ISO-001（OS 隔离）/ V21-ISO-002（Job 限制与退出回收），
实现规范 §3（Windows 隔离与 IPC）、§4（资源初值）：

① Job 内存硬限：子进程分配超限 → 非零退出且拿不到分配成功标记；
② KILL_ON_JOB_CLOSE：父进程关 Job 句柄 → 子进程被回收（轮询确认）；
③ ActiveProcessLimit=1：子进程再孙进程被拒；
④ AppContainer 成功路径：无 capability 子进程连 127.0.0.1 监听 socket 被拒；
⑤ AppContainer 不可用路径：显式 SandboxUnavailableError（sandbox_unavailable），绝不降级普通 subprocess；
⑥ IPC 帧协议：长度前缀 JSON 往返；超 1MiB / 深度>32 / pickle / 信封违规一律 ProtocolViolation；
⑦ 敏感文件拒读：ACL 未授权 AppContainer 的文件读取被拒；
⑧ 环境白名单 + 工作目录隔离：子进程只拿到白名单键，cwd=私有工作区。

沙盒用例全部真实 spawn 子进程（venv 解释器 / System32 curl.exe / cmd.exe），
全离线、不写源码树 data/。非 Windows 平台环境性跳过（沙盒为 Windows 专属能力，
本机为 win32 时必须全绿，不允许以 skip 宣称强隔离完成）。
"""

from __future__ import annotations

import json
import os
import pickle
import socket
import struct
import sys
import textwrap
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.supervisor import ipc
from plugins.bot_unified_runtime.domains.core.supervisor.ipc import MAX_NESTING_DEPTH
from plugins.bot_unified_runtime.domains.core.supervisor.windows_sandbox import (
    DEFAULT_ENV_WHITELIST,
    SANDBOX_UNAVAILABLE,
    SandboxLaunchSpec,
    SandboxUnavailableError,
    WindowsSandbox,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows 强隔离真机验收（沙盒为 Windows 专属能力）"
)

# §4 资源初值（普通插件 256MiB）；内存硬限用例取 96MiB 留出解释器启动余量
_MEM_LIMIT = 96 * 1024 * 1024

_SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def _python_exe() -> str:
    """隔离用例的子进程解释器。

    venv 的 python.exe 实为 venvlauncher（两级进程：先 spawn 真实解释器再执行），
    Job ActiveProcessLimit=1 会把第二段 spawn 拒掉（真机 stderr 实证）。强隔离
    要求单进程语义，故直用 base 解释器——与规范 §3「只读固定 Python」一致。
    """
    return str(getattr(sys, "_base_executable", None) or sys.executable)


def _make_spec(
    tmp_path: Path,
    *,
    executable: str = _python_exe(),
    argv: tuple[str, ...] = (),
    memory_limit_bytes: int = _MEM_LIMIT,
    active_process_limit: int = 1,
    use_appcontainer: bool = False,
    env_whitelist=None,
) -> SandboxLaunchSpec:
    """构造带唯一隔离键的启动参数（isolation_scope 逐用例唯一，不复用带状态进程）。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return SandboxLaunchSpec(
        plugin_id="plug.demo",
        plugin_release="1.0.0",
        isolation_scope=f"test-{next(temp_counter())}",
        executable=executable,
        argv=argv,
        workspace_dir=str(workspace),
        env_whitelist=env_whitelist,
        memory_limit_bytes=memory_limit_bytes,
        active_process_limit=active_process_limit,
        use_appcontainer=use_appcontainer,
    )


def temp_counter():
    """测试内取唯一 scope 序号。"""
    n = 0
    while True:
        n += 1
        yield f"s{n}"


# ---------------------------------------------------------------------------
# ① Job 内存硬限（V21-ISO-002）
# ---------------------------------------------------------------------------

def test_job_memory_hard_limit_kills_overspending_child(tmp_path: Path) -> None:
    child = "x = bytearray(256 * 1024 * 1024)\nprint('ALLOC_OK')\n"
    spec = _make_spec(tmp_path, argv=("-c", child))
    with WindowsSandbox(spec) as sandbox:
        assert sandbox.isolation_key == ("plug.demo", "1.0.0", sandbox.isolation_key[2])
        proc = sandbox.launch()
        out, _ = proc.communicate(timeout=60)
    assert proc.returncode != 0, "子进程超限分配必须非零退出"
    assert b"ALLOC_OK" not in out, "子进程不得成功完成超限分配"


# ---------------------------------------------------------------------------
# ② KILL_ON_JOB_CLOSE：父进程关句柄后子进程消失（V21-ISO-002 监督器退出回收）
# ---------------------------------------------------------------------------

def test_kill_on_job_close_reaps_child_after_parent_close(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, argv=("-c", "import time\ntime.sleep(60)\n"))
    sandbox = WindowsSandbox(spec)
    try:
        proc = sandbox.launch()
        assert proc.poll() is None, "子进程应处于运行中"
        sandbox.close()  # CloseHandle → JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 兜底回收
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.1)
        assert proc.poll() is not None, "父进程关句柄后子进程必须被回收"
    finally:
        sandbox.close()


# ---------------------------------------------------------------------------
# ③ ActiveProcessLimit=1：子进程再孙进程被拒（嵌套子进程配额）
# ---------------------------------------------------------------------------

def test_active_process_limit_blocks_grandchild(tmp_path: Path) -> None:
    child = textwrap.dedent(
        """
        import subprocess, sys
        try:
            p = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            p.kill()
            p.wait()
            print("GRANDCHILD_SPAWNED")
        except OSError:
            print("GRANDCHILD_BLOCKED")
        """
    )
    spec = _make_spec(tmp_path, argv=("-c", child), active_process_limit=1)
    with WindowsSandbox(spec) as sandbox:
        proc = sandbox.launch()
        out, _ = proc.communicate(timeout=60)
    assert b"GRANDCHILD_BLOCKED" in out, "Job ActiveProcessLimit=1 必须拒绝孙进程"
    assert b"GRANDCHILD_SPAWNED" not in out


# ---------------------------------------------------------------------------
# ④ AppContainer 成功路径：无 capability 子进程连 127.0.0.1 被拒（V21-ISO-001）
# ---------------------------------------------------------------------------

def test_appcontainer_loopback_connect_denied(tmp_path: Path) -> None:
    curl = _SYSTEM32 / "curl.exe"
    assert curl.is_file(), "前置条件缺失：System32 curl.exe 不存在，无法实机验证 AC 禁网"

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        spec = _make_spec(
            tmp_path,
            executable=str(curl),
            argv=(
                "--noproxy",
                "*",
                "-s",
                "-o",
                "NUL",
                "--connect-timeout",
                "3",
                f"http://127.0.0.1:{port}/",
            ),
            use_appcontainer=True,
        )
        with WindowsSandbox(spec) as sandbox:
            proc = sandbox.launch()
            rc = proc.wait(timeout=60)
        assert rc != 0, "AppContainer 无 capability 子进程连 loopback 必须失败"
        listener.settimeout(0.5)
        with pytest.raises((socket.timeout, TimeoutError)):
            listener.accept()  # 监听端不得收到任何连接
    finally:
        listener.close()


# ---------------------------------------------------------------------------
# ⑤ AppContainer 不可用路径：显式 sandbox_unavailable，绝不降级普通 subprocess
# ---------------------------------------------------------------------------

def test_appcontainer_unavailable_explicit_error_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import plugins.bot_unified_runtime.domains.core.supervisor.windows_sandbox as ws

    def _fail(*_args: object, **_kwargs: object) -> int:
        return 0x80070005  # E_ACCESSDENIED（模拟 CreateAppContainerProfile 失败）

    monkeypatch.setattr(ws, "_userenv_create_app_container_profile_raw", _fail)
    spec = _make_spec(tmp_path, argv=("-c", "pass"), use_appcontainer=True)
    with pytest.raises(SandboxUnavailableError) as excinfo:
        WindowsSandbox(spec)
    assert excinfo.value.reason_code == SANDBOX_UNAVAILABLE
    assert "create_appcontainer_profile" in str(excinfo.value)
    assert "win32_error=0x80070005" in str(excinfo.value)
    # 不降级：不存在任何绕过沙盒的启动旁路
    assert not hasattr(WindowsSandbox, "launch_unsandboxed")


# ---------------------------------------------------------------------------
# ⑥ IPC：长度前缀 JSON 帧协议（1MiB / 深度 32 / 禁 pickle）
# （纯 Python 协议层，不依赖 Windows，无 skipif）
# ---------------------------------------------------------------------------

def _envelope(**overrides: object) -> dict:
    base: dict = {
        "protocol_version": ipc.PROTOCOL_VERSION,
        "request_id": "req-0001",
        "trace_id": "trace-0001",
        "plugin_id": "plug.demo",
        "plugin_release": "1.0.0",
        "operation": "parse",
        "invocation_id": "inv-0001",
        "deadline_remaining_ms": 1500,
        "input": {"text": "hello", "rows": [1, 2, {"n": None}]},
        "asset_refs": ["asset-1"],
    }
    base.update(overrides)
    return base


def _send_raw(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def _nest(depth: int) -> dict:
    value: dict = {"leaf": 1}
    for _ in range(depth - 1):
        value = {"n": value}
    return value


def test_ipc_frame_roundtrip_socketpair() -> None:
    parent, child = socket.socketpair()
    try:
        env = _envelope()
        ipc.send_frame(parent, env)
        got = ipc.recv_frame(child)
        assert got == env
    finally:
        parent.close()
        child.close()


def test_ipc_rejects_oversize_frame() -> None:
    big_input = {"blob": "x" * (ipc.MAX_FRAME_BYTES + 1)}
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(_envelope(input=big_input))

    # 恶意长度前缀：接收端必须先拒前缀（不读帧体），防资源耗尽
    attacker, receiver = socket.socketpair()
    try:
        attacker.sendall(struct.pack("<I", ipc.MAX_FRAME_BYTES + 1))
        attacker.sendall(b"p" * 4096)
        with pytest.raises(ipc.ProtocolViolation):
            ipc.recv_frame(receiver)
    finally:
        attacker.close()
        receiver.close()


def test_ipc_rejects_deep_nesting_and_accepts_boundary() -> None:
    # 信封自身占 1 层：输入 _nest(32) → 整帧 33 层 → 拒绝
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(_envelope(input=_nest(MAX_NESTING_DEPTH)))
    # 恰好 32 层必须放行并保持往返一致（经真实 socket 帧，长度前缀由协议层自理）
    parent, child = socket.socketpair()
    try:
        boundary = _envelope(input=_nest(MAX_NESTING_DEPTH - 1))
        ipc.send_frame(parent, boundary)
        assert ipc.recv_frame(child) == boundary
    finally:
        parent.close()
        child.close()

    # 帧体合法 JSON 但深度超限 → 解码侧拒绝
    deep_payload = json.dumps(_envelope(input=_nest(MAX_NESTING_DEPTH + 1))).encode()
    assert len(deep_payload) <= ipc.MAX_FRAME_BYTES
    with pytest.raises(ipc.ProtocolViolation):
        ipc.decode_frame(deep_payload)


def test_ipc_rejects_pickle_and_non_json() -> None:
    with pytest.raises(ipc.ProtocolViolation):
        ipc.decode_frame(pickle.dumps({"a": 1}))
    with pytest.raises(ipc.ProtocolViolation):
        ipc.decode_frame(b"\x80\x04\x95not-really-pickle")


def test_ipc_rejects_truncated_frame_and_bad_envelope() -> None:
    attacker, receiver = socket.socketpair()
    try:
        attacker.sendall(struct.pack("<I", 100) + b"short")
        attacker.close()
        with pytest.raises(ipc.ProtocolViolation):
            ipc.recv_frame(receiver)
    finally:
        receiver.close()

    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(_envelope(protocol_version=ipc.PROTOCOL_VERSION + 1))
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame({"protocol_version": ipc.PROTOCOL_VERSION})
    bad = _envelope()
    bad.pop("request_id")
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(bad)
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(_envelope(deadline_remaining_ms=-5))
    with pytest.raises(ipc.ProtocolViolation):
        ipc.encode_frame(_envelope(asset_refs=[123]))


# ---------------------------------------------------------------------------
# ⑦ 敏感文件拒读：ACL 未授权 AppContainer 的文件读取被拒（V21-ISO-001）
# ---------------------------------------------------------------------------

def test_appcontainer_sensitive_file_read_denied(tmp_path: Path) -> None:
    cmd_exe = _SYSTEM32 / "cmd.exe"
    assert cmd_exe.is_file(), "前置条件缺失：System32 cmd.exe 不存在"

    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET-W4", encoding="utf-8")  # 位于工作区之外，无 AC SID ACE
    out = tmp_path / "workspace" / "read_result.txt"

    # cmd 子进程：读得到写 READ_OK，读不到写 READ_DENIED（工作区可写、secret 不可读）
    command = (
        f'type "{secret}" > NUL 2>&1 && (echo READ_OK> "{out}") '
        f'|| (echo READ_DENIED> "{out}")'
    )
    spec = _make_spec(
        tmp_path,
        executable=str(cmd_exe),
        argv=("/d", "/c", command),
        use_appcontainer=True,
    )
    with WindowsSandbox(spec) as sandbox:
        proc = sandbox.launch()
        rc = proc.wait(timeout=60)
    assert rc == 0, "cmd 子进程本身应正常退出（被拒的是文件访问，不是进程启动）"
    assert out.is_file(), "cmd 子进程必须能把判定写进已授权工作区"
    assert "READ_DENIED" in out.read_text(encoding="utf-8", errors="replace"), (
        "AppContainer 子进程读取 ACL 未授权文件必须被拒"
    )


# ---------------------------------------------------------------------------
# ⑧ 环境白名单 + 工作目录隔离（生成物隔离）
# ---------------------------------------------------------------------------

def test_env_whitelist_and_workspace_dir_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("W4_SECRET_CANARY", "leak-me")
    monkeypatch.setenv("W4_ALLOW_CANARY", "pass-me")
    child = (
        "import json, os\n"
        "print(json.dumps({'cwd': os.getcwd(), 'env': sorted(os.environ)}))\n"
    )
    whitelist = frozenset(DEFAULT_ENV_WHITELIST) | {"W4_ALLOW_CANARY"}
    spec = _make_spec(tmp_path, argv=("-c", child), env_whitelist=whitelist)
    workspace = Path(spec.workspace_dir)
    with WindowsSandbox(spec) as sandbox:
        proc = sandbox.launch()
        out, _ = proc.communicate(timeout=60)
    report = json.loads(out.decode("utf-8").strip().splitlines()[-1])

    assert Path(report["cwd"]).resolve() == workspace.resolve(), (
        "子进程工作目录必须指向私有临时工作区"
    )
    # Windows 环境键大小写不敏感（子进程 os.environ 统一大写回显），按大写比较
    env_keys = {key.upper() for key in report["env"]}
    whitelist_upper = {key.upper() for key in whitelist}
    assert "W4_ALLOW_CANARY" in env_keys, "白名单键必须注入"
    assert "W4_SECRET_CANARY" not in env_keys, "非白名单键必须被剥离"
    # TEMP/TMP 为沙盒按设计钉进私有工作区的键；其余必须严格等于白名单
    expected = whitelist_upper | {"TEMP", "TMP"}
    # 宿主注入豁免：本机常驻的 LSBOX_*（审计/共享内存）由外部沙箱工具在进程创建
    # 时强制注入，不经 env 参数——以仅含 SystemRoot/PATH 的 env 起子进程，
    # os.environ 仍含这 3 键（2026-09-18 实测复现）。产品侧白名单过滤本身正确
    # （上方 W4_SECRET_CANARY 已被剥离），故仅豁免该前缀，其余泄漏照旧报红。
    host_injected = {key for key in env_keys if key.startswith("LSBOX_")}
    unexpected = env_keys - expected - host_injected
    assert not unexpected, f"发现白名单外泄漏键：{sorted(unexpected)}"
