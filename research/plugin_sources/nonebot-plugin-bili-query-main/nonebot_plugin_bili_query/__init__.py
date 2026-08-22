from nonebot import require

# ====== require 放在所有 import 之前 ======
require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")

from nonebot import on_command, get_plugin_config, get_driver, get_bots
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.log import logger

from .config import Config
from .parser import parse_uid, parse_bv, parse_b23_url, parse_video_url
from .api import get_user_info, get_video_info, get_user_videos, resolve_b23_url
from .database import (
    init_db,
    add_subscription,
    remove_subscription,
    set_subscription_baseline,
)
from .scheduler import init_scheduler, register_notify_callback

# ————————————————————————————
# 插件元数据
# ————————————————————————————

__plugin_meta__ = PluginMetadata(
    name="B站查询与提醒",
    description="B站用户与视频查询插件，支持订阅用户更新提醒",
    usage=(
        "/help - 显示所有指令\n"
        "/用户查询 [UID/链接] - 查询B站用户信息\n"
        "/视频查询 [BV号/链接] - 查询B站视频信息\n"
        "/订阅 [UID/链接] - 订阅用户更新提醒\n"
        "/取消订阅 [UID/链接] - 取消订阅"
    ),
    type="application",
    homepage="https://github.com/Wojusensei/nonebot-plugin-bili-query",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# ————————————————————————————
# 读取配置
# ————————————————————————————

config = get_plugin_config(Config)

# ————————————————————————————
# 命令注册
# ————————————————————————————

help_cmd = on_command("help", aliases={"帮助"}, priority=10, block=True)
user_cmd = on_command("用户查询", priority=10, block=True)
video_cmd = on_command("视频查询", priority=10, block=True)
subscribe_cmd = on_command("订阅", priority=10, block=True)
unsubscribe_cmd = on_command("取消订阅", priority=10, block=True)


# ————————————————————————————
# 通知发送（由 scheduler 回调）
# ————————————————————————————

async def send_notification(group_id: str, uid: str, video_info: dict):
    """向群组发送视频更新通知（遍历所有已连接的 OneBot v11 Bot）"""
    title = video_info.get('title', '无标题')
    bvid = video_info.get('bvid', '')
    created = video_info.get('created')
    time_str = created.strftime("%Y-%m-%d %H:%M") if created else "未知"
    msg = (
        f"📢 您订阅的UP主 {uid} 发布了新视频！\n"
        f"标题：{title}\n"
        f"BV号：{bvid}\n"
        f"发布时间：{time_str}\n"
        f"链接：https://www.bilibili.com/video/{bvid}"
    )
    sent = False
    for bot in get_bots().values():
        if not isinstance(bot, Bot):
            continue
        try:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
            sent = True
        except Exception as e:
            logger.error(f"通过 Bot {bot.self_id} 发送通知失败: {e}")
    if not sent:
        logger.warning(f"没有可用的 OneBot v11 Bot，未能向群 {group_id} 发送订阅通知")


register_notify_callback(send_notification)


# ————————————————————————————
# /help
# ————————————————————————————

@help_cmd.handle()
async def handle_help():
    help_text = (
        "📖 B站查询与提醒 插件指令：\n"
        "1. /用户查询 [UID/链接] - 查询B站用户信息（粉丝、投稿数等）\n"
        "2. /视频查询 [BV号/链接] - 查询B站视频信息（播放量、点赞等）\n"
        "3. /订阅 [UID/链接] - 订阅用户，有新视频时自动提醒\n"
        "4. /取消订阅 [UID/链接] - 取消订阅\n"
        "5. /help - 显示本帮助"
    )
    await help_cmd.finish(help_text)


# ————————————————————————————
# /用户查询 命令
# ————————————————————————————

@user_cmd.handle()
async def handle_user_query(args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await user_cmd.finish("请提供要查询的 UID 或空间链接，例如：/用户查询 123456")

    uid = parse_uid(raw)
    if not uid:
        await user_cmd.finish("未能识别 UID，请提供 B站 UID 或空间链接")

    info = await get_user_info(uid)
    if not info:
        await user_cmd.finish("查询失败，请检查 UID 是否正确或稍后再试")

    last_video = info.get('last_video_time')
    last_video_str = last_video.strftime("%Y-%m-%d %H:%M") if last_video else "暂无"

    reply = (
        f"📊 用户信息：{info['name']}\n"
        f"UID：{info['uid']}\n"
        f"粉丝：{info['fans']}\n"
        f"关注：{info['following']}\n"
        f"投稿数：{info['videos']}\n"
        f"获赞数：{info['likes']}\n"
        f"专栏数：{info['article']}\n"
        f"动态数：{info['dynamic_count']}\n"
        f"最近视频：{last_video_str}"
    )
    await user_cmd.finish(reply)


# ————————————————————————————
# /视频查询 命令
# ————————————————————————————

@video_cmd.handle()
async def handle_video_query(args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await video_cmd.finish("请提供要查询的 BV 号或视频链接，例如：/视频查询 BV1xx411c7mD")

    # 依次尝试：直接提取 BV 号 → 完整链接中提取 → b23.tv 短链接解析
    bv = parse_bv(raw)
    if not bv:
        url = parse_video_url(raw)
        if url:
            bv = parse_bv(url)
    if not bv:
        b23 = parse_b23_url(raw)
        if b23:
            bv = await resolve_b23_url(b23)

    if not bv:
        await video_cmd.finish("未能识别 BV 号，请提供正确的 BV 号或视频链接")

    info = await get_video_info(bv)
    if not info:
        await video_cmd.finish("查询失败，请检查 BV 号是否正确或稍后再试")

    duration = info.get('duration', 0)
    minutes = duration // 60
    seconds = duration % 60
    duration_str = f"{minutes}分{seconds}秒"

    desc = (info.get('desc') or '无简介').strip()
    desc_str = desc[:100] + "..." if len(desc) > 100 else desc

    reply = (
        f"🎬 视频信息：{info['title']}\n"
        f"BV号：{info['bvid']}\n"
        f"UP主：{info['uploader']}\n"
        f"时长：{duration_str}\n"
        f"播放量：{info['play']}\n"
        f"点赞：{info['like']}\n"
        f"投币：{info['coin']}\n"
        f"收藏：{info['favorite']}\n"
        f"转发：{info['share']}\n"
        f"发布时间：{info['pubdate'].strftime('%Y-%m-%d %H:%M')}\n"
        f"简介：{desc_str}"
    )
    await video_cmd.finish(reply)


# ————————————————————————————
# /订阅 命令
# ————————————————————————————

@subscribe_cmd.handle()
async def handle_subscribe(event: Event, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await subscribe_cmd.finish("订阅功能仅支持群聊使用")

    raw = args.extract_plain_text().strip()
    if not raw:
        await subscribe_cmd.finish("请提供要订阅的 UID 或空间链接，例如：/订阅 123456")

    uid = parse_uid(raw)
    if not uid:
        await subscribe_cmd.finish("未能识别 UID，请提供 B站 UID 或空间链接")

    group_id = str(event.group_id)
    success = await add_subscription(group_id, uid)
    if not success:
        await subscribe_cmd.finish(f"⚠️ 该 UID 已被本群订阅")

    # 订阅时记录 UP 主当前最新视频作为基线，避免旧视频被当作新视频播报（尽力而为）
    try:
        videos = await get_user_videos(uid, ps=1)
        if videos and videos[0].get('bvid') and videos[0].get('created'):
            await set_subscription_baseline(
                group_id, uid, videos[0]['bvid'], int(videos[0]['created'].timestamp())
            )
    except Exception as e:
        logger.warning(f"记录订阅基线失败（不影响订阅）: {e}")

    await subscribe_cmd.finish(f"✅ 订阅成功！已订阅 UID：{uid}")


# ————————————————————————————
# /取消订阅 命令
# ————————————————————————————

@unsubscribe_cmd.handle()
async def handle_unsubscribe(event: Event, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await unsubscribe_cmd.finish("订阅功能仅支持群聊使用")

    raw = args.extract_plain_text().strip()
    if not raw:
        await unsubscribe_cmd.finish("请提供要取消订阅的 UID 或空间链接，例如：/取消订阅 123456")

    uid = parse_uid(raw)
    if not uid:
        await unsubscribe_cmd.finish("未能识别 UID，请提供 B站 UID 或空间链接")

    group_id = str(event.group_id)
    success = await remove_subscription(group_id, uid)
    if success:
        await unsubscribe_cmd.finish(f"✅ 取消订阅成功！已取消 UID：{uid}")
    else:
        await unsubscribe_cmd.finish("⚠️ 未找到该 UID 的订阅记录")


# ————————————————————————————
# 启动时初始化数据库和定时器
# ————————————————————————————

driver = get_driver()


@driver.on_startup
async def startup():
    await init_db()
    init_scheduler(config.bili_query_check_interval_minutes)
    logger.info("B站查询与提醒插件已启动")
