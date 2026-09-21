# V2.1 S1 沙箱席日志（Windows AppContainer + Job Objects 强隔离终验）

> 席位：SBX（S1 沙箱终验收口），2026-09-17。
> 合同：`backend-v2-implementation-guide.md` §3 / `backend-v2-acceptance-matrix.md` **V21-ISO-001/002**——
> 所有业务插件（含内置）最终 Windows AppContainer＋Job Objects 强隔离；普通同权限 subprocess
> 不是合格替代；隔离不可用必须显式阻断（`sandbox_unavailable`），**绝不静默降级**。
> 上一席（A7/S1 原语验证层）交付了 7 文件地基与全部测试但**无完成报告**（文件全部未跟踪入库，
> `docs/design/v21-s1-sandbox-log.md` 缺失）；本日志由终验席补写，基于本席实跑与代码内嵌真机注释。

## 一、现状盘点（接手时基线）

双路径结构（v21r2 重组后）：

- `plugins/bot_unified_runtime/supervisor/*` —— 7 个 compat shim（PEP 562 实时 re-export），
  全部指向 canonical 包，monkeypatch 双向同源。
- `plugins/bot_unified_runtime/domains/core/supervisor/*` —— 真身（共 3154 行）：

| 文件 | 行数 | 内容 |
|---|---|---|
| `job_objects.py` | 632 | Job 原语：内存/Job 内存、ActiveProcessLimit、单进程用户态时间、CPU 速率控制（enable/hard/weight）、KILL_ON_JOB_CLOSE；CREATE_SUSPENDED→Assign→Resume 零逃逸窗口；`ChildProcess`（wait/terminate/`start_stdout_drain` 排水线程）、`spawn_suspended`（NUL stdin+匿名管道 stdout/stderr）、嵌套 Job 探测、句柄计数、PID 存活 |
| `appcontainer_windows.py` | 525 | 纯 Python AC 路线（零第三方依赖）：`CreateAppContainerProfile`→`DeriveAppContainerSidFromAppContainerName`→`NtCreateLowBoxToken`（ntdll 直调，**空 capability=无网络无资源**）→`CreateEnvironmentBlock`→`CreateProcessAsUserW(CREATE_SUSPENDED)`；AC 授权管道（user+package 双 GRANT FA + `S:(ML;;NW;;;LW)` 低完整性标签，两端可继承）；任一步失败抛 `SandboxUnavailable`（error_code=`sandbox_unavailable`，layer/step/os_code/diagnostics 步骤级审计）；`probe_appcontainer` 端到端探测 |
| `sandbox_windows.py` | 292 | 编排层：`SandboxPolicy`（isolation_level=job/appcontainer）+ `spawn_isolated_worker` contextmanager（监督器退出=TerminateJobObject+KILL_ON_JOB_CLOSE 双保险回收，AC 会话含建档一并删除）+ `probe_sandbox` 结构化能力报告 |
| `acl_windows.py` | 396 | Deny-Write ACL（具体权利位 DE,WD,AD,WEA,WA，禁泛型位）施加/快照恢复 + `create_appcontainer_workspace`（创建即授权，Low 标签）；icacls 交叉验证 |
| `windows_sandbox.py` | 971 | W4 席插件面 API：`WindowsSandbox`/`SandboxLaunchSpec`/`SandboxProcess`（隔离键 `(plugin_id, plugin_release, isolation_scope)`、PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES 属性表路线、工作区 DACL 授权、env 白名单） |
| `ipc.py` | 212 | 长度前缀 JSON 帧协议（PROTOCOL_VERSION=1，1MB 帧上限，深度 32，防越界） |
| `__init__.py` | 126 | 出口聚合（40 符号） |

测试：`tests/test_sandbox_windows.py`（442 行，11 用例，Windows 全离线真机实跑——spawn 真实子进程、
127.0.0.1 监听仅作禁网对照，无出站网络）。

## 二、本席收口前唯一红点与真因

红点：`test_appcontainer_strong_isolation_or_explicit_block`（首跑 1 failed in 46.83s）。

### 真因 1：AC 探针管道背压死锁（主红点）

`_ac_probe` 手工布线 AC 授权管道（`std_handles=(read_end, write_end, write_end)`）后
**先 `child.wait(45)` 后读管道**。活性探针 `type C:\Windows\System32\notepad.exe` 向 stdout
写 **360,448 字节**（本机实测 notepad.exe 大小），远超匿名管道默认缓冲（~4KB）——子进程永久
阻塞在 `WriteFile`，父进程等退出 → 45s 超时 `rc=None`。

