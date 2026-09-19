"""表情包生成能力（bot.meme）：对接本地 meme-generator-rs HTTP API。

协议与 MemeCrafters/meme-generator-rs v0.5.x 一致（MIT，仅自研客户端，
不引用任何插件代码）：

- GET  /meme/version          -> 文本版本
- GET  /meme/keys             -> ["petpet", ...]
- GET  /memes/{key}/info      -> 表情参数信息
- POST /image/upload          {"type":"data","data": base64} -> {"image_id": "..."}
- POST /memes/{key}           {"images":[{"name","id"}],"texts":[...],"options":{}} -> {"image_id": "..."}
- GET  /image/{image_id}      -> PNG 字节

命令（大小写均可、斜杠可省略）：
- /表情 列表                列出可用表情 key
- /表情 <key> <文字…>       生成文字表情（“｜”分隔多段文字）
- /表情 <key>（发图或 @人）  生成图片表情：消息内图片 > @头像 > 发送者头像
- /表情帮助 / /meme help    用法

后端未启动时优雅降级提示，不抛异常；生成图片写入 data/memes/ 后
以图片形式走统一流水线发送。QQ 多媒体签名 URL 第三方抓不到（A-8 同款
结论），需要图片时一律 bot 侧下载后以 data 形式上传。
"""

from __future__ import annotations

import base64
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.media.digest import media_digest

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:表情|表情包|表情生成|表情包生成|表情制作|表情包制作|"
    # meme(?! (?:random|stats)\b)：裸 meme/memes 不吃「meme random/meme stats」
    # （归 bot.meme_library，见 meme_library._COMMAND_RE/_STATS_RE；触发
    # 规格体检冲突 ×2 清账）。\b 保证只挡这两条短语，meme generate /
    # meme statistics 等其余后继仍归本能力（meme generate 备选在后兜底）。
    # (?! generate[a-z0-9]) / meme generate(?![a-z0-9])：右侧词边界
    # （wiki _alias_hit 先例），generateqq 类胶合不再落入 rest
    # （边界体检清账）；「meme generate」裸词仍走裸 meme 路径（rest 兜底），
    # parse 口径零改动。
    r"表情製作|表情包製作|表情产生|表情產生|表情包產生|"
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：biaoqing 族同音覆盖 製作/產生
    # 简繁词；(?![a-z0-9]) 右边界使 biaoqingbaox/bqbcs 类胶合不触发；
    # 帮助/用法/菜单/列表 tail 词族不拼音化（同批一 eat 参数词族先例），
    # 故 bz/cd/lb/yf 缩写一并放弃（bz 另有 八字/帮助 真冲突）。
    r"biaoqingbaoshengcheng(?![a-z0-9])|bqbs(?![a-z0-9])"
    r"|biaoqingbaochansheng(?![a-z0-9])|bqbc(?![a-z0-9])"
    r"|biaoqingbaozhizuo(?![a-z0-9])|bqbz(?![a-z0-9])"
    r"|biaoqingbao(?![a-z0-9])|bqb(?![a-z0-9])"
    r"|biaoqingshengcheng(?![a-z0-9])|bqsc(?![a-z0-9])"
    r"|biaoqingzhizuo(?![a-z0-9])|bqzz(?![a-z0-9])"
    r"|biaoqingchansheng(?![a-z0-9])|bqcs(?![a-z0-9])"
    r"|biaoqing(?![a-z0-9])"
    r"|meme(?! (?:random|stats)\b)(?! generate[a-z0-9])"
    r"|memes(?! (?:random|stats)\b)(?! generate[a-z0-9])|meme generate(?![a-z0-9]))"
    r"(?:\s+(?P<rest>.+)|(?P<tail>帮助|幫助|help|用法|菜单|菜單|列表|list)?$)",
    re.IGNORECASE,
)
_LIST_VERBS = {"列表", "菜单", "全部", "list", "all", "keys"}
_HELP_VERBS = {"帮助", "用法", "help", "?"}

# 可注入的请求函数便于单元测试：request_fn(method, path, json=None) -> (status, body)
RequestFn = Callable[..., tuple[int, Any]]
# 图片抓取注入缝：image_fetch_fn(url) -> bytes | None（None=抓取失败）。
ImageFetchFn = Callable[[str], "bytes | None"]

# 图片下载上限：表情图不需要更大；异常超大响应直接放弃。
_IMAGE_FETCH_MAX_BYTES = 8 * 1024 * 1024


