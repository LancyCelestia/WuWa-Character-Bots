"""goal-12 表情包（贴纸）子系统波回归：反重复 / 相关性门 / 本命吸收 / 开关在册。

全离线：网络与 VLM 一律桩替换；所有 SQLite 只写 ``tmp_path``（源码树零写入，铁律 6）。
锁的分组与四件真身一一对应：

* 反重复（A）→ ``MemeSendHistoryStore`` + ``MemeLibraryStore.weighted_pick`` 咽喉
* 相关性/口味/心情门（B）→ ``meme_selection`` 打分与 ``select_sticker``
* 本命自动吸收 + 隔离不复活（C）→ ``shorekeeper_absorb`` + ``cleanup(protect_persona)``
* 情绪发图开关在册（D）→ ``feature_catalog`` + ``FeatureSwitchSnapshot.enabled``

其中 ``test_meme_feature_id_is_registered_and_off_by_default`` 是本波立案的原始
缺陷证：**未登记 id 恒 False**，根 ``__init__.py:8614`` 那条腿此前结构性死路。
"""

from __future__ import annotations

import ast
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    build_meme_library_capability,
    select_sticker_for_turn,
    sticker_scope_for,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    pick_reaction_meme,
    reaction_meme_intent_vocabulary,
)
from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_library_listener,
    meme_selection,
    shorekeeper_absorb,
)
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    GLOBAL_SCOPE,
    MemeQuarantineLedger,
    MemeSendHistoryStore,
    content_sha256_of_bytes,
    normalize_scope,
    scope_keys,
)

# ------------------------------------------------------------------ 夹具


def _png(tmp_path: Path, name: str, payload: str) -> Path:
    path = tmp_path / name
    path.write_bytes(payload.encode("utf-8"))
    return path


def _library(tmp_path: Path, items: dict[str, str], *, prefer: list[str] | None = None) -> MemeLibraryStore:
    """建一个「有标签、有内容哈希」的表情库（模拟 VLM 已打完标的状态）。"""
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=prefer or ["守岸人"])
    for md5, emotion in items.items():
        image = _png(tmp_path, f"{md5}.png", f"payload-{md5}")
        digest = content_sha256_of_bytes(image.read_bytes())
        store.add(md5=md5, path=str(image), ext="png", group_id="g1", content_sha256=digest)
        store.apply_tags(
            md5,
            is_meme=True,
            description=emotion,
            emotion_tags=[emotion],
            scene_tags=[],
            persona_hint="common",
            nsfw_score=0.0,
        )
    return store


def _md5(item: dict[str, Any] | None) -> str:
    """取 md5 并顺带完成 mypy 的 None 收窄：None 进来必炸测试，不会假绿。"""
    assert item is not None
    return str(item["md5"])


def _message(text: str, *, session_id: str = "group_1_2", sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        plain_text=text,
        request_id="req-1",
    )


def _decision() -> BotDecision:
    # 能力体只读 message（决策由路由层给），这里用轻量替身避免把契约字段
    # （target_scope/decision_reason/…）抄进测试——抄了就是「测夹具不测代码」。
    return SimpleNamespace(request_id="req-1", capability_id="bot.meme_library")  # type: ignore[return-value]


# ------------------------------------------------------------------ A 反重复


def test_history_never_repeats_within_scope(tmp_path: Path) -> None:
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3")
    sha = content_sha256_of_bytes(b"same-bytes")
    assert history.try_claim(sha, scope="group_1_2") is True
    # 同一作用域第二次必被拒。
    assert history.try_claim(sha, scope="group_1_2") is False
    # 换会话也一样：全局保留作用域参与判定 ⇒「绝不发第二次」是字面成立的。
    assert history.try_claim(sha, scope="group_9_9") is False
    assert history.is_sent(sha, scope="whatever") is True


def test_history_identity_is_content_not_filename(tmp_path: Path) -> None:
    """内容哈希认人：换个文件名仍是同一张 ⇒ 拒发；内容变了就是新图 ⇒ 放行。"""
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3")
    first = content_sha256_of_bytes(b"aaa")
    same_renamed = content_sha256_of_bytes(b"aaa")
    different = content_sha256_of_bytes(b"aab")
    assert first == same_renamed
    history.try_claim(first, scope="s")
    assert history.is_sent(same_renamed, scope="s")
    assert history.is_sent(different, scope="s") is False


def test_history_rejects_unknown_identity(tmp_path: Path) -> None:
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3")
    # 身份不明 = 无法保证不重发 ⇒ 一律视为「已发过」且占坑必失败。
    assert history.is_sent("") is True
    assert history.try_claim("", scope="s") is False


def test_history_window_and_retention_prune(tmp_path: Path) -> None:
    clock = {"now": 1_700_000_000.0}
    history = MemeSendHistoryStore(
        tmp_path / "h.sqlite3", window=2, retention_days=1, clock=lambda: clock["now"]
    )
    for index in range(5):
        history.try_claim(f"sha{index}", scope="s", at=clock["now"] + index)
    # 窗口由 prune 收口（每次收库都会调一次），不在插入路径上做同步裁剪。
    history.prune()
    # 窗口=2 ⇒ 每作用域只留最新两行（全局与 s 各两行，共 4 行）。
    stats = history.stats(scope="s")
    assert stats["global_sent"] == 2
    assert stats["total_rows"] == 4
    # 过期裁剪：把时钟推过一天以上，全部按龄出局。
    clock["now"] += 3 * 86400
    removed = history.prune()

    assert removed["expired"] >= 1
    assert history.stats(scope="s")["total_rows"] < 4


def test_history_prune_only_drops_dead_hashes_when_told(tmp_path: Path) -> None:
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3", window=0, retention_days=0)
    history.try_claim("sha-live", scope="s")
    history.try_claim("sha-gone", scope="s")
    removed = history.prune(live_hashes={"sha-live"})
    assert removed["dead"] == 2  # 全局 + 会话各一行
    assert history.is_sent("sha-live", scope="s") is True
    assert history.is_sent("sha-gone", scope="s") is False


def test_history_scope_normalisation_is_fail_closed() -> None:
    assert normalize_scope("") == GLOBAL_SCOPE
    assert normalize_scope("  group_1_2 ") == "group_1_2"
    assert normalize_scope("a\nb") == "a b"
    # 作用域键里塞通配符也不许伪造出「全局」以外的第二条宽松账。
    assert scope_keys(GLOBAL_SCOPE) == (GLOBAL_SCOPE,)
    assert scope_keys(None)[0] == GLOBAL_SCOPE


def test_history_forget_scope_never_touches_global(tmp_path: Path) -> None:
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3")
    history.try_claim("sha1", scope="s1")
    assert history.forget_scope(GLOBAL_SCOPE) == 0
    assert history.forget_scope("s1") == 1
    # 会话账清了，全局账仍在 ⇒ 还是不发第二次。
    assert history.is_sent("sha1", scope="s1") is True


def test_quarantine_ledger_is_append_only(tmp_path: Path) -> None:
    ledger = MemeQuarantineLedger(tmp_path / "q.sqlite3")
    assert ledger.contains("sha-x") is False
    assert ledger.add("sha-x", reason="nsfw_delete") is True
    # 重复立碑不覆盖首次证据，也不报错。
    assert ledger.add("sha-x", reason="later") is False
    assert ledger.reasons("sha-x") == "nsfw_delete"
    assert ledger.count() == 1


# ------------------------------------------------------------------ A 咽喉集成


def test_weighted_pick_never_resends_and_goes_none_when_exhausted(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "抱抱"})
    picked = [store.weighted_pick(keyword="", nsfw_max=0.2) for _ in range(4)]
    assert {_md5(item) for item in picked[:2]} == {"m1", "m2"}
    assert picked[2] is None and picked[3] is None, "耗尽必须 None，不得回炉重发"


