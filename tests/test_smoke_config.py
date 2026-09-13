"""smoke 配置装载 JSON 键回归（2026-09-12 真机验收阻塞项修复）。

被测：smoke.load_smoke_config 对 .env 里 JSON 列表/字典键（生产
BOT_ADMIN_PROFILES 等）的解析——须与 NoneBot dotenv 用户键解析同语义
（合法 JSON 解码、失败回退字符串），否则裸字符串进 pydantic 会在
``Config.model_validate`` 直接 ``list_type`` 崩溃，挡死 e2e_acceptance。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.smoke import (
    _json_decode_env_values,
    load_smoke_config,
)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """隔离进程环境：load_smoke_config 会向 os.environ 注入键。"""
    monkeypatch.setattr(os, "environ", dict(os.environ))
    yield


def _write_env(tmp_path: Path, lines: list[str]) -> Path:
    env_file = tmp_path / ".env.smoke-test"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def _base_lines(tmp_path: Path) -> list[str]:
    # BOT_RUNTIME_DATA_DIR 必须显式指到 tmp：缺省会回退源码树 data/。
    return [
        "BOT_CHAT_PROVIDER=static",
        f"BOT_RUNTIME_DATA_DIR={tmp_path.as_posix()}",
    ]


def test_load_smoke_config_parses_json_list_and_dict_keys(
    tmp_path: Path, isolated_env: None
) -> None:
    admin_profiles_json = (
        '[{"qq":"10001","name":"澜汐","role":"super","note":"测试"}]'
    )
    model_registry_json = (
        '{"default":{"model":"m1","base_url":"https://example.invalid"}}'
    )
    env_file = _write_env(
        tmp_path,
        _base_lines(tmp_path)
        + [
            f"BOT_ADMIN_PROFILES={admin_profiles_json}",
            'BOT_SUPER_ADMIN_USER_IDS=["10001","10002"]',
            f"BOT_MODEL_REGISTRY={model_registry_json}",
        ],
    )
    config = load_smoke_config(env_file)
    assert config.bot_admin_profiles == [
        {"qq": "10001", "name": "澜汐", "role": "super", "note": "测试"}
    ]
    assert config.bot_super_admin_user_ids == ["10001", "10002"]
    assert config.bot_model_registry["default"]["model"] == "m1"


def test_load_smoke_config_keeps_delimiter_and_plain_values(
    tmp_path: Path, isolated_env: None
) -> None:
    env_file = _write_env(
        tmp_path,
        _base_lines(tmp_path)
        + [
            "BOT_SUPER_ADMIN_USER_IDS=10001;20002",
            "BOT_PERSONA_DISPLAY_NAME=守岸人",
            "BOT_SMOKE_JSONFIX_MARKER=hello",
        ],
    )
    config = load_smoke_config(env_file)
    assert config.bot_super_admin_user_ids == ["10001", "20002"]
    assert config.bot_persona_display_name == "守岸人"
    # 进程环境注入保持原始字符串形态（与真实部署 env var 一致）。
    assert os.environ["BOT_SMOKE_JSONFIX_MARKER"] == "hello"


def test_load_smoke_config_invalid_json_falls_back_to_string(
    tmp_path: Path, isolated_env: None
) -> None:
    # 以 { 开头但非法的 JSON：解码回退字符串，再交给主配置 lenient
    # validator 降级（bot_model_registry 解析失败 → 空 dict），不硬崩。
    env_file = _write_env(
        tmp_path,
        _base_lines(tmp_path) + ["BOT_MODEL_REGISTRY={broken-json"],
    )
    config = load_smoke_config(env_file)
    assert config.bot_model_registry == {}


def test_json_decode_env_values_semantics() -> None:
    assert _json_decode_env_values({"a": '["x","y"]'}) == {"a": ["x", "y"]}
    assert _json_decode_env_values({"a": '{"k": 1}'}) == {"a": {"k": 1}}
    assert _json_decode_env_values({"a": "{broken"}) == {"a": "{broken"}
    assert _json_decode_env_values({"a": "[broken"}) == {"a": "[broken"}
    assert _json_decode_env_values({"a": "plain"}) == {"a": "plain"}
    assert _json_decode_env_values({"a": ""}) == {"a": ""}