def _collect_image_sources(message: IncomingMessage) -> list[str]:
    """图片来源优先级：消息内图片 URL → @群友 QQ 头像 → 发送者头像（仅 OneBot）。"""
    sources: list[str] = []
    for segment in message.raw_segments or []:
        seg_type = str(segment.get("type", "")).strip().lower()
        data = segment.get("data") or {}
        if seg_type == "image":
            url = str(data.get("url") or "").strip()
            if url.startswith("http"):
                sources.append(url)
        elif seg_type == "at":
            qq = str(data.get("qq") or "").strip()
            if qq and qq != "all":
                sources.append(f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640")
    if not sources and message.platform == "onebot":
        sender = str(message.sender_id or "").strip()
        if sender:
            sources.append(f"https://q1.qlogo.cn/g?b=qq&nk={sender}&s=640")
    return list(dict.fromkeys(sources))


def _default_image_fetch_fn(url: str) -> bytes | None:
    import httpx

    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        ) as client, client.stream("GET", url) as response:
            if response.status_code != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _IMAGE_FETCH_MAX_BYTES:
                    return None
                chunks.append(chunk)
        return b"".join(chunks) or None
    except Exception:  # noqa: BLE001 - 图片抓取失败按无图处理。
        return None


def is_meme_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def parse_meme_command(text: str) -> tuple[str, str, list[str]]:
    """返回 (动作, key, texts)。动作：help / list / render。"""
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a meme command")
    rest = (match.group("rest") or "").strip()
    tail = (match.groupdict().get("tail") or "").strip().lower()
    if tail in _LIST_VERBS:
        return "list", "", []
    if not rest or rest.lower() in _HELP_VERBS:
        return "help", "", []
    first, _, remainder = rest.partition(" ")
    if not remainder.strip():
        # “表情 列表”这种整体是关键词。
        if first.lower() in _LIST_VERBS:
            return "list", "", []
        # 纯 key（无文字）：可能是零文字的图片表情（如 petpet），
        # 也可能只是打错了 key——由能力层按 info 的 min_texts 区分。
        return "render", first, []
    if first.lower() in _LIST_VERBS:
        return "list", "", []
    texts = [item.strip() for item in remainder.split("｜") if item.strip()] or [
        remainder.strip()
    ]
    return "render", first, texts


def _usage_body() -> str:
    return (
        "表情包用法：\n"
        "1. /表情 列表 —— 列出可用表情 key\n"
        "2. /表情 <key> <文字> —— 生成表情，如『/表情 petpet 可爱』\n"
        "   多段文字用 ｜ 分隔：『/表情 文字表情 早上好｜晚上好』\n"
        "3. 需要图片的表情（如 petpet）：发图或 @ 群友后输命令，"
        "不带图时会用你的头像\n"
        "4. /表情帮助 —— 查看本说明\n"
        "需要本地运行 meme-generator-rs（默认 http://127.0.0.1:2233）。"
    )


_HTTP_CLIENTS: dict[tuple[str, float], Any] = {}
_HTTP_CLIENTS_LOCK = threading.Lock()


def _default_request_fn(base_url: str, timeout_seconds: float) -> RequestFn:
    import httpx

    key = (base_url.rstrip("/"), float(timeout_seconds))
    with _HTTP_CLIENTS_LOCK:
        client = _HTTP_CLIENTS.get(key)
        if client is None:
            # 进程内按 (base_url, timeout) 复用连接池——此前每次调用新建
            # Client 且从不 close，表情命令洪峰下泄漏连接。
            client = httpx.Client(base_url=key[0], timeout=timeout_seconds)
            _HTTP_CLIENTS[key] = client

    def request(method: str, path: str, json: dict | None = None) -> tuple[int, Any]:
        try:
            response = client.request(method.upper(), path, json=json)
        except httpx.HTTPError:
            return 0, None
        body: Any = None
        content_type = response.headers.get("content-type", "")
        try:
            if "json" in content_type:
                body = response.json()
            else:
                body = response.content
        except Exception:  # noqa: BLE001
            body = response.content
        return response.status_code, body

    return request


