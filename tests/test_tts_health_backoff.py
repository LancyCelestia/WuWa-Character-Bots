"""健康退避真闸（bot.tts，M-09 P1 / U-20 裁定=接线不删净，2026-09-19 统一波 T57）。

审计实证（`report-T29.md` M-09，四席以上独立同判）：
- `_HEALTH_BACKOFF_SECONDS/_last_failure_at` **写 3 读 0**（全仓零读取端）——
  宣称的「连续失败节流」是幻影能力：引擎挂死时每个请求都白打一次完整 HTTP
  （loopback 拒绝即时失败、URL 漂远端时每请求付满 60s 超时且无上限）；
- `acceptance-manual:478` ⑤排障指引指向这个不存在的闸。

本席按 U-20 推荐项**接线**（不删净）：
- 退避检查放在唯一 HTTP 入口 `_request_tts` 之前（`synthesize` 内、缓存查找
  之后）：**冷却窗内直接快速失败，不发 HTTP**；缓存命中不受闸影响（命中本就
  不打服务）；
- 快速失败原因固定以「服务不可达」开头 → 走既有 `_FAILURE_KINDS` 前缀映射，
  挂 ``OperationalIssue(kind="tts_service_unreachable", retryable=True)``；
- 窗满自动放行（**非永久拉黑**）；真成功把状态清零；快速失败**不刷新**窗口
  （否则持续重试会把 30s 退避变成永久拉黑）；
- 阈值=模块常量 ``_HEALTH_BACKOFF_SECONDS``，不加新 config 键；
- 线程安全：能力跑在 offload 线程池，「失败时刻+原因」必须成对读写——GIL 只
  保证单条赋值原子，保证不了配对一致，故模块级锁包住全部状态读写；临界区只有
  内存操作，HTTP 绝不持锁。

已知取舍（与闸共存的结构性边界）：「先查闸、后打请求」不是原子语义，窗沿上
并发的前几个请求都可能真打引擎——本闸是成本节流不是硬信号量，为它把锁横跨
HTTP 会把全部合成串行化，不可接受。

全离线，零网络零落盘（落盘只写 tmp_path）。
"""

from __future__ import annotations

import io
import sys
import time
import wave
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    RefAudio,
    TtsParams,
    synthesize,
)

_API_URL = "http://127.0.0.1:9880"


class _FakeConnectError(Exception):
    """假连接异常（`_request_tts` 按异常类型名记入失败原因）。"""


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav（能过 `_inspect_wav_bytes` 体检闸的产物形态）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _params() -> TtsParams:
    return TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )


@pytest.fixture(autouse=True)
def _isolate_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例干净缓存与退避状态（进程级全局，不隔离会跨用例串味）。"""
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


def _install_failing_httpx(
    monkeypatch: pytest.MonkeyPatch, *, fail_first: int, wav: bytes
) -> list[int]:
    """假 httpx：前 ``fail_first`` 次 post 抛连接异常，其后回真 wav。

    返回 post 尝试计数器——退避闸的核心断言就是「窗内不产生新尝试」。
    """
    attempts: list[int] = []

    class _FakeResponse:
        status_code = 200
        content = wav
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {}

    class _FakeClient:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, json: dict[str, object]) -> _FakeResponse:
            attempts.append(1)
            if len(attempts) <= fail_first:
                raise _FakeConnectError("connection refused")
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=_FakeClient))
    return attempts


def _ref(tmp_path: Path) -> RefAudio:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return RefAudio(path=str(path), text="你好", lang="zh")


def _call(tmp_path: Path, ref: RefAudio, *, cache_enabled: bool = False):
    return synthesize(
        api_url=_API_URL,
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=tmp_path / "out",
        cache_enabled=cache_enabled,
    )


def test_second_failure_within_window_fast_fails_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED 核心：冷却窗内第二次合成必须快速失败，绝不再打一次注定挂的服务。"""
    attempts = _install_failing_httpx(monkeypatch, fail_first=1, wav=_wav_bytes())
    ref = _ref(tmp_path)

    first_path, first_reason = _call(tmp_path, ref)
    assert first_path is None
    assert "不可达" in first_reason
    assert len(attempts) == 1

    second_path, second_reason = _call(tmp_path, ref)
    assert len(attempts) == 1, f"退避窗内竟又真打了一次服务（共 {len(attempts)} 次）"
    assert second_path is None
    # 快速失败必须能和普通失败区分（带退避标记），且仍以「服务不可达」开头
    # 走既有 issue 前缀映射。
    assert second_reason.startswith("服务不可达")
    assert "退避" in second_reason or "冷却" in second_reason


