import faulthandler
import os
import sys
import threading
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.telegram import Adapter as TelegramAdapter

# =========================================================================
# 进程守护 supervisor（审查 A-21，默认关闭）
# =========================================================================
# 背景（A 方审计 A-21）：原先 bot.py 只有 nonebot.run()，进程因未捕获异常/
# OOM/误杀崩溃后无人拉起，bot 停机直到人工介入。这里补一个最小守护循环：
# 环境变量 BOT_SUPERVISE=1 时，本进程在 nonebot.init 之前分叉、只当
# supervisor（不加载 500+ 字段配置、不加载插件、不占端口，保持轻薄），
# 子进程原样重跑 ``python bot.py`` 走现有完整启动路径；子进程非零退出按
# 退避重启（5s/15s/60s 封顶），10 分钟滑窗内连续崩溃达阈值则熔断停拉并写
# 崩溃摘要，防 crash-loop 烧日志。未设 BOT_SUPERVISE 时只多一次环境变量
# 读取，后续行为与原先完全一致（生产是否启用留 .env 裁定）。
#
# 可测试性约束：_supervise_loop / _run_supervised 只在函数体内导入模块级
# 没有的依赖（subprocess/time/deque/runtime_paths），不新增模块级状态——
# tests/test_bot_supervisor.py 用 AST 把顶层 import + 这几个函数摘到独立
# 命名空间执行（不能直接 import bot：模块级会触发 nonebot.init 与全插件
# 加载，重且带生产副作用）。


def _supervision_requested() -> bool:
    """BOT_SUPERVISE 显式为 1/true/on/yes（大小写不敏感）才启用守护。

    未设置或其余任何值一律视为关闭，行为与无此模块时完全一致。
    """
    return os.environ.get("BOT_SUPERVISE", "").strip().lower() in {"1", "true", "on", "yes"}


def _supervise_loop(
    child_command: list[str],
    *,
    child_env: dict[str, str] | None = None,
    backoff_schedule: tuple[float, ...] = (5.0, 15.0, 60.0),
    crash_window_seconds: float = 600.0,
    crash_threshold: int = 5,
    log_path: Path | None = None,
) -> int:
    """守护主循环（审查 A-21）。返回 supervisor 自身退出码。

    语义：
    - 子进程退出码 0 = 人工停止/优雅退出 → 不再拉起，supervisor 以 0 退出；
    - 非零退出视为崩溃 → 记入 ``crash_window_seconds`` 滑窗，窗口内达到
      ``crash_threshold`` 次即熔断（写摘要、以非零码退出），否则按
      ``backoff_schedule`` 退避后重启（超出档位取末档封顶）；
    - 每次拉起写一行（时间 + 第 N 次 + 上次退出码）进既有运行数据日志通道。

    Windows 信号取舍（为何这里没有信号处理器、也不开新进程组/job object）：
    - 子进程默认共享父进程控制台，控制台事件（CTRL_C_EVENT）由操作系统广播
      给控制台内所有进程 → 按下 Ctrl+C 时 nonebot 子进程照常优雅停机，
      supervisor 同时收到 KeyboardInterrupt，退出重启循环、等子进程退出后
      随同结束。「信号传递」由控制台广播天然完成，零转发代码——这是
      Windows 上最简可靠方案。
    - 不用 CREATE_NEW_PROCESS_GROUP：新进程组里的子进程默认忽略 Ctrl+C
      （需自行 SetConsoleCtrlHandler 重新启用），与「把 Ctrl+C 传给子进程
      正常退出」的目标相悖，故不采用。
    - 不引 job object：只多覆盖「父死子活」一种情形，属额外复杂度。停止
      整组用控制台 Ctrl+C 或 ``taskkill /T /PID <supervisor pid>``；单独杀
      supervisor 不会连带子进程（Windows 无 POSIX 进程组语义），运维须知。
    - 直接关闭控制台窗口（CTRL_CLOSE_EVENT）时操作系统同时终结两者，平台
      只给约 5 秒收尾，守护不覆盖该情形。
    """
    import subprocess
    import time
    from collections import deque

    def _log(line: str) -> None:
        # 既有日志通道 = 运行数据目录（与 faulthandler.log/crash.log 同处）；
        # supervisor 阶段还没有 nonebot logger，控制台同步回显一份。
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[supervisor] {stamp} {line}", flush=True)
        if log_path is None:
            return
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {line}\n")
        except OSError:
            pass  # 日志写不进去绝不影响守护本身

    crash_times: deque[float] = deque()
    restarts = 0
    last_returncode: int | None = None
    last_delay = 0.0
    while True:
        if restarts == 0:
            _log(f"第 1 次拉起子进程：{' '.join(child_command)}")
        else:
            _log(
                f"第 {restarts + 1} 次拉起"
                f"（上次退出码 {last_returncode}，退避 {last_delay:g}s 后重启）"
            )
        proc = subprocess.Popen(child_command, env=child_env)
        try:
            returncode = proc.wait()
        except KeyboardInterrupt:
            # 控制台事件已由 OS 同时送达子进程，让它走优雅停机；supervisor
            # 不吞信号也不抢跑：退出重启循环，等子进程退出后随同结束。
            _log("收到 Ctrl+C，停止拉起，等待子进程退出")
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _log("子进程 30s 未随 Ctrl+C 退出，强制终止（TerminateProcess 兜底）")
                proc.terminate()
            return 0
        if returncode == 0:
            _log("子进程退出码 0（正常停止），守护结束")
            return 0
        now = time.monotonic()
        crash_times.append(now)
        while crash_times and now - crash_times[0] > crash_window_seconds:
            crash_times.popleft()  # 窗口外的旧崩溃不累计（长期稳定运行后不算旧账）
        restarts += 1
        if len(crash_times) >= crash_threshold:
            _log(
                f"崩溃熔断：{crash_window_seconds:g}s 内连续崩溃 {len(crash_times)} 次"
                f"（阈值 {crash_threshold}），停止拉起防 crash-loop；最后退出码 {returncode}"
            )
            return 1
        last_returncode = returncode
        last_delay = backoff_schedule[min(restarts - 1, len(backoff_schedule) - 1)]
        try:
            time.sleep(last_delay)
        except KeyboardInterrupt:
            _log("重启等待期间收到 Ctrl+C，停止拉起")
            return 0


