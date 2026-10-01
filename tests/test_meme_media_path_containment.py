"""S-MEME-CONTAIN（2026-09-29）：表情库 ``path`` 的容器门行为锁。

上一波留下的 CRITICAL 洞：``MemeLibraryStore._resolve_media_path`` 把**绝对路径原样
返回**，而 ``remove``/``cleanup`` 直接对返回值 ``unlink()``、``weighted_pick`` 直接把它
当发送源 ⇒ 一条被污染的库行＝「任意路径删文件 / 任意路径发图」。本件锁四件事：

1. 容器内（相对旧口径 ``data/meme_library/x.png``、容器内绝对路径）照常解析——**修洞
   不许把功能一起修没**；
2. 越界形态（容器外绝对路径、``..`` 上跳、指向容器根本身、盘根）一律抛
   ``MemeMediaPathError``，观测包装 ``media_path_for_row`` 返回 ``None``；
3. 三条 IO 腿各自的诚实降级：选图**不参选**、删除**删行不删文件**、补标**记 skip**，
   且容器外那个文件在三种操作后**都还在盘上**（这才是"没逃逸成功"的证据）；
4. 判据只有一处（``confine_media_path``），不在各 IO 点散抄第二把尺。

全离线：文件只在 ``tmp_path`` 下造，零网络、零真实图库、零源码树写入。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
    MemeMediaPathError,
)

LEGACY_EXT = ".png"
PNG_HEAD = b"\x89PNG\r\n\x1a\n"


def _make_store(tmp_path: Path) -> tuple[MemeLibraryStore, Path, Path]:
    """``tmp_path/data/meme_library.sqlite3`` + ``tmp_path/data/meme_library/``。

    刻意照现网布局：db 住在数据根、贴纸住在根下的子目录 ⇒ 容器＝``db_path.parent``。
    """
    data_root = tmp_path / "data"
    library = data_root / "meme_library"
    library.mkdir(parents=True, exist_ok=True)
    store = MemeLibraryStore(str(data_root / "meme_library.sqlite3"), prefer=[])
    return store, data_root, library


def _put(library: Path, name: str = "a.png") -> Path:
    path = library / name
    path.write_bytes(PNG_HEAD + name.encode())
    return path


def _insert_row(store: MemeLibraryStore, md5: str, path: str, *, weight: float = 5.0) -> None:
    """直接写库行（跳过 ``add`` 的正常口径）——本件测的就是**坏行**进来以后怎么办。"""
    with sqlite3.connect(str(store.db_path), timeout=15) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO memes (md5, path, ext, group_id, added_at, weight)"
            " VALUES (?, ?, ?, '', ?, ?)",
            (md5, str(path), "png", 1_700_000_000.0, weight),
        )


# ---------------------------------------------------------------- 1. 容器内照旧


def test_legacy_relative_and_in_container_absolute_still_resolve(tmp_path: Path) -> None:
    store, _data_root, library = _make_store(tmp_path)
    made = _put(library, "a.png")
    # 旧口径：相对源 CWD 的 ``data/meme_library/a.png``。
    assert store._resolve_media_path("data/meme_library/a.png") == made.resolve()
    # 新口径：容器内绝对路径必须**继续能用**（修洞不许修没功能）。
    assert store._resolve_media_path(str(made)) == made.resolve()
    # 裸文件名＝既有口径里的「相对数据根」，落在容器内就照旧认（本件不动这条语义）。
    (_data_root / "b.png").write_bytes(PNG_HEAD + b"root-level")
    assert store._resolve_media_path("b.png") == (_data_root / "b.png").resolve()


# ---------------------------------------------------------------- 2. 越界形态


@pytest.mark.parametrize(
    "value",
    [
        "C:/Windows/win.ini",
        "/etc/passwd",
        "../../outside.png",
        "data/../outside.png",
        "data/meme_library/../../outside.png",
        str(Path(__file__).resolve()),
    ],
    ids=[
        "win-absolute",
        "posix-absolute",
        "dotdot-relative",
        "dotdot-under-data",
        "dotdot-out-of-library",
        "own-source-file",
    ],
)
def test_escaping_paths_raise_instead_of_silently_degrading(tmp_path: Path, value: str) -> None:
    store, _data_root, _library = _make_store(tmp_path)
    with pytest.raises(MemeMediaPathError):
        store._resolve_media_path(value)
    # 观测包装：不抛，返回 None（各 IO 点自己决定怎么降级）。
    assert store.media_path_for_row(value, where="test") is None


def test_container_root_itself_is_not_a_media_file(tmp_path: Path) -> None:
    """指向容器根（那是目录）也算越界：unlink 会炸、read 会把目录当图发。"""
    store, _data_root, _library = _make_store(tmp_path)
    with pytest.raises(MemeMediaPathError):
        store._resolve_media_path("data")


def test_single_judgement_site_and_no_bypass() -> None:
    """判据只有一处：容器门住在 ``confine_media_path``，别处不许再抄一把尺。"""
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/meme/sources/meme_library.py"
    )
    text = source.read_text(encoding="utf-8")
    assert text.count("def confine_media_path") == 1, "容器门出现第二份定义"
    assert text.count("is_relative_to") == 1, "容器判定被抄到别处 ⇒ 两把尺会说两说"
    # 每个磁盘 IO 点都必须经观测包装（``_resolve_media_path`` 只准被包装自己调用）。
    offenders = [
        line.strip()
        for line in text.splitlines()
        if "_resolve_media_path(" in line
        and "def _resolve_media_path" not in line
        and "return self._resolve_media_path(value)" not in line
    ]
    assert not offenders, f"仍有 IO 点绕过观测包装直呼解析口：{offenders}"


# ---------------------------------------------------------------- 3. 三条腿的降级


def test_weighted_pick_never_yields_escaped_row(tmp_path: Path) -> None:
    """逃逸行不参选，且**容器外的文件仍在盘上**（没被当贴纸发出去）。"""
    store, _data_root, library = _make_store(tmp_path)
    good = _put(library, "good.png")
    outside = tmp_path / "someone-elses-album.png"
    outside.write_bytes(PNG_HEAD + b"private")
    _insert_row(store, "good0000000000000000000000000000", str(good))
    _insert_row(store, "evil00000000000000000000000000000", str(outside))
    store.set_history(None)
    picked = store.weighted_pick(keyword="", nsfw_max=1.0)
    assert picked is not None
    assert Path(picked["path"]).resolve() == good.resolve()
    assert outside.exists(), "容器外的私人文件被当贴纸送进了选图池"


def test_remove_deletes_row_but_not_file_outside_container(tmp_path: Path) -> None:
    store, _data_root, _library = _make_store(tmp_path)
    outside = tmp_path / "keep-me.png"
    outside.write_bytes(PNG_HEAD + b"do-not-delete")
    md5 = "evil00000000000000000000000000000"
    _insert_row(store, md5, str(outside))
    store.remove(md5, tombstone_reason="manual_quarantine")
    assert outside.exists(), "remove() 把容器外的文件删了 ⇒ 任意文件删除面还活着"
    assert not store.exists(md5), "行必须照删（账本要干净，越界只是不碰盘）"


def test_cleanup_prunes_rows_without_touching_escaped_files(tmp_path: Path) -> None:
    store, _data_root, _library = _make_store(tmp_path)
    outside = tmp_path / "also-keep.png"
    outside.write_bytes(PNG_HEAD + b"do-not-delete")
    md5 = "evil11111111111111111111111111111"
    _insert_row(store, md5, str(outside))
    with sqlite3.connect(str(store.db_path), timeout=15) as connection:
        # added_at 造成一年前 ⇒ 落在「按龄裁剪」那一刀里。
        connection.execute("UPDATE memes SET added_at=? WHERE md5=?", (1_000_000_000.0, md5))
    report = store.cleanup(max_files=0, max_age_days=1, protect_persona=False)
    assert report["removed"] == 1
    assert outside.exists(), "cleanup() 越界删文件 ⇒ 同一个洞的第二条腿没闭上"


def test_backfill_leg_skips_escaped_row(tmp_path: Path) -> None:
    """补标腿（listener ``_backfill_one``）遇越界行 ⇒ ``skip``，且**一个字节都不读**。

    真跑 listener 那条腿（不是复刻判据）：给它一条 path 指向容器外的行，若它还去
    ``read_bytes`` 就会把容器外的私人文件送进 VLM 打标链路——那是同洞的第二条腿。
    """
    import asyncio

    from plugins.bot_unified_runtime.domains.meme.sources import meme_library_listener

    store, _data_root, _library = _make_store(tmp_path)
    outside = tmp_path / "not-mine.png"
    outside.write_bytes(PNG_HEAD + b"private")
    config = SimpleNamespace(bot_meme_library_vlm_enabled=True, bot_meme_library_vlm_preset="x")
    calls: list[str] = []

    async def _boom(*_a: Any, **_k: Any) -> Any:  # 打标腿被调到＝已经读了盘
        calls.append("vlm")
        raise AssertionError("越界行不该走到打标")

    monkey_del = getattr(meme_library_listener, "_tag_with_vlm", None)
    assert monkey_del is not None
    meme_library_listener._tag_with_vlm = _boom  # type: ignore[assignment]
    try:
        outcome = asyncio.run(
            meme_library_listener._backfill_one(store, config, {"md5": "x", "path": str(outside)})
        )
    finally:
        meme_library_listener._tag_with_vlm = monkey_del  # type: ignore[assignment]
    assert outcome == "skip"
    assert not calls, "越界行仍然走了打标腿 ⇒ 容器门在这条路上没拦住"


def test_escaped_row_is_reported_not_silently_swallowed(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """静默＝把逃逸藏成「这张图没了」。必须留下一行可 grep 的 WARNING（不含路径）。"""
    import logging

    store, _data_root, _library = _make_store(tmp_path)
    monkeypatch.setattr(logging.getLogger("plugins.bot_unified_runtime"), "level", logging.DEBUG)
    with caplog.at_level(logging.WARNING):
        assert store.media_path_for_row("C:/Windows/win.ini", where="unit") is None
    lines = [rec.getMessage() for rec in caplog.records if "meme media path" in rec.getMessage()]
    assert lines, "越界没有留痕 ⇒ 事后无从取证"
    assert "win.ini" not in " ".join(lines), "日志不许把用户路径原文带出去"


# ------------------------------------------------------------------ B3 收窄（2026-09-30）

def test_container_narrows_to_library_dir_when_given(tmp_path: Path) -> None:
    """构造时给了 ``library_dir`` ⇒ 容器=库目录本身，**不再宽到整个数据根**。

    旧形态：db 住数据根、容器=数据根 ⇒ 指向 ``data/downloads`` 等库外子目录的
    旧行/污染行能过门被发出。收窄后同一行在发送面拿到 ``None``、文件原地不动。
    """
    data_root = tmp_path / "data"
    library = data_root / "meme_library"
    library.mkdir(parents=True)
    downloads = data_root / "downloads"
    downloads.mkdir(parents=True)
    inside = library / "in.png"
    inside.write_bytes(PNG_HEAD + b"in")
    outside = downloads / "out.png"
    outside.write_bytes(PNG_HEAD + b"out")
    store = MemeLibraryStore(
        str(data_root / "meme_library.sqlite3"),
        prefer=[],
        library_dir=str(library),
    )
    assert store.media_container() == library.resolve()
    # 库内行照常解析（修洞不许把功能一起修没）。
    assert store.media_path_for_row(str(inside), where="unit") == inside.resolve()
    # 库外子目录行：门收窄后拒之门外，文件原地不动。
    assert store.media_path_for_row(str(outside), where="unit") is None
    assert outside.exists(), "容器收窄不许顺手删库外文件（删行不删文件的口径不变）"
    # 相对旧口径（data/ 前缀）折算后落在库内的行照常可用。
    legacy = library / "legacy.png"
    legacy.write_bytes(PNG_HEAD + b"legacy")
    assert store.media_path_for_row("data/meme_library/legacy.png", where="unit") == legacy.resolve()


def test_container_without_library_dir_keeps_legacy_semantics(tmp_path: Path) -> None:
    """不给 ``library_dir``（旧构造形/测试桩）⇒ 容器=db 父目录，行为逐字不变。"""
    store, data_root, _ = _make_store(tmp_path)
    assert store.media_container() == data_root.resolve()