def test_weighted_pick_works_without_history_store(tmp_path: Path) -> None:
    """反重复关掉（``no_repeat=False``）⇒ 逐字节回到旧行为（可重样）。"""
    image = _png(tmp_path, "m1.png", "开心")
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=["守岸人"])
    store.add(
        md5="m1",
        path=str(image),
        ext="png",
        content_sha256=content_sha256_of_bytes(image.read_bytes()),
    )
    store.apply_tags("m1", is_meme=True, description="开心", emotion_tags=["开心"])
    quiet = MemeLibraryStore(
        tmp_path / "meme_library.sqlite3", prefer=["守岸人"], no_repeat=False
    )
    seen = [_md5(quiet.weighted_pick(keyword="", nsfw_max=0.2)) for _ in range(3)]
    assert seen == ["m1", "m1", "m1"]
    assert quiet.history is None, "关掉后不再构造账本（也不该建文件）"
    assert not (tmp_path / "meme_send_history.sqlite3").exists()


def test_history_disabled_by_injection_is_ignored_when_no_repeat_true(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心"})
    store.set_history(None)
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is not None
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is not None


def test_legacy_rows_without_sha_get_filled_once(tmp_path: Path) -> None:
    """旧库行 sha 为空 ⇒ 首次过筛时懒补（一次算，永久复用），且不参选未补者。"""
    store = _library(tmp_path, {"m1": "开心"})
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE memes SET sha256=''")
    assert store.sent_content_hashes() == frozenset()
    picked = store.weighted_pick(keyword="", nsfw_max=0.2)
    assert picked is not None and picked["content_sha256"]
    with sqlite3.connect(store.db_path) as connection:
        stored = connection.execute("SELECT sha256 FROM memes WHERE md5='m1'").fetchone()[0]
    assert stored == picked["content_sha256"]
    # 补过之后第二次必空手（同一张不发两次）。
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is None


def test_unreadable_file_never_becomes_a_no_identity_send(tmp_path: Path) -> None:
    """文件被删 ⇒ 算不出身份 ⇒ 不许发（宁缺不重）。"""
    store = _library(tmp_path, {"m1": "开心"})
    (tmp_path / "m1.png").unlink()
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is None


def test_meme_library_command_goes_empty_after_library_spent(tmp_path: Path) -> None:
    """/偷表情 文案必须区分「库里没图」与「都发过了」。"""
    store = _library(tmp_path, {"m1": "开心"})
    capability = build_meme_library_capability(store, SimpleNamespace(
        bot_meme_library_cooldown_seconds=0, bot_meme_library_nsfw_max=0.2,
        bot_meme_sticker_scope_mode="global",
    ))
    first = capability(_message("偷表情", sender_id="u1"), _decision())
    assert first.images, "第一次应带图"
    second = capability(_message("偷表情", sender_id="u2"), _decision())
    assert not second.images
    assert "都发过" in second.body or "不重复" in second.body
    assert "all_sent" in second.audit_tags


def test_sticker_scope_mode_never_wider_than_global() -> None:
    assert sticker_scope_for("global", "group_1_2") is None
    assert sticker_scope_for("session", "group_1_2") == "group_1_2"
    # 未识别值落最严档，不因为拼错就放宽。
    assert sticker_scope_for("Sessions", "group_1_2") is None
    assert sticker_scope_for("", "") is None


def test_reaction_meme_leg_and_poke_leg_share_the_same_ledger(tmp_path: Path) -> None:
    """两条不改调用点的腿（回复后情绪发图 / 戳一戳发图）共用同一本反重复账。

    poke 腿在根 ``__init__.py`` 里只调 ``store.weighted_pick(keyword="", nsfw_max=…)``,
    一个参数都没多传——它却已经受管，这正是「机制做在咽喉」的意义。
    """
    store = _library(tmp_path, {"m1": "开心", "m2": "加油"})
    first = pick_reaction_meme(store, intent="开心", nsfw_max=0.2)
    assert first
    # 情绪腿发过的那张，poke 腿（旧签名、无 scope）再也拿不到。
    sent_by_reaction_leg = {
        content_sha256_of_bytes((tmp_path / f"{md5}.png").read_bytes())
        for md5 in ("m1", "m2")
    } & store.sent_content_hashes()
    assert sent_by_reaction_leg, "情绪腿必须留下账，不留账=反重复对它无效"
    later = store.weighted_pick(keyword="", nsfw_max=0.2)
    assert later is not None
    assert content_sha256_of_bytes(
        (tmp_path / f"{later['md5']}.png").read_bytes()
    ) not in sent_by_reaction_leg
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is None, "两张都发过 ⇒ 空手"


def test_pick_reaction_meme_tolerates_legacy_store_signature() -> None:
    """旧桩（只认 keyword/nsfw_max 两参数）不许因为新形参而炸掉表情腿。"""
    calls: list[dict[str, object]] = []

    class LegacyStore:
        def weighted_pick(self, *, keyword: str = "", nsfw_max: float = 0.2) -> dict[str, str]:
            calls.append({"keyword": keyword, "nsfw_max": nsfw_max})
            return {"path": "/tmp/legacy.png"}

    assert pick_reaction_meme(LegacyStore(), intent="开心", nsfw_max=0.3, scope="group_1_2")
    assert calls and all("scope" not in call for call in calls)


# ------------------------------------------------------------------ B 相关性门


def test_topic_terms_come_from_existing_vocabulary_only() -> None:
    vocabulary = meme_selection.default_vocabulary(
        prefer=["守岸人"],
        persona_terms=("岸宝",),
        intent_terms=reaction_meme_intent_vocabulary(),
    )
    assert "开心" in vocabulary and "搞笑" in vocabulary and "守岸人" in vocabulary
    terms = meme_selection.topic_terms_from_text("今天开会好开心啊", vocabulary=vocabulary)
    assert terms == ("开心",)
    # 自由词不进主题表：库没打标的图不会被「假装相关」选中。
    assert meme_selection.topic_terms_from_text("量子隧穿效应", vocabulary=vocabulary) == ()


def test_offtopic_rejected_for_strangers_allowed_for_close_users(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "加油"})
    ctx_off = meme_selection.StickerContext(topic_terms=("开心",), affinity_tier=0)
    hit = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx_off)
    assert hit is not None and hit["md5"] == "m1"
    ctx_none = meme_selection.StickerContext(topic_terms=("天气",), affinity_tier=0)
    assert store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx_none) is None, (
        "不熟的人：没有对题的就一张不发"
    )
    ctx_close = meme_selection.StickerContext(topic_terms=("天气",), affinity_tier=4)
    warm = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx_close)
    assert warm is not None, "熟人可退中性档（但仍是没发过的那张）"


def test_disliked_tag_is_a_veto_not_a_penalty(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "搞笑"})
    ctx = meme_selection.StickerContext(
        topic_terms=(), disliked_terms=("搞笑",), affinity_tier=5
    )
    picked = []
    while True:
        item = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx)
        if item is None:
            break
        picked.append(item["md5"])
        if len(picked) > 5:
            break
    assert picked == ["m1"], "被嫌的词族一张都不许发出去"


def test_mood_low_softens_noisy_but_does_not_switch_off(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "搞笑"})
    ctx = meme_selection.StickerContext(topic_terms=(), mood_valence=-0.9, affinity_tier=3)
    first = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx)
    assert _md5(first) == "m1", "低落时先给不吵闹的那张"
    second = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx)
    assert second is not None and second["md5"] == "m2", (
        "只剩吵闹的一张也照发（软偏置，不是硬开关）"
    )


