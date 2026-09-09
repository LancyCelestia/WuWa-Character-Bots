"""守岸人失败话术池回归：池完整性 + 会话内轮换不重复。"""

from __future__ import annotations

import random

from plugins.bot_unified_runtime.capabilities.chat import (
    _PERSONA_FAILURE_MESSAGES,
    persona_failure_message,
)


def test_pool_shape() -> None:
    assert len(_PERSONA_FAILURE_MESSAGES) >= 10
    # 无重复条目、无空串、每条不超过 40 字。
    assert len(set(_PERSONA_FAILURE_MESSAGES)) == len(_PERSONA_FAILURE_MESSAGES)
    assert all(isinstance(m, str) and m.strip() for m in _PERSONA_FAILURE_MESSAGES)
    assert all(len(m) <= 40 for m in _PERSONA_FAILURE_MESSAGES)


def test_rotation_covers_all_entries_without_repeat(monkeypatch) -> None:
    # 轮换游标回归：固定随机数后，同会话连续 12 次应恰好覆盖全部条目。
    monkeypatch.setattr(random, "randrange", lambda n: 0)
    session = "s1"
    seen = [
        persona_failure_message(session)
        for _ in range(len(_PERSONA_FAILURE_MESSAGES))
    ]
    assert len(set(seen)) == len(seen)
    assert set(seen) == set(_PERSONA_FAILURE_MESSAGES)
