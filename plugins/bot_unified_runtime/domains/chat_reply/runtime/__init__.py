"""chat_reply/runtime——消息主链运行时（pipeline/base_router/settings 等，v21r2 W15d 迁入）。"""

# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from .pipeline import RuntimeControlState, RuntimePipeline, offload_capability

__all__ = ["RuntimeControlState", "RuntimePipeline", "offload_capability"]
