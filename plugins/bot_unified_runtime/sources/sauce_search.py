"""SauceNAO 反搜图（对标 YetAnotherPicSearch 的能力空白补齐）。

GET https://saucenao.com/search.php?db=999&output_type=2&api_key=KEY&url=<图片URL>
返回 results[]：header.similarity + data.{title, member_name, source, ext_urls[]}。
key 配置：BOT_SAUCENAO_API_KEY 或 env:SAUCENAO_API_KEY。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from plugins.bot_unified_runtime.sources.search_api import resolve_search_secret

_API = "https://saucenao.com/search.php"
_SIMILARITY_RE = re.compile(r"([\d.]+)")


@dataclass(frozen=True)
class SauceHit:
    similarity: float
    title: str
    member: str
    source: str
    url: str


def search_saucenao(image_url: str, *, api_key: str = "", config: object | None = None) -> list[SauceHit]:
    """反搜一张图；失败/无结果返回空列表。"""
    if not image_url.startswith(("http://", "https://")):
        return []
    key = str(
        api_key
        or resolve_search_secret(
            getattr(config, "bot_saucenao_api_key", "") or "env:SAUCENAO_API_KEY", config
        )
    ).strip()
    if not key:
        return []
    try:
        response = httpx.get(
            _API,
            params={
                "db": "999",
                "output_type": "2",
                "api_key": key,
                "url": image_url,
            },
            timeout=15.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 - 反搜失败静默降级。
        return []
    hits: list[SauceHit] = []
    for item in (payload or {}).get("results") or []:
        header = item.get("header") or {}
        data = item.get("data") or {}
        raw_similarity = str(header.get("similarity") or "0")
        match = _SIMILARITY_RE.search(raw_similarity)
        similarity = float(match.group(1)) if match else 0.0
        ext_urls = data.get("ext_urls") or []
        hits.append(
            SauceHit(
                similarity=similarity,
                title=str(data.get("title") or data.get("material") or "").strip(),
                member=str(data.get("member_name") or data.get("author") or "").strip(),
                source=str(data.get("source") or data.get("engines") or "").strip(),
                url=str(ext_urls[0]) if ext_urls else "",
            )
        )
    hits.sort(key=lambda hit: hit.similarity, reverse=True)
    return hits[:3]
