"""宿主机状态能力入口（需求 5 呈现腿，capability_id ``bot.host_state``）。

超管问「机器现在什么样」→ 一句话回**逐项读数 + 宿主机状态卡图**。本文件只做
三件事：**认触发、把角色门、把报告装配成 ``CapabilityResult``**。

- 取数**零自有腿**：全部走 ``domains/ops/host_metrics``（需求 5 唯一取数真身，
  见 ``tests/test_host_metrics_single_source.py`` 的门）；本文件对真身入口的
  直调已按该门腿 D 的口径登记（「明确改吃真身并在此登记」那条路）。
- 出卡**零第二渲染器**：payload 由 ``host_metrics.assemble_card_payload`` 拼
  （全仓唯一拼装器），落图只经 ``monitor/host_card.render_payload_png``
  （与诊断卡同一条 ``render_html_card`` 路、通用卡模板 ``page_type=universal``，
  不新增 Jinja 模板 → 渲染契约清单与样张基线零扰动）。
- 版本五项（NoneBot/OneBot 适配器/协议端/插件包/构建）随真身的版本腿走
  ``error_report._version_pairs`` 现算，本文件里**没有任何版本号字面量**
  （由 tests/test_host_state_card.py 的形态锁执法）。

线程口径（与 echo ``/bot status`` 附块的既有先例同型）：真身同步采集含
200ms CPU 采样与 nvidia-smi 探测、渲染是秒级阻塞活，**一律不许落在事件循环
线程上**。能力被线程池 offload 时走「现取 + 出卡」满血腿；被 loop 直接调时
降级为「只读适配器缓存、不出卡、如实说明」，绝不偷偷在环上现取。

装配状态：**只交付函数入口，未接四处 Keystone 声明**（RouteKind 枚举行 /
``build_route_rules()`` RouteRule+闭包 / ``build_interface_manifest()``
InterfaceEntry / ``capability_registry`` 的 RouteCapabilityDecl+InterfaceDecl+
HelpTopicDecl）。路由与帮助主题的注册是主代理的活——触发词表已在
``DEFAULT_TRIGGER_WORDS`` 备好，帮助侧登记时须与之逐词对齐（触发词双向门会
双向 diff，写一头必红）。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_SUPER_ADMIN,
)
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger
from plugins.bot_unified_runtime.domains.ops import host_metrics as hm

CAPABILITY_ID = "bot.host_state"

# 触发词表（简中/繁中/英文/拼音，与 randpic 的 DEFAULT_TRIGGER_WORDS 同族形态）。
# 主代理接线时把这组词同步进 base_router 谓词与 echo 帮助词表——双向门按词级
# diff 执法，两头必须一字不差。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "宿主机状态",
    "机器状态",
    "机器配置",
    "宿主状态",
    "宿主機狀態",
    "機器狀態",
    "hoststate",
    "jiqizhuangtai",
    "jizhuangtai",
    "jiqipeizhi",
)

# 词尾边界集：与 randpic/media_archive 现行手抄串逐字节相同（中央权威集加宽
# 属行为变更，本席不动别的能力的既有口径，只对齐同族现状）。
_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈～~"

CARD_FAIL_NOTE = "宿主机卡未出图（渲染后端不可用），以上读数即全部结果。"
LOOP_DEGRADE_NOTE = (
    "本轮宿主机卡未生成：本能力未接入线程池 offload，事件循环线程上不做"
    "秒级采集与渲染。"
)
NO_DATA_LINE = (
    "宿主机（超管视图）：这会儿拿不到读数——采集器没有可用数据源"
    "（psutil 缺席，或缓存里还没有任何一份线程池现取的快照）。"
)


def is_host_state_command(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> bool:
    """触发判定：整句等于触发词，或触发词后跟标点/空白边界（randpic 同判据）。"""
    triggers = tuple(trigger_words) if trigger_words else DEFAULT_TRIGGER_WORDS
    return is_trigger(
        text,
        triggers,
        case_insensitive=False,
        bare_word=True,
        newline_as_space=False,
        boundary_chars=_BOUNDARY_CHARS,
        extra_boundary_chars="",
    )


def is_super_admin_actor(actor_roles: list[str] | None) -> bool:
    """角色判定只认唯一角色源 ``ROLE_SUPER_ADMIN``（echo 附块同口径，零新名单）。"""
    roles = {str(role).strip().lower() for role in (actor_roles or [])}
    return ROLE_SUPER_ADMIN in roles


def _running_loop_here() -> bool:
    """当前线程是否跑着事件循环（能力被线程池 offload 时返回 False）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def host_state_body_lines(
    report: hm.HostMetricsReport,
) -> list[str]:
    """读数→人话行（首行带取样时刻标注）。纯文本面与卡失败兜底共用这一份。"""
    lines = [f"宿主机（超管视图，取样 {report.taken_at}）："]
    lines += [f"{label}：{value}" for label, value in hm.metrics_rows(report)]
    return lines


