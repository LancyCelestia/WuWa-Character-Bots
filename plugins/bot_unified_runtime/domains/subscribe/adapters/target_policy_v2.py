"""订阅 V2 目标白名单（审查 SEAT-ATK-SUB F-6，2026-09-28 席位 S-FIX-SUB-SEC）。

洞形（评审在案）：订阅链冒号形态 ``provider:kind:key`` 的 key 段在整张
adapter 面上**零字符集校验**，key 原样内插进拉取 URL（查询参数位与路径位
均有，例 ``/api/playlist/detail?id={key}&limit=50``、``/api/album/{key}``），
用户可构造携带 URL 结构字符（``#`` 片段、``&``/``?`` 参数追加、``/`` 段
跳转）的 key，把同源请求 URL 改写到带平台 Cookie 的畸形目标上——私聊面
``/订阅 add …`` 零角色门槛即达。中央凭证咽喉（link_parse/parsers/
http_util.py 的 ``credentials_allowed_for_target``/``scrub_credentials_for_target``）
按域联合判定，同源注入本就过闸，故根修必须在**订阅侧目标派生点**收紧
key 字符集，并按平台锁出站 host。

本模块是三样东西的唯一真身（表格住订阅域自己身体里，禁散进解析器）：

1. ``TARGET_KEY_PATTERNS``：平台×kind 的 target_key 字符集白名单。
   fail-closed——未登记平台/非法 key 在出面（resolve）一律拒绝；存储/拉取
   纵深层对已登记平台的未登记 kind 回退全局安全字符集，对未登记平台只过
   结构底线（直构/存量复合 id 目标不误杀，含 URL 结构字符的 key 在任一层
   都过不去）。
2. ``PLATFORM_TRUSTED_HOSTS``：平台→可信出站 host 表。拉取 URL 的 host
   不在表内 ⇒ Cookie 一律不带出（即便域名落在中央联合域内）。
3. ``subscription_outbound_cookie``：出站 Cookie 组合口——本表 host 判定
   **且** 中央咽喉 ``scrub_credentials_for_target``（只读复用，本席禁改
   http_util.py）双腿全过才放行；任一腿拒 ⇒ 返回空串（降级未登录，
   语义与 WP1 一致）。

合法字符集口径：key 只允许无保留字符 ``[A-Za-z0-9_.@-]``（youtube 句柄/
xhs 用户 ID 等真实形态所需），各平台再收紧（网易云/pixiv/微博纯数字、
twitter 句柄 ≤15、telegram ≥4 等——与各 adapter URL 形态捕获正则互为
超集，不误杀链接形态订阅）。``..`` 连点与纯点段一律拒绝。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    scrub_credentials_for_target,
)

__all__ = [
    "PLATFORM_TRUSTED_HOSTS",
    "TARGET_KEY_PATTERNS",
    "require_legal_target_key",
    "subscription_outbound_cookie",
    "target_key_issue",
    "trusted_host_for_platform",
]

# 平台默认式＝全局安全字符集（不含任何 URL 结构字符 ``:/?#[]@&=%$+,''`` 中
# 除 @ 外的字符；@ 仅句柄形态无害且 youtube live 冒号形态存量在用）。
_UNIVERSAL_KEY_PATTERN = re.compile(r"[0-9A-Za-z_.@-]{1,64}")

TARGET_KEY_PATTERNS: dict[str, dict[str, re.Pattern[str]]] = {
    "netease": {
        # 网易云 playlist/album/artist/uid 实测均为纯数字 id。
        "*": re.compile(r"\d{1,32}"),
    },
    "bilibili": {
        # creator 放行 alnum_-：存量 v1/v2 目标含非纯数字用户串号（桥接回退
        # 路径测试面在册 u1 形态）；字符集仍零 URL 结构字符。
        "creator": re.compile(r"[0-9A-Za-z_-]{1,64}"),
        "live_room": re.compile(r"\d{1,20}"),
        "bangumi": re.compile(r"(?:ss|ep)\d{1,10}"),
        "favorite": re.compile(r"\d{1,20}"),
        "collection": re.compile(r"\d{1,20}"),
    },
    "xiaohongshu": {
        "*": re.compile(r"[0-9A-Za-z_-]{1,64}"),
    },
    "youtube": {
        # channel=UC 前缀 id 或 @句柄（_resolve_handle_channel_id 失败时
        # 回退存句柄）；playlist=list 参数；live 冒号形态存量含 @ 前缀。
        "channel": re.compile(r"@?[0-9A-Za-z_.-]{1,64}"),
        "playlist": re.compile(r"[0-9A-Za-z_-]{1,64}"),
        "live": re.compile(r"@?[0-9A-Za-z_.-]{1,64}"),
    },
    "telegram": {
        "*": re.compile(r"[0-9A-Za-z_]{4,64}"),
    },
    "pixiv": {
        "*": re.compile(r"\d{1,20}"),
    },
    "weibo": {
        "*": re.compile(r"\d{1,20}"),
    },
    "twitter": {
        # X 句柄上限 15。
        "creator": re.compile(r"[0-9A-Za-z_]{1,15}"),
    },
}

# 平台→可信出站 host（订阅域拉取真身实测 host，逐平台收紧；子域后缀匹配
# 见 trusted_host_for_platform）。扩表须与对应 adapter 的 URL 常量同批改。
PLATFORM_TRUSTED_HOSTS: dict[str, frozenset[str]] = {
    "netease": frozenset({"music.163.com"}),
    "bilibili": frozenset(
        {
            "api.bilibili.com",
            "live.bilibili.com",
            "www.bilibili.com",
            "space.bilibili.com",
        }
    ),
    "xiaohongshu": frozenset({"www.xiaohongshu.com", "xiaohongshu.com"}),
    "youtube": frozenset({"www.youtube.com", "youtube.com"}),
    "telegram": frozenset({"t.me"}),
    "pixiv": frozenset({"www.pixiv.net", "pixiv.net"}),
    "weibo": frozenset({"m.weibo.cn", "weibo.com"}),
    "twitter": frozenset({"x.com", "twitter.com"}),
}


def trusted_host_for_platform(platform: str, url: str) -> bool:
    """url 的 host 是否落在该平台的可信 host 表（精确或子域后缀匹配）。"""
    allowed = PLATFORM_TRUSTED_HOSTS.get(str(platform or ""))
    if not allowed:
        return False
    try:
        host = (urlsplit(str(url or "")).hostname or "").strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    for domain in allowed:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _key_pattern_for(platform: str, kind: str) -> re.Pattern[str] | None:
    table = TARGET_KEY_PATTERNS.get(str(platform or ""))
    if table is None:
        return None
    return table.get(str(kind or "")) or table.get("*")


# 未登记平台目标的底线字符集：不进模式表（无对应 adapter，落库不进出站，
# 出面 resolve 早已 fail-closed），但 URL 结构字符、空白、控制符在**任何**
# 一层都过不去；复合 id 冒号形态（测试面直构的 ``test:channel:1`` 类存量）
# 不误杀。
_STRUCTURAL_FORBIDDEN = frozenset(
    "\\/?#[]{}<>!$&'()*+,;=%^|`~\""
)


def _structural_issue(text: str) -> str:
    if ".." in text or set(text) <= {"."}:
        return "订阅目标标识含非法字符"
    for ch in text:
        if ch.isspace() or ch < " " or ch == "\x7f" or ch in _STRUCTURAL_FORBIDDEN:
            return "订阅目标标识含非法字符"
    return ""


def target_key_issue(platform: str, kind: str, key: str) -> str:
    """纵深层判据（存储 upsert / 拉取构造点共用）。返回 ''＝合法，否则人话原因。

    已登记平台：kind 有专属式用专属式，无专属式且平台无 ``*`` 默认时回退
    全局安全字符集；``..`` 连点与纯点段任何平台都不放行。未登记平台：
    不过模式表、只过结构底线（``_structural_issue``）——直构/存量复合 id
    目标不误杀，含 URL 结构字符或空白控制符的 key 依旧过不去。
    """
    text = str(key or "")
    if not text:
        return "订阅目标标识为空"
    if len(text) > 64:
        return "订阅目标标识过长"
    platform_text = str(platform or "")
    pattern = _key_pattern_for(platform_text, str(kind or ""))
    if pattern is None and platform_text in TARGET_KEY_PATTERNS:
        pattern = _UNIVERSAL_KEY_PATTERN
    if pattern is not None:
        if ".." in text or not pattern.fullmatch(text):
            return "订阅目标标识含非法字符"
        if set(text) <= {"."}:
            return "订阅目标标识含非法字符"
        return ""
    return _structural_issue(text)


def require_legal_target_key(platform: str, kind: str, key: str) -> None:
    """出面（resolve→构造 SubscriptionTarget 的唯一咽喉）硬校验，fail-closed。

    平台未登记或 key 非法 ⇒ ValueError（与「无法识别的订阅目标」同族语义，
    走 add 面既有拒绝路径，零落库）。不回显 key 原文，拒绝消息本身不再
    成为注入口。
    """
    if str(platform or "") not in TARGET_KEY_PATTERNS:
        raise ValueError(f"不支持的订阅平台：{platform}")
    issue = target_key_issue(platform, kind, key)
    if issue:
        raise ValueError(f"订阅目标被拒绝：{issue}（{platform}）")


def subscription_outbound_cookie(platform: str, url: str, cookie: str) -> str:
    """出站 Cookie 组合口：平台 host 表 ∧ 中央咽喉，双腿全过才带出。

    中央咽喉 ``scrub_credentials_for_target`` 只读复用（WP1 联合域判定），
    本表再按平台收紧——同源注入即便过联合域，也出不了本平台的 host 表。
    """
    text = str(cookie or "")
    if not text:
        return ""
    if not trusted_host_for_platform(platform, url):
        return ""
    return str(scrub_credentials_for_target(text, url) or "")
