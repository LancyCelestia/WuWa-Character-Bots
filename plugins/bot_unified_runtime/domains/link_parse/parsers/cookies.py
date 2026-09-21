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
from typing import Self, cast

# 平台 → 收集的域名（子域都归并到平台键下）+ 该平台的关键 cookie 名。
#
# WP1（凭证跨域外泄统一咽喉）：本表是「哪份 Cookie 允许发往哪些 host」的唯一
# 真身——http_util 的附凭证前目标域校验以此为判据。凡解析器会**附带登录态**
# 发往外部 host 的平台都必须在册，含两处不经 provider 的自读兜底：
#   - steam（platforms_steam.steam_cookie_header 自读 Netscape）；
#   - epic（platforms_epic.epic_cookie_header 自读，Cloudflare cf_clearance）。
# 域用后缀语义登记（`.x.com` 覆盖子域；无点前缀项既匹配裸域又匹配子域，见
# http_util._host_matches_domain），故 www./m./live./api. 等子域自动归位，
# 无需为每个子域单列，避免「为过门砍合法链路」。
PLATFORM_COOKIE_DOMAINS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "bilibili": ((".bilibili.com", "bilibili.com"), ("SESSDATA", "DedeUserID", "bili_jct")),
    "xiaohongshu": ((".xiaohongshu.com", "xiaohongshu.com"), ("web_session", "a1", "id_token", "websectiga")),
    "douyin": ((".douyin.com", "douyin.com"), ("ttwid", "odin_tt", "passport_csrf_token", "sessionid", "sessionid_ss")),
    "qqmusic": ((".qq.com", "qq.com", ".y.qq.com", "y.qq.com"), ("p_uin", "psrf_musickey", "psrf_qqaccess_token", "psrf_qqopenid", "uin", "skey")),
    # 网易云音频直链经 CDN（*.music.163.com 与 *.mutecdn.com/muzo 域），
    # 外加入 126.net 供音乐试听链的登录态目标域判定（不加入则误剥合法票）。
    "netease": ((".music.163.com", "music.163.com", ".163.com", "163.com"), ("MUSIC_U", "MUSIC_A", "MUSIC_R_T", "__csrf", "JSESSIONID-WYYY")),
    "kuwo": ((".kuwo.cn", "kuwo.cn"), ("kw_token", "Hm_lvt_cdb524f42f0ce19b169a8071123a4797")),
    "kugou": ((".kugou.com", "kugou.com"), ("kg_mid", "userid", "token", "dfid")),
    "twitter": ((".x.com", "x.com", ".twitter.com", "twitter.com"), ("auth_token", "ct0")),
    "youtube": ((".youtube.com", "youtube.com", ".youtu.be", "youtu.be", ".ytimg.com", "ytimg.com"), ("LOGIN_INFO", "SID", "HSID", "SSID")),
    "kurobbs": ((".kurobbs.com", "kurobbs.com"), ("user_token", "token")),
    "weibo": ((".weibo.com", "weibo.com", ".weibo.cn", "weibo.cn"), ("SUB", "SUBP", "ALF")),
    "kuaishou": ((".kuaishou.com", "kuaishou.com"), ("kuaishou.server.webday7_st", "passToken", "userId")),
    "acfun": ((".acfun.cn", "acfun.cn"), ("acPassToken", "acUsername")),
    "moegirl": ((".moegirl.org.cn", "moegirl.org.cn"), ("moegirlSSOToken",)),
    "xiaoheihe": ((".xiaoheihe.cn", "xiaoheihe.cn"), ("pkey", "hkey", "token")),
    "skland": ((".skland.com", "skland.com"), ()),
    "miyoushe": ((".miyoushe.com", "miyoushe.com", ".bbs.miyoushe.com", "bbs.miyoushe.com"), ()),
    # 知乎：解析链 403 需登录态（d_c0 为关键登录凭证）；白名单此前缺失。
    "zhihu": ((".zhihu.com", "zhihu.com"), ("d_c0", "_zap", "__snaker__id")),
    # WP1 新增：两处自读兜底平台的 Cookie 目标域入册（唯一真身，不另建表）。
    "steam": (
        (".steamcommunity.com", "steamcommunity.com", ".steampowered.com", "steampowered.com"),
        ("steamLoginSecure", "browserid", "birthtime", "steam Machineid"),
    ),
    "epic": ((".epicgames.com", "epicgames.com"), ("EPIC_SESSID", "cf_clearance")),
}


class PlatformCookie(str):
    """带平台域归属的 Cookie 头：仍是 str（拆分/真值/f-string 全兼容），

    额外携带 ``cookie_platform`` 与 ``cookie_domains``，供 http_util 在附凭证
    前做**窄域**校验（B 站票只能发 B 站域，跨到微博即使在联合域内也剥）。
    无归属的普通 str Cookie（如自读兜底）回退到 PLATFORM_COOKIE_DOMAINS 联合域。
    """

    __slots__ = ("cookie_domains", "cookie_platform")

    # 类级注解（无值）声明槽属性类型，供 mypy 认账；实际值在 __new__ 里写。
    cookie_platform: str
    cookie_domains: tuple[str, ...]

    def __new__(
        cls,
        value: str = "",
        *,
        cookie_platform: str = "",
        cookie_domains: tuple[str, ...] = (),
    ) -> Self:
        obj = cast("PlatformCookie", super().__new__(cls, value))
        obj.cookie_platform = cookie_platform
        obj.cookie_domains = tuple(cookie_domains)
        return cast(Self, obj)


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
            if not line:
                continue
            if line.startswith("#HttpOnly_"):
                # 浏览器扩展导出的合法 Netscape 行：#HttpOnly_ 前缀只是标记
                # HttpOnly 属性，剥掉后照常解析（否则关键登录态静默缺失）。
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, cookie_path, _, expires_raw, name, value = parts[:7]
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


def _resolve_relative_cookie_path(cookie_path: Path) -> Path:
    """Resolve relative cookies from external Runtime first, never from CWD.

    DATAFIX（2026-09-12）：此前只读进程 env（``os.getenv``），而 nonebot 的
    dotenv 只注入 driver config 不导出 os.environ——独立脚本/未导出 env 的
    入口会回退 ``project_root / data/...``，把写入落到源码树（实际泄漏：
    platform_cookies.txt）。现改走 scripts/runtime_paths 的数据根解析：
    env 优先，其次 .env/.env.prod，与 config 校验器同一口径。
    """
    if cookie_path.is_absolute():
        return cookie_path
    import sys

    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from scripts.runtime_paths import runtime_data_dir

    runtime_root = runtime_data_dir()
    normalized = str(cookie_path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.lower() == "data":
        return runtime_root
    if normalized.lower().startswith("data/"):
        return (runtime_root / normalized[5:]).resolve()
    return (runtime_root / cookie_path).resolve()


def build_platform_cookie_provider(path: str | Path | None) -> PlatformCookieProvider:
    provider = PlatformCookieProvider()
    if not path:
        return provider
    cookie_path = _resolve_relative_cookie_path(Path(path))
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
        provider.headers[platform] = PlatformCookie(
            "; ".join(f"{entry.name}={entry.value}" for entry in ordered),
            cookie_platform=platform,
            cookie_domains=tuple(domains),
        )
        provider.key_names[platform] = [entry.name for entry in ordered]
        # 全为会话 cookie（expires=0/空）时 min() 空序列会抛 ValueError：
        # 用 default=0 语义化为「无过期时间」，不让单条消息解析路径崩溃。
        provider.expires[platform] = min(
            (entry.expires for entry in ordered if entry.expires), default=0
        )
    return provider
