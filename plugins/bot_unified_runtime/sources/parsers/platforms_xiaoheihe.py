"""小黑盒（www.xiaoheihe.cn）链接解析。

- 帖子（``/app/topic/link/{id}``、``/app/bbs/link/{id}``）：web 端公开接口
  ``https://api.xiaoheihe.cn/bbs/app/link/tree?link_id=``（匿名可用，需带
  web 端 hkey 签名参数），取标题 / 描述 / 作者 / 头像 / 互动数 / 话题。
- 游戏（``/app/topic/game/{platform}/{appid}``）：
  ``https://api.xiaoheihe.cn/game/get_game_infos/?appids=``，取游戏名 /
  头图 / 关注数 / 发行状态。
- 页面本身是纯 SPA 空壳（无 SSR、无 per-item og），接口失败时诚实降级浅卡。

hkey 签名算法逆向自 web 端 SPA bundle（``hkey = Tr(path, _time + 1, nonce)``）：
Tr 为「时间戳/路径/nonce 按 GF(2^8) MixColumns 混淆 + MD5 截断」的无密钥哈希，
本模块按公开于页面 JS 的同一算法用 Python 复现，不使用任何私有凭据。
"""

from __future__ import annotations

import hashlib
import random
import re
import time
import urllib.parse

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

_XHH_API_BASE = "https://api.xiaoheihe.cn"
_XHH_REFERER = "https://www.xiaoheihe.cn/"
_XHH_TOPIC_RE = re.compile(r"xiaoheihe\.cn/app/(?:topic/link|bbs/link)/(\d+)")
_XHH_GAME_RE = re.compile(r"xiaoheihe\.cn/app/topic/game/([a-z]+)/(\d+)")
_HKEY_TABLE = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


def _hkey_xtime(value: int) -> int:
    """GF(2^8) 乘 2（AES xtime），对应 JS 端 d3()。"""
    return ((value << 1) ^ 0x1B) & 0xFF if value & 0x80 else (value << 1)


def _hkey_mc(value: int) -> int:
    return _hkey_xtime(value) ^ value


def _hkey_f(value: int) -> int:
    return _hkey_mc(_hkey_xtime(value))


def _hkey_l(value: int) -> int:
    return _hkey_f(_hkey_mc(_hkey_xtime(value)))


def _hkey_sg(value: int) -> int:
    return _hkey_l(value) ^ _hkey_f(value) ^ _hkey_mc(value)


def _hkey_mix_column(chars: list[int]) -> list[int]:
    """对应 JS 端 kwe()：AES MixColumns（前 4 字节变换，其余原样保留）。"""
    t0 = _hkey_sg(chars[0]) ^ _hkey_l(chars[1]) ^ _hkey_f(chars[2]) ^ _hkey_mc(chars[3])
    t1 = _hkey_mc(chars[0]) ^ _hkey_sg(chars[1]) ^ _hkey_l(chars[2]) ^ _hkey_f(chars[3])
    t2 = _hkey_f(chars[0]) ^ _hkey_mc(chars[1]) ^ _hkey_sg(chars[2]) ^ _hkey_l(chars[3])
    t3 = _hkey_l(chars[0]) ^ _hkey_f(chars[1]) ^ _hkey_mc(chars[2]) ^ _hkey_sg(chars[3])
    result = list(chars)
    result[0], result[1], result[2], result[3] = t0, t1, t2, t3
    return result


def _hkey_im(text: str, take: int) -> str:
    """对应 JS 端 IM()：``table.slice(0, take)``（take 为负 = 去掉尾部 N 位）。"""
    prefix = _HKEY_TABLE[:take]
    return "".join(prefix[ord(ch) % len(prefix)] for ch in text)


def _hkey_om(text: str) -> str:
    return "".join(_HKEY_TABLE[ord(ch) % len(_HKEY_TABLE)] for ch in text)


def _hkey_interleave(parts: list[str]) -> str:
    out: list[str] = []
    for index in range(max(len(p) for p in parts)):
        for part in parts:
            if index < len(part):
                out.append(part[index])
    return "".join(out)


def hkey_sign(path: str, time_sec: int, nonce: str) -> str:
    """复现 web 端 Tr()：path 归一为 /a/b/ 后与时间戳、nonce 混淆摘要。"""
    normalized = "/" + "/".join(part for part in path.split("/") if part) + "/"
    mixed_time = _hkey_im(str(time_sec), -2)
    mixed_path = _hkey_om(normalized)
    mixed_nonce = _hkey_om(nonce)
    digest = hashlib.md5(
        _hkey_interleave([mixed_time, mixed_path, mixed_nonce])[:20].encode("utf-8")
    ).hexdigest()
    tail_sum = sum(_hkey_mix_column([ord(ch) for ch in digest[-6:]]))
    tail = f"{tail_sum % 100:02d}"
    head = _hkey_im(digest[:5], -4)
    return head + tail


