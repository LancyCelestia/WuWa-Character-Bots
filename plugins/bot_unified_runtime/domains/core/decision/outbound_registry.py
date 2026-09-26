"""V2.1 S6 出站收编注册表层（A16）：Transport 固定映射注册表 + 入口接管登记表。

合同来源：
- 主规范 §10：「Transport固定映射平台方法，不接原始API名」「启动门拒绝
  未登记入口/出站绕行」。
- A1 冻结清单（docs/design/v21-s0-inventory.md §2）：50 matcher / 12 调度族 /
  62 控制面路由 / 直发出站嫌疑点（含取证坐标）——本模块是其结构化数据形态。
- 风险 5（docs/design/v21-risk-red-report.md）：直连坐标复核来源。

诚实边界：
- Transport 条目全部为**占位**（``bound_handler=None``，status="placeholder"）；
  真实 sender 绑定经 ``bind_handler`` 由接线席位执行。平台方法名只收录有
  出处的字面量（evidence 字段给出坐标或标准来源），绝不拼接合成。
- 接管登记表是 A1 冻结快照的结构化投影，不是实时状态；行号随工作树漂移，
  以 A1 冻结时刻为准（A1 原文已声明）。
- v1.py 路由明细 A1 只冻结到分组粒度（28 条中 26 条可从分组清单枚举），
  登记 group 级条目并如实记录 members 覆盖数，不臆造缺额路由名。
"""

from __future__ import annotations

# 坐标跟随注记（2026-09-28 S-SEAM-ROOT 批，非新注册）：本批只跟随根装配文件顶漂
# 重锚既有 MatcherEntry 的 __init__.py 行号，条目语义零改动。漂移源：根缝
# _run_capability_through_pipeline 签名扩展（+4，2543 起）与其下 image_search、
# content、music、today_history(交互)、group_info、host_state、consent、
# media_archive、meme_library 九处第二通路收编的行数收缩；跟随方式为按被锚行
# 原文内容重定位（脚本 seat-coord-follow.py + 7 枚同名冲突条目人工核对根行）。
# campus_record_matcher 等 5423 以上坐标不受本批影响（所有收缩均在其后）。

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "DirectSendCategory",
    "DirectSendEntry",
    "EntryKind",
    "MatcherEntry",
    "MigrationStatus",
    "RouteGroupEntry",
    "SchedulerEntry",
    "TakeoverChecklist",
    "TakeoverRegistry",
    "TransportChannel",
    "TransportEntry",
    "TransportPlatform",
    "TransportRegistry",
    "UnregisteredTransportError",
    "build_default_takeover_registry",
    "build_default_transport_registry",
]


# ---------------------------------------------------------------------------
# Transport 固定映射注册表
# ---------------------------------------------------------------------------


class TransportPlatform(str, Enum):
    QQ = "qq"
    TELEGRAM = "telegram"
    MAIL = "mail"
    CONSOLE = "console"


class TransportChannel(str, Enum):
    SEND_MESSAGE = "send_message"
    SEND_FILE = "send_file"
    SEND_MAIL = "send_mail"
    STICKER = "sticker"
    REACTION = "reaction"
    POKE = "poke"
    EDIT = "edit"
    DELETE = "delete"


@dataclass(frozen=True)
class TransportEntry:
    """一条固定映射：平台 × 通道 → 显式登记的平台方法名（字面量，禁拼接）。

    ``methods`` 按会话形态给出方法名（QQ 私聊/群聊方法名不同）；单方法通道
    用 {"*": 名字}。``evidence`` 记录方法名出处（file:line 坐标或标准来源），
    无出处的名字不收录。``handler`` 由 ``bind_handler`` 运行时绑定（真实
    sender 通道本体），占位阶段恒为 None。
    """

    platform: TransportPlatform
    channel: TransportChannel
    methods: Mapping[str, str]
    description: str
    evidence: str
    status: str = "placeholder"  # placeholder / bound
    handler: Callable[[Any], Any] | None = None

    def platform_method_for(self, session_type: str = "*") -> str:
        """查显式登记的方法名；未登记组合显式报错（绝不合成 API 名）。"""
        if session_type in self.methods:
            return self.methods[session_type]
        if "*" in self.methods:
            return self.methods["*"]
        raise UnregisteredTransportError(
            f"no registered platform method for {self.platform.value}/"
            f"{self.channel.value} session_type={session_type!r} "
            "(fixed mapping only; synthesizing API names is forbidden)"
        )

    def with_handler(self, handler: Callable[[Any], Any]) -> TransportEntry:
        return TransportEntry(
            platform=self.platform,
            channel=self.channel,
            methods=dict(self.methods),
            description=self.description,
            evidence=self.evidence,
            status="bound",
            handler=handler,
        )


class UnregisteredTransportError(Exception):
    """未注册的平台方法/通道组合：显式错误（§10 启动门拒绝出站绕行同源）。"""


