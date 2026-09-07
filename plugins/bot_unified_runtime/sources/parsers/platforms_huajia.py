"""网易画加（huajia.163.com）链接解析。

- 约稿商品（``/main/goods/details/{key}``）：
  ``GET /napp/store/goods/detail?goods_id={key}``（匿名可用），取商品名 /
  价格 / 封面 / 说明 / 画师信息。
- 约稿企划（``/main/projects/details/{key}``）：
  ``GET /napp/commission/commission/detail?commission_id={key}``（匿名可用），
  取标题 / 描述 / 预算区间 / 截稿时间 / 参考图 / 雇主信息。
- 画师主页（``/main/profile/{uid}``）：
  ``GET /app/v1/user/detail?uid={uid}``（匿名可用），取昵称 / 头像 / 等级 /
  简介标志 / 作品数 / 粉丝数。
- 作品广场（``/main/works/?tab=rank``）：列表页，走静态浅卡。

页面本身是纯 SPA 空壳（标题为站点通用文案，无 per-item og）。
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _format_epoch,
    _spa_link_card,
)

_HJ_BASE = "https://huajia.163.com"
_HJ_REFERER = "https://huajia.163.com/"
_HJ_GOODS_RE = re.compile(r"huajia\.163\.com/main/goods/details/([0-9A-Za-z]+)")
_HJ_PROJECT_RE = re.compile(r"huajia\.163\.com/main/projects/details/([0-9A-Za-z]+)")
_HJ_PROFILE_RE = re.compile(r"huajia\.163\.com/main/profile/([0-9A-Za-z]+)")


def _fmt_fen(value: object) -> str:
    """价格单位为分 → '¥xxx'；非法/为 0 返回空串。"""
    try:
        fen = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if fen <= 0:
        return ""
    yuan = fen / 100
    return f"¥{int(yuan)}" if yuan == int(yuan) else f"¥{yuan:.2f}"


def _hj_get(path: str, params: dict) -> dict:
    payload = http_get_json(
        f"{_HJ_BASE}{path}?{urlencode(params)}",
        timeout=12,
        referer=_HJ_REFERER,
    )
    if not isinstance(payload, dict):
        raise ParseHttpError("huajia: non-dict response")
    if payload.get("code") not in (200, "200", 0, "0"):
        raise ParseHttpError(f"huajia {path} code={payload.get('code')}")
    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        raise ParseHttpError(f"huajia {path} empty data")
    return data


def _hj_user_detail(user: object) -> dict:
    if not isinstance(user, dict):
        return {}
    detail: dict = {}
    if user.get("uid"):
        detail["uuid"] = str(user["uid"])
    if user.get("avatar"):
        detail["avatar"] = str(user["avatar"])
    if user.get("name"):
        detail["name"] = str(user["name"])
    return detail


def _hj_goods_card(url: str, goods_key: str) -> ParsedContent:
    """约稿商品：name/价格/封面/说明/画师。"""
    data = _hj_get("/napp/store/goods/detail", {"goods_id": goods_key})
    goods = data.get("goods") or {}
    if not isinstance(goods, dict) or not str(goods.get("name") or "").strip():
        raise ParseHttpError("huajia goods missing name")
    name = str(goods["name"]).strip()
    price = _fmt_fen(goods.get("price"))
    original = _fmt_fen(goods.get("original_price"))
    stats: dict = {}
    if price:
        stats["价格"] = price
    if original and original != price:
        stats["原价"] = original
    evaluations = goods.get("evaluation_count")
    if isinstance(evaluations, (int, float)) and evaluations > 0:
        stats["评价数"] = int(evaluations)
    cover = ""
    cover_obj = goods.get("cover_image")
    if isinstance(cover_obj, dict):
        cover = str(cover_obj.get("file_url") or "")
    description = re.sub(r"<[^>]+>", "", str(goods.get("description") or ""))
    description = re.sub(r"\s+", " ", description).strip()
    summary_lines: list[str] = []
    category = str(goods.get("category_desc") or "").strip()
    if category:
        summary_lines.append(f"分类：{category}")
    if price:
        summary_lines.append(f"价格：{price}")
    if description:
        summary_lines.append(f"说明：{description[:260]}")
    user = goods.get("user") or {}
    author_name = str(user.get("name") or "").strip() if isinstance(user, dict) else ""
    if author_name:
        summary_lines.append(f"画师：{author_name}")
    detail: dict = {"goods": {"goods_id": goods_key, "name": name, "price": price}}
    author_detail = _hj_user_detail(user)
    if author_detail:
        detail["author"] = author_detail
    return build_parsed_content(
        platform="huajia",
        item_id=goods_key,
        item_kind="goods",
        title=name,
        author_name=author_name,
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="goods",
        badge="画加",
        detail=detail,
    )


def _hj_project_card(url: str, project_key: str) -> ParsedContent:
    """约稿企划：title/描述/预算区间/截稿时间/参考图/雇主。"""
    data = _hj_get(
        "/napp/commission/commission/detail", {"commission_id": project_key}
    )
    commission = data.get("commission") or {}
    if not isinstance(commission, dict) or not str(commission.get("title") or "").strip():
        raise ParseHttpError("huajia commission missing title")
    title = str(commission["title"]).strip()
    min_budget = _fmt_fen(commission.get("min_budget"))
    max_budget = _fmt_fen(commission.get("max_budget"))
    budget = ""
    if min_budget and max_budget and min_budget != max_budget:
        budget = f"{min_budget} - {max_budget}"
    elif min_budget or max_budget:
        budget = min_budget or max_budget
    stats: dict = {}
    if budget:
        stats["预算"] = budget
    deadline_ts = commission.get("deadline")
    deadline = _format_epoch(deadline_ts)
    if deadline:
        stats["截稿时间"] = deadline
    created = _format_epoch(commission.get("created_at"))
    if created:
        stats["发布时间"] = created
    apply_count = commission.get("apply_count")
    if isinstance(apply_count, (int, float)) and apply_count > 0:
        stats["应征数"] = int(apply_count)
    description = re.sub(r"<[^>]+>", "", str(commission.get("description") or ""))
    description = re.sub(r"\s+", " ", description).strip()
    summary_lines: list[str] = []
    if budget:
        summary_lines.append(f"预算：{budget}")
    if deadline:
        summary_lines.append(f"截稿：{deadline}")
    if description:
        summary_lines.append(f"详情：{description[:260]}")
    images = [
        str(img.get("file_url") or "")
        for img in (commission.get("images") or [])
        if isinstance(img, dict) and img.get("file_url")
    ]
    if images:
        summary_lines.append(f"参考图 {len(images)} 张")
    user = commission.get("user") or {}
    author_name = str(user.get("name") or "").strip() if isinstance(user, dict) else ""
    if author_name:
        summary_lines.append(f"雇主：{author_name}")
    detail: dict = {
        "project": {
            "commission_id": project_key,
            "title": title,
            "budget": budget,
            "deadline": deadline,
        }
    }
    if images:
        detail["project"]["images"] = images[:6]
    author_detail = _hj_user_detail(user)
    if author_detail:
        detail["author"] = author_detail
    return build_parsed_content(
        platform="huajia",
        item_id=project_key,
        item_kind="project",
        title=title,
        author_name=author_name,
        summary="\n".join(summary_lines),
        cover_url=images[0] if images else "",
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="project",
        badge="画加",
        detail=detail,
    )


def _hj_profile_card(url: str, uid: str) -> ParsedContent:
    """画师主页：user/detail（昵称/等级/简介/作品数/粉丝数）。"""
    data = _hj_get("/app/v1/user/detail", {"uid": uid})
    user = data.get("user") or {}
    if not isinstance(user, dict) or not str(user.get("name") or "").strip():
        raise ParseHttpError("huajia profile missing name")
    name = str(user["name"]).strip()
    stats: dict = {}
    work_count = user.get("work_count")
    if isinstance(work_count, (int, float)):
        stats["作品数"] = int(work_count)
    follower_count = user.get("follower_count")
    if isinstance(follower_count, (int, float)) or (
        isinstance(follower_count, str) and follower_count.isdigit()
    ):
        stats["粉丝"] = int(follower_count)
    following_count = user.get("following_count")
    if isinstance(following_count, (int, float)) or (
        isinstance(following_count, str) and following_count.isdigit()
    ):
        stats["关注"] = int(following_count)
    grade = str(user.get("artist_grade_desc") or "").strip()
    intro = str(user.get("intro") or "").strip()
    summary_lines: list[str] = []
    if grade:
        summary_lines.append(f"等级：{grade}")
    tags = [str(tag) for tag in (user.get("show_tags") or []) if str(tag).strip()]
    if tags:
        summary_lines.append("擅长：" + "、".join(tags[:8]))
    if intro:
        summary_lines.append(f"简介：{intro[:260]}")
    author_detail: dict = {"uuid": uid}
    if user.get("avatar"):
        author_detail["avatar"] = str(user["avatar"])
    if intro:
        author_detail["signature"] = intro[:200]
    return build_parsed_content(
        platform="huajia",
        item_id=uid,
        item_kind="painter",
        title=name,
        author_name=name,
        summary="\n".join(summary_lines),
        cover_url=str(user.get("avatar") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="profile",
        badge="画加",
        detail={"author": author_detail},
    )


def parse_huajia(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """画加入口：商品/企划/画师主页深解析，作品广场等列表页浅卡。"""
    goods_match = _HJ_GOODS_RE.search(url)
    if goods_match:
        try:
            return _hj_goods_card(url, goods_match.group(1))
        except Exception:  # noqa: BLE001, S110 - 任何深解析异常（含网络层）降级浅卡。
            pass
    project_match = _HJ_PROJECT_RE.search(url)
    if project_match:
        try:
            return _hj_project_card(url, project_match.group(1))
        except Exception:  # noqa: BLE001, S110 - 任何深解析异常（含网络层）降级浅卡。
            pass
    profile_match = _HJ_PROFILE_RE.search(url)
    if profile_match:
        try:
            return _hj_profile_card(url, profile_match.group(1))
        except Exception:  # noqa: BLE001, S110 - 任何深解析异常（含网络层）降级浅卡。
            pass
    if "/works/" in url:
        return build_parsed_content(
            platform="huajia",
            item_id="",
            item_kind="works",
            title="画加作品广场",
            summary="（作品广场为列表页，机器人暂不支持整页抓取；"
            "想看哪个作品/商品，请把具体链接发我）",
            canonical_url=url,
            parse_depth="shallow",
            page_type="works",
            badge="画加",
        )
    return _spa_link_card(url, platform="huajia", item_kind="page", label="网易画加")