def _xhh_get(path: str, params: dict, *, cookie_header: str = "") -> dict:
    """带 hkey/_time/nonce/web 通用参数的 GET；status != ok 抛 ParseHttpError。"""
    time_sec = int(time.time())
    nonce_seed = f"{time_sec}{random.randint(10**17, 10**18)}{random.randint(10**17, 10**18)}"
    nonce = hashlib.md5(nonce_seed.encode("utf-8")).hexdigest().upper()
    query = {
        "os_type": "web",
        "app": "heybox",
        "x_client_type": "web",
        "x_os_type": "Mac",
        "x_app": "heybox",
        "x_client_version": "999.999.999",
        "version": "999.0.4",
        "hkey": hkey_sign(path, time_sec + 1, nonce),
        "_time": time_sec,
        "nonce": nonce,
    }
    query.update(params)
    url = f"{_XHH_API_BASE}{path}?{urllib.parse.urlencode(query)}"
    payload = http_get_json(
        url,
        timeout=12,
        referer=f"{_XHH_REFERER}{path}",
        cookie=cookie_header,
    )
    if not isinstance(payload, dict):
        raise ParseHttpError(f"xiaoheihe {path} returned non-dict")
    if payload.get("status") != "ok":
        raise ParseHttpError(f"xiaoheihe {path} status={payload.get('status')}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ParseHttpError(f"xiaoheihe {path} missing result")
    return result


def _xhh_topic_card(url: str, link_id: str, *, cookie_header: str) -> ParsedContent:
    """帖子：/bbs/app/link/tree → 标题/描述/作者/互动/话题。"""
    result = _xhh_get("/bbs/app/link/tree", {"link_id": link_id}, cookie_header=cookie_header)
    link = result.get("link") or {}
    title = str(link.get("title") or "").strip()
    if not title:
        raise ParseHttpError("xiaoheihe topic missing title")
    user = link.get("user") or {}
    stats: dict = {}
    for key, label in (
        ("up", "点赞"),
        ("comment_num", "评论"),
        ("favour_count", "收藏"),
        ("forward_num", "转发"),
        ("click", "浏览"),
    ):
        value = link.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _format_epoch(link.get("create_at"))
    if publish_time:
        stats["发布时间"] = publish_time
    summary = str(link.get("description") or "").strip()
    if len(summary) > 300:
        summary = summary[:300] + "…"
    summary_lines: list[str] = []
    topics = [
        str(t.get("name") or "")
        for t in (link.get("topics") or [])
        if isinstance(t, dict) and t.get("name")
    ]
    if topics:
        summary_lines.append("话题：" + "、".join(topics[:5]))
    if publish_time:
        summary_lines.append(f"发布时间：{publish_time}")
    if summary:
        summary_lines.append(summary)
    author_detail: dict = {}
    if user.get("userid"):
        author_detail["uuid"] = str(user["userid"])
    if user.get("avatar"):
        author_detail["avatar"] = str(user["avatar"])
    detail: dict = {"topic": {"link_id": link_id}}
    if topics:
        detail["topic"]["tags"] = topics[:5]
    if author_detail:
        detail["author"] = author_detail
    return build_parsed_content(
        platform="xiaoheihe",
        item_id=link_id,
        item_kind="post",
        title=title,
        author_name=str(user.get("username") or ""),
        summary="\n".join(summary_lines),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="post",
        badge="小黑盒",
        detail=detail,
    )


def _xhh_game_card(url: str, platform: str, appid: str, *, cookie_header: str) -> ParsedContent:
    """游戏：/game/get_game_infos/ → 游戏名/头图/关注数/发行状态。"""
    result = _xhh_get(
        "/game/get_game_infos/", {"appids": appid}, cookie_header=cookie_header
    )
    base_infos = result.get("base_infos") or []
    game = base_infos[0] if isinstance(base_infos, list) and base_infos else {}
    name = str(game.get("name") or "").strip()
    if not name:
        raise ParseHttpError("xiaoheihe game missing name")
    stats: dict = {}
    follow_num = game.get("follow_num")
    if isinstance(follow_num, (int, float)):
        stats["关注"] = int(follow_num)
    summary_lines: list[str] = []
    genres = [
        str(g.get("name") or "") if isinstance(g, dict) else str(g)
        for g in (game.get("genres") or [])
    ]
    genres = [g for g in genres if g]
    if genres:
        summary_lines.append("类型：" + "、".join(genres[:6]))
    release = str(game.get("release_date") or "").strip()
    if release:
        summary_lines.append(f"发售：{release}")
    if game.get("is_release") is False:
        summary_lines.append("状态：未发售")
    detail = {
        "game": {
            "appid": appid,
            "platform": platform,
            "steam_appid": game.get("steam_appid"),
            "name": name,
        }
    }
    icon = str(game.get("image") or game.get("icon") or "")
    return build_parsed_content(
        platform="xiaoheihe",
        item_id=appid,
        item_kind="game",
        title=name,
        summary="\n".join(summary_lines),
        cover_url=icon,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="game",
        badge="小黑盒",
        detail=detail,
    )


def parse_xiaoheihe(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """小黑盒入口：帖子/游戏深解析，其余路径静态浅卡（页面无 og 可兜底）。"""
    topic_match = _XHH_TOPIC_RE.search(url)
    if topic_match:
        try:
            return _xhh_topic_card(url, topic_match.group(1), cookie_header=cookie_header)
        except ParseHttpError:
            pass
    game_match = _XHH_GAME_RE.search(url)
    if game_match:
        try:
            return _xhh_game_card(
                url, game_match.group(1), game_match.group(2), cookie_header=cookie_header
            )
        except ParseHttpError:
            pass
    label = "小黑盒"
    item_kind = "page"
    if "/app/topic/game/" in url:
        label, item_kind = "小黑盒游戏页", "game"
    elif "/app/" in url:
        label, item_kind = "小黑盒帖子", "post"
    return _spa_link_card(url, platform="xiaoheihe", item_kind=item_kind, label=label)
