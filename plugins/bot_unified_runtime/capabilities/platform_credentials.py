"""平台登录凭证（Cookie）管理能力：状态查看与文本导入。

设计对标 nonebot-plugin-parser-lite 的"指令获取/使用登录凭证"：
- `cookie` / `cookie status`：按平台列出已存凭证的 cookie 名与到期时间（永不回显值）；
- `cookie import <平台> <Cookie 头>`：把 `a=1; b=2` 形式的 Cookie 头写进
  Netscape cookies.txt（BOT_COOKIES_FILE），下一次解析即热生效（解析链每次
  解析重建 provider）。导入成功只回显平台与 cookie 名清单。
仅管理员可用（门控在 matcher 规则层）。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from plugins.bot_unified_runtime.sources.parsers.cookies import (
    PLATFORM_COOKIE_DOMAINS,
    _resolve_relative_cookie_path,
    build_platform_cookie_provider,
)

_COMMAND_ALIASES = ("cookie", "凭证", "登录凭证")
# 统一命令格式：/bot <模块词:cookie> <功能词:status|import> [参数]
_COMMAND_PREFIX = "/bot "
_IMPORT_VERBS = ("import", "导入")

_DEFAULT_TTL_SECONDS = 180 * 86400
# 审计#28：cookies.txt 是读-判-写（读 existing → 判重 → append），
# 并发 import 同平台会产生重复行；全程持锁串行化。
# includeSubdomains 写死 TRUE 为有意保留：HTTP 头导入不含域属性，
# TRUE 与浏览器 Netscape 导出的主流值一致。
_COOKIE_FILE_LOCK = threading.Lock()


def is_cookie_command(text: str) -> bool:
    normalized = (text or "").strip().lower()
    for alias in _COMMAND_ALIASES:
        if normalized.startswith(f"{_COMMAND_PREFIX}{alias}") and (
            len(normalized) == len(f"{_COMMAND_PREFIX}{alias}")
            or normalized[len(f"{_COMMAND_PREFIX}{alias}"):].startswith(" ")
        ):
            return True
    return False


def parse_cookie_command(text: str) -> tuple[str, str, str] | None:
    """解析 `/bot cookie [status|import <平台> <Cookie头>]`。

    返回 (action, platform, header)；action ∈ {status, import}。
    省略功能词视为 status；import 省略参数时由调用方提示用法。
    """
    raw = (text or "").strip()
    if not raw.lower().startswith(_COMMAND_PREFIX):
        return None
    body = raw[len(_COMMAND_PREFIX):].strip()
    head = body.split(None, 1)
    if not head or head[0].lower() not in _COMMAND_ALIASES:
        return None
    rest = head[1].strip() if len(head) > 1 else ""
    lowered = rest.lower()
    for verb in _IMPORT_VERBS:
        if lowered == verb or lowered.startswith(f"{verb} "):
            after = rest[len(verb):].strip()
            parts = after.split(None, 1)
            if parts:
                return (
                    "import",
                    parts[0].strip().lower(),
                    parts[1].strip() if len(parts) > 1 else "",
                )
            return ("import", "", "")
    if not rest or lowered == "status" or lowered.startswith("status "):
        return ("status", "", "")
    if lowered == "expiry" or lowered.startswith(
        ("expiry ", "过期")
    ):
        return ("expiry", "", "")
    if lowered.startswith(("login", "check")):
        verb = lowered.split(None, 1)[0]
        after = rest[len(verb):].strip()
        return (verb, after.split(None, 1)[0].strip().lower() if after else "", "")
    # /bot cookie <未知功能词>：交给 import 分支按"缺平台"报错，或按 status 提示。
    return ("import", rest.split(None, 1)[0].strip().lower(), "")


def _parse_header_pairs(header: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in (header or "").replace("\n", ";").split(";"):
        if "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if name and value:
            pairs.append((name, value))
    return pairs


def cookie_status_text(config: object) -> str:
    """按平台列出已存凭证状态；只显示 cookie 名与到期日，不显示值。"""
    provider = build_platform_cookie_provider(
        getattr(config, "bot_cookies_file", "") or ""
    )
    now = int(time.time())
    lines: list[str] = ["平台凭证状态："]
    with_credentials = 0
    for platform in sorted(PLATFORM_COOKIE_DOMAINS):
        names = provider.key_names.get(platform) or []
        expires = provider.expires.get(platform, 0)
        if names:
            with_credentials += 1
            expiry_text = ""
            if expires > now:
                # 本地到期日本就是预期展示；astimezone 显式落地本地时区。
                expiry_text = "，到期 " + datetime.fromtimestamp(expires).astimezone().strftime(
                    "%Y-%m-%d"
                )
            lines.append(f"✅ {platform}：{len(names)} 项（{'、'.join(names[:6])}{'…' if len(names) > 6 else ''}{expiry_text}）")
        else:
            lines.append(f"⬜ {platform}：未配置")
    lines.append(f"共 {with_credentials}/{len(PLATFORM_COOKIE_DOMAINS)} 个平台已有凭证。")
    lines.append("导入：/bot cookie import <平台> <Cookie头>（管理员；如 /bot cookie import bilibili SESSDATA=...; bili_jct=...）")
    return "\n".join(lines)


def import_cookie_header(
    config: object,
    platform: str,
    header: str,
) -> str:
    """把 Cookie 头追加写入 Netscape cookies.txt；返回给用户的结果文本不含值。"""
    platform_entry = PLATFORM_COOKIE_DOMAINS.get(platform)
    if platform_entry is None:
        known = "、".join(sorted(PLATFORM_COOKIE_DOMAINS))
        return f"未知平台「{platform}」。支持的平台：{known}"
    platform_domains = platform_entry[0]
    pairs = _parse_header_pairs(header)
    if not pairs:
        return "Cookie 头解析失败：请用 `名=值; 名2=值2` 的形式（可直接从浏览器 F12 复制整行）。"
    cookie_path = _resolve_cookie_file(config)
    if cookie_path is None:
        return "未配置 BOT_COOKIES_FILE，无法写入凭证。"
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    primary_domain = platform_domains[0]
    expires = int(time.time()) + _DEFAULT_TTL_SECONDS
    with _COOKIE_FILE_LOCK:
        existing_names: set[str] = set()
        if cookie_path.exists():
            for line in cookie_path.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 7 and parts[0] in platform_domains:
                    existing_names.add(parts[5])
        rendered = [
            f"{primary_domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}"
            for name, value in pairs
            if name not in existing_names
        ]
        if not rendered:
            return f"平台 {platform} 的这些 Cookie 名已存在（同名不覆盖），未做修改。如需更新请先删除文件中的旧行。"
        with open(cookie_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(rendered) + "\n")
    return (
        f"✅ 已为 {platform} 写入 {len(rendered)} 项凭证（{'、'.join(name for name, _ in pairs if name not in existing_names)}），"
        "下一次解析即生效。值为空/重复的项已跳过。"
    )


def _resolve_cookie_file(config: object) -> Path | None:
    # 与 provider 同一解析规则：相对路径按 BOT_RUNTIME_DATA_DIR（env）解析，
    # 保证"写入的文件"与"读取的文件"始终是同一个。
    raw = str(getattr(config, "bot_cookies_file", "") or "").strip()
    if not raw:
        return None
    return _resolve_relative_cookie_path(Path(raw))



import random
import urllib.parse
import urllib.request

_QR_GENERATE_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
_QR_POLL_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_QR_SESSION_TTL = 600.0
_BILI_COOKIE_TTL = 180 * 86400

# 扫码登录已实现的平台 → (显示名, 入场白名单域)
_PLATFORM_LOGIN_QR = {"bilibili": ("bilibili", ".bilibili.com")}

# 扫码会话：短 key → {"platform", "qrcode_key", "qr_png", "created"}
_QR_SESSIONS: dict[str, dict] = {}
_QR_SESSION_CAP = 16


def login_methods_line(platform: str) -> str:
    """返回该平台支持的登录方式提示（诚实版）。"""
    if platform in _PLATFORM_LOGIN_QR:
        return "支持扫码登录：/bot cookie login " + platform
    return (
        "暂不支持自动登录（密码/短信需过平台人机验证，机器人无法代替人工）。"
        "请浏览器登录后导出 cookie，再 /bot cookie import 手动导入。"
    )


def cookie_login_start(config: object, platform: str) -> tuple[str, str, str]:
    """发起扫码登录，返回 (session_key, qr_png_path, text)。"""
    if platform not in _PLATFORM_LOGIN_QR:
        return (
            "",
            "",
            login_methods_line(platform)
            + "\n当前已支持扫码登录的平台：bilibili（其余平台逐步接入）。",
        )
    from plugins.bot_unified_runtime.sources.parsers.http_util import (
        http_get_json,
    )

    payload = http_get_json(
        _QR_GENERATE_API,
        referer="https://passport.bilibili.com/login",
        timeout=10,
    )
    data = (payload or {}).get("data") or {}
    qr_url = str(data.get("url") or "")
    qrcode_key = str(data.get("qrcode_key") or "")
    if not qr_url or not qrcode_key:
        return "", "", "B站登录接口响应异常，稍后再试。"
    session_key = f"{random.randint(0, 9999):04d}"
    while session_key in _QR_SESSIONS:
        session_key = f"{random.randint(0, 9999):04d}"
    png_path = _render_qr_png(qr_url, platform, session_key)
    _QR_SESSIONS[session_key] = {
        "platform": platform,
        "qrcode_key": qrcode_key,
        "created": time.time(),
    }
    # 清理过期会话
    now = time.time()
    for key in [k for k, v in _QR_SESSIONS.items() if now - v["created"] > _QR_SESSION_TTL]:
        _QR_SESSIONS.pop(key, None)
    while len(_QR_SESSIONS) > _QR_SESSION_CAP:
        _QR_SESSIONS.pop(next(iter(_QR_SESSIONS)), None)
    text = (
        f"已生成 {platform} 登录二维码（见图片）。请用 B站 App 扫码并确认，"
        f"完成后发送：/bot cookie check {platform}\n"
        f"（10 分钟内有效；也可以直接在手机浏览器打开二维码指向的链接确认）\n"
        f"回执编号：{session_key}"
    )
    return session_key, png_path, text


def _render_qr_png(content: str, platform: str, session_key: str) -> str:
    """二维码内容渲染为 PNG 落盘（qrcode 库已在依赖中）。失败返回空串。"""
    import tempfile

    try:
        import qrcode

        image = qrcode.make(content)
        path = tempfile.mktemp(prefix=f"login_{platform}_{session_key}_", suffix=".png")
        image.save(path)
        return path
    except Exception:  # noqa: BLE001 - 二维码渲染失败走链接兜底。
        return ""


def cookie_login_check(config: object, platform: str) -> str:
    """单次 poll：查询该平台最近一次扫码会话的结果。"""
    if platform not in _PLATFORM_LOGIN_QR:
        return f"{platform} 暂不支持扫码登录。" + login_methods_line(platform)
    session = next(
        (
            v
            for v in sorted(
                _QR_SESSIONS.values(), key=lambda v: v["created"], reverse=True
            )
            if v["platform"] == platform
        ),
        None,
    )
    if session is None:
        return "没有进行中的扫码登录。先发送 /bot cookie login " + platform + " 生成二维码。"
    if time.time() - session["created"] > _QR_SESSION_TTL:
        return "二维码已过期，请重新发送 /bot cookie login " + platform + "。"

    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(
        _QR_POLL_API + "?" + urllib.parse.urlencode({"qrcode_key": session["qrcode_key"]}),
        headers={"User-Agent": _DESKTOP_UA, "Referer": "https://passport.bilibili.com/"},
    )
    try:
        import json

        with opener.open(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
            set_cookies = response.headers.get_all("Set-Cookie") or []
    except Exception:  # noqa: BLE001 - 轮询失败按未确认处理。
        return "查询失败，稍后再试。"
    state_code = (payload or {}).get("data", {}).get("code")
    if state_code == 86038:
        return "二维码已过期，请重新发送 /bot cookie login " + platform + "。"
    if state_code in (86090, 86039):
        return "已扫码，等待你在手机上确认。"
    if state_code != 0:
        return f"登录未完成（code={state_code}），请重新扫码。"
    # 成功：Set-Cookie 提取 B站登录三件套（值与过期一并落盘）。
    wanted = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5")
    import email.utils

    cookie_path = _resolve_cookie_file(config)
    if cookie_path is None:
        return "未配置 BOT_COOKIES_FILE，无法写入凭证。"
    primary_domain = _PLATFORM_LOGIN_QR[platform][1]
    expires_default = int(time.time()) + _BILI_COOKIE_TTL
    rendered: list[str] = []
    names: list[str] = []
    for raw_cookie in set_cookies:
        parts = [chunk.strip() for chunk in raw_cookie.split(";")]
        if not parts or "=" not in parts[0]:
            continue
        name, _, value = parts[0].partition("=")
        name = name.strip()
        if name not in wanted:
            continue
        expires = expires_default
        for chunk in parts[1:]:
            if chunk.lower().startswith("expires="):
                try:
                    dt = email.utils.parsedate_to_datetime(chunk.split("=", 1)[1])
                    expires = int(dt.timestamp())
                except (TypeError, ValueError):
                    expires = expires_default
        rendered.append(
            f"{primary_domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}"
        )
        names.append(name)
    if not rendered:
        return "登录成功但未取到凭证 cookie，请重试。"
    with open(cookie_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(rendered) + "\n")
    for key in [
        k
        for k, v in _QR_SESSIONS.items()
        if v.get("qrcode_key") == session["qrcode_key"]
    ]:
        _QR_SESSIONS.pop(key, None)
    return (
        f"✅ {platform} 扫码登录成功，已写入凭证：{'、'.join(names)}。\n"
        "立即生效（解析链按 cookie 文件热加载），无需重启。"
    )


def cookie_expiry_rows(config: object, *, warn_days: int = 7) -> list[tuple]:
    """全部平台凭证的过期巡检数据。

    返回 [(platform, has_credentials, expires_epoch, state)]，
    state ∈ {"ok", "expiring", "expired", "missing"}。
    """
    provider = build_platform_cookie_provider(
        getattr(config, "bot_cookies_file", "") or ""
    )
    now = int(time.time())
    warn_horizon = now + warn_days * 86400
    rows: list[tuple] = []
    for platform in sorted(PLATFORM_COOKIE_DOMAINS):
        names = provider.key_names.get(platform) or []
        expires = provider.expires.get(platform, 0)
        if not names:
            rows.append((platform, False, 0, "missing"))
            continue
        if expires and expires <= now:
            rows.append((platform, True, expires, "expired"))
        elif expires and expires <= warn_horizon:
            rows.append((platform, True, expires, "expiring"))
        else:
            rows.append((platform, True, expires, "ok"))
    return rows


def cookie_expiry_report(config: object, *, warn_days: int = 7) -> str:
    """过期/临期平台的人类可读报告（无问题时返回空串）。"""
    lines: list[str] = []
    for platform, has_creds, expires, state in cookie_expiry_rows(
        config, warn_days=warn_days
    ):
        if state == "expired":
            lines.append(f"⛔ {platform}：凭证已过期，请重新导入")
        elif state == "expiring":
            days = max(0, (expires - int(time.time())) // 86400)
            lines.append(f"⚠️ {platform}：{days} 天后到期，建议尽快更新")
    if not lines:
        return ""
    return "平台凭证过期提醒：\n" + "\n".join(lines)
