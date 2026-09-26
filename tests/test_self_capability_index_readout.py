"""需求 10 的「功能」这一面：bot 自述能做什么，必须从帮助注册表现算。

锁的四件事：
1. **不发明功能**——列出者必是 ``HELP_TOPIC_DECLARATIONS`` 的成员；
2. **不漏可见面**——管理员看到全部，普通用户既看不到管理类主题、也不会被
   计数出卖（「我一共 40 项」本身就是泄露）；
3. **不静默截断**——被字数地板收口时「另有 N 项」必须出现，且列出+未列出=全量；
4. **生产真走得到**——chat 侧分区文本里就有这一段（不是只存在于取数口）。

全程离线，声明源用 ``monkeypatch`` 换成合成表；不读 .env、不联网。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat as chatmod
from plugins.bot_unified_runtime.domains.chat_reply.character import temporal as tmod
from plugins.bot_unified_runtime.domains.chat_reply.runtime import capability_registry

_TEMPORAL_SOURCE = (
    Path(tmod.__file__).resolve().read_text(encoding="utf-8")
)


def _decls(*pairs: tuple[str, bool]) -> tuple[capability_registry.HelpTopicDecl, ...]:
    return tuple(
        capability_registry.HelpTopicDecl(
            topic=topic, admin_only=admin_only, capability=f"bot.{topic}"
        )
        for topic, admin_only in pairs
    )


@pytest.fixture
def synthetic(monkeypatch):
    """换成合成声明源：两枚公开 + 两枚管理类。"""
    table = _decls(("天气", False), ("点歌", False), ("日志", True), ("配置", True))
    monkeypatch.setattr(capability_registry, "HELP_TOPIC_DECLARATIONS", table)
    return table


# ==================== ① 只列在册的，不发明 ====================


def test_admin_view_lists_exactly_the_registered_topics(synthetic) -> None:
    lines = tmod.capability_index_lines(is_admin=True)
    body = "\n".join(lines)
    for decl in synthetic:
        assert decl.topic in body, f"在册主题没被自述列出：{decl.topic}"
    listed = lines[0].split("：", 1)[1].split("、")
    assert {item.strip() for item in listed} <= {decl.topic for decl in synthetic}, listed


def test_no_hand_copied_topic_names_live_in_the_readout_module() -> None:
    """取数口里不许留主题名字面量（留了就是一份会过期的副本）。"""
    for topic in ("点歌", "好感度", "天气", "随机图"):
        assert f'"{topic}"' not in _TEMPORAL_SOURCE, topic


# ==================== ② 可见面与计数同源 ====================


def test_non_admin_view_hides_admin_topics_and_their_count(synthetic) -> None:
    lines = tmod.capability_index_lines(is_admin=False)
    body = "\n".join(lines)
    assert "日志" not in body and "配置" not in body, body
    assert "本会话可见 2 项" in body, body
    # 权限挡掉的那些**连计数都不许出现**：「另有 2 项未列出」本身就是一次泄露。
    # 「另有 N 项」这一行只服务字数地板截断（见 test_truncation_is_conservative…）。
    assert "另有" not in body, body


def test_empty_or_unusable_source_yields_no_block_not_a_guess(monkeypatch) -> None:
    monkeypatch.setattr(capability_registry, "HELP_TOPIC_DECLARATIONS", ())
    assert tmod.capability_index_lines(is_admin=True) == []


def test_source_import_failure_yields_no_block(monkeypatch) -> None:
    """真身取到但形状不可用时也不许硬凑——整块缺席比一份猜出来的清单诚实。"""
    monkeypatch.setattr(capability_registry, "HELP_TOPIC_DECLARATIONS", 7)
    assert tmod.capability_index_lines(is_admin=True) == []


# ==================== ③ 截断要守恒 ====================


def test_truncation_is_conservative_and_says_so(monkeypatch) -> None:
    table = _decls(*([(f"主题{i}", False) for i in range(400)]))
    monkeypatch.setattr(capability_registry, "HELP_TOPIC_DECLARATIONS", table)
    lines = tmod.capability_index_lines(is_admin=True)
    body = "\n".join(lines)
    listed = int(body.split("本会话可见 ", 1)[1].split(" 项", 1)[0])
    omitted = int(
        next(line for line in lines if "另有" in line).split("另有 ", 1)[1].split(" 项")[0]
    )
    assert listed + omitted == len(table)
    assert listed < len(table), "字数地板没生效，整块会无界膨胀"
    for line in lines:
        assert len(line) <= max(200, tmod._CAPABILITY_INDEX_MAX_CHARS + 40), len(line)


def test_pointing_line_exists_so_model_does_not_invent_arguments(synthetic) -> None:
    body = "\n".join(tmod.capability_index_lines(is_admin=True))
    assert "/bot help" in body and "/bot commands" in body, body


# ==================== ④ 生产分区真带这一段 ====================


def test_system_readout_partition_carries_the_capability_block(synthetic) -> None:
    text = chatmod._system_readout_section_text(is_admin=False)
    assert "我能做的事" in text, text
    assert "日志" not in text, "分区绕过可见性把管理面带进普通会话"


def test_system_readout_partition_for_admin_carries_admin_topics(synthetic) -> None:
    text = chatmod._system_readout_section_text(is_admin=True)
    assert "日志" in text and "配置" in text, text


def test_readout_builder_still_degrades_to_empty_on_failure(monkeypatch) -> None:
    """fail-open 不许把异常变成半截分区（旧行为：整块缺席，分区不出现）。"""

    def _throw(*_args, **_kwargs):
        raise RuntimeError("取数口炸了")

    monkeypatch.setattr(tmod, "system_readout_lines", _throw)
    assert chatmod._system_readout_section_text(is_admin=True) == ""


# ==================== ⑤ 生产调用点活性（不是只测得到函数） ====================


def test_production_call_site_passes_a_role_derived_flag() -> None:
    """装配点必须把**角色派生值**传给可见性参数，写死 True/False 都算绕过。

    上面几发分区锁是直接调构造器测的——那样即使生产把 ``is_admin=True`` 钉死
    也照样全绿（本席注毒实测到这一点：P4 打穿生产调用点、10 枚锁零红）。
    所以这一发按 AST 钉调用点的实参形态。
    """
    tree = ast.parse(Path(chatmod.__file__).resolve().read_text(encoding="utf-8"))
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_system_readout_section_text"
        and any(kw.arg == "is_admin" for kw in node.keywords)
    ]
    assert sites, "生产里没有带 is_admin 的调用点，可见性参数是死的"
    for site in sites:
        value = next(kw.value for kw in site.keywords if kw.arg == "is_admin")
        assert not isinstance(value, ast.Constant), (
            f"调用点把可见性写死成字面量 {value.value!r}，角色门等于没接"
        )
