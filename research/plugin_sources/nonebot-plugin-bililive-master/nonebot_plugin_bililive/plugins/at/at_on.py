from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.params import ArgPlainText
from nonebot.permission import SUPERUSER

from ...config import plugin_config
from ...database import DB as db
from ...utils import (
    get_type_id,
    group_only,
    handle_uid,
    on_command,
    to_me,
    uid_check,
)

at_on = on_command(
    "开启全体",
    rule=to_me(),
    permission=GROUP_OWNER | GROUP_ADMIN | SUPERUSER,
    priority=5,
)
at_on.__doc__ = """开启全体 UID"""

at_on.handle()(group_only)
at_on.handle()(handle_uid)
at_on.got("uid", prompt="请输入要开启全体的UID")(uid_check)


@at_on.handle()
async def _(event: GroupMessageEvent, uid: str = ArgPlainText("uid")):
    """根据 UID 开启全体"""
    if await db.set_sub(
        "at", True, uid=uid, type=event.message_type, type_id=await get_type_id(event)
    ):
        name = await db.get_name(uid) or "该UP主"
        await at_on.finish(
            f"已开启 {name}（{uid}）"
            f"{'直播推送' if not plugin_config.bililive_dynamic_at else ''}的@全体"
        )
    await at_on.finish(f"UID（{uid}）未关注，请先关注后再操作")
