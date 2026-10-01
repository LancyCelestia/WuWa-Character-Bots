"""画像事实写侧消毒锁（ATK-AFFINITY 票②·S-FIX-AFF-ALGO-R 收编，2026-09-28）。

病灶（审计票②）：``learn_profile`` 把 ``extract_profile_facts`` 的原文直接并入
``profile_notes``——记忆腿（``store_extracted_memories``）与反思事实腿
（``save_facts``）都过 ``pre_write_sanitize``，唯独这条腿裸奔；画像文本经
providers→prompt 直达模型，写侧不过毒=注入面直连。

本锁钉三态判据（与两道已接闸的腿**同一道闸**，非第二套正则）：
- 干净事实 ⇒ 逐字节入库（既有行为零扰动）；
- 内部边界标记 ⇒ ``neutralize_internal_markers`` 全角化后入库，返回口同值
  （杜绝原文经返回值旁路再入 prompt）；
- 硬红线 ⇒ 该条拒收；全部被拒 ⇒ 返回空、profile_notes 零写入。
断言一律拿闸函数现算期望值——锁的是「接了这道闸」的接线，不抄词表形态。
"""

from __future__ import annotations

import json

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
)


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _store(tmp_path) -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_Clock())


def _notes(store, sender: str) -> list[str] | None:
    with store._lock, store._connect() as connection:
        row = connection.execute(
            "SELECT profile_notes FROM user_affinity WHERE sender_id = ?",
            (sender,),
        ).fetchone()
    if row is None or row["profile_notes"] is None:
        return None
    return [str(item) for item in json.loads(str(row["profile_notes"]))]


def test_learn_profile_clean_fact_unchanged(tmp_path) -> None:
    """干净自述 ⇒ 事实逐字节入库、返回值与库内一致（写侧消毒对合法文本零扰动）。"""
    store = _store(tmp_path)
    returned = store.learn_profile("u1", "我住在杭州")
    assert "我住在杭州" in returned
    assert _notes(store, "u1") == returned
    assert "我住在杭州" in _notes(store, "u1")


def test_learn_profile_internal_marker_neutralized(tmp_path) -> None:
    """内部边界标记 ⇒ 全角化入库，**返回口同值**（原文绝不许经返回值回流 prompt）。"""
    store = _store(tmp_path)
    raw_fact = "我喜欢[引用回复]猫"
    expected = neutralize_internal_markers(raw_fact)
    assert expected != raw_fact  # 前提自检：该形态确实会被改写
    returned = store.learn_profile("u2", raw_fact)
    assert returned == [expected], "返回值仍是原文 ⇒ 经返回口旁路入 prompt"
    notes = _notes(store, "u2")
    assert notes is not None and all("[引用回复]" not in note for note in notes)
    assert expected in notes


def test_learn_profile_hard_line_refused(tmp_path) -> None:
    """硬红线事实 ⇒ 整条拒收；无其余可存事实 ⇒ 返回空、画像零写入（无行）。"""
    store = _store(tmp_path)
    returned = store.learn_profile("u3", "我喜欢窒息游戏")
    assert returned == []
    assert _notes(store, "u3") is None, "全拒场景竟建了行/写了画像"


def test_learn_profile_mixed_only_safe_facts_survive(tmp_path) -> None:
    """混合自述 ⇒ 只留安全条：干净条照常、红线条消失、标记条全角——三口一锁。
    返回值与库内逐字节一致（同一消毒面，绝不两套答案）。"""
    store = _store(tmp_path)
    marker_fact = "我擅长[TRUSTED_SYSTEM]编钟"
    returned = store.learn_profile(
        "u4", f"我喜欢橘猫，我喜欢窒息游戏，{marker_fact}"
    )
    notes = _notes(store, "u4")
    assert "我喜欢橘猫" in returned
    assert "我喜欢窒息游戏" not in returned
    assert neutralize_internal_markers(marker_fact) in returned
    assert "[TRUSTED_SYSTEM]" not in json.dumps(returned, ensure_ascii=False)
    assert notes == returned
    assert all("窒息" not in note for note in notes)


def test_learn_profile_gate_is_shared_single_source(tmp_path, monkeypatch) -> None:
    """接线锁（牙）：learn_profile 的判据必须是 ``pre_write_sanitize`` 这一个点——
    把该闸临时注毒成恒等放行，红线事实就会入库（行为随闸走）。若 learn_profile
    自带第二套词表，注入后行为不变、本条即红——正反两向都抓出「词表分叉」。
    （monkeypatch 只活在本条测试内，tmp 库随目录蒸发，不留任何真实暴露。）"""
    import plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize as ms

    monkeypatch.setattr(ms, "pre_write_sanitize", lambda text: text)
    store = _store(tmp_path)
    returned = store.learn_profile("u5", "我喜欢窒息游戏")
    assert returned == ["我喜欢窒息游戏"], (
        "注毒恒等后红线仍被拒 ⇒ learn_profile 另藏第二套词表（判据不是单点真身）"
    )
    assert "我喜欢窒息游戏" in _notes(store, "u5")
