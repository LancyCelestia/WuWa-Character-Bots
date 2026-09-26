"""S-T-RANDPIC-1（2026-09-26）随机发图「池子那一侧」的离线回归。

四族判据，每条锁都有注毒自证（见 ``.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-RANDPIC-1.md``）：

- **A 组 观察事实**：``GalleryFacts`` 把「配了几条目录 / 哪条根本不存在 / 哪条不是
  目录 / 哪条读不动 / 列出了多少文件 / 多少张是图片格式 / 多少张超过单张上限」分开
  记账；``verdict`` 是措辞的唯一来源。旧实现六种事实压成一个 ``[]``。
- **B 组 诚实降级**：没打开过的目录**绝不评论它的内容**（「我不知道」≠「它没有」，
  同 ``cd0068c``/``21bdabf`` 那条禁令），并且这句话必须真能到用户手上——旧分支标着
  ``SendPolicy.SILENT_AUDIT``，管线对它处置 ``SKIPPED``＋空正文，文案只存在于源码里。
- **C 组 取图代价**：同图判据仍是内容 SHA-256（唯一真身 ``domains/media/digest.py``），
  但「在不在窗内」先用文件大小做**超集排除**，只在大小撞车时才读字节。现网图库实测
  23,353 张 / 89,982 MB ⇒ 旧写法每次取图要把全库摘要一遍（外推 ≈127 秒，且记忆化上限
  1024 远小于库容量 ⇒ 每次都重来）。
- **D 组 诚实的「发完了 / 没翻完」**：上限内翻完全库才可以说 ``pool exhausted``；
  翻不完只说 ``unproven``。路径提示（窗账顺手记的那条路径）永远是**加速道**，
  要判据必须先过摘要复核。

全离线：图库只在 ``tmp_path`` 下造真字节小假图（合法 PNG 魔数），零网络、
零真实协议端、零源码树写入、零真实图库读取。
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: 「没打开过」那一族事实绝不允许出现的內容断言。
_CONTENT_CLAIM_PHRASES = (
    "没有能发的图片",
    "一张文件都没有",
    "没有我能发的图片格式",
    "都超过单张上限",
)
_CANT_SEE_PHRASES = ("没能打开", "打不开", "读不出", "看不到", "不是个文件夹")


def _write_image(root: Path, name: str, payload: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(PNG_MAGIC + payload)
    return path


def _size(path: Path) -> int:
    return path.stat().st_size


def _gallery(root: Path, count: int, *, distinct_sizes: bool = True) -> list[Path]:
    """造 ``count`` 张内容互异的图；``distinct_sizes=False`` 时**大小全同**（内容仍互异）。

    大小全同那一档是 C 组预筛的最不利形态：摘要一律要真读，一条都不许漏放。
    """
    made: list[Path] = []
    for index in range(count):
        if distinct_sizes:
            body = bytes([index % 251]) * (index + 1)
        else:
            body = bytes([index % 251]) * 8
        made.append(_write_image(root, f"pic-{index:04d}.png", body))
    return made


@pytest.fixture(autouse=True)
def _isolate_randpic_state(monkeypatch):
    """三本进程级账（TTL 清单 / 身份记忆化 / 窗账）逐用例复位，绝不跨例串味。"""
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    monkeypatch.setattr(randpic, "_IDENTITY_CACHE", OrderedDict())
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [],
        "bot_randpic_trigger_words": [],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_no_repeat_window_seconds": 3600.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(text: str = "随机图", *, session_id: str = "private_7", message_id: str = "m1"):
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP if session_id.startswith("group_") else SessionType.PRIVATE,
        sender_id="7",
        plain_text=text,
        message_id=message_id,
    )


def _run(config, text: str = "随机图", **kwargs):
    return randpic.build_randpic_capability(config)(_message(text, **kwargs), None)


def _outcome(dirs: list[str], *, session: str = "private_7", seed: str = "s", **kw):
    """主动腿缺省（``allow_exhausted=False``）——整库在窗内就不发。"""
    window = kw.pop("window", None) or randpic.RecentImageWindow()
    kw.setdefault("window_seconds", 3600.0)
    kw.setdefault("allow_exhausted", False)
    return randpic.pick_fresh_outcome(
        dirs, session_key=session, window=window, seed=seed, **kw
    )


def _walk_that_reports_one_error(top: str, *_args, **kwargs):
    """假 ``os.walk``：列出真文件，另外**如实报一条读不动**（复刻权限/卷离线）。

    ``os.walk`` 缺省 ``onerror=None`` ⇒ 这类错误被静默吞掉；本仓旧实现正是缺省形态，
    所以「目录读不动」和「目录是空的」在旧代码里根本分不开。
    """
    onerror = kwargs.get("onerror")
    entries = sorted(Path(top).iterdir()) if Path(top).is_dir() else []
    yield str(top), [str(p) for p in entries if p.is_dir()], [
        str(p.name) for p in entries if p.is_file()
    ]
    if callable(onerror):
        onerror(OSError(13, "Permission denied", str(top)))


# ============================================================================
# A 组：池子观察事实
# ============================================================================


def test_unconfigured_dirs_verdict() -> None:
    facts = randpic.gallery_facts([])
    assert facts.dirs_configured == 0 and facts.usable == 0
    assert facts.verdict == "unconfigured"
    assert facts.opened is False


def test_blank_dir_entries_are_not_counted_as_configured(
    tmp_path: Path, monkeypatch
) -> None:
    """``BOT_RANDPIC_DIRS=[" "]`` 这种空写位要归「没配」，不能编出一条路径错误。

    ``chdir`` 到空目录是刻意的：注毒（去掉跳过那一腿）时这条用例必须**便宜地红**，
    而不是去把真实工作目录扫一遍（旧写法正是会扫到 44,146 个文件那一档）。
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    facts = randpic.gallery_facts(["", "   "])
    assert facts.dirs_configured == 0
    assert facts.verdict == "unconfigured"
    assert facts.files_seen == 0, "空白写位被当成目录扫了工作目录"


