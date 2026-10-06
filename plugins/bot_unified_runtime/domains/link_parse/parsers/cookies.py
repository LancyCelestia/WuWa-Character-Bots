"""平台 Cookie 提供方：从 Netscape 格式 cookies.txt 提取各平台 Cookie 头。

安全规则（与 sources/credentials.py 一致）：

- 只加载本模块白名单内的平台域名，其余一律丢弃；
- 值只在解析请求的 transport 边界使用，不进日志/审计/消息；
- 输出只暴露「平台 → 关键 cookie 名列表」，绝不打印值。

配置：``BOT_COOKIES_FILE=data/platform_cookies.txt``（Netscape 格式，
浏览器扩展导出）。加载失败或文件缺失时返回空 cookie（解析自动降级，
不会让链路报错）。

未认领账目（2026-09-25 S-T-COOKIE-1）：文件里「没有任何平台认领的域名」
过去被静默丢弃，管理员只能看到「未配置」，看不出「这份文件对 bot 没用」。
现在 ``PlatformCookieProvider`` 携带**只含域名与计数、绝不含值**的账目，
并以 ``cookie_unclaimed_domains`` 为固定检索词打一条日志（同一份文件内容
只报一次，避免每条点歌/解析都刷盘）。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, cast

logger = logging.getLogger(__name__)

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
        # 🔴 原名单里的 `steam Machineid` 已删：真实 cookie 名不含空格，该判据永不成立；
        # Steam 的机器验证票名形如 `steamMachineAuth<steamid>`（带号），本就无法用静态名单表达，
        # 列进去只会让「缺主证键」永久误报。登录主证只认 steamLoginSecure。
        ("steamLoginSecure", "browserid", "birthtime"),
    ),
    "epic": ((".epicgames.com", "epicgames.com"), ("EPIC_SESSID", "cf_clearance")),
}

# 在册域名全集：**由上表派生，不另建第二份表**（http_util 的附凭证校验仍吃
# 上表本身，这里只服务「未认领」报告）。⚠ 只用于报告，绝不参与实际匹配——
# 把匹配从精确成员判定放宽成后缀语义是**安全面变更**（窄域剥离判据会变宽），
# 须另行裁定，见本席交接报告 findings §3。
_REGISTERED_COOKIE_DOMAINS: frozenset[str] = frozenset(
    domain for domains, _key_names in PLATFORM_COOKIE_DOMAINS.values() for domain in domains
)

# 报告里最多点名几个域名（超出只报总数）：域名不是秘密，但日志不该被一份
# 巨型导出刷满屏；总数始终给全，绝不让人误判「只有这几个」。
_MAX_REPORTED_DOMAINS = 12


def near_miss_platform(domain: str) -> str:
    """未认领域名是否**看起来**属于某个在册平台（仅用于报告，不参与匹配）。

    浏览器 Netscape 导出会把 host-only cookie 写成 ``www.bilibili.com`` 这类
    形态，而在册项是 ``.bilibili.com``/``bilibili.com``，精确成员判定吃不中
    ⇒ 登录态静默缺失。这一层判定把该形态点名出来，让「我明明导入了」变成
    一句能看懂的话，而不是又一条神秘现象。最长在册后缀胜出（防 ``qq.com``
    抢走 ``y.qq.com`` 一类的多级归属）。
    """
    candidate = (domain or "").strip().lower().lstrip(".")
    if not candidate:
        return ""
    best_platform = ""
    best_length = -1
    for platform, (domains, _key_names) in PLATFORM_COOKIE_DOMAINS.items():
        for registered in domains:
            needle = registered.lower().lstrip(".")
            if not needle:
                continue
            claimed = candidate == needle or candidate.endswith(f".{needle}")
            if claimed and len(needle) > best_length:
                best_platform, best_length = platform, len(needle)
    return best_platform



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
    # 🔴 注册表第二元素（登录主证键）的唯一消费者：该平台**有凭据但缺哪张主证票**。
    # 此前八个消费点全把它写成 `_key_names` 丢弃＝死数据，只会骗读代码的人（缺登录态时静默发匿名票）。
    missing_required: dict[str, list[str]] = field(default_factory=dict)
    # ↓ 未认领账目（只含域名与计数，**绝不含 cookie 值**）。
    # unclaimed_domains：域名 → 该域名被丢弃的条目数（无任何平台认领它）。
    unclaimed_domains: dict[str, int] = field(default_factory=dict)
    # near_miss_domains：上述域名 → 看起来应归属的平台（写法不合在册形态）。
    near_miss_domains: dict[str, str] = field(default_factory=dict)
    # expired_dropped：在册域名 → 条目数（域名认得但到期时间已过，被丢弃）。
    expired_dropped: dict[str, int] = field(default_factory=dict)
    # unparsable_lines：非注释非空行但**解析不出任何条目**的行数（分隔符不是
    # TAB 的「伪 Netscape」= 整份文件白导，过去完全静默）。仅在零条目时统计。
    unparsable_lines: int = 0
    entry_total: int = 0
    source_path: str = ""

    def cookie_header(self, platform: str) -> str:
        return self.headers.get(platform, "")

    def has_cookie(self, platform: str) -> bool:
        return bool(self.headers.get(platform, ""))

    def summary(self) -> dict[str, list[str]]:
        """只暴露 cookie 名，不暴露值。"""
        return dict(self.key_names)

    def earliest_expires(self, platform: str) -> int:
        return self.expires.get(platform, 0)

    def has_unclaimed(self) -> bool:
        """这份文件有没有「说不出为什么没生效」的部分（含过期与解析不出）。"""
        return bool(
            self.unclaimed_domains
            or self.expired_dropped
            or self.unparsable_lines
        )


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


def _count_payload_lines(path: Path) -> int:
    """非注释、非空的行数（只在解析出零条目时用到，热路径零成本）。

    典型命中：导出器用空格/逗号分隔而非 TAB，或只写了 `域名\t名字\t值`
    三列——这类文件看着「导入了」，实际一条都没进。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return sum(
                1
                for raw_line in handle
                if raw_line.strip() and not raw_line.strip().startswith("#")
            )
    except OSError:
        return 0


