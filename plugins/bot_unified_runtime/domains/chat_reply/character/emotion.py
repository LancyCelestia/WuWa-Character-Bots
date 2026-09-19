from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from plugins.bot_unified_runtime.contracts import EmotionSignal, PrivacyLevel


class EmotionProvider(Protocol):
    def analyze(
        self,
        *,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
    ) -> list[EmotionSignal]:
        raise NotImplementedError


class NullEmotionProvider:
    def analyze(
        self,
        *,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
    ) -> list[EmotionSignal]:
        return []


@dataclass(frozen=True)
class _EmotionRule:
    label: str
    signal_kind: str
    keywords: tuple[str, ...]
    confidence: float
    guidance: str


class RuleBasedEmotionProvider:
    """Small deterministic classifier for tone hints, not user diagnosis."""

    def __init__(self, *, max_signals: int = 4) -> None:
        self.max_signals = max(0, max_signals)
        self._rules = (
            _EmotionRule(
                label="support_needed",
                signal_kind="support_need",
                keywords=(
                    "难受",
                    "低落",
                    "伤心",
                    "崩溃",
                    "想哭",
                    "痛苦",
                    "撑不住",
                    "陪我",
                    "安慰",
                    "焦虑",
                    "害怕",
                ),
                confidence=0.82,
                guidance="先承接感受，再给轻量可执行建议。",
            ),
            _EmotionRule(
                label="lonely",
                signal_kind="support_need",
                keywords=("孤独", "孤单", "没人陪", "一个人", "寂寞"),
                confidence=0.72,
                guidance="语气更陪伴，避免夸大承诺。",
            ),
            _EmotionRule(
                label="low_energy",
                signal_kind="energy",
                keywords=("累", "疲惫", "困", "没力气", "撑不动"),
                confidence=0.68,
                guidance="降低压迫感，优先短句和低负担建议。",
            ),
            _EmotionRule(
                label="frustrated",
                signal_kind="friction",
                keywords=("烦", "气死", "崩了", "不想搞了", "卡住了"),
                confidence=0.66,
                guidance="先减压，再拆解问题。",
            ),
            _EmotionRule(
                label="help_seeking",
                signal_kind="task_need",
                keywords=(
                    "一步一步",
                    "怎么",
                    "如何",
                    "教我",
                    "教程",
                    "排查",
                    "报错",
                    "配置",
                    "为什么",
                    "帮我看",
                ),
                confidence=0.7,
                guidance="用步骤化回答，必要时分层说明。",
            ),
        )

    def analyze(
        self,
        *,
        request_id: str,
        sender_id: str,
        session_id: str,
        query_text: str,
    ) -> list[EmotionSignal]:
        if self.max_signals <= 0:
            return []

        normalized = query_text.strip()
        if not normalized:
            return []

        signals: list[EmotionSignal] = []
        for rule in self._rules:
            evidence = _first_matching_keyword(normalized, rule.keywords)
            if evidence is None:
                continue
            signals.append(
                EmotionSignal(
                    request_id=request_id,
                    session_id=session_id,
                    speaker_id=sender_id,
                    source="rule_based",
                    signal_kind=rule.signal_kind,
                    emotion_label=rule.label,
                    confidence=rule.confidence,
                    evidence=evidence,
                    guidance=rule.guidance,
                    privacy_level=PrivacyLevel.PERSONAL,
                )
            )
            if len(signals) >= self.max_signals:
                break

        return signals


def build_emotion_provider(config: object) -> EmotionProvider:
    enabled = bool(getattr(config, "bot_emotion_enabled", True))
    if not enabled:
        return NullEmotionProvider()
    max_signals = int(getattr(config, "bot_emotion_max_signals", 4))
    return RuleBasedEmotionProvider(max_signals=max_signals)


def _first_matching_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword
    return None
