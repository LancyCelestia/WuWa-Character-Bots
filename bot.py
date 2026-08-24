import faulthandler
import sys
import threading
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def _install_crash_guards() -> None:
    """把致命错误落盘，便于事后定位（无痕退出时也能留下证据）。

    - faulthandler：捕获段错误/栈溢出等原生致命错误并写堆栈；
    - sys.excepthook / threading.excepthook：主线程与子线程未捕获异常写日志。
    只做追加写入，不改变退出行为，无额外性能开销。
    """
    data_dir = Path(__file__).resolve().parent / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fault_log = open(data_dir / "faulthandler.log", "a", encoding="utf-8", buffering=1)
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

    sys.excepthook = _log_unhandled
    if hasattr(threading, "excepthook"):
        def _thread_hook(args) -> None:
            _log_unhandled(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook


_install_crash_guards()

nonebot.init(_env_file=(".env", ".env.prod"))

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 从 pyproject.toml 的 [tool.nonebot] 加载插件与适配器配置。
nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
