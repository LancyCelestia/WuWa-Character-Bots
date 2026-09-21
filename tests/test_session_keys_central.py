"""会话键形态中央件（FIX5）行为锁：``domains/core/session_keys.py`` 唯一判据。

照 T59（``text_boundary`` + ``test_text_boundary_central.py``）的形态做：
权威定义 + 例锁 + 可红性（变异见 fix-FIX5 日志，逐条注入后必红）。

取证结论（详 ``.superpowers/sdd/2026-09-20-spec-audit/fix-FIX5-log.md`` 阶段一表）：

- 生产会话键 = NoneBot ``get_session_id()``：OneBot V11 群
  ``group_<gid>_<uid>``、私聊 ``<uid>``；TG 群 ``group_<cid>_<uid>``（含
  ``group_<cid>_thread<t>_<uid>``）、私聊 ``private_<cid>``、频道 ``channel_<cid>``；
- 冒号形 ``group:<gid>`` 只在**出站** ``SendRequest.session_id`` 与合成/smoke
  路径存在，是另一个命名空间的书写法，不是「ingress 约定」（那两处注释失实）。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.session_keys import (
    FORM_BARE,
    FORM_COLON,
    FORM_EMPTY,
    FORM_OTHER,
    FORM_PRIVATE_SCHEME,
    FORM_UNDERSCORE,
    GROUP_SESSION_PREFIX,
    KIND_GROUP,
    KIND_PRIVATE,
    KIND_UNKNOWN,
    LEGACY_GROUP_SCHEME,
    UNKNOWN_SENDER,
    build_session_key,
    group_id_of_session_key,
    group_session_prefix,
    is_group_session_key,
    normalize_session_key,
    parse_session_key,
    private_session_key,
)

# 真实群号/用户号样本（取自 .env 现行白名单与 AGENTS 台账实证形态）。
GROUP = "1108838060"
SENDER = "3865067623"

# ---------------------------------------------------------------- 形态常量钉死


def test_prefix_constants_pinned() -> None:
    """两枚前缀字面量逐字钉死（换形即全仓红，杜绝第三次静默分叉）。"""
    assert GROUP_SESSION_PREFIX == "group_"
    assert LEGACY_GROUP_SCHEME == "group:"
    assert UNKNOWN_SENDER == "unknown"


# ---------------------------------------------------------------- 判群：正例
# (键, 期望群号, 期望发送者段) —— 全部来自适配器实测形态或仓内合成路径实发形态

_GROUP_POSITIVE: list[tuple[str, str, str]] = [
    (f"group_{GROUP}_{SENDER}", GROUP, SENDER),  # OneBot V11 群消息（生产主形）
    ("group_1076073471_3113533731", "1076073471", "3113533731"),
    ("group_-1001234567890_5551212", "-1001234567890", "5551212"),  # TG 超级群负 cid
    ("group_123_thread456_789", "123", "thread456_789"),  # TG 话题群
    ("group_123_unknown", "123", "unknown"),  # 中央构造器 unknown 兜底形
    (f"group:{GROUP}", GROUP, ""),  # 冒号形（出站/合成，判群、无发送者段）
]


@pytest.mark.parametrize(
    ("key", "expected_group_id", "expected_user_id"),
    _GROUP_POSITIVE,
    ids=lambda v: str(v),
)
def test_group_shapes_are_group(
    key: str, expected_group_id: str, expected_user_id: str
) -> None:
    parsed = parse_session_key(key)
    assert is_group_session_key(key) is True
    assert parsed.kind == KIND_GROUP
    assert parsed.is_group is True
    assert parsed.group_id == expected_group_id
    assert parsed.user_id == expected_user_id
    assert group_id_of_session_key(key) == expected_group_id


@pytest.mark.parametrize("raw", ["group_123456", "group__111", "group:", "group_"])
def test_half_baked_group_shapes_fail_closed(raw: str) -> None:
    """缺群号或缺发送者段的半截键**不判群**：真实适配器不发，宁可少判。"""
    assert is_group_session_key(raw) is False
    assert parse_session_key(raw).kind == KIND_UNKNOWN
    assert group_id_of_session_key(raw) == ""


def test_colon_form_is_tagged_as_legacy_scheme() -> None:
    """冒号形必须与下划线形在 ``form`` 上可区分（同一群判定、不同书写来源）。"""
    underscore = parse_session_key(f"group_{GROUP}_{SENDER}")
    colon = parse_session_key(f"group:{GROUP}")
    assert underscore.form == FORM_UNDERSCORE
    assert colon.form == FORM_COLON
    assert colon.kind == KIND_GROUP
    assert colon.user_id == ""


# ---------------------------------------------------------------- 判群：负例

_NOT_GROUP: list[str] = [
    SENDER,  # OneBot 私聊 = 裸 uid
    "1722380002",
    "private_123456",  # TG 私聊
    "private:456",  # 仓内合成私聊
    "channel_-100987654321",  # TG 频道
    "guild_1_channel_2_3",  # 官方 QQ 适配器频道（未覆盖登记）
    "friend_openidabc",  # 官方 QQ 私聊
    "email:someone@example.com",  # mail 摄取覆写
    "p2p_abc_def",  # console 频道键
    "unknown",
    "",
    "   ",
    "group",
    "groups_1_2",  # 含子串但不是前缀
    "xgroup_1_2",
    "agroup:123",
    "群_1_2",
    "GROUP_",  # 前缀本体残缺（大写也不补）
    "drop_table;--",
    "1;drop table",
]


@pytest.mark.parametrize("key", _NOT_GROUP, ids=lambda v: repr(v))
def test_non_group_shapes(key: str) -> None:
    assert is_group_session_key(key) is False
    assert parse_session_key(key).kind != KIND_GROUP
    assert group_id_of_session_key(key) == ""


@pytest.mark.parametrize(
    ("key", "form", "kind"),
    [
        (SENDER, FORM_BARE, KIND_PRIVATE),
        ("private_123", FORM_PRIVATE_SCHEME, KIND_PRIVATE),
        ("private:123", FORM_PRIVATE_SCHEME, KIND_PRIVATE),
        ("channel_9", FORM_BARE, KIND_PRIVATE),
        ("", FORM_EMPTY, KIND_UNKNOWN),
        ("guild_1_channel_2_3", FORM_BARE, KIND_PRIVATE),
        ("group_123", FORM_OTHER, KIND_UNKNOWN),
    ],
)
def test_parse_form_and_kind_matrix(key: str, form: str, kind: str) -> None:
    parsed = parse_session_key(key)
    assert parsed.form == form
    assert parsed.kind == kind


# ---------------------------------------------------------------- 归一口径


@pytest.mark.parametrize(
    "key",
    [
        f"GROUP_{GROUP}_{SENDER}",
        f"Group_{GROUP}_{SENDER}",
        f"gRoUp_{GROUP}_{SENDER}",
        f"  group_{GROUP}_{SENDER}  ",
        "\tgroup_" + GROUP + "_" + SENDER + "\n",
        f" GROUP:{GROUP} ",
    ],
    ids=range(6),
)
def test_case_and_whitespace_insensitive(key: str) -> None:
    """大小写不敏感 + 两端去空白（对真实输入是零差异的有意放宽，见模块 docstring ③）。"""
    assert is_group_session_key(key) is True


def test_raw_is_preserved_and_normalized_is_stripped() -> None:
    parsed = parse_session_key(f"  group_{GROUP}_{SENDER} ")
    assert parsed.raw.startswith("  ") and parsed.raw.endswith(" ")
    assert parsed.normalized == f"group_{GROUP}_{SENDER}"
    assert normalize_session_key(None) == ""
    assert normalize_session_key(123) == "123"


@pytest.mark.parametrize(
    "value",
    [None, 0, False, [], {}, (), object()],
    ids=["none", "zero", "false", "list", "dict", "tuple", "object"],
)
def test_never_raises_on_hostile_types(value: Any) -> None:
    """任何输入都得给个答案，绝不抛（判据错了顶多是形态不认，异常=静默断链）。"""
    assert isinstance(is_group_session_key(value), bool)
    assert isinstance(parse_session_key(value).normalized, str)


def test_control_chars_and_emoji_do_not_become_group() -> None:
    for key in ["group_\x00_1", "group_\n1_2", "group_🌊_1", "group_1_2\x07"]:
        assert isinstance(is_group_session_key(key), bool)
    # 换行/控制符不当群（第 2 例含 "group_" + 换行，其群号段为空 → fail-closed）
    assert is_group_session_key("group_\n1_2") is False


# ---------------------------------------------------------------- 派生键


def test_content_route_member_key_is_group() -> None:
    """亲密模式成员派生键 ``群键||u:用户号`` 仍以群键开头 → 判群（群内个人档）。"""
    member = f"group_{GROUP}_{SENDER}||u:1722380002"
    assert is_group_session_key(member) is True
    parsed = parse_session_key(member)
    assert parsed.group_id == GROUP
    assert parsed.user_id == f"{SENDER}||u:1722380002"


# ---------------------------------------------------------------- 构造侧


# 历史实现逐字内联副本（report-T66 式「内联规格重述」锚：中央件与它必须永远同值）。
def _legacy_session_key_from_ids(group_id: Any, user_id: Any) -> str:
    group = str(group_id or "").strip()
    user = str(user_id or "").strip()
    if group:
        return f"group_{group}_{user or 'unknown'}"
    return user or "unknown"


@pytest.mark.parametrize(
    ("group_id", "user_id"),
    [
        (GROUP, SENDER),
        (GROUP, ""),
        (GROUP, None),
        ("", SENDER),
        (None, SENDER),
        (None, None),
        (0, 0),
        (int(GROUP), int(SENDER)),  # int/str 混型（台账 #34 pydantic 标量键先例）
        (f"  {GROUP}  ", f" {SENDER} "),
        ("-100123", "555"),
    ],
    ids=range(10),
)
def test_builder_matches_legacy_byte_for_byte(group_id: Any, user_id: Any) -> None:
    assert build_session_key(group_id, user_id) == _legacy_session_key_from_ids(
        group_id, user_id
    )


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [(SENDER, SENDER), ("  " + SENDER + " ", SENDER), ("", UNKNOWN_SENDER), (None, UNKNOWN_SENDER)],
    ids=range(4),
)
def test_private_session_key(user_id: Any, expected: str) -> None:
    assert private_session_key(user_id) == expected
    assert is_group_session_key(private_session_key(user_id)) is False


@pytest.mark.parametrize(
    ("group_id", "expected"),
    [
        (GROUP, f"group_{GROUP}_"),
        (f"  {GROUP}  ", f"group_{GROUP}_"),
        ("", ""),
        (None, ""),
        (0, ""),  # 中央口径：falsy 一律无群号（shared_group 旧面 str(0) 差异单独钉）
    ],
    ids=range(5),
)
def test_group_session_prefix(group_id: Any, expected: str) -> None:
    assert group_session_prefix(group_id) == expected


@pytest.mark.parametrize("group_id", [GROUP, "631785829", f" {GROUP} "])
def test_group_prefix_is_a_prefix_of_built_key(group_id: str) -> None:
    """自反锁：构造器产出的每个群键都必然落在同件给出的群前缀内（读写永不劈叉）。"""
    key = build_session_key(group_id, SENDER)
    assert key.startswith(group_session_prefix(group_id))


@pytest.mark.parametrize(
    ("group_id", "user_id"),
    [(GROUP, SENDER), ("631785829", "1722380002"), ("-100123", "555")],
    ids=range(3),
)
def test_roundtrip_build_then_parse(group_id: str, user_id: str) -> None:
    parsed = parse_session_key(build_session_key(group_id, user_id))
    assert parsed.kind == KIND_GROUP
    assert parsed.group_id == group_id.strip()
    assert parsed.user_id == user_id.strip()
    assert parsed.form == FORM_UNDERSCORE


def test_adjacent_group_numbers_are_not_confused() -> None:
    """互为数字前缀的群号（123456 vs 1234567）互不串台——前缀必须带尾下划线。"""
    short = group_session_prefix("123456")
    long_key = build_session_key("1234567", "111")
    assert short == "group_123456_"
    assert not long_key.startswith(short)
    assert parse_session_key(long_key).group_id == "1234567"
