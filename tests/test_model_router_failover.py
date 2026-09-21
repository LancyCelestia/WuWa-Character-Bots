from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Self
from urllib.error import HTTPError

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
)

# ==================== A50 加固：channel_health 单例每测复位 ====================


@pytest.fixture(autouse=True)
def _reset_channel_health_singleton(tmp_path, monkeypatch):
    """每个测试前复位 channel_health 进程级单例并隔离到 tmp_path 独立库。

    背景（A50 排查实锤）：``channel_health._GLOBAL_STORE`` 是进程级单例 +
    SQLite 持久化 + latency_first 默认开；全量套件下一旦 .env 装载路径把
    ``BOT_CHANNEL_HEALTH_ENABLED`` 泄漏进 os.environ（生产 .env 确有该键），
    健康层会在这些纯路由测试中激活，读到单例里此前测试残留的 EMA 行 /
    不可用标记 → 候选序被延迟降序或健康过滤改写（'first' 系假红的根因）。
    channel_health 没有公开复位函数，故按仓库既有手法（test_channel_health_v2 /
    test_auditfix_llm_route 直接替换模块全局）做三重隔离：

    1) 全新空 store 替换 ``_GLOBAL_STORE``（monkeypatch 自动还原，不外溢）；
    2) ``resolve_default_db_path`` 钉到 tmp_path——单例即使被置 None 再取，
       也落临时库，绝不触生产 channel_health.sqlite3；
    3) 两个开关环境变量显式钉 0，锁死「本文件 = 健康层关闭」的语义前提；
       个别用例如需健康层，在用例内自行 monkeypatch 覆盖即可。
    """
    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health as channel_health_module

    db_path = str(tmp_path / "channel_health.sqlite3")
    monkeypatch.setattr(
        channel_health_module,
        "_GLOBAL_STORE",
        channel_health_module.ChannelHealthStore(db_path),
    )
    monkeypatch.setattr(
        channel_health_module, "resolve_default_db_path", lambda: db_path
    )
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "0")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")


class FakeProvider:
    def __init__(self, model_id: str, failures: dict[str, str], calls: list[str]) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


def _router(specs: dict[str, ModelSpec], failures: dict[str, str], calls: list[str]) -> ModelRouter:
    return ModelRouter(
        specs,
        provider_factory=lambda spec: FakeProvider(spec.model_id, failures, calls),
    )


def _spec(model_id: str, priority: int, *, api_key: str = "key") -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key=api_key,
        tags=("fast",),
        priority=priority,
    )


