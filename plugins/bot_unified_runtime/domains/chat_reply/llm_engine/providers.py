from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Protocol
from urllib import error, request
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from plugins.bot_unified_runtime.domains.core.contracts.runtime import StrictBaseModel


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_kind: str = "provider_error",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        # W1-② 证据链：底层异常原文的缩略（httpx ConnectTimeout/ConnectError
        # 等的判别细节）。message 面向分类保持稳定，原文走 detail 随逐跳
        # 日志落盘——09-29 故障排查时「timeout 是连不上还是读不到」无法
        # 区分，就是因为这一层被抽掉了。单行化 + 200 上限在**本咽喉统一
        # 执法**（构造点再多也不许爆行/超长）。
        self.detail = " / ".join(
            part.strip() for part in str(detail or "").splitlines() if part.strip()
        )[:200]
        # 本次故障转移的尝试轨迹（ModelRouter.generate 抛出前填充）；
        # 与具体请求绑定，审计消费点据此取数，避免跨请求共享状态串号。
        self.attempts: list[str] = []


# 响应体 `id`（→ 账本 remote_request_id → 归因匹配键）的长度上限。真实
# OpenAI 兼容 id 约 28–40 字符，128 是宽到不会截断任何合法 id 的天花板，
# 只挡敌意/脏回包的行膨胀（F-7）。
_REMOTE_REQUEST_ID_MAX_LEN = 128


# 只有本地配置类错误（config_missing）假定对所有候选同样致命；其余——
# 含 4xx 请求错误（管线检视 #2：中转站对参数/格式的拒绝是渠道相关的，
# 措辞漂移不应把多候选路由打成单点）、auth（各渠道 key 独立，一个 key
# 401/403 ≠ 全部失效）与 schema（中转站返回挑战页/非 JSON 垃圾是渠道级
# 故障）——都值得尝试下一个候选。
_FAILOVER_ERROR_KINDS = frozenset(
    {
        "timeout",
        "network",
        "server",
        "rate_limited",
        "provider_error",
        "empty_response",
        "model_not_found",
        "unsupported_model",
        "bad_request",
        "invalid_request",
        "unsupported_parameter",
        "http",
        "auth",
        "schema",
    }
)


def should_failover(error_kind: str) -> bool:
    return str(error_kind or "provider_error").strip().lower() in _FAILOVER_ERROR_KINDS