def test_missing_dir_is_reported_as_missing_not_empty(tmp_path: Path) -> None:
    """路径根本不存在 ⇒ verdict=missing，且**不许**冒充「打开过」。"""
    facts = randpic.gallery_facts([str(tmp_path / "从未存在的图库")])
    assert facts.verdict == "missing" and facts.dirs_missing == 1
    assert facts.opened is False  # 这是措辞能不能提内容的唯一许可证


def test_file_as_dir_is_not_directory(tmp_path: Path) -> None:
    made = _write_image(tmp_path, "not-a-folder.png", b"oops")
    facts = randpic.gallery_facts([str(made)])
    assert facts.verdict == "not_directory" and facts.opened is False


def test_truly_empty_dir_says_empty(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    root.mkdir()
    facts = randpic.gallery_facts([str(root)])
    assert facts.verdict == "empty" and facts.opened is True and facts.files_seen == 0


def test_dir_with_files_but_no_images_says_no_image_extension(tmp_path: Path) -> None:
    """「空的」与「有东西但没有图」是两种事实——旧实现把两者压成同一个空清单。"""
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "note.txt").write_text("不是图", encoding="utf-8")
    (root / "clip.mp4").write_bytes(b"0" * 10)
    facts = randpic.gallery_facts([str(root)])
    assert facts.verdict == "no_image_extension"
    assert facts.files_seen == 2 and facts.images_seen == 0 and facts.usable == 0


def test_images_over_size_cap_says_over_limit(tmp_path: Path) -> None:
    root = tmp_path / "big"
    for index in range(3):
        _write_image(root, f"heavy-{index}.png", b"H" * 40)
    facts = randpic.gallery_facts([str(root)], max_bytes=20)
    assert facts.verdict == "over_limit"
    assert facts.images_seen == 3 and facts.images_over_limit == 3 and facts.usable == 0


def test_stat_failure_is_unknown_not_absence(tmp_path: Path, monkeypatch) -> None:
    """stat 拿不到＝「不知道」；既不许说「没有图」，也不许说「都超限」。"""
    root = tmp_path / "locked"
    made = _write_image(root, "a.png", b"payload")
    _write_image(root, "b.png", b"fine")
    real_stat = Path.stat

    def _fake_stat(self, *_args, **_kwargs):
        if str(self).endswith("a.png"):
            raise OSError(13, "locked")
        return real_stat(self)

    monkeypatch.setattr(Path, "stat", _fake_stat)
    facts = randpic.gallery_facts([str(root)])
    assert made.name == "a.png"
    assert facts.images_stat_failed == 1 and facts.images_over_limit == 0
    assert facts.verdict == "usable"  # b.png 仍可用：一张坏图不毁掉整次请求
    assert facts.usable == 1


