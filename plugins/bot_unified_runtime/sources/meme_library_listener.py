"""群聊图片监听：异步下载图片 → MD5 去重入库 → 可选 VLM 打标。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

TAG_PROMPT = (
    "你是一个图片分析助手。请分析这张图片并返回JSON格式的标签信息。"
    "请返回以下格式的JSON(不要包含其他内容）："
    '{"is_meme": true, "description":"简短描述图片内容(20字以内）",'
    '"emotion_tags":["情绪标签1","情绪标签2"],'
    '"scene_tags":["场景标签1","场景标签2"],'
    '"persona_hint": "common", "nsfw_score":0.0}'
    "字段说明：is_meme 是否为表情包（带文字/配文的图片、表情包、梗图等），"
    "普通照片/风景/人物写真/截图/二次元/美女填 false；description 简短描述；"
    "emotion_tags 情绪标签；scene_tags 场景标签；persona_hint 建议人格归属，"
    "不确定填 common；nsfw_score 0.0~1.0。只返回JSON，不要有其他文字。"
)

_EXT_BY_CONTENT_TYPE = {
    "image/gif": "gif",
    "image/webp": "webp",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}
_URL_EXT_RE = re.compile(r"\.(gif|webp|png|jpe?g)(?:$|[?#])", re.IGNORECASE)

# 后台打标任务登记表：持有引用防止被 GC，done 回调负责收割异常。
_VLM_TASKS: set[asyncio.Task[None]] = set()


def _spawn_vlm_task(store: Any, config: Any, md5: str, image_bytes: bytes) -> None:
    try:
        task = asyncio.create_task(_tag_with_vlm(store, config, md5, image_bytes))
    except RuntimeError:
        return
    _VLM_TASKS.add(task)

    def _on_done(done: asyncio.Task[None]) -> None:
        _VLM_TASKS.discard(done)
        if done.cancelled():
            return
        # _tag_with_vlm 内部已捕获异常，这里只做兜底收割，避免未检索异常。
        done.exception()

    task.add_done_callback(_on_done)


def _segment_urls(message_segments: list[Any]) -> list[str]:
    urls: list[str] = []
    for segment in message_segments or []:
        segment_type = getattr(segment, "type", None)
        if isinstance(segment, dict):
            segment_type = segment.get("type")
        data = getattr(segment, "data", None)
        if isinstance(segment, dict):
            data = segment.get("data", {})
        if segment_type != "image" or not isinstance(data, dict):
            continue
        url = str(data.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


async def _download_once(url: str, *, max_bytes: int, proxy: str) -> tuple[bytes, str] | None:
    import httpx

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(12.0, connect=8.0),
        "follow_redirects": True,
        "headers": {"User-Agent": "Mozilla/5.0"},
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**client_kwargs) as client, client.stream(
            "GET", url
        ) as response:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("content-type", "")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    chunks.append(chunk)
                if not chunks:
                    return None
                return b"".join(chunks), content_type
    except Exception:  # noqa: BLE001 - 下载异常静默返回 None。
        return None


def _resolve_vision_config(config: Any) -> dict[str, str]:
    """识图模型预制接口：优先注册表预设，兼容旧字段；api_key 支持 env:VAR。"""
    import os

    preset_name = str(getattr(config, "bot_meme_library_vlm_preset", "deepseek-vision") or "")
    registry = getattr(config, "bot_vision_model_registry", None) or {}
    preset = registry.get(preset_name) if isinstance(registry, dict) else None
    model = str((preset or {}).get("model") or getattr(config, "bot_meme_library_vlm_model", "") or "")
    base_url = str((preset or {}).get("base_url") or getattr(config, "bot_meme_library_vlm_base_url", "") or "").rstrip("/")
    api_key = str((preset or {}).get("api_key") or getattr(config, "bot_meme_library_vlm_api_key", "") or "")
    if api_key.startswith("env:"):
        api_key = os.environ.get(api_key[4:].strip(), "")
    return {"model": model, "base_url": base_url, "api_key": api_key}


async def _tag_with_vlm(store: Any, config: Any, md5: str, image_bytes: bytes) -> None:
    """异步打标（失败静默）：更新描述/标签/NSFW 与权重；高危 NSFW 直接删除。"""
    import httpx

    vision = _resolve_vision_config(config)
    model = vision["model"]
    base_url = vision["base_url"]
    api_key = vision["api_key"]
    if not (model and base_url and api_key):
        return
    data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TAG_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 300,
    }
    try:
        async with httpx.AsyncClient(timeout=float(getattr(config, "bot_meme_library_vlm_timeout_seconds", 20) or 20)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if response.status_code != 200:
                return
            body = response.json()
            content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:  # noqa: BLE001 - 打标接口异常静默放弃本张图片。
        return
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return
        tags = json.loads(match.group(0))
        nsfw_score = max(0.0, min(1.0, float(tags.get("nsfw_score", 0.0) or 0.0)))
        delete_threshold = float(
            getattr(config, "bot_meme_library_nsfw_delete", 0.8) or 0.8
        )
        if nsfw_score >= delete_threshold:
            # 淫秽色情直接删除，不存储也不可被发送。
            store.remove(md5)
            return
        store.apply_tags(
            md5,
            is_meme=bool(tags.get("is_meme", True)),
            description=str(tags.get("description", ""))[:60],
            emotion_tags=[str(item) for item in (tags.get("emotion_tags") or [])][:6],
            scene_tags=[str(item) for item in (tags.get("scene_tags") or [])][:6],
            persona_hint=str(tags.get("persona_hint", "common"))[:24],
            nsfw_score=nsfw_score,
        )
    except Exception:  # noqa: BLE001 - 入库异常静默忽略。
        return


async def absorb_event_images(bot: Any, event: Any, config: Any, store: Any) -> dict[str, Any]:
    """监听事件中的图片：异步下载、MD5 去重、入库、可选打标。"""
    enabled = bool(getattr(config, "bot_meme_library_enabled", False))
    if not enabled:
        return {"handled": False, "reason": "disabled"}
    session_id = str(getattr(event, "get_session_id", lambda: "")() or "")
    if "group" not in session_id:
        return {"handled": False, "reason": "not_group"}
    group_id = str(getattr(event, "group_id", "") or "")
    allowlist = [str(item) for item in (getattr(config, "bot_meme_library_group_allowlist", []) or [])]
    denylist = [str(item) for item in (getattr(config, "bot_meme_library_group_denylist", []) or [])]
    if denylist and group_id in denylist:
        return {"handled": False, "reason": "group_denied"}
    if allowlist and group_id not in allowlist:
        return {"handled": False, "reason": "group_not_allowed"}

    try:
        segments = list(event.get_message())
    except Exception:  # noqa: BLE001 - 消息提取失败按无图片处理。
        segments = []
    urls = _segment_urls(segments)
    if not urls:
        return {"handled": False, "reason": "no_image"}

    target_dir = Path(str(getattr(config, "bot_meme_library_dir", "data/meme_library") or ""))
    target_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(getattr(config, "bot_meme_library_max_file_bytes", 5242880) or 5242880)
    proxy = str(getattr(config, "bot_meme_library_proxy", "") or "")

    saved = 0
    for url in urls[:4]:
        result = await _download_once(url, max_bytes=max_bytes, proxy=proxy)
        if not result:
            continue
        image_bytes, content_type = result
        md5 = hashlib.md5(image_bytes).hexdigest()
        if store.exists(md5):
            continue
        ext = _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
        if not ext:
            match = _URL_EXT_RE.search(url)
            ext = (match.group(1) if match else "png").lower()
        path = target_dir / f"{md5}.{ext}"
        try:
            path.write_bytes(image_bytes)
        except OSError:
            continue
        store.add(md5=md5, path=str(path), ext=ext, group_id=group_id)
        saved += 1
        if getattr(config, "bot_meme_library_vlm_enabled", False):
            _spawn_vlm_task(store, config, md5, image_bytes)
    try:
        store.cleanup(
            max_files=int(getattr(config, "bot_meme_library_max_files", 20000) or 0),
            max_age_days=int(getattr(config, "bot_meme_library_max_age_days", 30) or 0),
        )
    except Exception:  # noqa: BLE001, S110 - 清理失败不影响入库结果。
        pass
    return {"handled": True, "reason": "saved", "saved": saved}
