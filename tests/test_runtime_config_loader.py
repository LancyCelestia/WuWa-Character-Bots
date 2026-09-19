"""load_runtime_config 唯一配置装载入口回归（Wave G M-68 / T126 席）.

被测：scripts/load_runtime_config.py —— 生产同构的 .env 装载唯一入口
（dotenv 解析 → os.environ 优先 → JSON 解码 → translate_env_keys →
Config.model_validate），四方（生产语义参照 / smoke / 体检器 / 重启门）共用。

锁死三件事：
  1. 生产同构：与 nonebot 自带 DotEnvSettingsSource（生产 bot.py:255
     nonebot.init(_env_file=(".env",".env.prod")) 的真身解析器）逐键对拍，
     并在 Config.model_dump 层整体等价（零行为变更约束）。
  2. 消费方契约：pre_restart_check.load_env / verify_chatbot_env.load_env
     切换后签名与值语义不红。
  3. T24 两处实测分歧不回归：行内注释不假红、.env.prod 覆盖可见。

全离线：tmp_path 夹具 + monkeypatch os.environ，零网络、零 nonebot.init。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import load_runtime_config as lrc
from scripts import pre_restart_check as prc
from scripts import verify_chatbot_env as vce
from scripts.load_runtime_config import (
    config_from_env_values,
    json_decode_env_values,
    load_runtime_config,
    load_runtime_env_values,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _isolated_environ(monkeypatch: pytest.MonkeyPatch, extra: dict[str, str] | None = None) -> None:
    """隔离进程环境：装载链会读 os.environ（优先级），必须钉死."""
    monkeypatch.setattr(os, "environ", dict(extra or {}))


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    env = _write(tmp_path / ".env", [])
    prod = _write(tmp_path / ".env.prod", [])
    return env, prod


# ---------------------------------------------------------------------------
# 值层：load_runtime_env_values
# ---------------------------------------------------------------------------

def test_missing_files_skipped_silently_by_default(tmp_path: Path) -> None:
    loaded = load_runtime_env_values((tmp_path / ".env", tmp_path / ".env.prod"))
    assert loaded.values == {}
    assert loaded.files == ()


def test_required_raises_when_all_missing(tmp_path: Path) -> None:
    files = (tmp_path / ".env", tmp_path / ".env.prod")
    with pytest.raises(lrc.RuntimeEnvNotFoundError):
        load_runtime_env_values(files, required=True)
    with pytest.raises(lrc.RuntimeEnvNotFoundError):
        load_runtime_config(files, required=True)


def test_env_prod_overrides_env(tmp_path: Path) -> None:
    env = _write(tmp_path / ".env", ["BOT_TTS_ENABLED=true"])
    prod = _write(tmp_path / ".env.prod", ["BOT_TTS_ENABLED=false"])
    loaded = load_runtime_env_values((env, prod))
    assert loaded.values["BOT_TTS_ENABLED"] == "false"
    assert [p.name for p in loaded.files] == [".env", ".env.prod"]


def test_inline_comment_stripped_quoted_comment_kept(tmp_path: Path) -> None:
    """T24 f06e 实测分歧：`0.05  # 注释` 好配置不得假红."""
    env = _write(
        tmp_path / ".env",
        [
            "BOT_TTS_AUTO_REPLY_PROBABILITY=0.05  # 注释",
            'BOT_PERSONA_DISPLAY_NAME="守岸人 # 保持"',
            "BOT_TONE_DIRECTNESS=0.4#nospace",
            "BOT_X=a=b",
        ],
    )
    values = load_runtime_env_values((env,)).values
    assert values["BOT_TTS_AUTO_REPLY_PROBABILITY"] == "0.05"
    assert values["BOT_PERSONA_DISPLAY_NAME"] == "守岸人 # 保持"
    assert values["BOT_TONE_DIRECTNESS"] == "0.4#nospace"
    assert values["BOT_X"] == "a=b"


def test_environ_overrides_file_case_insensitively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _write(tmp_path / ".env", ["bot_tone_warmth=0.8"])
    _isolated_environ(monkeypatch, {"BOT_TONE_WARMTH": "0.9"})
    values = load_runtime_env_values((env,)).values
    assert values["bot_tone_warmth"] == "0.9"


def test_file_case_preserved_for_raw_consumers(tmp_path: Path) -> None:
    """pre_restart 等消费方按原键名取值（ONEBOT_WS_URLS 等），键不得被改写."""
    env = _write(tmp_path / ".env", ["ONEBOT_WS_URLS=['ws://127.0.0.1:3001']"])
    values = load_runtime_env_values((env,)).values
    assert "ONEBOT_WS_URLS" in values


# ---------------------------------------------------------------------------
# JSON 解码层（生产 nonebot extras 语义：非空即尝试 json.loads，失败回退原串）
# ---------------------------------------------------------------------------

def test_json_decode_semantics_production_parity() -> None:
    assert json_decode_env_values({"a": '["x","y"]'}) == {"a": ["x", "y"]}
    assert json_decode_env_values({"a": '{"k": 1}'}) == {"a": {"k": 1}}
    assert json_decode_env_values({"a": "{broken"}) == {"a": "{broken"}
    assert json_decode_env_values({"a": "[broken"}) == {"a": "[broken"}
    assert json_decode_env_values({"a": "plain"}) == {"a": "plain"}
    assert json_decode_env_values({"a": ""}) == {"a": ""}
    # 生产实况：裸标量合法 JSON 一并解码（真实 .env 实测 198 处，如 true/2097152/0.4）
    assert json_decode_env_values({"a": "true"}) == {"a": True}
    assert json_decode_env_values({"a": "2097152"}) == {"a": 2097152}
    assert json_decode_env_values({"a": "0.4"}) == {"a": 0.4}


# ---------------------------------------------------------------------------
# Config 层：load_runtime_config
# ---------------------------------------------------------------------------

def test_load_runtime_config_end_to_end_types(tmp_path: Path) -> None:
    _write(
        tmp_path / ".env",
        [
            "BOT_TTS_ENABLED=true",
            'BOT_TTS_REF_AUDIOS=["ref/a.wav|你好|zh"]',
            "BOT_TONE_WARMTH=0.8  # 行内注释",
        ],
    )
    cfg = load_runtime_config((tmp_path / ".env", tmp_path / ".env.prod"), required=True)
    assert cfg.bot_tts_enabled is True
    assert cfg.bot_tts_ref_audios == ["ref/a.wav|你好|zh"]
    assert cfg.bot_tone_warmth == pytest.approx(0.8)


def test_config_from_env_values_is_pure_layer(tmp_path: Path) -> None:
    cfg = config_from_env_values({"BOT_TTS_ENABLED": "false"})
    assert cfg.bot_tts_enabled is False


# ---------------------------------------------------------------------------
# 生产同构对拍锁：nonebot DotEnvSettingsSource（生产真身解析器）逐键 + Config 整体
# ---------------------------------------------------------------------------

_PARITY_LINES_ENV = [
    "BOT_PERSONA_DISPLAY_NAME=守岸人  # 行内注释",
    "BOT_TONE_WARMTH=0.8",
    "BOT_TTS_ENABLED=true",
    'BOT_TTS_REF_AUDIOS=["ref/a.wav|你好|zh"]',
    "onebot_lower_case=x",
    "BOT_TONE_DIRECTNESS=0.2",
]

_PARITY_LINES_PROD = [
    "BOT_TONE_WARMTH=0.9",
    "BOT_TTS_ENABLED=false",
]


def _parity_config() -> Any:
    from plugins.bot_unified_runtime.config import Config

    return Config


def test_parity_with_nonebot_dotenv_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot.config import Config as NBConfig
    from nonebot.config import DotEnvSettingsSource

    from plugins.bot_unified_runtime.config import translate_env_keys

    _isolated_environ(monkeypatch, {"BOT_TONE_DIRECTNESS": "0.4"})
    env = _write(tmp_path / ".env", _PARITY_LINES_ENV)
    prod = _write(tmp_path / ".env.prod", _PARITY_LINES_PROD)

    reference = DotEnvSettingsSource(
        NBConfig,
        env_file=(str(env), str(prod)),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )()

    loaded = load_runtime_env_values((env, prod))
    # 值层 → JSON 解码层 → translate：reference（DotEnvSettingsSource）已含
    # extras JSON 解码（裸标量一并解码），逐键对拍必须在同一层进行。
    translated = translate_env_keys(json_decode_env_values(dict(loaded.values)))
    nb_fields = set(NBConfig.model_fields)

    # 逐键：extras（BOT_* 与任意用户键）与生产真身解析器全等
    for key, value in reference.items():
        if key in nb_fields:
            continue  # nonebot 自有字段（driver/host/...）由 nonebot 实例化消费，不入 bot Config
        assert key in translated, f"生产可见键 {key} 在唯一入口缺失"
        assert translated[key] == value, f"键 {key} 与生产解析不等：{translated[key]!r} != {value!r}"

    # 整体：经生产同一条 Config.model_validate 链后 model_dump 全等
    cfg_prod = _parity_config().model_validate(translate_env_keys(dict(reference)))
    cfg_loader = load_runtime_config((env, prod))
    assert cfg_prod.model_dump() == cfg_loader.model_dump()


# ---------------------------------------------------------------------------
# 消费方切换契约：pre_restart / verify 委托唯一入口
# ---------------------------------------------------------------------------

def test_pre_restart_load_env_delegates(tmp_path: Path) -> None:
    _write(
        tmp_path / ".env",
        ["BOT_TTS_AUTO_REPLY_PROBABILITY=0.05  # 注释", "ONEBOT_WS_URLS=x"],
    )
    env = prc.load_env(tmp_path)
    assert env["BOT_TTS_AUTO_REPLY_PROBABILITY"] == "0.05"
    assert env["ONEBOT_WS_URLS"] == "x"
    assert dict(env) == dict(load_runtime_env_values((tmp_path / ".env", tmp_path / ".env.prod")).values)


def test_verify_load_env_contract(tmp_path: Path) -> None:
    _write(tmp_path / ".env", ["BOT_TTS_ENABLED=true"])
    _write(tmp_path / ".env.prod", ["BOT_TTS_ENABLED=false"])
    values, found = vce.load_env(tmp_path)
    assert values["BOT_TTS_ENABLED"] == "false"
    assert found == [".env", ".env.prod"]


def test_verify_inline_comment_not_false_red(tmp_path: Path) -> None:
    """T24 f06e 假红根治锁：体检器路径上 `0.05  # 注释` 不得再崩."""
    _write(
        tmp_path / ".env",
        ["BOT_TTS_ENABLED=true", "BOT_TTS_AUTO_REPLY_PROBABILITY=0.05  # 注释"],
    )
    values, _found = vce.load_env(tmp_path)
    cfg = config_from_env_values(values)
    assert cfg.bot_tts_auto_reply_probability == pytest.approx(0.05)


def test_default_root_is_repo_root() -> None:
    resolved = lrc.resolve_env_files((".env", ".env.prod"))
    assert resolved == (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.prod")
