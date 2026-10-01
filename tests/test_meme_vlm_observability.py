"""S-VLM-OBS（2026-09-27）：VLM 打标链静默点清零 / backfill 诚实 / 在册未执法可见。

按只读取证席 SEAT-VLM-REACH 的修法票 V-1..V-5 立案。此前四种服务层失败形态
（HTTP 非 200、请求异常、模型答无 JSON、JSON 解析炸）全部零留痕 ``return``，
「服务层坏了」与「开关没开」在日志里长得一模一样；backfill 按尝试数冒充
成功数（L13），全失败轮与"清空"不可分辨且循环无限重烧真实视觉调用。

本文件给每条留痕一记行为锁：**恰有一行**含可判别原因的 WARNING，且留痕不越
红线（只记类型/状态码/长度/md5/模型名；绝不记正文、Bearer、URL、api_key——
台账 #59 KQ-7 前半口径）。注毒自证：把任一 ``logger.warning`` 摘掉 ⇒ 对应锁红。

全离线：httpx 整体桩替换（真端点连构造都不会发生），SQLite 只写 tmp_path
（源码树零写入，铁律 6）；零真实网络请求。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import httpx
import pytest

from plugins.bot_unified_runtime.domains.meme.sources import meme_library_listener
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)

LOGGER_NAME = (
    "plugins.bot_unified_runtime.domains.meme.sources.meme_library_listener"
)
SECRET_KEY = "sk-SECRET-DO-NOT-LEAK-9e7"
FAKE_BASE_URL = "https://vlm.invalid.test/v1"
FAKE_MODEL = "test-vision-model"
BODY_MARK = "模型正文-不得进日志"
MD5 = "0123456789abcdef0123456789abcdef"

# 留痕红线探针：这些子串一旦出现在任何一条日志里，就是泄正文/泄凭据/泄 URL。
_LEAK_NEEDLES = (
    SECRET_KEY,
    "Bearer",
    "sk-",
    FAKE_BASE_URL,
    "vlm.invalid.test",
    "chat/completions",
    BODY_MARK,
)

# 四种失败形态的可判别原因代号（一行一形；摘掉对应留痕 ⇒ 该锁红）。
TOKEN_L4 = "meme vlm http"      # V-1：HTTP 状态码非 200
TOKEN_L5 = "meme vlm request failed"  # V-2：网络/超时/异常
TOKEN_L6 = "meme vlm unparseable"     # V-3：模型答里没有 JSON
TOKEN_L7 = "meme vlm json error"      # V-4：JSON 解析失败
_ALL_TOKENS = (TOKEN_L4, TOKEN_L5, TOKEN_L6, TOKEN_L7)

_GOOD_JSON = (
    '{"is_meme": true, "description": "测试打标", "emotion_tags": [],'
    ' "scene_tags": [], "persona_hint": "common", "nsfw_score": 0.1}'
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """门闩清零 + 默认禁读真实覆盖 store。

    ``_build_runtime_settings_store`` 的缺省替身直接抛：哪个测试没注入替身
    却走到读 store，就吃一条静默哑火（helper 的诚实降级路径），永不误开
    ``data/settings``（生产覆盖泄进测试进程＝eat.py:287 先例点名的事故族）。

    ``_vlm_dead_entry_ids`` 是 S-VLM-FAILOVER 加的进程级熔断名册：本文件的
    L4 用例发的是 401（永久档），不清零就会把后面每个复用同一枚 fake 端点的
    用例都判成「已熔断、不再问」⇒ posts=0 假红。逐例清零才各测各的。
    """
    meme_library_listener._restart_gaps_attempted.clear()
    meme_library_listener._restart_gaps_announced.clear()
    meme_library_listener._vlm_dead_entry_ids.clear()

    def _boom(config: Any) -> Any:
        raise RuntimeError("本测试未注入覆盖 store 替身")

    monkeypatch.setattr(
        meme_library_listener, "_build_runtime_settings_store", _boom
    )
    yield
    meme_library_listener._restart_gaps_attempted.clear()
    meme_library_listener._restart_gaps_announced.clear()
    meme_library_listener._vlm_dead_entry_ids.clear()


@pytest.fixture()
def fake_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    """端点解析整段替身：本文件锁的是失败形态留痕，不是注册表挑选（另有现成锁）。"""

    monkeypatch.setattr(
        meme_library_listener,
        "_resolve_vision_config",
        lambda config: {"model": FAKE_MODEL, "base_url": FAKE_BASE_URL, "api_key": SECRET_KEY},
    )


class _Response:
    def __init__(self, status_code: int = 200, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("response body is not json")
        return self._body


def _install_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> dict[str, int]:
    """把 httpx.AsyncClient 整体换桩：真实连接在原理上不可能发生。"""
    calls = {"posts": 0}

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, url: str, *, headers: Any = None, json: Any = None) -> Any:
            calls["posts"] += 1
            return handler(url, headers or {}, json or {})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


class _NoTouchStore:
    """失败形态的锁用这枚哨兵 store：任何触库动作 = 立即炸。"""

    db_path = None

    def apply_tags(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得触库")

    def remove(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得删库")

    def mark_persona_owned(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得标本命")


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


def _assert_one_trace_with_reason(
    messages: list[str], token: str, reason_needles: tuple[str, ...]
) -> str:
    """恰有一条该形态的 WARNING，含可判别原因；且只出现这一种形态的代号。"""
    hits = [message for message in messages if token in message]
    assert len(hits) == 1, f"留痕 {token!r} 应恰有一条，实际 {len(hits)} 条：{hits}"
    for needle in reason_needles:
        assert needle in hits[0], f"留痕缺可判别原因 {needle!r}：{hits[0]}"
    strangers = [
        other
        for other in _ALL_TOKENS
        if other != token and any(other in message for message in messages)
    ]
    assert not strangers, f"失败形态串档：本应只有 {token!r}，却出现 {strangers}"
    return hits[0]


def _assert_no_leak(messages: list[str]) -> None:
    joined = "\n".join(messages)
    for needle in _LEAK_NEEDLES:
        assert needle not in joined, f"留痕越红线：{needle!r} 出现在日志里"


# ------------------------------------------------------------------
# 一、四条静默 return 的留痕锁（V-1..V-4，四种失败形态各一锁）
# ------------------------------------------------------------------


def test_l4_http_status_leaves_one_attributable_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """L4（401/5xx 等服务层非 200）：恰一行、含状态码与 md5、零正文零凭据。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    _install_httpx(monkeypatch, lambda url, headers, payload: _Response(status_code=401))
    result = _run(
        meme_library_listener._tag_with_vlm(_NoTouchStore(), SimpleNamespace(), MD5, b"png")
    )
    assert result is None
    _assert_one_trace_with_reason(
        _messages(caplog), TOKEN_L4, ("status=401", MD5, FAKE_MODEL)
    )
    assert "meme absorb outcome" not in "\n".join(_messages(caplog))
    _assert_no_leak(_messages(caplog))


