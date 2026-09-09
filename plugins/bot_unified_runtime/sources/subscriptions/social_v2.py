"""V2 social subscription target resolvers.

The first implementation deliberately keeps fetching behind an explicit client
injection point. Target identity and capability declarations are stable even
when a provider requires credentials, browser automation, or an endpoint that
is temporarily unavailable.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, ClassVar

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionCursor,
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionSpec,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
)

_NOW = lambda: datetime.now(timezone.utc)


class TwitterGraphQLClient:
    """Authorized X/Twitter GraphQL timeline client.

    X rotates operation identifiers, so callers may provide current IDs through
    ``context['twitter_query_ids']`` or ``BOT_TWITTER_QUERY_IDS``.  The client
    never falls back to an anonymous timeline request.
    """

    # Operation ids and the public web bearer rotate independently.  Keep no
    # stale token in source; deployments may pin them or let discovery refresh.
    _DEFAULT_QUERY_IDS: ClassVar[dict[str, str]] = {}
    # 进程内 TTL 缓存：bundle 发现每进程一次（默认 1 小时），避免每个目标重复下载 JS。
    _CRED_CACHE_TTL_SECONDS: ClassVar[float] = 3600.0
    _discovered_credentials: ClassVar[tuple[float, str, dict[str, str]] | None] = None

    def __init__(
        self,
        *,
        json_getter: Callable[..., Any] | None = None,
        text_getter: Callable[..., Any] | None = None,
    ) -> None:
        self._json_getter = json_getter or http_get_json
        self._text_getter = text_getter or http_get_text

    @staticmethod
    def _cookie_parts(cookie: str) -> dict[str, str]:
        return {
            key.strip(): value.strip()
            for part in str(cookie or "").split(";")
            if "=" in part
            for key, value in [part.split("=", 1)]
            if key.strip() and value.strip()
        }

    @classmethod
    def _query_ids(cls, context: dict[str, Any]) -> dict[str, str]:
        configured = context.get("twitter_query_ids") or os.getenv("BOT_TWITTER_QUERY_IDS", "")
        if isinstance(configured, str):
            try:
                configured = json.loads(configured)
            except json.JSONDecodeError:
                configured = {}
        values = dict(cls._DEFAULT_QUERY_IDS)
        if isinstance(configured, dict):
            values.update({str(key): str(value) for key, value in configured.items() if value})
        for operation, env_name in (
            ("UserByScreenName", "BOT_TWITTER_USER_BY_SCREEN_NAME_QUERY_ID"),
            ("UserTweets", "BOT_TWITTER_USER_TWEETS_QUERY_ID"),
        ):
            if os.getenv(env_name):
                values[operation] = os.environ[env_name]
        return values

    @classmethod
    def _bearer_token(cls, context: dict[str, Any]) -> str:
        value = str(context.get("twitter_bearer_token") or os.getenv("BOT_TWITTER_BEARER_TOKEN", "")).strip()
        return value.removeprefix("Bearer ").strip()

    def _discover_web_credentials(
        self, *, proxy: str, timeout: float, cookie: str
    ) -> tuple[str, dict[str, str]]:
        """Discover the current web bearer and operation ids from x.com bundles."""
        _final_url, page = self._text_getter(
            "https://x.com/",
            timeout=timeout,
            cookie=cookie,
            proxy=proxy,
            referer="https://x.com/",
        )
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', page or "")
        bearer = ""
        operations: dict[str, str] = {}
        for script in scripts[-12:]:
            script_url = urllib.parse.urljoin("https://x.com/", script)
            try:
                _, source = self._text_getter(
                    script_url,
                    timeout=timeout,
                    cookie=cookie,
                    proxy=proxy,
                    referer="https://x.com/",
                )
            except (ParseHttpError, OSError, RuntimeError):
                continue
            if not bearer:
                match = re.search(r"AAAA[A-Za-z0-9%_-]{20,}", source)
                if match:
                    bearer = urllib.parse.unquote(match.group(0))
            for operation in ("UserByScreenName", "UserTweets"):
                match = re.search(
                    rf"queryId[\"']?\s*[:=]\s*[\"']([^\"']+)[\"'](?:(?!queryId).){{0,240}}(?:operationName|name)[\"']?\s*[:=]\s*[\"']{operation}[\"']",
                    source,
                )
                if match:
                    operations[operation] = match.group(1)
        return bearer, operations

    @staticmethod
    def _classify_error(exc: BaseException) -> tuple[str, bool, int | None]:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            retry_after = getattr(exc, "retry_after_seconds", None)
            try:
                retry_after = int(retry_after) if retry_after is not None else None
            except (TypeError, ValueError):
                retry_after = None
            return "rate_limited", True, retry_after
        if status_code in (401, 403):
            return "auth_required", False, None
        text = str(exc).lower()
        if "429" in text or "rate limit" in text or "too many" in text:
            retry_after = None
            match = re.search(r"retry[-_ ]after[=: ]+(\d+)", text)
            if match:
                retry_after = int(match.group(1))
            return "rate_limited", True, retry_after
        if any(marker in text for marker in ("401", "403", "unauthorized", "forbidden")):
            return "auth_required", False, None
        if any(
            marker in text
            for marker in (
                "suspended",
                "not found",
                "no user",
                "does not exist",
                "protected",
                "unavailable",
            )
        ):
            # 账号不存在/冻结/私密等：重试无意义，归为上游状态变化。
            return "upstream_changed", False, None
        if any(
            marker in text
            for marker in (
                "graphql",
                "query",
                "timeline",
                "invalid",
                "unknown",
                "removed",
                "cannot query",
            )
        ):
            return "upstream_changed", False, None
        return "network_error", True, None

    def _get_json(self, url: str, *, cookie: str, proxy: str, timeout: float, headers: dict[str, str]) -> Any:
        return self._json_getter(
            url,
            timeout=timeout,
            cookie=cookie,
            proxy=proxy,
            referer="https://x.com/",
            extra_headers=headers,
        )

    def _resolve_user_id(
        self,
        target: SubscriptionTarget,
        *,
        cookie: str,
        proxy: str,
        timeout: float,
        headers: dict[str, str],
        query_id: str,
    ) -> str:
        variables = urllib.parse.urlencode(
            {"variables": json.dumps({"screen_name": target.target_key, "withSafetyModeUserFields": True}, separators=(",", ":")),
             "features": json.dumps({"hidden_profile_subscriptions_enabled": True}, separators=(",", ":"))}
        )
        payload = self._get_json(
            f"https://x.com/i/api/graphql/{query_id}/UserByScreenName?{variables}",
            cookie=cookie,
            proxy=proxy,
            timeout=timeout,
            headers=headers,
        )
        result = (((payload or {}).get("data") or {}).get("user") or {}).get("result") or {}
        user_id = str(result.get("rest_id") or result.get("id_str") or "")
        if not user_id:
            raise ValueError("Twitter UserByScreenName returned no user id")
        return user_id

    def _ensure_discovered_credentials(
        self,
        bearer: str,
        query_ids: dict[str, str],
        *,
        proxy: str,
        timeout: float,
        cookie: str,
    ) -> tuple[str, dict[str, str]]:
        """query id / bearer 缺失时从 x.com bundle 发现；进程内 TTL 缓存兜底。"""
        if bearer and query_ids.get("UserByScreenName") and query_ids.get("UserTweets"):
            return bearer, query_ids
        cached = TwitterGraphQLClient._discovered_credentials
        if (
            cached is not None
            and time.monotonic() - cached[0] < self._CRED_CACHE_TTL_SECONDS
        ):
            merged = dict(query_ids)
            merged.update(cached[2])
            return bearer or cached[1], merged
        try:
            discovered_bearer, discovered_ids = self._discover_web_credentials(
                proxy=proxy, timeout=timeout, cookie=cookie
            )
        except (ParseHttpError, OSError, RuntimeError, TypeError, ValueError):
            discovered_bearer, discovered_ids = "", {}
        if (
            discovered_bearer
            and discovered_ids.get("UserByScreenName")
            and discovered_ids.get("UserTweets")
        ):
            TwitterGraphQLClient._discovered_credentials = (
                time.monotonic(),
                discovered_bearer,
                dict(discovered_ids),
            )
        merged = dict(query_ids)
        merged.update(discovered_ids)
        return bearer or discovered_bearer, merged

    def fetch_incremental(
        self,
        target: SubscriptionTarget,
        cursors: dict[str, Any],
        context: dict[str, Any],
    ) -> SubscriptionFetchResult:
        context = dict(context or {})
        cookie = str(context.get("cookie_header", "") or "")
        parts = self._cookie_parts(cookie)
        if not parts.get("auth_token") or not parts.get("ct0"):
            return SubscriptionFetchResult(
                health_state="auth_required", error_code="auth_required", retryable=False
            )
        timeout = float(context.get("timeout_seconds", 10.0) or 10.0)
        proxy = str(context.get("proxy", "") or "")
        bearer = self._bearer_token(context)
        query_ids = self._query_ids(context)
        if not bearer or not query_ids.get("UserByScreenName") or not query_ids.get("UserTweets"):
            bearer, query_ids = self._ensure_discovered_credentials(
                bearer, query_ids, proxy=proxy, timeout=timeout, cookie=cookie
            )
        if not bearer or not query_ids.get("UserByScreenName") or not query_ids.get("UserTweets"):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="upstream_changed", retryable=False
            )
        headers = {
            "Authorization": f"Bearer {bearer}",
            "x-csrf-token": parts["ct0"],
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "Accept": "application/json",
        }
        try:
            user_id = str((target.target_payload or {}).get("rest_id") or "")
            if not user_id:
                for cursor in (cursors or {}).values():
                    candidate = str(
                        getattr(cursor, "cursor_payload", {}).get("user_id", "") or ""
                    )
                    if candidate:
                        user_id = candidate
                        break
            if not user_id:
                user_id = self._resolve_user_id(
                    target,
                    cookie=cookie,
                    proxy=proxy,
                    timeout=timeout,
                    headers=headers,
                    query_id=query_ids["UserByScreenName"],
                )
            cursor = cursors.get("tweets") if cursors else None
            last_item_id = (
                str(getattr(cursor, "last_item_id", "") or "")
                if cursor is not None
                else ""
            )
            page_size = max(1, min(100, int(context.get("twitter_page_size", 40) or 40)))
            max_pages = max(1, min(10, int(context.get("twitter_max_pages", 3) or 3)))
            max_items = max(page_size, int(context.get("twitter_max_items", 100) or 100))
            items: list[ContentReference] = []
            newest = last_item_id
            next_page_cursor = ""
            hit_history = False
            # 每轮从最新页开始，单轮内沿 Bottom cursor 翻页；绝不把上一轮 Bottom
            # cursor 当作下一轮入口，否则会持续翻旧页。
            for _page in range(max_pages):
                variables: dict[str, Any] = {
                    "userId": user_id,
                    "count": page_size,
                    "includePromotedContent": False,
                    "withQuickPromoteEligibilityTweetFields": False,
                    "withVoice": False,
                }
                if next_page_cursor:
                    variables["cursor"] = next_page_cursor
                params = urllib.parse.urlencode(
                    {"variables": json.dumps(variables, separators=(",", ":")),
                     "features": json.dumps({"rweb_lists_timeline_redesign_enabled": True, "responsive_web_graphql_exclude_directive_enabled": True}, separators=(",", ":"))}
                )
                payload = self._get_json(
                    f"https://x.com/i/api/graphql/{query_ids['UserTweets']}/UserTweets?{params}",
                    cookie=cookie,
                    proxy=proxy,
                    timeout=timeout,
                    headers=headers,
                )
                if isinstance(payload, dict) and payload.get("errors"):
                    message = " ".join(
                        str(error.get("message") or "")
                        for error in payload["errors"]
                        if isinstance(error, dict)
                    )
                    raise ValueError(message or "Twitter GraphQL returned errors")
                (
                    page_items,
                    next_page_cursor,
                    _previous_cursor,
                    hit_history,
                ) = TwitterSubscriptionAdapterV2._parse_timeline_page(
                    payload, target, last_item_id
                )
                items.extend(page_items)
                for item in page_items:
                    if item.item_id.isdigit() and (
                        not newest.isdigit() or int(item.item_id) > int(newest)
                    ):
                        newest = item.item_id
                if (
                    hit_history
                    or not last_item_id
                    or not next_page_cursor
                    or len(items) >= max_items
                ):
                    break
            target.target_payload["rest_id"] = user_id
            cursor_payload: dict[str, Any] = {"user_id": user_id}
            if next_page_cursor:
                # 仅作诊断参考；下一轮入口永远是最新页，不消费该值。
                cursor_payload["next_cursor"] = next_page_cursor
            return SubscriptionFetchResult(
                items=items,
                cursors=[SubscriptionCursorV2(
                    target_id=target.id,
                    stream="tweets",
                    last_item_id=newest,
                    cursor_payload=cursor_payload,
                    updated_at=datetime.now(timezone.utc),
                )],
            )
        except (KeyError, TypeError, ValueError, ParseHttpError, RuntimeError) as exc:
            error_code, retryable, retry_after = self._classify_error(exc)
            return SubscriptionFetchResult(
                health_state="degraded" if error_code != "auth_required" else "auth_required",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=retry_after,
            )




def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_public_count(value: str | None) -> int | None:
    text = str(value or "").strip().upper().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith("K"):
        multiplier, text = 1000, text[:-1]
    elif text.endswith("M"):
        multiplier, text = 1000000, text[:-1]
    elif text.endswith("万"):
        multiplier, text = 10000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def _target(
    platform: str,
    kind: str,
    key: str,
    raw: str,
    *,
    now: datetime | None = None,
) -> SubscriptionTarget:
    timestamp = now or _NOW()
    return SubscriptionTarget(
        id=f"{platform}:{kind}:{key}",
        platform=platform,
        target_kind=kind,
        target_key=key,
        display_name=key,
        target_payload={"raw": raw},
        created_at=timestamp,
        updated_at=timestamp,
    )


class _BaseAdapter:
    platform = ""
    target_kinds = frozenset[str]()

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _fetch_text(self, target: SubscriptionTarget, context: dict[str, Any]) -> str:
        _final_url, body = http_get_text(
            self._target_url(target),
            timeout=float((context or {}).get("timeout_seconds", 10.0) or 10.0),
            cookie=str((context or {}).get("cookie_header", "") or ""),
            proxy=str((context or {}).get("proxy", "") or ""),
        )
        return body

    def _target_url(self, target: SubscriptionTarget) -> str:
        return str((target.target_payload or {}).get("raw") or "")

    async def _fetch_or_unsupported(
        self, target: SubscriptionTarget, cursors: dict[str, Any], context: dict[str, Any]
    ) -> SubscriptionFetchResult:
        if self.client is None:
            return SubscriptionFetchResult(
                health_state="unsupported",
                error_code="unsupported",
                retryable=False,
            )
        result = self.client.fetch_incremental(target, cursors, context)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, SubscriptionFetchResult):
            raise TypeError("subscription client must return SubscriptionFetchResult")
        return result


class BilibiliSubscriptionAdapterV2(_BaseAdapter):
    platform = "bilibili"
    target_kinds = frozenset({"creator", "live_room", "bangumi", "favorite", "collection"})

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if raw.startswith("bilibili:"):
            kind, _, key = raw.removeprefix("bilibili:").partition(":")
            if kind in self.target_kinds and key:
                return _target(self.platform, kind, key, raw)
        for pattern, kind in (
            (r"live\.bilibili\.com/(\d+)", "live_room"),
            (r"space\.bilibili\.com/(\d+)", "creator"),
            (r"bilibili\.com/bangumi/play/((?:ss|ep)\d+)", "bangumi"),
        ):
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                return _target(self.platform, kind, match.group(1), raw)
        raise ValueError("无法识别的 Bilibili 订阅目标")

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            from plugins.bot_unified_runtime.sources.subscriptions.bilibili_adapter import (
                BilibiliAdapter,
            )

            legacy = BilibiliAdapter()
            cursor_v2 = cursors.get("default") if cursors else None
            legacy_cursor = SubscriptionCursor(
                spec_id=target.id,
                last_item_id=str(getattr(cursor_v2, "last_item_id", "") or ""),
                last_timestamp=(
                    getattr(cursor_v2, "last_timestamp", None).isoformat()
                    if getattr(cursor_v2, "last_timestamp", None)
                    else ""
                ),
                cursor_payload=dict(getattr(cursor_v2, "cursor_payload", {}) or {}),
            )
            spec = SubscriptionSpec(
                id=target.id,
                platform=target.platform,
                target_kind=target.target_kind,
                target_id=target.target_key,
                target_name=target.display_name or target.target_key,
                created_by="v2",
            )
            result = await legacy.fetch_latest(spec, legacy_cursor, context)
        except (ImportError, ParseHttpError, TypeError, ValueError):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="network_error", retryable=True
            )
        items = [
            ContentReference(
                item_id=str(item.item_id),
                item_kind=str(item.kind),
                url=str(item.url),
                published_at=_parse_dt(str(item.published_at or "")),
                source_payload={
                    "title": item.title,
                    "summary": item.summary,
                    "cover_url": item.cover_url,
                    "stats": dict(item.stats or {}),
                },
            )
            for item in result.items
        ]
        old_cursor = result.new_cursor
        cursors_out = []
        if old_cursor is not None:
            cursors_out.append(SubscriptionCursorV2(
                target_id=target.id,
                stream="default",
                last_item_id=old_cursor.last_item_id,
                last_timestamp=_parse_dt(old_cursor.last_timestamp),
                cursor_payload=dict(old_cursor.cursor_payload or {}),
                updated_at=datetime.now(timezone.utc),
            ))
        return SubscriptionFetchResult(
            items=items,
            cursors=cursors_out,
            health_state=str(result.health_state or "healthy"),
        )


class XiaohongshuSubscriptionAdapterV2(_BaseAdapter):
    platform = "xiaohongshu"
    target_kinds = frozenset({"creator"})

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        match = re.search(r"xiaohongshu\.com/user/profile/([0-9A-Za-z]+)", raw)
        if not match and raw.startswith("xiaohongshu:creator:"):
            key = raw.removeprefix("xiaohongshu:creator:").strip()
        else:
            key = match.group(1) if match else ""
        if not key:
            raise ValueError("小红书订阅仅支持公开创作者主页")
        return _target(self.platform, "creator", key, raw)

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            from plugins.bot_unified_runtime.sources.subscriptions.xiaohongshu_adapter import (
                XiaohongshuAdapter,
            )

            legacy = XiaohongshuAdapter()
            cursor_v2 = cursors.get("default") if cursors else None
            legacy_cursor = SubscriptionCursor(
                spec_id=target.id,
                last_item_id=str(getattr(cursor_v2, "last_item_id", "") or ""),
                last_timestamp=(
                    getattr(cursor_v2, "last_timestamp", None).isoformat()
                    if getattr(cursor_v2, "last_timestamp", None)
                    else ""
                ),
            )
            spec = SubscriptionSpec(
                id=target.id,
                platform=target.platform,
                target_kind=target.target_kind,
                target_id=target.target_key,
                target_name=target.display_name or target.target_key,
                created_by="v2",
            )
            result = await legacy.fetch_latest(spec, legacy_cursor, context)
        except (ImportError, ParseHttpError, TypeError, ValueError):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="network_error", retryable=True
            )
        items = [
            ContentReference(
                item_id=str(item.item_id),
                item_kind=str(item.kind),
                url=str(item.url),
                source_payload={
                    "title": item.title,
                    "summary": item.summary,
                    "cover_url": item.cover_url,
                    "stats": dict(item.stats or {}),
                },
            )
            for item in result.items
        ]
        old_cursor = result.new_cursor
        cursors_out = []
        if old_cursor is not None:
            cursors_out.append(SubscriptionCursorV2(
                target_id=target.id,
                stream="default",
                last_item_id=old_cursor.last_item_id,
                last_timestamp=_parse_dt(old_cursor.last_timestamp),
                updated_at=datetime.now(timezone.utc),
            ))
        return SubscriptionFetchResult(
            items=items,
            cursors=cursors_out,
            health_state=str(result.health_state or "healthy"),
        )


class YouTubeSubscriptionAdapterV2(_BaseAdapter):
    platform = "youtube"
    target_kinds = frozenset({"channel", "playlist"})

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if raw.startswith("youtube:"):
            kind, _, key = raw.removeprefix("youtube:").partition(":")
            if kind in self.target_kinds and key:
                return _target(self.platform, kind, key, raw)
        match = re.search(r"youtube\.com/channel/(UC[0-9A-Za-z_-]+)", raw)
        if match:
            return _target(self.platform, "channel", match.group(1), raw)
        match = re.search(r"youtube\.com/playlist\?[^\s]*\blist=([0-9A-Za-z_-]+)", raw)
        if match:
            return _target(self.platform, "playlist", match.group(1), raw)
        match = re.search(r"youtube\.com/@([0-9A-Za-z_.-]+)", raw)
        if match:
            handle = match.group(1)
            # @handle 不是频道 id：先解析成真实 UC id 再走 channel target；
            # 解析失败回退现行为（key=handle），不抛异常、不阻塞订阅添加。
            channel_id = self._resolve_handle_channel_id(handle, ctx)
            return _target(self.platform, "channel", channel_id or handle, raw)
        raise ValueError("无法识别的 YouTube 频道或播放列表")

    @staticmethod
    def _resolve_handle_channel_id(handle: str, ctx: dict[str, Any]) -> str:
        """抓取 @handle 页面正文，解析真实 UC 频道 id；失败返回空串。"""
        try:
            _final_url, body = http_get_text(
                f"https://www.youtube.com/@{handle}",
                timeout=float((ctx or {}).get("timeout_seconds", 10.0) or 10.0),
                cookie=str((ctx or {}).get("cookie_header", "") or ""),
                proxy=str((ctx or {}).get("proxy", "") or ""),
            )
        except Exception:  # noqa: BLE001 - 网络异常按解析失败处理，走 handle 回退。
            return ""
        if not body:
            return ""
        match = re.search(r'"externalId":"(UC[0-9A-Za-z_-]+)"', body)
        if match:
            return match.group(1)
        match = re.search(r"channel/(UC[0-9A-Za-z_-]+)", body)
        if match:
            return match.group(1)
        return ""

    def _target_url(self, target: SubscriptionTarget) -> str:
        if target.target_kind == "channel":
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={target.target_key}"
        return f"https://www.youtube.com/feeds/videos.xml?playlist_id={target.target_key}"

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            body = self._fetch_text(target, context)
            root = ET.fromstring(body)
        except (ParseHttpError, ET.ParseError):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="invalid_payload", retryable=True
            )
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        items = []
        latest_id = ""
        latest_time = None
        for entry in root.findall("atom:entry", ns):
            video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
            if not video_id:
                continue
            title = html.unescape(entry.findtext("atom:title", default="", namespaces=ns) or "")
            published_raw = entry.findtext("atom:published", default="", namespaces=ns) or ""
            published = _parse_dt(published_raw)
            link = entry.find("atom:link", ns)
            url = str(link.attrib.get("href") if link is not None else f"https://www.youtube.com/watch?v={video_id}")
            items.append(ContentReference(item_id=video_id, item_kind="video", url=url, published_at=published, source_payload={"title": title}))
            if not latest_id:
                latest_id, latest_time = video_id, published
        cursor = SubscriptionCursorV2(
            target_id=target.id,
            stream=target.target_kind,
            last_item_id=latest_id,
            last_timestamp=latest_time,
            updated_at=datetime.now(timezone.utc),
        )
        return SubscriptionFetchResult(items=items, cursors=[cursor])


class TwitterSubscriptionAdapterV2(_BaseAdapter):
    platform = "twitter"
    target_kinds = frozenset({"creator"})

    def __init__(self, client: Any = None) -> None:
        super().__init__(client or TwitterGraphQLClient())

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if raw.startswith("twitter:creator:"):
            key = raw.removeprefix("twitter:creator:").strip()
        else:
            match = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]+)(?:/|$)", raw)
            key = match.group(1) if match else ""
        if not key:
            raise ValueError("无法识别的 X/Twitter 创作者")
        return _target(self.platform, "creator", key, raw)

    @staticmethod
    def parse_timeline_payload(
        payload: dict[str, Any], target: SubscriptionTarget, last_item_id: str = ""
    ) -> SubscriptionFetchResult:
        items, next_cursor, previous_cursor, _hit = (
            TwitterSubscriptionAdapterV2._parse_timeline_page(
                payload, target, last_item_id
            )
        )
        newest = max((item.item_id for item in items if item.item_id.isdigit()), default=last_item_id)
        cursor_payload = {"next_cursor": next_cursor} if next_cursor else {}
        if previous_cursor:
            cursor_payload["direction"] = previous_cursor
        return SubscriptionFetchResult(
            items=items,
            cursors=[SubscriptionCursorV2(
                target_id=target.id,
                stream="tweets",
                last_item_id=newest,
                cursor_payload=cursor_payload,
                updated_at=datetime.now(timezone.utc),
            )],
        )

    @staticmethod
    def _parse_timeline_page(
        payload: dict[str, Any],
        target: SubscriptionTarget,
        last_item_id: str = "",
    ) -> tuple[list[ContentReference], str, str, bool]:
        """解析单页 UserTweets。

        返回 (条目, Bottom cursor, Terminate direction, 是否触及 last_item_id
        之前的历史)。处理 TweetWithVisibilityResults 包裹、tombstone、promoted
        条目与会话 module 子项；置顶旧推文由 last_item_id 数值过滤挡下。
        """
        instructions = (
            payload.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        items: list[ContentReference] = []
        next_cursor = ""
        previous_cursor = ""
        state = {"hit_last": False}

        def append_tweet(raw_result: Any) -> None:
            if not isinstance(raw_result, dict):
                return
            # TweetWithVisibilityResults 把正文包在 result.tweet，rest_id 留在外层。
            inner = raw_result.get("tweet")
            if isinstance(inner, dict) and inner:
                merged = dict(inner)
                merged.setdefault("rest_id", raw_result.get("rest_id") or "")
                raw_result = merged
            item_id = str(raw_result.get("rest_id") or "")
            if not item_id:
                return
            if (
                last_item_id.isdigit()
                and item_id.isdigit()
                and int(item_id) <= int(last_item_id)
            ):
                state["hit_last"] = True
                return
            legacy = raw_result.get("legacy") or {}
            core = raw_result.get("core") or {}
            author_result = ((core.get("user_results") or {}).get("result") or {})
            author_legacy = author_result.get("legacy") or {}
            entities = legacy.get("entities") or {}
            extended = legacy.get("extended_entities") or {}
            media_entities = (
                extended.get("media") if isinstance(extended, dict) else None
            ) or (
                entities.get("media") if isinstance(entities, dict) else None
            ) or []
            media: list[dict[str, Any]] = []
            seen_urls: set[str] = set()
            for media_item in media_entities:
                if not isinstance(media_item, dict):
                    continue
                media_type = str(media_item.get("type") or "image")
                url = str(
                    media_item.get("media_url_https")
                    or media_item.get("media_url")
                    or ""
                )
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                entry: dict[str, Any] = {
                    "type": media_type,
                    "url": url,
                    "expanded_url": str(media_item.get("expanded_url") or ""),
                }
                sizes = media_item.get("sizes")
                large = sizes.get("large") if isinstance(sizes, dict) else None
                if isinstance(large, dict):
                    if large.get("w"):
                        entry["width"] = large.get("w")
                    if large.get("h"):
                        entry["height"] = large.get("h")
                video_info = media_item.get("video_info")
                if media_type in {"video", "animated_gif"} and isinstance(video_info, dict):
                    variants = [
                        v
                        for v in (video_info.get("variants") or [])
                        if isinstance(v, dict)
                    ]
                    best = max(
                        variants, key=lambda v: int(v.get("bitrate") or 0), default=None
                    )
                    if best is not None:
                        entry["video_url"] = str(best.get("url") or "")
                    entry["preview_image_url"] = str(
                        video_info.get("preview_image_url") or ""
                    )
                    duration = video_info.get("duration_millis")
                    if isinstance(duration, (int, float)) and duration > 0:
                        entry["duration_millis"] = int(duration)
                media.append(entry)
            profile = author_result.get("profile") or {}
            item_payload: dict[str, Any] = {
                "text": str(legacy.get("full_text") or ""),
                "author_id": str(author_result.get("rest_id") or ""),
                "author_handle": str(author_legacy.get("screen_name") or target.target_key),
                "author_name": str(author_legacy.get("name") or ""),
                "like_count": _parse_public_count(str(legacy.get("favorite_count") or "")) or 0,
                "repost_count": _parse_public_count(str(legacy.get("retweet_count") or "")) or 0,
                "comment_count": _parse_public_count(str(legacy.get("reply_count") or "")) or 0,
                "quote_count": _parse_public_count(str(legacy.get("quote_count") or "")) or 0,
                "bookmark_count": _parse_public_count(str(legacy.get("bookmark_count") or "")),
                "author_avatar": str(author_legacy.get("profile_image_url_https") or ""),
                "author_bio": str(profile.get("description") or author_legacy.get("description") or ""),
                "author_verified": bool(
                    author_legacy.get("verified") or author_result.get("is_blue_verified")
                ),
                "author_followers_count": author_legacy.get("followers_count"),
                "author_friends_count": author_legacy.get("friends_count"),
                "author_statuses_count": author_legacy.get("statuses_count"),
                "author_media_count": author_legacy.get("media_count"),
                "author_created_at": str(author_legacy.get("created_at") or ""),
                "media": media,
            }
            created_at = _parse_dt(str(legacy.get("created_at") or ""))
            items.append(ContentReference(
                item_id=item_id,
                item_kind="tweet",
                url=f"https://x.com/{author_legacy.get('screen_name') or target.target_key}/status/{item_id}",
                published_at=created_at,
                source_payload=item_payload,
            ))

        def consume_item_content(item_content: Any) -> None:
            if not isinstance(item_content, dict):
                return
            if "tombstone" in item_content or "itemContentPromoted" in item_content:
                # 值可能是空字典，必须按键存在性判断，不能用真值判断。
                return
            append_tweet((item_content.get("tweet_results") or {}).get("result"))

        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            for entry in instruction.get("entries", []) or []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("entryId") or "").startswith("promoted"):
                    continue
                content = entry.get("content") or {}
                if not isinstance(content, dict):
                    continue
                if content.get("cursorType") in {"Bottom", "ShowMore"}:
                    next_cursor = str(content.get("value") or next_cursor)
                    continue
                module_items = content.get("items")
                if isinstance(module_items, list):
                    for module_item in module_items:
                        if not isinstance(module_item, dict):
                            continue
                        nested = module_item.get("item") or {}
                        if isinstance(nested, dict):
                            consume_item_content(nested.get("itemContent"))
                    continue
                consume_item_content(content.get("itemContent"))
            if instruction.get("type") == "TimelineTerminateTimeline":
                previous_cursor = str((instruction.get("direction") or "") or previous_cursor)
        return items, next_cursor, previous_cursor, state["hit_last"]

    async def fetch_incremental(self, target, cursors, context):
        cookie = str((context or {}).get("cookie_header", "") or "")
        if "auth_token=" not in cookie or "ct0=" not in cookie:
            return SubscriptionFetchResult(
                health_state="auth_required", error_code="auth_required", retryable=False
            )
        if self.client is None:
            return SubscriptionFetchResult(
                health_state="auth_required", error_code="auth_required", retryable=False
            )
        return await self._fetch_or_unsupported(target, cursors, context)


class TelegramSubscriptionAdapterV2(_BaseAdapter):
    platform = "telegram"
    target_kinds = frozenset({"public_channel"})

    def _target_url(self, target: SubscriptionTarget) -> str:
        return f"https://t.me/s/{target.target_key}"

    def _parse_html(
        self, html_text: str, target: SubscriptionTarget, cursor: Any
    ) -> SubscriptionFetchResult:
        items: list[ContentReference] = []
        latest_id = ""
        latest_time: datetime | None = None
        blocks = [
            match.group(0)
            for match in re.finditer(
                r'<div[^>]+class="[^"]*tgme_widget_message_wrap[^"]*"[^>]*>'
                r'.*?(?=<div[^>]+class="[^"]*tgme_widget_message_wrap|$)',
                html_text or "",
                re.DOTALL,
            )
        ]
        if not blocks:
            blocks = [
                f'<div data-post="{post}">{body}'
                for post, body in re.findall(
                    r'<div[^>]+data-post="([^"]+)"[^>]*>(.*?)</div>',
                    html_text or "",
                    re.DOTALL,
                )
            ]
        last_item_id = str(getattr(cursor, "last_item_id", "") or "")
        for block in blocks:
            if 'data-pinned="1"' in block or "data-pinned='1'" in block:
                continue
            post = re.search(r'data-post=["\']([^"\']+)', block)
            if not post:
                continue
            item_id = post.group(1).rsplit("/", 1)[-1]
            if not item_id.isdigit() or (last_item_id.isdigit() and int(item_id) <= int(last_item_id)):
                continue
            text_match = re.search(r'class="[^"]*tgme_widget_message_text[^"]*">(.*?)</', block, re.DOTALL)
            body = re.sub(r"<[^>]+>", " ", text_match.group(1) if text_match else "")
            body = html.unescape(re.sub(r"\s+", " ", body)).strip()
            time_match = re.search(r'<time[^>]+datetime=["\']([^"\']+)', block)
            published = _parse_dt(time_match.group(1) if time_match else "")
            views_match = re.search(r'tgme_widget_message_views[^>]*>([^<]+)', block)
            view_count = _parse_public_count(views_match.group(1) if views_match else "")
            payload: dict[str, Any] = {}
            if view_count is not None:
                payload["view_count"] = view_count
            items.append(ContentReference(
                item_id=item_id,
                item_kind="post",
                url=f"https://t.me/{target.target_key}/{item_id}",
                published_at=published,
                source_payload={"text": body, **payload},
            ))
            if not latest_id or int(item_id) > int(latest_id):
                latest_id, latest_time = item_id, published
        return SubscriptionFetchResult(
            items=items,
            cursors=[SubscriptionCursorV2(
                target_id=target.id,
                stream="messages",
                last_item_id=latest_id or last_item_id,
                last_timestamp=latest_time,
                updated_at=datetime.now(timezone.utc),
            )],
        )

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if "+" in raw or raw.startswith("https://t.me/joinchat/"):
            raise ValueError("Telegram 订阅只支持公开频道")
        if raw.startswith("telegram:public_channel:"):
            key = raw.removeprefix("telegram:public_channel:").strip().lstrip("@")
        else:
            match = re.search(r"t\.me/(?:s/)?@?([A-Za-z0-9_]{4,})", raw)
            key = match.group(1) if match else ""
        if not key:
            raise ValueError("无法识别的 Telegram 公开频道")
        return _target(self.platform, "public_channel", key, raw)

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            body = self._fetch_text(target, context)
        except ParseHttpError:
            return SubscriptionFetchResult(
                health_state="degraded", error_code="network_error", retryable=True
            )
        cursor = cursors.get("messages") if cursors else None
        return self._parse_html(body, target, cursor)


class PixivSubscriptionAdapterV2(_BaseAdapter):
    platform = "pixiv"
    target_kinds = frozenset({"creator", "novel_creator", "novel_series"})

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if raw.startswith("pixiv:"):
            kind, _, key = raw.removeprefix("pixiv:").partition(":")
            if kind in self.target_kinds and key:
                return _target(self.platform, kind, key, raw)
        match = re.search(r"pixiv\.net/users/(\d+)", raw)
        if match:
            return _target(self.platform, "creator", match.group(1), raw)
        raise ValueError("无法识别的 Pixiv 创作者")

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            from plugins.bot_unified_runtime.sources.parsers.http_util import (
                http_get_json,
            )
            payload = http_get_json(
                f"https://www.pixiv.net/ajax/user/{target.target_key}/profile/all",
                timeout=float((context or {}).get("timeout_seconds", 10.0) or 10.0),
                cookie=str((context or {}).get("cookie_header", "") or ""),
                proxy=str((context or {}).get("proxy", "") or ""),
                referer="https://www.pixiv.net/",
            )
        except (ImportError, ParseHttpError):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="network_error", retryable=True
            )
        body = payload.get("body") if isinstance(payload, dict) else None
        if not isinstance(body, dict):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="invalid_payload", retryable=True
            )
        streams = {
            "novel": body.get("novels") if target.target_kind != "creator" else {},
            "illust": body.get("illusts") if target.target_kind != "novel_creator" else {},
            "manga": body.get("manga") if target.target_kind == "creator" else {},
        }
        items: list[ContentReference] = []
        cursors_out: list[SubscriptionCursorV2] = []
        for stream, value in streams.items():
            ids = [str(key) for key in value] if isinstance(value, dict) else []
            previous = str(getattr(cursors.get(stream), "last_item_id", "") or "") if cursors else ""
            for item_id in ids:
                if item_id == previous:
                    break
                kind = "novel" if stream == "novel" else "illust"
                path = "novel" if stream == "novel" else "artworks"
                items.append(ContentReference(
                    item_id=item_id,
                    item_kind=kind,
                    url=f"https://www.pixiv.net/{path}/{item_id}",
                    source_payload={"stream": stream},
                ))
            if ids:
                cursors_out.append(SubscriptionCursorV2(
                    target_id=target.id,
                    stream=stream,
                    last_item_id=ids[0],
                    updated_at=datetime.now(timezone.utc),
                ))
        return SubscriptionFetchResult(items=items, cursors=cursors_out)


class WeiboSubscriptionAdapterV2(_BaseAdapter):
    platform = "weibo"
    target_kinds = frozenset({"creator"})

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if raw.startswith("weibo:creator:"):
            key = raw.removeprefix("weibo:creator:").strip()
        else:
            match = re.search(r"weibo\.com/(?:u/)?(\d+)(?:/|$)", raw)
            key = match.group(1) if match else ""
        if not key:
            raise ValueError("无法识别的微博创作者")
        return _target(self.platform, "creator", key, raw)

    async def fetch_incremental(self, target, cursors, context):
        if self.client is not None:
            return await self._fetch_or_unsupported(target, cursors, context)
        try:
            from plugins.bot_unified_runtime.sources.parsers.http_util import (
                http_get_json,
            )
            payload = http_get_json(
                f"https://m.weibo.cn/api/container/getIndex?type=uid&value={target.target_key}",
                timeout=float((context or {}).get("timeout_seconds", 10.0) or 10.0),
                cookie=str((context or {}).get("cookie_header", "") or ""),
                proxy=str((context or {}).get("proxy", "") or ""),
                referer="https://m.weibo.cn/",
                extra_headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "MWeibo-Pwa": "1",
                },
            )
        except (ImportError, ParseHttpError):
            return SubscriptionFetchResult(
                health_state="degraded", error_code="network_error", retryable=True
            )
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        cards = data.get("cards") if isinstance(data, dict) else []
        cards = cards if isinstance(cards, list) else []
        previous = str(getattr(cursors.get("status"), "last_item_id", "") or "") if cursors else ""
        items: list[ContentReference] = []
        for card in cards:
            status = card.get("mblog") if isinstance(card, dict) else None
            if not isinstance(status, dict) or status.get("isTop"):
                continue
            item_id = str(status.get("id") or "")
            if not item_id or item_id == previous:
                break
            items.append(ContentReference(
                item_id=item_id,
                item_kind="post",
                url=f"https://weibo.com/{target.target_key}/{item_id}",
                source_payload={"text": str(status.get("text_raw") or status.get("text") or "")},
            ))
        cursor = SubscriptionCursorV2(
            target_id=target.id,
            stream="status",
            last_item_id=items[0].item_id if items else previous,
            updated_at=datetime.now(timezone.utc),
        )
        return SubscriptionFetchResult(items=items, cursors=[cursor])


ADAPTERS = [
    BilibiliSubscriptionAdapterV2(),
    XiaohongshuSubscriptionAdapterV2(),
    YouTubeSubscriptionAdapterV2(),
    TwitterSubscriptionAdapterV2(),
    TelegramSubscriptionAdapterV2(),
    PixivSubscriptionAdapterV2(),
    WeiboSubscriptionAdapterV2(),
]
