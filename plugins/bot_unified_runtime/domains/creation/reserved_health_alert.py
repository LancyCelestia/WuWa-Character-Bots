"""creation 预留面（AI 绘图 / 语音对接点）的巡检告警生产者（中央调度收编波 P5-E3）。

补的洞：目标 4 要求"未接 provider 必返 UNAVAILABLE **且诊断卡与巡检告警都可见**"。
诊断卡那条腿已由 `INVOKER_ERROR_DATA_KEY` → 层 1 re-raise 闭合（调用当场可见）；
但**没人调用就没人知道它坏了**——巡检面此前零生产者。本件补这一面。

手法＝照 `domains/media/voice_health_alert.py`（S-OBS）同构，不新造第三条告警路：
sink 由装配点注入（root 现场复用同一个 `_push_probe_issue`，即共用中央告警口与
`AdminAlertSuppression` 300s 抑制），本模块不 import root、不猜管理员名单、不直发消息。

**告警判据分两层，两把尺子（2026-09-24 巡检波 S102 补，勿混用）**：
- 「要而不得」＝ `bot_creation_*_provider` 已填（管理员显式指定了 provider）但**该对接点给不
  出真实结果** ⇒ 配置面不一致，属故障，kind=`config_missing`；**按需读数（/bot status）与周期
  巡检都投**，每次现算、陈旧不粘滞。
- 「键空缺位」＝ 她从没填过 provider。这**不是故障**，是声明中的预留位——但 mandate 要求「缺位
  必须巡检可见」，故由**周期巡检**投一条 kind=`creation_not_configured` 的**一次性**告警（本进程
  仅成功投一次，见 `_not_configured_fired` 门）让运维露头；**/bot status 面不投此腿**，仍只作
  「未接 provider，诚实不可用」状态行。理由：对未实现预留位**每 300s 反复**敲会把真告警淹没
  （本仓告警面曾因刷屏被加冷却闸）——一次性 + 只在巡检触发两头都占：缺位露头、又不刷屏。
  「响一次」由「仅投递成功后置 fired」保证：装配晚到不能把缺位永久隐身。

**"给不给得出"要分通道问（S69 现算钉死的一枚真洞，勿退回单一在场性腿）**：
- `creation.tts`：语音执行体（media 域唯一合成口）自 P4-C2 起真由中央 handler 在册即已满足，
  所以装配层注入的 `has_registered_handler` 探针就是"执行体在场"的有效代理（S50 假告警教训）。
- `creation.image`：handler 包壳自 P5/S09 起**恒在册**，但它只在有适配器时出图、否则恒返
  `UNAVAILABLE`。于是"包壳在册"对绘画**根本不是**"用户填的选择器被满足"的证据——若照 tts 的
  在场性腿判，绘画即便被填了 provider、PROVIDER_REGISTRY 里却没有适配器，也会**静默不告警**
  （现算 2026-09-24T00:32Z：probe=has_registered_handler + 键已填 ⇒ findings={} 且状态行说
  "未接 provider"，与事实相反）。故绘画这条腿**改问工厂唯一派发口**
  :func:`~plugins.bot_unified_runtime.domains.creation.image.provider_factory.build_image_provider`
  现算 `wired` 才算满足（工厂内部仍复用 reserved_provider 的"已配"尺子＝家规 1，本件不立第二把尺子、
  不新造第二条告警路，仍走同一个 sink + flush）。

其余纪律：
- **陈旧不粘滞**：每次 check 重算并**整体替换** pending（键被清空 ⇒ 旧 issue 自动撤回）；
- **去重不自造节流**：投递折叠在中央抑制器，本件只保证"读一次·投一次·清一次"；
- **fail-open**：sink 抛异常只吞不冒（告警链坏了不能拖垮触发它的状态查询）；
- **零网络、零消息、零配置写入**；摘要必过 `redact_local_secrets`（AGENTS 铁律 3）。

**为什么这里没有锁**（`test_v21_creation_skeleton.py::test_reserved_modules_forbidden_imports`
禁止 creation 域 import `threading`——该域是纯协议壳，不起线程也不自带互斥体）：
本件的全部可变状态只有 `_sink` 与 `_pending` 两枚**模块名绑定**，一律整体替换、从不原地改，
CPython 的名字赋值本身原子 ⇒ 读者只会看到"旧的一份"或"新的一份"，不会看到半成品。
剩下的唯一竞态是「A 线程 flush 正在投递、B 线程 check 同时整体替换 pending」：
最坏结果是已投的那条被 B 的新表覆盖、下一轮再投一次＝**重复一条告警**，
而中央抑制器（300s 同 kind 折叠）正是为此存在——所以这里宁可留一个有界的重复，
也不为一个可被上游折叠的噪音在纯协议壳里加锁。若哪天抑制器摘掉，这条要重新评估。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.contracts import OperationalIssue, new_debug_id
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

from . import reserved_provider

logger = logging.getLogger(__name__)

_Sink = Callable[[OperationalIssue], None]

#: 与 echo/tts 族同口径（issue 会进诊断卡与管理员私聊，不能裸长文）。
_ISSUE_SUMMARY_MAX_CHARS = 200

_PresenceProbe = Callable[[str], bool]

_sink: _Sink | None = None
#: 执行体在场性探针（capability_id → 中央是否已注册 handler）。**由装配层注入**：
#: creation 域按既有教义不 import 中央层（``reserved_provider`` 头注同一口径），
#: 所以"这条通道的执行体接上了没有"这个中央事实只能从外面递进来。
_execution_probe: _PresenceProbe | None = None
#: channel → 待投 issue；只整体替换、从不原地改（见模块 docstring「为什么这里没有锁」）。
_pending: dict[str, OperationalIssue] = {}

#: 「键空＝她从没填过 provider」的诚实态 kind。与 ``config_missing`` 严格分家：
#: ``config_missing``=「填了 provider 却给不出适配器」＝故障；本 kind=「整枚对接点尚未
#: 配置」＝缺位。二者语义不同、不得混用（混用会让「从没碰过」被读成「配了但坏了」）。
_NOT_CONFIGURED_KIND = "creation_not_configured"

#: 「未配置」待投 issue 的**独立**小桶。与 ``_pending`` 分家是因为
#: ``check_reserved_channels`` 每轮**整体替换** ``_pending``，把一次性 issue 抹掉；
#: 分桶才能保证「缺位响得出、且只响一次」。
_not_configured_pending: dict[str, OperationalIssue] = {}
#: 本进程是否已就「未配置」**成功投出**过一次（一次性口；仅投递成功后置真）。
_not_configured_fired: bool = False


def install_execution_presence_probe(probe: _PresenceProbe | None) -> None:
    """装配点注入执行体在场性探针（``None``=未接）。幂等、进程内。

    补的是 S50 实锤的假告警洞（GAP-CREAT-ALERT-STALE）：presence 判据键
    ``bot_tts_api_url`` 生产缺省恒非空 ⇒ 只按"键填了没"判"要而不得"，会在
    P4-C2 把语音执行体接上之后**每次 `/bot status` 仍报"实现工厂未接入"**。
    现在加第二腿：执行体已在册 ⇒ 通道已被满足 ⇒ 不告警。
    探针未注入＝**不可判**：宁可少投一条告警（状态行明写 ``probe=missing``），
    也不投一条可能与事实相反的告警——噪声淹没真告警有前例。
    """
    global _execution_probe
    _execution_probe = probe


def install_reserved_alert_sink(sink: _Sink | None) -> None:
    """装配点注入/撤除中央告警 sink（``None``=未接或下线）。幂等、进程内。"""
    global _sink
    _sink = sink


def has_alert_sink() -> bool:
    """中央告警口是否已接好（供装配自检与状态行诚实标注）。"""
    return _sink is not None


def _issue_for(channel: str, reason: str) -> OperationalIssue:
    """构造"要而不得"issue：``kind`` 复用既有 ``config_missing``（禁新造 kind）。"""
    raw = f"creation 对接点 {channel} 已指定 provider 但无可用适配器：{reason}"
    return OperationalIssue(
        stage="creation",
        kind="config_missing",
        retryable=True,
        debug_id=new_debug_id("creation_reserved"),
        safe_summary=redact_local_secrets(raw)[:_ISSUE_SUMMARY_MAX_CHARS].strip(),
    )


#: 绘画通道 id（本件唯一需要"分通道问"的一处——见模块 docstring 判据段）。
_IMAGE_CHANNEL = "creation.image"


def _image_adapter_wired(config: Any) -> bool:
    """绘画是否真给得出适配器：现问**工厂唯一派发口**，不凭 handler 包壳在场性。

    ``build_image_provider`` 只在 ``PROVIDER_REGISTRY`` 能派发出一个真实（非离线 mock、
    合 ``ImageProvider`` 协议面）适配器时判 ``wired``；它内部仍复用 reserved_provider 的
    "已配"尺子（家规 1），所以本函数不是第二把"是否已配"的尺子，而是回答另一个问题：
    "配置值到底能不能落到一个能出图的适配器上"。函数体内延迟 import（域→兄弟件只作回调、
    不在模块期把依赖面提前绑死），零网络/零配置写入/零文件 I/O。
    """
    from .image.provider_factory import build_image_provider

    return build_image_provider(config).state == "wired"


def check_reserved_channels(config: Any) -> dict[str, str]:
    """现算各通道"要而不得"状态，并**整体替换** pending issue。

    返回 ``channel → 状态说明``（只含"配了 provider 却给不出真实结果"的通道；
    全部未过问 / 全部已满足时为空表）。状态行与告警共用本函数的结论——
    同一判据、禁两处各算一遍。

    两腿按通道分别成立才算"要而不得"：
    ①``provider_configured``（她真过问过：键非空）；
    ②该通道"给不给得出"——语音看装配层注入的执行体在场性探针（缺 ② 就是 S50 假告警）；
      绘画看工厂 ``wired``（缺 ② 就是 S69 现算钉死的"填了却不告警、状态行还撒谎"）。
    """
    global _pending
    findings: dict[str, str] = {}
    fresh: dict[str, OperationalIssue] = {}
    for channel in reserved_provider.CHANNEL_IDS:
        probe_id = f"{channel}.check"
        if not reserved_provider.provider_configured(config, probe_id):
            # 没填 provider=声明中的预留位（诚实未实现），不是故障 ⇒ 不告警、不进 pending。
            continue
        if channel == _IMAGE_CHANNEL:
            # 绘画腿：handler 包壳恒在册，在场性探针会假报"已满足"⇒ 只能问工厂。
            if _image_adapter_wired(config):
                continue
            findings[channel] = (
                f"{channel}：provider 已配置但工厂无可用适配器"
                "（PROVIDER_REGISTRY 未登记该选择器，或非真实/mock/协议不合），诚实 unavailable"
            )
        else:
            # 语音腿：执行体（media 唯一合成口）由中央 handler 在册即已满足（S50 教训）。
            if _execution_probe is not None and _execution_probe(channel):
                continue
            if _execution_probe is None:
                # 探针未注入＝不可判。仍投（宁可吵也不静默），但文案**不许断言"未接入"**，
                # 免得一条"探针没装"被读成"能力坏了"。
                findings[channel] = (
                    f"{channel}：provider 已配置，但执行体在场性探针未注入（probe=missing），"
                    "按未满足处理"
                )
            else:
                findings[channel] = (
                    f"{channel}：provider 已配置但中央执行体未注册（not_wired），诚实 unavailable"
                )
        fresh[channel] = _issue_for(channel, findings[channel])
    _pending = fresh
    return findings


def pending_channels() -> tuple[str, ...]:
    """当前待投 issue 的通道名（测试/巡检取证用；不返回 issue 本体）。"""
    return tuple(sorted(_pending))


# ---------------------------------------------------------------------------
# 缺位可见性（巡检面专用一次性 NOT_CONFIGURED 腿）
#
# 为什么只挂在巡检、不挂在 /bot status：`test_unconfigured_provider_is_declared_
# placeholder_not_incident` 钉死「未配 provider=诚实预留位、不算故障」这条既有口径
# （status 面绝不为她从没碰过的对接点投 config_missing，否则每 300s 敲真告警被淹没）。
# mandate 的「缺位必须巡检可见」不与之冲突——由周期巡检**每进程只响一次**的 NOT_CONFIGURED
# 承担，二者分层：status=按需读数、patrol=主动让缺位对运维露头。
# ---------------------------------------------------------------------------


def not_configured_channels(config: Any) -> tuple[str, ...]:
    """现算哪些通道「她从没填过 provider」（键空）。

    与 :func:`reserved_provider.provider_configured` **反相、同一把尺子**（禁另算一遍）：
    逐 ``CHANNEL_IDS`` 用 ``f"{channel}.check"`` 探针位判定。全部已填 ⇒ 空表。
    """
    return tuple(
        channel
        for channel in reserved_provider.CHANNEL_IDS
        if not reserved_provider.provider_configured(config, f"{channel}.check")
    )


def _not_configured_issue(channels: tuple[str, ...]) -> OperationalIssue:
    """构造「缺位」一次性 issue：kind 走 ``creation_not_configured``、不可重试（这是常态
    配置态、非瞬时故障），摘要必过 ``redact_local_secrets``（AGENTS 铁律 3）。"""
    raw = (
        "creation 对接点 "
        + "、".join(channels)
        + " 未配置 provider（声明中的预留位，尚不可用）：巡检面据 mandate 让缺位对运维可见，本进程仅报一次"
    )
    return OperationalIssue(
        stage="creation",
        kind=_NOT_CONFIGURED_KIND,
        retryable=False,
        debug_id=new_debug_id("creation_reserved_not_configured"),
        safe_summary=redact_local_secrets(raw)[:_ISSUE_SUMMARY_MAX_CHARS].strip(),
    )


def has_fired_not_configured() -> bool:
    """本进程是否已就「未配置」成功投出过一次（供巡检自检与测试取证）。"""
    return _not_configured_fired


def check_and_arm_not_configured(config: Any) -> bool:
    """若存在未配置通道且本进程尚未报过 ⇒ 武装一条一次性 NOT_CONFIGURED pending。

    返回「本次是否新武装」。已报过、或全部通道已配置 ⇒ 不武装且清空桶（防恢复/改配后残留旧缺位）。
    置 fired 的时机在 :func:`flush_not_configured_issue` 成功投递之后——装配晚到不能把缺位永久隐身。
    """
    global _not_configured_pending
    if _not_configured_fired:
        _not_configured_pending = {}
        return False
    empty = not_configured_channels(config)
    if not empty:
        _not_configured_pending = {}
        return False
    _not_configured_pending = {"__not_configured__": _not_configured_issue(empty)}
    return True


def flush_not_configured_issue() -> int:
    """把「未配置」一次性 issue 交给中央 sink；**只有成功投递才置 fired**（本进程只响一次）。

    sink 未注入 / 无 pending ⇒ 0 且**不置 fired**（留待下次巡检）；sink 抛错 ⇒ 0 且不置 fired
    （件仍在，下轮再投）。与 config_missing 腿「宁可晚到、不可静默丢件」同纪律。
    """
    global _not_configured_pending, _not_configured_fired
    sink = _sink
    if sink is None or not _not_configured_pending:
        return 0
    _channel, issue = next(iter(_not_configured_pending.items()))
    try:
        sink(issue)
    except Exception as exc:  # noqa: BLE001 - 告警链故障绝不冒泡到巡检调度
        logger.debug("creation not_configured alert sink failed: %s", exc)
        return 0
    _not_configured_pending = {}
    _not_configured_fired = True
    return 1


def patrol_reserved_health(config: Any) -> int:
    """周期巡检**唯一入口**：一趟跑完「要而不得」腿 + 「键空缺位」腿，各自 flush。

    由**装配层调度器**周期调用——本域按教义不起线程、不 import nonebot/asyncio（见模块头
    「为什么这里没有锁」），所以周期化只能由 root 侧挂；本函数自身零网络、零消息、零配置写入，
    投递全部走 root 注入的同一个中央 sink（``_push_probe_issue``）+ ``AdminAlertSuppression``
    300s 抑制，绝不新造第三条告警路。返回本次成功投递的总条数（含两类）。

    设计要点：
    - config_missing 腿照旧每轮重算（键回落到未填 ⇒ 旧 pending 自动撤回）；
    - NOT_CONFIGURED 腿只在本进程首次遇到缺位时响一次（``_not_configured_fired`` 门），
      后续巡检不再重复 ⇒ 既让缺位露头、又不把真告警淹掉（docstring 判据段的取舍）。
    """
    check_reserved_channels(config)
    delivered = flush_reserved_issues_to_alerts()
    check_and_arm_not_configured(config)
    delivered += flush_not_configured_issue()
    return delivered


def flush_reserved_issues_to_alerts() -> int:
    """把 pending issue 逐条交给中央告警口；投成功即清（至多投一次）。

    返回本次成功投递的条数。sink 未注入 / 无 pending / sink 抛错都不丢件：
    抛错时**保留**该条 pending，等下一次查询再投（告警宁可晚到，不可静默消失）。
    清理按"整表重建"而非原地 pop——并发 check 换过的新 issue 下一轮必然被
    ``check_reserved_channels`` 重算出来，所以这里最坏只晚一轮，不会静默丢失。
    """
    global _pending
    sink = _sink
    queued = _pending
    if sink is None or not queued:
        return 0
    delivered: list[str] = []
    for channel, issue in queued.items():
        try:
            sink(issue)
        except Exception as exc:  # noqa: BLE001 - 告警链故障绝不冒泡到触发方
            logger.debug("creation reserved alert sink failed for %s: %s", channel, exc)
            continue
        delivered.append(channel)
    if delivered:
        settled = set(delivered)
        _pending = {channel: issue for channel, issue in _pending.items() if channel not in settled}
    return len(delivered)


def creation_status_line(config: Any) -> str:
    """``/bot status`` 一行式 creation 对接点摘要（与语音行并列，不复述其内容）。

    - 全通道未填 provider ⇒ ``reserved(未接 provider，诚实不可用)``（**不冒充可用**）；
    - 有通道"要而不得" ⇒ 逐通道点名原因，并标告警口是否已接（没接就直说 no_sink，
      免得"有告警面"被当成"已投递"）。
    """
    findings = check_reserved_channels(config)
    if not findings:
        return "绘画/生成对接点：reserved(未接 provider，诚实不可用)，alert=no_pending"
    detail = "；".join(f"{channel}={reason}" for channel, reason in sorted(findings.items()))
    return (
        f"绘画/生成对接点：requested_but_missing（{detail}），"
        f"alert={'sink_ready' if has_alert_sink() else 'no_sink'}"
    )


def reset_state() -> None:
    """测试隔离口：清空 pending（含一次性 not_configured 桶与 fired 标记；不动 sink——
    装配面由测试自己注/撤）。"""
    global _pending, _not_configured_pending, _not_configured_fired
    _pending = {}
    _not_configured_pending = {}
    _not_configured_fired = False