def build_host_state_result(
    report: hm.HostMetricsReport,
    *,
    request_id: str = "",
    render: bool = True,
    backend: Any = None,
    card_dir: str | None = None,
) -> CapabilityResult:
    """把一份真身报告装配成 ``CapabilityResult``（呈现契约层 1 的唯一出口）。

    - 卡走唯一落图口；**出图成功**才填 ``images``（``[{"file": path}]``，
      与 randpic/echo 附块同一字段口径）。
    - ``body`` 恒为逐项读数行——图挂了它是兜底，图活着它是文字账；
      卡未出时再补一行 ``CARD_FAIL_NOTE``，绝不让读数静默消失。
    """
    lines = host_state_body_lines(report)
    images: list[dict[str, Any]] = []
    if render:
        from plugins.bot_unified_runtime.domains.ops.monitor import host_card

        png = host_card.render_payload_png(
            hm.build_host_metrics_card_payload(report),
            backend=backend,
            card_dir=card_dir,
        )
        if png:
            images = [{"file": png}]
        else:
            lines.append(CARD_FAIL_NOTE)
    return CapabilityResult(
        request_id=request_id or new_request_id("host_state"),
        capability_id=CAPABILITY_ID,
        kind="text",
        title="宿主机状态",
        body="\n".join(lines),
        images=images,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["host_state", "card_sent" if images else "card_missing"],
    )


def _gate_result(request_id: str) -> CapabilityResult:
    """非超管门：话术走 Q-02 既有轮换池，且**一个读数都不采**。"""
    return CapabilityResult(
        request_id=request_id,
        capability_id=CAPABILITY_ID,
        kind="text",
        title="宿主机状态",
        body=random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(
            action="看宿主机状态"
        ),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["host_state", "gate_not_super_admin"],
    )


def _loop_degraded_result(request_id: str) -> CapabilityResult:
    """loop 线程降级腿：只吃适配器缓存（冷缓存=空组），不出卡、不现取。

    走 ``host_status.cached_host_snapshot(allow_blocking=False)`` 这条已登记的
    唯一缝——缓存里有什么就说什么，并明写为什么这一轮没有图。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    groups, taken_at = host_status.cached_host_snapshot(allow_blocking=False)
    rows = [row for items in groups.values() for row in items]
    if not rows:
        body = NO_DATA_LINE + "\n" + LOOP_DEGRADE_NOTE
    else:
        lead = f"宿主机（超管视图，取样 {taken_at}）：" if taken_at else "宿主机（超管视图）："
        body = "\n".join([lead] + [f"{label}：{value}" for label, value in rows] + [LOOP_DEGRADE_NOTE])
    return CapabilityResult(
        request_id=request_id,
        capability_id=CAPABILITY_ID,
        kind="text",
        title="宿主机状态",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["host_state", "loop_degraded"],
    )


def build_host_state_capability(config: Any | None = None) -> Any:
    """构建宿主机状态能力：与 randpic 一致，返回 ``(message, decision) -> 结果``。

    ``config`` 今天不读任何键（无自有配置面；本席禁写 config.py）。将来若加
    触发词/开关键，从这儿接，保持装配点在主代理手里。
    """

    def capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
        request_id = str(getattr(message, "request_id", "") or "") or new_request_id(
            "host_state"
        )
        text = str(getattr(message, "plain_text", "") or "")
        if not is_host_state_command(text):
            return CapabilityResult(
                request_id=request_id,
                capability_id=CAPABILITY_ID,
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["host_state", "skip_no_trigger"],
            )
        actor_roles = list(getattr(decision, "actor_roles", []) or [])
        if not is_super_admin_actor(actor_roles):
            return _gate_result(request_id)
        if _running_loop_here():
            return _loop_degraded_result(request_id)
        # 线程池里：现取满血 + 出卡（渲染后端不可用时自动退纯文本 + 点名说明）。
        report = hm.collect_host_metrics_sync()
        return build_host_state_result(report, request_id=request_id)

    return capability


__all__ = [
    "CAPABILITY_ID",
    "CARD_FAIL_NOTE",
    "DEFAULT_TRIGGER_WORDS",
    "LOOP_DEGRADE_NOTE",
    "NO_DATA_LINE",
    "build_host_state_capability",
    "build_host_state_result",
    "host_state_body_lines",
    "is_host_state_command",
    "is_super_admin_actor",
]
