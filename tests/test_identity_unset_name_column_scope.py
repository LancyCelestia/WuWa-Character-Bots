"""/bot identity unset-name 的**列作用域**锁（F-8 裁定甲＝按列清，2026-10-05 用户亲裁）。

起因（席 rowwipe 勘察 + 席 receiptorder 只修了说谎腿）：
`addressing_preferences` 的主键是 `(session_type, session_id, sender_id)`，QQ 私聊里
"那个人的称谓行"与"那个人的亲密档标记行"**天生同一行**（裸 uid 撞键形）。旧命令面走
`store.clear()`＝整条 DELETE ⇒ 一条"取消称呼"顺手把她亲手钉的 `intimate_pin_*` 两列与
`narration_*` 两列一起收回（描写档**没有 TTL**，本该活到本人 reset）。

本文件钉四枚断言 + 两枚反向锁：

- ① unset-name 之后 `intimate_pin_tier`／`intimate_explicit_at` 逐字照在；
- ② unset-name 之后 `narration_mode`／`narration_updated_at` 逐字照在（连 `relationship`
  与 `gender_identity` 也不许被牵连，一并钉在同一枚里）；
- ③ `addressing_preference` 那一列**确实**清了（否则＝整件事什么都没做）；
- ④ 回执点名"清了哪一列"与"保住了哪几列"，且**不**再宣称整条记录移除、**不**回显列值；
- 锁 A：命令面结构上碰不到 `store.clear()`（整行 DELETE 那支口在自助面零消费者）；
- 锁 B（注毒）：把按列清那一口**替换回**整行 DELETE，①②③④ 的正面断言当场全红——
  证明这四枚不是摆设。

夹具铁律（AGENTS 规则 6/7、台账 #66★、#76★）：
- 走偏好命令面的用例一律 `monkeypatch` 装配口，称谓库与 `shared_reply_policy_store`
  都指 tmp ⇒ 绝不写她生产库；
- `--basetemp` 在仓库外、且不在 `ChatBot_Runtime` 之下（否则媒体读根名册造假红）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    HELP_ENTRIES,
    build_identity_preference_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    providers as providers_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)

#: 该人行上五格的"原样"读数（注毒退回整行删时，这些值会一起变缺省）。
_TIER = "l1"
_TIER_STAMP = 1767000000.5
_MODE = "scene"
_MODE_STAMP = 1767000001.25
_RELATION = "lover"
_GENDER = "female"
_NAME = "岸宝"


class _FakeConfig:
    """处理器只经装配口触达存储（测试中已被替换成 tmp 库）。"""


@pytest.fixture(autouse=True)
def _reply_policy_points_at_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ReplyPolicyStore:
    """台账 #66★：偏好命令面的用例先把回复策略 store 结构性指 tmp（生产库零写）。"""
    policy_store = ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")
    monkeypatch.setattr(
        rp_module, "shared_reply_policy_store", lambda _config: policy_store
    )
    return policy_store


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AddressingPreferenceStore:
    real = AddressingPreferenceStore(tmp_path / "addressing_preferences.sqlite3")
    monkeypatch.setattr(
        providers_module, "build_addressing_preference_store", lambda _config: real
    )
    return real


def _run(store_fixture: AddressingPreferenceStore, text: str, *, group_id: str = "") -> Any:
    return build_identity_preference_result(
        _FakeConfig(),
        request_id="req-f8-column-scope",
        sender_id="u1",
        group_id=group_id,
        command_text=text,
    )


def _seed_the_whole_row(store_fixture: AddressingPreferenceStore) -> None:
    """把「那个人那一行」五格全部钉上：称谓＋性别自述＋关系档＋两枚标记列。

    私聊裸 uid（`("private", "", "u1")`）＝席 rowwipe 第 1 节认定的**撞键形那一支**，
    所以危害最重的形状就在这里造。
    """
    key = {"session_type": "private", "session_id": "", "sender_id": "u1"}
    store_fixture.set(
        **key, addressing_preference=_NAME, gender_identity=_GENDER  # type: ignore[arg-type]
    )
    store_fixture.set_relationship(**key, relationship=_RELATION)  # type: ignore[arg-type]
    store_fixture.set_intimate_pin(**key, tier=_TIER, explicit_at=_TIER_STAMP)  # type: ignore[arg-type]
    store_fixture.set_narration_pin(**key, mode=_MODE, updated_at=_MODE_STAMP)  # type: ignore[arg-type]


def _intimate(store_fixture: AddressingPreferenceStore) -> tuple[str, float]:
    return store_fixture.get_intimate_pin(session_type="private", session_id="", sender_id="u1")


