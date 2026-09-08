"""平台登录凭证（Cookie）管理能力：状态查看与文本导入。

设计对标 nonebot-plugin-parser-lite 的"指令获取/使用登录凭证"：
- `cookie` / `cookie status`：按平台列出已存凭证的 cookie 名与到期时间（永不回显值）；
- `cookie import <平台> <Cookie 头>`：把 `a=1; b=2` 形式的 Cookie 头写进
  Netscape cookies.txt（BOT_COOKIES_FILE），下一次解析即热生效（解析链每次
  解析重建 provider）。导入成功只回显平台与 cookie 名清单。
仅管理员可用（门控在 matcher 规则层）。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from plugins.bot_unified_runtime.sources.parsers.cookies import (
    PLATFORM_COOKIE_DOMAINS,
    _resolve_relative_cookie_path,
    build_platform_cookie_provider,
)

_COMMAND_ALIASES = ("cookie", "凭证", "登录凭证", "登录状态")
_IMPORT_VERBS = ("import", "导入", "导入凭证")

_DEFAULT_TTL_SECONDS = 180 * 86400


def is_cookie_command(text: str) -> bool:
    normalized = (text or "").strip().lower()
    prefixes = ("/bot ", "")
    for alias in _COMMAND_ALIASES:
        for prefix in prefixes:
            if normalized == f"{prefix}{alias}" or normalized.startswith(f"{prefix}{alias} "):
                return True
    return False


def parse_cookie_command(text: str) -> tuple[str, str, str] | None:
    """解析指令 → (action, platform, header)；action ∈ {status, import}。"""
    raw = (text or "").strip()
    lowered = raw.lower()
    for prefix in ("/bot ", ""):
        for alias in _COMMAND_ALIASES:
            if lowered.startswith(f"{prefix}{alias}") or raw.startswith(f"{prefix}{alias}"):
                rest = raw[len(prefix) + len(alias):].strip()
                for verb in _IMPORT_VERBS:
                    verb_prefix = f"{verb} "
                    if rest.lower().startswith(verb_prefix) or rest.startswith(verb):
                        body = rest[len(verb_prefix) if rest.lower().startswith(verb_prefix) else len(verb):].strip()
                        parts = body.split(None, 1)
                        if parts:
                            return (
                                "import",
                                parts[0].strip().lower(),
                                parts[1].strip() if len(parts) > 1 else "",
                            )
                        return ("import", "", "")
                return ("status", "", "")
    return None


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
    lines.append("导入：cookie import <平台> <Cookie头>（管理员；如 cookie import bilibili SESSDATA=...; bili_jct=...）")
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
