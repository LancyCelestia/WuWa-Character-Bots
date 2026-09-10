from __future__ import annotations

import hashlib
import logging
import random
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts.character import (
    ContextBundle,
    ConversationHistoryResult,
    KnowledgeChunk,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)

from .affinity import AFFINITY_BASE, DynamicAffinityStore, tier_for_affinity
from .documents import load_character_document
from .emotion import EmotionProvider, NullEmotionProvider, build_emotion_provider
from .glossary import GlossaryProvider, NullGlossaryProvider, build_glossary_provider
from .history import (
    ConversationHistoryProvider,
    NullConversationHistoryProvider,
    build_conversation_history_provider,
)
from .memory import MemoryProvider, NullMemoryProvider, build_memory_provider
from .persona_set import PersonaSelector, build_alt_personas
from .relationship import (
    NullRelationshipProvider,
    RelationshipProvider,
    apply_relationship_to_tone,
    build_relationship_provider,
)
from .shared_group import (
    NullSharedGroupContextProvider,
    SharedGroupContextProvider,
    build_shared_group_context_provider,
)
from .temporal import RuleBasedTemporalProvider, build_temporal_provider
from .trend import NullTrendProvider, TrendProvider, build_trend_provider
from .vector_knowledge import (
    build_keyword_knowledge_provider,
    build_vector_knowledge_provider,
)

LLM_SAFE_MEMORY_SENSITIVITIES = frozenset({"public", "group", "personal"})


class CharacterContextProvider(Protocol):
    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
        platform: str = "unknown",
        adapter: str = "unknown",
        bot_id: str = "unknown",
        group_id: str = "",
    ) -> ContextBundle:
        raise NotImplementedError


class NullCharacterContextProvider:
    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
        platform: str = "unknown",
        adapter: str = "unknown",
        bot_id: str = "unknown",
        group_id: str = "",
    ) -> ContextBundle:
        persona = PersonaProfile(
            profile_id="default",
            version="0",
            display_name="报存",
            identity="统一运行时默认人格",
            role_boundaries=["不直接发送插件效果", "不绕过审计"],
        )
        tone = ToneProfile(profile_id="default", mode="private_chat")
        return ContextBundle(
            request_id=request_id,
            persona=persona,
            tone=tone,
            memory_results=MemoryRetrievalResult(request_id=request_id),
            conversation_history=ConversationHistoryResult(request_id=request_id),
            knowledge_results=RetrievalResult(request_id=request_id),
            current_message=query_text,
            sender_id=sender_id,
            session_id=session_id,
        )


