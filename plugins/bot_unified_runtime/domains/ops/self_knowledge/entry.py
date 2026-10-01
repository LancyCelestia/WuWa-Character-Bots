"""自我认知装配层（需求 10）——实现真身。

本模块是**装配**，不是第二真身。它把已经存在的三处读数口拼成一段可**确定性**
（不经大模型）朗读的自我认知，并可被一个命令能力复用：

- 时刻与四历法（农历/伊斯兰历/藏历/东正教历）+ 叙述台账更新历史：
  ``domains/ops/self_calendar.self_calendar_report``（历法换算唯一真身在
  ``domains/divination/data/multi_calendar``，本模块零第二套天文量）。
- 软件框架 / 适配器 / 插件版本 / 系统 / 构建 / git 提交历史：
  ``character/temporal.system_readout_lines``（版本唯一来源
  ``ops.monitor.host_status._runtime_versions`` → ``error_report._version_pairs``）。
- 功能清单（按管理员可见性收口）：``temporal.capability_index_lines``（声明源
  ``capability_registry``）。

本模块只补真身没干净露出的那一面：**本次进程实际装载的 NoneBot 插件清单**
（``nonebot.get_loaded_plugins()``，离线/未初始化时诚实说「未探测」，绝不猜）。

纪律（锁在 ``tests/test_self_knowledge_entry.py``）：
- 零历法常数、零版本号自算、零手写功能/计数——会随代码漂移的数一律现读（规则 10）。
- 每个子块各自 fail-open：拿不到就少那一块并留一行诚实说明，绝不 fail 成「看起来完整」。
- 出图前整段过 ``redact_local_secrets``（铁律 3）：命令正文是说给用户听的可见面。
- 不在模块导入期读钟；命令正文的时刻由运行期 ``(message, decision)`` 交来。
配置：零新键；``timezone_name`` 由调用方传 ``config.bot_timezone``。
接线：路由 kind / 帮助主题 / matcher / 配置键都在禁改共享文件里，走 ``patch-SELF.md``。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    CapabilityResult,
    SendPolicy,
    new_request_id,
)

logger = logging.getLogger(__name__)

#: 命令能力 id（在册登记见 patch-SELF.md；本模块只造执行体，不自行注册路由）。
SELF_KNOWLEDGE_CAPABILITY_ID = "bot.self_info"

#: 管理员可见性判据：命中其一即按管理员面收口（超管在 roles.py 里自动叠加 admin）。
_ADMIN_ROLE_NAMES = frozenset({"admin", "owner", "super_admin", "超管"})

#: 「取数口拿不到」的统一诚实句（不含具体数，避免把缺数说成事实）。
_UNPROBED = "未接入（取数口不可用，本席不猜）"


def _redact(text: str) -> str:
    """整段过一遍 ``redact_local_secrets``；渲染域拿不到时原样返回（不吞正文）。

    口径：命令正文对用户可见，盘符路径/密钥形态必须打码（铁律 3）。渲染域若不可用，
    宁可少一道脱敏也别把整段吞掉——上游各块本就各自脱敏，这里是纵深防御的一层。
    """
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )

        return redact_local_secrets(text)
    except Exception:  # noqa: BLE001 - 渲染域不可用只是少一层保险
        return text


def _role_names(message: Any) -> set[str]:
    """摄取层填好的角色名集合（小写去空）；判据复用唯一角色源，不另立。"""
    raw = getattr(message, "sender_roles", None) or []
    return {str(role).strip().lower() for role in raw if str(role).strip()}


def _is_admin(message: Any) -> bool:
    return bool(_role_names(message) & {name.lower() for name in _ADMIN_ROLE_NAMES})


def plugin_inventory_lines() -> list[str]:
    """本次进程实际装载的 NoneBot 插件名清单（现读，离线/未初始化诚实降级）。

    口径：``nonebot.get_loaded_plugins()`` 是运行期事实，不是清单副本——名字数不写死、
    每次现取。未初始化（单测/纯函数调用/离线）时返回诚实一句，绝不编一份「标准插件表」。
    """
    try:
        import nonebot

        loaded = list(nonebot.get_loaded_plugins())
    except Exception as error:  # noqa: BLE001 - nonebot 不可用=没这个面，不是报错
        return [f"（未探测到已装载插件：nonebot 不可用或尚未初始化，{type(error).__name__}）"]
    names = sorted(
        {
            str(getattr(plugin, "name", "") or getattr(plugin, "id", "") or "").strip()
            for plugin in loaded
        }
        - {""}
    )
    if not names:
        return ["（本次进程未探测到已装载插件；离线或未初始化环境属正常，不作数）"]
    # 「装载 N 个」是本次现算的运行期读数，非手抄常量（规则 10）。
    return [f"本次进程装载 {len(names)} 个 NoneBot 插件（现读，非清单副本）：" + "、".join(names)]


def self_knowledge_lines(
    *,
    now: datetime | None = None,
    timezone_name: str = "",
    system_now: datetime | None = None,
    root: Path | None = None,
    is_admin: bool = True,
    include_detail: bool = False,
) -> list[str]:
    """把「我现在是谁、几时、身处何历法、用什么框架、能做什么、最近改了什么」装配成行。

    参数：``now`` 可注入（测试钉死时刻）；缺省由取数口取系统 UTC。
    ``timezone_name`` 传 ``config.bot_timezone``；``system_now`` 传同一次取数的系统本地钟
    （台账 #6：它与 ``bot_timezone`` 是两把钟，跨日时报告要点名）。
    ``is_admin`` 决定功能清单可见面（管理类主题对普通用户既不列也不计数）。
    失败：任一子块异常只丢那一块并留一行诚实说明，其余照出（fail-open，不伪装完整）。
    """
    lines: list[str] = []

    # A) 时刻 + 四历法 + 叙述台账更新历史（全部转调 self_calendar，零第二套）。
    try:
        from plugins.bot_unified_runtime.domains.ops.self_calendar import (
            self_calendar_report,
        )

        lines += list(
            self_calendar_report(
                now,
                timezone_name=timezone_name,
                system_now=system_now,
                root=root,
                include_update_history=True,
                include_detail=include_detail,
            )
        )
    except Exception as error:  # 历法面炸了只丢这一节
        logger.debug("self_knowledge: 自我历法块异常", exc_info=True)
        lines.append(f"【自我历法】：{_UNPROBED}（{type(error).__name__}）")

    # B) 软件框架 / 适配器 / 插件版本 / 系统 / 构建 / git 提交历史。
    versions_note = ""
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character import temporal

        versions = list(temporal.system_readout_lines())
    except Exception as error:  # 版本面拿不到就少这一节，不猜版本号
        logger.debug("self_knowledge: 系统自述块异常", exc_info=True)
        versions = []
        versions_note = f"（{type(error).__name__}）"
    if versions:
        lines.append("【框架 / 适配器 / 插件版本 / 提交历史】")
        lines += versions
    else:
        lines.append(f"【框架 / 版本】：{_UNPROBED}{versions_note}")

    # C) 功能清单（按管理员可见性收口）。
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character import temporal

        lines += list(temporal.capability_index_lines(is_admin=is_admin))
    except Exception:  # 功能面取数口炸了整块缺席，不报手抄旧清单
        logger.debug("self_knowledge: 功能清单块异常", exc_info=True)

    # D) 本次进程实际装载的 NoneBot 插件清单（本模块唯一新增的读数面）。
    lines.append("【NoneBot 插件装载】")
    lines += plugin_inventory_lines()

    return [_redact(line) for line in lines if str(line).strip()]


def self_knowledge_text(
    *,
    now: datetime | None = None,
    timezone_name: str = "",
    system_now: datetime | None = None,
    root: Path | None = None,
    is_admin: bool = True,
    include_detail: bool = False,
) -> str:
    """``self_knowledge_lines`` 的整段文本形（命令正文用）。"""
    return "\n".join(
        self_knowledge_lines(
            now=now,
            timezone_name=timezone_name,
            system_now=system_now,
            root=root,
            is_admin=is_admin,
            include_detail=include_detail,
        )
    )


#: 整句精确触发词（去空白后逐字比，绝不部分命中——宽触发会把「今天农历是不是…」
#: 这类自然问句从聊天腿抢走；那些问题本就有【当前时间】分区喂给模型，交给聊天答）。
_SELF_INFO_EXACT_TRIGGERS: frozenset[str] = frozenset(
    {
        "自我认知",
        "我是什么版本",
        "你现在是什么版本",
        "你都会做什么",
        "你都能做什么",
        "最近改了什么",
        "今天农历",
        "现在几点",
    }
)


def is_self_info_command(text: str | None) -> bool:
    """自我认知命令判定谓词（供 base_router/__init__ 的 matcher 调，仿 host_state）。

    口径：只认显式命令形 ``/bot self`` 与整句精确触发词，绝不做子串模糊匹配——
    自然语言问句留给聊天腿（自我认知读数已注入【当前时间】/【系统自述】分区）。
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if lowered.startswith("/bot self"):
        return True
    compact = lowered.replace(" ", "").replace("　", "")
    if "自我认知" in compact:
        return True
    return any(compact == key.replace(" ", "").lower() for key in _SELF_INFO_EXACT_TRIGGERS)