class TransportRegistry:
    """固定映射注册表：resolve 只回登记条目，未注册即显式错误。"""

    def __init__(self) -> None:
        self._entries: dict[tuple[TransportPlatform, TransportChannel], TransportEntry] = {}

    def register(self, entry: TransportEntry, *, replace: bool = False) -> None:
        key = (entry.platform, entry.channel)
        if key in self._entries and not replace:
            raise ValueError(
                f"transport already registered: {entry.platform.value}/{entry.channel.value}"
            )
        self._entries[key] = entry

    def bind_handler(
        self,
        platform: TransportPlatform,
        channel: TransportChannel,
        handler: Callable[[Any], Any],
    ) -> TransportEntry:
        """真实 sender 绑定接口：绑定后条目 status=bound（条目不可变，替换实例）。"""
        entry = self.resolve(platform, channel)
        bound = entry.with_handler(handler)
        self._entries[(platform, channel)] = bound
        return bound

    def resolve(
        self,
        platform: TransportPlatform,
        channel: TransportChannel,
    ) -> TransportEntry:
        entry = self._entries.get((platform, channel))
        if entry is None:
            raise UnregisteredTransportError(
                f"unregistered transport: platform={platform.value} channel={channel.value}"
            )
        return entry

    def entries(self) -> list[TransportEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


def build_default_transport_registry() -> TransportRegistry:
    """占位登记表：QQ/TG/Mail/sticker/reaction/poke/edit/delete 通道全占位。

    方法名出处（evidence）全部来自 A1 冻结清单 §2.4 / 风险 5 取证坐标，
    或 OneBot v11 / Telegram Bot API 标准方法面；真实 sender 绑定留接口。
    Telegram POKE 有意不注册（平台无此通道）——resolve 显式报错即契约行为。
    """
    reg = TransportRegistry()
    placeholder = "placeholder"

    def entry(
        platform: TransportPlatform,
        channel: TransportChannel,
        methods: Mapping[str, str],
        description: str,
        evidence: str,
    ) -> TransportEntry:
        return TransportEntry(
            platform=platform,
            channel=channel,
            methods=dict(methods),
            description=description,
            evidence=evidence,
            status=placeholder,
        )

    # QQ（OneBot v11 / SnowLuma）
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.SEND_MESSAGE,
        {"private": "send_private_msg", "group": "send_group_msg"},
        "QQ 文本/段消息发送（SendQueue worker 通道本体）",
        "v21-s0-inventory §2.4（sender/onebot.py:444,449,469,477 通道本体；"
        "原四处待收编绕行点已由 S0-ROOT-c 收编为 *_via_queue 门开分支（门缺省 "
        "False=门关直连等价；REG-REFRESH 2026-09-19 复核门关分支现坐标 "
        "4440-4444/5378-5382/5730-5740/5526-5538，行号会漂以符号 grep 复核））",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.SEND_FILE,
        {"private": "upload_private_file", "group": "upload_group_file"},
        "QQ 文件出站（file_gateway Phase-1 deliver 通道）",
        "v21-s0-inventory §2.4（domains/transport/sender/file_gateway.py:578-634 "
        "_deliver_onebot=通道本体；reorg 前 shim 旧坐标的 PENDING_RULING 已依 "
        "DIRECT-PLAN §二④ 改判 CHANNEL_BODY；v21r4-b S0-COLLECT 2026-09-18）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.DELETE,
        {"*": "delete_msg"},
        "QQ 撤回（dirty guard 等 by-design 撤回面）",
        "v21-s0-inventory §2.4（__init__.py delete_msg；REG-REFRESH 2026-09-19 复核"
        "现坐标 :4978，原登记 :4569 已漂移）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.POKE,
        {"group": "group_poke", "private": "friend_poke"},
        "QQ 戳一戳（回戳 v2 by-design 副作用；L34 已收编=executor 经本映射解析方法名）",
        "v21-risk-red-report 风险5（原直连 :4745-4746/:4751 已随收编消失；现执行面="
        "control_plane/dispatcher.py:162-220，装配 __init__.py:5683-5750；"
        "REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.REACTION,
        {"*": "set_msg_emoji_like"},
        "QQ 贴表情（贴纸回应 v2 by-design 副作用；L35 已收编=统一出站面经本映射）",
        "v21-risk-red-report 风险5（真身 domains/meme/reactions/engine.py:754-782 "
        "react_to_message→executor；runtime/ 旧路径为 shim；REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.EDIT,
        {"group": "edit_msg", "private": "edit_msg"},
        "QQ 消息编辑（NapCat 扩展方法；OneBot v11 标准无编辑面）",
        "NapCat 扩展 API 占位——OneBot v11 标准无此方法，bind 前必须对生产 "
        "NapCat 实测验证（A1/风险5 清单未取证，如实标注待验证）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.STICKER,
        {"private": "send_private_msg", "group": "send_group_msg"},
        "QQ 表情包/贴纸发送（meme 图走消息通道，方法同 SEND_MESSAGE）",
        "v21-s0-inventory §2.4（sender/onebot.py 通道本体）",
    ))

    # Telegram（Bot API 标准方法面；set_message_reaction 坐标已取证）
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.SEND_MESSAGE,
        {"*": "sendMessage"},
        "TG 消息发送（不设 Markdown parse_mode，§10 纯文本契约）",
        "Telegram Bot API 标准（发送通道本体）",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.EDIT,
        {"*": "editMessageText"},
        "TG 消息编辑",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.DELETE,
        {"*": "deleteMessage"},
        "TG 消息撤回",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.REACTION,
        {"*": "set_message_reaction"},
        "TG 贴 reaction（docstring 自述未接线触发点；出站面已统一经 executor）",
        "v21-risk-red-report 风险5（真身 domains/meme/reactions/engine.py:785-813 "
        "react_telegram_message；REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.SEND_FILE,
        {"*": "sendDocument"},
        "TG 文件出站",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.STICKER,
        {"*": "sendSticker"},
        "TG 贴纸发送",
        "Telegram Bot API 标准",
    ))
    # TG POKE：有意不注册（平台无 poke 通道）→ resolve 显式 UnregisteredTransportError。

    # Mail
    reg.register(entry(
        TransportPlatform.MAIL, TransportChannel.SEND_MAIL,
        {"*": "smtp_send"},
        "邮件发送（mail 适配器通道本体）",
        "v21-s0-inventory §2.4（sender/onebot.py 合法通道族；mail 适配器 SMTP 出站）",
    ))

    # Console
    reg.register(entry(
        TransportPlatform.CONSOLE, TransportChannel.SEND_MESSAGE,
        {"*": "console_print"},
        "控制台适配器出站（开发/验收用）",
        "适配器面（console 适配器，无平台 API 名；占位名仅为注册表占位）",
    ))
    return reg


# ---------------------------------------------------------------------------
# 入口接管登记表（A1 冻结清单的结构化投影）
# ---------------------------------------------------------------------------


class EntryKind(str, Enum):
    MATCHER = "matcher"
    SCHEDULER = "scheduler"
    CONTROL_ROUTE = "control_route"


class MigrationStatus(str, Enum):
    LEGACY = "legacy"  # 旧入口仍在岗
    TAKEOVER_READY = "takeover_ready"  # 已按 checklist 备妥，待切换
    TAKEN_OVER = "taken_over"  # 已收编（本轮无）


@dataclass(frozen=True)
class TakeoverChecklist:
    """接管前三问（接线席位逐项落答案后才能置 takeover_ready）。

    - idempotency_key_source：幂等键来源（平台+事件id+入口kind 的具体取值点）
    - feature_gate：FeatureGate id（或 none=无开关，须给理由）
    - trace_point：Trace 贯通点（事件入口/出站回执的 trace 注入位置）
    """

    idempotency_key_source: str = "todo"
    feature_gate: str = "todo"
    trace_point: str = "todo"

    def is_complete(self) -> bool:
        return all(
            value != "todo" and bool(value.strip())
            for value in (self.idempotency_key_source, self.feature_gate, self.trace_point)
        )