def test_persona_sticker_ranks_above_generic(tmp_path: Path) -> None:
    store = _library(
        tmp_path, {"m1": "开心", "m2": "开心"}, prefer=["守岸人"]
    )
    # m2 的标签里带她的别名 ⇒ 本命加权 8.0 + PERSONA_BONUS 双档都在它这边。
    store.apply_tags("m2", is_meme=True, description="守岸人 开心", emotion_tags=["开心"])
    ctx = meme_selection.StickerContext(topic_terms=("开心",), affinity_tier=3)
    picked = store.weighted_pick(
        keyword="", nsfw_max=0.2, context=ctx, persona_terms=("守岸人", "岸宝")
    )
    assert _md5(picked) == "m2"


def test_min_relevance_floor_rejects_non_meme_rows(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心"})
    store.apply_tags("m1", is_meme=False, description="开心", emotion_tags=["开心"])
    ctx = meme_selection.StickerContext(topic_terms=("开心",), affinity_tier=3)
    floor = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx, min_relevance=0.5)
    assert floor is None, "判非表情（权重 0.25）不得越过地板"
    loose = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx, min_relevance=0.1)
    assert loose is not None


def test_selection_is_deterministic(tmp_path: Path) -> None:
    store = _library(tmp_path, {"a": "开心", "b": "开心", "c": "开心"})
    ctx = meme_selection.StickerContext(topic_terms=("开心",), affinity_tier=3)
    picks = [
        (store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx) or {}).get("md5")
        for _ in range(4)
    ]
    order = sorted(
        ["a", "b", "c"],
        key=lambda md5: content_sha256_of_bytes((tmp_path / f"{md5}.png").read_bytes()),
    )
    assert picks == [*order, None], "同分按内容哈希升序，可复盘；耗尽后 None"


def test_select_sticker_returns_none_when_history_refuses() -> None:
    candidates = [
        {"md5": "x", "weight": 1.0, "description": "开心", "content_sha256": "sha-x"}
    ]
    ctx = meme_selection.StickerContext(topic_terms=("开心",), affinity_tier=3)

    class Spent:
        def try_claim(self, sha: str, *, scope: str | None = None) -> bool:
            return False

    assert meme_selection.select_sticker(candidates, ctx, history=Spent()) is None


def test_select_sticker_fails_closed_on_broken_ledger() -> None:
    candidates = [
        {"md5": "x", "weight": 1.0, "description": "开心", "content_sha256": "sha-x"}
    ]
    ctx = meme_selection.StickerContext(topic_terms=("开心",))

    class Broken:
        def try_claim(self, sha: str, *, scope: str | None = None) -> bool:
            raise sqlite3.OperationalError("disk I/O")

    assert meme_selection.select_sticker(candidates, ctx, history=Broken()) is None


def test_facade_reads_mood_affinity_and_config(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "加油"})
    config = SimpleNamespace(
        bot_meme_library_prefer=["守岸人"],
        bot_meme_library_nsfw_max=0.2,
        bot_meme_relevance_min=0.35,
        bot_meme_sticker_scope_mode="session",
        bot_persona_profile_id="",
        bot_persona_nicknames=["岸宝"],
    )
    picked, tags = select_sticker_for_turn(
        store,
        turn_text="今天好开心",
        session_key="group_1_2",
        sender_id="u1",
        config=config,
        mood_valence_fn=lambda: 0.4,
        affinity_snapshot={"tier": 3, "tags": ["开心"]},
    )
    assert picked is not None and picked["md5"] == "m1"
    assert "topic:开心" in tags and "tier:3" in tags
    # 对题的那张发过了：熟用户（档 3）可退「中性档」发离题的一张，这不是硬凑——
    # 中性档排在有主题者之后，且仍受反重复约束。
    again, tags2 = select_sticker_for_turn(
        store,
        turn_text="今天好开心",
        session_key="group_1_2",
        sender_id="u1",
        config=config,
        affinity_snapshot={"tier": 3, "tags": ["开心"]},
    )
    assert again is not None and again["md5"] == "m2"
    assert "taste:none" not in tags2, "带了口味标签就不该记「无口味」"
    third, tags3 = select_sticker_for_turn(
        store,
        turn_text="今天好开心",
        session_key="group_1_2",
        sender_id="u1",
        config=config,
        affinity_snapshot={"tier": 3, "tags": ["开心"]},
    )
    assert third is None and "none" in tags3


def test_facade_survives_broken_providers(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心"})

    def boom() -> float:
        raise RuntimeError("mood store down")

    picked, tags = select_sticker_for_turn(
        store,
        turn_text="",
        session_key="group_1_2",
        sender_id="u1",
        config=None,
        mood_valence_fn=boom,
        affinity_snapshot=None,
    )
    assert picked is not None, "心情读不到按中性处理，不许把贴纸腿一起打死"
    assert tags[0] == "meme_sticker"


# ------------------------------------------------------------------ C 本命吸收


def test_persona_terms_come_from_central_alias_source() -> None:
    terms = shorekeeper_absorb.persona_subject_terms(
        SimpleNamespace(bot_persona_profile_id="shorekeeper", bot_persona_nicknames=[])
    )
    assert "守岸人" in terms and "岸宝" in terms
    # 不硬写：中央别名口给出的集合是本件唯一词源（别名文件改了就跟随）。
    assert set(terms) >= set(shorekeeper_absorb.persona_subject_terms(
        SimpleNamespace(bot_persona_profile_id="shorekeeper", bot_persona_nicknames=["花房的守护者"])
    ))


def test_subject_hit_is_alias_bounded() -> None:
    terms = ("守岸人", "岸宝", "shorekeeper")
    assert shorekeeper_absorb.subject_hit("这张画的是守岸人", terms) == "守岸人"
    assert shorekeeper_absorb.subject_hit("SHOREKEEPER 抱猫", terms) == "shorekeeper"
    # ASCII 别名的右边界：中文直连不算命中变体（防「岸宝藏起来了」类误伤反向也防胶合）。
    assert shorekeeper_absorb.subject_hit("shorekeeperzzz", terms) == ""
    assert shorekeeper_absorb.subject_hit("", terms) == ""


def test_absorb_marks_persona_owned_and_keeps_weight_single_source(tmp_path: Path) -> None:
    """本命行的权重**只有一个来源**（``_score_weight``），本件不另算一份。

    2026-09-30 随需求 12 重述：原先只喂 VLM 一面证据就宣称本命——那条洞正是审核制
    要堵的（单面证据只入待审）；这里补上包名线索走合法路径，**门的形状一字未动**，
    锁的本意（权重单源）也一直没变。
    """
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=["守岸人"])
    image = _png(tmp_path, "p1.png", "body-1")
    digest = content_sha256_of_bytes(image.read_bytes())
    store.add(md5="p1", path=str(image), ext="png", content_sha256=digest)
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=None,
        md5="p1",
        content_sha256_value=digest,
        tags={"is_meme": True, "description": "守岸人 递茶", "emotion_tags": ["开心"],
              "scene_tags": [], "persona_hint": "守岸人", "nsfw_score": 0.0},
        nsfw_delete=0.8,
        persona_terms=("守岸人", "岸宝"),
        naming_hints=("守岸人表情包合集",),
    )
    assert decision.action == "accepted" and decision.persona_owned is True
    with store._connect() as connection:
        row = connection.execute(
            "SELECT weight, persona_owned FROM memes WHERE md5='p1'"
        ).fetchone()
    # 权重只由 _score_weight 那一个函数决定（本命 8.0），本件不另算一份。
    assert float(row["weight"]) > 8.0 and int(row["persona_owned"]) == 1


