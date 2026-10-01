"""记忆吸收器（absorber）守门键行为锁（席 S-ABSORBER，2026-09-29）。

判什么：记忆/知识吸收这条腿有两条写入入口，都由**同一枚**总闸
``bot_memory_bus_enabled``（config.py:``bot_memory_bus_enabled``）把关——闸的**唯一**
消费点是 ``memory_bus_v2.build_memory_bus``（经 ``settings_from_config`` 现读）：
关闸⇒返回 ``None``、连库文件都不建（别处不许再判第二次，也不许绕过它自建总线）。

本锁钉的是「关闸时吸收器**真的不干活**」的可观测面，且与既有锁不重叠：

- 关态：``build_memory_bus(关) is None`` 且**不落库文件**（闸关⇒吸收器根本拿不到），
  并把这份 ``None`` 喂进视觉→记忆吸收入口 ``absorb_preprocessed_summary``，断言它是
  彻底的空操作（返回 ``None``、一次都不碰 ``absorb``）。既有
  ``test_memory_bus_v2.py::test_build_memory_bus_none_when_disabled`` 停在
  ``build_memory_bus`` 一步；本锁**再往下走一层**到吸收器函数体，证明关闸后写入腿
  静默，而不仅是构造器吐 None。
- 开态（反证、给锁牙口）：喂一枚记账用的假总线，``absorb_preprocessed_summary``
  必须**恰好调用一次** ``absorb``——否则本锁只是"永远 None"的空夹具。假总线不碰磁盘，
  全程离线，绝不开真库（红线：不写生产 ``ChatBot_Runtime/data``）。

不走 ``/bot reply`` 命令面，故无需 monkeypatch ``shared_reply_policy_store``。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    build_memory_bus,
)
from plugins.bot_unified_runtime.domains.vision.capabilities.modality_preprocessing import (
    absorb_preprocessed_summary,
)


def _guard_config(*, enabled: bool, db_path: str) -> SimpleNamespace:
    """只放 ``build_memory_bus`` / ``settings_from_config`` 真会 getattr 的两键。"""
    return SimpleNamespace(
        bot_memory_bus_enabled=enabled,
        bot_memory_db_path=db_path,
    )


class _RecordingBus:
    """记账用的假总线：``absorb`` 记下调用并回一个哨兵，绝不落库。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def absorb(self, **kwargs: object) -> str:
        self.calls.append(str(kwargs.get("text", "")))
        return "absorbed-sentinel"


def test_guard_off_yields_no_absorber_and_vision_leg_is_inert(tmp_path: Path) -> None:
    db = tmp_path / "memory.sqlite3"
    # 闸关：唯一消费点 build_memory_bus 返回 None，且连文件都不该建（不干活到落盘层）。
    assert build_memory_bus(_guard_config(enabled=False, db_path=str(db))) is None
    assert not db.exists(), "关闸却建了库文件 ⇒ 吸收器并未真正静默"

    # 把关闸产出的那份 None 喂进视觉→记忆吸收入口：必须彻底空操作、直接返回 None。
    # （闸关 ⇒ build_memory_bus 交出的就是 None，写腿拿到 None 只能退让，不碰任何 absorb。）
    outcome = absorb_preprocessed_summary(
        None,
        owner_id="u1",
        subject_user_id="u1",
        session_id="group_123:456",
        summary="她这轮看了张图，材料应当沉淀进记忆",
    )
    assert outcome is None, "关闸后视觉吸收入口仍返回非 None ⇒ 写腿没被闸住"


def test_guard_on_actually_drives_absorb() -> None:
    """反证（锁的牙口）：有总线时吸收入口确实调 absorb，本锁不是"永远 None"的空夹具。"""
    spy = _RecordingBus()
    outcome = absorb_preprocessed_summary(
        spy,
        owner_id="u1",
        subject_user_id="u1",
        session_id="group_123:456",
        summary="材料应当沉淀进记忆",
    )
    assert outcome == "absorbed-sentinel", "开态没把候选交给 absorb ⇒ 本锁在空跑"
    assert spy.calls == ["材料应当沉淀进记忆"], spy.calls


def test_guard_on_empty_summary_short_circuits_without_absorb() -> None:
    """诚实边界：空材料不配惊动 absorb（在闸内、库外先退让），别把空串洗成事实。"""
    spy = _RecordingBus()
    assert absorb_preprocessed_summary(
        spy, owner_id="u1", subject_user_id="u1",
        session_id="group_123:456", summary="   ",
    ) is None
    assert spy.calls == []
