"""随机发图的「只读登记面」容器锁（席 PIC，需求 15 的隐私红线 + 容器逃逸根治）。

复现的洞（2026-09-29 取证，原文见 ``%TEMP%/chatbot-rescue/seat-PIC.md``）：
登记目录里放一枚 junction 指向别处，``os.walk`` 会照进不误（Windows 下 junction 的
``os.path.islink`` 为假，靠 ``st_file_attributes`` 的 ``FILE_ATTRIBUTE_REPARSE_POINT``
才认得出来），于是**私人相册整个被吸进候选清单**，``pick_random_image`` 直接把
``resolve()`` 后根本不在登记根里的那张交出去。修洞前实测：
``pick resolved inside gallery? False``。

本件锁五格，逐格对应用户明令：
① 登记根里的 junction/重解析点**不进树**，其下的文件一条都不列；
② 取图口出口再判一次「此刻这张的真身还在登记根内吗」——TTL 清单被污染/被篡改时
   也必须 hold，不许把越界路径交给出站链；
③ 入站附件面（别人发的图/归档/表情库落点）**永不得当图库**：登记了也拒，
   且拒因进观察事实与那句话（跨会话泄露红线）；
④ 登记根本身是 junction 时按**用户自己登记的这层**放行（修洞不许修没功能）；
⑤ 拒绝面说人话：图库被链接/被禁目录占满时，措辞讲清「哪条登记项、为什么没读」。

离线：夹具全在 ``tmp_path``，零网络，不碰生产 Runtime。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

PNG_HEAD = b"\x89PNG\r\n\x1a\n"
_MIN_BYTES = 0  # 内容守卫关掉（本件只判容器面，尺子归 pool_guards 那件）


def _png(path: Path, *, tail: str = "x", pad: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_HEAD + tail.encode() + (b"\x00" * pad))
    return path


def _junction(link: Path, target: Path) -> bool:
    if sys.platform != "win32":
        return False
    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,  # 调用方按 returncode 自行降级（平台不支持＝跳过，不抛）
    )
    return done.returncode == 0 and link.exists()


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [],
        "bot_randpic_trigger_words": ["随机图"],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_min_file_kb": 0,
        "bot_randpic_min_side": 0,
        "bot_randpic_no_repeat_window_seconds": 0.0,
        "bot_download_dir": "",
        "bot_media_archive_dir": "",
        "bot_meme_library_dir": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def arena(tmp_path: Path) -> dict[str, Path]:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    _png(gallery / "ok.png", tail="ok")
    private = tmp_path / "private-album"
    _png(private / "very-private.png", tail="private")
    return {"tmp": tmp_path, "gallery": gallery, "private": private}


# ---------------------------------------------------- ① junction 不进树


@pytest.mark.skipif(sys.platform != "win32", reason="junction 只在 Windows 存在")
def test_junction_inside_gallery_never_enters_the_listing(arena) -> None:
    if not _junction(arena["gallery"] / "pics", arena["private"]):
        pytest.skip("本机建不出 junction（未验，不谎称已拦）")
    config = _config(bot_randpic_dirs=[str(arena["gallery"])])
    listing = randpic.list_gallery_images(
        randpic.configured_gallery_dirs(config),
        max_bytes=10_000_000,
        min_bytes=_MIN_BYTES,
        min_side=_MIN_BYTES,
    )
    resolved = {str(item.resolve()) for item in listing}
    assert str((arena["private"] / "very-private.png").resolve()) not in resolved
    assert all(randpic.read_is_registered(item, config) for item in listing), "清单里混进了登记面之外的路径"

    picked = randpic.pick_gallery_image_outcome(config, session_key="group_1_1", seed="s")
    assert picked.path is not None
    assert randpic.read_is_registered(picked.path, config)
    assert (arena["private"] / "very-private.png").exists(), "越界读把私人文件动了"


def test_scan_prunes_reparse_dirs_even_when_platform_agnostic(arena, monkeypatch) -> None:
    """没有真 junction 时的替身腿：重解析点判定被桩成「是」⇒ 该子树一条都不列。"""
    hidden = arena["gallery"] / "hidden"
    _png(hidden / "nope.png", tail="hidden")
    monkeypatch.setattr(randpic, "_is_reparse_point", lambda _p: True)
    listing = randpic.list_gallery_images(
        [str(arena["gallery"])], max_bytes=10_000_000, min_bytes=_MIN_BYTES, min_side=_MIN_BYTES
    )
    assert all("nope.png" not in str(item) for item in listing), "重解析点子树仍被扫进候选"
    facts = randpic.gallery_facts(
        [str(arena["gallery"])], max_bytes=10_000_000, min_bytes=_MIN_BYTES, min_side=_MIN_BYTES
    )
    assert facts.dirs_pruned_links >= 1


# ---------------------------------------------------- ② 出口门


def test_exit_gate_holds_a_listing_pointing_outside_the_registered_root(arena) -> None:
    """TTL 清单被污染（旧口径残留/别处塞路径）⇒ 取图口必须 hold，不许交给出站链。"""
    config = _config(bot_randpic_dirs=[str(arena["gallery"])])
    outside = arena["private"] / "very-private.png"

    def _tampered(dirs, **kwargs):
        return [outside]

    original = randpic.list_gallery_images
    try:
        randpic.list_gallery_images = _tampered  # type: ignore[assignment]
        outcome = randpic.pick_gallery_image_outcome(config, session_key="group_9_9", seed="s")
        assert outcome.path is None
        assert outcome.reason == "out_of_registered_root"
    finally:
        randpic.list_gallery_images = original  # type: ignore[assignment]


def test_capability_sends_nothing_and_says_why_when_listing_is_out_of_root(arena, monkeypatch) -> None:
    config = _config(bot_randpic_dirs=[str(arena["gallery"])])
    outside = arena["private"] / "very-private.png"
    monkeypatch.setattr(randpic, "list_gallery_images", lambda dirs, **kwargs: [outside])
    message = SimpleNamespace(
        request_id="r1", plain_text="随机图", session_id="group_9_9", message_id="m1", group_id="9", user_id="9"
    )
    result = randpic.build_randpic_capability(config)(message, None)
    assert not result.images, "越界路径被塞进了发图部件"
    assert result.body, "失败面必须说人话，不许空回"
    assert any("out_of_registered_root" in tag for tag in result.audit_tags)


# ---------------------------------------------------- ③ 入站附件面不得当图库


def test_inbound_attachment_store_is_refused_as_gallery_root(arena) -> None:
    """「不得把别人发的图转给第三者」的结构性收口：入站附件目录登记了也不读。"""
    downloads = arena["tmp"] / "runtime-data" / "downloads"
    _png(downloads / "someone-elses-photo.png", tail="inbound")
    config = _config(
        bot_randpic_dirs=[str(downloads)],
        bot_download_dir=str(downloads),
    )
    assert randpic.registered_gallery_roots(config) == []
    facts = randpic.gallery_facts(
        randpic.configured_gallery_dirs(config),
        max_bytes=10_000_000,
        min_bytes=_MIN_BYTES,
        min_side=_MIN_BYTES,
        config=config,
    )
    assert facts.verdict == "denied_root"
    line = randpic.gallery_degradation_line(facts, randpic.configured_gallery_dirs(config))
    assert "BOT_RANDPIC_DIRS" in line and "没有能发的图" not in line
    assert randpic.pick_gallery_image(config, session_key="group_1_1", seed="s") is None


def test_denied_root_never_appears_as_gallery_empty(arena) -> None:
    """禁目录被拒 ≠ 「你的图库是空的」：断言面必须把两者分开记账。"""
    archive = arena["tmp"] / "runtime-data" / "media_archive"
    _png(archive / "x.png", tail="archive")
    config = _config(bot_randpic_dirs=[str(archive)], bot_media_archive_dir=str(archive))
    facts = randpic.gallery_facts(
        randpic.configured_gallery_dirs(config),
        max_bytes=10_000_000,
        min_bytes=_MIN_BYTES,
        min_side=_MIN_BYTES,
        config=config,
    )
    tags = randpic.gallery_audit_tags("gallery_denied_root", facts)
    assert "gallery_denied_root" in tags
    assert "gallery_empty" not in tags


# ---------------------------------------------------- ④ 登记根自己是 junction


@pytest.mark.skipif(sys.platform != "win32", reason="junction 只在 Windows 存在")
def test_registered_junction_root_is_still_read(arena) -> None:
    """用户自己把登记项做成 junction ⇒ 那是他登记的这层，照读（修洞不许修没功能）。"""
    target = arena["tmp"] / "own-pictures"
    _png(target / "mine.png", tail="mine")
    link = arena["tmp"] / "gallery-link"
    if not _junction(link, target):
        pytest.skip("本机建不出 junction")
    config = _config(bot_randpic_dirs=[str(link)])
    listing = randpic.list_gallery_images(
        randpic.configured_gallery_dirs(config),
        max_bytes=10_000_000,
        min_bytes=_MIN_BYTES,
        min_side=_MIN_BYTES,
    )
    assert [item.name for item in listing] == ["mine.png"]
    assert all(randpic.read_is_registered(item, config) for item in listing)


# ---------------------------------------------------- ⑤ 读图请求面那条锁


def test_read_request_outside_registered_dirs_is_refused(arena) -> None:
    """任何「目录在登记面之外」的读图请求必须被拒（用户明令新增的一条锁）。"""
    config = _config(bot_randpic_dirs=[str(arena["gallery"])])
    assert randpic.read_is_registered(arena["gallery"] / "ok.png", config) is True
    assert randpic.read_is_registered(arena["private"] / "very-private.png", config) is False
    assert randpic.read_is_registered(arena["private"], config) is False
    assert randpic.read_is_registered(arena["gallery"], config) is False  # 目录本身不是图
    assert randpic.read_is_registered("", config) is False
    assert randpic.read_is_registered(str(arena["private"] / "ghost.png"), _config()) is False


def test_privacy_lock_has_teeth_on_a_poisoned_listing(arena, monkeypatch) -> None:
    """注毒自证：把登记面之外的路径塞进清单，出口门必须判红（不是空跑的尺）。"""
    config = _config(bot_randpic_dirs=[str(arena["gallery"])])
    poison = arena["private"] / "very-private.png"
    assert randpic.read_is_registered(poison, config) is False
    monkeypatch.setattr(randpic, "list_gallery_images", lambda dirs, **kwargs: [poison])
    assert randpic.pick_gallery_image_outcome(config, session_key="p_1", seed="s").path is None
