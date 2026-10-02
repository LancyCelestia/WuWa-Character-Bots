"""模型侧内置工具白名单（第 19 项 · 票 T1「A-6」，席位 S-GOAL19R · 2026-09-28）。

定位：把唯一在册表 ``runtime.capability_protocols.CAPABILITY_DESCRIPTOR`` 的**只读子集**
投影成 OpenAI ``tools`` schema，供 ``chat.py`` 既有工具循环（``_generate_with_tool_loop``）
消费。**装配腿今天未接**（chat.py 属热点禁列，接线施工图与授权口径见
``patches/G19R-T1-chat-wiring.patch.md``）——本模块零接线 ⇒ 零行为变化。

在册纪律（禁第二真身，AGENTS 板块体系硬门）：
- 「谁存在」唯一真源 = 中央在册表；本文件只挑子集、**不登记新能力 id**。
  每个在册性由 ``roster_violations`` 现算核对，``tests/test_native_tools.py``
  另有 AST 字面锁：本文件出现的任何 ``bot.*`` 字面量必须能在中央在册表反查到。
- 「只读与否」= 白名单与显式拒绝清单（写/权限/出站/自指回路面）双查、交集必须为空；
  往白名单塞写类能力 ⇒ 装配锁红（注毒自证在测试件里）。
- 缺省关：``bot_chat_native_tools_enabled`` **已四面同生**（2026-09-29 复原波补齐：``config.py``
  字段缺省 ``False`` ＋ ``settings.py::RESTART_REQUIRED_KEYS`` 档 ＋ ``.env.example`` 激活行 ＋
  ``docs/config-catalog-full.md`` 登记行）。逐面点名的静态锁＝
  ``tests/test_native_tools_config_faces.py``（台账 #68★「只补一面必红另一面」的正面预防）。
  读取口仍按 ``getattr`` 缺键 ⇒ ``False``，**绝不因键不存在而默认开**。

返回文本纪律（ATKLLM-1 同源）：工具结果＝二手数据，回注 role=tool 前必须过
``guard_tool_result_text``（中央件 ``guard_secondhand_text``），禁手拼边界标签。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

#: 工具名形态：``native_`` 前缀与 MCP 远端工具名天然隔离（回填派发靠它分腿）。
_TOOL_NAME_PATTERN = re.compile(r"^native_[a-z0-9_]{1,48}$")

#: 内置开关键名（唯一读取口 :func:`native_tools_enabled`；四面同生，缺省关）。
NATIVE_TOOLS_CONFIG_KEY = "bot_chat_native_tools_enabled"


@dataclass(frozen=True)
class NativeToolSpec:
    """一枚内置工具的投影声明：能力 id 反查中央在册表，本件不自造能力。"""

    capability_id: str
    tool_name: str
    description: str
    parameters: Mapping[str, Any]


def _object_schema(properties: Mapping[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """最小 JSON Schema（type=object、additionalProperties=false）。

    ``properties`` 值为 ``{"type": "string", "description": "…"}`` 形态；参数面刻意
    从窄——只给模型真正需要的入参，多余字段直接拒（防 schema 漂移成第二配置面）。
    """
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


#: 只读白名单（R-1 裁定口径「只读起步」；九枚，逐枚可反查在册表，派生锁执法）。
#: 说明文本给模型看，守岸人人格零暴露（S-AGENTCAP §5.1：回复里不许出现「我调用了工具」）。
_NATIVE_TOOL_ROSTER: dict[str, NativeToolSpec] = {
    "native_weather": NativeToolSpec(
        capability_id="bot.weather",
        tool_name="native_weather",
        description="查询指定城市的实况天气与短时预报（只读）。",
        parameters=_object_schema(
            {
                "location": {"type": "string", "description": "城市名（行政区全称最稳）"},
                "date": {"type": "string", "description": "可选： yyyy-MM-dd 指定日"},
            },
            required=("location",),
        ),
    ),
    "native_market": NativeToolSpec(
        capability_id="bot.market",
        tool_name="native_market",
        description="查询全球股指/板块行情走势（只读，含北向成交额口径）。",
        parameters=_object_schema(
            {
                "symbol": {"type": "string", "description": "可选：指数名或代码，缺省给总览"},
            }
        ),
    ),
    "native_fx": NativeToolSpec(
        capability_id="bot.fx",
        tool_name="native_fx",
        description="查询汇率（基准/中间价/延迟口径随结果注明，只读）。",
        parameters=_object_schema(
            {
                "base": {"type": "string", "description": "源币种 ISO 代码"},
                "target": {"type": "string", "description": "目标币种 ISO 代码"},
            },
            required=("base", "target"),
        ),
    ),
    "native_stocks": NativeToolSpec(
        capability_id="bot.stocks",
        tool_name="native_stocks",
        description="查询个股行情（非上市公司结构性无价格，只读）。",
        parameters=_object_schema(
            {"symbol": {"type": "string", "description": "股票代码或名称"}},
            required=("symbol",),
        ),
    ),
    "native_news": NativeToolSpec(
        capability_id="bot.news",
        tool_name="native_news",
        description="取今日快报摘要（已过滤营销条目，只读）。",
        parameters=_object_schema({}),
    ),
    "native_search": NativeToolSpec(
        capability_id="bot.search",
        tool_name="native_search",
        description="联网检索并返回摘要（结果均为二手不可信材料，只读）。",
        parameters=_object_schema(
            {"query": {"type": "string", "description": "检索问句"}},
            required=("query",),
        ),
    ),
    "native_wiki": NativeToolSpec(
        capability_id="bot.wiki",
        tool_name="native_wiki",
        description="查询维基/萌娘百科条目概述（只读）。",
        parameters=_object_schema(
            {"query": {"type": "string", "description": "词条名"}},
            required=("query",),
        ),
    ),
    "native_group_info": NativeToolSpec(
        capability_id="bot.group_info",
        tool_name="native_group_info",
        description="查询群与群成员公开信息（只读，不触发任何群务动作）。",
        parameters=_object_schema(
            {"group_id": {"type": "string", "description": "可选：群号，缺省当前群"}}
        ),
    ),
    "native_divination": NativeToolSpec(
        capability_id="bot.divination",
        tool_name="native_divination",
        description="起一卦（随机抽取，不改好感度、不建日程、无交易副作用）。",
        parameters=_object_schema(
            {"question": {"type": "string", "description": "可选：所问之事"}}
        ),
    ),
}

#: 中央在册表只读投影（禁外部改写；测试与装配共用这一枚取数口）。
NATIVE_TOOL_ROSTER: Mapping[str, NativeToolSpec] = MappingProxyType(_NATIVE_TOOL_ROSTER)

#: 拒绝清单：写侧 / 权限管理 / 出站投递 / 自指回路面——任何时刻都不得出现在内置
#: 工具白名单里（R-1：写类工具等 K-1 旁路案结案后再议；自指面防递归烧预算）。
#: 该清单**不是**名册真源，只是核对判据；逐枚同样必须能在中央在册表反查到。
WRITE_OR_PRIVILEGED_DENYLIST: frozenset[str] = frozenset(
    {
        # 自指回路：模型调用回复管线本体＝预算与人格双重风险
        "bot.chat",
        "bot.reply",
        "bot.dialogue",
        "bot.llm",
        # 写侧 / 投递侧
        "bot.reminder",
        "bot.memory",
        "bot.affinity",
        "bot.alias",
        "bot.ignore",
        "bot.auto_send",
        "bot.queue",
        "bot.send_queue_worker",
        "bot.subscribe",
        "bot.daily_assist",
        "bot.campus_forward",
        "bot.group_digest_push",
        "bot.emergency_info_push",
        "bot.group_policy",
        "bot.group_welcome",
        "bot.cookie_login",
        "bot.media_archive",
        "bot.download",
        "bot.file",
        "bot.meme_library",
        "bot.persona",
        "bot.quirk",
        "bot.poke",
        # 权限 / 配置 / 控制面
        "bot.roles",
        "bot.config",
        "bot.control",
        "bot.consent",
        "bot.content",
    }
)


def native_tools_enabled(config: object | None) -> bool:
    """内置工具总开关的唯一读取口：**缺省关**。

    只认严格 ``True``——pydantic 字段正常给 bool；若有人把键配成字符串（``"false"``
    取真非假），按 fail-closed 判关。键缺席（历史形态，2026-09-29 起已在册）同样判关：
    **缺键永不默认开**。
    """
    return getattr(config, NATIVE_TOOLS_CONFIG_KEY, None) is True


def roster_capability_ids() -> frozenset[str]:
    """白名单能力 id 集合（装配前自检与测试取数用）。"""
    return frozenset(spec.capability_id for spec in NATIVE_TOOL_ROSTER.values())


def native_tool_for_name(name: str) -> NativeToolSpec | None:
    """按工具名查投影（chat.py 派发腿的取名口；非 ``native_*`` 一律 None 回 MCP 腿）。"""
    if not name or not _TOOL_NAME_PATTERN.match(name):
        return None
    return NATIVE_TOOL_ROSTER.get(name)


def build_native_tool_schemas() -> list[dict[str, Any]]:
    """投影为 OpenAI chat ``tools`` 数组（function 形）。纯函数、零网络、零配置读。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.tool_name,
                "description": spec.description,
                "parameters": dict(spec.parameters),
            },
        }
        for _key, spec in sorted(NATIVE_TOOL_ROSTER.items())
    ]