实证（最小复现脚本，启动排水线程后同探针）：

```
probe available = True | step = complete
liveness probe: rc = 10 | out_bytes = 360448   ← 与 notepad.exe 字节数完全一致
```

定性：**测试布线缺陷，非隔离能力缺陷**。生产代码无此问题——Job 层 `spawn_suspended`
自带 `start_stdout_drain()` 排水线程；生产 AC 启动路径不传 std_handles。

### 真因 2：禁网探测布线失效（排水修复后红点前移至此）

首修后红点移到 `assert not accepted.is_set()`：控制组对照（无沙盒 curl 连通性前提）已把
`accepted` 事件置位且服务线程只 accept 一次（早被控制组消费）——**断言永假，且即便容器真连上
也探测不到**。先取证再修：独立脚本给 AC 阶段全新监听+独立 accept 线程，实测零 capability
容器 curl loopback **确实被拒**（12s 零 accept、管道内为"拒绝访问"，cmd rc=25）——WFP
loopback 隔离机制本身有效，坏的只是探测布线。

## 三、裁决

按任务书「strong isolation OR explicit block」二选一收口，**取路径①：强隔离可用分支保留**。

依据：AppContainer 纯 Python 路线在本机**可离线真实验证**——`probe_sandbox(include_appcontainer=True)`
返回 `available=True, step=complete`（建档→lowbox→容器内 `cmd /c exit 0` 真实拉起），四支行为
探针（活性对照/敏感拒读/跨 workspace 拒写/loopback 禁网）全部真机可跑。无需降级到显式阻断语义。

**测试断言零放宽**：两处修改均为测试 plumbing 修正（补并发排水、补 accept 布线），不涉及任何
断言语义变化；显式阻断分支（`sandbox_unavailable`，含非法容器名用例
`test_explicit_block_invalid_container_name`）原样保留且绿。测试本身采用 probe 条件分支设计：
probe 报不可用则走阻断分支断言 `SandboxUnavailable`，本机走可用分支。

## 四、改动清单（本席域内）

1. `tests/test_sandbox_windows.py` `_ac_probe`：
   - launch 后 resume 前启动 daemon 排水线程（与 `job_objects.spawn_suspended` 的
     `start_stdout_drain` 同一模式），wait 与读管道并发；pipe 两端关闭与线程收尾移入
     finally（失败路径不再泄漏句柄）。
   - 禁网段：`accepted.clear()` + 重开一支服务线程守 AC 阶段，附真机实证注释。
2. `plugins/bot_unified_runtime/domains/core/supervisor/appcontainer_windows.py`
   `launch_appcontainer_process` docstring：补「std_handles 管道调用方必须在 wait 前
   并发排水，否则管道背压死锁」纪律一行（防后续调用方重蹈，代码行为零改动）。
3. 两文件 4 处 I001 import 格式（上一席 WIP 残留）`ruff --fix` 收口。

## 五、实跑证据（全部本席实跑，解释器=ChatBot_Runtime venv）

| 命令 | 结果 |
|---|---|
| 首跑红点 | `1 failed in 46.83s`：`AssertionError: AC worker 45s 未退出 / assert None is not None` |
| 排水最小复现 | `probe available=True`；`rc=10, out_bytes=360448` → 死锁假设实锤 |
| loopback 取证 | `cmd rc=25, accepted=False, no-accept: TimeoutError`，管道=「拒绝访问」→ 隔离有效 |
| 修复后单测 | `1 passed in 1.63s` |
| 全文件 | `pytest tests/test_sandbox_windows.py` → **11 passed in 10.02s**（ruff --fix 后复跑 **11 passed in 5.40s**） |
| 相邻回归 | `pytest tests/test_bot_supervisor.py tests/test_supervisor_isolation.py tests/test_v21r2_lifecycle_r2.py` → **40 passed, 1 warning**（warning=nonebot mail 适配器 Pydantic 弃用告警，与本域无关） |
| Ruff | 两文件 4×I001 → `--fix` 后 **0 remaining** |
| Mypy（dev.ps1 同口径 flags） | supervisor 14 文件本域 **0 错**（仅剩 `control_plane/api/platform.py` 既有 2 错=S12 在飞域，与 AGENTS.md 台账 #36 记载一致） |

