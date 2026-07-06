from __future__ import annotations

from .config import Config

try:
    from nonebot.plugin import PluginMetadata
except Exception:

    class PluginMetadata:  # type: ignore[no-redef]
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

__plugin_meta__ = PluginMetadata(
    name="WuWa Unified Runtime",
    description="统一角色机器人运行时、人格上下文、媒体解析和发送审计入口",
    usage="/wuwa status",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11", "~console", "~mail"},
    extra={"milestone": "0"},
)


def _register_nonebot_handlers() -> None:
    try:
        from nonebot import on_command
    except Exception:
        return

    from .capabilities.echo import build_status_result

    status = on_command("wuwa", aliases={"/wuwa"}, priority=20, block=True)

    @status.handle()
    async def _handle_status() -> None:
        result = build_status_result()
        await status.finish(result.body)


_register_nonebot_handlers()
