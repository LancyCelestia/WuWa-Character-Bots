"""审查 L-10 回归：randpic _SCAN_CACHE 缓存卫生（TTL 之外的键数治理）。

缺陷背景：_SCAN_CACHE 只有 30s TTL，过期键不删、键数无上限——长跑进程
按目录键无界增长。修复：对齐项目 LRU 惯例（runtime/reactions.py
_REACTION_LRU_CAP 先例）——键数封顶 512、触达 move_to_end、超界淘汰
最久未用键；过期键读取时惰性清除后重扫回填；扫描结果语义零变化。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.capabilities import randpic


def _make_image(dir_path: Path, name: str, payload: bytes = b"x") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    file = dir_path / name
    file.write_bytes(payload)
    return file


def _module_key(raw: str) -> str:
    """复刻模块内键构造规则（绝对路径归一后的 str）。"""
    root = Path(str(raw).strip())
    if not root.is_absolute():
        root = Path.cwd() / root
    return str(root)


def test_expired_cache_entry_lazily_cleared_and_rescanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """①过期键：读取时清除并可重扫（新文件可见、键不重复残留）。"""
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    gallery = tmp_path / "图库"
    _make_image(gallery, "a.png")

    first = randpic.list_gallery_images([str(gallery)])
    assert [p.name for p in first] == ["a.png"]

    key = _module_key(str(gallery))
    stale = randpic._SCAN_CACHE[key]
    # 手工把缓存条目拨回 60s 前（越过 30s TTL），旧清单仍是单文件。
    randpic._SCAN_CACHE[key] = (stale[0] - 60.0, stale[1])

    # TTL 窗口内改文件夹：过期后重扫必须看到新图。
    _make_image(gallery, "b.png")
    second = randpic.list_gallery_images([str(gallery)])
    assert sorted(p.name for p in second) == ["a.png", "b.png"]
    # 惰性清除生效：过期条目被替换为新鲜条目（同键不堆积）。
    assert len(randpic._SCAN_CACHE) == 1
    assert randpic._SCAN_CACHE[key][0] > stale[0] - 60.0


def test_scan_cache_key_count_capped_at_512(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """②键数封顶：超界淘汰最久未用键，缓存不超 512。"""
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    now = time.monotonic()
    for i in range(520):
        randpic._SCAN_CACHE[f"dummy-{i}"] = (now, [])

    gallery = tmp_path / "图库"
    _make_image(gallery, "a.png")
    images = randpic.list_gallery_images([str(gallery)])
    # 扫描结果本身不受缓存治理影响。
    assert [p.name for p in images] == ["a.png"]

    # 520 + 1 = 521 → 淘汰 9 个最旧键 → 恰为封顶值。
    assert len(randpic._SCAN_CACHE) == randpic._SCAN_CACHE_LRU_CAP == 512
    assert "dummy-0" not in randpic._SCAN_CACHE  # 最旧的被淘汰
    assert "dummy-519" in randpic._SCAN_CACHE  # 新近的保留
    assert _module_key(str(gallery)) in randpic._SCAN_CACHE  # 刚插入的保留


def test_fresh_cache_hit_reuses_scan_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """③语义零变化：TTL 内命中直接复用缓存清单，不重扫。"""
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    gallery = tmp_path / "图库"
    _make_image(gallery, "a.png")
    first = randpic.list_gallery_images([str(gallery)])
    assert [p.name for p in first] == ["a.png"]

    # TTL 窗口内新增的文件不应出现在命中结果里（30s 后才可见，与改前一致）。
    _make_image(gallery, "b.png")
    second = randpic.list_gallery_images([str(gallery)])
    assert [p.name for p in second] == ["a.png"]
