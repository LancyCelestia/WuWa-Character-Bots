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
- /表情帮助 / /meme help    用法

后端未启动时优雅降级提示，不抛异常；生成图片写入 data/memes/ 后
以图片形式走统一流水线发送。
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:表情|表情包|表情生成|表情包生成|表情制作|表情包制作|"
    r"表情製作|表情包製作|表情产生|表情包產生|meme|memes|meme generate)"
    r"(?:\s+(?P<rest>.+)|(?P<tail>帮助|幫助|help|用法|菜单|菜單|列表|list)?$)",
    re.IGNORECASE,
)
_LIST_VERBS = {"列表", "菜单", "全部", "list", "all", "keys"}
_HELP_VERBS = {"帮助", "用法", "help", "?"}

# 可注入的请求函数便于单元测试：request_fn(method, path, json=None) -> (status, body)
RequestFn = Callable[..., tuple[int, Any]]


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
        return "help", "", []
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
        "3. /表情帮助 —— 查看本说明\n"
        "需要本地运行 meme-generator-rs（默认 http://127.0.0.1:2233）。"
    )


def _default_request_fn(base_url: str, timeout_seconds: float) -> RequestFn:
    import httpx

    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

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
                body="表情包功能未启用。设置 BOT_MEME_API_ENABLED=true 并启动 meme-generator-rs 后重试。",
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

        status, body = requester(
            "POST",
            f"/memes/{key}",
            json={"images": [], "texts": texts, "options": {}},
        )
        if status != 200 or not isinstance(body, dict) or not body.get("image_id"):
            return _service_down_result(message, requester, base_url, key=key)
        image_id = str(body["image_id"])
        status, content = requester("GET", f"/image/{image_id}")
        if status != 200 or not isinstance(content, (bytes, bytearray)):
            return _service_down_result(message, requester, base_url, key=key)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(bytes(content)).hexdigest()[:12]
            path = out_dir / f"meme_{key}_{digest}.png"
            path.write_bytes(bytes(content))
            try:
                from plugins.bot_unified_runtime.runtime.cache_policy import enforce_quota

                enforce_quota(
                    out_dir,
                    max_bytes=int(getattr(config, "bot_meme_cache_max_bytes", 0) or 0),
                )
            except Exception:  # noqa: BLE001
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
) -> CapabilityResult:
    status, version = requester("GET", "/meme/version")
    if status == 200 and isinstance(version, (str, bytes)):
        hint = f"表情『{key}』参数不对或生成失败。" if key else "表情服务异常。"
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
