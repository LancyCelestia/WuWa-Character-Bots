from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib import error, request
from urllib.parse import urlsplit

from pydantic import Field

from plugins.wuwa_unified_runtime.contracts.runtime import StrictBaseModel


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, error_kind: str = "provider_error") -> None:
        super().__init__(message)
        self.error_kind = error_kind


_LLM_ERROR_PUBLIC_MESSAGES = {
    "config_missing": "LLM 诊断未执行：openai_compatible provider 缺少 API key。",
    "timeout": "LLM 诊断失败：模型服务请求超时，请检查 base_url、网络代理和超时配置。",
    "auth": "LLM 诊断失败：模型服务鉴权失败，请检查 API key、模型权限和账号状态。",
    "rate_limited": "LLM 诊断失败：模型服务触发限流，请稍后重试或检查服务配额。",
    "server": "LLM 诊断失败：模型服务端返回错误，请稍后重试或检查服务状态。",
    "http": "LLM 诊断失败：模型服务返回 HTTP 错误，请检查 base_url、model 和请求格式。",
    "network": "LLM 诊断失败：无法连接模型服务，请检查网络、代理和 base_url。",
    "schema": "LLM 诊断失败：模型响应格式不符合 OpenAI-compatible chat/completions 规范。",
    "empty_response": "LLM 诊断失败：模型返回了空回复。",
    "provider_error": "LLM 诊断失败：模型服务返回错误。请检查 base_url、model、API key 和网络代理。",
}


def public_llm_error_message(error_kind: str) -> str:
    return _LLM_ERROR_PUBLIC_MESSAGES.get(
        error_kind,
        _LLM_ERROR_PUBLIC_MESSAGES["provider_error"],
    )


class LLMReply(StrictBaseModel):
    text: str
    provider: str
    model: str
    confidence: float = 1.0
    raw_usage: dict[str, Any] = Field(default_factory=dict)


_SAFE_LLM_FINISH_REASONS = {
    "stop",
    "length",
    "content_filter",
    "tool_calls",
    "function_call",
}


def safe_llm_finish_reason(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if normalized in _SAFE_LLM_FINISH_REASONS:
        return normalized
    return ""


class LLMProvider(Protocol):
    def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> LLMReply:
        raise NotImplementedError


class StaticLLMProvider:
    def __init__(
        self,
        text: str = (
            "（轻轻点头）我这边还没有接上外面的模型，"
            "现在只能先陪着你说几句。等管理员把真实模型配置好，"
            "我就能按你的问题好好回答了。"
        ),
        model: str = "static",
    ) -> None:
        self.text = text
        self.model = model

    def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> LLMReply:
        return LLMReply(text=self.text, provider="static", model=self.model, confidence=0.0)


def normalize_openai_chat_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _base_url_error(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid"
    if parsed.username or parsed.password:
        return "unsafe"
    return ""


def _classify_http_error(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code <= 599:
        return "server"
    return "http"


def _is_timeout_reason(reason: object) -> bool:
    if isinstance(reason, TimeoutError):
        return True
    return "timed out" in str(reason).lower() or "timeout" in str(reason).lower()


def _extract_message_content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                raise TypeError("message content part is not an object")
            part_type = part.get("type")
            part_text = part.get("text")
            if part_type == "text" and isinstance(part_text, str):
                stripped = part_text.strip()
                if stripped:
                    text_parts.append(stripped)
        return "\n".join(text_parts).strip()
    raise TypeError("message content is not text")


def _extract_usage(usage: object, finish_reason: object = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(usage, dict):
        result = dict(usage)
    result.pop("finish_reason", None)
    safe_finish_reason = safe_llm_finish_reason(finish_reason)
    if safe_finish_reason:
        result["finish_reason"] = safe_finish_reason
    return result


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.strip().rstrip("/")
        self.endpoint_url = normalize_openai_chat_endpoint(base_url)
        self.timeout_seconds = timeout_seconds
        self._urlopen = urlopen or request.urlopen

    def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> LLMReply:
        if not self.api_key:
            raise LLMProviderError("LLM api key is empty", error_kind="config_missing")
        if _base_url_error(self.base_url):
            raise LLMProviderError(
                "LLM base_url is invalid or unsafe",
                error_kind="config_missing",
            )

        payload = {
            "model": kwargs.get("model") or self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 512),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            self.endpoint_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with self._urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise LLMProviderError(
                f"LLM HTTP request failed with status {exc.code}",
                error_kind=_classify_http_error(exc.code),
            ) from exc
        except TimeoutError as exc:
            raise LLMProviderError("LLM request timed out", error_kind="timeout") from exc
        except error.URLError as exc:
            error_kind = "timeout" if _is_timeout_reason(exc.reason) else "network"
            raise LLMProviderError(
                "LLM network error",
                error_kind=error_kind,
            ) from exc
        except Exception as exc:
            raise LLMProviderError(
                "LLM provider transport error",
                error_kind="provider_error",
            ) from exc

        try:
            data = json.loads(response_body)
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                "LLM response schema is invalid",
                error_kind="schema",
            ) from exc
        if not isinstance(message, dict):
            raise LLMProviderError(
                "LLM response schema is invalid",
                error_kind="schema",
            )
        if "content" not in message or message["content"] is None:
            raise LLMProviderError(
                "LLM returned empty text",
                error_kind="empty_response",
            )
        try:
            text = _extract_message_content_text(message["content"])
        except TypeError as exc:
            raise LLMProviderError(
                "LLM response schema is invalid",
                error_kind="schema",
            ) from exc

        if not text:
            raise LLMProviderError(
                "LLM returned empty text",
                error_kind="empty_response",
            )

        return LLMReply(
            text=text,
            provider="openai_compatible",
            model=str(payload["model"]),
            confidence=1.0,
            raw_usage=_extract_usage(data.get("usage"), choice.get("finish_reason")),
        )
