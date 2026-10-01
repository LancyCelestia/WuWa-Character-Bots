"""vis3 实战修复回归：最近图片上下文 + 管理身份昵称护栏。

MM-VIS-1（2026-09-29）把环形缓存的键位从群号换成 `session_id`（群/私聊两型都有），
本件随之改名；**群聊那一侧的行为判据一字未动**（TTL/上限/只收 http/只认 image 段），
私聊那一侧的新行为由 `tests/test_recent_image_private.py` 钉。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime import (
    _RECENT_IMAGES_BY_SESSION,
    _RECENT_IMAGE_TTL_SECONDS,
    _latest_fresh_session_image,
    _learned_name_is_admin_identity,
    _remember_session_images,
)


def _config():
    return SimpleNamespace(
        bot_admin_profiles=[
            {"qq": "1722380002", "name": "澜汐", "nicknames": "澜汐汐汐 / LancyCelestia", "role": "super"},
            {"qq": "3865067623", "name": "霞月", "nicknames": "", "role": "super"},
        ]
    )


def test_learned_name_guard_blocks_admin_identity_names() -> None:
    config = _config()
    assert _learned_name_is_admin_identity("澜汐", config) is True
    assert _learned_name_is_admin_identity("霞月", config) is True
    assert _learned_name_is_admin_identity("LancyCelestia", config) is True
    assert _learned_name_is_admin_identity("路人甲", config) is False
    assert _learned_name_is_admin_identity("", config) is False


def test_recent_group_image_latest_wins_and_non_http_skipped() -> None:
    bucket_key = "group_test_a"
    _remember_session_images(
        bucket_key,
        [
            {"type": "image", "data": {"url": "https://cdn.example/old.jpg"}},
            {"type": "image", "data": {"file": "file://C:/local/nope.png"}},
            {"type": "text", "data": {"text": "看图"}},
        ],
    )
    _remember_session_images(
        bucket_key, [{"type": "image", "data": {"url": "https://cdn.example/new.jpg"}}]
    )
    import time

    assert _latest_fresh_session_image(bucket_key, time.monotonic()) == (
        "https://cdn.example/new.jpg"
    )


def test_recent_group_image_ttl_expiry() -> None:
    import time

    bucket_key = "group_test_b"
    _remember_session_images(
        bucket_key, [{"type": "image", "data": {"url": "https://cdn.example/x.jpg"}}]
    )
    future_now = time.monotonic() + _RECENT_IMAGE_TTL_SECONDS + 1.0
    assert _latest_fresh_session_image(bucket_key, future_now) == ""
    # 过期条目已被顺手清理（空桶保留在字典里，等下一张图复用）。
    assert bucket_key not in _RECENT_IMAGES_BY_SESSION or not _RECENT_IMAGES_BY_SESSION[bucket_key] or all(
        now - ts <= _RECENT_IMAGE_TTL_SECONDS
        for ts, _url in _RECENT_IMAGES_BY_SESSION[bucket_key]
        for now in (time.monotonic(),)
    )