_LLM_ERROR_PUBLIC_MESSAGES = {
    "config_missing": "LLM 诊断未执行：openai_compatible provider 缺少 API key。",
    "timeout": "LLM 诊断失败：模型服务请求超时，请检查 base_url、网络代理和超时配置。",
    "auth": "LLM 诊断失败：模型服务鉴权失败，请检查 API key、模型权限和账号状态。",
    "rate_limited": "LLM 诊断失败：模型服务触发限流，请稍后重试或检查服务配额。",
    "server": "LLM 诊断失败：模型服务端返回错误，请稍后重试或检查服务状态。",
    "http": "LLM 诊断失败：模型服务返回 HTTP 错误，请检查 base_url、model 和请求格式。",
    "model_not_found": "LLM 诊断失败：当前模型不存在或未被该中转站注册，已尝试故障转移。",
    "unsupported_model": "LLM 诊断失败：当前中转站不支持该模型，已尝试故障转移。",
    "unsupported_parameter": "LLM 诊断失败：请求参数不被该渠道支持，已尝试故障转移。",
    "invalid_request": "LLM 诊断失败：该渠道拒绝请求格式或参数，已尝试故障转移。",
    "bad_request": "LLM 诊断失败：该渠道拒绝了本次请求（HTTP 4xx），已尝试故障转移。",
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
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    # 本次生成的路由尝试轨迹（ModelRouter.generate 成功返回前填充）。
    attempts: list[str] = Field(default_factory=list)
    # 响应体 ``id``：走 AxonHub 时它就是 ``requests.external_id``，是网关侧
    # 归因（实际渠道/逐跳错误/分项价）唯一的关联键（2026-09-25 B1）。
    # 非网关供应商也会填这里——查不到只会记 miss，不猜。
    remote_request_id: str = ""


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
            "（离线主链路测试）消息已完成接收、处理和出站；"
            "当前使用 static provider，未调用外部模型。"
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


def build_urlopen(
    proxy: str = "",
    urlopen: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """构建可选代理的 urlopen；显式代理优先于进程环境代理。"""
    if urlopen is not None:
        return urlopen
    normalized_proxy = str(proxy or "").strip()
    if not normalized_proxy:
        return request.urlopen
    return request.build_opener(
        request.ProxyHandler(
            {"http": normalized_proxy, "https": normalized_proxy}
        )
    ).open


# 响应体读取上限（管线检视 #7）：聊天补全正常响应远小于该值；故障中转站
# 返回的超大响应读到上限即拒绝，不再无界占用内存。错误体仅用于分类，上限更小。
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_ERROR_BODY_BYTES = 8192

_HTTP_CLIENT_LOCK = threading.Lock()
# 进程级 httpx.Client 连接桶（管线检视 #7 + S1 无界资源收口 2026-10-02）。
# 键 = 代理值维度（`str(proxy).strip()`）∪ 回环哨兵键，全部来自 config
# （`bot_download_proxy` 等）与本机固定哨兵，不是每请求新用户输入。现网实测
# 存活桶数 = 3（空代理 `""` 默认桶 / `BOT_DOWNLOAD_PROXY` 1 枚代理值 /
# `_LOOPBACK_DIRECT_KEY` 回环桶），故上界取 3 的 ≥2× 余量 **8 桶**——
# 覆盖"改配置换过一枚代理值"的热改代次窗口，绝不因代理键轮换无限堆积
# 已关闭的旧 Client。溢出按 LRU 关最旧桶（`OrderedDict.move_to_end` 记访问序，
# 淘汰 `popitem(last=False)`＝最久未用者），并 close 释放 socket，杜绝句柄泄漏。
_HTTP_CLIENTS: OrderedDict[str, httpx.Client] = OrderedDict()
_HTTP_CLIENTS_MAX_BUCKETS = 8

# 连接阶段上限：网络/代理/网关不可达时快败，交回 fail-fast 逐跳判定。
# 每请求覆盖超时时必须保住这一档——传标量会把四档一起改成同一个值。
_CONNECT_TIMEOUT_SECONDS = 5.0
# 空闲保活上限：本机出口对存量隧道的静默回收实测落在 5–20s，而 httpx 缺省
# keepalive_expiry 恰是 5.0s（同档竞走）⇒ 半开连接被池子交出去复用，一发就
# 挂到读超时。压到 2.0s 让客户端先关；回环那一跳的重连只是一次 TCP。
_KEEPALIVE_EXPIRY_SECONDS = 2.0


# 回环直连桶的缓存键：endpoint 指向本机网关（AxonHub）时专用。与空代理
# 键分开——空代理键保持 httpx 默认 trust_env 语义（temporal 天气依赖其
# 环境回落），回环桶必须无视环境/系统代理。
_LOOPBACK_DIRECT_KEY = "loopback:direct"


def _loopback_endpoint(endpoint_url: str) -> bool:
    """endpoint 是否指向本机回环（AxonHub 一类本地网关）。

    回环目标绕行代理毫无收益，反把 LLM 链拴在代理进程存活上——
    2026-09-29 22:09 Clash 7890 拒连窗口，本机网关健在而 bot 全链
    超时即实证。回环一律硬直连。
    """
    try:
        host = (urlsplit(str(endpoint_url or "")).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "::1", "localhost"}


def _shared_http_client(proxy: str = "", *, force_direct: bool = False) -> httpx.Client:
    """按代理维度缓存的进程级 httpx.Client（管线检视 #7）。

    LLM 主链路、视觉转译与 ASR 经同一 provider 类共用本客户端：连接池
    复用免去每次调用的 TCP+TLS 握手税。httpx 的代理是客户端级配置，故
    按代理值各持实例；Client 线程安全，调用方仅做每请求超时覆盖。

    force_direct（回环目标）＝硬直连桶：proxy=None 且 trust_env=False，
    环境变量与 Windows 系统代理都不参与——httpx 对 proxy=None 默认回落
    env/注册表代理，不关 trust_env 则「直连」形同虚设（本机用户级
    HTTP_PROXY 常驻 http://127.0.0.1:7890）。
    """
    key = _LOOPBACK_DIRECT_KEY if force_direct else str(proxy or "").strip()
    cached = _HTTP_CLIENTS.get(key)
    if cached is not None and not cached.is_closed:
        with _HTTP_CLIENT_LOCK:
            # 记访问序（LRU）：命中即挪到队尾，淘汰时只可能踢掉最久未用者。
            _HTTP_CLIENTS.move_to_end(key, last=True)
        return cached
    with _HTTP_CLIENT_LOCK:
        cached = _HTTP_CLIENTS.get(key)
        if cached is not None and not cached.is_closed:
            _HTTP_CLIENTS.move_to_end(key, last=True)
            return cached
        if cached is not None and cached.is_closed:
            # 同键旧实例已被关闭：先摘掉，避免占着名额又不可用。
            _HTTP_CLIENTS.pop(key, None)
        client = httpx.Client(
            proxy=None if force_direct else (key or None),
            trust_env=not force_direct,
            # 生产实弹（2026-09-15 LLM 超时告警排查）：连接与读取拆分——
            # 网络断时 connect 5s 快败，不再 30s×5 渠道干等 150s 才反馈。
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT_SECONDS,
                read=30.0,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=32,
                max_keepalive_connections=8,
                keepalive_expiry=_KEEPALIVE_EXPIRY_SECONDS,
            ),
        )
        _HTTP_CLIENTS[key] = client
        _HTTP_CLIENTS.move_to_end(key, last=True)
        # 有界淘汰：代理键维度虽由 config 约束，但热改换值会留下已关闭的
        # 旧 Client，绝不无界堆积。超出上界即按 LRU 关最旧桶并释放 socket。
        _enforce_http_client_bound(current_key=key)
        return client


def _enforce_http_client_bound(current_key: str) -> None:
    """把 ``_HTTP_CLIENTS`` 收进 ``_HTTP_CLIENTS_MAX_BUCKETS`` 上界（须持锁调用）。

    溢出按 LRU 淘汰：``OrderedDict`` 队首＝最久未用者，关闭并弹出它释放 socket；
    绝不弹出 ``current_key``（刚挪到队尾，理论上不在队首，防御性放回并止环）。
    生产稳态存活 3 桶 < 上界 8，本腿只在代理值热改换代的过渡窗口触发。
    """
    while len(_HTTP_CLIENTS) > _HTTP_CLIENTS_MAX_BUCKETS:
        evict_key, evicted = _HTTP_CLIENTS.popitem(last=False)
        if evict_key == current_key:
            # 理论上不会命中（刚挪到队尾）；放回并止环，别把在用桶关了。
            _HTTP_CLIENTS[evict_key] = evicted
            break
        try:
            evicted.close()
        except Exception:  # noqa: S110, BLE001 - 关闭失败不得阻断取用（socket 交 GC）。
            pass


def _brief_exc(exc: BaseException) -> str:
    """底层异常原文缩略（W1-② 证据链）：类型名 + 原文，交由
    ``LLMProviderError.__init__`` 统一单行化并截 200。

    只取我们自己抛点处的传输异常（httpx/urllib），不含响应体与鉴权头，
    无密钥泄露面。
    """
    return f"{type(exc).__name__}: {exc}"


def _read_stream_limited(
    response: httpx.Response,
    limit: int,
    *,
    truncate: bool = False,
    deadline: float | None = None,
) -> bytes:
    """限长流式读取。truncate=False：超限抛错（成功体护栏，防内存撑爆）；
    truncate=True：超限截断（错误体仅用于分类——超限抛 provider_error 会
    掩盖真实状态码，401+超大错误体不得误判为 provider_error）。

    deadline（time.monotonic 时刻）是整次响应的总预算：httpx 的 read 超时
    按 chunk 计时，慢滴流响应可永不触发单次超时、无限突破总预算——这里兜底。
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if deadline is not None and time.monotonic() > deadline:
            raise LLMProviderError("LLM request timed out", error_kind="timeout")
        total += len(chunk)
        if total > limit:
            if not truncate:
                raise LLMProviderError(
                    "LLM response exceeds size limit",
                    error_kind="provider_error",
                )
            chunks.append(chunk[: limit - (total - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def is_loopback_http_url(value: str) -> bool:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _base_url_error(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid"
    if parsed.username or parsed.password:
        return "unsafe"
    return ""


def _classify_http_error(status_code: int, response_body: str = "") -> str:
    """将 HTTP 错误映射为安全的内部类别，不暴露供应商原始响应。"""
    # 状态码优先：鉴权、限流和服务端故障的语义比响应体关键词稳定。
    if status_code in {401, 403}:
        return "auth"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code <= 599:
        return "server"

    body = str(response_body or "").strip().lower()
    if any(
        marker in body
        for marker in (
            "unsupported parameter",
            "unsupported_parameter",
            "unknown parameter",
            "invalid parameter",
        )
    ):
        return "unsupported_parameter"
    if any(
        marker in body
        for marker in (
            "model not found",
            "model_not_found",
            "model does not exist",
            "no such model",
            "unknown model",
        )
    ):
        return "model_not_found"
    if any(
        marker in body
        for marker in (
            "unsupported model",
            "model unsupported",
            "model not supported",
            "model is not supported",
        )
    ):
        return "unsupported_model"
    if any(
        marker in body
        for marker in (
            "invalid request",
            "invalid_request",
            "bad request",
            "validation error",
        )
    ):
        return "invalid_request"
    # 其余 4xx 一律按渠道相关错误分类（可故障转移）；未被 urllib/httpx
    # 以异常形式抛出的状态码才落到 "http" 兜底。
    if 400 <= status_code <= 499:
        return "bad_request"
    return "http"


def _read_http_error_body(exc: error.HTTPError, *, max_bytes: int = 8192) -> str:
    """读取有限长度的错误体，仅供分类；绝不写入公开异常消息或日志。"""
    try:
        raw = exc.read(max_bytes)
    except Exception:  # noqa: BLE001 - 错误体不可读时仍按状态码分类。
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")[:max_bytes]
    return str(raw or "")[:max_bytes]


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


def _first_int(*values: object) -> int:
    """返回第一个非负整数取值；全部缺失返回 0。"""
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdecimal():
            return int(value)
    return 0


#: 回包 usage 的读侧硬顶（PROVIDERS-R2 票 ATKLLM-2，2026-09-28）。被控或替换过的中转站
#: 可以对一次小额调用虚报 1e12 级 token，而成本按 token 线性放大 ⇒ 虚报直接变成天文账单，
#: 且 F-2 信任边界的对照基线又由**同一份不可信 usage** 算出（自指放行）。取现仓可见的
#: 真实上限（上下文 ≤2M + ``max_tokens`` 顶 65538）的数倍余量：合法回包咬不到，1e12 级虚报
#: 被切断。**要改口径只改这一行**（两消费臂都从这一处吃数）。
#: 刻意写成裸赋值、不加 ``Final`` 标注：注毒锁按 ``ast.Assign`` 认这枚常数，
#: 带标注会退化成 ``ast.AnnAssign`` 而看不见 ⇒ 常数锁假绿。
REPORTED_TOKEN_HARD_CAP = 10_000_000


def _extract_usage(usage: object, finish_reason: object = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(usage, dict):
        result = dict(usage)
    result.pop("finish_reason", None)
    # 归一化缓存命中/创建 token（存在才写键）：
    # - OpenAI 风格：prompt_tokens_details.cached_tokens
    # - DeepSeek 风格：prompt_cache_hit_tokens / prompt_cache_miss_tokens
    # - Anthropic 风格：cache_read_input_tokens / cache_creation_input_tokens
    details = result.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    cache_read = _first_int(
        result.get("prompt_cache_hit_tokens"),
        details.get("cached_tokens"),
        result.get("cached_tokens"),
        result.get("cache_read_input_tokens"),
    )
    cache_write = _first_int(
        details.get("cache_creation_tokens"),
        result.get("cache_creation_input_tokens"),
        result.get("cache_write_tokens"),
    )
    if cache_read > 0:
        result["cache_read_tokens"] = cache_read
    if cache_write > 0:
        result["cache_write_tokens"] = cache_write
    # PROVIDERS-R2 票 ATKLLM-2：回包 usage 的读侧硬顶（夹在这里＝唯一出点，
    # 台账 channel_spec 臂与 chat 审计臂同吃这一份 dict，夹一次全链有界）。
    # 只夹顶层 ``*_tokens`` 的**正整数**：负值/布尔原样交下游非负闸，本腿不重算语义；
    # 夹过必须留痕（静默改数＝谎报，事后无从分辨网关真给了这个数）。
    clamped_keys: list[str] = []
    for _token_key, _token_value in list(result.items()):
        if not _token_key.endswith("_tokens"):
            continue
        if isinstance(_token_value, bool) or not isinstance(_token_value, int):
            continue
        if _token_value > REPORTED_TOKEN_HARD_CAP:
            result[_token_key] = REPORTED_TOKEN_HARD_CAP
            clamped_keys.append(_token_key)
    if clamped_keys:
        result["usage_report_sanity"] = {
            "cap": REPORTED_TOKEN_HARD_CAP,
            "clamped_keys": clamped_keys,
        }
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
        provider_name: str = "openai_compatible",
        proxy: str = "",
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.strip().rstrip("/")
        self.endpoint_url = normalize_openai_chat_endpoint(base_url)
        self.timeout_seconds = timeout_seconds
        self.provider_name = provider_name
        self.proxy = str(proxy or "").strip()
        # 测试注入缝：显式传入 urlopen 走遗留 urllib 路径；None = 生产路径
        # （进程级 httpx.Client 单例 + 响应限长，见 _post_via_httpx）。
        self._urlopen = urlopen

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
        }
        max_tokens = kwargs.get("max_tokens", 0)
        if isinstance(max_tokens, (int, float)) and int(max_tokens) > 0:
            # 0 或负数 = 不设上限：不向 API 传 max_tokens，由模型自行决定。
            payload["max_tokens"] = int(max_tokens)
        reasoning_effort = str(kwargs.get("reasoning_effort", "") or "").strip().lower()
        qwen_compatible = "dashscope" in self.base_url.lower() or "qwen" in self.model.lower()
        if qwen_compatible and reasoning_effort in {"off", "low", "medium", "high", "xhigh", "max"}:
            payload["enable_thinking"] = reasoning_effort != "off"
        elif reasoning_effort in {"low", "medium", "high", "xhigh", "max"}:
            payload["reasoning_effort"] = reasoning_effort
        # 工具调用（OpenAI function calling 兼容）：由调用方注入 tools 清单。
        tools = kwargs.get("tools")
        if isinstance(tools, list) and tools:
            payload["tools"] = tools
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # 部分中转站的 WAF 会拦截 Python-urllib 默认 UA（403/1010）；
            # 使用普通浏览器 UA，不改变 API 协议或鉴权方式。
            "User-Agent": "Mozilla/5.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout_override = kwargs.get("timeout_seconds")
        request_timeout = self.timeout_seconds
        if isinstance(timeout_override, (int, float)) and float(timeout_override) > 0:
            request_timeout = min(request_timeout, float(timeout_override))

        if self._urlopen is not None:
            response_body = self._post_via_urllib(body, headers, request_timeout)
        else:
            response_body = self._post_via_httpx(body, headers, request_timeout)

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
        raw_tool_calls = message.get("tool_calls")
        tool_calls: list[dict[str, Any]] = []
        if isinstance(raw_tool_calls, list):
            for item in raw_tool_calls:
                if not isinstance(item, dict):
                    continue
                function = item.get("function")
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                tool_calls.append(
                    {
                        "id": str(item.get("id") or ""),
                        "type": str(item.get("type") or "function"),
                        "function": {
                            "name": str(function.get("name") or ""),
                            "arguments": str(function.get("arguments") or "{}"),
                        },
                    }
                )

        content = message.get("content")
        content_source = "content"
        if content is None or content == "":
            # 推理模型（如 deepseek-reasoner）可能把 token 全花在思维链上，
            # 导致 content 为空。回退到 reasoning_content 的尾部，保证用户
            # 至少能得到一句话；并保留标记便于审计。
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning.strip()[-600:]
                content_source = "reasoning_fallback"
        # 工具调用轮次允许 content 为空：调用方拿到 tool_calls 后回填工具结果。
        if content is None or content == "":
            if not tool_calls:
                raise LLMProviderError(
                    "LLM returned empty text",
                    error_kind="empty_response",
                )
            content = ""
        try:
            text = _extract_message_content_text(content) if content != "" else ""
        except TypeError as exc:
            raise LLMProviderError(
                "LLM response schema is invalid",
                error_kind="schema",
            ) from exc

        if not text and not tool_calls:
            raise LLMProviderError(
                "LLM returned empty text",
                error_kind="empty_response",
            )

        usage = _extract_usage(data.get("usage"), choice.get("finish_reason"))
        if content_source == "reasoning_fallback":
            usage["content_source"] = "reasoning_fallback"
        remote_id = data.get("id")
        # 响应体 id 是不完全可信面：截断到合理上限，杜绝上游/中转回一个超长
        # id 把账本行、归因键撑爆（F-7 的行膨胀臂；「同 id 双计」的归因臂需动
        # apply_attribution 去重语义，风险更高，移交处理）。
        remote_id_str = remote_id if isinstance(remote_id, str) else ""
        return LLMReply(
            text=text,
            provider=self.provider_name,
            model=str(payload["model"]),
            confidence=1.0,
            raw_usage=usage,
            tool_calls=tool_calls,
            remote_request_id=remote_id_str[:_REMOTE_REQUEST_ID_MAX_LEN],
        )

    def _post_via_urllib(
        self, body: bytes, headers: dict[str, str], request_timeout: float
    ) -> str:
        """遗留传输路径：仅当测试显式注入 urlopen 时使用。"""
        assert self._urlopen is not None
        http_request = request.Request(
            self.endpoint_url,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with self._urlopen(http_request, timeout=request_timeout) as response:
                return response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = _read_http_error_body(exc)
            raise LLMProviderError(
                f"LLM HTTP request failed with status {exc.code}",
                error_kind=_classify_http_error(exc.code, response_body),
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

    def _post_via_httpx(
        self, body: bytes, headers: dict[str, str], request_timeout: float
    ) -> str:
        """生产传输路径：进程级 httpx.Client 连接池复用 + 响应限长。"""
        # 回环网关（AxonHub 127.0.0.1）硬直连，不进代理桶。
        client = _shared_http_client(
            self.proxy, force_direct=_loopback_endpoint(self.endpoint_url)
        )
        deadline = time.monotonic() + max(0.0, request_timeout)
        # 每请求只覆盖读预算，connect 守住快败上限。传标量＝httpx 把四档一起
        # 改成同一个值，客户端那份 connect 快败在生产路径从未生效（实弹
        # 2026-09-29：40s×数跳挂满才认输，用户侧正是"收到消息一直不回"）。
        stream_timeout = httpx.Timeout(
            timeout=request_timeout,
            connect=min(_CONNECT_TIMEOUT_SECONDS, request_timeout),
        )
        try:
            with client.stream(
                "POST",
                self.endpoint_url,
                content=body,
                headers=headers,
                timeout=stream_timeout,
            ) as response:
                if response.status_code >= 400:
                    error_body = _read_stream_limited(
                        response, _MAX_ERROR_BODY_BYTES, truncate=True, deadline=deadline
                    )
                    raise LLMProviderError(
                        f"LLM HTTP request failed with status {response.status_code}",
                        error_kind=_classify_http_error(
                            response.status_code,
                            error_body.decode("utf-8", errors="replace"),
                        ),
                    )
                return _read_stream_limited(
                    response, _MAX_RESPONSE_BYTES, deadline=deadline
                ).decode(
                    "utf-8", errors="replace"
                )
        except LLMProviderError:
            raise
        except httpx.TimeoutException as exc:
            # 连接类超时（含 ConnectTimeout）与读取超时分类分离：前者=网络/
            # 代理/网关不可达（告警归 network，运营者先查本机出口），后者=
            # 上游慢（归 timeout，查供应商）。detail 由调用方携带轨迹。
            if isinstance(exc, httpx.ConnectTimeout):
                raise LLMProviderError(
                    "LLM gateway/upstream unreachable (connect timeout)",
                    error_kind="network",
                    detail=_brief_exc(exc),
                ) from exc
            raise LLMProviderError(
                "LLM request timed out", error_kind="timeout", detail=_brief_exc(exc)
            ) from exc
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.ConnectError):
                raise LLMProviderError(
                    "LLM gateway/upstream unreachable (connect failed)",
                    error_kind="network",
                    detail=_brief_exc(exc),
                ) from exc
            raise LLMProviderError(
                "LLM network error", error_kind="network", detail=_brief_exc(exc)
            ) from exc
        except Exception as exc:
            raise LLMProviderError(
                "LLM provider transport error",
                error_kind="provider_error",
                detail=_brief_exc(exc),
            ) from exc