def _run_supervised() -> int:
    """守护模式入口：本进程只当 supervisor，子进程原样重跑 ``python bot.py``。

    子进程命令就是「同一解释器 + 本文件」（剥离 BOT_SUPERVISE 后），与人工
    启动完全同路径——守护拉起等价于一次人工重启，不引入第二套启动逻辑。
    日志落运行数据目录 supervisor.log（经 scripts.runtime_paths 解析，与
    faulthandler.log/crash.log 同处；源码树 data/ 不会被写，符合 G1 守卫）。
    """
    from scripts.runtime_paths import runtime_data_dir

    bot_path = Path(__file__).resolve()
    child_env = dict(os.environ)
    # 关键：子进程必须摘掉开关，否则子进程也会进入守护分支，无限套娃。
    child_env.pop("BOT_SUPERVISE", None)
    return _supervise_loop(
        [sys.executable, str(bot_path)],
        child_env=child_env,
        log_path=runtime_data_dir() / "supervisor.log",
    )


if __name__ == "__main__" and _supervision_requested():
    # 守护模式必须在 nonebot.init 之前分叉（父进程保持轻薄、不与子进程抢
    # 端口/日志）；未启用守护时这里只是一次布尔短路，后面的模块级初始化
    # 与原先逐行一致。
    raise SystemExit(_run_supervised())