def test_l5_request_exception_traces_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """L5（网络/超时）：只记异常类型名——异常文本带着完整 URL+query 也不许进日志。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)

    def _raise(url: str, headers: dict, payload: dict) -> Any:
        raise httpx.ConnectTimeout(
            f"connect timed out {url}?api-key={SECRET_KEY}"
        )

    _install_httpx(monkeypatch, _raise)
    result = _run(
        meme_library_listener._tag_with_vlm(_NoTouchStore(), SimpleNamespace(), MD5, b"png")
    )
    assert result is None
    _assert_one_trace_with_reason(
        _messages(caplog), TOKEN_L5, ("type=ConnectTimeout", MD5)
    )
    # 故意让异常文本含 URL/密钥：本锁的红线部分是"异常文本一个字都不进日志"。
    _assert_no_leak(_messages(caplog))


def test_l6_answer_without_json_traces_length_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """L6（模型答非 JSON，如拒答纯文字）：记长度不记原文。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    body = {"choices": [{"message": {"content": f"我无法分析这张图。{BODY_MARK}"}}]}
    _install_httpx(monkeypatch, lambda url, headers, payload: _Response(200, body))
    result = _run(
        meme_library_listener._tag_with_vlm(_NoTouchStore(), SimpleNamespace(), MD5, b"png")
    )
    assert result is None
    messages = _messages(caplog)
    _assert_one_trace_with_reason(
        messages, TOKEN_L6, ("content_len=", MD5, FAKE_MODEL)
    )
    _assert_no_leak(messages)


