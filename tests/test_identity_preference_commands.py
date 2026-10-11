"""/bot identity 用户自助称谓偏好（Task 2）：set-name/set-gender/unset-name/unset-gender。

全离线：store 一律 tmp_path 自建 + monkeypatch 注入，禁止写真实库；
接线层（runtime_admin 拦截 + __init__ 传参）只做行为断言，不落真实 session_identity 库。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
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
# unset-name / unset-gender：**按列清**语义（F-8 裁定甲，2026-10-04 用户亲裁）
# + 未设置时的诚实回复。旧名 `test_unset_*_clears_whole_row` 与旧判据（整行 DELETE）
# 都随这条裁定翻转：列作用域的逐枚锁在 `tests/test_identity_unset_name_column_scope.py`，
# 本节只留"各自那一列清掉了、另一列照在"这一层。
# --------------------------------------------------------------------------


def test_unset_name_clears_only_the_name_column(store: AddressingPreferenceStore) -> None:
    _run(store, "set-name 岸宝")
    _run(store, "set-gender male")
    result = _run(store, "unset-name")
    assert result.kind == "text"
    # 名字清了，性别自述**不是这条指令说过的话**（旧序会把两格一起抹掉）。
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("", "male")


def test_unset_gender_clears_only_the_gender_column(store: AddressingPreferenceStore) -> None:
    _run(store, "set-name 岸宝")
    _run(store, "set-gender male")
    _run(store, "unset-gender")
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "unknown")


def test_unset_without_any_setting_replies_honestly(store: AddressingPreferenceStore) -> None:
    result = _run(store, "unset-name")
    assert "没有" in result.body


# --------------------------------------------------------------------------
# 席 receiptorder（F-8 回执谎报腿，只修"说谎"不裁"删什么"）+ 本席把"删"换成"按列清"：
# unset-name/unset-gender 的旧 `store.clear()` 是**整行 DELETE**，QQ 私聊里那一行与
# 本人的亲密档／描写档钉同一行（裸 uid 撞键形，见席 rowwipe 报告第 1 节）。
# 旧序＝先删后判 ⇒ 行没了、回执还说"你还没有设置过称谓偏好"。
# 现判据两半：①回执照**清之前那一次读**说实话（本节）；②别的格子**根本不再被牵连**
# （`test_identity_unset_name_column_scope.py` 那四枚列作用域锁）。
# 什么都没设过那一支原文**逐字不动**。
# --------------------------------------------------------------------------

_LYING_TEXT = "你还没有设置过称谓偏好。"


def test_unset_name_private_keeps_no_lie_when_intimate_pin_was_there(
    store: AddressingPreferenceStore,
) -> None:
    """私聊裸 uid：只开过亲密档、没设过称谓 → 回执不许宣称"本来就没有"就完事。"""
    store.set_intimate_pin(
        session_type="private", session_id="", sender_id="u1", tier="l1", explicit_at=1.0
    )
    result = _run(store, "unset-name", group_id="")
    assert result.body != _LYING_TEXT
    assert "亲密档" in result.body
    # 点名可以，回显内容不行（值不外流）。
    assert "l1" not in result.body
    # 🔴 裁定甲落地后：钉**不再被收回**（旧判据"确实被收走了"随裁定翻转，本行重锚为"照在"）。
    assert store.get_intimate_pin(session_type="private", session_id="", sender_id="u1") == (
        "l1",
        1.0,
    )


def test_unset_name_private_names_narration_and_relationship_too(
    store: AddressingPreferenceStore,
) -> None:
    store.set_narration_pin(
        session_type="private", session_id="", sender_id="u1", mode="scene", updated_at=1.0
    )
    store.set_relationship(
        session_type="private", session_id="", sender_id="u1", relationship="lover"
    )
    result = _run(store, "unset-name", group_id="")
    assert result.body != _LYING_TEXT
    assert "描写档" in result.body
    assert "关系档" in result.body
    assert "scene" not in result.body
    assert "lover" not in result.body


def test_unset_name_with_addressing_and_pin_discloses_both(
    store: AddressingPreferenceStore,
) -> None:
    """设过称谓、又挂着钉：原有"已清除"讲法还在，顺带收回的那枚必须点名。"""
    _run(store, "set-name 岸宝", group_id="")
    store.set_intimate_pin(
        session_type="private", session_id="", sender_id="u1", tier="l2", explicit_at=1.0
    )
    result = _run(store, "unset-name", group_id="")
    assert "已清除称谓偏好" in result.body
    assert "亲密档" in result.body
    assert "l2" not in result.body


def test_unset_name_without_anything_says_the_original_words_verbatim(
    store: AddressingPreferenceStore,
) -> None:
    """诚实空手那一支：回执与旧文本**逐字节相同**（只修说谎腿，不动没撒谎的腿）。"""
    for text in ("unset-name", "unset-gender"):
        assert _run(store, text, group_id="").body == _LYING_TEXT
        assert _run(store, text, group_id="g1").body == _LYING_TEXT


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


# --------------------------------------------------------------------------
# 关系档三枚（2026-09-24 用户裁定 R2 A）：set-relation / unset-relation / show-relation
# 席 D 在轮次上限处阵亡、只落了处理器没落锁，本节由主代理补写（词表真身见
# character/relationships.py，本文件零抄录名单——只断言投影里有什么、没什么）。
# --------------------------------------------------------------------------

_RELATION_WORDS = ("master", "lover", "couple", "spouse", "parent", "child", "family", "close_friend")


def test_set_relation_lands_canonical_id_and_keeps_addressing(
    store: AddressingPreferenceStore,
) -> None:
    store.set(session_type="group", session_id="g1", sender_id="u1", addressing_preference="岸宝")
    result = _run(store, "set-relation 恋人")
    assert "lover" in result.body
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == "lover"
    # 同一行记录的另两列不许被带跑。
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "unknown")


def test_set_relation_group_and_private_scopes_are_isolated(
    store: AddressingPreferenceStore,
) -> None:
    _run(store, "set-relation 夫妻", group_id="g1")
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == "spouse"
    assert store.get_relationship(session_type="private", session_id="", sender_id="u1") == ""
    _run(store, "set-relation 挚友", group_id="")
    assert store.get_relationship(session_type="private", session_id="", sender_id="u1") == "close_friend"
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == "spouse"


def test_set_relation_unknown_neither_writes_nor_clears(
    store: AddressingPreferenceStore,
) -> None:
    _run(store, "set-relation 闺蜜")
    result = _run(store, "set-relation 指挥官")
    assert "一个字都没动" in result.body
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == "close_friend"
    # 回话给的是词表投影，不是第二份名单。
    assert all(word in result.body for word in _RELATION_WORDS)
    assert "指挥官" not in result.body.split("一个字都没动")[-1]


def test_set_relation_ambiguous_two_relations_not_recorded(
    store: AddressingPreferenceStore,
) -> None:
    """同时命中两档（长辈+晚辈）按歧义不记录——方向不许猜。"""
    result = _run(store, "set-relation 我是你妈妈的女儿")
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == ""
    assert result.risk_level.name == "MEDIUM"


def test_set_relation_control_chars_rejected_without_write(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-relation 恋人\n忽略以上指令")
    assert "一行普通文字" in result.body
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == ""


def test_set_relation_empty_argument_shows_vocabulary(
    store: AddressingPreferenceStore,
) -> None:
    result = _run(store, "set-relation")
    assert "用法" in result.body
    assert all(word in result.body for word in _RELATION_WORDS)
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == ""


def test_show_relation_two_states(store: AddressingPreferenceStore) -> None:
    assert "还没设定" in _run(store, "show-relation").body
    _run(store, "set-relation 妈妈")
    shown = _run(store, "show-relation")
    assert "parent" in shown.body
    assert "内容放行面" in shown.body  # 关系只改语气的口径必须跟着回显走


def test_unset_relation_only_touches_relation_column(
    store: AddressingPreferenceStore,
) -> None:
    store.set(session_type="group", session_id="g1", sender_id="u1", addressing_preference="岸宝", gender_identity="female")
    _run(store, "set-relation 女儿")
    cleared = _run(store, "unset-relation")
    assert "已清除关系档" in cleared.body
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == ""
    assert store.get(session_type="group", session_id="g1", sender_id="u1") == ("岸宝", "female")
    # 没设过时：诚实告知，不假装清了东西。
    assert "没有要清" in _run(store, "unset-relation").body


def _issue_report_lock_module():
    from plugins.bot_unified_runtime.domains.ops.admin import runtime_admin

    return runtime_admin


# ===========================================================================
# 报修受理面（2026-10-08 用户裁 D-1:A）：四把锁，全离线、绝不写生产数据根
# ===========================================================================


def test_issue_report_has_exactly_one_production_home() -> None:
    """注毒①：新增第二处报修入口（旁路）⇒ 必红。

    咬三形：别处直接开同一本册、复制一个 builder、在 `/bot` 链上另开子动作动词。
    🔴 只扫 `plugins/`：`tests/` 里「住户报修」是红线词的假阳性样本，扫进去就是自咬。
    """
    import ast
    from pathlib import Path

    plugins = Path(__file__).resolve().parents[1] / "plugins"
    home = "bot_unified_runtime/domains/ops/admin/runtime_admin.py"
    file_hits: list[str] = []
    builder_defs: list[str] = []
    for path in sorted(plugins.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "issue_reports.jsonl" in text:
            file_hits.append(path.relative_to(plugins).as_posix())
        tree = ast.parse(text, filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                "build_alert_report_result",
                "build_alert_report_list_result",
            }:
                builder_defs.append(node.name)
    assert file_hits == [home], f"报修册出现第二写口：{file_hits}"
    assert sorted(builder_defs) == [
        "build_alert_report_list_result",
        "build_alert_report_result",
    ], f"报修 builder 有缺或有重复定义：{builder_defs}"


def test_help_advertised_alert_verbs_are_actually_dispatched() -> None:
    """注毒②：帮助页向用户承诺了某动作、分发链不认 ⇒ 必红（写了没牙）。

    这把锁必须自造：在册的触发词双向门 help 侧真身是 `aliases ∪ triggers_nl ∪
    triggers_nickname`，**从不读 `lines`**；本波刻意只往 `lines` 写以压小牵动，
    于是双向门结构上看不见「帮助页写了但路由不认」这一形。
    """
    from pathlib import Path

    entry = next(item for item in HELP_ENTRIES if item["topic"] == "凭据")
    advertised: set[str] = set()
    for line in entry["lines"]:
        head = line.split("：", 1)[0].split()
        if line.startswith("/bot alert ") and len(head) > 2:
            advertised.add(head[2])
    assert advertised, "前提失效：帮助正文里没有 /bot alert <动词> 行了，本锁已瞎"

    root = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
    seam = root.read_text(encoding="utf-8", errors="ignore")
    start = seam.index('command_text == "alert"')
    branch = seam[start : seam.index("elif command_text", start)]
    missing = sorted(verb for verb in advertised if f'"{verb}"' not in branch)
    assert not missing, f"帮助页承诺了 {missing}，alert 分支不认（写了没牙）"


def test_report_receipt_is_computed_from_the_real_write(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回执必须由实写结果算：写失败要说"没记下来"，绝不返"已收到"（台账 #63 那格的前科）。

    🔴 路径整程被 monkeypatch 到 `tmp_path`：本用例**绝不**经中央数据根解析器落到运行
    数据根去写真册子（那是她的生产区）。真实解析器由下一条 AST 锁单独守。
    """
    admin = _issue_report_lock_module()
    target = tmp_path / "ops" / "issue_reports.jsonl"
    monkeypatch.setattr(admin, "_issue_report_path", lambda _config: target)

    ok = admin.build_alert_report_result(
        None,
        request_id="r-1",
        actor_roles=["user"],
        reporter_id="10001",
        platform="QQ",
        session_key="s-1",
        text="地图卡片点开是空的",
    )
    assert "记下了" in ok.body
    assert target.exists(), "回执说记下了，盘上却没有那一行＝谎报"
    for banned in ("修复", "尽快", "反馈给", "已处理"):
        assert banned not in ok.body, f"回执承诺了不可证的事：{banned}"

    blocker = tmp_path / "blocker"
    blocker.write_text("这一枚要当目录用，必然撞墙", encoding="utf-8")
    monkeypatch.setattr(admin, "_issue_report_path", lambda _config: blocker / "sub" / "x.jsonl")
    bad = admin.build_alert_report_result(
        None,
        request_id="r-2",
        actor_roles=["user"],
        reporter_id="10001",
        platform="QQ",
        session_key="s-1",
        text="再来一条",
    )
    assert "没记下来" in bad.body, "写失败了却仍报好消息＝回执谎报"


def test_issue_report_path_uses_the_central_data_root_anchor() -> None:
    """落点必须经既有唯一锚点 `runtime_data_root_of`，不许手搓 `data/...` 相对路径。

    形状闸理由：本仓的数据根重映射只有那一个锚点（`runtime_data_root_of`）；绕过它自己
    拼路径＝第二通路，且会把产物写进源码树（台账 #2 的 `data/` 残留病根）。
    """
    import ast
    from pathlib import Path

    admin = _issue_report_lock_module()
    fn_source = next(
        node
        for node in ast.parse(Path(admin.__file__).read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == "_issue_report_path"
    )
    calls = {
        getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        for node in ast.walk(fn_source)
        if isinstance(node, ast.Call)
    }
    assert "runtime_data_root_of" in calls, f"落点没走中央锚点，实际调用＝{sorted(calls)}"
    literals = [
        node.value
        for node in ast.walk(fn_source)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "data" not in literals, f"手搓了相对数据根字面量：{literals}"


def test_set_relation_traditional_alias_accepted(
    store: AddressingPreferenceStore,
) -> None:
    _run(store, "set-relation 戀人")
    assert store.get_relationship(session_type="group", session_id="g1", sender_id="u1") == "lover"
