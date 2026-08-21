"""模型路由：多模型注册、规则自动选型、手动覆盖、失败自动切换。

支持的模型由 ``BOT_MODEL_REGISTRY`` 注册（OpenAI 兼容接口），例如
deepseek-v4-flash/pro、gpt-5.6-terra/sol、gemini-3.7-flash。每个条目：

    {
      "id": "flash",
      "model": "deepseek-v4-flash",
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "env:BOT_API_KEY_DEEPSEEK",   # 或直接填密钥
      "tags": ["fast"],                        # fast=快/便宜, strong=强
      "priority": 1                            # 越小越先选
    }

``api_key`` 也支持列表：``["env:BOT_API_KEY_DEEPSEEK","env:BOT_API_KEY_DEEPSEEK_2"]``，
同模型按列表顺序做密钥故障转移（第一个密钥 401/失败自动换下一个）。

自动选型（纯规则，不烧钱）：

1. 管理员手动指定（``/bot runtime model set <id>``）→ 只用该模型，
   失败时按优先级转移到其他模型。
2. 复杂任务（长文本/教程/排查/分析/写作类关键词）→ strong 档。
3. 默认 → fast 档（快、便宜）。
4. 同档模型失败 → 按 priority 依次转移；fast 全败 → 升级 strong 档。

密钥建议用 ``env:变量名`` 引用环境变量，避免写进配置。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from plugins.bot_unified_runtime.llm import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
)

# 复杂任务信号：命中即路由到 strong 档。
_COMPLEX_KEYWORDS = (
    "教程",
    "一步步",
    "逐步",
    "详细",
    "排查",
    "分析",
    "解释一下",
    "帮我写",
    "写一篇",
    "翻译",
    "总结",
    "比较",
    "推导",
    "证明",
    "代码",
    "配置",
    "部署",
)
_COMPLEX_MIN_CHARS = 300

DEFAULT_REGISTRY: dict[str, dict[str, Any]] = {
    "flash": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": ["env:BOT_API_KEY_DEEPSEEK", "env:BOT_API_KEY_DEEPSEEK_2"],
        "tags": ["fast"],
        "priority": 1,
    },
    "pro": {
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": ["env:BOT_API_KEY_DEEPSEEK", "env:BOT_API_KEY_DEEPSEEK_2"],
        "tags": ["strong"],
        "priority": 2,
    },
    "terra": {
        "model": "gpt-5.6-terra",
        "base_url": "https://api.openai.com/v1",
        "api_key": "env:BOT_API_KEY_OPENAI",
        "tags": ["strong"],
        "priority": 3,
    },
    "sol": {
        "model": "gpt-5.6-sol",
        "base_url": "https://api.openai.com/v1",
        "api_key": "env:BOT_API_KEY_OPENAI",
        "tags": ["strong"],
        "priority": 4,
    },
    "gemini-flash": {
        "model": "gemini-3.7-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "env:BOT_API_KEY_GEMINI",
        "tags": ["fast"],
        "priority": 5,
    },
}

_AUTO = "auto"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model: str
    base_url: str
    api_key: str
    api_keys: tuple[str, ...] = ()
    tags: tuple[str, ...] = ("fast",)
    priority: int = 100

    def all_api_keys(self) -> tuple[str, ...]:
        """全部可用密钥（按顺序故障转移）；未配置 api_keys 时退回单密钥。"""
        if self.api_keys:
            return self.api_keys
        return (self.api_key,) if self.api_key else ()


def _resolve_api_key(value: str) -> str:
    from os import environ

    if value.startswith("env:"):
        return environ.get(value.removeprefix("env:"), "")
    return value


def _resolve_api_keys(value: object) -> tuple[str, ...]:
    """解析单密钥或密钥列表（均可写 env:变量名 或明文），去掉空值。"""
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        items = [str(value)]
    return tuple(
        key for key in (_resolve_api_key(item).strip() for item in items) if key
    )


def build_model_registry(config: object) -> dict[str, ModelSpec]:
    raw = getattr(config, "bot_model_registry", None) or {}
    if not isinstance(raw, dict) or not raw:
        # 未配置注册表时，用主模型配置生成单模型注册表，行为等价旧版。
        return {}
    specs: dict[str, ModelSpec] = {}
    for model_id, item in raw.items():
        if not isinstance(item, dict):
            continue
        model = str(item.get("model", "")).strip()
        if not model:
            continue
        tags = item.get("tags")
        if isinstance(tags, list):
            tag_tuple = tuple(str(tag) for tag in tags)
        elif isinstance(tags, str):
            tag_tuple = tuple(tag.strip() for tag in tags.split(",") if tag.strip())
        else:
            tag_tuple = ("fast",)
        priority = item.get("priority", 100)
        if not isinstance(priority, int):
            try:
                priority = int(priority)
            except (TypeError, ValueError):
                priority = 100
        resolved_keys = _resolve_api_keys(item.get("api_key", ""))
        specs[str(model_id)] = ModelSpec(
            model_id=str(model_id),
            model=model,
            base_url=str(item.get("base_url", "")).strip(),
            api_key=resolved_keys[0] if resolved_keys else "",
            api_keys=resolved_keys,
            tags=tag_tuple,
            priority=priority,
        )
    return specs


def _main_fallback_spec(config: object) -> ModelSpec | None:
    """主 BOT_CHAT_* 配置的兜底模型（注册表为空时即旧版单模型行为）。"""
    model = str(getattr(config, "bot_chat_model", "")).strip()
    if not model:
        return None
    return ModelSpec(
        model_id="default",
        model=model,
        base_url=str(getattr(config, "bot_chat_base_url", "")).strip(),
        api_key=str(getattr(config, "bot_chat_api_key", "")),
        tags=("strong",),
        priority=1,
    )


def _preset_specs(config: object, *, priority_offset: int = 1000) -> dict[str, ModelSpec]:
    """把 BOT_MODEL_PRESETS 的预设名转成可路由的模型条目。

    预设只应被手动指定选中，因此打 ``manual`` 标签且优先级垫底，
    不会在自动选型中抢走主模型/注册表模型的位置。
    """
    presets = getattr(config, "bot_model_presets", {}) or {}
    if not isinstance(presets, dict):
        return {}
    main = _main_fallback_spec(config)
    base_url = main.base_url if main is not None else ""
    api_key = main.api_key if main is not None else ""
    specs: dict[str, ModelSpec] = {}
    for index, (name, model) in enumerate(presets.items()):
        model = str(model).strip()
        if not model:
            continue
        specs[str(name)] = ModelSpec(
            model_id=str(name),
            model=model,
            base_url=base_url,
            api_key=api_key,
            tags=("manual",),
            priority=priority_offset + index,
        )
    return specs


class ModelRouter:
    def __init__(
        self,
        specs: dict[str, ModelSpec],
        *,
        provider_factory: Callable[[ModelSpec], Any] | None = None,
        fallback_spec: ModelSpec | None = None,
    ) -> None:
        self.specs = specs
        # 兜底模板：未知覆盖 id 时当作完整模型名，走主配置的接口/密钥
        # （兼容旧版「直接给模型名」的用法）。
        self._fallback_spec = fallback_spec
        self._providers: dict[str, Any] = {}
        self._factory = provider_factory or self._default_provider

    def _default_provider(self, spec: ModelSpec) -> Any:
        return OpenAICompatibleLLMProvider(
            api_key=spec.api_key,
            model=spec.model,
            base_url=spec.base_url,
        )

    def _spec_for(self, model_id: str) -> ModelSpec | None:
        spec = self.specs.get(model_id)
        if spec is not None:
            return spec
        if self._fallback_spec is None:
            return None
        if model_id == self._fallback_spec.model_id:
            return self._fallback_spec
        return ModelSpec(
            model_id=model_id,
            model=model_id,
            base_url=self._fallback_spec.base_url,
            api_key=self._fallback_spec.api_key,
            tags=self._fallback_spec.tags,
            priority=100,
        )

    def provider_for(self, model_id: str, api_key: str | None = None) -> Any:
        spec = self._spec_for(model_id)
        if spec is None:
            raise KeyError(f"unknown model id: {model_id}")
        cache_key: object = model_id
        provider_spec = spec
        if api_key is not None and api_key != spec.api_key:
            cache_key = (model_id, api_key)
            provider_spec = replace(spec, api_key=api_key)
        if cache_key not in self._providers:
            self._providers[cache_key] = self._factory(provider_spec)
        return self._providers[cache_key]

    def model_ids(self) -> list[str]:
        return list(self.specs.keys())

    def route_ids(self, *, message_text: str, override: str) -> list[str]:
        """返回按优先级排列的候选模型 id 列表。"""
        override = (override or "").strip()
        if override and override != _AUTO:
            if self._spec_for(override) is None:
                # 管理员给了无法解析的 id：退回自动路由。
                return self._auto_route_ids(message_text)
            return [override, *self._auto_route_ids(message_text, exclude=override)]
        return self._auto_route_ids(message_text)

    def _auto_route_ids(self, message_text: str, exclude: str = "") -> list[str]:
        complex_task = len(message_text) >= _COMPLEX_MIN_CHARS or any(
            keyword in message_text for keyword in _COMPLEX_KEYWORDS
        )
        wanted = "strong" if complex_task else "fast"
        ordered = sorted(
            self.specs.values(),
            key=lambda spec: (spec.priority, spec.model_id),
        )
        primary = [spec.model_id for spec in ordered if wanted in spec.tags]
        fallback = [
            spec.model_id
            for spec in ordered
            if wanted not in spec.tags or spec.model_id in primary
        ]
        ids = list(dict.fromkeys([*primary, *fallback]))
        if exclude:
            ids = [model_id for model_id in ids if model_id != exclude]
        return ids

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        message_text: str = "",
        override: str = "",
        **kwargs: object,
    ) -> LLMReply:
        """按路由顺序生成；每个候选的每个密钥失败后自动切换下一个。

        尝试顺序：候选模型 × 该模型的密钥列表（api_keys 顺序），
        全部失败抛出最后一个错误。"""
        candidate_ids = self.route_ids(
            message_text=message_text or messages[-1].get("content", ""),
            override=override,
        )
        last_error: LLMProviderError | None = None
        for model_id in candidate_ids:
            spec = self._spec_for(model_id)
            if spec is None:
                continue
            for api_key in spec.all_api_keys():
                provider = self.provider_for(model_id, api_key)
                try:
                    return provider.generate(messages, **kwargs)
                except LLMProviderError as exc:
                    last_error = exc
                    continue
                except Exception as exc:
                    last_error = LLMProviderError(
                        f"model {model_id} failed: {type(exc).__name__}",
                        error_kind="provider_error",
                    )
                    continue
        if last_error is not None:
            raise last_error
        raise LLMProviderError(
            "no model available",
            error_kind="provider_not_configured",
        )


def build_model_router(
    config: object,
    *,
    provider_factory: Callable[[ModelSpec], Any] | None = None,
) -> ModelRouter:
    """组装路由器：注册表优先，预设名与主配置模型一并可解析。

    - 注册表（BOT_MODEL_REGISTRY）条目按各自 tags/priority 参与自动选型；
    - 预设（BOT_MODEL_PRESETS）只接受手动指定（``/bot runtime model set <预设名>``），
      不会在自动选型中抢占注册表/主模型；
    - 主配置模型（BOT_CHAT_MODEL）在注册表为空时充当默认模型（旧版行为），
      注册表存在时退居兜底；
    - 手动覆盖给出注册表/预设之外的名称时，按完整模型名用主配置接口调用。
    """
    registry = build_model_registry(config)
    main_spec = _main_fallback_spec(config)
    has_registry = bool(registry)

    specs: dict[str, ModelSpec] = dict(registry)
    for name, spec in _preset_specs(config).items():
        specs.setdefault(name, spec)
    if main_spec is not None:
        if has_registry:
            # 注册表在场时主配置模型退居兜底，不参与自动选型抢位。
            main_spec = ModelSpec(
                model_id=main_spec.model_id,
                model=main_spec.model,
                base_url=main_spec.base_url,
                api_key=main_spec.api_key,
                tags=("manual",),
                priority=2000,
            )
        specs.setdefault(main_spec.model_id, main_spec)
    return ModelRouter(
        specs,
        provider_factory=provider_factory,
        fallback_spec=main_spec,
    )
