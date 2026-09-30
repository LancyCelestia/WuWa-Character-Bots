"""本命贴纸准入的**双证据门 + 待审队列**（S-MEME2-REVIEW，2026-09-29，需求 12 半）。

用户裁定的原话形状是：VLM 认角色实测 0/4 不可信 ⇒「**绝不得把没认出的图当守岸人收**」，
所以主体判定不许再靠一条证据就进本命池。本件把准入判据收成一张表：

* **证据面（face）四类**，每面独立产出一条「谁主张这张的主角是她」的证词：
  ``vlm_tag``（模型给的 persona_hint / 描述句）、``naming``（包名·文件名·来源线索）、
  ``embedding``（与已确认本命样本的相似度，**注入式**）、``human``（管理员显式 pin/审批）。
* **入本命池的最低门槛**：``vlm_tag ∧ (naming ∨ embedding ∨ human)``。
  即"模型说 + 一条模型之外的独立线索"才算数；单面证据 ⇒ **只入待审**，不入本命池。
* **人审终裁**：``human`` 面单独成立即准入（管理员 pin/审批就是那条独立证据；
  ``scripts/import_meme_packs.py --pin`` 走的正是这一面）。
* **主体明确是别人** ⇒ ``none``：既不标本命也不进待审（旧防误吸闸语义逐字保留，
  见 ``shorekeeper_absorb.decide_subject`` 规则 2）。
* **什么都没主张** ⇒ ``none``：照常当普通梗图入库，不占待审名额。

三条纪律：

1. **不立第二套主体判据**：每面的"命中别名"仍只用 ``shorekeeper_absorb.subject_hit``
   一把尺（右边界、ASCII 防胶合都在它里），本件只做**择面与配平**。
2. **不猜缺席的证据**：``embedding`` 没有真身可算（全仓检索只有文本向量件
   ``chat_reply/character/vector_knowledge.py`` 与 wiki 嵌入，**没有图像嵌入道**）
   ⇒ 缺省记 ``embedding_unavailable`` 进审计，绝不拿"没算"冒充"算过且不像"。
   将来接上只需注入 provider。
3. **待审不等于禁发**：待审图仍在库里（普通梗图身份，走相关性地板与 NSFW 闸照旧），
   只是**不再吃本命加权**（8.0 那一档与选图侧的 ``PERSONA_BONUS`` 一起停）——
   理由是"未经确认的模型主张不配顶到选图前排"，而不是"这张不能发"。

安全面：NSFW 降权/删除、目录消毒、群黑白名单、墓碑优先的去重——全部留在原调用点，
本件一个都不放宽；它只回答"能不能算她的收藏"。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.domains.meme.sources import shorekeeper_absorb

#: 证据面代号（进审计与队列行，不进用户可见文案）。
FACE_VLM = "vlm_tag"
FACE_NAMING = "naming"
FACE_EMBEDDING = "embedding"
FACE_HUMAN = "human"

#: 第二证据面候选：模型之外，任何一面独立成立即可与 ``vlm_tag`` 配对。
_SECOND_FACES: tuple[str, ...] = (FACE_NAMING, FACE_EMBEDDING, FACE_HUMAN)

#: 准入结论三态（与库行 ``review_state`` 列的字面值同一套，不另立拼写）。
ADMIT = "approved"
PENDING = "pending"
NONE_ = "none"

#: 结论代号（审计用；逐枚都有牙锁，长出新值不吞）。
CODE_DUAL = "dual_evidence"
CODE_HUMAN = "human_decree"
CODE_SINGLE_VLM = "single_evidence:vlm"
CODE_SINGLE_NAMING = "single_evidence:naming"
CODE_SINGLE_EMBEDDING = "single_evidence:embedding"
CODE_OTHER_SUBJECT = "subject_other"
CODE_NO_CLAIM = "no_claim"
CODE_SWITCH_OFF = "absorb_switch_off"

#: 嵌入面的缺席记号（诚实边界，不是证据面）。
EMBEDDING_UNAVAILABLE = "embedding_unavailable"

#: provider 签名：``(md5) -> 命中的别名或假值``。算不出/没接上就返回 ``None``。
EmbeddingProvider = Callable[[str], "str | None"]


@dataclass(frozen=True)
class Evidence:
    """四条证据面的取证结果（只存命中别名，不存模型原文/用户原文）。"""

    hits: dict[str, str] = field(default_factory=dict)
    subject_code: str = shorekeeper_absorb.SUBJECT_UNDETERMINED
    notes: tuple[str, ...] = ()

    def face(self, name: str) -> str:
        return str(self.hits.get(name) or "")

    @property
    def active_faces(self) -> tuple[str, ...]:
        return tuple(name for name in (FACE_VLM, FACE_NAMING, FACE_EMBEDDING, FACE_HUMAN) if self.face(name))


@dataclass(frozen=True)
class Admission:
    """准入结论：``state`` ∈ {approved, pending, none}。"""

    state: str
    code: str
    persona_owned: bool = False
    subject_term: str = ""
    faces: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def review_state(self) -> str:
        """写进库行的字面值：``approved``/``pending`` 各记其名，``none`` 记空串（无主张）。"""
        return self.state if self.state in (ADMIT, PENDING) else ""


def _terms_text(values: Iterable[Any]) -> str:
    """把命名/来源线索拼成一条可匹配文本（去空、压空白，限长防灌）。"""
    cleaned = [str(item or "").strip() for item in values]
    return " ".join(" ".join(item for item in cleaned if item).split())[:200]


def collect_evidence(
    *,
    tags: dict[str, Any] | None,
    naming_hints: Sequence[str] = (),
    terms: Sequence[str],
    md5: str = "",
    human_term: str = "",
    embedding_provider: EmbeddingProvider | None = None,
) -> Evidence:
    """取证：逐面独立问一次，谁说了什么就记谁，互不借光。

    ``tags`` 是 VLM 的产出（persona_hint/description 择面由 ``decide_subject`` 判，
    本件不重复那套规则）；``naming_hints`` 是包名/文件名/来源标签这类**模型之外**
    的线索；``human_term`` 只由管理员 pin/审批给出；``embedding_provider`` 缺席即
    记 ``embedding_unavailable``（不猜、不冒充）。
    """
    hits: dict[str, str] = {}
    notes: list[str] = []
    payload = tags or {}
    subject_term, subject_code = shorekeeper_absorb.decide_subject(payload, terms)
    if subject_code == shorekeeper_absorb.SUBJECT_HIT:
        hits[FACE_VLM] = subject_term
    naming_text = _terms_text(naming_hints)
    naming_term = shorekeeper_absorb.subject_hit(naming_text, terms)
    if naming_term:
        hits[FACE_NAMING] = naming_term
    if embedding_provider is not None:
        try:
            embedding_term = embedding_provider(str(md5 or ""))
        except Exception:  # noqa: BLE001 - provider 抛错＝这一面今天没取证，不等于否定。
            embedding_term = None
            notes.append("embedding_error")
        if embedding_term:
            hits[FACE_EMBEDDING] = str(embedding_term)
    else:
        notes.append(EMBEDDING_UNAVAILABLE)
    if str(human_term or "").strip():
        hits[FACE_HUMAN] = str(human_term).strip()
    return Evidence(hits=hits, subject_code=subject_code, notes=tuple(notes))


def decide_admission(evidence: Evidence, *, absorb_enabled: bool = True) -> Admission:
    """表驱动准入判据（本件唯一裁决口）。

    判定次序钉死：先排掉「主体明确是别人」（一票不吸），再看开关，再看人审终裁，
    最后按「vlm ∧ 第二面」配平；配不齐就 pending，一面都没有就 none。
    """
    if evidence.subject_code == shorekeeper_absorb.SUBJECT_OTHER:
        return Admission(state=NONE_, code=CODE_OTHER_SUBJECT, faces=evidence.active_faces)
    if not absorb_enabled:
        # 开关关＝不做本命标记（图照常入库）；结论代号与旧口径逐字一致，别长第二套。
        return Admission(state=NONE_, code=CODE_SWITCH_OFF, faces=evidence.active_faces)
    faces = evidence.active_faces
    if FACE_HUMAN in faces:
        return Admission(
            state=ADMIT,
            code=CODE_HUMAN,
            persona_owned=True,
            subject_term=evidence.face(FACE_HUMAN),
            faces=faces,
        )
    term = evidence.face(FACE_VLM) or evidence.face(FACE_NAMING) or evidence.face(FACE_EMBEDDING)
    second = [name for name in _SECOND_FACES if name in faces]
    if FACE_VLM in faces and second:
        return Admission(
            state=ADMIT, code=CODE_DUAL, persona_owned=True, subject_term=term, faces=faces
        )
    if faces:
        single = faces[0]
        code = {
            FACE_VLM: CODE_SINGLE_VLM,
            FACE_NAMING: CODE_SINGLE_NAMING,
            FACE_EMBEDDING: CODE_SINGLE_EMBEDDING,
        }.get(single, CODE_SINGLE_VLM)
        missing = tuple(
            [FACE_VLM] if single != FACE_VLM else [name for name in _SECOND_FACES if name not in faces]
        )
        return Admission(state=PENDING, code=code, subject_term=term, faces=faces, missing=missing)
    return Admission(
        state=NONE_,
        code=CODE_NO_CLAIM,
        faces=faces,
        missing=(FACE_VLM, *_SECOND_FACES),
    )


def admit_evidence(
    *,
    tags: dict[str, Any] | None,
    naming_hints: Sequence[str] = (),
    terms: Sequence[str],
    md5: str = "",
    human_term: str = "",
    embedding_provider: EmbeddingProvider | None = None,
    absorb_enabled: bool = True,
) -> tuple[Admission, Evidence]:
    """取证 + 裁决的一站式入口（调用方不必自己拼两步，免得漏掉取证面）。"""
    evidence = collect_evidence(
        tags=tags,
        naming_hints=naming_hints,
        terms=terms,
        md5=md5,
        human_term=human_term,
        embedding_provider=embedding_provider,
    )
    return decide_admission(evidence, absorb_enabled=absorb_enabled), evidence


__all__ = [
    "ADMIT",
    "CODE_DUAL",
    "CODE_HUMAN",
    "CODE_NO_CLAIM",
    "CODE_OTHER_SUBJECT",
    "CODE_SINGLE_EMBEDDING",
    "CODE_SINGLE_NAMING",
    "CODE_SINGLE_VLM",
    "CODE_SWITCH_OFF",
    "EMBEDDING_UNAVAILABLE",
    "NONE_",
    "PENDING",
    "Evidence",
    "admit_evidence",
    "collect_evidence",
    "decide_admission",
]
