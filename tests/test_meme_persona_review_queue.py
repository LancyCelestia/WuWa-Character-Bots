"""S-MEME2-REVIEW（2026-09-29，需求 12）：本命准入的双证据门 + 待审队列。

用户裁定的形状：VLM 认角色实测不可信 ⇒ 一条证据不许进本命池，认不出主体的图
绝不许当守岸人收。本文件锁四件事，全部离线（tmp_path + 桩 config，不联网、
不碰生产库）：

1. **判据表**（``persona_review``）：``vlm ∧ (naming ∨ embedding ∨ human)`` 才准入；
   单面证据 ⇒ 待审；主体明确是别人 ⇒ 既不标本命也不占待审名额；谁都没主张 ⇒ none。
2. **取证面不许互相借光**：本地包导入只有文件名线索 ⇒ 命名面成立、VLM 面缺席，
   绝不因为同一段文字被写进 description 就凑成"两条证据"。
3. **待审 ≠ 禁发，但也不许吃本命加权**：pending 行仍可被普通选图腿挑走（相关性
   地板与 NSFW 闸照旧），只是 8.0 那一档与 ``PERSONA_BONUS`` 一并停掉；审批通过
   后加权照复。存量行（``review_state=''``）逐字节不变——不许把已确认的收藏悄悄降档。
4. **审批面**（``/表情库 审批 …``）：非管理员零执行、不改库；列表/通过/拒绝各有牙；
   拒绝走既有 ``remove(tombstone_reason=…)``，同图重发不复活。
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    build_meme_library_capability,
    parse_meme_library_command,
)
from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_selection,
    persona_review,
    shorekeeper_absorb,
)
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    MemeQuarantineLedger,
    content_sha256_of_bytes,
)

TERMS = ("守岸人", "岸宝", "shorekeeper")

# ------------------------------------------------------------------ 小工具


def _png_bytes(side: int = 512, seed: int = 7) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (seed % 251, 3, 9)).save(buffer, format="PNG")
    return buffer.getvalue()


def _seed_row(
    store: MemeLibraryStore,
    tmp_path: Path,
    md5: str,
    *,
    body: bytes | None = None,
) -> str:
    data = body if body is not None else _png_bytes(seed=abs(hash(md5)) % 250)
    path = tmp_path / f"{md5}.png"
    path.write_bytes(data)
    store.add(md5=md5, path=str(path), ext="png", content_sha256=content_sha256_of_bytes(data))
    return content_sha256_of_bytes(data)


def _message(text: str, *, sender_id: str = "u1", session_id: str = "group:1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP,
        group_id=session_id.split(":", 1)[-1],
        sender_id=sender_id,
        plain_text=text,
    )


_DECISION = BotDecision(
    request_id="r-meme2",
    should_respond=True,
    mode="command",
    trigger="test",
    capability_id="bot.meme_library",
    target_scope=SessionType.GROUP,
    decision_reason="unit-test",
)


# ============================================================ 1. 判据表本身


def test_single_vlm_face_is_pending_not_admitted() -> None:
    """VLM 单独一句话＝单面证据 ⇒ 待审，绝不直接进本命池（用户点名的红线）。"""
    admission, evidence = persona_review.admit_evidence(
        tags={"description": "递茶", "persona_hint": "守岸人"},
        terms=TERMS,
        naming_hints=[],
    )
    assert admission.state == persona_review.PENDING
    assert admission.persona_owned is False
    assert evidence.face(persona_review.FACE_VLM) == "守岸人"
    assert admission.code == persona_review.CODE_SINGLE_VLM
    # 缺的那一面必须说得出名字，不能只写"证据不足"四个字。
    assert persona_review.FACE_NAMING in admission.missing


def test_vlm_plus_naming_is_admitted() -> None:
    admission, _ = persona_review.admit_evidence(
        tags={"description": "递茶", "persona_hint": "守岸人"},
        terms=TERMS,
        naming_hints=["守岸人小贴纸包"],
    )
    assert admission.state == persona_review.ADMIT and admission.persona_owned is True
    assert admission.code == persona_review.CODE_DUAL
    assert set(admission.faces) >= {persona_review.FACE_VLM, persona_review.FACE_NAMING}


def test_naming_only_face_is_pending() -> None:
    """本地包导入只有文件名线索 ⇒ 待审（没有模型那一面，也没人点头）。"""
    admission, _ = persona_review.admit_evidence(
        tags={}, terms=TERMS, naming_hints=["岸宝合集", "岸宝-01"]
    )
    assert admission.state == persona_review.PENDING
    assert admission.code == persona_review.CODE_SINGLE_NAMING


def test_human_decree_alone_is_admitted() -> None:
    """管理员审批/pin 本身就是独立证据面，单独成立即准入。"""
    admission, _ = persona_review.admit_evidence(
        tags={}, terms=TERMS, naming_hints=[], human_term="守岸人"
    )
    assert admission.state == persona_review.ADMIT and admission.persona_owned is True
    assert admission.code == persona_review.CODE_HUMAN


def test_embedding_provider_face_pairs_with_vlm() -> None:
    admission, _ = persona_review.admit_evidence(
        tags={"persona_hint": "守岸人"},
        terms=TERMS,
        embedding_provider=lambda _md5: "岸宝",
    )
    assert admission.state == persona_review.ADMIT and admission.code == persona_review.CODE_DUAL


def test_embedding_absence_is_reported_not_faked() -> None:
    """没接图像嵌入道 ⇒ 记 unavailable，绝不把"没算"当成"算过且不像"。"""
    evidence = persona_review.collect_evidence(
        tags={"persona_hint": "守岸人"}, terms=TERMS, naming_hints=["普通梗图"]
    )
    assert persona_review.EMBEDDING_UNAVAILABLE in evidence.notes
    assert evidence.face(persona_review.FACE_EMBEDDING) == ""


def test_other_subject_never_enters_queue() -> None:
    """主体明确是别人：不标本命、也不占待审名额（旧防误吸闸语义逐字保留）。"""
    admission, _ = persona_review.admit_evidence(
        tags={"description": "可莉和守岸人同框", "persona_hint": "可莉"},
        terms=TERMS,
        naming_hints=["守岸人"],
    )
    assert admission.state == persona_review.NONE_
    assert admission.code == persona_review.CODE_OTHER_SUBJECT
    assert admission.review_state == ""


def test_no_claim_at_all_is_none() -> None:
    admission, _ = persona_review.admit_evidence(
        tags={"description": "路边猫", "persona_hint": "common"}, terms=TERMS
    )
    assert admission.state == persona_review.NONE_ and admission.code == persona_review.CODE_NO_CLAIM


def test_switch_off_keeps_old_code() -> None:
    admission, _ = persona_review.admit_evidence(
        tags={"persona_hint": "守岸人"}, terms=TERMS, naming_hints=["守岸人包"], absorb_enabled=False
    )
    assert admission.state == persona_review.NONE_
    assert admission.code == persona_review.CODE_SWITCH_OFF


def test_faces_do_not_double_count_the_same_string() -> None:
    """同一段文字既是 description 又是包名 ⇒ 只算命名面（取证不许自我借光）。"""
    evidence = persona_review.collect_evidence(
        tags={},  # 没有 VLM 产出
        terms=TERMS,
        naming_hints=["守岸人 递茶"],
    )
    assert evidence.face(persona_review.FACE_VLM) == ""
    assert evidence.face(persona_review.FACE_NAMING) == "守岸人"


# =============================================== 2. 落库：待审不吃本命加权


def test_absorb_single_evidence_lands_in_pending_queue(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib.sqlite3", prefer=["守岸人"])
    digest = _seed_row(store, tmp_path, "q1")
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=None,
        md5="q1",
        content_sha256_value=digest,
        tags={"is_meme": True, "description": "守岸人 递茶", "persona_hint": "守岸人"},
        nsfw_delete=0.8,
        persona_terms=TERMS,
    )
    assert decision.action == "accepted"
    assert decision.persona_owned is False, "单面证据绝不标本命"
    assert decision.review_state == persona_review.PENDING
    with store._connect() as connection:
        row = connection.execute(
            "SELECT weight, persona_owned, review_state FROM memes WHERE md5='q1'"
        ).fetchone()
    assert int(row["persona_owned"]) == 0 and str(row["review_state"]) == persona_review.PENDING
    assert float(row["weight"]) < 8.0, "待审图不许吃本命 8.0 那一档"


def test_absorb_dual_evidence_marks_persona(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib2.sqlite3", prefer=[])
    digest = _seed_row(store, tmp_path, "d1")
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=None,
        md5="d1",
        content_sha256_value=digest,
        tags={"description": "递茶", "persona_hint": "守岸人"},
        nsfw_delete=0.8,
        persona_terms=TERMS,
        naming_hints=["守岸人表情包合集"],
    )
    assert decision.persona_owned is True
    assert decision.review_state == persona_review.ADMIT
    with store._connect() as connection:
        weight = float(
            connection.execute("SELECT weight FROM memes WHERE md5='d1'").fetchone()[0]
        )
    assert weight >= 8.0, "双证据齐 ⇒ 本命加权照吃（权重真身仍是 _score_weight）"


def test_legacy_rows_keep_their_weight(tmp_path: Path) -> None:
    """存量行（review_state=''）逐字节不变：不许把已确认的收藏悄悄降档。"""
    store = MemeLibraryStore(tmp_path / "lib3.sqlite3", prefer=[])
    _seed_row(store, tmp_path, "old")
    store.apply_tags("old", description="守岸人 递茶", persona_hint="守岸人")
    with store._connect() as connection:
        weight = float(
            connection.execute("SELECT weight FROM memes WHERE md5='old'").fetchone()[0]
        )
    assert weight >= 8.0


def test_approve_restores_boost_and_reject_tombstones(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib4.sqlite3", prefer=[])
    ledger = MemeQuarantineLedger(tmp_path / "h.sqlite3")
    _seed_row(store, tmp_path, "p1")
    store.apply_tags("p1", description="守岸人 递茶", persona_hint="守岸人")
    assert store.set_review_state("p1", persona_review.PENDING) is True
    with store._connect() as connection:
        pending_weight = float(
            connection.execute("SELECT weight FROM memes WHERE md5='p1'").fetchone()[0]
        )
    assert pending_weight < 8.0
    assert store.set_review_state("p1", persona_review.ADMIT) is True
    with store._connect() as connection:
        row = connection.execute(
            "SELECT weight, persona_owned, review_state FROM memes WHERE md5='p1'"
        ).fetchone()
    assert float(row["weight"]) >= 8.0 and int(row["persona_owned"]) == 1
    assert str(row["review_state"]) == persona_review.ADMIT

    digest2 = _seed_row(store, tmp_path, "p2")
    store.apply_tags("p2", description="守岸人 比心", persona_hint="守岸人")
    store.set_review_state("p2", persona_review.PENDING)
    assert store.reject_review("p2", ledger=ledger) is True
    assert store.exists("p2") is False
    assert ledger.contains(digest2), "拒绝＝内容级墓碑，同图重发不复活"


def test_pending_rows_are_visible_in_stats_and_queue(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib5.sqlite3", prefer=[])
    _seed_row(store, tmp_path, "s1")
    _seed_row(store, tmp_path, "s2")
    store.apply_tags("s1", description="守岸人 递茶", persona_hint="守岸人")
    store.set_review_state("s1", persona_review.PENDING)
    stats = store.stats()
    assert stats["pending_review"] == 1
    queue = store.list_review(persona_review.PENDING, limit=10)
    assert [str(item["md5"]) for item in queue] == ["s1"]
    assert queue[0]["description"] == "守岸人 递茶"
    # 待审与"从没打过标"是两个数：队列不许靠 description 为空来冒充。
    assert store.stats()["untagged"] == 1, "此刻只剩 s2 没写过描述句"
    _seed_row(store, tmp_path, "s3")
    assert store.stats()["pending_review"] == 1, "新来的没打标行不许混进待审队列"
    # 现算口径（S-MEME-SEMANTICS）：s2 与 s3 都是描述句为空的行 ⇒ untagged 必须 1→2。
    # 旧写法抄成 1 是把刚插的那行漏数了（真身 ``stats``/``list_untagged`` 同一把尺
    # ``IFNULL(description,'')=''``，实测两条都空）；两个数各走各的才是本件要锁的事。
    assert store.stats()["untagged"] == 2, "没打标 +1、待审纹丝不动"


# =========================================== 3. 选图侧：待审不吃本命加成


def _candidate(md5: str, *, state: str, weight: float) -> dict[str, Any]:
    return {
        "md5": md5,
        "content_sha256": md5.ljust(64, "0"),
        "description": "守岸人 递茶",
        "emotion_tags": "[]",
        "scene_tags": "[]",
        "persona_hint": "守岸人",
        "weight": weight,
        "review_state": state,
    }


def test_pending_candidate_gets_no_persona_bonus() -> None:
    context = meme_selection.StickerContext(topic_terms=("守岸人",), affinity_tier=3)
    approved = _candidate("a", state=persona_review.ADMIT, weight=1.0)
    pending = _candidate("p", state=persona_review.PENDING, weight=1.0)
    gate_a, rank_a, reason_a = meme_selection.score_sticker_candidate(approved, context, persona_terms=TERMS)
    gate_p, rank_p, reason_p = meme_selection.score_sticker_candidate(pending, context, persona_terms=TERMS)
    assert rank_a > rank_p, "同一张图：待审档不许和已确认档并列前排"
    assert "persona" in reason_a
    assert "persona" not in reason_p
    assert gate_a == gate_p, "地板分不变——待审不是禁发，只是不加分"


def test_pending_rows_are_still_sendable(tmp_path: Path) -> None:
    """待审 ≠ 封禁：普通选图腿仍能挑走它（相关性地板与 NSFW 闸照旧）。"""
    store = MemeLibraryStore(tmp_path / "lib6.sqlite3", prefer=[])
    digest = _seed_row(store, tmp_path, "send1")
    store.apply_tags("send1", description="开心", persona_hint="common")
    store.set_review_state("send1", persona_review.PENDING)
    picked = store.weighted_pick(keyword="", nsfw_max=0.2)
    assert picked is not None and picked["md5"] == "send1"
    assert picked["review_state"] == persona_review.PENDING
    assert digest


# ================================================== 4. 审批命令面（能力层）


def _admin_config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_admin_user_ids=["900"],
        bot_super_admin_user_ids=["900"],
        bot_meme_library_nsfw_max=0.2,
        bot_meme_library_cooldown_seconds=20,
        bot_meme_relevance_min=0.35,
        bot_meme_sticker_scope_mode="global",
        bot_meme_library_prefer=["守岸人"],
        bot_reactions_sentiment_enabled=False,
    )


def test_review_command_parses_as_action() -> None:
    assert parse_meme_library_command("/表情库 待审") == ("review", "")
    assert parse_meme_library_command("表情统计 审批 通过 1234abcd") == ("review", "通过 1234abcd")
    assert parse_meme_library_command("表情库 审批 拒绝 12") == ("review", "拒绝 12")
    # 老命令一字不动：裸「表情库」仍走统计。
    assert parse_meme_library_command("/表情库") == ("stats", "")


def test_non_admin_cannot_touch_the_queue(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib7.sqlite3", prefer=[])
    _seed_row(store, tmp_path, "x1")
    store.apply_tags("x1", description="守岸人 递茶", persona_hint="守岸人")
    store.set_review_state("x1", persona_review.PENDING)
    capability = build_meme_library_capability(store, _admin_config())
    result = capability(_message("/表情库 审批 通过 x1", sender_id="666"), _DECISION)
    assert result.kind == "text" and "守岸人" in result.body
    assert "denied" in result.audit_tags
    assert store.exists("x1"), "非管理员零执行：库一个字节都不许动"
    with store._connect() as connection:
        state = str(
            connection.execute("SELECT review_state FROM memes WHERE md5='x1'").fetchone()[0]
        )
    assert state == persona_review.PENDING


def test_admin_can_list_approve_and_reject(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib8.sqlite3", prefer=[])
    digest = _seed_row(store, tmp_path, "abcdef1234")
    other = _seed_row(store, tmp_path, "ffeeddcc11")
    for md5 in ("abcdef1234", "ffeeddcc11"):
        store.apply_tags(md5, description="守岸人 递茶", persona_hint="守岸人")
        store.set_review_state(md5, persona_review.PENDING)
    capability = build_meme_library_capability(store, _admin_config())

    listed = capability(_message("/表情库 待审", sender_id="900"), _DECISION)
    assert "abcdef12" in listed.body and listed.kind == "mixed"
    assert listed.images, "审批要看得见图，否则管理员是在盲签"

    approved = capability(_message("/表情库 审批 通过 abcdef", sender_id="900"), _DECISION)
    assert "approved" in approved.audit_tags
    with store._connect() as connection:
        row = connection.execute(
            "SELECT review_state, persona_owned FROM memes WHERE md5='abcdef1234'"
        ).fetchone()
    assert str(row["review_state"]) == persona_review.ADMIT and int(row["persona_owned"]) == 1

    rejected = capability(_message("/表情库 审批 拒绝 ffeedd", sender_id="900"), _DECISION)
    assert "rejected" in rejected.audit_tags
    assert store.exists("ffeeddcc11") is False
    assert store.exists("abcdef1234") is True
    assert digest and other

    empty = capability(_message("/表情库 待审", sender_id="900"), _DECISION)
    assert empty.kind == "text" and "空" in empty.body


def test_ambiguous_prefix_asks_instead_of_guessing(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib9.sqlite3", prefer=[])
    for md5 in ("aa1", "aa2"):
        _seed_row(store, tmp_path, md5)
        store.apply_tags(md5, description="守岸人 递茶", persona_hint="守岸人")
        store.set_review_state(md5, persona_review.PENDING)
    capability = build_meme_library_capability(store, _admin_config())
    result = capability(_message("/表情库 审批 通过 a", sender_id="900"), _DECISION)
    assert "ambiguous" in result.audit_tags
    for md5 in ("aa1", "aa2"):
        assert store.exists(md5)


def test_pending_count_is_spoken_in_stats(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "lib10.sqlite3", prefer=[])
    _seed_row(store, tmp_path, "z1")
    store.apply_tags("z1", description="守岸人 递茶", persona_hint="守岸人")
    store.set_review_state("z1", persona_review.PENDING)
    capability = build_meme_library_capability(store, _admin_config())
    result = capability(_message("/表情库统计", sender_id="900"), _DECISION)
    assert "待审" in result.body or "1 张" in result.body


@pytest.mark.parametrize(
    "term",
    [persona_review.FACE_VLM, persona_review.FACE_NAMING, persona_review.FACE_EMBEDDING],
)
def test_each_single_face_alone_lands_in_pending(term: str) -> None:
    """三面逐一单独成立都只入待审（判据表没有旁门）。"""
    kwargs: dict[str, Any] = {"terms": TERMS}
    if term == persona_review.FACE_VLM:
        kwargs["tags"] = {"persona_hint": "守岸人"}
    elif term == persona_review.FACE_NAMING:
        kwargs["tags"] = {}
        kwargs["naming_hints"] = ["守岸人包"]
    else:
        kwargs["tags"] = {}
        kwargs["embedding_provider"] = lambda _md5: "守岸人"
    admission, _ = persona_review.admit_evidence(**kwargs)
    assert admission.state == persona_review.PENDING, f"{term} 单面不该进本命池"
