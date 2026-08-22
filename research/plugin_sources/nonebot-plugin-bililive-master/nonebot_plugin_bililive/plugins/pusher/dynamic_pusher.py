import asyncio
import contextlib
from datetime import datetime, timedelta
from time import monotonic

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_SCHEDULER_STARTED,
)
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11.message import MessageSegment
from playwright._impl._errors import TargetClosedError

from ...config import plugin_config
from ...database import DB as db
from ...database import dynamic_offset as offset
from ...libs.dynamic.web import (
    WebDynamicError,
    get_user_dynamics_web,
    parse_web_dynamic_payload,
)
from ...utils import (
    get_bilibili_cookies,
    get_dynamic_screenshot,
    get_user_dynamics_payload_in_browser,
    safe_send,
    scheduler,
)

WEB_REQUEST_BANNED_RETRY_SECONDS = 300
WEB_REQUEST_ERROR_RETRY_SECONDS = 600
dynamic_risk_control_until = {}
WEB_SKIP_DYNAMIC_TYPES = {
    "DYNAMIC_TYPE_LIVE_RCMD",
    "DYNAMIC_TYPE_LIVE",
    "DYNAMIC_TYPE_AD",
    "DYNAMIC_TYPE_BANNER",
}
WEB_DYNAMIC_TYPE_MESSAGES = {
    "DYNAMIC_TYPE_FORWARD": "转发了一条动态",
    "DYNAMIC_TYPE_WORD": "发布了新文字动态",
    "DYNAMIC_TYPE_DRAW": "发布了新图文动态",
    "DYNAMIC_TYPE_AV": "发布了新投稿",
    "DYNAMIC_TYPE_ARTICLE": "发布了新专栏",
    "DYNAMIC_TYPE_MUSIC": "发布了新音频",
}
DYNAMIC_FETCH_CONCURRENCY = 4
DYNAMIC_THROTTLE_SECONDS = 1
_dynamic_scheduler_stopping = False
_dynamic_listener_events = (
    EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_SCHEDULER_STARTED
)


def get_dynamic_id(dynamic, use_web_fallback: bool) -> int:
    return dynamic.dynamic_id


def get_dynamic_type(dynamic, use_web_fallback: bool):
    return dynamic.dynamic_type


def get_dynamic_author_name(dynamic, use_web_fallback: bool) -> str:
    return dynamic.author_name


def get_dynamic_type_message(dynamic_type, use_web_fallback: bool) -> str:
    return WEB_DYNAMIC_TYPE_MESSAGES.get(dynamic_type, "发布了新动态")


def should_skip_dynamic(dynamic_type, use_web_fallback: bool) -> bool:
    return dynamic_type in WEB_SKIP_DYNAMIC_TYPES


async def get_user_dynamics_with_web_fallback(uid: int) -> tuple[list, bool]:
    try:
        payload = await get_user_dynamics_payload_in_browser(uid)
        return parse_web_dynamic_payload(payload), True
    except WebDynamicError as browser_error:
        logger.debug(
            f"浏览器上下文动态接口获取失败，尝试直连 Web API：{uid} "
            f"{browser_error.code} {browser_error.msg}"
        )
    except TargetClosedError as browser_error:
        logger.warning(
            f"浏览器上下文已关闭，尝试直连 Web API：{uid} {browser_error}"
        )

    cookies = await get_bilibili_cookies()
    if not cookies:
        raise WebDynamicError(-1, "browser cookies unavailable")
    return (
        await get_user_dynamics_web(
            uid,
            cookies,
            proxy=plugin_config.bililive_proxy,
            user_agent=plugin_config.bililive_browser_ua or None,
            timeout=plugin_config.bililive_dynamic_timeout,
        ),
        True,
    )