def test_unreadable_dir_is_captured_not_swallowed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(os, "walk", _walk_that_reports_one_error)
    facts = randpic.gallery_facts([str(root)])
    assert facts.dirs_unreadable == 1
    assert facts.usable == 0
    assert facts.verdict == "unreadable"
    assert facts.opened is True  # 目录确实打开了，只是有一处读不动


def test_multiple_dirs_merge_and_keep_per_dir_facts(tmp_path: Path) -> None:
    good = tmp_path / "good"
    _gallery(good, 2)
    missing = str(tmp_path / "gone")
    facts = randpic.gallery_facts([str(good), missing])
    assert facts.dirs_configured == 2 and facts.usable == 2
    # 有一条能发 ⇒ 整池子算「能用」（缺的那条仍如实记在 dirs_missing 里，不藏）；
    # 但一条都发不出时，「打不开」必须排在「是空的」之前——见下一条。
    assert facts.verdict == "usable" and facts.dirs_missing == 1
    assert [p.name for p in randpic.list_gallery_images([str(good), missing])] == [
        "pic-0000.png",
        "pic-0001.png",
    ]


def test_missing_outranks_empty_when_nothing_is_sendable(tmp_path: Path) -> None:
    """两种「没货」混在一起时，措辞必须落在「我没能打开它」，不是「它是空的」。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    facts = randpic.gallery_facts([str(empty), str(tmp_path / "gone")])
    assert facts.usable == 0 and facts.dirs_read == 1 and facts.dirs_missing == 1
    assert facts.verdict == "missing"
    body = randpic.gallery_degradation_line(facts, [str(empty), str(tmp_path / "gone")])
    for phrase in _CONTENT_CLAIM_PHRASES:
        assert phrase not in body, f"有一条路没打开，却说成了『{phrase}』"


def test_relative_dir_resolves_against_cwd_and_tilde_expands(tmp_path: Path, monkeypatch) -> None:
    """相对路径按进程 CWD（在册口径）＋ ``~`` 必须展开——旧写法会安静变成 ``<CWD>/~/…``"""
    (tmp_path / "relative-gallery").mkdir()
    _write_image(tmp_path / "relative-gallery", "r.png", b"rel")
    monkeypatch.chdir(tmp_path)
    assert randpic.gallery_facts(["relative-gallery"]).usable == 1

    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    _write_image(home / "Pictures", "h.png", b"home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    assert randpic._gallery_root("~/Pictures") == home / "Pictures"
    assert randpic.gallery_facts(["~/Pictures"]).usable == 1


def test_listing_and_facts_come_from_one_scan(tmp_path: Path, monkeypatch) -> None:
    """同一 TTL 窗内三次读数只扫一遍：清单与事实不同源就会各说各话。"""
    root = tmp_path / "gallery"
    _gallery(root, 4)
    calls: list[str] = []
    real_walk = os.walk

    def _counting_walk(top, *args, **kwargs):
        calls.append(str(top))
        yield from real_walk(top, *args, **kwargs)

    monkeypatch.setattr(os, "walk", _counting_walk)
    first = randpic.list_gallery_images([str(root)])
    facts = randpic.gallery_facts([str(root)])
    again = randpic.list_gallery_images([str(root)])
    assert len(calls) == 1, f"三次读数扫了 {len(calls)} 遍 ⇒ 清单与事实不同源"
    assert first == again and facts.usable == 4


def test_nested_directories_are_included(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    _gallery(root, 2)
    sub = root / "sub"
    _write_image(sub, "nested.png", b"nested")
    assert randpic.gallery_facts([str(root)]).usable == 3


# ============================================================================
# B 组：诚实降级
# ============================================================================


def test_degradation_line_is_delivered_not_silently_audited(tmp_path: Path) -> None:
    """旧写法把文案写进 body 却标 SILENT_AUDIT ⇒ 管线判 SKIPPED，一句都出不去。"""
    result = _run(_config(bot_randpic_dirs=[str(tmp_path / "不存在")]))
    assert result.body.strip(), "降级那句话不能是空的"
    assert result.send_policy is not SendPolicy.SILENT_AUDIT, (
        "SILENT_AUDIT 在 pipeline._complete 里等于『不发出去』：这句必须真到用户手上"
    )
    assert result.images == []
    assert "\n" not in result.body.strip(), "降级只给一句，别铺成小作文"


def test_no_trigger_stays_silent(tmp_path: Path) -> None:
    """没命中触发词那一支**必须**继续 SILENT_AUDIT（matcher 抢跑时不该回话）。"""
    result = _run(_config(bot_randpic_dirs=[str(tmp_path / "g")]), text="今天天气不错")
    assert result.send_policy is SendPolicy.SILENT_AUDIT
    assert result.body == ""


def test_missing_dir_wording_does_not_claim_the_folder_is_empty(tmp_path: Path) -> None:
    """「我不知道」≠「它没有」：路径不存在时不许对内容下断言。"""
    body = _run(_config(bot_randpic_dirs=[str(tmp_path / "打不开")])).body
    assert "BOT_RANDPIC_DIRS" in body  # 既有锁（test_randpic_identity.py:120）
    for phrase in _CONTENT_CLAIM_PHRASES:
        assert phrase not in body, f"没打开过的目录被说成了『{phrase}』"
    assert any(phrase in body for phrase in _CANT_SEE_PHRASES), body


def test_unreadable_wording_does_not_claim_the_folder_is_empty(tmp_path, monkeypatch) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(os, "walk", _walk_that_reports_one_error)
    body = _run(_config(bot_randpic_dirs=[str(root)])).body
    assert any(phrase in body for phrase in _CANT_SEE_PHRASES), body
    for phrase in _CONTENT_CLAIM_PHRASES:
        assert phrase not in body


def test_empty_dir_wording_may_claim_absence(tmp_path: Path) -> None:
    """真打开过 ⇒ 这次可以有内容断言（与上面两条构成对照，防 B 组锁空跑）。"""
    root = tmp_path / "empty"
    root.mkdir()
    body = _run(_config(bot_randpic_dirs=[str(root)])).body
    assert "一张文件都没有" in body


def test_empty_vs_no_images_wording_are_different_sentences(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    mixed_root = tmp_path / "mixed"
    mixed_root.mkdir()
    (mixed_root / "readme.md").write_text("只有文档", encoding="utf-8")
    empty_body = _run(_config(bot_randpic_dirs=[str(empty_root)])).body
    mixed_body = _run(_config(bot_randpic_dirs=[str(mixed_root)])).body
    assert "一张文件都没有" in empty_body and "图片格式" not in empty_body
    assert "1 个文件" in mixed_body and "一张文件都没有" not in mixed_body


def test_over_limit_wording_names_the_count_and_the_cap(tmp_path: Path) -> None:
    root = tmp_path / "big"
    for index in range(2):
        _write_image(root, f"heavy-{index}.png", b"H" * 40)
    facts = randpic.gallery_facts([str(root)], max_bytes=20)
    line = randpic.gallery_degradation_line(facts, [str(root)], max_bytes=20)
    assert facts.verdict == "over_limit"
    assert "2 张图片" in line and "1 MB" in line and "BOT_RANDPIC_MAX_FILE_MB" in line


def test_unconfigured_wording_names_the_key_and_denies_self_building() -> None:
    body = _run(_config(bot_randpic_dirs=[])).body
    assert "BOT_RANDPIC_DIRS" in body and "绝不自建" in body


def test_audit_tags_only_say_gallery_empty_when_they_may(tmp_path: Path) -> None:
    """``gallery_empty`` 是「打开过、确实没货」的断言：路径不存在时不许贴。"""
    missing = _run(_config(bot_randpic_dirs=[str(tmp_path / "ghost")]))
    assert "gallery_empty" not in missing.audit_tags
    assert "gallery_missing" in missing.audit_tags
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    truly_empty = _run(_config(bot_randpic_dirs=[str(empty_root)]))
    # 既有锁的兼容面：真·空目录那格仍带 gallery_empty（test_randpic_dispatch.py:269）。
    assert "gallery_empty" in truly_empty.audit_tags


def test_capability_never_creates_anything(tmp_path: Path) -> None:
    root = tmp_path / "never-created"
    _run(_config(bot_randpic_dirs=[str(root)]))
    randpic.pick_gallery_image(_config(bot_randpic_dirs=[str(root)]), session_key="private_7")
    assert not root.exists()


def test_unknown_verdict_falls_back_to_no_content_claim(monkeypatch) -> None:
    """认不出的事实代号 ⇒ 兜底句不得含任何内容断言（措辞派生表漏配时的护栏）。"""
    facts = randpic.GalleryFacts(dirs_configured=1, dirs_read=1)
    monkeypatch.setattr(
        type(facts), "verdict", property(lambda self: "brand_new_verdict"), raising=False
    )
    line = randpic.gallery_degradation_line(facts, ["X:/whatever"])
    assert "brand_new_verdict" in line
    for phrase in _CONTENT_CLAIM_PHRASES:
        assert phrase not in line


# ============================================================================
# C 组：取图代价（大小预筛）
# ============================================================================


def test_pick_does_not_hash_the_whole_pool(tmp_path: Path, monkeypatch) -> None:
    """300 张互异大小的库、窗内 2 张 ⇒ 一次取图**真读字节**的张数必须是个位数。

    判据不走 ``outcome.reads``（那只是自报数），而是钉在**唯一摘要真身**
    ``domains/media/digest.py::media_digest_file`` 上数调用：谁绕开记忆化自己扫全库，
    这里一样红。
    """
    from plugins.bot_unified_runtime.domains.media import digest as digest_module

    root = tmp_path / "gallery"
    _gallery(root, 300)
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    for index in range(2):
        randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"warm-{index}", allow_exhausted=False,
        )
    counter = {"n": 0}
    real_digest = digest_module.media_digest_file

    def _spy(path, *args, **kwargs):
        counter["n"] += 1
        return real_digest(path, *args, **kwargs)

    digest_module.media_digest_file = _spy  # type: ignore[assignment]
    try:
        outcome = randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed="probe", allow_exhausted=False,
        )
    finally:
        digest_module.media_digest_file = real_digest  # type: ignore[assignment]
    assert outcome.path is not None
    assert counter["n"] <= 3, f"一次取图真读了 {counter['n']} 张的字节 ⇒ 全库扫描回来了"
    assert outcome.reads <= 3 and outcome.probes <= 3


def test_pick_lock_has_teeth_when_the_size_prefilter_is_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    """注毒自证：把预筛关掉（永远读字节）⇒ 上面那条代价锁必须当场红。"""
    root = tmp_path / "gallery"
    _gallery(root, 120)
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    for index in range(2):
        randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"warm-{index}", allow_exhausted=False,
        )
    monkeypatch.setattr(randpic, "_file_size", lambda path: None)
    # 大小一律读不出 ⇒ 预筛整体失效 ⇒ 必须回落到读字节（fail-closed，不是放行）。
    outcome = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="poison", allow_exhausted=True,
    )
    assert outcome.path is None  # 大小读不出＝这张不在原位 ⇒ 诚实不发，绝不乱发
    assert outcome.reason == "pool_vanished"


def test_same_sized_pool_still_never_repeats(tmp_path: Path) -> None:
    """大小全同 ⇒ 预筛筛不掉任何候选 ⇒ 老老实实读摘要，一条都不许漏放。"""
    root = tmp_path / "uniform"
    made = _gallery(root, 4, distinct_sizes=False)
    assert len({_size(p) for p in made}) == 1
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    seen: list[str] = []
    for index in range(4):
        outcome = randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"u{index}", allow_exhausted=False,
        )
        assert outcome.path is not None, f"库里还有没发过的却拒发：{seen}"
        identity = randpic.image_identity(outcome.path)
        assert identity not in seen, f"同大小库里出现了重发：{seen}"
        seen.append(identity)
        assert outcome.reads >= 1, "同大小却没读摘要 ⇒ 预筛越权当了判据"
    assert len(seen) == 4
    assert (
        randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed="u-after", allow_exhausted=False,
        ).path
        is None
    )


def test_ledger_without_size_fails_closed_to_reading_bytes(tmp_path: Path) -> None:
    """账本没带大小（旧记录/外部直写）⇒ 预筛必须整体失效，退回读字节。"""
    root = tmp_path / "gallery"
    made = _gallery(root, 3)
    window = randpic.RecentImageWindow()
    window.record("private_7", randpic.image_identity(made[0]), window_seconds=3600.0)
    sizes, unknown = window.recent_sizes("private_7", window_seconds=3600.0)
    assert sizes == frozenset() and unknown is True
    outcome = randpic.pick_fresh_outcome(
        [str(root)], session_key="private_7", window=window,
        window_seconds=3600.0, seed="fc", allow_exhausted=False,
    )
    assert outcome.path is not None and outcome.reads >= 1
    assert randpic.image_identity(outcome.path) != randpic.image_identity(made[0])


def test_renamed_picture_is_still_recognised_as_already_sent(tmp_path: Path) -> None:
    """改名不换图：摘要仍是同一条 ⇒ 绝不因路径变了就再发一遍。"""
    root = tmp_path / "gallery"
    made = _gallery(root, 3)
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    first = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="r0", allow_exhausted=False,
    )
    assert first.path is not None
    renamed = root / "owner-renamed.png"
    first.path.rename(renamed)
    randpic._SCAN_CACHE.clear()  # 模拟「用户整理图库后重扫」
    for index in range(1, 3):
        outcome = randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"r{index}", allow_exhausted=False,
        )
        assert outcome.path is not None
        assert randpic.image_identity(outcome.path) != randpic.image_identity(renamed)
        assert str(outcome.path) != str(renamed)


def test_identity_lock_reuses_central_digest_not_a_second_one(tmp_path: Path) -> None:
    """摘要唯一真身 = ``domains/media/digest.py``；本件只截短，不另算一遍。"""
    from plugins.bot_unified_runtime.domains.media import digest as digest_module

    root = tmp_path / "gallery"
    made = _write_image(root, "a.png", b"central-truth")
    calls: list[str] = []
    real = digest_module.media_digest_file

    def _spy(path, *args, **kwargs):
        calls.append(str(path))
        return real(path, *args, **kwargs)

    digest_module.media_digest_file = _spy  # type: ignore[assignment]
    try:
        randpic._IDENTITY_CACHE.clear()
        identity = randpic.image_identity(made)
    finally:
        digest_module.media_digest_file = real  # type: ignore[assignment]
    assert calls == [str(made)], f"读字节走了 {len(calls)} 次别的路 ⇒ 第二真身回来了"
    assert identity == real(str(made))[:16]


# ============================================================================
# D 组：死引用 / 发完了 vs 没翻完 / 提示只当加速道
# ============================================================================


def test_dead_listing_entry_is_dropped_not_returned(tmp_path: Path) -> None:
    """窗关（现网缺省）那条也不能把死引用交给出站链。"""
    root = tmp_path / "gallery"
    made = _gallery(root, 2)
    config = _config(bot_randpic_dirs=[str(root)], bot_randpic_no_repeat_window_seconds=0.0)
    assert randpic.pick_gallery_image(config, session_key="private_7") in made
    for path in made:
        path.unlink()
    assert randpic.pick_random_image([str(root)]) is None, "TTL 清单里的死引用被直接发出去了"
    result = _run(config)
    assert result.images == [] and result.body.strip()
    assert "reason_pool_vanished" in result.audit_tags, result.audit_tags


def test_dead_listing_entry_is_dropped_on_the_open_window_leg(
    tmp_path: Path, monkeypatch
) -> None:
    """开态那条也一样：探到死引用就当场摘掉，别在同一次取图里反复撞它。"""
    root = tmp_path / "gallery"
    made = _gallery(root, 2)
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    made[0].unlink()
    monkeypatch.setattr(
        randpic, "_probe_order", lambda images, seed, *, rng=None: list(images)
    )
    outcome = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="dead", allow_exhausted=False,
    )
    assert outcome.path == made[1]
    assert outcome.probes >= 1  # 死那条被真探过一次并摘掉
    assert made[0] not in randpic.list_gallery_images(dirs)


def test_exhausted_pool_recycle_is_labelled_not_silent(tmp_path: Path) -> None:
    """指令路整库都在窗内仍照发（在册裁定），但账上必须写明这是第二次。"""
    root = tmp_path / "gallery"
    _gallery(root, 1)
    config = _config(bot_randpic_dirs=[str(root)])
    first = _run(config, message_id="m-a")
    second = _run(config, message_id="m-b")
    assert first.images and second.images
    assert "recycled_in_window" not in first.audit_tags
    assert "recycled_in_window" in second.audit_tags
    assert "reason_recycled_least_recent" in second.audit_tags, second.audit_tags


def test_proactive_leg_holds_when_whole_pool_is_in_window(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    _gallery(root, 1)
    config = _config(bot_randpic_dirs=[str(root)])
    session = "group_42_7"
    assert randpic.pick_gallery_image(
        config, session_key=session, seed="poke", allow_exhausted=False
    ) is not None
    outcome = randpic.pick_gallery_image_outcome(
        config, session_key=session, seed="poke", allow_exhausted=False
    )
    assert outcome.path is None and outcome.reason == "held_pool_exhausted"


def test_pool_is_exhausted_predicate_is_the_single_definition() -> None:
    assert randpic.pool_is_exhausted(pool_identities=[], recent=frozenset({"a"})) is False
    assert randpic.pool_is_exhausted(pool_identities=["a"], recent=frozenset()) is False
    assert (
        randpic.pool_is_exhausted(pool_identities=["a", "b"], recent=frozenset({"a", "b", "c"}))
        is True
    )


def test_probe_ceiling_makes_no_exhaustion_claim(tmp_path: Path, monkeypatch) -> None:
    """库比上限大且翻完上限也没翻着 ⇒ 只说「没翻完」，不说「发完了」。"""
    root = tmp_path / "gallery"
    made = _gallery(root, 4)
    window = randpic.RecentImageWindow()
    monkeypatch.setattr(randpic, "_FRESH_PROBE_CEILING", 2)
    for path in made:  # 全库都记进窗账
        window.record(
            "private_7", randpic.image_identity(path), window_seconds=3600.0,
            size=_size(path), path=path,
        )
    dirs = [str(root)]
    held = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="ceiling", allow_exhausted=False,
    )
    assert held.path is None and held.reason == "held_pool_unproven"
    command = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="ceiling2", allow_exhausted=True,
    )
    assert command.path is not None
    assert command.reason == "recycled_unproven", command.reason


def test_path_hint_is_accelerator_not_the_judgment(tmp_path: Path) -> None:
    """账本里的路径必须过摘要复核 ⇒ 提示指错了地方就不许认。"""
    root = tmp_path / "gallery"
    a = _write_image(root, "a.png", b"first-picture!")
    b = _write_image(root, "b.png", b"second-picture")
    identity_a = randpic.image_identity(a)
    window = randpic.RecentImageWindow()
    window.record("s", identity_a, window_seconds=3600.0, size=_size(a), path=b)
    # 提示故意指到 b（另一张图）：复核不过 ⇒ 不许把 b 当成「identity_a 那张」发出去。
    assert window.path_hint_for("s", identity_a, window_seconds=3600.0) == str(b)
    resolved = randpic._resolve_identity_path(
        window,
        session_key="s",
        identity=identity_a,
        pool=[a, b],
        identities={},
        window_seconds=3600.0,
        read_identity=randpic.image_identity,
        ceiling=8,
        state={"reads": 0, "probes": 0},
    )
    assert resolved == a, "摘要复核没起作用（提示说什么就发什么）"
    missing = _write_image(root, "gone.png", b"third-picture!")
    identity_missing = randpic.image_identity(missing)
    window.record("s", identity_missing, window_seconds=3600.0, size=_size(missing), path=missing)
    missing.unlink()
    assert (
        randpic._resolve_identity_path(
            window,
            session_key="s",
            identity=identity_missing,
            pool=[a, b],
            identities={},
            window_seconds=3600.0,
            read_identity=randpic.image_identity,
            ceiling=8,
            state={"reads": 0, "probes": 0},
        )
        is None
    )


def test_newest_path_guard_blocks_a_consecutive_repeat(tmp_path: Path) -> None:
    """身份怎么都对不上时的终极兜底：可以退一张，但绝不退**刚发过**那一张。"""
    root = tmp_path / "gallery"
    a = _write_image(root, "a.png", b"aaaa")
    b = _write_image(root, "b.png", b"bbbb")
    window = randpic.RecentImageWindow()
    identity_a = randpic.image_identity(a)
    identity_b = randpic.image_identity(b)
    window.record("s", identity_a, window_seconds=3600.0, size=_size(a), path=a)
    window.record("s", identity_b, window_seconds=3600.0, size=_size(b), path=b)
    assert window.newest_path("s", window_seconds=3600.0) == str(b)
    # 两张文件内容都被换成别的图 ⇒ 账本里的身份再也对不上 ⇒ 走终极兜底。
    a.write_bytes(PNG_MAGIC + b"brand-new-1")
    b.write_bytes(PNG_MAGIC + b"brand-new-2")
    randpic._IDENTITY_CACHE.clear()
    dirs = [str(root)]
    stream: list[str] = []
    for index in range(4):
        outcome = randpic.pick_fresh_outcome(
            dirs, session_key="s", window=window, window_seconds=3600.0,
            seed=f"g{index}", allow_exhausted=True,
        )
        assert outcome.path is not None
        stream.append(str(outcome.path))
    assert all(stream[i] != stream[i - 1] for i in range(1, len(stream))), stream


def test_two_identical_bytes_copies_are_one_picture(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    root.mkdir()
    payload = PNG_MAGIC + b"same-picture"
    (root / "copy-a.png").write_bytes(payload)
    (root / "copy-b.png").write_bytes(payload)
    (root / "other.png").write_bytes(PNG_MAGIC + b"different")
    dirs = [str(root)]
    window = randpic.RecentImageWindow()
    sent: list[str] = []
    for index in range(3):
        outcome = randpic.pick_fresh_outcome(
            dirs, session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"dup{index}", allow_exhausted=False,
        )
        if outcome.path is None:
            break
        sent.append(randpic.image_identity(outcome.path))
    assert len(sent) == len(set(sent)) == 2, f"同字节副本被当成两张发：{sent}"


def test_same_dir_listed_twice_is_not_two_pictures(tmp_path: Path) -> None:
    """``BOT_RANDPIC_DIRS`` 里同一条目录写两遍 ⇒ 一张图，不该占两次概率。"""
    root = tmp_path / "gallery"
    _gallery(root, 1)
    dirs = [str(root), str(root)]
    window = randpic.RecentImageWindow()
    first = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="t0", allow_exhausted=False,
    )
    second = randpic.pick_fresh_outcome(
        dirs, session_key="private_7", window=window,
        window_seconds=3600.0, seed="t1", allow_exhausted=False,
    )
    assert first.path is not None and second.path is None
    # 对照：没去重的话清单会是两张（出站判据看的是候选条数，不是张数）。
    assert len(randpic.list_gallery_images(dirs)) == 2


def test_seeded_pick_is_reproducible_and_never_touches_random(tmp_path, monkeypatch) -> None:
    """开态带 seed ⇒ 全程零 stdlib random（可复现、可审计、测试不 flaky）。"""

    def _boom(*_args, **_kwargs):
        raise AssertionError("带 seed 的取图路径调用了 stdlib random")

    monkeypatch.setattr(randpic.random, "choice", _boom)
    monkeypatch.setattr(randpic.random, "shuffle", _boom)
    monkeypatch.setattr(randpic.random, "sample", _boom)
    root = tmp_path / "gallery"
    _gallery(root, 6)
    dirs = [str(root)]
    a = randpic.pick_fresh_outcome(
        dirs, session_key="s1", window=randpic.RecentImageWindow(),
        window_seconds=3600.0, seed="same",
    )
    b = randpic.pick_fresh_outcome(
        dirs, session_key="s2", window=randpic.RecentImageWindow(),
        window_seconds=3600.0, seed="same",
    )
    assert a.path is not None and a.path == b.path


def test_no_consecutive_repeat_across_twelve_command_picks(tmp_path: Path) -> None:
    """指令路连发 12 次：相邻两次绝不可能是同一张（ITEM 15(b) 字面口径）。"""
    root = tmp_path / "gallery"
    _gallery(root, 3)
    window = randpic.RecentImageWindow()
    stream: list[str] = []
    for index in range(12):
        outcome = randpic.pick_fresh_outcome(
            [str(root)], session_key="private_7", window=window,
            window_seconds=3600.0, seed=f"cmd:{index}", allow_exhausted=True,
        )
        assert outcome.path is not None
        stream.append(randpic.image_identity(outcome.path))
    repeats = [(i, stream[i]) for i in range(1, len(stream)) if stream[i] == stream[i - 1]]
    assert not repeats, f"连续重复同一张：{repeats}"


def test_legacy_cache_tuple_shape_does_not_crash_the_reader(tmp_path: Path) -> None:
    """既有缓存治理锁会手塞 ``(ts, [])`` 二元组 ⇒ 读数口不许因此打崩。"""
    root = tmp_path / "gallery"
    _gallery(root, 2)
    randpic._SCAN_CACHE[str(root)] = (0.0, [])  # 旧形态／已过期 ⇒ 走重扫
    assert randpic.gallery_facts([str(root)]).usable == 2
    assert randpic._cached_facts((1.0, [])) is randpic._EMPTY_FACTS
    assert randpic._cached_facts((1.0, [], randpic._EMPTY_FACTS)) is randpic._EMPTY_FACTS


def test_scan_cache_lru_cap_still_bounds_the_cache(tmp_path: Path) -> None:
    """加了一格事实不能动 LRU 治理：键数仍封顶 512。"""
    for index in range(randpic._SCAN_CACHE_LRU_CAP + 8):
        randpic._SCAN_CACHE[f"dummy-{index}"] = (0.0, [], randpic._EMPTY_FACTS)
    root = tmp_path / "gallery"
    _gallery(root, 1)
    assert len(randpic.list_gallery_images([str(root)])) == 1
    assert len(randpic._SCAN_CACHE) == randpic._SCAN_CACHE_LRU_CAP == 512