def test_absorb_switch_off_does_not_mark_persona(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3")
    image = _png(tmp_path, "p2.png", "body-2")
    digest = content_sha256_of_bytes(image.read_bytes())
    store.add(md5="p2", path=str(image), ext="png", content_sha256=digest)
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=None,
        md5="p2",
        content_sha256_value=digest,
        tags={"description": "守岸人 递茶", "nsfw_score": 0.0},
        nsfw_delete=0.8,
        persona_terms=("守岸人",),
        persona_absorb_enabled=False,
    )
    assert decision.persona_owned is False
    assert decision.action == "accepted", "关的是本命标记，不是把图丢掉"


def test_nsfw_delete_stands_before_persona_boost(tmp_path: Path) -> None:
    """她本人的高危图也照删：NSFW 闸不因本命豁免。"""
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=["守岸人"])
    image = _png(tmp_path, "p3.png", "body-3")
    digest = content_sha256_of_bytes(image.read_bytes())
    store.add(md5="p3", path=str(image), ext="png", content_sha256=digest)
    ledger = MemeQuarantineLedger(tmp_path / "h.sqlite3")
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=ledger,
        md5="p3",
        content_sha256_value=digest,
        tags={"description": "守岸人 色情", "nsfw_score": 0.95},
        nsfw_delete=0.8,
        persona_terms=("守岸人",),
    )
    assert decision.action == "quarantined"
    assert not image.exists() and ledger.contains(digest)
    with store._connect() as connection:
        assert connection.execute("SELECT 1 FROM memes WHERE md5='p3'").fetchone() is None


def test_quarantined_content_is_not_resurrected(tmp_path: Path) -> None:
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3")
    ledger = MemeQuarantineLedger(tmp_path / "h.sqlite3")
    body = b"bad-picture"
    digest = content_sha256_of_bytes(body)
    ledger.add(digest, reason="nsfw_delete")
    decision = shorekeeper_absorb.decide_intake(store=store, ledger=ledger, md5="abc", data=body)
    assert decision.action == "quarantined"
    assert decision.reason == "nsfw_delete"
    # 顺序钉死：即便库里已无此 md5（旧的「重复」判定会放行），墓碑仍优先。
    assert store.exists("abc") is False


