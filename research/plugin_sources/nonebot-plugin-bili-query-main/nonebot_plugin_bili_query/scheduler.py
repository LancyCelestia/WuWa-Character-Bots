from nonebot import require

require("nonebot_plugin_apscheduler")

from collections import defaultdict
from datetime import datetime
from typing import Awaitable, Callable, Dict, List

from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from .database import get_subscriptions, get_subscription_groups, update_last_video
from .api import get_user_videos

# 通知回调签名：(group_id, uid, video_info) -> None
NotifyCallback = Callable[[str, str, Dict], Awaitable[None]]

_notify_callbacks: List[NotifyCallback] = []


def register_notify_callback(callback: NotifyCallback):
    """注册通知回调函数，由 __init__ 调用"""
    if callback not in _notify_callbacks:
        _notify_callbacks.append(callback)


async def check_subscriptions():
    """定时任务：检查所有订阅用户是否有新视频

    同一位 UP 主可能被多个群订阅：按 UID 分组后统一判断一次更新，
    有新视频时向所有订阅了该 UP 主的群发送通知。
    """
    subscriptions = await get_subscriptions()
    if not subscriptions:
        return

    by_uid: Dict[str, List[str]] = defaultdict(list)
    for group_id, uid in subscriptions:
        by_uid[uid].append(group_id)

    for uid, groups in by_uid.items():
        try:
            videos = await get_user_videos(uid, ps=1)
            if not videos:
                continue

            latest = videos[0]
            bvid = latest.get('bvid')
            created = latest.get('created')
            if not bvid or not created:
                continue

            timestamp = int(created.timestamp())

            rows = await get_subscription_groups(uid)
            # update_last_video 按 UID 更新全部行，各行记录一致，取第一行即可
            last_bvid = rows[0][2] if rows else None
            last_time = rows[0][3] if rows else None

            if last_bvid is None:
                # 首次见到该订阅：只建立基线，不把旧视频当作新视频播报
                await update_last_video(uid, bvid, timestamp)
            elif bvid != last_bvid and (last_time is None or timestamp > last_time):
                await update_last_video(uid, bvid, timestamp)
                for callback in _notify_callbacks:
                    for group_id in groups:
                        try:
                            await callback(group_id, uid, latest)
                        except Exception as e:
                            logger.error(f"向群 {group_id} 发送订阅通知失败: {e}")

        except Exception as e:
            logger.error(f"检查订阅 {uid} 失败: {e}")


def init_scheduler(interval_minutes: int = 5):
    """初始化定时任务"""
    scheduler.add_job(
        check_subscriptions,
        'interval',
        minutes=interval_minutes,
        id='bili_query_check',
        replace_existing=True,
    )
    logger.info(f"B站订阅检查定时任务已启动（每 {interval_minutes} 分钟检查一次）")