class FileCharacterContextProvider:
    def __init__(
        self,
        *,
        persona_profile_id: str,
        persona_display_name: str,
        persona_version: str,
        persona_files: list[str | Path],
        knowledge_files: list[str | Path],
        knowledge_max_chunks: int = 4,
        knowledge_chunk_chars: int = 900,
        vector_retriever: Callable[[str], list[KnowledgeChunk]] | None = None,
        tone_mode: str = "private_chat",
        tone_voice: str = "soft",
        tone_warmth: float = 0.7,
        tone_directness: float = 0.5,
        tone_message_count_limit: int = 0,
        memory_provider: MemoryProvider | None = None,
        memory_max_items: int = 5,
        memory_max_chars: int = 1200,
        conversation_history_provider: ConversationHistoryProvider | None = None,
        history_max_turns: int = 6,
        history_max_chars: int = 1600,
        emotion_provider: EmotionProvider | None = None,
        trend_provider: TrendProvider | None = None,
        temporal_provider: RuleBasedTemporalProvider | None = None,
        glossary_provider: GlossaryProvider | None = None,
        relationship_provider: RelationshipProvider | None = None,
        affinity_store: DynamicAffinityStore | None = None,
        shared_group_provider: SharedGroupContextProvider | None = None,
        action_brackets: bool = True,
        action_brackets_provider: object | None = None,
        persona_selector: PersonaSelector | None = None,
        persona_override_provider: object | None = None,
        persona_weights_provider: object | None = None,
        persona_rng: random.Random | None = None,
    ) -> None:
        self.persona_profile_id = persona_profile_id
        self.persona_display_name = persona_display_name
        self.persona_version = persona_version
        self.persona_files = [Path(path).expanduser() for path in persona_files]
        self.knowledge_files = [Path(path).expanduser() for path in knowledge_files]
        self._persona_text_cache: dict[Path, tuple[int, int, str]] = {}
        self.knowledge_max_chunks = max(0, knowledge_max_chunks)
        self.knowledge_chunk_chars = max(120, knowledge_chunk_chars)
        self.vector_retriever = vector_retriever
        self.tone_mode = tone_mode
        self.tone_voice = tone_voice
        self.tone_warmth = tone_warmth
        self.tone_directness = tone_directness
        self.tone_message_count_limit = max(0, tone_message_count_limit)  # 0 = 不限制
        self.memory_provider = memory_provider or NullMemoryProvider()
        self.memory_max_items = max(0, memory_max_items)
        self.memory_max_chars = max(0, memory_max_chars)
        self.conversation_history_provider = (
            conversation_history_provider or NullConversationHistoryProvider()
        )
        self.history_max_turns = max(0, history_max_turns)
        self.history_max_chars = max(0, history_max_chars)
        self.emotion_provider = emotion_provider or NullEmotionProvider()
        self.trend_provider = trend_provider or NullTrendProvider()
        self.temporal_provider = temporal_provider or RuleBasedTemporalProvider()
        self.glossary_provider = glossary_provider or NullGlossaryProvider()
        self.relationship_provider = relationship_provider or NullRelationshipProvider()
        self.affinity_store: DynamicAffinityStore | None = affinity_store
        self.shared_group_provider = (
            shared_group_provider or NullSharedGroupContextProvider()
        )
        self.action_brackets = bool(action_brackets)
        self.action_brackets_provider = action_brackets_provider
        self.persona_selector = persona_selector or PersonaSelector({})
        self.persona_override_provider = persona_override_provider
        self.persona_weights_provider = persona_weights_provider
        self.persona_rng = persona_rng

    def _persona_override(self) -> str:
        if callable(self.persona_override_provider):
            try:
                return str(self.persona_override_provider()).strip()
            except Exception:  # noqa: BLE001 - 运行时提供者失败时回退为空字符串，不影响人格构建。
                return ""
        return ""

    def _persona_weights(self) -> dict[str, float]:
        if callable(self.persona_weights_provider):
            try:
                resolved = self.persona_weights_provider()
                if isinstance(resolved, dict):
                    return {
                        str(key): float(value)
                        for key, value in resolved.items()
                    }
            except Exception:  # noqa: BLE001 - 权重提供者失败时回退为空字典。
                return {}
        return {}

    def _load_persona_text(self, paths: list[Path]) -> str:
        chunks: list[str] = []
        for path in paths:
            try:
                stat = path.stat()
                signature = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                signature = (0, 0)
            cached = self._persona_text_cache.get(path)
            if cached is not None and cached[:2] == signature:
                chunks.append(cached[2])
                continue
            text = load_character_document(path)
            self._persona_text_cache[path] = (*signature, text)
            chunks.append(text)
        return "\n".join(chunks)

    def _action_brackets_enabled(self) -> bool:
        if callable(self.action_brackets_provider):
            try:
                return bool(self.action_brackets_provider())
            except Exception:  # noqa: BLE001 - 动作括号开关提供者失败时回退默认值。
                return self.action_brackets
        return self.action_brackets

    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
        platform: str = "unknown",
        adapter: str = "unknown",
        bot_id: str = "unknown",
        group_id: str = "",
    ) -> ContextBundle:
        emotion_signals = self.emotion_provider.analyze(
            request_id=request_id,
            sender_id=sender_id,
            session_id=session_id,
            query_text=query_text,
        )
        active_persona = self.persona_selector.select(
            emotions=[signal.emotion_label for signal in emotion_signals],
            override=self._persona_override(),
            weights=self._persona_weights(),
            rng=self.persona_rng,
        )
        if active_persona is not None:
            persona_profile_id = active_persona.profile_id
            persona_display_name = active_persona.display_name
            persona_files = [Path(path).expanduser() for path in active_persona.files]
        else:
            persona_profile_id = self.persona_profile_id
            persona_display_name = self.persona_display_name
            persona_files = self.persona_files
        persona_text = self._load_persona_text(persona_files)
        persona = _build_persona_profile(
            profile_id=persona_profile_id,
            version=self.persona_version,
            display_name=persona_display_name,
            persona_text=persona_text,
        )
        relationship = self.relationship_provider.load(
            request_id=request_id,
            sender_id=sender_id,
        )
        # 动态好感度融合（批次 C / v3）：行为驱动层有记录时覆盖 affinity/attitude，
        # 并把档位映射到 familiarity，使语气数值参数（warmth/directness）跟随动态档位；
        # 档案的其他字段（称呼/偏好/备注）保留。
        if self.affinity_store is not None and sender_id:
            dynamic = self.affinity_store.snapshot(sender_id)
            if dynamic.get("affinity") is not None and (dynamic["affinity"] != AFFINITY_BASE or dynamic.get("tags")):
                tags_text = "、".join(str(t) for t in dynamic.get("tags") or [])
                notes_text = "；".join(str(n) for n in dynamic.get("profile_notes") or [])
                nickname_text = str(dynamic.get("nickname") or "")
                attitude = str(dynamic.get("attitude") or "")
                if tags_text:
                    attitude += f"（印象参考：{tags_text}；只影响语气，不外显为标签）"
                if notes_text:
                    attitude += f"（已知画像：{notes_text}；可在对话中自然体现，不逐条复述）"
                if nickname_text:
                    attitude += f"（对方的小名：{nickname_text}；可用它称呼对方）"
                tier = tier_for_affinity(float(dynamic["affinity"]))
                familiarity = {"close": "close", "friendly": "familiar"}.get(tier, "stranger")
                relationship = relationship.model_copy(
                    update={
                        "affinity": float(dynamic["affinity"]),
                        "attitude": attitude,
                        "familiarity": familiarity,
                    }
                )
        tone_warmth, tone_directness = apply_relationship_to_tone(
            self.tone_warmth,
            self.tone_directness,
            relationship,
        )
        tone = ToneProfile(
            profile_id=persona_profile_id,
            mode=self.tone_mode,
            voice=self.tone_voice,
            warmth=tone_warmth,
            directness=tone_directness,
            message_count_limit=self.tone_message_count_limit,
            action_brackets=self._action_brackets_enabled(),
        )
        knowledge_chunks: list[KnowledgeChunk] = []
        retrieval_failed = False
        if self.vector_retriever is not None:
            try:
                knowledge_chunks = list(self.vector_retriever(query_text) or [])
            except Exception as exc:  # noqa: BLE001 - 检索服务故障不阻断上下文构建。
                retrieval_failed = True
                knowledge_chunks = []
                logging.getLogger(__name__).warning(
                    "vector knowledge retrieval degraded (service failure), "
                    "skipping static fallback: type=%s",
                    type(exc).__name__,
                )
        if not knowledge_chunks and not retrieval_failed:
            # 正常无命中：保留静态文件块兜底。服务故障（retrieval_failed）
            # 不再注入整文件前几块——静态注入既掩盖故障又污染 prompt。
            knowledge_chunks = _build_knowledge_chunks(
                files=self.knowledge_files,
                max_chunks=self.knowledge_max_chunks,
                chunk_chars=self.knowledge_chunk_chars,
            )
        memory_results = _filter_llm_safe_memory_results(
            self.memory_provider.retrieve(
                request_id=request_id,
                requester_id=sender_id,
                subject_user_id=sender_id,
                session_id=session_id,
                query_text=query_text,
                max_items=self.memory_max_items,
                max_chars=self.memory_max_chars,
            )
        )
        conversation_history = self.conversation_history_provider.retrieve(
            request_id=request_id,
            platform=platform,
            adapter=adapter,
            bot_id=bot_id,
            session_id=session_id,
            sender_id=sender_id,
            max_turns=self.history_max_turns,
            max_chars=self.history_max_chars,
        )
        trend_context = self.trend_provider.load(request_id=request_id)
        temporal_context = self.temporal_provider.snapshot(request_id=request_id)
        glossary_context = self.glossary_provider.load(request_id=request_id)
        shared_group_context = self.shared_group_provider.load(
            request_id=request_id,
            group_id=group_id,
            sender_id=sender_id,
        )
        return ContextBundle(
            request_id=request_id,
            persona=persona,
            tone=tone,
            memory_results=memory_results,
            conversation_history=conversation_history,
            knowledge_results=RetrievalResult(
                request_id=request_id,
                chunks=knowledge_chunks,
                answerable=bool(knowledge_chunks),
                confidence=0.8 if knowledge_chunks else 0.0,
            ),
            current_message=query_text,
            sender_id=sender_id,
            session_id=session_id,
            emotion_signals=emotion_signals,
            trend_context=trend_context,
            temporal_context=temporal_context,
            glossary_context=glossary_context,
            relationship_context=relationship,
            shared_group_context=shared_group_context,
            active_persona_id=persona_profile_id,
        )