def build_meme_capability(
    config: Any | None = None,
    *,
    request_fn: RequestFn | None = None,
    output_dir: str | None = None,
    image_fetch_fn: ImageFetchFn | None = None,
) -> Any:
    enabled = bool(getattr(config, "bot_meme_api_enabled", False)) if config else False
    base_url = (
        str(getattr(config, "bot_meme_api_base_url", "http://127.0.0.1:2233") or "")
        .strip()
        .rstrip("/")
        if config
        else "http://127.0.0.1:2233"
    )
    timeout = float(getattr(config, "bot_meme_api_timeout_seconds", 15.0) or 15.0) if config else 15.0
    out_dir = Path(output_dir or (str(getattr(config, "bot_meme_api_output_dir", "data/memes") or "") if config else "data/memes"))

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        if not enabled:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body="表情包功能还没开，等管理员把它打开就能玩了。",
                audit_tags=["meme", "meme_disabled"],
            )
        try:
            action, key, texts = parse_meme_command(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body=_usage_body(),
                audit_tags=["meme", "meme_missing_query"],
            )
        if action == "help":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                title="表情包帮助",
                body=_usage_body(),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme", "meme_help"],
            )

        requester = request_fn or _default_request_fn(base_url, timeout)
        if action == "list":
            status, body = requester("GET", "/meme/keys")
            if status != 200 or not isinstance(body, list) or not body:
                return _service_down_result(message, requester, base_url)
            preview = "、".join(str(item) for item in body[:200])
            tail = f"\n…共 {len(body)} 个" if len(body) > 200 else f"\n共 {len(body)} 个"
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                title="可用表情",
                body=f"{preview}{tail}",
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme", f"meme_keys:{len(body)}"],
            )

        # 图片表情：按 info 的参数决定是否带图（info 拿不到时按纯文字处理，
        # 与旧版行为兼容）。图片一律 bot 侧下载后转 data 上传——QQ 多媒体
        # 签名 URL 服务端抓不到。
        image_fetch = image_fetch_fn or _default_image_fetch_fn
        min_images = max_images = min_texts = 0
        info_ok = False
        status, info = requester("GET", f"/memes/{key}/info")
        if status == 200 and isinstance(info, dict):
            params = info.get("params") or {}
            if isinstance(params, dict):
                try:
                    min_images = max(0, int(params.get("min_images") or 0))
                    max_images = max(0, int(params.get("max_images") or 0))
                    min_texts = max(0, int(params.get("min_texts") or 0))
                    info_ok = True
                except (TypeError, ValueError):
                    min_images = max_images = min_texts = 0

        # 纯 key 无文字：确属零文字表情才渲染；否则当打错 key 回帮助。
        if not texts and not (info_ok and min_texts == 0):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body=_usage_body(),
                audit_tags=["meme", "meme_missing_query"],
            )

        image_params: list[dict[str, str]] = []
        if max_images > 0 or min_images > 0:
            sources = _collect_image_sources(message)
            for source in sources[:max(1, max_images)]:
                payload = image_fetch(source)
                if not payload:
                    continue
                status, uploaded = requester(
                    "POST",
                    "/image/upload",
                    json={"type": "data", "data": base64.b64encode(payload).decode()},
                )
                if status == 200 and isinstance(uploaded, dict) and uploaded.get("image_id"):
                    image_params.append(
                        {"name": f"img{len(image_params)}.png", "id": str(uploaded["image_id"])}
                    )
            if len(image_params) < min_images:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme",
                    kind="text",
                    body=(
                        f"表情『{key}』需要 {min_images} 张图片：把图片和命令发在同一条"
                        "消息里，或 @ 一位群友（我会用 Ta 的头像）。"
                    ),
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PUBLIC,
                    audit_tags=["meme", "meme_need_images"],
                )

        status, body = requester(
            "POST",
            f"/memes/{key}",
            json={"images": image_params, "texts": texts, "options": {}},
        )
        if status != 200 or not isinstance(body, dict) or not body.get("image_id"):
            # 服务端错误体为 {"code":…,"message":"…"}（meme-generator-rs 实测），
            # 透传 message 让用户知道是缺文字/缺图还是 key 不存在。
            detail = ""
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("detail") or "").strip()[:160]
            return _service_down_result(message, requester, base_url, key=key, detail=detail)
        image_id = str(body["image_id"])
        status, content = requester("GET", f"/image/{image_id}")
        if status != 200 or not isinstance(content, (bytes, bytearray)):
            return _service_down_result(message, requester, base_url, key=key)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            # [:12] 截短是消费侧缓存文件名决定（蓝图 §3.1：算法不截短）。
            digest = media_digest(bytes(content))[:12]
            # petpet 等表情产物是 GIF 动图；按魔数定扩展名，避免 QQ 端按
            # 扩展名渲染失败。
            suffix = ".gif" if bytes(content)[:3] == b"GIF" else ".png"
            path = out_dir / f"meme_{key}_{digest}{suffix}"
            path.write_bytes(bytes(content))
            try:
                from plugins.bot_unified_runtime.runtime.cache_policy import (
                    enforce_quota,
                )

                enforce_quota(
                    out_dir,
                    max_bytes=int(getattr(config, "bot_meme_cache_max_bytes", 0) or 0),
                )
            except Exception:  # noqa: S110, BLE001 - 缓存配额清理失败不影响主链路。
                pass
        except OSError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body="表情生成成功，但本地保存失败（磁盘不可写）。",
                audit_tags=["meme", "meme_save_failed"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.meme",
            kind="mixed",
            title=f"表情包 {key}",
            body=f"已生成表情『{key}』（{len(texts)} 段文字）。",
            images=[{"file": str(path)}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["meme", f"meme_key:{key}", "meme_render"],
        )

    return capability


def _service_down_result(
    message: IncomingMessage,
    requester: RequestFn,
    base_url: str,
    *,
    key: str | None = None,
    detail: str = "",
) -> CapabilityResult:
    status, version = requester("GET", "/meme/version")
    if status == 200 and isinstance(version, (str, bytes)):
        hint = f"表情『{key}』参数不对或生成失败。" if key else "表情服务异常。"
        if detail and key:
            hint += f"原因：{detail}"
    else:
        hint = (
            f"表情包服务未启动或不可达（{base_url}）。"
            "请先启动 meme-generator-rs，再试一次。"
        )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.meme",
        kind="text",
        body=hint,
        audit_tags=["meme", "meme_backend_unavailable"],
    )

