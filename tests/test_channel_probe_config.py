"""巡检并发/错峰参数化（B-2）回归：config 主路径 → env 兜底 → 默认 + 钳位。

默认参数（background 3 线程 + 0.4s 抖动；manual 8 线程）等价于历史硬编码，
行为回归约束：默认下现网行为不变。
"""

from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace

from plugins.bot_unified_runtime.llm import channel_health as chm
from plugins.bot_unified_runtime.llm.channel_health import (
    ChannelHealthStore,
    probe_all,
)

_PROBE_ENVS = (
    "BOT_CHANNEL_PROBE_THREADS",
    "BOT_CHANNEL_PROBE_MANUAL_THREADS",
    "BOT_CHANNEL_PROBE_JITTER_SECONDS",
)


def _specs(*model_ids: str) -> dict[str, SimpleNamespace]:
    return {
        model_id: SimpleNamespace(
            model_id=model_id,
            model="m",
            base_url="http://probe.test",
            api_key="k",
        )
        for model_id in model_ids
    }


def _clear_env(monkeypatch) -> None:
    for name in _PROBE_ENVS:
        monkeypatch.delenv(name, raising=False)


def _patch_executor(monkeypatch) -> list[int | None]:
    """替换 ThreadPoolExecutor 记录 max_workers，行为委托真身。"""
    created: list[int | None] = []
    real_cls = concurrent.futures.ThreadPoolExecutor

    class RecordingExecutor:
        def __init__(self, max_workers=None, *args, **kwargs) -> None:
            created.append(max_workers)
            self._real = real_cls(max_workers=max_workers)

        def __enter__(self):
            return self._real.__enter__()

        def __exit__(self, *exc_info):
            return self._real.__exit__(*exc_info)

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", RecordingExecutor)
    return created


def _patch_probe_and_sleep(monkeypatch) -> list[float]:
    """探针固定成功（不触网），记录 time.sleep 调用值。"""
    sleeps: list[float] = []
    monkeypatch.setattr(chm, "probe_entry", lambda spec, **kwargs: (True, 42, ""))
    monkeypatch.setattr(chm.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def test_background_uses_config_threads_and_jitter(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    config = SimpleNamespace(bot_channel_probe_threads=5, bot_channel_probe_jitter_seconds=0.7)
    created = _patch_executor(monkeypatch)
    sleeps = _patch_probe_and_sleep(monkeypatch)
    summary = probe_all(config, _specs("a", "b", "c"), store, mode="background")
    assert summary["ok"] == 3
    assert created == [5]
    assert sleeps == [0.7, 0.7]  # 3 次提交之间错峰 2 次


def test_background_jitter_zero_means_no_sleep(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    config = SimpleNamespace(bot_channel_probe_jitter_seconds=0)
    created = _patch_executor(monkeypatch)
    sleeps = _patch_probe_and_sleep(monkeypatch)
    probe_all(config, _specs("a", "b", "c"), store, mode="background")
    assert sleeps == []
    assert created == [3]  # jitter 单独置零不影响线程默认值


def test_defaults_fall_back_to_3_threads_and_04_jitter(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    config = SimpleNamespace()  # 裸脚本 stub：config 无任何字段
    created = _patch_executor(monkeypatch)
    sleeps = _patch_probe_and_sleep(monkeypatch)
    probe_all(config, _specs("a", "b", "c", "d"), store, mode="background")
    assert created == [3]
    assert sleeps == [0.4, 0.4, 0.4]


def test_manual_mode_defaults_to_8_threads(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    config = SimpleNamespace()
    created = _patch_executor(monkeypatch)
    _patch_probe_and_sleep(monkeypatch)
    probe_all(config, _specs("a", "b"), store, mode="manual")
    assert created == [8]  # 手动模式不吃 background 线程数与 jitter


def test_manual_mode_reads_config_override(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    config = SimpleNamespace(bot_channel_probe_manual_threads=2)
    created = _patch_executor(monkeypatch)
    _patch_probe_and_sleep(monkeypatch)
    probe_all(config, _specs("a", "b", "c"), store, mode="manual")
    assert created == [2]


def test_out_of_range_values_are_clamped(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    created = _patch_executor(monkeypatch)
    sleeps = _patch_probe_and_sleep(monkeypatch)

    config = SimpleNamespace(bot_channel_probe_threads=99, bot_channel_probe_jitter_seconds=9.0)
    probe_all(config, _specs("a", "b"), store, mode="background")
    assert created[-1] == 16  # 超上限钳到 16
    assert sleeps == [5.0]  # 抖动钳到 5.0s

    config = SimpleNamespace(bot_channel_probe_threads=-3, bot_channel_probe_jitter_seconds=-1.0)
    probe_all(config, _specs("a", "b"), store, mode="background")
    assert created[-1] == 1  # 0/负数钳到 1
    assert sleeps == [5.0]  # 负抖动钳到 0 → jitter<=0 完全不 sleep


def test_invalid_config_value_falls_back_to_env_then_default(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    created = _patch_executor(monkeypatch)
    sleeps = _patch_probe_and_sleep(monkeypatch)
    config = SimpleNamespace(
        bot_channel_probe_threads="not-a-number",
        bot_channel_probe_jitter_seconds=None,
    )
    # config 非法 → os.environ 兜底。
    monkeypatch.setenv("BOT_CHANNEL_PROBE_THREADS", "6")
    probe_all(config, _specs("a", "b", "c"), store, mode="background")
    assert created == [6]
    assert sleeps == [0.4, 0.4]  # env 未设 jitter → 默认 0.4
    # env 也非法 → 最终默认 3。
    monkeypatch.setenv("BOT_CHANNEL_PROBE_THREADS", "zero")
    probe_all(config, _specs("a", "b", "c"), store, mode="background")
    assert created == [6, 3]