def _tally_dropped_entries(
    provider: PlatformCookieProvider,
    entries: list[CookieEntry],
    *,
    now: int,
) -> None:
    """把「没被任何平台认领」的条目记成**域名 + 计数**账目（绝不含值）。

    三种静默丢弃各有各的账：域名不在册 / 域名在册但已过期 / 名字为空。
    """
    for entry in entries:
        domain = entry.domain or ""
        if domain in _REGISTERED_COOKIE_DOMAINS:
            if entry.expires and entry.expires <= now:
                provider.expired_dropped[domain] = provider.expired_dropped.get(domain, 0) + 1
            continue
        provider.unclaimed_domains[domain] = provider.unclaimed_domains.get(domain, 0) + 1
        guess = near_miss_platform(domain)
        if guess:
            provider.near_miss_domains[domain] = guess


def _sorted_counts(mapping: dict[str, int]) -> dict[str, int]:
    """按计数降序、同数按域名升序稳定排序（报告行序不随进程哈希重洗）。"""
    return dict(sorted(mapping.items(), key=lambda item: (-item[1], item[0])))


def _domain_face(mapping: dict[str, int]) -> str:
    """域名→计数 的紧凑呈现，超出 ``_MAX_REPORTED_DOMAINS`` 只报总数。"""
    if not mapping:
        return "无"
    shown = list(mapping.items())[:_MAX_REPORTED_DOMAINS]
    text = "、".join(f"{domain}×{count}" for domain, count in shown)
    hidden = len(mapping) - len(shown)
    if hidden > 0:
        text += f"（另有 {hidden} 个域名未列出）"
    return text


def cookie_file_report_lines(provider: PlatformCookieProvider | None) -> list[str]:
    """未认领账目的人读版（每行都已过 ``redact_local_secrets``）。

    给「状态面」用：``/bot cookie status`` 的 owner 只要把本函数返回的行
    接在平台清单之后，管理员就能看到「这份文件里哪几行对 bot 没用」，
    而不再只看到一串「未配置」。本函数**不写日志、不改任何 cookie**。
    """
    if provider is None:
        return []
    if not provider.has_unclaimed():
        return []
    unclaimed = _sorted_counts(provider.unclaimed_domains)
    expired = _sorted_counts(provider.expired_dropped)
    with_path = (
        "Cookie 文件体检："
        f"条目 {provider.entry_total} 条；"
        f"命中 {len(provider.headers)} 个平台；"
        f"未认领 {sum(unclaimed.values())} 条（域名 {len(unclaimed)} 个）；"
        f"已过期丢弃 {sum(expired.values())} 条"
        + (f"；解析不出条目的行 {provider.unparsable_lines} 行" if provider.unparsable_lines else "")
        + f"｜文件 {provider.source_path or '（未记录）'}"
    )
    fallback = (
        "Cookie 文件体检："
        f"条目 {provider.entry_total} 条；"
        f"命中 {len(provider.headers)} 个平台；"
        f"未认领 {sum(unclaimed.values())} 条（域名 {len(unclaimed)} 个）；"
        f"已过期丢弃 {sum(expired.values())} 条"
        + (f"；解析不出条目的行 {provider.unparsable_lines} 行" if provider.unparsable_lines else "")
        + "｜文件路径已隐藏"
    )
    lines = [_redact_or_hide_path(with_path, fallback=fallback)]
    if unclaimed:
        lines.append(f"未认领域名（bot 不吃这些域的 cookie）：{_domain_face(unclaimed)}")
    if provider.near_miss_domains:
        near_miss = "、".join(
            f"{domain}→{platform}"
            for domain, platform in sorted(provider.near_miss_domains.items())[:_MAX_REPORTED_DOMAINS]
        )
        lines.append(
            f"其中写法不像在册形态、疑似本该命中（未自动放宽匹配，需人工确认）：{near_miss}"
        )
    if expired:
        lines.append(f"域名在册但已过期（需重新登录/导入）：{_domain_face(expired)}")
    if provider.unparsable_lines:
        lines.append(
            f"另有 {provider.unparsable_lines} 行既非注释也解析不出条目"
            "（Netscape 必须用 TAB 分隔且满 7 列）"
        )
    return lines