def build_character_context_provider(
    config: object,
    *,
    conversation_history_provider: ConversationHistoryProvider | None = None,
    runtime_settings: Any | None = None,
    shared_group_llm_provider: object | None = None,
) -> CharacterContextProvider:
    action_brackets_provider: object | None = None
    interaction_counts_provider: Callable[[], dict[str, int]] | None = None
    persona_override_provider: object | None = None
    persona_weights_provider: object | None = None
    if runtime_settings is not None:
        def _runtime_action_brackets() -> bool:
            return bool(
                runtime_settings.get_or(
                    "BOT_PERSONA_ACTION_BRACKETS",
                    bool(getattr(config, "bot_persona_action_brackets", True)),
                )
            )

        def _interaction_counts() -> dict[str, int]:
            try:
                senders = runtime_settings.list_interaction_senders()
                get_count = runtime_settings.interaction_count
                return {
                    str(sender_id): int(get_count(str(sender_id)))
                    for sender_id in senders
                }
            except Exception:  # noqa: BLE001 - 交互计数读取失败时回退空字典。
                return {}

        def _persona_override() -> str:
            try:
                return str(runtime_settings.get_persona_override())
            except Exception:  # noqa: BLE001 - 运行时人格覆盖读取失败时回退为空字符串。
                return ""

        def _persona_weights() -> dict[str, float]:
            try:
                return dict(runtime_settings.get_persona_weights())
            except Exception:  # noqa: BLE001 - 运行时权重读取失败时回退为空字典。
                return {}

        action_brackets_provider = _runtime_action_brackets
        interaction_counts_provider = _interaction_counts
        persona_override_provider = _persona_override
        persona_weights_provider = _persona_weights
    fast_mode = bool(getattr(config, "bot_chat_fast_mode", True))
    skip_vector = bool(getattr(config, "bot_chat_fast_disable_vector_knowledge", True))
    vector_provider: Any = (
        build_vector_knowledge_provider(
            config,
            timeout_override=(
                float(getattr(config, "bot_chat_fast_embedding_timeout_seconds", 3.0) or 3.0)
                if fast_mode
                else None
            ),
        )
        if not (fast_mode and skip_vector)
        else type("UnavailableVectorProvider", (), {"available": False})()
    )
    knowledge_retriever: Any = (
        build_keyword_knowledge_provider(config)
        if fast_mode and skip_vector
        else (vector_provider if vector_provider.available else build_keyword_knowledge_provider(config))
    )
    # Crawl Wiki 知识库（RAG）：与人格知识库独立向量库，检索结果轮询交错
    # 合并（人格知识块排前）。fast 模式禁用向量知识时同样跳过（wiki 库
    # 依赖嵌入查询）；同样施加 fast 嵌入超时上限，防 Ollama 卡死拖垮请求。
    if not (fast_mode and skip_vector):
        try:
            from .kb_wiki import MergedKnowledgeRetriever, build_kb_wiki_retriever

            kb_retriever = build_kb_wiki_retriever(
                config,
                timeout_override=(
                    float(
                        getattr(config, "bot_chat_fast_embedding_timeout_seconds", 3.0)
                        or 3.0
                    )
                    if fast_mode
                    else None
                ),
            )
        except Exception:  # noqa: BLE001 - wiki 库构建失败不阻断人格知识检索。
            kb_retriever = None
        if kb_retriever is not None and getattr(kb_retriever, "available", False):
            knowledge_retriever = (
                MergedKnowledgeRetriever([knowledge_retriever, kb_retriever])
                if getattr(knowledge_retriever, "available", False)
                else kb_retriever
            )
    return FileCharacterContextProvider(
        persona_profile_id=str(getattr(config, "bot_persona_profile_id", "default")),
        persona_display_name=str(getattr(config, "bot_persona_display_name", "报存")),
        persona_version=str(getattr(config, "bot_persona_version", "0")),
        persona_files=list(getattr(config, "bot_persona_files", [])),
        knowledge_files=list(getattr(config, "bot_knowledge_files", [])),
        knowledge_max_chunks=int(getattr(config, "bot_knowledge_max_chunks", 4)),
        knowledge_chunk_chars=int(getattr(config, "bot_knowledge_chunk_chars", 900)),
        vector_retriever=knowledge_retriever.retrieve if knowledge_retriever.available else None,
        tone_mode=str(getattr(config, "bot_tone_mode", "private_chat")),
        tone_voice=str(getattr(config, "bot_tone_voice", "soft")),
        tone_warmth=float(getattr(config, "bot_tone_warmth", 0.7)),
        tone_directness=float(getattr(config, "bot_tone_directness", 0.5)),
        tone_message_count_limit=int(getattr(config, "bot_tone_message_count_limit", 0)),
        memory_provider=build_memory_provider(config),
        memory_max_items=int(getattr(config, "bot_memory_max_items", 5)),
        memory_max_chars=int(getattr(config, "bot_memory_max_chars", 1200)),
        conversation_history_provider=(
            conversation_history_provider
            or build_conversation_history_provider(config)
        ),
        history_max_turns=int(getattr(config, "bot_history_max_turns", 6)),
        history_max_chars=int(getattr(config, "bot_history_max_chars", 1600)),
        emotion_provider=build_emotion_provider(config),
        trend_provider=build_trend_provider(config),
        temporal_provider=build_temporal_provider(config),
        glossary_provider=build_glossary_provider(config),
        relationship_provider=build_relationship_provider(
            config,
            interaction_counts=interaction_counts_provider,
        ),
        affinity_store=(
            _shared_affinity_store(config)
            if getattr(config, "bot_affinity_enabled", True)
            else None
        ),
        shared_group_provider=build_shared_group_context_provider(
            config,
            llm_provider=shared_group_llm_provider,
        ),
        action_brackets=bool(getattr(config, "bot_persona_action_brackets", True)),
        action_brackets_provider=action_brackets_provider,
        persona_selector=PersonaSelector(build_alt_personas(config)),
        persona_override_provider=persona_override_provider,
        persona_weights_provider=persona_weights_provider,
    )


