"""平台扫码登录（Playwright 官方登录页模式）。

借鉴 MediaCrawler（30K+ Star）的成熟做法：不做任何接口逆向，直接用
Playwright 打开平台**官方登录页**（页面自带扫码二维码/手机号入口），管理员
用手机 App 扫码后，浏览器上下文即持有登录态；轮询 ``context.cookies()``
检测目标登录 cookie 出现，即可导出全部平台域 cookie 追加写入 Netscape
cookies.txt——对任意平台通用，不依赖逆向接口的稳定性。

与 B站二维码 API 方案（platform_credentials.bilibili）互补：B站走公开
qrcode API（无需浏览器），其余平台走本模块的官方登录页模式。
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# 平台 → 登录页/成功标志 cookie/域后缀/App 提示。
# success_cookie 是该平台"登录后必出现、未登录必没有"的 cookie 名。
LOGIN_PAGES: dict[str, dict[str, str]] = {
    "xiaohongshu": {
        "login_url": "https://www.xiaohongshu.com/",
        "success_cookie": "web_session",
        "domain_suffix": ".xiaohongshu.com",
        "app_hint": "小红书 App",
    },
    "weibo": {
        "login_url": "https://weibo.com/login.php",
        "success_cookie": "SUB",
        "domain_suffix": ".weibo.com",
        "app_hint": "微博 App",
    },
    "douyin": {
        "login_url": "https://www.douyin.com/",
        "success_cookie": "sessionid",
        "domain_suffix": ".douyin.com",
        "app_hint": "抖音 App",
    },
    "zhihu": {
        "login_url": "https://www.zhihu.com/signin?next=%2F",
        "success_cookie": "z_c0",
        "domain_suffix": ".zhihu.com",
        "app_hint": "知乎 App",
    },
    "kuaishou": {
        "login_url": "https://www.kuaishou.com/",
        "success_cookie": "kuaishou.server.webday7_st",
        "domain_suffix": ".kuaishou.com",
        "app_hint": "快手 App",
    },
}

# 会话状态：platform → 共享 dict（线程安全：字段赋值原子，读取方容忍旧值）。
_LOGIN_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_TIMEOUT = 180.0
_SCREENSHOT_POLL_SECONDS = 3.0


def playwright_login_platforms() -> tuple[str, ...]:
    return tuple(sorted(LOGIN_PAGES))


def login_session_state(platform: str) -> dict[str, Any] | None:
    with _SESSIONS_LOCK:
        session = _LOGIN_SESSIONS.get(platform)
        return dict(session) if session else None


def clear_login_session(platform: str) -> None:
    with _SESSIONS_LOCK:
        _LOGIN_SESSIONS.pop(platform, None)


def start_playwright_login(platform: str, *, screenshots_dir: str = "") -> dict[str, Any]:
    """启动后台扫码会话，立即返回（不阻塞调用方）。

    返回会话 dict：state ∈ {starting, waiting_scan, ok, timeout, error}；
    screenshot 路径就绪后填入。重复发起会先终止旧会话。
    """
    spec = LOGIN_PAGES.get(platform)
    if spec is None:
        return {"state": "unsupported"}
    with _SESSIONS_LOCK:
        old = _LOGIN_SESSIONS.get(platform)
        if old is not None:
            old["stop"] = True
        session: dict[str, Any] = {
            "platform": platform,
            "state": "starting",
            "screenshot": "",
            "cookies": [],
            "started": time.time(),
            "stop": False,
        }
        _LOGIN_SESSIONS[platform] = session

    def _run() -> None:
        try:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            try:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(user_agent=_DESKTOP_UA)
                page = context.new_page()
                page.goto(
                    spec["login_url"], timeout=30_000, wait_until="domcontentloaded"
                )
                shot_dir = Path(screenshots_dir) if screenshots_dir else Path(
                    tempfile.gettempdir()
                )
                shot_dir.mkdir(parents=True, exist_ok=True)
                shot_path = shot_dir / f"login_{platform}.png"
                deadline = time.time() + _SESSION_TIMEOUT
                session["state"] = "waiting_scan"
                while time.time() < deadline:
                    if session.get("stop"):
                        session["state"] = "cancelled"
                        return
                    page.screenshot(path=str(shot_path), full_page=False)
                    session["screenshot"] = str(shot_path)
                    cookies = context.cookies()
                    hit = any(
                        cookie.get("name") == spec["success_cookie"]
                        for cookie in cookies
                    )
                    if hit:
                        session["cookies"] = [
                            cookie
                            for cookie in cookies
                            if str(cookie.get("domain", "")).endswith(
                                spec["domain_suffix"]
                            )
                        ]
                        session["state"] = "ok"
                        return
                    time.sleep(_SCREENSHOT_POLL_SECONDS)
                session["state"] = "timeout"
            finally:
                browser.close()
                pw.stop()
        except Exception as exc:  # noqa: BLE001 - 后台线程失败落在状态里。
            session["state"] = "error"
            session["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=_run, name=f"qr-login-{platform}", daemon=True)
    thread.start()
    return session


def collect_login_cookies(platform: str) -> list[dict[str, str]]:
    """登录成功后取该平台全部 cookie（Netscape 行所需字段）。"""
    with _SESSIONS_LOCK:
        session = _LOGIN_SESSIONS.get(platform) or {}
        cookies = session.get("cookies") or []
    return [
        {
            "domain": str(cookie.get("domain", "")),
            "name": str(cookie.get("name", "")),
            "value": str(cookie.get("value", "")),
            "path": str(cookie.get("path", "/")) or "/",
            "expires": str(int(float(cookie.get("expires", 0) or 0))),
        }
        for cookie in cookies
    ]