def _install_crash_guards(runtime_data_dir: str | Path | None = None) -> None:
    """把致命错误落盘，便于事后定位（无痕退出时也能留下证据）。

    - faulthandler：捕获段错误/栈溢出等原生致命错误并写堆栈；
    - sys.excepthook / threading.excepthook：主线程与子线程未捕获异常写日志。
    只做追加写入，不改变退出行为，无额外性能开销。
    """
    configured = runtime_data_dir or os.environ.get("BOT_RUNTIME_DATA_DIR", "data")
    data_dir = Path(configured).expanduser()
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent / data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fault_log = open(data_dir / "faulthandler.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - faulthandler 需要长期持有追加日志句柄，不能随 with 关闭
        faulthandler.enable(fault_log, all_threads=True)
    except OSError:
        fault_log = None

    def _log_unhandled(exc_type, exc, tb) -> None:
        import traceback

        try:
            with open(data_dir / "crash.log", "a", encoding="utf-8") as handle:
                handle.write("=" * 60 + "\n")
                handle.write(f"{getattr(exc_type, '__name__', exc_type)}: {exc}\n")
                traceback.print_exception(exc_type, exc, tb, file=handle)
        except OSError:
            pass
        # 落盘之外同时打回控制台：否则前台启动时异常会被“静默吞掉”，
        # 只留下 crash.log，用户看到的是进程无故退出。
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = _log_unhandled
    if hasattr(threading, "excepthook"):
        def _thread_hook(args) -> None:
            _log_unhandled(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook



def _reap_background_threads(
    grace_seconds: float = 10.0,
    *,
    _force_exit=os._exit,
) -> None:
    """优雅停机上限（R2，治 Ctrl+C 后 60s+ 才退出）。

    实弹根因：nonebot 事件循环收尾后，进程内仍有**非 daemon 后台线程**
    （LLM offload 池 / mermaid-playwright 渲染线程 / kb_wiki 爬取线程 /
    ThreadPoolExecutor worker——这些线程在 Python 3.9+ 不可 daemon 化），
    解释器退出前的 ``threading._shutdown`` 会无限 join 它们，某个在途
    网络调用（LLM 预算最大 300s）不结束进程就不退出，期间再按 Ctrl+C
    即得 ``Exception ignored in threading._shutdown`` + KeyboardInterrupt。

    修法：nonebot.run() 正常返回后，给后台线程一个有限宽限（默认 10s）
    逐个 join；超限仍有滞留者且当前无异常在途（异常路径保留真实退出码
    给 crash guards / supervisor）则记一行并 ``os._exit(0)`` 强制收尾。
    SQLite 全部走事务/WAL，进程强制退出不会写坏库。测试经 AST 摘取本
    函数注入 ``_force_exit`` 桩执行（同 test_bot_supervisor 模式）。
    """
    import time

    main_thread = threading.current_thread()
    deadline = time.monotonic() + max(0.0, float(grace_seconds))
    stuck: list[threading.Thread] = []
    while True:
        stuck = [
            t
            for t in threading.enumerate()
            if t is not main_thread and t.is_alive() and not t.daemon
        ]
        if not stuck:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        for target in stuck:
            target.join(timeout=max(0.0, deadline - time.monotonic()))
    if stuck and sys.exc_info()[0] is None:
        names = ", ".join(sorted({t.name for t in stuck}))
        print(
            f"[bot] 停机宽限 {grace_seconds:g}s 后仍有后台线程未退出"
            f"（{names}），强制结束进程（在途任务放弃，数据面由事务/WAL 保证）。",
            flush=True,
        )
        _force_exit(0)



nonebot.init(_env_file=(".env", ".env.prod"))

# nonebot.init loads .env/.env.prod into the driver config. Install crash guards
# afterwards so startup failures are written to the same external Runtime data dir.
_driver_config = nonebot.get_driver().config
_install_crash_guards(getattr(_driver_config, "bot_runtime_data_dir", None))

# Telegram 轮询在代理瞬断/网络抖动时每 30 秒打一条完整堆栈；限速为首次与
# 每 5 分钟放行一条，其余丢弃。轮询失败由适配器自动重试并恢复，无需干预。
# OneBot V11 适配器在协议端（SnowLuma）未启动时同样每 5 秒重连并打完整堆栈，一并限速。
import time

from nonebot.log import default_filter, default_format

_POLL_FAILURE_COOLDOWN_SECONDS = 300.0
_POLL_FAILURE_STATE = {"last_shown": None, "suppressed": 0}


def _rate_limited_log_filter(record) -> bool:
    if not default_filter(record):
        return False
    message = str(record.get("message", ""))
    tg_poll_failure = any(
        marker in message for marker in ("Get updates for bot", "Setup for bot")
    ) and "failed" in message
    onebot_reconnect = "Error while setup websocket" in message
    if tg_poll_failure:
        # R2（2026-09-17）：TG 适配器在 poll/pre-setup 失败时打的 ERROR+完整
        # 堆栈全量丢弃，不再按 5 分钟冷却放行。韧性层（scripts/
        # telegram_resilience.py）已在同批失败上打简短一行告警（前 3 次 +
        # 之后每 5 次 + 恢复一条），堆栈零增量信息且刷屏——降为「告警一行+继续」。
        _POLL_FAILURE_STATE["suppressed"] += 1
        return False
    if onebot_reconnect:
        # 这类错误是代理/网络抖动的已知可恢复场景，韧性层会以简短行报告
        # 退避与恢复；完整堆栈对排障价值低且刷屏。按冷却限速放行：
        # 首条与每 5 分钟放行一条（运维必须能看见错误仍在发生），
        # 其余丢弃并计数。
        now = time.monotonic()
        last_shown = _POLL_FAILURE_STATE["last_shown"]
        if last_shown is None or now - last_shown >= _POLL_FAILURE_COOLDOWN_SECONDS:
            _POLL_FAILURE_STATE["last_shown"] = now
            _POLL_FAILURE_STATE["suppressed"] = 0
            return True
        _POLL_FAILURE_STATE["suppressed"] += 1
        return False
    return True


nonebot.logger.remove()
nonebot.logger.add(
    sys.stdout,
    level=0,
    diagnose=False,
    filter=_rate_limited_log_filter,
    format=default_format,
)


# Telegram 轮询韧性：通过子类覆盖启动与只读 getUpdates 网络重试；
# 不修改上游类、不接管消息 offset、不重复发送写操作。网络故障不阻塞主事件循环。
import asyncio

from nonebot.adapters.telegram.exception import NetworkError as TelegramNetworkError

from scripts.telegram_resilience import (
    build_resilient_telegram_adapter,
    is_transient_telegram_error,
)

ResilientTelegramAdapter = build_resilient_telegram_adapter(
    TelegramAdapter, network_error=TelegramNetworkError, logger=nonebot.logger,
    retryable=is_transient_telegram_error,
)


def _quiet_loop_exception_handler(loop, context):
    """网络断开时 asyncio 内部 create_connection 的裸 future 会抛
    "Task exception was never retrieved"（gaierror/TimeoutError 等 40 行堆栈）。
    这些异常的上游（mail worker / telegram poll）已经在各自重试并打简短日志，
    这里把裸异常降为一行摘要，不掩盖（仍可见类型与错误），只去噪。"""
    exception = context.get("exception")
    message = str(context.get("message", ""))
    if isinstance(exception, (ConnectionError, TimeoutError, OSError)) or "getaddrinfo" in message:
        handling = f"; handling={type(exception).__name__}" if exception else ""
        nonebot.logger.warning(
            "background network task failed (suppressed full traceback){}: {}",
            handling,
            message[:120],
        )
        return
    loop.default_exception_handler(context)




driver = nonebot.get_driver()


@driver.on_startup
async def _install_quiet_loop_exception_handler() -> None:
    """把降噪异常处理器装到真正运行中的事件循环上。

    此前在 import 期对 ``asyncio.get_event_loop()`` 的返回值安装，而
    ``nonebot.run()`` → ``asyncio.run()`` 会新建事件循环，处理器实际装在
    从未运行的旧循环上（该写法 Python 3.12+ 已弃用、3.14 直接报错）。
    必须是 async def：NoneBot 对同步 lifespan 钩子经 anyio run_sync 放到
    工作线程执行，那里没有事件循环（get_running_loop 直接报错）；async
    钩子才会被 await 在主循环上，此时取到的才是运行中的循环。
    """
    asyncio.get_running_loop().set_exception_handler(_quiet_loop_exception_handler)


@driver.on_shutdown
async def _early_shutdown_scheduler_stop() -> None:
    """停机序的第一拍（R2）：抢在 nonebot_plugin_apscheduler 自带的
    ``_shutdown_scheduler`` 之前关调度器（本钩子在 load_from_toml 之前
    注册，NoneBot on_shutdown 按 FIFO 执行）。

    - ``shutdown(wait=False)`` 立即取消在跑/排队的 job 执行（AsyncIOExecutor
      的 wait=True 本就无法等待协程 job，只做 cancel）——排队中的
      kb_wiki_sync 等长任务不再拖住停机序列；
    - 本钩子先关后，插件钩子看到的 ``scheduler.running`` 已为 False，自动
      跳过，等价幂等；若钩子顺序未来被反转，两边行为也一致（都是 cancel
      语义），不会双重关停。
    """
    try:
        from nonebot_plugin_apscheduler import scheduler as _apscheduler

        if _apscheduler.running:
            _apscheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001 - 停机清理绝不反噬停机本身。
        return


@driver.on_shutdown
async def _cancel_kb_sync_on_shutdown() -> None:
    """R3 停摆批（INT 席代挂）：停机即置 kb_wiki 同步协作取消位。

    前一钩子的 ``shutdown(wait=False)`` 只能取消排队 job——已开跑的同步
    线程（事件循环默认线程池）停不住；取消位让它在下一个批边界退出
    （断点在库，重启续跑），数小时级同步不再拖住进程收尾（bot.py:376
    既有注释口径：停机不等 kb 任务，本调用只加速收尾）。fail-open：
    导入失败/任务未在跑都只记一行，绝不反噬停机本身。
    """
    try:
        from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
            cancel_kb_sync_task,
        )

        cancel_kb_sync_task(reason="shutdown")
    except Exception:  # noqa: BLE001 - 停机清理绝不反噬停机本身。
        nonebot.logger.debug("kb_wiki 同步停机取消位设置失败（忽略）", exc_info=True)


driver.register_adapter(OneBotV11Adapter)
driver.register_adapter(ResilientTelegramAdapter)

# 从 pyproject.toml 的 [tool.nonebot] 加载插件与适配器配置。
nonebot.load_from_toml("pyproject.toml")

# R2（2026-09-17）：apscheduler misfire 降噪。插件默认 job_defaults 的
# misfire_grace_time=1s——良性 1-2s 的调度延迟即刷「Run time of job ... was
# missed by 0:00:01~2」。这里在**调度器已创建、尚未 start**（start 发生在
# 插件 on_startup 钩子）的窗口补设默认 30s；各 job 显式传入的
# misfire_grace_time（120/300/3600）不受影响，真超期仍照常告警。
try:
    from nonebot_plugin_apscheduler import scheduler as _apscheduler_for_defaults

    if not _apscheduler_for_defaults.running:
        _apscheduler_for_defaults.configure(job_defaults={"misfire_grace_time": 30})
except Exception as _misfire_exc:  # noqa: BLE001 - 调度器不可用时维持缺省行为，不影响启动。
    nonebot.logger.debug(
        "apscheduler misfire_grace_time 预设跳过: {}", _misfire_exc
    )


def _probe_onebot_endpoints() -> None:
    """启动预检：协议端未监听时给出人话告警（WinError 1225 高频现场）。

    OneBot V11 正向 WS 地址来自 driver 配置 ``onebot_ws_urls``（适配器
    adapter.py 的真实消费键）。探测失败绝不阻断启动——适配器韧性重连仍在，
    这里只是把「连接被拒绝 = 该地址没有进程在听」翻译成一句可执行的操作提示，
    代替让用户面对重连堆栈自行排障。
    """
    import socket
    from urllib.parse import urlsplit

    urls = getattr(_driver_config, "onebot_ws_urls", None) or []
    for raw in urls:
        try:
            parts = urlsplit(str(raw))
            host = parts.hostname or "127.0.0.1"
            port = parts.port or (443 if parts.scheme == "wss" else 80)
        except ValueError:
            continue
        try:
            with socket.create_connection((host, port), timeout=1.5):
                pass
        except ConnectionRefusedError:
            nonebot.logger.warning(
                "SnowLuma 未在 {host}:{port} 监听（WinError 1225 连接被拒绝 = 该地址没有进程在听）。"
                "请先启动 SnowLuma 并在其 WebUI「进程注入」页加载该号的 QQ，确认『正向 WebSocket 服务』"
                "监听地址与 access_token 和 .env 一致；bot 会继续启动，SnowLuma 上线后自动连上。",
                host=host,
                port=port,
            )
        except OSError:
            continue
        except Exception:  # noqa: BLE001 - 预检绝不影响启动。
            return


_probe_onebot_endpoints()

# Import the patched Mail adapter only after NoneBot has loaded project plugins;
# importing the package earlier triggers its plugin module initialization too soon.
# 插件未加载成功时不要导入其子模块：失败后父包已从 sys.modules 移除，
# 此时导入子模块会重新执行整个插件 __init__（重复注册 matcher 并再次报错）。
# 注意 plugin.id_ 是短名（如 bot_unified_runtime），module_name 才是完整模块路径。
_loaded_plugin_modules = {
    plugin.module_name for plugin in nonebot.get_loaded_plugins()
}
if "plugins.bot_unified_runtime" not in _loaded_plugin_modules:
    raise RuntimeError(
        "plugins.bot_unified_runtime 未成功加载（见上方日志），"
        "已停止初始化 Mail 适配器。请先修复插件导入错误。"
    )
from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    ResilientMailAdapter,
)

driver.register_adapter(ResilientMailAdapter)

# 可选外挂：表情包生成插件（含 meme-generator 模型资源）。
# 必须在 nonebot.init 之后加载（其 config 依赖 driver）；默认关闭，
# 开启后其命令 matcher 独立于统一管线直接响应，属能力空白的功能件。
if getattr(_driver_config, "bot_memes_plugin_enabled", False):
    try:
        nonebot.load_plugin("nonebot_plugin_memes")
    except Exception as _memes_exc:  # noqa: BLE001 - 外挂加载失败不阻断主 bot 启动。
        import sys as _sys

        print(f"[bot] nonebot_plugin_memes 加载失败（功能降级不影响其他能力）: {_memes_exc}", file=_sys.stderr)

if __name__ == "__main__":
    try:
        nonebot.run()
    except KeyboardInterrupt:
        pass  # Ctrl+C 属正常停机：退出码 0，supervisor 视为人工停止不重启。
    finally:
        # R2：后台线程有限宽限 + 超限强制收尾（见 _reap_background_threads）。
        _reap_background_threads()
