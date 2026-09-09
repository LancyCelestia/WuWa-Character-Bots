"""通用卡片渲染的数据模型。

移植并精简自 astrbot_plugin_parser core/render_html/models.py
（https://github.com/Zhalslar/astrbot_plugin_parser，MIT License，
Copyright (c) 2024 Les Freire）。

保持“精简但字段完整”：RenderPayload / ForwardPayload 覆盖模板会用到的
全部字段并携带安全默认值；从任意部分字典合并时也不会缺字段。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ForwardPayload:
    """卡片内的转发内容块（与参考库字段一致）。"""

    name: str = ""
    avatar: str = ""
    pendant: str = ""
    text: str = ""
    image_urls: list[str] = field(default_factory=list)
    qrcode: str = ""
    url: str = ""
    title: str = ""
    type: str = ""
    platform_display: str = ""
    summary: str = ""
    uid: str = ""
    banner: str = ""
    signature: str = ""
    author_uuid: str = ""
    header_desc_oneline: str = ""
    follower_count: str = ""
    timestamp: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    pinned_comment: dict[str, Any] | None = None
    hot_comment: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderPayload:
    """通用卡片模板上下文；字段缺失时对应区块整体隐藏。"""

    # 身份 / 内容主体
    name: str = ""
    avatar: str = ""
    pendant: str = ""
    text: str = ""
    summary: str = ""
    title: str = ""
    type: str = ""
    page_type: str = ""
    platform: str = ""
    platform_display: str = ""
    url: str = ""
    uid: str = ""
    banner: str = ""
    image_urls: list[str] = field(default_factory=list)
    qrcode: str = ""
    cover_url: str = ""

    # Header 五行
    signature: str = ""
    author_uuid: str = ""
    header_desc_oneline: str = ""
    follower_count: str = ""
    timestamp: str = ""
    edit_timestamp: str = ""
    handle: str = ""
    bvid: str = ""
    av_id: str = ""
    official_badge: str = ""
    official_title: str = ""
    extra_uid: str = ""
    extra_url: str = ""
    extra_url_display: str = ""
    extra_dynamic_id: str = ""
    extra_status_id: str = ""
    extra_video_id: str = ""
    extra_live_id: str = ""
    extra_space_id: str = ""
    extra_favlist_id: str = ""
    extra_bangumi_id: str = ""
    extra_post_count: str = ""
    extra_post_label: str = "帖子"
    extra_members_count: str = ""
    extra_members_label: str = "会员"
    header_l1_badges: list[dict[str, Any]] = field(default_factory=list)
    header_l2_items: list[dict[str, Any]] = field(default_factory=list)
    header_l4_items: list[dict[str, Any]] = field(default_factory=list)
    author_stat_items: list[dict[str, Any]] = field(default_factory=list)

    # 统计栏（已知键由模板渲染，未知键走 stats_extra_items 通用遍历）
    stats: dict[str, Any] = field(default_factory=dict)
    # Keep creator metrics separate from media/video engagement metrics.
    author_stats: dict[str, Any] = field(default_factory=dict)
    video_stats: dict[str, Any] = field(default_factory=dict)
    stats_bar_items: list[dict[str, Any]] = field(default_factory=list)
    stats_extra_items: list[dict[str, Any]] = field(default_factory=list)

    # 视频 / 分 P
    video_duration: str = ""
    video_desc: str = ""
    video_pages: list[dict[str, Any]] = field(default_factory=list)

    # 评论
    pinned_comment: dict[str, Any] | None = None
    hot_comment: dict[str, Any] | None = None
    hot_comments: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    # 会员购参展嘉宾（detail.show.guests 投影）
    show_guests: list[dict[str, Any]] = field(default_factory=list)
    # 作者栏帖子/专栏计数的标签（B 站 post_count 语义是专栏数）
    stats_post_label: str = "帖子"

    # 转发
    forward: ForwardPayload | dict[str, Any] | None = None
    repost: Any = None

    # 直播间
    live_title: str = ""
    live_cover: str = ""
    live_screenshot: str = ""
    live_duration: str = ""
    live_area: str = ""
    live_tags: str = ""
    live_desc: str = ""
    live_viewers: int = 0
    live_rank: str = ""
    live_replay_views: int = 0
    live_popularity: int = 0

    # 平台主题色 / 页脚（默认中性灰，与 UNKNOWN_PLATFORM_COLOR 一致）
    platform_color: str = "#607080"
    platform_color_rgb: str = "96,112,128"
    platform_color_dark: str = "#4a5866"
    platform_color_light: str = "#eef1f4"
    platform_official_name: str = ""
    platform_footer_label: str = ""
    platform_logo_svg: str = ""
    platform_mark: str = ""
    platform_mark_style: str = ""
    bot_name: str = "AstrBot"
    bot_avatar_url: str = ""
    card_width: str = "1440px"
    font_scale: float = 1.0
    scale_factor: float = 1.0

    # 页面 / 主页资料（契约未提供时全部隐藏）
    total_views: str = ""
    user_likes: str = ""
    following_count: str = ""
    profile_birthday: str = ""
    profile_join_date: str = ""
    profile_level: str = ""
    profile_live_room: str = ""
    profile_tags: list[str] = field(default_factory=list)
    recent_posts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ForwardPayload", "RenderPayload"]