def _narration(store_fixture: AddressingPreferenceStore) -> tuple[str, float]:
    return store_fixture.get_narration_pin(session_type="private", session_id="", sender_id="u1")


def _positive_locks(store_fixture: AddressingPreferenceStore) -> list[bool]:
    """①②③④ 四枚正面判据（逐枚返回值，供注毒席对照"恰有某枚变红"）。"""
    preference, gender = store_fixture.get(session_type="private", session_id="", sender_id="u1")
    body = _run(store_fixture, "unset-name", group_id="").body
    return [
        _intimate(store_fixture) == (_TIER, _TIER_STAMP),  # ①
        _narration(store_fixture) == (_MODE, _MODE_STAMP)  # ②
        and store_fixture.get_relationship(
            session_type="private", session_id="", sender_id="u1"
        )
        == _RELATION,
        preference == "" and gender == _GENDER,  # ③
        "已清除" in body  # ④
        and "保住" in body
        and "整条记录" not in body
        and all(label in body for label in ("性别自述", "关系档", "亲密档", "描写档"))
        and not any(
            value in body for value in (_NAME, _GENDER, _RELATION, _TIER, _MODE)
        ),
    ]


# --------------------------------------------------------------------------
# 正面四枚（先让 unset-name 只清自己那一列）
# --------------------------------------------------------------------------


def test_unset_name_leaves_the_intimate_pin_columns_untouched(
    store: AddressingPreferenceStore,
) -> None:
    """①：亲密档标记两列（档位＋墙钟时刻）逐字照在。"""
    _seed_the_whole_row(store)
    _run(store, "unset-name", group_id="")
    assert _intimate(store) == (_TIER, _TIER_STAMP)


def test_unset_name_leaves_the_narration_pin_and_neighbours_untouched(
    store: AddressingPreferenceStore,
) -> None:
    """②：描写档两列＋关系档＋性别自述都不是这条指令说过的话。"""
    _seed_the_whole_row(store)
    _run(store, "unset-name", group_id="")
    assert _narration(store) == (_MODE, _MODE_STAMP)
    assert store.get_relationship(session_type="private", session_id="", sender_id="u1") == (
        _RELATION
    )
    assert store.get(session_type="private", session_id="", sender_id="u1") == ("", _GENDER)


def test_unset_name_really_clears_the_name_column(
    store: AddressingPreferenceStore,
) -> None:
    """③：名字那一列确实清了（一枚"什么都不做"的实现过不了这一枚）。"""
    _seed_the_whole_row(store)
    _run(store, "unset-name", group_id="")
    preference, _gender = store.get(session_type="private", session_id="", sender_id="u1")
    assert preference == ""


def test_unset_name_receipt_names_the_cleared_and_the_kept_columns(
    store: AddressingPreferenceStore,
) -> None:
    """④：回执点清了哪一列、保了哪几列；旧"整条记录移除"那句不许再出现，列值不外流。"""
    _seed_the_whole_row(store)
    body = _run(store, "unset-name", group_id="").body
    assert "已清除" in body and "称谓偏好" in body
    assert "保住" in body
    for label in ("性别自述", "关系档", "亲密档", "描写档"):
        assert label in body, label
    assert "整条记录" not in body
    for value in (_NAME, _GENDER, _RELATION, _TIER, _MODE):
        assert value not in body, value


def test_unset_gender_leaves_the_name_and_both_pin_columns_untouched(
    store: AddressingPreferenceStore,
) -> None:
    """同一条按列清腿的另一支：unset-gender 只清性别自述那一列。

    裁定甲改的是 `docs/db-owners.md` 那句成文语义「清理＝按行删」，而这一支与
    unset-name **共用同一条尾巴**（席 rowwipe 第 3 节）⇒ 不改它，同一场销毁照旧成立。
    """
    _seed_the_whole_row(store)
    _run(store, "unset-gender", group_id="")
    preference, gender = store.get(session_type="private", session_id="", sender_id="u1")
    assert preference == _NAME
    assert gender == "unknown"
    assert _intimate(store) == (_TIER, _TIER_STAMP)
    assert _narration(store) == (_MODE, _MODE_STAMP)
    assert store.get_relationship(session_type="private", session_id="", sender_id="u1") == (
        _RELATION
    )