def test_decide_intake_reports_duplicate(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心"})
    image = tmp_path / "m1.png"
    decision = shorekeeper_absorb.decide_intake(
        store=store, ledger=None, md5="m1", data=image.read_bytes()
    )
    assert decision.action == "duplicate"


def test_persona_stickers_survive_age_prune_but_files_still_capped(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心", "m2": "抱抱"})
    store.mark_persona_owned("m1")
    with store._connect() as connection:
        # 把两张都推成「很久以前」，模拟过龄。
        connection.execute("UPDATE memes SET added_at = added_at - 999*86400")
    removed = store.cleanup(max_files=0, max_age_days=30, protect_persona=True)
    assert removed["removed"] == 1
    assert store.exists("m1") and not store.exists("m2")
    # 按量上限仍然压过豁免：本命也不能把库撑爆（否则全标本命=库无界增长）。
    image3 = _png(tmp_path, "m3.png", "payload-m3")
    store.add(md5="m3", path=str(image3), ext="png",
              content_sha256=content_sha256_of_bytes(image3.read_bytes()))
    store.mark_persona_owned("m3")
    assert store.stats()["total"] == 2
    over = store.cleanup(max_files=1, max_age_days=0, protect_persona=True)
    assert over["removed"] == 1
    assert store.stats()["total"] == 1


def _run(coro: object) -> object:
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]


def _absorb_config(tmp_path: Path) -> SimpleNamespace:
    """收库监听的离线配置：库开、打标关、目录全在 tmp_path。"""
    return SimpleNamespace(
        bot_meme_library_enabled=True,
        bot_meme_library_dir=str(tmp_path / "library"),
        bot_meme_library_max_file_bytes=1024,
        bot_meme_library_proxy="",
        bot_meme_library_group_allowlist=[],
        bot_meme_library_group_denylist=[],
        bot_meme_library_vlm_enabled=False,
        bot_meme_library_max_files=0,
        bot_meme_library_max_age_days=0,
        bot_meme_shorekeeper_protect_from_prune=True,
    )


def test_listener_absorb_skips_quarantined_before_writing(tmp_path: Path, monkeypatch) -> None:
    """端到端（离线）：下载→准入→写盘；被隔离的内容一个字节都不落盘。"""
    written: list[Path] = []
    body = b"blocked-payload"
    digest = content_sha256_of_bytes(body)

    async def fake_download(url: str, *, max_bytes: int, proxy: str) -> tuple[bytes, str]:
        return body, "image/png"

    monkeypatch.setattr(meme_library_listener, "_download_once", fake_download)

    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", no_repeat=False)
    # 墓碑账本的真身在「表情库 db 同目录/meme_send_history.sqlite3」，
    # 测试必须写到同一个路径，否则测的是「另一本账」= 假绿。
    ledger = MemeQuarantineLedger(tmp_path / "meme_send_history.sqlite3")
    ledger.add(digest, reason="nsfw_delete")
    config = _absorb_config(tmp_path)
    event = SimpleNamespace(
        get_session_id=lambda: "group_7",
        group_id="7",
        get_message=lambda: [{"type": "image", "data": {"url": "https://example.test/a.png"}}],
    )

    original_write = Path.write_bytes

    def guard_write(self: Path, data: object, *args: object, **kwargs: object) -> object:
        if self.parent.name == "library":
            written.append(self)
            raise AssertionError("隔离内容不得写盘")
        return original_write(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_bytes", guard_write)
    result = _run(meme_library_listener.absorb_event_images(None, event, config, store))
    assert isinstance(result, dict)
    assert result["saved"] == 0 and result["skipped"] == ["quarantined"]
    assert written == []


def test_absorb_admission_never_runs_on_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    """F-2 锁：准入判定（sha256 + 两次 SQLite 读）必须离环。

    判据不吃线程名、不量时间：``asyncio.get_running_loop()`` 只在**事件循环所在线程**
    成功——在 ``to_thread`` 的工作线程里它必抛 ``RuntimeError``。于是"探针在循环上被
    调到"就是可确定的红，而不是靠 sleep 猜竞态。旧实现把 ``decide_intake`` 放在循环
    上跑（每张图最坏 5MB 哈希 + 建表 executescript），群聊连发四图就是四次串行阻塞，
    与「吸收/下载绝不占事件循环」相抵。
    """
    import asyncio

    body = b"clean-payload-for-offload"

    async def fake_download(url: str, *, max_bytes: int, proxy: str) -> tuple[bytes, str]:
        return body, "image/png"

    monkeypatch.setattr(meme_library_listener, "_download_once", fake_download)

    on_loop: list[str] = []
    original_decide = shorekeeper_absorb.decide_intake

    def spy_decide(**kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # 工作线程：没有运行中的循环 = 已离环，符合预期。
        else:
            on_loop.append("decide_intake")
        return original_decide(**kwargs)

    monkeypatch.setattr(shorekeeper_absorb, "decide_intake", spy_decide)

    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", no_repeat=False)
    event = SimpleNamespace(
        get_session_id=lambda: "group_7",
        group_id="7",
        get_message=lambda: [{"type": "image", "data": {"url": "https://example.test/a.png"}}],
    )
    result = _run(
        meme_library_listener.absorb_event_images(None, event, _absorb_config(tmp_path), store)
    )
    assert isinstance(result, dict)
    assert result["saved"] == 1, "本锁只测'在哪跑'，不改变判定结果"
    assert on_loop == [], f"准入判定压在事件循环上：{on_loop}"


def test_resolve_vision_config_reads_production_list_shape() -> None:
    """F-1 锁：注册表**列表形态**（生产 ``.env`` 的真实形状）必须解析得出端点。

    旧实现按 ``registry.get(preset)`` 的 dict 形态读，列表形态取回 list、
    ``isinstance(entry, dict)`` 恒 False ⇒ 整个兜底是空操作 ⇒ 打标静默不跑
    （表现是「库里有图但都像随机」而不是报错）。修法是把形态判定交中央件
    ``vision_describe._flatten_vision_entries``——本锁同时钉住「不再回到自读形态」：
    注入的注册表两种合法形态都要能出端点。
    """
    list_shape = {
        "myvlm": [
            {"model": "m-low", "base_url": "https://low.test/v1", "priority": 5, "api_key": "k1"},
            {"model": "m-top", "base_url": "https://top.test/v1", "priority": 1, "api_key": "k2"},
        ]
    }
    dict_shape = {"other": {"model": "m-dict", "base_url": "https://dict.test/v1", "priority": 2}}

    def _config(registry: dict[str, Any], preset: str, fallback: bool) -> SimpleNamespace:
        return SimpleNamespace(
            bot_vision_model_registry=registry,
            bot_meme_library_vlm_preset=preset,
            bot_meme_library_vlm_fallback_first_preset=fallback,
            bot_meme_library_vlm_model="",
            bot_meme_library_vlm_base_url="",
            bot_meme_library_vlm_api_key="",
        )

    # 生产实况：preset 为空串 + 列表形态 ⇒ 退到真实存在、priority 最小的一条。
    got = meme_library_listener._resolve_vision_config(_config(list_shape, "", True))
    assert got["model"] == "m-top" and got["base_url"] == "https://top.test/v1"
    # 组名命中 `#` 前段：preset=myvlm 仍在这组里选 priority 最小者。
    got_named = meme_library_listener._resolve_vision_config(_config(list_shape, "myvlm", False))
    assert got_named["model"] == "m-top"
    # 单条目 dict 形态（旧配置）同样解析 ⇒ 修形态判定不是只修新形态。
    got_dict = meme_library_listener._resolve_vision_config(_config(dict_shape, "other", False))
    assert got_dict["model"] == "m-dict"
    # preset 落空且兜底关 ⇒ 诚实为空（不猜端点、不造第二份默认值）。
    got_none = meme_library_listener._resolve_vision_config(_config(list_shape, "nope", False))
    assert got_none["model"] == "" and got_none["base_url"] == ""
    # 注册表真空 ⇒ 依旧为空：兜底只兜「真实存在」的组。
    assert meme_library_listener._resolve_vision_config(_config({}, "", True))["model"] == ""


# ------------------------------------------------------------------ D 开关在册


def test_meme_feature_id_is_registered_and_off_by_default(tmp_path: Path) -> None:
    """本波立案的原始缺陷：未登记 id ⇒ ``enabled()`` 恒 False ⇒ 那条腿结构性死路。"""
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features import feature_catalog
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )

    ids = {item.id for item in feature_catalog.build_product_descriptors()}
    assert "bot.plugin.chat.reactions.meme" in ids, "根 __init__.py 问的那枚 id 必须在册"
    store = FeatureStateStore(tmp_path / "state.json", descriptors=feature_catalog.build_product_descriptors())
    service = FeatureControlService(store)
    snapshot = ProductFeatureGate(service).snapshot()
    # 缺省关（新增自动外发腿不许未经用户点头上现网），但父链是开的 ⇒ 关的是这一枚本身。
    assert snapshot.enabled("bot.plugin.chat.reactions.meme") is False
    assert snapshot.enabled("bot.plugin.chat.reactions.after_reply") is True
    # 一个真没登记的 id 仍然恒 False —— 这条断言就是原缺陷的样子。
    assert snapshot.enabled("bot.plugin.chat.reactions.not_a_real_node") is False


def test_super_admin_can_turn_the_meme_leg_on(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.control_plane.auth import Principal
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
    )
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )

    service = FeatureControlService(
        FeatureStateStore(tmp_path / "s.json", descriptors=build_product_descriptors())
    )
    node = "bot.plugin.chat.reactions.meme"
    gate = ProductFeatureGate(service)
    assert not gate.snapshot().enabled(node)
    service.change(node, True, principal=Principal("root", ("super_admin",)),
                   expected_version=service.detail(node)["state"]["version"])
    assert gate.snapshot().enabled(node)
    # 关掉父节点必须把这条腿一起带走（父子链真的执法）。
    service.change("bot.plugin.chat.reactions", False, principal=Principal("root", ("super_admin",)),
                   expected_version=service.detail("bot.plugin.chat.reactions")["state"]["version"])
    assert not gate.snapshot().enabled(node)


# ------------------------------------------------------------------ 登记面


def test_new_config_keys_have_defaults_and_are_registered() -> None:
    from plugins.bot_unified_runtime.config import Config

    defaults = {
        "bot_meme_library_vlm_fallback_first_preset": True,
        "bot_meme_shorekeeper_absorb_enabled": True,
        "bot_meme_shorekeeper_protect_from_prune": True,
        "bot_meme_relevance_min": 0.35,
        "bot_meme_sticker_scope_mode": "global",
    }
    fields = Config.model_fields
    for name, value in defaults.items():
        assert name in fields, name
        assert fields[name].default == value, name


def test_env_example_and_catalog_mention_every_new_key() -> None:
    root = Path(__file__).resolve().parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    catalog = (root / "docs" / "config-catalog-full.md").read_text(encoding="utf-8")
    for name in (
        "BOT_MEME_LIBRARY_VLM_FALLBACK_FIRST_PRESET",
        "BOT_MEME_SHOREKEEPER_ABSORB_ENABLED",
        "BOT_MEME_SHOREKEEPER_PROTECT_FROM_PRUNE",
        "BOT_MEME_RELEVANCE_MIN",
        "BOT_MEME_STICKER_SCOPE_MODE",
    ):
        assert name in env, name
        assert name in catalog, name


def test_source_tree_stays_clean_of_runtime_writes(tmp_path: Path) -> None:
    """全套动作都不许往源码树写 data/（铁律 6）。"""
    root = Path(__file__).resolve().parents[1]
    store = _library(tmp_path, {"m1": "开心"})
    store.weighted_pick(keyword="", nsfw_max=0.2)
    store.cleanup(max_files=1, max_age_days=1)
    store.stats()
    assert not (root / "data").exists() or not list((root / "data").glob("meme_send_history*"))


def test_history_file_lands_next_to_library_db(tmp_path: Path) -> None:
    store = _library(tmp_path, {"m1": "开心"})
    assert store.weighted_pick(keyword="", nsfw_max=0.2) is not None
    assert (tmp_path / "meme_send_history.sqlite3").is_file()
    assert store.history is not None


def test_candidate_text_uses_existing_tag_fields() -> None:
    text = meme_selection.candidate_text(
        {"description": "递茶", "emotion_tags": json.dumps(["开心"], ensure_ascii=False),
         "scene_tags": "[]", "persona_hint": "守岸人"}
    )
    assert "递茶" in text and "开心" in text and "守岸人" in text


def test_noisy_terms_are_a_single_copy() -> None:
    """吵闹词族只有一份真身（能力层改为 import，防第二真身）。"""
    from plugins.bot_unified_runtime.domains.meme.capabilities import meme_library

    assert meme_library._NOISY_MEME_TERMS is meme_selection.NOISY_MEME_TERMS
    assert meme_library._MOOD_LOW_VALENCE == meme_selection.MOOD_LOW_VALENCE


def test_thread_claim_is_unique_under_concurrency(tmp_path: Path) -> None:
    """并发抢同一张：只有一个线程拿得到坑（「绝不重发」在多线程下的真保证）。"""
    history = MemeSendHistoryStore(tmp_path / "h.sqlite3")
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(history.try_claim("sha-race", scope="group_1_2"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1


# ---------------------------------------------------------------------------
# 装配可达性（席 E，2026-09-26）：本波三件新件与那条门面**必须**在生产面被调到。
# 为什么单独立这条：单测全绿而生产空转是本仓最贵的一种假绿——门面
# ``select_sticker_for_turn`` 建好之后一度**只有测试在调**（戳一戳那条腿仍走裸
# ``weighted_pick``），与「配置键在册却无人读」是同一型失效形态。判据用 AST，
# 不用文本 grep（注释与 docstring 里提一句就算数＝锁形同虚设）。
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROD_SITES = {
    "门面 select_sticker_for_turn": (
        "plugins/bot_unified_runtime/__init__.py",
        {"select_sticker_for_turn"},
    ),
    "准入判定 decide_intake（落盘前先查墓碑）": (
        "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py",
        {"decide_intake"},
    ),
    "打标出口 apply_tagged_outcome（本命标记 / NSFW 立碑）": (
        "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py",
        {"apply_tagged_outcome"},
    ),
    "豁免按龄裁剪 protect_persona": (
        "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py",
        {"cleanup"},
    ),
}


def _called_names(path: Path) -> set[str]:
    """该文件里所有**被调用**的名字（``f(...)`` 与 ``obj.f(...)`` 两种形状）。"""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_goal12_pieces_are_reachable_from_production() -> None:
    """四枚装配点逐一现算：调用名必须真出现在生产件的 AST 里。"""
    for label, (relative, wanted) in _PROD_SITES.items():
        path = _REPO_ROOT / relative
        assert path.is_file(), f"生产件不在了：{relative}"
        calls = _called_names(path)
        missing = sorted(wanted - calls)
        assert not missing, f"{label} 在生产面不可达（{relative} 里没调到 {missing}）"


def test_keyword_argument_protect_persona_is_passed() -> None:
    """``store.cleanup(...)`` 必须带 ``protect_persona=`` 关键字（只调函数不算接线）。"""
    path = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cleanups = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cleanup"
    ]
    assert cleanups, "listener 里已无 store.cleanup 调用 ⇒ 本锁前提变了，改判据别删锁"
    assert any(
        kw.arg == "protect_persona" for call in cleanups for kw in call.keywords
    ), "cleanup 未传 protect_persona ⇒ 本命豁免那一档今天不生效（键在册却不执法）"


# ====================================================================
# S-STICKER-FINAL（2026-09-26）三组新锁：
#   E) 主体吸收四态判据（含守岸人=吸 / 不含=不吸 / 主体是别人=不吸 /
#      判不出=不吸且留观测）——判据单一真身 ``shorekeeper_absorb.decide_subject``
#   F) 每发归因落盘（meme_sends.reason + 结果 sticker_reason + 门面 why 标签 +
#      recent_sticker_sends 查询面）——「算了不落盘＝没做」的补账
#   G) 反重复**活性**锁（门面腿连续 N 发零重复、跨重开持久）与旧桩兼容
# ====================================================================


# ------------------------------------------------------------------ E 吸收四态


def _outcome(
    tmp_path: Path,
    tags: dict,
    *,
    enabled: bool = True,
    naming_hints: tuple[str, ...] = (),
):
    seed = abs(hash(str(tags)))
    store = MemeLibraryStore(tmp_path / f"lib-{seed}.sqlite3", prefer=["守岸人"])
    name = f"s{seed}.png"
    image = _png(tmp_path, name, f"body-{name}")
    digest = content_sha256_of_bytes(image.read_bytes())
    store.add(md5=name, path=str(image), ext="png", content_sha256=digest)
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store, ledger=None, md5=name, content_sha256_value=digest,
        tags=tags, nsfw_delete=0.8,
        persona_terms=("守岸人", "岸宝", "shorekeeper"),
        persona_absorb_enabled=enabled,
        naming_hints=naming_hints,
    )
    return store, decision, name


def test_absorb_positive_subject_hint_marks(tmp_path: Path) -> None:
    """正例①（强证据）：persona_hint 指向她 **且有第二条独立线索** ⇒ 标本命吸收。

    2026-09-30 随需求 12 重述：本锁的本意一直是「主体判对时标本命」，换代前它只喂
    VLM 一面证据就宣称本命——那正是审核制要堵的洞（单面证据只入待审，见
    ``test_meme_persona_review_queue.py::test_absorb_single_evidence_lands_in_pending_queue``）。
    这里补的是**合法路径**（包名线索＝``naming`` 第二面），不是把红线放宽。
    """
    store, decision, name = _outcome(
        tmp_path,
        {"description": "递茶", "persona_hint": "守岸人", "nsfw_score": 0.0},
        naming_hints=("守岸人表情包合集",),
    )
    assert decision.persona_owned is True and decision.subject_term == "守岸人"
    # 字面量锁的是**落库线值**（``persona_review.ADMIT``），不是本件的内部枚举。
    assert decision.review_state == "approved"
    with store._connect() as connection:
        marked = int(connection.execute(
            "SELECT persona_owned FROM memes WHERE md5=?", (name,)
        ).fetchone()[0])
    assert marked == 1


def test_absorb_positive_description_fallback_marks(tmp_path: Path) -> None:
    """正例②（补强证据）：hint 无归属（common）但描述句有她 ⇒ 走 VLM 面；
    第二面由包名线索补上才标本命（2026-09-30 随需求 12 重述，同上锁的口径）。"""
    _, decision, _ = _outcome(
        tmp_path,
        {"description": "守岸人 递茶", "persona_hint": "common", "nsfw_score": 0.0},
        naming_hints=("岸宝贴纸包",),
    )
    assert decision.persona_owned is True and decision.subject_term == "守岸人"


def test_absorb_negative_other_subject_never_marks(tmp_path: Path) -> None:
    """反例①（防误吸闸）：主体是别的角色、描述里带她 ⇒ **不标**。

    这正是「含守岸人但主体是别人」的字面场景；旧口径把四字段摊平求交，
    这一发会误标——本锁钉死新判据不复活旧行为。
    """
    _, decision, _ = _outcome(
        tmp_path,
        {"description": "可莉和守岸人同框", "persona_hint": "可莉", "nsfw_score": 0.0},
    )
    assert decision.persona_owned is False
    assert decision.audit == ("meme_absorb", "tagged", shorekeeper_absorb.SUBJECT_OTHER)


def test_absorb_negative_scene_tag_never_marks(tmp_path: Path) -> None:
    """反例②：她名字只出现在情绪/场景标签（氛围词）⇒ 不算主体证据，不标。"""
    _, decision, _ = _outcome(
        tmp_path,
        {"description": "普通日常梗图", "persona_hint": "common",
         "emotion_tags": ["开心"], "scene_tags": ["守岸人壁纸"], "nsfw_score": 0.0},
    )
    assert decision.persona_owned is False
    assert decision.audit[-1] == shorekeeper_absorb.SUBJECT_UNDETERMINED


def test_absorb_undetermined_leaves_observation(tmp_path: Path) -> None:
    """判不出＝不吸**且留观测**：结论代号进 audit（listener 落日志），不静默。"""
    _, decision, _ = _outcome(
        tmp_path, {"description": "一张普通梗图", "nsfw_score": 0.0}
    )
    assert decision.action == "accepted" and decision.persona_owned is False
    assert decision.audit == (
        "meme_absorb", "tagged", shorekeeper_absorb.SUBJECT_UNDETERMINED
    )


def test_absorb_switch_off_code_is_distinguishable(tmp_path: Path) -> None:
    """开关关与判不出必须是可区分的两种观测（别把「没开」读成「判不出」）。"""
    _, decision, _ = _outcome(
        tmp_path,
        {"description": "守岸人 递茶", "persona_hint": "守岸人", "nsfw_score": 0.0},
        enabled=False,
    )
    assert decision.persona_owned is False
    assert decision.reason == "absorb_switch_off"
    assert decision.audit[-1] == "absorb_switch_off"


def test_tag_prompt_defines_subject_semantics() -> None:
    """TAG_PROMPT 与判据的契约锁：persona_hint 必须被钉成「画面主体」归属，
    且明说「只是背景/客串不写她」——判据第 2 条的证据语义全靠这句撑着。"""
    prompt = meme_library_listener.TAG_PROMPT
    assert "画面主体" in prompt and "背景" in prompt and "common" in prompt


def test_listener_logs_absorb_outcome_decision() -> None:
    """观测腿结构锁：``_tag_with_vlm`` 拿到 decision 后必须落日志
    （只调函数不记＝没观测）。"""
    path = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_tag_with_vlm"
    )
    logs = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "info"
    ]
    assert logs, "_tag_with_vlm 不再记 outcome 日志 ⇒ 判不出的观测断了"
    assert "audit" in ast.dump(fn), "日志没带结论代号（audit）⇒ 观测只剩个 md5"


