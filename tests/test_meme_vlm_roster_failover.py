"""meme 打标道的注册表轮转 + 永久错误熔断 + reasoning 模型 token 地板（S-VLM-FAILOVER）。

立票缘由（2026-09-28 现场取证）：现网 ``BOT_MEME_LIBRARY_VLM`` 那条道用**裸 httpx**
自绘请求，端点取自 `_resolve_vision_config` —— 它按 priority 只挑**一枚**条目，
失败即 ``return``，从不试下一条。而注册表真身 ``vision_describe`` 早就是
「按 priority 轮转最多 3 条」。两条腿对同一张注册表两种吃法，后果就是 09-28 那轮：

    meme vlm http md5=… status=403 model=gemini-3.8-flash-high   （×4）
    meme backfill round all-failed 清空 0/尝试 20

上游对 p1/p2 回的是同一个钱包的 ``insufficient_user_quota``，而注册表里第三条腿
（免费 GLM）实测可用——**一条死腿把整轮 20 发真实调用烧光，活腿一次都没被问过**。

本文件锁三件事：
① 一条腿永久失败 ⇒ 换下一条（轮转，与真身同口径）；
② 永久失败（401/403＝`providers._classify_http_error` 的 ``auth`` 档）的端点
   进进程级熔断，第二张图不再重烧；全部端点皆永久失败 ⇒ 当轮即停，不空烧整批；
③ 打标请求的 ``max_tokens`` 必须喂得起 reasoning 模型——300 档 GLM 恒回
   ``content=""``（全文进 ``reasoning_content``），JSON 抽不出来 ⇒ 兜底腿形同不存在。

全离线：httpx 整体桩替换（真端点连构造都不会发生）；SQLite 只写 tmp_path（铁律 6）。
留痕红线沿用 S-VLM-OBS：只记 md5/状态码/模型名，绝不记正文、Bearer、URL、api_key。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import httpx
import pytest

from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_library_listener,
    persona_review,
    shorekeeper_absorb,
)
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)

LOGGER_NAME = "plugins.bot_unified_runtime.domains.meme.sources.meme_library_listener"
DEAD_MODEL = "dead-wallet-model"
LIVE_MODEL = "free-vision-model"
DEAD_BASE_URL = "https://dead.invalid.test/v1"
LIVE_BASE_URL = "https://live.invalid.test/v1"
DEAD_KEY = "dead-key-not-a-secret"
LIVE_KEY = "live-key-not-a-secret"
MD5 = "a" * 32

GOOD_JSON = (
    '{"is_meme": true, "description": "测试打标", "emotion_tags": [],'
    ' "scene_tags": [], "persona_hint": "common", "nsfw_score": 0.1}'
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """熔断名册逐例清零 + 覆盖 store 默认禁读（同 S-VLM-OBS 的哑火口径）。"""
    meme_library_listener._vlm_dead_entry_ids.clear()

    def _boom(config: Any) -> Any:
        raise RuntimeError("本测试未注入覆盖 store 替身")

    monkeypatch.setattr(meme_library_listener, "_build_runtime_settings_store", _boom)
    yield
    meme_library_listener._vlm_dead_entry_ids.clear()


def _registry_config() -> SimpleNamespace:
    """两腿注册表：p1 永久失败（欠费钱包）、p2 可用（免费腿）。"""
    return SimpleNamespace(
        bot_meme_library_vlm_enabled=True,
        bot_meme_library_vlm_preset="",
        bot_meme_library_vlm_fallback_first_preset=True,
        bot_meme_library_vlm_timeout_seconds=20,
        bot_meme_library_nsfw_delete=0.8,
        bot_meme_shorekeeper_absorb_enabled=True,
        bot_meme_library_vlm_model="",
        bot_meme_library_vlm_base_url="",
        bot_meme_library_vlm_api_key="",
        bot_vision_model_registry={
            "myvlm": [
                {"model": DEAD_MODEL, "base_url": DEAD_BASE_URL, "api_key": DEAD_KEY, "priority": 1},
                {"model": LIVE_MODEL, "base_url": LIVE_BASE_URL, "api_key": LIVE_KEY, "priority": 2},
            ]
        },
    )


class _Response:
    def __init__(self, status_code: int = 200, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("response body is not json")
        return self._body


def _install_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> dict[str, Any]:
    """httpx.AsyncClient 整桩：按 payload["model"] 分流，并记录每次出站的 model。"""
    calls: dict[str, Any] = {"posts": 0, "models": [], "payloads": []}

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, url: str, *, headers: Any = None, json: Any = None) -> Any:
            calls["posts"] += 1
            calls["models"].append(str((json or {}).get("model", "")))
            calls["payloads"].append(json or {})
            return handler(url, headers or {}, json or {})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


def _registry_config_live() -> SimpleNamespace:
    """两腿都可用的名册（只验循环续圈，不验轮转）。"""
    cfg = _registry_config()
    cfg.bot_vision_model_registry = {"myvlm": [
        {"model": LIVE_MODEL, "base_url": LIVE_BASE_URL, "api_key": LIVE_KEY, "priority": 1},
    ]}
    return cfg


def _dead_then_live(url: str, headers: dict, payload: dict) -> _Response:
    if payload.get("model") == DEAD_MODEL:
        return _Response(status_code=403)
    return _Response(200, {"choices": [{"message": {"content": GOOD_JSON}}]})


def _all_dead(url: str, headers: dict, payload: dict) -> _Response:
    return _Response(status_code=403)


def _Decision() -> shorekeeper_absorb.AbsorbDecision:
    """替身直接用**真身数据类**（S-MEME-SEMANTICS，2026-09-29）。

    旧桩手抄三字段（``action``/``persona_owned``/``audit``），而读侧 ``_tag_with_vlm``
    的 outcome 日志自 S-MEME2-REVIEW 起还要取 ``review_state`` ——桩缺这一格就
    ``AttributeError`` 假红整批（本文件 6 枚）。权威侧是读侧：真身 ``AbsorbDecision``
    一直带着这枚字段（``shorekeeper_absorb.py`` 的 dataclass），日志取的都是决策件
    真有的东西，另有 ``test_listener_logs_absorb_outcome_decision`` 的 AST 结构锁
    钉住「日志必须带 audit」。所以修桩不修断言、更不把断言改松：桩与契约同源后
    读侧再取新字段也不会假红，而真身缺字段时本文件照样红——牙还在。
    """
    return shorekeeper_absorb.AbsorbDecision(
        action="tagged",
        persona_owned=True,
        review_state=persona_review.ADMIT,
        audit=("ok",),
    )


@pytest.fixture()
def absorb_ok(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """打桩 apply_tagged_outcome：记录走通次数（成功判据落在这里）。"""
    applied: list[dict] = []

    def _fake(**kwargs: Any) -> _Decision:
        applied.append(kwargs)
        return _Decision()

    monkeypatch.setattr(shorekeeper_absorb, "apply_tagged_outcome", _fake)
    return applied


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]


def _pending_store(tmp_path: Path, count: int) -> MemeLibraryStore:
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", no_repeat=False)
    for index in range(count):
        md5 = f"{index:032x}"
        image = tmp_path / f"{md5}.png"
        image.write_bytes(b"img" + bytes([index]))
        store.add(md5=md5, path=str(image), ext="png", group_id="g1")
    return store


# ------------------------------------------------------------------
# ① 轮转：死腿之后必须问活腿（现网 0/尝试 20 的那枚根因）
# ------------------------------------------------------------------


def test_dead_entry_falls_over_to_next_roster_entry(
    monkeypatch: pytest.MonkeyPatch, absorb_ok: list[dict]
) -> None:
    """p1 永久失败 ⇒ 同一张图必须再问 p2，并把 p2 的标签落地。"""
    calls = _install_httpx(monkeypatch, _dead_then_live)
    result = _run(
        meme_library_listener._tag_with_vlm(_NoTouchStore(), _registry_config(), MD5, b"png")
    )
    assert calls["models"] == [DEAD_MODEL, LIVE_MODEL], f"未轮转到下一条：{calls['models']}"
    assert result is not None, "兜底腿成功时不得再返回 None"
    assert len(absorb_ok) == 1, "打标成功只应落一次库"


def test_transient_failure_does_not_circuit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """503 是瞬时档：不得进熔断名册（否则上游抖一下就永久隐身）。"""
    _install_httpx(monkeypatch, lambda url, headers, payload: _Response(status_code=503))
    config = _registry_config()
    for _ in range(2):
        _run(meme_library_listener._tag_with_vlm(_NoTouchStore(), config, MD5, b"png"))
    assert not meme_library_listener._vlm_dead_entry_ids, "瞬时错误不该熔断"


# ------------------------------------------------------------------
# ② 熔断：永久错误的端点第二张图不再重烧；全端点皆死 ⇒ 当轮即停
# ------------------------------------------------------------------


def test_permanent_entry_is_skipped_on_next_image(
    monkeypatch: pytest.MonkeyPatch, absorb_ok: list[dict]
) -> None:
    """第一张图把 p1 打成永久失败 ⇒ 第二张图只发 p2，不再空烧 p1。"""
    calls = _install_httpx(monkeypatch, _dead_then_live)
    config = _registry_config()
    _run(meme_library_listener._tag_with_vlm(_NoTouchStore(), config, MD5, b"png"))
    first_round_posts = calls["posts"]
    _run(meme_library_listener._tag_with_vlm(_NoTouchStore(), config, MD5, b"png"))
    assert first_round_posts == 2
    assert calls["posts"] == 3, "第二张图应跳过已熔断的 p1"
    assert calls["models"][-1] == LIVE_MODEL


def test_round_stops_when_every_entry_is_permanently_dead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """全部端点皆永久失败 ⇒ 当轮只烧一轮端点数（不是 张数×端点数），并点名原因。

    ``concurrency=1``：本锁要断言的是「熔断后不再重烧」的发数上限，必须逐张串行
    才确定；并发形态下的有界超烧由 ``test_concurrent_chunk_counts_stay_honest`` 负责。
    """
    caplog.set_level(logging.INFO, LOGGER_NAME)
    calls = _install_httpx(monkeypatch, _all_dead)
    store = _pending_store(tmp_path, 3)
    tagged = _run(
        meme_library_listener.backfill_meme_tags(
            store, _registry_config(), limit=10, concurrency=1
        )
    )
    assert tagged == 0
    assert calls["posts"] == 2, f"应当一轮问尽两条端点即停，实际发了 {calls['posts']} 发"
    messages = "\n".join(_messages(caplog))
    assert "meme backfill round attempted=1 tagged=0" in messages, messages
    assert "永久失败" in messages and "不再重烧" in messages, "熔断收轮必须说破，不许与『清空』同形"


def test_concurrent_chunk_counts_stay_honest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    absorb_ok: list[dict],
) -> None:
    """提速后的分片并发（S-VLM-SPEED）：计数口径不许变形—— attempted=发过请求的张数、
    tagged=走通落库的张数；死腿只拖慢第一片，不许把整批改成分母。"""
    caplog.set_level(logging.INFO, LOGGER_NAME)
    _install_httpx(monkeypatch, _dead_then_live)
    store = _pending_store(tmp_path, 3)
    tagged = _run(
        meme_library_listener.backfill_meme_tags(
            store, _registry_config(), limit=10, concurrency=3
        )
    )
    assert tagged == 3, f"三条腿轮转后每张都该补上：{tagged}"
    assert len(absorb_ok) == 3
    messages = "\n".join(_messages(caplog))
    assert "meme backfill round attempted=3 tagged=3" in messages, messages


# ------------------------------------------------------------------
# ③ token 地板：reasoning 模型在 300 档恒回空 content
# ------------------------------------------------------------------


def test_tag_request_carries_reasoning_token_floor(
    monkeypatch: pytest.MonkeyPatch, absorb_ok: list[dict]
) -> None:
    """max_tokens 必须高于 reasoning 模型的空档（现测 300 ⇒ content 全空）。"""
    calls = _install_httpx(monkeypatch, _dead_then_live)
    _run(meme_library_listener._tag_with_vlm(_NoTouchStore(), _registry_config(), MD5, b"png"))
    budgets = [int(p.get("max_tokens", 0)) for p in calls["payloads"]]
    assert all(b >= 600 for b in budgets), f"token 档喂不起 reasoning 模型：{budgets}"


# ------------------------------------------------------------------
# ④ 派生覆盖锁：熔断档位不许和 LLM 真身的分类器各说各话
# ------------------------------------------------------------------


def test_permanent_status_set_matches_provider_classifier() -> None:
    """`_VLM_PERMANENT_STATUSES` 必须与 providers._classify_http_error 的 auth 档同口径。"""
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        _classify_http_error,
    )

    for status in meme_library_listener._VLM_PERMANENT_STATUSES:
        assert _classify_http_error(status) == "auth", f"{status} 并不属 auth 档"
    assert meme_library_listener._VLM_PERMANENT_STATUSES == {
        code for code in (401, 402, 403) if _classify_http_error(code) == "auth"
    }, "auth 档状态码与熔断名册已漂移"


class _NoTouchStore:
    """失败路径的哨兵 store：任何触库动作 = 立即炸。"""

    db_path = None

    def apply_tags(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得触库")

    def remove(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得删库")

    def mark_persona_owned(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("打标失败不得标本命")


@pytest.fixture()
def absorb_writes(monkeypatch: pytest.MonkeyPatch):
    """替身按生产语义**真落库**：让队列真的缩短，循环才可能自然收束。

    为什么必须落库：上一版这把锁用空替身，结果「本轮报成功、下轮同一张又回来」
    把「有进展就续圈」跑成死循环——那正是 max_rounds 护栏要防的形态，
    所以这里刻意写真库，另用 test_round_cap 单独锁死循环护栏。
    """
    def _fake_apply(*, store: Any, md5: str, tags: Any, **_kw: Any) -> Any:
        if isinstance(tags, dict):
            store.apply_tags(md5, **tags)
        return _Decision()

    monkeypatch.setattr(shorekeeper_absorb, "apply_tagged_outcome", _fake_apply)


def _seq_failing_stub(monkeypatch: pytest.MonkeyPatch, fail_at: int) -> dict[str, int]:
    """按调用序号失败一发（模拟单张偶发限流/超时）。"""
    state = {"n": 0, "posts": 0}

    def _handler(url: str, headers: dict, payload: dict) -> _Response:
        state["n"] += 1
        state["posts"] += 1
        if state["n"] == fail_at:
            return _Response(status_code=503)
        return _Response(200, {"choices": [{"message": {"content": GOOD_JSON}}]})

    _install_httpx(monkeypatch, lambda url, headers, payload: _handler(url, headers, payload))
    return state


def test_partial_success_round_keeps_the_loop_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    absorb_writes: None,
) -> None:
    """提速真正的锁（S-VLM-SPEED 16:3x 现算）：**有进展就续圈**，零进展才收。

    旧判据「整批全成功才继续」在 batch=60 的现网里反向掐死吞吐：任何一张偶发
    失败都让整轮提前收摊，实测 10 小时只补 139 张。这里 3 张里坏 1 张：
    第一轮 2 成 1 败 ⇒ 必须续圈把那张问第二遍；补成后再一圈报 0/0 才收。
    """
    caplog.set_level(logging.INFO, LOGGER_NAME)
    store = _pending_store(tmp_path, 3)
    state = _seq_failing_stub(monkeypatch, fail_at=2)
    _run(
        meme_library_listener.backfill_meme_tags_loop(
            store, _registry_config_live(), batch=3, interval_seconds=0.0, concurrency=1
        )
    )
    counters = [m for m in _messages(caplog) if "meme backfill round attempted=" in m]
    assert len(counters) == 3, f"部分成功必须续圈，实际圈数={len(counters)}：{counters}"
    assert any("attempted=3 tagged=2" in m for m in counters), counters
    assert any("attempted=1 tagged=1" in m for m in counters), counters
    assert any("attempted=0 tagged=0" in m for m in counters), counters
    assert store.list_untagged(limit=10) == [], "队列应真被排空"
    assert state["posts"] == 4, f"3 张一发 + 坏那张再问一发 = 4 发，实际 {state['posts']}"


def test_round_cap_stops_a_non_shrinking_queue_and_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """死循环护栏：每轮都"报成功"却没让队列缩短 ⇒ 到圈数上限必须收，且留痕说破。

    这是本文件上一版自测时真实撞出来的形态（空替身不落库 ⇒ 零进展判据永远等不到），
    不是假想敌：V-5 防的"无限重烧真实视觉调用"在新判据下换了个入口回来。
    """
    caplog.set_level(logging.INFO, LOGGER_NAME)
    store = _pending_store(tmp_path, 2)

    def _fake_apply_never_lands(**_kw: Any) -> Any:
        return _Decision()  # 报成功但不写库 ⇒ 队列永远有货

    monkeypatch.setattr(shorekeeper_absorb, "apply_tagged_outcome", _fake_apply_never_lands)
    calls = _install_httpx(
        monkeypatch,
        lambda url, headers, payload: _Response(
            200, {"choices": [{"message": {"content": GOOD_JSON}}]}
        ),
    )
    _run(
        meme_library_listener.backfill_meme_tags_loop(
            store, _registry_config_live(), batch=2, interval_seconds=0.0,
            concurrency=1, max_rounds=3,
        )
    )
    messages = "\n".join(_messages(caplog))
    assert "收束于圈数上限 3" in messages, messages
    assert calls["posts"] == 6, f"3 圈 × 2 张 = 6 发封顶，实际 {calls['posts']} 发"
