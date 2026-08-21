"""共享群上下文接口（预留）。

会话隔离规则：注入大模型的历史**只按 platform/adapter/bot/session/
sender 隔离**——群聊里 A 与机器人的记录不会混进 B 与机器人的记录
（私聊同理，只有该用户与机器人）。这层接口解决另一件事：运营者
明确开启时，把"最近共同会话的公共投影"（不含任何个人私密内容）
作为可选上下文注入，例如群聊近期的共同话题摘要。

默认关闭；provider 未实现时返回空上下文，prompt 分区跳过。
接入方式：实现 ``SharedGroupContextProvider``（可从群历史仓库
生成脱敏摘要），在 ``build_character_context_provider`` 传入。
"""

from __future__ import annotations

from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import SharedGroupContext


class SharedGroupContextProvider(Protocol):
    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        """读取群维度公共上下文投影；无可用数据返回 enabled=False。"""


class NullSharedGroupContextProvider:
    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        return SharedGroupContext(request_id=request_id, enabled=False)


def build_shared_group_context_provider(config: object) -> SharedGroupContextProvider:
    # 首版：默认关闭。启用时也不自动猜测来源，要求显式实现 provider。
    enabled = bool(getattr(config, "wuwa_shared_group_context_enabled", False))
    if not enabled:
        return NullSharedGroupContextProvider()
    return NullSharedGroupContextProvider()
