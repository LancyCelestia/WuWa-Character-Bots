"""回归：合并转发按条数触发 + 心情系数每请求求值（评审时序 bug）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_forward_and_mood.py -q

两个实测缺陷：
  1. 合并转发只按**字数**触发（`BOT_RENDER_FORWARD_MIN_CHARS=0` → 完全禁用），
     用户口径是"需要发送的消息 >3 条就合并转发"。
  2. `group_auto_reply_probability` 在装配期被算成常量（`0.05 × 心情系数`）冻进
     `PolicySettings`，此后心情变化**永远不影响**开火概率——"心情低落时少插话"
     只在进程重启那一刻采样一次。
"""
from __future__ import annotations

from plugins.bot_unified_runtime.output.renderer import (
    build_forward_output,
    should_forward_by_node_count,
    split_text_chunks,
)
from plugins.bot_unified_runtime.policy.gate import PolicySettings, _resolve_probability

# ------------------------------------------------ 按条数触发合并转发（>3 条）


def test_four_chunks_trigger_forward() -> None:
    """>3 条（即 ≥4 条）才合并。"""
    text = "段落一的内容。\n\n段落二的内容。\n\n段落三的内容。\n\n段落四的内容。"
    chunks = split_text_chunks(text, node_chars=900)
    assert len(chunks) >= 4, f"构造用例应切出 ≥4 条，实际 {len(chunks)}"
    assert should_forward_by_node_count(text, node_chars=900, min_nodes=4) is True


def test_three_chunks_do_not_trigger_forward() -> None:
    """恰好 3 条不合并（用户明确"不含 3 条"）。"""
    text = "段落一的内容。\n\n段落二的内容。\n\n段落三的内容。"
    chunks = split_text_chunks(text, node_chars=900)
    assert len(chunks) == 3, f"构造用例应切出 3 条，实际 {len(chunks)}"
    assert should_forward_by_node_count(text, node_chars=900, min_nodes=4) is False


def test_single_paragraph_does_not_trigger_forward() -> None:
    assert should_forward_by_node_count("就一句话。", node_chars=900, min_nodes=4) is False


def test_min_nodes_zero_disables_rule() -> None:
    text = "\n\n".join([f"第{i}段。" for i in range(1, 10)])
    assert should_forward_by_node_count(text, node_chars=900, min_nodes=0) is False


def test_empty_text_does_not_trigger_forward() -> None:
    assert should_forward_by_node_count("", node_chars=900, min_nodes=4) is False


def test_forward_nodes_use_bot_name() -> None:
    """转发内节点署 bot 自己的名字（用户要求"发送的用户仍为 bot 自己"）。"""
    text = "\n\n".join([f"第{i}段内容。" for i in range(1, 6)])
    rendered = build_forward_output(
        "req-1", text, node_chars=900, sender_name="守岸人"
    )
    assert rendered.content_type == "forward"
    nodes = rendered.content_ref["messages"]
    assert nodes, "应至少产出一个转发节点"
    assert all(node["data"]["name"] == "守岸人" for node in nodes)


def test_forward_falls_back_to_generic_name_when_blank() -> None:
    rendered = build_forward_output("req-2", "内容", node_chars=900, sender_name="")
    assert rendered.content_ref["messages"][0]["data"]["name"] == "消息"


# ------------------------------------------- 心情系数每请求求值（时序 bug）


def test_resolve_probability_accepts_callable() -> None:
    """callable 概率必须每次调用时求值——这正是修掉时序 bug 的关键。"""
    state = {"p": 0.05}
    settings = PolicySettings(group_auto_reply_probability=lambda: state["p"])
    assert _resolve_probability(settings.group_auto_reply_probability) == 0.05
    state["p"] = 0.9
    assert _resolve_probability(settings.group_auto_reply_probability) == 0.9, (
        "概率必须随心情实时变化，不能在装配期冻结"
    )


def test_resolve_probability_accepts_plain_float() -> None:
    assert _resolve_probability(0.25) == 0.25


def test_resolve_probability_handles_bad_input() -> None:
    assert _resolve_probability(None) == 0.0
    assert _resolve_probability("not-a-number") == 0.0

    def _boom() -> float:
        raise RuntimeError("mood store unavailable")

    # 求值失败按"不抽签"处理，不能反过来误开火。
    assert _resolve_probability(_boom) == 0.0


def test_policy_settings_default_is_static_zero() -> None:
    assert _resolve_probability(PolicySettings().group_auto_reply_probability) == 0.0
