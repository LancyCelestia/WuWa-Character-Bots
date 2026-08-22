import asyncio
import contextlib
import datetime
import re
import sys
from typing import Annotated

import httpx
import nonebot
import nonebot_plugin_localstore as store
from nonebot import logger
from nonebot import on_command as _on_command
from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
    NetworkError,
)
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg, RawCommand
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ..config import plugin_config

DATA_DIR = store.get_plugin_data_dir()


def get_data_dir():
    """获取插件数据目录。"""
    return DATA_DIR


def get_path(*other):
    """获取插件数据文件绝对路径。"""
    return str(get_data_dir().joinpath(*other))


async def handle_uid(
    matcher: Matcher,
    command_arg: Annotated[Message, CommandArg()],
):
    if command_arg.extract_plain_text().strip():
        matcher.set_arg("uid", command_arg)


async def uid_check(
    matcher: Matcher,
    uid: str = ArgPlainText("uid"),
):
    uid = uid.strip()
    if extract := await uid_extract(uid):
        uid = extract
    else:
        await matcher.finish(
            "未找到该 UP，请输入正确的 UP 群内昵称、UP 名、UP UID或 UP 首页链接"
        )
    matcher.set_arg("uid", Message(uid))


async def b23_extract(text: str):
    if "b23.tv" not in text and "b23.wtf" not in text:
        return None
    if not (b23 := re.compile(r"b23.(tv|wtf)[\\/]+(\w+)").search(text)):
        return None
    try:
        url = f"https://b23.tv/{b23[2]}"
        for _ in range(3):
            with contextlib.suppress(Exception):
                async with httpx.AsyncClient(
                    proxy=plugin_config.bililive_proxy
                ) as client:
                    resp = await client.get(url, follow_redirects=True)
                break
        else:
            return None
        url = resp.url
        logger.debug(f"b23.tv url: {url}")
        return str(url)
    except TypeError:
        return None


async def search_user(keyword: str):
    """
    搜索用户
    """
    url = "https://api.bilibili.com/x/web-interface/search/type"
    data = {"keyword": keyword, "search_type": "bili_user"}
    async with httpx.AsyncClient(
        proxy=plugin_config.bililive_proxy,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        timeout=20,
        follow_redirects=True,
    ) as client:
        response = await client.get(url, params=data)
    payload = response.json()
    logger.debug(payload)
    return payload.get("data")


async def get_user_name_by_uid(uid: int | str) -> str | None:
    """通过较稳定的 card 接口获取用户昵称"""
    url = "https://api.bilibili.com/x/web-interface/card"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com/",
    }
    async with httpx.AsyncClient(
        proxy=plugin_config.bililive_proxy,
        headers=headers,
        timeout=20,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url, params={"mid": uid})
    data = resp.json()
    if data.get("code") != 0:
        return None
    return data.get("data", {}).get("card", {}).get("name")


async def uid_extract(text: str):
    logger.debug(f"[UID Extract] Original Text: {text}")
    b23_msg = await b23_extract(text) if "b23.tv" in text else None
    message = b23_msg or text
    logger.debug(f"[UID Extract] b23 extract: {message}")
    pattern = re.compile("^[0-9]*$|bilibili.com/([0-9]*)")
    if match := pattern.search(message):
        logger.debug(f"[UID Extract] Digit or Url: {match}")
        match = match[1] or match[0]
        return str(match)
    elif message.startswith("UID:"):
        pattern = re.compile("^\\d+")
        if match := pattern.search(message[4:]):
            logger.debug(f"[UID Extract] UID: {match}")
            return str(match[0])
    else:
        text_u = text.strip(""""'“”‘’""")
        if text_u != text:
            logger.debug(f"[UID Extract] Text is a Quoted Digit: {text_u}")
        logger.debug(f"[UID Extract] Searching UID in BiliBili: {text_u}")
        resp = await search_user(text_u)
        logger.debug(f"[UID Extract] Search result: {resp}")
        if resp and resp["numResults"]:
            for result in resp["result"]:
                if result["uname"] == text_u:
                    logger.debug(f"[UID Extract] Found User: {result}")
                    return str(result["mid"])
        logger.debug("[UID Extract] No User found")


async def permission_check(
    bot: Bot, event: GroupMessageEvent | PrivateMessageEvent
):
    from ..database import DB as db

    if isinstance(event, PrivateMessageEvent):
        if event.sub_type == "group":  # 不处理群临时会话
            raise FinishedException
        return
    if isinstance(event, GroupMessageEvent):
        if not await db.wait_until_ready():
            await bot.send(event, "数据库尚未初始化完成，请稍后再试")
            raise FinishedException
        if not await db.get_group_admin(event.group_id):
            return
        if await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event):
            return
    await bot.send(event, "权限不足，目前只有管理员才能使用")
    raise FinishedException


async def group_only(
    matcher: Matcher,
    event: PrivateMessageEvent,
    command: Annotated[str, RawCommand()],
):
    await matcher.finish(f"只有群里才能{command}")


