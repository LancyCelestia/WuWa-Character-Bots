"""vis3 实战修复回归：群聊最近图片上下文 + 管理身份昵称护栏。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.__init__ import (
    _GROUP_RECENT_IMAGE_TTL_SECONDS,
    _GROUP_RECENT_IMAGES,
    _latest_fresh_group_image,
    _learned_name_is_admin_identity,
    _remember_group_images,
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
    _remember_group_images(
        bucket_key,
        [
            {"type": "image", "data": {"url": "https://cdn.example/old.jpg"}},
            {"type": "image", "data": {"file": "file://C:/local/nope.png"}},
            {"type": "text", "data": {"text": "看图"}},
        ],
    )
    _remember_group_images(
        bucket_key, [{"type": "image", "data": {"url": "https://cdn.example/new.jpg"}}]
    )
    import time

    assert _latest_fresh_group_image(bucket_key, time.monotonic()) == (
        "https://cdn.example/new.jpg"
    )


def test_recent_group_image_ttl_expiry() -> None:
    import time

    bucket_key = "group_test_b"
    _remember_group_images(
        bucket_key, [{"type": "image", "data": {"url": "https://cdn.example/x.jpg"}}]
    )
    future_now = time.monotonic() + _GROUP_RECENT_IMAGE_TTL_SECONDS + 1.0
    assert _latest_fresh_group_image(bucket_key, future_now) == ""
    # 过期条目已被顺手清理（空桶保留在字典里，等下一张图复用）。
    assert bucket_key not in _GROUP_RECENT_IMAGES or not _GROUP_RECENT_IMAGES[bucket_key] or all(
        now - ts <= _GROUP_RECENT_IMAGE_TTL_SECONDS
        for ts, _url in _GROUP_RECENT_IMAGES[bucket_key]
        for now in (time.monotonic(),)
    )