def test_transient_provider_error_fails_over_to_next_candidate() -> None:
    calls: list[str] = []
    router = _router(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        {"first": "timeout"},
        calls,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == ["first:timeout", "second:success"]


# B-2（管线检视 #2）：未分类的 "http"、auth、schema 均为渠道相关错误，
# 纳入可故障转移（auth：各渠道 key 独立，一个 key 失效 ≠ 全部失效；
# schema：中转站返回挑战页/非 JSON 垃圾是渠道级故障）。只有本地配置洞
# （config_missing）仍判死——换候选同样无救，重试全渠道纯属浪费。
@pytest.mark.parametrize("error_kind", ["config_missing"])
def test_configuration_errors_stop_failover(error_kind: str) -> None:
    calls: list[str] = []
    router = _router(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        {"first": error_kind},
        calls,
    )

    with pytest.raises(LLMProviderError) as raised:
        router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert raised.value.error_kind == error_kind
    assert calls == ["first"]
    assert router.last_attempts == [f"first:{error_kind}"]


@pytest.mark.parametrize("error_kind", ["auth", "schema"])
def test_auth_and_schema_errors_are_channel_specific_and_fail_over(error_kind: str) -> None:
    calls: list[str] = []
    router = _router(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        {"first": error_kind},
        calls,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == [f"first:{error_kind}", "second:success"]


def test_provider_factory_error_is_recorded_and_does_not_break_next_candidate() -> None:
    calls: list[str] = []

    def factory(spec: ModelSpec) -> FakeProvider:
        if spec.model_id == "first":
            raise RuntimeError("factory failed")
        return FakeProvider(spec.model_id, {}, calls)

    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=factory,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["second"]
    assert router.last_attempts == ["first:provider_error", "second:success"]


def test_unconfigured_candidate_never_constructs_provider_and_continues() -> None:
    calls: list[str] = []
    router = _router(
        {
            "missing": _spec("missing", 1, api_key=""),
            "ready": _spec("ready", 2),
        },
        {},
        calls,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:ready"
    assert calls == ["ready"]
    assert router.last_attempts == ["missing:config_missing", "ready:success"]


def test_fast_candidate_limit_zero_means_unlimited() -> None:
    calls: list[str] = []
    router = _router(
        {
            "first": _spec("first", 1),
            "second": _spec("second", 2),
            "third": _spec("third", 3),
        },
        {"first": "timeout", "second": "timeout"},
        calls,
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        fast_mode=True,
        fast_max_candidates=0,
    )

    assert reply.text == "ok:third"
    assert calls == ["first", "second", "third"]


class TimeoutCaptureProvider(FakeProvider):
    def __init__(self, model_id: str, failures: dict[str, str], calls: list[str], timeouts: list[float]) -> None:
        super().__init__(model_id, failures, calls)
        self.timeouts = timeouts

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        timeout = kwargs.get("timeout_seconds")
        if isinstance(timeout, (int, float)):
            self.timeouts.append(float(timeout))
        return super().generate(messages, **kwargs)


def test_router_passes_remaining_deadline_to_each_provider_attempt() -> None:
    calls: list[str] = []
    timeouts: list[float] = []
    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: TimeoutCaptureProvider(
            spec.model_id, {"first": "timeout"}, calls, timeouts
        ),
        max_failover_seconds=0.05,
        # v21r2 R1 链预算止损缺省 3s：本用例预算 0.05s 专测「剩余 deadline
        # 逐跳透传」语义，须显式关闭止损（否则第二跳会在发起前被止损拦下）。
        credential_config=SimpleNamespace(bot_chat_failover_min_hop_seconds=0.0),
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert len(timeouts) == 2
    assert 0 < timeouts[0] <= 0.05
    assert 0 < timeouts[1] <= timeouts[0]


def _http_error(status: int, body: str) -> HTTPError:
    return HTTPError(
        url="https://example.test/v1/chat/completions",
        code=status,
        msg="provider error",
        hdrs=None,
        fp=io.BytesIO(body.encode("utf-8")),
    )


def test_provider_sends_reasoning_effort_and_qwen_thinking_switch() -> None:
    captured: list[dict[str, object]] = []

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

    def urlopen(request: object, **kwargs: object) -> Response:
        captured.append(json.loads(request.data.decode("utf-8")))  # type: ignore[attr-defined]
        return Response()

    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="reasoning-model",
        base_url="https://example.test/v1",
        urlopen=urlopen,
    )
    provider.generate([{"role": "user", "content": "hi"}], reasoning_effort="high")
    qwen = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="qwen-plus",
        base_url="https://dashscope.example/v1",
        urlopen=urlopen,
    )
    qwen.generate([{"role": "user", "content": "hi"}], reasoning_effort="off")

    assert captured[0]["reasoning_effort"] == "high"
    assert captured[1]["enable_thinking"] is False
    assert "reasoning_effort" not in captured[1]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, '{"error":{"message":"model not found"}}', "model_not_found"),
        (404, '{"error":{"message":"model is not supported"}}', "unsupported_model"),
        (422, '{"error":{"message":"unsupported parameter: temperature"}}', "unsupported_parameter"),
        (400, '{"error":{"message":"invalid request"}}', "invalid_request"),
    ],
)
def test_provider_classifies_model_and_request_http_errors(
    status: int,
    body: str,
    expected: str,
) -> None:
    def urlopen(*args: object, **kwargs: object) -> object:
        raise _http_error(status, body)

    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://example.test/v1",
        urlopen=urlopen,
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hello"}])

    assert raised.value.error_kind == expected
    assert "test-key" not in str(raised.value)


@pytest.mark.parametrize("error_kind", ["model_not_found", "unsupported_model"])
def test_model_capability_errors_fail_over_to_next_candidate(error_kind: str) -> None:
    calls: list[str] = []
    router = _router(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        {"first": error_kind},
        calls,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == [f"first:{error_kind}", "second:success"]


def test_unsupported_reasoning_parameter_retries_same_provider_without_it() -> None:
    calls: list[dict[str, object]] = []

    class Provider:
        def generate(self, messages: object, **kwargs: object) -> LLMReply:
            calls.append(dict(kwargs))
            if "reasoning_effort" in kwargs:
                raise LLMProviderError(
                    "unsupported reasoning",
                    error_kind="unsupported_parameter",
                )
            return LLMReply(text="ok", provider="fake", model="first")

    router = ModelRouter(
        {"first": _spec("first", 1)},
        provider_factory=lambda _spec: Provider(),
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        reasoning_effort="high",
    )

    assert reply.text == "ok"
    assert len(calls) == 2
    assert calls[0]["reasoning_effort"] == "high"
    assert "reasoning_effort" not in calls[1]
    assert router.last_attempts == ["first:success_without_reasoning"]


# B-2（管线检视 #2）：请求形状错误是渠道相关的——unsupported_parameter 先
# 走剥参重试，重试无效或 invalid_request 时应转移下一候选，而不是判死整条
# 多候选路由（一次中转站措辞变化曾是单点故障）。
@pytest.mark.parametrize("error_kind", ["unsupported_parameter", "invalid_request"])
def test_request_shape_errors_fail_over_to_next_candidate(error_kind: str) -> None:
    calls: list[str] = []
    router = _router(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        {"first": error_kind},
        calls,
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == [f"first:{error_kind}", "second:success"]

