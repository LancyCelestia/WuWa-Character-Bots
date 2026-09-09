"""萌娘百科查询能力（bot.moegirl）：`萌娘百科 <词条>` + 二次元问句自动查询。

显式指令走与 bot.wiki 相同的确定性命令链路；问句（「初音未来是谁？」）
先归一化出实体再查萌百：可信主词条（标题精确匹配或唯一候选）→ 简介+
链接；多候选 → 候选列表；无结果/网络失败 → 返回降级标记，由 handler
把同一条消息转交 AI 人格聊天链路，用户无感。

性能约定（回复速度优先）：问句路径全程至多「1 次搜索 + 1 次摘要」两次
外呼，紧超时 + 总预算硬约束；300s TTL 缓存让热门词条二次查询零外呼。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.moegirl import (
    DEFAULT_API_BASES,
    MoegirlHit,
    moegirl_page_summary,
    moegirl_search,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:萌娘百科|萌百|moegirl)\s*(?P<query>.+)$", re.IGNORECASE
)

# 长条目在前，避免「帮我查」抢在「帮我查一下」之前剥离。
_QUESTION_STRIP_PREFIXES = sorted(
    (
        "请问", "帮我查一下", "帮我查查", "帮我查", "帮我看看",
        "我想了解一下", "我想知道", "介绍一下", "介绍下", "查一下",
        "查查", "搜索", "搜一下", "什么是",
    ),
    key=len,
    reverse=True,
)
_QUESTION_STRIP_SUFFIXES = sorted(
    (
        "是谁呀", "是谁啊", "是谁呢", "是谁", "是什么呀", "是什么啊",
        "是什么意思", "是什么", "是啥呀", "是啥", "什么东西", "的资料",
        "的介绍", "的信息", "的词条",
    ),
    key=len,
    reverse=True,
)
_TRIM_CHARS = " \t\r\n「」『』“”‘’\"'《》【】·•。？！?!~～，,。；;：:"
# 人称问句（你是谁/我推是什么）交给聊天链路；整词命中即拒绝。
_PRONOUN_ENTITIES = frozenset(
    {"你", "我", "他", "她", "它", "您", "谁", "自己", "大家", "咱",
     "你们", "我们", "他们", "她们", "它们", "本人"}
)
_PRONOUN_PREFIXES = ("你", "我", "您", "咱")

_ENTITY_MIN_LEN = 2
_ENTITY_MAX_LEN = 30
_CANDIDATE_SNIPPET_CHARS = 60


def normalize_entity_question(text: str) -> str | None:
    """「初音未来是谁？」→「初音未来」；非实体问句返回 None。

    必须剥到至少一个问句标记（是谁/是什么/介绍一下…）才算实体问句，
    纯名词、普通闲聊一律返回 None；剥离后剩人称代词、过短/过长、
    含链接的同样拒绝（交给聊天/其他路由）。
    """
    value = str(text or "").strip().strip(_TRIM_CHARS)
    if not value:
        return None
    stripped_any = False
    changed = True
    while changed:
        changed = False
        for prefix in _QUESTION_STRIP_PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix):
                value = value[len(prefix):].strip(_TRIM_CHARS)
                stripped_any = True
                changed = True
                break
        for suffix in _QUESTION_STRIP_SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)].strip(_TRIM_CHARS)
                stripped_any = True
                changed = True
                break
    if not stripped_any:
        return None
    value = value.strip(_TRIM_CHARS)
    if not (_ENTITY_MIN_LEN <= len(value) <= _ENTITY_MAX_LEN):
        return None
    if value in _PRONOUN_ENTITIES or value.startswith(_PRONOUN_PREFIXES):
        return None
    if "http" in value.lower() or "/" in value:
        return None
    return value


def is_entity_question(text: str) -> bool:
    """路由判定：是否为可自动查萌百的实体问句。"""
    return normalize_entity_question(text) is not None


def is_moegirl_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def extract_moegirl_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a moegirl command")
    return match.group("query").strip()


# ---------------------------------------------------------------- 编排


def _norm_title(value: str) -> str:
    return re.sub(r"[\s_]+", "", (value or "").strip()).casefold()


def pick_main_hit(hits: list[MoegirlHit], entity: str) -> MoegirlHit | None:
    """可信主词条判定：标题精确匹配优先；唯一候选允许前缀匹配。

    多候选且无精确匹配 = 不可信（搜索相关性会夹带同名作品/消歧义页），
    由调用方改走候选列表。
    """
    if not hits:
        return None
    want = _norm_title(entity)
    if not want:
        return None
    for hit in hits:
        if _norm_title(hit.title) == want:
            return hit
    if len(hits) == 1 and _norm_title(hits[0].title).startswith(want):
        return hits[0]
    return None


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    limit = max(20, int(limit))
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    boundary = max(prefix.rfind(mark) for mark in "。！？.!?\n")
    if boundary >= limit // 2:
        prefix = prefix[: boundary + 1]
    return prefix.rstrip() + "…"


def format_main_result(hit: MoegirlHit, *, max_chars: int = 300) -> str:
    lines = [f"【{hit.title}】"]
    if hit.snippet:
        lines.append(_clip(hit.snippet, max_chars))
    if hit.url:
        lines.append(f"🔗 萌娘百科：{hit.url}")
    return "\n".join(lines)


def format_candidates(hits: list[MoegirlHit], *, limit: int = 5) -> str:
    lines = ["萌娘百科上找到几个相关词条，你想问的可能是："]
    for index, hit in enumerate(hits[:limit], 1):
        snippet = _clip(hit.snippet, _CANDIDATE_SNIPPET_CHARS)
        line = f"{index}. {hit.title}"
        if snippet:
            line += f"｜{snippet}"
        lines.append(line)
    lines.append("回复「萌娘百科 <词条名>」可看详细介绍。")
    return "\n".join(lines)


@dataclass(frozen=True)
class MoegirlQuestionOutcome:
    """问句路径结果：hit=已生成回复文本；degrade=转交 AI 聊天链路。"""

    status: str  # "hit" | "degrade"
    body: str = ""
    entity: str = ""
    elapsed_ms: int = 0


_KB_PROVIDER_CACHE: dict[str, Any] = {}
_KB_LOCK = __import__("threading").Lock()


def local_kb_answer(config: Any | None, entity: str, *, max_chars: int = 500) -> str | None:
    """本地向量知识库优先：命中返回格式化知识条目，未命中返回 None。

    用户本地已建鸣潮/方舟/原神等全套游戏知识库——问这些内容时不应
    再外查萌百（质量差且与本地设定冲突）。命中判定：top chunk 标题
    与实体互含（规范化后），防止弱相关 chunk 冒充答案。
    """
    if config is None or not entity:
        return None
    try:
        from plugins.bot_unified_runtime.character.vector_knowledge import (
            build_vector_knowledge_provider,
        )

        key = str(id(config))
        with _KB_LOCK:
            provider = _KB_PROVIDER_CACHE.get(key)
            if provider is None:
                provider = build_vector_knowledge_provider(config)
                _KB_PROVIDER_CACHE[key] = provider
        if provider is None:
            return None
        retrieve = getattr(provider, "retrieve", None)
        if not callable(retrieve):
            return None
        chunks = list(retrieve(entity) or [])
    except Exception:  # noqa: BLE001 - 本地库不可用时走原有萌百链路。
        return None
    if not chunks:
        return None

    def _norm(value: str) -> str:
        return re.sub(r"[\s_]+", "", (value or "")).casefold()

    want = _norm(entity)
    top = chunks[0]
    if want not in _norm(top.title) and _norm(top.title) not in want:
        return None
    content = re.sub(r"\s+", " ", str(top.content or "")).strip()
    if not content:
        return None
    body = f"【{top.title}】\n{content[:max_chars]}"
    if len(content) > max_chars:
        body += "…"
    return body


def question_lookup(
    text: str,
    *,
    config: Any | None = None,
    search_fn: Callable[..., list[MoegirlHit]] | None = None,
    page_fn: Callable[..., MoegirlHit | None] | None = None,
) -> MoegirlQuestionOutcome:
    """问句自动查询主流程；任何失败都以 degrade 收尾，不抛异常。

    ``search_fn``/``page_fn`` 可注入假实现做离线测试；默认实现按配置
    带上镜像域名与超时。主词条页摘要拉取失败时回退搜索自带摘要，
    不降级（已有可信命中就不浪费）。
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    entity = normalize_entity_question(text)
    if entity is None:
        return MoegirlQuestionOutcome(status="degrade", elapsed_ms=elapsed())
    api_bases = _configured_api_bases(config)
    timeout = float(
        getattr(config, "bot_moegirl_timeout_seconds", 5.0) or 5.0
    ) if config is not None else 5.0
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config is not None else ""
    max_chars = int(
        getattr(config, "bot_moegirl_summary_max_chars", 300) or 300
    ) if config is not None else 300

    search = search_fn or (
        lambda query, **kw: moegirl_search(
            query,
            api_bases=api_bases,
            timeout_seconds=timeout,
            proxy=proxy,
            **kw,
        )
    )
    try:
        hits = search(entity)
    except ParseHttpError:
        return MoegirlQuestionOutcome(
            status="degrade", entity=entity, elapsed_ms=elapsed()
        )
    except Exception:  # noqa: BLE001 - 查询层任何异常都按降级处理。
        return MoegirlQuestionOutcome(
            status="degrade", entity=entity, elapsed_ms=elapsed()
        )
    if not hits:
        return MoegirlQuestionOutcome(
            status="degrade", entity=entity, elapsed_ms=elapsed()
        )

    main = pick_main_hit(hits, entity)
    if main is None:
        # 多候选/无精确命中：多半是普通闲聊问题（"QQ用户是谁"）被问句
        # 路由误捕，词条选择列表对这类场景是骚扰。无感降级聊天链路；
        # 明确想查百科的用户请用 /萌娘 指令（那里保留候选列表）。
        return MoegirlQuestionOutcome(
            status="degrade", entity=entity, elapsed_ms=elapsed()
        )
    page = main
    fetch_page = page_fn
    if fetch_page is None:
        fetch_page = lambda title, **kw: moegirl_page_summary(
            title,
            api_bases=api_bases,
            timeout_seconds=timeout,
            proxy=proxy,
            **kw,
        )
    try:
        fetched = fetch_page(main.title)
        if fetched is not None:
            page = fetched
    except ParseHttpError:
        pass
    except Exception:  # noqa: BLE001, S110 - 摘要失败回退搜索摘要，不阻断回复。
        pass
    return MoegirlQuestionOutcome(
        status="hit",
        body=format_main_result(page, max_chars=max_chars),
        entity=entity,
        elapsed_ms=elapsed(),
    )