# ------------------------------------------------------------------ F 每发归因


def test_context_leg_persist_reason_to_ledger(tmp_path: Path) -> None:
    """四因腿（poke/问答共用门面）：选中的理由必须**同时**出现在
    ①结果字典 sticker_reason ②门面审计标签 why:* ③账本行 reason——三处同源。"""
    store = _library(tmp_path, {"m1": "开心", "m2": "加油"})
    config = SimpleNamespace(
        bot_meme_library_prefer=["守岸人"],
        bot_meme_library_nsfw_max=0.2,
        bot_meme_relevance_min=0.35,
        bot_meme_sticker_scope_mode="global",
        bot_persona_profile_id="",
        bot_persona_nicknames=[],
    )
    picked, tags = select_sticker_for_turn(
        store, turn_text="今天好开心", session_key="group_1_2", sender_id="u1",
        config=config, mood_valence_fn=lambda: 0.4,
        affinity_snapshot={"tier": 3, "tags": ["开心"]},
    )
    assert picked is not None
    reason = str(picked.get("sticker_reason", ""))
    assert reason.startswith("why="), f"结果没带归因: {reason!r}"
    assert "taste" in reason, "命中口味印象却没记进归因 ⇒ 可归因是假的"
    assert any(str(tag).startswith("why:") for tag in tags), tags
    sha = str(picked["content_sha256"])
    stored = store.history.last_reason(sha)
    assert stored == reason, "账本与结果不同源（两份真相）"
    assert "|tier=3" in stored and "topic=开心" in stored


