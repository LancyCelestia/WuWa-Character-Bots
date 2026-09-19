"""群聊图片监听：异步下载图片 → MD5 去重入库 → 可选 VLM 打标。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

# SSRF 咽喉：本域**不**自建校验逻辑，直引下载侧唯一护栏真身（v21r2 重组后的
# 权威路径，与 domains/notes 同一入口）；审计 U1-15/U1-10 记录本文件曾零调用。
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
    check_download_url,
)
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 手动逐跳跟随时的一次性上限（与 urllib 默认 10 相比取保守值，超限即弃图）。
_MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

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
    # B 线 2026-09-16「把所有表情贴纸存下来」：除 image 外收 mface（QQ 商城
    # 表情/贴纸，NapCat 段带 url）与 sticker；这些段与普通图片同走下载、
    # MD5 去重、VLM 打标入库，理解面与发送面因此共用同一个表情库。
    accepted_types = {"image", "mface", "sticker"}
    for segment in message_segments or []:
        segment_type = getattr(segment, "type", None)
        if isinstance(segment, dict):
            segment_type = segment.get("type")
        data = getattr(segment, "data", None)
        if isinstance(segment, dict):
            data = segment.get("data", {})
        if (
            str(segment_type or "").strip().lower() not in accepted_types
            or not isinstance(data, dict)
        ):
            continue
        url = str(data.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


async def _download_once(url: str, *, max_bytes: int, proxy: str) -> tuple[bytes, str] | None:
    """取一张图的字节：SSRF 咽喉做「入口 + 每一跳落点」双查（审计 U1-15）。

    与咽喉正例的一致性：URL 由群消息段诱发（任意群成员可发），比归档侧更宽松，
    因此这里取 ``media_archive._GuardedRedirectHandler`` 的**逐跳、发请求前**复查
    形态，而非 ``notes``/``eat`` 的 ``geturl`` 事后复查——手动逐跳（不让 httpx
    自动跟随），每一跳在发出请求之前过同一个 ``check_download_url``。
    校验逻辑一份不造：咽喉调用点在本函数内唯一，入口与落点共用。

    返回形态不变（``None`` = 这张不收）：拒绝不新增异常类型、不静默吞——
    在抛出点 WARNING 留痕（URL 过既有脱敏），单张失败不拖垮整条收库。
    """
    import httpx

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(12.0, connect=8.0),
        # 逐跳复查见下方循环：绝不把跳转交给客户端自动完成。
        "follow_redirects": False,
        "headers": {"User-Agent": "Mozilla/5.0"},
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    target = url
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            for hop in range(_MAX_REDIRECT_HOPS + 1):
                check_download_url(target)
                async with client.stream("GET", target) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = str(response.headers.get("location") or "").strip()
                        if not location or hop >= _MAX_REDIRECT_HOPS:
                            return None
                        # 相对 Location 按当前跳解析，再交下一轮循环复查落点。
                        target = str(httpx.URL(target).join(location))
                        continue
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
            return None
    except RejectedUrlError as exc:
        # 审查 F-06 同构口径：拒绝信号在抛出点留痕（重定向落点才是真实攻击面），
        # 按「这张取不到」返回，不中断同批其余条目。
        logger.warning(
            "meme library SSRF guard rejected url: %s (url=%s)",
            exc,
            redact_local_secrets(target),
        )
        return None
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
    # 视觉打标使用与聊天相同的 OpenAI-compatible 直连接口。
    # 表情库识图仅在显式配置有效端点时运行；空配置保持静默。
    if not (model and base_url):
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
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
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


async def backfill_meme_tags(store: Any, config: Any, *, limit: int = 20) -> int:
    """启动补标：给描述为空的图库图补 VLM 打标（用户导入表情包场景）。

    每轮最多 limit 张防打爆；逐张读文件 → 复用 _tag_with_vlm（含 NSFW
    删除语义）。返回实际处理张数；未配置视觉端点时直接返回 0。
    """
    vision = _resolve_vision_config(config)
    if not (vision["model"] and vision["base_url"]):
        return 0
    try:
        pending = store.list_untagged(limit=limit)
    except Exception:  # noqa: BLE001 - 队列查询失败按无待标处理。
        return 0
    processed = 0
    for row in pending:
        path = store._resolve_media_path(row.get("path", ""))
        try:
            if not path.is_file():
                continue
            image_bytes = path.read_bytes()
        except OSError:
            continue
        if not image_bytes:
            continue
        before = str(row.get("md5", ""))
        await _tag_with_vlm(store, config, before, image_bytes)
        processed += 1
    return processed


async def backfill_meme_tags_loop(
    store: Any, config: Any, *, batch: int = 20, interval_seconds: float = 600.0
) -> None:
    """周期补标循环：直到图库无待标图为止（每批 batch 张，批间隔 10 分钟）。

    防打爆设计：串行逐张 + 批间长休眠；视觉端点未配置时立即退出。
    """
    vision = _resolve_vision_config(config)
    if not (vision["model"] and vision["base_url"]):
        return
    while True:
        try:
            processed = await backfill_meme_tags(store, config, limit=batch)
        except Exception:  # noqa: BLE001 - 循环体异常不外泄。
            processed = 0
        if processed < batch:
            return  # 本批不足 = 已清空（或端点失效），结束循环
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
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
    pending: list[tuple[str, str, bytes]] = []  # (md5, ext, image_bytes)
    for url in urls[:4]:
        result = await _download_once(url, max_bytes=max_bytes, proxy=proxy)
        if not result:
            continue
        image_bytes, content_type = result
        md5 = hashlib.md5(image_bytes).hexdigest()
        ext = _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
        if not ext:
            match = _URL_EXT_RE.search(url)
            ext = (match.group(1) if match else "png").lower()
        pending.append((md5, ext, image_bytes))
    if pending:

        def _persist() -> list[tuple[str, bytes]]:
            # 写盘 + SQLite 入库是同步 IO，挪到线程池避免占用事件循环。
            saved_items: list[tuple[str, bytes]] = []
            for md5, ext, image_bytes in pending:
                if store.exists(md5):
                    continue
                path = target_dir / f"{md5}.{ext}"
                try:
                    path.write_bytes(image_bytes)
                except OSError:
                    continue
                store.add(md5=md5, path=str(path), ext=ext, group_id=group_id)
                saved_items.append((md5, image_bytes))
            return saved_items

        saved_items = await asyncio.to_thread(_persist)
        saved = len(saved_items)
        if getattr(config, "bot_meme_library_vlm_enabled", False):
            for md5, image_bytes in saved_items:
                _spawn_vlm_task(store, config, md5, image_bytes)

    def _cleanup() -> None:
        store.cleanup(
            max_files=int(getattr(config, "bot_meme_library_max_files", 20000) or 0),
            max_age_days=int(getattr(config, "bot_meme_library_max_age_days", 30) or 0),
        )

    try:
        await asyncio.to_thread(_cleanup)
    except Exception:  # noqa: BLE001, S110 - 清理失败不影响入库结果。
        pass
    return {"handled": True, "reason": "saved", "saved": saved}
