"""id-list 键的裸标量宽容装载（2026-09-21 生产启动链实炸复现）。

现场：00:37 生产 .env 把三枚 id-list 键写成了不带引号的裸数字
    BOT_EMERGENCY_INFO_PUSH_USER_IDS=3865067623
    BOT_EMERGENCY_INFO_REVIEWER_IDS=3865067623
    BOT_EMERGENCY_INFO_PUSH_GROUP_WHITELIST=1108838060
装载链（生产同构：load_runtime_env_values → json_decode_env_values → Config.model_validate）
里 json.loads("3865067623") 先解成 int，`_parse_id_list` 只认 list/JSON数组串/分隔串
⇒ 抛 TypeError ⇒ **整插件装载失败，bot 重启起不来**。

同文件已有的 `_coerce_scalar_id_to_str`（793e647 那笔）治的是标量 id 键，没覆盖 id-list 键；
这里按同一口径补：裸标量语义无歧义，收编成单元素列表；bool 显式排除（防 True→"True"）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.config import Config, translate_env_keys
from scripts.load_runtime_config import json_decode_env_values

_LIST_KEYS = (
    "bot_emergency_info_push_user_ids",
    "bot_emergency_info_reviewer_ids",
    "bot_emergency_info_push_group_whitelist",
)


@pytest.mark.parametrize("key", _LIST_KEYS)
def test_bare_scalar_id_is_accepted_as_a_one_element_list(key):
    """裸 int（生产 .env 经 JSON 装载后的实际形态）必须收编成单元素列表，
    而不是抛 TypeError 让整份 Config 装载失败。直接喂字段名，绕开键翻译噪音。"""
    cfg = Config.model_validate({key: 3865067623})
    assert getattr(cfg, key) == ["3865067623"]


def test_production_load_chain_accepts_the_real_env_shape():
    """端到端：字符串经 JSON 装载变 int 后，整条链必须装载成功且值不丢。

    这条锁的是今天真正炸掉 bot 启动的那个形态（.env 里写裸数字）。
    """
    decoded = json_decode_env_values({"BOT_EMERGENCY_INFO_REVIEWER_IDS": "3865067623"})
    assert isinstance(decoded["BOT_EMERGENCY_INFO_REVIEWER_IDS"], int), "装载链确实会产出裸标量"
    cfg = Config.model_validate({"bot_emergency_info_reviewer_ids": decoded[
        "BOT_EMERGENCY_INFO_REVIEWER_IDS"]})
    assert cfg.bot_emergency_info_reviewer_ids == ["3865067623"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('["3865067623", "1722380002"]', ["3865067623", "1722380002"]),  # JSON 数组串
        ("3865067623;1722380002", ["3865067623", "1722380002"]),        # 分隔串
        ("", []),                                                        # 空 ⇒ 空列表
        ([3865067623, " 1722380002 "], ["3865067623", "1722380002"]),   # 真 list
    ],
)
def test_existing_accepted_shapes_are_unchanged(value, expected):
    assert Config.model_validate(
        translate_env_keys({"BOT_EMERGENCY_INFO_REVIEWER_IDS": value})
    ).bot_emergency_info_reviewer_ids == expected


def test_bool_still_rejected_not_silently_stringified():
    """bool 不能被当成 id（True→"True"），必须继续报错。
    TypeError 是 pydantic 不包装、原样外抛的那一类（实测口径）。"""
    with pytest.raises(TypeError):
        Config.model_validate(translate_env_keys({"BOT_EMERGENCY_INFO_REVIEWER_IDS": True}))


def test_garbage_container_still_rejected():
    """非 id-list 的容器（set/自定义对象）仍按原口径拒绝，别把守卫焊成永真。"""
    with pytest.raises(TypeError):
        Config.model_validate(
            translate_env_keys({"BOT_EMERGENCY_INFO_REVIEWER_IDS": {"a", "b"}})
        )
