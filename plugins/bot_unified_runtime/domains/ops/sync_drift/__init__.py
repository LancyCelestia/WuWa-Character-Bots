"""一致性漂移「运行期巡检 + 超管教程告警」（IALERT 席，2026-09-20）。

用户规格：「实在不行的要在 qq、telegram、mail 提醒超级管理员去更改，要求提供教程，
要求教程细致入微」。本包只做**告警 + 教程投递**这半个能力；「能自动生成的一律自动
生成」的生成化改造另席负责。

模块分层：
* ``registry``：漂移登记表（真相源 ↔ 副本 ↔ 复算命令 ↔ 教程生成器入口），只读三态。
* ``tutorial``：修法教程**现场生成**（取数只 import 既有生成器，零手写副本）。
* ``service``：巡检调度 + 三通道投递（全部复用 ``domains/ops/monitor/alerts`` 与
  ``mail_bridge`` 中央件，零新发送路径）。

接线（缺省关，用户裁决后再动根 ``__init__.py``）::

    from plugins.bot_unified_runtime.domains.ops.sync_drift import install
    install(scheduler=scheduler, config=config, pipeline=pipeline, online_bots=_all_online_bots)
"""

from .registry import (
    DRIFT_CHECKS,
    UNVERIFIABLE_PREFIX,
    DriftCheck,
    DriftFinding,
    checks_for,
)
from .service import (
    JOB_ID,
    REPO_ROOT,
    DriftAlert,
    SyncDriftService,
    build_drift_alert,
    build_service,
    drift_findings,
    install,
    registered_surfaces,
    scan_drift,
    scan_surface,
)
from .tutorial import build_fix_steps

__all__ = [
    "DRIFT_CHECKS",
    "JOB_ID",
    "REPO_ROOT",
    "UNVERIFIABLE_PREFIX",
    "DriftAlert",
    "DriftCheck",
    "DriftFinding",
    "SyncDriftService",
    "build_drift_alert",
    "build_fix_steps",
    "build_service",
    "checks_for",
    "drift_findings",
    "install",
    "registered_surfaces",
    "scan_drift",
    "scan_surface",
]
