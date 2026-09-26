"""meme 域修复回归：冷却 LRU 有界化（审计#30）+ 错误详情透传 + 挑选扫描上限。

覆盖：
- /偷表情 冷却登记 LRU 封顶：超出容量后最旧会话记录被淘汰
- PokeLimiter._last 同款 LRU 封顶
- bot.meme 生成失败透传 meme-generator-rs 错误体 message（实测形状
  {"code":550,"message":"..."}，HTTP 500）
- bot.meme 后端不可达降级文案
- MemeLibraryStore.weighted_pick 扫描行数有界（只看最新 N 行）
- absorb_event_images 落盘/入库走线程池后语义不变（saved/文件/add 调用）
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import poke as poke_mod
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import PokeLimiter
from plugins.bot_unified_runtime.domains.meme.capabilities import (
    meme_library as meme_lib_mod,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme import (
    build_meme_capability,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    build_meme_library_capability,
)
from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_library as meme_store_mod,
)
from plugins.bot_unified_runtime.domains.meme.sources import meme_library_listener
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)


def _message(text: str, *, session_id: str = "group:1", sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP,
        group_id=session_id.split(":", 1)[-1],
        sender_id=sender_id,
        plain_text=text,
    )


_DECISION = BotDecision(
    request_id="r-test",
    should_respond=True,
    mode="command",
    trigger="test",
    capability_id="bot.test",
    target_scope=SessionType.GROUP,
    decision_reason="unit-test",
)


def _fake_store_pick() -> SimpleNamespace:
    def weighted_pick(*, keyword: str = "", nsfw_max: float = 0.2):
        return {"path": "x.png", "weight": 1.0, "md5": "m"}

    return SimpleNamespace(
        stats=lambda: {"total": 0, "used_total": 0, "nsfw_blocked": 0},
        weighted_pick=weighted_pick,
    )


# ---------------------------------------------------------------- 审计#30


def test_meme_library_cooldown_lru_bounded(monkeypatch) -> None:
    monkeypatch.setattr(meme_lib_mod, "_COOLDOWN_CAP", 5)
    capability = build_meme_library_capability(_fake_store_pick())
    sessions = [f"group:{i}" for i in range(6)]

    for index, session in enumerate(sessions):
        result = capability(_message("偷表情", session_id=session, sender_id=f"u{index}"), _DECISION)
        assert result.kind == "mixed", "首次偷表情应成功"

    # 最早的会话已被 LRU 淘汰：同会话同发送者可立刻再偷；最新会话仍在冷却。
    again_first = capability(_message("偷表情", session_id=sessions[0], sender_id="u0"), _DECISION)
    assert again_first.kind == "mixed", "被淘汰的冷却记录不应再拦截"
    again_last = capability(_message("偷表情", session_id=sessions[-1], sender_id="u5"), _DECISION)
    assert again_last.kind == "text" and "冷却" in again_last.body


def test_poke_limiter_lru_bounded(monkeypatch) -> None:
    monkeypatch.setattr(poke_mod, "_POKE_LAST_CAP", 3)
    limiter = PokeLimiter(clock=lambda: 1000.0)

    def poke(user_id: str) -> bool:
        event = SimpleNamespace(target_id="bot", group_id="g1", user_id=user_id)
        return limiter.accept(event, "bot", True, cooldown=100.0, group_cooldown=0.0)

    assert poke("u1") and poke("u2") and poke("u3") and poke("u4"), "四个不同用户首次都放行"
    assert len(limiter._last) <= 3, "冷却登记不得超出容量上限"
    assert not poke("u3"), "仍在容量的记录保持冷却"
    assert poke("u1"), "u1 记录已被 LRU 淘汰，应重新放行"


# ---------------------------------------------------------------- 错误详情透传


def _meme_request_fn(responses: dict[tuple[str, str], tuple[int, object]]):
    def request(method: str, path: str, json: dict | None = None):
        return responses[(method.upper(), path)]

    return request


def test_meme_error_detail_propagates(tmp_path) -> None:
    config = SimpleNamespace(
        bot_meme_api_enabled=True,
        bot_meme_api_base_url="http://127.0.0.1:2233",
        bot_meme_api_timeout_seconds=5,
        bot_meme_api_output_dir=str(tmp_path),
        bot_meme_cache_max_bytes=0,
    )
    request_fn = _meme_request_fn(
        {
            # info 缺失（404）→ 走纯文字直发兼容路径，POST 被服务端拒绝。
            ("GET", "/memes/petpet/info"): (404, None),
            ("POST", "/memes/petpet"): (
                500,
                {"code": 550, "message": "Image number mismatch: expected between 1 and 1, got 0"},
            ),
            ("GET", "/meme/version"): (200, "0.2.3"),
        }
    )
    capability = build_meme_capability(config, request_fn=request_fn)
    result = capability(_message("/表情 petpet 可爱"), _DECISION)
    assert result.kind == "text"
    assert "原因：Image number mismatch" in result.body, "应透传服务端 message"


def test_meme_service_down_hint(tmp_path) -> None:
    config = SimpleNamespace(
        bot_meme_api_enabled=True,
        bot_meme_api_base_url="http://127.0.0.1:2233",
        bot_meme_api_timeout_seconds=5,
        bot_meme_api_output_dir=str(tmp_path),
        bot_meme_cache_max_bytes=0,
    )
    request_fn = _meme_request_fn(
        {
            ("GET", "/memes/petpet/info"): (0, None),
            ("POST", "/memes/petpet"): (0, None),
            ("GET", "/meme/version"): (0, None),
        }
    )
    capability = build_meme_capability(config, request_fn=request_fn)
    result = capability(_message("/表情 petpet 可爱"), _DECISION)
    assert "未启动或不可达" in result.body


# ---------------------------------------------------------------- 挑选扫描上限


def test_weighted_pick_scan_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(meme_store_mod, "_PICK_SCAN_LIMIT", 5)
    # ``no_repeat=False``：本用例验的是**扫描行数有界**这一件事。20 行全用同一份
    # 字节 b"png" ⇒ 内容哈希相同 ⇒ 反重复一开，第 2 次挑必然空手（那是另一条机制
    # 在生效，会把本用例的判据糊成一团）。故按主题关掉账本、原判据原样保留；
    # 「扫描上限内的候选同样受反重复约束」由 tests/test_meme_sticker_wave.py 负责。
    store = MemeLibraryStore(tmp_path / "lib.sqlite3", prefer=[], no_repeat=False)
    md5s: list[str] = []
    for index in range(20):
        image = tmp_path / f"img{index}.png"
        image.write_bytes(b"png")
        md5 = f"{index:032d}"
        store.add(md5=md5, path=str(image), ext="png", group_id="g1")
        md5s.append(md5)
    with store._lock, store._connect() as connection:
        for index, md5 in enumerate(md5s):
            connection.execute(
                "UPDATE memes SET added_at=? WHERE md5=?", (1000.0 + index, md5)
            )
        # 最旧一行也命中关键词；最新三行命中关键词。
        connection.execute("UPDATE memes SET description='钻石' WHERE md5=?", (md5s[0],))
        for md5 in md5s[-3:]:
            connection.execute("UPDATE memes SET description='钻石' WHERE md5=?", (md5,))

    for _ in range(40):
        picked = store.weighted_pick(keyword="钻石")
        assert picked is not None
        assert picked["md5"] in set(md5s[-3:]), "扫描上限外的旧行不得再被挑中"


# ---------------------------------------------------------------- listener 落盘语义


def test_absorb_event_images_persists(tmp_path, monkeypatch) -> None:
    added: list[str] = []

    async def fake_download(url: str, *, max_bytes: int, proxy: str):
        # 每张图字节不同 → MD5 不同，才能验证两张都入库。
        return b"image-bytes-" + url.encode(), "image/png"

    monkeypatch.setattr(meme_library_listener, "_download_once", fake_download)
    store = SimpleNamespace(
        exists=lambda md5: False,
        # 真实 ``store.add`` 自 goal-12 起多一个 ``content_sha256``（内容身份）。
        # 桩跟着长，并把拿到的值记下来顺手验真（不给就只能是空串）。
        add=lambda *, md5, path, ext, group_id, content_sha256="": added.append(
            (md5, content_sha256)
        ),
        cleanup=lambda **kwargs: None,
    )
    event = SimpleNamespace(
        get_session_id=lambda: "group_123",
        group_id="123",
        get_message=lambda: [
            SimpleNamespace(type="image", data={"url": "http://x/1.png"}),
            SimpleNamespace(type="image", data={"url": "http://x/2.png"}),
        ],
    )
    config = SimpleNamespace(
        bot_meme_library_enabled=True,
        bot_meme_library_dir=str(tmp_path / "lib"),
        bot_meme_library_max_file_bytes=5242880,
        bot_meme_library_group_allowlist=[],
        bot_meme_library_group_denylist=[],
        bot_meme_library_vlm_enabled=False,
        bot_meme_library_max_files=0,
        bot_meme_library_max_age_days=0,
    )

    result = asyncio.run(
        meme_library_listener.absorb_event_images(None, event, config, store)
    )

    # ``skipped`` 是 goal-12 新加的观测位（被墓碑拒绝/内容重复的原因代号）。
    assert result == {"handled": True, "reason": "saved", "saved": 2, "skipped": []}
    assert len(added) == 2, "两张图都应入库"
    for md5, digest in added:
        stored = pathlib.Path(tmp_path / "lib" / f"{md5}.png").read_bytes()
        assert digest == hashlib.sha256(stored).hexdigest(), (
            "入库时必须带上**这张图自己**的内容哈希，不能是别人的"
        )
    saved_files = list((tmp_path / "lib").glob("*.png"))
    assert len(saved_files) == 2 and all(f.stat().st_size for f in saved_files)
