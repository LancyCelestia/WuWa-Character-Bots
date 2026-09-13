"""config.py 无 before-validator 的 list/dict 字段 JSON 串兜底回归（2026-09-12）。

背景（SMOKE-FIX 移交缺口）：`bot_admin_profiles` /
`bot_disconnect_notice_mail_recipients` / `bot_disconnect_notice_telegram_chat_ids` /
`bot_wiki_entry_pages` 此前没有 before-validator，非 smoke 旁路装载若从环境变量
拿到裸 JSON 字符串（未经 nonebot dotenv 解码）会在 pydantic 校验处
``list_type``/``dict_type`` ValidationError 硬崩。加固语义：仅当输入为 str 且
以 {/[ 开头时尝试 json.loads，合法则解码；非法 JSON / 其他类型原样返回，
交给既有校验，错误信息保持不变。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.config import Config


def _validate(**overrides: object) -> Config:
    values: dict[str, object] = {
        # 防源码树 data/ 回退（e2e 报告 §四.2 教训；路径解析纯字符串无 I/O）。
        "bot_runtime_data_dir": "/tmp/valj-data",
    }
    values.update(overrides)
    return Config.model_validate(values)


def test_admin_profiles_json_string_decodes() -> None:
    config = _validate(
        bot_admin_profiles='[{"qq":"10001","name":"澜汐","role":"super"}]'
    )
    assert config.bot_admin_profiles == [
        {"qq": "10001", "name": "澜汐", "role": "super"}
    ]


def test_admin_profiles_json_object_string_raises_like_before() -> None:
    # 合法 JSON 但不是数组：解码后交给既有校验，与直接传 dict 的行为一致。
    with pytest.raises(ValidationError):
        _validate(bot_admin_profiles='{"qq":"10001"}')


def test_str_list_fields_json_string_decode() -> None:
    config = _validate(
        bot_disconnect_notice_mail_recipients='["a@example.com","b@example.com"]',
        bot_disconnect_notice_telegram_chat_ids='["-100123"]',
        bot_wiki_entry_pages=' ["鳴潮角色列表", "泰缇斯"] ',
    )
    assert config.bot_disconnect_notice_mail_recipients == [
        "a@example.com",
        "b@example.com",
    ]
    assert config.bot_disconnect_notice_telegram_chat_ids == ["-100123"]
    # 首尾空白包裹的 JSON 串同样解码（与文件内既有 before-validator 风格一致）。
    assert config.bot_wiki_entry_pages == ["鳴潮角色列表", "泰缇斯"]


def test_native_list_inputs_behavior_unchanged() -> None:
    config = _validate(
        bot_admin_profiles=[{"qq": "10001"}],
        bot_disconnect_notice_mail_recipients=["a@example.com"],
        bot_disconnect_notice_telegram_chat_ids=["-100123"],
        bot_wiki_entry_pages=["页面"],
    )
    assert config.bot_admin_profiles == [{"qq": "10001"}]
    assert config.bot_disconnect_notice_mail_recipients == ["a@example.com"]
    assert config.bot_disconnect_notice_telegram_chat_ids == ["-100123"]
    assert config.bot_wiki_entry_pages == ["页面"]


def test_invalid_json_string_still_raises_unchanged() -> None:
    # 非法 JSON：原样返回交给既有校验，list_type 错误信息保持加固前形态。
    with pytest.raises(ValidationError) as exc_info:
        _validate(bot_wiki_entry_pages="[broken-json")
    assert "list_type" in str(exc_info.value)


def test_non_json_plain_string_still_raises_unchanged() -> None:
    # 不以 {/[ 开头的字符串（如分号串）不在兜底范围：保持既有报错行为，
    # 不悄悄引入分隔符拆分语义。
    with pytest.raises(ValidationError) as exc_info:
        _validate(bot_disconnect_notice_mail_recipients="a@example.com;b@example.com")
    assert "list_type" in str(exc_info.value)