@dataclass(frozen=True)
class MatcherEntry:
    name: str
    location: str  # __init__.py:4398 形态（A1 冻结坐标）
    matcher_type: str  # on_message / on_notice / on_command
    priority: int | None  # A1 未冻结 priority 的如实为 None
    route_kind_hint: str  # 功能名提示；精确 RouteKind 以 base_router ROUTE_RULES 为准
    status: MigrationStatus = MigrationStatus.LEGACY
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)
    note: str = ""  # 接线席收编指定/坐标审计留痕（与 Scheduler/RouteGroup 条目同构）


@dataclass(frozen=True)
class SchedulerEntry:
    family: str
    register_location: str
    add_job_locations: tuple[str, ...]
    status: MigrationStatus = MigrationStatus.LEGACY
    note: str = ""
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)


@dataclass(frozen=True)
class RouteGroupEntry:
    """控制面路由组：A1 以文件分组冻结（62 条）；v1.py 明细仅冻结到分组。"""

    module: str  # control_plane/api/v1.py
    prefix: str
    route_count: int  # A1 冻结的组内路由数（计数为准）
    members: tuple[str, ...]  # 可从 A1 分组清单枚举的明细；不臆造缺额
    status: MigrationStatus = MigrationStatus.LEGACY
    note: str = ""
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)


class DirectSendCategory(str, Enum):
    BYPASS_SUSPECT = "bypass_suspect"  # 绕 SendQueue 嫌疑（首要核对）
    ABSORBED = "absorbed"  # 已收编：旧直发分支已从生产删除，投递只剩统一管线/队列一条路
    BY_DESIGN = "by_design"  # 设计上旁路（poke/贴纸/撤回等，待收编裁决）
    CHANNEL_BODY = "channel_body"  # 合法通道本体（非绕行）
    PENDING_RULING = "pending_ruling"  # 待裁决（file_gateway 等）
    READ_PATH = "read_path"  # 读路径非出站（甄别用）


@dataclass(frozen=True)
class DirectSendEntry:
    location: str
    api: str
    category: DirectSendCategory
    note: str = ""
    evidence: str = "v21-s0-inventory §2.4 / v21-risk-red-report 风险5"


@dataclass(frozen=True)
class TakeoverRegistry:
    matchers: tuple[MatcherEntry, ...]
    schedulers: tuple[SchedulerEntry, ...]
    route_groups: tuple[RouteGroupEntry, ...]
    direct_sends: tuple[DirectSendEntry, ...]

    @property
    def total_control_routes(self) -> int:
        return sum(group.route_count for group in self.route_groups)

    def summary(self) -> dict[str, int]:
        return {
            "matchers": len(self.matchers),
            "schedulers": len(self.schedulers),
            "control_route_groups": len(self.route_groups),
            "control_routes": self.total_control_routes,
            "direct_send_entries": len(self.direct_sends),
        }


def _m(*items: MatcherEntry) -> tuple[MatcherEntry, ...]:
    return tuple(items)


# --- 2026-09-26 席位 S-ORC-1 全册复锚（坐标活性门三红的修复批） ---------------------
# 现场：门 tests/test_outbound_registry_coordinate_liveness.py 三红，活账 (77,1,11)
# 对上限 (18,1,0)。根因＝S181（2026-09-24）之后多席持续向根装配文件插行（现算根
# 9979 行），登记册 77 枚声明坐标与 1 枚散文坐标整体顶漂，其中 11 枚指上空行。
# 本批处置：全部按符号名 AST 现算重锚（matcher=唯一注册赋值行、调度族=_register_*
# 的 FunctionDef.lineno 与 scheduler.add_job( 调用起始行、直发=在岗管线调用点行、读
# 路径=API 名字符串常量所在调用行）；预期复算回落 (18,1,0)＝上限本身，18 枚为 S181
# 已定的结构性 label-type 残余、1 枚散文为 group_poke/friend_poke 锚名不在装配块端点
# 行上（方法名字面量只存本表 POKE 映射，装配行无自证锚名）。上限与 AUDIT_HISTORY 一
# 字未动；逐枚差集表见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md。
# 另按主代理 2026-09-26 确证刷新非根坐标：file_gateway.py _deliver_onebot 356-412→578-634
# （S-T-FILE-2 邮件腿插入顶漂；同文件 deliver=535-562、_deliver_mail=678-776、stage=435-440
# 系 AST 现算复核值，仅 _deliver_onebot 两枚在册，其余未登记不动）。
# --- end S-ORC-1 ---

