"""热路径性能回归门（交叉验证机制·性能层，2026-09-13）。

守「数量级」不抠精确值：阈值=实测基线 ×10 余量，机器慢/并发干扰不误报，
谁把性能拖垮一个数量级会当场红。基线出处：docs/perf-optimization-plan.md
（路由 P50 0.014ms / P95 0.054ms，2026-09-13 实测 2000 样例）。

本文件被 dev.ps1 -Task test 收集；阈值变更=规范变更，须同步 DESIGN-SPEC.md。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 路由判定吞吐：基线 P95≈0.054ms/次 → 3000 次理论 ≈0.16s；阈值 8s（50×余量，
# 只守数量级：引入 O(n²) 扫描或同步 IO 会在数百 ms→数十秒 量级炸穿）。
_ROUTE_SAMPLES = [
    "占卜",
    "今天天气怎么样",
    "英伟达股价",
    "美元兑人民币",
    "点歌 恋爱循环",
    "随便聊聊今天吃什么",
    "提醒我 12 点开会",
    "这是一条完全普通没有触发词的闲聊文本",
]


def test_route_classify_throughput_stays_order_of_magnitude() -> None:
    from plugins.bot_unified_runtime.runtime.base_router import (
        classify_message_route,
        clear_route_decision_cache,
    )

    classify_message_route("预热", config=object(), alias_resolver=None)
    start = time.perf_counter()
    for index in range(3000):
        classify_message_route(
            _ROUTE_SAMPLES[index % len(_ROUTE_SAMPLES)],
            config=object(),
            alias_resolver=None,
        )
    elapsed = time.perf_counter() - start
    clear_route_decision_cache()
    assert elapsed < 8.0, (
        f"路由判定 3000 次耗时 {elapsed:.2f}s（阈值 8s）——热路径被拖垮一个数量级，"
        "请用 systematic-debugging 定位新增开销，不要直接抬阈值。"
    )


def test_core_modules_import_under_budget() -> None:
    """核心模块冷导入预算：基线秒级内；阈值 15s 只防「导入即外呼/死等」级回归。"""
    import subprocess

    code = (
        f"import time, sys; sys.path.insert(0, r'{ROOT}'); "
        "start = time.perf_counter(); "
        "import plugins.bot_unified_runtime.runtime.base_router as m; "
        "print(time.perf_counter() - start)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
        env={
            **__import__("os").environ,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
    )
    assert result.returncode == 0, result.stderr[-400:]
    elapsed = float(result.stdout.strip().splitlines()[-1])
    assert elapsed < 15.0, (
        f"base_router 冷导入 {elapsed:.2f}s（阈值 15s）——出现导入期重活，"
        "检查是否引入了模块级网络/线程/重扫描。"
    )


@pytest.mark.parametrize(
    "module",
    [
        "plugins.bot_unified_runtime.output.card_render.theme_tokens",
        "plugins.bot_unified_runtime.sources.stock_data",
    ],
)
def test_render_and_data_modules_import_cleanly(module: str) -> None:
    import importlib

    start = time.perf_counter()
    importlib.import_module(module)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"{module} 导入 {elapsed:.2f}s（阈值 10s）"
