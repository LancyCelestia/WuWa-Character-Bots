"""萌娘百科查询能力（bot.moegirl）：`萌娘百科 <词条>` + 二次元问句自动查询。

2026-09-27 甲+丙合并批（输出契约变更，判据=用户原话「要 bot 读百科、用她的世界
观和语气说出来，不甩链接」）：

* 本能力**零 LLM 通路**——百科/本地知识库正文一律只作**接地块**（经消息契约
  `kb_grounding_text/kb_grounding_label`）进入聊天链的既有一次生成，由 chat.py
  装配点统一过中央件 guard_secondhand_text；出站全文无 URL、无 🔗。
* 显式指令走确定性命令链路：本地命中→ grounding；未命中才外查萌百（search+page
  至多两次外呼、紧超时+总预算、300s TTL 缓存不变）；grounding 命中转交聊天链，
  无条目/歧义/网络失败三类降级可判别（degrade_reason）。
* 本地命中判据（放宽但保住防冒充）：库内标题普遍带出处后缀
  （「予愿安洁莉娜（明日方舟）·萌娘百科」），旧「互含」判据认不下这类页；
  新判据=剥尾随来源段后「规范化同名」或以实体开头且后续**只有**限定括号，
  并现两个不同限定词判歧义不押注，消歧页/弱相关/近义不同实体一律不认。
  逐条反例锁在 tests/test_kb_grounding_chat.py。
"""

from __future__ import annotations

import random
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
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)
from plugins.bot_unified_runtime.domains.location.data.moegirl import (
    DEFAULT_API_BASES,
    MoegirlHit,
    moegirl_page_summary,
    moegirl_search,
)

# ASCII 别名右侧词边界（stocks _alias_hit 先例）：moegirlxx 字母延续不触发。
# 拼音（T-Spec T1.5/T1.6）：mengbai/mb 查重无冲突（fix-py1-report.md）。
_COMMAND_RE = re.compile(
    r"^[/!！]?(?:萌娘百科|萌百|moegirl(?![a-z0-9])|mengbai(?![a-z0-9])|mb(?![a-z0-9]))\s*(?P<query>.+)$",
    re.IGNORECASE,
)

