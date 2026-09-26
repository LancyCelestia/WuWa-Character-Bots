"""守岸人主体贴纸的自动吸收与隔离策略（goal-12 半 C）。

三件事，全部是**判定**，不做 IO：

1. **主体判定**：这张图的主角是不是守岸人本人。词表只认中央别名口
   ``domains/chat_reply/runtime/aliases.py::persona_alias_terms``
   （= ``personas/shorekeeper/aliases.txt`` ∪ 官方策展兜底），本件一个字的人名
   都不硬写——别名文件改了这里自动跟随，AGENTS「禁第二真身」在此落地。
   **判定面（S-STICKER-FINAL 收口，见 :func:`decide_subject`）**：主体证据分
   两层——``persona_hint``（TAG_PROMPT 钉死其语义=画面主体归属）优先且可一票
   指向他人；hint 无归属时退看 ``description``；情绪/场景标签**不算**主体证据
   （旧口径摊平四字段求交，会把「主体是别人、角落出现她」的图误标本命）。
   不引入新的视觉模型调用、不立第二套标签体系。
2. **命中即收藏**：主体是她的贴纸标 ``persona_owned=1``，并沿用既有
   ``MemeLibraryStore._score_weight`` 的本命加权（``_PRIORITY_HINTS`` 首档 8.0）
   ——权重只由那一个函数决定，本件不另算一份分数。``persona_owned`` 的**唯一**
   额外语义是「豁免按龄裁剪」：她的图是收藏，不是三十天流水（见
   ``meme_library.cleanup`` 的 ``protect_persona``）。
3. **隔离不复活**：NSFW 命中删除阈值时，删文件删行**并且**立内容级墓碑；
   吸收前先查墓碑，命中直接拒收。旧实现只有前者，于是同一张图再被发一次
   就会原样复活（重新入库、重新打标、重新可发送）——这是本件补的真实漏口。
   隔离语义对齐 ``scripts/clean_food_gallery.py``：文件可回捞、判定不落地就不动、
   证据不抹；差别是这里的账本是内容级永久表，不是按日期的一次性目录。

安全边界（不改的东西）：
* NSFW 降权/删除阈值仍由既有两枚配置键决定（``bot_meme_library_nsfw_max`` /
  ``bot_meme_library_nsfw_delete``），本件不放宽任何一档；
* 群白名单/黑名单门留在 ``absorb_event_images``，本件不碰；
* 落盘目录继续走 Config 的 ``path_fields`` 重映射（源码树零写入，铁律 6）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.domains.media.digest import media_digest
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    MemeQuarantineLedger,
)

#: 纯 ASCII 别名的右边界（``\b`` 在中英混排下会失效，仓内既有口径：
#: ``(?<![A-Za-z])…(?![A-Za-z])``，见 content_route / relationships 先例）。
_ASCII_ONLY_RE = re.compile(r"^[A-Za-z0-9 ._-]+$")

#: 墓碑理由代号（进审计，不进用户可见文案）。
REASON_NSFW = "nsfw_delete"
REASON_MANUAL = "manual_quarantine"

#: ``persona_hint`` 里表示「VLM 也说不准归属」的哨兵值（TAG_PROMPT 契约要求
#: 不确定填 ``common``）；它**不是**主体证据，只是「无强证据」的记号。
_HINT_UNKNOWN = {"", "common"}

#: 主体判定的三种结论代号（进审计=「判不出也留观测」的落点）。
SUBJECT_HIT = "subject_hit"            # 主体证据是她 ⇒ 吸收（标本命）
SUBJECT_OTHER = "subject_other"        # 主体明确是别人（persona_hint 指向他人）⇒ 不标
SUBJECT_UNDETERMINED = "subject_undetermined"  # 判不出 ⇒ 不标，留观测，不猜


def persona_subject_terms(config: Any) -> tuple[str, ...]:
    """主体词表 = 中央人格别名口；读不到时诚实返回空元组（= 永不判命中）。

    空表**不**回落成硬编码名单：那样等于在这里造第二真身，且会在别名源出问题时
    悄悄放宽自动收库。宁可今天不收，也不猜。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
            persona_alias_terms,
        )

        return tuple(persona_alias_terms(config))
    except Exception:  # noqa: BLE001 - 中央源不可用 ⇒ 不判主体，不影响其余收库。
        return ()


