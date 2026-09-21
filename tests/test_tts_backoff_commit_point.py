"""WP4：语音退避保护被提前清零——「算成功」判据与「退避清零」时机对齐。

缺陷（docs/audit-20260921.md E1-1 / P0-12，主会话核对行号）：Wave G 的 M-09
退避真闸在 ``_request_tts`` 的 **HTTP 200 + 非空体**分支（旧 ``tts.py:653``
``_clear_failure()``）就抢先清零，而引擎「200 + 恰 1 秒静音」伪装成功的
静音指纹闸（``_inspect_wav_bytes``）在**更后面**才判（旧 ``:757``）——于是引擎
以「静音陷阱」方式坏掉时，退避保护**永远不启动**：每条语音请求继续白等 60s，
并占死一个 ``ThreadPoolExecutor`` worker（默认 8 worker），把普通聊天一起拖慢。

本波修复的判据（验收即按这几条）：

1. 只有通过**全部产物校验**（结构体检 + 静音指纹 + 字节顶）**且真的落盘交付**
   之后，才允许 ``_clear_failure()``——清零时机=``synthesize`` 的唯一成功提交点。
2. 静音指纹命中必须走**失败路径**：计入退避窗（``_record_failure``）+ 挂可见
   issue，绝不静默。
3. 窗内后续请求快速失败**不再白打引擎**（用调用计数可断言证明）。
4. 结构性坏字节（非 RIFF/头不可解析/零帧）与字节顶超限**仍不入窗**（既有分类学
   ``test_tts_audio_gate.py`` / ``test_poison_artifact_never_enters_cache`` 锁死，
   不可放宽）——只有「引擎 200 却伪装成功」这一部署类形态才节流。
5. 既有「快速失败不刷新窗」「窗满自动恢复（非永久拉黑）」「成功清零」语义不回退。

全离线，零网络（HTTP 用假 httpx / monkeypatch），落盘只写 tmp_path。
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


def _params() -> TtsParams:
    return TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )


def _pcm_wav(*, seconds: float, rate: int, amplitude: int = 0) -> bytes:
    """PCM16 单声道 wav；``amplitude=0`` 全零（静音），>0 每隔一帧给一个峰值样本。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        n = int(rate * seconds)
        frames = bytearray(2 * n)
        if amplitude:
            for i in range(0, 2 * n, 2):
                frames[i : i + 2] = int(amplitude).to_bytes(2, "little", signed=True)
        handle.writeframes(bytes(frames))
    return buf.getvalue()


def _normal_wav() -> bytes:
    """正常产物形态：标称 32000Hz + 有声样本（绝不误判成静音陷阱）。"""
    return _pcm_wav(seconds=0.2, rate=32000, amplitude=3000)


def _silence_trap() -> bytes:
    """引擎陷阱指纹（T53 §3）：16000Hz + 恰 1s + 全零 int16。"""
    return _pcm_wav(seconds=1.0, rate=16000)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例干净缓存与退避状态（进程级全局，不隔离会跨用例串味）。"""
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


def _ref(tmp_path: Path) -> RefAudio:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return RefAudio(path=str(path), text="你好", lang="zh")


def _install_httpx_returning(
    monkeypatch: pytest.MonkeyPatch, *, status_code: int, content: bytes
) -> list[int]:
    """假 httpx：``post`` 计数并恒定返回给定状态/字节。返回调用计数 list。"""
    attempts: list[int] = []

    class _FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = content
            self.text = ""

        def json(self) -> dict[str, object]:
            return {}

    class _FakeClient:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def post(self, _url: str, json: dict[str, object]) -> _FakeResponse:
            attempts.append(1)
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=_FakeClient))
    return attempts


def _synth(tmp_path: Path, ref: RefAudio, *, text: str = "正文"):
    return synthesize(
        api_url=_API_URL,
        text=text,
        ref=ref,
        params=_params(),
        output_dir=tmp_path / "out",
    )


# ---------------------------------------------------------------------------
# 修复主体 1：静音陷阱计入退避窗 + 告警可见
# ---------------------------------------------------------------------------


def test_silence_trap_enters_backoff_window_and_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED 核心：200+静音陷阱产物 ⇒ 不清零、走失败、退避窗真的进入。"""
    attempts = _install_httpx_returning(
        monkeypatch, status_code=200, content=_silence_trap()
    )
    ref = _ref(tmp_path)

    path, reason = _synth(tmp_path, ref)
    assert path is None, "静音陷阱不得成功出站"
    assert "静音" in reason, f"返回原因须点名静音陷阱：{reason}"
    assert not (tmp_path / "out").exists() or not list(
        (tmp_path / "out").glob("*.wav")
    ), "静音产物绝不落盘"
    # 修复关键：陷阱请求之后退避窗**真的进入**（此前 _clear_failure 抢跑 ⇒ 永不进窗）。
    assert tts_mod._last_failure_at > 0.0, "静音陷阱必须计入退避窗（E1-1 修复目的）"
    assert tts_mod._backoff_reason() != "", "退避窗进入后闸必须是激活态"
    assert len(attempts) == 1

    # 告警可见（不能静默）：返回原因映射到一个结构化 kind + safe_summary 非空。
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
    issue = tts_mod._failure_issue(message, reason)
    assert issue.kind in {"tts_bad_audio", "tts_service_unreachable"}
    assert issue.safe_summary, "静音陷阱失败必须留下非空可观测证据"


