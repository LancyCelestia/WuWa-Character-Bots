"""W12 主控接线：重启申请消费者（Bot 侧）+ 动作申请告警 kind。

W2-ACT 席交回两处「不在我文件域」的接线，本模块替主控落这两处，
**不改 `__init__.py` 的 12125 行**（那是本仓最烫的共享文件，W2-UI/W2-TOKENS/W2-RES 都在改它附近）。

两件事：

1. `install_action_request_runner(...)`：把 `build_action_request_runner` 挂到 driver 上。
   未接线 ⇒ 面板申请永远停在 `pending`，用户点了以为生效（`AGENTS.md` 台账 #63「批即落
   从未实现」同一类病灶）。
2. `ACTION_REQUEST_ALERT_KIND` 的常量：告警 sink 走 `OperationalIssue`，kind 必须在
   `alerts._KIND_PLAIN` 里有人话条目，否则用户只看到「出了个我还没登记成人话的错」。

接线位置由调用方决定（`__init__.py` 装配层），本模块只提供形状。
"""

from __future__ import annotations

import logging
from typing import Any

#: 告警 kind：重启申请（面板 → Bot 侧喊人）。与 `alerts._KIND_PLAIN` 同字面。
ACTION_REQUEST_ALERT_KIND = "action_request_pending"

#: 告警 stage：控制面动作族。
ACTION_REQUEST_ALERT_STAGE = "control_plane_action"


def install_action_request_runner(
    store_or_source: Any,
    *,
    driver: Any,
    alert_sink: Any,
    logger: Any | None = None,
) -> Any:
    """把重启申请消费者挂到 driver；返回 runner（调用方持有引用即可）。

    ``store_or_source`` 接受 `SQLiteConfigCommandStore` 或 `SQLiteActionRequestStore`
    （`build_action_request_runner` 自己归一）。
    """
    from .config_commands import build_action_request_runner

    runner = build_action_request_runner(
        store_or_source,
        alert_sink=alert_sink,
        logger=logger or logging.getLogger(__name__),
    )
    runner.register(driver)
    return runner


def build_alert_sink(
    push_issue: Any,
) -> Any:
    """把 ``push_issue(OperationalIssue)`` 包成消费者要的 ``alert_sink(text)``。

    消费者只会传一条**人话字符串**（它不 import 告警链，避免控制面依赖监控域）。
    这里把那段文字原样塞进 ``OperationalIssue.safe_summary``，stage/kind 用本模块
    在册常量 ⇒ 告警出口仍是全仓唯一那一条（`alerts.notify_operational_issue`），
    不新造第二条直发腿。
    """
    from ..domains.core.contracts.runtime import OperationalIssue

    if not callable(push_issue):
        raise TypeError("alert sink 需要一个可调用的 issue 推送口")

    def sink(text: str) -> None:
        push_issue(
            OperationalIssue(
                stage=ACTION_REQUEST_ALERT_STAGE,
                kind=ACTION_REQUEST_ALERT_KIND,
                retryable=False,
                safe_summary=str(text),
            )
        )

    return sink
