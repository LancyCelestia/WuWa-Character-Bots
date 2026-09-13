"""热路径性能回归守门（对标交叉验证机制的性能件）。

阈值取「当前实测数量级的 3-10 倍」宽口径——守的是数量级塌方（谁把 O(1)
改成 O(n²)、谁在 import 期塞重活），不追毫秒级抖动，避免 CI 抖红。
基线来源：scripts/measure_latency_chains.py 2026-09-13 实测
（路由 P50 0.014ms / P95 0.054ms → 5000 次约 0.3s）。
"""

from __future__ import annotations

import time

from plugins.bot_unified_runtime.runtime.base_router import classify_message_route

_SAMPLES = [
    "占卜",
    "今天天气怎么样",
    "英伟达股价",
    "美元兑人民币",
    "点歌 恋爱循环",
    "提醒我 12 点开会",
    "莫斯科股指",
    "求籤",
    "随便聊聊今天吃什么",
    "这是一条完全普通没有触发词的闲聊文本",
] * 10


def test_route_classify_throughput_no_order_collapse() -> None:
    """5000 次路由判定 < 3s：判定序 priority 归一后为热路径（基线 0.3s）。"""
    classify_message_route("预热", config=object(), alias_resolver=None)
    start = time.perf_counter()
    for text in _SAMPLES * 5:
        classify_message_route(text, config=object(), alias_resolver=None)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"路由判定 5000 次耗时 {elapsed:.2f}s（阈值 3s）——疑似判定序退化"


def test_route_classify_single_call_p99_sane() -> None:
    """单次判定 P99 < 20ms：单条消息被路由拖垮会直接反映在回复延迟上。"""
    classify_message_route("预热", config=object(), alias_resolver=None)
    worst = 0.0
    for text in _SAMPLES:
        start = time.perf_counter()
        classify_message_route(text, config=object(), alias_resolver=None)
        worst = max(worst, time.perf_counter() - start)
    assert worst < 0.02, f"单次路由判定最慢 {worst * 1000:.1f}ms（阈值 20ms）"