def _alias_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    if _ASCII_ONLY_RE.match(term):
        return re.compile(rf"(?<![A-Za-z]){escaped}(?![A-Za-z])", re.IGNORECASE)
    return re.compile(escaped)


def subject_hit(text: str, terms: Sequence[str]) -> str:
    """返回第一个命中的主体别名（未命中返回空串）。"""
    haystack = str(text or "")
    if not haystack.strip():
        return ""
    for term in terms:
        clean = str(term or "").strip()
        if not clean:
            continue
        if _alias_pattern(clean).search(haystack):
            return clean
    return ""


def decide_subject(
    tags: dict[str, Any] | None,
    terms: Sequence[str],
) -> tuple[str, str]:
    """主体判定（S-STICKER-FINAL 收口的**唯一判据口**）→ ``(命中别名, 结论代号)``。

    四条规则，判定面按证据强度分层——**不再拿全量标签文本当主体证据**
    （旧口径把 ``description+persona_hint+emotion+scene`` 摊平求交，一张
    「主体是别家角色、角落贴了个守岸人小表情」的图会因 scene/description 提到
    她的名字被误标本命，整堆同人图因此被 8.0 权重顶进选图前排）：

    1. ``persona_hint``（TAG_PROMPT 已明确其语义=**画面主体**角色归属）命中她的
       别名 ⇒ ``(term, SUBJECT_HIT)``——强证据，吸收（标本命）。
    2. ``persona_hint`` 明确指向**他人**（非空、非 ``common``、不含她的别名）
       ⇒ ``("", SUBJECT_OTHER)``——即便 description 里提到她也不标；这正是
       「含守岸人但主体是别人」的防误吸闸。
    3. ``persona_hint`` 缺失/为 ``common``（VLM 没给出归属）时退看
       ``description``（主体描述句）命中 ⇒ ``(term, SUBJECT_HIT)``。
       情绪/场景标签**不**升格为主体证据（它们描述的是氛围，不是主角）。
    4. 两处都拿不到证据 ⇒ ``("", SUBJECT_UNDETERMINED)``——**判不出＝不吸**，
       但结论代号随 ``apply_tagged_outcome`` 的审计落进日志（留观测，不静默）。

    匹配器仍只有 :func:`subject_hit` 一把尺（别名右边界、ASCII 防胶合都在它
    里），本函数只做**字段择面**，不新增第二套词表/正则。
    """
    payload = tags or {}
    hint = str(payload.get("persona_hint", "") or "").strip()
    hint_term = subject_hit(hint, terms)
    if hint_term:
        return hint_term, SUBJECT_HIT
    if hint and hint.lower() not in _HINT_UNKNOWN:
        return "", SUBJECT_OTHER
    desc_term = subject_hit(str(payload.get("description", "") or ""), terms)
    if desc_term:
        return desc_term, SUBJECT_HIT
    return "", SUBJECT_UNDETERMINED


def content_sha256(data: bytes) -> str:
    """字节 → 内容身份（中央摘要件，本件不自拼算法）。"""
    return media_digest(bytes(data))


@dataclass(frozen=True)
class AbsorbDecision:
    """一次吸收尝试的判定结果（调用方据此决定写盘/入库/拒收）。"""

    action: str  # accepted | duplicate | quarantined | rejected
    md5: str = ""
    content_sha256: str = ""
    persona_owned: bool = False
    subject_term: str = ""
    reason: str = ""
    audit: tuple[str, ...] = field(default=())


def ledger_for(db_path: Any) -> MemeQuarantineLedger:
    """墓碑账本（与发送史同库同目录：一次 ``stat`` 就看全两张表）。"""
    return MemeQuarantineLedger(db_path)


def decide_intake(
    *,
    store: Any,
    ledger: Any,
    md5: str,
    data: bytes,
) -> AbsorbDecision:
    """落盘**之前**的准入判定：墓碑优先，其次内容去重。

    顺序是钉死的：先查墓碑再看 ``store.exists``。反过来时，一张被隔离过的图
    只要库里还留着它的行就会先被判「重复」而悄悄跳过，日志里看不出这是拒绝。
    """
    sha = content_sha256(data)
    safe_md5 = str(md5 or "").strip().lower()
    if ledger is not None and ledger.contains(sha):
        return AbsorbDecision(
            action="quarantined",
            md5=safe_md5,
            content_sha256=sha,
            reason=ledger.reasons(sha) or REASON_MANUAL,
            audit=("meme_absorb", "quarantine_hit"),
        )
    if store is not None and store.exists(safe_md5):
        return AbsorbDecision(
            action="duplicate", md5=safe_md5, content_sha256=sha, audit=("meme_absorb", "duplicate")
        )
    return AbsorbDecision(
        action="accepted", md5=safe_md5, content_sha256=sha, audit=("meme_absorb", "accepted")
    )