# 长条目在前，避免「帮我查」抢在「帮我查一下」之前剥离。
_QUESTION_STRIP_PREFIXES = sorted(
    (
        "请问", "帮我查一下", "帮我查查", "帮我查", "帮我看看",
        "我想了解一下", "我想知道", "介绍一下", "介绍下", "查一下",
        "查查", "搜索", "搜一下", "什么是",
        # 繁體形（TRA 草稿 介紹一下 词条）：繁體问句入口同口径。
        "請問", "幫我查一下", "幫我查查", "幫我查", "幫我看看",
        "我想了解一下", "我想知道", "介紹一下", "介紹下", "查一下",
        "查查", "搜索", "搜一下", "什麼是",
    ),
    key=len,
    reverse=True,
)
_QUESTION_STRIP_SUFFIXES = sorted(
    (
        "是谁呀", "是谁啊", "是谁呢", "是谁", "是什么呀", "是什么啊",
        "是什么意思", "是什么", "是啥呀", "是啥", "什么东西", "的资料",
        "的介绍", "的信息", "的词条",
        # 繁體形（TRA 草稿 是誰/是什麼 词条）。
        "是誰呀", "是誰啊", "是誰呢", "是誰", "是什麼呀", "是什麼啊",
        "是什麼意思", "是什麼", "是啥呀", "是啥", "什麼東西", "的資料",
        "的介紹", "的信息", "的詞條",
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

# 域词守卫（invest-moegirl-hijack §四 B）：剥词后的剩串若是其他能力域词
# （天气/预报形），不是萌百实体——「帮我查X天气」应让路 NL 层归一化天气。
# 「天气之子」类词条无空格、不以域词收尾，零误伤。
_DOMAIN_TAIL_SUFFIXES = ("天气", "天氣", "预报", "預報")
_DOMAIN_HEAD_PREFIXES = ("天气", "天氣")


def _is_domain_entity(value: str) -> bool:
    """剥词后的实体命中其他能力域词形态（天气/预报）→ True。"""
    if value.endswith(_DOMAIN_TAIL_SUFFIXES):
        return True
    return value.startswith(_DOMAIN_HEAD_PREFIXES) and " " in value


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
    if _is_domain_entity(value):
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
    """词条正文的统一人话格式：标题行 + 简介 + 一行中文出处（**永不拼 URL/🔗**）。

    2026-09-27 甲批：旧版在末行拼「🔗 萌娘百科：<url>」，用户裁定甩链接不合格；
    出处降为一行中文小字。URL 形态在进 prompt / 进正文前也会被 `_strip_urls`
    再洗一遍——双保险，但这里根本不产它。
    """
    lines = [f"【{hit.title}】"]
    if hit.snippet:
        lines.append(_strip_urls(_clip(hit.snippet, max_chars)))
    lines.append(f"出自：萌娘百科·{hit.title}")
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
class MoegirlGrounding:
    """百科接地块：只作为聊天链一次生成的资料进 prompt，永不直接当答案外发。

    text 已剥 URL 并压平空白；label 是一行中文来源标签（进
    guard_secondhand_text 的 source_label 与降级出处行），不进任何判据。
    """

    text: str
    label: str
    origin: str  # "local_kb" | "moegirl"
    title: str = ""


@dataclass(frozen=True)
class MoegirlQuestionOutcome:
    """问句路径结果：hit=拿到接地块（转聊天链生成）；degrade=直转聊天链。

    degrade_reason 让「不是实体问句 / 无条目 / 网络失败 / 多候选歧义」四类
    可判别（诚实降级，绝不编内容填空）。
    """

    status: str  # "hit" | "degrade"
    entity: str = ""
    grounding: MoegirlGrounding | None = None
    degrade_reason: str = ""  # "" | not_entity | no_entry | network_error | ambiguous
    elapsed_ms: int = 0


# ---------------------------------------------------------------- 接地取数

# 出站/进 prompt 前统一剥链接（形态判据，宁多洗不漏放）：协议 URL 与裸 www。
_URL_STRIP_RE = re.compile(r"(?:https?://|www\.)\S*", re.IGNORECASE)
_DISAMBIG_MARKERS = ("消歧", "歧义", "disambig")
# 尾随来源段（·萌娘百科 / ·B站wiki / ·prts_arknights）——只有「像来源」的尾段
# 才剥：含 wiki/百科/萌百/moegirl/prts/bilibili/bangumi 或纯 ASCII 词形。
# 名字本体含间隔号的（「安洁莉娜·卡多尔」）尾段是 CJK 人名节，不剥 ⇒ 不冒充。
_SOURCE_SUFFIX_TOKEN_RE = re.compile(r"(?:[·&｜|])([^·&｜|]*)$")
_SOURCE_HINT_RE = re.compile(
    r"(wiki|百科|萌百|moegirl|prts|bilibili|bangumi|fandom)", re.IGNORECASE
)


def _strip_urls(text: str) -> str:
    return _URL_STRIP_RE.sub("", str(text or ""))


def _norm_title(value: str) -> str:
    return re.sub(r"[\s_]+", "", (value or "")).casefold()


def _title_grounding_kind(title: str, entity: str) -> str | None:
    """标题对实体的接地形态：''=同名正页；非空=带限定词页；None=不认。

    防冒充三判据（每条都有反例锁，tests/test_kb_grounding_chat.py）：
    ①消歧页直接不认；②只剥「像来源」的尾段（黑猫→黑猫诺儿 这类近义不同
    实体因后续是名字本体而判不认）；③限定括号必须紧贴实体之后。
    """
    t = _norm_title(title)
    want = _norm_title(entity)
    if not t or not want:
        return None
    if any(marker in t for marker in _DISAMBIG_MARKERS):
        return None
    # 反复剥尾随来源段（多来源叠后缀也认）。
    while True:
        match = _SOURCE_SUFFIX_TOKEN_RE.search(t)
        if match is None:
            break
        tail = match.group(1)
        if not tail or (not _SOURCE_HINT_RE.search(tail) and not re.fullmatch(r"[a-z0-9]+", tail)):
            break
        t = t[: match.start()]
    if not t:
        return None
    if t == want:
        return ""
    if t.startswith(want):
        rest = t[len(want):]
        qual = re.fullmatch(r"[（(]([^（）()]+)[）)]", rest)
        if qual is not None:
            return qual.group(1)
    return None


def _kb_grounding_from_chunk(chunk: Any, entity: str, max_chars: int) -> MoegirlGrounding | None:
    title = str(getattr(chunk, "title", "") or "")
    content = _strip_urls(re.sub(r"\s+", " ", str(getattr(chunk, "content", "") or "")).strip())
    if not content:
        return None
    body = _clip(content, max_chars)
    if not body:
        return None
    return MoegirlGrounding(
        text=body,
        label=f"本地知识库·{title.strip() or entity}",
        origin="local_kb",
        title=title.strip() or entity,
    )


def select_kb_chunks(chunks: Any, entity: str) -> Any | None:
    """从检索结果里选「确属该实体」的块：同名正页先到先得；只有带限定词
    命中且限定词唯一时取之（pick_main_hit『唯一候选允许』同哲学）；并现
    两个不同限定词（不同游戏同名角色）判歧义，绝不押注。"""
    want = _norm_title(entity)
    if not want:
        return None
    qualified: dict[str, Any] = {}
    for chunk in chunks or []:
        kind = _title_grounding_kind(str(getattr(chunk, "title", "") or ""), want)
        if kind is None:
            continue
        if kind == "":
            return chunk
        title_key = _norm_title(str(getattr(chunk, "title", "") or ""))
        if title_key not in qualified:
            qualified[title_key] = chunk
        if len(qualified) > 1:
            return None
    return next(iter(qualified.values()), None)


_KB_GROUNDING_CACHE: dict[str, Any] = {}
_KB_LOCK = __import__("threading").Lock()
_KB_UNAVAILABLE = object()


def _merged_grounding_retrieve(config: Any) -> Any | None:
    """人格向量库 + Crawl Wiki 向量库的合并检索口（全部复用中央件真身）。

    旧 local_kb_answer 只查人格库——鸣潮/方舟/原神语料实际在 kb_wiki 库
    （knowledge_embeddings.sqlite3 35k 块 vs kb_wiki_embeddings.sqlite3 740k 块），
    这才是「本地优先」在生产恒 miss 的真根因（2026-09-27 现算）。
    """
    key = str(id(config))
    with _KB_LOCK:
        cached = _KB_GROUNDING_CACHE.get(key)
        if cached is _KB_UNAVAILABLE:
            return None
        if callable(cached):
            return cached
    fn: Any = None
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
            build_vector_knowledge_provider,
        )
        from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
            MergedKnowledgeRetriever,
            build_kb_wiki_retriever,
        )

        legs: list[Any] = []
        persona = build_vector_knowledge_provider(config)
        if getattr(persona, "available", False):
            legs.append(persona)
        wiki = build_kb_wiki_retriever(config)
        if getattr(wiki, "available", False):
            legs.append(wiki)
        merged = MergedKnowledgeRetriever(legs)
        if legs and getattr(merged, "available", False):
            fn = merged.retrieve
    except Exception:  # noqa: BLE001 - 本地检索链不可用时回退外查萌百旧链路。
        fn = None
    with _KB_LOCK:
        _KB_GROUNDING_CACHE[key] = fn if callable(fn) else _KB_UNAVAILABLE
    return fn if callable(fn) else None


