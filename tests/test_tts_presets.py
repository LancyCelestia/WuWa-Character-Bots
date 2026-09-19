"""中央语音预设表（bot.tts，Wave G G-2 契约层 T61，T54 规格 §2）。

- 预设表是合成参数的**唯一缺省源**（M-43/M-75/M-76 的共同载体）；
- v1 ``shorekeeper`` 预设 = 现状生产生效值收编，**零行为变更**；
- 引擎域值逐字抄 ``report-T53.md`` 机器可读 JSON（**禁自造域值**）；
- ``split_bucket=False`` 为 M-76 死意图显式化（引擎在 speed≠1 时无条件忽略）；
- config 侧唯一新选择键 ``bot_tts_preset``，枚举成员与注册表同步（AST/导入双门）。

全离线，零网络零落盘。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.media import tts_presets
from plugins.bot_unified_runtime.domains.media.tts_presets import (
    DEFAULT_PRESET_ID,
    ENGINE_PARAM_DOMAINS,
    PRESET_REGISTRY,
    resolve_preset,
)

# ---------------------------------------------------------------------------
# §2.2 预设表：v1 = 现状收编，零行为变更
# ---------------------------------------------------------------------------


def test_default_preset_is_shorekeeper() -> None:
    assert DEFAULT_PRESET_ID == "shorekeeper"
    assert set(PRESET_REGISTRY) == {"shorekeeper"}


def test_shorekeeper_v1_values_match_current_production() -> None:
    """v1 每个值都必须等于 T57 时点（d6801ab）生产实际出门值——零行为变更的锁。"""
    preset = PRESET_REGISTRY["shorekeeper"]
    assert preset.preset_id == "shorekeeper"
    assert preset.params == {
        "text_lang": "zh",
        "text_split_method": "cut5",
        "media_type": "wav",
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 0.9,
        "speed_factor": 0.85,
        "batch_size": 1,
        "batch_threshold": 0.75,
        "split_bucket": False,  # M-76：死意图显式化（引擎 speed≠1 时无条件忽略 True）
        "fragment_interval": 0.3,
        "repetition_penalty": 1.35,
        "parallel_infer": True,
    }


def test_split_bucket_explicit_false_is_dead_intent_elimination() -> None:
    """M-76：引擎在 speed_factor≠1 时无条件自动关 split_bucket（TTS.py:1097-1099）。

    生产恒 0.85 ⇒ 旧硬编码 True 每次都被引擎否决；预设显式 False 与实况对齐，
    出门字节级行为不变。
    """
    assert PRESET_REGISTRY["shorekeeper"].params["split_bucket"] is False


def test_seed_policy_derived_and_lexicon_minimal_set() -> None:
    """G2-R3/U-25：seed=cache_key 派生；M-77 词典占位转正=常见符号/单位最小集（T104）。

    最小集口径（不做全量读音规范，人名/专名另波）：只收**替换后语序天然正确**
    的符号；「%」「～」在表内但默认关断（见 test_lexicon_disabled_entries_kill_switch）。
    """
    preset = PRESET_REGISTRY["shorekeeper"]
    assert preset.seed_policy == "derived"
    assert preset.lexicon["℃"] == "摄氏度"
    assert preset.lexicon["℉"] == "华氏度"
    assert preset.lexicon["＆"] == "和"
    assert preset.lexicon["&"] == "和"
    assert preset.lexicon["±"] == "正负"
    assert preset.lexicon["×"] == "乘"
    assert preset.lexicon["÷"] == "除以"
    assert preset.lexicon["°"] == "度"


def test_lexicon_disabled_entries_kill_switch() -> None:
    """M-77 条级关断（T104）：词典条目可逐条关断，关断条目不进生效词典。

    - 「%」：汉语语序是「百分之」**前**置（50%→百分之五十），精确串替换只能
      后缀（50%→「50百分之」= 乱语序），反成回归 ⇒ 默认关断待正则级规则；
    - 「～」：双语义（「3～5天」范围 vs「好呀～」语气尾），精确串替换无法
      分语境 ⇒ 默认关断。
    """
    assert "%" in tts_presets.LEXICON_DISABLED
    assert "～" in tts_presets.LEXICON_DISABLED
    effective = tts_presets.effective_lexicon(PRESET_REGISTRY["shorekeeper"].lexicon)
    assert "%" not in effective
    assert "～" not in effective
    assert "℃" in effective


def test_rationale_records_provenance() -> None:
    """M-75：参数出处链必须有载体——rationale 至少覆盖全部采样参数。"""
    preset = PRESET_REGISTRY["shorekeeper"]
    for key in ("speed_factor", "temperature", "top_k", "top_p", "text_lang"):
        assert preset.rationale.get(key), f"参数 {key} 缺出处（M-75）"


def test_resolve_preset_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        resolve_preset("no-such-preset")


# ---------------------------------------------------------------------------
# §2.5 引擎域值：逐字抄 report-T53.md（禁自造）
# ---------------------------------------------------------------------------


def test_engine_param_domains_match_t53_truth() -> None:
    """T53 §2 WebUI 滑杆域（verified 逐行）；批注坐标也必须指向 T53 报告。"""
    assert ENGINE_PARAM_DOMAINS["top_k"] == (1, 100)
    assert ENGINE_PARAM_DOMAINS["top_p"] == (0.0, 1.0)
    assert ENGINE_PARAM_DOMAINS["temperature"] == (0.0, 1.0)
    assert ENGINE_PARAM_DOMAINS["speed_factor"] == (0.6, 1.65)
    assert ENGINE_PARAM_DOMAINS["repetition_penalty"] == (0.0, 2.0)
    assert ENGINE_PARAM_DOMAINS["fragment_interval"] == (0.01, 1.0)
    assert ENGINE_PARAM_DOMAINS["batch_size"] == (1, 200)


def test_preset_values_within_engine_domains() -> None:
    """预设值必须落在自家域值表内（表内自洽，防「域值抄了、预设越域」）。"""
    for key, (low, high) in ENGINE_PARAM_DOMAINS.items():
        value = float(PRESET_REGISTRY["shorekeeper"].params[key])  # type: ignore[arg-type]
        assert low <= value <= high, f"预设 {key}={value} 越出 T53 域 [{low},{high}]"


# ---------------------------------------------------------------------------
# config 唯一新键 bot_tts_preset + 数值族 Field 域闸（M-35）
# ---------------------------------------------------------------------------


def _config(**overrides: object) -> object:
    from plugins.bot_unified_runtime.config import Config

    return Config(**overrides)  # type: ignore[arg-type]


def test_config_default_preset_key() -> None:
    assert _config().bot_tts_preset == "shorekeeper"  # type: ignore[attr-defined]


def test_config_rejects_unknown_preset() -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_preset="luna")


def test_config_preset_ids_stay_in_sync_with_registry() -> None:
    """config 白名单与注册表键集必须同生（漂移即红）——M-43 单源纪律的门。"""
    from plugins.bot_unified_runtime.config import TTS_PRESET_IDS

    assert set(TTS_PRESET_IDS) == set(PRESET_REGISTRY)


def test_config_sampling_params_reject_out_of_domain_values() -> None:
    """M-35 本体：越界值装载期即拒，不再原样出门（top_k=-5/top_p=9.0 类实跑全通是旧病）。"""
    for field, value in (
        ("bot_tts_top_k", 0),
        ("bot_tts_top_k", 101),
        ("bot_tts_top_p", -0.1),
        ("bot_tts_top_p", 1.5),
        ("bot_tts_temperature", -0.1),
        ("bot_tts_temperature", 1.01),
        ("bot_tts_speed_factor", 0.5),
        ("bot_tts_speed_factor", 1.7),
        ("bot_tts_auto_reply_probability", -0.1),
        ("bot_tts_auto_reply_probability", 1.5),
        ("bot_tts_timeout_seconds", 0.5),
        ("bot_tts_max_chars", -1),
        ("bot_tts_auto_reply_max_chars", -1),
        ("bot_tts_hard_max_chars", -1),
        ("bot_tts_max_audio_bytes", -1),
    ):
        with pytest.raises(ValidationError, match=f"{field}"):
            _config(**{field: value})


def test_config_enums_reject_illegal_members() -> None:
    for field, value in (
        ("bot_tts_text_lang", "klingon"),
        ("bot_tts_text_split_method", "cut99"),
        ("bot_tts_auto_reply_scope", "both"),
    ):
        with pytest.raises(ValidationError):
            _config(**{field: value})


def test_config_text_lang_is_casefolded_at_load() -> None:
    """规格 §1.1：bot 出门前一律 casefold（POST 入口引擎用原值断言，'ZH' 必 400）。"""
    assert _config(bot_tts_text_lang="ZH").bot_tts_text_lang == "zh"  # type: ignore[attr-defined]


def test_config_hard_caps_default_per_g2_r3() -> None:
    """G2-R3：硬顶=2000 字（0=禁配无界取内置常量）+ 8 MiB 字节顶。"""
    config = _config()
    assert config.bot_tts_hard_max_chars == 2000  # type: ignore[attr-defined]
    assert config.bot_tts_max_audio_bytes == 8 * 1024 * 1024  # type: ignore[attr-defined]
    # 0=显式「禁配无界」语义（取内置常量），非法负值已被域闸拒。
    assert _config(bot_tts_hard_max_chars=0).bot_tts_hard_max_chars == 0  # type: ignore[attr-defined]


def test_config_quota_keys_default_off() -> None:
    """U-04：配额缺省关（0=不限制），字节级行为不变。"""
    config = _config()
    assert config.bot_tts_cache_max_bytes == 0  # type: ignore[attr-defined]
    assert config.bot_tts_cache_max_age_days == 0  # type: ignore[attr-defined]


def test_fallback_constants_match_config_defaults() -> None:
    """内置常量（0=禁配无界时的兜底）与 config 缺省同值——双处数字由本门锁死。"""
    config = _config()
    assert tts_presets.HARD_MAX_CHARS_FALLBACK == config.bot_tts_hard_max_chars  # type: ignore[attr-defined]
    assert tts_presets.MAX_AUDIO_BYTES_FALLBACK == config.bot_tts_max_audio_bytes  # type: ignore[attr-defined]
