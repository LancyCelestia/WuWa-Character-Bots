import aiohttp
import asyncio
import json
import os
import re

from typing import Literal
from nonebot import get_driver, logger, on_message, on_regex
from nonebot_plugin_htmlrender import get_new_page
from nonebot_plugin_localstore import get_plugin_cache_dir, get_plugin_config_file
from nonebot.adapters.onebot.v11 import Event, Message, MessageSegment
from nonebot.matcher import Matcher
from aiohttp import web

from ..modules.bilibili_apis import BilibiliApis
from ..renderer.bilibili_comment import BilibiliCommentRenderer
from ..config import config

driver = get_driver()

# 通用配置从 envConfig 读取
envConfig = get_driver().config
SUPERUSERS = list(envConfig.superusers)

# 插件配置从 config 读取
whitelist = config.analysis_whitelist
group_whitelist = config.analysis_group_whitelist
blacklist = config.analysis_blacklist
group_blacklist = config.analysis_group_blacklist
group_strategies = config.analysis_group_strategies

bili_helper_tmp_dir= get_plugin_cache_dir()

cookie_store_name = "cookie_store.json"
cookie_store_path = get_plugin_config_file(cookie_store_name)
def write_cookie(config: dict):
    try:
        with open(cookie_store_path, "w") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info('配置 {} 写入成功'.format(cookie_store_name))
        return True
    except Exception as e:
        logger.info('配置 {} 写入失败: {}'.format(cookie_store_name, e))
        return False
    
def read_cookie():
    config = { 'value': '' }
    try:
        with open(cookie_store_path, "r") as f:
            config = json.load(f)
        logger.info('配置 {} 读取成功'.format(cookie_store_name))
    except Exception as e:
        logger.info('配置 {} 为空或格式有误: {}'.format(cookie_store_name, e))
        logger.info('准备创建默认配置...')
        write_cookie(config)
    return config

cookie_store = read_cookie()
# print('Loaded cookie:', cookie_store)

bili_apis = BilibiliApis(
    cookie = cookie_store.get('value', ''),
)

def get_group_id(event: Event) -> str:
    return str(
        getattr(event, "group_id", None)
        if hasattr(event, "group_id")
        else getattr(event, "channel_id", None)
        if hasattr(event, "channel_id")
        else None
    )

async def is_allowed(event: Event) -> bool:
    user_id = str(event.get_user_id())
    group_id = get_group_id(event)

    if user_id in whitelist or group_id in group_whitelist:
        return True

    if len(whitelist) > 0 or len(group_whitelist) > 0:
        return False

    if user_id in blacklist or group_id in group_blacklist:
        return False

    return True

analysis_bili = on_message(
    rule=is_allowed,
    block=False,
    priority=8,
)