def _filter_llm_safe_memory_results(
    result: MemoryRetrievalResult,
) -> MemoryRetrievalResult:
    safe_facts = [
        fact
        for fact in result.facts
        if fact.get("sensitivity", "personal") in LLM_SAFE_MEMORY_SENSITIVITIES
    ]
    if len(safe_facts) == len(result.facts):
        return result
    return MemoryRetrievalResult(
        request_id=result.request_id,
        facts=safe_facts,
        raw_message_refs=result.raw_message_refs,
        confidence=result.confidence,
        privacy_level=result.privacy_level,
    )


def _build_persona_profile(
    *,
    profile_id: str,
    version: str,
    display_name: str,
    persona_text: str,
) -> PersonaProfile:
    lines = _meaningful_lines(persona_text)
    identity = next(
        (_clean_line(line) for line in lines if not line.startswith("#")),
        "统一运行时默认人格",
    )
    style_rules = [
        _clean_line(line)
        for line in lines
        if _contains_any(line, ("语气", "风格", "说话", "回复", "表达", "陪伴感"))
    ]
    role_boundaries = [
        _clean_line(line)
        for line in lines
        if _contains_any(line, ("边界", "权限", "审计", "发送", "插件", "不能", "不要"))
    ]
    forbidden_behaviors = [
        _clean_line(line)
        for line in lines
        if _contains_any(line, ("禁止", "不要", "不能", "泄露", "系统提示", "忽略", "越权", "脚本"))
    ]
    return PersonaProfile(
        profile_id=profile_id,
        version=version,
        display_name=display_name,
        identity=identity,
        role_boundaries=_dedupe_preserve_order(role_boundaries),
        style_rules=_dedupe_preserve_order(style_rules),
        forbidden_behaviors=_dedupe_preserve_order(forbidden_behaviors),
        raw_text=persona_text,
    )


