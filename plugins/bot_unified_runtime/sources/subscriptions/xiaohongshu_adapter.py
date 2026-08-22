"""小红书订阅源 adapter：基于 Playwright 抓取层解析用户主页最新笔记。

目标仅支持创作者主页链接与 ``xiaohongshu:creator:<id>`` URI；
``explore`` 笔记链接不在订阅范围内，统一拒绝。抓取优先通过
``capture_json`` 监听 ``user_posted`` 接口，失败时退化为页面 HTML
正则提取；两次都失败则返回 degraded 结果，不泄漏底层异常正文。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    SourceFetchResult,
    SubscriptionCursor,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.fetchers.playwright_backend import (
    PlaywrightFetchBackend,
)

_PROFILE_RE = re.compile(r"xiaohongshu\.com/user/profile/([0-9a-zA-Z]+)")
_EXPLORE_RE = re.compile(r"xiaohongshu\.com/explore/([0-9a-f]+)")
_CREATOR_URI_PREFIX = "xiaohongshu:creator:"
_USER_POSTED_FILTER = "/api/sns/web/v1/user_posted"
_UNSUPPORTED_ERROR = "playwright 不可用，无法轮询小红书"
_EXTRACT_FAILED_ERROR = "未能从页面提取笔记"
_MAX_HTML_ITEMS = 6


class XiaohongshuAdapter:
    """小红书创作者主页订阅适配器。"""

    platform = "xiaohongshu"
    target_kinds = ("creator",)
    LIVE_POLL = False

    def __init__(self, backend: Any = None) -> None:
        self.backend = backend if backend is not None else PlaywrightFetchBackend()

    def resolve_target(self, url: str) -> dict[str, str]:
        """解析用户主页链接或 ``xiaohongshu:creator:<id>`` URI。"""
        profile_match = _PROFILE_RE.search(url or "")
        if profile_match:
            target_id = profile_match.group(1)
            return {
                "platform": self.platform,
                "target_kind": "creator",
                "target_id": target_id,
                "target_name": target_id,
            }
        if _EXPLORE_RE.search(url or ""):
            raise ValueError("小红书订阅仅支持用户主页链接")
        if (url or "").startswith(_CREATOR_URI_PREFIX):
            target_id = url[len(_CREATOR_URI_PREFIX):].strip()
            if target_id:
                return {
                    "platform": self.platform,
                    "target_kind": "creator",
                    "target_id": target_id,
                    "target_name": target_id,
                }
        raise ValueError(f"无法识别的小红书订阅目标：{url}")

    def _cookies_from_header(self, header: str) -> list[dict[str, Any]]:
        """把 ``name=value; name2=value2`` 解析为 Playwright cookie 列表。"""
        cookies: list[dict[str, Any]] = []
        for chunk in (header or "").split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            name, value = chunk.split("=", 1)
            cookies.append(
                {
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".xiaohongshu.com",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": False,
                    "secure": False,
                    "sameSite": "Lax",
                }
            )
        return cookies

    @staticmethod
    def _extract_notes(payload: Any) -> list[Any]:
        """兼容多种载荷形状，返回笔记列表（取不到返回空列表）。"""
        if isinstance(payload, dict):
            candidates = (
                payload.get("data", {}).get("notes"),
                payload.get("notes"),
                payload.get("data", {}).get("user_posted", {}).get("notes"),
            )
            for candidate in candidates:
                if isinstance(candidate, list):
                    return candidate
            return []
        if isinstance(payload, list):
            for entry in payload:
                notes = XiaohongshuAdapter._extract_notes(entry)
                if notes:
                    return notes
            return payload
        return []

    @staticmethod
    def _publish_time(note: dict[str, Any]) -> str:
        value = note.get("publish_time") or note.get("time")
        if value is None or value == "":
            return ""
        return str(value)

    def _build_item(
        self, note: dict[str, Any], spec: SubscriptionSpec
    ) -> NormalizedSubscriptionItem:
        note_id = str(note.get("note_id") or "")
        note_type = str(note.get("type") or "").lower()
        kind = "video" if note_type == "video" else "note"

        cover = note.get("cover")
        if isinstance(cover, dict):
            cover_url = str(cover.get("url") or "")
        else:
            cover_url = str(cover or "")

        interact_info = note.get("interact_info")
        stats: dict[str, Any] = {}
        if isinstance(interact_info, dict):
            for key, label in (
                ("liked_count", "点赞"),
                ("collected_count", "收藏"),
                ("comment_count", "评论"),
            ):
                value = interact_info.get(key)
                if value is not None:
                    stats[label] = value

        user = note.get("user")
        author_name = ""
        if isinstance(user, dict):
            author_name = str(user.get("nickname") or "")
        if not author_name:
            author_name = str(spec.target_name or "")

        return NormalizedSubscriptionItem(
            item_id=note_id,
            kind=kind,
            title=str(note.get("display_title") or note.get("title") or ""),
            url=f"https://www.xiaohongshu.com/explore/{note_id}",
            author_name=author_name,
            cover_url=cover_url,
            stats=stats,
        )

    @staticmethod
    def _build_cursor(
        anchor: dict[str, Any], spec: SubscriptionSpec
    ) -> SubscriptionCursor | None:
        note_id = str(anchor.get("note_id") or "")
        if not note_id:
            return None
        return SubscriptionCursor(
            spec_id=spec.id,
            last_item_id=note_id,
            last_timestamp=XiaohongshuAdapter._publish_time(anchor),
        )

    def _filter_notes(
        self,
        notes: list[Any],
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
    ) -> tuple[list[NormalizedSubscriptionItem], SubscriptionCursor | None]:
        """按新到旧切分：遇到游标条目即停止且不含该条。"""
        anchor = next(
            (note for note in notes if str(note.get("note_id") or "")),
            None,
        )
        last_item_id = cursor.last_item_id if cursor is not None else ""
        items: list[NormalizedSubscriptionItem] = []
        for note in notes:
            note_id = str(note.get("note_id") or "")
            if not note_id:
                continue
            if last_item_id and note_id == last_item_id:
                break
            items.append(self._build_item(note, spec))
        new_cursor = self._build_cursor(anchor, spec) if anchor else None
        return items, new_cursor

    def _extract_html_items(
        self, html: str, spec: SubscriptionSpec
    ) -> list[NormalizedSubscriptionItem]:
        """从页面 HTML 尽力提取 noteId/title 对，最多 6 条。"""
        note_ids = re.findall(r'"noteId":"([^"]*)"', html or "")
        titles = re.findall(r'"title":"([^"]*)"', html or "")
        items: list[NormalizedSubscriptionItem] = []
        for note_id, title in zip(note_ids, titles):
            if not note_id or len(items) >= _MAX_HTML_ITEMS:
                continue
            items.append(
                NormalizedSubscriptionItem(
                    item_id=note_id,
                    kind="note",
                    title=title,
                    url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    author_name=str(spec.target_name or ""),
                )
            )
        return items

    async def fetch_latest(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        ctx: dict[str, Any],
    ) -> SourceFetchResult:
        """增量拉取最新笔记；backend 同步调用通过 to_thread offload。"""
        if self.backend is None or not getattr(self.backend, "available", False):
            return SourceFetchResult(
                items=[],
                health_state="unsupported",
                error=_UNSUPPORTED_ERROR,
            )

        cookies = self._cookies_from_header(ctx.get("cookie_header") or "")
        profile_url = f"https://www.xiaohongshu.com/user/profile/{spec.target_id}"

        try:
            payload = await asyncio.to_thread(
                self.backend.capture_json,
                profile_url,
                cookies=cookies,
                json_filter=_USER_POSTED_FILTER,
                timeout_ms=30000,
            )
        except Exception:  # noqa: BLE001 - 统一走 HTML 兜底。
            payload = None

        if isinstance(payload, (dict, list)):
            notes = self._extract_notes(payload)
            if notes:
                items, new_cursor = self._filter_notes(notes, spec, cursor)
                return SourceFetchResult(
                    items=items,
                    new_cursor=new_cursor,
                    health_state="healthy",
                    error="",
                )

        try:
            _, html = await asyncio.to_thread(
                self.backend.fetch_html,
                profile_url,
                cookies=cookies,
                timeout_ms=30000,
            )
        except Exception as exc:  # noqa: BLE001 - 不泄漏底层异常正文。
            return SourceFetchResult(
                items=[],
                health_state="degraded",
                error=f"{type(exc).__name__}",
            )

        items = self._extract_html_items(html, spec)
        if not items:
            return SourceFetchResult(
                items=[],
                health_state="degraded",
                error=_EXTRACT_FAILED_ERROR,
            )
        return SourceFetchResult(items=items, health_state="healthy", error="")


ADAPTERS = [XiaohongshuAdapter()]