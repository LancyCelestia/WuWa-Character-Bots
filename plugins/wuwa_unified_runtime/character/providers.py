from __future__ import annotations

from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import (
    ContextBundle,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)


class CharacterContextProvider(Protocol):
    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
    ) -> ContextBundle:
        raise NotImplementedError


class NullCharacterContextProvider:
    def build_context(
        self,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
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
            knowledge_results=RetrievalResult(request_id=request_id),
            current_message=query_text,
            sender_id=sender_id,
            session_id=session_id,
        )
