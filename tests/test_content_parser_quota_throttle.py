"""审查 L-08 回归：渲染配额巡检 60s 限频（全离线，不触网不真睡）。

锁定四件事：
- 60s 窗内多次渲染只触发 1 次真实 enforce_quota 扫描（注入时钟+计数 spy）；
- 窗口过后下一次渲染恢复巡检；恰好 60s 边界即触发（语义=「间隔 <60s 跳过」）；
- enforce_quota 本身超限淘汰语义零变化（真实函数直测：最旧先删、配额内不动）；
- 巡检被跳过不影响渲染产物落盘（卡 PNG 照常写出）。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import plugins.bot_unified_runtime.capabilities.content_parser as cp
import plugins.bot_unified_runtime.runtime.cache_policy as cache_policy
from plugins.bot_unified_runtime.contracts.media import build_parsed_content


# ---------------------------------------------------------------------------
# 打桩：注入时钟 / enforce_quota 计数 spy / 假渲染后端。
# ---------------------------------------------------------------------------


class _FakeClock:
    """可推进的单调时钟：替换 cp._quota_clock，测试内手动 advance。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(cp, "_quota_clock", clock)
    monkeypatch.setattr(cp, "_quota_last_sweep", 0.0)
    return clock


@pytest.fixture()
def sweep_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """包一层计数 spy：真实 enforce_quota 照常执行（rglob 扫真实目录）。"""
    calls = {"n": 0}
    real = cache_policy.enforce_quota

    def spy(directory: Any, **kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        return real(directory, **kwargs)

    monkeypatch.setattr(cache_policy, "enforce_quota", spy)
    return calls


class _FakeBackend:
    available = True

    def render_card(self, payload: dict) -> bytes:
        # 非 PNG 字节：PIL 裁剪分支静默失败用原字节，测试无需真出图。
        return b"fake-png"


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_persona_display_name="",
        bot_persona_avatar_url="",
        bot_card_cache_max_bytes=0,
    )


def _item() -> Any:
    return build_parsed_content(
        platform="bilibili",
        item_id="v1",
        item_kind="video",
        title="标题",
        author_name="某UP主",
        summary="简介",
        cover_url="",
        canonical_url="https://example.com/v",
        stats={"点赞": 1},
        page_type="video",
    )


def _render(card_dir: Path) -> dict | None:
    return cp.render_card_png(
        _FakeBackend(),
        _item(),
        config=_config(),
        card_dir=str(card_dir),
    )


# ---------------------------------------------------------------------------
# 限频行为。
# ---------------------------------------------------------------------------


def test_multiple_renders_within_window_sweep_once(
    tmp_path: Path, fake_clock: _FakeClock, sweep_spy: dict[str, int]
) -> None:
    """60s 窗内连渲染 3 次：只有第 1 次触发真实 enforce_quota 扫描。"""
    card_dir = tmp_path / "cards"
    for _ in range(3):
        result = _render(card_dir)
        assert result is not None
    assert sweep_spy["n"] == 1


def test_sweep_resumes_after_window(
    tmp_path: Path, fake_clock: _FakeClock, sweep_spy: dict[str, int]
) -> None:
    """窗内跳过、恰好满 60s 后恢复巡检（<60s 才跳过，边界即触发）。"""
    card_dir = tmp_path / "cards"
    assert _render(card_dir) is not None
    assert sweep_spy["n"] == 1

    fake_clock.advance(59.9)
    assert _render(card_dir) is not None
    assert sweep_spy["n"] == 1  # 仍在窗内：跳过

    fake_clock.advance(0.1)  # 距上次巡检恰好 60.0s
    assert _render(card_dir) is not None
    assert sweep_spy["n"] == 2  # 窗后恢复巡检


def test_render_artifact_written_even_when_sweep_skipped(
    tmp_path: Path, fake_clock: _FakeClock, sweep_spy: dict[str, int]
) -> None:
    """巡检被跳过不影响渲染产物：卡 PNG 照常落盘（同 digest 同名）。"""
    first = _render(tmp_path / "cards")
    assert first is not None
    fake_clock.advance(1.0)
    second = _render(tmp_path / "cards")
    assert second is not None
    assert Path(first["file"]).exists()
    assert Path(second["file"]) == Path(first["file"])
    assert sweep_spy["n"] == 1


# ---------------------------------------------------------------------------
# enforce_quota 本身语义零变化（真实函数直测，L-08 只改触发频率）。
# ---------------------------------------------------------------------------


def test_enforce_quota_eviction_semantics_unchanged(tmp_path: Path) -> None:
    """超限按最旧先删淘汰至配额内；配额内零删除。"""
    root = tmp_path / "quota"
    root.mkdir()
    files: list[Path] = []
    for i in range(4):
        path = root / f"f{i}.png"
        path.write_bytes(b"x" * 100)
        os.utime(path, (1000 + i, 1000 + i))  # mtime 递增 → 最旧先删
        files.append(path)

    report = cache_policy.enforce_quota(root, max_bytes=250)
    assert report["files_removed"] == 2
    assert report["bytes_removed"] == 200
    assert not files[0].exists()
    assert not files[1].exists()
    assert files[2].exists()
    assert files[3].exists()

    # 配额内：不删任何文件。
    report_within = cache_policy.enforce_quota(root, max_bytes=100_000)
    assert report_within["files_removed"] == 0
    assert report_within["bytes_removed"] == 0