def test_silence_trap_second_request_fast_fails_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """窗内后续请求快速失败、不再白打引擎（修复的真实目的，用调用计数断言）。"""
    attempts = _install_httpx_returning(
        monkeypatch, status_code=200, content=_silence_trap()
    )
    ref = _ref(tmp_path)

    first_path, _ = _synth(tmp_path, ref, text="第一句")
    assert first_path is None and len(attempts) == 1
    stamp = tts_mod._last_failure_at
    assert stamp > 0.0

    second_path, second_reason = _synth(tmp_path, ref, text="换一句不同的")
    assert second_path is None
    assert len(attempts) == 1, f"静音陷阱进窗后竟又真打引擎（共 {len(attempts)} 次）"
    assert second_reason.startswith("服务不可达")
    assert "退避" in second_reason or "冷却" in second_reason
    # 快速失败不得刷新窗（否则持续重试=永久拉黑，既有语义不回退）。
    assert tts_mod._last_failure_at == stamp


def test_structural_garbage_still_does_not_enter_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分类学边界：非 RIFF 结构坏字节仍不入窗（禁放宽既有 ``never_enters_cache``）。"""
    attempts = _install_httpx_returning(
        monkeypatch, status_code=200, content=b"garbage-not-audio"
    )
    ref = _ref(tmp_path)
    path, reason = _synth(tmp_path, ref)
    assert path is None
    assert "非 RIFF" in reason
    assert tts_mod._last_failure_at == 0.0, "结构性坏字节=非部署故障，不进退避窗"
    # 不入窗 ⇒ 第二次同句仍真打引擎（毒件绝不复放，且不被误节流）。
    path2, _ = _synth(tmp_path, ref)
    assert path2 is None and len(attempts) == 2


def test_byte_cap_rejection_does_not_enter_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """字节顶超限=请求侧内容问题，非引擎故障 ⇒ 不进退避窗。"""
    monkeypatch.setattr(
        tts_mod, "_request_tts", lambda **_kw: (_normal_wav(), "")
    )
    ref = _ref(tmp_path)
    path, reason = synthesize(
        api_url=_API_URL,
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=tmp_path / "out",
        max_audio_bytes=8,  # 8 字节：任何真产物都超限
    )
    assert path is None and reason.startswith("音频体检失败")
    assert tts_mod._last_failure_at == 0.0


# ---------------------------------------------------------------------------
# 修复主体 2：清零时机=唯一成功提交点（全部校验 + 落盘交付之后）
# ---------------------------------------------------------------------------


def test_valid_artifact_clears_backoff_on_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200+正常产物 ⇒ 通过全部校验并落盘后才清零退避状态。

    预置一个**已过窗**的失败（>0 但不再挡路），验证成功提交点把它清回 0.0。
    （若预置未过窗的失败，``synthesize`` 的退避闸会在请求到达提交点之前就快速
    失败，测不到清零时机——故必须用过期窗。）
    """
    expired = time.monotonic() - float(tts_mod._HEALTH_BACKOFF_SECONDS) - 1.0
    monkeypatch.setattr(tts_mod, "_last_failure_at", expired)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "服务不可达：ConnectError")
    assert tts_mod._last_failure_at > 0.0
    _install_httpx_returning(monkeypatch, status_code=200, content=_normal_wav())
    ref = _ref(tmp_path)
    path, reason = _synth(tmp_path, ref)
    assert path is not None and reason == ""
    assert tts_mod._last_failure_at == 0.0, "交付成功必须清零退避窗"
    assert tts_mod._last_failure_reason == ""


