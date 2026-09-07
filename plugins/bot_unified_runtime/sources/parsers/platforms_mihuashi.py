"""米画师（www.mihuashi.com）链接解析。

- 企划（``/projects/{id}``）：``GET https://www.mihuashi.com/api/v1/projects/{id}``
  匿名可用，取标题 / 预算 / 截稿日 / 分类 / 创建时间。
- 画师主页 / 作品 / 摊位：对应接口（``/api/v1/users/{id}``、
  ``/api/v1/artworks/{id}``、``/api/v1/stalls/{id}``）实测要求 ``M-S``/``M-T``
  请求签名（算法在站点懒加载 JS 中，未逆向出），诚实降级浅卡。
- 页面本身是纯 SPA 空壳（标题/描述为站点通用文案），无 per-item og 可兜底。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _spa_link_card,
)

_MHS_BASE = "https://www.mihuashi.com"
_MHS_REFERER = "https://www.mihuashi.com/"
_MHS_PROJECT_RE = re.compile(r"mihuashi\.com/projects/(\d+)")
_MHS_PROFILE_RE = re.compile(r"mihuashi\.com/profiles/(\d+)")
_MHS_ARTWORK_RE = re.compile(r"mihuashi\.com/artworks/(\d+)")
_MHS_STALL_RE = re.compile(r"mihuashi\.com/stalls/(\d+)")


def _fmt_price(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if number == int(number):
        return f"¥{int(number)}"
    return f"¥{number:.2f}"


def _mhs_project_card(url: str, project_id: str) -> ParsedContent:
    """企划：/api/v1/projects/{id}（标题/预算区间/截稿日/分类）。"""
    payload = http_get_json(
        f"{_MHS_BASE}/api/v1/projects/{project_id}",
        timeout=12,
        referer=_MHS_REFERER,
    )
    project = payload.get("project") if isinstance(payload, dict) else None
    if not isinstance(project, dict) or not str(project.get("name") or "").strip():
        raise ParseHttpError("mihuashi project payload incomplete")
    name = str(project["name"]).strip()
    lower = project.get("lower_price")
    upper = project.get("upper_price")
    stats: dict = {}
    budget = " - ".join(filter(None, [_fmt_price(lower), _fmt_price(upper)]))
    if budget:
        stats["预算"] = budget
    deadline = str(project.get("deadline") or "").strip()
    if deadline:
        stats["截稿日"] = deadline
    created = str(project.get("created_at") or "").strip()
    if created:
        stats["发布时间"] = created[:16].replace("T", " ")
    summary_lines: list[str] = []
    zone = str(project.get("zone_name") or "").strip()
    if zone:
        summary_lines.append(f"分类：{zone}")
    if budget:
        summary_lines.append(f"预算：{budget}")
    if deadline:
        summary_lines.append(f"截稿日：{deadline}")
    description = str(project.get("description") or "").strip()
    if description:
        text = re.sub(r"<[^>]+>", "", description)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            summary_lines.append(f"详情：{text[:260]}")
    return build_parsed_content(
        platform="mihuashi",
        item_id=project_id,
        item_kind="project",
        title=name,
        summary="\n".join(summary_lines),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="project",
        badge="米画师",
        detail={"project": {"project_id": project_id, "deadline": deadline}},
    )


def _mhs_shallow_card(url: str, item_id: str, kind: str, label: str) -> ParsedContent:
    return build_parsed_content(
        platform="mihuashi",
        item_id=item_id,
        item_kind=kind,
        title=f"{label} {item_id}".strip(),
        summary="（米画师该页面的数据接口需要请求签名，机器人拿不到具体内容；"
        "已保留原链接，点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
        badge="米画师",
    )


def parse_mihuashi(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """米画师入口：企划深解析；画师/作品/摊位接口需签名，诚实浅卡。"""
    project_match = _MHS_PROJECT_RE.search(url)
    if project_match:
        try:
            return _mhs_project_card(url, project_match.group(1))
        except ParseHttpError:
            pass
    profile_match = _MHS_PROFILE_RE.search(url)
    if profile_match:
        return _mhs_shallow_card(url, profile_match.group(1), "painter", "米画师画师主页")
    artwork_match = _MHS_ARTWORK_RE.search(url)
    if artwork_match:
        return _mhs_shallow_card(url, artwork_match.group(1), "artwork", "米画师作品")
    stall_match = _MHS_STALL_RE.search(url)
    if stall_match:
        return _mhs_shallow_card(url, stall_match.group(1), "stall", "米画师摊宣")
    return _spa_link_card(url, platform="mihuashi", item_kind="page", label="米画师")
