import faulthandler
import os
import sys
import threading
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.telegram import Adapter as TelegramAdapter


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



nonebot.init(_env_file=(".env", ".env.prod"))

# nonebot.init loads .env/.env.prod into the driver config. Install crash guards
# afterwards so startup failures are written to the same external Runtime data dir.
_driver_config = nonebot.get_driver().config
_install_crash_guards(getattr(_driver_config, "bot_runtime_data_dir", None))

# Telegram 轮询在代理瞬断/网络抖动时每 30 秒打一条完整堆栈；限速为首次与
# 每 5 分钟放行一条，其余丢弃。轮询失败由适配器自动重试并恢复，无需干预。
# OneBot V11 适配器在 NapCat 未启动时同样每 5 秒重连并打完整堆栈，一并限速。
import time

from nonebot.log import default_filter, default_format

_POLL_FAILURE_COOLDOWN_SECONDS = 300.0
_POLL_FAILURE_STATE = {"last_shown": 0.0, "suppressed": 0}


def _rate_limited_log_filter(record) -> bool:
    if not default_filter(record):
        return False
    message = str(record.get("message", ""))
    tg_poll_failure = any(
        marker in message for marker in ("Get updates for bot", "Setup for bot")
    ) and "failed" in message
    onebot_reconnect = "Error while setup websocket" in message
    if tg_poll_failure or onebot_reconnect:
        now = time.monotonic()
        if now - _POLL_FAILURE_STATE["last_shown"] < _POLL_FAILURE_COOLDOWN_SECONDS:
            _POLL_FAILURE_STATE["suppressed"] += 1
            return False
        _POLL_FAILURE_STATE["last_shown"] = now
        _POLL_FAILURE_STATE["suppressed"] = 0
    return True


nonebot.logger.remove()
nonebot.logger.add(
    sys.stdout,
    level=0,
    diagnose=False,
    filter=_rate_limited_log_filter,
    format=default_format,
)


# Telegram 轮询韧性：上游 poll() 的 pre-setup 失败（如启动瞬间代理不通）会直接
# 杀死轮询任务、Telegram 永久离线直到重启。这里在外层包无限重试（指数退避，
# 封顶 60 秒），保证代理/网络恢复后自动上线。
import asyncio

_original_tg_poll = TelegramAdapter.poll


async def _resilient_tg_poll(self, bot):
    delay = 3.0
    while True:
        try:
            return await _original_tg_poll(self, bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 轮询退出一律重试，退避已封顶。
            delay = min(delay * 2.0, 60.0)
            nonebot.logger.warning(
                "Telegram poll task exited ({}); retrying in {:.0f}s",
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)


TelegramAdapter.poll = _resilient_tg_poll

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
driver.register_adapter(TelegramAdapter)

# 从 pyproject.toml 的 [tool.nonebot] 加载插件与适配器配置。
nonebot.load_from_toml("pyproject.toml")

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
from plugins.bot_unified_runtime.mail_adapter import ResilientMailAdapter

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
    nonebot.run()
