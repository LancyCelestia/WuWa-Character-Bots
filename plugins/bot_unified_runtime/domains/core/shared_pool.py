"""进程级共享有界线程池（P2 减量波：线程 churn 治理）。

背景：search_v21 / acg_search / news_feeds / video_understanding / stocks
面板 / market_data.gather_within_budget 六个调用点各自
``ThreadPoolExecutor(max_workers=N)`` 逐次新建，功能触发时线程反复生灭。
本模块把它们收敛到**一个**进程级有界池。

共享语义与边界（接入前必读）：

- **惰性单例、绝不 shutdown**：首次 :func:`get_shared_pool` 创建，进程存活
  期常驻；调用方只许 submit/map，禁止 shutdown/close（没有"退出"语义可
  依赖）。
- **有界（8 workers）且不独占**：高并发时段某站点实际并发度可能低于它
  原先的 ``max_workers``（其余 worker 被兄弟站点占用），属预期降级——
  用吞吐换线程生灭，正确性不受影响。站点语义若要求"并发度＝条目数且
  ≤N"的强上限，须自行配信号量，不得改池子大小。
- **禁嵌套等待**：在本池任务内再向本池提交并**阻塞等待**，worker 全满
  时会线程饥饿死锁。现存六站点均已核实无嵌套（acg/news/gather 均在能力
  层调用，不在池任务内再提交）；新调用点接入前必须自查同一条。
- **完成语义归调用点**：本模块不替你 join。原先依赖 ``with`` 块退出
  join 的站点，改造后须用 ``concurrent.futures.wait(futures)``、消费完
  ``map`` 迭代器或逐 ``future.result()`` 等价保持"返回前所有 futures 已
  完成"；原先 ``shutdown(wait=False, cancel_futures=True)`` 的站点，改为
  对未完成 future 显式 ``cancel()``。
- 与既有专职池相互独立、不合并：``runtime/capability_protocols`` 的能力
  协议池、``chat_reply/runtime/pipeline`` 的 chat worker 池、
  ``ops/monitor/error_report`` 的渲染池、``render/renderer`` 的 mermaid
  池各有机能语义（有界提交门/专用命名/独立生命周期），不在本波范围。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

#: 共享池固定并发度；所有站点共用，不在调用点再调。
SHARED_POOL_MAX_WORKERS = 8

_SHARED_POOL: ThreadPoolExecutor | None = None
_INIT_LOCK = threading.Lock()


def get_shared_pool() -> ThreadPoolExecutor:
    """返回进程级共享线程池（惰性单例；调用方不得 shutdown）。"""
    global _SHARED_POOL
    if _SHARED_POOL is None:
        with _INIT_LOCK:
            if _SHARED_POOL is None:
                _SHARED_POOL = ThreadPoolExecutor(
                    max_workers=SHARED_POOL_MAX_WORKERS,
                    thread_name_prefix="shared-pool",
                )
    return _SHARED_POOL