@analysis_bili.handle()
async def handle_analysis(event: Event, matcher: Matcher) -> None:

    async def fallback_bili_url(url: str, matcher: Matcher):
        await matcher.send(f"检测到B站链接: {url}")
        matcher.stop_propagation()

    message = event.get_message()
    bili_url = None
    mode: Literal["detail+comments", "link+comments", None] = None

    # 先在小程序段里找
    for seg in message:
        if (seg.type == "json"):
            json_str = str(seg.data.get("data", {}))
            data = json.loads(json_str)

            app = data.get("app", "")
            meta = data.get("meta", {})
            if re.match(r"^com\.tencent\.miniapp(_|\.|$)", app):
                detail = None
                for k, v in meta.items():
                    if k.startswith("detail_"):
                        detail = v
                        break
                if not detail:
                    return
                url = detail.get("qqdocurl", "")
                logger.info(f"解析到小程序链接: {url}")
                if not url or not re.match(r"^https?://b23\.tv", url):
                    return
                bili_url = url
                mode = "link+comments"
                break
            if re.match(r"^com\.tencent\.tuwen(\.|$)", app):
                news = meta.get("news", {})
                url = news.get("jumpUrl", "")
                logger.info(f"解析到图文链接: {url}")
                if not url or not re.match(r"^https?://b23\.tv", url):
                    return
                bili_url = url
                mode = "detail+comments"
                break

    # 如果没有在小程序里找到，就在纯文本里找
    if not bili_url:
        text = event.get_plaintext().strip()
        bili_url = bili_apis.get_url_from_text(text)
        if bili_url:
            mode = 'detail+comments'

    # 如果还是没有找到，就直接返回
    if not bili_url:
        return

    is_info_sent = False
    try:
        mode_str = str(mode)
        matcher.stop_propagation()
        group_id = get_group_id(event)
        strategy = group_strategies.get(group_id, None)
        def is_mode_allowed(m: str) -> bool:
            if not strategy:
                return True
            return m in strategy
        # url = quote(bili_url)
        vids = await bili_apis.get_id_from_url(bili_url)
        if not vids:
            logger.warning(f"无法从链接中提取ID: {bili_url}")
            return
        logger.debug(f"提取到的ID: {vids}")
        bvid = vids.get("bv", "") if vids else ""
        info = await bili_apis.video_info_api(bvid=bvid).call()
        info_data = info.get("data", {})
        if is_mode_allowed("detail") and "detail" in mode_str:
            def number_readable(num: int) -> str:
                if num >= 1_0000_0000: return f"{num / 1_0000_0000:.1f}亿"
                elif num >= 1_0000: return f"{num / 1_0000:.1f}万"
                else: return str(num)

            def format_duration(seconds: int) -> str:
                if seconds < 60:
                    return f"00:{seconds:02d}"
                elif seconds < 3600:
                    minutes = seconds // 60
                    seconds = seconds % 60
                    return f"{minutes:02d}:{seconds:02d}"
                else:
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    seconds = seconds % 60
                    return f"{hours}:{minutes:02d}:{seconds:02d}"

            title = info_data.get("title", "未知标题")
            cover_url = info_data.get("pic", "")
            artist = info_data.get("owner", {}).get("name", "未知作者")
            type_name = info_data.get("tname", "未知分区")
            stat = info_data.get("stat", {})
            play_count = number_readable(stat.get("view", 0))
            # danmaku_count = number_readable(stat.get("danmaku", 0))
            like_count = number_readable(stat.get("like", 0))
            coin_count = number_readable(stat.get("coin", 0))
            # favorite_count = number_readable(stat.get("favorite", 0))
            duration = format_duration(info_data.get("duration", 0))
            desc = info_data.get("desc", "")

            msg_seg = [
                MessageSegment.text(f'{title}\n')
            ]

            try:
                if cover_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(cover_url, timeout=10) as resp:
                            cover_img = await resp.read()
                            msg_seg.append(MessageSegment.image(cover_img))
            except Exception as e:
                logger.warning(f"获取封面失败: {e}")

            info_text = f"👤 {artist}\n" \
                        f"🔖 {type_name}  📼 {duration}\n" \
                        f"▶️ {play_count}  👍 {like_count}  🪙 {coin_count}"
            msg_seg.append(MessageSegment.text(info_text))

            if desc:
                if len(desc) > 300:
                    desc = desc[:300] + "..."
                desc_lines = desc.splitlines()
                if len(desc_lines) > 3:
                    desc = "\n".join(desc_lines[:3]).rstrip("...") + "..."
                msg_seg.append(MessageSegment.text(f"\nℹ️ {desc}"))
            await matcher.send(Message(msg_seg))
            is_info_sent = True
        if is_mode_allowed("link") and "link" in mode_str:
            bvid = info_data.get("bvid", "")
            new_url = f"https://b23.tv/{bvid}" if bvid else bili_url
            await matcher.send(f"解析到B站链接: {new_url}")
            is_info_sent = True
        if is_mode_allowed("comments") and "comments" in mode_str:
            tmp_name = f"{int(event.time)}_{event.get_session_id()}"
            oid = str(info_data.get("aid", ""))
            comments = await bili_apis.get_comments_api(oid=oid, type=1, next_offset="").call()
            comments_html = BilibiliCommentRenderer.render_html(info, comments)
            comments_path = os.path.join(bili_helper_tmp_dir, f"{tmp_name}.html")
            with open(comments_path, "w", encoding="utf-8") as f:
                f.write(comments_html)
            logger.info(f"评论页已保存到 {comments_path}")
            async with get_new_page(
                device_scale_factor=1.0,
            ) as page:
                comments_full_path = os.path.abspath(comments_path)
                await page.goto("file://" + comments_full_path)
                await page.wait_for_load_state("networkidle")
                comments_img_path = os.path.join(bili_helper_tmp_dir, f"{tmp_name}.jpg")
                await page.screenshot(path=comments_img_path, full_page=True, type="jpeg", quality=80)
                logger.info(f"评论截图已保存到 {comments_img_path}")
                comments_img = open(comments_img_path, "rb").read()
                meg = Message(MessageSegment.image(comments_img))
                await matcher.send(meg)
                # 清理临时文件
                os.remove(comments_path)
                os.remove(comments_img_path)
    except Exception as e:
        logger.error(f"处理B站链接失败: {e}")
        if is_mode_allowed("link") and "link" in mode_str and not is_info_sent:
            await fallback_bili_url(bili_url, matcher)
    pass

set_cookie_pattern = rf"^设置B站Cookie\s*(.+)?$"
set_cookie_sniffer = on_regex(set_cookie_pattern, flags=re.DOTALL, priority=5, block=True)
@set_cookie_sniffer.handle()
async def handle_set_cookie(event: Event, matcher: Matcher) -> None:
    user_id = str(event.get_user_id())
    if not user_id in SUPERUSERS:
        return
    text = event.get_plaintext().strip()
    m = re.match(set_cookie_pattern, text, flags=re.DOTALL)
    if not m:
        return
    cookie_value = m.group(1).strip() if m.group(1) else ""
    if not cookie_value:
        await matcher.send("请提供Cookie内容")
        return
    cookie_store['value'] = cookie_value
    write_cookie(cookie_store)
    bili_apis.set_cookie(cookie_value)
    await matcher.send("B站Cookie已更新")