def test_l7_json_parse_error_traces_type_and_len(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """L7（有 {…} 形状但 loads 炸，如截断/双逗号）：与 L6 分档，类型名+长度可归因。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    broken = '{"is_meme": true,,' + BODY_MARK + '}'
    body = {"choices": [{"message": {"content": broken}}]}
    _install_httpx(monkeypatch, lambda url, headers, payload: _Response(200, body))
    result = _run(
        meme_library_listener._tag_with_vlm(_NoTouchStore(), SimpleNamespace(), MD5, b"png")
    )
    assert result is None
    _assert_one_trace_with_reason(
        _messages(caplog), TOKEN_L7, ("type=JSONDecodeError", "raw_len=", MD5)
    )
    _assert_no_leak(_messages(caplog))


# ------------------------------------------------------------------
# 二、backfill 诚实锁（V-5：退出判据=成功数；全失败轮点名「清空 0/尝试 N」）
# ------------------------------------------------------------------


def _pending_store(tmp_path: Path, items: dict[str, bytes]) -> MemeLibraryStore:
    """真 store + 落盘文件：description 为空 ⇒ list_untagged 全部在册。"""
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", no_repeat=False)
    for index, (md5, payload) in enumerate(items.items()):
        image = tmp_path / f"{md5}.png"
        image.write_bytes(payload)
        store.add(md5=md5, path=str(image), ext="png", group_id="g1")
    return store


def _vlm_on_config() -> SimpleNamespace:
    return SimpleNamespace(bot_meme_library_vlm_enabled=True)


def test_backfill_all_failed_round_reports_zero_of_attempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """全失败轮：返回成功数 0（不是尝试数），且「清空 0/尝试 N」必须被点名。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    store = _pending_store(tmp_path, {f"{i:032d}": b"img" + bytes([i]) for i in range(3)})
    _install_httpx(monkeypatch, lambda url, headers, payload: _Response(status_code=503))
    tagged = _run(meme_library_listener.backfill_meme_tags(store, _vlm_on_config(), limit=10))
    messages = _messages(caplog)
    assert tagged == 0, "退出判据口径=成功数：全失败轮必须返回 0，不许冒充处理过 3 张"
    # WARNING 计数与成功数自洽（报告 V-5 锁的判据）：3 张各有逐张留痕、0 张补成。
    assert sum(TOKEN_L4 in message for message in messages) == 3
    assert any(
        "meme backfill round attempted=3 tagged=0" in message for message in messages
    ), "每轮 attempted/tagged 两个数必须都进日志"
    assert any(
        "meme backfill round all-failed" in message and "清空 0/尝试 3" in message
        for message in messages
    ), "全失败轮必须点名「清空 0/尝试 N」，不许与『清空』同形"
    assert len(store.list_untagged(limit=10)) == 3, "失败的图必须仍在待标队列（没被谎报为补过）"
    _assert_no_leak(messages)


def test_backfill_counts_only_images_that_reached_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """成功数口径的分子：只有走通 apply_tagged_outcome 的才计数；混合轮不虚报不冤枉。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    good_md5, bad_md5 = "a" * 32, "b" * 32
    store = _pending_store(tmp_path, {good_md5: b"ok-image", bad_md5: b"bad-image"})

    def _handler(url: str, headers: dict, payload: dict) -> Any:
        data_url = payload["messages"][0]["content"][1]["image_url"]["url"]
        raw = base64.b64decode(data_url.split(",", 1)[1])
        if raw == b"ok-image":
            return _Response(200, {"choices": [{"message": {"content": _GOOD_JSON}}]})
        return _Response(status_code=503)

    _install_httpx(monkeypatch, _handler)
    tagged = _run(meme_library_listener.backfill_meme_tags(store, _vlm_on_config(), limit=10))
    assert tagged == 1
    messages = _messages(caplog)
    assert any("meme backfill round attempted=2 tagged=1" in m for m in messages)
    assert not any("all-failed" in m for m in messages), "有成功就不许喊全失败"
    pending = store.list_untagged(limit=10)
    assert [str(row["md5"]) for row in pending] == [bad_md5], "补成的离开队列、失败的留在队首"


def test_backfill_loop_stops_after_all_failed_round_and_never_reburns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """L13 主锁：全失败轮按旧口径（尝试数=batch）会无限续圈、每 10 分钟重烧真实
    视觉调用；成功数口径下必须一圈即停——发数恰等于张数，一次都不回头。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    store = _pending_store(tmp_path, {f"{i:032d}": b"img" + bytes([i]) for i in range(3)})
    calls = _install_httpx(monkeypatch, lambda url, headers, payload: _Response(status_code=503))
    _run(
        meme_library_listener.backfill_meme_tags_loop(
            store, _vlm_on_config(), batch=3, interval_seconds=0.0
        )
    )
    assert calls["posts"] == 3, f"全失败即停：只许每图一发，实际 {calls['posts']} 发"
    messages = _messages(caplog)
    assert sum("meme backfill round attempted=" in m for m in messages) == 1, "循环只走了一圈"
    assert any("all-failed" in m for m in messages)


def test_backfill_loop_keeps_going_only_while_batch_fully_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_vision: None
) -> None:
    """成功数口径的另一半：整批补成 ⇒ 续圈；下一轮队列空（attempted=0）⇒ 收束。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    store = _pending_store(tmp_path, {"c" * 32: b"ok-image", "d" * 32: b"ok-image"})
    calls = _install_httpx(
        monkeypatch,
        lambda url, headers, payload: _Response(
            200, {"choices": [{"message": {"content": _GOOD_JSON}}]}
        ),
    )
    _run(
        meme_library_listener.backfill_meme_tags_loop(
            store, _vlm_on_config(), batch=2, interval_seconds=0.0
        )
    )
    messages = _messages(caplog)
    assert calls["posts"] == 2
    assert any("meme backfill round attempted=2 tagged=2" in m for m in messages)
    assert any("meme backfill round attempted=0 tagged=0" in m for m in messages)
    assert store.list_untagged(limit=10) == [], "真清空时队列应为空（此时报 0/0 才诚实）"


# ------------------------------------------------------------------
# 三、在册未执法可见性锁（永久重启形：配置在册 true、装载 false ⇒ 说破需重启）
# ------------------------------------------------------------------


class _FakeOverrideStore:
    """替身只演语义不吃盘：有覆盖返覆盖，无覆盖回退装配值（真 store.get 同构）。"""

    def __init__(self, overrides: dict[str, Any], config: Any) -> None:
        self._overrides = dict(overrides)
        self._config = config
        self.gets = 0

    def get(self, key: str, config: Any) -> Any:
        self.gets += 1
        normalized = key.strip().upper()
        if normalized in self._overrides:
            return self._overrides[normalized]
        return getattr(config, normalized.lower(), None)


def test_restart_required_gap_announced_once_via_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """覆盖库在册 true 而装配装载 false ⇒ 启动道必须点名「需重启」，每键至多一行；
    装载 true 的键不许被牵连报出。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    fake = None

    def _build(config: Any) -> Any:
        nonlocal fake
        fake = _FakeOverrideStore(
            {"BOT_MEME_LIBRARY_VLM_ENABLED": "true"}, config
        )
        return fake

    monkeypatch.setattr(meme_library_listener, "_build_runtime_settings_store", _build)
    # 端点解析替身为空：可见性必须发生在端点检查**之前**（装载 false 时端点
    # 通不通与「在册未执法」无关，不许被提前 return 吃掉）。
    monkeypatch.setattr(
        meme_library_listener,
        "_resolve_vision_config",
        lambda config: {"model": "", "base_url": "", "api_key": ""},
    )
    config = SimpleNamespace(
        bot_meme_library_enabled=True, bot_meme_library_vlm_enabled=False
    )
    store = SimpleNamespace(list_untagged=lambda **kwargs: [])
    _run(meme_library_listener.backfill_meme_tags_loop(store, config, batch=1, interval_seconds=0.0))
    meme_library_listener._log_restart_required_gaps(config)  # 再来一次也不刷第二行

    warnings = [
        message
        for message in _messages(caplog)
        if "配置在册为 true、本进程装载为 false（需重启" in message
    ]
    assert len(warnings) == 1, f"至多点名一次，实际 {warnings}"
    assert "BOT_MEME_LIBRARY_VLM_ENABLED" in warnings[0]
    assert "BOT_MEME_LIBRARY_ENABLED" not in "\n".join(_messages(caplog)), (
        "library 键装载为 true（执法中），无『未执法』可报——不许误伤"
    )
    assert fake is not None and fake.gets == 1, "每键至多一查（读崩也不许重开 store）"


