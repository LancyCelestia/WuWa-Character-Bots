"""/bot identity 用户自助称谓偏好（Task 2）：set-name/set-gender/unset-name/unset-gender。

全离线：store 一律 tmp_path 自建 + monkeypatch 注入，禁止写真实库；
接线层（runtime_admin 拦截 + __init__ 传参）只做行为断言，不落真实 session_identity 库。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.echo import (
    HELP_ENTRIES,
    build_identity_preference_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    providers as providers_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)

_GENDER_WORDS = ("male", "female", "nonbinary", "custom", "unknown")


class _FakeConfig:
    """处理器只经 build_addressing_preference_store(config) 触达存储（测试中已被替换）。"""


@pytest.fixture()
def store(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> AddressingPreferenceStore:
    real = AddressingPreferenceStore(tmp_path / "addressing_preferences.sqlite3")
    monkeypatch.setattr(
        providers_module, "build_addressing_preference_store", lambda _config: real
    )
    return real


def _run(store_fixture: AddressingPreferenceStore, text: str, *, group_id: str = "g1") -> Any:
    return build_identity_preference_result(
        _FakeConfig(),
        request_id="req-identity-pref",
        sender_id="u1",
        group_id=group_id,
        command_text=text,
    )


# --------------------------------------------------------------------------
# set-name：写入发送者本人的称谓偏好（群=群键位，私聊=空 session_id）
# --------------------------------------------------------------------------


def test_set_name_in_group_uses_group_keys(store: AddressingPreferenceStore) -> None:
    result = _run(store, "set-name 岸宝")
    assert result.kind == "text"
    assert "岸宝" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "unknown")


def test_set_name_in_private_uses_empty_session_id(store: AddressingPreferenceStore) -> None:
    result = _run(store, "set-name 旅人", group_id="")
    assert "旅人" in result.body
    assert store.get(session_type="private", session_id="", sender_id="u1") == ("旅人", "unknown")


def test_set_name_only_affects_sender_self(store: AddressingPreferenceStore) -> None:
    _run(store, "set-name 岸宝")
    assert store.get(session_type="group", session_id="g1", sender_id="u2") == ("", "unknown")


def test_set_name_blank_value_replies_usage_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name")
    assert "用法" in result.body and "set-name" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_set_name_overlong_value_rejected_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name " + "超" * 40)
    assert "太长" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


# --------------------------------------------------------------------------
# set-gender：合法值大小写不敏感；非法值不落库并列出可接受值
# --------------------------------------------------------------------------


def test_set_gender_accepts_known_values_case_insensitive(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-gender FEMALE")
    assert result.kind == "text"
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "female")


def test_set_gender_partial_update_keeps_name(store: AddressingPreferenceStore) -> None:
    _run(store, "set-name 岸宝")
    _run(store, "set-gender nonbinary")
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == (
        "岸宝",
        "nonbinary",
    )


def test_set_gender_invalid_value_lists_choices_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-gender attack-helicopter")
    for word in _GENDER_WORDS:
        assert word in result.body, word
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


# --------------------------------------------------------------------------
# unset-name / unset-gender：整行清除语义 + 未设置时的诚实回复
# --------------------------------------------------------------------------


def test_unset_name_clears_whole_row(store: AddressingPreferenceStore) -> None:
    _run(store, "set-name 岸宝")
    _run(store, "set-gender male")
    result = _run(store, "unset-name")
    assert result.kind == "text"
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_unset_gender_clears_whole_row(store: AddressingPreferenceStore) -> None:
    _run(store, "set-gender male")
    _run(store, "unset-gender")
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_unset_without_any_setting_replies_honestly(store: AddressingPreferenceStore) -> None:
    result = _run(store, "unset-name")
    assert "没有" in result.body


# --------------------------------------------------------------------------
# 用法与降级
# --------------------------------------------------------------------------


def test_usage_lists_all_four_subcommands(store: AddressingPreferenceStore) -> None:
    for text in ("", "show"):
        result = _run(store, text)
        for sub in ("set-name", "set-gender", "unset-name", "unset-gender"):
            assert sub in result.body, (text, sub)


def test_missing_store_degrades_to_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        providers_module, "build_addressing_preference_store", lambda _config: None
    )
    result = build_identity_preference_result(
        _FakeConfig(),
        request_id="req-none",
        sender_id="u1",
        group_id="",
        command_text="set-name 岸宝",
    )
    assert result.kind == "text"
    assert "不可用" in result.body or "暂" in result.body


def test_missing_sender_id_rejected(store: AddressingPreferenceStore) -> None:
    result = build_identity_preference_result(
        _FakeConfig(),
        request_id="req-nosender",
        sender_id="",
        group_id="g1",
        command_text="set-name 岸宝",
    )
    assert "无法" in result.body


# --------------------------------------------------------------------------
# 接线：管理员门前拦截（普通用户可用）+ 旧管理员子命令门禁不回归
# --------------------------------------------------------------------------


def test_non_admin_reaches_preference_subcommand_via_admin_entrypoint(
    store: AddressingPreferenceStore,
) -> None:
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        build_session_identity_admin_result,
    )

    result = build_session_identity_admin_result(
        _FakeConfig(),
        request_id="req-wire",
        actor_roles=["user"],
        session_key="group_g1",
        sender_id="u1",
        group_id="g1",
        command_text="set-name 岸宝",
    )
    assert "岸宝" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "unknown")


def test_legacy_admin_subcommands_still_admin_gated(
    store: AddressingPreferenceStore,
) -> None:
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        build_session_identity_admin_result,
    )

    result = build_session_identity_admin_result(
        _FakeConfig(),
        request_id="req-gate",
        actor_roles=["user"],
        session_key="group_g1",
        sender_id="u1",
        group_id="g1",
        command_text="set 岸宝",
    )
    assert "只允许管理员" in result.body


# --------------------------------------------------------------------------
# help 注册表：identity 条目必须收录 4 个自助子命令（四要素行文）
# --------------------------------------------------------------------------


def test_identity_help_entry_documents_self_service_subcommands() -> None:
    entry = next(item for item in HELP_ENTRIES if item["topic"] == "身份")
    blob = "\n".join(str(line) for line in entry["lines"]) + str(entry["detail"])
    for sub in ("set-name", "set-gender", "unset-name", "unset-gender"):
        assert f"/bot identity {sub}" in blob, sub
    assert entry["admin_only"] is True


# --------------------------------------------------------------------------
# N1 回归：set-name 输入消毒——控制字符拒绝、内部连续空白折叠、合法输入不变
# --------------------------------------------------------------------------


def test_set_name_with_newline_rejected_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name 好\n名字")
    assert "一行" in result.body
    assert "32" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_set_name_with_tab_rejected_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name 好\t名字")
    assert "一行" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_set_name_pure_whitespace_rejected_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name   ")
    assert "用法" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "unknown")


def test_set_name_internal_spaces_collapsed_to_single(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name 小  澜")
    assert "小 澜" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("小 澜", "unknown")


def test_set_name_legal_input_unchanged(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-name 岸宝  ")
    assert "岸宝" in result.body
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "unknown")