# 静态知识文件文本签名缓存（管线检视 #9）：向量检索未命中是闲聊常态，
# 每条消息都会走 _build_knowledge_chunks 兜底，无签名缓存时每次都要对全部
# 知识文件重读盘+解析。(mtime,size) 未变直接复用文本；签名语义与人格文件
# 缓存（_load_persona_text）及 vector_knowledge._file_signature 一致。
_KNOWLEDGE_TEXT_CACHE: dict[Path, tuple[tuple[int, int], str]] = {}
_KNOWLEDGE_TEXT_CACHE_LOCK = threading.Lock()


def _load_knowledge_text(path: Path) -> str:
    """带 (mtime,size) 签名缓存的知识文件读取：未变复用，变了才重读重解析。"""
    try:
        stat = path.stat()
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        signature = (0, 0)
    with _KNOWLEDGE_TEXT_CACHE_LOCK:
        cached = _KNOWLEDGE_TEXT_CACHE.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        text = load_character_document(path)
        _KNOWLEDGE_TEXT_CACHE[path] = (signature, text)
        return text


def _build_knowledge_chunks(
    *,
    files: list[Path],
    max_chunks: int,
    chunk_chars: int,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for path in files:
        if len(chunks) >= max_chunks:
            break
        try:
            text = _load_knowledge_text(path)
        except (OSError, ValueError):
            # 单个知识文件缺失/不可读时跳过，不让它打断整个静态兜底链
            #（此前 FileNotFoundError 会令 build_context 直接失败）。
            continue
        for index, content in enumerate(_chunk_text(text, chunk_chars=chunk_chars), start=1):
            if len(chunks) >= max_chunks:
                break
            source_id = path.stem
            digest = hashlib.sha1(
                f"{path.as_posix()}:{index}:{content}".encode()
            ).hexdigest()[:12]
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{source_id}:{digest}",
                    source_id=source_id,
                    title=path.stem,
                    content=content,
                )
            )
    return chunks