def to_me():
    if plugin_config.bililive_to_me:
        from nonebot.rule import to_me

        return to_me()

    async def _to_me() -> bool:
        return True

    return Rule(_to_me)


def calc_time_total(t):
    t = int(t * 1000)
    if t < 5000:
        return f"{t} 毫秒"

    timedelta = datetime.timedelta(seconds=t // 1000)
    day = timedelta.days
    hour, mint, sec = tuple(int(n) for n in str(timedelta).split(",")[-1].split(":"))

    total = ""
    if day:
        total += f"{day} 天 "
    if hour:
        total += f"{hour} 小时 "
    if mint:
        total += f"{mint} 分钟 "
    if sec and not day and not hour:
        total += f"{sec} 秒 "
    return total


async def safe_send(bot_id, send_type, type_id, message, at=False):
    """发送出现错误时, 尝试重新发送, 并捕获异常且不会中断运行"""

    async def _safe_send(bot, send_type, type_id, message):
        result = await bot.call_api(
            f"send_{send_type}_msg",
            **{
                "message": message,
                "user_id" if send_type == "private" else "group_id": type_id,
            },
        )
        return result

    bots = nonebot.get_bots()
    bot = bots.get(str(bot_id))
    if bot is None:
        logger.error(f"推送失败，Bot（{bot_id}）未连接，尝试使用其他 Bot 推送")
        for bot_id, bot in bots.items():
            if at and (await bot.get_group_at_all_remain(group_id=type_id))["can_at_all"]:
                message = MessageSegment.at("all") + message
            try:
                result = await _safe_send(bot, send_type, type_id, message)
                logger.info(f"尝试使用 Bot（{bot_id}）推送成功")
                return result
            except Exception:
                continue
        logger.error("尝试失败，所有 Bot 均无法推送")
        return

    if at and (await bot.get_group_at_all_remain(group_id=type_id))["can_at_all"]:
        message = MessageSegment.at("all") + message

    try:
        return await _safe_send(bot, send_type, type_id, message)
    except ActionFailed as e:
        if e.info["msg"] == "GROUP_NOT_FOUND":
            from ..database import DB as db

            await db.delete_sub_list(type="group", type_id=type_id)
            await db.delete_group(id=type_id)
            logger.error(f"推送失败，群（{type_id}）不存在，已自动清理群订阅列表")
        elif e.info["msg"] == "SEND_MSG_API_ERROR":
            url = (
                "https://github.com/Akiyy-dev/nonebot-plugin-bililive/blob/master/"
                "docs/faq.md#机器人不发消息也没反应"
            )
            logger.error(f"推送失败，账号可能被风控（{url}），错误信息：{e.info}")
        else:
            logger.error(f"推送失败，未知错误，错误信息：{e.info}")
    except NetworkError as e:
        logger.error(f"推送失败，请检查网络连接，错误信息：{e.msg}")


async def get_type_id(event: MessageEvent):
    return event.group_id if isinstance(event, GroupMessageEvent) else event.user_id


def check_proxy():
    """检查代理是否有效"""
    if plugin_config.bililive_proxy:
        logger.info("检查代理是否有效")
        try:
            with httpx.Client(proxy=plugin_config.bililive_proxy, timeout=2) as client:
                client.get("https://icanhazip.com/")
        except Exception as err:
            raise RuntimeError(
                "加载失败，代理无法连接，请检查 BILILIVE_PROXY 后重试"
            ) from err


def on_startup():
    """安装依赖并检查当前环境是否满足运行条件"""
    if plugin_config.fastapi_reload and sys.platform == "win32":
        raise ImportError(
            "加载失败，Windows 必须设置 FASTAPI_RELOAD=false 才能正常运行 BiliLive"
        )
    try:  # 如果开启 realod 只在第一次运行
        asyncio.get_running_loop()
    except RuntimeError:
        from .browser import check_playwright_env, install

        check_proxy()
        if plugin_config.bililive_chromium_endpoint:
            logger.info(
                "已配置 BILILIVE_CHROMIUM_ENDPOINT，"
                "将优先连接外部 Chromium，跳过内置 Chromium 安装"
            )
        else:
            install()
            try:
                asyncio.get_event_loop().run_until_complete(check_playwright_env())
            except ImportError as err:
                logger.warning(
                    "Playwright 运行环境不完整，已跳过启动时强校验；"
                    f"涉及截图/浏览器能力时可能不可用。错误：{err}"
                )
        DATA_DIR.mkdir(parents=True, exist_ok=True)


def on_command(cmd, *args, **kwargs):
    return _on_command(plugin_config.bililive_command_prefix + cmd, *args, **kwargs)

from nonebot_plugin_apscheduler import scheduler  # noqa

from .browser import (  # noqa
    get_bilibili_cookies,
    get_dynamic_screenshot,
    get_user_dynamics_payload_in_browser,
)