def _redact_or_hide_path(text: str, *, fallback: str) -> str:
    """出口统一打码；打码件不可用时宁可**丢掉路径**也不裸奔（AGENTS 规则 3）。

    两条兜底腿各锁各的：①导入不到打码件 ②打码件自己抛异常。任一条被摘掉，
    ``tests/test_cookie_file_loader_end_to_end.py`` 对应用例即红（注毒实测见本
    席日志 §陆 M3/M4）。
    """
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )
    except Exception:  # noqa: BLE001 - 腿①：导入不了就打码不了，走无路径兜底。
        return fallback  # 兜底A-导入失败
    try:
        return redact_local_secrets(text)
    except Exception:  # noqa: BLE001 - 腿②：同上，函数异常也绝不返回未打码文本。
        return fallback  # 兜底B-打码抛错


# 同一份文件内容只报一次：点歌/解析每次都重建 provider，不去重会把日志刷满。
# 键含路径 + 条目数 + 未认领账目指纹（不含任何 cookie 值）。
_REPORTED_IDENTITIES: deque[tuple[object, ...]] = deque(maxlen=32)

UNCLAIMED_REPORT_TOKEN = "cookie_unclaimed_domains"


def _report_identity(provider: PlatformCookieProvider) -> tuple[object, ...]:
    return (
        provider.source_path,
        provider.entry_total,
        tuple(sorted(provider.unclaimed_domains.items())),
        tuple(sorted(provider.expired_dropped.items())),
        provider.unparsable_lines,
    )


def log_cookie_file_report(provider: PlatformCookieProvider) -> None:
    """把未认领账目打成一条可 grep 的日志（固定检索词 ``cookie_unclaimed_domains``）。

    只打域名与计数；路径经 ``redact_local_secrets``（本机盘符会被换成占位符）。
    """
    if not provider.has_unclaimed():
        return
    identity = _report_identity(provider)
    if identity in _REPORTED_IDENTITIES:
        return
    _REPORTED_IDENTITIES.append(identity)
    unclaimed = _sorted_counts(provider.unclaimed_domains)
    expired = _sorted_counts(provider.expired_dropped)
    message = (
        f"{UNCLAIMED_REPORT_TOKEN} file=%s entries=%d claimed_platforms=%d "
        f"unclaimed=%d unclaimed_domains=%s near_miss=%s expired_dropped=%s "
        f"unparsable_lines=%d"
    )
    near_miss = "、".join(
        f"{domain}->{platform}" for domain, platform in sorted(provider.near_miss_domains.items())
    )
    redacted = _redact_or_hide_path(
        message % (
            provider.source_path,
            provider.entry_total,
            len(provider.headers),
            sum(unclaimed.values()),
            _domain_face(unclaimed),
            near_miss or "无",
            _domain_face(expired) if expired else "无",
            provider.unparsable_lines,
        ),
        fallback=message
        % (
            "<本机路径已隐藏>",
            provider.entry_total,
            len(provider.headers),
            sum(unclaimed.values()),
            _domain_face(unclaimed),
            near_miss or "无",
            _domain_face(expired) if expired else "无",
            provider.unparsable_lines,
        ),
    )
    logger.warning(redacted)


def build_platform_cookie_provider(path: str | Path | None) -> PlatformCookieProvider:
    provider = PlatformCookieProvider()
    if not path:
        return provider
    cookie_path = _resolve_relative_cookie_path(Path(path))
    provider.source_path = str(cookie_path)
    if not cookie_path.exists():
        return provider
    try:
        entries = parse_netscape_cookie_file(cookie_path)
    except OSError:
        return provider
    provider.entry_total = len(entries)
    if not entries:
        # 零条目 + 有正文 = 分隔符/列数不合 Netscape，整份文件白导。
        provider.unparsable_lines = _count_payload_lines(cookie_path)
    now = int(time.time())
    for platform, (domains, required) in PLATFORM_COOKIE_DOMAINS.items():
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
        if required:
            present = {entry.name for entry in ordered}
            absent = [name for name in required if name not in present]
            if absent:
                provider.missing_required[platform] = absent
        # 全为会话 cookie（expires=0/空）时 min() 空序列会抛 ValueError：
        # 用 default=0 语义化为「无过期时间」，不让单条消息解析路径崩溃。
        provider.expires[platform] = min(
            (entry.expires for entry in ordered if entry.expires), default=0
        )
    _tally_dropped_entries(provider, entries, now=now)
    log_cookie_file_report(provider)
    return provider