def build_self_knowledge_capability(config: Any | None = None) -> Any:
    """命令形执行体：``build_x(config) -> (message, decision) -> CapabilityResult``。

    与 eat/reminder 等命令能力同形（命令形约定见 ``capability_registry``）。时刻现读、
    时区吃 ``config.bot_timezone``、管理员可见性吃 ``message.sender_roles``——三者都由
    运行期交来，本模块不在导入期取时刻（否则测试不稳定，同 self_calendar 口径）。
    正文由 :func:`self_knowledge_lines` 现装配并脱敏；全空时交回一句诚实说明，不假装成功。
    """
    timezone_name = str(getattr(config, "bot_timezone", "") or "").strip()

    def _run(message: Any, decision: Any = None) -> CapabilityResult:  # 中央 invoker 双参契约
        system_now: datetime | None = None
        try:
            from plugins.bot_unified_runtime.domains.ops.self_calendar import (
                system_clock_now,
            )

            system_now = system_clock_now()
        except Exception:  # noqa: BLE001 - 系统钟取不到只是少一把钟的对照，不影响主读数
            system_now = None
        lines = self_knowledge_lines(
            timezone_name=timezone_name,
            system_now=system_now,
            is_admin=_is_admin(message),
        )
        body = "\n".join(lines) or "这些读数这一轮没能凑齐，稍后再问一次，或让我说「/bot status」。"
        return CapabilityResult(
            request_id=getattr(message, "request_id", "") or new_request_id("self_info"),
            capability_id=SELF_KNOWLEDGE_CAPABILITY_ID,
            kind="text",
            title="自我认知",
            body=body,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["self_info", "goal18-10"],
        )

    return _run


__all__ = [
    "SELF_KNOWLEDGE_CAPABILITY_ID",
    "build_self_knowledge_capability",
    "is_self_info_command",
    "plugin_inventory_lines",
    "self_knowledge_lines",
    "self_knowledge_text",
]
