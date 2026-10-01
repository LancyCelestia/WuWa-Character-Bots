"""ops/self_knowledge：确定性「自我认知」装配（需求 10 的命令/自然语言入口核心）。

把 ``self_calendar``（时刻 + 四历法 + 台账更新历史）、``character/temporal``
（框架/适配器/插件版本 + git 提交历史 + 功能清单）与本包新增的 NoneBot 插件装载
清单一并装配成一段可确定朗读的读出，并可被命令能力 ``bot.self_info`` 复用。

本包零历法算法、零版本号自算、零手写计数（AGENTS 规则 10）；实现真身在 ``entry``。
接线（路由/帮助/配置）在禁改共享文件里，走 ``patch-SELF.md`` 交主会话串行落。
"""

from plugins.bot_unified_runtime.domains.ops.self_knowledge.entry import (
    SELF_KNOWLEDGE_CAPABILITY_ID,
    build_self_knowledge_capability,
    is_self_info_command,
    plugin_inventory_lines,
    self_knowledge_lines,
    self_knowledge_text,
)

__all__ = [
    "SELF_KNOWLEDGE_CAPABILITY_ID",
    "build_self_knowledge_capability",
    "is_self_info_command",
    "plugin_inventory_lines",
    "self_knowledge_lines",
    "self_knowledge_text",
]