树卫生：全程 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp=%TEMP%` + `-p no:cacheprovider`；
终查 supervisor/tests 无 `__pycache__`/`*.pyc`/`.pytest_cache` 残留；临时取证脚本已清。

## 六、V21-ISO-001/002 四列状态

| 合同条目 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| **V21-ISO-001** AppContainer 强隔离（含显式阻断） | **done**（纯 Python 全链：建档→SID→NtCreateLowBoxToken 空 capability→环境块→CreateProcessAsUserW 挂起态 + AC 授权管道 + SandboxUnavailable 步骤级阻断；W4 属性表路线并存）。confidence: **verified** | **not done**：`spawn_isolated_worker`/`WindowsSandbox` 生产消费方为零（grep 实证仅包内自引），插件仍进程内运行。confidence: **verified**（缺口本身可验证） | **done**：真实容器拉起四探针全绿——公共可读文件活性对照（360KB 回收无死锁）、敏感文件拒读（SECRET_MARKER 未入管道）、跨 workspace 拒写（物证无新文件）、loopback 禁网（零 accept）；不可用分支 `sandbox_unavailable` 阻断语义有专测。confidence: **verified** | **unknown**：生产 bot 未部署未重启，无真机在线段证据 |
| **V21-ISO-002** Job Objects 配额 + 监督器回收 + 不降级 | **done**（内存/Job 内存、ActiveProcessLimit、单进程 CPU 时间、CPU 速率硬限、KILL_ON_JOB_CLOSE；挂 Job 失败→挂起进程显式终止不放行；监督器退出双保险回收）。confidence: **verified** | **not done**（同上，无生产装配）。confidence: **verified** | **done**：11 用例全绿——64MB 限拦 256MB 分配（rc=3+峰值封顶）、孙进程超额被拒、1s 配额终止忙循环、CPU 速率回读 3000、监督器退出 worker+孙进程零残留、3 轮 spawn 句柄零增长、嵌套 Job 支持、Deny-Write 施加/恢复 icacls 交叉验证。confidence: **verified** | **unknown**（同上） |

## 七、继承的真机边界（上一席实证，结论存于代码注释；原始记录未随交接保留）

置信度 high（多处以断言/护栏形式固化在代码与测试中，可复跑复核）：

- **AC 工作区布置受限**：`C:\Users` 与 `%LOCALAPPDATA%` 链上无 package SID / ALL APPLICATION
  PACKAGES ACE（仅 C:\Windows 树带只读 RX），非提权进程无法布置可写工作区；
  `CreateAppContainerProfile` 成功也不落地 `Packages\<name>AC` 文件夹 → 工作区授权须走
  `create_appcontainer_workspace`（创建即授权 + Low 完整性标签）。
- **容器 stdout 唯一出路=AC 授权管道**：容器内控制台/NUL 写被强制策略吞掉；管道 SD 必须
  user+package 双 GRANT + `S:(ML;;NW;;;LW)` 标签且两端可继承。
- **DENY 掩码禁泛型位**：GENERIC_WRITE 展开含 READ_CONTROL，一旦 DENY 连恢复通道都锁死
  （孤儿目录事故）；掩码=具体权利位 DE,WD,AD,WEA,WA，不 deny READ_CONTROL/WRITE_DAC/WRITE_OWNER。
- **删除防护不归 ACL 层**：D1-D3/E1 对照实验（上一席）实证 %TEMP% 继承链 OWNER RIGHTS(F)
  使 owner 经父目录删除旁路绕开 DENY(DE)——删除防护由 Job 层 KILL_ON_JOB_CLOSE/TerminateJobObject
  兜底，测试只断言契约要求的拒写+可逆（见 test_acl_deny_write_blocks_and_restores 注释）。
- **ACL 继承位必须 0x3**：误设 0x2（仅容器）时 ACE 不下传到文件，拒写验证形同虚设。

## 八、遗留与建议（S4 Supervisor 接入时）

1. **production_wiring 是 V21-ISO-001/002 当前唯一实质缺口**：需要插件装载器把
   `spawn_isolated_worker`/`WindowsSandbox` 接进插件生命周期（AC 需要工作区布置与 env 白名单
   决策），属 S4 席位范围；未接线前合同「所有业务插件强隔离」不能声称达成。
2. `windows_sandbox.py`（W4 属性表路线）与 `sandbox_windows.py`（NtCreateLowBoxToken 路线）
   双轨并存，S4 接入时需裁决主路线（本席仅验证两轨的 offline 语义，未做取舍）。
3. live_validation 需生产 bot 重启后按 acceptance-manual 对应节实机验收；未做前一律 unknown。