def build_default_takeover_registry() -> TakeoverRegistry:
    """A1 冻结清单（v21-s0-inventory §2，HEAD=56d1461）的结构化登记表。

    逐条对齐 A1 §2.1（50 matcher）/§2.2（12 调度族）/§2.3（62 路由）/
    §2.4（直发嫌疑 8 组+读路径甄别）。checklist 除已知事实外一律 "todo"，
    由接线席位补齐——不臆造未验证的幂等来源。
    """
    # --- 50 matcher（A1 §2.1 逐行誊录；priority 缺失处 None 如实） ---
    matchers = _m(
        MatcherEntry("status", "__init__.py:5187", "on_command", None, "status", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。2026-09-26 主代理需求 5 接线：根装配文件于 :9127 之后插入宿主机状态 matcher 块（+59 行），本批坐标整体顶漂 59，按同名注册赋值行 AST 现算重锚。"),
        MatcherEntry("auto_send", "__init__.py:5194", "on_message", 13, "auto_send", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。2026-09-26 主代理需求 5 接线：根装配文件于 :9127 之后插入宿主机状态 matcher 块（+59 行），本批坐标整体顶漂 59，按同名注册赋值行 AST 现算重锚。"),
        MatcherEntry("mail_control", "__init__.py:5195", "on_command", None, "mail", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("mail_notice", "__init__.py:5202", "on_message", 9, "mail", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("chat", "__init__.py:5203", "on_message", 50, "chat", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("meme", "__init__.py:5216", "on_message", 20, "meme", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("natural", "__init__.py:5217", "on_message", 45, "natural", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("meme_library", "__init__.py:5225", "on_message", 22, "meme_library", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("meme_absorb", "__init__.py:5227", "on_message", 10, "meme_absorb", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_upload_notice", "__init__.py:5379", "on_notice", 6, "group_upload", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("dirty_guard_matcher", "__init__.py:5400", "on_message", 3, "dirty_guard", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry(
            "campus_record_matcher",
            "__init__.py:5423",
            "on_message",
            8,
            "campus",
            note=(
                "U17-CAMPUS-WIRE 收编中央管线（测试规约已立，生产接线待落地）；"
                "坐标/priority 为 2026-09-20 同波审计实读刷新（matcher 真身 "
                "on_message(priority=8, block=False)）。"
                "2026-09-23 5248→5280→5312：慢回复先回执两度在根 __init__.py 装配段"
                "纯插入（第一次 32 行=注入两个 kwarg；第二次 32 行=投递口补"
                "\"入列后就地投递\"），把该行整体下移，非 campus 侧改动。"
                "2026-09-24 5312→5330：语音双发根修波在根 __init__.py 两处纯插入"
                "（should_finish_nonebot_matcher 补 QUEUED 拦截 +5 行；"
                "_record_transport_receipt 接 book_inline_unknown_parts +13 行），"
                "合计 18 行整体下移，非 campus 侧改动。"
                "2026-09-24 5330→5337：中央调度收编波 P5-E3 在根 sink 装配段纯插入 7 行"
                "（creation 预留面告警 sink 复用同一个 _push_probe_issue，不另造第二条"
                "告警路），非 campus 侧改动。"
                "2026-09-24 5337→5342：同波 P4-E2 层 2 feature 门收编在根装配段纯插入 5 行"
                "（1 行 import + 3 行注释 + 1 行 attach_default_feature_gate），"
                "S43 施工图 §3 已证「该改动无法零顶漂」；非 campus 侧改动。"
                "2026-09-24 5342→5345：同波 P2-E1 第二通路收编在装配块 `_build_weather_with_backend` "
                "之后纯插入 3 行（新增 `_build_news_with_backend`，别名/自然语言 6 处内联直呼改走 "
                "`_build_*_with_backend` 起装件＝行内等值替换净 0 行），非 campus 侧改动。"
                "2026-09-24 5345→5348：同批续刀再补 3 行 `_build_wiki_with_backend`，并把 eat 两处/"
                "affinity 一处（原五行内联装配）改走既有起装件 ⇒ 第二通路 19→8；非 campus 侧改动。"
                "2026-09-24 5356→5396：SEAT-S102-PATROL-WIRE 把 creation 缺位告警升为周期驱动，"
                "在根 sink 装配段（`install_execution_presence_probe` 之后）纯插入 40 行"
                "（一条 on_startup 后台巡检任务，复用同一个 `_push_probe_issue` sink 与 300s 抑制，"
                "零新 config 键、零第二条投递路）；S102 简报预测 ≈39，实落 +40，差 1 行为块内空行。"
                "另照实记一处账缺：note 链上一格停在 5348 而登记值为 5356，**5348→5356 那 +8 无注记**"
                "（非本批改动作造成，本批只对 5356→5396 负责）；归该门 owner 在安静窗按活体行考古补齐"
                "。2026-09-24 5396→5383：裁定 R-4（四条目投递路径只走统一管线）在根装配段"
                "**删除**行（净 −66 行，分三处），第一处位于新侧 4816 一带、净减 13 行，"
                "campus 在 4816 与 5971 之间 ⇒ 只吃这一段 = 整行上移 13；S151 按符号名"
                "`campus_record_matcher = on_message(` 重定位实测 5383（唯一命中）。"
                "另更正一处口径：随迁工单把该段估成 −12，实测 −13，本席取实测。"
                "2026-09-25 5383→5412：分句折一轮与限流补回波在根装配段纯插入 29 行"
                "（回执自适应探针 `_slowest_gateway_ema_ms` 含注释 26 行 + policy import"
                " 补 1 行 + RuntimePipeline 两个新 kwarg 2 行），全部落在 campus 之上"
                "的装配段；折句钩子本身落在聊天 handler 内（campus 之下，不参与顶漂），"
                "非 campus 侧改动。"
                "2026-09-25 5412→5416：SEAT-C（P14 ITEM 14/15）接手时按符号名现算"
                "`campus_record_matcher = on_message(` 已在 5416，登记值仍是 5412"
                "＝**继承的 4 行漂移**（前一批落根而未随迁的插入），非本席改动；"
                "本席自身在 5899 之下的装配段改码（跟戳候选表 + 主动戳人 require_group"
                " + 恰一臂），全部落在 campus 之下 ⇒ 本席净顶漂 0 行，只补继承账。"
            ),
        ),
        MatcherEntry("file_notice", "__init__.py:5676", "on_notice", 8, "file", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("poke_notice", "__init__.py:6194", "on_notice", 7, "poke", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("emoji_like_notice", "__init__.py:6321", "on_notice", 7, "emoji_like", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_increase_notice", "__init__.py:6354", "on_notice", 6, "group_increase", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_decrease_notice", "__init__.py:6355", "on_notice", 6, "group_decrease", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_admin_notice", "__init__.py:6356", "on_notice", 6, "group_admin", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("file_export", "__init__.py:6496", "on_message", 8, "file_export", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("image_search", "__init__.py:6570", "on_message", 46, "image_search", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry(
            "cookie_admin",
            "__init__.py:6633",
            "on_message",
            8,
            "cookie_admin",
            note=(
                "2026-09-24 5105→6213（S151 按符号名重锚）。归因照实记：登记值自 A1 冻结"
                "起就与真身差约 1100 行（HEAD 侧实证当时真身已在 6111，登记仍写 5105）"
                "＝本来就漂，不是 R-4 造成的；R-4 的 −13 位移只是把它从 mismatch 推成"
                "blank（空行账因 R-4 +1 的那一枚）。随迁工单 FOLLOW-R4 §5 要求"
                "「按符号名重定位 4816 之后受影响的条目」，故本席重锚到唯一命中 6213；"
                "主账因此 −1，其中含代改成分，不宣称为纯跟随账。"
            ),
        ),
        MatcherEntry("nickname_set", "__init__.py:6640", "on_message", 8, "nickname", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_file_stats", "__init__.py:6666", "on_message", 8, "group_file_stats", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("content", "__init__.py:7066", "on_message", 46, "content", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("music_mode", "__init__.py:7067", "on_message", 40, "music_mode", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("music", "__init__.py:7068", "on_message", 41, "music", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry(
            "today_history",
            "__init__.py:7069",
            "on_message",
            None,
            "today_history",
            note=(
                "2026-09-24 5529→6649（S151 按符号名重锚）。同 cookie_admin 一型："
                "登记值本来就漂约 1000 行（HEAD 侧真身已在 6567），R-4 的 −13 位移只是"
                "把它从 mismatch 推成 blank；本席按「重定位 4816 之后受影响条目」重锚，"
                "主账 −1 含代改成分。注意本族另有 scheduler:today_history 两枚坐标，"
                "那条本席未动。"
            ),
        ),
        MatcherEntry("wiki", "__init__.py:7072", "on_message", 41, "wiki", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("moegirl", "__init__.py:7073", "on_message", 41, "moegirl", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("moegirl_question", "__init__.py:7074", "on_message", None, "moegirl", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("epic", "__init__.py:7077", "on_message", 41, "epic", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("weather", "__init__.py:7078", "on_message", 41, "weather", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("market", "__init__.py:7079", "on_message", 41, "market", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("fx", "__init__.py:7085", "on_message", 41, "fx", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("stocks", "__init__.py:7086", "on_message", 42, "stocks", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("commodities", "__init__.py:7087", "on_message", 41, "commodities", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("bond", "__init__.py:7088", "on_message", 41, "bond", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("northbound", "__init__.py:7089", "on_message", 41, "northbound", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("divination", "__init__.py:7090", "on_message", 41, "divination", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("news", "__init__.py:7091", "on_message", 41, "news", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("randpic", "__init__.py:7092", "on_message", 41, "randpic", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("reminder", "__init__.py:7094", "on_message", 41, "reminder", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("daily_assist", "__init__.py:7095", "on_message", 42, "daily_assist", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("eat", "__init__.py:7096", "on_message", 41, "eat", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry(
            "subscribe_cmd",
            "__init__.py:7097",
            "on_message",
            12,
            "subscribe",
            note=(
                "2026-09-24 5551→6677（S151 按符号名重锚）。同 cookie_admin 一型：本来就"
                "漂约 1100 行（HEAD 侧真身已在 6595），R-4 的 −13 位移把它从 mismatch 推成"
                "blank；本席据随迁工单「重定位 4816 之后受影响的条目」重锚，主账 −1 含"
                "代改成分。相邻的 commodities（登记 5542）本席未动——它在 R-4 前就指空行，"
                "是纯存量账，交坐标活性门 owner。"
            ),
        ),
        MatcherEntry("affinity", "__init__.py:7107", "on_message", 41, "affinity", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("alias", "__init__.py:7117", "on_message", 10, "alias", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("group_info_matcher", "__init__.py:9007", "on_message", 41, "group_info", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。"),
        MatcherEntry("ignore_guide", "__init__.py:9154", "on_message", None, "ignore_guide", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。2026-09-26 S-CONSDISP 装配：根 :9175 处（host_state 块之后、审查 C-07 之前）纯插入 bot.consent matcher 三件套（净增 69 行），本坐标随之整体顶漂 +69，按同名注册赋值行 AST 现算重锚。"),
        MatcherEntry("media_archive", "__init__.py:9176", "on_message", 43, "media_archive", note="S181 2026-09-24 按符号名 AST 重锚：A1 冻结行号随根装配文件插删整体漂移，现锚唯一注册赋值行（<name> = on_message/on_command/on_notice），判 plausible。2026-09-26 S-ORC-1 复锚：S181 后多席向根装配文件插行致本批坐标整体顶漂（幅度逐枚见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-ORC-1.md 差集表），按同名注册赋值行 AST 现算重锚一次。2026-09-26 S-CONSDISP 装配：根 :9175 处（host_state 块之后、审查 C-07 之前）纯插入 bot.consent matcher 三件套（净增 69 行），本坐标随之整体顶漂 +69，按同名注册赋值行 AST 现算重锚。"),
    )

    # --- 12 调度族（A1 §2.2） ---
    def sched(
        family: str,
        register: str,
        jobs: tuple[str, ...],
        note: str = "",
    ) -> SchedulerEntry:
        return SchedulerEntry(
            family=family,
            register_location=register,
            add_job_locations=jobs,
            note=note,
        )

    schedulers = (
            # 2026-09-26 S-ORC-1 复锚：本批 24 枚根调度坐标按 AST 现算整体刷新——register 一律
            # 指 _register_*_scheduler 的 FunctionDef.lineno，add_job 一律指该族 scheduler.add_job(
            # 调用起始行，unattributed 两枚指不隶属任何 _register_*_scheduler 的自由 add_job 行。
            # 顶漂成因=S181 后多席向根装配文件插行；幅度逐枚见 S-ORC-1 报告差集表；余 18 枚
            # label-type mismatch 为结构性残余（锚名不在行上），与上限 (18,1,0) 的 18 对应。
            # S181 2026-09-24 续锚：全部 __init__.py 调度族坐标按符号名（AST）重定位到
            # 真身注册行——register 一律指 _register_<family>_scheduler 的定义行、add_job
            # 一律指该族 scheduler.add_job(...) 调用起始行。register 是否 plausible 取决于
            # 家族标签是否作为 token 出现在定义行（函数名内嵌家族 ⇒ plausible；
            # send_queue_worker/reminder_delivery 家族标签非函数名 token ⇒ 结构性 label-type
            # mismatch，按本门 docstring「锚名不可推」诚实留红，不去撞 id=字符串行刷 plausible）。
            # add_job 行皆为多行调用 `scheduler.add_job(`、家族标签在下一行参数 ⇒ 恒 label-type
            # mismatch（坐标已正确、判据按单行取不到家族 token）。逐枚见 SEAT-S181 §1.4/§1.5。
            sched(
                "send_queue_worker", "__init__.py:1622", ("__init__.py:1674",),
                "发送队列 worker；dedupe_key 幂等已内建（SQLite part 级）。"
                "S181 2026-09-24 register 校正到 _register_send_queue_scheduler 定义行（真身）；"
                "家族标签 send_queue_worker 非该函数名 token ⇒ register/add_job 均 label-type"
                " mismatch（坐标正确、锚名不可推，非懒锚）。",
            ),
            sched(
                "credential_check", "__init__.py:1692", ("__init__.py:1789",),
                "S181 2026-09-24 register 重锚 _register_credential_check_scheduler（名内嵌家族⇒"
                "plausible）；add_job 校正到真 scheduler.add_job 行⇒label-type mismatch。",
            ),
            sched(
                "today_history", "__init__.py:1805", ("__init__.py:1887", "__init__.py:1923"),
                "含 job 重排。S181 2026-09-24 register 重锚 _register_today_history_scheduler"
                "（家族 token 在场⇒plausible）；两枚 add_job 坐标校正到真身，label-type mismatch。"
                "另注：在册另有 matcher:today_history 一枚，与调度族非同一坐标。",
            ),
            sched(
                "kb_wiki_sync", "__init__.py:1944", ("__init__.py:1988", "__init__.py:2004"),
                "S181 2026-09-24 register 重锚 _register_kb_wiki_sync_scheduler（家族 token⇒plausible）；"
                "add_job 坐标校正到真身，label-type mismatch。",
            ),
            sched(
                "reflection", "__init__.py:2821", ("__init__.py:2860", "__init__.py:2875"),
                "S181 2026-09-24 register 重锚 _register_reflection_scheduler（家族 token⇒plausible）；"
                "add_job 原 2643 指空行、校正到真 scheduler.add_job 行 2853（消空行账），"
                "两枚 add_job 均 label-type mismatch。",
            ),
            sched(
                "reminder_delivery", "__init__.py:3183", ("__init__.py:3214",),
                "S181 2026-09-24 register 校正到 _register_reminder_scheduler 定义行（真身）；"
                "家族标签 reminder_delivery 全根 0 命中、亦非该函数名 token ⇒ label-type"
                " mismatch（结构上无法按符号自证，交 owner 定夺家族正名，本席不臆造）。",
            ),
            sched(
                "digest_push", "__init__.py:3331", ("__init__.py:3367",),
                "S181 2026-09-24 register 重锚 _register_digest_push_scheduler（家族 token⇒plausible）；"
                "add_job 坐标校正到真 scheduler.add_job 行 3360，label-type mismatch。",
            ),
            sched(
                "daily_assist", "__init__.py:3608",
                ("__init__.py:3635", "__init__.py:3657", "__init__.py:3677"),
                "S181 2026-09-24 register 重锚 _register_daily_assist_scheduler（家族 token⇒plausible）；"
                "三枚 add_job（餐/早/晚报）坐标校正到真身 scheduler.add_job 行，label-type mismatch。",
            ),
            sched(
                "model_schedule", "domains/chat_reply/llm_engine/model_schedule.py:133", ("domains/chat_reply/llm_engine/model_schedule.py:162",),
            ),
            sched(
                "usage_monitor", "domains/ops/monitor/usage_monitor.py:396",
                ("domains/ops/monitor/usage_monitor.py:656", "domains/ops/monitor/usage_monitor.py:674"),
            ),
            sched(
                "subscription_poll", "sources/subscription_runtime_v2.py:module",
                ("sources/subscription_runtime_v2.py:40", "sources/subscription_runtime_v2.py:49"),
            ),
            sched(
                "unattributed_bare_add_jobs", "__init__.py:4807,4870",
                ("__init__.py:4807", "__init__.py:4870"),
                "A1 §2.2：用途 unknown——接管调度面前必须先定位。S181 2026-09-24 续锚：原登记 4027/4082"
                " 已随根插删失效（A1 -era 存量死号），按 AST 现算校正为当下**不隶属任何 _register_*_scheduler"
                " 的自由 add_job 调用行** 4775（_channel_health_job）与 4838（_cookie_expiry_reminder_job）；"
                "家族标签 unattributed_bare_add_jobs 全根 0 命中、亦非任何函数名 token ⇒ 三枚坐标（register＋两"
                "add_job）均 label-type mismatch（坐标正确、锚名不可推）。是否应拆成具名调度族属语义裁决，"
                "交该门 owner，本席不臆造。",
            ),
        )

    # --- 控制面路由组（A1 §2.3；62 条按组计数，明细以 A1 冻结粒度为准） ---
    route_groups = (
            RouteGroupEntry(
                module="control_plane/api/v1.py",
                prefix="/api/v1",
                route_count=28,
                members=(
                    "/protocol", "/openapi.json",
                    "/features", "/features/tree", "/features/{id}", "/features/{id}/children",
                    "/features/state", "/features/preview", "/features/enable",
                    "/features/disable", "/features/reset", "/features/audit",
                    "/config/schema", "/config/changes", "/config/{key}",
                    "/config/{key}/preview", "/config/{key}/set", "/config/{key}/reset",
                    "/logs", "/logs/sources",
                    "/metrics/resources", "/metrics/overview", "/metrics/models",
                    "/metrics/sessions", "/metrics/tokens", "/metrics/trends",
                    "/traces",
                ),
                note="A1 分组清单可枚举 27/28；缺额 1 条为 A1 未冻结明细，不臆造",
            ),
            RouteGroupEntry(
                module="control_plane/api/workspaces.py",
                prefix="/api/v1/workspaces",
                route_count=10,
                members=(
                    "GET /workspaces", "POST /workspaces", "GET /workspaces/{id}",
                    "DELETE /workspaces/{id}", "GET /workspaces/{id}/messages",
                    "POST /workspaces/{id}/messages", "POST /workspaces/{id}/reset",
                    "POST /workspaces/{id}/preview", "POST /workspaces/{id}/send",
                    "GET /workspaces/{id}/audit",
                ),
                note="/send 为模拟发送；绝不触达生产 SendQueue 属红线，接管时验证",
            ),
            RouteGroupEntry(
                module="control_plane/api/llm.py",
                prefix="/api/v1/llm",
                route_count=9,
                members=(
                    "GET /llm/providers", "PUT /llm/providers",
                    "GET /llm/channels", "PUT /llm/channels",
                    "GET /llm/models", "PUT /llm/models",
                    "GET /llm/health", "GET /llm/routes", "POST /llm/routes/preview",
                ),
            ),
            RouteGroupEntry(
                module="control_plane/api/actions.py",
                prefix="/api/v1/actions",
                route_count=7,
                members=(
                    "GET /actions", "GET /actions/runs", "GET /actions/runs/{id}",
                    "POST /actions/runs/{id}/cancel", "GET /actions/{id}",
                    "POST /actions/{id}/preview", "POST /actions/{id}/execute",
                ),
            ),
            RouteGroupEntry(
                module="control_plane/api/health.py",
                prefix="/admin/api/v1",
                route_count=4,
                members=("GET /healthz", "GET /health", "GET /status/bot", "GET /status/models"),
            ),
            RouteGroupEntry(
                module="control_plane/api/events.py",
                prefix="/api/v1/logs",
                route_count=4,
                members=("GET /logs/events", "GET /logs/sources", "GET /logs/stream", "GET /logs/events/{event_id}"),
            ),
            RouteGroupEntry(
                module="control_plane/api/platform.py",
                prefix="(动态 APIRouter)",
                route_count=0,
                members=(),
                note="A1 §2.3：动态注册未枚举（unknown）；OpenAPI 实际面以 /protocol 实跑为准",
            ),
        )

    # --- 直发出站嫌疑点（A1 §2.4 + 风险5 坐标复核；v21r4-b S0-COLLECT+REG-REFRESH） ---
    # 根 __init__.py 四处曾由 S0-ROOT-c（2026-09-19）收编为 *_via_queue 门开分支
    # （方案形态 B/A/A/D；门缺省 False=门关旧直连逐字节等价，重启不拨门=零变更）。
    # 2026-09-24 裁定 R-4 把「关态走旧直连」这第二条路连开关一并从生产根删净 ⇒ 前四枚
    # 嫌疑点全部改判 ABSORBED（S174 现算：B 类直发尺全域零命中 + 按名定位后继调用点，
    # 逐枚坐标与原因写在各条 note 里）。坐标口径同批由「门关分支行号」改为
    # 「唯一后继投递调用点行号」，锚名同步换成在岗符号——旧行号是已删分支的散文死号。
    direct_sends = (
            DirectSendEntry(
                "__init__.py:4855",
                "send_private_msg → _deliver_cookie_expiry_report_via_queue",
                DirectSendCategory.ABSORBED,
                "cookie 到期提醒投递口——**已收编**（裁定 R-4「走管线，全部统一」；S174 "
                "2026-09-24T07:29:14Z 现算改判）。前态：S0-ROOT-c 2026-09-19 收编为 "
                "bot_cookie_expiry_reminder_via_queue 门开分支，门缺省 False 时仍走"
                "逐管理员 send_private_msg 直发＝第二条路仍在岗（#49 已披露「在册未执法」）。"
                "R-4 把该开关与其下的直发分支一并从生产根删除（四枚 *_via_queue 键在 "
                "config.py 零命中），此族投递只剩 "
                "_deliver_cookie_expiry_report_via_queue（SendRequest→SendQueue→内联投递，"
                "dedupe 带本地日期=当日幂等，SENT 才算送达）一条路。旧登记坐标 4440-4444"
                "（含 S0-COLLECT 更早快照 4300）现指「邮件别名未接通」与掉线通知装配行＝"
                "已删分支的散文死号，故坐标改指本族唯一后继调用点 4823（该函数真身 def "
                "3067-3177；全根按名现算仅此一处调用）。2026-09-26 S-ORC-1 按 AST Call 行复锚至 4855（S181 后多席根插行顶漂 +32）。测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（4440-4444）→S174 2026-09-24 AST 现算：B 类直发唯一尺 "
                "scan_send_bypasses(plugins/bot_unified_runtime) 全域零命中，"
                "按名 ast.walk 定位后继调用点 4823",
            ),
            DirectSendEntry(
                "__init__.py:6393",
                "send_group_msg → _send_text_through_unified_pipeline",
                DirectSendCategory.ABSORBED,
                "入群欢迎 notice handler 投递口——**已收编**（裁定 R-4；S174 "
                "2026-09-24T07:29:14Z 现算补全改判，坐标由 S151 2026-09-24 先行重锚）。"
                "前态：S0-ROOT-c 2026-09-19 收编为 bot_group_welcome_via_queue 门开分支，"
                "门缺省 False 时走 call_api 直发；R-4 把该「关态走直发」的第二条路与开关"
                "一并退役（根 5971-5975 注释留痕），欢迎语只剩 "
                "_send_text_through_unified_pipeline（capability_id=bot.group_welcome，"
                "SENT/REDIRECTED 才记 group_welcome_sent）一条路。旧登记坐标 5378-5382 的"
                "直发块本体已被删除，故坐标改指唯一后继调用点 5977（capability 行 5981）。"
                "本条 api 现同时点名历史平台方法与被收编进的统一管线函数——后者才是**在岗**"
                "锚名：send_group_msg 字面量在根文件 AST 判据下命中 0 次，只按它锚定则活性门"
                "永判 mismatch（S151 已如实记下这笔），按符号名锚定＝本门注释的诚实路径①。"
                "2026-09-26 S-ORC-1 按 AST Call 行复锚至 6389（S181 后多席根插行顶漂 +412）。"
                "测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（5378-5382，该块已随 R-4 删除）→S151 2026-09-24 按符号 grep "
                "_send_text_through_unified_pipeline + capability_id=bot.group_welcome 重定位"
                "→S174 2026-09-24 AST 现算改判 ABSORBED 并把锚名换成在岗符号",
            ),
            DirectSendEntry(
                "__init__.py:6704",
                "send_group_msg + send_private_msg → _send_parts_through_unified_pipeline",
                DirectSendCategory.ABSORBED,
                "cookie 登录二维码图片（群/私聊双通道）投递口——**已收编**（裁定 R-4；"
                "S174 2026-09-24T07:29:14Z 现算改判）。前态：S0-ROOT-c 2026-09-19 收编为 "
                "bot_cookie_qr_via_queue 门开分支（mixed 件 text=\"\"+image=file:///，"
                "audit_tags=cookie_login_qr），门缺省 False 时走 group/private 二分支 "
                "call_api 直发；R-4 删二分支与开关（根 6278-6282 注释留痕：第二通路不该以"
                "「缺省关」的名义留在树上）。旧登记坐标 5730-5740 现指 meme 图库 nsfw 参数"
                "与回戳形参行＝散文死号，改指唯一后继调用点 6284（audit_tags 行 6289、"
                "capability_id=bot.cookie_login 行 6290；api 锚名同理换成在岗符号，见上一条；2026-09-26 S-ORC-1 按 AST Call 行复锚至 6716，顶漂 +432）。"
                "测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（5730-5740）→S174 2026-09-24 AST 现算：直发尺全域零命中，"
                "按名定位后继调用点 6284",
            ),
            DirectSendEntry(
                "__init__.py:6540",
                "upload_group_file + upload_private_file → _send_files_through_unified_pipeline",
                DirectSendCategory.ABSORBED,
                "文档导出上传投递口（原登记缺口补齐项）——**已收编**（裁定 R-4 + 裁项 5；"
                "S174 2026-09-24T07:29:14Z 现算改判）。前态：S0-ROOT-c 2026-09-19 收编为 "
                "bot_file_export_via_queue 门开分支（CapabilityResult.files→"
                "FileTransferGateway 既有链），门缺省 False 时走 call_api 直传二分支；"
                "R-4 删二分支与开关（根 6098-6102 注释留痕），平台方法面与直连一致"
                "（群 upload_group_file / 私聊 upload_private_file 由通道本体解析）。"
                "旧登记坐标 5526-5538 现指紧急信息域装配行（build_review_gate / "
                "source=emergency_source）＝散文死号，改指唯一后继调用点 6104"
                "（capability_id=bot.file 行 6108；该函数在根内仅此一处调用；2026-09-26 S-ORC-1 按 AST Call 行复锚至 6536，顶漂 +432）。"
                "测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（5526-5538）→S174 2026-09-24 AST 现算：直发尺全域零命中，"
                "按名定位后继调用点 6104",
            ),
            DirectSendEntry(
                "__init__.py:5411", "delete_msg",
                DirectSendCategory.BY_DESIGN,
                "撤回（dirty guard），非消息投递。S181 2026-09-24 续锚：原登记 4978 已随根插删漂移，"
                "按符号 delete_msg 现算唯一命中＝撤回调用行 5371（await bot.call_api delete_msg）⇒ plausible。2026-09-26 S-ORC-1 复锚 5407（多席根插行顶漂 +36，撤回调用行现算唯一命中）。",
                "v21-risk-red-report 风险5（REG-REFRESH 2026-09-19 复核现坐标 :4978；"
                "原登记 :4569→S0-COLLECT 观测 :4802 均已漂移→S181 2026-09-24 按符号 AST 重锚 5371）",
            ),
            DirectSendEntry(
                "control_plane/dispatcher.py:162-220", "group_poke / friend_poke",
                DirectSendCategory.BY_DESIGN,
                "回戳 v2（by-design 副作用）——已收编（L34）：直连点已不存在，"
                "经 OutboundSideEffectExecutor 统一出站面（cancel 闸→准入复验→租约"
                "线性化→Transport 固定映射解析方法名→call_api 通道本体）；装配 "
                "__init__.py:5683-5750；方法名字面量仅存本表 POKE 映射（绝不拼接）",
                "v21-risk-red-report 风险5（原直连坐标 :4745,4751 已随 L34 收编消失；"
                "REG-REFRESH 2026-09-19 grep 实证根 __init__.py 零 group_poke/"
                "friend_poke 直连）",
            ),
            DirectSendEntry(
                "domains/meme/reactions/engine.py:754-782", "set_msg_emoji_like",
                DirectSendCategory.BY_DESIGN,
                "贴表情旁路（by-design 副作用）——已收编（L35）：react_to_message 经 "
                "_REACTION_OUTBOUND_EXECUTOR（engine.py:664）统一出站面，方法名由 "
                "Transport 固定映射解析，失败静默语义保持；runtime/reactions.py 旧"
                "路径现为 compat shim（真身本路径）",
                "v21-risk-red-report 风险5（原登记 runtime/reactions.py:652-655 系 "
                "shim 旧路径；REG-REFRESH 2026-09-19 实读 engine.py 真身）",
            ),
            DirectSendEntry(
                "domains/meme/reactions/engine.py:785-813", "set_message_reaction",
                DirectSendCategory.BY_DESIGN,
                "TG reaction（docstring 自述未接线触发点，预留可选接线）——出站面已"
                "统一：react_telegram_message 经同一 executor（Transport 固定映射）",
                "v21-risk-red-report 风险5（原登记 runtime/reactions.py:681-686 系 "
                "shim 旧路径；REG-REFRESH 2026-09-19 实读 engine.py 真身）",
            ),
            DirectSendEntry(
                "domains/transport/sender/file_gateway.py:578-634", "call_api",
                DirectSendCategory.CHANNEL_BODY,
                "统一文件出站路径通道本体（FileTransferGateway._deliver_onebot 上传内环："
                "getattr(bot, api) 优先、退化 call_api、retcode 拒绝→upload_rejected）；"
                "onebot.py 文件部件分支统一经 get_default_file_gateway().stage→deliver 消费，"
                "生产侧无绕行实例；原 PENDING_RULING 依 DIRECT-PLAN §二④ 裁定建议改判，"
                "final 归 DELIVERY-001 owner 复核",
                "v21r4-b S0-COLLECT 2026-09-18 实读：旧坐标 sender/file_gateway.py:382 "
                "系 reorg 前 shim 路径（旧路径现为 3 行 compat shim）",
            ),
            DirectSendEntry(
                "sender/onebot.py:444,449,469,477,546,554,583,588,962",
                "send_*_msg / call_api",
                DirectSendCategory.CHANNEL_BODY, "SendQueue worker 合法通道本体，非绕行",
            ),
            # 读路径甄别（非出站；group_info.py:146 通用透传单列审计）
            DirectSendEntry(
                "capabilities/group_info.py:146", "call_api",
                DirectSendCategory.READ_PATH,
                "通用 call_api 透传 sink，动作面宽——DISPATCH-001 单列审计",
            ),
            DirectSendEntry(
                "__init__.py:521,1057,1153,2248,6463,6467 + runtime/video_pipeline.py:72,74 + sources/telegram_media.py:133",
                "get_forward_msg/get_record/get_stranger_info/get_file/download_file/get_msg",
                DirectSendCategory.READ_PATH,
                "读路径，非出站（A1 §2.4 甄别保留）。S181 2026-09-24 续锚：原登记"
                " 949/1014/2059/4924/4928/7468 已随根插删漂移，按六个读 API 符号（get_msg/"
                "get_forward_msg/get_record/get_stranger_info/get_file/download_file）现算校正为"
                "各真身 call_api/getattr 调用行 518/1054/1150/2245/6027/6031（排除同名注释/文档行，"
                "只取真实调用点）⇒ 六锚名皆在其行上＝plausible。2026-09-26 S-ORC-1 复锚六枚＝521/1057/1153/2248/6459/6463（多席根插行顶漂；get_msg/get_forward_msg/get_record/get_stranger_info 段 +3，get_file/download_file 段 +432；六枚均取字符串常量所在真实调用行）。",
            ),
        )

    return TakeoverRegistry(
        matchers=matchers,
        schedulers=schedulers,
        route_groups=route_groups,
        direct_sends=direct_sends,
    )
