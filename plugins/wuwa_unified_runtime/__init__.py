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
        from nonebot.adapters import Event
        from nonebot.params import CommandArg
        from nonebot.typing import T_State
    except Exception:
        return

    from .capabilities.auto_send import build_auto_send_preview_text
    from .capabilities.echo import build_status_result

    status = on_command("wuwa", aliases={"/wuwa"}, priority=20, block=True)
    auto_send = on_command("报存", priority=21, block=True)

    @status.handle()
    async def _handle_status(args=CommandArg()) -> None:
        if args.extract_plain_text().strip() != "status":
            from .capabilities.echo import build_help_result

            await status.finish(build_help_result().body)
        result = build_status_result()
        await status.finish(result.body)

    @auto_send.handle()
    async def _handle_auto_send(event: Event, state: T_State, args=CommandArg()) -> None:
        command_text = f"报存 {args.extract_plain_text()}".strip()
        preview = build_auto_send_preview_text(
            command_text,
            actor_sender_id=event.get_user_id(),
            actor_session_id=event.get_session_id(),
        )
        state["wuwa_preview_only"] = True
        await auto_send.finish(preview)


_register_nonebot_handlers()
