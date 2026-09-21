# v21r2 R8 席 — 生产闪退（2026-09-17 23:24）根因取证日志

> 席位：R8（生产闪退硬崩溃根因诊断，systematic-debugging）。全程只读取证（Runtime/火绒库均先拷 %TEMP% 后读副本），未动 bot.py/sender/*（R2b 域），未重启生产，未真实出站。
> 交付：根因结论（下方）+ 兜底加固 `scripts/crash_trap.py`（已落地，7 passed + ruff/mypy 全绿）+ bot.py 装配坐标（移交 R2b）。

## 一、症状

用户经 `dev.ps1 run` 前台启动生产 bot（PowerShell 历史实锤：今晚多次 `powershell ... dev.ps1 run`）。处理两条消息、发出一条私聊回复（message_sent SUCCESS 23:24:32，self_id 3958874605）后整个进程立即死亡：`scripts/dev.ps1:110` `Invoke-External` throw `python.exe exited with code -1.`，**无任何 Python traceback**。

## 二、死亡时刻钉定（wuwa_receipts.sqlite3，拷贝副本实读）

- 会话 A（死亡会话）最后一条 DB 写入：`dbg_9dc07e3b3489` / `req_44545718bd07` / state=sent / onebot.v11 / provider_message_id=175109482 / **created_at 2026-09-17T15:24:32.603364+00:00 = 23:24:32.603 本地**——与用户看到的 SUCCESS 完全吻合。queued→sent 全链（200ms）干净收尾，单段消息。
- 该行之后到 23:40:50 重启之间：**零业务写入**。发送管线是完整跑完的，死亡发生在回执落盘之后的静默期（worker 空转/贴表情等无 DB 痕迹步骤）。
- 会话 A 全程（23:05-23:24）共 13 条私聊 bot.chat 回复（session 422376604）+ 大量 policy blocked，无失败重试面。

## 三、四面取证（关键：全部为"无"）

| 证据面 | 结果 | 含义 |
|---|---|---|
| Windows 事件日志 Application（22:00-23:45 全量） | 仅 SPP/Defender 1151 健康报告，**无 1000 Application Error / 1001 WER** | 无原生崩溃。WER 未禁用（注册表 Disabled 为空），真崩溃必留痕 |
| WER ReportArchive/ReportQueue（用户级不存在；ProgramData 全量） | **任何日期都无 python.exe 记录** | 同上 |
| faulthandler.log（bot.py:179 已启用，all_threads，段错误/栈溢出必写） | **0 字节，mtime 08-24** | 无段错误/栈溢出/abort/fastfail |
| crash.log（sys.excepthook + threading.excepthook，bot.py:183-202） | 最后一条 09-15 16:37，今晚零写入 | 无主线程/子线程未捕获异常 |
| 源码硬退出点（rg 全树 + venv py） | 项目零 `exit(-1)/os._exit(-1)/SystemExit(-1)`；bot.py 唯一硬退是 `_reap_background_threads` 的 `os._exit(0)`（会打控制台提示且码≠-1）；venv 命中仅 pip/alembic 等 CLI | 排除代码内主动 -1 退出 |
| System 日志 23:18-23:45 | 仅 Schannel 36876 噪声（bot 出站 TLS 握手失败类，各时段都有） | 无系统级事件 |
| Security 4688/4689 审计 | 未开审计，无记录 | 看不到击杀者（见 §五） |
| Defender | RTP/OA/IOAV/BM 全 disabled（被火绒接管），隔离区零 python | 排除 Defender |
| 火绒（HipsDaemon/HRWSCCtrl 在跑）QuarantineEx.db + applog.db（拷副本实读） | 隔离区仅 ThrottleStop.sys（Vulndriver），零 python；applog 只记进程启动 | 火绒**未隔离** python；HIPS 击杀不落这些库，不能完全排除（§五） |
| 计划任务日志 23:10-23:30 | 无相关任务触发 | 排除计划任务击杀 |

## 四、exit code -1 的语义

`-1` = 0xFFFFFFFF。Windows 上该退出码的典型来源：**外部 `TerminateProcess(handle, 0xFFFFFFFF)`**——正是 .NET `Process.Kill()`/PowerShell `Stop-Process` 的固定签名（部分安全软件内核也用任意码）。段错误=0xC0000005、栈溢出=0xC00000FD、abort=0xC0000409、Ctrl+C=0xC000013A、taskkill/python `Popen.kill()`=1，均非 -1。

## 五、根因结论

**结论（置信度 high）：非崩溃，是被外部 `TerminateProcess(0xFFFFFFFF)` 击杀。** 证据链＝§三四面全空（Python 异常/原生崩溃全部必留痕而未留）+ §四退出码签名 + §二死亡发生在管线干净收尾后的静默期 + 全树无 -1 退出点。进程不是"死"于任何在跑的代码，是被"杀"的。

**击杀者身份（置信度 unknown，如实存疑）**：本机可见遥测全部照不到"谁发的 TerminateProcess"。候选：
1. **火绒 HIPS/加速球类主动拦截**（HipsDaemon 常驻；其击杀不进 Windows 日志、其自有库无击杀表；建议用户在火绒「信任区」加 bot 目录并翻其界面日志）。
2. **某个 AI 代理会话的 shell 内建 kill / Stop-Process**（23:19-23:31 WorkBuddy 的 PortableGit 工具链 cat/sort/mkdir/awk 活跃；bash `kill`/PS `Stop-Process` 均不产生新进程记录，AppRunInfoList 看不见；ZCode/WorkBuddy 代理规则禁杀生产但无法从日志证伪）。
3. 用户侧其他自动化脚本（Stop-Process 类）。

**已排除清单**：Python 主线程/子线程未捕获异常、asyncio 未检索异常（有 excepthook 面）、段错误/栈溢出/abort/fastfail（faulthandler+WER 面）、OOM（无 WER 低内存记录）、代码内主动 -1 退出、计划任务、Defender、火绒隔离、supervisor 熔断（无 supervisor.log，BOT_SUPERVISE 未启用）。

**附带发现（交用户）**：
- 23:40:50 起**两个 bot.py 进程并存**：PID 53584（venv python，正常工作）+ PID 25720（**系统 Python312 直跑 bot.py**），00:16:51 又双启了一次——双实例共抢 8080/3001/SQLite，属高危误操作面，建议只留一个入口启动。
- 23:24:39 有进程以 Git Bash `cp` 复制了停更于 09-12 的 nonebot.out.log → `.bak-20260912`（Creation=LastWrite=23:24:39 特征）；23:28:36 两个 nonebot 日志被清零。均非 bot 行为，系人/代理取证动作，与本 crash 无因果（dev.ps1 run 输出走控制台，今晚日志本就不落这些文件）。

## 六、兜底加固交付（必做项，已落地）

新文件 `scripts/crash_trap.py`：**外部 TerminateProcess 在进程内无钩子可拦，唯一对策是"平时留活口证据"**——
1. 存活心跳：daemon 线程每 5s 单行覆写 `crash_heartbeat_pid<pid>.log`（flush+fsync）→ 下次死亡可把时刻钉到 ±5s；
2. 退出标记：`mark(stage)` + atexit → `crash_markers.log`，"有 atexit 标记=优雅退出 / 无=被杀或硬崩"二值判定；
3. faulthandler 兜底启用（bot.py 已启用则跳过）+ sys.unraisablehook 补漏。

放置 `scripts/` 而非 `plugins.bot_unified_runtime.runtime/`：bot.py 装配点早于 load_from_toml，早 import 插件包子模块会连带执行整个插件 `__init__`；`scripts` 已是 bot.py 既有导入域（runtime_paths/telegram_resilience 先例）。

**实测**：`tests/test_crash_trap.py` 7 passed（0.5s，离线 tmp_path）；ruff All checks passed；mypy Success。

### R2b 落地坐标（bot.py，本席不越域）

`bot.py:260`（`_install_crash_guards(getattr(_driver_config, "bot_runtime_data_dir", None))` 一行）之后追加：

```python
# R8：崩溃/击杀取证陷阱（心跳+退出标记，治 2026-09-17 23:24 无痕闪退类）。
from scripts.crash_trap import install as install_crash_trap

install_crash_trap(getattr(_driver_config, "bot_runtime_data_dir", None))
```

可选增强：`_early_shutdown_scheduler_stop`（bot.py:368）首行加 `trap.mark("nonebot_on_shutdown")`（先 `install` 取单例），让"优雅停机开始"也可判定。

### 验收点（下次重启后）

- `ChatBot_Runtime/data/crash_heartbeat_pid*.log` 出现且每 5s 刷新；停机时 `crash_markers.log` 追加 `stage=nonebot_on_shutdown`/`stage=atexit_interpreter_shutdown`/`stage=trap_stop`。
- 再次无痕闪退时：心跳文件停在哪一秒 + markers 缺 atexit = 外部击杀实锤，配合火绒界面日志即可定位击杀者。