def test_backoff_fast_fail_maps_to_retryable_unreachable_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """快速失败挂既有 ``tts_service_unreachable``（可重试）——中央告警链照常可见。"""
    _install_failing_httpx(monkeypatch, fail_first=1, wav=_wav_bytes())
    ref = _ref(tmp_path)
    _call(tmp_path, ref)
    _second_path, second_reason = _call(tmp_path, ref)
    assert "退避" in second_reason or "冷却" in second_reason

    message = IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id="",
        plain_text="说 你好",
    )
    issue = tts_mod._failure_issue(message, second_reason)
    assert issue.kind == "tts_service_unreachable"
    assert issue.retryable is True
    assert issue.safe_summary


def test_window_expiry_recovers_and_success_resets_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全周期：失败进闸 → 窗内快速失败（不刷新窗）→ 窗满自动恢复 → 成功清零。"""
    attempts = _install_failing_httpx(monkeypatch, fail_first=1, wav=_wav_bytes())
    ref = _ref(tmp_path)

    first_path, _first_reason = _call(tmp_path, ref)
    assert first_path is None and len(attempts) == 1
    stamp_after_first = tts_mod._last_failure_at
    assert stamp_after_first > 0.0, "真实失败必须记账（进冷却窗）"

    second_path, second_reason = _call(tmp_path, ref)
    assert second_path is None
    assert len(attempts) == 1, "窗内不得再打服务"
    assert "退避" in second_reason or "冷却" in second_reason
    assert tts_mod._last_failure_at == stamp_after_first, (
        "快速失败不得刷新退避窗——否则持续重试会让 30s 退避变成永久拉黑"
    )

    # 窗满（把失败时刻拨回窗界之外）→ 自动恢复放行，且这次真能成功。
    monkeypatch.setattr(
        tts_mod,
        "_last_failure_at",
        time.monotonic() - float(tts_mod._HEALTH_BACKOFF_SECONDS) - 1.0,
    )
    third_path, third_reason = _call(tmp_path, ref)
    assert third_path is not None, f"窗满必须恢复放行：{third_reason}"
    assert third_reason == ""
    assert len(attempts) == 2, "恢复后的第一次合成应真打服务"
    assert tts_mod._last_failure_at == 0.0, "真成功必须清零退避状态"
    assert tts_mod._last_failure_reason == ""

    # 清零后的新一轮失败重新进入完整退避周期（非累积性永久拉黑）。
    fresh = _install_failing_httpx(monkeypatch, fail_first=1, wav=_wav_bytes())
    fourth_path, _r = _call(tmp_path, ref)
    assert fourth_path is None and len(fresh) == 1
    fifth_path, fifth_reason = _call(tmp_path, ref)
    assert fifth_path is None
    assert "退避" in fifth_reason or "冷却" in fifth_reason
    assert len(fresh) == 1, "新一轮失败必须重新进闸"


def test_backoff_never_blocks_cache_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """退避闸只省注定失败的 HTTP：已合成的缓存命中照常复用（闸在缓存查找之后）。"""
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_kw: _wav_bytes())
    ref = _ref(tmp_path)
    path1, reason1 = _call(tmp_path, ref, cache_enabled=True)
    assert path1 is not None and reason1 == ""

    # 模拟服务刚失败（冷却窗激活）。
    monkeypatch.setattr(tts_mod, "_last_failure_at", time.monotonic())
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "服务不可达：ConnectError")
    path2, reason2 = _call(tmp_path, ref, cache_enabled=True)
    assert path2 == path1 and reason2 == "", "缓存命中不得被退避闸拦下"