def test_random_leg_records_random_attribution(tmp_path: Path) -> None:
    """/偷表情（无上下文旧腿）：没有四因可记就**如实记 random**，不造四因假象。"""
    store = _library(tmp_path, {"m1": "开心"})
    picked = store.weighted_pick(keyword="", nsfw_max=0.2)
    assert picked is not None
    assert picked["sticker_reason"] == "why=random|kw=none"
    assert (
        store.history.last_reason(str(picked["content_sha256"]))
        == "why=random|kw=none"
    )


def test_attribution_carries_no_user_text(tmp_path: Path) -> None:
    """隐私钉：归因串只准有词表代号与分值——聊天原文、昵称一律不进账本。"""
    store = _library(tmp_path, {"m1": "开心"})
    config = SimpleNamespace(
        bot_meme_library_prefer=[], bot_meme_library_nsfw_max=0.2,
        bot_meme_relevance_min=0.0, bot_meme_sticker_scope_mode="global",
        bot_persona_profile_id="", bot_persona_nicknames=[],
    )
    picked, _tags = select_sticker_for_turn(
        store, turn_text="阿澜今天聊投资聊得好开心", session_key="group_9_9",
        sender_id="u1", config=config,
        affinity_snapshot={"tier": 2, "tags": []},
    )
    assert picked is not None
    reason = str(picked.get("sticker_reason", ""))
    for leak in ("投资", "阿澜", "聊得"):
        assert leak not in reason, f"归因串漏出用户原文: {reason!r}"
    assert "topic=开心" in reason, "词表词允许进（那是它自己的词表），原文不行"


def test_recent_sticker_sends_maps_back_to_rows(tmp_path: Path) -> None:
    """查询面：sha 反查回库行（md5/description），不暴露路径也不丢理由。"""
    store = _library(tmp_path, {"m1": "开心", "m2": "加油"})
    one = store.weighted_pick(keyword="", nsfw_max=0.2)
    rows = store.recent_sticker_sends(limit=5)
    assert one is not None
    assert len(rows) == 1
    row = rows[0]
    assert row["md5"] in {"m1", "m2"} and row["reason"].startswith("why=random")
    assert "path" not in row, "查询面不外泄文件路径"


def test_claim_tolerates_history_stub_without_reason_kwarg() -> None:
    """旧桩兼容：不认识 ``reason`` 形参的假账本照旧占坑
    （只对「签名不接受该关键字」的 TypeError 回退，其余异常不许吞）。"""
    calls: list = []

    class LegacyHistory:
        def try_claim(self, sha: str, *, scope: str | None = None) -> bool:
            calls.append({"scope": scope})
            return True

    assert meme_selection.claim_for_send(LegacyHistory(), "sha-a", "s", "why=persona")
    assert calls == [{"scope": "s"}]

    class Broken(LegacyHistory):
        def try_claim(self, sha: str, *, scope: str | None = None, reason: str = "") -> bool:
            raise sqlite3.OperationalError("disk I/O")

    try:
        meme_selection.claim_for_send(Broken(), "sha-b", "s", "why=persona")
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("非签名型 TypeError/账本异常被吞了")


def test_sanitize_reason_strips_newlines_and_caps() -> None:
    from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
        REASON_MAX_CHARS,
        sanitize_reason,
    )

    dirty = "why=persona\n\t多行 注入\r 原文" + ("x" * 400)
    clean = sanitize_reason(dirty)
    assert "\n" not in clean and "\r" not in clean and "\t" not in clean
    assert len(clean) <= REASON_MAX_CHARS and clean.startswith("why=persona")


def test_history_receives_reason_column_migration(tmp_path: Path) -> None:
    """旧表补列迁移：先按**旧三列**建一张 meme_sends，再用新件打开 ⇒
    reason 列出现、旧行不丢、旧行 reason 为空串（诚实：旧行为不记归因）。"""
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE meme_sends (scope TEXT NOT NULL, content_sha256 TEXT"
            " NOT NULL, sent_at REAL NOT NULL, PRIMARY KEY (scope, content_sha256))"
        )
        connection.execute(
            "INSERT INTO meme_sends (scope, content_sha256, sent_at)"
            " VALUES ('*', 'sha-old', 1.0)"
        )
    history = MemeSendHistoryStore(db)
    with history._connect() as connection:
        cols = {
            str(r["name"]) for r in connection.execute("PRAGMA table_info(meme_sends)")
        }
        assert "reason" in cols
        rows = connection.execute(
            "SELECT content_sha256, reason FROM meme_sends"
        ).fetchall()
    assert [(r["content_sha256"], r["reason"]) for r in rows] == [("sha-old", "")]
    assert history.try_claim("sha-new", scope="s1", reason="why=persona|topic=开心")
    assert history.last_reason("sha-new").startswith("why=persona")


# ------------------------------------------------------------------ G 反重复活性


