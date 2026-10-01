"""PROVIDERS-R2 票 ATKLLM-2 锁：回包 usage 读侧硬顶夹（席位 S-REVIEW-PROVIDERS，2026-09-28）。

病根（SEAT-ATK-LLMLEDGER，探针 ATKLLM-2 exit=1）：``providers._extract_usage``
对回包 usage 整包照收（``dict(usage)``），下游 ledger 仅有「非负」闸、**无上界**；
被控/替换的中转站对一次小额调用虚报 ``prompt_tokens=10**12`` ⇒ 台账 channel_spec
臂与 chat 审计臂（同吃 raw_usage）一起虚记天文成本，F-2 信任边界的对照基线又由
**同一份不可信 usage** 算出（自指放行）。本腿在**读侧唯一出点**夹死并留痕，
两消费臂同吃这一份 dict ⇒ 单点夹即全链有界。修法方向即探针 A3 原文（发送侧
尺寸对照属后续票，本锁只钉「有上界」这一半）。

四腿：
① 真锁——越硬顶的整数 token 键必须被夹到顶且打 ``usage_report_sanity`` 标记；
② 无扰动——合法量级 usage 逐字节原样透传（夹不碰小值、负值/布尔维持原形态交下游）；
③ 双臂同界——total/prompt/completion 全夹后任何键都不超过硬顶（虚报线性放大被切断）；
④ 注毒自证——把 ``_extract_usage`` 还原成补丁前裸 ``dict(usage)`` 形态，检测器必判红
   （证明 ① 咬的是真身源码，不是空转字符串）。

全离线纯函数，不请求网络、不读 config、不碰 ledger 写线程。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import providers as LLM
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    REPORTED_TOKEN_HARD_CAP,
    _extract_usage,
)

HUGE = 10**12  # 探针 A1 同量级虚报
_LLM_PROVIDERS_SOURCE = Path(inspect.getfile(LLM)).read_text(encoding="utf-8")


def test_r2_llm_huge_reported_tokens_clamped_to_cap() -> None:
    """真锁：10^12 级虚报 ⇒ 全部夹到硬顶，越界留痕。"""
    out = _extract_usage(
        {"prompt_tokens": HUGE, "completion_tokens": HUGE, "total_tokens": 2 * HUGE},
        finish_reason="stop",
    )
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        assert out[key] == REPORTED_TOKEN_HARD_CAP, f"{key} 未夹：{out.get(key)!r}"
    sanity = out.get("usage_report_sanity")
    assert isinstance(sanity, dict) and sanity.get("cap") == REPORTED_TOKEN_HARD_CAP
    assert set(sanity.get("clamped_keys", [])) == {
        "prompt_tokens", "completion_tokens", "total_tokens",
    }
    # 既有行为不回归：raw finish_reason 先 pop、再按安全枚举回填（sanitized 形态在）。
    assert out.get("finish_reason") == "stop"


def test_r2_llm_legitimate_usage_untouched() -> None:
    """无扰动锁：合法量级逐键原样透传、不打留痕；负值/布尔不夹（交下游非负闸，本腿不重算）。"""
    normal = {"prompt_tokens": 1234, "completion_tokens": 567, "total_tokens": 1801}
    out = _extract_usage(dict(normal))
    assert out == normal
    assert "usage_report_sanity" not in out
    odd = _extract_usage({"prompt_tokens": -5, "completion_tokens": True})
    assert odd["prompt_tokens"] == -5
    assert odd["completion_tokens"] is True
    assert "usage_report_sanity" not in odd


def test_r2_llm_clamped_values_are_bounded_across_arms() -> None:
    """双臂同界的算术前提：夹后任何 token 键 ≤ 硬顶 ⇒ 任何按 token 线性放大的成本臂有界。"""
    out = _extract_usage(
        {"prompt_tokens": HUGE, "output_tokens": 10**20, "reasoning_tokens": 7}
    )
    for key, value in out.items():
        if key.endswith("_tokens") and isinstance(value, int) and not isinstance(value, bool):
            assert 0 <= value <= REPORTED_TOKEN_HARD_CAP, f"{key} 越顶未夹：{value!r}"


def test_r2_llm_injection_selfproof_preclamp_shape_fails_detector() -> None:
    """注毒自证：检测器在补丁前形态（裸 dict(usage)）上必判「无上界」。"""
    pre_fix = '''
def _extract_usage(usage, finish_reason=None):
    result = {}
    if isinstance(usage, dict):
        result = dict(usage)
    result.pop("finish_reason", None)
    return result
'''

    def _clamp_leg_present(src: str) -> bool:
        return "REPORTED_TOKEN_HARD_CAP" in src and "> REPORTED_TOKEN_HARD_CAP" in src

    assert not _clamp_leg_present(pre_fix), "检测器失效：补丁前形态竟被判定有界"
    assert _clamp_leg_present(_LLM_PROVIDERS_SOURCE), (
        "真身源码里找不到硬顶夹——本锁的 ①③ 失去执法对象"
    )
    # 函数体真跑对照：夹值存在且为模块级常数（AST 面，防「注释里写了常数」的假绿）。
    tree = ast.parse(_LLM_PROVIDERS_SOURCE)
    consts = {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and node.targets
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "REPORTED_TOKEN_HARD_CAP"
    }
    assert consts and isinstance(consts["REPORTED_TOKEN_HARD_CAP"], ast.Constant)
    assert consts["REPORTED_TOKEN_HARD_CAP"].value == REPORTED_TOKEN_HARD_CAP
    assert REPORTED_TOKEN_HARD_CAP < HUGE, "硬顶设得比探针虚报量级还大＝夹了个寂寞"