def test_no_roster_entry_or_loaded_true_stays_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """负例锁：无覆盖（store.get 回退装配值 false）⇒ 那不算「在册」，一个字都不许说；
    装载 true 的键连覆盖库都不许碰（零 IO）。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    built: list[str] = []

    def _build(config: Any) -> Any:
        built.append("called")
        return _FakeOverrideStore({}, config)

    monkeypatch.setattr(meme_library_listener, "_build_runtime_settings_store", _build)
    meme_library_listener._log_restart_required_gaps(
        SimpleNamespace(bot_meme_library_enabled=True, bot_meme_library_vlm_enabled=False)
    )
    assert _messages(caplog) == [], "覆盖不存在时不许喊『在册未执法』（误报会淹没真点）"

    caplog.clear()
    built.clear()
    meme_library_listener._log_restart_required_gaps(
        SimpleNamespace(bot_meme_library_enabled=True, bot_meme_library_vlm_enabled=True)
    )
    assert _messages(caplog) == []
    assert built == [], "装载 true 的一侧本来就在执法：连 store 都不该被打开"


def test_restart_store_failure_degrades_silently_and_latches(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """诚实边界：覆盖 store 读不动 ⇒ 整段哑火（不编故事也不报错外泄），且本进程
    不再重开——每键至多一查，事件道反复调也不产生重复 IO。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    attempts: list[str] = []

    def _build(config: Any) -> Any:
        attempts.append("open")
        raise RuntimeError("覆盖库不可用")

    monkeypatch.setattr(meme_library_listener, "_build_runtime_settings_store", _build)
    config = SimpleNamespace(bot_meme_library_enabled=True, bot_meme_library_vlm_enabled=False)
    for _ in range(3):
        meme_library_listener._log_restart_required_gaps(config)
    assert _messages(caplog) == [], "读不动就说不了话：不许半真半假地报"
    assert len(attempts) == 1, f"读失败也必须有门闩（3 次调用只许 1 次开库），实际 {len(attempts)}"
