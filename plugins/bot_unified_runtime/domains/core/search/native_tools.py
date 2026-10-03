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

工具注册审批账（2026-10-02/03 安全与文档波补）：此前 MCP 腿是「schema 在册即白名单」
——``nonebot_plugin_mcpclient`` 交来什么工具名，模型可选面与执行面就照单全收，
服务端漂移/供应链污染能让**新工具名**静默进入执行面。:class:`ToolAdmissionLedger`
补 fail-closed 审批账：内置九枚以源内显式名册为账（存量兼容、零落盘放行）；
外来工具名首见 ⇒ 落 pending 审计行并拒执行，管理员经 :meth:`ToolAdmissionLedger.approve`
/:meth:`~ToolAdmissionLedger.deny` 显式登记后才放行/拉黑。账本＝JSONL append-only
（``consent.JsonSafetyLedger`` 同族、选轻），落点由装配期构造时给定；本模块自身
零接线 ⇒ 零行为变化，接线说明见波次交付报告。
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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


# ---------------------------------------------------------------------------
# 工具注册审批账（席7 安全与文档波，2026-10-03）：现状「schema 在册即白名单」——
# 任何新工具名只要进了 schema 就可执行，缺管理员审批环节。本账补上：
# 新工具名**首次出现** → 落 pending 审计行 + fail-closed 拒执行，直到管理员批准；
# ``NATIVE_TOOL_ROSTER`` 在册九枚默认视为已批准（存量兼容：零落盘、零行为变化）。
# 命令面（/bot 工具批准|拒绝 <工具名>）归 admin 域（不实现命令本体），
# 话术常量 ``TOOL_ADMIT_COMMAND_HINT`` + ``pending_names()`` 就是接线面。
# 账本形态照 ``consent.JsonSafetyLedger``：JSONL append-only、同工具名后写覆盖前写、
# 带锁；「谁批的、批的什么」不许被后来的重写抹掉。
# ---------------------------------------------------------------------------
TOOL_ADMIT_STATUS_PENDING = "pending"
TOOL_ADMIT_STATUS_APPROVED = "approved"
TOOL_ADMIT_STATUS_DENIED = "denied"

#: 管理员命令建议（接线方在 pending 回执里附这句；命令本体归 admin 域）。
TOOL_ADMIT_COMMAND_HINT = (
    "新工具要先有管理员点头我才用：批准「/bot 工具批准 <工具名>」、"
    "拒绝「/bot 工具拒绝 <工具名>」。没批之前我只记账、不执行。"
)

#: 审计标签常量（接线方落到 audit_tags；「不在账的工具被拒了」的唯一代号）。
TOOL_ADMIT_AUDIT_TAG = "tool_not_in_admit_ledger"


class ToolAdmitWriteError(RuntimeError):
    """审批账写不进去（目录建不了/盘写失败）——批准面必须原样抛（批准必须落得住账）。"""


@dataclass(frozen=True)
class ToolAdmissionRow:
    """一枚审批审计行（append-only 账上的一格；同工具名后写覆盖前写）。"""

    tool_name: str
    status: str  # pending / approved / denied
    source: str
    at: str  # ISO 时刻（带时区）
    actor: str = ""  # 批准/拒绝人（pending 行为空）
    note: str = ""


def _default_admit_clock() -> datetime:
    return datetime.now(timezone.utc)


