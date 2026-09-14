"""G-11 印象标签年龄淡出回归（审查 G-11，2026-09-15）。

缺陷：印象标签一次性打标永久保留、无淡出，数月前的陈旧标签永久污染画像。
修法：标签带最近打标时间（impression_tag_times 列，PRAGMA/ALTER 幂等迁移），
snapshot() 出口按 §3 半衰口径 ×2 过滤超龄标签（保留在库可溯，不物理删）。
覆盖：新标签注入 / 超龄不注入 / 未超龄混合 / 库内保留 / 滚动强化再打标 /
存量行 updated_at 锚点回退 / 缺列迁移幂等。
数值规范零触碰：本文件只断言标签注入判据，不断言任何好感度数值语义变更
（数值回归由 test_affinity.py / test_affinity_numerical.py 承担）。
"""

from __future__ import annotations

import json
import sqlite3

from plugins.bot_unified_runtime.character.affinity import DynamicAffinityStore

_DAY_SECONDS = 86400.0


class _StepClock:
    """可手动推进的注入时钟（秒）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _read_raw_tag_columns(db_path: object, sender_id: str) -> tuple[list[str], dict[str, str]]:
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute(
            "SELECT impression_tags, impression_tag_times FROM user_affinity WHERE sender_id = ?",
            (sender_id,),
        ).fetchone()
    assert row is not None
    return json.loads(str(row[0] or "[]")), json.loads(str(row[1] or "{}"))


def test_fresh_tag_is_injected(tmp_path) -> None:
    """①新标签注入：达标即打标且未超龄，正常进入 snapshot 注入面。"""
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_StepClock())
    for _ in range(3):
        store.observe("u1", "positive")  # 友善（positive≥3，有效龄 60 天）
    tags = store.snapshot("u1")["tags"]
    assert "友善" in tags


def test_expired_tag_not_injected_but_retained_in_db(tmp_path) -> None:
    """②超龄标签不注入：insult 档有效龄 15×2=30 天，超龄即从注入面消失；
    库内物理保留（标签名 + 打标时间都在），可溯不删。"""
    clock = _StepClock()
    db = tmp_path / "affinity.sqlite3"
    store = DynamicAffinityStore(db, clock=clock)
    for _ in range(2):
        store.observe("u1", "insult")  # 口无遮拦（insult≥2）
    assert "口无遮拦" in store.snapshot("u1")["tags"]
    clock.advance(30 * _DAY_SECONDS)  # 恰在有效龄边界：未超龄
    assert "口无遮拦" in store.snapshot("u1")["tags"]
    clock.advance(1 * _DAY_SECONDS)  # 超过 30 天：不再注入
    assert "口无遮拦" not in store.snapshot("u1")["tags"]
    raw_tags, raw_times = _read_raw_tag_columns(db, "u1")
    assert "口无遮拦" in raw_tags
    assert "口无遮拦" in raw_times


def test_mixed_fresh_and_expired_tags(tmp_path) -> None:
    """③未超龄混合正常：同批标签里只有超龄者被过滤，其余照常注入。"""
    clock = _StepClock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    for _ in range(3):
        store.observe("u1", "positive")  # 友善：有效龄 60 天
    for _ in range(2):
        store.observe("u1", "insult")  # 口无遮拦：有效龄 30 天
    clock.advance(40 * _DAY_SECONDS)  # 口无遮拦已超龄、友善未超龄
    tags = store.snapshot("u1")["tags"]
    assert "友善" in tags
    assert "口无遮拦" not in tags


def test_reinforced_tag_refreshes_and_neutral_does_not_revive(tmp_path) -> None:
    """滚动强化：标签年龄=最近一次同类行为时间。超龄后再犯（同类行为）即
    重新注入；中性消息不得给超龄标签续命。"""
    clock = _StepClock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    for _ in range(2):
        store.observe("u1", "insult")
    clock.advance(40 * _DAY_SECONDS)
    assert "口无遮拦" not in store.snapshot("u1")["tags"]
    store.observe("u1", "insult")  # 计数早已达标，同类行为刷新打标时间
    assert "口无遮拦" in store.snapshot("u1")["tags"]
    clock.advance(40 * _DAY_SECONDS)
    store.observe("u1", "neutral")  # 非同类行为：不刷新
    assert "口无遮拦" not in store.snapshot("u1")["tags"]


def test_legacy_row_falls_back_to_updated_at_anchor(tmp_path) -> None:
    """存量行锚点回退：迁移前的标签无时间戳条目时，按行级 updated_at（最后
    互动时间）定龄——活跃用户的既有标签不误伤，长期沉寂行的陈旧标签淡出。"""
    clock = _StepClock()
    db = tmp_path / "affinity.sqlite3"
    store = DynamicAffinityStore(db, clock=clock)
    store.observe("u1", "positive")  # 建行，updated_at = 当前时钟
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "UPDATE user_affinity SET impression_tags = ?, impression_tag_times = '{}' WHERE sender_id = 'u1'",
            (json.dumps(["友善", "爱抱怨"], ensure_ascii=False),),
        )
    # 锚点新近：存量标签视为未超龄
    assert set(store.snapshot("u1")["tags"]) == {"友善", "爱抱怨"}
    # 行级沉寂 90 天（> 60 天有效龄）：陈旧标签按最后互动龄淡出
    clock.advance(90 * _DAY_SECONDS)
    assert store.snapshot("u1")["tags"] == []
    # 库内仍全量保留
    raw_tags, _raw_times = _read_raw_tag_columns(db, "u1")
    assert set(raw_tags) == {"友善", "爱抱怨"}


def test_schema_migration_adds_tag_times_column_idempotent(tmp_path) -> None:
    """缺列迁移：旧版表（无 impression_tag_times）打开即补列，重复打开幂等，
    迁移后标签读写链路完整。"""
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            """
            CREATE TABLE user_affinity (
                sender_id TEXT PRIMARY KEY,
                affinity REAL NOT NULL DEFAULT 0.1,
                interaction_count INTEGER NOT NULL DEFAULT 0,
                positive_count INTEGER NOT NULL DEFAULT 0,
                negative_count INTEGER NOT NULL DEFAULT 0,
                tease_count INTEGER NOT NULL DEFAULT 0,
                insult_count INTEGER NOT NULL DEFAULT 0,
                nickname TEXT NOT NULL DEFAULT '',
                impression_tags TEXT NOT NULL DEFAULT '[]',
                profile_notes TEXT NOT NULL DEFAULT '[]',
                counter_day_index INTEGER NOT NULL DEFAULT -1,
                day_counters TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO user_affinity (sender_id, updated_at) VALUES ('u9', '2026-01-01T00:00:00Z')"
        )
    first = DynamicAffinityStore(db, clock=_StepClock())  # 迁移：补列
    second = DynamicAffinityStore(db, clock=_StepClock())  # 幂等：不因列已存在报错
    assert second.snapshot("u9")["tags"] == []
    for _ in range(3):
        first.observe("u9", "positive")
    assert "友善" in first.snapshot("u9")["tags"]
