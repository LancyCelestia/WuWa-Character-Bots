"""旧包再导出面：``RuntimeControlState`` / ``RuntimePipeline`` / ``offload_capability``。

真身已迁至 ``domains/chat_reply/runtime/pipeline.py``（v21r2 reorg）。本包名下的三个名字
按**属性访问时**再向该模块取名（``from . import pipeline`` 只挂模块、不抢名）。

为什么必须是惰性的（S142 实证，别改回抢名形）：真身 pipeline 在自身 line 58 处
经 ``domains/ops/features/feature_gate`` → ``feature_catalog`` 绕回本包
（``from plugins.bot_unified_runtime.runtime import capability_protocols``）。
若本 ``__init__`` 在**模块初始化期**就去取 ``RuntimeControlState``，此时真身尚在
``sys.modules`` 里半初始化 ⇒ ``getattr`` 落空、直接 ``ImportError``（环）。
只挂模块、把取名推迟到真正被访问那一刻，环就断开：访问发生时真身早已初始化完毕。
"""
from typing import Any

__all__ = ["RuntimeControlState", "RuntimePipeline", "offload_capability"]

_PIPELINE_NAMES = frozenset(__all__)


def __getattr__(name: str) -> Any:
    if name in _PIPELINE_NAMES:
        from . import pipeline as _pipeline

        return getattr(_pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _PIPELINE_NAMES)