def test_consecutive_facade_sends_never_repeat_until_exhausted(tmp_path: Path) -> None:
    """**活性锁**（不是存在性锁）：门面腿连续 8 发，重复数恒为零，先发完再空手。

    这条打的是「同一张贴纸不发第二次」的行为本身：账本+咽喉+四因腿端到端串
    起来跑 N 发，任何一发重样即红。与注毒台配合：把「重复集合读空」两层**同拆**
    必打红本锁；单拆一层是等价变异（另一层兜底 ⇒ 行为仍零重复），那是双层防线的
    设计语义，本锁按行为判定、不装出「一层坏就红」的样子。
    """
    store = _library(tmp_path, {f"m{i}": "开心" for i in range(6)})
    config = SimpleNamespace(
        bot_meme_library_prefer=["守岸人"], bot_meme_library_nsfw_max=0.2,
        bot_meme_relevance_min=0.0, bot_meme_sticker_scope_mode="global",
        bot_persona_profile_id="", bot_persona_nicknames=[],
    )
    seen: list = []
    exhausted_at = None
    for turn in range(8):
        picked, _tags = select_sticker_for_turn(
            store, turn_text="开心", session_key="group_5_5", sender_id="u5",
            config=config, affinity_snapshot={"tier": 3, "tags": []},
        )
        if picked is None:
            exhausted_at = turn
            break
        seen.append(str(picked["content_sha256"]))
    assert len(seen) == 6 == len(set(seen)), f"6 张库应发满 6 发且零重复：{seen}"
    assert exhausted_at == 6, "发完必须空手（不得回炉重发）"


def test_dedup_memory_survives_store_reopen(tmp_path: Path) -> None:
    """重启后仍记得：换一个全新的 store/history 实例指向同一文件，发过的照旧拒。"""
    store = _library(tmp_path, {"m1": "开心"})
    first = store.weighted_pick(keyword="", nsfw_max=0.2)
    assert first is not None
    reopened = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=["守岸人"])
    assert reopened.weighted_pick(keyword="", nsfw_max=0.2) is None, "重启即忘=假防重"


# ====================================================================
# S-STICKER-12（2026-09-26）：口味极性的**生产供给**锁 + 幻影键门 +
# 收库功能门在册锁。立案根因：build_context 旧代码读 snapshot 从不产出
# 的 disliked_tags 键 ⇒「不讨用户喜欢」一票否决在生产恒空（单测喂合成
# 快照全绿＝假绿），而 tags 列里 negative/insult/tease 来源的标签反而
# 混进口味加成。现修：极性劈分判据派生自 affinity._IMPRESSION_RULES。
# ====================================================================


def test_negative_impression_tags_derive_from_affinity_rules() -> None:
    """负向标签集合 = 规则表中非 positive 来源的标签（零词表副本，随真身漂移自动跟随）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        _IMPRESSION_RULES,
    )

    negatives = meme_selection.negative_impression_tags()
    expected = {tag for watch, _t, tag in _IMPRESSION_RULES if watch != "positive"}
    assert negatives == frozenset(expected)
    # 语义钉死（防「悄悄翻转某 watch 的极性」）：这三个由负行为攒出，必须是否决词；
    # 那两个是正向印象，绝不进否决面。
    assert {"爱抱怨", "口无遮拦", "爱戏弄"} <= negatives
    assert not ({"友善", "老朋友"} & negatives)


def test_negative_tag_never_earns_taste_bonus() -> None:
    """负向印象标签绝不进 liked（旧口径会加分＝「越口无遮拦越被奖励」）。"""
    ctx = meme_selection.build_context(
        affinity_snapshot={"tags": ["爱戏弄"], "tier": 5}
    )
    assert ctx.liked_terms == ()
    assert ctx.disliked_terms == ("爱戏弄",)


def test_production_snapshot_shape_vetoes_negative_tags(tmp_path: Path) -> None:
    """喂 affinity **真产出形态**的快照 ⇒ 带负向印象词的贴纸一张都不发。

    这是「不讨用户喜欢」腿从纯叙述变生产可达的行为锁：键集合就是
    DynamicAffinityStore.snapshot() 的出品（affinity.py 2298-2304 行形），
    不再靠任何合成 disliked_tags 键喂。
    """
    store = _library(tmp_path, {"m1": "开心", "m2": "爱抱怨"})
    snapshot = {
        "affinity": 0.2,
        "nickname": "",
        "tags": ["友善", "爱抱怨"],
        "profile_notes": [],
        "tier": 3,
        "attitude": "温和",
    }
    ctx = meme_selection.build_context(turn_text="", affinity_snapshot=snapshot)
    assert "爱抱怨" in ctx.disliked_terms
    assert "爱抱怨" not in ctx.liked_terms and "友善" in ctx.liked_terms
    sent: list[str] = []
    for _ in range(4):
        item = store.weighted_pick(keyword="", nsfw_max=0.2, context=ctx)
        if item is None:
            break
        sent.append(str(item["md5"]))
    assert sent == ["m1"], "被负向印象命中的贴纸必须一票否决，正向的那张照发"


def test_build_context_reads_only_keys_snapshot_emits() -> None:
    """幻影键门：build_context 从快照 get 的每个键都必须在 snapshot() 出品集合里。

    立案锁型——本波就是靠它把 disliked_tags 那类「消费方读一个生产者从不写的键」
    钉死。tier/tags 必须在（缺了＝口味/好感腿空转）；未来若 snapshot 真扩了
    否决列，加进出品列本锁自然放行，**不许**往本测试塞豁免名单。
    """
    sel_path = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/meme/sources/meme_selection.py"
    )
    sel_tree = ast.parse(sel_path.read_text(encoding="utf-8-sig"))
    consumed: set[str] = set()
    for node in ast.walk(sel_tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "build_context"):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "get"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id == "affinity_snapshot"
                and inner.args
                and isinstance(inner.args[0], ast.Constant)
                and isinstance(inner.args[0].value, str)
            ):
                consumed.add(str(inner.args[0].value))
    assert consumed, "build_context 已不读快照 ⇒ 本锁前提变了，改判据别删锁"
    assert {"tier", "tags"} <= consumed

    aff_path = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py"
    )
    aff_tree = ast.parse(aff_path.read_text(encoding="utf-8-sig"))
    produced: set[str] = set()
    for cls in ast.walk(aff_tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "DynamicAffinityStore"):
            continue
        for fn in cls.body:
            if not (isinstance(fn, ast.FunctionDef) and fn.name == "snapshot"):
                continue
            for d in ast.walk(fn):
                if isinstance(d, ast.Dict):
                    for key in d.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            produced.add(str(key.value))
    assert produced, "affinity.snapshot 的 dict 字面量解析不到 ⇒ 先修解析再谈锁"
    assert consumed <= produced, (
        f"幻影键回潮：build_context 读了 snapshot 不产出的键 {sorted(consumed - produced)}"
    )


def test_meme_auto_absorb_feature_registered_and_on_by_default(tmp_path: Path) -> None:
    """收库腿功能门三合一：在册、缺省**开**（goal-12「需要开启自动爬取吸收」）、
    根装配真问这枚 id（防「在册无人问」与「问而不册」两个方向）。"""
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features import feature_catalog
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )

    node = "bot.plugin.meme_library.auto_absorb"
    descriptors = feature_catalog.build_product_descriptors()
    by_id = {item.id: item for item in descriptors}
    assert node in by_id, "根文件问的 id 必须先在册（未登记恒 False＝结构性死路）"
    assert by_id[node].default_enabled is True
    service = FeatureControlService(
        FeatureStateStore(tmp_path / "feats.json", descriptors=descriptors)
    )
    assert ProductFeatureGate(service).snapshot().enabled(node) is True
    root_src = (
        _REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
    ).read_text(encoding="utf-8-sig")
    assert f'enabled("{node}")' in root_src, "缺省开却没人问＝假接线"
