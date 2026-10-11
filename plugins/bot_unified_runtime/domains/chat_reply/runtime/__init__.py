"""chat_reply/runtime——消息主链运行时（pipeline/base_router/settings 等，v21r2 W15d 迁入）。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from typing import Any

__all__ = ["RuntimeControlState", "RuntimePipeline", "offload_capability"]

_PIPELINE_NAMES = frozenset(__all__)


# 包出口「抢名形」→ 惰性形（同一族残余，与
# `plugins/bot_unified_runtime/runtime/__init__.py` 同因同修，那里的 S142 注释写死了
# 「别改回抢名形」）。原先本行是 `from .pipeline import RuntimeControlState, …`，它是
# policy ⇄ runtime 这一环的**唯一活边**：
#   任一入口 → `chat_reply.policy`（或其任一枚子模块，父包 __init__ 必先行）
#   → policy/__init__:1 `from .gate import PolicySettings`
#   → gate.py:16 `from …runtime.mentions import …`（父包 `chat_reply.runtime` 未装载）
#   → 本文件旧第 6 行**立刻**去加载 pipeline
#   → pipeline:55 `from …policy.gate import PolicySettings`
#   → gate 正停在第 16 行、`PolicySettings` 定义在第 47 行尚未绑定 ⇒ ImportError。
# 只挂模块、把取名推迟到真正被访问那一刻，环就断开：访问发生时 gate/policy 早已初始化完毕
# （`pipeline` 被直接点名时它自己就是入口，父包 __init__ 空转即返回）。
# 🔴 三枚名字的**公开面不变**：`from …runtime import RuntimePipeline` 与属性访问照旧，
# 取到的仍是 pipeline 里那同一批对象（同一性锁在 tests/test_pipeline_hard_timeout.py）。
def __getattr__(name: str) -> Any:
    if name in _PIPELINE_NAMES:
        from . import pipeline as _pipeline

        return getattr(_pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _PIPELINE_NAMES)