def local_kb_grounding(
    config: Any | None,
    entity: str,
    *,
    max_chars: int = 500,
    retrieve_fn: Any | None = None,
) -> MoegirlGrounding | None:
    """本地知识库优先接地：命中返回接地块，未命中/故障返回 None。

    retrieve_fn 可注入假检索做离线测试；缺省走人格库+维基库合并检索。
    """
    if (config is None and retrieve_fn is None) or not entity:
        return None
    retrieve = retrieve_fn if callable(retrieve_fn) else _merged_grounding_retrieve(config)
    if not callable(retrieve):
        return None
    try:
        chunks = list(retrieve(entity) or [])
    except Exception:  # noqa: BLE001 - 检索故障按未命中处理，走外查/降级。
        return None
    chunk = select_kb_chunks(chunks, entity)
    if chunk is None:
        return None
    return _kb_grounding_from_chunk(chunk, entity, max_chars)


def resolve_grounding_for_entity(
    entity: str,
    *,
    config: Any | None = None,
    search_fn: Callable[..., list[MoegirlHit]] | None = None,
    page_fn: Callable[..., MoegirlHit | None] | None = None,
    retrieve_fn: Any | None = None,
) -> tuple[MoegirlGrounding | None, str]:
    """实体 → 接地块：本地命中优先，未命中外查萌百主词条；失败可判别。

    返回 (grounding, degrade_reason)；reason ∈ {"", "no_entry", "network_error",
    "ambiguous"}。任何路径都不产 URL、不自调 LLM（唯一出口判据的结构面）。
    """
    local = local_kb_grounding(config, entity, retrieve_fn=retrieve_fn)
    if local is not None:
        return local, ""
    api_bases = _configured_api_bases(config)
    timeout = float(getattr(config, "bot_moegirl_timeout_seconds", 5.0) or 5.0) if config is not None else 5.0
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config is not None else ""
    max_chars = int(getattr(config, "bot_moegirl_summary_max_chars", 300) or 300) if config is not None else 300

    search = search_fn or (
        lambda query, **kw: moegirl_search(
            query, api_bases=api_bases, timeout_seconds=timeout, proxy=proxy, **kw
        )
    )
    try:
        hits = search(entity)
    except ParseHttpError:
        return None, "network_error"
    except Exception:  # noqa: BLE001 - 查询层任何异常都按网络失败降级。
        return None, "network_error"
    if not hits:
        return None, "no_entry"
    main = pick_main_hit(hits, entity)
    if main is None:
        # 多候选/无精确命中：多半是普通闲聊被问句路由误捕（"QQ用户是谁"），
        # 词条选择列表对这类场景是骚扰——降级交聊天链路（既有语义保持）。
        return None, "ambiguous"
    page = main
    fetch_page = page_fn
    if fetch_page is None:
        fetch_page = lambda title, **kw: moegirl_page_summary(
            title, api_bases=api_bases, timeout_seconds=timeout, proxy=proxy, **kw
        )
    try:
        fetched = fetch_page(main.title)
        if fetched is not None:
            page = fetched
    except ParseHttpError:
        pass
    except Exception:  # noqa: BLE001, S110 - 摘要失败回退搜索自带摘要，不降级。
        pass
    snippet = _strip_urls(_clip(page.snippet or main.snippet or "", max_chars))
    if not snippet:
        return None, "no_entry"
    title = (page.title or main.title or entity).strip()
    return (
        MoegirlGrounding(
            text=snippet,
            label=f"萌娘百科·{title}",
            origin="moegirl",
            title=title,
        ),
        "",
    )