def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        next_value = paragraph if not current else f"{current}\n{paragraph}"
        if len(next_value) <= chunk_chars:
            current = next_value
            continue
        if current:
            chunks.append(current)
        current = paragraph[:chunk_chars]
        while len(paragraph) > chunk_chars:
            paragraph = paragraph[chunk_chars:]
            chunks.append(current)
            current = paragraph[:chunk_chars]
    if current:
        chunks.append(current)
    return chunks


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _clean_line(value: str) -> str:
    return value.lstrip("#").lstrip("-*").strip()


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def build_runtime_data_path(config: object, value: str) -> Path:
    """data/... → 配置的 Runtime 数据根（复用 runtime_paths 规则）。"""
    import sys

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from scripts.runtime_paths import runtime_path

    return runtime_path(value)


def _shared_affinity_store(config: object) -> Any | None:
    """复用进程级共享好感度 store 单例（``__init__.build_character_affinity_store``）。

    此前这里直接 ``DynamicAffinityStore(...)`` 自建实例：与共享工厂各持一把锁、
    各开一条连接，每条聊天消息的被动感知与人格上下文构建互相争锁。
    延迟导入避免模块级循环依赖；工厂不可用时退回本地实例保持可用性。
    """
    try:
        from plugins.bot_unified_runtime import build_character_affinity_store

        return build_character_affinity_store(config)
    except Exception:  # noqa: BLE001 - 共享工厂失败时退回独立实例，不阻断上下文构建。
        return DynamicAffinityStore(
            build_runtime_data_path(
                config,
                str(getattr(config, "bot_affinity_db_path", "data/user_affinity.sqlite3")),
            )
        )
