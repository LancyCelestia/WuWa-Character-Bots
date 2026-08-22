import asyncio
import contextlib
import os
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from nonebot import logger
from playwright.__main__ import main
from playwright._impl._errors import TargetClosedError
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from ..config import plugin_config
from ..utils import get_path
from .captcha_solver import CaptchaInfer
from .fonts_provider import fill_font

_browser: BrowserContext | None = None
_cdp_browser: Browser | None = None
_playwright: Playwright | None = None
_browser_lock: asyncio.Lock | None = None
_browser_lock_loop: asyncio.AbstractEventLoop | None = None
T = TypeVar("T")
mobile_js = Path(__file__).parent.joinpath("mobile.js")
WEB_DYNAMIC_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DEFAULT_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; RMX1911) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/100.0.4896.127 Mobile Safari/537.36"
)
DEFAULT_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def get_user_agent() -> str:
    if plugin_config.bililive_browser_ua:
        return plugin_config.bililive_browser_ua
    if plugin_config.bililive_screenshot_style.lower() == "mobile":
        return DEFAULT_MOBILE_USER_AGENT
    return DEFAULT_DESKTOP_USER_AGENT


def get_dynamic_api_headers(uid: int) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "referer": f"https://space.bilibili.com/{uid}/dynamic",
        "origin": "https://space.bilibili.com",
    }


async def _ensure_playwright() -> Playwright:
    global _playwright
    if _playwright is None:
        _playwright = await async_playwright().start()
    return _playwright


