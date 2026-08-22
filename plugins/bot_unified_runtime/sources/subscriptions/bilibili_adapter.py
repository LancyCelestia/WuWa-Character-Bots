"""B 站订阅平台 adapter。

pkgutil 自动发现 ``*_adapter.py`` 并读取模块级 ``ADAPTERS``。
本模块只依赖订阅契约与 ``sources/parsers`` 的轻量 HTTP/WBI 工具，
所有失败统一降级为 ``SourceFetchResult(health_state="degraded")``，
错误文本只保留异常类型名，避免泄漏敏感信息。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    PushCandidate,
    SourceFetchResult,
    SubscriptionCursor,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.parsers import wbi
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_PLATFORM = "bilibili"
_TARGET_KINDS = ("creator", "live_room", "bangumi", "favorite", "collection")

_MAIN_REFERER = "https://www.bilibili.com/"
_SPACE_REFERER = "https://space.bilibili.com/"
_LIVE_REFERER = "https://live.bilibili.com/"

_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_ARC_SEARCH_API = "https://api.bilibili.com/x/space/wbi/arc/search"
_FEED_SPACE_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
_PGC_SEASON_API = "https://api.bilibili.com/pgc/view/web/season"
_FAV_LIST_API = "https://api.bilibili.com/x/v3/fav/resource/list"
_SERIES_LIST_API = (
    "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
)
_SERIES_ARCHIVES_API = (
    "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
)
_LIVE_INFO_API = (
    "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
)

_LIVE_RE = re.compile(r"live\.bilibili\.com/(\d+)")
_SPACE_RE = re.compile(r"space\.bilibili\.com/(\d+)")
_FAV_FID_RE = re.compile(r"[?&]fid=(\d+)")
_SERIES_SID_RE = re.compile(r"[?&]sid=(\d+)")
_SERIES_ML_RE = re.compile(r"[?&]ml=(\d+)")
_BANGUMI_RE = re.compile(r"bangumi/play/((?:ss|ep)\d+)", re.IGNORECASE)
_BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")


def _require_code(payload: Any) -> None:
    """B 站接口统一校验：非 dict 或 code != 0 都视为解析失败。"""
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ParseHttpError("bilibili api code != 0")


def _filter_until(
    entries: Any,
    last_id: str,
    id_getter: Any,
) -> list[Any]:
    """按列表顺序（新→旧）保留到 ``last_id`` 匹配为止，且不含该条。"""
    if not isinstance(entries, list):
        return []
    if not last_id:
        return [*entries]
    kept: list[Any] = []
    for entry in entries:
        if str(id_getter(entry) or "") == str(last_id):
            break
        kept.append(entry)
    return kept


def _series_seasons(data: Any) -> list[Any]:
    if not isinstance(data, dict):
        return []
    items_lists = data.get("items_lists") or {}
    seasons = items_lists.get("seasons_list")
    if seasons is None:
        seasons = data.get("seasons_list")
    if seasons is None:
        seasons = data.get("list")
    return seasons if isinstance(seasons, list) else []


def _series_archives(data: Any) -> list[Any]:
    if not isinstance(data, dict):
        return []
    archives = data.get("archives")
    if archives is None:
        archives = data.get("list")
    return archives if isinstance(archives, list) else []


def _numeric_key(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class BilibiliAdapter:
    """bilibili 创作者 / 直播 / 番剧 / 收藏夹 / 合集订阅适配器。"""

    platform = _PLATFORM
    target_kinds = _TARGET_KINDS
    LIVE_POLL = True

    def __init__(self) -> None:
        # live_tick 不传 cursor，进程内按 spec_id 缓存上次直播状态。
        self._live_status: dict[str, int] = {}

    # ---------- resolve_target ----------

    def resolve_target(self, url: str) -> dict[str, str]:
        raw = str(url or "").strip()
        if not raw:
            raise ValueError("空订阅目标")

        if raw.lower().startswith("bilibili:"):
            return self._resolve_short_form(raw)

        live_match = _LIVE_RE.search(raw)
        if live_match:
            room_id = live_match.group(1)
            return {
                "platform": _PLATFORM,
                "target_kind": "live_room",
                "target_id": room_id,
                "target_name": room_id,
            }

        space_match = _SPACE_RE.search(raw)
        if space_match:
            mid = space_match.group(1)
            if "/favlist" in raw:
                fid_match = _FAV_FID_RE.search(raw)
                if not fid_match:
                    raise ValueError(f"收藏夹链接缺少 fid：{url}")
                fid = fid_match.group(1)
                return {
                    "platform": _PLATFORM,
                    "target_kind": "favorite",
                    "target_id": fid,
                    "target_name": fid,
                    "extra_mid": mid,
                }
            if "/channel/seriesdetail" in raw or "/lists" in raw:
                sid_match = _SERIES_SID_RE.search(raw)
                ml_match = _SERIES_ML_RE.search(raw)
                sid = (
                    sid_match.group(1)
                    if sid_match
                    else (ml_match.group(1) if ml_match else "")
                )
                return {
                    "platform": _PLATFORM,
                    "target_kind": "collection",
                    "target_id": sid or mid,
                    "target_name": mid,
                    "extra_mid": mid,
                }
            return {
                "platform": _PLATFORM,
                "target_kind": "creator",
                "target_id": mid,
                "target_name": mid,
            }

        bangumi_match = _BANGUMI_RE.search(raw)
        if bangumi_match:
            target_id = bangumi_match.group(1).lower()
            return {
                "platform": _PLATFORM,
                "target_kind": "bangumi",
                "target_id": target_id,
                "target_name": target_id,
            }

        bvid_match = _BVID_RE.search(raw)
        if bvid_match:
            bvid = bvid_match.group(0)
            payload = http_get_json(
                f"{_VIEW_API}?bvid={bvid}",
                referer=_MAIN_REFERER,
                cookie="",
            )
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise ValueError(f"B 站视频信息获取失败：{bvid}")
            owner = (payload.get("data") or {}).get("owner") or {}
            mid = owner.get("mid")
            if mid is None:
                raise ValueError(f"B 站视频缺少作者信息：{bvid}")
            name = str(owner.get("name") or str(mid))
            return {
                "platform": _PLATFORM,
                "target_kind": "creator",
                "target_id": str(mid),
                "target_name": name,
            }

        raise ValueError(f"无法识别的 B 站订阅目标：{url}")

    @staticmethod
    def _resolve_short_form(raw: str) -> dict[str, str]:
        rest = raw[len("bilibili:"):]
        kind, separator, target_id = rest.partition(":")
        kind = kind.strip().lower()
        target_id = target_id.strip()
        if not separator or kind not in _TARGET_KINDS or not target_id:
            raise ValueError(f"无法识别的 B 站订阅目标：{raw}")
        return {
            "platform": _PLATFORM,
            "target_kind": kind,
            "target_id": target_id,
            "target_name": target_id,
        }

    # ---------- fetch_latest ----------

    async def fetch_latest(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        ctx: dict[str, Any],
    ) -> SourceFetchResult:
        cookie_header = str((ctx or {}).get("cookie_header") or "")
        proxy = str((ctx or {}).get("proxy") or "")
        try:
            if spec.target_kind == "creator":
                return self._fetch_creator(spec, cursor, cookie_header, proxy)
            if spec.target_kind == "bangumi":
                return self._fetch_bangumi(spec, cursor, cookie_header, proxy)
            if spec.target_kind == "favorite":
                return self._fetch_favorite(spec, cursor, cookie_header, proxy)
            if spec.target_kind == "collection":
                return self._fetch_collection(spec, cursor, cookie_header, proxy)
            if spec.target_kind == "live_room":
                # 直播增量交给 fetch_live_statuses 轮询。
                return SourceFetchResult(items=[], health_state="healthy")
            raise ValueError(f"unsupported bilibili target_kind: {spec.target_kind}")
        except ParseHttpError as exc:
            return SourceFetchResult(
                items=[],
                health_state="degraded",
                error=type(exc).__name__,
            )

    def _wbi_get(
        self,
        base_url: str,
        params: dict[str, Any],
        cookie_header: str,
        proxy: str,
    ) -> Any:
        """先请求 WBI 签名 URL；失败直接拼参数重试一次，仍失败向上抛。"""
        try:
            signed_url = wbi.build_wbi_signed_url(
                base_url,
                dict(params),
                cookie_header=cookie_header,
                proxy=proxy,
            )
            payload = http_get_json(
                signed_url,
                referer=_MAIN_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
            _require_code(payload)
            return payload
        except ParseHttpError:
            fallback_url = f"{base_url}?{urlencode(dict(params))}"
            payload = http_get_json(
                fallback_url,
                referer=_MAIN_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
            _require_code(payload)
            return payload

    def _fetch_creator(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        cookie_header: str,
        proxy: str,
    ) -> SourceFetchResult:
        params: dict[str, Any] = {
            "mid": str(spec.target_id),
            "pn": "1",
            "ps": "20",
        }
        payload = self._wbi_get(_ARC_SEARCH_API, params, cookie_header, proxy)
        data = (payload or {}).get("data") or {}
        vlist = (data.get("list") or {}).get("vlist") or []
        vlist = vlist if isinstance(vlist, list) else []

        last_id = str(cursor.last_item_id) if cursor else ""
        kept = _filter_until(
            vlist,
            last_id,
            lambda item: str((item or {}).get("bvid") or ""),
        )
        items: list[NormalizedSubscriptionItem] = []
        for raw_item in kept:
            item = raw_item if isinstance(raw_item, dict) else {}
            bvid = str(item.get("bvid") or "")
            if not bvid:
                continue
            play = item.get("play")
            stats = {"播放": play} if play is not None else {}
            items.append(
                NormalizedSubscriptionItem(
                    item_id=bvid,
                    kind="video",
                    title=str(item.get("title") or ""),
                    url=f"https://www.bilibili.com/video/{bvid}",
                    author_name=spec.target_name,
                    cover_url=str(item.get("pic") or ""),
                    summary=str(item.get("description") or ""),
                    stats=stats,
                    published_at=str(item.get("created") or ""),
                )
            )

        first_dynamic_id = ""
        if cookie_header:
            try:
                first_dynamic_id = self._collect_creator_dynamics(
                    spec, cursor, cookie_header, proxy, items
                )
            except Exception:  # noqa: BLE001 - 动态为 best-effort，失败静默。
                first_dynamic_id = ""

        payload_state = dict(cursor.cursor_payload) if cursor else {}
        if first_dynamic_id:
            payload_state["dynamic_last_id"] = first_dynamic_id

        first = vlist[0] if vlist else {}
        first_id = str(first.get("bvid") or "")
        new_cursor = SubscriptionCursor(
            spec_id=spec.id,
            last_item_id=first_id if vlist else last_id,
            last_timestamp=str(first.get("created") or "")
            if vlist
            else (str(cursor.last_timestamp) if cursor else ""),
            cursor_payload=payload_state,
        )
        return SourceFetchResult(items=items, new_cursor=new_cursor)

    def _collect_creator_dynamics(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        cookie_header: str,
        proxy: str,
        items: list[NormalizedSubscriptionItem],
    ) -> str:
        params: dict[str, Any] = {
            "host_mid": str(spec.target_id),
            "offset": "0",
            "timezone_offset": "-480",
            "features": "itemOpusStyle",
        }
        payload = self._wbi_get(_FEED_SPACE_API, params, cookie_header, proxy)
        data = (payload or {}).get("data") or {}
        raw_items = data.get("items") or []
        raw_items = raw_items if isinstance(raw_items, list) else []

        previous_last = ""
        if cursor:
            previous_last = str(
                (cursor.cursor_payload or {}).get("dynamic_last_id") or ""
            )
        video_last = str(cursor.last_item_id) if cursor else ""
        ids: list[str] = []
        for raw_item in raw_items:
            item = raw_item if isinstance(raw_item, dict) else {}
            id_str = str(item.get("id_str") or "")
            if not id_str:
                continue
            if id_str == previous_last or id_str == video_last:
                break
            modules = item.get("modules") or {}
            dynamic_mod = modules.get("module_dynamic") or {}
            desc = dynamic_mod.get("desc") or {}
            text = str(desc.get("text") or "")
            ids.append(id_str)
            items.append(
                NormalizedSubscriptionItem(
                    item_id=id_str,
                    kind="dynamic",
                    title=text[:40] if text else "动态",
                    url=f"https://www.bilibili.com/opus/{id_str}",
                    author_name=spec.target_name,
                    summary=text,
                )
            )
        return ids[0] if ids else ""

    def _fetch_bangumi(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        cookie_header: str,
        proxy: str,
    ) -> SourceFetchResult:
        target_id = str(spec.target_id or "")
        lowered = target_id.lower()
        if lowered.startswith("ep"):
            ep_payload = http_get_json(
                f"{_PGC_SEASON_API}?ep_id={target_id}",
                referer=_MAIN_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
            _require_code(ep_payload)
            season_id = str(
                ((ep_payload or {}).get("result") or {}).get("season_id") or ""
            )
        else:
            season_id = (
                target_id[2:] if lowered.startswith("ss") else target_id
            )
        if not season_id:
            raise ParseHttpError("bilibili bangumi season_id missing")

        payload = http_get_json(
            f"{_PGC_SEASON_API}?season_id={season_id}",
            referer=_MAIN_REFERER,
            cookie=cookie_header,
            proxy=proxy,
        )
        _require_code(payload)
        result = (payload or {}).get("result") or {}
        season_title = str(result.get("title") or spec.target_name or "")
        new_ep = result.get("new_ep") or {}
        summary = str(new_ep.get("desc") or "")
        episodes = result.get("episodes") or []
        episodes = [ep for ep in episodes if isinstance(ep, dict)]

        def sort_key(pair: tuple[int, dict]) -> tuple[int, int, int]:
            index, episode = pair
            value = _numeric_key(episode.get("id"))
            return (0 if value is not None else 1, value or 0, index)

        ordered = sorted(enumerate(episodes, start=1), key=sort_key)
        labeled: list[tuple[dict, str]] = []
        for _, episode in ordered:
            number = episode.get("index") or episode.get("id")
            label = (
                episode.get("long_title")
                or episode.get("title")
                or f"第{number}话"
            )
            labeled.append((episode, str(label)))

        last_id = str(cursor.last_item_id) if cursor else ""
        items: list[NormalizedSubscriptionItem] = []
        for episode, label in reversed(labeled):
            ep_id = str(episode.get("id") or "")
            if last_id and ep_id == last_id:
                break
            items.append(
                NormalizedSubscriptionItem(
                    item_id=ep_id,
                    kind="episode",
                    title=f"{season_title} {label}".strip(),
                    url=str(episode.get("share_url") or ""),
                    summary=summary,
                )
            )

        raw_ids = [episode.get("id") for episode in episodes]
        numeric_ids = [
            int(value)
            for value in raw_ids
            if _numeric_key(value) is not None
        ]
        if numeric_ids:
            new_id = str(max(numeric_ids))
        elif raw_ids:
            new_id = str(raw_ids[0] or "")
        else:
            new_id = last_id
        new_cursor = SubscriptionCursor(
            spec_id=spec.id,
            last_item_id=new_id,
            cursor_payload=dict(cursor.cursor_payload) if cursor else {},
        )
        return SourceFetchResult(items=items, new_cursor=new_cursor)

    def _fetch_favorite(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        cookie_header: str,
        proxy: str,
    ) -> SourceFetchResult:
        params: dict[str, Any] = {
            "media_id": str(spec.target_id),
            "pn": "1",
            "ps": "20",
            "platform": "web",
            "web_location": "333.1296",
        }
        payload = http_get_json(
            f"{_FAV_LIST_API}?{urlencode(params)}",
            referer=_SPACE_REFERER,
            cookie=cookie_header,
            proxy=proxy,
        )
        _require_code(payload)
        medias = ((payload or {}).get("data") or {}).get("medias") or []
        medias = medias if isinstance(medias, list) else []

        last_id = str(cursor.last_item_id) if cursor else ""
        kept = _filter_until(
            medias,
            last_id,
            lambda item: str(
                (item or {}).get("bvid") or (item or {}).get("id") or ""
            ),
        )
        items: list[NormalizedSubscriptionItem] = []
        for raw_item in kept:
            item = raw_item if isinstance(raw_item, dict) else {}
            bvid = str(item.get("bvid") or "")
            item_id = bvid or str(item.get("id") or "")
            if not item_id:
                continue
            upper = item.get("upper") or {}
            items.append(
                NormalizedSubscriptionItem(
                    item_id=item_id,
                    kind="video",
                    title=str(item.get("title") or ""),
                    url=(
                        f"https://www.bilibili.com/video/{bvid}"
                        if bvid
                        else ""
                    ),
                    author_name=str(upper.get("name") or ""),
                    cover_url=str(item.get("cover") or ""),
                    published_at=str(item.get("pubtime") or ""),
                )
            )

        first = medias[0] if medias else {}
        new_cursor = SubscriptionCursor(
            spec_id=spec.id,
            last_item_id=str(
                first.get("bvid") or first.get("id") or ""
            )
            if medias
            else last_id,
            last_timestamp=str(first.get("pubtime") or "") if medias else "",
            cursor_payload=dict(cursor.cursor_payload) if cursor else {},
        )
        return SourceFetchResult(items=items, new_cursor=new_cursor)

    def _fetch_collection(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        cookie_header: str,
        proxy: str,
    ) -> SourceFetchResult:
        target_id = str(spec.target_id or "")
        target_name = str(spec.target_name or "").strip()
        payload_state = dict(cursor.cursor_payload) if cursor else {}
        mid = str(payload_state.get("mid") or "")
        if not mid and target_name.isdigit():
            mid = target_name
        season_id = str(payload_state.get("season_id") or "")

        if season_id:
            # 已有 season_id；mid 缺失时从 target_name 尽力补齐。
            if not mid and target_name.isdigit():
                mid = target_name
        elif mid and target_id != mid:
            # extra_mid（target_name）与 target_id 不同：target_id 即 season_id。
            season_id = target_id
        else:
            # resolve 时无 sid：target_id 存 mid，先列合集取首个 season_id。
            mid = mid or target_id
            series_payload = http_get_json(
                f"{_SERIES_LIST_API}?mid={mid}&page_num=1&page_size=30",
                referer=_SPACE_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
            _require_code(series_payload)
            seasons = _series_seasons(
                (series_payload or {}).get("data") or {}
            )
            chosen = seasons[0] if seasons else None
            if chosen is None:
                raise ParseHttpError("bilibili collection series list empty")
            season_id = str((chosen or {}).get("season_id") or "")
        if not season_id:
            raise ParseHttpError("bilibili collection season_id missing")

        payload = http_get_json(
            (
                f"{_SERIES_ARCHIVES_API}?mid={mid}"
                f"&season_id={season_id}&page_num=1&page_size=30"
            ),
            referer=_SPACE_REFERER,
            cookie=cookie_header,
            proxy=proxy,
        )
        _require_code(payload)
        archives = _series_archives((payload or {}).get("data") or {})

        last_id = str(cursor.last_item_id) if cursor else ""
        kept = _filter_until(
            archives,
            last_id,
            lambda item: str(
                (item or {}).get("bvid") or (item or {}).get("id") or ""
            ),
        )
        items: list[NormalizedSubscriptionItem] = []
        for raw_item in kept:
            item = raw_item if isinstance(raw_item, dict) else {}
            bvid = str(item.get("bvid") or "")
            item_id = bvid or str(item.get("id") or "")
            if not item_id:
                continue
            items.append(
                NormalizedSubscriptionItem(
                    item_id=item_id,
                    kind="video",
                    title=str(item.get("title") or ""),
                    url=(
                        f"https://www.bilibili.com/video/{bvid}"
                        if bvid
                        else ""
                    ),
                    author_name=spec.target_name,
                    cover_url=str(item.get("cover") or ""),
                    published_at=str(item.get("pubtime") or ""),
                )
            )

        first = archives[0] if archives else {}
        payload_state["season_id"] = season_id
        payload_state["mid"] = mid
        new_cursor = SubscriptionCursor(
            spec_id=spec.id,
            last_item_id=str(
                first.get("bvid") or first.get("id") or ""
            )
            if archives
            else last_id,
            last_timestamp=str(first.get("pubtime") or "") if archives else "",
            cursor_payload=payload_state,
        )
        return SourceFetchResult(items=items, new_cursor=new_cursor)

    # ---------- fetch_live_statuses ----------

    async def fetch_live_statuses(
        self,
        specs: list[SubscriptionSpec],
        ctx: dict[str, Any],
    ) -> list[PushCandidate]:
        cookie_header = str((ctx or {}).get("cookie_header") or "")
        proxy = str((ctx or {}).get("proxy") or "")
        candidates: list[PushCandidate] = []
        for spec in specs:
            if spec.target_kind != "live_room":
                continue
            try:
                payload = http_get_json(
                    f"{_LIVE_INFO_API}?room_id={spec.target_id}",
                    referer=_LIVE_REFERER,
                    cookie=cookie_header,
                    proxy=proxy,
                )
                _require_code(payload)
            except ParseHttpError:
                continue
            room = ((payload or {}).get("data") or {}).get("room_info") or {}
            status = 1 if room.get("live_status") == 1 else 0
            previous = int(self._live_status.get(spec.id, 0) or 0)
            room_id = str(spec.target_id or "")
            title = str(room.get("title") or "")
            if status == 1 and previous != 1:
                live_start_time = str(room.get("live_start_time") or "0")
                item = NormalizedSubscriptionItem(
                    item_id=f"live:{room_id}:{live_start_time}",
                    kind="live",
                    title=title,
                    url=f"https://live.bilibili.com/{room_id}",
                    summary=f"{spec.target_name} 开播了",
                )
                candidates.append(
                    PushCandidate(
                        spec_id=spec.id,
                        item=item,
                        reason="live_started",
                    )
                )
            elif status != 1 and previous == 1:
                item = NormalizedSubscriptionItem(
                    item_id=f"liveend:{room_id}",
                    kind="live",
                    title=title,
                    url=f"https://live.bilibili.com/{room_id}",
                    summary=f"{spec.target_name} 下播了",
                )
                candidates.append(
                    PushCandidate(
                        spec_id=spec.id,
                        item=item,
                        reason="live_ended",
                    )
                )
            self._live_status[spec.id] = status
        return candidates


ADAPTERS = [BilibiliAdapter()]