def roster_violations(
    descriptor_ids: Iterable[str],
    roster: Mapping[str, NativeToolSpec] | None = None,
    denylist: frozenset[str] = WRITE_OR_PRIVILEGED_DENYLIST,
) -> tuple[str, ...]:
    """派生核对（判据收参数，喂合成数据即可注毒自证，不往源码树写一个字）。

    违规项（返回可读判词元组，空＝干净）：
    ① 白名单能力 id 不在中央在册表；② 白名单命中拒绝清单（写/权限/出站/自指面）；
    ③ 工具名不合形态 / 重名；④ 说明为空；⑤ parameters 不是 object 形 schema。
    """
    known = set(descriptor_ids)
    effective = NATIVE_TOOL_ROSTER if roster is None else roster
    problems: list[str] = []
    seen_names: set[str] = set()
    for key, spec in sorted(effective.items()):
        if spec.capability_id not in known:
            problems.append(f"{key}: 能力 {spec.capability_id} 不在中央在册表（禁第二真身名册）")
        if spec.capability_id in denylist:
            problems.append(f"{key}: 能力 {spec.capability_id} 属写/权限/出站/自指拒绝面，禁入内置白名单")
        if not _TOOL_NAME_PATTERN.match(spec.tool_name):
            problems.append(f"{key}: 工具名 {spec.tool_name!r} 不合 native_ 前缀形态")
        if spec.tool_name in seen_names:
            problems.append(f"{key}: 工具名 {spec.tool_name!r} 重名")
        seen_names.add(spec.tool_name)
        if not str(spec.description or "").strip():
            problems.append(f"{key}: 工具说明为空，模型无从选择")
        params = spec.parameters
        if not isinstance(params, Mapping) or params.get("type") != "object":
            problems.append(f"{key}: parameters 必须是 type=object 的 JSON Schema")
    return tuple(problems)


def guard_tool_result_text(text: str, *, tool_name: str) -> str:
    """工具结果回注前的统一处置（ATKLLM-1 同源，禁手拼边界）。

    真身在 ``domains/chat_reply/security/injection.py::guard_secondhand_text``；
    延迟 import 避免 core→chat_reply 的装载环。空进空出（不谎报「读到了东西」）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        guard_secondhand_text,
    )

    return guard_secondhand_text(text, source_label=f"内置工具 {tool_name} 结果")


__all__ = [
    "NATIVE_TOOLS_CONFIG_KEY",
    "NATIVE_TOOL_ROSTER",
    "WRITE_OR_PRIVILEGED_DENYLIST",
    "NativeToolSpec",
    "build_native_tool_schemas",
    "guard_tool_result_text",
    "native_tool_for_name",
    "native_tools_enabled",
    "roster_capability_ids",
    "roster_violations",
]