def test_group_scope_unset_name_does_not_disturb_the_private_row(
    store: AddressingPreferenceStore,
) -> None:
    """作用域键不许被顺手加宽：群里的 unset-name 只动群里那一行。"""
    _seed_the_whole_row(store)
    key = {"session_type": "group", "session_id": "g1", "sender_id": "u1"}
    store.set(**key, addressing_preference=_NAME)  # type: ignore[arg-type]
    _run(store, "unset-name", group_id="g1")
    assert store.get(**key) == ("", "unknown")  # type: ignore[arg-type]
    assert store.get(session_type="private", session_id="", sender_id="u1") == (_NAME, _GENDER)


# --------------------------------------------------------------------------
# 锁 A：自助命令面结构上碰不到整行 DELETE
# --------------------------------------------------------------------------


def test_the_self_service_surface_never_reaches_the_row_delete_entry(
    store: AddressingPreferenceStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令面一旦改回 `store.clear()`（整行 DELETE），这枚当场红——不用等人来看盘。"""
    reached: list[str] = []
    monkeypatch.setattr(
        AddressingPreferenceStore,
        "clear",
        lambda self, **_kw: reached.append("row-delete"),
    )
    monkeypatch.setattr(
        AddressingPreferenceStore,
        "clear_columns",
        lambda self, **_kw: reached.append("column-clear"),
    )
    _seed_the_whole_row(store)
    for text in ("unset-name", "unset-gender"):
        _run(store, text, group_id="")
    assert reached == ["column-clear", "column-clear"], (
        f"自助称谓面又摸回整行 DELETE 了（实际调用序列={reached}）"
    )


# --------------------------------------------------------------------------
# 锁 B：注毒——把按列清退回整行删，四枚正面判据必须红
# --------------------------------------------------------------------------


def test_poison_row_wipe_turns_the_four_positive_locks_red(
    store: AddressingPreferenceStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒自证：按列清那一口换成"整条 DELETE"⇒ ①②③④ 逐枚失效（锁真咬得住）。"""

    def _row_wipe(self: AddressingPreferenceStore, **kwargs: Any) -> None:
        self.clear(
            session_type=str(kwargs.get("session_type", "private")),
            session_id=str(kwargs.get("session_id", "")),
            sender_id=str(kwargs.get("sender_id", "")),
        )

    monkeypatch.setattr(AddressingPreferenceStore, "clear_columns", _row_wipe)
    _seed_the_whole_row(store)
    flags = _positive_locks(store)
    names = ("①亲密档照在", "②描写档照在", "③名字列清了", "④回执点名清/保")
    assert len(flags) == len(names)
    turned_red = [name for name, ok in zip(names, flags, strict=True) if not ok]
    assert turned_red == list(names), (
        f"注毒只让 {turned_red} 变红（其余仍绿）＝那几枚是摆设：退回整行删 ought 逐枚咬下"
    )


# --------------------------------------------------------------------------
# 文案面：帮助册不许再留「按行删」「按人不按会话」两句过期话
# --------------------------------------------------------------------------


def _entry_blob(topic: str) -> str:
    entry = next(item for item in HELP_ENTRIES if item["topic"] == topic)
    parts = [str(entry.get("index", "")), str(entry.get("title_line", "")), str(entry.get("detail", ""))]
    parts.extend(str(line) for line in entry.get("lines", []))
    return "\n".join(parts)


def test_identity_help_no_longer_promises_a_whole_row_cleanup() -> None:
    blob = _entry_blob("身份")
    assert "整条记录清除" not in blob, "帮助册还在承诺整条记录清除＝与裁定甲相反"
    assert "只清称谓偏好那一列" in blob
    assert "只清性别自述那一列" in blob


def test_intimate_help_no_longer_calls_unset_name_a_row_delete() -> None:
    blob = _entry_blob("亲密模式")
    assert "整行删除" not in blob, "「unset-name 的整行删除」这句在裁定甲之后是假陈述"


def test_narration_help_declares_the_i2_key_shape() -> None:
    """I-2：钉的键形＝(平台域, 会话, 这个人)，换了会话要重新激发——旧"按人不按会话"是假话。"""
    blob = _entry_blob("亲密模式")
    assert "这一轴按**会话里的这个人**" in blob
    assert "换了会话就需要重新激发" in blob
    assert "这一轴**按人**不按会话" not in blob
    assert "**描写档没有 TTL**" in blob  # 原有事实不许被整句替换顺手吃掉


def test_narration_help_discloses_the_group_whitelist_leg() -> None:
    """I-4 第③条：群侧这一格只在内容路由白名单群里生效，必须明写（防"开了却没变化"）。"""
    blob = _entry_blob("亲密模式")
    assert "内容路由白名单群" in blob
    assert "BOT_CONTENT_ROUTE_GROUP_WHITELIST" in blob
    assert "落回日常档" in blob
