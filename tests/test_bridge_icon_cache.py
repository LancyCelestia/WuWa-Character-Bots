"""审查 L-09：bridge 图标/logo 进程内 lru 缓存回归。

背景：SVG 指标图标×7 与平台 logo×12 键每次渲染都读盘+strip，内容进程内
不变 → bridge._load_icon_asset 加 functools.lru_cache。本文件锁死：
① 同路径二次调用只读盘一次；
② 不同路径各自缓存、互不干扰；
③ 文件缺失回退语义不变——返回 ""，且 lru_cache 不缓存异常（每次调用照旧
   重试读盘，不做负缓存，与未加缓存前逐位一致）；
④ 缓存可整体清空（发版换根/测试隔离兜底）。

测试卫生：缓存键只有相对路径，本组测试会换 _ICON_ASSET_ROOT，故 autouse
夹具在前后各清一次缓存，防止 tmp 内容泄漏进其它读真实资产的测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.render.card_render import bridge


@pytest.fixture(autouse=True)
def _isolate_icon_cache(monkeypatch: pytest.MonkeyPatch):
    """前后清缓存：前=保证每用例从冷缓存起步；后=防换根内容跨测试泄漏。"""
    bridge._read_icon_asset_cached.cache_clear()
    yield
    monkeypatch.undo()
    bridge._read_icon_asset_cached.cache_clear()


def _count_read_text(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """包一层 Path.read_text 计数器（真实读盘行为不变，只数调用次数）。"""
    counter = {"read_text": 0}
    real_read_text = Path.read_text

    def counting(self: Path, *args: object, **kwargs: object) -> str:
        counter["read_text"] += 1
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting)
    return counter


def _make_icon_root(tmp_path: Path) -> Path:
    root = tmp_path / "iconfont"
    root.mkdir()
    (root / "a.svg").write_text("<svg>a</svg>", encoding="utf-8")
    (root / "b.svg").write_text("<svg>b</svg>", encoding="utf-8")
    return root


def test_same_path_reads_disk_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """① 同路径二次调用命中缓存，只读盘一次。"""
    monkeypatch.setattr(bridge, "_ICON_ASSET_ROOT", _make_icon_root(tmp_path))
    counter = _count_read_text(monkeypatch)

    first = bridge._load_icon_asset("a.svg")
    second = bridge._load_icon_asset("a.svg")

    assert first == second == "<svg>a</svg>"
    assert counter["read_text"] == 1


def test_different_paths_cached_independently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """② 不同路径各自缓存：a/b 交错调用共读盘两次，值不串。"""
    monkeypatch.setattr(bridge, "_ICON_ASSET_ROOT", _make_icon_root(tmp_path))
    counter = _count_read_text(monkeypatch)

    a1 = bridge._load_icon_asset("a.svg")
    b1 = bridge._load_icon_asset("b.svg")
    a2 = bridge._load_icon_asset("a.svg")
    b2 = bridge._load_icon_asset("b.svg")

    assert (a1, b1, a2, b2) == ("<svg>a</svg>", "<svg>b</svg>", "<svg>a</svg>", "<svg>b</svg>")
    assert counter["read_text"] == 2


def test_missing_path_fallback_semantics_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """③ 缺失路径：每次调用回退 ""，且失败不进缓存（逐次重试，同旧行为）。"""
    monkeypatch.setattr(bridge, "_ICON_ASSET_ROOT", _make_icon_root(tmp_path))
    counter = _count_read_text(monkeypatch)

    first = bridge._load_icon_asset("missing.svg")
    second = bridge._load_icon_asset("missing.svg")

    assert first == second == ""
    # lru_cache 不缓存异常 → 每次调用都真实重试读盘（契约零变化的关键）。
    assert counter["read_text"] == 2


def test_empty_path_returns_empty_without_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """空相对路径直接回 ""，不产生任何读盘（原短路语义保持）。"""
    monkeypatch.setattr(bridge, "_ICON_ASSET_ROOT", _make_icon_root(tmp_path))
    counter = _count_read_text(monkeypatch)

    assert bridge._load_icon_asset("") == ""
    assert counter["read_text"] == 0


def test_cache_clear_forces_reload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """④ cache_clear 后强制重读（发版换根/测试隔离的兜底语义）。"""
    monkeypatch.setattr(bridge, "_ICON_ASSET_ROOT", _make_icon_root(tmp_path))
    counter = _count_read_text(monkeypatch)

    bridge._load_icon_asset("a.svg")
    bridge._read_icon_asset_cached.cache_clear()
    again = bridge._load_icon_asset("a.svg")

    assert again == "<svg>a</svg>"
    assert counter["read_text"] == 2
