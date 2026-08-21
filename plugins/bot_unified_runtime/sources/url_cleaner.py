"""URL 跟踪参数清洗。

用途：在把外部链接归一化、去重、缓存、渲染成卡片或发给用户之前，
去除常见的跟踪/分享参数（utm_*、各种 click id、分享来源等），让
``dedupe_key`` / ``cache_key`` 更稳定，也让用户看到的链接更干净。

边界（重要）：

- 只处理完整 http(s) URL，不处理 API endpoint 拼接。清洗器面向
  "出站链接、展示链接、去重键"，调用方不应拿它清洗 FetchRequest 的
  API 地址，因为某些平台 API 需要保留参数。
- 默认保留 path、fragment 和非跟踪参数；锚点（如 B 站 ``?p=2`` 分 P）
  不受影响。
- 默认规则保守：只去掉明确是跟踪/分享用途的参数，不去 "source"、
  "from"、"ref" 这类可能承载业务语义的通用词。需要更激进时通过
  ``extra_params`` 显式追加。

扩展方式：新增平台跟踪参数直接加到 ``DEFAULT_TRACKING_PARAMS``，
或运行时用 ``extra_params`` 注入，不需要改调用方。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        # UTM / Google / 广告
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "yclid",
        "ysclid",
        "mkt_tok",
        "mc_cid",
        "mc_eid",
        "igshid",
        "_openstat",
        "campaign_id",
        "ad_id",
        "adgroup_id",
        "adset_id",
        "ttclid",
        "twclid",
        "li_fat_id",
        "msclkid",
        "vero_id",
        # 阿里 / 淘宝系
        "spm",
        "scm",
        "ali_trackid",
        "ali_refid",
        "union_lens",
        "pvid",
        # 知乎 / 小红书 / 微博 / 抖音
        "xhsshare",
        "weiboauthoruid",
        "wm",
        "s_trans",
        "s_channel",
        "tma",
        "session_id_share",
        # B 站分享追踪
        "spm_id_from",
        "from_spmid",
        "vd_source",
        "is_story_h5",
        "unique_k",
        # 微信分享追踪
        "chksm",
        "mpshare",
        "scene",
        "srcid",
        "sharer_shareid",
        "sharer_sharetime",
        "ascene",
        "devicetype",
        "version",
        "nettype",
        "abtest_cookie",
        "lang",
        "exportkey",
        "pass_ticket",
        "wx_header",
        # 通用分享来源参数
        "share_source",
        "share_medium",
        "share_plat",
        "share_session_id",
        "share_tag",
        "share_id",
        "share_way",
        "share_type",
        "share_from",
        "from_source",
        "source_type",
        "traffic_source",
        "track_id",
        "click_id",
        "clk",
        # 邮件营销追踪
        "email_hash",
        "ehash",
        "mtm_campaign",
        "mtm_source",
        "mtm_medium",
        "mtm_content",
        "pk_campaign",
        "pk_source",
        "pk_medium",
        "pk_content",
        "piwik_campaign",
    }
)

_HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>\"'（）()【】\[\]{}]+")

_REASON_OK = "ok"
_REASON_INVALID_URL = "invalid_url"
_REASON_NON_HTTP = "non_http_url"
_REASON_NO_CHANGE = "no_tracking_params"


@dataclass(frozen=True)
class CleanedUrl:
    """一条 URL 的清洗结果。"""

    original: str
    url: str
    removed_params: tuple[str, ...]
    changed: bool
    reason: str = _REASON_OK


def _strip_params(url: str, tracking_params: frozenset[str]) -> CleanedUrl:
    try:
        parts = urlsplit(url)
    except ValueError:
        return CleanedUrl(
            original=url,
            url=url,
            removed_params=(),
            changed=False,
            reason=_REASON_INVALID_URL,
        )
    if not parts.scheme:
        return CleanedUrl(
            original=url,
            url=url,
            removed_params=(),
            changed=False,
            reason=_REASON_INVALID_URL,
        )
    if parts.scheme.lower() not in {"http", "https"}:
        return CleanedUrl(
            original=url,
            url=url,
            removed_params=(),
            changed=False,
            reason=_REASON_NON_HTTP,
        )
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    removed: list[str] = []
    for key, value in query_pairs:
        if key.lower() in tracking_params:
            removed.append(key)
            continue
        kept.append((key, value))
    if not removed:
        return CleanedUrl(
            original=url,
            url=url,
            removed_params=(),
            changed=False,
            reason=_REASON_NO_CHANGE,
        )
    cleaned_query = urlencode(kept)
    cleaned = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, cleaned_query, parts.fragment)
    )
    if cleaned == url:
        return CleanedUrl(
            original=url,
            url=url,
            removed_params=tuple(dict.fromkeys(removed)),
            changed=False,
            reason=_REASON_NO_CHANGE,
        )
    return CleanedUrl(
        original=url,
        url=cleaned,
        removed_params=tuple(dict.fromkeys(removed)),
        changed=True,
        reason=_REASON_OK,
    )


def clean_tracking_url(
    url: str,
    *,
    extra_params: list[str] | tuple[str, ...] | set[str] = (),
) -> CleanedUrl:
    """去除单条 URL 中的跟踪参数。

    ``extra_params`` 用于临时追加需要去掉的参数名（大小写不敏感）。
    """
    params = frozenset(
        {str(param).lower() for param in extra_params if str(param).strip()}
    ) | DEFAULT_TRACKING_PARAMS
    candidate = url.strip()
    return _strip_params(candidate, params)


def clean_urls_in_text(
    text: str,
    *,
    extra_params: list[str] | tuple[str, ...] | set[str] = (),
) -> str:
    """把文本中出现的 http(s) 链接逐个清洗并替换。

    不匹配任何链接的文本原样返回。
    """
    params = frozenset(
        {str(param).lower() for param in extra_params if str(param).strip()}
    ) | DEFAULT_TRACKING_PARAMS

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        # 链接可能以标点结尾，正则已排除常见标点，但括号内链接
        # 被排除会漏掉尾部，这里做一次尾部标点剥离再拼接。
        trailing = ""
        while raw and raw[-1] in ".,;:!?，。；：！？":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        cleaned = _strip_params(raw, params).url
        return f"{cleaned}{trailing}"

    return _HTTP_URL_PATTERN.sub(_replace, text)
