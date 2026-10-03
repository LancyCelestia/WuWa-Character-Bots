"""轻量宿主占用快照的**单行文本口**（文件链路波供件：给人格上下文注记用）。

与既有两件的关系（不建第二真身，取数口径全部继承）：

- 采样**只复用** ``domains/ops/host_metrics.py`` 的在册采集器（``_collect_spec``）——
  CPU 占用率/内存占用率的 psutil 采样、200ms 窗、缺包诚实降级全在真身那一处；
  本文件体内没有任何 psutil / 注册表 / 磁盘直调（AST 自门锁在
  ``tests/test_host_snapshot_section.py``，防未来长出自己的取数点，撞
  ``tests/test_single_entry_gates.py`` 门②的归属账）。
- 缓存口径照抄 ``monitor/host_status.py::cached_host_snapshot``：模块级
  ``threading.Lock`` + ``monotonic`` 墙钟 + 测试专用失效口。区别只有两处：
  TTL 缺省 30s（本口供每轮对话注记，比命令面的 90s 更激进）；采样失败
  **不占缓存**（transient 故障下次还有机会，psutil 缺席那类永久缺席每次
  现查也是零成本——真身对缺包直接折「未探测」，不做任何阻塞采样）。

三条硬口径：

- **任何失败 = 空串（fail-open）**：调用方拿不到注记就整段缺席，绝不编数、
  绝不抛异常打断调用链（真身单项「未探测/采集失败」本口一律视为「没有这一项」）。
- **不做权限门**：本口只产文本，注入侧（分区/提示词装配）按角色裁可见面。
- **采样阻塞约 200ms（缓存过期时）**：CPU 占用率必须带间隔窗采样（真身口径，
  ``interval=None`` 的首采是自进程启动以来的平均值＝假数）。缓存命中的调用
  零阻塞；过期后的第一次调用阻塞一次。事件循环线程上不要调——聊天能力在
  线程池里跑，装配点请照 ``cached_host_snapshot(allow_blocking=True)`` 同样的
  场景使用本口。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from plugins.bot_unified_runtime.domains.ops import host_metrics

__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "SECTION_HEADER",
    "host_snapshot_section_text",
    "invalidate_host_snapshot_for_tests",
]

#: 缺省缓存窗：每轮对话注记共享一份采样，30s 内的后续消息全部零成本。
DEFAULT_MAX_AGE_SECONDS = 30.0

#: 分区自题头（2026-10-03 席6 按消费者契约补）：providers.py 借 quirks_section 这个
#: 「裸渲染自题分区」槽注入——chat.py 对该槽整段原样输出、不加盖头，没有自题头
#: 快照行就混进人格怪癖里不可分辨。头部并进缓存文本（缓存的就是最终交出形态）。
SECTION_HEADER = "【宿主快照】"

#: 真身在册指标 id（``host_metrics.METRIC_SPECS`` 的两枚占用项）。字符串常量：
#: 门②按 AST 属性访问认读点，这里的 id 是指标声明，不是取数。
_CPU_METRIC_ID = "cpu_percent"
_MEMORY_METRIC_ID = "memory"

#: 从真身的展示值（CPU：``"12.3%"``；内存：``"总 31.8 GB · 可用 12.3 GB · 占用 46.3%"``）
#: 里取百分数的窄口。解析失败＝这一项没有，不猜。
_PERCENT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")

_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_CACHE: dict[str, Any] = {"text": "", "wall_clock": 0.0, "sampled": False}


def _metric_percent(metric_id: str) -> float | None:
    """叫真身在册采集器取一项占用百分数；取不到/解析不出 = ``None``（fail-open）。

    为什么走 ``_collect_spec`` 而不是 ``cached_host_snapshot``：后者一跑就是
    **全指标**采集（注册表扫描 + 子进程只读查询），供命令面整卡用；本口只要
    两枚占用项，逐项调真身采集器才是「轻量」且不绕判据——采样体仍在真身文件里，
    本文件零机器读数。
    """
    try:
        items = host_metrics._collect_spec(metric_id)
    except Exception:  # noqa: BLE001 - 真身收口已兜，这里再兜一层保 fail-open 承诺
        return None
    for item in items:
        if getattr(item, "state", "") != host_metrics.STATE_OK:
            continue
        match = _PERCENT_RE.search(str(getattr(item, "value", "") or ""))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _sample_usage_text() -> str:
    """采样一次并组装单行文本；两项全空 = 空串（调用方整段缺席）。"""
    cpu = _metric_percent(_CPU_METRIC_ID)
    memory = _metric_percent(_MEMORY_METRIC_ID)
    if cpu is None and memory is None:
        return ""
    parts: list[str] = []
    if cpu is not None:
        parts.append(f"CPU {cpu:.0f}%")
    if memory is not None:
        parts.append(f"内存 {memory:.0f}%")
    stamp = time.strftime("%H:%M:%S")
    return f"{' · '.join(parts)}（采样 {stamp}）"


def host_snapshot_section_text(max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> str:
    """「【宿主快照】CPU 12% · 内存 46%（采样 12:03:05）」形态的宿主占用注记。

    - ``max_age_seconds``＝缓存窗（缺省 30s）：窗内返回同一份采样文本（零阻塞）；
      过期后现采一次并回填。小于等于 0 = 每次现采。参数不可解析（None/非数）
      按契约 fail-open 回空串，绝不外抛。
    - 失败（psutil 缺席/采样异常/解析不出）＝空串，**不占缓存**（下次还能重试）。
    - 本函数可能阻塞约 200ms（缓存过期的第一次调用，CPU 间隔窗采样）——
      只准在工作线程里调，别上事件循环。
    - 无权限门：可见面由注入侧按角色裁。
    """
    try:
        ttl = max(0.0, float(max_age_seconds))
    except (TypeError, ValueError):
        return ""
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT_CACHE["sampled"]:
            age = time.monotonic() - float(_SNAPSHOT_CACHE["wall_clock"])
            # 严格小于：Windows monotonic 粒度下 age 会取到 0.0，`<=` 会让
            # ttl=0（文档承诺的「每次现采」）在边界上退化成缓存命中。
            if age < ttl:
                return str(_SNAPSHOT_CACHE["text"])
    try:
        text = _sample_usage_text()
    except Exception:  # noqa: BLE001 - fail-open：注记拿不到就缺席，绝不打断调用链
        return ""
    if not text:
        return ""
    labelled = f"{SECTION_HEADER}{text}"
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE["text"] = labelled
        _SNAPSHOT_CACHE["wall_clock"] = time.monotonic()
        _SNAPSHOT_CACHE["sampled"] = True
    return labelled


def invalidate_host_snapshot_for_tests() -> None:
    """测试专用：清空 TTL 缓存（用例间互不串读数）。"""
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE["text"] = ""
        _SNAPSHOT_CACHE["wall_clock"] = 0.0
        _SNAPSHOT_CACHE["sampled"] = False