def _configured_api_bases(config: Any | None) -> tuple[str, ...]:
    if config is None:
        return DEFAULT_API_BASES
    bases: list[str] = []
    for field in ("bot_moegirl_api_base", "bot_moegirl_mirror_api_base"):
        value = str(getattr(config, field, "") or "").strip()
        if value:
            bases.append(value)
    return tuple(bases) or DEFAULT_API_BASES


def _api_bases(config: Any | None) -> tuple[str, ...]:
    return _configured_api_bases(config)


# ---------------------------------------------------------------- 显式指令能力


def build_moegirl_capability(config: Any | None = None) -> Any:
    """`萌娘百科 <词条>`：精确页摘要 → 搜索可信主词条 → 候选列表。"""
    api_bases = _api_bases(config)
    timeout = float(
        getattr(config, "bot_moegirl_timeout_seconds", 5.0) or 5.0
    ) if config else 5.0
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""
    max_chars = int(
        getattr(config, "bot_moegirl_summary_max_chars", 300) or 300
    ) if config else 300

    def _page(title: str) -> MoegirlHit | None:
        return moegirl_page_summary(
            title, api_bases=api_bases, timeout_seconds=timeout, proxy=proxy
        )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        del decision
        try:
            query = extract_moegirl_query(message.plain_text)
        except ValueError:
            query = ""
        if not query:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                body="用法：萌娘百科 <词条>，例如『萌娘百科 洛天依』；也可以直接问『初音未来是谁』。",
                audit_tags=["moegirl", "missing_query"],
            )
        page: MoegirlHit | None = None
        try:
            page = _page(query)
        except ParseHttpError:
            page = None
        if page is not None:
            return _text_result(message, page, query, max_chars)
        try:
            hits = moegirl_search(
                query, api_bases=api_bases, timeout_seconds=timeout, proxy=proxy
            )
        except ParseHttpError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                body="萌娘百科暂时连不上，稍后再试试。",
                audit_tags=["moegirl", "network_error"],
            )
        if not hits:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                body=f"萌娘百科上没有找到『{query}』。",
                audit_tags=["moegirl", "not_found"],
            )
        main = pick_main_hit(hits, query)
        if main is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                body=format_candidates(hits),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["moegirl", "ambiguous", f"moegirl_query:{query[:20]}"],
            )
        if main.snippet or main.url:
            return _text_result(message, main, query, max_chars)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.moegirl",
            kind="text",
            body=format_candidates(hits),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["moegirl", "ambiguous", f"moegirl_query:{query[:20]}"],
        )

    return capability


def _text_result(
    message: IncomingMessage, hit: MoegirlHit, query: str, max_chars: int
) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.moegirl",
        kind="text",
        title="萌娘百科",
        body=format_main_result(hit, max_chars=max_chars),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        audit_tags=["moegirl", f"moegirl_query:{query[:20]}"],
    )