def question_lookup(
    text: str,
    *,
    config: Any | None = None,
    search_fn: Callable[..., list[MoegirlHit]] | None = None,
    page_fn: Callable[..., MoegirlHit | None] | None = None,
    local_retrieve: Any | None = None,
) -> MoegirlQuestionOutcome:
    """问句自动查询主流程：命中=接地块（由处理程序交聊天链一次生成）；失败=可判别降级。

    ``search_fn``/``page_fn``/``local_retrieve`` 可注入假实现做离线测试；
    零网络纪律不变（本件从不出网调用 LLM，萌百至多 1 搜索 + 1 摘要）。
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    entity = normalize_entity_question(text)
    if entity is None:
        return MoegirlQuestionOutcome(status="degrade", degrade_reason="not_entity", elapsed_ms=elapsed())
    grounding, reason = resolve_grounding_for_entity(
        entity,
        config=config,
        search_fn=search_fn,
        page_fn=page_fn,
        retrieve_fn=local_retrieve,
    )
    if grounding is not None:
        return MoegirlQuestionOutcome(
            status="hit", entity=entity, grounding=grounding, elapsed_ms=elapsed()
        )
    return MoegirlQuestionOutcome(
        status="degrade", entity=entity, degrade_reason=reason, elapsed_ms=elapsed()
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
    """`萌娘百科 <词条>`：本地接地优先 → 精确页摘要 → 搜索可信主词条 → 候选列表。

    2026-09-27 甲批：本执行体是命令面/中央调度 executor 的**兜底形态**——
    生产消息流里 `萌娘百科 <词条>` 与问句都先由根装配处理程序取接地并转交
    聊天链一次生成；走到这里的只剩无接地面（用法提示/候选列表/无条目/网络
    失败），以及不经 handler 的 executor 路径。所有输出统一走
    `format_main_result` / `format_grounding_result`：**无 URL、无 🔗，出处
    只留一行中文小字**。
    """
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
        # 本地知识库优先（方舟/原神等整套语料在库里，外网摘要只会更薄）。
        local = local_kb_grounding(config, query)
        if local is not None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                body=format_grounding_result(local),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["moegirl", "local_kb_grounding", f"moegirl_query:{query[:20]}"],
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
                # 审查 Q-01：数据源失败池轮换取句（原固定 U12 单句）。
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason="萌娘百科暂时连不上"
                ),
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
        if main.snippet:
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


def format_grounding_result(grounding: MoegirlGrounding, *, max_chars: int = 500) -> str:
    """接地块 → 人话条目（命令面/executor 兜底输出；聊天链路径不经过这里）。"""
    lines = [
        f"【{grounding.title}】",
        _strip_urls(_clip(grounding.text, max_chars)),
        f"出自：{grounding.label}",
    ]
    return "\n".join(line for line in lines if line)


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
