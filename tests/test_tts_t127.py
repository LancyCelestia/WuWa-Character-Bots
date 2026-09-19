"""T127 终补席：``_output_dir`` 空串兜底 Runtime 语义锁（M-52 第二半）。

背景（T125 移交 + 台账 #1 同族）：``plugins/bot_unified_runtime/domains/media/
capabilities/tts.py`` ``_output_dir`` 旧体 ``or "data/tts_output"`` 的兜底是
CWD 相对路径——显式配空串时语音产物可落源码树 ``data/``。修复后兜底经
``scripts.runtime_paths.runtime_path`` 落 Runtime 数据根，三态语义与
config path_fields（T125 已入 ``bot_tts_output_dir``）对齐：

- 绝对 / 已解析配置值 → 原样透传（不二次改写）；
- 空串（含纯空白）缺省 → ``<Runtime 数据根>/tts_output``（绝对路径，
  不再可能 CWD/源码树落点）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod


def _config(output_dir: object) -> SimpleNamespace:
    return SimpleNamespace(bot_tts_output_dir=output_dir)


def test_output_dir_empty_falls_back_to_runtime_data_root(
    tmp_path: Path, monkeypatch: object
) -> None:
    """空串缺省不再按 CWD 解析：兜底落 BOT_RUNTIME_DATA_DIR 指向的 Runtime 根。"""
    runtime_root = tmp_path / "rt"
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(runtime_root))  # type: ignore[attr-defined]
    result = tts_mod._output_dir(_config(""))
    assert result == (runtime_root / "tts_output").resolve(), (
        "空串兜底必须落 Runtime 数据根（runtime_paths 语义），"
        f"实际={result!r}"
    )
    assert result.is_absolute(), "兜底必须是绝对落点（CWD 相对=源码树污染面）"


def test_output_dir_blank_whitespace_treated_as_unconfigured(
    tmp_path: Path, monkeypatch: object
) -> None:
    """纯空白=未配置：同走 Runtime 兜底，不再产出 ``Path("   ")`` 形态。"""
    runtime_root = tmp_path / "rt"
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(runtime_root))  # type: ignore[attr-defined]
    result = tts_mod._output_dir(_config("   "))
    assert result == (runtime_root / "tts_output").resolve()


def test_output_dir_absolute_value_passthrough(tmp_path: Path) -> None:
    """绝对配置值原样透传（T125 三态锁第 1 态；不二次改写）。"""
    target = tmp_path / "abs_out"
    assert tts_mod._output_dir(_config(str(target))) == target


def test_output_dir_missing_attr_also_runtime_fallback(
    tmp_path: Path, monkeypatch: object
) -> None:
    """极端残缺 config（属性缺失）：getattr 缺省同样走 Runtime 兜底。"""
    runtime_root = tmp_path / "rt"
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(runtime_root))  # type: ignore[attr-defined]
    result = tts_mod._output_dir(SimpleNamespace())
    assert result == (runtime_root / "tts_output").resolve()
