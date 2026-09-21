"""2026-09-21 深读波 D1-7 回归锁：亲密路由状态机的线程安全。

病灶：进程级单例 ``SHARED_CONTENT_ROUTE_ENGINE._sessions``（``OrderedDict``）在
``_state`` 里被插入 / ``move_to_end`` / ``popitem`` 三类结构变更，而公开方法
``observe_turn / route_verdict / consume_reply / pinned_mode / apply_manual`` 还要
「取态→改分数→写回」——全程无锁。同层三处共享态（``base_router._ROUTE_CACHE``
带 ``_ROUTE_CACHE_LOCK``、``group_cache``、``parrot``）都各持一把锁，唯本件例外；
而能力确实跑在线程池（``pipeline.offload_capability`` 有界 ``ThreadPoolExecutor``，
默认 8 worker），且 pipeline 自身注释就写着「管线能力跑在线程池，读写必须持锁」。
``fail-open`` 会把竞态炸出的 ``RuntimeError`` 吞成「静默漏判亲密路由」。

修法＝公开方法整段上可重入锁（``_synchronized`` 装饰器）。本锁三件事：
①结构上确认五路全在锁内且判定不靠猜（记账式假锁）；②真并发压测不炸且容量上限
守住；③锁可重入（``_state`` 在被包裹的方法内部再进同一把锁不得自锁）。
"""
from __future__ import annotations

import threading

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    _SESSION_CAP,
    ContentRouteEngine,
)

_PUBLIC_STATE_METHODS = (
    "observe_turn",
    "route_verdict",
    "consume_reply",
    "pinned_mode",
    "apply_manual",
)


class _RecordingLock:
    """记账式假锁：只数进出次数，用于证明「调用路径真的过了锁」。"""

    def __init__(self) -> None:
        self.depth = 0
        self.max_depth = 0
        self.entries = 0

    def __enter__(self) -> object:
        self.entries += 1
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.depth -= 1
        return False


@pytest.mark.parametrize("name", _PUBLIC_STATE_METHODS)
def test_every_public_state_touching_method_is_locked(name: str) -> None:
    method = getattr(ContentRouteEngine, name)
    assert getattr(method, "__content_route_locked__", False) is True, (
        f"{name} 未过 _synchronized：共享态读写仍可能裸奔"
    )
    assert callable(getattr(method, "__wrapped__", None)), f"{name} 装饰器吞掉了原实现"


def test_lock_is_actually_acquired_on_call() -> None:
    engine = ContentRouteEngine()
    engine._lock = _RecordingLock()  # type: ignore[attr-defined]
    engine.observe_turn("private:1", message_text="你好", config=None)
    assert engine._lock.entries == 1, engine._lock.entries
    assert engine._lock.depth == 0, "出方法时未释放＝锁泄漏"


def test_lock_is_reentrant_for_inner_state_helper() -> None:
    """``_state`` 在公开方法内部取态：锁必须可重入，否则第一次调用就自锁死。"""
    engine = ContentRouteEngine()
    assert isinstance(engine._lock, type(threading.RLock())) or hasattr(engine._lock, "_count")
    engine.apply_manual("group:9_1", "intimate", config=None)
    assert engine.pinned_mode("group:9_1", config=None) == "intimate"


def test_concurrent_hammer_keeps_engine_alive_and_bounded() -> None:
    """8 线程 × 混合操作压测：不得抛异常、会话表不得越过容量上限。"""
    engine = ContentRouteEngine()
    errors: list[BaseException] = []
    rounds = 120

    def worker(worker_id: int) -> None:
        try:
            for i in range(rounds):
                key = f"group:9{worker_id}_{i % 37}"
                engine.observe_turn(key, message_text="这个姿势好色，想看裸体", config=None)
                engine.route_verdict(key, config=None)
                engine.consume_reply(key, "好呀", config=None)
                engine.pinned_mode(key, config=None)
                if i % 5 == 0:
                    engine.apply_manual(key, "intimate", config=None)
        except BaseException as exc:  # noqa: BLE001 - 压测席：任何异常都是证据
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "线程未结束＝疑似自锁"
    assert not errors, errors[:3]
    assert len(engine._sessions) <= _SESSION_CAP, len(engine._sessions)
