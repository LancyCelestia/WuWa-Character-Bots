"""平台 Cookie 提供方：从 Netscape 格式 cookies.txt 提取各平台 Cookie 头。

安全规则（与 sources/credentials.py 一致）：

- 只加载本模块白名单内的平台域名，其余一律丢弃；
- 值只在解析请求的 transport 边界使用，不进日志/审计/消息；
- 输出只暴露「平台 → 关键 cookie 名列表」，绝不打印值。

配置：``BOT_COOKIES_FILE=data/platform_cookies.txt``（Netscape 格式，
浏览器扩展导出）。加载失败或文件缺失时返回空 cookie（解析自动降级，
不会让链路报错）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

# 平台 → 收集的域名（子域都归并到平台键下）+ 该平台的关键 cookie 名。
PLATFORM_COOKIE_DOMAINS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "bilibili": ((".bilibili.com", "bilibili.com"), ("SESSDATA", "DedeUserID", "bili_jct")),
    "xiaohongshu": ((".xiaohongshu.com", "xiaohongshu.com"), ("web_session", "a1", "id_token", "websectiga")),
    "douyin": ((".douyin.com", "douyin.com"), ("ttwid", "odin_tt", "passport_csrf_token", "sessionid", "sessionid_ss")),
    "qqmusic": ((".qq.com", "qq.com", ".y.qq.com", "y.qq.com"), ("p_uin", "psrf_musickey", "psrf_qqaccess_token", "psrf_qqopenid", "uin", "skey")),
    "netease": ((".music.163.com", "music.163.com"), ("MUSIC_U", "MUSIC_A", "MUSIC_R_T", "__csrf", "JSESSIONID-WYYY")),
    "kuwo": ((".kuwo.cn", "kuwo.cn"), ("kw_token", "Hm_lvt_cdb524f42f0ce19b169a8071123a4797")),
    "kugou": ((".kugou.com", "kugou.com"), ("kg_mid", "userid", "token", "dfid")),
    "twitter": ((".x.com", "x.com", ".twitter.com", "twitter.com"), ("auth_token", "ct0")),
    "youtube": ((".youtube.com", "youtube.com"), ("LOGIN_INFO", "SID", "HSID", "SSID")),
    "kurobbs": ((".kurobbs.com", "kurobbs.com"), ("user_token", "token")),
    "skland": ((".skland.com", "skland.com"), ()),
    "miyoushe": ((".miyoushe.com", "miyoushe.com", ".bbs.miyoushe.com", "bbs.miyoushe.com"), ()),
}


@dataclass(frozen=True)
class CookieEntry:
    domain: str
    name: str
    value: str
    path: str = "/"
    expires: int = 0


@dataclass
class PlatformCookieProvider:
    """从 Netscape cookies.txt 构建的平台 Cookie 头集合。"""

    headers: dict[str, str] = field(default_factory=dict)
    key_names: dict[str, list[str]] = field(default_factory=dict)
    expires: dict[str, int] = field(default_factory=dict)

    def cookie_header(self, platform: str) -> str:
        return self.headers.get(platform, "")

    def has_cookie(self, platform: str) -> bool:
        return bool(self.headers.get(platform, ""))

    def summary(self) -> dict[str, list[str]]:
        """只暴露 cookie 名，不暴露值。"""
        return dict(self.key_names)

    def earliest_expires(self, platform: str) -> int:
        return self.expires.get(platform, 0)


def parse_netscape_cookie_file(path: str | Path) -> list[CookieEntry]:
    entries: list[CookieEntry] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, flag, cookie_path, secure, expires_raw, name, value = parts[:7]
            try:
                expires = int(expires_raw)
            except ValueError:
                expires = 0
            entries.append(
                CookieEntry(
                    domain=domain,
                    name=name,
                    value=value,
                    path=cookie_path or "/",
                    expires=expires,
                )
            )
    return entries


def build_platform_cookie_provider(path: str | Path | None) -> PlatformCookieProvider:
    provider = PlatformCookieProvider()
    if not path:
        return provider
    cookie_path = Path(path)
    if not cookie_path.is_absolute():
        # 相对路径两级回退：当前目录 → 项目根（保证从任意目录运行可用）。
        cwd_candidate = Path.cwd() / cookie_path
        if cwd_candidate.exists():
            cookie_path = cwd_candidate
        else:
            project_root = Path(__file__).resolve().parents[4]
            cookie_path = project_root / cookie_path
    if not cookie_path.exists():
        return provider
    try:
        entries = parse_netscape_cookie_file(cookie_path)
    except OSError:
        return provider
    now = int(time.time())
    for platform, (domains, _key_names) in PLATFORM_COOKIE_DOMAINS.items():
        matched = [
            entry
            for entry in entries
            if entry.domain in domains
            and (not entry.expires or entry.expires > now)
            and entry.name.strip()
        ]
        if not matched:
            continue
        # 同名 cookie 优先取更具体域名/更长路径的最新值。
        best: dict[str, CookieEntry] = {}
        for entry in matched:
            existing = best.get(entry.name)
            if existing is None or (len(entry.path) >= len(existing.path) and entry.expires >= existing.expires):
                best[entry.name] = entry
        ordered = sorted(best.values(), key=lambda entry: (len(entry.path), entry.name))
        provider.headers[platform] = "; ".join(
            f"{entry.name}={entry.value}" for entry in ordered
        )
        provider.key_names[platform] = [entry.name for entry in ordered]
        provider.expires[platform] = min(entry.expires for entry in ordered if entry.expires)
    return provider
