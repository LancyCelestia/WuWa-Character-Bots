"""B1 收库守卫波（2026-09-28）：表情库吸收链「只收真贴纸」的离线回归。

三层各锁一次，判据唯一真身 ``domains/media/image_guard.py``：

1. ``_absorb_size_guard_reason``（下限单元）：空载荷、假图（HTML 冒充 .png）、
   字节不足、短边不足、解不开坏件——逐代号；两把下限全 0 = 关 = B1 前逐字节同形
   （离线桩 config 读不到键即落此态，既有 ``_download_once`` 替换桩用例不受牵连）。
2. ``_download_once`` 的常开魔数闸（真路非替换桩）：用打桩 httpx 喂 HTML 字节，
   断言「这张不收」（返回 None），PNG 签名字节能取回。
3. ``absorb_event_images`` 端到端：被守卫挡下的图**一个字节都不落盘**、不进库，
   拒绝代号进返回值的 ``skipped`` 观测账（这就是「metric」）。

「把所有表情贴纸存下来」mandate 保留其意图、收窄其范围：image/mface/sticker
段型照收，但截图尺寸的大图过闸、1KB 图标不过。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.meme.sources import meme_library_listener

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png(side: int, *, pad_to: int = 0) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (side % 251, 3, 9)).save(buffer, format="PNG")
    data = buffer.getvalue()
    if pad_to > len(data):
        data += b"\x00" * (pad_to - len(data))
    return data


# ============================================================================
# 1. 下限守卫单元
# ============================================================================


def test_guard_disabled_by_default_is_byte_identical_to_pre_b1() -> None:
    """两把尺全 0（读不到配置键的离线桩态）：假图字节也放行——开关语义的负样本。"""
    assert meme_library_listener._absorb_size_guard_reason(
        b"<html>fake</html>", min_bytes=0, min_side=0
    ) == ""


def test_guard_rejects_empty_payload_unconditionally() -> None:
    assert (
        meme_library_listener._absorb_size_guard_reason(
            b"", min_bytes=0, min_side=0
        )
        == "guard_empty_payload"
    )


def test_guard_rejects_fake_png_html_body() -> None:
    """假 .png 名字下是 HTML：启用后按魔数挡（guard_not_image_magic）。"""
    fake = (b"<!DOCTYPE html><html><body>nope</body></html>" * 40)[:2_000]
    assert meme_library_listener._absorb_size_guard_reason(
        fake, min_bytes=1, min_side=0
    ) == "guard_not_image_magic"


def test_guard_rejects_tiny_icon_and_undersized_image() -> None:
    icon = _png(16, pad_to=512)
    assert meme_library_listener._absorb_size_guard_reason(
        icon, min_bytes=100 * 1024, min_side=0
    ) == "guard_below_min_bytes"
    small = _png(64, pad_to=2_048)
    assert meme_library_listener._absorb_size_guard_reason(
        small, min_bytes=1, min_side=300
    ) == "guard_below_min_side"


def test_guard_accepts_real_sticker_sized_image() -> None:
    good = _png(320, pad_to=4_096)
    assert (
        meme_library_listener._absorb_size_guard_reason(
            good, min_bytes=100, min_side=300
        )
        == ""
    )


def test_guard_rejects_undecodable_truncation() -> None:
    broken = PNG_MAGIC + b"\x00\x01\x02TRUNCATED"
    assert meme_library_listener._absorb_size_guard_reason(
        broken, min_bytes=1, min_side=300
    ) in {"guard_not_image_magic", "guard_undecodable"}


# ============================================================================
# 2. _download_once 常开魔数闸（真路，打桩 httpx，零网络）
# ============================================================================


class _FakeStreamResponse:
    def __init__(self, *, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers

    async def aiter_bytes(self):
        yield self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeClient:
    def __init__(self, script: dict[str, tuple[int, bytes, dict[str, str]]]) -> None:
        self._script = script

    def stream(self, method: str, url: str):  # 桩形态对齐 httpx（ANN 规则未在 tests 面启用 ⇒ 不挂 noqa）
        status, body, headers = self._script[url]
        return _FakeStreamResponse(status=status, body=body, headers=headers)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _install_client(monkeypatch: pytest.MonkeyPatch, script: dict) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeClient(script))
    monkeypatch.setattr(
        meme_library_listener, "check_download_url", lambda url: None
    )


def test_download_once_drops_non_image_body_despite_image_content_type(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """content-type 说 image/png、字节头是 HTML ⇒ 这张不收（None）。"""
    script = {
        "https://pic.example/fake.png": (
            200,
            b"<!DOCTYPE html><html>not a png</html>",
            {"content-type": "image/png"},
        )
    }
    _install_client(monkeypatch, script)
    got = asyncio.run(
        meme_library_listener._download_once(
            "https://pic.example/fake.png", max_bytes=5_242_880, proxy=""
        )
    )
    assert got is None


def test_download_once_returns_real_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _png(320)
    script = {"https://pic.example/real.png": (200, body, {"content-type": "image/png"})}
    _install_client(monkeypatch, script)
    got = asyncio.run(
        meme_library_listener._download_once(
            "https://pic.example/real.png", max_bytes=5_242_880, proxy=""
        )
    )
    assert got == (body, "image/png")


# ============================================================================
# 3. absorb 端到端：守卫挡下的一个字节都不落盘
# ============================================================================


def _absorb_event(url: str) -> Any:
    return SimpleNamespace(
        get_session_id=lambda: "group_7",
        group_id="7",
        get_message=lambda: [{"type": "image", "data": {"url": url}}],
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("fake-png-html", id="fake-png-html"),
        pytest.param("tiny-icon", id="tiny-icon"),
    ],
)
def test_absorb_rejects_and_records_reason_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """字节够大但文件头是 HTML ⇒ 魔数闸挡；真 PNG 但字节不足 ⇒ 体积闸先挡。"""
    if case == "fake-png-html":
        body: bytes = (b"<!DOCTYPE html><html>" + b"not an image " * 12_000)[:200_000]
        expected_code = "guard_not_image_magic"
    else:
        body = _png(64, pad_to=512)
        expected_code = "guard_below_min_bytes"
    async def fake_download(url: str, *, max_bytes: int, proxy: str):
        return body, "image/png"

    monkeypatch.setattr(meme_library_listener, "_download_once", fake_download)
    written: list[Path] = []
    original_write = Path.write_bytes

    def spy_write(self: Path, data: object, *args: object, **kwargs: object) -> object:
        written.append(self)
        return original_write(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_bytes", spy_write)

    store = SimpleNamespace(
        exists=lambda md5: False,
        add=lambda **kwargs: pytest.fail("被守卫挡下的图不许进库"),
        cleanup=lambda **kwargs: None,
    )
    config = SimpleNamespace(
        bot_meme_library_enabled=True,
        bot_meme_library_dir=str(tmp_path / "library"),
        bot_meme_library_max_file_bytes=5_242_880,
        bot_meme_library_min_file_kb=100,
        bot_meme_library_min_side=300,
        bot_meme_library_group_allowlist=[],
        bot_meme_library_group_denylist=[],
        bot_meme_library_vlm_enabled=False,
        bot_meme_library_max_files=0,
        bot_meme_library_max_age_days=0,
        bot_meme_shorekeeper_protect_from_prune=True,
    )
    result = asyncio.run(
        meme_library_listener.absorb_event_images(
            None, _absorb_event(f"https://pic.example/{case}.png"), config, store
        )
    )
    assert result["saved"] == 0
    assert expected_code in result["skipped"], result["skipped"]
    assert written == [], "被挡下的字节一个都不许落盘"


def test_absorb_still_saves_real_sticker_with_guards_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫开着，真贴纸（短边达标、字节达标）照收——mandate 没被误伤。"""
    body = _png(320, pad_to=110_000)

    async def fake_download(url: str, *, max_bytes: int, proxy: str):
        return body, "image/png"

    monkeypatch.setattr(meme_library_listener, "_download_once", fake_download)
    added: list[str] = []
    store = SimpleNamespace(
        exists=lambda md5: md5 in set(),
        add=lambda **kwargs: added.append(str(kwargs["md5"])),
        cleanup=lambda **kwargs: None,
    )
    config = SimpleNamespace(
        bot_meme_library_enabled=True,
        bot_meme_library_dir=str(tmp_path / "library"),
        bot_meme_library_max_file_bytes=5_242_880,
        bot_meme_library_min_file_kb=100,
        bot_meme_library_min_side=300,
        bot_meme_library_group_allowlist=[],
        bot_meme_library_group_denylist=[],
        bot_meme_library_vlm_enabled=False,
        bot_meme_library_max_files=0,
        bot_meme_library_max_age_days=0,
        bot_meme_shorekeeper_protect_from_prune=True,
    )
    result = asyncio.run(
        meme_library_listener.absorb_event_images(
            None, _absorb_event("https://pic.example/real.png"), config, store
        )
    )
    assert result["saved"] == 1 and len(added) == 1
    assert (tmp_path / "library").is_dir()
