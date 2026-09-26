"""P14 波 ITEM 15「随机发图派发」回归之二：**身份=内容摘要**（离线）。

与 ``tests/test_randpic_dispatch.py`` 的分工：那件测派发门链与降级，本件只测
「同一张图」这件事的**判据本身**——

- 判据是文件**字节的 SHA-256**，不是路径：用户整理图库时改名/换目录是常态，
  按路径记账等于把「窗内不重发」清零；
- 同字节的两个文件算**同一张**（复制出来的重复图不该被当成两张轮着发）；
- 读不出字节时退化成路径身份、**绝不抛异常**（一次 IO 失败不能打死发图腿）；
- 整库都在窗内的指令路退「**最久没发**」那张——本件 docstring 一直这么写，
  旧实现却按 seed 任取，这次把话与实现对齐。

全离线：图片是 ``tmp_path`` 里的假字节，零网络、零源码树写入。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

_PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _clean_caches():
    """三处模块级状态（目录清单/身份摘要/缺省窗账）都是跨例状态——逐例清空。"""
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _pick(dirs: list[str], *, session_key: str = "private_7", seed: str, **kwargs):
    """走**缺省窗账**（``window=None``）：同一例内多次调用要共享同一本账。

    每例都新建窗口就等于每次都是空账，「窗内不重发」这条判据根本测不到。
    """
    return randpic.pick_fresh_image(
        dirs,
        session_key=session_key,
        window=kwargs.pop("window", None),
        window_seconds=kwargs.pop("window_seconds", 3600.0),
        seed=seed,
        **kwargs,
    )


# ------------------------------------------------------------- 改名不该清零账本
def test_renamed_file_is_still_treated_as_already_sent(tmp_path) -> None:
    """改名后窗内仍算「发过」——按路径记账会在这里漏成第二张。"""
    gallery = tmp_path / "gallery"
    _write(gallery / "a.png", _PNG + b"one")
    dirs = [str(gallery)]

    first = _pick(dirs, seed="s1", allow_exhausted=False)
    assert first is not None and first.name == "a.png"

    os.rename(gallery / "a.png", gallery / "改名后的图.png")
    # 清单有 30 秒 TTL：现算必须重扫，否则测的是缓存里的旧路径（旧路径已不存在
    # 会被存在性过滤掉，那也能拿到 None，但那是**空库**的 None，不是本例要验的
    # 「同图已发」的 None——所以这里显式清缓存，把两条成因分开）。
    randpic._SCAN_CACHE.clear()
    assert (
        _pick(dirs, seed="s2", allow_exhausted=False) is None
    ), "改名被当成一张新图 ⇒ 窗内不重发在真实用法下失效"


def test_path_identity_would_have_let_the_rename_through(tmp_path) -> None:
    """对照组：同一张图**没改名**时，第二发也必须是 None（防上一条测的是空库）。"""
    gallery = tmp_path / "gallery"
    _write(gallery / "a.png", _PNG + b"one")
    dirs = [str(gallery)]
    assert _pick(dirs, seed="s1", allow_exhausted=False) is not None
    assert _pick(dirs, seed="s2", allow_exhausted=False) is None
    # 库里有第二张真不同内容的图时，改名那一发仍能被发出去（不是恒 None）。
    _write(gallery / "b.png", _PNG + b"two")
    randpic._SCAN_CACHE.clear()
    other = _pick(dirs, seed="s3", allow_exhausted=False)
    assert other is not None and other.name == "b.png"


# ----------------------------------------------------------- 同字节算同一张图
def test_two_paths_with_identical_bytes_count_as_one_image(tmp_path) -> None:
    gallery = tmp_path / "gallery"
    _write(gallery / "a.png", _PNG + b"same")
    _write(gallery / "b.png", _PNG + b"same")
    _write(gallery / "c.png", _PNG + b"other")
    dirs = [str(gallery)]
    window = randpic.RecentImageWindow()
    picked = [
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=3600.0,
            seed=f"seed-{index}",
            allow_exhausted=False,
        )
        for index in range(3)
    ]
    # 两张同字节 + 一张不同 = 只有两个身份可发 ⇒ 第三发必须作罢。
    # 不断言「具体哪一张先出」：先出哪张由 seed 决定，可发的**张数**才是判据。
    sends = [item for item in picked if item is not None]
    assert len(sends) == 2, f"同字节重复图没被折叠成一张：{picked}"
    assert (
        randpic.image_identity(gallery / "a.png")
        == randpic.image_identity(gallery / "b.png")
    )


# ---------------------------------------------------- 指令路退「最久没发」那张
def test_exhausted_command_path_returns_least_recently_sent(tmp_path) -> None:
    gallery = tmp_path / "gallery"
    first = _write(gallery / "a.png", _PNG + b"first")
    second = _write(gallery / "b.png", _PNG + b"second")
    dirs = [str(gallery)]
    window = randpic.RecentImageWindow()

    def _pick(**kwargs):
        return randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=3600.0,
            **kwargs,
        )

    sent_a = _pick(seed="x1")
    sent_b = _pick(seed="x2")
    assert {sent_a, sent_b} == {first, second}, "两身份两张图本该各发一次"
    # 整库进窗后走指令路：真按「最久没发」取，而不是凭 seed 任取。
    # 「最久没发」= 本例里**先**发出去的那一张（先发的在账本里排在最旧位）。
    assert _pick(seed="whatever", allow_exhausted=True) == sent_a


def test_least_recent_helper_is_ordered_by_send_time(tmp_path) -> None:
    gallery = tmp_path / "gallery"
    _write(gallery / "a.png", _PNG + b"a")
    _write(gallery / "b.png", _PNG + b"b")
    window = randpic.RecentImageWindow()
    window.record("s", "id-old", window_seconds=3600.0)
    window.record("s", "id-new", window_seconds=3600.0)
    assert window.least_recent_key("s", window_seconds=3600.0) == "id-old"
    # 重发把那一枚推到最新 ⇒ 最旧位换人（账本按发送序而非首次序排）。
    window.record("s", "id-old", window_seconds=3600.0)
    assert window.least_recent_key("s", window_seconds=3600.0) == "id-new"


# ------------------------------------------------------------------ 身份函数本身
def test_identity_is_content_and_invalidates_on_change(tmp_path) -> None:
    path = _write(tmp_path / "x.png", _PNG + b"v1")
    identity_v1 = randpic.image_identity(path)
    assert identity_v1 != str(path) and len(identity_v1) == 16
    # 同内容另一条路径 ⇒ 同一身份（身份与路径无关）。
    twin = _write(tmp_path / "y.png", _PNG + b"v1")
    assert randpic.image_identity(twin) == identity_v1
    # 字节变了 ⇒ 身份必须变（(mtime,size) 记忆化不能把旧摘要粘住）。
    _write(path, _PNG + b"v2-longer")
    assert randpic.image_identity(path) != identity_v1


def test_identity_never_raises_on_unreadable_input(tmp_path) -> None:
    missing = tmp_path / "gone.png"
    assert randpic.image_identity(missing) == str(missing)
    directory = tmp_path / "adir"
    directory.mkdir()
    # 目录名当图片传进来（清单缓存期内被用户换成目录）：退化路径身份、不抛。
    assert randpic.image_identity(directory) == str(directory)


def test_pick_survives_a_file_turning_unreadable(tmp_path) -> None:
    """取图口对坏文件的态度：跳得过去就发，全跳不过就 None，绝不抛。"""
    gallery = tmp_path / "gallery"
    _write(gallery / "ok.png", _PNG + b"ok")
    broken = gallery / "broken.png"
    broken.write_bytes(_PNG + b"broken")
    dirs = [str(gallery)]
    assert randpic.image_identity(broken) != ""
    broken.unlink()
    randpic._SCAN_CACHE.clear()
    assert _pick(dirs, seed="s", allow_exhausted=False) is not None