class ToolAdmissionLedger:
    """JSONL append-only 工具审批账（``consent.JsonSafetyLedger`` 同族形态）。

    - ``admit``：派发腿的唯一准入口。在册工具（``grandfathered``，缺省＝
      ``NATIVE_TOOL_ROSTER`` 全部工具名）直接放行且**零落盘**；其余查账：
      approved 放行、denied 拒、无账/pending ⇒ 先落 pending 审计行再拒
      （同工具已有 pending 行不重复落账，防调度循环刷爆账本）。
    - fail-closed：账本读不了/写不了 ⇒ admit 一律 pending 拒执行并带 note，
      绝不因账本缺席放行；``approve``/``deny`` 写失败原样抛
      :class:`ToolAdmitWriteError`（批准必须落得住账）。
    - 畸形工具名（空/超长）⇒ denied（不落账——没有可审计的「工具」）。
    """

    backend_name = "json"

    def __init__(
        self,
        directory: str | Path,
        *,
        basename: str = "tool_admit",
        grandfathered: frozenset[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        text = str(directory or "").strip()
        if not text:
            raise ValueError("工具审批账需要显式目录")
        self.directory = Path(text).expanduser()
        self.ledger_path = self.directory / f"{basename}_ledger.jsonl"
        self._grandfathered = (
            frozenset(spec.tool_name for spec in NATIVE_TOOL_ROSTER.values())
            if grandfathered is None
            else frozenset(grandfathered)
        )
        self._clock = clock or _default_admit_clock
        self._lock = threading.Lock()

    # ---- 账体 ----

    def _append(self, row: ToolAdmissionRow) -> None:
        line = json.dumps(
            {
                "tool_name": row.tool_name,
                "status": row.status,
                "source": row.source,
                "at": row.at,
                "actor": row.actor,
                "note": row.note,
            },
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n"
        try:
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(self.ledger_path, "a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError as exc:
            raise ToolAdmitWriteError(f"写 {self.ledger_path.name} 失败：{type(exc).__name__}: {exc}") from exc

    def _effective_status(self, tool_name: str) -> ToolAdmissionRow | None:
        """读账：同工具名最后一行说了算（append-only 的投影口）。读挂了返回 None。"""
        try:
            with self._lock, open(self.ledger_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return None
        row: ToolAdmissionRow | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue  # 烂行跳过（append-only 账不因半行报废）
            if not isinstance(payload, dict) or payload.get("tool_name") != tool_name:
                continue
            row = ToolAdmissionRow(
                tool_name=tool_name,
                status=str(payload.get("status") or TOOL_ADMIT_STATUS_PENDING),
                source=str(payload.get("source") or ""),
                at=str(payload.get("at") or ""),
                actor=str(payload.get("actor") or ""),
                note=str(payload.get("note") or ""),
            )
        return row

    # ---- 准入面 ----

    def admit(self, tool_name: str, *, source: str = "mcp") -> ToolAdmissionRow:
        """派发前的唯一准入口：approved 放行，其余一律先记账再拒（fail-closed）。"""
        name = str(tool_name or "").strip()
        if not name or len(name) > 128:
            return ToolAdmissionRow(
                tool_name=name[:128],
                status=TOOL_ADMIT_STATUS_DENIED,
                source=source,
                at=self._clock().isoformat(),
                note="畸形工具名（空或超长），不落账、不放行",
            )
        if name in self._grandfathered:
            return ToolAdmissionRow(
                tool_name=name,
                status=TOOL_ADMIT_STATUS_APPROVED,
                source=source,
                at=self._clock().isoformat(),
                note="内置在册工具（存量兼容，默认已批准）",
            )
        current = self._effective_status(name)
        if current is not None and current.status == TOOL_ADMIT_STATUS_APPROVED:
            return current
        if current is not None and current.status == TOOL_ADMIT_STATUS_DENIED:
            return current  # 已被拒绝：后写覆盖前写，拒绝是终态
        if current is not None and current.status == TOOL_ADMIT_STATUS_PENDING:
            return current  # 已在待批，不重复落账（调度循环防刷屏）
        row = ToolAdmissionRow(
            tool_name=name,
            status=TOOL_ADMIT_STATUS_PENDING,
            source=source,
            at=self._clock().isoformat(),
            note="新工具首次出现，待管理员批准；批之前拒执行",
        )
        try:
            self._append(row)
        except ToolAdmitWriteError as exc:
            return ToolAdmissionRow(
                tool_name=name,
                status=TOOL_ADMIT_STATUS_PENDING,
                source=source,
                at=self._clock().isoformat(),
                note=f"审计账写不下去，fail-closed 拒执行：{exc}",
            )
        return row

    def approve(self, tool_name: str, *, actor: str, note: str = "") -> ToolAdmissionRow:
        """管理员批准（命令面唯一入口；写失败原样抛——批准必须落得住账）。"""
        return self._record(
            tool_name, TOOL_ADMIT_STATUS_APPROVED, actor=actor, note=note
        )

    def deny(self, tool_name: str, *, actor: str, note: str = "") -> ToolAdmissionRow:
        """管理员拒绝；拒绝后 ``admit`` 恒 denied（后写覆盖前写）。"""
        return self._record(tool_name, TOOL_ADMIT_STATUS_DENIED, actor=actor, note=note)

    def _record(self, tool_name: str, status: str, *, actor: str, note: str) -> ToolAdmissionRow:
        name = str(tool_name or "").strip()
        row = ToolAdmissionRow(
            tool_name=name,
            status=status,
            source="admin",
            at=self._clock().isoformat(),
            actor=str(actor or "").strip(),
            note=note,
        )
        self._append(row)
        return row

    def pending_names(self) -> tuple[str, ...]:
        """当前 pending 的工具名（admin 命令面「待批清单」取数口；读挂了给空表）。"""
        try:
            with self._lock, open(self.ledger_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return ()
        latest: dict[str, str] = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("tool_name"):
                latest[str(payload["tool_name"])] = str(payload.get("status") or "")
        return tuple(sorted(n for n, s in latest.items() if s == TOOL_ADMIT_STATUS_PENDING))

    def status_of(self, tool_name: str) -> ToolAdmissionRow | None:
        """查一枚工具的现行审批态（只读；无账返回 None）。"""
        name = str(tool_name or "").strip()
        if name in self._grandfathered:
            return ToolAdmissionRow(
                tool_name=name,
                status=TOOL_ADMIT_STATUS_APPROVED,
                source="roster",
                at="",
                note="内置在册工具（存量兼容，默认已批准）",
            )
        return self._effective_status(name)


def filter_mcp_tools_schema(
    tools: Iterable[object],
    ledger: ToolAdmissionLedger,
) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
    """MCP schema 面的统一过滤口（``chat.py::_mcp_tools_schema`` 的接线挂点）。

    逐枚过 :meth:`ToolAdmissionLedger.admit`：approved 才进模型可选面；
    pending/denied/畸形条目一律拒之门外并回审计标签。返回
    ``(放行 schema 列表, 被拒工具名元组, 审计标签元组)``——调用方拿第一列
    替换原 schema、第三列落 audit_tags（禁在调用点自判，第二真身）。
    """
    admitted: list[dict[str, Any]] = []
    refused_names: list[str] = []
    tags: list[str] = []
    for item in tools or ():
        if not isinstance(item, Mapping):
            refused_names.append("?")
            tags.append(TOOL_ADMIT_AUDIT_TAG)
            continue
        fn = item.get("function")
        fn = fn if isinstance(fn, Mapping) else item
        name = str(fn.get("name") or "").strip()
        row = ledger.admit(name)
        if row.status == TOOL_ADMIT_STATUS_APPROVED:
            admitted.append(dict(item))
        else:
            refused_names.append(name or "?")
            tags.append(TOOL_ADMIT_AUDIT_TAG)
    return admitted, tuple(refused_names), tuple(tags)


__all__ = [
    "NATIVE_TOOLS_CONFIG_KEY",
    "NATIVE_TOOL_ROSTER",
    "TOOL_ADMIT_AUDIT_TAG",
    "TOOL_ADMIT_COMMAND_HINT",
    "TOOL_ADMIT_STATUS_APPROVED",
    "TOOL_ADMIT_STATUS_DENIED",
    "TOOL_ADMIT_STATUS_PENDING",
    "WRITE_OR_PRIVILEGED_DENYLIST",
    "NativeToolSpec",
    "ToolAdmissionLedger",
    "ToolAdmissionRow",
    "ToolAdmitWriteError",
    "build_native_tool_schemas",
    "filter_mcp_tools_schema",
    "guard_tool_result_text",
    "native_tool_for_name",
    "native_tools_enabled",
    "roster_capability_ids",
    "roster_violations",
]
