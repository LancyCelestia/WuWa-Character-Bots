from __future__ import annotations

import hashlib
import logging
import random
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
    build_addressing_context,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
    linear_transition_for_affinity,
    tier_for_affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.documents import (
    load_character_document,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.emotion import (
    EmotionProvider,
    NullEmotionProvider,
    build_emotion_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.glossary import (
    GlossaryProvider,
    NullGlossaryProvider,
    build_glossary_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
    ConversationHistoryProvider,
    NullConversationHistoryProvider,
    build_conversation_history_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    MemoryProvider,
    NullMemoryProvider,
    build_memory_read_path,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    DEGRADED_REASON_BUS_RECALL_FAILED,
    DEGRADED_REASON_LEGACY_NEWEST_N,
    DEGRADED_REASON_MEMORY_LEG_FAILED,
    PROVENANCE_REFLECTED,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_service import (
    MemoryKind,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRegistry,
    build_effective_alt_personas,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_set import (
    AltPersonaSpec,
    PersonaSelector,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.relationship import (
    NullRelationshipProvider,
    RelationshipProvider,
    apply_relationship_to_tone,
    build_relationship_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.shared_group import (
    NullSharedGroupContextProvider,
    SharedGroupContextProvider,
    build_shared_group_context_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.temporal import (
    RuleBasedTemporalProvider,
    build_temporal_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.trend import (
    NullTrendProvider,
    TrendProvider,
    build_trend_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    build_keyword_knowledge_provider,
    build_vector_knowledge_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    classify_question_intent,
    knowledge_confidence_from_evidence,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
)
from plugins.bot_unified_runtime.domains.core.contracts.character import (
    ContextBundle,
    ConversationHistoryResult,
    KnowledgeChunk,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.core.search.entity_relations import (
    reality_relation_lines,
    registered_entity_hit,
    relation_query_admissible,
)

# V21-PERSONA-001：模块级 logger（版本库注入溯源/降级告警面；与 character 兄弟模块同惯例）。
logger = logging.getLogger(__name__)

#: 实体命中查不到时**才**退回的问句类别（席 S19 改序，2026-10-03）：
#: 放行判据的第一道是「册里有这个名字」（``registered_entity_hit``），分类器不再是唯一门票——
#: 「明日方舟是谁开发的」这类无「哪个/什么公司」字样的问句，HEAD 轴 ``never`` 且不端关系块。
#: 分类器的既有作用原样保留：① 它仍管联网与别的分区（本函数之外零扰动）；
#: ② 册里查不到名字时，仍是它决定给不给查（第二道门一字未改）。
#: 登记表本身＝``classify_question_intent`` 的既有分类，不新造判据（真身住
#: ``runtime/question_intent.py``；二游语境落 ``LOCAL_KNOWLEDGE``，故不另立第二把尺）。
_REALITY_LOOKUP_CATEGORIES: frozenset[str] = frozenset(
    {
        "EXTERNAL_ENTITY",
        "CURRENT_REAL_WORLD",
        "LOCAL_KNOWLEDGE",
        "GENERAL_STATIC_KNOWLEDGE",
    }
)


def reality_relation_note_for(query_text: str) -> str:
    """实体关系册 → 对话分区【现实关系】正文（把"在盘不在码"那格接上，台账 #72★同型）。

    顺序（席 S19）：**实体命中在前**——``registered_entity_hit`` 为真就直接查一跳，
    不再先看分类器；查不到名字才退回分类器那道门（既有语义一字未改）。
    两道门之后还共过一把撞名尺 ``relation_query_admissible``：短拉丁别名（CD/CP/CQ/BW）、
    人格名（``kind == character``）、册里标未核的实体，单凭整词命中不放行，
    要「整句即该实体」或「与域词共现」——这是把幻觉从另一侧挡在门外的判据，
    拿「这个CD盘多少钱」「守岸人你喜欢什么」现算即落在门外。
    取名/取边/措辞＝``entity_relations.reality_relation_lines``（唯一真身）。
    本函数零判据（除上面两把尺）、零文案、**零联网零写盘**。
    两道门任一没命中 ⇒ 空串 ⇒ chat.py 侧整块不渲染（空分区不渲染）。
    任何异常 ⇒ 空串并留一行 warn：这条链路的红线是"不确定的别端出去"，
    少一块事实不叫事故，把待核说成已核才叫。
    """
    text = str(query_text or "").strip()
    if not text:
        return ""
    try:
        if not relation_query_admissible(text):
            return ""
        if not registered_entity_hit(text) and (
            classify_question_intent(text).category not in _REALITY_LOOKUP_CATEGORIES
        ):
            return ""
        return "\n".join(reality_relation_lines(text))
    except Exception:  # 现实关系块缺席即可，绝不带崩主链路（本仓未启用 BLE001，故不写 noqa）
        logger.warning("实体关系册现算失败，本轮【现实关系】分区缺席", exc_info=True)
        return ""

LLM_SAFE_MEMORY_SENSITIVITIES = frozenset({"public", "group", "personal"})

# ---- 需求11 · 记忆类型标签渲染层（S-T-MEM-3）----
# 类型词表真身 = memory_service.MemoryKind（存储层封闭枚举）。本层只提供
# 「枚举成员 → 中文显示名」的展示映射：dict 键型注解使幽灵键（枚举里不存在
# 的字符串）在类型层写不进来，词表增删永远以枚举为准，不构成第二真身。
# 枚举扩充而此表未登记显示名时，该值按「原样点名」降级（见
# _memory_kind_label），不编造中文标签；「昵称/身份/性格」类细分依赖写腿
# （S-T-MEM-1）把细分类型升格进 MemoryKind，此层随后补一行显示名即可。
_MEMORY_KIND_DISPLAY_ZH: dict[MemoryKind, str] = {
    MemoryKind.PREFERENCE: "爱好与偏好",
    MemoryKind.FACT: "事实信息",
    MemoryKind.EVENT: "近期动态",
    MemoryKind.REFLECTION: "回顾归纳",
    MemoryKind.PROPOSAL: "待确认提案",
}

# 「原样点名」只接受短英文标识形态：kind 值来自写侧自由文本（LLM 抽取的
# category 也可能落这里），渲染层不假定它干净——形状不符一律按缺失处理、
# 不打标签，杜绝任意字符串进标签位（注入面收口）。
_RAW_MEMORY_KIND_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{1,24}")

# 截断哨兵/回执共用的特殊 fact_id（非模型可见行；渲染层统一换算成一行回执）。
MEMORY_TRUNCATION_FACT_ID = "memory_render_truncation"
_MEMORY_TRUNCATION_TEMPLATE_ZH = "另有 {count} 条未列出"
# 回执自身占字：按最大形态「另有 9999 条未列出」预留，计数增长不击穿预算。
_MEMORY_TRUNCATION_RESERVE_CHARS = len(_MEMORY_TRUNCATION_TEMPLATE_ZH.format(count="9999"))

# docs/affinity-design.md §5 人格自守条款：追加在档位态度文本之后（独立一句，
# 任何档位生效）；触发形态见 §6 软类别 persona_degradation（贬低不改变扣分路径）。
_PERSONA_SELF_GUARD_CLAUSE = (
    "（人格自守：若被以“猪狗不如”“垃圾”“废物”等贬低人格，温和地守住自己、"
    "轻声表明立场，然后照常回应对方话语里正当的部分。）"
)


def _sanitize_profile_notes_text(text: object) -> str:
    """【已知画像】备注进 prompt 前的唯一读侧出点（PROVIDERS-R2 票②，2026-09-28）。

    备注是写侧自由文本（`learn_profile`/`extract_profile_facts` 抽出来的原话），
    `coerce_json_list` 只保 JSON 形状、不碰边界标记 ⇒ 一条「我住在[引用回复]」就能
    在每轮的画像段里伪造内部边界。口径同 P1-c：**只在读侧出点全角化，不动库行**
    （库里的原文是她让我记住的事证，改了就没法复查）。零新正则、零新标记名——
    全角化真身与二手文本咽喉共用 `security/injection` 那一把尺。
    """
    return neutralize_internal_markers(str(text or ""))


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
        sender_display_name: str | None = None,
        sender_roles: list[str] | None = None,
        gender_identity: str = "unknown",
        addressing_preference: str = "",
        sender_profile_note: str = "",
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
        sender_display_name: str | None = None,
        sender_roles: list[str] | None = None,
        gender_identity: str = "unknown",
        addressing_preference: str = "",
        sender_profile_note: str = "",
    ) -> ContextBundle:
        addressing_context = build_addressing_context(
            session_type="group" if group_id else "private",
            sender_display_name=sender_display_name,
            sender_roles=sender_roles,
            gender_identity=gender_identity,
            addressing_preference=addressing_preference,
        )
        persona = PersonaProfile(
            profile_id="default",
            version="0",
            display_name="报存",
            identity="统一运行时默认人格",
            role_boundaries=["不直接发送插件效果", "不绕过审计"],
        )
        tone = ToneProfile(profile_id="default", mode="private_chat")
        return ContextBundle(
            addressing_context=addressing_context,
            request_id=request_id,
            persona=persona,
            tone=tone,
            memory_results=MemoryRetrievalResult(request_id=request_id),
            conversation_history=ConversationHistoryResult(request_id=request_id),
            knowledge_results=RetrievalResult(request_id=request_id),
            current_message=query_text,
            sender_id=sender_id,
            session_id=session_id,
            sender_profile_note=sender_profile_note,
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
        addressing_preferences: AddressingPreferenceStore | None = None,
        mood_describe: Callable[[], str] | None = None,
        quirks_describe: Callable[..., str] | None = None,
        identity_describe: Callable[[str], str] | None = None,
        reactions_describe: Callable[[str], str] | None = None,
        shared_group_provider: SharedGroupContextProvider | None = None,
        action_brackets: bool = True,
        action_brackets_provider: object | None = None,
        persona_selector: PersonaSelector | None = None,
        persona_override_provider: object | None = None,
        persona_weights_provider: object | None = None,
        persona_rng: random.Random | None = None,
        persona_versioned_injection: bool = False,
        persona_version_service: Any | None = None,
        persona_registry: PersonaProfileRegistry | None = None,
    ) -> None:
        self.persona_profile_id = persona_profile_id
        self.persona_display_name = persona_display_name
        self.persona_version = persona_version
        self.persona_files = [Path(path).expanduser() for path in persona_files]
        self.knowledge_files = [Path(path).expanduser() for path in knowledge_files]
        # 人格册（H-5乙 唯一事实源）：None 时下游 helper 懒取进程级共享实例。
        self.persona_registry = persona_registry
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
        self.addressing_preferences = addressing_preferences
        self.mood_describe = mood_describe
        self.quirks_describe = quirks_describe
        self.identity_describe = identity_describe
        self.reactions_describe = reactions_describe
        self.shared_group_provider = (
            shared_group_provider or NullSharedGroupContextProvider()
        )
        self.action_brackets = bool(action_brackets)
        self.action_brackets_provider = action_brackets_provider
        self.persona_selector = persona_selector or PersonaSelector(dict)
        self.persona_override_provider = persona_override_provider
        self.persona_weights_provider = persona_weights_provider
        # V21-PERSONA-001 装配接线（docs/design/v21r2-wire-log.md §2）：
        # True 才从人格版本库取核心（默认 False=文件直读路径逐字节不变）。
        self.persona_versioned_injection = bool(persona_versioned_injection)
        self.persona_version_service = persona_version_service
        self._versioned_provenance: tuple[str, int, str] | None = None
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

    def _effective_knowledge_files(self, active_persona: object) -> list[Path]:
        """静态知识兜底腿取哪份清单（H-4甲）：**只换人格自带的文本清单，向量库不碰**。

        - 切到备用人格且该人格在册带 knowledge_files → 用它；
        - 主人格（active_persona=None）且主人格在册带清单 → 用册子清单；
        - 其余（人格未表态 / 读册失败）→ 回落构造期 ``self.knowledge_files``（``.env`` 基线）。
        读册失败绝不阻断对话：与 ``_persona_override`` 同口径吞异常回基线。
        """
        persona_knowledge = getattr(active_persona, "knowledge_files", ()) if active_persona is not None else ()
        if persona_knowledge:
            return [Path(path).expanduser() for path in persona_knowledge]
        if active_persona is None:
            try:
                from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
                    main_persona_knowledge_files,
                )

                register_files = main_persona_knowledge_files(
                    self.persona_profile_id, registry=self.persona_registry
                )
            except Exception:  # noqa: BLE001 - 人格册不可读时回基线，不阻塞消息链。
                register_files = ()
            if register_files:
                return [Path(path).expanduser() for path in register_files]
        return self.knowledge_files

    def _effective_persona_files(self) -> list[Path]:
        """主人格文本腿取哪份**设定清单**（H-5乙；审计 SEAT-AUDIT-PERSONA-KBLIST 1.3 次级缺口）：
        **每轮现取**，在册 ``files.settings`` 非空 ⇒ 随它；册未表态（清单为空/
        无本人格册项/读册失败）⇒ 回落装配期 ``self.persona_files``（``.env``
        基线兼容位，不制造第二真身）。与 ``_effective_knowledge_files`` 同型同
        口径；读册失败绝不阻断对话。"""
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
                get_shared_registry,
            )

            registry = (
                self.persona_registry
                if self.persona_registry is not None
                else get_shared_registry()
            )
            record = registry.get(self.persona_profile_id)
            register_files = record.settings_files if record is not None else ()
        except Exception:  # noqa: BLE001 - 人格册不可读时回基线，不阻塞消息链。
            register_files = ()
        if register_files:
            return [Path(path).expanduser() for path in register_files]
        return self.persona_files

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

    def _versioned_persona_text(self, fallback_text: str, *, resource_id: str) -> str:
        """从人格版本库取核心内容（V21-PERSONA-001 注入面，fail-open）。

        服务实例优先用注入的 persona_version_service（测试/多实例隔离），
        缺省懒取进程级共享单例；不可用→回退文件文本。溯源（version+sha256+
        revision）变更时 info 一行；degraded（服务层已回退最近完好版本并
        告警）照常服务，chat 侧不二次处理。
        """
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.character.persona_injection import (
                get_shared_persona_service,
                load_versioned_persona_core,
            )

            service = self.persona_version_service
            if service is None:
                service = get_shared_persona_service()
            if service is None:
                return fallback_text
            text, provenance = load_versioned_persona_core(
                service,
                resource_id,
                fallback_text,
            )
        except Exception:
            # 装配胶水任何故障都回退文件文本（含注入模块自身缺陷），不阻塞消息链。
            logger.exception(
                "persona versioned injection glue error — resource=%s 回退文件直读路径",
                resource_id,
            )
            return fallback_text
        if provenance is not None:
            marker = (
                resource_id,
                int(provenance["version"]),
                str(provenance["content_sha256"]),
            )
            if marker != self._versioned_provenance:
                self._versioned_provenance = marker
                logger.info(
                    "persona versioned injection: resource=%s version=%s "
                    "revision=%s sha256=%s degraded=%s baseline=%s",
                    resource_id,
                    provenance["version"],
                    provenance["persona_revision"],
                    provenance["content_sha256"],
                    provenance["degraded"],
                    provenance["baseline_status"],
                )
        return text

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
        sender_display_name: str | None = None,
        sender_roles: list[str] | None = None,
        gender_identity: str = "unknown",
        addressing_preference: str = "",
        sender_profile_note: str = "",
    ) -> ContextBundle:
        # 用户显式偏好（调用方参数）优先于持久化偏好；两者都缺时退回群昵称/漂泊者规则。
        stored_preference, stored_gender = ("", "unknown")
        if self.addressing_preferences is not None:
            stored_preference, stored_gender = self.addressing_preferences.get(
                session_type="group" if group_id else "private",
                session_id=str(group_id or ""),
                sender_id=str(sender_id or ""),
            )
        addressing_context = build_addressing_context(
            session_type="group" if group_id else "private",
            sender_display_name=sender_display_name,
            sender_roles=sender_roles,
            gender_identity=gender_identity if gender_identity != "unknown" else stored_gender,
            addressing_preference=addressing_preference or stored_preference,
        )
        emotion_signals = self.emotion_provider.analyze(
            request_id=request_id,
            sender_id=sender_id,
            session_id=session_id,
            query_text=query_text,
        )
        mood_description = ""
        if callable(self.mood_describe):
            try:
                mood_description = str(self.mood_describe() or "")
            except Exception:  # noqa: BLE001 - 心情层失败不影响主链路。
                mood_description = ""
        quirks_section = ""
        if callable(self.quirks_describe):
            try:
                # G-07：带 sender 供 user scope 过滤（兼容无参旧闭包）。
                try:
                    quirks_section = str(self.quirks_describe(sender_id) or "")
                except TypeError:
                    quirks_section = str(self.quirks_describe() or "")
            except Exception:  # noqa: BLE001 - quirk 层失败不影响主链路。
                quirks_section = ""
        session_identity_note = ""
        if callable(self.identity_describe):
            try:
                session_identity_note = str(self.identity_describe(session_id) or "")
            except Exception:  # noqa: BLE001 - 会话身份层失败不影响主链路。
                session_identity_note = ""
        reactions_section = ""
        if callable(self.reactions_describe):
            try:
                reactions_section = str(self.reactions_describe(session_id) or "")
            except Exception:  # noqa: BLE001 - 表情回应层失败不影响主链路。
                reactions_section = ""
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
            # 主人格设定清单每轮现取（H-5乙 主格随册）：册子表态即随，不表态回基线。
            persona_files = self._effective_persona_files()
        persona_text = self._load_persona_text(persona_files)
        if self.persona_versioned_injection:
            # V21-PERSONA-001：人格核心改从版本库取（幂等 baseline 灌入+
            # build_core_injection 唯一出站路径，带 version+sha256 溯源）；
            # 任何故障 fail-open 回退上方文件文本（warn 一行，不阻塞消息链）。
            persona_text = self._versioned_persona_text(
                persona_text,
                resource_id=persona_profile_id,
            )
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
        # 动态好感度融合（批次 C / v4 线性版）：行为驱动层有记录时覆盖 affinity/attitude，
        # 并把档位映射到 familiarity（docs/affinity-design.md §5：档 ≥+2 → close、
        # -1..+1 → familiar、≤-2 → stranger），使语气数值参数（warmth/directness）
        # 跟随动态档位；档案的其他字段（称呼/偏好/备注）保留。
        if self.affinity_store is not None and sender_id:
            dynamic = self.affinity_store.snapshot(sender_id)
            # G-13（注入判据收口）：好感度分区的注入判据从「分值偏离基准 或 有标签」
            # 放宽为「库中存在该用户记录即注入」（按当前档位渲染）。库里有交互记录
            # 就意味着这段关系存在：惰性回归把分值拉回基准、且用户无标签时，分区
            # 不得整体消失——哪怕档位文本就是基准档的温和表述。
            # 硬约束：本判据只决定「注入与否」，不改任何数值/档位/步长/文案
            # （数值规范以 docs/affinity-design.md 为权威）。
            # snapshot() 对无记录用户返回中性默认且不带存在标记，故存在性按两层判定：
            # ①画像载荷（标签/小名/画像备注）非空 ⇒ 必有记录；②载荷为空时按
            # interaction_count>0 探查（observe() 写入的行 interaction_count 恒 ≥1，
            # 该探查为主键单点读，仅载荷无法证明存在时才触发）。
            has_affinity_record = False
            if dynamic.get("affinity") is not None:
                if (
                    dynamic.get("tags")
                    or dynamic.get("nickname")
                    or dynamic.get("profile_notes")
                ):
                    has_affinity_record = True
                else:
                    factor = self.affinity_store.factor_profile(sender_id)
                    has_affinity_record = int(factor.get("interaction_count") or 0) > 0
            if has_affinity_record:
                tags_text = "、".join(str(t) for t in dynamic.get("tags") or [])
                notes_text = _sanitize_profile_notes_text(
                    "；".join(str(n) for n in dynamic.get("profile_notes") or [])
                )
                nickname_text = str(dynamic.get("nickname") or "")
                attitude = str(dynamic.get("attitude") or "")
                # v4.1 线性态度：距档界很近时注入自然过渡措辞，门槛两侧语气连续渐变，
                # 不因生硬的档位门槛剧烈转变（用户裁定，docs/affinity-design.md §4）。
                attitude += linear_transition_for_affinity(float(dynamic["affinity"]))
                attitude += "（好感语气为线性连续渐变，临近任何档位边界都不得生硬跳变）"
                # §5 人格自守条款：追加在态度文本之后（独立一句，任何档位生效）。
                attitude += _PERSONA_SELF_GUARD_CLAUSE
                if tags_text:
                    attitude += f"（印象参考：{tags_text}；只影响语气，不外显为标签）"
                if notes_text:
                    attitude += f"（已知画像：{notes_text}；可在对话中自然体现，不逐条复述）"
                if nickname_text:
                    attitude += f"（对方的小名：{nickname_text}；可用它称呼对方）"
                tier = int(tier_for_affinity(float(dynamic["affinity"])))
                # §5 familiarity 映射：档 ≥+2 close；档 -1..+1 familiar；档 ≤-2 stranger。
                if tier >= 2:
                    familiarity = "close"
                elif tier <= -2:
                    familiarity = "stranger"
                else:
                    familiarity = "familiar"
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
                # T3（需求 3 断链）：块序每轮由跨源判据算一次，不再靠装配时手写的
                # 传参先后。判据真身＝``search_service.resolve_answer_order``（本文件
                # 与 chat 层共读同一张阶梯），意图读数＝既有 ``search_intent`` 的
                # ``detect_acg_intent``（同一个纯函数，chat 层也调它，不是第二真身）。
                # 重排失败绝不允许拖垮检索：那会让本轮整个【知识库】区消失。
                if len(knowledge_chunks) > 1:
                    from plugins.bot_unified_runtime.domains.core.search import (
                        search_service,
                    )
                    from plugins.bot_unified_runtime.domains.core.search.search_intent import (
                        detect_acg_intent,
                    )

                    knowledge_chunks = search_service.reorder_knowledge_chunks(
                        knowledge_chunks,
                        wants_latest=bool(detect_acg_intent(query_text).wants_latest),
                    )
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
            # 清单随人格现取（H-4甲）：切人格只换文本清单，向量检索腿不碰。
            knowledge_chunks = _build_knowledge_chunks(
                files=self._effective_knowledge_files(active_persona),
                max_chunks=self.knowledge_max_chunks,
                chunk_chars=self.knowledge_chunk_chars,
            )
        memory_results = _render_memory_results_with_kind_labels(
            _filter_llm_safe_memory_results(
                self.memory_provider.retrieve(
                    request_id=request_id,
                    requester_id=sender_id,
                    subject_user_id=sender_id,
                    session_id=session_id,
                    query_text=query_text,
                    max_items=self.memory_max_items,
                    max_chars=self.memory_max_chars,
                )
            ),
            max_chars=self.memory_max_chars,
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
            addressing_context=addressing_context,
            request_id=request_id,
            persona=persona,
            tone=tone,
            memory_results=memory_results,
            conversation_history=conversation_history,
            knowledge_results=RetrievalResult(
                request_id=request_id,
                chunks=knowledge_chunks,
                answerable=bool(knowledge_chunks),
                # S13：由「有块即恒定 0.8」改为可复现的真实覆盖度信号，
                # 使一次偶然词面命中不再被当成「本地知识够用」而压制联网。
                confidence=knowledge_confidence_from_evidence(
                    query_text,
                    [chunk.content for chunk in knowledge_chunks],
                ),
            ),
            current_message=query_text,
            sender_id=sender_id,
            session_id=session_id,
            emotion_signals=emotion_signals,
            mood_description=mood_description,
            quirks_section=quirks_section,
            reactions_section=reactions_section,
            session_identity_note=session_identity_note,
            sender_profile_note=sender_profile_note,
            trend_context=trend_context,
            temporal_context=temporal_context,
            glossary_context=glossary_context,
            relationship_context=relationship,
            shared_group_context=shared_group_context,
            reality_relation_note=reality_relation_note_for(query_text),
            active_persona_id=persona_profile_id,
        )


from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    ReflectionStore,
    build_reflection_memory_provider,
)


def _leg_recall_mode(provider: object) -> str:
    """读一条腿自报的取数口径。

    ``recall_mode`` **不在 ``MemoryProvider`` 协议上**（协议只有 ``retrieve``），
    所以这里按「读到什么算什么」取：认不出就按关态口径 ``legacy_newest_n`` 记
    ——宁可把一轮读成「没按话题打分」，也不许把它误报成总线打过分。
    """
    return str(getattr(provider, "recall_mode", "") or "") or DEGRADED_REASON_LEGACY_NEWEST_N


def _leg_failure_reason(provider: object) -> str:
    """挂掉的这条腿该报哪枚理由（归因单一判据，不看位置看身份）。

    只有「本轮的统一打分器」= 总线那条腿挂了才许报 ``bus_recall_failed``；
    旧归纳腿/旧仓储腿挂了报 ``memory_leg_failed``。判据取腿自己的
    ``recall_mode``（``MemoryBusProvider`` 的类属性），不取列表下标——
    下标是装配顺序的巧合，装配口一改顺序归因就会跟着错。
    """
    if str(getattr(provider, "recall_mode", "") or "") == "memory_bus":
        return DEGRADED_REASON_BUS_RECALL_FAILED
    return DEGRADED_REASON_MEMORY_LEG_FAILED


class _MergedMemoryProvider:
    """记忆消费腿：把**打过分的**候选按预算并进 prompt，本层不再二次排序。

    预算/名额之外的**新候选**不再静默丢弃：条数经哨兵 fact 交给渲染层
    （`_render_memory_results_with_kind_labels`）统一出一行「另有 N 条未列出」
    （需求11 渲染腿；哨兵 kind/text 皆空，模型面只见回执一行）。

    两种形态由 ``build_memory_read_provider`` 这道闸决定，**永不同时成立**：

    - ``ranker="memory_bus"``：总线是唯一打分器，``_providers`` 只有一条腿；
      未迁进总线的旧归纳表经 ``bus.attach_candidate_source`` 并进同一打分池
      （见 ``memory_bus_v2`` 的候选池文档）。``_fallback`` 只在总线抛异常时被调用
      一次，并必须落一条降级审计——静默降级是漏报的谎。
    - ``ranker="legacy_newest_n"``：总线没开，旧主库腿按 ``updated_at DESC`` 取
      最近 N 条、**不看本轮查询**，反思腿自选自己的池子。关态逐字节旧行为，
      但这句"本轮没按话题打分"必须可读出来（``recall_mode`` + 装配期点名一次）。
      **关态没有审计通道**：降级审计落在总线的 ``memory_recall_audit_v21``，
      而关态根本不建总线（``build_memory_read_path`` 的既有不变量：不开新连接、
      不建 v2 表，由 ``test_bus_off_writes_nothing_into_the_v2_store`` 锁着）；
      返回契约 ``MemoryRetrievalResult`` 是 StrictBaseModel、无空闲字段可挂标记，
      所以关态这一轮的可读出口只有「装配期一行日志 + 腿自报的 ``recall_mode``」
      两处，本席不为此偷偷开一条写库路径（要成真字段需改 contracts，见交接）。
    """

    def __init__(
        self,
        providers: list[MemoryProvider],
        *,
        ranker: str,
        audit_bus: Any | None = None,
        fallback: MemoryProvider | None = None,
    ) -> None:
        self._providers = providers
        self._audit_bus = audit_bus
        self._fallback = fallback
        #: **装配期事实**：本实例这一条腿是按话题打分（``memory_bus``）还是按时间
        #: 取最近几条（``legacy_newest_n``）。per-request 的降级**不改写它**（改写
        #: =并发会话互相污染彼此的口径），只走日志与召回审计。
        self.recall_mode = ranker

    def _note_degraded(
        self,
        *,
        reason: str,
        subject_user_id: str,
        session_id: str,
        request_id: str,
        detail: str,
    ) -> None:
        """降级留痕：日志一行 +（有总线时）一条注入审计；观测失败绝不外抛。

        返回值只用于「审计有没有真落账」这一件事：``record_degraded_recall``
        自己吞异常返回 False，调用方不读它就等于把「留痕失败」读成「留痕成功」
        （S-T-MEM-5 首版即栽在这里）。留痕失败时补一行日志，仍不阻断回复。
        """
        logger.warning(
            "memory recall degraded reason=%s mode=%s type=%s",
            reason,
            self.recall_mode,
            detail,
        )
        if self._audit_bus is None:
            return
        try:
            landed = self._audit_bus.record_degraded_recall(
                owner_id=subject_user_id,
                session_id=session_id,
                request_id=request_id,
                reason=reason,
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - 观测面挂了也不许影响回复
            logger.warning("memory degrade audit failed type=%s", type(exc).__name__)
            return
        if landed is False:
            logger.warning("memory degrade audit failed reason=%s", reason)

    def retrieve(
        self,
        *,
        request_id: str,
        requester_id: str,
        subject_user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_chars: int,
    ) -> MemoryRetrievalResult:
        merged: dict[str, dict[str, str]] = {}
        order: list[str] = []
        seen_ids: set[str] = set()
        used_chars = 0
        dropped_candidates = 0

        def absorb(result: MemoryRetrievalResult) -> None:
            nonlocal used_chars, dropped_candidates
            for fact in result.facts:
                fact_id = str(fact.get("fact_id", ""))
                text_len = len(str(fact.get("text", "")))
                if not fact_id or fact_id in seen_ids:
                    # 无 id=契约残行（不进账也不计数）；同 id 再见=去重而非截断。
                    continue
                seen_ids.add(fact_id)
                if len(merged) >= max_items or used_chars + text_len > max_chars:
                    dropped_candidates += 1
                    continue
                merged[fact_id] = fact
                order.append(fact_id)
                used_chars += text_len

        legs = list(self._providers)
        for index, provider in enumerate(legs):
            try:
                absorb(
                    provider.retrieve(
                        request_id=request_id,
                        requester_id=requester_id,
                        subject_user_id=subject_user_id,
                        session_id=session_id,
                        query_text=query_text,
                        max_items=max_items,
                        max_chars=max_chars,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 单路故障不断链，但必须留痕
                # 归因必须分得清：只有「统一打分器那一条腿」挂了才叫
                # ``bus_recall_failed``。反思腿/旧仓储腿挂了报成同名，运维就会
                # 去查一个今天根本没开的总线（S-T-MEM-5 首版对所有腿共用一枚理由）。
                self._note_degraded(
                    reason=_leg_failure_reason(provider),
                    subject_user_id=subject_user_id,
                    session_id=session_id,
                    request_id=request_id,
                    detail=f"{type(provider).__name__}:{type(exc).__name__}",
                )
                if index > 0 or self._fallback is None:
                    continue
                # 只有主打分器挂了才启用兜底腿：本轮明确降级为「按时间取最近 N 条」，
                # 且这条事实必须被读出来（审计已落 + 日志点名兜底腿顶上）。
                # **不写回 self.recall_mode**：那是装配期事实，被一次 per-request
                # 故障改掉会让并发会话互相污染彼此的口径（谁读到的都是最后一个
                # 倒霉蛋的状态），降级只在本轮的日志与审计里说话。
                try:
                    absorb(
                        self._fallback.retrieve(
                            request_id=request_id,
                            requester_id=requester_id,
                            subject_user_id=subject_user_id,
                            session_id=session_id,
                            query_text=query_text,
                            max_items=max_items,
                            max_chars=max_chars,
                        )
                    )
                    logger.warning(
                        "memory recall served from fallback leg mode=%s instead=%s",
                        DEGRADED_REASON_LEGACY_NEWEST_N,
                        type(self._fallback).__name__,
                    )
                except Exception as fallback_exc:  # noqa: BLE001 - 兜底也挂=本轮没记忆
                    logger.warning(
                        "memory fallback leg also failed type=%s",
                        type(fallback_exc).__name__,
                    )
        facts = [merged[k] for k in order]
        if dropped_candidates > 0:
            facts = facts + [
                {
                    "fact_id": MEMORY_TRUNCATION_FACT_ID,
                    "kind": "",
                    "text": "",
                    "sensitivity": "personal",
                    "scope_key": "global",
                    "truncated_items": str(dropped_candidates),
                }
            ]
        return MemoryRetrievalResult(request_id=request_id, facts=facts)


_ADDRESSING_STORES_LOCK = threading.Lock()
_ADDRESSING_STORES: dict[str, AddressingPreferenceStore] = {}


def _shared_addressing_preferences(config: object) -> AddressingPreferenceStore | None:
    """进程级共享称谓偏好 store（懒构建；路径解析/建库失败返回 None 不阻断对话）。"""
    try:
        path = build_runtime_data_path(
            config,
            str(
                getattr(
                    config,
                    "bot_addressing_preferences_db_path",
                    "data/addressing_preferences.sqlite3",
                )
            ),
        )
    except Exception:  # noqa: BLE001 - 路径解析失败时降级为无持久化称谓上下文。
        return None
    cache_key = str(path)
    with _ADDRESSING_STORES_LOCK:
        store = _ADDRESSING_STORES.get(cache_key)
        if store is None:
            try:
                store = AddressingPreferenceStore(path)
            except Exception:  # noqa: BLE001 - SQLite 不可用时降级，不阻断对话。
                return None
            _ADDRESSING_STORES[cache_key] = store
        return store


def build_addressing_preference_store(config: object) -> AddressingPreferenceStore | None:
    """公开入口：进程级共享称谓偏好 store（供命令面读写用户显式偏好）。"""
    return _shared_addressing_preferences(config)



# ---------------------------------------------------------------------------
# 记忆消费腿的**唯一闸**（需求 11 · S-T-MEM-5）
# ---------------------------------------------------------------------------

#: 注入总线的旧归纳候选源名（进 fact_id 前缀，与总线原生行/``legacy:`` 互不碰撞）。
REFLECTED_CANDIDATE_SOURCE = "reflected"
#: 折进打分池前的候选窗（合并层的 max_items/max_chars 才是最终预算）。
_REFLECTED_CANDIDATE_LIMIT = 40
_REFLECTED_CANDIDATE_CHARS = 6000

_LEGACY_RANKER_WARNED: set[str] = set()
_LEGACY_RANKER_LOCK = threading.Lock()


def _warn_legacy_ranker_once(db_path: str) -> None:
    """关态点名一次：召回没按本轮话题打分。

    这不是告警噪音，而是让「记忆质量差」这个症状能被子系统归因——今天生产
    ``BOT_MEMORY_BUS_ENABLED`` 缺省关，症状（每轮塞最近几条、与话题无关）在线上没有
    任何一处自己承认过。每库一次，重启后重来。
    """
    with _LEGACY_RANKER_LOCK:
        if db_path in _LEGACY_RANKER_WARNED:
            return
        _LEGACY_RANKER_WARNED.add(db_path)
    logger.warning(
        "memory recall ranker=%s: 统一打分器没开（BOT_MEMORY_BUS_ENABLED=false），"
        "本轮注入按时间取最近几条，可能混进与话题无关的话；库=%s",
        DEGRADED_REASON_LEGACY_NEWEST_N,
        db_path,
    )


def _reflection_candidate_source(config: object) -> Any | None:
    """把「尚未迁进总线的旧归纳表」包成总线候选源；反思未启用则 None。

    读取口只认既有真身 ``ReflectionStore.facts_for``（主体 + 会话 + 置信度三道闸
    都在它里面，本函数不复制判据、也不放宽一寸）。门形与
    ``reflection.build_reflection_memory_provider`` 一致，由
    ``test_memory_bus_read_leg.py::test_reflection_gate_agrees_with_the_leg`` 锁住
    两态一致——两处判据不能各说各话。
    """
    if not bool(getattr(config, "bot_reflection_enabled", False)):
        return None
    db_path = str(getattr(config, "bot_reflection_db_path", "") or "").strip()
    if not db_path:
        return None
    store = ReflectionStore(db_path)

    def read(owner_id: str, session_id: str) -> list[dict[str, Any]]:
        facts = store.facts_for(
            owner_id,
            limit=_REFLECTED_CANDIDATE_LIMIT,
            max_chars=_REFLECTED_CANDIDATE_CHARS,
            session_id=session_id,
        )
        return [
            {
                "fact_id": fact.fact_id,
                "subject_user_id": fact.sender_id,
                "session_id": fact.session_key,
                "text": fact.fact_text,
                "confidence": fact.confidence,
                "created_at": fact.created_at,
            }
            for fact in facts
        ]

    return read


def build_memory_read_provider(config: object) -> MemoryProvider:
    """记忆读取路径的唯一装配口：总线开=一条腿一个打分器，总线关=旧形态原样。

    ``build_character_context_provider`` 只经这一个函数装配 ``memory_provider``
    （由 ``test_memory_bus_read_leg.py`` 的 AST 锁执法：仓里不得有第二处
    ``_MergedMemoryProvider(`` 构造点）。

    - 总线开：主腿 ``MemoryBusProvider``；旧归纳表 ``attach_candidate_source``
      并进同一打分池（仅当归纳还没落总线，否则同一条会以两个身份并池），
      反思腿**不再并列进合并层**——两路各排各的再按列表顺序抢预算，
      正是「高分旧事实被低分新事实挤掉」的病根；
      兜底腿=同一份旧仓储，只在总线抛异常时被调用一次并落降级审计。
    - 总线关：主腿旧仓储 + 反思腿，与开本席之前**逐字节同形**（预算、去重、
      哨兵回执一概不动），只多一行装配期点名。
    """
    primary, fallback = build_memory_read_path(config)
    bus = getattr(primary, "bus", None)
    if bus is None:
        _warn_legacy_ranker_once(
            str(getattr(config, "bot_memory_db_path", "") or "").strip() or "unset"
        )
        return _MergedMemoryProvider(
            [primary, build_reflection_memory_provider(config)],
            ranker=DEGRADED_REASON_LEGACY_NEWEST_N,
        )
    if not bus.settings().writes_to_bus:
        source = _reflection_candidate_source(config)
        if source is not None:
            bus.attach_candidate_source(
                REFLECTED_CANDIDATE_SOURCE, source, provenance=PROVENANCE_REFLECTED
            )
    return _MergedMemoryProvider(
        [primary],
        ranker=_leg_recall_mode(primary),
        audit_bus=bus,
        fallback=fallback,
    )

def build_character_context_provider(
    config: object,
    *,
    conversation_history_provider: ConversationHistoryProvider | None = None,
    runtime_settings: Any | None = None,
    shared_group_llm_provider: object | None = None,
    mood_describe: Callable[[], str] | None = None,
    quirks_describe: Callable[..., str] | None = None,
    identity_describe: Callable[[str], str] | None = None,
    reactions_describe: Callable[[str], str] | None = None,
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
    kb_retriever: Any = None
    if not (fast_mode and skip_vector):
        try:
            from plugins.bot_unified_runtime.domains.core.search import (
                search_service,
            )
            from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
                MergedKnowledgeRetriever,
                build_kb_wiki_retriever,
            )

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
        except Exception:
            # 但必须留痕：这里静默置 None 曾让 5.7GB wiki 库长期无人读取而无人察觉
            # （导入路径写错被本句吞掉，见 tests/test_kb_wiki_retriever_wiring.py）。
            logger.exception("Crawl Wiki 知识库检索器装配失败，本轮人格知识检索不受影响")
            kb_retriever = None
        if kb_retriever is not None and getattr(kb_retriever, "available", False):
            # T3：腿的先后不再手写。库名与检索器**成对**交给阶梯判据排一次
            # （背景档＝persona 在前，与旧的手写传参逐字节同序 ⇒ 本轮零行为变更；
            # 变更发生在时效档那一支：由 ``resolve_answer_order`` 每轮重排，见上面
            # ``provide()`` 的检索腿）。这里的排序只保证"装配基线也出自同一把尺"，
            # 免得出现"判据说 A 先、构造序写 B 先"的两处各说各话。
            merged_legs = search_service.ordered_retriever_legs(
                [
                    (search_service.KB_SOURCE_PERSONA, knowledge_retriever),
                    (search_service.KB_SOURCE_WIKI, kb_retriever),
                ],
                wants_latest=False,
            )
            knowledge_retriever = (
                MergedKnowledgeRetriever(
                    [retriever for _, retriever in merged_legs],
                    libraries=[name for name, _ in merged_legs],
                )
                if getattr(knowledge_retriever, "available", False)
                else kb_retriever
            )
        # 单路腿也必须标注：wiki 腿不可用时（嵌入链没就绪/库缺位）旧写法让整条
        # 链永远没有 source_library，读点只能退回页级 source_id ⇒ 撞 64 字符上限
        # 炸 bot.chat（2026-09-27 生产 ValidationError 的第三条腿）。
        if (
            kb_retriever is None
            or not getattr(kb_retriever, "available", False)
        ) and callable(getattr(knowledge_retriever, "retrieve", None)):
            knowledge_retriever = MergedKnowledgeRetriever(
                [knowledge_retriever],
                libraries=[search_service.KB_SOURCE_PERSONA],
            )
    # ①（S-FIX-PERSONA-TEXT）：文本消费腿的可调用视图——备用人格册**每轮现读**。
    # 装配期一次性快照（旧 :1185 直传 dict）会把人格册冻结在构造瞬间：启动后
    # 入册/改册的人格，校验腿（runtime_admin 现算）放行、外观腿现读即发，唯独
    # 语气文本回落主人格——半切态根病（SEAT-ATK-PERSONA-APPEARANCE 探针 P1/P2）。
    # 单一形态：PersonaSelector 只收 Callable[[], Mapping]，在**唯一构造点**适配；
    # 视图与 persona_registry 参数共用同一枚册实例（不留第二真身），读册失败
    # 回空视图＝select 不命中＝主人格继续服务，绝不阻断消息链（同 override 腿口径）。
    persona_registry = getattr(config, "persona_registry", None)

    def _alt_personas_view() -> dict[str, AltPersonaSpec]:
        try:
            return build_effective_alt_personas(config, registry=persona_registry)
        except Exception:  # 视图不可用时宁缺勿冻：回空＝主人格继续，绝不阻断消息链
            logger.exception("备用人格视图现读失败——本轮人格选择回主人格")
            return {}

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
        memory_provider=build_memory_read_provider(config),
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
        addressing_preferences=_shared_addressing_preferences(config),
        shared_group_provider=build_shared_group_context_provider(
            config,
            llm_provider=shared_group_llm_provider,
        ),
        mood_describe=mood_describe,
        quirks_describe=quirks_describe,
        identity_describe=identity_describe,
        reactions_describe=reactions_describe,
        action_brackets=bool(getattr(config, "bot_persona_action_brackets", True)),
        action_brackets_provider=action_brackets_provider,
        persona_selector=PersonaSelector(_alt_personas_view),
        persona_override_provider=persona_override_provider,
        persona_weights_provider=persona_weights_provider,
        persona_registry=persona_registry,
        # V21-PERSONA-001（docs/design/v21r2-wire-log.md §2）：默认 False
        # 保守灰度——旧测试 config stub 缺键经 getattr 缺省不炸，行为=旧路径。
        persona_versioned_injection=bool(
            getattr(config, "bot_persona_versioned_injection", False)
        ),
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


def _memory_kind_label(kind_value: object) -> str:
    """把记忆条目的 kind 映射为人话类型标签（词表派生自 MemoryKind 枚举）。

    - 枚举在册且本层登记了显示名 → 中文标签；
    - 枚举在册但未登记显示名（写腿刚扩充的细分类型）、或枚举外的短英文标识
      （存量 "manual"/"auto" 等散落字面量）→ 原样点名，不编造中文；
    - kind 缺失/空白/形状可疑（含空格、换行、任意串）→ 返回空串=不打标签，
      宁缺毋滥：给没把握的条目猜类型，比不标更易误导模型复述。
    """
    raw = str(kind_value or "").strip()
    if not raw:
        return ""
    try:
        display = _MEMORY_KIND_DISPLAY_ZH.get(MemoryKind(raw))
    except ValueError:
        display = None
    if display:
        return display
    if _RAW_MEMORY_KIND_TOKEN_RE.fullmatch(raw):
        return raw
    return ""


def _memory_truncation_notice_fact(dropped_count: int) -> dict[str, str]:
    """截断回执行：静默截断=谎报，丢了几条就必须点名几条。"""
    return {
        "fact_id": MEMORY_TRUNCATION_FACT_ID,
        "kind": "",
        "text": _MEMORY_TRUNCATION_TEMPLATE_ZH.format(count=max(0, int(dropped_count))),
        "sensitivity": "personal",
        "scope_key": "global",
    }


def _render_memory_results_with_kind_labels(
    result: MemoryRetrievalResult,
    *,
    max_chars: int,
) -> MemoryRetrievalResult:
    """渲染腿：每条记忆注入前带「【类型标签】正文」成对形态，并重算字符预算。

    契约（需求11 渲染腿，测试件 tests/test_memory_kind_rendering.py 逐条锁）：
    1. 类型标签与条目正文永远成对进上下文；标签派生自存储层枚举，未知值
       原样点名或不打标，绝不编造；
    2. 预算按渲染后正文（含标签）计：注入条目文本总长 ≤ max_chars；被丢
       候选（含上游 `_MergedMemoryProvider` 以哨兵 fact 交来的计数）合并
       成唯一一行「另有 N 条未列出」，N 恒为真实丢弃数；
    3. 隐私过滤在上游 `_filter_llm_safe_memory_results` 已完成：被过滤的
       credentialed 条目**不计入 N**——「存在一条不能说的事」本身就是敏感
       信息（per-sender 归属与群摘要隔离口径不放宽）。
    """
    dropped = 0
    rendered: list[dict[str, str]] = []
    used = 0
    for fact in result.facts:
        if str(fact.get("fact_id") or "") == MEMORY_TRUNCATION_FACT_ID:
            # 合并层哨兵只带计数不带正文：并账后由本函数统一出一行回执。
            try:
                dropped += max(0, int(str(fact.get("truncated_items") or "0")))
            except ValueError:
                pass
            continue
        text = str(fact.get("text") or fact.get("summary") or "")
        label = _memory_kind_label(fact.get("kind")) if text else ""
        labeled_text = f"【{label}】{text}" if label else text
        cost = len(labeled_text) + 1  # +1 = 行间换行，预算按实际注入形态计
        if used + cost > max_chars:
            dropped += 1
            continue
        new_fact = dict(fact)
        new_fact["text"] = labeled_text
        rendered.append(new_fact)
        used += cost
    if dropped > 0:
        # 回执也要进预算：逐条从尾部腾位（腾掉的同样记进 N），保证
        # 「注入正文 + 回执行」总长 ≤ max_chars。腾到只剩回执是预算小到
        # 装不下正文的退化态——那一行仍出（宁超几个字，不虚报为零）。
        while rendered:
            notice = _memory_truncation_notice_fact(dropped)
            total = sum(len(item["text"]) + 1 for item in rendered) + len(notice["text"]) + 1
            if total <= max_chars:
                rendered.append(notice)
                break
            rendered.pop()
            dropped += 1
        else:
            rendered.append(_memory_truncation_notice_fact(dropped))
    if not rendered and not result.facts:
        return result
    return MemoryRetrievalResult(
        request_id=result.request_id,
        facts=rendered,
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

    project_root = Path(__file__).resolve().parents[5]
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