async def _apply_browser_headers(context: BrowserContext) -> None:
    await context.set_extra_http_headers(
        {
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )


def _get_browser_lock() -> asyncio.Lock:
    global _browser_lock, _browser_lock_loop
    loop = asyncio.get_running_loop()
    if _browser_lock is None or _browser_lock_loop is not loop:
        _browser_lock = asyncio.Lock()
        _browser_lock_loop = loop
    return _browser_lock


def _is_browser_healthy(context: BrowserContext) -> bool:
    try:
        browser = context.browser
        if browser is not None and not browser.is_connected():
            return False
        _ = context.pages
        return True
    except Exception:
        return False


async def _reset_browser() -> None:
    global _browser, _cdp_browser
    if _cdp_browser is not None:
        with contextlib.suppress(Exception):
            await _cdp_browser.close()
        _cdp_browser = None
    elif _browser is not None:
        with contextlib.suppress(Exception):
            await _browser.close()
    _browser = None


async def _with_browser_retry(
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    for attempt in range(2):
        try:
            return await coro_factory()
        except TargetClosedError:
            if attempt == 0:
                logger.warning("浏览器连接已断开，正在重试")
                async with _get_browser_lock():
                    await _reset_browser()
                continue
            raise
    raise RuntimeError("unreachable")


async def init_browser_cdp(endpoint: str) -> BrowserContext:
    global _browser, _cdp_browser
    logger.info(f"连接外部 Chromium：{endpoint}")
    playwright = await _ensure_playwright()
    cdp_browser = await playwright.chromium.connect_over_cdp(endpoint)
    _cdp_browser = cdp_browser
    if cdp_browser.contexts:
        browser_context = cdp_browser.contexts[0]
    else:
        browser_context = await cdp_browser.new_context(
            user_agent=get_user_agent(),
            device_scale_factor=2,
        )
    await _apply_browser_headers(browser_context)
    _browser = browser_context
    logger.info("外部 Chromium 已连接")
    return _browser


async def init_browser_playwright(
    proxy=plugin_config.bililive_proxy, **kwargs
) -> BrowserContext:
    logger.info("初始化 Playwright 内置浏览器")
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    global _browser
    playwright = await _ensure_playwright()
    browser_data = Path(get_path("browser"))
    browser_data.mkdir(parents=True, exist_ok=True)
    browser_context = await playwright.chromium.launch_persistent_context(
        browser_data,
        user_agent=get_user_agent(),
        device_scale_factor=2,
        timeout=plugin_config.bililive_dynamic_timeout * 1000,
        **kwargs,
    )
    if plugin_config.bililive_screenshot_style.lower() != "mobile":
        await browser_context.add_cookies(
            [
                {
                    "name": "hit-dyn-v2",
                    "value": "1",
                    "domain": ".bilibili.com",
                    "path": "/",
                }
            ]
        )
    await _apply_browser_headers(browser_context)
    _browser = browser_context
    return _browser


async def init_browser(proxy=plugin_config.bililive_proxy, **kwargs) -> BrowserContext:
    endpoint = plugin_config.bililive_chromium_endpoint
    if endpoint:
        try:
            return await init_browser_cdp(endpoint)
        except Exception as err:
            logger.warning(
                f"连接外部 Chromium 失败（{endpoint}），"
                f"将回退到 Playwright 内置浏览器：{err}"
            )
    return await init_browser_playwright(proxy=proxy, **kwargs)


async def get_browser() -> BrowserContext:
    async with _get_browser_lock():
        if _browser and _is_browser_healthy(_browser):
            return _browser
        if _browser:
            logger.warning("浏览器上下文已失效，正在重新连接")
            await _reset_browser()
        return await init_browser()


async def get_bilibili_cookies() -> dict[str, str]:
    browser = await get_browser()
    cookies = await browser.cookies([
        "https://www.bilibili.com/",
        "https://api.bilibili.com/",
    ])
    return {cookie["name"]: cookie["value"] for cookie in cookies}


async def get_user_dynamics_payload_in_browser(uid: int) -> dict:
    async def _fetch() -> dict:
        browser = await get_browser()
        page = await browser.new_page()
        api_headers = get_dynamic_api_headers(uid)
        try:
            await page.set_extra_http_headers(
                {
                    **api_headers,
                    "User-Agent": get_user_agent(),
                }
            )
            await page.goto(
                "https://www.bilibili.com/",
                wait_until="domcontentloaded",
                timeout=plugin_config.bililive_dynamic_timeout * 1000,
            )
            return await page.evaluate(
                """async ({ url, uid, headers }) => {
                    const response = await fetch(`${url}?host_mid=${uid}`, {
                        credentials: 'include',
                        headers,
                    });
                    return await response.json();
                }""",
                {"url": WEB_DYNAMIC_URL, "uid": str(uid), "headers": api_headers},
            )
        finally:
            with contextlib.suppress(Exception):
                await page.close()

    return await _with_browser_retry(_fetch)


async def get_dynamic_screenshot(
    dynamic_id,
    style=plugin_config.bililive_screenshot_style,
):
    """获取动态截图"""
    image: bytes | None = None
    err = ""
    for i in range(3):
        browser = await get_browser()
        page = await browser.new_page()
        try:
            # if style.lower() == "mobile":
            #     page, clip = await get_dynamic_screenshot_mobile(dynamic_id, page)
            # else:
            #     page, clip = await get_dynamic_screenshot_pc(dynamic_id, page)
            page, clip = await get_dynamic_screenshot_mobile(dynamic_id, page)
            clip["height"] = min(clip["height"], 32766)
            return (
                await page.screenshot(clip=clip, full_page=True, type="jpeg", quality=98),
                None,
            )
        except TargetClosedError:
            logger.warning(f"浏览器连接已断开，截图重试 {i + 1}/3")
            async with _get_browser_lock():
                await _reset_browser()
            err = "截图失败"
        except TimeoutError:
            logger.warning(f"截图超时，重试 {i + 1}/3")
            err = "截图超时"
        except Notfound:
            logger.error(f"动态 {dynamic_id} 不存在")
            err = "动态不存在"
        except AssertionError:
            logger.error(f"动态 {dynamic_id} 截图失败")
            err = "网页元素获取失败"
            image = await page.screenshot(full_page=True, type="jpeg", quality=80)
        except Exception as e:
            if "bilibili.com/404" in page.url:
                logger.error(f"动态 {dynamic_id} 不存在")
                err = "动态不存在"
                break
            elif "waiting until" in str(e):
                logger.error(f"动态 {dynamic_id} 截图超时")
                err = "截图超时"
            else:
                logger.exception(f"动态 {dynamic_id} 截图失败")
                err = "截图失败"
                with contextlib.suppress(Exception):
                    image = await page.screenshot(full_page=True, type="jpeg", quality=80)
        finally:
            with contextlib.suppress(Exception):
                await page.close()
    return image, err


async def get_dynamic_screenshot_mobile(dynamic_id, page: Page):
    """移动端动态截图"""
    url = f"https://m.bilibili.com/dynamic/{dynamic_id}"
    await page.set_viewport_size({"width": 460, "height": 780})
    await page.route(re.compile("^https://static.graiax/fonts/(.+)$"), fill_font)
    if plugin_config.bililive_captcha_address:
        captcha = CaptchaInfer(
            plugin_config.bililive_captcha_address, plugin_config.bililive_captcha_token
        )
        page = await captcha.solve_captcha(page, url)
    else:
        await page.goto(url, wait_until="networkidle")
    # 动态被删除或者进审核了
    if page.url == "https://m.bilibili.com/404":
        raise Notfound
    # await page.add_script_tag(
    #     content=
    #     # 去除打开app按钮
    #     "document.getElementsByClassName('m-dynamic-float-openapp')"
    #     ".forEach(v=>v.remove());"
    #     # 去除关注按钮
    #     "document.getElementsByClassName('dyn-header__following')"
    #     ".forEach(v=>v.remove());"
    #     # 修复字体与换行问题
    #     "const dyn=document.getElementsByClassName('dyn-card')[0];"
    #     "dyn.style.fontFamily='Noto Sans CJK SC, sans-serif';"
    #     "dyn.style.overflowWrap='break-word'"
    # )

    await page.wait_for_load_state(state="domcontentloaded")
    await page.wait_for_selector(
        ".b-img__inner, .dyn-header__author__face",
        state="visible",
    )

    await page.add_script_tag(path=mobile_js)

    await page.evaluate(
        f'setFont("{plugin_config.bililive_dynamic_font}", '
        f'"{plugin_config.bililive_dynamic_font_source}")'
        if plugin_config.bililive_dynamic_font
        else "setFont()"
    )
    big_image = "true" if plugin_config.bililive_dynamic_big_image else "false"
    await page.wait_for_function(f"getMobileStyle({big_image})")

    await page.wait_for_load_state("networkidle")
    await page.wait_for_load_state("domcontentloaded")

    await page.wait_for_timeout(
        1000 if plugin_config.bililive_dynamic_font_source == "remote" else 200
    )

    # 判断字体是否加载完成
    need_wait = ["imageComplete", "fontsLoaded"]
    await asyncio.gather(*[page.wait_for_function(f"{i}()") for i in need_wait])

    selector = ".opus-modules" if "opus" in page.url else ".dyn-card"
    card = await page.query_selector(selector)
    assert card
    clip = await card.bounding_box()
    assert clip
    return page, clip


async def get_dynamic_screenshot_pc(dynamic_id, page: Page):
    """电脑端动态截图"""
    url = f"https://t.bilibili.com/{dynamic_id}"
    await page.set_viewport_size({"width": 2560, "height": 1080})
    await page.goto(url, wait_until="networkidle")
    # 动态被删除或者进审核了
    if page.url == "https://www.bilibili.com/404":
        raise Notfound
    card = await page.query_selector(".card")
    assert card
    clip = await card.bounding_box()
    assert clip
    bar = await page.query_selector(".bili-dyn-action__icon")
    assert bar
    bar_bound = await bar.bounding_box()
    assert bar_bound
    clip["height"] = bar_bound["y"] - clip["y"]
    return page, clip


def install():
    """自动安装、更新 Chromium"""

    def restore_env():
        os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        if plugin_config.bililive_proxy:
            os.environ.pop("HTTPS_PROXY", None)
        if original_proxy is not None:
            os.environ["HTTPS_PROXY"] = original_proxy

    logger.info("检查 Chromium 更新")
    sys.argv = ["", "install", "chromium"]
    original_proxy = os.environ.get("HTTPS_PROXY")
    if plugin_config.bililive_proxy:
        os.environ["HTTPS_PROXY"] = plugin_config.bililive_proxy
    success = False
    try:
        main()
    except SystemExit as e:
        if e.code == 0:
            success = True
    if not success:
        restore_env()
        raise RuntimeError("未知错误，Chromium 下载失败")
    restore_env()


async def check_playwright_env():
    """检查 Playwright 依赖"""
    logger.info("检查 Playwright 依赖")
    try:
        async with async_playwright() as p:
            await p.chromium.launch()
    except Exception as err:
        raise ImportError(
            "加载失败，Playwright 依赖不全，"
            "解决方法：https://github.com/Akiyy-dev/nonebot-plugin-bililive/"
            "blob/master/docs/faq.md#playwright-依赖不全"
        ) from err


class Notfound(Exception):
    pass