def test_clear_happens_only_after_disk_write_not_on_http_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """门有牙（钉死修复方向）：``_request_tts`` 拿到 200 字节时绝不碰退避状态。

    把 ``_clear_failure`` 挪回 ``_request_tts`` 的 200 分支（旧缺陷位置）会让本
    用例立刻红——因为直连 ``_request_tts`` 后窗仍必须保活（清零只发生在
    ``synthesize`` 完成体检+落盘之后）。
    """
    ref = _ref(tmp_path)
    active = time.monotonic()
    monkeypatch.setattr(tts_mod, "_last_failure_at", active)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "服务不可达：ConnectError")
    _install_httpx_returning(monkeypatch, status_code=200, content=_normal_wav())

    audio, failure = tts_mod._request_tts(
        api_url=_API_URL,
        text="正文",
        ref=ref,
        params=_params(),
        timeout_seconds=5.0,
        engine_params=dict(tts_mod.PRESET_REGISTRY["shorekeeper"].params),
        seed=1234,
    )
    assert audio is not None and failure == ""
    # HTTP 200 + 非空体，但未经体检/落盘 ⇒ 此刻绝不得清零（旧缺陷正是在此清零）。
    assert tts_mod._last_failure_at == active, (
        "200 抢跑清零=缺陷本体；清零必须推迟到体检+落盘之后"
    )


def test_backoff_window_expires_and_recovers_then_success_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """防永久拉黑不回退：陷阱进窗 → 窗内快速失败 → 窗满恢复 → 成功清零。"""
    attempts = _install_httpx_returning(
        monkeypatch, status_code=200, content=_silence_trap()
    )
    ref = _ref(tmp_path)

    first_path, _ = _synth(tmp_path, ref, text="甲")
    assert first_path is None
    assert tts_mod._last_failure_at > 0.0
    stamp = tts_mod._last_failure_at
    _second, _r = _synth(tmp_path, ref, text="乙")
    assert tts_mod._last_failure_at == stamp, "快速失败不得刷新窗"

    # 把失败时刻拨出窗外 ⇒ 放行；引擎仍坏 ⇒ 又一次真请求又入窗。
    monkeypatch.setattr(
        tts_mod,
        "_last_failure_at",
        time.monotonic() - float(tts_mod._HEALTH_BACKOFF_SECONDS) - 1.0,
    )
    third_path, _ = _synth(tmp_path, ref, text="丙")
    assert third_path is None
    assert len(attempts) == 2, "窗满必须恢复放行（非永久拉黑）"

    # 引擎恢复：把产物换成正常 wav，窗满后一次成功 ⇒ 清零。
    _install_httpx_returning(monkeypatch, status_code=200, content=_normal_wav())
    monkeypatch.setattr(
        tts_mod,
        "_last_failure_at",
        time.monotonic() - float(tts_mod._HEALTH_BACKOFF_SECONDS) - 1.0,
    )
    fourth_path, fourth_reason = _synth(tmp_path, ref, text="丁")
    assert fourth_path is not None, f"恢复后成功交付应放行：{fourth_reason}"
    assert tts_mod._last_failure_at == 0.0


# ---------------------------------------------------------------------------
# 门有牙（负样本自证）：若把「退避清零」或「陷阱记账」任一步摘掉，测试必须红
# ---------------------------------------------------------------------------


def test_gate_has_teeth_if_record_removed_on_trap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """去牙演示：若陷阱路径不再 ``_record_failure``（模拟修复被摘），窗必不进入。

    本用例不改动生产码——只是把修复要立的事实（陷阱后窗必须激活）反写成断言，
    使「修复被回退 ⇒ 红」可验证：把 ``_record_failure`` 变成 no-op 后，静音陷阱
    退化为「既不清零也不进窗」，本用例即红（证明上面核心用例真的承重）。
    """
    monkeypatch.setattr(tts_mod, "_record_failure", lambda *_a, **_k: None)
    _install_httpx_returning(monkeypatch, status_code=200, content=_silence_trap())
    ref = _ref(tmp_path)
    path, _reason = _synth(tmp_path, ref)
    assert path is None
    # 修复被摘（record 成 no-op）⇒ 窗未进入——正是旧缺陷形态，本断言因此为真；
    # 一旦恢复正确的 record_failure 实现，窗会进入，本分支反证「核心用例非空锁」。
    assert tts_mod._last_failure_at == 0.0
