"""语音引擎健康 issue → 中央告警链的唯一生产消费者（S-OBS）。

补的洞（SEAT-S-GAPMAP「前 5 刀」第 3 刀 / report-T79）：``voice_health_probe`` 探测到
引擎不可达会构造 ``tts_service_unreachable`` ``OperationalIssue`` 存进模块态，只经
``last_operational_issue()`` 暴露，但全树**生产读者为 0**——诊断结论到不了运维。
本模块是它唯一的消费者，把 issue 交给**既有**中央告警链，绝不新造第三条告警路：

- **sink 由装配点注入**：``install_probe_alert_sink`` 的实参在 root ``__init__.py``
  现场包一层，落到 ``alerts.notify_operational_issue``（自带 ``AdminAlertSuppression``
  300s 抑制）。本模块不 import pipeline、不猜管理员名单、不直发任何消息——那是 root
  装配面（宪法：跨域取数/装配只在装配层做）。未注入 sink = 生产尚未接好，本模块诚实
  no-op、绝不静默丢件（issue 留在探针侧，装配到位后仍可投出，见 flush 语义）。
- **不贴 ``CapabilityResult``**：带 issue 的呈现结果会触发 pipeline A-19 群聊吞体，且
  探针 ``_last_issue`` 若不随投随清会永久误报——所以走后台 sink、且投一次清一次（drain）。
- **去重不自造节流**：同窗不重复构造在探针侧（``_ISSUE_COOLDOWN_SECONDS``）、投递折叠在
  中央（300s），本消费者只做「读一次·投一次·清一次」，不放第三把时间闸。
- **陈旧不粘滞**：探针恢复沿自动 ``clear_operational_issue``，加上此处 drain，
  已恢复引擎的旧 issue 既不会被反复投、也不会在探针侧悬着。
- **fail-open**：sink 抛异常只吞不冒（「failure must not recurse」，同
  ``alerts.build_alert_content_sink``）——告警链坏了不能拖垮触发它的状态查询。

纯库模块：只 import 探针与 contracts，不 import root、不 import tts.py、零网络、零消息。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from plugins.bot_unified_runtime.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.media import voice_health_probe as _probe

logger = logging.getLogger(__name__)

_Sink = Callable[[OperationalIssue], None]

_LOCK = threading.Lock()
_sink: _Sink | None = None


def install_probe_alert_sink(sink: _Sink | None) -> None:
    """装配点注入/撤除告警 sink（``None``=未接或下线）。幂等、进程内、无副作用。"""
    global _sink
    with _LOCK:
        _sink = sink


def has_alert_sink() -> bool:
    """当前是否已接好中央告警链（供装配自检 / 巡检器判定是否值得 flush）。"""
    with _LOCK:
        return _sink is not None


def flush_probe_issue_to_alerts() -> bool:
    """把探针 pending issue 投给中央告警链；投递成功即 drain（至多投一次）。

    返回 ``True``=本次有一条 issue 成功交给 sink；``False``=无 pending issue、
    尚未装配 sink、或 sink 抛错（后两者都不丢件，留待下次 flush）。
    """
    issue = _probe.last_operational_issue()  # 全树唯一生产读者（活性锁钉死）
    if issue is None:
        return False
    with _LOCK:
        sink = _sink
    if sink is None:
        return False
    try:
        sink(issue)
    except Exception as exc:  # noqa: BLE001 - 告警链故障绝不冒泡到触发方
        logger.debug("voice probe alert sink failed: %s", exc)
        return False
    _probe.clear_operational_issue()  # 投一次清一次：非粘滞
    return True
