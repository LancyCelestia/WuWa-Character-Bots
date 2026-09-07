"""图片/表情包识别（VLM）：角色识别 + 文字转写 + 画面简述。

聊天链路在消息携带图片（image/mface 段，QQ 与 Telegram 通用）时调用本模块，
把图片内容转成紧凑的文字描述注入当前消息上下文，让人格模型"看懂"图片再回应。

识别模型来自 ``BOT_VISION_MODEL_REGISTRY``（OpenAI 兼容多模态接口），支持两种
写法：``id -> 条目``（单模型）与 ``id -> [条目, ...]``（一个供应商挂多个模型，
按条目内 priority 轮询）。运行时注册表（``/bot model vision add ...``）合并于
其上且即时生效；调用失败按优先级转移到下一个候选（最多 3 个）。未启用或未
配置时整条链路零开销跳过，识别失败不阻断聊天。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from plugins.bot_unified_runtime.llm import (
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)

logger = logging.getLogger(__name__)

_VISION_SYSTEM_PROMPT = (
    "你是图片识别器，为聊天机器人解读用户发来的图片、表情包或照片。"
    "严格按以下三行格式输出，不要输出任何其他内容：\n"
    "角色：<角色名（出处作品名）>；出自真人影视或现实照片则写“非动漫游戏角色”。"
    "无法确定时写“不确定”，并在同行给出最可能的候选与判断依据\n"
    "文字：<逐字转写图中出现的全部文字，保持原文不翻译不改写；没有文字写“无”>\n"
    "画面：<一句话描述画面内容与情绪>"
)
_IMAGE_SEGMENT_TYPES = {"image", "mface"}
_DEFAULT_MAX_IMAGES = 2
_DEFAULT_MAX_CHARS = 500
_MAX_VISION_FAILOVER_ATTEMPTS = 3


def extract_image_urls(raw_segments: list[dict[str, Any]] | None) -> list[str]:
    """从消息原始段提取图片 URL；image 与 mface（QQ 表情包）都算。"""
    urls: list[str] = []
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _IMAGE_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        url = str(data.get("url") or data.get("file") or "").strip()
        if url.startswith("http") and url not in urls:
            urls.append(url)
    return urls


def _flatten_vision_entries(
    registry: Any,
    *,
    resolve_key: bool = False,
    config: object = None,
) -> dict[str, dict[str, Any]]:
    """把注册表统一展平成 id -> 条目；id 支持单条目或条目列表。

    列表形态按 ``id#序号`` 展开；resolve_key 时把 env: 引用解析成真实密钥。
    """
    from plugins.bot_unified_runtime.llm.model_router import _resolve_api_key

    flattened: dict[str, dict[str, Any]] = {}
    if not isinstance(registry, dict):
        return flattened
    for group_id, value in registry.items():
        group = str(group_id)
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            model = str(item.get("model", "")).strip()
            base_url = str(item.get("base_url", "")).strip()
            if not model or not base_url:
                continue
            entry_id = f"{group}#{index}" if isinstance(value, list) else group
            entry = dict(item)
            if resolve_key:
                entry["api_key"] = _resolve_api_key(
                    str(entry.get("api_key", "")), config
                )
            flattened[entry_id] = entry
    return flattened


class DynamicVisionProvider:
    """视觉模型动态提供器：env 注册表 + 运行时注册表合并，按优先级故障转移。"""

    def __init__(
        self,
        config: object,
        *,
        dynamic_registry: Any = None,
        settings_store: Any = None,
    ) -> None:
        self._config = config
        self._dynamic_registry = dynamic_registry
        self._settings_store = settings_store
        self._providers: dict[tuple[str, str, str], Any] = {}
        self.last_attempts: list[str] = []

    def is_enabled(self) -> bool:
        if self._settings_store is not None:
            try:
                return bool(
                    self._settings_store.get_or(
                        "BOT_VISION_ENABLED",
                        bool(getattr(self._config, "bot_vision_enabled", False)),
                    )
                )
            except (KeyError, OSError, TypeError, ValueError):  # 开关读取失败回退 .env 值。
                logger.debug("vision enabled flag read failed; falling back to env")
        return bool(getattr(self._config, "bot_vision_enabled", False))

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        merged = _flatten_vision_entries(
            getattr(self._config, "bot_vision_model_registry", None),
            resolve_key=True,
            config=self._config,
        )
        if self._dynamic_registry is not None:
            try:
                dynamic = self._dynamic_registry() or {}
            except Exception:  # noqa: BLE001 - 运行时注册表读取失败沿用 env。
                dynamic = {}
            merged.update(
                _flatten_vision_entries(dynamic, resolve_key=True, config=self._config)
            )
        return merged

    def _provider_for(self, entry_id: str, entry: dict[str, Any]) -> Any | None:
        api_key = str(entry.get("api_key", "")).strip()
        model = str(entry.get("model", "")).strip()
        base_url = str(entry.get("base_url", "")).strip()
        if not api_key or not model or not base_url:
            return None
        fingerprint = (model, base_url, api_key)
        if fingerprint not in self._providers:
            self._providers[fingerprint] = OpenAICompatibleLLMProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
                proxy=str(getattr(self._config, "bot_download_proxy", "") or ""),
                timeout_seconds=float(
                    getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
                ),
            )
        return self._providers[fingerprint]

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> Any:
        self.last_attempts = []
        candidates = sorted(
            self._merged_entries().items(),
            key=lambda kv: (
                kv[1].get("priority", 100)
                if isinstance(kv[1].get("priority", 100), int)
                else 100,
                kv[0],
            ),
        )
        started = time.monotonic()
        deadline = float(
            getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
        ) * 2
        last_error: LLMProviderError | None = None
        for entry_id, entry in candidates[:_MAX_VISION_FAILOVER_ATTEMPTS]:
            if last_error is not None and (time.monotonic() - started) > deadline:
                self.last_attempts.append("vision:deadline")
                break
            provider = self._provider_for(entry_id, entry)
            if provider is None:
                last_error = LLMProviderError(
                    f"vision model {entry_id} is missing key/model/base_url",
                    error_kind="config_missing",
                )
                self.last_attempts.append(f"{entry_id}:config_missing")
                continue
            try:
                reply = provider.generate(messages, **kwargs)
            except LLMProviderError as exc:
                last_error = exc
                self.last_attempts.append(f"{entry_id}:{exc.error_kind}")
                continue
            except Exception as exc:  # noqa: BLE001 - 未分类异常统一为可转移错误。
                last_error = LLMProviderError(
                    f"vision model {entry_id} failed: {type(exc).__name__}",
                    error_kind="provider_error",
                )
                self.last_attempts.append(f"{entry_id}:provider_error")
                continue
            self.last_attempts.append(f"{entry_id}:success")
            return reply
        if last_error is not None:
            raise last_error
        raise LLMProviderError(
            "no vision model available",
            error_kind="provider_not_configured",
        )


def build_vision_provider(
    config: object,
    *,
    dynamic_registry: Any = None,
    settings_store: Any = None,
) -> DynamicVisionProvider | None:
    """组装动态视觉 provider；注册表完全为空时返回 None（零开销跳过）。

    开关（BOT_VISION_ENABLED）在每次调用时读取，支持运行时热切换。
    """
    has_env = bool(_flatten_vision_entries(
        getattr(config, "bot_vision_model_registry", None)
    ))
    has_dynamic = False
    if dynamic_registry is not None:
        try:
            has_dynamic = bool(_flatten_vision_entries(dynamic_registry() or {}))
        except Exception:  # noqa: BLE001 - 注册表读取失败按空处理。
            has_dynamic = False
    if not has_env and not has_dynamic:
        return None
    return DynamicVisionProvider(
        config,
        dynamic_registry=dynamic_registry,
        settings_store=settings_store,
    )


def _clip(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}…"


def describe_images(
    provider: Any,
    *,
    image_urls: list[str],
    query_text: str = "",
    max_images: int = _DEFAULT_MAX_IMAGES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """调用视觉模型输出紧凑识别结果；任何失败返回空串，绝不阻断主回复。"""
    if provider is None or not image_urls:
        return ""
    limit = max(1, int(max_images))
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "用户附带了图片。用户随图消息："
                f"{_clip(query_text, 200) or '（无文字）'}"
            ),
        }
    ]
    for url in image_urls[:limit]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        reply = provider.generate(messages, temperature=0.1, max_tokens=400)
    except LLMProviderError as exc:
        logger.warning(
            "vision describe failed kind=%s attempts=%s",
            exc.error_kind,
            getattr(provider, "last_attempts", []),
        )
        return ""
    except Exception:
        logger.exception("vision describe failed")
        return ""
    text = str(getattr(reply, "text", "") or "").strip()
    if not text:
        return ""
    return _clip(text, max(80, int(max_chars)))


def describe_subscription_item(
    provider: Any,
    payload: dict[str, Any],
    *,
    max_images: int = 1,
    max_chars: int = 200,
) -> str:
    """订阅推送的 vision 增强：无文本条目补一行图片描述；任何失败返回空串。

    调用方负责按 BOT_VISION_ENABLED 等开关决定是否传入 provider。
    """
    if provider is None or not isinstance(payload, dict):
        return ""
    urls: list[str] = []
    for media in payload.get("media") or []:
        if isinstance(media, dict):
            url = str(media.get("preview_image_url") or media.get("url") or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        for key in ("cover", "image", "thumbnail"):
            url = str(payload.get(key) or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        return ""
    return describe_images(
        provider,
        image_urls=urls,
        query_text=str(payload.get("title") or ""),
        max_images=max_images,
        max_chars=max_chars,
    )