def apply_tagged_outcome(
    *,
    store: Any,
    ledger: Any,
    md5: str,
    content_sha256_value: str,
    tags: dict[str, Any],
    nsfw_delete: float,
    persona_terms: Sequence[str],
    persona_absorb_enabled: bool = True,
) -> AbsorbDecision:
    """打标**之后**的落库判定：NSFW 删除并立碑 / 本命标记 / 普通入库。

    三个分支互斥且顺序固定（高危先走，绝不因为「是她」而豁免 NSFW 闸）。

    ``persona_absorb_enabled``（配置 ``bot_meme_shorekeeper_absorb_enabled``，缺省开）
    = 她的语义：**自动吸收主体是守岸人的贴纸**（标本命 ⇒ 入本命收藏、豁免按龄
    裁剪、选图时吃 ``_PRIORITY_HINTS`` 的 8.0 加权）。关掉它不改变「图片照常入库」
    这件事——收库门本身（``bot_meme_library_enabled`` + 群黑白名单）在调用方，
    本件不放宽、也不越权代开。
    """
    sha = str(content_sha256_value or "").strip().lower()
    nsfw = float((tags or {}).get("nsfw_score", 0.0) or 0.0)
    if nsfw >= float(nsfw_delete):
        # 淫秽色情不存也不可发：删行删文件 + 内容级墓碑（同图重发不复活）。
        removed = bool(store.remove(md5, tombstone_reason=REASON_NSFW))
        if ledger is not None and sha:
            ledger.add(sha, reason=REASON_NSFW)
        return AbsorbDecision(
            action="quarantined",
            md5=str(md5),
            content_sha256=sha,
            reason=REASON_NSFW,
            audit=("meme_absorb", "nsfw_deleted", "tombstone" if removed else "tombstone_only"),
        )
    store.apply_tags(
        md5,
        is_meme=bool((tags or {}).get("is_meme", True)),
        description=str((tags or {}).get("description", ""))[:60],
        emotion_tags=[str(item) for item in ((tags or {}).get("emotion_tags") or [])][:6],
        scene_tags=[str(item) for item in ((tags or {}).get("scene_tags") or [])][:6],
        persona_hint=str((tags or {}).get("persona_hint", "common"))[:24],
        nsfw_score=nsfw,
    )
    hit, subject_code = (
        decide_subject(tags, persona_terms)
        if persona_absorb_enabled
        else ("", "absorb_switch_off")
    )
    if not hit:
        # 「不标」也要能区分三种真因（她裁定的观测面：判不出/主体是别人/开关关）。
        # 结论代号进 audit——listener 把它落日志，事后「这张为什么没成她的收藏」
        # 有据可查，不是静默丢弃。
        return AbsorbDecision(
            action="accepted",
            md5=str(md5),
            content_sha256=sha,
            reason="" if persona_absorb_enabled else "absorb_switch_off",
            audit=("meme_absorb", "tagged", subject_code),
        )
    # 主体是她：标本命（豁免按龄裁剪）。权重不在此另算——``apply_tags`` 已经
    # 走过 ``_score_weight``，``_PRIORITY_HINTS`` 首档对「守岸人/岸宝」给 8.0。
    store.mark_persona_owned(md5, owned=True)
    return AbsorbDecision(
        action="accepted",
        md5=str(md5),
        content_sha256=sha,
        persona_owned=True,
        subject_term=hit,
        audit=("meme_absorb", "persona_owned"),
    )


__all__ = [
    "REASON_MANUAL",
    "REASON_NSFW",
    "SUBJECT_HIT",
    "SUBJECT_OTHER",
    "SUBJECT_UNDETERMINED",
    "AbsorbDecision",
    "apply_tagged_outcome",
    "content_sha256",
    "decide_intake",
    "decide_subject",
    "ledger_for",
    "persona_subject_terms",
    "subject_hit",
]
