from __future__ import annotations

from plugins.bot_unified_runtime.runtime.parrot import ParrotDetector


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_three_distinct_senders_trigger_tease() -> None:
    clock = _FakeClock()
    detector = ParrotDetector(clock=clock, threshold=3)

    assert detector.detect(session_id="g:1", sender_id="a", text="6") is None
    assert detector.detect(session_id="g:1", sender_id="b", text="6 ") is None  # 去空白后同文本
    tease = detector.detect(session_id="g:1", sender_id="c", text="6")
    assert tease is not None and "复读机" in tease


def test_same_sender_repeat_does_not_trigger() -> None:
    clock = _FakeClock()
    detector = ParrotDetector(clock=clock, threshold=3)
    for _ in range(4):
        assert detector.detect(session_id="g:1", sender_id="a", text="6") is None


def test_cooldown_prevents_repeat_teasing() -> None:
    clock = _FakeClock()
    detector = ParrotDetector(clock=clock, threshold=2, cooldown_seconds=300.0)
    detector.detect(session_id="g:1", sender_id="a", text="冲！")
    first = detector.detect(session_id="g:1", sender_id="b", text="冲！")
    assert first is not None

    clock.advance(10.0)
    detector.detect(session_id="g:1", sender_id="c", text="冲！")
    detector.detect(session_id="g:1", sender_id="d", text="冲！")
    assert detector.detect(session_id="g:1", sender_id="e", text="冲！") is None

    clock.advance(400.0)
    detector.detect(session_id="g:1", sender_id="f", text="冲！")
    second = detector.detect(session_id="g:1", sender_id="g", text="冲！")
    assert second is not None


def test_bot_self_and_long_text_are_ignored() -> None:
    clock = _FakeClock()
    detector = ParrotDetector(clock=clock, threshold=2)
    long_text = "x" * 200
    assert detector.detect(session_id="g", sender_id="bot", text="hi", is_bot_self=True) is None
    assert detector.detect(session_id="g", sender_id="a", text=long_text) is None
