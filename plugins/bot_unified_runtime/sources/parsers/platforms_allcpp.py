"""allcpp（无差别同人站）活动详情深度解析。

活动页是服务端渲染页面，详情数据内嵌在 HTML 的 ``eventParam.*`` 等 JS 变量中；
本模块直接抓页面正文做容错正则解析，不再调用任何 JSON 接口。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
)
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

_EVENT_ID_RE = re.compile(r"event=(\d+)")
_EID_RE = re.compile(r"eventParam\.EID\s*=\s*(\d+);")
_WORKSOBJNAME_RE = re.compile(r'WORKSOBJNAME\s*=\s*"([^"]*)";')
_EVENT_NAME_RE = re.compile(r'eventParam\.eventName\s*=\s*"([^"]*)";')
_PIC_URL_RE = re.compile(r'eventParam\.picUrl\s*=\s*"([^"]*)";')
_SDATE_RE = re.compile(r'eventParam\.sDate\s*=\s*"([^"]*)";')
_EDATE_RE = re.compile(r'eventParam\.eDate\s*=\s*"([^"]*)";')
_ENTER_ADDRESS_RE = re.compile(r'eventParam\.enterAddress\s*=\s*"([^"]*)";')
_EVENT_TAG_RE = re.compile(r'eventParam\.eventTag\s*=\s*"([^"]*)";')
_DES_CONTENT_RE = re.compile(r'eventParam\.desContent\s*=\s*"([^"]*)";')
_IS_ONLY_RE = re.compile(r"eventParam\.isOnly\s*=\s*(\d+);")
_EVENT_TYPE_RE = re.compile(r"eventParam\.eventType\s*=\s*(\d+);")
_LAST_DAYS_RE = re.compile(r"eventParam\.lastDays\s*=\s*(-?\d+);")
_ORGANIZER_RE = re.compile(r"EVENTUSERID\s*=\s*(\d+);")

# eventType 中文映射；未知值显示原数字。
_EVENT_TYPE_LABELS = {
    "1": "茶会",
    "2": "综合同人展",
    "3": "ONLY展",
    "4": "游戏展",
    "5": "线上活动",
}
_MAX_TAGS = 10
_MAX_DESC_CHARS = 300


def _extract(pattern: re.Pattern[str], html: str) -> str:
    """取正则第一个捕获组，匹配不到返回空串。"""
    match = pattern.search(html)
    return match.group(1) if match else ""


def parse_allcpp(url: str, *, cookie_header: str = "") -> PlatformParse:
    """解析 allcpp 活动页内嵌 SSR 变量，产出深度信息卡。

    抓取失败（``http_get_text`` 抛 ``ParseHttpError``）时原样上抛，
    由上层能力层降级，不在这里兜底成占位卡。
    """
    if not _EVENT_ID_RE.search(url):
        raise ParseHttpError("allcpp: no event id")
    final_url, html = http_get_text(
        url,
        timeout=15,
        referer="https://www.allcpp.cn/",
        cookie=cookie_header,
    )

    eid = _extract(_EID_RE, html)
    event_name = _extract(_EVENT_NAME_RE, html)
    if not event_name:
        # eventName 可能为空串，回退页面标题变量 WORKSOBJNAME。
        event_name = _extract(_WORKSOBJNAME_RE, html)
    if not eid or not event_name:
        raise ParseHttpError("allcpp: event data not found in page")

    _organizer_id = _extract(_ORGANIZER_RE, html)  # 主办方 ID 不当作作者名。
    pic_url = _extract(_PIC_URL_RE, html)
    s_date = _extract(_SDATE_RE, html)
    e_date = _extract(_EDATE_RE, html)
    enter_address = _extract(_ENTER_ADDRESS_RE, html)
    event_tag = _extract(_EVENT_TAG_RE, html)
    des_content = _extract(_DES_CONTENT_RE, html)
    is_only = _extract(_IS_ONLY_RE, html)
    event_type = _extract(_EVENT_TYPE_RE, html)
    last_days = _extract(_LAST_DAYS_RE, html)

    summary_lines: list[str] = []
    if s_date:
        if e_date and e_date != s_date:
            summary_lines.append(f"时间：{s_date} 至 {e_date}")
        else:
            summary_lines.append(f"时间：{s_date}")
    elif e_date:
        summary_lines.append(f"时间：{e_date}")
    if enter_address:
        summary_lines.append(f"地址：{enter_address}")
    type_label = _EVENT_TYPE_LABELS.get(event_type)
    if type_label is None and event_type:
        type_label = f"类型{event_type}"
    if type_label:
        summary_lines.append(f"类型：{type_label}")
    if is_only == "1":
        summary_lines.append("独家活动")
    tags = [tag for tag in event_tag.split("|") if tag][:_MAX_TAGS]
    if tags:
        summary_lines.append("标签：" + "、".join(tags))
    if des_content:
        if len(des_content) > _MAX_DESC_CHARS:
            des_content = des_content[:_MAX_DESC_CHARS] + "…"
        summary_lines.append(f"简介：{des_content}")

    stats: dict[str, str] = {}
    if last_days:
        days = int(last_days)
        if days > 0:
            stats["距离开始"] = f"{days} 天"

    return PlatformParse(
        platform="allcpp",
        item_id=eid,
        item_kind="event",
        title=event_name,
        summary="\n".join(summary_lines),
        cover_url=pic_url,
        canonical_url=final_url or url,
        stats=stats,
        parse_depth="deep",
    )