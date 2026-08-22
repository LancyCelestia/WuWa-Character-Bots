"""平台解析共用的结果类型（避免模块间循环导入）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlatformParse:
    """平台解析结果（渲染层用）。"""

    platform: str
    item_id: str
    item_kind: str
    title: str
    author_name: str = ""
    summary: str = ""
    cover_url: str = ""
    audio_url: str = ""
    canonical_url: str = ""
    stats: dict = field(default_factory=dict)
    parse_depth: str = "deep"
    page_type: str = ""
    badge: str = ""
    detail: dict = field(default_factory=dict)
