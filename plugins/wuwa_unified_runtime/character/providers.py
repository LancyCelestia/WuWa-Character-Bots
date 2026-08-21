from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import (
    ContextBundle,
    ConversationHistoryResult,
    KnowledgeChunk,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)

from .documents import load_character_document
from .emotion import EmotionProvider, NullEmotionProvider, build_emotion_provider
from .history import (
    ConversationHistoryProvider,
    NullConversationHistoryProvider,
    build_conversation_history_provider,
)
from .memory import MemoryProvider, NullMemoryProvider, build_memory_provider
from .temporal import RuleBasedTemporalProvider, build_temporal_provider
from .trend import NullTrendProvider, TrendProvider, build_trend_provider


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
        tone_mode: str = "private_chat",
        tone_voice: str = "soft",
        tone_warmth: float = 0.7,
        tone_directness: float = 0.5,
        tone_message_count_limit: int = 1,
        memory_provider: MemoryProvider | None = None,
        memory_max_items: int = 5,
        memory_max_chars: int = 1200,
        conversation_history_provider: ConversationHistoryProvider | None = None,
        history_max_turns: int = 6,
        history_max_chars: int = 1600,
        emotion_provider: EmotionProvider | None = None,
        trend_provider: TrendProvider | None = None,
        temporal_provider: RuleBasedTemporalProvider | None = None,
        action_brackets: bool = True,
    ) -> None:
        self.persona_profile_id = persona_profile_id
        self.persona_display_name = persona_display_name
        self.persona_version = persona_version
        self.persona_files = [Path(path).expanduser() for path in persona_files]
        self.knowledge_files = [Path(path).expanduser() for path in knowledge_files]
        self.knowledge_max_chunks = max(0, knowledge_max_chunks)
        self.knowledge_chunk_chars = max(120, knowledge_chunk_chars)
        self.tone_mode = tone_mode
        self.tone_voice = tone_voice
        self.tone_warmth = tone_warmth
        self.tone_directness = tone_directness
        self.tone_message_count_limit = max(1, tone_message_count_limit)
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
        self.action_brackets = bool(action_brackets)

    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
        platform: str = "unknown",
        adapter: str = "unknown",
        bot_id: str = "unknown",
    ) -> ContextBundle:
        persona_text = "\n".join(load_character_document(path) for path in self.persona_files)
        persona = _build_persona_profile(
            profile_id=self.persona_profile_id,
            version=self.persona_version,
            display_name=self.persona_display_name,
            persona_text=persona_text,
        )
        tone = ToneProfile(
            profile_id=self.persona_profile_id,
            mode=self.tone_mode,
            voice=self.tone_voice,
            warmth=self.tone_warmth,
            directness=self.tone_directness,
            message_count_limit=self.tone_message_count_limit,
            action_brackets=self.action_brackets,
        )
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
        emotion_signals = self.emotion_provider.analyze(
            request_id=request_id,
            sender_id=sender_id,
            session_id=session_id,
            query_text=query_text,
        )
        trend_context = self.trend_provider.load(request_id=request_id)
        temporal_context = self.temporal_provider.snapshot(request_id=request_id)
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
        )


def build_character_context_provider(
    config: object,
    *,
    conversation_history_provider: ConversationHistoryProvider | None = None,
) -> CharacterContextProvider:
    return FileCharacterContextProvider(
        persona_profile_id=str(getattr(config, "wuwa_persona_profile_id", "default")),
        persona_display_name=str(getattr(config, "wuwa_persona_display_name", "报存")),
        persona_version=str(getattr(config, "wuwa_persona_version", "0")),
        persona_files=list(getattr(config, "wuwa_persona_files", [])),
        knowledge_files=list(getattr(config, "wuwa_knowledge_files", [])),
        knowledge_max_chunks=int(getattr(config, "wuwa_knowledge_max_chunks", 4)),
        knowledge_chunk_chars=int(getattr(config, "wuwa_knowledge_chunk_chars", 900)),
        tone_mode=str(getattr(config, "wuwa_tone_mode", "private_chat")),
        tone_voice=str(getattr(config, "wuwa_tone_voice", "soft")),
        tone_warmth=float(getattr(config, "wuwa_tone_warmth", 0.7)),
        tone_directness=float(getattr(config, "wuwa_tone_directness", 0.5)),
        tone_message_count_limit=int(getattr(config, "wuwa_tone_message_count_limit", 1)),
        memory_provider=build_memory_provider(config),
        memory_max_items=int(getattr(config, "wuwa_memory_max_items", 5)),
        memory_max_chars=int(getattr(config, "wuwa_memory_max_chars", 1200)),
        conversation_history_provider=(
            conversation_history_provider
            or build_conversation_history_provider(config)
        ),
        history_max_turns=int(getattr(config, "wuwa_history_max_turns", 6)),
        history_max_chars=int(getattr(config, "wuwa_history_max_chars", 1600)),
        emotion_provider=build_emotion_provider(config),
        trend_provider=build_trend_provider(config),
        temporal_provider=build_temporal_provider(config),
        action_brackets=bool(getattr(config, "wuwa_persona_action_brackets", True)),
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
    )


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
        text = load_character_document(path)
        for index, content in enumerate(_chunk_text(text, chunk_chars=chunk_chars), start=1):
            if len(chunks) >= max_chunks:
                break
            source_id = path.stem
            digest = hashlib.sha1(
                f"{path.as_posix()}:{index}:{content}".encode("utf-8")
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
