"""热路径性能回归守门（对标交叉验证机制的性能件）。

阈值取「当前实测数量级的 3-10 倍」宽口径——守的是数量级塌方（谁把 O(1)
改成 O(n²)、谁在 import 期塞重活），不追毫秒级抖动，避免 CI 抖红。
基线来源：scripts/measure_latency_chains.py 2026-09-13 实测
（路由 P50 0.014ms / P95 0.054ms → 5000 次约 0.3s）。

常驻门清单（2026-09-14 起 3 条；规矩：只许新增/收紧，禁放宽任何阈值）：
1. test_route_classify_throughput_no_collapse——5000 次路由判定 < 3s（基线 ~0.3s，10x 余量）
2. test_route_classify_single_call_max_sane——单次判定 100 样本 max（P99 保守上界）< 20ms
3. test_package_import_duration_no_collapse——子进程整包导入 3 次中位 < 10s
   （基线 1.9~2.1s，5x 余量；补齐本 docstring 曾声称却缺失的 import 门，
   草案源：.superpowers/sdd/2026-09-13-six-domain-batch/perf-report.md §五）
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

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
    """5000 次路由判定 < 3s：判定序 priority 归一后为热路径（基线 0.3s）。

    2026-09-14 牙齿复核修正：_SAMPLES 已含 ×10 复制，原 `* 5` 实际只跑 500 次
    （实测 0.025s，余量 120x，远超设计的 10x）；`* 50` 才是真 5000 次，
    阈值 3s 不动（= 设计的 10x 余量）。证据：scripts/measure_latency_chains.py
    + $TEMP 延迟副本红试（500 次语义下 +6ms/次才红，修正后 +0.6ms/次即红）。
    """
    classify_message_route("预热", config=object(), alias_resolver=None)
    start = time.perf_counter()
    for text in _SAMPLES * 50:
        classify_message_route(text, config=object(), alias_resolver=None)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"路由判定 5000 次耗时 {elapsed:.2f}s（阈值 3s）——疑似判定序退化"


def test_route_classify_single_call_max_sane() -> None:
    """单次判定 100 样本取 max（P99 的保守上界）< 20ms：最慢一条直接进回复延迟。

    2026-09-14 牙齿复核改名（M-12）：原名单写 P99、实算 max——如实声明取
    max。n=100 下真 P99（第 99 序统量）与 max 几乎重合，显式分位估计器在
    该样本量只添方差徒增 CI 抖红；max ≥ P99 为保守上界，阈值 20ms 语义
    不变（不松不紧，「只许新增/收紧」铁律不受影响）。
    """
    classify_message_route("预热", config=object(), alias_resolver=None)
    worst = 0.0
    for text in _SAMPLES:
        start = time.perf_counter()
        classify_message_route(text, config=object(), alias_resolver=None)
        worst = max(worst, time.perf_counter() - start)
    assert worst < 0.02, f"单次路由判定最慢 {worst * 1000:.1f}ms（阈值 20ms）"


# --- import 时长门（2026-09-14 落地，草案：perf-report.md §五） ----------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
# 探针在子进程内用 perf_counter 夹住 import 语句，只计导入本身耗时
# （不含解释器启动 ~50ms；与草案的墙钟口径差一个常数，不影响数量级门判定）。
_IMPORT_PROBE_CODE = (
    "import time;t0=time.perf_counter();"
    "import plugins.bot_unified_runtime;print(time.perf_counter()-t0)"
)
_IMPORT_RUNS = 3  # 中位数防单次抖动（冷导入噪声约 ±10%）
_IMPORT_GATE_THRESHOLD_S = 10.0  # 基线：探针口径 ~1.0-1.3s / importtime 口径 1.9-2.1s（perf-report §三），5x+ 余量的数量级门
_IMPORT_PROBE_TIMEOUT_S = 60.0  # 必须 > 阈值：真退化走断言红，只有挂死才走超时红


def _probe_python() -> str:
    """探针解释器：优先运行数据根 venv（仓库同级 ChatBot_Runtime/venv），退回当前解释器。"""
    candidate = _REPO_ROOT.parent / "ChatBot_Runtime" / "venv" / "Scripts" / "python.exe"
    return str(candidate) if candidate.is_file() else sys.executable


def test_package_import_duration_no_collapse() -> None:
    """整包导入（子进程口径，3 次中位）< 10s：import 期塞重活/依赖树塌方的数量级门。

    基线：探针口径（无 importtime 开销）本机实测 ~1.0-1.3s；perf-report.md §三
    的 -X importtime 全包口径 1869~2058ms（含逐模块计时开销）。阈值 10s 余量 5x+。
    牙齿实测（2026-09-14）：阈值临时压到 1s 时 median 1.03s 即红——门真咬人。
    稳定性三件套：cwd=仓库根（.env / plugins 解析与生产同口径）、
    PYTHONDONTWRITEBYTECODE=1（源码树零缓存铁律）、3 次取中位防抖红。
    import 抛错即红，且 stderr 尾部进断言消息。
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    durations: list[float] = []
    for _ in range(_IMPORT_RUNS):
        try:
            proc = subprocess.run(
                [_probe_python(), "-c", _IMPORT_PROBE_CODE],
                capture_output=True,
                cwd=str(_REPO_ROOT),
                env=env,
                timeout=_IMPORT_PROBE_TIMEOUT_S,
                check=False,  # 非零退出由下方 returncode 断言给出可读报错
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(
                f"整包导入子进程超时（>{_IMPORT_PROBE_TIMEOUT_S}s）——疑似 import 期挂死"
            ) from exc
        stderr_tail = proc.stderr.decode(errors="replace")[-800:]
        assert proc.returncode == 0, (
            f"整包导入子进程失败（exit={proc.returncode}）：\n{stderr_tail}"
        )
        try:
            durations.append(float(proc.stdout.decode(errors="replace").strip()))
        except ValueError as exc:
            raise AssertionError(
                f"导入探针输出无法解析：stdout="
                f"{proc.stdout.decode(errors='replace')[-200:]!r}，stderr={stderr_tail!r}"
            ) from exc
    median = statistics.median(durations)
    assert median < _IMPORT_GATE_THRESHOLD_S, (
        f"整包导入 {_IMPORT_RUNS} 次中位 {median:.2f}s"
        f"（阈值 {_IMPORT_GATE_THRESHOLD_S}s，基线 ~2s）——疑似 import 期塞重活；"
        f"单次={[round(d, 2) for d in durations]}s"
    )