async def process_dynamic_uid(uid: int):
    user = await db.get_user(uid=uid)
    if user is None:
        logger.warning(f"动态推送跳过异常订阅 UID：{uid}")
        return
    name = user.name

    retry_at = dynamic_risk_control_until.get(uid)
    if retry_at is not None:
        if retry_at > monotonic():
            logger.debug(f"动态接口风控冷却中，跳过 {name}（{uid}）")
            return
        del dynamic_risk_control_until[uid]

    logger.debug(f"爬取动态 {name}（{uid}）")
    use_web_fallback = False
    try:
        dynamics, use_web_fallback = await get_user_dynamics_with_web_fallback(uid)
    except WebDynamicError as e:
        retry_seconds = (
            WEB_REQUEST_BANNED_RETRY_SECONDS
            if e.code == -412
            else WEB_REQUEST_ERROR_RETRY_SECONDS
        )
        dynamic_risk_control_until[uid] = monotonic() + retry_seconds
        retry_minutes = max(retry_seconds // 60, 1)
        logger.warning(
            f"动态 Web 接口获取失败，{name}（{uid}）将在 "
            f"{retry_minutes} 分钟后重试：{e.code} {e.msg}"
        )
        return

    dynamic_risk_control_until.pop(uid, None)

    if not dynamics:
        return
    name = get_dynamic_author_name(dynamics[0], use_web_fallback)

    if uid not in offset:  # 已删除
        return
    elif offset[uid] == -1:  # 第一次爬取
        await db.set_dynamic_offset(
            uid,
            max(get_dynamic_id(item, use_web_fallback) for item in dynamics),
        )
        return

    dynamic = None
    for dynamic in sorted(
        dynamics,
        key=lambda x: get_dynamic_id(x, use_web_fallback),  # 动态从旧到新排列
    ):
        dynamic_id = get_dynamic_id(dynamic, use_web_fallback)
        dynamic_type = get_dynamic_type(dynamic, use_web_fallback)
        if dynamic_id > offset[uid]:
            logger.info(f"检测到新动态（{dynamic_id}）：{name}（{uid}）")
            image, err = await get_dynamic_screenshot(dynamic_id)
            url = f"https://t.bilibili.com/{dynamic_id}"
            if image is None:
                logger.debug(f"动态不存在，已跳过：{url}")
                return
            elif should_skip_dynamic(dynamic_type, use_web_fallback):
                logger.debug(f"无需推送的动态 {dynamic_type}，已跳过：{url}")
                await db.set_dynamic_offset(uid, dynamic_id)
                return
            message = (
                f"{name} {get_dynamic_type_message(dynamic_type, use_web_fallback)}：\n"
                + str(f"动态图片可能截图异常：{err}\n" if err else "")
                + MessageSegment.image(image)
                + f"\n{url}"
            )

            push_list = await db.get_push_list(uid, "dynamic")
            for sets in push_list:
                await safe_send(
                    bot_id=sets.bot_id,
                    send_type=sets.type,
                    type_id=sets.type_id,
                    message=message,
                    at=bool(sets.at) and plugin_config.bililive_dynamic_at,
                )

            await db.set_dynamic_offset(uid, dynamic_id)

    if dynamic:
        await db.update_user(uid, name)


async def dy_sched():
    """动态推送"""
    try:
        if not await db.wait_until_ready():
            logger.debug("数据库尚未初始化完成，跳过本轮动态推送")
            return

        uids = await db.get_uid_list("dynamic")
        if not uids:
            return

        logger.debug(f"爬取动态列表，总共 {len(uids)} 人")
        semaphore = asyncio.Semaphore(DYNAMIC_FETCH_CONCURRENCY)

        async def run_for_uid(uid: int):
            async with semaphore:
                await process_dynamic_uid(uid)

        await asyncio.gather(*(run_for_uid(uid) for uid in uids))
    except asyncio.CancelledError:
        if _dynamic_scheduler_stopping:
            raise
        logger.debug("动态推送任务已取消")


def _stop_dynamic_scheduler():
    global _dynamic_scheduler_stopping
    _dynamic_scheduler_stopping = True
    if plugin_config.bililive_dynamic_interval == 0:
        with contextlib.suppress(ValueError):
            scheduler.remove_listener(dynamic_lisener, _dynamic_listener_events)
    with contextlib.suppress(Exception):
        scheduler.remove_job("dynamic_sched")


def schedule_next_dynamic_job(*, immediate: bool = False):
    if _dynamic_scheduler_stopping or not scheduler.running:
        return
    if scheduler.get_job("dynamic_sched"):
        return
    delay = timedelta(0) if immediate else timedelta(seconds=DYNAMIC_THROTTLE_SECONDS)
    scheduler.add_job(
        dy_sched,
        id="dynamic_sched",
        next_run_time=datetime.now(scheduler.timezone) + delay,
    )


def dynamic_lisener(event):
    if hasattr(event, "job_id") and event.job_id != "dynamic_sched":
        return
    if event.code == EVENT_JOB_ERROR and isinstance(
        getattr(event, "exception", None), asyncio.CancelledError
    ):
        logger.debug("动态推送任务已取消，将重新调度")
    schedule_next_dynamic_job(immediate=event.code == EVENT_SCHEDULER_STARTED)


if plugin_config.bililive_dynamic_interval == 0:
    scheduler.add_listener(dynamic_lisener, _dynamic_listener_events)
else:
    scheduler.add_job(
        dy_sched,
        "interval",
        seconds=plugin_config.bililive_dynamic_interval,
        id="dynamic_sched",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=5,
    )

get_driver().on_shutdown(_stop_dynamic_scheduler)
