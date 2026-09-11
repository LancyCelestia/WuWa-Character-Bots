"""DATAFIX 回归（2026-09-12）：运行时数据路径永落 Runtime 根，绝不写源码树。

背景：源码树 data/ 曾泄漏三个文件——platform_cookies.txt、reflection.sqlite3、
usage_report_state.json。根因是三类入口绕过 BOT_RUNTIME_DATA_DIR 重映射：

1. config 校验器 path_fields 遗漏 bot_usage_report_state_file（默认值保持
   CWD 相对路径，usage_monitor 按 CWD 解析落盘）；
2. cookies._resolve_relative_cookie_path 只读进程 env 不读 dotenv，
   dotenv-only 入口回退 project_root/data（platform_credentials 写入即泄漏）；
3. 消费点 getattr 兜底默认值（reflection/music/epic/steam）是纯相对路径。

本文件在「env 设置」与「env 未设置（dotenv 亦空）」两种环境下断言解析结果，
锁定源码树 data/ 不再成为解析目标。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import runtime_paths
from scripts.runtime_paths import runtime_data_dir, runtime_path

# 三个曾泄漏到源码树的文件（data/ 相对默认值）。
LEAKED_RELATIVE_PATHS = (
    "data/platform_cookies.txt",
    "data/reflection.sqlite3",
    "data/usage_report_state.json",
)

# config 校验器必须覆盖的字段（含 DATAFIX 前遗漏的）。
RESOLVED_CONFIG_FIELDS = (
    "bot_usage_report_state_file",
    "bot_media_registry_path",
    "bot_music_dir",
    "bot_mood_db_path",
    "bot_quirks_db_path",
    "bot_session_identity_db_path",
    "bot_reminder_db_path",
    "bot_affinity_db_path",
    "bot_reflection_db_path",
    "bot_cookies_file",
)


def _isolate_dotenv(monkeypatch: pytest.MonkeyPatch, value: str = "") -> None:
    """env 未设置场景下屏蔽真实 .env，令数据根解析完全确定。"""
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    monkeypatch.setattr(runtime_paths, "_dotenv_value", lambda key: value)


def test_runtime_path_env_set_remaps_leaked_defaults(tmp_path: Path, monkeypatch) -> None:
    """env 设置时：data/ 相对值必须重映射进 env 指定的数据根。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    for raw in LEAKED_RELATIVE_PATHS:
        resolved = runtime_path(raw)
        assert resolved == (tmp_path / Path(raw).name).resolve()
        assert PROJECT_ROOT / "data" not in resolved.parents


def test_runtime_path_env_set_handles_data_root_and_case(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert runtime_path("data") == tmp_path.resolve()
    assert runtime_path("./DATA/x.txt") == (tmp_path / "x.txt").resolve()


def test_runtime_path_non_data_relative_stays_project_rooted(tmp_path: Path, monkeypatch) -> None:
    """非 data/ 前缀的相对值保持「项目根相对」契约（与 runtime_paths 文档一致）。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert runtime_path("foo/bar.txt") == (PROJECT_ROOT / "foo" / "bar.txt").resolve()


def test_runtime_data_dir_unset_follows_dotenv_then_source_default(
    tmp_path: Path, monkeypatch
) -> None:
    """env 未设置：dotenv 命中则用 dotenv；两者皆空才回退源码 data/（既有默认）。"""
    _isolate_dotenv(monkeypatch)
    assert runtime_data_dir() == (PROJECT_ROOT / "data").resolve()
    _isolate_dotenv(monkeypatch, str(tmp_path))
    assert runtime_data_dir() == tmp_path.resolve()


def test_config_resolver_covers_all_runtime_data_fields(tmp_path: Path, monkeypatch) -> None:
    """Config 构造后全部 data/ 字段必须是数据根下的绝对路径（含此前遗漏项）。"""
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    from plugins.bot_unified_runtime.config import Config

    config = Config(bot_runtime_data_dir=str(tmp_path))
    for name in RESOLVED_CONFIG_FIELDS:
        raw = str(getattr(config, name))
        if not raw.strip():
            # 空值语义 = 功能关闭（如 bot_cookies_file 留空匿名解析），保持为空。
            continue
        value = Path(raw)
        assert value.is_absolute(), f"{name} 未被重映射: {value}"
        assert value == (tmp_path / value.name).resolve(), f"{name} 指向错误数据根"
        assert PROJECT_ROOT / "data" not in value.parents, f"{name} 落在源码树"


def test_cookie_relative_path_uses_dotenv_aware_root(tmp_path: Path, monkeypatch) -> None:
    """cookies 解析（platform_credentials 写入共用）env 与 dotenv 双通道生效。"""
    from plugins.bot_unified_runtime.sources.parsers.cookies import (
        _resolve_relative_cookie_path,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    resolved = _resolve_relative_cookie_path(Path("data/platform_cookies.txt"))
    assert resolved == (tmp_path / "platform_cookies.txt").resolve()

    _isolate_dotenv(monkeypatch, str(tmp_path))
    resolved = _resolve_relative_cookie_path(Path("data/platform_cookies.txt"))
    assert resolved == (tmp_path / "platform_cookies.txt").resolve()


def test_platform_credentials_write_target_never_source_tree(
    tmp_path: Path, monkeypatch
) -> None:
    """/bot cookie 写入路径与读取路径同源，env 设置时绝不指向源码树。"""
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.capabilities.platform_credentials import (
        _resolve_cookie_file,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    target = _resolve_cookie_file(
        SimpleNamespace(bot_cookies_file="data/platform_cookies.txt")
    )
    assert target is not None
    assert target == (tmp_path / "platform_cookies.txt").resolve()
    assert PROJECT_ROOT / "data" not in target.parents


@pytest.mark.parametrize("module_name", ["platforms_epic", "platforms_steam"])
def test_epic_steam_cookie_candidates_prefer_runtime_root(
    tmp_path: Path, monkeypatch, module_name: str
) -> None:
    """epic/steam 只读候选首位必须落在数据根（dotenv-only 入口也不跳源码树）。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BOT_COOKIES_FILE", raising=False)
    module = __import__(
        f"plugins.bot_unified_runtime.sources.parsers.{module_name}",
        fromlist=["_cookie_file_candidates"],
    )
    candidates = module._cookie_file_candidates()
    assert candidates, "候选列表不应为空"
    assert candidates[0] == (tmp_path / "platform_cookies.txt").resolve()


def test_music_default_dir_routes_to_runtime_root(tmp_path: Path, monkeypatch) -> None:
    """点歌试听下载目录：相对默认值落数据根；绝对配置原样保留。"""
    from plugins.bot_unified_runtime.capabilities.music import _resolve_music_data_dir

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert _resolve_music_data_dir("data/music") == (tmp_path / "music").resolve()

    absolute = tmp_path / "custom_music"
    assert _resolve_music_data_dir(str(absolute)) == absolute

    _isolate_dotenv(monkeypatch, str(tmp_path))
    assert _resolve_music_data_dir("data/music") == (tmp_path / "music").resolve()
